"""V2.66 Current and release control surfaces."""

from __future__ import annotations

import importlib.util
import argparse
import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from scripts.v266 import release_flow


ROOT = Path(__file__).resolve().parents[2]
VALIDATE_PATH = ROOT / "scripts/checks/validate.py"
SECURITY_RUNNER_PATH = ROOT / "scripts/checks/run-v266-release-security-review.py"
VERSION_SYNC_PATH = ROOT / "scripts/checks/check-version-sync.py"
SECURITY_MANIFEST_PATH = (
    ROOT
    / "references/current/generations/V2.66/contracts/"
    "release-security-review-manifest.json"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV266ReleaseSurfaces(unittest.TestCase):
    @staticmethod
    def _strict_projections(_sync):
        candidate = {
            "schema_version": "goal-teams-release-manifest-v2.65",
            "product_version": "V2.65",
            "candidate_product_version": "V2.66",
            "candidate_release_state": "development_candidate_not_published",
            "candidate_profile": "references/release-profiles/v2.66.json",
            "core_policy_version": "V2.5",
            "legacy_data_schema_version": "V2.3",
            "docs_policy": "local-only",
            "release_scope": "runtime-package",
            "claim_scope": (
                "agent_product_development_and_verification_governance_"
                "desktop_contracts"
            ),
            "cache_evidence": {
                "structural_delivery_state": "passed",
                "host_integration_state": "unavailable",
                "live_cache_validation_state": "not_authorized",
                "request_hit_rate_support_state": "unavailable",
            },
            "completion_telemetry": {
                "tokens_consumed": {
                    "status": "unavailable",
                    "value": None,
                    "display_zh": "未获取到",
                    "display_en": "Unavailable",
                },
                "cache_hit_rate": {
                    "status": "unavailable",
                    "value": None,
                    "display_zh": "未获取到",
                    "display_en": "Unavailable",
                },
                "claim_policy": "no_estimation_without_trusted_host_usage_evidence",
            },
            "release_identity": {
                "tag": "v2.65",
                "release_id": 375434758,
                "state": "published",
                "source_commit": "8512f6b9a7668daa6824b7a97494b927962b299e",
                "source_tree": "fb436dbee231ee6c066cbb00fc9048b3113134ef",
                "public_assets": [
                    "goal-teams-V2.65.tar.gz",
                    "SHA256SUMS",
                    "_release.json",
                    "_files.sha256",
                ],
            },
            "assurance_limits": {
                "reproducibility": "not_verified_by_v250_policy",
                "s2_security_checks": "not_run_by_v250_policy",
                "fresh_runtime_transition": "I1_correlated_not_external_independence",
                "kg_parser_scope": (
                    "controlled_markdown_lexical_subset_not_commonmark_gfm_conformance"
                ),
                "kg_digest_scope": "graph_input_manifest_not_rdf_dataset",
                "kg_isolated_entity_detector": "not_implemented",
                "kg_compile_resource_budget": "not_implemented",
                "kg_trace_truncated_match_count": (
                    "discovered_lower_bound_not_total_reachable_edges"
                ),
            },
            "status": "release",
        }
        final = {
            **candidate,
            "schema_version": "goal-teams-release-manifest-v2.66",
            "product_version": "V2.66",
            "release_identity": {
                **candidate["release_identity"],
                "tag": "v2.66",
                "release_id": 466000001,
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
        for key in (
            "candidate_product_version",
            "candidate_release_state",
            "candidate_profile",
        ):
            final.pop(key, None)
        return candidate, final

    def _run_version_sync_projection(
        self,
        sync,
        projection,
        *,
        readme_published_version: str | None = None,
    ) -> None:
        original_read = sync.read
        args = argparse.Namespace(
            mode="development",
            published_version=projection.get("product_version"),
            candidate_commit=None,
        )

        def projected_read(path: str) -> str:
            if path == "release/current/manifest.json":
                return json.dumps(projection)
            if path == "release/current/README.md":
                heading = readme_published_version or projection.get("product_version")
                return f"# Goal Teams {heading} Release\n\nV2.66\n"
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

    def test_version_sync_accepts_candidate_and_final_current_projection(self) -> None:
        sync = _load(VERSION_SYNC_PATH, "_test_v266_version_sync")
        candidate, final = self._strict_projections(sync)
        self.assertEqual(
            {
                "schema_version": "goal-teams-release-manifest-v2.65",
                "product_version": "V2.65",
                "tag": "v2.65",
                "release_id": 375434758,
                "source_commit": "8512f6b9a7668daa6824b7a97494b927962b299e",
                "source_tree": "fb436dbee231ee6c066cbb00fc9048b3113134ef",
            },
            {
                "schema_version": candidate["schema_version"],
                "product_version": candidate["product_version"],
                "tag": candidate["release_identity"]["tag"],
                "release_id": candidate["release_identity"]["release_id"],
                "source_commit": candidate["release_identity"]["source_commit"],
                "source_tree": candidate["release_identity"]["source_tree"],
            },
        )
        self.assertTrue(
            {
                "candidate_product_version",
                "candidate_release_state",
                "candidate_profile",
            }.isdisjoint(final)
        )
        for projection in (candidate, final):
            with self.subTest(published_version=projection["product_version"]):
                try:
                    self._run_version_sync_projection(sync, projection)
                except SystemExit as exc:
                    self.fail(
                        f"E_TEST_V266_VERSION_SYNC_REJECTED_VALID_PROJECTION:{exc.code}"
                    )

    def test_version_sync_rejects_mixed_or_partial_current_projection(self) -> None:
        sync = _load(VERSION_SYNC_PATH, "_test_v266_version_sync_negative")
        candidate, final = self._strict_projections(sync)
        invalid = []

        missing_profile = copy.deepcopy(candidate)
        missing_profile.pop("candidate_profile")
        invalid.append(missing_profile)

        candidate_schema = copy.deepcopy(candidate)
        candidate_schema["schema_version"] = "goal-teams-release-manifest-v2.66"
        invalid.append(candidate_schema)

        candidate_draft = copy.deepcopy(candidate)
        candidate_draft["release_identity"]["state"] = "draft"
        invalid.append(candidate_draft)

        for key in (
            "candidate_product_version",
            "candidate_release_state",
            "candidate_profile",
            "schema_version",
            "release_identity.tag",
            "release_identity.state",
            "release_identity.release_id",
            "release_identity.source_commit",
            "release_identity.source_tree",
            "release_identity.public_assets",
        ):
            mixed = copy.deepcopy(final)
            if key == "candidate_product_version":
                mixed[key] = "V2.66"
            elif key == "candidate_release_state":
                mixed[key] = "development_candidate_not_published"
            elif key == "candidate_profile":
                mixed[key] = "references/release-profiles/v2.66.json"
            elif key == "schema_version":
                mixed[key] = "goal-teams-release-manifest-v2.65"
            elif key == "release_identity.tag":
                mixed["release_identity"]["tag"] = "v2.65"
            elif key == "release_identity.state":
                mixed["release_identity"]["state"] = "draft"
            elif key == "release_identity.release_id":
                mixed["release_identity"]["release_id"] = 0
            elif key == "release_identity.source_commit":
                mixed["release_identity"]["source_commit"] = "a" * 39
            elif key == "release_identity.source_tree":
                mixed["release_identity"]["source_tree"] = "b" * 39
            else:
                mixed["release_identity"]["public_assets"][0] = (
                    "goal-teams-V2.65.tar.gz"
                )
            invalid.append(mixed)

        for projection in invalid:
            with self.subTest(projection=projection):
                with self.assertRaises(SystemExit):
                    self._run_version_sync_projection(sync, projection)

        with self.subTest(projection="final_with_predecessor_readme_heading"):
            with self.assertRaises(SystemExit):
                self._run_version_sync_projection(
                    sync,
                    final,
                    readme_published_version="V2.65",
                )

    def test_current_validator_dispatches_v266_without_legacy_readme_checks(self) -> None:
        validator = _load(VALIDATE_PATH, "_test_v266_current_validator")
        self.assertEqual("V2.66", validator.CURRENT_VERSION)
        with (
            mock.patch.object(validator.subprocess, "run") as run,
            mock.patch.object(
                validator,
                "check_readmes",
                side_effect=AssertionError("legacy README path invoked"),
            ),
            mock.patch("builtins.print"),
        ):
            validator.main()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(4, len(commands))
        self.assertIn(
            [
                validator.sys.executable,
                "scripts/checks/validate-v250-generation.py",
                "--generation-id",
                "V2.66",
                "--selection",
                "active",
            ],
            commands,
        )

    def test_current_release_readme_describes_v265_and_v263_predecessor(self) -> None:
        text = (ROOT / "scripts/release/README.md").read_text(encoding="utf-8")
        current = text.split("## V2.48 Skill 简单发行兼容", 1)[0]
        self.assertIn("V2.65 两阶段 Skill 发行", current)
        self.assertIn("--version V2.65", current)
        self.assertIn("docs/v2.65-release-runtime", current)
        self.assertIn("已安装 V2.63 Codex 宿主", current)
        self.assertNotIn("已安装 V2.6 Codex 宿主", current)
        self.assertIn("不是 V2.65\nCurrent Skill 发行默认入口", text)
        self.assertIn(
            "V2.65 是候选 `skill_simple` profile，V2.63 保持已安装基线直到 atomic cutover",
            text,
        )

    def test_v265_release_readme_uses_facts_derived_medium_route_only(self) -> None:
        text = (ROOT / "scripts/release/README.md").read_text(encoding="utf-8")
        current = text.split("## V2.48 Skill 简单发行兼容", 1)[0]
        self.assertIn("from scripts.v250.route_derivation import derive_route", current)
        self.assertIn(
            "from scripts.v250.route_closure import compile_derived_route_closure",
            current,
        )
        self.assertIn('"project_size": "medium"', current)
        self.assertIn('"workflow_phase": "release"', current)
        self.assertIn('"stage": "released"', current)
        self.assertIn("derive_route(project_route_facts)", current)
        self.assertIn("compile_derived_route_closure", current)
        self.assertIn("--project-size medium", current)
        self.assertNotIn("compile_route_closure", current)
        self.assertNotIn("--project-size large", current)

    def test_security_denominator_covers_new_runtime_and_projection_code(self) -> None:
        manifest = json.loads(SECURITY_MANIFEST_PATH.read_text(encoding="utf-8"))
        runner = _load(SECURITY_RUNNER_PATH, "_test_v266_security_runner")
        targets = {item["path"] for item in manifest["review_targets"]}
        required = {
            "scripts/checks/check.sh",
            "scripts/checks/check-v266.py",
            "scripts/checks/run-v266-release-security-review.py",
            "scripts/checks/validate.py",
            "scripts/checks/check-version-sync.py",
            "scripts/checks/validate-v250-generation.py",
            "scripts/checks/validate-v250-test-gate.py",
            "scripts/v250/generate_subagents.py",
            "scripts/v250/generate_unicode17_nfc.py",
            "scripts/v250/generation_runtime.py",
            "scripts/v250/loop_bootstrap.py",
            "scripts/v250/okf_conformance.py",
            "scripts/v250/output_contract.py",
            "scripts/v250/route_closure.py",
            "scripts/v250/test_gate.py",
            "scripts/v250/unicode17_data.py",
            "scripts/v250/unicode17_nfc.py",
            "scripts/v266/compatibility.py",
            "scripts/v266/project_host_assets.py",
            "scripts/v266/role_projections.py",
            "scripts/v266/release_identity.py",
            "scripts/v266/release_flow.py",
            "scripts/v266/repository_boundary.py",
            "scripts/v266/runtime_host_adapter.py",
            "scripts/v266/runtime_transition.py",
            "scripts/v266/s4_executor.py",
        }
        self.assertTrue(required.issubset(targets))
        self.assertEqual(targets, set(runner.MANDATORY_REVIEW_TARGETS))
        self.assertEqual(targets, set(release_flow.V250_SECURITY_REQUIRED_TARGET_PATHS))

    def test_current_full_regression_includes_v263_compatibility_and_excludes_legacy(self) -> None:
        command = json.loads(
            (
                ROOT
                / "references/current/generations/V2.66/contracts/"
                "release-command-manifest.json"
            ).read_text(encoding="utf-8")
        )
        denominator = command["release"]["s1"]["current_full_regression_denominator"]
        self.assertEqual(
            ["tests/v250", "tests/v266"],
            denominator["test_roots"],
        )
        self.assertEqual(
            ["tests/v265"], denominator["published_predecessor_test_roots"]
        )
        self.assertEqual(0, denominator["predecessor_test_invocation_limit"])
        self.assertEqual(
            ["tests/v23", "tests/v249", "tests/v26", "tests/v262", "tests/v263"],
            denominator["legacy_roots_excluded"],
        )

        for relative in (
            ".github/workflows/check.yml",
            ".github/workflows/release-gate.yml",
            "scripts/checks/check.sh",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            if relative.endswith(".yml"):
                self.assertIn("tests.v250.", text, relative)
                self.assertIn("tests.v266.", text, relative)
                self.assertNotIn("tests.v265.", text, relative)
            else:
                self.assertIn("tests.v250.", text, relative)
                self.assertIn("tests.v266.", text, relative)
                self.assertNotIn("tests.v265.", text, relative)


if __name__ == "__main__":
    unittest.main()
