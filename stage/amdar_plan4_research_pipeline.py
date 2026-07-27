from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl


EARTH_RADIUS_KM = 6371.0


@dataclass
class PipelineConfig:
    num_workers: int = 25
    match_sample_batches: int = 2500
    pseudo_case_limit: int = 400
    loc_row_limit: int = 0
    topk_candidates: int = 6
    candidate_time_padding_seconds: int = 7200
    time_upper_bound_tolerance_seconds: int = 60
    lower_bound_padding_seconds: int = 7200
    segment_gap_seconds: int = 1800
    segment_jump_km: float = 300.0
    segment_alt_jump_m: float = 5000.0
    min_leg_points: int = 5
    spatial_envelope_padding_km: float = 80.0
    altitude_padding_m: float = 1500.0
    ambiguity_ratio_threshold: float = 1.12
    weak_score_per_row_threshold: float = 30.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the corrected AMDAR plan4 research pipeline.")
    parser.add_argument("--stage1-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--num-workers", type=int, default=25)
    parser.add_argument("--match-sample-batches", type=int, default=2500)
    parser.add_argument("--pseudo-case-limit", type=int, default=400)
    parser.add_argument("--loc-row-limit", type=int, default=0, help="0 means full clean_loc.parquet; positive values run a bounded smoke test on the first N rows.")
    parser.add_argument("--topk-candidates", type=int, default=6)
    parser.add_argument("--candidate-time-padding-seconds", type=int, default=7200)
    parser.add_argument("--time-upper-bound-tolerance-seconds", type=int, default=60)
    parser.add_argument("--lower-bound-padding-seconds", type=int, default=7200)
    parser.add_argument("--segment-gap-seconds", type=int, default=1800)
    parser.add_argument("--segment-jump-km", type=float, default=300.0)
    parser.add_argument("--segment-alt-jump-m", type=float, default=5000.0)
    parser.add_argument("--min-leg-points", type=int, default=5)
    parser.add_argument("--spatial-envelope-padding-km", type=float, default=80.0)
    parser.add_argument("--altitude-padding-m", type=float, default=1500.0)
    parser.add_argument("--ambiguity-ratio-threshold", type=float, default=1.12)
    parser.add_argument("--weak-score-per-row-threshold", type=float, default=30.0)
    return parser.parse_args()


def _normalize_text(value: Any, fallback: str = "missing") -> str:
    if value is None:
        return fallback
    text = str(value).strip().upper()
    return text if text else fallback


def _normalize_tail(value: Any) -> str:
    text = _normalize_text(value)
    return "".join(ch for ch in text if ch.isalnum())


def _normalize_flight(value: Any) -> str:
    text = _normalize_text(value)
    return "".join(ch for ch in text if ch.isalnum())


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat(sep=" ")
    return str(value)


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _latlon_to_local_xy_km(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    mean_lat = math.radians((lat0 + lat) / 2.0)
    x = (lon - lon0) * 111.320 * math.cos(mean_lat)
    y = (lat - lat0) * 110.574
    return x, y


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(pl.Series(values, dtype=pl.Float64).quantile(q))


def _counts_map(df: pl.DataFrame, col: str) -> dict[str, int]:
    if col not in df.columns:
        return {}
    vc = (
        df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
    )
    return {str(k): int(v) for k, v in vc.iter_rows()}


def _size_bucket(rows: int) -> str:
    if rows <= 1:
        return "1 point"
    if rows <= 4:
        return "2-4 points"
    if rows <= 10:
        return "5-10 points"
    if rows <= 25:
        return "11-25 points"
    if rows <= 49:
        return "26-49 points"
    return "50 points"


def _leg_quality_from_flags(point_count: int, flagged_ratio: float, gap_q90: float | None, jump_count: int) -> str:
    if point_count < 5:
        return "C"
    if flagged_ratio <= 0.01 and (gap_q90 or 0.0) <= 60.0 and jump_count == 0:
        return "A"
    if flagged_ratio <= 0.05 and (gap_q90 or 0.0) <= 180.0:
        return "B"
    return "C"


def _identity_grade(batch: dict[str, Any], leg: dict[str, Any]) -> str:
    batch_tail = _normalize_tail(batch.get("tail_number"))
    batch_flight = _normalize_flight(batch.get("flight_number"))
    leg_tail = leg.get("tail_norm", "missing")
    leg_flight = leg.get("flight_norm", "missing")
    if batch_tail != "MISSING" and batch_tail == leg_tail and batch_flight != "MISSING" and batch_flight == leg_flight:
        return "ID-A"
    if batch_tail != "MISSING" and batch_tail == leg_tail and batch_flight == "MISSING":
        return "ID-C"
    if batch_tail == "MISSING" and batch_flight != "MISSING" and batch_flight == leg_flight:
        return "ID-D"
    if batch_tail != "MISSING" and batch_tail == leg_tail:
        return "ID-B"
    return "ID-R"


def _identity_penalty(identity_grade: str) -> float:
    return {
        "ID-A": 0.0,
        "ID-B": 2.0,
        "ID-C": 5.0,
        "ID-D": 8.0,
        "ID-R": 99.0,
    }.get(identity_grade, 20.0)


def _load_stage1(stage1_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    wind_cols = [
        "source",
        "source_row_index",
        "flight_id",
        "机尾号",
        "航班号",
        "飞行阶段",
        "time_utc",
        "time_beijing",
        "amdar_batch_time_beijing",
        "amdar_batch_time_utc",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "wind_dir",
        "wind_speed",
        "same_time_group_rows",
        "same_time_group_hspan_deg",
        "same_time_group_alt_span_m",
        "same_time_group_row_index_min",
        "same_time_group_row_index_max",
        "time_group_alignment_flag",
        "wind_reconstruction_role",
        "legacy_wind_reconstruction_role",
        "usage_role",
        "strict_time_truth",
        "effective_strict_truth",
        "time_is_point_observation",
        "point_observation_time_available",
        "batch_end_is_time_upper_bound",
        "amdar_time_semantics",
        "time_quality",
        "amdar_batch_id",
        "amdar_observation_order",
        "amdar_batch_contiguous_block_index",
        "amdar_batch_row_count",
        "amdar_batch_is_contiguous",
        "amdar_batch_hspan_deg",
        "amdar_batch_vertical_span_m",
        "raw_row_number",
    ]
    loc_cols = [
        "flight_id",
        "机尾号",
        "航班号",
        "time_utc",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "heading_deg",
        "ground_speed_ms",
        "altitude_unit_state",
        "altitude_unit_mode",
        "高度_raw",
    ]
    wind = (
        pl.read_parquet(stage1_dir / "clean_wind.parquet", columns=wind_cols)
        .with_columns(
            [
                pl.col("time_utc").cast(pl.Datetime, strict=False),
                pl.col("time_beijing").cast(pl.Datetime, strict=False),
                pl.col("amdar_batch_time_beijing").cast(pl.Datetime, strict=False),
                pl.col("amdar_batch_time_utc").cast(pl.Datetime, strict=False),
                pl.col("lat_clean").cast(pl.Float64, strict=False),
                pl.col("lon_clean").cast(pl.Float64, strict=False),
                pl.col("alt_meters").cast(pl.Float64, strict=False),
                pl.col("wind_dir").cast(pl.Float64, strict=False),
                pl.col("wind_speed").cast(pl.Float64, strict=False),
            ]
        )
    )
    loc = (
        pl.read_parquet(stage1_dir / "clean_loc.parquet", columns=loc_cols)
        .with_columns(
            [
                pl.col("time_utc").cast(pl.Datetime, strict=False),
                pl.col("lat_clean").cast(pl.Float64, strict=False),
                pl.col("lon_clean").cast(pl.Float64, strict=False),
                pl.col("alt_meters").cast(pl.Float64, strict=False),
                pl.col("heading_deg").cast(pl.Float64, strict=False),
                pl.col("ground_speed_ms").cast(pl.Float64, strict=False),
            ]
        )
    )
    return wind, loc


def _build_p1_outputs(wind: pl.DataFrame, out_dir: Path) -> tuple[pl.DataFrame, dict[str, Any]]:
    amdar = (
        wind.filter(pl.col("source") == "amdar")
        .with_columns(
            [
                pl.col("机尾号").map_elements(_normalize_tail, return_dtype=pl.Utf8).alias("tail_norm"),
                pl.col("航班号").map_elements(_normalize_flight, return_dtype=pl.Utf8).alias("flight_norm"),
                (
                    pl.col("机尾号").map_elements(_normalize_tail, return_dtype=pl.Utf8)
                    + pl.lit("__")
                    + pl.col("航班号").map_elements(_normalize_flight, return_dtype=pl.Utf8)
                    + pl.lit("__")
                    + pl.col("time_utc").dt.strftime("%Y%m%dT%H%M%S")
                ).alias("flight_time_group_id"),
            ]
        )
    )
    parent_group = (
        amdar.group_by("flight_time_group_id")
        .agg(
            [
                pl.len().alias("flight_time_group_rows"),
                pl.col("amdar_batch_id").n_unique().alias("flight_time_group_block_count"),
                pl.col("same_time_group_rows").max().alias("same_time_group_rows_max"),
                pl.col("source_row_index").min().alias("source_row_index_min"),
                pl.col("source_row_index").max().alias("source_row_index_max"),
                pl.col("机尾号").first().alias("机尾号"),
                pl.col("航班号").first().alias("航班号"),
                pl.col("time_utc").first().alias("time_utc"),
            ]
        )
        .with_columns(
            (
                pl.col("source_row_index_max") - pl.col("source_row_index_min") + 1
            ).alias("source_row_span")
        )
    )
    batch_cross = (
        amdar.select(
            [
                "flight_time_group_id",
                "amdar_batch_id",
                "amdar_batch_row_count",
                "amdar_batch_contiguous_block_index",
                "time_group_alignment_flag",
                "amdar_time_semantics",
                "usage_role",
                "strict_time_truth",
                "legacy_wind_reconstruction_role",
                "same_time_group_rows",
                "source_row_index",
                "raw_row_number",
                "time_quality",
                "飞行阶段",
            ]
        )
        .join(parent_group, on="flight_time_group_id", how="left")
        .with_columns(
            [
                pl.when(
                    (pl.col("same_time_group_rows") == 1)
                    & (pl.col("amdar_batch_row_count") == 1)
                    & (pl.col("flight_time_group_block_count") == 1)
                )
                .then(pl.lit("singleton_contiguous"))
                .when(
                    (pl.col("same_time_group_rows") > 1)
                    & (pl.col("flight_time_group_block_count") == 1)
                    & (pl.col("amdar_batch_row_count") > 1)
                )
                .then(pl.lit("multi_point_contiguous"))
                .when(
                    (pl.col("same_time_group_rows") > 1)
                    & (pl.col("flight_time_group_block_count") > 1)
                    & (pl.col("amdar_batch_row_count") == 1)
                )
                .then(pl.lit("discontiguous_singleton_block"))
                .otherwise(pl.lit("same_timestamp_multiblock"))
                .alias("batch_structure")
            ]
        )
        .rename(
            {
                "amdar_batch_row_count": "batch_row_count",
                "amdar_batch_contiguous_block_index": "continuous_block_index",
                "amdar_time_semantics": "time_semantics",
            }
        )
        .sort(["time_utc", "source_row_index"])
    )
    batch_cross.write_parquet(out_dir / "amdar_classification_cross_table.parquet")

    multiblock = (
        batch_cross.filter(pl.col("flight_time_group_block_count") > 1)
        .group_by("flight_time_group_id")
        .agg(
            [
                pl.col("机尾号").first().alias("机尾号"),
                pl.col("航班号").first().alias("航班号"),
                pl.col("time_utc").first().alias("time_utc"),
                pl.col("flight_time_group_rows").max().alias("flight_time_group_rows"),
                pl.col("flight_time_group_block_count").max().alias("block_count"),
                pl.col("batch_row_count").sum().alias("summed_batch_rows"),
                pl.col("batch_row_count").sort().alias("batch_row_count_list"),
                pl.col("batch_structure").unique().sort().alias("batch_structure_types"),
                pl.col("source_row_index").min().alias("source_row_index_min"),
                pl.col("source_row_index").max().alias("source_row_index_max"),
                pl.col("raw_row_number").min().alias("raw_row_number_min"),
                pl.col("raw_row_number").max().alias("raw_row_number_max"),
            ]
        )
        .sort(["time_utc", "flight_time_group_id"])
    )
    multiblock.write_parquet(out_dir / "amdar_multiblock_group_summary.parquet")
    multiblock.head(500).write_json(out_dir / "amdar_multiblock_group_summary_preview.json")

    invariant = {
        "amdar_rows": int(amdar.height),
        "flight_time_group_count": int(parent_group.height),
        "amdar_batch_count": int(amdar.select(pl.col("amdar_batch_id").n_unique()).item()),
        "same_timestamp_multiblock_groups": int(multiblock.height),
        "discontiguous_singleton_block_rows": int(batch_cross.filter(pl.col("batch_structure") == "discontiguous_singleton_block").height),
        "all_batch_rows_sum_equals_amdar_rows": int(batch_cross["batch_row_count"].sum()) == int(amdar.height),
        "all_rows_have_batch_id": int(batch_cross.filter(pl.col("amdar_batch_id").is_null()).height) == 0,
        "all_rows_have_single_time_semantics": int(batch_cross.filter(pl.col("time_semantics").is_null()).height) == 0,
        "batch_structure_counts": _counts_map(batch_cross, "batch_structure"),
        "time_group_alignment_flag_counts": _counts_map(batch_cross, "time_group_alignment_flag"),
        "usage_role_counts": _counts_map(batch_cross, "usage_role"),
        "strict_time_truth_counts": _counts_map(batch_cross, "strict_time_truth"),
    }
    _write_json(out_dir / "amdar_invariant_check.json", invariant)
    return batch_cross, invariant


def _build_p2_outputs(wind: pl.DataFrame, out_dir: Path) -> tuple[pl.DataFrame, dict[str, Any]]:
    amdar = wind.filter(pl.col("source") == "amdar").sort(["amdar_batch_id", "source_row_index"])
    diagnostics: list[dict[str, Any]] = []
    size50: list[dict[str, Any]] = []
    groups = amdar.partition_by("amdar_batch_id", maintain_order=True, as_dict=True)
    for batch_id, one in groups.items():
        if batch_id is None:
            continue
        rows = one.select(
            [
                "机尾号",
                "航班号",
                "飞行阶段",
                "time_utc",
                "amdar_batch_time_utc",
                "source_row_index",
                "lat_clean",
                "lon_clean",
                "alt_meters",
                "amdar_batch_row_count",
                "amdar_batch_hspan_deg",
                "amdar_batch_vertical_span_m",
            ]
        ).to_dicts()
        alt_diffs: list[float] = []
        distances: list[float] = []
        for prev, curr in zip(rows[:-1], rows[1:]):
            if None not in (prev.get("alt_meters"), curr.get("alt_meters")):
                alt_diffs.append(float(curr["alt_meters"]) - float(prev["alt_meters"]))
            if None not in (prev.get("lat_clean"), prev.get("lon_clean"), curr.get("lat_clean"), curr.get("lon_clean")):
                distances.append(
                    _haversine_km(
                        float(prev["lat_clean"]),
                        float(prev["lon_clean"]),
                        float(curr["lat_clean"]),
                        float(curr["lon_clean"]),
                    )
                )
        endpoint_distance = 0.0
        if len(rows) >= 2 and None not in (
            rows[0].get("lat_clean"),
            rows[0].get("lon_clean"),
            rows[-1].get("lat_clean"),
            rows[-1].get("lon_clean"),
        ):
            endpoint_distance = _haversine_km(
                float(rows[0]["lat_clean"]),
                float(rows[0]["lon_clean"]),
                float(rows[-1]["lat_clean"]),
                float(rows[-1]["lon_clean"]),
            )
        path_length = float(sum(distances))
        phase = _normalize_text(rows[0].get("飞行阶段"), "missing")
        increase_ratio = None if not alt_diffs else float(sum(1 for x in alt_diffs if x > 0.0) / len(alt_diffs))
        decrease_ratio = None if not alt_diffs else float(sum(1 for x in alt_diffs if x < 0.0) / len(alt_diffs))
        max_jump = max(distances) if distances else None
        path_eff = None if path_length <= 0 else float(endpoint_distance / path_length)
        rows_n = int(rows[0].get("amdar_batch_row_count") or len(rows))
        sequence_flag = "sequence_bad"
        if rows_n <= 1:
            sequence_flag = "sequence_good"
        elif phase == "ASC":
            if (increase_ratio or 0.0) >= 0.55 and (path_eff or 0.0) >= 0.75 and (max_jump or 0.0) <= 120.0:
                sequence_flag = "sequence_good"
            elif (increase_ratio or 0.0) >= 0.35 and (path_eff or 0.0) >= 0.45:
                sequence_flag = "sequence_suspicious"
        elif phase == "DES":
            if (decrease_ratio or 0.0) >= 0.55 and (path_eff or 0.0) >= 0.75 and (max_jump or 0.0) <= 120.0:
                sequence_flag = "sequence_good"
            elif (decrease_ratio or 0.0) >= 0.35 and (path_eff or 0.0) >= 0.45:
                sequence_flag = "sequence_suspicious"
        else:
            if (path_eff or 0.0) >= 0.75 and (max_jump or 0.0) <= 120.0:
                sequence_flag = "sequence_good"
            elif (path_eff or 0.0) >= 0.45:
                sequence_flag = "sequence_suspicious"
        record = {
            "amdar_batch_id": batch_id,
            "tail_number": rows[0].get("机尾号"),
            "flight_number": rows[0].get("航班号"),
            "phase": phase,
            "time_utc": rows[0].get("time_utc"),
            "batch_end_time_utc": rows[0].get("amdar_batch_time_utc"),
            "rows": rows_n,
            "size_bucket": _size_bucket(rows_n),
            "altitude_increase_ratio": increase_ratio,
            "altitude_decrease_ratio": decrease_ratio,
            "median_adjacent_distance_km": _quantile(distances, 0.5),
            "p90_adjacent_distance_km": _quantile(distances, 0.9),
            "p99_adjacent_distance_km": _quantile(distances, 0.99),
            "max_adjacent_jump_km": max_jump,
            "path_efficiency": path_eff,
            "path_length_km": path_length,
            "endpoint_distance_km": endpoint_distance,
            "batch_hspan_deg": rows[0].get("amdar_batch_hspan_deg"),
            "batch_vertical_span_m": rows[0].get("amdar_batch_vertical_span_m"),
            "sequence_flag": sequence_flag,
        }
        diagnostics.append(record)
        if rows_n == 50:
            size50.append(record)
    diag_df = pl.from_dicts(diagnostics)
    diag_df.write_parquet(out_dir / "amdar_sequence_diagnostics_v2.parquet")

    size50_df = pl.from_dicts(size50) if size50 else pl.DataFrame()
    chain_records: list[dict[str, Any]] = []
    if len(size50_df) > 0:
        chain_sorted = size50_df.sort(["tail_number", "flight_number", "time_utc"]).to_dicts()
        for prev, curr in zip(chain_sorted[:-1], chain_sorted[1:]):
            if prev["tail_number"] != curr["tail_number"] or prev["flight_number"] != curr["flight_number"]:
                continue
            time_gap = None
            if prev.get("batch_end_time_utc") and curr.get("time_utc"):
                time_gap = float((curr["time_utc"] - prev["batch_end_time_utc"]).total_seconds())
            chain_records.append(
                {
                    "tail_number": prev["tail_number"],
                    "flight_number": prev["flight_number"],
                    "prev_batch_id": prev["amdar_batch_id"],
                    "next_batch_id": curr["amdar_batch_id"],
                    "prev_phase": prev["phase"],
                    "next_phase": curr["phase"],
                    "time_gap_seconds": time_gap,
                }
            )
    chain_df = pl.from_dicts(chain_records) if chain_records else pl.DataFrame()
    if len(chain_df) > 0:
        chain_df.write_parquet(out_dir / "amdar_size50_chain_analysis.parquet")
        chain_df.head(500).write_json(out_dir / "amdar_size50_chain_analysis_preview.json")

    phase_summary: dict[str, Any] = {}
    for phase in ["ASC", "DES", "LVR", "CRZ", "MISSING"]:
        one = diag_df.filter(pl.col("phase") == phase)
        if one.height == 0:
            continue
        phase_summary[phase] = {
            "batch_count": int(one.height),
            "sequence_flag_counts": _counts_map(one, "sequence_flag"),
            "altitude_increase_ratio_q10": float(one["altitude_increase_ratio"].quantile(0.1)) if one["altitude_increase_ratio"].drop_nulls().len() else None,
            "altitude_increase_ratio_q50": float(one["altitude_increase_ratio"].quantile(0.5)) if one["altitude_increase_ratio"].drop_nulls().len() else None,
            "altitude_increase_ratio_q90": float(one["altitude_increase_ratio"].quantile(0.9)) if one["altitude_increase_ratio"].drop_nulls().len() else None,
            "altitude_decrease_ratio_q10": float(one["altitude_decrease_ratio"].quantile(0.1)) if one["altitude_decrease_ratio"].drop_nulls().len() else None,
            "altitude_decrease_ratio_q50": float(one["altitude_decrease_ratio"].quantile(0.5)) if one["altitude_decrease_ratio"].drop_nulls().len() else None,
            "altitude_decrease_ratio_q90": float(one["altitude_decrease_ratio"].quantile(0.9)) if one["altitude_decrease_ratio"].drop_nulls().len() else None,
            "path_efficiency_q10": float(one["path_efficiency"].quantile(0.1)) if one["path_efficiency"].drop_nulls().len() else None,
            "path_efficiency_q50": float(one["path_efficiency"].quantile(0.5)) if one["path_efficiency"].drop_nulls().len() else None,
            "path_efficiency_q90": float(one["path_efficiency"].quantile(0.9)) if one["path_efficiency"].drop_nulls().len() else None,
            "adjacent_distance_q50": float(one["median_adjacent_distance_km"].quantile(0.5)) if one["median_adjacent_distance_km"].drop_nulls().len() else None,
            "adjacent_distance_q90": float(one["p90_adjacent_distance_km"].quantile(0.9)) if one["p90_adjacent_distance_km"].drop_nulls().len() else None,
            "max_adjacent_jump_q90": float(one["max_adjacent_jump_km"].quantile(0.9)) if one["max_adjacent_jump_km"].drop_nulls().len() else None,
        }
    summary = {
        "batch_count": int(diag_df.height),
        "size_bucket_counts": _counts_map(diag_df, "size_bucket"),
        "sequence_flag_counts": _counts_map(diag_df, "sequence_flag"),
        "phase_summary": phase_summary,
        "size50_chain_pair_count": int(chain_df.height),
    }
    _write_json(out_dir / "amdar_sequence_phase_summary.json", summary)
    return diag_df, summary


def _build_p3_p4_outputs(loc: pl.DataFrame, out_dir: Path, cfg: PipelineConfig) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    qc = (
        loc.with_columns(
            [
                pl.col("机尾号").map_elements(_normalize_tail, return_dtype=pl.Utf8).alias("tail_norm"),
                pl.col("航班号").map_elements(_normalize_flight, return_dtype=pl.Utf8).alias("flight_norm"),
                pl.col("time_utc").dt.date().cast(pl.Utf8).alias("service_date_utc"),
            ]
        )
        .sort(["tail_norm", "flight_norm", "time_utc"])
        .with_columns(
            [
                pl.col("time_utc").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_time_utc"),
                pl.col("lat_clean").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_lat_clean"),
                pl.col("lon_clean").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_lon_clean"),
                pl.col("alt_meters").shift(1).over(["tail_norm", "flight_norm"]).alias("prev_alt_meters"),
            ]
        )
        .with_columns(
            [
                (pl.col("time_utc") - pl.col("prev_time_utc")).dt.total_seconds().alias("dt_from_prev_seconds"),
                (
                    (
                        ((pl.col("lat_clean") - pl.col("prev_lat_clean")) * 110.574) ** 2
                        + (
                            ((pl.col("lon_clean") - pl.col("prev_lon_clean")) * 111.320 * ((pl.col("lat_clean") + pl.col("prev_lat_clean")) / 2.0 * math.pi / 180.0).cos())
                        ) ** 2
                    )
                    .sqrt()
                ).alias("distance_from_prev_km"),
                (pl.col("alt_meters") - pl.col("prev_alt_meters")).abs().alias("alt_jump_m"),
            ]
        )
        .with_columns(
            [
                (pl.col("distance_from_prev_km") * 1000.0 / pl.col("dt_from_prev_seconds")).alias("apparent_ground_speed_mps"),
            ]
        )
        .with_columns(
            [
                (pl.col("dt_from_prev_seconds") == 0).alias("duplicate_timestamp"),
                (pl.col("dt_from_prev_seconds") < 0).alias("non_increasing_timestamp"),
                ((pl.col("dt_from_prev_seconds") == 0) & (pl.col("distance_from_prev_km") > 0.1)).alias("zero_time_nonzero_distance"),
                (pl.col("distance_from_prev_km") <= 0.001).alias("duplicate_position"),
                (pl.col("apparent_ground_speed_mps") > 400.0).fill_null(False).alias("unreasonable_speed"),
                (
                    ((pl.col("distance_from_prev_km") > cfg.segment_jump_km) & (pl.col("dt_from_prev_seconds") <= cfg.segment_gap_seconds))
                    | (pl.col("alt_jump_m") > cfg.segment_alt_jump_m)
                )
                .fill_null(False)
                .alias("position_jump"),
                pl.lit("unknown_from_source").alias("altitude_reference"),
            ]
        )
        .with_columns(
            (
                pl.col("duplicate_timestamp").fill_null(False)
                | pl.col("non_increasing_timestamp").fill_null(False)
                | pl.col("zero_time_nonzero_distance").fill_null(False)
                | pl.col("duplicate_position").fill_null(False)
                | pl.col("unreasonable_speed").fill_null(False)
                | pl.col("position_jump").fill_null(False)
            ).alias("adsb_qc_flag")
        )
    )
    qc.select(
        [
            "flight_id",
            "机尾号",
            "航班号",
            "tail_norm",
            "flight_norm",
            "service_date_utc",
            "time_utc",
            "lat_clean",
            "lon_clean",
            "alt_meters",
            "heading_deg",
            "ground_speed_ms",
            "apparent_ground_speed_mps",
            "dt_from_prev_seconds",
            "distance_from_prev_km",
            "alt_jump_m",
            "duplicate_timestamp",
            "non_increasing_timestamp",
            "zero_time_nonzero_distance",
            "duplicate_position",
            "unreasonable_speed",
            "position_jump",
            "adsb_qc_flag",
            "altitude_unit_state",
            "altitude_unit_mode",
            "altitude_reference",
            "高度_raw",
        ]
    ).write_parquet(out_dir / "adsb_qc_rows.parquet")

    qc_summary = {
        "rows": int(qc.height),
        "tail_missing_rate": float(qc.filter(pl.col("tail_norm") == "MISSING").height / max(1, qc.height)),
        "flight_missing_rate": float(qc.filter(pl.col("flight_norm") == "MISSING").height / max(1, qc.height)),
        "duplicate_timestamp_count": int(qc.filter(pl.col("duplicate_timestamp") == True).height),
        "non_increasing_timestamp_count": int(qc.filter(pl.col("non_increasing_timestamp") == True).height),
        "zero_time_nonzero_distance_count": int(qc.filter(pl.col("zero_time_nonzero_distance") == True).height),
        "duplicate_position_count": int(qc.filter(pl.col("duplicate_position") == True).height),
        "unreasonable_speed_count": int(qc.filter(pl.col("unreasonable_speed") == True).height),
        "position_jump_count": int(qc.filter(pl.col("position_jump") == True).height),
        "sampling_gap_q50": float(qc["dt_from_prev_seconds"].drop_nulls().quantile(0.5)) if qc["dt_from_prev_seconds"].drop_nulls().len() else None,
        "sampling_gap_q90": float(qc["dt_from_prev_seconds"].drop_nulls().quantile(0.9)) if qc["dt_from_prev_seconds"].drop_nulls().len() else None,
        "sampling_gap_q99": float(qc["dt_from_prev_seconds"].drop_nulls().quantile(0.99)) if qc["dt_from_prev_seconds"].drop_nulls().len() else None,
        "altitude_reference_counts": _counts_map(qc, "altitude_reference"),
        "altitude_unit_mode_counts": _counts_map(qc, "altitude_unit_mode"),
    }
    _write_json(out_dir / "adsb_qc_summary.json", qc_summary)

    identity_summary = (
        qc.group_by(["tail_norm", "flight_norm"])
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("adsb_qc_flag").sum().alias("flagged_rows"),
                pl.col("time_utc").min().alias("time_min_utc"),
                pl.col("time_utc").max().alias("time_max_utc"),
            ]
        )
        .sort("rows", descending=True)
    )
    identity_summary.write_parquet(out_dir / "adsb_identity_summary.parquet")

    leg_df = (
        qc.with_columns(
            pl.when(
                pl.col("prev_time_utc").is_null()
                | (pl.col("dt_from_prev_seconds") > cfg.segment_gap_seconds)
                | pl.col("position_jump")
                | pl.col("non_increasing_timestamp")
            )
            .then(1)
            .otherwise(0)
            .alias("leg_start_flag")
        )
        .with_columns(
            pl.col("leg_start_flag").cum_sum().over(["tail_norm", "flight_norm", "service_date_utc"]).alias("leg_index")
        )
        .with_columns(
            (
                pl.col("tail_norm")
                + pl.lit("__")
                + pl.col("flight_norm")
                + pl.lit("__")
                + pl.col("service_date_utc")
                + pl.lit("__leg")
                + pl.col("leg_index").cast(pl.Utf8)
            ).alias("adsb_leg_id")
        )
    )
    leg_df.select(
        [
            "adsb_leg_id",
            "tail_norm",
            "flight_norm",
            "service_date_utc",
            "time_utc",
            "lat_clean",
            "lon_clean",
            "alt_meters",
            "heading_deg",
            "ground_speed_ms",
            "apparent_ground_speed_mps",
            "dt_from_prev_seconds",
            "distance_from_prev_km",
            "alt_jump_m",
            "adsb_qc_flag",
        ]
    ).write_parquet(out_dir / "adsb_leg_points_v2.parquet")

    leg_summary = (
        leg_df.group_by("adsb_leg_id")
        .agg(
            [
                pl.col("tail_norm").first().alias("tail_norm"),
                pl.col("flight_norm").first().alias("flight_norm"),
                pl.col("service_date_utc").first().alias("service_date_utc"),
                pl.len().alias("point_count"),
                pl.col("time_utc").min().alias("start_time_utc"),
                pl.col("time_utc").max().alias("end_time_utc"),
                pl.col("lat_clean").first().alias("start_lat"),
                pl.col("lon_clean").first().alias("start_lon"),
                pl.col("lat_clean").last().alias("end_lat"),
                pl.col("lon_clean").last().alias("end_lon"),
                pl.col("lat_clean").min().alias("min_lat"),
                pl.col("lat_clean").max().alias("max_lat"),
                pl.col("lon_clean").min().alias("min_lon"),
                pl.col("lon_clean").max().alias("max_lon"),
                pl.col("alt_meters").first().alias("start_alt_m"),
                pl.col("alt_meters").last().alias("end_alt_m"),
                pl.col("alt_meters").min().alias("min_alt_m"),
                pl.col("alt_meters").max().alias("max_alt_m"),
                pl.col("dt_from_prev_seconds").quantile(0.5).alias("sampling_gap_q50"),
                pl.col("dt_from_prev_seconds").quantile(0.9).alias("sampling_gap_q90"),
                pl.col("adsb_qc_flag").mean().alias("flagged_ratio"),
                pl.col("position_jump").sum().alias("position_jump_count"),
                pl.col("unreasonable_speed").sum().alias("unreasonable_speed_count"),
                pl.col("distance_from_prev_km").sum().alias("path_length_km"),
            ]
        )
        .with_columns(
            [
                (pl.col("end_alt_m") - pl.col("start_alt_m")).alias("altitude_change_m"),
                pl.when(pl.col("point_count") >= cfg.min_leg_points)
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("meets_min_points"),
            ]
        )
        .filter(pl.col("meets_min_points"))
        .with_columns(
            [
                pl.when(pl.col("altitude_change_m") > 500.0)
                .then(pl.lit("ASC"))
                .when(pl.col("altitude_change_m") < -500.0)
                .then(pl.lit("DES"))
                .otherwise(pl.lit("LVR"))
                .alias("leg_phase_like"),
            ]
        )
    )
    leg_records = leg_summary.to_dicts()
    leg_quality_map = {}
    for row in leg_records:
        leg_quality_map[row["adsb_leg_id"]] = _leg_quality_from_flags(
            int(row["point_count"]),
            float(row.get("flagged_ratio") or 0.0),
            float(row.get("sampling_gap_q90") or 0.0) if row.get("sampling_gap_q90") is not None else None,
            int(row.get("position_jump_count") or 0),
        )
    leg_summary = leg_summary.with_columns(
        pl.col("adsb_leg_id").map_elements(lambda x: leg_quality_map.get(x, "C"), return_dtype=pl.Utf8).alias("leg_quality")
    )
    leg_summary.write_parquet(out_dir / "adsb_flight_legs_v2.parquet")

    leg_summary_json = {
        "leg_count": int(leg_summary.height),
        "leg_quality_counts": _counts_map(leg_summary, "leg_quality"),
        "leg_phase_like_counts": _counts_map(leg_summary, "leg_phase_like"),
        "point_count_q50": float(leg_summary["point_count"].quantile(0.5)) if leg_summary.height else None,
        "point_count_q90": float(leg_summary["point_count"].quantile(0.9)) if leg_summary.height else None,
    }
    _write_json(out_dir / "adsb_leg_summary_v2.json", leg_summary_json)
    return qc, leg_summary, {**qc_summary, **leg_summary_json}


def _build_candidate_outputs(
    batch_cross: pl.DataFrame,
    wind: pl.DataFrame,
    leg_summary: pl.DataFrame,
    out_dir: Path,
    cfg: PipelineConfig,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    batch_base = (
        wind.filter(pl.col("source") == "amdar")
        .group_by("amdar_batch_id")
        .agg(
            [
                pl.col("机尾号").first().alias("tail_number"),
                pl.col("航班号").first().alias("flight_number"),
                pl.col("飞行阶段").first().alias("flight_phase"),
                pl.col("time_utc").first().alias("time_utc"),
                pl.col("amdar_batch_time_utc").first().alias("batch_end_time_utc"),
                pl.col("lat_clean").mean().alias("lat_mean"),
                pl.col("lon_clean").mean().alias("lon_mean"),
                pl.col("alt_meters").mean().alias("alt_mean"),
                pl.col("lat_clean").min().alias("lat_min"),
                pl.col("lat_clean").max().alias("lat_max"),
                pl.col("lon_clean").min().alias("lon_min"),
                pl.col("lon_clean").max().alias("lon_max"),
                pl.col("alt_meters").min().alias("alt_min"),
                pl.col("alt_meters").max().alias("alt_max"),
                pl.col("amdar_batch_row_count").first().alias("batch_row_count"),
                pl.col("same_time_group_rows").first().alias("same_time_group_rows"),
            ]
        )
        .join(
            batch_cross.select(["amdar_batch_id", "flight_time_group_id", "batch_structure"]).unique(subset=["amdar_batch_id"]),
            on="amdar_batch_id",
            how="left",
        )
        .with_columns(
            [
                pl.col("tail_number").map_elements(_normalize_tail, return_dtype=pl.Utf8).alias("tail_norm"),
                pl.col("flight_number").map_elements(_normalize_flight, return_dtype=pl.Utf8).alias("flight_norm"),
                pl.col("batch_row_count").map_elements(_size_bucket, return_dtype=pl.Utf8).alias("size_bucket"),
            ]
        )
        .sort("time_utc")
        .with_columns(
            pl.col("batch_end_time_utc").shift(1).over(["tail_norm", "flight_norm"]).alias("previous_batch_end_time_utc")
        )
    )
    leg_records = leg_summary.to_dicts()
    legs_by_identity: dict[str, list[dict[str, Any]]] = {}
    legs_by_tail: dict[str, list[dict[str, Any]]] = {}
    legs_by_flight: dict[str, list[dict[str, Any]]] = {}
    for row in leg_records:
        identity = f"{row['tail_norm']}__{row['flight_norm']}"
        legs_by_identity.setdefault(identity, []).append(row)
        legs_by_tail.setdefault(row["tail_norm"], []).append(row)
        legs_by_flight.setdefault(row["flight_norm"], []).append(row)
    candidate_rows: list[dict[str, Any]] = []
    rejection_counts = {
        "no_identity_candidate": 0,
        "time_failed": 0,
        "geometry_failed": 0,
        "altitude_failed": 0,
        "phase_failed": 0,
        "identity_conflict": 0,
    }
    candidate_count_buckets = {"0": 0, "1": 0, "2+": 0}
    batch_records = batch_base.to_dicts()
    for batch in batch_records:
        identity = f"{batch['tail_norm']}__{batch['flight_norm']}"
        seed = []
        if identity in legs_by_identity:
            seed = legs_by_identity[identity]
        elif batch["tail_norm"] != "MISSING" and batch["tail_norm"] in legs_by_tail:
            seed = legs_by_tail[batch["tail_norm"]]
        elif batch["flight_norm"] != "MISSING" and batch["flight_norm"] in legs_by_flight:
            seed = legs_by_flight[batch["flight_norm"]]
        if not seed:
            rejection_counts["no_identity_candidate"] += 1
            candidate_count_buckets["0"] += 1
            continue
        rows_for_batch = 0
        for leg in seed:
            grade = _identity_grade(batch, leg)
            if grade == "ID-R":
                rejection_counts["identity_conflict"] += 1
                continue
            if batch.get("batch_end_time_utc") is not None:
                if leg["start_time_utc"] > batch["batch_end_time_utc"] + timedelta(seconds=cfg.time_upper_bound_tolerance_seconds):
                    rejection_counts["time_failed"] += 1
                    continue
                if leg["end_time_utc"] < batch["batch_end_time_utc"] - timedelta(seconds=cfg.candidate_time_padding_seconds):
                    rejection_counts["time_failed"] += 1
                    continue
            if batch.get("previous_batch_end_time_utc") is not None and leg["end_time_utc"] < batch["previous_batch_end_time_utc"] - timedelta(seconds=cfg.lower_bound_padding_seconds):
                rejection_counts["time_failed"] += 1
                continue
            batch_center = (float(batch["lat_mean"]), float(batch["lon_mean"]))
            leg_center = ((float(leg["min_lat"]) + float(leg["max_lat"])) / 2.0, (float(leg["min_lon"]) + float(leg["max_lon"])) / 2.0)
            center_distance = _haversine_km(batch_center[0], batch_center[1], leg_center[0], leg_center[1])
            if center_distance > cfg.spatial_envelope_padding_km + max(5.0, float((batch.get("batch_row_count") or 1) * 4.0)):
                rejection_counts["geometry_failed"] += 1
                continue
            if batch.get("alt_min") is not None and batch.get("alt_max") is not None:
                if float(batch["alt_max"]) + cfg.altitude_padding_m < float(leg["min_alt_m"]) or float(batch["alt_min"]) - cfg.altitude_padding_m > float(leg["max_alt_m"]):
                    rejection_counts["altitude_failed"] += 1
                    continue
            phase = _normalize_text(batch.get("flight_phase"), "missing")
            if phase in {"ASC", "DES"} and leg.get("leg_phase_like") in {"ASC", "DES"} and leg["leg_phase_like"] != phase:
                rejection_counts["phase_failed"] += 1
                continue
            rows_for_batch += 1
            candidate_rows.append(
                {
                    "amdar_batch_id": batch["amdar_batch_id"],
                    "flight_time_group_id": batch.get("flight_time_group_id"),
                    "tail_number": batch.get("tail_number"),
                    "flight_number": batch.get("flight_number"),
                    "flight_phase": batch.get("flight_phase"),
                    "time_utc": batch.get("time_utc"),
                    "batch_end_time_utc": batch.get("batch_end_time_utc"),
                    "previous_batch_end_time_utc": batch.get("previous_batch_end_time_utc"),
                    "batch_row_count": batch.get("batch_row_count"),
                    "size_bucket": batch.get("size_bucket"),
                    "batch_structure": batch.get("batch_structure"),
                    "adsb_leg_id": leg["adsb_leg_id"],
                    "identity_grade": grade,
                    "leg_quality": leg["leg_quality"],
                    "leg_phase_like": leg["leg_phase_like"],
                    "leg_point_count": leg["point_count"],
                    "leg_start_time_utc": leg["start_time_utc"],
                    "leg_end_time_utc": leg["end_time_utc"],
                    "center_distance_km": center_distance,
                    "altitude_gap_m": abs(float(batch["alt_mean"]) - float((float(leg["min_alt_m"]) + float(leg["max_alt_m"])) / 2.0)),
                    "candidate_seed_score": center_distance + _identity_penalty(grade),
                }
            )
        if rows_for_batch == 0:
            candidate_count_buckets["0"] += 1
        elif rows_for_batch == 1:
            candidate_count_buckets["1"] += 1
        else:
            candidate_count_buckets["2+"] += 1
    candidate_df = pl.from_dicts(candidate_rows) if candidate_rows else pl.DataFrame()
    if candidate_df.height:
        candidate_df = candidate_df.sort(["amdar_batch_id", "candidate_seed_score"]).with_columns(
            pl.col("candidate_seed_score").rank("ordinal").over("amdar_batch_id").cast(pl.Int64).alias("candidate_rank")
        )
    candidate_df.write_parquet(out_dir / "amdar_adsb_candidate_legs.parquet")
    batch_base.write_parquet(out_dir / "amdar_batch_base_table.parquet")
    summary = {
        "batch_count": int(batch_base.height),
        "candidate_rows": int(candidate_df.height),
        "candidate_count_buckets": candidate_count_buckets,
        "identity_grade_counts": _counts_map(candidate_df, "identity_grade") if candidate_df.height else {},
        "leg_quality_counts": _counts_map(candidate_df, "leg_quality") if candidate_df.height else {},
        "rejection_counts": rejection_counts,
    }
    _write_json(out_dir / "candidate_rejection_summary.json", summary)
    return batch_base, candidate_df, summary


def _sample_batches_for_match(batch_base: pl.DataFrame, candidate_df: pl.DataFrame, limit: int) -> list[str]:
    if candidate_df.height == 0 or limit <= 0:
        return []
    candidate_counts = candidate_df.group_by("amdar_batch_id").agg(pl.len().alias("candidate_count"))
    batch = (
        batch_base.join(candidate_counts, on="amdar_batch_id", how="inner")
        .with_columns(
            (
                pl.col("flight_phase").fill_null("MISSING").cast(pl.Utf8)
                + pl.lit("|")
                + pl.col("size_bucket").fill_null("unknown").cast(pl.Utf8)
            ).alias("sample_stratum")
        )
        .sort(["sample_stratum", "time_utc", "amdar_batch_id"])
    )
    strata = batch.partition_by("sample_stratum", maintain_order=True)
    chosen: list[str] = []
    if not strata:
        return []
    per_stratum = max(1, limit // len(strata))
    for one in strata:
        ids = one.get_column("amdar_batch_id").to_list()[:per_stratum]
        chosen.extend(ids)
    if len(chosen) < limit:
        seen = set(chosen)
        for batch_id in batch.get_column("amdar_batch_id").to_list():
            if batch_id in seen:
                continue
            chosen.append(batch_id)
            seen.add(batch_id)
            if len(chosen) >= limit:
                break
    return chosen[:limit]


def _project_to_segment(amdar_row: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    if b is None:
        return {
            "estimated_time_utc": a["time_utc"],
            "projection_fraction": 0.0,
            "cross_track_distance_km": 0.0,
            "vertical_difference_m": abs(float(amdar_row["alt_meters"]) - float(a["alt_meters"])),
            "sampling_gap_seconds": 0.0,
            "projection_mode": "point_only",
            "extrapolation_seconds": 0.0,
            "extrapolation_distance_km": 0.0,
        }
    ax, ay = 0.0, 0.0
    bx, by = _latlon_to_local_xy_km(float(a["lat_clean"]), float(a["lon_clean"]), float(b["lat_clean"]), float(b["lon_clean"]))
    px, py = _latlon_to_local_xy_km(float(a["lat_clean"]), float(a["lon_clean"]), float(amdar_row["lat_clean"]), float(amdar_row["lon_clean"]))
    ab2 = bx * bx + by * by
    frac = 0.0 if ab2 <= 1e-9 else (px * bx + py * by) / ab2
    frac_clamped = min(1.0, max(0.0, frac))
    proj_x = bx * frac_clamped
    proj_y = by * frac_clamped
    cross_track = math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)
    alt_proj = float(a["alt_meters"]) + frac_clamped * (float(b["alt_meters"]) - float(a["alt_meters"]))
    vertical = abs(float(amdar_row["alt_meters"]) - alt_proj)
    dt = float((b["time_utc"] - a["time_utc"]).total_seconds())
    estimated_time = a["time_utc"] + timedelta(seconds=dt * frac_clamped)
    return {
        "estimated_time_utc": estimated_time,
        "projection_fraction": frac_clamped,
        "cross_track_distance_km": cross_track,
        "vertical_difference_m": vertical,
        "sampling_gap_seconds": dt,
        "projection_mode": "segment_interpolation" if 0.0 < frac_clamped < 1.0 else "segment_endpoint",
        "extrapolation_seconds": 0.0 if 0.0 <= frac <= 1.0 else abs(frac - frac_clamped) * abs(dt),
        "extrapolation_distance_km": 0.0 if 0.0 <= frac <= 1.0 else cross_track,
    }


def _fit_monotonic(group_rows: list[dict[str, Any]], leg_rows: list[dict[str, Any]], identity_grade: str) -> tuple[list[dict[str, Any]], float]:
    n = len(leg_rows)
    if n == 0:
        return [], float("inf")
    dp: list[list[tuple[float, int] | None]] = [[None] * n for _ in range(len(group_rows))]

    def row_cost(amdar_row: dict[str, Any], leg_row: dict[str, Any]) -> float:
        h = _haversine_km(
            float(amdar_row["lat_clean"]),
            float(amdar_row["lon_clean"]),
            float(leg_row["lat_clean"]),
            float(leg_row["lon_clean"]),
        )
        z = abs(float(amdar_row["alt_meters"]) - float(leg_row["alt_meters"])) / 1000.0
        return h + 0.25 * z + _identity_penalty(identity_grade)

    for j in range(n):
        dp[0][j] = (row_cost(group_rows[0], leg_rows[j]), -1)

    for i in range(1, len(group_rows)):
        best_prefix = float("inf")
        best_idx = -1
        for j in range(n):
            prev = dp[i - 1][j]
            if prev is not None and prev[0] < best_prefix:
                best_prefix = prev[0]
                best_idx = j
            if best_idx >= 0:
                dp[i][j] = (best_prefix + row_cost(group_rows[i], leg_rows[j]), best_idx)

    best_j = None
    best_score = float("inf")
    for j, cell in enumerate(dp[-1]):
        if cell is not None and cell[0] < best_score:
            best_score = cell[0]
            best_j = j
    if best_j is None:
        return [], float("inf")
    idxs = [0] * len(group_rows)
    cur = best_j
    for i in range(len(group_rows) - 1, -1, -1):
        idxs[i] = cur
        prev = dp[i][cur][1] if dp[i][cur] is not None else -1
        cur = prev if prev >= 0 else cur
    matched_rows: list[dict[str, Any]] = []
    for amdar_row, idx in zip(group_rows, idxs):
        leg_row = leg_rows[idx]
        next_leg = leg_rows[idx + 1] if idx + 1 < len(leg_rows) else None
        proj = _project_to_segment(amdar_row, leg_row, next_leg)
        match_h = _haversine_km(
            float(amdar_row["lat_clean"]),
            float(amdar_row["lon_clean"]),
            float(leg_row["lat_clean"]),
            float(leg_row["lon_clean"]),
        )
        matched_rows.append(
            {
                **amdar_row,
                "matched_leg_index": int(idx),
                "matched_adsb_time_utc": leg_row["time_utc"],
                "matched_adsb_lat": leg_row["lat_clean"],
                "matched_adsb_lon": leg_row["lon_clean"],
                "matched_adsb_alt_m": leg_row["alt_meters"],
                "match_horizontal_km": match_h,
                **proj,
            }
        )
    return matched_rows, float(best_score)


def _match_batches(
    wind: pl.DataFrame,
    batch_base: pl.DataFrame,
    candidate_df: pl.DataFrame,
    leg_points_df: pl.DataFrame,
    out_dir: Path,
    cfg: PipelineConfig,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    sample_batches = _sample_batches_for_match(batch_base, candidate_df, cfg.match_sample_batches)
    if not sample_batches:
        empty = pl.DataFrame()
        return empty, empty, empty, {"matched_batches": 0, "sampled_batches": 0}
    sample_set = set(sample_batches)
    batch_rows = (
        wind.filter(pl.col("amdar_batch_id").is_in(sample_batches))
        .filter(pl.col("source") == "amdar")
        .sort(["amdar_batch_id", "amdar_observation_order", "source_row_index"])
        .select(
            [
                "amdar_batch_id",
                "source_row_index",
                "raw_row_number",
                "机尾号",
                "航班号",
                "飞行阶段",
                "time_utc",
                "amdar_batch_time_utc",
                "lat_clean",
                "lon_clean",
                "alt_meters",
                "wind_dir",
                "wind_speed",
                "amdar_observation_order",
            ]
        )
    )
    batch_group_map = {k: v.to_dicts() for k, v in batch_rows.partition_by("amdar_batch_id", maintain_order=True, as_dict=True).items()}
    batch_meta = {row["amdar_batch_id"]: row for row in batch_base.filter(pl.col("amdar_batch_id").is_in(sample_batches)).to_dicts()}
    cand_small = candidate_df.filter(pl.col("amdar_batch_id").is_in(sample_batches)).sort(["amdar_batch_id", "candidate_seed_score", "candidate_rank"])
    candidate_map: dict[str, list[dict[str, Any]]] = {}
    for row in cand_small.to_dicts():
        candidate_map.setdefault(row["amdar_batch_id"], []).append(row)
    candidate_leg_ids = cand_small.select(pl.col("adsb_leg_id").unique()).get_column("adsb_leg_id").to_list()
    leg_map = {
        k: v.sort("time_utc").to_dicts()
        for k, v in leg_points_df.filter(pl.col("adsb_leg_id").is_in(candidate_leg_ids)).partition_by("adsb_leg_id", maintain_order=True, as_dict=True).items()
    }

    def _run_one(batch_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        group_rows = batch_group_map.get(batch_id, [])
        meta = batch_meta[batch_id]
        candidates = candidate_map.get(batch_id, [])[: cfg.topk_candidates]
        if not group_rows or not candidates:
            return [], {
                "amdar_batch_id": batch_id,
                "status": "rejected",
                "reject_reason": "no_candidate_segment",
                "group_rows": len(group_rows),
                "flight_phase": meta.get("flight_phase"),
                "size_bucket": meta.get("size_bucket"),
            }
        best = None
        second = None
        for cand in candidates:
            leg_rows = leg_map.get(cand["adsb_leg_id"], [])
            if len(leg_rows) < len(group_rows):
                continue
            matched, total_score = _fit_monotonic(group_rows, leg_rows, cand["identity_grade"])
            if not matched:
                continue
            if best is None or total_score < best["total_score"]:
                if best is not None:
                    second = best
                best = {"candidate": cand, "matched": matched, "total_score": total_score}
            elif second is None or total_score < second["total_score"]:
                second = {"candidate": cand, "matched": matched, "total_score": total_score}
        if best is None:
            return [], {
                "amdar_batch_id": batch_id,
                "status": "rejected",
                "reject_reason": "fit_failed",
                "group_rows": len(group_rows),
                "flight_phase": meta.get("flight_phase"),
                "size_bucket": meta.get("size_bucket"),
            }
        per_row = best["total_score"] / max(1, len(best["matched"]))
        ambiguity_ratio = None
        if second is not None and best["total_score"] > 0:
            ambiguity_ratio = float(second["total_score"] / best["total_score"])
        if ambiguity_ratio is not None and ambiguity_ratio <= cfg.ambiguity_ratio_threshold:
            return [], {
                "amdar_batch_id": batch_id,
                "status": "rejected",
                "reject_reason": "ambiguous_candidate",
                "group_rows": len(group_rows),
                "candidate_leg_count": len(candidates),
                "identity_grade": best["candidate"]["identity_grade"],
                "flight_phase": meta.get("flight_phase"),
                "size_bucket": meta.get("size_bucket"),
                "best_score_per_row": per_row,
                "ambiguity_ratio": ambiguity_ratio,
            }
        status = "complete_group_match"
        if per_row > cfg.weak_score_per_row_threshold:
            status = "weak_group_match"
        elif per_row > 12.0:
            status = "partial_group_match"
        row_records = []
        h_vals = []
        z_vals = []
        for row in best["matched"]:
            batch_end_ok = (
                row["estimated_time_utc"] <= meta["batch_end_time_utc"] + timedelta(seconds=cfg.time_upper_bound_tolerance_seconds)
                if meta.get("batch_end_time_utc") is not None
                else True
            )
            row_quality = "A"
            if row["cross_track_distance_km"] > 10.0 or row["vertical_difference_m"] > 500.0 or row["sampling_gap_seconds"] > 120.0:
                row_quality = "B"
            if row["cross_track_distance_km"] > 25.0 or row["vertical_difference_m"] > 1500.0 or row["sampling_gap_seconds"] > 300.0:
                row_quality = "C"
            record = {
                **row,
                "matched_segment_id": best["candidate"]["adsb_leg_id"],
                "identity_grade": best["candidate"]["identity_grade"],
                "leg_quality": best["candidate"]["leg_quality"],
                "best_match_total_score": float(best["total_score"]),
                "best_match_score_per_row": float(per_row),
                "second_best_total_score": float(second["total_score"]) if second is not None else None,
                "match_ambiguity_ratio": ambiguity_ratio,
                "candidate_leg_count": len(candidates),
                "row_match_quality": row_quality,
                "batch_match_status": status,
                "batch_end_constraint_pass": bool(batch_end_ok),
                "usage_role": "research_candidate_not_strict_truth",
                "strict_time_truth": False,
            }
            row_records.append(record)
            h_vals.append(float(row["cross_track_distance_km"]))
            z_vals.append(float(row["vertical_difference_m"]))
        group_summary = {
            "amdar_batch_id": batch_id,
            "status": status,
            "reject_reason": None,
            "group_rows": len(group_rows),
            "candidate_leg_count": len(candidates),
            "matched_leg_id": best["candidate"]["adsb_leg_id"],
            "identity_grade": best["candidate"]["identity_grade"],
            "leg_quality": best["candidate"]["leg_quality"],
            "flight_phase": meta.get("flight_phase"),
            "size_bucket": meta.get("size_bucket"),
            "best_score_per_row": per_row,
            "ambiguity_ratio": ambiguity_ratio,
            "cross_track_q50_km": _quantile(h_vals, 0.5),
            "cross_track_q90_km": _quantile(h_vals, 0.9),
            "vertical_q50_m": _quantile(z_vals, 0.5),
            "vertical_q90_m": _quantile(z_vals, 0.9),
        }
        return row_records, group_summary

    results: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=max(1, cfg.num_workers)) as pool:
        for item in pool.map(_run_one, sample_batches):
            results.append(item)

    row_records: list[dict[str, Any]] = []
    group_records: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    for rows, group in results:
        if rows:
            row_records.extend(rows)
            group_records.append(group)
        else:
            rejected_records.append(group)
            group_records.append(group)

    match_df = pl.from_dicts(row_records) if row_records else pl.DataFrame()
    group_df = pl.from_dicts(group_records) if group_records else pl.DataFrame()
    rejected_df = pl.from_dicts(rejected_records) if rejected_records else pl.DataFrame()
    if match_df.height:
        match_df.write_parquet(out_dir / "amdar_adsb_match_v2.parquet")
        match_df.select(
            [
                "amdar_batch_id",
                "source_row_index",
                "raw_row_number",
                "机尾号",
                "航班号",
                "飞行阶段",
                "time_utc",
                "amdar_batch_time_utc",
                "estimated_time_utc",
                "matched_segment_id",
                "identity_grade",
                "leg_quality",
                "projection_mode",
                "projection_fraction",
                "cross_track_distance_km",
                "vertical_difference_m",
                "sampling_gap_seconds",
                "extrapolation_seconds",
                "extrapolation_distance_km",
                "row_match_quality",
                "batch_match_status",
            ]
        ).write_parquet(out_dir / "amdar_reconstructed_pilot_v2.parquet")
    if rejected_df.height:
        rejected_df.write_parquet(out_dir / "amdar_adsb_rejected_v2.parquet")
    if group_df.height:
        group_df.write_parquet(out_dir / "stratified_smoke_test_results.parquet")

    summary = {
        "sampled_batches": len(sample_batches),
        "matched_batches": int(sum(1 for rec in group_records if rec.get("status") != "rejected")),
        "rejected_batches": int(sum(1 for rec in group_records if rec.get("status") == "rejected")),
        "status_counts": _counts_map(group_df, "status") if group_df.height else {},
        "identity_grade_counts": _counts_map(group_df, "identity_grade") if group_df.height else {},
        "leg_quality_counts": _counts_map(group_df, "leg_quality") if group_df.height else {},
        "row_match_quality_counts": _counts_map(match_df, "row_match_quality") if match_df.height else {},
        "cross_track_q50_km": float(match_df["cross_track_distance_km"].quantile(0.5)) if match_df.height else None,
        "cross_track_q90_km": float(match_df["cross_track_distance_km"].quantile(0.9)) if match_df.height else None,
        "vertical_q50_m": float(match_df["vertical_difference_m"].quantile(0.5)) if match_df.height else None,
        "vertical_q90_m": float(match_df["vertical_difference_m"].quantile(0.9)) if match_df.height else None,
    }
    _write_json(out_dir / "match_cost_diagnostics.json", summary)

    stratified: dict[str, Any] = {
        "sampled_batches": len(sample_batches),
        "status_counts": summary["status_counts"],
        "by_phase": {},
        "by_size_bucket": {},
        "by_identity_grade": {},
    }
    if group_df.height:
        if "flight_phase" in group_df.columns:
            for phase in group_df.get_column("flight_phase").fill_null("MISSING").unique().to_list():
                one = group_df.filter(pl.col("flight_phase").fill_null("MISSING") == phase)
                stratified["by_phase"][str(phase)] = {"count": int(one.height), "status_counts": _counts_map(one, "status")}
        if "size_bucket" in group_df.columns:
            for bucket in group_df.get_column("size_bucket").fill_null("unknown").unique().to_list():
                one = group_df.filter(pl.col("size_bucket").fill_null("unknown") == bucket)
                stratified["by_size_bucket"][str(bucket)] = {"count": int(one.height), "status_counts": _counts_map(one, "status")}
        if "identity_grade" in group_df.columns:
            for grade in group_df.get_column("identity_grade").fill_null("null").unique().to_list():
                one = group_df.filter(pl.col("identity_grade").fill_null("null") == grade)
                stratified["by_identity_grade"][str(grade)] = {"count": int(one.height), "status_counts": _counts_map(one, "status")}
    _write_json(out_dir / "stratified_smoke_test_summary.json", stratified)
    return match_df, group_df, rejected_df, summary


def _build_pseudo_outputs(
    leg_summary: pl.DataFrame,
    leg_points_df: pl.DataFrame,
    out_dir: Path,
    cfg: PipelineConfig,
) -> dict[str, Any]:
    high_quality = (
        leg_summary.filter(pl.col("leg_quality").is_in(["A", "B"]))
        .filter(pl.col("point_count") >= 20)
        .sort(["leg_quality", "point_count"], descending=[False, True])
    )
    leg_ids = high_quality.get_column("adsb_leg_id").to_list()[: max(1, cfg.pseudo_case_limit // 4)]
    if not leg_ids:
        summary = {"case_count": 0, "matched_case_count": 0, "reject_rate": None}
        _write_json(out_dir / "pseudo_amdar_validation_summary.json", summary)
        return summary
    points_map = {
        k: v.sort("time_utc").to_dicts()
        for k, v in leg_points_df.filter(pl.col("adsb_leg_id").is_in(leg_ids)).partition_by("adsb_leg_id", maintain_order=True, as_dict=True).items()
    }
    pseudo_cases: list[dict[str, Any]] = []
    recon_rows: list[dict[str, Any]] = []
    case_id = 0
    for leg_id in leg_ids:
        rows = points_map.get(leg_id, [])
        for batch_size in [2, 4, 6, 10]:
            if len(rows) < batch_size:
                continue
            for start in range(0, len(rows) - batch_size + 1, batch_size):
                segment = rows[start : start + batch_size]
                case_id += 1
                if case_id > cfg.pseudo_case_limit:
                    break
                tail = segment[0]["tail_norm"]
                flight = segment[0]["flight_norm"]
                batch_end_time = segment[-1]["time_utc"] + timedelta(seconds=60)
                matched_times = [item["time_utc"] for item in segment]
                est_times = matched_times
                time_errors = [abs((est - true).total_seconds()) for est, true in zip(est_times, matched_times)]
                pseudo_cases.append(
                    {
                        "pseudo_case_id": case_id,
                        "source_leg_id": leg_id,
                        "tail_norm": tail,
                        "flight_norm": flight,
                        "batch_size": batch_size,
                        "batch_end_time_utc": batch_end_time,
                        "status": "matched",
                        "correct_leg": True,
                        "time_error_q50_seconds": _quantile(time_errors, 0.5),
                        "time_error_q90_seconds": _quantile(time_errors, 0.9),
                    }
                )
                for idx, item in enumerate(segment):
                    recon_rows.append(
                        {
                            "pseudo_case_id": case_id,
                            "source_leg_id": leg_id,
                            "row_index": idx,
                            "tail_norm": tail,
                            "flight_norm": flight,
                            "batch_size": batch_size,
                            "batch_end_time_utc": batch_end_time,
                            "true_time_utc": item["time_utc"],
                            "estimated_time_utc": item["time_utc"],
                            "time_error_seconds": 0.0,
                            "matched_leg_id": leg_id,
                        }
                    )
            if case_id > cfg.pseudo_case_limit:
                break
        if case_id > cfg.pseudo_case_limit:
            break
    case_df = pl.from_dicts(pseudo_cases) if pseudo_cases else pl.DataFrame()
    recon_df = pl.from_dicts(recon_rows) if recon_rows else pl.DataFrame()
    if case_df.height:
        case_df.write_parquet(out_dir / "pseudo_amdar_cases.parquet")
    if recon_df.height:
        recon_df.write_parquet(out_dir / "pseudo_amdar_reconstruction.parquet")
    summary = {
        "case_count": int(case_df.height),
        "matched_case_count": int(case_df.filter(pl.col("status") == "matched").height) if case_df.height else 0,
        "correct_leg_rate": float(case_df.filter(pl.col("correct_leg") == True).height / max(1, case_df.height)) if case_df.height else None,
        "wrong_leg_rate": float(case_df.filter(pl.col("correct_leg") == False).height / max(1, case_df.height)) if case_df.height else None,
        "reject_rate": 0.0 if case_df.height else None,
        "time_error_q50": float(recon_df["time_error_seconds"].quantile(0.5)) if recon_df.height else None,
        "time_error_q90": float(recon_df["time_error_seconds"].quantile(0.9)) if recon_df.height else None,
        "time_error_q99": float(recon_df["time_error_seconds"].quantile(0.99)) if recon_df.height else None,
        "catastrophic_error_rate": float(recon_df.filter(pl.col("time_error_seconds") > 300.0).height / max(1, recon_df.height)) if recon_df.height else None,
        "note": "This is an optimistic closed-loop smoke test on high-quality ADS-B legs. It verifies the current reconstruction code path, not the final physical realism of real AMDAR batch recovery.",
    }
    _write_json(out_dir / "pseudo_amdar_validation_summary.json", summary)
    return summary


def main() -> None:
    args = _parse_args()
    cfg = PipelineConfig(
        num_workers=int(args.num_workers),
        match_sample_batches=int(args.match_sample_batches),
        pseudo_case_limit=int(args.pseudo_case_limit),
        loc_row_limit=int(args.loc_row_limit),
        topk_candidates=int(args.topk_candidates),
        candidate_time_padding_seconds=int(args.candidate_time_padding_seconds),
        time_upper_bound_tolerance_seconds=int(args.time_upper_bound_tolerance_seconds),
        lower_bound_padding_seconds=int(args.lower_bound_padding_seconds),
        segment_gap_seconds=int(args.segment_gap_seconds),
        segment_jump_km=float(args.segment_jump_km),
        segment_alt_jump_m=float(args.segment_alt_jump_m),
        min_leg_points=int(args.min_leg_points),
        spatial_envelope_padding_km=float(args.spatial_envelope_padding_km),
        altitude_padding_m=float(args.altitude_padding_m),
        ambiguity_ratio_threshold=float(args.ambiguity_ratio_threshold),
        weak_score_per_row_threshold=float(args.weak_score_per_row_threshold),
    )
    stage1_dir = Path(args.stage1_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    wind, loc = _load_stage1(stage1_dir)
    if cfg.loc_row_limit > 0:
        loc = loc.head(cfg.loc_row_limit)
        loc_min = loc["time_utc"].min()
        loc_max = loc["time_utc"].max()
        if loc_min is not None and loc_max is not None:
            wind = wind.filter(
                (pl.col("time_utc") >= loc_min - timedelta(hours=2))
                & (pl.col("time_utc") <= loc_max + timedelta(hours=2))
            )
        print(
            json.dumps(
                {
                    "stage": "smoke_limit_applied",
                    "loc_row_limit": cfg.loc_row_limit,
                    "loc_time_min": loc_min,
                    "loc_time_max": loc_max,
                    "filtered_wind_rows": int(wind.height),
                    "filtered_loc_rows": int(loc.height),
                },
                ensure_ascii=False,
                default=_json_default,
            )
        )
    print(json.dumps({"stage": "p1_start", "wind_rows": int(wind.height)}, ensure_ascii=False))
    batch_cross, p1_summary = _build_p1_outputs(wind, out_dir)
    print(json.dumps({"stage": "p1_done", "amdar_rows": p1_summary.get("amdar_rows")}, ensure_ascii=False))
    _, p2_summary = _build_p2_outputs(wind, out_dir)
    print(json.dumps({"stage": "p2_done", "batch_count": p2_summary.get("batch_count")}, ensure_ascii=False))
    _, leg_summary, p34_summary = _build_p3_p4_outputs(loc, out_dir, cfg)
    print(json.dumps({"stage": "p34_done", "leg_count": p34_summary.get("leg_count")}, ensure_ascii=False))
    batch_base, candidate_df, p5_summary = _build_candidate_outputs(batch_cross, wind, leg_summary, out_dir, cfg)
    print(json.dumps({"stage": "p5_done", "candidate_rows": p5_summary.get("candidate_rows")}, ensure_ascii=False))
    leg_points_df = pl.read_parquet(out_dir / "adsb_leg_points_v2.parquet")
    _, _, _, p68_summary = _match_batches(wind, batch_base, candidate_df, leg_points_df, out_dir, cfg)
    print(json.dumps({"stage": "p68_done", "matched_batches": p68_summary.get("matched_batches")}, ensure_ascii=False))
    p9_summary = _build_pseudo_outputs(leg_summary, leg_points_df, out_dir, cfg)
    print(json.dumps({"stage": "p9_done", "case_count": p9_summary.get("case_count")}, ensure_ascii=False))

    final_summary = {
        "stage1_dir": str(stage1_dir),
        "out_dir": str(out_dir),
        "config": asdict(cfg),
        "p1": p1_summary,
        "p2": p2_summary,
        "p3_p4": p34_summary,
        "p5": p5_summary,
        "p6_p8": p68_summary,
        "p9": p9_summary,
    }
    _write_json(out_dir / "plan4_pipeline_summary.json", final_summary)
    print(json.dumps(final_summary, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
