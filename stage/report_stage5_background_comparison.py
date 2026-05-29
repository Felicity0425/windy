"""Render Stage4 vs Stage5 vs optional ERA5/GFS ROI background comparisons."""

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

from stage.stage5_background_utils import load_background, load_background_candidates


DEFAULT_STAGE4_DIR = Path("/data/LFT-W02_data/pengxu/stage4_output_v2")
DEFAULT_STAGE5_DIR = Path("/data/LFT-W02_data/pengxu/stage5_output_v1_keyframes")
DEFAULT_BACKGROUND_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/era5_roi_npz")
DEFAULT_BACKGROUND_DIRS = [
    Path("/data/LFT-W02_data/pengxu/stage5_external_background/era5_roi"),
    Path("/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz"),
    Path("/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz"),
]
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_background_comparison")
DEFAULT_FRAME_TIMES = "20260124013600,20260222063600,20260129114200,20260206174200"

LAT_MIN = 12.2
LAT_MAX = 54.2
LON_MIN = 73.0
LON_MAX = 135.0
ALT_STEP_M = 500.0


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


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


def _load_stage4(stage4_dir: Path, time_str: str) -> dict[str, Any]:
    path = stage4_dir / f"frame_{time_str}.npz"
    with np.load(path, allow_pickle=False) as npz:
        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int64).tolist())
        idx = np.asarray(npz["recon_idx"], dtype=np.int64)
        u = np.asarray(npz["recon_u_val"], dtype=np.float32)
        v = np.asarray(npz["recon_v_val"], dtype=np.float32)
        conf = np.asarray(npz["recon_conf_val"], dtype=np.float32)
        mask = np.asarray(npz["recon_mask_val"], dtype=np.float32)
    n = min(idx.size, u.size, v.size, conf.size, mask.size)
    idx, u, v, conf, mask = idx[:n], u[:n], v[:n], conf[:n], mask[:n]
    keep = (mask > 0) & np.isfinite(u) & np.isfinite(v) & np.isfinite(conf)
    z, y, x = _linear_to_zyx(idx[keep], shape)
    _, h_dim, w_dim = shape
    lon, lat = _xy_to_lonlat(x, y, h_dim, w_dim)
    return {
        "label": "Stage4 sparse reconstruction",
        "shape": shape,
        "idx": idx[keep],
        "lon": lon,
        "lat": lat,
        "alt_km": z.astype(np.float32) * (ALT_STEP_M / 1000.0),
        "u": u[keep],
        "v": v[keep],
        "conf": conf[keep],
    }


def _load_stage5(stage5_dir: Path, time_str: str) -> dict[str, Any]:
    path = stage5_dir / f"frame_{time_str}_stage5.npz"
    with np.load(path, allow_pickle=False) as npz:
        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int64).tolist())
        idx = np.asarray(npz["refined_idx"], dtype=np.int64)
        u = np.asarray(npz["refined_u_val"], dtype=np.float32)
        v = np.asarray(npz["refined_v_val"], dtype=np.float32)
        conf = np.asarray(npz["refined_conf_val"], dtype=np.float32)
        original = np.asarray(npz["original_mask_val"], dtype=np.float32) if "original_mask_val" in npz.files else np.ones_like(conf)
    z, y, x = _linear_to_zyx(idx, shape)
    _, h_dim, w_dim = shape
    lon, lat = _xy_to_lonlat(x, y, h_dim, w_dim)
    return {
        "label": "Stage5 ROI refinement",
        "shape": shape,
        "idx": idx,
        "lon": lon,
        "lat": lat,
        "alt_km": z.astype(np.float32) * (ALT_STEP_M / 1000.0),
        "u": u,
        "v": v,
        "conf": conf,
        "original": original,
    }


def _load_background(background_dir: Path | None, time_str: str, roi: dict[str, Any]) -> dict[str, Any] | None:
    if background_dir is None:
        return None
    bg = load_background(background_dir, time_str)
    if bg is None:
        return None
    lat = np.asarray(bg["lat"], dtype=np.float32)
    lon = np.asarray(bg["lon"], dtype=np.float32)
    alt = np.asarray(bg["alt_km"], dtype=np.float32)
    u = np.asarray(bg["u"], dtype=np.float32)
    v = np.asarray(bg["v"], dtype=np.float32)
    lon_min, lon_max = float(np.min(roi["lon"])), float(np.max(roi["lon"]))
    lat_min, lat_max = float(np.min(roi["lat"])), float(np.max(roi["lat"]))
    alt_min, alt_max = float(np.min(roi["alt_km"])), float(np.max(roi["alt_km"]))
    lon_keep = np.where((lon >= lon_min - 0.5) & (lon <= lon_max + 0.5))[0]
    lat_keep = np.where((lat >= lat_min - 0.5) & (lat <= lat_max + 0.5))[0]
    alt_keep = np.where((alt >= alt_min - 0.5) & (alt <= alt_max + 0.5))[0]
    if lon_keep.size == 0 or lat_keep.size == 0 or alt_keep.size == 0:
        return None
    return {
        "label": "ERA5/GFS ROI background",
        "path": str(bg.get("path", "")),
        "lon": lon,
        "lat": lat,
        "alt_km": alt,
        "u": u,
        "v": v,
        "lon_keep": lon_keep,
        "lat_keep": lat_keep,
        "alt_keep": alt_keep,
        "conf": np.full(len(lon_keep) * len(lat_keep) * len(alt_keep), 0.55, dtype=np.float32),
    }


def _load_background_candidates_for_roi(background_dirs: list[Path], time_str: str, roi: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for bg in load_background_candidates(background_dirs, time_str):
        sampled = _load_background(Path(str(bg["path"])), time_str, roi)
        if sampled is not None:
            out.append(sampled)
    return out


def _sample_background_points(
    background: dict[str, Any] | None,
    lon: np.ndarray,
    lat: np.ndarray,
    alt_km: np.ndarray,
) -> dict[str, Any] | None:
    if background is None:
        return None
    alt_axis = np.asarray(background["alt_km"], dtype=np.float32)
    lat_axis = np.asarray(background["lat"], dtype=np.float32)
    lon_axis = np.asarray(background["lon"], dtype=np.float32)
    u = np.asarray(background["u"], dtype=np.float32)
    v = np.asarray(background["v"], dtype=np.float32)
    if u.ndim != 3 or v.shape != u.shape:
        return None

    def _nearest(axis: np.ndarray, query: np.ndarray) -> np.ndarray:
        idx = np.searchsorted(axis, query)
        idx = np.clip(idx, 0, axis.size - 1)
        left = np.clip(idx - 1, 0, axis.size - 1)
        choose_right = np.abs(axis[idx] - query) < np.abs(axis[left] - query)
        return np.where(choose_right, idx, left).astype(np.int64, copy=False)

    bz = _nearest(alt_axis, np.asarray(alt_km, dtype=np.float32))
    by = _nearest(lat_axis, np.asarray(lat, dtype=np.float32))
    bx = _nearest(lon_axis, np.asarray(lon, dtype=np.float32))
    u = u[bz, by, bx]
    v = v[bz, by, bx]
    speed = np.sqrt(u ** 2 + v ** 2)
    return {
        "label": "ERA5/GFS ROI background",
        "path": str(background.get("path", "")),
        "lon": np.asarray(lon, dtype=np.float32),
        "lat": np.asarray(lat, dtype=np.float32),
        "alt_km": np.asarray(alt_km, dtype=np.float32),
        "u": u,
        "v": v,
        "speed": speed,
        "conf": np.full(u.size, 0.55, dtype=np.float32),
    }


def _build_shared_support(stage4: dict[str, Any], stage5: dict[str, Any], max_vectors: int) -> dict[str, Any] | None:
    if stage4["shape"] != stage5["shape"]:
        raise ValueError(f"Stage4/Stage5 grid shapes differ: {stage4['shape']} vs {stage5['shape']}")
    idx4 = np.asarray(stage4["idx"], dtype=np.int64)
    idx5 = np.asarray(stage5["idx"], dtype=np.int64)
    if idx4.size == 0 or idx5.size == 0:
        return None
    pos4 = {int(idx): i for i, idx in enumerate(idx4)}
    common_idx = []
    pos4_list = []
    pos5_list = []
    for j, idx in enumerate(idx5):
        i = pos4.get(int(idx))
        if i is None:
            continue
        common_idx.append(int(idx))
        pos4_list.append(i)
        pos5_list.append(j)
    if not common_idx:
        return None
    common_idx = np.asarray(common_idx, dtype=np.int64)
    pos4_arr = np.asarray(pos4_list, dtype=np.int64)
    pos5_arr = np.asarray(pos5_list, dtype=np.int64)
    stage5_speed = np.sqrt(np.asarray(stage5["u"], dtype=np.float32)[pos5_arr] ** 2 + np.asarray(stage5["v"], dtype=np.float32)[pos5_arr] ** 2)
    order = np.argsort(stage5_speed)[::-1]
    if order.size > int(max_vectors):
        order = order[: int(max_vectors)]
    common_idx = common_idx[order]
    pos4_arr = pos4_arr[order]
    pos5_arr = pos5_arr[order]
    z, y, x = _linear_to_zyx(common_idx, stage5["shape"])
    _, h_dim, w_dim = stage5["shape"]
    lon, lat = _xy_to_lonlat(x, y, h_dim, w_dim)
    alt = z.astype(np.float32) * (ALT_STEP_M / 1000.0)
    stage4_u = np.asarray(stage4["u"], dtype=np.float32)[pos4_arr]
    stage4_v = np.asarray(stage4["v"], dtype=np.float32)[pos4_arr]
    stage4_conf = np.asarray(stage4["conf"], dtype=np.float32)[pos4_arr]
    stage5_u = np.asarray(stage5["u"], dtype=np.float32)[pos5_arr]
    stage5_v = np.asarray(stage5["v"], dtype=np.float32)[pos5_arr]
    stage5_conf = np.asarray(stage5["conf"], dtype=np.float32)[pos5_arr]
    return {
        "idx": common_idx,
        "lon": lon,
        "lat": lat,
        "alt_km": alt,
        "stage4": {
            "u": stage4_u,
            "v": stage4_v,
            "conf": stage4_conf,
            "speed": np.sqrt(stage4_u ** 2 + stage4_v ** 2),
        },
        "stage5": {
            "u": stage5_u,
            "v": stage5_v,
            "conf": stage5_conf,
            "speed": np.sqrt(stage5_u ** 2 + stage5_v ** 2),
        },
    }


def _plot_panel(ax: Any, field: dict[str, Any], title: str, max_vectors: int, *, color_key: str = "speed") -> None:
    lon = np.asarray(field["lon"], dtype=np.float32)
    lat = np.asarray(field["lat"], dtype=np.float32)
    alt = np.asarray(field["alt_km"], dtype=np.float32)
    u = np.asarray(field["u"], dtype=np.float32)
    v = np.asarray(field["v"], dtype=np.float32)
    conf = np.asarray(field.get("conf", np.ones_like(u)), dtype=np.float32)
    speed = np.asarray(field.get("speed", np.sqrt(u ** 2 + v ** 2)), dtype=np.float32)
    if lon.size > max_vectors:
        order = np.argsort(speed)[::-1][:max_vectors]
        lon, lat, alt, u, v, conf, speed = lon[order], lat[order], alt[order], u[order], v[order], conf[order], speed[order]
    speed_ref = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    span = max(0.5, float(np.max(lon) - np.min(lon)) if lon.size else 0.5, float(np.max(lat) - np.min(lat)) if lat.size else 0.5)
    scale = span * 0.055 * np.clip(speed / max(speed_ref, 1e-6), 0.25, 1.8)
    denom = np.maximum(speed, 1e-6)
    dx = u / denom * scale
    dy = v / denom * scale
    color = speed if color_key == "speed" else conf
    cmap = "turbo" if color_key == "speed" else "viridis"
    sc = ax.scatter(lon, lat, alt, c=color, s=14 + 18 * np.clip(conf, 0.0, 1.0), cmap=cmap, alpha=0.82)
    ax.quiver(lon, lat, alt, dx, dy, np.zeros_like(dx), length=1.0, normalize=False, color="black", linewidth=0.55, alpha=0.62)
    ax.set_title(f"{title}\nN={lon.size}", fontsize=10)
    ax.set_xlabel("Lon")
    ax.set_ylabel("Lat")
    ax.set_zlabel("km")
    ax.view_init(elev=25, azim=-58)
    ax.grid(True, alpha=0.25)
    return sc


def _plot_delta_panel(ax: Any, field: dict[str, Any], title: str, max_vectors: int) -> None:
    lon = np.asarray(field["lon"], dtype=np.float32)
    lat = np.asarray(field["lat"], dtype=np.float32)
    alt = np.asarray(field["alt_km"], dtype=np.float32)
    du = np.asarray(field["du"], dtype=np.float32)
    dv = np.asarray(field["dv"], dtype=np.float32)
    conf = np.asarray(field.get("conf", np.ones_like(du)), dtype=np.float32)
    speed = np.sqrt(du ** 2 + dv ** 2)
    if lon.size > max_vectors:
        order = np.argsort(speed)[::-1][:max_vectors]
        lon, lat, alt, du, dv, conf, speed = lon[order], lat[order], alt[order], du[order], dv[order], conf[order], speed[order]
    speed_ref = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    span = max(0.5, float(np.max(lon) - np.min(lon)) if lon.size else 0.5, float(np.max(lat) - np.min(lat)) if lat.size else 0.5)
    scale = span * 0.055 * np.clip(speed / max(speed_ref, 1e-6), 0.25, 1.8)
    denom = np.maximum(speed, 1e-6)
    dx = du / denom * scale
    dy = dv / denom * scale
    sc = ax.scatter(lon, lat, alt, c=speed, s=14 + 18 * np.clip(conf, 0.0, 1.0), cmap="magma", alpha=0.82)
    ax.quiver(lon, lat, alt, dx, dy, np.zeros_like(dx), length=1.0, normalize=False, color="black", linewidth=0.55, alpha=0.62)
    ax.set_title(f"{title}\nN={lon.size}", fontsize=10)
    ax.set_xlabel("Lon")
    ax.set_ylabel("Lat")
    ax.set_zlabel("km")
    ax.view_init(elev=25, azim=-58)
    ax.grid(True, alpha=0.25)
    return sc


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Stage4/Stage5/background side-by-side ROI 3D PNGs.")
    parser.add_argument("--stage4-dir", type=Path, default=DEFAULT_STAGE4_DIR)
    parser.add_argument("--stage5-dir", type=Path, default=DEFAULT_STAGE5_DIR)
    parser.add_argument("--background-dir", type=Path, default=DEFAULT_BACKGROUND_DIR)
    parser.add_argument("--background-dirs", default="", help="Comma-separated candidate background directories or files.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--frame-times", default=DEFAULT_FRAME_TIMES)
    parser.add_argument("--max-vectors", type=int, default=250)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    background_dirs = [Path(token.strip()) for token in str(args.background_dirs).split(",") if token.strip()]
    if not background_dirs and args.background_dir is None:
        background_dirs = [path for path in DEFAULT_BACKGROUND_DIRS if path.exists()]
    records: list[dict[str, Any]] = []
    for time_str in [token.strip() for token in args.frame_times.split(",") if token.strip()]:
        try:
            stage4 = _load_stage4(args.stage4_dir, time_str)
            stage5 = _load_stage5(args.stage5_dir, time_str)
            background = _load_background(args.background_dir, time_str, stage5) if args.background_dir else None
            if background is None and background_dirs:
                candidates = _load_background_candidates_for_roi(background_dirs, time_str, stage5)
                background = candidates[0] if candidates else None
            shared = _build_shared_support(stage4, stage5, args.max_vectors)
            if shared is None:
                raise ValueError(f"No shared Stage4/Stage5 support found for {time_str}")
            background = _sample_background_points(background, shared["lon"], shared["lat"], shared["alt_km"])
            if background is None:
                raise ValueError(f"Background sampling failed for {time_str}")
            fields = [
                {
                    "label": "Stage4 sparse reconstruction",
                    "lon": shared["lon"],
                    "lat": shared["lat"],
                    "alt_km": shared["alt_km"],
                    "u": shared["stage4"]["u"],
                    "v": shared["stage4"]["v"],
                    "conf": shared["stage4"]["conf"],
                    "speed": shared["stage4"]["speed"],
                },
                {
                    "label": "Stage5 ROI refinement",
                    "lon": shared["lon"],
                    "lat": shared["lat"],
                    "alt_km": shared["alt_km"],
                    "u": shared["stage5"]["u"],
                    "v": shared["stage5"]["v"],
                    "conf": shared["stage5"]["conf"],
                    "speed": shared["stage5"]["speed"],
                },
                background,
            ]
            fig = plt.figure(figsize=(6.4 * len(fields), 6.0), constrained_layout=True)
            for i, field in enumerate(fields, 1):
                ax = fig.add_subplot(1, len(fields), i, projection="3d")
                _plot_panel(ax, field, str(field["label"]), args.max_vectors, color_key="speed")
            fig.suptitle(
                f"Stage4 vs Stage5 vs background - {time_str}\n"
                "Shared sparse support comparison; background sampled on the same points.",
                fontsize=12,
            )
            out = args.out_dir / f"{time_str}_stage4_stage5_background_3d.png"
            fig.savefig(out, dpi=150)
            plt.close(fig)
            delta = {
                "label": "Stage5 - background delta",
                "lon": shared["lon"],
                "lat": shared["lat"],
                "alt_km": shared["alt_km"],
                "du": shared["stage5"]["u"] - background["u"],
                "dv": shared["stage5"]["v"] - background["v"],
                "conf": shared["stage5"]["conf"],
            }
            diff_fig = plt.figure(figsize=(6.4, 6.0), constrained_layout=True)
            diff_ax = diff_fig.add_subplot(111, projection="3d")
            _plot_delta_panel(diff_ax, delta, delta["label"], args.max_vectors)
            diff_fig.suptitle(
                f"Stage5 minus background - {time_str}\n"
                "Shared sparse support; vector delta on the same ROI mask.",
                fontsize=12,
            )
            diff_out = args.out_dir / f"{time_str}_stage5_minus_background_3d.png"
            diff_fig.savefig(diff_out, dpi=150)
            plt.close(diff_fig)
            records.append(
                {
                    "time_str": time_str,
                    "status": "ok",
                    "png": str(out),
                    "delta_png": str(diff_out),
                    "background": bool(background is not None),
                    "background_path": str(background.get("path", "")) if background is not None else "",
                    "shared_points": int(shared["idx"].size),
                    "sample_mode": "shared_stage4_stage5_intersection",
                }
            )
            print(f"[compare] wrote {out}")
            print(f"[compare] wrote {diff_out}")
        except Exception as exc:
            records.append({"time_str": time_str, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"})
            print(f"[compare][WARN] failed {time_str}: {type(exc).__name__}: {exc}")
    with (args.out_dir / "comparison_summary.json").open("w", encoding="utf-8") as f:
        json.dump({"frames": records}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
