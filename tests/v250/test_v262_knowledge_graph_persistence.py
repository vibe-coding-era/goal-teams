from __future__ import annotations

import hashlib
import importlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "d" * 64
PROFILE_SHA256 = "e" * 64
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


def _target(testcase: unittest.TestCase):
    try:
        return importlib.import_module("scripts.v250.okf_document_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v250.okf_document_graph":
            testcase.fail("E_KG262_TARGET_MISSING: scripts.v250.okf_document_graph")
        raise


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestV262KnowledgeGraphPersistence(unittest.TestCase):
    def test_load_and_all_native_queries_have_no_database_network_or_disk_writes(self) -> None:
        kg = _target(self)
        with tempfile.TemporaryDirectory(prefix="kg262-persistence-") as tmp:
            root = Path(tmp) / "current"
            shutil.copytree(FIXTURES / "current", root)
            before = _snapshot(root)

            with (
                mock.patch(
                    "socket.create_connection",
                    side_effect=AssertionError("E_KG262_NETWORK_ATTEMPT"),
                ),
                mock.patch(
                    "urllib.request.urlopen",
                    side_effect=AssertionError("E_KG262_NETWORK_ATTEMPT"),
                ),
                mock.patch(
                    "sqlite3.connect",
                    side_effect=AssertionError("E_KG262_DATABASE_ATTEMPT"),
                ),
            ):
                graph = kg.load_current_graph(
                    root,
                    "knowledge-map.md",
                    kg_base_iri=BASE_IRI,
                    route_identity=ROUTE_IDENTITY,
                    profile_document_sha256=PROFILE_SHA256,
                )
                reference = "product.current:REQ-001@1#CLM-REQ-001-01"
                receipts = (
                    graph.observe(),
                    graph.resolve(reference),
                    graph.search("grounded answer"),
                    graph.neighbors(reference),
                    graph.trace(reference),
                    graph.explain(reference),
                )
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
        kg = _target(self)
        first = kg.load_current_graph(
            FIXTURES / "current",
            "knowledge-map.md",
            kg_base_iri=BASE_IRI,
            route_identity=ROUTE_IDENTITY,
            profile_document_sha256=PROFILE_SHA256,
        )
        second = kg.load_current_graph(
            FIXTURES / "current",
            "knowledge-map.md",
            kg_base_iri=BASE_IRI,
            route_identity=ROUTE_IDENTITY,
            profile_document_sha256=PROFILE_SHA256,
        )
        self.assertIsNot(first, second)
        self.assertEqual(first.graph_input_sha256, second.graph_input_sha256)
        self.assertEqual(first.triples, second.triples)
        self.assertEqual(first.statements, second.statements)


if __name__ == "__main__":
    unittest.main()
