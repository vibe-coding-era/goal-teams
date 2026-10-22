"""Observe-only quality findings: recorded, never gating, never fabricated."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from okf_graph import graph as kg
from tests.helpers import (
    BASE_IRI,
    FIXTURES,
    active_map,
    copy_basic,
    document,
    load,
    replace_text,
)


CONTROLLED_PREDICATES = {
    BASE_IRI + "/vocab/modality",
    BASE_IRI + "/vocab/epistemicState",
    BASE_IRI + "/vocab/sensitivity",
}


class TestQualityFixture(unittest.TestCase):
    def test_quality_findings_are_complete_observations_not_business_gates(self) -> None:
        graph = load(FIXTURES / "quality")

        self.assertEqual("partial", graph.coverage_state)
        self.assertIsInstance(graph.observations, tuple)
        rules = {item["rule_id"] for item in graph.observations}
        self.assertTrue(
            {
                "duplicate_map_member",
                "member_identity_mismatch",
                "invalid_timestamp",
                "dangling_or_mismatched_target",
                "conflict_candidate",
            }.issubset(rules),
            rules,
        )
        for observation in graph.observations:
            self.assertEqual("record", observation["current_action"])
            self.assertEqual("undecided", observation["future_action"])
            self.assertIn("finding_id", observation)
            self.assertIn("observation_state", observation)
            self.assertNotIn("gate_status", observation)
            self.assertNotIn("enforce", json.dumps(observation).lower())

    def test_dangling_row_is_not_fabricated_as_a_direct_or_reified_statement(self) -> None:
        graph = load(FIXTURES / "quality")
        rendered_triples = json.dumps(
            [
                {
                    "subject": item.subject,
                    "predicate": item.predicate,
                    "object": item.object,
                }
                for item in graph.triples
            ]
        )
        rendered_statements = json.dumps(graph.statements)
        self.assertNotIn("AC-MISSING", rendered_triples)
        self.assertNotIn("REL-BROKEN-001", rendered_statements)

        unresolved = [
            item
            for item in graph.observations
            if item["rule_id"] == "dangling_or_mismatched_target"
        ]
        self.assertTrue(unresolved)
        self.assertIn("AC-MISSING", json.dumps(unresolved))

    def test_observe_returns_findings_even_though_shacl_engine_is_not_claimed(self) -> None:
        graph = load(FIXTURES / "quality")
        receipt = graph.observe()
        self.assertEqual("completed", receipt["run_status"])
        self.assertEqual("record", receipt["current_action"])
        self.assertEqual("not_run", receipt["persistence"])
        self.assertEqual("not_implemented", graph.capabilities["shacl_engine_state"])
        self.assertNotIn("shacl_conforms", receipt)
        for result in receipt["results"]:
            if result.get("validation_state") == "nonconforms":
                self.assertEqual("record", result["current_action"])
                self.assertNotEqual("failed", result.get("run_status"))


class TestAssertionState(unittest.TestCase):
    SUBJECT = BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1"
    PREDICATE = BASE_IRI + "/vocab/hasAcceptanceCriterion"
    TARGET = BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1"

    def test_empty_assertion_state_is_observed_and_not_asserted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-empty-assertion-") as tmp:
            root = copy_basic(Path(tmp))
            replace_text(root / "requirements/source.md", "| `asserted` |", "|  |")
            graph = load(root)
            self.assertFalse(graph.has_triple(self.SUBJECT, self.PREDICATE, self.TARGET))
            self.assertFalse(
                any(item["relation_id"] == "REL-REQ-001-01" for item in graph.statements)
            )
            self.assertTrue(
                any(
                    item["rule_id"] == "missing_assertion_state"
                    for item in graph.observations
                )
            )

    def test_relations_table_without_assertion_state_column_is_withheld(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-no-assertion-column-") as tmp:
            root = copy_basic(Path(tmp))
            source = root / "requirements/source.md"
            replace_text(
                source,
                "| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |",
                "| relation_id | predicate | target_ref | target | qualifier | source_ref |",
            )
            replace_text(
                source,
                "| --- | --- | --- | --- | --- | --- | --- |",
                "| --- | --- | --- | --- | --- | --- |",
            )
            replace_text(source, "| `asserted` | `declared` |", "| `declared` |")

            graph = load(root)
            self.assertFalse(graph.has_triple(self.SUBJECT, self.PREDICATE, self.TARGET))
            self.assertFalse(
                any(item["relation_id"] == "REL-REQ-001-01" for item in graph.statements)
            )
            self.assertTrue(
                any(
                    item["rule_id"] == "missing_assertion_state_column"
                    for item in graph.observations
                )
            )


class TestMetadata(unittest.TestCase):
    def _graph_with_document(self, text: str):
        directory = tempfile.TemporaryDirectory(prefix="okfg-metadata-")
        root = Path(directory.name)
        (root / "knowledge-map.md").write_text(
            active_map(("SOURCE", "source.md")), encoding="utf-8"
        )
        (root / "source.md").write_text(text, encoding="utf-8")
        return directory, load(root)

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
                text = document("SOURCE", "### CLM-SOURCE\n\nClaim.").replace(
                    "2026-08-08T02:00:00+08:00", value
                )
                directory, graph = self._graph_with_document(text)
                try:
                    revision = graph.documents["product.current:SOURCE@1"]["revision_iri"]
                    self.assertFalse(
                        any(
                            triple.subject == revision
                            and triple.predicate == kg.DCTERMS + "modified"
                            for triple in graph.triples
                        )
                    )
                    self.assertTrue(
                        graph.has_triple(revision, BASE_IRI + "/vocab/timestampText", value)
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
        text = document("SOURCE", "### CLM-SOURCE\n\nClaim.")
        for line in (
            "modality: note\n",
            "epistemic_state: documented\n",
            "sensitivity: internal\n",
        ):
            text = text.replace(line, "")
        directory, graph = self._graph_with_document(text)
        try:
            revision = graph.documents["product.current:SOURCE@1"]["revision_iri"]
            self.assertFalse(
                any(
                    triple.subject == revision
                    and triple.predicate in CONTROLLED_PREDICATES
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

    def test_whitespace_and_markup_empty_metadata_are_withheld_consistently(self) -> None:
        text = document("SOURCE", "### CLM-SOURCE\n\nClaim.")
        text = text.replace("modality: note", 'modality: "   "')
        text = text.replace("epistemic_state: documented", "epistemic_state: '   '")
        text = text.replace("sensitivity: internal", "sensitivity: ``")
        text = text.replace("lifecycle: current", 'lifecycle: " current "')
        directory, graph = self._graph_with_document(text)
        try:
            document_record = graph.documents["product.current:SOURCE@1"]
            revision = document_record["revision_iri"]

            self.assertEqual("", document_record["modality"])
            self.assertEqual("", document_record["epistemic_state"])
            self.assertEqual("", document_record["sensitivity"])
            self.assertEqual("current", document_record["lifecycle"])
            self.assertFalse(
                any(
                    triple.subject == revision
                    and triple.predicate in CONTROLLED_PREDICATES
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
        finally:
            directory.cleanup()

    def test_non_string_controlled_metadata_is_missing_not_stringified(self) -> None:
        text = document("SOURCE", "### CLM-SOURCE\n\nClaim.")
        text = text.replace("modality: note", "modality: null")
        text = text.replace("epistemic_state: documented", "epistemic_state: false")
        text = text.replace("sensitivity: internal", "sensitivity: []")
        directory, graph = self._graph_with_document(text)
        try:
            document_record = graph.documents["product.current:SOURCE@1"]
            revision = document_record["revision_iri"]

            self.assertEqual("", document_record["modality"])
            self.assertEqual("", document_record["epistemic_state"])
            self.assertEqual("", document_record["sensitivity"])
            self.assertFalse(
                any(
                    triple.subject == revision
                    and triple.predicate in CONTROLLED_PREDICATES
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
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
