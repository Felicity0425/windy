"""Check Stage-1 / Stage-2 temporal and voxelization alignment.

This script focuses on whether cleaned location data from Stage-1 will align
with radar frames and produce non-empty voxelized outputs in Stage-2.

It reports:
- how many radar frames are usable
- how many location rows fall into each radar time window
- whether the time window overlaps look reasonable
- whether location coordinates can be voxelized into the expected grid range

Usage:
    python check_stage1_stage2_alignment.py
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pipeline_config as cfg

try:
    import polars as pl
except Exception as e:  # pragma: no cover
    pl = None
    POLARS_IMPORT_ERROR = e
else:
    POLARS_IMPORT_ERROR = None


STAGE1_DIR = os.path.join(cfg.BASE_DIR, "stage1_output")
STAGE1_WIND = os.path.join(STAGE1_DIR, "clean_wind.parquet")
STAGE1_LOC = os.path.join(STAGE1_DIR, "clean_loc.parquet")
STAGE1_RADAR_INDEX = os.path.join(STAGE1_DIR, "radar_index.json")
STAGE1_WINDOW_INDEX = os.path.join(STAGE1_DIR, "frame_window_index.json")


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_parquet(path: str):
    if pl is None:
        raise RuntimeError(f"polars not installed: {POLARS_IMPORT_ERROR}")
    return pl.read_parquet(path)


def _find_radar_files() -> List[str]:
    files: List[str] = []
    for pattern in cfg.RADAR_PATTERNS:
        if os.path.isabs(pattern):
            search_patterns = [pattern]
        else:
            search_patterns = [os.path.join(cfg.DATA_ROOT, pattern)]
        for sp in search_patterns:
            files.extend(glob.glob(sp, recursive=True))
    return sorted(set(files))


def _parse_radar_time(path: str) -> Optional[datetime]:
    fn = os.path.basename(path)
    try:
        ts = fn.split("_")[7]
        return datetime.strptime(ts, "%Y%m%d%H%M%S")
    except Exception:
        return None


def _estimate_grid_coverage(df_loc) -> Dict[str, Any]:
    if len(df_loc) == 0:
        return {"ok": False, "reason": "empty df_loc"}

    # Prefer cleaned columns from the rebuilt parquet; fall back if needed.
    needed = ["lat_clean", "lon_clean", "alt_meters"]
    missing = [c for c in needed if c not in df_loc.columns]
    if missing:
        alt_needed = ["纬度_clean", "经度_clean", "alt_meters"]
        if all(c in df_loc.columns for c in alt_needed):
            df_loc = df_loc.with_columns([
                pl.col("纬度_clean").alias("lat_clean"),
                pl.col("经度_clean").alias("lon_clean"),
            ])
            missing = []
        else:
            return {"ok": False, "reason": f"missing columns: {missing}"}

    h = 0
    w = 0
    radar_files = _find_radar_files()
    if radar_files:
        try:
            import cv2
            import numpy as np

            data = np.fromfile(radar_files[0], dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                h, w = img.shape
        except Exception:
            pass
    if h <= 0 or w <= 0:
        return {"ok": False, "reason": "cannot infer radar image shape"}

    delta_lat = (cfg.LAT_MAX - cfg.LAT_MIN) / h
    delta_lon = (cfg.LON_MAX - cfg.LON_MIN) / w

    df2 = df_loc.with_columns([
        ((pl.col("lon_clean") - cfg.LON_MIN) / delta_lon).cast(pl.Int32).alias("x"),
        ((cfg.LAT_MAX - pl.col("lat_clean")) / delta_lat).cast(pl.Int32).alias("y"),
        ((pl.col("alt_meters") - cfg.ALT_MIN) / cfg.DELTA_ALT).cast(pl.Int32).alias("z"),
    ])

    in_range = df2.filter(
        (pl.col("x") >= 0) & (pl.col("x") < w) &
        (pl.col("y") >= 0) & (pl.col("y") < h) &
        (pl.col("z") >= 0) & (pl.col("z") < cfg.Z_DIM)
    )

    return {
        "ok": True,
        "radar_shape": [h, w],
        "total_rows": int(len(df_loc)),
        "in_range_rows": int(len(in_range)),
        "in_range_ratio": float(len(in_range) / max(1, len(df_loc))),
        "unique_voxels": int(in_range.select(["z", "y", "x"]).unique().height) if len(in_range) > 0 else 0,
    }


def main():
    report: Dict[str, Any] = {
        "ok": True,
        "stage1_files": {},
        "radar_files_found": 0,
        "radar_frames_parsed": 0,
        "radar_frames_usable": 0,
        "window_stats": [],
        "coverage": {},
        "errors": [],
    }

    if pl is None:
        report["ok"] = False
        report["errors"].append(f"polars not installed: {POLARS_IMPORT_ERROR}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    if not os.path.exists(STAGE1_WIND) or not os.path.exists(STAGE1_LOC):
        report["ok"] = False
        report["errors"].append("stage1 output parquet files are missing")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    df_wind = _read_parquet(STAGE1_WIND)
    df_loc = _read_parquet(STAGE1_LOC)

    if "time_utc" not in df_loc.columns and "接收时间（UTC）" in df_loc.columns:
        df_loc = df_loc.with_columns(pl.col("接收时间（UTC）").alias("time_utc"))
    if "time_utc" not in df_wind.columns and "接收时间（UTC）" in df_wind.columns:
        df_wind = df_wind.with_columns(pl.col("接收时间（UTC）").alias("time_utc"))

    radar_index = _load_json(STAGE1_RADAR_INDEX) if os.path.exists(STAGE1_RADAR_INDEX) else []
    frame_window_index = _load_json(STAGE1_WINDOW_INDEX) if os.path.exists(STAGE1_WINDOW_INDEX) else []

    report["stage1_files"] = {
        "clean_wind_rows": int(len(df_wind)),
        "clean_loc_rows": int(len(df_loc)),
        "radar_index_count": int(len(radar_index)),
        "frame_window_count": int(len(frame_window_index)),
    }

    radar_files = _find_radar_files()
    report["radar_files_found"] = len(radar_files)

    parsed = []
    usable_count = 0
    loc_min_time = df_loc["time_utc"].min() if len(df_loc) > 0 and "time_utc" in df_loc.columns else None
    loc_max_time = df_loc["time_utc"].max() if len(df_loc) > 0 and "time_utc" in df_loc.columns else None

    for rp in radar_files:
        t = _parse_radar_time(rp)
        if t is None:
            continue
        parsed.append((rp, t))
        usable = True
        if cfg.OVERLAP_ONLY and loc_min_time is not None and loc_max_time is not None:
            usable = loc_min_time <= t <= loc_max_time
        if usable:
            usable_count += 1

            t_start = t - timedelta(minutes=cfg.TIME_WINDOW_MINUTES)
            t_end = t + timedelta(minutes=cfg.TIME_WINDOW_MINUTES)
            loc_rows = int(len(df_loc.filter((pl.col("time_utc") >= t_start) & (pl.col("time_utc") <= t_end))))
            wind_rows = int(len(df_wind.filter((pl.col("time_utc") >= t_start) & (pl.col("time_utc") <= t_end))))
            report["window_stats"].append({
                "filename": os.path.basename(rp),
                "timestamp_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "time_start": t_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "time_end": t_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "loc_rows": loc_rows,
                "wind_rows": wind_rows,
                "usable": True,
            })

    report["radar_frames_parsed"] = len(parsed)
    report["radar_frames_usable"] = usable_count

    coverage = _estimate_grid_coverage(df_loc)
    report["coverage"] = coverage

    if usable_count == 0:
        report["ok"] = False
        report["errors"].append("no usable radar frames overlap with location time range")
    if coverage.get("ok") and coverage.get("in_range_ratio", 0.0) < 0.2:
        report["ok"] = False
        report["errors"].append("less than 20% of location rows fall into the voxel grid")
    if coverage.get("ok") and coverage.get("unique_voxels", 0) == 0:
        report["ok"] = False
        report["errors"].append("no voxelized location points would be produced")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
