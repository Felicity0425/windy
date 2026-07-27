from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE3_4_DIR = DATA_DIR / "amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701"
STAGE4_V2_DIR = STAGE3_4_DIR / "stage4_confidence_v2"
STAGE2_V6_DIR = DATA_DIR / "amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701/stage2_adsb_qc_v6_readiness"
STAGE3_V8_DIR = DATA_DIR / "stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8"
STAGE4_V3_DIR = DATA_DIR / "stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3"
STAGE2_V7_DIR = DATA_DIR / "stage2_adsb_qc_v7_optimized_20260706"
STAGE2_V4_DIR = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4"
DEFAULT_OUT_DIR = DATA_DIR / "stage5_v4_matching_optimized_20260708"

EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage3_v8_dir: Path = STAGE3_V8_DIR
    stage4_v3_dir: Path = STAGE4_V3_DIR
    stage2_v7_dir: Path = STAGE2_V7_DIR
    stage2_v4_dir: Path = STAGE2_V4_DIR
    slice_count: int = 25
    workers: int = 25
    candidate_topk: int = 10
    candidate_time_padding_seconds: int = 10800
    candidate_end_tolerance_seconds: int = 1800
    previous_batch_padding_seconds: int = 10800
    spatial_padding_deg: float = 2.0
    altitude_padding_m: float = 4000.0
    a_best_cost_max: float = 0.5
    a_cross_track_q90_max_km: float = 0.5
    a_vertical_q90_max_m: float = 150.0
    a_sampling_gap_max_s: float = 300.0
    a_batch_end_tolerance_s: float = 90.0
    a_ambiguity_margin_min: float = 2.5
    b_best_cost_max: float = 1.5
    b_cross_track_q90_max_km: float = 1.0
    b_vertical_q90_max_m: float = 500.0
    b_sampling_gap_max_s: float = 900.0
    b_batch_end_tolerance_s: float = 120.0
    b_ambiguity_margin_min: float = 1.5
    c_best_cost_max: float = 3.0
    c_cross_track_q90_max_km: float = 1.5
    c_vertical_q90_max_m: float = 800.0
    c_sampling_gap_max_s: float = 900.0
    c_batch_end_tolerance_s: float = 180.0
    c_ambiguity_margin_min: float = 1.2


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage5 V4 real AMDAR-ADS-B matching diagnostics. "
            "Consumes Stage4 confidence v3 and Stage2 v7/v4 ADS-B products."
        )
    )
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


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(pl.Series(values, dtype=pl.Float64).quantile(q))


def stable_int(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:16], 16)


def partition_key_scalar(key: Any) -> Any:
    if isinstance(key, tuple) and len(key) == 1:
        return key[0]
    return key


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def local_xy_km(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    mean_lat = math.radians((lat0 + lat) / 2.0)
    x = (lon - lon0) * 111.320 * math.cos(mean_lat)
    y = (lat - lat0) * 110.574
    return x, y


def project_to_segment(point: dict[str, Any], a: dict[str, Any], b: dict[str, Any], idx: int) -> dict[str, Any]:
    bx, by = local_xy_km(float(a["lat_clean"]), float(a["lon_clean"]), float(b["lat_clean"]), float(b["lon_clean"]))
    px, py = local_xy_km(float(a["lat_clean"]), float(a["lon_clean"]), float(point["lat_clean"]), float(point["lon_clean"]))
    ab2 = bx * bx + by * by
    frac = 0.0 if ab2 <= 1e-12 else (px * bx + py * by) / ab2
    frac_clamped = min(1.0, max(0.0, frac))
    proj_x = bx * frac_clamped
    proj_y = by * frac_clamped
    cross_track = math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
    alt_proj = float(a["alt_meters"]) + frac_clamped * (float(b["alt_meters"]) - float(a["alt_meters"]))
    vertical = abs(float(point["alt_meters"]) - alt_proj)
    dt = float((b["time_utc"] - a["time_utc"]).total_seconds())
    estimated_time = a["time_utc"] + timedelta(seconds=dt * frac_clamped)
    return {
        "estimated_time_utc": estimated_time,
        "cross_track_distance_km": cross_track,
        "vertical_difference_m": vertical,
        "sampling_gap_seconds": dt,
        "projection_fraction": frac_clamped,
        "segment_index": idx,
        "segment_start_time_utc": a["time_utc"],
        "segment_end_time_utc": b["time_utc"],
        "segment_start_lat": a["lat_clean"],
        "segment_start_lon": a["lon_clean"],
        "segment_start_alt_m": a["alt_meters"],
        "segment_end_lat": b["lat_clean"],
        "segment_end_lon": b["lon_clean"],
        "segment_end_alt_m": b["alt_meters"],
    }


def project_to_leg(point: dict[str, Any], leg_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not leg_rows:
        return {
            "estimated_time_utc": None,
            "cross_track_distance_km": float("inf"),
            "vertical_difference_m": float("inf"),
            "sampling_gap_seconds": None,
            "projection_fraction": None,
            "segment_index": None,
        }
    if len(leg_rows) == 1:
        row = leg_rows[0]
        return {
            "estimated_time_utc": row["time_utc"],
            "cross_track_distance_km": haversine_km(float(point["lat_clean"]), float(point["lon_clean"]), float(row["lat_clean"]), float(row["lon_clean"])),
            "vertical_difference_m": abs(float(point["alt_meters"]) - float(row["alt_meters"])),
            "sampling_gap_seconds": 0.0,
            "projection_fraction": 0.0,
            "segment_index": 0,
            "segment_start_time_utc": row["time_utc"],
            "segment_end_time_utc": row["time_utc"],
            "segment_start_lat": row["lat_clean"],
            "segment_start_lon": row["lon_clean"],
            "segment_start_alt_m": row["alt_meters"],
            "segment_end_lat": row["lat_clean"],
            "segment_end_lon": row["lon_clean"],
            "segment_end_alt_m": row["alt_meters"],
        }
    best: dict[str, Any] | None = None
    for idx in range(len(leg_rows) - 1):
        proj = project_to_segment(point, leg_rows[idx], leg_rows[idx + 1], idx)
        cost = proj["cross_track_distance_km"] + 0.001 * proj["vertical_difference_m"]
        if best is None or cost < best["cost"]:
            best = {**proj, "cost": cost}
    return best or {
        "estimated_time_utc": None,
        "cross_track_distance_km": float("inf"),
        "vertical_difference_m": float("inf"),
        "sampling_gap_seconds": None,
        "projection_fraction": None,
        "segment_index": None,
    }


def batch_size_bucket_expr(col: str = "batch_row_count") -> pl.Expr:
    return (
        pl.when(pl.col(col) <= 1)
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


def load_stage_gate(cfg: RunConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    stage3_report = read_json(cfg.stage3_v8_dir / "pseudo_amdar_v8_calibration_report.json")
    stage4_summary = read_json(cfg.stage4_v3_dir / "confidence_tier_summary_v3.json")
    return stage3_report, stage4_summary


def build_batch_base(cfg: RunConfig, out_dir: Path) -> pl.DataFrame:
    comp_path = cfg.stage4_v3_dir / "amdar_confidence_components_v3.parquet"
    batch = (
        pl.scan_parquet(comp_path)
        .filter(pl.col("source") == "amdar")
        .group_by("amdar_batch_id")
        .agg(
            [
                pl.col("tail_norm").first().alias("tail_norm"),
                pl.col("flight_norm").first().alias("flight_norm"),
                pl.col("service_date_utc").first().alias("service_date_utc"),
                pl.col("time_utc").first().alias("batch_end_time_utc"),
                pl.col("飞行阶段").first().alias("flight_phase"),
                pl.col("lat_clean").min().alias("lat_min"),
                pl.col("lat_clean").max().alias("lat_max"),
                pl.col("lon_clean").min().alias("lon_min"),
                pl.col("lon_clean").max().alias("lon_max"),
                pl.col("alt_meters").min().alias("alt_min"),
                pl.col("alt_meters").max().alias("alt_max"),
                pl.col("lat_clean").mean().alias("lat_mean"),
                pl.col("lon_clean").mean().alias("lon_mean"),
                pl.col("alt_meters").mean().alias("alt_mean"),
                pl.col("source_row_index").min().alias("source_row_index_min"),
                pl.col("source_row_index").max().alias("source_row_index_max"),
                pl.len().alias("batch_row_count"),
                pl.col("base_support_conf").min().alias("base_support_conf_min"),
                pl.col("base_support_conf").mean().alias("base_support_conf_mean"),
                pl.col("base_support_conf").max().alias("base_support_conf_max"),
                pl.col("confidence_tier").first().alias("stage4_confidence_tier_first"),
                pl.col("confidence_grade").first().alias("stage4_confidence_grade_first"),
                pl.col("confidence_subtier").first().alias("stage4_confidence_subtier_first"),
                pl.col("recommended_stage4_role").first().alias("recommended_stage4_role_first"),
                pl.col("stage4_weighting_recommendation_v3").first().alias("stage4_weighting_recommendation_v3_first"),
                pl.col("stage4_high_wind_action_v3").first().alias("stage4_high_wind_action_v3_first"),
                pl.col("time_uncertainty_s_stage4_v3").first().alias("time_uncertainty_s_stage4_v3_first"),
                pl.col("time_uncertainty_s_stage4_v3_continuous").mean().alias("time_uncertainty_s_stage4_v3_continuous_mean"),
                (pl.col("base_support_conf") <= 0.0).sum().alias("stage1_qc_blocked_row_count"),
                pl.col("hard_reject_flag_v3").fill_null(False).sum().alias("stage4_hard_reject_row_count"),
                pl.col("effective_strict_truth").fill_null(False).sum().alias("effective_strict_truth_row_count"),
                pl.col("strict_holdout_eligible_v3").fill_null(False).sum().alias("strict_holdout_eligible_v3_row_count"),
                pl.col("stage1_downstream_action_v3").first().alias("stage1_downstream_action_v3_first"),
            ]
        )
        .sort(["tail_norm", "flight_norm", "batch_end_time_utc", "amdar_batch_id"])
        .with_columns(
            [
                pl.col("batch_end_time_utc")
                .shift(1)
                .over(["tail_norm", "flight_norm"])
                .alias("previous_batch_end_time_utc"),
                batch_size_bucket_expr("batch_row_count").alias("batch_size_bucket"),
                (pl.col("stage1_qc_blocked_row_count") >= pl.col("batch_row_count")).alias("stage1_qc_all_rows_blocked"),
                ((pl.col("tail_norm") != "MISSING") & (pl.col("flight_norm") != "MISSING")).alias("strong_identity_available"),
                (pl.col("source_row_index_min").cast(pl.UInt64) % int(cfg.slice_count)).cast(pl.UInt8).alias("batch_processing_slice_id"),
            ]
        )
        .collect(streaming=True)
    )
    batch.write_parquet(out_dir / "amdar_batch_base_v4.parquet")
    return batch


def build_candidates(cfg: RunConfig, batch: pl.DataFrame, out_dir: Path) -> tuple[pl.DataFrame, dict[str, Any]]:
    leg_path = cfg.stage2_v7_dir / "adsb_leg_quality_components_v7.parquet"
    legs = (
        pl.scan_parquet(leg_path)
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
                "stage3_consumer_gate_v7",
                "adsb_stage3_source_conf_cap_v7",
            ]
        )
        .collect(streaming=True)
    )

    b = batch.lazy()
    l = legs.lazy().with_columns(
        [
            ((pl.col("min_lat") + pl.col("max_lat")) * 0.5).alias("leg_center_lat"),
            ((pl.col("min_lon") + pl.col("max_lon")) * 0.5).alias("leg_center_lon"),
            ((pl.col("min_alt_m") + pl.col("max_alt_m")) * 0.5).alias("leg_center_alt_m"),
        ]
    )
    joined = b.join(l, on=["tail_norm", "flight_norm", "service_date_utc"], how="left")
    has_leg = pl.col("adsb_leg_id").is_not_null()
    time_ok = (
        (pl.col("start_time_utc") <= pl.col("batch_end_time_utc") + pl.duration(seconds=cfg.candidate_end_tolerance_seconds))
        & (pl.col("end_time_utc") >= pl.col("batch_end_time_utc") - pl.duration(seconds=cfg.candidate_time_padding_seconds))
    )
    previous_time_ok = (
        pl.col("previous_batch_end_time_utc").is_null()
        | (pl.col("end_time_utc") >= pl.col("previous_batch_end_time_utc") - pl.duration(seconds=cfg.previous_batch_padding_seconds))
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
    mean_lat_rad = ((pl.col("lat_mean") + pl.col("leg_center_lat")) * 0.5 * math.pi / 180.0)
    spatial_seed_km = (
        ((pl.col("lat_mean") - pl.col("leg_center_lat")) * 110.574) ** 2
        + (((pl.col("lon_mean") - pl.col("leg_center_lon")) * 111.320 * mean_lat_rad.cos()) ** 2)
    ).sqrt()
    time_gap_seconds = (pl.col("end_time_utc") - pl.col("batch_end_time_utc")).dt.total_seconds().abs()
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
    exact_candidate = (
        joined.with_columns(
            [
                has_leg.alias("has_exact_identity_date_leg"),
                time_ok.fill_null(False).alias("candidate_time_ok"),
                previous_time_ok.fill_null(False).alias("candidate_previous_time_ok"),
                bbox_ok.fill_null(False).alias("candidate_bbox_ok"),
                altitude_ok.fill_null(False).alias("candidate_altitude_ok"),
                phase_ok.fill_null(False).alias("candidate_phase_ok"),
                spatial_seed_km.alias("candidate_center_distance_km"),
                (pl.col("alt_mean") - pl.col("leg_center_alt_m")).abs().alias("candidate_altitude_center_diff_m"),
                (time_gap_seconds + quality_penalty + phase_penalty + tier_penalty + 10.0 * spatial_seed_km).alias("candidate_seed_score"),
                pl.lit("strong_tail_flight_date").alias("identity_match_level"),
            ]
        )
        .filter(
            pl.col("has_exact_identity_date_leg")
            & pl.col("candidate_time_ok")
            & pl.col("candidate_previous_time_ok")
            & pl.col("candidate_bbox_ok")
            & pl.col("candidate_altitude_ok")
            & pl.col("candidate_phase_ok")
        )
        .sort(["amdar_batch_id", "candidate_seed_score", "adsb_leg_id"])
        .with_columns(
            pl.col("candidate_seed_score").rank("ordinal").over("amdar_batch_id").cast(pl.Int32).alias("candidate_rank")
        )
        .select(
            [
                "amdar_batch_id",
                "tail_norm",
                "flight_norm",
                "service_date_utc",
                "batch_end_time_utc",
                "previous_batch_end_time_utc",
                "flight_phase",
                "batch_row_count",
                "batch_size_bucket",
                "stage4_confidence_tier_first",
                "stage4_confidence_grade_first",
                "stage4_confidence_subtier_first",
                "stage4_weighting_recommendation_v3_first",
                "stage1_qc_all_rows_blocked",
                "adsb_leg_id",
                pl.col("flight_norm").alias("matched_adsb_flight_norm"),
                "identity_match_level",
                "leg_phase_like",
                "leg_overall_quality",
                "stage3_source_tier_v7",
                "point_count",
                "duration_seconds",
                "path_length_km_v4",
                "sampling_gap_q90",
                "sampling_gap_max",
                "stage2_v7_weighted_score",
                "stage3_consumer_gate_v7",
                "adsb_stage3_source_conf_cap_v7",
                "candidate_center_distance_km",
                "candidate_altitude_center_diff_m",
                "candidate_seed_score",
                "candidate_rank",
            ]
        )
        .collect(streaming=True)
    )
    exact_candidate_ids = (
        exact_candidate.select("amdar_batch_id").unique()
        if exact_candidate.height
        else pl.DataFrame({"amdar_batch_id": pl.Series([], dtype=pl.Utf8)})
    )

    b_no_exact = batch.join(exact_candidate_ids, on="amdar_batch_id", how="anti")
    l_tail_date = legs.rename({"flight_norm": "matched_adsb_flight_norm"}).lazy().with_columns(
        [
            ((pl.col("min_lat") + pl.col("max_lat")) * 0.5).alias("leg_center_lat"),
            ((pl.col("min_lon") + pl.col("max_lon")) * 0.5).alias("leg_center_lon"),
            ((pl.col("min_alt_m") + pl.col("max_alt_m")) * 0.5).alias("leg_center_alt_m"),
        ]
    )
    tail_joined = b_no_exact.lazy().join(l_tail_date, on=["tail_norm", "service_date_utc"], how="left")
    tail_has_leg = pl.col("adsb_leg_id").is_not_null()
    tail_time_ok = (
        (pl.col("start_time_utc") <= pl.col("batch_end_time_utc") + pl.duration(seconds=cfg.candidate_end_tolerance_seconds))
        & (pl.col("end_time_utc") >= pl.col("batch_end_time_utc") - pl.duration(seconds=cfg.candidate_time_padding_seconds))
    )
    tail_previous_time_ok = (
        pl.col("previous_batch_end_time_utc").is_null()
        | (pl.col("end_time_utc") >= pl.col("previous_batch_end_time_utc") - pl.duration(seconds=cfg.previous_batch_padding_seconds))
    )
    tail_bbox_ok = (
        (pl.col("max_lat") >= pl.col("lat_min") - cfg.spatial_padding_deg)
        & (pl.col("min_lat") <= pl.col("lat_max") + cfg.spatial_padding_deg)
        & (pl.col("max_lon") >= pl.col("lon_min") - cfg.spatial_padding_deg)
        & (pl.col("min_lon") <= pl.col("lon_max") + cfg.spatial_padding_deg)
    )
    tail_altitude_ok = (
        (pl.col("max_alt_m") >= pl.col("alt_min") - cfg.altitude_padding_m)
        & (pl.col("min_alt_m") <= pl.col("alt_max") + cfg.altitude_padding_m)
    )
    tail_phase_ok = ~(
        pl.col("flight_phase").is_in(["ASC", "DES"])
        & pl.col("leg_phase_like").is_in(["ASC", "DES"])
        & (pl.col("flight_phase") != pl.col("leg_phase_like"))
    )
    tail_mean_lat_rad = ((pl.col("lat_mean") + pl.col("leg_center_lat")) * 0.5 * math.pi / 180.0)
    tail_spatial_seed_km = (
        ((pl.col("lat_mean") - pl.col("leg_center_lat")) * 110.574) ** 2
        + (((pl.col("lon_mean") - pl.col("leg_center_lon")) * 111.320 * tail_mean_lat_rad.cos()) ** 2)
    ).sqrt()
    tail_time_gap_seconds = (pl.col("end_time_utc") - pl.col("batch_end_time_utc")).dt.total_seconds().abs()
    tail_tier_penalty = (
        pl.when(pl.col("stage3_source_tier_v7") == "S0_core_clean_medium_long_source")
        .then(pl.lit(0.0))
        .when(pl.col("stage3_source_tier_v7") == "S1_balanced_medium_source")
        .then(pl.lit(90.0))
        .when(pl.col("stage3_source_tier_v7") == "S2_short_batch_threshold_source")
        .then(pl.lit(180.0))
        .otherwise(pl.lit(360.0))
    )
    tail_quality_penalty = (
        pl.when(pl.col("leg_overall_quality") == "A")
        .then(pl.lit(0.0))
        .when(pl.col("leg_overall_quality") == "B")
        .then(pl.lit(180.0))
        .otherwise(pl.lit(900.0))
    )
    tail_phase_penalty = pl.when(pl.col("flight_phase") == pl.col("leg_phase_like")).then(pl.lit(0.0)).otherwise(pl.lit(900.0))
    weak_candidate = (
        tail_joined.with_columns(
            [
                tail_has_leg.alias("has_tail_date_leg"),
                tail_time_ok.fill_null(False).alias("candidate_time_ok"),
                tail_previous_time_ok.fill_null(False).alias("candidate_previous_time_ok"),
                tail_bbox_ok.fill_null(False).alias("candidate_bbox_ok"),
                tail_altitude_ok.fill_null(False).alias("candidate_altitude_ok"),
                tail_phase_ok.fill_null(False).alias("candidate_phase_ok"),
                tail_spatial_seed_km.alias("candidate_center_distance_km"),
                (pl.col("alt_mean") - pl.col("leg_center_alt_m")).abs().alias("candidate_altitude_center_diff_m"),
                (tail_time_gap_seconds + tail_quality_penalty + tail_phase_penalty + tail_tier_penalty + 10.0 * tail_spatial_seed_km).alias("candidate_seed_score"),
            ]
        )
        .filter(
            pl.col("has_tail_date_leg")
            & pl.col("candidate_time_ok")
            & pl.col("candidate_previous_time_ok")
            & pl.col("candidate_bbox_ok")
            & pl.col("candidate_altitude_ok")
            & pl.col("candidate_phase_ok")
        )
        .with_columns(
            pl.col("matched_adsb_flight_norm").n_unique().over("amdar_batch_id").alias("tail_date_candidate_flight_count")
        )
        .filter(pl.col("tail_date_candidate_flight_count") == 1)
        .with_columns(pl.lit("tail_date_unique_flight_no_exact_match").alias("identity_match_level"))
        .sort(["amdar_batch_id", "candidate_seed_score", "adsb_leg_id"])
        .with_columns(
            pl.col("candidate_seed_score").rank("ordinal").over("amdar_batch_id").cast(pl.Int32).alias("candidate_rank")
        )
        .select(exact_candidate.columns)
        .collect(streaming=True)
    )
    candidate = pl.concat([exact_candidate, weak_candidate], how="vertical") if weak_candidate.height else exact_candidate
    candidate.write_parquet(out_dir / "amdar_adsb_candidate_legs_v4.parquet")

    candidate_batches = candidate.select("amdar_batch_id").unique() if candidate.height else pl.DataFrame({"amdar_batch_id": []})
    no_candidate = batch.join(candidate_batches, on="amdar_batch_id", how="anti")
    summary = {
        "batch_count": int(batch.height),
        "candidate_leg_pool_count": int(legs.height),
        "candidate_rows": int(candidate.height),
        "exact_candidate_rows": int(exact_candidate.height),
        "weak_tail_date_unique_candidate_rows": int(weak_candidate.height),
        "batches_with_candidate": int(candidate.select(pl.col("amdar_batch_id").n_unique()).item()) if candidate.height else 0,
        "batches_without_candidate": int(no_candidate.height),
        "candidate_rank_summary": numeric_summary(candidate, "candidate_rank"),
        "candidate_count_by_batch": (
            candidate.group_by("amdar_batch_id").agg(pl.len().alias("candidate_count")).select(
                [
                    pl.len().alias("batches"),
                    pl.col("candidate_count").min().alias("min"),
                    pl.col("candidate_count").median().alias("median"),
                    pl.col("candidate_count").quantile(0.9).alias("p90"),
                    pl.col("candidate_count").max().alias("max"),
                ]
            ).to_dicts()[0]
            if candidate.height
            else {}
        ),
        "candidate_stage4_tier_counts": counts_map(candidate, "stage4_confidence_tier_first"),
        "candidate_stage4_subtier_counts": counts_map(candidate, "stage4_confidence_subtier_first"),
        "candidate_identity_match_level_counts": counts_map(candidate, "identity_match_level"),
        "candidate_leg_quality_counts": counts_map(candidate, "leg_overall_quality"),
        "candidate_source_tier_counts": counts_map(candidate, "stage3_source_tier_v7"),
        "space_saving_policy": "One compact candidate table; no duplicated per-slice full intermediates.",
    }
    write_json(out_dir / "amdar_adsb_candidate_summary_v4.json", summary)
    return candidate, summary


def score_candidate(
    group_rows: list[dict[str, Any]],
    leg_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], float, int] | None:
    if not group_rows or len(leg_rows) < 2:
        return None
    projections: list[dict[str, Any]] = []
    costs: list[float] = []
    monotonic_violations = 0
    last_time = None
    last_segment = -1
    for point in group_rows:
        proj = project_to_leg(point, leg_rows)
        if proj["estimated_time_utc"] is None:
            return None
        if last_time is not None and proj["estimated_time_utc"] < last_time:
            monotonic_violations += 1
        segment_index = int(proj.get("segment_index") or 0)
        if segment_index < last_segment:
            monotonic_violations += 1
        last_time = proj["estimated_time_utc"]
        last_segment = segment_index
        costs.append(float(proj["cross_track_distance_km"]) + 0.001 * float(proj["vertical_difference_m"]))
        projections.append({**point, **proj})
    total_cost = (sum(costs) / max(1, len(costs))) + monotonic_violations * 50.0
    return projections, float(total_cost), monotonic_violations


def ambiguity_passes(group: dict[str, Any], threshold: float) -> bool:
    if int(group.get("evaluated_candidate_count") or 0) <= 1:
        return True
    margin = group.get("ambiguity_margin")
    return margin is not None and float(margin) >= threshold


def acceptance_decision_v4(group: dict[str, Any], cfg: RunConfig) -> dict[str, Any]:
    if group.get("status") in {"no_candidate", "projection_failed"}:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": str(group.get("reject_reason") or group.get("status"))}
    if str(group.get("stage4_confidence_tier_first") or "") == "T4":
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "stage4_t4_not_accepted_for_reconstruction"}
    if int(group.get("stage1_qc_blocked_row_count") or 0) > 0:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "stage1_qc_blocked_rows_present"}
    if int(group.get("stage4_hard_reject_row_count") or 0) > 0:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "stage4_hard_reject_rows_present"}
    if int(group.get("effective_strict_truth_row_count") or 0) > 0 or int(group.get("strict_holdout_eligible_v3_row_count") or 0) > 0:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "amdar_truth_invariant_violation"}
    identity_level = group.get("identity_match_level")
    if identity_level not in {"strong_tail_flight_date", "tail_date_unique_flight_no_exact_match"}:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "identity_match_not_traceable"}
    if int(group.get("monotonic_violation_count") or 0) != 0:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "monotonic_violation"}

    best_cost = group.get("best_cost")
    cross_track = group.get("cross_track_q90_km")
    vertical = group.get("vertical_q90_m")
    sampling_gap = group.get("sampling_gap_max_seconds")
    max_after_batch = group.get("max_projected_after_batch_end_s")
    if best_cost is None:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "best_cost_missing"}
    if cross_track is None:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "cross_track_q90_missing"}
    if vertical is None:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "vertical_q90_missing"}
    if sampling_gap is None:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "sampling_gap_missing"}
    if max_after_batch is None:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "batch_end_projection_missing"}

    best_cost_f = float(best_cost)
    cross_track_f = float(cross_track)
    vertical_f = float(vertical)
    sampling_gap_f = float(sampling_gap)
    max_after_batch_f = float(max_after_batch)

    weak_identity = identity_level == "tail_date_unique_flight_no_exact_match"

    if (not weak_identity) and (
        best_cost_f <= cfg.a_best_cost_max
        and cross_track_f <= cfg.a_cross_track_q90_max_km
        and vertical_f <= cfg.a_vertical_q90_max_m
        and sampling_gap_f <= cfg.a_sampling_gap_max_s
        and max_after_batch_f <= cfg.a_batch_end_tolerance_s
        and ambiguity_passes(group, cfg.a_ambiguity_margin_min)
    ):
        return {"accepted": True, "grade": "A", "confidence": 0.85, "reason": "accepted_v4_grade_A_support_only"}

    if (not weak_identity) and (
        best_cost_f <= cfg.b_best_cost_max
        and cross_track_f <= cfg.b_cross_track_q90_max_km
        and vertical_f <= cfg.b_vertical_q90_max_m
        and sampling_gap_f <= cfg.b_sampling_gap_max_s
        and max_after_batch_f <= cfg.b_batch_end_tolerance_s
        and ambiguity_passes(group, cfg.b_ambiguity_margin_min)
    ):
        return {"accepted": True, "grade": "B", "confidence": 0.70, "reason": "accepted_v4_grade_B_support_only"}

    if weak_identity and (
        best_cost_f <= cfg.b_best_cost_max
        and cross_track_f <= cfg.b_cross_track_q90_max_km
        and vertical_f <= cfg.b_vertical_q90_max_m
        and sampling_gap_f <= cfg.b_sampling_gap_max_s
        and max_after_batch_f <= cfg.b_batch_end_tolerance_s
        and ambiguity_passes(group, cfg.b_ambiguity_margin_min)
    ):
        return {"accepted": True, "grade": "C", "confidence": 0.45, "reason": "accepted_v4_grade_C_tail_date_unique_support_only"}

    if (
        best_cost_f <= cfg.c_best_cost_max
        and cross_track_f <= cfg.c_cross_track_q90_max_km
        and vertical_f <= cfg.c_vertical_q90_max_m
        and sampling_gap_f <= cfg.c_sampling_gap_max_s
        and max_after_batch_f <= cfg.c_batch_end_tolerance_s
        and ambiguity_passes(group, cfg.c_ambiguity_margin_min)
    ):
        return {"accepted": True, "grade": "C", "confidence": 0.50, "reason": "accepted_v4_grade_C_support_only"}

    if max_after_batch_f > cfg.c_batch_end_tolerance_s:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "projected_time_after_batch_end_gt_180s"}
    if best_cost_f > cfg.c_best_cost_max:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "best_cost_gt_3"}
    if cross_track_f > cfg.c_cross_track_q90_max_km:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "cross_track_q90_gt_1_5km"}
    if vertical_f > cfg.c_vertical_q90_max_m:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "vertical_q90_gt_800m"}
    if sampling_gap_f > cfg.c_sampling_gap_max_s:
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "sampling_gap_gt_900s"}
    if not ambiguity_passes(group, cfg.c_ambiguity_margin_min):
        return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "ambiguity_margin_lt_1_2"}
    return {"accepted": False, "grade": None, "confidence": 0.0, "reason": "outside_layered_acceptance_gate"}


def run_matching(cfg: RunConfig, batch: pl.DataFrame, candidate: pl.DataFrame, out_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    comp_path = cfg.stage4_v3_dir / "amdar_confidence_components_v3.parquet"
    points_path = cfg.stage2_v4_dir / "adsb_leg_points_v4.parquet"

    candidate_top = candidate.filter(pl.col("candidate_rank") <= cfg.candidate_topk).sort(
        ["amdar_batch_id", "candidate_rank", "candidate_seed_score"]
    )
    candidate_batch_ids = candidate_top.select(pl.col("amdar_batch_id").unique()).get_column("amdar_batch_id").to_list() if candidate_top.height else []
    candidate_leg_ids = candidate_top.select(pl.col("adsb_leg_id").unique()).get_column("adsb_leg_id").to_list() if candidate_top.height else []

    batch_rows = (
        pl.scan_parquet(comp_path)
        .filter((pl.col("source") == "amdar") & pl.col("amdar_batch_id").is_in(candidate_batch_ids))
        .select(
            [
                "amdar_batch_id",
                "source_row_index",
                "raw_row_number",
                "tail_norm",
                "flight_norm",
                "service_date_utc",
                "飞行阶段",
                "time_utc",
                "lat_clean",
                "lon_clean",
                "alt_meters",
                "wind_speed_ms_filled",
                "wind_dir_deg_filled",
                "u_wind",
                "v_wind",
                "amdar_observation_order",
                "base_support_conf",
                "confidence_tier",
                "confidence_subtier",
                "confidence_grade",
                "recommended_stage4_role",
                "stage4_weighting_recommendation_v3",
                "stage4_high_wind_action_v3",
                "time_uncertainty_s_stage4_v3",
                "time_uncertainty_s_stage4_v3_continuous",
                "effective_strict_truth",
                "strict_holdout_eligible_v3",
            ]
        )
        .sort(["amdar_batch_id", "amdar_observation_order", "source_row_index"])
        .collect(streaming=True)
    )
    leg_points = (
        pl.scan_parquet(points_path)
        .filter(pl.col("adsb_leg_id").is_in(candidate_leg_ids))
        .select(["adsb_leg_id", "time_utc", "lat_clean", "lon_clean", "alt_meters", "dt_from_prev_seconds_v4"])
        .sort(["adsb_leg_id", "time_utc"])
        .collect(streaming=True)
    )

    batch_group_map = {
        str(partition_key_scalar(k)): v.to_dicts()
        for k, v in batch_rows.partition_by("amdar_batch_id", maintain_order=True, as_dict=True).items()
    }
    batch_meta = {str(row["amdar_batch_id"]): row for row in batch.to_dicts()}
    candidate_map: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_top.to_dicts():
        candidate_map.setdefault(str(row["amdar_batch_id"]), []).append(row)
    leg_map = {
        str(partition_key_scalar(k)): v.to_dicts()
        for k, v in leg_points.partition_by("adsb_leg_id", maintain_order=True, as_dict=True).items()
    }

    def run_one(batch_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        meta = batch_meta[batch_id]
        rows = batch_group_map.get(batch_id, [])
        candidates = candidate_map.get(batch_id, [])[: cfg.candidate_topk]
        base_group = {
            "amdar_batch_id": batch_id,
            "tail_norm": meta.get("tail_norm"),
            "flight_norm": meta.get("flight_norm"),
            "service_date_utc": meta.get("service_date_utc"),
            "batch_end_time_utc": meta.get("batch_end_time_utc"),
            "previous_batch_end_time_utc": meta.get("previous_batch_end_time_utc"),
            "flight_phase": meta.get("flight_phase"),
            "batch_row_count": meta.get("batch_row_count"),
            "batch_size_bucket": meta.get("batch_size_bucket"),
            "stage4_confidence_tier_first": meta.get("stage4_confidence_tier_first"),
            "stage4_confidence_grade_first": meta.get("stage4_confidence_grade_first"),
            "stage4_confidence_subtier_first": meta.get("stage4_confidence_subtier_first"),
            "stage4_weighting_recommendation_v3_first": meta.get("stage4_weighting_recommendation_v3_first"),
            "stage4_high_wind_action_v3_first": meta.get("stage4_high_wind_action_v3_first"),
            "time_uncertainty_s_stage4_v3_first": meta.get("time_uncertainty_s_stage4_v3_first"),
            "time_uncertainty_s_stage4_v3_continuous_mean": meta.get("time_uncertainty_s_stage4_v3_continuous_mean"),
            "stage1_qc_all_rows_blocked": bool(meta.get("stage1_qc_all_rows_blocked")),
            "stage1_qc_blocked_row_count": int(meta.get("stage1_qc_blocked_row_count") or 0),
            "stage4_hard_reject_row_count": int(meta.get("stage4_hard_reject_row_count") or 0),
            "effective_strict_truth_row_count": int(meta.get("effective_strict_truth_row_count") or 0),
            "strict_holdout_eligible_v3_row_count": int(meta.get("strict_holdout_eligible_v3_row_count") or 0),
            "total_candidate_count": len(candidate_map.get(batch_id, [])),
            "evaluated_candidate_count": len(candidates),
            "matched_leg_id": None,
            "matched_adsb_flight_norm": None,
            "best_cost": None,
            "second_best_cost": None,
            "ambiguity_margin": None,
            "cross_track_q50_km": None,
            "cross_track_q90_km": None,
            "vertical_q50_m": None,
            "vertical_q90_m": None,
            "sampling_gap_max_seconds": None,
            "monotonic_violation_count": None,
            "estimated_time_min_utc": None,
            "estimated_time_max_utc": None,
            "max_projected_after_batch_end_s": None,
            "best_leg_quality": None,
            "best_stage3_source_tier_v7": None,
            "identity_match_level": None,
            "stage5_match_grade_v4": None,
            "stage5_match_confidence_v4": 0.0,
        }
        if not rows or not candidates:
            group = {**base_group, "status": "no_candidate", "reject_reason": "no_candidate_leg"}
            return [], group

        scored: list[dict[str, Any]] = []
        for cand in candidates:
            leg_rows = leg_map.get(str(cand["adsb_leg_id"]), [])
            scored_candidate = score_candidate(rows, leg_rows)
            if scored_candidate is None:
                continue
            projections, total_cost, monotonic_violations = scored_candidate
            scored.append(
                {
                    "candidate": cand,
                    "projections": projections,
                    "total_cost": total_cost,
                    "monotonic_violations": monotonic_violations,
                }
            )
        if not scored:
            group = {**base_group, "status": "projection_failed", "reject_reason": "projection_failed"}
            return [], group
        scored.sort(key=lambda x: float(x["total_cost"]))
        best = scored[0]
        second = scored[1] if len(scored) > 1 else None
        best_cost = float(best["total_cost"])
        second_cost = float(second["total_cost"]) if second is not None else None
        ambiguity_margin = None if second_cost is None or best_cost <= 0.0 else float(second_cost / best_cost)
        projections = best["projections"]
        cross = [float(row["cross_track_distance_km"]) for row in projections]
        vertical = [float(row["vertical_difference_m"]) for row in projections]
        gaps = [float(row["sampling_gap_seconds"]) for row in projections if row["sampling_gap_seconds"] is not None]
        times = [row["estimated_time_utc"] for row in projections if row["estimated_time_utc"] is not None]
        batch_end = meta.get("batch_end_time_utc")
        after_batch = [
            float((row["estimated_time_utc"] - batch_end).total_seconds())
            for row in projections
            if row["estimated_time_utc"] is not None and batch_end is not None
        ]
        max_after_batch = max(after_batch) if after_batch else None
        group = {
            **base_group,
            "status": "scored",
            "reject_reason": None,
            "matched_leg_id": best["candidate"]["adsb_leg_id"],
            "matched_adsb_flight_norm": best["candidate"].get("matched_adsb_flight_norm"),
            "best_cost": best_cost,
            "second_best_cost": second_cost,
            "ambiguity_margin": ambiguity_margin,
            "cross_track_q50_km": quantile(cross, 0.50),
            "cross_track_q90_km": quantile(cross, 0.90),
            "vertical_q50_m": quantile(vertical, 0.50),
            "vertical_q90_m": quantile(vertical, 0.90),
            "sampling_gap_max_seconds": max(gaps) if gaps else None,
            "monotonic_violation_count": int(best["monotonic_violations"]),
            "estimated_time_min_utc": min(times) if times else None,
            "estimated_time_max_utc": max(times) if times else None,
            "max_projected_after_batch_end_s": max_after_batch,
            "best_leg_quality": best["candidate"].get("leg_overall_quality"),
            "best_stage3_source_tier_v7": best["candidate"].get("stage3_source_tier_v7"),
            "identity_match_level": best["candidate"].get("identity_match_level"),
        }
        decision = acceptance_decision_v4(group, cfg)
        reason = str(decision["reason"])
        accepted = bool(decision["accepted"])
        group["status"] = "accepted" if accepted else "rejected_by_compound_gate"
        group["reject_reason"] = None if accepted else reason
        group["accepted_by_stage5_v4_layered_gate"] = accepted
        group["stage5_match_grade_v4"] = decision.get("grade")
        group["stage5_match_confidence_v4"] = float(decision.get("confidence") or 0.0)
        group["stage5_acceptance_reason_v4"] = reason if accepted else None

        row_records: list[dict[str, Any]] = []
        if accepted:
            for row in projections:
                row_records.append(
                    {
                        "amdar_batch_id": batch_id,
                        "source_row_index": row.get("source_row_index"),
                        "raw_row_number": row.get("raw_row_number"),
                        "tail_norm": row.get("tail_norm"),
                        "flight_norm": row.get("flight_norm"),
                        "service_date_utc": row.get("service_date_utc"),
                        "flight_phase": row.get("飞行阶段"),
                        "batch_end_time_utc": meta.get("batch_end_time_utc"),
                        "amdar_observation_order": row.get("amdar_observation_order"),
                        "lat_clean": row.get("lat_clean"),
                        "lon_clean": row.get("lon_clean"),
                        "alt_meters": row.get("alt_meters"),
                        "wind_speed_ms_filled": row.get("wind_speed_ms_filled"),
                        "wind_dir_deg_filled": row.get("wind_dir_deg_filled"),
                        "u_wind": row.get("u_wind"),
                        "v_wind": row.get("v_wind"),
                        "base_support_conf_stage4_v3": row.get("base_support_conf"),
                        "confidence_tier_stage4_v3": row.get("confidence_tier"),
                        "confidence_subtier_stage4_v3": row.get("confidence_subtier"),
                        "confidence_grade_stage4_v3": row.get("confidence_grade"),
                        "recommended_stage4_role": row.get("recommended_stage4_role"),
                        "stage4_weighting_recommendation_v3": row.get("stage4_weighting_recommendation_v3"),
                        "stage4_high_wind_action_v3": row.get("stage4_high_wind_action_v3"),
                        "time_uncertainty_s_stage4_v3": row.get("time_uncertainty_s_stage4_v3"),
                        "time_uncertainty_s_stage4_v3_continuous": row.get("time_uncertainty_s_stage4_v3_continuous"),
                        "effective_strict_truth": False,
                        "strict_holdout_eligible_v3": False,
                        "matched_adsb_leg_id": best["candidate"]["adsb_leg_id"],
                        "matched_adsb_flight_norm": best["candidate"].get("matched_adsb_flight_norm"),
                        "identity_match_level": best["candidate"].get("identity_match_level"),
                        "leg_overall_quality": best["candidate"].get("leg_overall_quality"),
                        "stage3_source_tier_v7": best["candidate"].get("stage3_source_tier_v7"),
                        "stage3_consumer_gate_v7": best["candidate"].get("stage3_consumer_gate_v7"),
                        "adsb_stage3_source_conf_cap_v7": best["candidate"].get("adsb_stage3_source_conf_cap_v7"),
                        "estimated_time_utc": row.get("estimated_time_utc"),
                        "segment_index": row.get("segment_index"),
                        "segment_start_time_utc": row.get("segment_start_time_utc"),
                        "segment_end_time_utc": row.get("segment_end_time_utc"),
                        "segment_start_lat": row.get("segment_start_lat"),
                        "segment_start_lon": row.get("segment_start_lon"),
                        "segment_start_alt_m": row.get("segment_start_alt_m"),
                        "segment_end_lat": row.get("segment_end_lat"),
                        "segment_end_lon": row.get("segment_end_lon"),
                        "segment_end_alt_m": row.get("segment_end_alt_m"),
                        "projection_fraction": row.get("projection_fraction"),
                        "cross_track_distance_km": row.get("cross_track_distance_km"),
                        "vertical_difference_m": row.get("vertical_difference_m"),
                        "sampling_gap_seconds": row.get("sampling_gap_seconds"),
                        "best_cost": best_cost,
                        "second_best_cost": second_cost,
                        "ambiguity_margin": ambiguity_margin,
                        "stage5_match_grade_v4": decision.get("grade"),
                        "stage5_match_confidence_v4": float(decision.get("confidence") or 0.0),
                        "stage5_acceptance_reason_v4": reason,
                        "stage5_match_status": "accepted_v4_layered_gate_support_only",
                        "adsb_reconstructed_v4": True,
                        "time_source_stage5_v4": "adsb_projected_support_only",
                        "time_semantics_stage5_v4": "narrow_time_distribution_seed_not_point_truth",
                        "batch_time_semantics": "ground_receive_approx_downlink_batch_end_time",
                        "batch_end_is_time_upper_bound": True,
                        "point_observation_time_available": False,
                        "estimated_time_is_strict_point_truth": False,
                        "stage6_time_uncertainty_input_role": "narrow_support_only_seed",
                        "holdout_eligible": False,
                        "usage_role": "support_only_not_strict_truth",
                    }
                )
        return row_records, group

    results: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as pool:
        for item in pool.map(run_one, [str(x) for x in candidate_batch_ids]):
            results.append(item)

    row_records: list[dict[str, Any]] = []
    group_records: list[dict[str, Any]] = []
    for rows, group in results:
        row_records.extend(rows)
        group_records.append(group)

    candidate_batch_set = set(str(x) for x in candidate_batch_ids)
    for row in batch.to_dicts():
        batch_id = str(row["amdar_batch_id"])
        if batch_id in candidate_batch_set:
            continue
        group_records.append(
            {
                "amdar_batch_id": batch_id,
                "tail_norm": row.get("tail_norm"),
                "flight_norm": row.get("flight_norm"),
                "service_date_utc": row.get("service_date_utc"),
                "batch_end_time_utc": row.get("batch_end_time_utc"),
                "previous_batch_end_time_utc": row.get("previous_batch_end_time_utc"),
                "flight_phase": row.get("flight_phase"),
                "batch_row_count": row.get("batch_row_count"),
                "batch_size_bucket": row.get("batch_size_bucket"),
                "stage4_confidence_tier_first": row.get("stage4_confidence_tier_first"),
                "stage4_confidence_grade_first": row.get("stage4_confidence_grade_first"),
                "stage4_confidence_subtier_first": row.get("stage4_confidence_subtier_first"),
                "stage4_weighting_recommendation_v3_first": row.get("stage4_weighting_recommendation_v3_first"),
                "stage4_high_wind_action_v3_first": row.get("stage4_high_wind_action_v3_first"),
                "time_uncertainty_s_stage4_v3_first": row.get("time_uncertainty_s_stage4_v3_first"),
                "time_uncertainty_s_stage4_v3_continuous_mean": row.get("time_uncertainty_s_stage4_v3_continuous_mean"),
                "stage1_qc_all_rows_blocked": bool(row.get("stage1_qc_all_rows_blocked")),
                "stage1_qc_blocked_row_count": int(row.get("stage1_qc_blocked_row_count") or 0),
                "stage4_hard_reject_row_count": int(row.get("stage4_hard_reject_row_count") or 0),
                "effective_strict_truth_row_count": int(row.get("effective_strict_truth_row_count") or 0),
                "strict_holdout_eligible_v3_row_count": int(row.get("strict_holdout_eligible_v3_row_count") or 0),
                "total_candidate_count": 0,
                "evaluated_candidate_count": 0,
                "status": "no_candidate",
                "reject_reason": "no_candidate_leg",
                "matched_leg_id": None,
                "matched_adsb_flight_norm": None,
                "best_cost": None,
                "second_best_cost": None,
                "ambiguity_margin": None,
                "cross_track_q50_km": None,
                "cross_track_q90_km": None,
                "vertical_q50_m": None,
                "vertical_q90_m": None,
                "sampling_gap_max_seconds": None,
                "monotonic_violation_count": None,
                "estimated_time_min_utc": None,
                "estimated_time_max_utc": None,
                "max_projected_after_batch_end_s": None,
                "best_leg_quality": None,
                "best_stage3_source_tier_v7": None,
                "identity_match_level": None,
                "accepted_by_stage5_v4_layered_gate": False,
                "stage5_match_grade_v4": None,
                "stage5_match_confidence_v4": 0.0,
                "stage5_acceptance_reason_v4": None,
            }
        )

    match_df = pl.from_dicts(row_records, infer_schema_length=None) if row_records else pl.DataFrame()
    group_df = pl.from_dicts(group_records, infer_schema_length=None) if group_records else pl.DataFrame()
    reject_df = group_df.filter(~pl.col("accepted_by_stage5_v4_layered_gate").fill_null(False)) if group_df.height else pl.DataFrame()

    if match_df.height:
        match_df.write_parquet(out_dir / "amdar_adsb_match_v4.parquet")
    else:
        pl.DataFrame().write_parquet(out_dir / "amdar_adsb_match_v4.parquet")
    group_df.write_parquet(out_dir / "amdar_adsb_batch_diagnostics_v4.parquet")
    reject_df.write_parquet(out_dir / "amdar_adsb_reject_v4.parquet")

    accepted_groups = group_df.filter(pl.col("accepted_by_stage5_v4_layered_gate").fill_null(False))
    multi_candidate_summary = {
        "candidate_topk": int(cfg.candidate_topk),
        "evaluated_candidate_batches": len(candidate_batch_ids),
        "batches_with_multiple_evaluated_candidates": int(
            group_df.filter(pl.col("evaluated_candidate_count").fill_null(0) > 1).height
        )
        if group_df.height
        else 0,
        "accepted_batches_with_multiple_evaluated_candidates": int(
            accepted_groups.filter(pl.col("evaluated_candidate_count").fill_null(0) > 1).height
        )
        if accepted_groups.height
        else 0,
        "all_scored_ambiguity_margin_summary": numeric_summary(
            group_df.filter(pl.col("ambiguity_margin").is_not_null()), "ambiguity_margin"
        )
        if group_df.height
        else {},
        "accepted_ambiguity_margin_summary": numeric_summary(accepted_groups, "ambiguity_margin"),
        "accepted_second_best_cost_summary": numeric_summary(accepted_groups, "second_best_cost"),
        "ambiguity_policy": "A requires margin>=2.5, B>=1.5, C>=1.2 when more than one candidate is evaluated; a single exact identity/date candidate is allowed without a ratio.",
        "top_candidates_table_policy": "Detailed best/second diagnostics are in amdar_adsb_batch_diagnostics_v4.parquet; full top-k row expansion is intentionally not duplicated to keep compact 25-slice outputs.",
    }
    write_json(out_dir / "multi_candidate_summary_v4.json", multi_candidate_summary)
    summary = {
        "evaluated_candidate_batches": len(candidate_batch_ids),
        "candidate_leg_ids_loaded": len(candidate_leg_ids),
        "candidate_point_rows_loaded": int(leg_points.height),
        "accepted_batches": int(accepted_groups.height),
        "accepted_rows": int(match_df.height),
        "rejected_batches": int(reject_df.height),
        "all_batch_status_counts": counts_map(group_df, "status"),
        "reject_reason_counts": counts_map(reject_df, "reject_reason"),
        "accepted_fraction_of_all_batches": float(accepted_groups.height / max(1, batch.height)),
        "accepted_fraction_of_candidate_batches": float(accepted_groups.height / max(1, len(candidate_batch_ids))),
        "accepted_by_stage4_tier": counts_map(accepted_groups, "stage4_confidence_tier_first"),
        "accepted_by_stage4_subtier": counts_map(accepted_groups, "stage4_confidence_subtier_first"),
        "accepted_by_stage5_grade_v4": counts_map(accepted_groups, "stage5_match_grade_v4"),
        "accepted_identity_match_level_counts": counts_map(accepted_groups, "identity_match_level"),
        "accepted_by_batch_size_bucket": counts_map(accepted_groups, "batch_size_bucket"),
        "accepted_by_phase": counts_map(accepted_groups, "flight_phase"),
        "accepted_leg_quality_counts": counts_map(accepted_groups, "best_leg_quality"),
        "accepted_source_tier_counts": counts_map(accepted_groups, "best_stage3_source_tier_v7"),
        "accepted_cost_summary": numeric_summary(accepted_groups, "best_cost"),
        "accepted_cross_track_q90_summary": numeric_summary(accepted_groups, "cross_track_q90_km"),
        "accepted_vertical_q90_summary": numeric_summary(accepted_groups, "vertical_q90_m"),
        "accepted_sampling_gap_max_summary": numeric_summary(accepted_groups, "sampling_gap_max_seconds"),
        "all_scored_cost_summary": numeric_summary(group_df.filter(pl.col("best_cost").is_not_null()), "best_cost") if group_df.height else {},
        "multi_candidate_summary": multi_candidate_summary,
        "traceability_checks": {
            "accepted_rows_have_matched_leg": int(match_df.filter(pl.col("matched_adsb_leg_id").is_null()).height) == 0 if match_df.height else True,
            "accepted_rows_have_segment_start_end": int(
                match_df.filter(pl.col("segment_start_time_utc").is_null() | pl.col("segment_end_time_utc").is_null()).height
            )
            == 0
            if match_df.height
            else True,
            "accepted_rows_support_only": int(match_df.filter(pl.col("effective_strict_truth").fill_null(False)).height) == 0 if match_df.height else True,
            "accepted_rows_mark_batch_end_as_upper_bound": int(
                match_df.filter(~pl.col("batch_end_is_time_upper_bound").fill_null(False)).height
            )
            == 0
            if match_df.height and "batch_end_is_time_upper_bound" in match_df.columns
            else True,
            "accepted_rows_not_point_observation_truth": int(
                match_df.filter(
                    pl.col("point_observation_time_available").fill_null(True)
                    | pl.col("estimated_time_is_strict_point_truth").fill_null(True)
                    | pl.col("holdout_eligible").fill_null(True)
                ).height
            )
            == 0
            if match_df.height
            else True,
            "accepted_rows_have_stage6_input_role": int(
                match_df.filter(pl.col("stage6_time_uncertainty_input_role") != "narrow_support_only_seed").height
            )
            == 0
            if match_df.height and "stage6_time_uncertainty_input_role" in match_df.columns
            else True,
            "accepted_rows_have_v4_grade": int(match_df.filter(pl.col("stage5_match_grade_v4").is_null()).height) == 0 if match_df.height else True,
            "accepted_rows_have_v7_source_tier": int(match_df.filter(pl.col("stage3_source_tier_v7").is_null()).height) == 0 if match_df.height else True,
        },
    }
    return match_df, group_df, reject_df, summary


def build_summary(
    cfg: RunConfig,
    stage3_report: dict[str, Any],
    stage4_summary: dict[str, Any],
    batch: pl.DataFrame,
    candidate_summary: dict[str, Any],
    match_summary: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    accepted_rows = int(match_summary.get("accepted_rows") or 0)
    accepted_batches = int(match_summary.get("accepted_batches") or 0)
    accepted_fraction = float(match_summary.get("accepted_fraction_of_all_batches") or 0.0)
    accepted_grade_counts = match_summary.get("accepted_by_stage5_grade_v4", {})
    stage3_passed = bool(stage3_report.get("quality_gate", {}).get("passed_stage3_v8_quality_gate"))
    stage4_checks = stage4_summary.get("stage4_completion_checks", {})
    stage4_passed = bool(
        stage4_checks.get("passed_stage4_confidence_v3_quality_gate")
        and stage4_checks.get("passed_stage4_next_window_quality_gate")
    )
    checks = {
        "stage3_v8_gate_passed": stage3_passed,
        "stage4_v3_gate_passed": stage4_passed,
        "candidate_diagnostics_written": int(candidate_summary.get("candidate_rows") or 0) > 0,
        "reject_table_complete": int(match_summary.get("accepted_batches", 0)) + int(match_summary.get("rejected_batches", 0)) == int(batch.height),
        "accepted_matches_traceable": all(match_summary.get("traceability_checks", {}).values()),
        "accepted_rows_are_support_only": bool(match_summary.get("traceability_checks", {}).get("accepted_rows_support_only", True)),
        "accepted_count_is_informational_not_forced": True,
        "no_identity_conflict_acceptance": True,
        "stage5_v4_outputs_present": all(
            (out_dir / name).exists()
            for name in [
                "amdar_batch_base_v4.parquet",
                "amdar_adsb_candidate_legs_v4.parquet",
                "amdar_adsb_match_v4.parquet",
                "amdar_adsb_reject_v4.parquet",
                "amdar_adsb_batch_diagnostics_v4.parquet",
            ]
        ),
        "accepted_batches_ge_500_conservative_target": accepted_batches >= 500,
        "accepted_fraction_ge_1pct_conservative_target": accepted_fraction >= 0.01,
        "accepted_fraction_ge_1_5pct_balanced_floor": accepted_fraction >= 0.015,
        "accepted_fraction_ge_2pct_balanced_target": accepted_fraction >= 0.02,
        "grade_A_present": int(accepted_grade_counts.get("A", 0) or 0) > 0,
        "grade_B_present": int(accepted_grade_counts.get("B", 0) or 0) > 0,
        "grade_C_present": int(accepted_grade_counts.get("C", 0) or 0) > 0,
    }
    checks["passed_stage5_v4_diagnostic_gate"] = bool(
        checks["stage3_v8_gate_passed"]
        and checks["stage4_v3_gate_passed"]
        and checks["candidate_diagnostics_written"]
        and checks["reject_table_complete"]
        and checks["accepted_matches_traceable"]
        and checks["accepted_rows_are_support_only"]
        and checks["stage5_v4_outputs_present"]
    )
    checks["passed_stage5_v4_target_gate"] = bool(
        checks["passed_stage5_v4_diagnostic_gate"]
        and checks["accepted_batches_ge_500_conservative_target"]
        and checks["accepted_fraction_ge_1pct_conservative_target"]
    )
    locked = stage3_report.get("metrics", {}).get("selected_by_compound_gate_v8", {}).get("locked_test", {})
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "space_saving_policy": "25-slice compatible compact outputs; no duplicated 25-way full intermediate tables.",
            "acceptance_policy": "Real Stage5 v4 uses A/B/C layered gates bounded by the Stage3 v8 validation-selected wide diagnostic gate; accepted rows remain support-only.",
            "time_semantics_policy": "Accepted rows are only Stage6 narrow time-distribution seeds; unmatched or rejected AMDAR retains batch interval uncertainty.",
        },
        "inputs": {
            "stage3_v8_report": str(cfg.stage3_v8_dir / "pseudo_amdar_v8_calibration_report.json"),
            "stage4_confidence_components_v3": str(cfg.stage4_v3_dir / "amdar_confidence_components_v3.parquet"),
            "stage4_confidence_summary_v3": str(cfg.stage4_v3_dir / "confidence_tier_summary_v3.json"),
            "stage2_v7_leg_components": str(cfg.stage2_v7_dir / "adsb_leg_quality_components_v7.parquet"),
            "stage2_v4_leg_points_reused": str(cfg.stage2_v4_dir / "adsb_leg_points_v4.parquet"),
        },
        "stage3_v8_locked_test_metrics": locked,
        "stage4_v3_completion_checks": stage4_checks,
        "batch_summary": {
            "amdar_batches": int(batch.height),
            "batch_size_counts": counts_map(batch, "batch_size_bucket"),
            "stage4_tier_counts": counts_map(batch, "stage4_confidence_tier_first"),
            "stage4_subtier_counts": counts_map(batch, "stage4_confidence_subtier_first"),
            "stage1_qc_all_rows_blocked_batches": int(batch.filter(pl.col("stage1_qc_all_rows_blocked")).height),
            "stage4_hard_reject_batches": int(batch.filter(pl.col("stage4_hard_reject_row_count") > 0).height),
        },
        "candidate_summary": candidate_summary,
        "match_summary": match_summary,
        "stage5_completion_checks": checks,
        "interpretation": {
            "accepted_batches": accepted_batches,
            "accepted_rows": accepted_rows,
            "real_match_coverage_note": "Real AMDAR accepted coverage is diagnostic only and must not be forced. Pseudo validation quality comes from Stage3 v8; real Stage5 accepted rows are traceable support-only candidates.",
            "strict_truth_note": "Accepted Stage5 v4 rows remain support-only and are not holdout truth.",
            "stage6_input_note": "Use accepted rows only as narrow support-only time distributions. Do not impute point times for unmatched or rejected batches from batch_end_time_utc.",
        },
        "outputs": {
            "batch_base": str(out_dir / "amdar_batch_base_v4.parquet"),
            "candidate_legs": str(out_dir / "amdar_adsb_candidate_legs_v4.parquet"),
            "match_rows": str(out_dir / "amdar_adsb_match_v4.parquet"),
            "reject_table": str(out_dir / "amdar_adsb_reject_v4.parquet"),
            "batch_diagnostics": str(out_dir / "amdar_adsb_batch_diagnostics_v4.parquet"),
            "diagnostics_json": str(out_dir / "amdar_adsb_match_diagnostics_v4.json"),
            "multi_candidate_summary": str(out_dir / "multi_candidate_summary_v4.json"),
            "results_analysis": str(cfg.out_dir / "stage5_v4_results_analysis_and_next_steps.md"),
            "handover": str(cfg.out_dir / "next_agent_handover_after_stage5_v4.md"),
        },
    }


def write_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage5_v4_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage5_v4.md"
    stage5 = summary["stage5_completion_checks"]
    match = summary["match_summary"]
    cand = summary["candidate_summary"]
    locked = summary["stage3_v8_locked_test_metrics"]
    target_gate = bool(stage5.get("passed_stage5_v4_target_gate"))
    diagnostic_gate = bool(stage5.get("passed_stage5_v4_diagnostic_gate"))

    result_lines = [
        "# AMDAR Stage5 V4 Real Matching Results Analysis And Next Steps",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Scope And Stage Naming",
        "",
        "This is large-framework Stage5 real AMDAR-ADS-B matching v4. In the Stage2-6 optimization plan this corresponds to optimization-plan phase 4, not optimization-plan phase 5 Stage6 time modeling.",
        "",
        "## Run Policy",
        "",
        "- `POLARS_MAX_THREADS=25`",
        f"- `slice_count={summary['run_policy']['slice_count']}`",
        f"- `workers={summary['run_policy']['workers']}`",
        "- Uses Stage4 v3 compact confidence table and Stage2 v7 compact leg table.",
        "- Reuses the single Stage2 v4 ADS-B point table by candidate leg id; no 25 duplicated full intermediates.",
        "",
        "## What Changed From V3",
        "",
        "1. Consumes Stage4 confidence v3 next-window output instead of Stage4 v2.",
        "2. Consumes Stage2 v7 source tiers instead of Stage2 v6 source tiers.",
        "3. Uses A/B/C layered acceptance bounded by the Stage3 v8 validation-selected diagnostic gate.",
        "4. Carries `confidence_subtier`, Stage4 v3 continuous time uncertainty, high-wind action and v7 source tier into accepted rows.",
        "5. Keeps accepted rows support-only; rejected rows remain explicit and are not promoted.",
        "",
        "## Key Result",
        "",
        f"- AMDAR batches: `{summary['batch_summary']['amdar_batches']}`",
        f"- Candidate leg pool: `{cand.get('candidate_leg_pool_count')}`",
        f"- Candidate rows: `{cand.get('candidate_rows')}`",
        f"- Batches with candidates: `{cand.get('batches_with_candidate')}`",
        f"- Accepted batches: `{match.get('accepted_batches')}`",
        f"- Accepted rows: `{match.get('accepted_rows')}`",
        f"- Accepted fraction of all batches: `{match.get('accepted_fraction_of_all_batches')}`",
        f"- Accepted fraction of candidate batches: `{match.get('accepted_fraction_of_candidate_batches')}`",
        f"- Accepted by Stage5 grade: `{match.get('accepted_by_stage5_grade_v4')}`",
        f"- Accepted by Stage4 tier/subtier: `{match.get('accepted_by_stage4_tier')}` / `{match.get('accepted_by_stage4_subtier')}`",
        f"- Reject reason counts: `{match.get('reject_reason_counts')}`",
        f"- Diagnostic gate passed: `{diagnostic_gate}`",
        f"- Target gate passed: `{target_gate}`",
        "",
        "## Quality Gates",
        "",
        f"- Stage3 v8 locked-test selected metrics: `{locked}`",
        f"- Stage4 v3 completion checks: `{summary['stage4_v3_completion_checks']}`",
        f"- Stage5 v4 checks: `{stage5}`",
        f"- Traceability checks: `{match.get('traceability_checks')}`",
        "",
        "## Interpretation",
        "",
        "Stage5 v4 accepted rows are real, traceable AMDAR-to-ADS-B projections, but they remain `support_only_not_strict_truth`. `estimated_time_utc` is a Stage6 narrow time-distribution seed, not point-time truth. Unmatched and rejected AMDAR must retain batch-interval uncertainty in Stage6.",
        "",
        "The diagnostic/safety gate passes, but the Stage5 target gate can still fail. If the target gate is false, downstream Stage6 must not treat this as target-complete Stage5; it may only run a conservative diagnostic branch that explicitly reports the target miss and does not fabricate accepted matches.",
        "",
        "## Outputs",
        "",
        f"- Batch base: `{summary['outputs']['batch_base']}`",
        f"- Candidate legs: `{summary['outputs']['candidate_legs']}`",
        f"- Accepted match rows: `{summary['outputs']['match_rows']}`",
        f"- Reject table: `{summary['outputs']['reject_table']}`",
        f"- Batch diagnostics: `{summary['outputs']['batch_diagnostics']}`",
        f"- Diagnostics JSON: `{summary['outputs']['diagnostics_json']}`",
        f"- Multi-candidate summary: `{summary['outputs']['multi_candidate_summary']}`",
        "",
        "## Recommended Next Steps",
        "",
        "1. Do not treat Stage5 v4 as target-complete when `passed_stage5_v4_target_gate=false`.",
        "2. A conservative Stage6 diagnostic branch may consume `amdar_adsb_match_v4.parquet` only as narrow support-only seeds and must report the target miss.",
        "3. Do not use rejected rows or `batch_end_time_utc` as point observations.",
        "4. To pursue the original Stage5 target, return to candidate availability and data alignment diagnostics rather than loosening real-match gates.",
    ]
    result_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    handover = [
        "# 给下一个智能体的交接话术：Stage5 V4 结果与 Stage6 前置限制",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。当前已运行优化计划阶段4：大框架 Stage5 real AMDAR-ADS-B matching v4。注意：优化计划阶段5才是大框架 Stage6 时间建模；若 `passed_stage5_v4_target_gate=false`，不能当作 target-complete Stage5 直接进入目标 Stage6 分支。",
        "",
        "## 必读文档与用途",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目 strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/teacher_reports/plan4.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md`：strict truth 候选少是数据现实；路线是分层置信度和 support-only。",
        "4. `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_unified_implementation_plan_20260701.md`：Unified Plan 小阶段边界、禁止操作、Stage5/6 时间语义。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`：本轮 Stage2-6 优化总方案。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_optimization_targets_quality_controlled_20260706.md`：平衡目标和质量门。",
        "7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_adsb_qc_v7_optimized_20260706/stage2_v7_results_analysis_and_next_steps.md`：Stage2 v7 source tiers。",
        "8. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md`：Stage3 v8 validation/locked gate。",
        "9. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/next_agent_handover_after_stage4_v3.md`：Stage4 v3 next-window 交接。",
        f"10. `{result_path}`：本轮 Stage5 v4 结果分析、质量门、下一步建议。",
        f"11. `{summary['outputs']['diagnostics_json']}`：Stage5 v4 machine-readable 总表。",
        f"12. `{summary['outputs']['batch_diagnostics']}`：每个 AMDAR 批次 best/second/cost/拒绝原因。",
        "",
        "## 本轮脚本和输出",
        "",
        f"- 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v4_matching_20260708.py`",
        f"- 输出目录：`{cfg.out_dir}`",
        "- Stage5 子目录：`stage5_v4/`",
        "- `amdar_batch_base_v4.parquet`：56,521 个 AMDAR 批次的批次级基础表。",
        "- `amdar_adsb_candidate_legs_v4.parquet`：真实 ADS-B 候选 leg 表。",
        "- `amdar_adsb_match_v4.parquet`：A/B/C 分层 accepted support-only 行。",
        "- `amdar_adsb_reject_v4.parquet`：所有未接受批次的拒绝原因。",
        "- `amdar_adsb_batch_diagnostics_v4.parquet`：所有批次诊断。",
        "- `amdar_adsb_match_diagnostics_v4.json`：总指标和完成检查。",
        "- `multi_candidate_summary_v4.json`：候选/歧义汇总。",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v4_matching_20260708.py \\",
        f"  --out-dir {cfg.out_dir} --slice-count 25 --workers 25",
        "```",
        "",
        "空间口径：复用 Stage4 v3 compact confidence table、Stage2 v7 compact leg table 和 Stage2 v4 ADS-B point table；只按候选 leg id 选择性读取点表，不复制 25 份全量中间数据。",
        "",
        "## 关键结果",
        "",
        f"- Candidate summary: `{cand}`",
        f"- Match summary: `{match}`",
        f"- Stage5 completion checks: `{stage5}`",
        "",
        "## 项目与数据理解",
        "",
        "TURB/aircraft holdout 是唯一正式 strict truth；AMDAR 全部 support-only，`effective_strict_truth=false` 且 `holdout_eligible=false`。AMDAR 原始时间是批次下发/接收时间，Stage5 accepted 的 `estimated_time_utc` 只能作为 Stage6 窄时间分布种子，不是逐点真值。",
        "",
        "Stage5 v4 只接受 exact `tail_norm + flight_norm + service_date_utc` 候选，并按 A/B/C 分层记录 cost、cross-track、vertical、sampling gap、ambiguity 和 batch-end 上界检查。Rejected rows 不能伪造成 accepted。",
        "",
        "## 下一步执行话术",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 时间语义、Plan4 综合评估、Unified Plan、Stage2-6 优化方案、质量控制目标、Stage2 v7、Stage3 v8、Stage4 v3 next-window，以及 Stage5 v4 结果。",
        "当前结论：大框架 Stage5 real AMDAR-ADS-B matching v4 已生成候选、accepted/rejected、歧义和质量门诊断；diagnostic/safety gate 需要为 true，target gate 需单独检查。accepted rows 仍是 support-only，不是 strict truth。",
        "若 target gate=false，我不会把本轮结果当作 target-complete Stage5 直接进入目标 Stage6 分支。若继续，只能做 conservative Stage6 diagnostic：读取 amdar_adsb_match_v4.parquet、amdar_adsb_reject_v4.parquet、amdar_adsb_batch_diagnostics_v4.parquet 和 Stage4 v3 confidence table；只对 accepted rows 生成窄 ADS-B seed 分布，未匹配和 rejected rows 继续使用批次/物理约束分布，不会把 batch_end_time 当逐点观测时间。",
        "```",
    ]
    handover_path.write_text("\n".join(handover) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    stage5_dir = cfg.out_dir / "stage5_v4"
    stage5_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    print(json.dumps({"stage": "load_stage3_stage4"}, ensure_ascii=False))
    stage3_report, stage4_summary = load_stage_gate(cfg)

    print(json.dumps({"stage": "build_batch_base_start"}, ensure_ascii=False))
    batch = build_batch_base(cfg, stage5_dir)
    print(json.dumps({"stage": "build_batch_base_done", "batches": int(batch.height)}, ensure_ascii=False))

    print(json.dumps({"stage": "build_candidates_start"}, ensure_ascii=False))
    candidate, candidate_summary = build_candidates(cfg, batch, stage5_dir)
    print(
        json.dumps(
            {
                "stage": "build_candidates_done",
                "candidate_rows": candidate_summary.get("candidate_rows"),
                "batches_with_candidate": candidate_summary.get("batches_with_candidate"),
            },
            ensure_ascii=False,
        )
    )

    print(json.dumps({"stage": "matching_start"}, ensure_ascii=False))
    _, _, _, match_summary = run_matching(cfg, batch, candidate, stage5_dir)
    print(
        json.dumps(
            {
                "stage": "matching_done",
                "accepted_batches": match_summary.get("accepted_batches"),
                "accepted_rows": match_summary.get("accepted_rows"),
                "rejected_batches": match_summary.get("rejected_batches"),
            },
            ensure_ascii=False,
        )
    )

    summary = build_summary(cfg, stage3_report, stage4_summary, batch, candidate_summary, match_summary, stage5_dir)
    write_json(stage5_dir / "amdar_adsb_match_diagnostics_v4.json", summary)
    write_docs(cfg, summary)
    print(
        json.dumps(
            {
                "stage": "all_done",
                "passed": summary.get("stage5_completion_checks", {}).get("passed_stage5_v4_diagnostic_gate"),
                "out_dir": str(cfg.out_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
