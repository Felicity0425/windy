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

STAGE2_SUPPORT_QC_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "stage2_support_qc_policy_v1.json"
)
C2_CONTEXT_WIND_RECORDS_NO_AMDAR = "context_wind_records_no_amdar"

DEFAULT_STAGE2_SUPPORT_QC_POLICY: dict[str, Any] = {
    "policy_name": "stage2_support_qc_policy_v1",
    "policy_version": "1.1",
    "enable_speed_tail": True,
    "enable_superob": True,
    "enable_weight_caps": True,
    "enable_real_space_conf": True,
    "enable_obs_error_model": True,
    "enable_buddy_features": True,
    "hard_speed_max_mps": 150.0,
    "enable_source_anomaly_hard_filter": True,
    "amdar_anomaly_speed_hard_mps": 120.0,
    "other_anomaly_speed_hard_mps": 120.0,
    "enable_amdar_batch_span_hard_filter": False,
    "amdar_anomaly_batch_hspan_deg_hard": 8.0,
    "amdar_anomaly_batch_vspan_m_hard": 8000.0,
    "amdar_speed_tail_start_mps": 70.0,
    "amdar_speed_tail_full_mps": 95.0,
    "amdar_speed_tail_min_factor": 0.10,
    "space_conf_min": 0.02,
    "space_conf_max": 1.0,
    "sigma_reference_mps": 8.0,
    "error_factor_min": 0.05,
    "error_factor_max": 4.0,
    "instrument_sigma_mps": {
        "turb": {"default": 2.0, "high_altitude": 2.5},
        "amdar": {"default": 4.0, "high_altitude": 5.5},
        "other": {"default": 6.0, "high_altitude": 7.5},
    },
    "instrument_sigma_high_altitude_m": 9000.0,
    "repr_floor_mps": 1.5,
    "repr_min_mps": 1.0,
    "repr_max_mps": 18.0,
    "repr_spread_coeff": 0.50,
    "repr_hspan_coeff": 1.0,
    "repr_vspan_coeff": 1.0,
    "repr_hscale_km": 80.0,
    "repr_vscale_m": 1200.0,
    "max_weight_per_batch_per_voxel": 3.0,
    "max_weight_per_flight_per_voxel": 3.0,
    "max_weight_per_source_per_voxel": 20.0,
    "max_single_group_weight_ratio": 0.30,
    "buddy_radius_xy": 1,
    "buddy_radius_z": 0,
    "buddy_min_neighbors": 2,
    "context_view_default": "with_amdar",
}


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


def _load_stage2_support_qc_policy(path: Path | None) -> dict[str, Any]:
    policy = dict(DEFAULT_STAGE2_SUPPORT_QC_POLICY)
    if path is None:
        path = STAGE2_SUPPORT_QC_POLICY_PATH
    if path and path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"Stage2 support QC policy must be a JSON object: {path}")
        policy.update(loaded)
        policy["policy_path"] = str(path)
    else:
        policy["policy_path"] = ""
    return policy


def _policy_float(policy: dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(policy.get(key, default))
    except (TypeError, ValueError):
        value = float(default)
    return value if math.isfinite(value) else float(default)


def _policy_int(policy: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(policy.get(key, default))
    except (TypeError, ValueError):
        return int(default)


def _policy_bool(policy: dict[str, Any], key: str, default: bool) -> bool:
    value = policy.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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


def _count_source(df: pl.DataFrame, source: str) -> int:
    if len(df) == 0 or "source" not in df.columns:
        return 0
    return int(len(df.filter(pl.col("source") == source)))


def _global_audit(df_wind: pl.DataFrame, df_loc: pl.DataFrame, radar_index: list[dict[str, Any]]) -> dict[str, Any]:
    audit = {
        "stage1_clean_wind_rows": int(len(df_wind)),
        "stage1_clean_loc_rows": int(len(df_loc)),
        "radar_index_rows": int(len(radar_index)),
        "radar_index_usable_rows": int(sum(1 for row in radar_index if row.get("usable"))),
    }
    if "wind_reconstruction_role" in df_wind.columns:
        vc = (
            df_wind.select(pl.col("wind_reconstruction_role").cast(pl.Utf8, strict=False).fill_null("null").alias("wind_reconstruction_role"))
            .to_series()
            .value_counts()
            .sort("count", descending=True)
        )
        audit["stage1_wind_reconstruction_role_counts"] = {str(k): int(v) for k, v in vc.iter_rows()}
        if "source" in df_wind.columns:
            role_source = (
                df_wind.group_by(["source", "wind_reconstruction_role"])
                .agg(pl.len().alias("rows"))
                .sort(["source", "wind_reconstruction_role"])
            )
            audit["stage1_wind_reconstruction_role_by_source"] = role_source.to_dicts()
    confidence_fields = [
        "obs_conf_v2",
        "confidence_tier",
        "confidence_grade",
        "time_uncertainty_s",
        "time_interval_start",
        "time_interval_end",
        "holdout_eligible",
        "stage8_effective_strict_truth",
        "stage8_usage_recommendation",
        "stage11_compat_role_policy",
    ]
    audit["stage1_confidence_fields_present"] = {col: col in df_wind.columns for col in confidence_fields}
    if {"source", "holdout_eligible", "stage8_effective_strict_truth"}.issubset(set(df_wind.columns)):
        strict_audit = (
            df_wind.group_by(["source", "holdout_eligible", "stage8_effective_strict_truth"])
            .agg(pl.len().alias("rows"))
            .sort(["source", "holdout_eligible", "stage8_effective_strict_truth"])
        )
        audit["stage1_truth_flags_by_source"] = strict_audit.to_dicts()
    if "time_group_alignment_flag" in df_wind.columns:
        vc = (
            df_wind.select(pl.col("time_group_alignment_flag").cast(pl.Utf8, strict=False).fill_null("null").alias("time_group_alignment_flag"))
            .to_series()
            .value_counts()
            .sort("count", descending=True)
        )
        audit["stage1_time_group_alignment_flag_counts"] = {str(k): int(v) for k, v in vc.iter_rows()}
    return audit


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
    wind_current_label: pl.DataFrame,
    wind_current_support: pl.DataFrame,
    wind_context: pl.DataFrame,
    wind_frame: pl.DataFrame,
    support_wind_frame: pl.DataFrame,
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
        "fusion_support_includes_current_support_only_rows": True,
        "context_window_definition": "historical context uses target_time +/- context_window_side_minutes excluding abs(delta_time_minutes) <= current_window_side_minutes; context_wind_records additionally include any current support-only wind rows excluded from strict truth candidates",
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
        "wind_current_label_raw_rows": int(len(wind_current_label)),
        "wind_current_support_raw_rows": int(len(wind_current_support)),
        "wind_context_raw_rows": int(len(wind_context)),
        "wind_current_label_amdar_rows": _count_source(wind_current_label, "amdar"),
        "wind_current_label_turb_rows": _count_source(wind_current_label, "turb"),
        "wind_current_support_amdar_rows": _count_source(wind_current_support, "amdar"),
        "wind_current_support_turb_rows": _count_source(wind_current_support, "turb"),
        "wind_context_amdar_rows": _count_source(wind_context, "amdar"),
        "wind_context_turb_rows": _count_source(wind_context, "turb"),
        "wind_current_required_fields_rows": _count_drop_nulls(wind_current, wind_required),
        "wind_current_label_required_fields_rows": _count_drop_nulls(wind_current_label, wind_required),
        "wind_current_support_required_fields_rows": _count_drop_nulls(wind_current_support, wind_required),
        "wind_context_required_fields_rows": _count_drop_nulls(wind_context, wind_required),
        "wind_current_in_domain_rows": _count_in_domain(wind_current),
        "wind_current_label_in_domain_rows": _count_in_domain(wind_current_label),
        "wind_current_support_in_domain_rows": _count_in_domain(wind_current_support),
        "wind_context_in_domain_rows": _count_in_domain(wind_context),
        "wind_current_voxelized_rows": int(len(wind_frame)),
        "wind_current_support_voxelized_rows": int(len(support_wind_frame)),
        "wind_context_voxelized_rows": int(len(context_wind_frame)),
        "wind_current_voxel_records": int(len(wind_grouped)),
        "wind_context_voxel_records": int(len(context_wind_grouped)),
        "wind_support_only_policy": "current rows with wind_reconstruction_role != strict_truth_candidate are excluded from wind_records and merged into context_wind_records as support-only fusion inputs",
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


def _obs_source_expr() -> pl.Expr:
    return (
        pl.when(pl.col("source").cast(pl.Utf8, strict=False).str.to_lowercase() == "turb")
        .then(pl.lit("turb"))
        .when(pl.col("source").cast(pl.Utf8, strict=False).str.to_lowercase() == "amdar")
        .then(pl.lit("amdar"))
        .otherwise(pl.lit("other"))
        .alias("obs_source")
    )


def _speed_tail_factor_expr(policy: dict[str, Any]) -> pl.Expr:
    if not _policy_bool(policy, "enable_speed_tail", True):
        return pl.lit(1.0).alias("speed_tail_factor")
    start = _policy_float(policy, "amdar_speed_tail_start_mps", 70.0)
    full = max(start + 1e-6, _policy_float(policy, "amdar_speed_tail_full_mps", 95.0))
    min_factor = min(1.0, max(0.0, _policy_float(policy, "amdar_speed_tail_min_factor", 0.10)))
    speed = pl.col("support_point_speed_mps")
    t = ((speed - float(start)) / float(full - start)).clip(lower_bound=0.0, upper_bound=1.0)
    smooth = 0.5 - 0.5 * (math.pi * t).cos()
    factor = 1.0 - (1.0 - float(min_factor)) * smooth
    return (
        pl.when(pl.col("obs_source") == "turb")
        .then(pl.lit(1.0))
        .when(speed <= float(start))
        .then(pl.lit(1.0))
        .when(speed >= float(full))
        .then(pl.lit(float(min_factor)))
        .otherwise(factor)
        .alias("speed_tail_factor")
    )


def _optional_float_col(df: pl.DataFrame, name: str, default: float = 0.0) -> pl.Expr:
    if name in df.columns:
        return pl.col(name).cast(pl.Float64, strict=False).fill_null(float(default))
    return pl.lit(float(default))


def _support_hard_reject_exprs(df: pl.DataFrame, policy: dict[str, Any]) -> list[pl.Expr]:
    speed = pl.col("support_point_speed_mps").cast(pl.Float64, strict=False)
    global_speed_max = _policy_float(policy, "hard_speed_max_mps", 150.0)
    enable_source_filter = _policy_bool(policy, "enable_source_anomaly_hard_filter", True)
    amdar_speed_hard = _policy_float(policy, "amdar_anomaly_speed_hard_mps", 120.0)
    other_speed_hard = _policy_float(policy, "other_anomaly_speed_hard_mps", 120.0)

    invalid_speed = speed > float(global_speed_max)
    amdar_anomalous_speed = (
        pl.lit(bool(enable_source_filter))
        & (pl.col("obs_source") == "amdar")
        & (speed >= float(amdar_speed_hard))
    )
    other_anomalous_speed = (
        pl.lit(bool(enable_source_filter))
        & (pl.col("obs_source") == "other")
        & (speed >= float(other_speed_hard))
    )

    same_hspan = _optional_float_col(df, "same_time_group_hspan_deg")
    batch_hspan = _optional_float_col(df, "amdar_batch_hspan_deg")
    same_vspan = _optional_float_col(df, "same_time_group_alt_span_m")
    batch_vspan = _optional_float_col(df, "amdar_batch_vertical_span_m")
    hspan = pl.max_horizontal(same_hspan.abs(), batch_hspan.abs())
    vspan = pl.max_horizontal(same_vspan.abs(), batch_vspan.abs())
    enable_batch_span_filter = _policy_bool(policy, "enable_amdar_batch_span_hard_filter", False)
    batch_hspan_hard = _policy_float(policy, "amdar_anomaly_batch_hspan_deg_hard", 8.0)
    batch_vspan_hard = _policy_float(policy, "amdar_anomaly_batch_vspan_m_hard", 8000.0)
    amdar_anomalous_batch_span = (
        pl.lit(bool(enable_batch_span_filter))
        & (pl.col("obs_source") == "amdar")
        & ((hspan >= float(batch_hspan_hard)) | (vspan >= float(batch_vspan_hard)))
    )

    hard_reject = (
        invalid_speed
        | amdar_anomalous_speed
        | other_anomalous_speed
        | amdar_anomalous_batch_span
    ).fill_null(False)
    reason = (
        pl.when(invalid_speed)
        .then(pl.lit("invalid_speed"))
        .when(amdar_anomalous_speed)
        .then(pl.lit("amdar_anomalous_speed"))
        .when(other_anomalous_speed)
        .then(pl.lit("other_anomalous_speed"))
        .when(amdar_anomalous_batch_span)
        .then(pl.lit("amdar_anomalous_batch_span"))
        .otherwise(pl.lit("none"))
        .alias("support_hard_reject_reason")
    )
    return [
        hard_reject.alias("support_hard_reject"),
        reason,
        hspan.alias("support_batch_hspan_deg"),
        vspan.alias("support_batch_vspan_m"),
    ]


def _reject_reason_counts(df: pl.DataFrame) -> dict[str, int]:
    if len(df) == 0 or "support_hard_reject_reason" not in df.columns:
        return {}
    reasons: dict[str, int] = {}
    for reason in df.filter(pl.col("support_hard_reject")).get_column("support_hard_reject_reason").to_list():
        key = str(reason or "unknown")
        reasons[key] = reasons.get(key, 0) + 1
    return reasons


def _instrument_sigma_expr(policy: dict[str, Any], source_col: str = "obs_source", alt_col: str = "alt_meters") -> pl.Expr:
    lookup = policy.get("instrument_sigma_mps", {})
    if not isinstance(lookup, dict):
        lookup = {}
    high_altitude = _policy_float(policy, "instrument_sigma_high_altitude_m", 9000.0)

    def _src_sigma(src: str, key: str, default: float) -> float:
        item = lookup.get(src, {})
        if not isinstance(item, dict):
            return float(default)
        value = item.get(key, item.get("default", default))
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = float(default)
        return value if math.isfinite(value) and value > 0.0 else float(default)

    turb_default = _src_sigma("turb", "default", 2.0)
    turb_high = _src_sigma("turb", "high_altitude", turb_default)
    amdar_default = _src_sigma("amdar", "default", 4.0)
    amdar_high = _src_sigma("amdar", "high_altitude", amdar_default)
    other_default = _src_sigma("other", "default", 6.0)
    other_high = _src_sigma("other", "high_altitude", other_default)
    source = pl.col(source_col)
    high = pl.col(alt_col).cast(pl.Float64, strict=False) >= float(high_altitude)
    return (
        pl.when(source == "turb")
        .then(pl.when(high).then(pl.lit(turb_high)).otherwise(pl.lit(turb_default)))
        .when(source == "amdar")
        .then(pl.when(high).then(pl.lit(amdar_high)).otherwise(pl.lit(amdar_default)))
        .otherwise(pl.when(high).then(pl.lit(other_high)).otherwise(pl.lit(other_default)))
        .alias("instrument_sigma_mps")
    )


def _repr_sigma_expr(policy: dict[str, Any]) -> pl.Expr:
    floor = _policy_float(policy, "repr_floor_mps", 1.5)
    c_spread = _policy_float(policy, "repr_spread_coeff", 0.50)
    c_h = _policy_float(policy, "repr_hspan_coeff", 1.0)
    c_v = _policy_float(policy, "repr_vspan_coeff", 1.0)
    hscale = max(1e-6, _policy_float(policy, "repr_hscale_km", 80.0))
    vscale = max(1e-6, _policy_float(policy, "repr_vscale_m", 1200.0))
    repr_min = max(0.0, _policy_float(policy, "repr_min_mps", 1.0))
    repr_max = max(repr_min, _policy_float(policy, "repr_max_mps", 18.0))
    spread = pl.col("within_group_spread").cast(pl.Float64, strict=False).fill_null(0.0)
    hspan = pl.col("superob_hspan_km").cast(pl.Float64, strict=False).fill_null(0.0)
    vspan = pl.col("superob_vspan_m").cast(pl.Float64, strict=False).fill_null(0.0)
    sigma = (
        float(floor) ** 2
        + float(c_spread) * spread**2
        + float(c_h) * (hspan / float(hscale)) ** 2
        + float(c_v) * (vspan / float(vscale)) ** 2
    ).sqrt()
    return sigma.clip(lower_bound=repr_min, upper_bound=repr_max).alias("repr_sigma_mps")


def _add_support_group_id(df: pl.DataFrame) -> pl.DataFrame:
    if len(df) == 0:
        return df
    cols = set(df.columns)
    exprs: list[pl.Expr] = []
    if "source" not in cols:
        exprs.append(pl.lit("other").alias("source"))
    if "flight_id" not in cols:
        exprs.append(pl.lit("").alias("flight_id"))
    if "source_row_index" not in cols:
        exprs.append(pl.lit(None).alias("source_row_index"))
    if "time_utc" not in cols:
        exprs.append(pl.lit(None).alias("time_utc"))
    if exprs:
        df = df.with_columns(exprs)
    return df.with_columns(
        [
            pl.when(pl.col("flight_id").cast(pl.Utf8, strict=False).fill_null("").str.len_chars() > 0)
            .then(pl.col("flight_id").cast(pl.Utf8, strict=False).fill_null(""))
            .otherwise(pl.concat_str([pl.lit("row"), pl.col("source_row_index").cast(pl.Utf8, strict=False).fill_null("unknown")], separator="_"))
            .alias("_support_flight_key"),
            pl.col("time_utc").dt.strftime("%Y%m%d%H%M%S").fill_null("unknown_time").alias("_support_time_key"),
        ]
    ).with_columns(
        pl.concat_str(
            [
                pl.col("obs_source"),
                pl.col("_support_flight_key"),
                pl.col("_support_time_key"),
            ],
            separator="|",
        ).alias("support_group_id")
    )


def _prepare_support_points(
    df: pl.DataFrame,
    halflife_minutes: float,
    roi_lat: float,
    roi_lon: float,
    roi_alt_m: float,
    space_sigma_km: float,
    vertical_sigma_m: float,
    policy: dict[str, Any],
) -> tuple[pl.DataFrame, dict[str, Any]]:
    if len(df) == 0:
        return df, {"input_rows": 0, "hard_reject_rows": 0}
    df = _filter_valid_numeric_rows(df, ["u_wind", "v_wind", "lat_clean", "lon_clean", "alt_meters", "delta_time_minutes"])
    if len(df) == 0:
        return df, {"input_rows": 0, "hard_reject_rows": 0}
    if "obs_conf" not in df.columns:
        df = df.with_columns(pl.lit(1.0).alias("obs_conf"))
    if "obs_conf_raw_for_reconstruction" not in df.columns:
        df = df.with_columns(pl.col("obs_conf").cast(pl.Float64, strict=False).alias("obs_conf_raw_for_reconstruction"))
    if "wind_reconstruction_role" not in df.columns:
        df = df.with_columns(pl.lit("strict_truth_candidate").alias("wind_reconstruction_role"))
    if "wind_reconstruction_exclusion_reason" not in df.columns:
        df = df.with_columns(pl.lit("none").alias("wind_reconstruction_exclusion_reason"))
    if "source" not in df.columns:
        df = df.with_columns(pl.lit("other").alias("source"))

    space_sigma = max(1e-6, float(space_sigma_km))
    vertical_sigma = max(1e-6, float(vertical_sigma_m))
    space_min = min(1.0, max(0.0, _policy_float(policy, "space_conf_min", 0.02)))
    space_max = min(1.0, max(space_min, _policy_float(policy, "space_conf_max", 1.0)))
    use_space = _policy_bool(policy, "enable_real_space_conf", True)

    prepared = (
        df.with_columns(
            [
                _obs_source_expr(),
                _time_conf_expr(halflife_minutes),
                _haversine_expr("lat_clean", "lon_clean", roi_lat, roi_lon),
                (pl.col("alt_meters") - float(roi_alt_m)).abs().alias("vertical_delta_to_roi_m"),
                (pl.col("u_wind") ** 2 + pl.col("v_wind") ** 2).sqrt().alias("support_point_speed_mps"),
                pl.lit(float(roi_lat)).alias("roi_center_lat"),
                pl.lit(float(roi_lon)).alias("roi_center_lon"),
                pl.lit(float(roi_alt_m)).alias("roi_center_alt_m"),
            ]
        )
        .with_columns(_support_hard_reject_exprs(df, policy))
    )
    reject_reason_counts = _reject_reason_counts(prepared)
    prepared = prepared.with_columns(
        (
            (
                -0.5 * (pl.col("distance_to_roi_km") / float(space_sigma)) ** 2
                - 0.5 * (pl.col("vertical_delta_to_roi_m") / float(vertical_sigma)) ** 2
            ).exp()
            if use_space
            else pl.lit(1.0)
        )
        .clip(lower_bound=space_min, upper_bound=space_max)
        .alias("space_conf")
    )
    prepared = prepared.with_columns(
        [
            pl.col("time_conf").alias("time_likelihood"),
            pl.col("space_conf").alias("space_likelihood"),
            _speed_tail_factor_expr(policy),
            _instrument_sigma_expr(policy),
        ]
    )
    prepared = _add_support_group_id(prepared)
    prepared = prepared.filter(~pl.col("support_hard_reject"))
    if len(prepared) == 0:
        return prepared, {
            "input_rows": int(len(df)),
            "hard_reject_rows": int(len(df)),
            "hard_reject_reason_counts": reject_reason_counts,
        }
    point_sigma = pl.col("instrument_sigma_mps")
    reference = max(1e-6, _policy_float(policy, "sigma_reference_mps", 8.0))
    f_min = _policy_float(policy, "error_factor_min", 0.05)
    f_max = max(f_min, _policy_float(policy, "error_factor_max", 4.0))
    prepared = prepared.with_columns(
        [
            point_sigma.alias("total_obs_error_sigma_mps"),
            ((float(reference) / point_sigma) ** 2).clip(lower_bound=f_min, upper_bound=f_max).alias("error_factor"),
        ]
    ).with_columns(
        (
            pl.col("obs_conf").cast(pl.Float64, strict=False).fill_null(1.0)
            * pl.col("time_conf").cast(pl.Float64, strict=False).fill_null(0.0)
            * pl.col("space_conf").cast(pl.Float64, strict=False).fill_null(1.0)
            * pl.col("speed_tail_factor").cast(pl.Float64, strict=False).fill_null(1.0)
            * pl.col("error_factor").cast(pl.Float64, strict=False).fill_null(1.0)
        ).alias("support_pre_weight")
    )
    return prepared, {
        "input_rows": int(len(df)),
        "hard_reject_rows": int(len(df) - len(prepared)),
        "hard_reject_reason_counts": reject_reason_counts,
    }


def _safe_weighted_expr(value_col: str, weight_col: str, alias: str) -> pl.Expr:
    weight_sum = pl.col(weight_col).sum()
    return ((pl.col(value_col) * pl.col(weight_col)).sum() / weight_sum.clip(lower_bound=1e-12)).alias(alias)


def _superob_context_wind(points: pl.DataFrame, policy: dict[str, Any]) -> pl.DataFrame:
    if len(points) == 0:
        return points
    if not _policy_bool(policy, "enable_superob", True):
        points = points.with_columns(
            [
                pl.lit(1).alias("superob_raw_count"),
                pl.lit(1.0).alias("superob_eff_n"),
                pl.lit(0.0).alias("within_group_spread"),
                pl.lit(0.0).alias("superob_hspan_km"),
                pl.lit(0.0).alias("superob_vspan_m"),
                pl.col("support_pre_weight").alias("superob_pre_cap_weight"),
            ]
        )
        return points.rename({"u_wind": "u", "v_wind": "v"})

    grouped = points.group_by(["support_group_id", "z", "y", "x"]).agg(
        [
            _safe_weighted_expr("u_wind", "support_pre_weight", "u"),
            _safe_weighted_expr("v_wind", "support_pre_weight", "v"),
            _safe_weighted_expr("lat_clean", "support_pre_weight", "lat_clean"),
            _safe_weighted_expr("lon_clean", "support_pre_weight", "lon_clean"),
            _safe_weighted_expr("alt_meters", "support_pre_weight", "alt_meters"),
            _safe_weighted_expr("delta_time_minutes", "support_pre_weight", "delta_time_minutes"),
            _safe_weighted_expr("time_conf", "support_pre_weight", "time_conf"),
            _safe_weighted_expr("space_conf", "support_pre_weight", "space_conf"),
            _safe_weighted_expr("speed_tail_factor", "support_pre_weight", "speed_tail_factor"),
            _safe_weighted_expr("error_factor", "support_pre_weight", "error_factor"),
            _safe_weighted_expr("obs_conf", "support_pre_weight", "obs_conf"),
            _safe_weighted_expr("obs_conf_raw_for_reconstruction", "support_pre_weight", "obs_conf_raw_for_reconstruction"),
            _safe_weighted_expr("instrument_sigma_mps", "support_pre_weight", "instrument_sigma_mps"),
            _safe_weighted_expr("distance_to_roi_km", "support_pre_weight", "distance_to_roi_km"),
            _safe_weighted_expr("vertical_delta_to_roi_m", "support_pre_weight", "vertical_delta_to_roi_m"),
            _safe_weighted_expr("u_wind", "support_pre_weight", "_u_for_variance"),
            _safe_weighted_expr("v_wind", "support_pre_weight", "_v_for_variance"),
            ((pl.col("u_wind") ** 2 * pl.col("support_pre_weight")).sum() / pl.col("support_pre_weight").sum().clip(lower_bound=1e-12)).alias("_u2"),
            ((pl.col("v_wind") ** 2 * pl.col("support_pre_weight")).sum() / pl.col("support_pre_weight").sum().clip(lower_bound=1e-12)).alias("_v2"),
            pl.col("support_pre_weight").sum().alias("superob_pre_cap_weight"),
            ((pl.col("support_pre_weight").sum() ** 2) / ((pl.col("support_pre_weight") ** 2).sum()).clip(lower_bound=1e-12)).alias("superob_eff_n"),
            pl.len().alias("superob_raw_count"),
            pl.col("lat_clean").min().alias("_lat_min"),
            pl.col("lat_clean").max().alias("_lat_max"),
            pl.col("lon_clean").min().alias("_lon_min"),
            pl.col("lon_clean").max().alias("_lon_max"),
            pl.col("alt_meters").min().alias("_alt_min"),
            pl.col("alt_meters").max().alias("_alt_max"),
            pl.col("obs_source").drop_nulls().mode().first().alias("obs_source"),
            pl.col("_support_flight_key").drop_nulls().first().alias("flight_id"),
            pl.col("wind_reconstruction_role").drop_nulls().mode().first().alias("wind_reconstruction_role"),
            pl.col("wind_reconstruction_exclusion_reason").drop_nulls().first().alias("wind_reconstruction_exclusion_reason"),
            pl.col("roi_center_lat").first().alias("roi_center_lat"),
            pl.col("roi_center_lon").first().alias("roi_center_lon"),
            pl.col("roi_center_alt_m").first().alias("roi_center_alt_m"),
            pl.when(pl.col("wind_reconstruction_role") == "support_only_not_strict_truth").then(1).otherwise(0).sum().alias("current_support_only_rows"),
        ]
    )
    grouped = grouped.with_columns(
        [
            ((pl.col("_u2") - pl.col("u") ** 2).clip(lower_bound=0.0) + (pl.col("_v2") - pl.col("v") ** 2).clip(lower_bound=0.0))
            .sqrt()
            .alias("within_group_spread"),
            (
                (((pl.col("_lat_max") - pl.col("_lat_min")) * 111.0) ** 2)
                + (((pl.col("_lon_max") - pl.col("_lon_min")) * 111.0) ** 2)
            )
            .sqrt()
            .alias("superob_hspan_km"),
            (pl.col("_alt_max") - pl.col("_alt_min")).abs().alias("superob_vspan_m"),
        ]
    )
    return grouped.drop(["_u_for_variance", "_v_for_variance", "_u2", "_v2", "_lat_min", "_lat_max", "_lon_min", "_lon_max", "_alt_min", "_alt_max"])


def _apply_support_weight_caps(superobs: pl.DataFrame, policy: dict[str, Any]) -> pl.DataFrame:
    if len(superobs) == 0:
        return superobs
    reference = max(1e-6, _policy_float(policy, "sigma_reference_mps", 8.0))
    f_min = _policy_float(policy, "error_factor_min", 0.05)
    f_max = max(f_min, _policy_float(policy, "error_factor_max", 4.0))
    with_sigma = (
        superobs.with_columns(_repr_sigma_expr(policy))
        .with_columns(
            [
                (pl.col("instrument_sigma_mps") ** 2 + pl.col("repr_sigma_mps") ** 2).sqrt().alias("obs_error_sigma_mps"),
            ]
        )
        .with_columns(
            [
                pl.col("obs_error_sigma_mps").alias("total_obs_error_sigma_mps"),
                pl.col("obs_error_sigma_mps").alias("total_obs_error_sigma_u_mps"),
                pl.col("obs_error_sigma_mps").alias("total_obs_error_sigma_v_mps"),
                ((float(reference) / pl.col("obs_error_sigma_mps")) ** 2).clip(lower_bound=f_min, upper_bound=f_max).alias("superob_error_factor"),
            ]
        )
    )
    if not _policy_bool(policy, "enable_weight_caps", True):
        return with_sigma.with_columns(
            [
                pl.col("superob_pre_cap_weight").alias("support_weight"),
                pl.lit(1.0).alias("superob_cap_reduction_factor"),
                pl.lit(False).alias("support_weight_limited"),
            ]
        )

    max_batch = max(0.0, _policy_float(policy, "max_weight_per_batch_per_voxel", 3.0))
    max_flight = max(0.0, _policy_float(policy, "max_weight_per_flight_per_voxel", 3.0))
    max_source = max(0.0, _policy_float(policy, "max_weight_per_source_per_voxel", 20.0))
    max_ratio = min(1.0, max(0.0, _policy_float(policy, "max_single_group_weight_ratio", 0.30)))
    capped = with_sigma.with_columns(pl.col("superob_pre_cap_weight").clip(upper_bound=max_batch).alias("_weight_batch_cap"))
    capped = capped.with_columns(
        (
            pl.when(pl.col("_weight_batch_cap").sum().over(["z", "y", "x", "flight_id"]) > float(max_flight))
            .then(float(max_flight) / pl.col("_weight_batch_cap").sum().over(["z", "y", "x", "flight_id"]).clip(lower_bound=1e-12))
            .otherwise(pl.lit(1.0))
        ).alias("_flight_cap_factor")
    ).with_columns((pl.col("_weight_batch_cap") * pl.col("_flight_cap_factor")).alias("_weight_flight_cap"))
    capped = capped.with_columns(
        (
            pl.when(pl.col("_weight_flight_cap").sum().over(["z", "y", "x", "obs_source"]) > float(max_source))
            .then(float(max_source) / pl.col("_weight_flight_cap").sum().over(["z", "y", "x", "obs_source"]).clip(lower_bound=1e-12))
            .otherwise(pl.lit(1.0))
        ).alias("_source_cap_factor")
    ).with_columns((pl.col("_weight_flight_cap") * pl.col("_source_cap_factor")).alias("_weight_source_cap"))
    capped = capped.with_columns(
        [
            pl.col("_weight_source_cap").sum().over(["z", "y", "x"]).alias("_voxel_weight_sum"),
            (pl.col("_weight_source_cap").sum().over(["z", "y", "x"]) - pl.col("_weight_source_cap")).clip(lower_bound=0.0).alias("_other_group_weight_sum"),
        ]
    )
    if max_ratio > 0.0 and max_ratio < 1.0:
        ratio_limit = max_ratio / max(1e-12, 1.0 - max_ratio)
        capped = capped.with_columns(
            pl.when(pl.col("_other_group_weight_sum") > 0.0)
            .then(pl.min_horizontal(pl.col("_weight_source_cap"), float(ratio_limit) * pl.col("_other_group_weight_sum")))
            .otherwise(pl.col("_weight_source_cap"))
            .alias("support_weight")
        )
    else:
        capped = capped.with_columns(pl.col("_weight_source_cap").alias("support_weight"))
    capped = capped.with_columns(
        [
            (pl.col("support_weight") / pl.col("superob_pre_cap_weight").clip(lower_bound=1e-12)).clip(lower_bound=0.0, upper_bound=1.0).alias("superob_cap_reduction_factor"),
            (pl.col("support_weight") < (pl.col("superob_pre_cap_weight") - 1e-9)).alias("support_weight_limited"),
        ]
    )
    return capped.drop(
        [
            "_weight_batch_cap",
            "_flight_cap_factor",
            "_weight_flight_cap",
            "_source_cap_factor",
            "_weight_source_cap",
            "_voxel_weight_sum",
            "_other_group_weight_sum",
        ]
    )


def _weighted_median(values: list[float], weights: list[float], ids: list[str]) -> float:
    clean = [
        (str(identifier), float(value), max(0.0, float(weight)))
        for identifier, value, weight in zip(ids, values, weights)
        if math.isfinite(float(value)) and math.isfinite(float(weight)) and float(weight) > 0.0
    ]
    if not clean:
        return float("nan")
    clean.sort(key=lambda item: (item[1], item[0]))
    total = sum(item[2] for item in clean)
    threshold = 0.5 * total
    acc = 0.0
    for _, value, weight in clean:
        acc += weight
        if acc >= threshold:
            return float(value)
    return float(clean[-1][1])


def _add_context_buddy_features(grouped: pl.DataFrame, policy: dict[str, Any]) -> pl.DataFrame:
    if len(grouped) == 0 or not _policy_bool(policy, "enable_buddy_features", True):
        return grouped.with_columns(
            [
                pl.lit(0.0).alias("context_buddy_innovation_mps"),
                pl.lit(0.0).alias("context_local_spread_mps"),
                pl.lit(0).alias("context_buddy_neighbor_count"),
            ]
        )
    radius_xy = max(0, _policy_int(policy, "buddy_radius_xy", 1))
    radius_z = max(0, _policy_int(policy, "buddy_radius_z", 0))
    records = grouped.to_dicts()
    index: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for row in records:
        key = (int(row.get("z", -1)), int(row.get("y", -1)), int(row.get("x", -1)))
        index.setdefault(key, []).append(row)
    for row in records:
        z = int(row.get("z", -1))
        y = int(row.get("y", -1))
        x = int(row.get("x", -1))
        neighbors: list[dict[str, Any]] = []
        for zz in range(z - radius_z, z + radius_z + 1):
            for yy in range(y - radius_xy, y + radius_xy + 1):
                for xx in range(x - radius_xy, x + radius_xy + 1):
                    if zz == z and yy == y and xx == x:
                        continue
                    neighbors.extend(index.get((zz, yy, xx), []))
        ids = [str(item.get("support_group_id", f"{item.get('z')}:{item.get('y')}:{item.get('x')}")) for item in neighbors]
        weights = [float(item.get("support_weight", 0.0) or 0.0) for item in neighbors]
        if not neighbors or sum(weights) <= 0.0:
            row["context_buddy_innovation_mps"] = 0.0
            row["context_local_spread_mps"] = 0.0
            row["context_buddy_neighbor_count"] = 0
            continue
        med_u = _weighted_median([float(item.get("u", 0.0) or 0.0) for item in neighbors], weights, ids)
        med_v = _weighted_median([float(item.get("v", 0.0) or 0.0) for item in neighbors], weights, ids)
        innovation = math.sqrt((float(row.get("u", 0.0) or 0.0) - med_u) ** 2 + (float(row.get("v", 0.0) or 0.0) - med_v) ** 2)
        residuals = [math.sqrt((float(item.get("u", 0.0) or 0.0) - med_u) ** 2 + (float(item.get("v", 0.0) or 0.0) - med_v) ** 2) for item in neighbors]
        spread = 1.4826 * _weighted_median(residuals, weights, ids)
        row["context_buddy_innovation_mps"] = float(innovation) if math.isfinite(innovation) else 0.0
        row["context_local_spread_mps"] = float(spread) if math.isfinite(spread) else 0.0
        row["context_buddy_neighbor_count"] = int(len(neighbors))
    return pl.DataFrame(records)


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
    df = _filter_valid_numeric_rows(df, ["lat_clean", "lon_clean", "alt_meters"])
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


def _split_current_label_support(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    if len(df) == 0:
        return df, df
    if "wind_reconstruction_role" not in df.columns:
        empty = df.head(0)
        return df, empty
    strict_source = pl.col("source").cast(pl.Utf8, strict=False).str.to_lowercase() == "turb" if "source" in df.columns else pl.lit(True)
    label_mask = (pl.col("wind_reconstruction_role") == "strict_truth_candidate") & strict_source
    label = df.filter(label_mask)
    support = df.filter(~label_mask)
    return label, support


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
    support_qc_policy: dict[str, Any] | None = None,
) -> pl.DataFrame:
    if len(df) == 0:
        return pl.DataFrame()
    policy = dict(DEFAULT_STAGE2_SUPPORT_QC_POLICY)
    if support_qc_policy:
        policy.update(support_qc_policy)
    support_points, prep_diag = _prepare_support_points(
        df,
        halflife_minutes,
        roi_lat,
        roi_lon,
        roi_alt_m,
        space_sigma_km,
        vertical_sigma_m,
        policy,
    )
    if len(support_points) == 0:
        return pl.DataFrame()
    superobs = _superob_context_wind(support_points, policy)
    weighted = _apply_support_weight_caps(superobs, policy)
    if len(weighted) == 0:
        return pl.DataFrame()
    weighted = weighted.with_columns(
        pl.col("support_weight").sum().over(["z", "y", "x"]).clip(lower_bound=1e-12).alias("_voxel_support_weight_sum")
    ).with_columns(
        [
            (pl.col("support_weight") / pl.col("_voxel_support_weight_sum")).alias("_voxel_weight_fraction"),
        ]
    ).with_columns(
        [
            (-(pl.col("_voxel_weight_fraction") * pl.col("_voxel_weight_fraction").clip(lower_bound=1e-12).log())).alias(
                "_weight_entropy_component"
            ),
        ]
    )
    agg_exprs = [
        _safe_weighted_expr("u", "support_weight", "u"),
        _safe_weighted_expr("v", "support_weight", "v"),
        pl.col("superob_raw_count").sum().alias("obs_count"),
        pl.len().alias("superob_count"),
        pl.col("superob_eff_n").sum().alias("superob_eff_n"),
        pl.col("superob_pre_cap_weight").sum().alias("superob_pre_cap_weight"),
        pl.col("support_weight").sum().alias("support_weight"),
        (pl.col("support_weight").sum() / pl.col("superob_pre_cap_weight").sum().clip(lower_bound=1e-12)).clip(lower_bound=0.0, upper_bound=1.0).alias("superob_cap_reduction_factor"),
        pl.col("support_weight_limited").fill_null(False).cast(pl.Int64).sum().alias("support_weight_limited_count"),
        pl.col("delta_time_minutes").abs().min().alias("nearest_delta_time_minutes"),
        _safe_weighted_expr("delta_time_minutes", "support_weight", "mean_delta_time_minutes"),
        _safe_weighted_expr("time_conf", "support_weight", "time_conf"),
        _safe_weighted_expr("time_conf", "support_weight", "time_likelihood"),
        _safe_weighted_expr("distance_to_roi_km", "support_weight", "distance_to_roi_km"),
        _safe_weighted_expr("vertical_delta_to_roi_m", "support_weight", "vertical_delta_to_roi_m"),
        _safe_weighted_expr("space_conf", "support_weight", "space_conf"),
        _safe_weighted_expr("space_conf", "support_weight", "space_likelihood"),
        _safe_weighted_expr("speed_tail_factor", "support_weight", "speed_tail_factor"),
        _safe_weighted_expr("error_factor", "support_weight", "stage2_point_error_factor"),
        _safe_weighted_expr("superob_error_factor", "support_weight", "stage2_superob_error_factor"),
        _safe_weighted_expr("obs_error_sigma_mps", "support_weight", "obs_error_sigma_mps"),
        _safe_weighted_expr("total_obs_error_sigma_u_mps", "support_weight", "total_obs_error_sigma_u_mps"),
        _safe_weighted_expr("total_obs_error_sigma_v_mps", "support_weight", "total_obs_error_sigma_v_mps"),
        _safe_weighted_expr("instrument_sigma_mps", "support_weight", "instrument_sigma_mps"),
        _safe_weighted_expr("repr_sigma_mps", "support_weight", "repr_sigma_mps"),
        _safe_weighted_expr("within_group_spread", "support_weight", "within_group_spread"),
        _safe_weighted_expr("superob_hspan_km", "support_weight", "superob_hspan_km"),
        _safe_weighted_expr("superob_vspan_m", "support_weight", "superob_vspan_m"),
        _safe_weighted_expr("obs_conf", "support_weight", "obs_conf"),
        _safe_weighted_expr("obs_conf_raw_for_reconstruction", "support_weight", "obs_conf_raw_for_reconstruction"),
        _safe_weighted_expr("lat_clean", "support_weight", "lat_clean"),
        _safe_weighted_expr("lon_clean", "support_weight", "lon_clean"),
        _safe_weighted_expr("alt_meters", "support_weight", "alt_meters"),
        pl.col("support_weight").max().alias("max_single_support_group_weight"),
        pl.col("_weight_entropy_component").sum().alias("weight_entropy"),
        pl.col("support_group_id").drop_nulls().first().alias("support_group_id"),
        pl.col("obs_source").drop_nulls().mode().first().alias("obs_source"),
        pl.col("roi_center_lat").first().alias("roi_center_lat"),
        pl.col("roi_center_lon").first().alias("roi_center_lon"),
        pl.col("roi_center_alt_m").first().alias("roi_center_alt_m"),
        pl.col("current_support_only_rows").sum().alias("current_support_only_rows"),
        pl.when(pl.col("wind_reconstruction_role") == "support_only_not_strict_truth")
        .then(pl.col("wind_reconstruction_exclusion_reason"))
        .otherwise(None)
        .drop_nulls()
        .first()
        .alias("support_exclusion_reason"),
    ]
    grouped = weighted.group_by(["z", "y", "x"]).agg(_append_confidence_agg_exprs(weighted, agg_exprs))
    grouped = grouped.with_columns(
        [
            (pl.col("u") ** 2 + pl.col("v") ** 2).sqrt().alias("wind_speed_diagnostic"),
            pl.lit(1.0).alias("quality_conf_diagnostic"),
            _density_conf_expr("obs_count"),
            (pl.col("support_weight") / pl.col("obs_count").cast(pl.Float64).clip(lower_bound=1e-12)).alias("joint_likelihood"),
            (pl.col("mean_delta_time_minutes").abs()).alias("mean_abs_delta_time_minutes"),
            (pl.col("support_weight_limited_count") > 0).alias("support_weight_limited"),
        ]
    )
    grouped = grouped.with_columns(
        [
            (pl.col("max_single_support_group_weight") / pl.col("support_weight").clip(lower_bound=1e-12)).alias("max_group_weight_ratio"),
            pl.lit(int(prep_diag.get("hard_reject_rows", 0))).alias("support_hard_reject_rows_frame"),
            pl.lit(json.dumps(prep_diag.get("hard_reject_reason_counts", {}), sort_keys=True)).alias(
                "support_hard_reject_reason_counts_frame"
            ),
        ]
    )
    grouped = grouped.with_columns((pl.col("obs_count") - pl.col("current_support_only_rows")).clip(lower_bound=0).alias("historical_context_rows"))
    grouped = grouped.with_columns(
        pl.when(pl.col("current_support_only_rows") > 0)
        .then(
            pl.when(pl.col("historical_context_rows") > 0)
            .then(pl.lit("mixed_support_and_historical_context"))
            .otherwise(pl.lit("current_support_only_not_strict_truth"))
        )
        .otherwise(pl.lit("historical_context"))
        .alias("support_record_role")
    )
    return grouped.with_columns(
        [
            _qc_flags_expr("wind_speed_diagnostic", "obs_count", 120.0),
            pl.lit("context").alias("source_role"),
            pl.lit("with_amdar").alias("context_view"),
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
    motion = _filter_valid_numeric_rows(df, ["u_motion", "v_motion", "lat_clean", "lon_clean", "alt_meters", "delta_time_minutes"])
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


def _filter_valid_numeric_rows(
    df: pl.DataFrame,
    required_float_cols: list[str],
    required_nonnull_cols: list[str] | None = None,
) -> pl.DataFrame:
    if len(df) == 0:
        return df
    filters: list[pl.Expr] = []
    for col in required_float_cols:
        if col in df.columns:
            filters.append(pl.col(col).cast(pl.Float64, strict=False).is_finite())
    for col in required_nonnull_cols or []:
        if col in df.columns:
            filters.append(pl.col(col).is_not_null())
    if not filters:
        return df
    return df.filter(pl.all_horizontal(filters))


def _mode_first_expr(col: str, alias: str | None = None) -> pl.Expr:
    return pl.col(col).cast(pl.Utf8, strict=False).drop_nulls().mode().first().alias(alias or f"{col}_mode")


def _sum_bool_expr(col: str, alias: str | None = None) -> pl.Expr:
    return pl.col(col).fill_null(False).cast(pl.Int64).sum().alias(alias or f"{col}_rows")


def _append_confidence_agg_exprs(df: pl.DataFrame, agg_exprs: list[pl.Expr]) -> list[pl.Expr]:
    cols = set(df.columns)
    if "obs_conf_v2" in cols:
        agg_exprs.append(pl.col("obs_conf_v2").cast(pl.Float64, strict=False).mean().alias("obs_conf_v2"))
    if "time_uncertainty_s" in cols:
        agg_exprs.append(pl.col("time_uncertainty_s").cast(pl.Float64, strict=False).mean().alias("mean_time_uncertainty_s"))
    if "confidence_grade" in cols:
        agg_exprs.append(_mode_first_expr("confidence_grade", "confidence_grade_mode"))
    if "confidence_tier" in cols:
        agg_exprs.append(_mode_first_expr("confidence_tier", "confidence_tier_mode"))
    if "stage8_usage_recommendation" in cols:
        agg_exprs.append(_mode_first_expr("stage8_usage_recommendation", "stage8_usage_recommendation_mode"))
    if "stage11_compat_role_policy" in cols:
        agg_exprs.append(_mode_first_expr("stage11_compat_role_policy", "stage11_compat_role_policy"))
    if "holdout_eligible" in cols:
        agg_exprs.append(_sum_bool_expr("holdout_eligible", "holdout_eligible_rows"))
    if "stage8_effective_strict_truth" in cols:
        agg_exprs.append(_sum_bool_expr("stage8_effective_strict_truth", "effective_strict_truth_rows"))
    if "stage8_point_time_strict_truth_available" in cols:
        agg_exprs.append(_sum_bool_expr("stage8_point_time_strict_truth_available", "point_time_strict_truth_rows"))
    if "source" in cols:
        agg_exprs.extend(
            [
                pl.when(pl.col("source") == "amdar").then(1).otherwise(0).sum().alias("amdar_rows"),
                pl.when(pl.col("source") == "turb").then(1).otherwise(0).sum().alias("turb_rows"),
            ]
        )
    return agg_exprs


def _aggregate_current_wind(df: pl.DataFrame) -> pl.DataFrame:
    schema = {"z": pl.Int64, "y": pl.Int64, "x": pl.Int64, "u": pl.Float64, "v": pl.Float64, "obs_count": pl.UInt32, "obs_conf": pl.Float64}
    if not _has_cols(df, ["z", "y", "x", "u_wind", "v_wind", "obs_conf"]):
        return _empty_df(schema)
    df = _filter_valid_numeric_rows(df, ["u_wind", "v_wind", "obs_conf"])
    if len(df) == 0:
        return _empty_df(schema)
    if "obs_conf_raw_for_reconstruction" not in df.columns:
        df = df.with_columns(pl.col("obs_conf").cast(pl.Float64, strict=False).alias("obs_conf_raw_for_reconstruction"))
    agg_exprs = [
        pl.col("u_wind").mean().alias("u"),
        pl.col("v_wind").mean().alias("v"),
        pl.len().alias("obs_count"),
        pl.col("obs_conf").mean().alias("obs_conf"),
        pl.col("obs_conf_raw_for_reconstruction").mean().alias("obs_conf_raw_for_reconstruction"),
    ]
    return df.group_by(["z", "y", "x"]).agg(_append_confidence_agg_exprs(df, agg_exprs))


def _aggregate_current_loc(df: pl.DataFrame) -> pl.DataFrame:
    schema = {"z": pl.Int64, "y": pl.Int64, "x": pl.Int64, "density": pl.UInt32}
    if not _has_cols(df, ["z", "y", "x"]):
        return _empty_df(schema)
    return df.group_by(["z", "y", "x"]).agg(pl.len().alias("density"))


def _aggregate_current_motion(df: pl.DataFrame) -> pl.DataFrame:
    schema = {"z": pl.Int64, "y": pl.Int64, "x": pl.Int64, "u_motion": pl.Float64, "v_motion": pl.Float64, "motion_count": pl.UInt32}
    if not _has_cols(df, ["z", "y", "x", "u_motion", "v_motion"]):
        return _empty_df(schema)
    motion = _filter_valid_numeric_rows(df, ["u_motion", "v_motion"])
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
    filtered = _filter_valid_numeric_rows(df.filter(pl.col("source") == source), ["u_wind", "v_wind"])
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
    support_qc_policy: dict[str, Any] | None = None,
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
    wind_current_label, wind_current_support = _split_current_label_support(wind_current)
    loc_current, loc_context = _split_current_context(df_loc, target_time, current_window_minutes)
    wind_frame = _with_voxel_columns(wind_current_label, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    loc_frame = _with_voxel_columns(loc_current, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    support_wind_frame = _with_voxel_columns(wind_current_support, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    context_wind_frame = _with_voxel_columns(wind_context, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    fusion_support_wind_frame = pl.concat([support_wind_frame, context_wind_frame], how="diagonal_relaxed") if len(support_wind_frame) or len(context_wind_frame) else pl.DataFrame()
    context_loc_frame = _with_voxel_columns(loc_context, h_dim, w_dim, xy_factor, z_dim, alt_step_m)
    roi_lat, roi_lon, roi_alt_m, roi_source = _eval_roi_center(loc_frame)

    wind_grouped = _aggregate_current_wind(wind_frame)
    loc_grouped = _aggregate_current_loc(loc_frame)
    motion_grouped = _aggregate_current_motion(loc_frame)
    support_qc_policy = dict(DEFAULT_STAGE2_SUPPORT_QC_POLICY if support_qc_policy is None else support_qc_policy)
    context_wind_grouped = _aggregate_context_wind(
        fusion_support_wind_frame,
        time_conf_halflife_minutes,
        roi_lat,
        roi_lon,
        roi_alt_m,
        space_sigma_km,
        vertical_sigma_m,
        support_qc_policy=support_qc_policy,
    )
    no_amdar_support_frame = (
        fusion_support_wind_frame.filter(pl.col("source").cast(pl.Utf8, strict=False).str.to_lowercase() != "amdar")
        if len(fusion_support_wind_frame) and "source" in fusion_support_wind_frame.columns
        else fusion_support_wind_frame
    )
    context_wind_grouped_no_amdar = _aggregate_context_wind(
        no_amdar_support_frame,
        time_conf_halflife_minutes,
        roi_lat,
        roi_lon,
        roi_alt_m,
        space_sigma_km,
        vertical_sigma_m,
        support_qc_policy=support_qc_policy,
    )
    if len(context_wind_grouped):
        context_wind_grouped = _add_context_buddy_features(context_wind_grouped, support_qc_policy)
    if len(context_wind_grouped_no_amdar):
        context_wind_grouped_no_amdar = _add_context_buddy_features(context_wind_grouped_no_amdar, support_qc_policy).with_columns(
            pl.lit("no_amdar").alias("context_view")
        )
    context_motion_grouped = _aggregate_context_motion(context_loc_frame, time_conf_halflife_minutes, roi_lat, roi_lon, roi_alt_m, space_sigma_km, vertical_sigma_m)
    flight_raw = _filter_valid_numeric_rows(
        loc_frame,
        ["u_motion", "v_motion", "lat_clean", "lon_clean", "alt_meters"],
        required_nonnull_cols=["flight_id", "time_utc"],
    )
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
        wind_current_label=wind_current_label,
        wind_current_support=wind_current_support,
        wind_context=wind_context,
        wind_frame=wind_frame,
        support_wind_frame=support_wind_frame,
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
        C2_CONTEXT_WIND_RECORDS_NO_AMDAR: np.array(_records(context_wind_grouped_no_amdar), dtype=object),
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
                    "context_excludes_current_window": False,
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
                    "context_window_definition": "target_time +/- context_window_side_minutes historical context plus any current-window support-only wind rows excluded from strict truth candidates",
                    "wind_record_role_policy": "wind_records contain only strict_truth_candidate current wind rows; support-only current rows are merged into context_wind_records",
                    "current_support_rows_excluded_from_wind_records": int(len(wind_current_support)),
                    "current_label_rows_kept_in_wind_records": int(len(wind_current_label)),
                    "reference_center_policy": "current_window_flight_median_after_voxel_domain_filter",
                    "reference_center_fallback": "domain_bbox_center_lat_33.2_lon_104.0_alt_0_when_current_window_flight_records_empty_or_missing",
                    "reference_center_source": roi_source,
                    "reference_center_lat": float(roi_lat),
                    "reference_center_lon": float(roi_lon),
                    "reference_center_alt_m": float(roi_alt_m),
                    "reference_center_used_for_weighting": False,
                    "stage2_space_conf_mode": "neutral_all_in",
                    "stage2_v2_support_qc_policy": support_qc_policy,
                    "stage2_v2_context_views": ["with_amdar", "no_amdar"],
                    "target_voxel_localization_deferred_to_stage4": True,
                    "roi_center_source": roi_source,
                    "roi_center_lat": float(roi_lat),
                    "roi_center_lon": float(roi_lon),
                    "roi_center_alt_m": float(roi_alt_m),
                    "time_conf_formula": "0.5 ** (abs(delta_time_minutes) / halflife_minutes)",
                    "time_conf_halflife_minutes": float(time_conf_halflife_minutes),
                    "space_conf_formula": "stage2_v2 real ROI representativeness confidence = exp(-0.5*(distance/space_sigma)^2 -0.5*(vertical_delta/vertical_sigma)^2), clipped by policy",
                    "space_sigma_km": float(space_sigma_km),
                    "vertical_sigma_m": float(vertical_sigma_m),
                    "stage4_target_voxel_localization_note": "Stage4 should compute spatial localization from observation voxel to each target voxel, not from observation to reference_center",
                    "joint_likelihood_formula": "stage2_v2 support_weight/obs_count after time, space, speed-tail, obs-error, super-ob and cap factors",
                    "diagnostic_confidence_policy": "stage2_v2 support_weight is active for context support; wind_records strict truth channel unchanged",
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
        "stage2_v2_support_qc_policy_path": str(support_qc_policy.get("policy_path", "")),
        "stage2_v2_context_views": ["with_amdar", "no_amdar"],
        "target_voxel_localization_deferred_to_stage4": 1,
        "wind_record_role_policy": "wind_records=strict current truth candidates only; context_wind_records=historical context plus current support-only wind rows",
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
        "context_wind_no_amdar_voxels": int(len(context_wind_grouped_no_amdar)),
        "current_support_only_rows": int(len(wind_current_support)),
        "current_label_rows": int(len(wind_current_label)),
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
        if args.support_qc_policy:
            cmd.extend(["--support-qc-policy", str(args.support_qc_policy)])
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
    parser.add_argument("--support-qc-policy", type=Path, default=STAGE2_SUPPORT_QC_POLICY_PATH)
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
    support_qc_policy = _load_stage2_support_qc_policy(args.support_qc_policy)
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
            "support_qc_policy": support_qc_policy,
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
