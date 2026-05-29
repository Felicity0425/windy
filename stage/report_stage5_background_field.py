"""Render GFS/GDAS/ERA5 ROI background fields as 3D wind PNGs."""

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

from stage.stage5_background_utils import load_background, resolve_background_path


DEFAULT_BACKGROUND_DIR = Path("/data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz")
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage5_visualizations/gfs_gdas_background")


def _subset_indices(values: np.ndarray, lo: float | None, hi: float | None, stride: int) -> np.ndarray:
    idx = np.arange(values.size)
    keep = np.ones(values.size, dtype=bool)
    if lo is not None:
        keep &= values >= float(lo)
    if hi is not None:
        keep &= values <= float(hi)
    idx = idx[keep]
    return idx[:: max(1, int(stride))]


def _render(path: Path, data: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    lat = data["lat"]
    lon = data["lon"]
    alt = data["alt_km"]
    lon_min, lon_max = (None, None) if not args.lon_range else [float(v) for v in args.lon_range.split(",")]
    lat_min, lat_max = (None, None) if not args.lat_range else [float(v) for v in args.lat_range.split(",")]
    alt_min, alt_max = (None, None) if not args.alt_range else [float(v) for v in args.alt_range.split(",")]
    xi = _subset_indices(lon, lon_min, lon_max, args.xy_stride)
    yi = _subset_indices(lat, lat_min, lat_max, args.xy_stride)
    zi = _subset_indices(alt, alt_min, alt_max, args.z_stride)
    if xi.size == 0 or yi.size == 0 or zi.size == 0:
        raise ValueError("Selected background subset is empty.")

    zz, yy, xx = np.meshgrid(zi, yi, xi, indexing="ij")
    flat_z = zz.reshape(-1)
    flat_y = yy.reshape(-1)
    flat_x = xx.reshape(-1)
    u = data["u"][flat_z, flat_y, flat_x]
    v = data["v"][flat_z, flat_y, flat_x]
    speed = np.sqrt(u ** 2 + v ** 2)
    if flat_x.size > int(args.max_vectors):
        order = np.argsort(speed)[::-1][: int(args.max_vectors)]
        flat_z = flat_z[order]
        flat_y = flat_y[order]
        flat_x = flat_x[order]
        u = u[order]
        v = v[order]
        speed = speed[order]

    plot_lon = lon[flat_x]
    plot_lat = lat[flat_y]
    plot_alt = alt[flat_z]
    speed_ref = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    span = max(0.5, float(np.max(plot_lon) - np.min(plot_lon)), float(np.max(plot_lat) - np.min(plot_lat)))
    scale = span * 0.055 * np.clip(speed / max(speed_ref, 1e-6), 0.25, 1.8)
    denom = np.maximum(speed, 1e-6)
    dx = u / denom * scale
    dy = v / denom * scale

    fig = plt.figure(figsize=(13, 10), constrained_layout=True)
    ax = fig.add_subplot(111, projection="3d")
    sc = ax.scatter(plot_lon, plot_lat, plot_alt, c=speed, s=18, cmap="turbo", alpha=0.84)
    ax.quiver(plot_lon, plot_lat, plot_alt, dx, dy, np.zeros_like(dx), length=1.0, normalize=False, color="black", linewidth=0.55, alpha=0.62)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.set_zlabel("Altitude (km)")
    ax.set_title(
        f"Operational background wind ROI - {data['time_str']}\n"
        "GFS/GDAS/ERA5 pressure-level background; arrows are horizontal wind u/v scaled for readability",
        fontsize=12,
    )
    ax.grid(True, alpha=0.25)
    ax.view_init(elev=26, azim=-58)
    fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02, label="wind speed (m/s)")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return {
        "png": str(path),
        "source": data["path"],
        "time_str": data["time_str"],
        "vectors": int(plot_lon.size),
        "lon_range": [float(np.min(plot_lon)), float(np.max(plot_lon))],
        "lat_range": [float(np.min(plot_lat)), float(np.max(plot_lat))],
        "alt_range_km": [float(np.min(plot_alt)), float(np.max(plot_alt))],
        "speed_mean": float(np.mean(speed)),
        "speed_p90": float(np.quantile(speed, 0.90)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a GFS/GDAS/ERA5 Stage5 background NPZ as 3D wind vectors.")
    parser.add_argument("--background-dir", type=Path, default=DEFAULT_BACKGROUND_DIR)
    parser.add_argument("--background-npz", type=Path, default=None)
    parser.add_argument("--time-str", default="", help="time_str to locate <prefix>_<time_str>.npz; defaults to latest *_roi_*.npz.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--lon-range", default="", help="Optional lon_min,lon_max.")
    parser.add_argument("--lat-range", default="", help="Optional lat_min,lat_max.")
    parser.add_argument("--alt-range", default="0,12", help="Optional alt_min,alt_max in km.")
    parser.add_argument("--xy-stride", type=int, default=3)
    parser.add_argument("--z-stride", type=int, default=2)
    parser.add_argument("--max-vectors", type=int, default=900)
    args = parser.parse_args()

    npz_path = args.background_npz or resolve_background_path(args.background_dir, args.time_str)
    if npz_path is None:
        raise FileNotFoundError(f"No background file found for time_str={args.time_str!r} in {args.background_dir}")
    data = load_background(npz_path, args.time_str or npz_path.stem.split("_")[-1])
    if data is None:
        raise RuntimeError(f"Failed to load background file: {npz_path}")
    time_str = args.time_str or str(data["time_str"])
    out_path = args.out_dir / f"{Path(npz_path).stem}_background_3d.png"
    record = _render(out_path, data, args)
    with (args.out_dir / f"{Path(npz_path).stem}_background_summary.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"[background-viz] wrote {out_path}")


if __name__ == "__main__":
    main()
