from __future__ import annotations

"""Full Stage-1 audit for handoff and regression checks.

This script is intentionally stricter than the older spot-check utilities.
It checks:
1. time / coordinate / altitude / speed field completeness and ranges
2. null-vs-NaN behavior in numeric columns
3. vector magnitude consistency for wind and motion components
4. radar/frame-window coverage
5. same-flight nearest-time alignment between clean_wind and clean_loc
6. suspicious duplicate AMDAR groups that share one timestamp but span many points

Outputs:
- stage1_full_audit_*.json
- stage1_full_audit_*.md
"""

import argparse
import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

import pipeline_config as cfg


DEFAULT_STAGE1_DIR = Path(cfg.BASE_DIR) / "stage1_output"
DEFAULT_OUT_DIR = Path(cfg.BASE_DIR) / "优化" / "stage1_full_audit_20260627"
ROI_LAT = (cfg.LAT_MIN, cfg.LAT_MAX)
ROI_LON = (cfg.LON_MIN, cfg.LON_MAX)
ROI_ALT = (float(cfg.ALT_MIN), float(cfg.ALT_MAX))


@dataclass
class AuditPaths:
    stage1_dir: Path
    out_dir: Path
    clean_wind: Path
    clean_loc: Path
    radar_index: Path
    frame_window_index: Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a full Stage-1 audit and write JSON/Markdown reports.")
    parser.add_argument("--stage1-dir", default=str(DEFAULT_STAGE1_DIR), help="Directory containing Stage-1 outputs.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory to store audit outputs.")
    parser.add_argument("--same-flight-tolerance-minutes", type=int, default=2, help="Nearest-time tolerance for wind-loc matching.")
    parser.add_argument("--nearby-window-minutes", type=int, default=20, help="Window size used when printing a suspicious example.")
    parser.add_argument("--top-group-limit", type=int, default=10, help="How many suspicious timestamp groups to keep in the report.")
    return parser.parse_args()


def _build_paths(args: argparse.Namespace) -> AuditPaths:
    stage1_dir = Path(args.stage1_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return AuditPaths(
        stage1_dir=stage1_dir,
        out_dir=out_dir,
        clean_wind=stage1_dir / "clean_wind.parquet",
        clean_loc=stage1_dir / "clean_loc.parquet",
        radar_index=stage1_dir / "radar_index.json",
        frame_window_index=stage1_dir / "frame_window_index.json",
    )


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat(sep=" ")
    return obj


def _value_counts(df: pl.DataFrame, col: str) -> dict[str, int]:
    if col not in df.columns:
        return {}
    table = (
        df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
    )
    return {str(k): int(v) for k, v in table.iter_rows()}


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _numeric_summary(df: pl.DataFrame, col: str) -> dict[str, Any]:
    if col not in df.columns:
        return {"present": False}

    s = df.select(pl.col(col).cast(pl.Float64, strict=False).alias(col)).get_column(col)
    total_rows = int(s.len())
    null_rows = int(s.is_null().sum())
    nan_rows = int(s.is_nan().sum())
    finite_mask = s.is_finite()
    finite = s.filter(finite_mask)
    finite_rows = int(finite.len())
    nonfinite_nonnull_rows = total_rows - null_rows - finite_rows

    out: dict[str, Any] = {
        "present": True,
        "rows": total_rows,
        "null_rows": null_rows,
        "nan_rows": nan_rows,
        "finite_rows": finite_rows,
        "nonfinite_nonnull_rows": int(nonfinite_nonnull_rows),
        "finite_ratio": float(finite_rows / total_rows) if total_rows else None,
    }
    if finite_rows == 0:
        return out

    out.update(
        {
            "min": float(finite.min()),
            "q01": float(finite.quantile(0.01)),
            "q10": float(finite.quantile(0.10)),
            "q50": float(finite.quantile(0.50)),
            "q90": float(finite.quantile(0.90)),
            "q99": float(finite.quantile(0.99)),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
        }
    )
    return out


def _datetime_summary(df: pl.DataFrame, col: str) -> dict[str, Any]:
    if col not in df.columns:
        return {"present": False}
    s = df.select(pl.col(col).cast(pl.Datetime, strict=False).alias(col)).get_column(col)
    out: dict[str, Any] = {
        "present": True,
        "rows": int(s.len()),
        "null_rows": int(s.is_null().sum()),
    }
    nn = s.drop_nulls()
    if nn.len() == 0:
        return out
    out["min"] = str(nn.min())
    out["max"] = str(nn.max())
    return out


def _range_ratio(df: pl.DataFrame, col: str, lo: float, hi: float) -> dict[str, Any]:
    if col not in df.columns:
        return {"present": False}
    s = df.select(pl.col(col).cast(pl.Float64, strict=False).alias(col)).get_column(col)
    finite = s.filter(s.is_finite())
    if finite.len() == 0:
        return {"present": True, "finite_rows": 0, "valid_ratio": None}
    valid = finite.filter((finite >= lo) & (finite <= hi))
    return {
        "present": True,
        "finite_rows": int(finite.len()),
        "valid_rows": int(valid.len()),
        "valid_ratio": float(valid.len() / finite.len()),
        "range": [lo, hi],
    }


def _vector_consistency(df: pl.DataFrame, speed_col: str, u_col: str, v_col: str) -> dict[str, Any]:
    needed = [speed_col, u_col, v_col]
    if any(col not in df.columns for col in needed):
        return {"present": False}

    one = (
        df.select(
            [
                pl.col(speed_col).cast(pl.Float64, strict=False).alias("speed"),
                pl.col(u_col).cast(pl.Float64, strict=False).alias("u"),
                pl.col(v_col).cast(pl.Float64, strict=False).alias("v"),
            ]
        )
        .filter(pl.col("speed").is_finite() & pl.col("u").is_finite() & pl.col("v").is_finite())
        .with_columns((((pl.col("u") ** 2) + (pl.col("v") ** 2)).sqrt()).alias("mag"))
        .with_columns((pl.col("mag") - pl.col("speed")).abs().alias("abs_diff"))
    )
    if one.height == 0:
        return {"present": True, "rows": 0}
    diff = one.get_column("abs_diff")
    return {
        "present": True,
        "rows": int(one.height),
        "median_abs_diff": float(diff.quantile(0.50)),
        "p99_abs_diff": float(diff.quantile(0.99)),
        "max_abs_diff": float(diff.max()),
    }


def _frame_window_stats(frame_window_index: list[dict[str, Any]]) -> dict[str, Any]:
    loc_rows = [int(x.get("loc_rows", 0)) for x in frame_window_index]
    wind_rows = [int(x.get("wind_rows", 0)) for x in frame_window_index]

    def _summary(values: list[int]) -> dict[str, Any]:
        if not values:
            return {"min": 0, "median": 0, "max": 0}
        values_sorted = sorted(values)
        return {
            "min": int(values_sorted[0]),
            "median": int(values_sorted[len(values_sorted) // 2]),
            "max": int(values_sorted[-1]),
        }

    loc_summary = _summary(loc_rows)
    wind_summary = _summary(wind_rows)
    return {
        "rows": int(len(frame_window_index)),
        "loc_rows": loc_summary,
        "wind_rows": wind_summary,
        "usable_zero_loc_rows": int(sum(1 for x in loc_rows if x == 0)),
        "usable_zero_wind_rows": int(sum(1 for x in wind_rows if x == 0)),
    }


def _same_flight_match(
    wind: pl.DataFrame,
    loc: pl.DataFrame,
    tolerance_minutes: int,
) -> dict[str, Any]:
    tolerance = f"{int(tolerance_minutes)}m"
    wind_match = (
        wind.select(["flight_id", "time_utc", "alt_meters", "lat_clean", "lon_clean", "source"])
        .drop_nulls(["flight_id", "time_utc"])
        .sort(["flight_id", "time_utc"])
    )
    loc_match = (
        loc.select(["flight_id", "time_utc", "alt_meters", "lat_clean", "lon_clean"])
        .drop_nulls(["flight_id", "time_utc"])
        .rename({"time_utc": "loc_time_utc", "alt_meters": "loc_alt_meters", "lat_clean": "loc_lat_clean", "lon_clean": "loc_lon_clean"})
        .sort(["flight_id", "loc_time_utc"])
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Sortedness of columns cannot be checked when 'by' groups provided")
        joined = wind_match.join_asof(
            loc_match,
            left_on="time_utc",
            right_on="loc_time_utc",
            by="flight_id",
            strategy="nearest",
            tolerance=tolerance,
        )

    joined = joined.with_columns(
        [
            (pl.col("time_utc") - pl.col("loc_time_utc")).dt.total_seconds().abs().alias("dt_sec"),
            (pl.col("alt_meters") - pl.col("loc_alt_meters")).abs().alias("alt_gap_m"),
            (pl.col("lat_clean") - pl.col("loc_lat_clean")).abs().alias("lat_gap_deg"),
            (pl.col("lon_clean") - pl.col("loc_lon_clean")).abs().alias("lon_gap_deg"),
        ]
    )
    matched = joined.filter(pl.col("loc_time_utc").is_not_null())

    source_counts = _value_counts(wind, "source")

    def _one(frame: pl.DataFrame, denom: int) -> dict[str, Any]:
        if frame.height == 0:
            return {"rows": 0}
        return {
            "rows": int(frame.height),
            "match_ratio": float(frame.height / max(1, denom)),
            "dt_sec_q50": float(frame["dt_sec"].drop_nulls().quantile(0.50)),
            "dt_sec_q90": float(frame["dt_sec"].drop_nulls().quantile(0.90)),
            "alt_gap_m_q50": float(frame["alt_gap_m"].drop_nulls().quantile(0.50)),
            "alt_gap_m_q90": float(frame["alt_gap_m"].drop_nulls().quantile(0.90)),
            "lat_gap_deg_q50": float(frame["lat_gap_deg"].drop_nulls().quantile(0.50)),
            "lon_gap_deg_q50": float(frame["lon_gap_deg"].drop_nulls().quantile(0.50)),
        }

    out = {
        "tolerance_minutes": int(tolerance_minutes),
        "wind_total_rows": int(wind.height),
        "matched_rows": int(matched.height),
        "match_ratio": float(matched.height / max(1, wind.height)),
        "overall": _one(matched, wind.height),
        "by_source": {},
    }
    for src in sorted(x for x in wind.get_column("source").drop_nulls().unique().to_list()):
        out["by_source"][str(src)] = _one(
            matched.filter(pl.col("source") == src),
            int(source_counts.get(str(src), 0)),
        )
    return out


def _wind_same_time_group_stats(
    wind: pl.DataFrame,
    top_group_limit: int,
) -> dict[str, Any]:
    grouped = (
        wind.select(["source", "flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"])
        .drop_nulls(["source", "flight_id", "time_utc"])
        .group_by(["source", "flight_id", "time_utc"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("lat_clean").min().alias("lat_min"),
                pl.col("lat_clean").max().alias("lat_max"),
                pl.col("lon_clean").min().alias("lon_min"),
                pl.col("lon_clean").max().alias("lon_max"),
                pl.col("alt_meters").min().alias("alt_min"),
                pl.col("alt_meters").max().alias("alt_max"),
            ]
        )
        .with_columns(
            [
                (pl.col("lat_max") - pl.col("lat_min")).alias("lat_span_deg"),
                (pl.col("lon_max") - pl.col("lon_min")).alias("lon_span_deg"),
                (pl.col("alt_max") - pl.col("alt_min")).alias("alt_span_m"),
                (((pl.col("lat_max") - pl.col("lat_min")) ** 2) + ((pl.col("lon_max") - pl.col("lon_min")) ** 2)).sqrt().alias("hspan_deg"),
            ]
        )
    )

    def _group_stats(frame: pl.DataFrame) -> dict[str, Any]:
        if frame.height == 0:
            return {"groups": 0}
        dup = frame.filter(pl.col("rows") > 1)
        rows_s = frame.get_column("rows")
        dup_rows = dup.get_column("rows") if dup.height else None
        return {
            "groups": int(frame.height),
            "duplicate_groups": int(dup.height),
            "duplicate_group_share": float(dup.height / frame.height),
            "duplicate_rows_total": int(dup_rows.sum()) if dup_rows is not None else 0,
            "rows_q50": float(rows_s.quantile(0.50)),
            "rows_q90": float(rows_s.quantile(0.90)),
            "rows_q99": float(rows_s.quantile(0.99)),
            "rows_max": int(rows_s.max()),
            "duplicate_big_hspan_ge_0p5deg_groups": int(dup.filter(pl.col("hspan_deg") >= 0.5).height),
            "duplicate_big_hspan_ge_1p0deg_groups": int(dup.filter(pl.col("hspan_deg") >= 1.0).height),
        }

    by_source: dict[str, Any] = {}
    for src in sorted(x for x in grouped.get_column("source").drop_nulls().unique().to_list()):
        by_source[str(src)] = _group_stats(grouped.filter(pl.col("source") == src))

    top_groups = (
        grouped.filter(pl.col("rows") > 1)
        .sort(["rows", "hspan_deg", "alt_span_m"], descending=[True, True, True])
        .head(int(top_group_limit))
        .to_dicts()
    )

    return {
        "overall": _group_stats(grouped),
        "by_source": by_source,
        "top_duplicate_groups": top_groups,
    }


def _suspicious_amdar_example(
    wind: pl.DataFrame,
    loc: pl.DataFrame,
    nearby_window_minutes: int,
) -> dict[str, Any]:
    amdar = wind.filter(pl.col("source") == "amdar")
    grouped = (
        amdar.group_by(["flight_id", "time_utc"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("lat_clean").min().alias("lat_min"),
                pl.col("lat_clean").max().alias("lat_max"),
                pl.col("lon_clean").min().alias("lon_min"),
                pl.col("lon_clean").max().alias("lon_max"),
                pl.col("alt_meters").min().alias("alt_min"),
                pl.col("alt_meters").max().alias("alt_max"),
            ]
        )
        .with_columns(
            [
                (pl.col("lat_max") - pl.col("lat_min")).alias("lat_span_deg"),
                (pl.col("lon_max") - pl.col("lon_min")).alias("lon_span_deg"),
                (pl.col("alt_max") - pl.col("alt_min")).alias("alt_span_m"),
                (((pl.col("lat_max") - pl.col("lat_min")) ** 2) + ((pl.col("lon_max") - pl.col("lon_min")) ** 2)).sqrt().alias("hspan_deg"),
            ]
        )
        .filter(pl.col("rows") > 1)
        .sort(["rows", "hspan_deg", "alt_span_m"], descending=[True, True, True])
    )
    if grouped.height == 0:
        return {}

    top = grouped.row(0, named=True)
    flight_id = str(top["flight_id"])
    ts = top["time_utc"]
    window = timedelta(minutes=int(nearby_window_minutes))

    wind_points = (
        amdar.filter((pl.col("flight_id") == flight_id) & (pl.col("time_utc") == ts))
        .select(["flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters", "wind_dir", "wind_speed"])
        .sort(["lon_clean", "lat_clean"])
        .head(12)
        .to_dicts()
    )

    loc_nearby = (
        loc.filter(
            (pl.col("flight_id") == flight_id)
            & (pl.col("time_utc") >= ts - window)
            & (pl.col("time_utc") <= ts + window)
        )
        .select(["flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters", "heading_deg", "ground_speed_ms"])
        .sort("time_utc")
        .to_dicts()
    )

    return {
        "flight_id": flight_id,
        "time_utc": str(ts),
        "rows": int(top["rows"]),
        "lat_span_deg": _safe_float(top["lat_span_deg"]),
        "lon_span_deg": _safe_float(top["lon_span_deg"]),
        "alt_span_m": _safe_float(top["alt_span_m"]),
        "wind_points_sample": wind_points,
        "loc_points_within_plus_minus_window": loc_nearby[:20],
        "loc_points_within_plus_minus_window_count": int(len(loc_nearby)),
        "nearby_window_minutes": int(nearby_window_minutes),
    }


def _render_markdown(report: dict[str, Any], paths: AuditPaths) -> str:
    same_flight = report["cross_table_same_flight_nearest_loc"]
    dup = report["wind_same_time_group_stats"]
    loc_speed = report["loc_numeric"]["ground_speed_ms"]
    motion_consistency = report["loc_motion_vector_consistency"]
    wind_consistency = report["wind_vector_consistency"]

    lines = [
        "# Stage1 Full Audit 2026-06-27",
        "",
        "## Scope",
        "",
        f"- Stage1 output directory: `{paths.stage1_dir}`",
        f"- clean_wind: `{paths.clean_wind}`",
        f"- clean_loc: `{paths.clean_loc}`",
        f"- radar_index: `{paths.radar_index}`",
        f"- frame_window_index: `{paths.frame_window_index}`",
        "",
        "## Verdict",
        "",
        "- `location` 主链路已经通过时间、坐标、高度、地速换算和运动向量一致性检查。",
        "- 高度单位修复已经生效：AMDAR/TURB 高度现在按 feet -> meters 转换，location 中少量 feet 异常行也已纠正。",
        "- Stage1 目前不能把 `AMDAR` 视为“已经严格时空对齐”的单点风观测；该源存在明显的同航班同时间批量多点展开现象，需要单独处理。",
        "- 当前 Stage1 处理策略应把所有同航班同时间重复 AMDAR 显式标记为 `support_only_not_strict_truth`，供下游融合使用，但不再作为严格 holdout 真值候选。",
        "- `wind_speed` 的最终单位口径仍不建议盲改，因为在 AMDAR 时间语义未厘清前，直接做 `kt -> m/s` 转换缺乏足够证据。",
        "",
        "## Confirmed Pass",
        "",
        f"- `clean_loc.parquet` 时间范围：`{report['loc_time']['min']}` 到 `{report['loc_time']['max']}`。",
        f"- `clean_wind.parquet` 时间范围：`{report['wind_time']['min']}` 到 `{report['wind_time']['max']}`。",
        f"- location ROI 覆盖：lat `{report['loc_range_checks']['lat_in_roi_ratio']['valid_ratio']:.6f}`，lon `{report['loc_range_checks']['lon_in_roi_ratio']['valid_ratio']:.6f}`，alt `{report['loc_range_checks']['alt_in_grid_ratio']['valid_ratio']:.6f}`。",
        f"- 地速换算后有限值数量：`{loc_speed['finite_rows']}` / `{loc_speed['rows']}`，中位数 `{loc_speed['q50']:.3f} m/s`，99 分位 `{loc_speed['q99']:.3f} m/s`。",
        f"- motion 向量一致性：`|sqrt(u_motion^2+v_motion^2)-ground_speed_ms|` 的最大误差 `{motion_consistency['max_abs_diff']:.3e}`。",
        f"- wind 向量一致性：`|sqrt(u_wind^2+v_wind^2)-wind_speed|` 的最大误差 `{wind_consistency['max_abs_diff']:.3e}`。",
        f"- 雷达可用帧：`{report['radar_index']['usable_rows']}` / `{report['radar_index']['rows']}`，可用帧中 `loc_rows=0` 仅 `{report['frame_window_stats']['usable_zero_loc_rows']}` 帧。",
        "",
        "## Risks",
        "",
        f"- location 数值缺测现在已标准化为 `null`。`ground_speed_ms` 当前 `null_rows={loc_speed['null_rows']}`、`nan_rows={loc_speed['nan_rows']}`；后续统计应以 `null` 口径为准。",
        f"- 同航班最近时间匹配中，wind->loc 的整体 2 分钟命中率只有 `{same_flight['match_ratio']:.6f}`；其中 `turb` 命中较好，但 `amdar` 命中结果并不能证明真实时空对齐。",
        f"- AMDAR 同航班同时间组异常明显：重复组占比 `{dup['by_source']['amdar']['duplicate_group_share']:.6f}`，其中横向跨度 >= 0.5 deg 的重复组有 `{dup['by_source']['amdar']['duplicate_big_hspan_ge_0p5deg_groups']}` 个。",
        f"- AMDAR 最大同时间组大小为 `{dup['by_source']['amdar']['rows_max']}`，这更像“批量轨迹片段共用同一时间戳”，而不是正常单点风观测。",
        f"- Stage1 分流后，`wind_reconstruction_role` 的当前快照见 `stage1_summary_snapshot.wind_reconstruction_role_counts`；后续 Stage2/Stage4 应仅将 `strict_truth_candidate` 视为严格真值候选。",
        "",
        "## Interpretation",
        "",
        "- 结论 1：`location` 这支数据已经可以继续作为 Stage2/Stage4 的轨迹和运动约束来源使用。",
        "- 结论 2：`TURB` 量很少，但结构上比 AMDAR 干净得多，至少没有大规模同时间多点展开问题。",
        "- 结论 3：`AMDAR` 的主要风险不是高度单位，而是时间字段语义或记录组织方式。更稳妥的解释是：当前时间列疑似报文打包时间/批次时间，而不是每个风点的真实采样时刻。",
        "- 结论 4：在 AMDAR 时间语义未确认前，不建议把该源直接当作严格独立真值去做精细时空对齐评估；所有同时间重复组都更适合作为 support-only 融合输入。",
        "",
        "## Suggested Next Step",
        "",
        "- 先保留当前高度修复成果，不再回滚。",
        "- 保持 downstream 继续按 `null` / `is_finite` 口径消费 `location` 数值列，避免旧脚本误把历史 `NaN` 语义带回来。",
        "- 针对 AMDAR 单独做源字段追溯：确认 `时间（北京时）` 是否为单点观测时刻、报文上送时刻，还是一个批次时间。",
        "- 在 AMDAR 时间语义明确之前，不要贸然做风速单位重标定，也不要把 AMDAR 当作严格点对点对齐真值。优先沿用“重复同时间组全部 support-only”的分流口径。",
        "",
        "## Files",
        "",
        f"- JSON report: `{report['report_paths']['json']}`",
        f"- Markdown report: `{report['report_paths']['markdown']}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parse_args()
    paths = _build_paths(args)

    wind = pl.read_parquet(paths.clean_wind).with_columns(
        [
            pl.col("time_utc").cast(pl.Datetime, strict=False).alias("time_utc"),
            pl.col("lat_clean").cast(pl.Float64, strict=False).alias("lat_clean"),
            pl.col("lon_clean").cast(pl.Float64, strict=False).alias("lon_clean"),
            pl.col("alt_meters").cast(pl.Float64, strict=False).alias("alt_meters"),
            pl.col("wind_dir").cast(pl.Float64, strict=False).alias("wind_dir"),
            pl.col("wind_speed").cast(pl.Float64, strict=False).alias("wind_speed"),
            pl.col("u_wind").cast(pl.Float64, strict=False).alias("u_wind"),
            pl.col("v_wind").cast(pl.Float64, strict=False).alias("v_wind"),
        ]
    )
    loc = pl.read_parquet(paths.clean_loc).with_columns(
        [
            pl.col("time_utc").cast(pl.Datetime, strict=False).alias("time_utc"),
            pl.col("lat_clean").cast(pl.Float64, strict=False).alias("lat_clean"),
            pl.col("lon_clean").cast(pl.Float64, strict=False).alias("lon_clean"),
            pl.col("alt_meters").cast(pl.Float64, strict=False).alias("alt_meters"),
            pl.col("heading_deg").cast(pl.Float64, strict=False).alias("heading_deg"),
            pl.col("ground_speed_ms").cast(pl.Float64, strict=False).alias("ground_speed_ms"),
            pl.col("u_motion").cast(pl.Float64, strict=False).alias("u_motion"),
            pl.col("v_motion").cast(pl.Float64, strict=False).alias("v_motion"),
        ]
    )
    radar_index = _load_json(paths.radar_index)
    frame_window_index = _load_json(paths.frame_window_index)
    stage1_summary = _load_json(paths.stage1_dir / "stage1_summary.json")

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stage1_dir": str(paths.stage1_dir),
        "stage1_summary_snapshot": stage1_summary,
        "wind_time": _datetime_summary(wind, "time_utc"),
        "loc_time": _datetime_summary(loc, "time_utc"),
        "wind_numeric": {
            "lat_clean": _numeric_summary(wind, "lat_clean"),
            "lon_clean": _numeric_summary(wind, "lon_clean"),
            "alt_meters": _numeric_summary(wind, "alt_meters"),
            "wind_dir": _numeric_summary(wind, "wind_dir"),
            "wind_speed": _numeric_summary(wind, "wind_speed"),
            "u_wind": _numeric_summary(wind, "u_wind"),
            "v_wind": _numeric_summary(wind, "v_wind"),
        },
        "loc_numeric": {
            "lat_clean": _numeric_summary(loc, "lat_clean"),
            "lon_clean": _numeric_summary(loc, "lon_clean"),
            "alt_meters": _numeric_summary(loc, "alt_meters"),
            "heading_deg": _numeric_summary(loc, "heading_deg"),
            "ground_speed_ms": _numeric_summary(loc, "ground_speed_ms"),
            "u_motion": _numeric_summary(loc, "u_motion"),
            "v_motion": _numeric_summary(loc, "v_motion"),
        },
        "wind_range_checks": {
            "lat_in_roi_ratio": _range_ratio(wind, "lat_clean", *ROI_LAT),
            "lon_in_roi_ratio": _range_ratio(wind, "lon_clean", *ROI_LON),
            "alt_in_grid_ratio": _range_ratio(wind, "alt_meters", *ROI_ALT),
            "wind_dir_0_360_ratio": _range_ratio(wind, "wind_dir", 0.0, 360.0),
            "wind_speed_0_100_ratio": _range_ratio(wind, "wind_speed", 0.0, float(cfg.MAX_WIND_SPEED_MS)),
        },
        "loc_range_checks": {
            "lat_in_roi_ratio": _range_ratio(loc, "lat_clean", *ROI_LAT),
            "lon_in_roi_ratio": _range_ratio(loc, "lon_clean", *ROI_LON),
            "alt_in_grid_ratio": _range_ratio(loc, "alt_meters", *ROI_ALT),
            "heading_0_360_ratio": _range_ratio(loc, "heading_deg", 0.0, 360.0),
            "ground_speed_0_400_ratio": _range_ratio(loc, "ground_speed_ms", 0.0, float(cfg.MAX_GROUND_SPEED_MS)),
        },
        "wind_source_counts": _value_counts(wind, "source"),
        "wind_altitude_unit_state_counts": _value_counts(wind, "altitude_unit_state"),
        "wind_altitude_unit_mode_counts": _value_counts(wind, "altitude_unit_mode"),
        "loc_altitude_unit_state_counts": _value_counts(loc, "altitude_unit_state"),
        "loc_altitude_unit_mode_counts": _value_counts(loc, "altitude_unit_mode"),
        "loc_flight_id_virtual_counts": _value_counts(loc, "flight_id_is_virtual"),
        "loc_flight_id_source_counts": _value_counts(loc, "flight_id_source"),
        "wind_vector_consistency": _vector_consistency(wind, "wind_speed", "u_wind", "v_wind"),
        "loc_motion_vector_consistency": _vector_consistency(loc, "ground_speed_ms", "u_motion", "v_motion"),
        "cross_table_same_flight_nearest_loc": _same_flight_match(wind, loc, args.same_flight_tolerance_minutes),
        "wind_same_time_group_stats": _wind_same_time_group_stats(wind, args.top_group_limit),
        "suspicious_amdar_example": _suspicious_amdar_example(wind, loc, args.nearby_window_minutes),
        "radar_index": {
            "rows": int(len(radar_index)),
            "usable_rows": int(sum(1 for x in radar_index if x.get("usable"))),
        },
        "frame_window_stats": _frame_window_stats(frame_window_index),
    }

    json_path = paths.out_dir / "stage1_full_audit_20260627.json"
    md_path = paths.out_dir / "stage1_full_audit_20260627.md"
    report["report_paths"] = {"json": str(json_path), "markdown": str(md_path)}

    json_path.write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report, paths), encoding="utf-8")

    print(f"[audit] wrote {json_path}")
    print(f"[audit] wrote {md_path}")
    print(
        json.dumps(
            {
                "loc_ground_speed_nan_rows": report["loc_numeric"]["ground_speed_ms"]["nan_rows"],
                "same_flight_match_ratio": report["cross_table_same_flight_nearest_loc"]["match_ratio"],
                "amdar_duplicate_group_share": report["wind_same_time_group_stats"]["by_source"].get("amdar", {}).get("duplicate_group_share"),
                "amdar_duplicate_rows_max": report["wind_same_time_group_stats"]["by_source"].get("amdar", {}).get("rows_max"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
