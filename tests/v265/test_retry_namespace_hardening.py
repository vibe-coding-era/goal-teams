from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from tests.v265 import test_graph_runtime as fx
from tests.v265 import test_runtime_semantic_closure as closure


CONTRACT_SHA256 = "dc6e7b513c15ef4537772296998829afd4809376fecc31ed7ad0627aa8653568"
PLAN_REVISION = 1
TASK_EXACT_SET_SHA256 = "c4a98383e3791fda6e9fc10b1ed8c8d6dbe9dfd5db04738af4a10327ed5a320e"


def _reserved_document(
    *, edge_type: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    _source, plan, validation, document = closure._fully_bound_inputs()
    if edge_type == "dependency":
        edge = next(item for item in document["edges"] if item["edge_id"] == "dep:A:JOIN")
        edge["edge_id"] = "retry_policy:declared-dependency"
        join = next(item for item in document["nodes"] if item["node_id"] == "JOIN")
        join["fan_in"]["edge_ids"] = sorted(
            "retry_policy:declared-dependency" if item == "dep:A:JOIN" else item
            for item in join["fan_in"]["edge_ids"]
        )
    else:
        edge = fx._edge(
            "retry_policy:declared-repeat",
            "repeat",
            "A",
            "A",
            accepted_outcomes=["failed"],
        )
        edge["traversal_budget"] = 1
        document["edges"].append(edge)
    return plan, validation, document


def _reserved_rehashed_graph() -> dict[str, Any]:
    graph = closure._compile_fully_bound()
    candidate = copy.deepcopy(graph)
    edge = next(item for item in candidate["edges"] if item["edge_id"] == "dep:A:JOIN")
    edge["edge_id"] = "retry_policy:declared-dependency"
    candidate["edges"] = sorted(candidate["edges"], key=lambda item: item["edge_id"])
    join = next(item for item in candidate["nodes"] if item["node_id"] == "JOIN")
    join["fan_in"]["edge_ids"] = sorted(
        "retry_policy:declared-dependency" if item == "dep:A:JOIN" else item
        for item in join["fan_in"]["edge_ids"]
    )
    candidate["fan_in_map"]["JOIN"] = copy.deepcopy(join["fan_in"])
    candidate["execution_edge_ids"] = sorted(
        "retry_policy:declared-dependency" if item == "dep:A:JOIN" else item
        for item in candidate["execution_edge_ids"]
    )
    return closure._rehash_compiled(candidate)


class TestV265RetryNamespaceHardening(unittest.TestCase):
    """Immutable Red denominator for the retry namespace and integer boundary."""

    _append = closure.TestV265RuntimeSemanticClosure._append
    _created = closure.TestV265RuntimeSemanticClosure._created
    _dispatch = closure.TestV265RuntimeSemanticClosure._dispatch
    _start_attempt = closure.TestV265RuntimeSemanticClosure._start_attempt
    _record_outcome = closure.TestV265RuntimeSemanticClosure._record_outcome

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name).resolve() / "workspace"
        for node_id in ("A", "B", "JOIN"):
            (self.workspace / "scope" / node_id).mkdir(parents=True, exist_ok=True)
        self.graph_contract = closure._target("scripts.v265.graph_contract")
        self.runtime = closure._target("scripts.v265.graph_runtime")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_compiler_rejects_reserved_namespace_for_every_real_edge_kind(self) -> None:
        self.assertRegex(CONTRACT_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(1, PLAN_REVISION)
        self.assertRegex(TASK_EXACT_SET_SHA256, r"^[0-9a-f]{64}$")
        for edge_type in ("dependency", "repeat"):
            plan, validation, document = _reserved_document(edge_type=edge_type)
            with self.subTest(edge_type=edge_type):
                with self.assertRaises(self.graph_contract.GraphContractError) as caught:
                    self.graph_contract.compile_graph_contract(
                        document,
                        compiled_task_plan=plan,
                        task_plan_validation_receipt=validation,
                    )
                self.assertEqual(
                    "E_V265_GRAPH_TRAVERSAL_BUDGET", caught.exception.code
                )

    def test_direct_intrinsic_preserves_single_invalid_receipt_boundary(self) -> None:
        with self.assertRaises(self.graph_contract.GraphContractError) as caught:
            self.graph_contract.validate_graph_intrinsic(_reserved_rehashed_graph())
        self.assertEqual("E_V265_GRAPH_RECEIPT_INVALID", caught.exception.code)

    def test_runtime_wrapper_maps_reserved_edge_to_integrity_error(self) -> None:
        with self.assertRaises(self.runtime.GraphRuntimeError) as caught:
            self.runtime.validate_runtime_graph_contract(_reserved_rehashed_graph())
        self.assertEqual("E_V265_RUNTIME_GRAPH_INTEGRITY", caught.exception.code)

    def _retry_prefix(self) -> tuple[dict[str, object], str, list[dict[str, object]]]:
        def retry_node(document: dict[str, object]) -> None:
            node = next(item for item in document["nodes"] if item["node_id"] == "A")
            node["recovery_policy"] = {"mode": "retry", "edge_id": None}

        graph = closure._compile_fully_bound(retry_node)
        run_id = "RUN-RETRY-INTEGER"
        events = self._created(graph, run_id)
        self._start_attempt(events, graph, run_id, "A", 1, emit_ready=True)
        self._record_outcome(
            events, graph, run_id, "A", 1, "failed", validate=False
        )
        return graph, run_id, events

    def test_retry_payload_requires_exact_positive_json_integers(self) -> None:
        graph, run_id, prefix = self._retry_prefix()
        cases = (
            ("traversal_true", "traversal_count", True),
            ("traversal_float", "traversal_count", 1.0),
            ("traversal_zero", "traversal_count", 0),
            ("traversal_negative", "traversal_count", -1),
            ("attempt_true", "next_attempt", True),
            ("attempt_float", "next_attempt", 2.0),
            ("attempt_zero", "next_attempt", 0),
            ("attempt_negative", "next_attempt", -1),
        )
        for name, field, value in cases:
            events = copy.deepcopy(prefix)
            payload: dict[str, object] = {
                "source_edge_id": "retry_policy:A",
                "traversal_count": 1,
                "next_attempt": 2,
            }
            payload[field] = value
            self._append(
                events,
                graph,
                run_id=run_id,
                event_type="node.retry_scheduled",
                node_id="A",
                attempt=1,
                payload=payload,
                actor="runtime_controller",
            )
            with self.subTest(case=name):
                try:
                    projection = self.runtime.reduce_graph_events(
                        graph, events, expected_bindings=fx._bindings(graph)
                    )
                except self.runtime.GraphRuntimeError as exc:
                    self.assertEqual("E_V265_RUNTIME_ATTEMPT_BUDGET", exc.code)
                except Exception as exc:
                    self.fail(
                        f"E_TEST_V265_RETRY_INTEGER_EXCEPTION:{type(exc).__name__}:{exc}"
                    )
                else:
                    observed = projection["traversal_counts"].get("retry_policy:A")
                    self.fail(
                        f"E_TEST_V265_RETRY_NON_INTEGER_ACCEPTED:{name}:{observed!r}"
                    )

    def test_non_reserved_positive_repeat_edge_remains_reachable_and_bounded(self) -> None:
        def real_repeat(document: dict[str, object]) -> None:
            edge = fx._edge(
                "repeat:A:A",
                "repeat",
                "A",
                "A",
                accepted_outcomes=["failed"],
            )
            edge["traversal_budget"] = 1
            document["edges"].append(edge)

        graph = closure._compile_fully_bound(real_repeat)
        run_id = "RUN-REAL-REPEAT"
        events = self._created(graph, run_id)
        self._start_attempt(events, graph, run_id, "A", 1, emit_ready=True)
        self._record_outcome(
            events, graph, run_id, "A", 1, "failed", validate=True
        )
        self._append(
            events,
            graph,
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id="A",
            attempt=1,
            payload={
                "source_edge_id": "repeat:A:A",
                "traversal_count": 1,
                "next_attempt": 2,
            },
            actor="runtime_controller",
        )
        projection = self.runtime.reduce_graph_events(
            graph, events, expected_bindings=fx._bindings(graph)
        )
        self.assertEqual("ready", projection["nodes"]["A"]["execution_state"])
        count = projection["traversal_counts"]["repeat:A:A"]
        self.assertIs(type(count), int)
        self.assertEqual(1, count)


if __name__ == "__main__":
    unittest.main()
