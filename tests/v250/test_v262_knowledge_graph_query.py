from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "5" * 64
PROFILE_SHA256 = "6" * 64


def _target(testcase: unittest.TestCase):
    try:
        return importlib.import_module("scripts.v250.okf_document_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v250.okf_document_graph":
            testcase.fail("E_KG262_TARGET_MISSING: scripts.v250.okf_document_graph")
        raise


def _graph(kg):
    return kg.load_current_graph(
        FIXTURES / "current",
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


class TestV262KnowledgeGraphQuery(unittest.TestCase):
    def assert_query_contract(self, graph, result: dict, query_kind: str) -> None:
        self.assertEqual(graph.graph_iri, result["graph_iri"])
        self.assertEqual(graph.graph_input_sha256, result["graph_input_sha256"])
        self.assertEqual(query_kind, result["query_kind"])
        self.assertEqual("completed", result["run_status"])
        self.assertEqual("record", result["current_action"])
        self.assertEqual("not_run", result["persistence"])
        self.assertIn("results", result)
        self.assertIn("limit", result)
        self.assertIsInstance(result["truncated"], bool)

    def test_resolve_and_search_are_graph_bound_and_deterministic(self) -> None:
        kg = _target(self)
        graph = _graph(kg)
        reference = "product.current:REQ-001@1#CLM-REQ-001-01"

        resolved = graph.resolve(reference)
        self.assert_query_contract(graph, resolved, "resolve")
        self.assertIn(reference, json.dumps(resolved["results"], ensure_ascii=False))

        searched = graph.search("grounded answer", limit=7)
        self.assert_query_contract(graph, searched, "search")
        self.assertEqual(7, searched["limit"])
        self.assertIn("product.current:REQ-001@1", json.dumps(searched["results"]))
        self.assertEqual(searched, graph.search("grounded answer", limit=7))

    def test_neighbors_only_follow_asserted_direct_triples(self) -> None:
        kg = _target(self)
        graph = _graph(kg)
        source = "product.current:REQ-001@1#CLM-REQ-001-01"

        result = graph.neighbors(
            source,
            direction="out",
            predicate="HAS_AC",
            limit=11,
        )
        self.assert_query_contract(graph, result, "neighbors")
        rendered = json.dumps(result["results"], ensure_ascii=False)
        self.assertIn("product.current:AC-001@1#CLM-AC-001-01", rendered)
        self.assertNotIn("described", rendered.lower())

    def test_trace_and_explain_return_current_claim_grounding(self) -> None:
        kg = _target(self)
        graph = _graph(kg)
        reference = "product.current:REQ-001@1#CLM-REQ-001-01"

        traced = graph.trace(reference, max_depth=2, limit=13)
        self.assert_query_contract(graph, traced, "trace")
        self.assertIn("product.current:AC-001@1", json.dumps(traced["results"]))

        explained = graph.explain(reference)
        self.assert_query_contract(graph, explained, "explain")
        rendered = json.dumps(explained["results"], ensure_ascii=False)
        self.assertIn("A factual answer cites an exact Current Claim occurrence.", rendered)
        self.assertIn("evidence/request.md", rendered)

    def test_observe_is_a_non_gating_query_receipt(self) -> None:
        kg = _target(self)
        graph = _graph(kg)
        result = graph.observe()
        self.assert_query_contract(graph, result, "observe")
        self.assertNotIn("gate", result)
        self.assertNotIn("enforce", json.dumps(result).lower())


if __name__ == "__main__":
    unittest.main()
