"""Slice visualization for regenerated centralized_v1 Stage2 voxel observations."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import DELTA_ALT, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from stage.centralized_v1.configs.centralized_v1_contract import (
    C2_CLOUD_2D,
    C2_CONTEXT_WIND_RECORDS,
    C2_GRID_SHAPE,
    C2_LOC_RECORDS,
    C2_MOTION_RECORDS,
    C2_MULTIMODAL_META_JSON,
    C2_TIME_STR,
    C2_WIND_RECORDS,
)


RECORD_STYLES = {
    "current_wind": {
        "source": "wind_records",
        "color": "#ff7a00",
        "marker": "arrow/circle",
        "meaning": "Current +/-5 min wind label candidates; u/v drives orange arrows; later Stage4 hold-out candidates.",
    },
    "context_wind": {
        "source": "context_wind_records",
        "color": "magma / #d936c9",
        "marker": "x",
        "meaning": "Historical +/-360 min context wind excluding current window; color encodes wind speed and size follows time_conf. Stage2 space_conf is neutral.",
    },
    "traj": {
        "source": "loc_records",
        "color": "#2aa8ff",
        "marker": "dot",
        "meaning": "Current-window trajectory density voxels.",
    },
    "motion": {
        "source": "motion_records",
        "color": "#20b25f",
        "marker": "dot",
        "meaning": "Current-window aircraft motion component voxels.",
    },
}

INTEGRITY_FIELDS = [
    "stage1_clean_wind_rows",
    "stage1_clean_loc_rows",
    "radar_index_rows",
    "radar_index_usable_rows",
    "current_window_side_minutes",
    "current_total_span_minutes",
    "context_window_side_minutes",
    "context_total_span_minutes",
    "wind_window_raw_rows",
    "wind_current_raw_rows",
    "wind_current_required_fields_rows",
    "wind_current_in_domain_rows",
    "wind_current_voxelized_rows",
    "wind_current_voxel_records",
    "wind_context_raw_rows",
    "wind_context_required_fields_rows",
    "wind_context_in_domain_rows",
    "wind_context_voxelized_rows",
    "wind_context_voxel_records",
    "loc_window_raw_rows",
    "loc_current_raw_rows",
    "loc_current_required_fields_rows",
    "loc_current_in_domain_rows",
    "loc_current_voxelized_rows",
    "traj_current_voxel_records",
    "motion_current_required_fields_rows",
    "motion_current_voxelized_rows",
    "motion_current_voxel_records",
    "loc_context_raw_rows",
    "loc_context_required_fields_rows",
    "loc_context_in_domain_rows",
    "loc_context_voxelized_rows",
    "motion_context_required_fields_rows",
    "motion_context_voxelized_rows",
    "motion_context_voxel_records",
    "flight_raw_required_rows",
    "flight_raw_voxelized_rows",
    "reference_center_source",
    "reference_center_lat",
    "reference_center_lon",
    "reference_center_alt_m",
]


def _records(arr: np.ndarray) -> list[dict[str, Any]]:
    return [dict(x) for x in arr.tolist()] if len(arr) else []


def _fmt_num(value: Any, digits: int = 6) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return ""
    return f"{number:.{digits}g}"


def _safe_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _range(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    arr = np.asarray(values, dtype=np.float64)
    return float(np.min(arr)), float(np.mean(arr)), float(np.max(arr))


def _record_speed(row: dict[str, Any], u_key: str = "u", v_key: str = "v") -> float | None:
    u = _safe_float(row, u_key)
    v = _safe_float(row, v_key)
    if u is None or v is None:
        return None
    return float(np.hypot(u, v))


def _stats_for(records: list[dict[str, Any]], z_idx: int, record_type: str) -> dict[str, Any]:
    rows = [r for r in records if int(r.get("z", -1)) == z_idx]
    if record_type == "motion":
        speeds = [_record_speed(r, "u_motion", "v_motion") for r in rows]
    else:
        speeds = [_record_speed(r) for r in rows]
    speeds = [v for v in speeds if v is not None]
    time_conf = [_safe_float(r, "time_conf") for r in rows]
    space_conf = [_safe_float(r, "space_conf") for r in rows]
    joint = [_safe_float(r, "joint_likelihood") for r in rows]
    density = [_safe_float(r, "density") for r in rows]
    obs_count = [_safe_float(r, "obs_count") for r in rows]
    motion_count = [_safe_float(r, "motion_count") for r in rows]
    quality_conf = [_safe_float(r, "quality_conf_diagnostic") for r in rows]
    density_conf = [_safe_float(r, "density_conf_diagnostic") for r in rows]
    qc_candidate_count = sum(1 for r in rows if str(r.get("qc_flags", "ok")) != "ok")
    speed_min, speed_mean, speed_max = _range(speeds)
    time_min, time_mean, time_max = _range([v for v in time_conf if v is not None])
    space_min, space_mean, space_max = _range([v for v in space_conf if v is not None])
    joint_min, joint_mean, joint_max = _range([v for v in joint if v is not None])
    density_min, density_mean, density_max = _range([v for v in density if v is not None])
    obs_min, obs_mean, obs_max = _range([v for v in obs_count if v is not None])
    motion_min, motion_mean, motion_max = _range([v for v in motion_count if v is not None])
    quality_min, quality_mean, quality_max = _range([v for v in quality_conf if v is not None])
    density_conf_min, density_conf_mean, density_conf_max = _range([v for v in density_conf if v is not None])
    style = RECORD_STYLES[record_type]
    return {
        "z": z_idx,
        "alt_m": z_idx * DELTA_ALT,
        "record_type": record_type,
        "source": style["source"],
        "color": style["color"],
        "marker": style["marker"],
        "count": len(rows),
        "wind_speed_min": speed_min,
        "wind_speed_mean": speed_mean,
        "wind_speed_max": speed_max,
        "time_conf_min": time_min,
        "time_conf_mean": time_mean,
        "time_conf_max": time_max,
        "space_conf_min": space_min,
        "space_conf_mean": space_mean,
        "space_conf_max": space_max,
        "joint_likelihood_min": joint_min,
        "joint_likelihood_mean": joint_mean,
        "joint_likelihood_max": joint_max,
        "density_min": density_min,
        "density_mean": density_mean,
        "density_max": density_max,
        "obs_count_min": obs_min,
        "obs_count_mean": obs_mean,
        "obs_count_max": obs_max,
        "motion_count_min": motion_min,
        "motion_count_mean": motion_mean,
        "motion_count_max": motion_max,
        "quality_conf_diagnostic_min": quality_min,
        "quality_conf_diagnostic_mean": quality_mean,
        "quality_conf_diagnostic_max": quality_max,
        "density_conf_diagnostic_min": density_conf_min,
        "density_conf_diagnostic_mean": density_conf_mean,
        "density_conf_diagnostic_max": density_conf_max,
        "qc_candidate_count": qc_candidate_count,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _fmt_num(row.get(key)) for key in fieldnames})


def _integrity_rows(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key in INTEGRITY_FIELDS:
        rows.append({"metric": key, "value": audit.get(key, "")})
    return rows


def _write_integrity_csv(path: Path, audit: dict[str, Any]) -> None:
    _write_csv(path, _integrity_rows(audit), ["metric", "value"])


def _write_integrity_md(path: Path, time_str: str, audit: dict[str, Any], png_size: tuple[int, int], z_levels: list[int]) -> None:
    lines = [
        f"# Stage2 Data Integrity Audit - {time_str}",
        "",
        "## Scope",
        "",
        "Stage2 is all-in inside the per-frame time window and Stage2 grid domain. It does not crop by ROI/reference center, but records still pass through time-window selection, China-domain/altitude voxel bounds, required-field checks, and voxel grouping.",
        "",
        f"- Stage1 clean wind rows: `{audit.get('stage1_clean_wind_rows')}`",
        f"- Stage1 clean loc rows: `{audit.get('stage1_clean_loc_rows')}`",
        f"- Radar index rows / usable: `{audit.get('radar_index_rows')}` / `{audit.get('radar_index_usable_rows')}`",
        f"- Current window: target time +/- `{audit.get('current_window_side_minutes')}` min, total `{audit.get('current_total_span_minutes')}` min.",
        f"- Context window: target time +/- `{audit.get('context_window_side_minutes')}` min, total `{audit.get('context_total_span_minutes')}` min, excluding current window.",
        f"- Domain: lat `{audit.get('domain_lat_min')}`-`{audit.get('domain_lat_max')}`, lon `{audit.get('domain_lon_min')}`-`{audit.get('domain_lon_max')}`, altitude `{audit.get('domain_alt_min_m')}`-`{audit.get('domain_alt_max_m')}` m.",
        f"- Grid shape: `{audit.get('grid_shape')}`; radar/cloud shape: `{audit.get('stage2_radar_shape')}`; original radar shape: `{audit.get('radar_original_shape')}`.",
        f"- Rendered PNG size: `{png_size[0]} x {png_size[1]}` px. This comes from matplotlib `figsize=(6.2 * {len(z_levels)}, 9.2)` and `dpi=170`, not from radar resolution.",
        "",
        "## Reference Center",
        "",
        f"- Policy: `{audit.get('reference_center_policy')}`",
        f"- Fallback: `{audit.get('reference_center_fallback')}`",
        f"- Selected center: lat=`{_fmt_num(audit.get('reference_center_lat'))}`, lon=`{_fmt_num(audit.get('reference_center_lon'))}`, alt_m=`{_fmt_num(audit.get('reference_center_alt_m'))}`, source=`{audit.get('reference_center_source')}`",
        f"- Used for Stage2 weighting: `{audit.get('reference_center_used_for_weighting', False)}`",
        f"- Stage2 space confidence mode: `{audit.get('stage2_space_conf_mode', 'neutral_all_in')}`",
        f"- Target-voxel localization deferred to Stage4: `{audit.get('target_voxel_localization_deferred_to_stage4', True)}`",
        "",
        "## Wind Integrity",
        "",
        "| Stage | Raw | Required fields | In domain | Voxelized rows | Voxel records |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| current wind | {audit.get('wind_current_raw_rows')} | {audit.get('wind_current_required_fields_rows')} | {audit.get('wind_current_in_domain_rows')} | {audit.get('wind_current_voxelized_rows')} | {audit.get('wind_current_voxel_records')} |",
        f"| context wind | {audit.get('wind_context_raw_rows')} | {audit.get('wind_context_required_fields_rows')} | {audit.get('wind_context_in_domain_rows')} | {audit.get('wind_context_voxelized_rows')} | {audit.get('wind_context_voxel_records')} |",
        "",
        "## Trajectory And Motion Integrity",
        "",
        "| Stage | Raw loc | Required loc fields | In domain | Voxelized loc rows | Traj voxel records | Motion required fields | Motion voxelized rows | Motion voxel records |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| current | {audit.get('loc_current_raw_rows')} | {audit.get('loc_current_required_fields_rows')} | {audit.get('loc_current_in_domain_rows')} | {audit.get('loc_current_voxelized_rows')} | {audit.get('traj_current_voxel_records')} | {audit.get('motion_current_required_fields_rows')} | {audit.get('motion_current_voxelized_rows')} | {audit.get('motion_current_voxel_records')} |",
        f"| context | {audit.get('loc_context_raw_rows')} | {audit.get('loc_context_required_fields_rows')} | {audit.get('loc_context_in_domain_rows')} | {audit.get('loc_context_voxelized_rows')} |  | {audit.get('motion_context_required_fields_rows')} | {audit.get('motion_context_voxelized_rows')} | {audit.get('motion_context_voxel_records')} |",
        "",
        "## Interpretation",
        "",
        "- Large drops from raw rows to voxel records are expected because records outside the Stage2 grid/altitude range are excluded and multiple observations in the same `(z,y,x)` are grouped.",
        "- Sparse current wind does not mean the radar or trajectory layer failed; it means few current-window wind observations survived the Stage2 grid-domain and current-window constraints.",
        "- QC candidates such as very high context wind speeds are reported, not deleted, in this Stage2 pass.",
        "- Stage2 keeps `space_conf=1.0` for all-in context records. Spatial localization should be computed later in Stage4 from each observation voxel to each target voxel.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _append_integrity_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage2 Data Integrity Summary",
        "",
        "Stage2 is now interpreted as all-in observation organization inside each frame's time window and Stage2 grid domain. It does not use ROI/reference-center distance as a filter.",
        "",
        "| time_str | current wind raw | current wind in-domain | current wind voxels | context wind raw | context wind in-domain | context wind voxels | current loc raw | motion usable current | motion voxels | context loc raw | context motion usable | context motion voxels | reference center |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        audit = row["audit"]
        center = (
            f"lat={_fmt_num(audit.get('reference_center_lat'))}, "
            f"lon={_fmt_num(audit.get('reference_center_lon'))}, "
            f"alt_m={_fmt_num(audit.get('reference_center_alt_m'))}, "
            f"source={audit.get('reference_center_source')}"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["time_str"]),
                    str(audit.get("wind_current_raw_rows")),
                    str(audit.get("wind_current_in_domain_rows")),
                    str(audit.get("wind_current_voxel_records")),
                    str(audit.get("wind_context_raw_rows")),
                    str(audit.get("wind_context_in_domain_rows")),
                    str(audit.get("wind_context_voxel_records")),
                    str(audit.get("loc_current_raw_rows")),
                    str(audit.get("motion_current_required_fields_rows")),
                    str(audit.get("motion_current_voxel_records")),
                    str(audit.get("loc_context_raw_rows")),
                    str(audit.get("motion_context_required_fields_rows")),
                    str(audit.get("motion_context_voxel_records")),
                    center,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Drops from raw rows to voxel records are expected because records are constrained to the target time window, Stage2 China-domain grid, `0-15000m` altitude range, required fields, and then grouped by `(z,y,x)`.",
            "- `20260211060600` has very sparse current wind labels because only one current-window wind observation survives the grid-domain constraints.",
            "- Context observations are not ground-truth labels. They are historical context with `time_conf`, neutral `space_conf=1.0`, and `joint_likelihood=obs_conf*time_conf` for later Stage4 fusion.",
            "- Stage4 should compute spatial localization from each observation voxel to each target voxel; Stage2 no longer downweights observations by distance to `reference_center`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _point_rows(record_type: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for r in records:
        z_idx = int(r.get("z", -1))
        u = _safe_float(r, "u")
        v = _safe_float(r, "v")
        u_motion = _safe_float(r, "u_motion")
        v_motion = _safe_float(r, "v_motion")
        if record_type == "motion":
            wind_speed = _record_speed(r, "u_motion", "v_motion")
        else:
            wind_speed = _record_speed(r)
        rows.append(
            {
                "record_type": record_type,
                "z": z_idx,
                "alt_m": z_idx * DELTA_ALT if z_idx >= 0 else None,
                "y": r.get("y"),
                "x": r.get("x"),
                "u": u,
                "v": v,
                "u_motion": u_motion,
                "v_motion": v_motion,
                "wind_speed": wind_speed,
                "time_conf": _safe_float(r, "time_conf"),
                "space_conf": _safe_float(r, "space_conf"),
                "joint_likelihood": _safe_float(r, "joint_likelihood"),
                "obs_count": _safe_float(r, "obs_count"),
                "density": _safe_float(r, "density"),
                "motion_count": _safe_float(r, "motion_count"),
                "quality_conf_diagnostic": _safe_float(r, "quality_conf_diagnostic"),
                "density_conf_diagnostic": _safe_float(r, "density_conf_diagnostic"),
                "qc_flags": r.get("qc_flags", ""),
            }
        )
    return rows


def _global_count_by_z(records: list[dict[str, Any]], z_dim: int) -> np.ndarray:
    counts = np.zeros(z_dim, dtype=np.int32)
    for r in records:
        zi = int(r.get("z", -1))
        if 0 <= zi < z_dim:
            counts[zi] += 1
    return counts


def _write_explanation(
    path: Path,
    time_str: str,
    cloud: np.ndarray,
    shape: tuple[int, int, int],
    z_levels: list[int],
    x_idx: int,
    x_band: int,
    meta: dict[str, Any],
    stats_rows: list[dict[str, Any]],
    wind_records: list[dict[str, Any]],
    context_wind_records: list[dict[str, Any]],
    loc_records: list[dict[str, Any]],
    motion_records: list[dict[str, Any]],
) -> None:
    z_dim, h_dim, w_dim = shape
    current_counts = _global_count_by_z(wind_records, z_dim)
    context_counts = _global_count_by_z(context_wind_records, z_dim)
    traj_counts = _global_count_by_z(loc_records, z_dim)
    motion_counts = _global_count_by_z(motion_records, z_dim)
    current_total = int(np.sum(current_counts))
    current_in_displayed = int(sum(current_counts[z] for z in z_levels))
    reference_source = meta.get("reference_center_source", meta.get("roi_center_source", "?"))
    reference_lat = meta.get("reference_center_lat", meta.get("roi_center_lat", "?"))
    reference_lon = meta.get("reference_center_lon", meta.get("roi_center_lon", "?"))
    reference_alt = meta.get("reference_center_alt_m", meta.get("roi_center_alt_m", "?"))
    current_side = meta.get("current_window_side_minutes", meta.get("current_window_minutes", "?"))
    current_total = meta.get("current_total_span_minutes", "?")
    context_side = meta.get("context_window_side_minutes", meta.get("context_window_minutes", "?"))
    context_total = meta.get("context_total_span_minutes", "?")
    xy_downsample = meta.get("xy_downsample", "?")
    lines = [
        f"# Stage2 Slice Explanation - {time_str}",
        "",
        "## Stage2 Role",
        "",
        "Stage2 is an all-in observation organization layer inside the per-frame time window and Stage2 grid domain. It does not reconstruct a wind field, does not crop to an ROI, and does not drop records by distance to the reference center.",
        "",
        f"- `stage2_role`: `{meta.get('stage2_role', 'observation_organization_not_reconstruction')}`",
        f"- `all_in_observations`: `{meta.get('all_in_observations', True)}`",
        f"- `all_in_scope`: `{meta.get('all_in_scope', 'per_frame_time_window_grid_domain_required_fields_before_voxel_grouping')}`",
        f"- `reference_center_does_not_filter_records`: `{meta.get('reference_center_does_not_filter_records', True)}`",
        f"- `reference_center_used_for_weighting`: `{meta.get('reference_center_used_for_weighting', False)}`",
        f"- `stage2_space_conf_mode`: `{meta.get('stage2_space_conf_mode', 'neutral_all_in')}`",
        f"- `target_voxel_localization_deferred_to_stage4`: `{meta.get('target_voxel_localization_deferred_to_stage4', True)}`",
        f"- `reference_center`: lat={_fmt_num(reference_lat)}, lon={_fmt_num(reference_lon)}, alt_m={_fmt_num(reference_alt)}, source={reference_source}",
        f"- `reference_center_policy`: `{meta.get('reference_center_policy', 'current_window_flight_median_after_voxel_domain_filter')}`",
        f"- `reference_center_fallback`: `{meta.get('reference_center_fallback', 'domain_bbox_center_lat_33.2_lon_104.0_alt_0_when_current_window_flight_records_empty_or_missing')}`",
        "",
        "## Figure Layout",
        "",
        f"- PNG size is `4216 x 1563` after the default render settings.",
        f"- Grid shape is `{z_dim} x {h_dim} x {w_dim}` with altitude step `{DELTA_ALT:.0f} m`.",
        f"- Top row: horizontal slices at z={','.join(str(z) for z in z_levels)}.",
        f"- Bottom-left: y-z vertical slice near x={x_idx} +/-{x_band}.",
        "- Bottom-right: voxel count by altitude.",
        f"- Radar/cloud layer shape is `{cloud.shape[0]} x {cloud.shape[1]}` after `xy_downsample={xy_downsample}`; nonzero pixels={int(np.count_nonzero(cloud))}; max intensity={_fmt_num(float(np.max(cloud)))}.",
        f"- PNG size is a rendered figure size: `figsize=(6.2 * {len(z_levels)}, 9.2)` at `dpi=170`, not the radar array resolution.",
        f"- Current window means target time +/- `{current_side}` min, total `{current_total}` min.",
        f"- Context window means target time +/- `{context_side}` min, total `{context_total}` min, excluding `abs(delta_time_minutes) <= {current_side}` current-window records.",
        "",
        "## Color And Marker Meaning",
        "",
        "| Type | Source | Color | Marker | Meaning |",
        "| --- | --- | --- | --- | --- |",
    ]
    for key in ("current_wind", "context_wind", "traj", "motion"):
        style = RECORD_STYLES[key]
        lines.append(f"| `{key}` | `{style['source']}` | `{style['color']}` | `{style['marker']}` | {style['meaning']} |")
    lines.extend(
        [
            "",
            "## Selected Z Layers",
            "",
            "| z | altitude_m | current_wind | context_wind | traj | motion |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for z_idx in z_levels:
        lines.append(
            f"| {z_idx} | {z_idx * DELTA_ALT:.0f} | {int(current_counts[z_idx])} | {int(context_counts[z_idx])} | {int(traj_counts[z_idx])} | {int(motion_counts[z_idx])} |"
        )
    if current_total > 0 and current_in_displayed == 0:
        lines.extend(
            [
                "",
                f"Note: this frame has `{current_total}` current wind candidate(s), but none fall on the automatically selected z layers shown in the top row.",
            ]
        )
    lines.extend(
        [
            "",
            "## Per-Layer Statistics",
            "",
            "| z | type | count | wind_speed_min | wind_speed_mean | wind_speed_max | time_conf_min | time_conf_mean | time_conf_max | space_conf_min | space_conf_mean | space_conf_max | joint_likelihood_min | joint_likelihood_mean | joint_likelihood_max |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in stats_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["z"]),
                    f"`{row['record_type']}`",
                    str(row["count"]),
                    _fmt_num(row["wind_speed_min"]),
                    _fmt_num(row["wind_speed_mean"]),
                    _fmt_num(row["wind_speed_max"]),
                    _fmt_num(row["time_conf_min"]),
                    _fmt_num(row["time_conf_mean"]),
                    _fmt_num(row["time_conf_max"]),
                    _fmt_num(row["space_conf_min"]),
                    _fmt_num(row["space_conf_mean"]),
                    _fmt_num(row["space_conf_max"]),
                    _fmt_num(row["joint_likelihood_min"]),
                    _fmt_num(row["joint_likelihood_mean"]),
                    _fmt_num(row["joint_likelihood_max"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Method Notes",
            "",
            "- Stage2 regenerates records from `clean_wind.parquet`, `clean_loc.parquet`, `radar_index.json`, and radar PNG frames.",
            "- Current-window records use target time +/-5 min. Context records use target time +/-360 min, i.e. 6 hours on each side and 12 hours total, and exclude the current-window label records.",
            "- `time_conf = 0.5 ** (abs(delta_time_minutes) / 180)`.",
            "- `space_conf = 1.0` in Stage2 neutral-all-in mode. The reference center is not used for Stage2 weighting.",
            "- `quality_conf_diagnostic`, `density_conf_diagnostic`, and `qc_flags` are report-only diagnostics. They do not change the active `joint_likelihood=obs_conf*time_conf` in Stage2/Stage3.",
            "- Spatial localization is deferred to Stage4, where each target voxel should be weighted by distance to observation voxels rather than distance to the logical Ground Center or reference center.",
            "- The method follows finite-window data-assimilation organization ideas from ECMWF ERA5/IFS 4D-Var, aircraft-observation structure from WMO AMDAR, localization intuition from DART/Gaspari-Cohn-style methods, and gridded temporal-context organization used by WeatherBench2, GraphCast/GenCast, Aurora and FourCastNet.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _scatter_xy(ax, records: list[dict[str, Any]], z_idx: int, color: str, label: str, size: float, alpha: float) -> int:
    pts = [r for r in records if int(r.get("z", -1)) == z_idx]
    if pts:
        ax.scatter([int(r["x"]) for r in pts], [int(r["y"]) for r in pts], s=size, c=color, label=f"{label} ({len(pts)})", alpha=alpha)
    return len(pts)


def _wind_quiver(ax, records: list[dict[str, Any]], z_idx: int) -> int:
    pts = [r for r in records if int(r.get("z", -1)) == z_idx]
    if not pts:
        return 0
    x = np.array([int(r["x"]) for r in pts], dtype=np.float32)
    y = np.array([int(r["y"]) for r in pts], dtype=np.float32)
    u = np.array([float(r.get("u", 0.0)) for r in pts], dtype=np.float32)
    v = np.array([-float(r.get("v", 0.0)) for r in pts], dtype=np.float32)
    ax.quiver(x, y, u, v, color="#ff7a00", alpha=0.85, scale=450, width=0.003)
    ax.scatter(x, y, s=22, c="#ff7a00", edgecolors="black", linewidths=0.25, label=f"wind vectors u/v (m/s) ({len(pts)})")
    return len(pts)


def _context_wind_scatter(ax, records: list[dict[str, Any]], z_idx: int) -> int:
    pts = [r for r in records if int(r.get("z", -1)) == z_idx]
    if not pts:
        return 0
    speeds = np.array([np.hypot(float(r.get("u", 0.0)), float(r.get("v", 0.0))) for r in pts], dtype=np.float32)
    conf = np.array([float(r.get("time_conf", 0.0)) for r in pts], dtype=np.float32)
    size = 8 + 28 * np.clip(conf, 0.0, 1.0)
    ax.scatter(
        [int(r["x"]) for r in pts],
        [int(r["y"]) for r in pts],
        s=size,
        c=speeds,
        cmap="magma",
        marker="x",
        alpha=0.55,
        label=f"context wind speed (m/s) ({len(pts)})",
    )
    return len(pts)


def _render_horizontal(
    ax,
    cloud: np.ndarray,
    wind_records: list[dict[str, Any]],
    context_wind_records: list[dict[str, Any]],
    loc_records: list[dict[str, Any]],
    motion_records: list[dict[str, Any]],
    z_idx: int,
) -> None:
    ax.imshow(cloud, cmap="gray", origin="upper")
    loc_count = _scatter_xy(ax, loc_records, z_idx, "#2aa8ff", "traj voxels (count)", 4, 0.22)
    motion_count = _scatter_xy(ax, motion_records, z_idx, "#20b25f", "motion voxels (count)", 6, 0.28)
    ctx_count = _context_wind_scatter(ax, context_wind_records, z_idx)
    wind_count = _wind_quiver(ax, wind_records, z_idx)
    alt_m = z_idx * DELTA_ALT
    ax.set_title(f"Horizontal z={z_idx} (~{alt_m:.0f} m)\ncurrent={wind_count}, context={ctx_count}, traj={loc_count}, motion={motion_count}")
    ax.set_xlabel("x voxel")
    ax.set_ylabel("y voxel")
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="lower right", fontsize=7, framealpha=0.78)


def _render_vertical_yz(
    ax,
    wind_records: list[dict[str, Any]],
    context_wind_records: list[dict[str, Any]],
    loc_records: list[dict[str, Any]],
    x_idx: int,
    x_band: int,
    z_dim: int,
) -> None:
    def near(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in records if abs(int(r.get("x", -999999)) - x_idx) <= x_band]

    loc_pts = near(loc_records)
    wind_pts = near(wind_records)
    context_pts = near(context_wind_records)
    if loc_pts:
        ax.scatter([int(r["y"]) for r in loc_pts], [int(r["z"]) for r in loc_pts], s=5, c="#2aa8ff", alpha=0.20, label=f"traj near x (count={len(loc_pts)})")
    if context_pts:
        ax.scatter(
            [int(r["y"]) for r in context_pts],
            [int(r["z"]) for r in context_pts],
            s=16,
            c="#d936c9",
            marker="x",
            alpha=0.45,
            label=f"context wind near x (count={len(context_pts)})",
        )
    if wind_pts:
        speeds = np.array([np.hypot(float(r.get("u", 0.0)), float(r.get("v", 0.0))) for r in wind_pts], dtype=np.float32)
        sc = ax.scatter([int(r["y"]) for r in wind_pts], [int(r["z"]) for r in wind_pts], s=34, c=speeds, cmap="turbo", edgecolors="black", linewidths=0.25, label=f"wind near x u/v (m/s) ({len(wind_pts)})")
        plt.colorbar(sc, ax=ax, fraction=0.046, pad=0.04, label="wind speed (m/s)")
    ax.set_ylim(-0.5, z_dim - 0.5)
    ax.set_title(f"Vertical y-z slice near x={x_idx} (+/-{x_band})")
    ax.set_xlabel("y voxel")
    ax.set_ylabel("z level")
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="upper right", fontsize=7, framealpha=0.78)


def _render_altitude_profile(
    ax,
    wind_records: list[dict[str, Any]],
    context_wind_records: list[dict[str, Any]],
    loc_records: list[dict[str, Any]],
    motion_records: list[dict[str, Any]],
    z_dim: int,
) -> None:
    z = np.arange(z_dim)
    wind_counts = np.zeros(z_dim, dtype=np.int32)
    context_counts = np.zeros(z_dim, dtype=np.int32)
    traj_counts = np.zeros(z_dim, dtype=np.int32)
    motion_counts = np.zeros(z_dim, dtype=np.int32)
    for arr, counts in ((wind_records, wind_counts), (context_wind_records, context_counts), (loc_records, traj_counts), (motion_records, motion_counts)):
        for r in arr:
            zi = int(r.get("z", -1))
            if 0 <= zi < z_dim:
                counts[zi] += 1
    ax.plot(wind_counts, z * DELTA_ALT / 1000.0, color="#ff7a00", label="wind voxels (count)")
    ax.plot(context_counts, z * DELTA_ALT / 1000.0, color="#d936c9", label="context wind voxels (count)")
    ax.plot(traj_counts, z * DELTA_ALT / 1000.0, color="#2aa8ff", label="traj voxels (count)")
    ax.plot(motion_counts, z * DELTA_ALT / 1000.0, color="#20b25f", label="motion voxels (count)")
    ax.set_title("Voxel count by altitude")
    ax.set_xlabel("voxel count")
    ax.set_ylabel("altitude (km)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)


def _write_encoding_charts(
    out_dir: Path,
    time_str: str,
    stats_rows: list[dict[str, Any]],
    wind_records: list[dict[str, Any]],
    context_wind_records: list[dict[str, Any]],
    loc_records: list[dict[str, Any]],
    motion_records: list[dict[str, Any]],
    z_dim: int,
) -> Path:
    z_values = np.arange(z_dim)
    counts_by_type = {
        "current_wind": _global_count_by_z(wind_records, z_dim),
        "context_wind": _global_count_by_z(context_wind_records, z_dim),
        "traj": _global_count_by_z(loc_records, z_dim),
        "motion": _global_count_by_z(motion_records, z_dim),
    }
    colors = {
        "current_wind": "#ff7a00",
        "context_wind": "#d936c9",
        "traj": "#2aa8ff",
        "motion": "#20b25f",
    }
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.5), constrained_layout=True)
    ax = axes[0, 0]
    for key, counts in counts_by_type.items():
        ax.plot(counts, z_values * DELTA_ALT / 1000.0, color=colors[key], label=f"{key} (voxel count)")
    ax.set_title("Voxel count by altitude")
    ax.set_xlabel("voxel count")
    ax.set_ylabel("altitude (km)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)

    ax = axes[0, 1]
    layer_labels = [f"z{row['z']}\n{row['record_type']}" for row in stats_rows]
    count_values = [int(row["count"]) for row in stats_rows]
    bar_colors = [colors.get(str(row["record_type"]), "#888888") for row in stats_rows]
    ax.bar(np.arange(len(count_values)), count_values, color=bar_colors, alpha=0.82)
    ax.set_title("Displayed-layer counts by encoded point type")
    ax.set_ylabel("count")
    ax.set_xticks(np.arange(len(layer_labels)))
    ax.set_xticklabels(layer_labels, rotation=75, ha="right", fontsize=7)
    ax.grid(axis="y", alpha=0.2)

    ax = axes[1, 0]
    ctx_speed = np.asarray([_record_speed(row) or np.nan for row in context_wind_records], dtype=np.float64)
    ctx_time = np.asarray([_safe_float(row, "time_conf") or np.nan for row in context_wind_records], dtype=np.float64)
    ok = np.isfinite(ctx_speed) & np.isfinite(ctx_time)
    if np.any(ok):
        sample = np.where(ok)[0]
        if len(sample) > 4000:
            sample = sample[:: max(1, len(sample) // 4000)]
        ax.scatter(ctx_time[sample], ctx_speed[sample], s=8 + 28 * np.clip(ctx_time[sample], 0.0, 1.0), c=ctx_speed[sample], cmap="magma", marker="x", alpha=0.45)
    ax.set_title("Context wind: color=speed (m/s), marker size=time_conf")
    ax.set_xlabel("time_conf")
    ax.set_ylabel("wind speed (m/s)")
    ax.grid(alpha=0.25)

    ax = axes[1, 1]
    legend_items = [
        ("current wind", "arrow/circle", "#ff7a00", "u/v wind (m/s), hold-out candidate"),
        ("context wind", "x", "#d936c9", "speed color (m/s), time_conf size"),
        ("trajectory", "dot", "#2aa8ff", "density voxel count"),
        ("motion", "dot", "#20b25f", "u_motion/v_motion (m/s) voxel"),
    ]
    ax.axis("off")
    ax.set_title("Visual encoding legend")
    for i, (name, marker, color, meaning) in enumerate(legend_items):
        y = 0.82 - i * 0.19
        if marker == "x":
            ax.scatter([0.08], [y], marker="x", s=120, color=color, alpha=0.65)
        elif marker == "arrow/circle":
            ax.scatter([0.08], [y], marker="o", s=85, color=color, edgecolors="black")
            ax.arrow(0.06, y - 0.035, 0.06, 0.03, color=color, width=0.005, head_width=0.025, length_includes_head=True)
        else:
            ax.scatter([0.08], [y], marker="o", s=75, color=color, alpha=0.55)
        ax.text(0.16, y, f"{name}: {marker}; {meaning}", va="center", fontsize=10)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    fig.suptitle(f"Stage2 visual encoding diagnostics - {time_str}", fontsize=13)
    out = out_dir / f"stage2_visual_encoding_{time_str}.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def _auto_z_levels(wind_records: list[dict[str, Any]], context_wind_records: list[dict[str, Any]], z_dim: int, top_k: int) -> list[int]:
    counts = np.zeros(z_dim, dtype=np.int32)
    for records, weight in ((wind_records, 5), (context_wind_records, 1)):
        for r in records:
            zi = int(r.get("z", -1))
            if 0 <= zi < z_dim:
                counts[zi] += weight
    ranked = [int(i) for i in np.argsort(counts)[::-1] if counts[i] > 0]
    if not ranked:
        ranked = [min(z_dim - 1, z_dim // 3), min(z_dim - 1, z_dim // 2), min(z_dim - 1, (2 * z_dim) // 3)]
    return ranked[: max(1, top_k)]


def render_one(frame_npz: Path, out_dir: Path, z_levels: list[int], auto_top_k: int, x_slice: int | None, x_band: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    with np.load(frame_npz, allow_pickle=True) as z:
        cloud = np.asarray(z[C2_CLOUD_2D], dtype=np.float32)
        shape = tuple(int(v) for v in np.asarray(z[C2_GRID_SHAPE], dtype=np.int32).tolist())
        time_str = str(z[C2_TIME_STR])
        wind_records = _records(z[C2_WIND_RECORDS])
        context_wind_records = _records(z[C2_CONTEXT_WIND_RECORDS]) if C2_CONTEXT_WIND_RECORDS in z.files else []
        loc_records = _records(z[C2_LOC_RECORDS])
        motion_records = _records(z[C2_MOTION_RECORDS])
        meta = json.loads(str(z[C2_MULTIMODAL_META_JSON])) if C2_MULTIMODAL_META_JSON in z.files else {}

    z_dim, _, w_dim = shape
    z_levels = _auto_z_levels(wind_records, context_wind_records, z_dim, auto_top_k) if auto_top_k > 0 else z_levels
    z_levels = [min(max(0, int(v)), z_dim - 1) for v in z_levels]
    z_levels = list(dict.fromkeys(z_levels))
    if not z_levels:
        z_levels = [0]
    x_idx = int(x_slice) if x_slice is not None else w_dim // 2
    x_idx = min(max(0, x_idx), w_dim - 1)

    stats_rows: list[dict[str, Any]] = []
    for z_idx in z_levels:
        stats_rows.extend(
            [
                _stats_for(wind_records, z_idx, "current_wind"),
                _stats_for(context_wind_records, z_idx, "context_wind"),
                _stats_for(loc_records, z_idx, "traj"),
                _stats_for(motion_records, z_idx, "motion"),
            ]
        )
    stats_fields = [
        "z",
        "alt_m",
        "record_type",
        "source",
        "color",
        "marker",
        "count",
        "wind_speed_min",
        "wind_speed_mean",
        "wind_speed_max",
        "time_conf_min",
        "time_conf_mean",
        "time_conf_max",
        "space_conf_min",
        "space_conf_mean",
        "space_conf_max",
        "joint_likelihood_min",
        "joint_likelihood_mean",
        "joint_likelihood_max",
        "density_min",
        "density_mean",
        "density_max",
        "obs_count_min",
        "obs_count_mean",
        "obs_count_max",
        "motion_count_min",
        "motion_count_mean",
        "motion_count_max",
        "quality_conf_diagnostic_min",
        "quality_conf_diagnostic_mean",
        "quality_conf_diagnostic_max",
        "density_conf_diagnostic_min",
        "density_conf_diagnostic_mean",
        "density_conf_diagnostic_max",
        "qc_candidate_count",
    ]
    point_rows = []
    point_rows.extend(_point_rows("current_wind", wind_records))
    point_rows.extend(_point_rows("context_wind", context_wind_records))
    point_rows.extend(_point_rows("traj", loc_records))
    point_rows.extend(_point_rows("motion", motion_records))
    point_fields = [
        "record_type",
        "z",
        "alt_m",
        "y",
        "x",
        "u",
        "v",
        "u_motion",
        "v_motion",
        "wind_speed",
        "time_conf",
        "space_conf",
        "joint_likelihood",
        "obs_count",
        "density",
        "motion_count",
        "quality_conf_diagnostic",
        "density_conf_diagnostic",
        "qc_flags",
    ]

    cols = max(2, len(z_levels))
    fig, axes = plt.subplots(2, cols, figsize=(6.2 * cols, 9.2), constrained_layout=True)
    for idx, z_idx in enumerate(z_levels):
        _render_horizontal(axes[0, idx], cloud, wind_records, context_wind_records, loc_records, motion_records, z_idx)
    for idx in range(len(z_levels), cols):
        axes[0, idx].axis("off")

    _render_vertical_yz(axes[1, 0], wind_records, context_wind_records, loc_records, x_idx, x_band, z_dim)
    _render_altitude_profile(axes[1, 1], wind_records, context_wind_records, loc_records, motion_records, z_dim)
    for idx in range(2, cols):
        axes[1, idx].axis("off")

    current_window = meta.get("current_window_minutes", "?")
    context_window = meta.get("context_window_minutes", "?")
    halflife = meta.get("time_conf_halflife_minutes", "?")
    ref_lat = meta.get("reference_center_lat", meta.get("roi_center_lat", "?"))
    ref_lon = meta.get("reference_center_lon", meta.get("roi_center_lon", "?"))
    ref_source = meta.get("reference_center_source", meta.get("roi_center_source", "?"))
    fig.suptitle(
        f"Centralized v1 Stage2 regenerated observations - {time_str}\n"
        f"Current +/-{current_window} min vs context +/-{context_window} min; time_conf=0.5^(|dt|/{halflife}); "
        f"Reference center=({ref_lat}, {ref_lon}) from {ref_source}; Stage2 space_conf=1.0, target-voxel localization deferred to Stage4\n"
        f"All-in observations; no Stage2 spatial crop/filter; Ground Center is logical, no comm-distance filter\n"
        f"Domain lat {LAT_MIN:.1f}-{LAT_MAX:.1f}, lon {LON_MIN:.1f}-{LON_MAX:.1f}, altitude step {DELTA_ALT:.0f} m",
        fontsize=12,
    )
    out = out_dir / f"{time_str}_centralized_stage2_slices.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    png_size = Image.open(out).size
    _write_csv(out_dir / f"stage2_slice_stats_{time_str}.csv", stats_rows, stats_fields)
    _write_csv(out_dir / f"stage2_slice_points_{time_str}.csv", point_rows, point_fields)
    _write_encoding_charts(out_dir, time_str, stats_rows, wind_records, context_wind_records, loc_records, motion_records, z_dim)
    _write_explanation(
        out_dir / f"stage2_slice_explanation_{time_str}.md",
        time_str,
        cloud,
        shape,
        z_levels,
        x_idx,
        int(x_band),
        meta,
        stats_rows,
        wind_records,
        context_wind_records,
        loc_records,
        motion_records,
    )
    audit = meta.get("data_integrity_audit", {})
    if audit:
        _write_integrity_csv(out_dir / f"stage2_data_integrity_{time_str}.csv", audit)
        _write_integrity_md(out_dir / f"stage2_data_integrity_{time_str}.md", time_str, audit, png_size, z_levels)
    return out


def _load_summary(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _time_from_npz_path(path: Path) -> str:
    name = path.name
    if name.startswith("frame_"):
        parts = name.split("_")
        if len(parts) > 1:
            return parts[1]
    return path.stem


def _render_batch_subprocess(args: argparse.Namespace, frame_npz_paths: list[Path]) -> list[str]:
    workers = max(1, int(args.num_workers))
    outputs: list[str] = []
    pending = list(frame_npz_paths)
    running: list[tuple[subprocess.Popen[str], Path, Path]] = []
    log_dir = args.out_dir / "shards"
    log_dir.mkdir(parents=True, exist_ok=True)
    env_base = os.environ.copy()
    env_base.setdefault("OMP_NUM_THREADS", "1")
    env_base.setdefault("OPENBLAS_NUM_THREADS", "1")
    while pending or running:
        while pending and len(running) < workers:
            frame_npz = pending.pop(0)
            time_str = _time_from_npz_path(frame_npz)
            log_file = log_dir / f"stage2_visual_{time_str}.log"
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--frame-npz",
                str(frame_npz),
                "--out-dir",
                str(args.out_dir),
                "--z-levels",
                str(args.z_levels),
                "--auto-top-k-z",
                str(args.auto_top_k_z),
                "--x-band",
                str(args.x_band),
            ]
            if args.x_slice is not None:
                cmd.extend(["--x-slice", str(args.x_slice)])
            with log_file.open("w", encoding="utf-8") as log:
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
            running.append((proc, frame_npz, log_file))
        still_running: list[tuple[subprocess.Popen[str], Path, Path]] = []
        for proc, frame_npz, log_file in running:
            rc = proc.poll()
            if rc is None:
                still_running.append((proc, frame_npz, log_file))
                continue
            if rc != 0:
                raise RuntimeError(f"Stage2 visual render failed rc={rc}; see {log_file}")
            time_str = _time_from_npz_path(frame_npz)
            outputs.append(str(args.out_dir / f"{time_str}_centralized_stage2_slices.png"))
        running = still_running
        if running:
            import time

            time.sleep(0.5)
    return sorted(outputs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Slice visualization for regenerated centralized_v1 Stage2 outputs.")
    parser.add_argument("--frame-npz", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--z-levels", default="3,8,12")
    parser.add_argument("--auto-top-k-z", type=int, default=4)
    parser.add_argument("--x-slice", type=int)
    parser.add_argument("--x-band", type=int, default=6)
    parser.add_argument("--num-workers", type=int, default=1)
    args = parser.parse_args()

    z_levels = [int(token.strip()) for token in str(args.z_levels).split(",") if token.strip()]
    if args.frame_npz is None and args.summary is None:
        raise ValueError("Provide either --frame-npz or --summary")

    outputs = []
    integrity_summaries = []
    if args.frame_npz is not None:
        outputs.append(render_one(args.frame_npz, args.out_dir, z_levels, int(args.auto_top_k_z), args.x_slice, int(args.x_band)))
        with np.load(args.frame_npz, allow_pickle=True) as z:
            meta = json.loads(str(z[C2_MULTIMODAL_META_JSON])) if C2_MULTIMODAL_META_JSON in z.files else {}
            time_str = str(z[C2_TIME_STR])
        if meta.get("data_integrity_audit"):
            integrity_summaries.append({"time_str": time_str, "audit": meta["data_integrity_audit"]})
    else:
        wanted = {token.strip() for token in args.frame_times.split(",") if token.strip()}
        rows = _load_summary(args.summary)
        selected_rows = [row for row in rows if not wanted or str(row.get("time_str")) in wanted]
        frame_npz_paths = [Path(row["multimodal_vox_path"]) for row in selected_rows]
        if int(args.num_workers) > 1 and len(frame_npz_paths) > 1:
            outputs.extend(_render_batch_subprocess(args, frame_npz_paths))
        else:
            for frame_npz in frame_npz_paths:
                outputs.append(render_one(frame_npz, args.out_dir, z_levels, int(args.auto_top_k_z), args.x_slice, int(args.x_band)))
        for row in selected_rows:
            if row.get("data_integrity_audit"):
                integrity_summaries.append({"time_str": str(row["time_str"]), "audit": row["data_integrity_audit"]})
    if integrity_summaries:
        _append_integrity_summary(args.out_dir / "stage2_data_integrity_summary.md", integrity_summaries)

    for out in outputs:
        print(out)


if __name__ == "__main__":
    main()
