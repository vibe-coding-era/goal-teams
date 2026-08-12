from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v250 import repository_boundary
from scripts.v250.repository_boundary import (
    build_boundary_receipt,
    validate_boundary_receipt,
)
from scripts.release.release_config import release_config


ROOT = Path(__file__).resolve().parents[2]
CHECKOUT = "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5"
SOURCE = "1" * 40
TREE = "2" * 40
DIGEST = "a" * 64


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def boundary_receipt(*, receipt_mode: str, reused_receipt_sha256: str | None = None) -> dict:
    commands = [
        ["python3", "scripts/checks/check-workspace-boundaries.py"],
        ["python3", "scripts/checks/check-package-manifest.py"],
        ["python3", "scripts/release/validate-release.py"],
    ]
    return build_boundary_receipt(
        source_commit=SOURCE,
        source_tree=TREE,
        asset_set_id="ASSET-V250",
        asset_set_digest=DIGEST,
        package_manifest_digest="b" * 64,
        validator_digest="c" * 64,
        argv=commands,
        cwd=".",
        check_state="passed",
        run_outcome="passed",
        receipt_mode=receipt_mode,
        reused_receipt_sha256=reused_receipt_sha256,
        frozen_source_revalidation={
            "check_state": "passed",
            "revalidated_now": True,
            "head_commit": SOURCE,
            "head_tree": TREE,
            "status_porcelain_sha256": __import__("hashlib").sha256(b"").hexdigest(),
            "dirty_entry_count": 0,
            "untracked_entry_count": 0,
        },
        command_receipts=[
            {"argv": argv, "returncode": 0, "output_sha256": str(index) * 64}
            for index, argv in enumerate(commands, start=1)
        ],
        s2_receipt_sha256="d" * 64,
    )


class TestWorkflowSSHContract(unittest.TestCase):
    def test_every_checkout_fails_closed_without_secret_and_uses_ssh(self) -> None:
        check = text(".github/workflows/check.yml")
        release = text(".github/workflows/release-gate.yml")
        combined = check + "\n" + release

        self.assertEqual(3, combined.count(f"uses: {CHECKOUT}"))
        self.assertEqual(
            3,
            combined.count("CHECKOUT_SSH_KEY: ${{ secrets.GOAL_TEAMS_CHECKOUT_SSH_KEY }}"),
        )
        self.assertEqual(
            3,
            combined.count("ssh-key: ${{ secrets.GOAL_TEAMS_CHECKOUT_SSH_KEY }}"),
        )
        self.assertEqual(3, combined.count("persist-credentials: false"))
        self.assertEqual(3, combined.count("fetch-depth: 0"))
        self.assertEqual(3, combined.count("E_V250_CHECKOUT_SSH_KEY_REQUIRED"))
        self.assertEqual(3, combined.count("Assert exact SSH fetch and push transport"))
        self.assertEqual(3, combined.count('expected="git@github.com:${GITHUB_REPOSITORY}.git"'))
        self.assertNotIn("https://github.com/${GITHUB_REPOSITORY}", combined)

    def test_full_history_and_pinned_draft_2020_validator_are_prepared_outside_worktree(
        self,
    ) -> None:
        combined = "\n".join(
            (
                text(".github/workflows/check.yml"),
                text(".github/workflows/release-gate.yml"),
            )
        )
        self.assertEqual(
            3,
            combined.count("Prepare pinned Draft 2020 validator outside the worktree"),
        )
        self.assertEqual(
            3,
            combined.count(
                "VALIDATOR_PYTHON_PREFIX: ${{ runner.temp }}/goal-teams-v250-python"
            ),
        )
        self.assertEqual(3, combined.count("jsonschema==4.23.0"))
        self.assertEqual(3, combined.count("--no-cache-dir"))
        self.assertEqual(
            3,
            combined.count("from jsonschema import Draft202012Validator"),
        )
        self.assertEqual(
            3,
            combined.count(
                'echo "PYTHONPATH=${VALIDATOR_PYTHON_PREFIX}${PYTHONPATH:+:${PYTHONPATH}}" >> "${GITHUB_ENV}"'
            ),
        )
        self.assertNotIn("node_modules", combined)
        self.assertNotIn("npm install", combined)
        self.assertNotIn("NODE_PATH", combined)

    def test_secret_guard_precedes_each_checkout_and_transport_assertion_follows(self) -> None:
        for path in (".github/workflows/check.yml", ".github/workflows/release-gate.yml"):
            workflow = text(path)
            cursor = 0
            while True:
                checkout = workflow.find(f"uses: {CHECKOUT}", cursor)
                if checkout < 0:
                    break
                guard = workflow.rfind("E_V250_CHECKOUT_SSH_KEY_REQUIRED", cursor, checkout)
                assertion = workflow.find("Assert exact SSH fetch and push transport", checkout)
                self.assertGreaterEqual(guard, cursor, path)
                self.assertGreater(assertion, checkout, path)
                cursor = assertion + 1


class TestReleaseWorkflowSequence(unittest.TestCase):
    def test_released_runtime_adapter_binds_external_handoff_and_fresh_child(self) -> None:
        workflow = text(".github/workflows/release-gate.yml")
        self.assertIn("Materialize the exact trusted Release route receipt", workflow)
        self.assertIn("derive_route(project_route_facts)", workflow)
        self.assertIn("compile_derived_route_closure", workflow)
        self.assertNotIn("compile_route_closure", workflow)
        self.assertIn("controller_handoff_receipt_json", workflow)
        self.assertIn(
            "Materialize the installed V2.62 host-issued V2.63 controller handoff",
            workflow,
        )
        self.assertNotIn("V2.63 host-signed controller handoff", workflow)
        self.assertIn("Verify the pinned GitHub owner public key before host launch", workflow)
        self.assertIn("https://api.github.com/users/vibe-coding-era/keys", workflow)
        self.assertIn("scripts/v250/runtime_host_adapter.py verify-github-key", workflow)
        adapter = workflow.index("scripts/v250/runtime_host_adapter.py launch")
        checker = workflow.index("python3 scripts/checks/check-v250.py", adapter)
        self.assertLess(adapter, checker)
        for option in (
            "--project-size \"${{ inputs.project_size }}\"",
            '--route-facts-receipt "${RUNNER_TEMP}/release-route-facts.json"',
            '--derived-route-receipt "${RUNNER_TEMP}/release-route-derived.json"',
            '--route-receipt "${RUNNER_TEMP}/release-route-receipt.json"',
            '--authorization-receipt "${RUNNER_TEMP}/authorization.json"',
            '--controller-handoff-receipt "${RUNNER_TEMP}/controller-handoff.json"',
            '--host-execution-id "${GITHUB_RUN_ID}"',
            "--adapter-identity github-actions-release-host-adapter",
            "--adapter-code scripts/v250/runtime_host_adapter.py",
        ):
            self.assertIn(option, workflow)
        for forbidden in (
            "--controller-version",
            "--previous-controller-version",
            "--loaded-runtime-version",
            "--previous-run-id",
            "--new-run-id",
            "GITHUB_RUN_ATTEMPT}:orchestrator",
            "GITHUB_RUN_ATTEMPT}:released-runtime",
        ):
            self.assertNotIn(forbidden, workflow)
        self.assertGreaterEqual(
            workflow.count("released-runtime-transition.json"),
            3,
        )
        self.assertIn('--expected-host-execution-id "${GITHUB_RUN_ID}"', workflow)

    def test_single_asset_set_flows_s2_boundary_s3_s4_without_rebuild(self) -> None:
        workflow = text(".github/workflows/release-gate.yml")
        build = workflow.index("Build the exact released asset set once")
        validate = workflow.index("Validate frozen-source integrity of the same built asset set")
        boundary = workflow.index("Run independent repository and same-asset boundary gate")
        pre_s3 = workflow.index("Revalidate frozen source and boundary before Large S3")
        s3 = workflow.index("Run Large-only isolated S3 install lifecycle once")
        pre_s4 = workflow.index("Revalidate frozen source and boundary before S4")
        s4 = workflow.index("Create the S4 authorized-operation plan without external writes")

        self.assertLess(build, validate)
        self.assertLess(validate, boundary)
        self.assertLess(boundary, pre_s3)
        self.assertLess(pre_s3, s3)
        self.assertLess(s3, pre_s4)
        self.assertLess(pre_s4, s4)
        self.assertEqual(1, workflow.count("scripts/release/build-release.py"))
        self.assertIn("--output-root release/versions", workflow)
        self.assertIn("--release-root release/versions", workflow)
        self.assertNotIn('${RUNNER_TEMP}/release"', workflow)
        self.assertIn("--reuse-receipt", workflow)
        self.assertIn("receipt_mode", text("scripts/v250/repository_boundary.py"))

    def test_large_s3_report_stays_inside_the_same_codex_home(self) -> None:
        workflow = text(".github/workflows/release-gate.yml")
        self.assertIn('CODEX_HOME="${RUNNER_TEMP}/codex-home"', workflow)
        self.assertIn(
            'INSTALL_REPORT="${RUNNER_TEMP}/codex-home/state/goal-teams/reports/s3-install-report.json"',
            workflow,
        )
        self.assertGreaterEqual(
            workflow.count(
                '${RUNNER_TEMP}/codex-home/state/goal-teams/reports/s3-install-report.json'
            ),
            2,
        )

    def test_same_release_root_and_receipts_are_persisted_for_s4_continuation(self) -> None:
        workflow = text(".github/workflows/release-gate.yml")
        upload = (
            "actions/upload-artifact@"
            "ea165f8d65b6e75b540449e92b4886f43607fa02"
        )
        self.assertEqual(2, workflow.count(upload))
        self.assertIn("name: goal-teams-v250-release-${{ github.sha }}", workflow)
        self.assertIn(
            "name: goal-teams-v250-diagnostic-${{ github.sha }}-"
            "${{ github.run_id }}-${{ github.run_attempt }}",
            workflow,
        )
        for relative in (
            "release/versions/V2.63/_artifacts/goal-teams-V2.63.tar.gz",
            "release/versions/V2.63/_artifacts/SHA256SUMS",
            "release/versions/V2.63/_release.json",
            "release/versions/V2.63/_files.sha256",
            "release/versions/V2.63/_receipts/",
        ):
            self.assertIn(relative, workflow)
        for receipt in (
            "release-route-facts.json",
            "release-route-derived.json",
            "release-route-receipt.json",
            "s1-check.json",
            "s2-build.json",
            "asset-validation.json",
            "repository-boundary.json",
            "s3.json",
            "release-control.json",
            "s4-authorized-operation-plan.json",
            "_checkpoint.json",
        ):
            self.assertIn(receipt, workflow)
        self.assertIn("if-no-files-found: error", workflow)
        self.assertEqual(1, workflow.count("scripts/release/build-release.py"))
        self.assertEqual(
            1,
            workflow.count(
                "if: always() && steps.release-version.outputs.release == 'true'"
            ),
        )
        self.assertIn("scripts/release/skill_release.py checkpoint", workflow)
        self.assertIn("scripts/release/skill_release.py verify-checkpoint", workflow)
        self.assertIn('> "${diagnostic_root}/checkpoint-output.json"', workflow)
        diagnostic_outputs = workflow[
            workflow.index("diagnostic_output_names=(") : workflow.index(
                "checkpoint_job_status=", workflow.index("diagnostic_output_names=(")
            )
        ]
        self.assertIn("s2-build.json", diagnostic_outputs)
        self.assertIn("asset-validation.json", diagnostic_outputs)
        self.assertNotIn('> "${diagnostic_root}/_checkpoint.json"', workflow)
        self.assertNotIn('"${diagnostic_root}/_checkpoint.json"', workflow)
        self.assertIn("steps.stage_receipts.outputs.checkpoint_state == 'ready_for_s4'", workflow)
        self.assertIn("path: release/versions/V2.63/_diagnostics/", workflow)
        self.assertIn('claim_scope', text("scripts/release/skill_release.py"))
        self.assertLess(
            workflow.index("Create the S4 authorized-operation plan without external writes"),
            workflow.index(upload),
        )

    def test_s4_workflow_uses_the_explicit_plan_only_command(self) -> None:
        workflow = text(".github/workflows/release-gate.yml")
        self.assertEqual(1, workflow.count("scripts/release/skill_release.py plan-s4"))
        self.assertNotIn("scripts/release/skill_release.py publish", workflow)
        self.assertIn(
            'plan.get("status") != "authorized_operation_plan_not_executed"',
            workflow,
        )
        self.assertIn('plan.get("publish_state") != "authorized_not_executed"', workflow)
        self.assertIn('plan.get("external_side_effect_count") != 0', workflow)
        self.assertEqual(
            1, workflow.count('for key in ("command", "status", "error_code")')
        )
        self.assertIn(
            'report_failure "${RUNNER_TEMP}/preflight-output.json"', workflow
        )
        self.assertIn(
            'report_failure "${RUNNER_TEMP}/plan-output.json"',
            workflow,
        )
        self.assertIn(
            'cp "${RUNNER_TEMP}/preflight-output.json" '
            '"${RUNNER_TEMP}/release-control.json"',
            workflow,
        )
        self.assertIn(
            'cp "${RUNNER_TEMP}/plan-output.json" '
            '"${RUNNER_TEMP}/s4-authorized-operation-plan.json"',
            workflow,
        )
        self.assertLess(
            workflow.index('raise SystemExit("E_V250_WORKFLOW_PLAN_ONLY_ASSERTION")'),
            workflow.index(
                'cp "${RUNNER_TEMP}/preflight-output.json" '
                '"${RUNNER_TEMP}/release-control.json"'
            ),
        )
        self.assertIn(
            '--release-control-receipt "${RUNNER_TEMP}/preflight-output.json"',
            workflow,
        )
        self.assertNotIn('cat "${RUNNER_TEMP}/preflight-output.json"', workflow)

    def test_release_order_is_consistent_in_owner_projections(self) -> None:
        skill = text("SKILL.md")
        self.assertIn(
            "S2 single package → repository boundary compliance → S3 Large-only install lifecycle → S4 publish/readback",
            skill,
        )
        command = json.loads(
            text(
                "references/current/generations/V2.63/contracts/release-command-manifest.json"
            )
        )
        chain = command["release"]["s4"]["required_receipt_chain"]
        self.assertLess(chain.index("s2"), chain.index("repository_boundary"))
        self.assertLess(chain.index("repository_boundary"), chain.index("s3"))
        self.assertEqual("release/versions", command["release"]["s2"]["output_root"])
        self.assertEqual(
            "authorized_operation_plan_only",
            command["release"]["s4"]["workflow_effect"],
        )
        continuation = command["release"]["s4"]["continuation_artifact"]
        self.assertEqual("release/versions/V2.63", continuation["release_root"])
        self.assertEqual(4, continuation["public_asset_count"])
        self.assertEqual(0, continuation["downstream_rebuild_invocation_limit"])

        profile = json.loads(text("references/release-profiles/v2.63.json"))
        gates = profile["release_gates"]
        self.assertLess(gates.index("single_build"), gates.index("repository_boundary_compliance"))
        self.assertLess(gates.index("repository_boundary_compliance"), gates.index("large_release_install"))
        self.assertIn("release_versions", profile["s2_policy"])
        self.assertFalse(profile["external_writes_allowed"])

    def test_v250_profile_loader_accepts_the_boundary_before_s3_projection(self) -> None:
        profile = release_config("V2.63")
        gates = profile["release_gates"]
        self.assertLess(gates.index("single_build"), gates.index("repository_boundary_compliance"))
        self.assertLess(gates.index("repository_boundary_compliance"), gates.index("large_release_install"))
        self.assertEqual(
            "single_build_release_versions_no_reproducibility_or_security",
            profile["s2_policy"],
        )
        self.assertEqual(
            "large_release_only_after_current_s1_and_repository_boundary",
            profile["s3_policy"],
        )


class TestBoundaryReceiptMode(unittest.TestCase):
    def test_live_source_observation_requires_exact_head_tree_and_clean_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Goal Teams Test"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=root,
                check=True,
            )
            tracked = root / "tracked.txt"
            tracked.write_text("frozen\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixture"],
                cwd=root,
                check=True,
            )
            source = subprocess.run(
                ["git", "rev-parse", "HEAD^{commit}"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            tree = subprocess.run(
                ["git", "rev-parse", "HEAD^{tree}"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            clean = repository_boundary.observe_frozen_source(
                source,
                tree,
                repository_root=root,
            )
            self.assertEqual("passed", clean["check_state"])
            self.assertEqual(0, clean["dirty_entry_count"])
            self.assertEqual(0, clean["untracked_entry_count"])

            tracked.write_text("staged drift\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            with self.assertRaisesRegex(
                ValueError,
                "E_V250_REPOSITORY_BOUNDARY_SOURCE_NOT_FROZEN",
            ):
                repository_boundary.observe_frozen_source(
                    source,
                    tree,
                    repository_root=root,
                )

    def test_boundary_accepts_only_the_repository_release_versions_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "release/versions"
            (expected / "V2.63").mkdir(parents=True)
            alternate = root / "alternate"
            (alternate / "V2.63").mkdir(parents=True)
            with mock.patch.object(repository_boundary, "ROOT", root):
                self.assertEqual(
                    (expected / "V2.63").resolve(),
                    repository_boundary.resolve_release_directory(expected),
                )
                with self.assertRaisesRegex(
                    ValueError, "E_V250_REPOSITORY_BOUNDARY_RELEASE_ROOT"
                ):
                    repository_boundary.resolve_release_directory(alternate)

    def test_executed_and_reused_receipts_are_distinct_and_current(self) -> None:
        executed = boundary_receipt(receipt_mode="executed_now")
        reused = boundary_receipt(
            receipt_mode="reused_receipt",
            reused_receipt_sha256=executed["receipt_sha256"],
        )
        self.assertEqual("executed_now", executed["receipt_mode"])
        self.assertIsNone(executed["reused_receipt_sha256"])
        self.assertEqual("reused_receipt", reused["receipt_mode"])
        self.assertEqual(executed["receipt_sha256"], reused["reused_receipt_sha256"])
        self.assertTrue(reused["frozen_source_revalidation"]["revalidated_now"])

        commands = reused["argv"]
        verdict = validate_boundary_receipt(
            reused,
            source_commit=SOURCE,
            source_tree=TREE,
            asset_set_id="ASSET-V250",
            asset_set_digest=DIGEST,
            package_manifest_digest="b" * 64,
            validator_digest="c" * 64,
            argv=commands,
            cwd=".",
            s2_receipt_sha256="d" * 64,
        )
        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_reused_receipt_without_live_frozen_revalidation_fails_closed(self) -> None:
        executed = boundary_receipt(receipt_mode="executed_now")
        reused = boundary_receipt(
            receipt_mode="reused_receipt",
            reused_receipt_sha256=executed["receipt_sha256"],
        )
        reused["frozen_source_revalidation"]["revalidated_now"] = False
        reused["receipt_sha256"] = __import__(
            "scripts.v250.repository_boundary", fromlist=["_receipt_sha256"]
        )._receipt_sha256(reused)
        verdict = validate_boundary_receipt(
            reused,
            source_commit=SOURCE,
            source_tree=TREE,
            asset_set_id="ASSET-V250",
            asset_set_digest=DIGEST,
            package_manifest_digest="b" * 64,
            validator_digest="c" * 64,
            argv=reused["argv"],
            cwd=".",
            s2_receipt_sha256="d" * 64,
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_REPOSITORY_BOUNDARY_SOURCE_NOT_FROZEN", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
