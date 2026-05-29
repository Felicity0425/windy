"""Batch-rewrite migrated absolute paths inside JSON manifests/summaries.

This is useful after moving a dataset from a Windows machine to the current
Linux workspace. It can rewrite old absolute prefixes in-place across a directory
-tree while keeping the rest of each JSON file intact.

Typical use:
    python rewire_migrated_paths.py \
      --root /data/LFT-W02_data/pengxu \
      --old-prefix C:\\Users\\007\\Desktop\\wind\\windy \
      --new-prefix /data/LFT-W02_data/pengxu

You can also use multiple mapping pairs:
    python rewire_migrated_paths.py \
      --root /data/LFT-W02_data/pengxu \
      --map C:\\Users\\007\\Desktop\\wind\\windy=/data/LFT-W02_data/pengxu \
      --map D:\\old_data=/mnt/data
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

JSON_EXTENSIONS = {".json"}
DEFAULT_SKIP_DIRS = {".git", "__pycache__", ".venv", ".conda"}


def _parse_maps(args: List[str], old_prefix: str | None, new_prefix: str | None) -> List[Tuple[str, str]]:
    mappings: List[Tuple[str, str]] = []
    if old_prefix and new_prefix:
        mappings.append((old_prefix, new_prefix))
    for item in args:
        if "=" not in item:
            raise ValueError(f"invalid --map value: {item!r}, expected old=new")
        old, new = item.split("=", 1)
        mappings.append((old, new))
    if not mappings:
        raise ValueError("no path mappings provided")
    return mappings


def _rewrite_string(value: str, mappings: Iterable[Tuple[str, str]]) -> str:
    out = value
    for old, new in mappings:
        if old in out:
            out = out.replace(old, new)
    return out


def _rewrite_obj(obj: Any, mappings: Iterable[Tuple[str, str]]) -> Tuple[Any, int]:
    changes = 0
    if isinstance(obj, str):
        new_val = _rewrite_string(obj, mappings)
        return new_val, int(new_val != obj)
    if isinstance(obj, list):
        new_list = []
        for item in obj:
            new_item, c = _rewrite_obj(item, mappings)
            new_list.append(new_item)
            changes += c
        return new_list, changes
    if isinstance(obj, dict):
        new_dict: Dict[str, Any] = {}
        for k, v in obj.items():
            new_k = _rewrite_string(k, mappings) if isinstance(k, str) else k
            if new_k != k:
                changes += 1
            new_v, c = _rewrite_obj(v, mappings)
            new_dict[new_k] = new_v
            changes += c
        return new_dict, changes
    return obj, 0


def _should_skip(path: Path) -> bool:
    return any(part in DEFAULT_SKIP_DIRS for part in path.parts)


def _iter_json_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in JSON_EXTENSIONS and not _should_skip(path):
            yield path


def _process_file(path: Path, mappings: List[Tuple[str, str]], dry_run: bool = False) -> Tuple[bool, int, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return False, 0, f"read error: {e}"

    try:
        data = json.loads(text)
    except Exception as e:
        return False, 0, f"json parse error: {e}"

    new_data, changes = _rewrite_obj(data, mappings)
    if changes == 0:
        return True, 0, None

    if not dry_run:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    return True, changes, None


def main():
    parser = argparse.ArgumentParser(description="Batch rewrite absolute paths inside JSON files.")
    parser.add_argument("--root", required=True, help="Root directory to scan recursively.")
    parser.add_argument("--map", action="append", default=[], help="Rewrite mapping in old=new form. Can be repeated.")
    parser.add_argument("--old-prefix", help="Legacy prefix to rewrite (paired with --new-prefix).")
    parser.add_argument("--new-prefix", help="Replacement prefix (paired with --old-prefix).")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    args = parser.parse_args()

    mappings = _parse_maps(args.map, args.old_prefix, args.new_prefix)
    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"root not found: {root}")

    scanned = 0
    changed = 0
    errors: List[Dict[str, str]] = []

    for path in _iter_json_files(root):
        scanned += 1
        ok, n_changes, err = _process_file(path, mappings, dry_run=args.dry_run)
        if not ok:
            errors.append({"file": str(path), "error": err or "unknown"})
            continue
        if n_changes > 0:
            changed += 1
            print(f"[changed] {path} ({n_changes} replacements)")

    report = {
        "root": str(root),
        "dry_run": bool(args.dry_run),
        "mappings": [{"old": old, "new": new} for old, new in mappings],
        "scanned_json_files": scanned,
        "changed_files": changed,
        "errors": errors,
        "ok": len(errors) == 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
