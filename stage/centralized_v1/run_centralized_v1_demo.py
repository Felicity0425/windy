"""Run the centralized_v1 Stage2->Stage5 demo pipeline on selected frames."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


BASE = Path("/data/LFT-W02_data/pengxu")
STAGE = BASE / "stage" / "centralized_v1" / "core"
LOG_DIR = BASE / "stage" / "centralized_v1" / "logs"
PY = BASE / ".conda" / "envs" / "windy310" / "bin" / "python"
DEFAULT_EXPANDED_FRAMES = (
    "20260131073000,"
    "20260206174200,"
    "20260207022400,"
    "20260208124800,"
    "20260210060000,"
    "20260211060600,"
    "20260213053600,"
    "20260215063000,"
    "20260215063600,"
    "20260215100600"
)


def _run(cmd: list[str], log_name: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / log_name
    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run centralized_v1 demo pipeline.")
    parser.add_argument("--frame-times", default="20260129114200,20260206174200")
    parser.add_argument("--expanded-strict", action="store_true", help="Run Stage3/Stage4 strict expanded 10-frame demo without touching baseline strict outputs.")
    parser.add_argument("--num-workers", type=int, default=12)
    parser.add_argument("--run-stage1", action="store_true")
    parser.add_argument("--run-cma-proxy", action="store_true")
    parser.add_argument("--run-visuals", action="store_true")
    args = parser.parse_args()

    py = str(PY if PY.exists() else "python")
    frame_times = DEFAULT_EXPANDED_FRAMES if args.expanded_strict else args.frame_times
    if args.run_stage1:
        _run(
            [
                py,
                str(BASE / "stage" / "stage1_prepare.py"),
                "--num-workers",
                str(args.num_workers),
            ],
            "stage1_prepare.log",
        )
    _run(
        [
            py,
            str(STAGE / "centralized_stage2_multimodal.py"),
            "--frame-times",
            frame_times,
            "--num-workers",
            str(args.num_workers),
        ],
        "stage2_multimodal.log",
    )
    stage3_out = BASE / "centralized_v1_output" / ("stage3_center_expanded" if args.expanded_strict else "stage3_center")
    _run(
        [
            py,
            str(STAGE / "centralized_stage3_center.py"),
            "--frame-times",
            frame_times,
            "--out-dir",
            str(stage3_out),
            "--num-workers",
            str(args.num_workers),
        ],
        "stage3_center.log",
    )
    stage4_out = BASE / "centralized_v1_output" / ("stage4_center_strict_expanded" if args.expanded_strict else "stage4_center_strict")
    _run(
        [
            py,
            str(STAGE / "centralized_stage4_ground_recon.py"),
            "--frame-times",
            frame_times,
            "--stage3-summary",
            str(stage3_out / "stage3_center_summary.json"),
            "--out-dir",
            str(stage4_out),
            "--num-workers",
            str(args.num_workers),
        ],
        "stage4_center.log",
    )
    if args.run_cma_proxy:
        cma_out = BASE / "centralized_v1_output" / "cma_ra_virtual_radial_3dvar_linear6min"
        _run(
            [
                py,
                str(STAGE / "centralized_cma_ra_virtual_radial_3dvar.py"),
                "--frame-times",
                frame_times,
                "--out-dir",
                str(cma_out),
                "--stage4-recon-dir",
                str(stage4_out),
                "--radar-sites",
                "stage2_roi,33.2,104.0,0.0;gz_proxy,23.0,113.0,50.0",
                "--cma-time-method",
                "linear",
                "--aircraft-anchor-mode",
                "none",
                "--num-workers",
                str(args.num_workers),
            ],
            "cma_ra_virtual_radial_3dvar.log",
        )
    if args.run_visuals:
        _run(
            [
                py,
                str(STAGE / "centralized_report_stage4_slices.py"),
                "--stage4-dir",
                str(stage4_out),
                "--frame-times",
                frame_times,
                "--out-dir",
                str(stage4_out / "slices"),
                "--num-workers",
                str(args.num_workers),
            ],
            "stage4_slices.log",
        )
    _run(
        [
            py,
            str(STAGE / "centralized_stage5_wind_cloud.py"),
        ],
        "stage5_center.log",
    )
    print(LOG_DIR)


if __name__ == "__main__":
    main()
