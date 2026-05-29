"""Quality checks for migrated location parquet shards.

This script validates the `location_location_parquet` directory produced from
`location.xlsx` on another machine and helps catch common migration/ETL issues:
- missing shard files
- unexpected row counts
- missing or mismatched columns
- invalid timestamps
- invalid latitude/longitude/altitude ranges
- suspiciously large empty-looking shards

It also understands the coordinate encoding used by the pipeline's Stage-1
logic, including strings like `N28203089` / `E109399986`.

Usage:
    python check_location_parquet_quality.py
    python check_location_parquet_quality.py --dir /path/to/location_location_parquet
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PARQUET_DIR = os.path.join(BASE_DIR, "20260224", "location_location_parquet")
DEFAULT_MANIFEST = os.path.join(DEFAULT_PARQUET_DIR, "_manifest.json")

EXPECTED_COLUMNS = [
    "接收时间（UTC）",
    "机尾号",
    "航班号",
    "纬度",
    "经度",
    "高度",
    "航向角",
    "地速",
]

LAT_RANGE = (12.2, 54.2)
LON_RANGE = (73.0, 135.0)
ALT_RANGE = (0, 15000)
SUSPICIOUS_ROW_THRESHOLD = 500000


@dataclass
class ShardReport:
    shard: str
    exists: bool
    rows: Optional[int] = None
    cols: Optional[int] = None
    missing_columns: Optional[List[str]] = None
    extra_columns: Optional[List[str]] = None
    empty_like: Optional[bool] = None
    timestamp_parse_rate: Optional[float] = None
    lat_valid_rate: Optional[float] = None
    lon_valid_rate: Optional[float] = None
    alt_valid_rate: Optional[float] = None
    status: str = "unknown"
    note: Optional[str] = None


def _load_manifest(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _try_import_polars():
    try:
        import polars as pl
        return pl
    except Exception:
        return None


def _parse_coord(v: Any, axis: Optional[str] = None) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        num = float(v)
        if abs(num) >= 1_000_000:
            num /= 1_000_000.0
        elif abs(num) >= 10000:
            if axis == "lat" and abs(num) <= 900000:
                num /= 10000.0
            elif axis == "lon" and abs(num) <= 18000000:
                num /= 10000.0
        return num
    s = str(v).strip()
    if not s:
        return None

    s = s.replace("°", "").replace(" ", "")
    if s[0] in ("N", "S", "E", "W"):
        hemi = s[0]
        sign = -1.0 if s[0] in ("S", "W") else 1.0
        try:
            num = float(s[1:])
        except Exception:
            return None
        # Aviation compact encodings in this project are micro-degrees:
        # N28203089 -> 28.203089, E109390986 -> 109.390986.
        if abs(num) >= 1_000_000:
            num /= 1_000_000.0
        elif abs(num) >= 10000:
            if hemi in ("N", "S") and abs(num) <= 900000:
                num /= 10000.0
            elif hemi in ("E", "W") and abs(num) <= 18000000:
                num /= 10000.0
            else:
                num /= 1_000_000.0
        return sign * num

    try:
        num = float(s)
    except Exception:
        return None

    if abs(num) >= 1_000_000:
        num /= 1_000_000.0
    elif abs(num) >= 10000:
        if axis == "lat" and abs(num) <= 900000:
            num /= 10000.0
        elif axis == "lon" and abs(num) <= 18000000:
            num /= 10000.0
        elif axis is None:
            num /= 10000.0
    return num


def _parse_numeric_series(series, axis: Optional[str] = None):
    out = []
    for x in series:
        if x is None:
            continue
        try:
            out.append(float(x))
        except Exception:
            parsed = _parse_coord(x, axis=axis)
            if parsed is not None:
                out.append(parsed)
    return out


def _first_existing_col(columns, candidates: List[str]) -> Optional[str]:
    for col in candidates:
        if col in columns:
            return col
    return None


def _valid_rate_by_clean_or_raw(df, clean_cols: List[str], raw_cols: List[str], axis: str):
    clean_col = _first_existing_col(df.columns, clean_cols)
    raw_col = _first_existing_col(df.columns, raw_cols)
    if clean_col is not None:
        vals = _parse_numeric_series(_series_to_list(df, clean_col), axis=axis)
    elif raw_col is not None:
        vals = _parse_numeric_series(_series_to_list(df, raw_col), axis=axis)
    else:
        return 0.0
    if axis == "lat":
        return _valid_rate(vals, *LAT_RANGE)
    return _valid_rate(vals, *LON_RANGE)


def _series_to_list(df, col: str):
    try:
        return df.get_column(col).to_list()
    except Exception:
        try:
            return df[col].to_list()
        except Exception:
            return []


def _valid_rate(values, lo, hi):
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0
    ok = sum(1 for v in vals if lo <= v <= hi)
    return ok / len(vals)


def _parse_time_rate(values):
    from datetime import datetime

    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0
    ok = 0
    for v in vals:
        s = str(v).strip()
        if not s:
            continue
        parsed = False
        for fmt in (
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M",
        ):
            try:
                datetime.strptime(s, fmt)
                parsed = True
                break
            except Exception:
                pass
        if parsed:
            ok += 1
    return ok / len(vals)


def _extract_columns(df) -> List[str]:
    try:
        return list(df.columns)
    except Exception:
        return []


def _read_shard(polars_mod, shard_path: str):
    if polars_mod is None:
        raise RuntimeError("polars is not installed")
    return polars_mod.read_parquet(shard_path)


def inspect_shard(polars_mod, shard_path: str) -> ShardReport:
    report = ShardReport(shard=os.path.basename(shard_path), exists=os.path.exists(shard_path))
    if not report.exists:
        report.status = "missing"
        report.note = "file not found"
        return report

    try:
        df = _read_shard(polars_mod, shard_path)
    except Exception as e:
        report.status = "read_error"
        report.note = str(e)
        return report

    cols = _extract_columns(df)
    report.cols = len(cols)
    report.rows = int(df.height) if hasattr(df, "height") else None

    missing = [c for c in EXPECTED_COLUMNS if c not in cols]
    extra = [c for c in cols if c not in EXPECTED_COLUMNS]
    report.missing_columns = missing
    report.extra_columns = extra[:20]

    if report.rows is not None and report.rows >= SUSPICIOUS_ROW_THRESHOLD:
        report.empty_like = True
        report.note = f"row count is very large: {report.rows}"
    else:
        report.empty_like = False

    try:
        if "接收时间（UTC）" in cols:
            time_vals = _series_to_list(df, "接收时间（UTC）")
            report.timestamp_parse_rate = _parse_time_rate(time_vals)
        elif "time_utc" in cols:
            time_vals = _series_to_list(df, "time_utc")
            report.timestamp_parse_rate = _parse_time_rate(time_vals)

        report.lat_valid_rate = _valid_rate_by_clean_or_raw(
            df,
            clean_cols=["lat_clean", "纬度_clean"],
            raw_cols=["纬度_raw", "纬度"],
            axis="lat",
        )
        report.lon_valid_rate = _valid_rate_by_clean_or_raw(
            df,
            clean_cols=["lon_clean", "经度_clean"],
            raw_cols=["经度_raw", "经度"],
            axis="lon",
        )

        if "高度" in cols:
            alt_vals = _parse_numeric_series(_series_to_list(df, "高度"))
        elif "alt_meters" in cols:
            alt_vals = _parse_numeric_series(_series_to_list(df, "alt_meters"))
        else:
            alt_vals = []
        report.alt_valid_rate = _valid_rate(alt_vals, *ALT_RANGE)
    except Exception as e:
        report.note = (report.note + " | " if report.note else "") + f"quality metric error: {e}"

    if missing:
        report.status = "schema_mismatch"
    elif report.timestamp_parse_rate is not None and report.timestamp_parse_rate < 0.5:
        report.status = "bad_time"
    elif (report.lat_valid_rate is not None and report.lat_valid_rate < 0.5) or (report.lon_valid_rate is not None and report.lon_valid_rate < 0.5):
        report.status = "bad_geo"
    else:
        report.status = "ok"
    return report


def main():
    parser = argparse.ArgumentParser(description="Quality checks for migrated location parquet shards.")
    parser.add_argument("--dir", default=DEFAULT_PARQUET_DIR, help="Directory containing location parquet shards.")
    args = parser.parse_args()

    parquet_dir = os.path.abspath(args.dir)
    manifest_path = os.path.join(parquet_dir, "_manifest.json")
    manifest = _load_manifest(manifest_path)
    if manifest is None:
        print(json.dumps({"ok": False, "error": f"missing manifest: {manifest_path}"}, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    shards = manifest.get("shards", [])
    expected = int(manifest.get("sheet_count", len(shards)))
    shard_paths = [s.get("parquet") or s.get("out_parquet") for s in shards if (s.get("parquet") or s.get("out_parquet"))]

    polars_mod = _try_import_polars()
    results: List[Dict[str, Any]] = []
    summary = {
        "ok": True,
        "manifest_source": manifest.get("source"),
        "sheet_count": expected,
        "found_shards": len(shard_paths),
        "polars_available": polars_mod is not None,
        "bad_shards": 0,
        "missing_shards": 0,
    }

    if polars_mod is None:
        summary["ok"] = False
        summary["error"] = "polars is not installed in the current environment"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    local_shards = []
    for s in shards:
        pq = s.get("parquet") or s.get("out_parquet")
        if not pq:
            continue
        normalized = pq.replace("\\", "/")
        shard_name = os.path.basename(normalized)
        local_shards.append(os.path.join(parquet_dir, shard_name))

    missing_files = [p for p in local_shards if not os.path.exists(p)]
    summary["missing_shards"] = len(missing_files)
    if missing_files:
        summary["ok"] = False

    for shard_path in local_shards:
        rep = inspect_shard(polars_mod, shard_path)
        results.append(asdict(rep))
        if rep.status != "ok":
            summary["bad_shards"] += 1
            summary["ok"] = False

    payload = {
        "summary": summary,
        "reports": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not summary["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
