"""CMA-RA virtual radial-velocity and 3DVAR-style proxy utilities.

This script is intentionally separate from the existing Stage4 strict
hold-out scripts.  It reads CMA-RA/CRA40 GRIB2 files, collocates u/v/w/GPH
fields to the centralized_v1 Stage2 grid, projects the wind vector to virtual
radial velocities for one or more synthetic radar locations, and runs a light
3DVAR-style proxy that blends four constraint families:

1. CMA background u/v/w;
2. virtual radial velocity projected from CMA-RA;
3. sparse Stage4 reconstructed wind prior, when a Stage4 NPZ is supplied;
4. sparse aircraft wind_records observation anchors.

The output is a weak-background / virtual-observation product.  It is not a
standard PyDDA radar retrieval because the current project still has no real
Doppler radial-velocity volume.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import (  # noqa: E402
    ALT_MAX,
    ALT_MIN,
    DELTA_ALT,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
)
from stage.centralized_v1.configs.centralized_v1_contract import (  # noqa: E402
    C2_GRID_SHAPE,
    C2_WIND_RECORDS,
    C4_RECON_CONF,
    C4_RECON_U,
    C4_RECON_V,
)
from stage.centralized_v1.core.centralized_stage4_ground_recon import (  # noqa: E402
    _load_json,
    _load_stage2_npz,
    _records,
    _safe_float,
    _safe_int,
)


CMA_VAR_CODES = {
    "GPH": "geopotential_height_gpm",
    "RHU": "relative_humidity_percent",
    "TEM": "temperature_k",
    "VVP": "vertical_velocity_pa_s",
    "WIU": "u_wind_mps",
    "WIV": "v_wind_mps",
}
REQUIRED_WIND_CODES = ("WIU", "WIV")
OPTIONAL_CODES = ("GPH", "RHU", "TEM", "VVP")
FILENAME_RE = re.compile(r"CRA40_([A-Z0-9]+)_(\d{10})_")
EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class CmaFile:
    var_code: str
    time_str: str
    path: Path


@dataclass(frozen=True)
class RadarSite:
    site_id: str
    lat: float
    lon: float
    alt_m: float


def _parse_cma_filename(path: Path) -> CmaFile | None:
    match = FILENAME_RE.search(path.name)
    if not match:
        return None
    var_code, time_str = match.groups()
    if var_code not in CMA_VAR_CODES:
        return None
    return CmaFile(var_code=var_code, time_str=time_str, path=path)


def _index_cma_files(cma_dir: Path) -> dict[str, dict[str, Path]]:
    index: dict[str, dict[str, Path]] = {}
    for path in cma_dir.iterdir():
        if not path.is_file():
            continue
        parsed = _parse_cma_filename(path)
        if parsed is None:
            continue
        index.setdefault(parsed.time_str, {})[parsed.var_code] = parsed.path
    return index


def _parse_stage_time(time_str: str) -> datetime:
    text = str(time_str)
    if len(text) == 14:
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if len(text) == 10:
        return datetime.strptime(text, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    raise ValueError(f"Unsupported time format: {time_str}")


def _nearest_cma_time(stage_time_str: str, available_times: list[str], max_hours: float) -> tuple[str, float]:
    target = _parse_stage_time(stage_time_str)
    best_time = ""
    best_abs_hours = float("inf")
    for cma_time in available_times:
        dt_hours = abs((_parse_stage_time(cma_time) - target).total_seconds()) / 3600.0
        if dt_hours < best_abs_hours:
            best_time = cma_time
            best_abs_hours = dt_hours
    if not best_time or best_abs_hours > float(max_hours):
        raise ValueError(f"No CMA time within {max_hours}h for Stage2 frame {stage_time_str}")
    signed_hours = (_parse_stage_time(best_time) - target).total_seconds() / 3600.0
    return best_time, float(signed_hours)


def _stage4_record_sort_key(row: dict[str, Any]) -> tuple[int, int, int, float, float]:
    return (
        _safe_int(row.get("z")),
        _safe_int(row.get("y")),
        _safe_int(row.get("x")),
        _safe_float(row.get("u")),
        _safe_float(row.get("v")),
    )


def _split_stage4_holdout_like(
    records: list[dict[str, Any]],
    holdout_fraction: float,
    holdout_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mirror Stage4 deterministic train/hold-out split for CMA proxy anchors."""

    if not records:
        return [], []
    sorted_records = sorted(records, key=_stage4_record_sort_key)
    n_records = len(sorted_records)
    if holdout_count > 0:
        n_holdout = min(n_records, int(holdout_count))
    else:
        n_holdout = max(1, int(math.ceil(n_records * max(0.0, float(holdout_fraction)))))
        n_holdout = min(n_records, n_holdout)
    if n_holdout >= n_records:
        selected = set(range(n_records))
    else:
        selected = {int(round(v)) for v in np.linspace(0, n_records - 1, n_holdout)}
        cursor = 0
        while len(selected) < n_holdout and cursor < n_records:
            selected.add(cursor)
            cursor += 1
    holdout = [row for i, row in enumerate(sorted_records) if i in selected]
    train = [row for i, row in enumerate(sorted_records) if i not in selected]
    return train, holdout


def _available_wind_times(cma_index: dict[str, dict[str, Path]]) -> list[str]:
    return sorted(time_str for time_str, files in cma_index.items() if all(code in files for code in REQUIRED_WIND_CODES))


def _bracket_cma_times(
    stage_time_str: str,
    available_times: list[str],
    max_window_hours: float,
) -> tuple[str, str, float, float, float]:
    """Return bracketing CMA times and interpolation fraction for a target time."""

    target = _parse_stage_time(stage_time_str)
    parsed = [(time_str, _parse_stage_time(time_str)) for time_str in available_times]
    previous = [(time_str, dt) for time_str, dt in parsed if dt <= target]
    following = [(time_str, dt) for time_str, dt in parsed if dt >= target]
    if not previous or not following:
        raise ValueError(f"No bracketing CMA times for Stage2 frame {stage_time_str}")
    t0_str, t0_dt = max(previous, key=lambda item: item[1])
    t1_str, t1_dt = min(following, key=lambda item: item[1])
    window_hours = (t1_dt - t0_dt).total_seconds() / 3600.0
    if window_hours < 0:
        raise ValueError(f"Invalid CMA time bracket: {t0_str} -> {t1_str}")
    if window_hours > float(max_window_hours):
        raise ValueError(
            f"CMA time bracket is {window_hours:.3f}h, larger than max_window_hours={max_window_hours}"
        )
    if window_hours == 0:
        alpha = 0.0
    else:
        alpha = (target - t0_dt).total_seconds() / max(1.0, (t1_dt - t0_dt).total_seconds())
    delta0_hours = (target - t0_dt).total_seconds() / 3600.0
    delta1_hours = (t1_dt - target).total_seconds() / 3600.0
    return t0_str, t1_str, float(np.clip(alpha, 0.0, 1.0)), float(delta0_hours), float(delta1_hours)


def _read_grib_stack_eccodes(path: Path) -> dict[str, Any]:
    import eccodes

    levels: list[int] = []
    values: list[np.ndarray] = []
    lats_1d: np.ndarray | None = None
    lons_1d: np.ndarray | None = None
    short_name = ""
    type_of_level = ""
    data_date = None
    data_time = None
    with path.open("rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                ni = int(eccodes.codes_get(gid, "Ni"))
                nj = int(eccodes.codes_get(gid, "Nj"))
                level = int(eccodes.codes_get(gid, "level"))
                short_name = str(eccodes.codes_get(gid, "shortName"))
                type_of_level = str(eccodes.codes_get(gid, "typeOfLevel"))
                data_date = eccodes.codes_get(gid, "dataDate")
                data_time = eccodes.codes_get(gid, "dataTime")
                arr = np.asarray(eccodes.codes_get_values(gid), dtype=np.float32).reshape(nj, ni)
                if lats_1d is None or lons_1d is None:
                    lat_values = np.asarray(eccodes.codes_get_array(gid, "latitudes"), dtype=np.float64).reshape(nj, ni)
                    lon_values = np.asarray(eccodes.codes_get_array(gid, "longitudes"), dtype=np.float64).reshape(nj, ni)
                    lats_1d = lat_values[:, 0]
                    lons_1d = lon_values[0, :]
                levels.append(level)
                values.append(arr)
            finally:
                eccodes.codes_release(gid)
    if not values or lats_1d is None or lons_1d is None:
        raise ValueError(f"No GRIB messages read from {path}")
    order = np.argsort(np.asarray(levels, dtype=np.int32))
    return {
        "path": str(path),
        "short_name": short_name,
        "type_of_level": type_of_level,
        "data_date": str(data_date),
        "data_time": str(data_time),
        "levels_hpa": np.asarray(levels, dtype=np.float32)[order],
        "values": np.stack(values, axis=0).astype(np.float32)[order],
        "latitudes": lats_1d.astype(np.float64),
        "longitudes": lons_1d.astype(np.float64),
    }


def _read_grib_stack(path: Path) -> dict[str, Any]:
    """Read a pressure-level GRIB2 file.

    Prefer cfgrib/xarray when the local environment is healthy, but keep an
    eccodes fallback because the project workstation can have mixed numpy and
    xarray builds.
    """

    try:
        import xarray as xr

        ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
        data_var = next(iter(ds.data_vars))
        values = np.asarray(ds[data_var].values, dtype=np.float32)
        if values.ndim == 2:
            values = values[None, :, :]
            levels = np.asarray([_safe_float(ds[data_var].attrs.get("GRIB_level"), 0.0)], dtype=np.float32)
        else:
            level_name = "isobaricInhPa" if "isobaricInhPa" in ds.coords else "level"
            levels = np.asarray(ds[level_name].values, dtype=np.float32)
        return {
            "path": str(path),
            "short_name": str(ds[data_var].attrs.get("GRIB_shortName", data_var)),
            "type_of_level": str(ds[data_var].attrs.get("GRIB_typeOfLevel", "")),
            "data_date": str(ds[data_var].attrs.get("GRIB_dataDate", "")),
            "data_time": str(ds[data_var].attrs.get("GRIB_dataTime", "")),
            "levels_hpa": levels,
            "values": values,
            "latitudes": np.asarray(ds["latitude"].values, dtype=np.float64),
            "longitudes": np.asarray(ds["longitude"].values, dtype=np.float64),
        }
    except Exception:
        return _read_grib_stack_eccodes(path)


def _pressure_hpa_to_alt_m(pressure_hpa: np.ndarray) -> np.ndarray:
    pressure = np.maximum(np.asarray(pressure_hpa, dtype=np.float64), 1e-6)
    return 44330.0 * (1.0 - (pressure / 1013.25) ** 0.1903)


def _stage2_lat_lon_alt(shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    z_dim, h_dim, w_dim = shape
    lat = LAT_MAX - (np.arange(h_dim, dtype=np.float64) + 0.5) / float(h_dim) * (LAT_MAX - LAT_MIN)
    lon = LON_MIN + (np.arange(w_dim, dtype=np.float64) + 0.5) / float(w_dim) * (LON_MAX - LON_MIN)
    alt = ALT_MIN + np.arange(z_dim, dtype=np.float64) * DELTA_ALT
    return lat, lon, alt


def _nearest_indices(desc_lats: np.ndarray, asc_lons: np.ndarray, target_lats: np.ndarray, target_lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat_axis_asc = desc_lats[::-1]
    lat_pos = np.searchsorted(lat_axis_asc, target_lats)
    lat_pos = np.clip(lat_pos, 0, len(lat_axis_asc) - 1)
    lat_prev = np.clip(lat_pos - 1, 0, len(lat_axis_asc) - 1)
    lat_use = np.where(np.abs(lat_axis_asc[lat_prev] - target_lats) <= np.abs(lat_axis_asc[lat_pos] - target_lats), lat_prev, lat_pos)
    lat_idx = (len(desc_lats) - 1 - lat_use).astype(np.int32)

    lon_pos = np.searchsorted(asc_lons, target_lons)
    lon_pos = np.clip(lon_pos, 0, len(asc_lons) - 1)
    lon_prev = np.clip(lon_pos - 1, 0, len(asc_lons) - 1)
    lon_idx = np.where(np.abs(asc_lons[lon_prev] - target_lons) <= np.abs(asc_lons[lon_pos] - target_lons), lon_prev, lon_pos).astype(np.int32)
    return lat_idx, lon_idx


def _vertical_interp_to_stage_alt(values: np.ndarray, levels_hpa: np.ndarray, target_alt_m: np.ndarray) -> np.ndarray:
    level_alt_m = _pressure_hpa_to_alt_m(levels_hpa)
    order = np.argsort(level_alt_m)
    alt_sorted = level_alt_m[order]
    vals_sorted = values[order].astype(np.float32)
    out = np.empty((len(target_alt_m),) + values.shape[1:], dtype=np.float32)
    for zi, target_alt in enumerate(target_alt_m):
        upper = int(np.searchsorted(alt_sorted, float(target_alt), side="left"))
        if upper <= 0:
            out[zi] = vals_sorted[0]
            continue
        if upper >= len(alt_sorted):
            out[zi] = vals_sorted[-1]
            continue
        lower = upper - 1
        denom = max(1e-6, float(alt_sorted[upper] - alt_sorted[lower]))
        frac = np.float32((float(target_alt) - float(alt_sorted[lower])) / denom)
        out[zi] = vals_sorted[lower] * (1.0 - frac) + vals_sorted[upper] * frac
    return out.astype(np.float32)


def _collocate_field_to_stage_grid(stack: dict[str, Any], shape: tuple[int, int, int]) -> np.ndarray:
    stage_lats, stage_lons, stage_alts = _stage2_lat_lon_alt(shape)
    lat_idx, lon_idx = _nearest_indices(np.asarray(stack["latitudes"]), np.asarray(stack["longitudes"]), stage_lats, stage_lons)
    horizontal = np.asarray(stack["values"], dtype=np.float32)[:, lat_idx[:, None], lon_idx[None, :]]
    return _vertical_interp_to_stage_alt(horizontal, np.asarray(stack["levels_hpa"], dtype=np.float32), stage_alts)


def _omega_to_w_mps(omega_pa_s: np.ndarray, temperature_k: np.ndarray, pressure_hpa_by_z: np.ndarray) -> np.ndarray:
    # Hydrostatic conversion: omega = dp/dt ~= -rho*g*w; rho=p/(R_d*T).
    p_pa = np.maximum(pressure_hpa_by_z.astype(np.float32), 1.0)[:, None, None] * 100.0
    density = p_pa / (287.05 * np.maximum(temperature_k.astype(np.float32), 150.0))
    return (-omega_pa_s.astype(np.float32) / np.maximum(density * 9.80665, 1e-6)).astype(np.float32)


def _load_cma_collocated(cma_files: dict[str, Path], shape: tuple[int, int, int]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    missing = [code for code in REQUIRED_WIND_CODES if code not in cma_files]
    if missing:
        raise FileNotFoundError(f"Missing required CMA wind variables: {missing}")
    fields: dict[str, np.ndarray] = {}
    meta: dict[str, Any] = {"source_files": {}, "levels_hpa_by_var": {}}
    stacks: dict[str, dict[str, Any]] = {}
    for code in REQUIRED_WIND_CODES + OPTIONAL_CODES:
        path = cma_files.get(code)
        if path is None:
            continue
        stack = _read_grib_stack(path)
        stacks[code] = stack
        fields[CMA_VAR_CODES[code]] = _collocate_field_to_stage_grid(stack, shape)
        meta["source_files"][code] = str(path)
        meta["levels_hpa_by_var"][code] = [float(x) for x in np.asarray(stack["levels_hpa"]).tolist()]
        meta[f"{code}_short_name"] = stack.get("short_name", "")

    if "vertical_velocity_pa_s" in fields:
        levels = np.asarray(stacks["VVP"]["levels_hpa"], dtype=np.float32)
        stage_alts = _stage2_lat_lon_alt(shape)[2]
        level_alts = _pressure_hpa_to_alt_m(levels)
        pressure_by_z = np.interp(stage_alts, level_alts[np.argsort(level_alts)], levels[np.argsort(level_alts)], left=levels[0], right=levels[-1])
        temp = fields.get("temperature_k", np.full(shape, 273.15, dtype=np.float32))
        fields["w_wind_mps_from_omega"] = _omega_to_w_mps(fields["vertical_velocity_pa_s"], temp, pressure_by_z.astype(np.float32))
    else:
        fields["w_wind_mps_from_omega"] = np.zeros(shape, dtype=np.float32)
    return fields, meta


def _load_cma_collocated_time_interpolated(
    cma_index: dict[str, dict[str, Path]],
    stage_time_str: str,
    shape: tuple[int, int, int],
    *,
    method: str,
    max_time_delta_hours: float,
    max_window_hours: float,
) -> tuple[dict[str, np.ndarray], dict[str, Any], str, float]:
    """Load CMA fields by nearest time or linear interpolation between bracketing analyses."""

    method = str(method)
    linear_qc = method == "linear_qc"
    if method == "nearest":
        available = _available_wind_times(cma_index)
        cma_time, delta_hours = _nearest_cma_time(stage_time_str, available, float(max_time_delta_hours))
        fields, meta = _load_cma_collocated(cma_index[cma_time], shape)
        fields["cma_temporal_change_speed_mps"] = np.zeros(shape, dtype=np.float32)
        fields["cma_temporal_confidence"] = np.ones(shape, dtype=np.float32)
        meta.update(
            {
                "time_match_method": "nearest",
                "matched_cma_time": cma_time,
                "matched_delta_hours": float(delta_hours),
                "interpolation_alpha": 0.0,
            }
        )
        return fields, meta, cma_time, float(delta_hours)
    if method not in {"linear", "linear_qc"}:
        raise ValueError("Unsupported CMA time interpolation method. Choose nearest, linear or linear_qc.")

    available = _available_wind_times(cma_index)
    t0, t1, alpha, delta0_hours, delta1_hours = _bracket_cma_times(
        stage_time_str,
        available,
        max_window_hours=max_window_hours,
    )
    fields0, meta0 = _load_cma_collocated(cma_index[t0], shape)
    if t0 == t1:
        fields0["cma_temporal_change_speed_mps"] = np.zeros(shape, dtype=np.float32)
        fields0["cma_temporal_confidence"] = np.ones(shape, dtype=np.float32)
        meta0.update(
            {
                "time_match_method": method,
                "cma_time_t0": t0,
                "cma_time_t1": t1,
                "interpolation_alpha": 0.0,
                "delta_hours_from_t0": 0.0,
                "delta_hours_to_t1": 0.0,
                "linear_interpolation_formula": "F(t) = (1-alpha)*F(T0) + alpha*F(T1)",
            }
        )
        return fields0, meta0, t0, 0.0

    fields1, meta1 = _load_cma_collocated(cma_index[t1], shape)
    interp_fields: dict[str, np.ndarray] = {}
    for key, value0 in fields0.items():
        if key not in fields1:
            continue
        value1 = fields1[key]
        interp_fields[key] = ((1.0 - alpha) * value0.astype(np.float32) + alpha * value1.astype(np.float32)).astype(np.float32)
    du = fields1["u_wind_mps"].astype(np.float32) - fields0["u_wind_mps"].astype(np.float32)
    dv = fields1["v_wind_mps"].astype(np.float32) - fields0["v_wind_mps"].astype(np.float32)
    dw = fields1["w_wind_mps_from_omega"].astype(np.float32) - fields0["w_wind_mps_from_omega"].astype(np.float32)
    change_speed = np.sqrt(du * du + dv * dv + dw * dw).astype(np.float32)
    # Smooth-evolution confidence: linear interpolation is trusted most where the
    # bracketing 6h analyses are mutually close, and downweighted in fast-changing
    # areas that should later receive convection/QC flags.
    temporal_conf = np.exp(-change_speed / np.float32(24.0)).astype(np.float32)
    rapid_change_threshold = np.float32(18.0)
    rapid_change_flag = (change_speed >= rapid_change_threshold).astype(np.float32)
    interp_fields["cma_temporal_change_speed_mps"] = change_speed
    interp_fields["cma_temporal_confidence"] = temporal_conf
    interp_fields["cma_rapid_change_flag"] = rapid_change_flag if linear_qc else np.zeros_like(change_speed, dtype=np.float32)
    meta = {
        "time_match_method": method,
        "cma_time_t0": t0,
        "cma_time_t1": t1,
        "interpolation_alpha": float(alpha),
        "delta_hours_from_t0": float(delta0_hours),
        "delta_hours_to_t1": float(delta1_hours),
        "linear_interpolation_formula": "F(t) = (1-alpha)*F(T0) + alpha*F(T1)",
        "temporal_change_speed_note": "sqrt((u_T1-u_T0)^2 + (v_T1-v_T0)^2 + (w_T1-w_T0)^2)",
        "temporal_confidence_formula": "exp(-temporal_change_speed_mps / 24)",
        "rapid_change_threshold_mps": float(rapid_change_threshold),
        "rapid_change_flag_note": "linear_qc marks voxels whose 6h bracketing CMA vector change exceeds the threshold; linear keeps the flag array at zero for compatibility.",
        "source_files_t0": meta0.get("source_files", {}),
        "source_files_t1": meta1.get("source_files", {}),
        "levels_hpa_by_var_t0": meta0.get("levels_hpa_by_var", {}),
        "levels_hpa_by_var_t1": meta1.get("levels_hpa_by_var", {}),
    }
    return interp_fields, meta, f"{t0}->{t1}", float(delta0_hours)


def _parse_radar_sites(text: str) -> list[RadarSite]:
    sites: list[RadarSite] = []
    for token in str(text).split(";"):
        item = token.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Radar site must be id,lat,lon,alt_m: {item}")
        sites.append(RadarSite(parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
    if not sites:
        raise ValueError("At least one radar site is required.")
    return sites


def _radial_velocity(u: np.ndarray, v: np.ndarray, w: np.ndarray, site: RadarSite, shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    stage_lats, stage_lons, stage_alts = _stage2_lat_lon_alt(shape)
    lat_grid = stage_lats[None, :, None]
    lon_grid = stage_lons[None, None, :]
    alt_grid = stage_alts[:, None, None]
    mean_lat = np.deg2rad((lat_grid + site.lat) / 2.0)
    east_m = np.deg2rad(lon_grid - site.lon) * EARTH_RADIUS_M * np.cos(mean_lat)
    north_m = np.deg2rad(lat_grid - site.lat) * EARTH_RADIUS_M
    up_m = alt_grid - float(site.alt_m)
    distance = np.sqrt(east_m * east_m + north_m * north_m + up_m * up_m)
    distance = np.maximum(distance, 1.0)
    vr = (u * east_m + v * north_m + w * up_m) / distance
    return vr.astype(np.float32), distance.astype(np.float32)


def _los_geometry_weight(east_hat: np.ndarray, north_hat: np.ndarray, distance: np.ndarray) -> np.ndarray:
    horizontal_observability = np.sqrt(east_hat.astype(np.float32) ** 2 + north_hat.astype(np.float32) ** 2)
    distance_scale = np.float32(1_000_000.0)
    distance_weight = np.clip(distance_scale / np.maximum(distance.astype(np.float32), distance_scale), 0.15, 1.0)
    return np.clip(horizontal_observability * distance_weight, 0.05, 1.0).astype(np.float32)


def _site_pair_los_difference(
    line_of_sight: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    shape: tuple[int, int, int],
) -> np.ndarray:
    site_ids = sorted(line_of_sight)
    if len(site_ids) < 2:
        return np.zeros(shape, dtype=np.float32)
    diffs: list[np.ndarray] = []
    for i, left in enumerate(site_ids):
        e0, n0, u0 = line_of_sight[left]
        for right in site_ids[i + 1 :]:
            e1, n1, u1 = line_of_sight[right]
            dot = np.clip(e0 * e1 + n0 * n1 + u0 * u1, -1.0, 1.0)
            diffs.append((1.0 - dot).astype(np.float32))
    return np.mean(np.stack(diffs, axis=0), axis=0).astype(np.float32)


def _line_of_sight_units(site: RadarSite, shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    stage_lats, stage_lons, stage_alts = _stage2_lat_lon_alt(shape)
    lat_grid = stage_lats[None, :, None]
    lon_grid = stage_lons[None, None, :]
    alt_grid = stage_alts[:, None, None]
    mean_lat = np.deg2rad((lat_grid + site.lat) / 2.0)
    east_m = np.deg2rad(lon_grid - site.lon) * EARTH_RADIUS_M * np.cos(mean_lat)
    north_m = np.deg2rad(lat_grid - site.lat) * EARTH_RADIUS_M
    up_m = alt_grid - float(site.alt_m)
    distance = np.maximum(np.sqrt(east_m * east_m + north_m * north_m + up_m * up_m), 1.0)
    return (
        (east_m / distance).astype(np.float32),
        (north_m / distance).astype(np.float32),
        (up_m / distance).astype(np.float32),
        distance.astype(np.float32),
    )


def _localized_aircraft_background(shape: tuple[int, int, int], wind_records: list[dict[str, Any]], radius_xy: int, radius_z: int, sigma_xy: float, sigma_z: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    acc_u = np.zeros(shape, dtype=np.float32)
    acc_v = np.zeros(shape, dtype=np.float32)
    acc_w = np.zeros(shape, dtype=np.float32)
    radius_xy = max(0, int(radius_xy))
    radius_z = max(0, int(radius_z))
    sigma_xy = max(1e-6, float(sigma_xy))
    sigma_z = max(1e-6, float(sigma_z))
    z_dim, h_dim, w_dim = shape
    for row in wind_records:
        z = _safe_int(row.get("z"))
        y = _safe_int(row.get("y"))
        x = _safe_int(row.get("x"))
        if not (0 <= z < z_dim and 0 <= y < h_dim and 0 <= x < w_dim):
            continue
        z0, z1 = max(0, z - radius_z), min(z_dim, z + radius_z + 1)
        y0, y1 = max(0, y - radius_xy), min(h_dim, y + radius_xy + 1)
        x0, x1 = max(0, x - radius_xy), min(w_dim, x + radius_xy + 1)
        dz = (np.arange(z0, z1, dtype=np.float32) - float(z))[:, None, None]
        dy = (np.arange(y0, y1, dtype=np.float32) - float(y))[None, :, None]
        dx = (np.arange(x0, x1, dtype=np.float32) - float(x))[None, None, :]
        loc = np.exp(-0.5 * ((dx / sigma_xy) ** 2 + (dy / sigma_xy) ** 2 + (dz / sigma_z) ** 2)).astype(np.float32)
        weight = loc * np.float32(max(0.0, _safe_float(row.get("obs_conf"), 1.0)))
        acc_u[z0:z1, y0:y1, x0:x1] += np.float32(_safe_float(row.get("u"))) * weight
        acc_v[z0:z1, y0:y1, x0:x1] += np.float32(_safe_float(row.get("v"))) * weight
        acc_w[z0:z1, y0:y1, x0:x1] += weight
    obs_u = np.divide(acc_u, np.maximum(acc_w, 1e-6), out=np.zeros_like(acc_u), where=acc_w > 0)
    obs_v = np.divide(acc_v, np.maximum(acc_w, 1e-6), out=np.zeros_like(acc_v), where=acc_w > 0)
    conf = np.clip(acc_w / max(1e-6, np.percentile(acc_w[acc_w > 0], 90) if np.any(acc_w > 0) else 1.0), 0.0, 1.0)
    return obs_u.astype(np.float32), obs_v.astype(np.float32), conf.astype(np.float32)


def _neighbor_mean_3d(field: np.ndarray) -> np.ndarray:
    pad = np.pad(field, ((1, 1), (1, 1), (1, 1)), mode="edge")
    return (
        pad[1:-1, 1:-1, :-2]
        + pad[1:-1, 1:-1, 2:]
        + pad[1:-1, :-2, 1:-1]
        + pad[1:-1, 2:, 1:-1]
        + pad[:-2, 1:-1, 1:-1]
        + pad[2:, 1:-1, 1:-1]
    ) / 6.0


def _laplacian_axis0(field: np.ndarray) -> np.ndarray:
    pad = np.pad(field, ((1, 1), (0, 0), (0, 0)), mode="edge")
    return (pad[:-2] - 2.0 * pad[1:-1] + pad[2:]).astype(np.float32)


def _boundary_mask(shape: tuple[int, int, int], width: int = 1) -> np.ndarray:
    width = max(1, int(width))
    mask = np.zeros(shape, dtype=np.float32)
    mask[:width, :, :] = 1.0
    mask[-width:, :, :] = 1.0
    mask[:, :width, :] = 1.0
    mask[:, -width:, :] = 1.0
    mask[:, :, :width] = 1.0
    mask[:, :, -width:] = 1.0
    return mask


def _find_stage4_recon_npz(stage4_recon_dir: Path | None, frame_time: str) -> Path | None:
    if stage4_recon_dir is None:
        return None
    candidates = [
        stage4_recon_dir / f"frame_{frame_time}_center_strict.npz",
        stage4_recon_dir / f"frame_{frame_time}_center.npz",
        stage4_recon_dir / f"{frame_time}.npz",
    ]
    for path in candidates:
        if path.exists():
            return path
    matches = sorted(stage4_recon_dir.rglob(f"*{frame_time}*.npz"))
    return matches[0] if matches else None


def _load_stage4_prior(path: Path | None, shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    if path is None:
        return (
            np.zeros(shape, dtype=np.float32),
            np.zeros(shape, dtype=np.float32),
            np.zeros(shape, dtype=np.float32),
            "",
        )
    with np.load(path, allow_pickle=True) as z:
        prior_u = np.asarray(z[C4_RECON_U], dtype=np.float32)
        prior_v = np.asarray(z[C4_RECON_V], dtype=np.float32)
        prior_conf = np.asarray(z[C4_RECON_CONF], dtype=np.float32)
    if prior_u.shape != shape or prior_v.shape != shape or prior_conf.shape != shape:
        raise ValueError(f"Stage4 prior shape mismatch: {path} has {prior_u.shape}, expected {shape}")
    return prior_u, prior_v, np.clip(prior_conf, 0.0, 1.0).astype(np.float32), str(path)


def _three_dvar_proxy(
    background_u: np.ndarray,
    background_v: np.ndarray,
    background_w: np.ndarray,
    virtual_radial: dict[str, np.ndarray],
    line_of_sight: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    prior_u: np.ndarray,
    prior_v: np.ndarray,
    prior_conf: np.ndarray,
    obs_u: np.ndarray,
    obs_v: np.ndarray,
    obs_conf: np.ndarray,
    *,
    iterations: int,
    background_weight: float,
    radial_weight: float,
    stage4_prior_weight: float,
    observation_weight: float,
    smoothness_weight: float,
    divergence_weight: float,
    vertical_shear_weight: float,
    boundary_weight: float,
    speed_limit_mps: float,
    geometry_balance_mode: str,
    radial_geometry_weight: dict[str, np.ndarray] | None,
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    u = background_u.astype(np.float32).copy()
    v = background_v.astype(np.float32).copy()
    b_u = background_u.astype(np.float32)
    b_v = background_v.astype(np.float32)
    b_w = background_w.astype(np.float32)
    prior_u = prior_u.astype(np.float32)
    prior_v = prior_v.astype(np.float32)
    prior_conf = np.clip(prior_conf.astype(np.float32), 0.0, 1.0)
    obs_conf = np.clip(obs_conf.astype(np.float32), 0.0, 1.0)
    boundary = _boundary_mask(u.shape, width=1)
    geometry_balance_mode = str(geometry_balance_mode)
    if geometry_balance_mode not in {"off", "los_weighted"}:
        raise ValueError("Unsupported --geometry-balance-mode. Choose off or los_weighted.")
    radial_geometry_weight = radial_geometry_weight or {}
    iterations = max(0, int(iterations))
    speed_limit_mps = max(1e-6, float(speed_limit_mps))
    last_obs = 0.0
    last_bg = 0.0
    last_prior = 0.0
    last_radial = 0.0
    last_smooth = 0.0
    last_div = 0.0
    last_shear = 0.0
    for _ in range(iterations):
        mean_u = _neighbor_mean_3d(u)
        mean_v = _neighbor_mean_3d(v)
        du_dx = np.gradient(u, axis=2)
        dv_dy = np.gradient(v, axis=1)
        div = du_dx + dv_dy
        radial_grad_u = np.zeros_like(u, dtype=np.float32)
        radial_grad_v = np.zeros_like(v, dtype=np.float32)
        radial_loss_parts = []
        for site_id, target_vr in virtual_radial.items():
            east_hat, north_hat, up_hat = line_of_sight[site_id]
            pred_vr = u * east_hat + v * north_hat + b_w * up_hat
            residual = pred_vr - target_vr.astype(np.float32)
            if geometry_balance_mode == "los_weighted":
                geom_w = radial_geometry_weight.get(site_id)
                if geom_w is None:
                    geom_w = np.ones_like(residual, dtype=np.float32)
                residual_for_grad = residual * geom_w.astype(np.float32)
            else:
                residual_for_grad = residual
            radial_grad_u += residual_for_grad * east_hat
            radial_grad_v += residual_for_grad * north_hat
            radial_loss_parts.append(float(np.mean(np.abs(residual_for_grad))))
        candidate_u = (
            u
            + smoothness_weight * (mean_u - u)
            - divergence_weight * np.gradient(div, axis=2)
            + vertical_shear_weight * _laplacian_axis0(u)
            + background_weight * (b_u - u)
            + stage4_prior_weight * prior_conf * (prior_u - u)
            + observation_weight * obs_conf * (obs_u - u)
            - radial_weight * radial_grad_u
            + boundary_weight * boundary * (b_u - u)
        )
        candidate_v = (
            v
            + smoothness_weight * (mean_v - v)
            - divergence_weight * np.gradient(div, axis=1)
            + vertical_shear_weight * _laplacian_axis0(v)
            + background_weight * (b_v - v)
            + stage4_prior_weight * prior_conf * (prior_v - v)
            + observation_weight * obs_conf * (obs_v - v)
            - radial_weight * radial_grad_v
            + boundary_weight * boundary * (b_v - v)
        )
        speed = np.sqrt(candidate_u * candidate_u + candidate_v * candidate_v)
        scale = np.minimum(1.0, speed_limit_mps / np.maximum(speed, 1e-6)).astype(np.float32)
        u = (candidate_u * scale).astype(np.float32)
        v = (candidate_v * scale).astype(np.float32)
        active = obs_conf > 0
        if np.any(active):
            last_obs = float(np.mean(np.sqrt((u[active] - obs_u[active]) ** 2 + (v[active] - obs_v[active]) ** 2)))
        prior_active = prior_conf > 0
        if np.any(prior_active):
            last_prior = float(np.mean(np.sqrt((u[prior_active] - prior_u[prior_active]) ** 2 + (v[prior_active] - prior_v[prior_active]) ** 2)))
        last_radial = float(np.mean(radial_loss_parts)) if radial_loss_parts else 0.0
        last_bg = float(np.mean(np.sqrt((u - b_u) ** 2 + (v - b_v) ** 2)))
        last_smooth = float(np.mean(np.sqrt((mean_u - u) ** 2 + (mean_v - v) ** 2)))
        last_div = float(np.mean(np.abs(div)))
        last_shear = float(np.mean(np.sqrt(np.gradient(u, axis=0) ** 2 + np.gradient(v, axis=0) ** 2)))
    return u, v, {
        "loss_observation_fit_proxy": last_obs,
        "loss_background_fit_proxy": last_bg,
        "loss_stage4_sparse_prior_fit_proxy": last_prior,
        "loss_virtual_radial_velocity_fit_proxy": last_radial,
        "loss_smoothness_proxy": last_smooth,
        "loss_weak_horizontal_divergence_proxy": last_div,
        "loss_vertical_shear_proxy": last_shear,
        "loss_boundary_background_proxy": float(np.mean(boundary * np.sqrt((u - b_u) ** 2 + (v - b_v) ** 2))),
        "coverage_conf_positive_fraction": float(np.count_nonzero(np.maximum(obs_conf, prior_conf) > 0.0) / obs_conf.size),
        "iterations": float(iterations),
        "geometry_balance_mode": 1.0 if geometry_balance_mode == "los_weighted" else 0.0,
    }


def _write_sample_csv(path: Path, fields: dict[str, np.ndarray], radial: dict[str, np.ndarray], shape: tuple[int, int, int], sample_stride: int) -> None:
    stride = max(1, int(sample_stride))
    stage_lats, stage_lons, stage_alts = _stage2_lat_lon_alt(shape)
    site_ids = sorted(radial)
    fieldnames = ["z", "y", "x", "lat", "lon", "alt_m", "u_cma", "v_cma", "w_cma"] + [f"vr_{sid}" for sid in site_ids]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for z in range(0, shape[0], stride):
            for y in range(0, shape[1], stride):
                for x in range(0, shape[2], stride):
                    row = {
                        "z": z,
                        "y": y,
                        "x": x,
                        "lat": float(stage_lats[y]),
                        "lon": float(stage_lons[x]),
                        "alt_m": float(stage_alts[z]),
                        "u_cma": float(fields["u_wind_mps"][z, y, x]),
                        "v_cma": float(fields["v_wind_mps"][z, y, x]),
                        "w_cma": float(fields["w_wind_mps_from_omega"][z, y, x]),
                    }
                    for sid in site_ids:
                        row[f"vr_{sid}"] = float(radial[sid][z, y, x])
                    writer.writerow(row)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        f"# CMA-RA Virtual Radial 3DVAR Proxy - {payload['stage2_time_str']}",
        "",
        "## Boundary",
        "",
        "This output uses CMA-RA/CRA40 as an external reanalysis background, projects its gridded wind to virtual radial velocities, and combines those virtual radial constraints with the sparse Stage4 reconstructed wind prior plus aircraft wind anchors. It is not a standard Doppler-radar PyDDA retrieval because no real radar radial-velocity volume is available.",
        "",
        "## Inputs",
        "",
        f"- Stage2 frame: `{payload['stage2_time_str']}`",
        f"- CMA time: `{payload['cma_time_str']}` (`delta_hours={payload['cma_delta_hours']:.3f}`)",
        f"- CMA time method: `{payload.get('cma_time_method', 'nearest')}`",
        f"- Stage2 npz: `{payload['stage2_npz']}`",
        f"- CMA directory: `{payload['cma_dir']}`",
        f"- Stage4 sparse prior: `{payload.get('stage4_prior_npz') or 'not supplied'}`",
        f"- Aircraft anchor mode: `{payload.get('aircraft_anchor_mode', 'all_wind_records')}`",
        "",
        "## Virtual Radar Sites",
        "",
        "| site | lat | lon | alt_m |",
        "| --- | ---: | ---: | ---: |",
    ]
    for site in payload["radar_sites"]:
        lines.append(f"| `{site['site_id']}` | {site['lat']:.6f} | {site['lon']:.6f} | {site['alt_m']:.1f} |")
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- NPZ: `{payload['output_npz']}`",
            f"- sample CSV: `{payload['sample_csv']}`",
            "",
            "## Proxy Losses",
            "",
            "| metric | value |",
            "| --- | ---: |",
        ]
    )
    for key, value in payload.get("proxy_losses", {}).items():
        lines.append(f"| `{key}` | {float(value):.6f} |")
    lines.extend(
        [
            "",
            "## Method Notes",
            "",
            "- Virtual radial velocity is the projection of CMA u/v/w onto the line-of-sight vector from a synthetic radar site to each Stage2 voxel.",
            "- When `cma_time_method=linear`, the CMA field is linearly interpolated in time between adjacent 6-hour analyses: `F(t) = (1-alpha)*F(T0) + alpha*F(T1)`, then projected to virtual radial velocity at the Stage2/radar frame time.",
            "- When `cma_time_method=linear_qc`, the same linear interpolation is used, and voxels with large 6-hour vector change are flagged through `cma_rapid_change_flag_3d` for later weak-background downweighting.",
            "- When `geometry_balance_mode=los_weighted`, virtual-radial residuals are weighted by line-of-sight horizontal observability and range so that site geometry has less opportunity to dominate the proxy update.",
            "- The class-3DVAR proxy blends virtual radial velocity fit, Stage4 sparse reconstruction-prior fit, aircraft observation fit, background fit, neighbor smoothness, weak horizontal divergence suppression, vertical shear regularization, boundary/background retention and speed clipping.",
            f"- Aircraft anchor records used: `{payload.get('aircraft_anchor_records_used', 0)}`; Stage4-like anchor hold-out excluded: `{payload.get('aircraft_anchor_holdout_excluded', 0)}`.",
            "- CMA-RA is an external weak/background field. It can support training and comparison, but it must not replace strict aircraft hold-out labels.",
            "- Real PyDDA would ingest radar radial-velocity volumes and radar geometry; this file only creates a proxy source until those observations exist.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_one_frame(args: argparse.Namespace) -> dict[str, Any]:
    stage2_rows = _load_json(args.stage2_summary)
    rows_by_time = {str(row["time_str"]): row for row in stage2_rows}
    if str(args.frame_time) not in rows_by_time:
        raise ValueError(f"frame-time not found in Stage2 summary: {args.frame_time}")
    stage2_row = rows_by_time[str(args.frame_time)]
    npz_path = Path(stage2_row["multimodal_vox_path"])
    if not npz_path.is_absolute():
        npz_path = ROOT_DIR / npz_path
    npz = _load_stage2_npz(npz_path)
    shape = tuple(int(v) for v in np.asarray(npz[C2_GRID_SHAPE], dtype=np.int32).tolist())
    wind_records = _records(npz.get(C2_WIND_RECORDS))
    if str(args.aircraft_anchor_mode) == "none":
        anchor_wind_records: list[dict[str, Any]] = []
        anchor_holdout_records: list[dict[str, Any]] = []
    elif str(args.aircraft_anchor_mode) == "all_wind_records":
        anchor_wind_records = wind_records
        anchor_holdout_records = []
    elif str(args.aircraft_anchor_mode) == "stage4_train_wind":
        anchor_wind_records, anchor_holdout_records = _split_stage4_holdout_like(
            wind_records,
            holdout_fraction=float(args.stage4_holdout_fraction),
            holdout_count=int(args.stage4_holdout_count),
        )
    else:
        raise ValueError("Unsupported --aircraft-anchor-mode. Choose none, all_wind_records or stage4_train_wind.")

    cma_index = _index_cma_files(args.cma_dir)
    fields, cma_meta, cma_time, delta_hours = _load_cma_collocated_time_interpolated(
        cma_index,
        str(args.frame_time),
        shape,
        method=str(args.cma_time_method),
        max_time_delta_hours=float(args.max_time_delta_hours),
        max_window_hours=float(args.max_linear_window_hours),
    )

    sites = _parse_radar_sites(args.radar_sites)
    radial_fields: dict[str, np.ndarray] = {}
    radial_distance_fields: dict[str, np.ndarray] = {}
    line_of_sight: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    radial_geometry_weights: dict[str, np.ndarray] = {}
    for site in sites:
        vr, distance = _radial_velocity(
            fields["u_wind_mps"],
            fields["v_wind_mps"],
            fields["w_wind_mps_from_omega"],
            site,
            shape,
        )
        radial_fields[site.site_id] = vr
        radial_distance_fields[site.site_id] = distance
        east_hat, north_hat, up_hat, _ = _line_of_sight_units(site, shape)
        line_of_sight[site.site_id] = (east_hat, north_hat, up_hat)
        radial_geometry_weights[site.site_id] = _los_geometry_weight(east_hat, north_hat, distance)
    site_pair_los_difference = _site_pair_los_difference(line_of_sight, shape)

    stage4_prior_npz = args.stage4_recon_npz
    if stage4_prior_npz is None:
        stage4_prior_npz = _find_stage4_recon_npz(args.stage4_recon_dir, str(args.frame_time))
    prior_u, prior_v, prior_conf, prior_path = _load_stage4_prior(stage4_prior_npz, shape)

    obs_u, obs_v, obs_conf = _localized_aircraft_background(
        shape,
        anchor_wind_records,
        radius_xy=int(args.aircraft_radius_xy),
        radius_z=int(args.aircraft_radius_z),
        sigma_xy=float(args.aircraft_sigma_xy),
        sigma_z=float(args.aircraft_sigma_z),
    )
    proxy_u, proxy_v, proxy_losses = _three_dvar_proxy(
        fields["u_wind_mps"],
        fields["v_wind_mps"],
        fields["w_wind_mps_from_omega"],
        radial_fields,
        line_of_sight,
        prior_u,
        prior_v,
        prior_conf,
        obs_u,
        obs_v,
        obs_conf,
        iterations=int(args.proxy_iters),
        background_weight=float(args.background_weight),
        radial_weight=float(args.radial_weight),
        stage4_prior_weight=float(args.stage4_prior_weight),
        observation_weight=float(args.observation_weight),
        smoothness_weight=float(args.smoothness_weight),
        divergence_weight=float(args.divergence_weight),
        vertical_shear_weight=float(args.vertical_shear_weight),
        boundary_weight=float(args.boundary_weight),
        speed_limit_mps=float(args.speed_limit_mps),
        geometry_balance_mode=str(args.geometry_balance_mode),
        radial_geometry_weight=radial_geometry_weights,
    )
    proxy_radial_fields: dict[str, np.ndarray] = {}
    for site in sites:
        vr, _ = _radial_velocity(proxy_u, proxy_v, fields["w_wind_mps_from_omega"], site, shape)
        proxy_radial_fields[site.site_id] = vr

    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_npz = args.out_dir / f"cma_ra_virtual_radial_3dvar_{args.frame_time}.npz"
    sample_csv = args.out_dir / f"cma_ra_virtual_radial_3dvar_{args.frame_time}_sample.csv"
    report_md = args.out_dir / f"cma_ra_virtual_radial_3dvar_{args.frame_time}.md"
    np.savez_compressed(
        output_npz,
        time_str=np.asarray(str(args.frame_time)),
        cma_time_str=np.asarray(cma_time),
        cma_time_method=np.asarray(str(args.cma_time_method)),
        grid_shape=np.asarray(shape, dtype=np.int32),
        u_cma_3d=fields["u_wind_mps"].astype(np.float32),
        v_cma_3d=fields["v_wind_mps"].astype(np.float32),
        w_cma_3d=fields["w_wind_mps_from_omega"].astype(np.float32),
        cma_temporal_change_speed_3d=fields.get("cma_temporal_change_speed_mps", np.zeros(shape, dtype=np.float32)).astype(np.float32),
        cma_temporal_conf_3d=fields.get("cma_temporal_confidence", np.ones(shape, dtype=np.float32)).astype(np.float32),
        cma_rapid_change_flag_3d=fields.get("cma_rapid_change_flag", np.zeros(shape, dtype=np.float32)).astype(np.float32),
        u_proxy_3d=proxy_u.astype(np.float32),
        v_proxy_3d=proxy_v.astype(np.float32),
        cma_horizontal_speed_3d=np.sqrt(fields["u_wind_mps"].astype(np.float32) ** 2 + fields["v_wind_mps"].astype(np.float32) ** 2).astype(np.float32),
        proxy_horizontal_speed_3d=np.sqrt(proxy_u.astype(np.float32) ** 2 + proxy_v.astype(np.float32) ** 2).astype(np.float32),
        obs_u_aircraft_localized_3d=obs_u.astype(np.float32),
        obs_v_aircraft_localized_3d=obs_v.astype(np.float32),
        obs_conf_aircraft_localized_3d=obs_conf.astype(np.float32),
        stage4_prior_u_3d=prior_u.astype(np.float32),
        stage4_prior_v_3d=prior_v.astype(np.float32),
        stage4_prior_conf_3d=prior_conf.astype(np.float32),
        coverage_conf_3d=np.maximum(obs_conf, prior_conf).astype(np.float32),
        virtual_radial_velocity_json=np.asarray(json.dumps({k: f"virtual_radial_velocity_{k}_3d" for k in radial_fields}, ensure_ascii=False)),
        **{f"virtual_radial_velocity_{k}_3d": v.astype(np.float32) for k, v in radial_fields.items()},
        **{f"proxy_virtual_radial_velocity_{k}_3d": v.astype(np.float32) for k, v in proxy_radial_fields.items()},
        **{f"radar_distance_{k}_3d": v.astype(np.float32) for k, v in radial_distance_fields.items()},
        **{f"los_geometry_weight_{k}_3d": v.astype(np.float32) for k, v in radial_geometry_weights.items()},
        site_pair_los_difference_3d=site_pair_los_difference.astype(np.float32),
        cma_meta_json=np.asarray(json.dumps(cma_meta, ensure_ascii=False)),
        proxy_losses_json=np.asarray(json.dumps(proxy_losses, ensure_ascii=False)),
    )
    _write_sample_csv(sample_csv, fields, radial_fields, shape, int(args.sample_stride))
    payload = {
        "stage2_time_str": str(args.frame_time),
        "cma_time_str": cma_time,
        "cma_delta_hours": float(delta_hours),
        "cma_time_method": str(args.cma_time_method),
        "stage2_npz": str(npz_path),
        "cma_dir": str(args.cma_dir),
        "stage4_prior_npz": prior_path,
        "aircraft_anchor_mode": str(args.aircraft_anchor_mode),
        "aircraft_anchor_records_used": int(len(anchor_wind_records)),
        "aircraft_anchor_holdout_excluded": int(len(anchor_holdout_records)),
        "stage4_holdout_fraction_for_anchor_split": float(args.stage4_holdout_fraction),
        "stage4_holdout_count_for_anchor_split": int(args.stage4_holdout_count),
        "radar_sites": [site.__dict__ for site in sites],
        "output_npz": str(output_npz),
        "sample_csv": str(sample_csv),
        "proxy_losses": proxy_losses,
        "cma_meta": cma_meta,
        "geometry_balance_mode": str(args.geometry_balance_mode),
    }
    _write_report(report_md, payload)
    (args.out_dir / f"cma_ra_virtual_radial_3dvar_{args.frame_time}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def _parse_frame_times(text: str) -> list[str]:
    return [token.strip() for token in str(text).split(",") if token.strip()]


def _read_frame_times_file(path: Path | None) -> list[str]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Frame times file must contain a JSON list: {path}")
    return [str(item) for item in payload]


def _write_shard_frame_times(path: Path, frame_times: list[str]) -> None:
    path.write_text(json.dumps(frame_times, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_parent_shards(args: argparse.Namespace, frame_times: list[str]) -> list[dict[str, Any]]:
    workers = max(1, int(args.num_workers))
    shard_dir = args.out_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards = [[] for _ in range(workers)]
    for idx, frame_time in enumerate(frame_times):
        shards[idx % workers].append(frame_time)

    procs: list[tuple[subprocess.Popen[str], Path, Path]] = []
    env_base = os.environ.copy()
    env_base.setdefault("POLARS_MAX_THREADS", "1")
    env_base.setdefault("OMP_NUM_THREADS", "1")
    env_base.setdefault("OPENBLAS_NUM_THREADS", "1")
    for shard_idx, shard_frames in enumerate(shards):
        if not shard_frames:
            continue
        frame_file = shard_dir / f"cma_proxy_shard_{shard_idx:02d}_frames.json"
        summary_file = shard_dir / f"cma_proxy_shard_{shard_idx:02d}_summary.json"
        log_file = shard_dir / f"cma_proxy_shard_{shard_idx:02d}.log"
        _write_shard_frame_times(frame_file, shard_frames)
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--cma-dir",
            str(args.cma_dir),
            "--stage2-summary",
            str(args.stage2_summary),
            "--frame-times-file",
            str(frame_file),
            "--out-dir",
            str(args.out_dir),
            "--stage4-recon-dir",
            str(args.stage4_recon_dir),
            "--max-time-delta-hours",
            str(args.max_time_delta_hours),
            "--cma-time-method",
            str(args.cma_time_method),
            "--max-linear-window-hours",
            str(args.max_linear_window_hours),
            "--aircraft-anchor-mode",
            str(args.aircraft_anchor_mode),
            "--stage4-holdout-fraction",
            str(args.stage4_holdout_fraction),
            "--stage4-holdout-count",
            str(args.stage4_holdout_count),
            "--radar-sites",
            str(args.radar_sites),
            "--aircraft-radius-xy",
            str(args.aircraft_radius_xy),
            "--aircraft-radius-z",
            str(args.aircraft_radius_z),
            "--aircraft-sigma-xy",
            str(args.aircraft_sigma_xy),
            "--aircraft-sigma-z",
            str(args.aircraft_sigma_z),
            "--proxy-iters",
            str(args.proxy_iters),
            "--background-weight",
            str(args.background_weight),
            "--radial-weight",
            str(args.radial_weight),
            "--stage4-prior-weight",
            str(args.stage4_prior_weight),
            "--observation-weight",
            str(args.observation_weight),
            "--smoothness-weight",
            str(args.smoothness_weight),
            "--divergence-weight",
            str(args.divergence_weight),
            "--vertical-shear-weight",
            str(args.vertical_shear_weight),
            "--boundary-weight",
            str(args.boundary_weight),
            "--speed-limit-mps",
            str(args.speed_limit_mps),
            "--geometry-balance-mode",
            str(args.geometry_balance_mode),
            "--sample-stride",
            str(args.sample_stride),
            "--num-workers",
            str(workers),
            "--shard-id",
            str(shard_idx),
            "--shard-summary",
            str(summary_file),
        ]
        if args.stage4_recon_npz:
            cmd.extend(["--stage4-recon-npz", str(args.stage4_recon_npz)])
        with log_file.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
        procs.append((proc, summary_file, log_file))

    summaries: list[dict[str, Any]] = []
    for proc, summary_file, log_file in procs:
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"CMA proxy shard failed rc={rc}; see {log_file}")
        summaries.extend(json.loads(summary_file.read_text(encoding="utf-8")))
    return sorted(summaries, key=lambda row: str(row["stage2_time_str"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CMA-RA virtual radial velocity and 3DVAR-style proxy fields.")
    parser.add_argument("--cma-dir", type=Path, default=Path("/data/LFT-W02_data/pengxu/cma"))
    parser.add_argument("--stage2-summary", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json"))
    parser.add_argument("--frame-time", help="Stage2 frame time, e.g. 20260208124800")
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/cma_ra_virtual_radial_3dvar"))
    parser.add_argument("--stage4-recon-dir", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded"))
    parser.add_argument("--stage4-recon-npz", type=Path)
    parser.add_argument("--max-time-delta-hours", type=float, default=3.1)
    parser.add_argument("--cma-time-method", choices=["nearest", "linear", "linear_qc"], default="nearest")
    parser.add_argument("--max-linear-window-hours", type=float, default=6.1)
    parser.add_argument("--aircraft-anchor-mode", choices=["none", "all_wind_records", "stage4_train_wind"], default="all_wind_records")
    parser.add_argument("--stage4-holdout-fraction", type=float, default=0.125)
    parser.add_argument("--stage4-holdout-count", type=int, default=0)
    parser.add_argument(
        "--radar-sites",
        default="stage2_roi,33.2,104.0,0.0",
        help="Semicolon-separated synthetic sites: id,lat,lon,alt_m;id,lat,lon,alt_m",
    )
    parser.add_argument("--aircraft-radius-xy", type=int, default=8)
    parser.add_argument("--aircraft-radius-z", type=int, default=2)
    parser.add_argument("--aircraft-sigma-xy", type=float, default=4.0)
    parser.add_argument("--aircraft-sigma-z", type=float, default=1.0)
    parser.add_argument("--proxy-iters", type=int, default=6)
    parser.add_argument("--background-weight", type=float, default=0.04)
    parser.add_argument("--radial-weight", type=float, default=0.08)
    parser.add_argument("--stage4-prior-weight", type=float, default=0.22)
    parser.add_argument("--observation-weight", type=float, default=0.28)
    parser.add_argument("--smoothness-weight", type=float, default=0.018)
    parser.add_argument("--divergence-weight", type=float, default=0.006)
    parser.add_argument("--vertical-shear-weight", type=float, default=0.006)
    parser.add_argument("--boundary-weight", type=float, default=0.02)
    parser.add_argument("--speed-limit-mps", type=float, default=120.0)
    parser.add_argument("--geometry-balance-mode", choices=["off", "los_weighted"], default="off")
    parser.add_argument("--sample-stride", type=int, default=24)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--shard-id", type=int, default=-1)
    parser.add_argument("--shard-summary", type=Path)
    args = parser.parse_args()
    frame_times = _read_frame_times_file(args.frame_times_file)
    if not frame_times:
        frame_times = _parse_frame_times(args.frame_times)
    if not frame_times and args.frame_time:
        frame_times = [str(args.frame_time)]
    if not frame_times:
        raise ValueError("Provide --frame-time, --frame-times, or --frame-times-file")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if int(args.shard_id) < 0 and int(args.num_workers) > 1 and len(frame_times) > 1:
        summaries = _run_parent_shards(args, frame_times)
        summary_path = args.out_dir / "cma_ra_virtual_radial_3dvar_summary.json"
        summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        print(summary_path)
        return
    payloads = []
    for frame_time in frame_times:
        args.frame_time = str(frame_time)
        payloads.append(process_one_frame(args))
    summary_path = args.shard_summary if args.shard_summary else args.out_dir / "cma_ra_virtual_radial_3dvar_summary.json"
    summary_path.write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")
    print(payloads[-1]["output_npz"] if len(payloads) == 1 else summary_path)


if __name__ == "__main__":
    main()
