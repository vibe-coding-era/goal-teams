from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = "V2.63"
GENERATION = ROOT / "references/current/generations/V2.63"
PROTECTED_README_SHA256 = {
    "README.md": "b41fe4de55832b561b077fff0a4c41659bc11058c560ba6b01f982003c6089af",
    "README.en.md": "b31c0a6d58375282f0ec60e06d74bb7a33179828e0f2def65c4c5c3743f33ec3",
}


class TestV263VersionMigration(unittest.TestCase):
    def test_product_current_bootstrap_and_human_readme_boundary(self) -> None:
        self.assertEqual(TARGET, (ROOT / "VERSION").read_text().strip())
        for relative in (
            "SKILL.md",
            ".agents/skills/goal-teams/SKILL.md",
            "RULES.md",
            "goal-teams.md",
            "AGENTS.md",
            "agents/openai.yaml",
        ):
            self.assertIn(TARGET, (ROOT / relative).read_text(encoding="utf-8"), relative)
        for relative, digest in PROTECTED_README_SHA256.items():
            self.assertEqual(digest, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest())

        active = json.loads((ROOT / "references/current/ACTIVE.json").read_text())
        self.assertEqual(TARGET, active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.63/activation-manifest.json",
            active["activation_manifest"],
        )
        activation_path = ROOT / active["activation_manifest"]
        self.assertEqual(
            active["activation_manifest_sha256"],
            hashlib.sha256(activation_path.read_bytes()).hexdigest(),
        )
        activation = json.loads(activation_path.read_text())
        self.assertEqual(TARGET, activation["generation_id"])
        self.assertEqual(TARGET, activation["identity"]["loaded_runtime_product_version"])
        self.assertEqual("V2.5", activation["identity"]["core_policy_version"])
        self.assertEqual("V2.3", activation["identity"]["legacy_data_schema_version"])

    def test_current_manifests_package_and_compatibility_projection_are_v263(self) -> None:
        prompt = json.loads((GENERATION / "prompt-manifest.json").read_text())
        rule = json.loads((GENERATION / "rule-manifest.json").read_text())
        rendered = json.dumps({"prompt": prompt, "rule": rule}, sort_keys=True)
        self.assertEqual(TARGET, prompt["generation_id"])
        self.assertEqual(TARGET, rule["generation_id"])
        self.assertNotIn("legacy-replay", rendered)

        package = (ROOT / "scripts/install/package-manifest.txt").read_text()
        for marker in (
            "product V2.63, core policy V2.5, legacy data schema V2.3",
            "prefix references/current/generations/V2.63/",
            "references/profiles/goal-teams-self-release-v2.63.md",
            "references/release-profiles/v2.63.json",
            "prefix scripts/v250/",
            "prefix schemas/v2.50/",
            "prefix tests/v250/",
            "prefix scripts/v263/",
            "prefix schemas/v2.63/",
            "prefix tests/v263/",
            "prefix references/compatibility/v2.63/",
        ):
            self.assertIn(marker, package)
        for stale in (
            "prefix references/current/generations/V2.62/",
            "prefix scripts/v262/",
            "prefix schemas/v2.62/",
            "prefix tests/v262/",
            "prefix references/compatibility/v2.62/",
            "references/legacy-replay",
        ):
            self.assertNotIn(stale, package)

    def test_release_candidate_profile_and_changelog_are_truthful(self) -> None:
        profile = json.loads((ROOT / "references/release-profiles/v2.63.json").read_text())
        self.assertEqual(TARGET, profile["version"])
        self.assertEqual("v2.63", profile["tag"])
        self.assertEqual("V2.62", profile["published_before"])
        self.assertEqual("V2.5", profile["core_policy_version"])
        self.assertEqual("V2.3", profile["legacy_data_schema_version"])
        release = json.loads((ROOT / "release/current/manifest.json").read_text())
        if release["product_version"] == "V2.62":
            self.assertEqual(TARGET, release["candidate_product_version"])
            self.assertNotEqual("published", release["candidate_release_state"])
        else:
            self.assertEqual(TARGET, release["product_version"])
            self.assertEqual("published", release["release_identity"]["state"])
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn("## V2.63", changelog)
        self.assertIn("drift", changelog.lower())


if __name__ == "__main__":
    unittest.main()
