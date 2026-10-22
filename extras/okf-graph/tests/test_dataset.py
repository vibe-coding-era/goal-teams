"""Graph identity: canonical input digest, receipts, immutability, no persistence."""

from __future__ import annotations

import contextlib
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_IRI, BASIC, copy_basic, load


FORBIDDEN_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".ttl",
    ".nt",
    ".nq",
    ".trig",
    ".jsonld",
    ".rdf",
}
REMOVED_RUNTIME_KEYS = (
    "graph_role",
    "route_identity",
    "acceptance_eligible",
    "profile_document_sha256",
    "replay_version",
    "snapshot_sha256",
)


def _snapshot(root: Path) -> dict:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestDataset(unittest.TestCase):
    def test_graph_input_is_content_bound_canonical_and_deterministic(self) -> None:
        first = load(BASIC)
        second = load(BASIC)

        self.assertEqual("complete", first.coverage_state)
        self.assertRegex(first.graph_input_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            BASE_IRI + "/graph/" + first.graph_input_sha256,
            first.graph_iri,
        )
        self.assertEqual(first.graph_input, second.graph_input)
        self.assertEqual(first.graph_input_sha256, second.graph_input_sha256)
        self.assertEqual(first.graph_iri, second.graph_iri)

        graph_input = first.graph_input
        self.assertEqual("okf-docgraph-graph-input-v0.5", graph_input["schema"])
        self.assertEqual(
            "okf-document-graph-v0.4-rdf-mapping", graph_input["profile_id"]
        )
        self.assertEqual(
            "okf-frontmatter-commonmark-gfm-table-v0.4",
            graph_input["parser_contract_id"],
        )
        self.assertEqual("map", graph_input["selection"])
        self.assertEqual("product.current:MAP-CURRENT@1", graph_input["entry_map_ref"])
        self.assertEqual(
            hashlib.sha256((BASIC / "knowledge-map.md").read_bytes()).hexdigest(),
            graph_input["entry_map_sha256"],
        )
        for key in REMOVED_RUNTIME_KEYS:
            self.assertNotIn(key, graph_input)

        member_paths = [item["canonical_path"] for item in graph_input["members"]]
        self.assertEqual(
            sorted(member_paths, key=lambda value: value.encode("utf-8")), member_paths
        )
        self.assertNotIn("knowledge-map.md", member_paths)
        for member in graph_input["members"]:
            self.assertRegex(member["source_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual("parsed", member["compile_state"])

        jcs_bytes = json.dumps(
            graph_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(hashlib.sha256(jcs_bytes).hexdigest(), first.graph_input_sha256)

    def test_receipt_is_exact_graph_bound_and_truthful_about_capabilities(self) -> None:
        graph = load(BASIC)
        receipt = graph.to_receipt()
        self.assertEqual("okf-docgraph-receipt-v0.5", receipt["schema"])
        self.assertEqual(graph.graph_iri, receipt["graph_iri"])
        self.assertEqual(graph.graph_input_sha256, receipt["graph_input_sha256"])
        self.assertEqual(graph.coverage_state, receipt["coverage_state"])
        self.assertEqual(graph.capabilities, receipt["capabilities"])
        self.assertEqual("not_run", receipt["persistence_state"])
        self.assertNotIn("sparql_endpoint", receipt)
        self.assertNotIn("shacl_conforms", receipt)
        for key in REMOVED_RUNTIME_KEYS:
            self.assertNotIn(key, receipt)
        for observation in load(BASIC.parent / "quality").observations:
            self.assertNotIn("route_identity", observation)

    def test_document_claim_resolve_and_explain_expose_exact_provenance(self) -> None:
        graph = load(BASIC)
        document_ref = "product.current:REQ-001@1"
        claim_ref = document_ref + "#CLM-REQ-001-01"
        document = graph.documents[document_ref]
        claim = graph.resolve(claim_ref)["results"][0]
        explained = graph.explain(claim_ref)["results"][0]
        expected_source = hashlib.sha256(
            (BASIC / "requirements/source.md").read_bytes()
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
            self.assertEqual(graph.graph_input_sha256, item["graph_input_sha256"])

    def test_graph_public_identity_and_triples_are_read_only(self) -> None:
        graph = load(BASIC)
        receipt = graph.to_receipt()
        assignments = {
            "graph_iri": "https://poison.invalid/graph",
            "coverage_state": "partial",
            "persistence_state": "completed",
            "member_paths": ("poison.md",),
            "triples": (),
            "statements": (),
            "observations": (),
            "documents": {},
            "claims": {},
            "graph_input": {},
            "capabilities": {},
        }
        for name, value in assignments.items():
            with self.subTest(name=name):
                with self.assertRaises((AttributeError, TypeError)):
                    setattr(graph, name, value)
        with self.assertRaises((AttributeError, TypeError)):
            graph.graph_input_sha256 = "0" * 64
        self.assertEqual(receipt, graph.to_receipt())

    def test_public_snapshots_and_query_results_cannot_poison_internal_state(self) -> None:
        graph = load(BASIC)
        document_ref = "product.current:REQ-001@1"
        claim_ref = document_ref + "#CLM-REQ-001-01"
        baseline_digest = graph.graph_input_sha256
        baseline_resolve = graph.resolve(claim_ref)
        baseline_search = graph.search("grounded answer")
        baseline_explain = graph.explain(claim_ref)
        baseline_lookup = graph.lookup(claim_ref)

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
        looked_up = graph.lookup(claim_ref)
        looked_up["results"][0]["evidence_refs"].clear()
        public_documents = graph.documents
        public_documents[document_ref]["title"] = "POISONED TITLE"
        public_documents.clear()
        public_claims = graph.claims
        public_claims[claim_ref]["claim_text"] = "POISONED CLAIM"
        public_claims.clear()

        self.assertEqual("okf-docgraph-graph-input-v0.5", graph.graph_input["schema"])
        self.assertTrue(graph.graph_input["members"])
        self.assertIn(document_ref, graph.documents)
        self.assertIn(claim_ref, graph.claims)
        self.assertNotEqual("POISONED TITLE", graph.documents[document_ref]["title"])
        self.assertEqual(baseline_resolve, graph.resolve(claim_ref))
        self.assertEqual(baseline_search, graph.search("grounded answer"))
        self.assertEqual(baseline_explain, graph.explain(claim_ref))
        self.assertEqual(baseline_lookup, graph.lookup(claim_ref))
        self.assertEqual(baseline_digest, graph.graph_input_sha256)
        canonical = json.dumps(
            graph.graph_input,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(baseline_digest, hashlib.sha256(canonical).hexdigest())


class TestNoPersistence(unittest.TestCase):
    def test_load_and_all_native_queries_have_no_database_network_or_disk_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-persistence-") as tmp:
            root = copy_basic(Path(tmp))
            before = _snapshot(root)

            with contextlib.ExitStack() as stack:
                for target, code in (
                    ("socket.create_connection", "E_KG262_NETWORK_ATTEMPT"),
                    ("urllib.request.urlopen", "E_KG262_NETWORK_ATTEMPT"),
                    ("sqlite3.connect", "E_KG262_DATABASE_ATTEMPT"),
                ):
                    stack.enter_context(
                        mock.patch(target, side_effect=AssertionError(code))
                    )
                graph = load(root)
                reference = "product.current:REQ-001@1#CLM-REQ-001-01"
                receipts = (
                    graph.observe(),
                    graph.resolve(reference),
                    graph.search("grounded answer"),
                    graph.neighbors(reference),
                    graph.trace(reference),
                    graph.explain(reference),
                    graph.lookup(reference),
                )
                self.assertTrue(graph.to_ntriples())
                self.assertTrue(
                    graph.has_triple(
                        BASE_IRI
                        + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1",
                        BASE_IRI + "/vocab/hasAcceptanceCriterion",
                        BASE_IRI
                        + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1",
                    )
                )

            self.assertEqual(before, _snapshot(root))
            self.assertEqual("not_run", graph.persistence_state)
            for receipt in receipts:
                self.assertEqual("not_run", receipt["persistence"])
            forbidden = [
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES
            ]
            self.assertEqual([], forbidden)

    def test_repeated_loads_do_not_reuse_a_hidden_mutable_graph_instance(self) -> None:
        first = load(BASIC)
        second = load(BASIC)
        self.assertIsNot(first, second)
        self.assertEqual(first.graph_input_sha256, second.graph_input_sha256)
        self.assertEqual(first.triples, second.triples)
        self.assertEqual(first.statements, second.statements)


if __name__ == "__main__":
    unittest.main()
