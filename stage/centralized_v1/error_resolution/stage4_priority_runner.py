"""Sequential Stage4 error-resolution runner with guarded promotion.

This runner follows the priority order in the 2026-06-02 Stage4 error plan.
It reruns the current seed candidates with a clean worker count, applies one
phase at a time, compares every candidate against the currently promoted active
run, and only promotes a phase when its guardrail passes.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

DEFAULT_PYTHON = Path("/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python")
DEFAULT_STAGE2_SUMMARY = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json")
DEFAULT_STAGE3_SUMMARY = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json")
DEFAULT_FRAME_TIMES_FILE = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/analysis/"
    "frame_times_200_holdout_seed20260531.txt"
)
DEFAULT_OUT_ROOT = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_priority_20260602_25w")
PYTHON_EXE = DEFAULT_PYTHON

SENSITIVITY_SCRIPT = ROOT_DIR / "stage/centralized_v1/core/centralized_stage4_sensitivity.py"
PAIRWISE_SCRIPT = ROOT_DIR / "stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py"
DECOMPOSITION_SCRIPT = ROOT_DIR / "stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py"


@dataclass(frozen=True)
class VariantSpec:
    slug: str
    description: str
    args_patch: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PhaseSpec:
    key: str
    source: str
    description: str
    variants: list[VariantSpec] = field(default_factory=list)
    analysis_only: bool = False


@dataclass
class RunState:
    label: str
    args: dict[str, Any]
    metrics_dir: Path


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _to_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _default_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("POLARS_MAX_THREADS", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    return env


def _base_timepower15_args(stage2_summary: Path, stage3_summary: Path, frame_times_file: Path, num_workers: int) -> dict[str, Any]:
    return {
        "stage2-summary": stage2_summary,
        "stage3-summary": stage3_summary,
        "frame-times-file": frame_times_file,
        "sample-count": 0,
        "param-grid": "8,4,2,1",
        "kernels": "gaussian",
        "confidence-mode": "diagnostic_weighted",
        "physics-constraint-mode": "pydda_3dvar_proxy",
        "current-weight-boost": 2.0,
        "context-weight-scale": 0.5,
        "context-time-conf-power": 1.5,
        "role-conflict-mode": "current_priority_adaptive",
        "conflict-speed-threshold-mps": 12.0,
        "conflict-context-factor": 0.25,
        "progress-interval-seconds": 30,
        "num-workers": num_workers,
    }


def _base_adaptive_v3_args(stage2_summary: Path, stage3_summary: Path, frame_times_file: Path, num_workers: int) -> dict[str, Any]:
    args = _base_timepower15_args(stage2_summary, stage3_summary, frame_times_file, num_workers)
    args.update(
        {
            "localization-policy": "diagnostic_adaptive_v3",
            "localization-candidate-grid": "8:4,10:5",
        }
    )
    return args


def _priority_phases() -> list[PhaseSpec]:
    return [
        PhaseSpec(
            key="vertical_structure",
            source="vertical_structure",
            description="Preserve strong vertical layers without sacrificing the current adaptive_v3 gains.",
            variants=[
                VariantSpec(
                    slug="adaptive_v3_vertical_preserve",
                    description="Enable preserve_strong_layers on top of the current active candidate.",
                    args_patch={
                        "vertical-risk-mode": "preserve_strong_layers",
                        "vertical-gradient-preserve-weight": 0.12,
                        "vertical-context-mismatch-damping": 0.35,
                    },
                )
            ],
        ),
        PhaseSpec(
            key="representation_error",
            source="representation_error",
            description="Write neighborhood-verification diagnostics for the current active candidate.",
            analysis_only=True,
        ),
        PhaseSpec(
            key="sparse_support",
            source="sparse_support",
            description="Try the support-aware frame/regime localization policy and widen only in fresh sparse-support regimes.",
            variants=[
                VariantSpec(
                    slug="adaptive_regime_v4",
                    description="Promote the new support-aware regime policy only if low-support and mid-error bands improve safely.",
                    args_patch={
                        "localization-policy": "diagnostic_adaptive_regime_v4",
                        "localization-candidate-grid": "8:4,10:5,12:6",
                    },
                )
            ],
        ),
        PhaseSpec(
            key="role_conflict",
            source="role_conflict",
            description="Conservatively sweep the current/context conflict threshold.",
            variants=[
                VariantSpec("role_threshold_10", "Lower conflict threshold to 10 m/s.", {"conflict-speed-threshold-mps": 10.0}),
                VariantSpec("role_threshold_16", "Raise conflict threshold to 16 m/s.", {"conflict-speed-threshold-mps": 16.0}),
            ],
        ),
        PhaseSpec(
            key="temporal_weighting",
            source="temporal_weighting",
            description="Tune the context time-confidence decay after role-conflict handling is settled.",
            variants=[
                VariantSpec("timepower_1_0", "Use a gentler context time-confidence decay.", {"context-time-conf-power": 1.0}),
                VariantSpec("timepower_2_0", "Use a sharper context time-confidence decay.", {"context-time-conf-power": 2.0}),
            ],
        ),
        PhaseSpec(
            key="tail_qc",
            source="tail_qc",
            description="Write tail-risk diagnostics for the current active candidate.",
            analysis_only=True,
        ),
        PhaseSpec(
            key="localization",
            source="localization",
            description="Final localization pass with regime-aware widening and optional vertical preservation kept together.",
            variants=[
                VariantSpec(
                    slug="adaptive_regime_v4_vertical_preserve",
                    description="Combine the regime-aware policy with vertical preservation in one guarded final pass.",
                    args_patch={
                        "localization-policy": "diagnostic_adaptive_regime_v4",
                        "localization-candidate-grid": "8:4,10:5,12:6",
                        "vertical-risk-mode": "preserve_strong_layers",
                        "vertical-gradient-preserve-weight": 0.12,
                        "vertical-context-mismatch-damping": 0.35,
                    },
                )
            ],
        ),
    ]


def _build_cli(script: Path, args_map: dict[str, Any], out_dir: Path) -> list[str]:
    cmd = [str(PYTHON_EXE), str(script)]
    ordered = dict(args_map)
    ordered["out-dir"] = out_dir
    for key, value in ordered.items():
        if value is None:
            continue
        cmd.extend([f"--{key}", str(value)])
    return cmd


def _run_logged(cmd: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(cmd, cwd=str(ROOT_DIR), env=_default_env(), stdout=log, stderr=subprocess.STDOUT, check=True, text=True)


def _run_metrics(label: str, args_map: dict[str, Any], out_dir: Path) -> RunState:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = _build_cli(SENSITIVITY_SCRIPT, args_map, out_dir)
    _run_logged(cmd, out_dir / f"{label}_run.log")
    _write_json(out_dir / f"{label}_command.json", {"cmd": cmd, "args": {k: str(v) for k, v in dict(args_map, **{'out-dir': out_dir}).items()}})
    return RunState(label=label, args=dict(args_map), metrics_dir=out_dir)


def _run_pairwise(baseline: RunState, candidate: RunState, out_dir: Path, prefix: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_csv = baseline.metrics_dir / "stage4_localization_sensitivity.csv"
    candidate_csv = candidate.metrics_dir / "stage4_localization_sensitivity.csv"
    baseline_point_csv = baseline.metrics_dir / "stage4_point_departures.csv"
    candidate_point_csv = candidate.metrics_dir / "stage4_point_departures.csv"

    pairwise_cmd = [
        str(PYTHON_EXE),
        str(PAIRWISE_SCRIPT),
        "--baseline-csv",
        str(baseline_csv),
        "--candidate-csv",
        str(candidate_csv),
        "--baseline-point-csv",
        str(baseline_point_csv),
        "--candidate-point-csv",
        str(candidate_point_csv),
        "--baseline-label",
        baseline.label,
        "--candidate-label",
        candidate.label,
        "--out-dir",
        str(out_dir),
        "--out-prefix",
        prefix,
        "--top-n",
        "30",
    ]
    _run_logged(pairwise_cmd, out_dir / f"{prefix}_pairwise.log")

    decomp_dir = out_dir / "error_source_decomposition"
    decomp_dir.mkdir(parents=True, exist_ok=True)
    decomp_cmd = [
        str(PYTHON_EXE),
        str(DECOMPOSITION_SCRIPT),
        "--baseline-csv",
        str(baseline_csv),
        "--candidate-csv",
        str(candidate_csv),
        "--baseline-point-csv",
        str(baseline_point_csv),
        "--candidate-point-csv",
        str(candidate_point_csv),
        "--baseline-label",
        baseline.label,
        "--candidate-label",
        candidate.label,
        "--out-dir",
        str(decomp_dir),
        "--out-prefix",
        f"{prefix}_error_sources",
        "--top-tail-n",
        "50",
    ]
    _run_logged(decomp_cmd, decomp_dir / f"{prefix}_error_sources.log")
    return {
        "summary_csv": out_dir / f"{prefix}_summary.csv",
        "band_csv": out_dir / f"{prefix}_baseline_rmse_bands.csv",
        "paper_summary_csv": out_dir / f"{prefix}_paper_summary.csv",
        "paper_height_csv": out_dir / f"{prefix}_paper_height_bins.csv",
        "point_csv": out_dir / f"{prefix}_paper_point_departures.csv",
        "source_priority_csv": decomp_dir / f"{prefix}_error_sources_source_priority.csv",
        "tail_audit_csv": decomp_dir / f"{prefix}_error_sources_tail_audit.csv",
        "action_plan_csv": decomp_dir / f"{prefix}_error_sources_action_plan.csv",
        "markdown": out_dir / f"{prefix}.md",
    }


def _load_compare_bundle(paths: dict[str, Path], baseline_label: str, candidate_label: str) -> dict[str, Any]:
    summary_rows = _read_csv_rows(paths["summary_csv"])
    band_rows = _read_csv_rows(paths["band_csv"])
    paper_rows = _read_csv_rows(paths["paper_summary_csv"])
    height_rows = _read_csv_rows(paths["paper_height_csv"])
    source_rows = _read_csv_rows(paths["source_priority_csv"])
    return {
        "summary": summary_rows[0] if summary_rows else {},
        "bands": {row["group"]: row for row in band_rows if row.get("group")},
        "paper_summary": {(row["group"], row["method"]): row for row in paper_rows if row.get("group") and row.get("method")},
        "paper_height": {(row["group"], row["method"]): row for row in height_rows if row.get("group") and row.get("method")},
        "source_priority": {row["source"]: row for row in source_rows if row.get("source")},
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "paths": {key: str(value) for key, value in paths.items()},
    }


def _band_delta(bundle: dict[str, Any], group: str) -> float:
    row = bundle["bands"].get(group, {})
    baseline_label = bundle["baseline_label"]
    candidate_label = bundle["candidate_label"]
    return _to_float(row, f"{candidate_label}_frame_mean_rmse") - _to_float(row, f"{baseline_label}_frame_mean_rmse")


def _height_value(bundle: dict[str, Any], group: str, label: str, key: str) -> float:
    return _to_float(bundle["paper_height"].get((group, label), {}), key, float("nan"))


def _priority_score(bundle: dict[str, Any], source: str) -> float:
    return _to_float(bundle["source_priority"].get(source, {}), "priority_score", float("nan"))


def _guardrail(bundle: dict[str, Any], phase_key: str) -> tuple[bool, list[str], float]:
    summary = bundle["summary"]
    baseline_label = bundle["baseline_label"]
    candidate_label = bundle["candidate_label"]
    baseline_weighted = _to_float(summary, f"{baseline_label}_weighted_rmse", float("inf"))
    candidate_weighted = _to_float(summary, f"{candidate_label}_weighted_rmse", float("inf"))
    candidate_frame = _to_float(summary, f"{candidate_label}_frame_mean_rmse", float("inf"))
    candidate_p95 = _to_float(summary, "p95_candidate_rmse", float("inf"))
    baseline_p95 = _to_float(summary, "p95_baseline_rmse", float("inf"))
    candidate_p99 = _to_float(summary, "p99_candidate_rmse", float("inf"))
    baseline_p99 = _to_float(summary, "p99_baseline_rmse", float("inf"))
    leakage_ok = str(summary.get("all_strict_holdout_no_leakage", "False")) == "True"
    motion_ok = str(summary.get("any_motion_used_as_wind", "True")) == "False"
    low_band_delta = _band_delta(bundle, "baseline_rmse_le6")
    mid_band_delta = _band_delta(bundle, "baseline_rmse_10_20")
    high_band_delta = _band_delta(bundle, "baseline_rmse_gt20")
    base_12km = _height_value(bundle, "12km+", baseline_label, "vector_rmse_mps")
    cand_12km = _height_value(bundle, "12km+", candidate_label, "vector_rmse_mps")
    base_9_12 = _height_value(bundle, "9-12km", baseline_label, "vector_rmse_mps")
    cand_9_12 = _height_value(bundle, "9-12km", candidate_label, "vector_rmse_mps")

    checks = [leakage_ok, motion_ok]
    notes = [
        f"weighted_rmse {baseline_label}->{candidate_label}: {baseline_weighted:.6f} -> {candidate_weighted:.6f}",
        f"low_band_delta={low_band_delta:.6f}, mid_band_delta={mid_band_delta:.6f}, high_band_delta={high_band_delta:.6f}",
        f"12km+ {base_12km:.6f} -> {cand_12km:.6f}, 9-12km {base_9_12:.6f} -> {cand_9_12:.6f}",
        f"p95 {baseline_p95:.6f} -> {candidate_p95:.6f}, p99 {baseline_p99:.6f} -> {candidate_p99:.6f}",
    ]

    if phase_key == "seed_adaptive_v3":
        checks.extend([candidate_weighted <= baseline_weighted, candidate_frame <= _to_float(summary, f"{baseline_label}_frame_mean_rmse", float("inf"))])
    elif phase_key == "vertical_structure":
        checks.extend(
            [
                candidate_weighted <= baseline_weighted + 0.10,
                cand_12km <= base_12km + 1e-6,
                cand_9_12 <= base_9_12 + 0.20,
                candidate_p95 <= baseline_p95 + 0.10,
            ]
        )
    elif phase_key == "sparse_support":
        checks.extend(
            [
                candidate_weighted <= baseline_weighted + 0.05,
                low_band_delta <= 0.05,
                mid_band_delta <= 0.0,
                candidate_p99 <= baseline_p99 + 0.10,
            ]
        )
    elif phase_key == "role_conflict":
        checks.extend(
            [
                candidate_weighted <= baseline_weighted + 0.05,
                low_band_delta <= 0.05,
                mid_band_delta <= 0.10,
            ]
        )
    elif phase_key == "temporal_weighting":
        checks.extend(
            [
                candidate_weighted <= baseline_weighted + 0.05,
                candidate_p95 <= baseline_p95 + 0.10,
                candidate_p99 <= baseline_p99 + 0.10,
            ]
        )
    elif phase_key == "localization":
        checks.extend(
            [
                candidate_weighted <= baseline_weighted + 0.02,
                low_band_delta <= 0.05,
                mid_band_delta <= 0.0,
                candidate_p99 <= baseline_p99 + 0.10,
                cand_12km <= base_12km + 0.20,
            ]
        )
    else:
        checks.append(True)

    score = (baseline_weighted - candidate_weighted) * 1000.0
    return all(checks), notes, score


def _ensure_reference_compare(reference: RunState, active: RunState, out_dir: Path, prefix: str) -> dict[str, Any]:
    candidate = active
    if reference.label == active.label:
        candidate = RunState(label=f"{active.label}_active", args=dict(active.args), metrics_dir=active.metrics_dir)
    paths = _run_pairwise(reference, candidate, out_dir, prefix)
    return _load_compare_bundle(paths, reference.label, candidate.label)


def _write_representation_report(path: Path, bundle: dict[str, Any]) -> None:
    candidate_label = bundle["candidate_label"]
    all_row = bundle["paper_summary"].get(("all_holdout_points", candidate_label), {})
    rep_score = _priority_score(bundle, "representation_error")
    lines = [
        "# Representation Error Diagnostics",
        "",
        f"Active candidate: `{candidate_label}`",
        f"Representation priority score: `{rep_score:.6f}`",
        "",
        f"- Mean neighborhood-min vector error: `{_to_float(all_row, 'mean_neighbor_min_vector_error_mps', float('nan')):.6f}` m/s",
        f"- Mean neighborhood-weighted vector error: `{_to_float(all_row, 'mean_neighbor_weighted_vector_error_mps', float('nan')):.6f}` m/s",
        f"- Mean point-minus-neighborhood-min gap: `{_to_float(all_row, 'mean_representativeness_gap_point_minus_min_mps', float('nan')):.6f}` m/s",
        "",
        "Interpretation:",
        "- The new neighborhood diagnostics help separate local representativeness mismatch from pure aircraft observation error.",
        "- This phase is diagnostic-only; it does not auto-promote a new active reconstruction config.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_tail_report(path: Path, bundle: dict[str, Any]) -> None:
    candidate_label = bundle["candidate_label"]
    summary = bundle["summary"]
    tail_score = _priority_score(bundle, "tail_qc")
    lines = [
        "# Tail QC Diagnostics",
        "",
        f"Active candidate: `{candidate_label}`",
        f"Tail priority score: `{tail_score:.6f}`",
        "",
        f"- Median RMSE: `{_to_float(summary, f'{candidate_label}_median_rmse', float('nan')):.6f}` m/s",
        f"- P95 RMSE: `{_to_float(summary, 'p95_candidate_rmse', float('nan')):.6f}` m/s",
        f"- P99 RMSE: `{_to_float(summary, 'p99_candidate_rmse', float('nan')):.6f}` m/s",
        f"- Trimmed RMSE P95: `{_to_float(summary, f'{candidate_label}_trimmed_rmse_p95', float('nan')):.6f}` m/s",
        "",
        "Interpretation:",
        "- Tail audit remains separate from mean-RMSE tuning.",
        "- This phase is diagnostic-only; it does not auto-promote a new active reconstruction config.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_journal(path: Path, journal: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage4 Error Resolution Journal",
        "",
        "| phase | source | decision | active_after | note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in journal:
        lines.append(
            f"| `{row['phase']}` | `{row['source']}` | `{row['decision']}` | "
            f"`{row['active_after']}` | {row['note']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run guarded sequential Stage4 error-resolution experiments.")
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--stage2-summary", type=Path, default=DEFAULT_STAGE2_SUMMARY)
    parser.add_argument("--stage3-summary", type=Path, default=DEFAULT_STAGE3_SUMMARY)
    parser.add_argument("--frame-times-file", type=Path, default=DEFAULT_FRAME_TIMES_FILE)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--num-workers", type=int, default=25)
    args = parser.parse_args()

    global PYTHON_EXE
    PYTHON_EXE = args.python

    args.out_root.mkdir(parents=True, exist_ok=True)
    runs_root = args.out_root / "runs"
    analysis_root = args.out_root / "analysis"
    reports_root = args.out_root / "reports"
    runs_root.mkdir(parents=True, exist_ok=True)
    analysis_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    timepower15 = _run_metrics(
        "timepower15",
        _base_timepower15_args(args.stage2_summary, args.stage3_summary, args.frame_times_file, args.num_workers),
        runs_root / "00_timepower15",
    )
    adaptive_v3_seed = _run_metrics(
        "adaptive_v3_seed",
        _base_adaptive_v3_args(args.stage2_summary, args.stage3_summary, args.frame_times_file, args.num_workers),
        runs_root / "01_adaptive_v3_seed",
    )

    seed_paths = _run_pairwise(timepower15, adaptive_v3_seed, analysis_root / "01_seed_compare", "timepower15_vs_adaptive_v3_seed")
    seed_bundle = _load_compare_bundle(seed_paths, timepower15.label, adaptive_v3_seed.label)
    seed_pass, seed_notes, _seed_score = _guardrail(seed_bundle, "seed_adaptive_v3")
    active = adaptive_v3_seed if seed_pass else timepower15

    journal: list[dict[str, Any]] = [
        {
            "phase": "seed_adaptive_v3",
            "source": "bootstrap",
            "decision": "promote" if seed_pass else "fallback",
            "active_after": active.label,
            "note": "; ".join(seed_notes),
            "compare_paths": seed_bundle["paths"],
        }
    ]

    phase_counter = 2
    for phase in _priority_phases():
        phase_dir = analysis_root / f"{phase_counter:02d}_{phase.key}"
        phase_dir.mkdir(parents=True, exist_ok=True)
        if phase.analysis_only:
            ref_bundle = _ensure_reference_compare(timepower15, active, phase_dir / "reference_compare", f"timepower15_vs_{active.label}")
            if phase.key == "representation_error":
                _write_representation_report(phase_dir / "representation_error_report.md", ref_bundle)
            elif phase.key == "tail_qc":
                _write_tail_report(phase_dir / "tail_qc_report.md", ref_bundle)
            journal.append(
                {
                    "phase": phase.key,
                    "source": phase.source,
                    "decision": "diagnostic_only",
                    "active_after": active.label,
                    "note": phase.description,
                    "compare_paths": ref_bundle["paths"],
                }
            )
            phase_counter += 1
            continue

        promoted_variant: RunState | None = None
        promoted_bundle: dict[str, Any] | None = None
        promoted_notes: list[str] = []
        best_score = float("-inf")

        for variant in phase.variants:
            candidate_args = dict(active.args)
            candidate_args.update(variant.args_patch)
            run_dir = runs_root / f"{phase_counter:02d}_{phase.key}_{variant.slug}"
            candidate = _run_metrics(variant.slug, candidate_args, run_dir)
            compare_dir = phase_dir / variant.slug
            compare_paths = _run_pairwise(active, candidate, compare_dir, f"{active.label}_vs_{variant.slug}")
            bundle = _load_compare_bundle(compare_paths, active.label, candidate.label)
            passes, notes, score = _guardrail(bundle, phase.key)
            notes.insert(0, variant.description)
            if passes and score > best_score:
                promoted_variant = candidate
                promoted_bundle = bundle
                promoted_notes = notes
                best_score = score

        if promoted_variant is not None and promoted_bundle is not None:
            active = promoted_variant
            decision = "promote"
            note = "; ".join(promoted_notes)
            compare_paths = promoted_bundle["paths"]
        else:
            decision = "keep_previous"
            note = f"No {phase.key} candidate passed the guardrail; active candidate stays `{active.label}`."
            compare_paths = {}

        journal.append(
            {
                "phase": phase.key,
                "source": phase.source,
                "decision": decision,
                "active_after": active.label,
                "note": note,
                "compare_paths": compare_paths,
            }
        )
        phase_counter += 1

    _write_json(reports_root / "phase_journal.json", journal)
    _write_journal(reports_root / "phase_journal.md", journal)
    _write_json(
        reports_root / "final_active_candidate.json",
        {
            "active_label": active.label,
            "metrics_dir": str(active.metrics_dir),
            "args": {key: str(value) for key, value in active.args.items()},
        },
    )
    print(active.metrics_dir)


if __name__ == "__main__":
    main()
