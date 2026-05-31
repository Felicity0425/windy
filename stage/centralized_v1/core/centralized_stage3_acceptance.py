"""Acceptance checks for centralized_v1 Stage3 payload-only outputs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_STAGE2_SUMMARY = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json"
)
DEFAULT_STAGE3_SUMMARY = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json"
)
DEFAULT_OUT_DIR = DEFAULT_STAGE3_SUMMARY.parent / "acceptance"

EXPECTED_PAYLOAD_ROLE = "stage4_strict_holdout_candidates_only"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _summary_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"metric": "status", "value": report["status"]},
        {"metric": "stage2_rows", "value": report["stage2_rows"]},
        {"metric": "stage3_rows", "value": report["stage3_rows"]},
        {"metric": "expected_frames", "value": report["expected_frames"]},
        {"metric": "time_set_match", "value": report["time_set_match"]},
        {"metric": "missing_agent_paths", "value": report["missing_agent_paths"]},
        {"metric": "missing_multimodal_paths", "value": report["missing_multimodal_paths"]},
        {"metric": "payload_role_failures", "value": report["payload_role_failures"]},
        {"metric": "label_count_mismatches", "value": report["label_count_mismatches"]},
        {"metric": "failure_count", "value": len(report["failures"])},
    ]
    for key, value in report["label_candidate_strata"].items():
        rows.append({"metric": f"label_candidate_strata.{key}", "value": value})
    for key, value in report["flag_counts"].items():
        rows.append({"metric": f"flag_counts.{key}", "value": value})
    return rows


def _write_md(path: Path, report: dict[str, Any]) -> None:
    strata = report["label_candidate_strata"]
    lines = [
        "# Stage3 Payload-Only Acceptance",
        "",
        f"- status: `{report['status']}`",
        f"- Stage2 summary: `{report['stage2_summary']}`",
        f"- Stage3 summary: `{report['stage3_summary']}`",
        f"- Stage2 rows: `{report['stage2_rows']}`",
        f"- Stage3 rows: `{report['stage3_rows']}`",
        f"- expected frames: `{report['expected_frames']}`",
        f"- Stage2/Stage3 time set match: `{report['time_set_match']}`",
        "",
        "## Payload-Only Flags",
        "",
        "| flag | count matching expected |",
        "| --- | ---: |",
    ]
    for key, value in report["flag_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Label Candidate Strata",
            "",
            "| stratum | frames |",
            "| --- | ---: |",
            f"| `holdout_candidate_frames` | {strata['holdout_candidate_frames']} |",
            f"| `no_holdout_frames` | {strata['no_holdout_frames']} |",
            f"| `single_candidate_pressure_frames` | {strata['single_candidate_pressure_frames']} |",
            f"| `multi_candidate_frames` | {strata['multi_candidate_frames']} |",
            "",
            "## Path And Payload Checks",
            "",
            f"- missing `agent_path`: `{report['missing_agent_paths']}`",
            f"- missing `multimodal_vox_path`: `{report['missing_multimodal_paths']}`",
            f"- payload role failures: `{report['payload_role_failures']}`",
            f"- label count mismatches: `{report['label_count_mismatches']}`",
            "",
            "The expected role is nested at `ground_center_payload.label_candidates.role`.",
        ]
    )
    if report["failures"]:
        lines.extend(["", "## Failures", "", "| section | time_str | field | expected | actual |", "| --- | --- | --- | --- | --- |"])
        for row in report["failures"][:50]:
            lines.append(
                f"| `{row.get('section', '')}` | `{row.get('time_str', '')}` | `{row.get('field', '')}` | "
                f"`{row.get('expected', '')}` | `{row.get('actual', '')}` |"
            )
        if len(report["failures"]) > 50:
            lines.append(f"| `truncated` |  |  |  | `{len(report['failures']) - 50} additional failures` |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_acceptance(stage2_summary: Path, stage3_summary: Path, expected_frames: int) -> dict[str, Any]:
    stage2_rows = _load_json(stage2_summary)
    stage3_rows = _load_json(stage3_summary)
    failures: list[dict[str, Any]] = []

    stage2_times = {str(row.get("time_str")) for row in stage2_rows}
    stage3_times = {str(row.get("time_str")) for row in stage3_rows}
    if len(stage2_rows) != expected_frames:
        failures.append({"section": "summary", "time_str": "", "field": "stage2_rows", "expected": expected_frames, "actual": len(stage2_rows)})
    if len(stage3_rows) != expected_frames:
        failures.append({"section": "summary", "time_str": "", "field": "stage3_rows", "expected": expected_frames, "actual": len(stage3_rows)})
    if stage2_times != stage3_times:
        failures.append(
            {
                "section": "summary",
                "time_str": "",
                "field": "time_str_set",
                "expected": "Stage2 and Stage3 sets equal",
                "actual": f"missing_from_stage3={len(stage2_times - stage3_times)}, extra_in_stage3={len(stage3_times - stage2_times)}",
            }
        )

    expected_flags = {
        "agent_mode": "none",
        "agent_builder_enabled": False,
        "no_air_to_air": True,
        "no_comm_distance_filter": True,
        "stage4_target_voxel_localization_deferred": True,
    }
    flag_counts = {key: 0 for key in expected_flags}
    label_counts = Counter()
    role_counts = Counter()
    missing_agent_paths = 0
    missing_multimodal_paths = 0
    payload_role_failures = 0
    label_count_mismatches = 0

    for row in stage3_rows:
        time_str = str(row.get("time_str", ""))
        label_count = _as_int(row.get("label_candidate_count"))
        label_counts["holdout_candidate_frames" if label_count > 0 else "no_holdout_frames"] += 1
        if label_count == 1:
            label_counts["single_candidate_pressure_frames"] += 1
        if label_count >= 2:
            label_counts["multi_candidate_frames"] += 1

        for key, expected in expected_flags.items():
            actual = row.get(key)
            ok = str(actual) == expected if isinstance(expected, str) else _as_bool(actual) == expected
            if ok:
                flag_counts[key] += 1
            else:
                failures.append({"section": "summary_flags", "time_str": time_str, "field": key, "expected": expected, "actual": actual})

        agent_path = Path(str(row.get("agent_path", "")))
        if not agent_path.exists():
            missing_agent_paths += 1
            failures.append({"section": "paths", "time_str": time_str, "field": "agent_path", "expected": "exists", "actual": str(agent_path)})
            continue
        multimodal_path = Path(str(row.get("multimodal_vox_path", "")))
        if not multimodal_path.exists():
            missing_multimodal_paths += 1
            failures.append({"section": "paths", "time_str": time_str, "field": "multimodal_vox_path", "expected": "exists", "actual": str(multimodal_path)})

        try:
            payload = _load_json(agent_path)
        except (OSError, json.JSONDecodeError) as exc:
            failures.append({"section": "payload", "time_str": time_str, "field": "read_json", "expected": "valid JSON", "actual": str(exc)})
            continue
        group = payload.get("ground_center_payload", {}).get("label_candidates", {})
        role = group.get("role")
        role_counts[str(role)] += 1
        if role != EXPECTED_PAYLOAD_ROLE:
            payload_role_failures += 1
            failures.append({"section": "payload", "time_str": time_str, "field": "label_candidates.role", "expected": EXPECTED_PAYLOAD_ROLE, "actual": role})
        payload_label_count = _as_int(group.get("count"))
        if payload_label_count != label_count:
            label_count_mismatches += 1
            failures.append({"section": "payload", "time_str": time_str, "field": "label_candidates.count", "expected": label_count, "actual": payload_label_count})

    report = {
        "status": "PASS" if not failures else "FAIL",
        "stage2_summary": str(stage2_summary),
        "stage3_summary": str(stage3_summary),
        "expected_frames": int(expected_frames),
        "stage2_rows": len(stage2_rows),
        "stage3_rows": len(stage3_rows),
        "time_set_match": stage2_times == stage3_times,
        "flag_counts": flag_counts,
        "label_candidate_strata": {
            "holdout_candidate_frames": int(label_counts["holdout_candidate_frames"]),
            "no_holdout_frames": int(label_counts["no_holdout_frames"]),
            "single_candidate_pressure_frames": int(label_counts["single_candidate_pressure_frames"]),
            "multi_candidate_frames": int(label_counts["multi_candidate_frames"]),
        },
        "payload_role_counts": dict(role_counts),
        "missing_agent_paths": int(missing_agent_paths),
        "missing_multimodal_paths": int(missing_multimodal_paths),
        "payload_role_failures": int(payload_role_failures),
        "label_count_mismatches": int(label_count_mismatches),
        "failures": failures,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate centralized_v1 Stage3 payload-only output.")
    parser.add_argument("--stage2-summary", type=Path, default=DEFAULT_STAGE2_SUMMARY)
    parser.add_argument("--stage3-summary", type=Path, default=DEFAULT_STAGE3_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--expected-frames", type=int, default=7395)
    args = parser.parse_args()

    report = run_acceptance(args.stage2_summary, args.stage3_summary, int(args.expected_frames))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "stage3_payload_only_acceptance.json"
    csv_path = args.out_dir / "stage3_payload_only_acceptance.csv"
    failures_csv_path = args.out_dir / "stage3_payload_only_acceptance_failures.csv"
    md_path = args.out_dir / "stage3_payload_only_acceptance.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(csv_path, _summary_rows(report), ["metric", "value"])
    _write_csv(failures_csv_path, report["failures"], ["section", "time_str", "field", "expected", "actual"])
    _write_md(md_path, report)
    print(json_path)
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
