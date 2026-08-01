"""V2.49 current-generation test-gate primitives.

This module deliberately keeps routing, immutable test receipts, and lightweight
policy checks in one dependency-free place.  It does not execute domain tests;
it validates receipts produced by a runner.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping, Sequence


HEX64 = frozenset("0123456789abcdef")
GATE_IDS = (
    "tdd",
    "incremental",
    "full_regression",
    "release_security_review",
    "s0",
    "s1",
    "s2",
    "s3",
    "s4",
)
TG_IDS = tuple(f"TG{index:02d}" for index in range(9))
TG_ERRORS = {
    "TG00": "E_V249_TG00_SCOPE",
    "TG01": "E_V249_TG01_CONTRACT",
    "TG02": "E_V249_TG02_IDENTITY",
    "TG03": "E_V249_TG03_ENVIRONMENT",
    "TG04": "E_V249_TG04_EXECUTION",
    "TG05": "E_V249_TG05_BUSINESS_ORACLE",
    "TG06": "E_V249_TG06_SIDE_EFFECT",
    "TG07": "E_V249_TG07_EVIDENCE",
    "TG08": "E_V249_TG08_REVIEW",
}
SIDE_EFFECT_FACETS = (
    "observation",
    "exact_readback",
    "cleanup",
    "cleanup_verification",
    "idempotency_retry",
    "replay_reconciliation",
)
ASSURANCE_AXES = ("actor", "oracle", "authorization")
LEGACY_PATH_MARKERS = (
    "schemas/v2.35/",
    "schemas/v2.44/",
    "schemas/v2.46/",
    "schemas/v2.47/",
    "references/legacy-replay/",
)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in HEX64 for character in value)
    )


def _canonical_digest(value: Mapping[str, Any], digest_field: str = "digest") -> str:
    payload = copy.deepcopy(dict(value))
    payload.pop(digest_field, None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_nonempty_text(item) for item in value)
    )


def _resolve_path(value: Any, path: str) -> tuple[bool, Any]:
    current = value
    for component in path.split("."):
        if not isinstance(current, Mapping) or component not in current:
            return False, None
        current = current[component]
    return True, current


def _error(*codes: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": codes[0] if codes else "E_V249_TEST_GATE",
        "errors": list(dict.fromkeys(codes)),
        "mutation_count": 0,
        **extra,
    }


def _passed(**extra: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "error_code": None,
        "errors": [],
        "mutation_count": 0,
        **extra,
    }


def _gate(
    requirement: str,
    *,
    activation: str,
    check_state: str,
    run_outcome: str,
    reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "gate_requirement": requirement,
        "gate_activation_state": activation,
        "check_state": check_state,
        "run_outcome": run_outcome,
    }
    if reason is not None:
        result["not_required_reason"] = reason
    return result


def derive_gate_plan(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Derive phase-scoped gates without executing any gate command."""

    size = facts.get("project_size")
    phase = facts.get("workflow_phase")
    release_intent = facts.get("release_intent") is True
    implementation_complete = facts.get("implementation_scope_complete") is True
    frozen = facts.get("stage") == "released" or facts.get("candidate_frozen") is True

    if size not in {"small", "medium", "large"}:
        return _error("E_V249_ROUTE_SIZE")
    if phase not in {"development", "release_readiness", "release"}:
        return _error("E_V249_WORKFLOW_PHASE")

    gates: dict[str, dict[str, Any]] = {}
    release_denominator: dict[str, Any]

    if phase == "development":
        gates["tdd"] = _gate(
            "required", activation="active", check_state="not_started", run_outcome="not_run"
        )
        gates["incremental"] = _gate(
            "required", activation="active", check_state="not_started", run_outcome="not_run"
        )
        for gate_id in GATE_IDS[2:]:
            gates[gate_id] = _gate(
                "not_required",
                activation="inactive",
                check_state="not_required",
                run_outcome="not_run",
                reason="not_required_by_development_phase",
            )

        if release_intent:
            # A release denominator may be planned during development, but it is
            # never activated or executed until the workflow changes phase.
            release_state = "scheduled"
            release_denominator = {
                "denominator_id": facts.get("release_denominator_id", "DEN-RELEASE-SCHEDULED"),
                "workflow_phase": "release",
                "gate_activation_state": release_state,
                "gates": {
                    gate_id: _gate(
                        "required",
                        activation=release_state,
                        check_state="not_started",
                        run_outcome="not_run",
                    )
                    for gate_id in ("full_regression", "release_security_review")
                },
            }
        else:
            release_denominator = {
                "denominator_id": facts.get("release_denominator_id", "DEN-RELEASE-INACTIVE"),
                "workflow_phase": "release",
                "gate_activation_state": "inactive",
                "gates": {
                    gate_id: _gate(
                        "not_required",
                        activation="inactive",
                        check_state="not_required",
                        run_outcome="not_run",
                        reason="not_required_by_non_release_policy",
                    )
                    for gate_id in ("full_regression", "release_security_review")
                },
            }
        return {
            "ok": True,
            "project_size": size,
            "workflow_phase": phase,
            "blocking_gates": ["tdd", "incremental"],
            "gates": gates,
            "development_denominator": {
                "denominator_id": facts.get("development_denominator_id", "DEN-DEVELOPMENT"),
                "workflow_phase": "development",
            },
            "release_denominator": release_denominator,
            "development_complete": implementation_complete,
            "release_ready": False,
        }

    release_ready_to_run = release_intent and implementation_complete and frozen
    for gate_id in ("tdd", "incremental"):
        gates[gate_id] = _gate(
            "not_required",
            activation="closed",
            check_state="not_required",
            run_outcome="not_run",
            reason="closed_development_phase",
        )
    for gate_id in ("full_regression", "release_security_review"):
        if release_ready_to_run:
            gates[gate_id] = _gate(
                "required", activation="active", check_state="not_started", run_outcome="not_run"
            )
        else:
            gates[gate_id] = _gate(
                "not_required" if not release_intent else "required",
                activation="inactive" if not release_intent else "scheduled",
                check_state="not_required" if not release_intent else "not_started",
                run_outcome="not_run",
                reason="not_required_by_non_release_policy" if not release_intent else None,
            )
    for gate_id in ("s0", "s1", "s2", "s4"):
        gates[gate_id] = _gate(
            "required" if release_ready_to_run else "not_required",
            activation="active" if release_ready_to_run else "inactive",
            check_state="not_started" if release_ready_to_run else "not_required",
            run_outcome="not_run",
            reason=None if release_ready_to_run else "release_readiness_incomplete",
        )
    s3_required = size == "large" and release_ready_to_run and facts.get("s1_current") is True
    gates["s3"] = _gate(
        "required" if s3_required else "not_required",
        activation="active" if s3_required else "inactive",
        check_state="not_started" if s3_required else "not_required",
        run_outcome="not_run",
        reason=None if s3_required else "not_required_by_v249_policy",
    )
    gates["s3"].update(
        s3_process_invocation_count=0,
        child_argv=[],
    )
    gates["s2"].update(
        deterministic_build_count=0,
        security_check_requirement="not_required",
        validation_mode="single_pass_artifact_validation",
    )
    gates["s4"].update(authorization_mode="startup_once")
    release_gate_ids = ["full_regression", "release_security_review", "s0", "s1", "s2"]
    if s3_required:
        release_gate_ids.append("s3")
    release_gate_ids.append("s4")
    return {
        "ok": True,
        "project_size": size,
        "workflow_phase": phase,
        "blocking_gates": (
            ["full_regression", "release_security_review"] if release_ready_to_run else []
        ),
        "gates": gates,
        "development_denominator": {
            "denominator_id": facts.get("development_denominator_id", "DEN-DEVELOPMENT"),
            "workflow_phase": "development",
            "gate_activation_state": "closed",
            "gates": ["tdd", "incremental"],
        },
        "release_denominator": {
            "denominator_id": facts.get("release_denominator_id", "DEN-RELEASE"),
            "workflow_phase": "release",
            "gate_activation_state": "active" if release_ready_to_run else "scheduled",
            "gates": release_gate_ids,
        },
        "development_complete": implementation_complete,
        "release_ready": False,
    }


def build_tdd_chain(
    denominator_id: str,
    test_case_id: str,
    test_file_digest: str,
    red_source_digest: str,
    green_source_digest: str,
    environment_digest: str,
) -> dict[str, Any]:
    """Build a deterministic Red/Green receipt chain for tests and adapters."""

    denominator: dict[str, Any] = {
        "object_type": "RiskDenominator",
        "denominator_id": denominator_id,
        "revision": 1,
        "workflow_phase": "development",
        "activation_condition": {"gate_id": "tdd"},
        "items": [
            {
                "item_id": f"RISK-{test_case_id}",
                "source_ref": f"acceptance.{test_case_id}",
                "severity": "high",
                "applicability": "applicable",
                "gate_requirement": "required",
                "case_refs": [test_case_id],
                "assertion_refs": ["ASSERT-BEHAVIOR"],
                "check_refs": list(TG_IDS),
                "coverage_state": "covered",
            }
        ],
    }
    denominator["digest"] = _canonical_digest(denominator)

    case: dict[str, Any] = {
        "schema_version": "goal-teams-test-case-v2.49",
        "object_type": "TestCase",
        "test_case_id": test_case_id,
        "case_revision": 1,
        "test_type": "tdd",
        "denominator_id": denominator_id,
        "denominator_digest": denominator["digest"],
        "plan_binding": {
            "plan_id": denominator_id,
            "revision": denominator["revision"],
            "digest": denominator["digest"],
        },
        "denominator_binding": {
            "denominator_id": denominator_id,
            "revision": denominator["revision"],
            "digest": denominator["digest"],
        },
        "requirement_refs": [f"REQ-{test_case_id}"],
        "acceptance_criteria_refs": [f"AC-{test_case_id}"],
        "risk_refs": [f"RISK-{test_case_id}"],
        "source_binding": {
            "target_id": f"TARGET-{test_case_id}",
            "protected_snapshot_required": True,
        },
        "environment_requirements": {
            "environment_digest": environment_digest,
            "preconditions": ["test_runner_available"],
            "data_refs": [f"synthetic:{test_case_id}"],
            "permission_refs": ["workspace_read_write"],
        },
        "preconditions": ["test_runner_available"],
        "input": {"value": False},
        "processing": ["invoke_target_behavior"],
        "expected_output": {"value": True},
        "test_file_digest": test_file_digest,
        "assertions": [
            {
                "assertion_id": "ASSERT-BEHAVIOR",
                "oracle_ref": "expected_output.value",
                "observed_field": "observed_output.value",
                "comparator": "equals",
                "expected_value": True,
                "severity": "high",
                "failure_code": "E_V249_BEHAVIOR",
            }
        ],
        "side_effect_contract": {"required": False, "external": False},
        "idempotency_contract": {"required": False, "idempotent": True},
        "cleanup_contract": {"required": False},
        "replay_policy": {"mode": "not_required", "automatic": False},
        "test_file_refs": [
            {
                "path": f"tests/{test_case_id}.py",
                "sha256": test_file_digest,
                "discovery_kind": "test_case",
                "discovery_id": test_case_id,
            }
        ],
        "typed_payload": {"red_green_required": True},
    }
    case["case_digest"] = _canonical_digest(case, "case_digest")

    def run(role: str, source_digest: str, outcome: str, ordinal: int) -> dict[str, Any]:
        observed_value = outcome == "passed"
        attempt_id = f"ATT-{ordinal}"
        receipt: dict[str, Any] = {
            "object_type": "TestRunReceipt",
            "run_id": f"RUN-{test_case_id}-{ordinal}",
            "run_role": role,
            "ordinal": ordinal,
            "denominator_id": denominator_id,
            "denominator_digest": denominator["digest"],
            "case_digest": case["case_digest"],
            "test_file_digest": test_file_digest,
            "source_digest": source_digest,
            "environment_digest": environment_digest,
            "run_outcome": outcome,
            "runner_identity": {
                "actor_id": f"runner-{ordinal}",
                "run_id": f"RUNNER-{test_case_id}-{ordinal}",
            },
            "command": {
                "argv": ["python3", "-m", "unittest", test_case_id],
                "cwd": ".",
            },
            "discovery_count": 1,
            "attempts": [
                {
                    "attempt_id": attempt_id,
                    "ordinal": 1,
                    "outcome": outcome,
                }
            ],
            "first_failure": (
                {
                    "attempt_id": attempt_id,
                    "failure_code": "E_V249_BEHAVIOR",
                    "outcome": "failed",
                }
                if outcome == "failed"
                else None
            ),
            "retry_authorization": {"authorized": False, "max_attempts": 1},
            "flake": {"detected": False, "classification": "none"},
            "observation": {"observed_output": {"value": observed_value}},
            "side_effects": {
                facet: "not_required" for facet in SIDE_EFFECT_FACETS
            },
            "raw_artifact_digest": _text_digest(
                f"{test_case_id}:{role}:{source_digest}:{outcome}"
            ),
        }
        receipt["digest"] = _canonical_digest(receipt)
        return receipt

    red = run("tdd_red", red_source_digest, "failed", 1)
    green = run("tdd_green", green_source_digest, "passed", 2)
    review: dict[str, Any] = {
        "object_type": "TestReviewReceipt",
        "review_id": f"REVIEW-{test_case_id}",
        "denominator_id": denominator_id,
        "denominator_digest": denominator["digest"],
        "case_digest": case["case_digest"],
        "run_receipt_digests": [red["digest"], green["digest"]],
        "validator_identity": {
            "validator_id": "v249-test-gate",
            "validator_digest": _text_digest("v249-test-gate"),
            "reviewer_run_id": f"REVIEWER-{test_case_id}",
        },
        "recomputed_assertions": [
            {
                "assertion_id": "ASSERT-BEHAVIOR",
                "comparator": "equals",
                "expected_value": True,
                "actual_value": True,
                "passed": True,
            }
        ],
        "coverage_projection": {
            "applicable_item_ids": [f"RISK-{test_case_id}"],
            "covered_item_ids": [f"RISK-{test_case_id}"],
            "uncovered_item_ids": [],
            "excluded_item_ids": [],
        },
        "side_effect_verification": {
            facet: "not_required" for facet in SIDE_EFFECT_FACETS
        },
        "evidence": [
            {
                "check_id": "tdd",
                "run_digest": receipt["digest"],
                "raw_artifact_digest": receipt["raw_artifact_digest"],
                "evidence_integrity": "valid",
                "evidence_applicability": "current",
                "revalidation_state": "closed",
            }
            for receipt in (red, green)
        ],
        "check_state": "passed",
        "assurance": {
            "delivery_run_ids": [red["runner_identity"]["run_id"], green["runner_identity"]["run_id"]],
            "reviewer_run_id": f"REVIEWER-{test_case_id}",
            "required_actor_assurances": ["runner", "reviewer"],
            "provided_actor_assurances": ["runner", "reviewer"],
            "required_oracle_assurances": ["deterministic_comparator"],
            "provided_oracle_assurances": ["deterministic_comparator"],
            "required_authorization_assurances": ["scope_authorized"],
            "provided_authorization_assurances": ["scope_authorized"],
        },
        "tg_results": [
            {"tg_id": tg_id, "gate_requirement": "required", "check_state": "passed"}
            for tg_id in TG_IDS
        ],
    }
    review["digest"] = _canonical_digest(review)
    return {
        "schema_version": "goal-teams-test-chain-v2.49",
        "denominator": denominator,
        "case": case,
        "runs": [red, green],
        "review": review,
    }


def _retry_became_flaky(run: Mapping[str, Any]) -> bool:
    attempts = run.get("attempts")
    if not isinstance(attempts, list) or len(attempts) < 2:
        return False
    outcomes = [item.get("outcome") for item in attempts if isinstance(item, dict)]
    return "failed" in outcomes[:-1] and outcomes[-1:] == ["passed"]


def validate_test_chain(chain: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    denominator = chain.get("denominator")
    case = chain.get("case")
    runs = chain.get("runs")
    review = chain.get("review")
    if not isinstance(denominator, dict) or not isinstance(case, dict):
        return _error("E_V249_TEST_CHAIN_SHAPE")
    if not isinstance(runs, list) or not runs or not isinstance(review, dict):
        return _error("E_V249_TEST_CHAIN_SHAPE")

    if denominator.get("digest") != _canonical_digest(denominator):
        errors.extend(("E_V249_TG00_DENOMINATOR", "E_V249_DIGEST_MISMATCH"))
    if case.get("denominator_id") != denominator.get("denominator_id") or case.get(
        "denominator_digest"
    ) != denominator.get("digest"):
        errors.append("E_V249_CHAIN_BINDING")
    if case.get("case_digest") != _canonical_digest(case, "case_digest"):
        errors.extend(("E_V249_TG01_CONTRACT", "E_V249_DIGEST_MISMATCH"))

    for run in runs:
        if not isinstance(run, dict):
            errors.append("E_V249_TG04_EXECUTION")
            continue
        if run.get("denominator_id") != denominator.get("denominator_id") or run.get(
            "denominator_digest"
        ) != denominator.get("digest"):
            errors.append("E_V249_CHAIN_BINDING")
        if run.get("case_digest") != case.get("case_digest") or run.get(
            "test_file_digest"
        ) != case.get("test_file_digest"):
            errors.append("E_V249_TDD_CASE_DRIFT")
        if run.get("digest") != _canonical_digest(run):
            # A changed binding is reported both as drift and digest tampering.
            if run.get("case_digest") != case.get("case_digest"):
                errors.append("E_V249_TDD_CASE_DRIFT")
            errors.append("E_V249_DIGEST_MISMATCH")
        if _retry_became_flaky(run) and run.get("run_outcome") != "flaky":
            errors.append("E_V249_TDD_FLAKE_MISCLASSIFIED")

    roles = [item.get("run_role") for item in runs if isinstance(item, dict)]
    if roles == ["tdd_red", "tdd_green"]:
        red, green = runs
        if red.get("run_outcome") != "failed":
            errors.append("E_V249_TDD_RED_NOT_OBSERVED")
        if green.get("run_outcome") != "passed":
            errors.append("E_V249_TG04_EXECUTION")
        if red.get("source_digest") == green.get("source_digest") or red.get(
            "ordinal"
        ) != 1 or green.get("ordinal") != 2:
            errors.append("E_V249_TDD_SOURCE_ORDER")
    elif "tdd_red" in roles or "tdd_green" in roles:
        errors.append("E_V249_TDD_SOURCE_ORDER")

    expected_run_digests = [item.get("digest") for item in runs if isinstance(item, dict)]
    if review.get("run_receipt_digests") != expected_run_digests:
        errors.append("E_V249_CHAIN_BINDING")
    if review.get("denominator_digest") != denominator.get("digest"):
        errors.append("E_V249_CHAIN_BINDING")
    if review.get("digest") != _canonical_digest(review):
        errors.append("E_V249_DIGEST_MISMATCH")
    tg_results = review.get("tg_results")
    if not isinstance(tg_results, list) or [item.get("tg_id") for item in tg_results] != list(TG_IDS):
        errors.append("E_V249_TG08_ASSURANCE")
    elif any(
        item.get("gate_requirement") == "required" and item.get("check_state") != "passed"
        for item in tg_results
    ):
        errors.append("E_V249_TG08_ASSURANCE")
    if review.get("check_state") != "passed":
        errors.append("E_V249_TG08_ASSURANCE")

    if errors:
        return _error(*errors)
    return _passed(
        denominator_id=denominator.get("denominator_id"),
        test_case_id=case.get("test_case_id"),
        run_ids=[item.get("run_id") for item in runs],
        review_id=review.get("review_id"),
    )


def validate_current_route_closure(
    loaded_paths: Sequence[str],
    *,
    replay_version: str | None = None,
) -> dict[str, Any]:
    intersection = sorted(
        path
        for path in loaded_paths
        if any(marker in path for marker in LEGACY_PATH_MARKERS)
    )
    if replay_version is None and intersection:
        return _error(
            "E_V249_GENERATION_REPLAY_LEAK", legacy_intersection=intersection
        )
    return _passed(legacy_intersection=intersection, replay_version=replay_version)


def derive_installer_route(
    project_size: str,
    *,
    release_intent: bool,
    s1_current: bool,
) -> dict[str, Any]:
    required = project_size == "large" and release_intent and s1_current
    return {
        "gate_requirement": "required" if required else "not_required",
        "s3_process_invocation_count": 0,
        "child_argv": [],
        "not_required_reason": None if required else "not_required_by_v249_policy",
    }


def validate_git_transport(remote_url: str) -> dict[str, Any]:
    is_ssh = remote_url.startswith("git@") or remote_url.startswith("ssh://")
    if not is_ssh:
        return _error("E_V249_GIT_TRANSPORT_NOT_SSH")
    return _passed(transport="ssh")


def validate_subagent_assurance(
    *,
    delivery_run_ids: Sequence[str],
    reviewer_run_id: str,
    required_actor_assurances: Sequence[str],
    provided_actor_assurances: Sequence[str],
) -> dict[str, Any]:
    if reviewer_run_id in set(delivery_run_ids):
        return _error("E_V249_TG08_ASSURANCE", reason="reviewer_not_independent")
    missing = sorted(set(required_actor_assurances) - set(provided_actor_assurances))
    if missing:
        return _error("E_V249_TG08_ASSURANCE", missing_actor_assurances=missing)
    return _passed(reviewer_run_id=reviewer_run_id)
