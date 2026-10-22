"""Security boundaries: exact member closure, path, symlink, network, IRI grammar."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from okf_graph import graph as kg
from tests.helpers import BASE_IRI, BASIC, FIXTURES, copy_basic, load


def _map_text(
    *,
    namespace: str = "product.current",
    knowledge_id: str = "MAP-IDENTITY",
    revision: str = "1",
    member_ref: Optional[str] = None,
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


class TestMapClosure(unittest.TestCase):
    def test_exact_map_closure_excludes_unlisted_orphan(self) -> None:
        graph = load(BASIC)
        self.assertEqual(
            (
                "acceptance/target.md",
                "evidence/request.md",
                "requirements/source.md",
            ),
            graph.member_paths,
        )
        self.assertNotIn("product.current:ORPHAN-001@1", graph.documents)
        search = graph.search("must never be returned")
        self.assertEqual([], search["results"])

    def test_path_escape_is_rejected_with_a_stable_security_code(self) -> None:
        with self.assertRaises(kg.GraphSecurityError) as caught:
            load(FIXTURES / "unsafe", entry_map="escape-map.md")
        self.assertEqual("E_KG262_PATH_ESCAPE", caught.exception.code)

    def test_network_member_is_rejected_without_dereference(self) -> None:
        with self.assertRaises(kg.GraphSecurityError) as caught:
            load(FIXTURES / "unsafe", entry_map="network-map.md")
        self.assertEqual("E_KG262_NETWORK_FORBIDDEN", caught.exception.code)

    def test_symlink_member_is_rejected_even_when_target_is_readable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-symlink-") as tmp:
            root = Path(tmp)
            shutil.copy2(FIXTURES / "unsafe" / "symlink-map.md", root / "symlink-map.md")
            outside = root.parent / (root.name + "-outside.md")
            outside.write_text("not authorized\n", encoding="utf-8")
            try:
                (root / "linked.md").symlink_to(outside)
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    load(root, entry_map="symlink-map.md")
                self.assertEqual("E_KG262_PATH_SYMLINK", caught.exception.code)
            finally:
                outside.unlink(missing_ok=True)

    def test_entry_map_itself_must_be_a_safe_relative_path(self) -> None:
        with self.assertRaises(kg.GraphSecurityError) as caught:
            load(BASIC, entry_map="../basic/knowledge-map.md")
        self.assertEqual("E_KG262_PATH_ESCAPE", caught.exception.code)

    def test_safe_read_blocks_check_then_read_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-toctou-") as tmp:
            parent = Path(tmp)
            root = copy_basic(parent)
            member = root / "requirements/source.md"
            original = member.read_bytes()
            outside = parent / "outside.md"
            outside.write_bytes(
                original.replace(
                    b"Grounded answers cite Current evidence",
                    b"OUTSIDE SWAP MUST NOT LOAD",
                )
            )
            backup = parent / "source-backup.md"
            original_read_bytes = Path.read_bytes
            swapped = False

            def swapping_read(path: Path) -> bytes:
                nonlocal swapped
                if not swapped and path.resolve(strict=False) == member.resolve(strict=False):
                    swapped = True
                    path.rename(backup)
                    path.symlink_to(outside)
                return original_read_bytes(path)

            try:
                with mock.patch.object(Path, "read_bytes", swapping_read):
                    try:
                        graph = load(root)
                    except kg.GraphSecurityError as exc:
                        self.assertEqual("E_KG262_PATH_SYMLINK", exc.code)
                    else:
                        self.assertNotIn(
                            "OUTSIDE SWAP MUST NOT LOAD",
                            json.dumps(graph.documents, ensure_ascii=False),
                        )
            finally:
                if member.is_symlink():
                    member.unlink()
                if backup.exists():
                    backup.rename(member)

    def test_member_swapped_to_symlink_after_check_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-toctou-open-") as tmp:
            parent = Path(tmp)
            root = copy_basic(parent)
            member = root / "requirements/source.md"
            outside = parent / "outside.md"
            outside.write_text("OUTSIDE SWAP MUST NOT LOAD\n", encoding="utf-8")
            original_safe_file = kg._safe_file

            def check_then_swap(trusted_root: Path, relative: str) -> Path:
                checked = original_safe_file(trusted_root, relative)
                if relative == "requirements/source.md":
                    member.unlink()
                    member.symlink_to(outside)
                return checked

            with mock.patch.object(kg, "_safe_file", check_then_swap):
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    load(root)
            self.assertEqual("E_KG262_PATH_SYMLINK", caught.exception.code)


class TestBaseIri(unittest.TestCase):
    def test_base_iri_rejects_noncanonical_or_ambiguous_spellings(self) -> None:
        invalid = (
            "https://kg.example.invalid/okf ",
            "https://kg.example.invalid/okf\tbad",
            "https://kg.example.invalid/okf\\child",
            "https://kg.example.invalid/a/../okf",
            "https://kg.example.invalid/%2f",
            "https://kg.example.invalid/%ZZ",
            "https://kg.example.invalid/%6F",  # percent-encoded unreserved 'o'
        )
        for base_iri in invalid:
            with self.subTest(base_iri=repr(base_iri)):
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    load(BASIC, base_iri=base_iri)
                self.assertEqual("E_KG262_INVALID_BASE_IRI", caught.exception.code)

    def test_base_iri_rejects_raw_characters_forbidden_by_iri_syntax(self) -> None:
        for character in ("<", ">", "|", "^", "`", "{", "}"):
            with self.subTest(character=character):
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    load(BASIC, base_iri=f"https://kg.example.invalid/okf{character}bad")
                self.assertEqual("E_KG262_INVALID_BASE_IRI", caught.exception.code)

    def test_raw_square_brackets_are_forbidden_in_base_iri_path(self) -> None:
        for suffix in ("[left", "right]", "[balanced]"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    load(BASIC, base_iri="https://kg.example.invalid/okf/" + suffix)
                self.assertEqual("E_KG262_INVALID_BASE_IRI", caught.exception.code)

    def test_rfc3986_path_pchar_delimiters_remain_legal(self) -> None:
        graph = load(BASIC, base_iri="https://kg.example.invalid/okf/:@!$&'()*+,;=")
        self.assertTrue(graph.graph_iri.startswith("https://kg.example.invalid/okf/"))


class TestIdentityGrammar(unittest.TestCase):
    def test_entry_map_with_ambiguous_namespace_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-entry-identity-") as tmp:
            root = Path(tmp)
            (root / "knowledge-map.md").write_text(
                _map_text(namespace="product:current", knowledge_id="SELF"),
                encoding="utf-8",
            )
            with self.assertRaises(kg.GraphSecurityError) as caught:
                load(root)
            self.assertEqual("E_KG262_IDENTITY_COMPONENT_INVALID", caught.exception.code)

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
                    with tempfile.TemporaryDirectory(prefix="okfg-member-identity-") as tmp:
                        root = Path(tmp)
                        (root / "knowledge-map.md").write_text(
                            _map_text(member_ref=reference), encoding="utf-8"
                        )
                        (root / "invalid.md").write_text(
                            _member_text(reference=reference, **components),
                            encoding="utf-8",
                        )
                        graph = load(root)
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
        graph = load(BASIC)
        self.assertIn("product.current:REQ-001@1", graph.documents)
        self.assertTrue(
            graph.has_triple(
                BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1",
                BASE_IRI + "/vocab/hasAcceptanceCriterion",
                BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1",
            )
        )


if __name__ == "__main__":
    unittest.main()
