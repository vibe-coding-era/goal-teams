from __future__ import annotations

import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262" / "current"
BASE_IRI = "https://kg.example.invalid/root/graph/profile"
ROUTE_IDENTITY = "sha256:" + "9" * 64
PROFILE_SHA256 = "a" * 64


class TestV262KnowledgeGraphAdversarialRound9(unittest.TestCase):
    def test_named_predicate_uses_exact_base_iri_containing_graph_segment(self) -> None:
        graph = kg.load_current_graph(
            FIXTURES,
            "knowledge-map.md",
            kg_base_iri=BASE_IRI,
            route_identity=ROUTE_IDENTITY,
            profile_document_sha256=PROFILE_SHA256,
        )
        source = "product.current:REQ-001@1#CLM-REQ-001-01"
        explicit = graph.neighbors(
            source,
            direction="out",
            predicate=BASE_IRI + "/vocab/hasAcceptanceCriterion",
        )
        named = graph.neighbors(
            source,
            direction="out",
            predicate="HAS_AC",
        )

        self.assertEqual(1, len(explicit["results"]))
        self.assertEqual(explicit["results"], named["results"])
        self.assertEqual(graph.graph_iri, named["graph_iri"])
        self.assertEqual(graph.graph_input_sha256, named["graph_input_sha256"])


if __name__ == "__main__":
    unittest.main()
