"""Run reproducible Stage-4 speed A/B diagnostics without changing Stage-4 logic.

This driver reuses `run_stage34_workflow_v2.sh` in `stage4_only` mode and
forces the same frame subset across profiles. It is intended to answer:
1. Is the slowdown mainly from config/profile differences?
2. Is compression a meaningful part of the slowdown?
3. Are recent post-processing cost proxies materially larger?
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from report_stage4_runtime_log import parse_stage4_log


PROFILE_ORDER = ["fast_baseline", "frozen_current", "write_cost_check"]
PROFILE_ENV_KEYS = [
    "WIND_STAGE4_FAST_MODE",
    "WIND_STAGE4_OUTPUT_PROFILE",
    "WIND_STAGE4_ENABLE_QUALITY_EXPAND",
    "WIND_STAGE4_FAST_SKIP_POST",
    "WIND_STAGE4_FAST_SKIP_DENSE_AUX",
    "WIND_STAGE4_SAVE_COMPRESSED",
]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_frame_indices(
    summary_path: Path,
    frame_indices: str,
    frame_offset: int,
    max_frames: int | None,
) -> list[int]:
    data = _load_json(summary_path)
    indexed = list(range(len(data)))
    indices_env = (frame_indices or "").strip()
    if indices_env:
        selected: list[int] = []
        for token in indices_env.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                idx = int(token)
            except ValueError:
                continue
            if 0 <= idx < len(indexed):
                selected.append(idx)
        return sorted(set(selected))

    selected = indexed[max(0, int(frame_offset)) :]
    if max_frames is not None:
        selected = selected[: max(1, int(max_frames))]
    return selected


def _parse_sample_sizes(text: str) -> list[int]:
    out: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        out.append(max(1, int(token)))
    return out


def _profile_env(profile: str) -> dict[str, str]:
    if profile == "fast_baseline":
        return {
            "WIND_STAGE4_FAST_MODE": "1",
            "WIND_STAGE4_OUTPUT_PROFILE": "fast",
            "WIND_STAGE4_ENABLE_QUALITY_EXPAND": "0",
            "WIND_STAGE4_FAST_SKIP_POST": "1",
            "WIND_STAGE4_FAST_SKIP_DENSE_AUX": "1",
            "WIND_STAGE4_SAVE_COMPRESSED": "0",
        }
    if profile == "frozen_current":
        return {}
    if profile == "write_cost_check":
        return {
            "WIND_STAGE4_SAVE_COMPRESSED": "0",
        }
    raise ValueError(f"Unknown profile={profile}")


def _build_log_dir(log_root_dir: Path, run_label_override: str) -> Path:
    return log_root_dir / f"indices_{run_label_override}__stage4_only"


def _build_output_dir(output_root: Path, run_label_override: str) -> Path:
    return output_root / run_label_override


def _latest_stage4_log(log_dir: Path) -> Path | None:
    logs = sorted(log_dir.glob("stage4*.log"))
    if not logs:
        return None
    return logs[0]


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _build_conclusion(records: dict[str, dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    fast = records.get("fast_baseline", {})
    frozen = records.get("frozen_current", {})
    write = records.get("write_cost_check", {})

    fast_t = _float_or_zero(fast.get("avg_sec_per_frame"))
    frozen_t = _float_or_zero(frozen.get("avg_sec_per_frame"))
    write_t = _float_or_zero(write.get("avg_sec_per_frame"))

    if fast_t > 0 and frozen_t > 0 and fast_t <= 0.80 * frozen_t:
        notes.append("`fast_baseline` 明显快于 `frozen_current`，主因更像是 profile / 后处理路径差异。")
    if write_t > 0 and frozen_t > 0 and write_t <= 0.90 * frozen_t:
        notes.append("`write_cost_check` 明显快于 `frozen_current`，压缩写盘成本占比显著。")
    if not notes and frozen_t > 0 and write_t > 0:
        notes.append("关闭压缩后改善不大，慢速更像来自重构输入规模或后处理本身。")

    frozen_diag = frozen.get("recent_diag_stats", {}) or {}
    fast_diag = fast.get("recent_diag_stats", {}) or {}
    if frozen_diag and fast_diag:
        if _float_or_zero(frozen_diag.get("support_fill_mean")) > _float_or_zero(fast_diag.get("support_fill_mean")):
            notes.append("`frozen_current` 的 support-fill 规模更大，后处理补洞成本可能更高。")
        if _float_or_zero(frozen_diag.get("support_expand_mean")) > _float_or_zero(fast_diag.get("support_expand_mean")):
            notes.append("`frozen_current` 的 support-expand 规模更大，扩展路径可能抬高耗时。")
        if _float_or_zero(frozen_diag.get("pruned_mean")) > _float_or_zero(fast_diag.get("pruned_mean")):
            notes.append("`frozen_current` 的 prune 规模更大，说明完整路径里尾部清理成本也在增加。")
        if _float_or_zero(frozen_diag.get("recon_vox_mean")) > _float_or_zero(fast_diag.get("recon_vox_mean")):
            notes.append("`frozen_current` 的重构体素规模更大，说明输入 bbox / 补全域可能更宽。")

    if not notes:
        notes.append("三组结果没有给出单一强结论，建议下一步重点检查触发帧比例与局部 bbox 大小。")
    return notes


def _write_markdown(report: dict[str, Any], out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# Stage4 Speed A/B Report")
    lines.append("")
    lines.append(f"- generated_at: `{report['generated_at']}`")
    lines.append(f"- workflow: `{report['workflow']}`")
    lines.append(f"- stage3_input_dir: `{report['stage3_input_dir']}`")
    lines.append(f"- frame_indices_base: `{report['frame_indices_base']}`")
    lines.append("")
    for sample in report["samples"]:
        lines.append(f"## Sample {sample['sample_size']}")
        lines.append("")
        lines.append("| profile | done | total | elapsed_sec | avg_sec_per_frame | fps | support_fill_mean | temporal_fill_mean | support_expand_mean | pruned_mean | recon_vox_mean |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for profile in PROFILE_ORDER:
            one = sample["profiles"].get(profile, {})
            diag = one.get("recent_diag_stats", {}) or {}
            lines.append(
                "| "
                f"{profile} | "
                f"{int(one.get('done', 0))} | "
                f"{int(one.get('total', 0))} | "
                f"{_float_or_zero(one.get('elapsed_sec')):.1f} | "
                f"{_float_or_zero(one.get('avg_sec_per_frame')):.3f} | "
                f"{_float_or_zero(one.get('fps')):.5f} | "
                f"{_float_or_zero(diag.get('support_fill_mean')):.1f} | "
                f"{_float_or_zero(diag.get('temporal_fill_mean')):.1f} | "
                f"{_float_or_zero(diag.get('support_expand_mean')):.1f} | "
                f"{_float_or_zero(diag.get('pruned_mean')):.1f} | "
                f"{_float_or_zero(diag.get('recon_vox_mean')):.1f} |"
            )
        lines.append("")
        lines.append("### Conclusion")
        lines.append("")
        for note in sample.get("conclusion", []):
            lines.append(f"- {note}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible Stage-4 speed A/B diagnostics.")
    script_dir = Path(__file__).resolve().parent
    default_base_dir = script_dir.parent
    parser.add_argument("--workflow", default=str(script_dir / "run_stage34_workflow_v2.sh"))
    parser.add_argument("--base-dir", default=str(default_base_dir))
    parser.add_argument("--stage2-output-dir", default="")
    parser.add_argument("--stage3-input-dir", default="")
    parser.add_argument("--log-root-dir", default=str(script_dir / "logs_v2"))
    parser.add_argument("--output-root", default="")
    parser.add_argument("--frame-indices", default=os.environ.get("WIND_FRAME_INDICES", ""))
    parser.add_argument("--frame-offset", type=int, default=int(os.environ.get("WIND_FRAME_OFFSET", "0") or "0"))
    parser.add_argument("--max-frames", type=int, default=(int(os.environ["WIND_MAX_FRAMES"]) if os.environ.get("WIND_MAX_FRAMES") not in (None, "", "0") else 0))
    parser.add_argument("--sample-sizes", default="10,50")
    parser.add_argument("--stage4-cpu-threads", type=int, default=int(os.environ.get("STAGE4_CPU_THREADS", "8") or "8"))
    parser.add_argument("--run-label-prefix", default="stage4_speed_ab")
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    workflow = Path(args.workflow).resolve()
    if not workflow.exists():
        raise SystemExit(f"Missing workflow script: {workflow}")

    base_dir = Path(args.base_dir).resolve()
    stage2_output_dir = Path(args.stage2_output_dir).resolve() if args.stage2_output_dir else base_dir / "stage2_output"
    stage3_input_dir = Path(args.stage3_input_dir).resolve() if args.stage3_input_dir else base_dir / "stage3_output_v2"
    log_root_dir = Path(args.log_root_dir).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else base_dir / "stage4_speed_ab_runs"
    output_root.mkdir(parents=True, exist_ok=True)
    stage2_summary_path = stage2_output_dir / "stage2_summary.json"
    if not stage2_summary_path.exists():
        raise SystemExit(f"Missing Stage-2 summary: {stage2_summary_path}")
    if not stage3_input_dir.exists():
        raise SystemExit(f"Missing Stage-3 input dir: {stage3_input_dir}")

    sample_sizes = _parse_sample_sizes(args.sample_sizes)
    base_max_frames = max(sample_sizes) if sample_sizes else 0
    requested_max_frames = args.max_frames if args.max_frames and args.max_frames > 0 else base_max_frames
    base_indices = _resolve_frame_indices(
        stage2_summary_path,
        frame_indices=args.frame_indices,
        frame_offset=args.frame_offset,
        max_frames=requested_max_frames,
    )
    if not base_indices:
        raise SystemExit("Resolved frame index set is empty.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report: dict[str, Any] = {
        "generated_at": timestamp,
        "workflow": str(workflow),
        "base_dir": str(base_dir),
        "stage2_output_dir": str(stage2_output_dir),
        "stage3_input_dir": str(stage3_input_dir),
        "log_root_dir": str(log_root_dir),
        "output_root": str(output_root),
        "frame_indices_base": base_indices,
        "sample_sizes": sample_sizes,
        "stage4_cpu_threads": args.stage4_cpu_threads,
        "samples": [],
    }

    for sample_size in sample_sizes:
        if len(base_indices) < sample_size:
            print(f"[stage4-speed-ab][WARN] skip sample_size={sample_size}: only {len(base_indices)} indices available")
            continue
        sample_indices = base_indices[:sample_size]
        sample_report: dict[str, Any] = {
            "sample_size": sample_size,
            "frame_indices": sample_indices,
            "profiles": {},
            "conclusion": [],
        }
        indices_csv = ",".join(str(x) for x in sample_indices)
        for profile in PROFILE_ORDER:
            run_label_override = f"{args.run_label_prefix}_{sample_size}_{profile}_{timestamp}"
            run_output_dir = _build_output_dir(output_root, run_label_override)
            run_output_dir.mkdir(parents=True, exist_ok=True)
            log_dir = _build_log_dir(log_root_dir, run_label_override)

            env = os.environ.copy()
            env["BASE_DIR"] = str(base_dir)
            env["STAGE_DIR"] = str(script_dir)
            env["LOG_ROOT_DIR"] = str(log_root_dir)
            env["LOG_DIR"] = str(log_root_dir)
            env["LATEST_LOG_DIR"] = str(log_root_dir)
            env["STAGE2_OUTPUT_DIR"] = str(stage2_output_dir)
            env["RUN_MODE"] = "indices"
            env["RUN_PHASE"] = "stage4_only"
            env["FRAME_INDICES"] = indices_csv
            env["RUN_LABEL_OVERRIDE"] = run_label_override
            env["STAGE3_INPUT_DIR_FOR_STAGE4"] = str(stage3_input_dir)
            env["STAGE4_OUTPUT_DIR"] = str(run_output_dir)
            env["WIND_STAGE4_OUTPUT_DIR"] = str(run_output_dir)
            env["STAGE4_CPU_THREADS"] = str(args.stage4_cpu_threads)
            env["OMP_NUM_THREADS"] = str(args.stage4_cpu_threads)
            env["MKL_NUM_THREADS"] = str(args.stage4_cpu_threads)
            env["NUMEXPR_NUM_THREADS"] = str(args.stage4_cpu_threads)
            env["POLARS_MAX_THREADS"] = str(args.stage4_cpu_threads)
            env["WIND_PROGRESS_EVERY"] = str(args.progress_every)
            env["RUN_VALIDATE"] = "0"
            env["EXPORT_AFTER_RUN"] = "0"
            for key in PROFILE_ENV_KEYS:
                env.pop(key, None)
            env.update(_profile_env(profile))

            cmd = ["bash", str(workflow)]
            print(f"[stage4-speed-ab] sample={sample_size} profile={profile} frames={indices_csv}")
            print(f"[stage4-speed-ab] output_dir={run_output_dir}")
            if args.dry_run:
                sample_report["profiles"][profile] = {
                    "dry_run": True,
                    "run_label_override": run_label_override,
                    "log_dir": str(log_dir),
                    "output_dir": str(run_output_dir),
                    "frame_indices": sample_indices,
                    "env_overrides": {k: env[k] for k in sorted(env) if k.startswith("WIND_STAGE4") or k in {
                        "RUN_MODE",
                        "RUN_PHASE",
                        "FRAME_INDICES",
                        "RUN_LABEL_OVERRIDE",
                        "STAGE3_INPUT_DIR_FOR_STAGE4",
                        "STAGE4_CPU_THREADS",
                        "OMP_NUM_THREADS",
                        "MKL_NUM_THREADS",
                        "NUMEXPR_NUM_THREADS",
                        "POLARS_MAX_THREADS",
                        "WIND_PROGRESS_EVERY",
                    }},
                }
                continue

            proc = subprocess.run(cmd, cwd=str(base_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            profile_record: dict[str, Any] = {
                "returncode": int(proc.returncode),
                "run_label_override": run_label_override,
                "log_dir": str(log_dir),
                "output_dir": str(run_output_dir),
                "workflow_stdout_tail": proc.stdout.splitlines()[-20:],
            }
            log_path = _latest_stage4_log(log_dir)
            if log_path is not None and log_path.exists():
                parsed = parse_stage4_log(log_path, tail_count=10)
                latest = parsed["latest_progress"]
                profile_record.update(
                    {
                        "log_path": str(log_path),
                        "done": int(latest.get("done", 0)),
                        "total": int(latest.get("total", 0)),
                        "elapsed_text": latest.get("elapsed_text", ""),
                        "elapsed_sec": float(latest.get("elapsed_sec", 0.0)),
                        "avg_sec_per_frame": float(latest.get("avg_sec_per_frame", 0.0)),
                        "fps": float(latest.get("fps", 0.0)),
                        "latest_progress_line": latest.get("line", ""),
                        "recent_frame_lines": parsed["recent_frame_lines"],
                        "recent_diag_lines": parsed["recent_diag_lines"],
                        "recent_frame_stats": parsed["recent_frame_stats"],
                        "recent_diag_stats": parsed["recent_diag_stats"],
                    }
                )
            else:
                profile_record["log_path"] = ""
                profile_record["error"] = "Missing Stage-4 log."
            sample_report["profiles"][profile] = profile_record

        sample_report["conclusion"] = _build_conclusion(sample_report["profiles"])
        report["samples"].append(sample_report)

    report_json = output_root / f"{args.run_label_prefix}_{timestamp}.json"
    report_md = output_root / f"{args.run_label_prefix}_{timestamp}.md"
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(report, report_md)

    print(f"[stage4-speed-ab] report_json={report_json}")
    print(f"[stage4-speed-ab] report_md={report_md}")


if __name__ == "__main__":
    main()
