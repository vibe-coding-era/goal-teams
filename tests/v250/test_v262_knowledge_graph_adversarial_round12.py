from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg
from tests.v250.test_v262_knowledge_graph_adversarial_round7 import (
    BASE_IRI,
    _active_map,
    _document,
    _load,
    _map_with_body,
    _member_table,
)


class TestV262KnowledgeGraphAdversarialRound12(unittest.TestCase):
    def test_multiline_comment_close_line_cannot_create_members_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-comment-members-") as tmp:
            root = Path(tmp)
            body = "\n".join(
                (
                    "<!--",
                    "-->## Members",
                    _member_table("FABRICATED", "fabricated.md"),
                    "",
                    "## Members",
                    "",
                    _member_table("ACTIVE", "active.md"),
                )
            )
            (root / "knowledge-map.md").write_text(
                _map_with_body(body), encoding="utf-8"
            )
            (root / "fabricated.md").write_text(
                _document("FABRICATED", "### CLM-FAB\n\nFabricated."),
                encoding="utf-8",
            )
            (root / "active.md").write_text(
                _document("ACTIVE", "### CLM-ACTIVE\n\nActive."),
                encoding="utf-8",
            )

            graph = _load(root)

            self.assertNotIn("product.current:FABRICATED@1", graph.documents)
            self.assertIn("product.current:ACTIVE@1", graph.documents)

    def test_multiline_comment_close_line_cannot_create_claim_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-comment-claim-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            body = "\n".join(
                (
                    "<!--",
                    "-->### CLM-FAB",
                    "Fabricated claim.",
                    "",
                    "### CLM-ACTIVE",
                    "",
                    "Active claim.",
                )
            )
            (root / "source.md").write_text(
                _document("SOURCE", body), encoding="utf-8"
            )

            graph = _load(root)

            self.assertEqual(
                [],
                graph.resolve("product.current:SOURCE@1#CLM-FAB")["results"],
            )
            self.assertEqual(
                1,
                len(
                    graph.resolve("product.current:SOURCE@1#CLM-ACTIVE")[
                        "results"
                    ]
                ),
            )

    def test_multiline_comment_close_line_cannot_create_relations_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-comment-relation-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            relation = """<!--
-->#### Relations
| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-FAB` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `fabricated` | [Self](source.md#CLM-SOURCE) |"""
            (root / "source.md").write_text(
                _document(
                    "SOURCE",
                    "### CLM-SOURCE\n\nActive claim.\n\n" + relation,
                ),
                encoding="utf-8",
            )

            graph = _load(root)

            self.assertEqual((), graph.statements)
            self.assertFalse(
                any(
                    triple.predicate == BASE_IRI + "/vocab/supports"
                    for triple in graph.triples
                )
            )

    def test_multiline_comment_close_line_cannot_create_evidence_heading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-comment-evidence-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _active_map(
                    ("SOURCE", "source.md"),
                    ("EVIDENCE", "evidence.md"),
                ),
                encoding="utf-8",
            )
            evidence = """<!--
-->#### Evidence
- [Fabricated evidence](evidence.md#CLM-EVIDENCE)"""
            (root / "source.md").write_text(
                _document(
                    "SOURCE",
                    "### CLM-SOURCE\n\nActive claim.\n\n" + evidence,
                ),
                encoding="utf-8",
            )
            (root / "evidence.md").write_text(
                _document(
                    "EVIDENCE",
                    "### CLM-EVIDENCE\n\nIndependent evidence.",
                ),
                encoding="utf-8",
            )

            graph = _load(root)
            source = graph.resolve(
                "product.current:SOURCE@1#CLM-SOURCE"
            )["results"][0]

            self.assertEqual([], source["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
