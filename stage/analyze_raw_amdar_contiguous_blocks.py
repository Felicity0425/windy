from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


RAW_AMDAR_XLSX = Path("/data/LFT-W02_data/pengxu/20260224/amdar.xlsx")


def _safe_str(value: Any, fallback: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze whether raw AMDAR same-timestamp groups split into multiple contiguous blocks.")
    parser.add_argument("--xlsx", default=str(RAW_AMDAR_XLSX))
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_excel(xlsx_path)
    df["source_row_index"] = range(len(df))
    for col in ("机尾号", "航班号", "飞行阶段"):
        if col in df.columns:
            df[col] = df[col].map(lambda x: _safe_str(x, "missing"))

    duplicate = df.groupby(["航班号", "时间（北京时）"], sort=False).size().reset_index(name="rows")
    duplicate = duplicate[duplicate["rows"] > 1]

    records: list[dict[str, Any]] = []
    multi_block_examples: list[dict[str, Any]] = []

    for flight_number, batch_time, rows in duplicate.itertuples(index=False):
        one = df[(df["航班号"] == flight_number) & (df["时间（北京时）"] == batch_time)].copy()
        one = one.sort_values("source_row_index")
        one["prev_row"] = one["source_row_index"].shift(1)
        one["is_block_start"] = one["prev_row"].isna() | ((one["source_row_index"] - one["prev_row"]) != 1)
        one["contiguous_block_index"] = one["is_block_start"].cumsum().astype(int)
        block_count = int(one["contiguous_block_index"].nunique())
        first_tail = _safe_str(one["机尾号"].iloc[0], "missing")
        first_phase = _safe_str(one["飞行阶段"].iloc[0], "missing")
        tail_nunique = int(one["机尾号"].nunique(dropna=False))
        phase_nunique = int(one["飞行阶段"].nunique(dropna=False))
        record = {
            "flight_number": flight_number,
            "batch_time_beijing": batch_time,
            "rows": int(rows),
            "contiguous_block_count": block_count,
            "tail_nunique": tail_nunique,
            "phase_nunique": phase_nunique,
            "tail_first": first_tail,
            "phase_first": first_phase,
            "raw_row_min": int(one["source_row_index"].min() + 2),
            "raw_row_max": int(one["source_row_index"].max() + 2),
        }
        records.append(record)
        if block_count > 1 and len(multi_block_examples) < 20:
            block_sizes = (
                one.groupby("contiguous_block_index", sort=False)
                .size()
                .reset_index(name="rows")
                .to_dict(orient="records")
            )
            multi_block_examples.append(
                {
                    **record,
                    "block_sizes": block_sizes,
                }
            )

    block_df = pd.DataFrame.from_records(records)
    multi_block = block_df[block_df["contiguous_block_count"] > 1].copy()

    summary = {
        "raw_amdar_xlsx": str(xlsx_path),
        "duplicate_groups": int(len(block_df)),
        "multi_contiguous_block_groups": int(len(multi_block)),
        "multi_contiguous_block_ratio": float(len(multi_block) / max(1, len(block_df))),
        "same_timestamp_group_block_count_quantiles": {
            "0.5": float(block_df["contiguous_block_count"].quantile(0.5)) if len(block_df) else None,
            "0.9": float(block_df["contiguous_block_count"].quantile(0.9)) if len(block_df) else None,
            "0.99": float(block_df["contiguous_block_count"].quantile(0.99)) if len(block_df) else None,
        },
        "multi_block_examples": multi_block_examples,
    }

    (out_dir / "raw_amdar_contiguous_block_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    block_df.to_csv(out_dir / "raw_amdar_contiguous_block_details.csv", index=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
