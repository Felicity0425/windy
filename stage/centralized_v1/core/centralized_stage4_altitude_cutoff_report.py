"""Evaluate Stage4 holdout metrics after excluding high-altitude points."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _vector_error(row: dict[str, Any]) -> float:
    vec = _safe_float(row.get("vector_error"))
    if math.isfinite(vec):
        return vec
    u_error = _safe_float(row.get("u_error"))
    v_error = _safe_float(row.get("v_error"))
    if math.isfinite(u_error) and math.isfinite(v_error):
        return math.sqrt(u_error * u_error + v_error * v_error)
    return float("nan")


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


def _speed_bin(speed_mps: float) -> str:
    if speed_mps < 5.0:
        return "lt5"
    if speed_mps < 15.0:
        return "5-15"
    if speed_mps < 30.0:
        return "15-30"
    if speed_mps < 60.0:
        return "30-60"
    return "60+"


def _mean(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return 0.0
    return sum(finite) / len(finite)


def _rmse(values: list[float]) -> float:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return 0.0
    return math.sqrt(sum(value * value for value in finite) / len(finite))


def _percentile(values: list[float], q: float) -> float:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return 0.0
    if len(finite) == 1:
        return finite[0]
    pos = (len(finite) - 1) * float(q)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return finite[lo]
    w = pos - lo
    return finite[lo] * (1.0 - w) + finite[hi] * w


def _frame_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        time_str = str(row.get("time_str", "")).strip()
        vec = _vector_error(row)
        if time_str and math.isfinite(vec):
            grouped[time_str].append(vec)
    out: list[dict[str, Any]] = []
    for time_str in sorted(grouped):
        values = grouped[time_str]
        out.append(
            {
                "time_str": time_str,
                "point_count": len(values),
                "frame_rmse_vector_mps": _rmse(values),
                "frame_mae_vector_mps": _mean([abs(value) for value in values]),
            }
        )
    return out


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vec: list[float] = []
    u_err: list[float] = []
    v_err: list[float] = []
    recon_conf: list[float] = []
    gt_speed: list[float] = []
    qc_true = 0
    for row in rows:
        value = _vector_error(row)
        if not math.isfinite(value):
            continue
        vec.append(value)
        u_err.append(_safe_float(row.get("u_error"), 0.0))
        v_err.append(_safe_float(row.get("v_error"), 0.0))
        conf = _safe_float(row.get("recon_confidence"))
        if math.isfinite(conf):
            recon_conf.append(conf)
        speed = _safe_float(row.get("gt_speed"))
        if math.isfinite(speed):
            gt_speed.append(speed)
        if _truthy(row.get("qc_review_flag", False)):
            qc_true += 1

    if not vec:
        return {
            "point_count": 0,
            "vector_rmse_mps": 0.0,
            "vector_mae_mps": 0.0,
            "u_bias_mean_mps": 0.0,
            "v_bias_mean_mps": 0.0,
            "p50_vector_error_mps": 0.0,
            "p95_vector_error_mps": 0.0,
            "p99_vector_error_mps": 0.0,
            "mean_recon_confidence": 0.0,
            "tail_ge30_count": 0,
            "tail_ge30_fraction": 0.0,
            "qc_review_true_count": 0,
            "qc_review_true_fraction": 0.0,
            "light_wind_5_15_count": 0,
            "light_wind_5_15_rmse_mps": 0.0,
            "light_wind_5_15_mae_mps": 0.0,
        }

    light_vec = [
        _vector_error(row)
        for row in rows
        if math.isfinite(_safe_float(row.get("gt_speed"))) and 5.0 <= _safe_float(row.get("gt_speed")) < 15.0 and math.isfinite(_vector_error(row))
    ]
    return {
        "point_count": len(vec),
        "vector_rmse_mps": _rmse(vec),
        "vector_mae_mps": _mean([abs(value) for value in vec]),
        "u_bias_mean_mps": _mean(u_err),
        "v_bias_mean_mps": _mean(v_err),
        "p50_vector_error_mps": _percentile(vec, 0.50),
        "p95_vector_error_mps": _percentile(vec, 0.95),
        "p99_vector_error_mps": _percentile(vec, 0.99),
        "mean_recon_confidence": _mean(recon_conf),
        "tail_ge30_count": sum(1 for value in vec if value >= 30.0),
        "tail_ge30_fraction": sum(1 for value in vec if value >= 30.0) / len(vec),
        "qc_review_true_count": qc_true,
        "qc_review_true_fraction": qc_true / len(vec),
        "light_wind_5_15_count": len(light_vec),
        "light_wind_5_15_rmse_mps": _rmse(light_vec),
        "light_wind_5_15_mae_mps": _mean([abs(value) for value in light_vec]) if light_vec else 0.0,
    }


def _group_summary(rows: list[dict[str, Any]], key_name: str, order: list[str] | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key_name])].append(row)
    keys = list(grouped.keys())
    if order is not None:
        ordered = [key for key in order if key in grouped]
        ordered.extend(sorted(key for key in keys if key not in set(order)))
        keys = ordered
    else:
        keys = sorted(keys)
    out: list[dict[str, Any]] = []
    for key in keys:
        metrics = _metric_summary(grouped[key])
        metrics[key_name] = key
        out.append(metrics)
    return out


def _subset_summary(rows: list[dict[str, Any]], all_frame_times: list[str]) -> dict[str, Any]:
    frame_rows = _frame_rows(rows)
    frame_rmse = [float(row["frame_rmse_vector_mps"]) for row in frame_rows]
    frame_mae = [float(row["frame_mae_vector_mps"]) for row in frame_rows]
    present_frames = {str(row["time_str"]) for row in frame_rows}
    missing_frames = [time_str for time_str in all_frame_times if time_str not in present_frames]
    altitude_rows = []
    speed_rows = []
    prepared_rows: list[dict[str, Any]] = []
    for row in rows:
        alt_m = _safe_float(row.get("alt_m"))
        speed = _safe_float(row.get("gt_speed"))
        enriched = dict(row)
        enriched["altitude_bin"] = _altitude_bin(alt_m)
        enriched["speed_bin"] = _speed_bin(speed) if math.isfinite(speed) else "unknown"
        prepared_rows.append(enriched)
    altitude_rows = _group_summary(prepared_rows, "altitude_bin", order=["0-3km", "3-6km", "6-9km", "9-12km", "12km+"])
    speed_rows = _group_summary(prepared_rows, "speed_bin", order=["lt5", "5-15", "15-30", "30-60", "60+"])
    return {
        "overall": _metric_summary(rows),
        "frame_metrics": {
            "frame_count": len(frame_rows),
            "frame_mean_rmse_mps": _mean(frame_rmse),
            "frame_mean_mae_mps": _mean(frame_mae),
            "frame_p95_rmse_mps": _percentile(frame_rmse, 0.95),
            "frame_p99_rmse_mps": _percentile(frame_rmse, 0.99),
            "frames_without_points_count": len(missing_frames),
            "frames_without_points_preview": missing_frames[:20],
        },
        "altitude_bins": altitude_rows,
        "speed_bins": speed_rows,
    }


def _to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    comp = report["comparison"]
    all_summary = report["all_points"]
    kept = report["kept_points"]
    removed = report["removed_points"]
    lines = [
        "# Stage4 altitude cutoff report",
        "",
        f"- Generated: `{report['generated_utc']}`",
        f"- Source CSV: `{report['point_csv']}`",
        f"- Keep rule: `{report['keep_rule']}`",
        "",
        "## Headline",
        "",
        f"- Total holdout points: `{all_summary['overall']['point_count']}`",
        f"- Kept points (`< {report['max_alt_m']:.0f} m`): `{kept['overall']['point_count']}`",
        f"- Removed points (`>= {report['max_alt_m']:.0f} m`): `{removed['overall']['point_count']}`",
        f"- Removed point fraction: `{comp['removed_point_fraction']:.3%}`",
        f"- Removed SSE fraction: `{comp['removed_vector_sse_fraction']:.3%}`",
        "",
        "## Overall comparison",
        "",
        f"- All-point vector RMSE: `{all_summary['overall']['vector_rmse_mps']:.6f}` m/s",
        f"- <= cutoff vector RMSE: `{kept['overall']['vector_rmse_mps']:.6f}` m/s",
        f"- RMSE delta (kept - all): `{comp['kept_minus_all_vector_rmse_mps']:.6f}` m/s",
        f"- All-point vector MAE: `{all_summary['overall']['vector_mae_mps']:.6f}` m/s",
        f"- <= cutoff vector MAE: `{kept['overall']['vector_mae_mps']:.6f}` m/s",
        f"- MAE delta (kept - all): `{comp['kept_minus_all_vector_mae_mps']:.6f}` m/s",
        "",
        "## Frame-level comparison",
        "",
        f"- All-point frame mean RMSE: `{all_summary['frame_metrics']['frame_mean_rmse_mps']:.6f}` m/s",
        f"- <= cutoff frame mean RMSE: `{kept['frame_metrics']['frame_mean_rmse_mps']:.6f}` m/s",
        f"- All-point frame P95 RMSE: `{all_summary['frame_metrics']['frame_p95_rmse_mps']:.6f}` m/s",
        f"- <= cutoff frame P95 RMSE: `{kept['frame_metrics']['frame_p95_rmse_mps']:.6f}` m/s",
        f"- All-point frame P99 RMSE: `{all_summary['frame_metrics']['frame_p99_rmse_mps']:.6f}` m/s",
        f"- <= cutoff frame P99 RMSE: `{kept['frame_metrics']['frame_p99_rmse_mps']:.6f}` m/s",
        f"- Frames emptied by cutoff: `{kept['frame_metrics']['frames_without_points_count']}`",
        "",
        "## Light wind",
        "",
        f"- All-point `5-15 m/s` RMSE: `{all_summary['overall']['light_wind_5_15_rmse_mps']:.6f}` m/s",
        f"- <= cutoff `5-15 m/s` RMSE: `{kept['overall']['light_wind_5_15_rmse_mps']:.6f}` m/s",
        f"- All-point `5-15 m/s` MAE: `{all_summary['overall']['light_wind_5_15_mae_mps']:.6f}` m/s",
        f"- <= cutoff `5-15 m/s` MAE: `{kept['overall']['light_wind_5_15_mae_mps']:.6f}` m/s",
        "",
        "## Kept altitude bins",
        "",
        "| Bin | Points | Vector RMSE | Vector MAE | P95 | Tail>=30 count |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in kept["altitude_bins"]:
        lines.append(
            "| {altitude_bin} | {point_count} | {vector_rmse_mps:.6f} | {vector_mae_mps:.6f} | {p95_vector_error_mps:.6f} | {tail_ge30_count} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Note",
            "",
            "This report redefines the evaluation scope by excluding high-altitude holdout points.",
            "It is useful for business-facing <=12 km diagnostics, but it is not directly comparable to the original all-altitude promotion gate unless that gate is also redefined.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Stage4 holdout metrics after excluding high-altitude points.")
    parser.add_argument("--point-csv", type=Path, required=True, help="Input stage4_point_departures.csv")
    parser.add_argument("--max-alt-m", type=float, default=12000.0, help="Keep rows with alt_m < this cutoff")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--out-kept-csv", type=Path, default=None)
    parser.add_argument("--out-removed-csv", type=Path, default=None)
    args = parser.parse_args()

    with args.point_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]

    all_frame_times = sorted({str(row.get("time_str", "")).strip() for row in rows if str(row.get("time_str", "")).strip()})
    invalid_alt_rows = 0
    kept_rows: list[dict[str, Any]] = []
    removed_rows: list[dict[str, Any]] = []
    for row in rows:
        alt_m = _safe_float(row.get("alt_m"))
        if not math.isfinite(alt_m):
            invalid_alt_rows += 1
            continue
        if alt_m < float(args.max_alt_m):
            kept_rows.append(row)
        else:
            removed_rows.append(row)

    if args.out_kept_csv is not None:
        _write_csv(args.out_kept_csv, kept_rows, fieldnames)
    if args.out_removed_csv is not None:
        _write_csv(args.out_removed_csv, removed_rows, fieldnames)

    all_summary = _subset_summary(rows, all_frame_times)
    kept_summary = _subset_summary(kept_rows, all_frame_times)
    removed_summary = _subset_summary(removed_rows, all_frame_times)

    all_sse = sum(_vector_error(row) ** 2 for row in rows if math.isfinite(_vector_error(row)))
    removed_sse = sum(_vector_error(row) ** 2 for row in removed_rows if math.isfinite(_vector_error(row)))

    report = {
        "generated_utc": _to_iso_utc(datetime.now(timezone.utc)),
        "point_csv": str(args.point_csv),
        "max_alt_m": float(args.max_alt_m),
        "keep_rule": f"alt_m < {float(args.max_alt_m):.1f}",
        "invalid_alt_rows_skipped": int(invalid_alt_rows),
        "comparison": {
            "removed_point_fraction": len(removed_rows) / max(1, len(rows)),
            "removed_vector_sse_fraction": removed_sse / max(all_sse, 1e-12),
            "kept_minus_all_vector_rmse_mps": kept_summary["overall"]["vector_rmse_mps"] - all_summary["overall"]["vector_rmse_mps"],
            "kept_minus_all_vector_mae_mps": kept_summary["overall"]["vector_mae_mps"] - all_summary["overall"]["vector_mae_mps"],
            "kept_minus_all_frame_p95_rmse_mps": kept_summary["frame_metrics"]["frame_p95_rmse_mps"] - all_summary["frame_metrics"]["frame_p95_rmse_mps"],
            "kept_minus_all_frame_p99_rmse_mps": kept_summary["frame_metrics"]["frame_p99_rmse_mps"] - all_summary["frame_metrics"]["frame_p99_rmse_mps"],
        },
        "all_points": all_summary,
        "kept_points": kept_summary,
        "removed_points": removed_summary,
        "notes": [
            "The filtered metrics answer a <= cutoff business question; they do not by themselves prove the original all-altitude objective improved.",
            "If the official project scope is redefined to <=12 km, downstream gates and baseline tables should be regenerated with the same cutoff.",
        ],
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(args.out_md, report)
    print(args.out_json)
    print(args.out_md)
    if args.out_kept_csv is not None:
        print(args.out_kept_csv)
    if args.out_removed_csv is not None:
        print(args.out_removed_csv)


if __name__ == "__main__":
    main()
