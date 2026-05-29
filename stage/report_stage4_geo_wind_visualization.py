"""Render Stage-4 sparse wind reconstructions in geographic coordinates.

This diagnostic is intentionally read-only. It uses Stage-4 sparse_lossless
fields and the fixed radar mosaic bounds used by Stage-2 voxelization:

    lat: 12.2 .. 54.2
    lon: 73.0 .. 135.0
    alt: z * 500 m

The plots are meant to show "sparse local 3D reconstruction on a national
radar grid", not a dense nationwide wind analysis.
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
from matplotlib.patches import Rectangle
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


DEFAULT_STAGE4_DIR = Path("/data/LFT-W02_data/pengxu/stage4_output_v2")
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative")

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


def _xy_to_lonlat(x: np.ndarray, y: np.ndarray, h_dim: int, w_dim: int) -> tuple[np.ndarray, np.ndarray]:
    lon = LON_MIN + (np.asarray(x, dtype=np.float64) + 0.5) * (LON_MAX - LON_MIN) / max(1, w_dim)
    lat = LAT_MAX - (np.asarray(y, dtype=np.float64) + 0.5) * (LAT_MAX - LAT_MIN) / max(1, h_dim)
    return lon.astype(np.float32, copy=False), lat.astype(np.float32, copy=False)


def _lonlat_to_xy(lon: float, lat: float, h_dim: int, w_dim: int) -> tuple[float, float]:
    x = (float(lon) - LON_MIN) * max(1, w_dim) / (LON_MAX - LON_MIN)
    y = (LAT_MAX - float(lat)) * max(1, h_dim) / (LAT_MAX - LAT_MIN)
    return x, y


def _load_sparse_recon_and_radar(npz_path: Path) -> dict[str, Any]:
    with np.load(npz_path, allow_pickle=False) as npz:
        required = {"grid_shape", "radar_2d", "recon_idx", "recon_u_val", "recon_v_val", "recon_conf_val", "recon_mask_val"}
        missing = sorted(required - set(npz.files))
        if missing:
            raise KeyError(f"{npz_path} is missing required keys: {', '.join(missing)}")

        shape = tuple(int(v) for v in np.asarray(npz["grid_shape"], dtype=np.int64).tolist())
        if len(shape) != 3:
            raise ValueError(f"Unexpected grid_shape in {npz_path}: {shape}")
        radar = np.asarray(npz["radar_2d"], dtype=np.float32)
        idx = np.asarray(npz["recon_idx"], dtype=np.int64)
        u_val = np.asarray(npz["recon_u_val"], dtype=np.float32)
        v_val = np.asarray(npz["recon_v_val"], dtype=np.float32)
        conf_val = np.asarray(npz["recon_conf_val"], dtype=np.float32)
        mask_val = np.asarray(npz["recon_mask_val"], dtype=np.float32)

    if not (idx.size == u_val.size == v_val.size == conf_val.size == mask_val.size):
        raise ValueError(f"Sparse reconstruction arrays have inconsistent sizes in {npz_path}")

    if idx.size > 0:
        z, y, x = _linear_to_zyx(idx, shape)
        keep = (mask_val > 0) & np.isfinite(conf_val) & np.isfinite(u_val) & np.isfinite(v_val)
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

    _, h_dim, w_dim = shape
    lon, lat = _xy_to_lonlat(x, y, h_dim, w_dim)
    alt_km = (z.astype(np.float32, copy=False) * (ALT_STEP_M / 1000.0)).astype(np.float32, copy=False)
    speed = np.sqrt(u_val ** 2 + v_val ** 2).astype(np.float32, copy=False)
    return {
        "shape": shape,
        "radar": radar,
        "x": x,
        "y": y,
        "z": z,
        "lon": lon,
        "lat": lat,
        "alt_km": alt_km,
        "u": u_val,
        "v": v_val,
        "conf": conf_val,
        "speed": speed,
    }


def _pool_mean_2d(arr: np.ndarray, max_side: int) -> np.ndarray:
    if max_side <= 0 or max(arr.shape) <= max_side:
        return arr
    fy = max(1, int(math.ceil(arr.shape[0] / max_side)))
    fx = max(1, int(math.ceil(arr.shape[1] / max_side)))
    pad_y = (-arr.shape[0]) % fy
    pad_x = (-arr.shape[1]) % fx
    if pad_y or pad_x:
        arr = np.pad(arr, ((0, pad_y), (0, pad_x)), mode="edge")
    return arr.reshape(arr.shape[0] // fy, fy, arr.shape[1] // fx, fx).mean(axis=(1, 3))


def _normalize_radar(radar: np.ndarray) -> np.ndarray:
    arr = np.asarray(radar, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    if arr.size == 0:
        return arr
    lo = float(np.quantile(arr, 0.02))
    hi = float(np.quantile(arr, 0.995))
    if hi <= lo:
        hi = float(np.max(arr)) if np.max(arr) > lo else lo + 1.0
    return np.clip((arr - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


def _sample_by_conf(conf: np.ndarray, max_points: int, min_conf: float = 0.0) -> np.ndarray:
    if conf.size == 0:
        return np.asarray([], dtype=np.int64)
    keep = np.where(np.asarray(conf, dtype=np.float32) >= float(min_conf))[0]
    if keep.size <= max_points:
        return keep
    order = keep[np.argsort(conf[keep])[::-1]]
    return np.sort(order[:max_points])


def _roi_bounds(data: dict[str, Any], pad_deg: float, min_span_deg: float) -> tuple[float, float, float, float]:
    lon = np.asarray(data["lon"], dtype=np.float64)
    lat = np.asarray(data["lat"], dtype=np.float64)
    lon0 = max(LON_MIN, float(np.min(lon)) - pad_deg)
    lon1 = min(LON_MAX, float(np.max(lon)) + pad_deg)
    lat0 = max(LAT_MIN, float(np.min(lat)) - pad_deg)
    lat1 = min(LAT_MAX, float(np.max(lat)) + pad_deg)

    def expand(lo: float, hi: float, global_lo: float, global_hi: float) -> tuple[float, float]:
        span = hi - lo
        if span >= min_span_deg:
            return lo, hi
        center = 0.5 * (lo + hi)
        half = 0.5 * min_span_deg
        lo = max(global_lo, center - half)
        hi = min(global_hi, center + half)
        if hi - lo < min_span_deg:
            if lo <= global_lo:
                hi = min(global_hi, global_lo + min_span_deg)
            elif hi >= global_hi:
                lo = max(global_lo, global_hi - min_span_deg)
        return lo, hi

    lon0, lon1 = expand(lon0, lon1, LON_MIN, LON_MAX)
    lat0, lat1 = expand(lat0, lat1, LAT_MIN, LAT_MAX)
    return lon0, lon1, lat0, lat1


def _radar_crop(radar: np.ndarray, roi: tuple[float, float, float, float]) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    lon0, lon1, lat0, lat1 = roi
    h_dim, w_dim = radar.shape
    x0f, y1f = _lonlat_to_xy(lon0, lat0, h_dim, w_dim)
    x1f, y0f = _lonlat_to_xy(lon1, lat1, h_dim, w_dim)
    x0 = max(0, min(w_dim - 1, int(math.floor(min(x0f, x1f)))))
    x1 = max(x0 + 1, min(w_dim, int(math.ceil(max(x0f, x1f)))))
    y0 = max(0, min(h_dim - 1, int(math.floor(min(y0f, y1f)))))
    y1 = max(y0 + 1, min(h_dim, int(math.ceil(max(y0f, y1f)))))
    crop = radar[y0:y1, x0:x1]
    crop_lon0 = LON_MIN + x0 * (LON_MAX - LON_MIN) / max(1, w_dim)
    crop_lon1 = LON_MIN + x1 * (LON_MAX - LON_MIN) / max(1, w_dim)
    crop_lat1 = LAT_MAX - y0 * (LAT_MAX - LAT_MIN) / max(1, h_dim)
    crop_lat0 = LAT_MAX - y1 * (LAT_MAX - LAT_MIN) / max(1, h_dim)
    return crop, (crop_lon0, crop_lon1, crop_lat0, crop_lat1)


def _vector_deltas(u: np.ndarray, v: np.ndarray, speed: np.ndarray, span_deg: float, arrow_fraction: float = 0.045) -> tuple[np.ndarray, np.ndarray]:
    u = np.asarray(u, dtype=np.float32)
    v = np.asarray(v, dtype=np.float32)
    speed = np.asarray(speed, dtype=np.float32)
    denom = np.maximum(speed, 1e-6)
    speed_ref = float(np.quantile(speed[speed > 0], 0.75)) if np.any(speed > 0) else 1.0
    length = max(0.02, float(span_deg) * arrow_fraction) * np.clip(speed / max(speed_ref, 1e-6), 0.25, 1.8)
    return (u / denom * length).astype(np.float32), (v / denom * length).astype(np.float32)


def _format_float(value: Any, ndigits: int = 6) -> str:
    try:
        return f"{float(value):.{ndigits}f}"
    except (TypeError, ValueError):
        return "0.000000"


def _title_info(row: dict[str, Any]) -> str:
    reasons = ", ".join(row.get("selection_reasons", []))
    return (
        f"time={row.get('time_str', '')}  reasons={reasons}\n"
        f"triggered={_int(row, 'recon_triggered')}  "
        f"filled/domain={_int(row, 'recon_filled_voxels')}/{_int(row, 'recon_domain_voxels')}  "
        f"coverage={_format_float(row.get('recon_coverage_ratio'))}  "
        f"conf_mean={_format_float(row.get('recon_conf_mean'))}  "
        f"hazard={_int(row, 'hazard_alert_voxels')}"
    )


def _render_country_png(
    row: dict[str, Any],
    data: dict[str, Any],
    roi: tuple[float, float, float, float],
    out_path: Path,
    *,
    max_radar_side: int,
    max_points: int,
    min_conf: float,
) -> None:
    radar = _pool_mean_2d(_normalize_radar(data["radar"]), max_radar_side)
    fig, ax = plt.subplots(figsize=(13, 9), constrained_layout=True)
    ax.imshow(
        radar,
        extent=(LON_MIN, LON_MAX, LAT_MIN, LAT_MAX),
        origin="upper",
        cmap="gray",
        alpha=0.82,
        interpolation="nearest",
    )
    idx = _sample_by_conf(np.asarray(data["conf"]), max_points=max_points, min_conf=min_conf)
    if idx.size > 0:
        scatter = ax.scatter(
            np.asarray(data["lon"])[idx],
            np.asarray(data["lat"])[idx],
            c=np.asarray(data["conf"])[idx],
            s=10 + 28 * np.clip(np.asarray(data["conf"])[idx], 0.0, 1.0),
            cmap="viridis",
            alpha=0.88,
            edgecolors="none",
            label="recon sparse voxels",
        )
        fig.colorbar(scatter, ax=ax, fraction=0.03, pad=0.015, label="recon confidence")
    lon0, lon1, lat0, lat1 = roi
    ax.add_patch(Rectangle((lon0, lat0), lon1 - lon0, lat1 - lat0, fill=False, edgecolor="#ff6b35", linewidth=2.2))
    ax.text(lon0, lat1, " ROI ", color="#ff6b35", fontsize=10, weight="bold", va="bottom", ha="left")
    ax.set_xlim(LON_MIN, LON_MAX)
    ax.set_ylim(LAT_MIN, LAT_MAX)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.set_title("Stage4 sparse local wind reconstruction on national radar grid\n" + _title_info(row), fontsize=12)
    ax.grid(color="white", alpha=0.25, linewidth=0.6)
    ax.text(
        0.01,
        0.02,
        "Not a dense nationwide wind field: only sparse reconstructed voxels are plotted.",
        transform=ax.transAxes,
        fontsize=9,
        color="white",
        bbox={"facecolor": "black", "alpha": 0.45, "edgecolor": "none", "pad": 4},
    )
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _choose_levels(z: np.ndarray, max_levels: int) -> list[int]:
    if z.size == 0:
        return []
    levels, counts = np.unique(np.asarray(z, dtype=np.int32), return_counts=True)
    top = levels[np.argsort(counts)[::-1][:max_levels]]
    return [int(v) for v in sorted(top)]


def _render_roi_layers_png(
    row: dict[str, Any],
    data: dict[str, Any],
    roi: tuple[float, float, float, float],
    out_path: Path,
    *,
    max_levels: int,
    max_vectors_per_level: int,
    min_conf: float,
    max_radar_side: int,
) -> list[int]:
    levels = _choose_levels(np.asarray(data["z"]), max_levels=max_levels)
    if not levels:
        return []

    ncols = 2
    nrows = int(math.ceil(len(levels) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 5.4 * nrows), squeeze=False, constrained_layout=True)
    crop, crop_extent = _radar_crop(_normalize_radar(data["radar"]), roi)
    crop = _pool_mean_2d(crop, max_radar_side)
    lon0, lon1, lat0, lat1 = roi
    span = max(lon1 - lon0, lat1 - lat0)

    for ax in axes.reshape(-1):
        ax.axis("off")

    for ax, level in zip(axes.reshape(-1), levels):
        ax.axis("on")
        ax.imshow(crop, extent=crop_extent, origin="upper", cmap="gray", alpha=0.70, interpolation="nearest")
        mask = (np.asarray(data["z"]) == level) & (np.asarray(data["conf"]) >= float(min_conf))
        local = np.where(mask)[0]
        if local.size > max_vectors_per_level:
            order = local[np.argsort(np.asarray(data["conf"])[local])[::-1]]
            local = np.sort(order[:max_vectors_per_level])
        if local.size > 0:
            dx, dy = _vector_deltas(
                np.asarray(data["u"])[local],
                np.asarray(data["v"])[local],
                np.asarray(data["speed"])[local],
                span_deg=span,
            )
            ax.scatter(
                np.asarray(data["lon"])[local],
                np.asarray(data["lat"])[local],
                c=np.asarray(data["conf"])[local],
                s=18 + 28 * np.clip(np.asarray(data["conf"])[local], 0.0, 1.0),
                cmap="viridis",
                alpha=0.88,
                edgecolors="none",
            )
            ax.quiver(
                np.asarray(data["lon"])[local],
                np.asarray(data["lat"])[local],
                dx,
                dy,
                angles="xy",
                scale_units="xy",
                scale=1.0,
                color="black",
                width=0.0032,
                headwidth=3.2,
                alpha=0.72,
            )
        ax.set_xlim(lon0, lon1)
        ax.set_ylim(lat0, lat1)
        ax.set_xlabel("Longitude (deg)")
        ax.set_ylabel("Latitude (deg)")
        ax.set_title(f"altitude={level * ALT_STEP_M / 1000.0:.1f} km  vectors={local.size}", fontsize=11)
        ax.grid(color="white", alpha=0.28, linewidth=0.6)

    fig.suptitle("ROI multi-altitude wind vectors (visual-only arrows)\n" + _title_info(row), fontsize=13)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    return levels


def _render_roi_3d_png(
    row: dict[str, Any],
    data: dict[str, Any],
    roi: tuple[float, float, float, float],
    out_path: Path,
    *,
    max_vectors: int,
    min_conf: float,
) -> bool:
    idx = _sample_by_conf(np.asarray(data["conf"]), max_points=max_vectors, min_conf=min_conf)
    if idx.size == 0:
        return False

    lon0, lon1, lat0, lat1 = roi
    span = max(lon1 - lon0, lat1 - lat0)
    dx, dy = _vector_deltas(
        np.asarray(data["u"])[idx],
        np.asarray(data["v"])[idx],
        np.asarray(data["speed"])[idx],
        span_deg=span,
        arrow_fraction=0.055,
    )

    fig = plt.figure(figsize=(13, 10), constrained_layout=True)
    ax = fig.add_subplot(111, projection="3d")
    scatter = ax.scatter(
        np.asarray(data["lon"])[idx],
        np.asarray(data["lat"])[idx],
        np.asarray(data["alt_km"])[idx],
        c=np.asarray(data["conf"])[idx],
        s=20 + 34 * np.clip(np.asarray(data["conf"])[idx], 0.0, 1.0),
        cmap="viridis",
        alpha=0.86,
    )
    ax.quiver(
        np.asarray(data["lon"])[idx],
        np.asarray(data["lat"])[idx],
        np.asarray(data["alt_km"])[idx],
        dx,
        dy,
        np.zeros_like(dx),
        length=1.0,
        normalize=False,
        color="black",
        linewidth=0.62,
        alpha=0.70,
    )
    ax.set_xlim(lon0, lon1)
    ax.set_ylim(lat0, lat1)
    ax.set_zlim(0.0, 15.0)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")
    ax.set_zlabel("Altitude (km)")
    ax.set_title("ROI 3D sparse wind vectors in lon/lat/alt coordinates\n" + _title_info(row), fontsize=12)
    ax.view_init(elev=26, azim=-58)
    ax.grid(True, alpha=0.25)
    fig.colorbar(scatter, ax=ax, fraction=0.035, pad=0.02, label="recon confidence")
    ax.text2D(
        0.02,
        0.02,
        "Arrows are scaled for readability; no nationwide interpolation is applied.",
        transform=ax.transAxes,
        fontsize=9,
        bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": "none", "pad": 4},
    )
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    return True


def _record(
    row: dict[str, Any],
    country_path: Path | None,
    roi_layers_path: Path | None,
    roi_3d_path: Path | None,
    skipped_reason: str,
    roi: tuple[float, float, float, float] | None,
    levels: list[int],
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
    out = {key: row.get(key) for key in keys if key in row}
    out["selection_reasons"] = list(row.get("selection_reasons", []))
    out["country_png_path"] = str(country_path) if country_path is not None else ""
    out["roi_layers_png_path"] = str(roi_layers_path) if roi_layers_path is not None else ""
    out["roi_3d_png_path"] = str(roi_3d_path) if roi_3d_path is not None else ""
    out["skipped_reason"] = skipped_reason
    if roi is not None:
        lon0, lon1, lat0, lat1 = roi
        out["roi_lon_min"] = lon0
        out["roi_lon_max"] = lon1
        out["roi_lat_min"] = lat0
        out["roi_lat_max"] = lat1
    out["rendered_z_levels"] = levels
    out["rendered_altitude_km"] = [round(v * ALT_STEP_M / 1000.0, 3) for v in levels]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Stage-4 sparse wind fields in geographic coordinates.")
    parser.add_argument("--stage4-dir", type=Path, default=DEFAULT_STAGE4_DIR)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--selection", choices=("representative", "frames"), default="representative")
    parser.add_argument("--frame-times", default="", help="Comma-separated time_str values for --selection=frames.")
    parser.add_argument("--max-country-points", type=int, default=5000)
    parser.add_argument("--max-vectors", type=int, default=350)
    parser.add_argument("--max-vectors-per-level", type=int, default=160)
    parser.add_argument("--max-levels", type=int, default=4)
    parser.add_argument("--min-conf", type=float, default=0.0)
    parser.add_argument("--roi-pad-deg", type=float, default=0.5)
    parser.add_argument("--min-roi-span-deg", type=float, default=1.0)
    parser.add_argument("--max-radar-side", type=int, default=900)
    args = parser.parse_args()

    stage4_dir = args.stage4_dir
    summary_path = args.summary or (stage4_dir / "stage4_summary.json")
    summary = _load_json(summary_path)
    if not isinstance(summary, list):
        raise TypeError(f"Expected Stage-4 summary list at {summary_path}")
    selected_rows = _select_representative_rows(summary) if args.selection == "representative" else _select_frame_rows(summary, args.frame_times)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for row in selected_rows:
        filename = str(row.get("filename") or f"frame_{row.get('time_str')}.npz")
        npz_path = stage4_dir / filename
        if not npz_path.exists():
            raise FileNotFoundError(f"Missing Stage-4 frame NPZ: {npz_path}")
        data = _load_sparse_recon_and_radar(npz_path)
        stem = f"{_int(row, 'source_index'):05d}_{_frame_id(row)}"

        country_path: Path | None = None
        roi_layers_path: Path | None = None
        roi_3d_path: Path | None = None
        skipped_reason = ""
        roi = None
        levels: list[int] = []

        if _int(row, "recon_filled_voxels") <= 0 or np.asarray(data["conf"]).size == 0:
            skipped_reason = "empty_reconstruction"
            print(f"[stage4-geo-viz] skip empty frame {stem}")
        else:
            roi = _roi_bounds(data, pad_deg=args.roi_pad_deg, min_span_deg=args.min_roi_span_deg)
            country_path = args.out_dir / f"{stem}_country_roi.png"
            roi_layers_path = args.out_dir / f"{stem}_roi_layers.png"
            roi_3d_path = args.out_dir / f"{stem}_roi_3d.png"

            _render_country_png(
                row,
                data,
                roi,
                country_path,
                max_radar_side=args.max_radar_side,
                max_points=args.max_country_points,
                min_conf=args.min_conf,
            )
            print(f"[stage4-geo-viz] wrote {country_path}")
            levels = _render_roi_layers_png(
                row,
                data,
                roi,
                roi_layers_path,
                max_levels=args.max_levels,
                max_vectors_per_level=args.max_vectors_per_level,
                min_conf=args.min_conf,
                max_radar_side=args.max_radar_side,
            )
            print(f"[stage4-geo-viz] wrote {roi_layers_path}")
            if _render_roi_3d_png(row, data, roi, roi_3d_path, max_vectors=args.max_vectors, min_conf=args.min_conf):
                print(f"[stage4-geo-viz] wrote {roi_3d_path}")
            else:
                roi_3d_path = None
                skipped_reason = "no_vectors_after_filter"

        records.append(_record(row, country_path, roi_layers_path, roi_3d_path, skipped_reason, roi, levels))

    selected_path = args.out_dir / "selected_frames_geo.json"
    with selected_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "stage4_dir": str(stage4_dir),
                "summary": str(summary_path),
                "selection": args.selection,
                "frame_count": len(records),
                "coordinate_mapping": {
                    "lat_min": LAT_MIN,
                    "lat_max": LAT_MAX,
                    "lon_min": LON_MIN,
                    "lon_max": LON_MAX,
                    "alt_step_m": ALT_STEP_M,
                    "statement": "Sparse local 3D wind reconstruction on a national radar grid; no dense nationwide interpolation.",
                },
                "frames": records,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[stage4-geo-viz] wrote {selected_path}")


if __name__ == "__main__":
    main()
