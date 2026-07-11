#!/usr/bin/env python3
"""Fail closed when the Goal Teams startup context exceeds its V2.3 budget."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_LIMIT = 12 * 1024
BASE_FILES = ("SKILL.md", "agents/openai.yaml", "RULES.md")
ROUTED_CORE_FILES = (
    "references/invariants.md",
    "prompts/lead/core.md",
    "prompts/lead/planning.md",
    "prompts/packets/memory.md",
    "references/compat.md",
)


def file_sizes(root: Path, relative_paths: tuple[str, ...]) -> dict[str, int]:
    result: dict[str, int] = {}
    for relative in relative_paths:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"missing context file: {relative}")
        result[relative] = len(path.read_bytes())
    return result


def evaluate(root: Path, limit: int) -> dict[str, object]:
    if limit <= 0:
        raise ValueError("context limit must be positive")
    base = file_sizes(root, BASE_FILES)
    routed = file_sizes(root, ROUTED_CORE_FILES)
    base_total = sum(base.values())
    routed_total = sum(routed.values())
    return {
        "schema_version": "goal-teams-context-budget-v2.3",
        "base": {
            "definition": "startup auto-load plus mandatory response contract",
            "files": base,
            "bytes": base_total,
            "limit_bytes": limit,
            "remaining_bytes": limit - base_total,
            "passed": base_total <= limit,
        },
        "routed": {
            "definition": "loaded only after goal/profile routing; reported separately from startup budget",
            "files": routed,
            "bytes": routed_total,
        },
        "passed": base_total <= limit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--limit-bytes", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    try:
        result = evaluate(args.root.resolve(), args.limit_bytes)
    except ValueError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
