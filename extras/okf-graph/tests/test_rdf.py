"""RDF projection: pinned Unicode 17 NFC, IRI minting and reification."""

from __future__ import annotations

import hashlib
import unittest

from okf_graph import graph as kg
from tests.helpers import BASE_IRI, BASIC, FIXTURES, load


NORMALIZATION_TEST_SHA256 = (
    "5019ffd530751a741900c849c0e010332f142a3612234639bd200b82138a87db"
)


class TestRdf(unittest.TestCase):
    def test_unicode_17_normalization_conformance_has_100170_nfc_assertions(self) -> None:
        source = FIXTURES / "unicode17" / "NormalizationTest.txt"
        self.assertEqual(
            NORMALIZATION_TEST_SHA256,
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )

        assertion_count = 0
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            payload = line.split("#", 1)[0].strip()
            if not payload or payload.startswith("@"):
                continue
            fields = [item.strip() for item in payload.split(";")[:5]]
            self.assertEqual(5, len(fields), f"line={line_number}")
            c1, c2, c3, c4, c5 = (
                "".join(chr(int(codepoint, 16)) for codepoint in field.split())
                for field in fields
            )
            for source_text, expected in (
                (c1, c2),
                (c2, c2),
                (c3, c2),
                (c4, c4),
                (c5, c4),
            ):
                self.assertEqual(
                    expected,
                    kg.normalize_nfc17(source_text),
                    f"NormalizationTest.txt:{line_number}",
                )
                assertion_count += 1

        self.assertEqual(100170, assertion_count)

    def test_pct_segment_is_unicode17_nfc_and_rfc3986_byte_exact(self) -> None:
        self.assertEqual("%2E", kg.pct_segment("."))
        self.assertEqual("%2E%2E", kg.pct_segment(".."))
        self.assertEqual("A%20z%2F%25%3F%23%3A.~", kg.pct_segment("A z/%?#:.~"))
        self.assertEqual("%C3%A9", kg.pct_segment("é"))
        self.assertEqual(kg.pct_segment("é"), kg.pct_segment("é"))

        with self.assertRaises(kg.GraphSecurityError) as caught:
            kg.pct_segment("͸")
        self.assertEqual("E_KG262_UNICODE_UNASSIGNED", caught.exception.code)

    def test_asserted_relation_emits_direct_triple_and_distinct_reification(self) -> None:
        graph = load(BASIC)
        source = (
            BASE_IRI
            + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1"
        )
        predicate = BASE_IRI + "/vocab/hasAcceptanceCriterion"
        target = BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1"
        relation = BASE_IRI + "/relation/product.current/REL-REQ-001-01"
        occurrence = (
            BASE_IRI
            + "/statement/product.current/REL-REQ-001-01/source/REQ-001/1/CLM-REQ-001-01"
        )

        self.assertTrue(graph.has_triple(source, predicate, target))
        self.assertIsInstance(graph.triples, tuple)
        direct = [
            triple
            for triple in graph.triples
            if (triple.subject, triple.predicate, triple.object)
            == (source, predicate, target)
        ]
        self.assertEqual(1, len(direct))
        self.assertEqual("iri", direct[0].object_kind)

        self.assertIsInstance(graph.statements, tuple)
        statements = [item for item in graph.statements if item["iri"] == occurrence]
        self.assertEqual(1, len(statements))
        statement = statements[0]
        self.assertEqual(source, statement["subject"])
        self.assertEqual(predicate, statement["predicate"])
        self.assertEqual(target, statement["object"])
        self.assertEqual(relation, statement["occurrence_of"])
        self.assertEqual("asserted", statement["assertion_state"])
        self.assertNotEqual(relation, occurrence)

    def test_graph_exposes_the_frozen_transient_rdf_capability_contract(self) -> None:
        graph = load(BASIC)
        self.assertEqual(
            {
                "rdf_view": "implemented",
                "sparql_state": "not_implemented",
                "shacl_engine_state": "not_implemented",
                "rdfs_owl_reasoning_state": "not_implemented",
            },
            graph.capabilities,
        )
        self.assertEqual("not_run", graph.persistence_state)
        self.assertIsInstance(graph.documents, dict)
        self.assertIn("product.current:REQ-001@1", graph.documents)


if __name__ == "__main__":
    unittest.main()
