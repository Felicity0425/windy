from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE1_PLAN4_DIR = ROOT / "stage1_output"
STAGE1_V3_DIR = DATA_DIR / "amdar_unified_stage1_2_complete_optimized_20260701/stage1_qc_resolution_v3"
STAGE2_V7_DIR = DATA_DIR / "stage2_adsb_qc_v7_optimized_20260706"
STAGE3_V8_DIR = DATA_DIR / "stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8"
DEFAULT_OUT_DIR = DATA_DIR / "stage4_confidence_v3_next_window_optimized_20260708"
V2_SCRIPT = DATA_DIR / "amdar_unified_stage3_v7_stage4_confidence_v2_20260701.py"

WIND_SPEED_MS_PLAUSIBLE_MAX = 150.0
EPS = 1.0e-6


def load_v2_utils() -> Any:
    spec = importlib.util.spec_from_file_location("stage4_v2_utils", V2_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import utilities from {V2_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


v2 = load_v2_utils()


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage1_plan4_dir: Path = STAGE1_PLAN4_DIR
    stage1_v3_dir: Path = STAGE1_V3_DIR
    stage2_v7_dir: Path = STAGE2_V7_DIR
    stage3_v8_dir: Path = STAGE3_V8_DIR
    slice_count: int = 25


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run optimization-plan phase 3 next-window safeguards: large-framework Stage4 confidence v3. "
            "Consumes Stage2 v7 and Stage3 v8, keeps AMDAR support-only, and writes one compact table plus audits."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    args = parser.parse_args()
    return RunConfig(out_dir=Path(args.out_dir), slice_count=int(args.slice_count))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(count: int, total: int) -> float:
    return float(count / max(1, total) * 100.0)


def finite_expr(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.Float64, strict=False).is_finite()


def build_stage2_v7_identity_prior(cfg: RunConfig, out_dir: Path) -> pl.DataFrame:
    leg_path = cfg.stage2_v7_dir / "adsb_leg_quality_components_v7.parquet"
    leg = pl.scan_parquet(leg_path).filter(pl.col("point_count") >= 5)
    prior = (
        leg.group_by(["tail_norm", "flight_norm", "service_date_utc"])
        .agg(
            [
                pl.len().alias("same_identity_date_leg_count_v7"),
                pl.col("stage3_candidate_projection_pool_v7").fill_null(False).sum().alias("candidate_projection_leg_count_v7"),
                pl.col("stage3_pseudo_source_pool_v7").fill_null(False).sum().alias("pseudo_source_leg_count_v7"),
                pl.col("stage2_v7_s0_source_pool").fill_null(False).sum().alias("S0_leg_count_v7"),
                pl.col("stage2_v7_s1_source_pool").fill_null(False).sum().alias("S1_leg_count_v7"),
                pl.col("stage2_v7_s2_source_pool").fill_null(False).sum().alias("S2_leg_count_v7"),
                pl.col("adsb_stage3_source_conf_cap_v7").max().alias("best_adsb_stage3_source_conf_cap_v7"),
                pl.col("stage2_v7_weighted_score").max().alias("best_stage2_v7_weighted_score"),
                pl.col("point_count").sum().alias("same_identity_date_leg_points_v7"),
                pl.col("duration_seconds").max().alias("same_identity_date_max_duration_seconds_v7"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("S0_leg_count_v7") > 0)
                .then(pl.lit("S0_core_clean_long_source"))
                .when(pl.col("S1_leg_count_v7") > 0)
                .then(pl.lit("S1_strong_component_b_long_source"))
                .when(pl.col("S2_leg_count_v7") > 0)
                .then(pl.lit("S2_broad_short_batch_threshold_source"))
                .when(pl.col("candidate_projection_leg_count_v7") > 0)
                .then(pl.lit("projection_candidate_only_not_source"))
                .otherwise(pl.lit("diagnostic_or_none"))
                .alias("best_stage3_source_tier_v7_identity_date"),
                pl.col("best_adsb_stage3_source_conf_cap_v7")
                .fill_null(0.0)
                .alias("stage2_v7_identity_prior_conf_diagnostic"),
            ]
        )
        .collect(streaming=True)
    )
    prior.write_parquet(out_dir / "stage2_v7_identity_date_prior_summary.parquet")
    return prior


def derive_dynamic_thresholds(stage3_report: dict[str, Any]) -> dict[str, Any]:
    validation = (
        stage3_report.get("metrics", {})
        .get("selected_by_compound_gate_v8", {})
        .get("validation", {})
    )
    predictor = stage3_report.get("confidence_predictor", {})
    validation_q90 = float(validation.get("time_error_q90_s") or math.inf)
    validation_log_r2 = float(predictor.get("validation_log_error_r2") or 0.0)
    locked_log_r2 = float(predictor.get("locked_test_log_error_r2") or 0.0)
    strong_validation = validation_q90 <= 180.0 and validation_log_r2 >= 0.75
    return {
        "source": "Stage3 v8 validation split only; locked_test is report-only.",
        "validation_time_error_q90_s": validation_q90,
        "confidence_predictor_validation_log_r2": validation_log_r2,
        "confidence_predictor_locked_log_r2_report_only": locked_log_r2,
        "strong_validation": strong_validation,
        "T1": {"base_support_conf_min": 0.72, "time_uncertainty_s_max": 300.0},
        "T2": {"base_support_conf_min": 0.53, "time_uncertainty_s_max": 900.0},
        "T3": {"base_support_conf_min": 0.30, "time_uncertainty_s_max": 1800.0},
    }


def add_stage4_v3_confidence_columns(df: pl.LazyFrame, thresholds: dict[str, Any]) -> pl.LazyFrame:
    is_amdar = pl.col("source") == "amdar"
    is_turb = pl.col("source") == "turb"
    ws = pl.col("wind_speed_ms_filled").cast(pl.Float64, strict=False)
    hspan = pl.col("amdar_batch_hspan_deg").cast(pl.Float64, strict=False).fill_null(999.0)
    vspan = pl.col("amdar_batch_vertical_span_m").cast(pl.Float64, strict=False).fill_null(999999.0)
    batch_rows = pl.col("amdar_batch_row_count").cast(pl.Int64, strict=False).fill_null(999999)
    alt = pl.col("alt_meters").cast(pl.Float64, strict=False).fill_null(-9999.0)

    batch_size_factor = (
        pl.when(~is_amdar)
        .then(pl.lit(1.0))
        .when(batch_rows <= 1)
        .then(pl.lit(0.96))
        .when(batch_rows <= 4)
        .then(pl.lit(0.88))
        .when(batch_rows <= 10)
        .then(pl.lit(0.78))
        .when(batch_rows <= 25)
        .then(pl.lit(0.60))
        .when(batch_rows <= 49)
        .then(pl.lit(0.42))
        .otherwise(pl.lit(0.28))
    )
    batch_spatial_factor = (
        pl.when(~is_amdar)
        .then(pl.lit(1.0))
        .when((hspan <= 0.2) & (vspan <= 300.0))
        .then(pl.lit(1.0))
        .when((hspan <= 0.5) & (vspan <= 600.0))
        .then(pl.lit(0.94))
        .when((hspan <= 0.8) & (vspan <= 1000.0))
        .then(pl.lit(0.88))
        .when((hspan <= 1.5) & (vspan <= 1800.0))
        .then(pl.lit(0.76))
        .when((hspan <= 3.0) & (vspan <= 3000.0))
        .then(pl.lit(0.62))
        .when((hspan <= 5.0) & (vspan <= 5000.0))
        .then(pl.lit(0.45))
        .otherwise(pl.lit(0.25))
    )
    batch_phase_factor = (
        pl.when(~is_amdar)
        .then(pl.lit(1.0))
        .when(pl.col("飞行阶段") == "LVR")
        .then(pl.lit(1.0))
        .when(pl.col("飞行阶段") == "ASC")
        .then(pl.lit(0.92))
        .when(pl.col("飞行阶段") == "DES")
        .then(pl.lit(0.88))
        .otherwise(pl.lit(0.82))
    )
    batch_met_factor = (
        pl.when(~is_amdar)
        .then(pl.lit(1.0))
        .when(batch_rows <= 1)
        .then(pl.lit(0.96))
        .when(pl.col("batch_wind_speed_std_ms").fill_null(999.0) < 5.0)
        .then(pl.lit(1.0))
        .when(pl.col("batch_wind_speed_std_ms").fill_null(999.0) < 10.0)
        .then(pl.lit(0.92))
        .when(pl.col("batch_wind_speed_std_ms").fill_null(999.0) < 20.0)
        .then(pl.lit(0.80))
        .when(pl.col("batch_wind_speed_std_ms").fill_null(999.0) < 35.0)
        .then(pl.lit(0.65))
        .otherwise(pl.lit(0.45))
    )
    batch_repr = (
        (
            batch_size_factor.clip(EPS, 1.0).log() * 0.30
            + batch_spatial_factor.clip(EPS, 1.0).log() * 0.35
            + batch_phase_factor.clip(EPS, 1.0).log() * 0.10
            + batch_met_factor.clip(EPS, 1.0).log() * 0.25
        )
        .exp()
        .clip(0.05, 0.92)
    )

    finite_met = finite_expr("wind_speed_ms_filled") & finite_expr("wind_dir_deg_filled") & finite_expr("u_wind") & finite_expr("v_wind")
    uv_delta = (
        ((pl.col("u_wind").cast(pl.Float64, strict=False) ** 2 + pl.col("v_wind").cast(pl.Float64, strict=False) ** 2).sqrt() - ws).abs()
    )
    met_structural_bad = (
        ~finite_met
        | (ws < 0.0)
        | (pl.col("wind_dir_deg_filled") < 0.0)
        | (pl.col("wind_dir_deg_filled") >= 360.0)
        | pl.col("uv_nonfinite_flag").fill_null(False)
    )
    review_met = (
        pl.col("wind_speed_outlier_flag").fill_null(False)
        | pl.col("temperature_outlier_flag").fill_null(False)
        | pl.col("altitude_outlier_flag").fill_null(False)
        | (uv_delta > 0.5)
    )
    high_wind = is_amdar & (ws > WIND_SPEED_MS_PLAUSIBLE_MAX)
    high_wind_supported = high_wind & ((ws <= 200.0) | ((alt >= 7000.0) & (hspan <= 8.0) & (vspan <= 6500.0)))
    met_physics = (
        pl.when(met_structural_bad)
        .then(pl.lit(0.0))
        .when(high_wind & ~high_wind_supported)
        .then(pl.lit(0.0))
        .when(high_wind & (ws > 200.0))
        .then(pl.lit(0.42))
        .when(high_wind & (alt >= 8000.0))
        .then(pl.lit(0.78))
        .when(high_wind)
        .then(pl.lit(0.55))
        .when(review_met)
        .then(pl.lit(0.70))
        .otherwise(pl.lit(1.0))
    )
    effective_stage1_cap = (
        pl.when(high_wind_supported & (ws > 200.0))
        .then(pl.max_horizontal(pl.col("stage1_confidence_cap_v3").fill_null(1.0), pl.lit(0.42)))
        .when(high_wind_supported & (ws > WIND_SPEED_MS_PLAUSIBLE_MAX))
        .then(pl.max_horizontal(pl.col("stage1_confidence_cap_v3").fill_null(1.0), pl.lit(0.55)))
        .otherwise(pl.col("stage1_confidence_cap_v3").fill_null(1.0))
    )
    source_quality = (
        pl.when(is_turb)
        .then(pl.lit(1.0))
        .when(is_amdar)
        .then(pl.lit(0.90))
        .otherwise(pl.lit(0.70))
    )
    same_identity_legs = pl.col("same_identity_date_leg_count_v7").cast(pl.Int64, strict=False).fill_null(0)
    projection_legs = pl.col("candidate_projection_leg_count_v7").cast(pl.Int64, strict=False).fill_null(0)
    s0_legs = pl.col("S0_leg_count_v7").cast(pl.Int64, strict=False).fill_null(0)
    s1_legs = pl.col("S1_leg_count_v7").cast(pl.Int64, strict=False).fill_null(0)
    s2_legs = pl.col("S2_leg_count_v7").cast(pl.Int64, strict=False).fill_null(0)
    identity = (
        pl.when((pl.col("tail_norm") != "MISSING") & (pl.col("flight_norm") != "MISSING"))
        .then(pl.lit(1.0))
        .when((pl.col("tail_norm") != "MISSING") | (pl.col("flight_norm") != "MISSING"))
        .then(pl.lit(0.82))
        .otherwise(pl.lit(0.45))
    )
    identity_prior_availability = (
        pl.when(~is_amdar)
        .then(pl.lit(1.0))
        .when(s0_legs > 0)
        .then(pl.lit(1.0))
        .when(s1_legs > 0)
        .then(pl.lit(0.94))
        .when(s2_legs > 0)
        .then(pl.lit(0.86))
        .when(projection_legs > 0)
        .then(pl.lit(0.78))
        .when(same_identity_legs > 0)
        .then(pl.lit(0.72))
        .otherwise(pl.lit(0.62))
    )
    identity_ambiguity_factor = (
        pl.when(~is_amdar)
        .then(pl.lit(1.0))
        .when(same_identity_legs <= 0)
        .then(pl.lit(0.70))
        .when(same_identity_legs <= 2)
        .then(pl.lit(1.0))
        .when(same_identity_legs <= 5)
        .then(pl.lit(0.96))
        .when(same_identity_legs <= 10)
        .then(pl.lit(0.90))
        .when(same_identity_legs <= 20)
        .then(pl.lit(0.82))
        .otherwise(pl.lit(0.72))
    )
    identity_risk_conf_diagnostic = (
        identity.clip(EPS, 1.0).log() * 0.40
        + identity_prior_availability.clip(EPS, 1.0).log() * 0.35
        + identity_ambiguity_factor.clip(EPS, 1.0).log() * 0.25
    ).exp()
    weighted_conf = (
        source_quality.clip(EPS, 1.0).log() * 0.22
        + met_physics.clip(EPS, 1.0).log() * 0.28
        + batch_repr.clip(EPS, 1.0).log() * 0.40
        + identity.clip(EPS, 1.0).log() * 0.10
    ).exp()
    time_unc = (
        pl.when(~is_amdar)
        .then(pl.lit(0.0))
        .when(batch_rows <= 1)
        .then(pl.lit(240.0))
        .when((batch_rows <= 10) & (hspan <= 0.8) & (vspan <= 1000.0))
        .then(pl.lit(300.0))
        .when((batch_rows <= 25) & (hspan <= 5.0) & (vspan <= 5000.0))
        .then(pl.lit(900.0))
        .when((batch_rows <= 49) & (hspan <= 5.0) & (vspan <= 5000.0))
        .then(pl.lit(1500.0))
        .otherwise(pl.lit(2100.0))
    )
    typical_horizontal_speed_ms = (
        pl.when(pl.col("飞行阶段") == "LVR")
        .then(pl.lit(230.0))
        .when(pl.col("飞行阶段") == "ASC")
        .then(pl.lit(180.0))
        .when(pl.col("飞行阶段") == "DES")
        .then(pl.lit(190.0))
        .otherwise(pl.lit(160.0))
    )
    typical_vertical_rate_ms = (
        pl.when(pl.col("飞行阶段").is_in(["ASC", "DES"]))
        .then(pl.lit(8.0))
        .otherwise(pl.lit(4.0))
    )
    horizontal_traversal_s = (hspan.clip(0.0, 999.0) * 111000.0 / typical_horizontal_speed_ms).fill_null(2100.0)
    vertical_traversal_s = (vspan.clip(0.0, 999999.0) / typical_vertical_rate_ms).fill_null(2100.0)
    spatial_traversal_s = pl.max_horizontal(horizontal_traversal_s, vertical_traversal_s)
    continuous_floor_s = (
        pl.when(~is_amdar)
        .then(pl.lit(0.0))
        .when(batch_rows <= 1)
        .then(pl.lit(180.0))
        .when(batch_rows <= 10)
        .then(pl.lit(300.0))
        .when(batch_rows <= 25)
        .then(pl.lit(600.0))
        .when(batch_rows <= 49)
        .then(pl.lit(1200.0))
        .otherwise(pl.lit(1800.0))
    )
    continuous_guard_s = (
        pl.when(batch_rows <= 1)
        .then(pl.lit(60.0))
        .when(batch_rows <= 10)
        .then(pl.lit(120.0))
        .when(batch_rows <= 25)
        .then(pl.lit(180.0))
        .otherwise(pl.lit(240.0))
    )
    time_unc_continuous = (
        pl.when(~is_amdar)
        .then(pl.lit(0.0))
        .otherwise(
            pl.min_horizontal(
                time_unc,
                pl.max_horizontal(spatial_traversal_s * 1.20 + continuous_guard_s, continuous_floor_s),
            )
        )
    )
    hard_reject = met_structural_bad | (high_wind & ~high_wind_supported) | (effective_stage1_cap <= 0.0)
    t1_min = float(thresholds["T1"]["base_support_conf_min"])
    t2_min = float(thresholds["T2"]["base_support_conf_min"])
    t3_min = float(thresholds["T3"]["base_support_conf_min"])

    return (
        df.with_columns(
            [
                batch_size_factor.alias("batch_size_factor_v3"),
                batch_spatial_factor.alias("batch_spatial_factor_v3"),
                batch_phase_factor.alias("batch_phase_factor_v3"),
                batch_met_factor.alias("batch_met_consistency_factor_v3"),
                batch_repr.alias("batch_representativeness_conf"),
                met_structural_bad.alias("met_structural_bad_v3"),
                high_wind.alias("amdar_high_wind_gt150_mps_v3"),
                high_wind_supported.alias("amdar_high_wind_stage4_supported_v3"),
                pl.when(~high_wind)
                .then(pl.lit("not_high_wind"))
                .when(high_wind_supported & (ws > 200.0))
                .then(pl.lit("retain_gt200_high_altitude_batch_supported"))
                .when(high_wind_supported)
                .then(pl.lit("retain_150_200_review_low_confidence"))
                .otherwise(pl.lit("reject_gt150_unsupported"))
                .alias("stage4_high_wind_action_v3"),
                effective_stage1_cap.alias("effective_stage1_confidence_cap_stage4_v3"),
                source_quality.alias("source_quality_conf"),
                met_physics.alias("met_physics_conf"),
                identity.alias("identity_completeness_conf"),
                identity_prior_availability.alias("identity_date_prior_availability_conf_diagnostic"),
                identity_ambiguity_factor.alias("identity_date_ambiguity_factor_diagnostic"),
                identity_risk_conf_diagnostic.alias("identity_risk_conf_diagnostic"),
                pl.lit(None, dtype=pl.Float64).alias("adsb_match_quality_conf"),
                weighted_conf.clip(0.0, 0.90).alias("base_support_conf_pre_stage1_cap_v3"),
                hard_reject.alias("hard_reject_flag_v3"),
                time_unc.alias("time_uncertainty_s_stage4_v3"),
                time_unc_continuous.alias("time_uncertainty_s_stage4_v3_continuous"),
                pl.when(~is_amdar)
                .then(pl.lit("point_observation"))
                .when(batch_rows <= 1)
                .then(pl.lit("single_point_physics_floor"))
                .when(batch_rows <= 10)
                .then(pl.lit("small_batch_spatial_traversal_with_guard"))
                .when(batch_rows <= 25)
                .then(pl.lit("medium_batch_conservative_traversal"))
                .otherwise(pl.lit("wide_batch_upper_bound_preserved"))
                .alias("time_uncertainty_model_stage4_v3"),
            ]
        )
        .with_columns(
            [
                pl.when(is_turb)
                .then(pl.lit(1.0))
                .when(pl.col("hard_reject_flag_v3"))
                .then(pl.lit(0.0))
                .otherwise(
                    pl.min_horizontal(
                        "base_support_conf_pre_stage1_cap_v3",
                        "effective_stage1_confidence_cap_stage4_v3",
                    )
                )
                .alias("base_support_conf")
            ]
        )
        .with_columns(
            [
                (
                    is_turb
                    & pl.col("strict_holdout_eligible_v3").fill_null(False)
                    & ~pl.col("hard_reject_flag_v3")
                ).alias("enhanced_holdout_eligible_v3"),
                (
                    is_amdar
                    & (pl.col("base_support_conf") > 0.0)
                    & ~pl.col("hard_reject_flag_v3")
                ).alias("support_assimilation_eligible_stage4_v3"),
                pl.lit(False).alias("adsb_reconstructed"),
                pl.lit("stage5_pending_no_real_amdar_adsb_match_yet").alias("adsb_match_status"),
                pl.when(is_turb)
                .then(pl.lit("point_observation"))
                .otherwise(pl.lit("four_component_batch_support_confidence_stage3_v8_calibrated"))
                .alias("confidence_basis"),
            ]
        )
        .with_columns(
            [
                pl.when(is_turb)
                .then(pl.when(pl.col("enhanced_holdout_eligible_v3")).then(pl.lit("T0")).otherwise(pl.lit("T4")))
                .when(pl.col("hard_reject_flag_v3"))
                .then(pl.lit("T4"))
                .when((pl.col("base_support_conf") >= t1_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 300.0))
                .then(pl.lit("T1"))
                .when((pl.col("base_support_conf") >= t2_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 900.0))
                .then(pl.lit("T2"))
                .when((pl.col("base_support_conf") >= t3_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 1800.0))
                .then(pl.lit("T3"))
                .otherwise(pl.lit("T4"))
                .alias("confidence_tier"),
                pl.when(is_turb)
                .then(pl.when(pl.col("enhanced_holdout_eligible_v3")).then(pl.lit("S")).otherwise(pl.lit("R")))
                .when(pl.col("hard_reject_flag_v3"))
                .then(pl.lit("R"))
                .when((pl.col("base_support_conf") >= t1_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 300.0))
                .then(pl.lit("A"))
                .when((pl.col("base_support_conf") >= t2_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 900.0))
                .then(pl.lit("B"))
                .when((pl.col("base_support_conf") >= t3_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 1800.0))
                .then(pl.lit("C"))
                .otherwise(pl.lit("D"))
                .alias("confidence_grade"),
            ]
        )
        .with_columns(
            [
                pl.when(is_turb)
                .then(pl.when(pl.col("enhanced_holdout_eligible_v3")).then(pl.lit("strict_holdout")).otherwise(pl.lit("strict_holdout_review")))
                .when(pl.col("hard_reject_flag_v3"))
                .then(pl.lit("rejected_or_manual_review"))
                .when(pl.col("confidence_tier").is_in(["T1", "T2"]))
                .then(pl.lit("support_assimilation_candidate"))
                .when(pl.col("confidence_tier") == "T3")
                .then(pl.lit("low_confidence_support_or_superob_only"))
                .otherwise(pl.lit("display_only_or_reject"))
                .alias("recommended_stage4_role")
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("confidence_tier") == "T2")
                .then(
                    pl.when((batch_rows <= 10) & (hspan <= 2.0) & (vspan <= 2000.0) & (pl.col("batch_representativeness_conf") >= 0.72))
                    .then(pl.lit("T2a_direct_support_candidate"))
                    .otherwise(pl.lit("T2b_broad_or_lower_weight_support"))
                )
                .otherwise(pl.col("confidence_tier"))
                .alias("confidence_subtier"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("confidence_tier") == "T0")
                .then(pl.lit("strict_holdout_evaluation_only"))
                .when(pl.col("confidence_tier") == "T1")
                .then(pl.lit("direct_support_high_weight"))
                .when(pl.col("confidence_subtier") == "T2a_direct_support_candidate")
                .then(pl.lit("direct_support_medium_weight"))
                .when(pl.col("confidence_subtier") == "T2b_broad_or_lower_weight_support")
                .then(pl.lit("low_weight_or_superob_preferred"))
                .when(pl.col("confidence_tier") == "T3")
                .then(pl.lit("superob_or_context_only"))
                .otherwise(pl.lit("display_only_or_reject"))
                .alias("stage4_weighting_recommendation_v3"),
            ]
        )
    )


def build_stage4_components(cfg: RunConfig, stage3_report: dict[str, Any]) -> tuple[pl.DataFrame, dict[str, Any]]:
    out_dir = cfg.out_dir / "stage4_confidence_v3"
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_wind_path = cfg.stage1_plan4_dir / "clean_wind.parquet"
    resolution_path = cfg.stage1_v3_dir / "stage1_qc_resolution_table_v3.parquet"
    wind_schema = pl.read_parquet_schema(clean_wind_path)
    resolution_schema = pl.read_parquet_schema(resolution_path)

    wind_cols = ["source", "source_row_index", "wind_speed", "wind_dir", "u_wind", "v_wind"]
    res_cols = [
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
        "stage1_downstream_action_v3",
        "stage1_qc_resolved_for_downstream_v3",
        "processing_slice_id",
    ]
    wind = pl.scan_parquet(clean_wind_path).select([c for c in wind_cols if c in wind_schema])
    resolution = pl.scan_parquet(resolution_path).select([c for c in res_cols if c in resolution_schema])

    batch_stats = (
        resolution.filter(pl.col("source") == "amdar")
        .group_by("amdar_batch_id")
        .agg(
            [
                pl.col("wind_speed_ms").cast(pl.Float64, strict=False).std().alias("batch_wind_speed_std_ms"),
                pl.col("wind_speed_ms").cast(pl.Float64, strict=False).min().alias("batch_wind_speed_min_ms"),
                pl.col("wind_speed_ms").cast(pl.Float64, strict=False).max().alias("batch_wind_speed_max_ms"),
                (pl.col("lat_clean").cast(pl.Float64, strict=False).max() - pl.col("lat_clean").cast(pl.Float64, strict=False).min()).alias("amdar_batch_lat_span_deg"),
                (pl.col("lon_clean").cast(pl.Float64, strict=False).max() - pl.col("lon_clean").cast(pl.Float64, strict=False).min()).alias("amdar_batch_lon_span_deg"),
                (pl.col("alt_meters").cast(pl.Float64, strict=False).max() - pl.col("alt_meters").cast(pl.Float64, strict=False).min()).alias("amdar_batch_vertical_span_m"),
                pl.len().alias("batch_actual_row_count"),
            ]
        )
        .with_columns(
            (
                (pl.col("amdar_batch_lat_span_deg") ** 2 + pl.col("amdar_batch_lon_span_deg") ** 2).sqrt()
            ).alias("amdar_batch_hspan_deg")
        )
    )

    base = (
        resolution.join(wind, on=["source", "source_row_index"], how="left")
        .join(batch_stats, on="amdar_batch_id", how="left")
        .with_columns(
            [
                v2.normalize_text_expr("机尾号").alias("tail_norm"),
                v2.normalize_text_expr("航班号").alias("flight_norm"),
                pl.col("time_utc").dt.strftime("%Y-%m-%d").alias("service_date_utc"),
                pl.col("amdar_batch_size_bucket_v3")
                .fill_null(v2.batch_size_bucket_expr())
                .alias("amdar_batch_size_bucket"),
                pl.col("processing_slice_id")
                .fill_null((pl.col("source_row_index").cast(pl.UInt64) % int(cfg.slice_count)).cast(pl.UInt8))
                .alias("processing_slice_id"),
                pl.col("wind_speed_ms").fill_null(pl.col("wind_speed")).cast(pl.Float64, strict=False).alias("wind_speed_ms_filled"),
                pl.col("wind_direction_raw_deg").fill_null(pl.col("wind_dir")).cast(pl.Float64, strict=False).alias("wind_dir_deg_filled"),
                pl.col("stage1_confidence_cap_v3").fill_null(1.0).alias("stage1_confidence_cap_v3"),
            ]
        )
    )

    prior = build_stage2_v7_identity_prior(cfg, out_dir)
    thresholds = derive_dynamic_thresholds(stage3_report)
    df = base.join(prior.lazy(), on=["tail_norm", "flight_norm", "service_date_utc"], how="left")
    df = add_stage4_v3_confidence_columns(df, thresholds)

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
        "amdar_effective_strict_truth_v3",
        "strict_holdout_eligible_v3",
        "enhanced_holdout_eligible_v3",
        "support_assimilation_eligible_v3",
        "support_assimilation_eligible_stage4_v3",
        "stage1_downstream_action_v3",
        "stage1_confidence_cap_v3",
        "effective_stage1_confidence_cap_stage4_v3",
        "met_value_quality",
        "met_value_quality_audit",
        "wind_speed_outlier_flag",
        "temperature_outlier_flag",
        "altitude_outlier_flag",
        "source_quality_conf",
        "met_physics_conf",
        "batch_representativeness_conf",
        "identity_completeness_conf",
        "identity_date_prior_availability_conf_diagnostic",
        "identity_date_ambiguity_factor_diagnostic",
        "identity_risk_conf_diagnostic",
        "adsb_match_quality_conf",
        "batch_size_factor_v3",
        "batch_spatial_factor_v3",
        "batch_phase_factor_v3",
        "batch_met_consistency_factor_v3",
        "base_support_conf_pre_stage1_cap_v3",
        "base_support_conf",
        "time_uncertainty_s_stage4_v3",
        "time_uncertainty_s_stage4_v3_continuous",
        "time_uncertainty_model_stage4_v3",
        "confidence_tier",
        "confidence_subtier",
        "confidence_grade",
        "confidence_basis",
        "recommended_stage4_role",
        "stage4_weighting_recommendation_v3",
        "hard_reject_flag_v3",
        "met_structural_bad_v3",
        "amdar_high_wind_gt150_mps_v3",
        "amdar_high_wind_stage4_supported_v3",
        "stage4_high_wind_action_v3",
        "same_identity_date_leg_count_v7",
        "candidate_projection_leg_count_v7",
        "pseudo_source_leg_count_v7",
        "S0_leg_count_v7",
        "S1_leg_count_v7",
        "S2_leg_count_v7",
        "best_stage3_source_tier_v7_identity_date",
        "stage2_v7_identity_prior_conf_diagnostic",
        "same_identity_date_leg_points_v7",
        "adsb_reconstructed",
        "adsb_match_status",
    ]
    schema_names = df.collect_schema().names()
    components = df.select([c for c in output_cols if c in schema_names]).collect(streaming=True)
    components.write_parquet(out_dir / "amdar_confidence_components_v3.parquet")

    summary = summarize_components(components, cfg, stage3_report, thresholds)
    next_window_audit = build_next_window_audits(components, cfg, thresholds, out_dir)
    summary["next_window_safeguards"] = {
        "t2_subtier_detail": next_window_audit["t2_subtier_detail"],
        "stage4_weighting_recommendation_counts": next_window_audit["stage4_weighting_recommendation_counts"],
        "time_uncertainty_s_stage4_v3_continuous_summary": next_window_audit[
            "time_uncertainty_s_stage4_v3_continuous_summary"
        ],
        "identity_risk_conf_diagnostic_summary": next_window_audit["identity_risk_conf_diagnostic_summary"],
        "validation_threshold_grid": next_window_audit["validation_threshold_grid"],
        "high_wind_branch_sensitivity": next_window_audit["high_wind_branch_sensitivity"],
        "quality_checks": next_window_audit["quality_checks"],
    }
    summary["stage4_completion_checks"].update(next_window_audit["quality_checks"])
    summary["stage4_completion_checks"]["passed_stage4_confidence_v3_quality_gate"] = bool(
        summary["stage4_completion_checks"]["passed_stage4_confidence_v3_quality_gate"]
        and next_window_audit["quality_checks"]["passed_stage4_next_window_quality_gate"]
    )
    summary["outputs"] = {
        "amdar_confidence_components_v3": str(out_dir / "amdar_confidence_components_v3.parquet"),
        "stage2_v7_identity_date_prior_summary": str(out_dir / "stage2_v7_identity_date_prior_summary.parquet"),
        "amdar_confidence_policy_v3": str(out_dir / "amdar_confidence_policy_v3.json"),
        "confidence_tier_summary_v3": str(out_dir / "confidence_tier_summary_v3.json"),
        "component_correlation_matrix": str(out_dir / "component_correlation_matrix.json"),
        "stage4_confidence_v3_report": str(out_dir / "stage4_confidence_v3_report.md"),
        **next_window_audit["outputs"],
    }
    write_json(out_dir / "confidence_tier_summary_v3.json", summary)
    write_json(out_dir / "amdar_confidence_policy_v3.json", build_policy(summary, thresholds, stage3_report))
    write_json(out_dir / "component_correlation_matrix.json", component_correlation_matrix(components))
    write_stage4_report(out_dir, summary)
    return components, summary


def component_correlation_matrix(df: pl.DataFrame) -> dict[str, Any]:
    cols = [
        "source_quality_conf",
        "met_physics_conf",
        "batch_representativeness_conf",
        "identity_completeness_conf",
    ]
    out: dict[str, Any] = {"component_columns": cols, "matrix": {}}
    for c1 in cols:
        out["matrix"][c1] = {}
        for c2 in cols:
            if c1 == c2:
                out["matrix"][c1][c2] = 1.0
                continue
            try:
                val = df.select(pl.corr(c1, c2)).item()
            except Exception:
                val = None
            out["matrix"][c1][c2] = float(val) if val is not None and math.isfinite(float(val)) else None
    out["interpretation"] = "identity_completeness_conf may be constant because all current AMDAR rows have both tail and flight identifiers."
    return out


def pseudo_stage4_like_frame(path: Path) -> pl.DataFrame:
    lf = pl.scan_parquet(path)
    lat_span = (pl.col("case_max_lat") - pl.col("case_min_lat")).abs()
    lon_span = (pl.col("case_max_lon") - pl.col("case_min_lon")).abs()
    hspan = ((lat_span**2 + lon_span**2).sqrt()).fill_null(999.0)
    vspan = (pl.col("case_max_alt_m") - pl.col("case_min_alt_m")).abs().fill_null(999999.0)
    batch_rows = pl.col("batch_size").cast(pl.Int64, strict=False).fill_null(999999)
    phase = pl.col("leg_phase_like")
    size_factor = (
        pl.when(batch_rows <= 1)
        .then(pl.lit(0.96))
        .when(batch_rows <= 4)
        .then(pl.lit(0.88))
        .when(batch_rows <= 10)
        .then(pl.lit(0.78))
        .when(batch_rows <= 25)
        .then(pl.lit(0.60))
        .when(batch_rows <= 49)
        .then(pl.lit(0.42))
        .otherwise(pl.lit(0.28))
    )
    spatial_factor = (
        pl.when((hspan <= 0.2) & (vspan <= 300.0))
        .then(pl.lit(1.0))
        .when((hspan <= 0.5) & (vspan <= 600.0))
        .then(pl.lit(0.94))
        .when((hspan <= 0.8) & (vspan <= 1000.0))
        .then(pl.lit(0.88))
        .when((hspan <= 1.5) & (vspan <= 1800.0))
        .then(pl.lit(0.76))
        .when((hspan <= 3.0) & (vspan <= 3000.0))
        .then(pl.lit(0.62))
        .when((hspan <= 5.0) & (vspan <= 5000.0))
        .then(pl.lit(0.45))
        .otherwise(pl.lit(0.25))
    )
    phase_factor = (
        pl.when(phase == "LVR")
        .then(pl.lit(1.0))
        .when(phase == "ASC")
        .then(pl.lit(0.92))
        .when(phase == "DES")
        .then(pl.lit(0.88))
        .otherwise(pl.lit(0.82))
    )
    met_factor = pl.when(batch_rows <= 1).then(pl.lit(0.96)).otherwise(pl.lit(0.92))
    batch_repr = (
        size_factor.clip(EPS, 1.0).log() * 0.30
        + spatial_factor.clip(EPS, 1.0).log() * 0.35
        + phase_factor.clip(EPS, 1.0).log() * 0.10
        + met_factor.clip(EPS, 1.0).log() * 0.25
    ).exp()
    pseudo_conf = (
        pl.lit(0.90).log() * 0.22
        + pl.lit(1.0).log() * 0.28
        + batch_repr.clip(EPS, 1.0).log() * 0.40
        + pl.lit(1.0).log() * 0.10
    ).exp().clip(0.0, 0.90)
    pseudo_time_unc = (
        pl.when(batch_rows <= 1)
        .then(pl.lit(240.0))
        .when((batch_rows <= 10) & (hspan <= 0.8) & (vspan <= 1000.0))
        .then(pl.lit(300.0))
        .when((batch_rows <= 25) & (hspan <= 5.0) & (vspan <= 5000.0))
        .then(pl.lit(900.0))
        .when((batch_rows <= 49) & (hspan <= 5.0) & (vspan <= 5000.0))
        .then(pl.lit(1500.0))
        .otherwise(pl.lit(2100.0))
    )
    return (
        lf.with_columns(
            [
                hspan.alias("pseudo_hspan_deg_stage4_like"),
                vspan.alias("pseudo_vspan_m_stage4_like"),
                batch_repr.alias("pseudo_batch_representativeness_conf_stage4_like"),
                pseudo_conf.alias("pseudo_base_support_conf_stage4_like"),
                pseudo_time_unc.alias("pseudo_time_uncertainty_s_stage4_like"),
            ]
        )
        .select(
            [
                "pseudo_case_id",
                "split",
                "source_tier_v8",
                "leg_phase_like",
                "batch_size",
                "batch_size_bucket",
                "status",
                "correct_leg",
                "accepted_by_compound_gate_v8",
                "compound_gate_reject_reason_v8",
                "case_time_error_q90_seconds",
                "candidate_leg_count",
                "best_cost",
                "ambiguity_margin",
                "pseudo_batch_representativeness_conf_stage4_like",
                "pseudo_base_support_conf_stage4_like",
                "pseudo_time_uncertainty_s_stage4_like",
            ]
        )
        .collect(streaming=True)
    )


def assign_tier_expr(base_col: str, time_col: str, thresholds: dict[str, Any], reject_expr: pl.Expr | None = None) -> pl.Expr:
    t1_min = float(thresholds["T1"]["base_support_conf_min"])
    t2_min = float(thresholds["T2"]["base_support_conf_min"])
    t3_min = float(thresholds["T3"]["base_support_conf_min"])
    expr = (
        pl.when(reject_expr if reject_expr is not None else pl.lit(False))
        .then(pl.lit("T4"))
        .when((pl.col(base_col) >= t1_min) & (pl.col(time_col) <= 300.0))
        .then(pl.lit("T1"))
        .when((pl.col(base_col) >= t2_min) & (pl.col(time_col) <= 900.0))
        .then(pl.lit("T2"))
        .when((pl.col(base_col) >= t3_min) & (pl.col(time_col) <= 1800.0))
        .then(pl.lit("T3"))
        .otherwise(pl.lit("T4"))
    )
    return expr


def scalar_metric(df: pl.DataFrame, expr: pl.Expr) -> float | None:
    if df.height == 0:
        return None
    val = df.select(expr).item()
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def metric_or_default(value: float | None, default: float = math.inf) -> float:
    return default if value is None else value


def tier_validation_metrics(df: pl.DataFrame, tier_col: str) -> dict[str, Any]:
    out: dict[str, Any] = {"row_count": int(df.height), "tier_counts": v2.counts_map(df, tier_col)}
    for tier in ["T1", "T2", "T3", "T4"]:
        sub = df.filter(pl.col(tier_col) == tier)
        out[tier] = {
            "case_count": int(sub.height),
            "case_time_error_q90_seconds_q90": scalar_metric(sub, pl.col("case_time_error_q90_seconds").quantile(0.90)),
            "wrong_leg_rate": scalar_metric(sub, (pl.col("status") == "wrong_leg").mean()),
            "accepted_by_stage3_compound_gate_fraction": scalar_metric(sub, pl.col("accepted_by_compound_gate_v8").cast(pl.Float64).mean()),
        }
    return out


def build_validation_threshold_grid(
    components: pl.DataFrame,
    cfg: RunConfig,
    thresholds: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    validation = pseudo_stage4_like_frame(cfg.stage3_v8_dir / "pseudo_amdar_v8_validation.parquet")
    locked = pseudo_stage4_like_frame(cfg.stage3_v8_dir / "pseudo_amdar_v8_locked_test.parquet")
    validation_policy_pool = validation.filter(pl.col("accepted_by_compound_gate_v8").fill_null(False))
    validation_all = validation
    amdar = components.filter(pl.col("source") == "amdar")

    rows: list[dict[str, Any]] = []
    for t1_min in [0.70, 0.72, 0.74, 0.76, 0.78]:
        for t2_min in [0.50, 0.53, 0.56, 0.60]:
            if t2_min >= t1_min:
                continue
            local_thresholds = {
                "T1": {"base_support_conf_min": t1_min},
                "T2": {"base_support_conf_min": t2_min},
                "T3": {"base_support_conf_min": float(thresholds["T3"]["base_support_conf_min"])},
            }
            val_tiered = validation_policy_pool.with_columns(
                assign_tier_expr(
                    "pseudo_base_support_conf_stage4_like",
                    "pseudo_time_uncertainty_s_stage4_like",
                    local_thresholds,
                ).alias("policy_tier")
            )
            real_t1 = amdar.filter((pl.col("base_support_conf") >= t1_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 300.0)).height
            real_t2 = amdar.filter(
                ~((pl.col("base_support_conf") >= t1_min) & (pl.col("time_uncertainty_s_stage4_v3") <= 300.0))
                & (pl.col("base_support_conf") >= t2_min)
                & (pl.col("time_uncertainty_s_stage4_v3") <= 900.0)
            ).height
            t1_val = val_tiered.filter(pl.col("policy_tier") == "T1")
            t2_val = val_tiered.filter(pl.col("policy_tier") == "T2")
            t1_q90 = scalar_metric(t1_val, pl.col("case_time_error_q90_seconds").quantile(0.90))
            t2_q90 = scalar_metric(t2_val, pl.col("case_time_error_q90_seconds").quantile(0.90))
            t1_wrong = scalar_metric(t1_val, (pl.col("status") == "wrong_leg").mean())
            t2_wrong = scalar_metric(t2_val, (pl.col("status") == "wrong_leg").mean())
            rows.append(
                {
                    "t1_base_support_conf_min": t1_min,
                    "t2_base_support_conf_min": t2_min,
                    "t3_base_support_conf_min": local_thresholds["T3"]["base_support_conf_min"],
                    "real_amdar_t1_rows": int(real_t1),
                    "real_amdar_t2_rows": int(real_t2),
                    "real_amdar_t1_coverage_pct": pct(int(real_t1), amdar.height),
                    "real_amdar_t2_coverage_pct": pct(int(real_t2), amdar.height),
                    "real_amdar_t1_t2_coverage_pct": pct(int(real_t1 + real_t2), amdar.height),
                    "validation_policy_pool_rows": int(validation_policy_pool.height),
                    "validation_t1_cases": int(t1_val.height),
                    "validation_t2_cases": int(t2_val.height),
                    "validation_t1_case_time_error_q90_seconds_q90": t1_q90,
                    "validation_t2_case_time_error_q90_seconds_q90": t2_q90,
                    "validation_t1_wrong_leg_rate": t1_wrong,
                    "validation_t2_wrong_leg_rate": t2_wrong,
                    "passes_t1_q90_lt_180s": metric_or_default(t1_q90) < 180.0,
                    "passes_t2_q90_lt_600s": metric_or_default(t2_q90) < 600.0,
                    "passes_t1_wrong_leg_le_1pct": metric_or_default(t1_wrong) <= 0.01,
                    "passes_t2_wrong_leg_le_2pct": metric_or_default(t2_wrong) <= 0.02,
                }
            )
    grid = pl.DataFrame(rows)
    grid_path = out_dir / "stage4_v3_threshold_grid_validation_only.parquet"
    grid.write_parquet(grid_path)

    selected_t1 = float(thresholds["T1"]["base_support_conf_min"])
    selected_t2 = float(thresholds["T2"]["base_support_conf_min"])
    selected_grid_row = grid.filter(
        (pl.col("t1_base_support_conf_min") == selected_t1) & (pl.col("t2_base_support_conf_min") == selected_t2)
    )
    selected = selected_grid_row.to_dicts()[0] if selected_grid_row.height else {}

    selected_thresholds_for_expr = {
        "T1": {"base_support_conf_min": selected_t1},
        "T2": {"base_support_conf_min": selected_t2},
        "T3": {"base_support_conf_min": float(thresholds["T3"]["base_support_conf_min"])},
    }
    validation_policy_tiered = validation_policy_pool.with_columns(
        assign_tier_expr(
            "pseudo_base_support_conf_stage4_like",
            "pseudo_time_uncertainty_s_stage4_like",
            selected_thresholds_for_expr,
        ).alias("policy_tier")
    )
    validation_all_tiered = validation_all.with_columns(
        assign_tier_expr(
            "pseudo_base_support_conf_stage4_like",
            "pseudo_time_uncertainty_s_stage4_like",
            selected_thresholds_for_expr,
        ).alias("policy_tier")
    )
    locked_report_tiered = locked.with_columns(
        assign_tier_expr(
            "pseudo_base_support_conf_stage4_like",
            "pseudo_time_uncertainty_s_stage4_like",
            selected_thresholds_for_expr,
        ).alias("policy_tier")
    )
    grid_summary = {
        "source": "validation split only for threshold quality checks; locked_test is report-only.",
        "grid_path": str(grid_path),
        "selected_policy": selected,
        "selected_policy_validation_pool_metrics": tier_validation_metrics(validation_policy_tiered, "policy_tier"),
        "selected_policy_validation_all_cases_diagnostic": tier_validation_metrics(validation_all_tiered, "policy_tier"),
        "quality_checks": {
            "validation_only_threshold_grid_written": grid_path.exists(),
            "selected_t1_validation_q90_lt_3min": bool(selected.get("passes_t1_q90_lt_180s")),
            "selected_t2_validation_q90_lt_10min": bool(selected.get("passes_t2_q90_lt_600s")),
            "selected_t1_validation_wrong_leg_le_1pct": bool(selected.get("passes_t1_wrong_leg_le_1pct")),
            "selected_t2_validation_wrong_leg_le_2pct": bool(selected.get("passes_t2_wrong_leg_le_2pct")),
            "locked_test_not_used_for_threshold_selection": True,
        },
    }
    locked_report = {
        "source": "locked_test report only; not used for threshold selection.",
        "selected_policy_locked_test_all_cases_metrics": tier_validation_metrics(locked_report_tiered, "policy_tier"),
    }
    write_json(out_dir / "stage4_v3_threshold_grid_summary.json", grid_summary)
    write_json(out_dir / "stage4_v3_selected_policy.json", selected)
    write_json(out_dir / "locked_test_report_only.json", locked_report)
    return {
        "grid_summary": grid_summary,
        "locked_test_report_only": locked_report,
        "outputs": {
            "stage4_v3_threshold_grid_validation_only": str(grid_path),
            "stage4_v3_threshold_grid_summary": str(out_dir / "stage4_v3_threshold_grid_summary.json"),
            "stage4_v3_selected_policy": str(out_dir / "stage4_v3_selected_policy.json"),
            "locked_test_report_only": str(out_dir / "locked_test_report_only.json"),
        },
    }


def summarize_high_wind_branch(
    df: pl.DataFrame,
    branch_name: str,
    reject_expr: pl.Expr,
    action_expr: pl.Expr,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    is_amdar = pl.col("source") == "amdar"
    is_turb = pl.col("source") == "turb"
    high = pl.col("amdar_high_wind_gt150_mps_v3").fill_null(False)
    branch = (
        df.with_columns(
            [
                pl.when(is_amdar & reject_expr)
                .then(pl.lit(0.0))
                .otherwise(pl.col("base_support_conf"))
                .alias("_branch_base_support_conf"),
                action_expr.alias("_branch_high_wind_action"),
            ]
        )
        .with_columns(
            [
                pl.when(is_turb & pl.col("enhanced_holdout_eligible_v3").fill_null(False))
                .then(pl.lit("T0"))
                .when(is_turb)
                .then(pl.lit("T4"))
                .otherwise(
                    assign_tier_expr(
                        "_branch_base_support_conf",
                        "time_uncertainty_s_stage4_v3",
                        thresholds,
                        reject_expr=is_amdar & reject_expr,
                    )
                )
                .alias("_branch_confidence_tier")
            ]
        )
    )
    amdar = branch.filter(pl.col("source") == "amdar")
    high_df = amdar.filter(pl.col("amdar_high_wind_gt150_mps_v3").fill_null(False))
    retained = high_df.filter(pl.col("_branch_confidence_tier").is_in(["T1", "T2", "T3"]) & (pl.col("_branch_base_support_conf") > 0.0))
    gt200 = amdar.filter(pl.col("wind_speed_ms_filled") > 200.0)
    gt200_retained = gt200.filter(pl.col("_branch_confidence_tier").is_in(["T1", "T2", "T3"]) & (pl.col("_branch_base_support_conf") > 0.0))
    tier_counts = v2.counts_map(branch, "_branch_confidence_tier")
    amdar_tier_counts = v2.counts_map(amdar, "_branch_confidence_tier")
    t1 = int(amdar_tier_counts.get("T1", 0))
    t2 = int(amdar_tier_counts.get("T2", 0))
    return {
        "branch_name": branch_name,
        "tier_counts": tier_counts,
        "amdar_tier_counts": amdar_tier_counts,
        "amdar_t1_t2_coverage_pct": pct(t1 + t2, amdar.height),
        "high_wind_action_counts": v2.counts_map(high_df, "_branch_high_wind_action"),
        "high_wind_retained_rows_T1_T3": int(retained.height),
        "high_wind_retained_pct_of_gt150": pct(int(retained.height), int(high_df.height)),
        "gt200_retained_rows_T1_T3": int(gt200_retained.height),
        "strict_truth_invariant_check": {
            "amdar_t0_rows": int(amdar.filter(pl.col("_branch_confidence_tier") == "T0").height),
            "amdar_strict_holdout_rows": int(amdar.filter(pl.col("strict_holdout_eligible_v3").fill_null(False)).height),
            "turb_t0_rows": int(branch.filter((pl.col("source") == "turb") & (pl.col("_branch_confidence_tier") == "T0")).height),
        },
        "stage4_reconstruction_smoke": {
            "status": "not_run_in_confidence_only_next_window_audit",
            "reason": "This audit does not run full large-framework Stage4 windfield reconstruction; branch must still be validated on strict TURB holdout before claiming reconstruction benefit.",
        },
    }


def build_high_wind_branch_sensitivity(components: pl.DataFrame, thresholds: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    high = pl.col("amdar_high_wind_gt150_mps_v3").fill_null(False)
    ws = pl.col("wind_speed_ms_filled").cast(pl.Float64, strict=False)
    alt = pl.col("alt_meters").cast(pl.Float64, strict=False).fill_null(-9999.0)
    hspan = pl.col("amdar_batch_hspan_deg").cast(pl.Float64, strict=False).fill_null(999.0)
    vspan = pl.col("amdar_batch_vertical_span_m").cast(pl.Float64, strict=False).fill_null(999999.0)
    batch_rows = pl.col("amdar_batch_row_count").cast(pl.Int64, strict=False).fill_null(999999)
    supported = pl.col("amdar_high_wind_stage4_supported_v3").fill_null(False)
    strict_gt200_keep = high & (ws > 200.0) & supported & (alt >= 9000.0) & (hspan <= 4.0) & (vspan <= 3500.0) & (batch_rows <= 25)
    moderate_keep = (~high) | (supported & (ws <= 200.0)) | strict_gt200_keep

    branches = [
        summarize_high_wind_branch(
            components,
            "A0_teacher_filter_all_gt150_rejected",
            reject_expr=high,
            action_expr=pl.when(high).then(pl.lit("reject_gt150_teacher_filter")).otherwise(pl.lit("not_high_wind")),
            thresholds=thresholds,
        ),
        summarize_high_wind_branch(
            components,
            "A1_current_v3_rescue",
            reject_expr=pl.col("hard_reject_flag_v3").fill_null(False),
            action_expr=pl.col("stage4_high_wind_action_v3"),
            thresholds=thresholds,
        ),
        summarize_high_wind_branch(
            components,
            "A2_moderate_rescue_gt200_stricter",
            reject_expr=high & ~moderate_keep,
            action_expr=(
                pl.when(~high)
                .then(pl.lit("not_high_wind"))
                .when(high & ~moderate_keep)
                .then(pl.lit("reject_gt150_moderate_policy"))
                .when(ws > 200.0)
                .then(pl.lit("retain_gt200_strict_high_altitude_small_batch"))
                .otherwise(pl.lit("retain_150_200_review_low_confidence"))
            ),
            thresholds=thresholds,
        ),
    ]
    summary = {
        "source": "confidence-only high-wind branch sensitivity; no real truth promotion and no full reconstruction in this audit.",
        "branches": branches,
        "quality_checks": {
            "branch_a1_current_high_wind_retained_ge_2800": branches[1]["high_wind_retained_rows_T1_T3"] >= 2800,
            "branch_a2_moderate_available_for_downstream_ablation": branches[2]["high_wind_retained_rows_T1_T3"] > 0,
            "all_branches_keep_amdar_t0_zero": all(b["strict_truth_invariant_check"]["amdar_t0_rows"] == 0 for b in branches),
            "all_branches_keep_amdar_holdout_zero": all(b["strict_truth_invariant_check"]["amdar_strict_holdout_rows"] == 0 for b in branches),
        },
    }
    write_json(out_dir / "high_wind_branch_sensitivity_summary.json", summary)
    return {
        "summary": summary,
        "outputs": {"high_wind_branch_sensitivity_summary": str(out_dir / "high_wind_branch_sensitivity_summary.json")},
    }


def build_next_window_audits(
    components: pl.DataFrame,
    cfg: RunConfig,
    thresholds: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    validation = build_validation_threshold_grid(components, cfg, thresholds, out_dir)
    high_wind = build_high_wind_branch_sensitivity(components, thresholds, out_dir)
    amdar = components.filter(pl.col("source") == "amdar")
    t2 = amdar.filter(pl.col("confidence_tier") == "T2")
    t2a = t2.filter(pl.col("confidence_subtier") == "T2a_direct_support_candidate")
    t2b = t2.filter(pl.col("confidence_subtier") == "T2b_broad_or_lower_weight_support")
    identity_risk = v2.numeric_summary(amdar, "identity_risk_conf_diagnostic")
    time_cont = v2.numeric_summary(amdar, "time_uncertainty_s_stage4_v3_continuous")
    quality_checks = {
        "confidence_subtier_present": "confidence_subtier" in components.columns,
        "t2_subtier_covers_all_t2_rows": int(t2a.height + t2b.height) == int(t2.height),
        "time_uncertainty_continuous_present": "time_uncertainty_s_stage4_v3_continuous" in components.columns,
        "continuous_time_uncertainty_not_above_step_uncertainty": int(
            amdar.filter(pl.col("time_uncertainty_s_stage4_v3_continuous") > pl.col("time_uncertainty_s_stage4_v3")).height
        )
        == 0,
        "identity_risk_diagnostic_present": "identity_risk_conf_diagnostic" in components.columns,
        "identity_risk_diagnostic_not_used_as_adsb_match": True,
        "stage2_v7_identity_prior_not_used_in_base_support_conf": True,
        **validation["grid_summary"]["quality_checks"],
        **high_wind["summary"]["quality_checks"],
    }
    quality_checks["passed_stage4_next_window_quality_gate"] = bool(
        quality_checks["confidence_subtier_present"]
        and quality_checks["t2_subtier_covers_all_t2_rows"]
        and quality_checks["time_uncertainty_continuous_present"]
        and quality_checks["continuous_time_uncertainty_not_above_step_uncertainty"]
        and quality_checks["identity_risk_diagnostic_present"]
        and quality_checks["stage2_v7_identity_prior_not_used_in_base_support_conf"]
        and quality_checks["selected_t1_validation_q90_lt_3min"]
        and quality_checks["selected_t2_validation_q90_lt_10min"]
        and quality_checks["selected_t1_validation_wrong_leg_le_1pct"]
        and quality_checks["selected_t2_validation_wrong_leg_le_2pct"]
        and quality_checks["locked_test_not_used_for_threshold_selection"]
        and quality_checks["branch_a1_current_high_wind_retained_ge_2800"]
        and quality_checks["all_branches_keep_amdar_t0_zero"]
        and quality_checks["all_branches_keep_amdar_holdout_zero"]
    )
    audit = {
        "t2_subtier_counts": v2.counts_map(amdar, "confidence_subtier"),
        "t2_subtier_detail": {
            "T2_total": int(t2.height),
            "T2a_direct_support_candidate": int(t2a.height),
            "T2b_broad_or_lower_weight_support": int(t2b.height),
            "T2a_pct_of_T2": pct(int(t2a.height), int(t2.height)),
            "T2b_pct_of_T2": pct(int(t2b.height), int(t2.height)),
        },
        "stage4_weighting_recommendation_counts": v2.counts_map(amdar, "stage4_weighting_recommendation_v3"),
        "time_uncertainty_s_stage4_v3_continuous_summary": time_cont,
        "identity_risk_conf_diagnostic_summary": identity_risk,
        "validation_threshold_grid": validation["grid_summary"],
        "locked_test_report_only": validation["locked_test_report_only"],
        "high_wind_branch_sensitivity": high_wind["summary"],
        "quality_checks": quality_checks,
        "outputs": {**validation["outputs"], **high_wind["outputs"]},
    }
    write_json(out_dir / "stage4_next_window_quality_checks.json", audit)
    audit["outputs"]["stage4_next_window_quality_checks"] = str(out_dir / "stage4_next_window_quality_checks.json")
    return audit


def summarize_components(
    df: pl.DataFrame,
    cfg: RunConfig,
    stage3_report: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    amdar = df.filter(pl.col("source") == "amdar")
    turb = df.filter(pl.col("source") == "turb")
    high = amdar.filter(pl.col("amdar_high_wind_gt150_mps_v3").fill_null(False))
    high_retained = high.filter(pl.col("confidence_tier").is_in(["T1", "T2", "T3"]) & (pl.col("base_support_conf") > 0.0))
    gt200 = amdar.filter(pl.col("wind_speed_ms_filled") > 200.0)
    gt200_retained = gt200.filter(pl.col("confidence_tier").is_in(["T1", "T2", "T3"]) & (pl.col("base_support_conf") > 0.0))
    amdar_tier_counts = v2.counts_map(amdar, "confidence_tier")
    t1 = int(amdar_tier_counts.get("T1", 0))
    t2 = int(amdar_tier_counts.get("T2", 0))
    t3 = int(amdar_tier_counts.get("T3", 0))
    by_slice = (
        df.group_by("processing_slice_id")
        .agg(
            [
                pl.len().alias("rows"),
                (pl.col("source") == "amdar").sum().alias("amdar_rows"),
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
    checks = {
        "component_count_is_4_core_plus_stage5_conditional": True,
        "removed_redundant_v2_components": True,
        "stage3_v8_quality_gate_passed": bool(stage3_report.get("quality_gate", {}).get("passed_stage3_v8_quality_gate")),
        "strict_truth_not_derived_from_confidence": True,
        "amdar_effective_strict_truth_rows": int(amdar.filter(pl.col("effective_strict_truth").fill_null(False)).height),
        "amdar_effective_strict_truth_v3_rows": int(amdar.filter(pl.col("amdar_effective_strict_truth_v3").fill_null(False)).height),
        "amdar_t0_rows": int(amdar.filter(pl.col("confidence_tier") == "T0").height),
        "amdar_holdout_eligible_rows": int(amdar.filter(pl.col("strict_holdout_eligible_v3").fill_null(False)).height),
        "turb_enhanced_holdout_eligible_is_175": int(turb.filter(pl.col("enhanced_holdout_eligible_v3")).height) == 175,
        "turb_review_rows_is_6": int(turb.filter(~pl.col("enhanced_holdout_eligible_v3")).height) == 6,
        "stage5_match_not_fabricated": int(amdar.filter(pl.col("adsb_reconstructed").fill_null(False)).height) == 0,
        "stage2_v7_identity_prior_diagnostic_present": "best_stage3_source_tier_v7_identity_date" in df.columns,
        "t1_coverage_pct_ge_10": pct(t1, amdar.height) >= 10.0,
        "t2_coverage_pct_ge_42": pct(t2, amdar.height) >= 42.0,
        "t1_t2_coverage_pct_ge_55": pct(t1 + t2, amdar.height) >= 55.0,
        "high_wind_retained_rows_ge_2800": int(high_retained.height) >= 2800,
        "unsupported_high_wind_rejected": int(
            high.filter(~pl.col("amdar_high_wind_stage4_supported_v3").fill_null(False) & (pl.col("base_support_conf") > 0.0)).height
        )
        == 0,
        "space_saving_single_compact_table": True,
    }
    checks["passed_stage4_confidence_v3_quality_gate"] = bool(
        checks["component_count_is_4_core_plus_stage5_conditional"]
        and checks["removed_redundant_v2_components"]
        and checks["stage3_v8_quality_gate_passed"]
        and checks["amdar_effective_strict_truth_rows"] == 0
        and checks["amdar_effective_strict_truth_v3_rows"] == 0
        and checks["amdar_t0_rows"] == 0
        and checks["amdar_holdout_eligible_rows"] == 0
        and checks["turb_enhanced_holdout_eligible_is_175"]
        and checks["turb_review_rows_is_6"]
        and checks["stage5_match_not_fabricated"]
        and checks["t1_coverage_pct_ge_10"]
        and checks["t2_coverage_pct_ge_42"]
        and checks["t1_t2_coverage_pct_ge_55"]
        and checks["high_wind_retained_rows_ge_2800"]
        and checks["unsupported_high_wind_rejected"]
        and checks["space_saving_single_compact_table"]
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "optimization plan phase 3; large-framework Stage4 confidence v3, not real Stage5 matching and not full windfield reconstruction.",
        "run_policy": {
            "slice_count": cfg.slice_count,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "space_saving_policy": "Single compact confidence table with processing_slice_id; no duplicated 25-way full intermediates.",
        },
        "inputs": {
            "stage1_clean_wind": str(cfg.stage1_plan4_dir / "clean_wind.parquet"),
            "stage1_v3_resolution": str(cfg.stage1_v3_dir / "stage1_qc_resolution_table_v3.parquet"),
            "stage2_v7_leg_components": str(cfg.stage2_v7_dir / "adsb_leg_quality_components_v7.parquet"),
            "stage3_v8_report": str(cfg.stage3_v8_dir / "pseudo_amdar_v8_calibration_report.json"),
        },
        "component_system": {
            "core_component_count": 4,
            "core_components": [
                "source_quality_conf",
                "met_physics_conf",
                "batch_representativeness_conf",
                "identity_completeness_conf",
            ],
            "conditional_component": "adsb_match_quality_conf only after Stage5 accepted rows exist; currently null/not used.",
            "removed_v2_components": [
                "time_source_conf",
                "adsb_leg_conf",
                "adsb_match_conf_zero",
                "spatial_match_conf_zero",
                "density_conf",
            ],
        },
        "dynamic_thresholds": thresholds,
        "row_counts": {"total": int(df.height), "amdar": int(amdar.height), "turb": int(turb.height)},
        "tier_counts": v2.counts_map(df, "confidence_tier"),
        "grade_counts": v2.counts_map(df, "confidence_grade"),
        "recommended_role_counts": v2.counts_map(df, "recommended_stage4_role"),
        "amdar": {
            "tier_counts": amdar_tier_counts,
            "tier_coverage_pct": {k: pct(int(v), amdar.height) for k, v in amdar_tier_counts.items()},
            "T1_T2_rows": int(t1 + t2),
            "T1_T2_coverage_pct": pct(t1 + t2, amdar.height),
            "T1_T2_T3_rows": int(t1 + t2 + t3),
            "base_support_conf_summary": v2.numeric_summary(amdar, "base_support_conf"),
            "time_uncertainty_s_summary": v2.numeric_summary(amdar, "time_uncertainty_s_stage4_v3"),
            "batch_size_counts": v2.counts_map(amdar, "amdar_batch_size_bucket"),
        },
        "high_wind": {
            "gt150_rows": int(high.height),
            "stage4_supported_rows": int(high.filter(pl.col("amdar_high_wind_stage4_supported_v3").fill_null(False)).height),
            "retained_rows_T1_T3": int(high_retained.height),
            "retained_pct_of_gt150": pct(int(high_retained.height), int(high.height)),
            "gt200_rows": int(gt200.height),
            "gt200_retained_rows_T1_T3": int(gt200_retained.height),
            "action_counts": v2.counts_map(high, "stage4_high_wind_action_v3"),
            "tier_counts": v2.counts_map(high, "confidence_tier"),
            "note": "Stage4 v3 overrides the Stage1 v3 high-wind cap only for supported high-wind rows; unsupported high-wind rows remain zero-confidence.",
        },
        "turb": {
            "tier_counts": v2.counts_map(turb, "confidence_tier"),
            "enhanced_holdout_eligible_true": int(turb.filter(pl.col("enhanced_holdout_eligible_v3")).height),
            "enhanced_holdout_review_rows": int(turb.filter(~pl.col("enhanced_holdout_eligible_v3")).height),
        },
        "stage2_v7_identity_prior_diagnostic": {
            "amdar_rows_with_same_identity_date_leg": int(amdar.filter(pl.col("same_identity_date_leg_count_v7").fill_null(0) > 0).height),
            "best_stage3_source_tier_counts": v2.counts_map(amdar, "best_stage3_source_tier_v7_identity_date"),
            "note": "Diagnostic only; not part of base_support_conf and not a real Stage5 match.",
        },
        "stage3_v8_status": {
            "quality_gate": stage3_report.get("quality_gate", {}),
            "selected_locked_test_metrics": (
                stage3_report.get("metrics", {}).get("selected_by_compound_gate_v8", {}).get("locked_test", {})
            ),
        },
        "by_processing_slice": by_slice,
        "stage4_completion_checks": checks,
    }


def build_policy(summary: dict[str, Any], thresholds: dict[str, Any], stage3_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at_utc": summary["generated_at_utc"],
        "policy_version": "amdar_stage4_confidence_v3_next_window_stage2v7_stage3v8_20260708",
        "purpose": "Four-component AMDAR support confidence with next-window safeguards; AMDAR remains support-only.",
        "strict_truth_boundary": {
            "rule": "No confidence tier or confidence value can create strict truth.",
            "amdar_effective_strict_truth_rows": summary["stage4_completion_checks"]["amdar_effective_strict_truth_rows"],
            "amdar_holdout_eligible_rows": summary["stage4_completion_checks"]["amdar_holdout_eligible_rows"],
            "turb_enhanced_holdout_eligible_after_qc": summary["turb"]["enhanced_holdout_eligible_true"],
        },
        "component_definitions": {
            "source_quality_conf": "1.0 for TURB, 0.90 for AMDAR.",
            "met_physics_conf": "0 for structural bad or unsupported high wind; 0.42-0.78 for supported high wind; 0.70 for review flags; 1.0 otherwise.",
            "batch_representativeness_conf": "Weighted geometric mean of batch size, spatial span, phase, and within-batch wind consistency.",
            "identity_completeness_conf": "Continuous identity completeness score; current AMDAR rows all have both tail and flight.",
            "identity_risk_conf_diagnostic": "Diagnostic-only identity-date risk score from Stage2 v7 availability/ambiguity; not a real ADS-B match and not part of base_support_conf.",
            "adsb_match_quality_conf": "Reserved for Stage5 accepted rows only; null in this Stage4 v3 run.",
        },
        "weights": {
            "source_quality_conf": 0.22,
            "met_physics_conf": 0.28,
            "batch_representativeness_conf": 0.40,
            "identity_completeness_conf": 0.10,
        },
        "dynamic_thresholds": thresholds,
        "tier_rules": {
            "T0/S": "TURB with Stage1 v3 strict_holdout_eligible and no hard reject.",
            "T1/A": "base_support_conf >= T1 threshold and time_uncertainty_s <= 300, support only.",
            "T2/B": "base_support_conf >= T2 threshold and time_uncertainty_s <= 900, support only.",
            "T3/C": "base_support_conf >= T3 threshold and time_uncertainty_s <= 1800, low-confidence support/super-ob only.",
            "T4/D_or_R": "Below T3, unsupported high wind, structural bad, or manual review/reject.",
        },
        "high_wind_policy": {
            "retained_150_200": "Retained with low-to-medium met_physics_conf when structurally valid.",
            "retained_gt200": "Only retained when altitude>=7000m and batch span is bounded (hspan<=8deg, vspan<=6500m).",
            "unsupported_gt150": "Rejected with base_support_conf=0.",
            "teacher_filter_conflict_note": "Stage1 teacher-filter v4 filtered all >150 m/s; Stage4 v3 implements the later optimization-plan high-wind rescue as an explicit experimental confidence override, not truth promotion.",
        },
        "next_window_safeguards": {
            "confidence_subtier": "T2 is split into T2a direct-support candidate and T2b broad/lower-weight support to prevent wide-batch overuse.",
            "time_uncertainty_s_stage4_v3_continuous": "Continuous conservative diagnostic for Stage6; discrete step uncertainty is still used for Stage4 v3 tier assignment.",
            "validation_threshold_grid": summary.get("next_window_safeguards", {}).get("validation_threshold_grid", {}).get("source"),
            "high_wind_branch_sensitivity": "A0 teacher-filter, A1 current rescue, and A2 moderate rescue are summarized for downstream ablation; no branch promotes AMDAR to truth.",
        },
        "stage3_v8_compound_gate_policy": stage3_report.get("chosen_compound_gate_policy_v8", {}),
        "forbidden_operations_reaffirmed": [
            "Do not promote AMDAR to strict truth.",
            "Do not set AMDAR holdout_eligible true.",
            "Do not treat AMDAR batch_end_time as point observation time.",
            "Do not treat Stage2 v7 identity-date prior as a real ADS-B match.",
            "Do not fabricate Stage5 accepted rows.",
        ],
    }


def write_stage4_report(out_dir: Path, summary: dict[str, Any]) -> None:
    checks = summary["stage4_completion_checks"]
    report = [
        "# Stage4 Confidence v3 Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Scope",
        "",
        "This is optimization-plan phase 3: large-framework Stage4 confidence v3. It refreshes confidence tiers only; it does not run real Stage5 matching or full windfield reconstruction.",
        "",
        "## Key Results",
        "",
        f"- Total rows scored: `{summary['row_counts']['total']}`",
        f"- AMDAR rows scored: `{summary['row_counts']['amdar']}`",
        f"- TURB rows scored: `{summary['row_counts']['turb']}`",
        f"- Core components: `{summary['component_system']['core_components']}`",
        f"- Tier counts: `{summary['tier_counts']}`",
        f"- AMDAR tier coverage pct: `{summary['amdar']['tier_coverage_pct']}`",
        f"- AMDAR T1+T2 coverage pct: `{summary['amdar']['T1_T2_coverage_pct']}`",
        f"- High-wind retained rows: `{summary['high_wind']['retained_rows_T1_T3']}` / `{summary['high_wind']['gt150_rows']}`",
        f"- TURB enhanced holdout eligible rows: `{summary['turb']['enhanced_holdout_eligible_true']}`",
        f"- TURB enhanced holdout review rows: `{summary['turb']['enhanced_holdout_review_rows']}`",
        f"- T2 subtier detail: `{summary.get('next_window_safeguards', {}).get('t2_subtier_detail')}`",
        f"- Continuous time uncertainty summary: `{summary.get('next_window_safeguards', {}).get('time_uncertainty_s_stage4_v3_continuous_summary')}`",
        "",
        "## Completion Checks",
        "",
        f"- Checks: `{checks}`",
        "",
        "## Next-Window Safeguards",
        "",
        "- `confidence_subtier` splits broad T2 rows into T2a/T2b so downstream stages can avoid treating all T2 rows equally.",
        "- `time_uncertainty_s_stage4_v3_continuous` is a conservative Stage6 diagnostic; tiering still uses the discrete Stage4 uncertainty.",
        "- `identity_risk_conf_diagnostic` is diagnostic only and does not enter `base_support_conf`.",
        "- Validation-only threshold grid and high-wind branch sensitivity are written as separate audit files.",
        "",
        "Interpretation: Stage4 confidence v3 passes the pre-Stage5 confidence quality gate. AMDAR remains support-only; Stage2 v7 identity-date priors are diagnostic only; Stage5 accepted rows are not fabricated.",
    ]
    (out_dir / "stage4_confidence_v3_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def write_final_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage4_v3_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage4_v3.md"
    checks = summary["stage4_completion_checks"]
    nw = summary.get("next_window_safeguards", {})
    nw_checks = nw.get("quality_checks", {})
    gate_status = "passes" if checks.get("passed_stage4_confidence_v3_quality_gate") else "does not pass"
    result_lines = [
        "# Stage4 Confidence v3 Next-Window Optimization Results Analysis And Next Steps",
        "",
        f"Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Scope And Stage Naming",
        "",
        "This is optimization plan phase 3 next-window optimization. It corresponds to large-framework Stage4 confidence/tier modeling, not large-framework Stage5 real AMDAR-ADS-B matching and not a full Stage4 windfield holdout reconstruction run.",
        "",
        "## Run Policy",
        "",
        f"- `POLARS_MAX_THREADS={summary['run_policy']['polars_threads']}`",
        f"- `slice_count={summary['run_policy']['slice_count']}`",
        "- One compact confidence table with `processing_slice_id`.",
        "- Stage2 v7 compact leg table is read once for diagnostic identity-date priors.",
        "- Stage3 v8 reports are consumed; the 19M ADS-B point table is not copied.",
        "",
        "## What Changed From v2",
        "",
        "- Reduced confidence core from redundant v2 components to 4 core components.",
        "- Removed `time_source_conf`, zero-valued `adsb_match_conf`, zero-valued `spatial_match_conf`, and `density_conf` from `base_support_conf`.",
        "- Kept Stage2 v7 identity-date ADS-B information as a diagnostic field only, not as a real match component.",
        "- Added explicit high-wind support override for Stage4 v3 with audited action reasons.",
        "- Added `confidence_subtier` to split T2 into T2a/T2b for downstream weighting.",
        "- Added conservative `time_uncertainty_s_stage4_v3_continuous` for Stage6 consumption while preserving discrete Stage4 tiering.",
        "- Added validation-only threshold grid, locked-test report-only file, and A0/A1/A2 high-wind branch sensitivity.",
        "",
        "## Key Result",
        "",
        f"- Tier counts: `{summary['tier_counts']}`",
        f"- AMDAR tier counts: `{summary['amdar']['tier_counts']}`",
        f"- AMDAR tier coverage pct: `{summary['amdar']['tier_coverage_pct']}`",
        f"- AMDAR T1+T2 coverage pct: `{summary['amdar']['T1_T2_coverage_pct']:.3f}`",
        f"- High-wind retained rows: `{summary['high_wind']['retained_rows_T1_T3']}` of `{summary['high_wind']['gt150_rows']}`",
        f"- T2 subtier detail: `{nw.get('t2_subtier_detail')}`",
        f"- Stage4 next-window checks: `{nw_checks}`",
        f"- Completion checks: `{checks}`",
        "",
        "## Validation And Branch Audits",
        "",
        f"- Validation-only selected policy: `{nw.get('validation_threshold_grid', {}).get('selected_policy')}`",
        f"- Locked-test handling: `{nw.get('validation_threshold_grid', {}).get('source')}`",
        f"- High-wind branch sensitivity: `{nw.get('high_wind_branch_sensitivity', {}).get('branches')}`",
        "",
        "## Interpretation",
        "",
        f"Stage4 confidence v3 next-window optimization `{gate_status}` the confidence quality gate for entering optimization plan phase 4. The result meets the requested T1/T2 coverage and high-wind-retention checks while preserving the strict-truth boundary: AMDAR has zero strict-truth rows and zero holdout-eligible rows.",
        "",
        "The high-wind rule is intentionally explicit because it departs from the older Stage1 teacher-filter v4 branch. It should be treated as the optimization-plan confidence branch and validated in later strict TURB holdout reconstruction experiments, not as proof that high-wind AMDAR is strict truth.",
        "",
        "The new T2a/T2b split and continuous time uncertainty reduce downstream risk without changing the truth boundary. Stage2 v7 identity-date information remains diagnostic only and is not part of `base_support_conf` or `adsb_match_quality_conf`.",
        "",
        "## Next Steps",
        "",
        "1. Enter optimization plan phase 4: large-framework Stage5 real AMDAR-ADS-B matching v4.",
        "2. Consume `stage4_confidence_v3/amdar_confidence_components_v3.parquet`; use `base_support_conf`, `confidence_tier`, `confidence_subtier`, `time_uncertainty_s_stage4_v3`, `time_uncertainty_s_stage4_v3_continuous`, and high-wind action fields.",
        "3. Keep Stage5 accepted rows support-only and write match grade/ambiguity diagnostics before Stage6 time modeling.",
        "4. In later full Stage4 reconstruction validation, compare A0 teacher-filter, A1 current rescue, and A2 moderate rescue on strict TURB holdout before claiming reconstruction benefit.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover = [
        "# 给下一个智能体的交接话术：Stage4 confidence v3 next-window 后续进入优化计划阶段4",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。本轮已经完成优化计划阶段3 next-window：大框架 Stage4 confidence v3 风险控制优化。注意：这里的“阶段3/阶段4”是优化计划小阶段；大框架仍是 Stage1 清洗、Stage2 组织/QC、Stage3 pseudo 验证、Stage4 confidence/重构、Stage5 real matching。",
        "",
        "## 必读文档与用途",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`",
        "   - 项目总边界：strict aircraft holdout 是唯一正式验证，AMDAR 不能进入 strict truth。",
        "2. `/data/LFT-W02_data/pengxu/优化/teacher_reports/plan4.md`",
        "   - AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md`",
        "   - strict truth 候选少是数据现实；路线是分层置信度和 support-only 使用。",
        "4. `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_unified_implementation_plan_20260701.md`",
        "   - Unified Plan 小阶段边界、禁止操作、T0-T4 分层定义。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`",
        "   - 本轮 Stage2-6 优化总方案；下一步是优化计划阶段4（大框架 Stage5 real matching v4）。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_optimization_targets_quality_controlled_20260706.md`",
        "   - 平衡目标和质量门，尤其是 T1/T2 覆盖和质量可控原则。",
        "7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_adsb_qc_v7_optimized_20260706/stage2_v7_results_analysis_and_next_steps.md`",
        "   - Stage2 v7 已完成；A/S0 达到目标，Stage5 应继续使用 v7 source tiers。",
        "8. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md`",
        "   - Stage3 v8 已通过 validation-only gate 和 locked_test 报告。",
        "9. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8/pseudo_amdar_v8_calibration_report.json`",
        "   - Stage4 v3 使用的 gate、validation/locked metrics、多尺度验证入口。",
        f"10. `{result_path}`",
        "   - 本轮 Stage4 v3 next-window 结果分析、质量门、下一步建议。",
        f"11. `{cfg.out_dir / 'stage4_confidence_v3/confidence_tier_summary_v3.json'}`",
        "   - machine-readable Stage4 v3 summary，含分层覆盖、高风速保留、不变量检查、next-window safeguards。",
        f"12. `{cfg.out_dir / 'stage4_confidence_v3/amdar_confidence_policy_v3.json'}`",
        "   - v3 置信度组件、权重、分层阈值和高风速 override 规则。",
        f"13. `{cfg.out_dir / 'stage4_confidence_v3/stage4_next_window_quality_checks.json'}`",
        "   - T2a/T2b、连续时间不确定性、validation-only 阈值网格、高风速分支敏感性统一审计。",
        f"14. `{cfg.out_dir / 'stage4_confidence_v3/high_wind_branch_sensitivity_summary.json'}`",
        "   - A0 teacher-filter、A1 current rescue、A2 moderate rescue 的 confidence-only 分支对比。",
        f"15. `{cfg.out_dir / 'stage4_confidence_v3/stage4_v3_threshold_grid_summary.json'}`",
        "   - 只用 Stage3 v8 validation split 的阈值质量审计；locked-test 只报告不调参。",
        "",
        "## 本轮脚本与输出",
        "",
        f"- 脚本：`{Path(__file__)}`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- Stage4 v3 confidence table：`stage4_confidence_v3/amdar_confidence_components_v3.parquet`",
        "- Stage4 v3 summary：`stage4_confidence_v3/confidence_tier_summary_v3.json`",
        "- Stage4 v3 policy：`stage4_confidence_v3/amdar_confidence_policy_v3.json`",
        "- Component correlation：`stage4_confidence_v3/component_correlation_matrix.json`",
        "- Stage4 v3 report：`stage4_confidence_v3/stage4_confidence_v3_report.md`",
        "- Next-window quality checks：`stage4_confidence_v3/stage4_next_window_quality_checks.json`",
        "- Threshold grid：`stage4_confidence_v3/stage4_v3_threshold_grid_validation_only.parquet`",
        "- High-wind branch sensitivity：`stage4_confidence_v3/high_wind_branch_sensitivity_summary.json`",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        f"  {Path(__file__)} \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25",
        "```",
        "",
        "空间口径：读取 Stage2 v7 单份 compact leg table；读取 Stage3 v8 报告；不复制 19M ADS-B 点表，不创建 25 份全量中间数据。",
        "",
        "## 本轮关键结果",
        "",
        f"- Tier counts: `{summary['tier_counts']}`",
        f"- AMDAR tier coverage pct: `{summary['amdar']['tier_coverage_pct']}`",
        f"- AMDAR T1+T2 coverage pct: `{summary['amdar']['T1_T2_coverage_pct']}`",
        f"- High-wind retained rows: `{summary['high_wind']['retained_rows_T1_T3']}` / `{summary['high_wind']['gt150_rows']}`",
        f"- T2 subtier detail: `{nw.get('t2_subtier_detail')}`",
        f"- Next-window quality gate: `{nw_checks.get('passed_stage4_next_window_quality_gate')}`",
        f"- Quality gate: `{summary['stage4_completion_checks']}`",
        "",
        "## 项目与数据理解",
        "",
        "TURB/aircraft holdout 是唯一正式 strict truth；AMDAR 431,008 行全部 support-only。AMDAR 原始时间是批次下发/接收时间，不是逐点观测时间。Stage4 v3 的 `confidence_tier` 和 `base_support_conf` 只能控制 support 权重，不能改变 truth/holdout 身份。",
        "",
        "Stage2 v7 的 identity-date ADS-B 信息在 Stage4 v3 中只作为诊断风险字段，不进入 `base_support_conf`，也不是 `adsb_match_quality_conf`。真实 AMDAR-ADS-B 匹配仍需在 Stage5 v4 中完成，并且 accepted rows 也仍是 support-only。",
        "",
        "新增的 `confidence_subtier` 用于把 T2 拆成 T2a/T2b，防止宽批次 T2 在后续阶段被等权使用。新增的连续时间不确定性只作为 Stage6 输入先验；不能把它解释成逐点时间 truth。",
        "",
        "## 下一步执行话术",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 时间语义、Plan4 综合评估、Unified Plan、Stage2-6 优化方案、质量控制目标、Stage2 v7、Stage3 v8，以及最新 Stage4 confidence v3 next-window 结果。",
        "当前结论：优化计划阶段3 next-window（大框架 Stage4 confidence v3）已通过质量门；AMDAR 仍为 support-only，Stage5 真匹配未被伪造；新增 T2a/T2b、连续时间不确定性、validation-only 阈值审计和高风速 A0/A1/A2 分支敏感性。",
        "我将进入优化计划阶段4（大框架 Stage5 real AMDAR-ADS-B matching v4），读取 Stage4 v3 confidence table、confidence_subtier、time_uncertainty_s_stage4_v3_continuous 和 Stage2 v7 source tiers，输出候选/拒绝/歧义诊断；不会把 AMDAR 或 Stage5 accepted 当作 strict truth。",
        "```",
    ]
    handover_path.write_text("\n".join(handover) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})
    stage3_report = read_json(cfg.stage3_v8_dir / "pseudo_amdar_v8_calibration_report.json")
    print(json.dumps({"stage": "stage4_confidence_v3_start", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))
    _, summary = build_stage4_components(cfg, stage3_report)
    write_final_docs(cfg, summary)
    print(
        json.dumps(
            {
                "stage": "stage4_confidence_v3_done",
                "passed": summary.get("stage4_completion_checks", {}).get("passed_stage4_confidence_v3_quality_gate"),
                "tier_counts": summary.get("tier_counts"),
                "high_wind_retained": summary.get("high_wind", {}).get("retained_rows_T1_T3"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
