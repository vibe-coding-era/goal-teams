from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg
from tests.v250.test_v262_knowledge_graph_adversarial_round5 import (
    _load,
    _map_text,
)


class TestV262KnowledgeGraphAdversarialRound10(unittest.TestCase):
    def test_current_rejects_every_replay_shaped_namespace_without_version(self) -> None:
        for namespace in (
            "product.replay",
            "replay",
            "product.x.RePlAy",
        ):
            with self.subTest(namespace=namespace), tempfile.TemporaryDirectory(
                prefix="kg262-current-replay-shaped-"
            ) as tmp:
                root = Path(tmp)
                (root / "knowledge-map.md").write_text(
                    _map_text(namespace=namespace), encoding="utf-8"
                )

                with self.assertRaises(kg.GraphSecurityError) as caught:
                    _load(root)

                self.assertEqual(
                    "E_KG262_GRAPH_ROLE_MISMATCH",
                    caught.exception.code,
                )


if __name__ == "__main__":
    unittest.main()
