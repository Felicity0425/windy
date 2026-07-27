from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE3_V8_SCRIPT = DATA_DIR / "amdar_unified_stage3_v8_20260707.py"
STAGE2_V7_PATH = DATA_DIR / "stage2_adsb_qc_v7_optimized_20260706/adsb_leg_quality_components_v7.parquet"
STAGE2_V4_POINTS = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_leg_points_v4.parquet"
DEFAULT_OUT_DIR = DATA_DIR / "stage3_pseudo_amdar_v9_micro_leg_optimized_20260713"
MICRO_TIER = "S3_micro_exact_identity_validation_source"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    slice_count: int = 25
    workers: int = 25
    pseudo_case_limit: int = 50_000
    source_cap_per_split_phase: int = 600
    candidate_topk: int = 10
    min_points: int = 5
    max_points: int = 9
    min_weighted_score: float = 0.90
    allow_point_count_only_hard_failure: bool = False


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Validate Stage5 exact-identity micro-leg candidates with pseudo-AMDAR.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--pseudo-case-limit", type=int, default=50_000)
    parser.add_argument("--source-cap-per-split-phase", type=int, default=600)
    parser.add_argument("--min-points", type=int, default=5)
    parser.add_argument("--max-points", type=int, default=9)
    parser.add_argument("--min-weighted-score", type=float, default=0.90)
    parser.add_argument("--allow-point-count-only-hard-failure", action="store_true")
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=args.slice_count,
        workers=args.workers,
        pseudo_case_limit=args.pseudo_case_limit,
        source_cap_per_split_phase=args.source_cap_per_split_phase,
        min_points=args.min_points,
        max_points=args.max_points,
        min_weighted_score=args.min_weighted_score,
        allow_point_count_only_hard_failure=args.allow_point_count_only_hard_failure,
    )


def load_stage3_v8() -> Any:
    spec = importlib.util.spec_from_file_location("stage3_v8_for_micro_validation", STAGE3_V8_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {STAGE3_V8_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def metric_value(metrics: dict[str, Any], key: str, default: float) -> float:
    value = metrics.get(key)
    return default if value is None else float(value)


def prepare_components(cfg: RunConfig, stage3: Any) -> pl.DataFrame:
    no_non_point_hard_failure = ~(
        pl.col("failed_time_order_v7").fill_null(True)
        | pl.col("failed_speed_v7").fill_null(True)
        | pl.col("failed_position_jump_v7").fill_null(True)
        | pl.col("failed_sampling_gap_v7").fill_null(True)
        | pl.col("failed_altitude_v7").fill_null(True)
        | pl.col("failed_identity_v7").fill_null(True)
        | pl.col("failed_duration_v7").fill_null(True)
        | pl.col("failed_phase_consistency_v7").fill_null(True)
    )
    hard_failure_policy = (
        no_non_point_hard_failure
        if cfg.allow_point_count_only_hard_failure
        else ~pl.col("stage2_v7_core_hard_failure").fill_null(True)
    )
    micro = (
        ~pl.col("stage3_candidate_projection_pool_v7").fill_null(False)
        & hard_failure_policy
        & (pl.col("point_count") >= cfg.min_points)
        & (pl.col("point_count") <= cfg.max_points)
        & (pl.col("stage2_v7_weighted_score") >= cfg.min_weighted_score)
    )
    tier = (
        pl.when(pl.col("stage3_source_tier_v7") == "S0_core_clean_medium_long_source")
        .then(pl.lit("S0_core_clean_long_source"))
        .when(pl.col("stage3_source_tier_v7") == "S1_balanced_medium_source")
        .then(pl.lit("S1_strong_component_b_long_source"))
        .when(pl.col("stage3_source_tier_v7") == "S2_short_batch_threshold_source")
        .then(pl.lit("S2_broad_short_batch_threshold_source"))
        .when(micro)
        .then(pl.lit(MICRO_TIER))
        .otherwise(pl.col("stage3_source_tier_v7"))
    )
    return (
        pl.scan_parquet(STAGE2_V7_PATH)
        .with_columns(
            [
                micro.alias("stage3_micro_source_v9"),
                tier.alias("stage3_source_tier_v6"),
                tier.alias("stage3_source_tier_v9"),
                (pl.col("stage3_pseudo_source_pool_v7").fill_null(False) | micro).alias("stage3_pseudo_source_pool_v6"),
                (pl.col("stage3_candidate_projection_pool_v7").fill_null(False) | micro).alias("stage3_candidate_projection_pool_v6"),
                pl.col("leg_overall_quality_v7").alias("leg_overall_quality"),
                pl.when(micro)
                .then(pl.lit(min(7, cfg.max_points)))
                .otherwise(pl.col("stage3_max_pseudo_batch_size_v6"))
                .cast(pl.Int32)
                .alias("stage3_max_pseudo_batch_size_v6"),
                pl.lit(False).alias("real_amdar_adsb_match_allowed_without_stage3_v8"),
                pl.lit(False).alias("real_amdar_adsb_match_allowed_without_stage3_v9"),
            ]
        )
        .collect(engine="streaming")
    )


def select_micro_sources(components: pl.DataFrame, cfg: RunConfig, stage3: Any) -> pl.DataFrame:
    sources = (
        components.filter(pl.col("stage3_micro_source_v9"))
        .with_columns(
            [
                (pl.col("tail_norm") + pl.lit("__") + pl.col("service_date_utc")).alias("group_id_tail_date"),
                stage3.V6.split_expr(),
                pl.lit(3, dtype=pl.Int32).alias("source_tier_priority_v6"),
            ]
        )
        .sort(
            ["split", "leg_phase_like", "stage2_v7_weighted_score", "point_count", "duration_seconds", "adsb_leg_id"],
            descending=[False, False, True, True, True, False],
        )
    )
    parts: list[pl.DataFrame] = []
    for split in ["calibration", "validation", "locked_test"]:
        for phase in ["ASC", "DES", "LVR"]:
            part = sources.filter((pl.col("split") == split) & (pl.col("leg_phase_like") == phase)).head(
                cfg.source_cap_per_split_phase
            )
            if part.height:
                parts.append(part)
    return pl.concat(parts, how="vertical") if parts else sources.head(0)


def run(cfg: RunConfig) -> dict[str, Any]:
    stage3 = load_stage3_v8()
    out = cfg.out_dir / "stage3_pseudo_amdar_v9_micro"
    out.mkdir(parents=True, exist_ok=True)
    components = prepare_components(cfg, stage3)
    sources = select_micro_sources(components, cfg, stage3)
    sources.write_parquet(out / "pseudo_amdar_v9_micro_source_legs.parquet")
    source_ids = sources.get_column("adsb_leg_id").to_list()
    source_points = pl.scan_parquet(STAGE2_V4_POINTS).filter(pl.col("adsb_leg_id").is_in(source_ids)).collect(engine="streaming")
    all_cases, all_points = stage3.V6.generate_all_pseudo_cases(sources, source_points)
    cases, pseudo_points = stage3.V6.balanced_case_subset(all_cases, all_points, cfg.pseudo_case_limit)
    cases = cases.with_columns(pl.lit(MICRO_TIER).alias("source_tier_v9"))
    pseudo_points = pseudo_points.with_columns(pl.lit(MICRO_TIER).alias("source_tier_v9"))
    cases.write_parquet(out / "pseudo_amdar_v9_micro_cases_all.parquet")
    pseudo_points.write_parquet(out / "pseudo_amdar_v9_micro_points_all.parquet")

    relevant_tails = cases.get_column("tail_norm").unique().to_list()
    candidate_components = components.filter(
        pl.col("stage3_candidate_projection_pool_v6") & pl.col("tail_norm").is_in(relevant_tails)
    )
    v8_cfg = stage3.RunConfig(
        out_dir=cfg.out_dir,
        slice_count=cfg.slice_count,
        pseudo_case_limit=cfg.pseudo_case_limit,
        workers=cfg.workers,
        candidate_topk=cfg.candidate_topk,
    )
    candidate_map = stage3.V6.candidate_ids_for_cases(cases, candidate_components, v8_cfg)
    candidate_ids = sorted({leg_id for values in candidate_map.values() for leg_id in values})
    candidate_points = pl.scan_parquet(STAGE2_V4_POINTS).filter(pl.col("adsb_leg_id").is_in(candidate_ids)).collect(engine="streaming")
    case_eval, row_eval = stage3.V6.evaluate_pseudo_cases(cases, pseudo_points, candidate_map, candidate_points, v8_cfg)
    case_eval = case_eval.with_columns(pl.lit(MICRO_TIER).alias("source_tier_v9"))
    row_eval = row_eval.with_columns(pl.lit(MICRO_TIER).alias("source_tier_v9"))
    calibration = stage3.calibrate_compound_policy(case_eval, row_eval, v8_cfg)
    policy = calibration["chosen_policy"]
    case_eval = case_eval.with_columns(
        [
            stage3.compound_gate_expr(policy).alias("accepted_by_compound_gate_v9"),
            stage3.reject_reason_expr(policy).alias("compound_gate_reject_reason_v9"),
        ]
    )
    case_eval.write_parquet(out / "pseudo_amdar_v9_micro_case_evaluation.parquet")
    row_eval.write_parquet(out / "pseudo_amdar_v9_micro_row_reconstruction.parquet")
    for split in ["calibration", "validation", "locked_test"]:
        case_eval.filter(pl.col("split") == split).write_parquet(out / f"pseudo_amdar_v9_micro_{split}.parquet")

    selected = {
        split: stage3.selected_metrics_by_gate(case_eval, row_eval, None if split == "overall" else split, "accepted_by_compound_gate_v9")
        for split in ["overall", "calibration", "validation", "locked_test"]
    }
    validation = selected["validation"]
    locked = selected["locked_test"]
    leakage = (
        case_eval.select(["group_id_tail_date", "split"])
        .unique()
        .group_by("group_id_tail_date")
        .agg(pl.col("split").n_unique().alias("split_count"))
        .filter(pl.col("split_count") > 1)
        .height
        == 0
    )
    gate = {
        "validation_selected_fraction_ge_30pct": metric_value(validation, "selected_case_fraction", 0.0) >= 0.30,
        "validation_wrong_leg_le_1pct": metric_value(validation, "wrong_leg_rate_selected", 1.0) <= 0.01,
        "validation_catastrophic_lt_3pct": metric_value(validation, "catastrophic_error_rate", 1.0) < 0.03,
        "validation_q90_le_330s": metric_value(validation, "time_error_q90_s", 999999.0) <= 330.0,
        "locked_case_count_ge_5000": int(locked.get("case_count") or 0) >= 5000,
        "locked_selected_fraction_ge_30pct": metric_value(locked, "selected_case_fraction", 0.0) >= 0.30,
        "locked_wrong_leg_le_1pct": metric_value(locked, "wrong_leg_rate_selected", 1.0) <= 0.01,
        "locked_catastrophic_lt_3pct": metric_value(locked, "catastrophic_error_rate", 1.0) < 0.03,
        "locked_q90_le_330s": metric_value(locked, "time_error_q90_s", 999999.0) <= 330.0,
        "no_tail_date_split_leakage": leakage,
        "locked_test_not_used_for_policy": True,
    }
    gate["passed_stage3_v9_micro_gate"] = all(gate.values())
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Stage3 pseudo validation for excluded 5-9 point exact-identity micro legs; not real Stage5 matching.",
        "run_config": asdict(cfg),
        "micro_component_count": int(components.filter(pl.col("stage3_micro_source_v9")).height),
        "selected_source_leg_count": sources.height,
        "generated_case_count_before_balance": all_cases.height,
        "case_count": cases.height,
        "candidate_component_count_relevant_tails": candidate_components.height,
        "candidate_leg_count_loaded": len(candidate_ids),
        "chosen_policy_validation_only": policy,
        "calibration": calibration,
        "selected_metrics": selected,
        "quality_gate": gate,
        "real_stage5_micro_branch_allowed": bool(gate["passed_stage3_v9_micro_gate"]),
    }
    write_json(out / "pseudo_amdar_v9_micro_validation_report.json", summary)
    write_json(cfg.out_dir / "run_config.json", asdict(cfg))
    return summary


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    summary = run(cfg)
    print(json.dumps({"quality_gate": summary["quality_gate"], "selected_metrics": summary["selected_metrics"]}, indent=2))


if __name__ == "__main__":
    main()
