"""Inventory and verify local CMA/CRA40 GRIB assets for Stage4 experiments."""

from __future__ import annotations

import argparse
import json
from bisect import bisect_left
from collections import defaultdict
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

from stage.centralized_v1.core.centralized_cma_ra_virtual_radial_3dvar import (
    OPTIONAL_CODES,
    REQUIRED_WIND_CODES,
    _available_wind_times,
    _bracket_cma_times,
    _index_cma_files,
    _parse_stage_time,
    _pressure_hpa_to_alt_m,
    _read_grib_stack,
)


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
    return [line.strip() for line in text.splitlines() if line.strip()]


def _sample_time_keys(times: list[str], count: int) -> list[str]:
    if not times:
        return []
    capped = max(1, int(count))
    if len(times) <= capped:
        return list(times)
    picks = {0, len(times) - 1, len(times) // 2}
    while len(picks) < capped:
        idx = int(round((len(times) - 1) * len(picks) / max(1, capped - 1)))
        picks.add(min(len(times) - 1, idx))
    return [times[idx] for idx in sorted(picks)]


def _choose_probe_paths(index: dict[str, dict[str, Path]], sample_per_var: int) -> list[Path]:
    by_var: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    for time_str, files in index.items():
        for code, path in files.items():
            by_var[code].append((time_str, path))
    selected: list[Path] = []
    seen: set[Path] = set()
    for code, pairs in sorted(by_var.items()):
        pairs = sorted(pairs, key=lambda item: item[0])
        sample_keys = set(_sample_time_keys([time_str for time_str, _ in pairs], sample_per_var))
        for time_str, path in pairs:
            if time_str not in sample_keys or path in seen:
                continue
            seen.add(path)
            selected.append(path)
    return selected


def _to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _frame_coverage_report(
    frame_times_path: Path,
    available_wind_times: list[str],
    incomplete_optional_times: set[str],
    max_window_hours: float,
) -> dict[str, Any]:
    frames = _read_frame_times_file(frame_times_path)
    available_dt = [_parse_stage_time(time_str) for time_str in available_wind_times]
    exact_hits = 0
    bracket_ok = 0
    outside_range = 0
    bracket_failures: list[dict[str, str]] = []
    optional_gap_hits: list[dict[str, Any]] = []
    for frame_time in frames:
        target = _parse_stage_time(frame_time)
        pos = bisect_left(available_dt, target)
        if pos < len(available_dt) and available_dt[pos] == target:
            exact_hits += 1
        try:
            t0, t1, alpha, delta0, delta1 = _bracket_cma_times(frame_time, available_wind_times, max_window_hours=max_window_hours)
            bracket_ok += 1
            impacted = sorted({time_str for time_str in (t0, t1) if time_str in incomplete_optional_times})
            if impacted:
                optional_gap_hits.append(
                    {
                        "frame_time": frame_time,
                        "t0": t0,
                        "t1": t1,
                        "alpha": round(float(alpha), 6),
                        "delta0_hours": round(float(delta0), 6),
                        "delta1_hours": round(float(delta1), 6),
                        "incomplete_optional_times": impacted,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - audit path
            outside = target < available_dt[0] or target > available_dt[-1]
            outside_range += int(outside)
            bracket_failures.append({"frame_time": frame_time, "reason": str(exc)})
    return {
        "frame_times_path": str(frame_times_path),
        "frame_count": len(frames),
        "frame_time_min": frames[0] if frames else "",
        "frame_time_max": frames[-1] if frames else "",
        "exact_cma_hour_hits": exact_hits,
        "bracket_ok_count": bracket_ok,
        "bracket_failure_count": len(bracket_failures),
        "outside_inventory_range_count": outside_range,
        "optional_gap_bracket_hits_count": len(optional_gap_hits),
        "optional_gap_bracket_hits_preview": optional_gap_hits[:10],
        "bracket_failures_preview": bracket_failures[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify CMA/CRA40 GRIB inventory, readability, and frame coverage.")
    parser.add_argument("--cma-dir", type=Path, required=True)
    parser.add_argument("--frame-times-file", type=Path, action="append", default=[])
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--sample-per-var", type=int, default=3)
    parser.add_argument("--max-window-hours", type=float, default=6.1)
    parser.add_argument("--full-read", action="store_true")
    args = parser.parse_args()

    cma_index = _index_cma_files(args.cma_dir)
    available_wind_times = _available_wind_times(cma_index)
    all_times = sorted(cma_index)
    var_counts: dict[str, int] = defaultdict(int)
    missing_vars_by_time: dict[str, list[str]] = {}
    missing_optional_by_time: dict[str, list[str]] = {}
    for time_str in all_times:
        files = cma_index[time_str]
        for code in files:
            var_counts[code] += 1
        missing_required = sorted(code for code in REQUIRED_WIND_CODES if code not in files)
        missing_optional = sorted(code for code in OPTIONAL_CODES if code not in files)
        if missing_required:
            missing_vars_by_time[time_str] = missing_required
        if missing_optional:
            missing_optional_by_time[time_str] = missing_optional

    probe_paths = (
        sorted(path for files in cma_index.values() for path in files.values())
        if args.full_read
        else _choose_probe_paths(cma_index, int(args.sample_per_var))
    )
    probe_results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for path in probe_paths:
        try:
            stack = _read_grib_stack(path)
            levels_hpa = np.asarray(stack["levels_hpa"], dtype=np.float64)
            level_alts = _pressure_hpa_to_alt_m(levels_hpa)
            probe_results.append(
                {
                    "path": str(path),
                    "short_name": str(stack.get("short_name", "")),
                    "type_of_level": str(stack.get("type_of_level", "")),
                    "shape": [int(v) for v in np.asarray(stack["values"]).shape],
                    "levels_count": int(levels_hpa.size),
                    "level_hpa_min": float(np.min(levels_hpa)),
                    "level_hpa_max": float(np.max(levels_hpa)),
                    "level_alt_m_min": float(np.min(level_alts)),
                    "level_alt_m_max": float(np.max(level_alts)),
                    "lat_min": float(np.min(np.asarray(stack["latitudes"], dtype=np.float64))),
                    "lat_max": float(np.max(np.asarray(stack["latitudes"], dtype=np.float64))),
                    "lon_min": float(np.min(np.asarray(stack["longitudes"], dtype=np.float64))),
                    "lon_max": float(np.max(np.asarray(stack["longitudes"], dtype=np.float64))),
                }
            )
        except Exception as exc:  # noqa: BLE001 - audit path
            failures.append({"path": str(path), "error": str(exc)})

    frame_reports = [
        _frame_coverage_report(
            frame_times_path=path,
            available_wind_times=available_wind_times,
            incomplete_optional_times=set(missing_optional_by_time),
            max_window_hours=float(args.max_window_hours),
        )
        for path in args.frame_times_file
    ]

    wind_probe = next(
        (
            item
            for item in probe_results
            if Path(item["path"]).name.startswith("CRA40_WIU_") or Path(item["path"]).name.startswith("CRA40_WIV_")
        ),
        None,
    )
    gph_probe = next((item for item in probe_results if Path(item["path"]).name.startswith("CRA40_GPH_")), None)
    report = {
        "generated_utc": _to_iso_utc(datetime.now(timezone.utc)),
        "cma_dir": str(args.cma_dir),
        "inventory": {
            "file_count": int(sum(len(files) for files in cma_index.values())),
            "time_count": len(all_times),
            "wind_time_count": len(available_wind_times),
            "time_min": all_times[0] if all_times else "",
            "time_max": all_times[-1] if all_times else "",
            "var_counts": {key: int(var_counts.get(key, 0)) for key in sorted(set(var_counts) | set(REQUIRED_WIND_CODES) | set(OPTIONAL_CODES))},
            "missing_required_by_time": missing_vars_by_time,
            "missing_optional_by_time": missing_optional_by_time,
        },
        "read_probe": {
            "mode": "full_read" if args.full_read else "sample_read",
            "probe_count": len(probe_paths),
            "success_count": len(probe_results),
            "failure_count": len(failures),
            "failures": failures,
            "samples": probe_results[: min(24, len(probe_results))],
        },
        "vertical_coverage": {
            "wind_probe": wind_probe,
            "gph_probe": gph_probe,
            "has_120hpa_or_higher_wind_level": bool(wind_probe and float(wind_probe["level_hpa_min"]) <= 120.0),
            "has_15000m_or_higher_wind_level": bool(wind_probe and float(wind_probe["level_alt_m_max"]) >= 15000.0),
        },
        "frame_coverage": frame_reports,
        "independence_hint": {
            "manual_product_type": "CMA-RA manual defines the product family as reanalysis built from observations, NWP, and data assimilation.",
            "local_filename_suffix_example": str(probe_paths[0].name) if probe_paths else "",
            "safe_for_m1_display_fill": True,
            "safe_for_oi_without_provider_confirmation": False,
            "reason": (
                "Local 2026 files carry a CRA40 FTM 6-hour product suffix, but there is no local proof that the "
                "background is independent of the strict-holdout aircraft winds. Use it for display-only M1 first; "
                "block OI/innovation-based validation until the provider confirms independence."
            ),
        },
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out_json)


if __name__ == "__main__":
    main()
