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


HTML_BLOCK_STARTS = (
    "<div>",
    '<x-probe data-mode="review">',
)


class TestV262KnowledgeGraphAdversarialRound8(unittest.TestCase):
    def test_blank_line_ends_html_block_before_active_members_table(self) -> None:
        for ordinal, start in enumerate(HTML_BLOCK_STARTS, start=1):
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="kg262-html-blank-members-"
            ) as tmp:
                root = Path(tmp)
                knowledge_id = f"ACTIVE-{ordinal}"
                path = f"active-{ordinal}.md"
                (root / "knowledge-map.md").write_text(
                    _map_with_body(
                        "## Members\n\n"
                        + start
                        + "\n\n"
                        + _member_table(knowledge_id, path)
                    ),
                    encoding="utf-8",
                )
                (root / path).write_text(
                    _document(
                        knowledge_id,
                        "### CLM-ACTIVE\n\nThis claim is active.",
                    ),
                    encoding="utf-8",
                )

                graph = _load(root)

                self.assertIn(
                    f"product.current:{knowledge_id}@1",
                    graph.documents,
                )

    def test_blank_line_ends_html_block_before_active_claim(self) -> None:
        for start in HTML_BLOCK_STARTS:
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="kg262-html-blank-claim-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(("SOURCE", "source.md")),
                    encoding="utf-8",
                )
                (root / "source.md").write_text(
                    _document(
                        "SOURCE",
                        start
                        + "\n\n### CLM-ACTIVE\n\nThis claim follows the block.",
                    ),
                    encoding="utf-8",
                )

                graph = _load(root)

                self.assertEqual(
                    1,
                    len(
                        graph.resolve(
                            "product.current:SOURCE@1#CLM-ACTIVE"
                        )["results"]
                    ),
                )

    def test_blank_line_ends_html_block_before_active_relation(self) -> None:
        relation = """#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-ACTIVE` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `active` | [Self](source.md#CLM-SOURCE) |"""
        for start in HTML_BLOCK_STARTS:
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="kg262-html-blank-relation-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(("SOURCE", "source.md")),
                    encoding="utf-8",
                )
                (root / "source.md").write_text(
                    _document(
                        "SOURCE",
                        "### CLM-SOURCE\n\nAn active claim.\n\n"
                        + start
                        + "\n\n"
                        + relation,
                    ),
                    encoding="utf-8",
                )

                graph = _load(root)

                self.assertEqual(1, len(graph.statements))
                self.assertTrue(
                    any(
                        triple.predicate == BASE_IRI + "/vocab/supports"
                        for triple in graph.triples
                    )
                )

    def test_blank_line_ends_html_block_before_active_evidence(self) -> None:
        evidence = """#### Evidence

- [Active evidence](evidence.md#CLM-EVIDENCE)"""
        for start in HTML_BLOCK_STARTS:
            with self.subTest(start=start), tempfile.TemporaryDirectory(
                prefix="kg262-html-blank-evidence-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(
                        ("SOURCE", "source.md"),
                        ("EVIDENCE", "evidence.md"),
                    ),
                    encoding="utf-8",
                )
                (root / "source.md").write_text(
                    _document(
                        "SOURCE",
                        "### CLM-SOURCE\n\nAn active claim.\n\n"
                        + start
                        + "\n\n"
                        + evidence,
                    ),
                    encoding="utf-8",
                )
                (root / "evidence.md").write_text(
                    _document(
                        "EVIDENCE",
                        "### CLM-EVIDENCE\n\nActive evidence.",
                    ),
                    encoding="utf-8",
                )

                graph = _load(root)
                source = graph.resolve(
                    "product.current:SOURCE@1#CLM-SOURCE"
                )["results"][0]
                evidence_claim = graph.resolve(
                    "product.current:EVIDENCE@1#CLM-EVIDENCE"
                )["results"][0]

                self.assertEqual(
                    ["product.current:EVIDENCE@1#CLM-EVIDENCE"],
                    source["evidence_refs"],
                )
                self.assertTrue(
                    graph.has_triple(
                        source["occurrence_iri"],
                        kg.DCTERMS + "references",
                        evidence_claim["occurrence_iri"],
                    )
                )


if __name__ == "__main__":
    unittest.main()
