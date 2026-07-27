"""Build one-shot altitude distribution tables across Stage1, Stage2 domain, and Stage4 holdout."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import ALT_MAX, ALT_MIN, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from stage.centralized_v1.core.centralized_stage4_ground_recon import _records


HEURISTIC_BIN_SPECS: list[tuple[str, float, float]] = [
    ("0-3km", 0.0, 3000.0),
    ("3-6km", 3000.0, 6000.0),
    ("6-9km", 6000.0, 9000.0),
    ("9-12km", 9000.0, 12000.0),
    ("12-13km", 12000.0, 13000.0),
    ("13-14km", 13000.0, 14000.0),
    ("14-15km", 14000.0, 15000.0),
    ("15-16km", 15000.0, 16000.0),
]

RAW_BIN_SPECS: list[tuple[str, float, float]] = [
    ("0-3km", 0.0, 3000.0),
    ("3-6km", 3000.0, 6000.0),
    ("6-9km", 6000.0, 9000.0),
    ("9-12km", 9000.0, 12000.0),
    ("12-15km", 12000.0, 15000.0),
    ("15-18km", 15000.0, 18000.0),
    ("18-30km", 18000.0, 30000.0),
    ("30-100km", 30000.0, 100000.0),
    ("100km+", 100000.0, float("inf")),
]


def _to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _heuristic_altitude_m(values: pd.Series) -> tuple[pd.Series, dict[str, Any]]:
    raw = pd.to_numeric(values, errors="coerce").astype(float)
    corrected = raw.copy()
    mask_ft = (raw > 16000.0) & (raw <= 60000.0)
    corrected.loc[mask_ft] = raw.loc[mask_ft] * 0.3048
    mask_bad = (~np.isfinite(corrected)) | (corrected < 0.0) | (corrected > 16000.0)
    stats = {
        "raw_nonnull_count": int(np.count_nonzero(np.isfinite(raw))),
        "direct_meter_count": int(np.count_nonzero((raw >= 0.0) & (raw <= 16000.0))),
        "feet_converted_count": int(np.count_nonzero(mask_ft)),
        "bad_after_heuristic_count": int(np.count_nonzero(mask_bad)),
        "valid_after_heuristic_count": int(np.count_nonzero(~mask_bad)),
    }
    corrected.loc[mask_bad] = np.nan
    return corrected, stats


def _bin_counter(values: pd.Series, specs: list[tuple[str, float, float]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    arr = pd.to_numeric(values, errors="coerce").astype(float)
    for value in arr:
        if not math.isfinite(value):
            continue
        for label, lower, upper in specs:
            if lower <= value < upper:
                counter[label] += 1
                break
    return counter


def _counter_rows(counter: Counter[str], total: int, specs: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, lower, upper in specs:
        count = int(counter.get(label, 0))
        rows.append(
            {
                "altitude_bin": label,
                "range_m": f"[{lower:.0f}, {upper if math.isfinite(upper) else float('inf'):.0f})" if math.isfinite(upper) else f">={lower:.0f}",
                "count": count,
                "fraction": (count / total) if total > 0 else 0.0,
                "percent": (count / total * 100.0) if total > 0 else 0.0,
            }
        )
    return rows


def _stage1_source_phase_summary(df: pd.DataFrame, corrected_alt_m: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    valid = corrected_alt_m.notna()
    if "source" in df.columns:
        for source_name, source_df in df.loc[valid].groupby("source"):
            source_alt = corrected_alt_m.loc[source_df.index]
            out[f"source::{source_name}"] = {
                "valid_count": int(source_alt.shape[0]),
                "ge12km_count": int(np.count_nonzero(source_alt >= 12000.0)),
                "ge12km_fraction": float(np.count_nonzero(source_alt >= 12000.0) / max(1, source_alt.shape[0])),
            }
    if "飞行阶段" in df.columns:
        phase_table = pd.crosstab(
            df.loc[valid, "飞行阶段"],
            pd.cut(
                corrected_alt_m.loc[valid],
                bins=[0.0, 3000.0, 6000.0, 9000.0, 12000.0, 16000.0],
                labels=["0-3km", "3-6km", "6-9km", "9-12km", "12-16km"],
                right=False,
            ),
            dropna=False,
        )
        out["phase_table"] = {
            str(index): {str(col): int(phase_table.loc[index, col]) for col in phase_table.columns}
            for index in phase_table.index
        }
    return out


def _stage2_domain_mask(df: pd.DataFrame) -> pd.Series:
    lat = pd.to_numeric(df.get("lat_clean"), errors="coerce").astype(float)
    lon = pd.to_numeric(df.get("lon_clean"), errors="coerce").astype(float)
    alt = pd.to_numeric(df.get("alt_meters"), errors="coerce").astype(float)
    return (
        lat.ge(LAT_MIN)
        & lat.le(LAT_MAX)
        & lon.ge(LON_MIN)
        & lon.le(LON_MAX)
        & alt.ge(ALT_MIN)
        & alt.le(ALT_MAX)
    )


def _read_frame_times(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return set()
    if stripped.startswith("["):
        payload = json.loads(stripped)
        return {str(item).strip() for item in payload if str(item).strip()}
    if "," in stripped and "\n" not in stripped:
        return {token.strip() for token in stripped.split(",") if token.strip()}
    return {line.strip() for line in text.splitlines() if line.strip()}


def _stage2_window_distribution(stage2_summary_path: Path, frame_times_file: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    wanted = _read_frame_times(frame_times_file)
    with stage2_summary_path.open("r", encoding="utf-8") as f:
        rows = json.load(f)
    selected = [row for row in rows if str(row.get("time_str", "")).strip() in wanted]
    frame_alt_rows: list[dict[str, Any]] = []
    total_frames = 0
    for row in selected:
        total_frames += 1
        npz_path = Path(row["multimodal_vox_path"])
        with np.load(npz_path, allow_pickle=True) as npz:
            wind_records = _records(npz.get("wind_records"))
            if not wind_records:
                continue
            z_alt_step_m = _safe_float(row.get("z_altitude_step_m"), 500.0)
            for item in wind_records:
                alt_m = _safe_float(item.get("alt_meters"))
                if not math.isfinite(alt_m):
                    z_value = _safe_float(item.get("z"))
                    if math.isfinite(z_value) and z_value >= 0.0:
                        alt_m = ALT_MIN + z_value * z_alt_step_m
                if math.isfinite(alt_m) and ALT_MIN <= alt_m <= ALT_MAX:
                    frame_alt_rows.append({"time_str": str(row["time_str"]), "alt_m": alt_m})
    df = pd.DataFrame(frame_alt_rows)
    return df, {"selected_frame_count": total_frames, "selected_stage2_row_count": len(selected)}


def _stage4_holdout_distribution(point_csv: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with point_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            alt_m = _safe_float(row.get("alt_m"))
            if math.isfinite(alt_m):
                rows.append({"time_str": str(row.get("time_str", "")).strip(), "alt_m": alt_m})
    return pd.DataFrame(rows)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    stage1 = report["stage1"]
    stage2 = report["stage2_in_domain"]
    stage4 = report["stage4_holdout"]
    lines = [
        "# Stage altitude distribution report",
        "",
        f"- Generated: `{report['generated_utc']}`",
        f"- Stage1 wind parquet: `{report['stage1_wind_path']}`",
        f"- Stage2 summary: `{report['stage2_summary_path']}`",
        f"- Stage4 point CSV: `{report['stage4_point_csv']}`",
        f"- Frame-times file: `{report['frame_times_file']}`",
        "",
        "## Headline",
        "",
        f"- Stage1 clean wind rows: `{stage1['row_count']}`",
        f"- Stage1 heuristic-valid altitude rows: `{stage1['heuristic_valid_count']}`",
        f"- Stage2 selected frames: `{stage2['selected_frame_count']}`",
        f"- Stage2 in-domain wind-record rows: `{stage2['row_count']}`",
        f"- Stage4 holdout rows: `{stage4['row_count']}`",
        "",
        "## Key interpretation",
        "",
        f"- Stage1 raw `alt_meters` has suspicious high values up to `{stage1['raw_alt_max_m']:.0f}` m, so raw full-table altitude stats are not directly usable.",
        f"- Heuristic-corrected Stage1 `12km+` fraction: `{stage1['heuristic_ge12km_fraction'] * 100.0:.3f}%`",
        f"- Stage2 in-domain `12km+` fraction: `{stage2['ge12km_fraction'] * 100.0:.3f}%`",
        f"- Stage4 holdout `12km+` fraction: `{stage4['ge12km_fraction'] * 100.0:.3f}%`",
        "",
        "## Why three tables differ",
        "",
        "- Stage1 full distribution reflects all cleaned aircraft wind records before Stage2 grid-domain clipping.",
        "- Stage2 in-domain distribution reflects only current-window wind records that actually entered the 0-15 km Stage2 domain for the selected frame set.",
        "- Stage4 holdout distribution reflects only the final strict evaluation subset, so it can over-emphasize difficult strata such as high altitude.",
        "",
        "## Stage1 altitude quality note",
        "",
        f"- Direct `0-16 km` rows kept as meters: `{stage1['heuristic_stats']['direct_meter_count']}`",
        f"- `16-60 km` rows treated as likely feet and converted: `{stage1['heuristic_stats']['feet_converted_count']}`",
        f"- Remaining bad rows after heuristic: `{stage1['heuristic_stats']['bad_after_heuristic_count']}`",
        "",
        "## Main conclusion",
        "",
        "Stage1 full-data `12km+` is not the dominant regime after heuristic correction, but the current Stage4 holdout subset is much more high-altitude-heavy. That means the current 200-frame evaluation set is a deliberately difficult subset for altitude-related error analysis, not a mirror of the whole raw aircraft dataset.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one-shot altitude distribution tables across Stage1, Stage2, and Stage4.")
    parser.add_argument("--stage1-wind", type=Path, required=True)
    parser.add_argument("--stage2-summary", type=Path, required=True)
    parser.add_argument("--frame-times-file", type=Path, required=True)
    parser.add_argument("--stage4-point-csv", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stage1_df = pd.read_parquet(args.stage1_wind)
    heuristic_alt_m, heuristic_stats = _heuristic_altitude_m(stage1_df["alt_meters"])
    raw_alt_m = pd.to_numeric(stage1_df["alt_meters"], errors="coerce").astype(float)

    stage1_raw_counter = _bin_counter(raw_alt_m, RAW_BIN_SPECS)
    stage1_heuristic_counter = _bin_counter(heuristic_alt_m, HEURISTIC_BIN_SPECS)

    stage2_df, stage2_meta = _stage2_window_distribution(args.stage2_summary, args.frame_times_file)
    stage2_counter = _bin_counter(stage2_df.get("alt_m", pd.Series(dtype=float)), HEURISTIC_BIN_SPECS)

    stage4_df = _stage4_holdout_distribution(args.stage4_point_csv)
    stage4_counter = _bin_counter(stage4_df.get("alt_m", pd.Series(dtype=float)), HEURISTIC_BIN_SPECS)

    stage1_heuristic_total = int(np.count_nonzero(np.isfinite(heuristic_alt_m)))
    stage2_total = int(len(stage2_df))
    stage4_total = int(len(stage4_df))

    stage1_raw_rows = _counter_rows(stage1_raw_counter, int(len(stage1_df)), RAW_BIN_SPECS)
    stage1_heuristic_rows = _counter_rows(stage1_heuristic_counter, stage1_heuristic_total, HEURISTIC_BIN_SPECS)
    stage2_rows = _counter_rows(stage2_counter, stage2_total, HEURISTIC_BIN_SPECS)
    stage4_rows = _counter_rows(stage4_counter, stage4_total, HEURISTIC_BIN_SPECS)

    compare_rows: list[dict[str, Any]] = []
    for idx, (label, _lower, _upper) in enumerate(HEURISTIC_BIN_SPECS):
        s1 = stage1_heuristic_rows[idx]
        s2 = stage2_rows[idx]
        s4 = stage4_rows[idx]
        compare_rows.append(
            {
                "altitude_bin": label,
                "stage1_full_count": s1["count"],
                "stage1_full_percent": s1["percent"],
                "stage2_in_domain_count": s2["count"],
                "stage2_in_domain_percent": s2["percent"],
                "stage4_holdout_count": s4["count"],
                "stage4_holdout_percent": s4["percent"],
            }
        )

    stage1_phase_source = _stage1_source_phase_summary(stage1_df, heuristic_alt_m)

    report = {
        "generated_utc": _to_iso_utc(datetime.now(timezone.utc)),
        "stage1_wind_path": str(args.stage1_wind),
        "stage2_summary_path": str(args.stage2_summary),
        "stage4_point_csv": str(args.stage4_point_csv),
        "frame_times_file": str(args.frame_times_file),
        "stage1": {
            "row_count": int(len(stage1_df)),
            "raw_alt_min_m": float(np.nanmin(raw_alt_m.to_numpy(dtype=float))),
            "raw_alt_max_m": float(np.nanmax(raw_alt_m.to_numpy(dtype=float))),
            "heuristic_valid_count": stage1_heuristic_total,
            "heuristic_stats": heuristic_stats,
            "heuristic_ge12km_count": int(np.count_nonzero(heuristic_alt_m >= 12000.0)),
            "heuristic_ge12km_fraction": float(np.count_nonzero(heuristic_alt_m >= 12000.0) / max(1, stage1_heuristic_total)),
            "raw_distribution_rows": stage1_raw_rows,
            "heuristic_distribution_rows": stage1_heuristic_rows,
            "phase_source_summary": stage1_phase_source,
        },
        "stage2_in_domain": {
            "row_count": stage2_total,
            "selected_frame_count": int(stage2_meta["selected_frame_count"]),
            "selected_stage2_row_count": int(stage2_meta["selected_stage2_row_count"]),
            "ge12km_count": int(np.count_nonzero(pd.to_numeric(stage2_df.get("alt_m", pd.Series(dtype=float)), errors="coerce") >= 12000.0)),
            "ge12km_fraction": float(np.count_nonzero(pd.to_numeric(stage2_df.get("alt_m", pd.Series(dtype=float)), errors="coerce") >= 12000.0) / max(1, stage2_total)),
            "distribution_rows": stage2_rows,
        },
        "stage4_holdout": {
            "row_count": stage4_total,
            "ge12km_count": int(np.count_nonzero(pd.to_numeric(stage4_df.get("alt_m", pd.Series(dtype=float)), errors="coerce") >= 12000.0)),
            "ge12km_fraction": float(np.count_nonzero(pd.to_numeric(stage4_df.get("alt_m", pd.Series(dtype=float)), errors="coerce") >= 12000.0) / max(1, stage4_total)),
            "distribution_rows": stage4_rows,
        },
        "comparison_rows": compare_rows,
    }

    (out_dir / "stage_altitude_distribution_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(out_dir / "stage1_full_raw_distribution.csv", stage1_raw_rows)
    _write_csv(out_dir / "stage1_full_heuristic_distribution.csv", stage1_heuristic_rows)
    _write_csv(out_dir / "stage2_in_domain_distribution.csv", stage2_rows)
    _write_csv(out_dir / "stage4_holdout_distribution.csv", stage4_rows)
    _write_csv(out_dir / "stage_altitude_distribution_comparison.csv", compare_rows)
    _write_markdown(out_dir / "stage_altitude_distribution_report.md", report)


if __name__ == "__main__":
    main()
