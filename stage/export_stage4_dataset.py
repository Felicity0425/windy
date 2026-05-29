import argparse
import json
import os
from glob import glob

import numpy as np


REQUIRED_KEYS = [
    "storage_mode",
    "grid_shape",
    "radar_2d",
    "trajectory_3d",
    "recon_u_3d",
    "recon_v_3d",
    "recon_mask_3d",
    "recon_confidence_3d",
    "flight_offsets",
    "flight_idx_flat",
    "flight_u_flat",
    "flight_v_flat",
    "flight_mask",
    "flight_comm_allowed",
    "flight_st_conf",
    "flight_st_likelihood",
    "flight_time_conf",
    "flight_space_conf",
    "flight_time_likelihood",
    "flight_space_likelihood",
    "flight_comm_weight",
    "flight_has_wind_obs",
    "flight_intent",
    "ff_comm_allowed",
    "ff_st_conf",
    "ff_st_likelihood",
    "ff_comm_weight",
    "ff_motion_allowed",
    "ff_motion_weight",
    "ff_wind_allowed",
    "ff_wind_weight",
    "comm_joint_idx",
    "comm_wind_idx",
    "comm_motion_idx",
]


def _restore_dense_from_sparse(idx, val, shape, fill_value=0.0):
    arr = np.full(shape, fill_value, dtype=np.float32)
    if idx is None or val is None:
        return arr
    idx = np.asarray(idx)
    val = np.asarray(val)
    if idx.size == 0 or val.size == 0:
        return arr
    idx = idx.astype(np.int64).reshape(-1)
    val = val.astype(np.float32).reshape(-1)
    arr.reshape(-1)[idx] = val
    return arr


def _get(npz, key, default=None):
    if key in npz.files:
        return npz[key]
    return default


def _compute_split_index(i, total):
    r = i / max(1, total)
    if r <= 0.70:
        return "train"
    if r <= 0.85:
        return "val"
    return "test"


def main():
    parser = argparse.ArgumentParser(description="Export stage4_output to training-ready dataset with progress")
    parser.add_argument("--src", type=str, default="stage4_output", help="Source stage4 directory")
    parser.add_argument("--dst", type=str, default="dataset_output_stage4_clean", help="Target dataset directory")
    parser.add_argument("--compressed", action="store_true", help="Use np.savez_compressed")
    parser.add_argument("--progress_every", type=int, default=50, help="Print progress every N files")
    args = parser.parse_args()

    src = os.path.abspath(args.src)
    dst = os.path.abspath(args.dst)
    os.makedirs(dst, exist_ok=True)

    npz_files = sorted(glob(os.path.join(src, "frame_*.npz")))
    if not npz_files:
        raise RuntimeError(f"No frame_*.npz found in: {src}")

    total = len(npz_files)
    print(f"Found {total} stage4 frames in {src}", flush=True)

    split = {"train": [], "val": [], "test": []}
    bad = []
    kept = 0

    for i, fp in enumerate(npz_files, 1):
        fn = os.path.basename(fp)
        try:
            with np.load(fp, allow_pickle=True) as npz:
                radar_2d = _get(npz, "radar_2d")
                trajectory_3d = _get(npz, "trajectory_3d")
                grid_shape = _get(npz, "grid_shape")
                recon_u = _get(npz, "recon_u_3d")
                recon_v = _get(npz, "recon_v_3d")
                recon_mask = _get(npz, "recon_mask_3d")
                recon_conf = _get(npz, "recon_confidence_3d")

                if grid_shape is None:
                    if recon_u is None:
                        raise KeyError("missing grid_shape and recon_u_3d")
                    grid_shape = np.array(recon_u.shape, dtype=np.int32)
                grid_shape = tuple(int(x) for x in np.asarray(grid_shape).tolist())

                if trajectory_3d is None:
                    traj_idx = _get(npz, "trajectory_idx")
                    traj_val = _get(npz, "trajectory_val")
                    if traj_idx is not None and traj_val is not None:
                        trajectory_3d = _restore_dense_from_sparse(traj_idx, traj_val, grid_shape, fill_value=0.0)
                    else:
                        trajectory_3d = np.zeros(grid_shape, dtype=np.float32)

                if radar_2d is None or recon_u is None or recon_v is None or recon_mask is None:
                    raise KeyError("missing one of radar_2d / recon_u_3d / recon_v_3d / recon_mask_3d")

                radar_2d = np.asarray(radar_2d, dtype=np.float32)
                trajectory_3d = np.asarray(trajectory_3d, dtype=np.float32)
                recon_u = np.asarray(recon_u, dtype=np.float32)
                recon_v = np.asarray(recon_v, dtype=np.float32)
                recon_mask = np.asarray(recon_mask, dtype=np.float32)
                recon_conf = np.asarray(recon_conf if recon_conf is not None else recon_mask, dtype=np.float32)

                if np.isnan(radar_2d).any():
                    raise ValueError("radar_2d contains NaN")
                if np.isnan(trajectory_3d).any():
                    raise ValueError("trajectory_3d contains NaN")
                if np.isnan(recon_u).any() or np.isnan(recon_v).any():
                    raise ValueError("recon field contains NaN")
                if np.isnan(recon_mask).any() or np.isnan(recon_conf).any():
                    raise ValueError("recon mask/conf contains NaN")
                if float(recon_mask.sum()) == 0.0:
                    raise ValueError("recon_mask sum is zero")

                flight_payload = {
                    k: _get(npz, k, None)
                    for k in [
                        "flight_offsets", "flight_idx_flat", "flight_u_flat", "flight_v_flat",
                        "flight_mask", "flight_comm_allowed", "flight_st_conf",
                        "flight_st_likelihood", "flight_time_conf", "flight_space_conf",
                        "flight_time_likelihood", "flight_space_likelihood", "flight_comm_weight",
                        "flight_has_wind_obs", "flight_intent", "ff_comm_allowed",
                        "ff_st_conf", "ff_st_likelihood", "ff_comm_weight", "ff_motion_allowed",
                        "ff_motion_weight", "ff_wind_allowed", "ff_wind_weight",
                        "comm_joint_idx", "comm_wind_idx", "comm_motion_idx",
                    ]
                }

                payload = {
                    "storage_mode": np.array("slim", dtype="<U4"),
                    "grid_shape": np.asarray(grid_shape, dtype=np.int32),
                    "radar_2d": radar_2d.astype(np.float32),
                    "trajectory_3d": trajectory_3d.astype(np.float32),
                    "recon_u_3d": recon_u.astype(np.float32),
                    "recon_v_3d": recon_v.astype(np.float32),
                    "recon_mask_3d": recon_mask.astype(np.float32),
                    "recon_confidence_3d": recon_conf.astype(np.float32),
                }
                for k, v in flight_payload.items():
                    if v is None:
                        continue
                    payload[k] = np.asarray(v)

                out_fp = os.path.join(dst, fn)
                if args.compressed:
                    np.savez_compressed(out_fp, **payload)
                else:
                    np.savez(out_fp, **payload)

                kept += 1
                split[_compute_split_index(i, total)].append(fn)

        except Exception as e:
            bad.append({"filename": fn, "error": str(e)})

        if i % max(1, args.progress_every) == 0 or i == total:
            print(
                f"[Export] {i}/{total} checked | kept={kept} | bad={len(bad)} | last={fn}",
                flush=True,
            )

    with open(os.path.join(dst, "dataset_split.json"), "w", encoding="utf-8") as f:
        json.dump({"splits": split}, f, ensure_ascii=False, indent=2)

    report = {
        "source": src,
        "target": dst,
        "total": total,
        "kept": kept,
        "bad": len(bad),
        "filtered_ratio": float(len(bad) / max(1, total)),
        "bad_samples": bad[:50],
        "required_keys": REQUIRED_KEYS,
    }
    with open(os.path.join(dst, "stage4_clean_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("Done.", flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
