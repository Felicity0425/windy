"""Download historical GFS ROI backgrounds with source-key dedup and resume.

This helper is built for large frame lists where many frame times map to the
same `(cycle, forecast_hour)` GFS source. It downloads each unique GFS source
once, converts it once, then fans out per-frame NPZ files with the target
`time_str` updated.
"""

from __future__ import annotations

import argparse
import json
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


def _pressure_level_signature_from_payload(payload: dict[str, Any]) -> tuple[int, ...]:
    if "pressure_hpa" not in payload:
        return ()
    pressure = np.asarray(payload["pressure_hpa"], dtype=np.float32).reshape(-1)
    return tuple(int(round(float(v))) for v in pressure.tolist())


def _pressure_level_signature(path: Path) -> tuple[int, ...]:
    if not path.exists():
        return ()
    payload = _load_npz_payload(path)
    return _pressure_level_signature_from_payload(payload)


def _payload_level_index(payload: dict[str, Any]) -> dict[int, int]:
    return {level: idx for idx, level in enumerate(_pressure_level_signature_from_payload(payload))}


def _merge_cache_payloads(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    existing_levels = _payload_level_index(existing)
    fresh_levels = _payload_level_index(fresh)
    union_levels = sorted(set(existing_levels) | set(fresh_levels), reverse=True)
    if not union_levels:
        raise ValueError("Cannot merge cache payloads without pressure_hpa levels.")

    out: dict[str, Any] = {}
    scalar_prefer_existing = [
        "time_str",
        "source_file",
        "source_url",
        "source",
        "cycle",
        "forecast_hour",
        "lat",
        "lon",
        "bbox_left_right_top_bottom",
    ]
    for key in scalar_prefer_existing:
        if key in existing:
            out[key] = np.array(existing[key])
        elif key in fresh:
            out[key] = np.array(fresh[key])

    lat_existing = np.asarray(existing.get("lat", []), dtype=np.float32)
    lat_fresh = np.asarray(fresh.get("lat", []), dtype=np.float32)
    lon_existing = np.asarray(existing.get("lon", []), dtype=np.float32)
    lon_fresh = np.asarray(fresh.get("lon", []), dtype=np.float32)
    if lat_existing.size and lat_fresh.size and not np.allclose(lat_existing, lat_fresh, equal_nan=True):
        raise ValueError("Existing and fresh GFS cache lat axes differ; cannot merge.")
    if lon_existing.size and lon_fresh.size and not np.allclose(lon_existing, lon_fresh, equal_nan=True):
        raise ValueError("Existing and fresh GFS cache lon axes differ; cannot merge.")

    shape_tail = None
    for payload in (existing, fresh):
        for key in ("u", "v"):
            if key in payload:
                arr = np.asarray(payload[key])
                if arr.ndim == 3:
                    shape_tail = arr.shape[1:]
                    break
        if shape_tail is not None:
            break
    if shape_tail is None:
        raise ValueError("Cannot merge cache payloads without 3D u/v fields.")

    out["pressure_hpa"] = np.asarray(union_levels, dtype=np.float32)
    level_to_alt: dict[int, float] = {}
    for payload, level_index in ((existing, existing_levels), (fresh, fresh_levels)):
        alt = np.asarray(payload.get("alt_km", []), dtype=np.float32).reshape(-1)
        for level, idx in level_index.items():
            if idx < alt.size:
                level_to_alt[level] = float(alt[idx])
    out["alt_km"] = np.asarray([level_to_alt[level] for level in union_levels], dtype=np.float32)

    union_keys = set(existing) | set(fresh)
    for key in sorted(union_keys):
        if key in out or key in {"pressure_hpa", "alt_km"}:
            continue
        ex = existing.get(key)
        fr = fresh.get(key)
        template = ex if ex is not None else fr
        arr_template = np.asarray(template)
        if arr_template.ndim == 3 and arr_template.shape[1:] == shape_tail:
            merged = np.full((len(union_levels), *shape_tail), np.nan, dtype=arr_template.dtype)
            for idx, level in enumerate(union_levels):
                if level in fresh_levels and fr is not None:
                    merged[idx] = np.asarray(fr)[fresh_levels[level]]
                elif level in existing_levels and ex is not None:
                    merged[idx] = np.asarray(ex)[existing_levels[level]]
            out[key] = merged
        else:
            if ex is not None:
                out[key] = np.array(ex)
            elif fr is not None:
                out[key] = np.array(fr)
    return out


def _missing_pressure_levels(cache_npz_path: Path, requested_levels: list[int]) -> list[int]:
    existing = set(_pressure_level_signature(cache_npz_path))
    return [level for level in requested_levels if int(level) not in existing]


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
        partial_grib_path = args.raw_dir / f"{stem}.partial.grib2"
        partial_npz_path = args.cache_npz_dir / f"{stem}.partial.npz"
        cache_updated = False

        missing_levels = _missing_pressure_levels(cache_npz_path, levels) if cache_npz_path.exists() else list(levels)
        if cache_npz_path.exists() and not missing_levels:
            print(f"[gfs-cached][skip-source] {stem} cache_npz_exists levels_ok", flush=True)
        else:
            attempt = 0
            while True:
                attempt += 1
                print(
                    f"[gfs-cached][source] {stem} frames={len(frames)} "
                    f"attempt={attempt} cycle={key.cycle} f{int(key.forecast_hour):03d} "
                    f"missing_levels={missing_levels}",
                    flush=True,
                )
                try:
                    download_levels = missing_levels if cache_npz_path.exists() else list(levels)
                    download_set = set(download_levels)
                    target_grib_path = partial_grib_path if cache_npz_path.exists() else grib_path
                    target_npz_path = partial_npz_path if cache_npz_path.exists() else cache_npz_path
                    for path in (idx_path, target_grib_path, target_npz_path):
                        if path.exists():
                            path.unlink()
                    _download_idx(str(idx_url), idx_path)
                    idx_records = _parse_idx(idx_path)
                    selected = _select_records(idx_records, set(variables), download_set)
                    expected = len(variables) * len(download_levels)
                    print(f"[gfs-cached][source] {stem} selected={len(selected)} expected={expected}", flush=True)
                    if len(selected) < expected:
                        found = {(rec.variable, rec.level) for rec in selected}
                        missing = [
                            (var, f"{level} mb")
                            for var in variables
                            for level in download_levels
                            if (var, f"{level} mb") not in found
                        ]
                        raise RuntimeError(f"Missing selected messages: {missing[:20]}")
                    _download_selected_grib(str(grib_url), selected, target_grib_path)
                    meta = {
                        "url": str(grib_url),
                        "cycle": key.cycle,
                        "forecast_hour": int(key.forecast_hour),
                    }
                    _convert_roi(target_grib_path, target_npz_path, frames[0], bbox, meta)
                    if cache_npz_path.exists() and target_npz_path == partial_npz_path:
                        merged = _merge_cache_payloads(_load_npz_payload(cache_npz_path), _load_npz_payload(partial_npz_path))
                        np.savez_compressed(cache_npz_path, **merged)
                        if partial_npz_path.exists():
                            partial_npz_path.unlink()
                        if partial_grib_path.exists():
                            partial_grib_path.unlink()
                    print(f"[gfs-cached][source-ok] {stem} cache_npz={cache_npz_path}", flush=True)
                    cache_updated = True
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

        cache_signature = _pressure_level_signature(cache_npz_path)
        for frame_time in frames:
            frame_npz_path = args.frame_npz_dir / f"gfs_roi_{frame_time}.npz"
            frame_signature = _pressure_level_signature(frame_npz_path) if frame_npz_path.exists() else ()
            if frame_npz_path.exists() and not cache_updated and frame_signature == cache_signature:
                continue
            try:
                _write_frame_npz(cache_npz_path, frame_npz_path, frame_time, frames)
                print(f"[gfs-cached][frame-ok] {frame_time} <= {stem} refreshed={int(frame_signature != cache_signature)}", flush=True)
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
