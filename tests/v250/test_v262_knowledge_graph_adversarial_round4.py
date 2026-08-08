from __future__ import annotations

import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262" / "current"
ROUTE_IDENTITY = "sha256:" + "9" * 64
PROFILE_SHA256 = "8" * 64


def _load(base_iri: str):
    return kg.load_current_graph(
        FIXTURES,
        "knowledge-map.md",
        kg_base_iri=base_iri,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


class TestV262KnowledgeGraphAdversarialRound4(unittest.TestCase):
    def test_raw_square_brackets_are_forbidden_in_base_iri_path(self) -> None:
        for suffix in ("[left", "right]", "[balanced]"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    _load("https://kg.example.invalid/okf/" + suffix)
                self.assertEqual("E_KG262_INVALID_BASE_IRI", caught.exception.code)

    def test_rfc3986_path_pchar_delimiters_remain_legal(self) -> None:
        graph = _load("https://kg.example.invalid/okf/:@!$&'()*+,;=")
        self.assertTrue(graph.graph_iri.startswith("https://kg.example.invalid/okf/"))


if __name__ == "__main__":
    unittest.main()
