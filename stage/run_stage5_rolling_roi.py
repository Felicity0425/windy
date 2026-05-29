"""Run a lightweight rolling ROI Stage3/Stage4/Stage5 slice.

This helper does not change the frozen Stage4 implementation. It builds the
commands needed for an online-style increment:

- run only requested frame indices through the existing Stage3/Stage4 v2 chain
- keep Stage4 single-process temporal ordering inside that small slice
- skip full-aux/report-heavy phases
- optionally run Stage5 ROI refinement on the produced Stage4 output

Use `--dry-run` first to inspect the commands.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


BASE_DIR = Path("/data/LFT-W02_data/pengxu")
STAGE_DIR = BASE_DIR / "stage"
WORKFLOW = STAGE_DIR / "run_stage34_workflow_v2.sh"
PYTHON_STAGE4 = BASE_DIR / ".conda/envs/windy310/bin/python"
PYTHON_VIZ = Path("/opt/miniconda3/bin/python")
DEFAULT_BACKGROUND_DIR = BASE_DIR / "stage5_external_background/gfs_gdas_roi_npz"
DEFAULT_STAGE2_SUMMARY = BASE_DIR / "stage2_output/stage2_summary.json"


def _run(cmd: list[str], env: dict[str, str], *, dry_run: bool) -> None:
    printable = " ".join(cmd)
    print(f"[rolling] {printable}")
    if dry_run:
        return
    subprocess.run(cmd, env=env, check=True)


def _indices_from_frame_times(summary_path: Path, frame_times: str) -> str:
    wanted = [token.strip() for token in frame_times.split(",") if token.strip()]
    if not wanted:
        raise ValueError("--frame-times is empty.")
    with summary_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    by_time = {str(row.get("time_str", "")): idx for idx, row in enumerate(summary)}
    missing = [time for time in wanted if time not in by_time]
    if missing:
        raise ValueError(f"Frame times not found in {summary_path}: {', '.join(missing)}")
    return ",".join(str(by_time[time]) for time in wanted)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run online-style rolling ROI Stage3/4/5 slice.")
    parser.add_argument("--frame-indices", default="", help="Comma-separated Stage2 source indices, for example 76,7041. Do not include angle brackets.")
    parser.add_argument("--frame-times", default="", help="Comma-separated time_str values; converted to Stage2 source indices.")
    parser.add_argument("--stage2-summary", type=Path, default=DEFAULT_STAGE2_SUMMARY)
    parser.add_argument("--run-label", default="rolling_roi_v1")
    parser.add_argument("--stage4-output-dir", type=Path, default=BASE_DIR / "stage4_output_rolling_roi_v1")
    parser.add_argument("--stage5-output-dir", type=Path, default=BASE_DIR / "stage5_output_rolling_roi_v1")
    parser.add_argument("--stage4-cpu-threads", type=int, default=6)
    parser.add_argument("--stage3-shards", type=int, default=2)
    parser.add_argument("--run-stage5", action="store_true")
    parser.add_argument("--background-dir", type=Path, default=DEFAULT_BACKGROUND_DIR)
    parser.add_argument("--no-background", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    frame_indices = args.frame_indices.strip()
    if args.frame_times.strip():
        frame_indices = _indices_from_frame_times(args.stage2_summary, args.frame_times)
        print(f"[rolling] resolved frame_times={args.frame_times} -> frame_indices={frame_indices}")
    if not frame_indices:
        raise SystemExit("Provide --frame-indices 76,7041 or --frame-times 20260124013600,20260222063600. Do not type angle brackets.")
    if "<" in frame_indices or ">" in frame_indices:
        raise SystemExit("Do not use placeholders like <new_frame_indices>; pass real indices, e.g. --frame-indices 76,7041.")

    env = os.environ.copy()
    env.update(
        {
            "BASE_DIR": str(BASE_DIR),
            "RUN_MODE": "indices",
            "RUN_LABEL_OVERRIDE": args.run_label,
            "RUN_PHASE": "stage34_core",
            "RUN_VALIDATE": "0",
            "FRAME_INDICES": frame_indices,
            "PROGRESS_EVERY": "1",
            "STAGE3_PARALLEL_SHARDS": str(args.stage3_shards),
            "STAGE3_CPU_THREADS_PER_WORKER": "1",
            "STAGE4_CPU_THREADS": str(args.stage4_cpu_threads),
            "MULTI_GPU_STAGE4_SHARD": "0",
            "STAGE3_INPUT_DIR_FOR_STAGE4": str(BASE_DIR / "stage3_output_v2"),
            "STAGE4_OUTPUT_DIR": str(args.stage4_output_dir),
            "WIND_STAGE4_FAST_MODE": "1",
            "WIND_STAGE4_OUTPUT_PROFILE": "fast",
            "WIND_STAGE4_ENABLE_QUALITY_EXPAND": "0",
            "WIND_STAGE4_USE_GPU": env.get("WIND_STAGE4_USE_GPU", "auto"),
            "WIND_STAGE4_GPU_DEVICE": env.get("WIND_STAGE4_GPU_DEVICE", "cuda:0"),
        }
    )
    if PYTHON_STAGE4.exists():
        env["PYTHON"] = str(PYTHON_STAGE4)

    _run(["bash", str(WORKFLOW)], env, dry_run=args.dry_run)

    if args.run_stage5:
        stage5_cmd = [
            str(PYTHON_VIZ if PYTHON_VIZ.exists() else PYTHON_STAGE4),
            str(STAGE_DIR / "stage5_pinn_diffusion_refine.py"),
            "--stage4-dir",
            str(args.stage4_output_dir),
            "--summary",
            str(args.stage4_output_dir / "stage4_summary.json"),
            "--out-dir",
            str(args.stage5_output_dir),
            "--selection",
            "representative",
            "--iterations",
            "4",
            "--local-expand-iters",
            "1",
            "--max-expand-voxels",
            "1000",
            "--max-local-voxels",
            "15000000",
            "--holdout-every",
            "5",
            "--hazard-conservative",
            "--make-plots",
            "1",
            "--max-plot-vectors",
            "250",
        ]
        if args.background_dir and not args.no_background:
            stage5_cmd.extend(["--background-dir", str(args.background_dir)])
        _run(stage5_cmd, env, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
