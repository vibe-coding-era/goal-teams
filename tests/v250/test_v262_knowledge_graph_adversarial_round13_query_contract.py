from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg
from tests.v250.test_v262_knowledge_graph_adversarial_round7 import (
    _active_map,
    _document,
    _load,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262" / "current"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "5" * 64
PROFILE_SHA256 = "6" * 64


def _fixture_graph():
    return kg.load_current_graph(
        FIXTURES,
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


class TestV262KnowledgeGraphAdversarialRound13QueryContract(unittest.TestCase):
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

    def test_every_query_receipt_has_explicit_match_and_ambiguity_state(self) -> None:
        graph = _fixture_graph()
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
        )
        for receipt, match_state, ambiguity_state in cases:
            with self.subTest(query_kind=receipt["query_kind"]):
                self.assert_match_contract(
                    receipt,
                    match_state=match_state,
                    ambiguity_state=ambiguity_state,
                )

    def test_document_explain_returns_all_claims_and_marks_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-explain-ambiguity-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            (root / "source.md").write_text(
                _document(
                    "SOURCE",
                    "### CLM-A\n\nFirst.\n\n### CLM-B\n\nSecond.",
                ),
                encoding="utf-8",
            )
            graph = _load(root)

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

    def test_neighbors_and_trace_edges_carry_statement_and_source_provenance(self) -> None:
        graph = _fixture_graph()
        source = "product.current:REQ-001@1#CLM-REQ-001-01"
        source_claim = graph.resolve(source)["results"][0]
        expected_sha = hashlib.sha256(
            (FIXTURES / "requirements/source.md").read_bytes()
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

    def test_schema_requires_query_match_contract_and_result_kind(self) -> None:
        schema = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "schemas/v2.50/okf-document-graph.schema.json"
            ).read_text(encoding="utf-8")
        )
        query = schema["$defs"]["query_receipt"]
        self.assertTrue(
            {"match_state", "match_count", "ambiguity_state"}.issubset(
                query["required"]
            )
        )
        self.assertEqual(
            {"none", "unique", "multiple", "not_applicable"},
            set(query["properties"]["match_state"]["enum"]),
        )
        self.assertEqual(
            {"unambiguous", "ambiguous", "not_applicable"},
            set(query["properties"]["ambiguity_state"]["enum"]),
        )
        self.assertIn("query_result", schema["$defs"])
        self.assertEqual(
            {"$ref": "#/$defs/query_result"},
            query["properties"]["results"]["items"],
        )


if __name__ == "__main__":
    unittest.main()
