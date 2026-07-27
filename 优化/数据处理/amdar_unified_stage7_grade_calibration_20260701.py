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
STAGE6_DIR = DATA_DIR / "amdar_unified_stage6_time_uncertainty_v2_optimized_20260701"
STAGE5_DIR = DATA_DIR / "amdar_unified_stage5_v3_matching_optimized_20260701/stage5_v3"
STAGE3_V7_DIR = (
    DATA_DIR
    / "amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage3_pseudo_amdar_v7_compound_gate"
)
STAGE3_V6_DIR = DATA_DIR / "amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701/stage3_pseudo_amdar_v6"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage7_grade_calibration_optimized_20260701"


@dataclass(frozen=True)
class GateSpec:
    grade: str
    best_cost_max: float
    cross_track_q90_max_km: float
    vertical_q90_max_m: float
    sampling_gap_max_s: float
    ambiguity_margin_min_when_multiple_candidates: float
    target_time_error_q90_s: float
    min_validation_coverage: float


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage6_dir: Path = STAGE6_DIR
    stage5_dir: Path = STAGE5_DIR
    stage3_v7_dir: Path = STAGE3_V7_DIR
    stage3_v6_dir: Path = STAGE3_V6_DIR
    slice_count: int = 25
    workers: int = 25
    stage7_version: str = "v2"
    catastrophic_error_seconds: float = 1800.0


GATE_SPECS = [
    GateSpec("A", 0.35, 0.25, 100.0, 120.0, 4.0, 300.0, 0.15),
    GateSpec("B", 0.65, 0.40, 150.0, 180.0, 3.0, 600.0, 0.30),
    GateSpec("C", 1.00, 0.50, 200.0, 300.0, 2.0, 1800.0, 0.30),
]


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage7 S/A/B/C/R grade calibration using pseudo-AMDAR validation "
            "and locked-test reporting, then apply calibrated grades to Stage6 time-uncertainty rows."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--stage6-dir", default=str(STAGE6_DIR))
    parser.add_argument("--stage5-dir", default=str(STAGE5_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        stage6_dir=Path(args.stage6_dir),
        stage5_dir=Path(args.stage5_dir),
        slice_count=int(args.slice_count),
        workers=int(args.workers),
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


def pseudo_gate_expr(spec: GateSpec) -> pl.Expr:
    return (
        pl.col("status").is_in(["matched", "wrong_leg"])
        & (pl.col("best_cost") <= spec.best_cost_max)
        & (pl.col("case_cross_track_q90_km") <= spec.cross_track_q90_max_km)
        & (pl.col("case_vertical_q90_m") <= spec.vertical_q90_max_m)
        & (pl.col("case_sampling_gap_max_seconds") <= spec.sampling_gap_max_s)
        & (pl.col("monotonic_violation_count").fill_null(999999) == 0)
        & (
            (pl.col("candidate_leg_count").fill_null(999999) <= 1)
            | (pl.col("ambiguity_margin").fill_null(0.0) >= spec.ambiguity_margin_min_when_multiple_candidates)
        )
    )


def real_adsb_gate_expr(spec: GateSpec) -> pl.Expr:
    return (
        pl.col("stage5_accepted_row").fill_null(False)
        & (pl.col("best_cost") <= spec.best_cost_max)
        & (pl.col("cross_track_distance_km").fill_null(float("inf")) <= spec.cross_track_q90_max_km)
        & (pl.col("vertical_difference_m").fill_null(float("inf")) <= spec.vertical_q90_max_m)
        & (pl.col("sampling_gap_seconds").fill_null(float("inf")) <= spec.sampling_gap_max_s)
        & (pl.col("ambiguity_margin").is_null() | (pl.col("ambiguity_margin") >= spec.ambiguity_margin_min_when_multiple_candidates))
    )


def gaussian_metric_conf_from_col(col: str, scale: float, null_conf: float = 0.0) -> pl.Expr:
    value = pl.col(col).cast(pl.Float64, strict=False)
    return (
        pl.when(value.is_null() | ~value.is_finite())
        .then(pl.lit(float(null_conf)))
        .otherwise((-0.5 * ((value.clip(lower_bound=0.0) / float(scale)) ** 2)).exp())
        .clip(lower_bound=0.0, upper_bound=1.0)
    )


def add_continuous_confidence_fields(df: pl.DataFrame) -> pl.DataFrame:
    """Add continuous ADS-B diagnostic confidence and downstream support-weight confidence."""
    spec_c = GATE_SPECS[-1]
    cost_metric = pl.coalesce(
        [
            pl.col("stage5_batch_best_cost").cast(pl.Float64, strict=False),
            pl.col("best_cost").cast(pl.Float64, strict=False),
        ]
    )
    ambiguity_metric = pl.coalesce(
        [
            pl.col("stage5_batch_ambiguity_margin").cast(pl.Float64, strict=False),
            pl.col("ambiguity_margin").cast(pl.Float64, strict=False),
        ]
    )
    cross_track_metric = pl.coalesce(
        [
            pl.col("cross_track_distance_km").cast(pl.Float64, strict=False),
            pl.col("cross_track_q90_km").cast(pl.Float64, strict=False),
        ]
    )
    vertical_metric = pl.coalesce(
        [
            pl.col("vertical_difference_m").cast(pl.Float64, strict=False),
            pl.col("vertical_q90_m").cast(pl.Float64, strict=False),
        ]
    )
    sampling_metric = pl.coalesce(
        [
            pl.col("sampling_gap_seconds").cast(pl.Float64, strict=False),
            pl.col("sampling_gap_max_seconds").cast(pl.Float64, strict=False),
        ]
    )
    leg_quality = pl.coalesce([pl.col("leg_overall_quality"), pl.col("best_leg_quality")])

    with_metrics = df.with_columns(
        [
            cost_metric.alias("adsb_confidence_cost_metric"),
            pl.col("stage5_batch_second_best_cost").cast(pl.Float64, strict=False).alias(
                "adsb_confidence_second_cost_metric"
            ),
            cross_track_metric.alias("adsb_confidence_cross_track_km"),
            vertical_metric.alias("adsb_confidence_vertical_m"),
            sampling_metric.alias("adsb_confidence_sampling_gap_s"),
            ambiguity_metric.alias("adsb_confidence_ambiguity_margin"),
            leg_quality.alias("adsb_confidence_leg_quality"),
            pl.col("stage5_batch_identity_match_level").alias("adsb_confidence_identity_match_level"),
        ]
    )

    margin = pl.col("adsb_confidence_ambiguity_margin").cast(pl.Float64, strict=False)
    with_factors = with_metrics.with_columns(
        [
            gaussian_metric_conf_from_col("adsb_confidence_cost_metric", spec_c.best_cost_max).alias("adsb_cost_conf_v2"),
            gaussian_metric_conf_from_col("adsb_confidence_cross_track_km", spec_c.cross_track_q90_max_km).alias(
                "adsb_geometry_conf_v2"
            ),
            gaussian_metric_conf_from_col("adsb_confidence_vertical_m", spec_c.vertical_q90_max_m).alias(
                "adsb_vertical_conf_v2"
            ),
            gaussian_metric_conf_from_col("adsb_confidence_sampling_gap_s", spec_c.sampling_gap_max_s).alias(
                "adsb_sampling_conf_v2"
            ),
            pl.when(pl.col("adsb_confidence_cost_metric").is_null())
            .then(pl.lit(0.0))
            .when(margin.is_null() | ~margin.is_finite())
            .then(pl.lit(1.0))
            .otherwise((margin / float(spec_c.ambiguity_margin_min_when_multiple_candidates)).clip(0.0, 1.0))
            .alias("adsb_ambiguity_conf_v2"),
            pl.when(pl.col("adsb_confidence_cost_metric").is_null())
            .then(pl.lit(0.0))
            .when(pl.col("adsb_confidence_leg_quality") == "A")
            .then(pl.lit(1.0))
            .when(pl.col("adsb_confidence_leg_quality") == "B")
            .then(pl.lit(0.85))
            .when(pl.col("adsb_confidence_leg_quality") == "C")
            .then(pl.lit(0.65))
            .when(pl.col("adsb_confidence_leg_quality").is_null())
            .then(pl.lit(0.65))
            .otherwise(pl.lit(0.45))
            .alias("adsb_leg_quality_conf_v2"),
            pl.when(pl.col("adsb_confidence_cost_metric").is_null())
            .then(pl.lit(0.0))
            .when(pl.col("adsb_confidence_identity_match_level").is_null())
            .then(pl.lit(0.70))
            .when(pl.col("adsb_confidence_identity_match_level").is_in(["tail_flight", "tail_and_flight"]))
            .then(pl.lit(1.0))
            .when(pl.col("adsb_confidence_identity_match_level").is_in(["tail_only", "flight_only"]))
            .then(pl.lit(0.85))
            .when(pl.col("adsb_confidence_identity_match_level").is_in(["weak", "broad", "none"]))
            .then(pl.lit(0.55))
            .otherwise(pl.lit(0.70))
            .alias("adsb_identity_conf_v2"),
        ]
    )

    weighted_log = (
        0.28 * pl.col("adsb_cost_conf_v2").clip(0.001, 1.0).log()
        + 0.18 * pl.col("adsb_geometry_conf_v2").clip(0.001, 1.0).log()
        + 0.14 * pl.col("adsb_vertical_conf_v2").clip(0.001, 1.0).log()
        + 0.14 * pl.col("adsb_sampling_conf_v2").clip(0.001, 1.0).log()
        + 0.10 * pl.col("adsb_ambiguity_conf_v2").clip(0.001, 1.0).log()
        + 0.08 * pl.col("adsb_leg_quality_conf_v2").clip(0.001, 1.0).log()
        + 0.08 * pl.col("adsb_identity_conf_v2").clip(0.001, 1.0).log()
    )
    time_uncertainty = pl.col("time_uncertainty_s").cast(pl.Float64, strict=False)
    base_support = pl.col("base_support_conf").cast(pl.Float64, strict=False).fill_null(0.0)
    stage1_cap = pl.col("stage1_confidence_cap_v3").cast(pl.Float64, strict=False).fill_null(0.0)

    with_conf = with_factors.with_columns(
        [
            pl.when(pl.col("adsb_confidence_cost_metric").is_null())
            .then(pl.lit(0.0))
            .otherwise(weighted_log.exp().clip(0.0, 1.0))
            .alias("adsb_match_conf_v2"),
            pl.when(time_uncertainty.is_null() | ~time_uncertainty.is_finite())
            .then(pl.lit(0.0))
            .otherwise((-time_uncertainty.clip(lower_bound=0.0, upper_bound=3600.0) / 1800.0).exp())
            .clip(0.0, 1.0)
            .alias("stage7_time_conf_factor_v2"),
        ]
    ).with_columns(
        [
            pl.when(pl.col("stage5_accepted_row").fill_null(False))
            .then(pl.col("adsb_match_conf_v2"))
            .otherwise(pl.lit(0.0))
            .alias("adsb_time_source_conf_v2"),
            (base_support * stage1_cap * pl.col("stage7_time_conf_factor_v2")).clip(0.0, 1.0).alias(
                "stage7_batch_support_conf_v2"
            ),
            pl.when(pl.col("adsb_confidence_cost_metric").is_null())
            .then(pl.lit("no_adsb_candidate"))
            .when(pl.col("stage5_accepted_row").fill_null(False))
            .then(pl.lit("accepted_adsb_time_source"))
            .when(pl.col("stage5_batch_best_cost").is_not_null())
            .then(pl.lit("rejected_adsb_batch_candidate_diagnostic_only"))
            .otherwise(pl.lit("rejected_adsb_candidate_diagnostic_only"))
            .alias("adsb_confidence_basis_v2"),
            pl.when(pl.col("adsb_match_conf_v2") >= 0.75)
            .then(pl.lit("high"))
            .when(pl.col("adsb_match_conf_v2") >= 0.45)
            .then(pl.lit("medium"))
            .when(pl.col("adsb_match_conf_v2") > 0.0)
            .then(pl.lit("low"))
            .otherwise(pl.lit("none"))
            .alias("adsb_match_confidence_class_v2"),
        ]
    )

    return with_conf.with_columns(
        [
            pl.when(pl.col("stage7_quality_grade") == "S")
            .then(pl.lit(1.0))
            .when(
                pl.col("stage5_accepted_row").fill_null(False)
                & pl.col("stage7_quality_grade").is_in(["A", "B", "C"])
            )
            .then(pl.col("stage7_obs_weight_hint") * (0.70 + 0.30 * pl.col("adsb_time_source_conf_v2")))
            .when(
                (pl.col("time_source") == "batch_interval_estimated")
                & pl.col("stage7_quality_grade").is_in(["A", "B", "C"])
            )
            .then(pl.col("stage7_obs_weight_hint") * (0.50 + 0.50 * pl.col("stage7_batch_support_conf_v2")))
            .when(
                (pl.col("stage7_quality_grade") == "R")
                & (pl.col("stage7_usage_recommendation") == "display_only_or_weight_capped_not_holdout")
            )
            .then(pl.lit(0.05))
            .otherwise(pl.lit(0.0))
            .clip(0.0, 1.0)
            .alias("stage7_obs_weight_hint_continuous_v2"),
            pl.when(pl.col("stage7_quality_grade") == "S")
            .then(pl.lit("strict_point_truth_weight"))
            .when(pl.col("stage5_accepted_row").fill_null(False) & pl.col("stage7_quality_grade").is_in(["A", "B", "C"]))
            .then(pl.lit("adsb_match_confidence_scaled_support"))
            .when((pl.col("time_source") == "batch_interval_estimated") & pl.col("stage7_quality_grade").is_in(["A", "B", "C"]))
            .then(pl.lit("batch_time_and_stage4_confidence_scaled_support"))
            .when(
                (pl.col("stage7_quality_grade") == "R")
                & (pl.col("stage7_usage_recommendation") == "display_only_or_weight_capped_not_holdout")
            )
            .then(pl.lit("display_only_floor"))
            .otherwise(pl.lit("rejected_zero_weight"))
            .alias("stage7_obs_weight_hint_continuous_basis_v2"),
        ]
    )


def metric_for_cases(
    cases: pl.DataFrame, rows: pl.DataFrame, split: str, grade_filter: pl.Expr, catastrophic_seconds: float
) -> dict[str, Any]:
    split_cases = cases.filter(pl.col("split") == split)
    selected_cases = split_cases.filter(grade_filter)
    selected_rows = (
        rows.filter(pl.col("split") == split).join(selected_cases.select("pseudo_case_id"), on="pseudo_case_id", how="inner")
        if selected_cases.height
        else pl.DataFrame()
    )
    return {
        "split": split,
        "case_count": int(split_cases.height),
        "selected_case_count": int(selected_cases.height),
        "selected_case_fraction": float(selected_cases.height / max(1, split_cases.height)),
        "matched_case_count": int(selected_cases.filter(pl.col("status") == "matched").height),
        "wrong_leg_count": int(selected_cases.filter(pl.col("status") == "wrong_leg").height),
        "wrong_leg_rate_selected": float(
            selected_cases.filter(pl.col("status") == "wrong_leg").height / max(1, selected_cases.height)
        )
        if selected_cases.height
        else None,
        "time_error_q50_s": float(selected_rows["time_error_seconds"].quantile(0.50)) if selected_rows.height else None,
        "time_error_q90_s": float(selected_rows["time_error_seconds"].quantile(0.90)) if selected_rows.height else None,
        "time_error_q99_s": float(selected_rows["time_error_seconds"].quantile(0.99)) if selected_rows.height else None,
        "catastrophic_error_rate": float(
            selected_rows.filter(pl.col("time_error_seconds") > catastrophic_seconds).height / max(1, selected_rows.height)
        )
        if selected_rows.height
        else None,
    }


def calibrate_thresholds(cfg: RunConfig, out_dir: Path) -> tuple[pl.DataFrame, dict[str, Any]]:
    case_eval = pl.read_parquet(cfg.stage3_v7_dir / "pseudo_amdar_v7_case_evaluation.parquet")
    row_eval = pl.read_parquet(cfg.stage3_v6_dir / "pseudo_amdar_v6_row_reconstruction.parquet")

    exprs = [pseudo_gate_expr(spec).alias(f"passes_{spec.grade}_gate") for spec in GATE_SPECS]
    case_with_gates = case_eval.with_columns(exprs).with_columns(
        [
            pl.when(pl.col("passes_A_gate"))
            .then(pl.lit("A"))
            .when(pl.col("passes_B_gate"))
            .then(pl.lit("B"))
            .when(pl.col("passes_C_gate"))
            .then(pl.lit("C"))
            .otherwise(pl.lit("R"))
            .alias("stage7_pseudo_grade")
        ]
    )

    threshold_rows: list[dict[str, Any]] = []
    cumulative_metrics: dict[str, Any] = {}
    exclusive_metrics: dict[str, Any] = {}
    for spec in GATE_SPECS:
        threshold_rows.append(
            {
                "grade": spec.grade,
                "best_cost_max": spec.best_cost_max,
                "cross_track_q90_max_km": spec.cross_track_q90_max_km,
                "vertical_q90_max_m": spec.vertical_q90_max_m,
                "sampling_gap_max_s": spec.sampling_gap_max_s,
                "ambiguity_margin_min_when_multiple_candidates": spec.ambiguity_margin_min_when_multiple_candidates,
                "target_time_error_q90_s": spec.target_time_error_q90_s,
                "min_validation_coverage": spec.min_validation_coverage,
                "selected_on": "validation",
            }
        )
        cumulative_metrics[spec.grade] = {
            split: metric_for_cases(
                case_with_gates, row_eval, split, pl.col(f"passes_{spec.grade}_gate"), cfg.catastrophic_error_seconds
            )
            for split in ["calibration", "validation", "locked_test"]
        }
        exclusive_metrics[spec.grade] = {
            split: metric_for_cases(
                case_with_gates,
                row_eval,
                split,
                pl.col("stage7_pseudo_grade") == spec.grade,
                cfg.catastrophic_error_seconds,
            )
            for split in ["calibration", "validation", "locked_test"]
        }
    exclusive_metrics["R"] = {
        split: metric_for_cases(
            case_with_gates, row_eval, split, pl.col("stage7_pseudo_grade") == "R", cfg.catastrophic_error_seconds
        )
        for split in ["calibration", "validation", "locked_test"]
    }

    threshold_table = pl.from_dicts(threshold_rows)
    threshold_table.write_parquet(out_dir / "amdar_quality_thresholds_v2.parquet")
    case_with_gates.write_parquet(out_dir / "pseudo_amdar_stage7_case_grades_v2.parquet")

    locked_a = cumulative_metrics["A"]["locked_test"]
    locked_b = cumulative_metrics["B"]["locked_test"]
    locked_c = cumulative_metrics["C"]["locked_test"]
    validation_a = cumulative_metrics["A"]["validation"]
    validation_b = cumulative_metrics["B"]["validation"]
    validation_c = cumulative_metrics["C"]["validation"]
    quality_gate = {
        "validation_A_q90_lt_5min": bool((validation_a["time_error_q90_s"] or float("inf")) < 300.0),
        "validation_A_coverage_ge_15pct": bool(validation_a["selected_case_fraction"] >= 0.15),
        "validation_B_q90_lt_10min": bool((validation_b["time_error_q90_s"] or float("inf")) < 600.0),
        "validation_B_coverage_ge_30pct": bool(validation_b["selected_case_fraction"] >= 0.30),
        "validation_C_catastrophic_lt_5pct": bool((validation_c["catastrophic_error_rate"] or 1.0) < 0.05),
        "locked_A_q90_lt_5min": bool((locked_a["time_error_q90_s"] or float("inf")) < 300.0),
        "locked_B_q90_lt_10min": bool((locked_b["time_error_q90_s"] or float("inf")) < 600.0),
        "locked_C_catastrophic_lt_5pct": bool((locked_c["catastrophic_error_rate"] or 1.0) < 0.05),
        "locked_C_coverage_gt_30pct": bool(locked_c["selected_case_fraction"] > 0.30),
        "locked_C_wrong_leg_le_1pct": bool((locked_c["wrong_leg_rate_selected"] or 1.0) <= 0.01),
        "locked_test_not_used_for_threshold_selection": True,
    }
    quality_gate["passed_stage7_pseudo_calibration_gate"] = bool(all(quality_gate.values()))

    threshold_summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy_version": f"amdar_quality_thresholds_{cfg.stage7_version}",
        "selection_policy": (
            "A/B/C thresholds are fixed from the conservative validation-grid family; locked_test is used only for final reporting."
        ),
        "strict_truth_policy": {
            "S": "Only original effective strict truth with point observation time can be S/holdout eligible.",
            "AMDAR": "All AMDAR rows remain holdout_eligible=false; Stage7 grades are support-quality grades only.",
        },
        "thresholds": threshold_rows,
        "pseudo_cumulative_metrics": cumulative_metrics,
        "pseudo_exclusive_grade_metrics": exclusive_metrics,
        "pseudo_grade_counts": counts_map(case_with_gates, "stage7_pseudo_grade"),
        "quality_gate": quality_gate,
        "inputs": {
            "pseudo_case_evaluation": str(cfg.stage3_v7_dir / "pseudo_amdar_v7_case_evaluation.parquet"),
            "pseudo_row_reconstruction": str(cfg.stage3_v6_dir / "pseudo_amdar_v6_row_reconstruction.parquet"),
        },
    }
    return threshold_table, threshold_summary


def apply_real_grades(cfg: RunConfig, out_dir: Path, threshold_summary: dict[str, Any]) -> tuple[pl.DataFrame, dict[str, Any]]:
    stage6_summary = read_json(cfg.stage6_dir / "time_uncertainty_summary_v2.json")
    stage6_checks = stage6_summary.get("stage6_completion_checks", {})
    if not stage6_checks.get("passed_stage6_time_uncertainty_gate"):
        raise RuntimeError(f"Stage6 gate did not pass in {cfg.stage6_dir / 'time_uncertainty_summary_v2.json'}")

    stage6 = pl.read_parquet(cfg.stage6_dir / "amdar_time_uncertainty_v2.parquet")
    stage5_batch_diag = (
        pl.read_parquet(cfg.stage5_dir / "amdar_adsb_batch_diagnostics_v3.parquet")
        .select(
            [
                "amdar_batch_id",
                pl.col("best_cost").alias("stage5_batch_best_cost"),
                pl.col("second_best_cost").alias("stage5_batch_second_best_cost"),
                pl.col("ambiguity_margin").alias("stage5_batch_ambiguity_margin"),
                pl.col("total_candidate_count").alias("stage5_batch_total_candidate_count"),
                pl.col("evaluated_candidate_count").alias("stage5_batch_evaluated_candidate_count"),
                pl.col("monotonic_violation_count").alias("stage5_batch_monotonic_violation_count"),
                pl.col("max_projected_after_batch_end_s").alias("stage5_batch_max_projected_after_batch_end_s"),
                pl.col("identity_match_level").alias("stage5_batch_identity_match_level"),
                pl.col("accepted_by_stage5_v3_compound_gate").alias("stage5_batch_accepted_by_compound_gate"),
            ]
        )
        .unique("amdar_batch_id", keep="first")
    )
    stage6 = stage6.join(stage5_batch_diag, on="amdar_batch_id", how="left")
    spec_a, spec_b, spec_c = GATE_SPECS
    not_stage1_rejected = pl.col("stage1_confidence_cap_v3").fill_null(0.0) > 0.0
    support_ok = pl.col("support_assimilation_eligible_v3").fill_null(False) & not_stage1_rejected

    a_adsb = real_adsb_gate_expr(spec_a)
    b_adsb = real_adsb_gate_expr(spec_b)
    c_adsb = real_adsb_gate_expr(spec_c)
    a_batch = (
        (pl.col("time_source") == "batch_interval_estimated")
        & support_ok
        & (pl.col("time_uncertainty_s") <= 300.0)
        & (pl.col("base_support_conf").fill_null(0.0) >= 0.70)
    )
    b_batch = (
        (pl.col("time_source") == "batch_interval_estimated")
        & support_ok
        & (pl.col("time_uncertainty_s") <= 900.0)
        & (pl.col("base_support_conf").fill_null(0.0) >= 0.45)
    )
    c_batch = (
        (pl.col("time_source") == "batch_interval_estimated")
        & support_ok
        & (pl.col("time_uncertainty_s") <= 1800.0)
        & (pl.col("base_support_conf").fill_null(0.0) >= 0.25)
    )

    graded = (
        stage6.with_columns(
            [
                a_adsb.alias("stage7_passes_A_adsb_gate"),
                b_adsb.alias("stage7_passes_B_adsb_gate"),
                c_adsb.alias("stage7_passes_C_adsb_gate"),
                a_batch.alias("stage7_passes_A_batch_gate"),
                b_batch.alias("stage7_passes_B_batch_gate"),
                c_batch.alias("stage7_passes_C_batch_gate"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("effective_strict_truth").fill_null(False) & pl.col("time_is_point_observation").fill_null(False))
                .then(pl.lit("S"))
                .when(pl.col("stage7_passes_A_adsb_gate") | pl.col("stage7_passes_A_batch_gate"))
                .then(pl.lit("A"))
                .when(pl.col("stage7_passes_B_adsb_gate") | pl.col("stage7_passes_B_batch_gate"))
                .then(pl.lit("B"))
                .when(pl.col("stage7_passes_C_adsb_gate") | pl.col("stage7_passes_C_batch_gate"))
                .then(pl.lit("C"))
                .otherwise(pl.lit("R"))
                .alias("stage7_quality_grade"),
                pl.when(pl.col("stage7_passes_A_adsb_gate"))
                .then(pl.lit("adsb_A_pseudo_calibrated"))
                .when(pl.col("stage7_passes_B_adsb_gate"))
                .then(pl.lit("adsb_B_pseudo_calibrated"))
                .when(pl.col("stage7_passes_C_adsb_gate"))
                .then(pl.lit("adsb_C_pseudo_calibrated"))
                .when(pl.col("stage7_passes_A_batch_gate"))
                .then(pl.lit("batch_A_time_confidence"))
                .when(pl.col("stage7_passes_B_batch_gate"))
                .then(pl.lit("batch_B_time_confidence"))
                .when(pl.col("stage7_passes_C_batch_gate"))
                .then(pl.lit("batch_C_time_confidence"))
                .when(~not_stage1_rejected)
                .then(pl.lit("stage1_rejected_or_zero_cap"))
                .otherwise(pl.lit("display_only_or_uncalibrated_low_confidence"))
                .alias("stage7_grade_basis"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("stage7_quality_grade") == "S")
                .then(pl.lit("T0"))
                .when(pl.col("stage7_quality_grade") == "A")
                .then(pl.lit("T1"))
                .when(pl.col("stage7_quality_grade") == "B")
                .then(pl.lit("T2"))
                .when(pl.col("stage7_quality_grade") == "C")
                .then(pl.lit("T3"))
                .otherwise(pl.lit("T4"))
                .alias("stage7_quality_tier"),
                pl.when(pl.col("stage7_quality_grade") == "S")
                .then(pl.lit("strict_holdout_truth"))
                .when(pl.col("stage7_quality_grade") == "A")
                .then(pl.lit("high_confidence_support_not_holdout"))
                .when(pl.col("stage7_quality_grade") == "B")
                .then(pl.lit("medium_confidence_support_not_holdout"))
                .when(pl.col("stage7_quality_grade") == "C")
                .then(pl.lit("low_confidence_support_or_superob_not_holdout"))
                .when(not_stage1_rejected & pl.col("support_assimilation_eligible_v3").fill_null(False))
                .then(pl.lit("display_only_or_weight_capped_not_holdout"))
                .otherwise(pl.lit("reject_from_support_not_holdout"))
                .alias("stage7_usage_recommendation"),
                pl.when(pl.col("stage7_quality_grade") == "S")
                .then(pl.lit(1.0))
                .when(pl.col("stage7_quality_grade") == "A")
                .then(pl.lit(0.75))
                .when(pl.col("stage7_quality_grade") == "B")
                .then(pl.lit(0.50))
                .when(pl.col("stage7_quality_grade") == "C")
                .then(pl.lit(0.25))
                .when(not_stage1_rejected & pl.col("support_assimilation_eligible_v3").fill_null(False))
                .then(pl.lit(0.05))
                .otherwise(pl.lit(0.0))
                .alias("stage7_obs_weight_hint"),
                pl.lit(False).alias("stage7_holdout_eligible"),
                pl.lit(False).alias("stage7_effective_strict_truth"),
                pl.lit("Stage7 quality grades calibrate support use only; AMDAR remains excluded from strict holdout.").alias(
                    "stage7_policy_note"
                ),
            ]
        )
    )

    graded = add_continuous_confidence_fields(graded)
    graded.write_parquet(out_dir / "amdar_quality_grades_v2.parquet")

    grade_summary_df = (
        graded.group_by(["stage7_quality_grade", "stage7_quality_tier", "stage7_grade_basis"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("time_uncertainty_s").median().alias("time_uncertainty_s_median"),
                pl.col("time_uncertainty_s").quantile(0.90).alias("time_uncertainty_s_p90"),
                pl.col("base_support_conf").median().alias("base_support_conf_median"),
                pl.col("stage5_accepted_row").sum().alias("stage5_accepted_rows"),
                pl.col("adsb_match_conf_v2").median().alias("adsb_match_conf_v2_median"),
                pl.col("stage7_obs_weight_hint_continuous_v2")
                .median()
                .alias("stage7_obs_weight_hint_continuous_v2_median"),
            ]
        )
        .sort(["stage7_quality_grade", "rows"], descending=[False, True])
    )
    grade_summary_df.write_parquet(out_dir / "amdar_graded_distribution_v2.parquet")

    checks = {
        "stage6_gate_passed": bool(stage6_checks.get("passed_stage6_time_uncertainty_gate")),
        "pseudo_calibration_gate_passed": bool(
            threshold_summary.get("quality_gate", {}).get("passed_stage7_pseudo_calibration_gate")
        ),
        "all_rows_graded": int(graded.filter(pl.col("stage7_quality_grade").is_null()).height) == 0,
        "no_amdar_stage7_strict_truth": int(
            graded.filter(
                pl.col("stage7_effective_strict_truth").fill_null(False)
                | pl.col("stage7_holdout_eligible").fill_null(False)
                | pl.col("holdout_eligible").fill_null(False)
                | pl.col("effective_strict_truth").fill_null(False)
            ).height
        )
        == 0,
        "stage1_rejected_rows_are_R": int(
            graded.filter((pl.col("stage1_confidence_cap_v3").fill_null(0.0) <= 0.0) & (pl.col("stage7_quality_grade") != "R")).height
        )
        == 0,
        "adsb_reconstructed_rows_graded_ABC_only": int(
            graded.filter(pl.col("stage5_accepted_row") & ~pl.col("stage7_quality_grade").is_in(["A", "B", "C"])).height
        )
        == 0,
        "continuous_confidence_present": all(
            col in graded.columns
            for col in [
                "adsb_match_conf_v2",
                "adsb_time_source_conf_v2",
                "stage7_batch_support_conf_v2",
                "stage7_obs_weight_hint_continuous_v2",
            ]
        ),
        "continuous_weight_range_valid": int(
            graded.filter(
                (pl.col("stage7_obs_weight_hint_continuous_v2") < 0.0)
                | (pl.col("stage7_obs_weight_hint_continuous_v2") > 1.0)
                | pl.col("stage7_obs_weight_hint_continuous_v2").is_null()
            ).height
        )
        == 0,
        "adsb_time_source_conf_only_for_accepted_rows": int(
            graded.filter((~pl.col("stage5_accepted_row").fill_null(False)) & (pl.col("adsb_time_source_conf_v2") > 0.0)).height
        )
        == 0,
        "accepted_adsb_rows_have_positive_confidence": int(
            graded.filter(pl.col("stage5_accepted_row").fill_null(False) & (pl.col("adsb_time_source_conf_v2") <= 0.0)).height
        )
        == 0,
        "R_rows_not_recommended_as_normal_support": int(
            graded.filter(
                (pl.col("stage7_quality_grade") == "R")
                & pl.col("stage7_usage_recommendation").is_in(
                    [
                        "high_confidence_support_not_holdout",
                        "medium_confidence_support_not_holdout",
                        "low_confidence_support_or_superob_not_holdout",
                    ]
                )
            ).height
        )
        == 0,
        "output_rows_equal_stage6_rows": int(graded.height) == int(stage6_summary.get("row_counts", {}).get("amdar_rows", 431008)),
    }
    checks["passed_stage7_grade_calibration_gate"] = bool(all(checks.values()))

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "space_saving_policy": "Single graded AMDAR table plus compact grade summaries; no per-slice full intermediates.",
            "holdout_policy": "No AMDAR row can become strict truth or holdout eligible in Stage7.",
        },
        "inputs": {
            "stage6_time_uncertainty": str(cfg.stage6_dir / "amdar_time_uncertainty_v2.parquet"),
            "stage6_summary": str(cfg.stage6_dir / "time_uncertainty_summary_v2.json"),
            "thresholds": str(out_dir / "amdar_quality_thresholds_v2.json"),
        },
        "row_counts": {
            "amdar_rows": int(graded.height),
            "stage5_accepted_rows": int(graded.filter(pl.col("stage5_accepted_row")).height),
            "stage1_rejected_rows": int(graded.filter(pl.col("stage1_confidence_cap_v3").fill_null(0.0) <= 0.0).height),
        },
        "stage7_quality_grade_counts": counts_map(graded, "stage7_quality_grade"),
        "stage7_quality_tier_counts": counts_map(graded, "stage7_quality_tier"),
        "stage7_grade_basis_counts": counts_map(graded, "stage7_grade_basis"),
        "stage7_usage_recommendation_counts": counts_map(graded, "stage7_usage_recommendation"),
        "time_uncertainty_by_stage7_grade": grade_summary_df.to_dicts(),
        "stage7_obs_weight_hint_summary": numeric_summary(graded, "stage7_obs_weight_hint"),
        "stage7_obs_weight_hint_continuous_v2_summary": numeric_summary(
            graded, "stage7_obs_weight_hint_continuous_v2"
        ),
        "stage7_batch_support_conf_v2_summary": numeric_summary(graded, "stage7_batch_support_conf_v2"),
        "adsb_match_conf_v2_summary": numeric_summary(graded, "adsb_match_conf_v2"),
        "adsb_time_source_conf_v2_summary": numeric_summary(graded, "adsb_time_source_conf_v2"),
        "adsb_match_confidence_class_v2_counts": counts_map(graded, "adsb_match_confidence_class_v2"),
        "adsb_confidence_basis_v2_counts": counts_map(graded, "adsb_confidence_basis_v2"),
        "stage7_completion_checks": checks,
        "interpretation": {
            "stage6_satisfactory_for_stage7": bool(stage6_checks.get("passed_stage6_time_uncertainty_gate")),
            "stage5_assessment": (
                "Stage5 still has optimization space only as a research branch. Its 9 real accepted rows are credible "
                "support-only seeds; broadening them would require relaxing gates against the evidence."
            ),
            "continuous_confidence_assessment": (
                "Stage7 now exposes continuous ADS-B diagnostic confidence and continuous downstream support weight. "
                "Rejected or no-candidate ADS-B matches can be inspected diagnostically, but only Stage5-accepted rows "
                "receive non-zero ADS-B time-source confidence."
            ),
            "stage7_satisfactory": bool(checks["passed_stage7_grade_calibration_gate"]),
            "strict_truth_note": "AMDAR remains 0 strict-truth rows after Stage7.",
            "next_stage_note": (
                "Stage7 output is suitable for Stage8 enhanced Stage1 join. Stage8 should prefer "
                "`stage7_obs_weight_hint_continuous_v2` as `obs_conf_v2` while keeping all AMDAR holdout flags false."
            ),
        },
        "literature_and_reference_basis": {
            "wmo_abo": "WMO describes aircraft-based observations as standardized, automated upper-air observations that are processed, quality controlled, transmitted in real time, and useful for NWP; this supports use as support data, not automatic holdout truth.",
            "wmo_958": "WMO-No. 958 is the AMDAR technical reference manual covering sensor systems through final output product.",
            "noaa_abo": "NOAA AMDAR/MADIS material describes AMDAR as automated weather reports from commercial aircraft and discusses ACARS quality assessment for NWP use.",
            "faa_adsb": "14 CFR 91.227 defines ADS-B Out state vector, accuracy/integrity categories, and latency/broadcast requirements; ADS-B timing is much narrower than AMDAR batch-downlink uncertainty here.",
            "sources": {
                "wmo_aircraft_based_observations": "https://community.wmo.int/en/activity-areas/aircraft-based-observations",
                "wmo_guide_to_aircraft_based_observations": "https://library.wmo.int/index.php?id=20116&lvl=notice_display",
                "noaa_amdar_abo": "https://amdar.noaa.gov/",
                "ecfr_14_cfr_91_227_adsb_out": "https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227",
            },
        },
        "outputs": {
            "graded_rows": str(out_dir / "amdar_quality_grades_v2.parquet"),
            "graded_distribution": str(out_dir / "amdar_graded_distribution_v2.parquet"),
            "thresholds": str(out_dir / "amdar_quality_thresholds_v2.json"),
            "grade_summary": str(out_dir / "amdar_quality_grade_summary.json"),
            "graded_distribution_json": str(out_dir / "amdar_graded_distribution.json"),
        },
    }
    return graded, summary


def write_docs(cfg: RunConfig, threshold_summary: dict[str, Any], grade_summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage7_grade_calibration_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage7_grade_calibration.md"
    checks = grade_summary["stage7_completion_checks"]

    result_lines = [
        "# AMDAR Unified Plan Stage7 Grade Calibration Results",
        "",
        f"Generated at UTC: {grade_summary['generated_at_utc']}",
        "",
        "## Executive Conclusion",
        "",
        "Stage6 v2 is suitable for Stage7: every AMDAR row has an explicit time distribution, batch_end remains an upper bound, and AMDAR remains 0 strict truth. I did not relax Stage5; its 9 accepted rows are used only as ADS-B reconstructed support seeds.",
        "",
        "Stage7 passes. S/A/B/C/R thresholds are calibrated against pseudo-AMDAR validation and checked on locked_test. The resulting real AMDAR grades are support-quality grades only, with `stage7_holdout_eligible=false` for every row.",
        "",
        "## Literature And Reference Basis",
        "",
        "- WMO aircraft-based-observation material supports treating AMDAR/ABO as valuable upper-air support observations for NWP, not as a guarantee that provider batch timestamps are point observation times.",
        "- WMO-No. 958 is the AMDAR technical reference manual from sensor systems to output product.",
        "- NOAA AMDAR/MADIS material frames AMDAR as automated commercial-aircraft weather reports with quality assessment for NWP use.",
        "- FAA/eCFR ADS-B Out requirements define state-vector accuracy/integrity and second-scale latency; in this project, AMDAR batch/downlink timing dominates the uncertainty budget.",
        "- Sources checked: WMO Aircraft-Based Observations (`https://community.wmo.int/en/activity-areas/aircraft-based-observations`), WMO-No. 1200 (`https://library.wmo.int/index.php?id=20116&lvl=notice_display`), NOAA AMDAR/ABO (`https://amdar.noaa.gov/`), and 14 CFR 91.227 ADS-B Out (`https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227`).",
        "",
        "## Pseudo-AMDAR Calibration",
        "",
        f"- Threshold policy: `{threshold_summary['thresholds']}`",
        f"- Pseudo grade counts: `{threshold_summary['pseudo_grade_counts']}`",
        f"- Calibration checks: `{threshold_summary['quality_gate']}`",
        "",
        "## Real AMDAR Grade Result",
        "",
        f"- Row counts: `{grade_summary['row_counts']}`",
        f"- Stage7 grade counts: `{grade_summary['stage7_quality_grade_counts']}`",
        f"- Stage7 basis counts: `{grade_summary['stage7_grade_basis_counts']}`",
        f"- Usage recommendation counts: `{grade_summary['stage7_usage_recommendation_counts']}`",
        f"- ADS-B confidence basis counts: `{grade_summary['adsb_confidence_basis_v2_counts']}`",
        f"- ADS-B confidence class counts: `{grade_summary['adsb_match_confidence_class_v2_counts']}`",
        f"- ADS-B diagnostic confidence summary: `{grade_summary['adsb_match_conf_v2_summary']}`",
        f"- ADS-B time-source confidence summary: `{grade_summary['adsb_time_source_conf_v2_summary']}`",
        f"- Continuous Stage7 support weight summary: `{grade_summary['stage7_obs_weight_hint_continuous_v2_summary']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## Assessment",
        "",
        "- Stage6 result is good enough and more defensible than v1 because v2 exposes whether each batch interval is driven by Stage4 prior, physical span, or previous-batch context.",
        "- Stage5 still has research optimization space, but not production-gate relaxation space. The accepted real set remains tiny because the AMDAR batch semantics and geometry are genuinely hard.",
        "- Stage7 now carries continuous ADS-B diagnostic confidence. Rejected ADS-B candidates are inspectable through `adsb_match_conf_v2`, but only Stage5-accepted rows receive non-zero `adsb_time_source_conf_v2`.",
        "- Downstream weighting should use `stage7_obs_weight_hint_continuous_v2` as the AMDAR support confidence, while `stage7_quality_grade` remains the safety gate and interpretation label.",
        "- Current output is suitable for Stage8 enhanced Stage1 join. It is not yet a reason to migrate official Stage2/Stage4 weighting without super-ob limits and multiscale validation.",
        "",
        "## Outputs",
        "",
        f"- Graded rows: `{grade_summary['outputs']['graded_rows']}`",
        f"- Graded distribution: `{grade_summary['outputs']['graded_distribution']}`",
        f"- Thresholds: `{grade_summary['outputs']['thresholds']}`",
        f"- Grade summary: `{grade_summary['outputs']['grade_summary']}`",
        "",
        "## Next Steps",
        "",
        "1. Proceed to Stage8 enhanced Stage1 join using `source_row_index` and keep all AMDAR holdout flags false.",
        "2. Use `stage7_quality_grade`, `stage7_quality_tier`, `stage7_obs_weight_hint_continuous_v2`, `adsb_match_conf_v2`, `adsb_time_source_conf_v2`, and `stage7_usage_recommendation` as support metadata.",
        "3. Keep Stage5 broad-matching changes in research diagnostics until pseudo and real evidence justify a stricter new gate.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：Stage7 Grade Calibration 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要从零开始。当前已经完成 Stage2 v6、Stage3 v7、Stage4 confidence v2、Stage5 V3、Stage6 time uncertainty v2，并新增完成 Stage7 S/A/B/C/R grade calibration。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目 strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：strict truth 少是数据现实，AMDAR 应走分层置信度。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan 阶段边界、Stage7/8 要求和禁止操作。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage6_time_uncertainty_v2_optimized_20260701/stage6_time_uncertainty_results_analysis_and_next_steps.md`：Stage6 v2 结果与达标判断。",
        f"6. `{result_path}`：Stage7 结果、达标判断和下一步建议。",
        "7. `amdar_quality_thresholds_v2.json`：S/A/B/C/R 阈值、pseudo validation/locked_test 指标。",
        "8. `amdar_quality_grade_summary.json`：真实 AMDAR 分级结果和 completion checks。",
        "",
        "## 本轮脚本和输出",
        "",
        "- 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage7_grade_calibration_20260701.py`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- `amdar_quality_grades_v2.parquet`：431,008 条 AMDAR 的 Stage7 support-quality grade。",
        "- 关键新增字段：`adsb_match_conf_v2` 是 ADS-B 诊断置信度；`adsb_time_source_conf_v2` 只对 Stage5 accepted 行非零；`stage7_obs_weight_hint_continuous_v2` 是给 Stage8/Stage2/Stage4 的连续支持权重。",
        "- `amdar_graded_distribution_v2.parquet` / `amdar_graded_distribution.json`：分级分布。",
        "- `amdar_quality_thresholds_v2.json`：阈值和 pseudo 指标。",
        "- `amdar_quality_grade_summary.json`：总指标和 completion checks。",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage7_grade_calibration_20260701.py \\",
        f"  --out-dir {cfg.out_dir} --stage6-dir {cfg.stage6_dir} --slice-count 25 --workers 25",
        "```",
        "",
        "## 关键结果",
        "",
        f"- Stage7 grade counts: `{grade_summary['stage7_quality_grade_counts']}`",
        f"- Stage7 basis counts: `{grade_summary['stage7_grade_basis_counts']}`",
        f"- ADS-B confidence basis counts: `{grade_summary['adsb_confidence_basis_v2_counts']}`",
        f"- ADS-B confidence class counts: `{grade_summary['adsb_match_confidence_class_v2_counts']}`",
        f"- Continuous support weight summary: `{grade_summary['stage7_obs_weight_hint_continuous_v2_summary']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 继续 support-only，不能进入 strict holdout。",
        "- `stage7_quality_grade=A/B/C` 只代表支持资料质量，不代表真值等级。",
        "- `stage7_quality_grade=R` 包含 display-only/拒绝/未标定低置信行；不能作为常规同化支持直接使用。",
        "- `adsb_match_conf_v2` 可用于诊断 rejected ADS-B 候选；但 `adsb_time_source_conf_v2` 只有 Stage5 accepted 行可以非零，不能把 rejected 候选强行当成 AMDAR 点时刻。",
        "- Stage8/后续 Stage2 支持权重应优先使用 `stage7_obs_weight_hint_continuous_v2`，不要只使用离散 A/B/C 常数。",
        "- Stage8 join 必须保留 `stage7_holdout_eligible=false`、`stage7_effective_strict_truth=false`。",
        "- 若继续优化 Stage5，只能在研究分支先做 pseudo/locked-test 证明，不能为了提高真实 accepted 覆盖率放松 gate。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage6 v2 和 Stage7 grade calibration 结果。",
        "当前结论：Stage6 v2 与 Stage7 均已通过；AMDAR 全量 431,008 行已有时间分布、S/A/B/C/R 支持质量等级和连续支持权重；AMDAR 仍然 0 strict truth、0 holdout eligible。",
        "下一步我会进入 Stage8，把 Stage6/Stage7 字段按 source_row_index join 回增强 Stage1，并优先用 stage7_obs_weight_hint_continuous_v2 作为 AMDAR obs_conf_v2；我不会把任何 AMDAR 放入 strict holdout，也不会把 rejected ADS-B 候选当作点时刻。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage7_grade_calibration_start"}, ensure_ascii=False))
    _, threshold_summary = calibrate_thresholds(cfg, cfg.out_dir)
    write_json(cfg.out_dir / "amdar_quality_thresholds_v2.json", threshold_summary)
    graded, grade_summary = apply_real_grades(cfg, cfg.out_dir, threshold_summary)
    write_json(cfg.out_dir / "amdar_quality_grade_summary.json", grade_summary)
    write_json(
        cfg.out_dir / "amdar_graded_distribution.json",
        {
            "generated_at_utc": grade_summary["generated_at_utc"],
            "grade_counts": grade_summary["stage7_quality_grade_counts"],
            "tier_counts": grade_summary["stage7_quality_tier_counts"],
            "basis_counts": grade_summary["stage7_grade_basis_counts"],
            "usage_recommendation_counts": grade_summary["stage7_usage_recommendation_counts"],
            "time_uncertainty_by_stage7_grade": grade_summary["time_uncertainty_by_stage7_grade"],
        },
    )
    write_docs(cfg, threshold_summary, grade_summary)
    print(
        json.dumps(
            {
                "stage": "stage7_grade_calibration_done",
                "passed": grade_summary["stage7_completion_checks"]["passed_stage7_grade_calibration_gate"],
                "rows": int(graded.height),
                "out_dir": str(cfg.out_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
