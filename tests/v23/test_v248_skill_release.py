"""Focused coverage for the V2.48 Skill simple-release path."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_config = load(
    "_test_v248_simple_release_config",
    "scripts/release/release_config.py",
)
skill_release = load(
    "_test_v248_skill_release",
    "scripts/release/skill_release.py",
)
release_validator = load(
    "_test_v248_release_validator",
    "scripts/release/validate-release.py",
)


class V248SkillReleaseTests(unittest.TestCase):
    def test_public_manifest_claims_v248_agent_product_scope(self) -> None:
        manifest = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["claim_scope"],
            "agent_product_development_and_verification_governance_desktop_contracts",
        )

    def test_isolated_validation_accepts_candidate_projection_only(self) -> None:
        candidate = {
            "product_version": "V2.46",
            "candidate_product_version": "V2.48",
            "candidate_release_state": "skill_simple_local_validation",
            "status": "release",
        }
        self.assertEqual(
            release_validator.release_projection_state(
                "V2.48",
                candidate,
                allow_candidate=True,
            ),
            "candidate",
        )
        self.assertEqual(
            release_validator.release_projection_state(
                "V2.48",
                candidate,
                allow_candidate=False,
            ),
            "invalid",
        )

    def test_profile_declares_five_gate_simple_release(self) -> None:
        raw = json.loads(
            (ROOT / "references/release-profiles/v2.48.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(raw["release_mode"], "skill_simple")
        self.assertEqual(
            raw["approval_model"],
            "single_human_before_external_write",
        )
        self.assertEqual(len(raw["release_gates"]), 5)
        self.assertEqual(
            raw["required_status_checks"],
            ["check-macos", "release-asset-gate"],
        )
        self.assertFalse(raw["external_writes_allowed"])
        for field in (
            "host_acceptance",
            "approval_signer",
            "nonce_consumption_authority",
            "independent_review_authority",
        ):
            self.assertNotIn(field, raw)

    def test_active_config_is_ready_for_local_validation(self) -> None:
        config = release_config.active_release_config()
        self.assertEqual(config["version"], "V2.48")
        self.assertEqual(config["release_mode"], "skill_simple")
        self.assertEqual(
            config["closure_state"],
            "ready_for_local_validation",
        )
        self.assertFalse(config["external_writes_allowed"])
        self.assertEqual(
            config["required_status_checks"],
            ["check-macos", "release-asset-gate"],
        )

    def test_skill_release_workflow_excludes_ubuntu_gate(self) -> None:
        workflow = (
            ROOT / ".github/workflows/release-gate.yml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("check-ubuntu", workflow)
        self.assertEqual(workflow.count("name: check-macos"), 1)
        self.assertEqual(workflow.count("name: release-asset-gate"), 1)

    def test_v246_governed_profile_remains_unchanged(self) -> None:
        config = release_config.release_config("V2.46")
        self.assertEqual(config["status"], "active")
        self.assertTrue(config["external_writes_allowed"])
        self.assertIsInstance(config["host_acceptance"], dict)

    def test_plan_is_read_only_and_keeps_publish_blocked(self) -> None:
        identity = {
            "source_commit": "a" * 40,
            "source_git_tree": "b" * 40,
            "tag": "v2.48",
            "tag_state": "absent",
            "tag_target_commit": None,
        }
        with mock.patch.object(
            skill_release,
            "_read_identity",
            return_value=identity,
        ):
            receipt = skill_release.plan("V2.48", "a" * 40)
        self.assertTrue(receipt["passed"])
        self.assertEqual(
            receipt["status"],
            "ready_for_local_validation",
        )
        self.assertEqual(len(receipt["gates"]), 5)
        self.assertEqual(
            receipt["gates"]["publish"],
            "requires_explicit_user_approval",
        )
        self.assertEqual(receipt["source_git_tree"], "b" * 40)
        self.assertEqual(receipt["tag"], "v2.48")
        self.assertEqual(receipt["persistent_local_mutation_count"], 0)
        self.assertEqual(receipt["external_mutation_count"], 0)
        self.assertEqual(receipt["external_side_effect_count"], 0)

    def test_publish_never_executes_an_action(self) -> None:
        identity = {
            "source_commit": "a" * 40,
            "source_git_tree": "b" * 40,
            "tag": "v2.48",
            "tag_state": "absent",
            "tag_target_commit": None,
        }
        with mock.patch.object(
            skill_release,
            "_read_identity",
            return_value=identity,
        ):
            receipt = skill_release.publish("V2.48", "a" * 40)
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["action_executed"])
        self.assertEqual(
            receipt["status"],
            "requires_explicit_user_approval",
        )
        self.assertEqual(receipt["external_mutation_count"], 0)
        self.assertEqual(receipt["external_side_effect_count"], 0)
        self.assertEqual(
            receipt["required_operations"],
            [
                "push_candidate_commit",
                "create_version_tag",
                "create_github_release",
            ],
        )

    def test_verify_rejects_nonimmutable_commit_before_builder(self) -> None:
        with mock.patch.object(skill_release, "_builder_module") as builder:
            with self.assertRaises(skill_release.SkillReleaseError) as caught:
                skill_release.verify("V2.48", "HEAD")
        builder.assert_not_called()
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_SKILL_RELEASE_COMMIT",
        )
        self.assertEqual(
            caught.exception.receipt["external_side_effect_count"],
            0,
        )

    def test_verify_binds_version_commit_tree_and_manifest(self) -> None:
        commit = "a" * 40
        record = {
            "version": "V2.48",
            "source_commit": commit,
            "source_git_tree_id": "b" * 40,
            "tree_sha256": "c" * 64,
            "source_package_manifest_sha256": "d" * 64,
        }
        builder = SimpleNamespace(build=mock.Mock(return_value=record))
        structure = {"returncode": 0, "output_sha256": "e" * 64}
        identity = {
            "source_commit": commit,
            "source_git_tree": "b" * 40,
            "tag": "v2.48",
            "tag_state": "absent",
            "tag_target_commit": None,
        }
        with (
            mock.patch.object(
                skill_release,
                "_read_identity",
                return_value=identity,
            ),
            mock.patch.object(
                skill_release,
                "_builder_module",
                return_value=builder,
            ),
            mock.patch.object(
                skill_release,
                "_run_structure_gate",
                return_value=structure,
            ),
        ):
            receipt = skill_release.verify("V2.48", commit)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["status"], "partial_local_verification")
        self.assertEqual(receipt["source_commit"], commit)
        self.assertEqual(receipt["source_git_tree"], "b" * 40)
        self.assertEqual(receipt["package_tree_sha256"], "c" * 64)
        self.assertEqual(
            receipt["package_manifest_sha256"],
            "d" * 64,
        )
        self.assertEqual(receipt["gates"]["checks"], "partial")
        self.assertEqual(receipt["gates"]["package"], "partial")
        self.assertEqual(receipt["gates"]["isolated_install"], "not_run")
        self.assertEqual(
            receipt["verification_detail"]["package"][
                "double_build_reproducibility"
            ],
            "not_run",
        )
        self.assertEqual(
            receipt["publish_state"],
            "requires_explicit_user_approval",
        )
        self.assertEqual(receipt["persistent_local_mutation_count"], 0)
        self.assertEqual(receipt["external_mutation_count"], 0)


if __name__ == "__main__":
    unittest.main()
