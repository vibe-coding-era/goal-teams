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
)


class TestV262KnowledgeGraphAdversarialRound11Indent(unittest.TestCase):
    def test_indented_h2_or_h3_heading_ends_claim_provenance_scope(self) -> None:
        relation = """#### Relations
| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-INDENT` | `SUPPORTS` | `product.current:SOURCE@1#CLM-SOURCE` | [Self](source.md#CLM-SOURCE) | `asserted` | `appendix` | [Self](source.md#CLM-SOURCE) |"""
        for spaces in (1, 2, 3):
            for level in (2, 3):
                heading = " " * spaces + "#" * level + " Appendix"
                with self.subTest(heading=heading), tempfile.TemporaryDirectory(
                    prefix="kg262-claim-indent-scope-"
                ) as tmp:
                    root = Path(tmp)
                    (root / "knowledge-map.md").write_text(
                        _active_map(("SOURCE", "source.md")), encoding="utf-8"
                    )
                    body = (
                        "### CLM-SOURCE\n\nGrounded claim.\n\n"
                        + heading
                        + "\n\nAppendix.\n\n"
                        + relation
                    )
                    (root / "source.md").write_text(
                        _document("SOURCE", body), encoding="utf-8"
                    )

                    graph = _load(root)
                    claim = graph.resolve(
                        "product.current:SOURCE@1#CLM-SOURCE"
                    )["results"][0]

                    self.assertEqual("Grounded claim.", claim["claim_text"])
                    self.assertEqual((), graph.statements)
                    self.assertFalse(
                        any(
                            triple.predicate == BASE_IRI + "/vocab/supports"
                            for triple in graph.triples
                        )
                    )


if __name__ == "__main__":
    unittest.main()
