"""Render Stage-3 flight-agent graphs as geographic and topology PNG diagnostics.

This script is intentionally read-only. It consumes existing Stage-2 and Stage-3
outputs, selects representative frames, and writes presentation-friendly PNGs
without mutating pipeline artifacts.
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


DEFAULT_STAGE2_SUMMARY = Path("/data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json")
DEFAULT_STAGE3_SUMMARY = Path("/data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json")
DEFAULT_STAGE3_DIR = Path("/data/LFT-W02_data/pengxu/stage3_output_v2")
DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative")

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


def _max_by_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda r: (_num(r, key), -_int(r, "source_index", 0)))


def _nearest_by_metric(rows: list[dict[str, Any]], key: str, target: float) -> dict[str, Any] | None:
    if not rows:
        return None
    return min(rows, key=lambda r: (abs(_num(r, key) - target), _time_key(r)))


def _select_representative_rows(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    _register_selection(selected, _max_by_metric(summary, "valid_flight_agents"), "max_valid_flight_agents")
    _register_selection(selected, _max_by_metric(summary, "flight_ff_allowed_edges"), "max_flight_ff_allowed_edges")
    _register_selection(selected, _max_by_metric(summary, "flight_ff_wind_edges"), "max_flight_ff_wind_edges")
    _register_selection(selected, _max_by_metric(summary, "valid_wind_capable_flights"), "max_valid_wind_capable_flights")
    _register_selection(selected, _max_by_metric(summary, "wind_support_score_p90"), "max_wind_support_score_p90")

    nonzero_wind = [r for r in summary if _num(r, "flight_ff_wind_edges") > 0.0]
    if nonzero_wind:
        _register_selection(selected, sorted(nonzero_wind, key=_time_key)[0], "earliest_nonzero_wind_edge_frame")

    if summary:
        ff_wind = np.asarray([_num(r, "flight_ff_wind_edges") for r in summary], dtype=np.float64)
        valid_agents = np.asarray([_num(r, "valid_flight_agents") for r in summary], dtype=np.float64)
        _register_selection(
            selected,
            _nearest_by_metric(summary, "flight_ff_wind_edges", float(np.median(ff_wind))),
            "median_flight_ff_wind_edges",
        )
        _register_selection(
            selected,
            _nearest_by_metric(summary, "valid_flight_agents", float(np.median(valid_agents))),
            "median_valid_flight_agents",
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
        raise ValueError(f"Frame times not found in Stage-3 summary: {', '.join(missing)}")
    rows = []
    for time in wanted:
        row = dict(by_time[time])
        row["selection_reasons"] = ["requested_frame"]
        rows.append(row)
    return rows


def _linear_to_zyx(idx: np.ndarray, h_dim: int, w_dim: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    idx64 = np.asarray(idx, dtype=np.int64)
    if idx64.size == 0:
        return (
            np.asarray([], dtype=np.int32),
            np.asarray([], dtype=np.int32),
            np.asarray([], dtype=np.int32),
        )
    z = idx64 // (h_dim * w_dim)
    rem = idx64 % (h_dim * w_dim)
    y = rem // w_dim
    x = rem % w_dim
    return z.astype(np.int32, copy=False), y.astype(np.int32, copy=False), x.astype(np.int32, copy=False)


def _xy_to_lonlat(x: np.ndarray, y: np.ndarray, h_dim: int, w_dim: int) -> tuple[np.ndarray, np.ndarray]:
    lon = LON_MIN + (np.asarray(x, dtype=np.float64) + 0.5) * (LON_MAX - LON_MIN) / max(1, w_dim)
    lat = LAT_MAX - (np.asarray(y, dtype=np.float64) + 0.5) * (LAT_MAX - LAT_MIN) / max(1, h_dim)
    return lon.astype(np.float32, copy=False), lat.astype(np.float32, copy=False)


def _stable_radius(agent_obs_count: np.ndarray) -> np.ndarray:
    if agent_obs_count.size == 0:
        return np.asarray([], dtype=np.float32)
    scaled = np.log1p(np.clip(agent_obs_count, 0.0, None))
    max_v = float(np.max(scaled))
    if max_v <= 1e-8:
        return np.full(agent_obs_count.size, 34.0, dtype=np.float32)
    return (28.0 + 54.0 * scaled / max_v).astype(np.float32, copy=False)


def _load_stage3_pack(stage3_summary_row: dict[str, Any], stage3_dir: Path) -> dict[str, Any]:
    agent_path = Path(str(stage3_summary_row.get("agent_path", "")))
    if not agent_path.exists():
        agent_path = stage3_dir / "agents" / f"frame_{stage3_summary_row['time_str']}_agents.json"
    if not agent_path.exists():
        raise FileNotFoundError(f"Missing Stage-3 agent json: {agent_path}")
    payload = _load_json(agent_path)
    payload["_agent_path"] = str(agent_path)
    return payload


def _resolve_stage2_hw(stage2_summary_map: dict[str, dict[str, Any]], time_str: str) -> tuple[int, int]:
    stage2_item = stage2_summary_map.get(time_str)
    if stage2_item is None:
        raise KeyError(f"Missing Stage-2 summary row for time_str={time_str}")
    vox_path = Path(str(stage2_item.get("vox_path", "")))
    if not vox_path.exists():
        raise FileNotFoundError(f"Missing Stage-2 voxel file: {vox_path}")
    with np.load(vox_path, allow_pickle=True) as npz:
        if "radar_shape" in npz.files:
            shape = tuple(int(v) for v in np.asarray(npz["radar_shape"], dtype=np.int64).tolist())
            return shape[0], shape[1]
        if "radar_img" in npz.files:
            img = np.asarray(npz["radar_img"])
            return int(img.shape[0]), int(img.shape[1])
    raise KeyError(f"Stage-2 voxel file does not contain radar shape info: {vox_path}")


def _extract_agent_nodes(stage3_pack: dict[str, Any], h_dim: int, w_dim: int, max_agents: int) -> dict[str, np.ndarray]:
    ids = np.asarray(stage3_pack.get("flight_agent_ids", []))
    offsets = np.asarray(stage3_pack.get("flight_offsets", []), dtype=np.int64)
    idx_flat = np.asarray(stage3_pack.get("flight_idx_flat", []), dtype=np.int64)
    mask = np.asarray(stage3_pack.get("flight_mask", []), dtype=np.uint8)
    has_wind = np.asarray(stage3_pack.get("flight_has_wind_obs", []), dtype=np.float32)
    obs_flat = np.asarray(stage3_pack.get("flight_count_flat", []), dtype=np.float32)
    comm_weight = np.asarray(stage3_pack.get("flight_comm_weight", []), dtype=np.float32)
    st_like = np.asarray(stage3_pack.get("flight_st_likelihood", []), dtype=np.float32)
    support_score = np.asarray(stage3_pack.get("flight_wind_support_score", []), dtype=np.float32)

    if ids.size == 0 or offsets.size != ids.size + 1:
        return {
            "slot_idx": np.asarray([], dtype=np.int32),
            "ids": np.asarray([], dtype="<U64"),
            "x": np.asarray([], dtype=np.float32),
            "y": np.asarray([], dtype=np.float32),
            "z": np.asarray([], dtype=np.float32),
            "lon": np.asarray([], dtype=np.float32),
            "lat": np.asarray([], dtype=np.float32),
            "alt_km": np.asarray([], dtype=np.float32),
            "has_wind": np.asarray([], dtype=np.float32),
            "obs_count": np.asarray([], dtype=np.float32),
            "comm_weight": np.asarray([], dtype=np.float32),
            "st_like": np.asarray([], dtype=np.float32),
            "support_score": np.asarray([], dtype=np.float32),
            "marker_size": np.asarray([], dtype=np.float32),
        }

    slot_idx = np.where(mask > 0)[0].astype(np.int32, copy=False)
    if slot_idx.size == 0:
        slot_idx = np.arange(min(ids.size, max_agents), dtype=np.int32)

    node_rows = []
    for i in slot_idx:
        sl = slice(int(offsets[i]), int(offsets[i + 1]))
        own_idx = idx_flat[sl]
        if own_idx.size == 0:
            continue
        own_z, own_y, own_x = _linear_to_zyx(own_idx, h_dim, w_dim)
        own_obs = obs_flat[sl] if sl.stop <= obs_flat.size else np.ones(own_idx.size, dtype=np.float32)
        weight = np.clip(own_obs.astype(np.float64, copy=False), 1.0, None)
        weight_sum = float(np.sum(weight))
        obs_count = float(np.sum(own_obs))
        cx = float(np.sum(own_x * weight) / max(1e-8, weight_sum))
        cy = float(np.sum(own_y * weight) / max(1e-8, weight_sum))
        cz = float(np.sum(own_z * weight) / max(1e-8, weight_sum))
        lon, lat = _xy_to_lonlat(np.asarray([cx]), np.asarray([cy]), h_dim, w_dim)
        node_rows.append(
            {
                "slot_idx": int(i),
                "id": str(ids[i]),
                "x": cx,
                "y": cy,
                "z": cz,
                "lon": float(lon[0]),
                "lat": float(lat[0]),
                "alt_km": float(cz * ALT_STEP_M / 1000.0),
                "has_wind": float(has_wind[i]) if i < has_wind.size else 0.0,
                "obs_count": obs_count,
                "comm_weight": float(comm_weight[i]) if i < comm_weight.size else 0.0,
                "st_like": float(st_like[i]) if i < st_like.size else 0.0,
                "support_score": float(support_score[i]) if i < support_score.size else 0.0,
            }
        )

    if not node_rows:
        return {
            "slot_idx": np.asarray([], dtype=np.int32),
            "ids": np.asarray([], dtype="<U64"),
            "x": np.asarray([], dtype=np.float32),
            "y": np.asarray([], dtype=np.float32),
            "z": np.asarray([], dtype=np.float32),
            "lon": np.asarray([], dtype=np.float32),
            "lat": np.asarray([], dtype=np.float32),
            "alt_km": np.asarray([], dtype=np.float32),
            "has_wind": np.asarray([], dtype=np.float32),
            "obs_count": np.asarray([], dtype=np.float32),
            "comm_weight": np.asarray([], dtype=np.float32),
            "st_like": np.asarray([], dtype=np.float32),
            "support_score": np.asarray([], dtype=np.float32),
            "marker_size": np.asarray([], dtype=np.float32),
        }

    node_rows.sort(
        key=lambda row: (
            row["has_wind"],
            row["support_score"],
            row["obs_count"],
            row["comm_weight"],
            -row["slot_idx"],
        ),
        reverse=True,
    )
    node_rows = node_rows[: max(1, int(max_agents))]

    slot = np.asarray([row["slot_idx"] for row in node_rows], dtype=np.int32)
    obs_count = np.asarray([row["obs_count"] for row in node_rows], dtype=np.float32)
    return {
        "slot_idx": slot,
        "ids": np.asarray([row["id"] for row in node_rows]),
        "x": np.asarray([row["x"] for row in node_rows], dtype=np.float32),
        "y": np.asarray([row["y"] for row in node_rows], dtype=np.float32),
        "z": np.asarray([row["z"] for row in node_rows], dtype=np.float32),
        "lon": np.asarray([row["lon"] for row in node_rows], dtype=np.float32),
        "lat": np.asarray([row["lat"] for row in node_rows], dtype=np.float32),
        "alt_km": np.asarray([row["alt_km"] for row in node_rows], dtype=np.float32),
        "has_wind": np.asarray([row["has_wind"] for row in node_rows], dtype=np.float32),
        "obs_count": obs_count,
        "comm_weight": np.asarray([row["comm_weight"] for row in node_rows], dtype=np.float32),
        "st_like": np.asarray([row["st_like"] for row in node_rows], dtype=np.float32),
        "support_score": np.asarray([row["support_score"] for row in node_rows], dtype=np.float32),
        "marker_size": _stable_radius(obs_count),
    }


def _extract_edge_pairs(
    stage3_pack: dict[str, Any],
    node_slot_idx: np.ndarray,
    max_geo_edges: int,
    max_topology_edges: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sparse_src = np.asarray(stage3_pack.get("ff_sparse_src", []), dtype=np.int32)
    sparse_dst = np.asarray(stage3_pack.get("ff_sparse_dst", []), dtype=np.int32)
    sparse_score = np.asarray(stage3_pack.get("ff_sparse_score", []), dtype=np.float32)
    ff_wind_allowed = np.asarray(stage3_pack.get("ff_wind_allowed", []), dtype=np.float32)

    keep_nodes = set(int(x) for x in np.asarray(node_slot_idx, dtype=np.int32).tolist())
    edges = []
    if sparse_src.size == sparse_dst.size == sparse_score.size:
        for s, d, score in zip(sparse_src, sparse_dst, sparse_score):
            s = int(s)
            d = int(d)
            if s == d or s not in keep_nodes or d not in keep_nodes:
                continue
            wind_gate = 0.0
            if ff_wind_allowed.ndim == 2 and s < ff_wind_allowed.shape[0] and d < ff_wind_allowed.shape[1]:
                wind_gate = float(ff_wind_allowed[s, d])
            edges.append(
                {
                    "src": s,
                    "dst": d,
                    "score": float(score),
                    "wind_gate": wind_gate,
                    "is_wind": bool(wind_gate > 0.0),
                    "is_strong_wind": bool(wind_gate >= 0.999),
                    "is_weak_wind": bool(0.0 < wind_gate < 0.999),
                }
            )

    edges.sort(
        key=lambda row: (
            row["is_strong_wind"],
            row["is_wind"],
            row["score"],
            -row["src"],
            -row["dst"],
        ),
        reverse=True,
    )
    return edges[: max_geo_edges], edges[: max_topology_edges]


def _make_topology_layout(node_slot_idx: np.ndarray, edges: list[dict[str, Any]]) -> dict[int, tuple[float, float]]:
    if node_slot_idx.size == 0:
        return {}

    node_slot_idx = np.asarray(node_slot_idx, dtype=np.int32)
    n = int(node_slot_idx.size)
    if n == 1:
        return {int(node_slot_idx[0]): (0.0, 0.0)}

    degrees = {int(slot): 0.0 for slot in node_slot_idx.tolist()}
    for edge in edges:
        degrees[int(edge["src"])] = degrees.get(int(edge["src"]), 0.0) + float(edge["score"])
        degrees[int(edge["dst"])] = degrees.get(int(edge["dst"]), 0.0) + float(edge["score"])

    order = sorted(node_slot_idx.tolist(), key=lambda slot: (-degrees.get(int(slot), 0.0), int(slot)))
    angles = np.linspace(0.0, 2.0 * math.pi, num=n, endpoint=False, dtype=np.float64)
    coords = {}
    for i, slot in enumerate(order):
        radius = 1.0 + 0.08 * min(10.0, degrees.get(int(slot), 0.0))
        coords[int(slot)] = (float(radius * math.cos(angles[i])), float(radius * math.sin(angles[i])))

    if not edges:
        return coords

    index = {int(slot): idx for idx, slot in enumerate(order)}
    points = np.asarray([coords[int(slot)] for slot in order], dtype=np.float64)
    anchor = points.copy()
    deg = np.asarray([degrees.get(int(slot), 0.0) for slot in order], dtype=np.float64)
    deg_scale = np.clip(0.12 + 0.02 * deg, 0.12, 0.28)

    edge_pairs = []
    edge_weights = []
    for edge in edges:
        s = index.get(int(edge["src"]))
        d = index.get(int(edge["dst"]))
        if s is None or d is None or s == d:
            continue
        edge_pairs.append((s, d))
        edge_weights.append(max(0.05, float(edge["score"])))

    if not edge_pairs:
        return coords

    edge_weights = np.asarray(edge_weights, dtype=np.float64)
    weight_scale = edge_weights / max(1e-8, float(np.max(edge_weights)))

    for _ in range(60):
        delta = np.zeros_like(points)
        for (s, d), ws in zip(edge_pairs, weight_scale):
            vec = points[d] - points[s]
            dist = float(np.linalg.norm(vec))
            if dist <= 1e-6:
                vec = np.array([0.01, -0.01], dtype=np.float64)
                dist = float(np.linalg.norm(vec))
            desired = 1.3 - 0.35 * ws
            force = 0.04 * (dist - desired)
            direction = vec / dist
            delta[s] += force * direction
            delta[d] -= force * direction
        delta += 0.06 * (anchor - points)
        points += np.clip(delta, -0.08, 0.08)
        points = points * (1.0 - deg_scale[:, None]) + anchor * deg_scale[:, None]

    return {int(slot): (float(points[i, 0]), float(points[i, 1])) for i, slot in enumerate(order)}


def _render_geo_png(
    out_path: Path,
    row: dict[str, Any],
    nodes: dict[str, np.ndarray],
    edges: list[dict[str, Any]],
    dpi: int,
) -> None:
    fig, ax = plt.subplots(figsize=(12.8, 8.2), dpi=dpi)
    ax.set_facecolor("#f6f3ea")

    ax.add_patch(
        plt.Rectangle(
            (LON_MIN, LAT_MIN),
            LON_MAX - LON_MIN,
            LAT_MAX - LAT_MIN,
            facecolor="#efe7d0",
            edgecolor="#b79d74",
            linewidth=1.4,
            zorder=0,
        )
    )
    for lon in np.linspace(LON_MIN, LON_MAX, 7):
        ax.plot([lon, lon], [LAT_MIN, LAT_MAX], color="#d8ccb1", linewidth=0.5, alpha=0.65, zorder=0)
    for lat in np.linspace(LAT_MIN, LAT_MAX, 7):
        ax.plot([LON_MIN, LON_MAX], [lat, lat], color="#d8ccb1", linewidth=0.5, alpha=0.65, zorder=0)

    slot_to_pos = {int(slot): (float(lon), float(lat)) for slot, lon, lat in zip(nodes["slot_idx"], nodes["lon"], nodes["lat"])}

    for edge in edges:
        p0 = slot_to_pos.get(int(edge["src"]))
        p1 = slot_to_pos.get(int(edge["dst"]))
        if p0 is None or p1 is None:
            continue
        if edge["is_strong_wind"]:
            color = "#d94801"
            alpha = 0.58
            width = 1.45 + 2.10 * float(edge["score"])
        elif edge["is_weak_wind"]:
            color = "#f59e0b"
            alpha = 0.42
            width = 0.95 + 1.50 * float(edge["score"])
        else:
            color = "#4b5563"
            alpha = 0.20
            width = 0.65 + 1.10 * float(edge["score"])
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=color, alpha=alpha, linewidth=width, zorder=1)

    has_wind = nodes["has_wind"] > 0.0
    weak = ~has_wind
    if np.any(weak):
        ax.scatter(
            nodes["lon"][weak],
            nodes["lat"][weak],
            s=nodes["marker_size"][weak],
            c="#2b6cb0",
            edgecolors="#0f172a",
            linewidths=0.6,
            alpha=0.78,
            zorder=2,
            label="Agent",
        )
    if np.any(has_wind):
        ax.scatter(
            nodes["lon"][has_wind],
            nodes["lat"][has_wind],
            s=nodes["marker_size"][has_wind],
            c="#c2410c",
            edgecolors="#431407",
            linewidths=0.7,
            alpha=0.90,
            zorder=3,
            label="Wind-capable Agent",
        )

    ground_lon = _num(row, "ground_lon")
    ground_lat = _num(row, "ground_lat")
    if math.isfinite(ground_lon) and math.isfinite(ground_lat):
        ax.scatter(
            [ground_lon],
            [ground_lat],
            s=180,
            marker="*",
            c="#111827",
            edgecolors="#f8fafc",
            linewidths=0.9,
            zorder=4,
            label="Dynamic Ground Reference",
        )

    ax.set_xlim(LON_MIN, LON_MAX)
    ax.set_ylim(LAT_MIN, LAT_MAX)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(
        f"Stage3 Agent Geo View | {row['time_str']} | "
        f"valid={_int(row, 'valid_flight_agents')} wind_edges={_int(row, 'flight_ff_wind_edges')}",
        fontsize=13,
        pad=12,
    )

    reason = ", ".join(row.get("selection_reasons", []))
    info = (
        f"reasons: {reason}\n"
        f"candidate={_int(row, 'candidate_flight_count')} "
        f"tier1={_int(row, 'tier1_candidate_count')} "
        f"tier2={_int(row, 'tier2_candidate_count')}\n"
        f"wind_capable={_int(row, 'valid_wind_capable_flights')} "
        f"ff_allowed={_int(row, 'flight_ff_allowed_edges')} "
        f"ff_wind={_int(row, 'flight_ff_wind_edges')}\n"
        f"support score p50/p90={_num(row, 'wind_support_score_p50'):.3f}/{_num(row, 'wind_support_score_p90'):.3f}"
    )
    ax.text(
        0.013,
        0.016,
        info,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        color="#1f2937",
        bbox={"facecolor": "#fffbef", "edgecolor": "#cbd5e1", "boxstyle": "round,pad=0.42", "alpha": 0.92},
    )

    leg = ax.legend(loc="upper right", frameon=True, framealpha=0.96)
    for text in leg.get_texts():
        text.set_fontsize(9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _render_topology_png(
    out_path: Path,
    row: dict[str, Any],
    nodes: dict[str, np.ndarray],
    edges: list[dict[str, Any]],
    dpi: int,
) -> None:
    layout = _make_topology_layout(nodes["slot_idx"], edges)
    fig, ax = plt.subplots(figsize=(10.5, 9.2), dpi=dpi)
    ax.set_facecolor("#fbf7ef")

    node_index = {int(slot): i for i, slot in enumerate(nodes["slot_idx"].tolist())}
    degree = np.zeros(nodes["slot_idx"].size, dtype=np.float32)
    for edge in edges:
        s = node_index.get(int(edge["src"]))
        d = node_index.get(int(edge["dst"]))
        if s is None or d is None:
            continue
        degree[s] += 1.0
        degree[d] += 1.0

    for edge in edges:
        p0 = layout.get(int(edge["src"]))
        p1 = layout.get(int(edge["dst"]))
        if p0 is None or p1 is None:
            continue
        if edge["is_strong_wind"]:
            color = "#b91c1c"
            alpha = 0.60
            width = 1.35 + 2.10 * float(edge["score"])
        elif edge["is_weak_wind"]:
            color = "#d97706"
            alpha = 0.45
            width = 1.00 + 1.45 * float(edge["score"])
        else:
            color = "#6b7280"
            alpha = 0.18
            width = 0.60 + 0.90 * float(edge["score"])
        ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=color, alpha=alpha, linewidth=width, zorder=1)

    coords_x = np.asarray([layout[int(slot)][0] for slot in nodes["slot_idx"]], dtype=np.float32)
    coords_y = np.asarray([layout[int(slot)][1] for slot in nodes["slot_idx"]], dtype=np.float32)
    degree_size = 20.0 * np.sqrt(np.clip(degree, 0.0, None))
    marker_size = np.clip(nodes["marker_size"] + degree_size, 36.0, 180.0)
    colors = np.where(nodes["has_wind"] > 0.0, "#dc2626", "#2563eb")
    edge_colors = np.where(nodes["has_wind"] > 0.0, "#450a0a", "#172554")
    ax.scatter(
        coords_x,
        coords_y,
        s=marker_size,
        c=colors,
        edgecolors=edge_colors,
        linewidths=0.8,
        alpha=0.92,
        zorder=2,
    )

    for x, y, label in zip(coords_x, coords_y, nodes["ids"]):
        short = str(label)[:8]
        ax.text(x, y, short, ha="center", va="center", fontsize=7.2, color="#f8fafc", zorder=3)

    strong_wind_edges = int(sum(1 for edge in edges if edge["is_strong_wind"]))
    weak_wind_edges = int(sum(1 for edge in edges if edge["is_weak_wind"]))
    info = (
        f"reasons: {', '.join(row.get('selection_reasons', []))}\n"
        f"nodes={len(nodes['slot_idx'])} strong_wind_edges={strong_wind_edges} weak_wind_edges={weak_wind_edges}\n"
        f"valid={_int(row, 'valid_flight_agents')} "
        f"wind_capable={_int(row, 'valid_wind_capable_flights')} "
        f"ff_allowed={_int(row, 'flight_ff_allowed_edges')}\n"
        f"wind_support p50/p90={_num(row, 'wind_support_score_p50'):.3f}/{_num(row, 'wind_support_score_p90'):.3f}"
    )
    ax.text(
        0.014,
        0.016,
        info,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        color="#1f2937",
        bbox={"facecolor": "#fffaf0", "edgecolor": "#d1d5db", "boxstyle": "round,pad=0.42", "alpha": 0.94},
    )

    ax.set_title(
        f"Stage3 Communication Topology | {row['time_str']}",
        fontsize=13,
        pad=12,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect("equal")
    ax.set_frame_on(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _render_one_frame(
    row: dict[str, Any],
    stage2_summary_map: dict[str, dict[str, Any]],
    stage3_dir: Path,
    out_dir: Path,
    max_geo_edges: int,
    max_topology_edges: int,
    max_agents: int,
    dpi: int,
) -> dict[str, Any]:
    time_str = str(row["time_str"])
    h_dim, w_dim = _resolve_stage2_hw(stage2_summary_map, time_str)
    stage3_pack = _load_stage3_pack(row, stage3_dir)
    nodes = _extract_agent_nodes(stage3_pack, h_dim, w_dim, max_agents=max_agents)
    geo_edges, topo_edges = _extract_edge_pairs(
        stage3_pack,
        nodes["slot_idx"],
        max_geo_edges=max_geo_edges,
        max_topology_edges=max_topology_edges,
    )

    geo_path = out_dir / f"frame_{time_str}_geo.png"
    topo_path = out_dir / f"frame_{time_str}_topology.png"
    _render_geo_png(geo_path, row, nodes, geo_edges, dpi=dpi)
    _render_topology_png(topo_path, row, nodes, topo_edges, dpi=dpi)

    return {
        "time_str": time_str,
        "source_index": _int(row, "source_index"),
        "selection_reasons": list(row.get("selection_reasons", [])),
        "agent_json": str(stage3_pack.get("_agent_path", "")),
        "geo_png": str(geo_path),
        "topology_png": str(topo_path),
        "node_count": int(nodes["slot_idx"].size),
        "geo_edge_count": int(len(geo_edges)),
        "topology_edge_count": int(len(topo_edges)),
        "strong_wind_edge_count": int(sum(1 for edge in topo_edges if edge["is_strong_wind"])),
        "weak_wind_edge_count": int(sum(1 for edge in topo_edges if edge["is_weak_wind"])),
        "valid_flight_agents": _int(row, "valid_flight_agents"),
        "valid_wind_capable_flights": _int(row, "valid_wind_capable_flights"),
        "flight_ff_allowed_edges": _int(row, "flight_ff_allowed_edges"),
        "flight_ff_wind_edges": _int(row, "flight_ff_wind_edges"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Stage-3 agent geographic and topology diagnostics.")
    parser.add_argument("--stage2-summary", type=Path, default=DEFAULT_STAGE2_SUMMARY, help="Path to stage2_summary.json.")
    parser.add_argument("--stage3-summary", type=Path, default=DEFAULT_STAGE3_SUMMARY, help="Path to stage3_summary.json.")
    parser.add_argument("--stage3-dir", type=Path, default=DEFAULT_STAGE3_DIR, help="Stage-3 output directory containing agents/.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for PNGs and selected_frames.json.")
    parser.add_argument("--selection", choices=("representative", "frames"), default="representative", help="Frame selection mode.")
    parser.add_argument("--frame-times", type=str, default="", help="Comma-separated time_str values used when --selection=frames.")
    parser.add_argument("--max-geo-edges", type=int, default=500, help="Maximum edges drawn in each geographic view.")
    parser.add_argument("--max-topology-edges", type=int, default=300, help="Maximum edges drawn in each topology view.")
    parser.add_argument("--max-agents", type=int, default=120, help="Maximum agents displayed in each frame.")
    parser.add_argument("--dpi", type=int, default=180, help="Output PNG DPI.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stage2_summary = _load_json(args.stage2_summary)
    stage3_summary = _load_json(args.stage3_summary)
    stage2_summary_map = {str(row.get("time_str", "")): row for row in stage2_summary}

    if args.selection == "representative":
        rows = _select_representative_rows(stage3_summary)
    else:
        rows = _select_frame_rows(stage3_summary, args.frame_times)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    selected_rows = []
    for row in rows:
        selected_rows.append(
            _render_one_frame(
                row=row,
                stage2_summary_map=stage2_summary_map,
                stage3_dir=args.stage3_dir,
                out_dir=args.out_dir,
                max_geo_edges=max(1, int(args.max_geo_edges)),
                max_topology_edges=max(1, int(args.max_topology_edges)),
                max_agents=max(1, int(args.max_agents)),
                dpi=max(72, int(args.dpi)),
            )
        )

    summary_payload = {
        "selection": args.selection,
        "frame_times": [str(row["time_str"]) for row in rows],
        "stage2_summary": str(args.stage2_summary),
        "stage3_summary": str(args.stage3_summary),
        "stage3_dir": str(args.stage3_dir),
        "out_dir": str(args.out_dir),
        "max_geo_edges": int(args.max_geo_edges),
        "max_topology_edges": int(args.max_topology_edges),
        "max_agents": int(args.max_agents),
        "dpi": int(args.dpi),
        "frames": selected_rows,
    }
    with (args.out_dir / "selected_frames.json").open("w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    print(f"[Stage3-Viz] selection={args.selection} frames={len(selected_rows)} out_dir={args.out_dir}")
    for item in selected_rows:
        print(
            f"[Stage3-Viz] time={item['time_str']} "
            f"nodes={item['node_count']} topo_edges={item['topology_edge_count']} "
            f"strong_wind={item['strong_wind_edge_count']} weak_wind={item['weak_wind_edge_count']}"
        )


if __name__ == "__main__":
    main()
