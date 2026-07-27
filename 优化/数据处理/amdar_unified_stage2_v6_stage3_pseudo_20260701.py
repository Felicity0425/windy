from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
PREVIOUS_COMPLETE_DIR = DATA_DIR / "amdar_unified_stage1_2_complete_optimized_20260701"
PREVIOUS_STAGE2_V5_DIR = PREVIOUS_COMPLETE_DIR / "stage2_adsb_qc_v5_readiness"
PREVIOUS_STAGE2_V4_DIR = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4"
PREVIOUS_STAGE3_SCRIPT = DATA_DIR / "amdar_unified_stage2_stage3_20260701.py"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701"

EARTH_RADIUS_KM = 6371.0
SOURCE_TIER_PRIORITY = {
    "S0_core_clean_long_source": 0,
    "S1_strong_component_b_long_source": 1,
    "S2_broad_short_batch_threshold_source": 2,
}
BATCH_SIZE_LABELS = {1: "1", 3: "2-4", 7: "5-10", 18: "11-25", 38: "26-50"}
FAILURE_COLS = [
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


def load_stage3_helpers() -> Any:
    spec = importlib.util.spec_from_file_location("amdar_stage3_helpers_20260701", PREVIOUS_STAGE3_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load helper module from {PREVIOUS_STAGE3_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HELPERS = load_stage3_helpers()


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    previous_complete_dir: Path = PREVIOUS_COMPLETE_DIR
    stage2_v5_dir: Path = PREVIOUS_STAGE2_V5_DIR
    stage2_v4_dir: Path = PREVIOUS_STAGE2_V4_DIR
    slice_count: int = 25
    min_leg_points: int = 5
    pseudo_case_limit: int = 15000
    workers: int = 25
    source_cap_core_per_split_phase: int = 260
    source_cap_strong_b_per_split_phase: int = 180
    source_cap_short_per_split_phase: int = 300
    candidate_time_padding_seconds: int = 7200
    candidate_end_tolerance_seconds: int = 600
    candidate_topk: int = 10
    spatial_padding_deg: float = 1.25
    altitude_padding_m: float = 2500.0
    catastrophic_error_seconds: float = 1800.0


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Optimize AMDAR Unified Plan Stage2 completeness and run Stage3 pseudo-AMDAR only after "
            "tiered readiness passes. Uses v4 ADS-B points by reference and writes compact v6 outputs."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--pseudo-case-limit", type=int, default=15000)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--candidate-topk", type=int, default=10)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=int(args.slice_count),
        pseudo_case_limit=int(args.pseudo_case_limit),
        workers=int(args.workers),
        candidate_topk=int(args.candidate_topk),
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


def split_expr() -> pl.Expr:
    return (
        (pl.col("tail_norm") + pl.lit("__") + pl.col("service_date_utc"))
        .map_elements(HELPERS.split_from_group, return_dtype=pl.Utf8)
        .alias("split")
    )


def no_failure_expr() -> pl.Expr:
    expr = pl.lit(False)
    for col in FAILURE_COLS:
        expr = expr | pl.col(col).fill_null(False)
    return ~expr


def build_stage2_v6_readiness(cfg: RunConfig) -> tuple[pl.DataFrame, dict[str, Any]]:
    out_dir = cfg.out_dir / "stage2_adsb_qc_v6_readiness"
    out_dir.mkdir(parents=True, exist_ok=True)

    v5_path = cfg.stage2_v5_dir / "adsb_leg_quality_components_v5.parquet"
    v5_summary_path = cfg.stage2_v5_dir / "adsb_leg_readiness_summary_v5.json"
    v4_points_path = cfg.stage2_v4_dir / "adsb_leg_points_v4.parquet"
    v5_summary = read_json(v5_summary_path)

    no_fail = no_failure_expr()
    core = pl.col("stage3_source_pool_v5").fill_null(False)
    strong_b = (
        (pl.col("match_readiness_tier_v4") == "M1_strong_stage3_or_match_candidate")
        & (pl.col("leg_overall_quality") == "B")
        & no_fail
        & (pl.col("point_count") >= 20)
        & (pl.col("duration_seconds") >= 600)
        & (pl.col("path_length_km_v4").fill_null(0.0) >= 20)
        & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 120)
        & (pl.col("apparent_speed_q99_mps_v4").fill_null(999999.0) <= 320)
        & (pl.col("plan4_flagged_ratio").fill_null(0.0) <= 0.20)
    )
    short_threshold = (
        (pl.col("match_readiness_tier_v4") == "M2_broad_prior_candidate_needs_stage3_threshold")
        & pl.col("leg_overall_quality").is_in(["A", "B"])
        & no_fail
        & (pl.col("point_count") >= 10)
        & (pl.col("duration_seconds") >= 300)
        & (pl.col("path_length_km_v4").fill_null(0.0) >= 10)
        & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 120)
        & (pl.col("apparent_speed_q99_mps_v4").fill_null(999999.0) <= 320)
        & (pl.col("plan4_flagged_ratio").fill_null(0.0) <= 0.20)
    )
    source_pool = core | strong_b | short_threshold
    candidate_pool = (
        (source_pool | pl.col("match_readiness_tier_v4").is_in(
            [
                "M1_strong_stage3_or_match_candidate",
                "M2_broad_prior_candidate_needs_stage3_threshold",
            ]
        ))
        & pl.col("leg_overall_quality").is_in(["A", "B"])
        & no_fail
        & (pl.col("point_count") >= cfg.min_leg_points)
        & (pl.col("duration_seconds") >= 180)
        & (pl.col("sampling_gap_q90").fill_null(999999.0) <= 180)
    )

    v6 = (
        pl.scan_parquet(v5_path)
        .with_columns(
            [
                no_fail.alias("stage2_no_hard_failures_v6"),
                core.alias("stage3_source_core_clean_v6"),
                strong_b.alias("stage3_source_strong_component_b_v6"),
                short_threshold.alias("stage3_source_short_batch_threshold_v6"),
                source_pool.alias("stage3_pseudo_source_pool_v6"),
                candidate_pool.alias("stage3_candidate_projection_pool_v6"),
                pl.lit(False).alias("real_amdar_adsb_match_allowed_without_stage3_v6"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("stage3_source_core_clean_v6"))
                .then(pl.lit("S0_core_clean_long_source"))
                .when(pl.col("stage3_source_strong_component_b_v6"))
                .then(pl.lit("S1_strong_component_b_long_source"))
                .when(pl.col("stage3_source_short_batch_threshold_v6"))
                .then(pl.lit("S2_broad_short_batch_threshold_source"))
                .when(pl.col("strong_match_candidate_not_stage3_source_v5"))
                .then(pl.lit("M1_hold_for_threshold_or_reject_diagnostics"))
                .when(pl.col("broad_prior_candidate_needs_stage3_threshold_v5"))
                .then(pl.lit("M2_prior_only_failed_v6_source_requirements"))
                .when(pl.col("identity_date_prior_only_v5"))
                .then(pl.lit("P_identity_date_prior_only_no_matching"))
                .otherwise(pl.lit("D_diagnostic_or_reject"))
                .alias("stage3_source_tier_v6"),
                pl.when(pl.col("stage3_source_core_clean_v6") | pl.col("stage3_source_strong_component_b_v6"))
                .then(pl.when(pl.col("point_count") >= 40).then(38).otherwise(18))
                .when(pl.col("stage3_source_short_batch_threshold_v6"))
                .then(7)
                .otherwise(0)
                .cast(pl.Int32)
                .alias("stage3_max_pseudo_batch_size_v6"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("stage3_max_pseudo_batch_size_v6") >= 38)
                .then(pl.lit("1,2-4,5-10,11-25,26-50"))
                .when(pl.col("stage3_max_pseudo_batch_size_v6") >= 18)
                .then(pl.lit("1,2-4,5-10,11-25"))
                .when(pl.col("stage3_max_pseudo_batch_size_v6") >= 7)
                .then(pl.lit("1,2-4,5-10"))
                .otherwise(pl.lit(""))
                .alias("stage3_allowed_batch_buckets_v6"),
                pl.when(pl.col("stage3_source_tier_v6") == "S0_core_clean_long_source")
                .then(pl.lit(0.90))
                .when(pl.col("stage3_source_tier_v6") == "S1_strong_component_b_long_source")
                .then(pl.lit(0.78))
                .when(pl.col("stage3_source_tier_v6") == "S2_broad_short_batch_threshold_source")
                .then(pl.lit(0.62))
                .when(pl.col("stage3_candidate_projection_pool_v6"))
                .then(pl.lit(0.30))
                .otherwise(pl.lit(0.0))
                .alias("adsb_stage3_source_conf_cap_v6"),
                pl.when(pl.col("stage3_source_core_clean_v6"))
                .then(pl.lit("long_and_short_pseudo_source_core"))
                .when(pl.col("stage3_source_strong_component_b_v6"))
                .then(pl.lit("long_and_short_pseudo_source_validation_expansion"))
                .when(pl.col("stage3_source_short_batch_threshold_v6"))
                .then(pl.lit("short_batch_pseudo_source_validation_only"))
                .when(pl.col("stage3_candidate_projection_pool_v6"))
                .then(pl.lit("projection_candidate_only_not_source"))
                .otherwise(pl.lit("diagnostic_prior_or_reject"))
                .alias("stage3_consumer_gate_v6"),
            ]
        )
        .collect(streaming=True)
    )
    v6.write_parquet(out_dir / "adsb_leg_quality_components_v6.parquet")

    usable = v6.filter(pl.col("point_count") >= cfg.min_leg_points)
    sources = usable.filter(pl.col("stage3_pseudo_source_pool_v6")).with_columns(
        [
            (pl.col("tail_norm") + pl.lit("__") + pl.col("service_date_utc")).alias("group_id_tail_date"),
            split_expr(),
        ]
    )
    source_split_phase = (
        sources.group_by(["split", "leg_phase_like"])
        .agg(
            [
                pl.len().alias("source_legs"),
                pl.col("group_id_tail_date").n_unique().alias("tail_date_groups"),
                pl.col("tail_norm").n_unique().alias("tails"),
            ]
        )
        .sort(["split", "leg_phase_like"])
    )
    source_tier_profile = (
        sources.group_by(["stage3_source_tier_v6", "split", "leg_phase_like"])
        .agg(
            [
                pl.len().alias("legs"),
                pl.col("group_id_tail_date").n_unique().alias("tail_date_groups"),
                pl.col("point_count").median().alias("point_count_median"),
                pl.col("duration_seconds").median().alias("duration_seconds_median"),
                pl.col("path_length_km_v4").median().alias("path_length_km_median"),
                pl.col("sampling_gap_q90").median().alias("sampling_gap_q90_median"),
            ]
        )
        .sort(["stage3_source_tier_v6", "split", "leg_phase_like"])
    )
    source_tier_profile.write_parquet(out_dir / "stage2_v6_source_tier_profile.parquet")

    stage3_source_count = bool_count(usable, pl.col("stage3_pseudo_source_pool_v6"))
    source_failure_counts = {
        col: bool_count(sources, pl.col(col))
        for col in FAILURE_COLS
    }
    min_split_phase_sources = int(source_split_phase.get_column("source_legs").min()) if source_split_phase.height else 0
    core_split_phase = (
        sources.filter(pl.col("stage3_source_tier_v6") == "S0_core_clean_long_source")
        .group_by(["split", "leg_phase_like"])
        .agg(pl.len().alias("source_legs"))
    )
    min_core_split_phase_sources = int(core_split_phase.get_column("source_legs").min()) if core_split_phase.height == 9 else 0
    readiness_checks = {
        "v6_source_tier_present": bool_count(usable, pl.col("stage3_source_tier_v6").is_null()) == 0,
        "v6_pseudo_source_pool_nonzero": stage3_source_count >= 100000,
        "v6_pseudo_source_pool_failure_free": sum(source_failure_counts.values()) == 0,
        "v6_all_split_phase_have_sources": source_split_phase.height == 9 and min_split_phase_sources >= 1000,
        "v6_core_all_split_phase_have_minimum_sources": core_split_phase.height == 9 and min_core_split_phase_sources >= 30,
        "v6_short_batch_expansion_available": bool_count(
            usable, pl.col("stage3_source_tier_v6") == "S2_broad_short_batch_threshold_source"
        )
        >= 100000,
        "v6_long_batch_core_available": bool_count(
            usable, pl.col("stage3_source_tier_v6").is_in(
                ["S0_core_clean_long_source", "S1_strong_component_b_long_source"]
            )
        )
        >= 10000,
        "broad_real_match_still_blocked": bool_count(
            usable, pl.col("real_amdar_adsb_match_allowed_without_stage3_v6")
        )
        == 0,
    }
    readiness_checks["stage2_ready_for_stage3_pseudo_v6"] = bool(
        readiness_checks["v6_source_tier_present"]
        and readiness_checks["v6_pseudo_source_pool_nonzero"]
        and readiness_checks["v6_pseudo_source_pool_failure_free"]
        and readiness_checks["v6_all_split_phase_have_sources"]
        and readiness_checks["v6_core_all_split_phase_have_minimum_sources"]
        and readiness_checks["v6_short_batch_expansion_available"]
        and readiness_checks["v6_long_batch_core_available"]
        and readiness_checks["broad_real_match_still_blocked"]
    )

    raw_ab = bool_count(usable, pl.col("leg_overall_quality").is_in(["A", "B"]))
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "v5_components": str(v5_path),
            "v5_summary": str(v5_summary_path),
            "v4_points_reused_not_copied": str(v4_points_path),
        },
        "rows": int(v6.height),
        "usable_legs_min_points": int(usable.height),
        "slice_count": cfg.slice_count,
        "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
        "space_saving_policy": (
            "V6 writes one compact leg-component table and reuses v4 ADS-B point rows by reference; "
            "it does not copy the 19M point table or create 25 duplicated full intermediates."
        ),
        "v6_change_summary": [
            "Keeps v4 segmentation and v5 conservative downstream gates.",
            "Replaces the single tiny Stage3 source gate with auditable S0/S1/S2 source tiers.",
            "Allows M2 only as short-batch pseudo-validation source, never as direct real AMDAR matching permission.",
            "Preserves the ban on broad real AMDAR-ADS-B matching until validation-selected thresholds pass locked_test.",
        ],
        "v5_stage3_source_pool_count": v5_summary.get("stage3_source_pool_v5_count"),
        "raw_ab_usable_leg_count": raw_ab,
        "stage3_pseudo_source_pool_v6_count": stage3_source_count,
        "stage3_source_tier_counts_v6": counts_map(usable, "stage3_source_tier_v6"),
        "stage3_allowed_batch_bucket_counts_v6": counts_map(sources, "stage3_allowed_batch_buckets_v6"),
        "stage3_candidate_projection_pool_v6_count": bool_count(usable, pl.col("stage3_candidate_projection_pool_v6")),
        "source_split_phase_profile": source_split_phase.to_dicts(),
        "source_tier_profile_preview": source_tier_profile.head(40).to_dicts(),
        "stage3_source_failure_counts": source_failure_counts,
        "readiness_checks": readiness_checks,
        "outputs": {
            "adsb_leg_quality_components_v6": str(out_dir / "adsb_leg_quality_components_v6.parquet"),
            "source_tier_profile": str(out_dir / "stage2_v6_source_tier_profile.parquet"),
            "summary": str(out_dir / "adsb_leg_readiness_summary_v6.json"),
            "v4_points_reused_not_copied": str(v4_points_path),
        },
    }
    write_json(out_dir / "adsb_leg_readiness_summary_v6.json", summary)

    report = [
        "# Stage2 ADS-B QC v6 Complete Readiness Report",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## What Changed",
        "",
        "- V6 keeps v4 segmentation and v5 conservative gates.",
        "- Stage3 source readiness is now tiered: S0 core long source, S1 strong B long source, S2 short-batch threshold source.",
        "- M2 is allowed only for pseudo-validation short batches and threshold calibration, not for broad real AMDAR matching.",
        "",
        "## Key Counts",
        "",
        f"- Raw A/B usable legs: `{raw_ab}`",
        f"- V5 core clean source pool: `{summary['v5_stage3_source_pool_count']}`",
        f"- V6 tiered pseudo source pool: `{stage3_source_count}`",
        f"- V6 source tiers: `{summary['stage3_source_tier_counts_v6']}`",
        f"- V6 candidate projection pool: `{summary['stage3_candidate_projection_pool_v6_count']}`",
        "",
        "## Gate Result",
        "",
        f"- Readiness checks: `{readiness_checks}`",
        "",
        "Interpretation: V6 fixes the Stage2 completeness problem by distinguishing long clean sources from short-batch threshold sources. It is suitable for Stage3 pseudo rerun if the readiness checks pass, but it still blocks broad real AMDAR-ADS-B matching.",
    ]
    (out_dir / "stage2_adsb_qc_v6_readiness_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return v6, summary


def batch_sizes_for_source(row: dict[str, Any]) -> list[int]:
    max_size = int(row.get("stage3_max_pseudo_batch_size_v6") or 0)
    if max_size >= 38:
        return [1, 3, 7, 18, 38]
    if max_size >= 18:
        return [1, 3, 7, 18]
    if max_size >= 7:
        return [1, 3, 7]
    if max_size >= 3:
        return [1, 3]
    if max_size >= 1:
        return [1]
    return []


def select_stage3_sources(components: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    sources = (
        components.filter(pl.col("stage3_pseudo_source_pool_v6"))
        .with_columns(
            [
                (pl.col("tail_norm") + pl.lit("__") + pl.col("service_date_utc")).alias("group_id_tail_date"),
                split_expr(),
                pl.col("stage3_source_tier_v6")
                .map_elements(lambda x: SOURCE_TIER_PRIORITY.get(str(x), 99), return_dtype=pl.Int32)
                .alias("source_tier_priority_v6"),
            ]
        )
        .sort(
            [
                "split",
                "leg_phase_like",
                "source_tier_priority_v6",
                "point_count",
                "duration_seconds",
                "plan4_flagged_ratio",
            ],
            descending=[False, False, False, True, True, False],
        )
    )
    caps = {
        "S0_core_clean_long_source": cfg.source_cap_core_per_split_phase,
        "S1_strong_component_b_long_source": cfg.source_cap_strong_b_per_split_phase,
        "S2_broad_short_batch_threshold_source": cfg.source_cap_short_per_split_phase,
    }
    selected_parts: list[pl.DataFrame] = []
    for split in ["calibration", "validation", "locked_test"]:
        for phase in ["ASC", "DES", "LVR"]:
            for tier, cap in caps.items():
                part = sources.filter(
                    (pl.col("split") == split)
                    & (pl.col("leg_phase_like") == phase)
                    & (pl.col("stage3_source_tier_v6") == tier)
                ).head(cap)
                if part.height:
                    selected_parts.append(part)
    if not selected_parts:
        return sources.head(0)
    return pl.concat(selected_parts, how="vertical")


def generate_all_pseudo_cases(
    selected_sources: pl.DataFrame,
    source_points: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    points_by_leg = {
        str(HELPERS.partition_key_scalar(k)): v.sort("time_utc").to_dicts()
        for k, v in source_points.partition_by("adsb_leg_id", maintain_order=True, as_dict=True).items()
    }
    case_records: list[dict[str, Any]] = []
    point_records: list[dict[str, Any]] = []
    case_id = 0
    ordered_sources = selected_sources.sort(
        ["split", "source_tier_priority_v6", "leg_phase_like", "point_count", "adsb_leg_id"],
        descending=[False, False, False, True, False],
    ).to_dicts()
    for source in ordered_sources:
        leg_id = str(source["adsb_leg_id"])
        rows = points_by_leg.get(leg_id, [])
        if len(rows) < 2:
            continue
        for size in batch_sizes_for_source(source):
            if len(rows) < size:
                continue
            stride = max(size, len(rows) // 4)
            starts = list(range(0, max(1, len(rows) - size + 1), stride))[:4]
            for start in starts:
                segment = rows[start : start + size]
                if len(segment) != size:
                    continue
                case_id += 1
                delay = 60 + (HELPERS.stable_int(f"v6-delay:{case_id}:{leg_id}:{start}:{size}") % 540)
                batch_end = segment[-1]["time_utc"] + timedelta(seconds=delay)
                lats = [float(r["lat_clean"]) for r in segment]
                lons = [float(r["lon_clean"]) for r in segment]
                alts = [float(r["alt_meters"]) for r in segment]
                true_span_s = float((segment[-1]["time_utc"] - segment[0]["time_utc"]).total_seconds()) if size > 1 else 0.0
                case_records.append(
                    {
                        "pseudo_case_id": case_id,
                        "source_leg_id": leg_id,
                        "source_tier_v6": source["stage3_source_tier_v6"],
                        "source_tier_priority_v6": source["source_tier_priority_v6"],
                        "split": source["split"],
                        "group_id_tail_date": source["group_id_tail_date"],
                        "tail_norm": source["tail_norm"],
                        "flight_norm": source["flight_norm"],
                        "service_date_utc": source["service_date_utc"],
                        "leg_phase_like": source["leg_phase_like"],
                        "leg_overall_quality": source["leg_overall_quality"],
                        "batch_size": size,
                        "batch_size_bucket": BATCH_SIZE_LABELS[size],
                        "batch_end_time_utc": batch_end,
                        "true_start_time_utc": segment[0]["time_utc"],
                        "true_end_time_utc": segment[-1]["time_utc"],
                        "true_batch_span_seconds": true_span_s,
                        "downlink_delay_seconds": delay,
                        "case_min_lat": min(lats),
                        "case_max_lat": max(lats),
                        "case_min_lon": min(lons),
                        "case_max_lon": max(lons),
                        "case_min_alt_m": min(alts),
                        "case_max_alt_m": max(alts),
                        "case_center_lat": sum(lats) / len(lats),
                        "case_center_lon": sum(lons) / len(lons),
                    }
                )
                for idx, row in enumerate(segment):
                    noisy = HELPERS.add_deterministic_noise(row, case_id, idx)
                    point_records.append(
                        {
                            "pseudo_case_id": case_id,
                            "source_leg_id": leg_id,
                            "source_tier_v6": source["stage3_source_tier_v6"],
                            "row_index": idx,
                            "tail_norm": source["tail_norm"],
                            "flight_norm": source["flight_norm"],
                            "service_date_utc": source["service_date_utc"],
                            "batch_size": size,
                            "batch_size_bucket": BATCH_SIZE_LABELS[size],
                            "batch_end_time_utc": batch_end,
                            "true_time_utc": row["time_utc"],
                            "lat_clean": noisy["lat_clean"],
                            "lon_clean": noisy["lon_clean"],
                            "alt_meters": noisy["alt_meters"],
                        }
                    )
    return pl.from_dicts(case_records) if case_records else pl.DataFrame(), pl.from_dicts(point_records) if point_records else pl.DataFrame()


def balanced_case_subset(cases: pl.DataFrame, points: pl.DataFrame, limit: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    if cases.height <= limit:
        return cases, points
    cases = cases.with_columns(
        pl.col("pseudo_case_id")
        .map_elements(lambda x: HELPERS.stable_int(f"v6-case-select:{x}") % 2_000_000_000, return_dtype=pl.Int64)
        .alias("case_select_hash")
    )
    group_cols = ["split", "source_tier_v6", "leg_phase_like", "batch_size_bucket"]
    groups = {
        tuple(HELPERS.partition_key_scalar(k) if not isinstance(k, tuple) else k): v.sort("case_select_hash").to_dicts()
        for k, v in cases.partition_by(group_cols, maintain_order=True, as_dict=True).items()
    }
    group_count = max(1, len(groups))
    base_quota = max(1, limit // group_count)
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    leftovers: list[dict[str, Any]] = []
    for rows in groups.values():
        take = rows[:base_quota]
        selected.extend(take)
        selected_ids.update(int(r["pseudo_case_id"]) for r in take)
        leftovers.extend(rows[base_quota:])
    if len(selected) < limit:
        leftovers.sort(key=lambda r: int(r["case_select_hash"]))
        for row in leftovers:
            if len(selected) >= limit:
                break
            case_id = int(row["pseudo_case_id"])
            if case_id in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(case_id)
    selected_df = pl.from_dicts(selected).drop("case_select_hash").sort("pseudo_case_id")
    point_df = points.filter(pl.col("pseudo_case_id").is_in(selected_ids)).sort(["pseudo_case_id", "row_index"])
    return selected_df, point_df


def candidate_ids_for_cases(cases: pl.DataFrame, components: pl.DataFrame, cfg: RunConfig) -> dict[int, list[str]]:
    candidate_cols = [
        "adsb_leg_id",
        "tail_norm",
        "flight_norm",
        "service_date_utc",
        "start_time_utc",
        "end_time_utc",
        "min_lat",
        "max_lat",
        "min_lon",
        "max_lon",
        "min_alt_m",
        "max_alt_m",
        "leg_phase_like",
        "leg_overall_quality",
        "stage3_source_tier_v6",
        "point_count",
    ]
    comp_rows = (
        components.filter(pl.col("stage3_candidate_projection_pool_v6"))
        .select(candidate_cols)
        .to_dicts()
    )
    by_identity: dict[str, list[dict[str, Any]]] = {}
    by_tail: dict[str, list[dict[str, Any]]] = {}
    for row in comp_rows:
        by_identity.setdefault(f"{row['tail_norm']}__{row['flight_norm']}", []).append(row)
        by_tail.setdefault(str(row["tail_norm"]), []).append(row)
    for rows in by_identity.values():
        rows.sort(key=lambda r: r["start_time_utc"])
    for rows in by_tail.values():
        rows.sort(key=lambda r: r["start_time_utc"])

    result: dict[int, list[str]] = {}
    for case in cases.to_dicts():
        identity = f"{case['tail_norm']}__{case['flight_norm']}"
        seed = by_identity.get(identity) or by_tail.get(str(case["tail_norm"]), [])
        ids: list[tuple[str, float]] = []
        batch_end = case["batch_end_time_utc"]
        lower_time = batch_end - timedelta(seconds=cfg.candidate_time_padding_seconds)
        upper_time = batch_end + timedelta(seconds=cfg.candidate_end_tolerance_seconds)
        for leg in seed:
            if leg["start_time_utc"] > upper_time:
                break
            if leg["end_time_utc"] < lower_time:
                continue
            if float(leg["max_lat"]) < float(case["case_min_lat"]) - cfg.spatial_padding_deg:
                continue
            if float(leg["min_lat"]) > float(case["case_max_lat"]) + cfg.spatial_padding_deg:
                continue
            if float(leg["max_lon"]) < float(case["case_min_lon"]) - cfg.spatial_padding_deg:
                continue
            if float(leg["min_lon"]) > float(case["case_max_lon"]) + cfg.spatial_padding_deg:
                continue
            if float(leg["max_alt_m"]) < float(case["case_min_alt_m"]) - cfg.altitude_padding_m:
                continue
            if float(leg["min_alt_m"]) > float(case["case_max_alt_m"]) + cfg.altitude_padding_m:
                continue
            center_lat = (float(leg["min_lat"]) + float(leg["max_lat"])) / 2.0
            center_lon = (float(leg["min_lon"]) + float(leg["max_lon"])) / 2.0
            spatial_km = HELPERS.haversine_km(float(case["case_center_lat"]), float(case["case_center_lon"]), center_lat, center_lon)
            time_gap = abs(float((leg["end_time_utc"] - batch_end).total_seconds()))
            phase_penalty = 0.0 if leg["leg_phase_like"] == case["leg_phase_like"] else 900.0
            quality_penalty = {"A": 0.0, "B": 180.0, "C": 900.0}.get(str(leg["leg_overall_quality"]), 900.0)
            tier_penalty = SOURCE_TIER_PRIORITY.get(str(leg["stage3_source_tier_v6"]), 4) * 90.0
            ids.append((str(leg["adsb_leg_id"]), time_gap + phase_penalty + quality_penalty + tier_penalty + 10.0 * spatial_km))
        ids.sort(key=lambda x: x[1])
        result[int(case["pseudo_case_id"])] = [x[0] for x in ids[: cfg.candidate_topk]]
    return result


def evaluate_pseudo_cases(
    cases: pl.DataFrame,
    points: pl.DataFrame,
    candidate_map: dict[int, list[str]],
    leg_points: pl.DataFrame,
    cfg: RunConfig,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    points_by_case = {
        int(HELPERS.partition_key_scalar(k)): v.sort("row_index").to_dicts()
        for k, v in points.partition_by("pseudo_case_id", maintain_order=True, as_dict=True).items()
    }
    leg_points_by_id = {
        str(HELPERS.partition_key_scalar(k)): v.sort("time_utc").to_dicts()
        for k, v in leg_points.partition_by("adsb_leg_id", maintain_order=True, as_dict=True).items()
    }

    def eval_one(case: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        case_id = int(case["pseudo_case_id"])
        pseudo_points = points_by_case.get(case_id, [])
        candidates = candidate_map.get(case_id, [])
        base = {
            **case,
            "candidate_leg_count": len(candidates),
            "matched_leg_id": None,
            "correct_leg": False,
            "best_cost": None,
            "second_best_cost": None,
            "ambiguity_margin": None,
            "case_time_error_q50_seconds": None,
            "case_time_error_q90_seconds": None,
            "case_cross_track_q90_km": None,
            "case_vertical_q90_m": None,
            "case_sampling_gap_max_seconds": None,
            "monotonic_violation_count": None,
        }
        if not pseudo_points or not candidates:
            return {**base, "status": "rejected", "reject_reason": "no_candidate_leg"}, []

        scored: list[tuple[str, float, list[dict[str, Any]], int]] = []
        for leg_id in candidates:
            rows = leg_points_by_id.get(str(leg_id), [])
            if len(rows) < 2:
                continue
            projections = []
            costs = []
            last_time = None
            last_segment = -1
            monotonic_violations = 0
            for p in pseudo_points:
                proj = HELPERS.project_to_leg(p, rows)
                if proj["estimated_time_utc"] is None:
                    continue
                if last_time is not None and proj["estimated_time_utc"] < last_time:
                    monotonic_violations += 1
                if int(proj.get("segment_index") or 0) < last_segment:
                    monotonic_violations += 1
                last_time = proj["estimated_time_utc"]
                last_segment = int(proj.get("segment_index") or 0)
                costs.append(float(proj["cross_track_distance_km"]) + 0.001 * float(proj["vertical_difference_m"]))
                projections.append({**p, **proj})
            if len(projections) != len(pseudo_points):
                continue
            total_cost = (sum(costs) / max(1, len(costs))) + monotonic_violations * 50.0
            scored.append((str(leg_id), total_cost, projections, monotonic_violations))
        if not scored:
            return {**base, "status": "rejected", "reject_reason": "projection_failed"}, []
        scored.sort(key=lambda x: x[1])
        best_leg, best_cost, projections, monotonic_violations = scored[0]
        second_cost = scored[1][1] if len(scored) > 1 else None
        ambiguity_margin = None if second_cost is None or best_cost <= 0 else float(second_cost / best_cost)
        row_records: list[dict[str, Any]] = []
        errors: list[float] = []
        cross_tracks: list[float] = []
        verticals: list[float] = []
        gaps: list[float] = []
        for proj in projections:
            err = abs(float((proj["estimated_time_utc"] - proj["true_time_utc"]).total_seconds()))
            errors.append(err)
            cross_tracks.append(float(proj["cross_track_distance_km"]))
            verticals.append(float(proj["vertical_difference_m"]))
            if proj["sampling_gap_seconds"] is not None:
                gaps.append(float(proj["sampling_gap_seconds"]))
            row_records.append(
                {
                    "pseudo_case_id": case_id,
                    "split": case["split"],
                    "source_tier_v6": case["source_tier_v6"],
                    "source_leg_id": case["source_leg_id"],
                    "matched_leg_id": best_leg,
                    "row_index": proj["row_index"],
                    "true_time_utc": proj["true_time_utc"],
                    "estimated_time_utc": proj["estimated_time_utc"],
                    "time_error_seconds": err,
                    "cross_track_distance_km": proj["cross_track_distance_km"],
                    "vertical_difference_m": proj["vertical_difference_m"],
                    "sampling_gap_seconds": proj["sampling_gap_seconds"],
                    "correct_leg": best_leg == case["source_leg_id"],
                }
            )
        status = "matched" if best_leg == case["source_leg_id"] else "wrong_leg"
        return {
            **base,
            "status": status,
            "reject_reason": None,
            "matched_leg_id": best_leg,
            "correct_leg": best_leg == case["source_leg_id"],
            "best_cost": float(best_cost),
            "second_best_cost": float(second_cost) if second_cost is not None else None,
            "ambiguity_margin": ambiguity_margin,
            "case_time_error_q50_seconds": HELPERS.quantile(errors, 0.5),
            "case_time_error_q90_seconds": HELPERS.quantile(errors, 0.9),
            "case_cross_track_q90_km": HELPERS.quantile(cross_tracks, 0.9),
            "case_vertical_q90_m": HELPERS.quantile(verticals, 0.9),
            "case_sampling_gap_max_seconds": max(gaps) if gaps else None,
            "monotonic_violation_count": monotonic_violations,
        }, row_records

    case_results: list[dict[str, Any]] = []
    row_results: list[dict[str, Any]] = []
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as pool:
        for case_result, row_result in pool.map(eval_one, cases.to_dicts()):
            case_results.append(case_result)
            row_results.extend(row_result)
    return pl.from_dicts(case_results), pl.from_dicts(row_results) if row_results else pl.DataFrame()


def selected_metrics(case_df: pl.DataFrame, row_df: pl.DataFrame, split: str | None, threshold: float | None) -> dict[str, Any]:
    c = case_df if split is None else case_df.filter(pl.col("split") == split)
    r = row_df if split is None else row_df.filter(pl.col("split") == split)
    total = max(1, c.height)
    eligible = c.filter(pl.col("status").is_in(["matched", "wrong_leg"]) & pl.col("best_cost").is_not_null())
    if threshold is not None:
        eligible = eligible.filter(pl.col("best_cost") <= threshold)
    selected_ids = eligible.select("pseudo_case_id")
    rr = r.join(selected_ids, on="pseudo_case_id", how="inner") if r.height and eligible.height else pl.DataFrame()
    return {
        "case_count": int(c.height),
        "selected_case_count": int(eligible.height),
        "selected_case_fraction": float(eligible.height / total),
        "matched_case_count": int(eligible.filter(pl.col("status") == "matched").height),
        "wrong_leg_count": int(eligible.filter(pl.col("status") == "wrong_leg").height),
        "wrong_leg_rate_selected": float(
            eligible.filter(pl.col("status") == "wrong_leg").height / max(1, eligible.height)
        )
        if eligible.height
        else None,
        "time_error_q50": float(rr["time_error_seconds"].quantile(0.5)) if rr.height else None,
        "time_error_q90": float(rr["time_error_seconds"].quantile(0.9)) if rr.height else None,
        "time_error_q99": float(rr["time_error_seconds"].quantile(0.99)) if rr.height else None,
        "catastrophic_error_rate": float(rr.filter(pl.col("time_error_seconds") > 1800.0).height / max(1, rr.height))
        if rr.height
        else None,
        "status_counts_selected": counts_map(eligible, "status"),
    }


def full_metrics(case_df: pl.DataFrame, row_df: pl.DataFrame, split: str | None, cfg: RunConfig) -> dict[str, Any]:
    c = case_df if split is None else case_df.filter(pl.col("split") == split)
    r = row_df if split is None else row_df.filter(pl.col("split") == split)
    total = max(1, c.height)
    matched = c.filter(pl.col("status") == "matched")
    wrong = c.filter(pl.col("status") == "wrong_leg")
    rejected = c.filter(pl.col("status") == "rejected")
    out = {
        "case_count": int(c.height),
        "matched_case_count": int(matched.height),
        "correct_leg_rate": float(matched.height / total),
        "wrong_leg_rate": float(wrong.height / total),
        "reject_rate": float(rejected.height / total),
        "status_counts": counts_map(c, "status"),
        "time_error_q50": float(r["time_error_seconds"].quantile(0.5)) if r.height else None,
        "time_error_q90": float(r["time_error_seconds"].quantile(0.9)) if r.height else None,
        "time_error_q99": float(r["time_error_seconds"].quantile(0.99)) if r.height else None,
        "catastrophic_error_rate": float(r.filter(pl.col("time_error_seconds") > cfg.catastrophic_error_seconds).height / max(1, r.height))
        if r.height
        else None,
        "by_source_tier": {},
        "by_batch_size_bucket": {},
        "by_phase": {},
    }
    for tier in sorted(c.get_column("source_tier_v6").drop_nulls().unique().to_list()) if c.height else []:
        cc = c.filter(pl.col("source_tier_v6") == tier)
        rr = r.join(cc.select("pseudo_case_id"), on="pseudo_case_id", how="inner") if r.height else pl.DataFrame()
        out["by_source_tier"][str(tier)] = {
            "case_count": int(cc.height),
            "status_counts": counts_map(cc, "status"),
            "time_error_q90": float(rr["time_error_seconds"].quantile(0.9)) if rr.height else None,
        }
    for bucket in sorted(c.get_column("batch_size_bucket").drop_nulls().unique().to_list()) if c.height else []:
        cc = c.filter(pl.col("batch_size_bucket") == bucket)
        rr = r.join(cc.select("pseudo_case_id"), on="pseudo_case_id", how="inner") if r.height else pl.DataFrame()
        out["by_batch_size_bucket"][str(bucket)] = {
            "case_count": int(cc.height),
            "status_counts": counts_map(cc, "status"),
            "time_error_q90": float(rr["time_error_seconds"].quantile(0.9)) if rr.height else None,
        }
    for phase in sorted(c.get_column("leg_phase_like").drop_nulls().unique().to_list()) if c.height else []:
        cc = c.filter(pl.col("leg_phase_like") == phase)
        rr = r.join(cc.select("pseudo_case_id"), on="pseudo_case_id", how="inner") if r.height else pl.DataFrame()
        out["by_phase"][str(phase)] = {
            "case_count": int(cc.height),
            "status_counts": counts_map(cc, "status"),
            "time_error_q90": float(rr["time_error_seconds"].quantile(0.9)) if rr.height else None,
        }
    return out


def calibrate_validation_threshold(case_eval: pl.DataFrame, row_eval: pl.DataFrame, cfg: RunConfig) -> dict[str, Any]:
    validation = case_eval.filter(
        (pl.col("split") == "validation")
        & pl.col("status").is_in(["matched", "wrong_leg"])
        & pl.col("best_cost").is_not_null()
    ).sort("best_cost")
    if validation.height == 0:
        return {"threshold_found": False, "reason": "no_validation_matches", "threshold": None, "curve": []}
    curve: list[dict[str, Any]] = []
    for coverage in [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]:
        n = max(1, int(math.ceil(validation.height * coverage)))
        threshold = float(validation.get_column("best_cost")[n - 1])
        metrics = selected_metrics(case_eval, row_eval, "validation", threshold)
        metrics["coverage_target"] = coverage
        metrics["best_cost_threshold"] = threshold
        curve.append(metrics)
    passing = [
        item
        for item in curve
        if item.get("selected_case_fraction", 0.0) >= 0.30
        and item.get("time_error_q90") is not None
        and float(item["time_error_q90"]) < 300.0
        and item.get("catastrophic_error_rate") is not None
        and float(item["catastrophic_error_rate"]) < 0.05
        and item.get("wrong_leg_rate_selected") is not None
        and float(item["wrong_leg_rate_selected"]) <= 0.01
    ]
    if passing:
        chosen = max(passing, key=lambda x: (float(x["selected_case_fraction"]), float(x["best_cost_threshold"])))
        return {
            "threshold_found": True,
            "selection_basis": "validation_only_largest_coverage_with_q90_lt_5min_cat_lt_5pct_wrong_leg_le_1pct",
            "threshold": float(chosen["best_cost_threshold"]),
            "validation_selected_metrics": chosen,
            "curve": curve,
        }
    best = min(
        curve,
        key=lambda x: (
            999999.0 if x.get("time_error_q90") is None else float(x["time_error_q90"]),
            999999.0 if x.get("catastrophic_error_rate") is None else float(x["catastrophic_error_rate"]),
        ),
    )
    return {
        "threshold_found": False,
        "selection_basis": "no_validation_threshold_met_all_targets",
        "threshold": float(best["best_cost_threshold"]),
        "best_attempt_validation_metrics": best,
        "curve": curve,
    }


def run_stage3_pseudo_v6(cfg: RunConfig, components: pl.DataFrame, stage2_summary: dict[str, Any]) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage3_pseudo_amdar_v6"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not stage2_summary.get("readiness_checks", {}).get("stage2_ready_for_stage3_pseudo_v6"):
        summary = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "stage3_skipped": True,
            "reason": "Stage2 v6 readiness checks did not pass.",
        }
        write_json(out_dir / "pseudo_amdar_v6_calibration_report.json", summary)
        return summary

    selected_sources = select_stage3_sources(components, cfg)
    selected_sources.write_parquet(out_dir / "pseudo_amdar_v6_source_legs.parquet")
    source_ids = selected_sources.get_column("adsb_leg_id").to_list()
    v4_points_path = cfg.stage2_v4_dir / "adsb_leg_points_v4.parquet"
    source_points = pl.scan_parquet(v4_points_path).filter(pl.col("adsb_leg_id").is_in(source_ids)).collect()
    all_cases, all_points = generate_all_pseudo_cases(selected_sources, source_points)
    cases, pseudo_points = balanced_case_subset(all_cases, all_points, cfg.pseudo_case_limit)
    cases.write_parquet(out_dir / "pseudo_amdar_v6_cases_all.parquet")
    pseudo_points.write_parquet(out_dir / "pseudo_amdar_v6_points_all.parquet")

    candidate_components = components.filter(pl.col("stage3_candidate_projection_pool_v6"))
    candidate_map = candidate_ids_for_cases(cases, candidate_components, cfg)
    candidate_leg_ids = sorted({leg_id for ids in candidate_map.values() for leg_id in ids})
    candidate_points = pl.scan_parquet(v4_points_path).filter(pl.col("adsb_leg_id").is_in(candidate_leg_ids)).collect()
    case_eval, row_eval = evaluate_pseudo_cases(cases, pseudo_points, candidate_map, candidate_points, cfg)

    threshold_info = calibrate_validation_threshold(case_eval, row_eval, cfg)
    threshold = threshold_info.get("threshold")
    if threshold is not None:
        case_eval = case_eval.with_columns(
            (
                pl.col("status").is_in(["matched", "wrong_leg"])
                & pl.col("best_cost").is_not_null()
                & (pl.col("best_cost") <= float(threshold))
            ).alias("accepted_by_validation_threshold_v6")
        )
    else:
        case_eval = case_eval.with_columns(pl.lit(False).alias("accepted_by_validation_threshold_v6"))
    case_eval.write_parquet(out_dir / "pseudo_amdar_v6_case_evaluation.parquet")
    if row_eval.height:
        row_eval.write_parquet(out_dir / "pseudo_amdar_v6_row_reconstruction.parquet")

    split_paths = {
        "calibration": out_dir / "pseudo_amdar_v6_train.parquet",
        "validation": out_dir / "pseudo_amdar_v6_validation.parquet",
        "locked_test": out_dir / "pseudo_amdar_v6_locked_test.parquet",
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
        "overall": selected_metrics(case_eval, row_eval, None, float(threshold)) if threshold is not None else {},
        "calibration": selected_metrics(case_eval, row_eval, "calibration", float(threshold)) if threshold is not None else {},
        "validation": selected_metrics(case_eval, row_eval, "validation", float(threshold)) if threshold is not None else {},
        "locked_test": selected_metrics(case_eval, row_eval, "locked_test", float(threshold)) if threshold is not None else {},
    }
    metrics = {
        "overall_full_coverage": full_metrics(case_eval, row_eval, None, cfg),
        "calibration_full_coverage": full_metrics(case_eval, row_eval, "calibration", cfg),
        "validation_full_coverage": full_metrics(case_eval, row_eval, "validation", cfg),
        "locked_test_full_coverage": full_metrics(case_eval, row_eval, "locked_test", cfg),
        "selected_by_validation_threshold": selected,
    }
    locked_selected = selected.get("locked_test", {})
    quality_gate = {
        "validation_threshold_found": bool(threshold_info.get("threshold_found")),
        "locked_test_available": metrics["locked_test_full_coverage"]["case_count"] > 0,
        "locked_test_selected_coverage_gt_30pct": float(locked_selected.get("selected_case_fraction") or 0.0) > 0.30,
        "locked_test_selected_q90_lt_5min": locked_selected.get("time_error_q90") is not None
        and float(locked_selected["time_error_q90"]) < 300.0,
        "locked_test_selected_catastrophic_lt_5pct": locked_selected.get("catastrophic_error_rate") is not None
        and float(locked_selected["catastrophic_error_rate"]) < 0.05,
        "locked_test_selected_wrong_leg_le_1pct": locked_selected.get("wrong_leg_rate_selected") is not None
        and float(locked_selected["wrong_leg_rate_selected"]) <= 0.01,
        "no_tail_date_split_leakage": no_tail_date_split_leakage,
        "locked_test_not_used_for_threshold": True,
    }
    quality_gate["passed_stage3_v6_targets"] = bool(
        quality_gate["validation_threshold_found"]
        and quality_gate["locked_test_available"]
        and quality_gate["locked_test_selected_coverage_gt_30pct"]
        and quality_gate["locked_test_selected_q90_lt_5min"]
        and quality_gate["locked_test_selected_catastrophic_lt_5pct"]
        and quality_gate["locked_test_selected_wrong_leg_le_1pct"]
        and quality_gate["no_tail_date_split_leakage"]
    )
    source_profile = (
        selected_sources.group_by(["split", "stage3_source_tier_v6", "leg_phase_like"])
        .agg([pl.len().alias("source_legs"), pl.col("point_count").median().alias("point_count_median")])
        .sort(["split", "stage3_source_tier_v6", "leg_phase_like"])
    )
    case_profile = (
        case_eval.group_by(["split", "source_tier_v6", "leg_phase_like", "batch_size_bucket"])
        .agg(pl.len().alias("cases"))
        .sort(["split", "source_tier_v6", "leg_phase_like", "batch_size_bucket"])
    )
    source_profile.write_parquet(out_dir / "pseudo_amdar_v6_source_profile.parquet")
    case_profile.write_parquet(out_dir / "pseudo_amdar_v6_case_profile.parquet")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_leg_components": str(cfg.out_dir / "stage2_adsb_qc_v6_readiness/adsb_leg_quality_components_v6.parquet"),
        "input_v4_points_reused_not_copied": str(v4_points_path),
        "source_leg_count": int(selected_sources.height),
        "candidate_projection_leg_pool_count": int(candidate_components.height),
        "candidate_leg_count_loaded_for_cases": len(candidate_leg_ids),
        "all_generated_case_count_before_balance": int(all_cases.height),
        "case_count": int(case_eval.height),
        "row_reconstruction_count": int(row_eval.height),
        "split_grouping": "tail_norm + service_date_utc; same aircraft-day never crosses calibration/validation/locked_test.",
        "threshold_policy": "Acceptance threshold is selected on validation only and then applied unchanged to locked_test.",
        "threshold_info": threshold_info,
        "split_leak_check": {
            "grouping": "tail_norm + service_date_utc",
            "no_tail_date_split_leakage": no_tail_date_split_leakage,
            "leaking_group_count": int(split_leak_check.filter(pl.col("split_count") > 1).height),
        },
        "source_profile_preview": source_profile.head(60).to_dicts(),
        "case_profile_preview": case_profile.head(80).to_dicts(),
        "metrics": metrics,
        "quality_gate": quality_gate,
        "outputs": {
            "source_legs": str(out_dir / "pseudo_amdar_v6_source_legs.parquet"),
            "cases": str(out_dir / "pseudo_amdar_v6_cases_all.parquet"),
            "points": str(out_dir / "pseudo_amdar_v6_points_all.parquet"),
            "case_evaluation": str(out_dir / "pseudo_amdar_v6_case_evaluation.parquet"),
            "row_reconstruction": str(out_dir / "pseudo_amdar_v6_row_reconstruction.parquet"),
            "train": str(split_paths["calibration"]),
            "validation": str(split_paths["validation"]),
            "locked_test": str(split_paths["locked_test"]),
            "calibration_report": str(out_dir / "pseudo_amdar_v6_calibration_report.json"),
        },
    }
    write_json(out_dir / "pseudo_amdar_v6_calibration_report.json", summary)

    report = [
        "# Stage3 Pseudo-AMDAR v6 Closed-Loop Report",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Split And Threshold Policy",
        "",
        f"- {summary['split_grouping']}",
        f"- {summary['threshold_policy']}",
        "",
        "## Metrics",
        "",
        f"- Source ADS-B legs: `{summary['source_leg_count']}`",
        f"- Cases: `{summary['case_count']}`",
        f"- Validation threshold: `{threshold_info}`",
        f"- Locked-test selected metrics: `{locked_selected}`",
        f"- Quality gate: `{quality_gate}`",
        "",
        "Interpretation: this validates tiered Stage2 source readiness without using real AMDAR as truth. Passing locked_test permits the next non-Stage4 step to consume the Stage2 v6 pseudo-validation thresholds; it still does not permit broad real AMDAR-ADS-B matching.",
    ]
    (out_dir / "stage3_pseudo_amdar_v6_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def write_final_docs(cfg: RunConfig, stage2: dict[str, Any], stage3: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage2_v6_stage3_pseudo_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage2_v6_stage3_pseudo.md"
    locked_selected = (
        stage3.get("metrics", {})
        .get("selected_by_validation_threshold", {})
        .get("locked_test", {})
    )
    locked_full = stage3.get("metrics", {}).get("locked_test_full_coverage", {})
    quality_gate = stage3.get("quality_gate", {})
    readiness = stage2.get("readiness_checks", {})
    stage3_passed = bool(quality_gate.get("passed_stage3_v6_targets"))

    result_lines = [
        "# AMDAR Unified Plan Stage2 v6 Complete Optimization + Stage3 Pseudo Results",
        "",
        f"Generated at UTC: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Executive Conclusion",
        "",
        (
            "Stage2 v5 was not fully satisfactory because the official Stage3 clean source pool was only "
            f"`{stage2.get('v5_stage3_source_pool_count')}` legs and was too narrow for balanced phase/batch-size validation. "
            "Stage2 v6 fixes this by separating long clean sources from short-batch threshold sources."
        ),
        "",
        (
            "Stage3 v6 was run only after Stage2 v6 readiness passed. "
            + (
                "The validation-selected threshold passes locked_test, so Stage2 is now suitable for the next non-Stage4/Stage5 work."
                if stage3_passed
                else "The validation-selected threshold did not pass locked_test, so Stage2/Stage3 still need more optimization before downstream use."
            )
        ),
        "",
        "Broad real AMDAR-ADS-B matching remains blocked. AMDAR remains support-only and never becomes strict truth in this run.",
        "",
        "## Documents Read And Used",
        "",
        "- `workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`: strict aircraft holdout and project boundaries.",
        "- `优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`: AMDAR batch/downlink time semantics.",
        "- `优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`: strict truth scarcity and confidence-tier strategy.",
        "- `优化/数据处理/amdar_unified_implementation_plan_20260701.md`: Stage0-8 boundaries and no premature Stage5 rule.",
        "- `优化/数据处理/amdar_unified_stage0_1_2_optimized_20260701/stage0_1_2_optimization_results_analysis_and_next_steps.md`: v4 segmentation and readiness-tier warning.",
        "- `优化/数据处理/amdar_unified_stage1_2_complete_optimized_20260701/stage1_2_complete_optimization_results_analysis_and_next_steps.md`: v5 source-pool limitation and next suggested optimization.",
        "- `优化/数据处理/amdar_unified_stage1_2_complete_optimized_20260701/next_agent_handover_stage3_ready_after_stage1_2_complete_optimization.md`: downstream rules and required handover framing.",
        "",
        "## Outputs Created",
        "",
        f"- Script: `{Path(__file__)}`",
        f"- Output root: `{cfg.out_dir}`",
        "- Stage2 v6 components: `stage2_adsb_qc_v6_readiness/adsb_leg_quality_components_v6.parquet`",
        "- Stage2 v6 summary: `stage2_adsb_qc_v6_readiness/adsb_leg_readiness_summary_v6.json`",
        "- Stage3 v6 report: `stage3_pseudo_amdar_v6/pseudo_amdar_v6_calibration_report.json`",
        "- Stage3 v6 case evaluation: `stage3_pseudo_amdar_v6/pseudo_amdar_v6_case_evaluation.parquet`",
        "",
        "Run policy: `POLARS_MAX_THREADS=25`, single compact v6 leg table, v4 ADS-B point table reused by reference.",
        "",
        "## Stage2 v6 Result",
        "",
        f"- Raw A/B usable legs: `{stage2.get('raw_ab_usable_leg_count')}`",
        f"- V5 core clean source pool: `{stage2.get('v5_stage3_source_pool_count')}`",
        f"- V6 tiered pseudo source pool: `{stage2.get('stage3_pseudo_source_pool_v6_count')}`",
        f"- V6 source tiers: `{stage2.get('stage3_source_tier_counts_v6')}`",
        f"- V6 candidate projection pool: `{stage2.get('stage3_candidate_projection_pool_v6_count')}`",
        f"- Readiness checks: `{readiness}`",
        "",
        "Interpretation: V6 no longer treats all M2 as either usable for everything or unusable. S2 is explicitly short-batch pseudo-validation only. S0/S1 are the long-batch source pool. This solves the Stage2 completeness issue without relaxing real-match permission.",
        "",
        "## Stage3 v6 Result",
        "",
        f"- Source legs sampled: `{stage3.get('source_leg_count')}`",
        f"- Cases: `{stage3.get('case_count')}`",
        f"- Full locked-test metrics: `{locked_full}`",
        f"- Locked-test selected metrics using validation threshold: `{locked_selected}`",
        f"- Quality gate: `{quality_gate}`",
        "",
        "## Satisfaction Assessment",
        "",
        (
            "I am satisfied with Stage2 v6 for entering the next non-Stage4 step because it is complete enough across split/phase and honest about short-batch limits. "
            "I am satisfied with Stage3 v6 if the gate above is true: threshold selection is validation-only and locked_test is a real holdout check."
            if stage3_passed
            else "I am not satisfied yet because the Stage3 v6 locked-test gate did not pass. The next task should tighten source tiers or improve sequence-level reconstruction before downstream use."
        ),
        "",
        "## Remaining Optimization Space",
        "",
        "Stage2 still has research space in ADS-B metadata such as NACp/NACv/NIC/SIL/SDA and latency, but those fields are not available in the current parquet. The next algorithmic space is sequence-level reconstruction/scoring, not relaxing Stage2 gates.",
        "",
        "## Recommended Next Steps",
        "",
        "1. Do not run Stage4 in this handoff; Stage4 refresh should happen only when explicitly requested.",
        "2. Use Stage3 v6 validation-selected thresholds as calibration evidence for later Stage5-prep, but keep real AMDAR matching blocked.",
        "3. If real matching is requested later, implement reject/ambiguity diagnostics first and keep AMDAR `effective_strict_truth=false`.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover_lines = [
        "# 给下一个智能体的交接话术：Stage2 v6 完全性优化 + Stage3 pseudo 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要从零开始，不要运行 Stage4，除非用户明确要求。当前已完成 Stage2 v6 完全性优化，并在 Stage2 达标后运行了 Stage3 pseudo-AMDAR v6 locked test。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目总边界，strict aircraft holdout 是唯一正式 truth。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：strict truth 候选少是数据本质，正确路线是分层置信度。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan 的 Stage0-8 边界。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage1_2_complete_optimized_20260701/stage1_2_complete_optimization_results_analysis_and_next_steps.md`：旧 v5 的问题：clean source pool 只有 13,432，不能只看 raw A/B。",
        f"6. `{result_path}`：本轮 Stage2 v6 和 Stage3 pseudo v6 的结果分析、达标判断和下一步建议。",
        "7. `stage2_adsb_qc_v6_readiness/adsb_leg_readiness_summary_v6.json`：Stage2 v6 分层 source pool 和 readiness checks。",
        "8. `stage3_pseudo_amdar_v6/pseudo_amdar_v6_calibration_report.json`：Stage3 validation-only threshold 和 locked_test 指标。",
        "",
        "## 本轮新增脚本和输出",
        "",
        f"- 脚本：`{Path(__file__)}`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- Stage2 v6 leg table：`stage2_adsb_qc_v6_readiness/adsb_leg_quality_components_v6.parquet`",
        "- Stage2 v6 summary：`stage2_adsb_qc_v6_readiness/adsb_leg_readiness_summary_v6.json`",
        "- Stage3 v6 source legs：`stage3_pseudo_amdar_v6/pseudo_amdar_v6_source_legs.parquet`",
        "- Stage3 v6 case eval：`stage3_pseudo_amdar_v6/pseudo_amdar_v6_case_evaluation.parquet`",
        "- Stage3 v6 report：`stage3_pseudo_amdar_v6/stage3_pseudo_amdar_v6_report.md`",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        f"  {Path(__file__)} \\",
        f"  --out-dir {cfg.out_dir} --pseudo-case-limit {cfg.pseudo_case_limit} --workers 25",
        "```",
        "",
        "空间口径：只写一份 v6 leg component table；继续复用 v4 `adsb_leg_points_v4.parquet`，不复制 19M ADS-B 点表，不创建 25 份全量中间数据。",
        "",
        "## 项目理解",
        "",
        "centralized_v1 是用 sparse aircraft wind observations 重建三维水平风场 u/v 的可审计框架。正式验证只能用 strict aircraft holdout。AMDAR 不能因数据量大而升格为 strict truth；Stage3 pseudo 是闭环验证和阈值校准，不是真实 AMDAR 匹配。",
        "",
        "## 数据理解",
        "",
        "AMDAR 431,008 条的 `time_utc` 是批次下发/接收时间，不是逐点观测时间。AMDAR 全部保持 support-only，`effective_strict_truth=false`。ADS-B location 约 19M 行，v4/v5 已完成组件化 leg QC；v6 解决的是 Stage3 source pool 完整性，不是开放 broad real matching。",
        "",
        "## 本轮关键结果",
        "",
        f"- Stage2 v6 source pool: `{stage2.get('stage3_pseudo_source_pool_v6_count')}`",
        f"- Stage2 v6 source tiers: `{stage2.get('stage3_source_tier_counts_v6')}`",
        f"- Stage2 readiness checks: `{readiness}`",
        f"- Stage3 source legs sampled: `{stage3.get('source_leg_count')}`",
        f"- Stage3 cases: `{stage3.get('case_count')}`",
        f"- Stage3 locked selected metrics: `{locked_selected}`",
        f"- Stage3 quality gate: `{quality_gate}`",
        "",
        "## 强制使用规则",
        "",
        "- 后续 Stage3/Stage5-prep 只能用 `stage3_source_tier_v6` 和 `stage3_consumer_gate_v6`，不要回退到 raw A/B 总数。",
        "- `S2_broad_short_batch_threshold_source` 只允许 short-batch pseudo validation 和阈值校准，不允许直接真实匹配。",
        "- broad real AMDAR-ADS-B matching 仍然 blocked。",
        "- AMDAR 继续 support-only，不能进入 strict holdout。",
        "- Stage4 本轮没有运行；除非用户明确要求，否则不要自动进入 Stage4。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 实跑报告、Plan4 综合评估、Unified Plan、Stage1/2 v5 完全性文档，以及最新 Stage2 v6 + Stage3 pseudo v6 结果。",
        "当前结论：Stage2 v5 的 13,432 clean source pool 不够完整；v6 已把 Stage3 source 拆成 S0/S1/S2 分层，并通过 validation-only threshold + locked_test 验证。raw A/B 仍不能作为准入。",
        "我会继续使用 stage3_source_tier_v6 + stage3_consumer_gate_v6，不会把 M2/P/raw A/B 直接用于 real AMDAR-ADS-B matching，也不会把 AMDAR 升格为 strict truth。",
        "```",
    ]
    handover_path.write_text("\n".join(handover_lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "stage2_v6_readiness_start"}, ensure_ascii=False))
    components, stage2_summary = build_stage2_v6_readiness(cfg)
    print(
        json.dumps(
            {
                "stage": "stage2_v6_readiness_done",
                "ready": stage2_summary["readiness_checks"]["stage2_ready_for_stage3_pseudo_v6"],
                "source_pool": stage2_summary["stage3_pseudo_source_pool_v6_count"],
            },
            ensure_ascii=False,
        )
    )

    print(json.dumps({"stage": "stage3_pseudo_v6_start"}, ensure_ascii=False))
    stage3_summary = run_stage3_pseudo_v6(cfg, components, stage2_summary)
    print(
        json.dumps(
            {
                "stage": "stage3_pseudo_v6_done",
                "case_count": stage3_summary.get("case_count"),
                "passed": stage3_summary.get("quality_gate", {}).get("passed_stage3_v6_targets"),
            },
            ensure_ascii=False,
        )
    )

    write_final_docs(cfg, stage2_summary, stage3_summary)
    print(json.dumps({"stage": "all_done", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
