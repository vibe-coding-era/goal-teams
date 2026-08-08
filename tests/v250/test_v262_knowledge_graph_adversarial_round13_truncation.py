from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.v250.test_v262_knowledge_graph_adversarial_round7 import (
    _active_map,
    _document,
    _load,
)


class TestV262KnowledgeGraphAdversarialRound13Truncation(unittest.TestCase):
    def test_truncated_explain_preserves_total_match_and_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-explain-truncated-") as tmp:
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

            receipt = graph.explain("product.current:SOURCE@1", limit=1)

            self.assertTrue(receipt["truncated"])
            self.assertEqual(1, len(receipt["results"]))
            self.assertEqual(2, receipt["match_count"])
            self.assertEqual("multiple", receipt["match_state"])
            self.assertEqual("ambiguous", receipt["ambiguity_state"])


if __name__ == "__main__":
    unittest.main()
