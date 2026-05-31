"""Centralized v1 Stage3: ground-center topology and confidence matrix."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import (
    REGENERATED_STAGE2_OUTPUT_DIR,
    STAGE3_OUTPUT_DIR,
    TIME_CONF_ALPHA,
)
from stage.centralized_v1.configs.centralized_v1_contract import (
    C2_CONTEXT_MOTION_RECORDS,
    C2_CONTEXT_WIND_RECORDS,
    C2_FLIGHT_RAW_RECORDS,
    C2_GRID_SHAPE,
    C2_LOC_RECORDS,
    C2_MOTION_RECORDS,
    C2_MULTIMODAL_META_JSON,
    C2_TIME_STR,
    C2_TIMESTAMP_UTC,
    C2_WIND_RECORDS,
    C3_AGENT_IDS,
    C3_AGENT_JOINT_CONF,
    C3_AGENT_SPACE_CONF,
    C3_AGENT_TIME_CONF,
    C3_ALPHA,
    C3_BETA,
    C3_CENTER_ACTIVE,
    C3_TIME_STR,
    C3_TIMESTAMP_UTC,
    C3_VOX_PATH,
)
from stage.centralized_v1.core.centralized_agents_builder import (
    build_ground_center_agents,
    empty_ground_center_agents,
)


def _load_summary(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


def _load_npz(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=True) as z:
        return {k: z[k] for k in z.files}


def _to_df(arr: np.ndarray) -> pl.DataFrame:
    return pl.DataFrame(arr.tolist()) if len(arr) else pl.DataFrame()


def _records(arr: np.ndarray) -> list[dict[str, Any]]:
    return [dict(x) for x in arr.tolist()] if len(arr) else []


def _record_count(npz: dict[str, Any], key: str) -> int:
    return int(len(npz[key])) if key in npz else 0


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value)
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _confidence_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("time_conf", "space_conf", "joint_likelihood", "obs_conf", "quality_conf_diagnostic", "density_conf_diagnostic"):
        vals = []
        for row in records:
            value = row.get(key)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if np.isfinite(number):
                vals.append(number)
        if vals:
            arr = np.asarray(vals, dtype=np.float64)
            out[f"{key}_min"] = float(np.min(arr))
            out[f"{key}_mean"] = float(np.mean(arr))
            out[f"{key}_max"] = float(np.max(arr))
        else:
            out[f"{key}_min"] = None
            out[f"{key}_mean"] = None
            out[f"{key}_max"] = None
    qc_counts: dict[str, int] = {}
    for row in records:
        flag = str(row.get("qc_flags", "ok") or "ok")
        qc_counts[flag] = qc_counts.get(flag, 0) + 1
    out["qc_flags_counts"] = qc_counts
    return out


def _record_group(key: str, role: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_key": key,
        "role": role,
        "count": int(len(records)),
        "confidence_summary": _confidence_summary(records),
    }


def process_frame(row: dict[str, Any], alpha: float, out_dir: Path, agent_mode: str = "none") -> tuple[dict[str, Any], dict[str, Any]]:
    npz = _load_npz(Path(row["multimodal_vox_path"]))
    meta = json.loads(str(npz[C2_MULTIMODAL_META_JSON])) if C2_MULTIMODAL_META_JSON in npz else {}
    flight_df = _to_df(npz[C2_FLIGHT_RAW_RECORDS])
    target_time = _parse_timestamp(npz[C2_TIMESTAMP_UTC])
    reference_center = {
        "lat": meta.get("reference_center_lat"),
        "lon": meta.get("reference_center_lon"),
        "alt_m": meta.get("reference_center_alt_m"),
        "source": meta.get("reference_center_source", "stage2_reference_center"),
    }
    if agent_mode == "diagnostic":
        agents = build_ground_center_agents(
            flight_df,
            target_time,
            alpha,
            reference_center=reference_center,
        )
        agent_builder_enabled = True
    else:
        agents = empty_ground_center_agents(reference_center)
        agents["agent_builder"] = "disabled"
        agents["agent_builder_role"] = "disabled_mainline_payload_only_no_agent_construction"
        agent_builder_enabled = False
    label_records = _records(npz[C2_WIND_RECORDS]) if C2_WIND_RECORDS in npz else []
    context_wind_records = _records(npz[C2_CONTEXT_WIND_RECORDS]) if C2_CONTEXT_WIND_RECORDS in npz else []
    context_motion_records = _records(npz[C2_CONTEXT_MOTION_RECORDS]) if C2_CONTEXT_MOTION_RECORDS in npz else []
    trajectory_records = _records(npz[C2_LOC_RECORDS]) if C2_LOC_RECORDS in npz else []
    motion_records = _records(npz[C2_MOTION_RECORDS]) if C2_MOTION_RECORDS in npz else []
    ground_center_payload = {
        "payload_role": "ground_center_intake_and_confidence_package",
        "stage3_role": "all_agents_downlinked_grouping_not_reconstruction",
        "all_agents_downlinked": True,
        "no_air_to_air": True,
        "no_comm_distance_filter": True,
        "stage2_npz_path": str(row["multimodal_vox_path"]),
        "grid_shape": np.asarray(npz[C2_GRID_SHAPE], dtype=np.int32).tolist(),
        "label_candidates": _record_group(C2_WIND_RECORDS, "stage4_strict_holdout_candidates_only", label_records),
        "context_wind_observations": _record_group(C2_CONTEXT_WIND_RECORDS, "historical_context_for_stage4_fusion", context_wind_records),
        "context_motion_observations": _record_group(C2_CONTEXT_MOTION_RECORDS, "historical_motion_context_for_stage4_fusion", context_motion_records),
        "trajectory_observations": _record_group(C2_LOC_RECORDS, "current_window_trajectory_support", trajectory_records),
        "motion_observations": _record_group(C2_MOTION_RECORDS, "current_window_motion_support", motion_records),
        "confidence_package": {
            "active_confidence": "obs_conf * time_conf",
            "time_conf": "temporal freshness; closer observations to target time are more representative",
            "obs_conf": "source observation confidence when available, otherwise 1.0",
            "space_conf": "neutral 1.0 in Stage2/Stage3 because Ground Center is logical and not a physical weighting center",
            "joint_likelihood": "obs_conf * time_conf in Stage2 neutral-all-in mode",
            "diagnostic_confidence": {
                "quality_conf_diagnostic": "diagnostic-only quality field; currently 1.0 after required-field filtering, not used in active joint_likelihood",
                "density_conf_diagnostic": "diagnostic-only aggregation support, computed as 1-exp(-count/3) from obs_count or motion_count",
                "qc_flags": "report-only QC candidate labels such as high_speed_qc_candidate; no default deletion or downweighting",
            },
            "reference_center_used_for_weighting": False,
            "stage2_space_conf_mode": meta.get("stage2_space_conf_mode", "neutral_all_in"),
            "target_voxel_localization_deferred_to_stage4": True,
            "stage4_localization_policy": "Stage4 should compute spatial localization from observation voxel to target voxel, e.g. Gaussian or Gaspari-Cohn style.",
        },
        "agent_builder_package": {
            "agent_mode": agent_mode,
            "agent_builder_enabled": agent_builder_enabled,
            "agent_builder": agents.get("agent_builder"),
            "agent_builder_role": agents.get("agent_builder_role"),
            "all_agents_downlinked": True,
            "no_air_to_air": True,
            "motion_used_as_wind": False,
            "center_downlink_edge_count": len(agents.get("center_downlink_src", [])),
            "reference_center_source": agents.get("agent_reference_center_source"),
            "reference_center_used_for_weighting": False,
        },
        "stage2_metadata_excerpt": {
            "stage2_role": meta.get("stage2_role"),
            "all_in_observations": meta.get("all_in_observations"),
            "all_in_scope": meta.get("all_in_scope"),
            "current_window_side_minutes": meta.get("current_window_side_minutes"),
            "context_window_side_minutes": meta.get("context_window_side_minutes"),
            "reference_center_source": meta.get("reference_center_source"),
            "reference_center_lat": meta.get("reference_center_lat"),
            "reference_center_lon": meta.get("reference_center_lon"),
            "reference_center_alt_m": meta.get("reference_center_alt_m"),
        },
    }
    payload = {
        C3_TIME_STR: str(npz[C2_TIME_STR]),
        C3_TIMESTAMP_UTC: str(npz[C2_TIMESTAMP_UTC]),
        C3_VOX_PATH: str(row["multimodal_vox_path"]),
        C3_CENTER_ACTIVE: 1,
        C3_ALPHA: float(alpha),
        C3_BETA: 0.0,
        **agents,
        "ground_center_payload": ground_center_payload,
        "all_agents_downlinked": True,
        "no_air_to_air": True,
        "no_comm_distance_filter": True,
        "stage3_space_conf_mode": "neutral_logical_ground_center",
        "stage4_target_voxel_localization_deferred": True,
        "agent_mode": agent_mode,
        "agent_builder_enabled": agent_builder_enabled,
        "deprecated_ff_fields": {
            "ff_comm_allowed": [],
            "ff_wind_allowed": [],
            "ff_sparse_src": [],
            "ff_sparse_dst": [],
            "ff_sparse_score": [],
        },
    }
    agent_dir = out_dir / "agents"
    agent_dir.mkdir(parents=True, exist_ok=True)
    out_path = agent_dir / f"frame_{row['time_str']}_center.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "time_str": row["time_str"],
        "timestamp_utc": row["timestamp_utc"],
        "center_agent_count": len(agents[C3_AGENT_IDS]),
        "agent_time_conf_mean": float(np.mean(agents[C3_AGENT_TIME_CONF])) if agents[C3_AGENT_TIME_CONF] else 0.0,
        "agent_space_conf_mean": float(np.mean(agents[C3_AGENT_SPACE_CONF])) if agents[C3_AGENT_SPACE_CONF] else 0.0,
        "agent_joint_conf_mean": float(np.mean(agents[C3_AGENT_JOINT_CONF])) if agents[C3_AGENT_JOINT_CONF] else 0.0,
        "agent_mode": agent_mode,
        "agent_builder_enabled": agent_builder_enabled,
        "agent_builder": agents.get("agent_builder"),
        "agent_builder_role": agents.get("agent_builder_role"),
        "agent_record_count_total": int(sum(agents.get("agent_record_count", []))),
        "agent_voxel_count_total": int(sum(agents.get("agent_voxel_count", []))),
        "agent_virtual_flight_count": int(agents.get("agent_virtual_flight_count", 0)),
        "agent_virtual_record_count": int(agents.get("agent_virtual_record_count", 0)),
        "center_downlink_edge_count": len(agents.get("center_downlink_src", [])),
        "agent_reference_center_source": agents.get("agent_reference_center_source"),
        "all_agents_downlinked": True,
        "no_air_to_air": True,
        "no_comm_distance_filter": True,
        "stage3_space_conf_mode": "neutral_logical_ground_center",
        "stage4_target_voxel_localization_deferred": True,
        "label_candidate_count": _record_count(npz, C2_WIND_RECORDS),
        "context_wind_observation_count": _record_count(npz, C2_CONTEXT_WIND_RECORDS),
        "context_motion_observation_count": _record_count(npz, C2_CONTEXT_MOTION_RECORDS),
        "trajectory_observation_count": _record_count(npz, C2_LOC_RECORDS),
        "motion_observation_count": _record_count(npz, C2_MOTION_RECORDS),
        "agent_path": str(out_path),
        "multimodal_vox_path": row["multimodal_vox_path"],
    }
    return payload, summary


def _parse_frame_times(frame_times: str) -> set[str]:
    return {token.strip() for token in str(frame_times).split(",") if token.strip()}


def _filter_rows(rows: list[dict[str, Any]], frame_times: str) -> list[dict[str, Any]]:
    wanted = _parse_frame_times(frame_times)
    if not wanted:
        return rows
    filtered = [row for row in rows if str(row.get("time_str")) in wanted]
    found = {str(row.get("time_str")) for row in filtered}
    missing = sorted(wanted - found)
    if missing:
        raise ValueError(f"Requested frame-times not found in Stage2 summary: {missing}")
    return filtered


def _write_shard_frame_times(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps([str(row["time_str"]) for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")


def _read_frame_times_file(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Stage3 frame-times-file must contain a JSON list: {path}")
    return ",".join(str(item) for item in payload)


def _write_progress(path: Path | None, *, completed: int, total: int, shard_id: int, status: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed": int(completed),
        "total": int(total),
        "shard_id": int(shard_id),
        "status": str(status),
        "percent": float(100.0 * completed / max(1, total)),
        "updated_unix": time.time(),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _read_progress(path: Path, fallback_total: int) -> tuple[int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return int(payload.get("completed", 0)), int(payload.get("total", fallback_total))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0, int(fallback_total)


def _print_parent_progress(progress_files: list[tuple[Path, int]], *, force: bool = False) -> None:
    completed = 0
    total = 0
    for path, shard_total in progress_files:
        done, part_total = _read_progress(path, shard_total)
        completed += min(done, part_total)
        total += part_total
    percent = 100.0 * completed / max(1, total)
    if force or total:
        print(f"[Stage3 progress] {completed}/{total} frames ({percent:.2f}%)", flush=True)


def _run_parent_shards(args: argparse.Namespace, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    workers = max(1, int(args.num_workers))
    shard_dir = args.out_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards = [[] for _ in range(workers)]
    for idx, row in enumerate(selected):
        shards[idx % workers].append(row)

    procs: list[tuple[subprocess.Popen[str], Path, Path, Path, int]] = []
    progress_files: list[tuple[Path, int]] = []
    env_base = os.environ.copy()
    env_base.setdefault("POLARS_MAX_THREADS", "1")
    for shard_idx, rows in enumerate(shards):
        if not rows:
            continue
        frame_file = shard_dir / f"stage3_shard_{shard_idx:02d}_frames.json"
        summary_file = shard_dir / f"stage3_shard_{shard_idx:02d}_summary.json"
        log_file = shard_dir / f"stage3_shard_{shard_idx:02d}.log"
        progress_file = shard_dir / f"stage3_shard_{shard_idx:02d}_progress.json"
        _write_shard_frame_times(frame_file, rows)
        _write_progress(progress_file, completed=0, total=len(rows), shard_id=shard_idx, status="queued")
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--stage2-summary",
            str(args.stage2_summary),
            "--out-dir",
            str(args.out_dir),
            "--frame-times-file",
            str(frame_file),
            "--alpha",
            str(args.alpha),
            "--agent-mode",
            str(args.agent_mode),
            "--num-workers",
            str(workers),
            "--shard-id",
            str(shard_idx),
            "--shard-summary",
            str(summary_file),
            "--progress-file",
            str(progress_file),
            "--progress-total",
            str(len(rows)),
        ]
        with log_file.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
        procs.append((proc, summary_file, log_file, progress_file, len(rows)))
        progress_files.append((progress_file, len(rows)))

    last_progress_print = 0.0
    while True:
        running = [proc for proc, _, _, _, _ in procs if proc.poll() is None]
        now = time.time()
        if now - last_progress_print >= max(1.0, float(args.progress_interval_seconds)):
            _print_parent_progress(progress_files)
            last_progress_print = now
        if not running:
            break
        time.sleep(1.0)
    _print_parent_progress(progress_files, force=True)
    summaries: list[dict[str, Any]] = []
    for proc, summary_file, log_file, _, _ in procs:
        rc = proc.poll()
        if rc != 0:
            raise RuntimeError(f"Stage3 shard failed rc={rc}; see {log_file}")
        summaries.extend(json.loads(summary_file.read_text(encoding="utf-8")))
    return sorted(summaries, key=lambda row: str(row["time_str"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Centralized v1 Stage3 ground-center topology builder.")
    parser.add_argument(
        "--stage2-summary",
        type=Path,
        default=REGENERATED_STAGE2_OUTPUT_DIR / "stage2_multimodal_summary.json",
    )
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--out-dir", type=Path, default=STAGE3_OUTPUT_DIR)
    parser.add_argument("--alpha", type=float, default=TIME_CONF_ALPHA)
    parser.add_argument(
        "--agent-mode",
        choices=("none", "diagnostic"),
        default="none",
        help="none keeps Stage3 as payload-only; diagnostic builds optional Ground Center agent diagnostics.",
    )
    parser.add_argument("--num-workers", type=int, default=8)
    parser.add_argument("--shard-id", type=int, default=-1)
    parser.add_argument("--shard-summary", type=Path)
    parser.add_argument("--progress-file", type=Path)
    parser.add_argument("--progress-total", type=int, default=0)
    parser.add_argument("--progress-interval-seconds", type=float, default=10.0)
    args = parser.parse_args()

    rows = _load_summary(args.stage2_summary)
    frame_times = _read_frame_times_file(args.frame_times_file) if args.frame_times_file else str(args.frame_times)
    rows = _filter_rows(rows, frame_times)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.shard_id < 0 and int(args.num_workers) > 1 and len(rows) > 1:
        summary_rows = _run_parent_shards(args, rows)
        summary_path = args.out_dir / "stage3_center_summary.json"
        summary_path.write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(summary_path)
        return

    summary_rows = []
    progress_total = int(args.progress_total) if int(args.progress_total) > 0 else len(rows)
    _write_progress(args.progress_file, completed=0, total=progress_total, shard_id=int(args.shard_id), status="running")
    for idx, row in enumerate(rows, start=1):
        _, summary = process_frame(row, float(args.alpha), args.out_dir, agent_mode=str(args.agent_mode))
        summary["num_workers"] = int(args.num_workers)
        summary["parallel_mode"] = "shard_subprocess" if int(args.num_workers) > 1 else "single_process"
        summary["shard_id"] = int(args.shard_id)
        summary_rows.append(summary)
        _write_progress(args.progress_file, completed=idx, total=progress_total, shard_id=int(args.shard_id), status="running")
    summary_rows.sort(key=lambda row: str(row["time_str"]))
    summary_path = args.shard_summary if args.shard_summary else args.out_dir / "stage3_center_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_progress(args.progress_file, completed=len(rows), total=progress_total, shard_id=int(args.shard_id), status="done")
    print(summary_path)


if __name__ == "__main__":
    main()
