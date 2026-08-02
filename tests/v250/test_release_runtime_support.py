"""Focused contract tests for the shared V2.50 release runtime."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "1" * 40
TREE = "2" * 40


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_config = load(
    "_test_v250_release_config",
    "scripts/release/release_config.py",
)
builder = load(
    "_test_v250_release_builder",
    "scripts/release/build-release.py",
)
validator = load(
    "_test_v250_release_validator",
    "scripts/release/validate-release.py",
)
skill_release = load(
    "_test_v250_skill_release",
    "scripts/release/skill_release.py",
)


class V250ReleaseRuntimeSupportTests(unittest.TestCase):
    def test_active_profile_is_v250_with_published_v248_predecessor(self) -> None:
        self.assertEqual("V2.50", release_config.ACTIVE_VERSION)
        self.assertIn("V2.49", release_config.supported_versions())
        self.assertIn("V2.50", release_config.supported_versions())

        active = release_config.active_release_config()
        self.assertEqual("V2.50", active["version"])
        self.assertEqual("V2.48", active["published_before"])
        self.assertEqual("codex/v2.50-release", active["candidate_branch"])
        self.assertEqual("v2.50", active["tag"])
        self.assertEqual(
            "project_start_authorization_reused",
            active["approval_model"],
        )
        self.assertEqual("ssh_only", active["git_transport"])
        self.assertEqual(
            "references/current/generations/V2.50/contracts/public-asset-map.json",
            active["public_asset_map_path"],
        )

        historical = release_config.release_config("V2.49")
        self.assertEqual("V2.49", historical["version"])
        self.assertEqual("v2.49", historical["tag"])

    def test_builder_and_validator_close_over_v250(self) -> None:
        self.assertEqual(
            "codex/v2.50-release",
            builder.KNOWN_RELEASES["V2.50"],
        )
        self.assertIn("V2.49", builder.STRICT_SNAPSHOT_VERSIONS)
        self.assertIn("V2.50", builder.STRICT_SNAPSHOT_VERSIONS)
        self.assertTrue(builder.validate_release_version("V2.50")["passed"])

        self.assertIn("V2.49", validator.SUPPORTED_RELEASE_VERSIONS)
        self.assertIn("V2.50", validator.SUPPORTED_RELEASE_VERSIONS)
        candidate = {
            "status": "release",
            "product_version": "V2.48",
            "candidate_product_version": "V2.50",
            "candidate_release_state": "v250_release_readiness",
        }
        self.assertEqual(
            "candidate",
            validator.release_projection_state(
                "V2.50", candidate, allow_candidate=True
            ),
        )
        self.assertEqual(
            "invalid",
            validator.release_projection_state(
                "V2.50", candidate, allow_candidate=False
            ),
        )

        identity = {
            "version": "V2.50",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "profile_sha256": "3" * 64,
            "asset_set_digest": "4" * 64,
            "asset_set_id": "V250-ASSET-TEST",
        }
        self.assertTrue(
            validator.validate_v250_release_identity(identity, identity)["passed"]
        )
        drift = dict(identity, version="V2.49")
        self.assertEqual(
            "E_V250_RELEASE_IDENTITY_DRIFT",
            validator.validate_v250_release_identity(identity, drift)[
                "error_code"
            ],
        )

    def test_okf_runtime_selection_tracks_current_generation(self) -> None:
        self.assertEqual("v249", builder.okf_runtime_generation("V2.49"))
        self.assertEqual("v250", builder.okf_runtime_generation("V2.50"))
        self.assertEqual("v249", validator.okf_runtime_generation("V2.49"))
        self.assertEqual("v250", validator.okf_runtime_generation("V2.50"))

    def test_skill_release_uses_v250_contract_and_keeps_v249_module(self) -> None:
        config = skill_release._simple_config("V2.50")
        self.assertEqual("V2.50", config["version"])
        self.assertEqual("project_start_authorization_reused", config["approval_model"])
        self.assertEqual("ssh_only", config["git_transport"])

        self.assertTrue(
            str(skill_release._release_flow_path("V2.49")).endswith(
                "scripts/v249/release_flow.py"
            )
        )
        self.assertTrue(
            str(skill_release._release_flow_path("V2.50")).endswith(
                "scripts/v250/release_flow.py"
            )
        )
        self.assertIn(
            "references/current/generations/V2.50/contracts/release-command-manifest.json",
            skill_release.runtime_static_input_paths("V2.50"),
        )
        self.assertNotIn(
            "references/current/generations/V2.49/contracts/release-command-manifest.json",
            skill_release.runtime_static_input_paths("V2.50"),
        )

    def test_v250_plan_reuses_start_authorization_and_single_build(self) -> None:
        identity = {
            "source_commit": SOURCE,
            "source_git_tree": TREE,
            "tag": "v2.50",
            "tag_state": "absent",
            "tag_target_commit": None,
        }
        release_flow = SimpleNamespace(
            derive_release_plan=mock.Mock(
                return_value={"release_ready": False, "project_size": "medium"}
            )
        )
        with (
            mock.patch.object(skill_release, "_read_identity", return_value=identity),
            mock.patch.object(
                skill_release,
                "_release_flow_module",
                return_value=release_flow,
            ) as flow_loader,
        ):
            receipt = skill_release.plan("V2.50", SOURCE)
        flow_loader.assert_called_once_with("V2.50")
        self.assertEqual("release_readiness_not_met", receipt["status"])
        self.assertEqual(
            "uses_project_start_authorization_receipt",
            receipt["gates"]["publish"],
        )
        self.assertEqual(
            "project_start_authorization_receipt_required",
            receipt["publish_state"],
        )

        with mock.patch.object(skill_release, "_read_identity", return_value=identity):
            with self.assertRaises(skill_release.SkillReleaseError) as caught:
                skill_release.verify("V2.50", SOURCE)
        self.assertEqual(
            "E_V250_EXPLICIT_SINGLE_BUILD_REQUIRED",
            caught.exception.receipt["error_code"],
        )
        self.assertEqual(0, caught.exception.receipt["s2_build_invocation_count"])

    def test_cli_defaults_to_v250(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            ["skill_release.py", "plan", "--commit", SOURCE],
        ):
            args = skill_release.parse_args()
        self.assertEqual("V2.50", args.version)

    def test_public_asset_names_are_version_specific(self) -> None:
        self.assertIn(
            "goal-teams-V2.49.tar.gz",
            skill_release.continuation_asset_names("V2.49"),
        )
        self.assertIn(
            "goal-teams-V2.50.tar.gz",
            skill_release.continuation_asset_names("V2.50"),
        )

        profile = json.loads(
            (ROOT / "references/release-profiles/v2.50.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("V2.48", profile["published_before"])
        self.assertEqual("codex/v2.50-release", profile["candidate_branch"])
        self.assertEqual("ssh_only", profile["git_transport"])


if __name__ == "__main__":
    unittest.main()
