from __future__ import annotations

import unittest

from scripts.v250 import okf_document_graph as kg


class TestV262KnowledgeGraphAdversarialRound12Surface(unittest.TestCase):
    def test_leading_single_line_block_comment_masks_all_graph_surface_suffixes(self) -> None:
        for surface in (
            "## Members",
            "### CLM-FAB",
            "#### Relations",
            "#### Evidence",
        ):
            for spaces in (0, 1, 2, 3):
                line = " " * spaces + "<!-- sample -->" + surface
                with self.subTest(surface=surface, spaces=spaces):
                    self.assertEqual([""], kg._active_markdown_lines([line]))


if __name__ == "__main__":
    unittest.main()
