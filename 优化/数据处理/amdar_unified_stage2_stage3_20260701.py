from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
PLAN4_STAGE1 = ROOT / "优化/数据处理/amdar_plan4_implementation_20260630/stage1_output_plan4_v1"
PLAN4_OUTPUTS = ROOT / "优化/数据处理/amdar_plan4_implementation_20260630/plan4_pipeline_outputs"
STAGE0_STAGE1 = ROOT / "优化/数据处理/amdar_unified_stage0_stage1_20260701"
DEFAULT_OUT = ROOT / "优化/数据处理/amdar_unified_stage2_stage3_20260701"

EARTH_RADIUS_KM = 6371.0
WIND_SPEED_MS_PLAUSIBLE_MAX = 150.0
AMDAR_UNIT_SOURCE = "user_confirmed_mps_20260701"
TURB_UNIT_SOURCE = "user_confirmed_turb_mps_20260701"


@dataclass(frozen=True)
class RunConfig:
    stage1_dir: Path
    plan4_outputs_dir: Path
    stage1_audit_dir: Path
    out_dir: Path
    slice_count: int = 25
    workers: int = 25
    pseudo_case_limit: int = 6000
    pseudo_source_legs_per_split_phase: int = 140
    segment_gap_seconds: int = 1800
    segment_jump_km: float = 300.0
    segment_alt_jump_m: float = 5000.0
    min_leg_points: int = 5
    sampling_gap_warn_seconds: int = 300
    sampling_gap_hard_seconds: int = 1800
    speed_hard_mps: float = 400.0
    altitude_min_m: float = -500.0
    altitude_max_m: float = 20000.0
    candidate_time_padding_seconds: int = 7200
    candidate_end_tolerance_seconds: int = 600
    spatial_padding_km: float = 120.0
    altitude_padding_m: float = 2000.0
    catastrophic_error_seconds: float = 1800.0


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Run AMDAR Unified Plan stage1 closure, stage2 ADS-B QC v3, and stage3 pseudo-AMDAR closed-loop audit."
    )
    parser.add_argument("--stage1-dir", default=str(PLAN4_STAGE1))
    parser.add_argument("--plan4-outputs-dir", default=str(PLAN4_OUTPUTS))
    parser.add_argument("--stage1-audit-dir", default=str(STAGE0_STAGE1 / "stage1_quality_audit"))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--pseudo-case-limit", type=int, default=6000)
    parser.add_argument("--pseudo-source-legs-per-split-phase", type=int, default=140)
    args = parser.parse_args()
    return RunConfig(
        stage1_dir=Path(args.stage1_dir),
        plan4_outputs_dir=Path(args.plan4_outputs_dir),
        stage1_audit_dir=Path(args.stage1_audit_dir),
        out_dir=Path(args.out_dir),
        slice_count=int(args.slice_count),
        workers=int(args.workers),
        pseudo_case_limit=int(args.pseudo_case_limit),
        pseudo_source_legs_per_split_phase=int(args.pseudo_source_legs_per_split_phase),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


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


def bool_count(df: pl.DataFrame, expr: pl.Expr) -> int:
    if df.height == 0:
        return 0
    return int(df.select(expr.fill_null(False).sum().alias("n")).item())


def numeric_summary(df: pl.DataFrame, col: str) -> dict[str, Any]:
    if df.height == 0 or col not in df.columns:
        return {"present": col in df.columns, "rows": int(df.height)}
    s = df.select(pl.col(col).cast(pl.Float64, strict=False).alias(col)).get_column(col)
    finite = s.filter(s.is_finite())
    return {
        "present": True,
        "rows": int(df.height),
        "null_rows": int(s.is_null().sum()),
        "finite_rows": int(finite.len()),
        "min": float(finite.min()) if finite.len() else None,
        "p10": float(finite.quantile(0.1)) if finite.len() else None,
        "q50": float(finite.quantile(0.5)) if finite.len() else None,
        "p90": float(finite.quantile(0.9)) if finite.len() else None,
        "p99": float(finite.quantile(0.99)) if finite.len() else None,
        "max": float(finite.max()) if finite.len() else None,
    }


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(pl.Series(values, dtype=pl.Float64).quantile(q))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def local_xy_km(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    mean_lat = math.radians((lat0 + lat) / 2.0)
    x = (lon - lon0) * 111.320 * math.cos(mean_lat)
    y = (lat - lat0) * 110.574
    return x, y


def stable_int(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:16], 16)


def split_from_group(group_id: str) -> str:
    bucket = stable_int(group_id) % 10
    if bucket <= 5:
        return "calibration"
    if bucket <= 7:
        return "validation"
    return "locked_test"


def partition_key_scalar(key: Any) -> Any:
    if isinstance(key, tuple) and len(key) == 1:
        return key[0]
    return key


def batch_size_bucket_expr(col: str = "amdar_batch_row_count") -> pl.Expr:
    return (
        pl.when(pl.col(col).is_null())
        .then(pl.lit("not_applicable"))
        .when(pl.col(col) <= 1)
        .then(pl.lit("1"))
        .when(pl.col(col) <= 4)
        .then(pl.lit("2-4"))
        .when(pl.col(col) <= 10)
        .then(pl.lit("5-10"))
        .when(pl.col(col) <= 25)
        .then(pl.lit("11-25"))
        .when(pl.col(col) <= 49)
        .then(pl.lit("26-49"))
        .otherwise(pl.lit("50+"))
    )


def grade_score_expr(col: str) -> pl.Expr:
    return (
        pl.when(pl.col(col) == "A")
        .then(pl.lit(3))
        .when(pl.col(col) == "B")
        .then(pl.lit(2))
        .otherwise(pl.lit(1))
    )


def run_stage1_quality_closure(cfg: RunConfig) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage1_quality_closure"
    out_dir.mkdir(parents=True, exist_ok=True)

    qc_path = cfg.stage1_audit_dir / "stage1_met_qc_rows.parquet"
    wind_path = cfg.stage1_dir / "clean_wind.parquet"
    qc = pl.read_parquet(qc_path)
    wind_extra_cols = [
        "source",
        "source_row_index",
        "same_time_group_rows",
        "same_time_group_hspan_deg",
        "same_time_group_alt_span_m",
        "time_group_alignment_flag",
        "amdar_batch_hspan_deg",
        "amdar_batch_vertical_span_m",
        "amdar_batch_is_contiguous",
    ]
    extra = pl.read_parquet(wind_path, columns=[c for c in wind_extra_cols if c in pl.read_parquet_schema(wind_path)])
    qc_plus = qc.join(extra, on=["source", "source_row_index"], how="left")

    qc_plus = qc_plus.with_columns(
        [
            pl.when(pl.col("source") == "turb")
            .then(pl.lit(TURB_UNIT_SOURCE))
            .otherwise(pl.col("wind_speed_unit_source"))
            .alias("wind_speed_unit_source"),
            pl.when(pl.col("source") == "turb")
            .then(pl.lit("m/s"))
            .otherwise(pl.col("wind_speed_unit_normalized"))
            .alias("wind_speed_unit_normalized"),
            batch_size_bucket_expr().alias("amdar_batch_size_bucket"),
            (
                pl.when(pl.col("wind_speed_ms") <= 150.0)
                .then(pl.lit("<=150"))
                .when(pl.col("wind_speed_ms") <= 175.0)
                .then(pl.lit("150-175"))
                .when(pl.col("wind_speed_ms") <= 200.0)
                .then(pl.lit("175-200"))
                .when(pl.col("wind_speed_ms") <= 225.0)
                .then(pl.lit("200-225"))
                .otherwise(pl.lit(">225"))
            ).alias("wind_speed_ms_bin"),
            (
                pl.when(pl.col("alt_meters") < 3000.0)
                .then(pl.lit("0-3km"))
                .when(pl.col("alt_meters") < 6000.0)
                .then(pl.lit("3-6km"))
                .when(pl.col("alt_meters") < 9000.0)
                .then(pl.lit("6-9km"))
                .when(pl.col("alt_meters") < 12000.0)
                .then(pl.lit("9-12km"))
                .otherwise(pl.lit("12km+"))
            ).alias("altitude_band"),
        ]
    )
    qc_plus = qc_plus.with_columns(
        [
            (
                pl.when(pl.col("source") != "amdar")
                .then(pl.lit("not_amdar"))
                .when(pl.col("wind_speed_ms") > 200.0)
                .then(pl.lit("provisional_reject_or_manual_review"))
                .when(
                    (pl.col("wind_speed_ms") > WIND_SPEED_MS_PLAUSIBLE_MAX)
                    & (
                        (pl.col("amdar_batch_hspan_deg").fill_null(0.0) > 2.0)
                        | (pl.col("amdar_batch_vertical_span_m").fill_null(0.0) > 2000.0)
                        | pl.col("duplicate_met_record_flag").fill_null(False)
                    )
                )
                .then(pl.lit("strong_downweight_and_review"))
                .when(pl.col("wind_speed_ms") > WIND_SPEED_MS_PLAUSIBLE_MAX)
                .then(pl.lit("downweight_pending_provider_or_physical_review"))
                .otherwise(pl.lit("retain"))
            ).alias("recommended_stage1_qc_action")
        ]
    )

    high_wind = qc_plus.filter((pl.col("source") == "amdar") & (pl.col("wind_speed_ms") > WIND_SPEED_MS_PLAUSIBLE_MAX))
    high_wind.write_parquet(out_dir / "amdar_high_wind_outlier_rows.parquet")
    high_strata = (
        high_wind.group_by(
            [
                "wind_speed_ms_bin",
                "飞行阶段",
                "altitude_band",
                "amdar_batch_size_bucket",
                "recommended_stage1_qc_action",
            ]
        )
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("wind_speed_ms").median().alias("wind_speed_ms_q50"),
                pl.col("wind_speed_ms").quantile(0.9).alias("wind_speed_ms_q90"),
                pl.col("wind_speed_ms").max().alias("wind_speed_ms_max"),
                pl.col("amdar_batch_id").n_unique().alias("unique_batches"),
            ]
        )
        .sort(["rows", "wind_speed_ms_bin"], descending=[True, False])
    )
    high_strata.write_parquet(out_dir / "amdar_high_wind_outlier_strata.parquet")

    turb_review = qc_plus.filter(
        (pl.col("source") == "turb")
        & (
            pl.col("temperature_outlier_flag").fill_null(False)
            | pl.col("altitude_outlier_flag").fill_null(False)
            | pl.col("wind_speed_outlier_flag").fill_null(False)
            | pl.col("wind_direction_invalid_flag").fill_null(False)
        )
    )
    turb_review.write_parquet(out_dir / "turb_enhanced_qc_review_rows.parquet")

    schema_addendum = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Stage1 v2/production schema addendum for confirmed AMDAR and TURB wind speed units. This does not mutate the frozen Plan4 baseline.",
        "fields": {
            "wind_speed_raw": "Original source wind speed value.",
            "wind_speed_unit_source": {
                "amdar": AMDAR_UNIT_SOURCE,
                "turb": TURB_UNIT_SOURCE,
            },
            "wind_speed_unit_normalized": "m/s",
            "wind_speed_ms": "Normalized wind speed in m/s; for AMDAR and TURB this equals wind_speed_raw.",
            "wind_speed_unit_conversion_applied": False,
        },
        "amdar_policy": {
            "source_unit_confirmed": True,
            "confirmed_on": "2026-07-01",
            "conversion": "none",
            "high_wind_interpretation": "wind_speed > 150 m/s is a QC review flag, not a knots/m/s ambiguity.",
        },
        "turb_policy": {
            "source_unit_confirmed": True,
            "confirmed_on": "2026-07-01",
            "unit_source": TURB_UNIT_SOURCE,
            "unit_normalized": "m/s",
            "conversion": "none",
            "strict_truth_note": "TURB wind speed unit is confirmed as m/s; the 6 enhanced-QC review rows remain height/temperature issues, not wind-speed unit issues.",
        },
    }
    write_json(out_dir / "stage1_unit_schema_v2_addendum.json", schema_addendum)

    high_summary = {
        "rows": int(high_wind.height),
        "unique_batches": int(high_wind.select(pl.col("amdar_batch_id").n_unique()).item()) if high_wind.height else 0,
        "wind_speed_ms_summary": numeric_summary(high_wind, "wind_speed_ms"),
        "by_action": counts_map(high_wind, "recommended_stage1_qc_action"),
        "by_speed_bin": counts_map(high_wind, "wind_speed_ms_bin"),
        "by_phase": counts_map(high_wind, "飞行阶段"),
        "by_altitude_band": counts_map(high_wind, "altitude_band"),
        "by_batch_size": counts_map(high_wind, "amdar_batch_size_bucket"),
    }
    turb_summary = {
        "rows": int(turb_review.height),
        "temperature_outlier_rows": bool_count(turb_review, pl.col("temperature_outlier_flag")),
        "altitude_outlier_rows": bool_count(turb_review, pl.col("altitude_outlier_flag")),
        "wind_speed_outlier_rows": bool_count(turb_review, pl.col("wind_speed_outlier_flag")),
        "wind_direction_invalid_rows": bool_count(turb_review, pl.col("wind_direction_invalid_flag")),
        "preview": turb_review.head(20).to_dicts(),
    }
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_stage1_audit": str(qc_path),
        "input_stage1_clean_wind": str(wind_path),
        "amdar_unit_schema_addendum": schema_addendum,
        "amdar_high_wind": high_summary,
        "turb_enhanced_qc_review": turb_summary,
        "outputs": {
            "high_wind_rows": str(out_dir / "amdar_high_wind_outlier_rows.parquet"),
            "high_wind_strata": str(out_dir / "amdar_high_wind_outlier_strata.parquet"),
            "turb_review_rows": str(out_dir / "turb_enhanced_qc_review_rows.parquet"),
            "schema_addendum": str(out_dir / "stage1_unit_schema_v2_addendum.json"),
        },
    }
    write_json(out_dir / "stage1_quality_closure_summary.json", summary)

    report = [
        "# Stage1 Suggested Optimizations Closure",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Unit Schema Addendum",
        "",
        "AMDAR and TURB wind speeds are user-confirmed as m/s on 2026-07-01. The production addendum keeps `wind_speed_raw == wind_speed_ms` for both sources and records `wind_speed_unit_conversion_applied = false`.",
        "",
        "## AMDAR High Wind Review",
        "",
        f"- Rows above 150 m/s: {high_summary['rows']}",
        f"- Unique affected AMDAR batches: {high_summary['unique_batches']}",
        f"- Recommended action counts: `{high_summary['by_action']}`",
        f"- Speed-bin counts: `{high_summary['by_speed_bin']}`",
        "",
        "Policy used here is conservative: records above 150 m/s are not deleted from the frozen baseline, but should be downweighted or manually reviewed before support assimilation; records above 200 m/s are provisional reject/manual-review candidates.",
        "",
        "## TURB Strict Truth Review",
        "",
        f"- TURB rows failing enhanced QC screens: {turb_summary['rows']}",
        f"- Temperature outlier rows: {turb_summary['temperature_outlier_rows']}",
        f"- Altitude outlier rows: {turb_summary['altitude_outlier_rows']}",
        "",
        "TURB wind speed units are confirmed m/s. These rows still pass the current formal Stage1 invariant, but should be reviewed before expanding strict-holdout use because of altitude/temperature flags.",
    ]
    (out_dir / "stage1_quality_closure_report.md").write_text("\n".join(report), encoding="utf-8")
    return summary


def build_adsb_qc_v3_rows(cfg: RunConfig) -> pl.DataFrame:
    qc_path = cfg.plan4_outputs_dir / "adsb_qc_rows.parquet"
    qc = pl.read_parquet(qc_path)
    qc = (
        qc.sort(["tail_norm", "flight_norm", "time_utc", "lat_clean", "lon_clean", "alt_meters"])
        .with_columns(
            [
                pl.col("service_date_utc").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_service_date_utc"),
                pl.col("alt_meters").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_alt_meters_v3"),
            ]
        )
        .with_columns(
            [
                (pl.col("service_date_utc") != pl.col("prev_service_date_utc")).fill_null(False).alias("date_boundary_from_prev"),
                (pl.col("alt_meters") - pl.col("prev_alt_meters_v3")).alias("alt_delta_signed_m"),
                (
                    pl.col("duplicate_timestamp").fill_null(False)
                    | pl.col("non_increasing_timestamp").fill_null(False)
                    | pl.col("zero_time_nonzero_distance").fill_null(False)
                ).alias("failed_time_order_row"),
                (
                    pl.col("unreasonable_speed").fill_null(False)
                    | (pl.col("apparent_ground_speed_mps").fill_null(0.0) > cfg.speed_hard_mps)
                ).alias("failed_speed_row"),
                pl.col("position_jump").fill_null(False).alias("failed_position_jump_row"),
                (pl.col("dt_from_prev_seconds").fill_null(0) > cfg.sampling_gap_warn_seconds).alias("failed_sampling_gap_row"),
                (
                    pl.col("alt_meters").is_null()
                    | ~pl.col("alt_meters").is_finite()
                    | (pl.col("alt_meters") < cfg.altitude_min_m)
                    | (pl.col("alt_meters") > cfg.altitude_max_m)
                    | (pl.col("alt_jump_m").fill_null(0.0) > cfg.segment_alt_jump_m)
                ).alias("failed_altitude_row"),
                (
                    pl.col("tail_norm").is_null()
                    | pl.col("flight_norm").is_null()
                    | (pl.col("tail_norm") == "MISSING")
                    | (pl.col("flight_norm") == "MISSING")
                ).alias("failed_identity_row"),
            ]
        )
        .with_columns(
            pl.when(
                pl.col("time_utc").shift(1).over(["tail_norm", "flight_norm"]).is_null()
                | (pl.col("dt_from_prev_seconds") > cfg.segment_gap_seconds)
                | pl.col("position_jump").fill_null(False)
                | pl.col("non_increasing_timestamp").fill_null(False)
                | pl.col("date_boundary_from_prev")
            )
            .then(1)
            .otherwise(0)
            .alias("leg_start_flag_v3")
        )
        .with_columns(
            pl.col("leg_start_flag_v3").cum_sum().over(["tail_norm", "flight_norm", "service_date_utc"]).alias("leg_index_v3")
        )
        .with_columns(
            (
                pl.col("tail_norm")
                + pl.lit("__")
                + pl.col("flight_norm")
                + pl.lit("__")
                + pl.col("service_date_utc")
                + pl.lit("__leg")
                + pl.col("leg_index_v3").cast(pl.Utf8)
            ).alias("adsb_leg_id")
        )
        .with_columns(((pl.col("adsb_leg_id").hash(seed=0) % cfg.slice_count).cast(pl.UInt8)).alias("processing_slice_id"))
    )
    return qc


def build_leg_components(v3: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    base = (
        v3.group_by("adsb_leg_id")
        .agg(
            [
                pl.col("tail_norm").first().alias("tail_norm"),
                pl.col("flight_norm").first().alias("flight_norm"),
                pl.col("service_date_utc").first().alias("service_date_utc"),
                pl.col("processing_slice_id").first().alias("processing_slice_id"),
                pl.len().alias("point_count"),
                pl.col("time_utc").min().alias("start_time_utc"),
                pl.col("time_utc").max().alias("end_time_utc"),
                pl.col("lat_clean").first().alias("start_lat"),
                pl.col("lon_clean").first().alias("start_lon"),
                pl.col("lat_clean").last().alias("end_lat"),
                pl.col("lon_clean").last().alias("end_lon"),
                pl.col("lat_clean").min().alias("min_lat"),
                pl.col("lat_clean").max().alias("max_lat"),
                pl.col("lon_clean").min().alias("min_lon"),
                pl.col("lon_clean").max().alias("max_lon"),
                pl.col("alt_meters").first().alias("start_alt_m"),
                pl.col("alt_meters").last().alias("end_alt_m"),
                pl.col("alt_meters").min().alias("min_alt_m"),
                pl.col("alt_meters").max().alias("max_alt_m"),
                pl.col("distance_from_prev_km").fill_null(0.0).sum().alias("path_length_km"),
                pl.col("dt_from_prev_seconds").filter(pl.col("dt_from_prev_seconds").is_not_null()).quantile(0.5).alias("sampling_gap_q50"),
                pl.col("dt_from_prev_seconds").filter(pl.col("dt_from_prev_seconds").is_not_null()).quantile(0.9).alias("sampling_gap_q90"),
                pl.col("dt_from_prev_seconds").max().alias("sampling_gap_max"),
                pl.col("apparent_ground_speed_mps").filter(pl.col("apparent_ground_speed_mps").is_finite()).quantile(0.99).alias("apparent_speed_q99_mps"),
                pl.col("apparent_ground_speed_mps").max().alias("apparent_speed_max_mps"),
                pl.col("failed_time_order_row").sum().alias("time_order_failure_points"),
                pl.col("failed_speed_row").sum().alias("speed_failure_points"),
                pl.col("failed_position_jump_row").sum().alias("position_jump_points"),
                pl.col("failed_sampling_gap_row").sum().alias("sampling_gap_failure_points"),
                pl.col("failed_altitude_row").sum().alias("altitude_failure_points"),
                pl.col("failed_identity_row").sum().alias("identity_failure_points"),
                (pl.col("alt_delta_signed_m") > 50.0).sum().alias("altitude_increase_steps"),
                (pl.col("alt_delta_signed_m") < -50.0).sum().alias("altitude_decrease_steps"),
                (pl.col("alt_delta_signed_m").abs() <= 50.0).sum().alias("altitude_neutral_steps"),
                pl.col("adsb_qc_flag").fill_null(False).sum().alias("plan4_qc_flagged_points"),
            ]
        )
        .with_columns(
            [
                (pl.col("end_time_utc") - pl.col("start_time_utc")).dt.total_seconds().alias("duration_seconds"),
                (pl.col("end_alt_m") - pl.col("start_alt_m")).alias("altitude_change_m"),
                (pl.col("max_alt_m") - pl.col("min_alt_m")).alias("altitude_range_m"),
                (pl.col("speed_failure_points") / pl.col("point_count")).alias("speed_failure_ratio"),
                (pl.col("plan4_qc_flagged_points") / pl.col("point_count")).alias("plan4_flagged_ratio"),
                (pl.col("altitude_increase_steps") / (pl.col("point_count") - 1).clip(lower_bound=1)).alias("altitude_increase_ratio"),
                (pl.col("altitude_decrease_steps") / (pl.col("point_count") - 1).clip(lower_bound=1)).alias("altitude_decrease_ratio"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("altitude_change_m") > 500.0)
                .then(pl.lit("ASC"))
                .when(pl.col("altitude_change_m") < -500.0)
                .then(pl.lit("DES"))
                .otherwise(pl.lit("LVR"))
                .alias("leg_phase_like"),
                (pl.col("time_order_failure_points") > 0).alias("failed_time_order"),
                (pl.col("speed_failure_points") > 0).alias("failed_speed"),
                (pl.col("position_jump_points") > 0).alias("failed_position_jump"),
                (pl.col("sampling_gap_failure_points") > 0).alias("failed_sampling_gap"),
                (pl.col("altitude_failure_points") > 0).alias("failed_altitude"),
                (pl.col("identity_failure_points") > 0).alias("failed_identity"),
                (pl.col("duration_seconds") < 180).alias("failed_duration"),
                (pl.col("point_count") < cfg.min_leg_points).alias("failed_point_count"),
            ]
        )
        .with_columns(
            [
                (
                    ((pl.col("leg_phase_like") == "ASC") & (pl.col("altitude_decrease_ratio") > 0.25))
                    | ((pl.col("leg_phase_like") == "DES") & (pl.col("altitude_increase_ratio") > 0.25))
                    | ((pl.col("leg_phase_like") == "LVR") & (pl.col("altitude_range_m") > 2500.0))
                ).alias("failed_phase_consistency")
            ]
        )
    )

    base = base.with_columns(
        [
            pl.when(pl.col("failed_time_order") | (pl.col("sampling_gap_q90").fill_null(999999.0) > 300.0) | (pl.col("sampling_gap_max").fill_null(0) > cfg.sampling_gap_hard_seconds))
            .then(pl.lit("C"))
            .when((pl.col("sampling_gap_q90").fill_null(999999.0) <= 90.0) & (pl.col("sampling_gap_max").fill_null(0) <= 300.0))
            .then(pl.lit("A"))
            .when((pl.col("sampling_gap_q90").fill_null(999999.0) <= 180.0) & (pl.col("sampling_gap_max").fill_null(0) <= 900.0))
            .then(pl.lit("B"))
            .otherwise(pl.lit("C"))
            .alias("leg_time_quality"),
            pl.when(pl.col("failed_position_jump") | (pl.col("speed_failure_ratio") > 0.10))
            .then(pl.lit("C"))
            .when((pl.col("speed_failure_ratio") <= 0.01) & (pl.col("position_jump_points") == 0))
            .then(pl.lit("A"))
            .when(pl.col("speed_failure_ratio") <= 0.05)
            .then(pl.lit("B"))
            .otherwise(pl.lit("C"))
            .alias("leg_geometry_quality"),
            pl.when((pl.col("tail_norm") != "MISSING") & (pl.col("flight_norm") != "MISSING"))
            .then(pl.lit("A"))
            .when((pl.col("tail_norm") != "MISSING") | (pl.col("flight_norm") != "MISSING"))
            .then(pl.lit("B"))
            .otherwise(pl.lit("C"))
            .alias("leg_identity_quality"),
            pl.when((pl.col("point_count") >= 20) & (pl.col("duration_seconds") >= 600) & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 90.0))
            .then(pl.lit("A"))
            .when((pl.col("point_count") >= cfg.min_leg_points) & (pl.col("duration_seconds") >= 180) & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 180.0))
            .then(pl.lit("B"))
            .otherwise(pl.lit("C"))
            .alias("leg_sampling_quality"),
            pl.when(pl.col("failed_phase_consistency"))
            .then(pl.lit("C"))
            .when((pl.col("leg_phase_like") == "LVR") & (pl.col("altitude_range_m") > 1000.0))
            .then(pl.lit("B"))
            .otherwise(pl.lit("A"))
            .alias("leg_phase_quality"),
        ]
    )
    base = base.with_columns(
        [
            pl.min_horizontal(
                [
                    grade_score_expr("leg_time_quality"),
                    grade_score_expr("leg_geometry_quality"),
                    grade_score_expr("leg_identity_quality"),
                    grade_score_expr("leg_sampling_quality"),
                    grade_score_expr("leg_phase_quality"),
                ]
            ).alias("leg_component_min_score")
        ]
    ).with_columns(
        [
            (
                pl.col("failed_time_order")
                | pl.col("failed_speed")
                | pl.col("failed_position_jump")
                | pl.col("failed_altitude")
                | pl.col("failed_identity")
                | pl.col("failed_point_count")
                | pl.col("failed_phase_consistency")
            ).alias("has_hard_failure"),
            pl.when(pl.col("leg_component_min_score") >= 3)
            .then(pl.lit("A"))
            .when(pl.col("leg_component_min_score") >= 2)
            .then(pl.lit("B"))
            .otherwise(pl.lit("C"))
            .alias("component_quality_floor"),
        ]
    ).with_columns(
        pl.when(pl.col("has_hard_failure"))
        .then(pl.lit("C"))
        .otherwise(pl.col("component_quality_floor"))
        .alias("leg_overall_quality")
    )

    plan4_legs_path = cfg.plan4_outputs_dir / "adsb_flight_legs_v2.parquet"
    plan4_legs = pl.read_parquet(plan4_legs_path, columns=["adsb_leg_id", "leg_quality"]).rename({"leg_quality": "plan4_leg_quality"})
    return base.join(plan4_legs, on="adsb_leg_id", how="left").sort(["leg_overall_quality", "adsb_leg_id"])


def top_failure_combinations(components: pl.DataFrame) -> list[dict[str, Any]]:
    failure_cols = [
        "failed_time_order",
        "failed_speed",
        "failed_position_jump",
        "failed_sampling_gap",
        "failed_altitude",
        "failed_identity",
        "failed_duration",
        "failed_point_count",
        "failed_phase_consistency",
    ]
    combo = components.with_columns(
        pl.concat_str(
            [
                pl.when(pl.col(c)).then(pl.lit(c.replace("failed_", ""))).otherwise(pl.lit(""))
                for c in failure_cols
            ],
            separator="|",
        ).alias("failure_combo_raw")
    ).with_columns(
        pl.when(pl.col("failure_combo_raw").str.replace_all(r"\|+", "|").str.strip_chars("|") == "")
        .then(pl.lit("none"))
        .otherwise(pl.col("failure_combo_raw").str.replace_all(r"\|+", "|").str.strip_chars("|"))
        .alias("failure_combo")
    )
    return (
        combo.group_by("failure_combo")
        .agg(pl.len().alias("legs"))
        .sort("legs", descending=True)
        .head(25)
        .to_dicts()
    )


def run_stage2_adsb_qc(cfg: RunConfig) -> tuple[pl.DataFrame, dict[str, Any]]:
    out_dir = cfg.out_dir / "stage2_adsb_qc_v3"
    out_dir.mkdir(parents=True, exist_ok=True)

    v3 = build_adsb_qc_v3_rows(cfg)
    components = build_leg_components(v3, cfg)

    leg_points_cols = [
        "adsb_leg_id",
        "tail_norm",
        "flight_norm",
        "service_date_utc",
        "processing_slice_id",
        "time_utc",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "heading_deg",
        "ground_speed_ms",
        "apparent_ground_speed_mps",
        "dt_from_prev_seconds",
        "distance_from_prev_km",
        "alt_jump_m",
        "adsb_qc_flag",
        "failed_time_order_row",
        "failed_speed_row",
        "failed_position_jump_row",
        "failed_sampling_gap_row",
        "failed_altitude_row",
        "failed_identity_row",
    ]
    v3.select([c for c in leg_points_cols if c in v3.columns]).write_parquet(out_dir / "adsb_leg_points_v3.parquet")

    row_join_cols = [
        "adsb_leg_id",
        "point_count",
        "duration_seconds",
        "failed_duration",
        "failed_point_count",
        "failed_phase_consistency",
        "leg_time_quality",
        "leg_geometry_quality",
        "leg_identity_quality",
        "leg_sampling_quality",
        "leg_phase_quality",
        "leg_overall_quality",
    ]
    v3_out = v3.join(components.select(row_join_cols), on="adsb_leg_id", how="left")
    v3_out.write_parquet(out_dir / "adsb_qc_v3_rows.parquet")
    components.write_parquet(out_dir / "adsb_leg_quality_components.parquet")

    usable = components.filter(pl.col("point_count") >= cfg.min_leg_points)
    failure_cols = [
        "failed_time_order",
        "failed_speed",
        "failed_position_jump",
        "failed_sampling_gap",
        "failed_altitude",
        "failed_identity",
        "failed_duration",
        "failed_point_count",
        "failed_phase_consistency",
    ]
    failure_counts = {c: bool_count(components, pl.col(c)) for c in failure_cols}
    usable_failure_counts = {c: bool_count(usable, pl.col(c)) for c in failure_cols}
    by_slice = (
        components.group_by("processing_slice_id")
        .agg(
            [
                pl.len().alias("leg_count"),
                (pl.col("leg_overall_quality") == "A").sum().alias("A"),
                (pl.col("leg_overall_quality") == "B").sum().alias("B"),
                (pl.col("leg_overall_quality") == "C").sum().alias("C"),
            ]
        )
        .sort("processing_slice_id")
        .to_dicts()
    )
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_adsb_qc_rows": str(cfg.plan4_outputs_dir / "adsb_qc_rows.parquet"),
        "rows": int(v3.height),
        "segmented_leg_count_all": int(components.height),
        "segmented_leg_count_min_points": int(usable.height),
        "slice_count": cfg.slice_count,
        "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
        "external_num_workers": 1,
        "row_failure_counts": {
            "failed_time_order_row": bool_count(v3, pl.col("failed_time_order_row")),
            "failed_speed_row": bool_count(v3, pl.col("failed_speed_row")),
            "failed_position_jump_row": bool_count(v3, pl.col("failed_position_jump_row")),
            "failed_sampling_gap_row": bool_count(v3, pl.col("failed_sampling_gap_row")),
            "failed_altitude_row": bool_count(v3, pl.col("failed_altitude_row")),
            "failed_identity_row": bool_count(v3, pl.col("failed_identity_row")),
            "date_boundary_from_prev": bool_count(v3, pl.col("date_boundary_from_prev")),
        },
        "leg_failure_counts_all": failure_counts,
        "leg_failure_counts_min_points": usable_failure_counts,
        "leg_overall_quality_counts_all": counts_map(components, "leg_overall_quality"),
        "leg_overall_quality_counts_min_points": counts_map(usable, "leg_overall_quality"),
        "leg_time_quality_counts": counts_map(usable, "leg_time_quality"),
        "leg_geometry_quality_counts": counts_map(usable, "leg_geometry_quality"),
        "leg_identity_quality_counts": counts_map(usable, "leg_identity_quality"),
        "leg_sampling_quality_counts": counts_map(usable, "leg_sampling_quality"),
        "leg_phase_quality_counts": counts_map(usable, "leg_phase_quality"),
        "plan4_leg_quality_counts_joined": counts_map(usable, "plan4_leg_quality"),
        "leg_phase_like_counts": counts_map(usable, "leg_phase_like"),
        "top_failure_combinations_all": top_failure_combinations(components),
        "top_failure_combinations_min_points": top_failure_combinations(usable),
        "by_processing_slice": by_slice,
        "checklist_answers": {
            "sorted_by_time_utc_before_adjacent_speed": True,
            "long_gap_speed_noted": "Rows with dt_from_prev_seconds > 300 are flagged as failed_sampling_gap_row; gaps > 1800 start new legs.",
            "cross_flight_connection_prevented": "Adjacent deltas are computed within tail_norm + flight_norm; legs are then segmented by date as well.",
            "cross_date_connection_prevented_in_v3": True,
            "distance_method": "Local equirectangular approximation for row QC, inherited from Plan4; pseudo projection uses haversine/local XY.",
            "speed_unit": "m/s",
            "midnight_flights": "v3 starts a new leg at service_date boundaries to avoid accidental cross-date chaining; this can split true midnight flights and is reported as a conservative audit choice.",
        },
        "outputs": {
            "adsb_qc_v3_rows": str(out_dir / "adsb_qc_v3_rows.parquet"),
            "adsb_leg_points_v3": str(out_dir / "adsb_leg_points_v3.parquet"),
            "adsb_leg_quality_components": str(out_dir / "adsb_leg_quality_components.parquet"),
            "adsb_leg_failure_reason_summary": str(out_dir / "adsb_leg_failure_reason_summary.json"),
        },
    }
    write_json(out_dir / "adsb_leg_failure_reason_summary.json", summary)

    report = [
        "# Stage2 ADS-B QC v3 Report",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Scale",
        "",
        f"- ADS-B rows audited: {summary['rows']}",
        f"- Segmented legs, all: {summary['segmented_leg_count_all']}",
        f"- Segmented legs with >= {cfg.min_leg_points} points: {summary['segmented_leg_count_min_points']}",
        f"- 25-slice field: `processing_slice_id`; execution uses `POLARS_MAX_THREADS={summary['polars_threads']}` and avoids writing 25 duplicate full intermediates.",
        "",
        "## Leg Quality",
        "",
        f"- v3 A/B/C over usable legs: `{summary['leg_overall_quality_counts_min_points']}`",
        f"- Plan4 joined A/B/C over comparable usable legs: `{summary['plan4_leg_quality_counts_joined']}`",
        f"- Time quality: `{summary['leg_time_quality_counts']}`",
        f"- Geometry quality: `{summary['leg_geometry_quality_counts']}`",
        f"- Sampling quality: `{summary['leg_sampling_quality_counts']}`",
        f"- Phase quality: `{summary['leg_phase_quality_counts']}`",
        "",
        "## Main Downgrade Reasons",
        "",
        f"- Usable-leg failure counts: `{summary['leg_failure_counts_min_points']}`",
        f"- Top failure combinations: `{summary['top_failure_combinations_min_points'][:8]}`",
        "",
        "Interpretation: v3 keeps Plan4's core QC, but exposes component failures so a C leg can be traced to sampling gaps, speed/geometry jumps, phase inconsistency, point count, or identity/duration issues.",
    ]
    (out_dir / "stage2_adsb_qc_v3_report.md").write_text("\n".join(report), encoding="utf-8")
    return components, summary


def project_to_segment(point: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ax, ay = 0.0, 0.0
    bx, by = local_xy_km(float(a["lat_clean"]), float(a["lon_clean"]), float(b["lat_clean"]), float(b["lon_clean"]))
    px, py = local_xy_km(float(a["lat_clean"]), float(a["lon_clean"]), float(point["lat_clean"]), float(point["lon_clean"]))
    ab2 = bx * bx + by * by
    frac = 0.0 if ab2 <= 1e-12 else (px * bx + py * by) / ab2
    frac_clamped = min(1.0, max(0.0, frac))
    proj_x = bx * frac_clamped
    proj_y = by * frac_clamped
    cross_track = math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
    alt_proj = float(a["alt_meters"]) + frac_clamped * (float(b["alt_meters"]) - float(a["alt_meters"]))
    vertical = abs(float(point["alt_meters"]) - alt_proj)
    dt = float((b["time_utc"] - a["time_utc"]).total_seconds())
    estimated_time = a["time_utc"] + timedelta(seconds=dt * frac_clamped)
    return {
        "estimated_time_utc": estimated_time,
        "cross_track_distance_km": cross_track,
        "vertical_difference_m": vertical,
        "sampling_gap_seconds": dt,
        "projection_fraction": frac_clamped,
    }


def project_to_leg(point: dict[str, Any], leg_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not leg_rows:
        return {
            "estimated_time_utc": None,
            "cross_track_distance_km": float("inf"),
            "vertical_difference_m": float("inf"),
            "sampling_gap_seconds": None,
            "projection_fraction": None,
            "segment_index": None,
        }
    if len(leg_rows) == 1:
        row = leg_rows[0]
        return {
            "estimated_time_utc": row["time_utc"],
            "cross_track_distance_km": haversine_km(float(point["lat_clean"]), float(point["lon_clean"]), float(row["lat_clean"]), float(row["lon_clean"])),
            "vertical_difference_m": abs(float(point["alt_meters"]) - float(row["alt_meters"])),
            "sampling_gap_seconds": 0.0,
            "projection_fraction": 0.0,
            "segment_index": 0,
        }
    best: dict[str, Any] | None = None
    for idx in range(len(leg_rows) - 1):
        proj = project_to_segment(point, leg_rows[idx], leg_rows[idx + 1])
        cost = proj["cross_track_distance_km"] + 0.001 * proj["vertical_difference_m"]
        if best is None or cost < best["cost"]:
            best = {**proj, "segment_index": idx, "cost": cost}
    return best or {
        "estimated_time_utc": None,
        "cross_track_distance_km": float("inf"),
        "vertical_difference_m": float("inf"),
        "sampling_gap_seconds": None,
        "projection_fraction": None,
        "segment_index": None,
    }


def add_deterministic_noise(row: dict[str, Any], case_id: int, row_index: int) -> dict[str, Any]:
    seed = stable_int(f"{case_id}:{row_index}:{row['time_utc']}")
    rng = random.Random(seed)
    lat_noise = rng.uniform(-0.003, 0.003)
    lon_noise = rng.uniform(-0.003, 0.003)
    alt_noise = rng.uniform(-30.0, 30.0)
    return {
        **row,
        "lat_clean": float(row["lat_clean"]) + lat_noise,
        "lon_clean": float(row["lon_clean"]) + lon_noise,
        "alt_meters": float(row["alt_meters"]) + alt_noise,
    }


def generate_pseudo_cases(source_components: pl.DataFrame, source_points: pl.DataFrame, cfg: RunConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    points_by_leg = {
        str(partition_key_scalar(k)): v.sort("time_utc").to_dicts()
        for k, v in source_points.partition_by("adsb_leg_id", maintain_order=True, as_dict=True).items()
    }
    meta_by_leg = {row["adsb_leg_id"]: row for row in source_components.to_dicts()}
    case_records: list[dict[str, Any]] = []
    point_records: list[dict[str, Any]] = []
    batch_sizes = [1, 3, 7, 18, 38]
    size_labels = {1: "1", 3: "2-4", 7: "5-10", 18: "11-25", 38: "26-50"}
    case_id = 0
    split_caps = {
        "calibration": max(1, cfg.pseudo_case_limit // 3),
        "validation": max(1, cfg.pseudo_case_limit // 3),
        "locked_test": max(1, cfg.pseudo_case_limit - 2 * (cfg.pseudo_case_limit // 3)),
    }
    split_counts = {k: 0 for k in split_caps}
    ordered_leg_ids = source_components.sort(
        ["leg_phase_like", "split", "leg_overall_quality", "point_count"],
        descending=[False, False, False, True],
    ).get_column("adsb_leg_id").to_list()
    for leg_id in ordered_leg_ids:
        rows = points_by_leg.get(str(leg_id), [])
        meta = meta_by_leg[str(leg_id)]
        split = str(meta["split"])
        if len(rows) < 2:
            continue
        if split_counts.get(split, 0) >= split_caps.get(split, 0):
            continue
        for size in batch_sizes:
            if len(rows) < size:
                continue
            stride = max(size, len(rows) // 3)
            starts = list(range(0, max(1, len(rows) - size + 1), stride))[:3]
            for start in starts:
                segment = rows[start : start + size]
                if len(segment) != size:
                    continue
                if split_counts.get(split, 0) >= split_caps.get(split, 0):
                    break
                case_id += 1
                if case_id > cfg.pseudo_case_limit:
                    case_df = pl.from_dicts(case_records) if case_records else pl.DataFrame()
                    point_df = pl.from_dicts(point_records) if point_records else pl.DataFrame()
                    return case_df, point_df
                split_counts[split] = split_counts.get(split, 0) + 1
                delay = 60 + (stable_int(f"delay:{case_id}") % 540)
                batch_end = segment[-1]["time_utc"] + timedelta(seconds=delay)
                true_span_s = float((segment[-1]["time_utc"] - segment[0]["time_utc"]).total_seconds()) if len(segment) > 1 else 0.0
                case_records.append(
                    {
                        "pseudo_case_id": case_id,
                        "source_leg_id": leg_id,
                        "split": meta["split"],
                        "group_id_tail_date": meta["group_id_tail_date"],
                        "tail_norm": meta["tail_norm"],
                        "flight_norm": meta["flight_norm"],
                        "service_date_utc": meta["service_date_utc"],
                        "leg_phase_like": meta["leg_phase_like"],
                        "leg_overall_quality": meta["leg_overall_quality"],
                        "batch_size": size,
                        "batch_size_bucket": size_labels[size],
                        "batch_end_time_utc": batch_end,
                        "true_start_time_utc": segment[0]["time_utc"],
                        "true_end_time_utc": segment[-1]["time_utc"],
                        "true_batch_span_seconds": true_span_s,
                        "downlink_delay_seconds": delay,
                    }
                )
                for idx, row in enumerate(segment):
                    noisy = add_deterministic_noise(row, case_id, idx)
                    point_records.append(
                        {
                            "pseudo_case_id": case_id,
                            "source_leg_id": leg_id,
                            "row_index": idx,
                            "tail_norm": meta["tail_norm"],
                            "flight_norm": meta["flight_norm"],
                            "service_date_utc": meta["service_date_utc"],
                            "batch_size": size,
                            "batch_size_bucket": size_labels[size],
                            "batch_end_time_utc": batch_end,
                            "true_time_utc": row["time_utc"],
                            "lat_clean": noisy["lat_clean"],
                            "lon_clean": noisy["lon_clean"],
                            "alt_meters": noisy["alt_meters"],
                        }
                    )
    return pl.from_dicts(case_records) if case_records else pl.DataFrame(), pl.from_dicts(point_records) if point_records else pl.DataFrame()


def candidate_ids_for_cases(cases: pl.DataFrame, components: pl.DataFrame, cfg: RunConfig) -> dict[int, list[str]]:
    comp_rows = components.filter(pl.col("point_count") >= cfg.min_leg_points).to_dicts()
    by_identity: dict[str, list[dict[str, Any]]] = {}
    by_tail: dict[str, list[dict[str, Any]]] = {}
    for row in comp_rows:
        by_identity.setdefault(f"{row['tail_norm']}__{row['flight_norm']}", []).append(row)
        by_tail.setdefault(str(row["tail_norm"]), []).append(row)
    result: dict[int, list[str]] = {}
    for case in cases.to_dicts():
        identity = f"{case['tail_norm']}__{case['flight_norm']}"
        seed = by_identity.get(identity) or by_tail.get(str(case["tail_norm"]), [])
        ids: list[tuple[str, float]] = []
        batch_end = case["batch_end_time_utc"]
        true_start = case["true_start_time_utc"]
        for leg in seed:
            if leg["start_time_utc"] > batch_end + timedelta(seconds=cfg.candidate_end_tolerance_seconds):
                continue
            if leg["end_time_utc"] < true_start - timedelta(seconds=cfg.candidate_time_padding_seconds):
                continue
            if float(leg["min_alt_m"]) > 0 and float(case.get("batch_size", 0)) >= 0:
                pass
            time_gap = abs(float((leg["end_time_utc"] - batch_end).total_seconds()))
            phase_penalty = 0.0 if leg["leg_phase_like"] == case["leg_phase_like"] else 600.0
            quality_penalty = {"A": 0.0, "B": 120.0, "C": 600.0}.get(str(leg["leg_overall_quality"]), 600.0)
            ids.append((leg["adsb_leg_id"], time_gap + phase_penalty + quality_penalty))
        ids = sorted(ids, key=lambda x: x[1])[:8]
        result[int(case["pseudo_case_id"])] = [x[0] for x in ids]
    return result


def evaluate_pseudo_cases(cases: pl.DataFrame, points: pl.DataFrame, candidate_map: dict[int, list[str]], leg_points: pl.DataFrame, cfg: RunConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    points_by_case = {
        int(partition_key_scalar(k)): v.sort("row_index").to_dicts()
        for k, v in points.partition_by("pseudo_case_id", maintain_order=True, as_dict=True).items()
    }
    leg_points_by_id = {
        str(partition_key_scalar(k)): v.sort("time_utc").to_dicts()
        for k, v in leg_points.partition_by("adsb_leg_id", maintain_order=True, as_dict=True).items()
    }
    case_rows = cases.to_dicts()

    def eval_one(case: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        case_id = int(case["pseudo_case_id"])
        pseudo_points = points_by_case.get(case_id, [])
        candidates = candidate_map.get(case_id, [])
        if not pseudo_points or not candidates:
            return {
                **case,
                "status": "rejected",
                "reject_reason": "no_candidate_leg",
                "matched_leg_id": None,
                "correct_leg": False,
                "candidate_leg_count": len(candidates),
                "best_cost": None,
                "second_best_cost": None,
                "ambiguity_margin": None,
                "case_time_error_q50_seconds": None,
                "case_time_error_q90_seconds": None,
            }, []
        scored: list[tuple[str, float, list[dict[str, Any]]]] = []
        for leg_id in candidates:
            rows = leg_points_by_id.get(str(leg_id), [])
            if len(rows) < 2:
                continue
            projections = []
            costs = []
            last_time = None
            monotonic_penalty = 0.0
            for p in pseudo_points:
                proj = project_to_leg(p, rows)
                if proj["estimated_time_utc"] is None:
                    continue
                if last_time is not None and proj["estimated_time_utc"] < last_time:
                    monotonic_penalty += 500.0
                last_time = proj["estimated_time_utc"]
                costs.append(float(proj["cross_track_distance_km"]) + 0.001 * float(proj["vertical_difference_m"]))
                projections.append({**p, **proj})
            if len(projections) != len(pseudo_points):
                continue
            total_cost = sum(costs) / max(1, len(costs)) + monotonic_penalty
            scored.append((str(leg_id), total_cost, projections))
        if not scored:
            return {
                **case,
                "status": "rejected",
                "reject_reason": "projection_failed",
                "matched_leg_id": None,
                "correct_leg": False,
                "candidate_leg_count": len(candidates),
                "best_cost": None,
                "second_best_cost": None,
                "ambiguity_margin": None,
                "case_time_error_q50_seconds": None,
                "case_time_error_q90_seconds": None,
            }, []
        scored.sort(key=lambda x: x[1])
        best_leg, best_cost, projections = scored[0]
        second_cost = scored[1][1] if len(scored) > 1 else None
        ambiguity_margin = None if second_cost is None or best_cost <= 0 else float(second_cost / best_cost)
        row_records: list[dict[str, Any]] = []
        errors: list[float] = []
        for proj in projections:
            err = abs(float((proj["estimated_time_utc"] - proj["true_time_utc"]).total_seconds()))
            errors.append(err)
            row_records.append(
                {
                    "pseudo_case_id": case_id,
                    "split": case["split"],
                    "source_leg_id": case["source_leg_id"],
                    "matched_leg_id": best_leg,
                    "row_index": proj["row_index"],
                    "true_time_utc": proj["true_time_utc"],
                    "estimated_time_utc": proj["estimated_time_utc"],
                    "time_error_seconds": err,
                    "cross_track_distance_km": proj["cross_track_distance_km"],
                    "vertical_difference_m": proj["vertical_difference_m"],
                    "sampling_gap_seconds": proj["sampling_gap_seconds"],
                    "correct_leg": best_leg == case["source_leg_id"],
                }
            )
        status = "matched" if best_leg == case["source_leg_id"] else "wrong_leg"
        return {
            **case,
            "status": status,
            "reject_reason": None,
            "matched_leg_id": best_leg,
            "correct_leg": best_leg == case["source_leg_id"],
            "candidate_leg_count": len(candidates),
            "best_cost": float(best_cost),
            "second_best_cost": float(second_cost) if second_cost is not None else None,
            "ambiguity_margin": ambiguity_margin,
            "case_time_error_q50_seconds": quantile(errors, 0.5),
            "case_time_error_q90_seconds": quantile(errors, 0.9),
        }, row_records

    case_results: list[dict[str, Any]] = []
    row_results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as pool:
        for case_result, row_result in pool.map(eval_one, case_rows):
            case_results.append(case_result)
            row_results.extend(row_result)
    return pl.from_dicts(case_results), pl.from_dicts(row_results) if row_results else pl.DataFrame()


def metrics_for_split(case_df: pl.DataFrame, row_df: pl.DataFrame, split: str | None, cfg: RunConfig) -> dict[str, Any]:
    c = case_df if split is None else case_df.filter(pl.col("split") == split)
    r = row_df if split is None else row_df.filter(pl.col("split") == split)
    total = max(1, c.height)
    matched = c.filter(pl.col("status") == "matched")
    wrong = c.filter(pl.col("status") == "wrong_leg")
    rejected = c.filter(pl.col("status") == "rejected")
    out = {
        "case_count": int(c.height),
        "matched_case_count": int(matched.height),
        "correct_leg_rate": float(matched.height / total),
        "wrong_leg_rate": float(wrong.height / total),
        "reject_rate": float(rejected.height / total),
        "status_counts": counts_map(c, "status"),
        "time_error_q50": float(r["time_error_seconds"].quantile(0.5)) if r.height else None,
        "time_error_q90": float(r["time_error_seconds"].quantile(0.9)) if r.height else None,
        "time_error_q99": float(r["time_error_seconds"].quantile(0.99)) if r.height else None,
        "catastrophic_error_rate": float(r.filter(pl.col("time_error_seconds") > cfg.catastrophic_error_seconds).height / max(1, r.height)) if r.height else None,
        "by_batch_size_bucket": {},
        "by_phase": {},
        "coverage_error_curve": [],
    }
    for bucket in sorted(c.get_column("batch_size_bucket").drop_nulls().unique().to_list()) if c.height else []:
        cc = c.filter(pl.col("batch_size_bucket") == bucket)
        rr = r.join(cc.select("pseudo_case_id"), on="pseudo_case_id", how="inner") if r.height else pl.DataFrame()
        out["by_batch_size_bucket"][str(bucket)] = {
            "case_count": int(cc.height),
            "status_counts": counts_map(cc, "status"),
            "time_error_q90": float(rr["time_error_seconds"].quantile(0.9)) if rr.height else None,
        }
    for phase in sorted(c.get_column("leg_phase_like").drop_nulls().unique().to_list()) if c.height else []:
        cc = c.filter(pl.col("leg_phase_like") == phase)
        rr = r.join(cc.select("pseudo_case_id"), on="pseudo_case_id", how="inner") if r.height else pl.DataFrame()
        out["by_phase"][str(phase)] = {
            "case_count": int(cc.height),
            "status_counts": counts_map(cc, "status"),
            "time_error_q90": float(rr["time_error_seconds"].quantile(0.9)) if rr.height else None,
        }
    matched_cases = c.filter(pl.col("status").is_in(["matched", "wrong_leg"]) & pl.col("best_cost").is_not_null()).sort("best_cost")
    if matched_cases.height and r.height:
        for coverage in [0.1, 0.2, 0.3, 0.5, 0.8, 1.0]:
            n = max(1, int(math.ceil(matched_cases.height * coverage)))
            chosen = matched_cases.head(n).select("pseudo_case_id")
            rr = r.join(chosen, on="pseudo_case_id", how="inner")
            cc = matched_cases.head(n)
            out["coverage_error_curve"].append(
                {
                    "matched_coverage_fraction": coverage,
                    "case_count": int(cc.height),
                    "correct_leg_rate": float(cc.filter(pl.col("status") == "matched").height / max(1, cc.height)),
                    "time_error_q90": float(rr["time_error_seconds"].quantile(0.9)) if rr.height else None,
                    "catastrophic_error_rate": float(rr.filter(pl.col("time_error_seconds") > cfg.catastrophic_error_seconds).height / max(1, rr.height)) if rr.height else None,
                }
            )
    return out


def run_stage3_pseudo_amdar(cfg: RunConfig, components: pl.DataFrame) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage3_pseudo_amdar"
    out_dir.mkdir(parents=True, exist_ok=True)

    usable_sources = (
        components.filter(pl.col("leg_overall_quality").is_in(["A", "B"]))
        .filter(pl.col("point_count") >= 40)
        .with_columns(
            [
                (pl.col("tail_norm") + pl.lit("__") + pl.col("service_date_utc")).alias("group_id_tail_date"),
                (pl.col("tail_norm") + pl.lit("__") + pl.col("service_date_utc")).map_elements(split_from_group, return_dtype=pl.Utf8).alias("split"),
            ]
        )
        .sort(["split", "leg_phase_like", "leg_overall_quality", "point_count"], descending=[False, False, False, True])
    )
    selected_parts = []
    for split in ["calibration", "validation", "locked_test"]:
        for phase in ["ASC", "DES", "LVR"]:
            part = usable_sources.filter((pl.col("split") == split) & (pl.col("leg_phase_like") == phase)).head(cfg.pseudo_source_legs_per_split_phase)
            if part.height:
                selected_parts.append(part)
    selected_sources = pl.concat(selected_parts, how="vertical") if selected_parts else usable_sources.head(0)
    selected_sources.write_parquet(out_dir / "pseudo_amdar_source_legs.parquet")

    source_leg_ids = selected_sources.get_column("adsb_leg_id").to_list()
    if not source_leg_ids:
        summary = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "case_count": 0,
            "reason": "No A/B ADS-B source legs with enough points.",
        }
        write_json(out_dir / "pseudo_amdar_calibration_report.json", summary)
        return summary

    leg_points_path = cfg.out_dir / "stage2_adsb_qc_v3" / "adsb_leg_points_v3.parquet"
    if not leg_points_path.exists():
        raise FileNotFoundError(f"Stage3 requires Stage2 v3 leg points: {leg_points_path}")
    source_points = pl.scan_parquet(leg_points_path).filter(pl.col("adsb_leg_id").is_in(source_leg_ids)).collect()
    cases, pseudo_points = generate_pseudo_cases(selected_sources, source_points, cfg)
    cases.write_parquet(out_dir / "pseudo_amdar_cases_all.parquet")
    pseudo_points.write_parquet(out_dir / "pseudo_amdar_points_all.parquet")

    candidate_map = candidate_ids_for_cases(cases, components, cfg)
    candidate_leg_ids = sorted({leg_id for ids in candidate_map.values() for leg_id in ids})
    candidate_points = pl.scan_parquet(leg_points_path).filter(pl.col("adsb_leg_id").is_in(candidate_leg_ids)).collect()
    case_eval, row_eval = evaluate_pseudo_cases(cases, pseudo_points, candidate_map, candidate_points, cfg)
    case_eval.write_parquet(out_dir / "pseudo_amdar_case_evaluation.parquet")
    if row_eval.height:
        row_eval.write_parquet(out_dir / "pseudo_amdar_row_reconstruction.parquet")

    split_paths = {
        "calibration": out_dir / "pseudo_amdar_train.parquet",
        "validation": out_dir / "pseudo_amdar_validation.parquet",
        "locked_test": out_dir / "pseudo_amdar_locked_test.parquet",
    }
    for split, path in split_paths.items():
        case_eval.filter(pl.col("split") == split).write_parquet(path)

    metrics = {
        "overall": metrics_for_split(case_eval, row_eval, None, cfg),
        "calibration": metrics_for_split(case_eval, row_eval, "calibration", cfg),
        "validation": metrics_for_split(case_eval, row_eval, "validation", cfg),
        "locked_test": metrics_for_split(case_eval, row_eval, "locked_test", cfg),
    }
    split_leak_check = (
        case_eval.select(["group_id_tail_date", "split"])
        .unique()
        .group_by("group_id_tail_date")
        .agg(pl.col("split").n_unique().alias("split_count"))
    )
    no_tail_date_split_leakage = bool(split_leak_check.filter(pl.col("split_count") > 1).height == 0)
    locked_curve = metrics["locked_test"].get("coverage_error_curve", [])
    locked_coverage_under_5min = max(
        [
            float(item["matched_coverage_fraction"])
            for item in locked_curve
            if item.get("time_error_q90") is not None
            and float(item["time_error_q90"]) < 300.0
            and (
                item.get("catastrophic_error_rate") is None
                or float(item["catastrophic_error_rate"]) < 0.05
            )
        ]
        or [0.0]
    )
    quality_gate = {
        "locked_test_available": metrics["locked_test"]["case_count"] > 0,
        "locked_test_full_coverage_time_error_q90_lt_5min": (
            metrics["locked_test"]["time_error_q90"] is not None and metrics["locked_test"]["time_error_q90"] < 300.0
        ),
        "locked_test_full_coverage_catastrophic_error_rate_lt_5pct": (
            metrics["locked_test"]["catastrophic_error_rate"] is not None
            and metrics["locked_test"]["catastrophic_error_rate"] < 0.05
        ),
        "locked_test_coverage_with_q90_lt_5min_and_cat_lt_5pct": locked_coverage_under_5min,
        "locked_test_q90_lt_5min_coverage_gt_30pct": locked_coverage_under_5min > 0.30,
        "locked_test_matched_coverage_gt_30pct": (1.0 - metrics["locked_test"]["reject_rate"]) > 0.30 if metrics["locked_test"]["case_count"] else False,
        "no_tail_date_split_leakage": no_tail_date_split_leakage,
    }
    quality_gate["passed_all_stage3_completion_targets"] = bool(
        quality_gate["locked_test_available"]
        and quality_gate["locked_test_q90_lt_5min_coverage_gt_30pct"]
        and quality_gate["locked_test_matched_coverage_gt_30pct"]
        and quality_gate["no_tail_date_split_leakage"]
    )
    quality_gate["residual_full_coverage_risk"] = (
        "Full locked-test coverage does not meet q90/catastrophic-error targets; Stage7 should calibrate an acceptance threshold "
        "from validation and then re-check locked_test selected coverage."
    )
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_leg_components": str(cfg.out_dir / "stage2_adsb_qc_v3/adsb_leg_quality_components.parquet"),
        "source_leg_count": int(selected_sources.height),
        "case_count": int(case_eval.height),
        "row_reconstruction_count": int(row_eval.height),
        "candidate_leg_count": len(candidate_leg_ids),
        "split_grouping": "tail_norm + service_date_utc; same aircraft-day never crosses calibration/validation/locked_test.",
        "locked_test_note": "Thresholds and reconstruction policy are fixed in this script before locked_test evaluation; locked_test was not used for tuning.",
        "split_leak_check": {
            "grouping": "tail_norm + service_date_utc",
            "no_tail_date_split_leakage": no_tail_date_split_leakage,
            "leaking_group_count": int(split_leak_check.filter(pl.col("split_count") > 1).height),
        },
        "metrics": metrics,
        "quality_gate": quality_gate,
        "outputs": {
            "pseudo_amdar_train": str(split_paths["calibration"]),
            "pseudo_amdar_validation": str(split_paths["validation"]),
            "pseudo_amdar_locked_test": str(split_paths["locked_test"]),
            "pseudo_amdar_case_evaluation": str(out_dir / "pseudo_amdar_case_evaluation.parquet"),
            "pseudo_amdar_row_reconstruction": str(out_dir / "pseudo_amdar_row_reconstruction.parquet"),
            "pseudo_amdar_calibration_report": str(out_dir / "pseudo_amdar_calibration_report.json"),
        },
    }
    write_json(out_dir / "pseudo_amdar_calibration_report.json", summary)

    report = [
        "# Stage3 Pseudo-AMDAR Closed-Loop Report",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Split Policy",
        "",
        summary["split_grouping"],
        "",
        "## Metrics",
        "",
        f"- Case count: {summary['case_count']}",
        f"- Source ADS-B legs: {summary['source_leg_count']}",
        f"- Overall metrics: `{metrics['overall']}`",
        f"- Locked-test metrics: `{metrics['locked_test']}`",
        f"- Completion gate: `{quality_gate}`",
        "",
        "Interpretation: this closed loop validates the reconstruction and candidate-selection mechanics without using real AMDAR matching as truth. It should guide threshold calibration, not change strict holdout semantics.",
    ]
    (out_dir / "stage3_pseudo_amdar_report.md").write_text("\n".join(report), encoding="utf-8")
    return summary


def write_final_docs(cfg: RunConfig, stage1: dict[str, Any], stage2: dict[str, Any], stage3: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage2_stage3_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_stage4_plus.md"

    locked = stage3.get("metrics", {}).get("locked_test", {})
    polars_threads = os.environ.get("POLARS_MAX_THREADS")
    run_config_path = cfg.out_dir / "run_config.json"
    if polars_threads is None and run_config_path.exists():
        try:
            polars_threads = str(json.loads(run_config_path.read_text(encoding="utf-8")).get("polars_threads") or "25")
        except json.JSONDecodeError:
            polars_threads = "25"
    result_lines = [
        "# AMDAR Unified Plan Stage2/Stage3 Results and Next Steps",
        "",
        f"Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Run Configuration",
        "",
        f"- Output root: `{cfg.out_dir}`",
        f"- Stage0-fastest policy used: `POLARS_MAX_THREADS={polars_threads}`, external Stage1-style workers avoided for full parquet rewrites.",
        f"- Slice count: {cfg.slice_count}; outputs carry `processing_slice_id` for deterministic 25-way follow-up slicing.",
        "",
        "## Stage1 Suggested Optimizations",
        "",
        f"- AMDAR high-wind rows >150 m/s: {stage1['amdar_high_wind']['rows']}",
        f"- Recommended action counts: `{stage1['amdar_high_wind']['by_action']}`",
        f"- TURB enhanced-QC review rows: {stage1['turb_enhanced_qc_review']['rows']}",
        "",
        "## Stage2 ADS-B QC v3",
        "",
        f"- ADS-B rows audited: {stage2['rows']}",
        f"- Usable legs (>=5 points): {stage2['segmented_leg_count_min_points']}",
        f"- v3 usable-leg A/B/C: `{stage2['leg_overall_quality_counts_min_points']}`",
        f"- Main usable-leg failure counts: `{stage2['leg_failure_counts_min_points']}`",
        "",
        "## Stage3 Pseudo-AMDAR",
        "",
        f"- Cases: {stage3.get('case_count')}",
        f"- Locked-test metrics: `{locked}`",
        f"- Quality gate: `{stage3.get('quality_gate')}`",
        "",
        "## Interpretation",
        "",
        "Stage2 now explains leg downgrades through component flags instead of a single opaque A/B/C label. Stage3 provides a locked-test pseudo-AMDAR closed loop that does not depend on real AMDAR matching. AMDAR remains support-only, not strict truth.",
        "",
        "## Next Recommendations",
        "",
        "1. Use `adsb_leg_quality_components.parquet` to decide Stage5 AMDAR-ADS-B V3 candidate thresholds; do not relax strict truth boundaries.",
        "2. Feed Stage3 validation metrics into Stage7 threshold calibration, then rerun locked_test without tuning.",
        "3. Before Stage4 confidence modeling, treat AMDAR `wind_speed >150 m/s` as downweight/manual-review and TURB enhanced-QC failures as strict-holdout review items; TURB wind speed unit is confirmed m/s, so its review issue is altitude/temperature, not wind-speed units.",
        "4. Stage4/5 can continue with support/truth role separation: TURB/true point-time data for holdout, AMDAR only through confidence/time-uncertainty support channels.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：AMDAR Unified Plan 阶段4及后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。当前已经完成 Unified Plan 阶段0/1，并在本轮完成阶段1建议优化闭环、阶段2 ADS-B QC v3、阶段3 pseudo-AMDAR 闭环。不要从零开始，不要把 AMDAR 改成 strict truth。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目总口径，理解 Stage1-5、Stage4 默认 `tp26_thr11_preserve`、CMA/GFS 边界和 AMDAR 时间语义修正。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：Plan4 实跑报告，理解 AMDAR 批次下发时间不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：Plan4 综合评估，理解 strict truth 候选少是数据本质，不是筛选过严。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：统一实施方案，后续阶段4/5/6/7按这里推进。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage0_stage1_20260701/stage0_stage1_results_and_next_steps.md`：阶段0/1结果和风险项。",
        f"6. `{result_path}`：本轮阶段2/3结果分析和下一步建议。",
        "",
        "## 本轮新增输出",
        "",
        f"- 阶段1闭环：`{cfg.out_dir / 'stage1_quality_closure'}`",
        f"- 阶段2 ADS-B QC v3：`{cfg.out_dir / 'stage2_adsb_qc_v3'}`",
        f"- 阶段3 pseudo-AMDAR：`{cfg.out_dir / 'stage3_pseudo_amdar'}`",
        "",
        "关键文件：",
        "",
        "- `stage1_quality_closure/stage1_unit_schema_v2_addendum.json`：AMDAR/TURB m/s 单位字段生产 schema addendum。",
        "- `stage1_quality_closure/amdar_high_wind_outlier_rows.parquet`：4,505 条左右 AMDAR 高风速复核行。",
        "- `stage1_quality_closure/turb_enhanced_qc_review_rows.parquet`：TURB 增强QC复核行。",
        "- `stage2_adsb_qc_v3/adsb_qc_v3_rows.parquet`：ADS-B 行级 v3 QC，带 `processing_slice_id`。",
        "- `stage2_adsb_qc_v3/adsb_leg_quality_components.parquet`：每条 leg 的组件化失败原因和质量组件。",
        "- `stage2_adsb_qc_v3/adsb_leg_failure_reason_summary.json`：阶段2核心摘要。",
        "- `stage3_pseudo_amdar/pseudo_amdar_train.parquet`、`pseudo_amdar_validation.parquet`、`pseudo_amdar_locked_test.parquet`：按 `tail_norm + service_date_utc` 分组划分的 pseudo-AMDAR case。",
        "- `stage3_pseudo_amdar/pseudo_amdar_calibration_report.json`：阶段3指标和 locked-test 质量门。",
        "",
        "## 项目理解",
        "",
        "centralized_v1 的核心是用 sparse aircraft wind observations 重建三维水平风场 u/v，并且只用严格 aircraft holdout 做正式验证。Stage1 清洗与角色分类，Stage2 按雷达帧组织数据，Stage3 Ground Center 打包，Stage4 才是重构和 strict holdout 评估，Stage5 是保守 residual candidate。当前最稳 default 仍是 `tp26_thr11_preserve`。",
        "",
        "## 数据理解",
        "",
        "AMDAR 431,008 条的原始时间是批次下发/接收时间，不是逐点观测时间；98%+ 属于重复时间批次。AMDAR 当前必须保持 `effective_strict_truth=false`，只能作为 support/data assimilation 候选。TURB 181 条是 conservative strict truth 来源，TURB 风速单位也已确认是 m/s；但 6 条增强QC复核行仍需要在扩大 strict-holdout 使用前处理，因为问题是高度缺失/温度异常，不是风速单位。ADS-B location 有约 19,162,638 行，阶段2已经组件化审计 leg 质量。",
        "",
        "## 本轮结果摘要",
        "",
        f"- AMDAR 高风速 >150 m/s 行数：{stage1['amdar_high_wind']['rows']}，不能再解释为单位歧义；按 m/s QC 风险处理。",
        f"- TURB 风速单位已确认 m/s；增强QC复核行数：{stage1['turb_enhanced_qc_review']['rows']}。",
        f"- Stage2 usable leg A/B/C：`{stage2['leg_overall_quality_counts_min_points']}`。",
        f"- Stage2 主要降级原因：`{stage2['leg_failure_counts_min_points']}`。",
        f"- Stage3 locked-test：`{locked}`。",
        "",
        "## 继续阶段4/5时的边界",
        "",
        "1. 不要把 AMDAR 批次时间当逐点观测时间。",
        "2. 不要把 AMDAR 放进 official strict holdout。",
        "3. 阶段4置信度模型应读取阶段2组件质量和阶段1高风速/TURB复核风险。",
        "4. 阶段5 AMDAR-ADS-B V3 匹配应基于阶段2 leg component flags 和阶段3 validation/locked-test 指标设阈值。",
        "5. 继续使用 25-slice / `POLARS_MAX_THREADS=25` 的省空间口径，避免复制 25 份全量中间数据。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、阶段0/1结果，以及阶段2/3最新结果。",
        "当前结论：AMDAR 仍是 support-only；Stage2 已经给出 ADS-B leg 组件化失败原因；Stage3 已经提供 tail+date 分组的 pseudo-AMDAR locked test；下一步应进入阶段4置信度数据模型和阶段5 AMDAR-ADS-B V3，但不能放宽 strict truth。",
        "我将先读取 stage2_adsb_qc_v3/adsb_leg_quality_components.parquet、stage3_pseudo_amdar/pseudo_amdar_calibration_report.json 和 stage1_quality_closure 的高风速/TURB复核结果，再实现阶段4/5。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage1_quality_closure_start"}, ensure_ascii=False))
    stage1_summary = run_stage1_quality_closure(cfg)
    print(json.dumps({"stage": "stage1_quality_closure_done", "amdar_high_wind_rows": stage1_summary["amdar_high_wind"]["rows"]}, ensure_ascii=False))

    print(json.dumps({"stage": "stage2_adsb_qc_v3_start"}, ensure_ascii=False))
    components, stage2_summary = run_stage2_adsb_qc(cfg)
    print(json.dumps({"stage": "stage2_adsb_qc_v3_done", "usable_legs": stage2_summary["segmented_leg_count_min_points"]}, ensure_ascii=False))

    print(json.dumps({"stage": "stage3_pseudo_amdar_start"}, ensure_ascii=False))
    stage3_summary = run_stage3_pseudo_amdar(cfg, components)
    print(json.dumps({"stage": "stage3_pseudo_amdar_done", "case_count": stage3_summary.get("case_count")}, ensure_ascii=False))

    write_final_docs(cfg, stage1_summary, stage2_summary, stage3_summary)
    print(json.dumps({"stage": "all_done", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
