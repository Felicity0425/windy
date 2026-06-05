"""Build aircraft observation-error calibration for Stage4 weights.

The calibration is intentionally derived only from non-holdout aircraft wind
records. For each frame, current holdout labels are removed first, then the
remaining current/context aircraft winds are compared with local neighboring
aircraft winds to estimate a robust vector-error sigma by diagnostic bins.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
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

from stage.centralized_v1.configs.centralized_v1_config import REGENERATED_STAGE2_OUTPUT_DIR  # noqa: E402
from stage.centralized_v1.configs.centralized_v1_contract import (  # noqa: E402
    C2_CONTEXT_WIND_RECORDS,
    C2_GRID_SHAPE,
    C2_WIND_RECORDS,
)
from stage.centralized_v1.core.centralized_stage4_ground_recon import (  # noqa: E402
    DEFAULT_QC_CALIBRATION,
    _load_json,
    _load_stage2_npz,
    _obs_error_composite_key,
    _obs_error_feature_labels,
    _records,
    _safe_float,
    _safe_int,
    _split_holdout,
)
from stage.centralized_v1.core.centralized_stage4_sensitivity import (  # noqa: E402
    _frame_times_from_args,
    _sample_rows,
    _select_rows,
)


REFERENCES = [
    {
        "topic": "WMO aircraft-based observations programme",
        "url": "https://wmo.int/aircraft-based-observations-programme",
        "why": "Aircraft reports are treated as sparse weather observations with position/time metadata, not as dense gridded truth.",
    },
    {
        "topic": "de Haan and Stoffelen 2016 Mode-S EHS wind QC/error estimation",
        "url": "https://amt.copernicus.org/articles/9/4141/2016/",
        "why": "Uses quality control and triple collocation ideas for aircraft-derived wind errors.",
    },
    {
        "topic": "EMADDC aircraft weather observations quality control",
        "url": "https://amt.copernicus.org/articles/18/3341/2025/",
        "why": "Documents modern aircraft weather observation processing and error/QC handling.",
    },
    {
        "topic": "DART localization and Gaspari-Cohn covariance cutoff",
        "url": "https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html",
        "why": "Motivates local-neighborhood weighting and localization as an assimilation design choice.",
    },
]


def _finite_array(values: list[float]) -> np.ndarray:
    return np.asarray([float(v) for v in values if math.isfinite(float(v))], dtype=np.float64)


def _robust_sigma(values: list[float], *, floor: float, cap: float) -> float | None:
    arr = _finite_array(values)
    if arr.size == 0:
        return None
    rms = float(np.sqrt(np.mean(arr**2)))
    p75 = float(np.percentile(arr, 75.0))
    sigma = 0.5 * rms + 0.5 * p75
    return float(np.clip(max(floor, sigma), floor, cap))


def _stats(values: list[float]) -> dict[str, Any]:
    arr = _finite_array(values)
    if arr.size == 0:
        return {"count": 0, "mean": None, "median": None, "p75": None, "p90": None, "rms": None, "max": None}
    return {
        "count": int(arr.size),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "p75": float(np.percentile(arr, 75.0)),
        "p90": float(np.percentile(arr, 90.0)),
        "rms": float(np.sqrt(np.mean(arr**2))),
        "max": float(np.max(arr)),
    }


def _row_time_conf(row: dict[str, Any], source_role: str) -> float:
    if source_role == "current_wind_train":
        return 1.0
    time_conf = _safe_float(row.get("time_conf"), 0.0)
    if time_conf <= 0.0 and row.get("joint_likelihood") is not None:
        obs_conf = max(1e-6, _safe_float(row.get("obs_conf"), 1.0))
        time_conf = _safe_float(row.get("joint_likelihood"), 0.0) / obs_conf
    return float(np.clip(time_conf, 0.0, 1.0))


def _local_departure_rows(
    *,
    time_str: str,
    wind_rows: list[dict[str, Any]],
    calibration: dict[str, Any],
    radius_xy: int,
    radius_z: int,
    sigma_xy: float,
    sigma_z: float,
    min_neighbors: int,
) -> list[dict[str, Any]]:
    if len(wind_rows) < 2:
        return []
    z = np.asarray([_safe_int(row.get("z"), -1) for row in wind_rows], dtype=np.float64)
    y = np.asarray([_safe_int(row.get("y"), -1) for row in wind_rows], dtype=np.float64)
    x = np.asarray([_safe_int(row.get("x"), -1) for row in wind_rows], dtype=np.float64)
    u = np.asarray([_safe_float(row.get("u"), np.nan) for row in wind_rows], dtype=np.float64)
    v = np.asarray([_safe_float(row.get("v"), np.nan) for row in wind_rows], dtype=np.float64)
    obs_conf = np.asarray([max(0.0, _safe_float(row.get("obs_conf"), 1.0)) for row in wind_rows], dtype=np.float64)
    time_conf = np.asarray([_row_time_conf(row, str(row.get("source_role"))) for row in wind_rows], dtype=np.float64)
    valid = (z >= 0) & (y >= 0) & (x >= 0) & np.isfinite(u) & np.isfinite(v)

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(wind_rows):
        if not bool(valid[idx]):
            continue
        dz = z - z[idx]
        dy = y - y[idx]
        dx = x - x[idx]
        mask = (
            valid
            & (np.arange(len(wind_rows)) != idx)
            & (np.abs(dz) <= float(radius_z))
            & (np.abs(dy) <= float(radius_xy))
            & (np.abs(dx) <= float(radius_xy))
        )
        if int(np.count_nonzero(mask)) < int(min_neighbors):
            continue
        loc = np.exp(-0.5 * ((dx / max(1e-6, sigma_xy)) ** 2 + (dy / max(1e-6, sigma_xy)) ** 2 + (dz / max(1e-6, sigma_z)) ** 2))
        weights = np.where(mask, loc * np.maximum(obs_conf, 0.05) * np.maximum(time_conf, 0.05), 0.0)
        weight_sum = float(np.sum(weights))
        if weight_sum <= 0.0:
            continue
        pred_u = float(np.sum(u * weights) / weight_sum)
        pred_v = float(np.sum(v * weights) / weight_sum)
        departure = float(math.sqrt((float(u[idx]) - pred_u) ** 2 + (float(v[idx]) - pred_v) ** 2))
        labels = _obs_error_feature_labels(row, calibration)
        out.append(
            {
                "time_str": time_str,
                "source_role": str(row.get("source_role")),
                "z": int(z[idx]),
                "y": int(y[idx]),
                "x": int(x[idx]),
                "u": float(u[idx]),
                "v": float(v[idx]),
                "obs_conf": float(obs_conf[idx]),
                "time_conf": float(time_conf[idx]),
                "neighbor_count": int(np.count_nonzero(mask)),
                "neighbor_weight_sum": weight_sum,
                "local_pred_u": pred_u,
                "local_pred_v": pred_v,
                "departure_vector_mps": departure,
                "obs_error_bin_key": _obs_error_composite_key(labels),
                "altitude_bin": labels["altitude"],
                "speed_bin": labels["speed"],
                "density_bin": labels["density"],
                "consistency_bin": labels["consistency"],
                "qc_flags": str(row.get("qc_flags", "ok") or "ok"),
            }
        )
    return out


def _group_values(rows: list[dict[str, Any]], key: str) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(str(row[key]), []).append(float(row["departure_vector_mps"]))
    return grouped


def _sigma_map(grouped: dict[str, list[float]], *, min_count: int, floor: float, cap: float) -> tuple[dict[str, float], dict[str, int]]:
    sigmas: dict[str, float] = {}
    counts: dict[str, int] = {}
    for key, values in sorted(grouped.items()):
        counts[key] = len(values)
        if len(values) < int(min_count):
            continue
        sigma = _robust_sigma(values, floor=floor, cap=cap)
        if sigma is not None:
            sigmas[key] = sigma
    return sigmas, counts


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    preferred = [
        "time_str",
        "source_role",
        "z",
        "y",
        "x",
        "obs_conf",
        "time_conf",
        "neighbor_count",
        "departure_vector_mps",
        "obs_error_bin_key",
        "altitude_bin",
        "speed_bin",
        "density_bin",
        "consistency_bin",
    ]
    for key in preferred:
        if any(key in row for row in rows):
            fieldnames.append(key)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_md(path: Path, calibration: dict[str, Any], sample_csv: Path) -> None:
    global_stats = calibration["obs_error_global_departure_stats"]
    lines = [
        "# Stage4 Aircraft Observation-Error Calibration",
        "",
        "This calibration is built from non-holdout aircraft wind records only. For every frame, the deterministic Stage4 holdout split is applied first; selected holdout records are excluded before local neighbor consistency is measured.",
        "",
        "## Summary",
        "",
        f"- generated UTC: `{calibration['generated_at_utc']}`",
        f"- frames selected: `{calibration['frames_selected']}`",
        f"- frames used with departures: `{calibration['frames_with_departures']}`",
        f"- departure samples: `{global_stats['count']}`",
        f"- global robust sigma: `{calibration['obs_error_sigma_default_mps']:.6f}` m/s",
        f"- reference sigma: `{calibration['obs_error_reference_sigma_mps']:.6f}` m/s",
        f"- sample CSV: `{sample_csv}`",
        "",
        "## Leakage Guard",
        "",
        "- Official truth remains current aircraft wind holdout only.",
        "- Holdout records are removed before calibration samples are produced.",
        "- Context/current non-holdout aircraft winds can estimate observation-error bins.",
        "- CMA/GFS/ERA and radar intensity are not used as labels in this calibration.",
        "",
        "## Global Departure Stats",
        "",
        "| metric | value |",
        "| --- | ---: |",
    ]
    for key, value in global_stats.items():
        if value is None:
            lines.append(f"| `{key}` |  |")
        else:
            lines.append(f"| `{key}` | {float(value):.6f} |")
    lines.extend(["", "## Literature", ""])
    for ref in REFERENCES:
        lines.append(f"- {ref['topic']}: {ref['url']}  ")
        lines.append(f"  Use here: {ref['why']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Stage4 obs_error_weighted calibration from non-holdout aircraft winds.")
    parser.add_argument("--stage2-summary", type=Path, default=REGENERATED_STAGE2_OUTPUT_DIR / "stage2_multimodal_summary.json")
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=20260531)
    parser.add_argument("--holdout-fraction", type=float, default=0.125)
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--neighbor-radius-xy", type=int, default=8)
    parser.add_argument("--neighbor-radius-z", type=int, default=2)
    parser.add_argument("--neighbor-sigma-xy", type=float, default=4.0)
    parser.add_argument("--neighbor-sigma-z", type=float, default=1.0)
    parser.add_argument("--min-neighbors", type=int, default=2)
    parser.add_argument("--min-bin-count", type=int, default=20)
    parser.add_argument("--min-marginal-bin-count", type=int, default=10)
    parser.add_argument("--sigma-floor-mps", type=float, default=1.0)
    parser.add_argument("--sigma-cap-mps", type=float, default=80.0)
    parser.add_argument("--weight-min", type=float, default=0.05)
    parser.add_argument("--weight-max", type=float, default=4.0)
    parser.add_argument("--disable-diagnostic-factor", action="store_true")
    args = parser.parse_args()

    frame_times = _frame_times_from_args(str(args.frame_times), args.frame_times_file)
    stage2_rows = _sample_rows(_select_rows(_load_json(args.stage2_summary), frame_times), int(args.sample_count), int(args.sample_seed))
    calibration = dict(DEFAULT_QC_CALIBRATION)
    calibration.update(
        {
            "calibration_role": "aircraft_obs_error_leave_one_local_neighbor_consistency",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "stage2_summary": str(args.stage2_summary),
            "frame_times_file": str(args.frame_times_file or ""),
            "frames_selected": int(len(stage2_rows)),
            "holdout_fraction": float(args.holdout_fraction),
            "holdout_count": int(args.holdout_count),
            "strict_holdout_excluded_from_calibration": True,
            "neighbor_radius_xy": int(args.neighbor_radius_xy),
            "neighbor_radius_z": int(args.neighbor_radius_z),
            "neighbor_sigma_xy": float(args.neighbor_sigma_xy),
            "neighbor_sigma_z": float(args.neighbor_sigma_z),
            "min_neighbors": int(args.min_neighbors),
            "obs_error_sigma_floor_mps": float(args.sigma_floor_mps),
            "obs_error_weight_min": float(args.weight_min),
            "obs_error_weight_max": float(args.weight_max),
            "obs_error_use_diagnostic_factor": 0.0 if args.disable_diagnostic_factor else 1.0,
            "references": [ref["url"] for ref in REFERENCES],
        }
    )

    sample_rows: list[dict[str, Any]] = []
    frames_with_departures = 0
    excluded_holdouts = 0
    for stage2_row in stage2_rows:
        npz = _load_stage2_npz(Path(stage2_row["multimodal_vox_path"]))
        _ = tuple(int(v) for v in np.asarray(npz[C2_GRID_SHAPE], dtype=np.int32).tolist())
        current_wind = _records(npz.get(C2_WIND_RECORDS))
        context_wind = _records(npz.get(C2_CONTEXT_WIND_RECORDS))
        train_current, holdout = _split_holdout(current_wind, float(args.holdout_fraction), int(args.holdout_count))
        excluded_holdouts += len(holdout)
        rows: list[dict[str, Any]] = []
        for row in train_current:
            item = dict(row)
            item["source_role"] = "current_wind_train"
            rows.append(item)
        for row in context_wind:
            item = dict(row)
            item["source_role"] = "context_wind"
            rows.append(item)
        departures = _local_departure_rows(
            time_str=str(stage2_row["time_str"]),
            wind_rows=rows,
            calibration=calibration,
            radius_xy=int(args.neighbor_radius_xy),
            radius_z=int(args.neighbor_radius_z),
            sigma_xy=float(args.neighbor_sigma_xy),
            sigma_z=float(args.neighbor_sigma_z),
            min_neighbors=int(args.min_neighbors),
        )
        if departures:
            frames_with_departures += 1
            sample_rows.extend(departures)

    departures = [float(row["departure_vector_mps"]) for row in sample_rows]
    default_sigma = _robust_sigma(departures, floor=float(args.sigma_floor_mps), cap=float(args.sigma_cap_mps))
    if default_sigma is None:
        default_sigma = float(DEFAULT_QC_CALIBRATION["obs_error_sigma_default_mps"])
    reference_sigma = float(np.clip(default_sigma, float(args.sigma_floor_mps), float(args.sigma_cap_mps)))

    composite_sigmas, composite_counts = _sigma_map(
        _group_values(sample_rows, "obs_error_bin_key"),
        min_count=int(args.min_bin_count),
        floor=float(args.sigma_floor_mps),
        cap=float(args.sigma_cap_mps),
    )
    altitude_sigmas, altitude_counts = _sigma_map(
        _group_values(sample_rows, "altitude_bin"),
        min_count=int(args.min_marginal_bin_count),
        floor=float(args.sigma_floor_mps),
        cap=float(args.sigma_cap_mps),
    )
    speed_sigmas, speed_counts = _sigma_map(
        _group_values(sample_rows, "speed_bin"),
        min_count=int(args.min_marginal_bin_count),
        floor=float(args.sigma_floor_mps),
        cap=float(args.sigma_cap_mps),
    )
    density_sigmas, density_counts = _sigma_map(
        _group_values(sample_rows, "density_bin"),
        min_count=int(args.min_marginal_bin_count),
        floor=float(args.sigma_floor_mps),
        cap=float(args.sigma_cap_mps),
    )
    consistency_sigmas, consistency_counts = _sigma_map(
        _group_values(sample_rows, "consistency_bin"),
        min_count=int(args.min_marginal_bin_count),
        floor=float(args.sigma_floor_mps),
        cap=float(args.sigma_cap_mps),
    )

    calibration.update(
        {
            "frames_with_departures": int(frames_with_departures),
            "holdout_records_excluded": int(excluded_holdouts),
            "departure_samples": int(len(sample_rows)),
            "obs_error_sigma_default_mps": float(default_sigma),
            "obs_error_reference_sigma_mps": float(reference_sigma),
            "obs_error_global_departure_stats": _stats(departures),
            "obs_error_bin_sigma_mps": composite_sigmas,
            "obs_error_bin_counts": composite_counts,
            "obs_error_altitude_bin_sigma_mps": altitude_sigmas,
            "obs_error_altitude_bin_counts": altitude_counts,
            "obs_error_speed_bin_sigma_mps": speed_sigmas,
            "obs_error_speed_bin_counts": speed_counts,
            "obs_error_density_bin_sigma_mps": density_sigmas,
            "obs_error_density_bin_counts": density_counts,
            "obs_error_consistency_bin_sigma_mps": consistency_sigmas,
            "obs_error_consistency_bin_counts": consistency_counts,
        }
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "stage4_aircraft_obs_error_calibration.json"
    md_path = args.out_dir / "stage4_aircraft_obs_error_calibration.md"
    sample_csv = args.out_dir / "stage4_aircraft_obs_error_calibration_samples.csv"
    json_path.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(sample_csv, sample_rows)
    _write_md(md_path, calibration, sample_csv)
    print(json_path)


if __name__ == "__main__":
    main()
