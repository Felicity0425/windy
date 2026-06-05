"""Wind-scale impact analysis for Stage4 point departures.

This report complements absolute RMSE/MSE with truth-speed-normalized and
direction-aware diagnostics. It is strict-evaluation reporting only: it reads
point departure CSVs and does not affect reconstruction.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np


SPEED_BINS: list[tuple[float | None, float | None, str]] = [
    (0.0, 5.0, "0-5mps_calm"),
    (5.0, 15.0, "5-15mps_light"),
    (15.0, 30.0, "15-30mps_moderate"),
    (30.0, 60.0, "30-60mps_strong"),
    (60.0, None, "60mps_plus_extreme"),
]
SPEED_BIN_ORDER = {label: idx for idx, (_, _, label) in enumerate(SPEED_BINS)}
ALTITUDE_BIN_ORDER = {"0-3km": 0, "3-6km": 1, "6-9km": 2, "9-12km": 3, "12km+": 4}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _to_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _to_int(row: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def _point_key(row: dict[str, Any]) -> tuple[str, int, int, int]:
    return str(row.get("time_str", "")), _to_int(row, "z"), _to_int(row, "y"), _to_int(row, "x")


def _bin(value: float, edges: list[tuple[float | None, float | None, str]]) -> str:
    for lo, hi, label in edges:
        if lo is not None and value < lo:
            continue
        if hi is not None and value >= hi:
            continue
        return label
    return "unknown"


def _altitude_bin(alt_m: float) -> str:
    if alt_m < 3000.0:
        return "0-3km"
    if alt_m < 6000.0:
        return "3-6km"
    if alt_m < 9000.0:
        return "6-9km"
    if alt_m < 12000.0:
        return "9-12km"
    return "12km+"


def _vector_angle_deg(u: float, v: float) -> float:
    return math.degrees(math.atan2(v, u))


def _angle_error_deg(gt_u: float, gt_v: float, pred_u: float, pred_v: float, gt_speed: float, pred_speed: float) -> float:
    if gt_speed < 5.0 or pred_speed < 1.0:
        return float("nan")
    delta = (_vector_angle_deg(pred_u, pred_v) - _vector_angle_deg(gt_u, gt_v) + 180.0) % 360.0 - 180.0
    return abs(delta)


def _finite(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    return arr[np.isfinite(arr)]


def _percentile(values: list[float], q: float) -> float:
    arr = _finite(values)
    return float(np.percentile(arr, q)) if arr.size else float("nan")


def _mean(values: list[float]) -> float:
    arr = _finite(values)
    return float(np.mean(arr)) if arr.size else float("nan")


def _rmse(values: list[float]) -> float:
    arr = _finite(values)
    return float(np.sqrt(np.mean(arr**2))) if arr.size else float("nan")


def _mse(values: list[float]) -> float:
    arr = _finite(values)
    return float(np.mean(arr**2)) if arr.size else float("nan")


def _fmt(value: Any, digits: int = 6) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(f):
        return ""
    return f"{f:.{digits}f}"


def _method_metrics(rows: list[dict[str, Any]], label: str, group: str) -> dict[str, Any]:
    vec = [_to_float(row, f"{label}_vector_error_mps") for row in rows]
    rel = [_to_float(row, f"{label}_relative_error_ratio") for row in rows]
    floor10 = [_to_float(row, f"{label}_floor10_relative_error") for row in rows]
    direction = [_to_float(row, f"{label}_direction_error_deg", float("nan")) for row in rows]
    gt_speed = [_to_float(row, "gt_speed_mps") for row in rows]
    pred_speed = [_to_float(row, f"{label}_pred_speed_mps") for row in rows]
    return {
        "group": group,
        "method": label,
        "points": len(rows),
        "gt_speed_mean_mps": _mean(gt_speed),
        "pred_speed_mean_mps": _mean(pred_speed),
        "vector_mse_mps2": _mse(vec),
        "vector_rmse_mps": _rmse(vec),
        "vector_mae_mps": _mean(vec),
        "p90_vector_error_mps": _percentile(vec, 90.0),
        "p95_vector_error_mps": _percentile(vec, 95.0),
        "p99_vector_error_mps": _percentile(vec, 99.0),
        "max_vector_error_mps": float(np.max(_finite(vec))) if _finite(vec).size else float("nan"),
        "relative_error_mae": _mean(rel),
        "relative_error_p95": _percentile(rel, 95.0),
        "floor10_relative_error_mae": _mean(floor10),
        "floor10_relative_error_p95": _percentile(floor10, 95.0),
        "direction_error_valid_points": int(_finite(direction).size),
        "direction_error_mae_deg": _mean(direction),
        "direction_error_p95_deg": _percentile(direction, 95.0),
    }


def _delta_metrics(rows: list[dict[str, Any]], baseline_label: str, candidate_label: str, group: str) -> dict[str, Any]:
    delta = [_to_float(row, "delta_candidate_minus_baseline_vector_error_mps") for row in rows]
    rel_delta = [_to_float(row, "delta_candidate_minus_baseline_floor10_relative_error") for row in rows]
    return {
        "group": group,
        "points": len(rows),
        "mean_delta_vector_error_mps": _mean(delta),
        "median_delta_vector_error_mps": float(np.median(_finite(delta))) if _finite(delta).size else float("nan"),
        "p90_delta_vector_error_mps": _percentile(delta, 90.0),
        "max_delta_vector_error_mps": float(np.max(_finite(delta))) if _finite(delta).size else float("nan"),
        "mean_delta_floor10_relative_error": _mean(rel_delta),
        "candidate_worse_gt5mps_points": sum(1 for value in delta if value > 5.0),
        "candidate_better_gt5mps_points": sum(1 for value in delta if value < -5.0),
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
    }


def _merge_rows(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
) -> list[dict[str, Any]]:
    baseline = {_point_key(row): row for row in baseline_rows if str(row.get("time_str", ""))}
    candidate = {_point_key(row): row for row in candidate_rows if str(row.get("time_str", ""))}
    common = sorted(set(baseline) & set(candidate))
    merged: list[dict[str, Any]] = []
    for key in common:
        base = baseline[key]
        cand = candidate[key]
        gt_u = _to_float(base, "gt_u", _to_float(cand, "gt_u"))
        gt_v = _to_float(base, "gt_v", _to_float(cand, "gt_v"))
        gt_speed = _to_float(base, "gt_speed", math.sqrt(gt_u**2 + gt_v**2))
        alt_m = _to_float(base, "alt_m", _to_float(cand, "alt_m"))
        out: dict[str, Any] = {
            "time_str": key[0],
            "z": key[1],
            "y": key[2],
            "x": key[3],
            "lat": _to_float(base, "lat", _to_float(cand, "lat")),
            "lon": _to_float(base, "lon", _to_float(cand, "lon")),
            "alt_m": alt_m,
            "altitude_bin": _altitude_bin(alt_m),
            "gt_u": gt_u,
            "gt_v": gt_v,
            "gt_speed_mps": gt_speed,
            "truth_speed_bin": _bin(gt_speed, SPEED_BINS),
            "nearest_train_source_role": cand.get("nearest_train_source_role", base.get("nearest_train_source_role", "")),
            "nearest_current_count": _to_int(cand, "nearest_current_count", _to_int(base, "nearest_current_count")),
            "nearest_context_count": _to_int(cand, "nearest_context_count", _to_int(base, "nearest_context_count")),
            "nearest_role_gap_mps": _to_float(cand, "nearest_role_gap_mps", _to_float(base, "nearest_role_gap_mps")),
            "nearest_train_distance_vox": _to_float(cand, "nearest_train_distance_vox", _to_float(base, "nearest_train_distance_vox")),
            "strict_holdout_no_leakage": str(cand.get("strict_holdout_no_leakage", base.get("strict_holdout_no_leakage", ""))),
            "motion_used_as_wind": str(cand.get("motion_used_as_wind", base.get("motion_used_as_wind", ""))),
        }
        for label, row in [(baseline_label, base), (candidate_label, cand)]:
            pred_u = _to_float(row, "pred_u")
            pred_v = _to_float(row, "pred_v")
            pred_speed = _to_float(row, "pred_speed", math.sqrt(pred_u**2 + pred_v**2))
            vec_error = _to_float(row, "vector_error", math.sqrt(_to_float(row, "u_error") ** 2 + _to_float(row, "v_error") ** 2))
            out[f"{label}_pred_u"] = pred_u
            out[f"{label}_pred_v"] = pred_v
            out[f"{label}_pred_speed_mps"] = pred_speed
            out[f"{label}_vector_error_mps"] = vec_error
            out[f"{label}_relative_error_ratio"] = vec_error / max(gt_speed, 1e-6)
            out[f"{label}_floor10_relative_error"] = vec_error / max(gt_speed, 10.0)
            out[f"{label}_direction_error_deg"] = _angle_error_deg(gt_u, gt_v, pred_u, pred_v, gt_speed, pred_speed)
            out[f"{label}_recon_confidence"] = _to_float(row, "recon_confidence")
        out["delta_candidate_minus_baseline_vector_error_mps"] = (
            out[f"{candidate_label}_vector_error_mps"] - out[f"{baseline_label}_vector_error_mps"]
        )
        out["delta_candidate_minus_baseline_floor10_relative_error"] = (
            out[f"{candidate_label}_floor10_relative_error"] - out[f"{baseline_label}_floor10_relative_error"]
        )
        merged.append(out)
    return merged


def _group_rows(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(key_fn(row), []).append(row)
    return groups


def _summary_rows(rows: list[dict[str, Any]], baseline_label: str, candidate_label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    method_rows: list[dict[str, Any]] = []
    delta_rows: list[dict[str, Any]] = []
    group_sets: list[tuple[str, dict[str, list[dict[str, Any]]]]] = [
        ("all", {"all_holdout_points": rows}),
        ("speed", _group_rows(rows, lambda row: str(row["truth_speed_bin"]))),
        ("altitude", _group_rows(rows, lambda row: str(row["altitude_bin"]))),
    ]
    for group_type, groups in group_sets:
        if group_type == "speed":
            ordered_groups = sorted(groups.items(), key=lambda item: SPEED_BIN_ORDER.get(item[0], 999))
        elif group_type == "altitude":
            ordered_groups = sorted(groups.items(), key=lambda item: ALTITUDE_BIN_ORDER.get(item[0], 999))
        else:
            ordered_groups = sorted(groups.items())
        for group, selected in ordered_groups:
            for label in [baseline_label, candidate_label]:
                row = _method_metrics(selected, label, group)
                row["group_type"] = group_type
                method_rows.append(row)
            delta = _delta_metrics(selected, baseline_label, candidate_label, group)
            delta["group_type"] = group_type
            delta_rows.append(delta)
    return method_rows, delta_rows


def _top_rows(rows: list[dict[str, Any]], baseline_label: str, candidate_label: str, top_n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def trim(row: dict[str, Any], rank: int, reason: str) -> dict[str, Any]:
        return {
            "rank": rank,
            "reason": reason,
            "time_str": row["time_str"],
            "z": row["z"],
            "y": row["y"],
            "x": row["x"],
            "alt_m": row["alt_m"],
            "altitude_bin": row["altitude_bin"],
            "truth_speed_bin": row["truth_speed_bin"],
            "gt_speed_mps": row["gt_speed_mps"],
            f"{baseline_label}_pred_speed_mps": row[f"{baseline_label}_pred_speed_mps"],
            f"{candidate_label}_pred_speed_mps": row[f"{candidate_label}_pred_speed_mps"],
            f"{baseline_label}_vector_error_mps": row[f"{baseline_label}_vector_error_mps"],
            f"{candidate_label}_vector_error_mps": row[f"{candidate_label}_vector_error_mps"],
            "delta_candidate_minus_baseline_vector_error_mps": row["delta_candidate_minus_baseline_vector_error_mps"],
            f"{baseline_label}_relative_error_ratio": row[f"{baseline_label}_relative_error_ratio"],
            f"{candidate_label}_relative_error_ratio": row[f"{candidate_label}_relative_error_ratio"],
            f"{baseline_label}_floor10_relative_error": row[f"{baseline_label}_floor10_relative_error"],
            f"{candidate_label}_floor10_relative_error": row[f"{candidate_label}_floor10_relative_error"],
            f"{baseline_label}_direction_error_deg": row[f"{baseline_label}_direction_error_deg"],
            f"{candidate_label}_direction_error_deg": row[f"{candidate_label}_direction_error_deg"],
            "nearest_train_source_role": row["nearest_train_source_role"],
            "nearest_current_count": row["nearest_current_count"],
            "nearest_context_count": row["nearest_context_count"],
            "nearest_role_gap_mps": row["nearest_role_gap_mps"],
            "nearest_train_distance_vox": row["nearest_train_distance_vox"],
        }

    top_abs_source = sorted(rows, key=lambda row: float(row[f"{candidate_label}_vector_error_mps"]), reverse=True)[:top_n]
    top_worsen_source = sorted(rows, key=lambda row: float(row["delta_candidate_minus_baseline_vector_error_mps"]), reverse=True)[:top_n]
    top_abs = [trim(row, idx + 1, "candidate_top_abs_error") for idx, row in enumerate(top_abs_source)]
    top_worsen = [trim(row, idx + 1, "candidate_worst_delta") for idx, row in enumerate(top_worsen_source)]
    return top_abs, top_worsen


def _write_md(
    path: Path,
    *,
    baseline_label: str,
    candidate_label: str,
    merged_rows: list[dict[str, Any]],
    method_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    top_abs: list[dict[str, Any]],
    top_worsen: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    speed_method = [row for row in method_rows if row["group_type"] == "speed"]
    speed_delta = [row for row in delta_rows if row["group_type"] == "speed"]
    altitude_method = [row for row in method_rows if row["group_type"] == "altitude"]
    all_delta = next((row for row in delta_rows if row["group"] == "all_holdout_points"), {})
    leakage_values = sorted({str(row.get("strict_holdout_no_leakage", "")) for row in merged_rows})
    motion_values = sorted({str(row.get("motion_used_as_wind", "")) for row in merged_rows})
    lines = [
        "# Stage4 Wind-Scale Impact Analysis",
        "",
        f"Baseline: `{baseline_label}`",
        f"Candidate: `{candidate_label}`",
        "",
        "## Validation",
        "",
        f"- points: `{len(merged_rows)}`",
        f"- strict_holdout_no_leakage values: `{','.join(leakage_values)}`",
        f"- motion_used_as_wind values: `{','.join(motion_values)}`",
        "",
        "## Interpretation",
        "",
        "Absolute RMSE/MSE is not enough by itself. The same 8 m/s error has very different meaning in calm/light winds than in high-speed upper-level flow.",
        "`relative_error_ratio = vector_error / gt_speed`; `floor10_relative_error = vector_error / max(gt_speed, 10)` keeps calm-wind ratios from exploding.",
        "Direction error is excluded when `gt_speed < 5 m/s` or `pred_speed < 1 m/s` because wind direction is unstable near calm or zero predictions.",
        "",
    ]
    if all_delta:
        lines.extend(
            [
                "## Overall Delta",
                "",
                "| metric | value |",
                "| --- | ---: |",
                f"| mean delta vector error | {_fmt(all_delta.get('mean_delta_vector_error_mps'))} |",
                f"| median delta vector error | {_fmt(all_delta.get('median_delta_vector_error_mps'))} |",
                f"| candidate worse >5 m/s points | {all_delta.get('candidate_worse_gt5mps_points', '')} |",
                f"| candidate better >5 m/s points | {all_delta.get('candidate_better_gt5mps_points', '')} |",
                "",
            ]
        )
    lines.extend(
        [
            "## Truth-Speed Bins",
            "",
            "| speed bin | method | points | gt mean | vector MSE | vector RMSE | vector MAE | P95 | rel MAE | floor10 rel MAE | dir MAE |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in speed_method:
        lines.append(
            f"| `{row['group']}` | `{row['method']}` | {row['points']} | {_fmt(row['gt_speed_mean_mps'])} | "
            f"{_fmt(row['vector_mse_mps2'])} | {_fmt(row['vector_rmse_mps'])} | {_fmt(row['vector_mae_mps'])} | "
            f"{_fmt(row['p95_vector_error_mps'])} | {_fmt(row['relative_error_mae'])} | "
            f"{_fmt(row['floor10_relative_error_mae'])} | {_fmt(row['direction_error_mae_deg'], 2)} |"
        )
    lines.extend(
        [
            "",
            "## Candidate Delta By Truth Speed",
            "",
            "| speed bin | points | mean delta | median delta | worsen >5 | improve >5 | floor10 rel delta |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in speed_delta:
        lines.append(
            f"| `{row['group']}` | {row['points']} | {_fmt(row['mean_delta_vector_error_mps'])} | "
            f"{_fmt(row['median_delta_vector_error_mps'])} | {row['candidate_worse_gt5mps_points']} | "
            f"{row['candidate_better_gt5mps_points']} | {_fmt(row['mean_delta_floor10_relative_error'])} |"
        )
    lines.extend(
        [
            "",
            "## Altitude Bins",
            "",
            "| altitude bin | method | points | gt mean | vector MSE | vector RMSE | vector MAE | P95 | rel MAE | floor10 rel MAE | dir MAE |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in altitude_method:
        lines.append(
            f"| `{row['group']}` | `{row['method']}` | {row['points']} | {_fmt(row['gt_speed_mean_mps'])} | "
            f"{_fmt(row['vector_mse_mps2'])} | {_fmt(row['vector_rmse_mps'])} | {_fmt(row['vector_mae_mps'])} | "
            f"{_fmt(row['p95_vector_error_mps'])} | {_fmt(row['relative_error_mae'])} | "
            f"{_fmt(row['floor10_relative_error_mae'])} | {_fmt(row['direction_error_mae_deg'], 2)} |"
        )
    for title, rows in [("Candidate Top Absolute Errors", top_abs), ("Candidate Worst New Deltas", top_worsen)]:
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                "| rank | time | z/y/x | alt bin | truth speed bin | gt speed | baseline error | candidate error | delta | candidate rel | candidate dir | nearest/current/role gap |",
                "| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in rows[:10]:
            lines.append(
                f"| {row['rank']} | `{row['time_str']}` | `{row['z']}/{row['y']}/{row['x']}` | "
                f"`{row['altitude_bin']}` | `{row['truth_speed_bin']}` | {_fmt(row['gt_speed_mps'])} | "
                f"{_fmt(row[f'{baseline_label}_vector_error_mps'])} | {_fmt(row[f'{candidate_label}_vector_error_mps'])} | "
                f"{_fmt(row['delta_candidate_minus_baseline_vector_error_mps'])} | "
                f"{_fmt(row[f'{candidate_label}_relative_error_ratio'])} | "
                f"{_fmt(row[f'{candidate_label}_direction_error_deg'], 2)} | "
                f"`{row['nearest_train_source_role']}/count_{row['nearest_current_count']}/gap_{_fmt(row['nearest_role_gap_mps'], 1)}` |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-point-csv", type=Path, required=True)
    parser.add_argument("--candidate-point-csv", type=Path, required=True)
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-prefix", default="stage4_wind_scale_impact")
    parser.add_argument("--expected-points", type=int, default=0)
    parser.add_argument("--top-n", type=int, default=30)
    args = parser.parse_args()

    baseline_rows = _read_csv(args.baseline_point_csv)
    candidate_rows = _read_csv(args.candidate_point_csv)
    merged = _merge_rows(baseline_rows, candidate_rows, args.baseline_label, args.candidate_label)
    if args.expected_points > 0 and len(merged) != args.expected_points:
        raise ValueError(f"Expected {args.expected_points} aligned points, got {len(merged)}")
    leakage_values = {str(row.get("strict_holdout_no_leakage", "")) for row in merged}
    motion_values = {str(row.get("motion_used_as_wind", "")) for row in merged}
    if leakage_values != {"True"}:
        raise ValueError(f"strict_holdout_no_leakage is not all True: {sorted(leakage_values)}")
    if motion_values != {"False"}:
        raise ValueError(f"motion_used_as_wind is not all False: {sorted(motion_values)}")

    method_rows, delta_rows = _summary_rows(merged, args.baseline_label, args.candidate_label)
    top_abs, top_worsen = _top_rows(merged, args.baseline_label, args.candidate_label, args.top_n)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.out_prefix
    _write_csv(out_dir / f"{prefix}_merged_points.csv", merged)
    _write_csv(out_dir / f"{prefix}_method_groups.csv", method_rows)
    _write_csv(out_dir / f"{prefix}_delta_groups.csv", delta_rows)
    _write_csv(out_dir / f"{prefix}_top_candidate_abs_errors.csv", top_abs)
    _write_csv(out_dir / f"{prefix}_top_candidate_worsening.csv", top_worsen)
    _write_md(
        out_dir / f"{prefix}.md",
        baseline_label=args.baseline_label,
        candidate_label=args.candidate_label,
        merged_rows=merged,
        method_rows=method_rows,
        delta_rows=delta_rows,
        top_abs=top_abs,
        top_worsen=top_worsen,
    )
    print(out_dir / f"{prefix}.md")


if __name__ == "__main__":
    main()
