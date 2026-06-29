from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import polars as pl


EARTH_RADIUS_KM = 6371.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze AMDAR batch sequence continuity and altitude trends.")
    parser.add_argument("--stage1-dir", default="/data/LFT-W02_data/pengxu/stage1_output")
    parser.add_argument("--out-dir", default="/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan2_implementation_20260628")
    return parser.parse_args()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    series = pl.Series(values, dtype=pl.Float64)
    return float(series.quantile(q))


def _value_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        counts[value] = counts.get(value, 0) + 1
    return counts


def main() -> None:
    args = _parse_args()
    stage1_dir = Path(args.stage1_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    wind = (
        pl.read_parquet(stage1_dir / "clean_wind.parquet")
        .filter(pl.col("source") == "amdar")
        .sort(["amdar_batch_id", "source_row_index"])
    )
    diagnostics: list[dict[str, Any]] = []
    group_size_50_rows: list[dict[str, Any]] = []

    grouped_batches = wind.partition_by("amdar_batch_id", maintain_order=True, as_dict=True)

    for batch_id, one in grouped_batches.items():
        if batch_id is None:
            continue
        one = one.select(
            [
                "source_row_index",
                "lat_clean",
                "lon_clean",
                "alt_meters",
                "飞行阶段",
                "机尾号",
                "航班号",
                "amdar_batch_row_count",
                "amdar_batch_is_contiguous",
                "amdar_batch_hspan_deg",
                "amdar_batch_vertical_span_m",
            ]
        )
        rows = one.to_dicts()
        phase_value = rows[0].get("飞行阶段") if rows else None
        if len(rows) < 2:
            diagnostics.append(
                {
                    "amdar_batch_id": batch_id,
                    "phase": phase_value,
                    "rows": int(len(rows)),
                    "altitude_increase_ratio": None,
                    "altitude_decrease_ratio": None,
                    "altitude_large_reverse_count": 0,
                    "median_adjacent_distance_km": None,
                    "p90_adjacent_distance_km": None,
                    "max_adjacent_distance_km": None,
                    "path_length_km": 0.0,
                    "endpoint_distance_km": 0.0,
                    "path_efficiency": None,
                }
            )
            continue

        alt_diffs: list[float] = []
        distances: list[float] = []
        for prev, curr in zip(rows[:-1], rows[1:]):
            alt_prev = prev.get("alt_meters")
            alt_curr = curr.get("alt_meters")
            if alt_prev is not None and alt_curr is not None:
                alt_diffs.append(float(alt_curr) - float(alt_prev))
            lat1 = prev.get("lat_clean")
            lon1 = prev.get("lon_clean")
            lat2 = curr.get("lat_clean")
            lon2 = curr.get("lon_clean")
            if None not in (lat1, lon1, lat2, lon2):
                distances.append(_haversine_km(float(lat1), float(lon1), float(lat2), float(lon2)))

        altitude_increase_ratio = None
        altitude_decrease_ratio = None
        altitude_large_reverse_count = 0
        if alt_diffs:
            altitude_increase_ratio = float(sum(1 for x in alt_diffs if x > 0.0) / len(alt_diffs))
            altitude_decrease_ratio = float(sum(1 for x in alt_diffs if x < 0.0) / len(alt_diffs))
            phase = str(phase_value or "")
            if phase == "ASC":
                altitude_large_reverse_count = int(sum(1 for x in alt_diffs if x < -150.0))
            elif phase == "DES":
                altitude_large_reverse_count = int(sum(1 for x in alt_diffs if x > 150.0))

        endpoint_distance_km = 0.0
        if None not in (rows[0].get("lat_clean"), rows[0].get("lon_clean"), rows[-1].get("lat_clean"), rows[-1].get("lon_clean")):
            endpoint_distance_km = _haversine_km(
                float(rows[0]["lat_clean"]),
                float(rows[0]["lon_clean"]),
                float(rows[-1]["lat_clean"]),
                float(rows[-1]["lon_clean"]),
            )
        path_length_km = float(sum(distances))
        path_efficiency = None if path_length_km <= 0 else float(endpoint_distance_km / path_length_km)

        record = {
            "amdar_batch_id": batch_id,
            "phase": phase_value,
            "rows": int(len(rows)),
            "amdar_batch_is_contiguous": rows[0].get("amdar_batch_is_contiguous") if rows else None,
            "amdar_batch_hspan_deg": rows[0].get("amdar_batch_hspan_deg") if rows else None,
            "amdar_batch_vertical_span_m": rows[0].get("amdar_batch_vertical_span_m") if rows else None,
            "altitude_increase_ratio": altitude_increase_ratio,
            "altitude_decrease_ratio": altitude_decrease_ratio,
            "altitude_large_reverse_count": altitude_large_reverse_count,
            "median_adjacent_distance_km": _quantile(distances, 0.5),
            "p90_adjacent_distance_km": _quantile(distances, 0.9),
            "max_adjacent_distance_km": max(distances) if distances else None,
            "path_length_km": path_length_km,
            "endpoint_distance_km": endpoint_distance_km,
            "path_efficiency": path_efficiency,
        }
        diagnostics.append(record)
        if int(len(rows)) == 50:
            group_size_50_rows.append(
                {
                    **record,
                    "tail_number": rows[0].get("机尾号"),
                    "flight_number": rows[0].get("航班号"),
                }
            )

    diag_df = pl.from_dicts(diagnostics) if diagnostics else pl.DataFrame()
    if len(diag_df) > 0:
        diag_df.write_parquet(out_dir / "amdar_sequence_diagnostics.parquet")

    size50_df = pl.from_dicts(group_size_50_rows) if group_size_50_rows else pl.DataFrame()
    if len(size50_df) > 0:
        size50_df.write_parquet(out_dir / "amdar_group_size_50_diagnostics.parquet")

    summary = {
        "stage1_dir": str(stage1_dir),
        "out_dir": str(out_dir),
        "batch_count": int(len(diagnostics)),
        "group_size_50_count": int(len(group_size_50_rows)),
        "group_size_50_phase_counts": _value_counts(group_size_50_rows, "phase"),
        "group_size_50_tail_top10": dict(sorted(_value_counts(group_size_50_rows, "tail_number").items(), key=lambda x: x[1], reverse=True)[:10]),
        "phase_altitude_increase_ratio_mean": {},
        "phase_altitude_decrease_ratio_mean": {},
        "phase_path_efficiency_mean": {},
    }

    for phase in ("ASC", "DES", "LVR", "CRZ"):
        phase_rows = [row for row in diagnostics if str(row.get("phase")) == phase]
        inc_vals = [float(row["altitude_increase_ratio"]) for row in phase_rows if row.get("altitude_increase_ratio") is not None]
        dec_vals = [float(row["altitude_decrease_ratio"]) for row in phase_rows if row.get("altitude_decrease_ratio") is not None]
        eff_vals = [float(row["path_efficiency"]) for row in phase_rows if row.get("path_efficiency") is not None]
        if inc_vals:
            summary["phase_altitude_increase_ratio_mean"][phase] = float(sum(inc_vals) / len(inc_vals))
        if dec_vals:
            summary["phase_altitude_decrease_ratio_mean"][phase] = float(sum(dec_vals) / len(dec_vals))
        if eff_vals:
            summary["phase_path_efficiency_mean"][phase] = float(sum(eff_vals) / len(eff_vals))

    (out_dir / "amdar_sequence_diagnostics_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
