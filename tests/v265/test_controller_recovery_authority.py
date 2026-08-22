from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from scripts.v265.canonical import canonical_sha256
from scripts.v265.graph_runtime import GraphRuntimeError, reduce_graph_events
from scripts.v265.host_adapter import HostAdapterError
from scripts.v265.runtime_controller import RuntimeController
from scripts.v265.runtime_store import SQLiteRuntimeStore
from tests.v265 import test_graph_runtime as base
from tests.v265 import test_runtime_execution_authority as authority


CONTROLLER_RECOVERY_CONTRACT_SHA256 = (
    "4417d73248e6f1a7ce2c5a44dbb8f18819a962bb1b2b1f741c44904a597e679d"
)
CONTROLLER_RECOVERY_PLAN_REVISION = 1
CONTROLLER_RECOVERY_TASK_EXACT_SET_SHA256 = (
    "9f322858c37a198fcf891cdc5a4b80dc9a54ce5a74ff0935347a142979981cf2"
)


MUTATION_FIELDS = {
    "schema_version",
    "operation",
    "run_id",
    "node_id",
    "event",
    "store_receipt",
    "revision",
    "projection_sha256",
    "host_quiescence_assurance",
    "receipt_sha256",
}
PROBE_FIELDS = {
    "schema_version",
    "adapter_id",
    "host_handle_id",
    "run_id",
    "node_id",
    "attempt",
    "observed_state",
    "quiescent",
    "observed_at",
    "evidence_refs",
    "receipt_sha256",
}


class _NoProbeExecutionAdapter:
    """Execution-capable proxy that deliberately exposes no probe_handle."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        if name == "probe_handle":
            raise AttributeError(name)
        return getattr(self._delegate, name)


class TestP265ControllerRecoveryAuthority(unittest.TestCase):
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
    ) -> RuntimeController:
        return RuntimeController(
            compiled_graph=graph,
            store=store,
            host_adapter=host,
            run_bindings=base._bindings(graph),
            max_workers=1,
            authorized_workspace_root=self.runtime_root,
        )

    @staticmethod
    def _captured_result(
        call: Any,
    ) -> tuple[Any | None, str | None, Exception | None]:
        try:
            return call(), None, None
        except Exception as exc:  # product boundary becomes an explicit assertion
            return None, getattr(exc, "code", None), exc

    def _append_root_ready(
        self,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        run_id: str,
    ) -> int:
        runtime = __import__("scripts.v265.graph_runtime", fromlist=["make_graph_event"])
        head = store.read_run_head(run_id)
        event = base._make_event(
            runtime,
            compiled_graph=graph,
            run_id=run_id,
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
        store.append_event(run_id, event, expected_revision=head["revision"])
        return head["revision"] + 1

    def _start_with_receipts(
        self,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        host: object,
        run_id: str,
    ) -> tuple[RuntimeController, dict[str, dict[str, Any]]]:
        controller = self._controller(graph, store, host)
        created = controller.create_run(
            run_id=run_id, created_at="2026-08-22T10:00:00Z"
        )
        revision = self._append_root_ready(graph, store, run_id)
        claimed = controller.claim_node(
            run_id=run_id,
            node_id="A",
            worker_id="WORKER-A",
            lease_seconds=30,
            now="2026-08-22T10:00:01Z",
            expected_revision=revision,
        )
        context, validation = base._context_bundle(graph, "A")
        started = controller.start_node(
            run_id=run_id,
            node_id="A",
            lease_id=claimed["event"]["payload"]["lease_id"],
            owner_run_id="RUN-OWNER-A",
            validator_run_id="RUN-VALIDATOR-A",
            context_bundle=context,
            context_validation_receipt=validation,
            capability_receipt=base._capability(graph, "A", self.workspace),
            now="2026-08-22T10:00:02Z",
            expected_revision=claimed["revision"],
        )
        return controller, {
            "create": created,
            "claim": claimed,
            "start": started,
        }

    def _activate_legacy_node(
        self, graph: dict[str, object], store: SQLiteRuntimeStore, run_id: str
    ) -> None:
        store.create_run(
            run_id,
            graph,
            base._bindings(graph),
            created_at="2026-08-22T10:00:00Z",
        )
        self.compiled_graph = graph
        self.bindings = base._bindings(graph)
        base.TestV265GraphRuntime._activate_node(self, store, run_id)

    @staticmethod
    def _mutation_facts(receipt: Mapping[str, Any]) -> tuple[set[str], Any, bool]:
        return (
            set(receipt),
            receipt.get("host_quiescence_assurance"),
            receipt.get("receipt_sha256")
            == canonical_sha256(
                {
                    key: value
                    for key, value in receipt.items()
                    if key != "receipt_sha256"
                }
            ),
        )

    @staticmethod
    def _recovery_facts(
        *,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        run_id: str,
        expected_handle_id: str,
        expected_attempt: int,
        expected_observed_state: str,
        result: Mapping[str, Any] | None,
        error: Exception | None,
        host: authority._LifecycleHost,
        probes_before: int,
    ) -> tuple[Any, ...]:
        events = store.load_events(run_id)
        projection = reduce_graph_events(
            graph,
            events,
            expected_bindings=base._bindings(graph),
        )
        probes = [
            event
            for event in events
            if event["event_type"] == "host.observation_recorded"
            and event["node_id"] == "A"
            and event["payload"].get("observation_type") == "probe"
        ]
        probe_event = probes[0] if len(probes) == 1 else {}
        probe = probe_event.get("payload", {}).get("observation_receipt", {})
        blocks = [
            event
            for event in events
            if event["event_type"] == "node.blocked" and event["node_id"] == "A"
        ]
        block = blocks[0] if len(blocks) == 1 else {}
        probe_index = events.index(probe_event) if probe_event else -1
        block_index = events.index(block) if block else -1
        digest = probe.get("receipt_sha256")
        state = projection["nodes"]["A"]
        probe_calls = sum(
            1
            for name, _node in host.calls
            if name in {"probe", "probe_error"}
        )
        return (
            error,
            len(probes),
            set(probe) if isinstance(probe, Mapping) else set(),
            probe.get("schema_version"),
            probe.get("adapter_id"),
            probe.get("host_handle_id"),
            probe.get("run_id"),
            probe.get("node_id"),
            probe.get("attempt"),
            probe.get("observed_state"),
            probe.get("quiescent"),
            (
                probe.get("receipt_sha256")
                == canonical_sha256(
                    {
                        key: value
                        for key, value in probe.items()
                        if key != "receipt_sha256"
                    }
                )
                if isinstance(probe, Mapping) and probe
                else False
            ),
            len(blocks),
            block.get("payload", {}).get("blocker_id"),
            (
                probe_index >= 0
                and block_index > probe_index
                and isinstance(digest, str)
                and digest in " ".join(block.get("evidence_refs", []))
            ),
            state["execution_state"],
            state["outcome"],
            state["validation_state"],
            state["execution_state"] == "ready",
            (
                "A" in result.get("ready_node_ids", [])
                if isinstance(result, Mapping)
                else False
            ),
            probe_calls - probes_before,
            host.execute_count.get("A"),
        )

    def test_execution_adapter_requires_probe_but_approval_only_is_compatible(self) -> None:
        graph = authority._compile_graph()
        with self.subTest(adapter_kind="execution_missing_probe"):
            store = self._store("missing-probe-construction")
            delegate = authority._LifecycleHost(graph)
            try:
                _controller, code, _error = self._captured_result(
                    lambda: self._controller(
                        graph, store, _NoProbeExecutionAdapter(delegate)
                    )
                )
                self.assertEqual(
                    "E_V265_HOST_LIFECYCLE",
                    code,
                    "E_TEST_P265_EXECUTION_ADAPTER_WITHOUT_PROBE_ACCEPTED",
                )
            finally:
                store.close()

        with self.subTest(adapter_kind="approval_only_legacy"):
            store = self._store("approval-only-construction")
            try:
                controller, code, error = self._captured_result(
                    lambda: self._controller(
                        graph, store, base._ExternalApprovalHost()
                    )
                )
                self.assertEqual(
                    (None, True),
                    (error, isinstance(controller, RuntimeController)),
                    f"E_TEST_P265_APPROVAL_ONLY_REJECTED:{code}",
                )
            finally:
                store.close()

    def test_active_running_handle_dynamic_probe_failure_never_becomes_ready(self) -> None:
        graph = authority._compile_graph()
        variants = ("missing", "error")
        for variant in variants:
            with self.subTest(dynamic_probe=variant):
                store = self._store(f"active-probe-{variant}")
                host = authority._LifecycleHost(
                    graph, store=store, probe_state="running"
                )
                run_id = f"RUN-ACTIVE-PROBE-{variant.upper()}"
                try:
                    _started, _receipts = self._start_with_receipts(
                        graph, store, host, run_id
                    )
                    recovered = self._controller(graph, store, host)
                    before = reduce_graph_events(
                        graph,
                        store.load_events(run_id),
                        expected_bindings=base._bindings(graph),
                    )
                    state_before = before["nodes"]["A"]
                    handle_id = str(state_before["host_handle_id"])
                    attempt = int(state_before["attempt"])
                    probes_before = sum(
                        1
                        for name, _node in host.calls
                        if name in {"probe", "probe_error"}
                    )
                    if variant == "missing":
                        host.probe_handle = None  # type: ignore[method-assign]
                    else:
                        def failing_probe(**kwargs: Any) -> dict[str, Any]:
                            host.calls.append(("probe_error", str(kwargs["node_id"])))
                            raise HostAdapterError(
                                "E_V265_HOST_OBSERVATION", "local fake probe failed"
                            )

                        host.probe_handle = failing_probe  # type: ignore[method-assign]
                    result, code, error = self._captured_result(
                        lambda: recovered.recover(
                            run_id=run_id, now="2026-08-22T10:05:00Z"
                        )
                    )
                    expected = (
                        None,
                        1,
                        PROBE_FIELDS,
                        "goal-teams-host-probe-receipt-v2.65",
                        host.adapter_id,
                        handle_id,
                        run_id,
                        "A",
                        attempt,
                        "indeterminate",
                        False,
                        True,
                        1,
                        f"host_quiescence_unconfirmed:{handle_id}",
                        True,
                        "terminal",
                        "blocked",
                        "not_run",
                        False,
                        False,
                        0 if variant == "missing" else 1,
                        1,
                    )
                    self.assertEqual(
                        expected,
                        self._recovery_facts(
                            graph=graph,
                            store=store,
                            run_id=run_id,
                            expected_handle_id=handle_id,
                            expected_attempt=attempt,
                            expected_observed_state="indeterminate",
                            result=result if isinstance(result, Mapping) else None,
                            error=error,
                            host=host,
                            probes_before=probes_before,
                        ),
                        f"E_TEST_P265_DYNAMIC_PROBE_NOT_FAIL_CLOSED:{code}",
                    )
                finally:
                    store.close()

    def test_durable_running_handle_is_probed_even_when_node_label_is_ready(self) -> None:
        graph = authority._compile_graph()
        store = self._store("ready-label")
        host = authority._LifecycleHost(graph, store=store, probe_state="running")
        run_id = "RUN-DURABLE-HOST-NODE-READY"
        try:
            _started, _receipts = self._start_with_receipts(
                graph, store, host, run_id
            )
            before_expiry = reduce_graph_events(
                graph,
                store.load_events(run_id),
                expected_bindings=base._bindings(graph),
            )
            state = before_expiry["nodes"]["A"]
            handle_id = str(state["host_handle_id"])
            attempt = int(state["attempt"])
            runtime = __import__("scripts.v265.graph_runtime", fromlist=["make_graph_event"])
            head = store.read_run_head(run_id)
            expired = base._make_event(
                runtime,
                compiled_graph=graph,
                run_id=run_id,
                event_seq=head["revision"] + 1,
                event_type="node.lease_expired",
                node_id="A",
                attempt=attempt,
                previous_event_sha256=head["last_event_sha256"],
                payload={
                    "lease_id": state["lease_id"],
                    "lease_expires_at": state["lease_expires_at"],
                    "recovery_decision": "ready",
                },
                actor_identity="runtime_controller",
            )
            store.release_lease(run_id, expired, expected_revision=head["revision"])
            label_projection = reduce_graph_events(
                graph,
                store.load_events(run_id),
                expected_bindings=base._bindings(graph),
            )
            self.assertEqual("ready", label_projection["nodes"]["A"]["execution_state"])
            self.assertEqual("running", label_projection["host_handles"][handle_id]["state"])

            recovered = self._controller(graph, store, host)
            probes_before = sum(1 for name, _node in host.calls if name == "probe")
            result, code, error = self._captured_result(
                lambda: recovered.recover(
                    run_id=run_id, now="2026-08-22T10:05:00Z"
                )
            )
            self.assertEqual(
                (
                    None,
                    1,
                    PROBE_FIELDS,
                    "goal-teams-host-probe-receipt-v2.65",
                    host.adapter_id,
                    handle_id,
                    run_id,
                    "A",
                    attempt,
                    "running",
                    False,
                    True,
                    1,
                    f"host_quiescence_unconfirmed:{handle_id}",
                    True,
                    "terminal",
                    "blocked",
                    "not_run",
                    False,
                    False,
                    1,
                    1,
                ),
                self._recovery_facts(
                    graph=graph,
                    store=store,
                    run_id=run_id,
                    expected_handle_id=handle_id,
                    expected_attempt=attempt,
                    expected_observed_state="running",
                    result=result if isinstance(result, Mapping) else None,
                    error=error,
                    host=host,
                    probes_before=probes_before,
                ),
                f"E_TEST_P265_READY_LABEL_SKIPPED_DURABLE_HANDLE:{code}",
            )
        finally:
            store.close()

    def test_mutation_receipts_have_exact_quiescence_assurance_and_self_digest(self) -> None:
        ordinary: list[tuple[str, Mapping[str, Any]]] = []

        graph = authority._compile_graph()
        store = self._store("ordinary-complete")
        host = authority._LifecycleHost(graph, store=store)
        try:
            controller, receipts = self._start_with_receipts(
                graph, store, host, "RUN-MUTATION-ORDINARY"
            )
            ordinary.extend(receipts.items())
            state = reduce_graph_events(
                graph,
                store.load_events("RUN-MUTATION-ORDINARY"),
                expected_bindings=base._bindings(graph),
            )["nodes"]["A"]
            heartbeat = controller.heartbeat(
                run_id="RUN-MUTATION-ORDINARY",
                node_id="A",
                lease_id=state["lease_id"],
                new_expires_at="2026-08-22T10:02:00Z",
                now="2026-08-22T10:00:03Z",
                expected_revision=store.read_run_head("RUN-MUTATION-ORDINARY")[
                    "revision"
                ],
            )
            ordinary.append(("heartbeat", heartbeat))
            artifact = base._artifact(graph, "RUN-MUTATION-ORDINARY", "A", 1)
            state = reduce_graph_events(
                graph,
                store.load_events("RUN-MUTATION-ORDINARY"),
                expected_bindings=base._bindings(graph),
            )["nodes"]["A"]
            completed = controller.complete_node(
                run_id="RUN-MUTATION-ORDINARY",
                node_id="A",
                lease_id=state["lease_id"],
                artifact_receipts=[artifact],
                evidence_refs=["evidence:local-outcome"],
                now="2026-08-22T10:00:04Z",
                expected_revision=store.read_run_head("RUN-MUTATION-ORDINARY")[
                    "revision"
                ],
            )
            ordinary.append(("outcome", completed))
            validation = base._validation_receipt(
                graph, "RUN-MUTATION-ORDINARY", "A", [artifact]
            )
            validated = controller.validate_node(
                run_id="RUN-MUTATION-ORDINARY",
                node_id="A",
                validator_run_id="RUN-VALIDATOR-A",
                validation_receipt=validation,
                now="2026-08-22T10:00:11Z",
                expected_revision=store.read_run_head("RUN-MUTATION-ORDINARY")[
                    "revision"
                ],
            )
            ordinary.append(("validate", validated))
        finally:
            store.close()

        retry_graph = authority._compile_graph(optional_a_output=True, retry_a=True)
        retry_store = self._store("ordinary-retry")
        retry_host = authority._LifecycleHost(retry_graph, store=retry_store)
        try:
            retry_controller, _receipts = self._start_with_receipts(
                retry_graph, retry_store, retry_host, "RUN-MUTATION-RETRY"
            )
            retry_state = reduce_graph_events(
                retry_graph,
                retry_store.load_events("RUN-MUTATION-RETRY"),
                expected_bindings=base._bindings(retry_graph),
            )["nodes"]["A"]
            failed = retry_controller.fail_node(
                run_id="RUN-MUTATION-RETRY",
                node_id="A",
                lease_id=retry_state["lease_id"],
                outcome="failed",
                failure_artifacts=[],
                evidence_refs=["evidence:local-failure"],
                now="2026-08-22T10:00:03Z",
                expected_revision=retry_store.read_run_head("RUN-MUTATION-RETRY")[
                    "revision"
                ],
            )
            ordinary.append(("failed_outcome", failed))
            retry = retry_controller.schedule_retry(
                run_id="RUN-MUTATION-RETRY",
                node_id="A",
                source_edge_id="retry_policy:A",
                now="2026-08-22T10:00:05Z",
                expected_revision=retry_store.read_run_head("RUN-MUTATION-RETRY")[
                    "revision"
                ],
            )
            ordinary.append(("retry", retry))
        finally:
            retry_store.close()

        block_store = self._store("ordinary-block")
        try:
            block_controller = self._controller(
                graph, block_store, authority._LifecycleHost(graph)
            )
            block_controller.create_run(
                run_id="RUN-MUTATION-BLOCK",
                created_at="2026-08-22T10:00:00Z",
            )
            blocked = block_controller.block_node(
                run_id="RUN-MUTATION-BLOCK",
                node_id="A",
                blocker_id="local-test-blocker",
                evidence_refs=["evidence:local-block"],
                now="2026-08-22T10:00:01Z",
                expected_revision=block_store.read_run_head("RUN-MUTATION-BLOCK")[
                    "revision"
                ],
            )
            ordinary.append(("block", blocked))
        finally:
            block_store.close()

        resume_store = self._store("ordinary-resume")
        try:
            self._activate_legacy_node(graph, resume_store, "RUN-MUTATION-RESUME")
            resume_controller = self._controller(
                graph, resume_store, base._ExternalApprovalHost()
            )
            interrupted = resume_controller.interrupt(
                run_id="RUN-MUTATION-RESUME",
                node_id="A",
                gate_id="gate:human:A",
                interrupt_id="INTERRUPT-RESUME-A",
                reason="approval",
                evidence_refs=["evidence:resume-interrupt"],
                now="2026-08-22T10:01:00Z",
                expected_revision=resume_store.read_run_head("RUN-MUTATION-RESUME")[
                    "revision"
                ],
            )
            approval = base._approval_receipt(
                graph, "A", interrupt_id="INTERRUPT-RESUME-A"
            )
            resumed = resume_controller.resume(
                run_id="RUN-MUTATION-RESUME",
                node_id="A",
                interrupt_id="INTERRUPT-RESUME-A",
                approval_receipt=approval,
                now="2026-08-22T10:01:02Z",
                expected_revision=interrupted["revision"],
            )
            ordinary.append(("resume", resumed))
        finally:
            resume_store.close()

        for name, receipt in ordinary:
            with self.subTest(mutation=name):
                self.assertEqual(
                    (MUTATION_FIELDS, "not_applicable", True),
                    self._mutation_facts(receipt),
                    "E_TEST_P265_ORDINARY_MUTATION_ASSURANCE",
                )

        controls: list[tuple[str, Mapping[str, Any], str]] = []
        for name, cancel_state, probe_state, operation, assurance_value in (
            ("confirmed_cancel", "running", "cancelled", "cancel", "confirmed"),
            ("unconfirmed_interrupt", "running", "running", "interrupt", "unconfirmed"),
        ):
            control_store = self._store(name)
            control_host = authority._LifecycleHost(
                graph,
                store=control_store,
                cancel_state=cancel_state,
                probe_state=probe_state,
            )
            try:
                control, _receipts = self._start_with_receipts(
                    graph, control_store, control_host, f"RUN-{name.upper()}"
                )
                head = control_store.read_run_head(f"RUN-{name.upper()}")
                if operation == "cancel":
                    receipt = control.cancel(
                        run_id=f"RUN-{name.upper()}",
                        node_id="A",
                        reason="control",
                        evidence_refs=["evidence:control"],
                        now="2026-08-22T10:00:03Z",
                        expected_revision=head["revision"],
                    )
                else:
                    receipt = control.interrupt(
                        run_id=f"RUN-{name.upper()}",
                        node_id="A",
                        gate_id="gate:human:A",
                        interrupt_id="INTERRUPT-A",
                        reason="control",
                        evidence_refs=["evidence:control"],
                        now="2026-08-22T10:00:03Z",
                        expected_revision=head["revision"],
                    )
                controls.append((name, receipt, assurance_value))
            finally:
                control_store.close()

        legacy_store = self._store("legacy-control")
        try:
            self._activate_legacy_node(graph, legacy_store, "RUN-LEGACY-CONTROL")
            legacy = self._controller(graph, legacy_store, base._ExternalApprovalHost())
            receipt = legacy.interrupt(
                run_id="RUN-LEGACY-CONTROL",
                node_id="A",
                gate_id="gate:human:A",
                interrupt_id="INTERRUPT-LEGACY-A",
                reason="approval",
                evidence_refs=["evidence:legacy-control"],
                now="2026-08-22T10:01:00Z",
                expected_revision=legacy_store.read_run_head("RUN-LEGACY-CONTROL")[
                    "revision"
                ],
            )
            controls.append(("legacy_interrupt", receipt, "not_observed"))
        finally:
            legacy_store.close()

        for name, receipt, assurance_value in controls:
            with self.subTest(control_mutation=name):
                self.assertEqual(
                    (MUTATION_FIELDS, assurance_value, True),
                    self._mutation_facts(receipt),
                    "E_TEST_P265_CONTROL_MUTATION_ASSURANCE",
                )


if __name__ == "__main__":
    unittest.main()
