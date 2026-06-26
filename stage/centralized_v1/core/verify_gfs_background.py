"""Verify cached historical GFS background NPZ assets for Stage4 OI diagnostics."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.stage5_background_utils import load_background


REQUIRED_CORE_KEYS = {"time_str", "lat", "lon", "alt_km", "pressure_hpa", "u", "v"}


def _to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_frame_times_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        payload = json.loads(stripped)
        if not isinstance(payload, list):
            raise ValueError(f"Frame times file must contain a JSON list or one frame time per line: {path}")
        return [str(item).strip() for item in payload if str(item).strip()]
    if "," in stripped and "\n" not in stripped:
        return [token.strip() for token in stripped.split(",") if token.strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _nan_fraction(arr: np.ndarray) -> float:
    if arr.size == 0:
        return 1.0
    finite = np.isfinite(arr)
    return float(1.0 - np.count_nonzero(finite) / float(arr.size))


def _is_monotonic(arr: np.ndarray, descending_ok: bool = False) -> bool:
    if arr.size <= 1:
        return True
    diff = np.diff(np.asarray(arr, dtype=np.float64))
    if descending_ok:
        return bool(np.all(diff <= 0.0) or np.all(diff >= 0.0))
    return bool(np.all(diff >= 0.0))


def _preview(values: list[Any], limit: int = 10) -> list[Any]:
    return values[: min(limit, len(values))]


def _summarize_npz(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    with np.load(path, allow_pickle=False) as npz:
        files = list(npz.files)
        missing = sorted(REQUIRED_CORE_KEYS - set(files))
        payload["keys"] = files
        payload["missing_required_keys"] = missing
        payload["time_str"] = str(npz["time_str"]) if "time_str" in npz.files else path.stem.split("_")[-1]
        payload["cycle"] = str(npz["cycle"]) if "cycle" in npz.files else ""
        payload["forecast_hour"] = int(np.asarray(npz["forecast_hour"]).reshape(-1)[0]) if "forecast_hour" in npz.files else -1
        payload["source_url"] = str(npz["source_url"]) if "source_url" in npz.files else ""
        payload["source_frame_times"] = (
            [token for token in str(npz["source_frame_times"]).split(",") if token] if "source_frame_times" in npz.files else []
        )
        lat = np.asarray(npz["lat"], dtype=np.float32) if "lat" in npz.files else np.asarray([], dtype=np.float32)
        lon = np.asarray(npz["lon"], dtype=np.float32) if "lon" in npz.files else np.asarray([], dtype=np.float32)
        alt_km = np.asarray(npz["alt_km"], dtype=np.float32) if "alt_km" in npz.files else np.asarray([], dtype=np.float32)
        pressure = np.asarray(npz["pressure_hpa"], dtype=np.float32) if "pressure_hpa" in npz.files else np.asarray([], dtype=np.float32)
        u = np.asarray(npz["u"], dtype=np.float32) if "u" in npz.files else np.asarray([], dtype=np.float32)
        v = np.asarray(npz["v"], dtype=np.float32) if "v" in npz.files else np.asarray([], dtype=np.float32)
        payload["shape_u"] = [int(v) for v in u.shape]
        payload["shape_v"] = [int(v) for v in v.shape]
        payload["levels_count"] = int(alt_km.size)
        payload["lat_count"] = int(lat.size)
        payload["lon_count"] = int(lon.size)
        payload["lat_min"] = _safe_float(np.min(lat) if lat.size else float("nan"))
        payload["lat_max"] = _safe_float(np.max(lat) if lat.size else float("nan"))
        payload["lon_min"] = _safe_float(np.min(lon) if lon.size else float("nan"))
        payload["lon_max"] = _safe_float(np.max(lon) if lon.size else float("nan"))
        payload["alt_km_min"] = _safe_float(np.min(alt_km) if alt_km.size else float("nan"))
        payload["alt_km_max"] = _safe_float(np.max(alt_km) if alt_km.size else float("nan"))
        payload["pressure_hpa_min"] = _safe_float(np.min(pressure) if pressure.size else float("nan"))
        payload["pressure_hpa_max"] = _safe_float(np.max(pressure) if pressure.size else float("nan"))
        payload["lat_monotonic"] = _is_monotonic(lat, descending_ok=True)
        payload["lon_monotonic"] = _is_monotonic(lon, descending_ok=False)
        payload["alt_monotonic"] = _is_monotonic(alt_km, descending_ok=False)
        payload["pressure_monotonic"] = _is_monotonic(pressure, descending_ok=True)
        payload["u_nan_fraction"] = _nan_fraction(u)
        payload["v_nan_fraction"] = _nan_fraction(v)
        payload["shape_consistent"] = bool(u.ndim == 3 and v.shape == u.shape and alt_km.size == u.shape[0] and lat.size == u.shape[1] and lon.size == u.shape[2])
        payload["supports_12km_plus"] = bool(payload["alt_km_max"] >= 12.0)
    return payload


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    inv = report["inventory"]
    checks = report["checks"]
    levels = report["vertical_coverage"]
    lines = [
        "# GFS background verify report",
        "",
        f"- Generated: `{report['generated_utc']}`",
        f"- Background dir: `{report['background_dir']}`",
        f"- Cache dir: `{report['cache_dir']}`",
        f"- Manifest path: `{report['manifest_path']}`",
        "",
        "## Overall",
        "",
        f"- Expected frames: `{inv['expected_frame_count']}`",
        f"- Present frame NPZ: `{inv['frame_npz_count']}`",
        f"- Cache NPZ: `{inv['cache_npz_count']}`",
        f"- Manifest unique sources: `{inv['manifest_unique_source_count']}`",
        f"- Failed frame count: `{inv['failed_count']}`",
        f"- Ready for S4-OI-DIAG: `{checks['ready_for_s4_oi_diag']}`",
        "",
        "## Coverage",
        "",
        f"- Frame coverage OK count: `{checks['frame_coverage_ok_count']}`",
        f"- Frame coverage fail count: `{checks['frame_coverage_fail_count']}`",
        f"- Missing expected frames: `{len(inv['missing_expected_frame_times'])}`",
        f"- Extra frames: `{len(inv['extra_frame_times'])}`",
        f"- 12km+ supported: `{levels['supports_12km_plus']}`",
        "",
        "## Axes",
        "",
        f"- Levels count set: `{levels['levels_count_set']}`",
        f"- Pressure hPa range: `{levels['pressure_hpa_min']}` to `{levels['pressure_hpa_max']}`",
        f"- Alt km range: `{levels['alt_km_min']}` to `{levels['alt_km_max']}`",
        f"- Lat range: `{report['horizontal_coverage']['lat_min']}` to `{report['horizontal_coverage']['lat_max']}`",
        f"- Lon range: `{report['horizontal_coverage']['lon_min']}` to `{report['horizontal_coverage']['lon_max']}`",
        "",
        "## Preview",
        "",
        f"- Cycle/hour preview: `{report['mapping_preview']}`",
        f"- Issues preview: `{report['issues_preview']}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify cached historical GFS background NPZ assets for Stage4 OI diagnostics.")
    parser.add_argument("--background-dir", type=Path, required=True, help="Frame NPZ directory, usually .../gfs_historical_aws_200/npz")
    parser.add_argument("--cache-dir", type=Path, default=None, help="Cache NPZ directory, usually .../gfs_historical_aws_200/cache_npz")
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--failed-frames-path", type=Path, default=None)
    parser.add_argument("--frame-times-file", type=Path, action="append", default=[])
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    frame_dir = args.background_dir
    cache_dir = args.cache_dir
    manifest_path = args.manifest_path
    failed_frames_path = args.failed_frames_path
    frame_paths = sorted(frame_dir.glob("gfs_roi_*.npz"))
    cache_paths = sorted(cache_dir.glob("gfs_src_*.npz")) if cache_dir and cache_dir.exists() else []

    expected_frames: list[str] = []
    for path in args.frame_times_file:
        expected_frames.extend(_read_frame_times_file(path))
    expected_frame_set = set(expected_frames)

    failed_frames = _read_frame_times_file(failed_frames_path) if failed_frames_path and failed_frames_path.exists() else []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path and manifest_path.exists() else {}

    frame_summaries: list[dict[str, Any]] = []
    cache_summaries: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    all_keys: set[str] = set()

    for path in frame_paths:
        try:
            data = load_background(path, "")
            summary = _summarize_npz(path)
            summary["readable"] = data is not None
            frame_summaries.append(summary)
            all_keys.update(summary["keys"])
            if summary["missing_required_keys"] or not summary["shape_consistent"]:
                issues.append(
                    {
                        "path": str(path),
                        "time_str": summary["time_str"],
                        "missing_required_keys": summary["missing_required_keys"],
                        "shape_consistent": summary["shape_consistent"],
                    }
                )
        except Exception as exc:  # noqa: BLE001 - verification path
            issues.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})

    for path in cache_paths:
        try:
            summary = _summarize_npz(path)
            cache_summaries.append(summary)
            all_keys.update(summary["keys"])
            if summary["missing_required_keys"] or not summary["shape_consistent"]:
                issues.append(
                    {
                        "path": str(path),
                        "time_str": summary["time_str"],
                        "missing_required_keys": summary["missing_required_keys"],
                        "shape_consistent": summary["shape_consistent"],
                    }
                )
        except Exception as exc:  # noqa: BLE001 - verification path
            issues.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})

    frame_times_present = [item["time_str"] for item in frame_summaries]
    frame_time_set = set(frame_times_present)
    missing_expected = sorted(expected_frame_set - frame_time_set)
    extra_times = sorted(frame_time_set - expected_frame_set) if expected_frame_set else []
    levels_count_set = sorted({int(item["levels_count"]) for item in frame_summaries}) if frame_summaries else []
    shape_u_set = sorted({tuple(item["shape_u"]) for item in frame_summaries}) if frame_summaries else []
    shape_v_set = sorted({tuple(item["shape_v"]) for item in frame_summaries}) if frame_summaries else []

    lat_min = min((item["lat_min"] for item in frame_summaries), default=float("nan"))
    lat_max = max((item["lat_max"] for item in frame_summaries), default=float("nan"))
    lon_min = min((item["lon_min"] for item in frame_summaries), default=float("nan"))
    lon_max = max((item["lon_max"] for item in frame_summaries), default=float("nan"))
    alt_min = min((item["alt_km_min"] for item in frame_summaries), default=float("nan"))
    alt_max = max((item["alt_km_max"] for item in frame_summaries), default=float("nan"))
    pressure_min = min((item["pressure_hpa_min"] for item in frame_summaries), default=float("nan"))
    pressure_max = max((item["pressure_hpa_max"] for item in frame_summaries), default=float("nan"))
    u_nan_fraction_max = max((item["u_nan_fraction"] for item in frame_summaries), default=float("nan"))
    v_nan_fraction_max = max((item["v_nan_fraction"] for item in frame_summaries), default=float("nan"))

    frame_coverage_ok_count = sum(
        1
        for item in frame_summaries
        if item["shape_consistent"] and not item["missing_required_keys"] and item["supports_12km_plus"]
    )
    frame_coverage_fail_count = len(frame_summaries) - frame_coverage_ok_count
    ready_for_s4_oi_diag = bool(
        (not expected_frame_set or (len(frame_summaries) == len(expected_frame_set) and not missing_expected))
        and len(failed_frames) == 0
        and frame_coverage_fail_count == 0
        and len(issues) == 0
        and bool(frame_summaries)
    )

    mapping_preview = [
        {
            "time_str": item["time_str"],
            "cycle": item["cycle"],
            "forecast_hour": item["forecast_hour"],
            "source_frame_group_size": len(item["source_frame_times"]),
        }
        for item in _preview(frame_summaries, limit=12)
    ]

    report = {
        "generated_utc": _to_iso_utc(datetime.now(timezone.utc)),
        "background_dir": str(frame_dir),
        "cache_dir": str(cache_dir or ""),
        "manifest_path": str(manifest_path or ""),
        "failed_frames_path": str(failed_frames_path or ""),
        "inventory": {
            "expected_frame_count": int(len(expected_frame_set) if expected_frame_set else len(expected_frames)),
            "frame_npz_count": int(len(frame_paths)),
            "cache_npz_count": int(len(cache_paths)),
            "manifest_frame_count": int(manifest.get("frame_count", 0)) if isinstance(manifest, dict) else 0,
            "manifest_unique_source_count": int(manifest.get("unique_source_count", 0)) if isinstance(manifest, dict) else 0,
            "failed_count": int(len(failed_frames)),
            "failed_frames_preview": _preview(sorted(failed_frames), 20),
            "frame_time_min": min(frame_times_present) if frame_times_present else "",
            "frame_time_max": max(frame_times_present) if frame_times_present else "",
            "missing_expected_frame_times": missing_expected,
            "extra_frame_times": extra_times,
            "variables_present": sorted(all_keys),
        },
        "checks": {
            "frame_coverage_ok_count": int(frame_coverage_ok_count),
            "frame_coverage_fail_count": int(frame_coverage_fail_count),
            "all_frame_shapes_u": [list(item) for item in shape_u_set],
            "all_frame_shapes_v": [list(item) for item in shape_v_set],
            "all_axes_monotonic": bool(
                all(item["lat_monotonic"] and item["lon_monotonic"] and item["alt_monotonic"] and item["pressure_monotonic"] for item in frame_summaries)
            ),
            "max_nan_fraction_u": _safe_float(u_nan_fraction_max),
            "max_nan_fraction_v": _safe_float(v_nan_fraction_max),
            "ready_for_s4_oi_diag": ready_for_s4_oi_diag,
        },
        "vertical_coverage": {
            "levels_count_set": levels_count_set,
            "pressure_hpa_min": _safe_float(pressure_min),
            "pressure_hpa_max": _safe_float(pressure_max),
            "alt_km_min": _safe_float(alt_min),
            "alt_km_max": _safe_float(alt_max),
            "supports_12km_plus": bool(alt_max >= 12.0) if np.isfinite(alt_max) else False,
        },
        "horizontal_coverage": {
            "lat_min": _safe_float(lat_min),
            "lat_max": _safe_float(lat_max),
            "lon_min": _safe_float(lon_min),
            "lon_max": _safe_float(lon_max),
        },
        "mapping_preview": mapping_preview,
        "issues_preview": _preview(issues, 20),
        "frame_summaries_preview": _preview(frame_summaries, 10),
        "cache_summaries_preview": _preview(cache_summaries, 10),
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(args.out_md, report)
    print(args.out_json)
    print(args.out_md)


if __name__ == "__main__":
    main()
