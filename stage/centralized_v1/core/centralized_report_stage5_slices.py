"""Slice visualization for centralized_v1 Stage5 future wind outputs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import DELTA_ALT
from stage.centralized_v1.configs.centralized_v1_contract import C5_FUTURE_WIND_CONF, C5_FUTURE_WIND_U, C5_FUTURE_WIND_V


def _render_horizontal(ax, u3d, v3d, z_idx, title):
    speed = np.sqrt(u3d[z_idx] ** 2 + v3d[z_idx] ** 2)
    im = ax.imshow(speed, cmap="turbo", origin="upper")
    step = max(1, speed.shape[0] // 40)
    yy, xx = np.mgrid[0:speed.shape[0]:step, 0:speed.shape[1]:step]
    uu = u3d[z_idx][::step, ::step]
    vv = -v3d[z_idx][::step, ::step]
    ax.quiver(xx, yy, uu, vv, color="black", alpha=0.4, scale=200)
    ax.set_title(title)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="future speed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Slice visualization for centralized_v1 Stage5 future wind.")
    parser.add_argument("--frame-npz", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--z-levels", default="1,3")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with np.load(args.frame_npz, allow_pickle=False) as z:
        u3d = np.asarray(z[C5_FUTURE_WIND_U], dtype=np.float32)
        v3d = np.asarray(z[C5_FUTURE_WIND_V], dtype=np.float32)
        time_str = str(z["time_str"]) if "time_str" in z.files else args.frame_npz.stem
    z_levels = [int(token.strip()) for token in str(args.z_levels).split(",") if token.strip()]
    z_levels = [min(max(0, z_idx), u3d.shape[0] - 1) for z_idx in z_levels]
    z_levels = list(dict.fromkeys(z_levels))

    fig, axes = plt.subplots(1, len(z_levels), figsize=(6.2 * len(z_levels), 4.8), constrained_layout=True)
    if len(z_levels) == 1:
        axes = [axes]
    for ax, z_idx in zip(axes, z_levels):
        alt_m = z_idx * DELTA_ALT
        _render_horizontal(ax, u3d, v3d, z_idx, f"Future wind slice z={z_idx} (~{alt_m:.0f} m)")
    fig.suptitle(f"Centralized v1 Stage5 future wind slices - {time_str}", fontsize=12)
    out = args.out_dir / f"{time_str}_centralized_stage5_future_slices.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    main()
