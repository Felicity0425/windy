"""Prepare, download, and convert GFS/GDAS ROI background fields for Stage5.

This script uses NOAA NOMADS GRIB filter URLs for real-time / near-real-time
background fields. It writes the same lightweight NPZ layout consumed by
`stage5_pinn_diffusion_refine.py`:

    lat, lon, alt_km, pressure_hpa, u, v, vertical_velocity, temperature,
    geopotential

Notes:
    - GFS is a forecast background, not a reanalysis truth field.
    - GDAS is useful as an analysis / short-delay comparison background.
    - Historical Jan/Feb 2026 replay may require NCEI/NCAR archives; NOMADS is
      primarily for current rolling operational data.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import numpy as np


DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi")
DEFAULT_NPZ_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz")
DEFAULT_FRAME_TIMES = "20260124013600,20260222063600,20260129114200,20260206174200"
DEFAULT_PRESSURE_LEVELS = [
    1000,
    975,
    950,
    925,
    900,
    850,
    800,
    750,
    700,
    650,
    600,
    550,
    500,
    450,
    400,
    350,
    300,
    250,
    200,
]
DEFAULT_VARS = ["UGRD", "VGRD", "VVEL", "TMP", "HGT"]
NOMADS_BASE = "https://nomads.ncep.noaa.gov/cgi-bin"


def _parse_time(time_str: str) -> datetime:
    return datetime.strptime(time_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _frame_tokens(frame_times: str) -> list[str]:
    return [token.strip() for token in frame_times.split(",") if token.strip()]


def _pressure_to_alt_km(pressure_hpa: np.ndarray) -> np.ndarray:
    pressure = np.maximum(np.asarray(pressure_hpa, dtype=np.float32), 1.0)
    return (44330.0 * (1.0 - (pressure / 1013.25) ** 0.1903) / 1000.0).astype(np.float32)


def _nearest_cycle_and_hour(dt: datetime, cycle_hours: tuple[int, ...] = (0, 6, 12, 18)) -> tuple[datetime, int]:
    base = dt.replace(minute=0, second=0, microsecond=0)
    candidates: list[datetime] = []
    for day_shift in (0, -1):
        day = (base + timedelta(days=day_shift)).date()
        for hour in cycle_hours:
            cyc = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
            if cyc <= base:
                candidates.append(cyc)
    if not candidates:
        cycle = base.replace(hour=0)
    else:
        cycle = max(candidates)
    forecast_hour = int(round((base - cycle).total_seconds() / 3600.0))
    return cycle, max(0, forecast_hour)


def _latest_cycle(now: datetime | None = None, lag_hours: int = 6) -> datetime:
    now = now or datetime.now(timezone.utc)
    safe = now - timedelta(hours=int(lag_hours))
    cycle, _ = _nearest_cycle_and_hour(safe)
    return cycle


def _parse_cycle(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("empty cycle")
    for fmt in ("%Y%m%d%H", "%Y%m%d%HZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise ValueError("--cycle must be formatted like YYYYMMDDHH, for example 2026051900")


def _filter_script(dataset: str) -> str:
    return "filter_gfs_0p25.pl" if dataset == "gfs" else "filter_gdas_0p25.pl"


def _file_name(dataset: str, cycle: datetime, forecast_hour: int) -> str:
    return f"{dataset}.t{cycle.hour:02d}z.pgrb2.0p25.f{forecast_hour:03d}"


def _dir_name(dataset: str, cycle: datetime) -> str:
    return f"/{dataset}.{cycle:%Y%m%d}/{cycle.hour:02d}/atmos"


def _build_nomads_url(
    *,
    dataset: str,
    cycle: datetime,
    forecast_hour: int,
    leftlon: float,
    rightlon: float,
    toplat: float,
    bottomlat: float,
    variables: list[str],
    pressure_levels: list[int],
) -> str:
    params: dict[str, str] = {
        "dir": _dir_name(dataset, cycle),
        "file": _file_name(dataset, cycle, forecast_hour),
        "subregion": "",
        "leftlon": f"{leftlon:g}",
        "rightlon": f"{rightlon:g}",
        "toplat": f"{toplat:g}",
        "bottomlat": f"{bottomlat:g}",
    }
    for var in variables:
        params[f"var_{var}"] = "on"
    for level in pressure_levels:
        params[f"lev_{level}_mb"] = "on"
    return f"{NOMADS_BASE}/{_filter_script(dataset)}?{urlencode(params)}"


def _manifest_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    variables = [token.strip().upper() for token in args.variables.split(",") if token.strip()]
    pressure_levels = [int(token.strip()) for token in args.pressure_levels.split(",") if token.strip()]
    leftlon, rightlon, toplat, bottomlat = [float(token.strip()) for token in args.bbox.split(",")]
    records: list[dict[str, Any]] = []
    if args.mode == "latest":
        frame_times = [args.alias_time or datetime.now(timezone.utc).strftime("%Y%m%d%H0000")]
        cycle = _parse_cycle(args.cycle) if args.cycle else _latest_cycle(lag_hours=args.latest_lag_hours)
        forecast_hour = int(args.forecast_hour)
    else:
        frame_times = _frame_tokens(args.frame_times)
        cycle = None
        forecast_hour = None
    for frame_time in frame_times:
        if args.mode == "frames":
            target_dt = _parse_time(frame_time)
            cycle, forecast_hour = _nearest_cycle_and_hour(target_dt)
        assert cycle is not None and forecast_hour is not None
        url = _build_nomads_url(
            dataset=args.dataset,
            cycle=cycle,
            forecast_hour=int(forecast_hour),
            leftlon=leftlon,
            rightlon=rightlon,
            toplat=toplat,
            bottomlat=bottomlat,
            variables=variables,
            pressure_levels=pressure_levels,
        )
        candidates = []
        for step in range(max(0, int(args.fallback_cycles)) + 1):
            candidate_cycle = cycle - timedelta(hours=6 * step)
            candidates.append(
                {
                    "cycle": candidate_cycle.strftime("%Y%m%d%H"),
                    "forecast_hour": int(forecast_hour + 6 * step) if args.mode == "latest" else int(forecast_hour),
                    "url": _build_nomads_url(
                        dataset=args.dataset,
                        cycle=candidate_cycle,
                        forecast_hour=int(forecast_hour + 6 * step) if args.mode == "latest" else int(forecast_hour),
                        leftlon=leftlon,
                        rightlon=rightlon,
                        toplat=toplat,
                        bottomlat=bottomlat,
                        variables=variables,
                        pressure_levels=pressure_levels,
                    ),
                }
            )
        target = args.out_dir / f"{args.dataset}_roi_{frame_time}.grib2"
        npz_target = args.npz_dir / f"{args.dataset}_roi_{frame_time}.npz"
        records.append(
            {
                "time_str": frame_time,
                "dataset": args.dataset,
                "cycle": cycle.strftime("%Y%m%d%H"),
                "forecast_hour": int(forecast_hour),
                "target": str(target),
                "npz_target": str(npz_target),
                "url": url,
                "fallback_candidates": candidates,
                "variables": variables,
                "pressure_levels": pressure_levels,
                "bbox_left_right_top_bottom": [leftlon, rightlon, toplat, bottomlat],
            }
        )
    return records


def _open_grib(path: Path) -> Any:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for conversion. Install xarray plus cfgrib/eccodes.") from exc
    try:
        return xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    except Exception as first:
        try:
            return xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": "", "filter_by_keys": {"typeOfLevel": "isobaricInhPa"}})
        except Exception as second:
            raise RuntimeError(f"Could not open {path} with cfgrib: {first}; {second}") from second


def _coord_values(ds: Any, *names: str) -> tuple[str, np.ndarray]:
    for name in names:
        if name in ds.coords:
            return name, np.asarray(ds[name].values, dtype=np.float32)
    raise KeyError(f"Missing coordinate, tried: {', '.join(names)}")


def _var(ds: Any, *names: str) -> np.ndarray | None:
    for name in names:
        if name in ds:
            arr = np.asarray(ds[name].values, dtype=np.float32)
            while arr.ndim > 3:
                arr = arr[0]
            return arr
    return None


def _ensure_zyx(arr: np.ndarray, pressure_len: int) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim != 3:
        raise ValueError(f"Expected 3D pressure/lat/lon field, got shape {arr.shape}")
    if arr.shape[0] == pressure_len:
        return arr
    if arr.shape[-1] == pressure_len:
        return np.moveaxis(arr, -1, 0)
    raise ValueError(f"Could not identify pressure axis in shape {arr.shape}, pressure_len={pressure_len}")


def _convert_to_npz(src: Path, dst: Path, frame_time: str) -> None:
    ds = _open_grib(src)
    _, lat = _coord_values(ds, "latitude", "lat")
    _, lon = _coord_values(ds, "longitude", "lon")
    _, pressure = _coord_values(ds, "isobaricInhPa", "level", "pressure_level")
    u = _var(ds, "u", "UGRD")
    v = _var(ds, "v", "VGRD")
    if u is None or v is None:
        raise KeyError(f"{src} does not contain UGRD/VGRD fields.")
    pressure = np.asarray(pressure, dtype=np.float32)
    payload: dict[str, Any] = {
        "time_str": np.array(frame_time),
        "source_file": np.array(str(src)),
        "lat": lat.astype(np.float32, copy=False),
        "lon": lon.astype(np.float32, copy=False),
        "pressure_hpa": pressure,
        "alt_km": _pressure_to_alt_km(pressure),
        "u": _ensure_zyx(u, pressure.size),
        "v": _ensure_zyx(v, pressure.size),
    }
    for out_name, names in {
        "vertical_velocity": ("w", "VVEL"),
        "temperature": ("t", "TMP"),
        "geopotential": ("gh", "z", "HGT"),
        "relative_humidity": ("r", "RH"),
    }.items():
        arr = _var(ds, *names)
        if arr is not None:
            payload[out_name] = _ensure_zyx(arr, pressure.size)
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, **payload)


def _download_url(url: str, target: Path, *, timeout: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=timeout) as resp, target.open("wb") as f:
        f.write(resp.read())


def _download_record(item: dict[str, Any], *, timeout: int) -> None:
    errors: list[str] = []
    candidates = item.get("fallback_candidates") or [{"url": item["url"], "cycle": item.get("cycle"), "forecast_hour": item.get("forecast_hour")}]
    for candidate in candidates:
        url = str(candidate["url"])
        try:
            print(f"[{item['dataset']}] try cycle={candidate.get('cycle')} f{int(candidate.get('forecast_hour', 0)):03d}")
            _download_url(url, Path(item["target"]), timeout=timeout)
            item["downloaded_cycle"] = candidate.get("cycle")
            item["downloaded_forecast_hour"] = int(candidate.get("forecast_hour", 0))
            return
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{candidate.get('cycle')} f{candidate.get('forecast_hour')}: {type(exc).__name__}: {exc}")
    raise RuntimeError("All NOMADS download candidates failed: " + " | ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/download/convert GFS/GDAS NOMADS ROI background fields.")
    parser.add_argument("--dataset", choices=("gfs", "gdas"), default="gfs")
    parser.add_argument("--mode", choices=("frames", "latest"), default="frames")
    parser.add_argument("--frame-times", default=DEFAULT_FRAME_TIMES)
    parser.add_argument("--alias-time", default="", help="Output time_str used in --mode latest.")
    parser.add_argument("--cycle", default="", help="Explicit cycle YYYYMMDDHH for --mode latest.")
    parser.add_argument("--forecast-hour", type=int, default=0, help="Forecast hour for --mode latest.")
    parser.add_argument("--latest-lag-hours", type=int, default=6)
    parser.add_argument("--fallback-cycles", type=int, default=3, help="Try previous 6-hour cycles when latest NOMADS cycle is unavailable.")
    parser.add_argument("--bbox", default="106.5,117.5,37.0,17.0", help="leftlon,rightlon,toplat,bottomlat.")
    parser.add_argument("--pressure-levels", default=",".join(str(v) for v in DEFAULT_PRESSURE_LEVELS))
    parser.add_argument("--variables", default=",".join(DEFAULT_VARS))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--npz-dir", type=Path, default=DEFAULT_NPZ_DIR)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--convert-existing", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records = _manifest_records(args)
    manifest_path = args.out_dir / f"{args.dataset}_roi_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "dataset": args.dataset,
                "source": "NOAA NOMADS GFS/GDAS GRIB filter",
                "note": "GFS/GDAS are operational background fields for Stage5 ROI priors, not full-field truth.",
                "records": records,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[{args.dataset}] wrote manifest {manifest_path}")

    if args.download:
        for item in records:
            print(f"[{args.dataset}] downloading {item['time_str']} -> {item['target']}")
            _download_record(item, timeout=int(args.timeout))

    if args.convert_existing:
        for item in records:
            src = Path(item["target"])
            if not src.exists():
                print(f"[{args.dataset}][WARN] skip missing source {src}")
                continue
            print(f"[{args.dataset}] converting {src} -> {item['npz_target']}")
            _convert_to_npz(src, Path(item["npz_target"]), str(item["time_str"]))


if __name__ == "__main__":
    main()
