"""Replay conservative Stage5 field-v2 gates on field-v1 holdout deltas.

This is a fast gate-only screening tool. It does not rebuild full 3D fields.
It reuses the already computed field-v1 point departures, applies stricter
truth-free suppressors/scales to the observed Stage5 holdout deltas, writes
Stage4-compatible candidate CSVs, and optionally runs the formal pairwise
checklist for each replay variant.
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[3]


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


def _to_bool(row: dict[str, Any], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"true", "1", "yes"}


def _point_key(row: dict[str, Any]) -> tuple[str, int, int, int]:
    return (
        str(row.get("time_str", "")),
        _to_int(row, "z"),
        _to_int(row, "y"),
        _to_int(row, "x"),
    )


def _variant_name(*, alt12_scale: float, cap: float, support_risk: bool, clean_suppress: bool) -> str:
    alt_tag = "alt12_" + ("off" if alt12_scale == 0.0 else str(alt12_scale).replace(".", "p"))
    cap_tag = "cap" + str(cap).replace(".", "p")
    risk_tag = "riskreq" if support_risk else "riskoff"
    clean_tag = "cleansup" if clean_suppress else "cleanoff"
    return f"{alt_tag}_{cap_tag}_{risk_tag}_{clean_tag}"


def _support_risk(row: dict[str, Any]) -> bool:
    return (
        _to_float(row, "nearest_train_distance_vox", 999.0) > 4.0
        or _to_int(row, "nearest_current_count", 0) <= 0
        or _to_float(row, "nearest_role_gap_mps", 0.0) >= 20.0
    )


def _clean_supported(row: dict[str, Any]) -> bool:
    return (
        _to_float(row, "recon_confidence", 0.0) >= 0.8
        and _to_float(row, "nearest_train_distance_vox", 999.0) <= 2.5
        and _to_int(row, "nearest_current_count", 0) >= 1
        and _to_float(row, "nearest_role_gap_mps", 999.0) < 20.0
    )


def _apply_variant_to_points(
    baseline_points: list[dict[str, Any]],
    field_v1_points: list[dict[str, Any]],
    *,
    variant: str,
    alt12_scale: float,
    cap: float,
    support_risk: bool,
    clean_suppress: bool,
) -> list[dict[str, Any]]:
    field_v1 = {_point_key(row): row for row in field_v1_points}
    out: list[dict[str, Any]] = []
    for base in baseline_points:
        key = _point_key(base)
        cand1 = field_v1.get(key)
        if cand1 is None:
            raise ValueError(f"field-v1 point missing for key={key}")
        base_u = _to_float(base, "pred_u")
        base_v = _to_float(base, "pred_v")
        du = _to_float(cand1, "pred_u") - base_u
        dv = _to_float(cand1, "pred_v") - base_v
        residual_norm = math.sqrt(du * du + dv * dv)
        changed_v1 = residual_norm > 1.0e-8

        enabled = changed_v1
        if support_risk and not _support_risk(base):
            enabled = False
        if clean_suppress and _clean_supported(base):
            enabled = False

        scale = 1.0
        if _to_float(base, "alt_m", 0.0) >= 12000.0:
            scale *= float(alt12_scale)
        if cap > 0.0 and residual_norm > cap:
            scale *= float(cap) / max(residual_norm, 1.0e-12)
        if not enabled:
            scale = 0.0

        pred_u = base_u + scale * du
        pred_v = base_v + scale * dv
        gt_u = _to_float(base, "gt_u")
        gt_v = _to_float(base, "gt_v")
        u_error = pred_u - gt_u
        v_error = pred_v - gt_v
        vector_error = math.sqrt(u_error * u_error + v_error * v_error)
        pred_speed = math.sqrt(pred_u * pred_u + pred_v * pred_v)
        gt_speed = _to_float(base, "gt_speed", math.sqrt(gt_u * gt_u + gt_v * gt_v))

        row = dict(base)
        row.update(
            {
                "pred_u": pred_u,
                "pred_v": pred_v,
                "pred_speed": pred_speed,
                "u_error": u_error,
                "v_error": v_error,
                "abs_u_error": abs(u_error),
                "abs_v_error": abs(v_error),
                "vector_error": vector_error,
                "error_to_truth_speed_ratio": vector_error / max(gt_speed, 1.0e-6),
                "stage5_v2_replay_variant": variant,
                "stage5_v1_residual_u": du,
                "stage5_v1_residual_v": dv,
                "stage5_v1_residual_norm": residual_norm,
                "stage5_v2_replay_enabled": bool(enabled and scale > 0.0),
                "stage5_v2_replay_scale": scale,
                "stage5_v2_alt12_scale": alt12_scale,
                "stage5_v2_cap_mps": cap,
                "stage5_v2_support_risk_required": bool(support_risk),
                "stage5_v2_clean_suppress": bool(clean_suppress),
            }
        )
        out.append(row)
    return out


def _frame_metrics(points: list[dict[str, Any]]) -> dict[str, float]:
    if not points:
        return {"rmse_vector": 0.0, "mae_vector": 0.0, "bias_u": 0.0, "bias_v": 0.0}
    vec = np.asarray([_to_float(row, "vector_error") for row in points], dtype=np.float64)
    u_err = np.asarray([_to_float(row, "u_error") for row in points], dtype=np.float64)
    v_err = np.asarray([_to_float(row, "v_error") for row in points], dtype=np.float64)
    return {
        "rmse_vector": float(np.sqrt(np.mean(vec**2))),
        "mae_vector": float(np.mean(vec)),
        "bias_u": float(np.mean(u_err)),
        "bias_v": float(np.mean(v_err)),
    }


def _make_frame_rows(
    baseline_frames: list[dict[str, Any]],
    candidate_points: list[dict[str, Any]],
    *,
    variant: str,
) -> list[dict[str, Any]]:
    frame_lookup = {str(row.get("time_str")): row for row in baseline_frames}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_points:
        grouped.setdefault(str(row.get("time_str")), []).append(row)
    out: list[dict[str, Any]] = []
    for time_str in sorted(grouped):
        base_frame = dict(frame_lookup[time_str])
        metrics = _frame_metrics(grouped[time_str])
        base_frame.update(metrics)
        base_frame["stage5_field_label"] = "tp26_residual_pinn_field_v2_replay"
        base_frame["stage5_v2_replay_variant"] = variant
        base_frame["holdout_wind_records"] = len(grouped[time_str])
        base_frame["strict_holdout_no_leakage"] = True
        base_frame["motion_used_as_wind"] = False
        out.append(base_frame)
    return out


def _read_checklist(path: Path) -> dict[str, Any]:
    rows = _read_csv(path)
    out: dict[str, Any] = {}
    for row in rows:
        gate = str(row.get("gate", ""))
        out[f"{gate}_passed"] = str(row.get("passed", "")).lower() == "true"
        out[f"{gate}_baseline"] = row.get("baseline_value", "")
        out[f"{gate}_candidate"] = row.get("candidate_value", "")
    return out


def _run_pairwise(
    *,
    baseline_frame_csv: Path,
    baseline_point_csv: Path,
    candidate_frame_csv: Path,
    candidate_point_csv: Path,
    out_dir: Path,
    prefix: str,
    python_bin: str,
) -> Path:
    cmd = [
        python_bin,
        "stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py",
        "--baseline-csv",
        str(baseline_frame_csv),
        "--candidate-csv",
        str(candidate_frame_csv),
        "--baseline-point-csv",
        str(baseline_point_csv),
        "--candidate-point-csv",
        str(candidate_point_csv),
        "--baseline-label",
        "tp26_thr11_preserve",
        "--candidate-label",
        "stage5_field_v2_replay",
        "--out-dir",
        str(out_dir),
        "--out-prefix",
        prefix,
        "--top-n",
        "30",
    ]
    subprocess.run(cmd, cwd=str(ROOT_DIR), check=True)
    return out_dir / f"{prefix}_promotion_checklist.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay conservative Stage5 field-v2 gate sweeps from field-v1 point deltas.")
    parser.add_argument("--baseline-frame-csv", type=Path, required=True)
    parser.add_argument("--baseline-point-csv", type=Path, required=True)
    parser.add_argument("--field-v1-point-csv", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--run-pairwise", action="store_true")
    args = parser.parse_args()

    baseline_frames = _read_csv(args.baseline_frame_csv)
    baseline_points = _read_csv(args.baseline_point_csv)
    field_v1_points = _read_csv(args.field_v1_point_csv)

    alt12_scales = [1.0, 0.5, 0.25, 0.0]
    caps = [10.0, 1.0, 0.75, 0.5]
    support_options = [False, True]
    clean_options = [False, True]

    summary_rows: list[dict[str, Any]] = []
    for alt12_scale in alt12_scales:
        for cap in caps:
            for support_risk in support_options:
                for clean_suppress in clean_options:
                    variant = _variant_name(
                        alt12_scale=alt12_scale,
                        cap=cap,
                        support_risk=support_risk,
                        clean_suppress=clean_suppress,
                    )
                    variant_dir = args.out_root / "variants" / variant
                    candidate_points = _apply_variant_to_points(
                        baseline_points,
                        field_v1_points,
                        variant=variant,
                        alt12_scale=alt12_scale,
                        cap=cap,
                        support_risk=support_risk,
                        clean_suppress=clean_suppress,
                    )
                    candidate_frames = _make_frame_rows(baseline_frames, candidate_points, variant=variant)
                    frame_csv = variant_dir / "stage4_localization_sensitivity.csv"
                    point_csv = variant_dir / "stage4_point_departures.csv"
                    _write_csv(frame_csv, candidate_frames)
                    _write_csv(point_csv, candidate_points)

                    changed_points = sum(1 for row in candidate_points if _to_bool(row, "stage5_v2_replay_enabled"))
                    worsened_good = sum(
                        1
                        for base, cand in zip(baseline_points, candidate_points)
                        if _to_float(base, "vector_error") < 5.0
                        and _to_float(cand, "vector_error") > _to_float(base, "vector_error") + 1.0e-9
                    )
                    row: dict[str, Any] = {
                        "variant": variant,
                        "alt12_scale": alt12_scale,
                        "cap": cap,
                        "support_risk_required": bool(support_risk),
                        "clean_suppress": bool(clean_suppress),
                        "changed_points": changed_points,
                        "worsened_baseline_error_lt5_points": worsened_good,
                        "candidate_frame_csv": str(frame_csv),
                        "candidate_point_csv": str(point_csv),
                    }
                    if args.run_pairwise:
                        pairwise_dir = variant_dir / "pairwise"
                        checklist = _run_pairwise(
                            baseline_frame_csv=args.baseline_frame_csv,
                            baseline_point_csv=args.baseline_point_csv,
                            candidate_frame_csv=frame_csv,
                            candidate_point_csv=point_csv,
                            out_dir=pairwise_dir,
                            prefix=variant,
                            python_bin=str(args.python_bin),
                        )
                        row.update(_read_checklist(checklist))
                        row["pairwise_dir"] = str(pairwise_dir)
                    summary_rows.append(row)

    args.out_root.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out_root / "field_v2_replay_sweep_summary.csv", summary_rows)
    passed = [
        row
        for row in summary_rows
        if str(row.get("PROMOTION_OVERALL_passed", "")).lower() == "true"
        or row.get("PROMOTION_OVERALL_passed") is True
    ]
    lines = [
        "# Stage5 Field V2 Replay Sweep",
        "",
        "This is a gate-only replay from field-v1 holdout deltas. It is a screening step, not a rebuilt full-field candidate.",
        "",
        f"- variants: `{len(summary_rows)}`",
        f"- promotion-pass variants: `{len(passed)}`",
        "",
        "| variant | changed points | alt12 scale | cap | support risk | clean suppress | promotion | weighted RMSE candidate | 12km+ candidate |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: |",
    ]
    for row in summary_rows:
        promo = "PASS" if row.get("PROMOTION_OVERALL_passed") is True else "FAIL"
        lines.append(
            f"| `{row['variant']}` | {int(row['changed_points'])} | {float(row['alt12_scale']):.2f} | "
            f"{float(row['cap']):.2f} | `{row['support_risk_required']}` | `{row['clean_suppress']}` | "
            f"`{promo}` | `{row.get('weighted_rmse_no_worse_candidate', '')}` | "
            f"`{row.get('alt_12km_plus_vector_rmse_no_worse_candidate', '')}` |"
        )
    (args.out_root / "field_v2_replay_sweep_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.out_root / "field_v2_replay_sweep_report.md")


if __name__ == "__main__":
    main()
