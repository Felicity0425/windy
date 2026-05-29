"""Stage5 v1: ROI-local PINN-proxy + diffusion-style wind refinement.

This script is deliberately independent from the frozen Stage4 chain. It reads
Stage4 sparse_lossless NPZ files, builds a local ROI volume, preserves direct
wind anchors, applies a conservative diffusion-style smoothing loop with a
small divergence-damping PINN proxy, and writes sparse refined outputs.

Important scope note:
    This is not a trained neural diffusion model. It is a runnable Stage5
    scaffold for physics-aware ROI refinement and for defining the interfaces
    that a future learned PINN/diffusion model should consume and produce.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

ROOT_DIR = Path(__file__).resolve().parent.parent
STAGE_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.stage5_background_utils import load_background, load_background_candidates


DEFAULT_STAGE4_DIR = Path("/data/LFT-W02_data/pengxu/stage4_output_v2")
DEFAULT_STAGE5_DIR = Path("/data/LFT-W02_data/pengxu/stage5_output_v1")
DEFAULT_BACKGROUND_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/era5_roi_npz")
DEFAULT_BACKGROUND_DIRS = [
    Path("/data/LFT-W02_data/pengxu/stage5_external_background/era5_roi"),
    Path("/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz"),
    Path("/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz"),
]

LAT_MIN = 12.2
LAT_MAX = 54.2
LON_MIN = 73.0
LON_MAX = 135.0
ALT_STEP_M = 500.0


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "none", "no")
    return bool(value)


def _num(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default) or default)
    except (TypeError, ValueError):
        return float(default)


def _int(row: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(row.get(key, default) or default)
    except (TypeError, ValueError):
        return int(default)


def _time_key(row: dict[str, Any]) -> tuple[int, str]:
    return (_int(row, "source_index", 0), str(row.get("time_str", "")))


def _frame_id(row: dict[str, Any]) -> str:
    return str(row.get("time_str") or Path(str(row.get("filename", ""))).stem.replace("frame_", ""))


def _register_selection(
    selected: "OrderedDict[str, dict[str, Any]]",
    row: dict[str, Any] | None,
    reason: str,
) -> None:
    if row is None:
        return
    key = _frame_id(row)
    if key not in selected:
        selected[key] = {"row": row, "reasons": []}
    if reason not in selected[key]["reasons"]:
        selected[key]["reasons"].append(reason)


def _nearest_by_metric(rows: list[dict[str, Any]], key: str, target: float) -> dict[str, Any] | None:
    if not rows:
        return None
    return min(rows, key=lambda r: (abs(_num(r, key) - target), _time_key(r)))


def _max_by_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda r: (_num(r, key), -_int(r, "source_index", 0)))


def _select_representative_rows(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    triggered = [r for r in summary if _truthy(r.get("recon_triggered"))]
    nontriggered = [r for r in summary if not _truthy(r.get("recon_triggered"))]

    if triggered:
        coverages = np.asarray([_num(r, "recon_coverage_ratio") for r in triggered], dtype=np.float64)
        for q in (0.25, 0.50, 0.75):
            _register_selection(
                selected,
                _nearest_by_metric(triggered, "recon_coverage_ratio", float(np.quantile(coverages, q))),
                f"coverage_q{int(q * 100)}",
            )

    high_domain = [
        r
        for r in triggered
        if _int(r, "recon_domain_voxels") >= 500 and _num(r, "recon_coverage_ratio") > 0.0
    ]
    _register_selection(selected, _max_by_metric(high_domain, "recon_coverage_ratio"), "max_coverage_domain_ge_500")

    for metric, reason in (
        ("hazard_alert_voxels", "max_hazard_alert"),
        ("temporal_fill_voxels", "max_temporal_fill"),
        ("support_expand_voxels", "max_support_expand"),
        ("anchor_restore_voxels", "max_anchor_restore"),
        ("anchor_force_voxels", "max_anchor_force"),
    ):
        positives = [r for r in summary if _num(r, metric) > 0.0]
        _register_selection(selected, _max_by_metric(positives, metric), reason)

    zero_fill_triggered = [
        r
        for r in triggered
        if _int(r, "recon_filled_voxels") == 0 or _num(r, "recon_coverage_ratio") == 0.0
    ]
    _register_selection(
        selected,
        sorted(zero_fill_triggered, key=_time_key)[0] if zero_fill_triggered else None,
        "triggered_zero_recon",
    )

    if nontriggered:
        nontriggered_sorted = sorted(nontriggered, key=_time_key)
        _register_selection(selected, nontriggered_sorted[len(nontriggered_sorted) // 2], "nontriggered_mid_time")

    rows = [item["row"] | {"selection_reasons": item["reasons"]} for item in selected.values()]
    return sorted(rows, key=_time_key)


def _select_frame_rows(summary: list[dict[str, Any]], frame_times: str) -> list[dict[str, Any]]:
    wanted = [token.strip() for token in frame_times.split(",") if token.strip()]
    if not wanted:
        raise ValueError("--frame-times is required when --selection=frames")
    by_time = {str(row.get("time_str", "")): row for row in summary}
    missing = [time for time in wanted if time not in by_time]
    if missing:
        raise ValueError(f"Frame times not found in summary: {', '.join(missing)}")
    rows = []
    for time in wanted:
        row = dict(by_time[time])
        row["selection_reasons"] = ["requested_frame"]
        rows.append(row)
    return rows


def _linear_to_zyx(idx: np.ndarray, shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _, h_dim, w_dim = shape
    idx64 = np.asarray(idx, dtype=np.int64)
    z = idx64 // (h_dim * w_dim)
    rem = idx64 % (h_dim * w_dim)
    y = rem // w_dim
    x = rem % w_dim
    return z.astype(np.int32, copy=False), y.astype(np.int32, copy=False), x.astype(np.int32, copy=False)


def _zyx_to_linear(z: np.ndarray, y: np.ndarray, x: np.ndarray, shape: tuple[int, int, int]) -> np.ndarray:
    _, h_dim, w_dim = shape
    return (np.asarray(z, dtype=np.int64) * h_dim * w_dim + np.asarray(y, dtype=np.int64) * w_dim + np.asarray(x, dtype=np.int64)).astype(np.uint32)


def _xy_to_lonlat(x: np.ndarray, y: np.ndarray, h_dim: int, w_dim: int) -> tuple[np.ndarray, np.ndarray]:
    lon = LON_MIN + (np.asarray(x, dtype=np.float64) + 0.5) * (LON_MAX - LON_MIN) / max(1, w_dim)
    lat = LAT_MAX - (np.asarray(y, dtype=np.float64) + 0.5) * (LAT_MAX - LAT_MIN) / max(1, h_dim)
    return lon.astype(np.float32, copy=False), lat.astype(np.float32, copy=False)


def _read_source(
    npz: np.lib.npyio.NpzFile,
    idx_key: str,
    u_key: str,
    v_key: str,
    *,
    conf_key: str | None = None,
    fallback_conf: float = 1.0,
) -> dict[str, np.ndarray]:
    if idx_key not in npz.files or u_key not in npz.files or v_key not in npz.files:
        empty_i = np.asarray([], dtype=np.int64)
        empty_f = np.asarray([], dtype=np.float32)
        return {"idx": empty_i, "u": empty_f, "v": empty_f, "conf": empty_f}
    idx = np.asarray(npz[idx_key], dtype=np.int64)
    u = np.asarray(npz[u_key], dtype=np.float32)
    v = np.asarray(npz[v_key], dtype=np.float32)
    n = min(idx.size, u.size, v.size)
    idx = idx[:n]
    u = u[:n]
    v = v[:n]
    if conf_key and conf_key in npz.files:
        conf = np.asarray(npz[conf_key], dtype=np.float32)[:n]
        if conf.size < n:
            conf = np.pad(conf, (0, n - conf.size), constant_values=fallback_conf)
    else:
        conf = np.full(n, float(fallback_conf), dtype=np.float32)
    keep = np.isfinite(u) & np.isfinite(v) & np.isfinite(conf)
    return {"idx": idx[keep], "u": u[keep], "v": v[keep], "conf": np.clip(conf[keep], 0.0, 1.0)}


def _split_anchor_holdout(source: dict[str, np.ndarray], every: int) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    every = int(every)
    n = int(np.asarray(source.get("idx", [])).size)
    if every <= 1 or n < every:
        empty_i = np.asarray([], dtype=np.int64)
        empty_f = np.asarray([], dtype=np.float32)
        return source, {"idx": empty_i, "u": empty_f, "v": empty_f, "conf": empty_f}
    pos = np.arange(n)
    holdout = (pos % every) == (every - 1)
    train = ~holdout
    return (
        {key: np.asarray(value)[train] for key, value in source.items()},
        {key: np.asarray(value)[holdout] for key, value in source.items()},
    )


def _load_stage4_sparse(npz_path: Path) -> dict[str, Any]:
    with np.load(npz_path, allow_pickle=False) as npz:
        required = {"grid_shape", "recon_idx", "recon_u_val", "recon_v_val", "recon_conf_val", "recon_mask_val"}
        missing = sorted(required - set(npz.files))
        if missing:
            raise KeyError(f"{npz_path} is missing required keys: {', '.join(missing)}")
        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int64).tolist())
        recon_idx = np.asarray(npz["recon_idx"], dtype=np.int64)
        recon_u = np.asarray(npz["recon_u_val"], dtype=np.float32)
        recon_v = np.asarray(npz["recon_v_val"], dtype=np.float32)
        recon_conf = np.asarray(npz["recon_conf_val"], dtype=np.float32)
        recon_mask = np.asarray(npz["recon_mask_val"], dtype=np.float32)
        direct_sources = {
            "wind": _read_source(npz, "uv_idx", "u_val", "v_val", conf_key="wind_conf_val", fallback_conf=0.85),
            "amdar": _read_source(npz, "amdar_idx", "amdar_u_val", "amdar_v_val", fallback_conf=1.0),
            "turb": _read_source(npz, "turb_idx", "turb_u_val", "turb_v_val", fallback_conf=0.90),
        }
    n = min(recon_idx.size, recon_u.size, recon_v.size, recon_conf.size, recon_mask.size)
    recon_idx = recon_idx[:n]
    recon_u = recon_u[:n]
    recon_v = recon_v[:n]
    recon_conf = recon_conf[:n]
    recon_mask = recon_mask[:n]
    keep = (recon_mask > 0) & np.isfinite(recon_u) & np.isfinite(recon_v) & np.isfinite(recon_conf)
    return {
        "shape": shape,
        "recon": {
            "idx": recon_idx[keep],
            "u": recon_u[keep],
            "v": recon_v[keep],
            "conf": np.clip(recon_conf[keep], 0.0, 1.0),
        },
        "direct_sources": direct_sources,
    }


def _load_stage5_as_background(npz_path: Path) -> dict[str, Any]:
    with np.load(npz_path, allow_pickle=False) as npz:
        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int64).tolist())
        idx = np.asarray(npz["refined_idx"], dtype=np.int64)
        u = np.asarray(npz["refined_u_val"], dtype=np.float32)
        v = np.asarray(npz["refined_v_val"], dtype=np.float32)
        time_str = str(npz["time_str"]) if "time_str" in npz.files else npz_path.stem
    z, y, x = _linear_to_zyx(idx, shape)
    field_u = np.zeros(shape, dtype=np.float32)
    field_v = np.zeros(shape, dtype=np.float32)
    mask = np.zeros(shape, dtype=bool)
    field_u[z, y, x] = u
    field_v[z, y, x] = v
    mask[z, y, x] = True
    if np.any(mask):
        u_mean, count = _neighbor_mean(field_u, mask)
        v_mean, _ = _neighbor_mean(field_v, mask)
        fill = (~mask) & (count > 0)
        field_u[fill] = u_mean[fill]
        field_v[fill] = v_mean[fill]
    z_dim, h_dim, w_dim = shape
    lon_axis = LON_MIN + (np.arange(w_dim, dtype=np.float32) + 0.5) * (LON_MAX - LON_MIN) / max(1, w_dim)
    lat_axis = LAT_MAX - (np.arange(h_dim, dtype=np.float32) + 0.5) * (LAT_MAX - LAT_MIN) / max(1, h_dim)
    alt_axis = np.arange(z_dim, dtype=np.float32) * (ALT_STEP_M / 1000.0)
    return {
        "path": f"internal_stage5:{npz_path}",
        "time_str": time_str,
        "lat": lat_axis,
        "lon": lon_axis,
        "alt_km": alt_axis,
        "u": field_u,
        "v": field_v,
    }


def _nearest_indices(values: np.ndarray, query: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    query = np.asarray(query, dtype=np.float32)
    if values.size == 0 or query.size == 0:
        return np.asarray([], dtype=np.int64)
    order = np.argsort(values)
    sorted_values = values[order]
    pos = np.searchsorted(sorted_values, query)
    left = np.clip(pos - 1, 0, sorted_values.size - 1)
    right = np.clip(pos, 0, sorted_values.size - 1)
    choose_right = np.abs(sorted_values[right] - query) < np.abs(sorted_values[left] - query)
    return order[np.where(choose_right, right, left)].astype(np.int64, copy=False)


def _sample_background_to_local(
    background: dict[str, Any] | None,
    bbox: tuple[int, int, int, int, int, int],
    local_shape: tuple[int, int, int],
    stage4_shape: tuple[int, int, int],
) -> dict[str, np.ndarray] | None:
    if background is None:
        return None
    z0, _, y0, _, x0, _ = bbox
    lz, ly, lx = local_shape
    _, h_dim, w_dim = stage4_shape
    gz = np.arange(z0, z0 + lz, dtype=np.float32)
    gy = np.arange(y0, y0 + ly, dtype=np.float32)
    gx = np.arange(x0, x0 + lx, dtype=np.float32)
    lon, _ = _xy_to_lonlat(gx, np.zeros_like(gx), h_dim, w_dim)
    _, lat = _xy_to_lonlat(np.zeros_like(gy), gy, h_dim, w_dim)
    alt_km = gz * (ALT_STEP_M / 1000.0)

    bz = _nearest_indices(background["alt_km"], alt_km)
    by = _nearest_indices(background["lat"], lat)
    bx = _nearest_indices(background["lon"], lon)
    if bz.size == 0 or by.size == 0 or bx.size == 0:
        return None
    u = background["u"][bz[:, None, None], by[None, :, None], bx[None, None, :]]
    v = background["v"][bz[:, None, None], by[None, :, None], bx[None, None, :]]
    sampled = {
        "u": np.asarray(u, dtype=np.float32),
        "v": np.asarray(v, dtype=np.float32),
        "path": str(background.get("path", "")),
    }
    for key in ("w", "vertical_velocity", "temperature", "geopotential"):
        if key in background and np.asarray(background[key]).shape == np.asarray(background["u"]).shape:
            sampled[key] = np.asarray(background[key], dtype=np.float32)[bz[:, None, None], by[None, :, None], bx[None, None, :]]
    return sampled


def _background_anchor_stats(
    sampled: dict[str, np.ndarray] | None,
    anchor_mask: np.ndarray,
    anchor_u: np.ndarray,
    anchor_v: np.ndarray,
) -> dict[str, float]:
    if sampled is None or not np.any(anchor_mask):
        return {
            "anchor_rmse": 0.0,
            "anchor_rmse_scaled": 0.0,
            "anchor_speed_bias": 0.0,
            "anchor_count": 0.0,
            "anchor_cosine_mean": 0.0,
            "speed_scale": 1.0,
        }
    bg_u = np.asarray(sampled["u"], dtype=np.float32)
    bg_v = np.asarray(sampled["v"], dtype=np.float32)
    mask = np.asarray(anchor_mask, dtype=bool)
    a_u = np.asarray(anchor_u, dtype=np.float32)[mask]
    a_v = np.asarray(anchor_v, dtype=np.float32)[mask]
    b_u = bg_u[mask]
    b_v = bg_v[mask]
    err2 = (b_u - a_u) ** 2 + (b_v - a_v) ** 2
    bg_speed = np.sqrt(b_u ** 2 + b_v ** 2)
    anchor_speed = np.sqrt(a_u ** 2 + a_v ** 2)
    speed_scale = float(np.median(anchor_speed) / max(np.median(bg_speed), 1e-6)) if bg_speed.size else 1.0
    scaled_u = b_u * speed_scale
    scaled_v = b_v * speed_scale
    err2_scaled = (scaled_u - a_u) ** 2 + (scaled_v - a_v) ** 2
    dot = a_u * b_u + a_v * b_v
    cosine = dot / (np.sqrt(a_u ** 2 + a_v ** 2) * np.sqrt(b_u ** 2 + b_v ** 2) + 1e-6)
    return {
        "anchor_rmse": float(np.sqrt(np.mean(err2))) if err2.size else 0.0,
        "anchor_rmse_scaled": float(np.sqrt(np.mean(err2_scaled))) if err2_scaled.size else 0.0,
        "anchor_speed_bias": float(np.mean(bg_speed - anchor_speed)) if err2.size else 0.0,
        "anchor_count": float(np.count_nonzero(mask)),
        "anchor_cosine_mean": float(np.mean(cosine)) if cosine.size else 0.0,
        "speed_scale": speed_scale,
    }


def _resolve_background_candidates(
    background_dir: Path | None,
    background_dirs: list[Path],
    time_str: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if background_dir is not None:
        background = load_background(background_dir, time_str)
        if background is not None:
            candidates.append(background)
        return candidates
    return load_background_candidates(background_dirs, time_str)


def _find_previous_stage5_background(
    summary: list[dict[str, Any]],
    current_row: dict[str, Any],
    internal_stage5_dir: Path | None,
) -> dict[str, Any] | None:
    if internal_stage5_dir is None:
        return None
    current_index = _int(current_row, "source_index", -1)
    previous_rows = [
        row
        for row in summary
        if _int(row, "source_index", -1) >= 0 and _int(row, "source_index", -1) < current_index
    ]
    if not previous_rows:
        return None
    previous = max(previous_rows, key=lambda row: _int(row, "source_index", -1))
    prev_time = _frame_id(previous)
    npz_path = internal_stage5_dir / f"frame_{prev_time}_stage5.npz"
    if not npz_path.exists():
        return None
    try:
        return _load_stage5_as_background(npz_path)
    except Exception:
        return None


def _bbox_from_points(
    points: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    shape: tuple[int, int, int],
    *,
    pad_z: int,
    pad_xy: int,
) -> tuple[int, int, int, int, int, int] | None:
    valid = [(z, y, x) for z, y, x in points if z.size > 0]
    if not valid:
        return None
    z = np.concatenate([item[0] for item in valid])
    y = np.concatenate([item[1] for item in valid])
    x = np.concatenate([item[2] for item in valid])
    z_dim, h_dim, w_dim = shape
    z0 = max(0, int(np.min(z)) - int(pad_z))
    z1 = min(z_dim, int(np.max(z)) + int(pad_z) + 1)
    y0 = max(0, int(np.min(y)) - int(pad_xy))
    y1 = min(h_dim, int(np.max(y)) + int(pad_xy) + 1)
    x0 = max(0, int(np.min(x)) - int(pad_xy))
    x1 = min(w_dim, int(np.max(x)) + int(pad_xy) + 1)
    return z0, z1, y0, y1, x0, x1


def _local_flat(z: np.ndarray, y: np.ndarray, x: np.ndarray, bbox: tuple[int, int, int, int, int, int], local_shape: tuple[int, int, int]) -> np.ndarray:
    z0, _, y0, _, x0, _ = bbox
    _, ly, lx = local_shape
    return ((np.asarray(z, dtype=np.int64) - z0) * ly * lx + (np.asarray(y, dtype=np.int64) - y0) * lx + (np.asarray(x, dtype=np.int64) - x0)).astype(np.int64)


def _neighbor_sum_and_count(field: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    field = np.asarray(field, dtype=np.float32)
    mask_f = np.asarray(mask, dtype=np.float32)
    padded_f = np.pad(field * mask_f, ((1, 1), (1, 1), (1, 1)), mode="constant")
    padded_m = np.pad(mask_f, ((1, 1), (1, 1), (1, 1)), mode="constant")
    slices = (
        (slice(0, -2), slice(1, -1), slice(1, -1)),
        (slice(2, None), slice(1, -1), slice(1, -1)),
        (slice(1, -1), slice(0, -2), slice(1, -1)),
        (slice(1, -1), slice(2, None), slice(1, -1)),
        (slice(1, -1), slice(1, -1), slice(0, -2)),
        (slice(1, -1), slice(1, -1), slice(2, None)),
    )
    total = np.zeros_like(field, dtype=np.float32)
    count = np.zeros_like(field, dtype=np.float32)
    for sl in slices:
        total += padded_f[sl]
        count += padded_m[sl]
    return total, count


def _neighbor_mean(field: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    total, count = _neighbor_sum_and_count(field, mask)
    mean = np.divide(total, np.maximum(count, 1.0), out=np.zeros_like(total), where=count > 0)
    return mean.astype(np.float32, copy=False), count


def _expand_boolean_mask(mask: np.ndarray, radius_xy: int, radius_z: int) -> np.ndarray:
    base = np.asarray(mask, dtype=bool)
    if not np.any(base):
        return np.zeros_like(base, dtype=bool)
    z_dim, y_dim, x_dim = base.shape
    out = np.zeros_like(base, dtype=bool)
    zz, yy, xx = np.where(base)
    for z, y, x in zip(zz, yy, xx):
        z0 = max(0, int(z) - int(radius_z))
        z1 = min(z_dim, int(z) + int(radius_z) + 1)
        y0 = max(0, int(y) - int(radius_xy))
        y1 = min(y_dim, int(y) + int(radius_xy) + 1)
        x0 = max(0, int(x) - int(radius_xy))
        x1 = min(x_dim, int(x) + int(radius_xy) + 1)
        out[z0:z1, y0:y1, x0:x1] = True
    return out


def _divergence_proxy(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    du_dx = np.gradient(np.asarray(u, dtype=np.float32), axis=2)
    dv_dy = np.gradient(np.asarray(v, dtype=np.float32), axis=1)
    return (du_dx + dv_dy).astype(np.float32, copy=False)


def _smoothness_proxy(u: np.ndarray, v: np.ndarray, mask: np.ndarray) -> np.ndarray:
    u_mean, count = _neighbor_mean(u, mask)
    v_mean, _ = _neighbor_mean(v, mask)
    lap_u = np.where(count > 0, u_mean - u, 0.0)
    lap_v = np.where(count > 0, v_mean - v, 0.0)
    return np.sqrt(lap_u ** 2 + lap_v ** 2).astype(np.float32, copy=False)


def _metric_stats(arr: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    vals = np.asarray(arr, dtype=np.float32)[np.asarray(mask, dtype=bool)]
    if vals.size == 0:
        return 0.0, 0.0
    vals = np.abs(vals)
    return float(np.mean(vals)), float(np.quantile(vals, 0.90))


def _masked_vector_rmse(u: np.ndarray, v: np.ndarray, ref_u: np.ndarray, ref_v: np.ndarray, mask: np.ndarray) -> float:
    valid = np.asarray(mask, dtype=bool) & np.isfinite(ref_u) & np.isfinite(ref_v)
    if not np.any(valid):
        return 0.0
    err2 = (np.asarray(u, dtype=np.float32)[valid] - np.asarray(ref_u, dtype=np.float32)[valid]) ** 2
    err2 += (np.asarray(v, dtype=np.float32)[valid] - np.asarray(ref_v, dtype=np.float32)[valid]) ** 2
    return float(np.sqrt(np.mean(err2)))


def _holdout_rmse(problem: dict[str, Any], u: np.ndarray, v: np.ndarray, include_sources: set[str]) -> tuple[float, int]:
    holdouts = problem.get("holdout_sources", {})
    bbox = problem["bbox"]
    local_shape = problem["local_shape"]
    shape = problem["shape"]
    z0, z1, y0, y1, x0, x1 = bbox
    errs: list[np.ndarray] = []
    for name, source in holdouts.items():
        if name not in include_sources or source["idx"].size == 0:
            continue
        sz, sy, sx = _linear_to_zyx(source["idx"], shape)
        keep = (sz >= z0) & (sz < z1) & (sy >= y0) & (sy < y1) & (sx >= x0) & (sx < x1)
        if not np.any(keep):
            continue
        flat = _local_flat(sz[keep], sy[keep], sx[keep], bbox, local_shape)
        pred_u = u.reshape(-1)[flat]
        pred_v = v.reshape(-1)[flat]
        err = np.sqrt((pred_u - source["u"][keep]) ** 2 + (pred_v - source["v"][keep]) ** 2)
        errs.append(err.astype(np.float32, copy=False))
    if not errs:
        return 0.0, 0
    all_err = np.concatenate(errs)
    return float(np.sqrt(np.mean(all_err ** 2))), int(all_err.size)


def _build_local_problem(
    sparse: dict[str, Any],
    *,
    pad_z: int,
    pad_xy: int,
    include_sources: set[str],
    max_local_voxels: int,
    holdout_every: int,
    background: dict[str, Any] | None,
) -> dict[str, Any]:
    shape = sparse["shape"]
    recon = sparse["recon"]
    rz, ry, rx = _linear_to_zyx(recon["idx"], shape) if recon["idx"].size else (
        np.asarray([], dtype=np.int32),
        np.asarray([], dtype=np.int32),
        np.asarray([], dtype=np.int32),
    )

    point_sets: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = [(rz, ry, rx)]
    source_zyx: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    train_sources: dict[str, dict[str, np.ndarray]] = {}
    holdout_sources: dict[str, dict[str, np.ndarray]] = {}
    for name, source in sparse["direct_sources"].items():
        source_train, source_holdout = _split_anchor_holdout(source, holdout_every)
        train_sources[name] = source_train
        holdout_sources[name] = source_holdout
        if name not in include_sources or source_train["idx"].size == 0:
            source_zyx[name] = (
                np.asarray([], dtype=np.int32),
                np.asarray([], dtype=np.int32),
                np.asarray([], dtype=np.int32),
            )
            continue
        sz, sy, sx = _linear_to_zyx(source_train["idx"], shape)
        source_zyx[name] = (sz, sy, sx)
        point_sets.append((sz, sy, sx))

    bbox = _bbox_from_points(point_sets, shape, pad_z=pad_z, pad_xy=pad_xy)
    if bbox is None:
        raise ValueError("No sparse reconstruction or direct source points available for local Stage5 problem.")
    z0, z1, y0, y1, x0, x1 = bbox
    local_shape = (z1 - z0, y1 - y0, x1 - x0)
    local_voxels = int(np.prod(local_shape))
    if local_voxels > int(max_local_voxels):
        raise ValueError(f"Local ROI is too large: {local_shape} = {local_voxels} voxels > {max_local_voxels}")

    u = np.zeros(local_shape, dtype=np.float32)
    v = np.zeros(local_shape, dtype=np.float32)
    conf = np.zeros(local_shape, dtype=np.float32)
    mask = np.zeros(local_shape, dtype=bool)

    if recon["idx"].size:
        flat = _local_flat(rz, ry, rx, bbox, local_shape)
        u.reshape(-1)[flat] = recon["u"]
        v.reshape(-1)[flat] = recon["v"]
        conf.reshape(-1)[flat] = recon["conf"]
        mask.reshape(-1)[flat] = True
    original_mask = mask.copy()

    bg_local = _sample_background_to_local(background, bbox, local_shape, shape)

    anchor_u_sum = np.zeros(local_shape, dtype=np.float32)
    anchor_v_sum = np.zeros(local_shape, dtype=np.float32)
    anchor_w_sum = np.zeros(local_shape, dtype=np.float32)
    source_counts: dict[str, int] = {}
    source_weights = {"wind": 0.85, "amdar": 1.0, "turb": 0.9}
    for name, source in train_sources.items():
        source_counts[name] = int(sparse["direct_sources"][name]["idx"].size)
        if name not in include_sources or source["idx"].size == 0:
            continue
        sz, sy, sx = source_zyx[name]
        keep = (sz >= z0) & (sz < z1) & (sy >= y0) & (sy < y1) & (sx >= x0) & (sx < x1)
        if not np.any(keep):
            continue
        flat = _local_flat(sz[keep], sy[keep], sx[keep], bbox, local_shape)
        weight = np.clip(source["conf"][keep] * source_weights.get(name, 0.8), 0.05, 1.0).astype(np.float32, copy=False)
        np.add.at(anchor_u_sum.reshape(-1), flat, source["u"][keep] * weight)
        np.add.at(anchor_v_sum.reshape(-1), flat, source["v"][keep] * weight)
        np.add.at(anchor_w_sum.reshape(-1), flat, weight)

    anchor_mask = anchor_w_sum > 0
    anchor_u = np.divide(anchor_u_sum, np.maximum(anchor_w_sum, 1e-6), out=np.zeros_like(anchor_u_sum), where=anchor_mask)
    anchor_v = np.divide(anchor_v_sum, np.maximum(anchor_w_sum, 1e-6), out=np.zeros_like(anchor_v_sum), where=anchor_mask)
    mask[anchor_mask] = True
    u[anchor_mask] = np.where(conf[anchor_mask] > 0, 0.35 * u[anchor_mask] + 0.65 * anchor_u[anchor_mask], anchor_u[anchor_mask])
    v[anchor_mask] = np.where(conf[anchor_mask] > 0, 0.35 * v[anchor_mask] + 0.65 * anchor_v[anchor_mask], anchor_v[anchor_mask])
    conf[anchor_mask] = np.maximum(conf[anchor_mask], np.clip(anchor_w_sum[anchor_mask], 0.0, 1.0))

    return {
        "shape": shape,
        "bbox": bbox,
        "local_shape": local_shape,
        "u": u,
        "v": v,
        "conf": conf,
        "mask": mask,
        "original_mask": original_mask,
        "background": bg_local,
        "anchor_u": anchor_u.astype(np.float32, copy=False),
        "anchor_v": anchor_v.astype(np.float32, copy=False),
        "anchor_weight": np.clip(anchor_w_sum, 0.0, 1.0).astype(np.float32, copy=False),
        "anchor_mask": anchor_mask,
        "holdout_sources": holdout_sources,
        "source_counts": source_counts,
        "recon_count": int(recon["idx"].size),
        "local_voxels": local_voxels,
    }


def _choose_background_for_problem(
    problem: dict[str, Any],
    backgrounds: list[dict[str, Any]],
    *,
    consistency_scale: float,
    top_k: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not backgrounds:
        return None, []
    scored: list[dict[str, Any]] = []
    for background in backgrounds:
        sampled = _sample_background_to_local(background, problem["bbox"], problem["local_shape"], problem["shape"])
        if sampled is None:
            continue
        stats = _background_anchor_stats(sampled, problem["anchor_mask"], problem["anchor_u"], problem["anchor_v"])
        rmse = float(stats["anchor_rmse_scaled"])
        bias = abs(float(stats["anchor_speed_bias"]))
        cosine_bonus = max(0.0, float(stats["anchor_cosine_mean"]))
        score = rmse + 0.18 * bias - 2.0 * cosine_bonus
        consistency = float(np.clip((cosine_bonus + max(0.0, 1.0 - rmse / max(1e-6, consistency_scale))) / 2.0, 0.0, 1.0))
        scored.append(
            {
                "path": str(sampled.get("path", background.get("path", ""))),
                "sampled": sampled,
                "anchor_rmse": float(stats["anchor_rmse"]),
                "anchor_rmse_scaled": rmse,
                "anchor_speed_bias": float(stats["anchor_speed_bias"]),
                "anchor_count": float(stats["anchor_count"]),
                "anchor_cosine_mean": float(stats["anchor_cosine_mean"]),
                "speed_scale": float(stats["speed_scale"]),
                "consistency_score": consistency,
                "selection_score": score,
            }
        )
    if not scored:
        return None, []
    scored.sort(key=lambda item: (item["selection_score"], -item["consistency_score"], item["path"]))
    selected = scored[0]
    if top_k > 1 and len(scored) > 1:
        top = scored[: max(1, int(top_k))]
        weights = np.asarray([max(1e-4, item["consistency_score"]) for item in top], dtype=np.float32)
        weights = weights / np.sum(weights)
        fused = {
            "u": np.zeros_like(np.asarray(top[0]["sampled"]["u"], dtype=np.float32)),
            "v": np.zeros_like(np.asarray(top[0]["sampled"]["v"], dtype=np.float32)),
            "path": " | ".join(item["path"] for item in top),
        }
        for w, item in zip(weights, top):
            fused["u"] += float(w) * np.asarray(item["sampled"]["u"], dtype=np.float32)
            fused["v"] += float(w) * np.asarray(item["sampled"]["v"], dtype=np.float32)
        selected = {
            "path": fused["path"],
            "sampled": fused,
            "anchor_rmse": float(np.sum(weights * np.asarray([item["anchor_rmse"] for item in top], dtype=np.float32))),
            "anchor_rmse_scaled": float(np.sum(weights * np.asarray([item["anchor_rmse_scaled"] for item in top], dtype=np.float32))),
            "anchor_speed_bias": float(np.sum(weights * np.asarray([item["anchor_speed_bias"] for item in top], dtype=np.float32))),
            "anchor_count": float(top[0]["anchor_count"]),
            "anchor_cosine_mean": float(np.sum(weights * np.asarray([item["anchor_cosine_mean"] for item in top], dtype=np.float32))),
            "speed_scale": float(np.sum(weights * np.asarray([item["speed_scale"] for item in top], dtype=np.float32))),
            "consistency_score": float(np.sum(weights * np.asarray([item["consistency_score"] for item in top], dtype=np.float32))),
            "selection_score": float(np.sum(weights * np.asarray([item["selection_score"] for item in top], dtype=np.float32))),
        }
    return selected, scored


def _expand_local_support(
    u: np.ndarray,
    v: np.ndarray,
    conf: np.ndarray,
    mask: np.ndarray,
    *,
    iters: int,
    min_neighbors: int,
    max_expand_voxels: int,
    expand_conf_scale: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    expanded_total = 0
    for _ in range(max(0, int(iters))):
        u_mean, count = _neighbor_mean(u, mask)
        v_mean, _ = _neighbor_mean(v, mask)
        conf_mean, _ = _neighbor_mean(conf, mask)
        candidates = (~mask) & (count >= int(min_neighbors)) & (conf_mean > 0)
        candidate_idx = np.flatnonzero(candidates.reshape(-1))
        if candidate_idx.size == 0:
            break
        remaining = max(0, int(max_expand_voxels) - expanded_total)
        if remaining <= 0:
            break
        if candidate_idx.size > remaining:
            scores = conf_mean.reshape(-1)[candidate_idx]
            candidate_idx = candidate_idx[np.argsort(scores)[::-1][:remaining]]
        flat_u = u.reshape(-1)
        flat_v = v.reshape(-1)
        flat_conf = conf.reshape(-1)
        flat_mask = mask.reshape(-1)
        flat_u[candidate_idx] = u_mean.reshape(-1)[candidate_idx]
        flat_v[candidate_idx] = v_mean.reshape(-1)[candidate_idx]
        flat_conf[candidate_idx] = np.clip(conf_mean.reshape(-1)[candidate_idx] * float(expand_conf_scale), 0.0, 1.0)
        flat_mask[candidate_idx] = True
        expanded_total += int(candidate_idx.size)
    return u, v, conf, mask, expanded_total


def _refine_local(problem: dict[str, Any], args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, float]]:
    u = np.asarray(problem["u"], dtype=np.float32).copy()
    v = np.asarray(problem["v"], dtype=np.float32).copy()
    conf = np.asarray(problem["conf"], dtype=np.float32).copy()
    mask = np.asarray(problem["mask"], dtype=bool).copy()
    original_mask = np.asarray(problem["original_mask"], dtype=bool)
    anchor_u = np.asarray(problem["anchor_u"], dtype=np.float32)
    anchor_v = np.asarray(problem["anchor_v"], dtype=np.float32)
    anchor_weight = np.asarray(problem["anchor_weight"], dtype=np.float32)
    anchor_mask = np.asarray(problem["anchor_mask"], dtype=bool)
    background = problem.get("background")
    background_consistency = np.ones_like(conf, dtype=np.float32)
    background_speed_scale = float(problem.get("background_speed_scale", 1.0))
    background_selected_path = str(problem.get("background_selected_path", ""))
    is_internal_background = background_selected_path.startswith("internal_stage5:")
    anchor_neighborhood_mask = _expand_boolean_mask(
        anchor_mask,
        int(args.anchor_neighborhood_radius_xy),
        int(args.anchor_neighborhood_radius_z),
    )
    expanded_background_relax_voxels = 0
    direction_consistency_after = np.ones_like(conf, dtype=np.float32)

    div0 = _divergence_proxy(u, v)
    smooth0 = _smoothness_proxy(u, v, mask)
    div0_mean, div0_p90 = _metric_stats(div0, mask)
    smooth0_mean, smooth0_p90 = _metric_stats(smooth0, mask)
    initial_mask_count = int(np.count_nonzero(mask))

    u, v, conf, mask, expanded_voxels = _expand_local_support(
        u,
        v,
        conf,
        mask,
        iters=args.local_expand_iters,
        min_neighbors=args.expand_min_neighbors,
        max_expand_voxels=args.max_expand_voxels,
        expand_conf_scale=args.expand_conf_scale,
    )
    expanded_mask = mask & ~original_mask
    if background is not None and float(args.background_init_weight) > 0 and np.any(expanded_mask):
        bg_u = np.asarray(background["u"], dtype=np.float32) * background_speed_scale
        bg_v = np.asarray(background["v"], dtype=np.float32) * background_speed_scale
        if np.any(anchor_mask):
            anchor_cons = np.zeros_like(conf, dtype=np.float32)
            anchor_delta = np.sqrt((bg_u[anchor_mask] - anchor_u[anchor_mask]) ** 2 + (bg_v[anchor_mask] - anchor_v[anchor_mask]) ** 2)
            anchor_cons[anchor_mask] = np.clip(
                1.0 - anchor_delta / max(1e-6, float(args.background_consistency_scale)),
                0.0,
                1.0,
            ).astype(np.float32, copy=False)
            cons_mean, count = _neighbor_mean(anchor_cons, anchor_mask)
            background_consistency = np.where(anchor_mask, anchor_cons, cons_mean).astype(np.float32, copy=False)
            background_consistency = np.clip(background_consistency, 0.20, 1.0)
        init_w = np.clip(float(args.background_init_weight) * float(args.background_data_weight), 0.0, 1.0) * (1.0 - np.clip(conf, 0.0, 1.0))
        init_w = np.clip(init_w, 0.0, 0.90)
        init_w = init_w * background_consistency
        if is_internal_background:
            zone = np.zeros_like(init_w, dtype=np.float32)
            zone[expanded_mask] = float(args.internal_background_expanded_weight)
            zone[anchor_neighborhood_mask & expanded_mask] = float(args.internal_background_near_anchor_weight)
            zone[(original_mask & ~anchor_mask)] = float(args.internal_background_original_weight)
            zone[anchor_mask] = 0.0
            init_w = init_w * zone
        u[expanded_mask] = (1.0 - init_w[expanded_mask]) * u[expanded_mask] + init_w[expanded_mask] * bg_u[expanded_mask]
        v[expanded_mask] = (1.0 - init_w[expanded_mask]) * v[expanded_mask] + init_w[expanded_mask] * bg_v[expanded_mask]
        conf[expanded_mask] = np.minimum(conf[expanded_mask], float(args.expanded_conf_cap))

    for _ in range(max(0, int(args.iterations))):
        u_mean, count = _neighbor_mean(u, mask)
        v_mean, _ = _neighbor_mean(v, mask)
        valid = mask & (count > 0)
        blend = float(args.diffusion_strength) * (0.35 + 0.65 * np.clip(conf, 0.0, 1.0))
        blend = np.clip(blend * (1.0 - 0.65 * anchor_weight), 0.0, 0.85)
        u[valid] = (1.0 - blend[valid]) * u[valid] + blend[valid] * u_mean[valid]
        v[valid] = (1.0 - blend[valid]) * v[valid] + blend[valid] * v_mean[valid]

        if background is not None and float(args.background_relax_weight) > 0:
            bg_u = np.asarray(background["u"], dtype=np.float32) * background_speed_scale
            bg_v = np.asarray(background["v"], dtype=np.float32) * background_speed_scale
            bg_weight = np.clip(float(args.background_relax_weight) * float(args.background_data_weight) * (1.0 - np.clip(conf, 0.0, 1.0)), 0.0, 0.60)
            bg_weight = bg_weight * background_consistency
            bg_valid = mask & ~anchor_mask & expanded_mask
            if bool(args.background_relax_on_original_nonanchor):
                bg_valid = bg_valid | (mask & original_mask & ~anchor_mask)
            if bool(args.hazard_conservative) and _truthy(problem.get("hazard_frame", False)):
                bg_valid = bg_valid & (background_consistency >= float(args.background_consistency_threshold))
            if is_internal_background:
                zone = np.zeros_like(bg_weight, dtype=np.float32)
                zone[expanded_mask] = float(args.internal_background_expanded_weight)
                zone[anchor_neighborhood_mask & expanded_mask] = float(args.internal_background_near_anchor_weight)
                zone[(original_mask & ~anchor_mask)] = float(args.internal_background_original_weight)
                zone[anchor_mask] = 0.0
                bg_weight = bg_weight * zone
            expanded_background_relax_voxels = int(np.count_nonzero(bg_valid))
            u[bg_valid] = (1.0 - bg_weight[bg_valid]) * u[bg_valid] + bg_weight[bg_valid] * bg_u[bg_valid]
            v[bg_valid] = (1.0 - bg_weight[bg_valid]) * v[bg_valid] + bg_weight[bg_valid] * bg_v[bg_valid]

        if background is not None and float(args.direction_consistency_weight) > 0 and np.any(expanded_mask):
            bg_u = np.asarray(background["u"], dtype=np.float32) * background_speed_scale
            bg_v = np.asarray(background["v"], dtype=np.float32) * background_speed_scale
            ref_u = bg_u.copy()
            ref_v = bg_v.copy()
            if str(args.direction_consistency_reference) == "background_or_anchor_neighborhood":
                a_u_mean, a_count = _neighbor_mean(anchor_u, anchor_mask)
                a_v_mean, _ = _neighbor_mean(anchor_v, anchor_mask)
                weak_bg = np.sqrt(bg_u ** 2 + bg_v ** 2) < 1e-3
                use_anchor_ref = weak_bg | (~anchor_neighborhood_mask)
                ref_u[use_anchor_ref] = a_u_mean[use_anchor_ref]
                ref_v[use_anchor_ref] = a_v_mean[use_anchor_ref]
            cur_speed = np.sqrt(u ** 2 + v ** 2)
            ref_speed = np.sqrt(ref_u ** 2 + ref_v ** 2)
            ref_dir_u = np.divide(ref_u, np.maximum(ref_speed, 1e-6), out=np.zeros_like(ref_u), where=ref_speed > 0)
            ref_dir_v = np.divide(ref_v, np.maximum(ref_speed, 1e-6), out=np.zeros_like(ref_v), where=ref_speed > 0)
            cur_dir_u = np.divide(u, np.maximum(cur_speed, 1e-6), out=np.zeros_like(u), where=cur_speed > 0)
            cur_dir_v = np.divide(v, np.maximum(cur_speed, 1e-6), out=np.zeros_like(v), where=cur_speed > 0)
            cosine = cur_dir_u * ref_dir_u + cur_dir_v * ref_dir_v
            direction_consistency_after = np.clip(cosine, -1.0, 1.0).astype(np.float32, copy=False)
            dir_w = float(args.direction_consistency_weight)
            if bool(args.hazard_conservative) and _truthy(problem.get("hazard_frame", False)):
                dir_w = min(dir_w, float(args.direction_consistency_hazard_weight))
            dir_mask = expanded_mask & mask
            if bool(args.hazard_conservative) and _truthy(problem.get("hazard_frame", False)):
                dir_mask = dir_mask & anchor_neighborhood_mask
            mix = np.clip(dir_w * np.clip(conf, 0.0, 1.0) * np.clip(background_consistency, 0.0, 1.0), 0.0, 0.45)
            new_dir_u = (1.0 - mix) * cur_dir_u + mix * ref_dir_u
            new_dir_v = (1.0 - mix) * cur_dir_v + mix * ref_dir_v
            new_norm = np.sqrt(new_dir_u ** 2 + new_dir_v ** 2)
            new_dir_u = np.divide(new_dir_u, np.maximum(new_norm, 1e-6), out=np.zeros_like(new_dir_u), where=new_norm > 0)
            new_dir_v = np.divide(new_dir_v, np.maximum(new_norm, 1e-6), out=np.zeros_like(new_dir_v), where=new_norm > 0)
            u[dir_mask] = new_dir_u[dir_mask] * cur_speed[dir_mask]
            v[dir_mask] = new_dir_v[dir_mask] * cur_speed[dir_mask]

        if float(args.pinn_strength) > 0:
            div = _divergence_proxy(u, v)
            grad_x = np.gradient(div, axis=2).astype(np.float32, copy=False)
            grad_y = np.gradient(div, axis=1).astype(np.float32, copy=False)
            strength = float(args.pinn_strength) * np.clip(conf, 0.0, 1.0)
            u[mask] = u[mask] - strength[mask] * grad_x[mask]
            v[mask] = v[mask] - strength[mask] * grad_y[mask]

        if np.any(anchor_mask):
            keep = np.clip(float(args.anchor_preserve) * np.maximum(anchor_weight, 0.20), 0.0, 1.0)
            u[anchor_mask] = (1.0 - keep[anchor_mask]) * u[anchor_mask] + keep[anchor_mask] * anchor_u[anchor_mask]
            v[anchor_mask] = (1.0 - keep[anchor_mask]) * v[anchor_mask] + keep[anchor_mask] * anchor_v[anchor_mask]
            conf[anchor_mask] = np.maximum(conf[anchor_mask], np.clip(anchor_weight[anchor_mask], 0.0, 1.0))

        if float(args.original_delta_cap) > 0 and np.any(original_mask):
            du = u - problem["u"]
            dv = v - problem["v"]
            delta = np.sqrt(du ** 2 + dv ** 2)
            cap_mask = original_mask & (delta > float(args.original_delta_cap))
            scale = float(args.original_delta_cap) / np.maximum(delta, 1e-6)
            u[cap_mask] = problem["u"][cap_mask] + du[cap_mask] * scale[cap_mask]
            v[cap_mask] = problem["v"][cap_mask] + dv[cap_mask] * scale[cap_mask]

    div1 = _divergence_proxy(u, v)
    smooth1 = _smoothness_proxy(u, v, mask)
    div1_mean, div1_p90 = _metric_stats(div1, mask)
    smooth1_mean, smooth1_p90 = _metric_stats(smooth1, mask)

    anchor_rmse = 0.0
    if np.any(anchor_mask):
        err = np.sqrt((u[anchor_mask] - anchor_u[anchor_mask]) ** 2 + (v[anchor_mask] - anchor_v[anchor_mask]) ** 2)
        anchor_rmse = float(np.sqrt(np.mean(err ** 2))) if err.size else 0.0

    delta = np.sqrt((u - problem["u"]) ** 2 + (v - problem["v"]) ** 2)
    delta_vals = delta[mask]
    delta_original = delta[mask & original_mask]
    delta_expanded = delta[mask & ~original_mask]
    background_rmse = 0.0
    background_speed_bias = 0.0
    if background is not None:
        bg_u = np.asarray(background["u"], dtype=np.float32) * background_speed_scale
        bg_v = np.asarray(background["v"], dtype=np.float32) * background_speed_scale
        background_rmse = _masked_vector_rmse(u, v, bg_u, bg_v, mask)
        speed = np.sqrt(u ** 2 + v ** 2)
        bg_speed = np.sqrt(bg_u ** 2 + bg_v ** 2)
        background_speed_bias = float(np.mean((speed - bg_speed)[mask])) if np.any(mask) else 0.0
    holdout_rmse, holdout_count = _holdout_rmse(problem, u, v, {token.strip().lower() for token in str(args.include_sources).split(",") if token.strip()})
    speed_ref = float(np.mean(np.sqrt(u[mask] ** 2 + v[mask] ** 2))) if np.any(mask) else 0.0
    norm_div = div1_mean / max(speed_ref, 1e-6)
    norm_smooth = smooth1_mean / max(speed_ref, 1e-6)
    metrics = {
        "initial_voxels": float(initial_mask_count),
        "refined_voxels": float(np.count_nonzero(mask)),
        "expanded_voxels": float(expanded_voxels),
        "anchor_voxels": float(np.count_nonzero(anchor_mask)),
        "divergence_abs_mean_before": div0_mean,
        "divergence_abs_p90_before": div0_p90,
        "smoothness_mean_before": smooth0_mean,
        "smoothness_p90_before": smooth0_p90,
        "divergence_abs_mean_after": div1_mean,
        "divergence_abs_p90_after": div1_p90,
        "smoothness_mean_after": smooth1_mean,
        "smoothness_p90_after": smooth1_p90,
        "anchor_rmse_after": anchor_rmse,
        "heldout_anchor_rmse_after": holdout_rmse,
        "heldout_anchor_count": float(holdout_count),
        "delta_speed_mean": float(np.mean(delta_vals)) if delta_vals.size else 0.0,
        "delta_speed_p90": float(np.quantile(delta_vals, 0.90)) if delta_vals.size else 0.0,
        "delta_speed_original_mean": float(np.mean(delta_original)) if delta_original.size else 0.0,
        "delta_speed_original_p90": float(np.quantile(delta_original, 0.90)) if delta_original.size else 0.0,
        "delta_speed_expanded_mean": float(np.mean(delta_expanded)) if delta_expanded.size else 0.0,
        "delta_speed_expanded_p90": float(np.quantile(delta_expanded, 0.90)) if delta_expanded.size else 0.0,
        "background_vector_rmse": background_rmse,
        "background_speed_bias": background_speed_bias,
        "normalized_divergence_abs_mean_after": norm_div,
        "normalized_smoothness_mean_after": norm_smooth,
        "conf_mean_after": float(np.mean(conf[mask])) if np.any(mask) else 0.0,
        "conf_expanded_mean_after": float(np.mean(conf[mask & ~original_mask])) if np.any(mask & ~original_mask) else 0.0,
        "background_available": float(background is not None),
    }
    if "background_selected_path" in problem:
        metrics["background_anchor_rmse"] = float(problem.get("background_anchor_rmse", 0.0))
        metrics["background_anchor_rmse_scaled"] = float(problem.get("background_anchor_rmse_scaled", 0.0))
        metrics["background_anchor_speed_bias"] = float(problem.get("background_anchor_speed_bias", 0.0))
        metrics["background_anchor_cosine_mean"] = float(problem.get("background_anchor_cosine_mean", 0.0))
        metrics["background_consistency_score"] = float(problem.get("background_consistency_score", 0.0))
        metrics["background_speed_scale"] = float(problem.get("background_speed_scale", 1.0))
    metrics["direction_consistency_mean_after"] = float(np.mean(direction_consistency_after[mask])) if np.any(mask) else 0.0
    metrics["direction_consistency_p10_after"] = float(np.quantile(direction_consistency_after[mask], 0.10)) if np.any(mask) else 0.0
    metrics["expanded_background_relax_voxels"] = float(expanded_background_relax_voxels)
    metrics["internal_background_zone_counts"] = {
        "expanded": int(np.count_nonzero(expanded_mask)),
        "expanded_near_anchor": int(np.count_nonzero(expanded_mask & anchor_neighborhood_mask)),
        "original_nonanchor": int(np.count_nonzero(original_mask & ~anchor_mask)),
    }
    refined = {
        "u": u.astype(np.float32, copy=False),
        "v": v.astype(np.float32, copy=False),
        "conf": np.clip(conf, 0.0, 1.0).astype(np.float32, copy=False),
        "mask": mask,
        "divergence": div1.astype(np.float32, copy=False),
        "smoothness": smooth1.astype(np.float32, copy=False),
    }
    return refined, metrics


def _save_stage5_npz(
    out_path: Path,
    row: dict[str, Any],
    problem: dict[str, Any],
    refined: dict[str, Any],
    metrics: dict[str, float],
    args: argparse.Namespace,
) -> dict[str, Any]:
    mask = np.asarray(refined["mask"], dtype=bool)
    local_idx = np.flatnonzero(mask.reshape(-1))
    z0, z1, y0, y1, x0, x1 = problem["bbox"]
    lz, ly, lx = problem["local_shape"]
    local_z = local_idx // (ly * lx)
    rem = local_idx % (ly * lx)
    local_y = rem // lx
    local_x = rem % lx
    global_z = local_z + z0
    global_y = local_y + y0
    global_x = local_x + x0
    refined_idx = _zyx_to_linear(global_z, global_y, global_x, problem["shape"])

    div_vals = np.asarray(refined["divergence"], dtype=np.float32).reshape(-1)[local_idx]
    smooth_vals = np.asarray(refined["smoothness"], dtype=np.float32).reshape(-1)[local_idx]
    anchor_local = np.where(np.asarray(problem["anchor_mask"], dtype=bool))
    if anchor_local[0].size:
        anchor_idx = _zyx_to_linear(
            anchor_local[0] + z0,
            anchor_local[1] + y0,
            anchor_local[2] + x0,
            problem["shape"],
        )
    else:
        anchor_idx = np.asarray([], dtype=np.uint32)

    payload = {
        "storage_mode": np.array("stage5_roi_sparse_v1"),
        "method": np.array("pinn_proxy_diffusion_style_v1"),
        "source_stage4_frame": np.array(str(row.get("filename", ""))),
        "source_index": np.array(_int(row, "source_index"), dtype=np.int32),
        "time_str": np.array(_frame_id(row)),
        "grid_shape": np.asarray(problem["shape"], dtype=np.int32),
        "bbox_zyx": np.asarray(problem["bbox"], dtype=np.int32),
        "local_shape": np.asarray(problem["local_shape"], dtype=np.int32),
        "refined_idx": refined_idx,
        "refined_u_val": np.asarray(refined["u"], dtype=np.float32).reshape(-1)[local_idx],
        "refined_v_val": np.asarray(refined["v"], dtype=np.float32).reshape(-1)[local_idx],
        "refined_conf_val": np.asarray(refined["conf"], dtype=np.float32).reshape(-1)[local_idx],
        "refined_divergence_val": div_vals.astype(np.float32, copy=False),
        "refined_smoothness_val": smooth_vals.astype(np.float32, copy=False),
        "anchor_idx": anchor_idx,
        "original_mask_val": np.asarray(problem["original_mask"], dtype=np.float32).reshape(-1)[local_idx],
        "expanded_mask_val": (~np.asarray(problem["original_mask"], dtype=bool)).astype(np.float32).reshape(-1)[local_idx],
        "iterations": np.array(int(args.iterations), dtype=np.int32),
        "diffusion_strength": np.array(float(args.diffusion_strength), dtype=np.float32),
        "pinn_strength": np.array(float(args.pinn_strength), dtype=np.float32),
        "anchor_preserve": np.array(float(args.anchor_preserve), dtype=np.float32),
        "metrics_json": np.array(json.dumps(metrics, ensure_ascii=False)),
    }
    if problem.get("background") is not None:
        bg = problem["background"]
        payload["background_source"] = np.array(str(bg.get("path", "")))
        payload["background_u_val"] = np.asarray(bg["u"], dtype=np.float32).reshape(-1)[local_idx]
        payload["background_v_val"] = np.asarray(bg["v"], dtype=np.float32).reshape(-1)[local_idx]
        for key in ("w", "vertical_velocity", "temperature", "geopotential"):
            if key in bg:
                payload[f"background_{key}_val"] = np.asarray(bg[key], dtype=np.float32).reshape(-1)[local_idx]
    np.savez_compressed(out_path, **payload)
    return {
        "output_npz": str(out_path),
        "refined_voxels": int(local_idx.size),
        "bbox_zyx": [int(v) for v in problem["bbox"]],
        "local_shape": [int(v) for v in problem["local_shape"]],
    }


def _render_stage5_3d_png(
    out_path: Path,
    row: dict[str, Any],
    problem: dict[str, Any],
    refined: dict[str, Any],
    *,
    max_vectors: int,
) -> None:
    mask = np.asarray(refined["mask"], dtype=bool)
    if not np.any(mask):
        return
    local_idx = np.flatnonzero(mask.reshape(-1))
    conf_flat = np.asarray(refined["conf"], dtype=np.float32).reshape(-1)
    if local_idx.size > max_vectors:
        local_idx = local_idx[np.argsort(conf_flat[local_idx])[::-1][:max_vectors]]
        local_idx = np.sort(local_idx)

    z0, _, y0, _, x0, _ = problem["bbox"]
    _, h_dim, w_dim = problem["shape"]
    _, ly, lx = problem["local_shape"]
    local_z = local_idx // (ly * lx)
    rem = local_idx % (ly * lx)
    local_y = rem // lx
    local_x = rem % lx
    global_z = local_z + z0
    global_y = local_y + y0
    global_x = local_x + x0
    lon, lat = _xy_to_lonlat(global_x, global_y, h_dim, w_dim)
    alt_km = global_z.astype(np.float32) * (ALT_STEP_M / 1000.0)

    u = np.asarray(refined["u"], dtype=np.float32).reshape(-1)[local_idx]
    v = np.asarray(refined["v"], dtype=np.float32).reshape(-1)[local_idx]
    conf = conf_flat[local_idx]
    speed = np.sqrt(u ** 2 + v ** 2)
    speed_ref = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    lon_span = max(0.5, float(np.max(lon) - np.min(lon)) if lon.size else 0.5)
    lat_span = max(0.5, float(np.max(lat) - np.min(lat)) if lat.size else 0.5)
    scale = max(lon_span, lat_span) * 0.055 * np.clip(speed / max(speed_ref, 1e-6), 0.25, 1.8)
    denom = np.maximum(speed, 1e-6)
    dx = u / denom * scale
    dy = v / denom * scale

    fig = plt.figure(figsize=(13, 10), constrained_layout=True)
    ax = fig.add_subplot(111, projection="3d")
    scatter = ax.scatter(lon, lat, alt_km, c=conf, s=18 + 34 * np.clip(conf, 0.0, 1.0), cmap="plasma", alpha=0.86)
    ax.quiver(lon, lat, alt_km, dx, dy, np.zeros_like(dx), length=1.0, normalize=False, color="black", linewidth=0.60, alpha=0.68)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.set_zlabel("Altitude (km)")
    ax.set_title(
        f"Stage5 ROI PINN-proxy + diffusion-style refinement - {_frame_id(row)}\n"
        "Sparse ROI field only; arrows scaled for readability",
        fontsize=12,
    )
    ax.grid(True, alpha=0.25)
    ax.view_init(elev=26, azim=-58)
    fig.colorbar(scatter, ax=ax, fraction=0.035, pad=0.02, label="refined confidence")
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _record_summary(
    row: dict[str, Any],
    status: str,
    reason: str,
    problem: dict[str, Any] | None = None,
    metrics: dict[str, float] | None = None,
    save_info: dict[str, Any] | None = None,
    png_path: Path | None = None,
) -> dict[str, Any]:
    out = {
        "filename": row.get("filename"),
        "source_index": row.get("source_index"),
        "time_str": row.get("time_str"),
        "timestamp_utc": row.get("timestamp_utc"),
        "selection_reasons": list(row.get("selection_reasons", [])),
        "status": status,
        "reason": reason,
        "stage4_recon_triggered": row.get("recon_triggered"),
        "stage4_recon_filled_voxels": row.get("recon_filled_voxels"),
        "stage4_recon_coverage_ratio": row.get("recon_coverage_ratio"),
        "stage4_recon_conf_mean": row.get("recon_conf_mean"),
    }
    if problem is not None:
        out["source_counts"] = problem.get("source_counts", {})
        out["stage5_local_voxels"] = int(problem.get("local_voxels", 0))
        out["stage5_anchor_voxels"] = int(np.count_nonzero(problem.get("anchor_mask", [])))
        out["background_selected_path"] = str(problem.get("background_selected_path", ""))
        out["background_anchor_rmse"] = float(problem.get("background_anchor_rmse", 0.0))
        out["background_anchor_speed_bias"] = float(problem.get("background_anchor_speed_bias", 0.0))
        out["background_consistency_score"] = float(problem.get("background_consistency_score", 0.0))
        if "background_candidates" in problem:
            out["background_candidates"] = [
                {
                    "path": str(item.get("path", "")),
                    "anchor_rmse": float(item.get("anchor_rmse", 0.0)),
                    "anchor_rmse_scaled": float(item.get("anchor_rmse_scaled", item.get("anchor_rmse", 0.0))),
                    "anchor_speed_bias": float(item.get("anchor_speed_bias", 0.0)),
                    "anchor_cosine_mean": float(item.get("anchor_cosine_mean", 0.0)),
                    "speed_scale": float(item.get("speed_scale", 1.0)),
                    "consistency_score": float(item.get("consistency_score", 0.0)),
                    "selection_score": float(item.get("selection_score", 0.0)),
                }
                for item in problem.get("background_candidates", [])
            ]
    if metrics:
        out.update(metrics)
    if save_info:
        out.update(save_info)
    out["preview_png"] = str(png_path) if png_path is not None else ""
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage5 ROI-local PINN-proxy + diffusion-style refinement.")
    parser.add_argument("--stage4-dir", type=Path, default=DEFAULT_STAGE4_DIR)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_STAGE5_DIR)
    parser.add_argument("--selection", choices=("representative", "frames"), default="representative")
    parser.add_argument("--frame-times", default="", help="Comma-separated time_str values for --selection=frames.")
    parser.add_argument("--include-sources", default="wind,amdar,turb", help="Comma-separated direct sources used as anchors.")
    parser.add_argument("--holdout-every", type=int, default=0, help="Hold out every Nth direct source point for validation; 0 disables.")
    parser.add_argument("--background-dir", type=Path, default=None, help="Directory or file containing ERA5/GFS ROI background NPZ files.")
    parser.add_argument(
        "--background-dirs",
        default="",
        help="Comma-separated candidate background directories or files. Used when --background-dir is not set.",
    )
    parser.add_argument(
        "--internal-stage5-dir",
        type=Path,
        default=None,
        help="Optional prior Stage5 output dir; previous frame Stage5 output can be used as an internal temporal background candidate.",
    )
    parser.add_argument(
        "--disable-internal-stage5-background",
        action="store_true",
        help="Disable previous-frame Stage5 temporal background candidate.",
    )
    parser.add_argument("--background-init-weight", type=float, default=0.25)
    parser.add_argument("--background-relax-weight", type=float, default=0.04)
    parser.add_argument("--background-data-weight", type=float, default=0.35, help="Additional multiplier for background blending strength.")
    parser.add_argument("--background-consistency-scale", type=float, default=8.0, help="Reduce background influence when it conflicts with local anchor flow.")
    parser.add_argument("--background-top-k", type=int, default=1, help="Fuse the top-K most consistent backgrounds; 1 means choose one best background.")
    parser.add_argument("--background-relax-on-original-nonanchor", type=int, default=0, help="Allow background relax on original non-anchor voxels; default 0 keeps external background on expanded area only.")
    parser.add_argument("--background-consistency-threshold", type=float, default=0.35)
    parser.add_argument("--expanded-conf-cap", type=float, default=0.42)
    parser.add_argument("--original-delta-cap", type=float, default=3.0)
    parser.add_argument("--hazard-conservative", action="store_true", help="Use lower diffusion/PINN strength for hazard-heavy frames.")
    parser.add_argument("--hazard-threshold", type=int, default=100)
    parser.add_argument("--refine-empty", action="store_true", help="Allow refinement for frames with empty Stage4 recon if direct anchors exist.")
    parser.add_argument("--pad-xy", type=int, default=8)
    parser.add_argument("--pad-z", type=int, default=1)
    parser.add_argument("--max-local-voxels", type=int, default=15_000_000)
    parser.add_argument("--local-expand-iters", type=int, default=1)
    parser.add_argument("--expand-min-neighbors", type=int, default=2)
    parser.add_argument("--max-expand-voxels", type=int, default=5000)
    parser.add_argument("--expand-conf-scale", type=float, default=0.55)
    parser.add_argument("--iterations", type=int, default=8)
    parser.add_argument("--diffusion-strength", type=float, default=0.22)
    parser.add_argument("--pinn-strength", type=float, default=0.035)
    parser.add_argument("--anchor-preserve", type=float, default=0.90)
    parser.add_argument("--internal-background-expanded-weight", type=float, default=1.0)
    parser.add_argument("--internal-background-near-anchor-weight", type=float, default=0.65)
    parser.add_argument("--internal-background-original-weight", type=float, default=0.10)
    parser.add_argument("--anchor-neighborhood-radius-xy", type=int, default=3)
    parser.add_argument("--anchor-neighborhood-radius-z", type=int, default=1)
    parser.add_argument("--direction-consistency-weight", type=float, default=0.12)
    parser.add_argument("--direction-consistency-hazard-weight", type=float, default=0.08)
    parser.add_argument("--direction-consistency-reference", default="background_or_anchor_neighborhood")
    parser.add_argument("--make-plots", type=int, default=1)
    parser.add_argument("--max-plot-vectors", type=int, default=350)
    args = parser.parse_args()

    stage4_dir = args.stage4_dir
    summary_path = args.summary or (stage4_dir / "stage4_summary.json")
    summary = _load_json(summary_path)
    if not isinstance(summary, list):
        raise TypeError(f"Expected Stage4 summary list at {summary_path}")
    rows = _select_representative_rows(summary) if args.selection == "representative" else _select_frame_rows(summary, args.frame_times)

    include_sources = {token.strip().lower() for token in args.include_sources.split(",") if token.strip()}
    background_dirs = [Path(token.strip()) for token in str(args.background_dirs).split(",") if token.strip()]
    if not background_dirs and args.background_dir is None:
        background_dirs = [path for path in DEFAULT_BACKGROUND_DIRS if path.exists()]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    for row in rows:
        stem = f"{_int(row, 'source_index'):05d}_{_frame_id(row)}"
        filename = str(row.get("filename") or f"frame_{row.get('time_str')}.npz")
        npz_path = stage4_dir / filename
        if not npz_path.exists():
            records.append(_record_summary(row, "skipped", f"missing_npz:{npz_path}"))
            continue
        if _int(row, "recon_filled_voxels") <= 0 and not args.refine_empty:
            print(f"[stage5] skip empty Stage4 recon {stem}")
            records.append(_record_summary(row, "skipped", "empty_stage4_reconstruction"))
            continue
        try:
            frame_args = argparse.Namespace(**vars(args))
            if bool(args.hazard_conservative) and _int(row, "hazard_alert_voxels") >= int(args.hazard_threshold):
                frame_args.diffusion_strength = min(float(frame_args.diffusion_strength), 0.14)
                frame_args.pinn_strength = min(float(frame_args.pinn_strength), 0.018)
                frame_args.original_delta_cap = min(float(frame_args.original_delta_cap), 1.5)
            sparse = _load_stage4_sparse(npz_path)
            try:
                background_candidates = _resolve_background_candidates(args.background_dir, background_dirs, _frame_id(row))
            except Exception as exc:
                print(f"[stage5][WARN] background load failed for {_frame_id(row)}: {type(exc).__name__}: {exc}")
                background_candidates = []
            if not bool(args.disable_internal_stage5_background):
                internal_background = _find_previous_stage5_background(summary, row, args.internal_stage5_dir or args.out_dir)
                if internal_background is not None:
                    background_candidates = [internal_background, *background_candidates]
            problem = _build_local_problem(
                sparse,
                pad_z=frame_args.pad_z,
                pad_xy=frame_args.pad_xy,
                include_sources=include_sources,
                max_local_voxels=frame_args.max_local_voxels,
                holdout_every=frame_args.holdout_every,
                background=None,
            )
            problem["hazard_frame"] = bool(_int(row, "hazard_alert_voxels") >= int(frame_args.hazard_threshold))
            background_selected, background_scored = _choose_background_for_problem(
                problem,
                background_candidates,
                consistency_scale=float(frame_args.background_consistency_scale),
                top_k=int(frame_args.background_top_k),
            )
            if background_selected is not None:
                problem["background"] = background_selected["sampled"]
                problem["background_selected_path"] = str(background_selected["path"])
                problem["background_anchor_rmse"] = float(background_selected["anchor_rmse"])
                problem["background_anchor_rmse_scaled"] = float(background_selected.get("anchor_rmse_scaled", background_selected["anchor_rmse"]))
                problem["background_anchor_speed_bias"] = float(background_selected["anchor_speed_bias"])
                problem["background_anchor_cosine_mean"] = float(background_selected.get("anchor_cosine_mean", 0.0))
                problem["background_consistency_score"] = float(background_selected["consistency_score"])
                problem["background_speed_scale"] = float(background_selected.get("speed_scale", 1.0))
                problem["background_candidates"] = background_scored
            refined, metrics = _refine_local(problem, frame_args)
            out_npz = args.out_dir / f"frame_{_frame_id(row)}_stage5.npz"
            save_info = _save_stage5_npz(out_npz, row, problem, refined, metrics, frame_args)
            png_path: Path | None = None
            if int(args.make_plots):
                png_path = args.out_dir / f"{stem}_stage5_roi_3d.png"
                _render_stage5_3d_png(png_path, row, problem, refined, max_vectors=args.max_plot_vectors)
            records.append(_record_summary(row, "ok", "", problem, metrics, save_info, png_path))
            print(f"[stage5] wrote {out_npz}")
        except Exception as exc:
            records.append(_record_summary(row, "failed", f"{type(exc).__name__}: {exc}"))
            print(f"[stage5][WARN] failed {stem}: {type(exc).__name__}: {exc}")

    summary_out = args.out_dir / "stage5_summary.json"
    with summary_out.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "stage": "stage5_pinn_proxy_diffusion_style_v1",
                "stage4_dir": str(stage4_dir),
                "summary": str(summary_path),
                "selection": args.selection,
                "include_sources": sorted(include_sources),
                "output_dir": str(args.out_dir),
                "frame_count": len(records),
                "notes": [
                    "Standalone Stage5 scaffold; Stage4 outputs are read-only inputs.",
                    "This is not a trained neural diffusion model.",
                    "Outputs are sparse ROI refinements, not dense nationwide wind fields.",
                ],
                "config": {
                    "pad_xy": int(args.pad_xy),
                    "pad_z": int(args.pad_z),
                    "local_expand_iters": int(args.local_expand_iters),
                    "iterations": int(args.iterations),
                    "diffusion_strength": float(args.diffusion_strength),
                    "pinn_strength": float(args.pinn_strength),
                    "anchor_preserve": float(args.anchor_preserve),
                    "holdout_every": int(args.holdout_every),
                    "background_dir": str(args.background_dir) if args.background_dir else "",
                    "background_dirs": [str(path) for path in background_dirs],
                    "internal_stage5_dir": str(args.internal_stage5_dir or args.out_dir),
                    "disable_internal_stage5_background": bool(args.disable_internal_stage5_background),
                    "background_init_weight": float(args.background_init_weight),
                    "background_relax_weight": float(args.background_relax_weight),
                    "background_data_weight": float(args.background_data_weight),
                    "background_consistency_scale": float(args.background_consistency_scale),
                    "background_top_k": int(args.background_top_k),
                    "background_relax_on_original_nonanchor": int(args.background_relax_on_original_nonanchor),
                    "background_consistency_threshold": float(args.background_consistency_threshold),
                    "expanded_conf_cap": float(args.expanded_conf_cap),
                    "original_delta_cap": float(args.original_delta_cap),
                    "hazard_conservative": bool(args.hazard_conservative),
                    "internal_background_expanded_weight": float(args.internal_background_expanded_weight),
                    "internal_background_near_anchor_weight": float(args.internal_background_near_anchor_weight),
                    "internal_background_original_weight": float(args.internal_background_original_weight),
                    "anchor_neighborhood_radius_xy": int(args.anchor_neighborhood_radius_xy),
                    "anchor_neighborhood_radius_z": int(args.anchor_neighborhood_radius_z),
                    "direction_consistency_weight": float(args.direction_consistency_weight),
                    "direction_consistency_hazard_weight": float(args.direction_consistency_hazard_weight),
                    "direction_consistency_reference": str(args.direction_consistency_reference),
                },
                "frames": records,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[stage5] wrote {summary_out}")


if __name__ == "__main__":
    main()
