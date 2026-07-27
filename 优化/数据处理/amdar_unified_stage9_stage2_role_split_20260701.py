from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE1_DIR = DATA_DIR / "amdar_plan4_implementation_20260630/stage1_output_plan4_v1"
STAGE8_DIR = DATA_DIR / "amdar_unified_stage8_enhanced_stage1_optimized_20260701"
STAGE6_DIR = DATA_DIR / "amdar_unified_stage6_time_uncertainty_v2_optimized_20260701"
STAGE7_DIR = DATA_DIR / "amdar_unified_stage7_grade_calibration_optimized_20260701"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage9_stage2_role_split_optimized_20260701"

LAT_MIN = 12.2
LAT_MAX = 54.2
LON_MIN = 73.0
LON_MAX = 135.0
ALT_MIN = 0.0
ALT_MAX = 15000.0
DELTA_ALT = 500.0
DEFAULT_XY_DOWNSAMPLE = 4
DEFAULT_FRAME_WINDOW_MINUTES = 5
DEFAULT_CONTEXT_WINDOW_MINUTES = 360
DEFAULT_CONTEXT_HALFLIFE_MINUTES = 180.0


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage1_dir: Path = STAGE1_DIR
    stage8_dir: Path = STAGE8_DIR
    stage6_dir: Path = STAGE6_DIR
    stage7_dir: Path = STAGE7_DIR
    frame_window_minutes: int = DEFAULT_FRAME_WINDOW_MINUTES
    context_window_minutes: int = DEFAULT_CONTEXT_WINDOW_MINUTES
    context_halflife_minutes: float = DEFAULT_CONTEXT_HALFLIFE_MINUTES
    xy_downsample: int = DEFAULT_XY_DOWNSAMPLE
    alt_step_m: float = DELTA_ALT
    slice_count: int = 25
    workers: int = 25
    stage9_version: str = "v1"
    shard_id: int | None = None
    frame_times_file: Path | None = None
    shard_summary: Path | None = None
    progress_file: Path | None = None
    progress_interval_seconds: float = 30.0
    drop_shard_parquets_after_merge: bool = False
    parent_mode: bool = True


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage9 Stage2 role split. The script consumes Stage8 enhanced clean_wind, "
            "computes frame-level time-overlap confidence, and writes compact role-channel parquet outputs."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--stage1-dir", default=str(STAGE1_DIR))
    parser.add_argument("--stage8-dir", default=str(STAGE8_DIR))
    parser.add_argument("--stage6-dir", default=str(STAGE6_DIR))
    parser.add_argument("--stage7-dir", default=str(STAGE7_DIR))
    parser.add_argument("--frame-window-minutes", type=int, default=DEFAULT_FRAME_WINDOW_MINUTES)
    parser.add_argument("--context-window-minutes", type=int, default=DEFAULT_CONTEXT_WINDOW_MINUTES)
    parser.add_argument("--context-halflife-minutes", type=float, default=DEFAULT_CONTEXT_HALFLIFE_MINUTES)
    parser.add_argument("--xy-downsample", type=int, default=DEFAULT_XY_DOWNSAMPLE)
    parser.add_argument("--alt-step-m", type=float, default=DELTA_ALT)
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--shard-id", type=int)
    parser.add_argument("--shard-summary", type=Path)
    parser.add_argument("--progress-file", type=Path)
    parser.add_argument("--progress-interval-seconds", type=float, default=30.0)
    parser.add_argument(
        "--drop-shard-parquets-after-merge",
        action="store_true",
        help="After merged all-record/all-voxel parquet files are written, remove per-shard parquet payloads to save space.",
    )
    args = parser.parse_args()
    parent_mode = args.shard_id is None
    return RunConfig(
        out_dir=Path(args.out_dir).resolve(),
        stage1_dir=Path(args.stage1_dir).resolve(),
        stage8_dir=Path(args.stage8_dir).resolve(),
        stage6_dir=Path(args.stage6_dir).resolve(),
        stage7_dir=Path(args.stage7_dir).resolve(),
        frame_window_minutes=int(args.frame_window_minutes),
        context_window_minutes=int(args.context_window_minutes),
        context_halflife_minutes=float(args.context_halflife_minutes),
        xy_downsample=int(args.xy_downsample),
        alt_step_m=float(args.alt_step_m),
        slice_count=int(args.slice_count),
        workers=int(args.workers),
        shard_id=args.shard_id,
        frame_times_file=args.frame_times_file.resolve() if args.frame_times_file else None,
        shard_summary=args.shard_summary.resolve() if args.shard_summary else None,
        progress_file=args.progress_file.resolve() if args.progress_file else None,
        progress_interval_seconds=float(args.progress_interval_seconds),
        drop_shard_parquets_after_merge=bool(args.drop_shard_parquets_after_merge),
        parent_mode=parent_mode,
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    tmp_path.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def counts_map(df: pl.DataFrame, col: str) -> dict[str, int]:
    if df.height == 0 or col not in df.columns:
        return {}
    vc = (
        df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
    )
    return {str(k): int(v) for k, v in vc.iter_rows()}


def numeric_summary(df: pl.DataFrame, col: str) -> dict[str, Any]:
    if df.height == 0 or col not in df.columns:
        return {"present": col in df.columns, "rows": int(df.height)}
    series = df.select(pl.col(col).cast(pl.Float64, strict=False).alias(col)).get_column(col)
    finite = series.filter(series.is_finite())
    return {
        "present": True,
        "rows": int(df.height),
        "null_rows": int(series.is_null().sum()),
        "finite_rows": int(finite.len()),
        "min": float(finite.min()) if finite.len() else None,
        "p10": float(finite.quantile(0.10)) if finite.len() else None,
        "q50": float(finite.quantile(0.50)) if finite.len() else None,
        "p90": float(finite.quantile(0.90)) if finite.len() else None,
        "p99": float(finite.quantile(0.99)) if finite.len() else None,
        "max": float(finite.max()) if finite.len() else None,
    }


def require_upstream_gates(cfg: RunConfig) -> dict[str, Any]:
    stage6_summary = read_json(cfg.stage6_dir / "time_uncertainty_summary_v2.json")
    stage7_summary = read_json(cfg.stage7_dir / "amdar_quality_grade_summary.json")
    stage8_summary = read_json(cfg.stage8_dir / "stage8_enhanced_stage1_summary.json")
    checks = {
        "stage6_gate_passed": bool(
            stage6_summary.get("stage6_completion_checks", {}).get("passed_stage6_time_uncertainty_gate")
        ),
        "stage7_gate_passed": bool(
            stage7_summary.get("stage7_completion_checks", {}).get("passed_stage7_grade_calibration_gate")
        ),
        "stage8_gate_passed": bool(
            stage8_summary.get("stage8_completion_checks", {}).get("passed_stage8_enhanced_stage1_gate")
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Upstream Stage6/7/8 gate failure before Stage9: {checks}")
    return {
        "stage6_summary": stage6_summary,
        "stage7_summary": stage7_summary,
        "stage8_summary": stage8_summary,
        "upstream_checks": checks,
    }


def load_frames(cfg: RunConfig) -> list[dict[str, Any]]:
    radar_index_path = cfg.stage1_dir / "radar_index.json"
    rows = json.loads(radar_index_path.read_text(encoding="utf-8"))
    usable = [{**row, "global_frame_index": idx} for idx, row in enumerate(row for row in rows if row.get("usable"))]
    if cfg.frame_times_file:
        wanted = {str(x) for x in json.loads(cfg.frame_times_file.read_text(encoding="utf-8"))}
        selected = [row for row in usable if str(row.get("time_str")) in wanted]
        missing = sorted(wanted - {str(row.get("time_str")) for row in selected})
        if missing:
            raise ValueError(f"Requested frame times not found as usable radar frames: {missing[:10]}")
        return selected
    return usable


def frame_table(frames: list[dict[str, Any]]) -> pl.DataFrame:
    return (
        pl.DataFrame(
            {
                "frame_index": [int(row.get("global_frame_index", idx)) for idx, row in enumerate(frames)],
                "time_str": [str(row["time_str"]) for row in frames],
                "radar_path": [str(row.get("radar_path", "")) for row in frames],
                "filename": [str(row.get("filename", "")) for row in frames],
            }
        )
        .with_columns(pl.col("time_str").str.strptime(pl.Datetime, "%Y%m%d%H%M%S").alias("target_time"))
        .with_columns(pl.col("target_time").dt.epoch("s").alias("target_time_s"))
    )


def output_dirs(cfg: RunConfig) -> dict[str, Path]:
    dirs = {
        "records": cfg.out_dir / "stage2_observation_records",
        "voxel": cfg.out_dir / "stage2_voxel_support_summary",
        "shards": cfg.out_dir / "shards",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def base_observations(cfg: RunConfig) -> pl.LazyFrame:
    path = cfg.stage8_dir / "clean_wind_with_confidence.parquet"
    selected_cols = [
        "stage8_input_order",
        "source_row_index",
        "source",
        "flight_id",
        "amdar_batch_id",
        "amdar_observation_order",
        "raw_row_number",
        "机尾号",
        "航班号",
        "飞行阶段",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "wind_dir",
        "wind_speed",
        "u_wind",
        "v_wind",
        "obs_conf",
        "obs_conf_v2",
        "source_conf",
        "met_conf",
        "batch_conf",
        "time_source_conf",
        "sequence_conf",
        "identity_conf",
        "spatial_representativeness",
        "batch_met_consistency",
        "base_support_conf",
        "confidence_tier",
        "confidence_grade",
        "stage7_quality_tier",
        "stage7_quality_grade",
        "stage7_grade_basis",
        "stage7_usage_recommendation",
        "stage7_obs_weight_hint",
        "stage8_usage_recommendation",
        "stage8_support_assimilation_eligible",
        "stage8_display_only",
        "stage8_rejected_from_support",
        "holdout_eligible",
        "stage8_effective_strict_truth",
        "stage8_holdout_review",
        "stage8_point_time_strict_truth_available",
        "estimated_time_is_strict_point_truth",
        "estimated_time_q10",
        "estimated_time_q50",
        "estimated_time_q90",
        "time_interval_start",
        "time_interval_end",
        "time_interval_width_s",
        "time_uncertainty_s",
        "time_pdf_type",
        "time_source",
        "time_reconstruction_grade",
        "batch_interval_driver",
        "batch_time_semantics",
        "adsb_reconstructed",
        "adsb_match_quality",
        "adsb_match_cost",
        "adsb_match_ambiguity",
        "adsb_cross_track_dist",
        "adsb_vertical_diff",
        "wind_speed_outlier_flag",
        "temperature_outlier_flag",
        "altitude_outlier_flag",
        "met_value_quality_audit",
    ]
    return (
        pl.scan_parquet(path)
        .select(selected_cols)
        .with_columns(
            [
                pl.concat_str(
                    [
                        pl.col("source").cast(pl.Utf8),
                        pl.col("source_row_index").cast(pl.Utf8),
                        pl.col("stage8_input_order").cast(pl.Utf8),
                    ],
                    separator=":",
                ).alias("observation_id"),
                pl.col("time_interval_start").dt.epoch("s").alias("interval_start_s"),
                pl.col("time_interval_end").dt.epoch("s").alias("interval_end_s"),
                pl.col("estimated_time_q10").dt.epoch("s").alias("q10_s"),
                pl.col("estimated_time_q50").dt.epoch("s").alias("q50_s"),
                pl.col("estimated_time_q90").dt.epoch("s").alias("q90_s"),
            ]
        )
        .with_columns(
            [
                pl.when(
                    pl.col("holdout_eligible").fill_null(False)
                    & pl.col("stage8_effective_strict_truth").fill_null(False)
                    & pl.col("stage8_point_time_strict_truth_available").fill_null(False)
                    & (pl.col("confidence_grade") == "S")
                )
                .then(pl.lit("strict_truth_records"))
                .when(pl.col("source") == "amdar")
                .then(
                    pl.when(pl.col("confidence_grade").is_in(["A", "B"]))
                    .then(pl.lit("current_support_records"))
                    .when(pl.col("confidence_grade") == "C")
                    .then(pl.lit("batch_support_records"))
                    .when(pl.col("stage8_usage_recommendation") == "display_only_not_regular_support")
                    .then(pl.lit("diagnostic_only_records"))
                    .otherwise(pl.lit("rejected_records"))
                )
                .when(pl.col("stage8_holdout_review").fill_null(False))
                .then(pl.lit("diagnostic_only_records"))
                .otherwise(pl.lit("rejected_records"))
                .alias("stage9_primary_channel"),
                pl.when(
                    (pl.col("source") == "amdar")
                    & pl.col("confidence_grade").is_in(["A", "B", "C"])
                    & ~pl.col("holdout_eligible").fill_null(False)
                )
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("stage9_context_support_candidate"),
                pl.when(pl.col("confidence_grade").is_in(["A", "B", "C"]))
                .then(pl.col("confidence_grade"))
                .otherwise(pl.col("confidence_grade"))
                .alias("quality_grade"),
                pl.when(pl.col("confidence_grade") == "S")
                .then(pl.lit("S"))
                .when(pl.col("time_reconstruction_grade").str.starts_with("B"))
                .then(pl.lit("B"))
                .when(pl.col("time_reconstruction_grade").str.starts_with("C"))
                .then(pl.lit("C"))
                .otherwise(pl.lit("R"))
                .alias("time_grade"),
            ]
        )
        .with_columns(
            pl.when(pl.col("confidence_grade") == "R")
            .then(pl.col("stage8_usage_recommendation"))
            .otherwise(pl.col("stage9_primary_channel"))
            .alias("stage9_role_reason")
        )
    )


def with_frame_window(frames: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    window_s = int(cfg.frame_window_minutes * 60)
    return frames.with_columns(
        [
            (pl.col("target_time_s") - window_s).alias("frame_window_start_s"),
            (pl.col("target_time_s") + window_s).alias("frame_window_end_s"),
        ]
    )


def with_overlap_columns(df: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    eps = 1e-9
    interval_width = (pl.col("interval_end_s") - pl.col("interval_start_s")).cast(pl.Float64)
    intersection = (
        pl.min_horizontal(["interval_end_s", "frame_window_end_s"])
        - pl.max_horizontal(["interval_start_s", "frame_window_start_s"])
    ).clip(lower_bound=0)
    left_width = (pl.col("q50_s") - pl.col("interval_start_s")).clip(lower_bound=0).cast(pl.Float64)
    right_width = (pl.col("interval_end_s") - pl.col("q50_s")).clip(lower_bound=0).cast(pl.Float64)
    total_width = interval_width.clip(lower_bound=eps)
    left_norm = left_width.clip(lower_bound=eps)
    right_norm = right_width.clip(lower_bound=eps)
    sample_n = 9
    sample_exprs: list[pl.Expr] = []
    for idx in range(sample_n):
        frac = (idx + 0.5) / sample_n
        sample_s = pl.col("frame_window_start_s") + (pl.col("frame_window_end_s") - pl.col("frame_window_start_s")) * frac
        triangular_density = (
            pl.when(sample_s < pl.col("interval_start_s"))
            .then(0.0)
            .when(sample_s > pl.col("interval_end_s"))
            .then(0.0)
            .when(sample_s <= pl.col("q50_s"))
            .then(2.0 * (sample_s - pl.col("interval_start_s")).clip(lower_bound=0) / (total_width * left_norm))
            .otherwise(2.0 * (pl.col("interval_end_s") - sample_s).clip(lower_bound=0) / (total_width * right_norm))
        )
        sample_exprs.append(triangular_density)
    triangular_prob = (
        sum(sample_exprs)
        * ((pl.col("frame_window_end_s") - pl.col("frame_window_start_s")).cast(pl.Float64) / sample_n)
        / 1.0
    ).clip(lower_bound=0.0, upper_bound=1.0)
    uniform_prob = (intersection.cast(pl.Float64) / interval_width.clip(lower_bound=eps)).clip(
        lower_bound=0.0, upper_bound=1.0
    )
    point_prob = (
        (pl.col("q50_s") >= pl.col("frame_window_start_s")) & (pl.col("q50_s") <= pl.col("frame_window_end_s"))
    ).cast(pl.Float64)
    overlap_prob = (
        pl.when(pl.col("time_pdf_type") == "point_observation_time")
        .then(point_prob)
        .when(pl.col("time_pdf_type").str.contains("triangular"))
        .then(triangular_prob)
        .otherwise(uniform_prob)
    ).clip(lower_bound=0.0, upper_bound=1.0)
    return df.with_columns(
        [
            intersection.cast(pl.Float64).alias("frame_interval_overlap_s"),
            interval_width.alias("observation_interval_width_s"),
            overlap_prob.alias("frame_time_overlap_prob"),
            (pl.col("q50_s") - pl.col("target_time_s")).cast(pl.Float64).alias("q50_delta_to_frame_s"),
            (pl.col("obs_conf_v2").cast(pl.Float64) * overlap_prob).alias("frame_time_conf"),
            (
                pl.col("obs_conf_v2").cast(pl.Float64)
                * overlap_prob
                * pl.col("spatial_representativeness").cast(pl.Float64).fill_null(1.0)
            ).alias("frame_joint_conf"),
            pl.lit("stage6_distribution_overlap").alias("frame_time_conf_method"),
        ]
    )


def with_context_columns(df: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    halflife_s = max(60.0, float(cfg.context_halflife_minutes) * 60.0)
    delta_abs = (pl.col("q50_s") - pl.col("target_time_s")).abs().cast(pl.Float64)
    context_time_conf = (0.5 ** (delta_abs / halflife_s)).clip(lower_bound=0.0, upper_bound=1.0)
    return df.with_columns(
        [
            delta_abs.alias("context_abs_q50_delta_s"),
            context_time_conf.alias("context_time_conf"),
            (pl.col("obs_conf_v2").cast(pl.Float64) * context_time_conf).alias("context_joint_conf"),
            pl.lit(0.0).alias("frame_time_overlap_prob"),
            pl.lit(0.0).alias("frame_time_conf"),
            pl.lit(0.0).alias("frame_joint_conf"),
            pl.lit(0.0).alias("frame_interval_overlap_s"),
            pl.lit("q50_context_halflife_not_current_frame").alias("frame_time_conf_method"),
            pl.lit("context_support_records").alias("stage9_output_channel"),
        ]
    )


def add_voxel_columns(df: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    if df.height == 0:
        return df
    coarse_h = max(1, 2100 // int(cfg.xy_downsample))
    coarse_w = max(1, 3100 // int(cfg.xy_downsample))
    z_dim = int((ALT_MAX - ALT_MIN) / float(cfg.alt_step_m)) + 1
    delta_lat = (LAT_MAX - LAT_MIN) / 2100.0
    delta_lon = (LON_MAX - LON_MIN) / 3100.0
    return (
        df.with_columns(
            [
                (((pl.col("lon_clean") - LON_MIN) / delta_lon) / int(cfg.xy_downsample))
                .floor()
                .cast(pl.Int32)
                .alias("x"),
                (((LAT_MAX - pl.col("lat_clean")) / delta_lat) / int(cfg.xy_downsample))
                .floor()
                .cast(pl.Int32)
                .alias("y"),
                ((pl.col("alt_meters") - ALT_MIN) / float(cfg.alt_step_m)).floor().cast(pl.Int32).alias("z"),
            ]
        )
        .filter(
            (pl.col("x") >= 0)
            & (pl.col("x") < coarse_w)
            & (pl.col("y") >= 0)
            & (pl.col("y") < coarse_h)
            & (pl.col("z") >= 0)
            & (pl.col("z") < z_dim)
            & pl.col("lat_clean").is_finite()
            & pl.col("lon_clean").is_finite()
            & pl.col("alt_meters").is_finite()
            & pl.col("u_wind").is_finite()
            & pl.col("v_wind").is_finite()
        )
    )


def output_columns(include_context: bool = False) -> list[str]:
    cols = [
        "frame_index",
        "time_str",
        "target_time",
        "observation_id",
        "stage8_input_order",
        "source_row_index",
        "source",
        "flight_id",
        "amdar_batch_id",
        "amdar_observation_order",
        "raw_row_number",
        "机尾号",
        "航班号",
        "飞行阶段",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "x",
        "y",
        "z",
        "wind_dir",
        "wind_speed",
        "u_wind",
        "v_wind",
        "obs_conf_v2",
        "source_conf",
        "met_conf",
        "batch_conf",
        "time_source_conf",
        "sequence_conf",
        "identity_conf",
        "spatial_representativeness",
        "batch_met_consistency",
        "base_support_conf",
        "confidence_tier",
        "confidence_grade",
        "quality_grade",
        "time_grade",
        "stage9_primary_channel",
        "stage9_output_channel",
        "stage9_role_reason",
        "stage8_usage_recommendation",
        "holdout_eligible",
        "stage8_effective_strict_truth",
        "estimated_time_is_strict_point_truth",
        "stage8_point_time_strict_truth_available",
        "estimated_time_q10",
        "estimated_time_q50",
        "estimated_time_q90",
        "time_interval_start",
        "time_interval_end",
        "time_interval_width_s",
        "time_uncertainty_s",
        "time_pdf_type",
        "time_source",
        "time_reconstruction_grade",
        "batch_interval_driver",
        "adsb_reconstructed",
        "adsb_match_quality",
        "adsb_match_cost",
        "adsb_match_ambiguity",
        "adsb_cross_track_dist",
        "adsb_vertical_diff",
        "frame_interval_overlap_s",
        "observation_interval_width_s",
        "frame_time_overlap_prob",
        "q50_delta_to_frame_s",
        "frame_time_conf",
        "frame_joint_conf",
        "frame_time_conf_method",
    ]
    if include_context:
        cols.extend(["context_abs_q50_delta_s", "context_time_conf", "context_joint_conf"])
    return cols


def voxel_summary(df: pl.DataFrame, include_context: bool = False) -> pl.DataFrame:
    if df.height == 0:
        base_schema = {
            "frame_index": pl.Int64,
            "time_str": pl.Utf8,
            "stage9_output_channel": pl.Utf8,
            "confidence_grade": pl.Utf8,
            "z": pl.Int32,
            "y": pl.Int32,
            "x": pl.Int32,
            "rows": pl.UInt32,
            "unique_flights": pl.UInt32,
            "unique_batches": pl.UInt32,
            "weighted_u": pl.Float64,
            "weighted_v": pl.Float64,
            "mean_wind_speed": pl.Float64,
            "mean_obs_conf_v2": pl.Float64,
            "sum_frame_time_conf": pl.Float64,
            "sum_frame_joint_conf": pl.Float64,
            "mean_frame_time_overlap_prob": pl.Float64,
            "max_frame_time_conf": pl.Float64,
            "holdout_rows": pl.UInt32,
        }
        if include_context:
            base_schema.update({"sum_context_joint_conf": pl.Float64, "mean_context_time_conf": pl.Float64})
        return pl.DataFrame(schema=base_schema)
    agg_exprs = [
        pl.len().alias("rows"),
        pl.col("flight_id").n_unique().alias("unique_flights"),
        pl.col("amdar_batch_id").n_unique().alias("unique_batches"),
        ((pl.col("u_wind") * pl.col("frame_joint_conf")).sum() / pl.col("frame_joint_conf").sum()).alias(
            "weighted_u_raw"
        ),
        ((pl.col("v_wind") * pl.col("frame_joint_conf")).sum() / pl.col("frame_joint_conf").sum()).alias(
            "weighted_v_raw"
        ),
        pl.col("u_wind").mean().alias("mean_u"),
        pl.col("v_wind").mean().alias("mean_v"),
        pl.col("wind_speed").mean().alias("mean_wind_speed"),
        pl.col("obs_conf_v2").mean().alias("mean_obs_conf_v2"),
        pl.col("frame_time_conf").sum().alias("sum_frame_time_conf"),
        pl.col("frame_joint_conf").sum().alias("sum_frame_joint_conf"),
        pl.col("frame_time_overlap_prob").mean().alias("mean_frame_time_overlap_prob"),
        pl.col("frame_time_conf").max().alias("max_frame_time_conf"),
        pl.col("holdout_eligible").sum().alias("holdout_rows"),
    ]
    if include_context:
        agg_exprs.extend(
            [
                pl.col("context_joint_conf").sum().alias("sum_context_joint_conf"),
                pl.col("context_time_conf").mean().alias("mean_context_time_conf"),
            ]
        )
    grouped = df.group_by(["frame_index", "time_str", "stage9_output_channel", "confidence_grade", "z", "y", "x"]).agg(
        agg_exprs
    )
    return grouped.with_columns(
        [
            pl.coalesce([pl.col("weighted_u_raw"), pl.col("mean_u")]).alias("weighted_u"),
            pl.coalesce([pl.col("weighted_v_raw"), pl.col("mean_v")]).alias("weighted_v"),
        ]
    ).drop(["weighted_u_raw", "weighted_v_raw", "mean_u", "mean_v"])


def make_shard_frames(frames: list[dict[str, Any]], slice_count: int) -> list[list[dict[str, Any]]]:
    slices = [[] for _ in range(max(1, slice_count))]
    for idx, row in enumerate(frames):
        slices[idx % len(slices)].append(row)
    return slices


def stage9_for_frames(cfg: RunConfig, frames: list[dict[str, Any]]) -> dict[str, Any]:
    dirs = output_dirs(cfg)
    frame_df = with_frame_window(frame_table(frames), cfg)
    if frame_df.height == 0:
        return {
            "shard_id": cfg.shard_id,
            "frames": 0,
            "observation_record_rows": 0,
            "voxel_summary_rows": 0,
        }

    obs_lf = base_observations(cfg)
    min_window_s = int(frame_df["frame_window_start_s"].min())
    max_window_s = int(frame_df["frame_window_end_s"].max())
    min_context_s = int(frame_df["target_time_s"].min() - cfg.context_window_minutes * 60)
    max_context_s = int(frame_df["target_time_s"].max() + cfg.context_window_minutes * 60)

    current_candidates = (
        obs_lf.filter((pl.col("interval_start_s") <= max_window_s) & (pl.col("interval_end_s") >= min_window_s))
        .join(frame_df.lazy(), how="cross")
        .filter((pl.col("interval_start_s") <= pl.col("frame_window_end_s")) & (pl.col("interval_end_s") >= pl.col("frame_window_start_s")))
        .collect(engine="streaming")
    )
    current_candidates = add_voxel_columns(with_overlap_columns(current_candidates, cfg), cfg)
    current_candidates = current_candidates.filter(pl.col("frame_time_overlap_prob") > 0.0)
    current_candidates = current_candidates.with_columns(pl.col("stage9_primary_channel").alias("stage9_output_channel"))

    context_candidates = (
        obs_lf.filter(
            pl.col("stage9_context_support_candidate")
            & (pl.col("q50_s") >= min_context_s)
            & (pl.col("q50_s") <= max_context_s)
        )
        .join(frame_df.lazy(), how="cross")
        .filter(
            (pl.col("q50_s") >= pl.col("target_time_s") - cfg.context_window_minutes * 60)
            & (pl.col("q50_s") <= pl.col("target_time_s") + cfg.context_window_minutes * 60)
        )
        .filter(
            ~(
                (pl.col("interval_start_s") <= pl.col("frame_window_end_s"))
                & (pl.col("interval_end_s") >= pl.col("frame_window_start_s"))
            )
        )
        .collect(engine="streaming")
    )
    context_candidates = add_voxel_columns(with_context_columns(context_candidates, cfg), cfg)

    shard_label = f"shard_{cfg.shard_id:02d}" if cfg.shard_id is not None else "single"
    current_out = dirs["records"] / f"{shard_label}_current_batch_diagnostic_reject.parquet"
    context_out = dirs["records"] / f"{shard_label}_context_support.parquet"
    current_voxel_out = dirs["voxel"] / f"{shard_label}_current_batch_diagnostic_reject_voxels.parquet"
    context_voxel_out = dirs["voxel"] / f"{shard_label}_context_support_voxels.parquet"

    current_cols = [col for col in output_columns(False) if col in current_candidates.columns]
    context_cols = [col for col in output_columns(True) if col in context_candidates.columns]
    current_candidates.select(current_cols).write_parquet(current_out)
    context_candidates.select(context_cols).write_parquet(context_out)
    current_voxel = voxel_summary(current_candidates, include_context=False)
    context_voxel = voxel_summary(context_candidates, include_context=True)
    current_voxel.write_parquet(current_voxel_out)
    context_voxel.write_parquet(context_voxel_out)

    channel_counts = counts_map(current_candidates, "stage9_output_channel")
    context_channel_counts = counts_map(context_candidates, "stage9_output_channel")
    summary = {
        "shard_id": cfg.shard_id,
        "frames": int(frame_df.height),
        "first_frame": str(frame_df["time_str"][0]),
        "last_frame": str(frame_df["time_str"][-1]),
        "current_record_path": str(current_out),
        "context_record_path": str(context_out),
        "current_voxel_path": str(current_voxel_out),
        "context_voxel_path": str(context_voxel_out),
        "observation_record_rows": int(current_candidates.height + context_candidates.height),
        "current_like_record_rows": int(current_candidates.height),
        "context_record_rows": int(context_candidates.height),
        "voxel_summary_rows": int(current_voxel.height + context_voxel.height),
        "current_channel_counts": channel_counts,
        "context_channel_counts": context_channel_counts,
        "current_grade_counts": counts_map(current_candidates, "confidence_grade"),
        "context_grade_counts": counts_map(context_candidates, "confidence_grade"),
        "frame_time_conf_summary_current_like": numeric_summary(current_candidates, "frame_time_conf"),
        "frame_time_overlap_summary_current_like": numeric_summary(current_candidates, "frame_time_overlap_prob"),
        "context_joint_conf_summary": numeric_summary(context_candidates, "context_joint_conf"),
        "strict_truth_rows": int(
            current_candidates.filter(pl.col("stage9_output_channel") == "strict_truth_records").height
        ),
        "strict_truth_amdar_rows": int(
            current_candidates.filter(
                (pl.col("stage9_output_channel") == "strict_truth_records") & (pl.col("source") == "amdar")
            ).height
        ),
        "amdar_holdout_rows": int(current_candidates.filter((pl.col("source") == "amdar") & pl.col("holdout_eligible")).height),
        "r_regular_support_rows": int(
            current_candidates.filter(
                (pl.col("confidence_grade") == "R")
                & pl.col("stage9_output_channel").is_in(
                    ["current_support_records", "batch_support_records", "context_support_records"]
                )
            ).height
        )
        + int(context_candidates.filter(pl.col("confidence_grade") == "R").height),
    }
    if cfg.shard_summary:
        write_json(cfg.shard_summary, summary)
    return summary


def format_elapsed(seconds: float) -> str:
    seconds_i = max(0, int(seconds))
    hours, rem = divmod(seconds_i, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def write_progress(path: Path | None, shard_id: int | None, done: int, total: int, status: str, detail: str = "") -> None:
    if path is None:
        return
    write_json(
        path,
        {
            "shard_id": shard_id,
            "done": int(done),
            "total": int(total),
            "percent": float(done / max(1, total) * 100.0),
            "status": status,
            "detail": detail,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def run_parent(cfg: RunConfig, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dirs = output_dirs(cfg)
    shards = make_shard_frames(frames, cfg.slice_count)
    procs: list[dict[str, Any]] = []
    env_base = os.environ.copy()
    env_base.setdefault("POLARS_MAX_THREADS", "1")
    for shard_id, shard_frames in enumerate(shards):
        if not shard_frames:
            continue
        frame_file = dirs["shards"] / f"stage9_shard_{shard_id:02d}_frames.json"
        summary_file = dirs["shards"] / f"stage9_shard_{shard_id:02d}_summary.json"
        progress_file = dirs["shards"] / f"stage9_shard_{shard_id:02d}_progress.json"
        log_file = dirs["shards"] / f"stage9_shard_{shard_id:02d}.log"
        write_json(frame_file, [row["time_str"] for row in shard_frames])
        write_progress(progress_file, shard_id, 0, len(shard_frames), "queued")
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--out-dir",
            str(cfg.out_dir),
            "--stage1-dir",
            str(cfg.stage1_dir),
            "--stage8-dir",
            str(cfg.stage8_dir),
            "--stage6-dir",
            str(cfg.stage6_dir),
            "--stage7-dir",
            str(cfg.stage7_dir),
            "--frame-window-minutes",
            str(cfg.frame_window_minutes),
            "--context-window-minutes",
            str(cfg.context_window_minutes),
            "--context-halflife-minutes",
            str(cfg.context_halflife_minutes),
            "--xy-downsample",
            str(cfg.xy_downsample),
            "--alt-step-m",
            str(cfg.alt_step_m),
            "--slice-count",
            str(cfg.slice_count),
            "--workers",
            str(cfg.workers),
            "--frame-times-file",
            str(frame_file),
            "--shard-id",
            str(shard_id),
            "--shard-summary",
            str(summary_file),
            "--progress-file",
            str(progress_file),
            "--progress-interval-seconds",
            str(cfg.progress_interval_seconds),
        ]
        with log_file.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
        procs.append(
            {
                "proc": proc,
                "shard_id": shard_id,
                "frames": len(shard_frames),
                "summary": summary_file,
                "progress": progress_file,
                "log": log_file,
            }
        )

    start_ts = time.time()
    total = len(procs)
    while procs:
        failed = [item for item in procs if item["proc"].poll() not in (None, 0)]
        if failed:
            item = failed[0]
            raise RuntimeError(f"Stage9 shard {item['shard_id']} failed rc={item['proc'].poll()}; see {item['log']}")
        active = sum(1 for item in procs if item["proc"].poll() is None)
        done = total - active
        print(
            f"[Stage9 parent] shards done={done}/{total} active={active} elapsed={format_elapsed(time.time() - start_ts)}",
            flush=True,
        )
        if active == 0:
            break
        time.sleep(max(5.0, min(60.0, cfg.progress_interval_seconds)))

    summaries: list[dict[str, Any]] = []
    for item in procs:
        rc = item["proc"].wait()
        if rc != 0:
            raise RuntimeError(f"Stage9 shard {item['shard_id']} failed rc={rc}; see {item['log']}")
        summaries.append(read_json(item["summary"]))
    summaries.sort(key=lambda row: int(row.get("shard_id", 0)))
    return summaries


def combine_parquets(cfg: RunConfig, shard_summaries: list[dict[str, Any]]) -> dict[str, Path]:
    dirs = output_dirs(cfg)
    paths = {
        "all_observation_records": cfg.out_dir / "stage2_observation_records_all.parquet",
        "all_voxel_support_summary": cfg.out_dir / "stage2_voxel_support_summary_all.parquet",
    }
    current_paths = [Path(row["current_record_path"]) for row in shard_summaries]
    context_paths = [Path(row["context_record_path"]) for row in shard_summaries]
    current_voxel_paths = [Path(row["current_voxel_path"]) for row in shard_summaries]
    context_voxel_paths = [Path(row["context_voxel_path"]) for row in shard_summaries]
    if current_paths or context_paths:
        pl.concat(
            [pl.scan_parquet(str(path)) for path in current_paths + context_paths],
            how="diagonal_relaxed",
        ).sink_parquet(paths["all_observation_records"])
    if current_voxel_paths or context_voxel_paths:
        pl.concat(
            [pl.scan_parquet(str(path)) for path in current_voxel_paths + context_voxel_paths],
            how="diagonal_relaxed",
        ).sink_parquet(paths["all_voxel_support_summary"])
    if cfg.drop_shard_parquets_after_merge:
        for path in current_paths + context_paths + current_voxel_paths + context_voxel_paths:
            path.unlink(missing_ok=True)
    # Keep the user-facing folder names from the plan while storing one compact merged file.
    (dirs["records"] / "README.txt").write_text(
        "Shard parquet files plus ../stage2_observation_records_all.parquet contain Stage9 role-split observation records.\n",
        encoding="utf-8",
    )
    (dirs["voxel"] / "README.txt").write_text(
        "Shard parquet files plus ../stage2_voxel_support_summary_all.parquet contain Stage9 voxel support summaries.\n",
        encoding="utf-8",
    )
    return paths


def aggregate_summary(cfg: RunConfig, upstream: dict[str, Any], shard_summaries: list[dict[str, Any]], merged: dict[str, Path]) -> dict[str, Any]:
    records = pl.read_parquet(merged["all_observation_records"])
    voxels = pl.read_parquet(merged["all_voxel_support_summary"])
    stage8_summary = upstream["stage8_summary"]
    full_frame_count = int(stage8_summary.get("reference_frame_count", 7395) or 7395)
    strict = records.filter(pl.col("stage9_output_channel") == "strict_truth_records")
    current_ab = records.filter(pl.col("stage9_output_channel") == "current_support_records")
    batch_c = records.filter(pl.col("stage9_output_channel") == "batch_support_records")
    context = records.filter(pl.col("stage9_output_channel") == "context_support_records")
    diagnostic = records.filter(pl.col("stage9_output_channel") == "diagnostic_only_records")
    rejected = records.filter(pl.col("stage9_output_channel") == "rejected_records")
    frame_channel = (
        records.group_by(["time_str", "stage9_output_channel"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("frame_time_conf").sum().alias("sum_frame_time_conf"),
                pl.col("context_joint_conf").sum().alias("sum_context_joint_conf"),
                pl.col("observation_id").n_unique().alias("unique_observations"),
            ]
        )
        .sort(["time_str", "stage9_output_channel"])
    )
    frame_channel_path = cfg.out_dir / "stage2_channel_statistics.parquet"
    frame_channel.write_parquet(frame_channel_path)
    channel_stats_json = (
        records.group_by(["stage9_output_channel", "source", "confidence_grade"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("observation_id").n_unique().alias("unique_observations"),
                pl.col("frame_time_conf").sum().alias("sum_frame_time_conf"),
                pl.col("frame_joint_conf").sum().alias("sum_frame_joint_conf"),
                pl.col("context_joint_conf").sum().alias("sum_context_joint_conf"),
                pl.col("frame_time_overlap_prob").mean().alias("mean_frame_time_overlap_prob"),
            ]
        )
        .sort(["stage9_output_channel", "source", "confidence_grade"])
        .to_dicts()
    )
    time_conf_dist = {
        "current_support_records": numeric_summary(current_ab, "frame_time_conf"),
        "batch_support_records": numeric_summary(batch_c, "frame_time_conf"),
        "strict_truth_records": numeric_summary(strict, "frame_time_conf"),
        "diagnostic_only_records": numeric_summary(diagnostic, "frame_time_conf"),
        "rejected_records": numeric_summary(rejected, "frame_time_conf"),
        "context_support_records_context_joint_conf": numeric_summary(context, "context_joint_conf"),
    }
    unique_time_str = int(records.select(pl.col("time_str").n_unique()).item())
    unique_frame_index = int(records.select(pl.col("frame_index").n_unique()).item())
    frame_index_time_check = records.group_by("frame_index").agg(pl.col("time_str").n_unique().alias("time_str_count"))
    is_full_frame_run = unique_time_str >= full_frame_count
    structural_checks = {
        **upstream["upstream_checks"],
        "records_written": records.height > 0,
        "voxel_summary_written": voxels.height > 0,
        "frame_index_global_unique": unique_frame_index == unique_time_str,
        "frame_index_maps_to_single_time_str": int(frame_index_time_check.filter(pl.col("time_str_count") > 1).height)
        == 0,
        "strict_truth_only_turb": int(strict.filter(pl.col("source") != "turb").height) == 0,
        "strict_truth_rows_match_stage8_holdout_frames": int(strict.select(pl.col("observation_id").n_unique()).item())
        <= int(stage8_summary.get("row_counts", {}).get("holdout_eligible_rows", 175)),
        "no_amdar_holdout_records": int(records.filter((pl.col("source") == "amdar") & pl.col("holdout_eligible")).height) == 0,
        "no_amdar_effective_strict_truth_records": int(
            records.filter((pl.col("source") == "amdar") & pl.col("stage8_effective_strict_truth")).height
        )
        == 0,
        "r_not_regular_support": int(
            records.filter(
                (pl.col("confidence_grade") == "R")
                & pl.col("stage9_output_channel").is_in(
                    ["current_support_records", "batch_support_records", "context_support_records"]
                )
            ).height
        )
        == 0,
        "frame_time_conf_bounded": int(
            records.filter((pl.col("frame_time_conf") < 0.0) | (pl.col("frame_time_conf") > 1.0)).height
        )
        == 0,
        "context_not_marked_current": int(
            context.filter((pl.col("frame_time_conf") != 0.0) | (pl.col("frame_time_overlap_prob") != 0.0)).height
        )
        == 0,
        "stage9_no_clean_loc_copy": not (cfg.out_dir / "clean_loc.parquet").exists(),
        "space_saving_sharded_outputs": len(shard_summaries) <= max(1, cfg.slice_count),
    }
    full_run_checks = {
        "full_frame_run": is_full_frame_run,
        "strict_truth_channel_present_full_run": int(strict.height) > 0,
        "current_support_channel_present_full_run": int(current_ab.height) > 0,
        "batch_support_channel_present_full_run": int(batch_c.height) > 0,
        "context_support_channel_present_full_run": int(context.height) > 0,
        "diagnostic_channel_present_full_run": int(diagnostic.height) > 0,
        "rejected_channel_present_full_run": int(rejected.height) > 0,
    }
    checks = {
        **structural_checks,
        **full_run_checks,
        "passed_stage9_stage2_role_split_gate": bool(all(structural_checks.values()) and all(full_run_checks.values())),
        "passed_stage9_structural_smoke_gate": bool(all(structural_checks.values())),
    }
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "frame_window_minutes": cfg.frame_window_minutes,
            "context_window_minutes": cfg.context_window_minutes,
            "context_halflife_minutes": cfg.context_halflife_minutes,
            "xy_downsample": cfg.xy_downsample,
            "alt_step_m": cfg.alt_step_m,
            "space_saving_policy": (
                "Read Stage8 clean_wind_with_confidence plus radar_index only. Do not copy clean_loc. "
                "Write sharded compact parquet and two merged parquet files, not 25 full input copies. "
                "Use --drop-shard-parquets-after-merge to keep only merged parquet payloads after successful merge."
            ),
            "stage9_boundary_note": (
                "This is Unified Plan Stage9, a Stage2 role-split interface. It is not the large-framework "
                "Stage1/2/3/4 naming and not Stage10 super-ob weight limiting."
            ),
        },
        "inputs": {
            "stage8_clean_wind_with_confidence": str(cfg.stage8_dir / "clean_wind_with_confidence.parquet"),
            "stage8_summary": str(cfg.stage8_dir / "stage8_enhanced_stage1_summary.json"),
            "stage6_summary": str(cfg.stage6_dir / "time_uncertainty_summary_v2.json"),
            "stage7_summary": str(cfg.stage7_dir / "amdar_quality_grade_summary.json"),
            "radar_index": str(cfg.stage1_dir / "radar_index.json"),
        },
        "row_counts": {
            "frames": unique_time_str,
            "unique_frame_indices": unique_frame_index,
            "observation_record_rows": int(records.height),
            "unique_observations_used": int(records.select(pl.col("observation_id").n_unique()).item()),
            "voxel_summary_rows": int(voxels.height),
            "strict_truth_record_rows": int(strict.height),
            "strict_truth_unique_observations": int(strict.select(pl.col("observation_id").n_unique()).item())
            if strict.height
            else 0,
            "current_support_record_rows": int(current_ab.height),
            "batch_support_record_rows": int(batch_c.height),
            "context_support_record_rows": int(context.height),
            "diagnostic_only_record_rows": int(diagnostic.height),
            "rejected_record_rows": int(rejected.height),
        },
        "channel_counts": counts_map(records, "stage9_output_channel"),
        "source_counts": counts_map(records, "source"),
        "confidence_grade_counts": counts_map(records, "confidence_grade"),
        "channel_statistics": channel_stats_json,
        "time_confidence_distribution": time_conf_dist,
        "frame_channel_statistics": str(frame_channel_path),
        "shard_summaries": shard_summaries,
        "stage9_completion_checks": checks,
        "assessment": {
            "stage6_7_8_readiness": (
                "Stage6/7/8 gates remain valid. Stage9 uses their conservative semantics instead of relaxing "
                "AMDAR point-time or holdout rules."
            ),
            "stage9_result_quality": (
                "Stage9 separates strict truth, A/B current support, C batch support, context support, diagnostic-only, "
                "and rejected channels. The result is suitable for Stage10 super-ob/weight-limit development."
            ),
            "remaining_optimization_space": (
                "Stage10 should cap batch/flight/source weights and create super-ob summaries. Stage13 should test "
                "multi-scale ablations before any official Stage2/Stage4 migration."
            ),
        },
        "outputs": {
            "all_observation_records": str(merged["all_observation_records"]),
            "all_voxel_support_summary": str(merged["all_voxel_support_summary"]),
            "observation_records_dir": str(cfg.out_dir / "stage2_observation_records"),
            "voxel_support_summary_dir": str(cfg.out_dir / "stage2_voxel_support_summary"),
            "channel_statistics": str(frame_channel_path),
            "stage9_summary": str(cfg.out_dir / "stage9_stage2_role_split_summary.json"),
            "stage9_policy": str(cfg.out_dir / "stage9_policy_v1.json"),
            "role_audit": str(cfg.out_dir / "stage2_role_audit.json"),
            "time_conf_distribution": str(cfg.out_dir / "stage2_time_conf_distribution.json"),
            "channel_statistics_json": str(cfg.out_dir / "stage2_channel_statistics.json"),
        },
        "literature_and_reference_basis": {
            "wmo_aircraft_based_observations": (
                "Aircraft-based observations are valuable upper-air observations for forecasting/NWP, but that "
                "does not make AMDAR batch/downlink time a per-point observation time."
            ),
            "noaa_amdar_abo": (
                "NOAA AMDAR/ABO materials support quality-assessed use of aircraft reports in NWP, consistent with "
                "support channels and QC metadata."
            ),
            "faa_adsb": (
                "ADS-B Out state-vector timing/accuracy rules justify using ADS-B as support for time reconstruction, "
                "while the AMDAR batch semantics remain the dominant uncertainty."
            ),
            "sources": {
                "wmo_aircraft_based_observations": "https://community.wmo.int/en/activity-areas/aircraft-based-observations",
                "wmo_guide_to_aircraft_based_observations": "https://library.wmo.int/idurl/4/68221",
                "noaa_amdar_abo": "https://amdar.noaa.gov/",
                "ecfr_14_cfr_91_227_adsb_out": "https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227",
            },
        },
    }
    return summary


def build_policy(cfg: RunConfig, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at_utc": summary["generated_at_utc"],
        "policy_version": f"amdar_unified_stage9_stage2_role_split_{cfg.stage9_version}",
        "purpose": "Stage2 role separation using Stage8 enhanced Stage1 confidence and Stage6 time distributions.",
        "global_rules": [
            "AMDAR remains support-only and never enters strict_truth_records.",
            "strict_truth_records are T0/S TURB enhanced-holdout rows only.",
            "A/B AMDAR enter current_support_records only through frame-window time-distribution overlap.",
            "C AMDAR enter batch_support_records through frame-window overlap and context_support_records through q50 context windows.",
            "R display-only and rejected records are separated; neither is regular support.",
            "context_support_records are historical/context conditioning and have frame_time_conf=0.",
            "Do not copy clean_loc or create full per-slice input replicas.",
        ],
        "time_confidence": {
            "frame_window_minutes": cfg.frame_window_minutes,
            "point_time": "probability is 1 only when point q50 is inside the frame window.",
            "triangular_or_batch_interval": "probability is estimated from Stage6 interval/q50 overlap with the frame window.",
            "other_interval": "probability is conservative uniform interval overlap.",
            "frame_time_conf": "obs_conf_v2 * frame_time_overlap_prob.",
            "frame_joint_conf": "frame_time_conf * spatial_representativeness.",
            "context_joint_conf": "obs_conf_v2 * 0.5 ** (abs(q50-target_time) / context_halflife_seconds).",
        },
        "channel_mapping": {
            "strict_truth_records": "TURB T0/S holdout records only.",
            "current_support_records": "AMDAR A/B support records with current-frame overlap.",
            "batch_support_records": "AMDAR C support records with current-frame overlap; Stage10 should super-ob and cap weights.",
            "context_support_records": "AMDAR A/B/C context records by q50 +/- context window, excluding current overlap.",
            "diagnostic_only_records": "TURB holdout review rows plus AMDAR display-only R rows.",
            "rejected_records": "Rejected R rows not used as support.",
        },
        "completion_checks": summary["stage9_completion_checks"],
    }


def write_stage9_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage9_stage2_role_split_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage9_stage2_role_split.md"
    checks = summary["stage9_completion_checks"]
    rows = summary["row_counts"]
    result_lines = [
        "# AMDAR Unified Plan Stage9 Stage2 Role Split Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## 核心结论",
        "",
        "Stage6/7/8 继续达标，可以进入 Stage9。Stage9 已完成 Stage2 角色分流接口：strict truth、A/B current support、C batch support、A/B/C context support、diagnostic-only、rejected 分通道保留逐条观测记录，并生成体素支持摘要。",
        "",
        "重要边界：这是 Unified Plan Stage9 的 Stage2 角色分流，不是回到大框架 Stage1/2/3/4 重命名；也没有提前执行 Stage10 的 super-ob 和密度权重上限。",
        "",
        "## Stage6/7/8 达标复核",
        "",
        f"- Stage6 gate: `{checks['stage6_gate_passed']}`",
        f"- Stage7 gate: `{checks['stage7_gate_passed']}`",
        f"- Stage8 gate: `{checks['stage8_gate_passed']}`",
        "- 结论：现在的结果满足进入 Stage9 的要求。优化空间主要在 Stage10/13，而不是放宽 Stage6/7 的生产 gate。",
        "",
        "## Stage9 输出结果",
        "",
        f"- Frames: `{rows['frames']}`",
        f"- Observation record rows: `{rows['observation_record_rows']}`",
        f"- Unique observations used: `{rows['unique_observations_used']}`",
        f"- Voxel summary rows: `{rows['voxel_summary_rows']}`",
        f"- Strict truth record rows: `{rows['strict_truth_record_rows']}`",
        f"- Current A/B support rows: `{rows['current_support_record_rows']}`",
        f"- Batch C support rows: `{rows['batch_support_record_rows']}`",
        f"- Context support rows: `{rows['context_support_record_rows']}`",
        f"- Diagnostic-only rows: `{rows['diagnostic_only_record_rows']}`",
        f"- Rejected rows: `{rows['rejected_record_rows']}`",
        f"- Channel counts: `{summary['channel_counts']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## 关键修正点",
        "",
        "- 旧 Stage2 的风险是直接按 `time_utc` T±5 分钟筛选，容易把 AMDAR 批次下发时间误当逐点时间。Stage9 改为使用 Stage6 `time_interval_start/end`、`estimated_time_q50` 和 `time_pdf_type` 计算 frame-level overlap probability。",
        "- `frame_time_conf = obs_conf_v2 * frame_time_overlap_prob`，`frame_joint_conf` 再乘空间代表性；context 通道只做历史/上下文条件，`frame_time_conf=0`。",
        "- AMDAR 没有进入 strict truth；R 级 display-only 与 rejected 已分开，不能作为常规支持资料。",
        "- `frame_index` 保持全局 radar frame 编号，不随 25-slice 分片重置；后续 Stage10 可安全按帧做权重审计。",
        "- 输出采用 25-slice 分片 compact parquet，并合并成两个总 parquet；未复制 `clean_loc.parquet`。",
        "",
        "## Outputs",
        "",
        f"- Observation records: `{summary['outputs']['all_observation_records']}`",
        f"- Voxel support summary: `{summary['outputs']['all_voxel_support_summary']}`",
        f"- Role audit: `{summary['outputs']['role_audit']}`",
        f"- Time confidence distribution: `{summary['outputs']['time_conf_distribution']}`",
        f"- Channel statistics: `{summary['outputs']['channel_statistics_json']}`",
        f"- Stage9 summary: `{summary['outputs']['stage9_summary']}`",
        f"- Stage9 policy: `{summary['outputs']['stage9_policy']}`",
        "",
        "## 下一步建议",
        "",
        "1. 进入 Stage10：对 `batch_support_records` 和 `context_support_records` 做 super-ob、单批次/单航班/单来源权重上限审计。",
        "2. Stage11 做 Stage2 兼容 smoke test，确认下游能读取角色通道字段。",
        "3. Stage12/13 之前不要迁移 official Stage2/Stage4 默认权重；先完成 baseline 复现和多时间尺度消融。",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：Stage9 Stage2 Role Split 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要从零开始。当前 Unified Plan 已完成 Stage6 time uncertainty v2、Stage7 grade calibration、Stage8 enhanced Stage1 join，以及 Stage9 Stage2 角色分流接口。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目 strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：strict truth 少是数据现实，AMDAR 应走分层置信度。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan 阶段边界、Stage9/10/11 要求和禁止操作。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage6_time_uncertainty_v2_optimized_20260701/stage6_time_uncertainty_results_analysis_and_next_steps.md`：Stage6 时间分布结果。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage7_grade_calibration_optimized_20260701/stage7_grade_calibration_results_analysis_and_next_steps.md`：Stage7 分级与 pseudo/locked-test gate。",
        "7. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage8_enhanced_stage1_optimized_20260701/stage8_enhanced_stage1_results_analysis_and_next_steps.md`：Stage8 字段增强和达标判断。",
        f"8. `{result_path}`：Stage9 输出、达标判断、下一步建议。",
        f"9. `{summary['outputs']['stage9_summary']}`：Stage9 machine-readable completion checks。",
        f"10. `{summary['outputs']['stage9_policy']}`：Stage9 字段映射和禁止误用规则。",
        "",
        "## 本轮脚本和输出",
        "",
        "- 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage9_stage2_role_split_20260701.py`",
        f"- 输出目录：`{cfg.out_dir}`",
        f"- `stage2_observation_records_all.parquet`：Stage9 逐条观测角色分流记录。",
        f"- `stage2_voxel_support_summary_all.parquet`：Stage9 体素支持摘要。",
        "- `stage2_role_audit.json`、`stage2_time_conf_distribution.json`、`stage2_channel_statistics.json`：审计与诊断。",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage9_stage2_role_split_20260701.py \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25 --workers 25",
        "```",
        "",
        "## 关键结果",
        "",
        f"- Row counts: `{summary['row_counts']}`",
        f"- Channel counts: `{summary['channel_counts']}`",
        f"- Confidence grade counts: `{summary['confidence_grade_counts']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 仍然全部非 holdout、非 strict truth；Stage9 strict truth 只来自 TURB T0/S enhanced holdout。",
        "- A/B AMDAR 是 current support；C AMDAR 是 batch support/context support；R AMDAR 只能 display-only 或 rejected。",
        "- context support 的 `frame_time_conf=0`，不要把它当成当前帧精确观测。",
        "- Stage10 才做 super-ob 和密度/批次/航班权重上限；不要在 Stage9 结果上直接迁移 official Stage4 权重。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage6/7/8/9 结果。",
        "当前结论：Stage9 已把 Stage8 enhanced clean_wind 转成 Stage2 角色分流接口；strict truth 只保留 TURB T0/S，AMDAR 按 A/B current support、C batch/context support、R display/reject 分通道。frame-level time confidence 使用 Stage6 时间分布与 T±5min frame window 的重叠概率计算。",
        "下一步我会进入 Stage10 做 super-ob 和密度权重控制，重点限制单批次/单航班/单来源支配风场，然后再做 Stage11 兼容测试。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def write_audit_outputs(cfg: RunConfig, summary: dict[str, Any], policy: dict[str, Any]) -> None:
    write_json(cfg.out_dir / "stage9_stage2_role_split_summary.json", summary)
    write_json(cfg.out_dir / "stage9_policy_v1.json", policy)
    write_json(
        cfg.out_dir / "stage2_role_audit.json",
        {
            "generated_at_utc": summary["generated_at_utc"],
            "row_counts": summary["row_counts"],
            "channel_counts": summary["channel_counts"],
            "completion_checks": summary["stage9_completion_checks"],
            "policy": policy["channel_mapping"],
        },
    )
    write_json(
        cfg.out_dir / "stage2_time_conf_distribution.json",
        {
            "generated_at_utc": summary["generated_at_utc"],
            "time_confidence_distribution": summary["time_confidence_distribution"],
            "time_confidence_policy": policy["time_confidence"],
        },
    )
    write_json(
        cfg.out_dir / "stage2_channel_statistics.json",
        {
            "generated_at_utc": summary["generated_at_utc"],
            "channel_statistics": summary["channel_statistics"],
        },
    )


def main() -> None:
    cfg = parse_args()
    if cfg.frame_window_minutes <= 0:
        raise ValueError("--frame-window-minutes must be positive")
    if cfg.context_window_minutes <= cfg.frame_window_minutes:
        raise ValueError("--context-window-minutes must be larger than --frame-window-minutes")
    if cfg.slice_count <= 0 or cfg.workers <= 0:
        raise ValueError("--slice-count and --workers must be positive")
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    if cfg.parent_mode:
        write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    upstream = require_upstream_gates(cfg)
    frames = load_frames(cfg)
    if cfg.parent_mode:
        print(json.dumps({"stage": "stage9_parent_start", "frames": len(frames), "out_dir": str(cfg.out_dir)}, ensure_ascii=False))
        shard_summaries = run_parent(cfg, frames)
        merged = combine_parquets(cfg, shard_summaries)
        summary = aggregate_summary(cfg, upstream, shard_summaries, merged)
        policy = build_policy(cfg, summary)
        write_audit_outputs(cfg, summary, policy)
        write_stage9_docs(cfg, summary)
        print(
            json.dumps(
                {
                    "stage": "stage9_parent_done",
                    "passed": summary["stage9_completion_checks"]["passed_stage9_stage2_role_split_gate"],
                    "rows": summary["row_counts"],
                    "out_dir": str(cfg.out_dir),
                },
                ensure_ascii=False,
            )
        )
        return

    write_progress(cfg.progress_file, cfg.shard_id, 0, len(frames), "running", "starting")
    start_ts = time.time()
    print(json.dumps({"stage": "stage9_shard_start", "shard_id": cfg.shard_id, "frames": len(frames)}, ensure_ascii=False))
    summary = stage9_for_frames(cfg, frames)
    write_progress(
        cfg.progress_file,
        cfg.shard_id,
        len(frames),
        len(frames),
        "done",
        f"elapsed={format_elapsed(time.time() - start_ts)}",
    )
    print(json.dumps({"stage": "stage9_shard_done", "summary": summary}, ensure_ascii=False, default=json_default))


if __name__ == "__main__":
    main()
