#!/usr/bin/env python3
"""Generate pointwise speed/direction departure table for current best S11 run."""

from __future__ import annotations

import csv
import math
from pathlib import Path


ROOT = Path("/data/LFT-W02_data/pengxu")
SRC = ROOT / "优化/数据处理/amdar_unified_stage13_stage4_source_ablation_20260702/experiments/S11_drop_context_speed_gt80_all/stage4_point_departures.csv"
OUT_DIR = ROOT / "优化/数据处理/amdar_unified_stage14_stage2_stage4_qc_superob_redesign_20260702"
CSV_OUT = OUT_DIR / "stage14_s11_pointwise_speed_direction_departures.csv"
MD_OUT = OUT_DIR / "stage14_s11_pointwise_speed_direction_departures.md"
ALT_RMSE_CSV_OUT = OUT_DIR / "stage14_s11_altitude_layer_rmse.csv"
FILTER_ALT_MAX_M = 12000.0


def speed(u: float, v: float) -> float:
    return math.hypot(u, v)


def wind_dir_from_deg(u: float, v: float) -> float:
    if speed(u, v) < 1e-9:
        return float("nan")
    return (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def circular_diff_deg(pred_dir: float, gt_dir: float) -> float:
    return ((pred_dir - gt_dir + 180.0) % 360.0) - 180.0


def percentile(values: list[float], q: float) -> float:
    vals = sorted(values)
    if not vals:
        return float("nan")
    k = (len(vals) - 1) * q / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return vals[int(k)]
    return vals[lo] * (hi - k) + vals[hi] * (k - lo)


def fmt(value: object, digits: int = 3) -> str:
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.{digits}f}"
    return str(value)


def load_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    excluded_above_alt = 0
    with SRC.open("r", encoding="utf-8", newline="") as f:
        idx = 0
        for raw in csv.DictReader(f):
            alt_m = float(raw.get("alt_m") or int(raw["z"]) * 500.0)
            if alt_m > FILTER_ALT_MAX_M:
                excluded_above_alt += 1
                continue
            idx += 1
            gt_u = float(raw["gt_u"])
            gt_v = float(raw["gt_v"])
            pred_u = float(raw["pred_u"])
            pred_v = float(raw["pred_v"])
            gt_speed = speed(gt_u, gt_v)
            pred_speed = speed(pred_u, pred_v)
            gt_dir = wind_dir_from_deg(gt_u, gt_v)
            pred_dir = wind_dir_from_deg(pred_u, pred_v)
            dir_diff = circular_diff_deg(pred_dir, gt_dir) if math.isfinite(gt_dir) and math.isfinite(pred_dir) else float("nan")
            rows.append(
                {
                    "idx": idx,
                    "time_str": raw["time_str"],
                    "z": int(raw["z"]),
                    "y": int(raw["y"]),
                    "x": int(raw["x"]),
                    "alt_m": alt_m,
                    "alt_km": alt_m / 1000.0,
                    "gt_u_mps": gt_u,
                    "gt_v_mps": gt_v,
                    "pred_u_mps": pred_u,
                    "pred_v_mps": pred_v,
                    "gt_speed_mps": gt_speed,
                    "pred_speed_mps": pred_speed,
                    "speed_diff_pred_minus_gt_mps": pred_speed - gt_speed,
                    "abs_speed_diff_mps": abs(pred_speed - gt_speed),
                    "gt_dir_from_deg": gt_dir,
                    "pred_dir_from_deg": pred_dir,
                    "dir_diff_pred_minus_gt_deg": dir_diff,
                    "abs_dir_diff_deg": abs(dir_diff) if math.isfinite(dir_diff) else float("nan"),
                    "vector_error_mps": math.hypot(pred_u - gt_u, pred_v - gt_v),
                    "direction_valid_gt_pred_ge5": bool(gt_speed >= 5.0 and pred_speed >= 5.0 and math.isfinite(dir_diff)),
                    "context_filter_policy": raw.get("context_filter_policy", ""),
                    "nearest_train_source_role": raw.get("nearest_train_source_role", ""),
                    "qc_review_flag": raw.get("qc_review_flag", ""),
                    "qc_review_reasons": raw.get("qc_review_reasons", ""),
                }
            )
    load_rows.excluded_above_alt = excluded_above_alt  # type: ignore[attr-defined]
    return rows


def write_csv(rows: list[dict[str, object]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def altitude_rmse_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[float, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(float(row["alt_km"]), []).append(row)
    out: list[dict[str, object]] = []
    for alt_km in sorted(grouped):
        items = grouped[alt_km]
        vector_error = [float(r["vector_error_mps"]) for r in items]
        speed_error = [float(r["speed_diff_pred_minus_gt_mps"]) for r in items]
        abs_speed_error = [float(r["abs_speed_diff_mps"]) for r in items]
        abs_dir_valid = [float(r["abs_dir_diff_deg"]) for r in items if bool(r["direction_valid_gt_pred_ge5"])]
        out.append(
            {
                "alt_km": alt_km,
                "alt_m": alt_km * 1000.0,
                "count": len(items),
                "vector_rmse_mps": math.sqrt(sum(v * v for v in vector_error) / len(vector_error)),
                "vector_mae_mps": sum(vector_error) / len(vector_error),
                "speed_rmse_mps": math.sqrt(sum(v * v for v in speed_error) / len(speed_error)),
                "speed_mae_mps": sum(abs_speed_error) / len(abs_speed_error),
                "speed_bias_pred_minus_gt_mps": sum(speed_error) / len(speed_error),
                "direction_valid_count": len(abs_dir_valid),
                "abs_direction_mean_deg_valid": sum(abs_dir_valid) / len(abs_dir_valid) if abs_dir_valid else float("nan"),
            }
        )
    return out


def write_altitude_rmse_csv(rows: list[dict[str, object]]) -> None:
    rmse_rows = altitude_rmse_rows(rows)
    fieldnames = list(rmse_rows[0].keys())
    with ALT_RMSE_CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rmse_rows)


def write_markdown(rows: list[dict[str, object]]) -> None:
    n = len(rows)
    speed_diff = [float(r["speed_diff_pred_minus_gt_mps"]) for r in rows]
    abs_speed_diff = [float(r["abs_speed_diff_mps"]) for r in rows]
    vector_error = [float(r["vector_error_mps"]) for r in rows]
    abs_dir_all = [float(r["abs_dir_diff_deg"]) for r in rows if math.isfinite(float(r["abs_dir_diff_deg"]))]
    abs_dir_valid = [float(r["abs_dir_diff_deg"]) for r in rows if bool(r["direction_valid_gt_pred_ge5"])]
    signed_dir_valid = [float(r["dir_diff_pred_minus_gt_deg"]) for r in rows if bool(r["direction_valid_gt_pred_ge5"])]

    lines = [
        "# S11 Strict-Holdout Pointwise Speed/Direction Departures",
        "",
        f"- Source CSV: `{SRC}`",
        f"- Output CSV: `{CSV_OUT}`",
        f"- Altitude filter: `alt_m <= {FILTER_ALT_MAX_M:.0f}`",
        f"- Rows after altitude filter: `{n}`",
        f"- Rows excluded above 12 km: `{getattr(load_rows, 'excluded_above_alt', 0)}`",
        f"- Altitude range after filter: `{min(float(r['alt_m']) for r in rows):.1f}` to `{max(float(r['alt_m']) for r in rows):.1f}` m",
        "",
        "## Formulas",
        "",
        "- `gt_speed = sqrt(gt_u^2 + gt_v^2)`",
        "- `pred_speed = sqrt(pred_u^2 + pred_v^2)`",
        "- `speed_diff_pred_minus_gt = pred_speed - gt_speed`",
        "- `abs_speed_diff = abs(speed_diff_pred_minus_gt)`",
        "- Meteorological from-direction: `dir_from_deg = (atan2(-u, -v) * 180 / pi + 360) mod 360`",
        "- Signed circular direction difference: `dir_diff = ((pred_dir - gt_dir + 180) mod 360) - 180`, range `[-180, 180)`",
        "- `abs_dir_diff = abs(dir_diff)`",
        "- `vector_error = sqrt((pred_u - gt_u)^2 + (pred_v - gt_v)^2)`",
        "- Altitude filter for official values here: keep points with `alt_m <= 12000`; points above 12 km are excluded before all metrics.",
        "- Direction-stable subset: `gt_speed >= 5 m/s and pred_speed >= 5 m/s`.",
        "",
        "## Single-Value Metrics",
        "",
        f"- Speed bias mean pred-GT: `{sum(speed_diff) / n:.6f}` m/s",
        f"- Speed MAE: `{sum(abs_speed_diff) / n:.6f}` m/s",
        f"- Speed RMSE: `{math.sqrt(sum(v * v for v in speed_diff) / n):.6f}` m/s",
        f"- Speed abs p50/p95/max: `{percentile(abs_speed_diff, 50):.6f}` / `{percentile(abs_speed_diff, 95):.6f}` / `{max(abs_speed_diff):.6f}` m/s",
        f"- Vector RMSE: `{math.sqrt(sum(v * v for v in vector_error) / n):.6f}` m/s",
        f"- Direction all count: `{len(abs_dir_all)}`, abs mean/p50/p95: `{sum(abs_dir_all) / len(abs_dir_all):.6f}` / `{percentile(abs_dir_all, 50):.6f}` / `{percentile(abs_dir_all, 95):.6f}` deg",
        f"- Direction stable count: `{len(abs_dir_valid)}`, abs mean/p50/p95/max: `{sum(abs_dir_valid) / len(abs_dir_valid):.6f}` / `{percentile(abs_dir_valid, 50):.6f}` / `{percentile(abs_dir_valid, 95):.6f}` / `{max(abs_dir_valid):.6f}` deg",
        f"- Direction stable signed bias: `{sum(signed_dir_valid) / len(signed_dir_valid):.6f}` deg",
        "",
        "## RMSE By Altitude Layer",
        "",
        f"- Altitude-layer RMSE CSV: `{ALT_RMSE_CSV_OUT}`",
        "",
        "| alt km | count | vector RMSE m/s | speed RMSE m/s | speed bias pred-GT m/s | speed MAE m/s | dir valid count | abs dir mean deg |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in altitude_rmse_rows(rows):
        lines.append(
            f"| {fmt(row['alt_km'])} | {row['count']} | {fmt(row['vector_rmse_mps'])} | "
            f"{fmt(row['speed_rmse_mps'])} | {fmt(row['speed_bias_pred_minus_gt_mps'])} | "
            f"{fmt(row['speed_mae_mps'])} | {row['direction_valid_count']} | {fmt(row['abs_direction_mean_deg_valid'])} |"
        )

    lines.extend(
        [
            "",
        "## Pointwise Table",
        "",
        "| # | time | z/y/x | alt km | GT speed | Pred speed | Speed diff | abs speed diff | GT dir | Pred dir | dir diff | abs dir diff | vector err | stable dir |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        zyx = f"{row['z']}/{row['y']}/{row['x']}"
        lines.append(
            f"| {row['idx']} | {row['time_str']} | {zyx} | "
            f"{fmt(row['alt_km'])} | "
            f"{fmt(row['gt_speed_mps'])} | {fmt(row['pred_speed_mps'])} | "
            f"{fmt(row['speed_diff_pred_minus_gt_mps'])} | {fmt(row['abs_speed_diff_mps'])} | "
            f"{fmt(row['gt_dir_from_deg'])} | {fmt(row['pred_dir_from_deg'])} | "
            f"{fmt(row['dir_diff_pred_minus_gt_deg'])} | {fmt(row['abs_dir_diff_deg'])} | "
            f"{fmt(row['vector_error_mps'])} | {str(row['direction_valid_gt_pred_ge5']).lower()} |"
        )

    MD_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = load_rows()
    write_csv(rows)
    write_altitude_rmse_csv(rows)
    write_markdown(rows)
    print(CSV_OUT)
    print(ALT_RMSE_CSV_OUT)
    print(MD_OUT)
    print(f"rows={len(rows)}")


if __name__ == "__main__":
    main()
