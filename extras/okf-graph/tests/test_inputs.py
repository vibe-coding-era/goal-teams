"""Input selection (map, explicit files, directory scan) and host-independent output."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from okf_graph import graph as kg
from tests.helpers import BASE_IRI, BASIC, FIXTURES, copy_basic, document, load


HAS_AC = (
    BASE_IRI + "/claim/product.current/REQ-001/CLM-REQ-001-01/revision/1",
    BASE_IRI + "/vocab/hasAcceptanceCriterion",
    BASE_IRI + "/claim/product.current/AC-001/CLM-AC-001-01/revision/1",
)
ALL_BASIC_FILES = [
    "acceptance/target.md",
    "evidence/request.md",
    "orphan.md",
    "requirements/source.md",
]


def _rules(graph) -> set:
    return {item["rule_id"] for item in graph.observations}


class TestSelection(unittest.TestCase):
    def test_auto_mode_uses_the_knowledge_map_when_present(self) -> None:
        auto = kg.load_graph(BASIC)
        explicit = load(BASIC)
        self.assertEqual("map", auto.graph_input["selection"])
        self.assertEqual(explicit.graph_input_sha256, auto.graph_input_sha256)
        self.assertNotIn("product.current:ORPHAN-001@1", auto.documents)

    def test_directory_without_map_compiles_every_markdown_file(self) -> None:
        mapped = load(BASIC)
        with tempfile.TemporaryDirectory(prefix="okfg-scan-") as tmp:
            root = copy_basic(Path(tmp))
            (root / "knowledge-map.md").unlink()
            self.assertEqual(ALL_BASIC_FILES, kg.discover_markdown_files(root))

            graph = kg.load_graph(root)
            self.assertEqual(tuple(ALL_BASIC_FILES), graph.member_paths)
            self.assertEqual("files", graph.graph_input["selection"])
            self.assertNotIn("entry_map_ref", graph.graph_input)
            self.assertNotIn("entry_map_sha256", graph.graph_input)
            self.assertIn("product.current:ORPHAN-001@1", graph.documents)
            self.assertTrue(graph.has_triple(*HAS_AC))
            # Same documents mint the same IRIs and triples in either mode.
            self.assertTrue(set(mapped.triples).issubset(set(graph.triples)))
            self.assertEqual(
                graph.graph_input_sha256,
                kg.load_graph(root, kg.discover_markdown_files(root)).graph_input_sha256,
            )

    def test_explicit_files_select_exact_members_in_any_order(self) -> None:
        graph = kg.load_graph(
            BASIC,
            ["requirements/source.md", "./acceptance/target.md", "requirements/source.md"],
        )
        self.assertEqual(("acceptance/target.md", "requirements/source.md"), graph.member_paths)
        self.assertEqual("files", graph.graph_input["selection"])
        self.assertTrue(graph.has_triple(*HAS_AC))
        # The evidence document is not a member, so its links stay unresolved.
        self.assertIn("dangling_or_mismatched_evidence", _rules(graph))
        self.assertEqual("partial", graph.coverage_state)
        reordered = kg.load_graph(BASIC, ["acceptance/target.md", "requirements/source.md"])
        self.assertEqual(graph.graph_input_sha256, reordered.graph_input_sha256)

    def test_files_and_entry_map_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            kg.load_graph(BASIC, ["orphan.md"], entry_map="knowledge-map.md")
        with self.assertRaises(TypeError):
            kg.load_graph(BASIC, "orphan.md")

    def test_explicit_entry_map_must_exist(self) -> None:
        with self.assertRaises(kg.GraphSecurityError) as caught:
            kg.load_graph(BASIC, entry_map="missing-map.md")
        self.assertEqual("E_KG262_ENTRY_MAP_MISSING", caught.exception.code)

    def test_explicit_file_paths_fail_closed_like_map_members(self) -> None:
        cases = {
            "../outside.md": "E_KG262_PATH_ESCAPE",
            "a/../../outside.md": "E_KG262_PATH_ESCAPE",
            "/etc/passwd": "E_KG262_PATH_ESCAPE",
            "": "E_KG262_PATH_ESCAPE",
            "https://example.invalid/remote.md": "E_KG262_NETWORK_FORBIDDEN",
            "//example.invalid/remote.md": "E_KG262_NETWORK_FORBIDDEN",
        }
        for raw, code in cases.items():
            with self.subTest(raw=raw):
                with self.assertRaises(kg.GraphSecurityError) as caught:
                    kg.load_graph(BASIC, [raw])
                self.assertEqual(code, caught.exception.code)

    def test_explicit_file_names_are_literal_not_uri_references(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-literal-name-") as tmp:
            root = Path(tmp)
            (root / "notes#1?.md").write_text(
                document("NOTES", "### CLM-NOTES\n\nNotes."), encoding="utf-8"
            )
            graph = kg.load_graph(root, ["notes#1?.md"])
            self.assertEqual("notes#1?.md", graph.documents["product.current:NOTES@1"]["path"])

    def test_directory_scan_skips_hidden_entries_and_never_follows_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-scan-skip-") as tmp:
            root = Path(tmp) / "docs"
            (root / "sub").mkdir(parents=True)
            (root / ".git").mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            for path, knowledge_id in (
                (root / "a.md", "A"),
                (root / "sub" / "b.md", "B"),
                (root / ".hidden.md", "HIDDEN"),
                (root / ".git" / "c.md", "GIT"),
                (outside / "secret.md", "SECRET"),
            ):
                path.write_text(document(knowledge_id, "### CLM-X\n\nX."), encoding="utf-8")
            (root / "notes.txt").write_text("not markdown\n", encoding="utf-8")
            (root / "link.md").symlink_to(outside / "secret.md")
            (root / "linked-dir").symlink_to(outside, target_is_directory=True)

            self.assertEqual(["a.md", "sub/b.md"], kg.discover_markdown_files(root))
            graph = kg.load_graph(root)
            self.assertEqual(
                ["product.current:A@1", "product.current:B@1"], sorted(graph.documents)
            )
            with self.assertRaises(kg.GraphSecurityError) as caught:
                kg.load_graph(root, ["link.md"])
            self.assertEqual("E_KG262_PATH_SYMLINK", caught.exception.code)

    def test_document_without_identity_is_observed_without_a_map(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-no-identity-") as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Plain Markdown\n", encoding="utf-8")
            (root / "bad.md").write_text(
                document("BAD ID", "### CLM-X\n\nX."), encoding="utf-8"
            )
            (root / "good.md").write_text(
                document("GOOD", "### CLM-X\n\nX."), encoding="utf-8"
            )
            graph = kg.load_graph(root)
            self.assertEqual(["product.current:GOOD@1"], list(graph.documents))
            findings = {
                item["subject_ref"]: item["detail"]["fields"]
                for item in graph.observations
                if item["rule_id"] == "missing_document_identity"
            }
            self.assertEqual(
                {"README.md": ["knowledge_id", "namespace", "revision"], "bad.md": ["knowledge_id"]},
                findings,
            )
            self.assertIn("invalid_identity_component", _rules(graph))
            states = {m["canonical_path"]: m["compile_state"] for m in graph.graph_input["members"]}
            self.assertEqual(
                {"README.md": "partial", "bad.md": "partial", "good.md": "parsed"}, states
            )


class TestLifecycleAndDeterminism(unittest.TestCase):
    def _single(self, text: str):
        directory = tempfile.TemporaryDirectory(prefix="okfg-lifecycle-")
        root = Path(directory.name)
        (root / "doc.md").write_text(text, encoding="utf-8")
        self.addCleanup(directory.cleanup)
        graph = kg.load_graph(root)
        return graph, graph.documents[next(iter(graph.documents))]

    def test_lifecycle_and_namespace_no_longer_select_a_loader(self) -> None:
        text = document("OLD", "### CLM-OLD\n\nOld claim.").replace(
            "lifecycle: current", "lifecycle: ARCHIVED"
        ).replace("namespace: product.current", "namespace: product.replay.v2.6")
        graph, record = self._single(text)
        self.assertEqual("product.replay.v2.6:OLD@1", record["reference"])
        self.assertEqual("archived", record["lifecycle"])
        self.assertTrue(
            graph.has_triple(
                record["revision_iri"],
                BASE_IRI + "/vocab/lifecycle",
                BASE_IRI + "/vocab/archived",
            )
        )
        self.assertEqual((), graph.observations)

    def test_lifecycle_iri_does_not_depend_on_the_host_unicode_case_tables(self) -> None:
        # U+10570 (Unicode 14) lowercases on Python >= 3.11 but not on 3.9.
        text = document("CASE", "### CLM-CASE\n\nCase.").replace(
            "lifecycle: current", "lifecycle: \U00010570"
        )
        graph, record = self._single(text)
        self.assertEqual("\U00010570", record["lifecycle"])
        self.assertTrue(
            graph.has_triple(
                record["revision_iri"],
                BASE_IRI + "/vocab/lifecycle",
                BASE_IRI + "/vocab/%F0%90%95%B0",
            )
        )

    def test_missing_lifecycle_is_withheld_and_observed(self) -> None:
        text = document("NOLIFE", "### CLM-X\n\nX.").replace("lifecycle: current\n", "")
        graph, record = self._single(text)
        self.assertEqual("", record["lifecycle"])
        self.assertFalse(
            any(t.predicate == BASE_IRI + "/vocab/lifecycle" for t in graph.triples)
        )
        finding = next(
            item for item in graph.observations
            if item["rule_id"] == "missing_recommended_metadata"
        )
        self.assertEqual(["lifecycle"], finding["detail"]["fields"])

    def test_timestamp_validity_does_not_depend_on_the_python_version(self) -> None:
        # datetime.fromisoformat accepts only 3 or 6 fraction digits before 3.11.
        for value in (
            "2026-08-08T12:34:56.1+08:00",
            "2026-08-08T12:34:56.12Z",
            "2026-08-08T12:34:56.1234567-05:00",
            "2028-02-29T00:00:00Z",
        ):
            with self.subTest(valid=value):
                self.assertTrue(kg._valid_timestamp(value))
        for value in ("2026-02-29T00:00:00Z", "2026-04-31T00:00:00Z", "0000-01-01T00:00:00Z"):
            with self.subTest(invalid=value):
                self.assertFalse(kg._valid_timestamp(value))

        text = document("TS", "### CLM-TS\n\nTimestamp.").replace(
            "2026-08-08T02:00:00+08:00", "2026-08-08T02:00:00.5+08:00"
        )
        graph, record = self._single(text)
        self.assertTrue(
            any(
                t.subject == record["revision_iri"]
                and t.predicate == kg.DCTERMS + "modified"
                and t.datatype == kg.XSD + "dateTimeStamp"
                for t in graph.triples
            )
        )
        self.assertNotIn("invalid_timestamp", _rules(graph))

    def test_basic_fixture_output_is_pinned_across_python_versions(self) -> None:
        """Any interpreter (3.9+) must mint exactly these bytes for the fixture.

        Update the digests only for an intentional change of the mapping or
        of the fixture files.
        """

        graph = load(BASIC)
        self.assertEqual(
            "64738eb9e48bc818e8c387d22f737f8e42dfb979b6a8304b443c6ab405444fd5",
            graph.graph_input_sha256,
        )
        self.assertEqual(
            PINNED_BASIC_NTRIPLES_SHA256,
            hashlib.sha256(graph.to_ntriples().encode("utf-8")).hexdigest(),
        )
        quality = load(FIXTURES / "quality")
        self.assertEqual(
            PINNED_QUALITY_FINDING_IDS,
            sorted(item["finding_id"] for item in quality.observations),
        )


PINNED_BASIC_NTRIPLES_SHA256 = (
    "9a057f8b99d4e60f8c0248909a0989ed4e7f4227cb1a1e3c18031d70758c5f59"
)
# Finding ids hash rule, subject and detail only, so they match earlier releases.
PINNED_QUALITY_FINDING_IDS = [
    "OBS-KG262-0D50A683CC688D09C8C7",
    "OBS-KG262-5BA1F9476277ABAD9F6B",
    "OBS-KG262-5ED6162C0C048D6E2681",
    "OBS-KG262-6C88B215DB3CEB8BBD2A",
    "OBS-KG262-F9F03E8E415B6AFB593F",
]


if __name__ == "__main__":
    unittest.main()
