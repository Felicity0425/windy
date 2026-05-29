"""Render full-ROI Stage5 sparse points against full ERA5/GFS ROI background.

This demo intentionally does not reduce both sides to the shared 250-point
support used by the comparison script. Instead it shows:

1. All Stage5 refined sparse ROI points for the chosen frame
2. The full background ROI crop inside the same bbox / altitude range
3. A dense ROI difference summary sampled on the Stage5 sparse points
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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

from stage.stage5_background_utils import load_background


LAT_MIN = 12.2
LAT_MAX = 54.2
LON_MIN = 73.0
LON_MAX = 135.0
ALT_STEP_M = 500.0

DEFAULT_STAGE5_DIR = Path("/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test")
DEFAULT_BACKGROUND_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/era5_roi")
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo")
DEFAULT_FRAME_TIME = "20260129114200"


def _linear_to_zyx(idx: np.ndarray, shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    _, h_dim, w_dim = shape
    idx64 = np.asarray(idx, dtype=np.int64)
    z = idx64 // (h_dim * w_dim)
    rem = idx64 % (h_dim * w_dim)
    y = rem // w_dim
    x = rem % w_dim
    return z.astype(np.int32), y.astype(np.int32), x.astype(np.int32)


def _xy_to_lonlat(x: np.ndarray, y: np.ndarray, h_dim: int, w_dim: int) -> tuple[np.ndarray, np.ndarray]:
    lon = LON_MIN + (np.asarray(x, dtype=np.float64) + 0.5) * (LON_MAX - LON_MIN) / max(1, w_dim)
    lat = LAT_MAX - (np.asarray(y, dtype=np.float64) + 0.5) * (LAT_MAX - LAT_MIN) / max(1, h_dim)
    return lon.astype(np.float32), lat.astype(np.float32)


def _nearest_indices(values: np.ndarray, query: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    query = np.asarray(query, dtype=np.float32)
    order = np.argsort(values)
    sorted_values = values[order]
    pos = np.searchsorted(sorted_values, query)
    left = np.clip(pos - 1, 0, sorted_values.size - 1)
    right = np.clip(pos, 0, sorted_values.size - 1)
    choose_right = np.abs(sorted_values[right] - query) < np.abs(sorted_values[left] - query)
    return order[np.where(choose_right, right, left)].astype(np.int64, copy=False)


def _load_stage5(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as npz:
        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int64).tolist())
        idx = np.asarray(npz["refined_idx"], dtype=np.int64)
        u = np.asarray(npz["refined_u_val"], dtype=np.float32)
        v = np.asarray(npz["refined_v_val"], dtype=np.float32)
        conf = np.asarray(npz["refined_conf_val"], dtype=np.float32)
        bbox = tuple(int(v) for v in np.asarray(npz["bbox_zyx"], dtype=np.int32).tolist())
        local_shape = tuple(int(v) for v in np.asarray(npz["local_shape"], dtype=np.int32).tolist())
        metrics = json.loads(str(npz["metrics_json"])) if "metrics_json" in npz.files else {}
    z, y, x = _linear_to_zyx(idx, shape)
    _, h_dim, w_dim = shape
    lon, lat = _xy_to_lonlat(x, y, h_dim, w_dim)
    return {
        "shape": shape,
        "bbox": bbox,
        "local_shape": local_shape,
        "idx": idx,
        "z": z,
        "y": y,
        "x": x,
        "lon": lon,
        "lat": lat,
        "alt_km": z.astype(np.float32) * (ALT_STEP_M / 1000.0),
        "u": u,
        "v": v,
        "conf": conf,
        "speed": np.sqrt(u ** 2 + v ** 2),
        "metrics": metrics,
    }


def _crop_background(background: dict[str, Any], stage5: dict[str, Any]) -> dict[str, Any]:
    z0, z1, y0, y1, x0, x1 = stage5["bbox"]
    _, h_dim, w_dim = stage5["shape"]
    gx = np.arange(x0, x1, dtype=np.float32)
    gy = np.arange(y0, y1, dtype=np.float32)
    gz = np.arange(z0, z1, dtype=np.float32)
    lon_axis, _ = _xy_to_lonlat(gx, np.zeros_like(gx), h_dim, w_dim)
    _, lat_axis = _xy_to_lonlat(np.zeros_like(gy), gy, h_dim, w_dim)
    alt_axis = gz * (ALT_STEP_M / 1000.0)

    bx = _nearest_indices(np.asarray(background["lon"], dtype=np.float32), lon_axis)
    by = _nearest_indices(np.asarray(background["lat"], dtype=np.float32), lat_axis)
    bz = _nearest_indices(np.asarray(background["alt_km"], dtype=np.float32), alt_axis)

    u = np.asarray(background["u"], dtype=np.float32)[bz[:, None, None], by[None, :, None], bx[None, None, :]]
    v = np.asarray(background["v"], dtype=np.float32)[bz[:, None, None], by[None, :, None], bx[None, None, :]]
    zz, yy, xx = np.meshgrid(alt_axis, lat_axis, lon_axis, indexing="ij")
    return {
        "path": str(background.get("path", "")),
        "lon_grid": xx,
        "lat_grid": yy,
        "alt_grid": zz,
        "u": u,
        "v": v,
        "speed": np.sqrt(u ** 2 + v ** 2),
    }


def _sample_background_on_stage5(background: dict[str, Any], stage5: dict[str, Any]) -> dict[str, Any]:
    bz = _nearest_indices(np.asarray(background["alt_km"], dtype=np.float32), np.asarray(stage5["alt_km"], dtype=np.float32))
    by = _nearest_indices(np.asarray(background["lat"], dtype=np.float32), np.asarray(stage5["lat"], dtype=np.float32))
    bx = _nearest_indices(np.asarray(background["lon"], dtype=np.float32), np.asarray(stage5["lon"], dtype=np.float32))
    bg_u = np.asarray(background["u"], dtype=np.float32)[bz, by, bx]
    bg_v = np.asarray(background["v"], dtype=np.float32)[bz, by, bx]
    return {
        "u": bg_u,
        "v": bg_v,
        "speed": np.sqrt(bg_u ** 2 + bg_v ** 2),
    }


def _plot_stage5(ax: Any, stage5: dict[str, Any]) -> None:
    conf = np.asarray(stage5["conf"], dtype=np.float32)
    sc = ax.scatter(stage5["lon"], stage5["lat"], stage5["alt_km"], c=conf, s=18 + 34 * np.clip(conf, 0.0, 1.0), cmap="plasma", alpha=0.82)
    speed = np.asarray(stage5["speed"], dtype=np.float32)
    speed_ref = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    span = max(0.5, float(np.max(stage5["lon"]) - np.min(stage5["lon"])), float(np.max(stage5["lat"]) - np.min(stage5["lat"])))
    scale = span * 0.055 * np.clip(speed / max(speed_ref, 1e-6), 0.25, 1.8)
    dx = stage5["u"] / np.maximum(speed, 1e-6) * scale
    dy = stage5["v"] / np.maximum(speed, 1e-6) * scale
    ax.quiver(stage5["lon"], stage5["lat"], stage5["alt_km"], dx, dy, np.zeros_like(dx), length=1.0, normalize=False, color="black", linewidth=0.45, alpha=0.60)
    ax.set_title(f"Stage5 all sparse refined voxels\nN={len(stage5['idx'])}", fontsize=10)
    ax.set_xlabel("Lon")
    ax.set_ylabel("Lat")
    ax.set_zlabel("km")
    ax.view_init(elev=25, azim=-58)
    ax.grid(True, alpha=0.25)
    return sc


def _plot_background(ax: Any, bg_crop: dict[str, Any], xy_stride: int, z_stride: int) -> None:
    lon = bg_crop["lon_grid"][::z_stride, ::xy_stride, ::xy_stride].reshape(-1)
    lat = bg_crop["lat_grid"][::z_stride, ::xy_stride, ::xy_stride].reshape(-1)
    alt = bg_crop["alt_grid"][::z_stride, ::xy_stride, ::xy_stride].reshape(-1)
    u = bg_crop["u"][::z_stride, ::xy_stride, ::xy_stride].reshape(-1)
    v = bg_crop["v"][::z_stride, ::xy_stride, ::xy_stride].reshape(-1)
    speed = np.sqrt(u ** 2 + v ** 2)
    sc = ax.scatter(lon, lat, alt, c=speed, s=9, cmap="turbo", alpha=0.55)
    speed_ref = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    span = max(0.5, float(np.max(lon) - np.min(lon)), float(np.max(lat) - np.min(lat)))
    scale = span * 0.045 * np.clip(speed / max(speed_ref, 1e-6), 0.25, 1.6)
    dx = u / np.maximum(speed, 1e-6) * scale
    dy = v / np.maximum(speed, 1e-6) * scale
    ax.quiver(lon, lat, alt, dx, dy, np.zeros_like(dx), length=1.0, normalize=False, color="black", linewidth=0.35, alpha=0.40)
    ax.set_title(f"Background full ROI crop\nsampled grid N={lon.size}", fontsize=10)
    ax.set_xlabel("Lon")
    ax.set_ylabel("Lat")
    ax.set_zlabel("km")
    ax.view_init(elev=25, azim=-58)
    ax.grid(True, alpha=0.25)
    return sc


def main() -> None:
    parser = argparse.ArgumentParser(description="Full ROI Stage5 vs full ROI background demo.")
    parser.add_argument("--stage5-dir", type=Path, default=DEFAULT_STAGE5_DIR)
    parser.add_argument("--background-dir", type=Path, default=DEFAULT_BACKGROUND_DIR)
    parser.add_argument("--frame-time", default=DEFAULT_FRAME_TIME)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--bg-xy-stride", type=int, default=10)
    parser.add_argument("--bg-z-stride", type=int, default=2)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stage5_path = args.stage5_dir / f"frame_{args.frame_time}_stage5.npz"
    stage5 = _load_stage5(stage5_path)
    background = load_background(args.background_dir, args.frame_time)
    if background is None:
        raise FileNotFoundError(f"No background found for {args.frame_time} in {args.background_dir}")
    bg_scale = float(stage5.get("metrics", {}).get("background_speed_scale", 1.0))

    bg_crop = _crop_background(background, stage5)
    bg_on_stage5 = _sample_background_on_stage5(background, stage5)
    raw_bg_u = np.asarray(bg_on_stage5["u"], dtype=np.float32)
    raw_bg_v = np.asarray(bg_on_stage5["v"], dtype=np.float32)
    scaled_bg_u = raw_bg_u * bg_scale
    scaled_bg_v = raw_bg_v * bg_scale
    raw_du = np.asarray(stage5["u"], dtype=np.float32) - raw_bg_u
    raw_dv = np.asarray(stage5["v"], dtype=np.float32) - raw_bg_v
    raw_diff = np.sqrt(raw_du ** 2 + raw_dv ** 2)
    scaled_du = np.asarray(stage5["u"], dtype=np.float32) - scaled_bg_u
    scaled_dv = np.asarray(stage5["v"], dtype=np.float32) - scaled_bg_v
    scaled_diff = np.sqrt(scaled_du ** 2 + scaled_dv ** 2)

    summary = {
        "frame_time": args.frame_time,
        "stage5_npz": str(stage5_path),
        "background_path": str(background.get("path", "")),
        "stage5_sparse_voxels": int(len(stage5["idx"])),
        "stage5_bbox_zyx": [int(v) for v in stage5["bbox"]],
        "stage5_local_shape": [int(v) for v in stage5["local_shape"]],
        "background_crop_shape": list(np.asarray(bg_crop["u"]).shape),
        "background_sampled_points_on_stage5": int(raw_diff.size),
        "stage5_speed_mean": float(np.mean(stage5["speed"])) if len(stage5["speed"]) else 0.0,
        "background_speed_scale": bg_scale,
        "raw_background_speed_mean_on_stage5_points": float(np.mean(bg_on_stage5["speed"])) if raw_diff.size else 0.0,
        "raw_vector_rmse_on_stage5_points": float(np.sqrt(np.mean(raw_diff ** 2))) if raw_diff.size else 0.0,
        "raw_vector_diff_mean_on_stage5_points": float(np.mean(raw_diff)) if raw_diff.size else 0.0,
        "raw_vector_diff_p90_on_stage5_points": float(np.quantile(raw_diff, 0.90)) if raw_diff.size else 0.0,
        "scaled_background_speed_mean_on_stage5_points": float(np.mean(np.sqrt(scaled_bg_u ** 2 + scaled_bg_v ** 2))) if scaled_diff.size else 0.0,
        "scaled_vector_rmse_on_stage5_points": float(np.sqrt(np.mean(scaled_diff ** 2))) if scaled_diff.size else 0.0,
        "scaled_vector_diff_mean_on_stage5_points": float(np.mean(scaled_diff)) if scaled_diff.size else 0.0,
        "scaled_vector_diff_p90_on_stage5_points": float(np.quantile(scaled_diff, 0.90)) if scaled_diff.size else 0.0,
    }

    fig = plt.figure(figsize=(12.8, 6.0), constrained_layout=True)
    ax1 = fig.add_subplot(1, 2, 1, projection="3d")
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    _plot_stage5(ax1, stage5)
    _plot_background(ax2, bg_crop, args.bg_xy_stride, args.bg_z_stride)
    fig.suptitle(
        f"Stage5 full sparse ROI vs full ROI background crop - {args.frame_time}\n"
        "Left: all Stage5 sparse voxels; Right: full ERA5/GFS ROI crop inside the same bbox.",
        fontsize=12,
    )
    png = args.out_dir / f"{args.frame_time}_stage5_full_vs_background_full_roi.png"
    fig.savefig(png, dpi=160)
    plt.close(fig)

    diff_fig = plt.figure(figsize=(6.4, 6.0), constrained_layout=True)
    ax = diff_fig.add_subplot(111, projection="3d")
    sc = ax.scatter(stage5["lon"], stage5["lat"], stage5["alt_km"], c=scaled_diff, s=18 + 22 * np.clip(stage5["conf"], 0.0, 1.0), cmap="magma", alpha=0.82)
    speed_ref = float(np.quantile(scaled_diff[scaled_diff > 0], 0.75)) if np.any(scaled_diff > 0) else 1.0
    span = max(0.5, float(np.max(stage5["lon"]) - np.min(stage5["lon"])), float(np.max(stage5["lat"]) - np.min(stage5["lat"])))
    scale = span * 0.055 * np.clip(scaled_diff / max(speed_ref, 1e-6), 0.25, 1.8)
    dx = scaled_du / np.maximum(scaled_diff, 1e-6) * scale
    dy = scaled_dv / np.maximum(scaled_diff, 1e-6) * scale
    ax.quiver(stage5["lon"], stage5["lat"], stage5["alt_km"], dx, dy, np.zeros_like(dx), length=1.0, normalize=False, color="black", linewidth=0.45, alpha=0.60)
    ax.set_title(f"Stage5 - scaled background on all Stage5 sparse points\nN={len(stage5['idx'])}", fontsize=10)
    ax.set_xlabel("Lon")
    ax.set_ylabel("Lat")
    ax.set_zlabel("km")
    ax.view_init(elev=25, azim=-58)
    ax.grid(True, alpha=0.25)
    diff_fig.colorbar(sc, ax=ax, fraction=0.04, pad=0.02, label="|Stage5 - scaled background|")
    diff_png = args.out_dir / f"{args.frame_time}_stage5_minus_background_full_sparse.png"
    diff_fig.savefig(diff_png, dpi=160)
    plt.close(diff_fig)

    summary_path = args.out_dir / f"{args.frame_time}_full_roi_demo_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"png": str(png), "diff_png": str(diff_png), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
