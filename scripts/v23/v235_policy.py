#!/usr/bin/env python3
"""Deterministic V2.35 routing, specialist, test and release policies.

This module is intentionally side-effect free.  It validates structured facts
and returns stable result objects; it never dispatches work, executes a command,
opens a network connection, or mutates a repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


PROJECT_ROUTE_SCHEMA = "goal-teams-project-route-v2.35"
TEST_CASE_SCHEMA = "goal-teams-test-case-v2.35"
SPECIALIST_ROLES = ("security", "performance", "refactor", "sqa")
PROJECT_SIZES = frozenset({"large", "medium", "small"})
WORK_TYPES = frozenset({"feature", "bugfix"})
RISKS = frozenset({"low", "medium", "high", "critical"})
TEST_KINDS = frozenset({"unit", "tdd", "integration", "e2e", "cli", "api", "fixture"})
PROCESSING_KINDS = frozenset({"call", "command", "http", "browser", "fixture_load"})
ALLOWED_COMPARATORS = (
    "equals",
    "not_equals",
    "contains",
    "member_of",
    "less_than",
    "less_than_or_equal",
    "greater_than",
    "greater_than_or_equal",
    "json_subset",
    "sequence_equals",
    "sha256_equals",
    "exit_code_equals",
    "status_code_equals",
)
_COMPARATOR_SET = frozenset(ALLOWED_COMPARATORS)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_REF_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_ROUTE_REQUIRED = (
    "schema_version",
    "project_size",
    "work_type",
    "release",
    "ui",
    "backend",
    "api",
    "cli",
    "tests",
    "risk",
    "security_sensitive",
    "external_write",
    "auth",
    "payment",
    "migration",
    "destructive",
    "specialist_requests",
)
_ROUTE_FIELDS = frozenset(_ROUTE_REQUIRED)
_ROUTE_BOOLEANS = (
    "release",
    "ui",
    "backend",
    "api",
    "cli",
    "tests",
    "security_sensitive",
    "external_write",
    "auth",
    "payment",
    "migration",
    "destructive",
)
_SECURITY_OVERRIDE_FIELDS = (
    "security_sensitive",
    "external_write",
    "auth",
    "payment",
    "migration",
    "destructive",
)
_TEST_CASE_REQUIRED = frozenset(
    {
        "schema_version",
        "case_id",
        "test_kind",
        "acceptance_refs",
        "test_file_refs",
        "input",
        "processing",
        "expected_output",
        "assertions",
    }
)
_TEST_CASE_FIELDS = _TEST_CASE_REQUIRED | {"tdd"}
_PROCESS_PARTS = frozenset(
    {
        ".git",
        ".goalteams-state",
        ".goalteams-quarantine",
        "ledger",
        "evidence",
        "audit",
        "reviews",
        "harness",
        "identity",
        "provenance",
        "secrets",
        "credentials",
    }
)
_ROADMAP_BASENAME = "后续版本规划 V3.3-3.5.md"
_EXPECTED_SPECIALISTS = {
    "security": {
        "agent_type": "goal_security",
        "capabilities": frozenset({"security_assessment", "security_proposal"}),
    },
    "performance": {
        "agent_type": "goal_performance",
        "capabilities": frozenset({"performance_benchmark", "performance_proposal"}),
    },
    "refactor": {
        "agent_type": "goal_refactor",
        "capabilities": frozenset({"refactor_equivalence", "refactor_proposal"}),
    },
    "sqa": {
        "agent_type": "goal_sqa",
        "capabilities": frozenset({"sqa_process_review", "sqa_archive_proposal"}),
    },
}


class DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key at the parse boundary."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(key)
        value[key] = item
    return value


def strict_json_loads(text: str) -> Any:
    """Parse JSON while rejecting duplicate object keys."""

    return json.loads(text, object_pairs_hook=_unique_object)


def _ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, "error_code": None, "mutation_count": 0, **data}


def _reject(code: str, **data: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": code,
        "errors": [code],
        "mutation_count": 0,
        **data,
    }


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any, *, nonempty: bool = True) -> bool:
    return bool(
        isinstance(value, list)
        and (value or not nonempty)
        and all(_nonempty(item) for item in value)
    )


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def is_v235_route(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    schema = value.get("schema_version")
    return bool(
        (isinstance(schema, str) and schema.startswith("goal-teams-project-route-"))
        or "project_size" in value
        or "work_type" in value
    )


def normalize_project_route(request: Any) -> dict[str, Any]:
    """Validate and reduce the orthogonal V2.35 project route."""

    if not isinstance(request, dict):
        return _reject("E_V235_ROUTE_TYPE")
    missing = sorted(_ROUTE_FIELDS - set(request))
    if missing:
        return _reject("E_V235_ROUTE_REQUIRED", missing_fields=missing)
    unknown = sorted(set(request) - _ROUTE_FIELDS)
    if unknown:
        return _reject("E_V235_ROUTE_UNKNOWN_FIELD", unknown_fields=unknown)
    if isinstance(request.get("project_size"), list):
        return _reject(
            "E_V235_ROUTE_CONFLICT"
            if len(request["project_size"]) > 1
            else "E_V235_ROUTE_TYPE"
        )
    scalar_fields = ("schema_version", "project_size", "work_type", "risk")
    if any(not isinstance(request.get(field), str) for field in scalar_fields):
        return _reject("E_V235_ROUTE_TYPE")
    if any(type(request.get(field)) is not bool for field in _ROUTE_BOOLEANS):
        return _reject("E_V235_ROUTE_TYPE")
    specialists_requested = request.get("specialist_requests")
    if not isinstance(specialists_requested, list) or any(
        not isinstance(item, str) for item in specialists_requested
    ):
        return _reject("E_V235_ROUTE_TYPE")
    if request["schema_version"] != PROJECT_ROUTE_SCHEMA:
        return _reject("E_V235_ROUTE_SCHEMA")
    if request["project_size"] not in PROJECT_SIZES:
        return _reject("E_V235_PROJECT_SIZE")
    if request["work_type"] not in WORK_TYPES:
        return _reject("E_V235_WORK_TYPE")
    if request["risk"] not in RISKS:
        return _reject("E_V235_RISK")
    if (
        any(item not in SPECIALIST_ROLES for item in specialists_requested)
        or len(specialists_requested) != len(set(specialists_requested))
    ):
        return _reject("E_V235_SPECIALIST_REQUEST")

    project_size = request["project_size"]
    work_type = request["work_type"]
    gates = {
        "architecture": "required",
        "environment": "required",
        "independent_tests": "required",
        "evidence": "required",
    }
    specialists = {role: "not_loaded" for role in SPECIALIST_ROLES}
    reasons: list[str] = []

    if project_size == "large":
        gates["tdd"] = "required"
        gates["integration"] = "required"
        gates["full_regression"] = "required"
        reasons.append("V235_LARGE_DEFAULT")
        if request["release"] and work_type == "feature":
            specialists = {role: "required" for role in SPECIALIST_ROLES}
            reasons.append("V235_LARGE_RELEASE")
    elif project_size == "medium":
        reasons.append("V235_MEDIUM_DEFAULT")
    else:
        reasons.append("V235_SMALL_SHORT_REQUIREMENTS")

    if work_type == "bugfix":
        gates["tdd"] = "required"
        gates["integration"] = "required"
        reasons.append("V235_BUGFIX_TDD_INTEGRATION")
    if request["ui"]:
        gates["e2e"] = "required"
        reasons.append("V235_UI_E2E_OVERRIDE")
    if request["release"]:
        gates["release_evidence"] = "required"

    security_override = bool(
        request["risk"] in {"high", "critical"}
        or any(request[field] for field in _SECURITY_OVERRIDE_FIELDS)
    )
    if security_override:
        specialists["security"] = "required"
        reasons.append("V235_SECURITY_OVERRIDE")
    if specialists_requested:
        for role in specialists_requested:
            specialists[role] = "required"
        reasons.append("V235_EXPLICIT_SPECIALIST_REQUEST")

    refs = {
        "RULES.md",
        "references/invariants.md",
        "references/compat.md",
        "references/rules-project-sizing.md",
        "references/rules-testing.md",
        "references/test-case-assertion-protocol.md",
    }
    if request["ui"]:
        refs.add("references/rules-ui.md")
    if any(value == "required" for value in specialists.values()):
        refs.add("references/rules-specialists.md")
    if security_override:
        refs.add("references/dual-review-protocol.md")

    return _ok(
        schema_version=PROJECT_ROUTE_SCHEMA,
        project_size=project_size,
        work_type=work_type,
        profile="regulated" if security_override else ("full" if project_size == "large" else "standard"),
        required_review_class="safety" if security_override else "semantic",
        gates=gates,
        specialists=specialists,
        rule_set=sorted(refs),
        reason_codes=sorted(set(reasons)),
        blocked=False,
        mode="execute",
        writes_created=None,
    )


def validate_specialist_capability_registry(registry: Any) -> dict[str, Any]:
    if not isinstance(registry, dict) or registry.get("schema_version") != "goal-teams-specialist-capability-registry-v2.35":
        return _reject("E_V235_SPECIALIST_CAPABILITY")
    identities = registry.get("identities")
    if (
        not isinstance(identities, list)
        or any(not isinstance(item, dict) for item in identities)
        or any(
            not _nonempty(item.get(field))
            for item in identities
            for field in ("agent_run_id", "member_id", "display_name", "transport_handle")
        )
    ):
        return _reject("E_V235_SPECIALIST_CAPABILITY")
    for field in ("agent_run_id", "member_id", "display_name", "transport_handle"):
        values = [item[field] for item in identities]
        if len(values) != len(set(values)):
            return _reject("E_V235_SPECIALIST_IDENTITY_DUPLICATE")
    by_role = {
        item.get("role"): item
        for item in identities
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    if set(by_role) != set(SPECIALIST_ROLES) or len(identities) != len(SPECIALIST_ROLES):
        return _reject("E_V235_SPECIALIST_CAPABILITY")
    for role, expected in _EXPECTED_SPECIALISTS.items():
        item = by_role[role]
        capabilities = item.get("capabilities")
        if (
            item.get("agent_type") != expected["agent_type"]
            or not _string_list(capabilities)
            or len(capabilities) != len(set(capabilities))
            or frozenset(capabilities) != expected["capabilities"]
        ):
            return _reject("E_V235_SPECIALIST_CAPABILITY")
        if (
            item.get("sandbox_mode") != "read-only"
            or item.get("coordination_depth") != 1
            or item.get("can_spawn_subagents") is not False
            or item.get("can_dispatch") is not False
            or item.get("dispatch_owner_agent_type") != "goal_lead"
            or item.get("handoff_mode") != "proposal_only"
        ):
            return _reject("E_V235_SPECIALIST_PERMISSION")
    return _ok(validated_roles=list(SPECIALIST_ROLES))


def validate_specialist_action(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _reject("E_V235_SPECIALIST_ACTION_FORBIDDEN")
    if (
        request.get("role") not in SPECIALIST_ROLES
        or not _nonempty(request.get("specialist_run_id"))
        or request.get("action") != "submit_proposal"
        or request.get("target") != "goal_lead"
        or request.get("mutation_count", 0) != 0
    ):
        return _reject("E_V235_SPECIALIST_ACTION_FORBIDDEN")
    return _ok(handoff_mode="proposal_only", target="goal_lead")


def _valid_command(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and isinstance(value.get("argv"), list)
        and value["argv"]
        and all(_nonempty(item) for item in value["argv"])
        and _nonempty(value.get("cwd"))
    )


def validate_specialist_proposal(proposal: Any) -> dict[str, Any]:
    if not isinstance(proposal, dict) or proposal.get("schema_version") != "goal-teams-specialist-proposal-v2.35":
        return _reject("E_V235_SPECIALIST_CAPABILITY")
    role = proposal.get("role")
    if role not in SPECIALIST_ROLES or not all(
        _nonempty(proposal.get(field)) for field in ("proposal_id", "specialist_run_id")
    ):
        return _reject("E_V235_SPECIALIST_CAPABILITY")
    priority_level = proposal.get("priority_level")
    if (
        proposal.get("lifecycle_state") != "proposed"
        or not isinstance(priority_level, str)
        or priority_level not in {"L0", "L1", "L2"}
    ):
        return _reject("E_V235_SPECIALIST_PRIORITY")
    relaxes = proposal.get("relaxes")
    if not isinstance(relaxes, list) or any(not isinstance(item, str) for item in relaxes):
        return _reject("E_V235_SPECIALIST_PRIORITY")
    if proposal.get("priority_level") == "L2" and any(
        item.startswith("L0:") or item.startswith("L1:") for item in relaxes
    ):
        return _reject("E_V235_SPECIALIST_PRIORITY")
    if proposal.get("write_scope", []) not in ([], None):
        return _reject("E_V235_SPECIALIST_PERMISSION")

    if role == "security":
        coverage = proposal.get("coverage")
        if not _string_list(coverage) or not {
            "code", "dependencies", "secrets", "injection", "ports"
        } <= set(coverage):
            return _reject("E_V235_SECURITY_SCOPE")
        if proposal.get("required_review_class") != "safety":
            return _reject("E_V235_SECURITY_REVIEW_CLASS")
    elif role == "performance":
        benchmark = proposal.get("benchmark")
        evidence = proposal.get("benchmark_evidence")
        if (
            not isinstance(benchmark, dict)
            or not _valid_hash(benchmark.get("environment_digest"))
            or not _valid_hash(benchmark.get("candidate_digest"))
            or not isinstance(benchmark.get("data_scale"), dict)
            or not benchmark["data_scale"]
            or not _valid_command(benchmark.get("command"))
            or not isinstance(evidence, dict)
            or not _nonempty(evidence.get("evidence_id"))
        ):
            return _reject("E_V235_PERFORMANCE_BENCHMARK_REQUIRED")
        if (
            evidence.get("current") is not True
            or evidence.get("environment_digest") != benchmark.get("environment_digest")
            or evidence.get("candidate_digest") != benchmark.get("candidate_digest")
            or evidence.get("data_scale") != benchmark.get("data_scale")
        ):
            return _reject("E_V235_PERFORMANCE_EVIDENCE_STALE")
    elif role == "refactor":
        equivalence = proposal.get("equivalence_contract")
        if (
            not isinstance(equivalence, dict)
            or not _valid_hash(equivalence.get("public_behavior_sha256"))
            or not _string_list(equivalence.get("scope"))
        ):
            return _reject("E_V235_REFACTOR_EQUIVALENCE")
        for name in ("regression_evidence", "holdout_evidence"):
            evidence = proposal.get(name)
            if (
                not isinstance(evidence, dict)
                or not _nonempty(evidence.get("evidence_id"))
                or evidence.get("current") is not True
                or evidence.get("state") != "passed"
            ):
                return _reject("E_V235_REFACTOR_EVIDENCE")
        rollback = proposal.get("rollback_boundary")
        if (
            not isinstance(rollback, dict)
            or not _string_list(rollback.get("paths"))
            or not _string_list(rollback.get("command"))
        ):
            return _reject("E_V235_REFACTOR_ROLLBACK")
    else:
        release_version = proposal.get("release_version")
        version_record = proposal.get("version_record")
        classifications = proposal.get("classifications")
        if (
            release_version != "V2.35"
            or not isinstance(version_record, dict)
            or version_record.get("version") != release_version
            or not _string_list(version_record.get("change_ids"))
            or not _nonempty(proposal.get("index_ref"))
            or not _string_list(classifications)
            or not {"release", "process", "quality"} <= set(classifications)
            or proposal.get("version_directory") != "docs/archive/V2.35"
        ):
            return _reject("E_V235_SQA_ARCHIVE_CONTRACT")
        public = proposal.get("public_copy")
        if (
            not isinstance(public, dict)
            or public.get("sanitized") is not True
            or public.get("secret_count") != 0
            or public.get("absolute_home_path_count") != 0
        ):
            return _reject("E_V235_SQA_PUBLIC_SANITIZATION")
        provenance = proposal.get("private_provenance")
        if (
            not isinstance(provenance, dict)
            or provenance.get("retained") is not True
            or not _nonempty(provenance.get("ref"))
            or not _valid_hash(provenance.get("sha256"))
        ):
            return _reject("E_V235_SQA_PROVENANCE")
    return _ok(role=role, proposal_id=proposal["proposal_id"], handoff_mode="proposal_only")


def validate_specialist_improvement_lifecycle(records: Any) -> dict[str, Any]:
    if not isinstance(records, list) or not records or any(not isinstance(item, dict) for item in records):
        return _reject("E_V235_SPECIALIST_LIFECYCLE")
    states = [item.get("state") for item in records]
    if states not in (["proposed", "reviewed", "applied", "verified"], ["proposed", "reviewed", "applied", "reverted"]):
        return _reject("E_V235_SPECIALIST_LIFECYCLE")
    actors = [item.get("actor_run_id") for item in records]
    if any(not _nonempty(item) for item in actors) or len(actors) != len(set(actors)):
        return _reject("E_V235_SPECIALIST_LIFECYCLE")
    if states[-1] == "verified":
        final = records[-1]
        if (
            not _nonempty(final.get("regression_evidence_id"))
            or not _nonempty(final.get("holdout_evidence_id"))
            or final.get("regression_evidence_id") == final.get("holdout_evidence_id")
            or actors[-1] == actors[-2]
        ):
            return _reject("E_V235_SPECIALIST_LIFECYCLE")
    return _ok(final_state=states[-1])


def evaluate_port_scan_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _reject("E_V235_EXTERNAL_PORT_SCAN_AUTH_REQUIRED", blocked=True, stop_reason="authorization_required", command=None)
    target_scope = request.get("target_scope")
    scan_mode = request.get("scan_mode")
    target = request.get("target")
    active_or_external = target_scope == "external" or scan_mode == "active"
    authorized = bool(
        request.get("fresh_exact_authorization") is True
        and _nonempty(target)
        and request.get("authorization_target") == target
    )
    if active_or_external and not authorized:
        return _reject(
            "E_V235_EXTERNAL_PORT_SCAN_AUTH_REQUIRED",
            blocked=True,
            stop_reason="authorization_required",
            command=None,
            executed=False,
        )
    if target_scope == "local" and scan_mode == "passive" and target == "localhost":
        return _ok(
            blocked=False,
            command=None,
            executed=False,
            record={
                "target": "localhost",
                "target_scope": "local",
                "scan_mode": "passive",
                "outbound_connections": 0,
            },
        )
    if active_or_external and authorized:
        return _ok(
            blocked=False,
            command=None,
            executed=False,
            handoff_mode="proposal_only",
            dispatch_request={
                "target": target,
                "target_scope": target_scope,
                "scan_mode": scan_mode,
                "required_review_class": "safety",
            },
        )
    return _reject("E_V235_EXTERNAL_PORT_SCAN_AUTH_REQUIRED", blocked=True, stop_reason="authorization_required", command=None)


def _ref_parts(value: Any, allowed_roots: Iterable[str]) -> tuple[str, ...] | None:
    if not isinstance(value, str) or not value or any(
        token in value for token in ("/", "\\", "..", "://", "$(", "`")
    ):
        return None
    parts = tuple(value.split("."))
    if len(parts) < 2 or parts[0] not in set(allowed_roots) or any(
        not _REF_SEGMENT.fullmatch(part) for part in parts
    ):
        return None
    return parts


def _resolve_ref(document: dict[str, Any], value: Any, allowed_roots: Iterable[str]) -> tuple[bool, Any]:
    parts = _ref_parts(value, allowed_roots)
    if parts is None:
        return False, None
    current: Any = document
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def validate_test_case_contract(case: Any) -> dict[str, Any]:
    if not isinstance(case, dict):
        return _reject("E_V235_TEST_CASE_REQUIRED")
    unknown = sorted(set(case) - _TEST_CASE_FIELDS)
    if unknown:
        return _reject("E_V235_TEST_CASE_UNKNOWN_FIELD", unknown_fields=unknown)
    missing = sorted(_TEST_CASE_REQUIRED - set(case))
    if missing:
        return _reject("E_V235_TEST_CASE_REQUIRED", missing_fields=missing)
    if (
        case.get("schema_version") != TEST_CASE_SCHEMA
        or not _nonempty(case.get("case_id"))
        or not isinstance(case.get("test_kind"), str)
        or case.get("test_kind") not in TEST_KINDS
        or not _string_list(case.get("acceptance_refs"))
        or not _string_list(case.get("test_file_refs"))
    ):
        return _reject("E_V235_TEST_CASE_REQUIRED")
    if not isinstance(case.get("input"), dict) or not case["input"]:
        return _reject("E_V235_INPUT_EMPTY")
    processing = case.get("processing")
    if (
        not isinstance(processing, dict)
        or not processing
        or not isinstance(processing.get("kind"), str)
        or processing.get("kind") not in PROCESSING_KINDS
        or not _nonempty(processing.get("target"))
        or not _nonempty(processing.get("invocation_ref"))
        or not _resolve_ref(case, processing.get("invocation_ref"), {"input", "processing"})[0]
        or (processing.get("kind") == "command" and not _valid_command(processing.get("command")))
    ):
        return _reject("E_V235_PROCESSING_NOT_EXECUTABLE")
    expected = case.get("expected_output")
    if (
        not isinstance(expected, dict)
        or not expected
        or not isinstance(expected.get("value"), dict)
        or not expected["value"]
        or not _string_list(expected.get("observable_refs"))
    ):
        return _reject("E_V235_EXPECTED_OUTPUT_EMPTY")
    assertions = case.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        return _reject("E_V235_ASSERTIONS_EMPTY")
    preflight_comparators: list[str] = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            return _reject("E_V235_ASSERTION_ID")
        comparator = assertion.get("comparator")
        if not isinstance(comparator, str) or comparator not in _COMPARATOR_SET:
            return _reject("E_V235_COMPARATOR_UNKNOWN")
        preflight_comparators.append(comparator)
    if all(item == "exit_code_equals" for item in preflight_comparators):
        return _reject("E_V235_EXIT_CODE_ONLY")
    if all(item == "status_code_equals" for item in preflight_comparators):
        return _reject("E_V235_STATUS_CODE_ONLY")
    assertion_ids: set[str] = set()
    actual_refs: set[str] = set()
    comparators: list[str] = []
    observable_refs = set(expected["observable_refs"])
    for assertion in assertions:
        if not isinstance(assertion, dict) or not _nonempty(assertion.get("assertion_id")):
            return _reject("E_V235_ASSERTION_ID")
        assertion_id = assertion["assertion_id"]
        if assertion_id in assertion_ids:
            return _reject("E_V235_ASSERTION_ID")
        assertion_ids.add(assertion_id)
        comparator = assertion.get("comparator")
        if not isinstance(comparator, str) or comparator not in _COMPARATOR_SET:
            return _reject("E_V235_COMPARATOR_UNKNOWN")
        comparators.append(comparator)
        actual_ref = assertion.get("actual_ref")
        if _ref_parts(actual_ref, {"observed_output", "artifact", "execution"}) is None or actual_ref not in observable_refs:
            return _reject("E_V235_ASSERTION_REF")
        actual_refs.add(actual_ref)
        has_expected_ref = "expected_ref" in assertion
        has_expected_value = "expected_value" in assertion
        if has_expected_ref == has_expected_value:
            return _reject("E_V235_ASSERTION_REF")
        if has_expected_ref and not _resolve_ref(case, assertion.get("expected_ref"), {"expected_output"})[0]:
            return _reject("E_V235_ASSERTION_REF")
    if case["test_kind"] == "tdd":
        tdd = case.get("tdd")
        required = (
            "phase",
            "expected_initial_state",
            "test_sha256_ref",
            "preimplementation_tree_ref",
            "domain_log_ref",
            "ledger_event_ref",
        )
        if (
            not isinstance(tdd, dict)
            or tdd.get("phase") != "pre_implementation"
            or tdd.get("expected_initial_state") != "red"
            or any(not _nonempty(tdd.get(field)) for field in required[2:])
            or _ref_parts(tdd.get("test_sha256_ref"), {"artifact"}) is None
            or _ref_parts(tdd.get("preimplementation_tree_ref"), {"artifact"}) is None
            or _ref_parts(tdd.get("domain_log_ref"), {"execution"}) is None
            or _ref_parts(tdd.get("ledger_event_ref"), {"artifact"}) is None
        ):
            return _reject("E_V235_TDD_BINDING")
    elif "tdd" in case:
        return _reject("E_V235_TDD_BINDING")

    if case["test_kind"] in {"integration", "api"}:
        consumed = processing.get("consumed_input_refs")
        bindings = expected.get("input_bindings")
        if not _string_list(consumed) or not isinstance(bindings, list) or not bindings:
            return _reject("E_V235_INTEGRATION_COMPARISON")
        consumed_set = set(consumed)
        if len(consumed_set) != len(consumed) or any(
            not _resolve_ref(case, item, {"input"})[0] for item in consumed
        ):
            return _reject("E_V235_INTEGRATION_COMPARISON")
        binding_pairs: list[tuple[str, str]] = []
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) != {"input_ref", "observable_ref"}:
                return _reject("E_V235_INTEGRATION_COMPARISON")
            input_ref = binding.get("input_ref")
            observable_ref = binding.get("observable_ref")
            if (
                not isinstance(input_ref, str)
                or not isinstance(observable_ref, str)
                or input_ref not in consumed_set
                or not _resolve_ref(case, input_ref, {"input"})[0]
                or observable_ref not in observable_refs
                or observable_ref not in actual_refs
            ):
                return _reject("E_V235_INTEGRATION_COMPARISON")
            binding_pairs.append((input_ref, observable_ref))
        if len(binding_pairs) != len(set(binding_pairs)) or {item[0] for item in binding_pairs} != consumed_set:
            return _reject("E_V235_INTEGRATION_COMPARISON")
    return _ok(case_id=case["case_id"], test_kind=case["test_kind"], assertion_ids=sorted(assertion_ids))


def validate_test_case_document(document: Any) -> dict[str, Any]:
    if isinstance(document, dict) and document.get("schema_version") == TEST_CASE_SCHEMA:
        cases = [document]
    elif isinstance(document, dict) and isinstance(document.get("valid_cases"), list):
        cases = document["valid_cases"]
    elif isinstance(document, list):
        cases = document
    else:
        return _reject("E_V235_TEST_CASE_REQUIRED")
    if not cases:
        return _reject("E_V235_TEST_CASE_REQUIRED")
    case_ids: list[str] = []
    for case in cases:
        result = validate_test_case_contract(case)
        if not result.get("ok"):
            return result
        case_ids.append(result["case_id"])
    if len(case_ids) != len(set(case_ids)):
        return _reject("E_V235_TEST_CASE_REQUIRED")
    return _ok(validated_case_ids=case_ids, count=len(case_ids))


def evaluate_implementation_gate(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schema_version") != "goal-teams-implementation-gate-v2.35":
        return _reject("E_V235_GATE_CONTRACT")
    contract = request.get("contract")
    architecture = request.get("architecture")
    environment = request.get("environment")
    red = request.get("red_evidence")
    if (
        not isinstance(contract, dict)
        or contract.get("state") != "accepted"
        or contract.get("check_state") != "passed"
        or not _valid_hash(contract.get("artifact_sha256"))
        or contract.get("artifact_sha256") != contract.get("current_sha256")
    ):
        return _reject("E_V235_GATE_CONTRACT")
    contract_identities = (
        contract.get("owner_run_id"),
        contract.get("validator_run_id"),
    )
    if (
        any(not _nonempty(item) for item in contract_identities)
        or contract_identities[0] == contract_identities[1]
    ):
        return _reject("E_V235_GATE_INDEPENDENCE")
    if (
        not isinstance(architecture, dict)
        or architecture.get("state") != "accepted"
        or architecture.get("check_state") != "passed"
        or not _valid_hash(architecture.get("artifact_sha256"))
        or architecture.get("artifact_sha256") != architecture.get("current_sha256")
        or architecture.get("contract_sha256") != contract.get("artifact_sha256")
    ):
        return _reject("E_V235_GATE_ARCHITECTURE")
    architecture_identities = (
        architecture.get("owner_run_id"),
        architecture.get("validator_run_id"),
    )
    if (
        any(not _nonempty(item) for item in architecture_identities)
        or architecture_identities[0] == architecture_identities[1]
    ):
        return _reject("E_V235_GATE_INDEPENDENCE")
    if (
        not isinstance(environment, dict)
        or environment.get("conclusion") != "ready"
        or environment.get("check_state") != "passed"
        or not _valid_hash(environment.get("artifact_sha256"))
        or environment.get("artifact_sha256") != environment.get("current_sha256")
        or environment.get("architecture_sha256") != architecture.get("artifact_sha256")
    ):
        return _reject("E_V235_GATE_ENVIRONMENT")
    environment_identities = (
        environment.get("owner_run_id"),
        environment.get("validator_run_id"),
    )
    if (
        any(not _nonempty(item) for item in environment_identities)
        or environment_identities[0] == environment_identities[1]
    ):
        return _reject("E_V235_GATE_INDEPENDENCE")
    if not isinstance(red, dict) or red.get("state") != "red" or red.get("current") is not True:
        return _reject("E_V235_TDD_EVIDENCE")
    designer_run_id = red.get("designer_run_id")
    implementer_run_id = request.get("implementer_run_id")
    if (
        not _nonempty(designer_run_id)
        or not _nonempty(implementer_run_id)
        or implementer_run_id == designer_run_id
    ):
        return _reject("E_V235_GATE_INDEPENDENCE")
    if not _valid_hash(red.get("test_sha256")) or red.get("test_sha256") != red.get("current_test_sha256"):
        return _reject("E_V235_TDD_TEST_HASH")
    if not _valid_hash(red.get("preimplementation_tree")) or red.get("preimplementation_tree") != red.get("current_preimplementation_tree"):
        return _reject("E_V235_TDD_TREE")
    if (
        not _nonempty(red.get("domain_log_ref"))
        or not _valid_hash(red.get("domain_log_sha256"))
        or red.get("domain_log_current") is not True
    ):
        return _reject("E_V235_TDD_DOMAIN_LOG")
    if (
        not _valid_hash(red.get("ledger_prefix_sha256"))
        or not isinstance(red.get("ledger_revision"), int)
        or red.get("ledger_revision") <= 0
        or red.get("ledger_current") is not True
    ):
        return _reject("E_V235_TDD_LEDGER")
    start_revision = request.get("implementation_start_revision")
    design_revision = red.get("test_design_event_revision")
    if (
        red.get("implementation_started") is not False
        or not isinstance(start_revision, int)
        or not isinstance(design_revision, int)
        or design_revision >= start_revision
        or design_revision != red.get("ledger_revision")
    ):
        return _reject("E_V235_TDD_TIMING")
    return _ok(gate_state="open", implementation_start_revision=start_revision)


def evaluate_green_gate(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schema_version") != "goal-teams-green-gate-v2.35":
        return _reject("E_V235_GREEN_EVIDENCE")
    identities = [
        request.get("runner_run_id"),
        request.get("designer_run_id"),
        request.get("implementer_run_id"),
    ]
    if any(not _nonempty(item) for item in identities) or len(identities) != len(set(identities)):
        return _reject("E_V235_GREEN_INDEPENDENCE")
    green = request.get("green_evidence")
    if not isinstance(green, dict) or green.get("state") != "green" or green.get("current") is not True:
        return _reject("E_V235_GREEN_EVIDENCE")
    results = green.get("assertion_results")
    if not isinstance(results, list) or not results or any(
        not isinstance(item, dict) or not _nonempty(item.get("assertion_id")) or item.get("state") != "passed"
        for item in results
    ):
        return _reject("E_V235_GREEN_ASSERTIONS")
    if not _valid_hash(green.get("test_sha256")) or green.get("test_sha256") != green.get("red_test_sha256"):
        return _reject("E_V235_TDD_TEST_HASH")
    if (
        not _valid_hash(green.get("implementation_tree"))
        or green.get("implementation_tree") != green.get("current_implementation_tree")
        or not _nonempty(green.get("domain_log_ref"))
        or not _valid_hash(green.get("domain_log_sha256"))
        or green.get("domain_log_current") is not True
    ):
        return _reject("E_V235_GREEN_EVIDENCE")
    revisions = (
        request.get("red_event_revision"),
        request.get("implementation_event_revision"),
        request.get("green_event_revision"),
    )
    if any(not isinstance(item, int) for item in revisions) or not (revisions[0] < revisions[1] < revisions[2]):
        return _reject("E_V235_TDD_TIMING")
    return _ok(gate_state="accepted", assertion_ids=sorted(item["assertion_id"] for item in results))


def _audit_self_reference(request: dict[str, Any]) -> bool:
    audit = request.get("completion_audit")
    audit_ref = audit.get("artifact_ref") if isinstance(audit, dict) else None
    if not isinstance(audit, dict) or audit.get("in_required_graph") is not False:
        return True
    required_tasks = request.get("required_tasks")
    if not isinstance(required_tasks, list) or any(
        isinstance(item, str) and "completion_audit" in item.casefold() for item in required_tasks
    ):
        return True
    artifact_refs = request.get("required_task_artifact_refs")
    evidence_refs = request.get("required_task_evidence_refs")
    if not isinstance(artifact_refs, list) or not isinstance(evidence_refs, list):
        return True
    if any(item == audit_ref or (isinstance(item, str) and "completion-audit" in item.casefold()) for item in artifact_refs):
        return True
    return any(isinstance(item, str) and "completion-audit" in item.casefold() for item in evidence_refs)


def evaluate_release_audit_gate(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schema_version") != "goal-teams-release-audit-gate-v2.35":
        return _reject("E_V235_RELEASE_TASK", audit_allowed=False)
    if _audit_self_reference(request):
        return _reject("E_AUDIT_SELF_REFERENCE", audit_allowed=False)
    commit = request.get("release_commit")
    release = request.get("release_task")
    remote = request.get("remote_evidence")
    local = request.get("local_evidence")
    post = request.get("post_release_task")
    if (
        not isinstance(commit, str)
        or not _COMMIT.fullmatch(commit)
        or not isinstance(release, dict)
        or release.get("task_state") != "accepted"
        or release.get("check_state") != "passed"
    ):
        return _reject("E_V235_RELEASE_TASK", audit_allowed=False)
    if (
        not isinstance(remote, dict)
        or remote.get("state") != "accepted"
        or remote.get("current") is not True
        or remote.get("commit") != commit
        or remote.get("branch_fast_forward") is not True
        or remote.get("main_fast_forward") is not True
    ):
        return _reject("E_V235_REMOTE_EVIDENCE", audit_allowed=False)
    if (
        not isinstance(local, dict)
        or local.get("state") != "accepted"
        or local.get("current") is not True
        or local.get("commit") != commit
        or local.get("installed_version") != "V2.35"
        or local.get("full_check_passed") is not True
    ):
        return _reject("E_V235_LOCAL_EVIDENCE", audit_allowed=False)
    required_evidence = request.get("required_task_evidence_refs")
    if (
        not isinstance(post, dict)
        or post.get("task_state") != "accepted"
        or post.get("check_state") != "passed"
        or not _string_list(post.get("evidence_refs"))
        or not _string_list(required_evidence)
        or not set(required_evidence) <= set(post["evidence_refs"])
    ):
        return _reject("E_V235_POST_RELEASE_TASK", audit_allowed=False)
    return _ok(audit_allowed=True, release_commit=commit)


def _safe_relative(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(char) < 32 for char in value):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.parts


def _regular_contained_file(root: Path, relative: str) -> Path | None:
    parts = _safe_relative(relative)
    if parts is None:
        return None
    current = root
    try:
        for part in parts:
            current = current / part
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode):
                return None
        if not stat.S_ISREG(os.lstat(current).st_mode) or current.stat().st_nlink != 1:
            return None
        current.resolve().relative_to(root.resolve())
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None
    return current


def _builtin_denied(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    lowered = {part.casefold() for part in parts}
    return bool(
        not parts
        or any(part.startswith("GoalTeamsWork-") for part in parts)
        or lowered & _PROCESS_PARTS
        or parts[-1] == _ROADMAP_BASENAME
    )


def _manifest_allowlist(path: Path) -> tuple[set[str], tuple[str, ...]] | None:
    files: set[str] = set()
    prefixes: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kind, value = line.split(maxsplit=1)
            if _safe_relative(value.rstrip("/")) is None:
                return None
            if kind == "file" and not value.endswith("/"):
                files.add(value)
            elif kind == "prefix" and value.endswith("/"):
                prefixes.append(value)
            else:
                return None
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return files, tuple(sorted(set(prefixes)))


def evaluate_package_selection(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _reject("E_V235_PACKAGE_PATH")
    try:
        root = Path(str(request.get("repo_root", ""))).absolute().resolve()
    except (OSError, RuntimeError):
        return _reject("E_V235_PACKAGE_PATH")
    if not root.is_dir() or root.is_symlink():
        return _reject("E_V235_PACKAGE_PATH")
    manifest_ref = request.get("manifest_path")
    manifest = _regular_contained_file(root, manifest_ref) if isinstance(manifest_ref, str) else None
    allowlist = _manifest_allowlist(manifest) if manifest is not None else None
    candidates = request.get("candidate_paths")
    immutable = request.get("immutable_sources")
    if allowlist is None or not isinstance(candidates, list) or not isinstance(immutable, list):
        return _reject("E_V235_PACKAGE_PATH")
    immutable_records: list[dict[str, Any]] = []
    for item in immutable:
        if not isinstance(item, dict) or not _valid_hash(item.get("sha256")):
            return _reject("E_V235_PACKAGE_IMMUTABLE_SOURCE")
        path = _regular_contained_file(root, item.get("path")) if isinstance(item.get("path"), str) else None
        if path is None:
            return _reject("E_V235_PACKAGE_PATH")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        if before != item["sha256"]:
            return _reject("E_V235_PACKAGE_IMMUTABLE_SOURCE")
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        if after != before:
            return _reject("E_V235_PACKAGE_IMMUTABLE_SOURCE")
        immutable_records.append(
            {"path": item["path"], "before_sha256": before, "after_sha256": after}
        )
    files, prefixes = allowlist
    selected: list[str] = []
    denied: list[str] = []
    if any(not isinstance(item, str) for item in candidates):
        return _reject("E_V235_PACKAGE_PATH")
    for relative in sorted(set(candidates)):
        path = _regular_contained_file(root, relative)
        if path is None:
            return _reject("E_V235_PACKAGE_PATH")
        allowed = relative in files or any(relative.startswith(prefix) for prefix in prefixes)
        if _builtin_denied(relative) or not allowed:
            denied.append(relative)
        else:
            selected.append(relative)
    return _ok(
        selected_paths=selected,
        denied_paths=denied,
        immutable_sources=immutable_records,
        deny_policy_source="builtin_l0",
    )


__all__ = [
    "ALLOWED_COMPARATORS",
    "DuplicateKeyError",
    "evaluate_green_gate",
    "evaluate_implementation_gate",
    "evaluate_package_selection",
    "evaluate_port_scan_request",
    "evaluate_release_audit_gate",
    "is_v235_route",
    "normalize_project_route",
    "strict_json_loads",
    "validate_specialist_action",
    "validate_specialist_capability_registry",
    "validate_specialist_improvement_lifecycle",
    "validate_specialist_proposal",
    "validate_test_case_contract",
    "validate_test_case_document",
]
