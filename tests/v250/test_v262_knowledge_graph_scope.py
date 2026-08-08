from __future__ import annotations

import importlib
import shutil
import tempfile
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "kg262"
BASE_IRI = "https://kg.example.invalid/okf"
ROUTE_IDENTITY = "sha256:" + "3" * 64
PROFILE_SHA256 = "4" * 64


def _target(testcase: unittest.TestCase):
    try:
        return importlib.import_module("scripts.v250.okf_document_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v250.okf_document_graph":
            testcase.fail("E_KG262_TARGET_MISSING: scripts.v250.okf_document_graph")
        raise


def _load(kg, root: Path, entry_map: str):
    return kg.load_current_graph(
        root,
        entry_map,
        kg_base_iri=BASE_IRI,
        route_identity=ROUTE_IDENTITY,
        profile_document_sha256=PROFILE_SHA256,
    )


class TestV262KnowledgeGraphScope(unittest.TestCase):
    def test_exact_map_closure_excludes_unlisted_orphan(self) -> None:
        kg = _target(self)
        graph = _load(kg, FIXTURES / "current", "knowledge-map.md")
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
        kg = _target(self)
        with self.assertRaises(kg.GraphSecurityError) as caught:
            _load(kg, FIXTURES / "unsafe", "escape-map.md")
        self.assertEqual("E_KG262_PATH_ESCAPE", caught.exception.code)

    def test_network_member_is_rejected_without_dereference(self) -> None:
        kg = _target(self)
        with self.assertRaises(kg.GraphSecurityError) as caught:
            _load(kg, FIXTURES / "unsafe", "network-map.md")
        self.assertEqual("E_KG262_NETWORK_FORBIDDEN", caught.exception.code)

    def test_symlink_member_is_rejected_even_when_target_is_readable(self) -> None:
        kg = _target(self)
        with tempfile.TemporaryDirectory(prefix="kg262-symlink-") as tmp:
            root = Path(tmp)
            shutil.copy2(FIXTURES / "unsafe" / "symlink-map.md", root / "symlink-map.md")
            outside = root.parent / (root.name + "-outside.md")
            outside.write_text("not authorized\n", encoding="utf-8")
            try:
                (root / "linked.md").symlink_to(outside)
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    _load(kg, root, "symlink-map.md")
                self.assertEqual("E_KG262_PATH_SYMLINK", caught.exception.code)
            finally:
                outside.unlink(missing_ok=True)

    def test_entry_map_itself_must_be_a_safe_relative_path(self) -> None:
        kg = _target(self)
        with self.assertRaises(kg.GraphSecurityError) as caught:
            _load(kg, FIXTURES / "current", "../current/knowledge-map.md")
        self.assertEqual("E_KG262_PATH_ESCAPE", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
