#!/usr/bin/env python3
"""Fail closed when Goal Teams startup, routed rules, or role packages exceed budget."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_LIMIT = 12_032
BASE_FILES = ("SKILL.md", "agents/openai.yaml", "RULES.md")
ROUTED_CORE_FILES = (
    "references/invariants.md",
    "prompts/lead/core.md",
    "prompts/lead/planning.md",
    "prompts/packets/memory.md",
    "references/compat.md",
)
V235_ROUTING_FILES = (
    "references/rules-project-sizing.md",
    "references/rules-specialists.md",
    "references/test-case-assertion-protocol.md",
)
V235_ROUTING_LIMITS = {
    "references/rules-project-sizing.md": 6 * 1024,
    "references/rules-specialists.md": 6 * 1024,
    "references/test-case-assertion-protocol.md": 8 * 1024,
}
SPECIALIST_ROLES = ("security", "performance", "refactor", "sqa")
SPECIALIST_FILES = ("prompt.md", "template.md", "workflow.md", "scripts.md")
SPECIALIST_PROMPT_LIMIT = 3 * 1024
SPECIALIST_PACKAGE_LIMIT = 10 * 1024


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
    routing = file_sizes(root, V235_ROUTING_FILES)
    base_total = sum(base.values())
    routed_total = sum(routed.values())
    startup = {
        "definition": "startup auto-load plus mandatory response contract",
        "files": base,
        "bytes": base_total,
        "limit_bytes": limit,
        "remaining_bytes": limit - base_total,
        "passed": base_total <= limit,
    }
    routing_result = {
        "definition": "V2.37 conditionally routed core/profile policy files",
        "files": routing,
        "bytes": sum(routing.values()),
        "limits": V235_ROUTING_LIMITS,
        "passed": all(
            routing[path] <= V235_ROUTING_LIMITS[path] for path in V235_ROUTING_FILES
        ),
    }
    specialists: dict[str, object] = {}
    for role in SPECIALIST_ROLES:
        paths = tuple(f"prompts/members/{role}/{name}" for name in SPECIALIST_FILES)
        sizes = file_sizes(root, paths)
        prompt_size = sizes[f"prompts/members/{role}/prompt.md"]
        package_size = sum(sizes.values())
        specialists[role] = {
            "files": sizes,
            "prompt_bytes": prompt_size,
            "package_bytes": package_size,
            "prompt_limit_bytes": SPECIALIST_PROMPT_LIMIT,
            "package_limit_bytes": SPECIALIST_PACKAGE_LIMIT,
            "passed": (
                prompt_size <= SPECIALIST_PROMPT_LIMIT
                and package_size <= SPECIALIST_PACKAGE_LIMIT
            ),
        }
    passed = (
        bool(startup["passed"])
        and bool(routing_result["passed"])
        and all(bool(item["passed"]) for item in specialists.values())
    )
    return {
        "schema_version": "goal-teams-context-budget-v2.37",
        "startup": startup,
        "base": startup,
        "routed": {
            "definition": "loaded only after goal/profile routing; reported separately from startup budget",
            "files": routed,
            "bytes": routed_total,
        },
        "routing": routing_result,
        "specialists": specialists,
        "passed": passed,
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
