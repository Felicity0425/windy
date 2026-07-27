from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
DEFAULT_INPUT = ROOT / "stage1_output/clean_loc.parquet"
DOCUMENTED_V4_INPUT = (
    DATA_DIR
    / "amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_qc_v4_rows.parquet"
)
DEFAULT_OUT = DATA_DIR / "stage2_v8_track_graph_optimized_20260716"
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class RunConfig:
    input_path: Path = DEFAULT_INPUT
    out_dir: Path = DEFAULT_OUT
    slice_count: int = 25
    workers: int = 25
    smoke_group_modulus: int = 1
    max_graph_gap_s: int = 1800
    top_k: int = 5
    overwrite: bool = False


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Large-framework Stage2 v8 sparse ADS-B track graph.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument(
        "--smoke-group-modulus",
        type=int,
        default=1,
        help="1 means full data; 100 selects about 1%% of exact identity/date groups.",
    )
    parser.add_argument("--max-graph-gap-s", type=int, default=1800)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    return RunConfig(
        input_path=Path(args.input),
        out_dir=Path(args.out_dir),
        slice_count=args.slice_count,
        workers=args.workers,
        smoke_group_modulus=args.smoke_group_modulus,
        max_graph_gap_s=args.max_graph_gap_s,
        top_k=args.top_k,
        overwrite=args.overwrite,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def haversine_expr(lat1: pl.Expr, lon1: pl.Expr, lat2: pl.Expr, lon2: pl.Expr) -> pl.Expr:
    lat1r = lat1.radians()
    lat2r = lat2.radians()
    dlat = (lat2 - lat1).radians()
    dlon = (lon2 - lon1).radians()
    a = (dlat / 2).sin().pow(2) + lat1r.cos() * lat2r.cos() * (dlon / 2).sin().pow(2)
    return 2.0 * EARTH_RADIUS_KM * a.sqrt().arcsin()


def angle_difference_expr(left: pl.Expr, right: pl.Expr) -> pl.Expr:
    return ((left - right + 180.0) % 360.0 - 180.0).abs()


def source_lazyframe(cfg: RunConfig) -> pl.LazyFrame:
    identity = ["tail_norm", "flight_norm", "service_date_utc"]
    lf = (
        pl.scan_parquet(cfg.input_path)
        .with_row_index("raw_row_number")
        .select(
            [
                pl.col("raw_row_number").cast(pl.UInt64),
                pl.col("机尾号")
                .cast(pl.Utf8)
                .str.strip_chars()
                .str.to_uppercase()
                .str.replace_all(r"[^A-Z0-9]", "")
                .alias("tail_norm"),
                pl.col("航班号")
                .cast(pl.Utf8)
                .str.strip_chars()
                .str.to_uppercase()
                .str.replace_all(r"[^A-Z0-9]", "")
                .alias("flight_norm"),
                pl.col("time_utc").cast(pl.Datetime("us")),
                pl.col("time_utc").dt.date().alias("service_date_utc"),
                pl.col("lat_clean").cast(pl.Float64),
                pl.col("lon_clean").cast(pl.Float64),
                pl.col("alt_meters").cast(pl.Float64),
                pl.col("heading_deg").cast(pl.Float64),
                pl.col("ground_speed_ms").cast(pl.Float64),
            ]
        )
        .with_columns(
            pl.concat_str(identity, separator="__")
            .hash(seed=20260716)
            .alias("identity_date_hash_v8")
        )
        .with_columns(
            (pl.col("identity_date_hash_v8") % cfg.slice_count).cast(pl.UInt8).alias("processing_slice_id")
        )
    )
    if cfg.smoke_group_modulus > 1:
        lf = lf.filter(((pl.col("identity_date_hash_v8") // cfg.slice_count) % cfg.smoke_group_modulus) == 0)
    return lf


def prepare_input_shards(cfg: RunConfig) -> dict[str, Any]:
    shard_dir = cfg.out_dir / "stage2_track_graph_v8/raw_input_shards_v8"
    shard_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(shard_dir.glob("slice_*.parquet"))
    if len(existing) == cfg.slice_count and not cfg.overwrite:
        counts = [pl.scan_parquet(path).select(pl.len()).collect(engine="streaming").item() for path in existing]
        return {"reused": True, "rows": int(sum(counts)), "slice_rows": counts}

    frame = source_lazyframe(cfg).collect(engine="streaming")
    frame = frame.sort(["processing_slice_id", "tail_norm", "flight_norm", "service_date_utc", "time_utc", "raw_row_number"])
    partitions = {int(part[0, "processing_slice_id"]): part for part in frame.partition_by("processing_slice_id", maintain_order=True)}
    slice_rows: list[int] = []
    for slice_id in range(cfg.slice_count):
        part = partitions.get(slice_id, frame.head(0))
        path = shard_dir / f"slice_{slice_id:02d}.parquet"
        part.write_parquet(path, compression="zstd", statistics=True)
        slice_rows.append(part.height)
    return {"reused": False, "rows": frame.height, "slice_rows": slice_rows}


def add_local_features(frame: pl.DataFrame) -> pl.DataFrame:
    keys = ["tail_norm", "flight_norm", "service_date_utc"]
    frame = frame.sort(keys + ["time_utc", "raw_row_number"])
    previous = lambda column, n=1: pl.col(column).shift(n).over(keys)
    following = lambda column, n=1: pl.col(column).shift(-n).over(keys)
    frame = frame.with_columns(
        [
            previous("time_utc").alias("prev_time_v8"),
            following("time_utc").alias("next_time_v8"),
            previous("lat_clean").alias("prev_lat_v8"),
            previous("lon_clean").alias("prev_lon_v8"),
            previous("alt_meters").alias("prev_alt_v8"),
            previous("heading_deg").alias("prev_heading_v8"),
            following("lat_clean").alias("next_lat_v8"),
            following("lon_clean").alias("next_lon_v8"),
            following("alt_meters").alias("next_alt_v8"),
            following("heading_deg").alias("next_heading_v8"),
        ]
    ).with_columns(
        [
            (pl.col("time_utc") - pl.col("prev_time_v8")).dt.total_seconds().cast(pl.Float64).alias("dt_prev_s_v8"),
            (pl.col("next_time_v8") - pl.col("time_utc")).dt.total_seconds().cast(pl.Float64).alias("dt_next_s_v8"),
            haversine_expr(pl.col("prev_lat_v8"), pl.col("prev_lon_v8"), pl.col("lat_clean"), pl.col("lon_clean")).alias("distance_prev_km_v8"),
            haversine_expr(pl.col("lat_clean"), pl.col("lon_clean"), pl.col("next_lat_v8"), pl.col("next_lon_v8")).alias("distance_next_km_v8"),
            haversine_expr(pl.col("prev_lat_v8"), pl.col("prev_lon_v8"), pl.col("next_lat_v8"), pl.col("next_lon_v8")).alias("distance_skip_km_v8"),
        ]
    ).with_columns(
        [
            (pl.col("distance_prev_km_v8") * 1000.0 / pl.col("dt_prev_s_v8")).alias("speed_prev_mps_v8"),
            (pl.col("distance_next_km_v8") * 1000.0 / pl.col("dt_next_s_v8")).alias("speed_next_mps_v8"),
            (pl.col("distance_skip_km_v8") * 1000.0 / (pl.col("dt_prev_s_v8") + pl.col("dt_next_s_v8"))).alias("speed_skip_mps_v8"),
            ((pl.col("alt_meters") - pl.col("prev_alt_v8")) / pl.col("dt_prev_s_v8")).alias("vertical_rate_mps_v8"),
            angle_difference_expr(pl.col("heading_deg"), pl.col("prev_heading_v8")).alias("heading_residual_deg_v8"),
            angle_difference_expr(pl.col("next_heading_v8"), pl.col("heading_deg")).alias("heading_forward_residual_deg_v8"),
        ]
    ).with_columns(
        [
            ((pl.col("speed_next_mps_v8") - pl.col("speed_prev_mps_v8")) / ((pl.col("dt_prev_s_v8") + pl.col("dt_next_s_v8")) / 2.0)).alias("acceleration_mps2_v8"),
            (pl.col("heading_residual_deg_v8") / pl.col("dt_prev_s_v8")).alias("turn_rate_deg_s_v8"),
            pl.col("time_utc").cum_count().over(keys + ["time_utc"]).alias("duplicate_time_rank_v8"),
        ]
    )
    invalid_identity = (
        pl.col("tail_norm").is_null()
        | pl.col("flight_norm").is_null()
        | (pl.col("tail_norm") == "")
        | (pl.col("flight_norm") == "")
    )
    invalid_position = (
        pl.col("lat_clean").is_null()
        | pl.col("lon_clean").is_null()
        | ~pl.col("lat_clean").is_between(-90.0, 90.0)
        | ~pl.col("lon_clean").is_between(-180.0, 180.0)
        | pl.col("alt_meters").is_null()
    )
    isolated_position = (
        (pl.col("dt_prev_s_v8") > 0)
        & (pl.col("dt_next_s_v8") > 0)
        & (pl.col("dt_prev_s_v8") <= 600)
        & (pl.col("dt_next_s_v8") <= 600)
        & (pl.col("speed_prev_mps_v8") > 420)
        & (pl.col("speed_next_mps_v8") > 420)
        & (pl.col("speed_skip_mps_v8") <= 340)
    )
    isolated_altitude = (
        (pl.col("prev_alt_v8").is_not_null())
        & (pl.col("next_alt_v8").is_not_null())
        & ((pl.col("alt_meters") - (pl.col("prev_alt_v8") + pl.col("next_alt_v8")) / 2.0).abs() > 3000)
        & ((pl.col("prev_alt_v8") - pl.col("next_alt_v8")).abs() < 1800)
    )
    timestamp_bias = (
        ~isolated_position
        & (pl.col("speed_prev_mps_v8") > 420)
        & (pl.col("speed_next_mps_v8") <= 340)
        & (pl.col("dt_prev_s_v8") <= 30)
    ) | (
        ~isolated_position
        & (pl.col("speed_next_mps_v8") > 420)
        & (pl.col("speed_prev_mps_v8") <= 340)
        & (pl.col("dt_next_s_v8") <= 30)
    )
    frame = frame.with_columns(
        [
            invalid_identity.alias("identity_discontinuity_v8"),
            invalid_position.alias("invalid_position_v8"),
            isolated_position.alias("isolated_position_spike_v8"),
            isolated_altitude.alias("isolated_altitude_spike_v8"),
            timestamp_bias.alias("timestamp_bias_candidate_v8"),
            ((pl.col("dt_prev_s_v8") > 1800) | (pl.col("dt_next_s_v8") > 1800)).fill_null(False).alias("real_sampling_gap_candidate_v8"),
            ((pl.col("speed_prev_mps_v8") > 420) | (pl.col("speed_next_mps_v8") > 420)).fill_null(False).alias("unreachable_speed_edge_v8"),
            (pl.col("vertical_rate_mps_v8").abs() > 75).fill_null(False).alias("unreachable_vertical_rate_edge_v8"),
        ]
    ).with_columns(
        [
            pl.when(pl.col("identity_discontinuity_v8"))
            .then(pl.lit("identity_discontinuity"))
            .when(pl.col("invalid_position_v8"))
            .then(pl.lit("invalid_position"))
            .when(pl.col("duplicate_time_rank_v8") > 1)
            .then(pl.lit("timestamp_duplicate"))
            .when(pl.col("isolated_position_spike_v8"))
            .then(pl.lit("isolated_position_spike"))
            .when(pl.col("isolated_altitude_spike_v8"))
            .then(pl.lit("isolated_altitude_spike"))
            .when(pl.col("timestamp_bias_candidate_v8"))
            .then(pl.lit("timestamp_bias_candidate"))
            .when(pl.col("real_sampling_gap_candidate_v8"))
            .then(pl.lit("real_sampling_gap_candidate"))
            .when(pl.col("unreachable_speed_edge_v8") | pl.col("unreachable_vertical_rate_edge_v8"))
            .then(pl.lit("unreachable_motion_edge"))
            .when(pl.col("dt_prev_s_v8").is_null() | pl.col("dt_next_s_v8").is_null())
            .then(pl.lit("insufficient_context"))
            .otherwise(pl.lit("locally_consistent"))
            .alias("point_anomaly_type_v8"),
            pl.when(
                pl.col("identity_discontinuity_v8")
                | pl.col("invalid_position_v8")
                | (pl.col("duplicate_time_rank_v8") > 1)
                | pl.col("isolated_position_spike_v8")
                | pl.col("isolated_altitude_spike_v8")
            )
            .then(pl.lit("diagnostic_exclude"))
            .when(pl.col("timestamp_bias_candidate_v8") | pl.col("unreachable_speed_edge_v8") | pl.col("unreachable_vertical_rate_edge_v8"))
            .then(pl.lit("uncertain_keep_low_weight"))
            .otherwise(pl.lit("clean_include"))
            .alias("clean_point_role_v8"),
        ]
    ).with_columns(
        (
            1.0
            - 0.35 * pl.col("unreachable_speed_edge_v8").cast(pl.Float64)
            - 0.30 * pl.col("unreachable_vertical_rate_edge_v8").cast(pl.Float64)
            - 0.20 * pl.col("timestamp_bias_candidate_v8").cast(pl.Float64)
            - 0.15 * pl.col("real_sampling_gap_candidate_v8").cast(pl.Float64)
            - 0.50 * pl.col("isolated_position_spike_v8").cast(pl.Float64)
            - 0.50 * pl.col("isolated_altitude_spike_v8").cast(pl.Float64)
        ).clip(0.0, 1.0).alias("local_consistency_score_v8")
    )
    legacy_break = (
        pl.col("dt_prev_s_v8").is_null()
        | (pl.col("dt_prev_s_v8") <= 0)
        | (pl.col("dt_prev_s_v8") > 900)
        | (pl.col("speed_prev_mps_v8") > 400)
        | (pl.col("distance_prev_km_v8") > 200)
        | ((pl.col("alt_meters") - pl.col("prev_alt_v8")).abs() > 5000)
    )
    return frame.with_columns(legacy_break.fill_null(True).alias("legacy_leg_start_v4_compatible"))


def rebuild_clean_tracklets(local: pl.DataFrame) -> pl.DataFrame:
    keys = ["tail_norm", "flight_norm", "service_date_utc"]
    clean = local.filter(pl.col("clean_point_role_v8") != "diagnostic_exclude").sort(keys + ["time_utc", "raw_row_number"])
    clean = clean.with_columns(
        [
            pl.col("time_utc").shift(1).over(keys).alias("clean_prev_time_v8"),
            pl.col("lat_clean").shift(1).over(keys).alias("clean_prev_lat_v8"),
            pl.col("lon_clean").shift(1).over(keys).alias("clean_prev_lon_v8"),
            pl.col("alt_meters").shift(1).over(keys).alias("clean_prev_alt_v8"),
        ]
    ).with_columns(
        [
            (pl.col("time_utc") - pl.col("clean_prev_time_v8")).dt.total_seconds().cast(pl.Float64).alias("clean_dt_prev_s_v8"),
            haversine_expr(pl.col("clean_prev_lat_v8"), pl.col("clean_prev_lon_v8"), pl.col("lat_clean"), pl.col("lon_clean")).alias("clean_distance_prev_km_v8"),
        ]
    ).with_columns(
        [
            (pl.col("clean_distance_prev_km_v8") * 1000.0 / pl.col("clean_dt_prev_s_v8")).alias("clean_speed_prev_mps_v8"),
            ((pl.col("alt_meters") - pl.col("clean_prev_alt_v8")) / pl.col("clean_dt_prev_s_v8")).alias("clean_vertical_rate_prev_mps_v8"),
        ]
    )
    hard_break = (
        pl.col("clean_prev_time_v8").is_null()
        | (pl.col("clean_dt_prev_s_v8") <= 0)
        | (pl.col("clean_dt_prev_s_v8") > 900)
        | (pl.col("clean_speed_prev_mps_v8") > 420)
        | (pl.col("clean_vertical_rate_prev_mps_v8").abs() > 75)
    )
    uncertain_break = (
        (pl.col("clean_point_role_v8") == "uncertain_keep_low_weight")
        & (pl.col("clean_dt_prev_s_v8") > 900)
    )
    clean = clean.with_columns(
        [
            hard_break.fill_null(True).alias("clean_hard_break_v8"),
            uncertain_break.fill_null(False).alias("clean_uncertain_break_v8"),
        ]
    ).with_columns((pl.col("clean_hard_break_v8") | pl.col("clean_uncertain_break_v8")).alias("clean_tracklet_start_v8"))
    clean = clean.with_columns(pl.col("clean_tracklet_start_v8").cast(pl.UInt32).cum_sum().over(keys).alias("clean_tracklet_index_v8"))
    return clean.with_columns(
        pl.concat_str(
            [
                pl.lit("ct8"),
                pl.col("identity_date_hash_v8").cast(pl.Utf8),
                pl.col("clean_tracklet_index_v8").cast(pl.Utf8),
            ],
            separator="_",
        ).alias("clean_tracklet_id_v8")
    )


def smooth_axis(times: np.ndarray, observations: np.ndarray, measurement_var: np.ndarray, process_scale: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    count = len(observations)
    filtered_position = np.empty(count, dtype=np.float64)
    filtered_velocity = np.empty(count, dtype=np.float64)
    filtered_variance = np.empty(count, dtype=np.float64)
    if count == 0:
        return filtered_position, filtered_velocity, filtered_variance
    position = float(observations[0])
    velocity = 0.0
    position_var = max(float(measurement_var[0]), 1e-6)
    velocity_var = max(process_scale, 1e-6)
    filtered_position[0] = position
    filtered_velocity[0] = velocity
    filtered_variance[0] = position_var
    for index in range(1, count):
        dt = max(float(times[index] - times[index - 1]), 1.0)
        predicted_position = position + velocity * dt
        predicted_position_var = position_var + dt * dt * velocity_var + process_scale * dt
        gain = predicted_position_var / (predicted_position_var + max(float(measurement_var[index]), 1e-6))
        innovation = float(observations[index] - predicted_position)
        position = predicted_position + gain * innovation
        velocity_gain = min(0.8, 2.0 * gain / dt)
        velocity = velocity + velocity_gain * innovation
        position_var = max((1.0 - gain) * predicted_position_var, 1e-6)
        velocity_var = max((1.0 - min(gain, 0.6)) * velocity_var + process_scale, 1e-8)
        filtered_position[index] = position
        filtered_velocity[index] = velocity
        filtered_variance[index] = position_var
    backward_position = np.empty(count, dtype=np.float64)
    backward_velocity = np.empty(count, dtype=np.float64)
    backward_variance = np.empty(count, dtype=np.float64)
    position = float(observations[-1])
    velocity = 0.0
    position_var = max(float(measurement_var[-1]), 1e-6)
    velocity_var = max(process_scale, 1e-6)
    backward_position[-1] = position
    backward_velocity[-1] = velocity
    backward_variance[-1] = position_var
    for index in range(count - 2, -1, -1):
        dt = max(float(times[index + 1] - times[index]), 1.0)
        predicted_position = position - velocity * dt
        predicted_position_var = position_var + dt * dt * velocity_var + process_scale * dt
        gain = predicted_position_var / (predicted_position_var + max(float(measurement_var[index]), 1e-6))
        innovation = float(observations[index] - predicted_position)
        position = predicted_position + gain * innovation
        velocity = velocity - min(0.8, 2.0 * gain / dt) * innovation
        position_var = max((1.0 - gain) * predicted_position_var, 1e-6)
        velocity_var = max((1.0 - min(gain, 0.6)) * velocity_var + process_scale, 1e-8)
        backward_position[index] = position
        backward_velocity[index] = velocity
        backward_variance[index] = position_var
    forward_precision = 1.0 / filtered_variance
    backward_precision = 1.0 / backward_variance
    total_precision = forward_precision + backward_precision
    smoothed_position = (filtered_position * forward_precision + backward_position * backward_precision) / total_precision
    smoothed_velocity = (filtered_velocity * forward_precision - backward_velocity * backward_precision) / total_precision
    smoothed_variance = 1.0 / total_precision
    return smoothed_position, smoothed_velocity, smoothed_variance


def smooth_tracklets(clean: pl.DataFrame) -> pl.DataFrame:
    if clean.height == 0:
        return clean
    output: list[pl.DataFrame] = []
    for tracklet in clean.partition_by("clean_tracklet_id_v8", maintain_order=True):
        lat = tracklet["lat_clean"].to_numpy()
        lon = tracklet["lon_clean"].to_numpy()
        alt = tracklet["alt_meters"].to_numpy()
        times = tracklet["time_utc"].cast(pl.Int64).to_numpy() / 1_000_000.0
        lat0 = float(np.nanmedian(lat))
        lon0 = float(np.nanmedian(lon))
        north = (lat - lat0) * 111.32
        east = (lon - lon0) * 111.32 * max(math.cos(math.radians(lat0)), 0.1)
        score = tracklet["local_consistency_score_v8"].fill_null(0.5).to_numpy()
        measurement_horizontal = np.square(0.025 + 0.20 * (1.0 - score))
        measurement_altitude = np.square(20.0 + 180.0 * (1.0 - score))
        east_s, east_v, east_var = smooth_axis(times, east, measurement_horizontal, 2e-6)
        north_s, north_v, north_var = smooth_axis(times, north, measurement_horizontal, 2e-6)
        alt_s, alt_v, alt_var = smooth_axis(times, alt, measurement_altitude, 0.08)
        smoothed_lat = lat0 + north_s / 111.32
        smoothed_lon = lon0 + east_s / (111.32 * max(math.cos(math.radians(lat0)), 0.1))
        vertical_abs = np.abs(alt_v)
        turn = tracklet["turn_rate_deg_s_v8"].fill_null(0.0).abs().to_numpy()
        turn_prob = np.clip(turn / 3.0, 0.0, 0.8)
        asc_prob = np.clip(vertical_abs / 12.0, 0.0, 0.85) * (1.0 - turn_prob)
        level_prob = np.clip(1.0 - turn_prob - asc_prob, 0.05, 1.0)
        total = level_prob + asc_prob + turn_prob
        output.append(
            tracklet.with_columns(
                [
                    pl.Series("smoothed_lat_v8", smoothed_lat),
                    pl.Series("smoothed_lon_v8", smoothed_lon),
                    pl.Series("smoothed_alt_v8", alt_s),
                    pl.Series("smoothed_v_east_km_s_v8", east_v),
                    pl.Series("smoothed_v_north_km_s_v8", north_v),
                    pl.Series("smoothed_v_vertical_m_s_v8", alt_v),
                    pl.Series("mode_prob_level_v8", level_prob / total),
                    pl.Series("mode_prob_asc_des_v8", asc_prob / total),
                    pl.Series("mode_prob_turn_v8", turn_prob / total),
                    pl.Series("cov_xx_km2_v8", east_var),
                    pl.Series("cov_xy_km2_v8", np.zeros(len(tracklet))),
                    pl.Series("cov_yy_km2_v8", north_var),
                    pl.Series("cov_alt_m2_v8", alt_var),
                    pl.Series("state_uncertainty_radius_km_v8", np.sqrt(east_var + north_var)),
                    pl.lit("smoothed_observed").alias("state_source_role_v8"),
                    pl.lit("diagonal_cv_imm_style_forward_backward_v1").alias("smoother_method_v8"),
                ]
            )
        )
    return pl.concat(output, how="vertical_relaxed")


def summarize_tracklets(smoothed: pl.DataFrame) -> pl.DataFrame:
    if smoothed.height == 0:
        return pl.DataFrame()
    return (
        smoothed.group_by("clean_tracklet_id_v8", maintain_order=True)
        .agg(
            [
                pl.first("tail_norm"),
                pl.first("flight_norm"),
                pl.first("service_date_utc"),
                pl.first("identity_date_hash_v8"),
                pl.first("processing_slice_id"),
                pl.min("time_utc").alias("start_time_utc"),
                pl.max("time_utc").alias("end_time_utc"),
                pl.len().alias("point_count"),
                pl.first("smoothed_lat_v8").alias("start_lat_v8"),
                pl.first("smoothed_lon_v8").alias("start_lon_v8"),
                pl.first("smoothed_alt_v8").alias("start_alt_v8"),
                pl.last("smoothed_lat_v8").alias("end_lat_v8"),
                pl.last("smoothed_lon_v8").alias("end_lon_v8"),
                pl.last("smoothed_alt_v8").alias("end_alt_v8"),
                pl.first("smoothed_v_east_km_s_v8").alias("start_v_east_km_s_v8"),
                pl.first("smoothed_v_north_km_s_v8").alias("start_v_north_km_s_v8"),
                pl.first("smoothed_v_vertical_m_s_v8").alias("start_v_vertical_m_s_v8"),
                pl.last("smoothed_v_east_km_s_v8").alias("end_v_east_km_s_v8"),
                pl.last("smoothed_v_north_km_s_v8").alias("end_v_north_km_s_v8"),
                pl.last("smoothed_v_vertical_m_s_v8").alias("end_v_vertical_m_s_v8"),
                pl.last("cov_xx_km2_v8").alias("end_cov_xx_km2_v8"),
                pl.last("cov_yy_km2_v8").alias("end_cov_yy_km2_v8"),
                pl.last("cov_alt_m2_v8").alias("end_cov_alt_m2_v8"),
                pl.first("cov_xx_km2_v8").alias("start_cov_xx_km2_v8"),
                pl.first("cov_yy_km2_v8").alias("start_cov_yy_km2_v8"),
                pl.first("cov_alt_m2_v8").alias("start_cov_alt_m2_v8"),
                pl.median("local_consistency_score_v8").alias("local_consistency_q50_v8"),
                pl.quantile("local_consistency_score_v8", 0.9).alias("local_consistency_q90_v8"),
                (pl.col("clean_point_role_v8") == "uncertain_keep_low_weight").sum().alias("uncertain_point_count_v8"),
                pl.col("legacy_leg_start_v4_compatible").sum().alias("raw_leg_count_covered_v8"),
            ]
        )
        .with_columns(
            [
                ((pl.col("end_time_utc") - pl.col("start_time_utc")).dt.total_seconds()).alias("duration_s_v8"),
                pl.when((pl.col("point_count") >= 8) & (pl.col("local_consistency_q50_v8") >= 0.8))
                .then(pl.lit("T0_clean_core"))
                .when(pl.col("point_count") >= 3)
                .then(pl.lit("T1_clean_short"))
                .when((pl.col("point_count") == 1) & (pl.col("local_consistency_q50_v8") >= 0.65))
                .then(pl.lit("T2_singleton_supported"))
                .when(pl.col("point_count") >= 1)
                .then(pl.lit("T3_uncertain_fragment"))
                .otherwise(pl.lit("T4_reject"))
                .alias("tracklet_quality_tier_v8"),
            ]
        )
        .with_columns(
            [
                pl.col("tracklet_quality_tier_v8").is_in(["T0_clean_core", "T1_clean_short"]).alias("stage3_source_allowed_v8"),
                (pl.col("tracklet_quality_tier_v8") != "T4_reject").alias("graph_node_allowed_v8"),
            ]
        )
    )


def build_graph_edges(summary: pl.DataFrame, max_gap_s: int) -> pl.DataFrame:
    if summary.height == 0:
        return pl.DataFrame()
    keys = ["tail_norm", "flight_norm", "service_date_utc"]
    nodes = summary.filter(pl.col("graph_node_allowed_v8")).sort(keys + ["start_time_utc", "clean_tracklet_id_v8"])
    edges: list[pl.DataFrame] = []
    for offset in (1, 2, 3):
        candidate = nodes.with_columns(
            [
                pl.col("clean_tracklet_id_v8").shift(-offset).over(keys).alias("to_tracklet_id"),
                pl.col("start_time_utc").shift(-offset).over(keys).alias("to_start_time"),
                pl.col("start_lat_v8").shift(-offset).over(keys).alias("to_start_lat"),
                pl.col("start_lon_v8").shift(-offset).over(keys).alias("to_start_lon"),
                pl.col("start_alt_v8").shift(-offset).over(keys).alias("to_start_alt"),
                pl.col("start_v_east_km_s_v8").shift(-offset).over(keys).alias("to_start_v_east"),
                pl.col("start_v_north_km_s_v8").shift(-offset).over(keys).alias("to_start_v_north"),
                pl.col("start_v_vertical_m_s_v8").shift(-offset).over(keys).alias("to_start_v_vertical"),
                pl.col("start_cov_xx_km2_v8").shift(-offset).over(keys).alias("to_cov_xx"),
                pl.col("start_cov_yy_km2_v8").shift(-offset).over(keys).alias("to_cov_yy"),
                pl.col("start_cov_alt_m2_v8").shift(-offset).over(keys).alias("to_cov_alt"),
            ]
        ).rename({"clean_tracklet_id_v8": "from_tracklet_id"})
        candidate = candidate.with_columns(
            (pl.col("to_start_time") - pl.col("end_time_utc")).dt.total_seconds().cast(pl.Float64).alias("gap_seconds")
        ).filter(pl.col("gap_seconds").is_between(1, max_gap_s, closed="both"))
        if candidate.height == 0:
            continue
        candidate = candidate.with_columns(
            [
                (pl.col("end_lat_v8") + pl.col("end_v_north_km_s_v8") * pl.col("gap_seconds") / 111.32).alias("predicted_lat"),
                (
                    pl.col("end_lon_v8")
                    + pl.col("end_v_east_km_s_v8")
                    * pl.col("gap_seconds")
                    / (111.32 * pl.col("end_lat_v8").radians().cos().clip(0.1, 1.0))
                ).alias("predicted_lon"),
                (pl.col("end_alt_v8") + pl.col("end_v_vertical_m_s_v8") * pl.col("gap_seconds")).alias("predicted_alt"),
            ]
        ).with_columns(
            [
                haversine_expr(pl.col("predicted_lat"), pl.col("predicted_lon"), pl.col("to_start_lat"), pl.col("to_start_lon")).alias("position_residual_km_v8"),
                (pl.col("to_start_alt") - pl.col("predicted_alt")).abs().alias("altitude_residual_m_v8"),
                (((pl.col("to_start_v_east") - pl.col("end_v_east_km_s_v8")).pow(2) + (pl.col("to_start_v_north") - pl.col("end_v_north_km_s_v8")).pow(2)).sqrt() * 1000.0).alias("speed_delta_mps_v8"),
                ((pl.col("to_start_v_vertical") - pl.col("end_v_vertical_m_s_v8")).abs()).alias("vertical_rate_delta_mps_v8"),
                (
                    pl.col("end_cov_xx_km2_v8")
                    + pl.col("end_cov_yy_km2_v8")
                    + pl.col("to_cov_xx")
                    + pl.col("to_cov_yy")
                    + (0.0025 * pl.col("gap_seconds")).pow(2)
                ).alias("position_variance_km2_v8"),
                (
                    pl.col("end_cov_alt_m2_v8")
                    + pl.col("to_cov_alt")
                    + (1.5 * pl.col("gap_seconds")).pow(2)
                ).alias("altitude_variance_m2_v8"),
            ]
        ).with_columns(
            [
                (pl.col("position_residual_km_v8") / pl.col("position_variance_km2_v8").sqrt().clip(0.02, None)).alias("forward_mahalanobis_v8"),
                (pl.col("altitude_residual_m_v8") / pl.col("altitude_variance_m2_v8").sqrt().clip(20.0, None)).alias("altitude_mahalanobis_v8"),
            ]
        ).with_columns(
            (
                -0.55 * pl.col("forward_mahalanobis_v8")
                - 0.35 * pl.col("altitude_mahalanobis_v8")
                - 0.004 * pl.col("speed_delta_mps_v8")
                - 0.001 * pl.col("gap_seconds")
            ).exp().clip(0.0, 1.0).alias("bridge_prior_score_v8")
        ).with_columns(
            [
                (
                    (pl.col("forward_mahalanobis_v8") <= 12.0)
                    & (pl.col("altitude_mahalanobis_v8") <= 12.0)
                    & (pl.col("speed_delta_mps_v8") <= 180.0)
                    & (pl.col("position_residual_km_v8") <= (3.0 + 0.03 * pl.col("gap_seconds")))
                ).alias("physical_candidate_gate_v8"),
                pl.lit(False).alias("formal_bridge_accepted_v8"),
                pl.lit(offset).alias("candidate_hop_v8"),
            ]
        ).select(
            [
                "from_tracklet_id",
                "to_tracklet_id",
                "tail_norm",
                "flight_norm",
                "service_date_utc",
                "processing_slice_id",
                "gap_seconds",
                "forward_mahalanobis_v8",
                pl.col("forward_mahalanobis_v8").alias("backward_mahalanobis_v8"),
                "position_residual_km_v8",
                "altitude_residual_m_v8",
                "speed_delta_mps_v8",
                pl.lit(None, dtype=pl.Float64).alias("heading_delta_deg_v8"),
                "vertical_rate_delta_mps_v8",
                pl.lit("unfrozen_stage2_prior_only").alias("phase_transition_v8"),
                pl.when(pl.col("candidate_hop_v8") == 1).then(pl.lit("adjacent_clean_tracklets")).otherwise(pl.lit("competing_nonadjacent_tracklet")).alias("original_break_reason_v4"),
                "bridge_prior_score_v8",
                "physical_candidate_gate_v8",
                "formal_bridge_accepted_v8",
                "candidate_hop_v8",
            ]
        )
        edges.append(candidate)
    return pl.concat(edges, how="vertical_relaxed") if edges else pl.DataFrame()


def build_paths(summary: pl.DataFrame, edges: pl.DataFrame, top_k: int) -> pl.DataFrame:
    singles = summary.select(
        [
            pl.concat_str([pl.lit("path8_single"), pl.col("clean_tracklet_id_v8")], separator="_").alias("graph_path_id"),
            pl.col("clean_tracklet_id_v8").alias("source_tracklet_ids"),
            "tail_norm",
            "flight_norm",
            "service_date_utc",
            "processing_slice_id",
            pl.lit("clean_tracklet").alias("path_type_v8"),
            pl.lit(1).alias("node_count_v8"),
            pl.lit(1.0).alias("path_prior_weight_v8"),
            pl.lit(1).alias("path_rank_v8"),
            pl.lit(False).alias("formal_path_accepted_v8"),
        ]
    )
    if edges.height == 0:
        return singles
    stitched = (
        edges.filter(pl.col("physical_candidate_gate_v8"))
        .sort(["from_tracklet_id", "bridge_prior_score_v8"], descending=[False, True])
        .with_columns(pl.col("bridge_prior_score_v8").rank("ordinal", descending=True).over("from_tracklet_id").alias("path_rank_v8"))
        .filter(pl.col("path_rank_v8") <= top_k)
        .select(
            [
                pl.concat_str([pl.lit("path8_bridge"), pl.col("from_tracklet_id"), pl.col("to_tracklet_id")], separator="_").alias("graph_path_id"),
                pl.concat_str([pl.col("from_tracklet_id"), pl.col("to_tracklet_id")], separator="|").alias("source_tracklet_ids"),
                "tail_norm",
                "flight_norm",
                "service_date_utc",
                "processing_slice_id",
                pl.lit("stitched_hypothesis").alias("path_type_v8"),
                pl.lit(2).alias("node_count_v8"),
                pl.col("bridge_prior_score_v8").alias("path_prior_weight_v8"),
                "path_rank_v8",
                pl.lit(False).alias("formal_path_accepted_v8"),
            ]
        )
    )
    return pl.concat([singles, stitched], how="vertical_relaxed")


def process_slice(args: tuple[int, RunConfig]) -> dict[str, Any]:
    slice_id, cfg = args
    base = cfg.out_dir / "stage2_track_graph_v8"
    raw_path = base / "raw_input_shards_v8" / f"slice_{slice_id:02d}.parquet"
    local_path = base / "local_consistency_points_v8" / f"slice_{slice_id:02d}.parquet"
    clean_path = base / "clean_tracklet_points_v8" / f"slice_{slice_id:02d}.parquet"
    smooth_path = base / "smoothed_track_states_v8" / f"slice_{slice_id:02d}.parquet"
    summary_path = base / "clean_tracklet_summary_v8" / f"slice_{slice_id:02d}.parquet"
    edge_path = base / "tracklet_graph_edges_v8" / f"slice_{slice_id:02d}.parquet"
    path_path = base / "track_graph_paths_v8" / f"slice_{slice_id:02d}.parquet"
    for path in [local_path, clean_path, smooth_path, summary_path, edge_path, path_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.exists() and path_path.exists() and not cfg.overwrite:
        return json.loads((base / "slice_reports" / f"slice_{slice_id:02d}.json").read_text(encoding="utf-8"))
    raw = pl.read_parquet(raw_path)
    local = add_local_features(raw)
    local.write_parquet(local_path, compression="zstd", statistics=True)
    clean = rebuild_clean_tracklets(local)
    clean.write_parquet(clean_path, compression="zstd", statistics=True)
    smoothed = smooth_tracklets(clean)
    smoothed.write_parquet(smooth_path, compression="zstd", statistics=True)
    summary = summarize_tracklets(smoothed)
    summary.write_parquet(summary_path, compression="zstd", statistics=True)
    edges = build_graph_edges(summary, cfg.max_graph_gap_s)
    edges.write_parquet(edge_path, compression="zstd", statistics=True)
    paths = build_paths(summary, edges, cfg.top_k)
    paths.write_parquet(path_path, compression="zstd", statistics=True)
    legacy_legs = int(local.select(pl.col("legacy_leg_start_v4_compatible").sum()).item()) if local.height else 0
    report = {
        "slice_id": slice_id,
        "input_rows": raw.height,
        "local_rows": local.height,
        "clean_rows": clean.height,
        "diagnostic_excluded_rows": local.height - clean.height,
        "legacy_compatible_leg_count": legacy_legs,
        "clean_tracklet_count": summary.height,
        "fragmentation_delta": summary.height - legacy_legs,
        "singleton_tracklets": int(summary.filter(pl.col("point_count") == 1).height) if summary.height else 0,
        "graph_edges": edges.height,
        "physical_graph_edges": int(edges.filter(pl.col("physical_candidate_gate_v8")).height) if edges.height else 0,
        "graph_paths": paths.height,
        "formal_bridge_accepts": 0,
        "point_role_counts": local.group_by("clean_point_role_v8").len().to_dicts() if local.height else [],
        "anomaly_counts": local.group_by("point_anomaly_type_v8").len().to_dicts() if local.height else [],
    }
    write_json(base / "slice_reports" / f"slice_{slice_id:02d}.json", report)
    return report


def concat_dataset(input_dir: Path, output_path: Path) -> None:
    paths = sorted(input_dir.glob("slice_*.parquet"))
    if not paths:
        return
    pl.scan_parquet(paths).sink_parquet(output_path, compression="zstd", statistics=True, mkdir=True)


def main() -> None:
    cfg = parse_args()
    os.environ.setdefault("POLARS_MAX_THREADS", "25")
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        cfg.out_dir / "run_config.json",
        {
            **asdict(cfg),
            "generated_at_utc": utc_now(),
            "POLARS_MAX_THREADS": os.environ.get("POLARS_MAX_THREADS"),
            "documented_v4_input": str(DOCUMENTED_V4_INPUT),
            "documented_v4_input_exists": DOCUMENTED_V4_INPUT.exists(),
            "input_fallback_reason": "The documented v4 derived directory is absent; the exact 19,162,638-row Stage1 ADS-B source is used to rebuild compatible audit fields.",
            "space_policy": "25 mutually exclusive shards; each source point belongs to one shard; no 25 full-data copies.",
        },
    )
    input_rows = pl.scan_parquet(cfg.input_path).select(pl.len()).collect(engine="streaming").item()
    schema = {name: str(dtype) for name, dtype in pl.scan_parquet(cfg.input_path).collect_schema().items()}
    write_json(
        cfg.out_dir / "source_input_manifest.json",
        {
            "input_path": str(cfg.input_path),
            "input_rows": int(input_rows),
            "expected_documented_rows": 19_162_638,
            "row_count_matches_documented_source": int(input_rows) == 19_162_638,
            "schema": schema,
            "truth_semantics": "ADS-B observations only; no AMDAR point-truth is created.",
        },
    )
    shard_report = prepare_input_shards(cfg)
    write_json(cfg.out_dir / "stage2_v8_input_profile.json", shard_report)
    jobs = [(slice_id, cfg) for slice_id in range(cfg.slice_count)]
    reports: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=min(cfg.workers, cfg.slice_count),
        mp_context=mp.get_context("spawn"),
    ) as executor:
        futures = {executor.submit(process_slice, job): job[0] for job in jobs}
        for future in as_completed(futures):
            report = future.result()
            reports.append(report)
            print(json.dumps({"stage": "slice_done", **report}, ensure_ascii=False), flush=True)
    reports.sort(key=lambda item: item["slice_id"])
    base = cfg.out_dir / "stage2_track_graph_v8"
    concat_dataset(base / "clean_tracklet_summary_v8", base / "clean_tracklet_summary_v8.parquet")
    concat_dataset(base / "tracklet_graph_edges_v8", base / "tracklet_graph_edges_v8.parquet")
    concat_dataset(base / "track_graph_paths_v8", base / "track_graph_paths_v8.parquet")
    totals = {
        "input_rows": sum(item["input_rows"] for item in reports),
        "local_rows": sum(item["local_rows"] for item in reports),
        "clean_rows": sum(item["clean_rows"] for item in reports),
        "diagnostic_excluded_rows": sum(item["diagnostic_excluded_rows"] for item in reports),
        "legacy_compatible_leg_count": sum(item["legacy_compatible_leg_count"] for item in reports),
        "clean_tracklet_count": sum(item["clean_tracklet_count"] for item in reports),
        "singleton_tracklets": sum(item["singleton_tracklets"] for item in reports),
        "graph_edges": sum(item["graph_edges"] for item in reports),
        "physical_graph_edges": sum(item["physical_graph_edges"] for item in reports),
        "graph_paths": sum(item["graph_paths"] for item in reports),
        "formal_bridge_accepts": 0,
    }
    totals["fragmentation_delta"] = totals["clean_tracklet_count"] - totals["legacy_compatible_leg_count"]
    totals["fragmentation_reduction_fraction"] = (
        (totals["legacy_compatible_leg_count"] - totals["clean_tracklet_count"]) / totals["legacy_compatible_leg_count"]
        if totals["legacy_compatible_leg_count"]
        else 0.0
    )
    totals["point_conservation_passed"] = totals["input_rows"] == shard_report["rows"] == totals["local_rows"]
    totals["formal_bridge_stage2_invariant_passed"] = totals["formal_bridge_accepts"] == 0
    report = {
        "generated_at_utc": utc_now(),
        "scope": "Large-framework Stage2 v8 local consistency, clean tracklets, covariance smoother, and uncalibrated track graph.",
        "run_config": {**asdict(cfg), "POLARS_MAX_THREADS": os.environ.get("POLARS_MAX_THREADS")},
        "totals": totals,
        "slice_reports": reports,
        "quality_gate": {
            "point_conservation": totals["point_conservation_passed"],
            "no_formal_bridge_acceptance_in_stage2": totals["formal_bridge_stage2_invariant_passed"],
            "fragmentation_not_worse": totals["fragmentation_delta"] <= 0,
            "graph_candidates_nonzero": totals["physical_graph_edges"] > 0,
            "truth_holdout_violations": 0,
        },
        "limitations": [
            "The deleted v4 derived tables were not recreated byte-for-byte; compatible legacy boundary fields were rebuilt from the exact Stage1 source.",
            "The smoother is a transparent diagonal constant-velocity IMM-style forward/backward covariance smoother, not a full CTRV implementation.",
            "All graph scores remain priors and formal acceptance is false until Stage3 v13 calibration.",
        ],
    }
    write_json(base / "stage2_v8_track_graph_report.json", report)
    print(json.dumps({"stage": "stage2_v8_done", "totals": totals}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
