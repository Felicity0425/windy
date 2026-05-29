"""Normalize all path separators inside a manifest-style JSON file.

This helper is intentionally conservative for a single target JSON file. It
recursively traverses the JSON structure and replaces every backslash with a
forward slash in string values and string keys.

Example:
    python normalize_manifest_paths.py \
      --path /data/LFT-W02_data/pengxu/20260224/location_location_parquet/_manifest.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Tuple


def _normalize(value: Any) -> Tuple[Any, int]:
    if isinstance(value, str):
        new_value = value.replace("\\", "/")
        return new_value, int(new_value != value)
    if isinstance(value, list):
        out = []
        changes = 0
        for item in value:
            new_item, n = _normalize(item)
            out.append(new_item)
            changes += n
        return out, changes
    if isinstance(value, dict):
        out: Dict[Any, Any] = {}
        changes = 0
        for k, v in value.items():
            new_k = k.replace("\\", "/") if isinstance(k, str) else k
            changes += int(new_k != k)
            new_v, n = _normalize(v)
            out[new_k] = new_v
            changes += n
        return out, changes
    return value, 0


def main():
    parser = argparse.ArgumentParser(description="Normalize path separators in a JSON file.")
    parser.add_argument("--path", required=True, help="Path to the JSON file to normalize.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing.")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    new_data, changes = _normalize(data)

    report = {
        "path": str(path),
        "dry_run": bool(args.dry_run),
        "changes": changes,
        "ok": True,
    }

    if not args.dry_run and changes > 0:
        path.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
