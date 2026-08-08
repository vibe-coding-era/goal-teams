from __future__ import annotations

import hashlib
import importlib
import json
import re
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262"
BASE_IRI = "https://kg.example.invalid/okf"
CURRENT_ROUTE = "sha256:" + "7" * 64
REPLAY_ROUTE = "sha256:" + "8" * 64
PROFILE_SHA256 = "9" * 64
SNAPSHOT_SHA256 = "a" * 64


def _target(testcase: unittest.TestCase):
    try:
        return importlib.import_module("scripts.v250.okf_document_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v250.okf_document_graph":
            testcase.fail("E_KG262_TARGET_MISSING: scripts.v250.okf_document_graph")
        raise


def _current(kg):
    return kg.load_current_graph(
        FIXTURES / "current",
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=CURRENT_ROUTE,
        profile_document_sha256=PROFILE_SHA256,
    )


def _replay(kg):
    return kg.load_replay_graph(
        FIXTURES / "replay",
        "knowledge-map.md",
        kg_base_iri=BASE_IRI,
        route_identity=REPLAY_ROUTE,
        profile_document_sha256=PROFILE_SHA256,
        replay_version="V2.6",
        snapshot_sha256=SNAPSHOT_SHA256,
    )


class TestV262KnowledgeGraphDataset(unittest.TestCase):
    def test_current_graph_input_is_content_bound_canonical_and_deterministic(self) -> None:
        kg = _target(self)
        first = _current(kg)
        second = _current(kg)

        self.assertEqual("current", first.graph_role)
        self.assertEqual(CURRENT_ROUTE, first.route_identity)
        self.assertTrue(first.acceptance_eligible)
        self.assertEqual("complete", first.coverage_state)
        self.assertRegex(first.graph_input_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            BASE_IRI + "/graph/current/" + first.graph_input_sha256,
            first.graph_iri,
        )
        self.assertEqual(first.graph_input, second.graph_input)
        self.assertEqual(first.graph_input_sha256, second.graph_input_sha256)
        self.assertEqual(first.graph_iri, second.graph_iri)

        graph_input = first.graph_input
        self.assertEqual("okf-docgraph-graph-input-v0.4", graph_input["schema"])
        self.assertEqual(
            "okf-document-graph-v0.4-rdf-mapping", graph_input["profile_id"]
        )
        self.assertEqual(PROFILE_SHA256, graph_input["profile_document_sha256"])
        self.assertEqual(
            "okf-frontmatter-commonmark-gfm-table-v0.4",
            graph_input["parser_contract_id"],
        )
        self.assertEqual("current", graph_input["graph_role"])
        self.assertEqual(CURRENT_ROUTE, graph_input["route_identity"])
        self.assertEqual("product.current:MAP-CURRENT@1", graph_input["entry_map_ref"])
        self.assertEqual(
            hashlib.sha256(
                (FIXTURES / "current" / "knowledge-map.md").read_bytes()
            ).hexdigest(),
            graph_input["entry_map_sha256"],
        )
        self.assertNotIn("replay_version", graph_input)
        self.assertNotIn("snapshot_sha256", graph_input)

        member_paths = [item["canonical_path"] for item in graph_input["members"]]
        self.assertEqual(sorted(member_paths, key=lambda value: value.encode("utf-8")), member_paths)
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
        self.assertEqual(
            hashlib.sha256(jcs_bytes).hexdigest(), first.graph_input_sha256
        )

    def test_replay_requires_explicit_identity_and_never_becomes_current(self) -> None:
        kg = _target(self)
        current = _current(kg)
        replay = _replay(kg)

        self.assertEqual("replay", replay.graph_role)
        self.assertEqual(REPLAY_ROUTE, replay.route_identity)
        self.assertFalse(replay.acceptance_eligible)
        self.assertEqual("V2.6", replay.graph_input["replay_version"])
        self.assertEqual(SNAPSHOT_SHA256, replay.graph_input["snapshot_sha256"])
        self.assertEqual(
            BASE_IRI
            + "/graph/replay/V2.6/"
            + replay.graph_input_sha256,
            replay.graph_iri,
        )
        self.assertNotEqual(current.graph_iri, replay.graph_iri)
        self.assertNotEqual(current.graph_input_sha256, replay.graph_input_sha256)
        self.assertIn("product.replay.v2.6:REQ-OLD-001@1", replay.documents)
        self.assertNotIn("product.replay.v2.6:REQ-OLD-001@1", current.documents)
        self.assertNotIn("product.current:REQ-001@1", replay.documents)

    def test_receipt_is_exact_graph_bound_and_truthful_about_capabilities(self) -> None:
        kg = _target(self)
        graph = _current(kg)
        receipt = graph.to_receipt()
        self.assertEqual(graph.graph_role, receipt["graph_role"])
        self.assertEqual(graph.graph_iri, receipt["graph_iri"])
        self.assertEqual(graph.graph_input_sha256, receipt["graph_input_sha256"])
        self.assertEqual(graph.route_identity, receipt["route_identity"])
        self.assertEqual(graph.acceptance_eligible, receipt["acceptance_eligible"])
        self.assertEqual(graph.coverage_state, receipt["coverage_state"])
        self.assertEqual(graph.capabilities, receipt["capabilities"])
        self.assertEqual("not_run", receipt["persistence_state"])
        self.assertNotIn("sparql_endpoint", receipt)
        self.assertNotIn("shacl_conforms", receipt)


if __name__ == "__main__":
    unittest.main()
