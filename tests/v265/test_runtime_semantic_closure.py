from __future__ import annotations

import copy
import importlib
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Mapping

from tests.v265 import test_graph_runtime as fx


CONTRACT_SHA256 = "a5643853ff8feceb6b2d12b85af1e8ffa0a2c354d381837d4cbe3701dfcd4446"
PLAN_REVISION = 2
TASK_EXACT_SET_SHA256 = "7d818fd0c644dd8388abbcd889ce6a66e7f133cf5aeaaf083ae93f83b1047472"

GRAPH_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "graph_id",
        "graph_revision",
        "plan_binding",
        "supersedes_graph_sha256",
        "nodes",
        "edges",
        "resources",
        "gates",
        "actions",
    }
)
INTRINSIC_RECEIPT_FIELDS = {
    "schema_version",
    "graph_id",
    "graph_revision",
    "graph_contract_sha256",
    "compiled_graph_receipt_sha256",
    "derived_map_sha256",
    "valid",
    "validator",
    "receipt_sha256",
}


def _target(name: str) -> Any:
    return importlib.import_module(name)


def _redigest(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result.pop(field, None)
    result[field] = fx._canonical_sha256(result)
    return result


def _fully_bound_inputs() -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, object]
]:
    """Return a local complete fixture before the repository fixture migration."""

    source, plan, validation = fx._authoritative_plan()
    document = fx._graph_document(source, plan, validation)
    if not any(edge["edge_id"] == "data:B:JOIN" for edge in document["edges"]):
        document["edges"].append(
            fx._edge(
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
            )
        )
    join = next(node for node in document["nodes"] if node["node_id"] == "JOIN")
    if "data:B:JOIN" not in join["fan_in"]["edge_ids"]:
        join["fan_in"]["edge_ids"].append("data:B:JOIN")
    join["fan_in"]["edge_ids"] = sorted(join["fan_in"]["edge_ids"])
    document["edges"] = sorted(document["edges"], key=lambda edge: edge["edge_id"])
    return source, plan, validation, document


def _compile_fully_bound(
    mutator: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    _source, plan, validation, document = _fully_bound_inputs()
    if mutator is not None:
        mutator(document)
    return _target("scripts.v265.graph_contract").compile_graph_contract(
        document,
        compiled_task_plan=plan,
        task_plan_validation_receipt=validation,
    )


def _rehash_compiled(value: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result["graph_contract_sha256"] = fx._canonical_sha256(
        {field: copy.deepcopy(result[field]) for field in GRAPH_INPUT_FIELDS}
    )
    result["receipt_sha256"] = fx._canonical_sha256(
        {key: item for key, item in result.items() if key != "receipt_sha256"}
    )
    return result


def _remove_b_data(compiled_graph: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(compiled_graph))
    result["edges"] = [
        edge for edge in result["edges"] if edge["edge_id"] != "data:B:JOIN"
    ]
    join = next(node for node in result["nodes"] if node["node_id"] == "JOIN")
    join["fan_in"]["edge_ids"] = [
        edge_id
        for edge_id in join["fan_in"]["edge_ids"]
        if edge_id != "data:B:JOIN"
    ]
    result["fan_in_map"]["JOIN"] = copy.deepcopy(join["fan_in"])
    result["execution_edge_ids"] = [
        edge_id
        for edge_id in result["execution_edge_ids"]
        if edge_id != "data:B:JOIN"
    ]
    return _rehash_compiled(result)


def _intrinsic_forgeries(compiled_graph: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    node_scope = copy.deepcopy(dict(compiled_graph))
    node_scope["nodes"][0]["scope_allowlist"] = []
    candidates["node_scope"] = _rehash_compiled(node_scope)

    gate = copy.deepcopy(dict(compiled_graph))
    evidence_gate = next(item for item in gate["gates"] if item["gate_type"] == "evidence")
    evidence_gate["required_evidence_types"] = []
    candidates["gate"] = _rehash_compiled(gate)

    action = copy.deepcopy(dict(compiled_graph))
    action["actions"][0]["runner"] = "forged_runner"
    candidates["action"] = _rehash_compiled(action)

    resource = copy.deepcopy(dict(compiled_graph))
    resource["resources"][0]["token_budget"] = 0
    candidates["resource"] = _rehash_compiled(resource)

    port = copy.deepcopy(dict(compiled_graph))
    join = next(item for item in port["nodes"] if item["node_id"] == "JOIN")
    join["input_ports"][0]["required"] = "yes"
    candidates["port"] = _rehash_compiled(port)

    data = copy.deepcopy(dict(compiled_graph))
    data_edge = next(item for item in data["edges"] if item["edge_id"] == "data:B:JOIN")
    data_edge["data_bindings"][0]["schema_ref"] = "schema:forged"
    candidates["data"] = _rehash_compiled(data)

    fan_in = copy.deepcopy(dict(compiled_graph))
    join = next(item for item in fan_in["nodes"] if item["node_id"] == "JOIN")
    join["fan_in"].update(
        {"mode": "quorum", "quorum_count": None, "quorum_ratio_basis_points": None}
    )
    fan_in["fan_in_map"]["JOIN"] = copy.deepcopy(join["fan_in"])
    candidates["fan_in"] = _rehash_compiled(fan_in)

    candidates["missing_required_data"] = _remove_b_data(compiled_graph)
    return candidates


class TestV265RuntimeSemanticClosure(unittest.TestCase):
    """Immutable Red denominator for the bounded semantic-closure overlay."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name).resolve() / "workspace"
        for node_id in ("A", "B", "JOIN"):
            (self.workspace / "scope" / node_id).mkdir(parents=True, exist_ok=True)
        self.graph_contract = _target("scripts.v265.graph_contract")
        self.runtime = _target("scripts.v265.graph_runtime")
        self.graph = _compile_fully_bound()
        self.bindings = fx._bindings(self.graph)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _append(
        self,
        events: list[dict[str, object]],
        graph: Mapping[str, Any],
        *,
        run_id: str,
        event_type: str,
        node_id: str | None,
        attempt: int,
        payload: Mapping[str, Any],
        actor: str,
        occurred_at: str | None = None,
    ) -> dict[str, object]:
        sequence = len(events) + 1
        event = self.runtime.make_graph_event(
            run_id=run_id,
            event_id=f"EVENT-{run_id}-{sequence}",
            event_seq=sequence,
            event_type=event_type,
            node_id=node_id,
            attempt=attempt,
            cas_base_revision=sequence - 1,
            previous_event_sha256=(
                fx.ZERO_SHA256 if not events else str(events[-1]["event_sha256"])
            ),
            bindings=fx._bindings(graph),
            payload=copy.deepcopy(dict(payload)),
            evidence_refs=[f"evidence:closure:{sequence}"],
            actor_identity=actor,
            actor_relationship="authorized_writer",
            occurred_at=occurred_at or f"2026-08-22T10:01:{sequence:02d}Z",
        )
        events.append(event)
        return event

    def _created(self, graph: Mapping[str, Any], run_id: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="run.created",
            node_id=None,
            attempt=0,
            payload={"graph_receipt_sha256": graph["receipt_sha256"]},
            actor="goal_lead",
        )
        return events

    def _dispatch(
        self, graph: dict[str, object], run_id: str, node_id: str, attempt: int
    ) -> dict[str, dict[str, object]]:
        context, context_validation = fx._context_bundle(graph, node_id)
        capability = fx._capability(graph, node_id, self.workspace)
        request = fx._capability_request(
            graph,
            node_id,
            context,
            capability,
            run_id=run_id,
            attempt=attempt,
        )
        decision = fx._capability_decision(request, capability)
        packet = fx._member_packet(
            graph,
            node_id,
            context,
            context_validation,
            capability,
            request,
            decision,
        )
        return {
            "context": context,
            "capability": capability,
            "request": request,
            "decision": decision,
            "packet": packet,
        }

    def _start_attempt(
        self,
        events: list[dict[str, object]],
        graph: dict[str, object],
        run_id: str,
        node_id: str,
        attempt: int,
        *,
        emit_ready: bool,
        short_lease: bool = False,
    ) -> str:
        if emit_ready:
            self._append(
                events,
                graph,
                run_id=run_id,
                event_type="node.ready",
                node_id=node_id,
                attempt=attempt,
                payload={
                    "satisfied_edge_ids": [],
                    "fan_in_mode": "root",
                    "required_edge_count": 0,
                    "satisfied_edge_count": 0,
                },
                actor="runtime_controller",
            )
        claim_sequence = len(events) + 1
        lease_id = f"LEASE-{node_id}-{attempt}"
        lease_expires_at = (
            f"2026-08-22T10:01:{claim_sequence + 1:02d}Z"
            if short_lease
            else "2026-08-22T10:01:59Z"
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.claimed",
            node_id=node_id,
            attempt=attempt,
            payload={
                "worker_id": f"WORKER-{node_id}-{attempt}",
                "lease_id": lease_id,
                "lease_expires_at": lease_expires_at,
            },
            actor="runtime_controller",
        )
        dispatch = self._dispatch(graph, run_id, node_id, attempt)
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.started",
            node_id=node_id,
            attempt=attempt,
            payload={
                "owner_run_id": f"RUN-OWNER-{node_id}",
                "validator_run_id": f"RUN-VALIDATOR-{node_id}",
                "member_packet": dispatch["packet"],
                "context_bundle_sha256": dispatch["context"]["bundle_sha256"],
                "capability_receipt": dispatch["capability"],
                "capability_request": dispatch["request"],
                "capability_decision": dispatch["decision"],
                "host_handle_id": f"HANDLE-{node_id}-{attempt}",
            },
            actor=f"RUN-OWNER-{node_id}",
        )
        return lease_id

    def _record_outcome(
        self,
        events: list[dict[str, object]],
        graph: dict[str, object],
        run_id: str,
        node_id: str,
        attempt: int,
        outcome: str,
        *,
        validate: bool,
    ) -> None:
        artifact = fx._artifact(graph, run_id, node_id, attempt)
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.outcome_recorded",
            node_id=node_id,
            attempt=attempt,
            payload={
                "outcome": outcome,
                "owner_run_id": f"RUN-OWNER-{node_id}",
                "artifact_receipts": [artifact],
            },
            actor=f"RUN-OWNER-{node_id}",
        )
        if validate:
            receipt = fx._validation_receipt(graph, run_id, node_id, [artifact])
            receipt.update(
                {
                    "attempt": attempt,
                    "observed_outcome": outcome,
                    "validation_state": "passed",
                }
            )
            receipt = _redigest(receipt, "receipt_sha256")
            self._append(
                events,
                graph,
                run_id=run_id,
                event_type="node.validation_recorded",
                node_id=node_id,
                attempt=attempt,
                payload={
                    "validation_state": "passed",
                    "validator_run_id": f"RUN-VALIDATOR-{node_id}",
                    "validation_receipt": receipt,
                    "observed_outcome": outcome,
                },
                actor=f"RUN-VALIDATOR-{node_id}",
            )

    def _expire_to_second_attempt(
        self,
        events: list[dict[str, object]],
        graph: dict[str, object],
        run_id: str,
        node_id: str,
        outcome: str,
    ) -> None:
        lease_id = self._start_attempt(
            events,
            graph,
            run_id,
            node_id,
            1,
            emit_ready=True,
            short_lease=True,
        )
        lease_expires_at = f"2026-08-22T10:01:{len(events):02d}Z"
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.lease_expired",
            node_id=node_id,
            attempt=1,
            payload={
                "lease_id": lease_id,
                "lease_expires_at": lease_expires_at,
                "recovery_decision": "ready",
            },
            actor="runtime_controller",
        )
        self._start_attempt(
            events,
            graph,
            run_id,
            node_id,
            2,
            emit_ready=False,
        )
        self._record_outcome(
            events, graph, run_id, node_id, 2, outcome, validate=True
        )

    def _assert_runtime_error(
        self,
        graph: Mapping[str, Any],
        events: list[dict[str, object]],
        code: str,
    ) -> None:
        try:
            self.runtime.reduce_graph_events(
                graph, events, expected_bindings=fx._bindings(graph)
            )
        except self.runtime.GraphRuntimeError as exc:
            self.assertEqual(code, exc.code)
        except Exception as exc:  # product exceptions must not leak their class
            self.fail(f"E_TEST_V265_NON_CONTRACT_EXCEPTION:{type(exc).__name__}:{exc}")
        else:
            self.fail(f"E_TEST_V265_EXPECTED_RUNTIME_ERROR:{code}")

    def test_required_input_ports_require_exactly_one_data_binding(self) -> None:
        self.assertEqual(PLAN_REVISION, 2)
        self.assertRegex(CONTRACT_SHA256, r"^[0-9a-f]{64}$")
        self.assertRegex(TASK_EXACT_SET_SHA256, r"^[0-9a-f]{64}$")
        _source, plan, validation, fully_bound = _fully_bound_inputs()

        missing = copy.deepcopy(fully_bound)
        missing["edges"] = [
            edge for edge in missing["edges"] if edge["edge_id"] != "data:B:JOIN"
        ]
        join = next(node for node in missing["nodes"] if node["node_id"] == "JOIN")
        join["fan_in"]["edge_ids"].remove("data:B:JOIN")

        duplicate = copy.deepcopy(fully_bound)
        duplicate["edges"].append(
            fx._edge(
                "data:A:JOIN:duplicate",
                "data",
                "A",
                "JOIN",
                data_bindings=[
                    {
                        "output_port_id": "out:A",
                        "input_port_id": "in:B",
                        "schema_ref": "schema:artifact:v1",
                    }
                ],
            )
        )
        duplicate_join = next(
            node for node in duplicate["nodes"] if node["node_id"] == "JOIN"
        )
        duplicate_join["fan_in"]["edge_ids"].append("data:A:JOIN:duplicate")
        duplicate_join["fan_in"]["edge_ids"] = sorted(
            duplicate_join["fan_in"]["edge_ids"]
        )

        optional_duplicate = copy.deepcopy(fully_bound)
        optional_join = next(
            node for node in optional_duplicate["nodes"] if node["node_id"] == "JOIN"
        )
        optional_join["input_ports"].append(
            {
                "port_id": "in:optional",
                "schema_ref": "schema:artifact:v1",
                "required": False,
                "sensitivity": "internal",
            }
        )
        for source in ("A", "B"):
            edge_id = f"data:{source}:JOIN:optional"
            optional_duplicate["edges"].append(
                fx._edge(
                    edge_id,
                    "data",
                    source,
                    "JOIN",
                    data_bindings=[
                        {
                            "output_port_id": f"out:{source}",
                            "input_port_id": "in:optional",
                            "schema_ref": "schema:artifact:v1",
                        }
                    ],
                )
            )
            optional_join["fan_in"]["edge_ids"].append(edge_id)
        optional_join["fan_in"]["edge_ids"] = sorted(
            optional_join["fan_in"]["edge_ids"]
        )

        for name, document in (
            ("missing", missing),
            ("duplicate", duplicate),
            ("optional_duplicate", optional_duplicate),
        ):
            with self.subTest(case=name):
                with self.assertRaises(self.graph_contract.GraphContractError) as caught:
                    self.graph_contract.compile_graph_contract(
                        document,
                        compiled_task_plan=plan,
                        task_plan_validation_receipt=validation,
                    )
                self.assertEqual("E_V265_GRAPH_DATA_BINDING", caught.exception.code)

    def test_direct_graph_intrinsic_api_is_exact_and_rejects_rehashed_forgeries(self) -> None:
        validator = getattr(self.graph_contract, "validate_graph_intrinsic", None)
        self.assertTrue(callable(validator), "E_TEST_V265_GRAPH_INTRINSIC_API_MISSING")
        receipt = validator(self.graph)
        self.assertEqual(INTRINSIC_RECEIPT_FIELDS, set(receipt))
        self.assertEqual("goal-teams-graph-intrinsic-validation-v2.65", receipt["schema_version"])
        self.assertEqual(self.graph["graph_id"], receipt["graph_id"])
        self.assertEqual(self.graph["graph_revision"], receipt["graph_revision"])
        self.assertEqual(self.graph["graph_contract_sha256"], receipt["graph_contract_sha256"])
        self.assertEqual(self.graph["receipt_sha256"], receipt["compiled_graph_receipt_sha256"])
        derived = {
            field: self.graph[field]
            for field in (
                "task_node_map",
                "predecessor_map",
                "fan_in_map",
                "topological_order",
                "ready_roots",
                "execution_edge_ids",
                "lineage_edge_ids",
            )
        }
        self.assertEqual(fx._canonical_sha256(derived), receipt["derived_map_sha256"])
        self.assertEqual(
            "scripts.v265.graph_contract.validate_graph_intrinsic",
            receipt["validator"],
        )
        self.assertTrue(receipt["valid"])
        self.assertEqual(
            fx._canonical_sha256(
                {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            ),
            receipt["receipt_sha256"],
        )
        for name, candidate in _intrinsic_forgeries(self.graph).items():
            with self.subTest(case=name):
                with self.assertRaises(self.graph_contract.GraphContractError) as caught:
                    validator(candidate)
                self.assertEqual("E_V265_GRAPH_RECEIPT_INVALID", caught.exception.code)

    def test_runtime_wrapper_rejects_every_rehashed_intrinsic_forgery(self) -> None:
        for name, candidate in _intrinsic_forgeries(self.graph).items():
            with self.subTest(case=name):
                with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
                    self.runtime.validate_runtime_graph_contract(candidate)
                self.assertEqual("E_V265_RUNTIME_GRAPH_INTEGRITY", caught.exception.code)

    def test_terminal_gate_state_cannot_be_overwritten(self) -> None:
        run_id = "RUN-GATE-TERMINAL"
        events = self._created(self.graph, run_id)
        passed = fx._gate_receipt(self.graph, run_id)
        self._append(
            events,
            self.graph,
            run_id=run_id,
            event_type="gate.passed",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": passed["gate_id"],
                "gate_receipt": passed,
                "gate_decision_sha256": passed["receipt_sha256"],
                "decision": "passed",
            },
            actor=str(passed["authority_identity"]),
        )
        rejected = copy.deepcopy(passed)
        rejected["decision"] = "rejected"
        rejected = _redigest(rejected, "receipt_sha256")
        self._append(
            events,
            self.graph,
            run_id=run_id,
            event_type="gate.rejected",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": rejected["gate_id"],
                "gate_receipt": rejected,
                "gate_decision_sha256": rejected["receipt_sha256"],
                "decision": "rejected",
            },
            actor=str(rejected["authority_identity"]),
        )
        self._assert_runtime_error(self.graph, events, "E_V265_RUNTIME_GATE")

        rejected_run = "RUN-GATE-REJECTED-TERMINAL"
        rejected_events = self._created(self.graph, rejected_run)
        rejected_first = fx._gate_receipt(self.graph, rejected_run)
        rejected_first["decision"] = "rejected"
        rejected_first = _redigest(rejected_first, "receipt_sha256")
        self._append(
            rejected_events,
            self.graph,
            run_id=rejected_run,
            event_type="gate.rejected",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": rejected_first["gate_id"],
                "gate_receipt": rejected_first,
                "gate_decision_sha256": rejected_first["receipt_sha256"],
                "decision": "rejected",
            },
            actor=str(rejected_first["authority_identity"]),
        )
        rejected_projection = self.runtime.reduce_graph_events(
            self.graph,
            rejected_events,
            expected_bindings=self.bindings,
        )
        self.assertEqual(
            "rejected",
            rejected_projection["gate_states"]["gate:join-evidence"],
        )
        passed_after_rejected = fx._gate_receipt(self.graph, rejected_run)
        self._append(
            rejected_events,
            self.graph,
            run_id=rejected_run,
            event_type="gate.passed",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": passed_after_rejected["gate_id"],
                "gate_receipt": passed_after_rejected,
                "gate_decision_sha256": passed_after_rejected["receipt_sha256"],
                "decision": "passed",
            },
            actor=str(passed_after_rejected["authority_identity"]),
        )
        self._assert_runtime_error(
            self.graph, rejected_events, "E_V265_RUNTIME_GATE"
        )

    def test_gate_timeout_recomputes_deadline_outcome_and_terminal_state(self) -> None:
        cases: list[tuple[str, list[dict[str, object]]]] = []

        valid_run = "RUN-GATE-TIMEOUT-VALID"
        valid_timeout = self._created(self.graph, valid_run)
        self._append(
            valid_timeout,
            self.graph,
            run_id=valid_run,
            event_type="gate.timed_out",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": "gate:join-evidence",
                "deadline": "2026-08-22T10:01:30Z",
                "on_timeout_outcome": "blocked",
            },
            actor="runtime_controller",
            occurred_at="2026-08-22T10:02:00Z",
        )
        valid_projection = self.runtime.reduce_graph_events(
            self.graph,
            valid_timeout,
            expected_bindings=self.bindings,
        )
        self.assertEqual(
            "timed_out", valid_projection["gate_states"]["gate:join-evidence"]
        )

        for next_type in ("gate.passed", "gate.rejected"):
            terminal_copy = copy.deepcopy(valid_timeout)
            receipt = fx._gate_receipt(self.graph, valid_run)
            decision = "passed" if next_type == "gate.passed" else "rejected"
            receipt["decision"] = decision
            receipt = _redigest(receipt, "receipt_sha256")
            self._append(
                terminal_copy,
                self.graph,
                run_id=valid_run,
                event_type=next_type,
                node_id=None,
                attempt=0,
                payload={
                    "gate_id": receipt["gate_id"],
                    "gate_receipt": receipt,
                    "gate_decision_sha256": receipt["receipt_sha256"],
                    "decision": decision,
                },
                actor=str(receipt["authority_identity"]),
                occurred_at="2026-08-22T10:02:01Z",
            )
            cases.append((f"timed_out_then_{decision}", terminal_copy))

        future = self._created(self.graph, "RUN-GATE-FUTURE")
        self._append(
            future,
            self.graph,
            run_id="RUN-GATE-FUTURE",
            event_type="gate.timed_out",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": "gate:join-evidence",
                "deadline": "2026-08-22T10:05:00Z",
                "on_timeout_outcome": "blocked",
            },
            actor="runtime_controller",
            occurred_at="2026-08-22T10:02:00Z",
        )
        cases.append(("future_deadline", future))

        wrong_outcome = self._created(self.graph, "RUN-GATE-OUTCOME")
        self._append(
            wrong_outcome,
            self.graph,
            run_id="RUN-GATE-OUTCOME",
            event_type="gate.timed_out",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": "gate:join-evidence",
                "deadline": "2026-08-22T10:01:30Z",
                "on_timeout_outcome": "failed",
            },
            actor="runtime_controller",
            occurred_at="2026-08-22T10:02:00Z",
        )
        cases.append(("wrong_outcome", wrong_outcome))

        terminal = self._created(self.graph, "RUN-GATE-TIMEOUT-TERMINAL")
        passed = fx._gate_receipt(self.graph, "RUN-GATE-TIMEOUT-TERMINAL")
        self._append(
            terminal,
            self.graph,
            run_id="RUN-GATE-TIMEOUT-TERMINAL",
            event_type="gate.passed",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": passed["gate_id"],
                "gate_receipt": passed,
                "gate_decision_sha256": passed["receipt_sha256"],
                "decision": "passed",
            },
            actor=str(passed["authority_identity"]),
        )
        self._append(
            terminal,
            self.graph,
            run_id="RUN-GATE-TIMEOUT-TERMINAL",
            event_type="gate.timed_out",
            node_id=None,
            attempt=0,
            payload={
                "gate_id": "gate:join-evidence",
                "deadline": "2026-08-22T10:01:30Z",
                "on_timeout_outcome": "blocked",
            },
            actor="runtime_controller",
            occurred_at="2026-08-22T10:02:00Z",
        )
        cases.append(("terminal_overwrite", terminal))

        for name, events in cases:
            with self.subTest(case=name):
                self._assert_runtime_error(self.graph, events, "E_V265_RUNTIME_GATE")

    def test_exhausted_retry_sentinel_never_leaks_index_error(self) -> None:
        def retry_node(document: dict[str, object]) -> None:
            node = next(item for item in document["nodes"] if item["node_id"] == "A")
            node["recovery_policy"] = {"mode": "retry", "edge_id": None}

        graph = _compile_fully_bound(retry_node)
        run_id = "RUN-RETRY-EXHAUSTED"
        events = self._created(graph, run_id)
        self._start_attempt(events, graph, run_id, "A", 1, emit_ready=True)
        self._record_outcome(
            events, graph, run_id, "A", 1, "failed", validate=False
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id="A",
            attempt=1,
            payload={
                "source_edge_id": "retry_policy:A",
                "traversal_count": 1,
                "next_attempt": 2,
            },
            actor="runtime_controller",
        )
        self._start_attempt(events, graph, run_id, "A", 2, emit_ready=False)
        self._record_outcome(
            events, graph, run_id, "A", 2, "failed", validate=False
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id="A",
            attempt=2,
            payload={
                "source_edge_id": "retry_policy:A",
                "traversal_count": 2,
                "next_attempt": 3,
            },
            actor="runtime_controller",
        )
        self._assert_runtime_error(graph, events, "E_V265_RUNTIME_ATTEMPT_BUDGET")

    def test_real_recovery_edge_checks_target_budget_without_node_backoff(self) -> None:
        def recovery_edge(document: dict[str, object]) -> None:
            edge = fx._edge(
                "recovery:B:A",
                "recovery",
                "B",
                "A",
                accepted_outcomes=["failed"],
            )
            edge["traversal_budget"] = 1
            document["edges"].append(edge)
            node = next(item for item in document["nodes"] if item["node_id"] == "B")
            node["recovery_policy"] = {"mode": "edge", "edge_id": "recovery:B:A"}

        graph = _compile_fully_bound(recovery_edge)
        run_id = "RUN-RECOVERY-TARGET-EXHAUSTED"
        events = self._created(graph, run_id)
        self._expire_to_second_attempt(events, graph, run_id, "A", "completed")
        self._expire_to_second_attempt(events, graph, run_id, "B", "failed")
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id="B",
            attempt=2,
            payload={
                "source_edge_id": "recovery:B:A",
                "traversal_count": 1,
                "next_attempt": 3,
            },
            actor="runtime_controller",
        )
        self._assert_runtime_error(graph, events, "E_V265_RUNTIME_ATTEMPT_BUDGET")


if __name__ == "__main__":
    unittest.main()
