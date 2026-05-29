"""Prepare and optionally download ERA5 ROI background fields for Stage5.

The script has three jobs:

1. Build a small keyframe-oriented CDS request manifest.
2. Optionally submit the requests when `cdsapi` and `$HOME/.cdsapirc` exist.
3. Convert downloaded ERA5 NetCDF/GRIB files into the lightweight NPZ layout
   consumed by `stage5_pinn_diffusion_refine.py`.

The NPZ layout is deliberately simple:

    lat, lon, alt_km, pressure_hpa, u, v, vertical_velocity, temperature,
    geopotential

`u` and `v` must have shape `(z, y, x)`.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_SUMMARY = Path("/data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json")
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/era5_roi")
DEFAULT_NPZ_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/era5_roi_npz")
DEFAULT_FRAME_TIMES = "20260124013600,20260129114200,20260129174200,20260205173000,20260206174200,20260222063600"

DEFAULT_PRESSURE_LEVELS = [
    "1000",
    "975",
    "950",
    "925",
    "900",
    "875",
    "850",
    "800",
    "750",
    "700",
    "600",
    "500",
    "400",
    "300",
    "250",
    "225",
    "200",
]
DEFAULT_VARIABLES = [
    "u_component_of_wind",
    "v_component_of_wind",
    "vertical_velocity",
    "geopotential",
    "temperature",
]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _frame_id(row: dict[str, Any]) -> str:
    return str(row.get("time_str") or Path(str(row.get("filename", ""))).stem.replace("frame_", ""))


def _find_rows(summary: list[dict[str, Any]], frame_times: str) -> list[dict[str, Any]]:
    wanted = [token.strip() for token in frame_times.split(",") if token.strip()]
    by_time = {str(row.get("time_str", "")): row for row in summary}
    missing = [time for time in wanted if time not in by_time]
    if missing:
        raise ValueError(f"Frame times not found in summary: {', '.join(missing)}")
    return [by_time[time] for time in wanted]


def _parse_time(time_str: str) -> datetime:
    return datetime.strptime(time_str, "%Y%m%d%H%M%S")


def _hour_string(dt: datetime) -> str:
    return f"{dt.hour:02d}:00"


def _request_for_row(
    row: dict[str, Any],
    *,
    area: list[float],
    pressure_levels: list[str],
    variables: list[str],
    data_format: str,
) -> dict[str, Any]:
    dt = _parse_time(_frame_id(row))
    return {
        "product_type": ["reanalysis"],
        "variable": variables,
        "year": [f"{dt.year:04d}"],
        "month": [f"{dt.month:02d}"],
        "day": [f"{dt.day:02d}"],
        "time": [_hour_string(dt)],
        "pressure_level": pressure_levels,
        "data_format": data_format,
        "download_format": "unarchived",
        "area": area,
    }


def _pressure_to_alt_km(pressure_hpa: np.ndarray) -> np.ndarray:
    pressure = np.maximum(np.asarray(pressure_hpa, dtype=np.float32), 1.0)
    return (44330.0 * (1.0 - (pressure / 1013.25) ** 0.1903) / 1000.0).astype(np.float32)


def _normalize_lat_lon(ds: Any) -> tuple[np.ndarray, np.ndarray, str, str]:
    lat_name = "latitude" if "latitude" in ds.coords else "lat"
    lon_name = "longitude" if "longitude" in ds.coords else "lon"
    lat = np.asarray(ds[lat_name].values, dtype=np.float32)
    lon = np.asarray(ds[lon_name].values, dtype=np.float32)
    return lat, lon, lat_name, lon_name


def _normalize_level(ds: Any) -> tuple[np.ndarray, str]:
    for name in ("pressure_level", "level", "isobaricInhPa"):
        if name in ds.coords:
            return np.asarray(ds[name].values, dtype=np.float32), name
    raise KeyError("Could not find ERA5 pressure level coordinate.")


def _var(ds: Any, *names: str) -> np.ndarray | None:
    for name in names:
        if name in ds:
            arr = np.asarray(ds[name].values, dtype=np.float32)
            while arr.ndim > 3:
                arr = arr[0]
            return arr
    return None


def _convert_to_npz(src: Path, dst: Path, frame_time: str) -> None:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required for --convert-existing. Install xarray plus netcdf4 or cfgrib.") from exc

    open_kwargs: dict[str, Any] = {}
    if src.suffix.lower() in (".grib", ".grib2"):
        open_kwargs["engine"] = "cfgrib"
    ds = xr.open_dataset(src, **open_kwargs)
    lat, lon, _, _ = _normalize_lat_lon(ds)
    pressure, _ = _normalize_level(ds)
    u = _var(ds, "u", "u_component_of_wind")
    v = _var(ds, "v", "v_component_of_wind")
    if u is None or v is None:
        raise KeyError(f"{src} does not contain u/v wind variables.")
    payload: dict[str, Any] = {
        "time_str": np.array(frame_time),
        "source_file": np.array(str(src)),
        "lat": lat,
        "lon": lon,
        "pressure_hpa": pressure,
        "alt_km": _pressure_to_alt_km(pressure),
        "u": u.astype(np.float32, copy=False),
        "v": v.astype(np.float32, copy=False),
    }
    for out_name, names in {
        "vertical_velocity": ("w", "vertical_velocity"),
        "geopotential": ("z", "geopotential"),
        "temperature": ("t", "temperature"),
    }.items():
        arr = _var(ds, *names)
        if arr is not None:
            payload[out_name] = arr.astype(np.float32, copy=False)
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, **payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/download/convert ERA5 ROI pressure-level background fields.")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--frame-times", default=DEFAULT_FRAME_TIMES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--npz-dir", type=Path, default=DEFAULT_NPZ_DIR)
    parser.add_argument("--area", default="37.0,106.5,17.0,117.5", help="CDS area as north,west,south,east.")
    parser.add_argument("--pressure-levels", default=",".join(DEFAULT_PRESSURE_LEVELS))
    parser.add_argument("--variables", default=",".join(DEFAULT_VARIABLES))
    parser.add_argument("--data-format", choices=("netcdf", "grib"), default="netcdf")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--convert-existing", action="store_true")
    args = parser.parse_args()

    summary = _load_json(args.summary)
    if not isinstance(summary, list):
        raise TypeError(f"Expected Stage4 summary list at {args.summary}")
    rows = _find_rows(summary, args.frame_times)
    area = [float(token.strip()) for token in args.area.split(",") if token.strip()]
    if len(area) != 4:
        raise ValueError("--area must be north,west,south,east")
    levels = [token.strip() for token in args.pressure_levels.split(",") if token.strip()]
    variables = [token.strip() for token in args.variables.split(",") if token.strip()]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for row in rows:
        frame_time = _frame_id(row)
        ext = "nc" if args.data_format == "netcdf" else "grib"
        target = args.out_dir / f"era5_roi_{frame_time}.{ext}"
        npz_target = args.npz_dir / f"era5_roi_{frame_time}.npz"
        request = _request_for_row(
            row,
            area=area,
            pressure_levels=levels,
            variables=variables,
            data_format=args.data_format,
        )
        manifest.append(
            {
                "time_str": frame_time,
                "source_index": row.get("source_index"),
                "target": str(target),
                "npz_target": str(npz_target),
                "request": request,
            }
        )

    manifest_path = args.out_dir / "era5_roi_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "dataset": "reanalysis-era5-pressure-levels",
                "note": "ERA5 is historical background/benchmark data, not the online real-time input.",
                "area_north_west_south_east": area,
                "records": manifest,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[era5] wrote manifest {manifest_path}")

    if args.download:
        if not (Path.home() / ".cdsapirc").exists():
            raise FileNotFoundError("Missing $HOME/.cdsapirc. Configure a CDS API token before --download.")
        try:
            import cdsapi
        except ImportError as exc:
            raise RuntimeError("cdsapi is required for --download. Install it in the active Python environment.") from exc
        client = cdsapi.Client()
        for item in manifest:
            print(f"[era5] downloading {item['time_str']} -> {item['target']}")
            client.retrieve("reanalysis-era5-pressure-levels", item["request"], item["target"])

    if args.convert_existing:
        for item in manifest:
            src = Path(item["target"])
            if not src.exists():
                print(f"[era5][WARN] skip missing source {src}")
                continue
            print(f"[era5] converting {src} -> {item['npz_target']}")
            _convert_to_npz(src, Path(item["npz_target"]), str(item["time_str"]))


if __name__ == "__main__":
    main()
