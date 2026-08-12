"""Compile V2.63 control vocabulary and typed Owner dependency closure."""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping, Sequence

from scripts.v250.control_registry import ControlRegistryError, resolve_control_term
from scripts.v250.generation_runtime import canonical_json_digest


DEPENDENCY_KINDS = frozenset(
    {"required", "optional", "phase_gated", "fact_gated"}
)


class SemanticClosureError(ValueError):
    """Owner or control closure is ambiguous or incomplete."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise SemanticClosureError(code, message)


def _strings(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        _fail("E_V263_SEMANTIC_SHAPE", f"{field} must be a unique string array")
    return list(value)


def _normalized_owners(
    owners: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    if not isinstance(owners, list) or not owners:
        _fail("E_V263_OWNER_SHAPE", "owners must be a non-empty array")
    by_id: dict[str, dict[str, Any]] = {}
    id_by_path: dict[str, str] = {}
    for raw in owners:
        if not isinstance(raw, Mapping):
            _fail("E_V263_OWNER_SHAPE", "owner must be an object")
        owner_id = raw.get("owner_id")
        path = raw.get("path")
        if not isinstance(owner_id, str) or not owner_id:
            _fail("E_V263_OWNER_SHAPE", "owner_id is required")
        if not isinstance(path, str) or not path:
            _fail("E_V263_OWNER_SHAPE", f"owner path is required: {owner_id}")
        if owner_id in by_id or path in id_by_path:
            _fail("E_V263_OWNER_DUPLICATE", f"duplicate owner identity: {owner_id}")
        dependencies = raw.get("dependencies")
        if not isinstance(dependencies, list):
            _fail("E_V263_OWNER_SHAPE", f"dependencies must be an array: {owner_id}")
        normalized_dependencies: list[dict[str, Any]] = []
        seen_dependencies: set[tuple[str, str]] = set()
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                _fail("E_V263_DEPENDENCY_SHAPE", f"invalid dependency: {owner_id}")
            kind = dependency.get("kind")
            target = dependency.get("owner_id")
            if kind not in DEPENDENCY_KINDS:
                _fail("E_V263_DEPENDENCY_KIND", f"unknown dependency kind: {kind!r}")
            if not isinstance(target, str) or not target:
                _fail("E_V263_DEPENDENCY_SHAPE", f"dependency target is missing: {owner_id}")
            identity = (str(kind), target)
            if identity in seen_dependencies:
                _fail("E_V263_DEPENDENCY_DUPLICATE", f"duplicate dependency: {owner_id}->{target}")
            seen_dependencies.add(identity)
            expected_fields = {"kind", "owner_id"}
            item: dict[str, Any] = {"kind": kind, "owner_id": target}
            if kind == "phase_gated":
                expected_fields.add("phases")
                phases = _strings(
                    dependency.get("phases"),
                    "dependency.phases",
                    allow_empty=False,
                )
                try:
                    item["phases"] = [
                        resolve_control_term("phase", value) for value in phases
                    ]
                except ControlRegistryError as exc:
                    raise SemanticClosureError("E_V263_CONTROL_TERM", exc.message) from exc
            elif kind == "fact_gated":
                expected_fields.update({"fact", "equals"})
                fact = dependency.get("fact")
                if not isinstance(fact, str) or not fact:
                    _fail("E_V263_DEPENDENCY_SHAPE", "fact_gated dependency requires fact")
                item["fact"] = fact
                item["equals"] = dependency.get("equals")
            if set(dependency) != expected_fields:
                _fail("E_V263_DEPENDENCY_SHAPE", f"dependency fields differ: {owner_id}->{target}")
            normalized_dependencies.append(item)
        by_id[owner_id] = {
            "owner_id": owner_id,
            "path": path,
            "dependencies": normalized_dependencies,
            "route_membership": _strings(
                raw.get("route_membership"), f"route_membership:{owner_id}"
            ),
        }
        id_by_path[path] = owner_id
    for owner in by_id.values():
        for dependency in owner["dependencies"]:
            if dependency["owner_id"] not in by_id:
                _fail(
                    "E_V263_DEPENDENCY_UNKNOWN",
                    f"unknown dependency: {owner['owner_id']}->{dependency['owner_id']}",
                )
    return by_id, id_by_path


def _dependency_is_active(
    dependency: Mapping[str, Any], *, phase: str, facts: Mapping[str, Any]
) -> bool:
    kind = dependency["kind"]
    if kind == "required":
        return True
    if kind == "optional":
        return False
    if kind == "phase_gated":
        return phase in dependency["phases"]
    return facts.get(dependency["fact"]) == dependency["equals"]


def compile_owner_closure(
    *,
    owners: Any,
    route_id: str,
    phase: str,
    facts: Mapping[str, Any],
    ordered_refs: Sequence[str],
) -> dict[str, Any]:
    """Validate exact route membership and all active typed dependencies."""

    if not isinstance(route_id, str) or not route_id:
        _fail("E_V263_ROUTE_ID", "route_id is required")
    try:
        normalized_phase = resolve_control_term("phase", phase)
    except ControlRegistryError as exc:
        raise SemanticClosureError("E_V263_CONTROL_TERM", exc.message) from exc
    if not isinstance(facts, Mapping):
        _fail("E_V263_FACTS", "facts must be an object")
    if (
        not isinstance(ordered_refs, Sequence)
        or isinstance(ordered_refs, (str, bytes))
        or not ordered_refs
        or not all(isinstance(item, str) and item for item in ordered_refs)
    ):
        _fail("E_V263_ORDERED_REFS", "ordered_refs must be a non-empty string array")
    refs = list(ordered_refs)
    if len(refs) != len(set(refs)):
        _fail("E_V263_ORDERED_REF_DUPLICATE", "ordered_refs contains duplicates")

    by_id, id_by_path = _normalized_owners(owners)
    unknown_paths = [path for path in refs if path not in id_by_path]
    if unknown_paths:
        _fail("E_V263_ROUTE_WITHOUT_OWNER", "unknown route refs: " + ", ".join(unknown_paths))
    selected_ids = [id_by_path[path] for path in refs]
    selected = set(selected_ids)

    queue = deque(selected_ids)
    visited: set[str] = set()
    while queue:
        owner_id = queue.popleft()
        if owner_id in visited:
            continue
        visited.add(owner_id)
        for dependency in by_id[owner_id]["dependencies"]:
            if not _dependency_is_active(
                dependency, phase=normalized_phase, facts=facts
            ):
                continue
            target = dependency["owner_id"]
            if target not in selected:
                code = {
                    "required": "E_V263_REQUIRED_DEPENDENCY",
                    "phase_gated": "E_V263_PHASE_DEPENDENCY",
                    "fact_gated": "E_V263_FACT_DEPENDENCY",
                }[dependency["kind"]]
                _fail(code, f"active dependency is absent: {owner_id}->{target}")
            queue.append(target)

    declared_members = {
        owner_id
        for owner_id, owner in by_id.items()
        if route_id in owner["route_membership"]
    }
    if declared_members != selected:
        _fail(
            "E_V263_ROUTE_MEMBERSHIP",
            "route and Owner membership differ; missing="
            + ",".join(sorted(declared_members - selected))
            + "; undeclared="
            + ",".join(sorted(selected - declared_members)),
        )

    result: dict[str, Any] = {
        "schema_version": "goal-teams-owner-closure-v2.63",
        "route_id": route_id,
        "phase": normalized_phase,
        "ordered_refs": refs,
        "ordered_owner_ids": selected_ids,
        "membership_check": "full",
        "dependency_kinds": sorted(DEPENDENCY_KINDS),
    }
    result["closure_sha256"] = canonical_json_digest(result)
    return result


def validate_route_controls(route: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one route's phase and gate vocabulary without silent aliases."""

    if not isinstance(route, Mapping):
        _fail("E_V263_ROUTE_CONTROL", "route must be an object")
    try:
        phase = resolve_control_term("phase", route.get("workflow_phase"))
    except ControlRegistryError as exc:
        raise SemanticClosureError("E_V263_CONTROL_TERM", exc.message) from exc
    result: dict[str, Any] = {"workflow_phase": phase}
    for field in ("required_gates", "conditional_gates"):
        values = _strings(route.get(field), field)
        try:
            normalized = [resolve_control_term("gate", value) for value in values]
        except ControlRegistryError as exc:
            raise SemanticClosureError("E_V263_CONTROL_TERM", exc.message) from exc
        if len(normalized) != len(set(normalized)):
            _fail("E_V263_CONTROL_ALIAS_COLLISION", f"{field} aliases collide")
        result[field] = normalized
    result["controls_sha256"] = canonical_json_digest(result)
    return result


__all__ = [
    "SemanticClosureError",
    "compile_owner_closure",
    "validate_route_controls",
]
