from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg
from tests.v250.test_v262_knowledge_graph_adversarial_round7 import (
    _active_map,
    _document,
    _load,
)


class TestV262KnowledgeGraphAdversarialRound12Inline(unittest.TestCase):
    def test_leading_single_line_html_comment_owns_complete_line(self) -> None:
        for spaces in (0, 1, 2, 3):
            line = " " * spaces + "<!-- sample -->### CLM-FAB"
            with self.subTest(spaces=spaces):
                self.assertEqual([""], kg._active_markdown_lines([line]))

        self.assertEqual(
            ["Active text  remains active."],
            kg._active_markdown_lines(
                ["Active text <!-- inline note --> remains active."]
            ),
        )

    def test_leading_single_line_comment_cannot_create_claim(self) -> None:
        for spaces in (0, 1, 2, 3):
            with self.subTest(spaces=spaces), tempfile.TemporaryDirectory(
                prefix="kg262-leading-comment-claim-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _active_map(("SOURCE", "source.md")), encoding="utf-8"
                )
                body = (
                    " " * spaces
                    + "<!-- sample -->### CLM-FAB\nFabricated.\n\n"
                    + "### CLM-ACTIVE\n\nActive."
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


if __name__ == "__main__":
    unittest.main()
