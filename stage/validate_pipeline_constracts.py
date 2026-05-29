"""Validate cross-stage pipeline contracts.

This lightweight checker is meant to catch the most common integration issues
before long full runs:
- Stage 2 and Stage 3 frame alignment
- Stage 3 agent pack availability
- Stage 4 summary field presence
- Reconstruction helper importability

It intentionally avoids heavy computation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
STAGE_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

import pipeline_config as cfg

EXPECTED_STAGE4_FIELDS = {
    "filename",
    "source_index",
    "time_str",
    "timestamp_utc",
    "wind_voxels",
    "traj_voxels",
    "motion_voxels",
    "amdar_voxels",
    "turb_voxels",
    "candidate_flight_count",
    "tier1_candidate_count",
    "tier2_candidate_count",
    "valid_flight_agents",
    "flight_comm_allowed_agents",
    "flight_ff_allowed_edges",
    "flight_ff_motion_edges",
    "flight_ff_wind_edges",
    "recon_filled_voxels",
    "recon_coverage_ratio",
    "recon_conf_mean",
    "recon_conf_p75",
    "ground_lat",
    "ground_lon",
    "ground_alt",
}


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# [改动说明] 这里让 validator 能识别小批量/精确抽帧测试，
# 避免再拿全量 Stage-2 去误报 stage3 missing frames。
def _select_stage2_subset(stage2_summary):
    """按当前环境变量还原本次试跑实际处理的 Stage-2 子集。

    这样 validator 在小批量调试、跳帧调试、精确抽高风帧调试时，
    就不会再拿“全量 Stage-2”去对齐“子集 Stage-3/4”而误报。
    """
    indexed = []
    for idx, item in enumerate(stage2_summary):
        one = dict(item)
        one["source_index"] = idx
        indexed.append(one)

    indices_env = os.environ.get("WIND_FRAME_INDICES", "").strip()
    if indices_env:
        picked = []
        for token in indices_env.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                src_idx = int(token)
            except ValueError:
                continue
            if 0 <= src_idx < len(indexed):
                picked.append(dict(indexed[src_idx]))
        return sorted(picked, key=lambda x: int(x.get("source_index", -1)))

    frame_offset = max(0, int(os.environ.get("WIND_FRAME_OFFSET", "0") or "0"))
    if frame_offset > 0:
        indexed = indexed[frame_offset:]

    max_frames_env = os.environ.get("WIND_MAX_FRAMES")
    max_frames = None
    if max_frames_env not in (None, "", "0"):
        try:
            max_frames = max(1, int(max_frames_env))
        except ValueError:
            max_frames = None
    if max_frames is not None:
        indexed = indexed[:max_frames]
    return indexed


def main():
    errors = []
    stage2_path = os.path.join(cfg.BASE_DIR, "stage2_output", "stage2_summary.json")
    stage3_path = os.path.join(cfg.BASE_DIR, "stage3_output", "stage3_summary.json")
    stage4_path = os.path.join(cfg.BASE_DIR, "stage4_output", "stage4_summary.json")

    if not os.path.exists(stage2_path):
        errors.append(f"missing: {stage2_path}")
    if not os.path.exists(stage3_path):
        errors.append(f"missing: {stage3_path}")

    if os.path.exists(stage2_path) and os.path.exists(stage3_path):
        s2 = _select_stage2_subset(_load_json(stage2_path))
        s3 = _load_json(stage3_path)
        s2_times = {x["time_str"] for x in s2}
        s3_times = {x["time_str"] for x in s3}
        if not s2_times.issubset(s3_times):
            errors.append(f"stage3 missing frames: {len(s2_times - s3_times)}")

    if os.path.exists(stage4_path):
        s4 = _load_json(stage4_path)
        if s4:
            missing = sorted(EXPECTED_STAGE4_FIELDS - set(s4[0].keys()))
            if missing:
                errors.append(f"stage4 missing fields: {missing}")

    try:
        from reconstruct_utils import _reconstruct_wind_field  # noqa: F401
    except Exception as e:
        errors.append(f"reconstruct_utils import failed: {e}")

    if errors:
        print("[contract-check] FAIL")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    print("[contract-check] PASS")


if __name__ == "__main__":
    main()
