from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from scripts.v265.canonical import canonical_sha256
from scripts.v265.graph_runtime import GraphRuntimeError, reduce_graph_events
from scripts.v265.runtime_controller import RuntimeController
from scripts.v265.runtime_store import SQLiteRuntimeStore
from tests.v265 import test_graph_runtime as base
from tests.v265 import test_runtime_execution_authority as authority


READBACK_ORDER_CONTRACT_SHA256 = (
    "1e74a2f418dbb6a4710fe79f8e30e63542afe6d587d3beab450b9f092470ddfc"
)
READBACK_ORDER_PLAN_REVISION = 1
READBACK_ORDER_TASK_EXACT_SET_SHA256 = (
    "09def3cd33119646de7087e79a33c7569ad102e81b7748a0c3f9bcf4a4a5a4f9"
)


class TestO265HostReadbackOrder(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp.name).resolve()
        self.workspace = self.runtime_root / "workspace"
        for node_id in ("A", "B", "JOIN"):
            (self.workspace / "scope" / node_id).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _external_event_stream(
        self, name: str
    ) -> tuple[dict[str, object], list[dict[str, Any]], dict[str, str]]:
        graph = authority._compile_graph(external_a=True)
        bindings = base._bindings(graph)
        store = SQLiteRuntimeStore(
            self.runtime_root / f"{name}.sqlite3",
            runtime_root=self.runtime_root,
            busy_timeout_ms=5000,
        )
        host = authority._LifecycleHost(
            graph,
            store=store,
            readback_state="confirmed",
        )
        run_id = f"RUN-READBACK-{name.upper()}"
        try:
            controller = RuntimeController(
                compiled_graph=graph,
                store=store,
                host_adapter=host,
                run_bindings=bindings,
                max_workers=1,
                authorized_workspace_root=self.runtime_root,
            )
            controller.create_run(
                run_id=run_id, created_at="2026-08-22T10:00:00Z"
            )
            inputs = base._dispatch_inputs(graph, self.workspace)
            inputs["A"]["capability_receipt"] = authority._external_capability(
                graph, "A", self.workspace
            )
            controller.run_ready_wave(
                run_id=run_id,
                dispatch_inputs=inputs,
                now="2026-08-22T10:00:02Z",
                expected_revision=store.read_run_head(run_id)["revision"],
            )
            all_events = [copy.deepcopy(event) for event in store.load_events(run_id)]
        finally:
            store.close()

        confirmation_index = next(
            index
            for index, event in enumerate(all_events)
            if event["event_type"] == "side_effect.confirmed"
            and event["node_id"] == "A"
        )
        # The oracle stops immediately after confirmation. A later Controller
        # implementation may append Node Outcome, but readback must remain running
        # until that distinct Event is reduced.
        return graph, all_events[: confirmation_index + 1], bindings

    @staticmethod
    def _rechain_without_execution(
        events: list[dict[str, Any]], *, run_id: str
    ) -> list[dict[str, Any]]:
        filtered = [
            copy.deepcopy(event)
            for event in events
            if not (
                event["event_type"] == "host.execution_started"
                and event["node_id"] == "A"
            )
        ]
        previous = "0" * 64
        result: list[dict[str, Any]] = []
        for event_seq, event in enumerate(filtered, start=1):
            event["event_id"] = f"EVENT-{run_id}-PREPARED-{event_seq}"
            event["event_seq"] = event_seq
            event["cas_base_revision"] = event_seq - 1
            event["previous_event_sha256"] = previous
            event["event_sha256"] = canonical_sha256(
                {
                    key: value
                    for key, value in event.items()
                    if key != "event_sha256"
                }
            )
            previous = event["event_sha256"]
            result.append(event)
        return result

    def test_running_execution_accepts_readback_and_preserves_running(self) -> None:
        graph, events, bindings = self._external_event_stream("running")
        relevant_types = [
            event["event_type"]
            for event in events
            if event["node_id"] == "A"
            and event["event_type"]
            in {
                "host.prepared",
                "node.started",
                "side_effect.intent",
                "host.execution_started",
                "host.observation_recorded",
                "side_effect.confirmed",
            }
        ]
        projection = reduce_graph_events(
            graph,
            events,
            expected_bindings=bindings,
        )
        node = projection["nodes"]["A"]
        handle = projection["host_handles"][node["host_handle_id"]]
        intent = next(
            event
            for event in events
            if event["event_type"] == "side_effect.intent"
            and event["node_id"] == "A"
        )
        idempotency = projection["idempotency"][
            intent["payload"]["idempotency_key"]
        ]
        self.assertEqual(
            (
                [
                    "host.prepared",
                    "node.started",
                    "side_effect.intent",
                    "host.execution_started",
                    "host.observation_recorded",
                    "side_effect.confirmed",
                ],
                "active",
                "running",
                "readback",
                "confirmed",
            ),
            (
                relevant_types,
                node["execution_state"],
                handle["state"],
                handle["last_observation_type"],
                idempotency["state"],
            ),
            "E_TEST_O265_RUNNING_READBACK_REGRESSION",
        )

    def test_prepared_only_readback_fails_before_idempotency_confirmation(self) -> None:
        graph, running_events, bindings = self._external_event_stream(
            "prepared-only"
        )
        run_id = str(running_events[0]["run_id"])
        prepared_events = self._rechain_without_execution(
            running_events, run_id=run_id
        )
        self.assertNotIn(
            "host.execution_started",
            [event["event_type"] for event in prepared_events],
        )
        readback_index = next(
            index
            for index, event in enumerate(prepared_events)
            if event["event_type"] == "host.observation_recorded"
            and event["node_id"] == "A"
            and event["payload"]["observation_type"] == "readback"
        )
        before_readback = reduce_graph_events(
            graph,
            prepared_events[:readback_index],
            expected_bindings=bindings,
        )
        intent = next(
            event
            for event in prepared_events
            if event["event_type"] == "side_effect.intent"
            and event["node_id"] == "A"
        )
        idempotency_key = intent["payload"]["idempotency_key"]
        code: str | None = None
        caught: Exception | None = None
        full_projection: Mapping[str, Any] | None = None
        try:
            full_projection = reduce_graph_events(
                graph,
                prepared_events,
                expected_bindings=bindings,
            )
        except Exception as exc:  # product rejection becomes an explicit assertion
            caught = exc
            code = getattr(exc, "code", None)
        confirmed = (
            full_projection is not None
            and full_projection["idempotency"][idempotency_key]["state"]
            == "confirmed"
        )
        self.assertEqual(
            ("pending", "E_V265_HOST_LIFECYCLE", False, GraphRuntimeError),
            (
                before_readback["idempotency"][idempotency_key]["state"],
                code,
                confirmed,
                type(caught) if caught is not None else None,
            ),
            "E_TEST_O265_PREPARED_READBACK_CONFIRMED",
        )


if __name__ == "__main__":
    unittest.main()
