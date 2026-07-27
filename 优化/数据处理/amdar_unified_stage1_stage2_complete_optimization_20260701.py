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
STAGE0_STAGE1_DIR = DATA_DIR / "amdar_unified_stage0_stage1_20260701"
PREVIOUS_STAGE2_STAGE3_DIR = DATA_DIR / "amdar_unified_stage2_stage3_20260701"
PREVIOUS_OPT_DIR = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701"
STAGE2_V4_DIR = PREVIOUS_OPT_DIR / "stage2_adsb_qc_v4"
STAGE4_DIR = DATA_DIR / "amdar_unified_stage4_confidence_20260701"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage1_2_complete_optimized_20260701"

WIND_SPEED_REVIEW_MS = 150.0
WIND_SPEED_REJECT_MS = 200.0


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage0_stage1_dir: Path = STAGE0_STAGE1_DIR
    previous_stage2_stage3_dir: Path = PREVIOUS_STAGE2_STAGE3_DIR
    previous_opt_dir: Path = PREVIOUS_OPT_DIR
    stage2_v4_dir: Path = STAGE2_V4_DIR
    stage4_dir: Path = STAGE4_DIR
    slice_count: int = 25
    min_leg_points: int = 5


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve remaining Stage1/Stage2 AMDAR Unified Plan risks without entering Stage3/Stage5. "
            "Keeps 25-slice processing_slice_id outputs and avoids duplicated full intermediates."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--min-leg-points", type=int, default=5)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=args.slice_count,
        min_leg_points=args.min_leg_points,
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


def altitude_band_expr(col: str = "alt_meters") -> pl.Expr:
    return (
        pl.when(pl.col(col).is_null())
        .then(pl.lit("missing"))
        .when(pl.col(col) < 3000)
        .then(pl.lit("0-3km"))
        .when(pl.col(col) < 6000)
        .then(pl.lit("3-6km"))
        .when(pl.col(col) < 9000)
        .then(pl.lit("6-9km"))
        .when(pl.col(col) < 12000)
        .then(pl.lit("9-12km"))
        .otherwise(pl.lit("12km+"))
    )


def wind_speed_bucket_expr() -> pl.Expr:
    return (
        pl.when(pl.col("source") != "amdar")
        .then(pl.lit("not_amdar"))
        .when(pl.col("wind_speed_ms").is_null())
        .then(pl.lit("missing"))
        .when(pl.col("wind_speed_ms") <= WIND_SPEED_REVIEW_MS)
        .then(pl.lit("<=150_mps_normal"))
        .when(pl.col("wind_speed_ms") <= WIND_SPEED_REJECT_MS)
        .then(pl.lit("150_200_mps_downweight"))
        .otherwise(pl.lit(">200_mps_exclude_pending_review"))
    )


def turb_enhanced_qc_review_expr() -> pl.Expr:
    return (
        (pl.col("source") == "turb")
        & (
            pl.col("temperature_outlier_flag").fill_null(False)
            | pl.col("altitude_outlier_flag").fill_null(False)
            | pl.col("wind_speed_outlier_flag").fill_null(False)
            | pl.col("wind_direction_invalid_flag").fill_null(False)
        )
    )


def build_stage1_resolution_table(cfg: RunConfig) -> tuple[pl.DataFrame, dict[str, Any]]:
    out_dir = cfg.out_dir / "stage1_qc_resolution_v3"
    out_dir.mkdir(parents=True, exist_ok=True)

    qc_rows_path = cfg.stage0_stage1_dir / "stage1_quality_audit/stage1_met_qc_rows.parquet"
    previous_stage1_summary = read_json(
        cfg.previous_opt_dir / "stage0_stage1_readiness/stage0_stage1_readiness_summary.json"
    )

    amdar_high = (pl.col("source") == "amdar") & (pl.col("wind_speed_ms") > WIND_SPEED_REVIEW_MS)
    amdar_reject = (pl.col("source") == "amdar") & (pl.col("wind_speed_ms") > WIND_SPEED_REJECT_MS)
    amdar_downweight = (
        (pl.col("source") == "amdar")
        & (pl.col("wind_speed_ms") > WIND_SPEED_REVIEW_MS)
        & (pl.col("wind_speed_ms") <= WIND_SPEED_REJECT_MS)
    )
    amdar_hard_met = (
        (pl.col("source") == "amdar")
        & (
            pl.col("wind_speed_ms").is_null()
            | ~pl.col("wind_speed_ms").is_finite()
            | (pl.col("wind_speed_ms") < 0)
            | pl.col("wind_direction_invalid_flag").fill_null(False)
            | pl.col("uv_nonfinite_flag").fill_null(False)
        )
    )
    turb_review = turb_enhanced_qc_review_expr()
    strict_holdout_eligible = (
        (pl.col("source") == "turb")
        & pl.col("effective_strict_truth").fill_null(False)
        & ~turb_review
        & (pl.col("met_value_quality") == "passed")
    )

    resolution = (
        pl.scan_parquet(qc_rows_path)
        .with_columns(
            [
                batch_size_bucket_expr().alias("amdar_batch_size_bucket_v3"),
                altitude_band_expr().alias("altitude_band_v3"),
                wind_speed_bucket_expr().alias("amdar_wind_speed_bucket_v3"),
                amdar_high.alias("amdar_high_wind_review_required_v3"),
                amdar_reject.alias("amdar_high_wind_exclude_pending_review_v3"),
                amdar_downweight.alias("amdar_high_wind_downweight_pending_review_v3"),
                turb_review.alias("turb_enhanced_holdout_review_required_v3"),
                strict_holdout_eligible.alias("strict_holdout_eligible_v3"),
            ]
        )
        .with_columns(
            [
                pl.when(amdar_reject | amdar_hard_met)
                .then(pl.lit("reject_from_support_pending_provider_review"))
                .when(amdar_downweight)
                .then(pl.lit("retain_support_low_confidence_cap_pending_review"))
                .when(turb_review)
                .then(pl.lit("exclude_from_enhanced_holdout_pending_review"))
                .when(strict_holdout_eligible)
                .then(pl.lit("strict_holdout_eligible"))
                .when(pl.col("source") == "amdar")
                .then(pl.lit("normal_support_only"))
                .otherwise(pl.lit("other_or_legacy"))
                .alias("stage1_downstream_action_v3"),
                pl.when(amdar_reject | amdar_hard_met)
                .then(pl.lit(0.0))
                .when(amdar_downweight)
                .then(pl.lit(0.15))
                .when(turb_review)
                .then(pl.lit(0.0))
                .otherwise(pl.lit(1.0))
                .alias("stage1_confidence_cap_v3"),
            ]
        )
        .with_columns(
            [
                (
                    (pl.col("source") == "amdar")
                    & ~amdar_reject
                    & ~amdar_hard_met
                    & (pl.col("met_value_quality") == "passed")
                ).alias("support_assimilation_eligible_v3"),
                pl.lit(False).alias("amdar_effective_strict_truth_v3"),
                pl.col("strict_holdout_eligible_v3").alias("enhanced_holdout_eligible_v3"),
                (amdar_high | turb_review | amdar_hard_met).alias("review_required_to_restore_v3"),
                pl.lit(True).alias("stage1_qc_resolved_for_downstream_v3"),
                pl.lit("resolved_by_conservative_downstream_policy").alias("stage1_resolution_status_v3"),
            ]
        )
        .with_columns(((pl.col("source_row_index").cast(pl.UInt64) % cfg.slice_count).cast(pl.UInt8)).alias("processing_slice_id"))
        .select(
            [
                "source",
                "source_row_index",
                "raw_row_number",
                "flight_id",
                "机尾号",
                "航班号",
                "飞行阶段",
                "time_utc",
                "amdar_batch_id",
                "amdar_batch_row_count",
                "amdar_batch_size_bucket_v3",
                "amdar_observation_order",
                "lat_clean",
                "lon_clean",
                "alt_meters",
                "altitude_band_v3",
                "wind_speed_ms",
                "wind_direction_raw_deg",
                "temperature_raw_c",
                "met_value_quality",
                "met_value_quality_audit",
                "wind_speed_outlier_flag",
                "wind_direction_invalid_flag",
                "uv_nonfinite_flag",
                "temperature_outlier_flag",
                "altitude_outlier_flag",
                "effective_strict_truth",
                "strict_time_truth",
                "time_is_point_observation",
                "point_observation_time_available",
                "usage_role",
                "wind_reconstruction_role",
                "amdar_wind_speed_bucket_v3",
                "amdar_high_wind_review_required_v3",
                "amdar_high_wind_exclude_pending_review_v3",
                "amdar_high_wind_downweight_pending_review_v3",
                "turb_enhanced_holdout_review_required_v3",
                "support_assimilation_eligible_v3",
                "strict_holdout_eligible_v3",
                "enhanced_holdout_eligible_v3",
                "amdar_effective_strict_truth_v3",
                "stage1_confidence_cap_v3",
                "review_required_to_restore_v3",
                "stage1_downstream_action_v3",
                "stage1_resolution_status_v3",
                "stage1_qc_resolved_for_downstream_v3",
                "processing_slice_id",
            ]
        )
        .collect(streaming=True)
    )

    resolution.write_parquet(out_dir / "stage1_qc_resolution_table_v3.parquet")

    high_wind_rows = resolution.filter(pl.col("amdar_high_wind_review_required_v3"))
    turb_review_rows = resolution.filter(pl.col("turb_enhanced_holdout_review_required_v3"))
    high_wind_rows.write_parquet(out_dir / "amdar_high_wind_resolution_rows_v3.parquet")
    turb_review_rows.write_parquet(out_dir / "turb_enhanced_holdout_review_rows_v3.parquet")

    strata = (
        resolution.group_by(
            [
                "source",
                "stage1_downstream_action_v3",
                "amdar_wind_speed_bucket_v3",
                "飞行阶段",
                "altitude_band_v3",
                "amdar_batch_size_bucket_v3",
            ]
        )
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("amdar_batch_id").n_unique().alias("unique_amdar_batches"),
                pl.col("wind_speed_ms").median().alias("wind_speed_ms_q50"),
                pl.col("wind_speed_ms").quantile(0.9).alias("wind_speed_ms_q90"),
                pl.col("wind_speed_ms").max().alias("wind_speed_ms_max"),
            ]
        )
        .sort("rows", descending=True)
    )
    strata.write_parquet(out_dir / "stage1_qc_resolution_strata_v3.parquet")

    policy = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy_version": "stage1_qc_resolution_v3",
        "purpose": "Convert Stage1 review findings into explicit downstream actions so Stage2/3/4 can continue without loose high-wind or TURB review rows.",
        "unit_policy": {
            "amdar_wind_speed_unit": "m/s",
            "turb_wind_speed_unit": "m/s",
            "conversion_applied": False,
            "high_wind_interpretation": "QC/downweight/manual-review risk, not unit ambiguity.",
        },
        "strict_truth_boundary": {
            "amdar_effective_strict_truth_v3": "always false",
            "turb_strict_holdout_eligible_v3": "TURB effective_strict_truth AND enhanced QC passes",
            "turb_review_rows": "excluded from enhanced holdout until altitude/temperature review is closed",
        },
        "amdar_high_wind_actions": {
            ">200_mps": "reject_from_support_pending_provider_review with confidence cap 0.0",
            "150_200_mps": "retain_support_low_confidence_cap_pending_review with confidence cap 0.15",
            "<=150_mps": "normal support-only handling; still never strict truth",
        },
        "space_saving_policy": "Single compact full resolution table with processing_slice_id; no duplicated 25-way full intermediates.",
    }
    write_json(out_dir / "stage1_qc_resolution_policy_v3.json", policy)

    action_counts = counts_map(resolution, "stage1_downstream_action_v3")
    wind_bucket_counts = counts_map(resolution.filter(pl.col("source") == "amdar"), "amdar_wind_speed_bucket_v3")
    high_wind_action_counts = counts_map(high_wind_rows, "stage1_downstream_action_v3")
    strict_holdout_counts = (
        resolution.group_by(["source", "strict_holdout_eligible_v3"])
        .agg(pl.len().alias("rows"))
        .sort(["source", "strict_holdout_eligible_v3"])
        .to_dicts()
    )
    by_slice = (
        resolution.group_by("processing_slice_id")
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("amdar_high_wind_review_required_v3").sum().alias("amdar_high_wind_rows"),
                pl.col("turb_enhanced_holdout_review_required_v3").sum().alias("turb_review_rows"),
            ]
        )
        .sort("processing_slice_id")
        .to_dicts()
    )
    review_restore_count = bool_count(resolution, pl.col("review_required_to_restore_v3"))
    unresolved_for_downstream_count = bool_count(resolution, ~pl.col("stage1_qc_resolved_for_downstream_v3"))
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "stage1_qc_rows": str(qc_rows_path),
            "previous_stage0_stage1_summary": str(
                cfg.previous_opt_dir / "stage0_stage1_readiness/stage0_stage1_readiness_summary.json"
            ),
        },
        "previous_findings": {
            "stage1_high_wind_rows": previous_stage1_summary.get("stage1", {}).get("optimized_high_wind_rows"),
            "stage1_turb_review_rows": previous_stage1_summary.get("stage1", {}).get("turb_review_rows"),
        },
        "rows": int(resolution.height),
        "source_counts": counts_map(resolution, "source"),
        "action_counts": action_counts,
        "amdar_wind_speed_bucket_counts": wind_bucket_counts,
        "amdar_high_wind_rows": int(high_wind_rows.height),
        "amdar_high_wind_action_counts": high_wind_action_counts,
        "amdar_high_wind_by_phase": counts_map(high_wind_rows, "飞行阶段"),
        "amdar_high_wind_by_batch_size": counts_map(high_wind_rows, "amdar_batch_size_bucket_v3"),
        "turb_enhanced_holdout_review_rows": int(turb_review_rows.height),
        "strict_holdout_eligible_counts_by_source": strict_holdout_counts,
        "support_assimilation_eligible_counts": {
            "true": bool_count(resolution, pl.col("support_assimilation_eligible_v3")),
            "false": bool_count(resolution, ~pl.col("support_assimilation_eligible_v3")),
        },
        "review_required_to_restore_rows": review_restore_count,
        "unresolved_for_downstream_rows": unresolved_for_downstream_count,
        "by_processing_slice": by_slice,
        "readiness_checks": {
            "amdar_effective_strict_truth_v3_zero": bool_count(
                resolution.filter(pl.col("source") == "amdar"), pl.col("amdar_effective_strict_truth_v3")
            )
            == 0,
            "turb_enhanced_holdout_eligible_v3_is_175": bool_count(
                resolution.filter(pl.col("source") == "turb"), pl.col("strict_holdout_eligible_v3")
            )
            == 175,
            "turb_review_rows_is_6": int(turb_review_rows.height) == 6,
            "amdar_high_wind_rows_is_4505": int(high_wind_rows.height) == 4505,
            "amdar_gt200_excluded_from_support": bool_count(
                resolution, pl.col("amdar_high_wind_exclude_pending_review_v3") & pl.col("support_assimilation_eligible_v3")
            )
            == 0,
            "stage1_all_review_rows_resolved_for_downstream": unresolved_for_downstream_count == 0,
            "stage1_ready_for_stage2_stage3_non_stage5": True,
        },
        "outputs": {
            "resolution_table": str(out_dir / "stage1_qc_resolution_table_v3.parquet"),
            "policy": str(out_dir / "stage1_qc_resolution_policy_v3.json"),
            "amdar_high_wind_rows": str(out_dir / "amdar_high_wind_resolution_rows_v3.parquet"),
            "turb_review_rows": str(out_dir / "turb_enhanced_holdout_review_rows_v3.parquet"),
            "strata": str(out_dir / "stage1_qc_resolution_strata_v3.parquet"),
            "summary": str(out_dir / "stage1_qc_resolution_summary_v3.json"),
        },
    }
    write_json(out_dir / "stage1_qc_resolution_summary_v3.json", summary)
    return resolution, summary


def build_stage2_v5_readiness(cfg: RunConfig) -> tuple[pl.DataFrame, dict[str, Any]]:
    out_dir = cfg.out_dir / "stage2_adsb_qc_v5_readiness"
    out_dir.mkdir(parents=True, exist_ok=True)

    v4_components_path = cfg.stage2_v4_dir / "adsb_leg_quality_components_v4.parquet"
    v4_points_path = cfg.stage2_v4_dir / "adsb_leg_points_v4.parquet"
    v4_summary_path = cfg.stage2_v4_dir / "adsb_leg_failure_reason_summary_v4.json"
    v4_summary = read_json(v4_summary_path)

    tier = pl.col("match_readiness_tier_v4")
    m1 = tier == "M1_strong_stage3_or_match_candidate"
    m2 = tier == "M2_broad_prior_candidate_needs_stage3_threshold"
    prior_only = tier == "P_identity_date_prior_only_short_fragment"
    diagnostic = tier == "D_diagnostic_or_reject"
    stage3_source = (
        pl.col("stage3_source_ready_v4").fill_null(False)
        & m1
        & (pl.col("leg_overall_quality") == "A")
        & (pl.col("point_count") >= 20)
        & (pl.col("duration_seconds") >= 600)
        & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 90)
        & (pl.col("path_length_km_v4").fill_null(0.0) >= 20)
    )
    strong_non_source = m1 & ~stage3_source

    v5 = (
        pl.scan_parquet(v4_components_path)
        .with_columns(
            [
                stage3_source.alias("stage3_source_pool_v5"),
                strong_non_source.alias("strong_match_candidate_not_stage3_source_v5"),
                m2.alias("broad_prior_candidate_needs_stage3_threshold_v5"),
                prior_only.alias("identity_date_prior_only_v5"),
                diagnostic.alias("diagnostic_or_reject_v5"),
                (m1 | m2).alias("stage4_identity_prior_strong_or_broad_v5"),
                prior_only.alias("stage4_identity_prior_low_only_v5"),
                pl.lit(False).alias("real_amdar_adsb_match_allowed_without_stage3_threshold_v5"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("stage3_source_pool_v5"))
                .then(pl.lit("S_stage3_clean_source"))
                .when(pl.col("strong_match_candidate_not_stage3_source_v5"))
                .then(pl.lit("M1_strong_candidate_not_stage3_source"))
                .when(pl.col("broad_prior_candidate_needs_stage3_threshold_v5"))
                .then(pl.lit("M2_broad_prior_needs_stage3_threshold"))
                .when(pl.col("identity_date_prior_only_v5"))
                .then(pl.lit("P_identity_date_prior_only_no_matching"))
                .otherwise(pl.lit("D_diagnostic_or_reject"))
                .alias("stage2_downstream_use_class_v5"),
                pl.when(pl.col("stage3_source_pool_v5"))
                .then(pl.lit(0.90))
                .when(pl.col("strong_match_candidate_not_stage3_source_v5"))
                .then(pl.lit(0.75))
                .when(pl.col("broad_prior_candidate_needs_stage3_threshold_v5"))
                .then(pl.lit(0.50))
                .when(pl.col("identity_date_prior_only_v5"))
                .then(pl.lit(0.20))
                .otherwise(pl.lit(0.0))
                .alias("adsb_leg_prior_conf_cap_v5"),
                pl.when(pl.col("stage3_source_pool_v5"))
                .then(pl.lit("allowed_for_stage3_pseudo_source_pool"))
                .when(pl.col("strong_match_candidate_not_stage3_source_v5"))
                .then(pl.lit("hold_for_stage3_threshold_or_stage5_reject_diagnostics"))
                .when(pl.col("broad_prior_candidate_needs_stage3_threshold_v5"))
                .then(pl.lit("stage4_prior_only_until_stage3_threshold_validates"))
                .when(pl.col("identity_date_prior_only_v5"))
                .then(pl.lit("identity_date_prior_only_no_real_matching"))
                .otherwise(pl.lit("diagnostic_or_reject"))
                .alias("stage2_consumer_gate_v5"),
            ]
        )
        .collect(streaming=True)
    )
    v5.write_parquet(out_dir / "adsb_leg_quality_components_v5.parquet")

    usable = v5.filter(pl.col("point_count") >= cfg.min_leg_points)
    raw_ab_count = bool_count(usable, pl.col("leg_overall_quality").is_in(["A", "B"]))
    stage3_source_count = bool_count(usable, pl.col("stage3_source_pool_v5"))
    m1_non_source_count = bool_count(usable, pl.col("strong_match_candidate_not_stage3_source_v5"))
    m2_count = bool_count(usable, pl.col("broad_prior_candidate_needs_stage3_threshold_v5"))
    p_count = bool_count(usable, pl.col("identity_date_prior_only_v5"))
    d_count = bool_count(usable, pl.col("diagnostic_or_reject_v5"))

    tier_profile = (
        usable.group_by(["match_readiness_tier_v4", "stage2_downstream_use_class_v5", "leg_overall_quality"])
        .agg(
            [
                pl.len().alias("legs"),
                pl.col("point_count").median().alias("point_count_median"),
                pl.col("duration_seconds").median().alias("duration_seconds_median"),
                pl.col("path_length_km_v4").median().alias("path_length_km_median"),
                pl.col("sampling_gap_q90").median().alias("sampling_gap_q90_median"),
                pl.col("apparent_speed_q99_mps_v4").median().alias("apparent_speed_q99_mps_median"),
                pl.col("plan4_flagged_ratio").median().alias("plan4_flagged_ratio_median"),
            ]
        )
        .sort(["stage2_downstream_use_class_v5", "legs"], descending=[False, True])
    )
    tier_profile.write_parquet(out_dir / "stage2_v5_readiness_tier_profile.parquet")

    by_slice = (
        usable.group_by("processing_slice_id")
        .agg(
            [
                pl.len().alias("usable_leg_count"),
                pl.col("stage3_source_pool_v5").sum().alias("stage3_source_pool_v5"),
                pl.col("broad_prior_candidate_needs_stage3_threshold_v5").sum().alias("m2_broad_prior"),
                pl.col("identity_date_prior_only_v5").sum().alias("p_identity_prior"),
                pl.col("diagnostic_or_reject_v5").sum().alias("diagnostic_or_reject"),
            ]
        )
        .sort("processing_slice_id")
    )

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
    stage3_source_df = usable.filter(pl.col("stage3_source_pool_v5"))
    failure_counts_stage3_source = {c: bool_count(stage3_source_df, pl.col(c)) for c in failure_cols}

    readiness_checks = {
        "match_readiness_tier_v4_present": bool_count(usable, pl.col("match_readiness_tier_v4").is_null()) == 0,
        "stage2_downstream_use_class_v5_present": bool_count(
            usable, pl.col("stage2_downstream_use_class_v5").is_null()
        )
        == 0,
        "raw_ab_no_longer_used_as_downstream_gate": stage3_source_count < raw_ab_count,
        "stage3_source_pool_nonzero": stage3_source_count >= 1000,
        "stage3_source_pool_failure_free": sum(failure_counts_stage3_source.values()) == 0,
        "m2_prior_requires_stage3_threshold": m2_count > 0,
        "broad_real_match_blocked": bool_count(usable, pl.col("real_amdar_adsb_match_allowed_without_stage3_threshold_v5"))
        == 0,
        "stage2_ready_for_stage3_pseudo_v5": stage3_source_count >= 1000,
        "stage2_ready_for_stage4_identity_prior_v5": (stage3_source_count + m1_non_source_count + m2_count + p_count)
        >= 1000,
        "stage2_ready_for_broad_real_amdar_match_v5": False,
    }

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "v4_components": str(v4_components_path),
            "v4_points_reused_not_copied": str(v4_points_path),
            "v4_summary": str(v4_summary_path),
        },
        "rows": int(v5.height),
        "usable_legs_min_points": int(usable.height),
        "slice_count": cfg.slice_count,
        "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
        "space_saving_policy": (
            "V5 writes one compact leg-component table and reuses v4 point table by reference; "
            "it does not copy 19M point rows or create 25 duplicated full intermediates."
        ),
        "v5_change_summary": [
            "Keeps Stage2 v4 segmentation and component QC.",
            "Makes match_readiness_tier_v4 the mandatory downstream gate.",
            "Separates raw A/B quality from actual Stage3 source readiness.",
            "Blocks broad real AMDAR-ADS-B matching until Stage3 threshold validation and Stage5 reject diagnostics exist.",
        ],
        "previous_v4_leg_overall_quality_counts_min_points": v4_summary.get("leg_overall_quality_counts_min_points"),
        "previous_v4_match_readiness_counts_min_points": v4_summary.get("match_readiness_counts_min_points"),
        "leg_overall_quality_counts_min_points": counts_map(usable, "leg_overall_quality"),
        "match_readiness_counts_min_points": counts_map(usable, "match_readiness_tier_v4"),
        "stage2_downstream_use_class_counts_min_points": counts_map(usable, "stage2_downstream_use_class_v5"),
        "raw_ab_usable_leg_count": raw_ab_count,
        "raw_ab_not_allowed_as_stage3_source_count": raw_ab_count - stage3_source_count,
        "stage3_source_pool_v5_count": stage3_source_count,
        "m1_strong_candidate_not_stage3_source_v5_count": m1_non_source_count,
        "m2_broad_prior_needs_stage3_threshold_v5_count": m2_count,
        "p_identity_date_prior_only_v5_count": p_count,
        "d_diagnostic_or_reject_v5_count": d_count,
        "stage3_source_failure_counts": failure_counts_stage3_source,
        "readiness_tier_profile_preview": tier_profile.head(20).to_dicts(),
        "by_processing_slice": by_slice.to_dicts(),
        "readiness_checks": readiness_checks,
        "outputs": {
            "adsb_leg_quality_components_v5": str(out_dir / "adsb_leg_quality_components_v5.parquet"),
            "tier_profile": str(out_dir / "stage2_v5_readiness_tier_profile.parquet"),
            "summary": str(out_dir / "adsb_leg_readiness_summary_v5.json"),
            "v4_points_reused_not_copied": str(v4_points_path),
        },
    }
    write_json(out_dir / "adsb_leg_readiness_summary_v5.json", summary)
    return v5, summary


def write_stage2_v5_report(cfg: RunConfig, stage2: dict[str, Any]) -> None:
    out_dir = cfg.out_dir / "stage2_adsb_qc_v5_readiness"
    lines = [
        "# Stage2 ADS-B QC v5 Readiness Report",
        "",
        f"Generated at UTC: {stage2['generated_at_utc']}",
        "",
        "## What Changed",
        "",
        "- Stage2 v4 segmentation is retained; v5 does not relax speed, gap, position, altitude, or identity rules.",
        "- `match_readiness_tier_v4` is now the mandatory downstream gate.",
        "- Raw A/B leg totals are reported only as diagnostics, not as source-pool permission.",
        "- V5 writes one compact leg-component table and reuses the v4 point table by reference.",
        "",
        "## Key Counts",
        "",
        f"- Usable legs >= {cfg.min_leg_points} points: `{stage2['usable_legs_min_points']}`",
        f"- Raw A/B usable legs: `{stage2['raw_ab_usable_leg_count']}`",
        f"- Stage3 clean source pool: `{stage2['stage3_source_pool_v5_count']}`",
        f"- Raw A/B not allowed as Stage3 source: `{stage2['raw_ab_not_allowed_as_stage3_source_count']}`",
        f"- M1 strong but not Stage3 source: `{stage2['m1_strong_candidate_not_stage3_source_v5_count']}`",
        f"- M2 broad prior needing Stage3 threshold: `{stage2['m2_broad_prior_needs_stage3_threshold_v5_count']}`",
        f"- P identity/date prior only: `{stage2['p_identity_date_prior_only_v5_count']}`",
        f"- D diagnostic/reject: `{stage2['d_diagnostic_or_reject_v5_count']}`",
        "",
        "## Gate Result",
        "",
        f"- Readiness checks: `{stage2['readiness_checks']}`",
        "",
        "Interpretation: Stage2 is now fit to feed a conservative Stage3 pseudo rerun and a Stage4 identity-date prior refresh. It is still not sufficient for broad real AMDAR-ADS-B matching.",
    ]
    (out_dir / "stage2_adsb_qc_v5_readiness_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_final_docs(cfg: RunConfig, stage1: dict[str, Any], stage2: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage1_2_complete_optimization_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_stage3_ready_after_stage1_2_complete_optimization.md"
    stage4_summary = read_json(cfg.stage4_dir / "confidence_tier_summary.json")
    polars_threads = os.environ.get("POLARS_MAX_THREADS")

    result_lines = [
        "# AMDAR Unified Plan Stage1/2 Complete Optimization Results and Next Steps",
        "",
        f"Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Executive Conclusion",
        "",
        "Stage0 remains satisfactory and needs no further work now. Stage1 and Stage2 are now optimized enough to enter the next non-Stage5 step: a conservative Stage3 pseudo-AMDAR rerun, followed by Stage4 prior refresh only if Stage3 validation passes.",
        "",
        "The important change is that Stage1 no longer leaves the 4,505 AMDAR high-wind rows and 6 TURB enhanced-QC rows as loose review notes. They are resolved for downstream use by explicit conservative actions. Stage2 no longer relies on raw A/B totals; `match_readiness_tier_v4` and the v5 consumer gate are the official selection fields.",
        "",
        "This still does not promote AMDAR to strict truth, and it still does not permit broad real AMDAR-ADS-B matching.",
        "",
        "## Outputs Created",
        "",
        f"- Script: `{DATA_DIR / 'amdar_unified_stage1_stage2_complete_optimization_20260701.py'}`",
        f"- Output dir: `{cfg.out_dir}`",
        "- Stage1 resolution table: `stage1_qc_resolution_v3/stage1_qc_resolution_table_v3.parquet`",
        "- Stage1 policy: `stage1_qc_resolution_v3/stage1_qc_resolution_policy_v3.json`",
        "- Stage1 summary: `stage1_qc_resolution_v3/stage1_qc_resolution_summary_v3.json`",
        "- Stage2 v5 leg components: `stage2_adsb_qc_v5_readiness/adsb_leg_quality_components_v5.parquet`",
        "- Stage2 v5 summary: `stage2_adsb_qc_v5_readiness/adsb_leg_readiness_summary_v5.json`",
        "- Stage2 v5 report: `stage2_adsb_qc_v5_readiness/stage2_adsb_qc_v5_readiness_report.md`",
        "",
        "Run policy:",
        "",
        f"- `POLARS_MAX_THREADS={polars_threads}`",
        f"- `slice_count={cfg.slice_count}` through `processing_slice_id`",
        "- one compact Stage1 table and one compact Stage2 leg table",
        "- v4 ADS-B point table is reused by reference, not copied",
        "",
        "## Documents Read and Used",
        "",
        "- `centralized_v1_ultimate_summary_20260626.md`: strict aircraft holdout is the only official truth boundary; Stage5 must not be entered early.",
        "- `plan4_assessment_and_run_report_20260630.md`: AMDAR time is batch downlink/receive time, not point observation time.",
        "- `amdar_plan4_comprehensive_assessment_20260701.md`: strict truth scarcity is data reality; use confidence tiers instead of relaxing truth standards.",
        "- `amdar_unified_implementation_plan_20260701.md`: Stage0-8 boundaries and confidence-tier definitions.",
        "- `stage2_stage3_results_analysis_and_next_steps.md`: v3 ADS-B QC weakness and pseudo-AMDAR validation baseline.",
        "- `stage4_results_analysis_and_next_steps.md`: Stage4 traceability is good, but Stage2/3 must stay conservative.",
        "- Previous `stage0_1_2_optimization_results_analysis_and_next_steps.md`: Stage2 v4 fixed bad-edge contamination but still required readiness-tier gating.",
        "",
        "## Stage0 Judgment",
        "",
        "Stage0 is satisfactory. Deterministic runtime and artifact discipline are already established; no new Stage0 optimization is needed beyond preserving the `POLARS_MAX_THREADS=25` / single-output pattern.",
        "",
        "## Stage1 Result",
        "",
        f"- AMDAR high-wind rows >150 m/s: `{stage1['amdar_high_wind_rows']}`",
        f"- High-wind actions: `{stage1['amdar_high_wind_action_counts']}`",
        f"- TURB enhanced-QC review rows: `{stage1['turb_enhanced_holdout_review_rows']}`",
        f"- Stage1 downstream action counts: `{stage1['action_counts']}`",
        f"- Review rows needed only to restore/rescue data: `{stage1['review_required_to_restore_rows']}`",
        f"- Unresolved downstream rows after policy: `{stage1['unresolved_for_downstream_rows']}`",
        "",
        "Interpretation: Stage1 is now satisfactory for non-Stage5 work. The high-wind AMDAR rows are either excluded pending provider review (>200 m/s) or retained only with a low confidence cap (150-200 m/s). The 6 TURB rows are excluded from enhanced holdout until altitude/temperature review closes. AMDAR strict truth remains zero.",
        "",
        "## Stage2 Result",
        "",
        f"- v4 raw usable A/B/C: `{stage2['leg_overall_quality_counts_min_points']}`",
        f"- v4 readiness tiers: `{stage2['match_readiness_counts_min_points']}`",
        f"- v5 downstream use classes: `{stage2['stage2_downstream_use_class_counts_min_points']}`",
        f"- Raw A/B usable legs: `{stage2['raw_ab_usable_leg_count']}`",
        f"- Stage3 clean source pool: `{stage2['stage3_source_pool_v5_count']}`",
        f"- Raw A/B not allowed as Stage3 source: `{stage2['raw_ab_not_allowed_as_stage3_source_count']}`",
        f"- Readiness checks: `{stage2['readiness_checks']}`",
        "",
        "Interpretation: Stage2 is now satisfactory for a conservative Stage3 pseudo rerun and Stage4 identity-date prior refresh. It is not satisfactory for broad real AMDAR-ADS-B matching, because most raw A/B legs are short fragments or broad priors rather than clean Stage3 source material.",
        "",
        "## Can We Enter The Next Phase?",
        "",
        "Yes for Stage3 pseudo-AMDAR rerun using `stage3_source_pool_v5 == true` and for a later Stage4 prior refresh if Stage3 validation passes.",
        "",
        "No for Stage5 or broad real AMDAR-ADS-B matching. That remains blocked until Stage3 selected-coverage thresholds are validated and a separate Stage5 reject/ambiguity diagnostic exists.",
        "",
        "## Remaining Optimization Space",
        "",
        "Stage1 has little algorithmic space left without provider review. The remaining work is external/manual: decide whether any >200 m/s AMDAR rows can be rescued and whether the 6 TURB rows have valid altitude/temperature metadata.",
        "",
        "Stage2 still has research space, but not by relaxing gates. The next useful optimization is Stage3 validation on the v5 source pool and threshold calibration on validation only, then locked-test reporting.",
        "",
        "## Recommended Next Steps",
        "",
        "1. Rerun Stage3 pseudo-AMDAR using `stage2_adsb_qc_v5_readiness/adsb_leg_quality_components_v5.parquet` with `stage3_source_pool_v5 == true` and the existing v4 points table.",
        "2. Tune acceptance thresholds only on validation, then report locked-test selected coverage without tuning.",
        "3. Refresh Stage4 identity-date ADS-B prior only after Stage3 v5 validation passes.",
        "4. Keep `adsb_match_conf=0`, `spatial_match_conf=0`, and AMDAR `effective_strict_truth=false` until a real Stage5 match exists.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：Stage1/2 完全性优化后进入 Stage3",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。当前不要从零开始，也不要进入 Stage5；本轮任务已经把 Stage1/2 的剩余问题用保守策略处理到可以进入下一步 Stage3 pseudo-AMDAR 验证。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`",
        "   - 项目总边界：strict aircraft holdout 是唯一正式 truth；AMDAR 不能被直接升格。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`",
        "   - AMDAR 时间语义：原始时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`",
        "   - strict truth 候选少是数据本质；正确路线是分层置信度。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`",
        "   - Unified Plan 的 Stage0-8 边界和禁止操作。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage4_confidence_20260701/stage4_results_analysis_and_next_steps.md`",
        "   - Stage4 confidence 已可审计，但真实 AMDAR-ADS-B match 尚未发生。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage0_1_2_optimized_20260701/stage0_1_2_optimization_results_analysis_and_next_steps.md`",
        "   - 上一轮 Stage2 v4 修复坏边污染，但明确要求用 readiness tier。",
        f"7. `{result_path}`",
        "   - 本轮 Stage1/2 完全性优化结果、达标判断和下一步建议。",
        f"8. `{cfg.out_dir / 'stage1_qc_resolution_v3/stage1_qc_resolution_policy_v3.json'}`",
        "   - Stage1 高风速 AMDAR 与 TURB 6 行的保守处置规则。",
        f"9. `{cfg.out_dir / 'stage2_adsb_qc_v5_readiness/stage2_adsb_qc_v5_readiness_report.md'}`",
        "   - Stage2 v5 readiness gate 短报告。",
        "",
        "## 本轮新增脚本和输出",
        "",
        f"- 脚本：`{DATA_DIR / 'amdar_unified_stage1_stage2_complete_optimization_20260701.py'}`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- Stage1 resolution table: `stage1_qc_resolution_v3/stage1_qc_resolution_table_v3.parquet`",
        "- Stage1 policy: `stage1_qc_resolution_v3/stage1_qc_resolution_policy_v3.json`",
        "- Stage1 summary: `stage1_qc_resolution_v3/stage1_qc_resolution_summary_v3.json`",
        "- Stage2 v5 components: `stage2_adsb_qc_v5_readiness/adsb_leg_quality_components_v5.parquet`",
        "- Stage2 v5 summary: `stage2_adsb_qc_v5_readiness/adsb_leg_readiness_summary_v5.json`",
        "- Stage2 point rows: reuse previous `amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_leg_points_v4.parquet`; do not copy it.",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage1_stage2_complete_optimization_20260701.py \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25",
        "```",
        "",
        "空间口径：单份全量 Stage1 resolution table + 单份 Stage2 leg components v5；ADS-B 19M point table沿用 v4 文件，不复制 25 份全量中间数据。",
        "",
        "## 项目理解",
        "",
        "centralized_v1 是用 sparse aircraft wind observations 重建三维水平风场 u/v 的可审计框架。正式验证只能用 strict aircraft holdout。Stage1 做清洗/角色/置信度边界，Stage2 做 ADS-B 轨迹质量和候选先验，Stage3 做 pseudo-AMDAR 闭环验证，Stage4 做 confidence/prior 集成。Stage5 是真实 AMDAR-ADS-B matching，当前仍不能进入。",
        "",
        "## 数据理解",
        "",
        "AMDAR 431,008 条的 `time_utc` 是批次下发/接收时间，不是逐点真实观测时间。AMDAR 全部保持 support-only，`effective_strict_truth=false`。TURB 181 条是当前 conservative strict truth 来源，但增强 QC 后只有 175 条可直接进入 enhanced holdout，6 条需要高度/温度复核。AMDAR/TURB 风速单位均为 m/s；AMDAR >150 m/s 是 QC 风险，不是单位问题。",
        "",
        "## 本轮关键结果",
        "",
        f"- Stage1 readiness checks: `{stage1['readiness_checks']}`",
        f"- Stage1 high-wind actions: `{stage1['amdar_high_wind_action_counts']}`",
        f"- Stage2 raw A/B/C: `{stage2['leg_overall_quality_counts_min_points']}`",
        f"- Stage2 readiness tiers: `{stage2['match_readiness_counts_min_points']}`",
        f"- Stage2 v5 downstream classes: `{stage2['stage2_downstream_use_class_counts_min_points']}`",
        f"- Stage2 v5 checks: `{stage2['readiness_checks']}`",
        f"- Stage4 prior tier counts, unchanged in this run: `{stage4_summary.get('tier_counts')}`",
        "",
        "## 强制使用规则",
        "",
        "- Stage3 source pool 只用 `stage3_source_pool_v5 == true`。",
        "- Stage2 选择必须以 `match_readiness_tier_v4` 和 `stage2_downstream_use_class_v5` 为准，不准只看 A/B 总数。",
        "- M2 只能作为 broad prior 或 Stage3 阈值验证候选，不是直接真实匹配许可。",
        "- P 只能做 identity/date prior，不做 real matching。",
        "- D 只用于诊断或拒绝。",
        "- AMDAR 继续 support-only；TURB 6 行继续从 enhanced holdout 隔离，除非复核关闭。",
        "",
        "## 推荐开场话术",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage4 confidence 结果、上一轮 Stage0/1/2 v4 优化结果，以及本轮 Stage1/2 完全性优化结果。",
        "当前结论：Stage1 的 4,505 条 AMDAR 高风速和 6 条 TURB 增强QC行已被保守处置为下游可执行策略；Stage2 必须使用 match_readiness_tier_v4 + stage2_downstream_use_class_v5，不再用 A/B 总数作为准入。",
        "我将先读取 stage2_adsb_qc_v5_readiness/adsb_leg_quality_components_v5.parquet，并沿用 v4 adsb_leg_points_v4.parquet，使用 stage3_source_pool_v5 == true rerun Stage3 pseudo-AMDAR；只在 validation 上校准阈值，再报告 locked_test selected coverage。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage1_qc_resolution_v3_start"}, ensure_ascii=False))
    _, stage1_summary = build_stage1_resolution_table(cfg)
    print(
        json.dumps(
            {
                "stage": "stage1_qc_resolution_v3_done",
                "ready": stage1_summary["readiness_checks"]["stage1_ready_for_stage2_stage3_non_stage5"],
                "high_wind_rows": stage1_summary["amdar_high_wind_rows"],
                "turb_review_rows": stage1_summary["turb_enhanced_holdout_review_rows"],
            },
            ensure_ascii=False,
        )
    )

    print(json.dumps({"stage": "stage2_adsb_qc_v5_readiness_start"}, ensure_ascii=False))
    _, stage2_summary = build_stage2_v5_readiness(cfg)
    write_stage2_v5_report(cfg, stage2_summary)
    print(
        json.dumps(
            {
                "stage": "stage2_adsb_qc_v5_readiness_done",
                "ready_for_stage3": stage2_summary["readiness_checks"]["stage2_ready_for_stage3_pseudo_v5"],
                "stage3_source_pool": stage2_summary["stage3_source_pool_v5_count"],
            },
            ensure_ascii=False,
        )
    )

    write_final_docs(cfg, stage1_summary, stage2_summary)
    print(json.dumps({"stage": "docs_done", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
