"""Apply a Stage5 residual PINN report checkpoint to a point dataset."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

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


class ResidualMLP(nn.Module):
    def __init__(self, input_dim: int, width: int, layers: int, delta_cap: float) -> None:
        super().__init__()
        modules: list[nn.Module] = []
        dim = input_dim
        for _ in range(max(1, layers)):
            modules.append(nn.Linear(dim, width))
            modules.append(nn.SiLU())
            modules.append(nn.LayerNorm(width))
            dim = width
        modules.append(nn.Linear(dim, 4))
        self.net = nn.Sequential(*modules)
        self.delta_cap = float(delta_cap)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        raw = self.net(x)
        delta = self.delta_cap * torch.tanh(raw[:, :2])
        sigma = 0.25 + F.softplus(raw[:, 2:4])
        return delta, sigma


def _load_npz(dataset_dir: Path, split: str) -> dict[str, np.ndarray]:
    with np.load(dataset_dir / f"features_{split}.npz", allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def _normalise(x: np.ndarray, normalizer: dict[str, object]) -> np.ndarray:
    mean = np.asarray(normalizer["feature_mean"], dtype=np.float32)
    std = np.asarray(normalizer["feature_std"], dtype=np.float32)
    std = np.where(std < 1e-6, 1.0, std)
    return ((x.astype(np.float32) - mean) / std).astype(np.float32)


def _predict(model: ResidualMLP, payload: dict[str, np.ndarray], normalizer: dict[str, object]) -> dict[str, np.ndarray]:
    x = _normalise(payload["x"].astype(np.float32), normalizer)
    with torch.no_grad():
        delta, sigma = model(torch.as_tensor(x, dtype=torch.float32))
    delta_np = delta.cpu().numpy().astype(np.float32)
    sigma_np = sigma.cpu().numpy().astype(np.float32)
    gate = payload["residual_gate_initial"].astype(np.float32)[:, None]
    corr = gate * delta_np
    cand_u = payload["pred_u"].astype(np.float32) + corr[:, 0]
    cand_v = payload["pred_v"].astype(np.float32) + corr[:, 1]
    return {"delta": delta_np, "sigma": sigma_np, "candidate_u": cand_u, "candidate_v": cand_v}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply residual PINN report_v1 checkpoint to point dataset.")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    ckpt = torch.load(args.checkpoint, map_location="cpu")
    model = ResidualMLP(
        int(ckpt["input_dim"]),
        int(ckpt["width"]),
        int(ckpt["layers"]),
        float(ckpt["delta_cap_mps"]),
    )
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_dir / "predictions_all.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
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
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for split in ("train", "val", "test"):
            payload = _load_npz(args.dataset_dir, split)
            pred = _predict(model, payload, ckpt["normalizer"])
            base_err = np.sqrt((payload["pred_u"] - payload["gt_u"]) ** 2 + (payload["pred_v"] - payload["gt_v"]) ** 2)
            cand_err = np.sqrt((pred["candidate_u"] - payload["gt_u"]) ** 2 + (pred["candidate_v"] - payload["gt_v"]) ** 2)
            for i, row_id in enumerate(payload["row_id"]):
                writer.writerow(
                    {
                        "row_id": int(row_id),
                        "split": split,
                        "gt_u": float(payload["gt_u"][i]),
                        "gt_v": float(payload["gt_v"][i]),
                        "gt_speed": float(payload["gt_speed"][i]),
                        "baseline_u": float(payload["pred_u"][i]),
                        "baseline_v": float(payload["pred_v"][i]),
                        "candidate_u": float(pred["candidate_u"][i]),
                        "candidate_v": float(pred["candidate_v"][i]),
                        "delta_u": float(pred["delta"][i, 0]),
                        "delta_v": float(pred["delta"][i, 1]),
                        "residual_gate": float(payload["residual_gate_initial"][i]),
                        "sigma_u": float(pred["sigma"][i, 0]),
                        "sigma_v": float(pred["sigma"][i, 1]),
                        "baseline_vector_error": float(base_err[i]),
                        "candidate_vector_error": float(cand_err[i]),
                        "delta_vector_error": float(cand_err[i] - base_err[i]),
                        "floor10_relative_error": float(cand_err[i] / max(float(payload["gt_speed"][i]), 10.0)),
                        "relative_error_ratio": float(cand_err[i] / max(float(payload["gt_speed"][i]), 1e-6)),
                    }
                )
    metadata = {
        "checkpoint": str(args.checkpoint),
        "dataset_dir": str(args.dataset_dir),
        "output": str(out_csv),
        "mode": "point_report_apply_not_full_field",
        "changes_stage4_recon": False,
    }
    (args.out_dir / "apply_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(out_csv)


if __name__ == "__main__":
    main()
