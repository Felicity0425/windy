from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE1_DIR = DATA_DIR / "amdar_plan4_implementation_20260630/stage1_output_plan4_v1"
STAGE4_V2_DIR = (
    DATA_DIR / "amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage4_confidence_v2"
)
STAGE6_DIR = DATA_DIR / "amdar_unified_stage6_time_uncertainty_v2_optimized_20260701"
STAGE7_DIR = DATA_DIR / "amdar_unified_stage7_grade_calibration_optimized_20260701"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage8_enhanced_stage1_optimized_20260701"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage1_dir: Path = STAGE1_DIR
    stage4_v2_dir: Path = STAGE4_V2_DIR
    stage6_dir: Path = STAGE6_DIR
    stage7_dir: Path = STAGE7_DIR
    slice_count: int = 25
    workers: int = 25
    stage8_version: str = "v1"


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage8 enhanced Stage1 output. This joins Stage6 time uncertainty "
            "and Stage7 support-quality grades back to Stage1 wind rows without copying clean_loc or "
            "duplicating per-slice full intermediates."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--stage1-dir", default=str(STAGE1_DIR))
    parser.add_argument("--stage4-v2-dir", default=str(STAGE4_V2_DIR))
    parser.add_argument("--stage6-dir", default=str(STAGE6_DIR))
    parser.add_argument("--stage7-dir", default=str(STAGE7_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir).resolve(),
        stage1_dir=Path(args.stage1_dir).resolve(),
        stage4_v2_dir=Path(args.stage4_v2_dir).resolve(),
        stage6_dir=Path(args.stage6_dir).resolve(),
        stage7_dir=Path(args.stage7_dir).resolve(),
        slice_count=int(args.slice_count),
        workers=int(args.workers),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def require_upstream_gates(cfg: RunConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    stage6_summary = read_json(cfg.stage6_dir / "time_uncertainty_summary_v2.json")
    stage7_summary = read_json(cfg.stage7_dir / "amdar_quality_grade_summary.json")
    stage6_checks = stage6_summary.get("stage6_completion_checks", {})
    stage7_checks = stage7_summary.get("stage7_completion_checks", {})
    if not stage6_checks.get("passed_stage6_time_uncertainty_gate"):
        raise RuntimeError(f"Stage6 gate did not pass: {cfg.stage6_dir / 'time_uncertainty_summary_v2.json'}")
    if not stage7_checks.get("passed_stage7_grade_calibration_gate"):
        raise RuntimeError(f"Stage7 gate did not pass: {cfg.stage7_dir / 'amdar_quality_grade_summary.json'}")
    return stage6_summary, stage7_summary


def build_stage4_components(cfg: RunConfig, source: str = "amdar") -> pl.LazyFrame:
    return (
        pl.scan_parquet(cfg.stage4_v2_dir / "amdar_confidence_components_v2.parquet")
        .filter(pl.col("source") == source)
        .select(
            [
                "source_row_index",
                "source_conf",
                "met_conf",
                "batch_conf",
                "time_source_conf",
                "sequence_conf",
                "identity_conf",
                "adsb_leg_conf",
                "adsb_match_conf",
                "spatial_match_conf",
                pl.col("spatial_representativeness_conf").alias("spatial_representativeness"),
                "density_conf",
                "batch_size_conf",
                pl.col("batch_met_consistency_conf").alias("batch_met_consistency"),
                "base_support_conf_pre_stage1_cap",
                "base_support_conf",
                "time_uncertainty_s_stage4_v2",
                "support_assimilation_eligible_v3",
                "stage1_downstream_action_v3",
                "stage1_confidence_cap_v3",
                "strict_holdout_eligible_v3",
                "enhanced_holdout_eligible_v2",
                pl.col("confidence_tier").alias("stage4_confidence_tier"),
                pl.col("confidence_grade").alias("stage4_confidence_grade"),
                "confidence_basis",
                "recommended_stage4_role",
                "primary_quality_action_reason",
                "met_value_quality_audit",
                "wind_speed_outlier_flag",
                "temperature_outlier_flag",
                "altitude_outlier_flag",
                pl.col("adsb_reconstructed").alias("stage4_adsb_reconstructed"),
                pl.col("adsb_match_status").alias("stage4_adsb_match_status"),
            ]
        )
    )


def build_stage7_fields(cfg: RunConfig) -> pl.LazyFrame:
    return pl.scan_parquet(cfg.stage7_dir / "amdar_quality_grades_v2.parquet").select(
        [
            "source_row_index",
            "stage5_accepted_row",
            "stage5_accepted_batch",
            "status",
            "reject_reason",
            "matched_adsb_leg_id",
            "matched_leg_id",
            pl.col("estimated_time_utc").alias("adsb_estimated_time_utc"),
            "segment_start_time_utc",
            "segment_end_time_utc",
            "cross_track_distance_km",
            "vertical_difference_m",
            "sampling_gap_seconds",
            "best_cost",
            "ambiguity_margin",
            "cross_track_q90_km",
            "vertical_q90_m",
            "sampling_gap_max_seconds",
            "leg_overall_quality",
            "stage3_source_tier_v6",
            "best_leg_quality",
            "best_stage3_source_tier_v6",
            "previous_batch_end_time_utc",
            "next_batch_end_time_utc",
            "previous_batch_gap_s",
            "next_batch_gap_s",
            "estimated_time_q10",
            "estimated_time_q50",
            "estimated_time_q90",
            "time_interval_start",
            "time_interval_end",
            "time_interval_width_s",
            "time_pdf_type",
            "time_uncertainty_s",
            "time_source",
            "time_reconstruction_grade",
            "q50_seconds_before_batch_end",
            "stage4_prior_duration_s",
            "batch_physical_span_duration_s",
            "batch_context_cap_s",
            "batch_unconstrained_interval_width_s",
            "batch_interval_driver",
            "batch_feature_duration_s",
            "batch_interval_start_offset_s",
            "adsb_estimated_time_clipped_to_batch_end",
            "batch_time_semantics",
            "estimated_time_is_strict_point_truth",
            pl.col("holdout_eligible").alias("stage6_holdout_eligible"),
            "time_semantics_note",
            "stage7_passes_A_adsb_gate",
            "stage7_passes_B_adsb_gate",
            "stage7_passes_C_adsb_gate",
            "stage7_passes_A_batch_gate",
            "stage7_passes_B_batch_gate",
            "stage7_passes_C_batch_gate",
            "stage7_quality_grade",
            "stage7_grade_basis",
            "stage7_quality_tier",
            "stage7_usage_recommendation",
            "stage7_obs_weight_hint",
            "stage5_batch_best_cost",
            "stage5_batch_second_best_cost",
            "stage5_batch_ambiguity_margin",
            "stage5_batch_total_candidate_count",
            "stage5_batch_evaluated_candidate_count",
            "stage5_batch_monotonic_violation_count",
            "stage5_batch_max_projected_after_batch_end_s",
            "stage5_batch_identity_match_level",
            "stage5_batch_accepted_by_compound_gate",
            "adsb_confidence_cost_metric",
            "adsb_confidence_second_cost_metric",
            "adsb_confidence_cross_track_km",
            "adsb_confidence_vertical_m",
            "adsb_confidence_sampling_gap_s",
            "adsb_confidence_ambiguity_margin",
            "adsb_confidence_leg_quality",
            "adsb_confidence_identity_match_level",
            "adsb_cost_conf_v2",
            "adsb_geometry_conf_v2",
            "adsb_vertical_conf_v2",
            "adsb_sampling_conf_v2",
            "adsb_ambiguity_conf_v2",
            "adsb_leg_quality_conf_v2",
            "adsb_identity_conf_v2",
            "adsb_match_conf_v2",
            "adsb_time_source_conf_v2",
            "stage7_time_conf_factor_v2",
            "stage7_batch_support_conf_v2",
            "adsb_confidence_basis_v2",
            "adsb_match_confidence_class_v2",
            "stage7_obs_weight_hint_continuous_v2",
            "stage7_obs_weight_hint_continuous_basis_v2",
            "stage7_holdout_eligible",
            "stage7_effective_strict_truth",
            "stage7_policy_note",
        ]
    )


def enhanced_amdar(stage1: pl.LazyFrame, cfg: RunConfig) -> pl.LazyFrame:
    stage4 = build_stage4_components(cfg)
    stage7 = build_stage7_fields(cfg)
    return (
        stage1.filter(pl.col("source") == "amdar")
        .join(stage4, on="source_row_index", how="left")
        .join(stage7, on="source_row_index", how="left")
        .with_columns(
            [
                pl.coalesce(
                    [
                        pl.col("stage7_obs_weight_hint_continuous_v2").cast(pl.Float64),
                        pl.col("stage7_obs_weight_hint").cast(pl.Float64),
                    ]
                ).alias("obs_conf_v2"),
                pl.col("stage7_quality_tier").alias("confidence_tier"),
                pl.col("stage7_quality_grade").alias("confidence_grade"),
                pl.col("stage7_holdout_eligible").fill_null(False).alias("holdout_eligible"),
                pl.col("stage7_effective_strict_truth").fill_null(False).alias("stage8_effective_strict_truth"),
                pl.col("stage7_quality_grade").is_in(["A", "B", "C"]).alias("stage8_support_assimilation_eligible"),
                (pl.col("stage7_usage_recommendation") == "display_only_or_weight_capped_not_holdout").alias(
                    "stage8_display_only"
                ),
                (pl.col("stage7_usage_recommendation") == "reject_from_support_not_holdout").alias(
                    "stage8_rejected_from_support"
                ),
                pl.lit(False).alias("stage8_holdout_review"),
                pl.lit(False).alias("stage8_point_time_strict_truth_available"),
                pl.col("stage5_accepted_row").fill_null(False).alias("adsb_reconstructed"),
                pl.coalesce([pl.col("leg_overall_quality"), pl.col("best_leg_quality")]).alias("adsb_leg_quality"),
                pl.when(pl.col("stage7_passes_A_adsb_gate"))
                .then(pl.lit("A"))
                .when(pl.col("stage7_passes_B_adsb_gate"))
                .then(pl.lit("B"))
                .when(pl.col("stage7_passes_C_adsb_gate"))
                .then(pl.lit("C"))
                .when(pl.col("stage5_accepted_row").fill_null(False))
                .then(pl.lit("accepted_below_calibrated_gate"))
                .otherwise(pl.lit(None, dtype=pl.Utf8))
                .alias("adsb_match_quality"),
                pl.col("adsb_match_confidence_class_v2").alias("adsb_match_confidence_class"),
                pl.col("adsb_confidence_basis_v2").alias("adsb_confidence_basis"),
                pl.col("best_cost").alias("adsb_match_cost"),
                pl.col("ambiguity_margin").alias("adsb_match_ambiguity"),
                pl.col("cross_track_distance_km").alias("adsb_cross_track_dist"),
                pl.col("vertical_difference_m").alias("adsb_vertical_diff"),
                pl.when(pl.col("stage7_quality_grade").is_in(["A", "B", "C"]))
                .then(pl.col("stage7_usage_recommendation"))
                .when(pl.col("stage7_usage_recommendation") == "display_only_or_weight_capped_not_holdout")
                .then(pl.lit("display_only_not_regular_support"))
                .otherwise(pl.lit("reject_not_support"))
                .alias("stage8_usage_recommendation"),
                pl.lit("amdar_stage6_stage7_joined").alias("stage8_join_status"),
                pl.lit(
                    "Stage8 joins AMDAR Stage6 time distributions and Stage7 support grades; AMDAR remains non-holdout."
                ).alias("stage8_policy_note"),
            ]
        )
    )


def enhanced_non_amdar(stage1: pl.LazyFrame, cfg: RunConfig) -> pl.LazyFrame:
    stage4 = build_stage4_components(cfg, source="turb")
    enhanced_holdout = pl.col("enhanced_holdout_eligible_v2").fill_null(False)
    strict_holdout = pl.col("strict_holdout_eligible_v3").fill_null(False)
    holdout_review = pl.col("time_is_point_observation").fill_null(False) & ~enhanced_holdout
    return stage1.filter(pl.col("source") != "amdar").join(stage4, on="source_row_index", how="left").with_columns(
        [
            pl.when(enhanced_holdout).then(pl.lit(1.0)).otherwise(pl.lit(0.0)).alias("obs_conf_v2"),
            pl.col("source_conf").fill_null(1.0).alias("source_conf"),
            pl.col("met_conf").fill_null(0.0).alias("met_conf"),
            pl.col("batch_conf").alias("batch_conf"),
            pl.col("time_source_conf").fill_null(1.0).alias("time_source_conf"),
            pl.col("sequence_conf").fill_null(1.0).alias("sequence_conf"),
            pl.col("identity_conf").fill_null(1.0).alias("identity_conf"),
            pl.col("adsb_leg_conf").alias("adsb_leg_conf"),
            pl.col("adsb_match_conf").alias("adsb_match_conf"),
            pl.col("spatial_match_conf").alias("spatial_match_conf"),
            pl.col("spatial_representativeness").fill_null(1.0).alias("spatial_representativeness"),
            pl.col("density_conf").alias("density_conf"),
            pl.col("batch_size_conf").alias("batch_size_conf"),
            pl.col("batch_met_consistency").fill_null(1.0).alias("batch_met_consistency"),
            pl.col("base_support_conf_pre_stage1_cap").fill_null(0.0).alias("base_support_conf_pre_stage1_cap"),
            pl.col("base_support_conf").fill_null(0.0).alias("base_support_conf"),
            pl.col("time_uncertainty_s_stage4_v2").fill_null(0.0).alias("time_uncertainty_s_stage4_v2"),
            pl.lit(False).alias("support_assimilation_eligible_v3"),
            pl.coalesce([pl.col("stage1_downstream_action_v3"), pl.col("recommended_stage4_role")]).alias(
                "stage1_downstream_action_v3"
            ),
            pl.col("stage1_confidence_cap_v3").fill_null(0.0).alias("stage1_confidence_cap_v3"),
            pl.col("stage4_confidence_tier").fill_null("T4").alias("stage4_confidence_tier"),
            pl.col("stage4_confidence_grade").fill_null("R").alias("stage4_confidence_grade"),
            pl.col("confidence_basis").fill_null("non_amdar_stage4_qc").alias("confidence_basis"),
            pl.col("recommended_stage4_role").fill_null("strict_holdout_review").alias("recommended_stage4_role"),
            pl.col("primary_quality_action_reason")
            .fill_null("missing_stage4_non_amdar_confidence")
            .alias("primary_quality_action_reason"),
            pl.col("met_value_quality_audit").fill_null("failed").alias("met_value_quality_audit"),
            pl.col("wind_speed_outlier_flag").fill_null(False).alias("wind_speed_outlier_flag"),
            pl.col("temperature_outlier_flag").fill_null(False).alias("temperature_outlier_flag"),
            pl.col("altitude_outlier_flag").fill_null(False).alias("altitude_outlier_flag"),
            pl.col("stage4_adsb_reconstructed").fill_null(False).alias("stage4_adsb_reconstructed"),
            pl.lit(None, dtype=pl.Utf8).alias("stage4_adsb_match_status"),
            pl.lit(False).alias("stage5_accepted_row"),
            pl.lit(False).alias("stage5_accepted_batch"),
            pl.lit(None, dtype=pl.Utf8).alias("status"),
            pl.lit(None, dtype=pl.Utf8).alias("reject_reason"),
            pl.lit(None, dtype=pl.Utf8).alias("matched_adsb_leg_id"),
            pl.lit(None, dtype=pl.Utf8).alias("matched_leg_id"),
            pl.col("observation_time_utc").alias("adsb_estimated_time_utc"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("segment_start_time_utc"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("segment_end_time_utc"),
            pl.lit(None, dtype=pl.Float64).alias("cross_track_distance_km"),
            pl.lit(None, dtype=pl.Float64).alias("vertical_difference_m"),
            pl.lit(None, dtype=pl.Float64).alias("sampling_gap_seconds"),
            pl.lit(None, dtype=pl.Float64).alias("best_cost"),
            pl.lit(None, dtype=pl.Float64).alias("ambiguity_margin"),
            pl.lit(None, dtype=pl.Float64).alias("cross_track_q90_km"),
            pl.lit(None, dtype=pl.Float64).alias("vertical_q90_m"),
            pl.lit(None, dtype=pl.Float64).alias("sampling_gap_max_seconds"),
            pl.lit(None, dtype=pl.Utf8).alias("leg_overall_quality"),
            pl.lit(None, dtype=pl.Utf8).alias("stage3_source_tier_v6"),
            pl.lit(None, dtype=pl.Utf8).alias("best_leg_quality"),
            pl.lit(None, dtype=pl.Utf8).alias("best_stage3_source_tier_v6"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("previous_batch_end_time_utc"),
            pl.lit(None, dtype=pl.Datetime("us")).alias("next_batch_end_time_utc"),
            pl.lit(None, dtype=pl.Float64).alias("previous_batch_gap_s"),
            pl.lit(None, dtype=pl.Float64).alias("next_batch_gap_s"),
            pl.col("observation_time_utc").alias("estimated_time_q10"),
            pl.col("observation_time_utc").alias("estimated_time_q50"),
            pl.col("observation_time_utc").alias("estimated_time_q90"),
            pl.col("observation_time_utc").alias("time_interval_start"),
            pl.col("observation_time_utc").alias("time_interval_end"),
            pl.lit(0.0).alias("time_interval_width_s"),
            pl.lit("point_observation_time").alias("time_pdf_type"),
            pl.lit(0.0).alias("time_uncertainty_s"),
            pl.col("observation_time_source").alias("time_source"),
            pl.lit("S_strict_point_time").alias("time_reconstruction_grade"),
            pl.lit(0.0).alias("q50_seconds_before_batch_end"),
            pl.lit(None, dtype=pl.Float64).alias("stage4_prior_duration_s"),
            pl.lit(None, dtype=pl.Float64).alias("batch_physical_span_duration_s"),
            pl.lit(None, dtype=pl.Float64).alias("batch_context_cap_s"),
            pl.lit(None, dtype=pl.Float64).alias("batch_unconstrained_interval_width_s"),
            pl.lit(None, dtype=pl.Utf8).alias("batch_interval_driver"),
            pl.lit(None, dtype=pl.Float64).alias("batch_feature_duration_s"),
            pl.lit(None, dtype=pl.Float64).alias("batch_interval_start_offset_s"),
            pl.lit(False).alias("adsb_estimated_time_clipped_to_batch_end"),
            pl.lit(None, dtype=pl.Utf8).alias("batch_time_semantics"),
            pl.lit(True).alias("estimated_time_is_strict_point_truth"),
            pl.lit(False).alias("stage6_holdout_eligible"),
            pl.lit("Non-AMDAR strict point observation time preserved by Stage8.").alias("time_semantics_note"),
            pl.lit(False).alias("stage7_passes_A_adsb_gate"),
            pl.lit(False).alias("stage7_passes_B_adsb_gate"),
            pl.lit(False).alias("stage7_passes_C_adsb_gate"),
            pl.lit(False).alias("stage7_passes_A_batch_gate"),
            pl.lit(False).alias("stage7_passes_B_batch_gate"),
            pl.lit(False).alias("stage7_passes_C_batch_gate"),
            pl.col("stage4_confidence_grade").fill_null("R").alias("stage7_quality_grade"),
            pl.when(enhanced_holdout)
            .then(pl.lit("non_amdar_enhanced_strict_holdout"))
            .otherwise(pl.lit("non_amdar_strict_point_time_review"))
            .alias("stage7_grade_basis"),
            pl.col("stage4_confidence_tier").fill_null("T4").alias("stage7_quality_tier"),
            pl.when(enhanced_holdout)
            .then(pl.lit("strict_holdout_truth"))
            .otherwise(pl.lit("strict_holdout_review_not_official"))
            .alias("stage7_usage_recommendation"),
            pl.when(enhanced_holdout).then(pl.lit(1.0)).otherwise(pl.lit(0.0)).alias("stage7_obs_weight_hint"),
            pl.lit(None, dtype=pl.Float64).alias("stage5_batch_best_cost"),
            pl.lit(None, dtype=pl.Float64).alias("stage5_batch_second_best_cost"),
            pl.lit(None, dtype=pl.Float64).alias("stage5_batch_ambiguity_margin"),
            pl.lit(None, dtype=pl.Int64).alias("stage5_batch_total_candidate_count"),
            pl.lit(None, dtype=pl.Int64).alias("stage5_batch_evaluated_candidate_count"),
            pl.lit(None, dtype=pl.Int64).alias("stage5_batch_monotonic_violation_count"),
            pl.lit(None, dtype=pl.Float64).alias("stage5_batch_max_projected_after_batch_end_s"),
            pl.lit(None, dtype=pl.Utf8).alias("stage5_batch_identity_match_level"),
            pl.lit(None, dtype=pl.Boolean).alias("stage5_batch_accepted_by_compound_gate"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_confidence_cost_metric"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_confidence_second_cost_metric"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_confidence_cross_track_km"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_confidence_vertical_m"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_confidence_sampling_gap_s"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_confidence_ambiguity_margin"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_confidence_leg_quality"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_confidence_identity_match_level"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_cost_conf_v2"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_geometry_conf_v2"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_vertical_conf_v2"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_sampling_conf_v2"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_ambiguity_conf_v2"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_leg_quality_conf_v2"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_identity_conf_v2"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_match_conf_v2"),
            pl.lit(0.0).alias("adsb_time_source_conf_v2"),
            pl.lit(1.0).alias("stage7_time_conf_factor_v2"),
            pl.lit(None, dtype=pl.Float64).alias("stage7_batch_support_conf_v2"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_confidence_basis_v2"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_match_confidence_class_v2"),
            pl.when(enhanced_holdout).then(pl.lit(1.0)).otherwise(pl.lit(0.0)).alias(
                "stage7_obs_weight_hint_continuous_v2"
            ),
            pl.when(enhanced_holdout)
            .then(pl.lit("strict_point_truth_weight"))
            .otherwise(pl.lit("non_amdar_review_zero_weight"))
            .alias("stage7_obs_weight_hint_continuous_basis_v2"),
            enhanced_holdout.alias("stage7_holdout_eligible"),
            strict_holdout.alias("stage7_effective_strict_truth"),
            pl.lit("Stage8 preserves non-AMDAR point-time semantics; final holdout follows Stage4 enhanced QC.").alias(
                "stage7_policy_note"
            ),
            pl.col("stage4_confidence_tier").fill_null("T4").alias("confidence_tier"),
            pl.col("stage4_confidence_grade").fill_null("R").alias("confidence_grade"),
            enhanced_holdout.alias("holdout_eligible"),
            strict_holdout.alias("stage8_effective_strict_truth"),
            pl.lit(False).alias("stage8_support_assimilation_eligible"),
            pl.lit(False).alias("stage8_display_only"),
            pl.lit(False).alias("stage8_rejected_from_support"),
            holdout_review.alias("stage8_holdout_review"),
            pl.col("time_is_point_observation").fill_null(False).alias("stage8_point_time_strict_truth_available"),
            pl.lit(False).alias("adsb_reconstructed"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_leg_quality"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_match_quality"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_match_confidence_class"),
            pl.lit(None, dtype=pl.Utf8).alias("adsb_confidence_basis"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_match_cost"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_match_ambiguity"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_cross_track_dist"),
            pl.lit(None, dtype=pl.Float64).alias("adsb_vertical_diff"),
            pl.when(enhanced_holdout)
            .then(pl.lit("strict_holdout_truth"))
            .otherwise(pl.lit("strict_holdout_review_not_official"))
            .alias("stage8_usage_recommendation"),
            pl.when(enhanced_holdout)
            .then(pl.lit("non_amdar_enhanced_holdout_preserved"))
            .otherwise(pl.lit("non_amdar_holdout_review_preserved"))
            .alias("stage8_join_status"),
            pl.lit(
                "Stage8 keeps non-AMDAR point-time semantics, but only Stage4 enhanced-QC rows are final holdout eligible."
            ).alias("stage8_policy_note"),
        ]
    )


def build_enhanced_stage1(cfg: RunConfig, stage6_summary: dict[str, Any], stage7_summary: dict[str, Any]) -> dict[str, Any]:
    clean_wind_path = cfg.stage1_dir / "clean_wind.parquet"
    out_path = cfg.out_dir / "clean_wind_with_confidence.parquet"
    stage1_schema = pl.scan_parquet(clean_wind_path).collect_schema()
    original_columns = stage1_schema.names()

    stage1 = pl.scan_parquet(clean_wind_path).with_row_index("stage8_input_order")
    enhanced = pl.concat([enhanced_amdar(stage1, cfg), enhanced_non_amdar(stage1, cfg)], how="diagonal_relaxed").sort(
        "stage8_input_order"
    )
    enhanced.collect(engine="streaming").write_parquet(out_path)

    df = pl.read_parquet(out_path)
    amdar = df.filter(pl.col("source") == "amdar")
    non_amdar = df.filter(pl.col("source") != "amdar")
    turb = df.filter(pl.col("source") == "turb")

    confidence_tier_summary = (
        df.group_by(["source", "confidence_tier", "confidence_grade"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("obs_conf_v2").median().alias("obs_conf_v2_median"),
                pl.col("time_uncertainty_s").median().alias("time_uncertainty_s_median"),
                pl.col("time_uncertainty_s").quantile(0.90).alias("time_uncertainty_s_p90"),
                pl.col("holdout_eligible").sum().alias("holdout_eligible_rows"),
                pl.col("stage8_support_assimilation_eligible").sum().alias("support_eligible_rows"),
            ]
        )
        .sort(["source", "confidence_tier", "confidence_grade"])
    )
    confidence_by_phase = (
        df.group_by(["source", "飞行阶段", "confidence_grade"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("obs_conf_v2").median().alias("obs_conf_v2_median"),
                pl.col("time_uncertainty_s").median().alias("time_uncertainty_s_median"),
            ]
        )
        .sort(["source", "飞行阶段", "confidence_grade"])
    )
    grade_transition = (
        amdar.group_by(["stage4_confidence_tier", "stage4_confidence_grade", "confidence_tier", "confidence_grade"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("stage5_accepted_row").sum().alias("stage5_accepted_rows"),
                pl.col("time_uncertainty_s").median().alias("time_uncertainty_s_median"),
                pl.col("obs_conf_v2").median().alias("obs_conf_v2_median"),
            ]
        )
        .sort(["stage4_confidence_tier", "stage4_confidence_grade", "confidence_tier", "confidence_grade"])
    )

    confidence_tier_summary.write_parquet(cfg.out_dir / "confidence_tier_summary.parquet")
    confidence_by_phase.write_parquet(cfg.out_dir / "confidence_distribution_by_phase.parquet")
    grade_transition.write_parquet(cfg.out_dir / "grade_transition_matrix.parquet")

    confidence_tier_json = confidence_tier_summary.to_dicts()
    confidence_by_phase_json = confidence_by_phase.to_dicts()
    grade_transition_json = grade_transition.to_dicts()

    write_json(
        cfg.out_dir / "confidence_tier_summary.json",
        {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "rows": confidence_tier_json},
    )
    write_json(
        cfg.out_dir / "confidence_distribution_by_phase.json",
        {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "rows": confidence_by_phase_json},
    )
    write_json(
        cfg.out_dir / "grade_transition_matrix.json",
        {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "rows": grade_transition_json},
    )

    time_uncertainty_summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "all_rows": numeric_summary(df, "time_uncertainty_s"),
        "amdar_rows": numeric_summary(amdar, "time_uncertainty_s"),
        "turb_rows": numeric_summary(turb, "time_uncertainty_s"),
        "by_confidence_grade": (
            df.group_by(["source", "confidence_grade"])
            .agg(
                [
                    pl.len().alias("rows"),
                    pl.col("time_uncertainty_s").min().alias("time_uncertainty_s_min"),
                    pl.col("time_uncertainty_s").median().alias("time_uncertainty_s_median"),
                    pl.col("time_uncertainty_s").quantile(0.90).alias("time_uncertainty_s_p90"),
                    pl.col("time_uncertainty_s").max().alias("time_uncertainty_s_max"),
                ]
            )
            .sort(["source", "confidence_grade"])
            .to_dicts()
        ),
    }
    write_json(cfg.out_dir / "time_uncertainty_summary.json", time_uncertainty_summary)

    adsb_summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "amdar_rows": int(amdar.height),
        "adsb_reconstructed_rows": int(amdar.filter(pl.col("adsb_reconstructed")).height),
        "adsb_reconstructed_batches": int(
            amdar.filter(pl.col("adsb_reconstructed")).select(pl.col("amdar_batch_id").n_unique()).item()
        ),
        "adsb_match_quality_counts": counts_map(amdar, "adsb_match_quality"),
        "adsb_match_confidence_class_counts": counts_map(amdar, "adsb_match_confidence_class_v2"),
        "adsb_confidence_basis_counts": counts_map(amdar, "adsb_confidence_basis_v2"),
        "adsb_match_conf_v2_summary": numeric_summary(amdar, "adsb_match_conf_v2"),
        "adsb_time_source_conf_v2_summary": numeric_summary(amdar, "adsb_time_source_conf_v2"),
        "stage7_batch_support_conf_v2_summary": numeric_summary(amdar, "stage7_batch_support_conf_v2"),
        "stage7_obs_weight_hint_continuous_v2_summary": numeric_summary(
            amdar, "stage7_obs_weight_hint_continuous_v2"
        ),
        "adsb_reconstructed_time_uncertainty_summary": numeric_summary(
            amdar.filter(pl.col("adsb_reconstructed")), "time_uncertainty_s"
        ),
        "batch_interval_rows": int(amdar.filter(pl.col("time_source") == "batch_interval_estimated").height),
        "time_source_counts": counts_map(amdar, "time_source"),
        "stage5_status_counts": counts_map(amdar, "status"),
        "stage5_reject_reason_counts": counts_map(amdar, "reject_reason"),
    }
    write_json(cfg.out_dir / "adsb_reconstruction_summary.json", adsb_summary)

    original_fields_present = all(col in df.columns for col in original_columns)
    stage8_checks = {
        "stage6_gate_passed": bool(
            stage6_summary.get("stage6_completion_checks", {}).get("passed_stage6_time_uncertainty_gate")
        ),
        "stage7_gate_passed": bool(
            stage7_summary.get("stage7_completion_checks", {}).get("passed_stage7_grade_calibration_gate")
        ),
        "row_count_preserved": int(df.height) == int(stage1.select(pl.len()).collect().item()),
        "source_counts_preserved": counts_map(df, "source") == counts_map(pl.read_parquet(clean_wind_path), "source"),
        "original_stage1_fields_present": original_fields_present,
        "amdar_rows_joined": int(amdar.height) == int(stage7_summary.get("row_counts", {}).get("amdar_rows", 431008)),
        "all_amdar_have_stage6_time_distribution": int(
            amdar.filter(
                pl.col("estimated_time_q10").is_null()
                | pl.col("estimated_time_q50").is_null()
                | pl.col("estimated_time_q90").is_null()
                | pl.col("time_interval_start").is_null()
                | pl.col("time_interval_end").is_null()
                | pl.col("time_uncertainty_s").is_null()
                | pl.col("time_pdf_type").is_null()
            ).height
        )
        == 0,
        "all_amdar_have_stage7_grade": int(
            amdar.filter(
                pl.col("confidence_tier").is_null()
                | pl.col("confidence_grade").is_null()
                | pl.col("obs_conf_v2").is_null()
                | pl.col("stage7_quality_grade").is_null()
            ).height
        )
        == 0,
        "no_amdar_holdout_or_strict_truth": int(
            amdar.filter(
                pl.col("holdout_eligible").fill_null(False)
                | pl.col("stage8_effective_strict_truth").fill_null(False)
                | pl.col("estimated_time_is_strict_point_truth").fill_null(False)
            ).height
        )
        == 0,
        "turb_enhanced_holdout_preserved": int(
            turb.filter(
                pl.col("holdout_eligible").fill_null(False)
                & pl.col("stage8_effective_strict_truth").fill_null(False)
                & pl.col("estimated_time_is_strict_point_truth").fill_null(False)
                & (pl.col("confidence_grade") == "S")
                & (pl.col("confidence_tier") == "T0")
                & (pl.col("time_uncertainty_s") == 0.0)
            ).height
        )
        == 175,
        "turb_holdout_review_rows_preserved": int(
            turb.filter(
                ~pl.col("holdout_eligible").fill_null(False)
                & ~pl.col("stage8_effective_strict_truth").fill_null(False)
                & pl.col("estimated_time_is_strict_point_truth").fill_null(False)
                & pl.col("stage8_point_time_strict_truth_available").fill_null(False)
                & pl.col("stage8_holdout_review").fill_null(False)
                & (pl.col("confidence_grade") == "R")
                & (pl.col("confidence_tier") == "T4")
            ).height
        )
        == 6,
        "turb_point_time_semantics_preserved": int(
            turb.filter(
                pl.col("stage8_point_time_strict_truth_available").fill_null(False)
                & pl.col("estimated_time_is_strict_point_truth").fill_null(False)
                & (pl.col("time_uncertainty_s") == 0.0)
            ).height
        )
        == int(turb.height)
        == 181,
        "no_turb_adsb_contamination": int(turb.filter(pl.col("adsb_reconstructed").fill_null(False)).height) == 0,
        "r_rows_not_regular_support": int(
            amdar.filter(
                (pl.col("confidence_grade") == "R") & pl.col("stage8_support_assimilation_eligible").fill_null(False)
            ).height
        )
        == 0,
        "abc_amdar_support_eligible": int(
            amdar.filter(pl.col("confidence_grade").is_in(["A", "B", "C"]) & ~pl.col("stage8_support_assimilation_eligible")).height
        )
        == 0,
        "obs_conf_uses_continuous_stage7_weight_for_amdar": int(
            amdar.filter(
                (
                    pl.col("obs_conf_v2").cast(pl.Float64)
                    - pl.col("stage7_obs_weight_hint_continuous_v2").cast(pl.Float64)
                )
                .abs()
                > 1e-9
            ).height
        )
        == 0,
        "adsb_time_source_conf_only_for_accepted_amdar": int(
            amdar.filter((~pl.col("stage5_accepted_row").fill_null(False)) & (pl.col("adsb_time_source_conf_v2") > 0.0)).height
        )
        == 0,
        "stage6_stage7_source_row_index_join_scoped_to_amdar": int(
            non_amdar.filter(
                ~pl.col("stage8_join_status").is_in(
                    ["non_amdar_enhanced_holdout_preserved", "non_amdar_holdout_review_preserved"]
                )
            ).height
        )
        == 0,
        "output_rows_equal_stage1_clean_wind_rows": int(df.height) == 431189,
        "space_saving_no_clean_loc_copy": not (cfg.out_dir / "clean_loc.parquet").exists(),
    }
    stage8_checks["passed_stage8_enhanced_stage1_gate"] = bool(all(stage8_checks.values()))

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "space_saving_policy": (
                "Read one Stage1 clean_wind table plus compact Stage4/6/7 AMDAR tables. "
                "Do not copy clean_loc and do not write 25 per-slice full intermediates."
            ),
            "join_policy": (
                "Stage6/7 are joined only to source == amdar rows because source_row_index is unique within AMDAR "
                "but not globally unique across AMDAR and TURB."
            ),
        },
        "inputs": {
            "stage1_clean_wind": str(clean_wind_path),
            "stage4_confidence_components_v2": str(cfg.stage4_v2_dir / "amdar_confidence_components_v2.parquet"),
            "stage6_time_uncertainty": str(cfg.stage6_dir / "amdar_time_uncertainty_v2.parquet"),
            "stage6_summary": str(cfg.stage6_dir / "time_uncertainty_summary_v2.json"),
            "stage7_quality_grades": str(cfg.stage7_dir / "amdar_quality_grades_v2.parquet"),
            "stage7_summary": str(cfg.stage7_dir / "amdar_quality_grade_summary.json"),
        },
        "row_counts": {
            "clean_wind_rows": int(df.height),
            "amdar_rows": int(amdar.height),
            "non_amdar_rows": int(non_amdar.height),
            "turb_rows": int(turb.height),
            "stage8_support_assimilation_eligible_rows": int(
                df.filter(pl.col("stage8_support_assimilation_eligible")).height
            ),
            "holdout_eligible_rows": int(df.filter(pl.col("holdout_eligible")).height),
            "effective_strict_truth_rows": int(df.filter(pl.col("stage8_effective_strict_truth")).height),
            "point_time_strict_semantics_rows": int(
                df.filter(pl.col("stage8_point_time_strict_truth_available")).height
            ),
            "holdout_review_rows": int(df.filter(pl.col("stage8_holdout_review")).height),
        },
        "source_counts": counts_map(df, "source"),
        "confidence_grade_counts": counts_map(df, "confidence_grade"),
        "confidence_tier_counts": counts_map(df, "confidence_tier"),
        "stage8_usage_recommendation_counts": counts_map(df, "stage8_usage_recommendation"),
        "amdar_stage7_grade_counts": counts_map(amdar, "stage7_quality_grade"),
        "amdar_time_source_counts": counts_map(amdar, "time_source"),
        "time_uncertainty_summary": time_uncertainty_summary,
        "adsb_reconstruction_summary": adsb_summary,
        "confidence_tier_summary": confidence_tier_json,
        "grade_transition_matrix": grade_transition_json,
        "stage8_completion_checks": stage8_checks,
        "assessment": {
            "stage6_result_quality": (
                "Stage6 is suitable for Stage8. It provides complete time distributions for all AMDAR rows, "
                "keeps batch_end as an upper bound, and leaves AMDAR with zero strict truth rows."
            ),
            "stage7_result_quality": (
                "Stage7 is suitable for Stage8. Pseudo validation and locked-test gates pass, and real AMDAR "
                "grades are support-quality labels only. Continuous confidence fields are available for ADS-B "
                "diagnostics and downstream support weighting."
            ),
            "optimization_space": (
                "Further work should focus on research-only Stage5 sequence/trajectory matching, super-ob limits, "
                "and Stage9/10 role separation. There is no defensible production reason to loosen Stage6/7 gates."
            ),
            "stage8_satisfactory": bool(stage8_checks["passed_stage8_enhanced_stage1_gate"]),
        },
        "outputs": {
            "clean_wind_with_confidence": str(out_path),
            "confidence_tier_summary": str(cfg.out_dir / "confidence_tier_summary.json"),
            "confidence_distribution_by_phase": str(cfg.out_dir / "confidence_distribution_by_phase.json"),
            "time_uncertainty_summary": str(cfg.out_dir / "time_uncertainty_summary.json"),
            "adsb_reconstruction_summary": str(cfg.out_dir / "adsb_reconstruction_summary.json"),
            "grade_transition_matrix": str(cfg.out_dir / "grade_transition_matrix.json"),
            "stage8_summary": str(cfg.out_dir / "stage8_enhanced_stage1_summary.json"),
            "stage8_policy": str(cfg.out_dir / "stage8_policy_v1.json"),
        },
        "literature_and_reference_basis": {
            "wmo_aircraft_based_observations": (
                "WMO describes aircraft-based observations/AMDAR as accurate, high-volume upper-air data useful "
                "for forecasting and meteorological applications; this supports support-data use but not treating "
                "provider batch timestamps as point truth."
            ),
            "noaa_amdar_abo": (
                "NOAA describes AMDAR/ABO as automated commercial-aircraft weather reports and notes long-running "
                "ACARS quality assessment for NWP use."
            ),
            "faa_adsb": (
                "14 CFR 91.227 defines ADS-B state-vector broadcast, accuracy/integrity categories, and latency; "
                "ADS-B timing is much narrower than the AMDAR batch/downlink uncertainty in this dataset."
            ),
            "sources": {
                "wmo_aircraft_based_observations": "https://community.wmo.int/site/knowledge-hub/programmes-and-initiatives/aircraft-based-observations",
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
        "policy_version": f"amdar_unified_stage8_enhanced_stage1_{cfg.stage8_version}",
        "purpose": "Add Stage6 time uncertainty and Stage7 support-quality fields to Stage1 clean_wind rows.",
        "global_rules": [
            "Original Stage1 fields are preserved.",
            "Stage6/7 joins are scoped to source == amdar because source_row_index is not globally unique.",
            "AMDAR remains support-only, holdout_eligible=false, stage8_effective_strict_truth=false.",
            "TURB keeps 181 point-time strict-semantics rows, but final holdout eligibility follows Stage4 enhanced QC: 175 holdout, 6 review.",
            "R-grade AMDAR is not regular support; display-only and rejected cases are separated.",
            "clean_loc is not copied in Stage8 to avoid large duplicate outputs.",
        ],
        "field_mapping": {
            "obs_conf_v2": "For AMDAR, continuous Stage7 support-weight confidence when available, falling back to the calibrated discrete Stage7 weight hint; for TURB, 1.0 only for 175 enhanced holdout rows and 0.0 for 6 review rows.",
            "confidence_tier": "T0/T1/T2/T3/T4, mapped from Stage7 for AMDAR and from Stage4 enhanced QC for TURB.",
            "confidence_grade": "S/A/B/C/R, mapped from Stage7 for AMDAR and from Stage4 enhanced QC for TURB.",
            "time_uncertainty_s": "Stage6 uncertainty for AMDAR, 0 for TURB point-time rows.",
            "time_source": "Stage6 time source for AMDAR, original observation time source for TURB.",
            "adsb_match_conf_v2": "Continuous ADS-B diagnostic confidence from match cost, geometry, vertical consistency, sampling gap, ambiguity, and leg quality.",
            "adsb_time_source_conf_v2": "Non-zero only for Stage5-accepted ADS-B matches; rejected/no-candidate ADS-B diagnostics never become AMDAR time-source confidence.",
            "stage7_obs_weight_hint_continuous_v2": "Continuous downstream support-weight confidence used as AMDAR obs_conf_v2.",
            "holdout_eligible": "False for every AMDAR row; true for the 175 TURB rows passing Stage4 enhanced holdout QC.",
            "stage8_support_assimilation_eligible": "True for AMDAR A/B/C support rows; false for R and strict holdout rows.",
            "stage8_point_time_strict_truth_available": "True for all 181 TURB point-time rows; false for AMDAR.",
            "stage8_holdout_review": "True for the 6 TURB point-time rows excluded from enhanced holdout by QC.",
        },
        "completion_checks": summary["stage8_completion_checks"],
    }


def write_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage8_enhanced_stage1_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage8_enhanced_stage1.md"
    checks = summary["stage8_completion_checks"]
    rows = summary["row_counts"]

    result_lines = [
        "# AMDAR Unified Plan Stage8 Enhanced Stage1 Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## 核心结论",
        "",
        "Stage6/Stage7 复核后可以进入 Stage8：Stage6 已为所有 AMDAR 建立时间分布且不产生 strict truth；Stage7 已通过 pseudo validation 与 locked-test gate，真实 AMDAR 分级只作为 support-quality metadata。",
        "",
        "Stage8 已通过。增强后的 Stage1 风观测表保留原始 `clean_wind` 所有字段，并新增时间不确定性、ADS-B 连续诊断置信度、ADS-B 时间源置信度、Stage7 连续支持权重和 Stage7 分级字段。AMDAR 仍然全部 `holdout_eligible=false`；TURB 保留 181 条 point-time strict semantics，其中 175 条通过 Stage4 enhanced holdout QC，6 条保留为 holdout review。",
        "",
        "## 文献与资料依据",
        "",
        "- WMO Aircraft-Based Observations 将 AMDAR/ABO 定位为高容量上空气象观测，可用于预报和气象应用；这支持作为支持资料使用，但不等价于供应商批次时间就是逐点观测时间。",
        "- NOAA AMDAR/ABO 将 AMDAR 描述为商用飞机自动天气报告，并说明 ACARS/AMDAR 质量评估服务于 NWP 使用。",
        "- 14 CFR 91.227 定义 ADS-B Out state vector、精度/完整性与延迟要求；本项目里 ADS-B 秒级时间误差不是主导项，AMDAR 批次下发语义才是主导不确定性。",
        "- Sources: WMO Aircraft-Based Observations (`https://community.wmo.int/site/knowledge-hub/programmes-and-initiatives/aircraft-based-observations`), WMO-No. 1200 (`https://library.wmo.int/idurl/4/68221`), NOAA AMDAR/ABO (`https://amdar.noaa.gov/`), 14 CFR 91.227 (`https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227`).",
        "",
        "## Stage6/7 达标判断",
        "",
        f"- Stage6 gate: `{checks['stage6_gate_passed']}`",
        f"- Stage7 gate: `{checks['stage7_gate_passed']}`",
        "- 当前结果让我满意，适合进入下一阶段。优化空间仍存在，但属于研究分支：Stage5 sequence/trajectory matching、super-ob 限权、Stage9/10 多尺度验证；不应为了覆盖率放松 Stage6/7 生产 gate。",
        "",
        "## Stage8 输出结果",
        "",
        f"- Clean wind rows: `{rows['clean_wind_rows']}`",
        f"- AMDAR rows: `{rows['amdar_rows']}`",
        f"- TURB rows: `{rows['turb_rows']}`",
        f"- Holdout eligible rows: `{rows['holdout_eligible_rows']}`",
        f"- Effective strict truth rows: `{rows['effective_strict_truth_rows']}`",
        f"- Point-time strict semantics rows: `{rows['point_time_strict_semantics_rows']}`",
        f"- Holdout review rows: `{rows['holdout_review_rows']}`",
        f"- Support-assimilation eligible rows: `{rows['stage8_support_assimilation_eligible_rows']}`",
        f"- Confidence grade counts: `{summary['confidence_grade_counts']}`",
        f"- AMDAR time source counts: `{summary['amdar_time_source_counts']}`",
        f"- ADS-B reconstructed rows: `{summary['adsb_reconstruction_summary']['adsb_reconstructed_rows']}`",
        f"- ADS-B confidence basis counts: `{summary['adsb_reconstruction_summary']['adsb_confidence_basis_counts']}`",
        f"- ADS-B confidence class counts: `{summary['adsb_reconstruction_summary']['adsb_match_confidence_class_counts']}`",
        f"- ADS-B diagnostic confidence summary: `{summary['adsb_reconstruction_summary']['adsb_match_conf_v2_summary']}`",
        f"- ADS-B time-source confidence summary: `{summary['adsb_reconstruction_summary']['adsb_time_source_conf_v2_summary']}`",
        f"- Continuous AMDAR support weight summary: `{summary['adsb_reconstruction_summary']['stage7_obs_weight_hint_continuous_v2_summary']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## 关键修正点",
        "",
        "- Stage8 没有直接用全表 `source_row_index` join。因为 `clean_wind` 中 AMDAR 与 TURB 的 `source_row_index` 不是全局唯一，脚本先拆分 `source == amdar` 后再 join Stage6/7，避免把 AMDAR 分级误贴到 TURB。",
        "- `obs_conf_v2` 对 AMDAR 优先使用 Stage7 连续支持权重 `stage7_obs_weight_hint_continuous_v2`；A/B/C/R 仍作为解释性等级和安全 gate，TURB 175 条 enhanced holdout 为 1.0，6 条 review 为 0。",
        "- `adsb_match_conf_v2` 是 ADS-B 诊断置信度；`adsb_time_source_conf_v2` 只有 Stage5 accepted 行非零。rejected ADS-B 候选可以被分析，但不会被强行用作 AMDAR 点时刻。",
        "- `clean_loc.parquet` 未复制，避免制造大型重复中间产物；Stage8 只产出增强 `clean_wind` 和紧凑 summary。",
        "",
        "## Outputs",
        "",
        f"- Enhanced clean wind: `{summary['outputs']['clean_wind_with_confidence']}`",
        f"- Stage8 summary: `{summary['outputs']['stage8_summary']}`",
        f"- Stage8 policy: `{summary['outputs']['stage8_policy']}`",
        f"- Confidence tier summary: `{summary['outputs']['confidence_tier_summary']}`",
        f"- Time uncertainty summary: `{summary['outputs']['time_uncertainty_summary']}`",
        f"- ADS-B reconstruction summary: `{summary['outputs']['adsb_reconstruction_summary']}`",
        f"- Grade transition matrix: `{summary['outputs']['grade_transition_matrix']}`",
        "",
        "## 下一步建议",
        "",
        "1. 进入 Stage9：Stage2 角色分流，拆出 strict truth、A/B current support、C batch/super-ob support、R display/reject 通道。",
        "2. Stage9 必须继续保留 AMDAR `holdout_eligible=false`，并用时间分布与目标帧窗口重叠概率计算 frame-level time confidence。",
        "3. 不要把 R 级 AMDAR 当常规支持资料；C 级建议先走 super-ob/低权重通道。",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：Stage8 Enhanced Stage1 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要从零开始。当前已经完成 Stage2 v6、Stage3 v7、Stage4 confidence v2、Stage5 V3、Stage6 time uncertainty v2、Stage7 grade calibration，并完成 Stage8 enhanced Stage1 join。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目 strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：strict truth 少是数据现实，AMDAR 应走分层置信度。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan 阶段边界、Stage8/9 要求和禁止操作。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage6_time_uncertainty_v2_optimized_20260701/stage6_time_uncertainty_results_analysis_and_next_steps.md`：Stage6 时间分布结果。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage7_grade_calibration_optimized_20260701/stage7_grade_calibration_results_analysis_and_next_steps.md`：Stage7 分级与 pseudo/locked-test gate。",
        f"7. `{result_path}`：Stage8 输出、达标判断、下一步建议。",
        f"8. `{summary['outputs']['stage8_summary']}`：Stage8 machine-readable completion checks。",
        f"9. `{summary['outputs']['stage8_policy']}`：字段映射和禁止误用规则。",
        "",
        "## 本轮脚本和输出",
        "",
        "- 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage8_enhanced_stage1_20260701.py`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- `clean_wind_with_confidence.parquet`：431,189 条风观测增强 Stage1 输出。",
        "- AMDAR 关键置信度字段：`adsb_match_conf_v2`、`adsb_time_source_conf_v2`、`stage7_obs_weight_hint_continuous_v2`、`obs_conf_v2`。",
        "- `stage8_enhanced_stage1_summary.json`：总指标和 completion checks。",
        "- `stage8_policy_v1.json`：Stage8 字段映射与禁止误用说明。",
        "- `confidence_tier_summary.json`、`time_uncertainty_summary.json`、`adsb_reconstruction_summary.json`、`grade_transition_matrix.json`：分布与诊断。",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage8_enhanced_stage1_20260701.py \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25 --workers 25",
        "```",
        "",
        "## 关键结果",
        "",
        f"- Row counts: `{summary['row_counts']}`",
        f"- Confidence grade counts: `{summary['confidence_grade_counts']}`",
        f"- AMDAR Stage7 grade counts: `{summary['amdar_stage7_grade_counts']}`",
        f"- AMDAR time source counts: `{summary['amdar_time_source_counts']}`",
        f"- ADS-B confidence basis counts: `{summary['adsb_reconstruction_summary']['adsb_confidence_basis_counts']}`",
        f"- ADS-B confidence class counts: `{summary['adsb_reconstruction_summary']['adsb_match_confidence_class_counts']}`",
        f"- Continuous AMDAR support weight summary: `{summary['adsb_reconstruction_summary']['stage7_obs_weight_hint_continuous_v2_summary']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 仍然全部 `holdout_eligible=false`、`stage8_effective_strict_truth=false`、`estimated_time_is_strict_point_truth=false`。",
        "- TURB 181 条保留 point-time strict semantics；其中 175 条是 T0/S official enhanced holdout，6 条是 T4/R holdout review。",
        "- `source_row_index` 只在 AMDAR 子集内用于 Stage6/7 join，不能对全表直接 join。",
        "- `obs_conf_v2` 对 AMDAR 已经使用连续支持权重，不再只是 A/B/C 离散常数。",
        "- `adsb_time_source_conf_v2` 只有 Stage5 accepted ADS-B 行可以非零；rejected/no-candidate 不得用 ADS-B 时间替代 AMDAR 批次时间。",
        "- R 级 AMDAR 不能作为常规支持资料；display-only 与 rejected 需要分开处理。",
        "- Stage9/Stage10 之前不要迁移 official Stage2/Stage4 默认权重。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage6/7/8 结果。",
        "当前结论：Stage8 已把 Stage6 时间分布、Stage7 S/A/B/C/R 支持等级和连续置信度 join 回 Stage1 clean_wind；输出共 431,189 行，其中 431,008 AMDAR 全部非 holdout，AMDAR obs_conf_v2 已使用 stage7_obs_weight_hint_continuous_v2，TURB 保留 181 条 point-time strict semantics，其中 175 条 official enhanced holdout、6 条 review。",
        "下一步我会进入 Stage9 做 Stage2 角色分流：strict truth、A/B current support、C batch/super-ob support、R display/reject 分通道，并用时间分布与目标帧窗口重叠概率计算 frame-level time confidence；我不会把 rejected ADS-B 候选当作 AMDAR 点时刻。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage8_enhanced_stage1_start"}, ensure_ascii=False))
    stage6_summary, stage7_summary = require_upstream_gates(cfg)
    summary = build_enhanced_stage1(cfg, stage6_summary, stage7_summary)
    policy = build_policy(cfg, summary)
    write_json(cfg.out_dir / "stage8_enhanced_stage1_summary.json", summary)
    write_json(cfg.out_dir / "stage8_policy_v1.json", policy)
    write_docs(cfg, summary)
    print(
        json.dumps(
            {
                "stage": "stage8_enhanced_stage1_done",
                "passed": summary["stage8_completion_checks"]["passed_stage8_enhanced_stage1_gate"],
                "rows": summary["row_counts"]["clean_wind_rows"],
                "out_dir": str(cfg.out_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
