"""okf_graph_cli.py: build / lookup / quality, exit codes and error reporting."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import okf_graph_cli as cli
from tests.helpers import BASE_IRI, BASIC, EXTRA_ROOT, FIXTURES, load


def run(*argv: str):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class TestBuild(unittest.TestCase):
    def test_build_prints_ntriples_and_a_summary(self) -> None:
        code, out, err = run("build", str(BASIC))
        self.assertEqual(0, code)
        self.assertEqual(load(BASIC).to_ntriples(), out)
        self.assertIn("3 documents, 3 claims, 93 triples, 0 findings", err)

    def test_build_writes_out_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-cli-out-") as tmp:
            target = Path(tmp) / "graph.nt"
            code, out, err = run("build", str(BASIC), "--out", str(target))
            self.assertEqual(0, code)
            self.assertEqual("", out)
            self.assertEqual(load(BASIC).to_ntriples(), target.read_bytes().decode("utf-8"))
            self.assertIn(str(target), err)

    def test_build_json_exports_the_whole_projection(self) -> None:
        code, out, _ = run("build", str(BASIC), "--format", "json")
        self.assertEqual(0, code)
        payload = json.loads(out)
        graph = load(BASIC)
        self.assertEqual("okf-docgraph-export-v0.5", payload["schema"])
        self.assertEqual(graph.to_receipt(), payload["receipt"])
        self.assertEqual(graph.graph_input, payload["graph_input"])
        self.assertEqual(sorted(graph.documents), sorted(payload["documents"]))
        self.assertEqual(sorted(graph.claims), sorted(payload["claims"]))
        self.assertEqual(len(graph.triples), len(payload["triples"]))
        self.assertEqual(
            {"subject", "predicate", "object", "object_kind", "datatype", "language"},
            set(payload["triples"][0]),
        )

    def test_explicit_files_and_base_iri_options(self) -> None:
        code, out, _ = run(
            "build", str(BASIC), "--format", "json",
            "--file", "requirements/source.md",
            "--base-iri", "https://example.invalid/kb",
        )
        self.assertEqual(0, code)
        payload = json.loads(out)
        self.assertEqual(["product.current:REQ-001@1"], list(payload["documents"]))
        self.assertEqual("files", payload["graph_input"]["selection"])
        self.assertTrue(payload["receipt"]["graph_iri"].startswith("https://example.invalid/kb/graph/"))


class TestLookup(unittest.TestCase):
    def test_lookup_by_reference_shows_edges_and_evidence(self) -> None:
        code, out, _ = run("lookup", str(BASIC), "product.current:REQ-001@1#CLM-REQ-001-01")
        self.assertEqual(0, code)
        self.assertIn("by reference", out)
        self.assertIn("* claim product.current:REQ-001@1#CLM-REQ-001-01", out)
        self.assertIn("-> HAS_AC product.current:AC-001@1#CLM-AC-001-01", out)
        self.assertIn("evidence: product.current:EVD-001@1#CLM-EVD-001-01", out)

    def test_lookup_by_iri_and_by_label(self) -> None:
        iri = BASE_IRI + "/resource/product.current/REQ-001/revision/1"
        code, out, _ = run("lookup", str(BASIC), iri)
        self.assertEqual(0, code)
        self.assertIn("by iri", out)
        self.assertIn("* document product.current:REQ-001@1", out)

        code, out, _ = run("lookup", str(BASIC), "cited answer")
        self.assertEqual(0, code)
        self.assertIn("by text", out)
        self.assertIn("* product.current:REQ-001@1  (requirements/source.md)", out)

    def test_lookup_json_and_no_match_exit_code(self) -> None:
        code, out, _ = run("lookup", str(BASIC), "product.current:AC-001@1", "--json")
        self.assertEqual(0, code)
        receipt = json.loads(out)
        self.assertEqual(("lookup", "reference", 1), (
            receipt["query_kind"], receipt["lookup_mode"], receipt["match_count"]
        ))

        code, out, _ = run("lookup", str(BASIC), "no such label anywhere")
        self.assertEqual(1, code)
        self.assertIn("0 match(es)", out)


class TestQuality(unittest.TestCase):
    def test_quality_lists_findings_and_still_exits_zero(self) -> None:
        code, out, _ = run("quality", str(FIXTURES / "quality"))
        self.assertEqual(0, code)
        self.assertIn("5 finding(s)", out)
        self.assertIn("Observe-only", out)
        for rule in (
            "conflict_candidate",
            "dangling_or_mismatched_target",
            "duplicate_map_member",
            "invalid_timestamp",
            "member_identity_mismatch",
        ):
            self.assertIn(rule, out)

    def test_quality_without_findings_does_not_claim_a_pass(self) -> None:
        code, out, _ = run("quality", str(BASIC))
        self.assertEqual(0, code)
        self.assertIn("0 finding(s)", out)
        self.assertIn("not a pass verdict", out)

    def test_quality_json_is_the_observe_receipt(self) -> None:
        code, out, _ = run("quality", str(FIXTURES / "quality"), "--json")
        self.assertEqual(0, code)
        receipt = json.loads(out)
        self.assertEqual("observe", receipt["query_kind"])
        self.assertEqual("record", receipt["current_action"])
        self.assertEqual(5, receipt["match_count"])


class TestErrors(unittest.TestCase):
    def test_input_errors_exit_two_with_a_stable_code(self) -> None:
        cases = (
            (("quality", str(FIXTURES / "unsafe"), "--map", "escape-map.md"), "E_KG262_PATH_ESCAPE"),
            (("build", str(FIXTURES / "unsafe"), "--map", "network-map.md"), "E_KG262_NETWORK_FORBIDDEN"),
            (("build", str(BASIC), "--base-iri", "http://insecure.invalid"), "E_KG262_INVALID_BASE_IRI"),
            (("lookup", str(BASIC / "missing-dir"), "x"), "E_KG262_PATH_ESCAPE"),
            (("build", str(BASIC), "--map", "missing-map.md"), "E_KG262_ENTRY_MAP_MISSING"),
        )
        for argv, code_text in cases:
            with self.subTest(argv=argv):
                code, out, err = run(*argv)
                self.assertEqual(2, code)
                self.assertEqual("", out)
                self.assertIn(code_text, err)

    def test_unwritable_out_file_is_an_input_error(self) -> None:
        code, _, err = run("build", str(BASIC), "--out", str(BASIC / "no-such-dir" / "g.nt"))
        self.assertEqual(2, code)
        self.assertIn("error:", err)

    def test_usage_errors_exit_two(self) -> None:
        stderr = io.StringIO()
        for argv in (
            ["build", str(BASIC), "--map", "knowledge-map.md", "--file", "orphan.md"],
            ["build", str(BASIC), "--format", "turtle"],
            [],
        ):
            with self.subTest(argv=argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as caught:
                    cli.main(argv)
                self.assertEqual(2, caught.exception.code)


class TestScript(unittest.TestCase):
    def test_script_runs_from_any_directory_in_isolated_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="okfg-cli-cwd-") as tmp:
            result = subprocess.run(
                [sys.executable, "-I", str(EXTRA_ROOT / "okf_graph_cli.py"), "quality", str(BASIC)],
                cwd=tmp,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", "replace"))
        self.assertIn(b"0 finding(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
