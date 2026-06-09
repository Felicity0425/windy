"""Run full-data Stage5 residual PINN sweeps across multiple GPUs.

The runner keeps the leakage boundary intact: labels still come only from
aircraft point departures, while gate selection uses validation split and
truth-free features only. It is an orchestration helper, not a new model.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Candidate:
    cap: float
    seed: int
    width: int
    layers: int

    @property
    def name(self) -> str:
        cap_tag = str(self.cap).replace(".", "p")
        return f"cap{cap_tag}_seed{self.seed}_w{self.width}_l{self.layers}"


def _split_csv_floats(value: str) -> list[float]:
    return [float(item.strip()) for item in str(value).split(",") if item.strip()]


def _split_csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in str(value).split(",") if item.strip()]


def _run_checked(cmd: list[str], cwd: Path, log_path: Path | None = None, env: dict[str, str] | None = None) -> None:
    if log_path is None:
        subprocess.run(cmd, cwd=str(cwd), env=env, check=True)
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        subprocess.run(cmd, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT, check=True)


def _build_dataset(args: argparse.Namespace, python_bin: str, dataset_dir: Path, log_dir: Path) -> None:
    if dataset_dir.exists() and not bool(args.force_rebuild_dataset):
        return
    cmd = [
        python_bin,
        "stage/centralized_v1/core/centralized_stage5_residual_pinn_dataset.py",
        "--point-departures",
        str(args.point_departures),
        "--out-dir",
        str(dataset_dir),
    ]
    if args.manifest:
        cmd.extend(["--manifest", str(args.manifest)])
    else:
        cmd.extend(["--train-fraction", str(args.train_fraction), "--val-fraction", str(args.val_fraction)])
    _run_checked(cmd, ROOT_DIR, log_dir / "build_dataset.log")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _spawn_train(
    args: argparse.Namespace,
    python_bin: str,
    dataset_dir: Path,
    out_root: Path,
    log_dir: Path,
    candidate: Candidate,
    gpu_id: int,
) -> subprocess.Popen[bytes]:
    out_dir = out_root / f"train_{candidate.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        python_bin,
        "stage/centralized_v1/core/centralized_stage5_residual_pinn_train.py",
        "--dataset-dir",
        str(dataset_dir),
        "--out-dir",
        str(out_dir),
        "--max-epochs",
        str(args.max_epochs),
        "--batch-size",
        str(args.batch_size),
        "--learning-rate",
        str(args.learning_rate),
        "--width",
        str(candidate.width),
        "--layers",
        str(candidate.layers),
        "--delta-cap-mps",
        str(candidate.cap),
        "--huber-beta",
        str(args.huber_beta),
        "--uncertainty-loss-weight",
        str(args.uncertainty_loss_weight),
        "--delta-reg-weight",
        str(args.delta_reg_weight),
        "--patience",
        str(args.patience),
        "--seed",
        str(candidate.seed),
        "--device",
        "cuda",
        "--allow-tf32",
    ]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    env.setdefault("OMP_NUM_THREADS", str(args.omp_threads))
    env.setdefault("MKL_NUM_THREADS", str(args.omp_threads))
    log_path = log_dir / f"train_{candidate.name}_gpu{gpu_id}.log"
    log = log_path.open("w", encoding="utf-8")
    log.write("$ CUDA_VISIBLE_DEVICES=" + str(gpu_id) + " " + " ".join(cmd) + "\n\n")
    log.flush()
    proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), env=env, stdout=log, stderr=subprocess.STDOUT)
    proc._stage5_log_handle = log  # type: ignore[attr-defined]
    return proc


def _run_gate(
    args: argparse.Namespace,
    python_bin: str,
    dataset_dir: Path,
    out_root: Path,
    log_dir: Path,
    candidate: Candidate,
) -> dict[str, Any]:
    train_dir = out_root / f"train_{candidate.name}"
    gate_dir = out_root / f"gate_{candidate.name}"
    cmd = [
        python_bin,
        "stage/centralized_v1/core/centralized_stage5_residual_pinn_gate_select.py",
        "--dataset-dir",
        str(dataset_dir),
        "--candidate-point-predictions",
        str(train_dir / "predictions_all.csv"),
        "--out-dir",
        str(gate_dir),
        "--selection-split",
        "val",
        "--evaluation-split",
        "test",
        "--rule-profile",
        str(args.rule_profile),
        "--selection-policy",
        str(args.selection_policy),
        "--promotion-safe-retain-fraction",
        str(args.promotion_safe_retain_fraction),
        "--min-enabled",
        str(args.min_enabled),
        "--min-rmse-gain",
        str(args.min_rmse_gain),
    ]
    _run_checked(cmd, ROOT_DIR, log_dir / f"gate_{candidate.name}.log")
    payload = _load_json(gate_dir / "selected_gate.json")
    train_metrics = _load_json(train_dir / "train_metrics.json")
    test_row = next(row for row in payload["split_rows"] if row["split"] == "test")
    val_row = next(row for row in payload["split_rows"] if row["split"] == "val")
    selected = payload["selected"]
    return {
        "candidate": candidate.name,
        "cap": candidate.cap,
        "seed": candidate.seed,
        "width": candidate.width,
        "layers": candidate.layers,
        "train_dir": str(train_dir),
        "gate_dir": str(gate_dir),
        "device": train_metrics.get("training", {}).get("device", ""),
        "cuda_device_name": train_metrics.get("training", {}).get("cuda_device_name", ""),
        "cuda_memory_allocated_mb": train_metrics.get("training", {}).get("cuda_memory_allocated_mb", 0.0),
        "best_epoch": train_metrics.get("training", {}).get("best_epoch", -1.0),
        "raw_test_delta_rmse": train_metrics.get("test", {}).get("delta_vector_rmse", 0.0),
        "gate_rule": selected.get("rule_name", ""),
        "gate_scale": selected.get("scale", 0.0),
        "val_delta_rmse": val_row["delta_rmse"],
        "val_guardrail_pass": bool(val_row["guardrail_pass"]),
        "test_enabled_points": int(test_row["enabled_points"]),
        "test_points": int(test_row["points"]),
        "test_delta_rmse": test_row["delta_rmse"],
        "test_delta_p95": test_row["delta_p95"],
        "test_delta_p99": test_row["delta_p99"],
        "test_delta_light_rmse": test_row["delta_light_rmse"],
        "test_delta_floor10": test_row["delta_floor10_relative_mae"],
        "test_guardrail_pass": bool(test_row["guardrail_pass"]),
    }


def _write_report(path: Path, dataset_summary: dict[str, Any], rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    ranked = sorted(rows, key=lambda r: (not bool(r["test_guardrail_pass"]), float(r["test_delta_rmse"])))
    lines = [
        "# Stage5 Residual PINN Full-Data GPU Sweep",
        "",
        "This sweep trains point-level residual candidates on the larger full tp26 departure set, then selects a truth-free guarded gate on validation and locks test evaluation.",
        "",
        "## Dataset",
        "",
        f"- point departures: `{args.point_departures}`",
        f"- frames: `{dataset_summary.get('frames', 0)}`",
        f"- points: `{dataset_summary.get('points', 0)}`",
        f"- split counts: `{dataset_summary.get('split_counts', {})}`",
        "",
        "## GPU Policy",
        "",
        f"- GPU IDs: `{args.gpu_ids}`",
        f"- one training process per listed GPU by default",
        f"- CUDA_VISIBLE_DEVICES is set per process so each candidate sees one RTX 4090 as `cuda:0`",
        "",
        "## Ranking",
        "",
        "| candidate | cap | seed | gate | scale | test enabled | raw test dRMSE | gated test dRMSE | dP95 | dP99 | dLight | dFloor10 | test gate |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in ranked:
        lines.append(
            f"| `{row['candidate']}` | {row['cap']:.3f} | {int(row['seed'])} | `{row['gate_rule']}` | "
            f"{float(row['gate_scale']):.3f} | {int(row['test_enabled_points'])}/{int(row['test_points'])} | "
            f"{float(row['raw_test_delta_rmse']):+.6f} | {float(row['test_delta_rmse']):+.6f} | "
            f"{float(row['test_delta_p95']):+.6f} | {float(row['test_delta_p99']):+.6f} | "
            f"{float(row['test_delta_light_rmse']):+.6f} | {float(row['test_delta_floor10']):+.6f} | "
            f"`{'PASS' if row['test_guardrail_pass'] else 'FAIL'}` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This is still point-level promotion evidence, not a full field_v1 result.",
            "- Passing candidates may enter field_v1 smoke only through the selected truth-free gate.",
            "- Stage4 `tp26_thr11_preserve` remains the default until full-field smoke and 200-frame strict pairwise checks pass.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stage5 residual PINN full-data training sweep across GPUs.")
    parser.add_argument("--point-departures", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, default=None)
    parser.add_argument("--force-rebuild-dataset", action="store_true")
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--gpu-ids", default="0,1,2")
    parser.add_argument("--caps", default="0.5,1.0,3.0")
    parser.add_argument("--seeds", default="20260608,20260609,20260610")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--layers", type=int, default=6)
    parser.add_argument("--max-epochs", type=int, default=1200)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=8e-4)
    parser.add_argument("--huber-beta", type=float, default=2.0)
    parser.add_argument("--uncertainty-loss-weight", type=float, default=0.03)
    parser.add_argument("--delta-reg-weight", type=float, default=0.02)
    parser.add_argument("--patience", type=int, default=160)
    parser.add_argument("--omp-threads", type=int, default=8)
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--rule-profile", choices=["broad", "tail_safe"], default="tail_safe")
    parser.add_argument("--selection-policy", choices=["best_rmse", "promotion_safe"], default="promotion_safe")
    parser.add_argument("--promotion-safe-retain-fraction", type=float, default=0.50)
    parser.add_argument("--min-enabled", type=int, default=10)
    parser.add_argument("--min-rmse-gain", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    out_root = args.out_root
    dataset_dir = args.dataset_dir or (out_root / "dataset_full_tp26")
    log_dir = out_root / "logs"
    out_root.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    python_bin = str(args.python_bin)
    gpu_ids = _split_csv_ints(str(args.gpu_ids))
    caps = _split_csv_floats(str(args.caps))
    seeds = _split_csv_ints(str(args.seeds))
    candidates = [
        Candidate(cap=cap, seed=seed, width=int(args.width), layers=int(args.layers))
        for cap, seed in itertools.product(caps, seeds)
    ]
    manifest = {
        "point_departures": str(args.point_departures),
        "dataset_dir": str(dataset_dir),
        "out_root": str(out_root),
        "gpu_ids": gpu_ids,
        "caps": caps,
        "seeds": seeds,
        "width": int(args.width),
        "layers": int(args.layers),
        "max_epochs": int(args.max_epochs),
        "batch_size": int(args.batch_size),
        "rule_profile": str(args.rule_profile),
        "selection_policy": str(args.selection_policy),
        "candidates": [candidate.name for candidate in candidates],
    }
    (out_root / "sweep_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if bool(args.dry_run):
        for i, candidate in enumerate(candidates):
            gpu_id = gpu_ids[i % len(gpu_ids)]
            print(f"{candidate.name}: CUDA_VISIBLE_DEVICES={gpu_id} train -> {out_root / ('train_' + candidate.name)}")
        return

    _build_dataset(args, python_bin, dataset_dir, log_dir)
    dataset_summary = _load_json(dataset_dir / "dataset_summary.json")

    pending = list(candidates)
    running: dict[subprocess.Popen[bytes], tuple[Candidate, int]] = {}
    complete: list[Candidate] = []
    failed: list[tuple[Candidate, int]] = []
    next_gpu = 0
    while pending or running:
        while pending and len(running) < len(gpu_ids):
            candidate = pending.pop(0)
            gpu_id = gpu_ids[next_gpu % len(gpu_ids)]
            next_gpu += 1
            proc = _spawn_train(args, python_bin, dataset_dir, out_root, log_dir, candidate, gpu_id)
            running[proc] = (candidate, gpu_id)
            print(f"spawned {candidate.name} on GPU {gpu_id}")
        time.sleep(5.0)
        for proc in list(running):
            ret = proc.poll()
            if ret is None:
                continue
            log_handle = getattr(proc, "_stage5_log_handle", None)
            if log_handle is not None:
                log_handle.close()
            candidate, gpu_id = running.pop(proc)
            if ret == 0:
                complete.append(candidate)
                print(f"completed {candidate.name} on GPU {gpu_id}")
            else:
                failed.append((candidate, int(ret)))
                print(f"failed {candidate.name} on GPU {gpu_id}: {ret}")

    rows: list[dict[str, Any]] = []
    for candidate in complete:
        rows.append(_run_gate(args, python_bin, dataset_dir, out_root, log_dir, candidate))

    with (out_root / "sweep_results.csv").open("w", encoding="utf-8", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    result_payload = {"rows": rows, "failed": [{"candidate": c.name, "returncode": ret} for c, ret in failed]}
    (out_root / "sweep_results.json").write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(out_root / "sweep_report.md", dataset_summary, rows, args)
    print(out_root / "sweep_report.md")


if __name__ == "__main__":
    main()
