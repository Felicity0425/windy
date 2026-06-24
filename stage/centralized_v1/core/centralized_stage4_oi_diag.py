"""Stage4 OI report-only diagnostics.

This script implements the lightweight S4-OI-DIAG step from the Stage45 plan.
It samples existing CMA/CRA40 proxy NPZ fields at aircraft observation voxels
and writes point/frame/stratified diagnostics only. It never writes 3D
reconstruction NPZ outputs and never changes official Stage4 recon fields.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR_LOCAL = Path(__file__).resolve().parents[3]
STAGE_DIR_LOCAL = Path(__file__).resolve().parents[2]
import sys

if str(ROOT_DIR_LOCAL) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR_LOCAL))
if str(STAGE_DIR_LOCAL) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR_LOCAL))

from stage.centralized_v1.configs.centralized_v1_config import ALT_MIN, DELTA_ALT
from stage.centralized_v1.configs.centralized_v1_contract import (
    C2_GRID_SHAPE,
    C2_WIND_RECORDS,
)
from stage.centralized_v1.core.centralized_stage4_ground_recon import (
    ROOT_DIR,
    _find_cma_proxy_npz,
    _load_json,
    _load_stage2_npz,
    _records,
    _safe_float,
    _safe_int,
    _split_holdout,
)


DEFAULT_STAGE2_SUMMARY = ROOT_DIR / "centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json"
DEFAULT_CMA_PROXY_DIR = ROOT_DIR / "centralized_v1_output/stage4_three_method_compare_20260531/cma_proxy"
DEFAULT_BASELINE_SUMMARY = (
    ROOT_DIR
    / "centralized_v1_output/stage45_oi_cma_m1_200_25w_20260614/baseline_tp26_ground_recon/stage4_center_summary.json"
)
DEFAULT_OUT_DIR = ROOT_DIR / "centralized_v1_output/stage45_oi_diag_light_200_20260614"


def _read_frame_times_file(path: Path | None) -> list[str]:
    if path is None:
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError(f"frame-times JSON must be a list: {path}")
        return [str(x).strip() for x in payload if str(x).strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_frame_times(raw: str, frame_times_file: Path | None) -> set[str]:
    values = _read_frame_times_file(frame_times_file)
    if raw.strip():
        values.extend([part.strip() for part in raw.split(",") if part.strip()])
    return set(values)


def _select_rows(rows: list[dict[str, Any]], frame_times: set[str]) -> list[dict[str, Any]]:
    if not frame_times:
        return sorted(rows, key=lambda row: str(row["time_str"]))
    selected = [row for row in rows if str(row.get("time_str")) in frame_times]
    found = {str(row.get("time_str")) for row in selected}
    missing = sorted(frame_times - found)
    if missing:
        raise ValueError(f"Requested frame-times not found in Stage2 summary: {missing[:10]}")
    return sorted(selected, key=lambda row: str(row["time_str"]))


def _sample_rows(rows: list[dict[str, Any]], sample_count: int, sample_seed: int) -> list[dict[str, Any]]:
    sample_count = int(sample_count)
    if sample_count <= 0 or sample_count >= len(rows):
        return rows
    rng = np.random.default_rng(int(sample_seed))
    indices = sorted(int(i) for i in rng.choice(len(rows), size=sample_count, replace=False))
    return [rows[i] for i in indices]


def _load_cma_fields(path: Path, shape: tuple[int, int, int]) -> dict[str, np.ndarray]:
    with np.load(path) as z:
        u = np.asarray(z["u_cma_3d"], dtype=np.float32)
        v = np.asarray(z["v_cma_3d"], dtype=np.float32)
        if u.shape != shape or v.shape != shape:
            raise ValueError(f"CMA shape mismatch for {path}: u={u.shape}, v={v.shape}, expected={shape}")
        temporal_conf = (
            np.asarray(z["cma_temporal_conf_3d"], dtype=np.float32)
            if "cma_temporal_conf_3d" in z.files
            else np.ones(shape, dtype=np.float32)
        )
        temporal_change = (
            np.asarray(z["cma_temporal_change_speed_3d"], dtype=np.float32)
            if "cma_temporal_change_speed_3d" in z.files
            else np.zeros(shape, dtype=np.float32)
        )
        rapid_flag = (
            np.asarray(z["cma_rapid_change_flag_3d"], dtype=np.float32)
            if "cma_rapid_change_flag_3d" in z.files
            else np.zeros(shape, dtype=np.float32)
        )
    return {
        "u": u,
        "v": v,
        "temporal_conf": temporal_conf,
        "temporal_change": temporal_change,
        "rapid_flag": rapid_flag,
    }


def _alt_m(z: int) -> float:
    return float(ALT_MIN + int(z) * DELTA_ALT)


def _alt_band(alt_m: float) -> str:
    if alt_m >= 12000.0:
        return "alt_12km_plus"
    if alt_m >= 9000.0:
        return "alt_9_12km"
    if alt_m >= 6000.0:
        return "alt_6_9km"
    if alt_m >= 3000.0:
        return "alt_3_6km"
    return "alt_0_3km"


def _speed_band(speed_mps: float) -> str:
    if speed_mps >= 90.0:
        return "speed_90_plus"
    if speed_mps >= 60.0:
        return "speed_60_90"
    if speed_mps >= 30.0:
        return "speed_30_60"
    return "speed_0_30"


def _support_band(obs_count: int) -> str:
    if obs_count <= 0:
        return "support_count_0"
    if obs_count == 1:
        return "support_count_1"
    if obs_count <= 3:
        return "support_count_2_3"
    return "support_count_4_plus"


def _cma_conf_band(value: float) -> str:
    if not math.isfinite(value):
        return "cma_conf_nan"
    if value < 0.55:
        return "cma_conf_lt_0p55"
    if value < 0.8:
        return "cma_conf_0p55_0p8"
    return "cma_conf_ge_0p8"


def _error_band(value: float) -> str:
    if value >= 60.0:
        return "err_60_plus"
    if value >= 30.0:
        return "err_30_60"
    if value >= 15.0:
        return "err_15_30"
    return "err_0_15"


def _sigma_obs_mps(alt_m: float) -> float:
    if alt_m < 3000.0:
        return 2.2
    if alt_m < 6000.0:
        return 2.5
    return 2.8


def _sigma_repr_mps(alt_m: float, obs_count: int) -> float:
    sigma = 8.0
    if alt_m >= 12000.0:
        sigma *= 2.0
    elif alt_m >= 9000.0:
        sigma *= 1.5
    if obs_count <= 0:
        sigma *= 2.5
    elif obs_count == 1:
        sigma *= 1.5
    return sigma


def _point_diag_row(
    *,
    time_str: str,
    role: str,
    record: dict[str, Any],
    cma: dict[str, np.ndarray],
    strict_min_temporal_conf: float,
    strict_max_temporal_change_mps: float,
    sigma_bg_mps: float,
) -> dict[str, Any] | None:
    z = _safe_int(record.get("z"))
    y = _safe_int(record.get("y"))
    x = _safe_int(record.get("x"))
    shape = cma["u"].shape
    if not (0 <= z < shape[0] and 0 <= y < shape[1] and 0 <= x < shape[2]):
        return None

    gt_u = _safe_float(record.get("u"))
    gt_v = _safe_float(record.get("v"))
    bg_u = float(cma["u"][z, y, x])
    bg_v = float(cma["v"][z, y, x])
    temporal_conf = float(cma["temporal_conf"][z, y, x])
    temporal_change = float(cma["temporal_change"][z, y, x])
    rapid_flag = float(cma["rapid_flag"][z, y, x])
    cma_valid = (
        math.isfinite(bg_u)
        and math.isfinite(bg_v)
        and math.isfinite(temporal_conf)
        and math.isfinite(temporal_change)
        and temporal_conf >= float(strict_min_temporal_conf)
        and temporal_change <= float(strict_max_temporal_change_mps)
    )
    du = bg_u - gt_u
    dv = bg_v - gt_v
    vector_error = math.sqrt(du * du + dv * dv) if cma_valid else float("nan")
    gt_speed = math.sqrt(gt_u * gt_u + gt_v * gt_v)
    bg_speed = math.sqrt(bg_u * bg_u + bg_v * bg_v) if cma_valid else float("nan")
    alt_m = _alt_m(z)
    obs_count = _safe_int(record.get("obs_count"), 1)
    sigma_obs = _sigma_obs_mps(alt_m)
    sigma_repr = _sigma_repr_mps(alt_m, obs_count)
    sigma_total2 = sigma_obs * sigma_obs + sigma_repr * sigma_repr
    sigma_bg2 = float(sigma_bg_mps) * float(sigma_bg_mps)
    obs_influence_at_obs = sigma_bg2 / max(1e-9, sigma_bg2 + sigma_total2)
    analysis_error_var = sigma_bg2 * sigma_total2 / max(1e-9, sigma_bg2 + sigma_total2)
    return {
        "time_str": time_str,
        "role": role,
        "z": z,
        "y": y,
        "x": x,
        "alt_m": alt_m,
        "alt_band": _alt_band(alt_m),
        "obs_count": obs_count,
        "support_band": _support_band(obs_count),
        "gt_u": gt_u,
        "gt_v": gt_v,
        "gt_speed": gt_speed,
        "cma_u": bg_u,
        "cma_v": bg_v,
        "cma_speed": bg_speed,
        "cma_temporal_conf": temporal_conf,
        "cma_temporal_conf_band": _cma_conf_band(temporal_conf),
        "cma_temporal_change_mps": temporal_change,
        "cma_rapid_change_flag": rapid_flag,
        "cma_valid_strict_temporal": bool(cma_valid),
        "omb_u": du if cma_valid else float("nan"),
        "omb_v": dv if cma_valid else float("nan"),
        "omb_vector_error": vector_error,
        "omb_error_band": _error_band(vector_error) if cma_valid else "invalid_cma",
        "speed_band": _speed_band(gt_speed),
        "sigma_bg_mps": float(sigma_bg_mps),
        "sigma_obs_mps": sigma_obs,
        "sigma_repr_mps": sigma_repr,
        "sigma_total_mps": math.sqrt(sigma_total2),
        "oi_diag_obs_influence_at_obs": obs_influence_at_obs,
        "oi_diag_analysis_error_var": analysis_error_var,
    }


def _percentile(values: list[float], q: float) -> float:
    finite = [float(v) for v in values if math.isfinite(float(v))]
    if not finite:
        return float("nan")
    return float(np.percentile(np.asarray(finite, dtype=np.float64), q))


def _summary_from_points(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if bool(row.get("cma_valid_strict_temporal", False))]
    vec = [float(row["omb_vector_error"]) for row in valid]
    uerr = [float(row["omb_u"]) for row in valid]
    verr = [float(row["omb_v"]) for row in valid]
    influence = [float(row["oi_diag_obs_influence_at_obs"]) for row in valid]
    if not valid:
        return {
            "point_count": len(rows),
            "valid_count": 0,
            "valid_fraction": 0.0,
            "omb_mae_vector": float("nan"),
            "omb_rmse_vector": float("nan"),
            "omb_p50_vector": float("nan"),
            "omb_p90_vector": float("nan"),
            "omb_p95_vector": float("nan"),
            "omb_p99_vector": float("nan"),
            "omb_bias_u": float("nan"),
            "omb_bias_v": float("nan"),
            "oi_obs_influence_mean": float("nan"),
        }
    arr = np.asarray(vec, dtype=np.float64)
    return {
        "point_count": len(rows),
        "valid_count": len(valid),
        "valid_fraction": float(len(valid) / max(1, len(rows))),
        "omb_mae_vector": float(np.mean(arr)),
        "omb_rmse_vector": float(np.sqrt(np.mean(arr**2))),
        "omb_p50_vector": _percentile(vec, 50),
        "omb_p90_vector": _percentile(vec, 90),
        "omb_p95_vector": _percentile(vec, 95),
        "omb_p99_vector": _percentile(vec, 99),
        "omb_bias_u": float(np.mean(np.asarray(uerr, dtype=np.float64))),
        "omb_bias_v": float(np.mean(np.asarray(verr, dtype=np.float64))),
        "oi_obs_influence_mean": float(np.mean(np.asarray(influence, dtype=np.float64))),
    }


def _evaluate_frame(
    stage2_row: dict[str, Any],
    *,
    cma_proxy_dir: Path | None,
    cma_proxy_npz: Path | None,
    holdout_fraction: float,
    holdout_count: int,
    strict_min_temporal_conf: float,
    strict_max_temporal_change_mps: float,
    sigma_bg_mps: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    time_str = str(stage2_row["time_str"])
    npz_path = Path(stage2_row["multimodal_vox_path"])
    if not npz_path.is_absolute():
        npz_path = ROOT_DIR / npz_path
    npz = _load_stage2_npz(npz_path)
    shape = tuple(int(v) for v in np.asarray(npz[C2_GRID_SHAPE], dtype=np.int32).tolist())
    wind_records = _records(npz.get(C2_WIND_RECORDS))
    train_wind, holdout_wind = _split_holdout(wind_records, holdout_fraction, holdout_count)
    cma_path = cma_proxy_npz if cma_proxy_npz is not None else _find_cma_proxy_npz(cma_proxy_dir, time_str)
    if cma_path is None:
        return (
            {
                "time_str": time_str,
                "stage2_npz": str(npz_path),
                "cma_proxy_npz": "",
                "status": "missing_cma_proxy",
                "train_point_count": len(train_wind),
                "holdout_point_count": len(holdout_wind),
            },
            [],
        )
    cma = _load_cma_fields(cma_path, shape)
    point_rows: list[dict[str, Any]] = []
    for role, records in (("train_current", train_wind), ("holdout_current_report_only", holdout_wind)):
        for record in records:
            row = _point_diag_row(
                time_str=time_str,
                role=role,
                record=record,
                cma=cma,
                strict_min_temporal_conf=strict_min_temporal_conf,
                strict_max_temporal_change_mps=strict_max_temporal_change_mps,
                sigma_bg_mps=sigma_bg_mps,
            )
            if row is not None:
                point_rows.append(row)
    train_summary = _summary_from_points([row for row in point_rows if row["role"] == "train_current"])
    holdout_summary = _summary_from_points([row for row in point_rows if row["role"] == "holdout_current_report_only"])
    frame_summary = {
        "time_str": time_str,
        "stage2_npz": str(npz_path),
        "cma_proxy_npz": str(cma_path),
        "status": "ok",
        **{f"train_{key}": value for key, value in train_summary.items()},
        **{f"holdout_report_only_{key}": value for key, value in holdout_summary.items()},
    }
    return frame_summary, point_rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        fieldnames = keys
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _stratified_rows(point_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    group_specs = [
        ("all", lambda row: "all"),
        ("alt_band", lambda row: str(row.get("alt_band", ""))),
        ("speed_band", lambda row: str(row.get("speed_band", ""))),
        ("support_band", lambda row: str(row.get("support_band", ""))),
        ("cma_temporal_conf_band", lambda row: str(row.get("cma_temporal_conf_band", ""))),
        ("omb_error_band", lambda row: str(row.get("omb_error_band", ""))),
    ]
    for row in point_rows:
        role = str(row.get("role", ""))
        for group_type, get_value in group_specs:
            groups[(role, group_type, get_value(row))].append(row)
    out: list[dict[str, Any]] = []
    for (role, group_type, group_value), rows in sorted(groups.items()):
        summary = _summary_from_points(rows)
        out.append(
            {
                "role": role,
                "group_type": group_type,
                "group_value": group_value,
                **summary,
            }
        )
    return out


def _aggregate_frame_rows(frame_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in frame_rows if row.get("status") == "ok"]
    return {
        "frame_count": len(frame_rows),
        "ok_frame_count": len(ok),
        "missing_cma_proxy_count": len(frame_rows) - len(ok),
        "train_point_count": int(sum(int(row.get("train_point_count", 0)) for row in frame_rows)),
        "holdout_report_only_point_count": int(sum(int(row.get("holdout_report_only_point_count", 0)) for row in frame_rows)),
    }


def _load_baseline_rmse(path: Path | None) -> float | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return None
    vals = [float(row["rmse_vector"]) for row in payload if row.get("rmse_vector") is not None]
    if not vals:
        return None
    return float(np.mean(np.asarray(vals, dtype=np.float64)))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_report(
    path: Path,
    *,
    run_meta: dict[str, Any],
    aggregate: dict[str, Any],
    stratified: list[dict[str, Any]],
    baseline_rmse: float | None,
) -> None:
    train_all = next(
        (row for row in stratified if row["role"] == "train_current" and row["group_type"] == "all"),
        {},
    )
    holdout_all = next(
        (row for row in stratified if row["role"] == "holdout_current_report_only" and row["group_type"] == "all"),
        {},
    )
    train_rmse = float(train_all.get("omb_rmse_vector", float("nan")))
    train_p95 = float(train_all.get("omb_p95_vector", float("nan")))
    baseline_note = "not supplied"
    rmse_ratio = float("nan")
    if baseline_rmse is not None and baseline_rmse > 0:
        rmse_ratio = train_rmse / baseline_rmse
        baseline_note = f"{baseline_rmse:.6f} m/s"
    recommendation = "report_only_do_not_promote_to_m2"
    reasons = [
        "background_independent_of_holdout is not confirmed",
        "S4-OI-DIAG is diagnostics-only and does not modify official recon",
    ]
    if math.isfinite(rmse_ratio) and rmse_ratio > 1.5:
        reasons.append(f"train OMB RMSE is {rmse_ratio:.2f}x the Stage4 baseline frame RMSE")
    if math.isfinite(train_p95) and train_p95 > 30.0:
        reasons.append(f"train OMB P95 is high ({train_p95:.3f} m/s)")
    lines = [
        "# Stage4 OI Diagnostic Report",
        "",
        "## Scope",
        "",
        "- Mode: `S4-OI-DIAG`, report-only.",
        "- No 3D reconstruction NPZ files are written.",
        "- Official `recon_u/v/conf/mask` and point-eval logic are unchanged.",
        "- Train current aircraft observations are used for OMB reliability diagnostics; holdout rows are report-only side evidence.",
        "",
        "## Run",
        "",
        f"- Frames: {aggregate['ok_frame_count']}/{aggregate['frame_count']} ok",
        f"- Train current points: {aggregate['train_point_count']}",
        f"- Holdout report-only points: {aggregate['holdout_report_only_point_count']}",
        f"- CMA proxy dir: `{run_meta.get('cma_proxy_dir')}`",
        f"- Baseline Stage4 frame RMSE mean: {baseline_note}",
        "",
        "## OMB Summary",
        "",
        "| role | valid | RMSE | MAE | P95 | P99 | mean OI influence at obs |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| train_current | {train_all.get('valid_count', 0)} | "
            f"{float(train_all.get('omb_rmse_vector', float('nan'))):.6f} | "
            f"{float(train_all.get('omb_mae_vector', float('nan'))):.6f} | "
            f"{float(train_all.get('omb_p95_vector', float('nan'))):.6f} | "
            f"{float(train_all.get('omb_p99_vector', float('nan'))):.6f} | "
            f"{float(train_all.get('oi_obs_influence_mean', float('nan'))):.6f} |"
        ),
        (
            f"| holdout_report_only | {holdout_all.get('valid_count', 0)} | "
            f"{float(holdout_all.get('omb_rmse_vector', float('nan'))):.6f} | "
            f"{float(holdout_all.get('omb_mae_vector', float('nan'))):.6f} | "
            f"{float(holdout_all.get('omb_p95_vector', float('nan'))):.6f} | "
            f"{float(holdout_all.get('omb_p99_vector', float('nan'))):.6f} | "
            f"{float(holdout_all.get('oi_obs_influence_mean', float('nan'))):.6f} |"
        ),
        "",
        "## Recommendation",
        "",
        f"- Decision: `{recommendation}`.",
        *[f"- Reason: {reason}." for reason in reasons],
        "",
        "## Outputs",
        "",
        "- `oi_diag_frame_summary.csv`",
        "- `oi_diag_point_departures.csv`",
        "- `oi_diag_stratified_summary.csv`",
        "- `oi_diag_summary.json`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-summary", type=Path, default=DEFAULT_STAGE2_SUMMARY)
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--sample-count", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=20260614)
    parser.add_argument("--cma-proxy-dir", type=Path, default=DEFAULT_CMA_PROXY_DIR)
    parser.add_argument("--cma-proxy-npz", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--stage4-holdout-fraction", type=float, default=0.125)
    parser.add_argument("--stage4-holdout-count", type=int, default=0)
    parser.add_argument("--cma-strict-min-temporal-conf", type=float, default=0.55)
    parser.add_argument("--cma-strict-max-temporal-change-mps", type=float, default=8.0)
    parser.add_argument("--oi-sigma-bg-mps", type=float, default=12.0)
    parser.add_argument("--baseline-summary", type=Path, default=DEFAULT_BASELINE_SUMMARY)
    parser.add_argument("--background-independent-of-holdout", choices=["true", "false", "unknown"], default="unknown")
    args = parser.parse_args()

    started = time.time()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frame_times = _parse_frame_times(str(args.frame_times), args.frame_times_file)
    rows = _select_rows(_load_json(args.stage2_summary), frame_times)
    rows = _sample_rows(rows, int(args.sample_count), int(args.sample_seed))
    frame_rows: list[dict[str, Any]] = []
    point_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        frame_summary, frame_points = _evaluate_frame(
            row,
            cma_proxy_dir=args.cma_proxy_dir,
            cma_proxy_npz=args.cma_proxy_npz,
            holdout_fraction=float(args.stage4_holdout_fraction),
            holdout_count=int(args.stage4_holdout_count),
            strict_min_temporal_conf=float(args.cma_strict_min_temporal_conf),
            strict_max_temporal_change_mps=float(args.cma_strict_max_temporal_change_mps),
            sigma_bg_mps=float(args.oi_sigma_bg_mps),
        )
        frame_rows.append(frame_summary)
        point_rows.extend(frame_points)
        if idx == 1 or idx == len(rows) or idx % 25 == 0:
            print(f"[S4-OI-DIAG] {idx}/{len(rows)} frames", flush=True)

    stratified = _stratified_rows(point_rows)
    aggregate = _aggregate_frame_rows(frame_rows)
    baseline_rmse = _load_baseline_rmse(args.baseline_summary)
    run_meta = {
        "script": str(Path(__file__).resolve()),
        "stage2_summary": str(args.stage2_summary),
        "frame_times_file": str(args.frame_times_file or ""),
        "sample_count": int(args.sample_count),
        "sample_seed": int(args.sample_seed),
        "cma_proxy_dir": str(args.cma_proxy_dir or ""),
        "cma_proxy_npz": str(args.cma_proxy_npz or ""),
        "stage4_holdout_fraction": float(args.stage4_holdout_fraction),
        "stage4_holdout_count": int(args.stage4_holdout_count),
        "cma_strict_min_temporal_conf": float(args.cma_strict_min_temporal_conf),
        "cma_strict_max_temporal_change_mps": float(args.cma_strict_max_temporal_change_mps),
        "oi_sigma_bg_mps": float(args.oi_sigma_bg_mps),
        "background_independent_of_holdout": str(args.background_independent_of_holdout),
        "background_independence_confirmed": str(args.background_independent_of_holdout).lower() == "true",
        "elapsed_seconds": float(time.time() - started),
    }

    _write_csv(args.out_dir / "oi_diag_frame_summary.csv", frame_rows)
    _write_csv(args.out_dir / "oi_diag_point_departures.csv", point_rows)
    _write_csv(args.out_dir / "oi_diag_stratified_summary.csv", stratified)
    summary_payload = {
        "run_meta": run_meta,
        "aggregate": aggregate,
        "baseline_frame_rmse_mean": baseline_rmse,
        "stratified_summary": stratified,
    }
    (args.out_dir / "oi_diag_summary.json").write_text(
        json.dumps(_json_safe(summary_payload), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    _write_report(
        args.out_dir / "oi_diag_report.md",
        run_meta=run_meta,
        aggregate=aggregate,
        stratified=stratified,
        baseline_rmse=baseline_rmse,
    )
    print(args.out_dir / "oi_diag_report.md")


if __name__ == "__main__":
    main()
