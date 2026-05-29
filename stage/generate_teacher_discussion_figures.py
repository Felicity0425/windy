"""Generate Stage1-Stage3 discussion figures for teacher presentation.

This helper works in two steps:

1. `--prepare-data`:
   read parquet / npz / json and export lightweight JSON assets
2. `--render`:
   read those JSON assets and render PNG figures with matplotlib
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")


BASE = Path("/data/LFT-W02_data/pengxu")
OUT_DIR = BASE / "teacher_discussion_assets"
ASSET_PATH = OUT_DIR / "teacher_discussion_assets.json"
FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def prepare_data() -> None:
    import pandas as pd
    import numpy as np

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    stage1_summary = _load_json(BASE / "stage1_output/stage1_summary.json")
    frame_windows = _load_json(BASE / "stage1_output/frame_window_index.json")
    wind = pd.read_parquet(BASE / "stage1_output/clean_wind.parquet", columns=["lat_clean", "alt_meters"])
    loc = pd.read_parquet(BASE / "stage1_output/clean_loc.parquet", columns=["lon_clean", "lat_clean"])

    stage2_rows = _load_json(BASE / "stage2_output/stage2_summary.json")
    target_stage2 = next(r for r in stage2_rows if r["time_str"] == "20260206174200")
    with np.load(target_stage2["vox_path"], allow_pickle=True) as z:
        radar = np.asarray(z["radar_img"], dtype=np.float32)
        wind_records = [dict(x) for x in z["wind_records"].tolist()]
        grid_shape = [int(v) for v in np.asarray(z["grid_shape"], dtype=np.int32).tolist()]

    stage3_rows = _load_json(BASE / "stage3_output_v2/stage3_summary.json")
    stage3_obj = _load_json(BASE / "stage3_output_v2/agents/frame_20260206174200_agents.json")

    asset = {
        "stage1": {
            "summary": stage1_summary,
            "wind_lat_sample": wind["lat_clean"].dropna().iloc[:: max(1, len(wind) // 8000)].tolist(),
            "wind_alt_km_sample": (wind["alt_meters"].dropna().iloc[:: max(1, len(wind) // 8000)] / 1000.0).tolist(),
            "loc_lon_sample": loc["lon_clean"].dropna().iloc[:: max(1, len(loc) // 15000)].tolist(),
            "loc_lat_sample": loc["lat_clean"].dropna().iloc[:: max(1, len(loc) // 15000)].tolist(),
            "frame_window_head": frame_windows[:300],
        },
        "stage2": {
            "summary_rows": stage2_rows,
            "target_time": "20260206174200",
            "target_radar_img": radar.tolist(),
            "target_wind_records": wind_records,
            "target_grid_shape": grid_shape,
        },
        "stage3": {
            "summary_rows": stage3_rows,
            "graph_example": {
                "valid_flight_agents": int(stage3_obj.get("valid_flight_agents", 0)),
                "ff_sparse_src": stage3_obj.get("ff_sparse_src", []),
                "ff_sparse_dst": stage3_obj.get("ff_sparse_dst", []),
                "ff_sparse_score": stage3_obj.get("ff_sparse_score", []),
            },
        },
    }
    ASSET_PATH.write_text(json.dumps(asset, ensure_ascii=False), encoding="utf-8")
    print(str(ASSET_PATH))


def render_figures() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib import font_manager, rcParams

    if Path(FONT_PATH).exists():
        font_manager.fontManager.addfont(FONT_PATH)
        rcParams["font.family"] = "Noto Sans CJK JP"
    rcParams["axes.unicode_minus"] = False

    asset = _load_json(ASSET_PATH)
    paths: list[str] = []

    def save(fig: plt.Figure, name: str) -> None:
        path = OUT_DIR / name
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        paths.append(str(path))

    st1 = asset["stage1"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    labels = ["clean_wind_rows", "clean_loc_rows", "radar_usable", "window_records"]
    vals = [st1["summary"][k] for k in labels]
    axes[0].bar(range(len(labels)), vals, color=["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd"])
    axes[0].set_xticks(range(len(labels)))
    axes[0].set_xticklabels(labels, rotation=15, ha="right")
    axes[0].set_title("Stage1 summary counts")
    axes[0].grid(True, axis="y", alpha=0.25)
    axes[1].scatter(st1["wind_lat_sample"], st1["wind_alt_km_sample"], s=3, alpha=0.18, color="#1f77b4")
    axes[1].set_xlabel("Latitude")
    axes[1].set_ylabel("Altitude (km)")
    axes[1].set_title("Stage1 wind samples: latitude vs altitude")
    axes[1].grid(True, alpha=0.25)
    save(fig, "stage1_summary_and_wind_distribution.png")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    axes[0].scatter(st1["loc_lon_sample"], st1["loc_lat_sample"], s=1, alpha=0.10, color="#ff7f0e")
    axes[0].set_xlabel("Longitude")
    axes[0].set_ylabel("Latitude")
    axes[0].set_title("Stage1 trajectory samples in map coordinates")
    axes[0].grid(True, alpha=0.25)
    xs = np.arange(len(st1["frame_window_head"]))
    wind_rows = [r["wind_rows"] for r in st1["frame_window_head"]]
    loc_rows = [r["loc_rows"] for r in st1["frame_window_head"]]
    axes[1].plot(xs, wind_rows, label="wind_rows", color="#1f77b4")
    axes[1].plot(xs, loc_rows, label="loc_rows", color="#ff7f0e")
    axes[1].set_title("Stage1 first 300 radar windows")
    axes[1].set_xlabel("usable frame index")
    axes[1].set_ylabel("rows in +/-5 min window")
    axes[1].legend()
    axes[1].grid(True, alpha=0.25)
    save(fig, "stage1_trajectory_map_and_window_rows.png")

    st2 = asset["stage2"]
    rows = st2["summary_rows"]
    keys = ["wind_voxels", "traj_voxels", "motion_voxels", "amdar_voxels", "turb_voxels"]
    colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#d62728"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    means = [float(np.mean([r.get(k, 0) for r in rows])) for k in keys]
    axes[0].bar(range(len(keys)), means, color=colors)
    axes[0].set_xticks(range(len(keys)))
    axes[0].set_xticklabels(keys, rotation=20, ha="right")
    axes[0].set_title("Stage2 mean voxel counts by record type")
    axes[0].grid(True, axis="y", alpha=0.25)
    top_rows = sorted(rows, key=lambda r: r.get("wind_voxels", 0), reverse=True)[:12]
    axes[1].bar(np.arange(len(top_rows)), [r["wind_voxels"] for r in top_rows], color="#1f77b4")
    axes[1].set_xticks(np.arange(len(top_rows)))
    axes[1].set_xticklabels([r["time_str"][4:12] for r in top_rows], rotation=45, ha="right")
    axes[1].set_title("Stage2 top wind-support frames")
    axes[1].grid(True, axis="y", alpha=0.25)
    save(fig, "stage2_voxel_statistics.png")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    radar = np.asarray(st2["target_radar_img"], dtype=np.float32)
    axes[0].imshow(radar, cmap="gray")
    axes[0].set_title("Stage2 radar mosaic base: 20260206174200")
    axes[0].axis("off")
    wind_records = st2["target_wind_records"]
    xs = [int(r["x"]) for r in wind_records]
    ys = [int(r["y"]) for r in wind_records]
    zs = [int(r["z"]) for r in wind_records]
    cs = [float(r.get("obs_count", 1)) for r in wind_records]
    sc = axes[1].scatter(xs, ys, c=zs, s=np.array(cs) * 6.0, cmap="turbo", alpha=0.75)
    axes[1].invert_yaxis()
    axes[1].set_title("Stage2 wind voxels projected on radar plane")
    axes[1].set_xlabel("x")
    axes[1].set_ylabel("y")
    fig.colorbar(sc, ax=axes[1], fraction=0.046, pad=0.04, label="z layer")
    save(fig, "stage2_radar_and_wind_voxels.png")

    st3 = asset["stage3"]
    rows = st3["summary_rows"]
    keys = ["valid_flight_agents", "flight_comm_allowed_agents", "flight_ff_allowed_edges", "flight_ff_wind_edges"]
    colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    means = [float(np.mean([r.get(k, 0) for r in rows])) for k in keys]
    axes[0].bar(range(len(keys)), means, color=colors)
    axes[0].set_xticks(range(len(keys)))
    axes[0].set_xticklabels(keys, rotation=20, ha="right")
    axes[0].set_title("Stage3 mean agent / edge statistics")
    axes[0].grid(True, axis="y", alpha=0.25)
    top_rows = sorted(rows, key=lambda r: r.get("flight_ff_wind_edges", 0), reverse=True)[:10]
    axes[1].bar(np.arange(len(top_rows)), [r["flight_ff_wind_edges"] for r in top_rows], color="#9467bd")
    axes[1].set_xticks(np.arange(len(top_rows)))
    axes[1].set_xticklabels([r["time_str"][4:12] for r in top_rows], rotation=45, ha="right")
    axes[1].set_title("Stage3 top wind-edge frames")
    axes[1].grid(True, axis="y", alpha=0.25)
    save(fig, "stage3_agent_edge_statistics.png")

    ex = st3["graph_example"]
    n = min(220, int(ex["valid_flight_agents"]))
    src = np.asarray(ex["ff_sparse_src"], dtype=np.int32)
    dst = np.asarray(ex["ff_sparse_dst"], dtype=np.int32)
    score = np.asarray(ex["ff_sparse_score"], dtype=np.float32)
    keep = (src < n) & (dst < n)
    src = src[keep]
    dst = dst[keep]
    score = score[keep]
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    node_x = np.cos(theta)
    node_y = np.sin(theta)
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    ax.scatter(node_x, node_y, s=18, color="#1f77b4", alpha=0.9)
    for s, d, w in zip(src[:300], dst[:300], score[:300]):
        ax.plot([node_x[s], node_x[d]], [node_y[s], node_y[d]], color="#ff7f0e", alpha=min(0.45, 0.10 + 0.35 * float(w)), linewidth=0.5)
    ax.set_title("Stage3 sparse communication graph view: 20260206174200")
    ax.set_aspect("equal")
    ax.axis("off")
    save(fig, "stage3_sparse_graph_example.png")

    (OUT_DIR / "teacher_discussion_figure_manifest.json").write_text(
        json.dumps({"figures": paths}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"figures": paths}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-data", action="store_true")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    if args.prepare_data:
        prepare_data()
    if args.render:
        render_figures()


if __name__ == "__main__":
    main()
