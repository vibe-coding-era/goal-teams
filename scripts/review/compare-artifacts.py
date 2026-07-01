#!/usr/bin/env python3
"""Compare files or directories and emit deterministic review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, root: Path | None = None) -> dict[str, Any]:
    label = str(path.relative_to(root)) if root else path.name
    return {
        "path": label,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def collect(path: Path) -> list[dict[str, Any]]:
    if path.is_file():
        return [file_record(path)]
    if not path.is_dir():
        raise SystemExit(f"[FAIL] Not a file or directory: {path}")
    return [file_record(item, path) for item in sorted(path.rglob("*")) if item.is_file()]


def compare(left: Path, right: Path) -> dict[str, Any]:
    left_records = collect(left)
    right_records = collect(right)
    left_by_path = {item["path"]: item for item in left_records}
    right_by_path = {item["path"]: item for item in right_records}
    all_paths = sorted(set(left_by_path) | set(right_by_path))
    changed = []
    missing_left = []
    missing_right = []
    same = []
    for path in all_paths:
        left_item = left_by_path.get(path)
        right_item = right_by_path.get(path)
        if left_item is None:
            missing_left.append(path)
        elif right_item is None:
            missing_right.append(path)
        elif left_item["sha256"] == right_item["sha256"]:
            same.append(path)
        else:
            changed.append(
                {
                    "path": path,
                    "left_sha256": left_item["sha256"],
                    "right_sha256": right_item["sha256"],
                    "left_bytes": left_item["bytes"],
                    "right_bytes": right_item["bytes"],
                }
            )
    status = "passed" if not changed and not missing_left and not missing_right else "changed"
    return {
        "tool": "compare-artifacts",
        "left": str(left),
        "right": str(right),
        "status": status,
        "same_count": len(same),
        "changed": changed,
        "missing_left": missing_left,
        "missing_right": missing_right,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        left = root / "left"
        right = root / "right"
        left.mkdir()
        right.mkdir()
        (left / "same.txt").write_text("same\n", encoding="utf-8")
        (right / "same.txt").write_text("same\n", encoding="utf-8")
        (left / "changed.txt").write_text("left\n", encoding="utf-8")
        (right / "changed.txt").write_text("right\n", encoding="utf-8")
        result = compare(left, right)
        if result["status"] != "changed" or len(result["changed"]) != 1:
            raise SystemExit("[FAIL] compare-artifacts self-test failed")
    print("Artifact comparison self-test passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", nargs="?")
    parser.add_argument("right", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.left or not args.right:
        parser.error("left and right are required unless --self-test is used")
    payload = compare(Path(args.left), Path(args.right))
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
