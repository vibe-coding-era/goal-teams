from __future__ import annotations

import importlib.util
import argparse
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.v250 import release_flow


ROOT = Path(__file__).resolve().parents[2]


def load_checker():
    path = ROOT / "scripts/checks/check-v250.py"
    spec = importlib.util.spec_from_file_location("_test_v250_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV250ReleaseChecker(unittest.TestCase):
    def test_release_cli_accepts_portable_runtime_receipt_inputs(self) -> None:
        checker = load_checker()
        argv = [
            "check-v250.py",
            "--phase",
            "release",
            "--route-facts-receipt",
            "downloaded/release-route-facts.json",
            "--derived-route-receipt",
            "downloaded/release-route-derived.json",
            "--route-receipt",
            "downloaded/release-route-receipt.json",
            "--authorization-receipt",
            "downloaded/authorization.json",
        ]

        with mock.patch.object(checker.sys, "argv", argv):
            args = checker.parse_args()

        self.assertEqual(
            Path("downloaded/release-route-facts.json"),
            args.route_facts_receipt,
        )
        self.assertEqual(
            Path("downloaded/release-route-derived.json"),
            args.derived_route_receipt,
        )
        self.assertEqual(
            Path("downloaded/release-route-receipt.json"),
            args.route_receipt,
        )
        self.assertEqual(
            Path("downloaded/authorization.json"),
            args.authorization_receipt,
        )

    def test_release_checker_forwards_portable_runtime_receipt_inputs(self) -> None:
        checker = load_checker()
        receipt_paths = {
            "route_facts_receipt": Path("downloaded/release-route-facts.json"),
            "derived_route_receipt": Path("downloaded/release-route-derived.json"),
            "route_receipt": Path("downloaded/release-route-receipt.json"),
            "authorization_receipt": Path("downloaded/authorization.json"),
        }
        args = argparse.Namespace(
            phase="release",
            project_size="medium",
            stage="released",
            release_intent=True,
            implementation_scope_complete=True,
            s1_current=False,
            source_commit="1" * 40,
            source_tree="2" * 40,
            released_runtime_receipt=Path("downloaded/released-runtime-transition.json"),
            expected_host_execution_id="host-run-263",
            **receipt_paths,
        )
        validate_transition = mock.Mock(return_value={"may_enter_s0": False})
        runtime_transition = SimpleNamespace(validate_transition=validate_transition)
        release_flow_module = SimpleNamespace(
            canonical_sha256=lambda _value: "f" * 64,
            derive_release_plan=lambda route: {"route": route},
        )
        output = io.StringIO()

        with mock.patch.object(checker, "parse_args", return_value=args), mock.patch.object(
            checker, "validate_contracts", return_value={"passed": True}
        ), mock.patch.object(
            checker,
            "_load_module",
            side_effect=[release_flow_module, runtime_transition],
        ), mock.patch.object(
            checker,
            "_released_identity",
            return_value=(args.source_commit, args.source_tree, {}),
        ), mock.patch.object(
            checker, "_read_json", return_value={"receipt": "runtime"}
        ), redirect_stdout(output):
            self.assertEqual(1, checker.main())

        validate_transition.assert_called_once_with(
            {"receipt": "runtime"},
            expected_stage="released",
            allow_release=True,
            expected_source_commit=args.source_commit,
            expected_source_tree=args.source_tree,
            expected_project_size="medium",
            expected_host_execution_id="host-run-263",
            route_facts_receipt_path_override=receipt_paths[
                "route_facts_receipt"
            ].resolve(),
            derived_route_receipt_path_override=receipt_paths[
                "derived_route_receipt"
            ].resolve(),
            route_receipt_path_override=receipt_paths["route_receipt"].resolve(),
            authorization_receipt_path_override=receipt_paths[
                "authorization_receipt"
            ].resolve(),
            root=checker.ROOT,
        )

    def test_command_count_includes_each_git_child_process(self) -> None:
        checker = load_checker()
        checker._COMMAND_EXECUTION_COUNT = 0
        completed = subprocess.CompletedProcess(
            ["git", "status"], 0, stdout="", stderr=""
        )
        with mock.patch.object(checker.subprocess, "run", return_value=completed):
            checker._git_run("status", "--porcelain=v1")
            checker._git_run("rev-parse", "HEAD")
        self.assertEqual(2, checker._COMMAND_EXECUTION_COUNT)

    def test_release_failure_before_child_process_reports_zero_commands(self) -> None:
        checker = load_checker()
        args = argparse.Namespace(
            phase="release",
            project_size="large",
            stage="released",
            release_intent=True,
            implementation_scope_complete=True,
            s1_current=False,
            source_commit="1" * 40,
            source_tree="2" * 40,
            released_runtime_receipt=Path("missing.json"),
        )
        output = io.StringIO()
        with mock.patch.object(checker, "parse_args", return_value=args), mock.patch.object(
            checker, "_released_identity", side_effect=ValueError("E_TEST_EARLY")
        ), redirect_stdout(output):
            self.assertEqual(1, checker.main())
        payload = json.loads(output.getvalue())
        self.assertEqual(0, payload["command_execution_count"])

    def test_release_identity_rejects_dirty_worktree(self) -> None:
        checker = load_checker()
        commit = "1" * 40
        tree = "2" * 40

        def git_text(*args: str) -> str:
            if args == ("rev-parse", "--show-toplevel"):
                return str(checker.ROOT)
            if args == ("rev-parse", "HEAD^{commit}"):
                return commit
            if args == ("rev-parse", f"{commit}^{{tree}}"):
                return tree
            raise AssertionError(args)

        dirty = subprocess.CompletedProcess(
            ["git"], 0, stdout=" M scripts/checks/check-v250.py\n", stderr=""
        )
        with mock.patch.object(checker, "_git_text", side_effect=git_text), mock.patch.object(
            checker, "_git_run", return_value=dirty
        ):
            with self.assertRaisesRegex(ValueError, "E_V250_RELEASE_WORKTREE_DIRTY"):
                checker._released_identity(commit, tree)

    def test_current_denominator_binds_every_exact_current_test_file(self) -> None:
        checker = load_checker()
        commit = "1" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests/v250").mkdir(parents=True)
            (root / "tests/v263").mkdir(parents=True)
            (root / "tests/v265").mkdir(parents=True)
            files = {
                "tests/v250/test_a.py": b"import unittest\n",
                "tests/v250/test_b.py": b"import unittest\n",
                "tests/v263/test_c.py": b"import unittest\n",
                "tests/v265/test_d.py": b"import unittest\n",
            }
            for relative, data in files.items():
                (root / relative).write_bytes(data)
            with mock.patch.object(checker, "ROOT", root), mock.patch.object(
                checker,
                "_git_text",
                return_value="\n".join(sorted(files)),
            ), mock.patch.object(
                checker,
                "_git_bytes",
                side_effect=lambda *args: files[args[-1].split(":", 1)[1]],
            ):
                denominator = checker._current_test_denominator(
                    commit,
                    observed_test_count=7,
                    release_flow=release_flow,
                )
        self.assertEqual(3, denominator["test_file_count"])
        self.assertEqual(7, denominator["test_case_count"])
        self.assertEqual(
            ["tests/v250", "tests/v265"],
            denominator["test_roots"],
        )
        self.assertEqual(
            ["tests/v263"], denominator["published_predecessor_test_roots"]
        )
        self.assertEqual(0, denominator["predecessor_test_invocation_limit"])
        self.assertEqual(
            ["tests/v23", "tests/v249", "tests/v26"],
            denominator["legacy_roots_excluded"],
        )
        self.assertEqual(
            release_flow.canonical_sha256(denominator["test_files"]),
            denominator["test_file_set_sha256"],
        )

    def test_security_review_is_a_fresh_correlated_process(self) -> None:
        checker = load_checker()
        counter = {"count": 0}
        def child_result(argv, **kwargs):
            kwargs["command_counter"]["count"] += 1
            review_run_id = argv[argv.index("--review-run-id") + 1]
            orchestrator_pid = int(argv[argv.index("--orchestrator-pid") + 1])
            receipt = {
                "gate_id": "release_security_review",
                "review_run_id": review_run_id,
                "check_state": "passed",
                "fresh_separate_process": True,
                "runner_pid": orchestrator_pid + 1,
                "orchestrator_pid": orchestrator_pid,
                "actor_assurance": "I1",
                "actor_relationship": "correlated",
                "external_independence": False,
                "reviewer_identity": {"reviewer_id": "implementation-security-reviewer"},
            }
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(receipt), stderr="")

        with mock.patch.object(checker, "_run_subprocess", side_effect=child_result) as run:
            receipt = checker.run_release_security_review(
                "1" * 40, "2" * 40, command_counter=counter
            )
        self.assertEqual(1, counter["count"])
        run.assert_called_once()
        self.assertEqual("passed", receipt["check_state"])
        self.assertTrue(receipt["fresh_separate_process"])
        self.assertNotEqual(receipt["runner_pid"], receipt["orchestrator_pid"])
        self.assertEqual("I1", receipt["actor_assurance"])
        self.assertEqual("correlated", receipt["actor_relationship"])
        self.assertFalse(receipt["external_independence"])
        self.assertIn("reviewer_identity", receipt)
        self.assertIn("review_run_id", receipt)


if __name__ == "__main__":
    unittest.main()
