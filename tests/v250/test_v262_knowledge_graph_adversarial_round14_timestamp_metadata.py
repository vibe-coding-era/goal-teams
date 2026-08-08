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


class TestV262KnowledgeGraphAdversarialRound14TimestampMetadata(unittest.TestCase):
    def _graph_with_document(self, text: str):
        directory = tempfile.TemporaryDirectory(prefix="kg262-metadata-")
        root = Path(directory.name)
        (root / "knowledge-map.md").write_text(
            _active_map(("SOURCE", "source.md")), encoding="utf-8"
        )
        (root / "source.md").write_text(text, encoding="utf-8")
        return directory, _load(root)

    def test_only_strict_xsd_datetime_stamp_lexical_subset_is_typed(self) -> None:
        invalid = (
            "2026-08-08 12:34:56+08:00",
            "2026-08-08t12:34:56+08:00",
            "2026-08-08T12:34+08:00",
            "2026-W32-6T12:34:56+08:00",
            "2026-08-08T12:34:56+15:00",
            "2026-08-08T12:34:56-23:59",
        )
        for value in invalid:
            with self.subTest(value=value):
                text = _document("SOURCE", "### CLM-SOURCE\n\nClaim.").replace(
                    "2026-08-08T02:00:00+08:00", value
                )
                directory, graph = self._graph_with_document(text)
                try:
                    revision = graph.documents["product.current:SOURCE@1"][
                        "revision_iri"
                    ]
                    self.assertFalse(
                        any(
                            triple.subject == revision
                            and triple.predicate == kg.DCTERMS + "modified"
                            for triple in graph.triples
                        )
                    )
                    self.assertTrue(
                        graph.has_triple(
                            revision,
                            BASE_IRI + "/vocab/timestampText",
                            value,
                        )
                    )
                    self.assertTrue(
                        any(
                            item["rule_id"] == "invalid_timestamp"
                            for item in graph.observations
                        )
                    )
                finally:
                    directory.cleanup()

        for value in (
            "2026-08-08T12:34:56Z",
            "2026-08-08T12:34:56.123+14:00",
            "2026-08-08T12:34:56-14:00",
        ):
            with self.subTest(valid=value):
                self.assertTrue(kg._valid_timestamp(value))

    def test_empty_controlled_metadata_is_observed_and_not_minted_as_vocab_root(self) -> None:
        text = _document("SOURCE", "### CLM-SOURCE\n\nClaim.")
        for line in (
            "modality: note\n",
            "epistemic_state: documented\n",
            "sensitivity: internal\n",
        ):
            text = text.replace(line, "")
        directory, graph = self._graph_with_document(text)
        try:
            revision = graph.documents["product.current:SOURCE@1"]["revision_iri"]
            controlled_predicates = {
                BASE_IRI + "/vocab/modality",
                BASE_IRI + "/vocab/epistemicState",
                BASE_IRI + "/vocab/sensitivity",
            }
            self.assertFalse(
                any(
                    triple.subject == revision
                    and triple.predicate in controlled_predicates
                    for triple in graph.triples
                )
            )
            findings = [
                item
                for item in graph.observations
                if item["rule_id"] == "missing_recommended_metadata"
            ]
            self.assertEqual(1, len(findings))
            self.assertEqual(
                ["epistemic_state", "modality", "sensitivity"],
                findings[0]["detail"]["fields"],
            )
            self.assertEqual("completed", findings[0]["run_status"])
            self.assertEqual("record", findings[0]["current_action"])
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
