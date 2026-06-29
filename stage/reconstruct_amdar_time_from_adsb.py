from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import polars as pl


EARTH_RADIUS_KM = 6371.0


@dataclass
class MatchConfig:
    segment_gap_seconds: int = 1800
    segment_jump_km: float = 300.0
    segment_alt_jump_m: float = 5000.0
    candidate_time_padding_seconds: int = 3600
    time_upper_bound_tolerance_seconds: int = 60
    topk_candidates: int = 6
    horizontal_weight_km: float = 1.0
    vertical_weight_per_km: float = 0.25
    min_segment_points: int = 5
    duplicate_groups_only: bool = True
    ambiguity_ratio_threshold: float = 1.15
    reject_score_per_row: float = 30.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconstruct AMDAR pseudo UTC time from ADS-B/location trajectories.")
    parser.add_argument("--stage1-dir", default="/data/LFT-W02_data/pengxu/stage1_output")
    parser.add_argument("--out-dir", default="/data/LFT-W02_data/pengxu/优化/数据处理/amdar_adsb_time_reconstruction_20260628")
    parser.add_argument("--segment-gap-seconds", type=int, default=1800)
    parser.add_argument("--segment-jump-km", type=float, default=300.0)
    parser.add_argument("--segment-alt-jump-m", type=float, default=5000.0)
    parser.add_argument("--candidate-time-padding-seconds", type=int, default=7200)
    parser.add_argument("--time-upper-bound-tolerance-seconds", type=int, default=60)
    parser.add_argument("--topk-candidates", type=int, default=12)
    parser.add_argument("--horizontal-weight-km", type=float, default=1.0)
    parser.add_argument("--vertical-weight-per-km", type=float, default=0.25)
    parser.add_argument("--min-segment-points", type=int, default=5)
    parser.add_argument("--duplicate-groups-only", type=int, default=1)
    parser.add_argument("--ambiguity-ratio-threshold", type=float, default=1.15)
    parser.add_argument("--reject-score-per-row", type=float, default=30.0)
    parser.add_argument("--sample-limit", type=int, default=0, help="0 means full dataset")
    return parser.parse_args()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _load_inputs(stage1_dir: Path, sample_limit: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    wind = (
        pl.read_parquet(stage1_dir / "clean_wind.parquet")
        .filter(pl.col("source") == "amdar")
        .with_columns(
            [
                pl.col("time_utc").cast(pl.Datetime, strict=False).alias("time_utc"),
                pl.col("time_beijing").cast(pl.Datetime, strict=False).alias("time_beijing"),
                pl.col("lat_clean").cast(pl.Float64, strict=False).alias("lat_clean"),
                pl.col("lon_clean").cast(pl.Float64, strict=False).alias("lon_clean"),
                pl.col("alt_meters").cast(pl.Float64, strict=False).alias("alt_meters"),
                pl.col("wind_dir").cast(pl.Float64, strict=False).alias("wind_dir"),
                pl.col("wind_speed").cast(pl.Float64, strict=False).alias("wind_speed"),
                pl.col("source_row_index").cast(pl.Int64, strict=False).alias("source_row_index"),
                pl.col("amdar_batch_time_utc").cast(pl.Datetime, strict=False).alias("amdar_batch_time_utc"),
                pl.col("机尾号").cast(pl.Utf8, strict=False).alias("tail_number"),
                pl.col("航班号").cast(pl.Utf8, strict=False).alias("flight_number"),
                pl.col("飞行阶段").cast(pl.Utf8, strict=False).alias("flight_phase"),
            ]
        )
        .sort(["flight_id", "source_row_index"])
    )
    if sample_limit > 0:
        wind = wind.head(sample_limit)

    loc = (
        pl.read_parquet(stage1_dir / "clean_loc.parquet")
        .with_columns(
            [
                pl.col("time_utc").cast(pl.Datetime, strict=False).alias("time_utc"),
                pl.col("lat_clean").cast(pl.Float64, strict=False).alias("lat_clean"),
                pl.col("lon_clean").cast(pl.Float64, strict=False).alias("lon_clean"),
                pl.col("alt_meters").cast(pl.Float64, strict=False).alias("alt_meters"),
                pl.col("heading_deg").cast(pl.Float64, strict=False).alias("heading_deg"),
                pl.col("机尾号").cast(pl.Utf8, strict=False).alias("tail_number"),
                pl.col("航班号").cast(pl.Utf8, strict=False).alias("flight_number"),
            ]
        )
        .drop_nulls(["time_utc", "lat_clean", "lon_clean", "alt_meters"])
        .sort(["tail_number", "flight_number", "flight_id", "time_utc"])
    )
    return wind, loc


def _normalize_key(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else fallback


def _build_location_segments(loc: pl.DataFrame, cfg: MatchConfig) -> dict[str, Any]:
    loc = (
        loc.with_columns(
            [
                pl.col("tail_number").fill_null("missing_tail").alias("tail_key"),
                pl.coalesce(
                    [
                        pl.col("flight_number").cast(pl.Utf8, strict=False),
                        pl.col("flight_id").cast(pl.Utf8, strict=False),
                    ]
                )
                .fill_null("missing_flight")
                .alias("flight_key"),
            ]
        )
        .with_columns(
            [
                pl.col("time_utc").shift(1).over(["tail_key", "flight_key"]).alias("prev_time_utc"),
                pl.col("lat_clean").shift(1).over(["tail_key", "flight_key"]).alias("prev_lat_clean"),
                pl.col("lon_clean").shift(1).over(["tail_key", "flight_key"]).alias("prev_lon_clean"),
                pl.col("alt_meters").shift(1).over(["tail_key", "flight_key"]).alias("prev_alt_meters"),
            ]
        )
        .with_columns(
            [
                (pl.col("time_utc") - pl.col("prev_time_utc")).dt.total_seconds().alias("dt_from_prev_sec"),
                (
                    (
                        (pl.col("lat_clean") - pl.col("prev_lat_clean")) ** 2
                        + (pl.col("lon_clean") - pl.col("prev_lon_clean")) ** 2
                    )
                    .sqrt()
                    * 111.0
                ).alias("jump_km_approx"),
                (pl.col("alt_meters") - pl.col("prev_alt_meters")).abs().alias("alt_jump_m"),
            ]
        )
        .with_columns(
            pl.when(
                pl.col("dt_from_prev_sec").is_null()
                | (pl.col("dt_from_prev_sec") > cfg.segment_gap_seconds)
                | (pl.col("jump_km_approx") > cfg.segment_jump_km)
                | (pl.col("alt_jump_m") > cfg.segment_alt_jump_m)
            )
            .then(1)
            .otherwise(0)
            .alias("segment_start_flag")
        )
        .with_columns(
            pl.col("segment_start_flag")
            .cum_sum()
            .over(["tail_key", "flight_key"])
            .alias("segment_id")
        )
    )

    rows = loc.select(
        [
            "flight_id",
            "tail_key",
            "flight_key",
            "time_utc",
            "lat_clean",
            "lon_clean",
            "alt_meters",
            "heading_deg",
            "segment_id",
        ]
    ).to_dicts()

    by_identity: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        identity_key = f"{row['tail_key']}__{row['flight_key']}"
        by_identity.setdefault(identity_key, []).append(row)

    all_segments: list[dict[str, Any]] = []
    segments_by_tail: dict[str, list[dict[str, Any]]] = {}
    segments_by_flight: dict[str, list[dict[str, Any]]] = {}
    segments_by_identity: dict[str, list[dict[str, Any]]] = {}

    for identity_key, seq in by_identity.items():
        segs: dict[int, list[dict[str, Any]]] = {}
        for row in seq:
            segs.setdefault(int(row["segment_id"]), []).append(row)
        for seg_id, items in segs.items():
            if len(items) < cfg.min_segment_points:
                continue
            tail_key = _normalize_key(items[0].get("tail_key"), "missing_tail")
            flight_key = _normalize_key(items[0].get("flight_key"), "missing_flight")
            segment = {
                "segment_id": f"{tail_key}__{flight_key}__seg{seg_id}",
                "rows": items,
                "t_min": items[0]["time_utc"],
                "t_max": items[-1]["time_utc"],
                "tail_key": tail_key,
                "flight_key": flight_key,
                "flight_id": _normalize_key(items[0].get("flight_id"), "missing_flight_id"),
            }
            all_segments.append(segment)
            segments_by_tail.setdefault(tail_key, []).append(segment)
            segments_by_flight.setdefault(flight_key, []).append(segment)
            segments_by_identity.setdefault(identity_key, []).append(segment)

    for mapping in (segments_by_tail, segments_by_flight, segments_by_identity):
        for key, segments in mapping.items():
            mapping[key] = sorted(segments, key=lambda x: x["t_min"])
    all_segments = sorted(all_segments, key=lambda x: x["t_min"])
    return {
        "all_segments": all_segments,
        "segments_by_tail": segments_by_tail,
        "segments_by_flight": segments_by_flight,
        "segments_by_identity": segments_by_identity,
    }


def _prepare_amdar_groups(wind: pl.DataFrame, duplicate_groups_only: bool) -> list[dict[str, Any]]:
    if "amdar_batch_id" in wind.columns:
        grouped = (
            wind.group_by("amdar_batch_id")
            .agg(
                [
                    pl.col("flight_id").first().alias("flight_id"),
                    pl.col("time_utc").first().alias("time_utc"),
                    pl.col("time_beijing").first().alias("time_beijing"),
                    pl.col("amdar_batch_time_utc").first().alias("amdar_batch_time_utc"),
                    pl.col("tail_number").first().alias("tail_number"),
                    pl.col("flight_number").first().alias("flight_number"),
                    pl.col("flight_phase").first().alias("flight_phase"),
                    pl.col("source_row_index").min().alias("source_row_index_min"),
                    pl.col("source_row_index").max().alias("source_row_index_max"),
                    pl.col("lat_clean").mean().alias("lat_mean"),
                    pl.col("lon_clean").mean().alias("lon_mean"),
                    pl.col("alt_meters").mean().alias("alt_mean"),
                    pl.col("amdar_observation_order").max().alias("rows"),
                    pl.col("amdar_batch_row_count").first().alias("batch_row_count"),
                    pl.col("amdar_batch_contiguous_block_index").first().alias("batch_block_index"),
                ]
            )
            .with_columns(
                pl.coalesce(
                    [
                        pl.col("batch_row_count").cast(pl.Int64, strict=False),
                        pl.col("rows").cast(pl.Int64, strict=False),
                    ]
                ).alias("rows")
            )
            .sort(["tail_number", "flight_number", "time_utc", "source_row_index_min"])
            .with_columns(
                pl.col("amdar_batch_time_utc")
                .shift(1)
                .over(["tail_number", "flight_number"])
                .alias("previous_batch_end_time_utc")
            )
        )
    else:
        grouped = (
            wind.group_by(["flight_id", "time_utc"])
            .agg(
                [
                    pl.len().alias("rows"),
                    pl.col("source_row_index").min().alias("source_row_index_min"),
                    pl.col("source_row_index").max().alias("source_row_index_max"),
                    pl.col("lat_clean").mean().alias("lat_mean"),
                    pl.col("lon_clean").mean().alias("lon_mean"),
                    pl.col("alt_meters").mean().alias("alt_mean"),
                    pl.col("time_beijing").first().alias("time_beijing"),
                    pl.col("tail_number").first().alias("tail_number"),
                    pl.col("flight_number").first().alias("flight_number"),
                    pl.col("flight_phase").first().alias("flight_phase"),
                ]
            )
            .with_columns(
                [
                    pl.col("time_utc").alias("amdar_batch_time_utc"),
                    pl.lit(None, dtype=pl.Utf8).alias("amdar_batch_id"),
                    pl.lit(None, dtype=pl.Datetime).alias("previous_batch_end_time_utc"),
                ]
            )
            .sort(["tail_number", "flight_number", "time_utc", "source_row_index_min"])
        )
    if duplicate_groups_only:
        grouped = grouped.filter(pl.col("rows") > 1)
    return grouped.to_dicts()


def _segment_candidate_score(group: dict[str, Any], segment_rows: list[dict[str, Any]], cfg: MatchConfig) -> float:
    best = None
    for item in segment_rows:
        h_km = _haversine_km(group["lat_mean"], group["lon_mean"], item["lat_clean"], item["lon_clean"])
        z_km = abs(float(group["alt_mean"]) - float(item["alt_meters"])) / 1000.0
        score = h_km * cfg.horizontal_weight_km + z_km * cfg.vertical_weight_per_km
        if best is None or score < best:
            best = score
    return float(best if best is not None else 1e18)


def _candidate_segments_for_group(group: dict[str, Any], segment_catalog: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    tail_key = _normalize_key(group.get("tail_number"), "missing_tail")
    flight_key = _normalize_key(group.get("flight_number"), "missing_flight")
    identity_key = f"{tail_key}__{flight_key}"

    by_identity = segment_catalog["segments_by_identity"]
    by_tail = segment_catalog["segments_by_tail"]
    by_flight = segment_catalog["segments_by_flight"]

    if identity_key in by_identity:
        return by_identity[identity_key], "tail_and_flight_exact"
    if tail_key != "missing_tail" and tail_key in by_tail:
        tail_segments = by_tail[tail_key]
        flight_exact = [seg for seg in tail_segments if seg.get("flight_key") == flight_key]
        if flight_exact:
            return flight_exact, "tail_exact_with_flight_exact_subset"
        return tail_segments, "tail_exact_only"
    if flight_key != "missing_flight" and flight_key in by_flight:
        return by_flight[flight_key], "flight_only"
    return [], "no_identity_match"


def _filtered_segment_rows_for_group(group: dict[str, Any], segment: dict[str, Any], cfg: MatchConfig) -> list[dict[str, Any]]:
    upper_bound = group.get("amdar_batch_time_utc") or group.get("time_utc")
    lower_bound = group.get("previous_batch_end_time_utc")
    upper_pad = cfg.time_upper_bound_tolerance_seconds
    lower_pad = cfg.candidate_time_padding_seconds
    out = []
    for row in segment["rows"]:
        t = row["time_utc"]
        if upper_bound is not None:
            dt_upper = float((t - upper_bound).total_seconds())
            if dt_upper > upper_pad:
                continue
        if lower_bound is not None:
            dt_lower = float((t - lower_bound).total_seconds())
            if dt_lower < -lower_pad:
                continue
        out.append(row)
    return out


def _top_segment_candidates(group: dict[str, Any], segments: list[dict[str, Any]], cfg: MatchConfig) -> list[dict[str, Any]]:
    upper_bound = group.get("amdar_batch_time_utc") or group.get("time_utc")
    out = []
    for segment in segments:
        if upper_bound is not None:
            pad = cfg.candidate_time_padding_seconds
            dt_to_range = 0.0
            if upper_bound < segment["t_min"]:
                dt_to_range = float((segment["t_min"] - upper_bound).total_seconds())
            elif upper_bound > segment["t_max"]:
                dt_to_range = float((upper_bound - segment["t_max"]).total_seconds())
            if dt_to_range > pad:
                continue
        segment_rows = _filtered_segment_rows_for_group(group, segment, cfg)
        if len(segment_rows) < int(group["rows"]):
            continue
        score = _segment_candidate_score(group, segment_rows, cfg)
        if score > 600.0:
            continue
        out.append({"score": score, "segment": segment, "segment_rows": segment_rows})
    out.sort(key=lambda x: x["score"])
    return out[: cfg.topk_candidates]


def _group_rows_for_match(group: dict[str, Any], wind: pl.DataFrame) -> list[dict[str, Any]]:
    if group.get("amdar_batch_id") is not None and "amdar_batch_id" in wind.columns:
        batch_filter = pl.col("amdar_batch_id") == group["amdar_batch_id"]
    else:
        batch_filter = (
            (pl.col("flight_id") == group["flight_id"])
            & (pl.col("time_utc") == group["time_utc"])
        )
    sort_key = "amdar_observation_order" if "amdar_observation_order" in wind.columns else "source_row_index"
    select_cols = [
        "source_row_index",
        "flight_id",
        "time_utc",
        "time_beijing",
        "lat_clean",
        "lon_clean",
        "alt_meters",
        "wind_dir",
        "wind_speed",
        "tail_number",
        "flight_number",
        "flight_phase",
        "amdar_batch_time_utc",
        "amdar_observation_order",
        "raw_row_number",
        "amdar_batch_id",
    ]
    existing_select_cols = [c for c in select_cols if c in wind.columns]
    rows = (
        wind.filter(batch_filter)
        .sort(sort_key)
        .select(existing_select_cols)
        .to_dicts()
    )
    return rows


def _fit_rows_to_segment(group_rows: list[dict[str, Any]], segment_rows: list[dict[str, Any]], cfg: MatchConfig) -> tuple[list[dict[str, Any]], float]:
    n = len(segment_rows)
    if n == 0:
        return [], float("inf")

    dp: list[list[tuple[float, int] | None]] = [[None] * n for _ in range(len(group_rows))]

    def cost(amdar_row: dict[str, Any], seg_row: dict[str, Any]) -> float:
        h_km = _haversine_km(amdar_row["lat_clean"], amdar_row["lon_clean"], seg_row["lat_clean"], seg_row["lon_clean"])
        z_km = abs(float(amdar_row["alt_meters"]) - float(seg_row["alt_meters"])) / 1000.0
        return h_km * cfg.horizontal_weight_km + z_km * cfg.vertical_weight_per_km

    for j in range(n):
        dp[0][j] = (cost(group_rows[0], segment_rows[j]), -1)

    for i in range(1, len(group_rows)):
        prefix_best_score = float("inf")
        prefix_best_idx = -1
        for j in range(n):
            prev = dp[i - 1][j]
            if prev is not None and prev[0] < prefix_best_score:
                prefix_best_score = prev[0]
                prefix_best_idx = j
            if prefix_best_idx >= 0:
                dp[i][j] = (prefix_best_score + cost(group_rows[i], segment_rows[j]), prefix_best_idx)

    best_j = None
    best_score = float("inf")
    last_row = dp[-1]
    for j, cell in enumerate(last_row):
        if cell is not None and cell[0] < best_score:
            best_score = cell[0]
            best_j = j
    if best_j is None:
        return [], float("inf")

    idxs = [0] * len(group_rows)
    cur_j = best_j
    for i in range(len(group_rows) - 1, -1, -1):
        idxs[i] = cur_j
        prev_j = dp[i][cur_j][1] if dp[i][cur_j] is not None else -1
        cur_j = prev_j if prev_j >= 0 else cur_j

    matched = []
    for amdar_row, seg_idx in zip(group_rows, idxs):
        seg_row = segment_rows[seg_idx]
        h_km = _haversine_km(amdar_row["lat_clean"], amdar_row["lon_clean"], seg_row["lat_clean"], seg_row["lon_clean"])
        z_m = abs(float(amdar_row["alt_meters"]) - float(seg_row["alt_meters"]))
        matched.append(
            {
                **amdar_row,
                "matched_segment_index": int(seg_idx),
                "reconstructed_time_utc": seg_row["time_utc"],
                "matched_adsb_time_utc": seg_row["time_utc"],
                "matched_adsb_lat": seg_row["lat_clean"],
                "matched_adsb_lon": seg_row["lon_clean"],
                "matched_adsb_alt_m": seg_row["alt_meters"],
                "matched_adsb_heading_deg": seg_row.get("heading_deg"),
                "match_horizontal_km": h_km,
                "match_vertical_m": z_m,
                "match_direction_metric_removed_reason": "amdar_wind_dir_is_meteorological_wind_from_direction_not_aircraft_heading",
                "time_uncertainty_seconds": 60.0,
                "match_score": h_km * cfg.horizontal_weight_km + (z_m / 1000.0) * cfg.vertical_weight_per_km,
            }
        )
    return matched, float(best_score)


def reconstruct(stage1_dir: Path, out_dir: Path, cfg: MatchConfig, sample_limit: int) -> dict[str, Any]:
    wind, loc = _load_inputs(stage1_dir, sample_limit)
    segment_catalog = _build_location_segments(loc, cfg)
    amdar_groups = _prepare_amdar_groups(wind, cfg.duplicate_groups_only)

    matched_rows: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []

    for group in amdar_groups:
        segments, identity_match_mode = _candidate_segments_for_group(group, segment_catalog)
        group_rows = _group_rows_for_match(group, wind)

        if not segments or not group_rows:
            group_summaries.append(
                {
                    "flight_id": str(group["flight_id"]),
                    "amdar_batch_id": group.get("amdar_batch_id"),
                    "amdar_time_utc": str(group["time_utc"]),
                    "amdar_batch_time_utc": str(group.get("amdar_batch_time_utc")),
                    "group_rows": int(group["rows"]),
                    "status": "no_adsb_segment",
                    "identity_match_mode": identity_match_mode,
                }
            )
            continue

        top_segments = _top_segment_candidates(group, segments, cfg)
        if not top_segments:
            group_summaries.append(
                {
                    "flight_id": str(group["flight_id"]),
                    "amdar_batch_id": group.get("amdar_batch_id"),
                    "amdar_time_utc": str(group["time_utc"]),
                    "amdar_batch_time_utc": str(group.get("amdar_batch_time_utc")),
                    "group_rows": int(group["rows"]),
                    "status": "no_candidate_segment",
                    "identity_match_mode": identity_match_mode,
                }
            )
            continue

        best_match = None
        second_best_score = None
        for cand in top_segments:
            matched, total_score = _fit_rows_to_segment(group_rows, cand["segment_rows"], cfg)
            if matched and (best_match is None or total_score < best_match["total_score"]):
                if best_match is not None:
                    second_best_score = best_match["total_score"]
                best_match = {
                    "matched": matched,
                    "total_score": total_score,
                    "segment": cand["segment"],
                    "segment_rows": cand["segment_rows"],
                    "segment_seed_score": cand["score"],
                }
            elif matched:
                if second_best_score is None or total_score < second_best_score:
                    second_best_score = total_score

        if best_match is None:
            group_summaries.append(
                {
                    "flight_id": str(group["flight_id"]),
                    "amdar_batch_id": group.get("amdar_batch_id"),
                    "amdar_time_utc": str(group["time_utc"]),
                    "amdar_batch_time_utc": str(group.get("amdar_batch_time_utc")),
                    "group_rows": int(group["rows"]),
                    "status": "fit_failed",
                    "identity_match_mode": identity_match_mode,
                }
            )
            continue

        rows_count = max(1, int(group["rows"]))
        per_row_score = float(best_match["total_score"]) / rows_count
        ambiguity_ratio = (
            float(second_best_score / best_match["total_score"])
            if second_best_score is not None and best_match["total_score"] > 0
            else None
        )

        reject_reason = None
        if per_row_score > cfg.reject_score_per_row:
            reject_reason = "score_per_row_too_high"
        elif ambiguity_ratio is not None and ambiguity_ratio <= cfg.ambiguity_ratio_threshold:
            reject_reason = "candidate_ambiguity_too_high"

        if reject_reason is not None:
            group_summaries.append(
                {
                    "flight_id": str(group["flight_id"]),
                    "amdar_batch_id": group.get("amdar_batch_id"),
                    "amdar_time_utc": str(group["time_utc"]),
                    "amdar_batch_time_utc": str(group.get("amdar_batch_time_utc")),
                    "group_rows": int(group["rows"]),
                    "status": "rejected",
                    "identity_match_mode": identity_match_mode,
                    "matched_segment_id": str(best_match["segment"]["segment_id"]),
                    "fit_total_score": float(best_match["total_score"]),
                    "fit_score_per_row": per_row_score,
                    "second_best_total_score": float(second_best_score) if second_best_score is not None else None,
                    "match_ambiguity_ratio": ambiguity_ratio,
                    "reject_reason": reject_reason,
                }
            )
            continue

        for row in best_match["matched"]:
            row["matched_segment_id"] = str(best_match["segment"]["segment_id"])
            row["matched_segment_t_min"] = best_match["segment"]["t_min"]
            row["matched_segment_t_max"] = best_match["segment"]["t_max"]
            row["matched_segment_seed_score"] = float(best_match["segment_seed_score"])
            row["identity_match_mode"] = identity_match_mode
            row["best_match_total_score"] = float(best_match["total_score"])
            row["best_match_score_per_row"] = per_row_score
            row["second_best_total_score"] = float(second_best_score) if second_best_score is not None else None
            row["match_ambiguity_ratio"] = ambiguity_ratio
            row["candidate_leg_count"] = len(top_segments)
            row["time_quality_level"] = (
                "A"
                if per_row_score <= 5.0
                else "B"
                if per_row_score <= 12.0
                else "C"
            )
            row["usage_role"] = "research_candidate_not_strict_truth"
            row["strict_time_truth"] = False
            row["reject_reason"] = None
            row["batch_end_constraint_pass"] = bool(
                row.get("reconstructed_time_utc") is not None
                and group.get("amdar_batch_time_utc") is not None
                and row["reconstructed_time_utc"] <= group["amdar_batch_time_utc"]
            )
            matched_rows.append(row)

        group_summaries.append(
            {
                "flight_id": str(group["flight_id"]),
                "amdar_batch_id": group.get("amdar_batch_id"),
                "amdar_time_utc": str(group["time_utc"]),
                "amdar_batch_time_utc": str(group.get("amdar_batch_time_utc")),
                "group_rows": int(group["rows"]),
                "status": "matched",
                "identity_match_mode": identity_match_mode,
                "candidate_leg_count": len(top_segments),
                "matched_segment_id": str(best_match["segment"]["segment_id"]),
                "segment_seed_score": float(best_match["segment_seed_score"]),
                "fit_total_score": float(best_match["total_score"]),
                "fit_score_per_row": per_row_score,
                "second_best_total_score": float(second_best_score) if second_best_score is not None else None,
                "match_ambiguity_ratio": ambiguity_ratio,
                "reconstructed_time_min_utc": str(best_match["matched"][0]["reconstructed_time_utc"]),
                "reconstructed_time_max_utc": str(best_match["matched"][-1]["reconstructed_time_utc"]),
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    match_df = pl.from_dicts(matched_rows) if matched_rows else pl.DataFrame()
    groups_df = pl.from_dicts(group_summaries) if group_summaries else pl.DataFrame()
    if len(match_df) > 0:
        match_df.write_parquet(out_dir / "amdar_adsb_reconstructed_times.parquet")
    if len(groups_df) > 0:
        groups_df.write_parquet(out_dir / "amdar_adsb_group_match_summary.parquet")

    summary = {
        "stage1_dir": str(stage1_dir),
        "output_dir": str(out_dir),
        "sample_limit": int(sample_limit),
        "config": asdict(cfg),
        "amdar_rows": int(wind.height),
        "amdar_groups": int(len(amdar_groups)),
        "matched_rows": int(len(matched_rows)),
        "matched_groups": int(sum(1 for x in group_summaries if x.get("status") == "matched")),
        "rejected_groups": int(sum(1 for x in group_summaries if x.get("status") == "rejected")),
        "unmatched_groups": int(sum(1 for x in group_summaries if x.get("status") not in {"matched", "rejected"})),
    }

    if len(match_df) > 0:
        summary["matched_row_ratio"] = float(len(match_df) / max(1, wind.height))
        summary["match_horizontal_km_q50"] = float(match_df["match_horizontal_km"].quantile(0.5))
        summary["match_horizontal_km_q90"] = float(match_df["match_horizontal_km"].quantile(0.9))
        summary["match_vertical_m_q50"] = float(match_df["match_vertical_m"].quantile(0.5))
        summary["match_vertical_m_q90"] = float(match_df["match_vertical_m"].quantile(0.9))
        summary["time_uncertainty_seconds_q50"] = float(match_df["time_uncertainty_seconds"].quantile(0.5))
        summary["time_uncertainty_seconds_q90"] = float(match_df["time_uncertainty_seconds"].quantile(0.9))
        summary["best_match_score_per_row_q50"] = float(match_df["best_match_score_per_row"].quantile(0.5))
        summary["best_match_score_per_row_q90"] = float(match_df["best_match_score_per_row"].quantile(0.9))
        summary["direction_metric_removed_reason"] = "AMDAR wind_dir is a meteorological wind direction and cannot be compared to ADS-B aircraft heading"

    (out_dir / "amdar_adsb_reconstruction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    args = _parse_args()
    cfg = MatchConfig(
        segment_gap_seconds=int(args.segment_gap_seconds),
        segment_jump_km=float(args.segment_jump_km),
        segment_alt_jump_m=float(args.segment_alt_jump_m),
        candidate_time_padding_seconds=int(args.candidate_time_padding_seconds),
        time_upper_bound_tolerance_seconds=int(args.time_upper_bound_tolerance_seconds),
        topk_candidates=int(args.topk_candidates),
        horizontal_weight_km=float(args.horizontal_weight_km),
        vertical_weight_per_km=float(args.vertical_weight_per_km),
        min_segment_points=int(args.min_segment_points),
        duplicate_groups_only=bool(int(args.duplicate_groups_only)),
        ambiguity_ratio_threshold=float(args.ambiguity_ratio_threshold),
        reject_score_per_row=float(args.reject_score_per_row),
    )
    summary = reconstruct(Path(args.stage1_dir), Path(args.out_dir), cfg, int(args.sample_limit))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
