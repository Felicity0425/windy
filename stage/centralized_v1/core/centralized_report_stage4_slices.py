"""Slice visualization for centralized_v1 Stage4 outputs."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.colors import PowerNorm
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import ALT_MIN, DELTA_ALT, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from stage.centralized_v1.configs.centralized_v1_contract import (
    C4_BLINDZONE_MASK,
    C4_CLOUD_2D,
    C4_DISPLAY_CONF,
    C4_DISPLAY_FILL_DIAGNOSTICS_JSON,
    C4_DISPLAY_MASK,
    C4_DISPLAY_SOURCE,
    C4_DISPLAY_U,
    C4_DISPLAY_V,
    C4_POINT_EVAL_JSON,
    C4_RELIABILITY_CONF,
    C4_RECON_CONF,
    C4_RECON_MASK,
    C4_RECON_U,
    C4_RECON_V,
)


def _frame_time_from_npz(path: Path) -> str:
    name = path.name
    if name.startswith("frame_"):
        parts = name.split("_")
        if len(parts) > 1:
            return parts[1]
    return path.stem


def _discover_frame_npz(stage4_dir: Path | None, frame_times: str) -> list[Path]:
    if stage4_dir is None:
        return []
    wanted = {token.strip() for token in str(frame_times).split(",") if token.strip()}
    paths = sorted(stage4_dir.glob("frame_*_center_strict.npz"))
    if not wanted:
        return paths
    return [path for path in paths if _frame_time_from_npz(path) in wanted]


def _read_frame_npz_list(path: Path | None) -> list[Path]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"--frame-npz-list-file must contain a JSON list: {path}")
    return [Path(str(item)) for item in payload]


def _render_batch_subprocess(args: argparse.Namespace, frame_npz_paths: list[Path]) -> list[dict[str, str]]:
    workers = max(1, int(args.num_workers))
    outputs: list[dict[str, str]] = []
    pending = list(frame_npz_paths)
    running: list[tuple[subprocess.Popen[str], Path, Path]] = []
    log_dir = args.out_dir / "shards"
    log_dir.mkdir(parents=True, exist_ok=True)
    env_base = os.environ.copy()
    env_base.setdefault("OMP_NUM_THREADS", "1")
    env_base.setdefault("OPENBLAS_NUM_THREADS", "1")
    while pending or running:
        while pending and len(running) < workers:
            frame_npz = pending.pop(0)
            time_str = _frame_time_from_npz(frame_npz)
            log_file = log_dir / f"stage4_visual_{time_str}.log"
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--frame-npz",
                str(frame_npz),
                "--out-dir",
                str(args.out_dir),
                "--z-levels",
                str(args.z_levels),
                "--crop-mode",
                str(args.crop_mode),
                "--crop-pad",
                str(args.crop_pad),
                "--field-mode",
                str(args.field_mode),
            ]
            if args.x_slice is not None:
                cmd.extend(["--x-slice", str(args.x_slice)])
            with log_file.open("w", encoding="utf-8") as log:
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
            running.append((proc, frame_npz, log_file))
        still_running: list[tuple[subprocess.Popen[str], Path, Path]] = []
        for proc, frame_npz, log_file in running:
            rc = proc.poll()
            if rc is None:
                still_running.append((proc, frame_npz, log_file))
                continue
            if rc != 0:
                raise RuntimeError(f"Stage4 visual render failed rc={rc}; see {log_file}")
            time_str = _frame_time_from_npz(frame_npz)
            outputs.append(
                {
                    "frame_npz": str(frame_npz),
                    "png": str(args.out_dir / f"{time_str}_centralized_stage4_slices.png"),
                    "stats": str(args.out_dir / f"{time_str}_centralized_stage4_slice_stats.csv"),
                    "diagnostics": str(args.out_dir / f"{time_str}_centralized_stage4_diagnostics.png"),
                }
            )
        running = still_running
        if running:
            import time

            time.sleep(0.5)
    return sorted(outputs, key=lambda row: row["png"])


def _extent_stats(mask: np.ndarray, blind: np.ndarray, u3d: np.ndarray, v3d: np.ndarray, c3d: np.ndarray) -> dict[str, float | int]:
    total = int(mask.size)
    active = int(np.count_nonzero(mask))
    fill = int(np.count_nonzero(mask & (blind > 0)))
    speed = np.sqrt(u3d**2 + v3d**2)
    stats: dict[str, float | int] = {
        "grid_total_voxels": total,
        "effective_reconstructed_voxels": active,
        "effective_reconstructed_fraction": float(active / total) if total else 0.0,
        "low_conf_fill_voxels": fill,
        "low_conf_fill_fraction": float(fill / total) if total else 0.0,
        "mask_conf_positive_mismatch_voxels": int(np.count_nonzero((c3d > 0) != mask)),
    }
    if active == 0:
        stats.update(
            {
                "bbox_z_min": -1,
                "bbox_z_max": -1,
                "bbox_y_min": -1,
                "bbox_y_max": -1,
                "bbox_x_min": -1,
                "bbox_x_max": -1,
                "bbox_lat_min": 0.0,
                "bbox_lat_max": 0.0,
                "bbox_lon_min": 0.0,
                "bbox_lon_max": 0.0,
                "bbox_alt_min_m": 0.0,
                "bbox_alt_max_m": 0.0,
                "speed_active_mean_mps": 0.0,
                "speed_active_max_mps": 0.0,
                "confidence_active_mean": 0.0,
            }
        )
        return stats
    zz, yy, xx = np.where(mask)
    z_min, z_max = int(zz.min()), int(zz.max())
    y_min, y_max = int(yy.min()), int(yy.max())
    x_min, x_max = int(xx.min()), int(xx.max())
    _, h_dim, w_dim = mask.shape
    stats.update(
        {
            "bbox_z_min": z_min,
            "bbox_z_max": z_max,
            "bbox_y_min": y_min,
            "bbox_y_max": y_max,
            "bbox_x_min": x_min,
            "bbox_x_max": x_max,
            "bbox_lat_min": float(LAT_MAX - (y_max + 1) / h_dim * (LAT_MAX - LAT_MIN)),
            "bbox_lat_max": float(LAT_MAX - y_min / h_dim * (LAT_MAX - LAT_MIN)),
            "bbox_lon_min": float(LON_MIN + x_min / w_dim * (LON_MAX - LON_MIN)),
            "bbox_lon_max": float(LON_MIN + (x_max + 1) / w_dim * (LON_MAX - LON_MIN)),
            "bbox_alt_min_m": float(ALT_MIN + z_min * DELTA_ALT),
            "bbox_alt_max_m": float(ALT_MIN + z_max * DELTA_ALT),
            "speed_active_mean_mps": float(np.mean(speed[mask])),
            "speed_active_max_mps": float(np.max(speed[mask])),
            "confidence_active_mean": float(np.mean(c3d[mask])),
        }
    )
    return stats


def _render_horizontal_slice(ax, u3d, v3d, c3d, mask3d, blind3d, z_idx: int, title: str, point_eval: list[dict]) -> None:
    speed = np.sqrt(u3d[z_idx] ** 2 + v3d[z_idx] ** 2)
    active = mask3d[z_idx] > 0
    support = active & ~(blind3d[z_idx] > 0)
    fill = active & (blind3d[z_idx] > 0)
    speed_masked = np.ma.masked_where(~active, speed)
    cmap = plt.get_cmap("turbo").copy()
    cmap.set_bad("#f1f5f9")
    ax.set_facecolor("#f1f5f9")
    im = ax.imshow(speed_masked, cmap=cmap, origin="upper")
    ax.contour(support.astype(np.float32), levels=[0.5], colors=["#e0f2fe"], linewidths=0.55, alpha=0.9)
    ax.contour(fill.astype(np.float32), levels=[0.5], colors=["#111827"], linewidths=0.45, alpha=0.65)
    ax.add_patch(Rectangle((0, 0), 0, 0, facecolor="#f1f5f9", edgecolor="#cbd5e1", label="outside recon_mask (no claim)"))
    ax.add_line(Line2D([], [], color="#e0f2fe", linewidth=1.2, label="obs-supported contour"))
    ax.add_line(Line2D([], [], color="#111827", linewidth=1.2, label="low-conf fill contour"))
    conf_overlay = np.ma.masked_where(~active, c3d[z_idx])
    ax.imshow(conf_overlay, cmap="Greys", origin="upper", alpha=0.14)
    step = max(1, speed.shape[0] // 40)
    yy, xx = np.mgrid[0:speed.shape[0]:step, 0:speed.shape[1]:step]
    quiver_mask = active[::step, ::step]
    uu = np.where(quiver_mask, u3d[z_idx][::step, ::step], np.nan)
    vv = np.where(quiver_mask, -v3d[z_idx][::step, ::step], np.nan)
    ax.quiver(xx, yy, uu, vv, color="black", alpha=0.4, scale=200, label="u/v wind (m/s)")
    points = [row for row in point_eval if int(row.get("z", -1)) == int(z_idx)]
    if points:
        ax.scatter(
            [float(row["x"]) for row in points],
            [float(row["y"]) for row in points],
            marker="o",
            s=58,
            facecolors="none",
            edgecolors="white",
            linewidths=1.4,
            label="hold-out wind truth",
        )
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="upper right", fontsize=7)
    ax.set_title(title)
    ax.set_xlabel("x voxel")
    ax.set_ylabel("y voxel")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="speed (m/s)")


def _render_vertical_slice(ax, u3d, v3d, c3d, mask3d, blind3d, x_idx: int, title: str) -> None:
    speed = np.sqrt(u3d[:, :, x_idx] ** 2 + v3d[:, :, x_idx] ** 2)
    active = mask3d[:, :, x_idx] > 0
    support = active & ~(blind3d[:, :, x_idx] > 0)
    fill = active & (blind3d[:, :, x_idx] > 0)
    speed_masked = np.ma.masked_where(~active, speed)
    cmap = plt.get_cmap("turbo").copy()
    cmap.set_bad("#f1f5f9")
    ax.set_facecolor("#f1f5f9")
    im = ax.imshow(speed_masked, cmap=cmap, origin="lower", aspect="auto")
    ax.contour(support.astype(np.float32), levels=[0.5], colors=["#e0f2fe"], linewidths=0.55, alpha=0.9)
    ax.contour(fill.astype(np.float32), levels=[0.5], colors=["#111827"], linewidths=0.45, alpha=0.65)
    ax.add_patch(Rectangle((0, 0), 0, 0, facecolor="#f1f5f9", edgecolor="#cbd5e1", label="outside recon_mask (no claim)"))
    ax.add_line(Line2D([], [], color="#e0f2fe", linewidth=1.2, label="obs-supported contour"))
    ax.add_line(Line2D([], [], color="#111827", linewidth=1.2, label="low-conf fill contour"))
    step_z = max(1, speed.shape[0] // 16)
    step_y = max(1, speed.shape[1] // 40)
    zz, yy = np.mgrid[0:speed.shape[0]:step_z, 0:speed.shape[1]:step_y]
    quiver_mask = active[::step_z, ::step_y]
    uu = np.where(quiver_mask, u3d[:, :, x_idx][::step_z, ::step_y], np.nan)
    vv = np.where(quiver_mask, v3d[:, :, x_idx][::step_z, ::step_y], np.nan)
    ax.quiver(yy, zz, uu, vv, color="black", alpha=0.4, scale=200, label="u/v wind (m/s)")
    ax.set_title(title)
    ax.set_xlabel("y voxel")
    ax.set_ylabel("z level (500 m each)")
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="upper right", fontsize=7)
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="speed (m/s)")


def _render_confidence_slice(ax, c3d, mask3d, blind3d, z_idx: int, title: str, *, use_reliability_label: bool = False) -> None:
    active = mask3d[z_idx] > 0
    support = active & ~(blind3d[z_idx] > 0)
    fill = active & (blind3d[z_idx] > 0)
    conf = np.ma.masked_where(~active, c3d[z_idx])
    cmap = plt.get_cmap("magma").copy()
    cmap.set_bad("#f8fafc")
    ax.set_facecolor("#f8fafc")
    im = ax.imshow(conf, cmap=cmap, origin="upper", norm=PowerNorm(gamma=0.35, vmin=0.0, vmax=1.0))
    ax.contour(support.astype(np.float32), levels=[0.5], colors=["#22c55e"], linewidths=0.9, alpha=0.95)
    ax.contour(fill.astype(np.float32), levels=[0.5], colors=["#ef4444"], linewidths=0.9, alpha=0.95)
    low_conf_mask = active & (c3d[z_idx] <= 0.20)
    if np.any(low_conf_mask):
        ax.contourf(
            np.where(low_conf_mask, 1.0, np.nan),
            levels=[0.5, 1.5],
            colors=["#ffffff"],
            alpha=0.18,
        )
    ax.add_line(Line2D([], [], color="#22c55e", linewidth=1.4, label="higher-confidence official support"))
    ax.add_line(Line2D([], [], color="#ef4444", linewidth=1.4, label="low-confidence background fill"))
    ax.set_title(title)
    ax.set_xlabel("x voxel")
    ax.set_ylabel("y voxel")
    ax.legend(loc="upper right", fontsize=7)
    label = "reliability confidence (0-1)" if use_reliability_label else "display confidence (0-1)"
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label=label)


def _render_source_slice(ax, source3d, mask3d, z_idx: int, title: str) -> None:
    source = np.asarray(source3d[z_idx], dtype=np.uint8).copy()
    source[mask3d[z_idx] <= 0] = 0
    cmap = ListedColormap(["#f8fafc", "#22c55e", "#ef4444"])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], cmap.N)
    ax.set_facecolor("#f8fafc")
    im = ax.imshow(source, cmap=cmap, norm=norm, origin="upper")
    ax.add_patch(Rectangle((0, 0), 0, 0, facecolor="#22c55e", edgecolor="none", label="official recon support"))
    ax.add_patch(Rectangle((0, 0), 0, 0, facecolor="#ef4444", edgecolor="none", label="low-confidence background fill"))
    ax.add_patch(Rectangle((0, 0), 0, 0, facecolor="#f8fafc", edgecolor="#cbd5e1", label="outside recon mask"))
    ax.set_title(title)
    ax.set_xlabel("x voxel")
    ax.set_ylabel("y voxel")
    ax.legend(loc="upper right", fontsize=7)
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, ticks=[0, 1, 2])
    cbar.ax.set_yticklabels(["none", "official", "background fill"])


def _auto_x_slice(c3d: np.ndarray, point_eval: list[dict], requested: int | None) -> tuple[int, str]:
    if requested is not None:
        x = min(max(0, int(requested)), c3d.shape[2] - 1)
        if np.count_nonzero(c3d[:, :, x] > 0) > 0:
            return x, "requested_nonempty"
    if point_eval:
        candidates = sorted({int(row.get("x", -1)) for row in point_eval if int(row.get("x", -1)) >= 0})
        best_x = None
        best_score = -1
        for x in candidates:
            if 0 <= x < c3d.shape[2]:
                score = int(np.count_nonzero(c3d[:, :, x] > 0))
                if score > best_score:
                    best_x = x
                    best_score = score
        if best_x is not None and best_score > 0:
            return int(best_x), "auto_from_holdout_nonempty"
    coverage = np.count_nonzero(c3d > 0, axis=(0, 1))
    x = int(np.argmax(coverage))
    return x, "auto_max_confidence_coverage"


def _auto_z_levels(mask3d: np.ndarray, requested: str, max_levels: int = 3) -> list[int]:
    token = str(requested).strip().lower()
    if token != "auto":
        z_levels = [int(part.strip()) for part in str(requested).split(",") if part.strip()]
        z_levels = [min(max(0, z_idx), mask3d.shape[0] - 1) for z_idx in z_levels]
        return list(dict.fromkeys(z_levels))
    coverage = np.count_nonzero(mask3d > 0, axis=(1, 2))
    active = [int(z) for z in np.argsort(coverage)[::-1] if int(coverage[int(z)]) > 0]
    if not active:
        return [0]
    selected = sorted(active[: max(1, int(max_levels))])
    return selected


def _crop_to_recon_bbox(
    u3d: np.ndarray,
    v3d: np.ndarray,
    c3d: np.ndarray,
    mask3d: np.ndarray,
    blind: np.ndarray,
    cloud: np.ndarray,
    point_eval: list[dict],
    *,
    crop_mode: str,
    crop_pad: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict], dict[str, int | str]]:
    if str(crop_mode) != "bbox" or not np.any(mask3d):
        return u3d, v3d, c3d, mask3d, blind, cloud, point_eval, {
            "crop_mode": str(crop_mode),
            "crop_y0": 0,
            "crop_y1": int(mask3d.shape[1] - 1),
            "crop_x0": 0,
            "crop_x1": int(mask3d.shape[2] - 1),
        }

    _, yy, xx = np.where(mask3d)
    y0, y1 = int(yy.min()), int(yy.max())
    x0, x1 = int(xx.min()), int(xx.max())
    pad = max(0, int(crop_pad))
    y0 = max(0, y0 - pad)
    y1 = min(mask3d.shape[1] - 1, y1 + pad)
    x0 = max(0, x0 - pad)
    x1 = min(mask3d.shape[2] - 1, x1 + pad)

    cropped_points: list[dict] = []
    for row in point_eval:
        try:
            x = int(row.get("x", -1))
            y = int(row.get("y", -1))
        except Exception:
            continue
        if x0 <= x <= x1 and y0 <= y <= y1:
            updated = dict(row)
            updated["x_global"] = x
            updated["y_global"] = y
            updated["x"] = x - x0
            updated["y"] = y - y0
            cropped_points.append(updated)

    return (
        u3d[:, y0 : y1 + 1, x0 : x1 + 1],
        v3d[:, y0 : y1 + 1, x0 : x1 + 1],
        c3d[:, y0 : y1 + 1, x0 : x1 + 1],
        mask3d[:, y0 : y1 + 1, x0 : x1 + 1],
        blind[:, y0 : y1 + 1, x0 : x1 + 1],
        cloud[y0 : y1 + 1, x0 : x1 + 1],
        cropped_points,
        {
            "crop_mode": "bbox",
            "crop_y0": y0,
            "crop_y1": y1,
            "crop_x0": x0,
            "crop_x1": x1,
        },
    )


def _metrics_from_point_eval(point_eval: list[dict]) -> dict[str, float]:
    if not point_eval:
        return {"holdout_count": 0.0, "mae_vector": 0.0, "rmse_vector": 0.0, "bias_u": 0.0, "bias_v": 0.0}
    vec = np.asarray([float(row.get("vector_error", 0.0)) for row in point_eval], dtype=np.float64)
    u_err = np.asarray([float(row.get("u_error", 0.0)) for row in point_eval], dtype=np.float64)
    v_err = np.asarray([float(row.get("v_error", 0.0)) for row in point_eval], dtype=np.float64)
    return {
        "holdout_count": float(len(point_eval)),
        "mae_vector": float(np.mean(np.abs(vec))),
        "rmse_vector": float(np.sqrt(np.mean(vec**2))),
        "bias_u": float(np.mean(u_err)),
        "bias_v": float(np.mean(v_err)),
    }


def _slice_stats(
    u3d: np.ndarray,
    v3d: np.ndarray,
    c3d: np.ndarray,
    mask3d: np.ndarray,
    blind: np.ndarray,
    z_levels: list[int],
    x_idx: int,
) -> list[dict[str, float | int | str]]:
    speed = np.sqrt(u3d**2 + v3d**2)
    rows: list[dict[str, float | int | str]] = []
    for z_idx in z_levels:
        sp = speed[z_idx]
        cf = c3d[z_idx]
        mk = mask3d[z_idx] > 0
        bl = blind[z_idx]
        active = mk
        rows.append(
            {
                "slice": f"horizontal_z_{z_idx}",
                "z": int(z_idx),
                "alt_m": float(z_idx * DELTA_ALT),
                "x": "",
                "active_voxels": int(np.count_nonzero(active)),
                "support_voxels": int(np.count_nonzero(active & ~(bl > 0))),
                "low_conf_fill_voxels": int(np.count_nonzero(active & (bl > 0))),
                "blindzone_voxels": int(np.count_nonzero(active & (bl > 0))),
                "speed_min_mps": float(np.min(sp[active])) if np.any(active) else 0.0,
                "speed_mean_mps": float(np.mean(sp[active])) if np.any(active) else 0.0,
                "speed_max_mps": float(np.max(sp[active])) if np.any(active) else 0.0,
                "conf_mean": float(np.mean(cf[active])) if np.any(active) else 0.0,
                "conf_max": float(np.max(cf[active])) if np.any(active) else 0.0,
            }
        )
    sp = speed[:, :, x_idx]
    cf = c3d[:, :, x_idx]
    mk = mask3d[:, :, x_idx] > 0
    bl = blind[:, :, x_idx]
    active = mk
    rows.append(
        {
            "slice": f"vertical_x_{x_idx}",
            "z": "",
            "alt_m": "",
            "x": int(x_idx),
            "active_voxels": int(np.count_nonzero(active)),
            "support_voxels": int(np.count_nonzero(active & ~(bl > 0))),
            "low_conf_fill_voxels": int(np.count_nonzero(active & (bl > 0))),
            "blindzone_voxels": int(np.count_nonzero(active & (bl > 0))),
            "speed_min_mps": float(np.min(sp[active])) if np.any(active) else 0.0,
            "speed_mean_mps": float(np.mean(sp[active])) if np.any(active) else 0.0,
            "speed_max_mps": float(np.max(sp[active])) if np.any(active) else 0.0,
            "conf_mean": float(np.mean(cf[active])) if np.any(active) else 0.0,
            "conf_max": float(np.max(cf[active])) if np.any(active) else 0.0,
        }
    )
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_diagnostic_chart(
    out_dir: Path,
    time_str: str,
    stats_rows: list[dict],
    point_eval: list[dict],
    metrics: dict[str, float],
    extent: dict[str, float | int],
) -> Path:
    fig, axes = plt.subplots(2, 3, figsize=(17.0, 8.0), constrained_layout=True)
    labels = [str(row["slice"]).replace("horizontal_", "h_").replace("vertical_", "v_") for row in stats_rows]
    active = [int(row["active_voxels"]) for row in stats_rows]
    support = [int(row["support_voxels"]) for row in stats_rows]
    fill = [int(row["low_conf_fill_voxels"]) for row in stats_rows]
    x = np.arange(len(labels))
    axes[0, 0].bar(x - 0.24, active, width=0.24, label="active voxels (count)", color="#3b82f6")
    axes[0, 0].bar(x, support, width=0.24, label="observation-supported voxels (count)", color="#14b8a6")
    axes[0, 0].bar(x + 0.24, fill, width=0.24, label="low-conf fill voxels (count)", color="#f59e0b")
    axes[0, 0].set_title("Slice coverage (voxel count)")
    axes[0, 0].set_xticks(x)
    axes[0, 0].set_xticklabels(labels, rotation=25, ha="right")
    axes[0, 0].legend(fontsize=8)
    axes[0, 0].grid(axis="y", alpha=0.2)

    speed_mean = [float(row["speed_mean_mps"]) for row in stats_rows]
    speed_max = [float(row["speed_max_mps"]) for row in stats_rows]
    axes[0, 1].plot(labels, speed_mean, marker="o", label="mean speed (m/s)", color="#14b8a6")
    axes[0, 1].plot(labels, speed_max, marker="s", label="max speed (m/s)", color="#ef4444")
    axes[0, 1].set_title("Speed statistics (m/s)")
    axes[0, 1].tick_params(axis="x", rotation=25)
    axes[0, 1].set_ylabel("m/s")
    axes[0, 1].legend(fontsize=8)
    axes[0, 1].grid(alpha=0.2)

    conf_mean = [float(row["conf_mean"]) for row in stats_rows]
    conf_max = [float(row["conf_max"]) for row in stats_rows]
    axes[1, 0].bar(x - 0.18, conf_mean, width=0.36, label="mean confidence (0-1)", color="#7c3aed", alpha=0.80)
    axes[1, 0].bar(x + 0.18, conf_max, width=0.36, label="max confidence (0-1)", color="#f59e0b", alpha=0.80)
    axes[1, 0].set_title("Confidence statistics (0-1)")
    axes[1, 0].set_xticks(x)
    axes[1, 0].set_xticklabels(labels, rotation=25, ha="right")
    axes[1, 0].set_ylim(0.0, 1.05)
    axes[1, 0].legend(fontsize=8)
    axes[1, 0].grid(axis="y", alpha=0.2)

    if point_eval:
        idx = np.arange(len(point_eval))
        vec = [float(row.get("vector_error", 0.0)) for row in point_eval]
        conf = [float(row.get("recon_confidence", 0.0)) for row in point_eval]
        axes[1, 1].bar(idx, vec, color="#8b5cf6", alpha=0.78, label="vector error (m/s)")
        axes[1, 1].plot(idx, conf, color="#111827", marker="o", linewidth=1.2, label="recon confidence (0-1)")
        axes[1, 1].set_title("Hold-out point errors")
        axes[1, 1].set_xlabel("hold-out index")
        axes[1, 1].set_ylabel("error (m/s) / confidence (0-1)")
        axes[1, 1].legend(fontsize=8)
        axes[1, 1].grid(axis="y", alpha=0.2)
    else:
        axes[1, 1].axis("off")

    axes[1, 2].axis("off")
    lines = [
        f"hold-out count: {int(metrics['holdout_count'])}",
        f"RMSE vector: {metrics['rmse_vector']:.3f} m/s",
        f"MAE vector: {metrics['mae_vector']:.3f} m/s",
        f"bias u/v: {metrics['bias_u']:.3f}, {metrics['bias_v']:.3f}",
        f"effective voxels: {int(extent['effective_reconstructed_voxels'])} ({float(extent['effective_reconstructed_fraction']):.3%})",
        f"low-conf fill: {int(extent['low_conf_fill_voxels'])} ({float(extent['low_conf_fill_fraction']):.3%})",
        f"bbox lat/lon: {float(extent['bbox_lat_min']):.2f}-{float(extent['bbox_lat_max']):.2f}, {float(extent['bbox_lon_min']):.2f}-{float(extent['bbox_lon_max']):.2f}",
        f"bbox alt: {float(extent['bbox_alt_min_m']):.0f}-{float(extent['bbox_alt_max_m']):.0f} m",
        "Stage4 method:",
        "non-holdout current wind + context wind",
        "Gaussian target-voxel localization",
        "PINN-proxy + diffusion-style low-conf fill",
        "Block footprint = engineering localization/fill, not physical proof.",
    ]
    axes[1, 2].text(0.02, 0.92, "\n".join(lines), va="top", fontsize=11)
    fig.suptitle(f"Stage4 diagnostics - {time_str}", fontsize=13)
    out = out_dir / f"{time_str}_centralized_stage4_diagnostics.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Slice visualization for centralized_v1 Stage4 outputs.")
    parser.add_argument("--frame-npz", type=Path)
    parser.add_argument("--frame-npz-list-file", type=Path)
    parser.add_argument("--stage4-dir", type=Path)
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--z-levels", default="3,8")
    parser.add_argument("--x-slice", type=int)
    parser.add_argument("--crop-mode", choices=["full", "bbox"], default="full")
    parser.add_argument("--crop-pad", type=int, default=24)
    parser.add_argument("--field-mode", choices=["recon", "display_filled"], default="recon")
    parser.add_argument("--num-workers", type=int, default=1)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    batch_paths = _read_frame_npz_list(args.frame_npz_list_file)
    batch_paths.extend(_discover_frame_npz(args.stage4_dir, args.frame_times))
    if args.frame_npz:
        batch_paths.append(args.frame_npz)
    batch_paths = list(dict.fromkeys(batch_paths))
    if not batch_paths:
        raise ValueError("Provide --frame-npz, --frame-npz-list-file, or --stage4-dir")
    if len(batch_paths) > 1 or int(args.num_workers) > 1:
        outputs = _render_batch_subprocess(args, batch_paths)
        summary_path = args.out_dir / "stage4_visual_summary.json"
        summary_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(summary_path)
        return
    args.frame_npz = batch_paths[0]
    with np.load(args.frame_npz, allow_pickle=False) as z:
        field_mode = str(args.field_mode)
        reliability_c3d: np.ndarray | None = None
        if field_mode == "display_filled":
            missing = [key for key in [C4_DISPLAY_U, C4_DISPLAY_V, C4_DISPLAY_CONF, C4_DISPLAY_MASK] if key not in z.files]
            if missing:
                raise KeyError(f"display_filled mode requested but NPZ is missing {missing}: {args.frame_npz}")
            u3d = np.asarray(z[C4_DISPLAY_U], dtype=np.float32)
            v3d = np.asarray(z[C4_DISPLAY_V], dtype=np.float32)
            c3d = np.asarray(z[C4_DISPLAY_CONF], dtype=np.float32)
            reliability_c3d = np.asarray(z[C4_RELIABILITY_CONF], dtype=np.float32) if C4_RELIABILITY_CONF in z.files else None
            mask3d = np.asarray(z[C4_DISPLAY_MASK], dtype=np.float32) > 0
            display_source = np.asarray(z[C4_DISPLAY_SOURCE], dtype=np.uint8) if C4_DISPLAY_SOURCE in z.files else np.zeros_like(c3d, dtype=np.uint8)
            official_u3d = np.asarray(z[C4_RECON_U], dtype=np.float32)
            official_v3d = np.asarray(z[C4_RECON_V], dtype=np.float32)
            official_c3d = np.asarray(z[C4_RECON_CONF], dtype=np.float32)
            official_mask3d = np.asarray(z[C4_RECON_MASK], dtype=np.float32) > 0 if C4_RECON_MASK in z.files else official_c3d > 0
            official_blind = (
                np.asarray(z[C4_BLINDZONE_MASK], dtype=np.float32) if C4_BLINDZONE_MASK in z.files else np.zeros_like(official_c3d)
            )
            if C4_DISPLAY_FILL_DIAGNOSTICS_JSON in z.files:
                display_fill_diagnostics = json.loads(str(z[C4_DISPLAY_FILL_DIAGNOSTICS_JSON]))
            else:
                display_fill_diagnostics = {}
        else:
            u3d = np.asarray(z[C4_RECON_U], dtype=np.float32)
            v3d = np.asarray(z[C4_RECON_V], dtype=np.float32)
            c3d = np.asarray(z[C4_RECON_CONF], dtype=np.float32)
            mask3d = np.asarray(z[C4_RECON_MASK], dtype=np.float32) > 0 if C4_RECON_MASK in z.files else c3d > 0
            display_source = np.zeros_like(c3d, dtype=np.uint8)
            display_fill_diagnostics = {}
            official_u3d = u3d
            official_v3d = v3d
            official_c3d = c3d
            official_mask3d = mask3d
            official_blind = np.asarray(z[C4_BLINDZONE_MASK], dtype=np.float32) if C4_BLINDZONE_MASK in z.files else np.zeros_like(c3d)
        c3d = np.where(mask3d, c3d, 0.0).astype(np.float32)
        blind = np.asarray(z[C4_BLINDZONE_MASK], dtype=np.float32) if C4_BLINDZONE_MASK in z.files else np.zeros_like(c3d)
        if field_mode == "display_filled":
            blind = np.where(display_source == 2, 1.0, 0.0).astype(np.float32)
        else:
            blind = np.where(mask3d, blind, 0.0).astype(np.float32)
        cloud = np.asarray(z[C4_CLOUD_2D], dtype=np.float32)
        if C4_POINT_EVAL_JSON in z.files:
            point_eval = json.loads(str(z[C4_POINT_EVAL_JSON]))
        else:
            point_eval = []
        time_str = str(z["time_str"]) if "time_str" in z.files else args.frame_npz.stem

    original_extent = _extent_stats(official_mask3d, official_blind, official_u3d, official_v3d, official_c3d)
    u3d, v3d, c3d, mask3d, blind, cloud, point_eval, crop_meta = _crop_to_recon_bbox(
        u3d,
        v3d,
        c3d,
        mask3d,
        blind,
        cloud,
        point_eval,
        crop_mode=str(args.crop_mode),
        crop_pad=int(args.crop_pad),
    )
    if reliability_c3d is not None:
        if crop_meta.get("crop_mode") == "bbox":
            reliability_c3d = reliability_c3d[
                :,
                int(crop_meta["crop_y0"]) : int(crop_meta["crop_y1"]) + 1,
                int(crop_meta["crop_x0"]) : int(crop_meta["crop_x1"]) + 1,
            ]
        reliability_c3d = np.where(mask3d, reliability_c3d, 0.0).astype(np.float32)
    if str(args.field_mode) == "display_filled":
        if crop_meta.get("crop_mode") == "bbox":
            display_source = display_source[
                :,
                int(crop_meta["crop_y0"]) : int(crop_meta["crop_y1"]) + 1,
                int(crop_meta["crop_x0"]) : int(crop_meta["crop_x1"]) + 1,
            ]
        display_source = np.where(mask3d, display_source, 0).astype(np.uint8)
    z_levels = _auto_z_levels(mask3d, str(args.z_levels), max_levels=3)
    x_idx, x_source = _auto_x_slice(c3d, point_eval, args.x_slice)
    extent = _extent_stats(mask3d, blind, u3d, v3d, c3d)
    cols = max(3, len(z_levels) + 1)
    if str(args.field_mode) == "display_filled":
        cols = max(cols, len(z_levels) + 4)
    fig, axes = plt.subplots(2, cols, figsize=(5.2 * cols, 9.0), constrained_layout=True)
    if str(args.field_mode) == "display_filled":
        fig.patch.set_facecolor("#e5e7eb")
    for i, z_idx in enumerate(z_levels):
        alt_m = z_idx * DELTA_ALT
        _render_horizontal_slice(
            axes[0, i],
            u3d,
            v3d,
            c3d,
            mask3d,
            blind,
            z_idx,
            f"Horizontal slice z={z_idx} (~{alt_m:.0f} m)",
            point_eval,
        )
    radar_im = axes[0, -1].imshow(cloud, cmap="gray")
    if int(extent["effective_reconstructed_voxels"]) > 0:
        x0, x1 = int(extent["bbox_x_min"]), int(extent["bbox_x_max"])
        y0, y1 = int(extent["bbox_y_min"]), int(extent["bbox_y_max"])
        axes[0, -1].plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], color="#f97316", linewidth=1.6, label="recon bbox")
        axes[0, -1].legend(loc="upper right", fontsize=7)
    crop_note = ""
    if crop_meta.get("crop_mode") == "bbox":
        crop_note = f"\ncropped global y={crop_meta['crop_y0']}..{crop_meta['crop_y1']}, x={crop_meta['crop_x0']}..{crop_meta['crop_x1']}"
    axes[0, -1].set_title(f"Cloud / radar 2D intensity\norange box = recon bbox{crop_note}")
    axes[0, -1].set_xlabel("x voxel")
    axes[0, -1].set_ylabel("y voxel")
    plt.colorbar(radar_im, ax=axes[0, -1], fraction=0.046, pad=0.04, label="radar intensity (gray level)")

    if str(args.field_mode) == "display_filled" and len(z_levels) > 0:
        rel_col = len(z_levels)
        conf_col = len(z_levels) + 1
        source_col = len(z_levels) + 2
        z_focus = int(z_levels[min(1, len(z_levels) - 1)])
        _render_confidence_slice(
            axes[0, rel_col],
            reliability_c3d if reliability_c3d is not None else c3d,
            mask3d,
            blind,
            z_focus,
            f"Reliability slice z={z_focus}",
            use_reliability_label=True,
        )
        _render_confidence_slice(
            axes[0, conf_col],
            c3d,
            mask3d,
            blind,
            z_focus,
            f"Display confidence slice z={z_focus}",
            use_reliability_label=False,
        )
        _render_source_slice(
            axes[0, source_col],
            display_source,
            mask3d,
            z_focus,
            f"Display source class z={z_focus}",
        )

    _render_vertical_slice(axes[1, 0], u3d, v3d, c3d, mask3d, blind, int(x_idx), f"Vertical slice x={int(x_idx)} ({x_source})")
    speed = np.sqrt(u3d**2 + v3d**2)
    alt_profile = []
    for zi in range(u3d.shape[0]):
        active = mask3d[zi]
        alt_profile.append(float(np.mean(speed[zi][active])) if np.any(active) else np.nan)
    axes[1, 1].plot(alt_profile, np.arange(u3d.shape[0]) * DELTA_ALT / 1000.0)
    axes[1, 1].set_title("Mean active speed by altitude")
    axes[1, 1].set_xlabel("mean active speed (m/s)")
    axes[1, 1].set_ylabel("altitude (km)")
    axes[1, 1].grid(alpha=0.25)
    for j in range(2, axes.shape[1]):
        axes[1, j].set_facecolor("#e5e7eb")
        axes[1, j].axis("off")
    if str(args.field_mode) == "display_filled" and axes.shape[1] > 2:
        axes[1, 2].text(
            0.02,
            0.92,
            "display-filled layer\nweak background outside official recon\nconfidence/source views added:\nred contour = low-confidence background fill\ngreen contour = higher-confidence official support\nsource map: green=official, red=background fill",
            va="top",
            fontsize=11,
        )

    metrics = _metrics_from_point_eval(point_eval)
    field_note = "Official recon_mask/no wind claim outside mask"
    if str(args.field_mode) == "display_filled":
        bg_voxels = int(display_fill_diagnostics.get("display_background_voxels", int(np.count_nonzero(blind > 0))))
        field_note = (
            "DISPLAY-FILLED: full-color low-confidence weak background outside official recon; "
            f"background voxels={bg_voxels}; not official accuracy"
        )
    fig.suptitle(
        f"Centralized v1 Stage4 slices - {time_str}\n"
        f"Domain lat {LAT_MIN:.1f}-{LAT_MAX:.1f}, lon {LON_MIN:.1f}-{LON_MAX:.1f}, altitude step {DELTA_ALT:.0f} m | "
        f"hold-out={int(metrics['holdout_count'])}, RMSE={metrics['rmse_vector']:.2f} m/s, MAE={metrics['mae_vector']:.2f} m/s\n"
        f"Effective recon={int(original_extent['effective_reconstructed_voxels'])} voxels ({float(original_extent['effective_reconstructed_fraction']):.3%} of full grid); "
        f"low-conf/display fill={int(extent['low_conf_fill_voxels'])}; {field_note}",
        fontsize=12,
    )
    out = args.out_dir / f"{time_str}_centralized_stage4_slices.png"
    fig.savefig(out, dpi=170)
    plt.close(fig)
    stats_rows = _slice_stats(u3d, v3d, c3d, mask3d, blind, z_levels, int(x_idx))
    stats_rows.append({"slice": "domain_extent", "z": "", "alt_m": "", "x": "", **extent})
    _write_csv(args.out_dir / f"{time_str}_centralized_stage4_slice_stats.csv", stats_rows)
    _write_diagnostic_chart(args.out_dir, time_str, [row for row in stats_rows if row.get("slice") != "domain_extent"], point_eval, metrics, extent)
    print(out)


if __name__ == "__main__":
    main()
