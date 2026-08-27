"""Focused contract tests for the shared V2.66 release runtime."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
import tempfile
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
    @staticmethod
    def _candidate_v265_projection() -> dict[str, object]:
        predecessor = json.loads(
            (
                ROOT
                / "references/current/generations/V2.66/contracts/"
                "predecessor-release-identity.json"
            ).read_text(encoding="utf-8")
        )
        return {
            "schema_version": "goal-teams-release-manifest-v2.65",
            "product_version": "V2.65",
            "candidate_product_version": "V2.66",
            "candidate_release_state": "v250_release_readiness",
            "candidate_profile": "references/release-profiles/v2.66.json",
            "core_policy_version": "V2.5",
            "legacy_data_schema_version": "V2.3",
            "status": "release",
            "release_identity": predecessor["release_identity"],
        }

    @staticmethod
    def _published_v266_projection() -> dict[str, object]:
        return {
            "schema_version": "goal-teams-release-manifest-v2.66",
            "product_version": "V2.66",
            "core_policy_version": "V2.5",
            "legacy_data_schema_version": "V2.3",
            "status": "release",
            "release_identity": {
                "tag": "v2.66",
                "release_id": 463000001,
                "state": "published",
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "public_assets": [
                    "goal-teams-V2.66.tar.gz",
                    "SHA256SUMS",
                    "_release.json",
                    "_files.sha256",
                ],
            },
        }

    def _run_version_sync_projection(
        self,
        projection: dict[str, object],
        *,
        readme_heading: str = "V2.66",
    ) -> None:
        sync = load(
            f"_test_v250_projection_sync_{id(projection)}_{readme_heading}",
            "scripts/checks/check-version-sync.py",
        )
        original_read = sync.read
        args = argparse.Namespace(
            mode="development",
            published_version="V2.66",
            candidate_commit=None,
        )

        def projected_read(path: str) -> str:
            if path == "release/current/manifest.json":
                return json.dumps(projection)
            if path == "release/current/README.md":
                return f"# Goal Teams {readme_heading} Release\n\nV2.66\n"
            return original_read(path)

        with (
            mock.patch.object(sync, "parse_args", return_value=args),
            mock.patch.object(sync, "read", side_effect=projected_read),
            mock.patch.object(
                sync,
                "validate_runtime_identity",
                side_effect=AssertionError("legacy identity path invoked"),
            ),
            mock.patch("builtins.print"),
        ):
            sync.main()

    def test_active_profile_is_v250_with_published_v248_predecessor(self) -> None:
        self.assertEqual("V2.66", release_config.ACTIVE_VERSION)
        self.assertIn("V2.49", release_config.supported_versions())
        self.assertIn("V2.6", release_config.supported_versions())
        self.assertIn("V2.66", release_config.supported_versions())

        active = release_config.active_release_config()
        self.assertEqual("V2.66", active["version"])
        self.assertEqual("V2.65", active["published_before"])
        self.assertEqual("codex/develop-v2.66", active["candidate_branch"])
        self.assertEqual("v2.66", active["tag"])
        self.assertEqual(
            "project_start_authorization_reused",
            active["approval_model"],
        )
        self.assertEqual("ssh_only", active["git_transport"])
        self.assertEqual(
            "references/current/generations/V2.66/contracts/public-asset-map.json",
            active["public_asset_map_path"],
        )

        historical = release_config.release_config("V2.49")
        self.assertEqual("V2.49", historical["version"])
        self.assertEqual("v2.49", historical["tag"])

    def test_builder_and_validator_close_over_v250(self) -> None:
        self.assertEqual(
            "codex/develop-v2.66",
            builder.KNOWN_RELEASES["V2.66"],
        )
        self.assertIn("V2.49", builder.STRICT_SNAPSHOT_VERSIONS)
        self.assertIn("V2.66", builder.STRICT_SNAPSHOT_VERSIONS)
        self.assertTrue(builder.validate_release_version("V2.66")["passed"])

        self.assertIn("V2.49", validator.SUPPORTED_RELEASE_VERSIONS)
        self.assertIn("V2.66", validator.SUPPORTED_RELEASE_VERSIONS)
        candidate = self._candidate_v265_projection()
        self.assertEqual(
            "candidate",
            validator.release_projection_state(
                "V2.66", candidate, allow_candidate=True
            ),
        )
        self.assertEqual(
            "invalid",
            validator.release_projection_state(
                "V2.66", candidate, allow_candidate=False
            ),
        )
        current = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        current_state = validator.release_projection_state(
            "V2.66", current, allow_candidate=True
        )
        strict_current_state = validator.release_projection_state(
            "V2.66", current, allow_candidate=False
        )
        self.assertIn(current_state, {"candidate", "final"})
        identity = current["release_identity"]
        if current_state == "candidate":
            self.assertEqual("invalid", strict_current_state)
            predecessor = json.loads(
                (
                    ROOT
                    / "references/current/generations/V2.66/contracts/"
                    "predecessor-release-identity.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                predecessor["release_identity"],
                identity,
            )
        else:
            self.assertEqual("final", strict_current_state)
            self.assertEqual("V2.66", current.get("product_version"))
            self.assertTrue(
                {
                    "candidate_product_version",
                    "candidate_release_state",
                    "candidate_profile",
                }.isdisjoint(current)
            )
            self.assertEqual("v2.66", identity.get("tag"))
            self.assertEqual("published", identity.get("state"))
            self.assertIsInstance(identity.get("release_id"), int)
            self.assertNotIsInstance(identity.get("release_id"), bool)
            self.assertGreater(identity["release_id"], 0)
            self.assertRegex(identity.get("source_commit", ""), r"^[0-9a-f]{40}$")
            self.assertRegex(identity.get("source_tree", ""), r"^[0-9a-f]{40}$")
            self.assertEqual(
                [
                    "goal-teams-V2.66.tar.gz",
                    "SHA256SUMS",
                    "_release.json",
                    "_files.sha256",
                ],
                identity.get("public_assets"),
            )

        identity = {
            "version": "V2.66",
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

    def test_strict_published_projection_contract_and_negative_matrix(self) -> None:
        published = self._published_v266_projection()
        self.assertEqual(
            "final",
            validator.release_projection_state(
                "V2.66", published, allow_candidate=True
            ),
        )
        self.assertEqual(
            "final",
            validator.release_projection_state(
                "V2.66", published, allow_candidate=False
            ),
        )
        self._run_version_sync_projection(published)

        invalid: list[dict[str, object]] = []
        for mutate in (
            lambda value: value.update(
                {"schema_version": "goal-teams-release-manifest-v2.65"}
            ),
            lambda value: value.update(
                {"candidate_product_version": "V2.66"}
            ),
            lambda value: value.pop("release_identity"),
            lambda value: value["release_identity"].update({"tag": "v2.65"}),
            lambda value: value["release_identity"].update({"release_id": True}),
            lambda value: value["release_identity"].update(
                {"source_commit": "not-a-commit"}
            ),
            lambda value: value["release_identity"]["public_assets"].__setitem__(
                0, "goal-teams-V2.65.tar.gz"
            ),
        ):
            candidate = copy.deepcopy(published)
            mutate(candidate)
            invalid.append(candidate)

        for projection in invalid:
            with self.subTest(projection=projection):
                self.assertEqual(
                    "invalid",
                    validator.release_projection_state(
                        "V2.66", projection, allow_candidate=True
                    ),
                )
                with self.assertRaises(SystemExit):
                    self._run_version_sync_projection(projection)

        with self.assertRaises(SystemExit):
            self._run_version_sync_projection(published, readme_heading="V2.65")

    def test_strict_candidate_projection_negative_matrix(self) -> None:
        candidate = self._candidate_v265_projection()
        self.assertEqual(
            "candidate",
            validator.release_projection_state(
                "V2.66", candidate, allow_candidate=True
            ),
        )
        self.assertEqual(
            "invalid",
            validator.release_projection_state(
                "V2.66", candidate, allow_candidate=False
            ),
        )

        invalid: list[dict[str, object]] = []
        for mutate in (
            lambda value: value.update(
                {"schema_version": "goal-teams-release-manifest-v2.66"}
            ),
            lambda value: value.pop("candidate_profile"),
            lambda value: value.update({"candidate_extra": "forbidden"}),
            lambda value: value["release_identity"].update({"tag": "v2.66"}),
            lambda value: value["release_identity"].update({"release_id": 1}),
            lambda value: value["release_identity"]["public_assets"].__setitem__(
                0, "goal-teams-V2.66.tar.gz"
            ),
        ):
            projection = copy.deepcopy(candidate)
            mutate(projection)
            invalid.append(projection)

        for projection in invalid:
            with self.subTest(projection=projection):
                self.assertEqual(
                    "invalid",
                    validator.release_projection_state(
                        "V2.66", projection, allow_candidate=True
                    ),
                )

    def test_okf_runtime_selection_tracks_current_generation(self) -> None:
        self.assertEqual("v249", builder.okf_runtime_generation("V2.49"))
        self.assertEqual("v250", builder.okf_runtime_generation("V2.66"))
        self.assertEqual("v249", validator.okf_runtime_generation("V2.49"))
        self.assertEqual("v250", validator.okf_runtime_generation("V2.66"))

    def test_skill_release_uses_v250_contract_and_keeps_v249_module(self) -> None:
        config = skill_release._simple_config("V2.66")
        self.assertEqual("V2.66", config["version"])
        self.assertEqual("project_start_authorization_reused", config["approval_model"])
        self.assertEqual("ssh_only", config["git_transport"])

        self.assertTrue(
            str(skill_release._release_flow_path("V2.49")).endswith(
                "scripts/v249/release_flow.py"
            )
        )
        self.assertTrue(
            str(skill_release._release_flow_path("V2.66")).endswith(
                "scripts/v266/release_flow.py"
            )
        )
        with self.assertRaises(skill_release.SkillReleaseError) as caught:
            skill_release._release_flow_module("V2.65")
        self.assertEqual(
            "E_SKILL_RELEASE_PREDECESSOR_FLOW_UNAVAILABLE",
            caught.exception.receipt["error_code"],
        )
        self.assertIn(
            "references/current/generations/V2.66/contracts/release-command-manifest.json",
            skill_release.runtime_static_input_paths("V2.66"),
        )
        self.assertIn(
            "scripts/v266/runtime_transition.py",
            skill_release.runtime_static_input_paths("V2.66"),
        )
        self.assertIn(
            "references/current/generations/V2.66/contracts/predecessor-release-identity.json",
            skill_release.runtime_static_input_paths("V2.66"),
        )
        self.assertNotIn(
            "release/current/manifest.json",
            skill_release.runtime_static_input_paths("V2.66"),
        )
        self.assertNotIn(
            "references/current/generations/V2.49/contracts/release-command-manifest.json",
            skill_release.runtime_static_input_paths("V2.66"),
        )

    def test_v250_plan_reuses_start_authorization_and_single_build(self) -> None:
        identity = {
            "source_commit": SOURCE,
            "source_git_tree": TREE,
            "tag": "v2.66",
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
            receipt = skill_release.plan("V2.66", SOURCE)
        flow_loader.assert_called_once_with("V2.66")
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
                skill_release.verify("V2.66", SOURCE)
        self.assertEqual(
            "E_V266_EXPLICIT_SINGLE_BUILD_REQUIRED",
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
        self.assertEqual("V2.66", args.version)

    def test_public_asset_names_are_version_specific(self) -> None:
        self.assertIn(
            "goal-teams-V2.49.tar.gz",
            skill_release.continuation_asset_names("V2.49"),
        )
        self.assertIn(
            "goal-teams-V2.66.tar.gz",
            skill_release.continuation_asset_names("V2.66"),
        )

        profile = json.loads(
            (ROOT / "references/release-profiles/v2.66.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("V2.65", profile["published_before"])
        self.assertEqual("codex/develop-v2.66", profile["candidate_branch"])
        self.assertEqual("ssh_only", profile["git_transport"])

    def test_same_asset_failure_preserves_validator_errors(self) -> None:
        record = {
            "version": "V2.66",
            "source_commit": SOURCE,
            "source_git_tree_id": TREE,
        }
        with tempfile.TemporaryDirectory() as directory:
            release_root = Path(directory)
            snapshot = release_root / "V2.66"
            artifacts = snapshot / "_artifacts"
            artifacts.mkdir(parents=True)
            (snapshot / "_release.json").write_text(
                json.dumps(record), encoding="utf-8"
            )
            (snapshot / "_files.sha256").write_text("files\n", encoding="utf-8")
            (artifacts / "SHA256SUMS").write_text("sums\n", encoding="utf-8")
            (artifacts / "goal-teams-V2.66.tar.gz").write_bytes(b"asset")
            validation = {
                "passed": False,
                "errors": ["V2.66: current release manifest is not final"],
            }
            with (
                mock.patch.object(
                    skill_release,
                    "_read_identity",
                    return_value={
                        "source_commit": SOURCE,
                        "source_git_tree": TREE,
                    },
                ),
                mock.patch.object(
                    skill_release.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=1,
                        stdout=json.dumps(validation),
                        stderr="",
                    ),
                ),
                self.assertRaises(skill_release.SkillReleaseError) as caught,
            ):
                skill_release.validate_existing_asset_set(
                    "V2.66",
                    SOURCE,
                    release_root=release_root,
                    build_receipt={"built": [record]},
                )
        self.assertEqual(
            validation["errors"], caught.exception.receipt["validator_errors"]
        )

    def test_security_external_anchor_paths_follow_the_frozen_manifest(self) -> None:
        manifest = json.loads(
            (
                ROOT
                / "references/current/generations/V2.66/contracts/"
                "release-security-review-manifest.json"
            ).read_text(encoding="utf-8")
        )
        expected = {
            target["path"]
            for target in manifest["review_targets"]
            if "contract" in target["categories"]
        }
        self.assertIn("scripts/v250/refresh_generation_manifests.py", expected)
        self.assertEqual(
            expected,
            skill_release._security_external_anchor_paths(manifest),
        )

        historical = json.loads(
            (
                ROOT
                / "references/current/generations/V2.49/contracts/"
                "release-security-review-manifest.json"
            ).read_text(encoding="utf-8")
        )
        historical_expected = {
            target["path"]
            for target in historical["review_targets"]
            if "contract" in target["categories"]
        }
        self.assertEqual(6, len(historical_expected))
        self.assertEqual(
            historical_expected,
            skill_release._security_external_anchor_paths(historical),
        )

        for malformed in (
            {},
            {"review_targets": []},
            {"review_targets": [{"path": "contract.json"}]},
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    skill_release._security_external_anchor_paths(malformed)


if __name__ == "__main__":
    unittest.main()
