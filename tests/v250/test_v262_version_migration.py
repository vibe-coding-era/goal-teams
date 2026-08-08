from __future__ import annotations

import hashlib
import importlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET_VERSION = "V2.62"
GENERATION = ROOT / "references" / "current" / "generations" / TARGET_VERSION
PROTECTED_README_SHA256 = {
    "README.md": "eb1a9737261e68431a7e91b2104aca5575d47eb5b52498e836e4be8378b71820",
    "README.en.md": "e0fabc8a00a009eb75bddf68a71adc4b048126ede44ed8c5449a3b12df7c166e",
}


def _target(testcase: unittest.TestCase):
    try:
        return importlib.import_module("scripts.v250.okf_document_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v250.okf_document_graph":
            testcase.fail("E_KG262_TARGET_MISSING: scripts.v250.okf_document_graph")
        raise


class TestV262VersionMigration(unittest.TestCase):
    def test_product_current_and_release_projection_are_v262(self) -> None:
        self.assertEqual(TARGET_VERSION, (ROOT / "VERSION").read_text().strip())
        active = json.loads(
            (ROOT / "references/current/ACTIVE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(TARGET_VERSION, active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.62/activation-manifest.json",
            active["activation_manifest"],
        )
        activation_path = ROOT / active["activation_manifest"]
        self.assertTrue(activation_path.is_file())
        self.assertEqual(
            active["activation_manifest_sha256"],
            hashlib.sha256(activation_path.read_bytes()).hexdigest(),
        )
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        self.assertEqual(TARGET_VERSION, activation["generation_id"])
        self.assertEqual(
            TARGET_VERSION, activation["identity"]["loaded_runtime_product_version"]
        )
        self.assertEqual(
            TARGET_VERSION, activation["identity"]["target_policy_generation"]
        )

        release = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        if release["product_version"] == "V2.6":
            self.assertEqual(TARGET_VERSION, release["candidate_product_version"])
            self.assertEqual(
                "v250_release_readiness",
                release["candidate_release_state"],
            )
        else:
            self.assertEqual(TARGET_VERSION, release["product_version"])
            self.assertEqual("published", release["release_identity"]["state"])
        self.assertEqual("V2.5", release["core_policy_version"])
        self.assertEqual("V2.3", release["legacy_data_schema_version"])
        self.assertIn(TARGET_VERSION, (ROOT / "release/current/README.md").read_text())

    def test_skill_identity_and_frontmatter_are_closed_without_touching_readmes(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        frontmatter = skill.split("---", 2)[1]
        keys = [
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if line.strip()
        ]
        self.assertEqual(["name", "description"], keys)
        self.assertIn("Goal Teams V2.62", skill)
        self.assertIn("我是 Goal Teams Lead V2.62。", skill)
        self.assertIn(
            "V2.62",
            (ROOT / ".agents/skills/goal-teams/SKILL.md").read_text(encoding="utf-8"),
        )
        self.assertIn("产品版本：`V2.62`", (ROOT / "AGENTS.md").read_text())
        self.assertIn("V2.62", (ROOT / "agents/openai.yaml").read_text())
        for path, expected in PROTECTED_README_SHA256.items():
            self.assertEqual(
                expected,
                hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                f"human-owned {path} changed",
            )

    def test_current_has_one_knowledge_graph_owner_and_no_legacy_prompt_dependency(self) -> None:
        owner = GENERATION / "functions" / "knowledge-graph.md"
        self.assertTrue(owner.is_file())
        self.assertIn("Observe-only", owner.read_text(encoding="utf-8"))
        prompt_manifest = json.loads(
            (GENERATION / "prompt-manifest.json").read_text(encoding="utf-8")
        )
        rule_manifest = json.loads(
            (GENERATION / "rule-manifest.json").read_text(encoding="utf-8")
        )
        rendered = json.dumps(
            {"prompt": prompt_manifest, "rule": rule_manifest},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertIn("functions/knowledge-graph.md", rendered)
        self.assertNotIn("legacy-replay", rendered)
        owner_mentions = [
            path
            for path in GENERATION.rglob("*.md")
            if "OKF Document Graph" in path.read_text(encoding="utf-8")
        ]
        self.assertIn(owner, owner_mentions)

    def test_execution_core_stays_v250_and_package_includes_v262_current(self) -> None:
        package = (ROOT / "scripts/install/package-manifest.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("prefix references/current/generations/V2.62/", package)
        self.assertIn("references/profiles/goal-teams-self-release-v2.62.md", package)
        self.assertIn("references/release-profiles/v2.62.json", package)
        self.assertIn("prefix scripts/v250/", package)
        self.assertIn("prefix schemas/v2.50/", package)
        self.assertIn("prefix tests/v250/", package)
        self.assertIn("prefix scripts/v262/", package)
        self.assertIn("prefix schemas/v2.62/", package)
        self.assertIn("prefix tests/v262/", package)
        self.assertIn("prefix references/compatibility/v2.62/", package)
        self.assertNotIn("references/legacy-replay", package)
        self.assertTrue(
            (ROOT / "schemas/v2.50/okf-document-graph.schema.json").is_file()
        )
        self.assertTrue((ROOT / "scripts/v250/okf_document_graph.py").is_file())
        self.assertTrue((ROOT / "scripts/v262").is_dir())
        self.assertTrue((ROOT / "schemas/v2.62").is_dir())
        self.assertTrue((ROOT / "tests/v262").is_dir())
        self.assertTrue((ROOT / "references/compatibility/v2.62").is_dir())

    def test_v262_release_profile_and_changelog_declare_the_feature_truthfully(self) -> None:
        profile = json.loads(
            (ROOT / "references/release-profiles/v2.62.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(TARGET_VERSION, profile["version"])
        self.assertIn("Goal Teams V2.62", profile["release_title"])
        self.assertIn(
            "V2.62",
            (ROOT / "references/profiles/goal-teams-self-release-v2.62.md").read_text(),
        )
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("V2.62", changelog)
        self.assertIn("OKF Document Graph", changelog)
        self.assertIn("No database", changelog)
        self.assertIn("Observe-only", changelog)

    def test_runtime_module_exports_only_the_frozen_public_entrypoints(self) -> None:
        kg = _target(self)
        for name in (
            "GraphSecurityError",
            "normalize_nfc17",
            "pct_segment",
            "load_current_graph",
            "load_replay_graph",
        ):
            self.assertTrue(hasattr(kg, name), name)


if __name__ == "__main__":
    unittest.main()
