"""Download historical GFS pressure-level ROI backgrounds from NOAA AWS.

NOMADS is mainly a rolling operational endpoint, so historical Jan/Feb 2026
frames need the public GFS archive objects. This utility reads the small .idx
file, downloads only selected GRIB messages by byte range, and writes the
Stage5 background NPZ layout cropped to the configured ROI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from download_stage5_gfs_gdas_roi import (
    _coord_values,
    _ensure_zyx,
    _open_grib,
    _pressure_to_alt_km,
    _var,
)


DEFAULT_FRAME_TIMES = "20260124013600,20260222063600,20260129114200,20260206174200"
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws")
DEFAULT_NPZ_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz")
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
AWS_BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"


@dataclass
class IdxRecord:
    number: int
    offset: int
    date_token: str
    variable: str
    level: str
    forecast: str
    end_offset: int | None = None


def _parse_time(time_str: str) -> datetime:
    return datetime.strptime(time_str, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _nearest_cycle_and_hour(dt: datetime) -> tuple[datetime, int]:
    base = dt.replace(minute=0, second=0, microsecond=0)
    candidates: list[datetime] = []
    for day_shift in (0, -1):
        day = (base + timedelta(days=day_shift)).date()
        for hour in (0, 6, 12, 18):
            cyc = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
            if cyc <= base:
                candidates.append(cyc)
    cycle = max(candidates)
    forecast_hour = int(round((base - cycle).total_seconds() / 3600.0))
    return cycle, max(0, forecast_hour)


def _gfs_url(cycle: datetime, forecast_hour: int, suffix: str = "") -> str:
    name = f"gfs.t{cycle.hour:02d}z.pgrb2.0p25.f{forecast_hour:03d}{suffix}"
    return f"{AWS_BASE}/gfs.{cycle:%Y%m%d}/{cycle.hour:02d}/atmos/{name}"


def _run_curl(args: list[str], stdout: Any | None = None, attempts: int = 6) -> None:
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            subprocess.run(
                ["curl", "-L", "-sS", "--fail", "--connect-timeout", "20", "--max-time", "180", *args],
                stdout=stdout,
                check=True,
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(20, 2 * attempt))
    assert last_error is not None
    raise last_error


def _download_idx(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_curl([url, "-o", str(path)])


def _parse_idx(path: Path) -> list[IdxRecord]:
    records: list[IdxRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(":")
        if len(parts) < 6:
            continue
        records.append(
            IdxRecord(
                number=int(parts[0]),
                offset=int(parts[1]),
                date_token=parts[2],
                variable=parts[3],
                level=parts[4],
                forecast=":".join(parts[5:]),
            )
        )
    for current, nxt in zip(records, records[1:]):
        current.end_offset = nxt.offset - 1
    return records


def _select_records(records: list[IdxRecord], variables: set[str], levels: set[int]) -> list[IdxRecord]:
    wanted_levels = {f"{level} mb" for level in levels}
    selected = [rec for rec in records if rec.variable in variables and rec.level in wanted_levels]
    selected.sort(key=lambda rec: rec.number)
    return selected


def _download_selected_grib(url: str, selected: list[IdxRecord], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as fout:
        for rec in selected:
            byte_range = f"{rec.offset}-" if rec.end_offset is None else f"{rec.offset}-{rec.end_offset}"
            print(f"[aws-gfs] range {byte_range} {rec.variable} {rec.level}")
            _run_curl(["-r", byte_range, url], stdout=fout)


def _subset_indices(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    return np.where((values >= min(lo, hi)) & (values <= max(lo, hi)))[0]


def _convert_roi(src: Path, dst: Path, frame_time: str, bbox: tuple[float, float, float, float], meta: dict[str, Any]) -> None:
    leftlon, rightlon, toplat, bottomlat = bbox
    ds = _open_grib(src)
    _, lat = _coord_values(ds, "latitude", "lat")
    _, lon = _coord_values(ds, "longitude", "lon")
    _, pressure = _coord_values(ds, "isobaricInhPa", "level", "pressure_level")
    pressure = np.asarray(pressure, dtype=np.float32)
    yi = _subset_indices(lat, bottomlat, toplat)
    xi = _subset_indices(lon, leftlon, rightlon)
    if yi.size == 0 or xi.size == 0:
        raise ValueError(f"Empty ROI for bbox={bbox}, lat range=({lat.min()}, {lat.max()}), lon range=({lon.min()}, {lon.max()})")

    def crop(arr: np.ndarray) -> np.ndarray:
        zyx = _ensure_zyx(arr, pressure.size)
        return zyx[:, yi, :][:, :, xi].astype(np.float32, copy=False)

    u = _var(ds, "u", "UGRD")
    v = _var(ds, "v", "VGRD")
    if u is None or v is None:
        raise KeyError(f"{src} does not contain UGRD/VGRD fields.")
    payload: dict[str, Any] = {
        "time_str": np.array(frame_time),
        "source_file": np.array(str(src)),
        "source_url": np.array(str(meta["url"])),
        "source": np.array("NOAA GFS historical AWS selected GRIB messages"),
        "cycle": np.array(str(meta["cycle"])),
        "forecast_hour": np.array(int(meta["forecast_hour"]), dtype=np.int32),
        "lat": lat[yi].astype(np.float32, copy=False),
        "lon": lon[xi].astype(np.float32, copy=False),
        "pressure_hpa": pressure,
        "alt_km": _pressure_to_alt_km(pressure),
        "u": crop(u),
        "v": crop(v),
        "bbox_left_right_top_bottom": np.asarray(bbox, dtype=np.float32),
    }
    for out_name, names in {
        "vertical_velocity": ("w", "VVEL"),
        "temperature": ("t", "TMP"),
        "geopotential": ("gh", "z", "HGT"),
        "relative_humidity": ("r", "RH"),
    }.items():
        arr = _var(ds, *names)
        if arr is not None:
            payload[out_name] = crop(arr)
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, **payload)


def _records_for_frames(args: argparse.Namespace) -> list[dict[str, Any]]:
    levels = [int(token.strip()) for token in args.pressure_levels.split(",") if token.strip()]
    variables = [token.strip().upper() for token in args.variables.split(",") if token.strip()]
    bbox = tuple(float(token.strip()) for token in args.bbox.split(","))
    records: list[dict[str, Any]] = []
    for frame_time in [token.strip() for token in args.frame_times.split(",") if token.strip()]:
        cycle, forecast_hour = _nearest_cycle_and_hour(_parse_time(frame_time))
        grib_url = _gfs_url(cycle, forecast_hour)
        idx_url = _gfs_url(cycle, forecast_hour, ".idx")
        records.append(
            {
                "time_str": frame_time,
                "cycle": cycle.strftime("%Y%m%d%H"),
                "forecast_hour": forecast_hour,
                "url": grib_url,
                "idx_url": idx_url,
                "idx_target": str(args.out_dir / f"gfs_roi_{frame_time}.idx"),
                "target": str(args.out_dir / f"gfs_roi_{frame_time}.grib2"),
                "npz_target": str(args.npz_dir / f"gfs_roi_{frame_time}.npz"),
                "variables": variables,
                "pressure_levels": levels,
                "bbox_left_right_top_bottom": list(bbox),
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Download historical GFS AWS selected GRIB messages and convert to Stage5 ROI NPZ.")
    parser.add_argument("--frame-times", default=DEFAULT_FRAME_TIMES)
    parser.add_argument("--bbox", default="106.5,117.5,37.0,17.0", help="leftlon,rightlon,toplat,bottomlat")
    parser.add_argument("--pressure-levels", default=",".join(str(v) for v in DEFAULT_PRESSURE_LEVELS))
    parser.add_argument("--variables", default=",".join(DEFAULT_VARS))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--npz-dir", type=Path, default=DEFAULT_NPZ_DIR)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--convert-existing", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.npz_dir.mkdir(parents=True, exist_ok=True)
    records = _records_for_frames(args)
    manifest_path = args.out_dir / "gfs_historical_aws_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": "gfs",
                "source": "NOAA GFS public AWS archive selected by .idx byte ranges",
                "note": "Historical GFS background fields for Stage5 ROI priors; not reconstruction truth.",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[aws-gfs] wrote manifest {manifest_path}")

    for item in records:
        idx_path = Path(item["idx_target"])
        target = Path(item["target"])
        npz_target = Path(item["npz_target"])
        if args.download:
            print(f"[aws-gfs] downloading idx {item['idx_url']}")
            _download_idx(str(item["idx_url"]), idx_path)
            idx_records = _parse_idx(idx_path)
            selected = _select_records(idx_records, set(item["variables"]), set(item["pressure_levels"]))
            expected = len(item["variables"]) * len(item["pressure_levels"])
            print(f"[aws-gfs] selected {len(selected)} messages, expected {expected}")
            if len(selected) < expected:
                found = {(rec.variable, rec.level) for rec in selected}
                missing = [
                    (var, f"{level} mb")
                    for var in item["variables"]
                    for level in item["pressure_levels"]
                    if (var, f"{level} mb") not in found
                ]
                raise RuntimeError(f"Missing selected messages for {item['time_str']}: {missing[:20]}")
            _download_selected_grib(str(item["url"]), selected, target)
        if args.convert_existing:
            if not target.exists():
                print(f"[aws-gfs][WARN] missing {target}, skip conversion")
                continue
            bbox = tuple(float(v) for v in item["bbox_left_right_top_bottom"])
            print(f"[aws-gfs] converting {target} -> {npz_target}")
            _convert_roi(target, npz_target, str(item["time_str"]), bbox, item)


if __name__ == "__main__":
    main()
