from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250 import okf_document_graph as kg


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262" / "current"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "6" * 64
PROFILE_SHA256 = "5" * 64


def _load(root: Path):
    return kg.load_current_graph(
        root,
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


def _map_text(
    *,
    namespace: str = "product.current",
    knowledge_id: str = "MAP-IDENTITY",
    revision: str = "1",
    member_ref: str | None = None,
) -> str:
    member = ""
    if member_ref is not None:
        member = (
            f"| `{member_ref}` | [Invalid identity](invalid.md) | "
            "`Knowledge Note` | `current` |"
        )
    return f"""---
type: Knowledge Map
title: Identity grammar map
description: Exact identity grammar adversarial map.
timestamp: 2026-08-08T00:00:00+08:00
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: {namespace}
knowledge_id: {knowledge_id}
revision: "{revision}"
owner: identity-owner
lifecycle: current
modality: collection-map
epistemic_state: documented
sensitivity: internal
---

# Identity grammar map

## Members

| member_ref | path | member_kind | lifecycle |
| --- | --- | --- | --- |
{member}
"""


def _member_text(
    *, namespace: str, knowledge_id: str, revision: str, reference: str
) -> str:
    return f"""---
type: Knowledge Note
title: Invalid identity component
description: Must remain outside the deterministic RDF projection.
timestamp: 2026-08-08T00:00:01+08:00
okf_version: "0.1"
kg_profile: okf-document-graph-v0.4-rdf-mapping
namespace: {namespace}
knowledge_id: {knowledge_id}
revision: "{revision}"
owner: identity-owner
lifecycle: current
modality: note
epistemic_state: documented
sensitivity: internal
---

# Invalid identity component

### CLM-SELF

An invalid document identity cannot become a relation lineage.

#### Relations

| relation_id | predicate | target_ref | target | assertion_state | qualifier | source_ref |
| --- | --- | --- | --- | --- | --- | --- |
| `REL-SELF` | `SUPPORTS` | `{reference}#CLM-SELF` | [Self](invalid.md#CLM-SELF) | `asserted` | `declared` | [Self](invalid.md#CLM-SELF) |
"""


class TestV262KnowledgeGraphAdversarialRound5(unittest.TestCase):
    def test_entry_map_with_ambiguous_namespace_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-entry-identity-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _map_text(namespace="product:current", knowledge_id="SELF"),
                encoding="utf-8",
            )
            with self.assertRaises(kg.GraphSecurityError) as caught:
                _load(root)
            self.assertEqual(
                "E_KG262_IDENTITY_COMPONENT_INVALID", caught.exception.code
            )

    def test_all_identity_components_reject_reference_delimiters_and_whitespace(self) -> None:
        defaults = {
            "namespace": "product.current",
            "knowledge_id": "SELF",
            "revision": "1",
        }
        invalid_values = {
            "namespace": ("product:current", "product@current", "product#current", "product current", "product\x01current"),
            "knowledge_id": ("SELF:ID", "SELF@ID", "SELF#ID", "SELF ID", "SELF\x01ID"),
            "revision": ("1:2", "1@2", "1#2", "1 2", "1\x012"),
        }
        for field, values in invalid_values.items():
            for invalid in values:
                with self.subTest(field=field, invalid=repr(invalid)):
                    components = dict(defaults)
                    components[field] = invalid
                    reference = (
                        f"{components['namespace']}:{components['knowledge_id']}"
                        f"@{components['revision']}"
                    )
                    with tempfile.TemporaryDirectory(
                        prefix="kg262-member-identity-"
                    ) as tmp:
                        root = Path(tmp)
                        (root / "knowledge-map.md").write_text(
                            _map_text(member_ref=reference), encoding="utf-8"
                        )
                        (root / "invalid.md").write_text(
                            _member_text(reference=reference, **components),
                            encoding="utf-8",
                        )
                        graph = _load(root)
                        self.assertNotIn(reference, graph.documents)
                        self.assertEqual((), graph.statements)
                        self.assertFalse(
                            any(
                                item.predicate == BASE_IRI + "/vocab/supports"
                                for item in graph.triples
                            )
                        )
                        self.assertTrue(
                            any(
                                item["rule_id"] == "invalid_identity_component"
                                for item in graph.observations
                            )
                        )

    def test_existing_unambiguous_identity_still_emits_the_asserted_relation(self) -> None:
        graph = _load(FIXTURES)
        self.assertIn("product.current:REQ-001@1", graph.documents)
        self.assertTrue(
            graph.has_triple(
                BASE_IRI
                + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1",
                BASE_IRI + "/vocab/hasAcceptanceCriterion",
                BASE_IRI
                + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1",
            )
        )


if __name__ == "__main__":
    unittest.main()
