from __future__ import annotations

import copy
import hashlib
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Mapping

from scripts.v265.canonical import canonical_sha256
from scripts.v265.graph_runtime import GraphRuntimeError, reduce_graph_events
from scripts.v265.host_adapter import CallbackHostAdapter, HostAdapterError
from scripts.v265.runtime_controller import RuntimeController
from scripts.v265.runtime_store import RuntimeStoreError, SQLiteRuntimeStore
from tests.v265 import test_graph_runtime as base


ARCHITECTURE_SHA256 = "5f350bae868f842bc02d00b67ba44c577765c3f9a7f9ed080ada31e81f3c486f"
HARDENING_PLAN_REVISION = 3
HARDENING_TASK_EXACT_SET_SHA256 = (
    "d0f5bbf75cadf24338028d477b0e1ccc40c29b8aeb0c642cdc988d2600ebf496"
)


def _rehash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(dict(value))
    result[field] = canonical_sha256(
        {key: item for key, item in result.items() if key != field}
    )
    return result


def _required_method(value: object, name: str) -> Any:
    method = getattr(value, name, None)
    if not callable(method):
        raise AssertionError(f"E_TEST_H265_TARGET_MISSING:{type(value).__name__}.{name}")
    return method


def _compile_graph(
    *,
    optional_a_output: bool = False,
    external_a: bool = False,
    retry_a: bool = False,
) -> dict[str, object]:
    source, compiled_plan, validation = base._authoritative_plan()
    document = base._graph_document(source, compiled_plan, validation)
    node_a = next(item for item in document["nodes"] if item["node_id"] == "A")
    action_a = next(
        item for item in document["actions"] if item["action_id"] == "action:A"
    )
    if optional_a_output:
        node_a["output_ports"][0]["required"] = False
    if external_a:
        action_a["effect"] = "external_write"
        action_a["idempotency_required"] = True
    if retry_a:
        node_a["recovery_policy"] = {"mode": "retry", "edge_id": None}
    from scripts.v265.graph_contract import compile_graph_contract

    return compile_graph_contract(
        document,
        compiled_task_plan=compiled_plan,
        task_plan_validation_receipt=validation,
    )


def _external_capability(
    graph: dict[str, object], node_id: str, workspace: Path
) -> dict[str, object]:
    capability = base._capability(graph, node_id, workspace)
    capability.update(
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
    return _rehash(capability, "receipt_sha256")


def _dispatch(
    graph: dict[str, object],
    workspace: Path,
    *,
    run_id: str = "RUN-DIRECT-DISPATCH",
    capability: dict[str, object] | None = None,
) -> dict[str, object]:
    evidence = base._dispatch_evidence(graph, run_id, "A", workspace)
    if capability is not None:
        evidence["capability"] = capability
        evidence["request"] = base._capability_request(
            graph,
            "A",
            evidence["context"],
            capability,
            run_id=run_id,
            attempt=1,
        )
        evidence["decision"] = base._capability_decision(
            evidence["request"], capability
        )
        evidence["packet"] = base._member_packet(
            graph,
            "A",
            evidence["context"],
            evidence["context_validation"],
            capability,
            evidence["request"],
            evidence["decision"],
        )
    return {
        "schema_version": "goal-teams-host-dispatch-v2.65",
        "run_id": run_id,
        "node_id": "A",
        "task_id": "A",
        "attempt": 1,
        "action_ref": "action:A",
        "member_packet": evidence["packet"],
        "context_bundle": evidence["context"],
        "capability_receipt": evidence["capability"],
        "capability_decision": evidence["decision"],
        "idempotency_key": "KEY-AUTHORITY-A-1",
    }


class _LifecycleHost:
    """Host-neutral fake: observable local lifecycle, never real authority."""

    def __init__(
        self,
        graph: dict[str, object],
        *,
        store: SQLiteRuntimeStore | None = None,
        timeout: bool = False,
        cancel_state: str = "cancelled",
        probe_state: str = "cancelled",
        readback_state: str = "confirmed",
        outcomes: Mapping[str, str] | None = None,
    ) -> None:
        self.graph = graph
        self.store = store
        self.timeout = timeout
        self.cancel_state = cancel_state
        self.probe_state = probe_state
        self.readback_state = readback_state
        self.outcomes = dict(outcomes or {})
        self.calls: list[tuple[str, str]] = []
        self.execute_event_types: list[list[str]] = []
        self.execute_count: dict[str, int] = {}
        self._handles: dict[str, dict[str, object]] = {}
        self._dispatches: dict[str, dict[str, object]] = {}

    @property
    def adapter_id(self) -> str:
        return "hardening-fake-host"

    @property
    def proof_strength(self) -> str:
        return "externally_attested"

    @property
    def trusted_issuer_ids(self) -> frozenset[str]:
        return frozenset(
            {"callback_fixture", "external-human-authority", "external-capability-authority"}
        )

    def verify_capability(
        self, request: Mapping[str, Any], capability_receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        return base._capability_decision(dict(request), dict(capability_receipt))

    def prepare(
        self, dispatch: Mapping[str, Any], *, prepared_at: str
    ) -> dict[str, Any]:
        dispatch_value = copy.deepcopy(dict(dispatch))
        dispatch_sha256 = canonical_sha256(dispatch_value)
        node_id = str(dispatch_value["node_id"])
        attempt = int(dispatch_value["attempt"])
        handle_id = f"HANDLE-{dispatch_value['run_id']}-{node_id}-{attempt}"
        handle: dict[str, Any] = {
            "schema_version": "goal-teams-host-handle-v2.65",
            "adapter_id": self.adapter_id,
            "host_handle_id": handle_id,
            "run_id": dispatch_value["run_id"],
            "node_id": node_id,
            "attempt": attempt,
            "transport": "hardening_fake",
            "proof_strength": self.proof_strength,
            "dispatch_sha256": dispatch_sha256,
            "state": "prepared",
            "prepared_at": prepared_at,
        }
        handle["handle_sha256"] = canonical_sha256(handle)
        self._handles[handle_id] = copy.deepcopy(handle)
        self._dispatches[handle_id] = dispatch_value
        self.calls.append(("prepare", node_id))
        return copy.deepcopy(handle)

    def execute(
        self,
        handle: Mapping[str, Any],
        dispatch: Mapping[str, Any],
        *,
        started_at: str,
    ) -> dict[str, Any]:
        handle_value = dict(handle)
        dispatch_value = dict(dispatch)
        handle_id = str(handle_value["host_handle_id"])
        node_id = str(handle_value["node_id"])
        stored = self._handles.get(handle_id)
        if stored is None or stored["state"] != "prepared":
            raise HostAdapterError("E_V265_HOST_LIFECYCLE", "handle is not prepared")
        if stored["dispatch_sha256"] != canonical_sha256(dispatch_value):
            raise HostAdapterError("E_V265_HOST_CAPABILITY", "Dispatch digest differs")
        if self.store is not None:
            event_types = [
                event["event_type"]
                for event in self.store.load_events(str(handle_value["run_id"]))
            ]
            self.execute_event_types.append(event_types)
        stored["state"] = "running"
        self.execute_count[node_id] = self.execute_count.get(node_id, 0) + 1
        self.calls.append(("execute", node_id))
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-host-execution-receipt-v2.65",
            "adapter_id": self.adapter_id,
            "host_handle_id": handle_id,
            "handle_sha256": handle_value["handle_sha256"],
            "dispatch_sha256": stored["dispatch_sha256"],
            "state": "running",
            "started_at": started_at,
            "proof_strength": self.proof_strength,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def spawn(self, dispatch: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append(("legacy_spawn", str(dispatch["node_id"])))
        handle = self.prepare(dispatch, prepared_at="2026-08-22T10:00:02Z")
        self.execute(handle, dispatch, started_at="2026-08-22T10:00:02Z")
        return handle

    def wait(
        self, handle: Mapping[str, Any], *, timeout_seconds: int
    ) -> dict[str, Any]:
        if self.timeout:
            raise HostAdapterError("E_V265_HOST_TIMEOUT", "fake wait timed out")
        handle_value = dict(handle)
        node_id = str(handle_value["node_id"])
        outcome = self.outcomes.get(node_id, "completed")
        artifacts = (
            [
                base._artifact(
                    self.graph,
                    str(handle_value["run_id"]),
                    node_id,
                    int(handle_value["attempt"]),
                )
            ]
            if outcome == "completed"
            else []
        )
        self._handles[str(handle_value["host_handle_id"])]["state"] = "terminal"
        result: dict[str, Any] = {
            "schema_version": "goal-teams-host-outcome-v2.65",
            "host_handle_id": handle_value["host_handle_id"],
            "outcome": outcome,
            "artifact_receipts": artifacts,
            "evidence_refs": [f"evidence:fake:{node_id}"],
            "side_effects": [],
            "started_at": "2026-08-22T10:00:02Z",
            "finished_at": "2026-08-22T10:00:03Z",
        }
        result["observation_sha256"] = canonical_sha256(result)
        self.calls.append(("wait", node_id))
        return result

    def readback(
        self,
        handle: Mapping[str, Any],
        dispatch: Mapping[str, Any],
        outcome: Mapping[str, Any],
        *,
        observed_at: str,
    ) -> dict[str, Any]:
        handle_value = dict(handle)
        dispatch_value = dict(dispatch)
        confirmed = self.readback_state == "confirmed"
        result_digest = hashlib.sha256(b"external-result").hexdigest() if confirmed else None
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-host-side-effect-readback-v2.65",
            "adapter_id": self.adapter_id,
            "host_handle_id": handle_value["host_handle_id"],
            "handle_sha256": handle_value["handle_sha256"],
            "dispatch_sha256": canonical_sha256(dispatch_value),
            "run_id": dispatch_value["run_id"],
            "node_id": dispatch_value["node_id"],
            "attempt": dispatch_value["attempt"],
            "idempotency_key": dispatch_value["idempotency_key"],
            "action_sha256": canonical_sha256(
                next(
                    action
                    for action in self.graph["actions"]
                    if action["action_id"] == dispatch_value["action_ref"]
                )
            ),
            "observed_state": self.readback_state,
            "result_digest": result_digest,
            "external_receipt_ref": "external:receipt:1" if confirmed else None,
            "issuer": "external-capability-authority" if confirmed else None,
            "issuer_assurance": "externally_attested" if confirmed else None,
            "proof_strength": "externally_attested" if confirmed else None,
            "attestation_ref": "external-attestation:readback:1" if confirmed else None,
            "observed_at": observed_at,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        self.calls.append(("readback", str(dispatch_value["node_id"])))
        return receipt

    def probe_handle(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
        host_handle_id: str,
        observed_at: str,
    ) -> dict[str, Any]:
        state = self.probe_state
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-host-probe-receipt-v2.65",
            "adapter_id": self.adapter_id,
            "host_handle_id": host_handle_id,
            "run_id": run_id,
            "node_id": node_id,
            "attempt": attempt,
            "observed_state": state,
            "quiescent": state in {"terminal", "cancelled", "absent"},
            "observed_at": observed_at,
            "evidence_refs": ["evidence:fake-probe"],
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        self.calls.append(("probe", node_id))
        return receipt

    def cancel(self, handle: Mapping[str, Any]) -> dict[str, Any]:
        state = self.cancel_state
        result: dict[str, Any] = {
            "schema_version": "goal-teams-host-cancel-result-v2.65",
            "host_handle_id": handle["host_handle_id"],
            "cancelled": state in {"cancelled_before_start", "cancelled"},
            "observed_state": state,
            "reason_code": "fake_cancel_observation",
        }
        result["decision_sha256"] = canonical_sha256(result)
        self.calls.append(("cancel", str(handle["node_id"])))
        return result

    def verify_approval(
        self, interrupt: Mapping[str, Any], approval_receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        return base._ExternalApprovalHost().verify_approval(
            dict(interrupt), dict(approval_receipt)
        )


class TestH265RuntimeExecutionAuthority(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp.name).resolve()
        self.workspace = self.runtime_root / "workspace"
        for node_id in ("A", "B", "JOIN"):
            (self.workspace / "scope" / node_id).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _store(self, name: str) -> SQLiteRuntimeStore:
        return SQLiteRuntimeStore(
            self.runtime_root / f"{name}.sqlite3",
            runtime_root=self.runtime_root,
            busy_timeout_ms=5000,
        )

    def _controller(
        self,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        host: object,
        *,
        max_workers: int = 1,
        authorized_root: Path | None = None,
    ) -> RuntimeController:
        kwargs: dict[str, object] = {
            "compiled_graph": graph,
            "store": store,
            "host_adapter": host,
            "run_bindings": base._bindings(graph),
            "max_workers": max_workers,
        }
        if authorized_root is not None:
            kwargs["authorized_workspace_root"] = authorized_root
        try:
            return RuntimeController(**kwargs)
        except TypeError as exc:
            if authorized_root is not None and "authorized_workspace_root" in str(exc):
                raise AssertionError(
                    "E_TEST_H265_TARGET_MISSING:RuntimeController.authorized_workspace_root"
                ) from exc
            raise

    def _append_root_ready(
        self,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        run_id: str,
        *,
        node_id: str = "A",
    ) -> int:
        runtime = __import__("scripts.v265.graph_runtime", fromlist=["make_graph_event"])
        head = store.read_run_head(run_id)
        event = base._make_event(
            runtime,
            compiled_graph=graph,
            run_id=run_id,
            event_seq=head["revision"] + 1,
            event_type="node.ready",
            node_id=node_id,
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
        store.append_event(run_id, event, expected_revision=head["revision"])
        return head["revision"] + 1

    def test_callback_prepare_validates_dispatch_and_lifecycle(self) -> None:
        graph = _compile_graph()
        adapter = CallbackHostAdapter(
            {"action:A": lambda dispatch: {"outcome": "completed", "artifact_receipts": [], "evidence_refs": ["evidence:A"], "side_effects": []}},
            adapter_id="callback_fixture",
            max_workers=1,
            clock=lambda: "2026-08-22T10:00:04Z",
        )
        try:
            prepare = _required_method(adapter, "prepare")
            execute = _required_method(adapter, "execute")
            dispatch = _dispatch(graph, self.workspace)
            handle = prepare(dispatch, prepared_at="2026-08-22T10:00:01Z")
            self.assertEqual("prepared", handle["state"])

            tampered_decision = copy.deepcopy(dispatch)
            tampered_decision["capability_decision"]["verified"] = False
            tampered_decision["capability_decision"] = _rehash(
                tampered_decision["capability_decision"], "decision_sha256"
            )
            with self.assertRaises(HostAdapterError) as caught:
                prepare(tampered_decision, prepared_at="2026-08-22T10:00:01Z")
            self.assertEqual("E_V265_HOST_CAPABILITY", caught.exception.code)

            tampered_packet = copy.deepcopy(dispatch)
            tampered_packet["member_packet"]["node_id"] = "B"
            tampered_packet["member_packet"] = _rehash(
                tampered_packet["member_packet"], "packet_sha256"
            )
            with self.assertRaises(HostAdapterError) as caught:
                prepare(tampered_packet, prepared_at="2026-08-22T10:00:01Z")
            self.assertEqual("E_V265_HOST_CAPABILITY", caught.exception.code)

            execution = execute(
                handle, dispatch, started_at="2026-08-22T10:00:02Z"
            )
            self.assertEqual("running", execution["state"])
            with self.assertRaises(HostAdapterError) as caught:
                execute(handle, dispatch, started_at="2026-08-22T10:00:03Z")
            self.assertEqual("E_V265_HOST_LIFECYCLE", caught.exception.code)
            adapter.wait(handle, timeout_seconds=1)
        finally:
            adapter.close()

    def test_controller_consumes_intrinsic_graph_validator(self) -> None:
        graph = _compile_graph()
        forged = copy.deepcopy(graph)
        forged["nodes"][0]["scope_allowlist"] = ["scope/forged/**"]
        store = self._store("forged-graph")
        try:
            with self.assertRaises(GraphRuntimeError) as caught:
                self._controller(forged, store, _LifecycleHost(forged))
            self.assertEqual("E_V265_RUNTIME_GRAPH_INTEGRITY", caught.exception.code)
        finally:
            store.close()

    def test_prepare_is_inert_and_execute_follows_durable_host_events(self) -> None:
        graph = _compile_graph()
        store = self._store("durable-order")
        host = _LifecycleHost(graph, store=store)
        try:
            controller = self._controller(graph, store, host, max_workers=1)
            controller.create_run(run_id="RUN-DURABLE-ORDER", created_at="2026-08-22T10:00:00Z")
            controller.run_ready_wave(
                run_id="RUN-DURABLE-ORDER",
                dispatch_inputs=base._dispatch_inputs(graph, self.workspace),
                now="2026-08-22T10:00:02Z",
                expected_revision=store.read_run_head("RUN-DURABLE-ORDER")["revision"],
            )
            self.assertNotIn("legacy_spawn", [name for name, _ in host.calls])
            self.assertTrue(host.execute_event_types)
            for event_types in host.execute_event_types:
                self.assertIn("host.prepared", event_types)
                self.assertIn("node.started", event_types)
                self.assertLess(
                    event_types.index("host.prepared"), event_types.index("node.started")
                )
        finally:
            store.close()

    def test_trusted_workspace_root_rejects_escape_and_symlink(self) -> None:
        graph = _compile_graph()
        for name, workspace_realpath in (
            ("escape", Path("/etc")),
            ("symlink", self.runtime_root / "workspace-link"),
        ):
            with self.subTest(path_case=name):
                if name == "symlink":
                    workspace_realpath.symlink_to(self.workspace, target_is_directory=True)
                store = self._store(f"workspace-{name}")
                host = _LifecycleHost(graph)
                try:
                    controller = self._controller(
                        graph,
                        store,
                        host,
                        authorized_root=self.workspace,
                    )
                    controller.create_run(
                        run_id=f"RUN-WORKSPACE-{name.upper()}",
                        created_at="2026-08-22T10:00:00Z",
                    )
                    revision = store.read_run_head(
                        f"RUN-WORKSPACE-{name.upper()}"
                    )["revision"]
                    ready = base._make_event(
                        __import__("scripts.v265.graph_runtime", fromlist=["make_graph_event"]),
                        compiled_graph=graph,
                        run_id=f"RUN-WORKSPACE-{name.upper()}",
                        event_seq=revision + 1,
                        event_type="node.ready",
                        node_id="A",
                        attempt=1,
                        previous_event_sha256=store.read_run_head(
                            f"RUN-WORKSPACE-{name.upper()}"
                        )["last_event_sha256"],
                        payload={"satisfied_edge_ids": [], "fan_in_mode": "root", "required_edge_count": 0, "satisfied_edge_count": 0},
                        actor_identity="goal_lead",
                    )
                    store.append_event(
                        f"RUN-WORKSPACE-{name.upper()}", ready, expected_revision=revision
                    )
                    claim = controller.claim_node(
                        run_id=f"RUN-WORKSPACE-{name.upper()}",
                        node_id="A",
                        worker_id="WORKER-A",
                        lease_seconds=30,
                        now="2026-08-22T10:00:01Z",
                        expected_revision=revision + 1,
                    )
                    context, validation = base._context_bundle(graph, "A")
                    capability = base._capability(graph, "A", self.workspace)
                    capability["workspace_realpath"] = str(workspace_realpath)
                    capability = _rehash(capability, "receipt_sha256")
                    with self.assertRaises(GraphRuntimeError) as caught:
                        controller.start_node(
                            run_id=f"RUN-WORKSPACE-{name.upper()}",
                            node_id="A",
                            lease_id=claim["event"]["payload"]["lease_id"],
                            owner_run_id="RUN-OWNER-A",
                            validator_run_id="RUN-VALIDATOR-A",
                            context_bundle=context,
                            context_validation_receipt=validation,
                            capability_receipt=capability,
                            now="2026-08-22T10:00:02Z",
                            expected_revision=claim["revision"],
                        )
                    self.assertEqual("E_V265_MEMBER_SCOPE", caught.exception.code)
                    self.assertFalse(any(call[0] == "prepare" for call in host.calls))
                finally:
                    store.close()

    def test_external_write_intent_readback_confirm_and_reconcile(self) -> None:
        graph = _compile_graph(external_a=True)
        for state in ("confirmed", "indeterminate"):
            with self.subTest(readback_state=state):
                store = self._store(f"external-{state}")
                host = _LifecycleHost(graph, store=store, readback_state=state)
                run_id = f"RUN-EXTERNAL-{state.upper()}"
                try:
                    controller = self._controller(
                        graph,
                        store,
                        host,
                        max_workers=1,
                        authorized_root=self.workspace,
                    )
                    controller.create_run(run_id=run_id, created_at="2026-08-22T10:00:00Z")
                    inputs = base._dispatch_inputs(graph, self.workspace)
                    inputs["A"]["capability_receipt"] = _external_capability(
                        graph, "A", self.workspace
                    )
                    controller.run_ready_wave(
                        run_id=run_id,
                        dispatch_inputs=inputs,
                        now="2026-08-22T10:00:02Z",
                        expected_revision=store.read_run_head(run_id)["revision"],
                    )
                    event_types = [event["event_type"] for event in store.load_events(run_id)]
                    self.assertLess(event_types.index("node.started"), event_types.index("side_effect.intent"))
                    self.assertLess(event_types.index("side_effect.intent"), event_types.index("host.execution_started"))
                    self.assertIn("host.observation_recorded", event_types)
                    self.assertTrue(host.execute_event_types)
                    self.assertIn("side_effect.intent", host.execute_event_types[0])
                    record = store.get_idempotency_record(run_id, inputs["A"]["idempotency_key"])
                    expected_state = "confirmed" if state == "confirmed" else "reconciliation_required"
                    self.assertEqual(expected_state, record["state"])
                    self.assertEqual(1, host.execute_count.get("A"))
                    controller.recover(run_id=run_id, now="2026-08-22T10:05:00Z")
                    self.assertEqual(1, host.execute_count.get("A"))
                finally:
                    store.close()

    def test_controller_enforces_max_workers_independent_of_adapter_pool(self) -> None:
        graph = _compile_graph()
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def callback(dispatch: Mapping[str, Any]) -> dict[str, Any]:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                time.sleep(0.08)
                return {
                    "outcome": "completed",
                    "artifact_receipts": [base._artifact(graph, str(dispatch["run_id"]), str(dispatch["node_id"]), int(dispatch["attempt"]))],
                    "evidence_refs": ["evidence:bounded-wave"],
                    "side_effects": [],
                }
            finally:
                with lock:
                    active -= 1

        adapter = CallbackHostAdapter(
            {"action:A": callback, "action:B": callback},
            adapter_id="callback_fixture",
            max_workers=4,
            clock=lambda: "2026-08-22T10:00:04Z",
        )
        store = self._store("controller-bound")
        try:
            controller = self._controller(graph, store, adapter, max_workers=1)
            controller.create_run(run_id="RUN-BOUND", created_at="2026-08-22T10:00:00Z")
            wave = controller.run_ready_wave(
                run_id="RUN-BOUND",
                dispatch_inputs=base._dispatch_inputs(graph, self.workspace),
                now="2026-08-22T10:00:02Z",
                expected_revision=store.read_run_head("RUN-BOUND")["revision"],
            )
            self.assertEqual(1, wave["max_workers"])
            self.assertEqual(1, maximum_active)
        finally:
            adapter.close()
            store.close()

    def test_timeout_cancel_probe_has_one_fail_closed_projection(self) -> None:
        graph = _compile_graph()
        store = self._store("timeout")
        host = _LifecycleHost(
            graph,
            store=store,
            timeout=True,
            cancel_state="running",
            probe_state="running",
        )
        try:
            controller = self._controller(graph, store, host, max_workers=1)
            controller.create_run(run_id="RUN-TIMEOUT", created_at="2026-08-22T10:00:00Z")
            try:
                wave = controller.run_ready_wave(
                    run_id="RUN-TIMEOUT",
                    dispatch_inputs=base._dispatch_inputs(graph, self.workspace),
                    now="2026-08-22T10:00:02Z",
                    expected_revision=store.read_run_head("RUN-TIMEOUT")["revision"],
                )
            except HostAdapterError as exc:
                self.fail(f"E_TEST_H265_TIMEOUT_NOT_CONSUMED:{exc.code}")
            self.assertEqual(["A"], wave["blocked_node_ids"])
            projection = reduce_graph_events(
                graph, store.load_events("RUN-TIMEOUT"), expected_bindings=base._bindings(graph)
            )
            self.assertEqual("blocked", projection["nodes"]["A"]["outcome"])
            event_types = [event["event_type"] for event in store.load_events("RUN-TIMEOUT")]
            self.assertIn("host.observation_recorded", event_types)
            self.assertNotIn("node.cancelled", event_types)
        finally:
            store.close()

    def test_live_and_imported_handles_require_quiescence_before_pause_or_cancel(self) -> None:
        graph = _compile_graph()
        for operation in ("cancel", "interrupt"):
            with self.subTest(live_operation=operation):
                store = self._store(f"live-{operation}")
                host = _LifecycleHost(graph, cancel_state="running", probe_state="running")
                run_id = f"RUN-LIVE-{operation.upper()}"
                try:
                    controller = self._controller(graph, store, host)
                    controller.create_run(run_id=run_id, created_at="2026-08-22T10:00:00Z")
                    revision = self._append_root_ready(graph, store, run_id)
                    claim = controller.claim_node(run_id=run_id, node_id="A", worker_id="WORKER-A", lease_seconds=30, now="2026-08-22T10:00:01Z", expected_revision=revision)
                    context, validation = base._context_bundle(graph, "A")
                    capability = base._capability(graph, "A", self.workspace)
                    controller.start_node(
                        run_id=run_id,
                        node_id="A",
                        lease_id=claim["event"]["payload"]["lease_id"],
                        owner_run_id="RUN-OWNER-A",
                        validator_run_id="RUN-VALIDATOR-A",
                        context_bundle=context,
                        context_validation_receipt=validation,
                        capability_receipt=capability,
                        now="2026-08-22T10:00:02Z",
                        expected_revision=claim["revision"],
                    )
                    head = store.read_run_head(run_id)
                    if operation == "cancel":
                        controller.cancel(run_id=run_id, node_id="A", reason="user", evidence_refs=["evidence:cancel"], now="2026-08-22T10:00:03Z", expected_revision=head["revision"])
                    else:
                        controller.interrupt(run_id=run_id, node_id="A", gate_id="gate:human:A", interrupt_id="INTERRUPT-A", reason="approval", evidence_refs=["evidence:interrupt"], now="2026-08-22T10:00:03Z", expected_revision=head["revision"])
                    projection = reduce_graph_events(graph, store.load_events(run_id), expected_bindings=base._bindings(graph))
                    self.assertEqual("blocked", projection["nodes"]["A"]["outcome"])
                    self.assertNotIn(projection["nodes"]["A"]["execution_state"], {"cancelled", "waiting_user"})
                finally:
                    store.close()

        store = self._store("imported-handle")
        host = _LifecycleHost(graph, probe_state="indeterminate")
        try:
            store.create_run("RUN-IMPORTED", graph, base._bindings(graph), created_at="2026-08-22T10:00:00Z")
            self.compiled_graph = graph
            self.bindings = base._bindings(graph)
            base.TestV265GraphRuntime._activate_node(self, store, "RUN-IMPORTED")
            controller = self._controller(graph, store, host)
            head = store.read_run_head("RUN-IMPORTED")
            controller.interrupt(run_id="RUN-IMPORTED", node_id="A", gate_id="gate:human:A", interrupt_id="INTERRUPT-IMPORTED", reason="approval", evidence_refs=["evidence:interrupt"], now="2026-08-22T10:00:03Z", expected_revision=head["revision"])
            projection = reduce_graph_events(graph, store.load_events("RUN-IMPORTED"), expected_bindings=base._bindings(graph))
            self.assertEqual("blocked", projection["nodes"]["A"]["outcome"])
        finally:
            store.close()

    def test_approval_requires_full_external_assurance(self) -> None:
        graph = _compile_graph()
        variants = {
            "issuer_assurance": "repository_fixture",
            "actor_relationship": "self",
            "proof_strength": "fixture_only",
            "permission_effect": "none",
            "attestation_ref": None,
        }
        for field, value in variants.items():
            with self.subTest(approval_field=field):
                store = self._store(f"approval-{field}")
                run_id = f"RUN-APPROVAL-{field.upper()}"
                try:
                    store.create_run(run_id, graph, base._bindings(graph), created_at="2026-08-22T10:00:00Z")
                    self.compiled_graph = graph
                    self.bindings = base._bindings(graph)
                    base.TestV265GraphRuntime._activate_node(self, store, run_id)
                    controller = self._controller(graph, store, base._ExternalApprovalHost())
                    interrupted = controller.interrupt(run_id=run_id, node_id="A", gate_id="gate:human:A", interrupt_id=f"INTERRUPT-{field}", reason="approval", evidence_refs=["evidence:interrupt"], now="2026-08-22T10:01:00Z", expected_revision=store.read_run_head(run_id)["revision"])
                    approval = base._approval_receipt(graph, "A", interrupt_id=f"INTERRUPT-{field}")
                    approval[field] = value
                    approval = _rehash(approval, "receipt_sha256")
                    with self.assertRaises(GraphRuntimeError) as caught:
                        controller.resume(run_id=run_id, node_id="A", interrupt_id=f"INTERRUPT-{field}", approval_receipt=approval, now="2026-08-22T10:01:02Z", expected_revision=interrupted["revision"])
                    self.assertEqual("E_V265_RUNTIME_GATE", caught.exception.code)
                finally:
                    store.close()

    def test_schedule_retry_uses_compiled_policy_and_budget(self) -> None:
        graph = _compile_graph(optional_a_output=True, retry_a=True)

        def failed(dispatch: Mapping[str, Any]) -> dict[str, Any]:
            return {"outcome": "failed", "artifact_receipts": [], "evidence_refs": ["evidence:failed"], "side_effects": []}

        def completed(dispatch: Mapping[str, Any]) -> dict[str, Any]:
            return {"outcome": "completed", "artifact_receipts": [base._artifact(graph, str(dispatch["run_id"]), str(dispatch["node_id"]), int(dispatch["attempt"]))], "evidence_refs": ["evidence:completed"], "side_effects": []}

        adapter = CallbackHostAdapter({"action:A": failed, "action:B": completed}, adapter_id="callback_fixture", max_workers=2, clock=lambda: "2026-08-22T10:00:04Z")
        store = self._store("retry")
        try:
            controller = self._controller(graph, store, adapter, max_workers=1)
            controller.create_run(run_id="RUN-RETRY", created_at="2026-08-22T10:00:00Z")
            controller.run_ready_wave(run_id="RUN-RETRY", dispatch_inputs=base._dispatch_inputs(graph, self.workspace), now="2026-08-22T10:00:02Z", expected_revision=store.read_run_head("RUN-RETRY")["revision"])
            schedule_retry = _required_method(controller, "schedule_retry")
            receipt = schedule_retry(run_id="RUN-RETRY", node_id="A", source_edge_id="retry_policy:A", now="2026-08-22T10:00:05Z", expected_revision=store.read_run_head("RUN-RETRY")["revision"])
            self.assertEqual("node.retry_scheduled", receipt["event"]["event_type"])
            projection = reduce_graph_events(graph, store.load_events("RUN-RETRY"), expected_bindings=base._bindings(graph))
            self.assertEqual("ready", projection["nodes"]["A"]["execution_state"])
            self.assertEqual(1, projection["traversal_counts"]["retry_policy:A"])
        finally:
            adapter.close()
            store.close()

    def test_recover_verifies_store_before_mutation(self) -> None:
        graph = _compile_graph()
        database_path = self.runtime_root / "recover-verify.sqlite3"
        store = self._store("recover-verify")
        run_id = "RUN-RECOVER-VERIFY"
        try:
            store.create_run(run_id, graph, base._bindings(graph), created_at="2026-08-22T10:00:00Z")
            connection = sqlite3.connect(database_path)
            try:
                connection.execute("UPDATE runs SET last_event_sha256=? WHERE run_id=?", ("f" * 64, run_id))
                connection.commit()
            finally:
                connection.close()
            controller = self._controller(graph, store, _LifecycleHost(graph))
            revision_before = store.read_run_head(run_id)["revision"]
            with self.assertRaises(RuntimeStoreError) as caught:
                controller.recover(run_id=run_id, now="2026-08-22T10:05:00Z")
            self.assertEqual("E_V265_STORE_CORRUPT", caught.exception.code)
            self.assertEqual(revision_before, store.read_run_head(run_id)["revision"])
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
