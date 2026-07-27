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
STAGE5_V4_SCRIPT = DATA_DIR / "amdar_unified_stage5_v4_matching_20260708.py"
EXPANSION_SCRIPT = DATA_DIR / "amdar_unified_stage5_v5_exact_leg_expansion_diagnostic_20260713.py"
STAGE5_V4_DIR = DATA_DIR / "stage5_v4_matching_optimized_20260708/stage5_v4"
STAGE3_V9_REPORT = DATA_DIR / "stage3_pseudo_amdar_v9_micro_leg_optimized_20260713/stage3_pseudo_amdar_v9_micro/pseudo_amdar_v9_micro_validation_report.json"
STAGE3_V10_TINY_REPORT = DATA_DIR / "stage3_pseudo_amdar_v10_tiny_leg_optimized_20260714_validated/stage3_pseudo_amdar_v9_micro/pseudo_amdar_v9_micro_validation_report.json"
STAGE4_V3_SUMMARY = DATA_DIR / "stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/confidence_tier_summary_v3.json"
DEFAULT_OUT_DIR = DATA_DIR / "stage5_v5_matching_optimized_20260713"
MICRO_TIER = "SX_exact_identity_unvalidated_diagnostic"
TINY_TIER = "SX_tiny_exact_identity_v10_validated"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    slice_count: int = 25
    workers: int = 25
    candidate_topk: int = 10
    micro_min_points: int = 5
    micro_max_points: int = 9
    micro_min_weighted_score: float = 0.90


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Run validated Stage5 v5 matching with exact-identity micro-leg expansion.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--candidate-topk", type=int, default=10)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=args.slice_count,
        workers=args.workers,
        candidate_topk=args.candidate_topk,
    )


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def counts_map(df: pl.DataFrame, column: str) -> dict[str, int]:
    if df.height == 0 or column not in df.columns:
        return {}
    values = df.select(pl.col(column).cast(pl.Utf8, strict=False).fill_null("null")).to_series().value_counts().sort("count", descending=True)
    return {str(key): int(count) for key, count in values.iter_rows()}


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.out_dir / "stage5_v5"
    out.mkdir(parents=True, exist_ok=True)
    stage5 = load_module("stage5_v4_for_stage5_v5", STAGE5_V4_SCRIPT)
    expansion = load_module("stage5_v5_expansion_builder", EXPANSION_SCRIPT)
    stage3_v9 = read_json(STAGE3_V9_REPORT)
    stage3_v10_tiny = read_json(STAGE3_V10_TINY_REPORT)
    stage4_v3 = read_json(STAGE4_V3_SUMMARY)
    if not stage3_v9.get("quality_gate", {}).get("passed_stage3_v9_micro_gate"):
        raise RuntimeError("Stage3 v9 micro-leg validation gate did not pass")
    if not stage3_v10_tiny.get("quality_gate", {}).get("passed_stage3_v9_micro_gate"):
        raise RuntimeError("Stage3 v10 tiny-leg validation gate did not pass")
    if not stage4_v3.get("stage4_completion_checks", {}).get("passed_stage4_next_window_quality_gate"):
        raise RuntimeError("Stage4 v3 next-window quality gate did not pass")

    batch = pl.read_parquet(STAGE5_V4_DIR / "amdar_batch_base_v4.parquet")
    v4_candidates = pl.read_parquet(STAGE5_V4_DIR / "amdar_adsb_candidate_legs_v4.parquet")
    v4_diagnostics = pl.read_parquet(STAGE5_V4_DIR / "amdar_adsb_batch_diagnostics_v4.parquet")
    rejected_ids = v4_diagnostics.filter(
        ~pl.col("accepted_by_stage5_v4_layered_gate").fill_null(False)
    ).select("amdar_batch_id")
    rejected_batch = batch.join(rejected_ids, on="amdar_batch_id", how="semi")
    expansion_cfg = expansion.RunConfig(
        out_dir=cfg.out_dir,
        slice_count=cfg.slice_count,
        workers=cfg.workers,
        min_points=cfg.micro_min_points,
        max_points=cfg.micro_max_points,
        min_weighted_score=cfg.micro_min_weighted_score,
        allow_point_count_only_hard_failure=False,
        source_tier=MICRO_TIER,
    )
    micro_candidates, eligible_micro_leg_count = expansion.build_candidates(expansion_cfg, rejected_batch)
    tiny_expansion_cfg = expansion.RunConfig(
        out_dir=cfg.out_dir,
        slice_count=cfg.slice_count,
        workers=cfg.workers,
        min_points=2,
        max_points=4,
        min_weighted_score=0.65,
        allow_point_count_only_hard_failure=True,
        source_tier=TINY_TIER,
    )
    tiny_candidates, eligible_tiny_leg_count = expansion.build_candidates(tiny_expansion_cfg, rejected_batch)
    candidates = pl.concat([v4_candidates, micro_candidates, tiny_candidates], how="vertical_relaxed").sort(
        ["amdar_batch_id", "candidate_seed_score", "adsb_leg_id"]
    )
    candidates.write_parquet(out / "amdar_adsb_candidate_legs_v5.parquet")

    scorer_dir = Path("/tmp/stage5_v5_internal_v4_scorer_20260713")
    scorer_dir.mkdir(parents=True, exist_ok=True)
    scorer_cfg = stage5.RunConfig(
        out_dir=cfg.out_dir,
        slice_count=cfg.slice_count,
        workers=cfg.workers,
        candidate_topk=cfg.candidate_topk,
    )
    match, diagnostics, _, raw_summary = stage5.run_matching(scorer_cfg, batch, candidates, scorer_dir)
    is_micro = pl.col("best_stage3_source_tier_v7") == MICRO_TIER
    is_tiny = pl.col("best_stage3_source_tier_v7") == TINY_TIER
    is_validated_expansion = is_micro | is_tiny
    ambiguity_ok = (pl.col("evaluated_candidate_count") <= 1) | (pl.col("ambiguity_margin") >= 1.5)
    micro_v9_policy_pass = (
        (pl.col("best_cost") <= 2.0)
        & (pl.col("cross_track_q90_km") <= 1.0)
        & (pl.col("vertical_q90_m") <= 500.0)
        & (pl.col("sampling_gap_max_seconds") <= 600.0)
        & ambiguity_ok
    )
    official_accept = pl.col("accepted_by_stage5_v4_layered_gate") & (~is_validated_expansion | micro_v9_policy_pass)
    diagnostics = diagnostics.with_columns(official_accept.alias("accepted_by_stage5_v5_layered_gate")).with_columns(
        [
            pl.when(pl.col("accepted_by_stage5_v5_layered_gate") & is_micro)
            .then(pl.lit("C"))
            .when(pl.col("accepted_by_stage5_v5_layered_gate") & is_tiny)
            .then(pl.lit("C"))
            .when(pl.col("accepted_by_stage5_v5_layered_gate"))
            .then(pl.col("stage5_match_grade_v4"))
            .otherwise(pl.lit(None, dtype=pl.Utf8))
            .alias("stage5_match_grade_v5"),
            pl.when(pl.col("accepted_by_stage5_v5_layered_gate") & is_micro)
            .then(pl.lit(0.40))
            .when(pl.col("accepted_by_stage5_v5_layered_gate") & is_tiny)
            .then(pl.lit(0.30))
            .when(pl.col("accepted_by_stage5_v5_layered_gate"))
            .then(pl.col("stage5_match_confidence_v4"))
            .otherwise(pl.lit(0.0))
            .alias("stage5_match_confidence_v5"),
            pl.when(pl.col("accepted_by_stage5_v5_layered_gate") & is_micro)
            .then(pl.lit("accepted_v5_grade_C_exact_micro_leg_support_only"))
            .when(pl.col("accepted_by_stage5_v5_layered_gate") & is_tiny)
            .then(pl.lit("accepted_v5_grade_C_exact_tiny_leg_support_only"))
            .when(pl.col("accepted_by_stage5_v5_layered_gate"))
            .then(pl.col("stage5_acceptance_reason_v4"))
            .otherwise(pl.lit(None, dtype=pl.Utf8))
            .alias("stage5_acceptance_reason_v5"),
            pl.when(is_micro)
            .then(pl.lit("I0_exact_tail_flight_date_micro_leg_v9_validated"))
            .when(is_tiny)
            .then(pl.lit("I0_exact_tail_flight_date_tiny_leg_v10_validated"))
            .otherwise(pl.col("identity_match_level"))
            .alias("identity_level_v5"),
            pl.when(pl.col("accepted_by_stage5_v5_layered_gate"))
            .then(pl.lit("accepted"))
            .when(pl.col("accepted_by_stage5_v4_layered_gate") & is_validated_expansion & ~micro_v9_policy_pass)
            .then(pl.lit("rejected_by_expansion_validation_gate"))
            .otherwise(pl.col("status"))
            .alias("status_v5"),
            pl.when(pl.col("accepted_by_stage5_v4_layered_gate") & is_validated_expansion & ~micro_v9_policy_pass)
            .then(pl.lit("validated_expansion_compound_gate_fail"))
            .when(pl.col("accepted_by_stage5_v5_layered_gate"))
            .then(pl.lit(None, dtype=pl.Utf8))
            .otherwise(pl.col("reject_reason"))
            .alias("reject_reason_v5"),
        ]
    )
    official_batch_ids = diagnostics.filter(pl.col("accepted_by_stage5_v5_layered_gate")).get_column("amdar_batch_id").to_list()
    match = match.filter(pl.col("amdar_batch_id").is_in(official_batch_ids))
    match = match.with_columns(
        [
            pl.when(pl.col("stage3_source_tier_v7").is_in([MICRO_TIER, TINY_TIER])).then(pl.lit("C")).otherwise(pl.col("stage5_match_grade_v4")).alias("stage5_match_grade_v5"),
            pl.when(pl.col("stage3_source_tier_v7") == MICRO_TIER)
            .then(pl.lit(0.40))
            .when(pl.col("stage3_source_tier_v7") == TINY_TIER)
            .then(pl.lit(0.30))
            .otherwise(pl.col("stage5_match_confidence_v4"))
            .alias("stage5_match_confidence_v5"),
            pl.when(pl.col("stage3_source_tier_v7") == MICRO_TIER)
            .then(pl.lit("I0_exact_tail_flight_date_micro_leg_v9_validated"))
            .when(pl.col("stage3_source_tier_v7") == TINY_TIER)
            .then(pl.lit("I0_exact_tail_flight_date_tiny_leg_v10_validated"))
            .otherwise(pl.col("identity_match_level"))
            .alias("identity_level_v5"),
            pl.lit(False).alias("estimated_time_is_strict_point_truth"),
            pl.lit("support_only_not_strict_truth").alias("usage_role"),
        ]
    )
    reject = diagnostics.filter(~pl.col("accepted_by_stage5_v5_layered_gate"))
    batch.write_parquet(out / "amdar_batch_base_v5.parquet")
    match.write_parquet(out / "amdar_adsb_match_v5.parquet")
    reject.write_parquet(out / "amdar_adsb_reject_v5.parquet")
    diagnostics.write_parquet(out / "amdar_adsb_batch_diagnostics_v5.parquet")

    accepted_groups = diagnostics.filter(pl.col("accepted_by_stage5_v5_layered_gate"))
    micro_accepted = accepted_groups.filter(pl.col("best_stage3_source_tier_v7") == MICRO_TIER)
    tiny_accepted = accepted_groups.filter(pl.col("best_stage3_source_tier_v7") == TINY_TIER)
    safety_checks = {
        "stage3_v9_micro_gate_passed": True,
        "stage3_v10_tiny_gate_passed": True,
        "stage4_v3_gate_passed": True,
        "batch_diagnostics_cover_all_56521": diagnostics.height == 56521,
        "accepted_rows_have_matched_leg": match.filter(pl.col("matched_adsb_leg_id").is_null()).height == 0,
        "accepted_rows_support_only": match.filter(pl.col("effective_strict_truth").fill_null(False)).height == 0,
        "accepted_rows_holdout_false": match.filter(pl.col("strict_holdout_eligible_v3").fill_null(False)).height == 0,
        "estimated_time_not_strict_point_truth": match.filter(pl.col("estimated_time_is_strict_point_truth")).height == 0,
        "usage_role_support_only": match.filter(pl.col("usage_role") != "support_only_not_strict_truth").height == 0,
        "micro_rows_exact_identity_only": micro_accepted.filter(pl.col("identity_level_v5") != "I0_exact_tail_flight_date_micro_leg_v9_validated").height == 0,
        "micro_rows_grade_c_only": micro_accepted.filter(pl.col("stage5_match_grade_v5") != "C").height == 0,
        "micro_rows_confidence_capped_0_40": micro_accepted.filter(pl.col("stage5_match_confidence_v5") > 0.40).height == 0,
        "micro_rows_satisfy_v9_cost": micro_accepted.filter(pl.col("best_cost") > 2.0).height == 0,
        "micro_rows_satisfy_v9_cross_track": micro_accepted.filter(pl.col("cross_track_q90_km") > 1.0).height == 0,
        "micro_rows_satisfy_v9_vertical": micro_accepted.filter(pl.col("vertical_q90_m") > 500.0).height == 0,
        "micro_rows_satisfy_v9_sampling_gap": micro_accepted.filter(pl.col("sampling_gap_max_seconds") > 600.0).height == 0,
        "micro_rows_satisfy_v9_ambiguity": micro_accepted.filter(
            (pl.col("evaluated_candidate_count") > 1) & (pl.col("ambiguity_margin") < 1.5)
        ).height
        == 0,
        "tiny_rows_exact_identity_only": tiny_accepted.filter(pl.col("identity_level_v5") != "I0_exact_tail_flight_date_tiny_leg_v10_validated").height == 0,
        "tiny_rows_grade_c_only": tiny_accepted.filter(pl.col("stage5_match_grade_v5") != "C").height == 0,
        "tiny_rows_confidence_capped_0_30": tiny_accepted.filter(pl.col("stage5_match_confidence_v5") > 0.30).height == 0,
        "tiny_rows_satisfy_v10_gate": tiny_accepted.filter(
            (pl.col("best_cost") > 2.0)
            | (pl.col("cross_track_q90_km") > 1.0)
            | (pl.col("vertical_q90_m") > 500.0)
            | (pl.col("sampling_gap_max_seconds") > 600.0)
            | ((pl.col("evaluated_candidate_count") > 1) & (pl.col("ambiguity_margin") < 1.5))
        ).height == 0,
    }
    safety_checks["passed_stage5_v5_safety_gate"] = all(safety_checks.values())
    accepted_batches = accepted_groups.height
    accepted_fraction = accepted_batches / max(1, diagnostics.height)
    target_checks = {
        "accepted_batches_ge_566": accepted_batches >= 566,
        "accepted_fraction_ge_1pct": accepted_fraction >= 0.01,
        "grades_a_b_c_present": {"A", "B", "C"}.issubset(set(accepted_groups.get_column("stage5_match_grade_v5").drop_nulls().to_list())),
    }
    target_checks["passed_stage5_v5_target_gate"] = all(target_checks.values())
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Large-framework Stage5 real AMDAR-ADS-B matching v5; optimization-plan phase 4.",
        "run_policy": {
            "POLARS_MAX_THREADS": 25,
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "space_policy": "Single compact candidate/output tables; one reused ADS-B point table; no 25 full copies.",
        },
        "inputs": {
            "stage5_v4_dir": str(STAGE5_V4_DIR),
            "stage3_v9_micro_report": str(STAGE3_V9_REPORT),
            "stage3_v10_tiny_report": str(STAGE3_V10_TINY_REPORT),
            "stage4_v3_summary": str(STAGE4_V3_SUMMARY),
        },
        "candidate_counts": {
            "v4_candidate_rows": v4_candidates.height,
            "v4_rejected_batches_expanded": rejected_batch.height,
            "eligible_micro_leg_count": eligible_micro_leg_count,
            "micro_candidate_rows": micro_candidates.height,
            "micro_candidate_batches": micro_candidates.select(pl.col("amdar_batch_id").n_unique()).item() if micro_candidates.height else 0,
            "eligible_tiny_leg_count": eligible_tiny_leg_count,
            "tiny_candidate_rows": tiny_candidates.height,
            "tiny_candidate_batches": tiny_candidates.select(pl.col("amdar_batch_id").n_unique()).item() if tiny_candidates.height else 0,
            "total_candidate_rows_v5": candidates.height,
        },
        "result": {
            "amdar_batches": diagnostics.height,
            "accepted_batches": accepted_batches,
            "accepted_rows": match.height,
            "accepted_fraction_of_all_batches": accepted_fraction,
            "incremental_micro_accepted_batches": micro_accepted.height,
            "incremental_tiny_accepted_batches": tiny_accepted.height,
            "accepted_by_grade_v5": counts_map(accepted_groups, "stage5_match_grade_v5"),
            "accepted_by_identity_level_v5": counts_map(accepted_groups, "identity_level_v5"),
            "reject_reason_counts": counts_map(diagnostics.filter(~pl.col("accepted_by_stage5_v5_layered_gate")), "reject_reason_v5"),
        },
        "raw_v4_scorer_summary": raw_summary,
        "safety_checks": safety_checks,
        "target_checks": target_checks,
        "stage6_allowed_mode": "target_branch" if target_checks["passed_stage5_v5_target_gate"] else "conservative_diagnostic_only",
        "truth_boundary": {
            "amdar_effective_strict_truth_rows": 0,
            "amdar_holdout_eligible_rows": 0,
            "estimated_time_is_strict_point_truth": False,
            "usage_role": "support_only_not_strict_truth",
        },
    }
    write_json(out / "amdar_adsb_match_diagnostics_v5.json", summary)
    write_json(cfg.out_dir / "run_config.json", asdict(cfg))
    print(json.dumps({"result": summary["result"], "safety_checks": safety_checks, "target_checks": target_checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
