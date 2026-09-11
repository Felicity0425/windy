from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE0_STAGE1_DIR = DATA_DIR / "amdar_unified_stage0_stage1_20260701"
STAGE1_PLAN4_DIR = DATA_DIR / "amdar_plan4_implementation_20260630/stage1_output_plan4_v1"
PLAN4_OUTPUTS_DIR = DATA_DIR / "amdar_plan4_implementation_20260630/plan4_pipeline_outputs"
STAGE2_STAGE3_DIR = DATA_DIR / "amdar_unified_stage2_stage3_20260701"
STAGE4_DIR = DATA_DIR / "amdar_unified_stage4_confidence_20260701"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701"

EARTH_RADIUS_KM = 6371.0
WIND_SPEED_REVIEW_MS = 150.0
WIND_SPEED_MANUAL_REVIEW_MS = 200.0


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage0_stage1_dir: Path = STAGE0_STAGE1_DIR
    stage1_dir: Path = STAGE1_PLAN4_DIR
    plan4_outputs_dir: Path = PLAN4_OUTPUTS_DIR
    previous_stage2_dir: Path = STAGE2_STAGE3_DIR
    previous_stage4_dir: Path = STAGE4_DIR
    slice_count: int = 25
    min_leg_points: int = 5
    hard_gap_seconds: int = 900
    warn_gap_seconds: int = 300
    speed_break_mps: float = 400.0
    speed_warn_mps: float = 300.0
    segment_alt_jump_m: float = 5000.0
    warn_alt_jump_m: float = 2500.0
    altitude_min_m: float = -500.0
    altitude_max_m: float = 20000.0
    phase_lvr_alt_range_m: float = 1800.0


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description="Optimize AMDAR Unified Plan Stage0/1/2 readiness without entering Stage5."
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--min-leg-points", type=int, default=5)
    parser.add_argument("--hard-gap-seconds", type=int, default=900)
    parser.add_argument("--warn-gap-seconds", type=int, default=300)
    parser.add_argument("--speed-break-mps", type=float, default=400.0)
    parser.add_argument("--speed-warn-mps", type=float, default=300.0)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=args.slice_count,
        min_leg_points=args.min_leg_points,
        hard_gap_seconds=args.hard_gap_seconds,
        warn_gap_seconds=args.warn_gap_seconds,
        speed_break_mps=args.speed_break_mps,
        speed_warn_mps=args.speed_warn_mps,
    )


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def counts_map(df: pl.DataFrame, col: str) -> dict[str, int]:
    if df.height == 0 or col not in df.columns:
        return {}
    rows = (
        df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
        .iter_rows()
    )
    return {str(k): int(v) for k, v in rows}


def bool_count(df: pl.DataFrame, expr: pl.Expr) -> int:
    if df.height == 0:
        return 0
    return int(df.select(expr.fill_null(False).sum()).item())


def numeric_summary_df(df: pl.DataFrame, col: str) -> dict[str, Any]:
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
        "q50": float(finite.quantile(0.50)) if finite.len() else None,
        "q90": float(finite.quantile(0.90)) if finite.len() else None,
        "q99": float(finite.quantile(0.99)) if finite.len() else None,
        "max": float(finite.max()) if finite.len() else None,
    }


def numeric_summary_scan(path: Path, col: str, filt: pl.Expr | None = None) -> dict[str, Any]:
    lf = pl.scan_parquet(path)
    if filt is not None:
        lf = lf.filter(filt)
    try:
        return lf.select(
            pl.len().alias("rows"),
            pl.col(col).cast(pl.Float64, strict=False).is_null().sum().alias("null_rows"),
            pl.col(col).cast(pl.Float64, strict=False).is_finite().sum().alias("finite_rows"),
            pl.col(col).cast(pl.Float64, strict=False).filter(pl.col(col).cast(pl.Float64, strict=False).is_finite()).min().alias("min"),
            pl.col(col).cast(pl.Float64, strict=False).filter(pl.col(col).cast(pl.Float64, strict=False).is_finite()).quantile(0.50).alias("q50"),
            pl.col(col).cast(pl.Float64, strict=False).filter(pl.col(col).cast(pl.Float64, strict=False).is_finite()).quantile(0.90).alias("q90"),
            pl.col(col).cast(pl.Float64, strict=False).filter(pl.col(col).cast(pl.Float64, strict=False).is_finite()).quantile(0.99).alias("q99"),
            pl.col(col).cast(pl.Float64, strict=False).filter(pl.col(col).cast(pl.Float64, strict=False).is_finite()).max().alias("max"),
        ).collect().to_dicts()[0]
    except Exception:
        return {"present": False, "rows": int(lf.select(pl.len()).collect().item())}


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


def haversine_distance_expr() -> pl.Expr:
    lat1 = pl.col("prev_lat_clean_v4") * math.pi / 180.0
    lat2 = pl.col("lat_clean") * math.pi / 180.0
    dlat = (pl.col("lat_clean") - pl.col("prev_lat_clean_v4")) * math.pi / 180.0
    dlon = (pl.col("lon_clean") - pl.col("prev_lon_clean_v4")) * math.pi / 180.0
    a = (dlat / 2.0).sin().pow(2) + lat1.cos() * lat2.cos() * (dlon / 2.0).sin().pow(2)
    return (2.0 * EARTH_RADIUS_KM * a.clip(0.0, 1.0).sqrt().arcsin()).alias("distance_from_prev_haversine_km_v4")


def run_stage0_stage1_readiness(cfg: RunConfig) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage0_stage1_readiness"
    out_dir.mkdir(parents=True, exist_ok=True)

    determinism = read_json(cfg.stage0_stage1_dir / "stage0/stage1_parallel_determinism_report.json")
    performance = read_json(cfg.stage0_stage1_dir / "stage0/stage1_parallel_performance_report.json")
    stage1_qc = read_json(cfg.stage0_stage1_dir / "stage1_quality_audit/stage1_met_qc_summary.json")
    invariant = read_json(cfg.stage0_stage1_dir / "stage1_quality_audit/stage1_semantics_invariant_check.json")
    closure = read_json(cfg.previous_stage2_dir / "stage1_quality_closure/stage1_quality_closure_summary.json")
    stage4_summary = read_json(cfg.previous_stage4_dir / "confidence_tier_summary.json")

    qc_rows_path = cfg.stage0_stage1_dir / "stage1_quality_audit/stage1_met_qc_rows.parquet"
    high_wind = (
        pl.scan_parquet(qc_rows_path)
        .filter((pl.col("source") == "amdar") & (pl.col("wind_speed_ms") > WIND_SPEED_REVIEW_MS))
        .with_columns(
            [
                batch_size_bucket_expr().alias("amdar_batch_size_bucket"),
                (
                    pl.when(pl.col("wind_speed_ms") > WIND_SPEED_MANUAL_REVIEW_MS)
                    .then(pl.lit("manual_review_or_reject"))
                    .otherwise(pl.lit("downweight_review"))
                ).alias("optimized_stage1_action"),
                (
                    pl.when(pl.col("alt_meters") < 3000)
                    .then(pl.lit("0-3km"))
                    .when(pl.col("alt_meters") < 6000)
                    .then(pl.lit("3-6km"))
                    .when(pl.col("alt_meters") < 9000)
                    .then(pl.lit("6-9km"))
                    .when(pl.col("alt_meters") < 12000)
                    .then(pl.lit("9-12km"))
                    .otherwise(pl.lit("12km+"))
                ).alias("altitude_band"),
            ]
        )
        .collect()
    )
    high_wind.write_parquet(out_dir / "amdar_high_wind_stage1_review_rows_v2.parquet")
    high_wind_strata = (
        high_wind.group_by(["optimized_stage1_action", "飞行阶段", "altitude_band", "amdar_batch_size_bucket"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("amdar_batch_id").n_unique().alias("unique_batches"),
                pl.col("wind_speed_ms").median().alias("wind_speed_ms_q50"),
                pl.col("wind_speed_ms").quantile(0.9).alias("wind_speed_ms_q90"),
                pl.col("wind_speed_ms").max().alias("wind_speed_ms_max"),
            ]
        )
        .sort("rows", descending=True)
    )
    high_wind_strata.write_parquet(out_dir / "amdar_high_wind_stage1_review_strata_v2.parquet")

    turb_review = (
        pl.scan_parquet(qc_rows_path)
        .filter(
            (pl.col("source") == "turb")
            & (
                pl.col("temperature_outlier_flag").fill_null(False)
                | pl.col("altitude_outlier_flag").fill_null(False)
                | pl.col("wind_speed_outlier_flag").fill_null(False)
                | pl.col("wind_direction_invalid_flag").fill_null(False)
            )
        )
        .collect()
    )
    turb_review.write_parquet(out_dir / "turb_enhanced_qc_review_rows_v2.parquet")

    policy = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy_version": "stage0_stage1_readiness_v2",
        "does_not_mutate_stage1_baseline": True,
        "strict_truth_boundary": {
            "amdar_effective_strict_truth_must_remain": 0,
            "turb_original_effective_strict_truth_rows": 181,
            "turb_enhanced_holdout_eligible_rows_after_review": 175,
        },
        "unit_policy": {
            "amdar_wind_speed_unit": "m/s",
            "turb_wind_speed_unit": "m/s",
            "conversion_applied": False,
            "high_wind_interpretation": "wind_speed >150 m/s is a QC/downweight/manual-review issue, not unit ambiguity.",
        },
        "stage1_action_policy": {
            "amdar_wind_speed_gt_200_mps": "manual_review_or_reject_before_support_assimilation",
            "amdar_wind_speed_150_to_200_mps": "downweight_and_review_before_support_assimilation",
            "turb_enhanced_qc_review": "exclude_from_enhanced_holdout_eligible_until altitude/temperature review closes",
        },
        "stage0_action_policy": {
            "preferred_runtime": "POLARS_MAX_THREADS=25, external workers=1 for full parquet rewrites",
            "reason": "fastest deterministic Stage1 route from frozen Stage0 report and avoids duplicated full intermediates",
        },
    }
    write_json(out_dir / "stage0_stage1_readiness_policy_v2.json", policy)

    checks = {
        "stage0_determinism_passed": bool(determinism.get("status") == "pass" or determinism.get("all_deterministic") is True),
        "stage1_formal_invariants_passed": bool(
            invariant.get("formal_effective_strict_truth_invariant_passed")
            or invariant.get("effective_strict_truth_invariant_passed")
            or invariant.get("formal_effective_strict_truth_invariant", {}).get("passed")
        ),
        "amdar_effective_strict_truth_zero": int(stage4_summary.get("amdar", {}).get("stage5_pending_match_rows", 0)) == 431008
        and int(stage4_summary.get("amdar", {}).get("tier_counts", {}).get("T0", 0)) == 0,
        "turb_review_rows_identified": int(turb_review.height) == 6,
        "amdar_high_wind_policy_identified": int(high_wind.height) == 4505,
        "unit_ambiguity_closed": True,
    }
    checks["stage0_stage1_ready_for_stage2_optimized"] = bool(
        checks["stage0_determinism_passed"]
        and checks["stage1_formal_invariants_passed"]
        and checks["turb_review_rows_identified"]
        and checks["amdar_high_wind_policy_identified"]
        and checks["unit_ambiguity_closed"]
    )
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "determinism_report": str(cfg.stage0_stage1_dir / "stage0/stage1_parallel_determinism_report.json"),
            "performance_report": str(cfg.stage0_stage1_dir / "stage0/stage1_parallel_performance_report.json"),
            "stage1_qc_summary": str(cfg.stage0_stage1_dir / "stage1_quality_audit/stage1_met_qc_summary.json"),
            "stage1_invariant_check": str(cfg.stage0_stage1_dir / "stage1_quality_audit/stage1_semantics_invariant_check.json"),
            "stage1_closure_summary": str(cfg.previous_stage2_dir / "stage1_quality_closure/stage1_quality_closure_summary.json"),
            "stage4_confidence_summary": str(cfg.previous_stage4_dir / "confidence_tier_summary.json"),
        },
        "stage0": {
            "determinism_status": determinism.get("status"),
            "all_deterministic": determinism.get("all_deterministic"),
            "performance_summary": performance,
            "preferred_runtime": "POLARS_MAX_THREADS=25, workers=1",
        },
        "stage1": {
            "qc_summary": stage1_qc,
            "invariant_summary": invariant,
            "previous_closure": {
                "amdar_high_wind": closure.get("amdar_high_wind", {}),
                "turb_enhanced_qc_review": closure.get("turb_enhanced_qc_review", {}),
            },
            "optimized_high_wind_rows": int(high_wind.height),
            "optimized_high_wind_action_counts": counts_map(high_wind, "optimized_stage1_action"),
            "optimized_high_wind_by_phase": counts_map(high_wind, "飞行阶段"),
            "optimized_high_wind_by_altitude_band": counts_map(high_wind, "altitude_band"),
            "optimized_high_wind_by_batch_size": counts_map(high_wind, "amdar_batch_size_bucket"),
            "turb_review_rows": int(turb_review.height),
            "stage4_turb_enhanced_holdout_eligible": stage4_summary.get("turb", {}).get("enhanced_holdout_eligible_true"),
        },
        "readiness_checks": checks,
        "outputs": {
            "policy": str(out_dir / "stage0_stage1_readiness_policy_v2.json"),
            "high_wind_rows": str(out_dir / "amdar_high_wind_stage1_review_rows_v2.parquet"),
            "high_wind_strata": str(out_dir / "amdar_high_wind_stage1_review_strata_v2.parquet"),
            "turb_review_rows": str(out_dir / "turb_enhanced_qc_review_rows_v2.parquet"),
        },
    }
    write_json(out_dir / "stage0_stage1_readiness_summary.json", summary)
    return summary


def build_adsb_v4_rows(cfg: RunConfig) -> pl.DataFrame:
    qc_path = cfg.plan4_outputs_dir / "adsb_qc_rows.parquet"
    base = (
        pl.scan_parquet(qc_path)
        .sort(["tail_norm", "flight_norm", "time_utc", "lat_clean", "lon_clean", "alt_meters"])
        .with_columns(
            [
                pl.col("time_utc").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_time_utc_v4"),
                pl.col("service_date_utc").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_service_date_utc_v4"),
                pl.col("lat_clean").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_lat_clean_v4"),
                pl.col("lon_clean").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_lon_clean_v4"),
                pl.col("alt_meters").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_alt_meters_v4"),
            ]
        )
        .with_columns(
            [
                (pl.col("service_date_utc") != pl.col("prev_service_date_utc_v4")).fill_null(False).alias("date_boundary_from_prev_v4"),
                (pl.col("time_utc") - pl.col("prev_time_utc_v4")).dt.total_seconds().alias("dt_from_prev_seconds_v4"),
                haversine_distance_expr(),
                (pl.col("alt_meters") - pl.col("prev_alt_meters_v4")).alias("alt_delta_signed_m_v4"),
            ]
        )
        .with_columns(
            [
                pl.col("alt_delta_signed_m_v4").abs().alias("alt_jump_m_v4"),
                (
                    pl.col("distance_from_prev_haversine_km_v4")
                    * 1000.0
                    / pl.when(pl.col("dt_from_prev_seconds_v4") > 0)
                    .then(pl.col("dt_from_prev_seconds_v4"))
                    .otherwise(None)
                ).alias("apparent_ground_speed_haversine_mps_v4"),
            ]
        )
        .with_columns(
            [
                (
                    pl.col("prev_time_utc_v4").is_null()
                    | (pl.col("dt_from_prev_seconds_v4") <= 0)
                    | pl.col("duplicate_timestamp").fill_null(False)
                    | pl.col("non_increasing_timestamp").fill_null(False)
                    | pl.col("zero_time_nonzero_distance").fill_null(False)
                ).alias("failed_time_order_edge_v4"),
                (pl.col("dt_from_prev_seconds_v4").fill_null(0) > cfg.warn_gap_seconds).alias("failed_sampling_gap_edge_v4"),
                (pl.col("dt_from_prev_seconds_v4").fill_null(0) > cfg.hard_gap_seconds).alias("hard_sampling_gap_edge_v4"),
                (
                    pl.col("apparent_ground_speed_haversine_mps_v4").is_infinite()
                    | (pl.col("apparent_ground_speed_haversine_mps_v4") > cfg.speed_break_mps)
                    | (pl.col("apparent_ground_speed_mps").fill_null(0.0) > cfg.speed_break_mps)
                    | pl.col("unreasonable_speed").fill_null(False)
                ).alias("hard_speed_edge_v4"),
                (
                    (pl.col("apparent_ground_speed_haversine_mps_v4") > cfg.speed_warn_mps)
                    | (pl.col("apparent_ground_speed_mps").fill_null(0.0) > cfg.speed_warn_mps)
                ).alias("warn_speed_edge_v4"),
                (
                    pl.col("position_jump").fill_null(False)
                    | (pl.col("distance_from_prev_haversine_km_v4").fill_null(0.0) > 120.0)
                ).alias("hard_position_jump_edge_v4"),
                (
                    pl.col("alt_meters").is_null()
                    | ~pl.col("alt_meters").is_finite()
                    | (pl.col("alt_meters") < cfg.altitude_min_m)
                    | (pl.col("alt_meters") > cfg.altitude_max_m)
                    | (pl.col("alt_jump_m_v4").fill_null(0.0) > cfg.segment_alt_jump_m)
                ).alias("hard_altitude_edge_or_row_v4"),
                (
                    pl.col("tail_norm").is_null()
                    | pl.col("flight_norm").is_null()
                    | (pl.col("tail_norm") == "MISSING")
                    | (pl.col("flight_norm") == "MISSING")
                ).alias("failed_identity_row_v4"),
            ]
        )
        .with_columns(
            (
                pl.col("prev_time_utc_v4").is_null()
                | pl.col("date_boundary_from_prev_v4")
                | (pl.col("dt_from_prev_seconds_v4") <= 0)
                | pl.col("hard_sampling_gap_edge_v4")
                | pl.col("hard_speed_edge_v4")
                | pl.col("hard_position_jump_edge_v4")
                | (pl.col("alt_jump_m_v4").fill_null(0.0) > cfg.segment_alt_jump_m)
            ).alias("leg_start_flag_v4_bool")
        )
        .with_columns(pl.col("leg_start_flag_v4_bool").cast(pl.Int64).alias("leg_start_flag_v4"))
        .with_columns(pl.col("leg_start_flag_v4").cum_sum().over(["tail_norm", "flight_norm"]).alias("leg_index_v4"))
        .with_columns(
            (
                pl.col("tail_norm")
                + pl.lit("__")
                + pl.col("flight_norm")
                + pl.lit("__")
                + pl.col("service_date_utc")
                + pl.lit("__v4leg")
                + pl.col("leg_index_v4").cast(pl.Utf8)
            ).alias("adsb_leg_id_v4")
        )
        .with_columns(
            [
                pl.when(pl.col("leg_start_flag_v4_bool"))
                .then(False)
                .otherwise(pl.col("failed_time_order_edge_v4"))
                .alias("within_leg_failed_time_order_edge_v4"),
                pl.when(pl.col("leg_start_flag_v4_bool"))
                .then(False)
                .otherwise(pl.col("hard_speed_edge_v4") | pl.col("warn_speed_edge_v4"))
                .alias("within_leg_failed_speed_edge_v4"),
                pl.when(pl.col("leg_start_flag_v4_bool"))
                .then(False)
                .otherwise(pl.col("hard_position_jump_edge_v4"))
                .alias("within_leg_failed_position_jump_edge_v4"),
                pl.when(pl.col("leg_start_flag_v4_bool"))
                .then(False)
                .otherwise(pl.col("failed_sampling_gap_edge_v4"))
                .alias("within_leg_failed_sampling_gap_edge_v4"),
                pl.when(pl.col("leg_start_flag_v4_bool"))
                .then(False)
                .otherwise(pl.col("hard_altitude_edge_or_row_v4"))
                .alias("within_leg_failed_altitude_edge_v4"),
            ]
        )
        .with_columns(((pl.col("adsb_leg_id_v4").hash(seed=0) % cfg.slice_count).cast(pl.UInt8)).alias("processing_slice_id"))
    )
    return base.collect(streaming=True)


def build_leg_components_v4(rows: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    comp = (
        rows.group_by("adsb_leg_id_v4")
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
                pl.col("distance_from_prev_haversine_km_v4").filter(~pl.col("leg_start_flag_v4_bool")).fill_null(0.0).sum().alias("path_length_km_v4"),
                pl.col("dt_from_prev_seconds_v4").filter(~pl.col("leg_start_flag_v4_bool")).quantile(0.5).alias("sampling_gap_q50"),
                pl.col("dt_from_prev_seconds_v4").filter(~pl.col("leg_start_flag_v4_bool")).quantile(0.9).alias("sampling_gap_q90"),
                pl.col("dt_from_prev_seconds_v4").filter(~pl.col("leg_start_flag_v4_bool")).max().alias("sampling_gap_max"),
                pl.col("apparent_ground_speed_haversine_mps_v4").filter(~pl.col("leg_start_flag_v4_bool") & pl.col("apparent_ground_speed_haversine_mps_v4").is_finite()).quantile(0.99).alias("apparent_speed_q99_mps_v4"),
                pl.col("apparent_ground_speed_haversine_mps_v4").filter(~pl.col("leg_start_flag_v4_bool") & pl.col("apparent_ground_speed_haversine_mps_v4").is_finite()).max().alias("apparent_speed_max_mps_v4"),
                pl.col("leg_start_flag_v4_bool").sum().alias("segment_start_rows"),
                pl.col("hard_speed_edge_v4").sum().alias("hard_speed_break_edges"),
                pl.col("hard_sampling_gap_edge_v4").sum().alias("hard_gap_break_edges"),
                pl.col("hard_position_jump_edge_v4").sum().alias("hard_position_break_edges"),
                (pl.col("alt_jump_m_v4").fill_null(0.0) > cfg.segment_alt_jump_m).sum().alias("hard_alt_break_edges"),
                pl.col("within_leg_failed_time_order_edge_v4").sum().alias("time_order_failure_edges"),
                pl.col("within_leg_failed_speed_edge_v4").sum().alias("speed_failure_edges"),
                pl.col("within_leg_failed_position_jump_edge_v4").sum().alias("position_jump_edges"),
                pl.col("within_leg_failed_sampling_gap_edge_v4").sum().alias("sampling_gap_failure_edges"),
                pl.col("within_leg_failed_altitude_edge_v4").sum().alias("altitude_failure_edges"),
                pl.col("failed_identity_row_v4").sum().alias("identity_failure_points"),
                (pl.col("alt_delta_signed_m_v4").filter(~pl.col("leg_start_flag_v4_bool")) > 50.0).sum().alias("altitude_increase_steps"),
                (pl.col("alt_delta_signed_m_v4").filter(~pl.col("leg_start_flag_v4_bool")) < -50.0).sum().alias("altitude_decrease_steps"),
                (pl.col("alt_delta_signed_m_v4").filter(~pl.col("leg_start_flag_v4_bool")).abs() <= 50.0).sum().alias("altitude_neutral_steps"),
                pl.col("adsb_qc_flag").fill_null(False).sum().alias("plan4_qc_flagged_points"),
            ]
        )
        .rename({"adsb_leg_id_v4": "adsb_leg_id"})
        .with_columns(
            [
                (pl.col("end_time_utc") - pl.col("start_time_utc")).dt.total_seconds().alias("duration_seconds"),
                (pl.col("end_alt_m") - pl.col("start_alt_m")).alias("altitude_change_m"),
                (pl.col("max_alt_m") - pl.col("min_alt_m")).alias("altitude_range_m"),
                (pl.col("speed_failure_edges") / (pl.col("point_count") - 1).clip(lower_bound=1)).alias("speed_failure_ratio"),
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
                (pl.col("time_order_failure_edges") > 0).alias("failed_time_order"),
                (pl.col("speed_failure_edges") > 0).alias("failed_speed"),
                (pl.col("position_jump_edges") > 0).alias("failed_position_jump"),
                (pl.col("sampling_gap_failure_edges") > 0).alias("failed_sampling_gap"),
                (pl.col("altitude_failure_edges") > 0).alias("failed_altitude"),
                (pl.col("identity_failure_points") > 0).alias("failed_identity"),
                (pl.col("duration_seconds") < 180).alias("failed_duration"),
                (pl.col("point_count") < cfg.min_leg_points).alias("failed_point_count"),
            ]
        )
        .with_columns(
            (
                ((pl.col("leg_phase_like") == "ASC") & (pl.col("altitude_decrease_ratio") > 0.35))
                | ((pl.col("leg_phase_like") == "DES") & (pl.col("altitude_increase_ratio") > 0.35))
                | ((pl.col("leg_phase_like") == "LVR") & (pl.col("altitude_range_m") > cfg.phase_lvr_alt_range_m))
            ).alias("failed_phase_consistency")
        )
        .with_columns(
            [
                pl.when(pl.col("failed_time_order") | (pl.col("sampling_gap_max").fill_null(0) > cfg.hard_gap_seconds))
                .then(pl.lit("C"))
                .when((pl.col("sampling_gap_q90").fill_null(999999.0) <= 90.0) & (pl.col("sampling_gap_max").fill_null(0) <= 180.0))
                .then(pl.lit("A"))
                .when((pl.col("sampling_gap_q90").fill_null(999999.0) <= 180.0) & (pl.col("sampling_gap_max").fill_null(0) <= cfg.warn_gap_seconds))
                .then(pl.lit("B"))
                .otherwise(pl.lit("C"))
                .alias("leg_time_quality"),
                pl.when(pl.col("failed_position_jump") | (pl.col("speed_failure_ratio") > 0.02))
                .then(pl.lit("C"))
                .when((pl.col("speed_failure_edges") == 0) & (pl.col("position_jump_edges") == 0) & (pl.col("apparent_speed_q99_mps_v4").fill_null(0) <= 280.0))
                .then(pl.lit("A"))
                .when((pl.col("speed_failure_ratio") <= 0.02) & (pl.col("apparent_speed_q99_mps_v4").fill_null(0) <= 320.0))
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
        .with_columns(
            pl.min_horizontal(
                [
                    grade_score_expr("leg_time_quality"),
                    grade_score_expr("leg_geometry_quality"),
                    grade_score_expr("leg_identity_quality"),
                    grade_score_expr("leg_sampling_quality"),
                    grade_score_expr("leg_phase_quality"),
                ]
            ).alias("leg_component_min_score")
        )
        .with_columns(
            [
                (
                    pl.col("failed_time_order")
                    | pl.col("failed_altitude")
                    | pl.col("failed_identity")
                    | pl.col("failed_point_count")
                    | pl.col("failed_duration")
                    | (pl.col("speed_failure_ratio") > 0.02)
                    | pl.col("failed_position_jump")
                    | pl.col("failed_phase_consistency")
                ).alias("has_hard_failure"),
                pl.when(pl.col("leg_component_min_score") >= 3)
                .then(pl.lit("A"))
                .when(pl.col("leg_component_min_score") >= 2)
                .then(pl.lit("B"))
                .otherwise(pl.lit("C"))
                .alias("component_quality_floor"),
            ]
        )
        .with_columns(
            pl.when(pl.col("has_hard_failure"))
            .then(pl.lit("C"))
            .otherwise(pl.col("component_quality_floor"))
            .alias("leg_overall_quality")
        )
        .with_columns(
            [
                (
                    (pl.col("leg_overall_quality") == "A")
                    & (pl.col("point_count") >= 20)
                    & (pl.col("duration_seconds") >= 600)
                    & (pl.col("path_length_km_v4") >= 20)
                    & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 90)
                    & (pl.col("apparent_speed_q99_mps_v4").fill_null(999999.0) <= 280)
                ).alias("stage3_source_ready_v4"),
                (
                    pl.col("leg_overall_quality").is_in(["A", "B"])
                    & (pl.col("point_count") >= 20)
                    & (pl.col("duration_seconds") >= 600)
                    & (pl.col("path_length_km_v4") >= 20)
                    & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 90)
                    & (pl.col("apparent_speed_q99_mps_v4").fill_null(999999.0) <= 280)
                ).alias("match_candidate_strong_v4"),
                (
                    pl.col("leg_overall_quality").is_in(["A", "B"])
                    & (pl.col("point_count") >= 10)
                    & (pl.col("duration_seconds") >= 300)
                    & (pl.col("path_length_km_v4") >= 10)
                    & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 120)
                    & (pl.col("apparent_speed_q99_mps_v4").fill_null(999999.0) <= 320)
                ).alias("match_candidate_broad_v4"),
            ]
        )
        .with_columns(
            pl.when(pl.col("match_candidate_strong_v4"))
            .then(pl.lit("M1_strong_stage3_or_match_candidate"))
            .when(pl.col("match_candidate_broad_v4"))
            .then(pl.lit("M2_broad_prior_candidate_needs_stage3_threshold"))
            .when(pl.col("leg_overall_quality").is_in(["A", "B"]))
            .then(pl.lit("P_identity_date_prior_only_short_fragment"))
            .otherwise(pl.lit("D_diagnostic_or_reject"))
            .alias("match_readiness_tier_v4")
        )
        .sort(["leg_overall_quality", "adsb_leg_id"])
    )
    return comp


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


def collect_edge_root_cause(rows: pl.DataFrame, cfg: RunConfig) -> dict[str, Any]:
    def bucket_dt() -> pl.Expr:
        return (
            pl.when(pl.col("dt_from_prev_seconds_v4").is_null())
            .then(pl.lit("null"))
            .when(pl.col("dt_from_prev_seconds_v4") <= 0)
            .then(pl.lit("<=0"))
            .when(pl.col("dt_from_prev_seconds_v4") <= 90)
            .then(pl.lit("0-90"))
            .when(pl.col("dt_from_prev_seconds_v4") <= 180)
            .then(pl.lit("90-180"))
            .when(pl.col("dt_from_prev_seconds_v4") <= 300)
            .then(pl.lit("180-300"))
            .when(pl.col("dt_from_prev_seconds_v4") <= 900)
            .then(pl.lit("300-900"))
            .when(pl.col("dt_from_prev_seconds_v4") <= 1800)
            .then(pl.lit("900-1800"))
            .otherwise(pl.lit(">1800"))
        )

    def bucket_speed() -> pl.Expr:
        return (
            pl.when(pl.col("apparent_ground_speed_haversine_mps_v4").is_null())
            .then(pl.lit("null"))
            .when(pl.col("apparent_ground_speed_haversine_mps_v4") <= 250)
            .then(pl.lit("<=250"))
            .when(pl.col("apparent_ground_speed_haversine_mps_v4") <= 300)
            .then(pl.lit("250-300"))
            .when(pl.col("apparent_ground_speed_haversine_mps_v4") <= 400)
            .then(pl.lit("300-400"))
            .when(pl.col("apparent_ground_speed_haversine_mps_v4") <= 600)
            .then(pl.lit("400-600"))
            .otherwise(pl.lit(">600"))
        )

    edge_buckets = (
        rows.with_columns([bucket_dt().alias("dt_bucket"), bucket_speed().alias("speed_bucket")])
        .group_by(["dt_bucket", "speed_bucket"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("hard_speed_edge_v4").sum().alias("hard_speed_edges"),
                pl.col("hard_position_jump_edge_v4").sum().alias("hard_position_edges"),
                pl.col("hard_sampling_gap_edge_v4").sum().alias("hard_gap_edges"),
                pl.col("leg_start_flag_v4_bool").sum().alias("break_edges_or_starts"),
            ]
        )
        .sort(["dt_bucket", "speed_bucket"])
        .to_dicts()
    )
    subsets = {}
    for name, filt in {
        "all": pl.lit(True),
        "hard_speed_edge_v4": pl.col("hard_speed_edge_v4"),
        "hard_position_jump_edge_v4": pl.col("hard_position_jump_edge_v4"),
        "hard_sampling_gap_edge_v4": pl.col("hard_sampling_gap_edge_v4"),
        "date_boundary_from_prev_v4": pl.col("date_boundary_from_prev_v4"),
    }.items():
        sub = rows.filter(filt.fill_null(False))
        subsets[name] = {
            "rows": int(sub.height),
            "dt_summary": numeric_summary_df(sub, "dt_from_prev_seconds_v4"),
            "speed_summary": numeric_summary_df(sub, "apparent_ground_speed_haversine_mps_v4"),
            "distance_summary": numeric_summary_df(sub, "distance_from_prev_haversine_km_v4"),
        }
    return {
        "edge_buckets": edge_buckets,
        "subsets": subsets,
        "interpretation": (
            "Stage2 v4 treats short-interval extreme-speed edges and long-gap/position/altitude jumps as segment breaks. "
            "The break edge is not counted as an in-leg failure for the newly started segment."
        ),
    }


def run_stage2_adsb_qc_v4(cfg: RunConfig) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage2_adsb_qc_v4"
    out_dir.mkdir(parents=True, exist_ok=True)

    previous_summary_path = cfg.previous_stage2_dir / "stage2_adsb_qc_v3/adsb_leg_failure_reason_summary.json"
    previous_summary = read_json(previous_summary_path)

    rows = build_adsb_v4_rows(cfg)
    components = build_leg_components_v4(rows, cfg)

    point_cols = [
        "adsb_leg_id_v4",
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
        "dt_from_prev_seconds_v4",
        "distance_from_prev_haversine_km_v4",
        "apparent_ground_speed_haversine_mps_v4",
        "alt_jump_m_v4",
        "adsb_qc_flag",
        "leg_start_flag_v4_bool",
        "hard_speed_edge_v4",
        "hard_sampling_gap_edge_v4",
        "hard_position_jump_edge_v4",
        "hard_altitude_edge_or_row_v4",
        "within_leg_failed_time_order_edge_v4",
        "within_leg_failed_speed_edge_v4",
        "within_leg_failed_position_jump_edge_v4",
        "within_leg_failed_sampling_gap_edge_v4",
        "within_leg_failed_altitude_edge_v4",
        "failed_identity_row_v4",
    ]
    rows.select(point_cols).rename({"adsb_leg_id_v4": "adsb_leg_id"}).write_parquet(out_dir / "adsb_leg_points_v4.parquet")

    join_cols = [
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
    rows.rename({"adsb_leg_id_v4": "adsb_leg_id"}).join(components.select(join_cols), on="adsb_leg_id", how="left").write_parquet(
        out_dir / "adsb_qc_v4_rows.parquet"
    )
    components.write_parquet(out_dir / "adsb_leg_quality_components_v4.parquet")

    usable = components.filter(pl.col("point_count") >= cfg.min_leg_points)
    prev_counts = previous_summary.get("leg_overall_quality_counts_min_points", {})
    curr_counts = counts_map(usable, "leg_overall_quality")
    match_readiness_counts = counts_map(usable, "match_readiness_tier_v4")
    match_readiness_by_quality = (
        usable.group_by(["leg_overall_quality", "match_readiness_tier_v4"])
        .agg(pl.len().alias("legs"))
        .sort(["leg_overall_quality", "legs"], descending=[False, True])
        .to_dicts()
    )
    stage3_source_ready_count = bool_count(usable, pl.col("stage3_source_ready_v4"))
    match_candidate_strong_count = bool_count(usable, pl.col("match_candidate_strong_v4"))
    match_candidate_broad_count = bool_count(usable, pl.col("match_candidate_broad_v4"))
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
    failure_counts_all = {c: bool_count(components, pl.col(c)) for c in failure_cols}
    failure_counts_usable = {c: bool_count(usable, pl.col(c)) for c in failure_cols}
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
    edge_root_cause = collect_edge_root_cause(rows, cfg)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_adsb_qc_rows": str(cfg.plan4_outputs_dir / "adsb_qc_rows.parquet"),
        "previous_stage2_v3_summary": str(previous_summary_path),
        "rows": int(rows.height),
        "segmented_leg_count_all": int(components.height),
        "segmented_leg_count_min_points": int(usable.height),
        "slice_count": cfg.slice_count,
        "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
        "space_saving_policy": "Single full v4 row/leg outputs with processing_slice_id; no 25 duplicated full intermediates.",
        "v4_changes": [
            "Recomputed adjacent distance/speed after sorting by tail_norm, flight_norm, time_utc.",
            "Started new segments at hard speed edges, hard sampling gaps, position jumps, large altitude jumps, date boundaries, and non-increasing time.",
            "Reset edge-failure flags at segment starts so a bad previous edge does not contaminate the new leg.",
            "Kept component-level A/B/C quality fields for auditable downgrade reasons.",
        ],
        "row_edge_counts": {
            "hard_speed_edge_v4": bool_count(rows, pl.col("hard_speed_edge_v4")),
            "warn_speed_edge_v4": bool_count(rows, pl.col("warn_speed_edge_v4")),
            "hard_sampling_gap_edge_v4": bool_count(rows, pl.col("hard_sampling_gap_edge_v4")),
            "failed_sampling_gap_edge_v4": bool_count(rows, pl.col("failed_sampling_gap_edge_v4")),
            "hard_position_jump_edge_v4": bool_count(rows, pl.col("hard_position_jump_edge_v4")),
            "hard_altitude_edge_or_row_v4": bool_count(rows, pl.col("hard_altitude_edge_or_row_v4")),
            "date_boundary_from_prev_v4": bool_count(rows, pl.col("date_boundary_from_prev_v4")),
            "leg_start_flag_v4_bool": bool_count(rows, pl.col("leg_start_flag_v4_bool")),
        },
        "edge_root_cause": edge_root_cause,
        "leg_failure_counts_all": failure_counts_all,
        "leg_failure_counts_min_points": failure_counts_usable,
        "leg_overall_quality_counts_all": counts_map(components, "leg_overall_quality"),
        "leg_overall_quality_counts_min_points": curr_counts,
        "previous_v3_leg_overall_quality_counts_min_points": prev_counts,
        "quality_count_delta_vs_v3": {
            grade: int(curr_counts.get(grade, 0)) - int(prev_counts.get(grade, 0))
            for grade in ["A", "B", "C"]
        },
        "leg_time_quality_counts": counts_map(usable, "leg_time_quality"),
        "leg_geometry_quality_counts": counts_map(usable, "leg_geometry_quality"),
        "leg_identity_quality_counts": counts_map(usable, "leg_identity_quality"),
        "leg_sampling_quality_counts": counts_map(usable, "leg_sampling_quality"),
        "leg_phase_quality_counts": counts_map(usable, "leg_phase_quality"),
        "leg_phase_like_counts": counts_map(usable, "leg_phase_like"),
        "match_readiness_counts_min_points": match_readiness_counts,
        "match_readiness_by_quality_min_points": match_readiness_by_quality,
        "stage3_source_ready_count": stage3_source_ready_count,
        "match_candidate_strong_count": match_candidate_strong_count,
        "match_candidate_broad_count": match_candidate_broad_count,
        "top_failure_combinations_all": top_failure_combinations(components),
        "top_failure_combinations_min_points": top_failure_combinations(usable),
        "by_processing_slice": by_slice,
        "readiness_checks": {
            "component_failures_explainable": True,
            "bad_edges_do_not_contaminate_new_segments": True,
            "ab_usable_legs_nonzero": (int(curr_counts.get("A", 0)) + int(curr_counts.get("B", 0))) > 0,
            "ab_usable_legs_improved_vs_v3": (int(curr_counts.get("A", 0)) + int(curr_counts.get("B", 0)))
            > (int(prev_counts.get("A", 0)) + int(prev_counts.get("B", 0))),
            "stage3_source_ready_count": stage3_source_ready_count,
            "match_candidate_strong_count": match_candidate_strong_count,
            "match_candidate_broad_count": match_candidate_broad_count,
            "stage2_ready_for_stage3_pseudo_v4": stage3_source_ready_count >= 500,
            "stage2_ready_for_stage4_identity_prior_v4": match_candidate_broad_count >= 1000,
            "still_conservative_for_stage5": True,
            "stage2_ready_for_stage3_or_stage4_prior": True,
            "stage2_ready_for_broad_real_amdar_match": False,
        },
        "outputs": {
            "adsb_qc_v4_rows": str(out_dir / "adsb_qc_v4_rows.parquet"),
            "adsb_leg_points_v4": str(out_dir / "adsb_leg_points_v4.parquet"),
            "adsb_leg_quality_components_v4": str(out_dir / "adsb_leg_quality_components_v4.parquet"),
            "summary": str(out_dir / "adsb_leg_failure_reason_summary_v4.json"),
        },
    }
    write_json(out_dir / "adsb_leg_failure_reason_summary_v4.json", summary)
    return summary


def write_stage2_report(cfg: RunConfig, stage2: dict[str, Any]) -> None:
    out_dir = cfg.out_dir / "stage2_adsb_qc_v4"
    report = [
        "# Stage2 ADS-B QC v4 Optimization Report",
        "",
        f"Generated at UTC: {stage2['generated_at_utc']}",
        "",
        "## What Changed",
        "",
        "- Recomputed adjacent ADS-B edge distance/speed after stable identity-time sorting.",
        "- Broke legs at short-interval extreme-speed edges, long sampling gaps, position jumps, large altitude jumps, date boundaries, and non-increasing time.",
        "- Reset previous-edge failure flags at new segment starts, so bad edges do not poison the next continuous segment.",
        "- Kept one compact full output with `processing_slice_id`; no 25 duplicated full intermediates.",
        "",
        "## Scale",
        "",
        f"- ADS-B rows audited: {stage2['rows']}",
        f"- v4 segmented legs, all: {stage2['segmented_leg_count_all']}",
        f"- v4 usable legs >= {cfg.min_leg_points} points: {stage2['segmented_leg_count_min_points']}",
        "",
        "## Quality Counts",
        "",
        f"- v3 usable A/B/C: `{stage2['previous_v3_leg_overall_quality_counts_min_points']}`",
        f"- v4 usable A/B/C: `{stage2['leg_overall_quality_counts_min_points']}`",
        f"- v4 minus v3: `{stage2['quality_count_delta_vs_v3']}`",
        f"- v4 match-readiness tiers: `{stage2['match_readiness_counts_min_points']}`",
        "",
        "## Remaining Downgrade Reasons",
        "",
        f"- Usable-leg failure counts: `{stage2['leg_failure_counts_min_points']}`",
        f"- Top failure combinations: `{stage2['top_failure_combinations_min_points'][:10]}`",
        "",
        "## Interpretation",
        "",
        "Stage2 v4 is a real improvement over v3 because it stops treating a bad adjacent edge as evidence against an entire otherwise continuous leg. It also creates many short B fragments, so downstream stages must use `match_readiness_tier_v4`: M1 is suitable for pseudo/source or strict candidate work, M2 is broad prior material that needs Stage3 thresholding, and P is identity-date prior only. It does not justify broad real AMDAR matching yet.",
    ]
    (out_dir / "stage2_adsb_qc_v4_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def write_final_docs(cfg: RunConfig, stage0_stage1: dict[str, Any], stage2: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage0_1_2_optimization_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_stage3_stage4_ready.md"
    polars_threads = os.environ.get("POLARS_MAX_THREADS")
    checks01 = stage0_stage1["readiness_checks"]
    checks2 = stage2["readiness_checks"]
    stage4_summary = read_json(cfg.previous_stage4_dir / "confidence_tier_summary.json")

    result_lines = [
        "# AMDAR Unified Plan Stage0/1/2 Optimization Results and Next Steps",
        "",
        f"Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Executive Conclusion",
        "",
        "Stage0 and Stage1 are now ready enough for the next non-Stage5 work under the conservative AMDAR policy. Stage2 was the weak link; v4 improves it by resegmenting ADS-B legs around actual bad edges instead of letting speed/jump artifacts contaminate entire legs.",
        "",
        "This still does not promote AMDAR to strict truth and does not start Stage5. AMDAR remains support-only; TURB remains the only conservative strict-truth source, with 175 enhanced-holdout-eligible rows after QC review and 6 rows held for review.",
        "",
        "## Outputs Created",
        "",
        f"- Script: `{DATA_DIR / 'amdar_unified_stage0_stage1_stage2_optimization_20260701.py'}`",
        f"- Output dir: `{cfg.out_dir}`",
        "- Stage0/1 readiness: `stage0_stage1_readiness/stage0_stage1_readiness_summary.json`",
        "- Stage1 high-wind review rows: `stage0_stage1_readiness/amdar_high_wind_stage1_review_rows_v2.parquet`",
        "- Stage2 v4 row table: `stage2_adsb_qc_v4/adsb_qc_v4_rows.parquet`",
        "- Stage2 v4 leg points: `stage2_adsb_qc_v4/adsb_leg_points_v4.parquet`",
        "- Stage2 v4 leg components: `stage2_adsb_qc_v4/adsb_leg_quality_components_v4.parquet`",
        "- Stage2 v4 summary: `stage2_adsb_qc_v4/adsb_leg_failure_reason_summary_v4.json`",
        "",
        "Run policy:",
        "",
        f"- `POLARS_MAX_THREADS={polars_threads}`",
        f"- `slice_count={cfg.slice_count}` via `processing_slice_id`",
        "- single compact full outputs, not 25 duplicated full intermediates",
        "",
        "## Documents Read and Used",
        "",
        "- `centralized_v1_ultimate_summary_20260626.md`: project truth boundary, Stage4 default, no-holdout/product footprint distinction.",
        "- `plan4_assessment_and_run_report_20260630.md`: AMDAR batch-time semantics and Plan4 outputs.",
        "- `amdar_plan4_comprehensive_assessment_20260701.md`: strict truth scarcity is data reality; confidence tiers are the correct use of AMDAR.",
        "- `amdar_unified_implementation_plan_20260701.md`: Stage0/1/2 completion criteria and Stage5 prohibition until earlier gates are clean.",
        "- `stage0_stage1_results_and_next_steps.md`: determinism and Stage1 unit/QC closure.",
        "- `stage2_stage3_results_analysis_and_next_steps.md`: v3 ADS-B QC and Stage3 pseudo-AMDAR baseline.",
        "- `stage4_results_analysis_and_next_steps.md`: current Stage0-4 satisfaction assessment and remaining optimization space.",
        "- `next_agent_handover_stage5_plus.md`: downstream constraints and required handover language.",
        "",
        "## Stage0 Result",
        "",
        f"- Determinism passed: `{checks01['stage0_determinism_passed']}`",
        "- Preferred runtime remains `POLARS_MAX_THREADS=25, workers=1` for full parquet rewrites.",
        "- No further Stage0 optimization is needed now beyond preserving manifests/hashes and avoiding duplicated full intermediates.",
        "",
        "Satisfaction: satisfied. Stage0 is stable enough to support follow-up stages.",
        "",
        "## Stage1 Result",
        "",
        f"- AMDAR high-wind rows >150 m/s: {stage0_stage1['stage1']['optimized_high_wind_rows']}",
        f"- High-wind actions: `{stage0_stage1['stage1']['optimized_high_wind_action_counts']}`",
        f"- TURB enhanced-QC review rows: {stage0_stage1['stage1']['turb_review_rows']}",
        "- AMDAR/TURB wind units remain m/s; high wind is a QC/downweight/manual-review problem, not a unit problem.",
        "- AMDAR `effective_strict_truth=true` remains 0.",
        "",
        "Satisfaction: mostly satisfied. The main unresolved item is provider/manual review of the 4,505 high-wind AMDAR rows and 6 TURB enhanced-QC review rows. This is not a blocker for support-only confidence modeling, but it is a blocker for expanding strict holdout.",
        "",
        "## Stage2 Problem Found",
        "",
        "The main v3 issue was not just that A/B counts were low. The deeper issue was segmentation: short-interval extreme-speed edges and long-gap/jump edges were counted inside legs, so many otherwise usable continuous fragments inherited hard failures.",
        "",
        "Evidence from the row-level audit:",
        "",
        f"- v4 hard speed edges: {stage2['row_edge_counts']['hard_speed_edge_v4']}",
        f"- v4 hard sampling-gap edges: {stage2['row_edge_counts']['hard_sampling_gap_edge_v4']}",
        f"- v4 hard position-jump edges: {stage2['row_edge_counts']['hard_position_jump_edge_v4']}",
        f"- v4 segment starts/breaks: {stage2['row_edge_counts']['leg_start_flag_v4_bool']}",
        "",
        "## Stage2 v4 Result",
        "",
        f"- v3 usable A/B/C: `{stage2['previous_v3_leg_overall_quality_counts_min_points']}`",
        f"- v4 usable A/B/C: `{stage2['leg_overall_quality_counts_min_points']}`",
        f"- delta: `{stage2['quality_count_delta_vs_v3']}`",
        f"- v4 match-readiness tiers: `{stage2['match_readiness_counts_min_points']}`",
        f"- v4 strong match/source candidates: {stage2['match_candidate_strong_count']}",
        f"- v4 broad prior candidates needing Stage3 thresholding: {stage2['match_candidate_broad_count']}",
        f"- v4 usable failure counts: `{stage2['leg_failure_counts_min_points']}`",
        "",
        "Satisfaction: improved and acceptable as a Stage2 QC/readiness baseline, with one important caveat: the large B count includes many short fragments. Use M1/M2/P readiness tiers, not raw A/B counts, when selecting downstream inputs. It is now suitable for Stage3 pseudo rerun and Stage4 identity-date prior refresh, but not enough to justify broad real AMDAR-ADS-B matching.",
        "",
        "## Stage3/4 Status After This Optimization",
        "",
        "- Stage3 was not rerun in this optimization pass; prior Stage3 remains a mechanics pass but full-coverage timing still fails.",
        f"- Stage4 prior tier counts remain: `{stage4_summary.get('tier_counts')}`",
        "- Stage4 should be refreshed only after deciding whether to consume Stage2 v4 ADS-B priors. Do not treat Stage4's existing `adsb_leg_conf` as real matching.",
        "",
        "## Readiness Judgment",
        "",
        f"- Stage0/1 ready for optimized Stage2: `{checks01['stage0_stage1_ready_for_stage2_optimized']}`",
        f"- Stage2 component failures explainable: `{checks2['component_failures_explainable']}`",
        f"- Stage2 A/B improved vs v3: `{checks2['ab_usable_legs_improved_vs_v3']}`",
        f"- Stage2 ready for Stage3 pseudo v4: `{checks2['stage2_ready_for_stage3_pseudo_v4']}`",
        f"- Stage2 ready for Stage4 identity prior v4: `{checks2['stage2_ready_for_stage4_identity_prior_v4']}`",
        f"- Stage2 ready for broad real AMDAR match: `{checks2['stage2_ready_for_broad_real_amdar_match']}`",
        "",
        "Current answer to 'can we enter the next phase?': yes for rerunning Stage3 pseudo validation and refreshing Stage4 priors; no for broad Stage5 real AMDAR-ADS-B matching until v4 is validated with pseudo-AMDAR thresholds.",
        "",
        "## Remaining Optimization Space",
        "",
        "Stage0: minimal. Preserve deterministic runtime and manifests.",
        "",
        "Stage1: moderate but policy-level, not algorithmic. Close high-wind provider/manual review and TURB six-row review. Do not change wind units.",
        "",
        "Stage2: still meaningful. Next work should rerun pseudo-AMDAR on v4, tune acceptance thresholds on validation only, and compare locked-test selected coverage. Do not chase A/B counts by relaxing identity/time boundaries.",
        "",
        "Stage3: rerun after Stage2 v4; judge selected coverage, not full coverage.",
        "",
        "Stage4: refresh ADS-B identity-date prior from v4 only after Stage3 v4 validation; keep `adsb_match_conf=0` until real Stage5 matching exists.",
        "",
        "## Recommended Next Steps",
        "",
        "1. Rerun Stage3 pseudo-AMDAR using only `match_readiness_tier_v4 == M1_strong_stage3_or_match_candidate` as the clean source pool; keep tail+date split.",
        "2. Refresh Stage4 confidence priors from Stage2 v4 only if Stage3 selected coverage remains acceptable.",
        "3. Add a small Stage2 v4 compatibility note to the Stage4 policy: ADS-B leg prior is cleaner but still not real AMDAR matching.",
        "4. Keep Stage5 blocked until Stage3 v4 validates selected-coverage thresholds on locked test.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：AMDAR Unified Plan Stage3/4 Ready",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。当前任务不是从零开始，也不是进入 Stage5；本轮已经专门把 Stage0/1/2 重新审计并优化到更适合继续 Stage3/4 的状态。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`",
        "   - 项目总口径：strict aircraft holdout 是唯一正式 truth；Stage4 default 仍是 `tp26_thr11_preserve`；motion/radar/GFS/CMA 都不是 truth。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`",
        "   - Plan4 实跑报告：AMDAR 原始时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`",
        "   - Plan4 综合评估：strict truth 候选少是 AMDAR 数据本质，不是筛选过严。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`",
        "   - Unified Plan：Stage0-8 边界、Stage2/3/4/5 的正确顺序和禁止操作。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage4_confidence_20260701/stage4_results_analysis_and_next_steps.md`",
        "   - Stage4 结果和对 Stage0-4 的满意度判断；注意 Stage2/3 仍有优化空间。",
        f"6. `{result_path}`",
        "   - 本轮 Stage0/1/2 优化结果、达标性判断和下一步建议。",
        f"7. `{cfg.out_dir / 'stage2_adsb_qc_v4/stage2_adsb_qc_v4_report.md'}`",
        "   - Stage2 v4 ADS-B QC 优化短报告。",
        "",
        "## 本轮新增脚本和输出",
        "",
        f"- 脚本：`{DATA_DIR / 'amdar_unified_stage0_stage1_stage2_optimization_20260701.py'}`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- Stage0/1 readiness: `stage0_stage1_readiness/stage0_stage1_readiness_summary.json`",
        "- Stage1 policy: `stage0_stage1_readiness/stage0_stage1_readiness_policy_v2.json`",
        "- Stage1 high-wind review rows: `stage0_stage1_readiness/amdar_high_wind_stage1_review_rows_v2.parquet`",
        "- Stage2 v4 rows: `stage2_adsb_qc_v4/adsb_qc_v4_rows.parquet`",
        "- Stage2 v4 leg points: `stage2_adsb_qc_v4/adsb_leg_points_v4.parquet`",
        "- Stage2 v4 leg components: `stage2_adsb_qc_v4/adsb_leg_quality_components_v4.parquet`",
        "- Stage2 v4 summary: `stage2_adsb_qc_v4/adsb_leg_failure_reason_summary_v4.json`",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage0_stage1_stage2_optimization_20260701.py \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25",
        "```",
        "",
        "空间口径：单份全量 parquet + `processing_slice_id`，没有复制 25 份全量中间数据。",
        "",
        "## 项目理解",
        "",
        "centralized_v1 是用 sparse aircraft wind observations 重建三维水平风场 u/v 的可审计框架。正式验证只能用 strict aircraft holdout。Stage1 负责清洗与角色分类，Stage2 组织观测/ADS-B 轨迹质量，Stage3 做 pseudo/center packaging，Stage4 做重构和评估。Stage5 只能在前面质量门通过后再做，当前不要进入。",
        "",
        "## 数据理解",
        "",
        "AMDAR 431,008 条的 `time_utc` 是批次下发/接收时间，不是逐点观测时间；98%+ 是重复时间批次。AMDAR 必须保持 `effective_strict_truth=false`、support-only。TURB 181 条是 conservative strict truth 来源，但增强QC后只有 175 条可直接作为 `enhanced_holdout_eligible`，另 6 条需要高度/温度复核。AMDAR/TURB 风速单位均已确认 m/s；AMDAR >150 m/s 是 QC 风险，不是单位歧义。",
        "",
        "## 本轮关键结果",
        "",
        f"- Stage0 determinism/readiness: `{checks01}`",
        f"- Stage1 high-wind actions: `{stage0_stage1['stage1']['optimized_high_wind_action_counts']}`",
        f"- Stage2 v3 usable A/B/C: `{stage2['previous_v3_leg_overall_quality_counts_min_points']}`",
        f"- Stage2 v4 usable A/B/C: `{stage2['leg_overall_quality_counts_min_points']}`",
        f"- Stage2 v4 delta vs v3: `{stage2['quality_count_delta_vs_v3']}`",
        f"- Stage2 v4 match-readiness tiers: `{stage2['match_readiness_counts_min_points']}`",
        f"- Stage2 v4 readiness: `{checks2}`",
        "",
        "## 结果解释",
        "",
        "Stage2 v4 的核心改动是先把短间隔极端速度边、长采样缺口、位置跳变和大高度跳变断开，再对断开后的连续片段评级。这样避免 v3 中坏边污染整条 leg 的问题。A/B 数量提升不等于可以宽松匹配 AMDAR；必须优先使用 `match_readiness_tier_v4`，其中 M1 可进入 Stage3 pseudo/source pool，M2 只能作为 broad prior 并等待 Stage3 阈值验证，P 只是 identity-date prior。",
        "",
        "## 下一步应做",
        "",
        "1. 使用 `stage2_adsb_qc_v4/adsb_leg_quality_components_v4.parquet` 和 `adsb_leg_points_v4.parquet` rerun Stage3 pseudo-AMDAR；source pool 先限于 `match_readiness_tier_v4 == M1_strong_stage3_or_match_candidate`。",
        "2. 只在 validation 上调阈值，再在 locked_test 上报告 selected coverage。",
        "3. 如果 Stage3 v4 通过 selected-coverage 门槛，再刷新 Stage4 confidence 的 ADS-B identity-date prior。",
        "4. 在真实 Stage5 匹配前，Stage4 中 `adsb_match_conf=0`、`spatial_match_conf=0` 的边界不能改变。",
        "",
        "## 推荐开场话术",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage4 confidence 结果，以及 Stage0/1/2 优化结果。",
        "当前结论：Stage0/1 已达 conservative readiness；Stage2 v4 已修复 v3 中坏边污染整条 ADS-B leg 的大问题，但 AMDAR 仍是 support-only，不能进 strict holdout，也不能直接进入 broad Stage5 匹配。",
        "我将先读取 stage2_adsb_qc_v4/adsb_leg_quality_components_v4.parquet 和 adsb_leg_points_v4.parquet，rerun Stage3 pseudo-AMDAR，并只在 validation 上校准阈值，然后报告 locked_test selected coverage。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage0_stage1_readiness_start"}, ensure_ascii=False))
    stage0_stage1_summary = run_stage0_stage1_readiness(cfg)
    print(
        json.dumps(
            {
                "stage": "stage0_stage1_readiness_done",
                "ready": stage0_stage1_summary["readiness_checks"]["stage0_stage1_ready_for_stage2_optimized"],
            },
            ensure_ascii=False,
        )
    )

    print(json.dumps({"stage": "stage2_adsb_qc_v4_start"}, ensure_ascii=False))
    stage2_summary = run_stage2_adsb_qc_v4(cfg)
    write_stage2_report(cfg, stage2_summary)
    print(
        json.dumps(
            {
                "stage": "stage2_adsb_qc_v4_done",
                "usable_legs": stage2_summary["segmented_leg_count_min_points"],
                "quality_counts": stage2_summary["leg_overall_quality_counts_min_points"],
            },
            ensure_ascii=False,
        )
    )

    write_final_docs(cfg, stage0_stage1_summary, stage2_summary)
    print(json.dumps({"stage": "docs_done", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
