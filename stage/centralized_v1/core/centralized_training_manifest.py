"""Build strict training manifests for PINN/proxy and diffusion experiments.

The manifest is a planning artifact: it records which frames may be used for
train/validation/test, which sparse aircraft labels remain strict hold-out
truth, which Stage4/CMA-proxy products can be used as weak dense targets or
priors, and which physics losses should be optimized.

It does not train a network.  That is deliberate: the project first needs
enough collocated Stage4 + CMA-proxy frames and stable validation/test splits.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.core.centralized_stage4_ground_recon import _load_json  # noqa: E402


CMA_FILENAME_RE = re.compile(r"CRA40_([A-Z0-9]+)_(\d{10})_")
CMA_REQUIRED_WIND_CODES = ("WIU", "WIV")
CMA_VAR_CODES = {
    "GPH": "geopotential_height_gpm",
    "RHU": "relative_humidity_percent",
    "TEM": "temperature_k",
    "VVP": "vertical_velocity_pa_s",
    "WIU": "u_wind_mps",
    "WIV": "v_wind_mps",
}

DEFAULT_LOSS_CONFIG = {
    "training_status": "manifest_only_not_trained",
    "core_formula": "F_pinn = F_timepower15 + delta_u/delta_v; diffusion consumes F_pinn plus masks/confidence for local residual and uncertainty.",
    "target_policy": {
        "aircraft_holdout_labels": "strict validation/test labels; never used as dense truth",
        "stage4_sparse_reconstruction": "sparse prior or pseudo-target inside recon_mask_3d",
        "cma_ra_or_cra40": "weak dense background, condition input, boundary/physics constraint; never formal truth",
        "cma_ra_virtual_radial_3dvar": "weak dense background/proxy target after collocation",
        "external_reanalysis_or_nwp": "weak/background field, not absolute truth",
    },
    "loss_terms": {
        "observation_fit": {
            "formula": "mean(||pred_u/v at aircraft observation voxels - observed_u/v||^2)",
            "default_weight": 1.0,
        },
        "virtual_radial_fit": {
            "formula": "mean((dot(pred_u/v/w, radar_line_of_sight) - virtual_radial_velocity)^2)",
            "default_weight": 0.35,
        },
        "stage4_sparse_prior_fit": {
            "formula": "mean(recon_conf * ||pred_u/v - stage4_recon_u/v||^2)",
            "default_weight": 0.45,
        },
        "background_fit": {
            "formula": "mean(||pred_u/v - CMA_or_NWP_background_u/v||^2)",
            "default_weight": 0.15,
        },
        "timepower15_residual_regularization": {
            "formula": "mean(recon_conf * ||delta_u/v||^2), where pred = TimePower15 + delta",
            "default_weight": 0.20,
        },
        "field_smoothness": {
            "formula": "mean(|grad_x/y/z pred_u|^2 + |grad_x/y/z pred_v|^2)",
            "default_weight": 0.05,
        },
        "weak_horizontal_divergence": {
            "formula": "mean((d pred_u/dx + d pred_v/dy)^2)",
            "default_weight": 0.03,
        },
        "vertical_wind_shear": {
            "formula": "mean(|d pred_u/dz|^2 + |d pred_v/dz|^2), optionally altitude-weighted",
            "default_weight": 0.03,
        },
        "vertical_gradient_preservation": {
            "formula": "penalize loss of strong observed/CMA-supported vertical gradients instead of smoothing them away",
            "default_weight": 0.04,
        },
        "strong_layer_anti_oversmooth": {
            "formula": "increase residual capacity or reduce smoothing weight where strong-layer oversmoothing diagnostics are positive",
            "default_weight": 0.03,
        },
        "boundary_background": {
            "formula": "mean(boundary_mask * ||pred_u/v - background_u/v||^2)",
            "default_weight": 0.05,
        },
        "coverage_mask": {
            "formula": "train dense losses only where recon_mask, CMA coverage, or explicit background mask is valid",
            "default_weight": 1.0,
        },
    },
    "model_families": {
        "pinn_or_proxy": "coordinate/time-conditioned network or neural field with physics losses",
        "diffusion": "conditional sparse-to-dense model; condition on aircraft anchors, Stage4 prior, CMA background/radial fields, radar/cloud context and masks",
    },
    "references": [
        "https://doi.org/10.1016/j.jcp.2018.10.045",
        "https://openradarscience.org/PyDDA/",
        "https://www.nature.com/articles/s41586-024-08252-9",
        "https://doi.org/10.1109/34.56205",
        "https://doi.org/10.1007/s13351-023-2086-x",
    ],
}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _stage4_time_set(stage4_csv: Path) -> set[str]:
    return {str(row.get("time_str")) for row in _read_csv(stage4_csv) if row.get("time_str")}


def _available_cma_proxy(proxy_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    if not proxy_dir.exists():
        return out
    for path in proxy_dir.glob("cma_ra_virtual_radial_3dvar_*.npz"):
        time_str = path.stem.replace("cma_ra_virtual_radial_3dvar_", "")
        out[time_str] = path
    return out


def _index_cma_raw(cma_raw_dir: Path) -> tuple[dict[str, set[str]], dict[str, int]]:
    index: dict[str, set[str]] = {}
    counts: dict[str, int] = defaultdict(int)
    if not cma_raw_dir.exists():
        return index, dict(counts)
    for path in cma_raw_dir.iterdir():
        if not path.is_file():
            continue
        match = CMA_FILENAME_RE.search(path.name)
        if not match:
            continue
        var_code, cma_time = match.groups()
        if var_code not in CMA_VAR_CODES:
            continue
        index.setdefault(cma_time, set()).add(var_code)
        counts[var_code] += 1
    return index, dict(counts)


def _parse_time_utc(time_str: str) -> datetime:
    text = str(time_str)
    if len(text) == 14:
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if len(text) == 10:
        return datetime.strptime(text, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    raise ValueError(f"Unsupported time_str: {time_str}")


def _bracket_cma_raw_time(
    frame_time: str,
    cma_raw_index: dict[str, set[str]],
    max_window_hours: float,
) -> dict[str, Any]:
    target = _parse_time_utc(frame_time)
    available = sorted(
        time_str
        for time_str, var_codes in cma_raw_index.items()
        if all(code in var_codes for code in CMA_REQUIRED_WIND_CODES)
    )
    parsed = [(time_str, _parse_time_utc(time_str)) for time_str in available]
    previous = [(time_str, dt) for time_str, dt in parsed if dt <= target]
    following = [(time_str, dt) for time_str, dt in parsed if dt >= target]
    if not previous or not following:
        return {
            "has_cma_raw_wind_bracket": False,
            "cma_raw_time_t0": "",
            "cma_raw_time_t1": "",
            "cma_raw_alpha": "",
            "cma_raw_delta_hours_from_t0": "",
            "cma_raw_delta_hours_to_t1": "",
            "cma_raw_bracket_hours": "",
            "cma_raw_vars_t0": "",
            "cma_raw_vars_t1": "",
        }
    t0_str, t0_dt = max(previous, key=lambda item: item[1])
    t1_str, t1_dt = min(following, key=lambda item: item[1])
    window_hours = (t1_dt - t0_dt).total_seconds() / 3600.0
    if window_hours > float(max_window_hours):
        return {
            "has_cma_raw_wind_bracket": False,
            "cma_raw_time_t0": t0_str,
            "cma_raw_time_t1": t1_str,
            "cma_raw_alpha": "",
            "cma_raw_delta_hours_from_t0": "",
            "cma_raw_delta_hours_to_t1": "",
            "cma_raw_bracket_hours": float(window_hours),
            "cma_raw_vars_t0": ",".join(sorted(cma_raw_index.get(t0_str, set()))),
            "cma_raw_vars_t1": ",".join(sorted(cma_raw_index.get(t1_str, set()))),
        }
    denom = max(1.0, (t1_dt - t0_dt).total_seconds())
    alpha = 0.0 if t0_dt == t1_dt else (target - t0_dt).total_seconds() / denom
    return {
        "has_cma_raw_wind_bracket": True,
        "cma_raw_time_t0": t0_str,
        "cma_raw_time_t1": t1_str,
        "cma_raw_alpha": float(max(0.0, min(1.0, alpha))),
        "cma_raw_delta_hours_from_t0": float((target - t0_dt).total_seconds() / 3600.0),
        "cma_raw_delta_hours_to_t1": float((t1_dt - target).total_seconds() / 3600.0),
        "cma_raw_bracket_hours": float(window_hours),
        "cma_raw_vars_t0": ",".join(sorted(cma_raw_index.get(t0_str, set()))),
        "cma_raw_vars_t1": ",".join(sorted(cma_raw_index.get(t1_str, set()))),
    }


def _split_frames(frame_times: list[str], train_fraction: float, val_fraction: float) -> dict[str, str]:
    ordered = sorted(dict.fromkeys(frame_times))
    n = len(ordered)
    n_train = int(round(n * float(train_fraction)))
    n_val = int(round(n * float(val_fraction)))
    n_train = max(0, min(n, n_train))
    n_val = max(0, min(n - n_train, n_val))
    split: dict[str, str] = {}
    for idx, time_str in enumerate(ordered):
        if idx < n_train:
            split[time_str] = "train"
        elif idx < n_train + n_val:
            split[time_str] = "val"
        else:
            split[time_str] = "test"
    return split


def _write_md(path: Path, manifest: dict[str, Any]) -> None:
    counts = manifest["split_counts"]
    lines = [
        "# Centralized V1 Training Manifest",
        "",
        "This is a strict split and loss-configuration manifest. It does not train a model.",
        "",
        "## Split",
        "",
        f"- train frames: `{counts.get('train', 0)}`",
        f"- validation frames: `{counts.get('val', 0)}`",
        f"- test frames: `{counts.get('test', 0)}`",
        f"- frames with Stage4 metrics: `{manifest['frames_with_stage4_metrics']}`",
        f"- frames with CMA proxy NPZ: `{manifest['frames_with_cma_proxy']}`",
        f"- frames with raw CMA wind bracket: `{manifest['frames_with_cma_raw_wind_bracket']}`",
        f"- raw CMA wind times: `{manifest['cma_raw_wind_time_count']}`",
        "",
        "## Training Boundary",
        "",
        "- Aircraft sparse wind points can train observation-fit losses only inside the train split.",
        "- Validation and test aircraft hold-out labels remain hidden from training.",
        "- CMA-RA / NWP / reanalysis fields are weak background or pseudo-labels, not absolute truth.",
        "- Diffusion and PINN/proxy models should report both sparse aircraft hold-out metrics and background-field consistency metrics.",
        "",
        "## Loss Terms",
        "",
        "| loss | default weight | formula |",
        "| --- | ---: | --- |",
    ]
    for name, cfg in manifest["loss_config"]["loss_terms"].items():
        lines.append(f"| `{name}` | {float(cfg['default_weight']):.3f} | {cfg['formula']} |")
    lines.extend(
        [
            "",
            "## Frame Table",
            "",
            "| split | time | stage2 npz | stage4 metrics | cma proxy | raw CMA bracket |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in manifest["frames"]:
        bracket = ""
        if row.get("has_cma_raw_wind_bracket"):
            bracket = f"{row.get('cma_raw_time_t0')}->{row.get('cma_raw_time_t1')} alpha={float(row.get('cma_raw_alpha', 0.0)):.3f}"
        lines.append(
            f"| `{row['split']}` | `{row['time_str']}` | `{row['stage2_npz']}` | "
            f"`{row['has_stage4_metrics']}` | `{row['cma_proxy_npz']}` | `{bracket}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a strict training manifest for PINN/proxy and diffusion experiments.")
    parser.add_argument("--stage2-summary", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json"))
    parser.add_argument("--stage4-csv", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529/stage4_localization_sensitivity.csv"))
    parser.add_argument("--cma-raw-dir", type=Path, default=Path("/data/LFT-W02_data/pengxu/cma"))
    parser.add_argument("--cma-proxy-dir", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/cma_ra_virtual_radial_3dvar"))
    parser.add_argument("--out-dir", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/training_manifest"))
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--cma-max-linear-window-hours", type=float, default=6.1)
    parser.add_argument("--require-stage4-metrics", action="store_true")
    args = parser.parse_args()

    stage2_rows = _load_json(args.stage2_summary)
    stage4_times = _stage4_time_set(args.stage4_csv)
    cma_proxy = _available_cma_proxy(args.cma_proxy_dir)
    cma_raw_index, cma_raw_counts = _index_cma_raw(args.cma_raw_dir)
    cma_raw_wind_times = [
        time_str
        for time_str, var_codes in cma_raw_index.items()
        if all(code in var_codes for code in CMA_REQUIRED_WIND_CODES)
    ]
    candidates = []
    for row in stage2_rows:
        time_str = str(row["time_str"])
        if args.require_stage4_metrics and time_str not in stage4_times:
            continue
        candidates.append(row)
    split = _split_frames([str(row["time_str"]) for row in candidates], args.train_fraction, args.val_fraction)
    frames = []
    for row in sorted(candidates, key=lambda item: str(item["time_str"])):
        time_str = str(row["time_str"])
        frames.append(
            {
                "time_str": time_str,
                "split": split[time_str],
                "stage2_npz": str(row.get("multimodal_vox_path", "")),
                "has_stage4_metrics": time_str in stage4_times,
                "cma_proxy_npz": str(cma_proxy.get(time_str, "")),
                **_bracket_cma_raw_time(time_str, cma_raw_index, float(args.cma_max_linear_window_hours)),
                "wind_voxels": int(row.get("wind_voxels", 0)),
                "context_wind_voxels": int(row.get("context_wind_voxels", 0)),
                "traj_voxels": int(row.get("traj_voxels", 0)),
            }
        )
    split_counts: dict[str, int] = defaultdict(int)
    for row in frames:
        split_counts[row["split"]] += 1
    manifest = {
        "stage2_summary": str(args.stage2_summary),
        "stage4_csv": str(args.stage4_csv),
        "cma_raw_dir": str(args.cma_raw_dir),
        "cma_proxy_dir": str(args.cma_proxy_dir),
        "cma_raw_file_count": int(sum(cma_raw_counts.values())),
        "cma_raw_file_counts_by_var": cma_raw_counts,
        "cma_raw_wind_time_count": len(cma_raw_wind_times),
        "frames_total": len(frames),
        "frames_with_stage4_metrics": sum(1 for row in frames if row["has_stage4_metrics"]),
        "frames_with_cma_proxy": sum(1 for row in frames if row["cma_proxy_npz"]),
        "frames_with_cma_raw_wind_bracket": sum(1 for row in frames if row["has_cma_raw_wind_bracket"]),
        "split_counts": dict(split_counts),
        "loss_config": DEFAULT_LOSS_CONFIG,
        "frames": frames,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "centralized_training_manifest.json"
    md_path = args.out_dir / "centralized_training_manifest.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(md_path, manifest)
    print(json_path)


if __name__ == "__main__":
    main()
