from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from scripts.v250.task_plan_compiler import (
    compile_task_plan,
    validate_compiled_task_plan,
)


ZERO_SHA256 = "0" * 64
SHA = {letter: letter * 64 for letter in "abcdef0123456789"}


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _with_self_digest(value: dict[str, object], field: str) -> dict[str, object]:
    result = copy.deepcopy(value)
    result[field] = _canonical_sha256(result)
    return result


def _rehash_event(event: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(event)
    result["event_sha256"] = _canonical_sha256(
        {key: value for key, value in result.items() if key != "event_sha256"}
    )
    return result


def _target(module_name: str) -> Any:
    """Keep discovery positive while the exact Runtime target is absent."""

    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == module_name or missing.startswith("scripts.v265"):
            raise AssertionError(
                f"E_TEST_V265_TARGET_MISSING:{module_name}"
            ) from exc
        raise


def _task(
    task_id: str,
    *,
    depends_on: list[str],
    consumers: list[str],
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "requirement_refs": [f"REQ-RUNTIME-{task_id}"],
        "consumer_refs": list(consumers),
        "admission": {
            "current_consumer_confirmed": True,
            "observable_acceptance_defined": True,
            "scope_locked": True,
            "budget_bound": True,
            "exit_condition_frozen": True,
            "evidence_refs": [f"evidence:consumer:{task_id}"],
        },
        "owner": f"owner:{task_id}",
        "validator": f"validator:{task_id}",
        "scope_allowlist": [f"scope/{task_id}/**"],
        "forbidden_scope": ["README.md", "release/**"],
        "depends_on": list(depends_on),
        "budget_wu": 2,
        "attempt_budget": 2,
        "revalidation_budget": 1,
        "inputs": [{"input_id": f"input:{task_id}"}],
        "outputs": [
            {
                "output_id": f"output:{task_id}",
                "consumer_refs": list(consumers),
                "required": True,
            }
        ],
        "verification": [
            {
                "verification_id": f"verification:{task_id}",
                "verification_type": "runtime_behavior",
                "method": f"observe Runtime Node {task_id}",
                "expected_result": f"Node {task_id} emits a typed Outcome",
                "evidence_refs": [f"evidence:verification:{task_id}"],
            }
        ],
        "business_oracle": {
            "oracle_id": f"oracle:{task_id}",
            "oracle_type": "runtime_behavior",
            "acceptance_criteria": [f"Node {task_id} is independently observable"],
            "evidence_refs": [f"evidence:oracle:{task_id}"],
        },
        "exit_condition": {
            "exit_id": f"exit:{task_id}",
            "exit_type": "validated_outcome",
            "required_receipt_types": ["node_outcome", "node_validation"],
            "on_budget_exhaustion": "replan",
        },
        "failure_artifacts": [f"failure:{task_id}"],
    }


def _authoritative_plan() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    source = {
        "schema_version": "goal-teams-task-plan-v1",
        "plan_id": "GT-V265-RUNTIME-TEST",
        "plan_revision": 1,
        "tasks": [
            _task("A", depends_on=[], consumers=["task:JOIN"]),
            _task("B", depends_on=[], consumers=["task:JOIN"]),
            _task("JOIN", depends_on=["A", "B"], consumers=["consumer:v265"]),
        ],
        "phase_exact_sets": {
            "development": ["A", "B", "JOIN"],
            "runtime": [],
            "release": [],
        },
    }
    compiled = compile_task_plan(source)
    validation = validate_compiled_task_plan(compiled)
    return source, compiled, validation


def _input_port(port_id: str) -> dict[str, object]:
    return {
        "port_id": port_id,
        "schema_ref": "schema:artifact:v1",
        "required": True,
        "sensitivity": "internal",
    }


def _output_port(
    port_id: str,
    consumers: list[str],
    *,
    required: bool = True,
) -> dict[str, object]:
    return {
        "port_id": port_id,
        "schema_ref": "schema:artifact:v1",
        "required": required,
        "sensitivity": "internal",
        "consumer_node_ids": list(consumers),
    }


def _node(
    task: dict[str, object],
    *,
    optional_data_output: bool = False,
) -> dict[str, object]:
    node_id = str(task["task_id"])
    is_join = node_id == "JOIN"
    return {
        "node_id": node_id,
        "task_refs": [node_id],
        "node_type": "validation" if is_join else "action",
        "owner_identity": task["owner"],
        "validator_identity": task["validator"],
        "action_ref": f"action:{node_id}",
        "resource_refs": {
            "required": [f"resource:{node_id}:required"],
            "recommended": [],
            "generated": [f"resource:{node_id}:generated"],
            "upstream_artifacts": (
                ["resource:A:artifact", "resource:B:artifact"] if is_join else []
            ),
            "forbidden": [f"resource:{node_id}:forbidden"],
        },
        "input_ports": [_input_port("in:A"), _input_port("in:B")] if is_join else [],
        "output_ports": [
            _output_port(
                f"out:{node_id}",
                ["JOIN"] if node_id in {"A", "B"} else [],
                required=not (optional_data_output and node_id == "A"),
            )
        ],
        "scope_allowlist": copy.deepcopy(task["scope_allowlist"]),
        "forbidden_scope": copy.deepcopy(task["forbidden_scope"]),
        "budget": {
            "work_units": task["budget_wu"],
            "attempts": task["attempt_budget"],
            "revalidations": task["revalidation_budget"],
            "context_tokens": 512,
        },
        "timeout_seconds": 30,
        "retry_policy": {
            "max_attempts": task["attempt_budget"],
            "retryable_outcomes": ["failed"],
            "backoff_seconds": [0],
        },
        "gate_refs": ["gate:join-evidence"] if is_join else [],
        "exit_condition_ref": task["exit_condition"]["exit_id"],
        "recovery_policy": {"mode": "none", "edge_id": None},
        "fan_in": (
            {
                "mode": "all",
                "edge_ids": [
                    "data:A:JOIN",
                    "data:B:JOIN",
                    "dep:A:JOIN",
                    "dep:B:JOIN",
                ],
                "quorum_count": None,
                "quorum_ratio_basis_points": None,
            }
            if is_join
            else None
        ),
    }


def _edge(
    edge_id: str,
    edge_type: str,
    source: str,
    target: str,
    *,
    accepted_outcomes: list[str] | None = None,
    data_bindings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "edge_type": edge_type,
        "source_node_id": source,
        "target_node_id": target,
        "accepted_outcomes": list(accepted_outcomes or ["completed"]),
        "gate_ref": None,
        "data_bindings": copy.deepcopy(data_bindings or []),
        "traversal_budget": 0,
    }


def _resource(
    resource_id: str,
    *,
    resource_type: str,
    producer: str | None,
    consumers: list[str],
) -> dict[str, object]:
    runtime = resource_type in {"upstream_artifact", "generated_context"}
    payload = f"bytes:{resource_id}".encode("utf-8")
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "source_ref": f"tests/v265/resources/{resource_id.replace(':', '-')}.txt",
        "revision": "revision:1",
        "expected_sha256": None if runtime else hashlib.sha256(payload).hexdigest(),
        "schema_ref": "schema:artifact:v1",
        "freshness_policy": {
            "mode": "runtime" if runtime else "max_age",
            "max_age_seconds": None if runtime else 60,
        },
        "sensitivity": "internal",
        "permission_ref": f"permission:{resource_id}",
        "token_budget": 128,
        "producer_node_id": producer,
        "consumer_node_ids": list(consumers),
    }


def _graph_document(
    source: dict[str, object],
    compiled_plan: dict[str, object],
    validation: dict[str, object],
    *,
    optional_data_output: bool = False,
) -> dict[str, object]:
    resources: list[dict[str, object]] = []
    for node_id in ("A", "B", "JOIN"):
        resources.extend(
            [
                _resource(
                    f"resource:{node_id}:required",
                    resource_type="repository_file",
                    producer=None,
                    consumers=[node_id],
                ),
                _resource(
                    f"resource:{node_id}:generated",
                    resource_type="generated_context",
                    producer=node_id,
                    consumers=[node_id],
                ),
                _resource(
                    f"resource:{node_id}:forbidden",
                    resource_type="repository_file",
                    producer=None,
                    consumers=[],
                ),
            ]
        )
    resources.extend(
        [
            _resource(
                "resource:A:artifact",
                resource_type="upstream_artifact",
                producer="A",
                consumers=["JOIN"],
            ),
            _resource(
                "resource:B:artifact",
                resource_type="upstream_artifact",
                producer="B",
                consumers=["JOIN"],
            ),
        ]
    )
    return {
        "schema_version": "goal-teams-graph-contract-v2.65",
        "graph_id": "GRAPH-V265-RUNTIME-TEST",
        "graph_revision": 1,
        "plan_binding": {
            "plan_id": source["plan_id"],
            "plan_revision": source["plan_revision"],
            "task_exact_set_sha256": compiled_plan["task_exact_set_digest"],
            "compiled_task_plan_sha256": compiled_plan["receipt_digest"],
            "task_plan_validation_sha256": validation["receipt_digest"],
        },
        "supersedes_graph_sha256": None,
        "nodes": [
            _node(task, optional_data_output=optional_data_output)
            for task in source["tasks"]
        ],
        "edges": [
            _edge("dep:A:JOIN", "dependency", "A", "JOIN"),
            _edge("dep:B:JOIN", "dependency", "B", "JOIN"),
            _edge(
                "data:A:JOIN",
                "data",
                "A",
                "JOIN",
                data_bindings=[
                    {
                        "output_port_id": "out:A",
                        "input_port_id": "in:A",
                        "schema_ref": "schema:artifact:v1",
                    }
                ],
            ),
            _edge(
                "data:B:JOIN",
                "data",
                "B",
                "JOIN",
                data_bindings=[
                    {
                        "output_port_id": "out:B",
                        "input_port_id": "in:B",
                        "schema_ref": "schema:artifact:v1",
                    }
                ],
            ),
        ],
        "resources": resources,
        "gates": [
            {
                "gate_id": "gate:human:A",
                "gate_type": "human_approval",
                "authority_ref": "external-human-authority",
                "required_evidence_types": ["approval_receipt"],
                "condition": None,
                "timeout_seconds": 300,
                "on_timeout_outcome": "waiting_user",
            },
            {
                "gate_id": "gate:join-evidence",
                "gate_type": "evidence",
                "authority_ref": None,
                "required_evidence_types": ["validator_receipt"],
                "condition": None,
                "timeout_seconds": 60,
                "on_timeout_outcome": "blocked",
            },
        ],
        "actions": [
            {
                "action_id": f"action:{node_id}",
                "runner": "host_adapter",
                "effect": "local_write",
                "tool_allowlist": ["callback"],
                "network_policy": "deny",
                "workspace_policy": "node_scope",
                "input_schema_ref": f"schema:action:{node_id}:input",
                "output_schema_ref": f"schema:action:{node_id}:output",
                "idempotency_required": False,
            }
            for node_id in ("A", "B", "JOIN")
        ],
    }


def _compiled_graph(*, optional_data_output: bool = False) -> dict[str, object]:
    source, compiled_plan, validation = _authoritative_plan()
    graph = importlib.import_module("scripts.v265.graph_contract")
    return graph.compile_graph_contract(
        _graph_document(
            source,
            compiled_plan,
            validation,
            optional_data_output=optional_data_output,
        ),
        compiled_task_plan=compiled_plan,
        task_plan_validation_receipt=validation,
    )


def _bindings(compiled_graph: dict[str, object]) -> dict[str, str]:
    return {
        "source_sha256": SHA["1"],
        "route_sha256": SHA["2"],
        "contract_sha256": str(compiled_graph["receipt_sha256"]),
        "task_exact_set_sha256": str(
            compiled_graph["plan_binding"]["task_exact_set_sha256"]
        ),
        "environment_sha256": SHA["3"],
        "authorization_lineage_sha256": SHA["4"],
    }


def _context_bundle(
    compiled_graph: dict[str, object],
    node_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    payload = f"bytes:resource:{node_id}:required".encode("utf-8")
    resource = next(
        item
        for item in compiled_graph["resources"]
        if item["resource_id"] == f"resource:{node_id}:required"
    )
    compiled_resource = {
        "resource_id": resource["resource_id"],
        "resource_type": resource["resource_type"],
        "source_ref": resource["source_ref"],
        "revision": resource["revision"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "estimated_tokens": (len(payload) + 3) // 4,
        "freshness_state": "current",
        "sensitivity": resource["sensitivity"],
        "permission_ref": resource["permission_ref"],
        "producer_node_id": None,
        "producer_receipt_sha256": None,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }
    bundle = _with_self_digest(
        {
            "schema_version": "goal-teams-context-bundle-v2.65",
            "bundle_id": f"BUNDLE-{node_id}",
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "node_id": node_id,
            "resources": [compiled_resource],
            "review_capsule_sha256": None,
            "total_bytes": len(payload),
            "estimated_tokens": (len(payload) + 3) // 4,
            "token_estimate_algorithm": "utf8_bytes_ceiling_div4",
            "compiled_at": "2026-08-22T10:00:00Z",
        },
        "bundle_sha256",
    )
    validation = _with_self_digest(
        {
            "schema_version": "goal-teams-context-validation-receipt-v2.65",
            "bundle_id": bundle["bundle_id"],
            "node_id": node_id,
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "bundle_sha256": bundle["bundle_sha256"],
            "valid": True,
            "validator": "scripts.v265.context_compiler.validate_context_bundle",
            "validated_at": "2026-08-22T10:00:01Z",
        },
        "receipt_sha256",
    )
    return bundle, validation


def _scope_sha256(node: dict[str, object]) -> str:
    return _canonical_sha256(
        {
            "scope_allowlist": node["scope_allowlist"],
            "forbidden_scope": node["forbidden_scope"],
        }
    )


def _capability(
    compiled_graph: dict[str, object],
    node_id: str,
    workspace: Path,
) -> dict[str, object]:
    node = next(item for item in compiled_graph["nodes"] if item["node_id"] == node_id)
    return _with_self_digest(
        {
            "schema_version": "goal-teams-host-capability-receipt-v2.65",
            "capability_id": f"capability:{node_id}",
            "issuer": "callback_fixture",
            "issuer_key_id": "callback_fixture:key:1",
            "issuer_assurance": "repository_fixture",
            "actor_relationship": "self",
            "proof_strength": "fixture_only",
            "host_execution_id": "HOST-FIXTURE-1",
            "node_id": node_id,
            "owner_run_id": f"RUN-OWNER-{node_id}",
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "scope_allowlist": copy.deepcopy(node["scope_allowlist"]),
            "forbidden_scope": copy.deepcopy(node["forbidden_scope"]),
            "scope_sha256": _scope_sha256(node),
            "tool_allowlist": ["callback"],
            "network_policy": "deny",
            "workspace_policy": "node_scope",
            "workspace_realpath": str(workspace / "scope" / node_id),
            "not_before": "2026-08-22T09:59:00Z",
            "issued_at": "2026-08-22T10:00:00Z",
            "expires_at": "2026-08-22T11:00:00Z",
            "freshness_state": "current",
            "permission_effect": "local_execution",
            "attestation_ref": None,
        },
        "receipt_sha256",
    )


def _capability_request(
    compiled_graph: dict[str, object],
    node_id: str,
    context: dict[str, object],
    capability: dict[str, object],
    *,
    run_id: str,
    attempt: int,
) -> dict[str, object]:
    node = next(item for item in compiled_graph["nodes"] if item["node_id"] == node_id)
    return _with_self_digest(
        {
            "schema_version": "goal-teams-host-capability-request-v2.65",
            "run_id": run_id,
            "node_id": node_id,
            "task_id": node["task_refs"][0],
            "attempt": attempt,
            "action_ref": node["action_ref"],
            "owner_run_id": f"RUN-OWNER-{node_id}",
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "scope_sha256": _scope_sha256(node),
            "context_bundle_sha256": context["bundle_sha256"],
            "capability_receipt_sha256": capability["receipt_sha256"],
            "requested_at": "2026-08-22T10:00:02Z",
        },
        "request_sha256",
    )


def _capability_decision(
    request: dict[str, object],
    capability: dict[str, object],
) -> dict[str, object]:
    return _with_self_digest(
        {
            "schema_version": "goal-teams-host-capability-decision-v2.65",
            "verified": True,
            "issuer": capability["issuer"],
            "issuer_key_id": capability["issuer_key_id"],
            "issuer_assurance": capability["issuer_assurance"],
            "actor_relationship": capability["actor_relationship"],
            "proof_strength": capability["proof_strength"],
            "permission_effect": capability["permission_effect"],
            "freshness_state": capability["freshness_state"],
            "scope_sha256": capability["scope_sha256"],
            "node_id": capability["node_id"],
            "capability_receipt_sha256": capability["receipt_sha256"],
            "request_sha256": request["request_sha256"],
            "reason_code": "verified_by_callback_fixture",
        },
        "decision_sha256",
    )


def _member_packet(
    compiled_graph: dict[str, object],
    node_id: str,
    context: dict[str, object],
    context_validation: dict[str, object],
    capability: dict[str, object],
    request: dict[str, object],
    decision: dict[str, object],
) -> dict[str, object]:
    node = next(item for item in compiled_graph["nodes"] if item["node_id"] == node_id)
    return _with_self_digest(
        {
            "schema_version": "goal-teams-member-packet-v2.65",
            "packet_id": f"PACKET-{node_id}",
            "graph_id": compiled_graph["graph_id"],
            "graph_revision": compiled_graph["graph_revision"],
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "plan_id": compiled_graph["plan_binding"]["plan_id"],
            "plan_revision": compiled_graph["plan_binding"]["plan_revision"],
            "task_exact_set_sha256": compiled_graph["plan_binding"][
                "task_exact_set_sha256"
            ],
            "node_id": node_id,
            "task_id": node["task_refs"][0],
            "owner_identity": node["owner_identity"],
            "owner_run_id": f"RUN-OWNER-{node_id}",
            "validator_identity": node["validator_identity"],
            "validator_run_id": f"RUN-VALIDATOR-{node_id}",
            "action_ref": node["action_ref"],
            "scope_sha256": _scope_sha256(node),
            "context_bundle_sha256": context["bundle_sha256"],
            "context_validation_receipt_sha256": context_validation["receipt_sha256"],
            "capability_receipt_sha256": capability["receipt_sha256"],
            "capability_request_sha256": request["request_sha256"],
            "capability_decision_sha256": decision["decision_sha256"],
            "issued_at": "2026-08-22T10:00:03Z",
        },
        "packet_sha256",
    )


def _dispatch_evidence(
    compiled_graph: dict[str, object],
    run_id: str,
    node_id: str,
    workspace: Path,
) -> dict[str, dict[str, object]]:
    context, context_validation = _context_bundle(compiled_graph, node_id)
    capability = _capability(compiled_graph, node_id, workspace)
    request = _capability_request(
        compiled_graph,
        node_id,
        context,
        capability,
        run_id=run_id,
        attempt=1,
    )
    decision = _capability_decision(request, capability)
    packet = _member_packet(
        compiled_graph,
        node_id,
        context,
        context_validation,
        capability,
        request,
        decision,
    )
    return {
        "context": context,
        "context_validation": context_validation,
        "capability": capability,
        "request": request,
        "decision": decision,
        "packet": packet,
    }


def _artifact(
    compiled_graph: dict[str, object],
    run_id: str,
    node_id: str,
    attempt: int,
) -> dict[str, object]:
    return _with_self_digest(
        {
            "schema_version": "goal-teams-artifact-receipt-v2.65",
            "receipt_id": f"ARTIFACT-{run_id}-{node_id}-{attempt}",
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "run_id": run_id,
            "node_id": node_id,
            "attempt": attempt,
            "artifact_id": f"artifact:{node_id}:{attempt}",
            "output_port_id": f"out:{node_id}",
            "schema_ref": "schema:artifact:v1",
            "artifact_sha256": hashlib.sha256(
                f"artifact:{run_id}:{node_id}:{attempt}".encode("utf-8")
            ).hexdigest(),
            "source_revision": "candidate:c145b713",
            "freshness_state": "current",
            "sensitivity": "internal",
            "evidence_refs": [f"evidence:artifact:{node_id}"],
            "issued_at": "2026-08-22T10:00:10Z",
        },
        "receipt_sha256",
    )


def _validation_receipt(
    compiled_graph: dict[str, object],
    run_id: str,
    node_id: str,
    artifacts: list[dict[str, object]],
) -> dict[str, object]:
    node = next(item for item in compiled_graph["nodes"] if item["node_id"] == node_id)
    return _with_self_digest(
        {
            "schema_version": "goal-teams-node-validation-receipt-v2.65",
            "receipt_id": f"VALIDATION-{run_id}-{node_id}",
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "node_id": node_id,
            "task_id": node["task_refs"][0],
            "attempt": 1,
            "observed_outcome": "completed",
            "validation_state": "passed",
            "owner_run_id": f"RUN-OWNER-{node_id}",
            "validator_identity": node["validator_identity"],
            "validator_run_id": f"RUN-VALIDATOR-{node_id}",
            "actor_relationship": "structurally_separate",
            "artifact_receipt_sha256s": [
                artifact["receipt_sha256"] for artifact in artifacts
            ],
            "evidence_refs": [f"evidence:validation:{node_id}"],
            "issued_at": "2026-08-22T10:00:11Z",
        },
        "receipt_sha256",
    )


def _gate_receipt(
    compiled_graph: dict[str, object],
    run_id: str,
) -> dict[str, object]:
    return _with_self_digest(
        {
            "schema_version": "goal-teams-gate-receipt-v2.65",
            "receipt_id": "GATE-JOIN-PASSED",
            "graph_contract_sha256": compiled_graph["receipt_sha256"],
            "run_id": run_id,
            "gate_id": "gate:join-evidence",
            "gate_type": "evidence",
            "decision": "passed",
            "authority_identity": "validator:JOIN",
            "actor_relationship": "structurally_separate",
            "evidence_refs": ["evidence:gate:validator-receipt"],
            "observed_facts": {"validator_receipt": SHA["5"]},
            "issued_at": "2026-08-22T10:00:12Z",
            "expires_at": "2026-08-22T11:00:00Z",
        },
        "receipt_sha256",
    )


def _approval_receipt(
    compiled_graph: dict[str, object],
    node_id: str,
    *,
    interrupt_id: str,
    issuer: str = "external-human-authority",
    scope_sha256: str | None = None,
    expires_at: str = "2026-08-22T10:05:00Z",
) -> dict[str, object]:
    node = next(item for item in compiled_graph["nodes"] if item["node_id"] == node_id)
    return _with_self_digest(
        {
            "schema_version": "goal-teams-host-approval-receipt-v2.65",
            "approval_id": f"APPROVAL-{node_id}-{interrupt_id}",
            "issuer": issuer,
            "issuer_key_id": f"{issuer}:key:1",
            "issuer_assurance": "externally_attested",
            "actor_relationship": "independent",
            "proof_strength": "externally_attested",
            "interrupt_id": interrupt_id,
            "gate_id": f"gate:human:{node_id}",
            "scope_sha256": scope_sha256 or _scope_sha256(node),
            "decision": "approve",
            "not_before": "2026-08-22T10:00:00Z",
            "issued_at": "2026-08-22T10:01:01Z",
            "expires_at": expires_at,
            "permission_effect": "local_execution",
            "attestation_ref": f"external-attestation:{node_id}:{interrupt_id}",
        },
        "receipt_sha256",
    )


def _make_event(
    runtime: Any,
    *,
    compiled_graph: dict[str, object],
    run_id: str,
    event_seq: int,
    event_type: str,
    node_id: str | None,
    attempt: int,
    previous_event_sha256: str,
    payload: dict[str, object],
    actor_identity: str,
) -> dict[str, object]:
    return runtime.make_graph_event(
        run_id=run_id,
        event_id=f"EVENT-{run_id}-{event_seq}",
        event_seq=event_seq,
        event_type=event_type,
        node_id=node_id,
        attempt=attempt,
        cas_base_revision=event_seq - 1,
        previous_event_sha256=previous_event_sha256,
        bindings=_bindings(compiled_graph),
        payload=payload,
        evidence_refs=[f"evidence:event:{event_seq}"],
        actor_identity=actor_identity,
        actor_relationship="authorized_writer",
        occurred_at=f"2026-08-22T10:01:{event_seq:02d}Z",
    )


def _run_created(
    runtime: Any,
    compiled_graph: dict[str, object],
    run_id: str,
) -> dict[str, object]:
    return _make_event(
        runtime,
        compiled_graph=compiled_graph,
        run_id=run_id,
        event_seq=1,
        event_type="run.created",
        node_id=None,
        attempt=0,
        previous_event_sha256=ZERO_SHA256,
        payload={"graph_receipt_sha256": compiled_graph["receipt_sha256"]},
        actor_identity="goal_lead",
    )


def _successful_node_events(
    runtime: Any,
    compiled_graph: dict[str, object],
    run_id: str,
    node_id: str,
    *,
    start_seq: int,
    previous_event_sha256: str,
    workspace: Path,
    include_artifact: bool = True,
    include_validation: bool = True,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    dispatch_evidence = _dispatch_evidence(
        compiled_graph,
        run_id,
        node_id,
        workspace,
    )
    artifact = _artifact(compiled_graph, run_id, node_id, 1)
    artifact_receipts = [artifact] if include_artifact else []
    validation = _validation_receipt(
        compiled_graph,
        run_id,
        node_id,
        artifact_receipts,
    )
    specs = [
        (
            "node.ready",
            {
                "satisfied_edge_ids": [],
                "fan_in_mode": "root",
                "required_edge_count": 0,
                "satisfied_edge_count": 0,
            },
            "goal_lead",
        ),
        (
            "node.claimed",
            {
                "worker_id": f"WORKER-{node_id}",
                "lease_id": f"LEASE-{node_id}-1",
                "lease_expires_at": "2026-08-22T10:10:00Z",
            },
            "goal_lead",
        ),
        (
            "node.started",
            {
                "owner_run_id": f"RUN-OWNER-{node_id}",
                "validator_run_id": f"RUN-VALIDATOR-{node_id}",
                "member_packet": dispatch_evidence["packet"],
                "context_bundle_sha256": dispatch_evidence["context"][
                    "bundle_sha256"
                ],
                "capability_receipt": dispatch_evidence["capability"],
                "capability_request": dispatch_evidence["request"],
                "capability_decision": dispatch_evidence["decision"],
                "host_handle_id": f"HANDLE-{node_id}-1",
            },
            f"RUN-OWNER-{node_id}",
        ),
        (
            "node.outcome_recorded",
            {
                "outcome": "completed",
                "owner_run_id": f"RUN-OWNER-{node_id}",
                "artifact_receipts": artifact_receipts,
            },
            f"RUN-OWNER-{node_id}",
        ),
    ]
    if include_validation:
        specs.append(
            (
                "node.validation_recorded",
                {
                    "validation_state": "passed",
                    "validator_run_id": f"RUN-VALIDATOR-{node_id}",
                    "validation_receipt": validation,
                    "observed_outcome": "completed",
                },
                f"RUN-VALIDATOR-{node_id}",
            )
        )
    events: list[dict[str, object]] = []
    previous = previous_event_sha256
    for offset, (event_type, payload, actor) in enumerate(specs):
        event = _make_event(
            runtime,
            compiled_graph=compiled_graph,
            run_id=run_id,
            event_seq=start_seq + offset,
            event_type=event_type,
            node_id=node_id,
            attempt=1,
            previous_event_sha256=previous,
            payload=payload,
            actor_identity=actor,
        )
        events.append(event)
        previous = event["event_sha256"]
    return events, artifact


def _dispatch_inputs(
    compiled_graph: dict[str, object],
    workspace: Path,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for node_id in ("A", "B"):
        context, validation = _context_bundle(compiled_graph, node_id)
        result[node_id] = {
            "worker_id": f"WORKER-{node_id}",
            "lease_seconds": 30,
            "owner_run_id": f"RUN-OWNER-{node_id}",
            "validator_run_id": f"RUN-VALIDATOR-{node_id}",
            "context_bundle": context,
            "context_validation_receipt": validation,
            "capability_receipt": _capability(
                compiled_graph,
                node_id,
                workspace,
            ),
            "idempotency_key": f"IDEMPOTENCY-{node_id}-1",
        }
    return result


class _ExternalApprovalHost:
    @property
    def adapter_id(self) -> str:
        return "external-approval-fixture"

    @property
    def proof_strength(self) -> str:
        return "externally_attested"

    @property
    def trusted_issuer_ids(self) -> frozenset[str]:
        return frozenset({"external-human-authority"})

    def verify_capability(
        self,
        request: dict[str, object],
        capability_receipt: dict[str, object],
    ) -> dict[str, object]:
        return _capability_decision(request, capability_receipt)

    def spawn(self, dispatch: dict[str, object]) -> dict[str, object]:
        raise AssertionError("HITL fixture does not spawn")

    def wait(
        self,
        handle: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> dict[str, object]:
        raise AssertionError("HITL fixture does not wait")

    def cancel(self, handle: dict[str, object]) -> dict[str, object]:
        raise AssertionError("HITL fixture does not cancel")

    def verify_approval(
        self,
        interrupt: dict[str, object],
        approval_receipt: dict[str, object],
    ) -> dict[str, object]:
        return _with_self_digest(
            {
                "schema_version": "goal-teams-host-approval-decision-v2.65",
                "verified": True,
                "issuer": approval_receipt["issuer"],
                "issuer_key_id": approval_receipt["issuer_key_id"],
                "issuer_assurance": approval_receipt["issuer_assurance"],
                "actor_relationship": approval_receipt["actor_relationship"],
                "proof_strength": approval_receipt["proof_strength"],
                "permission_effect": approval_receipt["permission_effect"],
                "freshness_state": "current",
                "scope_sha256": approval_receipt["scope_sha256"],
                "interrupt_id": interrupt["interrupt_id"],
                "approval_receipt_sha256": approval_receipt["receipt_sha256"],
                "expires_at": approval_receipt["expires_at"],
                "reason_code": "verified_external_approval",
            },
            "decision_sha256",
        )


class TestV265GraphRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp.name).resolve()
        self.db_path = self.runtime_root / "runtime-v265.sqlite3"
        self.workspace = self.runtime_root / "workspace"
        for node_id in ("A", "B", "JOIN"):
            (self.workspace / "scope" / node_id).mkdir(parents=True, exist_ok=True)
        self.compiled_graph = _compiled_graph()
        self.bindings = _bindings(self.compiled_graph)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _store(self) -> Any:
        runtime_store = _target("scripts.v265.runtime_store")
        return runtime_store.SQLiteRuntimeStore(
            self.db_path,
            runtime_root=self.runtime_root,
            busy_timeout_ms=5000,
        )

    def _callback_adapter(
        self,
        callbacks: dict[str, Any],
        *,
        max_workers: int,
    ) -> Any:
        host = _target("scripts.v265.host_adapter")
        return host.CallbackHostAdapter(
            callbacks,
            adapter_id="callback_fixture",
            max_workers=max_workers,
            clock=lambda: "2026-08-22T10:00:30Z",
        )

    def _controller(self, store: Any, adapter: Any, *, max_workers: int = 2) -> Any:
        controller = _target("scripts.v265.runtime_controller")
        return controller.RuntimeController(
            compiled_graph=self.compiled_graph,
            store=store,
            host_adapter=adapter,
            run_bindings=self.bindings,
            max_workers=max_workers,
        )

    def _activate_node(self, store: Any, run_id: str, node_id: str = "A") -> None:
        runtime = _target("scripts.v265.graph_runtime")
        head = store.read_run_head(run_id)
        previous = head["last_event_sha256"]
        ready = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id=run_id,
            event_seq=head["revision"] + 1,
            event_type="node.ready",
            node_id=node_id,
            attempt=1,
            previous_event_sha256=previous,
            payload={
                "satisfied_edge_ids": [],
                "fan_in_mode": "root",
                "required_edge_count": 0,
                "satisfied_edge_count": 0,
            },
            actor_identity="goal_lead",
        )
        store.append_event(run_id, ready, expected_revision=head["revision"])
        head = store.read_run_head(run_id)
        claimed = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id=run_id,
            event_seq=head["revision"] + 1,
            event_type="node.claimed",
            node_id=node_id,
            attempt=1,
            previous_event_sha256=head["last_event_sha256"],
            payload={
                "worker_id": f"WORKER-{node_id}",
                "lease_id": f"LEASE-{node_id}-1",
                "lease_expires_at": "2026-08-22T10:10:00Z",
            },
            actor_identity="goal_lead",
        )
        store.claim_lease(run_id, claimed, expected_revision=head["revision"])
        head = store.read_run_head(run_id)
        dispatch_evidence = _dispatch_evidence(
            self.compiled_graph,
            run_id,
            node_id,
            self.workspace,
        )
        started = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id=run_id,
            event_seq=head["revision"] + 1,
            event_type="node.started",
            node_id=node_id,
            attempt=1,
            previous_event_sha256=head["last_event_sha256"],
            payload={
                "owner_run_id": f"RUN-OWNER-{node_id}",
                "validator_run_id": f"RUN-VALIDATOR-{node_id}",
                "member_packet": dispatch_evidence["packet"],
                "context_bundle_sha256": dispatch_evidence["context"][
                    "bundle_sha256"
                ],
                "capability_receipt": dispatch_evidence["capability"],
                "capability_request": dispatch_evidence["request"],
                "capability_decision": dispatch_evidence["decision"],
                "host_handle_id": f"HANDLE-{node_id}-1",
            },
            actor_identity=f"RUN-OWNER-{node_id}",
        )
        store.record_attempt(run_id, started, expected_revision=head["revision"])

    def test_predecessor_validation_gate_and_data_are_enforced_from_events(self) -> None:
        runtime = _target("scripts.v265.graph_runtime")
        run_id = "RUN-PREDECESSOR-BYPASS"
        created = _run_created(runtime, self.compiled_graph, run_id)
        roots = runtime.evaluate_next(
            self.compiled_graph,
            [created],
            expected_bindings=self.bindings,
            now="2026-08-22T10:01:01Z",
        )
        self.assertEqual(["A", "B"], [item["node_id"] for item in roots])

        bypass = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id=run_id,
            event_seq=2,
            event_type="node.ready",
            node_id="JOIN",
            attempt=1,
            previous_event_sha256=created["event_sha256"],
            payload={
                "satisfied_edge_ids": [
                    "data:A:JOIN",
                    "data:B:JOIN",
                    "dep:A:JOIN",
                    "dep:B:JOIN",
                ],
                "fan_in_mode": "all",
                "required_edge_count": 4,
                "satisfied_edge_count": 4,
            },
            actor_identity="goal_lead",
        )
        with self.assertRaises(runtime.GraphRuntimeError) as caught:
            runtime.reduce_graph_events(
                self.compiled_graph,
                [created, bypass],
                expected_bindings=self.bindings,
            )
        self.assertEqual("E_V265_RUNTIME_PREDECESSOR", caught.exception.code)

        def pair_events(
            pair_run_id: str,
            *,
            include_a_artifact: bool,
            include_a_validation: bool,
            graph: dict[str, object] | None = None,
        ) -> list[dict[str, object]]:
            selected_graph = graph or self.compiled_graph
            pair_created = _run_created(runtime, selected_graph, pair_run_id)
            pair: list[dict[str, object]] = [pair_created]
            a_events, _ = _successful_node_events(
                runtime,
                selected_graph,
                pair_run_id,
                "A",
                start_seq=2,
                previous_event_sha256=pair_created["event_sha256"],
                workspace=self.workspace,
                include_artifact=include_a_artifact,
                include_validation=include_a_validation,
            )
            pair.extend(a_events)
            b_events, _ = _successful_node_events(
                runtime,
                selected_graph,
                pair_run_id,
                "B",
                start_seq=len(pair) + 1,
                previous_event_sha256=pair[-1]["event_sha256"],
                workspace=self.workspace,
            )
            pair.extend(b_events)
            return pair

        capability_created = _run_created(
            runtime,
            self.compiled_graph,
            "RUN-CAPABILITY-TAMPER",
        )
        capability_events, _ = _successful_node_events(
            runtime,
            self.compiled_graph,
            "RUN-CAPABILITY-TAMPER",
            "A",
            start_seq=2,
            previous_event_sha256=capability_created["event_sha256"],
            workspace=self.workspace,
        )
        capability_prefix = [capability_created, *capability_events[:3]]
        tampered_started = copy.deepcopy(capability_prefix[-1])
        tampered_started["payload"]["capability_receipt"]["scope_sha256"] = SHA["f"]
        capability_prefix[-1] = _rehash_event(tampered_started)
        with self.assertRaises(runtime.GraphRuntimeError) as caught:
            runtime.reduce_graph_events(
                self.compiled_graph,
                capability_prefix,
                expected_bindings=self.bindings,
            )
        self.assertEqual("E_V265_MEMBER_CAPABILITY", caught.exception.code)

        identity_created = _run_created(
            runtime,
            self.compiled_graph,
            "RUN-VALIDATOR-IDENTITY",
        )
        identity_events, _ = _successful_node_events(
            runtime,
            self.compiled_graph,
            "RUN-VALIDATOR-IDENTITY",
            "A",
            start_seq=2,
            previous_event_sha256=identity_created["event_sha256"],
            workspace=self.workspace,
        )
        identity_chain = [identity_created, *identity_events]
        bad_validation_event = copy.deepcopy(identity_chain[-1])
        bad_validation = bad_validation_event["payload"]["validation_receipt"]
        bad_validation["validator_identity"] = "validator:OTHER"
        bad_validation["receipt_sha256"] = _canonical_sha256(
            {
                key: value
                for key, value in bad_validation.items()
                if key != "receipt_sha256"
            }
        )
        identity_chain[-1] = _rehash_event(bad_validation_event)
        with self.assertRaises(runtime.GraphRuntimeError) as caught:
            runtime.reduce_graph_events(
                self.compiled_graph,
                identity_chain,
                expected_bindings=self.bindings,
            )
        self.assertEqual("E_V265_RUNTIME_VALIDATOR", caught.exception.code)

        validation_missing = pair_events(
            "RUN-VALIDATION-MISSING",
            include_a_artifact=True,
            include_a_validation=False,
        )
        validation_gate = _gate_receipt(
            self.compiled_graph,
            "RUN-VALIDATION-MISSING",
        )
        validation_missing.append(
            _make_event(
                runtime,
                compiled_graph=self.compiled_graph,
                run_id="RUN-VALIDATION-MISSING",
                event_seq=len(validation_missing) + 1,
                event_type="gate.passed",
                node_id=None,
                attempt=0,
                previous_event_sha256=validation_missing[-1]["event_sha256"],
                payload={
                    "gate_id": validation_gate["gate_id"],
                    "gate_receipt": validation_gate,
                    "gate_decision_sha256": validation_gate["receipt_sha256"],
                    "decision": "passed",
                },
                actor_identity="validator:JOIN",
            )
        )
        validation_projection = runtime.reduce_graph_events(
            self.compiled_graph,
            validation_missing,
            expected_bindings=self.bindings,
        )
        self.assertEqual(
            "not_run",
            validation_projection["nodes"]["A"]["validation_state"],
        )
        self.assertEqual(
            [],
            runtime.evaluate_next(
                self.compiled_graph,
                validation_missing,
                expected_bindings=self.bindings,
                now="2026-08-22T10:01:12Z",
            ),
        )

        optional_data_graph = _compiled_graph(optional_data_output=True)
        optional_data_bindings = _bindings(optional_data_graph)
        data_missing = pair_events(
            "RUN-DATA-MISSING",
            include_a_artifact=False,
            include_a_validation=True,
            graph=optional_data_graph,
        )
        data_gate = _gate_receipt(optional_data_graph, "RUN-DATA-MISSING")
        data_gate_event = _make_event(
            runtime,
            compiled_graph=optional_data_graph,
            run_id="RUN-DATA-MISSING",
            event_seq=len(data_missing) + 1,
            event_type="gate.passed",
            node_id=None,
            attempt=0,
            previous_event_sha256=data_missing[-1]["event_sha256"],
            payload={
                "gate_id": data_gate["gate_id"],
                "gate_receipt": data_gate,
                "gate_decision_sha256": data_gate["receipt_sha256"],
                "decision": "passed",
            },
            actor_identity="validator:JOIN",
        )
        data_missing.append(data_gate_event)
        data_projection = runtime.reduce_graph_events(
            optional_data_graph,
            data_missing,
            expected_bindings=optional_data_bindings,
        )
        self.assertEqual("passed", data_projection["nodes"]["A"]["validation_state"])
        self.assertEqual([], data_projection["nodes"]["A"]["artifact_receipts"])
        self.assertEqual(
            [],
            runtime.evaluate_next(
                optional_data_graph,
                data_missing,
                expected_bindings=optional_data_bindings,
                now="2026-08-22T10:01:13Z",
            ),
        )

        events = pair_events(
            "RUN-POSITIVE",
            include_a_artifact=True,
            include_a_validation=True,
        )
        self.assertEqual(
            [],
            runtime.evaluate_next(
                self.compiled_graph,
                events,
                expected_bindings=self.bindings,
                now="2026-08-22T10:01:14Z",
            ),
        )
        gate = _gate_receipt(self.compiled_graph, "RUN-POSITIVE")
        expired_gate = copy.deepcopy(gate)
        expired_gate["expires_at"] = "2026-08-22T10:00:13Z"
        expired_gate["receipt_sha256"] = _canonical_sha256(
            {
                key: value
                for key, value in expired_gate.items()
                if key != "receipt_sha256"
            }
        )
        expired_gate_event = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id="RUN-POSITIVE",
            event_seq=len(events) + 1,
            event_type="gate.passed",
            node_id=None,
            attempt=0,
            previous_event_sha256=events[-1]["event_sha256"],
            payload={
                "gate_id": expired_gate["gate_id"],
                "gate_receipt": expired_gate,
                "gate_decision_sha256": expired_gate["receipt_sha256"],
                "decision": "passed",
            },
            actor_identity="validator:JOIN",
        )
        with self.assertRaises(runtime.GraphRuntimeError) as caught:
            runtime.reduce_graph_events(
                self.compiled_graph,
                [*events, expired_gate_event],
                expected_bindings=self.bindings,
            )
        self.assertEqual("E_V265_RUNTIME_GATE", caught.exception.code)

        gate_event = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id="RUN-POSITIVE",
            event_seq=len(events) + 1,
            event_type="gate.passed",
            node_id=None,
            attempt=0,
            previous_event_sha256=events[-1]["event_sha256"],
            payload={
                "gate_id": gate["gate_id"],
                "gate_receipt": gate,
                "gate_decision_sha256": gate["receipt_sha256"],
                "decision": "passed",
            },
            actor_identity="validator:JOIN",
        )
        events.append(gate_event)
        positive_projection = runtime.reduce_graph_events(
            self.compiled_graph,
            events,
            expected_bindings=self.bindings,
        )
        self.assertEqual(
            "passed",
            positive_projection["nodes"]["A"]["validation_state"],
        )
        self.assertTrue(positive_projection["nodes"]["A"]["artifact_receipts"])
        ready = runtime.evaluate_next(
            self.compiled_graph,
            events,
            expected_bindings=self.bindings,
            now="2026-08-22T10:01:15Z",
        )
        self.assertEqual(["JOIN"], [item["node_id"] for item in ready])

    def test_two_root_nodes_execute_in_one_bounded_concurrent_wave(self) -> None:
        barrier = threading.Barrier(2, timeout=5)
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def callback(dispatch: dict[str, object]) -> dict[str, object]:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                barrier.wait()
                return {
                    "outcome": "completed",
                    "artifact_receipts": [
                        _artifact(
                            self.compiled_graph,
                            str(dispatch["run_id"]),
                            str(dispatch["node_id"]),
                            int(dispatch["attempt"]),
                        )
                    ],
                    "evidence_refs": [f"evidence:callback:{dispatch['node_id']}"],
                    "side_effects": [],
                }
            finally:
                with lock:
                    active -= 1

        adapter = self._callback_adapter(
            {"action:A": callback, "action:B": callback},
            max_workers=2,
        )
        store = self._store()
        try:
            controller = self._controller(store, adapter)
            controller.create_run(run_id="RUN-WAVE", created_at="2026-08-22T10:00:00Z")
            head = store.read_run_head("RUN-WAVE")
            wave = controller.run_ready_wave(
                run_id="RUN-WAVE",
                dispatch_inputs=_dispatch_inputs(self.compiled_graph, self.workspace),
                now="2026-08-22T10:00:02Z",
                expected_revision=head["revision"],
            )
            self.assertEqual(["A", "B"], wave["ready_node_ids"])
            self.assertEqual(["A", "B"], wave["completed_node_ids"])
            self.assertEqual(2, maximum_active)
            projection = _target("scripts.v265.graph_runtime").reduce_graph_events(
                self.compiled_graph,
                store.load_events("RUN-WAVE"),
                expected_bindings=self.bindings,
            )
            self.assertEqual("not_run", projection["nodes"]["A"]["validation_state"])
            self.assertEqual("not_run", projection["nodes"]["B"]["validation_state"])
        finally:
            store.close()

    def test_store_cas_lease_expiry_and_attempt_budget_fail_closed(self) -> None:
        runtime = _target("scripts.v265.graph_runtime")
        adapter = self._callback_adapter({}, max_workers=1)
        store = self._store()
        try:
            store.create_run(
                "RUN-LEASE",
                self.compiled_graph,
                self.bindings,
                created_at="2026-08-22T10:00:00Z",
            )
            head = store.read_run_head("RUN-LEASE")
            forged = _make_event(
                runtime,
                compiled_graph=self.compiled_graph,
                run_id="RUN-LEASE",
                event_seq=head["revision"] + 1,
                event_type="node.ready",
                node_id="A",
                attempt=1,
                previous_event_sha256=head["last_event_sha256"],
                payload={
                    "satisfied_edge_ids": [],
                    "fan_in_mode": "root",
                    "required_edge_count": 0,
                    "satisfied_edge_count": 0,
                },
                actor_identity="goal_lead",
            )
            store_module = _target("scripts.v265.runtime_store")
            with self.assertRaises(store_module.RuntimeStoreError) as caught:
                store.append_event("RUN-LEASE", forged, expected_revision=0)
            self.assertEqual("E_V265_STORE_CAS", caught.exception.code)

            controller = self._controller(store, adapter, max_workers=1)
            head = store.read_run_head("RUN-LEASE")
            ready = _make_event(
                runtime,
                compiled_graph=self.compiled_graph,
                run_id="RUN-LEASE",
                event_seq=head["revision"] + 1,
                event_type="node.ready",
                node_id="A",
                attempt=1,
                previous_event_sha256=head["last_event_sha256"],
                payload={
                    "satisfied_edge_ids": [],
                    "fan_in_mode": "root",
                    "required_edge_count": 0,
                    "satisfied_edge_count": 0,
                },
                actor_identity="goal_lead",
            )
            store.append_event(
                "RUN-LEASE",
                ready,
                expected_revision=head["revision"],
            )
            head = store.read_run_head("RUN-LEASE")
            controller.claim_node(
                run_id="RUN-LEASE",
                node_id="A",
                worker_id="WORKER-A-1",
                lease_seconds=1,
                now="2026-08-22T10:00:01Z",
                expected_revision=head["revision"],
            )
            first_recovery = controller.recover(
                run_id="RUN-LEASE",
                now="2026-08-22T10:00:03Z",
            )
            self.assertEqual(["A"], first_recovery["expired_lease_node_ids"])
            head = store.read_run_head("RUN-LEASE")
            controller.claim_node(
                run_id="RUN-LEASE",
                node_id="A",
                worker_id="WORKER-A-2",
                lease_seconds=1,
                now="2026-08-22T10:00:04Z",
                expected_revision=head["revision"],
            )
            controller.recover(run_id="RUN-LEASE", now="2026-08-22T10:00:06Z")
            head = store.read_run_head("RUN-LEASE")
            with self.assertRaises(runtime.GraphRuntimeError) as caught:
                controller.claim_node(
                    run_id="RUN-LEASE",
                    node_id="A",
                    worker_id="WORKER-A-3",
                    lease_seconds=1,
                    now="2026-08-22T10:00:07Z",
                    expected_revision=head["revision"],
                )
            self.assertEqual("E_V265_RUNTIME_ATTEMPT_BUDGET", caught.exception.code)
            self.assertEqual(
                [1, 2],
                [
                    attempt["attempt"]
                    for attempt in store.read_attempts("RUN-LEASE")
                    if attempt["node_id"] == "A"
                ],
            )
        finally:
            store.close()

    def test_real_sqlite_close_reopen_restores_verified_checkpoint(self) -> None:
        runtime_store = _target("scripts.v265.runtime_store")
        with self.assertRaises(runtime_store.RuntimeStoreError) as caught:
            runtime_store.SQLiteRuntimeStore(
                ":memory:",
                runtime_root=self.runtime_root,
            )
        self.assertEqual("E_V265_STORE_PATH", caught.exception.code)

        store = self._store()
        store.create_run(
            "RUN-CRASH",
            self.compiled_graph,
            self.bindings,
            created_at="2026-08-22T10:00:00Z",
        )
        runtime = _target("scripts.v265.graph_runtime")
        projection = runtime.reduce_graph_events(
            self.compiled_graph,
            store.load_events("RUN-CRASH"),
            expected_bindings=self.bindings,
        )
        head = store.read_run_head("RUN-CRASH")
        store.save_checkpoint(
            "RUN-CRASH",
            projection,
            expected_revision=head["revision"],
            created_at="2026-08-22T10:00:01Z",
        )
        expected_projection_sha256 = projection["projection_sha256"]
        store.close()

        reopened = self._store()
        try:
            checkpoint = reopened.load_checkpoint("RUN-CRASH")
            self.assertEqual(expected_projection_sha256, checkpoint["projection_sha256"])
            self.assertEqual(
                self.compiled_graph,
                reopened.read_run_head("RUN-CRASH")["compiled_graph"],
            )
            verification = reopened.verify_run("RUN-CRASH")
            self.assertTrue(verification["verified"])
            self.assertEqual(expected_projection_sha256, verification["projection_sha256"])
        finally:
            reopened.close()

        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual("wal", connection.execute("PRAGMA journal_mode").fetchone()[0])
            self.assertEqual(2, connection.execute("PRAGMA synchronous").fetchone()[0])
            self.assertEqual(265, connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()

    def test_corrupt_sqlite_event_or_index_never_verifies(self) -> None:
        runtime_store = _target("scripts.v265.runtime_store")
        store = self._store()
        store.create_run(
            "RUN-CORRUPT",
            self.compiled_graph,
            self.bindings,
            created_at="2026-08-22T10:00:00Z",
        )
        store.close()
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE events SET event_json = ? WHERE run_id = ? AND event_seq = 1",
                ("{}", "RUN-CORRUPT"),
            )
            connection.commit()
        finally:
            connection.close()

        reopened = self._store()
        try:
            with self.assertRaises(runtime_store.RuntimeStoreError) as caught:
                reopened.verify_run("RUN-CORRUPT")
            self.assertEqual("E_V265_STORE_CORRUPT", caught.exception.code)
        finally:
            reopened.close()

    def test_confirmed_idempotency_key_does_not_execute_again_after_reopen(self) -> None:
        runtime = _target("scripts.v265.graph_runtime")
        store = self._store()
        store.create_run(
            "RUN-IDEMPOTENT",
            self.compiled_graph,
            self.bindings,
            created_at="2026-08-22T10:00:00Z",
        )
        self._activate_node(store, "RUN-IDEMPOTENT")
        head = store.read_run_head("RUN-IDEMPOTENT")
        action = next(item for item in self.compiled_graph["actions"] if item["action_id"] == "action:A")
        intent = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id="RUN-IDEMPOTENT",
            event_seq=head["revision"] + 1,
            event_type="side_effect.intent",
            node_id="A",
            attempt=1,
            previous_event_sha256=head["last_event_sha256"],
            payload={
                "idempotency_key": "KEY-A-1",
                "action_sha256": _canonical_sha256(action),
            },
            actor_identity="RUN-OWNER-A",
        )
        reserved = store.reserve_idempotency_key(
            "RUN-IDEMPOTENT",
            "A",
            "KEY-A-1",
            intent,
            expected_revision=head["revision"],
        )
        self.assertTrue(reserved["execute"])
        head = store.read_run_head("RUN-IDEMPOTENT")
        confirmation = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id="RUN-IDEMPOTENT",
            event_seq=head["revision"] + 1,
            event_type="side_effect.confirmed",
            node_id="A",
            attempt=1,
            previous_event_sha256=head["last_event_sha256"],
            payload={
                "idempotency_key": "KEY-A-1",
                "result_digest": SHA["5"],
                "readback_receipt_sha256": SHA["6"],
            },
            actor_identity="RUN-OWNER-A",
        )
        store.confirm_idempotency_key(
            "RUN-IDEMPOTENT",
            "KEY-A-1",
            SHA["5"],
            confirmation,
            expected_revision=head["revision"],
        )
        store.close()

        reopened = self._store()
        try:
            head = reopened.read_run_head("RUN-IDEMPOTENT")
            duplicate = _make_event(
                runtime,
                compiled_graph=self.compiled_graph,
                run_id="RUN-IDEMPOTENT",
                event_seq=head["revision"] + 1,
                event_type="side_effect.intent",
                node_id="A",
                attempt=2,
                previous_event_sha256=head["last_event_sha256"],
                payload={
                    "idempotency_key": "KEY-A-1",
                    "action_sha256": _canonical_sha256(action),
                },
                actor_identity="RUN-OWNER-A",
            )
            decision = reopened.reserve_idempotency_key(
                "RUN-IDEMPOTENT",
                "A",
                "KEY-A-1",
                duplicate,
                expected_revision=head["revision"],
            )
            callback_count = 0
            if decision["execute"]:
                callback_count += 1
            self.assertFalse(decision["execute"])
            self.assertEqual(SHA["5"], decision["result_digest"])
            self.assertEqual(0, callback_count)
        finally:
            reopened.close()

    def test_unknown_side_effect_result_requires_reconciliation_not_replay(self) -> None:
        runtime = _target("scripts.v265.graph_runtime")
        adapter = self._callback_adapter({}, max_workers=1)
        store = self._store()
        store.create_run(
            "RUN-UNKNOWN",
            self.compiled_graph,
            self.bindings,
            created_at="2026-08-22T10:00:00Z",
        )
        self._activate_node(store, "RUN-UNKNOWN")
        head = store.read_run_head("RUN-UNKNOWN")
        action = next(item for item in self.compiled_graph["actions"] if item["action_id"] == "action:A")
        intent = _make_event(
            runtime,
            compiled_graph=self.compiled_graph,
            run_id="RUN-UNKNOWN",
            event_seq=head["revision"] + 1,
            event_type="side_effect.intent",
            node_id="A",
            attempt=1,
            previous_event_sha256=head["last_event_sha256"],
            payload={
                "idempotency_key": "KEY-UNKNOWN",
                "action_sha256": _canonical_sha256(action),
            },
            actor_identity="RUN-OWNER-A",
        )
        store.reserve_idempotency_key(
            "RUN-UNKNOWN",
            "A",
            "KEY-UNKNOWN",
            intent,
            expected_revision=head["revision"],
        )
        store.close()

        reopened = self._store()
        try:
            recovery = self._controller(reopened, adapter, max_workers=1).recover(
                run_id="RUN-UNKNOWN",
                now="2026-08-22T10:05:00Z",
            )
            self.assertEqual(["A"], recovery["reconciliation_required_node_ids"])
            self.assertNotIn("A", recovery["ready_node_ids"])
            self.assertEqual(
                "reconciliation_required",
                reopened.get_idempotency_record("RUN-UNKNOWN", "KEY-UNKNOWN")["state"],
            )
        finally:
            reopened.close()

    def test_hitl_resume_uses_external_decision_without_widening_node_capability(self) -> None:
        runtime = _target("scripts.v265.graph_runtime")
        store = self._store()
        store.create_run(
            "RUN-HITL",
            self.compiled_graph,
            self.bindings,
            created_at="2026-08-22T10:00:00Z",
        )
        self._activate_node(store, "RUN-HITL")
        before = runtime.reduce_graph_events(
            self.compiled_graph,
            store.load_events("RUN-HITL"),
            expected_bindings=self.bindings,
        )
        original_capability = before["nodes"]["A"]["capability_receipt_sha256"]
        controller = self._controller(store, _ExternalApprovalHost(), max_workers=1)
        head = store.read_run_head("RUN-HITL")
        interrupted = controller.interrupt(
            run_id="RUN-HITL",
            node_id="A",
            gate_id="gate:human:A",
            interrupt_id="INTERRUPT-A-1",
            reason="external approval required",
            evidence_refs=["evidence:interrupt"],
            now="2026-08-22T10:01:00Z",
            expected_revision=head["revision"],
        )
        bad_approvals = {
            "issuer": _approval_receipt(
                self.compiled_graph,
                "A",
                interrupt_id="INTERRUPT-A-1",
                issuer="untrusted-human-authority",
            ),
            "scope": _approval_receipt(
                self.compiled_graph,
                "A",
                interrupt_id="INTERRUPT-A-1",
                scope_sha256=SHA["f"],
            ),
            "expiry": _approval_receipt(
                self.compiled_graph,
                "A",
                interrupt_id="INTERRUPT-A-1",
                expires_at="2026-08-22T10:01:01Z",
            ),
            "interrupt": _approval_receipt(
                self.compiled_graph,
                "A",
                interrupt_id="INTERRUPT-OTHER",
            ),
        }
        for name, bad_approval in bad_approvals.items():
            with self.subTest(binding=name):
                with self.assertRaises(runtime.GraphRuntimeError) as caught:
                    controller.resume(
                        run_id="RUN-HITL",
                        node_id="A",
                        interrupt_id="INTERRUPT-A-1",
                        approval_receipt=bad_approval,
                        now="2026-08-22T10:01:02Z",
                        expected_revision=interrupted["revision"],
                    )
                self.assertEqual("E_V265_RUNTIME_GATE", caught.exception.code)
                self.assertEqual(
                    interrupted["revision"],
                    store.read_run_head("RUN-HITL")["revision"],
                )

        approval = _approval_receipt(
            self.compiled_graph,
            "A",
            interrupt_id="INTERRUPT-A-1",
        )
        resumed = controller.resume(
            run_id="RUN-HITL",
            node_id="A",
            interrupt_id="INTERRUPT-A-1",
            approval_receipt=approval,
            now="2026-08-22T10:01:02Z",
            expected_revision=interrupted["revision"],
        )
        after = runtime.reduce_graph_events(
            self.compiled_graph,
            store.load_events("RUN-HITL"),
            expected_bindings=self.bindings,
        )
        self.assertEqual("ready", after["nodes"]["A"]["execution_state"])
        self.assertEqual(original_capability, after["nodes"]["A"]["capability_receipt_sha256"])
        self.assertRegex(after["nodes"]["A"]["approval_decision_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(resumed["revision"], store.read_run_head("RUN-HITL")["revision"])
        store.close()

    def test_callback_adapter_is_fixture_only_and_cannot_claim_external_or_hard_cancel(self) -> None:
        host = _target("scripts.v265.host_adapter")
        started = threading.Event()
        release = threading.Event()

        def callback(dispatch: dict[str, object]) -> dict[str, object]:
            started.set()
            release.wait(timeout=5)
            return {
                "outcome": "completed",
                "artifact_receipts": [
                    _artifact(
                        self.compiled_graph,
                        str(dispatch["run_id"]),
                        "A",
                        1,
                    )
                ],
                "evidence_refs": ["evidence:callback:A"],
                "side_effects": [],
            }

        adapter = host.CallbackHostAdapter(
            {"action:A": callback},
            adapter_id="callback_fixture",
            max_workers=1,
            clock=lambda: "2026-08-22T10:00:30Z",
        )
        self.assertEqual("fixture_only", adapter.proof_strength)
        context, context_validation = _context_bundle(self.compiled_graph, "A")
        capability = _capability(self.compiled_graph, "A", self.workspace)
        request = _capability_request(
            self.compiled_graph,
            "A",
            context,
            capability,
            run_id="RUN-CALLBACK",
            attempt=1,
        )
        decision = adapter.verify_capability(request, capability)
        self.assertEqual("fixture_only", decision["proof_strength"])
        self.assertEqual("local_execution", decision["permission_effect"])

        external = copy.deepcopy(capability)
        external.update(
            {
                "issuer": "external-capability-authority",
                "issuer_key_id": "external-capability-authority:key:1",
                "issuer_assurance": "externally_attested",
                "actor_relationship": "independent",
                "proof_strength": "externally_attested",
                "permission_effect": "external_side_effects",
                "attestation_ref": "external-attestation:capability:A:1",
            }
        )
        external["receipt_sha256"] = _canonical_sha256(
            {key: value for key, value in external.items() if key != "receipt_sha256"}
        )
        external_request = _capability_request(
            self.compiled_graph,
            "A",
            context,
            external,
            run_id="RUN-CALLBACK",
            attempt=1,
        )
        with self.assertRaises(host.HostAdapterError) as caught:
            adapter.verify_capability(external_request, external)
        self.assertEqual("E_V265_HOST_CAPABILITY", caught.exception.code)

        approval_graph = _compiled_graph()
        approval_interrupt = {
            "run_id": "RUN-CALLBACK",
            "interrupt_id": "INTERRUPT-CALLBACK",
            "node_id": "A",
            "gate_id": "gate:human:A",
            "state": "waiting_user",
            "approval_receipt_sha256": None,
            "updated_at": "2026-08-22T10:00:30Z",
        }
        callback_approval = _approval_receipt(
            approval_graph,
            "A",
            interrupt_id="INTERRUPT-CALLBACK",
        )
        with self.assertRaises(host.HostAdapterError) as caught:
            adapter.verify_approval(approval_interrupt, callback_approval)
        self.assertEqual("E_V265_HOST_CAPABILITY", caught.exception.code)

        member = importlib.import_module("scripts.v265.member_packet")
        packet = member.compile_member_packet(
            packet_id="PACKET-CALLBACK-A",
            compiled_graph=self.compiled_graph,
            node_id="A",
            owner_run_id="RUN-OWNER-A",
            validator_run_id="RUN-VALIDATOR-A",
            context_bundle=context,
            context_validation_receipt=context_validation,
            capability_receipt=capability,
            capability_request=request,
            capability_decision=decision,
            issued_at="2026-08-22T10:00:30Z",
        )
        dispatch = {
            "schema_version": "goal-teams-host-dispatch-v2.65",
            "run_id": "RUN-CALLBACK",
            "node_id": "A",
            "task_id": "A",
            "attempt": 1,
            "action_ref": "action:A",
            "member_packet": packet,
            "context_bundle": context,
            "capability_receipt": capability,
            "capability_decision": decision,
            "idempotency_key": "KEY-CALLBACK-A",
        }
        handle = adapter.spawn(dispatch)
        self.assertTrue(started.wait(timeout=2))
        try:
            with self.assertRaises(host.HostAdapterError) as caught:
                adapter.cancel(handle)
            self.assertEqual("E_V265_HOST_CANCEL_UNCONFIRMED", caught.exception.code)
        finally:
            release.set()
            adapter.wait(handle, timeout_seconds=5)


if __name__ == "__main__":
    unittest.main()
