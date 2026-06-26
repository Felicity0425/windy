"""Download historical GFS ROI backgrounds with source-key dedup and resume.

This helper is built for large frame lists where many frame times map to the
same `(cycle, forecast_hour)` GFS source. It downloads each unique GFS source
once, converts it once, then fans out per-frame NPZ files with the target
`time_str` updated.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from download_stage5_gfs_aws_historical_roi import (
    DEFAULT_PRESSURE_LEVELS,
    _convert_roi,
    _download_idx,
    _download_selected_grib,
    _gfs_url,
    _nearest_cycle_and_hour,
    _parse_idx,
    _parse_time,
    _select_records,
)


@dataclass(frozen=True)
class SourceKey:
    cycle: str
    forecast_hour: int


def _frame_tokens_from_file(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _frame_tokens_from_csv(text: str) -> list[str]:
    return [token.strip() for token in text.split(",") if token.strip()]


def _source_key(frame_time: str) -> SourceKey:
    cycle_dt, forecast_hour = _nearest_cycle_and_hour(_parse_time(frame_time))
    return SourceKey(cycle=cycle_dt.strftime("%Y%m%d%H"), forecast_hour=int(forecast_hour))


def _group_frames(frame_times: list[str]) -> list[tuple[SourceKey, list[str]]]:
    grouped: dict[SourceKey, list[str]] = {}
    ordered: list[SourceKey] = []
    for frame_time in frame_times:
        key = _source_key(frame_time)
        if key not in grouped:
            grouped[key] = []
            ordered.append(key)
        grouped[key].append(frame_time)
    return [(key, grouped[key]) for key in ordered]


def _stem(key: SourceKey) -> str:
    return f"gfs_src_{key.cycle}_f{int(key.forecast_hour):03d}"


def _load_npz_payload(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as npz:
        return {name: np.array(npz[name]) for name in npz.files}


def _write_frame_npz(cache_npz: Path, frame_npz: Path, frame_time: str, source_frames: list[str]) -> None:
    payload = _load_npz_payload(cache_npz)
    payload["time_str"] = np.array(frame_time)
    payload["source_frame_times"] = np.array(",".join(source_frames))
    frame_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(frame_npz, **payload)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download cached historical GFS ROI backgrounds for many frames.")
    parser.add_argument("--frame-times-file", type=Path, default=None)
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--bbox", default="106.5,117.5,37.0,17.0", help="leftlon,rightlon,toplat,bottomlat")
    parser.add_argument(
        "--pressure-levels",
        default=",".join(str(v) for v in DEFAULT_PRESSURE_LEVELS),
        help="Comma-separated pressure levels in hPa.",
    )
    parser.add_argument("--variables", default="UGRD,VGRD", help="Comma-separated GFS variables, default UGRD,VGRD.")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--cache-npz-dir", type=Path, required=True)
    parser.add_argument("--frame-npz-dir", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--failed-frames-path", type=Path, required=True)
    parser.add_argument("--retry-sleep-seconds", type=int, default=10)
    parser.add_argument("--retry-sleep-max-seconds", type=int, default=120)
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=0,
        help="0 means retry forever; otherwise retry at most this many times per unique source.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.frame_times_file is not None:
        frame_times = _frame_tokens_from_file(args.frame_times_file)
    else:
        frame_times = _frame_tokens_from_csv(args.frame_times)
    if not frame_times:
        raise ValueError("No frame times provided.")

    bbox = tuple(float(token.strip()) for token in args.bbox.split(",") if token.strip())
    if len(bbox) != 4:
        raise ValueError("--bbox must be leftlon,rightlon,toplat,bottomlat")
    levels = [int(token.strip()) for token in args.pressure_levels.split(",") if token.strip()]
    variables = [token.strip().upper() for token in args.variables.split(",") if token.strip()]
    if not variables:
        raise ValueError("No variables provided.")

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    args.cache_npz_dir.mkdir(parents=True, exist_ok=True)
    args.frame_npz_dir.mkdir(parents=True, exist_ok=True)
    args.failed_frames_path.parent.mkdir(parents=True, exist_ok=True)

    groups = _group_frames(frame_times)
    manifest: dict[str, Any] = {
        "dataset": "gfs",
        "source": "NOAA GFS public AWS archive selected by .idx byte ranges",
        "mode": "cached_batch_unique_source_download",
        "frame_count": int(len(frame_times)),
        "unique_source_count": int(len(groups)),
        "variables": variables,
        "pressure_levels": levels,
        "bbox_left_right_top_bottom": list(bbox),
        "groups": [],
    }
    for key, frames in groups:
        manifest["groups"].append(
            {
                "cycle": key.cycle,
                "forecast_hour": int(key.forecast_hour),
                "source_stem": _stem(key),
                "frame_times": frames,
            }
        )
    args.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[gfs-cached] total_frames={len(frame_times)} unique_sources={len(groups)} "
        f"variables={variables} levels={len(levels)}",
        flush=True,
    )

    failed_frames: set[str] = set()
    for key, frames in groups:
        stem = _stem(key)
        cycle_dt = _parse_time(f"{key.cycle}0000")
        idx_url = _gfs_url(cycle_dt, int(key.forecast_hour), ".idx")
        grib_url = _gfs_url(cycle_dt, int(key.forecast_hour))
        idx_path = args.raw_dir / f"{stem}.idx"
        grib_path = args.raw_dir / f"{stem}.grib2"
        cache_npz_path = args.cache_npz_dir / f"{stem}.npz"

        if cache_npz_path.exists():
            print(f"[gfs-cached][skip-source] {stem} cache_npz_exists", flush=True)
        else:
            attempt = 0
            while True:
                attempt += 1
                print(
                    f"[gfs-cached][source] {stem} frames={len(frames)} "
                    f"attempt={attempt} cycle={key.cycle} f{int(key.forecast_hour):03d}",
                    flush=True,
                )
                try:
                    for path in (idx_path, grib_path, cache_npz_path):
                        if path.exists():
                            path.unlink()
                    _download_idx(str(idx_url), idx_path)
                    idx_records = _parse_idx(idx_path)
                    selected = _select_records(idx_records, set(variables), set(levels))
                    expected = len(variables) * len(levels)
                    print(f"[gfs-cached][source] {stem} selected={len(selected)} expected={expected}", flush=True)
                    if len(selected) < expected:
                        found = {(rec.variable, rec.level) for rec in selected}
                        missing = [
                            (var, f"{level} mb")
                            for var in variables
                            for level in levels
                            if (var, f"{level} mb") not in found
                        ]
                        raise RuntimeError(f"Missing selected messages: {missing[:20]}")
                    _download_selected_grib(str(grib_url), selected, grib_path)
                    meta = {
                        "url": str(grib_url),
                        "cycle": key.cycle,
                        "forecast_hour": int(key.forecast_hour),
                    }
                    _convert_roi(grib_path, cache_npz_path, frames[0], bbox, meta)
                    print(f"[gfs-cached][source-ok] {stem} cache_npz={cache_npz_path}", flush=True)
                    break
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    print(f"[gfs-cached][source-retry] {stem} error={type(exc).__name__}: {exc}", flush=True)
                    if int(args.max_attempts) > 0 and attempt >= int(args.max_attempts):
                        print(f"[gfs-cached][source-fail] {stem} exhausted attempts", flush=True)
                        failed_frames.update(frames)
                        break
                    sleep_seconds = min(
                        int(args.retry_sleep_max_seconds),
                        int(args.retry_sleep_seconds) * max(1, attempt),
                    )
                    time.sleep(sleep_seconds)

        if not cache_npz_path.exists():
            failed_frames.update(frames)
            continue

        for frame_time in frames:
            frame_npz_path = args.frame_npz_dir / f"gfs_roi_{frame_time}.npz"
            if frame_npz_path.exists():
                continue
            try:
                _write_frame_npz(cache_npz_path, frame_npz_path, frame_time, frames)
                print(f"[gfs-cached][frame-ok] {frame_time} <= {stem}", flush=True)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[gfs-cached][frame-fail] {frame_time} error={type(exc).__name__}: {exc}", flush=True)
                failed_frames.add(frame_time)

    args.failed_frames_path.write_text(
        "\n".join(sorted(failed_frames)) + ("\n" if failed_frames else ""),
        encoding="utf-8",
    )
    print(
        f"[gfs-cached][done] frame_npz_count={len(list(args.frame_npz_dir.glob('gfs_roi_*.npz')))} "
        f"failed_count={len(failed_frames)}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
