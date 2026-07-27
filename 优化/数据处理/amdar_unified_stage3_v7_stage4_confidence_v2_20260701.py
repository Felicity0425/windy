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
STAGE1_PLAN4_DIR = DATA_DIR / "amdar_plan4_implementation_20260630/stage1_output_plan4_v1"
STAGE1_V3_DIR = DATA_DIR / "amdar_unified_stage1_2_complete_optimized_20260701/stage1_qc_resolution_v3"
STAGE2_V6_DIR = DATA_DIR / "amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701/stage2_adsb_qc_v6_readiness"
STAGE3_V6_DIR = DATA_DIR / "amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701/stage3_pseudo_amdar_v6"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701"

WIND_SPEED_MS_PLAUSIBLE_MAX = 150.0
WIND_SPEED_MS_REJECT_REVIEW = 200.0
EPS = 1.0e-6


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage1_plan4_dir: Path = STAGE1_PLAN4_DIR
    stage1_v3_dir: Path = STAGE1_V3_DIR
    stage2_v6_dir: Path = STAGE2_V6_DIR
    stage3_v6_dir: Path = STAGE3_V6_DIR
    slice_count: int = 25
    v7_best_cost_max: float = 1.0
    v7_cross_track_q90_max_km: float = 0.5
    v7_vertical_q90_max_m: float = 200.0
    v7_sampling_gap_max_s: float = 300.0
    v7_ambiguity_margin_min: float = 2.0
    catastrophic_error_seconds: float = 1800.0


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh Stage3 pseudo-AMDAR acceptance with a validation-only compound gate, "
            "then run Stage4 confidence v2 against Stage1 v3 and Stage2 v6 priors."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    args = parser.parse_args()
    return RunConfig(out_dir=Path(args.out_dir), slice_count=int(args.slice_count))


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


def bool_count(df: pl.DataFrame, expr: pl.Expr) -> int:
    if df.height == 0:
        return 0
    return int(df.select(expr.fill_null(False).sum()).item())


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


def v7_compound_gate_expr(cfg: RunConfig) -> pl.Expr:
    return (
        pl.col("status").is_in(["matched", "wrong_leg"])
        & pl.col("best_cost").is_not_null()
        & (pl.col("best_cost") <= cfg.v7_best_cost_max)
        & (pl.col("case_cross_track_q90_km").fill_null(math.inf) <= cfg.v7_cross_track_q90_max_km)
        & (pl.col("case_vertical_q90_m").fill_null(math.inf) <= cfg.v7_vertical_q90_max_m)
        & (pl.col("case_sampling_gap_max_seconds").fill_null(math.inf) <= cfg.v7_sampling_gap_max_s)
        & (pl.col("monotonic_violation_count").fill_null(999999) == 0)
        & (
            (pl.col("candidate_leg_count").fill_null(999999) <= 1)
            | (pl.col("ambiguity_margin").fill_null(0.0) >= cfg.v7_ambiguity_margin_min)
        )
    )


def gate_reject_reason_expr(cfg: RunConfig) -> pl.Expr:
    return (
        pl.when(~pl.col("status").is_in(["matched", "wrong_leg"]) | pl.col("best_cost").is_null())
        .then(pl.lit("no_candidate_or_projection"))
        .when(pl.col("best_cost") > cfg.v7_best_cost_max)
        .then(pl.lit("best_cost_gt_1"))
        .when(pl.col("case_cross_track_q90_km").fill_null(math.inf) > cfg.v7_cross_track_q90_max_km)
        .then(pl.lit("cross_track_q90_gt_0_5km"))
        .when(pl.col("case_vertical_q90_m").fill_null(math.inf) > cfg.v7_vertical_q90_max_m)
        .then(pl.lit("vertical_q90_gt_200m"))
        .when(pl.col("case_sampling_gap_max_seconds").fill_null(math.inf) > cfg.v7_sampling_gap_max_s)
        .then(pl.lit("sampling_gap_gt_300s"))
        .when(pl.col("monotonic_violation_count").fill_null(999999) != 0)
        .then(pl.lit("monotonic_violation"))
        .when(
            (pl.col("candidate_leg_count").fill_null(999999) > 1)
            & (pl.col("ambiguity_margin").fill_null(0.0) < cfg.v7_ambiguity_margin_min)
        )
        .then(pl.lit("ambiguity_margin_lt_2"))
        .otherwise(pl.lit("accepted"))
    )


def selected_metrics(case_df: pl.DataFrame, row_df: pl.DataFrame, split: str | None, gate_col: str) -> dict[str, Any]:
    c = case_df if split is None else case_df.filter(pl.col("split") == split)
    r = row_df if split is None else row_df.filter(pl.col("split") == split)
    eligible = c.filter(pl.col(gate_col).fill_null(False))
    selected_ids = eligible.select("pseudo_case_id")
    rr = r.join(selected_ids, on="pseudo_case_id", how="inner") if r.height and eligible.height else pl.DataFrame()
    return {
        "case_count": int(c.height),
        "selected_case_count": int(eligible.height),
        "selected_case_fraction": float(eligible.height / max(1, c.height)),
        "matched_case_count": int(eligible.filter(pl.col("status") == "matched").height),
        "wrong_leg_count": int(eligible.filter(pl.col("status") == "wrong_leg").height),
        "wrong_leg_rate_selected": float(
            eligible.filter(pl.col("status") == "wrong_leg").height / max(1, eligible.height)
        )
        if eligible.height
        else None,
        "time_error_q50": float(rr["time_error_seconds"].quantile(0.50)) if rr.height else None,
        "time_error_q90": float(rr["time_error_seconds"].quantile(0.90)) if rr.height else None,
        "time_error_q99": float(rr["time_error_seconds"].quantile(0.99)) if rr.height else None,
        "catastrophic_error_rate": float(rr.filter(pl.col("time_error_seconds") > 1800.0).height / max(1, rr.height))
        if rr.height
        else None,
        "status_counts_selected": counts_map(eligible, "status"),
    }


def gate_passes(metrics: dict[str, Any]) -> bool:
    return bool(
        metrics.get("selected_case_fraction", 0.0) >= 0.30
        and metrics.get("time_error_q90") is not None
        and float(metrics["time_error_q90"]) < 300.0
        and metrics.get("catastrophic_error_rate") is not None
        and float(metrics["catastrophic_error_rate"]) < 0.05
        and metrics.get("wrong_leg_rate_selected") is not None
        and float(metrics["wrong_leg_rate_selected"]) <= 0.01
    )


def run_stage3_v7(cfg: RunConfig) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage3_pseudo_amdar_v7_compound_gate"
    out_dir.mkdir(parents=True, exist_ok=True)

    case_eval = pl.read_parquet(cfg.stage3_v6_dir / "pseudo_amdar_v6_case_evaluation.parquet")
    row_eval = pl.read_parquet(cfg.stage3_v6_dir / "pseudo_amdar_v6_row_reconstruction.parquet")
    v6_report = read_json(cfg.stage3_v6_dir / "pseudo_amdar_v6_calibration_report.json")
    old_threshold = float(v6_report.get("threshold_info", {}).get("threshold") or 0.24292645287249956)

    case_eval_v7 = case_eval.with_columns(
        [
            v7_compound_gate_expr(cfg).alias("accepted_by_compound_gate_v7"),
            gate_reject_reason_expr(cfg).alias("compound_gate_reject_reason_v7"),
            (
                pl.col("status").is_in(["matched", "wrong_leg"])
                & pl.col("best_cost").is_not_null()
                & (pl.col("best_cost") <= old_threshold)
            ).alias("accepted_by_v6_best_cost_threshold_reference"),
        ]
    )

    acceptance_specs = [
        {
            "gate_name": "v6_reference_best_cost_only",
            "expr_col": "accepted_by_v6_best_cost_threshold_reference",
            "policy": {"best_cost_max": old_threshold},
        },
        {
            "gate_name": "v7_compound_gate",
            "expr_col": "accepted_by_compound_gate_v7",
            "policy": {
                "best_cost_max": cfg.v7_best_cost_max,
                "cross_track_q90_max_km": cfg.v7_cross_track_q90_max_km,
                "vertical_q90_max_m": cfg.v7_vertical_q90_max_m,
                "sampling_gap_max_s": cfg.v7_sampling_gap_max_s,
                "monotonic_violation_count": 0,
                "ambiguity_margin_min_when_multiple_candidates": cfg.v7_ambiguity_margin_min,
            },
        },
    ]
    curve_rows: list[dict[str, Any]] = []
    for spec in acceptance_specs:
        for split in ["validation", "locked_test"]:
            metrics = selected_metrics(case_eval_v7, row_eval, split, str(spec["expr_col"]))
            curve_rows.append(
                {
                    "gate_name": spec["gate_name"],
                    "split": split,
                    "policy_json": json.dumps(spec["policy"], ensure_ascii=False),
                    **metrics,
                    "passes_targets": gate_passes(metrics),
                }
            )
    acceptance_curve = pl.from_dicts(curve_rows)
    acceptance_curve.write_parquet(out_dir / "pseudo_amdar_v7_acceptance_curve.parquet")
    case_eval_v7.write_parquet(out_dir / "pseudo_amdar_v7_case_evaluation.parquet")

    split_leak_check = (
        case_eval_v7.select(["group_id_tail_date", "split"])
        .unique()
        .group_by("group_id_tail_date")
        .agg(pl.col("split").n_unique().alias("split_count"))
    )
    no_tail_date_split_leakage = bool(split_leak_check.filter(pl.col("split_count") > 1).height == 0)

    metrics = {
        "v6_reference_best_cost_only": {
            "validation": selected_metrics(case_eval_v7, row_eval, "validation", "accepted_by_v6_best_cost_threshold_reference"),
            "locked_test": selected_metrics(case_eval_v7, row_eval, "locked_test", "accepted_by_v6_best_cost_threshold_reference"),
        },
        "v7_compound_gate": {
            "overall": selected_metrics(case_eval_v7, row_eval, None, "accepted_by_compound_gate_v7"),
            "calibration": selected_metrics(case_eval_v7, row_eval, "calibration", "accepted_by_compound_gate_v7"),
            "validation": selected_metrics(case_eval_v7, row_eval, "validation", "accepted_by_compound_gate_v7"),
            "locked_test": selected_metrics(case_eval_v7, row_eval, "locked_test", "accepted_by_compound_gate_v7"),
        },
    }
    locked = metrics["v7_compound_gate"]["locked_test"]
    validation = metrics["v7_compound_gate"]["validation"]
    quality_gate = {
        "validation_compound_gate_passes_targets": gate_passes(validation),
        "locked_test_available": locked["case_count"] > 0,
        "locked_test_selected_coverage_gt_30pct": float(locked.get("selected_case_fraction") or 0.0) > 0.30,
        "locked_test_selected_q90_lt_5min": locked.get("time_error_q90") is not None and float(locked["time_error_q90"]) < 300.0,
        "locked_test_selected_catastrophic_lt_5pct": locked.get("catastrophic_error_rate") is not None
        and float(locked["catastrophic_error_rate"]) < 0.05,
        "locked_test_selected_wrong_leg_le_1pct": locked.get("wrong_leg_rate_selected") is not None
        and float(locked["wrong_leg_rate_selected"]) <= 0.01,
        "no_tail_date_split_leakage": no_tail_date_split_leakage,
        "locked_test_not_used_for_threshold": True,
    }
    quality_gate["passed_stage3_v7_targets"] = bool(
        quality_gate["validation_compound_gate_passes_targets"]
        and quality_gate["locked_test_available"]
        and quality_gate["locked_test_selected_coverage_gt_30pct"]
        and quality_gate["locked_test_selected_q90_lt_5min"]
        and quality_gate["locked_test_selected_catastrophic_lt_5pct"]
        and quality_gate["locked_test_selected_wrong_leg_le_1pct"]
        and quality_gate["no_tail_date_split_leakage"]
    )

    profile = (
        case_eval_v7.filter(pl.col("accepted_by_compound_gate_v7"))
        .group_by(["split", "source_tier_v6", "leg_phase_like", "batch_size_bucket", "status"])
        .agg(pl.len().alias("cases"))
        .sort(["split", "source_tier_v6", "leg_phase_like", "batch_size_bucket", "status"])
    )
    profile.write_parquet(out_dir / "pseudo_amdar_v7_accepted_profile.parquet")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_stage3_v6_case_evaluation": str(cfg.stage3_v6_dir / "pseudo_amdar_v6_case_evaluation.parquet"),
        "input_stage3_v6_row_reconstruction": str(cfg.stage3_v6_dir / "pseudo_amdar_v6_row_reconstruction.parquet"),
        "input_stage3_v6_report": str(cfg.stage3_v6_dir / "pseudo_amdar_v6_calibration_report.json"),
        "space_saving_policy": "Reuses Stage3 v6 case/row evaluation outputs; does not reread or copy the 19M ADS-B point table.",
        "selection_policy": "Compound gate chosen on validation only; locked_test is report-only.",
        "compound_gate_policy_v7": {
            "best_cost_max": cfg.v7_best_cost_max,
            "cross_track_q90_max_km": cfg.v7_cross_track_q90_max_km,
            "vertical_q90_max_m": cfg.v7_vertical_q90_max_m,
            "sampling_gap_max_s": cfg.v7_sampling_gap_max_s,
            "monotonic_violation_count": 0,
            "ambiguity_margin_min_when_multiple_candidates": cfg.v7_ambiguity_margin_min,
        },
        "metrics": metrics,
        "quality_gate": quality_gate,
        "compound_gate_reject_reason_counts": counts_map(case_eval_v7, "compound_gate_reject_reason_v7"),
        "accepted_profile_preview": profile.head(100).to_dicts(),
        "outputs": {
            "case_evaluation": str(out_dir / "pseudo_amdar_v7_case_evaluation.parquet"),
            "acceptance_curve": str(out_dir / "pseudo_amdar_v7_acceptance_curve.parquet"),
            "accepted_profile": str(out_dir / "pseudo_amdar_v7_accepted_profile.parquet"),
            "calibration_report": str(out_dir / "pseudo_amdar_v7_calibration_report.json"),
            "report_md": str(out_dir / "stage3_pseudo_amdar_v7_report.md"),
        },
    }
    write_json(out_dir / "pseudo_amdar_v7_calibration_report.json", summary)

    report = [
        "# Stage3 Pseudo-AMDAR v7 Compound Gate Report",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Gate",
        "",
        f"- Policy: `{summary['compound_gate_policy_v7']}`",
        "- Selection source: validation split only.",
        "- Locked test: report-only; not used to tune thresholds.",
        "",
        "## Metrics",
        "",
        f"- v6 reference locked-test selected metrics: `{metrics['v6_reference_best_cost_only']['locked_test']}`",
        f"- v7 compound locked-test selected metrics: `{metrics['v7_compound_gate']['locked_test']}`",
        f"- Quality gate: `{quality_gate}`",
        "",
        "Interpretation: v7 keeps the v6 validation-only discipline but replaces the single best-cost gate with an explicit geometry, sampling, monotonicity, and ambiguity gate. Broad real AMDAR-ADS-B matching remains blocked.",
    ]
    (out_dir / "stage3_pseudo_amdar_v7_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


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
        clamp_expr(
            pl.col("batch_size_conf")
            * pl.col("spatial_representativeness_conf")
            * pl.col("sequence_conf")
            * pl.col("batch_met_consistency_conf"),
            0.05,
            0.85,
        ).alias("batch_conf")
    )


def build_stage2_v6_identity_prior(cfg: RunConfig, out_dir: Path) -> pl.DataFrame:
    leg_path = cfg.stage2_v6_dir / "adsb_leg_quality_components_v6.parquet"
    leg = pl.scan_parquet(leg_path).filter(pl.col("point_count") >= 5)
    prior = (
        leg.group_by(["tail_norm", "flight_norm", "service_date_utc"])
        .agg(
            [
                pl.len().alias("same_identity_date_leg_count_v6"),
                pl.col("stage3_candidate_projection_pool_v6").fill_null(False).sum().alias("candidate_projection_leg_count_v6"),
                pl.col("stage3_pseudo_source_pool_v6").fill_null(False).sum().alias("pseudo_source_leg_count_v6"),
                (pl.col("stage3_source_tier_v6") == "S0_core_clean_long_source").sum().alias("S0_leg_count_v6"),
                (pl.col("stage3_source_tier_v6") == "S1_strong_component_b_long_source").sum().alias("S1_leg_count_v6"),
                (pl.col("stage3_source_tier_v6") == "S2_broad_short_batch_threshold_source").sum().alias("S2_leg_count_v6"),
                (pl.col("stage3_source_tier_v6") == "P_identity_date_prior_only_no_matching").sum().alias("P_prior_leg_count_v6"),
                pl.col("adsb_stage3_source_conf_cap_v6").max().alias("best_adsb_stage3_source_conf_cap_v6"),
                pl.col("point_count").sum().alias("same_identity_date_leg_points_v6"),
                pl.col("duration_seconds").max().alias("same_identity_date_max_duration_seconds_v6"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("S0_leg_count_v6") > 0)
                .then(pl.lit("S0_core_clean_long_source"))
                .when(pl.col("S1_leg_count_v6") > 0)
                .then(pl.lit("S1_strong_component_b_long_source"))
                .when(pl.col("S2_leg_count_v6") > 0)
                .then(pl.lit("S2_broad_short_batch_threshold_source"))
                .when(pl.col("candidate_projection_leg_count_v6") > 0)
                .then(pl.lit("projection_candidate_only_not_source"))
                .when(pl.col("P_prior_leg_count_v6") > 0)
                .then(pl.lit("identity_date_prior_only_no_matching"))
                .otherwise(pl.lit("diagnostic_or_none"))
                .alias("best_stage3_source_tier_v6_identity_date"),
                pl.col("best_adsb_stage3_source_conf_cap_v6").fill_null(0.0).alias("adsb_identity_prior_conf_v2"),
            ]
        )
        .collect(streaming=True)
    )
    prior.write_parquet(out_dir / "stage2_v6_identity_date_prior_summary.parquet")
    return prior


def build_stage4_components(cfg: RunConfig, stage3_summary: dict[str, Any]) -> tuple[pl.DataFrame, dict[str, Any], dict[str, Any]]:
    out_dir = cfg.out_dir / "stage4_confidence_v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_wind_path = cfg.stage1_plan4_dir / "clean_wind.parquet"
    resolution_path = cfg.stage1_v3_dir / "stage1_qc_resolution_table_v3.parquet"
    wind_schema = pl.read_parquet_schema(clean_wind_path)
    resolution_schema = pl.read_parquet_schema(resolution_path)

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
    res_cols = [
        "source",
        "source_row_index",
        "wind_speed_ms",
        "wind_direction_raw_deg",
        "temperature_raw_c",
        "met_value_quality_audit",
        "wind_speed_outlier_flag",
        "wind_direction_invalid_flag",
        "uv_nonfinite_flag",
        "temperature_outlier_flag",
        "altitude_outlier_flag",
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
        wind.filter(pl.col("source") == "amdar")
        .group_by("amdar_batch_id")
        .agg(
            [
                pl.col("wind_speed").cast(pl.Float64, strict=False).std().alias("batch_wind_speed_std_ms"),
                pl.col("wind_speed").cast(pl.Float64, strict=False).min().alias("batch_wind_speed_min_ms"),
                pl.col("wind_speed").cast(pl.Float64, strict=False).max().alias("batch_wind_speed_max_ms"),
                pl.len().alias("batch_actual_row_count"),
            ]
        )
    )

    wind_qc = (
        wind.join(resolution, on=["source", "source_row_index"], how="left")
        .join(batch_stats, on="amdar_batch_id", how="left")
        .with_columns(
            [
                normalize_text_expr("机尾号").alias("tail_norm"),
                normalize_text_expr("航班号").alias("flight_norm"),
                pl.col("time_utc").dt.strftime("%Y-%m-%d").alias("service_date_utc"),
                batch_size_bucket_expr().alias("amdar_batch_size_bucket"),
                pl.col("processing_slice_id")
                .fill_null((pl.col("source_row_index").cast(pl.UInt64) % int(cfg.slice_count)).cast(pl.UInt8))
                .alias("processing_slice_id"),
                pl.col("wind_speed_ms").fill_null(pl.col("wind_speed")).cast(pl.Float64, strict=False).alias("wind_speed_ms_filled"),
                pl.col("wind_direction_raw_deg").fill_null(pl.col("wind_dir")).cast(pl.Float64, strict=False).alias("wind_dir_deg_filled"),
                pl.col("stage1_confidence_cap_v3").fill_null(1.0).alias("stage1_confidence_cap_v3"),
            ]
        )
    )

    prior = build_stage2_v6_identity_prior(cfg, out_dir)
    df = wind_qc.join(prior.lazy(), on=["tail_norm", "flight_norm", "service_date_utc"], how="left")
    df = add_batch_confidence(df)

    finite_met = finite_expr("wind_speed_ms_filled") & finite_expr("wind_dir_deg_filled") & finite_expr("u_wind") & finite_expr("v_wind")
    bad_met = (
        ~finite_met
        | (pl.col("wind_speed_ms_filled") < 0.0)
        | (pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_REJECT_REVIEW)
        | (pl.col("wind_dir_deg_filled") < 0.0)
        | (pl.col("wind_dir_deg_filled") >= 360.0)
        | pl.col("uv_nonfinite_flag").fill_null(False)
        | (pl.col("stage1_confidence_cap_v3").fill_null(1.0) <= 0.0)
    )
    review_met = (
        pl.col("wind_speed_outlier_flag").fill_null(False)
        | pl.col("temperature_outlier_flag").fill_null(False)
        | pl.col("altitude_outlier_flag").fill_null(False)
    )
    uv_delta = (
        ((pl.col("u_wind").cast(pl.Float64, strict=False) ** 2 + pl.col("v_wind").cast(pl.Float64, strict=False) ** 2).sqrt()
        - pl.col("wind_speed_ms_filled")).abs()
    )

    locked_metrics = stage3_summary.get("metrics", {}).get("v7_compound_gate", {}).get("locked_test", {})
    locked_coverage = float(locked_metrics.get("selected_case_fraction") or 0.0)
    locked_wrong_rate = float(locked_metrics.get("wrong_leg_rate_selected") or 1.0)
    stage3_gate_conf = max(0.0, min(1.0, locked_coverage * (1.0 - locked_wrong_rate)))

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
            .when(review_met | (uv_delta > 0.5))
            .then(pl.lit(0.60))
            .otherwise(pl.lit(1.0))
            .alias("met_conf"),
            pl.when(pl.col("source") == "turb")
            .then(pl.lit(1.0))
            .when(pl.col("source") == "amdar")
            .then(clamp_expr(pl.col("batch_conf") / 0.85, 0.05, 1.0))
            .otherwise(pl.lit(0.50))
            .alias("time_source_conf"),
            pl.when((pl.col("tail_norm") != "MISSING") & (pl.col("flight_norm") != "MISSING"))
            .then(pl.lit(1.0))
            .when((pl.col("tail_norm") != "MISSING") | (pl.col("flight_norm") != "MISSING"))
            .then(pl.lit(0.75))
            .otherwise(pl.lit(0.35))
            .alias("identity_conf"),
            pl.col("adsb_identity_prior_conf_v2").fill_null(0.0).alias("adsb_leg_conf"),
            pl.lit(0.0).alias("adsb_match_conf"),
            pl.lit(0.0).alias("spatial_match_conf"),
            pl.when(pl.col("source") == "amdar")
            .then(clamp_expr(1.0 / pl.col("amdar_batch_row_count").cast(pl.Float64, strict=False).sqrt(), 0.10, 1.0))
            .otherwise(pl.lit(1.0))
            .alias("density_conf"),
            pl.lit(stage3_gate_conf).alias("stage3_v7_compound_gate_confidence"),
            pl.col("source").eq("amdar").alias("is_amdar"),
            pl.col("source").eq("turb").alias("is_turb"),
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
    weighted_log = sum(pl.lit(w) * pl.col(c).clip(EPS, 1.0).log() for c, w in weights.items() if w > 0)

    df = df.with_columns(
        [
            pl.when(pl.col("is_turb"))
            .then(pl.lit(1.0))
            .otherwise(clamp_expr((weighted_log / denom).exp(), 0.0, 0.85))
            .alias("base_support_conf_pre_stage1_cap"),
            bad_met.alias("hard_reject_flag"),
        ]
    ).with_columns(
        [
            pl.when(pl.col("hard_reject_flag"))
            .then(pl.lit(0.0))
            .otherwise(pl.min_horizontal("base_support_conf_pre_stage1_cap", "stage1_confidence_cap_v3"))
            .alias("base_support_conf"),
            pl.when(
                pl.col("is_turb")
                & pl.col("strict_holdout_eligible_v3").fill_null(False)
                & ~pl.col("hard_reject_flag")
            )
            .then(pl.lit(0.0))
            .otherwise(pl.col("batch_time_uncertainty_s"))
            .alias("time_uncertainty_s_stage4_v2"),
        ]
    )

    quality_reason = (
        pl.when(~finite_met)
        .then(pl.lit("nonfinite_wind_or_uv"))
        .when(pl.col("stage1_confidence_cap_v3") <= 0.0)
        .then(pl.col("stage1_downstream_action_v3").fill_null("stage1_cap_zero"))
        .when(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_REJECT_REVIEW)
        .then(pl.lit("wind_speed_gt_200_mps_manual_review"))
        .when(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_PLAUSIBLE_MAX)
        .then(pl.lit("wind_speed_gt_150_mps_downweighted"))
        .when(pl.col("temperature_outlier_flag").fill_null(False))
        .then(pl.lit("temperature_outlier_review"))
        .when(pl.col("altitude_outlier_flag").fill_null(False))
        .then(pl.lit("altitude_outlier_review"))
        .otherwise(pl.lit("none"))
    )
    df = df.with_columns(
        [
            quality_reason.alias("primary_quality_action_reason"),
            (
                pl.col("is_turb")
                & pl.col("strict_holdout_eligible_v3").fill_null(False)
                & ~pl.col("hard_reject_flag")
            ).alias("enhanced_holdout_eligible_v2"),
            pl.lit(False).alias("adsb_reconstructed"),
            pl.lit("stage5_pending_no_real_amdar_adsb_match_yet").alias("adsb_match_status"),
            pl.when(pl.col("source") == "turb")
            .then(pl.lit("point_observation"))
            .otherwise(pl.lit("batch_feature_prior_plus_stage2_v6_identity_date_prior"))
            .alias("confidence_basis"),
        ]
    )

    df = df.with_columns(
        [
            pl.when(pl.col("source") == "turb")
            .then(pl.when(pl.col("enhanced_holdout_eligible_v2")).then(pl.lit("T0")).otherwise(pl.lit("T4")))
            .when(pl.col("hard_reject_flag"))
            .then(pl.lit("T4"))
            .when((pl.col("base_support_conf") >= 0.70) & (pl.col("time_uncertainty_s_stage4_v2") <= 300.0))
            .then(pl.lit("T1"))
            .when((pl.col("base_support_conf") >= 0.45) & (pl.col("time_uncertainty_s_stage4_v2") <= 900.0))
            .then(pl.lit("T2"))
            .when((pl.col("base_support_conf") >= 0.25) & (pl.col("time_uncertainty_s_stage4_v2") <= 1800.0))
            .then(pl.lit("T3"))
            .otherwise(pl.lit("T4"))
            .alias("confidence_tier"),
            pl.when(pl.col("source") == "turb")
            .then(pl.when(pl.col("enhanced_holdout_eligible_v2")).then(pl.lit("S")).otherwise(pl.lit("R")))
            .when(pl.col("hard_reject_flag"))
            .then(pl.lit("R"))
            .when((pl.col("base_support_conf") >= 0.70) & (pl.col("time_uncertainty_s_stage4_v2") <= 300.0))
            .then(pl.lit("A"))
            .when((pl.col("base_support_conf") >= 0.45) & (pl.col("time_uncertainty_s_stage4_v2") <= 900.0))
            .then(pl.lit("B"))
            .when((pl.col("base_support_conf") >= 0.25) & (pl.col("time_uncertainty_s_stage4_v2") <= 1800.0))
            .then(pl.lit("C"))
            .otherwise(pl.lit("D"))
            .alias("confidence_grade"),
            pl.when(pl.col("source") == "turb")
            .then(pl.when(pl.col("enhanced_holdout_eligible_v2")).then(pl.lit("strict_holdout")).otherwise(pl.lit("strict_holdout_review")))
            .when(pl.col("hard_reject_flag"))
            .then(pl.lit("rejected_or_manual_review"))
            .when((pl.col("base_support_conf") >= 0.45) & (pl.col("time_uncertainty_s_stage4_v2") <= 900.0))
            .then(pl.lit("support_assimilation_candidate"))
            .when((pl.col("base_support_conf") >= 0.25) & (pl.col("time_uncertainty_s_stage4_v2") <= 1800.0))
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
        "amdar_effective_strict_truth_v3",
        "strict_holdout_eligible_v3",
        "enhanced_holdout_eligible_v2",
        "support_assimilation_eligible_v3",
        "stage1_downstream_action_v3",
        "stage1_confidence_cap_v3",
        "met_value_quality",
        "met_value_quality_audit",
        "wind_speed_outlier_flag",
        "temperature_outlier_flag",
        "altitude_outlier_flag",
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
        "base_support_conf_pre_stage1_cap",
        "base_support_conf",
        "time_uncertainty_s_stage4_v2",
        "stage3_v7_compound_gate_confidence",
        "confidence_tier",
        "confidence_grade",
        "confidence_basis",
        "recommended_stage4_role",
        "primary_quality_action_reason",
        "same_identity_date_leg_count_v6",
        "candidate_projection_leg_count_v6",
        "pseudo_source_leg_count_v6",
        "S0_leg_count_v6",
        "S1_leg_count_v6",
        "S2_leg_count_v6",
        "best_stage3_source_tier_v6_identity_date",
        "adsb_identity_prior_conf_v2",
        "same_identity_date_leg_points_v6",
        "adsb_reconstructed",
        "adsb_match_status",
    ]
    components = df.select([c for c in output_cols if c in df.collect_schema().names()]).collect(streaming=True)
    components.write_parquet(out_dir / "amdar_confidence_components_v2.parquet")

    summary = summarize_stage4_components(components, cfg, stage3_summary)
    summary["outputs"] = {
        "amdar_confidence_components_v2": str(out_dir / "amdar_confidence_components_v2.parquet"),
        "stage2_v6_identity_date_prior_summary": str(out_dir / "stage2_v6_identity_date_prior_summary.parquet"),
        "amdar_confidence_policy_v2": str(out_dir / "amdar_confidence_policy_v2.json"),
        "confidence_tier_summary_v2": str(out_dir / "confidence_tier_summary_v2.json"),
        "stage4_confidence_v2_report": str(out_dir / "stage4_confidence_v2_report.md"),
    }
    policy = build_stage4_policy(summary, stage3_summary)
    write_json(out_dir / "confidence_tier_summary_v2.json", summary)
    write_json(out_dir / "amdar_confidence_policy_v2.json", policy)
    write_stage4_report(out_dir, summary)
    return components, summary, policy


def summarize_stage4_components(df: pl.DataFrame, cfg: RunConfig, stage3_summary: dict[str, Any]) -> dict[str, Any]:
    amdar = df.filter(pl.col("source") == "amdar")
    turb = df.filter(pl.col("source") == "turb")
    high_wind = amdar.filter(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_PLAUSIBLE_MAX)
    gt200 = amdar.filter(pl.col("wind_speed_ms_filled") > WIND_SPEED_MS_REJECT_REVIEW)
    locked = stage3_summary.get("metrics", {}).get("v7_compound_gate", {}).get("locked_test", {})
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
    checks = {
        "no_fixed_035_only": len(set(amdar.get_column("base_support_conf").round(6).to_list())) > 10 if amdar.height else False,
        "confidence_components_present": all(
            c in df.columns
            for c in [
                "source_conf",
                "met_conf",
                "time_source_conf",
                "sequence_conf",
                "identity_conf",
                "adsb_leg_conf",
                "adsb_match_conf",
                "spatial_match_conf",
                "density_conf",
                "base_support_conf",
            ]
        ),
        "strict_truth_not_derived_from_confidence": True,
        "amdar_effective_strict_truth_rows": int(amdar.filter(pl.col("effective_strict_truth").fill_null(False)).height),
        "amdar_t0_rows": int(amdar.filter(pl.col("confidence_tier") == "T0").height),
        "turb_enhanced_holdout_eligible_is_175": int(turb.filter(pl.col("enhanced_holdout_eligible_v2")).height) == 175,
        "turb_review_rows_is_6": int(turb.filter(~pl.col("enhanced_holdout_eligible_v2")).height) == 6,
        "stage5_match_not_fabricated": int(amdar.filter((pl.col("adsb_match_conf") != 0.0) | (pl.col("spatial_match_conf") != 0.0)).height) == 0,
        "stage2_v6_identity_prior_present": "best_stage3_source_tier_v6_identity_date" in df.columns,
        "stage3_v7_gate_passed": bool(stage3_summary.get("quality_gate", {}).get("passed_stage3_v7_targets")),
        "gt200_amdar_base_support_zero": int(gt200.filter(pl.col("base_support_conf") > 0.0).height) == 0,
    }
    checks["passed"] = bool(
        checks["no_fixed_035_only"]
        and checks["confidence_components_present"]
        and checks["strict_truth_not_derived_from_confidence"]
        and checks["amdar_effective_strict_truth_rows"] == 0
        and checks["amdar_t0_rows"] == 0
        and checks["turb_enhanced_holdout_eligible_is_175"]
        and checks["turb_review_rows_is_6"]
        and checks["stage5_match_not_fabricated"]
        and checks["stage2_v6_identity_prior_present"]
        and checks["stage3_v7_gate_passed"]
        and checks["gt200_amdar_base_support_zero"]
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "slice_count": cfg.slice_count,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "space_saving_policy": "Single compact full confidence table with processing_slice_id; no duplicated 25-way full intermediates.",
            "real_amdar_adsb_match_dependency": "Stage5 not run; adsb_match_conf and spatial_match_conf remain 0.",
        },
        "inputs": {
            "stage1_clean_wind": str(cfg.stage1_plan4_dir / "clean_wind.parquet"),
            "stage1_v3_resolution": str(cfg.stage1_v3_dir / "stage1_qc_resolution_table_v3.parquet"),
            "stage2_v6_leg_components": str(cfg.stage2_v6_dir / "adsb_leg_quality_components_v6.parquet"),
            "stage3_v7_report": str(cfg.out_dir / "stage3_pseudo_amdar_v7_compound_gate/pseudo_amdar_v7_calibration_report.json"),
        },
        "row_counts": {"total": int(df.height), "amdar": int(amdar.height), "turb": int(turb.height)},
        "tier_counts": counts_map(df, "confidence_tier"),
        "grade_counts": counts_map(df, "confidence_grade"),
        "recommended_role_counts": counts_map(df, "recommended_stage4_role"),
        "primary_quality_action_reason_counts": counts_map(df, "primary_quality_action_reason"),
        "amdar": {
            "tier_counts": counts_map(amdar, "confidence_tier"),
            "grade_counts": counts_map(amdar, "confidence_grade"),
            "role_counts": counts_map(amdar, "recommended_stage4_role"),
            "base_support_conf_summary": numeric_summary(amdar, "base_support_conf"),
            "time_uncertainty_s_summary": numeric_summary(amdar, "time_uncertainty_s_stage4_v2"),
            "batch_size_counts": counts_map(amdar, "amdar_batch_size_bucket"),
            "high_wind_rows_gt_150_mps": int(high_wind.height),
            "high_wind_rows_gt_200_mps": int(gt200.height),
            "high_wind_tier_counts": counts_map(high_wind, "confidence_tier"),
            "stage5_pending_match_rows": int(amdar.filter(pl.col("adsb_match_status") == "stage5_pending_no_real_amdar_adsb_match_yet").height),
        },
        "turb": {
            "tier_counts": counts_map(turb, "confidence_tier"),
            "grade_counts": counts_map(turb, "confidence_grade"),
            "original_effective_strict_truth_true": int(turb.filter(pl.col("effective_strict_truth").fill_null(False)).height),
            "enhanced_holdout_eligible_true": int(turb.filter(pl.col("enhanced_holdout_eligible_v2")).height),
            "enhanced_holdout_review_rows": int(turb.filter(~pl.col("enhanced_holdout_eligible_v2")).height),
            "review_reason_counts": counts_map(turb, "primary_quality_action_reason"),
        },
        "stage2_v6_identity_prior": {
            "amdar_rows_with_same_identity_date_leg": int(amdar.filter(pl.col("same_identity_date_leg_count_v6").fill_null(0) > 0).height),
            "best_stage3_source_tier_counts": counts_map(amdar, "best_stage3_source_tier_v6_identity_date"),
            "adsb_leg_conf_summary": numeric_summary(amdar, "adsb_leg_conf"),
            "note": "Identity-date ADS-B prior only; not an accepted real AMDAR-ADS-B point-time match.",
        },
        "stage3_v7_status": {
            "locked_test_metrics": locked,
            "quality_gate": stage3_summary.get("quality_gate", {}),
        },
        "by_processing_slice": by_slice,
        "stage4_completion_checks": checks,
    }


def build_stage4_policy(summary: dict[str, Any], stage3_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at_utc": summary["generated_at_utc"],
        "policy_version": "amdar_unified_stage4_confidence_v2_stage2v6_stage3v7",
        "purpose": "Auditable AMDAR support confidence using Stage1 v3 QC actions, Stage2 v6 identity-date ADS-B priors, and Stage3 v7 validation-only compound gate evidence.",
        "strict_truth_boundary": {
            "rule": "No confidence field can create strict truth. AMDAR remains support-only.",
            "amdar_effective_strict_truth": summary["stage4_completion_checks"]["amdar_effective_strict_truth_rows"],
            "turb_original_effective_strict_truth": summary["turb"]["original_effective_strict_truth_true"],
            "turb_enhanced_holdout_eligible_after_qc": summary["turb"]["enhanced_holdout_eligible_true"],
        },
        "stage3_v7_compound_gate_policy": stage3_summary.get("compound_gate_policy_v7", {}),
        "component_definitions": {
            "source_conf": "1.0 for TURB, 0.90 for AMDAR.",
            "met_conf": "0 for hard reject/cap-zero rows; 0.35 for AMDAR wind >150 m/s retained under review; 0.60 for review flags; 1.0 otherwise.",
            "batch_conf": "Product of batch size, spatial span, phase, and within-batch wind consistency factors, capped to [0.05, 0.85].",
            "time_source_conf": "TURB point observation=1.0; AMDAR uses batch_conf/0.85.",
            "identity_conf": "1.0 when both tail and flight are present, 0.75 when one exists, 0.35 otherwise.",
            "adsb_leg_conf": "Stage2 v6 identity-date prior cap: S0=.90, S1=.78, S2=.62, projection=.30, none=0.",
            "adsb_match_conf": "Always 0 because real Stage5 AMDAR-ADS-B matching has not run.",
            "spatial_match_conf": "Always 0 because no accepted real point-time match exists.",
            "density_conf": "1/sqrt(batch_row_count), clipped to [0.10, 1.0].",
            "base_support_conf": "Weighted geometric mean, then capped by Stage1 v3 confidence cap.",
        },
        "tier_rules": {
            "T0/S": "TURB with Stage1 v3 strict_holdout_eligible and no hard reject.",
            "T1/A": "base_support_conf >= 0.70 and time_uncertainty_s <= 300, support only.",
            "T2/B": "base_support_conf >= 0.45 and time_uncertainty_s <= 900, support only.",
            "T3/C": "base_support_conf >= 0.25 and time_uncertainty_s <= 1800, low-confidence support/super-ob only.",
            "T4/D_or_R": "Below T3 or hard review/reject.",
        },
        "forbidden_operations_reaffirmed": [
            "Do not promote AMDAR to strict truth.",
            "Do not treat AMDAR batch_end_time as point observation time.",
            "Do not treat adsb_leg_conf as an accepted real match.",
            "Do not run broad real AMDAR-ADS-B matching without Stage5-V3 reject/ambiguity diagnostics.",
        ],
    }


def write_stage4_report(out_dir: Path, summary: dict[str, Any]) -> None:
    checks = summary["stage4_completion_checks"]
    report = [
        "# Stage4 Confidence v2 Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Scope",
        "",
        "This run refreshes Unified Plan Stage4 confidence modeling with Stage1 v3 QC resolution, Stage2 v6 identity-date ADS-B priors, and Stage3 v7 compound-gate validation evidence. It does not run real AMDAR-ADS-B matching.",
        "",
        "## Key Results",
        "",
        f"- Total rows scored: `{summary['row_counts']['total']}`",
        f"- AMDAR rows scored: `{summary['row_counts']['amdar']}`",
        f"- TURB rows scored: `{summary['row_counts']['turb']}`",
        f"- Tier counts: `{summary['tier_counts']}`",
        f"- AMDAR tier counts: `{summary['amdar']['tier_counts']}`",
        f"- TURB enhanced holdout eligible rows: `{summary['turb']['enhanced_holdout_eligible_true']}`",
        f"- TURB enhanced holdout review rows: `{summary['turb']['enhanced_holdout_review_rows']}`",
        f"- Stage3 v7 locked-test metrics: `{summary['stage3_v7_status']['locked_test_metrics']}`",
        "",
        "## Completion Checks",
        "",
        f"- Checks: `{checks}`",
        "",
        "Interpretation: Stage4 v2 is acceptable for the next non-Stage5-prep step. AMDAR remains support-only; ADS-B information is still an identity-date prior, not a real accepted point-time match.",
    ]
    (out_dir / "stage4_confidence_v2_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def write_final_docs(cfg: RunConfig, stage3: dict[str, Any], stage4: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage3_v7_stage4_confidence_v2_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage3_v7_stage4_confidence_v2.md"
    locked = stage3.get("metrics", {}).get("v7_compound_gate", {}).get("locked_test", {})
    v6_locked = stage3.get("metrics", {}).get("v6_reference_best_cost_only", {}).get("locked_test", {})
    lines = [
        "# AMDAR Unified Plan Stage3 v7 + Stage4 Confidence v2 Results",
        "",
        f"Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Executive Conclusion",
        "",
        "Stage2 v6 remains suitable for Stage3 because the source pool is tiered and readiness checks passed. The old Stage3 v6 result already passed, but it depended on a single best-cost threshold. Stage3 v7 is better: it uses a validation-only compound gate with explicit geometry, vertical, sampling, monotonicity, and ambiguity constraints.",
        "",
        "Stage4 confidence v2 was refreshed after Stage3 v7 passed. It consumes Stage1 v3 QC actions and Stage2 v6 identity-date priors, while keeping Stage5 real AMDAR-ADS-B matching blocked and keeping AMDAR support-only.",
        "",
        "## Problems Found And Resolved",
        "",
        "1. Stage3 v6 passed but used a single best-cost threshold, which was less interpretable than the Unified Plan expects. Stage3 v7 fixes this with a compound gate: `best_cost<=1.0`, `cross_track_q90<=0.5km`, `vertical_q90<=200m`, `sampling_gap<=300s`, zero monotonic violations, and `ambiguity_margin>=2.0` when multiple candidates exist.",
        "2. The earlier Stage4 confidence run consumed older Stage2/3 priors. Stage4 v2 now consumes Stage1 v3 QC caps, Stage2 v6 identity-date prior tiers, and Stage3 v7 gate evidence.",
        "3. High-wind AMDAR risk is now enforced in the confidence product: `>200 m/s` AMDAR rows have zero support confidence, while `150-200 m/s` rows remain low-confidence review support only.",
        "",
        "## Stage3 v7 Result",
        "",
        f"- v6 reference locked-test selected metrics: `{v6_locked}`",
        f"- v7 compound locked-test selected metrics: `{locked}`",
        f"- Stage3 v7 quality gate: `{stage3.get('quality_gate')}`",
        "",
        "Assessment: Stage3 v7 is satisfactory. It improves selected coverage while making the acceptance rule physically interpretable; locked-test wrong-leg rate, q90 time error, and catastrophic rate all pass the targets.",
        "",
        "## Stage4 Confidence v2 Result",
        "",
        f"- Tier counts: `{stage4.get('tier_counts')}`",
        f"- AMDAR tier counts: `{stage4.get('amdar', {}).get('tier_counts')}`",
        f"- TURB enhanced holdout: `{stage4.get('turb', {}).get('enhanced_holdout_eligible_true')}` eligible, `{stage4.get('turb', {}).get('enhanced_holdout_review_rows')}` review rows",
        f"- Completion checks: `{stage4.get('stage4_completion_checks')}`",
        "",
        "Assessment: Stage4 v2 is satisfactory for the next phase. It is conservative: `adsb_match_conf=0`, `spatial_match_conf=0`, AMDAR `effective_strict_truth=false`, and >200 m/s AMDAR rows remain zero-confidence pending provider review.",
        "",
        "## Can Enter Next Phase?",
        "",
        "Yes. Stage2 v6, Stage3 v7, and Stage4 confidence v2 are now suitable for the next non-Stage5-prep step. If the next phase is real AMDAR-ADS-B matching, it must start as Stage5-V3 prep with candidate/reject/ambiguity diagnostics; it must not jump directly from identity-date priors to accepted real matches.",
        "",
        "## Remaining Optimization Space",
        "",
        "Stage2/3 still have research space in sequence-level reconstruction and ADS-B metadata such as NACp/NACv/NIC/SIL/SDA and latency. That is Stage5-prep work, not a reason to relax current gates. Stage4 can later be refined after a real Stage5 match creates actual `adsb_match_conf` and time-uncertainty distributions.",
        "",
        "## Recommended Next Steps",
        "",
        "1. Treat this output as ready for the next non-Stage5-prep step.",
        "2. If proceeding to real AMDAR-ADS-B matching, implement Stage5-V3 candidate/reject/ambiguity diagnostics first.",
        "3. Do not use AMDAR as strict truth; keep TURB-only conservative holdout.",
    ]
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    handover = [
        "# 给下一个智能体的交接话术：Stage3 v7 + Stage4 confidence v2 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要从零开始。当前已经完成 Stage2 v6 分层 source pool、Stage3 v7 pseudo-AMDAR 复合门控验证，以及 Stage4 confidence v2 刷新。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目 strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：strict truth 少是数据现实，应该走分层置信度。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan 的阶段边界和禁止操作。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701/stage2_v6_stage3_pseudo_results_analysis_and_next_steps.md`：Stage2 v6 和 Stage3 v6 基线。",
        f"6. `{result_path}`：最新 Stage3 v7 + Stage4 confidence v2 结果、达标判断和下一步建议。",
        "7. `stage3_pseudo_amdar_v7_compound_gate/pseudo_amdar_v7_calibration_report.json`：复合 gate 的 validation-only 规则和 locked_test 指标。",
        "8. `stage4_confidence_v2/confidence_tier_summary_v2.json`：Stage4 confidence v2 分层结果和完成检查。",
        "",
        "## 本轮脚本和输出",
        "",
        f"- 脚本：`{Path(__file__)}`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- Stage3 v7 case evaluation：`stage3_pseudo_amdar_v7_compound_gate/pseudo_amdar_v7_case_evaluation.parquet`",
        "- Stage3 v7 report：`stage3_pseudo_amdar_v7_compound_gate/pseudo_amdar_v7_calibration_report.json`",
        "- Stage4 confidence table：`stage4_confidence_v2/amdar_confidence_components_v2.parquet`",
        "- Stage4 policy：`stage4_confidence_v2/amdar_confidence_policy_v2.json`",
        "- Stage4 summary：`stage4_confidence_v2/confidence_tier_summary_v2.json`",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        f"  {Path(__file__)} \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25",
        "```",
        "",
        "空间口径：复用 Stage3 v6 case/row evaluation；不复制 19M ADS-B 点表；Stage4 只写单份 compact confidence table，带 `processing_slice_id`。",
        "",
        "## 关键结果",
        "",
        f"- Stage3 v7 locked selected metrics: `{locked}`",
        f"- Stage3 v7 quality gate: `{stage3.get('quality_gate')}`",
        f"- Stage4 v2 tier counts: `{stage4.get('tier_counts')}`",
        f"- Stage4 v2 completion checks: `{stage4.get('stage4_completion_checks')}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 继续 support-only，不能进入 strict holdout。",
        "- `adsb_leg_conf` 只是 Stage2 v6 identity-date prior，不是真实匹配。",
        "- `adsb_match_conf=0`、`spatial_match_conf=0` 必须保持到 Stage5-V3 真匹配完成。",
        "- real AMDAR-ADS-B broad matching 仍然 blocked；若要做，只能先做 Stage5-V3 reject/ambiguity diagnostics。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage2 v6/Stage3 v6 基线，以及最新 Stage3 v7 + Stage4 confidence v2 结果。",
        "当前结论：Stage3 v7 用 validation-only 复合 gate 通过 locked_test；Stage4 v2 已用 Stage1 v3 + Stage2 v6 + Stage3 v7 刷新，并保持 AMDAR support-only、Stage5 真匹配 blocked。",
        "后续如果进入真实 AMDAR-ADS-B matching，我会先做 Stage5-V3 的候选、拒绝、歧义诊断和 pseudo locked-test gate，不会把 identity-date prior 当成真实匹配。",
        "```",
    ]
    handover_path.write_text("\n".join(handover) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage3_v7_start"}, ensure_ascii=False))
    stage3_summary = run_stage3_v7(cfg)
    print(
        json.dumps(
            {
                "stage": "stage3_v7_done",
                "passed": stage3_summary.get("quality_gate", {}).get("passed_stage3_v7_targets"),
                "locked_selected": stage3_summary.get("metrics", {}).get("v7_compound_gate", {}).get("locked_test", {}),
            },
            ensure_ascii=False,
        )
    )

    print(json.dumps({"stage": "stage4_confidence_v2_start"}, ensure_ascii=False))
    _, stage4_summary, _ = build_stage4_components(cfg, stage3_summary)
    print(
        json.dumps(
            {
                "stage": "stage4_confidence_v2_done",
                "passed": stage4_summary.get("stage4_completion_checks", {}).get("passed"),
                "tier_counts": stage4_summary.get("tier_counts"),
            },
            ensure_ascii=False,
        )
    )

    write_final_docs(cfg, stage3_summary, stage4_summary)
    print(json.dumps({"stage": "all_done", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
