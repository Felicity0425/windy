"""Robust Excel -> parquet converter for `location` / `amdar` / `turb`.

This version is intentionally strict about downstream schema stability:
- `location`: first sheet has header row; the other 18 sheets are headerless data
- `amdar` / `turb`: preserve all original columns and add normalized helper fields
- always keep raw columns, plus cleaned helpers used by Stage 1~4
- normalize time, coordinates, altitude, wind, heading, ground speed
- write parquet shards + `_manifest.json` with absolute paths

Notes
-----
- This script does *best-effort* parsing. If a source cell is truly empty, the
  cleaned helper column will remain null; however, the goal is to avoid
  accidental nulls caused by parsing/format mismatch.
- Location coordinates use aviation-style compact encodings such as
  `N28203089` / `E109390986`.
- `amdar` and `turb` time values are expected to be Beijing time and are
  converted to UTC.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class SheetResult:
    source_file: str
    workbook_type: str
    sheet_name: str
    rows: int
    cols: int
    out_parquet: str
    status: str
    elapsed_seconds: float
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------------

def _try_imports():
    import pandas as pd  # type: ignore
    import polars as pl  # type: ignore
    return pd, pl


def _norm_col_name(name: Any) -> str:
    return str(name).replace("\u3000", " ").strip()


def _safe_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    try:
        import pandas as pd  # type: ignore
        if pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).strip()
    return s if s else None


def _guess_workbook_type(path: Path) -> str:
    stem = path.stem.lower()
    if "location" in stem:
        return "location"
    if "amdar" in stem:
        return "amdar"
    if "turb" in stem:
        return "turb"
    return "generic"


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

def _parse_excel_time_to_dt(v: Any):
    """Parse one cell to pandas.Timestamp (naive datetime-like).

    统一时间解析逻辑：
    - 兼容 Excel 原生日期时间
    - 兼容字符串时间，比如 `2026/1/22 18:00:25`
    - 兼容 `2026-01-22 18:00:25`
    - 兼容被截断的年份显示，如 `026/1/22 18:00:25`
    - 兼容 Excel 序列日期数字
    """
    import pandas as pd  # type: ignore

    if v is None or (hasattr(pd, "isna") and pd.isna(v)):
        return pd.NaT

    # 1) Excel 数字日期（序列号）
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        try:
            return pd.to_datetime(v, unit="D", origin="1899-12-30", errors="coerce")
        except Exception:
            pass

    # 2) 转字符串后逐值解析
    s = _safe_str(v)
    if not s:
        return pd.NaT

    # 修复被 Excel 截断的年份，例如：026/1/22 -> 2026/1/22
    if re.match(r"^\d{3}/", s):
        s = "2" + s
    if re.match(r"^\d{2}/", s):
        y = s[:2]
        rest = s[2:]
        s = f"20{y}{rest}"

    # 3) 优先使用 pandas 通用解析
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        # 4) 再使用显式格式兜底
        fmts = [
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d",
            "%Y-%m-%d",
            "%y/%m/%d %H:%M:%S",
            "%y/%m/%d %H:%M",
            "%y/%m/%d",
        ]
        for fmt in fmts:
            try:
                dt = datetime.strptime(s, fmt)
                return pd.Timestamp(dt)
            except Exception:
                continue
    return dt


def _dt_to_str_z(dt) -> Optional[str]:
    import pandas as pd  # type: ignore
    if dt is None or pd.isna(dt):
        return None
    if not isinstance(dt, pd.Timestamp):
        dt = pd.Timestamp(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _series_to_beijing_utc(series):
    """Return (time_beijing, time_utc) string series for stable parquet storage.

    说明：
    - `time_beijing` 用本地北京时间字符串表示，不加 `Z`
    - `time_utc` 才使用 `Z` 表示 UTC
    - 先逐值解析，再统一格式化，避免 pandas 推断不稳定
    """
    import pandas as pd  # type: ignore

    parsed = series.map(_parse_excel_time_to_dt)
    bj = pd.to_datetime(parsed, errors="coerce")
    utc = bj - pd.Timedelta(hours=8)
    return bj.dt.strftime("%Y-%m-%d %H:%M:%S"), utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_first_existing_col(columns, candidates):
    colset = set(columns)
    for c in candidates:
        if c in colset:
            return c
    return None


# ---------------------------------------------------------------------------
# Coordinate parsing
# ---------------------------------------------------------------------------

def _parse_coord(v: Any, axis: Optional[str] = None) -> Optional[float]:
    """Parse coordinate values conservatively.

    Supported encodings:
    - numeric floats / ints
    - strings like `N28203089` / `E109399986`
    - strings already in decimal degrees
    - combined strings like `N28203089E109399986`
    """
    if v is None:
        return None
    try:
        import pandas as pd  # type: ignore
        if pd.isna(v):
            return None
    except Exception:
        pass

    if isinstance(v, (int, float)) and not isinstance(v, bool):
        num = float(v)
        # Heuristic: integer-style coordinate encodings are usually 1e6 scaled.
        if abs(num) >= 1_000_000:
            num /= 1_000_000.0
        elif abs(num) >= 10000:
            # fallback for encoded degrees
            if axis == "lat" and abs(num) <= 900000:
                num /= 10000.0
            elif axis == "lon" and abs(num) <= 18000000:
                num /= 10000.0
        return num

    s = _safe_str(v)
    if not s:
        return None

    # Combined string like N28203089E109399986
    combo = re.match(r"^([NS])([\d\.]+)([EW])([\d\.]+)$", s.replace(" ", ""), re.IGNORECASE)
    if combo:
        hemi1, num1, hemi2, num2 = combo.groups()
        if axis == "lat":
            s = f"{hemi1.upper()}{num1}"
        elif axis == "lon":
            s = f"{hemi2.upper()}{num2}"
        else:
            s = f"{hemi1.upper()}{num1}"

    sign = 1.0
    if s[0] in ("N", "S", "E", "W"):
        if s[0] in ("S", "W"):
            sign = -1.0
        s = s[1:].strip()

    s = s.replace("°", "").replace(" ", "")
    try:
        num = float(s)
    except Exception:
        return None

    # Aviation encodings often use micro-degrees.
    if abs(num) >= 1_000_000:
        num /= 1_000_000.0
    elif abs(num) >= 10000:
        if axis == "lat" and abs(num) <= 900000:
            num /= 10000.0
        elif axis == "lon" and abs(num) <= 18000000:
            num /= 10000.0
        elif axis is None:
            num /= 10000.0

    return sign * num


# ---------------------------------------------------------------------------
# Workbook normalization
# ---------------------------------------------------------------------------

def _normalize_location_df(df, pd):
    """Normalize one location sheet.

    说明：
    - 第 1 个 sheet 有表头；后续 sheet 通常是无表头原始数据。
    - 这里优先保留原始列，再补齐下游需要的标准化字段。
    - 目标是让 Stage 1/2 可以直接使用 `time_utc / lat_clean / lon_clean`
      等标准列，不再依赖旧 Excel 列名。
    """
    out = df.copy()
    out.columns = [_norm_col_name(c) for c in out.columns]

    # ----------------------------
    # 时间列
    # ----------------------------
    if "接收时间（UTC）" in out.columns:
        out["接收时间（UTC）_raw"] = out["接收时间（UTC）"]
        out["time_utc"] = out["接收时间（UTC）"].map(_parse_excel_time_to_dt)
    else:
        out["接收时间（UTC）_raw"] = pd.NA
        out["time_utc"] = pd.NaT

    # ----------------------------
    # 飞机标识列
    # ----------------------------
    if "机尾号" in out.columns:
        out["机尾号_raw"] = out["机尾号"]
    if "航班号" in out.columns:
        out["航班号_raw"] = out["航班号"]

    # ----------------------------
    # 经纬度与高度
    # ----------------------------
    if "纬度" in out.columns:
        out["纬度_raw"] = out["纬度"]
        out["lat_clean"] = out["纬度"].map(lambda x: _parse_coord(x, axis="lat"))
    else:
        out["纬度_raw"] = pd.NA
        out["lat_clean"] = pd.NA

    if "经度" in out.columns:
        out["经度_raw"] = out["经度"]
        out["lon_clean"] = out["经度"].map(lambda x: _parse_coord(x, axis="lon"))
    else:
        out["经度_raw"] = pd.NA
        out["lon_clean"] = pd.NA

    if "高度" in out.columns:
        out["高度_raw"] = out["高度"]
        out["alt_meters"] = pd.to_numeric(out["高度"], errors="coerce")
    else:
        out["高度_raw"] = pd.NA
        out["alt_meters"] = pd.NA

    # ----------------------------
    # 航向和地速
    # ----------------------------
    if "航向角" in out.columns:
        out["航向角_raw"] = out["航向角"]
        out["heading_deg"] = pd.to_numeric(out["航向角"], errors="coerce")
    else:
        out["航向角_raw"] = pd.NA
        out["heading_deg"] = pd.NA

    if "地速" in out.columns:
        out["地速_raw"] = out["地速"]
        out["ground_speed_ms"] = pd.to_numeric(out["地速"], errors="coerce") * (1000.0 / 3600.0)
    else:
        out["地速_raw"] = pd.NA
        out["ground_speed_ms"] = pd.NA

    # ----------------------------
    # flight_id：优先航班号，其次机尾号，最后造一个稳定 id
    # ----------------------------
    if "航班号" in out.columns:
        out["flight_id"] = out["航班号"].astype("string")
    elif "机尾号" in out.columns:
        out["flight_id"] = out["机尾号"].astype("string")
    else:
        out["flight_id"] = [f"flight_{i:08d}" for i in range(len(out))]

    # ----------------------------
    # 运动分量：供 Stage 1/2/3 下游使用
    # ----------------------------
    if "heading_deg" in out.columns and "ground_speed_ms" in out.columns:
        rad = pd.to_numeric(out["heading_deg"], errors="coerce") * (3.141592653589793 / 180.0)
        spd = pd.to_numeric(out["ground_speed_ms"], errors="coerce")
        out["u_motion"] = spd * rad.map(lambda x: float(__import__("math").sin(x)) if pd.notna(x) else pd.NA)
        out["v_motion"] = spd * rad.map(lambda x: float(__import__("math").cos(x)) if pd.notna(x) else pd.NA)
    else:
        out["u_motion"] = pd.NA
        out["v_motion"] = pd.NA

    return out


def _normalize_amdar_df(df, pd):
    """Normalize AMDAR workbook.

    说明：AMDAR 的时间列在原始 Excel 中叫 `时间（北京时）` 或类似名称。
    这里采用与 location 类似的逐值解析方式，再显式把北京时间转成 UTC。
    """
    out = df.copy()
    out.columns = [_norm_col_name(c) for c in out.columns]

    # ----------------------------
    # 时间列：优先解析北京时间，再得到 UTC
    # ----------------------------
    time_col = _find_first_existing_col(
        out.columns,
        ["时间（北京时）", "时间（北京时间）", "时间（北京时）", "time_beijing", "接收时间（UTC）"]
    )
    if time_col is not None:
        out[f"{time_col}_raw"] = out[time_col]
        if time_col == "接收时间（UTC）":
            utc = pd.to_datetime(out[time_col], errors="coerce")
            out["time_utc"] = utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            out["time_beijing"] = (utc + pd.Timedelta(hours=8)).dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            bj, utc = _series_to_beijing_utc(out[time_col])
            out["time_beijing"] = bj
            out["time_utc"] = utc
    else:
        out["time_beijing"] = pd.NA
        out["time_utc"] = pd.NA

    # ----------------------------
    # 经纬度与高度
    # ----------------------------
    if "纬度" in out.columns:
        out["纬度_raw"] = out["纬度"]
        out["lat_clean"] = out["纬度"].map(_parse_coord)
    else:
        out["纬度_raw"] = pd.NA
        out["lat_clean"] = pd.NA

    if "经度" in out.columns:
        out["经度_raw"] = out["经度"]
        out["lon_clean"] = out["经度"].map(_parse_coord)
    else:
        out["经度_raw"] = pd.NA
        out["lon_clean"] = pd.NA

    if "高度" in out.columns:
        out["高度_raw"] = out["高度"]
        out["alt_meters"] = pd.to_numeric(out["高度"], errors="coerce")
    else:
        out["高度_raw"] = pd.NA
        out["alt_meters"] = pd.NA

    # ----------------------------
    # 风向、风速与风矢量
    # ----------------------------
    for col in ("飞行阶段", "静温", "风向", "风速", "风向_raw", "风速_raw"):
        if col in out.columns:
            out[f"{col}_raw"] = out[col]

    if "风向" in out.columns:
        out["wind_dir"] = pd.to_numeric(out["风向"], errors="coerce")
    elif "风向_raw" in out.columns:
        out["wind_dir"] = pd.to_numeric(out["风向_raw"], errors="coerce")
    else:
        out["wind_dir"] = pd.NA

    if "风速" in out.columns:
        out["wind_speed"] = pd.to_numeric(out["风速"], errors="coerce")
    elif "风速_raw" in out.columns:
        out["wind_speed"] = pd.to_numeric(out["风速_raw"], errors="coerce")
    else:
        out["wind_speed"] = pd.NA

    rad = pd.to_numeric(out["wind_dir"], errors="coerce") * (3.141592653589793 / 180.0)
    spd = pd.to_numeric(out["wind_speed"], errors="coerce")
    out["u_wind"] = spd * rad.map(lambda x: float(__import__("math").sin(x)) if pd.notna(x) else pd.NA) * -1
    out["v_wind"] = spd * rad.map(lambda x: float(__import__("math").cos(x)) if pd.notna(x) else pd.NA) * -1

    # ----------------------------
    # flight_id
    # ----------------------------
    if "航班号" in out.columns:
        out["flight_id"] = out["航班号"].astype("string")
    elif "机尾号" in out.columns:
        out["flight_id"] = out["机尾号"].astype("string")
    else:
        out["flight_id"] = pd.NA

    return out


def _normalize_turb_df(df, pd):
    """Normalize TURB workbook.

    说明：TURB 和 AMDAR 一样，时间通常来自北京时间字段；导出时同时
    保留 `time_beijing` 和 `time_utc`。如果原始表没有北京时间字段，而
    只有 UTC 字段，也会尽量兼容。
    """
    out = df.copy()
    out.columns = [_norm_col_name(c) for c in out.columns]

    # ----------------------------
    # 时间列
    # ----------------------------
    time_col = _find_first_existing_col(out.columns, ["时间（北京时）", "时间（北京时间）", "time_beijing", "接收时间（UTC）"])
    if time_col is not None:
        out[f"{time_col}_raw"] = out[time_col]
        if time_col == "接收时间（UTC）":
            utc = pd.to_datetime(out[time_col], errors="coerce")
            out["time_utc"] = utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            out["time_beijing"] = (utc + pd.Timedelta(hours=8)).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            bj, utc = _series_to_beijing_utc(out[time_col])
            out["time_beijing"] = bj
            out["time_utc"] = utc
    else:
        out["time_beijing"] = pd.NA
        out["time_utc"] = pd.NA

    # ----------------------------
    # 经纬度与高度
    # ----------------------------
    if "纬度" in out.columns:
        out["纬度_raw"] = out["纬度"]
        out["lat_clean"] = out["纬度"].map(_parse_coord)
    else:
        out["纬度_raw"] = pd.NA
        out["lat_clean"] = pd.NA

    if "经度" in out.columns:
        out["经度_raw"] = out["经度"]
        out["lon_clean"] = out["经度"].map(_parse_coord)
    else:
        out["经度_raw"] = pd.NA
        out["lon_clean"] = pd.NA

    if "高度" in out.columns:
        out["高度_raw"] = out["高度"]
        out["alt_meters"] = pd.to_numeric(out["高度"], errors="coerce")
    else:
        out["高度_raw"] = pd.NA
        out["alt_meters"] = pd.NA

    # ----------------------------
    # 风、姿态、扰动字段
    # ----------------------------
    for col in ("静温", "风向", "风速", "俯仰", "旋转", "航向", "颠簸强度"):
        if col in out.columns:
            out[f"{col}_raw"] = out[col]

    if "风向" in out.columns:
        out["wind_dir"] = pd.to_numeric(out["风向"], errors="coerce")
    else:
        out["wind_dir"] = pd.NA

    if "风速" in out.columns:
        out["wind_speed"] = pd.to_numeric(out["风速"], errors="coerce")
    else:
        out["wind_speed"] = pd.NA

    rad = pd.to_numeric(out["wind_dir"], errors="coerce") * (3.141592653589793 / 180.0)
    spd = pd.to_numeric(out["wind_speed"], errors="coerce")
    out["u_wind"] = spd * rad.map(lambda x: float(__import__("math").sin(x)) if pd.notna(x) else pd.NA) * -1
    out["v_wind"] = spd * rad.map(lambda x: float(__import__("math").cos(x)) if pd.notna(x) else pd.NA) * -1

    # ----------------------------
    # flight_id
    # ----------------------------
    if "航班号" in out.columns:
        out["flight_id"] = out["航班号"].astype("string")
    elif "机尾号" in out.columns:
        out["flight_id"] = out["机尾号"].astype("string")
    else:
        out["flight_id"] = pd.NA

    return out


def _normalize_generic_df(df, pd):
    out = df.copy()
    out.columns = [_norm_col_name(c) for c in out.columns]
    if "纬度" in out.columns:
        out["纬度_clean"] = out["纬度"].map(_parse_coord)
    if "经度" in out.columns:
        out["经度_clean"] = out["经度"].map(_parse_coord)
    if "接收时间（UTC）" in out.columns:
        out["time_utc"] = out["接收时间（UTC）"].map(_parse_excel_time_to_dt)
    if "高度" in out.columns:
        out["alt_meters"] = pd.to_numeric(out["高度"], errors="coerce")
    return out


# ---------------------------------------------------------------------------
# I/O + manifest
# ---------------------------------------------------------------------------

def _write_manifest(out_dir: Path, source_file: Path, workbook_type: str, results: List[SheetResult]) -> None:
    manifest = {
        "source": str(source_file),
        "workbook_type": workbook_type,
        "sheet_count": len(results),
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "shards": [asdict(r) for r in results],
    }
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def convert_excel_file(pd, pl, excel_path: Path, out_root: Path, max_sheets: Optional[int] = None, sheet_offset: int = 0) -> List[SheetResult]:
    if not excel_path.exists():
        raise FileNotFoundError(excel_path)

    workbook_type = _guess_workbook_type(excel_path)
    if workbook_type == "location":
        out_dir = out_root / "location_location_parquet"
    elif workbook_type == "amdar":
        out_dir = out_root / "amdar_parquet"
    elif workbook_type == "turb":
        out_dir = out_root / "turb_parquet"
    else:
        out_dir = out_root / f"{excel_path.stem}_parquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    xls = pd.ExcelFile(excel_path)
    sheet_names = list(xls.sheet_names)
    if max_sheets is not None:
        sheet_names = sheet_names[sheet_offset: sheet_offset + max_sheets]
    elif sheet_offset:
        sheet_names = sheet_names[sheet_offset:]

    results: List[SheetResult] = []

    for rel_idx, sheet_name in enumerate(sheet_names):
        i = sheet_offset + rel_idx
        sheet_start = time.time()
        print(f"[convert] {excel_path.name} | sheet {i+1}/{len(xls.sheet_names)} | {sheet_name} | start")

        try:
            # Location: sheet-1 has header, sheets 2..19 are headerless.
            if workbook_type == "location":
                if i == 0:
                    df = pd.read_excel(excel_path, sheet_name=sheet_name, dtype=object, header=0)
                else:
                    df = pd.read_excel(excel_path, sheet_name=sheet_name, dtype=object, header=None)
                    # There are 8 canonical columns in the location workbook.
                    cols = ["接收时间（UTC）", "机尾号", "航班号", "纬度", "经度", "高度", "航向角", "地速"]
                    df.columns = cols[: len(df.columns)]
            else:
                df = pd.read_excel(excel_path, sheet_name=sheet_name, dtype=object, header=0)
        except Exception as e:
            elapsed = time.time() - sheet_start
            results.append(
                SheetResult(
                    source_file=str(excel_path),
                    workbook_type=workbook_type,
                    sheet_name=sheet_name,
                    rows=0,
                    cols=0,
                    out_parquet="",
                    status="read_error",
                    elapsed_seconds=elapsed,
                    note=str(e),
                )
            )
            print(f"[convert] {excel_path.name} | sheet {i+1}/{len(xls.sheet_names)} | {sheet_name} | read_error | {elapsed:.2f}s")
            continue

        # Normalize by workbook family.
        if workbook_type == "location":
            df = _normalize_location_df(df, pd)
        elif workbook_type == "amdar":
            df = _normalize_amdar_df(df, pd)
        elif workbook_type == "turb":
            df = _normalize_turb_df(df, pd)
        else:
            df = _normalize_generic_df(df, pd)

        # Best-effort NA handling for stable parquet output.
        df = df.where(pd.notna(df), None)

        parquet_path = out_dir / f"sheet_{i:02d}.parquet"
        pl_df = pl.from_dicts(df.to_dict(orient="records"))
        pl_df.write_parquet(str(parquet_path))

        elapsed = time.time() - sheet_start
        results.append(
            SheetResult(
                source_file=str(excel_path),
                workbook_type=workbook_type,
                sheet_name=sheet_name,
                rows=int(len(df)),
                cols=int(len(df.columns)),
                out_parquet=str(parquet_path),
                status="ok",
                elapsed_seconds=elapsed,
                note=None,
            )
        )
        print(
            f"[convert] {excel_path.name} | sheet {i+1}/{len(xls.sheet_names)} | {sheet_name} | "
            f"rows={len(df)} cols={len(df.columns)} | done | {elapsed:.2f}s"
        )

    _write_manifest(out_dir, excel_path, workbook_type, results)
    return results


def main():
    parser = argparse.ArgumentParser(description="Robust Excel -> parquet converter.")
    parser.add_argument("--excel", action="append", required=True, help="Excel file path. Can be repeated.")
    parser.add_argument("--out-root", required=True, help="Output root directory.")
    parser.add_argument("--max-sheets", type=int, default=None, help="Maximum number of sheets to convert per workbook.")
    parser.add_argument("--sheet-offset", type=int, default=0, help="Starting sheet index (0-based).")
    args = parser.parse_args()

    pd, pl = _try_imports()
    out_root = Path(args.out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    all_results: List[SheetResult] = []
    for excel in args.excel:
        excel_path = Path(excel).resolve()
        results = convert_excel_file(pd, pl, excel_path, out_root, max_sheets=args.max_sheets, sheet_offset=args.sheet_offset)
        all_results.extend(results)

    payload = {
        "ok": True,
        "converted_sheets": len(all_results),
        "output_root": str(out_root),
        "total_elapsed_seconds": round(sum(r.elapsed_seconds for r in all_results), 3),
        "results": [asdict(r) for r in all_results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
