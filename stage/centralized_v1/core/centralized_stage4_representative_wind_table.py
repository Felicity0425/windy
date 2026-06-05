"""Build representative Stage4 holdout wind speed/direction tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


SPEED_BINS = [
    (0.0, 5.0, "0-5mps_calm"),
    (5.0, 15.0, "5-15mps_light"),
    (15.0, 30.0, "15-30mps_moderate"),
    (30.0, 60.0, "30-60mps_strong"),
    (60.0, None, "60mps_plus_extreme"),
]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON list: {path}")
    return [dict(row) for row in payload]


def _to_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _speed_bin(speed: float) -> str:
    for lo, hi, name in SPEED_BINS:
        if speed >= lo and (hi is None or speed < hi):
            return name
    return "unknown"


def _angle_deg(u: float, v: float) -> float:
    return float((math.degrees(math.atan2(v, u)) + 360.0) % 360.0)


def _angle_error_deg(gt_u: float, gt_v: float, pred_u: float, pred_v: float, gt_speed: float, pred_speed: float) -> float:
    if gt_speed < 5.0 or pred_speed < 1.0:
        return float("nan")
    diff = abs((_angle_deg(pred_u, pred_v) - _angle_deg(gt_u, gt_v) + 180.0) % 360.0 - 180.0)
    return float(diff)


def _discover_point_files(point_eval_dir: Path, frame_times: list[str]) -> list[Path]:
    if frame_times:
        out: list[Path] = []
        for frame in frame_times:
            csv_path = point_eval_dir / f"point_eval_{frame}.csv"
            json_path = point_eval_dir / f"point_eval_{frame}.json"
            if csv_path.exists():
                out.append(csv_path)
            elif json_path.exists():
                out.append(json_path)
            else:
                raise FileNotFoundError(f"No point_eval CSV/JSON for frame {frame} under {point_eval_dir}")
        return out
    return sorted(point_eval_dir.glob("point_eval_*.csv"))


def _frame_from_path(path: Path) -> str:
    name = path.stem
    if name.startswith("point_eval_"):
        return name[len("point_eval_") :]
    return name


def _rows_from_file(path: Path) -> list[dict[str, Any]]:
    source = _read_json(path) if path.suffix == ".json" else _read_csv(path)
    frame = _frame_from_path(path)
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(source):
        gt_u = _to_float(row, "gt_u")
        gt_v = _to_float(row, "gt_v")
        pred_u = _to_float(row, "pred_u")
        pred_v = _to_float(row, "pred_v")
        gt_speed = _to_float(row, "gt_speed", math.sqrt(gt_u**2 + gt_v**2))
        pred_speed = _to_float(row, "pred_speed", math.sqrt(pred_u**2 + pred_v**2))
        vector_error = _to_float(row, "vector_error", math.sqrt((_to_float(row, "u_error")) ** 2 + (_to_float(row, "v_error")) ** 2))
        out.append(
            {
                "time_str": str(row.get("time_str", frame) or frame),
                "point_index": idx,
                "z": row.get("z", ""),
                "y": row.get("y", ""),
                "x": row.get("x", ""),
                "alt_m": row.get("alt_m", ""),
                "truth_speed_bin": _speed_bin(gt_speed),
                "gt_speed_mps": gt_speed,
                "pred_speed_mps": pred_speed,
                "speed_delta_pred_minus_gt_mps": pred_speed - gt_speed,
                "gt_direction_atan2_v_u_deg": _angle_deg(gt_u, gt_v),
                "pred_direction_atan2_v_u_deg": _angle_deg(pred_u, pred_v),
                "direction_error_deg": _angle_error_deg(gt_u, gt_v, pred_u, pred_v, gt_speed, pred_speed),
                "vector_error_mps": vector_error,
                "relative_error_ratio": vector_error / max(gt_speed, 1e-6),
                "floor10_relative_error": vector_error / max(gt_speed, 10.0),
                "recon_confidence": _to_float(row, "recon_confidence"),
                "nearest_train_source_role": row.get("nearest_train_source_role", ""),
                "nearest_current_count": row.get("nearest_current_count", ""),
                "nearest_context_count": row.get("nearest_context_count", ""),
                "nearest_role_gap_mps": row.get("nearest_role_gap_mps", ""),
                "strict_holdout_no_leakage": row.get("strict_holdout_no_leakage", ""),
                "motion_used_as_wind": row.get("motion_used_as_wind", ""),
            }
        )
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def _fmt(value: Any, digits: int = 3) -> str:
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value_f):
        return "NA"
    return f"{value_f:.{digits}f}"


def _write_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Representative Wind Speed / Direction Table",
        "",
        "Direction is computed as `atan2(v, u)` for the horizontal wind vector. Direction error is set to NA when `gt_speed < 5 m/s` or `pred_speed < 1 m/s`.",
        "",
        "| frame | z/y/x | speed bin | gt speed | pred speed | vector error | rel ratio | floor10 rel | dir error | confidence | support |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['time_str']}` | `{row['z']}/{row['y']}/{row['x']}` | `{row['truth_speed_bin']}` | "
            f"{_fmt(row['gt_speed_mps'])} | {_fmt(row['pred_speed_mps'])} | {_fmt(row['vector_error_mps'])} | "
            f"{_fmt(row['relative_error_ratio'])} | {_fmt(row['floor10_relative_error'])} | {_fmt(row['direction_error_deg'], 2)} | "
            f"{_fmt(row['recon_confidence'])} | `{row['nearest_train_source_role']}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--point-eval-dir", type=Path, required=True)
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-prefix", default="representative_wind_speed_direction_table")
    args = parser.parse_args()

    frames = [token.strip() for token in str(args.frame_times).split(",") if token.strip()]
    rows: list[dict[str, Any]] = []
    for path in _discover_point_files(args.point_eval_dir, frames):
        rows.extend(_rows_from_file(path))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / f"{args.out_prefix}.csv"
    md_path = args.out_dir / f"{args.out_prefix}.md"
    _write_csv(csv_path, rows)
    _write_md(md_path, rows)
    print(md_path)


if __name__ == "__main__":
    main()
