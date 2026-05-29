"""Prepare and optionally convert MERRA-2 ROI background fields for Stage5.

This utility mirrors the existing ERA5/GFS helpers:

1. Build a keyframe-oriented manifest for MERRA-2 3D analysis fields.
2. Optionally convert locally downloaded NetCDF files into the lightweight NPZ
   layout consumed by `stage5_pinn_diffusion_refine.py`.

Notes:
    - MERRA-2 requires NASA Earthdata authentication for direct downloads.
    - This script writes a manifest and supports offline conversion first.
    - MERRA-2 is treated as a background prior / benchmark, not reconstruction truth.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi")
DEFAULT_NPZ_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz")
DEFAULT_FRAME_TIMES = "20260124013600,20260129114200,20260206174200,20260222063600"
DEFAULT_BBOX = "106.5,117.5,37.0,17.0"
DEFAULT_COLLECTION = "M2I3NVASM"


def _parse_time(time_str: str) -> datetime:
    return datetime.strptime(time_str, "%Y%m%d%H%M%S")


def _frame_tokens(frame_times: str) -> list[str]:
    return [token.strip() for token in frame_times.split(",") if token.strip()]


def _pressure_to_alt_km(pressure_hpa: np.ndarray) -> np.ndarray:
    pressure = np.maximum(np.asarray(pressure_hpa, dtype=np.float32), 1.0)
    return (44330.0 * (1.0 - (pressure / 1013.25) ** 0.1903) / 1000.0).astype(np.float32)


def _merra2_url(collection: str, dt: datetime) -> str:
    year = dt.strftime("%Y")
    doy = dt.strftime("%j")
    date = dt.strftime("%Y%m%d")
    filename = f"{collection}.5.12.4.{date}.nc4"
    return (
        "https://goldsmr5.gesdisc.eosdis.nasa.gov/data/"
        f"MERRA2/{collection}.5.12.4/{year}/{doy}/{filename}"
    )


def _var(ds: Any, *names: str) -> np.ndarray | None:
    for name in names:
        if name in ds.variables:
            arr = np.asarray(ds.variables[name][:], dtype=np.float32)
            while arr.ndim > 3:
                arr = arr[0]
            return arr
    return None


def _coord(ds: Any, *names: str) -> np.ndarray:
    for name in names:
        if name in ds.variables:
            return np.asarray(ds.variables[name][:], dtype=np.float32)
    raise KeyError(f"Missing coordinate among: {', '.join(names)}")


def _nearest_hour_index(hours: np.ndarray, target_hour: int) -> int:
    hours = np.asarray(hours, dtype=np.float32)
    if hours.size == 0:
        return 0
    return int(np.argmin(np.abs(hours - float(target_hour))))


def _subset_indices(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return np.where((values >= min(lo, hi)) & (values <= max(lo, hi)))[0]


def _convert_to_npz(src: Path, dst: Path, frame_time: str, bbox: tuple[float, float, float, float]) -> None:
    try:
        from netCDF4 import Dataset
    except ImportError as exc:
        raise RuntimeError("netCDF4 is required for MERRA-2 conversion.") from exc

    leftlon, rightlon, toplat, bottomlat = bbox
    dt = _parse_time(frame_time)
    with Dataset(src) as ds:
        lat = _coord(ds, "lat", "latitude")
        lon = _coord(ds, "lon", "longitude")
        lev = _coord(ds, "lev", "level", "pressure_hpa")
        time_vals = _coord(ds, "time")
        hour_idx = _nearest_hour_index(time_vals, dt.hour)
        yi = _subset_indices(lat, bottomlat, toplat)
        xi = _subset_indices(lon, leftlon, rightlon)
        if yi.size == 0 or xi.size == 0:
            raise ValueError(f"Empty ROI for bbox={bbox}")

        def crop(arr: np.ndarray) -> np.ndarray:
            arr = np.asarray(arr, dtype=np.float32)
            while arr.ndim > 3:
                arr = arr[hour_idx]
            if arr.ndim != 3:
                raise ValueError(f"Expected 3D field, got {arr.shape}")
            return arr[:, yi, :][:, :, xi].astype(np.float32, copy=False)

        u = _var(ds, "U", "u")
        v = _var(ds, "V", "v")
        if u is None or v is None:
            raise KeyError(f"{src} missing U/V variables")
        payload: dict[str, Any] = {
            "time_str": np.array(frame_time),
            "source_file": np.array(str(src)),
            "source": np.array("NASA MERRA-2 analysis"),
            "lat": lat[yi].astype(np.float32, copy=False),
            "lon": lon[xi].astype(np.float32, copy=False),
            "pressure_hpa": lev.astype(np.float32, copy=False),
            "alt_km": _pressure_to_alt_km(lev),
            "u": crop(u),
            "v": crop(v),
            "bbox_left_right_top_bottom": np.asarray(bbox, dtype=np.float32),
        }
        for out_name, names in {
            "vertical_velocity": ("OMEGA", "w"),
            "temperature": ("T", "t"),
            "relative_humidity": ("RH",),
            "geopotential": ("H", "PHIS"),
        }.items():
            arr = _var(ds, *names)
            if arr is not None:
                payload[out_name] = crop(arr)
        dst.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(dst, **payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare/convert MERRA-2 ROI background fields for Stage5.")
    parser.add_argument("--frame-times", default=DEFAULT_FRAME_TIMES)
    parser.add_argument("--bbox", default=DEFAULT_BBOX, help="leftlon,rightlon,toplat,bottomlat")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="MERRA-2 collection, default M2I3NVASM")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--npz-dir", type=Path, default=DEFAULT_NPZ_DIR)
    parser.add_argument("--convert-existing", action="store_true")
    args = parser.parse_args()

    bbox = tuple(float(token.strip()) for token in args.bbox.split(",") if token.strip())
    if len(bbox) != 4:
        raise ValueError("--bbox must be leftlon,rightlon,toplat,bottomlat")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.npz_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for frame_time in _frame_tokens(args.frame_times):
        dt = _parse_time(frame_time)
        target = args.out_dir / f"merra2_roi_{frame_time}.nc4"
        npz_target = args.npz_dir / f"merra2_roi_{frame_time}.npz"
        records.append(
            {
                "time_str": frame_time,
                "date": dt.strftime("%Y-%m-%d"),
                "hour_utc": dt.hour,
                "collection": args.collection,
                "target": str(target),
                "npz_target": str(npz_target),
                "url": _merra2_url(args.collection, dt),
                "bbox_left_right_top_bottom": list(bbox),
                "note": "Download with Earthdata-authenticated client, then run --convert-existing.",
            }
        )

    manifest_path = args.out_dir / "merra2_roi_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": "MERRA-2",
                "collection": args.collection,
                "source": "NASA GES DISC",
                "note": "MERRA-2 is used as a Stage5 background prior / benchmark, not reconstruction truth.",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[merra2] wrote manifest {manifest_path}")

    if args.convert_existing:
        for item in records:
            src = Path(item["target"])
            dst = Path(item["npz_target"])
            if not src.exists():
                print(f"[merra2][WARN] skip missing source {src}")
                continue
            print(f"[merra2] converting {src} -> {dst}")
            _convert_to_npz(src, dst, str(item["time_str"]), bbox)


if __name__ == "__main__":
    main()
