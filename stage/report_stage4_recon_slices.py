"""Render representative Stage-4 reconstruction slices as PNG diagnostics.

The script is intentionally read-only. It prefers the sparse reconstruction
arrays saved in Stage-4 `sparse_lossless` NPZ files and avoids inflating the
large dense 3D volumes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


DEFAULT_STAGE4_DIR = Path("/data/LFT-W02_data/pengxu/stage4_output_v2")
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative")


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
            target = float(np.quantile(coverages, q))
            _register_selection(
                selected,
                _nearest_by_metric(triggered, "recon_coverage_ratio", target),
                f"coverage_q{int(q * 100)}",
            )

    high_domain = [
        r
        for r in triggered
        if _int(r, "recon_domain_voxels") >= 500 and _num(r, "recon_coverage_ratio") > 0.0
    ]
    _register_selection(
        selected,
        _max_by_metric(high_domain, "recon_coverage_ratio"),
        "max_coverage_domain_ge_500",
    )

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
        _register_selection(
            selected,
            nontriggered_sorted[len(nontriggered_sorted) // 2],
            "nontriggered_mid_time",
        )

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
    z_dim, h_dim, w_dim = shape
    del z_dim
    idx64 = np.asarray(idx, dtype=np.int64)
    z = idx64 // (h_dim * w_dim)
    rem = idx64 % (h_dim * w_dim)
    y = rem // w_dim
    x = rem % w_dim
    return z.astype(np.int32, copy=False), y.astype(np.int32, copy=False), x.astype(np.int32, copy=False)


def _load_sparse_recon(npz_path: Path) -> dict[str, Any]:
    with np.load(npz_path, allow_pickle=False) as npz:
        files = set(npz.files)
        required = {"grid_shape", "recon_idx", "recon_u_val", "recon_v_val", "recon_conf_val", "recon_mask_val"}
        missing = sorted(required - files)
        if missing:
            raise KeyError(f"{npz_path} is missing sparse reconstruction keys: {', '.join(missing)}")

        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int64).tolist())
        if len(shape) != 3:
            raise ValueError(f"Unexpected grid_shape in {npz_path}: {shape}")
        z_dim, h_dim, w_dim = shape
        idx = np.asarray(npz["recon_idx"], dtype=np.int64)
        u_val = np.asarray(npz["recon_u_val"], dtype=np.float32)
        v_val = np.asarray(npz["recon_v_val"], dtype=np.float32)
        conf_val = np.asarray(npz["recon_conf_val"], dtype=np.float32)
        mask_val = np.asarray(npz["recon_mask_val"], dtype=np.float32)

    if not (idx.size == u_val.size == v_val.size == conf_val.size == mask_val.size):
        raise ValueError(f"Sparse reconstruction arrays have inconsistent sizes in {npz_path}")

    if idx.size > 0:
        z, y, x = _linear_to_zyx(idx, shape)
        keep = (mask_val > 0) & np.isfinite(conf_val)
        z = z[keep]
        y = y[keep]
        x = x[keep]
        u_val = u_val[keep]
        v_val = v_val[keep]
        conf_val = conf_val[keep]
    else:
        z = np.asarray([], dtype=np.int32)
        y = np.asarray([], dtype=np.int32)
        x = np.asarray([], dtype=np.int32)
        u_val = np.asarray([], dtype=np.float32)
        v_val = np.asarray([], dtype=np.float32)
        conf_val = np.asarray([], dtype=np.float32)

    speed = np.sqrt(u_val ** 2 + v_val ** 2).astype(np.float32, copy=False)
    return {
        "shape": shape,
        "sparse_count": int(idx.size),
        "x": x,
        "y": y,
        "z": z,
        "u": u_val,
        "v": v_val,
        "conf": conf_val,
        "speed": speed,
    }


def _build_sparse_projections(sparse: dict[str, Any]) -> dict[str, Any]:
    z_dim, h_dim, w_dim = sparse["shape"]
    xy_mask = np.zeros((h_dim, w_dim), dtype=np.float32)
    xy_conf = np.zeros((h_dim, w_dim), dtype=np.float32)
    xy_speed = np.zeros((h_dim, w_dim), dtype=np.float32)
    xz_conf = np.zeros((z_dim, w_dim), dtype=np.float32)
    yz_conf = np.zeros((z_dim, h_dim), dtype=np.float32)

    if sparse["z"].size > 0:
        z = sparse["z"]
        y = sparse["y"]
        x = sparse["x"]
        conf = sparse["conf"]
        speed = sparse["speed"]
        np.maximum.at(xy_mask, (y, x), 1.0)
        np.maximum.at(xy_conf, (y, x), conf)
        np.maximum.at(xy_speed, (y, x), speed)
        np.maximum.at(xz_conf, (z, x), conf)
        np.maximum.at(yz_conf, (z, y), conf)

    return {
        "shape": sparse["shape"],
        "sparse_count": sparse["sparse_count"],
        "xy_mask": xy_mask,
        "xy_conf": xy_conf,
        "xy_speed": xy_speed,
        "xz_conf": xz_conf,
        "yz_conf": yz_conf,
    }


def _max_pool_2d(arr: np.ndarray, max_side: int) -> np.ndarray:
    if max_side <= 0 or max(arr.shape) <= max_side:
        return arr
    fy = max(1, int(math.ceil(arr.shape[0] / max_side)))
    fx = max(1, int(math.ceil(arr.shape[1] / max_side)))
    pad_y = (-arr.shape[0]) % fy
    pad_x = (-arr.shape[1]) % fx
    if pad_y or pad_x:
        arr = np.pad(arr, ((0, pad_y), (0, pad_x)), mode="constant", constant_values=0.0)
    return arr.reshape(arr.shape[0] // fy, fy, arr.shape[1] // fx, fx).max(axis=(1, 3))


def _format_float(value: Any, ndigits: int = 6) -> str:
    try:
        return f"{float(value):.{ndigits}f}"
    except (TypeError, ValueError):
        return "0.000000"


def _render_frame_png(
    row: dict[str, Any],
    projections: dict[str, Any],
    out_path: Path,
    *,
    max_side: int,
) -> None:
    panels = [
        ("XY recon_mask max", _max_pool_2d(projections["xy_mask"], max_side), "gray"),
        ("XY recon_conf max", _max_pool_2d(projections["xy_conf"], max_side), "viridis"),
        ("XY wind speed max", _max_pool_2d(projections["xy_speed"], max_side), "magma"),
        ("XZ recon_conf max", _max_pool_2d(projections["xz_conf"], max_side), "viridis"),
        ("YZ recon_conf max", _max_pool_2d(projections["yz_conf"], max_side), "viridis"),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(16, 9), constrained_layout=True)
    axes_flat = axes.reshape(-1)
    for ax, (title, arr, cmap) in zip(axes_flat[:5], panels):
        vmax = float(np.max(arr)) if arr.size else 0.0
        image = ax.imshow(arr, origin="lower", cmap=cmap, interpolation="nearest", vmin=0.0, vmax=vmax if vmax > 0 else 1.0)
        ax.set_title(title, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.02)

    ax_text = axes_flat[5]
    ax_text.axis("off")
    reasons = ", ".join(row.get("selection_reasons", []))
    text_lines = [
        f"time: {row.get('time_str', '')}",
        f"file: {row.get('filename', '')}",
        f"reasons: {reasons}",
        f"triggered: {_int(row, 'recon_triggered')}",
        f"coverage: {_format_float(row.get('recon_coverage_ratio'))}",
        f"conf_mean: {_format_float(row.get('recon_conf_mean'))}",
        f"conf_spread: {_format_float(row.get('recon_conf_spread_p10_p90'))}",
        f"filled/domain: {_int(row, 'recon_filled_voxels')}/{_int(row, 'recon_domain_voxels')}",
        f"support_fill: {_int(row, 'support_fill_voxels')}",
        f"temporal_fill: {_int(row, 'temporal_fill_voxels')}",
        f"support_expand: {_int(row, 'support_expand_voxels')}",
        f"anchor_restore: {_int(row, 'anchor_restore_voxels')}",
        f"anchor_force: {_int(row, 'anchor_force_voxels')}",
        f"hazard_alert: {_int(row, 'hazard_alert_voxels')}",
        f"sparse voxels: {projections['sparse_count']}",
        f"grid_shape: {projections['shape']}",
    ]
    ax_text.text(0.02, 0.98, "\n".join(text_lines), va="top", ha="left", family="monospace", fontsize=10)
    fig.suptitle(f"Stage4 Reconstruction Diagnostics - {_frame_id(row)}", fontsize=13)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _sample_vector_indices(sparse: dict[str, Any], max_vectors: int, min_conf: float) -> np.ndarray:
    conf = np.asarray(sparse["conf"], dtype=np.float32)
    if conf.size == 0:
        return np.asarray([], dtype=np.int64)
    keep = np.where(conf >= float(min_conf))[0]
    if keep.size == 0:
        return keep
    if keep.size <= max_vectors:
        return keep
    order = keep[np.argsort(conf[keep])[::-1]]
    return np.sort(order[:max_vectors])


def _render_frame_3d_png(
    row: dict[str, Any],
    sparse: dict[str, Any],
    out_path: Path,
    *,
    max_vectors: int,
    z_exaggeration: float,
    min_conf: float,
) -> bool:
    sample_idx = _sample_vector_indices(sparse, max_vectors=max_vectors, min_conf=min_conf)
    if sample_idx.size == 0:
        return False

    x = np.asarray(sparse["x"], dtype=np.float32)[sample_idx]
    y = np.asarray(sparse["y"], dtype=np.float32)[sample_idx]
    z = np.asarray(sparse["z"], dtype=np.float32)[sample_idx] * float(z_exaggeration)
    u = np.asarray(sparse["u"], dtype=np.float32)[sample_idx]
    v = np.asarray(sparse["v"], dtype=np.float32)[sample_idx]
    conf = np.asarray(sparse["conf"], dtype=np.float32)[sample_idx]
    speed = np.asarray(sparse["speed"], dtype=np.float32)[sample_idx]

    fig = plt.figure(figsize=(13, 10), constrained_layout=True)
    ax = fig.add_subplot(111, projection="3d")
    scatter = ax.scatter(x, y, z, c=conf, s=18 + 34 * np.clip(conf, 0.0, 1.0), cmap="viridis", alpha=0.82)
    speed_scale = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    arrow_len = max(10.0, min(80.0, 35.0 / max(speed_scale, 1e-6)))
    ax.quiver(x, y, z, u, v, np.zeros_like(u), length=arrow_len, normalize=True, color="black", linewidth=0.55, alpha=0.62)
    ax.set_title(f"Stage4 3D Wind Field - {_frame_id(row)}", fontsize=13)
    ax.set_xlabel("x voxel")
    ax.set_ylabel("y voxel")
    ax.set_zlabel(f"z voxel x{z_exaggeration:g}")
    ax.view_init(elev=26, azim=-58)
    ax.grid(True, alpha=0.25)
    fig.colorbar(scatter, ax=ax, fraction=0.035, pad=0.02, label="recon confidence")

    reasons = ", ".join(row.get("selection_reasons", []))
    info = (
        f"time={row.get('time_str', '')}\n"
        f"reasons={reasons}\n"
        f"vectors={sample_idx.size}/{sparse['conf'].size}\n"
        f"coverage={_format_float(row.get('recon_coverage_ratio'))}  "
        f"conf_mean={_format_float(row.get('recon_conf_mean'))}\n"
        f"filled/domain={_int(row, 'recon_filled_voxels')}/{_int(row, 'recon_domain_voxels')}  "
        f"hazard={_int(row, 'hazard_alert_voxels')}"
    )
    ax.text2D(0.02, 0.98, info, transform=ax.transAxes, va="top", ha="left", family="monospace", fontsize=9)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return True


def _selected_record(
    row: dict[str, Any],
    png_path: Path | None,
    png_3d_path: Path | None,
    skipped_3d_reason: str,
) -> dict[str, Any]:
    keys = [
        "filename",
        "source_index",
        "time_str",
        "timestamp_utc",
        "recon_triggered",
        "recon_trigger_reason",
        "recon_filled_voxels",
        "recon_coverage_ratio",
        "recon_conf_mean",
        "recon_conf_spread_p10_p90",
        "recon_domain_voxels",
        "support_fill_voxels",
        "temporal_fill_voxels",
        "support_expand_voxels",
        "anchor_restore_voxels",
        "anchor_force_voxels",
        "hazard_alert_voxels",
    ]
    record = {key: row.get(key) for key in keys if key in row}
    record["selection_reasons"] = list(row.get("selection_reasons", []))
    record["png_path"] = str(png_path) if png_path is not None else ""
    record["png_3d_path"] = str(png_3d_path) if png_3d_path is not None else ""
    record["skipped_3d_reason"] = skipped_3d_reason
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Render representative Stage-4 reconstruction PNG diagnostics.")
    parser.add_argument("--stage4-dir", type=Path, default=DEFAULT_STAGE4_DIR)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--selection", choices=("representative", "frames"), default="representative")
    parser.add_argument("--frame-times", default="", help="Comma-separated time_str values, required for --selection=frames.")
    parser.add_argument("--viz-mode", choices=("slices", "3d", "both"), default="both")
    parser.add_argument("--max-side", type=int, default=900, help="Maximum rendered side length after max pooling.")
    parser.add_argument("--max-vectors", type=int, default=250, help="Maximum vectors in each 3D quiver plot.")
    parser.add_argument("--z-exaggeration", type=float, default=40.0, help="Visual z-axis scale factor for 3D plots.")
    parser.add_argument("--min-conf", type=float, default=0.0, help="Minimum confidence for 3D vectors.")
    args = parser.parse_args()

    stage4_dir = args.stage4_dir
    summary_path = args.summary or (stage4_dir / "stage4_summary.json")
    summary = _load_json(summary_path)
    if not isinstance(summary, list):
        raise TypeError(f"Expected Stage-4 summary list at {summary_path}")

    if args.selection == "representative":
        selected_rows = _select_representative_rows(summary)
    else:
        selected_rows = _select_frame_rows(summary, args.frame_times)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    selected_records: list[dict[str, Any]] = []
    for row in selected_rows:
        filename = str(row.get("filename") or f"frame_{row.get('time_str')}.npz")
        npz_path = stage4_dir / filename
        if not npz_path.exists():
            raise FileNotFoundError(f"Missing Stage-4 frame NPZ: {npz_path}")
        sparse = _load_sparse_recon(npz_path)
        stem = f"{_int(row, 'source_index'):05d}_{_frame_id(row)}"
        png_path: Path | None = None
        png_3d_path: Path | None = None
        skipped_3d_reason = ""

        if args.viz_mode in ("slices", "both"):
            projections = _build_sparse_projections(sparse)
            png_path = args.out_dir / f"{stem}.png"
            _render_frame_png(row, projections, png_path, max_side=args.max_side)
            print(f"[stage4-viz] wrote {png_path}")

        if args.viz_mode in ("3d", "both"):
            if _int(row, "recon_filled_voxels") <= 0 or sparse["conf"].size == 0:
                skipped_3d_reason = "empty_reconstruction"
            else:
                candidate_3d_path = args.out_dir / f"{stem}_3d.png"
                if _render_frame_3d_png(
                    row,
                    sparse,
                    candidate_3d_path,
                    max_vectors=args.max_vectors,
                    z_exaggeration=args.z_exaggeration,
                    min_conf=args.min_conf,
                ):
                    png_3d_path = candidate_3d_path
                    print(f"[stage4-viz] wrote {png_3d_path}")
                else:
                    skipped_3d_reason = "no_vectors_after_filter"

        selected_records.append(_selected_record(row, png_path, png_3d_path, skipped_3d_reason))

    selected_path = args.out_dir / "selected_frames.json"
    with selected_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "stage4_dir": str(stage4_dir),
                "summary": str(summary_path),
                "selection": args.selection,
                "viz_mode": args.viz_mode,
                "frame_count": len(selected_records),
                "frames": selected_records,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[stage4-viz] wrote {selected_path}")


if __name__ == "__main__":
    main()
