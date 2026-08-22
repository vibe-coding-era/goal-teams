from __future__ import annotations

import copy
import base64
import hashlib
import importlib
import json
import unittest
from collections.abc import Callable
from typing import Any

from scripts.v250.task_plan_compiler import (
    compile_task_plan,
    validate_compiled_task_plan,
)


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


def _target(module_name: str) -> Any:
    """Fail inside each discovered test while the V2.65 target is absent."""

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
    output_consumers: list[str],
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "requirement_refs": [f"REQ-GE-265-{task_id}"],
        "consumer_refs": list(output_consumers),
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
        "budget_wu": 3,
        "attempt_budget": 2,
        "revalidation_budget": 1,
        "inputs": [{"input_id": f"input:{task_id}"}],
        "outputs": [
            {
                "output_id": f"output:{task_id}",
                "consumer_refs": list(output_consumers),
                "required": True,
            }
        ],
        "verification": [
            {
                "verification_id": f"verification:{task_id}",
                "verification_type": "behavior",
                "method": f"observe node {task_id}",
                "expected_result": f"node {task_id} produces its typed outcome",
                "evidence_refs": [f"evidence:test:{task_id}"],
            }
        ],
        "business_oracle": {
            "oracle_id": f"oracle:{task_id}",
            "oracle_type": "graph_behavior",
            "acceptance_criteria": [f"node {task_id} is independently observable"],
            "evidence_refs": [f"evidence:oracle:{task_id}"],
        },
        "exit_condition": {
            "exit_id": f"exit:{task_id}",
            "exit_type": "validated_outcome",
            "required_receipt_types": ["node_outcome", "validator_result"],
            "on_budget_exhaustion": "replan",
        },
        "failure_artifacts": [f"failure:{task_id}"],
    }


def _authoritative_plan(
    phase_sets: dict[str, list[str]] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    source = {
        "schema_version": "goal-teams-task-plan-v1",
        "plan_id": "GT-V265-GRAPH-TEST",
        "plan_revision": 1,
        "tasks": [
            _task("A", depends_on=[], output_consumers=["task:JOIN"]),
            _task("B", depends_on=[], output_consumers=["task:JOIN"]),
            _task("JOIN", depends_on=["A", "B"], output_consumers=["consumer:v265"]),
        ],
        "phase_exact_sets": phase_sets
        or {
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


def _output_port(port_id: str, consumers: list[str]) -> dict[str, object]:
    return {
        "port_id": port_id,
        "schema_ref": "schema:artifact:v1",
        "required": True,
        "sensitivity": "internal",
        "consumer_node_ids": list(consumers),
    }


def _node(task: dict[str, object]) -> dict[str, object]:
    task_id = str(task["task_id"])
    is_join = task_id == "JOIN"
    return {
        "node_id": task_id,
        "task_refs": [task_id],
        "node_type": "validation" if is_join else "action",
        "owner_identity": task["owner"],
        "validator_identity": task["validator"],
        "action_ref": f"action:{task_id}",
        "resource_refs": {
            "required": [f"resource:{task_id}:required"],
            "recommended": [],
            "generated": [f"resource:{task_id}:generated"],
            "upstream_artifacts": (
                ["resource:A:artifact", "resource:B:artifact"] if is_join else []
            ),
            "forbidden": [f"resource:{task_id}:forbidden"],
        },
        "input_ports": [_input_port("in:A"), _input_port("in:B")] if is_join else [],
        "output_ports": [
            _output_port(
                f"out:{task_id}",
                ["JOIN"] if task_id in {"A", "B"} else [],
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
    gate_ref: str | None = None,
    data_bindings: list[dict[str, object]] | None = None,
    traversal_budget: int = 0,
) -> dict[str, object]:
    return {
        "edge_id": edge_id,
        "edge_type": edge_type,
        "source_node_id": source,
        "target_node_id": target,
        "accepted_outcomes": list(accepted_outcomes or ["completed"]),
        "gate_ref": gate_ref,
        "data_bindings": copy.deepcopy(data_bindings or []),
        "traversal_budget": traversal_budget,
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
    source_plan: dict[str, object],
    compiled_plan: dict[str, object],
    validation: dict[str, object],
) -> dict[str, object]:
    resources: list[dict[str, object]] = []
    for task_id in ("A", "B", "JOIN"):
        resources.extend(
            [
                _resource(
                    f"resource:{task_id}:required",
                    resource_type="repository_file",
                    producer=None,
                    consumers=[task_id],
                ),
                _resource(
                    f"resource:{task_id}:generated",
                    resource_type="generated_context",
                    producer=task_id,
                    consumers=[task_id],
                ),
                _resource(
                    f"resource:{task_id}:forbidden",
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
        "graph_id": "GRAPH-V265-TEST",
        "graph_revision": 1,
        "plan_binding": {
            "plan_id": source_plan["plan_id"],
            "plan_revision": source_plan["plan_revision"],
            "task_exact_set_sha256": compiled_plan["task_exact_set_digest"],
            "compiled_task_plan_sha256": compiled_plan["receipt_digest"],
            "task_plan_validation_sha256": validation["receipt_digest"],
        },
        "supersedes_graph_sha256": None,
        "nodes": [_node(task) for task in source_plan["tasks"]],
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
                "gate_id": "gate:join-evidence",
                "gate_type": "evidence",
                "authority_ref": None,
                "required_evidence_types": ["validator_receipt"],
                "condition": None,
                "timeout_seconds": 60,
                "on_timeout_outcome": "blocked",
            }
        ],
        "actions": [
            {
                "action_id": f"action:{task_id}",
                "runner": "host_adapter",
                "effect": "local_write",
                "tool_allowlist": ["callback"],
                "network_policy": "deny",
                "workspace_policy": "node_scope",
                "input_schema_ref": f"schema:action:{task_id}:input",
                "output_schema_ref": f"schema:action:{task_id}:output",
                "idempotency_required": False,
            }
            for task_id in ("A", "B", "JOIN")
        ],
    }


def _context_bundle(compiled_graph: dict[str, object], node_id: str) -> dict[str, object]:
    payload = b"bytes:resource:A:required"
    compiled_resource = {
        "resource_id": "resource:A:required",
        "resource_type": "repository_file",
        "source_ref": "project://resource:A:required",
        "revision": "revision:1",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "estimated_tokens": (len(payload) + 3) // 4,
        "freshness_state": "current",
        "sensitivity": "internal",
        "permission_ref": "permission:resource:A:required",
        "producer_node_id": None,
        "producer_receipt_sha256": None,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }
    base = {
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
    }
    return _with_self_digest(base, "bundle_sha256")


def _context_validation(bundle: dict[str, object]) -> dict[str, object]:
    base = {
        "schema_version": "goal-teams-context-validation-receipt-v2.65",
        "bundle_id": bundle["bundle_id"],
        "node_id": bundle["node_id"],
        "graph_contract_sha256": bundle["graph_contract_sha256"],
        "bundle_sha256": bundle["bundle_sha256"],
        "valid": True,
        "validator": "scripts.v265.context_compiler.validate_context_bundle",
        "validated_at": "2026-08-22T10:00:01Z",
    }
    return _with_self_digest(base, "receipt_sha256")


def _capability(compiled_graph: dict[str, object], node_id: str) -> dict[str, object]:
    node = next(item for item in compiled_graph["nodes"] if item["node_id"] == node_id)
    scope = {
        "scope_allowlist": node["scope_allowlist"],
        "forbidden_scope": node["forbidden_scope"],
    }
    base = {
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
        "scope_sha256": _canonical_sha256(scope),
        "tool_allowlist": ["callback"],
        "network_policy": "deny",
        "workspace_policy": "node_scope",
        "workspace_realpath": "/tmp/v265-fixture-workspace",
        "not_before": "2026-08-22T09:59:00Z",
        "issued_at": "2026-08-22T10:00:00Z",
        "expires_at": "2026-08-22T10:30:00Z",
        "freshness_state": "current",
        "permission_effect": "local_execution",
        "attestation_ref": None,
    }
    return _with_self_digest(base, "receipt_sha256")


def _capability_request(
    compiled_graph: dict[str, object],
    context_bundle: dict[str, object],
    capability_receipt: dict[str, object],
    node_id: str,
) -> dict[str, object]:
    node = next(item for item in compiled_graph["nodes"] if item["node_id"] == node_id)
    scope_sha256 = _canonical_sha256(
        {
            "scope_allowlist": node["scope_allowlist"],
            "forbidden_scope": node["forbidden_scope"],
        }
    )
    base = {
        "schema_version": "goal-teams-host-capability-request-v2.65",
        "run_id": "RUN-GRAPH-TEST",
        "node_id": node_id,
        "task_id": node["task_refs"][0],
        "attempt": 1,
        "action_ref": node["action_ref"],
        "owner_run_id": f"RUN-OWNER-{node_id}",
        "graph_contract_sha256": compiled_graph["receipt_sha256"],
        "scope_sha256": scope_sha256,
        "context_bundle_sha256": context_bundle["bundle_sha256"],
        "capability_receipt_sha256": capability_receipt["receipt_sha256"],
        "requested_at": "2026-08-22T10:00:01Z",
    }
    return _with_self_digest(base, "request_sha256")


def _capability_decision(
    capability_request: dict[str, object],
    capability_receipt: dict[str, object],
) -> dict[str, object]:
    base = {
        "schema_version": "goal-teams-host-capability-decision-v2.65",
        "verified": True,
        "issuer": capability_receipt["issuer"],
        "issuer_key_id": capability_receipt["issuer_key_id"],
        "issuer_assurance": capability_receipt["issuer_assurance"],
        "actor_relationship": capability_receipt["actor_relationship"],
        "proof_strength": capability_receipt["proof_strength"],
        "permission_effect": capability_receipt["permission_effect"],
        "freshness_state": capability_receipt["freshness_state"],
        "scope_sha256": capability_receipt["scope_sha256"],
        "node_id": capability_receipt["node_id"],
        "capability_receipt_sha256": capability_receipt["receipt_sha256"],
        "request_sha256": capability_request["request_sha256"],
        "reason_code": "verified_by_callback_fixture",
    }
    return _with_self_digest(base, "decision_sha256")


class TestV265GraphContract(unittest.TestCase):
    def setUp(self) -> None:
        self.source_plan, self.compiled_plan, self.plan_validation = _authoritative_plan()
        self.document = _graph_document(
            self.source_plan,
            self.compiled_plan,
            self.plan_validation,
        )

    def _compile(self, document: dict[str, object] | None = None) -> tuple[Any, dict[str, object]]:
        graph = _target("scripts.v265.graph_contract")
        receipt = graph.compile_graph_contract(
            document or self.document,
            compiled_task_plan=self.compiled_plan,
            task_plan_validation_receipt=self.plan_validation,
        )
        return graph, receipt

    def _assert_graph_error(
        self,
        code: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> None:
        graph = _target("scripts.v265.graph_contract")
        document = copy.deepcopy(self.document)
        mutate(document)
        with self.assertRaises(graph.GraphContractError) as caught:
            graph.compile_graph_contract(
                document,
                compiled_task_plan=self.compiled_plan,
                task_plan_validation_receipt=self.plan_validation,
            )
        self.assertEqual(code, caught.exception.code)

    def test_exact_task_coverage_binding_and_deterministic_receipt(self) -> None:
        graph, first = self._compile()
        reordered = copy.deepcopy(self.document)
        reordered["actions"].reverse()
        reordered["resources"].reverse()
        second = graph.compile_graph_contract(
            reordered,
            compiled_task_plan=copy.deepcopy(self.compiled_plan),
            task_plan_validation_receipt=copy.deepcopy(self.plan_validation),
        )
        self.assertEqual(first, second)
        self.assertEqual(["A", "B"], first["ready_roots"])
        self.assertEqual(["A", "B"], first["predecessor_map"]["JOIN"])
        self.assertEqual(
            ["data:A:JOIN", "data:B:JOIN", "dep:A:JOIN", "dep:B:JOIN"],
            first["fan_in_map"]["JOIN"]["edge_ids"],
        )
        self.assertEqual(["A", "B", "JOIN"], first["topological_order"])
        self.assertRegex(first["graph_contract_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(first["receipt_sha256"], r"^[0-9a-f]{64}$")
        validation = graph.validate_compiled_graph_contract(
            first,
            compiled_task_plan=self.compiled_plan,
            task_plan_validation_receipt=self.plan_validation,
        )
        self.assertEqual(
            {
                "schema_version",
                "graph_id",
                "graph_revision",
                "task_exact_set_sha256",
                "compiled_graph_receipt_sha256",
                "validator",
                "valid",
                "receipt_sha256",
            },
            set(validation),
        )
        self.assertTrue(validation["valid"])

        self._assert_graph_error(
            "E_V265_GRAPH_BINDING",
            lambda document: document["plan_binding"].__setitem__(
                "task_exact_set_sha256", SHA["f"]
            ),
        )
        self._assert_graph_error(
            "E_V265_GRAPH_TASK_COVERAGE",
            lambda document: document.__setitem__("nodes", document["nodes"][:-1]),
        )

    def test_owner_scope_and_budget_must_equal_frozen_task(self) -> None:
        self._assert_graph_error(
            "E_V265_GRAPH_OWNER_VALIDATOR",
            lambda document: document["nodes"][0].__setitem__(
                "validator_identity", document["nodes"][0]["owner_identity"]
            ),
        )
        self._assert_graph_error(
            "E_V265_GRAPH_TASK_BINDING",
            lambda document: document["nodes"][0].__setitem__(
                "scope_allowlist", ["scope/escape/**"]
            ),
        )
        def drift_frozen_attempt_budget(document: dict[str, object]) -> None:
            document["nodes"][0]["budget"]["attempts"] = 3
            document["nodes"][0]["retry_policy"]["max_attempts"] = 3
            document["nodes"][0]["retry_policy"]["backoff_seconds"] = [0, 0]

        self._assert_graph_error(
            "E_V265_GRAPH_TASK_BINDING",
            drift_frozen_attempt_budget,
        )

    def test_edge_endpoint_type_cycle_phase_and_duplicate_ids_fail_closed(self) -> None:
        self._assert_graph_error(
            "E_V265_GRAPH_EDGE_ENDPOINT",
            lambda document: document["edges"][0].__setitem__(
                "target_node_id", "MISSING"
            ),
        )
        self._assert_graph_error(
            "E_V265_GRAPH_EDGE_TYPE",
            lambda document: document["edges"][0].__setitem__(
                "edge_type", "magic_success"
            ),
        )

        def cycle(document: dict[str, object]) -> None:
            document["edges"].append(
                _edge("dep:JOIN:A", "dependency", "JOIN", "A")
            )
            document["nodes"][0]["fan_in"] = {
                "mode": "all",
                "edge_ids": ["dep:JOIN:A"],
                "quorum_count": None,
                "quorum_ratio_basis_points": None,
            }

        self._assert_graph_error("E_V265_GRAPH_CYCLE", cycle)

        def duplicate_edge(document: dict[str, object]) -> None:
            document["edges"].append(copy.deepcopy(document["edges"][0]))

        self._assert_graph_error("E_V265_GRAPH_DUPLICATE_ID", duplicate_edge)

        def duplicate_action(document: dict[str, object]) -> None:
            document["actions"].append(copy.deepcopy(document["actions"][0]))

        self._assert_graph_error("E_V265_GRAPH_DUPLICATE_ID", duplicate_action)

        source, compiled, validation = _authoritative_plan(
            {"development": ["A"], "runtime": ["B"], "release": ["JOIN"]}
        )
        phase_inverted = _graph_document(source, compiled, validation)
        phase_inverted["edges"].append(
            _edge("dep:B:A", "dependency", "B", "A")
        )
        phase_inverted["nodes"][0]["fan_in"] = {
            "mode": "all",
            "edge_ids": ["dep:B:A"],
            "quorum_count": None,
            "quorum_ratio_basis_points": None,
        }
        graph = _target("scripts.v265.graph_contract")
        with self.assertRaises(graph.GraphContractError) as caught:
            graph.compile_graph_contract(
                phase_inverted,
                compiled_task_plan=compiled,
                task_plan_validation_receipt=validation,
            )
        self.assertEqual("E_V265_GRAPH_EDGE_ENDPOINT", caught.exception.code)

    def test_action_binding_and_condition_gate_shape_are_exact(self) -> None:
        self._assert_graph_error(
            "E_V265_GRAPH_ACTION_BINDING",
            lambda document: document.__setitem__("actions", document["actions"][1:]),
        )
        self._assert_graph_error(
            "E_V265_GRAPH_ACTION_BINDING",
            lambda document: document["actions"][0].__setitem__("runner", "local_shell"),
        )

        graph = _target("scripts.v265.graph_contract")
        condition_graph = copy.deepcopy(self.document)
        condition_graph["gates"][0] = {
            "gate_id": "gate:join-evidence",
            "gate_type": "condition",
            "authority_ref": None,
            "required_evidence_types": ["typed_fact_receipt"],
            "condition": {
                "fact_ref": "fact:join-ready",
                "operator": "equals",
                "expected_value": True,
            },
            "timeout_seconds": 60,
            "on_timeout_outcome": "blocked",
        }
        compiled = graph.compile_graph_contract(
            condition_graph,
            compiled_task_plan=self.compiled_plan,
            task_plan_validation_receipt=self.plan_validation,
        )
        self.assertEqual("condition", compiled["gates"][0]["gate_type"])

        invalid = copy.deepcopy(condition_graph)
        invalid["gates"][0]["condition"]["operator"] = "execute_python"
        with self.assertRaises(graph.GraphContractError) as caught:
            graph.compile_graph_contract(
                invalid,
                compiled_task_plan=self.compiled_plan,
                task_plan_validation_receipt=self.plan_validation,
            )
        self.assertEqual("E_V265_GRAPH_GATE_BINDING", caught.exception.code)

    def test_data_edges_resolve_typed_ports_and_control_dependency(self) -> None:
        self._assert_graph_error(
            "E_V265_GRAPH_SCHEMA",
            lambda document: document["edges"][2].pop("edge_type"),
        )
        self._assert_graph_error(
            "E_V265_GRAPH_DATA_BINDING",
            lambda document: document["edges"][2]["data_bindings"][0].__setitem__(
                "schema_ref", "schema:other:v1"
            ),
        )

        def missing_control(document: dict[str, object]) -> None:
            document["edges"] = document["edges"][1:]
            document["nodes"][2]["fan_in"]["edge_ids"] = [
                "data:A:JOIN",
                "data:B:JOIN",
                "dep:B:JOIN",
            ]

        self._assert_graph_error("E_V265_GRAPH_DATA_BINDING", missing_control)

    def test_resource_producer_and_consumer_binding_is_exact(self) -> None:
        def wrong_consumer(document: dict[str, object]) -> None:
            resource = next(
                item
                for item in document["resources"]
                if item["resource_id"] == "resource:A:required"
            )
            resource["consumer_node_ids"] = ["B"]

        self._assert_graph_error("E_V265_GRAPH_RESOURCE_BINDING", wrong_consumer)

    def test_all_any_quorum_count_and_ratio_fan_in_are_exact(self) -> None:
        self._assert_graph_error(
            "E_V265_GRAPH_FAN_IN",
            lambda document: document["nodes"][2].__setitem__("fan_in", None),
        )

        graph = _target("scripts.v265.graph_contract")
        valid_modes = (
            ("all", None, None),
            ("any", None, None),
            ("quorum", 2, None),
            ("quorum", None, 5000),
        )
        for mode, count, ratio in valid_modes:
            with self.subTest(mode=mode, count=count, ratio=ratio):
                document = copy.deepcopy(self.document)
                document["nodes"][2]["fan_in"] = {
                    "mode": mode,
                    "edge_ids": [
                        "data:A:JOIN",
                        "data:B:JOIN",
                        "dep:A:JOIN",
                        "dep:B:JOIN",
                    ],
                    "quorum_count": count,
                    "quorum_ratio_basis_points": ratio,
                }
                receipt = graph.compile_graph_contract(
                    document,
                    compiled_task_plan=self.compiled_plan,
                    task_plan_validation_receipt=self.plan_validation,
                )
                self.assertEqual(mode, receipt["fan_in_map"]["JOIN"]["mode"])

        self._assert_graph_error(
            "E_V265_GRAPH_FAN_IN",
            lambda document: document["nodes"][2].__setitem__(
                "fan_in",
                {
                    "mode": "quorum",
                    "edge_ids": [
                        "data:A:JOIN",
                        "data:B:JOIN",
                        "dep:A:JOIN",
                        "dep:B:JOIN",
                    ],
                    "quorum_count": 5,
                    "quorum_ratio_basis_points": None,
                },
            ),
        )

    def test_repeat_and_recovery_require_positive_traversal_budget(self) -> None:
        for edge_type in ("repeat", "recovery"):
            with self.subTest(edge_type=edge_type):
                def unbounded(document: dict[str, object], selected: str = edge_type) -> None:
                    source = "A" if selected == "repeat" else "JOIN"
                    target = "A"
                    document["edges"].append(
                        _edge(
                            f"{selected}:{source}:{target}",
                            selected,
                            source,
                            target,
                            accepted_outcomes=["failed"],
                            traversal_budget=0,
                        )
                    )
                    if selected == "recovery":
                        document["nodes"][2]["recovery_policy"] = {
                            "mode": "edge",
                            "edge_id": "recovery:JOIN:A",
                        }

                self._assert_graph_error(
                    "E_V265_GRAPH_TRAVERSAL_BUDGET",
                    unbounded,
                )

    def test_forged_compiled_graph_receipt_cannot_validate(self) -> None:
        graph, receipt = self._compile()
        forged = copy.deepcopy(receipt)
        forged["ready_roots"] = ["JOIN"]
        forged["receipt_sha256"] = _canonical_sha256(
            {key: value for key, value in forged.items() if key != "receipt_sha256"}
        )
        with self.assertRaises(graph.GraphContractError) as caught:
            graph.validate_compiled_graph_contract(
                forged,
                compiled_task_plan=self.compiled_plan,
                task_plan_validation_receipt=self.plan_validation,
            )
        self.assertEqual("E_V265_GRAPH_RECEIPT_INVALID", caught.exception.code)

    def test_member_packet_binds_graph_context_capability_and_distinct_runs(self) -> None:
        _, compiled_graph = self._compile()
        member = _target("scripts.v265.member_packet")
        context = _context_bundle(compiled_graph, "A")
        context_validation = _context_validation(context)
        capability = _capability(compiled_graph, "A")
        capability_request = _capability_request(
            compiled_graph,
            context,
            capability,
            "A",
        )
        capability_decision = _capability_decision(
            capability_request,
            capability,
        )
        packet = member.compile_member_packet(
            packet_id="PACKET-A",
            compiled_graph=compiled_graph,
            node_id="A",
            owner_run_id="RUN-OWNER-A",
            validator_run_id="RUN-VALIDATOR-A",
            context_bundle=context,
            context_validation_receipt=context_validation,
            capability_receipt=capability,
            capability_request=capability_request,
            capability_decision=capability_decision,
            issued_at="2026-08-22T10:00:02Z",
        )
        validation = member.validate_member_packet(
            packet,
            compiled_graph=compiled_graph,
            context_bundle=context,
            capability_receipt=capability,
            capability_request=capability_request,
            capability_decision=capability_decision,
        )
        self.assertTrue(validation["valid"])
        self.assertNotEqual(packet["owner_run_id"], packet["validator_run_id"])
        self.assertEqual(
            capability_request["request_sha256"],
            packet["capability_request_sha256"],
        )
        self.assertEqual(
            capability_decision["decision_sha256"],
            packet["capability_decision_sha256"],
        )
        self.assertEqual(
            capability_request["request_sha256"],
            validation["capability_request_sha256"],
        )
        self.assertEqual(
            capability_decision["decision_sha256"],
            validation["capability_decision_sha256"],
        )
        self.assertRegex(packet["packet_sha256"], r"^[0-9a-f]{64}$")

        packet_drifts = {
            "graph_contract_sha256": (SHA["1"], "E_V265_MEMBER_BINDING"),
            "node_id": ("B", "E_V265_MEMBER_BINDING"),
            "plan_id": ("GT-FORGED-PLAN", "E_V265_MEMBER_BINDING"),
            "plan_revision": (999, "E_V265_MEMBER_BINDING"),
            "scope_sha256": (SHA["2"], "E_V265_MEMBER_SCOPE"),
        }
        for field, (value, code) in packet_drifts.items():
            with self.subTest(packet_binding=field):
                forged_packet = copy.deepcopy(packet)
                forged_packet[field] = value
                forged_packet["packet_sha256"] = _canonical_sha256(
                    {
                        key: item
                        for key, item in forged_packet.items()
                        if key != "packet_sha256"
                    }
                )
                with self.assertRaises(member.MemberPacketError) as caught:
                    member.validate_member_packet(
                        forged_packet,
                        compiled_graph=compiled_graph,
                        context_bundle=context,
                        capability_receipt=capability,
                        capability_request=capability_request,
                        capability_decision=capability_decision,
                    )
                self.assertEqual(code, caught.exception.code)

        tampered_request = copy.deepcopy(capability_request)
        tampered_request["request_sha256"] = SHA["f"]
        with self.assertRaises(member.MemberPacketError) as caught:
            member.compile_member_packet(
                packet_id="PACKET-TAMPERED-REQUEST",
                compiled_graph=compiled_graph,
                node_id="A",
                owner_run_id="RUN-OWNER-A",
                validator_run_id="RUN-VALIDATOR-A",
                context_bundle=context,
                context_validation_receipt=context_validation,
                capability_receipt=capability,
                capability_request=tampered_request,
                capability_decision=capability_decision,
                issued_at="2026-08-22T10:00:02Z",
            )
        self.assertEqual("E_V265_MEMBER_CAPABILITY", caught.exception.code)

        request_drifts = {
            "context_bundle_sha256": SHA["1"],
            "action_ref": "action:B",
            "owner_run_id": "RUN-OWNER-OTHER",
            "graph_contract_sha256": SHA["2"],
            "scope_sha256": SHA["3"],
            "capability_receipt_sha256": SHA["4"],
        }
        for field, value in request_drifts.items():
            with self.subTest(request_binding=field):
                drifted_request = copy.deepcopy(capability_request)
                drifted_request[field] = value
                drifted_request["request_sha256"] = _canonical_sha256(
                    {
                        key: item
                        for key, item in drifted_request.items()
                        if key != "request_sha256"
                    }
                )
                drifted_decision = _capability_decision(
                    drifted_request,
                    capability,
                )
                with self.assertRaises(member.MemberPacketError) as caught:
                    member.compile_member_packet(
                        packet_id=f"PACKET-DRIFT-{field}",
                        compiled_graph=compiled_graph,
                        node_id="A",
                        owner_run_id="RUN-OWNER-A",
                        validator_run_id="RUN-VALIDATOR-A",
                        context_bundle=context,
                        context_validation_receipt=context_validation,
                        capability_receipt=capability,
                        capability_request=drifted_request,
                        capability_decision=drifted_decision,
                        issued_at="2026-08-22T10:00:02Z",
                    )
                self.assertEqual("E_V265_MEMBER_CAPABILITY", caught.exception.code)

        with self.assertRaises(member.MemberPacketError) as caught:
            member.compile_member_packet(
                packet_id="PACKET-SELF",
                compiled_graph=compiled_graph,
                node_id="A",
                owner_run_id="RUN-SAME",
                validator_run_id="RUN-SAME",
                context_bundle=context,
                context_validation_receipt=context_validation,
                capability_receipt=capability,
                capability_request=capability_request,
                capability_decision=capability_decision,
                issued_at="2026-08-22T10:00:02Z",
            )
        self.assertEqual("E_V265_MEMBER_IDENTITY", caught.exception.code)

        drifted_context = copy.deepcopy(context)
        drifted_context["bundle_sha256"] = SHA["f"]
        with self.assertRaises(member.MemberPacketError) as caught:
            member.validate_member_packet(
                packet,
                compiled_graph=compiled_graph,
                context_bundle=drifted_context,
                capability_receipt=capability,
                capability_request=capability_request,
                capability_decision=capability_decision,
            )
        self.assertEqual("E_V265_MEMBER_CONTEXT", caught.exception.code)

        capability_drifts = {
            "tool_allowlist": ["callback", "network"],
            "network_policy": "declared",
            "workspace_policy": "read_only",
            "permission_effect": "external_side_effects",
        }
        for field, value in capability_drifts.items():
            with self.subTest(capability_binding=field):
                drifted_capability = copy.deepcopy(capability)
                drifted_capability[field] = value
                drifted_capability["receipt_sha256"] = _canonical_sha256(
                    {
                        key: item
                        for key, item in drifted_capability.items()
                        if key != "receipt_sha256"
                    }
                )
                drifted_request = _capability_request(
                    compiled_graph,
                    context,
                    drifted_capability,
                    "A",
                )
                drifted_decision = _capability_decision(
                    drifted_request,
                    drifted_capability,
                )
                with self.assertRaises(member.MemberPacketError) as caught:
                    member.compile_member_packet(
                        packet_id=f"PACKET-CAPABILITY-{field}",
                        compiled_graph=compiled_graph,
                        node_id="A",
                        owner_run_id="RUN-OWNER-A",
                        validator_run_id="RUN-VALIDATOR-A",
                        context_bundle=context,
                        context_validation_receipt=context_validation,
                        capability_receipt=drifted_capability,
                        capability_request=drifted_request,
                        capability_decision=drifted_decision,
                        issued_at="2026-08-22T10:00:02Z",
                    )
                self.assertEqual("E_V265_MEMBER_CAPABILITY", caught.exception.code)

        forged_decision = copy.deepcopy(capability_decision)
        forged_decision["request_sha256"] = SHA["f"]
        forged_decision["decision_sha256"] = _canonical_sha256(
            {
                key: value
                for key, value in forged_decision.items()
                if key != "decision_sha256"
            }
        )
        with self.assertRaises(member.MemberPacketError) as caught:
            member.compile_member_packet(
                packet_id="PACKET-FORGED-DECISION",
                compiled_graph=compiled_graph,
                node_id="A",
                owner_run_id="RUN-OWNER-A",
                validator_run_id="RUN-VALIDATOR-A",
                context_bundle=context,
                context_validation_receipt=context_validation,
                capability_receipt=capability,
                capability_request=capability_request,
                capability_decision=forged_decision,
                issued_at="2026-08-22T10:00:02Z",
            )
        self.assertEqual("E_V265_MEMBER_CAPABILITY", caught.exception.code)

        with self.assertRaises(member.MemberPacketError) as caught:
            member.validate_member_packet(
                b"raw packet bypass",
                compiled_graph=compiled_graph,
                context_bundle=context,
                capability_receipt=capability,
                capability_request=capability_request,
                capability_decision=capability_decision,
            )
        self.assertEqual("E_V265_MEMBER_RAW_PACKET_FORBIDDEN", caught.exception.code)

if __name__ == "__main__":
    unittest.main()
