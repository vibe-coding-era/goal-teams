from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v250 import okf_document_graph as kg


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "f" * 64
PROFILE_SHA256 = "e" * 64
SNAPSHOT_SHA256 = "d" * 64


def _load_current(root: Path, *, base_iri: str = BASE_IRI):
    return kg.load_current_graph(
        root,
        "knowledge-map.md",
        kg_base_iri=base_iri,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


def _load_replay(root: Path):
    return kg.load_replay_graph(
        root,
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
        replay_version="V2.6",
        snapshot_sha256=SNAPSHOT_SHA256,
    )


def _copy_current(parent: Path, name: str = "current") -> Path:
    root = parent / name
    shutil.copytree(FIXTURES / "current", root)
    return root


def _replace(path: Path, old: str, new: str, *, count: int = 1) -> None:
    source = path.read_text(encoding="utf-8")
    if old not in source:
        raise AssertionError(f"fixture token missing: {old!r}")
    path.write_text(source.replace(old, new, count), encoding="utf-8")


def _document(
    *,
    namespace: str,
    knowledge_id: str,
    claim_id: str,
    title: str,
    lifecycle: str = "current",
) -> str:
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
lifecycle: {lifecycle}
modality: note
epistemic_state: documented
sensitivity: internal
---

# {title}

### {claim_id}

{title} claim text.
"""


def _map_document(rows: list[tuple[str, str]], *, lifecycle: str = "current") -> str:
    rendered = "\n".join(
        f"| `{reference}` | [{reference}]({path}) | `Knowledge Note` | `{lifecycle}` |"
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
lifecycle: {lifecycle}
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


class TestV262KnowledgeGraphAdversarial(unittest.TestCase):
    def test_safe_read_blocks_check_then_read_symlink_swap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-toctou-") as tmp:
            parent = Path(tmp)
            root = _copy_current(parent)
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
                if (
                    not swapped
                    and path.resolve(strict=False) == member.resolve(strict=False)
                ):
                    swapped = True
                    path.rename(backup)
                    path.symlink_to(outside)
                return original_read_bytes(path)

            try:
                with mock.patch.object(Path, "read_bytes", swapping_read):
                    try:
                        graph = _load_current(root)
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

    def test_unknown_or_unsupported_neighbor_predicate_never_disables_filter(self) -> None:
        graph = _load_current(FIXTURES / "current")
        reference = "product.current:REQ-001@1#CLM-REQ-001-01"
        for predicate in ("UNKNOWN_PREDICATE", "RELATED_TO"):
            with self.subTest(predicate=predicate):
                try:
                    receipt = graph.neighbors(
                        reference, direction="out", predicate=predicate
                    )
                except kg.GraphSecurityError:
                    continue
                self.assertEqual([], receipt["results"])

    def test_target_link_fragment_must_match_target_ref_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-target-fragment-") as tmp:
            root = _copy_current(Path(tmp))
            source = root / "requirements/source.md"
            _replace(
                source,
                "../acceptance/target.md#CLM-AC-001-01",
                "../acceptance/target.md#CLM-WRONG-ANCHOR",
            )
            graph = _load_current(root)
            subject = BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1"
            predicate = BASE_IRI + "/vocab/hasAcceptanceCriterion"
            target = BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1"
            self.assertFalse(graph.has_triple(subject, predicate, target))
            findings = [
                item
                for item in graph.observations
                if item["rule_id"] == "dangling_or_mismatched_target"
            ]
            self.assertTrue(findings)
            self.assertIn("CLM-WRONG-ANCHOR", json.dumps(findings))

    def test_evidence_anchor_must_resolve_exact_claim_without_path_guess(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-evidence-anchor-") as tmp:
            root = _copy_current(Path(tmp))
            source = root / "requirements/source.md"
            _replace(
                source,
                "../evidence/request.md#CLM-EVD-001-01",
                "../evidence/request.md#CLM-EVD-MISSING",
                count=2,
            )
            graph = _load_current(root)
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

    def test_duplicate_document_revision_identity_is_observed_and_first_wins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-duplicate-doc-") as tmp:
            root = _copy_current(Path(tmp))
            duplicate = root / "zzz-duplicate.md"
            duplicate.write_text(
                (root / "requirements/source.md")
                .read_text(encoding="utf-8")
                .replace(
                    "Grounded answers cite Current evidence",
                    "DUPLICATE REVISION MUST NOT WIN",
                ),
                encoding="utf-8",
            )
            map_path = root / "knowledge-map.md"
            _replace(
                map_path,
                "| `product.current:EVD-001@1` | [User evidence](evidence/request.md) | `Knowledge Evidence` | `current` |",
                "| `product.current:EVD-001@1` | [User evidence](evidence/request.md) | `Knowledge Evidence` | `current` |\n"
                "| `product.current:REQ-001@1` | [Duplicate revision](zzz-duplicate.md) | `Knowledge Requirement` | `current` |",
            )
            graph = _load_current(root)
            reference = "product.current:REQ-001@1"
            self.assertEqual("requirements/source.md", graph.documents[reference]["path"])
            self.assertTrue(
                any(
                    item["rule_id"] == "duplicate_document_revision_identity"
                    for item in graph.observations
                )
            )

    def test_duplicate_relation_id_cannot_reuse_one_statement_for_two_spo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-duplicate-relation-") as tmp:
            root = _copy_current(Path(tmp))
            source = root / "requirements/source.md"
            existing = "| `REL-REQ-001-01` | `HAS_AC` | `product.current:AC-001@1#CLM-AC-001-01` | [Citation AC](../acceptance/target.md#CLM-AC-001-01) | `asserted` | `declared` | [User evidence](../evidence/request.md#CLM-EVD-001-01) |"
            duplicate = "| `REL-REQ-001-01` | `SUPPORTS` | `product.current:EVD-001@1#CLM-EVD-001-01` | [Evidence target](../evidence/request.md#CLM-EVD-001-01) | `asserted` | `declared` | [User evidence](../evidence/request.md#CLM-EVD-001-01) |"
            _replace(source, existing, existing + "\n" + duplicate)
            graph = _load_current(root)
            statements = [
                item
                for item in graph.statements
                if item["relation_id"] == "REL-REQ-001-01"
            ]
            self.assertEqual(1, len(statements))
            self.assertTrue(
                any(
                    item["rule_id"] == "duplicate_relation_id"
                    for item in graph.observations
                )
            )
            source_iri = BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1"
            evidence_iri = BASE_IRI + "/claim/product.current/EVD-001/CLM-EVD-001-01/revision/1"
            self.assertFalse(
                graph.has_triple(
                    source_iri, BASE_IRI + "/vocab/supports", evidence_iri
                )
            )

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
                    _load_current(FIXTURES / "current", base_iri=base_iri)
                self.assertEqual("E_KG262_INVALID_BASE_IRI", caught.exception.code)

    def test_current_and_replay_lifecycle_inputs_are_not_interchangeable(self) -> None:
        with self.assertRaises(kg.GraphSecurityError) as current_error:
            _load_current(FIXTURES / "replay")
        self.assertEqual("E_KG262_GRAPH_ROLE_MISMATCH", current_error.exception.code)

        with self.assertRaises(kg.GraphSecurityError) as replay_error:
            _load_replay(FIXTURES / "current")
        self.assertEqual("E_KG262_GRAPH_ROLE_MISMATCH", replay_error.exception.code)

    def test_document_claim_resolve_and_explain_expose_exact_provenance(self) -> None:
        graph = _load_current(FIXTURES / "current")
        document_ref = "product.current:REQ-001@1"
        claim_ref = document_ref + "#CLM-REQ-001-01"
        document = graph.documents[document_ref]
        claim = graph.resolve(claim_ref)["results"][0]
        explained = graph.explain(claim_ref)["results"][0]
        expected_source = hashlib.sha256(
            (FIXTURES / "current/requirements/source.md").read_bytes()
        ).hexdigest()

        for item, expected_anchor in (
            (document, "requirements/source.md"),
            (claim, "requirements/source.md#CLM-REQ-001-01"),
            (explained, "requirements/source.md#CLM-REQ-001-01"),
        ):
            self.assertEqual(expected_source, item["source_sha256"])
            self.assertRegex(item["revision_digest"], r"^[0-9a-f]{64}$")
            self.assertEqual(expected_anchor, item["source_anchor"])
            self.assertEqual("parsed", item["extraction_state"])
            self.assertEqual(graph.graph_iri, item["graph_iri"])
            self.assertEqual(
                graph.graph_input_sha256, item["graph_input_sha256"]
            )

    def test_unicode_nfc_identity_collision_is_observed_without_shared_iri(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-nfc-collision-") as tmp:
            root = Path(tmp) / "current"
            root.mkdir()
            first_id = "CAF\u00e9"
            second_id = "CAFe\u0301"
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
                _map_document(
                    [(first_ref, "first.md"), (second_ref, "second.md")]
                ),
                encoding="utf-8",
            )
            graph = _load_current(root)
            self.assertTrue(
                any(
                    item["rule_id"] == "identity_nfc_collision"
                    for item in graph.observations
                )
            )
            revision_iris = [
                graph.documents[reference]["revision_iri"]
                for reference in (first_ref, second_ref)
                if reference in graph.documents
            ]
            self.assertEqual(len(revision_iris), len(set(revision_iris)))

    def test_public_snapshots_and_query_results_cannot_poison_internal_state(self) -> None:
        graph = _load_current(FIXTURES / "current")
        document_ref = "product.current:REQ-001@1"
        claim_ref = document_ref + "#CLM-REQ-001-01"
        baseline_digest = graph.graph_input_sha256
        baseline_resolve = graph.resolve(claim_ref)
        baseline_search = graph.search("grounded answer")
        baseline_explain = graph.explain(claim_ref)

        public_input = graph.graph_input
        public_input["schema"] = "poisoned"
        public_input["members"].clear()
        resolved = graph.resolve(claim_ref)
        resolved["results"][0]["claim_text"] = "POISONED CLAIM"
        resolved["results"][0]["evidence_paths"].append("poison.md")
        searched = graph.search("grounded answer")
        searched["results"][0]["claim_refs"].clear()
        explained = graph.explain(claim_ref)
        explained["results"][0]["evidence_paths"].append("poison.md")
        public_documents = graph.documents
        public_documents[document_ref]["title"] = "POISONED TITLE"
        public_documents.clear()

        self.assertEqual("okf-docgraph-graph-input-v0.4", graph.graph_input["schema"])
        self.assertTrue(graph.graph_input["members"])
        self.assertIn(document_ref, graph.documents)
        self.assertNotEqual("POISONED TITLE", graph.documents[document_ref]["title"])
        self.assertEqual(baseline_resolve, graph.resolve(claim_ref))
        self.assertEqual(baseline_search, graph.search("grounded answer"))
        self.assertEqual(baseline_explain, graph.explain(claim_ref))
        self.assertEqual(baseline_digest, graph.graph_input_sha256)
        canonical = json.dumps(
            graph.graph_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(baseline_digest, hashlib.sha256(canonical).hexdigest())

    def test_empty_v04_assertion_state_is_observed_and_not_asserted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kg262-empty-assertion-") as tmp:
            root = _copy_current(Path(tmp))
            source = root / "requirements/source.md"
            _replace(source, "| `asserted` |", "|  |")
            graph = _load_current(root)
            source_iri = BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1"
            predicate = BASE_IRI + "/vocab/hasAcceptanceCriterion"
            target_iri = BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1"
            self.assertFalse(graph.has_triple(source_iri, predicate, target_iri))
            self.assertFalse(
                any(
                    item["relation_id"] == "REL-REQ-001-01"
                    for item in graph.statements
                )
            )
            self.assertTrue(
                any(
                    item["rule_id"] == "missing_assertion_state"
                    for item in graph.observations
                )
            )


if __name__ == "__main__":
    unittest.main()
