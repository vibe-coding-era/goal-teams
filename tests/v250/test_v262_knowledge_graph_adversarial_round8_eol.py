from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg
from tests.v250.test_v262_knowledge_graph_adversarial_round7 import (
    _document,
    _load,
    _map_with_body,
    _member_table,
)


class TestV262KnowledgeGraphAdversarialRound8Eol(unittest.TestCase):
    def test_type6_end_of_line_start_masks_every_graph_surface_until_blank(self) -> None:
        surfaces = (
            "## Members",
            "### CLM-HIDDEN",
            "#### Relations",
            "#### Evidence",
        )
        for surface in surfaces:
            with self.subTest(surface=surface):
                lines = ["<div", surface, "", "### CLM-ACTIVE"]
                self.assertEqual(
                    ["", "", "", "### CLM-ACTIVE"],
                    kg._active_markdown_lines(lines),
                )

    def test_type6_end_of_line_start_cannot_select_hidden_members_table(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-html-eol-members-") as tmp:
            root = Path(tmp)
            body = "\n".join(
                (
                    "<div",
                    "## Members",
                    _member_table("HIDDEN", "hidden.md"),
                    "",
                    "## Members",
                    "",
                    _member_table("ACTIVE", "active.md"),
                )
            )
            (root / "knowledge-map.md").write_text(
                _map_with_body(body), encoding="utf-8"
            )
            (root / "hidden.md").write_text(
                _document("HIDDEN", "### CLM-HIDDEN\n\nHidden."),
                encoding="utf-8",
            )
            (root / "active.md").write_text(
                _document("ACTIVE", "### CLM-ACTIVE\n\nActive."),
                encoding="utf-8",
            )

            graph = _load(root)

            self.assertEqual(
                [],
                graph.resolve("product.current:HIDDEN@1#CLM-HIDDEN")["results"],
            )
            self.assertEqual(
                1,
                len(
                    graph.resolve("product.current:ACTIVE@1#CLM-ACTIVE")[
                        "results"
                    ]
                ),
            )


if __name__ == "__main__":
    unittest.main()
