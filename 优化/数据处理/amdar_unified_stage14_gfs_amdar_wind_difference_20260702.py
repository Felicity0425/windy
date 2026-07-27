#!/usr/bin/env python3
"""Compare current Stage12/13 Stage2 wind observations with available GFS background.

This is a report-only diagnostic. It does not modify Stage2/Stage4 inputs and it
does not materialize per-observation intermediate tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path("/data/LFT-W02_data/pengxu")
STAGE12_DIR = ROOT / "优化/数据处理/amdar_unified_stage12_stage4_baseline_reproduction_optimized_20260702"
DEFAULT_STAGE2_SUMMARY = STAGE12_DIR / "stage2_baseline_compat_200/stage2_multimodal_summary.json"
DEFAULT_GFS_ROI_DIR = ROOT / "优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/npz"
DEFAULT_GFS_CACHE_DIR = ROOT / "优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/cache_npz"
DEFAULT_OUT_DIR = ROOT / "优化/数据处理/amdar_unified_stage14_gfs_amdar_wind_difference_20260702"

LAT_MIN = 12.2
LAT_MAX = 54.2
LON_MIN = 73.0
LON_MAX = 135.0
ALT_MIN = 0.0
DELTA_ALT = 500.0


def parse_time(text: str) -> datetime:
    return datetime.strptime(str(text), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value


def load_background_npz(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as z:
        out = {
            "path": str(path),
            "time_str": str(z["time_str"]) if "time_str" in z.files else "",
            "cycle": str(z["cycle"]) if "cycle" in z.files else "",
            "forecast_hour": int(np.asarray(z["forecast_hour"]).reshape(-1)[0]) if "forecast_hour" in z.files else -1,
            "lat": np.asarray(z["lat"], dtype=np.float32),
            "lon": np.asarray(z["lon"], dtype=np.float32),
            "alt_km": np.asarray(z["alt_km"], dtype=np.float32),
            "u": np.asarray(z["u"], dtype=np.float32),
            "v": np.asarray(z["v"], dtype=np.float32),
        }
        if "source_frame_times" in z.files:
            out["source_frame_times"] = str(z["source_frame_times"])
    return out


def nearest_index(axis: np.ndarray, values: np.ndarray) -> np.ndarray:
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
        idx = work.size - 1 - idx
    return idx.astype(np.int32, copy=False)


def xyz_to_lat_lon_alt(z: np.ndarray, y: np.ndarray, x: np.ndarray, grid_shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _, h_dim, w_dim = grid_shape
    lat = LAT_MAX - (np.asarray(y, dtype=np.float32) + 0.5) / float(h_dim) * (LAT_MAX - LAT_MIN)
    lon = LON_MIN + (np.asarray(x, dtype=np.float32) + 0.5) / float(w_dim) * (LON_MAX - LON_MIN)
    alt_m = ALT_MIN + np.asarray(z, dtype=np.float32) * np.float32(DELTA_ALT)
    return lat.astype(np.float32), lon.astype(np.float32), alt_m.astype(np.float32)


def sample_background(background: dict[str, Any], z: np.ndarray, y: np.ndarray, x: np.ndarray, grid_shape: tuple[int, int, int]) -> dict[str, np.ndarray]:
    lat, lon, alt_m = xyz_to_lat_lon_alt(z, y, x, grid_shape)
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
    iz = nearest_index(bg_alt, alt_km)
    iy = nearest_index(bg_lat, lat)
    ix = nearest_index(bg_lon, lon)
    u = np.asarray(background["u"], dtype=np.float32)[iz, iy, ix]
    v = np.asarray(background["v"], dtype=np.float32)[iz, iy, ix]
    return {"lat": lat, "lon": lon, "alt_m": alt_m, "inside": inside, "bg_u": u, "bg_v": v}


def records_from_array(arr: np.ndarray) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if arr is None:
        return out
    for item in np.asarray(arr, dtype=object).reshape(-1):
        if isinstance(item, dict):
            out.append(item)
        elif hasattr(item, "item"):
            value = item.item()
            if isinstance(value, dict):
                out.append(value)
    return out


def float_field(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, default)
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def int_field(row: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        value = row.get(key, default)
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def met_dir_from_deg(u: float, v: float) -> float:
    return float((math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0)


def circular_diff_deg(a: float, b: float) -> float:
    return float(((a - b + 180.0) % 360.0) - 180.0)


def source_group(row: dict[str, Any], record_family: str) -> str:
    amdar = int_field(row, "amdar_rows")
    turb = int_field(row, "turb_rows")
    if record_family == "wind_records":
        if amdar > 0 and turb > 0:
            return "current_mixed_strict"
        if turb > 0:
            return "current_turb_strict"
        if amdar > 0:
            return "current_amdar_unexpected"
        return "current_unknown_strict"
    if amdar > 0 and turb > 0:
        return "context_mixed_support"
    if amdar > 0:
        return "context_amdar_support"
    if turb > 0:
        return "context_turb_support"
    return "context_unknown_support"


def altitude_bin(alt_m: float) -> str:
    if alt_m < 3000.0:
        return "0-3km"
    if alt_m < 6000.0:
        return "3-6km"
    if alt_m < 9000.0:
        return "6-9km"
    if alt_m < 12000.0:
        return "9-12km"
    return "12km+"


def speed_bin(speed: float) -> str:
    if speed < 5.0:
        return "lt5"
    if speed < 15.0:
        return "5-15"
    if speed < 30.0:
        return "15-30"
    if speed < 60.0:
        return "30-60"
    return "60+"


def delta_bin(minutes: float) -> str:
    if minutes == 0.0:
        return "exact_target_file"
    if minutes <= 30.0:
        return "le30min"
    if minutes <= 60.0:
        return "30-60min"
    if minutes <= 180.0:
        return "60-180min"
    return "gt180min"


@dataclass
class Stat:
    count: int = 0
    inside_count: int = 0
    vector_values: list[float] = field(default_factory=list)
    speed_diff_values: list[float] = field(default_factory=list)
    abs_speed_diff_values: list[float] = field(default_factory=list)
    direction_abs_values: list[float] = field(default_factory=list)
    direction_signed_values: list[float] = field(default_factory=list)
    obs_speed_values: list[float] = field(default_factory=list)
    bg_speed_values: list[float] = field(default_factory=list)
    du_sum: float = 0.0
    dv_sum: float = 0.0

    def add(self, metric: dict[str, float]) -> None:
        self.count += 1
        self.inside_count += 1
        vec = float(metric["vector_error_mps"])
        speed_diff = float(metric["speed_diff_obs_minus_gfs_mps"])
        self.vector_values.append(vec)
        self.speed_diff_values.append(speed_diff)
        self.abs_speed_diff_values.append(abs(speed_diff))
        self.obs_speed_values.append(float(metric["obs_speed_mps"]))
        self.bg_speed_values.append(float(metric["gfs_speed_mps"]))
        self.du_sum += float(metric["du_obs_minus_gfs_mps"])
        self.dv_sum += float(metric["dv_obs_minus_gfs_mps"])
        direction = metric.get("direction_diff_signed_deg")
        if direction is not None and math.isfinite(float(direction)):
            d = float(direction)
            self.direction_signed_values.append(d)
            self.direction_abs_values.append(abs(d))

    @staticmethod
    def pct(values: list[float], q: float) -> float:
        finite = np.asarray([v for v in values if math.isfinite(float(v))], dtype=np.float64)
        if not finite.size:
            return float("nan")
        return float(np.percentile(finite, q))

    @staticmethod
    def mean(values: list[float]) -> float:
        finite = np.asarray([v for v in values if math.isfinite(float(v))], dtype=np.float64)
        if not finite.size:
            return float("nan")
        return float(np.mean(finite))

    def as_dict(self) -> dict[str, Any]:
        vec = np.asarray([v for v in self.vector_values if math.isfinite(float(v))], dtype=np.float64)
        return {
            "count": int(self.count),
            "vector_rmse_mps": float(np.sqrt(np.mean(vec * vec))) if vec.size else float("nan"),
            "vector_mae_mps": self.mean(self.vector_values),
            "vector_p50_mps": self.pct(self.vector_values, 50),
            "vector_p95_mps": self.pct(self.vector_values, 95),
            "obs_speed_mean_mps": self.mean(self.obs_speed_values),
            "gfs_speed_mean_mps": self.mean(self.bg_speed_values),
            "speed_bias_obs_minus_gfs_mean_mps": self.mean(self.speed_diff_values),
            "abs_speed_diff_mean_mps": self.mean(self.abs_speed_diff_values),
            "abs_speed_diff_p50_mps": self.pct(self.abs_speed_diff_values, 50),
            "abs_speed_diff_p95_mps": self.pct(self.abs_speed_diff_values, 95),
            "u_bias_obs_minus_gfs_mean_mps": self.du_sum / self.count if self.count else float("nan"),
            "v_bias_obs_minus_gfs_mean_mps": self.dv_sum / self.count if self.count else float("nan"),
            "direction_valid_count_speed_ge5": int(len(self.direction_abs_values)),
            "abs_direction_diff_mean_deg_speed_ge5": self.mean(self.direction_abs_values),
            "abs_direction_diff_p50_deg_speed_ge5": self.pct(self.direction_abs_values, 50),
            "abs_direction_diff_p95_deg_speed_ge5": self.pct(self.direction_abs_values, 95),
            "direction_bias_signed_mean_deg_speed_ge5": self.mean(self.direction_signed_values),
        }


class Aggregator:
    def __init__(self) -> None:
        self.stats: dict[tuple[str, str], Stat] = defaultdict(Stat)

    def add(self, metric: dict[str, Any]) -> None:
        keys = {
            "overall": "all",
            "match_mode": str(metric["match_mode"]),
            "source_group": str(metric["source_group"]),
            "record_family": str(metric["record_family"]),
            "altitude_bin": str(metric["altitude_bin"]),
            "obs_speed_bin": str(metric["obs_speed_bin"]),
            "gfs_delta_bin": str(metric["gfs_delta_bin"]),
            "match_source": f"{metric['match_mode']}|{metric['source_group']}",
            "match_altitude": f"{metric['match_mode']}|{metric['altitude_bin']}",
            "source_altitude": f"{metric['source_group']}|{metric['altitude_bin']}",
            "source_speed": f"{metric['source_group']}|{metric['obs_speed_bin']}",
        }
        for group_name, group_value in keys.items():
            self.stats[(group_name, group_value)].add(metric)

    def rows(self) -> list[dict[str, Any]]:
        out = []
        for (group_name, group_value), stat in sorted(self.stats.items()):
            out.append({"group_name": group_name, "group_value": group_value, **stat.as_dict()})
        return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def discover_exact_files(gfs_roi_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in sorted(gfs_roi_dir.glob("gfs_roi_*.npz")):
        match = re.search(r"gfs_roi_(\d{14})\.npz$", path.name)
        if match:
            out[match.group(1)] = path
    return out


def discover_cache_files(gfs_cache_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(gfs_cache_dir.glob("gfs_src_*.npz")):
        try:
            with np.load(path, allow_pickle=False) as z:
                time_str = str(z["time_str"]) if "time_str" in z.files else ""
                cycle = str(z["cycle"]) if "cycle" in z.files else ""
                forecast_hour = int(np.asarray(z["forecast_hour"]).reshape(-1)[0]) if "forecast_hour" in z.files else -1
            if time_str:
                out.append({"time_str": time_str, "dt": parse_time(time_str), "path": path, "cycle": cycle, "forecast_hour": forecast_hour})
        except Exception:
            continue
    return sorted(out, key=lambda item: item["dt"])


def choose_nearest_cache(cache: list[dict[str, Any]], target_dt: datetime) -> tuple[dict[str, Any] | None, float]:
    if not cache:
        return None, float("nan")
    best = min(cache, key=lambda item: abs((item["dt"] - target_dt).total_seconds()))
    delta_min = abs((best["dt"] - target_dt).total_seconds()) / 60.0
    return best, float(delta_min)


def process_records_for_background(
    npz: Any,
    background: dict[str, Any],
    match_mode: str,
    match_delta_min: float,
    aggregator: Aggregator,
) -> tuple[int, int, dict[str, int]]:
    grid_shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int32).tolist())
    families = [
        ("wind_records", records_from_array(npz["wind_records"])),
        ("context_wind_records", records_from_array(npz["context_wind_records"])),
    ]
    total = 0
    inside_total = 0
    source_counts: dict[str, int] = defaultdict(int)
    for family, rows in families:
        if not rows:
            continue
        z = np.asarray([int_field(row, "z") for row in rows], dtype=np.int32)
        y = np.asarray([int_field(row, "y") for row in rows], dtype=np.int32)
        x = np.asarray([int_field(row, "x") for row in rows], dtype=np.int32)
        sampled = sample_background(background, z, y, x, grid_shape)
        for idx, row in enumerate(rows):
            total += 1
            group = source_group(row, family)
            source_counts[group] += 1
            if not bool(sampled["inside"][idx]):
                continue
            obs_u = float_field(row, "u")
            obs_v = float_field(row, "v")
            bg_u = float(sampled["bg_u"][idx])
            bg_v = float(sampled["bg_v"][idx])
            if not all(math.isfinite(v) for v in (obs_u, obs_v, bg_u, bg_v)):
                continue
            obs_speed = math.hypot(obs_u, obs_v)
            bg_speed = math.hypot(bg_u, bg_v)
            obs_dir = met_dir_from_deg(obs_u, obs_v)
            bg_dir = met_dir_from_deg(bg_u, bg_v)
            direction_diff = circular_diff_deg(obs_dir, bg_dir) if obs_speed >= 5.0 and bg_speed >= 5.0 else float("nan")
            metric = {
                "match_mode": match_mode,
                "record_family": family,
                "source_group": group,
                "altitude_bin": altitude_bin(float(sampled["alt_m"][idx])),
                "obs_speed_bin": speed_bin(obs_speed),
                "gfs_delta_bin": delta_bin(match_delta_min),
                "obs_speed_mps": obs_speed,
                "gfs_speed_mps": bg_speed,
                "du_obs_minus_gfs_mps": obs_u - bg_u,
                "dv_obs_minus_gfs_mps": obs_v - bg_v,
                "speed_diff_obs_minus_gfs_mps": obs_speed - bg_speed,
                "vector_error_mps": math.hypot(obs_u - bg_u, obs_v - bg_v),
                "direction_diff_signed_deg": direction_diff,
            }
            aggregator.add(metric)
            inside_total += 1
    return total, inside_total, dict(source_counts)


def first_row(rows: list[dict[str, Any]], group_name: str, group_value: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("group_name") == group_name and row.get("group_value") == group_value:
            return row
    return None


def fmt(value: Any, digits: int = 3) -> str:
    try:
        v = float(value)
        if not math.isfinite(v):
            return "nan"
        return f"{v:.{digits}f}"
    except Exception:
        return str(value)


def write_markdown(path: Path, summary: dict[str, Any], aggregate_rows: list[dict[str, Any]]) -> None:
    exact_all = first_row(aggregate_rows, "match_mode", "exact_frame")
    nearest_all = first_row(aggregate_rows, "match_mode", "nearest_cache")
    exact_amdar = first_row(aggregate_rows, "match_source", "exact_frame|context_amdar_support")
    nearest_amdar = first_row(aggregate_rows, "match_source", "nearest_cache|context_amdar_support")
    nearest_turb = first_row(aggregate_rows, "match_source", "nearest_cache|current_turb_strict")

    lines = [
        "# Stage14 GFS vs AMDAR/TURB wind difference diagnostic",
        "",
        f"- Generated: `{summary['generated_utc']}`",
        f"- Stage2 summary: `{summary['inputs']['stage2_summary']}`",
        f"- GFS ROI dir: `{summary['inputs']['gfs_roi_dir']}`",
        f"- GFS cache dir: `{summary['inputs']['gfs_cache_dir']}`",
        f"- Stage2 frames: `{summary['frame_counts']['stage2_frames']}`",
        f"- Exact GFS target-frame matches: `{summary['frame_counts']['exact_frame_matches']}`",
        f"- Nearest-cache frame matches: `{summary['frame_counts']['nearest_cache_matches']}`",
        f"- Nearest-cache delta minutes p50/p95/max: `{fmt(summary['nearest_cache_delta_minutes']['p50'])}` / `{fmt(summary['nearest_cache_delta_minutes']['p95'])}` / `{fmt(summary['nearest_cache_delta_minutes']['max'])}`",
        "",
        "## Key Metrics",
        "",
        "| subset | count | vector RMSE m/s | vector p95 m/s | obs speed mean | GFS speed mean | speed bias obs-GFS | abs dir diff mean deg | abs dir diff p95 deg |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, row in [
        ("exact_frame all", exact_all),
        ("exact_frame AMDAR support", exact_amdar),
        ("nearest_cache all", nearest_all),
        ("nearest_cache AMDAR support", nearest_amdar),
        ("nearest_cache current TURB strict", nearest_turb),
    ]:
        if row is None:
            continue
        lines.append(
            "| "
            + label
            + f" | {row['count']} | {fmt(row['vector_rmse_mps'])} | {fmt(row['vector_p95_mps'])} | {fmt(row['obs_speed_mean_mps'])} | {fmt(row['gfs_speed_mean_mps'])} | {fmt(row['speed_bias_obs_minus_gfs_mean_mps'])} | {fmt(row['abs_direction_diff_mean_deg_speed_ge5'])} | {fmt(row['abs_direction_diff_p95_deg_speed_ge5'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- GFS should be treated as a weak, gated background prior, not as dense truth and not as a replacement for AMDAR.",
            "- The current Stage12/13 failure mode is sparse/context-dominated reconstruction; GFS can help fill no-observation or low-confidence voxels, but strong weighting will smooth local aircraft wind and can worsen high-wind tails.",
            "- Negative speed bias means observed AMDAR/TURB speed is lower than GFS at matched voxels; positive means the aircraft observation is stronger than GFS.",
            "- Direction metrics are computed only where both observed and GFS speeds are at least 5 m/s, because low-speed direction is not physically stable.",
            "",
            "## Recommended Fusion Direction",
            "",
            "1. Keep AMDAR support observations; do not delete AMDAR.",
            "2. Add GFS as `cma_reanalysis_background`/background-style weak prior with diagnostic gating, small weight, and no use as holdout truth.",
            "3. Downweight or disable GFS where aircraft support is current/high-confidence or where GFS-aircraft vector departure is large.",
            "4. Validate as a Stage4 experiment against strict TURB holdout before promoting it into the main Stage1-4 pipeline.",
            "",
            "## Outputs",
            "",
            f"- Aggregate CSV: `{summary['outputs']['aggregate_csv']}`",
            f"- Frame match CSV: `{summary['outputs']['frame_match_csv']}`",
            f"- Summary JSON: `{summary['outputs']['summary_json']}`",
            f"- Handover: `{summary['outputs']['handover_md']}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_handover(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Next Agent Handover: Stage14 GFS vs AMDAR/TURB wind difference",
        "",
        "## What was done",
        "",
        "- Compared the current Stage12/13 Stage2 wind records with available historical GFS background.",
        "- Kept AMDAR intact; this is diagnostic only and does not delete, filter, or alter Stage2/Stage4 inputs.",
        "- Produced aggregate statistics only, without full per-observation materialization.",
        "",
        "## Important paths",
        "",
        f"- Main analysis: `{summary['outputs']['analysis_md']}`",
        f"- Summary JSON: `{summary['outputs']['summary_json']}`",
        f"- Aggregate CSV: `{summary['outputs']['aggregate_csv']}`",
        f"- Frame match CSV: `{summary['outputs']['frame_match_csv']}`",
        f"- Stage12 baseline doc: `{STAGE12_DIR / 'stage12_baseline_reproduction_results_analysis_and_next_steps.md'}`",
        f"- Stage13 source ablation doc: `{ROOT / '优化/数据处理/amdar_unified_stage13_stage4_source_ablation_20260702/stage13_stage4_source_ablation_results_analysis_and_next_steps.md'}`",
        f"- Old GFS diagnostic: `{ROOT / '优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.md'}`",
        "",
        "## Result summary",
        "",
        f"- Stage2 frames: `{summary['frame_counts']['stage2_frames']}`",
        f"- Exact target-frame GFS matches: `{summary['frame_counts']['exact_frame_matches']}`",
        f"- Nearest cache matches: `{summary['frame_counts']['nearest_cache_matches']}`",
        f"- Nearest-cache delta p50/p95/max minutes: `{summary['nearest_cache_delta_minutes']['p50']:.3f}` / `{summary['nearest_cache_delta_minutes']['p95']:.3f}` / `{summary['nearest_cache_delta_minutes']['max']:.3f}`",
        "",
        "## Project understanding",
        "",
        "- Big Stage1: data cleaning/QC and role policy. AMDAR is support-only; strict truth is TURB T0/S in the current compatible design.",
        "- Big Stage2: organize observations into per-frame multimodal voxels; it should not perform reconstruction.",
        "- Big Stage3: build agent/context packaging and compatibility artifacts.",
        "- Big Stage4: reconstruct/evaluate wind fields against strict holdout; this is where GFS should be tested as weak background.",
        "",
        "## Recommended next step",
        "",
        "- Run a constrained Stage4 GFS-background experiment on the same 200-frame Stage12/13 set.",
        "- Use GFS only as weak prior in low-confidence/no-observation regions; gate it off near current high-confidence TURB and strong AMDAR support.",
        "- Compare against Stage13 best `S10/S11` and require strict holdout RMSE/p95/max to improve, not merely visualization to look smoother.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage2-summary", type=Path, default=DEFAULT_STAGE2_SUMMARY)
    parser.add_argument("--gfs-roi-dir", type=Path, default=DEFAULT_GFS_ROI_DIR)
    parser.add_argument("--gfs-cache-dir", type=Path, default=DEFAULT_GFS_CACHE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = read_json(args.stage2_summary)
    exact_files = discover_exact_files(args.gfs_roi_dir)
    cache_files = discover_cache_files(args.gfs_cache_dir)

    aggregator = Aggregator()
    frame_rows: list[dict[str, Any]] = []
    nearest_deltas: list[float] = []
    exact_match_count = 0
    nearest_match_count = 0

    for item in summary_rows:
        time_str = str(item["time_str"])
        target_dt = parse_time(time_str)
        npz_path = Path(item.get("multimodal_vox_path") or item.get("vox_path"))
        with np.load(npz_path, allow_pickle=True) as npz:
            exact_path = exact_files.get(time_str)
            frame_payload: dict[str, Any] = {
                "time_str": time_str,
                "stage2_npz": str(npz_path),
                "exact_frame_gfs": str(exact_path) if exact_path else "",
                "nearest_cache_gfs": "",
                "nearest_cache_time_str": "",
                "nearest_cache_delta_minutes": "",
                "exact_total_records": 0,
                "exact_inside_records": 0,
                "nearest_total_records": 0,
                "nearest_inside_records": 0,
            }
            if exact_path is not None:
                bg = load_background_npz(exact_path)
                total, inside, source_counts = process_records_for_background(npz, bg, "exact_frame", 0.0, aggregator)
                exact_match_count += 1
                frame_payload["exact_total_records"] = total
                frame_payload["exact_inside_records"] = inside
                for key, value in source_counts.items():
                    frame_payload[f"exact_source_count_{key}"] = value

            nearest, delta_min = choose_nearest_cache(cache_files, target_dt)
            if nearest is not None:
                bg = load_background_npz(Path(nearest["path"]))
                total, inside, source_counts = process_records_for_background(npz, bg, "nearest_cache", delta_min, aggregator)
                nearest_match_count += 1
                nearest_deltas.append(delta_min)
                frame_payload["nearest_cache_gfs"] = str(nearest["path"])
                frame_payload["nearest_cache_time_str"] = str(nearest["time_str"])
                frame_payload["nearest_cache_delta_minutes"] = f"{delta_min:.6f}"
                frame_payload["nearest_total_records"] = total
                frame_payload["nearest_inside_records"] = inside
                for key, value in source_counts.items():
                    frame_payload[f"nearest_source_count_{key}"] = value
            frame_rows.append(frame_payload)

    aggregate_rows = aggregator.rows()
    aggregate_csv = args.out_dir / "stage14_gfs_amdar_wind_difference_aggregate.csv"
    frame_csv = args.out_dir / "stage14_gfs_frame_match_summary.csv"
    summary_json = args.out_dir / "stage14_gfs_amdar_wind_difference_summary.json"
    analysis_md = args.out_dir / "stage14_gfs_amdar_wind_difference_analysis_and_next_steps.md"
    handover_md = args.out_dir / "next_agent_handover_after_stage14_gfs_amdar_wind_difference.md"

    write_csv(aggregate_csv, aggregate_rows)
    write_csv(frame_csv, frame_rows)

    delta_arr = np.asarray(nearest_deltas, dtype=np.float64)
    summary = {
        "generated_utc": iso_utc(),
        "inputs": {
            "stage2_summary": str(args.stage2_summary),
            "gfs_roi_dir": str(args.gfs_roi_dir),
            "gfs_cache_dir": str(args.gfs_cache_dir),
        },
        "frame_counts": {
            "stage2_frames": len(summary_rows),
            "gfs_roi_files": len(exact_files),
            "gfs_cache_files": len(cache_files),
            "exact_frame_matches": exact_match_count,
            "nearest_cache_matches": nearest_match_count,
        },
        "nearest_cache_delta_minutes": {
            "min": float(np.min(delta_arr)) if delta_arr.size else float("nan"),
            "p50": float(np.percentile(delta_arr, 50)) if delta_arr.size else float("nan"),
            "p95": float(np.percentile(delta_arr, 95)) if delta_arr.size else float("nan"),
            "max": float(np.max(delta_arr)) if delta_arr.size else float("nan"),
            "le30_count": int(np.sum(delta_arr <= 30.0)) if delta_arr.size else 0,
            "le60_count": int(np.sum(delta_arr <= 60.0)) if delta_arr.size else 0,
            "le180_count": int(np.sum(delta_arr <= 180.0)) if delta_arr.size else 0,
        },
        "key_rows": {
            "exact_all": first_row(aggregate_rows, "match_mode", "exact_frame"),
            "exact_amdar_support": first_row(aggregate_rows, "match_source", "exact_frame|context_amdar_support"),
            "nearest_all": first_row(aggregate_rows, "match_mode", "nearest_cache"),
            "nearest_amdar_support": first_row(aggregate_rows, "match_source", "nearest_cache|context_amdar_support"),
            "nearest_current_turb_strict": first_row(aggregate_rows, "match_source", "nearest_cache|current_turb_strict"),
        },
        "outputs": {
            "aggregate_csv": str(aggregate_csv),
            "frame_match_csv": str(frame_csv),
            "summary_json": str(summary_json),
            "analysis_md": str(analysis_md),
            "handover_md": str(handover_md),
        },
    }
    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(to_jsonable(summary), f, ensure_ascii=False, indent=2)
    write_markdown(analysis_md, summary, aggregate_rows)
    write_handover(handover_md, summary)
    print(json.dumps(to_jsonable(summary["key_rows"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
