"""Query a Stage4 reconstructed wind field at a voxel or random active point."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_contract import C4_BLINDZONE_MASK, C4_RECON_CONF, C4_RECON_MASK, C4_RECON_U, C4_RECON_V
from stage.centralized_v1.core.centralized_stage4_ground_recon import _idx_to_geo_point


def _load_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=True) as z:
        return {k: z[k] for k in z.files}


def _query_row(npz: dict[str, np.ndarray], z: int, y: int, x: int) -> dict[str, float | int | bool]:
    u = np.asarray(npz[C4_RECON_U], dtype=np.float32)
    v = np.asarray(npz[C4_RECON_V], dtype=np.float32)
    conf = np.asarray(npz[C4_RECON_CONF], dtype=np.float32)
    mask = np.asarray(npz[C4_RECON_MASK], dtype=np.float32) > 0
    blind = np.asarray(npz.get(C4_BLINDZONE_MASK, np.zeros_like(conf)), dtype=np.float32) > 0
    if not (0 <= z < u.shape[0] and 0 <= y < u.shape[1] and 0 <= x < u.shape[2]):
        raise ValueError(f"Query voxel outside grid shape {u.shape}: z={z}, y={y}, x={x}")
    geo = _idx_to_geo_point(tuple(int(vv) for vv in u.shape), z, y, x)
    uq = float(u[z, y, x])
    vq = float(v[z, y, x])
    return {
        "z": int(z),
        "y": int(y),
        "x": int(x),
        "lat": float(geo["lat"]),
        "lon": float(geo["lon"]),
        "alt_m": float(geo["alt_m"]),
        "u_mps": uq,
        "v_mps": vq,
        "speed_mps": float(math.sqrt(uq * uq + vq * vq)),
        "confidence": float(conf[z, y, x]),
        "active_reconstructed": bool(mask[z, y, x]),
        "low_conf_fill": bool(blind[z, y, x]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Query one or more Stage4 reconstructed wind voxels.")
    parser.add_argument("--npz", type=Path, required=True)
    parser.add_argument("--z", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--x", type=int)
    parser.add_argument("--random-active", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-csv", type=Path)
    args = parser.parse_args()

    npz = _load_npz(args.npz)
    rows = []
    if args.random_active > 0:
        mask = np.asarray(npz[C4_RECON_MASK], dtype=np.float32) > 0
        coords = np.column_stack(np.where(mask))
        if coords.size == 0:
            raise ValueError(f"No active reconstructed voxels in {args.npz}")
        rng = np.random.default_rng(int(args.seed))
        take = min(int(args.random_active), int(coords.shape[0]))
        for z, y, x in coords[rng.choice(coords.shape[0], size=take, replace=False)]:
            rows.append(_query_row(npz, int(z), int(y), int(x)))
    else:
        if args.z is None or args.y is None or args.x is None:
            raise ValueError("Provide --z/--y/--x or --random-active N.")
        rows.append(_query_row(npz, int(args.z), int(args.y), int(args.x)))

    text = json.dumps(rows, ensure_ascii=False, indent=2)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(text, encoding="utf-8")
    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.out_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(text)


if __name__ == "__main__":
    main()
