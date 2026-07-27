#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE5_V4_DIR = DATA_DIR / "stage5_v4_matching_optimized_20260708/stage5_v4"
STAGE2_V7_DIR = DATA_DIR / "stage2_adsb_qc_v7_optimized_20260706"
STAGE4_V3_DIR = DATA_DIR / "stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3"
DEFAULT_OUT_DIR = DATA_DIR / "stage5_v5_alignment_audit_optimized_20260708"


@dataclass(frozen=True)
class AuditConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage5_v4_dir: Path = STAGE5_V4_DIR
    stage2_v7_dir: Path = STAGE2_V7_DIR
    stage4_v3_dir: Path = STAGE4_V3_DIR
    slice_count: int = 25
    candidate_time_padding_seconds: int = 10800
    candidate_end_tolerance_seconds: int = 1800
    previous_batch_padding_seconds: int = 10800
    spatial_padding_deg: float = 2.0
    altitude_padding_m: float = 4000.0


def parse_args() -> AuditConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run Stage5 V5 alignment audit. This is an audit only: it does not "
            "promote any AMDAR row to strict truth and does not accept weak "
            "identity candidates without pseudo validation."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    args = parser.parse_args()
    return AuditConfig(out_dir=Path(args.out_dir), slice_count=int(args.slice_count))


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
        "p25": float(finite.quantile(0.25)) if finite.len() else None,
        "q50": float(finite.quantile(0.50)) if finite.len() else None,
        "p75": float(finite.quantile(0.75)) if finite.len() else None,
        "p90": float(finite.quantile(0.90)) if finite.len() else None,
        "p99": float(finite.quantile(0.99)) if finite.len() else None,
        "max": float(finite.max()) if finite.len() else None,
    }


def load_inputs(cfg: AuditConfig) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    batch = pl.read_parquet(cfg.stage5_v4_dir / "amdar_batch_base_v4.parquet")
    reject = pl.read_parquet(cfg.stage5_v4_dir / "amdar_adsb_reject_v4.parquet")
    diagnostics = pl.read_parquet(cfg.stage5_v4_dir / "amdar_adsb_batch_diagnostics_v4.parquet")
    legs = (
        pl.scan_parquet(cfg.stage2_v7_dir / "adsb_leg_quality_components_v7.parquet")
        .filter(pl.col("stage3_candidate_projection_pool_v7").fill_null(False))
        .select(
            [
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
                pl.col("leg_overall_quality_v7").alias("leg_overall_quality"),
                "stage3_source_tier_v7",
                "point_count",
                "duration_seconds",
                "path_length_km_v4",
                "sampling_gap_q90",
                "sampling_gap_max",
                "stage2_v7_weighted_score",
            ]
        )
        .collect(streaming=True)
        .with_columns(
            [
                pl.col("flight_norm").cast(pl.Utf8, strict=False).fill_null("MISSING").str.replace_all(r"\D+", "").alias("flight_digits"),
                pl.col("flight_norm").cast(pl.Utf8, strict=False).fill_null("MISSING").str.replace_all(r"\d+", "").alias("flight_prefix"),
            ]
        )
    )
    return batch, reject, diagnostics, legs


def leg_for_join(legs: pl.DataFrame) -> pl.DataFrame:
    return legs.with_columns(
        [
            pl.col("flight_norm").alias("leg_flight_norm_value"),
            pl.col("service_date_utc").alias("leg_service_date_utc_value"),
            pl.col("flight_digits").alias("leg_flight_digits_value"),
            pl.col("flight_prefix").alias("leg_flight_prefix_value"),
        ]
    ).rename(
        {
            "flight_norm": "leg_flight_norm",
            "service_date_utc": "leg_service_date_utc",
            "flight_digits": "leg_flight_digits",
            "flight_prefix": "leg_flight_prefix",
        }
    )


def add_filter_columns(
    joined: pl.DataFrame,
    cfg: AuditConfig,
    *,
    lookback_s: int | None = None,
    end_tolerance_s: int | None = None,
    previous_padding_s: int | None = None,
) -> pl.DataFrame:
    lookback_s = cfg.candidate_time_padding_seconds if lookback_s is None else int(lookback_s)
    end_tolerance_s = cfg.candidate_end_tolerance_seconds if end_tolerance_s is None else int(end_tolerance_s)
    previous_padding_s = cfg.previous_batch_padding_seconds if previous_padding_s is None else int(previous_padding_s)
    mean_lat_rad = ((pl.col("lat_mean") + ((pl.col("min_lat") + pl.col("max_lat")) * 0.5)) * 0.5 * 3.141592653589793 / 180.0)
    spatial_seed_km = (
        ((pl.col("lat_mean") - ((pl.col("min_lat") + pl.col("max_lat")) * 0.5)) * 110.574) ** 2
        + (((pl.col("lon_mean") - ((pl.col("min_lon") + pl.col("max_lon")) * 0.5)) * 111.320 * mean_lat_rad.cos()) ** 2)
    ).sqrt()
    tier_penalty = (
        pl.when(pl.col("stage3_source_tier_v7") == "S0_core_clean_medium_long_source")
        .then(pl.lit(0.0))
        .when(pl.col("stage3_source_tier_v7") == "S1_balanced_medium_source")
        .then(pl.lit(90.0))
        .when(pl.col("stage3_source_tier_v7") == "S2_short_batch_threshold_source")
        .then(pl.lit(180.0))
        .otherwise(pl.lit(360.0))
    )
    quality_penalty = (
        pl.when(pl.col("leg_overall_quality") == "A")
        .then(pl.lit(0.0))
        .when(pl.col("leg_overall_quality") == "B")
        .then(pl.lit(180.0))
        .otherwise(pl.lit(900.0))
    )
    phase_penalty = pl.when(pl.col("flight_phase") == pl.col("leg_phase_like")).then(pl.lit(0.0)).otherwise(pl.lit(900.0))
    time_gap_seconds = (pl.col("end_time_utc") - pl.col("batch_end_time_utc")).dt.total_seconds().abs()
    has_leg = pl.col("adsb_leg_id").is_not_null()
    time_ok = (
        (pl.col("start_time_utc") <= pl.col("batch_end_time_utc") + pl.duration(seconds=end_tolerance_s))
        & (pl.col("end_time_utc") >= pl.col("batch_end_time_utc") - pl.duration(seconds=lookback_s))
    )
    previous_time_ok = (
        pl.col("previous_batch_end_time_utc").is_null()
        | (pl.col("end_time_utc") >= pl.col("previous_batch_end_time_utc") - pl.duration(seconds=previous_padding_s))
    )
    bbox_ok = (
        (pl.col("max_lat") >= pl.col("lat_min") - cfg.spatial_padding_deg)
        & (pl.col("min_lat") <= pl.col("lat_max") + cfg.spatial_padding_deg)
        & (pl.col("max_lon") >= pl.col("lon_min") - cfg.spatial_padding_deg)
        & (pl.col("min_lon") <= pl.col("lon_max") + cfg.spatial_padding_deg)
    )
    altitude_ok = (
        (pl.col("max_alt_m") >= pl.col("alt_min") - cfg.altitude_padding_m)
        & (pl.col("min_alt_m") <= pl.col("alt_max") + cfg.altitude_padding_m)
    )
    phase_ok = ~(
        pl.col("flight_phase").is_in(["ASC", "DES"])
        & pl.col("leg_phase_like").is_in(["ASC", "DES"])
        & (pl.col("flight_phase") != pl.col("leg_phase_like"))
    )
    return joined.with_columns(
        [
            has_leg.alias("has_joined_leg"),
            time_ok.fill_null(False).alias("candidate_time_ok"),
            previous_time_ok.fill_null(False).alias("candidate_previous_time_ok"),
            bbox_ok.fill_null(False).alias("candidate_bbox_ok"),
            altitude_ok.fill_null(False).alias("candidate_altitude_ok"),
            phase_ok.fill_null(False).alias("candidate_phase_ok"),
            spatial_seed_km.alias("candidate_center_distance_km"),
            (pl.col("alt_mean") - ((pl.col("min_alt_m") + pl.col("max_alt_m")) * 0.5)).abs().alias("candidate_altitude_center_diff_m"),
            (time_gap_seconds + quality_penalty + phase_penalty + tier_penalty + 10.0 * spatial_seed_km).alias("candidate_seed_score"),
        ]
    ).with_columns(
        (
            pl.col("has_joined_leg")
            & pl.col("candidate_time_ok")
            & pl.col("candidate_previous_time_ok")
            & pl.col("candidate_bbox_ok")
            & pl.col("candidate_altitude_ok")
            & pl.col("candidate_phase_ok")
        ).alias("candidate_passes_v4_prefilter")
    )


def summarize_join(joined: pl.DataFrame, group_cols: list[str]) -> pl.DataFrame:
    if joined.height == 0:
        return pl.DataFrame()
    leg_flight_col = "leg_flight_norm" if "leg_flight_norm" in joined.columns else "leg_flight_norm_value"
    base_cols = [
        "tail_norm",
        "flight_norm",
        "service_date_utc",
        "batch_end_time_utc",
        "previous_batch_end_time_utc",
        "flight_phase",
        "batch_row_count",
        "stage4_confidence_tier_first",
        "stage4_confidence_subtier_first",
    ]
    keep_cols = [c for c in base_cols if c not in group_cols and c in joined.columns]
    agg_exprs: list[pl.Expr] = [
        pl.len().alias("joined_leg_rows"),
        pl.col("adsb_leg_id").n_unique().alias("unique_leg_count"),
        pl.col(leg_flight_col).n_unique().alias("unique_adsb_flight_count"),
        pl.col("candidate_time_ok").sum().alias("time_ok_rows"),
        pl.col("candidate_previous_time_ok").sum().alias("previous_time_ok_rows"),
        pl.col("candidate_bbox_ok").sum().alias("bbox_ok_rows"),
        pl.col("candidate_altitude_ok").sum().alias("altitude_ok_rows"),
        pl.col("candidate_phase_ok").sum().alias("phase_ok_rows"),
        pl.col("candidate_passes_v4_prefilter").sum().alias("candidate_rows_pass_filters"),
        pl.col("candidate_seed_score").filter(pl.col("candidate_passes_v4_prefilter")).min().alias("best_prefilter_seed_score"),
        pl.col("candidate_center_distance_km").filter(pl.col("candidate_passes_v4_prefilter")).min().alias("best_prefilter_center_distance_km"),
        pl.col("candidate_altitude_center_diff_m").filter(pl.col("candidate_passes_v4_prefilter")).min().alias("best_prefilter_altitude_center_diff_m"),
        pl.col(leg_flight_col).filter(pl.col("candidate_passes_v4_prefilter")).first().alias("first_passing_adsb_flight_norm"),
        pl.col("adsb_leg_id").filter(pl.col("candidate_passes_v4_prefilter")).first().alias("first_passing_adsb_leg_id"),
    ]
    for col in keep_cols:
        agg_exprs.append(pl.col(col).first().alias(col))
    return (
        joined.group_by(group_cols)
        .agg(agg_exprs)
        .with_columns((pl.col("candidate_rows_pass_filters") > 0).alias("has_prefilter_candidate"))
    )


def join_exact(batch_subset: pl.DataFrame, legs_join: pl.DataFrame) -> pl.DataFrame:
    return batch_subset.join(
        legs_join,
        left_on=["tail_norm", "flight_norm", "service_date_utc"],
        right_on=["tail_norm", "leg_flight_norm", "leg_service_date_utc"],
        how="inner",
    )


def shifted_service_date_expr(days: int) -> pl.Expr:
    return (
        pl.col("service_date_utc")
        .str.strptime(pl.Date, "%F", strict=False)
        .dt.offset_by(f"{days}d")
        .dt.strftime("%F")
    )


def audit_no_candidate(
    cfg: AuditConfig,
    batch: pl.DataFrame,
    reject: pl.DataFrame,
    legs: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    no_candidate_ids = reject.filter(pl.col("reject_reason") == "no_candidate_leg").select("amdar_batch_id").unique()
    no_candidate = batch.join(no_candidate_ids, on="amdar_batch_id", how="semi")
    legs_join = leg_for_join(legs)

    tail_keys = legs.select("tail_norm").unique()
    tail_date_keys = legs.select(["tail_norm", "service_date_utc"]).unique()
    tail_flight_date_keys = legs.select(["tail_norm", "flight_norm", "service_date_utc"]).unique()

    tail_missing = no_candidate.join(tail_keys, on="tail_norm", how="anti")
    tail_present = no_candidate.join(tail_keys, on="tail_norm", how="semi")
    tail_date_missing = tail_present.join(tail_date_keys, on=["tail_norm", "service_date_utc"], how="anti")
    tail_date_present = tail_present.join(tail_date_keys, on=["tail_norm", "service_date_utc"], how="semi")
    exact_triplet_missing = tail_date_present.join(
        tail_flight_date_keys, on=["tail_norm", "flight_norm", "service_date_utc"], how="anti"
    )
    exact_triplet_present = tail_date_present.join(
        tail_flight_date_keys, on=["tail_norm", "flight_norm", "service_date_utc"], how="semi"
    )

    exact_joined = add_filter_columns(join_exact(exact_triplet_present, legs_join), cfg)
    exact_summary = summarize_join(exact_joined, ["amdar_batch_id"]) if exact_joined.height else pl.DataFrame()
    if exact_summary.height:
        exact_summary = exact_summary.with_columns(
            pl.when(pl.col("has_prefilter_candidate"))
            .then(pl.lit("unexpected_prefilter_candidate"))
            .when(pl.col("time_ok_rows") == 0)
            .then(pl.lit("exact_identity_no_time_overlap"))
            .when(pl.col("previous_time_ok_rows") == 0)
            .then(pl.lit("exact_identity_previous_batch_time_filter"))
            .when(pl.col("bbox_ok_rows") == 0)
            .then(pl.lit("exact_identity_bbox_filter"))
            .when(pl.col("altitude_ok_rows") == 0)
            .then(pl.lit("exact_identity_altitude_filter"))
            .when(pl.col("phase_ok_rows") == 0)
            .then(pl.lit("exact_identity_phase_filter"))
            .otherwise(pl.lit("exact_identity_compound_filter_intersection"))
            .alias("primary_filter_failure")
        )

    date_shift_frames: list[pl.DataFrame] = []
    for shift in (-1, 1):
        shifted = no_candidate.with_columns(
            [
                shifted_service_date_expr(shift).alias("candidate_service_date_utc"),
                pl.lit(shift).alias("date_shift_days"),
            ]
        )
        joined = shifted.join(
            legs_join,
            left_on=["tail_norm", "flight_norm", "candidate_service_date_utc"],
            right_on=["tail_norm", "leg_flight_norm", "leg_service_date_utc"],
            how="inner",
        )
        if joined.height:
            joined = add_filter_columns(joined, cfg)
            date_shift_frames.append(summarize_join(joined, ["amdar_batch_id", "date_shift_days", "candidate_service_date_utc"]))
    date_shift_audit = pl.concat(date_shift_frames, how="diagonal") if date_shift_frames else pl.DataFrame()
    if date_shift_audit.height:
        date_shift_audit = date_shift_audit.sort(["amdar_batch_id", "date_shift_days"])

    flight_norm_base = no_candidate.with_columns(
        [
            pl.col("flight_norm").cast(pl.Utf8, strict=False).fill_null("MISSING").str.replace_all(r"\D+", "").alias("amdar_flight_digits"),
            pl.col("flight_norm").cast(pl.Utf8, strict=False).fill_null("MISSING").str.replace_all(r"\d+", "").alias("amdar_flight_prefix"),
        ]
    ).filter((pl.col("amdar_flight_digits").is_not_null()) & (pl.col("amdar_flight_digits") != ""))
    flight_joined = flight_norm_base.join(
        legs_join,
        left_on=["tail_norm", "service_date_utc", "amdar_flight_digits"],
        right_on=["tail_norm", "leg_service_date_utc", "leg_flight_digits"],
        how="inner",
    ).filter(pl.col("leg_flight_norm") != pl.col("flight_norm"))
    if flight_joined.height:
        flight_joined = add_filter_columns(flight_joined, cfg)
        same_digit_audit = summarize_join(
            flight_joined,
            ["amdar_batch_id", "amdar_flight_digits", "amdar_flight_prefix", "leg_flight_norm", "leg_flight_prefix"],
        ).with_columns(
            pl.when(pl.col("has_prefilter_candidate"))
            .then(pl.lit("same_digits_prefilter_candidate_available"))
            .otherwise(pl.lit("same_digits_present_but_prefilters_fail"))
            .alias("normalization_audit_status")
        )
    else:
        same_digit_audit = pl.DataFrame()
    same_digit_batch_ids = (
        same_digit_audit.select("amdar_batch_id").unique()
        if same_digit_audit.height
        else pl.DataFrame({"amdar_batch_id": pl.Series([], dtype=pl.Utf8)})
    )
    no_same_digit_audit = (
        exact_triplet_missing.join(same_digit_batch_ids, on="amdar_batch_id", how="anti")
        .with_columns(
            [
                pl.col("flight_norm").cast(pl.Utf8, strict=False).fill_null("MISSING").str.replace_all(r"\D+", "").alias("amdar_flight_digits"),
                pl.col("flight_norm").cast(pl.Utf8, strict=False).fill_null("MISSING").str.replace_all(r"\d+", "").alias("amdar_flight_prefix"),
                pl.lit(None, dtype=pl.Utf8).alias("leg_flight_norm"),
                pl.lit(None, dtype=pl.Utf8).alias("leg_flight_prefix"),
                pl.lit(0, dtype=pl.UInt32).alias("joined_leg_rows"),
                pl.lit(0, dtype=pl.UInt32).alias("unique_leg_count"),
                pl.lit(0, dtype=pl.UInt32).alias("unique_adsb_flight_count"),
                pl.lit(0, dtype=pl.UInt32).alias("time_ok_rows"),
                pl.lit(0, dtype=pl.UInt32).alias("previous_time_ok_rows"),
                pl.lit(0, dtype=pl.UInt32).alias("bbox_ok_rows"),
                pl.lit(0, dtype=pl.UInt32).alias("altitude_ok_rows"),
                pl.lit(0, dtype=pl.UInt32).alias("phase_ok_rows"),
                pl.lit(0, dtype=pl.UInt32).alias("candidate_rows_pass_filters"),
                pl.lit(None, dtype=pl.Float64).alias("best_prefilter_seed_score"),
                pl.lit(None, dtype=pl.Float64).alias("best_prefilter_center_distance_km"),
                pl.lit(None, dtype=pl.Float64).alias("best_prefilter_altitude_center_diff_m"),
                pl.lit(None, dtype=pl.Utf8).alias("first_passing_adsb_flight_norm"),
                pl.lit(None, dtype=pl.Utf8).alias("first_passing_adsb_leg_id"),
                pl.lit(False).alias("has_prefilter_candidate"),
                pl.lit("no_same_digit_adsb_flight_under_tail_date").alias("normalization_audit_status"),
            ]
        )
    )
    flight_norm_audit = (
        pl.concat([same_digit_audit, no_same_digit_audit], how="diagonal_relaxed")
        .sort(["amdar_batch_id", "normalization_audit_status"])
        if same_digit_audit.height or no_same_digit_audit.height
        else pl.DataFrame()
    )

    tail_date_flight_counts = (
        legs.select(["tail_norm", "service_date_utc", "flight_norm"])
        .unique()
        .group_by(["tail_norm", "service_date_utc"])
        .agg(
            [
                pl.col("flight_norm").n_unique().alias("adsb_unique_flight_count_tail_date"),
                pl.col("flight_norm").first().alias("tail_date_unique_adsb_flight_norm"),
            ]
        )
        .filter(pl.col("adsb_unique_flight_count_tail_date") == 1)
    )
    i3_base = no_candidate.join(tail_date_flight_counts, on=["tail_norm", "service_date_utc"], how="inner")
    i3_joined = i3_base.join(
        legs_join,
        left_on=["tail_norm", "service_date_utc", "tail_date_unique_adsb_flight_norm"],
        right_on=["tail_norm", "leg_service_date_utc", "leg_flight_norm"],
        how="inner",
    )
    if i3_joined.height:
        i3_joined = add_filter_columns(i3_joined, cfg)
        i3_audit = summarize_join(i3_joined, ["amdar_batch_id", "tail_date_unique_adsb_flight_norm"])
    else:
        i3_audit = pl.DataFrame()

    i1_batches = set(date_shift_audit.filter(pl.col("has_prefilter_candidate")).get_column("amdar_batch_id").to_list()) if date_shift_audit.height else set()
    i2_batches = set(flight_norm_audit.filter(pl.col("has_prefilter_candidate")).get_column("amdar_batch_id").to_list()) if flight_norm_audit.height else set()
    i3_batches = set(i3_audit.filter(pl.col("has_prefilter_candidate")).get_column("amdar_batch_id").to_list()) if i3_audit.height else set()
    total_potential_batches = sorted(i1_batches | i2_batches | i3_batches)

    exact_failure_counts = counts_map(exact_summary, "primary_filter_failure") if exact_summary.height else {}
    decomposition = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Stage5 v5 alignment audit; no real AMDAR match is accepted here.",
        "input_counts": {
            "all_amdar_batches": int(batch.height),
            "v4_no_candidate_batches": int(no_candidate.height),
            "stage2_v7_candidate_projection_legs": int(legs.height),
        },
        "no_candidate_layer_decomposition": {
            "tail_missing_or_not_in_adsb": int(tail_missing.height),
            "tail_present_but_service_date_missing": int(tail_date_missing.height),
            "tail_date_present_but_exact_flight_missing": int(exact_triplet_missing.height),
            "exact_tail_flight_date_present_but_current_prefilters_fail": int(exact_summary.filter(~pl.col("has_prefilter_candidate")).height) if exact_summary.height else 0,
            "unexpected_exact_prefilter_candidate_batches": int(exact_summary.filter(pl.col("has_prefilter_candidate")).height) if exact_summary.height else 0,
            "exact_prefilter_failure_primary_counts": exact_failure_counts,
        },
        "candidate_policy_potential_prefilter_only": {
            "I1_exact_tail_flight_date_shift_batches": len(i1_batches),
            "I2_normalized_flight_equivalent_batches": len(i2_batches),
            "I3_tail_date_unique_flight_batches": len(i3_batches),
            "I1_I2_I3_union_batches": len(total_potential_batches),
            "note": (
                "These are prefilter candidate-availability counts, not accepted matches. "
                "They still require pseudo validation and real projection scoring."
            ),
        },
        "decision_thresholds": {
            "continue_phase2_strong": 10000,
            "continue_phase2_minimum": 5000,
            "real_stage5_v5_target_requires_pseudo_gate": True,
        },
    }
    if len(total_potential_batches) >= 10000:
        decomposition["audit_decision"] = "continue_phase2_candidate_policy_with_normal_pseudo_gate"
    elif len(total_potential_batches) >= 5000:
        decomposition["audit_decision"] = "continue_phase2_cautiously_lower_target_expectation"
    else:
        decomposition["audit_decision"] = "do_not_run_real_v5_target_branch_without_upstream_candidate_work"

    return date_shift_audit, flight_norm_audit, i3_audit, decomposition


def audit_time_windows(cfg: AuditConfig, batch: pl.DataFrame, reject: pl.DataFrame, legs: pl.DataFrame) -> pl.DataFrame:
    no_candidate_ids = reject.filter(pl.col("reject_reason") == "no_candidate_leg").select("amdar_batch_id").unique()
    no_candidate = batch.join(no_candidate_ids, on="amdar_batch_id", how="semi")
    legs_join = leg_for_join(legs)
    exact = join_exact(no_candidate, legs_join)
    if exact.height == 0:
        return pl.DataFrame()
    scenarios = [
        ("current_v4_3h_back_30m_after", 10800, 1800),
        ("wide_6h_back_1h_after", 21600, 3600),
        ("wide_12h_back_2h_after", 43200, 7200),
        ("diagnostic_24h_back_4h_after", 86400, 14400),
    ]
    frames: list[pl.DataFrame] = []
    for name, lookback_s, end_tolerance_s in scenarios:
        joined = add_filter_columns(exact, cfg, lookback_s=lookback_s, end_tolerance_s=end_tolerance_s)
        summary = summarize_join(joined, ["amdar_batch_id"]).with_columns(
            [
                pl.lit(name).alias("time_window_scenario"),
                pl.lit(lookback_s).alias("lookback_seconds"),
                pl.lit(end_tolerance_s).alias("end_tolerance_seconds"),
            ]
        )
        frames.append(summary)
    return pl.concat(frames, how="diagonal").sort(["time_window_scenario", "amdar_batch_id"])


def audit_geometry(diagnostics: pl.DataFrame) -> dict[str, Any]:
    scored = diagnostics.filter(pl.col("best_cost").is_not_null())
    accepted = diagnostics.filter(pl.col("accepted_by_stage5_v4_layered_gate").fill_null(False))
    rejected_scored = scored.filter(~pl.col("accepted_by_stage5_v4_layered_gate").fill_null(False))
    best_cost_gt3 = diagnostics.filter(pl.col("reject_reason") == "best_cost_gt_3")

    def threshold_count(cost: float, cross: float, vertical: float, after_s: float = 180.0) -> int:
        if scored.height == 0:
            return 0
        return int(
            scored.filter(
                (pl.col("best_cost") <= cost)
                & (pl.col("cross_track_q90_km") <= cross)
                & (pl.col("vertical_q90_m") <= vertical)
                & (pl.col("max_projected_after_batch_end_s") <= after_s)
                & (pl.col("monotonic_violation_count") == 0)
                & (pl.col("stage4_confidence_tier_first") != "T4")
                & (pl.col("stage1_qc_blocked_row_count") == 0)
                & (pl.col("stage4_hard_reject_row_count") == 0)
                & (pl.col("effective_strict_truth_row_count") == 0)
                & (pl.col("strict_holdout_eligible_v3_row_count") == 0)
            ).height
        )

    by_reject_reason: dict[str, Any] = {}
    for reason in diagnostics.select(pl.col("reject_reason").drop_nulls().unique()).to_series().to_list():
        reason_df = diagnostics.filter(pl.col("reject_reason") == reason)
        by_reject_reason[str(reason)] = {
            "batches": int(reason_df.height),
            "best_cost": numeric_summary(reason_df, "best_cost"),
            "cross_track_q90_km": numeric_summary(reason_df, "cross_track_q90_km"),
            "vertical_q90_m": numeric_summary(reason_df, "vertical_q90_m"),
            "max_projected_after_batch_end_s": numeric_summary(reason_df, "max_projected_after_batch_end_s"),
        }

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scored_batches": int(scored.height),
        "accepted_batches_v4": int(accepted.height),
        "rejected_scored_batches": int(rejected_scored.height),
        "all_scored": {
            "best_cost": numeric_summary(scored, "best_cost"),
            "cross_track_q90_km": numeric_summary(scored, "cross_track_q90_km"),
            "vertical_q90_m": numeric_summary(scored, "vertical_q90_m"),
            "max_projected_after_batch_end_s": numeric_summary(scored, "max_projected_after_batch_end_s"),
        },
        "accepted_v4": {
            "best_cost": numeric_summary(accepted, "best_cost"),
            "cross_track_q90_km": numeric_summary(accepted, "cross_track_q90_km"),
            "vertical_q90_m": numeric_summary(accepted, "vertical_q90_m"),
        },
        "best_cost_gt_3": {
            "batches": int(best_cost_gt3.height),
            "best_cost": numeric_summary(best_cost_gt3, "best_cost"),
            "cross_track_q90_km": numeric_summary(best_cost_gt3, "cross_track_q90_km"),
            "vertical_q90_m": numeric_summary(best_cost_gt3, "vertical_q90_m"),
            "identity_match_level_counts": counts_map(best_cost_gt3, "identity_match_level"),
            "stage4_tier_counts": counts_map(best_cost_gt3, "stage4_confidence_tier_first"),
        },
        "by_reject_reason": by_reject_reason,
        "stress_threshold_counts_with_current_safety_filters": {
            "validated_c_gate_cost3_cross1_5_vertical800_time180": threshold_count(3.0, 1.5, 800.0, 180.0),
            "unsafe_cost5_cross3_vertical1000_time180": threshold_count(5.0, 3.0, 1000.0, 180.0),
            "unsafe_cost10_cross5_vertical1500_time180": threshold_count(10.0, 5.0, 1500.0, 180.0),
            "unsafe_cost20_cross10_vertical2000_time180": threshold_count(20.0, 10.0, 2000.0, 180.0),
            "unsafe_cost30_cross15_vertical2500_time180": threshold_count(30.0, 15.0, 2500.0, 180.0),
            "note": "Counts above the validated C gate are diagnostic only and must not be called accepted real matches.",
        },
    }


def write_report(
    cfg: AuditConfig,
    decomposition: dict[str, Any],
    date_shift_audit: pl.DataFrame,
    flight_norm_audit: pl.DataFrame,
    i3_audit: pl.DataFrame,
    time_window_audit: pl.DataFrame,
    geometry: dict[str, Any],
) -> None:
    potential = decomposition["candidate_policy_potential_prefilter_only"]
    exact_counts = decomposition["no_candidate_layer_decomposition"]
    time_counts = (
        time_window_audit.group_by("time_window_scenario")
        .agg(
            [
                pl.len().alias("batches_with_exact_identity_join"),
                pl.col("has_prefilter_candidate").sum().alias("batches_passing_prefilter"),
            ]
        )
        .sort("time_window_scenario")
        .to_dicts()
        if time_window_audit.height
        else []
    )
    decision = decomposition["audit_decision"]
    if decision == "continue_phase2_candidate_policy_with_normal_pseudo_gate":
        decision_text = "审计发现 I1/I2/I3 的 prefilter 潜在候选充足，可以进入 Phase 2，但仍必须先做 Stage3 pseudo validation。"
    elif decision == "continue_phase2_cautiously_lower_target_expectation":
        decision_text = "审计发现潜在候选处于最低可继续区间；可以谨慎进入 Phase 2，但应降低目标预期并严格执行 pseudo gate。"
    else:
        decision_text = "审计未发现足够的系统性候选修复收益；不能运行 real Stage5 v5 target branch，应先回到候选池/上游数据对齐工作。"

    md = f"""# Stage5 V5 Alignment Audit Results And Next Steps

Generated at UTC: `{datetime.now(timezone.utc).isoformat()}`

## Scope And Stage Naming

This is optimization-plan phase 4 work for large-framework Stage5 real AMDAR-ADS-B matching. It is an alignment audit only. It does not run large-framework Stage6 time modeling, does not create strict AMDAR truth, and does not accept weak identity candidates.

## Inputs And Space Policy

- Stage5 v4 compact batch/reject/diagnostic tables: `{cfg.stage5_v4_dir}`
- Stage2 v7 compact ADS-B leg table: `{cfg.stage2_v7_dir / 'adsb_leg_quality_components_v7.parquet'}`
- Stage4 v3 compact confidence directory: `{cfg.stage4_v3_dir}`
- `POLARS_MAX_THREADS=25`, `slice_count={cfg.slice_count}`
- The audit reads compact leg/batch tables only. It does not copy the Stage2 v4 full ADS-B point table and does not create 25 duplicated full intermediates.

## No-Candidate Decomposition

- Total AMDAR batches: `{decomposition['input_counts']['all_amdar_batches']}`
- V4 no-candidate batches: `{decomposition['input_counts']['v4_no_candidate_batches']}`
- Stage2 v7 candidate projection legs: `{decomposition['input_counts']['stage2_v7_candidate_projection_legs']}`
- Tail missing/not in ADS-B: `{exact_counts['tail_missing_or_not_in_adsb']}`
- Tail present but same service date missing: `{exact_counts['tail_present_but_service_date_missing']}`
- Tail/date present but exact flight missing: `{exact_counts['tail_date_present_but_exact_flight_missing']}`
- Exact tail/flight/date present but current prefilters fail: `{exact_counts['exact_tail_flight_date_present_but_current_prefilters_fail']}`
- Exact prefilter primary failure counts: `{exact_counts['exact_prefilter_failure_primary_counts']}`

## Candidate-Policy Potential

These counts are availability/prefilter counts only, not accepted matches.

- I1 exact tail+flight with date shift: `{potential['I1_exact_tail_flight_date_shift_batches']}` batches
- I2 normalized flight equivalent by same flight digits: `{potential['I2_normalized_flight_equivalent_batches']}` batches
- I3 tail/date unique flight: `{potential['I3_tail_date_unique_flight_batches']}` batches
- I1/I2/I3 union: `{potential['I1_I2_I3_union_batches']}` batches

## Time-Window Audit

`{time_counts}`

## Geometry Failure Audit

- Scored batches: `{geometry['scored_batches']}`
- V4 accepted batches: `{geometry['accepted_batches_v4']}`
- `best_cost_gt_3` batches: `{geometry['best_cost_gt_3']['batches']}`
- All-scored best_cost summary: `{geometry['all_scored']['best_cost']}`
- best_cost_gt_3 summary: `{geometry['best_cost_gt_3']['best_cost']}`
- Stress threshold counts: `{geometry['stress_threshold_counts_with_current_safety_filters']}`

Interpretation: direct relaxation beyond `cost<=3` and `cross_track_q90<=1.5km` remains diagnostic only. It must not be used to create accepted real matches unless reproduced and validated in Stage3 pseudo-AMDAR.

## Decision

Audit decision: `{decision}`

{decision_text}

## Required Next Steps

1. If continuing, implement candidate policy v5 as a separate output branch with explicit `identity_level`, evidence fields, date-shift/normalization diagnostics, ambiguity diagnostics, and `identity_conflict=false` enforcement.
2. Reproduce the enabled v5 policy in Stage3 pseudo-AMDAR validation before any real Stage5 v5 target run.
3. Tune only on validation split; locked test must remain report-only.
4. Report wrong-leg and catastrophic rates separately for I0/I1/I2/I3.
5. Keep AMDAR `effective_strict_truth=false`, `holdout_eligible=false`, `estimated_time_is_strict_point_truth=false`, and `usage_role=support_only_not_strict_truth`.

## Output Files

- `no_candidate_decomposition_v5.json`
- `flight_normalization_audit_v5.parquet`
- `date_shift_candidate_audit_v5.parquet`
- `time_window_candidate_audit_v5.parquet`
- `geometry_failure_quantiles_v5.json`
- `alignment_audit_results_and_next_steps.md`
"""
    write_markdown(cfg.out_dir / "alignment_audit_results_and_next_steps.md", md)
    write_markdown(cfg.out_dir / "alignment_audit_results_and_next_steps_v5.md", md)


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Stage5 v5 audit] output={cfg.out_dir}")
    batch, reject, diagnostics, legs = load_inputs(cfg)
    print(f"[load] batches={batch.height} reject={reject.height} diagnostics={diagnostics.height} legs={legs.height}")

    date_shift_audit, flight_norm_audit, i3_audit, decomposition = audit_no_candidate(cfg, batch, reject, legs)
    time_window_audit = audit_time_windows(cfg, batch, reject, legs)
    geometry = audit_geometry(diagnostics)

    write_json(cfg.out_dir / "run_config.json", asdict(cfg))
    write_json(cfg.out_dir / "no_candidate_decomposition_v5.json", decomposition)
    write_json(cfg.out_dir / "geometry_failure_quantiles_v5.json", geometry)

    if flight_norm_audit.height:
        flight_norm_audit.write_parquet(cfg.out_dir / "flight_normalization_audit_v5.parquet")
    else:
        pl.DataFrame().write_parquet(cfg.out_dir / "flight_normalization_audit_v5.parquet")
    if date_shift_audit.height:
        date_shift_audit.write_parquet(cfg.out_dir / "date_shift_candidate_audit_v5.parquet")
    else:
        pl.DataFrame().write_parquet(cfg.out_dir / "date_shift_candidate_audit_v5.parquet")
    if time_window_audit.height:
        time_window_audit.write_parquet(cfg.out_dir / "time_window_candidate_audit_v5.parquet")
    else:
        pl.DataFrame().write_parquet(cfg.out_dir / "time_window_candidate_audit_v5.parquet")
    if i3_audit.height:
        i3_audit.write_parquet(cfg.out_dir / "tail_date_unique_candidate_audit_v5.parquet")
    else:
        pl.DataFrame().write_parquet(cfg.out_dir / "tail_date_unique_candidate_audit_v5.parquet")

    write_report(cfg, decomposition, date_shift_audit, flight_norm_audit, i3_audit, time_window_audit, geometry)
    print(f"[decision] {decomposition['audit_decision']}")
    print(f"[potential] {decomposition['candidate_policy_potential_prefilter_only']}")


if __name__ == "__main__":
    main()
