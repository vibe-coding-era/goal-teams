"""Identity and linking: exact anchors, duplicates, NFC collisions, relation lineage."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from okf_graph import graph as kg
from tests.helpers import BASE_IRI, BASIC, copy_basic, load, replace_text


SOURCE_IRI = BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1"
TARGET_IRI = BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1"
HAS_AC = BASE_IRI + "/vocab/hasAcceptanceCriterion"


def _document(*, namespace: str, knowledge_id: str, claim_id: str, title: str) -> str:
    return f"""---
type: Knowledge Note
title: {title}
description: Adversarial identity fixture.
timestamp: 2026-08-07T23:30:00+08:00
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: {namespace}
knowledge_id: {knowledge_id}
revision: "1"
owner: adversarial-owner
lifecycle: current
modality: note
epistemic_state: documented
sensitivity: internal
---

# {title}

### {claim_id}

{title} claim text.
"""


def _map_document(rows: list) -> str:
    rendered = "\n".join(
        f"| `{reference}` | [{reference}]({path}) | `Knowledge Note` | `current` |"
        for reference, path in rows
    )
    return f"""---
type: Knowledge Map
title: Adversarial map
description: Exact adversarial map closure.
timestamp: 2026-08-07T23:29:00+08:00
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: product.current
knowledge_id: MAP-ADVERSARIAL
revision: "1"
owner: adversarial-owner
lifecycle: current
modality: collection-map
epistemic_state: documented
sensitivity: internal
---

# Adversarial map

## Members

| member_ref | path | member_kind | lifecycle |
| --- | --- | --- | --- |
{rendered}
"""


class TestLinks(unittest.TestCase):
    def test_unknown_or_unsupported_neighbor_predicate_never_disables_filter(self) -> None:
        graph = load(BASIC)
        reference = "product.current:REQ-001@1#CLM-REQ-001-01"
        for predicate in ("UNKNOWN_PREDICATE", "RELATED_TO"):
            with self.subTest(predicate=predicate):
                try:
                    receipt = graph.neighbors(reference, direction="out", predicate=predicate)
                except kg.GraphSecurityError:
                    continue
                self.assertEqual([], receipt["results"])

    def test_target_link_fragment_must_match_target_ref_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-target-fragment-") as tmp:
            root = copy_basic(Path(tmp))
            replace_text(
                root / "requirements/source.md",
                "../acceptance/target.md#CLM-AC-001-01",
                "../acceptance/target.md#CLM-WRONG-ANCHOR",
            )
            graph = load(root)
            self.assertFalse(graph.has_triple(SOURCE_IRI, HAS_AC, TARGET_IRI))
            findings = [
                item
                for item in graph.observations
                if item["rule_id"] == "dangling_or_mismatched_target"
            ]
            self.assertTrue(findings)
            self.assertIn("CLM-WRONG-ANCHOR", json.dumps(findings))

    def test_evidence_anchor_must_resolve_exact_claim_without_path_guess(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-evidence-anchor-") as tmp:
            root = copy_basic(Path(tmp))
            replace_text(
                root / "requirements/source.md",
                "../evidence/request.md#CLM-EVD-001-01",
                "../evidence/request.md#CLM-EVD-MISSING",
                count=2,
            )
            graph = load(root)
            reference = "product.current:REQ-001@1#CLM-REQ-001-01"
            explained = graph.explain(reference)["results"][0]
            self.assertEqual([], explained["evidence_refs"])
            findings = [
                item
                for item in graph.observations
                if item["rule_id"] == "dangling_or_mismatched_evidence"
            ]
            self.assertTrue(findings)
            self.assertIn("CLM-EVD-MISSING", json.dumps(findings))


class TestDuplicates(unittest.TestCase):
    def test_duplicate_document_revision_identity_is_observed_and_first_wins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-duplicate-doc-") as tmp:
            root = copy_basic(Path(tmp))
            (root / "zzz-duplicate.md").write_text(
                (root / "requirements/source.md")
                .read_text(encoding="utf-8")
                .replace(
                    "Grounded answers cite Current evidence",
                    "DUPLICATE REVISION MUST NOT WIN",
                ),
                encoding="utf-8",
            )
            evidence_row = (
                "| `product.current:EVD-001@1` | [User evidence](evidence/request.md)"
                " | `Knowledge Evidence` | `current` |"
            )
            replace_text(
                root / "knowledge-map.md",
                evidence_row,
                evidence_row
                + "\n| `product.current:REQ-001@1` | [Duplicate revision](zzz-duplicate.md)"
                " | `Knowledge Requirement` | `current` |",
            )
            graph = load(root)
            reference = "product.current:REQ-001@1"
            self.assertEqual("requirements/source.md", graph.documents[reference]["path"])
            self.assertTrue(
                any(
                    item["rule_id"] == "duplicate_document_revision_identity"
                    for item in graph.observations
                )
            )

    def test_duplicate_relation_id_cannot_reuse_one_statement_for_two_spo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-duplicate-relation-") as tmp:
            root = copy_basic(Path(tmp))
            existing = "| `REL-REQ-001-01` | `HAS_AC` | `product.current:AC-001@1#CLM-AC-001-01` | [Citation AC](../acceptance/target.md#CLM-AC-001-01) | `asserted` | `declared` | [User evidence](../evidence/request.md#CLM-EVD-001-01) |"
            duplicate = "| `REL-REQ-001-01` | `SUPPORTS` | `product.current:EVD-001@1#CLM-EVD-001-01` | [Evidence target](../evidence/request.md#CLM-EVD-001-01) | `asserted` | `declared` | [User evidence](../evidence/request.md#CLM-EVD-001-01) |"
            replace_text(root / "requirements/source.md", existing, existing + "\n" + duplicate)
            graph = load(root)
            statements = [
                item for item in graph.statements if item["relation_id"] == "REL-REQ-001-01"
            ]
            self.assertEqual(1, len(statements))
            self.assertTrue(
                any(item["rule_id"] == "duplicate_relation_id" for item in graph.observations)
            )
            evidence_iri = BASE_IRI + "/claim/product.current/EVD-001/CLM-EVD-001-01/revision/1"
            self.assertFalse(
                graph.has_triple(SOURCE_IRI, BASE_IRI + "/vocab/supports", evidence_iri)
            )

    def test_unicode_nfc_identity_collision_is_observed_without_shared_iri(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-nfc-collision-") as tmp:
            root = Path(tmp) / "basic"
            root.mkdir()
            first_id = "CAFé"
            second_id = "CAFé"
            first_ref = f"product.current:{first_id}@1"
            second_ref = f"product.current:{second_id}@1"
            (root / "first.md").write_text(
                _document(
                    namespace="product.current",
                    knowledge_id=first_id,
                    claim_id="CLM-FIRST",
                    title="First NFC identity",
                ),
                encoding="utf-8",
            )
            (root / "second.md").write_text(
                _document(
                    namespace="product.current",
                    knowledge_id=second_id,
                    claim_id="CLM-SECOND",
                    title="Second raw identity",
                ),
                encoding="utf-8",
            )
            (root / "knowledge-map.md").write_text(
                _map_document([(first_ref, "first.md"), (second_ref, "second.md")]),
                encoding="utf-8",
            )
            graph = load(root)
            self.assertTrue(
                any(item["rule_id"] == "identity_nfc_collision" for item in graph.observations)
            )
            revision_iris = [
                graph.documents[reference]["revision_iri"]
                for reference in (first_ref, second_ref)
                if reference in graph.documents
            ]
            self.assertEqual(len(revision_iris), len(set(revision_iris)))


class TestRelationLineage(unittest.TestCase):
    def test_relation_id_is_stable_across_source_revisions_with_distinct_occurrences(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-relation-revisions-") as tmp:
            root = copy_basic(Path(tmp))
            source_v1 = root / "requirements/source.md"
            (root / "requirements/source-v2.md").write_text(
                source_v1.read_text(encoding="utf-8")
                .replace('revision: "1"', 'revision: "2"', 1)
                .replace(
                    "Grounded answers cite Current evidence",
                    "Grounded answers revision two",
                ),
                encoding="utf-8",
            )
            marker = "| `product.current:REQ-001@1` | [Grounded answer requirement](requirements/source.md) | `Knowledge Requirement` | `current` |"
            replace_text(
                root / "knowledge-map.md",
                marker,
                marker
                + "\n| `product.current:REQ-001@2` | [Grounded answer revision two](requirements/source-v2.md) | `Knowledge Requirement` | `current` |",
            )

            graph = load(root)
            statements = [
                item for item in graph.statements if item["relation_id"] == "REL-REQ-001-01"
            ]
            self.assertEqual(2, len(statements))
            self.assertEqual(2, len({item["iri"] for item in statements}))
            self.assertEqual(1, len({item["occurrence_of"] for item in statements}))
            self.assertNotIn(
                "duplicate_relation_id", {item["rule_id"] for item in graph.observations}
            )
            for revision in ("1", "2"):
                subject = (
                    BASE_IRI
                    + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/"
                    + revision
                )
                self.assertTrue(graph.has_triple(subject, HAS_AC, TARGET_IRI))

    def test_illegal_claim_delimiter_is_observed_without_assertion_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-invalid-claim-") as tmp:
            root = copy_basic(Path(tmp))
            replace_text(
                root / "requirements/source.md",
                "### CLM-REQ-001-01",
                "### CLM-REQ-001-01#ILLEGAL",
            )
            graph = load(root)
            self.assertTrue(
                any(item["rule_id"] == "invalid_claim_id" for item in graph.observations)
            )
            self.assertNotIn(
                "product.current:REQ-001@1#CLM-REQ-001-01#ILLEGAL",
                graph.resolve("product.current:REQ-001@1#CLM-REQ-001-01#ILLEGAL")["results"],
            )
            self.assertFalse(
                any("CLM-REQ-001-01%23ILLEGAL" in item.subject for item in graph.triples)
            )


if __name__ == "__main__":
    unittest.main()
