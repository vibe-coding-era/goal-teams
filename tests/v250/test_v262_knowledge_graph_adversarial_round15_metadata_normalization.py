from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.v250.test_v262_knowledge_graph_adversarial_round7 import (
    BASE_IRI,
    _active_map,
    _document,
    _load,
)


class TestV262KnowledgeGraphAdversarialRound15MetadataNormalization(
    unittest.TestCase
):
    def test_whitespace_and_markup_empty_metadata_are_withheld_consistently(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-empty-metadata-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            text = _document("SOURCE", "### CLM-SOURCE\n\nClaim.")
            text = text.replace("modality: note", 'modality: "   "')
            text = text.replace(
                "epistemic_state: documented", "epistemic_state: '   '"
            )
            text = text.replace("sensitivity: internal", "sensitivity: ``")
            text = text.replace("lifecycle: current", 'lifecycle: " current "')
            (root / "source.md").write_text(text, encoding="utf-8")

            graph = _load(root)
            document = graph.documents["product.current:SOURCE@1"]
            revision = document["revision_iri"]
            controlled_predicates = {
                BASE_IRI + "/vocab/modality",
                BASE_IRI + "/vocab/epistemicState",
                BASE_IRI + "/vocab/sensitivity",
            }

            self.assertEqual("", document["modality"])
            self.assertEqual("", document["epistemic_state"])
            self.assertEqual("", document["sensitivity"])
            self.assertEqual("current", document["lifecycle"])
            self.assertFalse(
                any(
                    triple.subject == revision
                    and triple.predicate in controlled_predicates
                    for triple in graph.triples
                )
            )
            finding = next(
                item
                for item in graph.observations
                if item["rule_id"] == "missing_recommended_metadata"
            )
            self.assertEqual(
                ["epistemic_state", "modality", "sensitivity"],
                finding["detail"]["fields"],
            )
            self.assertEqual("withheld", finding["detail"]["projection"])
            self.assertTrue(
                graph.has_triple(
                    revision,
                    BASE_IRI + "/vocab/lifecycle",
                    BASE_IRI + "/vocab/current",
                )
            )

    def test_non_string_controlled_metadata_is_missing_not_stringified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-nonstring-metadata-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _active_map(("SOURCE", "source.md")), encoding="utf-8"
            )
            text = _document("SOURCE", "### CLM-SOURCE\n\nClaim.")
            text = text.replace("modality: note", "modality: null")
            text = text.replace(
                "epistemic_state: documented", "epistemic_state: false"
            )
            text = text.replace("sensitivity: internal", "sensitivity: []")
            (root / "source.md").write_text(text, encoding="utf-8")

            graph = _load(root)
            document = graph.documents["product.current:SOURCE@1"]
            revision = document["revision_iri"]
            controlled_predicates = {
                BASE_IRI + "/vocab/modality",
                BASE_IRI + "/vocab/epistemicState",
                BASE_IRI + "/vocab/sensitivity",
            }

            self.assertEqual("", document["modality"])
            self.assertEqual("", document["epistemic_state"])
            self.assertEqual("", document["sensitivity"])
            self.assertFalse(
                any(
                    triple.subject == revision
                    and triple.predicate in controlled_predicates
                    for triple in graph.triples
                )
            )
            finding = next(
                item
                for item in graph.observations
                if item["rule_id"] == "missing_recommended_metadata"
            )
            self.assertEqual(
                ["epistemic_state", "modality", "sensitivity"],
                finding["detail"]["fields"],
            )


if __name__ == "__main__":
    unittest.main()
