from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_config = _load(
    "goal_teams_v244_release_config",
    "scripts/release/release_config.py",
)
builder = _load(
    "goal_teams_v244_release_builder",
    "scripts/release/build-release.py",
)
validator = _load(
    "goal_teams_v244_release_validator",
    "scripts/release/validate-release.py",
)
adapter = _load(
    "goal_teams_v244_github_adapter",
    "scripts/release/github_adapter.py",
)
source_validator = _load(
    "goal_teams_v244_source_validator",
    "scripts/checks/validate.py",
)
release = _load(
    "goal_teams_v244_release",
    "scripts/release/release.py",
)


class V244ReleaseEngineTests(unittest.TestCase):
    def test_active_profile_closes_every_public_release_identity(self) -> None:
        profile = release_config.active_release_config()
        self.assertEqual(profile["version"], "V2.44")
        self.assertEqual(profile["status"], "active")
        self.assertTrue(profile["external_writes_allowed"])
        self.assertEqual(profile["candidate_branch"], "codex/v2.44-testing-capability")
        self.assertEqual(profile["tag"], "v2.44")
        self.assertEqual(profile["release_title"], "Goal Teams V2.44")
        self.assertEqual(profile["tag_message"], "Goal Teams V2.44")
        self.assertEqual(
            profile["host_acceptance"]["schema_version"],
            "goal-teams-external-host-acceptance-v2",
        )
        self.assertEqual(profile["host_acceptance"]["algorithm"], "Ed25519")
        self.assertEqual(
            profile["host_acceptance"]["signature_domain"],
            "goal-teams/v2.44/cp05/host-acceptance/ed25519/v1",
        )
        self.assertEqual(
            hashlib.sha256(
                bytes.fromhex(profile["host_acceptance"]["public_key_hex"])
            ).hexdigest(),
            profile["host_acceptance"]["key_id"],
        )
        self.assertEqual(
            profile["files_manifest_format"],
            "sha256-mode-size-path-v1",
        )
        self.assertRegex(profile["config_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(profile["config_canonical_sha256"], r"^[0-9a-f]{64}$")

    def test_unknown_profile_and_profile_field_drift_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported release version"):
            release_config.release_config("V2.45")
        original = release_config.PROFILE_BY_VERSION["V2.44"]
        try:
            release_config.PROFILE_BY_VERSION["V2.44"] = (
                ROOT / "references" / "release-profiles" / "v2.40.json"
            )
            with self.assertRaisesRegex(ValueError, "fields drift|identity drift"):
                release_config.release_config("V2.44")
        finally:
            release_config.PROFILE_BY_VERSION["V2.44"] = original

    def test_v244_keeps_v240_strict_snapshot_contract(self) -> None:
        self.assertIn("V2.44", builder.KNOWN_RELEASES)
        self.assertIn("V2.44", builder.OKF_RELEASE_VERSIONS)
        self.assertIn("V2.44", builder.STRICT_SNAPSHOT_VERSIONS)
        self.assertIn("V2.44", validator.STRICT_SNAPSHOT_VERSIONS)
        rows = [
            {
                "sha256": "a" * 64,
                "mode": "100755",
                "size": 7,
                "path": "scripts/check.sh",
            }
        ]
        self.assertEqual(
            builder.format_v240_files_manifest(rows),
            f"{'a' * 64}\t100755\t7\tscripts/check.sh\n",
        )
        installer = (ROOT / "scripts/install/install-local.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('version in {"V2.40", "V2.44"}', installer)

    def test_github_adapter_projects_v244_and_denies_v240_writes(self) -> None:
        instance = adapter.GitHubAdapter(
            source_root=ROOT,
            workspace_root=ROOT,
            repository="vibe-coding-era/goal-teams",
            version="V2.44",
            candidate_commit="b" * 40,
            base_main_commit="a" * 40,
            authority={},
            execute_external_writes=False,
        )
        self.assertEqual(instance.candidate_ref, "refs/heads/codex/v2.44-testing-capability")
        self.assertEqual(instance.tag, "v2.44")
        self.assertEqual(instance.release_title, "Goal Teams V2.44")
        with self.assertRaises(adapter.AdapterError) as caught:
            adapter.GitHubAdapter(
                source_root=ROOT,
                workspace_root=ROOT,
                repository="vibe-coding-era/goal-teams",
                version="V2.40",
                candidate_commit="b" * 40,
                base_main_commit="a" * 40,
                authority={},
                execute_external_writes=True,
            )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_HISTORICAL_WRITE_FORBIDDEN",
        )

    def test_workflow_and_release_projection_are_v244(self) -> None:
        workflow = (ROOT / ".github/workflows/release-gate.yml").read_text(
            encoding="utf-8"
        ) if (ROOT / ".github/workflows/release-gate.yml").is_file() else None
        if workflow is not None:
            source_validator.check_release_workflow_projection(
                release_config.active_release_config(), workflow
            )
        manifest = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["product_version"], "V2.44")
        self.assertEqual(manifest["status"], "release")
        self.assertIn("V2.44", (ROOT / "release/current/README.md").read_text())

    def test_workflow_projection_rejects_each_release_identity_drift(self) -> None:
        workflow_path = ROOT / ".github/workflows/release-gate.yml"
        if not workflow_path.is_file():
            self.skipTest("installed package does not include GitHub workflow")
        workflow = workflow_path.read_text(encoding="utf-8")
        profile = release_config.active_release_config()
        mutations = (
            workflow.replace(
                "branches: [main, codex/v2.44-testing-capability]",
                "branches: [main, codex/v2.40]",
                1,
            ),
            workflow.replace("--version V2.44", "--version V2.40", 1),
            workflow.replace(
                "Goal Teams V2.44 release {0}",
                "Goal Teams V2.40 release {0}",
                1,
            ),
            workflow.replace(
                "/V2.44/_files.sha256",
                "/V2.40/_files.sha256",
                1,
            ),
        )
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                with mock.patch.object(
                    source_validator, "fail", side_effect=SystemExit(1)
                ), self.assertRaises(SystemExit):
                    source_validator.check_release_workflow_projection(profile, mutated)

    def test_v244_private_workflow_helper_is_also_host_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "docs").mkdir()
            state = {
                "version": "V2.44",
                "candidate_commit": "b" * 40,
            }
            approval = {
                "reviewer": {
                    "role": "independent_release_reviewer",
                    "member_id": "goal-lead",
                    "run_id": "RUN-V244-LEAD",
                    "independent": True,
                    "decision": "accepted",
                    "source_commit": "b" * 40,
                    "reviewed_at": "2026-07-24T00:00:00Z",
                }
            }
            with mock.patch.object(
                release, "_workspace_root", return_value=workspace
            ), mock.patch.object(
                release, "_require_clean_candidate_checkout", return_value={}
            ):
                with self.assertRaises(release.PolicyError) as caught:
                    release._execute_local_operation(
                        "CP05.workflow_approve",
                        state,
                        {"ci_approval": approval},
                        workspace / "docs" / "state.json",
                    )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V244_HOST_CP05_REQUIRED",
        )

    def test_v244_public_cp05_is_permanently_host_only_and_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            docs = workspace / "docs"
            docs.mkdir()
            state_path = docs / "promotion-state.json"
            state_path.write_text('{"sentinel":"unchanged"}\n', encoding="utf-8")
            before = hashlib.sha256(state_path.read_bytes()).hexdigest()
            state = {
                "version": "V2.44",
                "current_checkpoint": "CP05",
            }
            forged_variants = (
                {"operation_authorizations": {}},
                {"host_acceptance": True},
                {"host_acceptance_sha256": "a" * 64},
                {"host_acceptance_path": "/tmp/host-acceptance.json"},
                {"host_capability": "argv-or-env-token"},
            )
            for forged in forged_variants:
                for recover_only in (False, True):
                    with self.subTest(
                        forged=forged, recover_only=recover_only
                    ), mock.patch.object(
                        release,
                        "_load_state_cas",
                        return_value=(state_path, dict(state), before),
                    ), mock.patch.object(
                        release, "_verify_frozen_git_identity"
                    ), mock.patch.object(
                        release, "_atomic_state_write"
                    ) as atomic_write, mock.patch.object(
                        release, "_persist_operation_readback"
                    ) as persist_readback:
                        with self.assertRaises(release.PolicyError) as caught:
                            release.execute_current_checkpoint(
                                state_path,
                                {
                                    "expected_state_sha256": before,
                                    "checkpoint_id": "CP05",
                                    **forged,
                                },
                                recover_only=recover_only,
                            )
                    self.assertEqual(
                        caught.exception.receipt["error_code"],
                        "E_V244_HOST_CP05_REQUIRED",
                    )
                    atomic_write.assert_not_called()
                    persist_readback.assert_not_called()
                    self.assertEqual(
                        hashlib.sha256(state_path.read_bytes()).hexdigest(),
                        before,
                    )

    def test_compatibility_shell_adapter_is_read_only(self) -> None:
        script = (ROOT / "scripts/release/publish-github-release.sh").read_text(
            encoding="utf-8"
        )
        case_block = script[script.index('case "$ACTION" in') :]
        self.assertIn("E_V240_INTERNAL_ADAPTER_WRITE_FORBIDDEN", case_block)
        self.assertNotIn("gh release create", case_block)
        self.assertNotIn("gh release edit", case_block)

    def test_immutable_release_enable_uses_bodyless_github_put(self) -> None:
        instance = adapter.GitHubAdapter(
            source_root=ROOT,
            workspace_root=ROOT,
            repository="vibe-coding-era/goal-teams",
            version="V2.44",
            candidate_commit="b" * 40,
            base_main_commit="a" * 40,
            authority={},
            execute_external_writes=True,
        )
        observed = {
            "classification": "absent",
            "details": {"enabled": False},
        }
        enabled = {
            "classification": "exact",
            "details": {"enabled": True},
        }
        with mock.patch.object(
            instance, "observe", side_effect=(observed, enabled)
        ), mock.patch.object(
            instance, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_run"
        ) as run:
            result = instance.execute(
                operation_id="CP03.immutable_release_enable",
                action="immutable_release_enable",
                expected_before={"enabled": False},
                parameters={},
            )
        run.assert_called_once_with(
            (
                "gh",
                "api",
                "repos/vibe-coding-era/goal-teams/immutable-releases",
                "--hostname",
                "github.com",
                "--method",
                "PUT",
            ),
            cwd=ROOT,
            env={"GH_HOST": "github.com"},
        )
        self.assertEqual(result["classification"], "exact")

    def test_candidate_push_uses_exact_remote_lease_for_existing_branch(
        self,
    ) -> None:
        candidate = "b" * 40
        previous = "c" * 40
        instance = adapter.GitHubAdapter(
            source_root=ROOT,
            workspace_root=ROOT,
            repository="vibe-coding-era/goal-teams",
            version="V2.44",
            candidate_commit=candidate,
            base_main_commit="a" * 40,
            authority={},
            execute_external_writes=True,
        )
        with mock.patch.object(
            instance, "_remote_ref", return_value=previous
        ):
            observed = instance.observe(
                operation_id="CP12.candidate_push",
                action="candidate_push",
                expected_before={"remote_candidate_commit": previous},
                parameters={},
            )
        self.assertEqual(observed["classification"], "before")

        before = {"classification": "before", "details": {}}
        exact = {"classification": "exact", "details": {}}
        with mock.patch.object(
            instance, "observe", side_effect=(before, exact)
        ), mock.patch.object(
            instance, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_run"
        ) as run:
            result = instance.execute(
                operation_id="CP12.candidate_push",
                action="candidate_push",
                expected_before={"remote_candidate_commit": previous},
                parameters={},
            )
        run.assert_called_once_with(
            (
                "git",
                "push",
                f"--force-with-lease={instance.candidate_ref}:{previous}",
                "origin",
                f"{candidate}:{instance.candidate_ref}",
            ),
            cwd=ROOT,
        )
        self.assertEqual(result["classification"], "exact")

    def test_candidate_push_handles_absent_exact_and_prewrite_conflict(
        self,
    ) -> None:
        candidate = "b" * 40
        previous = "c" * 40
        concurrent = "d" * 40
        instance = adapter.GitHubAdapter(
            source_root=ROOT,
            workspace_root=ROOT,
            repository="vibe-coding-era/goal-teams",
            version="V2.44",
            candidate_commit=candidate,
            base_main_commit="a" * 40,
            authority={},
            execute_external_writes=True,
        )
        for remote, expected, classification in (
            (None, None, "absent"),
            (candidate, previous, "exact"),
            (concurrent, previous, "conflict"),
        ):
            with self.subTest(classification=classification), mock.patch.object(
                instance, "_remote_ref", return_value=remote
            ):
                observed = instance.observe(
                    operation_id="CP12.candidate_push",
                    action="candidate_push",
                    expected_before={"remote_candidate_commit": expected},
                    parameters={},
                )
            self.assertEqual(observed["classification"], classification)

        with mock.patch.object(
            instance,
            "observe",
            return_value={"classification": "exact", "details": {}},
        ), mock.patch.object(
            instance, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_run"
        ) as run:
            adopted = instance.execute(
                operation_id="CP12.candidate_push",
                action="candidate_push",
                expected_before={"remote_candidate_commit": previous},
                parameters={},
            )
        self.assertTrue(adopted["adopted_existing"])
        self.assertEqual(adopted["external_side_effect_count"], 0)
        run.assert_not_called()

        with mock.patch.object(
            instance,
            "observe",
            return_value={"classification": "conflict", "details": {}},
        ), mock.patch.object(
            instance, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_run"
        ) as run:
            with self.assertRaises(adapter.AdapterError) as caught:
                instance.execute(
                    operation_id="CP12.candidate_push",
                    action="candidate_push",
                    expected_before={"remote_candidate_commit": previous},
                    parameters={},
                )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_REMOTE_RESOURCE_CONFLICT",
        )
        self.assertEqual(
            caught.exception.receipt["external_side_effect_count"], 0
        )
        run.assert_not_called()

    def test_candidate_push_maps_post_observation_lease_race_to_conflict(
        self,
    ) -> None:
        previous = "c" * 40
        instance = adapter.GitHubAdapter(
            source_root=ROOT,
            workspace_root=ROOT,
            repository="vibe-coding-era/goal-teams",
            version="V2.44",
            candidate_commit="b" * 40,
            base_main_commit="a" * 40,
            authority={},
            execute_external_writes=True,
        )
        before = {"classification": "before", "details": {}}
        conflict = {"classification": "conflict", "details": {}}
        command_failure = adapter.AdapterError(
            "E_V240_ADAPTER_COMMAND", "lease rejected"
        )
        with mock.patch.object(
            instance, "observe", side_effect=(before, conflict)
        ), mock.patch.object(
            instance, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_run", side_effect=command_failure
        ):
            with self.assertRaises(adapter.AdapterError) as caught:
                instance.execute(
                    operation_id="CP12.candidate_push",
                    action="candidate_push",
                    expected_before={"remote_candidate_commit": previous},
                    parameters={},
                )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_REMOTE_RESOURCE_CONFLICT",
        )
        self.assertEqual(
            caught.exception.receipt["external_side_effect_count"], 0
        )

        with mock.patch.object(
            instance, "observe"
        ) as observe, mock.patch.object(
            instance, "_require_write_authority"
        ):
            with self.assertRaises(adapter.AdapterError) as malformed:
                instance.execute(
                    operation_id="CP12.candidate_push",
                    action="candidate_push",
                    expected_before={"remote_candidate_commit": "bad"},
                    parameters={},
                )
        self.assertEqual(
            malformed.exception.receipt["error_code"],
            "E_V240_ADAPTER_EXPECTED_BEFORE",
        )
        observe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
