from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "c" * 64
PROFILE_SHA256 = "b" * 64
SNAPSHOT_SHA256 = "a" * 64


def _current(root: Path, *, base_iri: str = BASE_IRI):
    return kg.load_current_graph(
        root,
        "knowledge-map.md",
        kg_base_iri=base_iri,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


def _replay(root: Path, replay_version: str):
    return kg.load_replay_graph(
        root,
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
        replay_version=replay_version,
        snapshot_sha256=SNAPSHOT_SHA256,
    )


def _copy_current(parent: Path) -> Path:
    root = parent / "current"
    shutil.copytree(FIXTURES / "current", root)
    return root


def _replace(path: Path, old: str, new: str, *, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"fixture token not found: {old!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


class TestV262KnowledgeGraphAdversarialRound3(unittest.TestCase):
    def test_relations_table_without_assertion_state_column_is_withheld(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-no-assertion-column-") as tmp:
            root = _copy_current(Path(tmp))
            source = root / "requirements/source.md"
            _replace(
                source,
                "| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |",
                "| relation_id | predicate | target_ref | target | qualifier | source_ref |",
            )
            _replace(
                source,
                "| --- | --- | --- | --- | --- | --- | --- |",
                "| --- | --- | --- | --- | --- | --- |",
            )
            _replace(source, "| `asserted` | `declared` |", "| `declared` |")

            graph = _current(root)
            subject = BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1"
            predicate = BASE_IRI + "/vocab/hasAcceptanceCriterion"
            target = BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1"
            self.assertFalse(graph.has_triple(subject, predicate, target))
            self.assertFalse(
                any(
                    item["relation_id"] == "REL-REQ-001-01"
                    for item in graph.statements
                )
            )
            self.assertTrue(
                any(
                    item["rule_id"] == "missing_assertion_state_column"
                    for item in graph.observations
                )
            )

    def test_graph_public_identity_and_triples_are_read_only(self) -> None:
        graph = _current(FIXTURES / "current")
        receipt = graph.to_receipt()
        assignments = {
            "graph_role": "replay",
            "graph_iri": "https://poison.invalid/graph",
            "route_identity": "sha256:" + "0" * 64,
            "acceptance_eligible": False,
            "coverage_state": "partial",
            "persistence_state": "completed",
            "member_paths": ("poison.md",),
            "triples": (),
        }
        for name, value in assignments.items():
            with self.subTest(name=name):
                with self.assertRaises((AttributeError, TypeError)):
                    setattr(graph, name, value)
        with self.assertRaises((AttributeError, TypeError)):
            graph.graph_input_sha256 = "0" * 64
        self.assertEqual(receipt, graph.to_receipt())

    def test_relation_id_is_stable_across_source_revisions_with_distinct_occurrences(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-relation-revisions-") as tmp:
            root = _copy_current(Path(tmp))
            source_v1 = root / "requirements/source.md"
            source_v2 = root / "requirements/source-v2.md"
            source_v2.write_text(
                source_v1.read_text(encoding="utf-8")
                .replace('revision: "1"', 'revision: "2"', 1)
                .replace(
                    "Grounded answers cite Current evidence",
                    "Grounded answers revision two",
                ),
                encoding="utf-8",
            )
            knowledge_map = root / "knowledge-map.md"
            marker = "| `product.current:REQ-001@1` | [Grounded answer requirement](requirements/source.md) | `Knowledge Requirement` | `current` |"
            _replace(
                knowledge_map,
                marker,
                marker
                + "\n| `product.current:REQ-001@2` | [Grounded answer revision two](requirements/source-v2.md) | `Knowledge Requirement` | `current` |",
            )

            graph = _current(root)
            statements = [
                item
                for item in graph.statements
                if item["relation_id"] == "REL-REQ-001-01"
            ]
            self.assertEqual(2, len(statements))
            self.assertEqual(2, len({item["iri"] for item in statements}))
            self.assertEqual(1, len({item["occurrence_of"] for item in statements}))
            self.assertNotIn(
                "duplicate_relation_id",
                {item["rule_id"] for item in graph.observations},
            )
            for revision in ("1", "2"):
                subject = (
                    BASE_IRI
                    + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/"
                    + revision
                )
                self.assertTrue(
                    graph.has_triple(
                        subject,
                        BASE_IRI + "/vocab/hasAcceptanceCriterion",
                        BASE_IRI
                        + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1",
                    )
                )

    def test_illegal_claim_delimiter_is_observed_without_assertion_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-invalid-claim-") as tmp:
            root = _copy_current(Path(tmp))
            source = root / "requirements/source.md"
            _replace(
                source,
                "### CLM-REQ-001-01",
                "### CLM-REQ-001-01#ILLEGAL",
            )
            graph = _current(root)
            self.assertTrue(
                any(
                    item["rule_id"] == "invalid_claim_id"
                    for item in graph.observations
                )
            )
            self.assertNotIn(
                "product.current:REQ-001@1#CLM-REQ-001-01#ILLEGAL",
                graph.resolve(
                    "product.current:REQ-001@1#CLM-REQ-001-01#ILLEGAL"
                )["results"],
            )
            self.assertFalse(
                any("CLM-REQ-001-01%23ILLEGAL" in item.subject for item in graph.triples)
            )

    def test_base_iri_rejects_raw_characters_forbidden_by_iri_syntax(self) -> None:
        for character in ("<", ">", "|", "^", "`", "{", "}"):
            with self.subTest(character=character):
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    _current(
                        FIXTURES / "current",
                        base_iri=f"https://kg.example.invalid/okf{character}bad",
                    )
                self.assertEqual("E_KG262_INVALID_BASE_IRI", caught.exception.code)

    def test_replay_version_must_match_map_and_document_generation_identity(self) -> None:
        with self.assertRaises(kg.GraphSecurityError) as caught:
            _replay(FIXTURES / "replay", "V9.9")
        self.assertEqual("E_KG262_REPLAY_VERSION_MISMATCH", caught.exception.code)

        graph = _replay(FIXTURES / "replay", "V2.6")
        self.assertEqual("V2.6", graph.graph_input["replay_version"])
        self.assertIn("product.replay.v2.6:REQ-OLD-001@1", graph.documents)


if __name__ == "__main__":
    unittest.main()
