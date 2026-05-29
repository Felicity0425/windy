"""Centralized v1 Stage2: regenerate multimodal voxels from Stage1 outputs.

This Stage2 entrypoint intentionally does not read the historical
``stage2_output/voxels`` files. It rebuilds the per-frame voxel records from
Stage1 cleaned observations and radar frames, then writes an isolated
centralized_v1 output for downstream Ground Center reconstruction demos.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.pipeline_utils import _read_gray_image_robust
from stage.centralized_v1.configs.centralized_v1_config import (
    ALT_MAX,
    ALT_MIN,
    CONTEXT_SPACE_SIGMA_KM,
    CONTEXT_TIME_CONF_HALFLIFE_MINUTES,
    CONTEXT_VERTICAL_SIGMA_M,
    CONTEXT_WINDOW_MINUTES,
    DELTA_ALT,
    GROUND_CENTER_FALLBACK_ALT_M,
    GROUND_CENTER_FALLBACK_LAT,
    GROUND_CENTER_FALLBACK_LON,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    REGENERATED_STAGE2_OUTPUT_DIR,
    TIME_WINDOW_MINUTES,
    VOXEL_XY_DOWNSAMPLE,
    Z_DIM,
)
from stage.centralized_v1.configs.centralized_v1_contract import (
    C2_CLOUD_2D,
    C2_CLOUD_FEATURE_RECORDS,
    C2_CONTEXT_MOTION_RECORDS,
    C2_CONTEXT_WIND_RECORDS,
    C2_FILENAME,
    C2_FLIGHT_RAW_RECORDS,
    C2_GRID_SHAPE,
    C2_LOC_RECORDS,
    C2_MOTION_RECORDS,
    C2_MULTIMODAL_META_JSON,
    C2_RADAR_IMG,
    C2_RADAR_SHAPE,
    C2_TIME_STR,
    C2_TIMESTAMP_UTC,
    C2_WIND_RECORDS,
)

DEFAULT_DEMO_FRAMES = (
    "20260208124800,"
    "20260206174200,"
    "20260207022400,"
    "20260131073000,"
    "20260215063600,"
    "20260215063000,"
    "20260215100600,"
    "20260211060600,"
    "20260213053600,"
    "20260210060000"
)


def _load_stage1_outputs(stage1_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame, list[dict[str, Any]]]:
    wind_path = stage1_dir / "clean_wind.parquet"
    loc_path = stage1_dir / "clean_loc.parquet"
    radar_index_path = stage1_dir / "radar_index.json"
    missing = [str(p) for p in (wind_path, loc_path, radar_index_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing Stage1 inputs: {missing}")
    df_wind = pl.read_parquet(wind_path)
    df_loc = pl.read_parquet(loc_path)
    radar_index = json.loads(radar_index_path.read_text(encoding="utf-8"))
    return df_wind, df_loc, radar_index


def _records(df: pl.DataFrame) -> list[dict[str, Any]]:
    if len(df) == 0:
        return []
    return df.to_dicts()


def _count_drop_nulls(df: pl.DataFrame, subset: list[str]) -> int:
    existing = [col for col in subset if col in df.columns]
    if not existing:
        return 0
    return int(len(df.drop_nulls(subset=existing)))


def _count_in_domain(df: pl.DataFrame) -> int:
    needed = {"lat_clean", "lon_clean", "alt_meters"}
    if len(df) == 0 or not needed.issubset(set(df.columns)):
        return 0
    return int(
        len(
            df.filter(
                (pl.col("lat_clean") >= LAT_MIN)
                & (pl.col("lat_clean") <= LAT_MAX)
                & (pl.col("lon_clean") >= LON_MIN)
                & (pl.col("lon_clean") <= LON_MAX)
                & (pl.col("alt_meters") >= ALT_MIN)
                & (pl.col("alt_meters") <= ALT_MAX)
            )
        )
    )


def _global_audit(df_wind: pl.DataFrame, df_loc: pl.DataFrame, radar_index: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stage1_clean_wind_rows": int(len(df_wind)),
        "stage1_clean_loc_rows": int(len(df_loc)),
        "radar_index_rows": int(len(radar_index)),
        "radar_index_usable_rows": int(sum(1 for row in radar_index if row.get("usable"))),
    }


def _frame_audit(
    *,
    global_audit: dict[str, Any],
    target_time: datetime,
    h_dim: int,
    w_dim: int,
    coarse_h: int,
    coarse_w: int,
    z_dim: int,
    xy_factor: int,
    current_window_minutes: int,
    context_window_minutes: int,
    alt_step_m: float,
    roi_source: str,
    roi_lat: float,
    roi_lon: float,
    roi_alt_m: float,
    wind_window: pl.DataFrame,
    wind_current: pl.DataFrame,
    wind_context: pl.DataFrame,
    wind_frame: pl.DataFrame,
    context_wind_frame: pl.DataFrame,
    wind_grouped: pl.DataFrame,
    context_wind_grouped: pl.DataFrame,
    loc_window: pl.DataFrame,
    loc_current: pl.DataFrame,
    loc_context: pl.DataFrame,
    loc_frame: pl.DataFrame,
    context_loc_frame: pl.DataFrame,
    loc_grouped: pl.DataFrame,
    motion_grouped: pl.DataFrame,
    context_motion_grouped: pl.DataFrame,
    flight_raw: pl.DataFrame,
) -> dict[str, Any]:
    wind_required = ["time_utc", "lat_clean", "lon_clean", "alt_meters", "u_wind", "v_wind"]
    loc_required = ["time_utc", "lat_clean", "lon_clean", "alt_meters"]
    motion_required = ["time_utc", "lat_clean", "lon_clean", "alt_meters", "u_motion", "v_motion"]
    flight_required = ["u_motion", "v_motion", "flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"]
    virtual_flight_rows = 0
    virtual_flight_unique = 0
    if "flight_id_is_virtual" in flight_raw.columns and len(flight_raw) > 0:
        virtual_flight_rows = int(flight_raw.filter(pl.col("flight_id_is_virtual") == True).height)
        virtual_flight_unique = int(flight_raw.filter(pl.col("flight_id_is_virtual") == True).select(pl.col("flight_id").n_unique()).item()) if virtual_flight_rows else 0
    return {
        **global_audit,
        "audit_scope": "per_frame_time_window_grid_domain_voxel_aggregation",
        "target_time_utc": target_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stage2_all_in_definition": "all observations inside the per-frame time window, Stage2 grid domain, altitude range, and required-field constraints are retained before voxel grouping",
        "current_window_side_minutes": int(current_window_minutes),
        "current_total_span_minutes": int(current_window_minutes) * 2,
        "context_window_side_minutes": int(context_window_minutes),
        "context_total_span_minutes": int(context_window_minutes) * 2,
        "context_excludes_current_window": True,
        "context_window_definition": "target_time +/- context_window_side_minutes, excluding abs(delta_time_minutes) <= current_window_side_minutes",
        "domain_lat_min": float(LAT_MIN),
        "domain_lat_max": float(LAT_MAX),
        "domain_lon_min": float(LON_MIN),
        "domain_lon_max": float(LON_MAX),
        "domain_alt_min_m": float(ALT_MIN),
        "domain_alt_max_m": float(ALT_MAX),
        "xy_downsample": int(xy_factor),
        "radar_original_shape": [int(h_dim), int(w_dim)],
        "stage2_radar_shape": [int(coarse_h), int(coarse_w)],
        "grid_shape": [int(z_dim), int(coarse_h), int(coarse_w)],
        "z_altitude_step_m": float(alt_step_m),
        "rendered_png_size_note": "PNG size is determined by matplotlib figsize and dpi, not by radar_img/cloud_2d array size",
        "reference_center_policy": "current_window_flight_median_after_voxel_domain_filter",
        "reference_center_fallback": "domain_bbox_center_lat_33.2_lon_104.0_alt_0_when_current_window_flight_records_empty_or_missing",
        "reference_center_source": roi_source,
        "reference_center_lat": float(roi_lat),
        "reference_center_lon": float(roi_lon),
        "reference_center_alt_m": float(roi_alt_m),
        "reference_center_used_for_weighting": False,
        "stage2_space_conf_mode": "neutral_all_in",
        "target_voxel_localization_deferred_to_stage4": True,
        "wind_window_raw_rows": int(len(wind_window)),
        "wind_current_raw_rows": int(len(wind_current)),
        "wind_context_raw_rows": int(len(wind_context)),
        "wind_current_required_fields_rows": _count_drop_nulls(wind_current, wind_required),
        "wind_context_required_fields_rows": _count_drop_nulls(wind_context, wind_required),
        "wind_current_in_domain_rows": _count_in_domain(wind_current),
        "wind_context_in_domain_rows": _count_in_domain(wind_context),
        "wind_current_voxelized_rows": int(len(wind_frame)),
        "wind_context_voxelized_rows": int(len(context_wind_frame)),
        "wind_current_voxel_records": int(len(wind_grouped)),
        "wind_context_voxel_records": int(len(context_wind_grouped)),
        "loc_window_raw_rows": int(len(loc_window)),
        "loc_current_raw_rows": int(len(loc_current)),
        "loc_context_raw_rows": int(len(loc_context)),
        "loc_current_required_fields_rows": _count_drop_nulls(loc_current, loc_required),
        "loc_context_required_fields_rows": _count_drop_nulls(loc_context, loc_required),
        "loc_current_in_domain_rows": _count_in_domain(loc_current),
        "loc_context_in_domain_rows": _count_in_domain(loc_context),
        "loc_current_voxelized_rows": int(len(loc_frame)),
        "loc_context_voxelized_rows": int(len(context_loc_frame)),
        "traj_current_voxel_records": int(len(loc_grouped)),
        "motion_current_required_fields_rows": _count_drop_nulls(loc_current, motion_required),
        "motion_context_required_fields_rows": _count_drop_nulls(loc_context, motion_required),
        "motion_current_voxelized_rows": int(len(loc_frame.drop_nulls(subset=["u_motion", "v_motion"])) if len(loc_frame) else 0),
        "motion_context_voxelized_rows": int(len(context_loc_frame.drop_nulls(subset=["u_motion", "v_motion"])) if len(context_loc_frame) else 0),
        "motion_current_voxel_records": int(len(motion_grouped)),
        "motion_context_voxel_records": int(len(context_motion_grouped)),
        "flight_raw_required_rows": _count_drop_nulls(loc_current, flight_required),
        "flight_raw_voxelized_rows": int(len(flight_raw)),
        "flight_id_virtual_rows": virtual_flight_rows,
        "flight_id_virtual_unique": virtual_flight_unique,
        "qc_candidate_policy": "report_outliers_only_no_default_filtering",
    }


def _merge_existing_summary(summary_path: Path, new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not summary_path.exists():
        return sorted(new_rows, key=lambda row: str(row["time_str"]))
    merged = {str(row["time_str"]): row for row in json.loads(summary_path.read_text(encoding="utf-8"))}
    for row in new_rows:
        merged[str(row["time_str"])] = row
    return sorted(merged.values(), key=lambda row: str(row["time_str"]))


def _parse_frame_times(frame_times: str) -> set[str]:
    return {token.strip() for token in frame_times.split(",") if token.strip()}


def _time_conf_expr(halflife_minutes: float) -> pl.Expr:
    halflife = max(1.0, float(halflife_minutes))
    return (0.5 ** (pl.col("delta_time_minutes").abs() / halflife)).alias("time_conf")


def _density_conf_expr(count_col: str, scale: float = 3.0) -> pl.Expr:
    return (1.0 - (-pl.col(count_col).cast(pl.Float64) / float(scale)).exp()).alias("density_conf_diagnostic")


def _qc_flags_expr(speed_col: str, count_col: str, high_speed_threshold: float) -> pl.Expr:
    return (
        pl.when(pl.col(speed_col) > float(high_speed_threshold))
        .then(pl.lit("high_speed_qc_candidate"))
        .otherwise(pl.lit("ok"))
        .alias("qc_flags")
    )


def _haversine_expr(lat_col: str, lon_col: str, center_lat: float, center_lon: float) -> pl.Expr:
    r = 6371.0
    lat1 = pl.col(lat_col).radians()
    lat2 = math.radians(float(center_lat))
    dlat = (pl.col(lat_col) - float(center_lat)).radians()
    dlon = (pl.col(lon_col) - float(center_lon)).radians()
    a = (dlat / 2.0).sin() ** 2 + lat1.cos() * math.cos(lat2) * ((dlon / 2.0).sin() ** 2)
    return (2.0 * r * a.sqrt().arcsin()).alias("distance_to_roi_km")


def _eval_roi_center(loc_frame: pl.DataFrame) -> tuple[float, float, float, str]:
    if len(loc_frame) == 0:
        return GROUND_CENTER_FALLBACK_LAT, GROUND_CENTER_FALLBACK_LON, GROUND_CENTER_FALLBACK_ALT_M, "domain_bbox_fallback"
    needed = {"lat_clean", "lon_clean", "alt_meters"}
    if not needed.issubset(set(loc_frame.columns)):
        return GROUND_CENTER_FALLBACK_LAT, GROUND_CENTER_FALLBACK_LON, GROUND_CENTER_FALLBACK_ALT_M, "domain_bbox_fallback"
    center = loc_frame.select(
        [
            pl.col("lat_clean").median().alias("lat"),
            pl.col("lon_clean").median().alias("lon"),
            pl.col("alt_meters").median().alias("alt"),
        ]
    ).to_dicts()[0]
    if center["lat"] is None or center["lon"] is None or center["alt"] is None:
        return GROUND_CENTER_FALLBACK_LAT, GROUND_CENTER_FALLBACK_LON, GROUND_CENTER_FALLBACK_ALT_M, "domain_bbox_fallback"
    return float(center["lat"]), float(center["lon"]), float(center["alt"]), "current_flight_raw_median"


def _pool_patch(arr: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> dict[str, float]:
    patch = np.asarray(arr[y0:y1, x0:x1], dtype=np.float32)
    return {
        "cloud_mean": float(np.mean(patch)),
        "cloud_max": float(np.max(patch)),
        "cloud_std": float(np.std(patch)),
    }


def _build_cloud_feature_records(radar_img: np.ndarray, coarse_h: int, coarse_w: int, z_dim: int, factor: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for y in range(coarse_h):
        for x in range(coarse_w):
            y0 = y * factor
            y1 = min(radar_img.shape[0], (y + 1) * factor)
            x0 = x * factor
            x1 = min(radar_img.shape[1], (x + 1) * factor)
            feat = _pool_patch(radar_img, y0, y1, x0, x1)
            if feat["cloud_max"] <= 0.0:
                continue
            for z in range(z_dim):
                records.append({"z": z, "y": y, "x": x, **feat})
    return records


def _with_voxel_columns(df: pl.DataFrame, h_dim: int, w_dim: int, xy_factor: int, z_dim: int, alt_step_m: float) -> pl.DataFrame:
    if len(df) == 0:
        return df
    delta_lat = (LAT_MAX - LAT_MIN) / float(h_dim)
    delta_lon = (LON_MAX - LON_MIN) / float(w_dim)
    return (
        df.with_columns(
            [
                (((pl.col("lon_clean") - LON_MIN) / delta_lon) / xy_factor).floor().cast(pl.Int32).alias("x"),
                (((LAT_MAX - pl.col("lat_clean")) / delta_lat) / xy_factor).floor().cast(pl.Int32).alias("y"),
                ((pl.col("alt_meters") - ALT_MIN) / alt_step_m).floor().cast(pl.Int32).alias("z"),
            ]
        )
        .filter(
            (pl.col("x") >= 0)
            & (pl.col("x") < max(1, w_dim // xy_factor))
            & (pl.col("y") >= 0)
            & (pl.col("y") < max(1, h_dim // xy_factor))
            & (pl.col("alt_meters") >= ALT_MIN)
            & (pl.col("alt_meters") <= ALT_MAX)
            & (pl.col("z") >= 0)
            & (pl.col("z") < z_dim)
        )
    )


def _load_stage1_windows(df_wind: pl.DataFrame, df_loc: pl.DataFrame, target_time: datetime, context_window_minutes: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    start = target_time - timedelta(minutes=context_window_minutes)
    end = target_time + timedelta(minutes=context_window_minutes)
    wind = df_wind.filter((pl.col("time_utc") >= start) & (pl.col("time_utc") <= end))
    loc = df_loc.filter((pl.col("time_utc") >= start) & (pl.col("time_utc") <= end))
    return wind, loc


def _split_current_context(df: pl.DataFrame, target_time: datetime, current_window_minutes: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    if len(df) == 0:
        return df, df
    with_dt = df.with_columns((pl.col("time_utc") - pl.lit(target_time)).dt.total_minutes().cast(pl.Float64).alias("delta_time_minutes"))
    current = with_dt.filter(pl.col("delta_time_minutes").abs() <= current_window_minutes)
    context = with_dt.filter(pl.col("delta_time_minutes").abs() > current_window_minutes)
    return current, context


def _with_context_confidence(
    df: pl.DataFrame,
    halflife_minutes: float,
    roi_lat: float,
    roi_lon: float,
    roi_alt_m: float,
    space_sigma_km: float,
    vertical_sigma_m: float,
) -> pl.DataFrame:
    if len(df) == 0:
        return df
    return df.with_columns(
        [
            _time_conf_expr(halflife_minutes),
            _haversine_expr("lat_clean", "lon_clean", roi_lat, roi_lon),
            (pl.col("alt_meters") - float(roi_alt_m)).abs().alias("vertical_delta_to_roi_m"),
            pl.lit(float(roi_lat)).alias("roi_center_lat"),
            pl.lit(float(roi_lon)).alias("roi_center_lon"),
            pl.lit(float(roi_alt_m)).alias("roi_center_alt_m"),
        ]
    ).with_columns(
        [
            pl.col("time_conf").alias("time_likelihood"),
            pl.lit(1.0).alias("space_conf"),
        ]
    ).with_columns(
        [
            pl.col("space_conf").alias("space_likelihood"),
            (pl.col("obs_conf").fill_null(1.0) * pl.col("time_conf")).alias("joint_likelihood"),
        ]
    )


def _aggregate_context_wind(
    df: pl.DataFrame,
    halflife_minutes: float,
    roi_lat: float,
    roi_lon: float,
    roi_alt_m: float,
    space_sigma_km: float,
    vertical_sigma_m: float,
) -> pl.DataFrame:
    if len(df) == 0:
        return pl.DataFrame()
    weighted = _with_context_confidence(df, halflife_minutes, roi_lat, roi_lon, roi_alt_m, space_sigma_km, vertical_sigma_m)
    grouped = weighted.group_by(["z", "y", "x"]).agg(
        [
            ((pl.col("u_wind") * pl.col("joint_likelihood")).sum() / pl.col("joint_likelihood").sum()).alias("u"),
            ((pl.col("v_wind") * pl.col("joint_likelihood")).sum() / pl.col("joint_likelihood").sum()).alias("v"),
            pl.len().alias("obs_count"),
            pl.col("delta_time_minutes").abs().min().alias("nearest_delta_time_minutes"),
            pl.col("delta_time_minutes").abs().mean().alias("mean_abs_delta_time_minutes"),
            pl.col("time_conf").mean().alias("time_conf"),
            pl.col("time_likelihood").mean().alias("time_likelihood"),
            pl.col("distance_to_roi_km").mean().alias("distance_to_roi_km"),
            pl.col("vertical_delta_to_roi_m").mean().alias("vertical_delta_to_roi_m"),
            pl.col("space_conf").mean().alias("space_conf"),
            pl.col("space_likelihood").mean().alias("space_likelihood"),
            pl.col("joint_likelihood").mean().alias("joint_likelihood"),
            pl.col("obs_conf").mean().alias("obs_conf"),
            pl.col("roi_center_lat").first().alias("roi_center_lat"),
            pl.col("roi_center_lon").first().alias("roi_center_lon"),
            pl.col("roi_center_alt_m").first().alias("roi_center_alt_m"),
        ]
    )
    grouped = grouped.with_columns(
        [
            (pl.col("u") ** 2 + pl.col("v") ** 2).sqrt().alias("wind_speed_diagnostic"),
            pl.lit(1.0).alias("quality_conf_diagnostic"),
            _density_conf_expr("obs_count"),
        ]
    )
    return grouped.with_columns(
        [
            _qc_flags_expr("wind_speed_diagnostic", "obs_count", 120.0),
            pl.lit("context").alias("source_role"),
        ]
    )


def _aggregate_context_motion(
    df: pl.DataFrame,
    halflife_minutes: float,
    roi_lat: float,
    roi_lon: float,
    roi_alt_m: float,
    space_sigma_km: float,
    vertical_sigma_m: float,
) -> pl.DataFrame:
    if len(df) == 0:
        return pl.DataFrame()
    motion = df.drop_nulls(subset=["u_motion", "v_motion"])
    if len(motion) == 0:
        return pl.DataFrame()
    motion = _with_context_confidence(
        motion.with_columns(pl.lit(1.0).alias("obs_conf")),
        halflife_minutes,
        roi_lat,
        roi_lon,
        roi_alt_m,
        space_sigma_km,
        vertical_sigma_m,
    )
    grouped = motion.group_by(["z", "y", "x"]).agg(
        [
            ((pl.col("u_motion") * pl.col("joint_likelihood")).sum() / pl.col("joint_likelihood").sum()).alias("u_motion"),
            ((pl.col("v_motion") * pl.col("joint_likelihood")).sum() / pl.col("joint_likelihood").sum()).alias("v_motion"),
            pl.len().alias("motion_count"),
            pl.col("delta_time_minutes").abs().min().alias("nearest_delta_time_minutes"),
            pl.col("delta_time_minutes").abs().mean().alias("mean_abs_delta_time_minutes"),
            pl.col("time_conf").mean().alias("time_conf"),
            pl.col("time_likelihood").mean().alias("time_likelihood"),
            pl.col("distance_to_roi_km").mean().alias("distance_to_roi_km"),
            pl.col("vertical_delta_to_roi_m").mean().alias("vertical_delta_to_roi_m"),
            pl.col("space_conf").mean().alias("space_conf"),
            pl.col("space_likelihood").mean().alias("space_likelihood"),
            pl.col("joint_likelihood").mean().alias("joint_likelihood"),
            pl.col("roi_center_lat").first().alias("roi_center_lat"),
            pl.col("roi_center_lon").first().alias("roi_center_lon"),
            pl.col("roi_center_alt_m").first().alias("roi_center_alt_m"),
        ]
    )
    grouped = grouped.with_columns(
        [
            (pl.col("u_motion") ** 2 + pl.col("v_motion") ** 2).sqrt().alias("motion_speed_diagnostic"),
            pl.lit(1.0).alias("quality_conf_diagnostic"),
            _density_conf_expr("motion_count"),
        ]
    )
    return grouped.with_columns(
        [
            _qc_flags_expr("motion_speed_diagnostic", "motion_count", 320.0),
            pl.lit("context").alias("source_role"),
        ]
    )


def _empty_df(schema: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _has_cols(df: pl.DataFrame, cols: list[str]) -> bool:
    return len(df) > 0 and all(col in df.columns for col in cols)


def _aggregate_current_wind(df: pl.DataFrame) -> pl.DataFrame:
    schema = {"z": pl.Int64, "y": pl.Int64, "x": pl.Int64, "u": pl.Float64, "v": pl.Float64, "obs_count": pl.UInt32, "obs_conf": pl.Float64}
    if not _has_cols(df, ["z", "y", "x", "u_wind", "v_wind", "obs_conf"]):
        return _empty_df(schema)
    return df.group_by(["z", "y", "x"]).agg(
        [
            pl.col("u_wind").mean().alias("u"),
            pl.col("v_wind").mean().alias("v"),
            pl.len().alias("obs_count"),
            pl.col("obs_conf").mean().alias("obs_conf"),
        ]
    )


def _aggregate_current_loc(df: pl.DataFrame) -> pl.DataFrame:
    schema = {"z": pl.Int64, "y": pl.Int64, "x": pl.Int64, "density": pl.UInt32}
    if not _has_cols(df, ["z", "y", "x"]):
        return _empty_df(schema)
    return df.group_by(["z", "y", "x"]).agg(pl.len().alias("density"))


def _aggregate_current_motion(df: pl.DataFrame) -> pl.DataFrame:
    schema = {"z": pl.Int64, "y": pl.Int64, "x": pl.Int64, "u_motion": pl.Float64, "v_motion": pl.Float64, "motion_count": pl.UInt32}
    if not _has_cols(df, ["z", "y", "x", "u_motion", "v_motion"]):
        return _empty_df(schema)
    motion = df.drop_nulls(subset=["u_motion", "v_motion"])
    if len(motion) == 0:
        return _empty_df(schema)
    return motion.group_by(["z", "y", "x"]).agg(
        [
            pl.col("u_motion").mean().alias("u_motion"),
            pl.col("v_motion").mean().alias("v_motion"),
            pl.len().alias("motion_count"),
        ]
    )


def _aggregate_source_wind(df: pl.DataFrame, source: str) -> pl.DataFrame:
    schema = {"z": pl.Int64, "y": pl.Int64, "x": pl.Int64, "u": pl.Float64, "v": pl.Float64, "obs_count": pl.UInt32}
    if not _has_cols(df, ["z", "y", "x", "u_wind", "v_wind", "source"]):
        return _empty_df(schema)
    filtered = df.filter(pl.col("source") == source)
    if len(filtered) == 0:
        return _empty_df(schema)
    return filtered.group_by(["z", "y", "x"]).agg(
        [
            pl.col("u_wind").mean().alias("u"),
            pl.col("v_wind").mean().alias("v"),
            pl.len().alias("obs_count"),
        ]
    )


def process_frame(
    df_wind_all: pl.DataFrame,
    df_loc_all: pl.DataFrame,
    stage1_global_audit: dict[str, Any],
    radar_item: dict[str, Any],
    out_dir: Path,
    xy_factor: int,
    current_window_minutes: int,
    context_window_minutes: int,
    alt_step_m: float,
    time_conf_halflife_minutes: float,
    space_sigma_km: float,
    vertical_sigma_m: float,
    num_workers: int,
) -> dict[str, Any] | None:
    time_str = str(radar_item["time_str"])
    target_time = datetime.strptime(time_str, "%Y%m%d%H%M%S")
    z_dim = int((ALT_MAX - ALT_MIN) / alt_step_m) + 1

    radar_img = _read_gray_image_robust(radar_item["radar_path"])
    if radar_img is None:
        return None
    radar_img = np.asarray(radar_img)
    h_dim, w_dim = radar_img.shape
    coarse_h = max(1, h_dim // xy_factor)
    coarse_w = max(1, w_dim // xy_factor)

    df_wind, df_loc = _load_stage1_windows(df_wind_all, df_loc_all, target_time, context_window_minutes)
    wind_current, wind_context = _split_current_context(df_wind, target_time, current_window_minutes)
    loc_current, loc_context = _split_current_context(df_loc, target_time, current_window_minutes)
    wind_frame = _with_voxel_columns(wind_current, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    loc_frame = _with_voxel_columns(loc_current, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    context_wind_frame = _with_voxel_columns(wind_context, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    context_loc_frame = _with_voxel_columns(loc_context, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    roi_lat, roi_lon, roi_alt_m, roi_source = _eval_roi_center(loc_frame)

    wind_grouped = _aggregate_current_wind(wind_frame)
    loc_grouped = _aggregate_current_loc(loc_frame)
    motion_grouped = _aggregate_current_motion(loc_frame)
    context_wind_grouped = _aggregate_context_wind(context_wind_frame, time_conf_halflife_minutes, roi_lat, roi_lon, roi_alt_m, space_sigma_km, vertical_sigma_m)
    context_motion_grouped = _aggregate_context_motion(context_loc_frame, time_conf_halflife_minutes, roi_lat, roi_lon, roi_alt_m, space_sigma_km, vertical_sigma_m)
    flight_raw = loc_frame.drop_nulls(subset=["u_motion", "v_motion", "flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"])
    amdar_grouped = _aggregate_source_wind(wind_frame, "amdar")
    turb_grouped = _aggregate_source_wind(wind_frame, "turb")
    cloud_records = _build_cloud_feature_records(radar_img, coarse_h, coarse_w, z_dim, xy_factor)
    data_integrity_audit = _frame_audit(
        global_audit=stage1_global_audit,
        target_time=target_time,
        h_dim=h_dim,
        w_dim=w_dim,
        coarse_h=coarse_h,
        coarse_w=coarse_w,
        z_dim=z_dim,
        xy_factor=xy_factor,
        current_window_minutes=current_window_minutes,
        context_window_minutes=context_window_minutes,
        alt_step_m=alt_step_m,
        roi_source=roi_source,
        roi_lat=roi_lat,
        roi_lon=roi_lon,
        roi_alt_m=roi_alt_m,
        wind_window=df_wind,
        wind_current=wind_current,
        wind_context=wind_context,
        wind_frame=wind_frame,
        context_wind_frame=context_wind_frame,
        wind_grouped=wind_grouped,
        context_wind_grouped=context_wind_grouped,
        loc_window=df_loc,
        loc_current=loc_current,
        loc_context=loc_context,
        loc_frame=loc_frame,
        context_loc_frame=context_loc_frame,
        loc_grouped=loc_grouped,
        motion_grouped=motion_grouped,
        context_motion_grouped=context_motion_grouped,
        flight_raw=flight_raw,
    )

    payload = {
        C2_FILENAME: np.array(str(radar_item["filename"])),
        C2_TIME_STR: np.array(time_str),
        C2_TIMESTAMP_UTC: np.array(target_time.strftime("%Y-%m-%dT%H:%M:%SZ")),
        C2_RADAR_SHAPE: np.array([coarse_h, coarse_w], dtype=np.int32),
        C2_GRID_SHAPE: np.array([z_dim, coarse_h, coarse_w], dtype=np.int32),
        C2_RADAR_IMG: radar_img[::xy_factor, ::xy_factor],
        C2_CLOUD_2D: radar_img[::xy_factor, ::xy_factor],
        C2_WIND_RECORDS: np.array(_records(wind_grouped), dtype=object),
        C2_CONTEXT_WIND_RECORDS: np.array(_records(context_wind_grouped), dtype=object),
        C2_LOC_RECORDS: np.array(_records(loc_grouped), dtype=object),
        C2_MOTION_RECORDS: np.array(_records(motion_grouped), dtype=object),
        C2_CONTEXT_MOTION_RECORDS: np.array(_records(context_motion_grouped), dtype=object),
        C2_FLIGHT_RAW_RECORDS: np.array(_records(flight_raw), dtype=object),
        C2_CLOUD_FEATURE_RECORDS: np.array(cloud_records, dtype=object),
        C2_MULTIMODAL_META_JSON: np.array(
            json.dumps(
                {
                    "source": "stage1_regenerated",
                    "current_window_minutes": int(current_window_minutes),
                    "context_window_minutes": int(context_window_minutes),
                    "context_excludes_current_window": True,
                    "xy_downsample": int(xy_factor),
                    "z_altitude_step_m": float(alt_step_m),
                    "z_dim": int(z_dim),
                    "num_workers": int(num_workers),
                    "parallel_mode": "shard_subprocess" if num_workers > 1 else "single_process",
                    "stage2_role": "observation_organization_not_reconstruction",
                    "all_in_observations": True,
                    "all_in_scope": "per_frame_time_window_grid_domain_required_fields_before_voxel_grouping",
                    "reference_center_does_not_filter_records": True,
                    "ground_center_mode": "logical_ground_center_all_agents_downlink_no_comm_filter",
                    "current_window_side_minutes": int(current_window_minutes),
                    "current_total_span_minutes": int(current_window_minutes) * 2,
                    "context_window_side_minutes": int(context_window_minutes),
                    "context_total_span_minutes": int(context_window_minutes) * 2,
                    "context_window_definition": "target_time +/- context_window_side_minutes, excluding abs(delta_time_minutes) <= current_window_side_minutes",
                    "reference_center_policy": "current_window_flight_median_after_voxel_domain_filter",
                    "reference_center_fallback": "domain_bbox_center_lat_33.2_lon_104.0_alt_0_when_current_window_flight_records_empty_or_missing",
                    "reference_center_source": roi_source,
                    "reference_center_lat": float(roi_lat),
                    "reference_center_lon": float(roi_lon),
                    "reference_center_alt_m": float(roi_alt_m),
                    "reference_center_used_for_weighting": False,
                    "stage2_space_conf_mode": "neutral_all_in",
                    "target_voxel_localization_deferred_to_stage4": True,
                    "roi_center_source": roi_source,
                    "roi_center_lat": float(roi_lat),
                    "roi_center_lon": float(roi_lon),
                    "roi_center_alt_m": float(roi_alt_m),
                    "time_conf_formula": "0.5 ** (abs(delta_time_minutes) / halflife_minutes)",
                    "time_conf_halflife_minutes": float(time_conf_halflife_minutes),
                    "space_conf_formula": "1.0 in Stage2 neutral-all-in mode; target-voxel localization is deferred to Stage4",
                    "space_sigma_km": float(space_sigma_km),
                    "vertical_sigma_m": float(vertical_sigma_m),
                    "stage4_target_voxel_localization_note": "Stage4 should compute spatial localization from observation voxel to each target voxel, not from observation to reference_center",
                    "joint_likelihood_formula": "obs_conf * time_conf",
                    "diagnostic_confidence_policy": "diagnostic_only_not_used_in_active_joint_likelihood",
                    "quality_conf_diagnostic_formula": "1.0 in current Stage2 because required-field filtering already happened; future versions may lower this for QC candidates",
                    "density_conf_diagnostic_formula": "1 - exp(-count/3), using obs_count for context wind and motion_count for context motion",
                    "qc_flags_policy": "report high-speed candidates only; do not delete or downweight by default",
                    "qc_high_wind_speed_threshold_mps": 120.0,
                    "qc_high_motion_speed_threshold_mps": 320.0,
                    "cloud_feature_count": int(len(cloud_records)),
                    "cloud_feature_desc": ["cloud_mean", "cloud_max", "cloud_std"],
                    "sota_reference_methods": [
                        "GraphCast/GenCast-style gridded multivariate state plus temporal conditioning",
                        "Conditional diffusion-style context packaging for Stage5, no Stage2 training",
                        "FourCastNet/Aurora-style efficient gridded weather feature preparation",
                    ],
                    "point_eval_role": "candidate_ground_truth_only; prediction errors belong to Stage4 strict hold-out",
                    "data_integrity_audit": data_integrity_audit,
                },
                ensure_ascii=False,
            )
        ),
    }

    vox_dir = out_dir / "voxels"
    vox_dir.mkdir(parents=True, exist_ok=True)
    out_path = vox_dir / f"frame_{time_str}_multimodal.npz"
    np.savez_compressed(out_path, **payload)

    total_grid = max(1, z_dim * coarse_h * coarse_w)
    wind_speeds = np.sqrt(wind_grouped["u"].to_numpy() ** 2 + wind_grouped["v"].to_numpy() ** 2) if len(wind_grouped) else np.array([])
    return {
        "filename": radar_item["filename"],
        "time_str": time_str,
        "timestamp_utc": target_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "multimodal_vox_path": str(out_path),
        "vox_path": str(out_path),
        "regenerated_from_stage1": 1,
        "current_window_minutes": int(current_window_minutes),
        "context_window_minutes": int(context_window_minutes),
        "time_conf_halflife_minutes": float(time_conf_halflife_minutes),
        "space_sigma_km": float(space_sigma_km),
        "vertical_sigma_m": float(vertical_sigma_m),
        "num_workers": int(num_workers),
        "parallel_mode": "shard_subprocess" if num_workers > 1 else "single_process",
        "stage2_role": "observation_organization_not_reconstruction",
        "all_in_observations": 1,
        "all_in_scope": "per_frame_time_window_grid_domain_required_fields_before_voxel_grouping",
        "reference_center_does_not_filter_records": 1,
        "current_window_side_minutes": int(current_window_minutes),
        "current_total_span_minutes": int(current_window_minutes) * 2,
        "context_window_side_minutes": int(context_window_minutes),
        "context_total_span_minutes": int(context_window_minutes) * 2,
        "reference_center_policy": "current_window_flight_median_after_voxel_domain_filter",
        "reference_center_source": roi_source,
        "reference_center_lat": float(roi_lat),
        "reference_center_lon": float(roi_lon),
        "reference_center_alt_m": float(roi_alt_m),
        "reference_center_used_for_weighting": 0,
        "stage2_space_conf_mode": "neutral_all_in",
        "target_voxel_localization_deferred_to_stage4": 1,
        "diagnostic_confidence_policy": "diagnostic_only_not_used_in_active_joint_likelihood",
        "qc_high_wind_speed_threshold_mps": 120.0,
        "qc_high_motion_speed_threshold_mps": 320.0,
        "roi_center_source": roi_source,
        "roi_center_lat": float(roi_lat),
        "roi_center_lon": float(roi_lon),
        "roi_center_alt_m": float(roi_alt_m),
        "xy_downsample": int(xy_factor),
        "z_altitude_step_m": float(alt_step_m),
        "grid_shape": [int(z_dim), int(coarse_h), int(coarse_w)],
        "wind_voxels": int(len(wind_grouped)),
        "context_wind_voxels": int(len(context_wind_grouped)),
        "traj_voxels": int(len(loc_grouped)),
        "motion_voxels": int(len(motion_grouped)),
        "context_motion_voxels": int(len(context_motion_grouped)),
        "flight_raw_records": int(len(flight_raw)),
        "amdar_voxels": int(len(amdar_grouped)),
        "turb_voxels": int(len(turb_grouped)),
        "cloud_voxels": int(len(cloud_records)),
        "cloud_feature_coverage": float(len(cloud_records) / total_grid),
        "wind_speed_mean": float(np.mean(wind_speeds)) if wind_speeds.size else 0.0,
        "wind_speed_max": float(np.max(wind_speeds)) if wind_speeds.size else 0.0,
        "data_integrity_audit": data_integrity_audit,
    }


def _process_frame_worker(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    return process_frame(**kwargs)


def _format_elapsed(seconds: float) -> str:
    seconds_i = max(0, int(seconds))
    hours, rem = divmod(seconds_i, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _write_progress_file(
    progress_file: Path | None,
    shard_id: int | None,
    done: int,
    total: int,
    last_time_str: str | None = None,
) -> None:
    if progress_file is None:
        return
    total_safe = max(0, int(total))
    done_safe = min(max(0, int(done)), total_safe) if total_safe else max(0, int(done))
    payload = {
        "shard_id": shard_id,
        "done": done_safe,
        "total": total_safe,
        "percent": float((done_safe / total_safe) * 100.0) if total_safe else 100.0,
        "last_time_str": last_time_str,
        "updated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = progress_file.with_name(f"{progress_file.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(progress_file)


def _read_progress_done(progress_file: Path, fallback_total: int, proc_done: bool) -> int:
    if proc_done:
        return int(fallback_total)
    try:
        payload = json.loads(progress_file.read_text(encoding="utf-8"))
        return min(max(0, int(payload.get("done", 0))), int(fallback_total))
    except Exception:
        return 0


def _print_progress(label: str, done: int, total: int, start_ts: float, detail: str = "") -> None:
    total_safe = max(1, int(total))
    done_safe = min(max(0, int(done)), total_safe)
    percent = done_safe / total_safe * 100.0
    elapsed = _format_elapsed(time.time() - start_ts)
    suffix = f" {detail}" if detail else ""
    print(f"[Stage2 progress] {label}: {done_safe}/{total_safe} frames ({percent:5.1f}%) elapsed={elapsed}{suffix}", file=sys.stderr, flush=True)


def _write_shard_frame_times(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = [str(row["time_str"]) for row in rows]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_parent_shards(args: argparse.Namespace, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    workers = max(1, int(args.num_workers))
    shard_dir = args.out_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards = [[] for _ in range(workers)]
    for idx, row in enumerate(selected):
        shards[idx % workers].append(row)

    procs = []
    env_base = os.environ.copy()
    env_base.setdefault("POLARS_MAX_THREADS", "1")
    for shard_idx, rows in enumerate(shards):
        if not rows:
            continue
        frame_file = shard_dir / f"stage2_shard_{shard_idx:02d}_frames.json"
        summary_file = shard_dir / f"stage2_shard_{shard_idx:02d}_summary.json"
        log_file = shard_dir / f"stage2_shard_{shard_idx:02d}.log"
        progress_file = shard_dir / f"stage2_shard_{shard_idx:02d}_progress.json"
        _write_shard_frame_times(frame_file, rows)
        _write_progress_file(progress_file, shard_idx, 0, len(rows))
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--stage1-dir",
            str(args.stage1_dir),
            "--out-dir",
            str(args.out_dir),
            "--frame-times-file",
            str(frame_file),
            "--xy-downsample",
            str(args.xy_downsample),
            "--current-window-minutes",
            str(args.current_window_minutes),
            "--context-window-minutes",
            str(args.context_window_minutes),
            "--alt-step-m",
            str(args.alt_step_m),
            "--time-conf-halflife-minutes",
            str(args.time_conf_halflife_minutes),
            "--space-sigma-km",
            str(args.space_sigma_km),
            "--vertical-sigma-m",
            str(args.vertical_sigma_m),
            "--num-workers",
            str(workers),
            "--shard-id",
            str(shard_idx),
            "--shard-summary",
            str(summary_file),
            "--progress-file",
            str(progress_file),
            "--progress-interval-seconds",
            str(args.progress_interval_seconds),
        ]
        with log_file.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
        procs.append(
            {
                "proc": proc,
                "summary_file": summary_file,
                "log_file": log_file,
                "progress_file": progress_file,
                "total": len(rows),
            }
        )

    total_frames = sum(int(item["total"]) for item in procs)
    start_ts = time.time()
    _print_progress("parent", 0, total_frames, start_ts, f"active_shards={len(procs)}/{len(procs)}")
    last_print_ts = time.time()
    last_done = 0
    while procs:
        failed = [item for item in procs if item["proc"].poll() not in (None, 0)]
        if failed:
            item = failed[0]
            raise RuntimeError(f"Stage2 shard failed rc={item['proc'].poll()}; see {item['log_file']}")

        active = sum(1 for item in procs if item["proc"].poll() is None)
        done = sum(
            _read_progress_done(
                item["progress_file"],
                int(item["total"]),
                item["proc"].poll() == 0,
            )
            for item in procs
        )
        now = time.time()
        interval = max(1.0, float(args.progress_interval_seconds))
        if done != last_done or now - last_print_ts >= interval:
            _print_progress("parent", done, total_frames, start_ts, f"active_shards={active}/{len(procs)}")
            last_done = done
            last_print_ts = now
        if active == 0:
            break
        time.sleep(min(interval, 5.0))

    summaries: list[dict[str, Any]] = []
    for item in procs:
        proc = item["proc"]
        summary_file = item["summary_file"]
        log_file = item["log_file"]
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"Stage2 shard failed rc={rc}; see {log_file}")
        summaries.extend(json.loads(summary_file.read_text(encoding="utf-8")))
    summaries.sort(key=lambda row: str(row["time_str"]))
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Centralized v1 Stage2 regenerate multimodal voxels from Stage1.")
    parser.add_argument("--stage1-dir", type=Path, default=ROOT_DIR / "stage1_output")
    parser.add_argument("--out-dir", type=Path, default=REGENERATED_STAGE2_OUTPUT_DIR)
    parser.add_argument("--frame-times", default=DEFAULT_DEMO_FRAMES)
    parser.add_argument("--xy-downsample", type=int, default=VOXEL_XY_DOWNSAMPLE)
    parser.add_argument("--current-window-minutes", type=int, default=TIME_WINDOW_MINUTES)
    parser.add_argument("--context-window-minutes", type=int, default=CONTEXT_WINDOW_MINUTES)
    parser.add_argument("--alt-step-m", type=float, default=DELTA_ALT)
    parser.add_argument("--time-conf-halflife-minutes", type=float, default=CONTEXT_TIME_CONF_HALFLIFE_MINUTES)
    parser.add_argument("--space-sigma-km", type=float, default=CONTEXT_SPACE_SIGMA_KM)
    parser.add_argument("--vertical-sigma-m", type=float, default=CONTEXT_VERTICAL_SIGMA_M)
    parser.add_argument("--num-workers", type=int, default=8)
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--shard-id", type=int)
    parser.add_argument("--shard-summary", type=Path)
    parser.add_argument("--progress-file", type=Path)
    parser.add_argument("--progress-interval-seconds", type=float, default=10.0)
    parser.add_argument("--merge-existing-summary", action="store_true")
    args = parser.parse_args()

    if args.xy_downsample <= 0:
        raise ValueError("--xy-downsample must be positive")
    if args.current_window_minutes <= 0:
        raise ValueError("--current-window-minutes must be positive")
    if args.context_window_minutes <= args.current_window_minutes:
        raise ValueError("--context-window-minutes must be larger than --current-window-minutes")
    if args.alt_step_m <= 0:
        raise ValueError("--alt-step-m must be positive")
    df_wind, df_loc, radar_index = _load_stage1_outputs(args.stage1_dir)
    stage1_global_audit = _global_audit(df_wind, df_loc, radar_index)
    if args.frame_times_file is not None:
        wanted = {str(x) for x in json.loads(args.frame_times_file.read_text(encoding="utf-8"))}
    else:
        wanted = _parse_frame_times(args.frame_times)
    selected = [row for row in radar_index if row.get("usable") and str(row.get("time_str")) in wanted]
    missing = sorted(wanted - {str(row.get("time_str")) for row in selected})
    if missing:
        raise ValueError(f"Requested frame-times not found as usable radar frames: {missing}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if int(args.num_workers) > 1 and args.shard_id is None:
        summaries = _run_parent_shards(args, selected)
        summary_path = args.out_dir / "stage2_multimodal_summary.json"
        if args.merge_existing_summary:
            summaries = _merge_existing_summary(summary_path, summaries)
        summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        print(summary_path)
        return

    jobs = [
        {
            "df_wind_all": df_wind,
            "df_loc_all": df_loc,
            "stage1_global_audit": stage1_global_audit,
            "radar_item": row,
            "out_dir": args.out_dir,
            "xy_factor": int(args.xy_downsample),
            "current_window_minutes": int(args.current_window_minutes),
            "context_window_minutes": int(args.context_window_minutes),
            "alt_step_m": float(args.alt_step_m),
            "time_conf_halflife_minutes": float(args.time_conf_halflife_minutes),
            "space_sigma_km": float(args.space_sigma_km),
            "vertical_sigma_m": float(args.vertical_sigma_m),
            "num_workers": int(args.num_workers),
        }
        for row in selected
    ]
    summaries = []
    progress_total = len(jobs)
    progress_start_ts = time.time()
    progress_label = f"shard {args.shard_id:02d}" if args.shard_id is not None else "single"
    progress_interval = max(1.0, float(args.progress_interval_seconds))
    last_progress_print_ts = 0.0
    _write_progress_file(args.progress_file, args.shard_id, 0, progress_total)
    _print_progress(progress_label, 0, progress_total, progress_start_ts)
    for idx, job in enumerate(jobs, start=1):
        out = _process_frame_worker(job)
        if out is not None:
            summaries.append(out)
        last_time_str = str(job["radar_item"].get("time_str", ""))
        _write_progress_file(args.progress_file, args.shard_id, idx, progress_total, last_time_str)
        now = time.time()
        if idx == 1 or idx == progress_total or now - last_progress_print_ts >= progress_interval:
            _print_progress(progress_label, idx, progress_total, progress_start_ts, f"last={last_time_str}")
            last_progress_print_ts = now
    summaries.sort(key=lambda row: str(row["time_str"]))

    summary_path = args.shard_summary if args.shard_summary is not None else args.out_dir / "stage2_multimodal_summary.json"
    if args.merge_existing_summary and args.shard_summary is None:
        summaries = _merge_existing_summary(summary_path, summaries)
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)


if __name__ == "__main__":
    main()
