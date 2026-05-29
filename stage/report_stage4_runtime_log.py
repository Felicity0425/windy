"""Parse Stage-4 runtime logs and summarize speed-related diagnostics.

This script is intentionally lightweight and log-oriented. It does not read
`npz` outputs or mutate any pipeline state. It focuses on:
1. Latest `[Stage-4][progress]` timing stats;
2. Recent `[Stage-4][frame]` and `[Stage-4][diag]` lines;
3. Parsed tail statistics for post-processing cost proxies.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

_PROGRESS_DONE_RE = re.compile(r"\]\s*(\d+)/(\d+)\s*\(")
_PROGRESS_ELAPSED_RE = re.compile(r"elapsed=([0-9hms.]+)")
_PROGRESS_ETA_RE = re.compile(r"eta=([0-9hms.]+)")
_PROGRESS_FPS_RE = re.compile(r"fps=([0-9.]+)")

_FRAME_PATTERNS: dict[str, re.Pattern[str]] = {
    "triggered": re.compile(r"triggered=(\d+)"),
    "seed": re.compile(r"seed=([0-9.]+)"),
    "filled": re.compile(r"filled=(\d+)"),
    "support_fill": re.compile(r"support_fill=(\d+)"),
    "temporal_fill": re.compile(r"temporal_fill=(\d+)"),
    "relax_steps": re.compile(r"relax_steps=(\d+)"),
    "comm_joint": re.compile(r"comm_joint=(\d+)"),
    "hazard_alert": re.compile(r"hazard_alert=(\d+)"),
    "coverage": re.compile(r"coverage=([0-9.]+)"),
    "conf_mean": re.compile(r"conf_mean=([0-9.]+)"),
}

_DIAG_PATTERNS: dict[str, re.Pattern[str]] = {
    "wind_raw": re.compile(r"wind_raw=(\d+)"),
    "wind": re.compile(r"wind=(\d+)"),
    "wind_primary": re.compile(r"wind_primary=(\d+)"),
    "motion_raw": re.compile(r"motion_raw=(\d+)"),
    "motion": re.compile(r"motion=(\d+)"),
    "seed_vox": re.compile(r"seed_vox=(\d+)"),
    "support_vox": re.compile(r"support_vox=(\d+)"),
    "support_fill": re.compile(r"support_fill=(\d+)"),
    "temporal_fill": re.compile(r"temporal_fill=(\d+)"),
    "relax_steps": re.compile(r"relax_steps=(\d+)"),
    "support_expand": re.compile(r"support_expand=(\d+)"),
    "anchor_restore": re.compile(r"anchor_restore=(\d+)"),
    "anchor_force": re.compile(r"anchor_force=(\d+)"),
    "comm_joint": re.compile(r"comm_joint=(\d+)"),
    "outlier_drop": re.compile(r"outlier_drop=(\d+)"),
    "pruned": re.compile(r"pruned=(\d+)"),
    "hazard_alert": re.compile(r"hazard_alert=(\d+)"),
    "recon_vox": re.compile(r"recon_vox=(\d+)"),
}


def _parse_duration_seconds(text: str) -> float:
    if not text:
        return 0.0
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", text.strip())
    if not m:
        return 0.0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = float(m.group(3) or 0.0)
    return hours * 3600.0 + minutes * 60.0 + seconds


def _parse_latest_progress(progress_lines: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "done": 0,
        "total": 0,
        "elapsed_text": "",
        "elapsed_sec": 0.0,
        "eta_text": "",
        "eta_sec": 0.0,
        "avg_sec_per_frame": 0.0,
        "fps": 0.0,
        "line": "",
    }
    for line in reversed(progress_lines):
        m_done = _PROGRESS_DONE_RE.search(line)
        m_elapsed = _PROGRESS_ELAPSED_RE.search(line)
        if not (m_done and m_elapsed):
            continue
        done = int(m_done.group(1))
        total = int(m_done.group(2))
        elapsed_text = m_elapsed.group(1)
        elapsed_sec = _parse_duration_seconds(elapsed_text)
        eta_text = ""
        eta_sec = 0.0
        fps = 0.0
        m_eta = _PROGRESS_ETA_RE.search(line)
        if m_eta:
            eta_text = m_eta.group(1)
            eta_sec = _parse_duration_seconds(eta_text)
        m_fps = _PROGRESS_FPS_RE.search(line)
        if m_fps:
            fps = float(m_fps.group(1))
        out.update(
            {
                "done": done,
                "total": total,
                "elapsed_text": elapsed_text,
                "elapsed_sec": elapsed_sec,
                "eta_text": eta_text,
                "eta_sec": eta_sec,
                "avg_sec_per_frame": (elapsed_sec / done) if done > 0 and elapsed_sec > 0 else 0.0,
                "fps": fps,
                "line": line,
            }
        )
        return out
    return out


def _parse_numeric_tail(lines: list[str], patterns: dict[str, re.Pattern[str]]) -> list[dict[str, float]]:
    parsed: list[dict[str, float]] = []
    for line in lines:
        row: dict[str, float] = {}
        for key, pat in patterns.items():
            m = pat.search(line)
            if m:
                raw = m.group(1)
                try:
                    row[key] = float(raw)
                except Exception:
                    continue
        if row:
            parsed.append(row)
    return parsed


def _describe_tail(parsed: list[dict[str, float]]) -> dict[str, float]:
    if not parsed:
        return {}
    keys = sorted({k for row in parsed for k in row})
    out: dict[str, float] = {}
    for key in keys:
        vals = np.asarray([row[key] for row in parsed if key in row], dtype=np.float64)
        if vals.size == 0:
            continue
        out[f"{key}_mean"] = float(np.mean(vals))
        out[f"{key}_p50"] = float(np.quantile(vals, 0.50))
        out[f"{key}_max"] = float(np.max(vals))
    return out


def parse_stage4_log(log_path: Path, tail_count: int = 10) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    all_lines = text.splitlines()
    progress_lines = [x for x in all_lines if "[Stage-4][progress]" in x]
    frame_lines = [x for x in all_lines if "[Stage-4][frame]" in x]
    diag_lines = [x for x in all_lines if "[Stage-4][diag]" in x]

    recent_frame_lines = frame_lines[-tail_count:]
    recent_diag_lines = diag_lines[-tail_count:]
    recent_frame_parsed = _parse_numeric_tail(recent_frame_lines, _FRAME_PATTERNS)
    recent_diag_parsed = _parse_numeric_tail(recent_diag_lines, _DIAG_PATTERNS)

    return {
        "log_path": str(log_path),
        "progress_line_count": len(progress_lines),
        "frame_line_count": len(frame_lines),
        "diag_line_count": len(diag_lines),
        "latest_progress": _parse_latest_progress(progress_lines),
        "recent_frame_lines": recent_frame_lines,
        "recent_diag_lines": recent_diag_lines,
        "recent_frame_stats": _describe_tail(recent_frame_parsed),
        "recent_diag_stats": _describe_tail(recent_diag_parsed),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Stage-4 runtime log and summarize timing diagnostics.")
    parser.add_argument("--log", required=True, help="Path to Stage-4 log file")
    parser.add_argument("--tail-count", type=int, default=10, help="Number of recent frame/diag lines to keep")
    parser.add_argument("--out-json", default="", help="Optional output JSON path")
    args = parser.parse_args()

    report = parse_stage4_log(Path(args.log), tail_count=max(1, int(args.tail_count)))

    latest = report["latest_progress"]
    print(f"log_path={report['log_path']}")
    print(f"progress_lines={report['progress_line_count']}")
    print(f"frame_lines={report['frame_line_count']}")
    print(f"diag_lines={report['diag_line_count']}")
    print(f"done={latest.get('done', 0)}")
    print(f"total={latest.get('total', 0)}")
    print(f"elapsed={latest.get('elapsed_text', '')}")
    print(f"elapsed_sec={latest.get('elapsed_sec', 0.0):.3f}")
    print(f"avg_sec_per_frame={latest.get('avg_sec_per_frame', 0.0):.3f}")
    print(f"fps={latest.get('fps', 0.0):.5f}")
    print("latest_progress_line:")
    print(latest.get("line", ""))
    print("[recent_frame_stats]")
    print(json.dumps(report["recent_frame_stats"], ensure_ascii=False, indent=2))
    print("[recent_diag_stats]")
    print(json.dumps(report["recent_diag_stats"], ensure_ascii=False, indent=2))

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
