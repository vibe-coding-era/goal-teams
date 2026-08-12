#!/usr/bin/env python3
"""Validate V2.62/V2.63 owner projections and semantic route closure."""

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

from scripts.v250.generation_runtime import (
    GenerationLoadError,
    load_candidate_generation,
    load_generation,
    load_prepared_generation,
    resolve_repo_file,
)
from scripts.v250.replay_runner import load_replay_manifest, run_replay
from scripts.v250.route_closure import (
    RouteClosureError,
    compile_route_closure,
    validate_declared_route_closure,
)


RULE_RE = re.compile(r"^- \x60(GT(?:250|263)-[A-Z0-9-]+)\x60:", re.MULTILINE)


def validate_generation(
    repo_root: Path | str,
    generation_id: str = "V2.63",
    *,
    selection: str = "active",
    expected_activation_sha256: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    errors: list[str] = []
    closures: dict[str, Any] = {}
    if selection == "active" and expected_activation_sha256 is not None:
        return {
            "ok": False,
            "generation_id": generation_id,
            "selection": selection,
            "errors": ["E_V250_ACTIVE_EXTERNAL_DIGEST_FORBIDDEN"],
            "closures": {},
        }
    try:
        if selection in {"candidate", "prepared-active"}:
            activation_path = (
                root
                / f"references/current/generations/{generation_id}/activation-manifest.json"
            )
            if expected_activation_sha256 is None:
                return {
                    "ok": False,
                    "generation_id": generation_id,
                    "selection": selection,
                    "errors": ["E_V250_EXPLICIT_DIGEST_REQUIRED"],
                    "closures": {},
                }
            loader = (
                load_candidate_generation
                if selection == "candidate"
                else load_prepared_generation
            )
            generation = loader(
                root,
                generation_id=generation_id,
                activation_manifest_path=activation_path.relative_to(root).as_posix(),
                expected_activation_sha256=expected_activation_sha256,
            )
        elif selection == "active":
            generation = load_generation(root, generation_id=generation_id)
        else:
            return {
                "ok": False,
                "generation_id": generation_id,
                "selection": selection,
                "errors": ["E_V250_SELECTION_INVALID"],
                "closures": {},
            }
    except GenerationLoadError as exc:
        return {
            "ok": False,
            "generation_id": generation_id,
            "selection": selection,
            "errors": [exc.code],
            "closures": {},
        }

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
                closures[route_id] = (
                    validate_declared_route_closure(
                        root,
                        generation,
                        route_id=route_id,
                    )
                    if generation_id == "V2.63"
                    else compile_route_closure(root, generation, route_id)
                )
            except RouteClosureError as exc:
                errors.append(exc.code)

    # Candidate validation proves its own Legacy zero-intersection from the
    # candidate activation. Replay execution remains bound to the active
    # generation until ACTIVE-last cutover.
    if generation_id != "V2.63":
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
        "selection": selection,
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
    parser.add_argument("--generation-id", default="V2.63")
    parser.add_argument(
        "--selection",
        required=True,
        choices=("candidate", "prepared-active", "active"),
    )
    parser.add_argument("--expected-activation-sha256")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = validate_generation(
        args.repo_root,
        args.generation_id,
        selection=args.selection,
        expected_activation_sha256=args.expected_activation_sha256,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["ok"]:
        print(
            f"{args.generation_id} generation validation passed: "
            f"{result['route_count']} routes, {result['rule_count']} unique rules"
        )
    else:
        print(f"{args.generation_id} generation validation failed: " + ", ".join(result["errors"]))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
