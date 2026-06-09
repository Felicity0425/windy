"""Train a conservative point-level residual PINN report model.

This is the Stage5 `report_v1` training path. It trains a small residual MLP on
frame-split point departures and reports whether a gated residual correction
can improve held-out frames. It is not a full-field PINN and does not change
Stage4 official outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))


@dataclass
class SplitData:
    split: str
    row_id: np.ndarray
    x: np.ndarray
    target_delta: np.ndarray
    gt_u: np.ndarray
    gt_v: np.ndarray
    gt_speed: np.ndarray
    pred_u: np.ndarray
    pred_v: np.ndarray
    gate: np.ndarray
    sample_weight: np.ndarray
    sigma_rep: np.ndarray


class ResidualMLP(nn.Module):
    def __init__(self, input_dim: int, width: int, layers: int, delta_cap: float) -> None:
        super().__init__()
        blocks: list[nn.Module] = []
        dim = input_dim
        for _ in range(max(1, layers)):
            blocks.append(nn.Linear(dim, width))
            blocks.append(nn.SiLU())
            blocks.append(nn.LayerNorm(width))
            dim = width
        blocks.append(nn.Linear(dim, 4))
        self.net = nn.Sequential(*blocks)
        self.delta_cap = float(delta_cap)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        raw = self.net(x)
        delta = self.delta_cap * torch.tanh(raw[:, :2])
        sigma = 0.25 + F.softplus(raw[:, 2:4])
        return delta, sigma


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _load_split(dataset_dir: Path, split: str) -> SplitData:
    path = dataset_dir / f"features_{split}.npz"
    with np.load(path, allow_pickle=False) as data:
        target = np.stack([data["target_delta_u"], data["target_delta_v"]], axis=1).astype(np.float32)
        return SplitData(
            split=split,
            row_id=data["row_id"].astype(np.int64),
            x=data["x"].astype(np.float32),
            target_delta=target,
            gt_u=data["gt_u"].astype(np.float32),
            gt_v=data["gt_v"].astype(np.float32),
            gt_speed=data["gt_speed"].astype(np.float32),
            pred_u=data["pred_u"].astype(np.float32),
            pred_v=data["pred_v"].astype(np.float32),
            gate=data["residual_gate_initial"].astype(np.float32),
            sample_weight=data["sample_weight_raw"].astype(np.float32),
            sigma_rep=data["sigma_rep_proxy_mps"].astype(np.float32),
        )


def _normalize_features(train: SplitData, splits: list[SplitData]) -> dict[str, Any]:
    mean = train.x.mean(axis=0)
    std = train.x.std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    for split in splits:
        split.x = ((split.x - mean) / std).astype(np.float32)
    w_mean = float(np.mean(train.sample_weight)) if train.sample_weight.size else 1.0
    if not np.isfinite(w_mean) or w_mean <= 0:
        w_mean = 1.0
    for split in splits:
        split.sample_weight = np.clip(split.sample_weight / w_mean, 0.05, 20.0).astype(np.float32)
    return {"feature_mean": mean.tolist(), "feature_std": std.tolist(), "train_sample_weight_mean": w_mean}


def _torch_split(split: SplitData, device: torch.device) -> dict[str, torch.Tensor]:
    return {
        "x": torch.as_tensor(split.x, dtype=torch.float32, device=device),
        "target": torch.as_tensor(split.target_delta, dtype=torch.float32, device=device),
        "gate": torch.as_tensor(split.gate[:, None], dtype=torch.float32, device=device),
        "weight": torch.as_tensor(split.sample_weight[:, None], dtype=torch.float32, device=device),
    }


def _predict(model: ResidualMLP, split: SplitData, device: torch.device) -> dict[str, np.ndarray]:
    model.eval()
    with torch.no_grad():
        x = torch.as_tensor(split.x, dtype=torch.float32, device=device)
        delta, sigma = model(x)
        delta_np = delta.cpu().numpy().astype(np.float32)
        sigma_np = sigma.cpu().numpy().astype(np.float32)
    gate = split.gate[:, None].astype(np.float32)
    corr = gate * delta_np
    cand_u = split.pred_u + corr[:, 0]
    cand_v = split.pred_v + corr[:, 1]
    return {
        "delta_u": delta_np[:, 0],
        "delta_v": delta_np[:, 1],
        "sigma_u": sigma_np[:, 0],
        "sigma_v": sigma_np[:, 1],
        "candidate_u": cand_u.astype(np.float32),
        "candidate_v": cand_v.astype(np.float32),
    }


def _metrics(split: SplitData, pred: dict[str, np.ndarray]) -> dict[str, float]:
    base_err = np.sqrt((split.pred_u - split.gt_u) ** 2 + (split.pred_v - split.gt_v) ** 2)
    cand_err = np.sqrt((pred["candidate_u"] - split.gt_u) ** 2 + (pred["candidate_v"] - split.gt_v) ** 2)
    gt_speed = np.maximum(split.gt_speed, 0.0)
    light = (gt_speed >= 5.0) & (gt_speed < 15.0)
    light_mod = (gt_speed >= 5.0) & (gt_speed < 30.0)
    rel = cand_err / np.maximum(gt_speed, 1e-6)
    delta_err = cand_err - base_err

    def rmse(values: np.ndarray) -> float:
        return float(np.sqrt(np.mean(values**2))) if values.size else 0.0

    def mean(values: np.ndarray) -> float:
        return float(np.mean(values)) if values.size else 0.0

    def q(values: np.ndarray, p: float) -> float:
        return float(np.quantile(values, p)) if values.size else 0.0

    return {
        "points": float(cand_err.size),
        "baseline_vector_rmse": rmse(base_err),
        "candidate_vector_rmse": rmse(cand_err),
        "delta_vector_rmse": rmse(cand_err) - rmse(base_err),
        "baseline_vector_mae": mean(base_err),
        "candidate_vector_mae": mean(cand_err),
        "baseline_p95": q(base_err, 0.95),
        "candidate_p95": q(cand_err, 0.95),
        "baseline_p99": q(base_err, 0.99),
        "candidate_p99": q(cand_err, 0.99),
        "baseline_floor10_relative_mae": mean(base_err / np.maximum(gt_speed, 10.0)),
        "candidate_floor10_relative_mae": mean(cand_err / np.maximum(gt_speed, 10.0)),
        "baseline_light_rmse": rmse(base_err[light]),
        "candidate_light_rmse": rmse(cand_err[light]),
        "baseline_light_mae": mean(base_err[light]),
        "candidate_light_mae": mean(cand_err[light]),
        "baseline_high_error_ge30_count": float(np.count_nonzero(base_err >= 30.0)),
        "candidate_high_error_ge30_count": float(np.count_nonzero(cand_err >= 30.0)),
        "new_light_moderate_relative_tail_failures": float(np.count_nonzero(light_mod & (rel > 2.0) & (delta_err > 5.0))),
        "candidate_delta_abs_mean": mean(np.sqrt(pred["delta_u"] ** 2 + pred["delta_v"] ** 2) * split.gate),
        "candidate_sigma_mean": mean((pred["sigma_u"] + pred["sigma_v"]) * 0.5),
    }


def _training_loss(
    model: ResidualMLP,
    tensors: dict[str, torch.Tensor],
    huber_beta: float,
    uncertainty_weight: float,
    delta_reg_weight: float,
) -> torch.Tensor:
    delta, sigma = model(tensors["x"])
    correction = tensors["gate"] * delta
    residual = correction - tensors["target"]
    huber = F.smooth_l1_loss(residual, torch.zeros_like(residual), beta=huber_beta, reduction="none").sum(dim=1, keepdim=True)
    obs_loss = torch.mean(tensors["weight"] * huber)
    nll = 0.5 * ((residual / torch.clamp(sigma, min=0.25, max=40.0)) ** 2 + 2.0 * torch.log(torch.clamp(sigma, min=0.25, max=40.0)))
    unc_loss = torch.mean(torch.clamp(nll, min=-2.0, max=20.0))
    delta_reg = torch.mean((correction / max(1e-6, model.delta_cap)) ** 2)
    return obs_loss + float(uncertainty_weight) * unc_loss + float(delta_reg_weight) * delta_reg


def _write_predictions(path: Path, splits: list[SplitData], preds: dict[str, dict[str, np.ndarray]]) -> None:
    fieldnames = [
        "row_id",
        "split",
        "gt_u",
        "gt_v",
        "gt_speed",
        "baseline_u",
        "baseline_v",
        "candidate_u",
        "candidate_v",
        "delta_u",
        "delta_v",
        "residual_gate",
        "sigma_u",
        "sigma_v",
        "baseline_vector_error",
        "candidate_vector_error",
        "delta_vector_error",
        "floor10_relative_error",
        "relative_error_ratio",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for split in splits:
            pred = preds[split.split]
            base_err = np.sqrt((split.pred_u - split.gt_u) ** 2 + (split.pred_v - split.gt_v) ** 2)
            cand_err = np.sqrt((pred["candidate_u"] - split.gt_u) ** 2 + (pred["candidate_v"] - split.gt_v) ** 2)
            for i, row_id in enumerate(split.row_id):
                writer.writerow(
                    {
                        "row_id": int(row_id),
                        "split": split.split,
                        "gt_u": float(split.gt_u[i]),
                        "gt_v": float(split.gt_v[i]),
                        "gt_speed": float(split.gt_speed[i]),
                        "baseline_u": float(split.pred_u[i]),
                        "baseline_v": float(split.pred_v[i]),
                        "candidate_u": float(pred["candidate_u"][i]),
                        "candidate_v": float(pred["candidate_v"][i]),
                        "delta_u": float(pred["delta_u"][i]),
                        "delta_v": float(pred["delta_v"][i]),
                        "residual_gate": float(split.gate[i]),
                        "sigma_u": float(pred["sigma_u"][i]),
                        "sigma_v": float(pred["sigma_v"][i]),
                        "baseline_vector_error": float(base_err[i]),
                        "candidate_vector_error": float(cand_err[i]),
                        "delta_vector_error": float(cand_err[i] - base_err[i]),
                        "floor10_relative_error": float(cand_err[i] / max(float(split.gt_speed[i]), 10.0)),
                        "relative_error_ratio": float(cand_err[i] / max(float(split.gt_speed[i]), 1e-6)),
                    }
                )


def _write_report(path: Path, metrics: dict[str, dict[str, float]], args: argparse.Namespace) -> None:
    lines = [
        "# Stage5 Residual PINN Report V1 Training",
        "",
        "This is a point-level residual MLP report. It is not a full-field PINN and it does not change Stage4 default recon.",
        "",
        "## Boundary",
        "",
        "- Split is frame/time based.",
        "- Candidate is `tp26 + gate * clipped_delta`; it cannot replace Stage4 by itself.",
        "- Training labels are aircraft point residuals inside the train split only.",
        "- Validation/test labels are evaluation only.",
        "",
        "## Metrics",
        "",
        "| split | points | baseline RMSE | candidate RMSE | delta RMSE | baseline P95 | candidate P95 | baseline P99 | candidate P99 | light RMSE base/cand | floor10 MAE base/cand | new light/mod fails |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for split in ("train", "val", "test"):
        row = metrics.get(split, {})
        lines.append(
            f"| `{split}` | {int(row.get('points', 0.0))} | "
            f"{row.get('baseline_vector_rmse', 0.0):.6f} | {row.get('candidate_vector_rmse', 0.0):.6f} | "
            f"{row.get('delta_vector_rmse', 0.0):+.6f} | {row.get('baseline_p95', 0.0):.6f} | "
            f"{row.get('candidate_p95', 0.0):.6f} | {row.get('baseline_p99', 0.0):.6f} | "
            f"{row.get('candidate_p99', 0.0):.6f} | "
            f"{row.get('baseline_light_rmse', 0.0):.6f}/{row.get('candidate_light_rmse', 0.0):.6f} | "
            f"{row.get('baseline_floor10_relative_mae', 0.0):.6f}/{row.get('candidate_floor10_relative_mae', 0.0):.6f} | "
            f"{int(row.get('new_light_moderate_relative_tail_failures', 0.0))} |"
        )
    lines.extend(
        [
            "",
            "## Training Config",
            "",
            f"- model: `{args.model}`",
            f"- epochs requested: `{args.max_epochs}`",
            f"- delta cap m/s: `{args.delta_cap_mps}`",
            f"- seed: `{args.seed}`",
            f"- requested device: `{args.device}`",
            f"- resolved device: `{metrics.get('training', {}).get('device', 'unknown')}`",
            f"- cuda available: `{metrics.get('training', {}).get('cuda_available', False)}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_device(device_arg: str) -> torch.device:
    requested = str(device_arg).lower()
    if requested == "cpu":
        return torch.device("cpu")
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("Requested --device cuda, but torch.cuda.is_available() is False")
        return torch.device("cuda:0")
    if requested != "auto":
        raise ValueError(f"Unsupported --device {device_arg}")
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Stage5 residual PINN report_v1 point model.")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--model", choices=["residual_mlp_v1"], default="residual_mlp_v1")
    parser.add_argument("--max-epochs", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--delta-cap-mps", type=float, default=3.0)
    parser.add_argument("--huber-beta", type=float, default=2.0)
    parser.add_argument("--uncertainty-loss-weight", type=float, default=0.03)
    parser.add_argument("--delta-reg-weight", type=float, default=0.02)
    parser.add_argument("--patience", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260608)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--allow-tf32", action="store_true")
    args = parser.parse_args()

    _set_seed(int(args.seed))
    if bool(args.allow_tf32):
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.set_float32_matmul_precision("high")
    train = _load_split(args.dataset_dir, "train")
    val = _load_split(args.dataset_dir, "val")
    test = _load_split(args.dataset_dir, "test")
    splits = [train, val, test]
    normalizer = _normalize_features(train, splits)
    device = _resolve_device(str(args.device))
    model = ResidualMLP(train.x.shape[1], int(args.width), int(args.layers), float(args.delta_cap_mps)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=float(args.learning_rate), weight_decay=1e-4)
    train_t = _torch_split(train, device)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    best_state = None
    best_val = float("inf")
    best_epoch = -1
    no_improve = 0
    history: list[dict[str, float]] = []
    n = train.x.shape[0]
    for epoch in range(1, int(args.max_epochs) + 1):
        model.train()
        order = np.random.permutation(n)
        losses: list[float] = []
        for start in range(0, n, int(args.batch_size)):
            idx = order[start : start + int(args.batch_size)]
            batch = {key: value[idx] for key, value in train_t.items()}
            loss = _training_loss(
                model,
                batch,
                huber_beta=float(args.huber_beta),
                uncertainty_weight=float(args.uncertainty_loss_weight),
                delta_reg_weight=float(args.delta_reg_weight),
            )
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
            opt.step()
            losses.append(float(loss.detach().cpu().item()))
        pred_val = _predict(model, val, device)
        val_metrics = _metrics(val, pred_val)
        val_score = val_metrics["candidate_vector_rmse"]
        history.append({"epoch": float(epoch), "train_loss": float(np.mean(losses)), "val_candidate_rmse": float(val_score)})
        if val_score + 1e-6 < best_val:
            best_val = val_score
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1
        if no_improve >= int(args.patience):
            break
    if best_state is not None:
        model.load_state_dict(best_state)

    preds = {split.split: _predict(model, split, device) for split in splits}
    metrics = {split.split: _metrics(split, preds[split.split]) for split in splits}
    metrics["training"] = {
        "best_epoch": float(best_epoch),
        "best_val_candidate_rmse": float(best_val),
        "device": str(device),
        "requested_device": str(args.device),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "allow_tf32": bool(args.allow_tf32),
        "cuda_memory_allocated_mb": float(torch.cuda.max_memory_allocated(device) / (1024.0**2)) if device.type == "cuda" else 0.0,
        "cuda_memory_reserved_mb": float(torch.cuda.max_memory_reserved(device) / (1024.0**2)) if device.type == "cuda" else 0.0,
    }

    ckpt = {
        "model_state_dict": model.state_dict(),
        "input_dim": int(train.x.shape[1]),
        "width": int(args.width),
        "layers": int(args.layers),
        "delta_cap_mps": float(args.delta_cap_mps),
        "normalizer": normalizer,
        "feature_schema": json.loads((args.dataset_dir / "feature_schema.json").read_text(encoding="utf-8")),
        "model_role": "point_level_residual_pinn_report_v1_not_full_field",
        "device_used": str(device),
    }
    torch.save(ckpt, args.out_dir / "checkpoint.pt")
    (args.out_dir / "normalizer.json").write_text(json.dumps(normalizer, indent=2), encoding="utf-8")
    (args.out_dir / "train_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.out_dir / "train_history.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["epoch", "train_loss", "val_candidate_rmse"])
        writer.writeheader()
        writer.writerows(history)
    _write_predictions(args.out_dir / "predictions_all.csv", splits, preds)
    _write_report(args.out_dir / "train_report.md", metrics, args)
    print(args.out_dir / "train_report.md")


if __name__ == "__main__":
    main()
