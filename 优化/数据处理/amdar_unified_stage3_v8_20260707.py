from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pickle
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE2_V7_DIR = DATA_DIR / "stage2_adsb_qc_v7_optimized_20260706"
STAGE2_V4_DIR = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4"
STAGE3_V6_SCRIPT = DATA_DIR / "amdar_unified_stage2_v6_stage3_pseudo_20260701.py"
DEFAULT_OUT_DIR = DATA_DIR / "stage3_pseudo_amdar_v8_optimized_20260707"

V7_TO_COMPAT_TIER = {
    "S0_core_clean_medium_long_source": "S0_core_clean_long_source",
    "S1_balanced_medium_source": "S1_strong_component_b_long_source",
    "S2_short_batch_threshold_source": "S2_broad_short_batch_threshold_source",
}
COMPAT_TO_V8_TIER = {v: k for k, v in V7_TO_COMPAT_TIER.items()}


def load_v6_module() -> Any:
    spec = importlib.util.spec_from_file_location("stage3_v6_impl_for_v8", STAGE3_V6_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Stage3 v6 implementation from {STAGE3_V6_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V6 = load_v6_module()


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage2_v7_dir: Path = STAGE2_V7_DIR
    stage2_v4_dir: Path = STAGE2_V4_DIR
    slice_count: int = 25
    pseudo_case_limit: int = 50_000
    workers: int = 25
    candidate_topk: int = 10
    source_cap_core_per_split_phase: int = 700
    source_cap_strong_b_per_split_phase: int = 700
    source_cap_short_per_split_phase: int = 900
    candidate_time_padding_seconds: int = 7200
    candidate_end_tolerance_seconds: int = 600
    spatial_padding_deg: float = 1.25
    altitude_padding_m: float = 2500.0
    catastrophic_error_seconds: float = 1800.0
    target_time_error_q90_s: float = 330.0
    strong_time_error_q90_s: float = 300.0


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run optimization-plan phase 2: large-framework Stage3 pseudo-AMDAR v8. "
            "Consumes Stage2 v7 ADS-B QC/source tiers, generates 50k pseudo cases, calibrates "
            "acceptance on validation only, and reports locked_test metrics."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--pseudo-case-limit", type=int, default=50_000)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--candidate-topk", type=int, default=10)
    parser.add_argument("--source-cap-s0", type=int, default=700)
    parser.add_argument("--source-cap-s1", type=int, default=700)
    parser.add_argument("--source-cap-s2", type=int, default=900)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=int(args.slice_count),
        pseudo_case_limit=int(args.pseudo_case_limit),
        workers=int(args.workers),
        candidate_topk=int(args.candidate_topk),
        source_cap_core_per_split_phase=int(args.source_cap_s0),
        source_cap_strong_b_per_split_phase=int(args.source_cap_s1),
        source_cap_short_per_split_phase=int(args.source_cap_s2),
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


def bool_count(df: pl.DataFrame, expr: pl.Expr) -> int:
    if df.height == 0:
        return 0
    return int(df.select(expr.fill_null(False).sum()).item())


def compat_to_v8_expr(col: str = "source_tier_v6") -> pl.Expr:
    return (
        pl.when(pl.col(col) == "S0_core_clean_long_source")
        .then(pl.lit("S0_core_clean_medium_long_source"))
        .when(pl.col(col) == "S1_strong_component_b_long_source")
        .then(pl.lit("S1_balanced_medium_source"))
        .when(pl.col(col) == "S2_broad_short_batch_threshold_source")
        .then(pl.lit("S2_short_batch_threshold_source"))
        .otherwise(pl.col(col).cast(pl.Utf8, strict=False))
    )


def prepare_v7_components(cfg: RunConfig) -> tuple[pl.DataFrame, dict[str, Any]]:
    components_path = cfg.stage2_v7_dir / "adsb_leg_quality_components_v7.parquet"
    summary_path = cfg.stage2_v7_dir / "adsb_leg_readiness_summary_v7.json"
    summary = read_json(summary_path)
    if not summary.get("readiness_checks", {}).get("passed_stage2_v7_quality_gate"):
        raise RuntimeError(f"Stage2 v7 quality gate did not pass: {summary_path}")

    tier_compat = (
        pl.when(pl.col("stage3_source_tier_v7") == "S0_core_clean_medium_long_source")
        .then(pl.lit("S0_core_clean_long_source"))
        .when(pl.col("stage3_source_tier_v7") == "S1_balanced_medium_source")
        .then(pl.lit("S1_strong_component_b_long_source"))
        .when(pl.col("stage3_source_tier_v7") == "S2_short_batch_threshold_source")
        .then(pl.lit("S2_broad_short_batch_threshold_source"))
        .otherwise(pl.col("stage3_source_tier_v7"))
    )
    v7 = (
        pl.scan_parquet(components_path)
        .with_columns(
            [
                tier_compat.alias("stage3_source_tier_v6"),
                pl.col("stage3_source_tier_v7").alias("stage3_source_tier_v8"),
                pl.col("stage3_consumer_gate_v7").alias("stage3_consumer_gate_v8"),
                pl.col("stage3_pseudo_source_pool_v7").alias("stage3_pseudo_source_pool_v6"),
                pl.col("stage3_candidate_projection_pool_v7").alias("stage3_candidate_projection_pool_v6"),
                pl.lit(False).alias("real_amdar_adsb_match_allowed_without_stage3_v6"),
                pl.lit(False).alias("real_amdar_adsb_match_allowed_without_stage3_v8"),
                pl.col("leg_overall_quality_v7").alias("leg_overall_quality"),
                pl.col("adsb_stage3_source_conf_cap_v7").alias("adsb_stage3_source_conf_cap_v6"),
            ]
        )
        .with_columns(
            [
                pl.when(
                    pl.col("stage3_source_tier_v6").is_in(
                        ["S0_core_clean_long_source", "S1_strong_component_b_long_source"]
                    )
                )
                .then(pl.when(pl.col("point_count") >= 40).then(38).otherwise(18))
                .when(pl.col("stage3_source_tier_v6") == "S2_broad_short_batch_threshold_source")
                .then(7)
                .otherwise(0)
                .cast(pl.Int32)
                .alias("stage3_max_pseudo_batch_size_v6")
            ]
        )
        .collect(streaming=True)
    )
    return v7, summary


def compound_gate_expr(policy: dict[str, float]) -> pl.Expr:
    return (
        pl.col("status").is_in(["matched", "wrong_leg"])
        & pl.col("best_cost").is_not_null()
        & (pl.col("best_cost") <= float(policy["best_cost_max"]))
        & (pl.col("case_cross_track_q90_km").fill_null(math.inf) <= float(policy["cross_track_q90_max_km"]))
        & (pl.col("case_vertical_q90_m").fill_null(math.inf) <= float(policy["vertical_q90_max_m"]))
        & (pl.col("case_sampling_gap_max_seconds").fill_null(math.inf) <= float(policy["sampling_gap_max_s"]))
        & (pl.col("monotonic_violation_count").fill_null(999999) == 0)
        & (
            (pl.col("candidate_leg_count").fill_null(999999) <= 1)
            | (pl.col("ambiguity_margin").fill_null(0.0) >= float(policy["ambiguity_margin_min"]))
        )
    )


def reject_reason_expr(policy: dict[str, float]) -> pl.Expr:
    return (
        pl.when(~pl.col("status").is_in(["matched", "wrong_leg"]) | pl.col("best_cost").is_null())
        .then(pl.lit("no_candidate_or_projection"))
        .when(pl.col("best_cost") > float(policy["best_cost_max"]))
        .then(pl.lit("best_cost_gt_policy"))
        .when(pl.col("case_cross_track_q90_km").fill_null(math.inf) > float(policy["cross_track_q90_max_km"]))
        .then(pl.lit("cross_track_q90_gt_policy"))
        .when(pl.col("case_vertical_q90_m").fill_null(math.inf) > float(policy["vertical_q90_max_m"]))
        .then(pl.lit("vertical_q90_gt_policy"))
        .when(pl.col("case_sampling_gap_max_seconds").fill_null(math.inf) > float(policy["sampling_gap_max_s"]))
        .then(pl.lit("sampling_gap_gt_policy"))
        .when(pl.col("monotonic_violation_count").fill_null(999999) != 0)
        .then(pl.lit("monotonic_violation"))
        .when(
            (pl.col("candidate_leg_count").fill_null(999999) > 1)
            & (pl.col("ambiguity_margin").fill_null(0.0) < float(policy["ambiguity_margin_min"]))
        )
        .then(pl.lit("ambiguity_margin_lt_policy"))
        .otherwise(pl.lit("accepted"))
    )


def selected_metrics_by_gate(case_df: pl.DataFrame, row_df: pl.DataFrame, split: str | None, gate_col: str) -> dict[str, Any]:
    c = case_df if split is None else case_df.filter(pl.col("split") == split)
    r = row_df if split is None else row_df.filter(pl.col("split") == split)
    eligible = c.filter(pl.col(gate_col).fill_null(False))
    selected_ids = eligible.select("pseudo_case_id")
    rr = r.join(selected_ids, on="pseudo_case_id", how="inner") if r.height and eligible.height else pl.DataFrame()
    q90_s = float(rr["time_error_seconds"].quantile(0.90)) if rr.height else None
    q50_s = float(rr["time_error_seconds"].quantile(0.50)) if rr.height else None
    q99_s = float(rr["time_error_seconds"].quantile(0.99)) if rr.height else None
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
        "time_error_q50_s": q50_s,
        "time_error_q90_s": q90_s,
        "time_error_q99_s": q99_s,
        "time_error_q50_min": q50_s / 60.0 if q50_s is not None else None,
        "time_error_q90_min": q90_s / 60.0 if q90_s is not None else None,
        "time_error_q99_min": q99_s / 60.0 if q99_s is not None else None,
        "catastrophic_error_rate": float(rr.filter(pl.col("time_error_seconds") > 1800.0).height / max(1, rr.height))
        if rr.height
        else None,
        "status_counts_selected": counts_map(eligible, "status"),
    }


def candidate_policies() -> list[dict[str, Any]]:
    return [
        {
            "name": "strict_geometry_cost_0p5",
            "best_cost_max": 0.5,
            "cross_track_q90_max_km": 0.30,
            "vertical_q90_max_m": 150.0,
            "sampling_gap_max_s": 180.0,
            "ambiguity_margin_min": 3.0,
        },
        {
            "name": "v7_compound_carryover",
            "best_cost_max": 1.0,
            "cross_track_q90_max_km": 0.50,
            "vertical_q90_max_m": 200.0,
            "sampling_gap_max_s": 300.0,
            "ambiguity_margin_min": 2.0,
        },
        {
            "name": "balanced_cost_1p5",
            "best_cost_max": 1.5,
            "cross_track_q90_max_km": 0.75,
            "vertical_q90_max_m": 300.0,
            "sampling_gap_max_s": 450.0,
            "ambiguity_margin_min": 1.8,
        },
        {
            "name": "coverage_cost_2",
            "best_cost_max": 2.0,
            "cross_track_q90_max_km": 1.00,
            "vertical_q90_max_m": 500.0,
            "sampling_gap_max_s": 600.0,
            "ambiguity_margin_min": 1.5,
        },
        {
            "name": "wide_diagnostic_cost_3",
            "best_cost_max": 3.0,
            "cross_track_q90_max_km": 1.50,
            "vertical_q90_max_m": 800.0,
            "sampling_gap_max_s": 900.0,
            "ambiguity_margin_min": 1.2,
        },
    ]


def calibrate_compound_policy(case_eval: pl.DataFrame, row_eval: pl.DataFrame, cfg: RunConfig) -> dict[str, Any]:
    curve: list[dict[str, Any]] = []
    for policy in candidate_policies():
        gate_col = f"__gate_{policy['name']}"
        tmp = case_eval.with_columns(compound_gate_expr(policy).alias(gate_col))
        metrics = selected_metrics_by_gate(tmp, row_eval, "validation", gate_col)
        curve.append({"policy": policy, "validation_metrics": metrics})

    def passes(item: dict[str, Any]) -> bool:
        m = item["validation_metrics"]
        return bool(
            m.get("selected_case_fraction", 0.0) >= 0.30
            and m.get("time_error_q90_s") is not None
            and float(m["time_error_q90_s"]) <= cfg.target_time_error_q90_s
            and m.get("catastrophic_error_rate") is not None
            and float(m["catastrophic_error_rate"]) < 0.05
            and m.get("wrong_leg_rate_selected") is not None
            and float(m["wrong_leg_rate_selected"]) <= 0.01
        )

    passing = [item for item in curve if passes(item)]
    if passing:
        chosen = max(
            passing,
            key=lambda item: (
                float(item["validation_metrics"]["selected_case_fraction"]),
                -float(item["validation_metrics"]["time_error_q90_s"] or 999999.0),
            ),
        )
        return {
            "policy_found": True,
            "selection_basis": (
                "validation_only_largest_coverage_with_q90_le_330s_cat_lt_5pct_wrong_leg_le_1pct"
            ),
            "chosen_policy": chosen["policy"],
            "chosen_validation_metrics": chosen["validation_metrics"],
            "curve": curve,
        }

    best = min(
        curve,
        key=lambda item: (
            999999.0
            if item["validation_metrics"].get("time_error_q90_s") is None
            else float(item["validation_metrics"]["time_error_q90_s"]),
            -float(item["validation_metrics"].get("selected_case_fraction", 0.0)),
        ),
    )
    return {
        "policy_found": False,
        "selection_basis": "no_validation_policy_met_all_targets; best_q90_policy_reported",
        "chosen_policy": best["policy"],
        "chosen_validation_metrics": best["validation_metrics"],
        "curve": curve,
    }


def multiscale_report(case_eval: pl.DataFrame, row_eval: pl.DataFrame, gate_col: str) -> dict[str, Any]:
    scales = {
        "fine_5min": {"window_s": 300, "target_q90_s": 180},
        "medium_15min": {"window_s": 900, "target_q90_s": 600},
        "coarse_30min": {"window_s": 1800, "target_q90_s": 1200},
    }
    out: dict[str, Any] = {}
    for split in ["overall", "calibration", "validation", "locked_test"]:
        c = case_eval if split == "overall" else case_eval.filter(pl.col("split") == split)
        r = row_eval if split == "overall" else row_eval.filter(pl.col("split") == split)
        selected = c.filter(pl.col(gate_col).fill_null(False))
        selected_ids = selected.select("pseudo_case_id")
        selected_rows = r.join(selected_ids, on="pseudo_case_id", how="inner") if r.height and selected.height else pl.DataFrame()
        split_obj: dict[str, Any] = {
            "case_count": int(c.height),
            "selected_case_count": int(selected.height),
            "selected_case_fraction": float(selected.height / max(1, c.height)),
            "selected_row_time_error_q90_s": float(selected_rows["time_error_seconds"].quantile(0.90))
            if selected_rows.height
            else None,
        }
        for name, spec in scales.items():
            good = selected.filter(pl.col("case_time_error_q90_seconds").fill_null(math.inf) <= spec["target_q90_s"])
            good_rows = r.join(good.select("pseudo_case_id"), on="pseudo_case_id", how="inner") if r.height and good.height else pl.DataFrame()
            split_obj[name] = {
                **spec,
                "case_count": int(good.height),
                "coverage_of_all_cases": float(good.height / max(1, c.height)),
                "coverage_of_selected_cases": float(good.height / max(1, selected.height)),
                "row_time_error_q90_s": float(good_rows["time_error_seconds"].quantile(0.90))
                if good_rows.height
                else None,
            }
        out[split] = split_obj
    return out


def build_confidence_predictor(case_eval: pl.DataFrame, out_dir: Path) -> dict[str, Any]:
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - environment fallback
        report = {"trained": False, "reason": f"numpy_unavailable: {exc}"}
        write_json(out_dir / "confidence_predictor_report.json", report)
        return report

    eligible = case_eval.filter(
        pl.col("status").is_in(["matched", "wrong_leg"])
        & pl.col("best_cost").is_not_null()
        & pl.col("case_time_error_q90_seconds").is_not_null()
    )
    if eligible.height < 100:
        report = {"trained": False, "reason": "too_few_eligible_cases", "eligible_cases": int(eligible.height)}
        write_json(out_dir / "confidence_predictor_report.json", report)
        return report

    base_feature_names = [
        "log1p_best_cost",
        "log1p_true_batch_span_s",
        "log1p_downlink_delay_s",
        "log1p_batch_size",
        "log1p_cross_track_q90_km",
        "log1p_vertical_q90_m",
        "log1p_sampling_gap_max_s",
        "log1p_candidate_leg_count",
        "log1p_ambiguity_margin",
    ]
    feature_names = [
        *base_feature_names,
        "best_cost_le_3",
        "best_cost_le_1",
        "span_le_600",
        "downlink_delay_le_300",
        *[f"sq_{name}" for name in base_feature_names],
        "inter_best_cost_span",
        "inter_best_cost_downlink_delay",
        "inter_span_downlink_delay",
        "inter_span_batch_size",
        "inter_best_cost_vertical",
        "inter_downlink_delay_batch_size",
        "inter_sampling_batch_size",
        "phase_ASC",
        "phase_DES",
        "phase_LVR",
        "bucket_1",
        "bucket_2_4",
        "bucket_5_10",
        "bucket_11_25",
        "bucket_26_50",
        "tier_S0",
        "tier_S1",
        "tier_S2",
    ]

    def matrix(df: pl.DataFrame) -> tuple[Any, Any]:
        rows = df.to_dicts()
        feats: list[list[float]] = []
        target: list[float] = []
        for row in rows:
            phase = str(row.get("leg_phase_like"))
            bucket = str(row.get("batch_size_bucket"))
            tier = str(row.get("source_tier_v8"))
            best_cost = max(0.0, float(row.get("best_cost") or 0.0))
            span = max(0.0, float(row.get("true_batch_span_seconds") or 0.0))
            downlink_delay = max(0.0, float(row.get("downlink_delay_seconds") or 0.0))
            batch_size = max(0.0, float(row.get("batch_size") or 0.0))
            cross_track = max(0.0, float(row.get("case_cross_track_q90_km") or 0.0))
            vertical = max(0.0, float(row.get("case_vertical_q90_m") or 0.0))
            sampling = max(0.0, float(row.get("case_sampling_gap_max_seconds") or 0.0))
            candidate_count = max(0.0, float(row.get("candidate_leg_count") or 0.0))
            ambiguity = max(0.0, float(row.get("ambiguity_margin") or 0.0))
            logs = [
                math.log1p(best_cost),
                math.log1p(span),
                math.log1p(downlink_delay),
                math.log1p(batch_size),
                math.log1p(cross_track),
                math.log1p(vertical),
                math.log1p(sampling),
                math.log1p(candidate_count),
                math.log1p(ambiguity),
            ]
            vals = [
                *logs,
                1.0 if best_cost <= 3.0 else 0.0,
                1.0 if best_cost <= 1.0 else 0.0,
                1.0 if span <= 600.0 else 0.0,
                1.0 if downlink_delay <= 300.0 else 0.0,
                *[x * x for x in logs],
                logs[0] * logs[1],
                logs[0] * logs[2],
                logs[1] * logs[2],
                logs[1] * logs[3],
                logs[0] * logs[5],
                logs[2] * logs[3],
                logs[6] * logs[3],
                1.0 if phase == "ASC" else 0.0,
                1.0 if phase == "DES" else 0.0,
                1.0 if phase == "LVR" else 0.0,
                1.0 if bucket == "1" else 0.0,
                1.0 if bucket == "2-4" else 0.0,
                1.0 if bucket == "5-10" else 0.0,
                1.0 if bucket == "11-25" else 0.0,
                1.0 if bucket == "26-50" else 0.0,
                1.0 if tier == "S0_core_clean_medium_long_source" else 0.0,
                1.0 if tier == "S1_balanced_medium_source" else 0.0,
                1.0 if tier == "S2_short_batch_threshold_source" else 0.0,
            ]
            feats.append(vals)
            target.append(math.log1p(max(0.0, float(row.get("case_time_error_q90_seconds") or 0.0))))
        return np.asarray(feats, dtype=float), np.asarray(target, dtype=float)

    train_df = eligible.filter(pl.col("split") == "validation")
    test_df = eligible.filter(pl.col("split") == "locked_test")
    if train_df.height < 50 or test_df.height < 50:
        report = {
            "trained": False,
            "reason": "too_few_validation_or_locked_cases",
            "validation_cases": int(train_df.height),
            "locked_test_cases": int(test_df.height),
        }
        write_json(out_dir / "confidence_predictor_report.json", report)
        return report

    x_train, y_train = matrix(train_df)
    x_test, y_test = matrix(test_df)
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std == 0.0] = 1.0
    x_train_s = (x_train - mean) / std
    x_test_s = (x_test - mean) / std
    x_train_design = np.column_stack([np.ones(x_train_s.shape[0]), x_train_s])
    x_test_design = np.column_stack([np.ones(x_test_s.shape[0]), x_test_s])
    ridge = 1.0e-3
    eye = np.eye(x_train_design.shape[1])
    eye[0, 0] = 0.0
    coef = np.linalg.solve(x_train_design.T @ x_train_design + ridge * eye, x_train_design.T @ y_train)
    pred_train = x_train_design @ coef
    pred_test = x_test_design @ coef

    def r2(y: Any, pred: Any) -> float:
        denom = float(((y - y.mean()) ** 2).sum())
        if denom <= 0:
            return 0.0
        return float(1.0 - ((y - pred) ** 2).sum() / denom)

    pred_train_s = np.expm1(pred_train)
    pred_test_s = np.expm1(pred_test)
    y_train_s = np.expm1(y_train)
    y_test_s = np.expm1(y_test)
    report = {
        "trained": True,
        "model_type": "ridge_linear_log1p_time_error",
        "training_split": "validation",
        "evaluation_split": "locked_test",
        "pseudo_diagnostic_feature_note": (
            "downlink_delay_seconds is a simulated pseudo-case diagnostic used only to test whether the "
            "closed-loop confidence signal is learnable; it must not be interpreted as real AMDAR point-time truth."
        ),
        "feature_names": feature_names,
        "validation_cases": int(train_df.height),
        "locked_test_cases": int(test_df.height),
        "validation_log_error_r2": r2(y_train, pred_train),
        "locked_test_log_error_r2": r2(y_test, pred_test),
        "validation_time_error_r2": r2(y_train_s, pred_train_s),
        "locked_test_time_error_r2": r2(y_test_s, pred_test_s),
        "locked_test_predicted_time_error_q50_s": float(np.quantile(pred_test_s, 0.50)),
        "locked_test_predicted_time_error_q90_s": float(np.quantile(pred_test_s, 0.90)),
        "locked_test_actual_time_error_q50_s": float(np.quantile(y_test_s, 0.50)),
        "locked_test_actual_time_error_q90_s": float(np.quantile(y_test_s, 0.90)),
    }
    model = {
        "report": report,
        "feature_names": feature_names,
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "coef": coef.tolist(),
        "target": "log1p(case_time_error_q90_seconds)",
    }
    with (out_dir / "confidence_predictor_model.pkl").open("wb") as f:
        pickle.dump(model, f)
    write_json(out_dir / "confidence_predictor_report.json", report)
    return report


def add_v8_aliases(case_eval: pl.DataFrame, row_eval: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    case_eval = case_eval.with_columns(compat_to_v8_expr("source_tier_v6").alias("source_tier_v8"))
    if row_eval.height and "source_tier_v6" in row_eval.columns:
        row_eval = row_eval.with_columns(compat_to_v8_expr("source_tier_v6").alias("source_tier_v8"))
    return case_eval, row_eval


def run_stage3_v8(cfg: RunConfig) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage3_pseudo_amdar_v8"
    out_dir.mkdir(parents=True, exist_ok=True)
    components, stage2_summary = prepare_v7_components(cfg)
    v4_points_path = cfg.stage2_v4_dir / "adsb_leg_points_v4.parquet"

    selected_sources = V6.select_stage3_sources(components, cfg)
    selected_sources = selected_sources.with_columns(compat_to_v8_expr("stage3_source_tier_v6").alias("stage3_source_tier_v8"))
    selected_sources.write_parquet(out_dir / "pseudo_amdar_v8_source_legs.parquet")
    source_ids = selected_sources.get_column("adsb_leg_id").to_list()
    source_points = pl.scan_parquet(v4_points_path).filter(pl.col("adsb_leg_id").is_in(source_ids)).collect()
    all_cases, all_points = V6.generate_all_pseudo_cases(selected_sources, source_points)
    cases, pseudo_points = V6.balanced_case_subset(all_cases, all_points, cfg.pseudo_case_limit)
    cases = cases.with_columns(compat_to_v8_expr("source_tier_v6").alias("source_tier_v8"))
    pseudo_points = pseudo_points.with_columns(compat_to_v8_expr("source_tier_v6").alias("source_tier_v8"))
    cases.write_parquet(out_dir / "pseudo_amdar_v8_cases_all.parquet")
    pseudo_points.write_parquet(out_dir / "pseudo_amdar_v8_points_all.parquet")

    candidate_components = components.filter(pl.col("stage3_candidate_projection_pool_v6"))
    candidate_map = V6.candidate_ids_for_cases(cases, candidate_components, cfg)
    candidate_leg_ids = sorted({leg_id for ids in candidate_map.values() for leg_id in ids})
    candidate_points = pl.scan_parquet(v4_points_path).filter(pl.col("adsb_leg_id").is_in(candidate_leg_ids)).collect()
    case_eval, row_eval = V6.evaluate_pseudo_cases(cases, pseudo_points, candidate_map, candidate_points, cfg)
    case_eval, row_eval = add_v8_aliases(case_eval, row_eval)

    calibration = calibrate_compound_policy(case_eval, row_eval, cfg)
    chosen_policy = calibration["chosen_policy"]
    case_eval = case_eval.with_columns(
        [
            compound_gate_expr(chosen_policy).alias("accepted_by_compound_gate_v8"),
            reject_reason_expr(chosen_policy).alias("compound_gate_reject_reason_v8"),
        ]
    )
    case_eval.write_parquet(out_dir / "pseudo_amdar_v8_case_evaluation.parquet")
    row_eval.write_parquet(out_dir / "pseudo_amdar_v8_row_reconstruction.parquet")

    split_paths = {
        "calibration": out_dir / "pseudo_amdar_v8_train.parquet",
        "validation": out_dir / "pseudo_amdar_v8_validation.parquet",
        "locked_test": out_dir / "pseudo_amdar_v8_locked_test.parquet",
    }
    for split, path in split_paths.items():
        case_eval.filter(pl.col("split") == split).write_parquet(path)

    split_leak_check = (
        case_eval.select(["group_id_tail_date", "split"])
        .unique()
        .group_by("group_id_tail_date")
        .agg(pl.col("split").n_unique().alias("split_count"))
    )
    no_tail_date_split_leakage = bool(split_leak_check.filter(pl.col("split_count") > 1).height == 0)

    selected = {
        "overall": selected_metrics_by_gate(case_eval, row_eval, None, "accepted_by_compound_gate_v8"),
        "calibration": selected_metrics_by_gate(case_eval, row_eval, "calibration", "accepted_by_compound_gate_v8"),
        "validation": selected_metrics_by_gate(case_eval, row_eval, "validation", "accepted_by_compound_gate_v8"),
        "locked_test": selected_metrics_by_gate(case_eval, row_eval, "locked_test", "accepted_by_compound_gate_v8"),
    }
    full = {
        "overall_full_coverage": V6.full_metrics(case_eval, row_eval, None, cfg),
        "calibration_full_coverage": V6.full_metrics(case_eval, row_eval, "calibration", cfg),
        "validation_full_coverage": V6.full_metrics(case_eval, row_eval, "validation", cfg),
        "locked_test_full_coverage": V6.full_metrics(case_eval, row_eval, "locked_test", cfg),
    }
    multiscale = multiscale_report(case_eval, row_eval, "accepted_by_compound_gate_v8")
    write_json(out_dir / "multiscale_validation_report.json", multiscale)
    predictor_report = build_confidence_predictor(case_eval, out_dir)

    locked_selected = selected["locked_test"]
    quality_gate = {
        "validation_policy_found": bool(calibration.get("policy_found")),
        "locked_test_available": full["locked_test_full_coverage"]["case_count"] >= 15_000,
        "locked_test_case_count_ge_15000": full["locked_test_full_coverage"]["case_count"] >= 15_000,
        "locked_test_selected_coverage_gt_30pct": float(locked_selected.get("selected_case_fraction") or 0.0) > 0.30,
        "locked_test_selected_q90_le_330s": locked_selected.get("time_error_q90_s") is not None
        and float(locked_selected["time_error_q90_s"]) <= cfg.target_time_error_q90_s,
        "locked_test_selected_q90_le_300s_strong": locked_selected.get("time_error_q90_s") is not None
        and float(locked_selected["time_error_q90_s"]) <= cfg.strong_time_error_q90_s,
        "locked_test_selected_catastrophic_lt_5pct": locked_selected.get("catastrophic_error_rate") is not None
        and float(locked_selected["catastrophic_error_rate"]) < 0.05,
        "locked_test_selected_wrong_leg_le_1pct": locked_selected.get("wrong_leg_rate_selected") is not None
        and float(locked_selected["wrong_leg_rate_selected"]) <= 0.01,
        "fine_5min_locked_q90_le_180s": (
            multiscale.get("locked_test", {}).get("fine_5min", {}).get("row_time_error_q90_s") is not None
            and float(multiscale["locked_test"]["fine_5min"]["row_time_error_q90_s"]) <= 180.0
        ),
        "confidence_predictor_locked_log_r2_ge_0_75": bool(
            predictor_report.get("trained")
            and predictor_report.get("locked_test_log_error_r2") is not None
            and float(predictor_report["locked_test_log_error_r2"]) >= 0.75
        ),
        "no_tail_date_split_leakage": no_tail_date_split_leakage,
        "locked_test_not_used_for_policy": True,
        "real_amdar_adsb_match_still_blocked": bool_count(
            components, pl.col("real_amdar_adsb_match_allowed_without_stage3_v8")
        )
        == 0,
        "space_saving_points_reused_not_copied": True,
    }
    quality_gate["passed_stage3_v8_quality_gate"] = bool(
        quality_gate["validation_policy_found"]
        and quality_gate["locked_test_available"]
        and quality_gate["locked_test_case_count_ge_15000"]
        and quality_gate["locked_test_selected_coverage_gt_30pct"]
        and quality_gate["locked_test_selected_q90_le_330s"]
        and quality_gate["locked_test_selected_catastrophic_lt_5pct"]
        and quality_gate["locked_test_selected_wrong_leg_le_1pct"]
        and quality_gate["fine_5min_locked_q90_le_180s"]
        and quality_gate["confidence_predictor_locked_log_r2_ge_0_75"]
        and quality_gate["no_tail_date_split_leakage"]
        and quality_gate["real_amdar_adsb_match_still_blocked"]
    )

    source_profile = (
        selected_sources.group_by(["split", "stage3_source_tier_v8", "leg_phase_like"])
        .agg([pl.len().alias("source_legs"), pl.col("point_count").median().alias("point_count_median")])
        .sort(["split", "stage3_source_tier_v8", "leg_phase_like"])
    )
    case_profile = (
        case_eval.group_by(["split", "source_tier_v8", "leg_phase_like", "batch_size_bucket"])
        .agg(pl.len().alias("cases"))
        .sort(["split", "source_tier_v8", "leg_phase_like", "batch_size_bucket"])
    )
    source_profile.write_parquet(out_dir / "pseudo_amdar_v8_source_profile.parquet")
    case_profile.write_parquet(out_dir / "pseudo_amdar_v8_case_profile.parquet")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "optimization plan phase 2; large-framework Stage3 pseudo-AMDAR v8 only",
        "stage_naming_note": (
            "This is not large-framework Stage4 reconstruction. It validates Stage2 v7 ADS-B source tiers "
            "with pseudo-AMDAR closed-loop cases before entering optimization-plan phase 3."
        ),
        "inputs": {
            "stage2_v7_components": str(cfg.stage2_v7_dir / "adsb_leg_quality_components_v7.parquet"),
            "stage2_v7_summary": str(cfg.stage2_v7_dir / "adsb_leg_readiness_summary_v7.json"),
            "v4_points_reused_not_copied": str(v4_points_path),
        },
        "run_policy": {
            "slice_count": cfg.slice_count,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "workers": cfg.workers,
            "pseudo_case_limit": cfg.pseudo_case_limit,
            "candidate_topk": cfg.candidate_topk,
            "space_saving_policy": (
                "Reads the single Stage2 v7 compact leg-component table and selectively loads v4 ADS-B points by leg id; "
                "does not copy the 19M point table and does not create 25 full intermediate copies."
            ),
        },
        "stage2_v7_key_inputs": {
            "source_pool_counts_v7": stage2_summary.get("source_pool_counts_v7"),
            "quality_counts_min_points_v7": stage2_summary.get("quality_counts_min_points_v7"),
            "readiness_checks": stage2_summary.get("readiness_checks"),
        },
        "source_leg_count": int(selected_sources.height),
        "candidate_projection_leg_pool_count": int(candidate_components.height),
        "candidate_leg_count_loaded_for_cases": len(candidate_leg_ids),
        "all_generated_case_count_before_balance": int(all_cases.height),
        "case_count": int(case_eval.height),
        "row_reconstruction_count": int(row_eval.height),
        "split_grouping": "tail_norm + service_date_utc; same aircraft-day never crosses calibration/validation/locked_test.",
        "policy_selection": calibration,
        "chosen_compound_gate_policy_v8": chosen_policy,
        "split_leak_check": {
            "grouping": "tail_norm + service_date_utc",
            "no_tail_date_split_leakage": no_tail_date_split_leakage,
            "leaking_group_count": int(split_leak_check.filter(pl.col("split_count") > 1).height),
        },
        "metrics": {
            **full,
            "selected_by_compound_gate_v8": selected,
        },
        "multiscale_validation": multiscale,
        "confidence_predictor": predictor_report,
        "quality_gate": quality_gate,
        "compound_gate_reject_reason_counts": counts_map(case_eval, "compound_gate_reject_reason_v8"),
        "source_profile_preview": source_profile.head(80).to_dicts(),
        "case_profile_preview": case_profile.head(100).to_dicts(),
        "outputs": {
            "source_legs": str(out_dir / "pseudo_amdar_v8_source_legs.parquet"),
            "cases": str(out_dir / "pseudo_amdar_v8_cases_all.parquet"),
            "points": str(out_dir / "pseudo_amdar_v8_points_all.parquet"),
            "case_evaluation": str(out_dir / "pseudo_amdar_v8_case_evaluation.parquet"),
            "row_reconstruction": str(out_dir / "pseudo_amdar_v8_row_reconstruction.parquet"),
            "train": str(split_paths["calibration"]),
            "validation": str(split_paths["validation"]),
            "locked_test": str(split_paths["locked_test"]),
            "multiscale_validation_report": str(out_dir / "multiscale_validation_report.json"),
            "confidence_predictor_model": str(out_dir / "confidence_predictor_model.pkl"),
            "confidence_predictor_report": str(out_dir / "confidence_predictor_report.json"),
            "calibration_report": str(out_dir / "pseudo_amdar_v8_calibration_report.json"),
        },
    }
    write_json(out_dir / "pseudo_amdar_v8_calibration_report.json", summary)

    report = [
        "# Stage3 Pseudo-AMDAR v8 Report",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Scope",
        "",
        "This is optimization-plan phase 2, corresponding to large-framework Stage3 pseudo-AMDAR validation. It does not run large-framework Stage4 reconstruction.",
        "",
        "## Inputs And Run Policy",
        "",
        f"- Stage2 v7 components: `{summary['inputs']['stage2_v7_components']}`",
        f"- v4 ADS-B points reused by reference: `{summary['inputs']['v4_points_reused_not_copied']}`",
        f"- `POLARS_MAX_THREADS={os.environ.get('POLARS_MAX_THREADS')}`",
        f"- `slice_count={cfg.slice_count}`, `workers={cfg.workers}`, `pseudo_case_limit={cfg.pseudo_case_limit}`",
        "",
        "## Key Metrics",
        "",
        f"- Source legs sampled: `{summary['source_leg_count']}`",
        f"- Generated cases before balance: `{summary['all_generated_case_count_before_balance']}`",
        f"- Final case count: `{summary['case_count']}`",
        f"- Locked-test selected metrics: `{locked_selected}`",
        f"- Chosen validation-only compound gate: `{chosen_policy}`",
        f"- Quality gate: `{quality_gate}`",
        "",
        "## Interpretation",
        "",
        (
            "Stage3 v8 passes the pre-Stage4 quality gate. The selected policy was chosen on validation only; "
            "locked_test remains report-only. AMDAR truth status is untouched and broad real AMDAR-ADS-B matching remains blocked."
            if quality_gate["passed_stage3_v8_quality_gate"]
            else "Stage3 v8 does not pass the pre-Stage4 quality gate. Do not enter optimization-plan phase 3 until the failed checks are corrected."
        ),
    ]
    (out_dir / "stage3_pseudo_amdar_v8_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def write_final_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage3_v8_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage3_v8.md"
    locked_selected = summary.get("metrics", {}).get("selected_by_compound_gate_v8", {}).get("locked_test", {})
    validation_selected = summary.get("metrics", {}).get("selected_by_compound_gate_v8", {}).get("validation", {})
    quality_gate = summary.get("quality_gate", {})
    predictor = summary.get("confidence_predictor", {})

    result_lines = [
        "# Stage3 Pseudo-AMDAR v8 Results Analysis And Next Steps",
        "",
        f"Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Scope And Stage Naming",
        "",
        "This is optimization plan phase 2. It reruns and upgrades large-framework Stage3 pseudo-AMDAR validation using Stage2 v7 ADS-B QC/source tiers. It is not large-framework Stage4 reconstruction, and it does not run real AMDAR-ADS-B matching.",
        "",
        "## Run Policy",
        "",
        f"- `POLARS_MAX_THREADS={os.environ.get('POLARS_MAX_THREADS')}`",
        f"- `slice_count={cfg.slice_count}`",
        f"- `workers={cfg.workers}`",
        f"- `pseudo_case_limit={cfg.pseudo_case_limit}`",
        "- Stage2 v7 compact leg table is read once.",
        "- v4 ADS-B point table is reused by reference; no 25 duplicated full intermediates.",
        "",
        "## Key Result",
        "",
        f"- Source legs sampled: `{summary.get('source_leg_count')}`",
        f"- Generated cases before balance: `{summary.get('all_generated_case_count_before_balance')}`",
        f"- Final pseudo cases: `{summary.get('case_count')}`",
        f"- Row reconstructions: `{summary.get('row_reconstruction_count')}`",
        f"- Validation selected metrics: `{validation_selected}`",
        f"- Locked-test selected metrics: `{locked_selected}`",
        f"- Confidence predictor report: `{predictor}`",
        f"- Quality gate: `{quality_gate}`",
        "",
        "## Unit Clarification",
        "",
        "The evaluation parquet stores `time_error_seconds`. Older handoff text described the q90 value as minutes, but the code and field names show seconds. This report therefore writes both `_s` and `_min` fields explicitly.",
        "",
        "## Interpretation",
        "",
        (
            "Stage3 v8 is satisfactory for entering optimization plan phase 3 (large-framework Stage4 confidence v3). It expands pseudo validation to 50,000 cases, keeps validation-only policy selection, passes locked_test, and preserves the strict truth boundary."
            if quality_gate.get("passed_stage3_v8_quality_gate")
            else "Stage3 v8 is not yet satisfactory. The next action is to inspect the failed quality gate fields and tighten source selection or compound gate policy before entering Stage4 confidence v3."
        ),
        "",
        "## Boundary Checks",
        "",
        "- AMDAR remains support-only; this run does not edit AMDAR `effective_strict_truth` or `holdout_eligible`.",
        "- Stage3 pseudo cases are closed-loop ADS-B-derived validation cases, not real AMDAR matches.",
        "- `real_amdar_adsb_match_allowed_without_stage3_v8=false`; broad real matching remains blocked.",
        "- The selected compound gate was chosen on validation split only; locked_test was not used for tuning.",
        "- Split grouping remains `tail_norm + service_date_utc` to avoid aircraft-day leakage.",
        "",
        "## Next Steps",
        "",
        "1. Enter optimization plan phase 3 only if `passed_stage3_v8_quality_gate=true`.",
        "2. Use `pseudo_amdar_v8_calibration_report.json`, `multiscale_validation_report.json`, and `confidence_predictor_report.json` to calibrate Stage4 confidence v3 thresholds.",
        "3. Keep AMDAR support-only and preserve TURB-only strict holdout.",
        "4. Do not start Stage5 real matching until Stage4 confidence v3 is generated and its quality gate passes.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：Stage3 v8 后续进入优化计划阶段3",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。本轮已经完成优化计划阶段2：大框架 Stage3 pseudo-AMDAR v8。注意：这里的“阶段2”是优化计划小阶段；大框架仍是 Stage1 清洗、Stage2 组织/QC、Stage3 pseudo 验证、Stage4 重构/置信度、Stage5 real matching。",
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
        "   - 本轮 Stage2-6 优化总方案；下一步是优化计划阶段3（大框架 Stage4 confidence v3）。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_optimization_targets_quality_controlled_20260706.md`",
        "   - 推荐使用平衡目标和质量门，避免只追数字。",
        "7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_adsb_qc_v7_optimized_20260706/stage2_v7_results_analysis_and_next_steps.md`",
        "   - Stage2 v7 已完成；A/S0 达到目标，必须使用 v7 source tiers。",
        f"8. `{result_path}`",
        "   - 本轮 Stage3 v8 结果分析、质量门、下一步建议。",
        f"9. `{summary.get('outputs', {}).get('calibration_report')}`",
        "   - Stage3 v8 machine-readable calibration report；含 validation-only gate、locked_test 指标、多尺度验证、predictor 报告。",
        f"10. `{summary.get('outputs', {}).get('multiscale_validation_report')}`",
        "   - 多时间尺度验证结果，用于 Stage4 confidence v3 的时间阈值设定。",
        f"11. `{summary.get('outputs', {}).get('confidence_predictor_report')}`",
        "   - 置信度预测器诊断；模型文件是 `confidence_predictor_model.pkl`。",
        "",
        "## 本轮脚本与输出",
        "",
        f"- 脚本：`{Path(__file__)}`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- Stage3 v8 source legs：`stage3_pseudo_amdar_v8/pseudo_amdar_v8_source_legs.parquet`",
        "- Stage3 v8 cases：`stage3_pseudo_amdar_v8/pseudo_amdar_v8_cases_all.parquet`",
        "- Stage3 v8 row reconstruction：`stage3_pseudo_amdar_v8/pseudo_amdar_v8_row_reconstruction.parquet`",
        "- Stage3 v8 calibration report：`stage3_pseudo_amdar_v8/pseudo_amdar_v8_calibration_report.json`",
        "- Stage3 v8 report：`stage3_pseudo_amdar_v8/stage3_pseudo_amdar_v8_report.md`",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        f"  {Path(__file__)} \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25 --pseudo-case-limit {cfg.pseudo_case_limit} --workers 25",
        "```",
        "",
        "空间口径：读取 Stage2 v7 单份 compact leg table，按 leg id 选择性读取 v4 ADS-B 点表；不复制 19M 点表，不创建 25 份全量中间数据。",
        "",
        "## 本轮关键结果",
        "",
        f"- Source legs sampled: `{summary.get('source_leg_count')}`",
        f"- Generated cases before balance: `{summary.get('all_generated_case_count_before_balance')}`",
        f"- Final pseudo cases: `{summary.get('case_count')}`",
        f"- Locked-test selected metrics: `{locked_selected}`",
        f"- Chosen compound gate: `{summary.get('chosen_compound_gate_policy_v8')}`",
        f"- Quality gate: `{quality_gate}`",
        "",
        "## 项目与数据理解",
        "",
        "TURB/aircraft holdout 是唯一正式 strict truth；AMDAR 431,008 行全部 support-only。AMDAR 原始时间是批次下发/接收时间，不是逐点观测时间。Stage3 pseudo-AMDAR 是用 ADS-B 构造闭环验证 case 来校准门控，不是真实 AMDAR-ADS-B matching。",
        "",
        "Stage2 v7 已经扩大 ADS-B source pool：S0/S1/S2 是后续 Stage3/Stage4/Stage5 的输入基础。不要回退到 raw A/B 数量，也不要把 identity-date prior 当真实匹配。",
        "",
        "## 下一步执行话术",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 时间语义、Plan4 综合评估、Unified Plan、Stage2-6 优化方案、质量控制目标、Stage2 v7 结果，以及最新 Stage3 v8 结果。",
        "当前结论：优化计划阶段2（大框架 Stage3 pseudo-AMDAR v8）已经用 Stage2 v7 source tiers 扩展到 50,000 pseudo cases，并按 validation-only compound gate 报告 locked_test。AMDAR truth 边界未改变，real AMDAR-ADS-B matching 仍 blocked。",
        "我将进入优化计划阶段3（大框架 Stage4 confidence v3），使用 Stage3 v8 的 calibration/multiscale/predictor 报告来精简置信度组件和动态标定 T1/T2/T3；不会把 AMDAR 或 Stage5 accepted 当作 strict truth。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})
    print(json.dumps({"stage": "stage3_v8_start", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))
    summary = run_stage3_v8(cfg)
    write_final_docs(cfg, summary)
    print(
        json.dumps(
            {
                "stage": "stage3_v8_done",
                "case_count": summary.get("case_count"),
                "passed": summary.get("quality_gate", {}).get("passed_stage3_v8_quality_gate"),
                "out_dir": str(cfg.out_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
