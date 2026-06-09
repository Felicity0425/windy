"""Select a truth-free residual gate on validation, then lock-test it.

This is a point-level Stage5 report tool. It does not train a model and it does
not promote a full-field reconstruction. Candidate gate rules may use Stage4
and report features, but never truth/error columns.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))


@dataclass(frozen=True)
class RuleSpec:
    name: str
    description: str
    complexity: int
    mask_fn: Callable[[pd.DataFrame], pd.Series]


def _load_features(dataset_dir: Path) -> pd.DataFrame:
    schema = json.loads((dataset_dir / "feature_schema.json").read_text(encoding="utf-8"))
    feature_names = list(schema["feature_names"])
    rows: list[pd.DataFrame] = []
    for split in ("train", "val", "test"):
        with np.load(dataset_dir / f"features_{split}.npz", allow_pickle=False) as data:
            frame = pd.DataFrame(data["x"], columns=feature_names)
            frame["row_id"] = data["row_id"].astype(np.int64)
            frame["feature_split"] = split
            rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def _num(df: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce").fillna(default).astype("float64")


def _bool_series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").fillna(0.0).astype("float64") > 0.5


def _build_rules() -> list[RuleSpec]:
    rules: list[RuleSpec] = []

    def add(name: str, description: str, complexity: int, fn: Callable[[pd.DataFrame], pd.Series]) -> None:
        rules.append(RuleSpec(name=name, description=description, complexity=complexity, mask_fn=fn))

    add("all_points", "Enable the residual correction at every point.", 1, lambda df: pd.Series(True, index=df.index))
    add(
        "not_pred_light",
        "Enable only where Stage4 predicted wind is not light.",
        1,
        lambda df: ~_bool_series(_num(df, "pred_light_wind_flag", 0.0)),
    )
    for speed in (15.0, 20.0, 30.0, 45.0, 60.0):
        add(
            f"pred_speed_ge_{int(speed)}",
            f"Enable only where Stage4 predicted speed >= {speed:.0f} m/s.",
            1,
            lambda df, speed=speed: _num(df, "pred_speed", 0.0) >= speed,
        )
        add(
            f"pred_speed_ge_{int(speed)}_not_light",
            f"Enable where Stage4 predicted speed >= {speed:.0f} m/s and not pred-light.",
            2,
            lambda df, speed=speed: (_num(df, "pred_speed", 0.0) >= speed)
            & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
        )
    for alt in (9000.0, 12000.0):
        add(
            f"alt_ge_{int(alt)}",
            f"Enable only where altitude >= {alt:.0f} m.",
            1,
            lambda df, alt=alt: _num(df, "alt_m", 0.0) >= alt,
        )
        add(
            f"alt_ge_{int(alt)}_not_light",
            f"Enable where altitude >= {alt:.0f} m and not pred-light.",
            2,
            lambda df, alt=alt: (_num(df, "alt_m", 0.0) >= alt)
            & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
        )
    add(
        "high_altitude_not_light",
        "Enable only at high-altitude points and not pred-light.",
        2,
        lambda df: _bool_series(_num(df, "high_altitude_flag", 0.0))
        & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
    )

    for risk in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
        tag = str(risk).replace(".", "p")
        add(
            f"risk_ge_{tag}",
            f"Enable only where representation risk >= {risk:.2f}.",
            1,
            lambda df, risk=risk: _num(df, "representation_risk_score", 0.0) >= risk,
        )
        add(
            f"risk_ge_{tag}_not_light",
            f"Enable where representation risk >= {risk:.2f} and not pred-light.",
            2,
            lambda df, risk=risk: (_num(df, "representation_risk_score", 0.0) >= risk)
            & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
        )
        add(
            f"risk_ge_{tag}_or_pred30_not_light",
            f"Enable where risk >= {risk:.2f} or pred_speed >= 30 m/s, excluding pred-light.",
            3,
            lambda df, risk=risk: (
                (_num(df, "representation_risk_score", 0.0) >= risk)
                | (_num(df, "pred_speed", 0.0) >= 30.0)
            )
            & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
        )
        add(
            f"risk_ge_{tag}_or_pred45_not_light",
            f"Enable where risk >= {risk:.2f} or pred_speed >= 45 m/s, excluding pred-light.",
            3,
            lambda df, risk=risk: (
                (_num(df, "representation_risk_score", 0.0) >= risk)
                | (_num(df, "pred_speed", 0.0) >= 45.0)
            )
            & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
        )
        add(
            f"risk_ge_{tag}_or_alt12_not_light",
            f"Enable where risk >= {risk:.2f} or altitude >= 12 km, excluding pred-light.",
            3,
            lambda df, risk=risk: (
                (_num(df, "representation_risk_score", 0.0) >= risk)
                | (_num(df, "alt_m", 0.0) >= 12000.0)
            )
            & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
        )
    add(
        "risk_0p20_to_0p50_not_light",
        "Enable where 0.20 <= representation risk < 0.50 and not pred-light.",
        3,
        lambda df: (_num(df, "representation_risk_score", 0.0) >= 0.20)
        & (_num(df, "representation_risk_score", 0.0) < 0.50)
        & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
    )
    add(
        "role_gap_ge30_not_light",
        "Enable where nearest role gap >= 30 m/s and not pred-light.",
        2,
        lambda df: (_num(df, "nearest_role_gap_mps", 0.0) >= 30.0)
        & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
    )
    add(
        "sigma_rep_ge10_not_light",
        "Enable where representation sigma proxy >= 10 m/s and not pred-light.",
        2,
        lambda df: (_num(df, "sigma_rep_proxy_mps", 0.0) >= 10.0)
        & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
    )
    add(
        "vertical_gap_ge15_not_light",
        "Enable where vertical gap/jump proxy >= 15 m/s and not pred-light.",
        2,
        lambda df: (
            np.maximum(_num(df, "vertical_speed_gap_mps", 0.0), _num(df, "recon_vertical_jump_mps", 0.0)) >= 15.0
        )
        & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
    )
    for gap in (10.0, 20.0, 30.0):
        add(
            f"vertical_gap_ge{int(gap)}_not_light",
            f"Enable where vertical gap/jump proxy >= {gap:.0f} m/s and not pred-light.",
            2,
            lambda df, gap=gap: (
                np.maximum(_num(df, "vertical_speed_gap_mps", 0.0), _num(df, "recon_vertical_jump_mps", 0.0))
                >= gap
            )
            & (~_bool_series(_num(df, "pred_light_wind_flag", 0.0))),
        )
    return rules


def _profile_accepts(rule_name: str, profile: str) -> bool:
    if profile == "broad":
        return True
    if profile not in {"tail_safe", "narrow_safe"}:
        raise ValueError(f"Unsupported rule profile: {profile}")
    if rule_name in {"all_points", "not_pred_light"}:
        return False
    if rule_name.startswith("alt_ge_") or rule_name == "high_altitude_not_light":
        return False
    if "pred_speed_ge_15" in rule_name or "pred_speed_ge_20" in rule_name or "pred_speed_ge_30" in rule_name:
        return False
    if "or_pred30" in rule_name:
        return False
    if rule_name.startswith("risk_ge_") and not rule_name.endswith("_not_light") and "_or_pred45_not_light" not in rule_name:
        return False
    if profile == "narrow_safe":
        if "_or_pred" in rule_name or "_or_alt" in rule_name:
            return False
        if rule_name.startswith("pred_speed_ge_"):
            return rule_name in {"pred_speed_ge_45_not_light", "pred_speed_ge_60_not_light"}
        if rule_name in {"risk_ge_0p1", "risk_ge_0p1_not_light"} or rule_name.startswith("risk_ge_0p1_or_"):
            return False
        if rule_name.startswith("risk_ge_") and not rule_name.endswith("_not_light"):
            return False
    return True


def _apply_gate(df: pd.DataFrame, enabled: np.ndarray, scale: float) -> pd.DataFrame:
    out = df.copy()
    gate_scale = enabled.astype(np.float64) * float(scale)
    raw_du = _num(out, "candidate_u") - _num(out, "baseline_u")
    raw_dv = _num(out, "candidate_v") - _num(out, "baseline_v")
    out["raw_candidate_u"] = _num(out, "candidate_u")
    out["raw_candidate_v"] = _num(out, "candidate_v")
    out["raw_candidate_vector_error"] = _num(out, "candidate_vector_error")
    out["gate_selector_enabled"] = enabled.astype(np.int8)
    out["gate_selector_scale"] = gate_scale
    out["candidate_u"] = _num(out, "baseline_u") + gate_scale * raw_du
    out["candidate_v"] = _num(out, "baseline_v") + gate_scale * raw_dv
    gt_u = _num(out, "gt_u")
    gt_v = _num(out, "gt_v")
    base_err = np.sqrt((_num(out, "baseline_u") - gt_u) ** 2 + (_num(out, "baseline_v") - gt_v) ** 2)
    cand_err = np.sqrt((_num(out, "candidate_u") - gt_u) ** 2 + (_num(out, "candidate_v") - gt_v) ** 2)
    gt_speed = _num(out, "gt_speed")
    out["baseline_vector_error"] = base_err
    out["candidate_vector_error"] = cand_err
    out["delta_vector_error"] = cand_err - base_err
    out["floor10_relative_error"] = cand_err / np.maximum(gt_speed, 10.0)
    out["relative_error_ratio"] = cand_err / np.maximum(gt_speed, 1e-6)
    return out


def _metrics(group: pd.DataFrame) -> dict[str, Any]:
    base = _num(group, "baseline_vector_error").to_numpy(dtype=np.float64)
    cand = _num(group, "candidate_vector_error").to_numpy(dtype=np.float64)
    gt_speed = _num(group, "gt_speed").to_numpy(dtype=np.float64)
    light = (gt_speed >= 5.0) & (gt_speed < 15.0)
    light_mod = (gt_speed >= 5.0) & (gt_speed < 30.0)
    rel = cand / np.maximum(gt_speed, 1e-6)
    delta = cand - base

    def rmse(values: np.ndarray) -> float:
        return float(np.sqrt(np.mean(values**2))) if values.size else 0.0

    def mean(values: np.ndarray) -> float:
        return float(np.mean(values)) if values.size else 0.0

    def q(values: np.ndarray, quantile: float) -> float:
        return float(np.quantile(values, quantile)) if values.size else 0.0

    return {
        "points": int(len(group)),
        "enabled_points": int(np.count_nonzero(_num(group, "gate_selector_enabled").to_numpy(dtype=np.float64) > 0.5))
        if "gate_selector_enabled" in group.columns
        else 0,
        "baseline_rmse": rmse(base),
        "candidate_rmse": rmse(cand),
        "delta_rmse": rmse(cand) - rmse(base),
        "baseline_mae": mean(base),
        "candidate_mae": mean(cand),
        "delta_mae": mean(cand) - mean(base),
        "baseline_p95": q(base, 0.95),
        "candidate_p95": q(cand, 0.95),
        "delta_p95": q(cand, 0.95) - q(base, 0.95),
        "baseline_p99": q(base, 0.99),
        "candidate_p99": q(cand, 0.99),
        "delta_p99": q(cand, 0.99) - q(base, 0.99),
        "baseline_light_rmse": rmse(base[light]),
        "candidate_light_rmse": rmse(cand[light]),
        "delta_light_rmse": rmse(cand[light]) - rmse(base[light]),
        "baseline_light_mae": mean(base[light]),
        "candidate_light_mae": mean(cand[light]),
        "delta_light_mae": mean(cand[light]) - mean(base[light]),
        "baseline_floor10_relative_mae": mean(base / np.maximum(gt_speed, 10.0)),
        "candidate_floor10_relative_mae": mean(cand / np.maximum(gt_speed, 10.0)),
        "delta_floor10_relative_mae": mean(cand / np.maximum(gt_speed, 10.0)) - mean(base / np.maximum(gt_speed, 10.0)),
        "baseline_high_error_ge30_count": int(np.count_nonzero(base >= 30.0)),
        "candidate_high_error_ge30_count": int(np.count_nonzero(cand >= 30.0)),
        "new_light_moderate_relative_tail_failures": int(np.count_nonzero(light_mod & (rel > 2.0) & (delta > 5.0))),
        "improved_points": int(np.count_nonzero(delta < -1e-6)),
        "worsened_points": int(np.count_nonzero(delta > 1e-6)),
    }


def _passes(row: dict[str, Any], tolerance: float) -> dict[str, bool]:
    tol = float(tolerance)
    return {
        "weighted_rmse_not_worse": row["candidate_rmse"] <= row["baseline_rmse"] + tol,
        "p95_not_worse": row["candidate_p95"] <= row["baseline_p95"] + tol,
        "p99_not_worse": row["candidate_p99"] <= row["baseline_p99"] + tol,
        "light_rmse_not_worse": row["candidate_light_rmse"] <= row["baseline_light_rmse"] + tol,
        "light_mae_not_worse": row["candidate_light_mae"] <= row["baseline_light_mae"] + tol,
        "floor10_not_worse": row["candidate_floor10_relative_mae"] <= row["baseline_floor10_relative_mae"] + tol,
        "no_new_light_moderate_tail_failure": int(row["new_light_moderate_relative_tail_failures"]) == 0,
        "high_error_count_not_worse": row["candidate_high_error_ge30_count"] <= row["baseline_high_error_ge30_count"],
    }


def _split_rows(df: pd.DataFrame, tolerance: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("train", "val", "test"):
        row = _metrics(df[df["split"] == split])
        row["split"] = split
        gates = _passes(row, tolerance)
        row.update({f"pass_{key}": bool(value) for key, value in gates.items()})
        row["guardrail_pass"] = bool(all(gates.values()))
        rows.append(row)
    all_row = _metrics(df)
    all_row["split"] = "all"
    gates = _passes(all_row, tolerance)
    all_row.update({f"pass_{key}": bool(value) for key, value in gates.items()})
    all_row["guardrail_pass"] = bool(all(gates.values()))
    rows.append(all_row)
    return rows


def _evaluate_rule(
    df: pd.DataFrame,
    rule: RuleSpec,
    scale: float,
    selection_split: str,
    evaluation_split: str,
    tolerance: float,
) -> dict[str, Any]:
    enabled = rule.mask_fn(df).fillna(False).to_numpy(dtype=bool)
    gated = _apply_gate(df, enabled, scale)
    rows = _split_rows(gated, tolerance)
    by_split = {str(row["split"]): row for row in rows}
    sel = by_split[selection_split]
    evl = by_split[evaluation_split]
    return {
        "rule_name": rule.name,
        "description": rule.description,
        "complexity": int(rule.complexity),
        "scale": float(scale),
        "selection_split": selection_split,
        "evaluation_split": evaluation_split,
        "selection_enabled_points": int(sel["enabled_points"]),
        "selection_points": int(sel["points"]),
        "selection_delta_rmse": float(sel["delta_rmse"]),
        "selection_delta_p95": float(sel["delta_p95"]),
        "selection_delta_p99": float(sel["delta_p99"]),
        "selection_delta_light_rmse": float(sel["delta_light_rmse"]),
        "selection_delta_light_mae": float(sel["delta_light_mae"]),
        "selection_delta_floor10": float(sel["delta_floor10_relative_mae"]),
        "selection_guardrail_pass": bool(sel["guardrail_pass"]),
        "evaluation_enabled_points": int(evl["enabled_points"]),
        "evaluation_points": int(evl["points"]),
        "evaluation_delta_rmse": float(evl["delta_rmse"]),
        "evaluation_delta_p95": float(evl["delta_p95"]),
        "evaluation_delta_p99": float(evl["delta_p99"]),
        "evaluation_delta_light_rmse": float(evl["delta_light_rmse"]),
        "evaluation_delta_light_mae": float(evl["delta_light_mae"]),
        "evaluation_delta_floor10": float(evl["delta_floor10_relative_mae"]),
        "evaluation_guardrail_pass": bool(evl["guardrail_pass"]),
    }


def _write_report(
    path: Path,
    selected: dict[str, Any],
    selected_rows: list[dict[str, Any]],
    candidates: pd.DataFrame,
    selection_split: str,
    evaluation_split: str,
    selected_description: str,
    min_rmse_gain: float,
    selection_policy: str,
    retain_fraction: float,
    max_enabled_fraction: float,
) -> None:
    lines = [
        "# Stage5 Residual PINN Truth-Free Gate Selection",
        "",
        "The gate is selected on validation only, then locked before the test split is evaluated.",
        "Rules use Stage4/report features only; truth-speed and error buckets are not rule inputs.",
        "",
        "## Selected Gate",
        "",
        f"- rule: `{selected['rule_name']}`",
        f"- scale: `{selected['scale']:.3f}`",
        f"- description: {selected_description}",
        f"- selected by: `{selection_split}` guardrail pass and RMSE gain > `{min_rmse_gain:.6f}`",
        f"- selection policy: `{selection_policy}`",
        f"- promotion-safe retain fraction: `{retain_fraction:.3f}`",
        f"- max enabled fraction: `{max_enabled_fraction:.3f}`",
        "",
        "## Locked Metrics",
        "",
        "| split | points | enabled | baseline RMSE | gated RMSE | delta RMSE | baseline P95 | gated P95 | baseline P99 | gated P99 | light RMSE base/gated | floor10 base/gated | guardrail |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in selected_rows:
        lines.append(
            f"| `{row['split']}` | {int(row['points'])} | {int(row['enabled_points'])} | "
            f"{row['baseline_rmse']:.6f} | {row['candidate_rmse']:.6f} | {row['delta_rmse']:+.6f} | "
            f"{row['baseline_p95']:.6f} | {row['candidate_p95']:.6f} | "
            f"{row['baseline_p99']:.6f} | {row['candidate_p99']:.6f} | "
            f"{row['baseline_light_rmse']:.6f}/{row['candidate_light_rmse']:.6f} | "
            f"{row['baseline_floor10_relative_mae']:.6f}/{row['candidate_floor10_relative_mae']:.6f} | "
            f"`{'PASS' if row['guardrail_pass'] else 'FAIL'}` |"
        )
    sel = next(row for row in selected_rows if row["split"] == selection_split)
    evl = next(row for row in selected_rows if row["split"] == evaluation_split)
    lines.extend(
        [
            "",
            f"## `{selection_split}` Guardrail",
            "",
            "| gate | result |",
            "| --- | --- |",
        ]
    )
    for key, value in _passes(sel, 1e-9).items():
        lines.append(f"| `{key}` | `{'PASS' if value else 'FAIL'}` |")
    lines.append(f"| `POINT_REPORT_OVERALL` | `{'PASS' if sel['guardrail_pass'] else 'FAIL'}` |")
    lines.extend(["", f"## Locked `{evaluation_split}` Guardrail", "", "| gate | result |", "| --- | --- |"])
    for key, value in _passes(evl, 1e-9).items():
        lines.append(f"| `{key}` | `{'PASS' if value else 'FAIL'}` |")
    lines.append(f"| `POINT_REPORT_OVERALL` | `{'PASS' if evl['guardrail_pass'] else 'FAIL'}` |")

    ranked = candidates.sort_values(
        ["selection_guardrail_pass", "selection_delta_rmse", "complexity", "selection_enabled_points"],
        ascending=[False, True, True, False],
    ).head(20)
    lines.extend(
        [
            "",
            "## Top Validation Candidates",
            "",
            "| rule | scale | val enabled | val delta RMSE | val delta P95 | val light delta | val floor10 delta | val pass | locked test delta RMSE | locked test pass |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for _, row in ranked.iterrows():
        lines.append(
            f"| `{row['rule_name']}` | {row['scale']:.3f} | {int(row['selection_enabled_points'])} | "
            f"{row['selection_delta_rmse']:+.6f} | {row['selection_delta_p95']:+.6f} | "
            f"{row['selection_delta_light_rmse']:+.6f} | {row['selection_delta_floor10']:+.6f} | "
            f"`{'PASS' if row['selection_guardrail_pass'] else 'FAIL'}` | "
            f"{row['evaluation_delta_rmse']:+.6f} | `{'PASS' if row['evaluation_guardrail_pass'] else 'FAIL'}` |"
        )
    lines.extend(
        [
            "",
            "## Field Decision Boundary",
            "",
            "- This is still a point-level report gate, not a field_v1 promotion.",
            "- A field_v1 candidate should only be generated after the locked test point report passes, then it still needs full-field smoke and strict holdout pairwise checks.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Select Stage5 residual PINN truth-free gate on val, then lock-test.")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--candidate-point-predictions", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--selection-split", choices=["train", "val"], default="val")
    parser.add_argument("--evaluation-split", choices=["val", "test"], default="test")
    parser.add_argument("--scales", default="0.25,0.5,0.75,1.0")
    parser.add_argument("--rule-profile", choices=["broad", "tail_safe", "narrow_safe"], default="broad")
    parser.add_argument("--selection-policy", choices=["best_rmse", "promotion_safe", "stable_safe"], default="best_rmse")
    parser.add_argument("--promotion-safe-retain-fraction", type=float, default=0.50)
    parser.add_argument("--max-enabled-fraction", type=float, default=1.0)
    parser.add_argument("--min-enabled", type=int, default=3)
    parser.add_argument("--min-rmse-gain", type=float, default=0.0)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    args = parser.parse_args()

    predictions = pd.read_csv(args.candidate_point_predictions)
    features = _load_features(args.dataset_dir)
    df = predictions.merge(features, left_on=["row_id", "split"], right_on=["row_id", "feature_split"], how="left")
    if df["feature_split"].isna().any():
        missing = int(df["feature_split"].isna().sum())
        raise ValueError(f"Feature merge failed for {missing} prediction rows")

    scales = [float(item) for item in str(args.scales).split(",") if str(item).strip()]
    candidates: list[dict[str, Any]] = []
    baseline_rule = RuleSpec(
        name="baseline_no_stage5",
        description="Disable all Stage5 residual corrections.",
        complexity=0,
        mask_fn=lambda frame: pd.Series(False, index=frame.index),
    )
    rules = [rule for rule in _build_rules() if _profile_accepts(rule.name, str(args.rule_profile))]
    for rule in [baseline_rule] + rules:
        rule_scales = [0.0] if rule.name == "baseline_no_stage5" else scales
        for scale in rule_scales:
            row = _evaluate_rule(df, rule, scale, str(args.selection_split), str(args.evaluation_split), float(args.tolerance))
            row["eligible"] = bool(
                row["selection_guardrail_pass"]
                and row["selection_delta_rmse"] < -float(args.min_rmse_gain)
                and row["selection_enabled_points"] >= int(args.min_enabled)
            )
            if rule.name == "baseline_no_stage5":
                row["eligible"] = False
            candidates.append(row)

    cand_df = pd.DataFrame(candidates)
    eligible = cand_df[cand_df["eligible"]].copy()
    if eligible.empty:
        selected_row = cand_df[cand_df["rule_name"] == "baseline_no_stage5"].iloc[0].to_dict()
        selected_description = "No validation-passing improving gate was found; keep tp26 unchanged."
    else:
        if str(args.selection_policy) == "promotion_safe":
            best_delta = float(eligible["selection_delta_rmse"].min())
            keep_threshold = best_delta * float(args.promotion_safe_retain_fraction)
            eligible = eligible[eligible["selection_delta_rmse"] <= keep_threshold].copy()
            eligible = eligible.sort_values(
                ["scale", "selection_delta_floor10", "complexity", "selection_delta_rmse", "selection_enabled_points"],
                ascending=[True, True, True, True, False],
            )
        elif str(args.selection_policy) == "stable_safe":
            eligible["selection_enabled_fraction"] = eligible["selection_enabled_points"] / eligible["selection_points"].clip(lower=1)
            eligible = eligible[eligible["selection_enabled_fraction"] <= float(args.max_enabled_fraction)].copy()
            if eligible.empty:
                selected_row = cand_df[cand_df["rule_name"] == "baseline_no_stage5"].iloc[0].to_dict()
                selected_description = "No stable-safe validation gate survived coverage filtering; keep tp26 unchanged."
                eligible = None
            else:
                best_delta = float(eligible["selection_delta_rmse"].min())
                keep_threshold = best_delta * float(args.promotion_safe_retain_fraction)
                eligible = eligible[eligible["selection_delta_rmse"] <= keep_threshold].copy()
                eligible["selection_tail_margin"] = (
                    eligible["selection_delta_p99"].clip(upper=0.0)
                    + eligible["selection_delta_light_rmse"].clip(upper=0.0)
                    + eligible["selection_delta_light_mae"].clip(upper=0.0)
                    + eligible["selection_delta_floor10"].clip(upper=0.0)
                )
                eligible = eligible.sort_values(
                    [
                        "selection_enabled_fraction",
                        "selection_delta_floor10",
                        "selection_delta_light_rmse",
                        "selection_delta_p99",
                        "scale",
                        "selection_delta_rmse",
                    ],
                    ascending=[True, True, True, True, True, True],
                )
                selected_row = eligible.iloc[0].to_dict()
                selected_description = str(selected_row["description"])
        else:
            eligible = eligible.sort_values(
                ["selection_delta_rmse", "complexity", "selection_enabled_points", "scale"],
                ascending=[True, True, False, True],
            )
        if str(args.selection_policy) != "stable_safe":
            selected_row = eligible.iloc[0].to_dict()
            selected_description = str(selected_row["description"])

    selected_rule = next((rule for rule in _build_rules() if rule.name == selected_row["rule_name"]), baseline_rule)
    selected_enabled = selected_rule.mask_fn(df).fillna(False).to_numpy(dtype=bool)
    selected_df = _apply_gate(df, selected_enabled, float(selected_row["scale"]))
    selected_rows = _split_rows(selected_df, float(args.tolerance))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    cand_df.to_csv(args.out_dir / "gate_candidates.csv", index=False)
    selected_df.to_csv(args.out_dir / "gated_predictions_all.csv", index=False)
    with (args.out_dir / "gated_point_compare.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(selected_rows[0].keys()))
        writer.writeheader()
        writer.writerows(selected_rows)
    payload = {
        "selected": selected_row,
        "selected_description": selected_description,
        "selection_split": str(args.selection_split),
        "evaluation_split": str(args.evaluation_split),
        "min_enabled": int(args.min_enabled),
        "min_rmse_gain": float(args.min_rmse_gain),
        "tolerance": float(args.tolerance),
        "truth_free_gate_policy": True,
        "rule_profile": str(args.rule_profile),
        "selection_policy": str(args.selection_policy),
        "promotion_safe_retain_fraction": float(args.promotion_safe_retain_fraction),
        "max_enabled_fraction": float(args.max_enabled_fraction),
        "test_not_used_for_selection": str(args.evaluation_split) == "test",
        "split_rows": selected_rows,
    }
    (args.out_dir / "selected_gate.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(
        args.out_dir / "gate_selection_report.md",
        selected_row,
        selected_rows,
        cand_df,
        str(args.selection_split),
        str(args.evaluation_split),
        selected_description,
        float(args.min_rmse_gain),
        str(args.selection_policy),
        float(args.promotion_safe_retain_fraction),
        float(args.max_enabled_fraction),
    )
    print(args.out_dir / "gate_selection_report.md")


if __name__ == "__main__":
    main()
