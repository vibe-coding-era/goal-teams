from __future__ import annotations

import copy
import hashlib
import importlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from tests.v265 import test_graph_runtime as fx


ARCHITECTURE_SHA256 = "5f350bae868f842bc02d00b67ba44c577765c3f9a7f9ed080ada31e81f3c486f"
HARDENING_PLAN_REVISION = 3
HARDENING_TASK_EXACT_SET_SHA256 = (
    "d0f5bbf75cadf24338028d477b0e1ccc40c29b8aeb0c642cdc988d2600ebf496"
)
AJV_VERSION = "8.18.0"
AJV_2020_ENTRY_SHA256 = "908e9670b478b2ba126802a221b7e47006f50cf467e2c5dd7935d3dbef10a20a"


def _target(module_name: str) -> Any:
    return importlib.import_module(module_name)


def _rehash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result[field] = fx._canonical_sha256(
        {key: item for key, item in result.items() if key != field}
    )
    return result


def _compiled_document(mutator: Any | None = None) -> dict[str, object]:
    source, plan, validation = fx._authoritative_plan()
    document = fx._graph_document(source, plan, validation)
    if mutator is not None:
        mutator(document)
    graph = _target("scripts.v265.graph_contract")
    return graph.compile_graph_contract(
        document,
        compiled_task_plan=plan,
        task_plan_validation_receipt=validation,
    )


class TestV265RuntimeSemanticHardening(unittest.TestCase):
    """Immutable Red denominator for Architecture Revision 11.3 H265-01."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        for node_id in ("A", "B", "JOIN"):
            (self.workspace / "scope" / node_id).mkdir(parents=True, exist_ok=True)
        self.graph = fx._compiled_graph()
        self.bindings = fx._bindings(self.graph)
        self.runtime = _target("scripts.v265.graph_runtime")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _append(
        self,
        events: list[dict[str, object]],
        graph: dict[str, object],
        *,
        run_id: str,
        event_type: str,
        node_id: str | None,
        attempt: int,
        payload: dict[str, object],
        actor: str,
        occurred_at: str | None = None,
    ) -> dict[str, object]:
        seq = len(events) + 1
        event = self.runtime.make_graph_event(
            run_id=run_id,
            event_id=f"EVENT-{run_id}-{seq}",
            event_seq=seq,
            event_type=event_type,
            node_id=node_id,
            attempt=attempt,
            cas_base_revision=seq - 1,
            previous_event_sha256=(
                fx.ZERO_SHA256 if not events else str(events[-1]["event_sha256"])
            ),
            bindings=fx._bindings(graph),
            payload=payload,
            evidence_refs=[f"evidence:event:{run_id}:{seq}"],
            actor_identity=actor,
            actor_relationship="authorized_writer",
            occurred_at=occurred_at or f"2026-08-22T10:02:{seq:02d}Z",
        )
        events.append(event)
        return event

    def _created(self, graph: dict[str, object], run_id: str) -> list[dict[str, object]]:
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

    def _start(
        self,
        events: list[dict[str, object]],
        graph: dict[str, object],
        run_id: str,
        node_id: str,
        *,
        attempt: int = 1,
    ) -> dict[str, dict[str, object]]:
        dispatch = fx._dispatch_evidence(graph, run_id, node_id, self.workspace)
        if attempt != 1:
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
            dispatch = {
                "context": context,
                "context_validation": context_validation,
                "capability": capability,
                "request": request,
                "decision": decision,
                "packet": packet,
            }
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.ready" if attempt == 1 else "node.claimed",
            node_id=node_id,
            attempt=attempt,
            payload=(
                {
                    "satisfied_edge_ids": [],
                    "fan_in_mode": "root",
                    "required_edge_count": 0,
                    "satisfied_edge_count": 0,
                }
                if attempt == 1
                else {
                    "worker_id": f"WORKER-{node_id}-{attempt}",
                    "lease_id": f"LEASE-{node_id}-{attempt}",
                    "lease_expires_at": "2026-08-22T10:20:00Z",
                }
            ),
            actor="goal_lead",
        )
        if attempt == 1:
            self._append(
                events,
                graph,
                run_id=run_id,
                event_type="node.claimed",
                node_id=node_id,
                attempt=attempt,
                payload={
                    "worker_id": f"WORKER-{node_id}-{attempt}",
                    "lease_id": f"LEASE-{node_id}-{attempt}",
                    "lease_expires_at": "2026-08-22T10:20:00Z",
                },
                actor="goal_lead",
            )
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
        return dispatch

    def _record_outcome(
        self,
        events: list[dict[str, object]],
        graph: dict[str, object],
        run_id: str,
        node_id: str,
        *,
        attempt: int,
        outcome: str,
        validate: bool,
    ) -> dict[str, object]:
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
            receipt["attempt"] = attempt
            receipt["observed_outcome"] = outcome
            receipt["validation_state"] = "passed"
            receipt["receipt_sha256"] = fx._canonical_sha256(
                {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            )
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
        return artifact

    def _gate_event(
        self,
        events: list[dict[str, object]],
        graph: dict[str, object],
        run_id: str,
        receipt: dict[str, object],
        *,
        event_type: str = "gate.passed",
        actor: str | None = None,
    ) -> dict[str, object]:
        return self._append(
            events,
            graph,
            run_id=run_id,
            event_type=event_type,
            node_id=None,
            attempt=0,
            payload={
                "gate_id": receipt["gate_id"],
                "gate_receipt": receipt,
                "gate_decision_sha256": receipt["receipt_sha256"],
                "decision": receipt["decision"],
            },
            actor=actor or str(receipt["authority_identity"]),
        )

    def _schema_events(self) -> list[dict[str, object]]:
        graph = self.graph
        run_id = "RUN-SCHEMA"
        dispatch = fx._dispatch_evidence(graph, run_id, "A", self.workspace)
        artifact = fx._artifact(graph, run_id, "A", 1)
        validation = fx._validation_receipt(graph, run_id, "A", [artifact])
        gate = fx._gate_receipt(graph, run_id)
        approval = fx._approval_receipt(graph, "A", interrupt_id="INT-SCHEMA")
        approval_decision = fx._ExternalApprovalHost().verify_approval(
            {
                "run_id": run_id,
                "interrupt_id": "INT-SCHEMA",
                "node_id": "A",
                "gate_id": "gate:human:A",
                "state": "waiting_user",
                "approval_receipt_sha256": None,
                "updated_at": "2026-08-22T10:02:00Z",
            },
            approval,
        )
        host_dispatch = {
            "schema_version": "goal-teams-host-dispatch-v2.65",
            "run_id": run_id,
            "node_id": "A",
            "task_id": "A",
            "attempt": 1,
            "action_ref": "action:A",
            "member_packet": dispatch["packet"],
            "context_bundle": dispatch["context"],
            "capability_receipt": dispatch["capability"],
            "capability_decision": dispatch["decision"],
            "idempotency_key": "KEY-SCHEMA",
        }
        dispatch_sha = fx._canonical_sha256(host_dispatch)
        handle = _rehash(
            {
                "schema_version": "goal-teams-host-handle-v2.65",
                "adapter_id": "callback_fixture",
                "host_handle_id": "HANDLE-SCHEMA",
                "run_id": run_id,
                "node_id": "A",
                "attempt": 1,
                "transport": "thread_future",
                "proof_strength": "fixture_only",
                "dispatch_sha256": dispatch_sha,
                "state": "prepared",
                "prepared_at": "2026-08-22T10:02:01Z",
            },
            "handle_sha256",
        )
        execution = _rehash(
            {
                "schema_version": "goal-teams-host-execution-receipt-v2.65",
                "adapter_id": "callback_fixture",
                "host_handle_id": "HANDLE-SCHEMA",
                "handle_sha256": handle["handle_sha256"],
                "dispatch_sha256": dispatch_sha,
                "state": "running",
                "started_at": "2026-08-22T10:02:02Z",
                "proof_strength": "fixture_only",
            },
            "receipt_sha256",
        )
        probe = _rehash(
            {
                "schema_version": "goal-teams-host-probe-receipt-v2.65",
                "adapter_id": "callback_fixture",
                "host_handle_id": "HANDLE-SCHEMA",
                "run_id": run_id,
                "node_id": "A",
                "attempt": 1,
                "observed_state": "running",
                "quiescent": False,
                "observed_at": "2026-08-22T10:02:03Z",
                "evidence_refs": ["evidence:probe"],
            },
            "receipt_sha256",
        )
        payloads: dict[str, tuple[str | None, int, dict[str, object]]] = {
            "run.created": (None, 0, {"graph_receipt_sha256": graph["receipt_sha256"]}),
            "gate.passed": (None, 0, {"gate_id": gate["gate_id"], "gate_receipt": gate, "gate_decision_sha256": gate["receipt_sha256"], "decision": "passed"}),
            "gate.rejected": (None, 0, {"gate_id": gate["gate_id"], "gate_receipt": {**gate, "decision": "rejected"}, "gate_decision_sha256": gate["receipt_sha256"], "decision": "rejected"}),
            "gate.timed_out": (None, 0, {"gate_id": gate["gate_id"], "deadline": "2026-08-22T10:03:00Z", "on_timeout_outcome": "blocked"}),
            "node.ready": ("A", 1, {"satisfied_edge_ids": [], "fan_in_mode": "root", "required_edge_count": 0, "satisfied_edge_count": 0}),
            "node.claimed": ("A", 1, {"worker_id": "WORKER-A", "lease_id": "LEASE-A", "lease_expires_at": "2026-08-22T10:10:00Z"}),
            "node.started": ("A", 1, {"owner_run_id": "RUN-OWNER-A", "validator_run_id": "RUN-VALIDATOR-A", "member_packet": dispatch["packet"], "context_bundle_sha256": dispatch["context"]["bundle_sha256"], "capability_receipt": dispatch["capability"], "capability_request": dispatch["request"], "capability_decision": dispatch["decision"], "host_handle_id": "HANDLE-SCHEMA"}),
            "node.heartbeat": ("A", 1, {"lease_id": "LEASE-A", "previous_expires_at": "2026-08-22T10:10:00Z", "new_expires_at": "2026-08-22T10:11:00Z"}),
            "node.outcome_recorded": ("A", 1, {"outcome": "completed", "owner_run_id": "RUN-OWNER-A", "artifact_receipts": [artifact]}),
            "node.validation_recorded": ("A", 1, {"validation_state": "passed", "validator_run_id": "RUN-VALIDATOR-A", "validation_receipt": validation, "observed_outcome": "completed"}),
            "node.blocked": ("A", 1, {"blocker_id": "BLOCK-A"}),
            "node.interrupted": ("A", 1, {"interrupt_id": "INT-SCHEMA", "gate_id": "gate:human:A", "reason": "approval", "capability_receipt_sha256": dispatch["capability"]["receipt_sha256"]}),
            "node.resumed": ("A", 1, {"interrupt_id": "INT-SCHEMA", "approval_receipt": approval, "approval_decision": approval_decision, "decision": "approve"}),
            "node.cancelled": ("A", 1, {"reason": "cancelled"}),
            "node.lease_expired": ("A", 1, {"lease_id": "LEASE-A", "lease_expires_at": "2026-08-22T10:01:00Z", "recovery_decision": "ready"}),
            "node.retry_scheduled": ("A", 1, {"source_edge_id": "retry_policy:A", "traversal_count": 1, "next_attempt": 2}),
            "side_effect.intent": ("A", 1, {"idempotency_key": "KEY-A", "action_sha256": fx.SHA["1"]}),
            "side_effect.confirmed": ("A", 1, {"idempotency_key": "KEY-A", "result_digest": fx.SHA["2"], "readback_receipt_sha256": fx.SHA["3"]}),
            "side_effect.reconciliation_required": ("A", 1, {"idempotency_key": "KEY-A", "reason_code": "unknown"}),
            "checkpoint.created": (None, 0, {"checkpoint_revision": 1, "projection_sha256": fx.SHA["4"]}),
            "node.stale": ("A", 1, {"changed_binding_fields": ["source_sha256"]}),
            "host.prepared": ("A", 1, {"host_handle": handle, "dispatch_sha256": dispatch_sha}),
            "host.execution_started": ("A", 1, {"host_handle_sha256": handle["handle_sha256"], "execution_receipt": execution}),
            "host.observation_recorded": ("A", 1, {"observation_type": "probe", "host_handle_id": "HANDLE-SCHEMA", "observation_receipt": probe, "observation_sha256": probe["receipt_sha256"]}),
        }
        events = []
        for index, (event_type, (node_id, attempt, payload)) in enumerate(payloads.items(), 1):
            events.append(
                self.runtime.make_graph_event(
                    run_id=run_id,
                    event_id=f"SCHEMA-{index}",
                    event_seq=1,
                    event_type=event_type,
                    node_id=node_id,
                    attempt=attempt,
                    cas_base_revision=0,
                    previous_event_sha256=fx.ZERO_SHA256,
                    bindings=self.bindings,
                    payload=payload,
                    evidence_refs=["evidence:schema"],
                    actor_identity="schema-fixture",
                    actor_relationship="authorized_writer",
                    occurred_at="2026-08-22T10:02:30Z",
                )
            )
        return events

    def test_01_real_ajv2020_strict_validates_every_event_payload_matrix(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.fail("E_TEST_V265_AJV2020_UNAVAILABLE:node")
        metadata_script = """
const fs=require('fs');
try {
  const entry=require.resolve('ajv/dist/2020');
  const version=require('ajv/package.json').version;
  const crypto=require('crypto');
  const digest=crypto.createHash('sha256').update(fs.readFileSync(entry)).digest('hex');
  process.stdout.write(JSON.stringify({entry,version,digest}));
} catch (error) { process.stderr.write(String(error)); process.exit(91); }
"""
        metadata = subprocess.run(
            [node, "-e", metadata_script],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
            check=False,
        )
        if metadata.returncode != 0:
            self.fail(f"E_TEST_V265_AJV2020_UNAVAILABLE:{metadata.stderr}")
        observed = json.loads(metadata.stdout)
        self.assertEqual(AJV_VERSION, observed["version"])
        self.assertEqual(AJV_2020_ENTRY_SHA256, observed["digest"])

        schema = json.loads(
            Path("schemas/v2.65/graph-runtime.schema.json").read_text(encoding="utf-8")
        )
        valid_events = self._schema_events()
        instances: list[dict[str, object]] = []
        expectations: list[bool] = []
        for event in valid_events:
            instances.append(event)
            expectations.append(True)
            extra = copy.deepcopy(event)
            extra["payload"]["unexpected"] = True
            instances.append(extra)
            expectations.append(False)
            missing = copy.deepcopy(event)
            first_key = next(iter(missing["payload"]))
            missing["payload"].pop(first_key)
            instances.append(missing)
            expectations.append(False)

        validator_script = """
const fs=require('fs');
let Ajv2020;
try { Ajv2020=require('ajv/dist/2020').default; }
catch (error) { process.stderr.write(String(error)); process.exit(91); }
const input=JSON.parse(fs.readFileSync(0,'utf8'));
let validate;
try { validate=new Ajv2020({strict:true,allErrors:true,validateFormats:false}).compile(input.schema); }
catch (error) { process.stderr.write(String(error)); process.exit(92); }
const results=input.instances.map((item)=>({valid:validate(item),errors:validate.errors||[]}));
process.stdout.write(JSON.stringify(results));
"""
        run = subprocess.run(
            [node, "-e", validator_script],
            cwd=Path(__file__).resolve().parents[2],
            input=json.dumps({"schema": schema, "instances": instances}),
            text=True,
            capture_output=True,
            check=False,
        )
        if run.returncode != 0:
            self.fail(f"E_TEST_V265_AJV2020_UNAVAILABLE:{run.returncode}:{run.stderr}")
        results = json.loads(run.stdout)
        self.assertEqual(expectations, [item["valid"] for item in results])

    def test_02_intrinsic_graph_validator_rejects_input_derived_and_receipt_forgery(self) -> None:
        validator = getattr(self.runtime, "validate_runtime_graph_contract", None)
        self.assertTrue(callable(validator), "E_TEST_V265_RUNTIME_GRAPH_VALIDATOR_MISSING")
        receipt = validator(self.graph)
        self.assertEqual(
            {
                "schema_version",
                "graph_id",
                "graph_revision",
                "graph_contract_sha256",
                "compiled_graph_receipt_sha256",
                "derived_map_sha256",
                "validator",
                "valid",
                "receipt_sha256",
            },
            set(receipt),
        )
        self.assertTrue(receipt["valid"])

        mutations = []
        input_forgery = copy.deepcopy(self.graph)
        input_forgery["nodes"][0]["owner_identity"] = "owner:FORGED"
        input_forgery = _rehash(input_forgery, "receipt_sha256")
        mutations.append(input_forgery)

        derived_forgery = copy.deepcopy(self.graph)
        derived_forgery["predecessor_map"]["JOIN"] = ["A"]
        derived_forgery = _rehash(derived_forgery, "receipt_sha256")
        mutations.append(derived_forgery)

        receipt_forgery = copy.deepcopy(self.graph)
        receipt_forgery["receipt_sha256"] = fx.ZERO_SHA256
        mutations.append(receipt_forgery)

        for candidate in mutations:
            with self.subTest(candidate=candidate["receipt_sha256"]):
                with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
                    validator(candidate)
                self.assertEqual("E_V265_RUNTIME_GRAPH_INTEGRITY", caught.exception.code)

    def test_03_gate_oracle_recomputes_decision_evidence_condition_and_actor(self) -> None:
        run_id = "RUN-GATE-HARDENING"
        events = self._created(self.graph, run_id)
        valid = fx._gate_receipt(self.graph, run_id)
        self._gate_event(events, self.graph, run_id, valid)
        projection = self.runtime.reduce_graph_events(
            self.graph, events, expected_bindings=self.bindings
        )
        self.assertEqual("passed", projection["gate_states"]["gate:join-evidence"])

        invalid_receipts = []
        missing = copy.deepcopy(valid)
        missing["observed_facts"] = {}
        invalid_receipts.append(_rehash(missing, "receipt_sha256"))
        extra = copy.deepcopy(valid)
        extra["observed_facts"]["unexpected"] = fx.SHA["6"]
        invalid_receipts.append(_rehash(extra, "receipt_sha256"))
        non_sha = copy.deepcopy(valid)
        non_sha["observed_facts"]["validator_receipt"] = "receipt:not-a-sha"
        invalid_receipts.append(_rehash(non_sha, "receipt_sha256"))
        for receipt in invalid_receipts:
            candidate = self._created(self.graph, f"RUN-GATE-{len(receipt)}-{receipt['receipt_sha256'][:6]}")
            receipt["run_id"] = candidate[0]["run_id"]
            receipt = _rehash(receipt, "receipt_sha256")
            self._gate_event(candidate, self.graph, str(candidate[0]["run_id"]), receipt)
            with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
                self.runtime.reduce_graph_events(
                    self.graph,
                    candidate,
                    expected_bindings=self.bindings,
                )
            self.assertEqual("E_V265_RUNTIME_GATE", caught.exception.code)

        actor_events = self._created(self.graph, "RUN-GATE-ACTOR")
        actor_receipt = fx._gate_receipt(self.graph, "RUN-GATE-ACTOR")
        self._gate_event(
            actor_events,
            self.graph,
            "RUN-GATE-ACTOR",
            actor_receipt,
            actor="forged:authority",
        )
        with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
            self.runtime.reduce_graph_events(
                self.graph, actor_events, expected_bindings=self.bindings
            )
        self.assertEqual("E_V265_RUNTIME_GATE", caught.exception.code)

        def condition_mutator(document: dict[str, object]) -> None:
            gate = next(item for item in document["gates"] if item["gate_id"] == "gate:join-evidence")
            gate.update(
                {
                    "gate_type": "condition",
                    "required_evidence_types": [],
                    "condition": {
                        "fact_ref": "fact:approved",
                        "operator": "equals",
                        "expected_value": True,
                    },
                }
            )

        condition_graph = _compiled_document(condition_mutator)
        condition_bindings = fx._bindings(condition_graph)
        condition_events = self._created(condition_graph, "RUN-CONDITION")
        condition_receipt = _rehash(
            {
                "schema_version": "goal-teams-gate-receipt-v2.65",
                "receipt_id": "GATE-CONDITION",
                "graph_contract_sha256": condition_graph["receipt_sha256"],
                "run_id": "RUN-CONDITION",
                "gate_id": "gate:join-evidence",
                "gate_type": "condition",
                "decision": "passed",
                "authority_identity": "condition:evaluator",
                "actor_relationship": "correlated",
                "evidence_refs": ["evidence:condition"],
                "observed_facts": {
                    "fact_ref": "fact:approved",
                    "operator": "equals",
                    "expected_value": True,
                    "observed_value": False,
                    "matched": True,
                },
                "issued_at": "2026-08-22T10:00:00Z",
                "expires_at": "2026-08-22T11:00:00Z",
            },
            "receipt_sha256",
        )
        self._gate_event(
            condition_events,
            condition_graph,
            "RUN-CONDITION",
            condition_receipt,
        )
        with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
            self.runtime.reduce_graph_events(
                condition_graph,
                condition_events,
                expected_bindings=condition_bindings,
            )
        self.assertEqual("E_V265_RUNTIME_GATE", caught.exception.code)

    def test_04_external_approval_is_reducer_validated_and_satisfies_human_edge(self) -> None:
        def human_edge_mutator(document: dict[str, object]) -> None:
            edges = document["edges"]
            dependency = next(item for item in edges if item["edge_id"] == "dep:A:JOIN")
            dependency.update(
                {
                    "edge_type": "human_approved",
                    "gate_ref": "gate:human:A",
                    "accepted_outcomes": ["completed"],
                }
            )

        graph = _compiled_document(human_edge_mutator)
        bindings = fx._bindings(graph)
        run_id = "RUN-HUMAN-EDGE"
        events = self._created(graph, run_id)
        dispatch = self._start(events, graph, run_id, "A")
        interrupt_id = "INT-HUMAN-A"
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.interrupted",
            node_id="A",
            attempt=1,
            payload={
                "interrupt_id": interrupt_id,
                "gate_id": "gate:human:A",
                "reason": "human approval",
                "capability_receipt_sha256": dispatch["capability"]["receipt_sha256"],
            },
            actor="runtime_controller",
        )
        approval = fx._approval_receipt(graph, "A", interrupt_id=interrupt_id)
        decision = fx._ExternalApprovalHost().verify_approval(
            {
                "run_id": run_id,
                "interrupt_id": interrupt_id,
                "node_id": "A",
                "gate_id": "gate:human:A",
                "state": "waiting_user",
                "approval_receipt_sha256": None,
                "updated_at": "2026-08-22T10:02:05Z",
            },
            approval,
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.resumed",
            node_id="A",
            attempt=1,
            payload={
                "interrupt_id": interrupt_id,
                "approval_receipt": approval,
                "approval_decision": decision,
                "decision": "approve",
            },
            actor="runtime_controller",
        )
        self._start(events, graph, run_id, "A", attempt=2)
        self._record_outcome(
            events, graph, run_id, "A", attempt=2, outcome="completed", validate=True
        )
        self._start(events, graph, run_id, "B")
        self._record_outcome(
            events, graph, run_id, "B", attempt=1, outcome="completed", validate=True
        )
        gate = fx._gate_receipt(graph, run_id)
        self._gate_event(events, graph, run_id, gate)
        projection = self.runtime.reduce_graph_events(
            graph, events, expected_bindings=bindings
        )
        self.assertEqual("passed", projection["gate_states"]["gate:human:A"])
        ready = self.runtime.evaluate_next(
            graph,
            events,
            expected_bindings=bindings,
            now="2026-08-22T10:10:00Z",
        )
        self.assertEqual(["JOIN"], [item["node_id"] for item in ready])

        forged = copy.deepcopy(events)
        resume_event = next(item for item in forged if item["event_type"] == "node.resumed")
        resume_event["payload"]["approval_decision"]["issuer_assurance"] = "repository_fixture"
        resume_event["payload"]["approval_decision"] = _rehash(
            resume_event["payload"]["approval_decision"], "decision_sha256"
        )
        forged_index = forged.index(resume_event)
        forged[forged_index] = fx._rehash_event(resume_event)
        forged = forged[: forged_index + 1]
        with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
            self.runtime.reduce_graph_events(graph, forged, expected_bindings=bindings)
        self.assertEqual("E_V265_RUNTIME_GATE", caught.exception.code)

    def test_05_required_data_cannot_be_bypassed_by_any_or_quorum(self) -> None:
        for mode in ("any", "quorum"):
            def fan_mutator(document: dict[str, object], selected: str = mode) -> None:
                join = next(item for item in document["nodes"] if item["node_id"] == "JOIN")
                join["fan_in"].update(
                    {
                        "mode": selected,
                        "quorum_count": 1 if selected == "quorum" else None,
                        "quorum_ratio_basis_points": None,
                    }
                )

            graph = _compiled_document(fan_mutator)
            bindings = fx._bindings(graph)
            run_id = f"RUN-DATA-{mode.upper()}"
            events = self._created(graph, run_id)
            self._start(events, graph, run_id, "B")
            self._record_outcome(
                events,
                graph,
                run_id,
                "B",
                attempt=1,
                outcome="completed",
                validate=True,
            )
            gate = fx._gate_receipt(graph, run_id)
            self._gate_event(events, graph, run_id, gate)
            ready = self.runtime.evaluate_next(
                graph,
                events,
                expected_bindings=bindings,
                now="2026-08-22T10:10:00Z",
            )
            self.assertNotIn(
                "JOIN",
                [item["node_id"] for item in ready],
                f"{mode} control fan-in bypassed required Data",
            )

    def test_06_retry_policy_sentinel_enforces_validation_backoff_and_budget(self) -> None:
        def backoff_mutator(document: dict[str, object]) -> None:
            node = next(item for item in document["nodes"] if item["node_id"] == "A")
            node["recovery_policy"] = {"mode": "retry", "edge_id": None}
            node["retry_policy"]["backoff_seconds"] = [10]

        graph = _compiled_document(backoff_mutator)
        bindings = fx._bindings(graph)
        run_id = "RUN-RETRY-SENTINEL"
        events = self._created(graph, run_id)
        self._start(events, graph, run_id, "A")
        self._record_outcome(
            events,
            graph,
            run_id,
            "A",
            attempt=1,
            outcome="failed",
            validate=False,
        )
        invalid = copy.deepcopy(events)
        self._append(
            invalid,
            graph,
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id="A",
            attempt=1,
            payload={
                "source_edge_id": "retry_policy:OTHER",
                "traversal_count": 1,
                "next_attempt": 2,
            },
            actor="runtime_controller",
            occurred_at="2026-08-22T10:02:07Z",
        )
        with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
            self.runtime.reduce_graph_events(graph, invalid, expected_bindings=bindings)
        self.assertEqual("E_V265_RUNTIME_ATTEMPT_BUDGET", caught.exception.code)

        too_early = copy.deepcopy(events)
        self._append(
            too_early,
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
            occurred_at="2026-08-22T10:02:08Z",
        )
        with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
            self.runtime.reduce_graph_events(graph, too_early, expected_bindings=bindings)
        self.assertEqual("E_V265_RUNTIME_ATTEMPT_BUDGET", caught.exception.code)

        after_backoff = copy.deepcopy(events)
        self._append(
            after_backoff,
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
            occurred_at="2026-08-22T10:03:00Z",
        )
        projection = self.runtime.reduce_graph_events(
            graph, after_backoff, expected_bindings=bindings
        )
        self.assertEqual("ready", projection["nodes"]["A"]["execution_state"])

    def test_07_recovery_edge_activates_target_and_requires_passed_source_validation(self) -> None:
        def recovery_mutator(document: dict[str, object]) -> None:
            document["edges"].append(
                fx._edge(
                    "recovery:B:A",
                    "recovery",
                    "B",
                    "A",
                    accepted_outcomes=["failed"],
                )
            )
            document["edges"][-1]["traversal_budget"] = 1
            node_b = next(item for item in document["nodes"] if item["node_id"] == "B")
            node_b["recovery_policy"] = {"mode": "edge", "edge_id": "recovery:B:A"}

        graph = _compiled_document(recovery_mutator)
        bindings = fx._bindings(graph)
        run_id = "RUN-RECOVERY-TARGET"
        events = self._created(graph, run_id)
        self._start(events, graph, run_id, "A")
        self._record_outcome(
            events,
            graph,
            run_id,
            "A",
            attempt=1,
            outcome="completed",
            validate=True,
        )
        self._start(events, graph, run_id, "B")
        self._record_outcome(
            events,
            graph,
            run_id,
            "B",
            attempt=1,
            outcome="failed",
            validate=True,
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id="B",
            attempt=1,
            payload={
                "source_edge_id": "recovery:B:A",
                "traversal_count": 1,
                "next_attempt": 2,
            },
            actor="runtime_controller",
            occurred_at="2026-08-22T10:10:00Z",
        )
        projection = self.runtime.reduce_graph_events(
            graph, events, expected_bindings=bindings
        )
        self.assertEqual("terminal", projection["nodes"]["B"]["execution_state"])
        self.assertEqual("ready", projection["nodes"]["A"]["execution_state"])
        self.assertEqual(1, projection["traversal_counts"]["recovery:B:A"])

        exhausted = copy.deepcopy(events[:-1])
        self._append(
            exhausted,
            graph,
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id="B",
            attempt=1,
            payload={
                "source_edge_id": "recovery:B:A",
                "traversal_count": 2,
                "next_attempt": 2,
            },
            actor="runtime_controller",
            occurred_at="2026-08-22T10:10:00Z",
        )
        with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
            self.runtime.reduce_graph_events(graph, exhausted, expected_bindings=bindings)
        self.assertEqual("E_V265_RUNTIME_ATTEMPT_BUDGET", caught.exception.code)

    def test_08_host_events_are_canonical_and_derive_host_projection(self) -> None:
        graph = self.graph
        bindings = self.bindings
        run_id = "RUN-HOST-EVENTS"
        events = self._created(graph, run_id)
        dispatch = fx._dispatch_evidence(graph, run_id, "A", self.workspace)
        host_dispatch = {
            "schema_version": "goal-teams-host-dispatch-v2.65",
            "run_id": run_id,
            "node_id": "A",
            "task_id": "A",
            "attempt": 1,
            "action_ref": "action:A",
            "member_packet": dispatch["packet"],
            "context_bundle": dispatch["context"],
            "capability_receipt": dispatch["capability"],
            "capability_decision": dispatch["decision"],
            "idempotency_key": "KEY-HOST-EVENTS",
        }
        dispatch_sha = fx._canonical_sha256(host_dispatch)
        handle = _rehash(
            {
                "schema_version": "goal-teams-host-handle-v2.65",
                "adapter_id": "callback_fixture",
                "host_handle_id": "HANDLE-HOST-EVENTS",
                "run_id": run_id,
                "node_id": "A",
                "attempt": 1,
                "transport": "thread_future",
                "proof_strength": "fixture_only",
                "dispatch_sha256": dispatch_sha,
                "state": "prepared",
                "prepared_at": "2026-08-22T10:02:02Z",
            },
            "handle_sha256",
        )
        execution = _rehash(
            {
                "schema_version": "goal-teams-host-execution-receipt-v2.65",
                "adapter_id": "callback_fixture",
                "host_handle_id": handle["host_handle_id"],
                "handle_sha256": handle["handle_sha256"],
                "dispatch_sha256": dispatch_sha,
                "state": "running",
                "started_at": "2026-08-22T10:02:05Z",
                "proof_strength": "fixture_only",
            },
            "receipt_sha256",
        )
        probe = _rehash(
            {
                "schema_version": "goal-teams-host-probe-receipt-v2.65",
                "adapter_id": "callback_fixture",
                "host_handle_id": handle["host_handle_id"],
                "run_id": run_id,
                "node_id": "A",
                "attempt": 1,
                "observed_state": "running",
                "quiescent": False,
                "observed_at": "2026-08-22T10:02:06Z",
                "evidence_refs": ["evidence:probe"],
            },
            "receipt_sha256",
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.ready",
            node_id="A",
            attempt=1,
            payload={"satisfied_edge_ids": [], "fan_in_mode": "root", "required_edge_count": 0, "satisfied_edge_count": 0},
            actor="runtime_controller",
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.claimed",
            node_id="A",
            attempt=1,
            payload={"worker_id": "WORKER-A", "lease_id": "LEASE-A", "lease_expires_at": "2026-08-22T10:20:00Z"},
            actor="runtime_controller",
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="host.prepared",
            node_id="A",
            attempt=1,
            payload={"host_handle": handle, "dispatch_sha256": dispatch_sha},
            actor="runtime_controller",
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.started",
            node_id="A",
            attempt=1,
            payload={"owner_run_id": "RUN-OWNER-A", "validator_run_id": "RUN-VALIDATOR-A", "member_packet": dispatch["packet"], "context_bundle_sha256": dispatch["context"]["bundle_sha256"], "capability_receipt": dispatch["capability"], "capability_request": dispatch["request"], "capability_decision": dispatch["decision"], "host_handle_id": handle["host_handle_id"]},
            actor="RUN-OWNER-A",
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="host.execution_started",
            node_id="A",
            attempt=1,
            payload={"host_handle_sha256": handle["handle_sha256"], "execution_receipt": execution},
            actor="runtime_controller",
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="host.observation_recorded",
            node_id="A",
            attempt=1,
            payload={"observation_type": "probe", "host_handle_id": handle["host_handle_id"], "observation_receipt": probe, "observation_sha256": probe["receipt_sha256"]},
            actor="runtime_controller",
        )
        try:
            projection = self.runtime.reduce_graph_events(
                graph, events, expected_bindings=bindings
            )
        except self.runtime.GraphRuntimeError as exc:
            self.fail(f"E_TEST_V265_HOST_EVENTS_NOT_IMPLEMENTED:{exc.code}")
        self.assertEqual("confirmed", projection["nodes"]["A"]["host_binding_assurance"])
        self.assertEqual(handle["host_handle_id"], projection["nodes"]["A"]["host_handle_id"])
        self.assertEqual("running", projection["host_handles"][handle["host_handle_id"]]["state"])
        self.assertEqual(
            probe["receipt_sha256"],
            projection["host_handles"][handle["host_handle_id"]]["last_observation_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
