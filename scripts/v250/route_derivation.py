"""Derive V2.63 Goal Teams routes from trusted facts.

The caller supplies facts, never a final route.  Project size and assurance are
kept orthogonal: a high-risk Small task remains Small, but cannot use Lite
assurance.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.v250.generation_runtime import canonical_json_digest


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ASSURANCE_RANK = {"lite": 0, "standard": 1, "high": 2, "critical": 3}
FACT_FIELDS = frozenset(
    {
        "project_size",
        "workflow_phase",
        "stage",
        "release_intent",
        "implementation_scope_complete",
        "risk",
        "failure_consequence",
        "reversibility",
        "compliance",
        "external_write",
        "security_sensitive",
        "ui_or_desktop",
        "agent_runtime",
        "environment_check_required",
        "authorization_state",
        "facts_source_sha256",
    }
)


class RouteDerivationError(ValueError):
    """Stable fail-closed error raised by the V2.63 route derivation contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise RouteDerivationError(code, message)


def _require_boolean(facts: Mapping[str, Any], field: str) -> bool:
    value = facts.get(field)
    if not isinstance(value, bool):
        _fail("E_V263_ROUTE_FACTS", f"{field} must be boolean")
    return value


def _require_enum(
    facts: Mapping[str, Any], field: str, choices: frozenset[str]
) -> str:
    value = facts.get(field)
    if not isinstance(value, str) or value not in choices:
        _fail("E_V263_ROUTE_FACTS", f"invalid {field}")
    return value


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def derive_route(
    facts: Mapping[str, Any], *, requested_assurance: str | None = None
) -> dict[str, Any]:
    """Return a digest-bound route receipt derived only from validated facts."""

    if not isinstance(facts, Mapping):
        _fail("E_V263_ROUTE_FACTS", "facts must be an object")
    if "route_id" in facts or "derived_route" in facts:
        _fail(
            "E_V263_ROUTE_CALLER_SELECTED",
            "the caller cannot supply a final route",
        )
    unknown = sorted(set(facts) - FACT_FIELDS)
    missing = sorted(FACT_FIELDS - set(facts))
    if unknown or missing:
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unknown:
            detail.append("unknown=" + ",".join(unknown))
        _fail("E_V263_ROUTE_FACTS", "; ".join(detail))

    size = _require_enum(
        facts, "project_size", frozenset({"discussion", "small", "medium", "large"})
    )
    phase = _require_enum(
        facts,
        "workflow_phase",
        frozenset({"discussion", "development", "release_readiness", "release"}),
    )
    stage = _require_enum(facts, "stage", frozenset({"candidate", "released"}))
    release_intent = _require_boolean(facts, "release_intent")
    implementation_complete = _require_boolean(
        facts, "implementation_scope_complete"
    )
    risk = _require_enum(
        facts, "risk", frozenset({"low", "medium", "high", "critical"})
    )
    consequence = _require_enum(
        facts,
        "failure_consequence",
        frozenset({"low", "medium", "high", "critical"}),
    )
    reversibility = _require_enum(
        facts,
        "reversibility",
        frozenset({"reversible", "partially_reversible", "irreversible"}),
    )
    compliance = _require_enum(
        facts, "compliance", frozenset({"none", "standard", "regulated"})
    )
    external_write = _require_boolean(facts, "external_write")
    security_sensitive = _require_boolean(facts, "security_sensitive")
    ui_or_desktop = _require_boolean(facts, "ui_or_desktop")
    agent_runtime = _require_boolean(facts, "agent_runtime")
    environment_check_required = _require_boolean(
        facts, "environment_check_required"
    )
    authorization_state = _require_enum(
        facts,
        "authorization_state",
        frozenset({"not_required", "granted", "missing", "expired", "denied"}),
    )
    facts_source_sha256 = facts.get("facts_source_sha256")
    if not isinstance(facts_source_sha256, str) or SHA256_RE.fullmatch(
        facts_source_sha256
    ) is None:
        _fail("E_V263_ROUTE_FACTS", "facts_source_sha256 must be lowercase SHA-256")

    if size == "discussion" and phase != "discussion":
        _fail("E_V263_ROUTE_FACTS", "discussion size requires discussion phase")
    if phase == "discussion" and size != "discussion":
        _fail("E_V263_ROUTE_FACTS", "discussion phase requires discussion size")
    if phase == "discussion":
        discussion_conflicts = {
            "release_intent": release_intent,
            "implementation_scope_complete": implementation_complete,
            "external_write": external_write,
            "ui_or_desktop": ui_or_desktop,
            "agent_runtime": agent_runtime,
            "environment_check_required": environment_check_required,
            "authorization_state": authorization_state != "not_required",
        }
        conflicting_fields = sorted(
            field for field, conflicts in discussion_conflicts.items() if conflicts
        )
        if conflicting_fields:
            _fail(
                "E_V263_ROUTE_DISCUSSION_CONFLICT",
                "discussion cannot carry execution or release facts: "
                + ", ".join(conflicting_fields),
            )
    if phase in {"release_readiness", "release"}:
        if not release_intent:
            _fail("E_V263_ROUTE_RELEASE_INTENT", "release phase requires release intent")
        if not implementation_complete:
            _fail(
                "E_V263_ROUTE_RELEASE_INCOMPLETE",
                "release routing requires complete implementation scope",
            )
    if external_write and authorization_state != "granted":
        _fail(
            "E_V263_ROUTE_AUTHORIZATION",
            "external write requires granted project-start authorization",
        )
    if not external_write and authorization_state not in {"not_required", "granted"}:
        _fail(
            "E_V263_ROUTE_AUTHORIZATION",
            "authorization state is invalid for a non-external-write route",
        )

    assurance_rank = ASSURANCE_RANK["lite" if size in {"discussion", "small"} else "standard"]
    if risk in {"high", "critical"} or consequence in {"high", "critical"}:
        assurance_rank = max(assurance_rank, ASSURANCE_RANK["high"])
    if (
        security_sensitive
        or compliance == "regulated"
        or reversibility == "irreversible"
        or external_write
        or phase in {"release_readiness", "release"}
    ):
        assurance_rank = max(assurance_rank, ASSURANCE_RANK["high"])
    if risk == "critical" or consequence == "critical":
        assurance_rank = ASSURANCE_RANK["critical"]
    assurance_floor = next(
        name for name, rank in ASSURANCE_RANK.items() if rank == assurance_rank
    )

    if requested_assurance is not None:
        if requested_assurance not in ASSURANCE_RANK:
            _fail("E_V263_ROUTE_ASSURANCE", "unknown requested assurance")
        if ASSURANCE_RANK[requested_assurance] < assurance_rank:
            _fail(
                "E_V263_ROUTE_ASSURANCE_DOWNGRADE",
                f"{requested_assurance} is below derived floor {assurance_floor}",
            )
        effective_assurance = requested_assurance
    else:
        effective_assurance = assurance_floor

    gates: list[str] = []
    conditional_gates: list[str] = []
    exclusions: list[str] = []
    if phase == "discussion":
        route_id = "V250-ROUTE-DISCUSSION"
        exclusions.extend(["execution_not_requested", "release_not_requested"])
    elif phase == "development":
        if ui_or_desktop:
            route_id = "V250-ROUTE-UI-DESKTOP"
        elif agent_runtime:
            route_id = "V250-ROUTE-AGENT-RUNTIME"
        else:
            route_id = f"V250-ROUTE-{size.upper()}-DEVELOPMENT"
        gates.extend(["loop_bootstrap", "environment_preflight"])
        if size in {"medium", "large"} or ui_or_desktop or agent_runtime:
            gates.append("development_environment_check")
        gates.extend(["tdd", "incremental"])
        if agent_runtime or ui_or_desktop:
            gates.append("runtime_capability")
        if ui_or_desktop:
            gates.append("ui_e2e")

        # Start with the exact route-manifest conditional vocabulary. Facts may
        # promote one of these gates to required, but cannot invent a new gate.
        if ui_or_desktop:
            conditional_gates.extend(
                [
                    "pixel_comparison",
                    "desktop_runtime",
                    "completion_audit",
                    "project_start_authorization",
                ]
            )
        elif agent_runtime:
            conditional_gates.extend(
                [
                    "fresh_runtime_transition",
                    "completion_audit",
                    "project_start_authorization",
                ]
            )
        elif size == "small":
            conditional_gates.extend(
                [
                    "development_environment_check",
                    "project_start_authorization",
                    "independent_review",
                ]
            )
        elif size == "medium":
            conditional_gates.extend(
                [
                    "semantic_review",
                    "behavior_review",
                    "project_start_authorization",
                ]
            )
        else:
            conditional_gates.extend(
                [
                    "semantic_review",
                    "behavior_review",
                    "completion_audit",
                    "project_start_authorization",
                ]
            )

        def promote(gate: str) -> None:
            if gate in conditional_gates:
                conditional_gates.remove(gate)
                gates.append(gate)

        if environment_check_required:
            promote("development_environment_check")
        if external_write:
            promote("project_start_authorization")
        if assurance_rank >= ASSURANCE_RANK["high"]:
            if size == "small" and not ui_or_desktop and not agent_runtime:
                promote("independent_review")
            elif ui_or_desktop or agent_runtime or size == "large":
                promote("completion_audit")
            else:
                promote("semantic_review")
                promote("behavior_review")

        # Release intent affects later route eligibility, never the Development
        # gate set. Full/security gates are dispatched only by a Release route.
        exclusions.append(
            "release_gates_deferred" if release_intent else "release_gates_not_required"
        )
    else:
        route_id = (
            "V250-ROUTE-LARGE-RELEASE"
            if size == "large"
            else "V250-ROUTE-MEDIUM-RELEASE"
        )
        gates.extend(
            [
                "loop_bootstrap",
                "environment_preflight",
                "development_environment_check",
            ]
        )
        gates.extend(
            [
                "fresh_runtime_transition",
                "s0",
                "full_regression",
                "release_security_review",
                "s2",
                "repository_boundary_compliance",
            ]
        )
        if size == "large":
            gates.append("s3")
        else:
            exclusions.append("s3_large_release_only")
        gates.append("s4")
        conditional_gates.append("project_start_authorization")
        if external_write:
            conditional_gates.remove("project_start_authorization")
            gates.append("project_start_authorization")

    normalized_facts = {field: facts[field] for field in sorted(FACT_FIELDS)}
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-derived-route-receipt-v2.63",
        "derivation_version": "V2.63",
        "facts": normalized_facts,
        "facts_sha256": canonical_json_digest(normalized_facts),
        "facts_source_sha256": facts_source_sha256,
        "project_size": size,
        "workflow_phase": phase,
        "stage": stage,
        "route_id": route_id,
        "assurance_floor": assurance_floor,
        "effective_assurance": effective_assurance,
        "required_gates": gates,
        "conditional_gates": conditional_gates,
        "exclusion_reasons": exclusions,
    }
    receipt["receipt_sha256"] = canonical_json_digest(receipt)
    return receipt


__all__ = ["RouteDerivationError", "derive_route"]
