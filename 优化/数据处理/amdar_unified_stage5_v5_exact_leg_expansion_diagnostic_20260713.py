from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE5_V4_SCRIPT = DATA_DIR / "amdar_unified_stage5_v4_matching_20260708.py"
STAGE5_V4_DIR = DATA_DIR / "stage5_v4_matching_optimized_20260708/stage5_v4"
STAGE2_V7_PATH = DATA_DIR / "stage2_adsb_qc_v7_optimized_20260706/adsb_leg_quality_components_v7.parquet"
DEFAULT_OUT_DIR = DATA_DIR / "stage5_v5_exact_leg_expansion_diagnostic_optimized_20260713"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    slice_count: int = 25
    workers: int = 25
    min_points: int = 2
    max_points: int = 4
    min_weighted_score: float = 0.75
    allow_point_count_only_hard_failure: bool = False
    source_tier: str = "SX_exact_identity_unvalidated_diagnostic"


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Score excluded exact-identity ADS-B legs as an unvalidated Stage5 diagnostic.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--min-points", type=int, default=2)
    parser.add_argument("--max-points", type=int, default=4)
    parser.add_argument("--min-weighted-score", type=float, default=0.75)
    parser.add_argument("--allow-point-count-only-hard-failure", action="store_true")
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=args.slice_count,
        workers=args.workers,
        min_points=args.min_points,
        max_points=args.max_points,
        min_weighted_score=args.min_weighted_score,
        allow_point_count_only_hard_failure=args.allow_point_count_only_hard_failure,
    )


def load_stage5_v4() -> Any:
    spec = importlib.util.spec_from_file_location("stage5_v4_for_v5_expansion_diagnostic", STAGE5_V4_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {STAGE5_V4_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def build_candidates(cfg: RunConfig, batch: pl.DataFrame) -> tuple[pl.DataFrame, int]:
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
    policy = (
        ~pl.col("stage3_candidate_projection_pool_v7").fill_null(False)
        & hard_failure_policy
        & (pl.col("point_count") >= cfg.min_points)
        & (pl.col("point_count") <= cfg.max_points)
        & (pl.col("stage2_v7_weighted_score") >= cfg.min_weighted_score)
    )
    legs = (
        pl.scan_parquet(STAGE2_V7_PATH)
        .filter(policy)
        .select(
            [
                "adsb_leg_id", "tail_norm", "flight_norm", "service_date_utc", "start_time_utc", "end_time_utc",
                "min_lat", "max_lat", "min_lon", "max_lon", "min_alt_m", "max_alt_m", "leg_phase_like",
                pl.lit("C").alias("leg_overall_quality"),
                pl.lit(cfg.source_tier).alias("stage3_source_tier_v7"),
                "point_count", "duration_seconds", "path_length_km_v4", "sampling_gap_q90", "sampling_gap_max",
                "stage2_v7_weighted_score",
                pl.lit("pseudo_validation_required").alias("stage3_consumer_gate_v7"),
                pl.lit(0.0).alias("adsb_stage3_source_conf_cap_v7"),
            ]
        )
        .collect(engine="streaming")
    )
    leg_lazy = legs.lazy().with_columns(
        [
            ((pl.col("min_lat") + pl.col("max_lat")) * 0.5).alias("leg_center_lat"),
            ((pl.col("min_lon") + pl.col("max_lon")) * 0.5).alias("leg_center_lon"),
            ((pl.col("min_alt_m") + pl.col("max_alt_m")) * 0.5).alias("leg_center_alt_m"),
        ]
    )
    joined = batch.lazy().join(leg_lazy, on=["tail_norm", "flight_norm", "service_date_utc"], how="inner")
    time_ok = (
        (pl.col("start_time_utc") <= pl.col("batch_end_time_utc") + pl.duration(seconds=1800))
        & (pl.col("end_time_utc") >= pl.col("batch_end_time_utc") - pl.duration(seconds=10800))
    )
    previous_ok = pl.col("previous_batch_end_time_utc").is_null() | (
        pl.col("end_time_utc") >= pl.col("previous_batch_end_time_utc") - pl.duration(seconds=10800)
    )
    bbox_ok = (
        (pl.col("max_lat") >= pl.col("lat_min") - 2.0)
        & (pl.col("min_lat") <= pl.col("lat_max") + 2.0)
        & (pl.col("max_lon") >= pl.col("lon_min") - 2.0)
        & (pl.col("min_lon") <= pl.col("lon_max") + 2.0)
    )
    altitude_ok = (
        (pl.col("max_alt_m") >= pl.col("alt_min") - 4000.0)
        & (pl.col("min_alt_m") <= pl.col("alt_max") + 4000.0)
    )
    phase_ok = ~(
        pl.col("flight_phase").is_in(["ASC", "DES"])
        & pl.col("leg_phase_like").is_in(["ASC", "DES"])
        & (pl.col("flight_phase") != pl.col("leg_phase_like"))
    )
    mean_lat = (pl.col("lat_mean") + pl.col("leg_center_lat")) * 0.5 * math.pi / 180.0
    spatial_km = (
        ((pl.col("lat_mean") - pl.col("leg_center_lat")) * 110.574) ** 2
        + (((pl.col("lon_mean") - pl.col("leg_center_lon")) * 111.320 * mean_lat.cos()) ** 2)
    ).sqrt()
    seed_score = (
        (pl.col("end_time_utc") - pl.col("batch_end_time_utc")).dt.total_seconds().abs()
        + 1260.0
        + 10.0 * spatial_km
    )
    candidate = (
        joined.filter(time_ok & previous_ok & bbox_ok & altitude_ok & phase_ok)
        .with_columns(
            [
                spatial_km.alias("candidate_center_distance_km"),
                (pl.col("alt_mean") - pl.col("leg_center_alt_m")).abs().alias("candidate_altitude_center_diff_m"),
                seed_score.alias("candidate_seed_score"),
                pl.lit("strong_tail_flight_date").alias("identity_match_level"),
            ]
        )
        .sort(["amdar_batch_id", "candidate_seed_score", "adsb_leg_id"])
        .with_columns(pl.col("candidate_seed_score").rank("ordinal").over("amdar_batch_id").cast(pl.Int32).alias("candidate_rank"))
        .select(
            [
                "amdar_batch_id", "tail_norm", "flight_norm", "service_date_utc", "batch_end_time_utc",
                "previous_batch_end_time_utc", "flight_phase", "batch_row_count", "batch_size_bucket",
                "stage4_confidence_tier_first", "stage4_confidence_grade_first", "stage4_confidence_subtier_first",
                "stage4_weighting_recommendation_v3_first", "stage1_qc_all_rows_blocked", "adsb_leg_id",
                pl.col("flight_norm").alias("matched_adsb_flight_norm"), "identity_match_level", "leg_phase_like",
                "leg_overall_quality", "stage3_source_tier_v7", "point_count", "duration_seconds", "path_length_km_v4",
                "sampling_gap_q90", "sampling_gap_max", "stage2_v7_weighted_score", "stage3_consumer_gate_v7",
                "adsb_stage3_source_conf_cap_v7", "candidate_center_distance_km", "candidate_altitude_center_diff_m",
                "candidate_seed_score", "candidate_rank",
            ]
        )
        .collect(engine="streaming")
    )
    return candidate, legs.height


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    stage5 = load_stage5_v4()
    all_batch = pl.read_parquet(STAGE5_V4_DIR / "amdar_batch_base_v4.parquet")
    no_candidate_ids = (
        pl.read_parquet(STAGE5_V4_DIR / "amdar_adsb_reject_v4.parquet")
        .filter(pl.col("reject_reason") == "no_candidate_leg")
        .select("amdar_batch_id")
    )
    batch = all_batch.join(no_candidate_ids, on="amdar_batch_id", how="semi")
    candidate, eligible_leg_count = build_candidates(cfg, batch)
    diagnostic_dir = cfg.out_dir / "unvalidated_scoring"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    v4_cfg = stage5.RunConfig(
        out_dir=cfg.out_dir,
        slice_count=cfg.slice_count,
        workers=cfg.workers,
        candidate_topk=10,
    )
    _, diagnostics, _, raw_summary = stage5.run_matching(v4_cfg, batch, candidate, diagnostic_dir)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Unvalidated Stage5 exact-leg expansion diagnostic only; no row is an official accepted match.",
        "run_config": asdict(cfg),
        "eligible_excluded_leg_count": eligible_leg_count,
        "prefilter_candidate_rows": candidate.height,
        "prefilter_candidate_batches": candidate.select(pl.col("amdar_batch_id").n_unique()).item() if candidate.height else 0,
        "geometry_gate_pass_like_batches_unvalidated": int(raw_summary.get("accepted_batches") or 0),
        "raw_v4_scoring_summary": raw_summary,
        "decision": "pseudo_validation_required_before_any_real_use",
    }
    write_json(cfg.out_dir / "exact_leg_expansion_diagnostic_summary.json", summary)
    write_json(cfg.out_dir / "run_config.json", asdict(cfg))
    (cfg.out_dir / "README.md").write_text(
        "# Stage5 V5 Exact-Leg Expansion Diagnostic\n\n"
        "This output is diagnostic only. Rows marked accepted by the reused v4 scorer are not official Stage5 accepted rows. "
        "They require a dedicated Stage3 pseudo-validation gate before any real use.\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
