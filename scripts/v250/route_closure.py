"""Compile and verify a Current route closure."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.v250.generation_runtime import (
    canonical_json_bytes,
    canonical_json_digest,
    resolve_repo_file,
    sha256_bytes,
)


class RouteClosureError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


PATH_TOKEN_RE = re.compile(r"(?:\x60|\()((?:references|schemas|scripts|prompts|subagents|tests)/[^\x60)\s]+)")


def _ordered_paths(values: Any, *, reject_duplicates: bool) -> list[str]:
    if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
        raise RouteClosureError("E_V250_ROUTE_REFS", "ordered_refs must be a non-empty string array")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            if reject_duplicates:
                raise RouteClosureError(
                    "E_V263_ORDERED_REF_DUPLICATE", f"ordered_refs repeats {value}"
                )
            continue
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
    """Compile a legacy direct route; modern runtime callers must use facts."""

    if generation.get("generation_id") in {"V2.63", "V2.65"}:
        raise RouteClosureError(
            "E_V263_ROUTE_FACTS_REQUIRED",
            "V2.63 runtime route closure requires a DerivedRouteReceipt",
        )
    return _compile_route_closure(
        repo_root,
        generation,
        route_id=route_id,
        route_selection_mode="active_bound_legacy",
        derived_route_sha256=None,
    )


def _compile_route_closure(
    repo_root: Path | str,
    generation: dict[str, Any],
    *,
    route_id: str,
    route_selection_mode: str,
    derived_route_sha256: str | None,
) -> dict[str, Any]:
    """Compile the manifest-declared exact route and fail closed on drift."""

    generation_id = generation.get("generation_id")
    if generation_id not in {"V2.62", "V2.63", "V2.65"}:
        raise RouteClosureError("E_V250_ROUTE_GENERATION", "route compiler received an unsupported generation")
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

    loaded_paths = _ordered_paths(
        route.get("ordered_refs"), reject_duplicates=generation_id in {"V2.63", "V2.65"}
    )
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

    if generation_id in {"V2.63", "V2.65"}:
        from scripts.v250.semantic_closure import (
            SemanticClosureError,
            compile_owner_closure,
            validate_route_controls,
        )

        workflow_phase = route.get("workflow_phase")
        semantic_phase = "development" if workflow_phase == "startup" else workflow_phase
        try:
            controls = validate_route_controls(
                {
                    "workflow_phase": semantic_phase,
                    "required_gates": route.get("required_gates", []),
                    "conditional_gates": route.get("conditional_gates", []),
                }
            )
            semantic = compile_owner_closure(
                owners=owners,
                route_id=route_id,
                phase=semantic_phase,
                facts={"agent_runtime": route_id == "V250-ROUTE-AGENT-RUNTIME"},
                ordered_refs=loaded_paths,
            )
        except SemanticClosureError as exc:
            raise RouteClosureError(exc.code, exc.message) from exc
        if controls["required_gates"] != route.get("required_gates", []) or controls[
            "conditional_gates"
        ] != route.get("conditional_gates", []):
            raise RouteClosureError(
                "E_V263_CONTROL_ALIAS",
                "modern route manifests must store canonical controls",
            )

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
        "generation_id": generation_id,
        "route_id": route_id,
        "route_selection_mode": route_selection_mode,
        "derived_route_sha256": derived_route_sha256,
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
    if generation_id in {"V2.63", "V2.65"}:
        result["semantic_closure_sha256"] = semantic["closure_sha256"]
    result["closure_digest"] = canonical_json_digest(result)
    return result


def _validate_derived_route_receipt(
    generation: dict[str, Any], receipt: Any
) -> tuple[str, str]:
    if not isinstance(receipt, dict):
        raise RouteClosureError(
            "E_V263_DERIVED_ROUTE_RECEIPT", "derived route receipt is required"
        )
    generation_id = generation.get("generation_id")
    if (
        generation_id not in {"V2.63", "V2.65"}
        or receipt.get("derivation_version") != generation_id
        or receipt.get("schema_version")
        != f"goal-teams-derived-route-receipt-{str(generation_id).lower()}"
    ):
        raise RouteClosureError(
            "E_V263_DERIVED_ROUTE_RECEIPT", "derived route identity differs"
        )
    observed = receipt.get("receipt_sha256")
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if not isinstance(observed, str) or observed != canonical_json_digest(payload):
        raise RouteClosureError(
            "E_V263_DERIVED_ROUTE_DIGEST", "derived route receipt digest differs"
        )
    try:
        from scripts.v250.prompt_compiler import (
            PromptCompilerError,
            validate_derived_route_receipt,
        )

        validate_derived_route_receipt(receipt)
    except PromptCompilerError as exc:
        raise RouteClosureError(
            "E_V263_DERIVED_ROUTE_REPLAY",
            "derived route failed exact ProjectRouteFacts replay",
        ) from exc
    route_id = receipt.get("route_id")
    if not isinstance(route_id, str) or not route_id:
        raise RouteClosureError(
            "E_V263_DERIVED_ROUTE_RECEIPT", "derived route id is missing"
        )

    prompt = generation.get("prompt_manifest")
    routes = prompt.get("routes") if isinstance(prompt, dict) else None
    route = routes.get(route_id) if isinstance(routes, dict) else None
    if not isinstance(route, dict):
        raise RouteClosureError("E_V250_ROUTE_UNKNOWN", f"unknown route: {route_id}")
    try:
        from scripts.v250.semantic_closure import validate_route_controls

        manifest_controls = validate_route_controls(
            {
                "workflow_phase": (
                    "development"
                    if route.get("workflow_phase") == "startup"
                    else route.get("workflow_phase")
                ),
                "required_gates": route.get("required_gates", []),
                "conditional_gates": route.get("conditional_gates", []),
            }
        )
        derived_controls = validate_route_controls(
            {
                "workflow_phase": receipt.get("workflow_phase"),
                "required_gates": receipt.get("required_gates", []),
                "conditional_gates": receipt.get("conditional_gates", []),
            }
        )
    except (ValueError, TypeError) as exc:
        raise RouteClosureError(
            "E_V263_DERIVED_ROUTE_CONTROLS", str(exc)
        ) from exc
    manifest_required = set(manifest_controls["required_gates"])
    manifest_all = manifest_required | set(manifest_controls["conditional_gates"])
    derived_required = set(derived_controls["required_gates"])
    derived_all = derived_required | set(derived_controls["conditional_gates"])
    if (
        derived_controls["workflow_phase"] != manifest_controls["workflow_phase"]
        or not manifest_required.issubset(derived_required)
        or derived_all != manifest_all
    ):
        raise RouteClosureError(
            "E_V263_DERIVED_ROUTE_CONTROLS",
            "derived and manifest route controls differ",
        )
    return route_id, observed


def compile_derived_route_closure(
    repo_root: Path | str,
    generation: dict[str, Any],
    derived_route_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Compile the only V2.63 runtime route entry from a verified receipt."""

    route_id, receipt_sha256 = _validate_derived_route_receipt(
        generation, derived_route_receipt
    )
    return _compile_route_closure(
        repo_root,
        generation,
        route_id=route_id,
        route_selection_mode="facts_derived",
        derived_route_sha256=receipt_sha256,
    )


def validate_declared_route_closure(
    repo_root: Path | str,
    generation: dict[str, Any],
    *,
    route_id: str,
) -> dict[str, Any]:
    """Offline-only manifest audit; this does not authorize a runtime route."""

    return _compile_route_closure(
        repo_root,
        generation,
        route_id=route_id,
        route_selection_mode="offline_manifest_audit",
        derived_route_sha256=None,
    )


def _normalized_json_object(raw: bytes, *, evidence_kind: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw:
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_EVIDENCE_REQUIRED",
            f"{evidence_kind} evidence is required",
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_EVIDENCE_JSON",
            f"{evidence_kind} evidence is not valid UTF-8 JSON",
        ) from exc
    if not isinstance(value, dict):
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_EVIDENCE_JSON",
            f"{evidence_kind} evidence must be an object",
        )
    if raw != canonical_json_bytes(value) + b"\n":
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_EVIDENCE_NORMALIZATION",
            f"{evidence_kind} evidence is not canonical JSON with one trailing newline",
        )
    return value


def validate_released_runtime_route_triplet(
    repo_root: Path | str,
    generation: dict[str, Any],
    *,
    project_route_facts_raw: bytes,
    derived_route_receipt_raw: bytes,
    route_closure_raw: bytes,
    expected_stage: str,
    expected_workflow_phase: str,
    expected_project_size: str,
    expected_route_id: str,
) -> dict[str, Any]:
    """Rebuild the exact facts-derived route used by released Runtime/S0.

    The three inputs are intentionally separate persisted artifacts.  Runtime
    acceptance depends on their raw normalized bytes and on an exact closure
    recompile; a self-consistent offline audit or re-sealed mutation therefore
    cannot become Release authority.
    """

    facts_evidence = _normalized_json_object(
        project_route_facts_raw, evidence_kind="ProjectRouteFacts"
    )
    if set(facts_evidence) != {
        "facts_source",
        "project_route_facts",
        "project_route_facts_sha256",
    }:
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_FACTS",
            "ProjectRouteFacts evidence fields differ",
        )
    facts_source = facts_evidence.get("facts_source")
    facts = facts_evidence.get("project_route_facts")
    if not isinstance(facts_source, dict) or not isinstance(facts, dict):
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_FACTS",
            "facts source and ProjectRouteFacts must be objects",
        )
    facts_sha256 = canonical_json_digest(facts)
    if (
        facts_evidence.get("project_route_facts_sha256") != facts_sha256
        or facts.get("facts_source_sha256") != canonical_json_digest(facts_source)
    ):
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_FACTS_DIGEST",
            "ProjectRouteFacts or its source digest differs",
        )

    derived = _normalized_json_object(
        derived_route_receipt_raw, evidence_kind="DerivedRouteReceipt"
    )
    route_id, derived_route_sha256 = _validate_derived_route_receipt(
        generation, derived
    )
    if (
        derived.get("facts") != facts
        or derived.get("facts_sha256") != facts_sha256
        or derived.get("facts_source_sha256") != facts.get("facts_source_sha256")
    ):
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_FACTS_BINDING",
            "DerivedRouteReceipt does not bind the persisted ProjectRouteFacts",
        )
    if (
        expected_stage not in {"candidate", "released"}
        or expected_workflow_phase
        not in {"discussion", "development", "release_readiness", "release"}
        or expected_project_size
        not in {"discussion", "small", "medium", "large"}
        or (expected_stage == "released" and expected_workflow_phase != "release")
        or (expected_stage == "released" and expected_project_size == "discussion")
        or derived.get("stage") != expected_stage
        or derived.get("workflow_phase") != expected_workflow_phase
        or derived.get("project_size") != expected_project_size
        or route_id != expected_route_id
    ):
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_IDENTITY",
            "released route stage, phase, project size, or route id differs",
        )

    closure = _normalized_json_object(
        route_closure_raw, evidence_kind="RouteClosure"
    )
    if (
        closure.get("generation_id") != generation.get("generation_id")
        or closure.get("route_id") != expected_route_id
        or closure.get("route_selection_mode") != "facts_derived"
        or closure.get("derived_route_sha256") != derived_route_sha256
        or closure.get("closure_digest")
        != canonical_json_digest(
            {key: value for key, value in closure.items() if key != "closure_digest"}
        )
    ):
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_CLOSURE",
            "runtime requires a digest-valid facts-derived route closure",
        )
    rebuilt = compile_derived_route_closure(repo_root, generation, derived)
    if closure != rebuilt:
        raise RouteClosureError(
            "E_V263_RUNTIME_ROUTE_RECOMPILE",
            "route closure differs from the exact facts-derived recompile",
        )
    return {
        "project_route_facts": facts,
        "project_route_facts_sha256": facts_sha256,
        "derived_route_receipt": derived,
        "derived_route_sha256": derived_route_sha256,
        "route_closure": closure,
        "route_selection_mode": "facts_derived",
        "route_id": route_id,
    }


__all__ = [
    "RouteClosureError",
    "compile_derived_route_closure",
    "compile_route_closure",
    "validate_declared_route_closure",
    "validate_released_runtime_route_triplet",
]
