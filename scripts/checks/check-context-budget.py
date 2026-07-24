#!/usr/bin/env python3
"""Fail closed when Goal Teams startup, routed rules, or role packages exceed budget."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


# V2.44 loads the mandatory flow-clarification protocol at startup.  The
# repository-startup route budget is the source of truth in the prompt-cache
# manifest; this default keeps the legacy checker aligned with that route.
DEFAULT_LIMIT = 21_504
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


def _load_prompt_cache(root: Path):
    path = root / "scripts" / "v23" / "prompt_cache.py"
    if not path.is_file():
        raise ValueError("missing prompt cache runtime: scripts/v23/prompt_cache.py")
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("_goalteams_prompt_cache_budget", path)
        if spec is None or spec.loader is None:
            raise ValueError("cannot load prompt cache runtime")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


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
    prompt_cache = _load_prompt_cache(root)
    installed_identity = prompt_cache.build_prompt_identity(root, "installed_startup")
    repository_scope = (root / ".agents" / "skills" / "goal-teams" / "SKILL.md").is_file()
    repository_identity = prompt_cache.build_prompt_identity(
        root, "repository_startup" if repository_scope else "installed_startup"
    )
    base = file_sizes(root, BASE_FILES)
    routed = file_sizes(root, ROUTED_CORE_FILES)
    routing = file_sizes(root, V235_ROUTING_FILES)
    base_total = sum(base.values())
    routed_total = sum(routed.values())
    startup = {
        "definition": (
            "repository wrapper plus startup auto-load and mandatory response contract"
            if repository_scope
            else "installed startup auto-load plus mandatory response contract"
        ),
        "files": {
            path: metadata["bytes"]
            for path, metadata in repository_identity["files"].items()
        },
        "ordered_refs": repository_identity["ordered_refs"],
        "manifest_ordered_refs": repository_identity["ordered_refs"],
        "prefix_manifest_sha256": repository_identity["prefix_manifest_sha256"],
        "route_static_digest": repository_identity["route_static_digest"],
        "runtime_prompt_digest": repository_identity["runtime_prompt_digest"],
        "manifest_status": repository_identity["manifest_status"],
        "digest_scope": repository_identity["digest_scope"],
        "budget_receipt": repository_identity["budget_receipt"],
        "bytes": repository_identity["route_bytes"],
        "limit_bytes": limit,
        "remaining_bytes": limit - repository_identity["route_bytes"],
        "passed": repository_identity["passed"] and repository_identity["route_bytes"] <= limit,
    }
    base_result = {
        "definition": "installed startup auto-load plus mandatory response contract",
        "files": base,
        "ordered_refs": installed_identity["ordered_refs"],
        "manifest_ordered_refs": installed_identity["ordered_refs"],
        "prefix_manifest_sha256": installed_identity["prefix_manifest_sha256"],
        "route_static_digest": installed_identity["route_static_digest"],
        "runtime_prompt_digest": installed_identity["runtime_prompt_digest"],
        "manifest_status": installed_identity["manifest_status"],
        "digest_scope": installed_identity["digest_scope"],
        "budget_receipt": installed_identity["budget_receipt"],
        "bytes": base_total,
        "limit_bytes": limit,
        "remaining_bytes": limit - base_total,
        "passed": installed_identity["passed"] and base_total <= limit,
    }
    routing_result = {
        "definition": "V2.44 conditionally routed core/profile policy files",
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
    route_ids = ("runtime", "capability", "telemetry", "benchmark", "production")
    routes = {}
    for route_id in route_ids:
        identity = prompt_cache.build_prompt_identity(root, route_id)
        routes[route_id] = {
            **identity,
            "bytes": identity["route_bytes"],
            "manifest_ordered_refs": identity["ordered_refs"],
        }
    passed = (
        bool(startup["passed"])
        and bool(base_result["passed"])
        and bool(routing_result["passed"])
        and all(bool(item["passed"]) for item in routes.values())
        and all(bool(item["passed"]) for item in specialists.values())
    )
    return {
        "schema_version": "goal-teams-context-budget-v2.41",
        "startup": startup,
        "base": base_result,
        "routed": {
            "definition": "loaded only after goal/profile routing; reported separately from startup budget",
            "files": routed,
            "bytes": routed_total,
        },
        "routing": routing_result,
        "routes": routes,
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
