"""Compile and verify a V2.6 Current route closure."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scripts.v250.generation_runtime import canonical_json_digest, resolve_repo_file, sha256_bytes


class RouteClosureError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


PATH_TOKEN_RE = re.compile(r"(?:\x60|\()((?:references|schemas|scripts|prompts|subagents|tests)/[^\x60)\s]+)")


def _deduplicate_paths(values: Any) -> list[str]:
    if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
        raise RouteClosureError("E_V250_ROUTE_REFS", "ordered_refs must be a non-empty string array")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _is_legacy(path: str, exact: set[str], prefixes: list[str]) -> bool:
    return path in exact or any(path.startswith(prefix) for prefix in prefixes)


def compile_route_closure(
    repo_root: Path | str,
    generation: dict[str, Any],
    route_id: str,
) -> dict[str, Any]:
    """Compile a route from ordered refs and fail closed on drift."""

    if generation.get("generation_id") != "V2.6":
        raise RouteClosureError("E_V250_ROUTE_GENERATION", "V2.6 route compiler received another generation")
    if not generation.get("activation_digest_verified") or not generation.get("member_digests_verified"):
        raise RouteClosureError("E_V250_ROUTE_UNVERIFIED_GENERATION", "generation digests are not verified")

    prompt_manifest = generation.get("prompt_manifest")
    rule_manifest = generation.get("rule_manifest")
    if not isinstance(prompt_manifest, dict) or not isinstance(rule_manifest, dict):
        raise RouteClosureError("E_V250_ROUTE_MANIFEST", "prompt and rule manifests are required")
    routes = prompt_manifest.get("routes")
    if not isinstance(routes, dict) or route_id not in routes:
        raise RouteClosureError("E_V250_ROUTE_UNKNOWN", f"unknown route: {route_id}")
    route = routes[route_id]
    if not isinstance(route, dict):
        raise RouteClosureError("E_V250_ROUTE_SHAPE", f"invalid route object: {route_id}")

    loaded_paths = _deduplicate_paths(route.get("ordered_refs"))
    allowlist = generation.get("current_default_allowlist", [])
    if not isinstance(allowlist, list):
        raise RouteClosureError("E_V250_ROUTE_ALLOWLIST", "generation current allowlist is invalid")
    allowset = set(allowlist)
    unmanaged = sorted(path for path in loaded_paths if path not in allowset)
    if unmanaged:
        raise RouteClosureError("E_V250_ROUTE_UNMANAGED", "route loads unmanaged paths: " + ", ".join(unmanaged))

    exact_legacy = set(generation.get("legacy_exact_paths", []))
    legacy_prefixes = list(generation.get("legacy_path_prefixes", []))
    legacy_references: set[str] = set()
    loaded_bytes = 0
    observed_digests: dict[str, str] = {}
    root = Path(repo_root).resolve()
    for relative_path in loaded_paths:
        if _is_legacy(relative_path, exact_legacy, legacy_prefixes):
            legacy_references.add(relative_path)
        path = resolve_repo_file(root, relative_path)
        raw = path.read_bytes()
        loaded_bytes += len(raw)
        observed_digests[relative_path] = sha256_bytes(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RouteClosureError("E_V250_ROUTE_NON_TEXT", f"rule file is not UTF-8: {relative_path}") from exc
        for token in PATH_TOKEN_RE.findall(text):
            normalized = token.rstrip(".,;:")
            if _is_legacy(normalized, exact_legacy, legacy_prefixes):
                legacy_references.add(normalized)

    legacy_intersection = sorted(legacy_references)
    if legacy_intersection:
        raise RouteClosureError(
            "E_V250_ROUTE_LEGACY_REACHABLE",
            "Current route reaches Legacy: " + ", ".join(legacy_intersection),
        )

    owners = rule_manifest.get("owners")
    if not isinstance(owners, list):
        raise RouteClosureError("E_V250_RULE_INDEX", "rule manifest owners must be an array")
    owner_by_path: dict[str, dict[str, Any]] = {}
    all_rule_ids: set[str] = set()
    duplicate_rule_ids: set[str] = set()
    for owner in owners:
        if not isinstance(owner, dict) or not isinstance(owner.get("path"), str):
            raise RouteClosureError("E_V250_RULE_OWNER", "invalid rule owner")
        owner_path = owner["path"]
        if owner_path in owner_by_path:
            raise RouteClosureError("E_V250_RULE_OWNER_DUPLICATE", f"duplicate owner path: {owner_path}")
        owner_by_path[owner_path] = owner
        for rule_id in owner.get("owned_rule_ids", []):
            if rule_id in all_rule_ids:
                duplicate_rule_ids.add(rule_id)
            all_rule_ids.add(rule_id)
    if duplicate_rule_ids:
        raise RouteClosureError(
            "E_V250_RULE_ID_DUPLICATE",
            "duplicate rule IDs: " + ", ".join(sorted(duplicate_rule_ids)),
        )

    compiled_rule_ids: list[str] = []
    for path in loaded_paths:
        owner = owner_by_path.get(path)
        if owner is None:
            raise RouteClosureError("E_V250_ROUTE_WITHOUT_OWNER", f"route ref has no rule owner: {path}")
        if route_id not in owner.get("route_membership", []):
            raise RouteClosureError(
                "E_V250_ROUTE_MEMBERSHIP_DRIFT",
                f"owner {owner.get('owner_id')} does not declare route {route_id}",
            )
        expected_source = owner.get("source_sha256")
        if observed_digests[path] != expected_source:
            raise RouteClosureError("E_V250_OWNER_DIGEST_DRIFT", f"owner digest differs: {path}")
        compiled_rule_ids.extend(owner.get("owned_rule_ids", []))

    expected_bytes = route.get("expected_loaded_rule_bytes")
    if not isinstance(expected_bytes, int) or expected_bytes != loaded_bytes:
        raise RouteClosureError(
            "E_V250_ROUTE_BYTE_DRIFT",
            f"route {route_id} expected {expected_bytes}, observed {loaded_bytes}",
        )
    route_budget = route.get("max_loaded_rule_bytes")
    generation_budget = generation.get("activation_manifest", {}).get("budgets", {}).get("max_route_rule_bytes")
    budgets = [value for value in (route_budget, generation_budget) if isinstance(value, int)]
    if not budgets or loaded_bytes > min(budgets):
        raise RouteClosureError("E_V250_ROUTE_BUDGET", f"route {route_id} uses {loaded_bytes} bytes")

    result = {
        "generation_id": "V2.6",
        "route_id": route_id,
        "loaded_paths": loaded_paths,
        "loaded_rule_files": list(loaded_paths),
        "loaded_rule_file_count": len(loaded_paths),
        "loaded_rule_bytes": loaded_bytes,
        "compiled_rule_ids": compiled_rule_ids,
        "required_gates": list(route.get("required_gates", [])),
        "conditional_gates": list(route.get("conditional_gates", [])),
        "legacy_references": [],
        "legacy_intersection": [],
        "manual_artifact_count": route.get("manual_artifact_count", 0),
        "governance_time": route.get("governance_time", "unknown"),
        "path_digests": observed_digests,
    }
    result["closure_digest"] = canonical_json_digest(result)
    return result


__all__ = ["RouteClosureError", "compile_route_closure"]
