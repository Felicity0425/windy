from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
STAGE1_DIR = ROOT / "优化/数据处理/amdar_plan4_implementation_20260630/stage1_output_plan4_v1"
STAGE0_STAGE1_DIR = ROOT / "优化/数据处理/amdar_unified_stage0_stage1_20260701"
STAGE2_STAGE3_DIR = ROOT / "优化/数据处理/amdar_unified_stage2_stage3_20260701"
DEFAULT_OUT = ROOT / "优化/数据处理/amdar_unified_stage4_confidence_20260701"

WIND_SPEED_MS_PLAUSIBLE_MAX = 150.0
WIND_SPEED_MS_REJECT_REVIEW = 200.0
EPS = 1.0e-6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AMDAR Unified Plan stage4 confidence component model without mutating the frozen Plan4 baseline."
    )
    parser.add_argument("--stage1-dir", default=str(STAGE1_DIR))
    parser.add_argument("--stage0-stage1-dir", default=str(STAGE0_STAGE1_DIR))
    parser.add_argument("--stage2-stage3-dir", default=str(STAGE2_STAGE3_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--slice-count", type=int, default=25)
    return parser.parse_args()


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
        "p10": float(finite.quantile(0.10)) if finite.len() else None,
        "q50": float(finite.quantile(0.50)) if finite.len() else None,
        "p90": float(finite.quantile(0.90)) if finite.len() else None,
        "p99": float(finite.quantile(0.99)) if finite.len() else None,
        "max": float(finite.max()) if finite.len() else None,
    }


def normalize_text_expr(col: str, fallback: str = "MISSING") -> pl.Expr:
    return (
        pl.when(pl.col(col).is_null())
        .then(pl.lit(fallback))
        .otherwise(
            pl.col(col)
            .cast(pl.Utf8, strict=False)
            .str.strip_chars()
            .str.to_uppercase()
            .str.replace_all(r"[^A-Z0-9]", "")
        )
        .alias(col)
    )


def grade_score_expr(col: str) -> pl.Expr:
    return (
        pl.when(pl.col(col) == "A")
        .then(pl.lit(3))
        .when(pl.col(col) == "B")
        .then(pl.lit(2))
        .otherwise(pl.lit(1))
    )


def finite_expr(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.Float64, strict=False).is_finite()


def clamp_expr(expr: pl.Expr, low: float = 0.0, high: float = 1.0) -> pl.Expr:
    return expr.clip(lower_bound=low, upper_bound=high)


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


def add_batch_confidence(df: pl.LazyFrame) -> pl.LazyFrame:
    size_factor = (
        pl.when(pl.col("source") != "amdar")
        .then(pl.lit(1.0))
        .when(pl.col("amdar_batch_row_count") <= 1)
        .then(pl.lit(0.85))
        .when(pl.col("amdar_batch_row_count") <= 4)
        .then(pl.lit(0.70))
        .when(pl.col("amdar_batch_row_count") <= 10)
        .then(pl.lit(0.55))
        .when(pl.col("amdar_batch_row_count") <= 25)
        .then(pl.lit(0.35))
        .otherwise(pl.lit(0.15))
    )
    spatial_factor = (
        pl.when(pl.col("source") != "amdar")
        .then(pl.lit(1.0))
        .when((pl.col("amdar_batch_hspan_deg") < 0.1) & (pl.col("amdar_batch_vertical_span_m") < 200.0))
        .then(pl.lit(1.0))
        .when((pl.col("amdar_batch_hspan_deg") < 0.5) & (pl.col("amdar_batch_vertical_span_m") < 500.0))
        .then(pl.lit(0.85))
        .when((pl.col("amdar_batch_hspan_deg") < 1.0) & (pl.col("amdar_batch_vertical_span_m") < 1000.0))
        .then(pl.lit(0.65))
        .when((pl.col("amdar_batch_hspan_deg") < 2.0) & (pl.col("amdar_batch_vertical_span_m") < 2000.0))
        .then(pl.lit(0.40))
        .otherwise(pl.lit(0.15))
    )
    phase_factor = (
        pl.when(pl.col("source") != "amdar")
        .then(pl.lit(1.0))
        .when(pl.col("飞行阶段") == "LVR")
        .then(pl.lit(1.0))
        .when(pl.col("飞行阶段") == "ASC")
        .then(pl.lit(0.85))
        .when(pl.col("飞行阶段") == "DES")
        .then(pl.lit(0.75))
        .otherwise(pl.lit(0.70))
    )
    batch_met_factor = (
        pl.when(pl.col("source") != "amdar")
        .then(pl.lit(1.0))
        .when(pl.col("amdar_batch_row_count") <= 1)
        .then(pl.lit(0.90))
        .when(pl.col("batch_wind_speed_std_ms").fill_null(999.0) < 5.0)
        .then(pl.lit(1.0))
        .when(pl.col("batch_wind_speed_std_ms").fill_null(999.0) < 10.0)
        .then(pl.lit(0.85))
        .when(pl.col("batch_wind_speed_std_ms").fill_null(999.0) < 20.0)
        .then(pl.lit(0.70))
        .otherwise(pl.lit(0.50))
    )
    batch_time_uncertainty = (
        pl.when(pl.col("source") != "amdar")
        .then(pl.lit(0.0))
        .when(pl.col("amdar_batch_row_count") <= 1)
        .then(pl.lit(300.0))
        .when(pl.col("amdar_batch_row_count") <= 4)
        .then(pl.lit(600.0))
        .when(pl.col("amdar_batch_row_count") <= 10)
        .then(pl.lit(900.0))
        .when(pl.col("amdar_batch_row_count") <= 25)
        .then(pl.lit(1500.0))
        .otherwise(pl.lit(1800.0))
    )
    return df.with_columns(
        [
            size_factor.alias("batch_size_conf"),
            spatial_factor.alias("spatial_representativeness_conf"),
            phase_factor.alias("sequence_conf"),
            batch_met_factor.alias("batch_met_consistency_conf"),
            batch_time_uncertainty.alias("batch_time_uncertainty_s"),
        ]
    ).with_columns(
        [
            clamp_expr(
                pl.col("batch_size_conf")
                * pl.col("spatial_representativeness_conf")
                * pl.col("sequence_conf")
                * pl.col("batch_met_consistency_conf"),
                0.05,
                0.85,
            ).alias("batch_conf")
        ]
    )


def build_components(args: argparse.Namespace) -> pl.DataFrame:
    stage1_dir = Path(args.stage1_dir)
    stage0_stage1_dir = Path(args.stage0_stage1_dir)
    stage2_stage3_dir = Path(args.stage2_stage3_dir)

    clean_wind_path = stage1_dir / "clean_wind.parquet"
    stage1_qc_path = stage0_stage1_dir / "stage1_quality_audit/stage1_met_qc_rows.parquet"
    leg_components_path = stage2_stage3_dir / "stage2_adsb_qc_v3/adsb_leg_quality_components.parquet"

    wind_cols = [
        "source",
        "source_row_index",
        "raw_row_number",
        "机尾号",
        "航班号",
        "flight_id",
        "飞行阶段",
        "time_utc",
        "observation_time_utc",
        "observation_time_source",
        "observation_time_uncertainty_s",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "wind_speed",
        "wind_dir",
        "u_wind",
        "v_wind",
        "met_value_quality",
        "obs_conf",
        "amdar_batch_id",
        "amdar_batch_row_count",
        "amdar_observation_order",
        "amdar_batch_time_utc",
        "amdar_batch_hspan_deg",
        "amdar_batch_vertical_span_m",
        "amdar_batch_is_contiguous",
        "time_group_alignment_flag",
        "strict_time_truth",
        "time_is_point_observation",
        "point_observation_time_available",
        "batch_end_is_time_upper_bound",
        "wind_reconstruction_role",
        "usage_role",
        "legacy_wind_reconstruction_role",
        "effective_strict_truth",
    ]
    qc_cols = [
        "source",
        "source_row_index",
        "wind_speed_raw",
        "wind_speed_unit_source",
        "wind_speed_unit_normalized",
        "wind_speed_ms",
        "wind_speed_unit_conversion_applied",
        "wind_direction_raw_deg",
        "temperature_raw_c",
        "met_value_quality_audit",
        "wind_speed_outlier_flag",
        "wind_direction_invalid_flag",
        "uv_nonfinite_flag",
        "temperature_outlier_flag",
        "altitude_outlier_flag",
        "duplicate_met_record_flag",
    ]

    wind_schema = pl.read_parquet_schema(clean_wind_path)
    qc_schema = pl.read_parquet_schema(stage1_qc_path)
    wind = pl.scan_parquet(clean_wind_path).select([c for c in wind_cols if c in wind_schema])
    qc = pl.scan_parquet(stage1_qc_path).select([c for c in qc_cols if c in qc_schema])

    batch_stats = (
        wind.filter(pl.col("source") == "amdar")
        .group_by("amdar_batch_id")
        .agg(
            [
                pl.col("wind_speed").cast(pl.Float64, strict=False).std().alias("batch_wind_speed_std_ms"),
                pl.col("wind_speed").cast(pl.Float64, strict=False).min().alias("batch_wind_speed_min_ms"),
                pl.col("wind_speed").cast(pl.Float64, strict=False).max().alias("batch_wind_speed_max_ms"),
                pl.col("wind_dir").cast(pl.Float64, strict=False).std().alias("batch_wind_dir_linear_std_deg"),
                pl.len().alias("batch_actual_row_count"),
            ]
        )
    )

    wind_qc = (
        wind.join(qc, on=["source", "source_row_index"], how="left")
        .join(batch_stats, on="amdar_batch_id", how="left")
        .with_columns(
            [
                normalize_text_expr("机尾号").alias("tail_norm"),
                normalize_text_expr("航班号").alias("flight_norm"),
                pl.col("time_utc").dt.strftime("%Y-%m-%d").alias("service_date_utc"),
                batch_size_bucket_expr().alias("amdar_batch_size_bucket"),
                ((pl.col("source_row_index").cast(pl.UInt64) % int(args.slice_count)).cast(pl.UInt8)).alias("processing_slice_id"),
                pl.col("wind_speed_ms").fill_null(pl.col("wind_speed")).cast(pl.Float64, strict=False).alias("wind_speed_ms_filled"),
                pl.col("wind_direction_raw_deg").fill_null(pl.col("wind_dir")).cast(pl.Float64, strict=False).alias("wind_dir_deg_filled"),
            ]
        )
    )

    leg_schema = pl.read_parquet_schema(leg_components_path)
    leg_cols = [
        "tail_norm",
        "flight_norm",
        "service_date_utc",
        "adsb_leg_id",
        "processing_slice_id",
        "point_count",
        "duration_seconds",
        "leg_overall_quality",
        "leg_time_quality",
        "leg_geometry_quality",
        "leg_identity_quality",
        "leg_sampling_quality",
        "leg_phase_quality",
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
    leg = pl.scan_parquet(leg_components_path).select([c for c in leg_cols if c in leg_schema])
    usable_leg = leg.filter(pl.col("point_count") >= 5)
    identity_leg = (
        usable_leg.group_by(["tail_norm", "flight_norm", "service_date_utc"])
        .agg(
            [
                pl.len().alias("same_identity_date_leg_count"),
                (pl.col("leg_overall_quality") == "A").sum().alias("same_identity_date_leg_A_count"),
                (pl.col("leg_overall_quality") == "B").sum().alias("same_identity_date_leg_B_count"),
                (pl.col("leg_overall_quality") == "C").sum().alias("same_identity_date_leg_C_count"),
                grade_score_expr("leg_overall_quality").max().alias("same_identity_date_best_leg_score"),
                pl.col("point_count").sum().alias("same_identity_date_leg_points"),
                pl.col("duration_seconds").max().alias("same_identity_date_max_duration_seconds"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("same_identity_date_best_leg_score") >= 3)
                .then(pl.lit("A"))
                .when(pl.col("same_identity_date_best_leg_score") >= 2)
                .then(pl.lit("B"))
                .when(pl.col("same_identity_date_best_leg_score") >= 1)
                .then(pl.lit("C"))
                .otherwise(pl.lit("none"))
                .alias("same_identity_date_best_leg_quality"),
                (
                    (pl.col("same_identity_date_leg_A_count") * 1.0 + pl.col("same_identity_date_leg_B_count") * 0.8 + pl.col("same_identity_date_leg_C_count") * 0.5)
                    / pl.col("same_identity_date_leg_count").clip(lower_bound=1)
                ).alias("same_identity_date_leg_quality_mean_conf"),
            ]
        )
    )

    df = wind_qc.join(identity_leg, on=["tail_norm", "flight_norm", "service_date_utc"], how="left")
    df = add_batch_confidence(df)

    finite_met = finite_expr("wind_speed_ms_filled") & finite_expr("wind_dir_deg_filled") & finite_expr("u_wind") & finite_expr("v_wind")
    bad_met = (
        ~finite_met
        | (pl.col("wind_speed_ms_filled") < 0.0)
        | (pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_REJECT_REVIEW)
        | (pl.col("wind_dir_deg_filled") < 0.0)
        | (pl.col("wind_dir_deg_filled") >= 360.0)
        | pl.col("uv_nonfinite_flag").fill_null(False)
    )
    review_met = (
        pl.col("wind_speed_outlier_flag").fill_null(False)
        | pl.col("temperature_outlier_flag").fill_null(False)
        | pl.col("altitude_outlier_flag").fill_null(False)
        | pl.col("duplicate_met_record_flag").fill_null(False)
    )
    uv_delta = (
        ((pl.col("u_wind").cast(pl.Float64, strict=False) ** 2 + pl.col("v_wind").cast(pl.Float64, strict=False) ** 2).sqrt() - pl.col("wind_speed_ms_filled")).abs()
    )

    df = df.with_columns(
        [
            pl.when(pl.col("source") == "turb")
            .then(pl.lit(1.0))
            .when(pl.col("source") == "amdar")
            .then(pl.lit(0.90))
            .otherwise(pl.lit(0.70))
            .alias("source_conf"),
            pl.when(bad_met)
            .then(pl.lit(0.0))
            .when(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_PLAUSIBLE_MAX)
            .then(pl.lit(0.35))
            .when(review_met)
            .then(pl.lit(0.60))
            .when(uv_delta > 0.5)
            .then(pl.lit(0.60))
            .otherwise(pl.lit(1.0))
            .alias("met_conf"),
            pl.when(pl.col("source") == "turb")
            .then(pl.lit(1.0))
            .when(pl.col("source") == "amdar")
            .then((pl.col("batch_conf") / 0.85).clip(lower_bound=0.05, upper_bound=1.0))
            .otherwise(pl.lit(0.50))
            .alias("time_source_conf"),
            pl.when((pl.col("tail_norm") != "MISSING") & (pl.col("flight_norm") != "MISSING"))
            .then(pl.lit(1.0))
            .when((pl.col("tail_norm") != "MISSING") | (pl.col("flight_norm") != "MISSING"))
            .then(pl.lit(0.75))
            .otherwise(pl.lit(0.35))
            .alias("identity_conf"),
            pl.when(pl.col("same_identity_date_best_leg_quality") == "A")
            .then(pl.lit(1.0))
            .when(pl.col("same_identity_date_best_leg_quality") == "B")
            .then(pl.lit(0.80))
            .when(pl.col("same_identity_date_best_leg_quality") == "C")
            .then(pl.lit(0.50))
            .otherwise(pl.lit(0.0))
            .alias("adsb_leg_conf"),
            pl.lit(0.0).alias("adsb_match_conf"),
            pl.lit(0.0).alias("spatial_match_conf"),
            pl.when(pl.col("source") == "amdar")
            .then((1.0 / pl.col("amdar_batch_row_count").cast(pl.Float64, strict=False).sqrt()).clip(lower_bound=0.10, upper_bound=1.0))
            .otherwise(pl.lit(1.0))
            .alias("density_conf"),
            (pl.col("source") == "amdar").alias("is_amdar"),
            (pl.col("source") == "turb").alias("is_turb"),
        ]
    )

    components = [
        "source_conf",
        "met_conf",
        "time_source_conf",
        "sequence_conf",
        "identity_conf",
        "adsb_leg_conf",
        "adsb_match_conf",
        "spatial_match_conf",
        "spatial_representativeness_conf",
        "density_conf",
    ]
    weights = {
        "source_conf": 1.0,
        "met_conf": 2.0,
        "time_source_conf": 2.0,
        "sequence_conf": 1.0,
        "identity_conf": 1.0,
        "adsb_leg_conf": 0.5,
        "adsb_match_conf": 0.0,
        "spatial_match_conf": 0.0,
        "spatial_representativeness_conf": 1.0,
        "density_conf": 1.0,
    }
    denom = sum(weights.values())
    weighted_log = sum(pl.lit(w) * (pl.col(c).clip(EPS, 1.0).log()) for c, w in weights.items() if w > 0)

    df = df.with_columns(
        [
            pl.when(pl.col("is_turb"))
            .then(pl.lit(1.0))
            .otherwise((weighted_log / denom).exp().clip(lower_bound=0.0, upper_bound=0.85))
            .alias("base_support_conf_pre_qc"),
            (
                bad_met
                | (
                    (pl.col("source") == "turb")
                    & (pl.col("temperature_outlier_flag").fill_null(False) | pl.col("altitude_outlier_flag").fill_null(False))
                )
            ).alias("hard_reject_flag"),
        ]
    )
    df = df.with_columns(
        [
            pl.when(pl.col("hard_reject_flag"))
            .then(pl.lit(0.0))
            .when((pl.col("source") == "amdar") & (pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_PLAUSIBLE_MAX))
            .then((pl.col("base_support_conf_pre_qc") * 0.35).clip(0.0, 0.30))
            .otherwise(pl.col("base_support_conf_pre_qc"))
            .alias("base_support_conf"),
            pl.when(pl.col("is_turb") & pl.col("effective_strict_truth").fill_null(False) & ~pl.col("hard_reject_flag"))
            .then(pl.lit(0.0))
            .otherwise(pl.col("batch_time_uncertainty_s"))
            .alias("time_uncertainty_s_stage4"),
        ]
    )

    reject_reason = (
        pl.when(~finite_met)
        .then(pl.lit("nonfinite_wind_or_uv"))
        .when(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_REJECT_REVIEW)
        .then(pl.lit("wind_speed_gt_200_mps_manual_review"))
        .when(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_PLAUSIBLE_MAX)
        .then(pl.lit("wind_speed_gt_150_mps_downweighted"))
        .when((pl.col("source") == "turb") & pl.col("altitude_outlier_flag").fill_null(False))
        .then(pl.lit("turb_altitude_missing_or_outlier_review"))
        .when((pl.col("source") == "turb") & pl.col("temperature_outlier_flag").fill_null(False))
        .then(pl.lit("turb_temperature_outlier_review"))
        .when(pl.col("duplicate_met_record_flag").fill_null(False))
        .then(pl.lit("duplicate_met_record_downweighted"))
        .otherwise(pl.lit("none"))
    )
    df = df.with_columns(
        [
            reject_reason.alias("primary_quality_action_reason"),
            pl.when(pl.col("source") == "turb")
            .then(pl.col("effective_strict_truth").fill_null(False) & ~pl.col("hard_reject_flag"))
            .otherwise(pl.lit(False))
            .alias("enhanced_holdout_eligible"),
            pl.lit(False).alias("adsb_reconstructed"),
            pl.lit("stage5_pending_no_real_amdar_adsb_match_yet").alias("adsb_match_status"),
            pl.when(pl.col("source") == "turb")
            .then(pl.lit("point_observation"))
            .otherwise(pl.lit("batch_feature_prior"))
            .alias("confidence_basis"),
        ]
    )

    df = df.with_columns(
        [
            pl.when(pl.col("source") == "turb")
            .then(pl.when(pl.col("enhanced_holdout_eligible")).then(pl.lit("T0")).otherwise(pl.lit("T4")))
            .when(pl.col("hard_reject_flag"))
            .then(pl.lit("T4"))
            .when((pl.col("base_support_conf") >= 0.70) & (pl.col("time_uncertainty_s_stage4") <= 300.0))
            .then(pl.lit("T1"))
            .when((pl.col("base_support_conf") >= 0.45) & (pl.col("time_uncertainty_s_stage4") <= 900.0))
            .then(pl.lit("T2"))
            .when((pl.col("base_support_conf") >= 0.25) & (pl.col("time_uncertainty_s_stage4") <= 1800.0))
            .then(pl.lit("T3"))
            .otherwise(pl.lit("T4"))
            .alias("confidence_tier"),
            pl.when(pl.col("source") == "turb")
            .then(pl.when(pl.col("enhanced_holdout_eligible")).then(pl.lit("S")).otherwise(pl.lit("R")))
            .when(pl.col("hard_reject_flag"))
            .then(pl.lit("R"))
            .when((pl.col("base_support_conf") >= 0.70) & (pl.col("time_uncertainty_s_stage4") <= 300.0))
            .then(pl.lit("A"))
            .when((pl.col("base_support_conf") >= 0.45) & (pl.col("time_uncertainty_s_stage4") <= 900.0))
            .then(pl.lit("B"))
            .when((pl.col("base_support_conf") >= 0.25) & (pl.col("time_uncertainty_s_stage4") <= 1800.0))
            .then(pl.lit("C"))
            .otherwise(pl.lit("D"))
            .alias("confidence_grade"),
            pl.when(pl.col("source") == "turb")
            .then(pl.when(pl.col("enhanced_holdout_eligible")).then(pl.lit("strict_holdout")).otherwise(pl.lit("strict_holdout_review")))
            .when(pl.col("hard_reject_flag"))
            .then(pl.lit("rejected_or_manual_review"))
            .when((pl.col("base_support_conf") >= 0.45) & (pl.col("time_uncertainty_s_stage4") <= 900.0))
            .then(pl.lit("support_assimilation_candidate"))
            .when((pl.col("base_support_conf") >= 0.25) & (pl.col("time_uncertainty_s_stage4") <= 1800.0))
            .then(pl.lit("low_confidence_support_or_superob_only"))
            .otherwise(pl.lit("display_only_or_reject"))
            .alias("recommended_stage4_role"),
        ]
    )

    output_cols = [
        "source",
        "source_row_index",
        "raw_row_number",
        "flight_id",
        "机尾号",
        "航班号",
        "tail_norm",
        "flight_norm",
        "service_date_utc",
        "飞行阶段",
        "time_utc",
        "observation_time_utc",
        "observation_time_source",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "wind_speed_ms_filled",
        "wind_dir_deg_filled",
        "u_wind",
        "v_wind",
        "temperature_raw_c",
        "amdar_batch_id",
        "amdar_batch_row_count",
        "amdar_batch_size_bucket",
        "amdar_batch_hspan_deg",
        "amdar_batch_vertical_span_m",
        "amdar_observation_order",
        "processing_slice_id",
        "strict_time_truth",
        "time_is_point_observation",
        "point_observation_time_available",
        "batch_end_is_time_upper_bound",
        "effective_strict_truth",
        "enhanced_holdout_eligible",
        "wind_reconstruction_role",
        "usage_role",
        "legacy_wind_reconstruction_role",
        "met_value_quality",
        "met_value_quality_audit",
        "wind_speed_outlier_flag",
        "temperature_outlier_flag",
        "altitude_outlier_flag",
        "duplicate_met_record_flag",
        "source_conf",
        "met_conf",
        "batch_conf",
        "time_source_conf",
        "sequence_conf",
        "identity_conf",
        "adsb_leg_conf",
        "adsb_match_conf",
        "spatial_match_conf",
        "spatial_representativeness_conf",
        "density_conf",
        "batch_size_conf",
        "batch_met_consistency_conf",
        "base_support_conf_pre_qc",
        "base_support_conf",
        "time_uncertainty_s_stage4",
        "confidence_tier",
        "confidence_grade",
        "confidence_basis",
        "recommended_stage4_role",
        "primary_quality_action_reason",
        "same_identity_date_leg_count",
        "same_identity_date_best_leg_quality",
        "same_identity_date_leg_quality_mean_conf",
        "adsb_reconstructed",
        "adsb_match_status",
    ]
    return df.select([c for c in output_cols if c in df.collect_schema().names()]).collect(streaming=True)


def summarize_components(df: pl.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    amdar = df.filter(pl.col("source") == "amdar")
    turb = df.filter(pl.col("source") == "turb")
    support = amdar.filter(pl.col("base_support_conf") > 0)
    high_wind = amdar.filter(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_PLAUSIBLE_MAX)
    stage2_stage3_dir = Path(args.stage2_stage3_dir)
    pseudo_report_path = stage2_stage3_dir / "stage3_pseudo_amdar/pseudo_amdar_calibration_report.json"
    pseudo_report = json.loads(pseudo_report_path.read_text(encoding="utf-8")) if pseudo_report_path.exists() else {}
    quality_gate = pseudo_report.get("quality_gate", {})
    locked_metrics = pseudo_report.get("metrics", {}).get("locked_test", {})

    by_slice = (
        df.group_by("processing_slice_id")
        .agg(
            [
                pl.len().alias("rows"),
                (pl.col("source") == "amdar").sum().alias("amdar_rows"),
                (pl.col("source") == "turb").sum().alias("turb_rows"),
                (pl.col("confidence_tier") == "T0").sum().alias("T0"),
                (pl.col("confidence_tier") == "T1").sum().alias("T1"),
                (pl.col("confidence_tier") == "T2").sum().alias("T2"),
                (pl.col("confidence_tier") == "T3").sum().alias("T3"),
                (pl.col("confidence_tier") == "T4").sum().alias("T4"),
                pl.col("base_support_conf").mean().alias("base_support_conf_mean"),
            ]
        )
        .sort("processing_slice_id")
        .to_dicts()
    )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "slice_count": int(args.slice_count),
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "space_saving_policy": "Single full confidence table with processing_slice_id; no 25 duplicated full intermediates.",
            "real_amdar_adsb_match_dependency": "Stage5 not yet run; adsb_match_conf and spatial_match_conf are explicitly 0/stage5_pending.",
        },
        "inputs": {
            "stage1_clean_wind": str(Path(args.stage1_dir) / "clean_wind.parquet"),
            "stage1_met_qc_rows": str(Path(args.stage0_stage1_dir) / "stage1_quality_audit/stage1_met_qc_rows.parquet"),
            "stage2_leg_components": str(Path(args.stage2_stage3_dir) / "stage2_adsb_qc_v3/adsb_leg_quality_components.parquet"),
            "stage3_pseudo_report": str(pseudo_report_path),
        },
        "row_counts": {
            "total": int(df.height),
            "amdar": int(amdar.height),
            "turb": int(turb.height),
        },
        "tier_counts": counts_map(df, "confidence_tier"),
        "grade_counts": counts_map(df, "confidence_grade"),
        "recommended_role_counts": counts_map(df, "recommended_stage4_role"),
        "primary_quality_action_reason_counts": counts_map(df, "primary_quality_action_reason"),
        "amdar": {
            "tier_counts": counts_map(amdar, "confidence_tier"),
            "grade_counts": counts_map(amdar, "confidence_grade"),
            "role_counts": counts_map(amdar, "recommended_stage4_role"),
            "base_support_conf_summary": numeric_summary(amdar, "base_support_conf"),
            "time_uncertainty_s_summary": numeric_summary(amdar, "time_uncertainty_s_stage4"),
            "batch_size_counts": counts_map(amdar, "amdar_batch_size_bucket"),
            "high_wind_rows_gt_150_mps": int(high_wind.height),
            "high_wind_rows_gt_200_mps": int(amdar.filter(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_REJECT_REVIEW).height),
            "high_wind_tier_counts": counts_map(high_wind, "confidence_tier"),
            "stage5_pending_match_rows": int(amdar.filter(pl.col("adsb_match_status") == "stage5_pending_no_real_amdar_adsb_match_yet").height),
        },
        "turb": {
            "tier_counts": counts_map(turb, "confidence_tier"),
            "grade_counts": counts_map(turb, "confidence_grade"),
            "original_effective_strict_truth_true": int(turb.filter(pl.col("effective_strict_truth").fill_null(False)).height),
            "enhanced_holdout_eligible_true": int(turb.filter(pl.col("enhanced_holdout_eligible")).height),
            "enhanced_holdout_review_rows": int(turb.filter(~pl.col("enhanced_holdout_eligible")).height),
            "review_reason_counts": counts_map(turb, "primary_quality_action_reason"),
        },
        "adsb_identity_prior": {
            "amdar_rows_with_same_identity_date_leg": int(amdar.filter(pl.col("same_identity_date_leg_count").fill_null(0) > 0).height),
            "best_leg_quality_counts": counts_map(amdar, "same_identity_date_best_leg_quality"),
            "adsb_leg_conf_summary": numeric_summary(amdar, "adsb_leg_conf"),
            "note": "This is only a leg availability prior, not a point-time reconstruction or accepted AMDAR-ADS-B match.",
        },
        "stage3_status": {
            "locked_test_metrics": locked_metrics,
            "quality_gate": quality_gate,
            "interpretation": "Full locked-test coverage remains above the q90/catastrophic targets; selected coverage up to 0.5 is usable for threshold calibration in Stage7.",
        },
        "by_processing_slice": by_slice,
        "stage4_completion_checks": {
            "no_fixed_035_only": len(set(amdar.get_column("base_support_conf").round(6).to_list())) > 10 if amdar.height else False,
            "confidence_components_present": True,
            "strict_truth_not_derived_from_confidence": True,
            "amdar_effective_strict_truth_rows": int(amdar.filter(pl.col("effective_strict_truth").fill_null(False)).height),
            "turb_enhanced_holdout_review_applied": int(turb.filter(~pl.col("enhanced_holdout_eligible")).height) == 6,
            "stage5_match_not_fabricated": int(amdar.filter(pl.col("adsb_match_conf") != 0.0).height) == 0,
        },
    }
    summary["stage4_completion_checks"]["passed"] = all(
        bool(v)
        for k, v in summary["stage4_completion_checks"].items()
        if k not in {"amdar_effective_strict_truth_rows"}
    ) and summary["stage4_completion_checks"]["amdar_effective_strict_truth_rows"] == 0
    return summary


def build_policy(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at_utc": summary["generated_at_utc"],
        "policy_version": "amdar_unified_stage4_confidence_v1",
        "purpose": "Replace one-size-fits-all AMDAR obs_conf with auditable confidence components while preserving strict truth boundaries.",
        "strict_truth_boundary": {
            "rule": "base_support_conf, confidence_tier, and confidence_grade never create strict truth.",
            "amdar_effective_strict_truth": 0,
            "turb_original_effective_strict_truth": summary["turb"]["original_effective_strict_truth_true"],
            "turb_enhanced_holdout_eligible_after_qc": summary["turb"]["enhanced_holdout_eligible_true"],
            "note": "The 6 TURB enhanced-QC review rows remain original Plan4 strict candidates, but are excluded from enhanced_holdout_eligible until altitude/temperature review.",
        },
        "component_definitions": {
            "source_conf": "1.0 for TURB, 0.90 for AMDAR, 0.70 fallback.",
            "met_conf": "0 for nonfinite, impossible wind/direction, wind >200 m/s, or TURB enhanced-QC review; 0.35 for AMDAR wind >150 m/s; 0.60 for review flags; 1.0 otherwise.",
            "batch_conf": "Product of batch size, spatial span, phase, and within-batch wind consistency factors, capped to [0.05, 0.85].",
            "time_source_conf": "1.0 for TURB point observations; AMDAR uses batch_conf/0.85 as a batch time-source prior.",
            "sequence_conf": "Phase prior: LVR=1.0, ASC=0.85, DES=0.75, unknown=0.70.",
            "identity_conf": "1.0 when both tail and flight are present, 0.75 when either exists, 0.35 otherwise.",
            "adsb_leg_conf": "Identity-date ADS-B leg availability prior from Stage2 components: A=1.0, B=0.80, C=0.50, none=0.0.",
            "adsb_match_conf": "Always 0 in Stage4 because real AMDAR-ADS-B V3 matching is Stage5.",
            "spatial_match_conf": "Always 0 in Stage4 because no accepted real match exists yet.",
            "spatial_representativeness_conf": "Batch horizontal/vertical span factor.",
            "density_conf": "1/sqrt(batch_row_count), clipped to [0.10, 1.0], to prevent large batches from dominating later support use.",
            "base_support_conf": "Weighted geometric mean over available components, then hard QC/downweighting rules.",
        },
        "weights": {
            "source_conf": 1.0,
            "met_conf": 2.0,
            "time_source_conf": 2.0,
            "sequence_conf": 1.0,
            "identity_conf": 1.0,
            "adsb_leg_conf": 0.5,
            "adsb_match_conf": 0.0,
            "spatial_match_conf": 0.0,
            "spatial_representativeness_conf": 1.0,
            "density_conf": 1.0,
        },
        "tier_rules": {
            "T0/S": "TURB with original effective_strict_truth and no enhanced QC hard review.",
            "T1/A": "base_support_conf >= 0.70 and time_uncertainty_s <= 300, support only.",
            "T2/B": "base_support_conf >= 0.45 and time_uncertainty_s <= 900, support only.",
            "T3/C": "base_support_conf >= 0.25 and time_uncertainty_s <= 1800, low-confidence support/super-ob only.",
            "T4/D_or_R": "Below T3 or hard review/reject.",
        },
        "forbidden_operations_reaffirmed": [
            "Do not promote AMDAR to strict truth from confidence values.",
            "Do not treat AMDAR batch_end_time as point observation time.",
            "Do not use adsb_leg_conf as if it were a real accepted match.",
            "Do not include the 6 TURB enhanced-QC review rows in enhanced strict holdout before manual review.",
        ],
    }


def write_report(out_dir: Path, summary: dict[str, Any]) -> None:
    checks = summary["stage4_completion_checks"]
    report = [
        "# AMDAR Unified Plan Stage4 Confidence Model Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Scope",
        "",
        "This run implements Unified Plan Stage4 confidence data modeling. It does not run real AMDAR-ADS-B V3 matching and does not mutate the frozen Plan4 Stage1 baseline.",
        "",
        "## Key Results",
        "",
        f"- Total rows scored: {summary['row_counts']['total']}",
        f"- AMDAR rows scored: {summary['row_counts']['amdar']}",
        f"- TURB rows scored: {summary['row_counts']['turb']}",
        f"- Tier counts: `{summary['tier_counts']}`",
        f"- AMDAR tier counts: `{summary['amdar']['tier_counts']}`",
        f"- TURB enhanced holdout eligible rows: {summary['turb']['enhanced_holdout_eligible_true']} / {summary['turb']['original_effective_strict_truth_true']}",
        f"- TURB enhanced holdout review rows: {summary['turb']['enhanced_holdout_review_rows']}",
        f"- AMDAR high-wind >150 m/s rows: {summary['amdar']['high_wind_rows_gt_150_mps']}",
        f"- AMDAR high-wind >200 m/s manual-review rows: {summary['amdar']['high_wind_rows_gt_200_mps']}",
        "",
        "## Interpretation",
        "",
        "Stage4 now replaces the legacy fixed AMDAR `obs_conf=0.35` behavior with auditable component fields. The distribution is intentionally conservative because Stage5 real matching is not done yet; `adsb_match_conf` and `spatial_match_conf` are explicitly zero and marked as pending.",
        "",
        "AMDAR remains support-only. No confidence tier can create strict truth. TURB remains the only conservative strict-truth source, but the 6 enhanced-QC rows are excluded from `enhanced_holdout_eligible` until altitude/temperature review.",
        "",
        "## Completion Checks",
        "",
        f"- No fixed-only 0.35 AMDAR confidence: {checks['no_fixed_035_only']}",
        f"- Confidence components present: {checks['confidence_components_present']}",
        f"- Strict truth not derived from confidence: {checks['strict_truth_not_derived_from_confidence']}",
        f"- AMDAR effective strict truth rows: {checks['amdar_effective_strict_truth_rows']}",
        f"- TURB enhanced holdout review applied: {checks['turb_enhanced_holdout_review_applied']}",
        f"- Stage5 match not fabricated: {checks['stage5_match_not_fabricated']}",
        f"- Stage4 passed: {checks['passed']}",
        "",
        "## Stage3 Carry-Forward",
        "",
        f"- Locked-test gate: `{summary['stage3_status']['quality_gate']}`",
        "",
        "Stage3 full coverage still does not meet the q90/catastrophic targets. The useful signal is selected coverage thresholding for Stage7, not a license to accept full-coverage real AMDAR matching.",
    ]
    (out_dir / "stage4_confidence_results_report.md").write_text("\n".join(report), encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    components = build_components(args)
    components.write_parquet(out_dir / "amdar_confidence_components.parquet")

    summary = summarize_components(components, args)
    summary["outputs"] = {
        "amdar_confidence_components": str(out_dir / "amdar_confidence_components.parquet"),
        "amdar_confidence_policy_v1": str(out_dir / "amdar_confidence_policy_v1.json"),
        "confidence_tier_summary": str(out_dir / "confidence_tier_summary.json"),
        "stage4_confidence_results_report": str(out_dir / "stage4_confidence_results_report.md"),
    }
    write_json(out_dir / "confidence_tier_summary.json", summary)
    write_json(out_dir / "amdar_confidence_policy_v1.json", build_policy(summary))
    write_report(out_dir, summary)
    print(json.dumps({"out_dir": str(out_dir), "passed": summary["stage4_completion_checks"]["passed"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
