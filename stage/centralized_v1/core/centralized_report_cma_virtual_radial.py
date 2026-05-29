"""Visual report for CMA-RA virtual radial velocity proxy fields."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _scalar_text(value: Any) -> str:
    arr = np.asarray(value)
    if arr.shape == ():
        return str(arr.item())
    return str(value)


def _safe_stats(arr: np.ndarray) -> dict[str, float | int]:
    finite = np.asarray(arr, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {
            "finite_count": 0,
            "nonzero_count": 0,
            "min": 0.0,
            "p01": 0.0,
            "mean": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }
    return {
        "finite_count": int(finite.size),
        "nonzero_count": int(np.count_nonzero(arr)),
        "min": float(np.min(finite)),
        "p01": float(np.percentile(finite, 1)),
        "mean": float(np.mean(finite)),
        "p99": float(np.percentile(finite, 99)),
        "max": float(np.max(finite)),
    }


def _diverging_rgb(slice2d: np.ndarray, limit: float) -> np.ndarray:
    data = np.asarray(slice2d, dtype=np.float32)
    if limit <= 0:
        finite = data[np.isfinite(data)]
        limit = float(np.percentile(np.abs(finite), 99)) if finite.size else 1.0
    limit = max(1e-6, float(limit))
    norm = np.clip(data / limit, -1.0, 1.0)
    mag = np.abs(norm)
    rgb = np.empty(data.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = np.where(norm > 0, 255, (255 * (1.0 - mag))).astype(np.uint8)
    rgb[..., 1] = (255 * (1.0 - mag)).astype(np.uint8)
    rgb[..., 2] = np.where(norm < 0, 255, (255 * (1.0 - mag))).astype(np.uint8)
    rgb[~np.isfinite(data)] = 0
    return rgb


def _sequential_rgb(slice2d: np.ndarray, vmax: float | None = None) -> np.ndarray:
    data = np.asarray(slice2d, dtype=np.float32)
    finite = data[np.isfinite(data)]
    if vmax is None:
        vmax = float(np.percentile(finite, 99)) if finite.size else 1.0
    vmax = max(1e-6, float(vmax))
    norm = np.clip(data / vmax, 0.0, 1.0)
    rgb = np.empty(data.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = (25 + 220 * norm).astype(np.uint8)
    rgb[..., 1] = (35 + 180 * np.sqrt(norm)).astype(np.uint8)
    rgb[..., 2] = (55 + 80 * (1.0 - norm)).astype(np.uint8)
    rgb[~np.isfinite(data)] = 0
    return rgb


def _resize_tile(rgb: np.ndarray, width: int) -> Image.Image:
    image = Image.fromarray(rgb, mode="RGB")
    if image.width <= width:
        return image
    height = max(1, int(round(image.height * width / image.width)))
    return image.resize((width, height), Image.Resampling.BILINEAR)


def _captioned_tile(rgb: np.ndarray, caption: str, *, width: int, font: ImageFont.ImageFont) -> Image.Image:
    tile = _resize_tile(rgb, width)
    caption_h = 34
    out = Image.new("RGB", (tile.width, tile.height + caption_h), "white")
    out.paste(tile, (0, caption_h))
    draw = ImageDraw.Draw(out)
    draw.rectangle([0, 0, tile.width, caption_h], fill=(245, 245, 245))
    draw.text((8, 9), caption[:80], fill=(20, 20, 20), font=font)
    return out


def _parse_z_levels(text: str, shape: tuple[int, int, int]) -> list[int]:
    if text.strip():
        levels = [int(part.strip()) for part in text.split(",") if part.strip()]
    else:
        z_dim = shape[0]
        levels = sorted({max(0, min(z_dim - 1, z)) for z in (6, 14, 23, 29)})
    return [z for z in levels if 0 <= z < shape[0]]


def _write_stats(path: Path, arrays: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, arr in arrays.items():
        stats = _safe_stats(arr)
        rows.append({"field": key, "shape": "x".join(str(v) for v in arr.shape), **stats})
    fieldnames = ["field", "shape", "finite_count", "nonzero_count", "min", "p01", "mean", "p99", "max"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return rows


def build_report(npz_path: Path, out_dir: Path, z_levels_text: str, tile_width: int) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with np.load(npz_path, allow_pickle=True) as z:
        time_str = _scalar_text(z["time_str"]) if "time_str" in z.files else npz_path.stem
        cma_time = _scalar_text(z["cma_time_str"]) if "cma_time_str" in z.files else ""
        shape = tuple(int(v) for v in np.asarray(z["grid_shape"], dtype=np.int32).tolist())
        radial_keys = sorted(k for k in z.files if k.startswith("virtual_radial_velocity_") and k.endswith("_3d"))
        proxy_keys = sorted(k for k in z.files if k.startswith("proxy_virtual_radial_velocity_") and k.endswith("_3d"))
        arrays = {k: np.asarray(z[k], dtype=np.float32) for k in radial_keys + proxy_keys}
        for extra in (
            "cma_horizontal_speed_3d",
            "proxy_horizontal_speed_3d",
            "coverage_conf_3d",
            "stage4_prior_conf_3d",
            "obs_conf_aircraft_localized_3d",
            "cma_temporal_conf_3d",
            "cma_temporal_change_speed_3d",
            "cma_rapid_change_flag_3d",
            "site_pair_los_difference_3d",
        ):
            if extra in z.files:
                arrays[extra] = np.asarray(z[extra], dtype=np.float32)
        for key in sorted(k for k in z.files if k.startswith("los_geometry_weight_") and k.endswith("_3d")):
            arrays[key] = np.asarray(z[key], dtype=np.float32)
        speed = None
        if "u_cma_3d" in z.files and "v_cma_3d" in z.files:
            speed = np.sqrt(np.asarray(z["u_cma_3d"], dtype=np.float32) ** 2 + np.asarray(z["v_cma_3d"], dtype=np.float32) ** 2)
            arrays["cma_horizontal_speed_3d"] = speed.astype(np.float32)
        if "u_proxy_3d" in z.files and "v_proxy_3d" in z.files:
            proxy_speed = np.sqrt(np.asarray(z["u_proxy_3d"], dtype=np.float32) ** 2 + np.asarray(z["v_proxy_3d"], dtype=np.float32) ** 2)
            arrays["proxy_horizontal_speed_3d"] = proxy_speed.astype(np.float32)
        z_levels = _parse_z_levels(z_levels_text, shape)

    font = ImageFont.load_default()
    title_h = 76
    margin = 12
    gap = 10
    tiles: list[Image.Image] = []
    if radial_keys:
        finite = np.concatenate([arrays[k][np.isfinite(arrays[k])].ravel() for k in radial_keys])
        radial_limit = float(np.percentile(np.abs(finite), 99)) if finite.size else 1.0
    else:
        radial_limit = 1.0
    for key in radial_keys:
        site = key.replace("virtual_radial_velocity_", "").replace("_3d", "")
        for z_idx in z_levels:
            rgb = _diverging_rgb(arrays[key][z_idx], radial_limit)
            tiles.append(_captioned_tile(rgb, f"{site} virtual radial z={z_idx} lim=+/-{radial_limit:.1f} m/s", width=tile_width, font=font))
    for speed_key, label in (("cma_horizontal_speed_3d", "CMA horizontal speed"), ("proxy_horizontal_speed_3d", "Proxy horizontal speed")):
        if speed_key in arrays:
            speed_arr = arrays[speed_key]
            speed_vmax = float(np.percentile(speed_arr[np.isfinite(speed_arr)], 99)) if np.isfinite(speed_arr).any() else 1.0
            for z_idx in z_levels[:2]:
                rgb = _sequential_rgb(speed_arr[z_idx], speed_vmax)
                tiles.append(_captioned_tile(rgb, f"{label} z={z_idx} vmax={speed_vmax:.1f} m/s", width=tile_width, font=font))
    for key in ("stage4_prior_conf_3d", "coverage_conf_3d", "obs_conf_aircraft_localized_3d", "cma_temporal_conf_3d"):
        if key in arrays:
            for z_idx in z_levels[:2]:
                rgb = _sequential_rgb(arrays[key][z_idx], 1.0)
                tiles.append(_captioned_tile(rgb, f"{key} z={z_idx}", width=tile_width, font=font))
    if "cma_temporal_change_speed_3d" in arrays:
        finite = arrays["cma_temporal_change_speed_3d"][np.isfinite(arrays["cma_temporal_change_speed_3d"])]
        vmax = float(np.percentile(finite, 99)) if finite.size else 1.0
        for z_idx in z_levels[:2]:
            rgb = _sequential_rgb(arrays["cma_temporal_change_speed_3d"][z_idx], vmax)
            tiles.append(_captioned_tile(rgb, f"cma_temporal_change_speed_3d z={z_idx} vmax={vmax:.1f} m/s", width=tile_width, font=font))
    for key in ("cma_rapid_change_flag_3d", "site_pair_los_difference_3d"):
        if key in arrays:
            vmax = 1.0 if key == "cma_rapid_change_flag_3d" else float(np.percentile(arrays[key][np.isfinite(arrays[key])], 99))
            vmax = max(vmax, 1e-6)
            for z_idx in z_levels[:2]:
                rgb = _sequential_rgb(arrays[key][z_idx], vmax)
                tiles.append(_captioned_tile(rgb, f"{key} z={z_idx} vmax={vmax:.2f}", width=tile_width, font=font))
    for key in sorted(k for k in arrays if k.startswith("los_geometry_weight_") and k.endswith("_3d")):
        site = key.replace("los_geometry_weight_", "").replace("_3d", "")
        for z_idx in z_levels[:1]:
            rgb = _sequential_rgb(arrays[key][z_idx], 1.0)
            tiles.append(_captioned_tile(rgb, f"{site} LOS geometry weight z={z_idx}", width=tile_width, font=font))

    cols = 2 if len(tiles) <= 8 else 4
    rows = int(np.ceil(len(tiles) / cols)) if tiles else 1
    tile_w = max((tile.width for tile in tiles), default=tile_width)
    tile_h = max((tile.height for tile in tiles), default=tile_width)
    canvas_w = margin * 2 + cols * tile_w + (cols - 1) * gap
    canvas_h = margin * 2 + title_h + rows * tile_h + (rows - 1) * gap
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, margin), f"CMA-RA virtual radial velocity pattern - Stage2 {time_str}", fill=(0, 0, 0), font=font)
    draw.text((margin, margin + 18), f"CMA time {cma_time}; blue=toward negative LOS projection, red=positive", fill=(45, 45, 45), font=font)
    draw.text((margin, margin + 36), "Speed panels are geometry-invariant; radial panels vary with radar line-of-sight geometry.", fill=(45, 45, 45), font=font)
    draw.text((margin, margin + 54), f"source NPZ: {npz_path}", fill=(45, 45, 45), font=font)
    for idx, tile in enumerate(tiles):
        row = idx // cols
        col = idx % cols
        x = margin + col * (tile_w + gap)
        y = margin + title_h + row * (tile_h + gap)
        canvas.paste(tile, (x, y))

    png_path = out_dir / f"{time_str}_cma_virtual_radial_pattern.png"
    stats_path = out_dir / f"{time_str}_cma_virtual_radial_stats.csv"
    md_path = out_dir / f"{time_str}_cma_virtual_radial_pattern.md"
    canvas.save(png_path)
    rows_out = _write_stats(stats_path, arrays)
    md_lines = [
        f"# CMA-RA Virtual Radial Pattern - {time_str}",
        "",
        f"- Source NPZ: `{npz_path}`",
        f"- CMA time: `{cma_time}`",
        f"- Pattern PNG: `{png_path}`",
        f"- Stats CSV: `{stats_path}`",
        "",
        "## Field Summary",
        "",
        "| field | shape | min | mean | max | nonzero |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows_out:
        md_lines.append(
            f"| `{row['field']}` | `{row['shape']}` | {float(row['min']):.6f} | "
            f"{float(row['mean']):.6f} | {float(row['max']):.6f} | {int(row['nonzero_count'])} |"
        )
    md_lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The virtual radial velocity fields are line-of-sight projections of CMA u/v/w onto synthetic radar-site geometry. They are proxy radial observations for class-3DVAR experiments, not measured Doppler velocity volumes.",
        ]
    )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return {"png": str(png_path), "stats": str(stats_path), "md": str(md_path)}


def _read_npz_list(npz_list_file: Path | None, npz_dir: Path | None) -> list[Path]:
    if npz_list_file:
        payload = json.loads(npz_list_file.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"--npz-list-file must contain a JSON list: {npz_list_file}")
        return [Path(str(item)) for item in payload]
    if npz_dir:
        return sorted(npz_dir.glob("cma_ra_virtual_radial_3dvar_*.npz"))
    return []


def _write_shard_npz_list(path: Path, npz_paths: list[Path]) -> None:
    path.write_text(json.dumps([str(p) for p in npz_paths], ensure_ascii=False, indent=2), encoding="utf-8")


def _run_parent_shards(args: argparse.Namespace, npz_paths: list[Path]) -> list[dict[str, str]]:
    workers = max(1, int(args.num_workers))
    shard_dir = args.out_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards = [[] for _ in range(workers)]
    for idx, npz_path in enumerate(npz_paths):
        shards[idx % workers].append(npz_path)
    procs: list[tuple[subprocess.Popen[str], Path, Path]] = []
    env_base = os.environ.copy()
    env_base.setdefault("OMP_NUM_THREADS", "1")
    env_base.setdefault("OPENBLAS_NUM_THREADS", "1")
    for shard_idx, shard_npz in enumerate(shards):
        if not shard_npz:
            continue
        npz_file = shard_dir / f"cma_visual_shard_{shard_idx:02d}_npz.json"
        summary_file = shard_dir / f"cma_visual_shard_{shard_idx:02d}_summary.json"
        log_file = shard_dir / f"cma_visual_shard_{shard_idx:02d}.log"
        _write_shard_npz_list(npz_file, shard_npz)
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--npz-list-file",
            str(npz_file),
            "--out-dir",
            str(args.out_dir),
            "--z-levels",
            str(args.z_levels),
            "--tile-width",
            str(args.tile_width),
            "--num-workers",
            str(workers),
            "--shard-id",
            str(shard_idx),
            "--shard-summary",
            str(summary_file),
        ]
        with log_file.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
        procs.append((proc, summary_file, log_file))
    summaries: list[dict[str, str]] = []
    for proc, summary_file, log_file in procs:
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"CMA visual shard failed rc={rc}; see {log_file}")
        summaries.extend(json.loads(summary_file.read_text(encoding="utf-8")))
    return sorted(summaries, key=lambda row: str(row["md"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize CMA-RA virtual radial velocity proxy fields.")
    parser.add_argument("--npz", type=Path)
    parser.add_argument("--npz-dir", type=Path)
    parser.add_argument("--npz-list-file", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--z-levels", default="")
    parser.add_argument("--tile-width", type=int, default=320)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--shard-id", type=int, default=-1)
    parser.add_argument("--shard-summary", type=Path)
    args = parser.parse_args()
    npz_paths = _read_npz_list(args.npz_list_file, args.npz_dir)
    if args.npz:
        npz_paths.append(args.npz)
    npz_paths = list(dict.fromkeys(npz_paths))
    if not npz_paths:
        raise ValueError("Provide --npz, --npz-dir, or --npz-list-file")
    if int(args.shard_id) < 0 and int(args.num_workers) > 1 and len(npz_paths) > 1:
        outputs = _run_parent_shards(args, npz_paths)
        summary_path = args.out_dir / "cma_virtual_radial_visual_summary.json"
        summary_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
        print(summary_path)
        return
    outputs = [build_report(path, args.out_dir, str(args.z_levels), int(args.tile_width)) for path in npz_paths]
    summary_path = args.shard_summary if args.shard_summary else args.out_dir / "cma_virtual_radial_visual_summary.json"
    summary_path.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(outputs[0] if len(outputs) == 1 else {"summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
