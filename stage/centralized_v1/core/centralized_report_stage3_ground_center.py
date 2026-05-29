"""Ground Center payload report for centralized_v1 Stage3."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

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


PAYLOAD_GROUPS = [
    "label_candidates",
    "context_wind_observations",
    "context_motion_observations",
    "trajectory_observations",
    "motion_observations",
]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def _group_counts(payload: dict[str, Any]) -> dict[str, int]:
    ground = payload.get("ground_center_payload", {})
    counts = {}
    for key in PAYLOAD_GROUPS:
        counts[key] = int(ground.get(key, {}).get("count", 0))
    return counts


def _qc_counts(payload: dict[str, Any]) -> dict[str, int]:
    ground = payload.get("ground_center_payload", {})
    out: dict[str, int] = {}
    for key in ("context_wind_observations", "context_motion_observations"):
        counts = ground.get(key, {}).get("confidence_summary", {}).get("qc_flags_counts", {})
        for flag, count in counts.items():
            out[str(flag)] = out.get(str(flag), 0) + int(count)
    return out


def _rows(summary_row: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    ground = payload.get("ground_center_payload", {})
    counts = _group_counts(payload)
    qc = _qc_counts(payload)
    rows: list[dict[str, Any]] = []
    for key, count in counts.items():
        rows.append({"section": "payload_count", "metric": key, "value": count})
    for key in ("center_agent_count", "agent_time_conf_mean", "agent_space_conf_mean", "agent_joint_conf_mean"):
        rows.append({"section": "stage3_summary", "metric": key, "value": summary_row.get(key, "")})
    for key in ("all_agents_downlinked", "no_air_to_air", "no_comm_distance_filter", "stage3_space_conf_mode"):
        rows.append({"section": "ground_center_flags", "metric": key, "value": payload.get(key, ground.get(key, ""))})
    for key, count in sorted(qc.items()):
        rows.append({"section": "qc_flags", "metric": key, "value": count})
    confidence = ground.get("confidence_package", {})
    rows.append({"section": "confidence_policy", "metric": "active_confidence", "value": confidence.get("active_confidence", "")})
    rows.append({"section": "confidence_policy", "metric": "space_conf", "value": confidence.get("space_conf", "")})
    rows.append({"section": "confidence_policy", "metric": "stage4_localization_policy", "value": confidence.get("stage4_localization_policy", "")})
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "metric", "value"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _fmt(row.get(key)) for key in ("section", "metric", "value")})


def _write_md(path: Path, summary_row: dict[str, Any], payload: dict[str, Any]) -> None:
    time_str = str(summary_row["time_str"])
    counts = _group_counts(payload)
    qc = _qc_counts(payload)
    confidence = payload.get("ground_center_payload", {}).get("confidence_package", {})
    lines = [
        f"# Stage3 Ground Center Report - {time_str}",
        "",
        "## Role",
        "",
        "Stage3 is Ground Center intake and confidence packaging. It does not reconstruct a wind field and does not draw Air-to-Air communication edges.",
        "",
        "## Ground Center Flags",
        "",
        f"- `all_agents_downlinked`: `{payload.get('all_agents_downlinked')}`",
        f"- `no_air_to_air`: `{payload.get('no_air_to_air')}`",
        f"- `no_comm_distance_filter`: `{payload.get('no_comm_distance_filter')}`",
        f"- `stage3_space_conf_mode`: `{payload.get('stage3_space_conf_mode')}`",
        "",
        "## Payload Counts",
        "",
        "| group | count | meaning |",
        "| --- | ---: | --- |",
    ]
    meanings = {
        "label_candidates": "Current-window wind_records; Stage4 hold-out candidates only.",
        "context_wind_observations": "Historical context_wind_records for Stage4 fusion.",
        "context_motion_observations": "Historical context_motion_records for Stage4 fusion.",
        "trajectory_observations": "Current-window loc_records trajectory support.",
        "motion_observations": "Current-window motion_records motion support.",
    }
    for key in PAYLOAD_GROUPS:
        lines.append(f"| `{key}` | {counts[key]} | {meanings[key]} |")
    lines.extend(
        [
            "",
            "## Agent And Confidence Summary",
            "",
            f"- `center_agent_count`: `{summary_row.get('center_agent_count')}`",
            f"- `agent_time_conf_mean`: `{_fmt(summary_row.get('agent_time_conf_mean'))}`",
            f"- `agent_space_conf_mean`: `{_fmt(summary_row.get('agent_space_conf_mean'))}`",
            f"- `agent_joint_conf_mean`: `{_fmt(summary_row.get('agent_joint_conf_mean'))}`",
            "",
            "Active confidence remains:",
            "",
            "```text",
            "joint_likelihood = obs_conf * time_conf",
            "space_conf = 1.0",
            "```",
            "",
            f"- `active_confidence`: `{confidence.get('active_confidence', '')}`",
            f"- `stage4_localization_policy`: `{confidence.get('stage4_localization_policy', '')}`",
            "",
            "## QC Flags",
            "",
            "| flag | count |",
            "| --- | ---: |",
        ]
    )
    if qc:
        for key, count in sorted(qc.items()):
            lines.append(f"| `{key}` | {count} |")
    else:
        lines.append("| `none` | 0 |")
    lines.extend(
        [
            "",
            "## Stage4 Entry",
            "",
            "Stage4 should draw strict hold-out points only from `label_candidates` / `wind_records`. Any selected hold-out point must be removed before fusion and then evaluated with concrete `gt_u/gt_v/pred_u/pred_v` errors.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _render_png(path: Path, summary_row: dict[str, Any], payload: dict[str, Any]) -> None:
    time_str = str(summary_row["time_str"])
    counts = _group_counts(payload)
    qc = _qc_counts(payload)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)

    labels = list(counts.keys())
    vals = [counts[k] for k in labels]
    axes[0, 0].barh(labels, vals, color=["#ff7a00", "#d936c9", "#7a4cc2", "#2aa8ff", "#20b25f"])
    axes[0, 0].set_title("Ground Center Payload Counts")
    axes[0, 0].set_xlabel("records")

    agent_metrics = {
        "agents": _safe_float(summary_row.get("center_agent_count")),
        "all_downlinked": 1.0 if payload.get("all_agents_downlinked") else 0.0,
        "no_air_to_air": 1.0 if payload.get("no_air_to_air") else 0.0,
        "no_comm_filter": 1.0 if payload.get("no_comm_distance_filter") else 0.0,
    }
    axes[0, 1].bar(agent_metrics.keys(), agent_metrics.values(), color="#4f7ecb")
    axes[0, 1].set_title("Agent Count And Ground Center Flags")
    axes[0, 1].tick_params(axis="x", rotation=25)

    conf = {
        "time_mean": _safe_float(summary_row.get("agent_time_conf_mean")),
        "space_mean": _safe_float(summary_row.get("agent_space_conf_mean")),
        "joint_mean": _safe_float(summary_row.get("agent_joint_conf_mean")),
    }
    axes[1, 0].bar(conf.keys(), conf.values(), color=["#355c7d", "#6c5b7b", "#c06c84"])
    axes[1, 0].set_ylim(0.0, 1.05)
    axes[1, 0].set_title("Stage3 Confidence Summary")

    if qc:
        axes[1, 1].bar(qc.keys(), qc.values(), color="#c44e52")
    else:
        axes[1, 1].bar(["none"], [0], color="#c44e52")
    axes[1, 1].set_title("Context QC Flags")
    axes[1, 1].tick_params(axis="x", rotation=20)

    fig.suptitle(
        f"Centralized v1 Stage3 Ground Center Payload - {time_str}\n"
        "All agents downlinked; no Air-to-Air; no communication-distance filter; no reconstruction in Stage3",
        fontsize=13,
    )
    fig.savefig(path, dpi=170)
    plt.close(fig)


def render_one(summary_row: dict[str, Any], out_dir: Path) -> dict[str, str]:
    payload = _load_json(Path(summary_row["agent_path"]))
    time_str = str(summary_row["time_str"])
    png = out_dir / f"stage3_ground_center_{time_str}.png"
    md = out_dir / f"stage3_ground_center_{time_str}.md"
    csv_path = out_dir / f"stage3_ground_center_{time_str}.csv"
    _render_png(png, summary_row, payload)
    _write_md(md, summary_row, payload)
    _write_csv(csv_path, _rows(summary_row, payload))
    return {"time_str": time_str, "png": str(png), "md": str(md), "csv": str(csv_path)}


def _write_rows_file(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_batch_subprocess(args: argparse.Namespace, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    workers = max(1, int(args.num_workers))
    outputs: list[dict[str, str]] = []
    pending = list(rows)
    running: list[tuple[subprocess.Popen[str], Path, Path]] = []
    log_dir = args.out_dir / "shards"
    log_dir.mkdir(parents=True, exist_ok=True)
    env_base = os.environ.copy()
    env_base.setdefault("OMP_NUM_THREADS", "1")
    env_base.setdefault("OPENBLAS_NUM_THREADS", "1")
    while pending or running:
        while pending and len(running) < workers:
            row = pending.pop(0)
            time_str = str(row["time_str"])
            row_file = log_dir / f"stage3_report_{time_str}_row.json"
            summary_file = log_dir / f"stage3_report_{time_str}_summary.json"
            log_file = log_dir / f"stage3_report_{time_str}.log"
            _write_rows_file(row_file, [row])
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--stage3-summary",
                str(row_file),
                "--out-dir",
                str(args.out_dir),
                "--shard-summary",
                str(summary_file),
            ]
            with log_file.open("w", encoding="utf-8") as log:
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
            running.append((proc, summary_file, log_file))
        still_running: list[tuple[subprocess.Popen[str], Path, Path]] = []
        for proc, summary_file, log_file in running:
            rc = proc.poll()
            if rc is None:
                still_running.append((proc, summary_file, log_file))
                continue
            if rc != 0:
                raise RuntimeError(f"Stage3 report shard failed rc={rc}; see {log_file}")
            shard_rows = json.loads(summary_file.read_text(encoding="utf-8"))
            outputs.extend(shard_rows)
        running = still_running
        if running:
            import time

            time.sleep(0.5)
    return sorted(outputs, key=lambda row: str(row["time_str"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Render centralized_v1 Stage3 Ground Center payload reports.")
    parser.add_argument("--stage3-summary", type=Path, required=True)
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--shard-summary", type=Path)
    args = parser.parse_args()

    rows = _load_json(args.stage3_summary)
    wanted = {token.strip() for token in str(args.frame_times).split(",") if token.strip()}
    if wanted:
        rows = [row for row in rows if str(row.get("time_str")) in wanted]
        found = {str(row.get("time_str")) for row in rows}
        missing = sorted(wanted - found)
        if missing:
            raise ValueError(f"Requested frame-times not found in Stage3 summary: {missing}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if int(args.num_workers) > 1 and len(rows) > 1:
        outputs = _run_batch_subprocess(args, rows)
    else:
        outputs = [render_one(row, args.out_dir) for row in rows]
    index_path = args.shard_summary if args.shard_summary else args.out_dir / "stage3_ground_center_report_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in outputs:
        print(row["png"])


if __name__ == "__main__":
    main()
