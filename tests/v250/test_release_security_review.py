from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v250 import release_flow


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts/checks/run-v250-release-security-review.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("_test_v250_security_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
    )
    return result.stdout.strip()


class TestV250ReleaseSecurityReview(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = load_runner()
        self.manifest = json.loads((ROOT / self.runner.CONTRACT_PATH).read_text(encoding="utf-8"))
        self.targets = self.runner._validate_manifest(self.manifest)
        self.texts = {
            target["path"]: (ROOT / target["path"]).read_text(encoding="utf-8")
            for target in self.targets
        }

    def test_current_dangerous_secret_command_and_workflow_surfaces_are_green(self) -> None:
        dangerous = self.runner._evaluate_dangerous_operations(self.texts, self.manifest)
        secrets = self.runner._scan_secrets(self.texts)
        commands = self.runner._scan_command_boundaries(self.targets, self.texts)
        workflows, ssh = self.runner._scan_workflows_and_ssh(self.texts)

        self.assertTrue(dangerous["passed"], dangerous["findings"])
        self.assertGreater(dangerous["observed_count"], 0)
        self.assertEqual(dangerous["observed_count"], dangerous["allowed_count"])
        self.assertTrue(secrets["passed"], secrets["findings"])
        self.assertTrue(commands["passed"], commands["findings"])
        self.assertGreater(commands["subprocess_call_count"], 0)
        self.assertTrue(workflows["passed"], workflows["findings"])
        self.assertTrue(ssh["passed"], ssh["findings"])

    def test_contract_unchanged_destructive_mutation_is_not_allowlisted(self) -> None:
        mutated = dict(self.texts)
        mutated["scripts/v250/s4_executor.py"] += "\nshutil.rmtree(ROOT)\n"
        verdict = self.runner._evaluate_dangerous_operations(mutated, self.manifest)
        self.assertFalse(verdict["passed"])
        self.assertEqual(1, len([item for item in verdict["findings"] if item["rule_id"] == "unknown_dangerous_operation"]))

    def test_every_new_child_process_api_fails_closed(self) -> None:
        for api in ("call", "check_call", "check_output"):
            with self.subTest(api=api):
                mutated = dict(self.texts)
                mutated["scripts/checks/check-v250.py"] += (
                    f"\ndef injected_child():\n    subprocess.{api}(['id'])\n"
                )
                dangerous = self.runner._evaluate_dangerous_operations(
                    mutated, self.manifest
                )
                commands = self.runner._scan_command_boundaries(
                    self.targets, mutated
                )
                self.assertFalse(dangerous["passed"])
                self.assertFalse(commands["passed"])
                self.assertIn(
                    "unallowlisted_child_process_api",
                    {item["rule_id"] for item in commands["findings"]},
                )

        aliased = dict(self.texts)
        aliased["scripts/checks/check-v250.py"] += (
            "\nfrom subprocess import check_output as injected_child\n"
            "injected_child(['id'])\n"
        )
        alias_danger = self.runner._evaluate_dangerous_operations(
            aliased, self.manifest
        )
        alias_verdict = self.runner._scan_command_boundaries(self.targets, aliased)
        self.assertFalse(alias_danger["passed"])
        self.assertFalse(alias_verdict["passed"])

    def test_allowed_api_aliases_still_create_unknown_callsite_fingerprints(self) -> None:
        mutations = (
            "\nimport subprocess as injected_sp\ninjected_sp.run(['id'])\n",
            "\nfrom subprocess import run as injected_run\ninjected_run(['id'])\n",
        )
        unknown_fingerprints = []
        for mutation in mutations:
            mutated = dict(self.texts)
            mutated["scripts/checks/check-v250.py"] += mutation
            dangerous = self.runner._evaluate_dangerous_operations(
                mutated, self.manifest
            )
            commands = self.runner._scan_command_boundaries(self.targets, mutated)
            self.assertFalse(dangerous["passed"])
            self.assertTrue(commands["passed"], commands["findings"])
            unknown = [
                item["callsite_fingerprint"]
                for item in dangerous["findings"]
                if item["rule_id"] == "unknown_dangerous_operation"
            ]
            self.assertEqual(1, len(unknown))
            unknown_fingerprints.extend(unknown)
        self.assertEqual(2, len(set(unknown_fingerprints)))

    def test_committed_module_and_from_import_alias_mutations_fail_review(self) -> None:
        mutations = (
            "\nimport subprocess as injected_sp\ninjected_sp.run(['id'])\n",
            "\nfrom subprocess import run as injected_run\ninjected_run(['id'])\n",
        )
        observed_unknowns = []
        for index, mutation in enumerate(mutations, start=1):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for target in self.targets:
                    source = ROOT / target["path"]
                    destination = root / target["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                git(root, "init", "-q")
                git(root, "config", "user.name", "Security Test")
                git(root, "config", "user.email", "security@example.invalid")
                git(root, "add", ".")
                git(root, "commit", "-qm", "exact review fixture")
                target = root / "scripts/checks/check-v250.py"
                target.write_text(
                    target.read_text(encoding="utf-8") + mutation,
                    encoding="utf-8",
                )
                git(root, "add", "scripts/checks/check-v250.py")
                git(root, "commit", "-qm", f"alias mutation {index}")
                commit = git(root, "rev-parse", "HEAD")
                tree = git(root, "rev-parse", "HEAD^{tree}")
                receipt = self.runner.run_review(
                    source_commit=commit,
                    source_tree=tree,
                    reviewer_id="fixture-security-reviewer",
                    review_run_id=f"SECURITY-ALIAS-MUTATION-{index}",
                    orchestrator_pid=os.getpid() + 100000,
                    root=root,
                )
                self.assertEqual("failed", receipt["check_state"])
                unknown = [
                    finding["callsite_fingerprint"]
                    for finding in receipt["findings"]
                    if finding["rule_id"] == "unknown_dangerous_operation"
                ]
                self.assertEqual(1, len(unknown))
                observed_unknowns.extend(unknown)
        self.assertEqual(2, len(set(observed_unknowns)))

    def test_secret_scan_ignores_workflow_reference_but_detects_literal(self) -> None:
        workflow_reference = "CHECKOUT_SSH_KEY: ${{ secrets.GOAL_TEAMS_CHECKOUT_SSH_KEY }}\n"
        clean = self.runner._scan_secrets({"workflow.yml": workflow_reference})
        self.assertTrue(clean["passed"], clean["findings"])

        leaked = self.runner._scan_secrets(
            {"implementation.py": 'GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz123456"\n'}
        )
        self.assertFalse(leaked["passed"])
        self.assertEqual("github_classic_token", leaked["findings"][0]["rule_id"])
        self.assertNotIn("ghp_", json.dumps(leaked))

    def test_undeclared_dependency_manifest_fails_closed(self) -> None:
        for dependency_path in ("pyproject.toml", "setup.py", "setup.cfg", "package.json"):
            with self.subTest(dependency_path=dependency_path):
                tree = {dependency_path: {"type": "blob"}}
                verdict = self.runner._scan_dependencies(
                    tree_entries=tree,
                    targets=[],
                    texts={},
                    manifest={"declared_dependency_files": [], "allowed_external_python_imports": []},
                )
                self.assertFalse(verdict["passed"])
                self.assertEqual("dependency_manifest_denominator_drift", verdict["findings"][0]["rule_id"])

    def test_job_level_reusable_workflow_must_use_full_sha(self) -> None:
        workflow = {
            ".github/workflows/reusable.yml": (
                "jobs:\n"
                "  delegated:\n"
                "    uses: example/repository/.github/workflows/reuse.yml@main\n"
            )
        }
        actions, _ = self.runner._scan_workflows_and_ssh(workflow)
        self.assertFalse(actions["passed"])
        self.assertEqual("job", actions["action_pins"][0]["scope"])
        self.assertIn(
            "workflow_action_not_pinned",
            {finding["rule_id"] for finding in actions["findings"]},
        )

    def test_symlink_and_parent_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, "init", "-q")
            git(root, "config", "user.name", "Security Test")
            git(root, "config", "user.email", "security@example.invalid")
            (root / "review.py").write_text("print('safe')\n", encoding="utf-8")
            git(root, "add", "review.py")
            git(root, "commit", "-qm", "fixture")
            commit = git(root, "rev-parse", "HEAD")
            entries = self.runner._ls_tree(root, commit)
            (root / "review.py").unlink()
            (root / "review.py").symlink_to("outside.py")
            with self.assertRaisesRegex(self.runner.SecurityReviewError, "E_V250_SECURITY_TARGET_SYMLINK"):
                self.runner._frozen_file(root, commit, entries, "review.py")
        with self.assertRaisesRegex(self.runner.SecurityReviewError, "E_V250_SECURITY_DENOMINATOR_PATH"):
            self.runner._safe_path("../outside")

    def test_exact_clean_repo_passes_then_committed_mutation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target in self.targets:
                source = ROOT / target["path"]
                destination = root / target["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            git(root, "init", "-q")
            git(root, "config", "user.name", "Security Test")
            git(root, "config", "user.email", "security@example.invalid")
            git(root, "add", ".")
            git(root, "commit", "-qm", "exact review fixture")
            commit = git(root, "rev-parse", "HEAD")
            tree = git(root, "rev-parse", "HEAD^{tree}")

            receipt = self.runner.run_review(
                source_commit=commit,
                source_tree=tree,
                reviewer_id="fixture-security-reviewer",
                review_run_id="SECURITY-FIXTURE-GREEN",
                orchestrator_pid=os.getpid() + 100000,
                root=root,
            )
            self.assertEqual("passed", receipt["check_state"], receipt["findings"])
            self.assertEqual(len(self.targets), receipt["review_denominator"]["target_count"])
            self.assertEqual(0, receipt["finding_count"])
            with mock.patch.object(release_flow, "REPO_ROOT", root):
                self.assertEqual(
                    [],
                    release_flow._validate_security_review_receipt(
                        receipt, commit, tree
                    ),
                )

            s4 = root / "scripts/v250/s4_executor.py"
            s4.write_text(s4.read_text(encoding="utf-8") + "\nshutil.rmtree(ROOT)\n", encoding="utf-8")
            git(root, "add", "scripts/v250/s4_executor.py")
            git(root, "commit", "-qm", "mutate implementation only")
            mutated_commit = git(root, "rev-parse", "HEAD")
            mutated_tree = git(root, "rev-parse", "HEAD^{tree}")
            failed = self.runner.run_review(
                source_commit=mutated_commit,
                source_tree=mutated_tree,
                reviewer_id="fixture-security-reviewer",
                review_run_id="SECURITY-FIXTURE-MUTATED",
                orchestrator_pid=os.getpid() + 100000,
                root=root,
            )
            self.assertEqual("failed", failed["check_state"])
            self.assertIn(
                "unknown_dangerous_operation",
                {finding["rule_id"] for finding in failed["findings"]},
            )


if __name__ == "__main__":
    unittest.main()
