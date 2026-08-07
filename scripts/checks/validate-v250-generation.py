#!/usr/bin/env python3
"""Validate V2.6 owner projections, route closures, budgets, and replay isolation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.v250.generation_runtime import GenerationLoadError, load_generation, resolve_repo_file
from scripts.v250.replay_runner import load_replay_manifest, run_replay
from scripts.v250.route_closure import RouteClosureError, compile_route_closure


RULE_RE = re.compile(r"^- \x60(GT250-[A-Z0-9-]+)\x60:", re.MULTILINE)


def validate_generation(repo_root: Path | str, generation_id: str = "V2.6") -> dict[str, Any]:
    root = Path(repo_root).resolve()
    errors: list[str] = []
    closures: dict[str, Any] = {}
    try:
        generation = load_generation(root, generation_id=generation_id)
    except GenerationLoadError as exc:
        return {"ok": False, "generation_id": generation_id, "errors": [exc.code], "closures": {}}

    rule_manifest = generation.get("rule_manifest", {})
    prompt_manifest = generation.get("prompt_manifest", {})
    owners = rule_manifest.get("owners", [])
    owner_ids: set[str] = set()
    owner_paths: set[str] = set()
    all_rules: set[str] = set()
    duplicate_rules: set[str] = set()

    if not isinstance(owners, list) or not owners:
        errors.append("E_V250_RULE_OWNERS_EMPTY")
    else:
        for owner in owners:
            if not isinstance(owner, dict):
                errors.append("E_V250_RULE_OWNER_INVALID")
                continue
            owner_id = owner.get("owner_id")
            path = owner.get("path")
            if not isinstance(owner_id, str) or owner_id in owner_ids:
                errors.append("E_V250_RULE_OWNER_DUPLICATE")
            else:
                owner_ids.add(owner_id)
            if not isinstance(path, str) or path in owner_paths:
                errors.append("E_V250_RULE_OWNER_PATH_DUPLICATE")
                continue
            owner_paths.add(path)
            try:
                source = resolve_repo_file(root, path).read_text(encoding="utf-8")
            except (GenerationLoadError, UnicodeDecodeError):
                errors.append("E_V250_RULE_OWNER_UNREADABLE")
                continue
            source_rules = set(RULE_RE.findall(source))
            projected_rules = owner.get("owned_rule_ids")
            if not isinstance(projected_rules, list) or source_rules != set(projected_rules):
                errors.append("E_V250_RULE_PROJECTION_DRIFT")
                continue
            for rule_id in projected_rules:
                if rule_id in all_rules:
                    duplicate_rules.add(rule_id)
                all_rules.add(rule_id)
        if duplicate_rules:
            errors.append("E_V250_RULE_ID_DUPLICATE")

    routes = prompt_manifest.get("routes", {})
    if not isinstance(routes, dict) or not routes:
        errors.append("E_V250_ROUTES_EMPTY")
    else:
        for route_id in sorted(routes):
            try:
                closures[route_id] = compile_route_closure(root, generation, route_id)
            except RouteClosureError as exc:
                errors.append(exc.code)

    try:
        replay_manifest = load_replay_manifest(root)
        replay_versions = [entry["legacy_version"] for entry in replay_manifest["replays"]]
        for version in replay_versions:
            denied = run_replay(root, version)
            if denied.get("status") != "replay_unavailable":
                errors.append("E_V250_REPLAY_IMPLICITLY_ENABLED")
            explicit = run_replay(root, version, explicit_intent=True)
            if explicit.get("status") not in {"historical_passed", "historical_failed", "replay_unavailable"}:
                errors.append("E_V250_REPLAY_OUTPUT")
            if explicit.get("current_completion_eligible") is not False:
                errors.append("E_V250_REPLAY_CURRENT_LEAK")
    except GenerationLoadError as exc:
        errors.append(exc.code)

    return {
        "ok": not errors,
        "generation_id": generation_id,
        "activation_manifest_sha256": generation.get("activation_manifest_sha256"),
        "prompt_manifest_sha256": generation.get("prompt_manifest_sha256"),
        "rule_manifest_sha256": generation.get("rule_manifest_sha256"),
        "route_count": len(closures),
        "rule_count": len(all_rules),
        "errors": sorted(set(errors)),
        "closures": closures,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--generation-id", default="V2.6")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = validate_generation(args.repo_root, args.generation_id)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["ok"]:
        print(
            f"V2.6 generation validation passed: "
            f"{result['route_count']} routes, {result['rule_count']} unique rules"
        )
    else:
        print("V2.6 generation validation failed: " + ", ".join(result["errors"]))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
