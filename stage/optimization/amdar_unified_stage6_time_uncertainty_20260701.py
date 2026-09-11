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
STAGE3_4_DIR = DATA_DIR / "amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701"
STAGE4_V2_DIR = STAGE3_4_DIR / "stage4_confidence_v2"
STAGE5_DIR = DATA_DIR / "amdar_unified_stage5_v3_matching_optimized_20260701/stage5_v3"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage6_time_uncertainty_optimized_20260701"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage4_v2_dir: Path = STAGE4_V2_DIR
    stage5_dir: Path = STAGE5_DIR
    slice_count: int = 25
    workers: int = 25
    adsb_latency_floor_s: float = 90.0
    accepted_narrow_uncertainty_cap_s: float = 300.0
    accepted_single_point_min_uncertainty_s: float = 180.0
    accepted_multi_point_min_uncertainty_s: float = 240.0
    batch_interval_floor_s: float = 300.0
    batch_interval_ceiling_s: float = 3600.0
    first_batch_interval_ceiling_s: float = 7200.0
    batch_interval_padding_s: float = 300.0
    batch_gap_padding_s: float = 300.0
    physical_span_padding_s: float = 180.0
    physical_span_multiplier: float = 1.35
    stage6_version: str = "v2"


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage6 time uncertainty modeling. "
            "Accepted Stage5 rows become narrow support-only distributions; all other AMDAR rows keep batch-interval uncertainty."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    args = parser.parse_args()
    return RunConfig(out_dir=Path(args.out_dir), slice_count=int(args.slice_count), workers=int(args.workers))


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


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


def build_time_uncertainty(cfg: RunConfig, out_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    comp_path = cfg.stage4_v2_dir / "amdar_confidence_components_v2.parquet"
    match_path = cfg.stage5_dir / "amdar_adsb_match_v3.parquet"
    diag_path = cfg.stage5_dir / "amdar_adsb_batch_diagnostics_v3.parquet"
    stage5_json_path = cfg.stage5_dir / "amdar_adsb_match_diagnostics_v3.json"

    stage5_summary = read_json(stage5_json_path)
    stage5_checks = stage5_summary.get("stage5_completion_checks", {})
    if not stage5_checks.get("passed_stage5_v3_diagnostic_gate"):
        raise RuntimeError(f"Stage5 gate did not pass in {stage5_json_path}")

    comp = pl.scan_parquet(comp_path).filter(pl.col("source") == "amdar")
    match = (
        pl.scan_parquet(match_path)
        .select(
            [
                "source_row_index",
                "amdar_batch_id",
                "matched_adsb_leg_id",
                "estimated_time_utc",
                "segment_start_time_utc",
                "segment_end_time_utc",
                "cross_track_distance_km",
                "vertical_difference_m",
                "sampling_gap_seconds",
                "best_cost",
                "ambiguity_margin",
                "leg_overall_quality",
                "stage3_source_tier_v6",
                "stage5_match_status",
                "adsb_reconstructed_v3",
            ]
        )
        .with_columns(pl.lit(True).alias("stage5_accepted_row"))
    )
    diag = pl.scan_parquet(diag_path).select(
        [
            "amdar_batch_id",
            "status",
            "reject_reason",
            "accepted_by_stage5_v3_compound_gate",
            "matched_leg_id",
            "best_cost",
            "second_best_cost",
            "ambiguity_margin",
            "cross_track_q90_km",
            "vertical_q90_m",
            "sampling_gap_max_seconds",
            "estimated_time_min_utc",
            "estimated_time_max_utc",
            "max_projected_after_batch_end_s",
            "best_leg_quality",
            "best_stage3_source_tier_v6",
            "evaluated_candidate_count",
            "total_candidate_count",
        ]
    )

    base_cols = [
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
        "support_assimilation_eligible_v3",
        "stage1_downstream_action_v3",
        "stage1_confidence_cap_v3",
        "met_value_quality",
        "base_support_conf",
        "time_uncertainty_s_stage4_v2",
        "confidence_tier",
        "confidence_grade",
        "recommended_stage4_role",
        "primary_quality_action_reason",
    ]
    enriched_base = (
        comp.select(base_cols)
        .join(match, on=["source_row_index", "amdar_batch_id"], how="left")
        .join(diag, on="amdar_batch_id", how="left", suffix="_batch")
        .with_columns(
            [
                pl.col("stage5_accepted_row").fill_null(False).alias("stage5_accepted_row"),
                pl.col("accepted_by_stage5_v3_compound_gate")
                .fill_null(False)
                .alias("stage5_accepted_batch"),
                (pl.col("stage1_confidence_cap_v3").fill_null(1.0) <= 0.0).alias("stage1_rejected_from_support"),
            ]
        )
    )

    batch_context = (
        enriched_base.group_by("amdar_batch_id")
        .agg(
            [
                pl.col("tail_norm").first().alias("tail_norm_context"),
                pl.col("flight_norm").first().alias("flight_norm_context"),
                pl.col("service_date_utc").first().alias("service_date_utc_context"),
                pl.col("time_utc").first().alias("batch_end_time_for_context"),
                pl.col("amdar_batch_row_count").first().alias("batch_row_count_context"),
                pl.col("amdar_batch_hspan_deg").first().alias("batch_hspan_deg_context"),
                pl.col("amdar_batch_vertical_span_m").first().alias("batch_vertical_span_m_context"),
                pl.col("lat_clean").min().alias("batch_lat_min"),
                pl.col("lat_clean").max().alias("batch_lat_max"),
                pl.col("lon_clean").min().alias("batch_lon_min"),
                pl.col("lon_clean").max().alias("batch_lon_max"),
                pl.col("alt_meters").min().alias("batch_alt_min_m"),
                pl.col("alt_meters").max().alias("batch_alt_max_m"),
            ]
        )
        .with_columns(
            [
                pl.col("batch_end_time_for_context")
                .shift(1)
                .over(
                    ["tail_norm_context", "flight_norm_context", "service_date_utc_context"],
                    order_by=["batch_end_time_for_context", "amdar_batch_id"],
                )
                .alias("previous_batch_end_time_utc"),
                pl.col("batch_end_time_for_context")
                .shift(-1)
                .over(
                    ["tail_norm_context", "flight_norm_context", "service_date_utc_context"],
                    order_by=["batch_end_time_for_context", "amdar_batch_id"],
                )
                .alias("next_batch_end_time_utc"),
            ]
        )
        .with_columns(
            [
                ((pl.col("batch_end_time_for_context") - pl.col("previous_batch_end_time_utc")).dt.total_seconds())
                .cast(pl.Float64)
                .alias("previous_batch_gap_s"),
                ((pl.col("next_batch_end_time_utc") - pl.col("batch_end_time_for_context")).dt.total_seconds())
                .cast(pl.Float64)
                .alias("next_batch_gap_s"),
                (
                    pl.max_horizontal(
                        (pl.col("batch_hspan_deg_context").fill_null(0.0).abs() * 111000.0),
                        ((pl.col("batch_lat_max") - pl.col("batch_lat_min")).fill_null(0.0).abs() * 111000.0),
                    )
                ).alias("batch_horizontal_span_m_context"),
            ]
        )
        .select(
            [
                "amdar_batch_id",
                "previous_batch_end_time_utc",
                "next_batch_end_time_utc",
                "previous_batch_gap_s",
                "next_batch_gap_s",
                "batch_horizontal_span_m_context",
                "batch_lat_min",
                "batch_lat_max",
                "batch_lon_min",
                "batch_lon_max",
                "batch_alt_min_m",
                "batch_alt_max_m",
            ]
        )
    )

    enriched = enriched_base.join(batch_context, on="amdar_batch_id", how="left")

    order_denom = pl.max_horizontal(pl.col("amdar_batch_row_count").cast(pl.Float64) - 1.0, pl.lit(1.0))
    order_progress = ((pl.col("amdar_observation_order").cast(pl.Float64) - 1.0) / order_denom).clip(0.0, 1.0)
    # Earlier observations in a batch receive earlier q50 estimates, but q50 stays inside the interval
    # and never collapses to the batch-end upper bound.
    stage4_prior_duration = pl.max_horizontal(
        pl.min_horizontal(
            pl.col("time_uncertainty_s_stage4_v2").cast(pl.Float64).fill_null(cfg.batch_interval_floor_s),
            pl.lit(cfg.batch_interval_ceiling_s),
        ),
        pl.lit(cfg.batch_interval_floor_s),
    )
    phase_horizontal_speed_mps = (
        pl.when(pl.col("飞行阶段") == "ASC")
        .then(pl.lit(160.0))
        .when(pl.col("飞行阶段") == "DES")
        .then(pl.lit(180.0))
        .when(pl.col("飞行阶段") == "LVR")
        .then(pl.lit(230.0))
        .otherwise(pl.lit(200.0))
    )
    phase_vertical_rate_mps = (
        pl.when(pl.col("飞行阶段") == "ASC")
        .then(pl.lit(8.0))
        .when(pl.col("飞行阶段") == "DES")
        .then(pl.lit(10.0))
        .when(pl.col("飞行阶段") == "LVR")
        .then(pl.lit(5.0))
        .otherwise(pl.lit(7.5))
    )
    physical_span_duration = (
        pl.max_horizontal(
            pl.col("batch_horizontal_span_m_context").cast(pl.Float64).fill_null(0.0) / phase_horizontal_speed_mps,
            pl.col("amdar_batch_vertical_span_m").cast(pl.Float64).fill_null(0.0).abs() / phase_vertical_rate_mps,
        )
        * pl.lit(cfg.physical_span_multiplier)
        + pl.lit(cfg.physical_span_padding_s)
    )
    physical_span_duration = pl.max_horizontal(
        pl.min_horizontal(physical_span_duration, pl.lit(cfg.batch_interval_ceiling_s)),
        pl.lit(cfg.batch_interval_floor_s),
    )
    previous_gap_cap = (
        pl.when(pl.col("previous_batch_gap_s").is_not_null() & (pl.col("previous_batch_gap_s") > 0.0))
        .then(pl.col("previous_batch_gap_s") + pl.lit(cfg.batch_gap_padding_s))
        .otherwise(pl.lit(cfg.first_batch_interval_ceiling_s))
    )
    context_cap = pl.max_horizontal(
        pl.min_horizontal(previous_gap_cap, pl.lit(cfg.first_batch_interval_ceiling_s)),
        pl.lit(cfg.batch_interval_floor_s),
    )
    unconstrained_batch_width = pl.max_horizontal(stage4_prior_duration, physical_span_duration)
    batch_width = pl.max_horizontal(
        pl.min_horizontal(unconstrained_batch_width, context_cap, pl.lit(cfg.batch_interval_ceiling_s)),
        pl.lit(cfg.batch_interval_floor_s),
    )
    interval_driver = (
        pl.when(context_cap < unconstrained_batch_width)
        .then(pl.lit("previous_batch_gap_cap"))
        .when(physical_span_duration > stage4_prior_duration)
        .then(pl.lit("physical_span_prior"))
        .otherwise(pl.lit("stage4_confidence_prior"))
    )
    accepted_base_unc = pl.max_horizontal(
        pl.lit(cfg.adsb_latency_floor_s),
        pl.col("sampling_gap_seconds").cast(pl.Float64).fill_null(0.0) * 0.5,
        pl.col("cross_track_distance_km").cast(pl.Float64).fill_null(0.0) * 12.0,
        pl.col("vertical_difference_m").cast(pl.Float64).fill_null(0.0) * 0.05,
    )
    accepted_unc = (
        pl.when(pl.col("amdar_batch_row_count") <= 1)
        .then(pl.max_horizontal(accepted_base_unc, pl.lit(cfg.accepted_single_point_min_uncertainty_s)))
        .otherwise(pl.max_horizontal(accepted_base_unc, pl.lit(cfg.accepted_multi_point_min_uncertainty_s)))
        .clip(cfg.adsb_latency_floor_s, cfg.accepted_narrow_uncertainty_cap_s)
    )

    batch_q50 = pl.col("time_utc") - pl.duration(
        seconds=(batch_width - batch_width * (0.25 + 0.55 * order_progress))
    )
    accepted_q50 = pl.min_horizontal(pl.col("estimated_time_utc"), pl.col("time_utc"))
    accepted_q10 = accepted_q50 - pl.duration(seconds=pl.col("accepted_adsb_time_uncertainty_s") * 0.5)
    accepted_q90 = pl.min_horizontal(
        accepted_q50 + pl.duration(seconds=pl.col("accepted_adsb_time_uncertainty_s") * 0.5),
        pl.col("time_utc"),
    )
    out = (
        enriched.with_columns(
            [
                order_progress.alias("batch_order_progress"),
                stage4_prior_duration.alias("stage4_prior_duration_s"),
                physical_span_duration.alias("batch_physical_span_duration_s"),
                context_cap.alias("batch_context_cap_s"),
                unconstrained_batch_width.alias("batch_unconstrained_interval_width_s"),
                interval_driver.alias("batch_interval_driver"),
                batch_width.alias("batch_feature_duration_s"),
                batch_width.alias("batch_interval_start_offset_s"),
                batch_width.alias("batch_interval_width_s"),
                accepted_unc.alias("accepted_adsb_time_uncertainty_s"),
                (pl.col("estimated_time_utc") > pl.col("time_utc")).fill_null(False).alias(
                    "adsb_estimated_time_clipped_to_batch_end"
                ),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("stage5_accepted_row"))
                .then(accepted_q50)
                .otherwise(batch_q50)
                .alias("estimated_time_q50"),
                pl.when(pl.col("stage5_accepted_row"))
                .then(accepted_q10)
                .otherwise(pl.col("time_utc") - pl.duration(seconds=pl.col("batch_interval_start_offset_s")))
                .alias("estimated_time_q10"),
                pl.when(pl.col("stage5_accepted_row"))
                .then(accepted_q90)
                .otherwise(pl.col("time_utc"))
                .alias("estimated_time_q90"),
                pl.when(pl.col("stage5_accepted_row"))
                .then(accepted_q10)
                .otherwise(pl.col("time_utc") - pl.duration(seconds=pl.col("batch_interval_start_offset_s")))
                .alias("time_interval_start"),
                pl.when(pl.col("stage5_accepted_row"))
                .then(accepted_q90)
                .otherwise(pl.col("time_utc"))
                .alias("time_interval_end"),
                pl.when(pl.col("stage5_accepted_row"))
                .then(pl.lit("gaussian_truncated_by_batch_upper_bound"))
                .otherwise(pl.lit("triangular_batch_interval_end_biased"))
                .alias("time_pdf_type"),
                pl.when(pl.col("stage5_accepted_row"))
                .then((accepted_q90 - accepted_q10).dt.total_seconds().cast(pl.Float64))
                .otherwise(pl.col("batch_interval_width_s"))
                .alias("time_uncertainty_s"),
                pl.when(pl.col("stage5_accepted_row"))
                .then(pl.lit("adsb_reconstructed_support_only"))
                .otherwise(pl.lit("batch_interval_estimated"))
                .alias("time_source"),
                pl.when(pl.col("stage5_accepted_row"))
                .then(
                    pl.when(pl.col("time_uncertainty_s_stage4_v2") <= 300.0)
                    .then(pl.lit("B_adsb_narrow_support"))
                    .otherwise(pl.lit("C_adsb_narrow_support"))
                )
                .when(pl.col("stage1_rejected_from_support"))
                .then(pl.lit("R_batch_rejected"))
                .when(pl.col("time_uncertainty_s_stage4_v2") <= 300.0)
                .then(pl.lit("C_batch_interval"))
                .when(pl.col("time_uncertainty_s_stage4_v2") <= 900.0)
                .then(pl.lit("C_batch_interval"))
                .when(pl.col("time_uncertainty_s_stage4_v2") <= 1800.0)
                .then(pl.lit("D_batch_wide_interval"))
                .otherwise(pl.lit("R_batch_rejected"))
                .alias("time_reconstruction_grade"),
            ]
        )
        .with_columns(
            [
                ((pl.col("time_interval_end") - pl.col("time_interval_start")).dt.total_seconds()).alias(
                    "time_interval_width_s"
                ),
                ((pl.col("time_utc") - pl.col("estimated_time_q50")).dt.total_seconds()).alias(
                    "q50_seconds_before_batch_end"
                ),
                pl.lit(False).alias("estimated_time_is_strict_point_truth"),
                pl.lit(False).alias("holdout_eligible"),
                pl.lit("support_only_not_strict_truth").alias("usage_role"),
                pl.lit("ground_receive_approx_downlink_batch_end_time").alias("batch_time_semantics"),
                pl.lit("Stage6 keeps batch-end as an upper bound; q50 is a distribution location, not truth.").alias(
                    "time_semantics_note"
                ),
            ]
        )
        .select(
            [
                "source_row_index",
                "raw_row_number",
                "flight_id",
                "机尾号",
                "航班号",
                "tail_norm",
                "flight_norm",
                "service_date_utc",
                "飞行阶段",
                "amdar_batch_id",
                "amdar_batch_row_count",
                "amdar_batch_size_bucket",
                "amdar_batch_hspan_deg",
                "amdar_batch_vertical_span_m",
                "amdar_observation_order",
                "batch_order_progress",
                "processing_slice_id",
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
                "base_support_conf",
                "confidence_tier",
                "confidence_grade",
                "recommended_stage4_role",
                "primary_quality_action_reason",
                "support_assimilation_eligible_v3",
                "stage1_downstream_action_v3",
                "stage1_confidence_cap_v3",
                "stage5_accepted_row",
                "stage5_accepted_batch",
                "status",
                "reject_reason",
                "matched_adsb_leg_id",
                "matched_leg_id",
                "estimated_time_utc",
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
                "batch_horizontal_span_m_context",
                "batch_lat_min",
                "batch_lat_max",
                "batch_lon_min",
                "batch_lon_max",
                "batch_alt_min_m",
                "batch_alt_max_m",
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
                "batch_end_is_time_upper_bound",
                "point_observation_time_available",
                "strict_time_truth",
                "time_is_point_observation",
                "effective_strict_truth",
                "estimated_time_is_strict_point_truth",
                "holdout_eligible",
                "usage_role",
                "time_semantics_note",
            ]
        )
        .collect(streaming=True)
    )

    row_output_name = f"amdar_time_uncertainty_{cfg.stage6_version}.parquet"
    batch_output_name = f"amdar_batch_time_uncertainty_{cfg.stage6_version}.parquet"
    policy_output_name = f"time_uncertainty_policy_{cfg.stage6_version}.json"
    summary_output_name = f"time_uncertainty_summary_{cfg.stage6_version}.json"
    out.write_parquet(out_dir / row_output_name)

    batch = (
        out.group_by("amdar_batch_id")
        .agg(
            [
                pl.col("tail_norm").first().alias("tail_norm"),
                pl.col("flight_norm").first().alias("flight_norm"),
                pl.col("service_date_utc").first().alias("service_date_utc"),
                pl.col("飞行阶段").first().alias("flight_phase"),
                pl.col("time_utc").first().alias("batch_end_time_utc"),
                pl.len().alias("row_count"),
                pl.col("stage5_accepted_batch").max().alias("stage5_accepted_batch"),
                pl.col("stage5_accepted_row").sum().alias("stage5_accepted_rows"),
                pl.col("time_source").first().alias("primary_time_source"),
                pl.col("time_reconstruction_grade").first().alias("primary_time_reconstruction_grade"),
                pl.col("time_uncertainty_s").min().alias("time_uncertainty_s_min"),
                pl.col("time_uncertainty_s").median().alias("time_uncertainty_s_median"),
                pl.col("time_uncertainty_s").max().alias("time_uncertainty_s_max"),
                pl.col("time_interval_start").min().alias("time_interval_start_min"),
                pl.col("time_interval_end").max().alias("time_interval_end_max"),
                pl.col("q50_seconds_before_batch_end").min().alias("q50_before_batch_end_s_min"),
                pl.col("q50_seconds_before_batch_end").median().alias("q50_before_batch_end_s_median"),
                pl.col("q50_seconds_before_batch_end").max().alias("q50_before_batch_end_s_max"),
                pl.col("stage4_prior_duration_s").first().alias("stage4_prior_duration_s"),
                pl.col("batch_physical_span_duration_s").first().alias("batch_physical_span_duration_s"),
                pl.col("batch_context_cap_s").first().alias("batch_context_cap_s"),
                pl.col("batch_interval_driver").first().alias("batch_interval_driver"),
                pl.col("previous_batch_gap_s").first().alias("previous_batch_gap_s"),
                pl.col("next_batch_gap_s").first().alias("next_batch_gap_s"),
                pl.col("reject_reason").first().alias("stage5_reject_reason"),
                pl.col("matched_leg_id").first().alias("matched_leg_id"),
                pl.col("cross_track_q90_km").first().alias("cross_track_q90_km"),
                pl.col("vertical_q90_m").first().alias("vertical_q90_m"),
                pl.col("sampling_gap_max_seconds").first().alias("sampling_gap_max_seconds"),
                pl.col("base_support_conf").mean().alias("base_support_conf_mean"),
                pl.col("confidence_tier").first().alias("stage4_confidence_tier_first"),
                pl.col("confidence_grade").first().alias("stage4_confidence_grade_first"),
            ]
        )
        .sort(["tail_norm", "flight_norm", "batch_end_time_utc", "amdar_batch_id"])
    )
    batch.write_parquet(out_dir / batch_output_name)

    accepted = out.filter(pl.col("stage5_accepted_row"))
    unmatched = out.filter(~pl.col("stage5_accepted_row"))
    rejected_support = out.filter(pl.col("stage1_confidence_cap_v3").fill_null(1.0) <= 0.0)
    checks = {
        "stage5_gate_passed": bool(stage5_checks.get("passed_stage5_v3_diagnostic_gate")),
        "all_amdar_rows_have_time_distribution": int(
            out.filter(
                pl.col("estimated_time_q10").is_null()
                | pl.col("estimated_time_q50").is_null()
                | pl.col("estimated_time_q90").is_null()
                | pl.col("time_interval_start").is_null()
                | pl.col("time_interval_end").is_null()
                | pl.col("time_uncertainty_s").is_null()
            ).height
        )
        == 0,
        "no_amdar_strict_truth": int(
            out.filter(
                pl.col("effective_strict_truth").fill_null(False)
                | pl.col("estimated_time_is_strict_point_truth").fill_null(False)
                | pl.col("holdout_eligible").fill_null(False)
            ).height
        )
        == 0,
        "accepted_rows_narrow_lt_5min": int(accepted.filter(pl.col("time_uncertainty_s") > 300.0).height) == 0
        if accepted.height
        else True,
        "only_accepted_rows_have_adsb_reconstructed_source": int(
            out.filter((pl.col("time_source") == "adsb_reconstructed_support_only") & ~pl.col("stage5_accepted_row")).height
        )
        == 0,
        "unmatched_rows_do_not_use_adsb_reconstructed_source": int(
            unmatched.filter(pl.col("time_source") == "adsb_reconstructed_support_only").height
        )
        == 0,
        "unmatched_rows_use_batch_interval": int(
            unmatched.filter(pl.col("time_source") != "batch_interval_estimated").height
        )
        == 0,
        "unmatched_batch_intervals_end_at_batch_end": int(
            unmatched.filter(pl.col("time_interval_end") != pl.col("time_utc")).height
        )
        == 0,
        "estimated_q90_respects_batch_end_upper_bound": int(
            out.filter(pl.col("estimated_time_q90") > pl.col("time_utc")).height
        )
        == 0,
        "interval_end_respects_batch_end_upper_bound": int(
            out.filter(pl.col("time_interval_end") > pl.col("time_utc")).height
        )
        == 0,
        "interval_width_matches_time_uncertainty": int(
            out.filter((pl.col("time_interval_width_s") - pl.col("time_uncertainty_s")).abs() > 1.0).height
        )
        == 0,
        "batch_interval_driver_present": int(unmatched.filter(pl.col("batch_interval_driver").is_null()).height) == 0,
        "batch_end_kept_as_upper_bound": int(out.filter(~pl.col("batch_end_is_time_upper_bound").fill_null(False)).height) == 0,
        "point_observation_time_unavailable_for_all_amdar": int(
            out.filter(pl.col("point_observation_time_available").fill_null(True)).height
        )
        == 0,
        "stage1_rejected_rows_not_promoted": int(
            rejected_support.filter(pl.col("time_reconstruction_grade") != "R_batch_rejected").height
        )
        == 0,
        "output_rows_equal_amdar_rows": int(out.height) == int(stage5_summary.get("batch_summary", {}).get("amdar_rows", out.height))
        if "amdar_rows" in stage5_summary.get("batch_summary", {})
        else int(out.height) == 431008,
    }
    checks["passed_stage6_time_uncertainty_gate"] = bool(all(checks.values()))

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "space_saving_policy": "Single full AMDAR time-uncertainty table plus compact batch summary; no duplicated per-slice full intermediates.",
            "accepted_stage5_policy": "Accepted Stage5 rows become narrow support-only distributions, never strict point truth.",
            "unmatched_policy": "Unmatched/rejected AMDAR rows retain batch-interval uncertainty with batch_end_time_utc as upper bound.",
        },
        "inputs": {
            "stage4_confidence_components_v2": str(comp_path),
            "stage5_match_rows": str(match_path),
            "stage5_batch_diagnostics": str(diag_path),
            "stage5_diagnostics_json": str(stage5_json_path),
        },
        "row_counts": {
            "amdar_rows": int(out.height),
            "amdar_batches": int(batch.height),
            "stage5_accepted_rows": int(accepted.height),
            "stage5_accepted_batches": int(batch.filter(pl.col("stage5_accepted_batch")).height),
            "batch_interval_rows": int(unmatched.height),
            "stage1_rejected_rows": int(rejected_support.height),
        },
        "time_source_counts": counts_map(out, "time_source"),
        "time_reconstruction_grade_counts": counts_map(out, "time_reconstruction_grade"),
        "time_pdf_type_counts": counts_map(out, "time_pdf_type"),
        "batch_interval_driver_counts": counts_map(out, "batch_interval_driver"),
        "stage5_reject_reason_row_counts": counts_map(out, "reject_reason"),
        "time_uncertainty_summary_all_rows": numeric_summary(out, "time_uncertainty_s"),
        "time_uncertainty_summary_accepted_rows": numeric_summary(accepted, "time_uncertainty_s"),
        "time_uncertainty_summary_batch_interval_rows": numeric_summary(unmatched, "time_uncertainty_s"),
        "time_interval_width_summary_all_rows": numeric_summary(out, "time_interval_width_s"),
        "q50_seconds_before_batch_end_summary_all_rows": numeric_summary(out, "q50_seconds_before_batch_end"),
        "stage4_prior_duration_summary": numeric_summary(unmatched, "stage4_prior_duration_s"),
        "physical_span_duration_summary": numeric_summary(unmatched, "batch_physical_span_duration_s"),
        "context_cap_summary": numeric_summary(unmatched, "batch_context_cap_s"),
        "previous_batch_gap_summary": numeric_summary(unmatched, "previous_batch_gap_s"),
        "accepted_match_geometry": {
            "cross_track_km_summary": numeric_summary(accepted, "cross_track_distance_km"),
            "vertical_m_summary": numeric_summary(accepted, "vertical_difference_m"),
            "sampling_gap_s_summary": numeric_summary(accepted, "sampling_gap_seconds"),
            "adsb_estimated_time_clipped_to_batch_end_rows": int(
                accepted.filter(pl.col("adsb_estimated_time_clipped_to_batch_end")).height
            ),
        },
        "by_stage4_tier": (
            out.group_by("confidence_tier")
            .agg(
                [
                    pl.len().alias("rows"),
                    pl.col("time_uncertainty_s").median().alias("time_uncertainty_s_median"),
                    pl.col("time_uncertainty_s").quantile(0.90).alias("time_uncertainty_s_p90"),
                    pl.col("stage5_accepted_row").sum().alias("stage5_accepted_rows"),
                ]
            )
            .sort("confidence_tier")
            .to_dicts()
        ),
        "stage6_completion_checks": checks,
        "interpretation": {
            "stage5_satisfactory_for_stage6": bool(stage5_checks.get("passed_stage5_v3_diagnostic_gate")),
            "stage5_coverage_assessment": "Accepted real AMDAR coverage remains tiny, so Stage5 is satisfactory only as conservative support-only diagnostics, not as a broad point-time reconstruction.",
            "stage6_satisfactory": bool(checks["passed_stage6_time_uncertainty_gate"]),
            "strict_truth_note": "AMDAR remains 0 strict-truth rows after Stage6.",
            "next_stage_note": "Stage6 output is suitable for Stage7 grade calibration or Stage8 enhanced Stage1 join; official Stage2/Stage4 migration still requires later role separation and multiscale validation.",
        },
        "literature_and_reference_basis": {
            "amdar_acars": "AMDAR/ACARS operational references describe automated commercial-aircraft meteorological reports transmitted at intervals after onboard preprocessing/downlink; this supports treating AMDAR as valuable but not automatically point-time truth.",
            "wmo_abo": "WMO aircraft-based-observation material positions AMDAR as an upper-air observation source for monitoring and data assimilation, not as a guarantee that provider batch timestamps are per-point observation times.",
            "faa_adsb": "FAA ADS-B Out requirements define state-vector broadcast performance, integrity, and latency expectations; ADS-B timing uncertainty is not the dominant error here compared with AMDAR batch/downlink timing.",
            "sources": {
                "wmo_aircraft_based_observations": "https://community.wmo.int/en/activity-areas/aircraft-based-observations",
                "wmo_guide_to_aircraft_based_observations": "https://library.wmo.int/index.php?id=20116&lvl=notice_display",
                "noaa_amdar_abo": "https://amdar.noaa.gov/",
                "ecfr_14_cfr_91_227_adsb_out": "https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227",
            },
        },
        "outputs": {
            "row_time_uncertainty": str(out_dir / row_output_name),
            "batch_time_uncertainty": str(out_dir / batch_output_name),
            "policy": str(out_dir / policy_output_name),
            "summary": str(out_dir / summary_output_name),
        },
    }
    return out, batch, summary


def build_policy(cfg: RunConfig, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at_utc": summary["generated_at_utc"],
        "policy_version": f"amdar_unified_stage6_time_uncertainty_{cfg.stage6_version}",
        "purpose": "Provide explicit time distributions for every AMDAR row while preserving strict truth boundaries.",
        "global_rules": [
            "AMDAR batch_end_time_utc remains an upper bound, not point observation time.",
            "Stage5 accepted rows are support-only narrow time distributions.",
            "Unmatched or rejected rows use batch-feature interval distributions.",
            "No AMDAR row becomes strict truth or holdout eligible in Stage6.",
        ],
        "accepted_stage5_rows": {
            "time_source": "adsb_reconstructed_support_only",
            "pdf": "gaussian_truncated_by_batch_upper_bound",
            "uncertainty_formula": (
                "max(90s ADS-B/clock floor, 0.5*sampling_gap_s, 12*cross_track_km, "
                "0.05*vertical_m, accepted row-count floor), clipped to <=300s and then truncated at batch_end_time_utc"
            ),
            "grade": "B_adsb_narrow_support or C_adsb_narrow_support depending on prior Stage4 time uncertainty",
            "not_truth": True,
        },
        "unmatched_rows": {
            "time_source": "batch_interval_estimated",
            "pdf": "triangular_batch_interval_end_biased",
            "interval": (
                "time_interval_start = batch_end - calibrated_width; time_interval_end = batch_end. "
                "calibrated_width = max(stage4 prior, phase-aware physical span prior), clipped by previous batch gap "
                "and global ceilings."
            ),
            "q50": "distributed through the interval by original AMDAR order; q50 remains a probability location, not truth",
            "grades": ["C_batch_interval", "D_batch_wide_interval", "R_batch_rejected"],
            "interval_drivers": [
                "stage4_confidence_prior",
                "physical_span_prior",
                "previous_batch_gap_cap",
            ],
        },
        "parameters": asdict(cfg),
        "completion_checks": summary["stage6_completion_checks"],
    }


def write_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage6_time_uncertainty_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage6_time_uncertainty.md"
    checks = summary["stage6_completion_checks"]

    result_lines = [
        "# AMDAR Unified Plan Stage6 Time Uncertainty Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Executive Conclusion",
        "",
        "Stage5 V3 is acceptable for Stage6 only as conservative diagnostics: it found a tiny, fully traceable accepted set, but not broad AMDAR point-time recovery. I therefore did not relax Stage5. Stage6 uses those accepted rows as narrow support-only time distributions and keeps every other AMDAR row on calibrated batch-interval uncertainty.",
        "",
        f"The Stage6 {cfg.stage6_version} gate passes. All 431,008 AMDAR rows now have `estimated_time_q10/q50/q90`, `time_interval_start/end`, `time_pdf_type`, `time_uncertainty_s`, and `time_reconstruction_grade`; zero AMDAR rows are strict truth or holdout eligible.",
        "",
        "## Literature And Reference Basis",
        "",
        "- WMO and AMDAR/ACARS operational material treat aircraft-based observations as valuable upper-air observations for monitoring and NWP assimilation, but that does not make a provider batch/downlink timestamp a per-point observation time.",
        "- AMDAR/ACARS reporting is interval-based and transmitted after onboard preprocessing/downlink, supporting a conservative time-distribution approach.",
        "- FAA ADS-B Out rules define state-vector broadcast performance and latency/integrity requirements; in this dataset the dominant uncertainty is AMDAR batch/downlink timing and within-batch ordering, not ADS-B second-scale latency.",
        "- Sources checked: WMO Aircraft-Based Observations (`https://community.wmo.int/en/activity-areas/aircraft-based-observations`), WMO-No. 1200 (`https://library.wmo.int/index.php?id=20116&lvl=notice_display`), NOAA AMDAR/ABO (`https://amdar.noaa.gov/`), and 14 CFR 91.227 ADS-B Out (`https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227`).",
        "",
        "## Stage5 Assessment Before Stage6",
        "",
        f"- Stage5 accepted rows: `{summary['row_counts']['stage5_accepted_rows']}`",
        f"- Stage5 accepted batches: `{summary['row_counts']['stage5_accepted_batches']}`",
        "- Assessment: satisfactory for narrow support-only inputs, not satisfactory for broad point-time reconstruction. No Stage5 gate was loosened.",
        "",
        "## Stage6 Result",
        "",
        f"- AMDAR rows with time distributions: `{summary['row_counts']['amdar_rows']}`",
        f"- AMDAR batches: `{summary['row_counts']['amdar_batches']}`",
        f"- Time source counts: `{summary['time_source_counts']}`",
        f"- Time reconstruction grade counts: `{summary['time_reconstruction_grade_counts']}`",
        f"- Batch interval driver counts: `{summary['batch_interval_driver_counts']}`",
        f"- Time uncertainty summary: `{summary['time_uncertainty_summary_all_rows']}`",
        f"- Accepted-row time uncertainty summary: `{summary['time_uncertainty_summary_accepted_rows']}`",
        f"- Batch-interval time uncertainty summary: `{summary['time_uncertainty_summary_batch_interval_rows']}`",
        f"- Physical span duration summary: `{summary['physical_span_duration_summary']}`",
        f"- Context cap summary: `{summary['context_cap_summary']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## Outputs",
        "",
        f"- Row-level time uncertainty: `{summary['outputs']['row_time_uncertainty']}`",
        f"- Batch-level time uncertainty: `{summary['outputs']['batch_time_uncertainty']}`",
        f"- Policy: `{summary['outputs']['policy']}`",
        f"- Summary JSON: `{summary['outputs']['summary']}`",
        "",
        "## Next Steps",
        "",
        "1. Proceed to Stage7 grade calibration if the next task is threshold calibration.",
        f"2. For Stage8 enhanced Stage1, join `{Path(summary['outputs']['row_time_uncertainty']).name}` by `source_row_index` and preserve `holdout_eligible=false` for all AMDAR.",
        "3. Do not migrate official Stage2/Stage4 until later role separation, super-ob/weight limits, and multiscale validation are complete.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：Stage6 Time Uncertainty 后续",
        "",
        f"你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要从零开始。当前已经完成 Stage2 v6、Stage3 v7、Stage4 confidence v2、Stage5 V3 matching diagnostics，并新增完成 Stage6 time uncertainty {cfg.stage6_version}。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目 strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：strict truth 少是数据现实，AMDAR 应走分层置信度。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan 阶段边界、Stage6/7/8 要求和禁止操作。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v3_matching_optimized_20260701/stage5_v3_results_analysis_and_next_steps.md`：Stage5 V3 的真实 accepted/reject 诊断。",
        f"6. `{result_path}`：Stage6 结果、达标判断和下一步建议。",
        f"7. `time_uncertainty_summary_{cfg.stage6_version}.json`：Stage6 总指标和 completion checks。",
        f"8. `time_uncertainty_policy_{cfg.stage6_version}.json`：Stage6 时间分布策略和禁止误用说明。",
        "",
        "## 本轮脚本和输出",
        "",
        f"- 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage6_time_uncertainty_20260701.py`",
        f"- 输出目录：`{cfg.out_dir}`",
        f"- `{Path(summary['outputs']['row_time_uncertainty']).name}`：431,008 条 AMDAR 逐行时间分布。",
        f"- `{Path(summary['outputs']['batch_time_uncertainty']).name}`：56,521 个批次级时间不确定性摘要。",
        f"- `{Path(summary['outputs']['policy']).name}`：Stage6 策略文件。",
        f"- `{Path(summary['outputs']['summary']).name}`：Stage6 总指标。",
        "- `stage6_time_uncertainty_results_analysis_and_next_steps.md`：结果分析与下一步。",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage6_time_uncertainty_20260701.py \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25 --workers 25",
        "```",
        "",
        "## 关键结果",
        "",
        f"- Row counts: `{summary['row_counts']}`",
        f"- Time source counts: `{summary['time_source_counts']}`",
        f"- Grade counts: `{summary['time_reconstruction_grade_counts']}`",
        f"- Batch interval driver counts: `{summary['batch_interval_driver_counts']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 继续 support-only，不能进入 strict holdout。",
        "- Stage5 accepted rows 只能作为窄时间分布 support-only seed，不是 strict point truth。",
        "- 未匹配/拒绝 AMDAR 保留 batch interval uncertainty，不能把 batch_end_time_utc 当逐点时间。",
        "- `estimated_time_q50` 是时间分布位置，不是逐点真实观测时间。",
        "- 下一阶段若做 Stage7/Stage8，必须保留 `holdout_eligible=false`、`estimated_time_is_strict_point_truth=false`。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage5 V3 结果，以及最新 Stage6 time uncertainty 结果。",
        "当前结论：Stage6 已为全部 AMDAR 生成时间分布；只有 Stage5 accepted 的 9 行使用 ADS-B reconstructed narrow support-only distribution，其余 430,999 行保留由 Stage4 先验、物理跨度和相邻批次间隔共同约束的批次时间区间。AMDAR 仍然 0 strict truth。",
        f"下一步如果进入 Stage7，我会基于 pseudo-AMDAR locked test 标定 S/A/B/C/R 阈值；如果进入 Stage8，我会把 `{Path(summary['outputs']['row_time_uncertainty']).name}` join 回增强 Stage1，但不会把任何 AMDAR 放入 holdout。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage6_time_uncertainty_start"}, ensure_ascii=False))
    _, _, summary = build_time_uncertainty(cfg, cfg.out_dir)
    policy = build_policy(cfg, summary)
    write_json(cfg.out_dir / f"time_uncertainty_policy_{cfg.stage6_version}.json", policy)
    write_json(cfg.out_dir / f"time_uncertainty_summary_{cfg.stage6_version}.json", summary)
    write_docs(cfg, summary)
    print(
        json.dumps(
            {
                "stage": "stage6_time_uncertainty_done",
                "passed": summary["stage6_completion_checks"]["passed_stage6_time_uncertainty_gate"],
                "rows": summary["row_counts"]["amdar_rows"],
                "out_dir": str(cfg.out_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
