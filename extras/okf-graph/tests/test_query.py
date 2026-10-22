"""Native queries: graph-bound receipts with explicit match and ambiguity state."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import BASE_IRI, BASIC, active_map, document, load


class TestQueryReceipts(unittest.TestCase):
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
        graph = load(BASIC)
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
        graph = load(BASIC)
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

    def test_trace_and_explain_return_claim_grounding(self) -> None:
        graph = load(BASIC)
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
        graph = load(BASIC)
        result = graph.observe()
        self.assert_query_contract(graph, result, "observe")
        self.assertNotIn("gate", result)
        self.assertNotIn("enforce", json.dumps(result).lower())

    def test_named_predicate_uses_exact_base_iri_containing_graph_segment(self) -> None:
        base_iri = "https://kg.example.invalid/root/graph/profile"
        graph = load(BASIC, base_iri=base_iri)
        source = "product.current:REQ-001@1#CLM-REQ-001-01"
        explicit = graph.neighbors(
            source,
            direction="out",
            predicate=base_iri + "/vocab/hasAcceptanceCriterion",
        )
        named = graph.neighbors(source, direction="out", predicate="HAS_AC")

        self.assertEqual(1, len(explicit["results"]))
        self.assertEqual(explicit["results"], named["results"])
        self.assertEqual(graph.graph_iri, named["graph_iri"])
        self.assertEqual(graph.graph_input_sha256, named["graph_input_sha256"])


class TestMatchContract(unittest.TestCase):
    def assert_match_contract(
        self,
        receipt: dict,
        *,
        match_state: str,
        ambiguity_state: str,
    ) -> None:
        self.assertEqual(len(receipt["results"]), receipt["match_count"])
        self.assertEqual(match_state, receipt["match_state"])
        self.assertEqual(ambiguity_state, receipt["ambiguity_state"])
        for result in receipt["results"]:
            self.assertIn("result_kind", result)

    def _two_claim_graph(self, tmp: str):
        root = Path(tmp)
        (root / "knowledge-map.md").write_text(
            active_map(("SOURCE", "source.md")), encoding="utf-8"
        )
        (root / "source.md").write_text(
            document("SOURCE", "### CLM-A\n\nFirst.\n\n### CLM-B\n\nSecond."),
            encoding="utf-8",
        )
        return load(root)

    def test_every_query_receipt_has_explicit_match_and_ambiguity_state(self) -> None:
        graph = load(BASIC)
        source = "product.current:REQ-001@1#CLM-REQ-001-01"
        cases = (
            (graph.observe(), "not_applicable", "not_applicable"),
            (graph.resolve("product.current:MISSING@1"), "none", "unambiguous"),
            (graph.resolve(source), "unique", "unambiguous"),
            (graph.search("grounded answer"), "unique", "not_applicable"),
            (
                graph.neighbors(source, direction="out", predicate="HAS_AC"),
                "unique",
                "not_applicable",
            ),
            (graph.trace(source, max_depth=1), "unique", "not_applicable"),
            (graph.explain(source), "unique", "unambiguous"),
            (graph.lookup(source), "unique", "unambiguous"),
        )
        for receipt, match_state, ambiguity_state in cases:
            with self.subTest(query_kind=receipt["query_kind"]):
                self.assert_match_contract(
                    receipt,
                    match_state=match_state,
                    ambiguity_state=ambiguity_state,
                )

    def test_document_explain_returns_all_claims_and_marks_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-explain-ambiguity-") as tmp:
            graph = self._two_claim_graph(tmp)

            receipt = graph.explain("product.current:SOURCE@1")

            self.assert_match_contract(
                receipt,
                match_state="multiple",
                ambiguity_state="ambiguous",
            )
            self.assertEqual(
                [
                    "product.current:SOURCE@1#CLM-A",
                    "product.current:SOURCE@1#CLM-B",
                ],
                [item["reference"] for item in receipt["results"]],
            )

    def test_truncated_explain_preserves_total_match_and_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-explain-truncated-") as tmp:
            graph = self._two_claim_graph(tmp)

            receipt = graph.explain("product.current:SOURCE@1", limit=1)

            self.assertTrue(receipt["truncated"])
            self.assertEqual(1, len(receipt["results"]))
            self.assertEqual(2, receipt["match_count"])
            self.assertEqual("multiple", receipt["match_state"])
            self.assertEqual("ambiguous", receipt["ambiguity_state"])

    def test_neighbors_and_trace_edges_carry_statement_and_source_provenance(self) -> None:
        graph = load(BASIC)
        source = "product.current:REQ-001@1#CLM-REQ-001-01"
        source_claim = graph.resolve(source)["results"][0]
        expected_sha = hashlib.sha256(
            (BASIC / "requirements/source.md").read_bytes()
        ).hexdigest()
        for receipt in (
            graph.neighbors(source, direction="out", predicate="HAS_AC"),
            graph.trace(source, max_depth=1),
        ):
            with self.subTest(query_kind=receipt["query_kind"]):
                edge = receipt["results"][0]
                self.assertEqual("edge", edge["result_kind"])
                self.assertRegex(edge["statement_iri"], r"/statement/")
                self.assertEqual(source, edge["source_ref"])
                self.assertEqual("requirements/source.md", edge["source_path"])
                self.assertEqual(expected_sha, edge["source_sha256"])
                self.assertEqual(
                    source_claim["revision_digest"], edge["revision_digest"]
                )
                self.assertEqual(
                    "product.current:EVD-001@1#CLM-EVD-001-01",
                    edge["evidence_ref"],
                )
                self.assertEqual("evidence/request.md", edge["evidence_path"])


class TestLookup(unittest.TestCase):
    def test_lookup_matches_iri_then_reference_then_text(self) -> None:
        graph = load(BASIC)
        claim_ref = "product.current:REQ-001@1#CLM-REQ-001-01"
        claim = graph.claims[claim_ref]
        document_ref = "product.current:REQ-001@1"
        statement = graph.statements[0]
        cases = (
            (claim["occurrence_iri"], "iri", "claim", [claim_ref]),
            (claim["stable_iri"], "iri", "claim", [claim_ref]),
            (graph.documents[document_ref]["revision_iri"], "iri", "document", [document_ref]),
            (statement["iri"], "iri", "statement", [None]),
            (claim_ref, "reference", "claim", [claim_ref]),
            ("product.current:REQ-001#CLM-REQ-001-01", "reference", "claim", [claim_ref]),
            ("Grounded Answer", "text", "search_hit", [document_ref]),
        )
        for text, mode, kind, references in cases:
            with self.subTest(text=text):
                receipt = graph.lookup(text)
                self.assertEqual("lookup", receipt["query_kind"])
                self.assertEqual(mode, receipt["lookup_mode"])
                self.assertEqual("unique", receipt["match_state"])
                self.assertEqual(
                    [kind], [item["result_kind"] for item in receipt["results"]]
                )
                self.assertEqual(
                    references,
                    [item.get("reference") for item in receipt["results"]],
                )

    def test_lookup_reports_none_and_ambiguity_honestly(self) -> None:
        graph = load(BASIC)
        missing = graph.lookup(BASE_IRI + "/claim/product.current/NOPE")
        self.assertEqual(("none", 0, "iri"), (
            missing["match_state"], missing["match_count"], missing["lookup_mode"]
        ))
        stable = graph.lookup("product.current:REQ-001")
        self.assertEqual("reference", stable["lookup_mode"])
        self.assertEqual("multiple", stable["match_state"])
        self.assertEqual("ambiguous", stable["ambiguity_state"])


if __name__ == "__main__":
    unittest.main()
