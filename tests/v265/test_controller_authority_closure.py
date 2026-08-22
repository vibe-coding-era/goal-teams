from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from scripts.v265.canonical import canonical_sha256
from scripts.v265.graph_runtime import GraphRuntimeError, reduce_graph_events
from scripts.v265.host_adapter import CallbackHostAdapter, HostAdapterError
from scripts.v265.runtime_controller import RuntimeController
from scripts.v265.runtime_store import SQLiteRuntimeStore
from tests.v265 import test_graph_runtime as base
from tests.v265 import test_runtime_execution_authority as authority


AUTHORITY_CLOSURE_CONTRACT_SHA256 = (
    "273b9ce0f1b6bec5ccf000379c1809c23620bcea59eb0e3ac2219374347a3697"
)
AUTHORITY_CLOSURE_PLAN_REVISION = 1
AUTHORITY_CLOSURE_TASK_EXACT_SET_SHA256 = (
    "800917c46eab127dfd0b5f0deb68f553b30cf25ed01c62ff54ae705e7ca7b2c1"
)
FROZEN_H265_AUTHORITY_TEST_SHA256 = (
    "543e1daf761d0f541396e49e0383a9db7221d83c0cf52ee002bc0a8ce91069b3"
)


class _FaultingLifecycleHost(authority._LifecycleHost):
    """Local fake Host with deterministic wait/readback failures."""

    def __init__(
        self,
        graph: dict[str, object],
        *,
        store: SQLiteRuntimeStore | None = None,
        wait_error: bool = False,
        readback_error: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(graph, store=store, **kwargs)
        self.wait_error = wait_error
        self.readback_error = readback_error

    def wait(
        self, handle: Mapping[str, Any], *, timeout_seconds: int
    ) -> dict[str, Any]:
        if self.wait_error:
            self.calls.append(("wait_error", str(handle["node_id"])))
            raise HostAdapterError(
                "E_V265_HOST_OBSERVATION", "local fake wait observation failed"
            )
        return super().wait(handle, timeout_seconds=timeout_seconds)

    def readback(
        self,
        handle: Mapping[str, Any],
        dispatch: Mapping[str, Any],
        outcome: Mapping[str, Any],
        *,
        observed_at: str,
    ) -> dict[str, Any]:
        if self.readback_error:
            self.calls.append(("readback_error", str(dispatch["node_id"])))
            raise HostAdapterError(
                "E_V265_HOST_OBSERVATION", "local fake readback failed"
            )
        return super().readback(
            handle, dispatch, outcome, observed_at=observed_at
        )


class TestA265ControllerAuthorityClosure(unittest.TestCase):
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
        authorized_root: Path | None = None,
        use_default_root: bool = False,
    ) -> RuntimeController:
        kwargs: dict[str, object] = {
            "compiled_graph": graph,
            "store": store,
            "host_adapter": host,
            "run_bindings": base._bindings(graph),
            "max_workers": 1,
        }
        if not use_default_root:
            kwargs["authorized_workspace_root"] = (
                self.runtime_root if authorized_root is None else authorized_root
            )
        return RuntimeController(**kwargs)

    def _compile_scope_graph(
        self,
        *,
        scope_allowlist: list[str],
        forbidden_scope: list[str] | None = None,
    ) -> dict[str, object]:
        source, _compiled_plan, _validation = base._authoritative_plan()
        task_a = next(item for item in source["tasks"] if item["task_id"] == "A")
        task_a["scope_allowlist"] = scope_allowlist
        task_a["forbidden_scope"] = list(forbidden_scope or [])
        from scripts.v250.task_plan_compiler import (
            compile_task_plan,
            validate_compiled_task_plan,
        )

        compiled_plan = compile_task_plan(source)
        validation = validate_compiled_task_plan(compiled_plan)
        document = base._graph_document(source, compiled_plan, validation)
        from scripts.v265.graph_contract import compile_graph_contract

        return compile_graph_contract(
            document,
            compiled_task_plan=compiled_plan,
            task_plan_validation_receipt=validation,
        )

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

    def _start_active(
        self,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        host: object,
        run_id: str,
        *,
        controller: RuntimeController | None = None,
        capability: dict[str, object] | None = None,
    ) -> RuntimeController:
        selected = controller or self._controller(graph, store, host)
        selected.create_run(run_id=run_id, created_at="2026-08-22T10:00:00Z")
        revision = self._append_root_ready(graph, store, run_id)
        claim = selected.claim_node(
            run_id=run_id,
            node_id="A",
            worker_id="WORKER-A",
            lease_seconds=30,
            now="2026-08-22T10:00:01Z",
            expected_revision=revision,
        )
        context, validation = base._context_bundle(graph, "A")
        selected.start_node(
            run_id=run_id,
            node_id="A",
            lease_id=claim["event"]["payload"]["lease_id"],
            owner_run_id="RUN-OWNER-A",
            validator_run_id="RUN-VALIDATOR-A",
            context_bundle=context,
            context_validation_receipt=validation,
            capability_receipt=(
                base._capability(graph, "A", self.workspace)
                if capability is None
                else capability
            ),
            now="2026-08-22T10:00:02Z",
            expected_revision=claim["revision"],
        )
        return selected

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
    def _captured_code(call: Any) -> tuple[str | None, Exception | None]:
        try:
            call()
        except Exception as exc:  # product boundary is converted to a test assertion
            return getattr(exc, "code", None), exc
        return None, None

    @staticmethod
    def _captured_result(
        call: Any,
    ) -> tuple[Any | None, str | None, Exception | None]:
        try:
            return call(), None, None
        except Exception as exc:  # product boundary is converted to a test assertion
            return None, getattr(exc, "code", None), exc

    def test_default_store_root_and_scope_grammar_fail_before_prepare(self) -> None:
        graph = authority._compile_graph()
        with self.subTest(scope_case="default_root"):
            store = self._store("default-root")
            try:
                controller = self._controller(
                    graph,
                    store,
                    authority._LifecycleHost(graph),
                    use_default_root=True,
                )
                self.assertEqual(
                    store.runtime_root,
                    controller.authorized_workspace_root,
                    "E_TEST_A265_DEFAULT_ROOT_BYPASS",
                )
            finally:
                store.close()

        escape_target = self.runtime_root / "outside-workspace"
        escape_target.mkdir()
        (self.workspace / "scope-link").symlink_to(
            escape_target, target_is_directory=True
        )
        variants = {
            "allow_parent": (["../escape/**"], []),
            "forbid_parent": (["scope/**"], ["../escape/**"]),
            "absolute": (["/etc/**"], []),
            "empty_component": (["scope//**"], []),
            "dot_component": (["scope/./**"], []),
            "symlink_prefix": (["scope-link/**"], []),
        }
        for name, (allowlist, forbidden) in variants.items():
            with self.subTest(scope_case=name):
                variant_graph = self._compile_scope_graph(
                    scope_allowlist=allowlist,
                    forbidden_scope=forbidden,
                )
                variant_store = self._store(f"scope-{name}")
                host = authority._LifecycleHost(variant_graph)
                try:
                    controller = self._controller(
                        variant_graph,
                        variant_store,
                        host,
                        use_default_root=True,
                    )
                    run_id = f"RUN-SCOPE-{name.upper()}"
                    controller.create_run(
                        run_id=run_id, created_at="2026-08-22T10:00:00Z"
                    )
                    revision = self._append_root_ready(
                        variant_graph, variant_store, run_id
                    )
                    claim = controller.claim_node(
                        run_id=run_id,
                        node_id="A",
                        worker_id="WORKER-A",
                        lease_seconds=30,
                        now="2026-08-22T10:00:01Z",
                        expected_revision=revision,
                    )
                    context, validation = base._context_bundle(variant_graph, "A")
                    capability = base._capability(
                        variant_graph, "A", self.workspace
                    )
                    code, _ = self._captured_code(
                        lambda: controller.start_node(
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
                    )
                    prepare_calls = sum(
                        1 for operation, _node in host.calls if operation == "prepare"
                    )
                    self.assertEqual(
                        ("E_V265_MEMBER_SCOPE", 0),
                        (code, prepare_calls),
                        "E_TEST_A265_SCOPE_NOT_REJECTED_BEFORE_PREPARE",
                    )
                finally:
                    variant_store.close()

        with self.subTest(scope_case="valid_glob"):
            valid_graph = self._compile_scope_graph(scope_allowlist=["scope/**"])
            valid_store = self._store("scope-valid")
            host = authority._LifecycleHost(valid_graph)
            try:
                controller = self._controller(
                    valid_graph, valid_store, host, use_default_root=True
                )
                code, _ = self._captured_code(
                    lambda: self._start_active(
                        valid_graph,
                        valid_store,
                        host,
                        "RUN-SCOPE-VALID",
                        controller=controller,
                    )
                )
                self.assertEqual(
                    (None, 1),
                    (
                        code,
                        sum(
                            1
                            for operation, _node in host.calls
                            if operation == "prepare"
                        ),
                    ),
                    "E_TEST_A265_VALID_GLOB_REJECTED",
                )
            finally:
                valid_store.close()

    def test_stale_cas_cancel_and_interrupt_make_zero_host_calls(self) -> None:
        graph = authority._compile_graph()
        for operation in ("cancel", "interrupt"):
            with self.subTest(operation=operation):
                store = self._store(f"stale-{operation}")
                host = authority._LifecycleHost(
                    graph, cancel_state="running", probe_state="running"
                )
                run_id = f"RUN-STALE-{operation.upper()}"
                try:
                    controller = self._start_active(graph, store, host, run_id)
                    head = store.read_run_head(run_id)
                    control_before = sum(
                        1
                        for name, _node in host.calls
                        if name in {"cancel", "probe"}
                    )
                    revision_before = head["revision"]
                    if operation == "cancel":
                        call = lambda: controller.cancel(
                            run_id=run_id,
                            node_id="A",
                            reason="stale-cas",
                            evidence_refs=["evidence:stale-cas"],
                            now="2026-08-22T10:00:03Z",
                            expected_revision=revision_before - 1,
                        )
                    else:
                        call = lambda: controller.interrupt(
                            run_id=run_id,
                            node_id="A",
                            gate_id="gate:human:A",
                            interrupt_id="INTERRUPT-STALE-A",
                            reason="stale-cas",
                            evidence_refs=["evidence:stale-cas"],
                            now="2026-08-22T10:00:03Z",
                            expected_revision=revision_before - 1,
                        )
                    code, _ = self._captured_code(call)
                    control_after = sum(
                        1
                        for name, _node in host.calls
                        if name in {"cancel", "probe"}
                    )
                    self.assertEqual(
                        ("E_V265_RUNTIME_CAS", 0, revision_before),
                        (
                            code,
                            control_after - control_before,
                            store.read_run_head(run_id)["revision"],
                        ),
                        "E_TEST_A265_STALE_CAS_TOUCHED_HOST",
                    )
                finally:
                    store.close()

    def test_external_confirmed_terminal_and_uncertain_results_reconcile(self) -> None:
        graph = authority._compile_graph(external_a=True)
        variants = (
            ("confirmed", False, False),
            ("absent", False, False),
            ("indeterminate", False, False),
            ("wait_exception", True, False),
            ("readback_exception", False, True),
        )
        for state, wait_error, readback_error in variants:
            with self.subTest(external_state=state):
                store = self._store(f"external-{state}")
                host = _FaultingLifecycleHost(
                    graph,
                    store=store,
                    readback_state=(
                        state if state in {"confirmed", "absent", "indeterminate"}
                        else "confirmed"
                    ),
                    wait_error=wait_error,
                    readback_error=readback_error,
                )
                run_id = f"RUN-EXTERNAL-{state.upper()}"
                try:
                    controller = self._controller(graph, store, host)
                    controller.create_run(
                        run_id=run_id, created_at="2026-08-22T10:00:00Z"
                    )
                    inputs = base._dispatch_inputs(graph, self.workspace)
                    inputs["A"]["capability_receipt"] = authority._external_capability(
                        graph, "A", self.workspace
                    )
                    code, error = self._captured_code(
                        lambda: controller.run_ready_wave(
                            run_id=run_id,
                            dispatch_inputs=inputs,
                            now="2026-08-22T10:00:02Z",
                            expected_revision=store.read_run_head(run_id)["revision"],
                        )
                    )
                    self.assertIsNone(
                        error,
                        f"E_TEST_A265_EXTERNAL_EXCEPTION_NOT_RECONCILED:{code}",
                    )
                    projection = reduce_graph_events(
                        graph,
                        store.load_events(run_id),
                        expected_bindings=base._bindings(graph),
                    )
                    state_a = projection["nodes"]["A"]
                    handle_id = state_a["host_handle_id"]
                    record = store.get_idempotency_record(
                        run_id, inputs["A"]["idempotency_key"]
                    )
                    if state == "confirmed":
                        self.assertEqual(
                            ("terminal", "completed", "terminal", "confirmed"),
                            (
                                state_a["execution_state"],
                                state_a["outcome"],
                                projection["host_handles"][handle_id]["state"],
                                record["state"],
                            ),
                            "E_TEST_A265_CONFIRMED_EXTERNAL_NOT_TERMINAL",
                        )
                    else:
                        self.assertEqual(
                            ("waiting_user", "unverified", "reconciliation_required"),
                            (
                                state_a["execution_state"],
                                state_a["outcome"],
                                record["state"],
                            ),
                            "E_TEST_A265_EXTERNAL_UNCERTAINTY_NOT_RECONCILED",
                        )
                    controller.recover(
                        run_id=run_id, now="2026-08-22T10:05:00Z"
                    )
                    self.assertEqual(
                        1,
                        host.execute_count.get("A"),
                        "E_TEST_A265_EXTERNAL_REPLAYED",
                    )
                finally:
                    store.close()

    def test_callback_prepare_rejects_resigned_lineage_tampering(self) -> None:
        graph = authority._compile_graph()
        original = authority._dispatch(graph, self.workspace)

        def decision_request_lineage(dispatch: dict[str, object]) -> None:
            decision = dispatch["capability_decision"]
            packet = dispatch["member_packet"]
            assert isinstance(decision, dict) and isinstance(packet, dict)
            decision["request_sha256"] = "f" * 64
            dispatch["capability_decision"] = authority._rehash(
                decision, "decision_sha256"
            )
            packet["capability_decision_sha256"] = dispatch[
                "capability_decision"
            ]["decision_sha256"]
            dispatch["member_packet"] = authority._rehash(packet, "packet_sha256")

        def packet_lineage(
            dispatch: dict[str, object], field: str, replacement: str
        ) -> None:
            packet = dispatch["member_packet"]
            assert isinstance(packet, dict)
            packet[field] = replacement
            dispatch["member_packet"] = authority._rehash(packet, "packet_sha256")

        def capability_policy(
            dispatch: dict[str, object], field: str, replacement: object
        ) -> None:
            capability = dispatch["capability_receipt"]
            decision = dispatch["capability_decision"]
            packet = dispatch["member_packet"]
            assert (
                isinstance(capability, dict)
                and isinstance(decision, dict)
                and isinstance(packet, dict)
            )
            capability[field] = replacement
            dispatch["capability_receipt"] = authority._rehash(
                capability, "receipt_sha256"
            )
            if field in {
                "issuer_key_id",
                "issuer_assurance",
                "actor_relationship",
                "freshness_state",
            }:
                decision[field] = replacement
            decision["capability_receipt_sha256"] = dispatch[
                "capability_receipt"
            ]["receipt_sha256"]
            dispatch["capability_decision"] = authority._rehash(
                decision, "decision_sha256"
            )
            packet.update(
                {
                    "capability_receipt_sha256": dispatch["capability_receipt"][
                        "receipt_sha256"
                    ],
                    "capability_decision_sha256": dispatch[
                        "capability_decision"
                    ]["decision_sha256"],
                }
            )
            dispatch["member_packet"] = authority._rehash(packet, "packet_sha256")

        policy_variants: dict[str, tuple[str, object]] = {
            "issuer_key_id": ("issuer_key_id", "callback_fixture:key:attacker"),
            "issuer_assurance": ("issuer_assurance", "host_correlated"),
            "actor_relationship": ("actor_relationship", "correlated"),
            "freshness_state": ("freshness_state", "stale"),
            "tool_allowlist": ("tool_allowlist", ["shell"]),
            "network_policy": ("network_policy", "declared"),
            "workspace_policy": ("workspace_policy", "read_only"),
        }
        lineage_variants = {
            "packet_context": lambda dispatch: packet_lineage(
                dispatch, "context_bundle_sha256", "a" * 64
            ),
            "packet_capability": lambda dispatch: packet_lineage(
                dispatch, "capability_receipt_sha256", "b" * 64
            ),
            "packet_request": lambda dispatch: packet_lineage(
                dispatch, "capability_request_sha256", "c" * 64
            ),
            "packet_scope": lambda dispatch: packet_lineage(
                dispatch, "scope_sha256", "d" * 64
            ),
            "decision_request": decision_request_lineage,
        }
        adapter = CallbackHostAdapter(
            {
                "action:A": lambda _dispatch: {
                    "outcome": "completed",
                    "artifact_receipts": [],
                    "evidence_refs": ["evidence:local-only"],
                    "side_effects": [],
                }
            },
            adapter_id="callback_fixture",
            max_workers=1,
            clock=lambda: "2026-08-22T10:00:04Z",
        )
        try:
            for name, (field, replacement) in policy_variants.items():
                with self.subTest(capability_policy=name):
                    dispatch = copy.deepcopy(original)
                    capability_policy(dispatch, field, replacement)
                    code, _ = self._captured_code(
                        lambda: adapter.prepare(
                            dispatch, prepared_at="2026-08-22T10:00:01Z"
                        )
                    )
                    self.assertEqual(
                        "E_V265_HOST_CAPABILITY",
                        code,
                        "E_TEST_A265_RESIGNED_CAPABILITY_POLICY_ACCEPTED",
                    )
            for name, tamper in lineage_variants.items():
                with self.subTest(packet_lineage=name):
                    dispatch = copy.deepcopy(original)
                    tamper(dispatch)
                    code, _ = self._captured_code(
                        lambda: adapter.prepare(
                            dispatch, prepared_at="2026-08-22T10:00:01Z"
                        )
                    )
                    self.assertEqual(
                        "E_V265_HOST_CAPABILITY",
                        code,
                        "E_TEST_A265_RESIGNED_PACKET_LINEAGE_ACCEPTED",
                    )
        finally:
            adapter.close()

    def test_imported_handle_is_observed_and_legacy_authority_is_interrupt_only(self) -> None:
        graph = authority._compile_graph()
        with self.subTest(imported_handle="durable"):
            store = self._store("imported-durable")
            host = authority._LifecycleHost(graph, probe_state="terminal")
            run_id = "RUN-IMPORTED-DURABLE"
            try:
                self._start_active(graph, store, host, run_id)
                imported = self._controller(graph, store, host)
                head = store.read_run_head(run_id)
                before = reduce_graph_events(
                    graph,
                    store.load_events(run_id),
                    expected_bindings=base._bindings(graph),
                )
                expected_handle_id = before["nodes"]["A"]["host_handle_id"]
                expected_attempt = before["nodes"]["A"]["attempt"]
                receipt, code, error = self._captured_result(
                    lambda: imported.interrupt(
                        run_id=run_id,
                        node_id="A",
                        gate_id="gate:human:A",
                        interrupt_id="INTERRUPT-IMPORTED-A",
                        reason="approval",
                        evidence_refs=["evidence:imported-probe"],
                        now="2026-08-22T10:00:03Z",
                        expected_revision=head["revision"],
                    )
                )
                events = store.load_events(run_id)
                event_types = [event["event_type"] for event in events]
                observations = [
                    event
                    for event in events
                    if event["event_type"] == "host.observation_recorded"
                ]
                observation = observations[0] if len(observations) == 1 else {}
                payload = observation.get("payload", {})
                probe = payload.get("observation_receipt", {})
                expected_probe_fields = {
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
                interrupt_event = next(
                    (
                        event
                        for event in events
                        if event["event_type"] == "node.interrupted"
                    ),
                    {},
                )
                probe_index = next(
                    (
                        index
                        for index, event_type in enumerate(event_types)
                        if event_type == "host.observation_recorded"
                    ),
                    -1,
                )
                interrupt_index = next(
                    (
                        index
                        for index, event_type in enumerate(event_types)
                        if event_type == "node.interrupted"
                    ),
                    -1,
                )
                probe_digest = probe.get("receipt_sha256")
                # Attempt identity is observed through the public Probe Receipt;
                # the test never inspects Controller private handle dictionaries.
                self.assertEqual(
                    (
                        None,
                        1,
                        "probe",
                        expected_probe_fields,
                        "goal-teams-host-probe-receipt-v2.65",
                        host.adapter_id,
                        expected_handle_id,
                        run_id,
                        "A",
                        expected_attempt,
                        "terminal",
                        True,
                        True,
                        "node.interrupted",
                        "confirmed",
                        True,
                        1,
                    ),
                    (
                        error,
                        len(observations),
                        payload.get("observation_type"),
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
                        interrupt_event.get("event_type"),
                        (
                            receipt.get("host_quiescence_assurance")
                            if isinstance(receipt, Mapping)
                            else None
                        ),
                        (
                            probe_index >= 0
                            and interrupt_index > probe_index
                            and isinstance(probe_digest, str)
                            and probe_digest
                            in " ".join(interrupt_event.get("evidence_refs", []))
                        ),
                        sum(1 for name, _node in host.calls if name == "probe"),
                    ),
                    f"E_TEST_A265_IMPORTED_PROBE_INCOMPLETE:{code}",
                )
            finally:
                store.close()

        with self.subTest(legacy_control="interrupt"):
            store = self._store("legacy-interrupt")
            run_id = "RUN-LEGACY-INTERRUPT"
            try:
                self._activate_legacy_node(graph, store, run_id)
                controller = self._controller(
                    graph, store, base._ExternalApprovalHost()
                )
                receipt = controller.interrupt(
                    run_id=run_id,
                    node_id="A",
                    gate_id="gate:human:A",
                    interrupt_id="INTERRUPT-LEGACY-A",
                    reason="approval",
                    evidence_refs=["evidence:legacy-interrupt"],
                    now="2026-08-22T10:01:00Z",
                    expected_revision=store.read_run_head(run_id)["revision"],
                )
                self.assertEqual(
                    ("node.interrupted", "not_observed", 0),
                    (
                        receipt["event"]["event_type"],
                        receipt.get("host_quiescence_assurance"),
                        sum(
                            1
                            for event in store.load_events(run_id)
                            if event["event_type"] == "host.observation_recorded"
                        ),
                    ),
                    "E_TEST_A265_LEGACY_INTERRUPT_ASSURANCE",
                )
            finally:
                store.close()

        with self.subTest(legacy_control="cancel_forbidden"):
            store = self._store("legacy-cancel")
            run_id = "RUN-LEGACY-CANCEL"
            try:
                self._activate_legacy_node(graph, store, run_id)
                controller = self._controller(
                    graph, store, base._ExternalApprovalHost()
                )
                before = reduce_graph_events(
                    graph,
                    store.load_events(run_id),
                    expected_bindings=base._bindings(graph),
                )
                handle_id = before["nodes"]["A"]["host_handle_id"]
                receipt, code, error = self._captured_result(
                    lambda: controller.cancel(
                        run_id=run_id,
                        node_id="A",
                        reason="legacy-cancel",
                        evidence_refs=["evidence:legacy-cancel"],
                        now="2026-08-22T10:01:00Z",
                        expected_revision=store.read_run_head(run_id)["revision"],
                    )
                )
                events = store.load_events(run_id)
                silently_cancelled = any(
                    event["event_type"] == "node.cancelled" for event in events
                )
                if error is not None:
                    explicit_refusal = isinstance(code, str) and bool(code)
                else:
                    returned_event = (
                        receipt.get("event", {})
                        if isinstance(receipt, Mapping)
                        else {}
                    )
                    explicit_refusal = (
                        returned_event.get("event_type") == "node.blocked"
                        and returned_event.get("payload", {}).get("blocker_id")
                        == f"host_quiescence_unconfirmed:{handle_id}"
                        and receipt.get("host_quiescence_assurance") == "unconfirmed"
                    )
                self.assertEqual(
                    (False, True),
                    (silently_cancelled, explicit_refusal),
                    f"E_TEST_A265_LEGACY_CANCEL_AUTHORIZED:{code}:{type(error).__name__ if error else 'none'}",
                )
            finally:
                store.close()

    def test_recover_probes_durable_handles_before_readiness(self) -> None:
        graph = authority._compile_graph()
        store = self._store("recover-probe")
        host = authority._LifecycleHost(graph, store=store, probe_state="running")
        run_id = "RUN-RECOVER-PROBE"
        try:
            self._start_active(graph, store, host, run_id)
            recovered = self._controller(graph, store, host)
            before = reduce_graph_events(
                graph,
                store.load_events(run_id),
                expected_bindings=base._bindings(graph),
            )
            expected_handle_id = before["nodes"]["A"]["host_handle_id"]
            expected_attempt = before["nodes"]["A"]["attempt"]
            probes_before = sum(1 for name, _node in host.calls if name == "probe")
            _receipt, code, error = self._captured_result(
                lambda: recovered.recover(
                    run_id=run_id, now="2026-08-22T10:05:00Z"
                )
            )
            self.assertIsNone(error, f"E_TEST_A265_RECOVER_ERROR:{code}")
            events = store.load_events(run_id)
            projection = reduce_graph_events(
                graph,
                events,
                expected_bindings=base._bindings(graph),
            )
            probes_after = sum(1 for name, _node in host.calls if name == "probe")
            probe_events = [
                event
                for event in events
                if event["event_type"] == "host.observation_recorded"
                and event["payload"].get("observation_type") == "probe"
                and event["node_id"] == "A"
            ]
            probe_event = probe_events[0] if len(probe_events) == 1 else {}
            probe_payload = probe_event.get("payload", {})
            probe = probe_payload.get("observation_receipt", {})
            expected_probe_fields = {
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
            block_events = [
                event
                for event in events
                if event["event_type"] == "node.blocked" and event["node_id"] == "A"
            ]
            block = block_events[0] if len(block_events) == 1 else {}
            probe_index = events.index(probe_event) if probe_event else -1
            block_index = events.index(block) if block else -1
            probe_digest = probe.get("receipt_sha256")
            state = projection["nodes"]["A"]
            host_state = projection["host_handles"].get(expected_handle_id, {})
            # recover returns the exact Recovery Receipt, not a Controller Mutation
            # Receipt. Unconfirmed quiescence is therefore asserted from the full
            # public Probe Receipt, its evidence-linked exact blocker, and the
            # resulting projection; no Controller-private handle state is read.
            self.assertEqual(
                (
                    1,
                    1,
                    expected_probe_fields,
                    "goal-teams-host-probe-receipt-v2.65",
                    host.adapter_id,
                    expected_handle_id,
                    run_id,
                    "A",
                    expected_attempt,
                    "running",
                    False,
                    True,
                    1,
                    f"host_quiescence_unconfirmed:{expected_handle_id}",
                    True,
                    "terminal",
                    "blocked",
                    "not_run",
                    "confirmed",
                    "running",
                    False,
                    1,
                ),
                (
                    probes_after - probes_before,
                    len(probe_events),
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
                    len(block_events),
                    block.get("payload", {}).get("blocker_id"),
                    (
                        probe_index >= 0
                        and block_index > probe_index
                        and isinstance(probe_digest, str)
                        and probe_digest in " ".join(block.get("evidence_refs", []))
                    ),
                    state["execution_state"],
                    state["outcome"],
                    state["validation_state"],
                    state["host_binding_assurance"],
                    host_state.get("state"),
                    state["execution_state"] == "ready",
                    host.execute_count.get("A"),
                ),
                "E_TEST_A265_RECOVER_HOST_OBSERVATION_OR_BLOCK_INCOMPLETE",
            )
        finally:
            store.close()

    def test_timeout_reuses_one_quiescence_control_result(self) -> None:
        graph = authority._compile_graph()
        store = self._store("timeout-single-control")
        host = authority._LifecycleHost(
            graph,
            store=store,
            timeout=True,
            cancel_state="running",
            probe_state="cancelled",
        )
        run_id = "RUN-TIMEOUT-SINGLE-CONTROL"
        try:
            controller = self._controller(graph, store, host)
            controller.create_run(
                run_id=run_id, created_at="2026-08-22T10:00:00Z"
            )
            code, error = self._captured_code(
                lambda: controller.run_ready_wave(
                    run_id=run_id,
                    dispatch_inputs=base._dispatch_inputs(graph, self.workspace),
                    now="2026-08-22T10:00:02Z",
                    expected_revision=store.read_run_head(run_id)["revision"],
                )
            )
            self.assertIsNone(error, f"E_TEST_A265_TIMEOUT_CONTROL_ERROR:{code}")
            events = store.load_events(run_id)
            cancel_count = sum(1 for name, _node in host.calls if name == "cancel")
            probe_count = sum(1 for name, _node in host.calls if name == "probe")
            observations = [
                event
                for event in events
                if event["event_type"] == "host.observation_recorded"
            ]
            observation_types = [
                event["payload"].get("observation_type") for event in observations
            ]
            probe_event = next(
                (
                    event
                    for event in observations
                    if event["payload"].get("observation_type") == "probe"
                ),
                {},
            )
            probe = probe_event.get("payload", {}).get(
                "observation_receipt", {}
            )
            cancelled_events = [
                event
                for event in events
                if event["event_type"] == "node.cancelled" and event["node_id"] == "A"
            ]
            cancelled = cancelled_events[0] if len(cancelled_events) == 1 else {}
            probe_index = events.index(probe_event) if probe_event else -1
            cancel_index = events.index(cancelled) if cancelled else -1
            probe_digest = probe.get("receipt_sha256")
            projection = reduce_graph_events(
                graph,
                events,
                expected_bindings=base._bindings(graph),
            )
            state = projection["nodes"]["A"]
            handle_state = projection["host_handles"].get(
                state["host_handle_id"], {}
            )
            # run_ready_wave likewise has no public Mutation Receipt. Confirmed
            # quiescence is bound by the one full Probe Receipt plus the cancelled
            # Host/Node projection and exact timeout reason.
            self.assertEqual(
                (
                    1,
                    1,
                    2,
                    ["cancel", "probe"],
                    "goal-teams-host-probe-receipt-v2.65",
                    state["host_handle_id"],
                    run_id,
                    "A",
                    state["attempt"],
                    "cancelled",
                    True,
                    True,
                    1,
                    "host_timeout",
                    True,
                    "cancelled",
                    "cancelled",
                    "confirmed",
                    "cancelled",
                    0,
                ),
                (
                    cancel_count,
                    probe_count,
                    len(observations),
                    observation_types,
                    probe.get("schema_version"),
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
                    len(cancelled_events),
                    cancelled.get("payload", {}).get("reason"),
                    (
                        probe_index >= 0
                        and cancel_index > probe_index
                        and isinstance(probe_digest, str)
                        and probe_digest
                        in " ".join(cancelled.get("evidence_refs", []))
                    ),
                    state["execution_state"],
                    state["outcome"],
                    state["host_binding_assurance"],
                    handle_state.get("state"),
                    sum(
                        1
                        for event in events
                        if event["event_type"] == "node.blocked"
                    ),
                ),
                "E_TEST_A265_TIMEOUT_CONTROL_OR_ASSURANCE_INCOMPLETE",
            )
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
