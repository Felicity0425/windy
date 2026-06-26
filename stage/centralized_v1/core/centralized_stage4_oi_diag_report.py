"""Report-only GFS innovation diagnostics for Stage4 OI readiness."""

from __future__ import annotations

import argparse
import csv
import json
import math
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

from stage.stage5_background_utils import load_background
from stage.centralized_v1.configs.centralized_v1_config import ALT_MIN, DELTA_ALT, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from stage.centralized_v1.core.centralized_stage4_ground_recon import (
    DEFAULT_QC_CALIBRATION,
    _build_wind_observations,
    _load_json,
    _load_stage2_npz,
    _records,
    _safe_float,
    _safe_int,
    _split_holdout,
)


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


def _time_conf_bin(time_conf: float) -> str:
    if time_conf < 0.4:
        return "lt0.4"
    if time_conf < 0.6:
        return "0.4-0.6"
    return "ge0.6"


def _count_bin(count: int) -> str:
    if count <= 0:
        return "count_0"
    if count == 1:
        return "count_1"
    return "count_ge2"


def _distance_bin(distance_vox: float) -> str:
    if distance_vox >= 6.0:
        return "dist_ge6"
    if distance_vox >= 4.0:
        return "dist_4_6"
    if distance_vox >= 2.0:
        return "dist_2_4"
    return "dist_lt2"


def _role_gap_bin(gap_mps: float) -> str:
    if gap_mps >= 30.0:
        return "gap_ge30"
    if gap_mps >= 10.0:
        return "gap_10_30"
    return "gap_lt10"


def _obs_influence_proxy(base_weight: float, background_reference_weight: float) -> float:
    weight = max(0.0, float(base_weight))
    return float(np.clip(weight / max(1e-6, weight + float(background_reference_weight)), 0.0, 1.0))


def _obs_influence_bin(value: float) -> str:
    if value < 0.30:
        return "lt0.30"
    if value < 0.70:
        return "0.30-0.70"
    return "ge0.70"


def _nearest_index(axis: np.ndarray, values: np.ndarray) -> np.ndarray:
    arr = np.asarray(axis, dtype=np.float32).reshape(-1)
    target = np.asarray(values, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return np.zeros_like(target, dtype=np.int32)
    descending = bool(arr.size > 1 and arr[0] > arr[-1])
    work = arr[::-1] if descending else arr
    pos = np.searchsorted(work, target, side="left")
    pos = np.clip(pos, 0, work.size - 1)
    left = np.clip(pos - 1, 0, work.size - 1)
    choose_left = np.abs(target - work[left]) <= np.abs(target - work[pos])
    idx = np.where(choose_left, left, pos)
    if descending:
        idx = (work.size - 1 - idx).astype(np.int32, copy=False)
    return idx.astype(np.int32, copy=False)


def _xyz_to_lat_lon_alt(z: np.ndarray, y: np.ndarray, x: np.ndarray, grid_shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _, h_dim, w_dim = grid_shape
    lat = LAT_MAX - (np.asarray(y, dtype=np.float32) + 0.5) / float(h_dim) * (LAT_MAX - LAT_MIN)
    lon = LON_MIN + (np.asarray(x, dtype=np.float32) + 0.5) / float(w_dim) * (LON_MAX - LON_MIN)
    alt_m = ALT_MIN + np.asarray(z, dtype=np.float32) * np.float32(DELTA_ALT)
    return lat.astype(np.float32, copy=False), lon.astype(np.float32, copy=False), alt_m.astype(np.float32, copy=False)


def _sample_background(background: dict[str, Any], z: np.ndarray, y: np.ndarray, x: np.ndarray, grid_shape: tuple[int, int, int]) -> dict[str, np.ndarray]:
    lat, lon, alt_m = _xyz_to_lat_lon_alt(z, y, x, grid_shape)
    alt_km = alt_m / 1000.0
    bg_lat = np.asarray(background["lat"], dtype=np.float32)
    bg_lon = np.asarray(background["lon"], dtype=np.float32)
    bg_alt = np.asarray(background["alt_km"], dtype=np.float32)
    inside = (
        (lat >= float(np.min(bg_lat)))
        & (lat <= float(np.max(bg_lat)))
        & (lon >= float(np.min(bg_lon)))
        & (lon <= float(np.max(bg_lon)))
        & (alt_km >= float(np.min(bg_alt)))
        & (alt_km <= float(np.max(bg_alt)))
    )
    iz = _nearest_index(bg_alt, alt_km)
    iy = _nearest_index(bg_lat, lat)
    ix = _nearest_index(bg_lon, lon)
    u = np.asarray(background["u"], dtype=np.float32)[iz, iy, ix]
    v = np.asarray(background["v"], dtype=np.float32)[iz, iy, ix]
    return {
        "lat": lat,
        "lon": lon,
        "alt_m": alt_m,
        "alt_km": alt_km.astype(np.float32, copy=False),
        "bg_u": u.astype(np.float32, copy=False),
        "bg_v": v.astype(np.float32, copy=False),
        "inside": inside.astype(bool, copy=False),
    }


def _vector_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "vector_rmse_mps": float("nan"),
            "vector_mae_mps": float("nan"),
            "u_bias_mean_mps": float("nan"),
            "v_bias_mean_mps": float("nan"),
            "speed_bias_mean_mps": float("nan"),
            "obs_influence_proxy_mean": float("nan"),
            "p50_vector_error_mps": float("nan"),
            "p95_vector_error_mps": float("nan"),
        }
    vec = np.asarray([float(row["vector_error_mps"]) for row in rows], dtype=np.float64)
    du = np.asarray([float(row["du_mps"]) for row in rows], dtype=np.float64)
    dv = np.asarray([float(row["dv_mps"]) for row in rows], dtype=np.float64)
    speed_bias = np.asarray([float(row["speed_bias_mps"]) for row in rows], dtype=np.float64)
    influence = np.asarray([float(row.get("obs_influence_proxy", float("nan"))) for row in rows], dtype=np.float64)
    finite_influence = influence[np.isfinite(influence)]
    return {
        "count": int(vec.size),
        "vector_rmse_mps": float(np.sqrt(np.mean(vec * vec))),
        "vector_mae_mps": float(np.mean(np.abs(vec))),
        "u_bias_mean_mps": float(np.mean(du)),
        "v_bias_mean_mps": float(np.mean(dv)),
        "speed_bias_mean_mps": float(np.mean(speed_bias)),
        "obs_influence_proxy_mean": float(np.mean(finite_influence)) if finite_influence.size else float("nan"),
        "p50_vector_error_mps": float(np.percentile(vec, 50)),
        "p95_vector_error_mps": float(np.percentile(vec, 95)),
    }


def _summarize_groups(rows: list[dict[str, Any]], group_key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(group_key, ""))].append(row)
    out: list[dict[str, Any]] = []
    for key in sorted(grouped):
        metrics = _vector_metrics(grouped[key])
        metrics[group_key] = key
        out.append(metrics)
    return out


def _safe_round_key(*values: Any) -> tuple[Any, ...]:
    out: list[Any] = []
    for value in values:
        if isinstance(value, str):
            out.append(value)
        else:
            out.append(round(float(value), 6))
    return tuple(out)


def _load_departures_index(path: Path) -> tuple[dict[tuple[Any, ...], dict[str, str]], dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    index: dict[tuple[Any, ...], dict[str, str]] = {}
    duplicate_count = 0
    for row in rows:
        key = _safe_round_key(
            row.get("time_str", ""),
            _safe_int(row.get("z")),
            _safe_int(row.get("y")),
            _safe_int(row.get("x")),
            _safe_float(row.get("gt_u")),
            _safe_float(row.get("gt_v")),
        )
        if key in index:
            duplicate_count += 1
        index[key] = row
    return index, {"row_count": len(rows), "duplicate_key_count": duplicate_count}


def _attach_holdout_strata(
    time_str: str,
    holdout_rows: list[dict[str, Any]],
    departures_index: dict[tuple[Any, ...], dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    misses: list[dict[str, Any]] = []
    hits = 0
    attached: list[dict[str, Any]] = []
    for row in holdout_rows:
        key = _safe_round_key(time_str, _safe_int(row.get("z")), _safe_int(row.get("y")), _safe_int(row.get("x")), _safe_float(row.get("u")), _safe_float(row.get("v")))
        dep = departures_index.get(key)
        payload = dict(row)
        if dep is None:
            payload["nearest_current_count_bin"] = ""
            payload["nearest_train_distance_bin"] = ""
            payload["nearest_role_gap_bin"] = ""
            misses.append({"time_str": time_str, "z": row.get("z"), "y": row.get("y"), "x": row.get("x")})
        else:
            hits += 1
            payload["nearest_current_count_bin"] = _count_bin(_safe_int(dep.get("nearest_current_count"), 0))
            payload["nearest_train_distance_bin"] = _distance_bin(_safe_float(dep.get("nearest_train_distance_vox"), float("nan")))
            payload["nearest_role_gap_bin"] = _role_gap_bin(_safe_float(dep.get("nearest_role_gap_mps"), float("nan")))
            payload["qc_review_flag"] = str(dep.get("qc_review_flag", ""))
        attached.append(payload)
    return attached, {"join_hits": hits, "join_misses": len(misses), "join_misses_preview": misses[:10]}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    holdout = report["holdout_background"]
    train = report["train_innovation"]
    rec = report["recommendation"]
    lines = [
        "# S4 OI diagnostic report",
        "",
        f"- Generated: `{report['generated_utc']}`",
        f"- Background dir: `{report['background_dir']}`",
        f"- Stage2 summary: `{report['stage2_summary']}`",
        f"- Frame count: `{report['frame_count']}`",
        "",
        "## Train Innovation",
        "",
        f"- Rows inside background ROI: `{train['inside_background_count']}`",
        f"- Rows outside background ROI: `{train['outside_background_count']}`",
        f"- Overall vector RMSE: `{train['overall']['vector_rmse_mps']:.6f}` m/s",
        f"- Overall vector MAE: `{train['overall']['vector_mae_mps']:.6f}` m/s",
        f"- Mean obs_influence_proxy: `{train['overall']['obs_influence_proxy_mean']:.6f}`",
        "",
        "## Holdout Background",
        "",
        f"- Strict holdout rows inside background ROI: `{holdout['inside_background_count']}`",
        f"- Strict holdout rows outside background ROI: `{holdout['outside_background_count']}`",
        f"- Overall vector RMSE: `{holdout['overall']['vector_rmse_mps']:.6f}` m/s",
        f"- Overall vector MAE: `{holdout['overall']['vector_mae_mps']:.6f}` m/s",
        f"- Departures join hit rate: `{holdout['departures_join_hit_rate']:.6f}`",
        "",
        "## Recommendation",
        "",
        f"- Summary: `{rec['summary']}`",
        f"- Next step: `{rec['next_step']}`",
        f"- High-risk strata: `{rec['high_risk_strata']}`",
        f"- Conditionally usable strata: `{rec['conditionally_usable_strata']}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Report-only GFS innovation diagnostics for Stage4 OI readiness.")
    parser.add_argument("--stage2-summary", type=Path, required=True)
    parser.add_argument("--frame-times-file", type=Path, required=True)
    parser.add_argument("--background-dir", type=Path, required=True)
    parser.add_argument("--departures-csv", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--out-train-strata-csv", type=Path, required=True)
    parser.add_argument("--out-holdout-strata-csv", type=Path, required=True)
    parser.add_argument("--holdout-fraction", type=float, default=0.125)
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--confidence-mode", default="diagnostic_weighted")
    parser.add_argument("--current-weight-boost", type=float, default=2.0)
    parser.add_argument("--context-weight-scale", type=float, default=0.5)
    parser.add_argument("--context-time-conf-power", type=float, default=2.6)
    parser.add_argument("--background-reference-weight", type=float, default=0.20)
    args = parser.parse_args()

    wanted = set(_read_frame_times_file(args.frame_times_file))
    stage2_rows_all = _load_json(args.stage2_summary)
    stage2_rows = [row for row in stage2_rows_all if str(row.get("time_str")) in wanted]
    stage2_rows = sorted(stage2_rows, key=lambda row: str(row["time_str"]))
    departures_index, departures_meta = _load_departures_index(args.departures_csv)

    train_rows: list[dict[str, Any]] = []
    holdout_rows: list[dict[str, Any]] = []
    frame_summaries: list[dict[str, Any]] = []
    missing_background_frames: list[str] = []
    train_outside = 0
    holdout_outside = 0
    join_hits = 0
    join_misses = 0
    join_miss_preview: list[dict[str, Any]] = []

    for stage2_row in stage2_rows:
        time_str = str(stage2_row["time_str"])
        background = load_background(args.background_dir, time_str)
        if background is None:
            missing_background_frames.append(time_str)
            continue
        npz = _load_stage2_npz(Path(stage2_row["multimodal_vox_path"]))
        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int32).tolist())
        wind_records = _records(npz.get("wind_records"))
        context_wind_records = _records(npz.get("context_wind_records"))
        train_current, holdout = _split_holdout(wind_records, args.holdout_fraction, args.holdout_count)
        observations, _ = _build_wind_observations(
            train_current,
            context_wind_records,
            args.confidence_mode,
            qc_calibration=dict(DEFAULT_QC_CALIBRATION),
            current_weight_boost=args.current_weight_boost,
            context_weight_scale=args.context_weight_scale,
            context_time_conf_power=args.context_time_conf_power,
        )

        if observations:
            obs_z = np.asarray([_safe_int(row.get("z")) for row in observations], dtype=np.int32)
            obs_y = np.asarray([_safe_int(row.get("y")) for row in observations], dtype=np.int32)
            obs_x = np.asarray([_safe_int(row.get("x")) for row in observations], dtype=np.int32)
            sampled = _sample_background(background, obs_z, obs_y, obs_x, shape)
            for idx, row in enumerate(observations):
                inside = bool(sampled["inside"][idx])
                if not inside:
                    train_outside += 1
                    continue
                obs_u = _safe_float(row.get("u"))
                obs_v = _safe_float(row.get("v"))
                bg_u = float(sampled["bg_u"][idx])
                bg_v = float(sampled["bg_v"][idx])
                speed_obs = math.hypot(obs_u, obs_v)
                speed_bg = math.hypot(bg_u, bg_v)
                influence = _obs_influence_proxy(row.get("base_weight", 0.0), args.background_reference_weight)
                train_rows.append(
                    {
                        "dataset": "train_innovation",
                        "time_str": time_str,
                        "source_role": str(row.get("source_role", "")),
                        "altitude_bin": _altitude_bin(float(sampled["alt_m"][idx])),
                        "speed_bin": _speed_bin(speed_obs),
                        "time_conf_bin": _time_conf_bin(_safe_float(row.get("time_conf"), 1.0)),
                        "obs_influence_bin": _obs_influence_bin(influence),
                        "obs_influence_proxy": influence,
                        "du_mps": obs_u - bg_u,
                        "dv_mps": obs_v - bg_v,
                        "speed_bias_mps": speed_obs - speed_bg,
                        "vector_error_mps": math.hypot(obs_u - bg_u, obs_v - bg_v),
                    }
                )

        attached_holdout, join_info = _attach_holdout_strata(time_str, holdout, departures_index)
        join_hits += int(join_info["join_hits"])
        join_misses += int(join_info["join_misses"])
        if join_info["join_misses_preview"]:
            room = max(0, 10 - len(join_miss_preview))
            join_miss_preview.extend(join_info["join_misses_preview"][:room])
        if attached_holdout:
            hz = np.asarray([_safe_int(row.get("z")) for row in attached_holdout], dtype=np.int32)
            hy = np.asarray([_safe_int(row.get("y")) for row in attached_holdout], dtype=np.int32)
            hx = np.asarray([_safe_int(row.get("x")) for row in attached_holdout], dtype=np.int32)
            sampled_holdout = _sample_background(background, hz, hy, hx, shape)
            inside_count = 0
            for idx, row in enumerate(attached_holdout):
                inside = bool(sampled_holdout["inside"][idx])
                if not inside:
                    holdout_outside += 1
                    continue
                inside_count += 1
                obs_u = _safe_float(row.get("u"))
                obs_v = _safe_float(row.get("v"))
                bg_u = float(sampled_holdout["bg_u"][idx])
                bg_v = float(sampled_holdout["bg_v"][idx])
                speed_obs = math.hypot(obs_u, obs_v)
                speed_bg = math.hypot(bg_u, bg_v)
                holdout_rows.append(
                    {
                        "dataset": "holdout_background",
                        "time_str": time_str,
                        "altitude_bin": _altitude_bin(float(sampled_holdout["alt_m"][idx])),
                        "speed_bin": _speed_bin(speed_obs),
                        "nearest_current_count_bin": str(row.get("nearest_current_count_bin", "")),
                        "nearest_train_distance_bin": str(row.get("nearest_train_distance_bin", "")),
                        "nearest_role_gap_bin": str(row.get("nearest_role_gap_bin", "")),
                        "qc_review_flag": str(row.get("qc_review_flag", "")),
                        "obs_influence_proxy": float("nan"),
                        "du_mps": obs_u - bg_u,
                        "dv_mps": obs_v - bg_v,
                        "speed_bias_mps": speed_obs - speed_bg,
                        "vector_error_mps": math.hypot(obs_u - bg_u, obs_v - bg_v),
                    }
                )
            frame_summaries.append(
                {
                    "time_str": time_str,
                    "background_cycle": str(background.get("cycle", "")),
                    "background_forecast_hour": int(np.asarray(background.get("forecast_hour", -1)).reshape(-1)[0]) if "forecast_hour" in background else -1,
                    "train_observation_count": len(observations),
                    "holdout_count": len(holdout),
                    "holdout_inside_background_count": inside_count,
                }
            )

    train_overall = _vector_metrics(train_rows)
    holdout_overall = _vector_metrics(holdout_rows)

    train_group_specs = [
        ("source_role", "train_source_role"),
        ("altitude_bin", "train_altitude_bin"),
        ("time_conf_bin", "train_time_conf_bin"),
        ("speed_bin", "train_speed_bin"),
        ("obs_influence_bin", "train_obs_influence_bin"),
    ]
    holdout_group_specs = [
        ("altitude_bin", "holdout_altitude_bin"),
        ("speed_bin", "holdout_speed_bin"),
        ("nearest_current_count_bin", "holdout_nearest_current_count_bin"),
        ("nearest_train_distance_bin", "holdout_nearest_train_distance_bin"),
        ("nearest_role_gap_bin", "holdout_nearest_role_gap_bin"),
        ("qc_review_flag", "holdout_qc_review_flag"),
    ]
    train_strata_csv_rows: list[dict[str, Any]] = []
    holdout_strata_csv_rows: list[dict[str, Any]] = []

    train_strata: dict[str, list[dict[str, Any]]] = {}
    holdout_strata: dict[str, list[dict[str, Any]]] = {}
    for group_key, label in train_group_specs:
        metrics = _summarize_groups(train_rows, group_key)
        for row in metrics:
            train_strata_csv_rows.append({"group_name": label, **row})
        train_strata[label] = metrics
    for group_key, label in holdout_group_specs:
        metrics = _summarize_groups(holdout_rows, group_key)
        for row in metrics:
            holdout_strata_csv_rows.append({"group_name": label, **row})
        holdout_strata[label] = metrics

    _write_csv(args.out_train_strata_csv, train_strata_csv_rows)
    _write_csv(args.out_holdout_strata_csv, holdout_strata_csv_rows)

    overall_holdout_rmse = holdout_overall["vector_rmse_mps"] if math.isfinite(holdout_overall["vector_rmse_mps"]) else float("nan")
    critical_rows = holdout_strata.get("holdout_altitude_bin", []) + holdout_strata.get("holdout_nearest_current_count_bin", []) + holdout_strata.get("holdout_nearest_role_gap_bin", [])
    high_risk: list[str] = []
    usable: list[str] = []
    for row in critical_rows:
        name = next((str(row[key]) for key in row.keys() if key.endswith("_bin")), "")
        rmse = _safe_float(row.get("vector_rmse_mps"), float("nan"))
        bias = abs(_safe_float(row.get("speed_bias_mean_mps"), float("nan")))
        if not math.isfinite(rmse) or not math.isfinite(overall_holdout_rmse) or int(row.get("count", 0)) < 10:
            continue
        if rmse > overall_holdout_rmse * 1.25 or bias > 5.0:
            high_risk.append(name)
        else:
            usable.append(name)

    if missing_background_frames:
        summary = "Background coverage incomplete; do not enter OI yet."
        next_step = "Fix background mapping or missing frame NPZs before constrained OI."
    elif high_risk:
        summary = "GFS is usable as a diagnostic/weak background, but high-risk strata remain and official OI should stay constrained."
        next_step = "Proceed only with constrained S4-OI-1a/1b style experiments, protect light wind and treat high-risk strata conservatively."
    else:
        summary = "GFS background diagnostics look stable enough to proceed to constrained OI experiments."
        next_step = "Proceed to S4-OI-1a/1b report-only or limited oi_diag_approx trials."

    report = {
        "generated_utc": _to_iso_utc(datetime.now(timezone.utc)),
        "stage2_summary": str(args.stage2_summary),
        "frame_times_file": str(args.frame_times_file),
        "background_dir": str(args.background_dir),
        "departures_csv": str(args.departures_csv),
        "frame_count": len(stage2_rows),
        "missing_background_frames": missing_background_frames,
        "departures_index_meta": departures_meta,
        "frame_summaries_preview": frame_summaries[:12],
        "train_innovation": {
            "inside_background_count": len(train_rows),
            "outside_background_count": int(train_outside),
            "overall": train_overall,
            "strata": train_strata,
        },
        "holdout_background": {
            "inside_background_count": len(holdout_rows),
            "outside_background_count": int(holdout_outside),
            "overall": holdout_overall,
            "departures_join_hits": int(join_hits),
            "departures_join_misses": int(join_misses),
            "departures_join_hit_rate": float(join_hits / max(1, join_hits + join_misses)),
            "departures_join_miss_preview": join_miss_preview,
            "strata": holdout_strata,
        },
        "recommendation": {
            "summary": summary,
            "next_step": next_step,
            "high_risk_strata": sorted(set(high_risk)),
            "conditionally_usable_strata": sorted(set(usable)),
            "note": "obs_influence_proxy is a report-only heuristic derived from Stage4 observation base_weight, not a formal OI analysis influence.",
        },
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(args.out_md, report)
    print(args.out_json)
    print(args.out_md)
    print(args.out_train_strata_csv)
    print(args.out_holdout_strata_csv)


if __name__ == "__main__":
    main()
