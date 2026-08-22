from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

from scripts.v265.canonical import canonical_sha256
from scripts.v265.graph_runtime import reduce_graph_events
from scripts.v265.host_adapter import CallbackHostAdapter
from scripts.v265.runtime_controller import RuntimeController
from scripts.v265.runtime_store import SQLiteRuntimeStore
from tests.v265 import test_graph_runtime as base
from tests.v265 import test_loop_coordinator as loop_fixture
from tests.v265 import test_runtime_execution_authority as authority
from tests.v265.test_loop_review import ZERO_SHA256


INTEGRATION_CHAIN_ID = "H265-05-LOCAL-HARDENING-INTEGRATION"


class _IntegrationLifecycleHost(authority._LifecycleHost):
    """Reviewable local external-authority fake; never performs a real effect."""

    real_external_effects = False

    def handle_for(self, host_handle_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._handles[host_handle_id])

    def wait(
        self, handle: Mapping[str, Any], *, timeout_seconds: int
    ) -> dict[str, Any]:
        outcome = super().wait(handle, timeout_seconds=timeout_seconds)
        outcome["started_at"] = "2026-08-22T10:02:04Z"
        outcome["finished_at"] = "2026-08-22T10:02:05Z"
        outcome["observation_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in outcome.items()
                if key != "observation_sha256"
            }
        )
        return outcome


class TestH265RuntimeHardeningIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp.name).resolve()
        self.workspace = self.runtime_root / "workspace"
        for node_id in ("A", "B", "JOIN"):
            (self.workspace / "scope" / node_id).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _controller(
        self,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        host: object,
        *,
        max_workers: int,
    ) -> RuntimeController:
        return RuntimeController(
            compiled_graph=graph,
            store=store,
            host_adapter=host,
            run_bindings=base._bindings(graph),
            max_workers=max_workers,
            authorized_workspace_root=self.runtime_root,
        )

    def _activate_legacy_node(
        self,
        graph: dict[str, object],
        store: SQLiteRuntimeStore,
        run_id: str,
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

    def _runtime_dag_hitl_phase(self, evidence_chain: list[str]) -> dict[str, Any]:
        graph = base._compiled_graph()
        bindings = base._bindings(graph)
        run_id = "RUN-H265-05-INTEGRATION"
        database_path = self.runtime_root / "integration-runtime.sqlite3"
        store = SQLiteRuntimeStore(
            database_path,
            runtime_root=self.runtime_root,
            busy_timeout_ms=5000,
        )
        barrier = threading.Barrier(2, timeout=5)
        lock = threading.Lock()
        active = 0
        maximum_active = 0
        callback_count = {"A": 0, "B": 0}

        def callback(dispatch: Mapping[str, Any]) -> dict[str, Any]:
            nonlocal active, maximum_active
            node_id = str(dispatch["node_id"])
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                callback_count[node_id] += 1
            try:
                barrier.wait()
                return {
                    "outcome": "completed",
                    "artifact_receipts": [
                        base._artifact(
                            graph,
                            str(dispatch["run_id"]),
                            node_id,
                            int(dispatch["attempt"]),
                        )
                    ],
                    "evidence_refs": [f"evidence:{INTEGRATION_CHAIN_ID}:{node_id}"],
                    "side_effects": [],
                }
            finally:
                with lock:
                    active -= 1

        callback_host = CallbackHostAdapter(
            {"action:A": callback, "action:B": callback},
            adapter_id="callback_fixture",
            max_workers=2,
            clock=lambda: "2026-08-22T10:00:04Z",
        )
        external_host: _IntegrationLifecycleHost | None = None
        try:
            controller = self._controller(
                graph, store, callback_host, max_workers=2
            )
            controller.create_run(
                run_id=run_id, created_at="2026-08-22T10:00:00Z"
            )
            wave = controller.run_ready_wave(
                run_id=run_id,
                dispatch_inputs=base._dispatch_inputs(graph, self.workspace),
                now="2026-08-22T10:00:02Z",
                expected_revision=store.read_run_head(run_id)["revision"],
            )

            for node_id in ("A", "B"):
                projection = reduce_graph_events(
                    graph,
                    store.load_events(run_id),
                    expected_bindings=bindings,
                )
                artifacts = projection["nodes"][node_id]["artifact_receipts"]
                validation = base._validation_receipt(
                    graph, run_id, node_id, artifacts
                )
                controller.validate_node(
                    run_id=run_id,
                    node_id=node_id,
                    validator_run_id=f"RUN-VALIDATOR-{node_id}",
                    validation_receipt=validation,
                    now="2026-08-22T10:00:11Z",
                    expected_revision=store.read_run_head(run_id)["revision"],
                )

            runtime = __import__(
                "scripts.v265.graph_runtime", fromlist=["make_graph_event"]
            )
            gate = base._gate_receipt(graph, run_id)
            head = store.read_run_head(run_id)
            gate_event = base._make_event(
                runtime,
                compiled_graph=graph,
                run_id=run_id,
                event_seq=head["revision"] + 1,
                event_type="gate.passed",
                node_id=None,
                attempt=0,
                previous_event_sha256=head["last_event_sha256"],
                payload={
                    "gate_id": gate["gate_id"],
                    "gate_receipt": gate,
                    "gate_decision_sha256": gate["receipt_sha256"],
                    "decision": "passed",
                },
                actor_identity="validator:JOIN",
            )
            store.append_event(
                run_id, gate_event, expected_revision=head["revision"]
            )
            ready = controller.evaluate_next(
                run_id=run_id, now="2026-08-22T10:02:00Z"
            )
            join_ready = next(item for item in ready if item["node_id"] == "JOIN")

            callback_host.close()
            external_host = _IntegrationLifecycleHost(
                graph,
                store=store,
                cancel_state="cancelled",
                probe_state="cancelled",
                outcomes={"JOIN": "completed"},
            )
            join_controller = self._controller(
                graph, store, external_host, max_workers=1
            )
            head = store.read_run_head(run_id)
            ready_event = base._make_event(
                runtime,
                compiled_graph=graph,
                run_id=run_id,
                event_seq=head["revision"] + 1,
                event_type="node.ready",
                node_id="JOIN",
                attempt=int(join_ready["next_attempt"]),
                previous_event_sha256=head["last_event_sha256"],
                payload={
                    key: join_ready[key]
                    for key in (
                        "satisfied_edge_ids",
                        "fan_in_mode",
                        "required_edge_count",
                        "satisfied_edge_count",
                    )
                },
                actor_identity="runtime_controller",
            )
            store.append_event(
                run_id, ready_event, expected_revision=head["revision"]
            )
            claim_one = join_controller.claim_node(
                run_id=run_id,
                node_id="JOIN",
                worker_id="WORKER-JOIN-1",
                lease_seconds=60,
                now="2026-08-22T10:02:00Z",
                expected_revision=store.read_run_head(run_id)["revision"],
            )
            context, context_validation = base._context_bundle(graph, "JOIN")
            join_controller.start_node(
                run_id=run_id,
                node_id="JOIN",
                lease_id=claim_one["event"]["payload"]["lease_id"],
                owner_run_id="RUN-OWNER-JOIN",
                validator_run_id="RUN-VALIDATOR-JOIN",
                context_bundle=context,
                context_validation_receipt=context_validation,
                capability_receipt=base._capability(
                    graph, "JOIN", self.workspace
                ),
                now="2026-08-22T10:02:00Z",
                expected_revision=claim_one["revision"],
            )
            interrupted = join_controller.interrupt(
                run_id=run_id,
                node_id="JOIN",
                gate_id="gate:human:A",
                interrupt_id="INTERRUPT-GLOBAL-JOIN",
                reason="global human approval",
                evidence_refs=[f"evidence:{INTEGRATION_CHAIN_ID}:interrupt"],
                now="2026-08-22T10:02:01Z",
                expected_revision=store.read_run_head(run_id)["revision"],
            )
            approval = base._approval_receipt(
                graph,
                "JOIN",
                interrupt_id="INTERRUPT-GLOBAL-JOIN",
            )
            approval["gate_id"] = "gate:human:A"
            approval = authority._rehash(approval, "receipt_sha256")
            resumed = join_controller.resume(
                run_id=run_id,
                node_id="JOIN",
                interrupt_id="INTERRUPT-GLOBAL-JOIN",
                approval_receipt=approval,
                now="2026-08-22T10:02:02Z",
                expected_revision=interrupted["revision"],
            )
            claim_two = join_controller.claim_node(
                run_id=run_id,
                node_id="JOIN",
                worker_id="WORKER-JOIN-2",
                lease_seconds=60,
                now="2026-08-22T10:02:03Z",
                expected_revision=resumed["revision"],
            )
            join_controller.start_node(
                run_id=run_id,
                node_id="JOIN",
                lease_id=claim_two["event"]["payload"]["lease_id"],
                owner_run_id="RUN-OWNER-JOIN",
                validator_run_id="RUN-VALIDATOR-JOIN",
                context_bundle=context,
                context_validation_receipt=context_validation,
                capability_receipt=base._capability(
                    graph, "JOIN", self.workspace
                ),
                now="2026-08-22T10:02:04Z",
                expected_revision=claim_two["revision"],
            )
            running = reduce_graph_events(
                graph,
                store.load_events(run_id),
                expected_bindings=bindings,
            )
            join_handle_id = running["nodes"]["JOIN"]["host_handle_id"]
            outcome = external_host.wait(
                external_host.handle_for(join_handle_id), timeout_seconds=60
            )
            completed = join_controller.complete_node(
                run_id=run_id,
                node_id="JOIN",
                lease_id=running["nodes"]["JOIN"]["lease_id"],
                artifact_receipts=outcome["artifact_receipts"],
                evidence_refs=outcome["evidence_refs"],
                now=outcome["finished_at"],
                expected_revision=store.read_run_head(run_id)["revision"],
            )
            join_validation = base._validation_receipt(
                graph, run_id, "JOIN", outcome["artifact_receipts"]
            )
            join_validation["attempt"] = 2
            join_validation = authority._rehash(
                join_validation, "receipt_sha256"
            )
            join_controller.validate_node(
                run_id=run_id,
                node_id="JOIN",
                validator_run_id="RUN-VALIDATOR-JOIN",
                validation_receipt=join_validation,
                now="2026-08-22T10:02:06Z",
                expected_revision=completed["revision"],
            )
            events = store.load_events(run_id)
            final = reduce_graph_events(
                graph, events, expected_bindings=bindings
            )
            evidence_chain.extend(
                [
                    f"runtime:{run_id}",
                    f"projection:{final['projection_sha256']}",
                    f"event:{events[-1]['event_sha256']}",
                ]
            )
            owner_validator_pairs = {
                node_id: (
                    final["nodes"][node_id]["owner_run_id"],
                    final["nodes"][node_id]["validator_run_id"],
                )
                for node_id in ("A", "B", "JOIN")
            }
            join_event_types = [
                event["event_type"]
                for event in events
                if event["node_id"] == "JOIN"
            ]
            serialized = json.dumps(events, sort_keys=True).lower()
            return {
                "wave_ready": wave["ready_node_ids"],
                "wave_completed": wave["completed_node_ids"],
                "maximum_active": maximum_active,
                "callback_count": callback_count,
                "callback_assurance": callback_host.proof_strength,
                "fake_external_assurance": external_host.proof_strength,
                "real_external_effects": external_host.real_external_effects,
                "join_satisfied_edges": join_ready["satisfied_edge_ids"],
                "join_required_count": join_ready["required_edge_count"],
                "join_attempt": final["nodes"]["JOIN"]["attempt"],
                "final_nodes": {
                    node_id: (
                        final["nodes"][node_id]["execution_state"],
                        final["nodes"][node_id]["outcome"],
                        final["nodes"][node_id]["validation_state"],
                    )
                    for node_id in ("A", "B", "JOIN")
                },
                "owner_validator_pairs": owner_validator_pairs,
                "gate_states": final["gate_states"],
                "interrupt_state": final["interrupts"][
                    "INTERRUPT-GLOBAL-JOIN"
                ]["state"],
                "join_event_types": join_event_types,
                "mock_absent": "mock" not in serialized,
                "final_projection_sha256": final["projection_sha256"],
            }
        finally:
            try:
                callback_host.close()
            except Exception:
                pass
            store.close()

    def _crash_recovery_phase(self, evidence_chain: list[str]) -> dict[str, Any]:
        graph = base._compiled_graph()
        bindings = base._bindings(graph)
        run_id = "RUN-H265-05-CRASH"
        database_path = self.runtime_root / "integration-crash.sqlite3"
        store = SQLiteRuntimeStore(
            database_path,
            runtime_root=self.runtime_root,
            busy_timeout_ms=5000,
        )
        self._activate_legacy_node(graph, store, run_id)
        store.close()

        pid = os.fork()
        if pid == 0:
            try:
                child = SQLiteRuntimeStore(
                    database_path,
                    runtime_root=self.runtime_root,
                    busy_timeout_ms=5000,
                )
                runtime = __import__(
                    "scripts.v265.graph_runtime", fromlist=["make_graph_event"]
                )
                action = next(
                    item
                    for item in graph["actions"]
                    if item["action_id"] == "action:A"
                )
                head = child.read_run_head(run_id)
                intent = base._make_event(
                    runtime,
                    compiled_graph=graph,
                    run_id=run_id,
                    event_seq=head["revision"] + 1,
                    event_type="side_effect.intent",
                    node_id="A",
                    attempt=1,
                    previous_event_sha256=head["last_event_sha256"],
                    payload={
                        "idempotency_key": "KEY-H265-05-CONFIRMED",
                        "action_sha256": canonical_sha256(action),
                    },
                    actor_identity="RUN-OWNER-A",
                )
                child.reserve_idempotency_key(
                    run_id,
                    "A",
                    "KEY-H265-05-CONFIRMED",
                    intent,
                    expected_revision=head["revision"],
                )
                head = child.read_run_head(run_id)
                confirmation = base._make_event(
                    runtime,
                    compiled_graph=graph,
                    run_id=run_id,
                    event_seq=head["revision"] + 1,
                    event_type="side_effect.confirmed",
                    node_id="A",
                    attempt=1,
                    previous_event_sha256=head["last_event_sha256"],
                    payload={
                        "idempotency_key": "KEY-H265-05-CONFIRMED",
                        "result_digest": "5" * 64,
                        "readback_receipt_sha256": "6" * 64,
                    },
                    actor_identity="RUN-OWNER-A",
                )
                child.confirm_idempotency_key(
                    run_id,
                    "KEY-H265-05-CONFIRMED",
                    "5" * 64,
                    confirmation,
                    expected_revision=head["revision"],
                )
                os._exit(23)
            except BaseException:
                os._exit(91)

        waited_pid, status = os.waitpid(pid, 0)
        exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
        reopened = SQLiteRuntimeStore(
            database_path,
            runtime_root=self.runtime_root,
            busy_timeout_ms=5000,
        )
        callback_count = 0

        def should_not_execute(_dispatch: Mapping[str, Any]) -> dict[str, Any]:
            nonlocal callback_count
            callback_count += 1
            return {
                "outcome": "completed",
                "artifact_receipts": [],
                "evidence_refs": ["evidence:unexpected-execute"],
                "side_effects": [],
            }

        adapter = CallbackHostAdapter(
            {"action:A": should_not_execute},
            adapter_id="callback_fixture",
            max_workers=1,
            clock=lambda: "2026-08-22T10:05:00Z",
        )
        try:
            verification = reopened.verify_run(run_id)
            recovery = self._controller(
                graph, reopened, adapter, max_workers=1
            ).recover(run_id=run_id, now="2026-08-22T10:05:00Z")
            record = reopened.get_idempotency_record(
                run_id, "KEY-H265-05-CONFIRMED"
            )
            runtime = __import__(
                "scripts.v265.graph_runtime", fromlist=["make_graph_event"]
            )
            action = next(
                item
                for item in graph["actions"]
                if item["action_id"] == "action:A"
            )
            head = reopened.read_run_head(run_id)
            duplicate_event = base._make_event(
                runtime,
                compiled_graph=graph,
                run_id=run_id,
                event_seq=head["revision"] + 1,
                event_type="side_effect.intent",
                node_id="A",
                attempt=2,
                previous_event_sha256=head["last_event_sha256"],
                payload={
                    "idempotency_key": "KEY-H265-05-CONFIRMED",
                    "action_sha256": canonical_sha256(action),
                },
                actor_identity="RUN-OWNER-A",
            )
            duplicate = reopened.reserve_idempotency_key(
                run_id,
                "A",
                "KEY-H265-05-CONFIRMED",
                duplicate_event,
                expected_revision=head["revision"],
            )
            evidence_chain.extend(
                [
                    f"crash:{waited_pid}:{exit_code}",
                    f"store:{verification['projection_sha256']}",
                    f"idempotency:{record['result_digest']}",
                ]
            )
            return {
                "exit_code": exit_code,
                "verified": verification["verified"],
                "record_state": record["state"],
                "result_digest": record["result_digest"],
                "recovery_ready": recovery["ready_node_ids"],
                "reconciliation": recovery[
                    "reconciliation_required_node_ids"
                ],
                "duplicate_execute": duplicate["execute"],
                "duplicate_result": duplicate["result_digest"],
                "callback_count": callback_count,
            }
        finally:
            adapter.close()
            reopened.close()

    def _coordinator_phase(self, evidence_chain: list[str]) -> dict[str, Any]:
        coordinator = __import__(
            "scripts.v265.loop_coordinator", fromlist=["begin_round"]
        )
        review = __import__(
            "scripts.v265.loop_review", fromlist=["inspect_loop_review"]
        )
        project_root = self.runtime_root / "coordinator-project"
        project_root.mkdir()
        relative_path = "GoalTeamsWork/versions/V2.65/loop-review.md"
        first = coordinator.begin_round(
            project_root,
            relative_path,
            loop_fixture._descriptor(loop_round=1),
            expected_coordinator_revision=0,
        )
        end_one = loop_fixture._unsigned_review(
            trigger="loop_end",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
            loop_round=1,
        )
        final_one = coordinator.finalize_round(
            project_root,
            relative_path,
            end_one,
            active_review_ids=[end_one["review_id"]],
            compiled_at="2026-08-22T11:02:00Z",
            expected_coordinator_revision=first["coordinator_revision_after"],
        )
        second = coordinator.begin_round(
            project_root,
            relative_path,
            loop_fixture._descriptor(loop_round=2),
            expected_coordinator_revision=final_one[
                "coordinator_revision_after"
            ],
        )
        inspection = review.inspect_loop_review(project_root, relative_path)
        end_two = loop_fixture._unsigned_review(
            trigger="loop_end",
            sequence=2,
            previous_review_sha256=inspection["last_review_sha256"],
            loop_round=2,
        )
        final_two = coordinator.finalize_round(
            project_root,
            relative_path,
            end_two,
            active_review_ids=[end_two["review_id"]],
            compiled_at="2026-08-22T11:03:00Z",
            expected_coordinator_revision=second[
                "coordinator_revision_after"
            ],
        )
        review_path = project_root / relative_path
        capsule_one_path = project_root / final_one["capsule_relative_path"]
        capsule_two_path = project_root / final_two["capsule_relative_path"]
        markdown = review_path.read_text(encoding="utf-8")
        capsule_one = json.loads(capsule_one_path.read_text(encoding="utf-8"))
        capsule_two = json.loads(capsule_two_path.read_text(encoding="utf-8"))
        evidence_chain.extend(
            [
                f"review:{inspection['last_review_sha256']}",
                f"capsule:{final_one['capsule_sha256']}",
                f"capsule:{final_two['capsule_sha256']}",
            ]
        )
        return {
            "review_exists": review_path.is_file(),
            "review_one": markdown.count(f"## {end_one['review_id']}\n"),
            "review_two": markdown.count(f"## {end_two['review_id']}\n"),
            "capsule_one_exists": capsule_one_path.is_file(),
            "capsule_two_exists": capsule_two_path.is_file(),
            "capsules_distinct": capsule_one_path != capsule_two_path,
            "capsule_one_sha": capsule_one["capsule_sha256"],
            "capsule_two_sha": capsule_two["capsule_sha256"],
            "receipt_one_sha": final_one["capsule_sha256"],
            "receipt_two_sha": final_two["capsule_sha256"],
            "finalized_one": final_one["finalized"],
            "finalized_two": final_two["finalized"],
            "loop_round_two": final_two["loop_round"],
        }

    def test_local_hardening_chain_runtime_crash_and_two_round_review(self) -> None:
        evidence_chain = [f"chain:{INTEGRATION_CHAIN_ID}"]
        facts: dict[str, dict[str, Any]] = {}
        errors: dict[str, Exception | None] = {
            "runtime": None,
            "crash": None,
            "coordinator": None,
        }
        for phase, operation in (
            ("runtime", self._runtime_dag_hitl_phase),
            ("crash", self._crash_recovery_phase),
            ("coordinator", self._coordinator_phase),
        ):
            try:
                facts[phase] = operation(evidence_chain)
            except Exception as exc:  # integration product failure remains a test FAIL
                errors[phase] = exc
                facts[phase] = {}

        with self.subTest(phase="runtime_dag_hitl"):
            runtime = facts["runtime"]
            self.assertIsNone(
                errors["runtime"],
                f"E_TEST_H265_INTEGRATION_RUNTIME:{errors['runtime']}",
            )
            self.assertEqual(["A", "B"], runtime["wave_ready"])
            self.assertEqual(["A", "B"], runtime["wave_completed"])
            self.assertEqual(2, runtime["maximum_active"])
            self.assertEqual({"A": 1, "B": 1}, runtime["callback_count"])
            self.assertEqual("fixture_only", runtime["callback_assurance"])
            self.assertEqual(
                "externally_attested", runtime["fake_external_assurance"]
            )
            self.assertFalse(runtime["real_external_effects"])
            self.assertEqual(4, runtime["join_required_count"])
            self.assertEqual(
                {
                    "dep:A:JOIN",
                    "dep:B:JOIN",
                    "data:A:JOIN",
                    "data:B:JOIN",
                },
                set(runtime["join_satisfied_edges"]),
            )
            self.assertEqual(2, runtime["join_attempt"])
            self.assertEqual(
                {
                    "A": ("terminal", "completed", "passed"),
                    "B": ("terminal", "completed", "passed"),
                    "JOIN": ("terminal", "completed", "passed"),
                },
                runtime["final_nodes"],
            )
            self.assertTrue(
                all(
                    owner != validator
                    for owner, validator in runtime["owner_validator_pairs"].values()
                )
            )
            self.assertEqual("passed", runtime["gate_states"]["gate:join-evidence"])
            self.assertEqual("passed", runtime["gate_states"]["gate:human:A"])
            self.assertEqual("resolved", runtime["interrupt_state"])
            self.assertIn("node.interrupted", runtime["join_event_types"])
            self.assertIn("node.resumed", runtime["join_event_types"])
            self.assertTrue(runtime["mock_absent"])

        with self.subTest(phase="subprocess_crash_recovery"):
            crash = facts["crash"]
            self.assertIsNone(
                errors["crash"],
                f"E_TEST_H265_INTEGRATION_CRASH:{errors['crash']}",
            )
            self.assertEqual(23, crash["exit_code"])
            self.assertTrue(crash["verified"])
            self.assertEqual("confirmed", crash["record_state"])
            self.assertEqual("5" * 64, crash["result_digest"])
            self.assertNotIn("A", crash["recovery_ready"])
            self.assertEqual([], crash["reconciliation"])
            self.assertFalse(crash["duplicate_execute"])
            self.assertEqual("5" * 64, crash["duplicate_result"])
            self.assertEqual(0, crash["callback_count"])

        with self.subTest(phase="coordinator_two_rounds"):
            coordinator = facts["coordinator"]
            self.assertIsNone(
                errors["coordinator"],
                f"E_TEST_H265_INTEGRATION_COORDINATOR:{errors['coordinator']}",
            )
            self.assertTrue(coordinator["review_exists"])
            self.assertEqual(1, coordinator["review_one"])
            self.assertEqual(1, coordinator["review_two"])
            self.assertTrue(coordinator["capsule_one_exists"])
            self.assertTrue(coordinator["capsule_two_exists"])
            self.assertTrue(coordinator["capsules_distinct"])
            self.assertEqual(
                coordinator["receipt_one_sha"], coordinator["capsule_one_sha"]
            )
            self.assertEqual(
                coordinator["receipt_two_sha"], coordinator["capsule_two_sha"]
            )
            self.assertTrue(coordinator["finalized_one"])
            self.assertTrue(coordinator["finalized_two"])
            self.assertEqual(2, coordinator["loop_round_two"])

        self.assertGreaterEqual(len(evidence_chain), 10)
        self.assertEqual(len(evidence_chain), len(set(evidence_chain)))


if __name__ == "__main__":
    unittest.main()
