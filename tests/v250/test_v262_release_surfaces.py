from __future__ import annotations

import importlib.util
import argparse
import json
import unittest
from pathlib import Path
from unittest import mock

from scripts.v250 import release_flow


ROOT = Path(__file__).resolve().parents[2]
VALIDATE_PATH = ROOT / "scripts/checks/validate.py"
SECURITY_RUNNER_PATH = ROOT / "scripts/checks/run-v250-release-security-review.py"
VERSION_SYNC_PATH = ROOT / "scripts/checks/check-version-sync.py"
SECURITY_MANIFEST_PATH = (
    ROOT
    / "references/current/generations/V2.62/contracts/"
    "release-security-review-manifest.json"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV262ReleaseSurfaces(unittest.TestCase):
    def test_version_sync_uses_v262_current_projection_not_legacy_markers(self) -> None:
        sync = _load(VERSION_SYNC_PATH, "_test_v262_version_sync")
        args = argparse.Namespace(
            mode="candidate",
            published_version=None,
            candidate_commit=None,
        )
        with (
            mock.patch.object(sync, "parse_args", return_value=args),
            mock.patch.object(
                sync,
                "validate_runtime_identity",
                side_effect=AssertionError("legacy identity path invoked"),
            ),
            mock.patch("builtins.print"),
        ):
            sync.main()

    def test_current_validator_dispatches_v262_without_legacy_readme_checks(self) -> None:
        validator = _load(VALIDATE_PATH, "_test_v262_current_validator")
        self.assertEqual("V2.62", validator.CURRENT_VERSION)
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
                "V2.62",
            ],
            commands,
        )

    def test_current_release_readme_describes_v262_and_v26_predecessor(self) -> None:
        text = (ROOT / "scripts/release/README.md").read_text(encoding="utf-8")
        current = text.split("## V2.48 Skill 简单发行兼容", 1)[0]
        self.assertIn("V2.62 两阶段 Skill 发行", current)
        self.assertIn("--version V2.62", current)
        self.assertIn("docs/v2.62-release-runtime", current)
        self.assertIn("已安装 V2.6 Codex 宿主", current)
        self.assertNotIn("已安装 V2.52 Codex 宿主", current)
        self.assertIn("不是 V2.62\nCurrent Skill 发行默认入口", text)
        self.assertIn(
            "V2.62 是候选 `skill_simple` profile，V2.6 保持已安装基线直到 atomic cutover",
            text,
        )

    def test_security_denominator_covers_new_runtime_and_projection_code(self) -> None:
        manifest = json.loads(SECURITY_MANIFEST_PATH.read_text(encoding="utf-8"))
        runner = _load(SECURITY_RUNNER_PATH, "_test_v262_security_runner")
        targets = {item["path"] for item in manifest["review_targets"]}
        required = {
            "scripts/checks/check.sh",
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
            "scripts/v262/compatibility.py",
            "scripts/v262/project_host_assets.py",
            "scripts/v262/role_projections.py",
        }
        self.assertTrue(required.issubset(targets))
        self.assertEqual(targets, set(runner.MANDATORY_REVIEW_TARGETS))
        self.assertEqual(targets, set(release_flow.V250_SECURITY_REQUIRED_TARGET_PATHS))

    def test_current_full_regression_declares_v26_predecessor_tests_excluded(self) -> None:
        command = json.loads(
            (
                ROOT
                / "references/current/generations/V2.62/contracts/"
                "release-command-manifest.json"
            ).read_text(encoding="utf-8")
        )
        denominator = command["release"]["s1"]["current_full_regression_denominator"]
        self.assertEqual(
            ["tests/v250", "tests/v262"],
            denominator["test_roots"],
        )
        self.assertEqual(
            ["tests/v23", "tests/v249", "tests/v26"],
            denominator["legacy_roots_excluded"],
        )

        for relative in (
            ".github/workflows/check.yml",
            ".github/workflows/release-gate.yml",
            "scripts/checks/check.sh",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("tests/v250", text, relative)
            self.assertIn("tests/v262", text, relative)


if __name__ == "__main__":
    unittest.main()
