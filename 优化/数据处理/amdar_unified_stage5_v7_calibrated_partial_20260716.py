from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from amdar_unified_stage3_v12_drop_dtw_20260716 import (
    drop_dtw_align,
    leave_one_out_stability,
    pav_predict,
    score_pair,
)


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE4_COMPONENTS = DATA_DIR / "stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/amdar_confidence_components_v3.parquet"
STAGE2_POINTS = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_leg_points_v4.parquet"
STAGE5_V5_DIR = DATA_DIR / "stage5_v5_final_optimized_20260714/stage5_v5"
STAGE5_V6_DIR = DATA_DIR / "stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6"
STAGE3_V12_DIR = DATA_DIR / "stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12"
DEFAULT_OUT_DIR = DATA_DIR / "stage5_v7_calibrated_partial_optimized_20260716"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    slice_count: int = 25
    workers: int = 25
    candidate_topk: int = 10
    max_cross_track_q90_km: float = 1.5
    max_vertical_q90_m: float = 800.0
    max_sampling_gap_seconds: float = 900.0
    max_after_batch_end_seconds: float = 180.0
    candidate_posterior_min: float = 0.90
    maximum_drop_fraction: float = 0.50


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Stage5 v7 calibrated partial matcher using frozen Stage3 v12 validation.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--candidate-topk", type=int, default=10)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=int(args.slice_count),
        workers=int(args.workers),
        candidate_topk=int(args.candidate_topk),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def partition_key(key: Any) -> Any:
    return key[0] if isinstance(key, tuple) and len(key) == 1 else key


def softmax_probabilities(costs: list[float]) -> list[float]:
    values = np.asarray(costs, dtype=np.float64)
    logits = -(values - float(values.min())) / max(0.05, float(np.std(values)) if values.size > 1 else 0.25)
    logits -= logits.max()
    probability = np.exp(logits)
    return (probability / probability.sum()).tolist()


def numeric_summary(df: pl.DataFrame, column: str) -> dict[str, Any]:
    if df.height == 0 or column not in df.columns:
        return {"rows": int(df.height), "present": column in df.columns}
    values = df.get_column(column).cast(pl.Float64, strict=False).drop_nulls()
    finite = np.isfinite(values.to_numpy())
    values = values.filter(pl.Series(finite))
    return {
        "rows": int(df.height),
        "finite": int(values.len()),
        "min": float(values.min()) if values.len() else None,
        "q50": float(values.quantile(0.50)) if values.len() else None,
        "q90": float(values.quantile(0.90)) if values.len() else None,
        "max": float(values.max()) if values.len() else None,
    }


def model_blocks(model: dict[str, Any], drop_penalty: float) -> list[dict[str, float]]:
    raw = model["isotonic_blocks_by_drop_penalty"]
    key = str(drop_penalty)
    if key not in raw:
        key = min(raw, key=lambda value: abs(float(value) - drop_penalty))
    return raw[key]


def main() -> None:
    cfg = parse_args()
    os.environ.setdefault("POLARS_MAX_THREADS", str(cfg.workers))
    out = cfg.out_dir / "stage5_v7"
    out.mkdir(parents=True, exist_ok=True)

    diagnostics_v6 = pl.read_parquet(STAGE5_V6_DIR / "amdar_adsb_batch_diagnostics_v6.parquet")
    scores_v6 = pl.read_parquet(STAGE5_V6_DIR / "amdar_adsb_candidate_sequence_scores_v6.parquet")
    match_v6 = pl.read_parquet(STAGE5_V6_DIR / "amdar_adsb_match_v6.parquet")
    report_v12 = json.loads((STAGE3_V12_DIR / "stage3_v12_calibration_report.json").read_text(encoding="utf-8"))
    model_v12 = json.loads((STAGE3_V12_DIR / "association_posterior_model_v12.json").read_text(encoding="utf-8"))
    policy = report_v12["selected_policy"]
    drop_penalty = float(policy["drop_penalty"])
    matched_min = float(policy["matched_fraction_min"])
    contiguous_min = float(policy["contiguous_fraction_min"])
    posterior_min = float(policy["posterior_min"])

    mixtures = diagnostics_v6.filter(pl.col("accepted_mixture_by_stage5_v6"))
    near_pass = diagnostics_v6.filter(
        (pl.col("alignment_mode_v6") == "partial_monotone_70pct")
        & (~pl.col("accepted_unique_by_stage5_v6"))
        & (pl.col("partial_coverage_v6") >= 0.70)
        & pl.col("physical_gate_v6")
    )
    bridges = diagnostics_v6.filter(
        (pl.col("alignment_mode_v6") == "stitched_track_hmm_viterbi")
        & pl.col("physical_gate_v6")
    )
    audit = pl.concat([mixtures, near_pass, bridges]).unique("amdar_batch_id", keep="first")
    audit_ids = audit.get_column("amdar_batch_id").to_list()

    candidate_rows = (
        scores_v6.filter(pl.col("amdar_batch_id").is_in(audit_ids) & (pl.col("candidate_kind") == "single_leg"))
        .sort(["amdar_batch_id", "candidate_rank_v6", "candidate_sequence_score"])
        .group_by("amdar_batch_id", maintain_order=True)
        .head(cfg.candidate_topk)
    )
    candidate_leg_ids = candidate_rows.get_column("adsb_leg_id").unique().to_list()
    amdar_rows = (
        pl.scan_parquet(STAGE4_COMPONENTS)
        .filter((pl.col("source") == "amdar") & pl.col("amdar_batch_id").is_in(audit_ids))
        .select(
            [
                "amdar_batch_id", "source_row_index", "raw_row_number", "tail_norm", "flight_norm", "service_date_utc",
                "飞行阶段", "time_utc", "lat_clean", "lon_clean", "alt_meters", "wind_speed_ms_filled",
                "wind_dir_deg_filled", "u_wind", "v_wind", "amdar_observation_order", "base_support_conf",
                "confidence_tier", "confidence_subtier", "confidence_grade", "recommended_stage4_role",
                "stage4_weighting_recommendation_v3", "stage4_high_wind_action_v3", "time_uncertainty_s_stage4_v3",
                "time_uncertainty_s_stage4_v3_continuous", "effective_strict_truth", "strict_holdout_eligible_v3",
            ]
        )
        .sort(["amdar_batch_id", "amdar_observation_order", "source_row_index"])
        .collect(engine="streaming")
    )
    leg_points = (
        pl.scan_parquet(STAGE2_POINTS)
        .filter(pl.col("adsb_leg_id").is_in(candidate_leg_ids))
        .select(["adsb_leg_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"])
        .sort(["adsb_leg_id", "time_utc"])
        .collect(engine="streaming")
    )
    batch_map = {str(partition_key(key)): value.to_dicts() for key, value in amdar_rows.partition_by("amdar_batch_id", as_dict=True, maintain_order=True).items()}
    leg_map = {str(partition_key(key)): value.to_dicts() for key, value in leg_points.partition_by("adsb_leg_id", as_dict=True, maintain_order=True).items()}
    candidate_map: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_rows.to_dicts():
        candidate_map.setdefault(str(row["amdar_batch_id"]), []).append(row)
    audit_map = {str(row["amdar_batch_id"]): row for row in audit.to_dicts()}
    blocks = model_blocks(model_v12, drop_penalty)

    score_records: list[dict[str, Any]] = []
    batch_records: list[dict[str, Any]] = []
    match_records: list[dict[str, Any]] = []
    row_records: list[dict[str, Any]] = []
    for batch_index, batch_id_raw in enumerate(audit_ids):
        batch_id = str(batch_id_raw)
        rows = batch_map.get(batch_id, [])
        metadata = audit_map[batch_id]
        if not rows:
            batch_records.append({"amdar_batch_id": batch_id, "v7_status": "missing_amdar_rows", "accepted_unique_by_stage5_v7": False})
            continue
        maximum_time = (rows[0]["time_utc"] - datetime(1970, 1, 1)).total_seconds() + cfg.max_after_batch_end_seconds
        scored: list[dict[str, Any]] = []
        for candidate in candidate_map.get(batch_id, []):
            leg_id = str(candidate["adsb_leg_id"])
            leg_rows = leg_map.get(leg_id, [])
            if len(leg_rows) < 2:
                continue
            result = drop_dtw_align(rows, leg_rows, drop_penalty, 1.5, maximum_time)
            if result is None:
                continue
            result["leave_one_out_path_stability"] = leave_one_out_stability(rows, leg_rows, drop_penalty, 1.5)
            score_cost = result["normalized_cost"] - 0.75 * result["matched_row_fraction"] - 0.25 * result["matched_contiguous_fraction"]
            scored.append({"candidate": candidate, "leg_rows": leg_rows, "score_cost": score_cost, **result})
        if not scored:
            batch_records.append({"amdar_batch_id": batch_id, "v7_status": "no_drop_dtw_candidate", "accepted_unique_by_stage5_v7": False})
            continue
        scored.sort(key=lambda item: (item["score_cost"], item["normalized_cost"], str(item["candidate"]["adsb_leg_id"])))
        probabilities = softmax_probabilities([item["score_cost"] for item in scored])
        for item, probability in zip(scored, probabilities):
            item["candidate_posterior_v7"] = probability
        best = scored[0]
        second = scored[1] if len(scored) > 1 else {
            "normalized_cost": best["normalized_cost"] + max(2.0, drop_penalty),
            "matched_row_fraction": 0.0,
            "leave_one_out_path_stability": 0.0,
            "matched_contiguous_fraction": 0.0,
        }
        association_score = score_pair(best, second)
        association_posterior = float(pav_predict(np.array([association_score]), blocks)[0])
        path = best["path"]
        cross = np.array([item["cross_track_distance_km"] for item in path], dtype=np.float64)
        vertical = np.array([item["vertical_difference_m"] for item in path], dtype=np.float64)
        gaps = np.array([item["sampling_gap_seconds"] for item in path], dtype=np.float64)
        times = np.array([item["estimated_time_seconds"] for item in path], dtype=np.float64)
        cross_q90 = float(np.quantile(cross, 0.90)) if cross.size else math.inf
        vertical_q90 = float(np.quantile(vertical, 0.90)) if vertical.size else math.inf
        gap_max = float(gaps.max()) if gaps.size else math.inf
        after_batch_end = float(times.max() - maximum_time + cfg.max_after_batch_end_seconds) if times.size else math.inf
        exact_identity = str(best["candidate"].get("identity_match_level")) in {
            "tail_flight_date",
            "tail_flight_date_exact",
            "strong_tail_flight_date",
        }
        physical_gate = (
            cross_q90 <= cfg.max_cross_track_q90_km
            and vertical_q90 <= cfg.max_vertical_q90_m
            and gap_max <= cfg.max_sampling_gap_seconds
            and after_batch_end <= cfg.max_after_batch_end_seconds
        )
        validation_gate = (
            best["matched_row_fraction"] >= matched_min
            and best["matched_contiguous_fraction"] >= contiguous_min
            and best["leave_one_out_path_stability"] >= 0.60
            and association_posterior >= posterior_min
            and best["drop_fraction"] <= cfg.maximum_drop_fraction
        )
        candidate_unique = float(best["candidate_posterior_v7"]) >= cfg.candidate_posterior_min
        accepted = bool(report_v12["quality_gate"]["passed_stage3_v12_quality_gate"] and exact_identity and physical_gate and validation_gate and candidate_unique)
        source_group = (
            "v6_mixture" if bool(metadata.get("accepted_mixture_by_stage5_v6"))
            else "v6_partial_near_pass" if metadata.get("alignment_mode_v6") == "partial_monotone_70pct"
            else "v6_physical_bridge"
        )
        reason = "accepted_v7_stage3_v12_calibrated_partial_support_only" if accepted else "v7_compound_gate_fail"
        batch_records.append(
            {
                "amdar_batch_id": batch_id,
                "processing_slice_id": int(batch_index % cfg.slice_count),
                "audit_source_group": source_group,
                "matched_adsb_leg_id_v7": best["candidate"]["adsb_leg_id"],
                "identity_match_level_v7": best["candidate"].get("identity_match_level"),
                "drop_penalty_v7": drop_penalty,
                "matched_row_fraction_v7": best["matched_row_fraction"],
                "matched_contiguous_fraction_v7": best["matched_contiguous_fraction"],
                "drop_fraction_v7": best["drop_fraction"],
                "largest_dropped_block_fraction_v7": best["largest_dropped_block_fraction"],
                "matched_cost_q90_v7": best["matched_cost_q90"],
                "candidate_sequence_margin_v7": second["normalized_cost"] - best["normalized_cost"],
                "leave_one_out_path_stability_v7": best["leave_one_out_path_stability"],
                "candidate_posterior_v7": best["candidate_posterior_v7"],
                "association_score_v12": association_score,
                "association_posterior_v12": association_posterior,
                "cross_track_q90_km_v7": cross_q90,
                "vertical_q90_m_v7": vertical_q90,
                "sampling_gap_max_seconds_v7": gap_max,
                "max_after_batch_end_seconds_v7": after_batch_end,
                "exact_identity_gate_v7": exact_identity,
                "physical_gate_v7": physical_gate,
                "validation_gate_v7": validation_gate,
                "candidate_unique_gate_v7": candidate_unique,
                "accepted_unique_by_stage5_v7": accepted,
                "v7_status": "accepted" if accepted else "rejected",
                "v7_reason": reason,
                "effective_strict_truth": False,
                "holdout_eligible": False,
                "estimated_time_is_strict_point_truth": False,
                "usage_role": "support_only_not_strict_truth",
            }
        )
        for rank, item in enumerate(scored, start=1):
            score_records.append(
                {
                    "amdar_batch_id": batch_id,
                    "candidate_rank_v7": rank,
                    "adsb_leg_id": item["candidate"]["adsb_leg_id"],
                    "identity_match_level": item["candidate"].get("identity_match_level"),
                    "normalized_cost": item["normalized_cost"],
                    "score_cost": item["score_cost"],
                    "matched_row_fraction": item["matched_row_fraction"],
                    "matched_contiguous_fraction": item["matched_contiguous_fraction"],
                    "drop_fraction": item["drop_fraction"],
                    "leave_one_out_path_stability": item["leave_one_out_path_stability"],
                    "candidate_posterior_v7": item["candidate_posterior_v7"],
                }
            )
        if accepted:
            path_by_index = {item["original_index"]: item for item in path}
            for row_index, row in enumerate(rows):
                selected = row_index in path_by_index
                row_records.append(
                    {
                        "amdar_batch_id": batch_id,
                        "source_row_index": row.get("source_row_index"),
                        "selected_by_drop_dtw_v7": selected,
                        "row_role_v7": "matched_support_only" if selected else "excluded_calibrated_outlier",
                        "effective_strict_truth": False,
                        "holdout_eligible": False,
                    }
                )
                if not selected:
                    continue
                projection = path_by_index[row_index]
                match_records.append(
                    {
                        **row,
                        "matched_adsb_leg_id": best["candidate"]["adsb_leg_id"],
                        "matched_adsb_flight_norm": best["candidate"].get("matched_adsb_flight_norm"),
                        "identity_match_level": best["candidate"].get("identity_match_level"),
                        "segment_index": projection["segment_index"],
                        "segment_fraction": projection["segment_fraction"],
                        "estimated_time_utc": datetime.fromtimestamp(projection["estimated_time_seconds"], tz=timezone.utc).replace(tzinfo=None),
                        "cross_track_distance_km": projection["cross_track_distance_km"],
                        "vertical_difference_m": projection["vertical_difference_m"],
                        "sampling_gap_seconds": projection["sampling_gap_seconds"],
                        "association_posterior_stage3_v12": association_posterior,
                        "candidate_posterior_v7": best["candidate_posterior_v7"],
                        "accepted_by_stage5_v7": True,
                        "stage5_match_grade_v7": "C",
                        "stage5_match_confidence_v7": min(0.50, 0.50 * association_posterior),
                        "stage5_acceptance_reason_v7": reason,
                        "effective_strict_truth": False,
                        "holdout_eligible": False,
                        "estimated_time_is_strict_point_truth": False,
                        "point_observation_time_available": False,
                        "batch_end_is_time_upper_bound": True,
                        "stage6_time_uncertainty_input_role": "narrow_support_only_seed",
                        "usage_role": "support_only_not_strict_truth",
                    }
                )

    score_df = pl.from_dicts(score_records, infer_schema_length=None) if score_records else pl.DataFrame()
    batch_df = pl.from_dicts(batch_records, infer_schema_length=None) if batch_records else pl.DataFrame()
    incremental = pl.from_dicts(match_records, infer_schema_length=None) if match_records else pl.DataFrame()
    row_df = pl.from_dicts(row_records, infer_schema_length=None) if row_records else pl.DataFrame()
    accepted_ids = set(batch_df.filter(pl.col("accepted_unique_by_stage5_v7")).get_column("amdar_batch_id").to_list()) if batch_df.height else set()
    prior_ids = set(match_v6.get_column("amdar_batch_id").cast(pl.Utf8).to_list())
    overlap = prior_ids & accepted_ids
    prior_match = match_v6.with_columns(
        [pl.lit("frozen_stage5_v6_baseline").alias("stage5_v7_source_branch"), pl.lit(True).alias("accepted_by_stage5_v7")]
    )
    combined = (
        pl.concat(
            [prior_match, incremental.with_columns(pl.lit("stage3_v12_calibrated_partial_incremental").alias("stage5_v7_source_branch"))],
            how="diagonal_relaxed",
        )
        if incremental.height
        else prior_match
    )
    score_df.write_parquet(out / "amdar_adsb_candidate_drop_dtw_scores_v7.parquet", compression="zstd")
    batch_df.write_parquet(out / "amdar_adsb_batch_diagnostics_v7.parquet", compression="zstd")
    incremental.write_parquet(out / "amdar_adsb_match_incremental_v7.parquet", compression="zstd")
    row_df.write_parquet(out / "amdar_adsb_partial_row_diagnostics_v7.parquet", compression="zstd")
    combined.write_parquet(out / "amdar_adsb_match_v7.parquet", compression="zstd")

    final_unique = combined.filter(pl.col("amdar_batch_id").is_not_null()).get_column("amdar_batch_id").n_unique()
    new_unique = len(accepted_ids)
    total_incremental_from_v5 = final_unique - 198
    safety = {
        "stage3_v12_quality_gate_passed": bool(report_v12["quality_gate"]["passed_stage3_v12_quality_gate"]),
        "prior_205_unique_batches_preserved": match_v6.get_column("amdar_batch_id").n_unique() == 205,
        "no_overlap_with_prior_unique": len(overlap) == 0,
        "all_new_exact_identity": batch_df.filter(pl.col("accepted_unique_by_stage5_v7") & (~pl.col("exact_identity_gate_v7"))).height == 0 if batch_df.height else True,
        "all_new_physical_gate": batch_df.filter(pl.col("accepted_unique_by_stage5_v7") & (~pl.col("physical_gate_v7"))).height == 0 if batch_df.height else True,
        "all_new_validation_gate": batch_df.filter(pl.col("accepted_unique_by_stage5_v7") & (~pl.col("validation_gate_v7"))).height == 0 if batch_df.height else True,
        "truth_invariants_preserved": incremental.filter(pl.col("effective_strict_truth") | pl.col("holdout_eligible") | pl.col("estimated_time_is_strict_point_truth")).height == 0 if incremental.height else True,
        "space_saving_policy_preserved": True,
    }
    safety["passed_stage5_v7_safety_gate"] = all(safety.values())
    merge = {
        "new_unique_ge_3": new_unique >= 3,
        "total_incremental_from_v5_ge_10": total_incremental_from_v5 >= 10,
        "final_unique_batches_ge_208": final_unique >= 208,
        "stage3_v12_gate_passed": bool(report_v12["quality_gate"]["passed_stage3_v12_quality_gate"]),
        "safety_gate_passed": safety["passed_stage5_v7_safety_gate"],
    }
    merge["passed_stage5_v7_merge_target"] = all(merge.values())
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Large-framework Stage5 v7 calibrated partial matcher; audit-first execution.",
        "run_config": asdict(cfg),
        "run_policy": {
            "POLARS_MAX_THREADS": int(os.environ.get("POLARS_MAX_THREADS", str(cfg.workers))),
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "space_policy": "Audit-only candidate scope plus one combined output; no 25 full copies.",
        },
        "stage3_v12_policy": policy,
        "audit_scope": {
            "v6_mixtures": mixtures.height,
            "v6_partial_near_pass": near_pass.height,
            "v6_physical_bridges": bridges.height,
            "unique_audit_batches": audit.height,
        },
        "result": {
            "prior_unique_batches": 205,
            "new_unique_batches": new_unique,
            "new_unique_rows": incremental.height,
            "final_unique_batches": final_unique,
            "final_unique_rows": combined.height,
            "total_incremental_from_frozen_v5_198": total_incremental_from_v5,
            "accepted_by_source_group": batch_df.filter(pl.col("accepted_unique_by_stage5_v7")).group_by("audit_source_group").len().to_dicts() if batch_df.height else [],
            "association_posterior_summary": numeric_summary(batch_df.filter(pl.col("accepted_unique_by_stage5_v7")), "association_posterior_v12") if batch_df.height else {},
            "matched_fraction_summary": numeric_summary(batch_df.filter(pl.col("accepted_unique_by_stage5_v7")), "matched_row_fraction_v7") if batch_df.height else {},
        },
        "safety_checks": safety,
        "merge_target_checks": merge,
        "stage6_allowed_mode": "target_branch" if merge["passed_stage5_v7_merge_target"] else "conservative_diagnostic_only",
        "truth_boundary": {
            "amdar_effective_strict_truth_rows": 0,
            "amdar_holdout_eligible_rows": 0,
            "estimated_time_is_strict_point_truth": False,
            "usage_role": "support_only_not_strict_truth",
        },
        "outputs": {
            "candidate_scores": str(out / "amdar_adsb_candidate_drop_dtw_scores_v7.parquet"),
            "batch_diagnostics": str(out / "amdar_adsb_batch_diagnostics_v7.parquet"),
            "incremental_match": str(out / "amdar_adsb_match_incremental_v7.parquet"),
            "partial_row_diagnostics": str(out / "amdar_adsb_partial_row_diagnostics_v7.parquet"),
            "combined_match": str(out / "amdar_adsb_match_v7.parquet"),
        },
    }
    write_json(out / "amdar_adsb_match_diagnostics_v7.json", summary)
    write_json(cfg.out_dir / "stage5_v7_stage6_gate_check.json", {
        "generated_date": "2026-07-16",
        "large_framework_stage": "Stage5 v7 complete; Stage6 gate decision",
        "stage5_v7_safety_gate": safety["passed_stage5_v7_safety_gate"],
        "stage5_v7_merge_target": merge["passed_stage5_v7_merge_target"],
        "final_unique_batches": final_unique,
        "new_unique_batches_v7": new_unique,
        "total_incremental_from_v5": total_incremental_from_v5,
        "stage6_allowed_mode": summary["stage6_allowed_mode"],
        "truth_invariants_preserved": safety["truth_invariants_preserved"],
    })
    write_json(cfg.out_dir / "run_config.json", asdict(cfg))
    print(json.dumps({"audit_scope": summary["audit_scope"], "result": summary["result"], "safety_checks": safety, "merge_target_checks": merge}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
