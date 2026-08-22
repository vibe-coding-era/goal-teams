from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV265CurrentReleaseClosure(unittest.TestCase):
    def test_release_profile_is_registered_for_v265(self) -> None:
        from scripts.release import release_config

        profile = release_config.release_config("V2.65")
        self.assertEqual("V2.65", profile["version"])
        self.assertEqual("V2.63", profile["published_before"])
        self.assertEqual("v2.65", profile["tag"])
        self.assertEqual("codex/develop-v2.65", profile["candidate_branch"])
        self.assertEqual("V2.5", profile["core_policy_version"])
        self.assertEqual("V2.3", profile["legacy_data_schema_version"])

    def test_default_package_selects_only_v265_current_and_execution(self) -> None:
        body = (ROOT / "scripts/install/package-manifest.txt").read_text(encoding="utf-8")
        required = {
            "prefix references/current/generations/V2.65/",
            "prefix references/compatibility/v2.65/",
            "file references/profiles/goal-teams-self-release-v2.65.md",
            "file references/release-profiles/v2.65.json",
            "prefix schemas/v2.65/",
            "prefix scripts/v265/",
            "prefix tests/v265/",
        }
        for line in required:
            self.assertIn(line, body)
        forbidden = {
            "prefix references/current/generations/V2.63/",
            "prefix references/compatibility/v2.63/",
            "prefix schemas/v2.63/",
            "prefix scripts/v263/",
            "prefix tests/v263/",
        }
        for line in forbidden:
            self.assertNotIn(line, body)

    def test_release_current_is_candidate_or_published_v265_projection(self) -> None:
        manifest = json.loads((ROOT / "release/current/manifest.json").read_text(encoding="utf-8"))
        self.assertIn(manifest["product_version"], {"V2.63", "V2.65"})
        if manifest["product_version"] == "V2.63":
            self.assertEqual("published", manifest["release_identity"]["state"])
            self.assertEqual("V2.65", manifest.get("candidate_product_version"))
            self.assertEqual(
                "development_candidate_not_published",
                manifest.get("candidate_release_state"),
            )
            self.assertEqual(
                "references/release-profiles/v2.65.json",
                manifest.get("candidate_profile"),
            )
        else:
            self.assertEqual("goal-teams-release-manifest-v2.65", manifest["schema_version"])
            self.assertEqual("v2.65", manifest["release_identity"]["tag"])
            self.assertEqual("published", manifest["release_identity"]["state"])

    def test_ci_and_release_workflow_are_v265_and_medium(self) -> None:
        check = (ROOT / ".github/workflows/check.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/release-gate.yml").read_text(encoding="utf-8")
        self.assertIn("Active V2.65 pre-release exact Development gate", check)
        self.assertIn("--generation-id V2.65", check)
        self.assertIn("Goal Teams V2.65 phase-aware verification", release)
        self.assertIn("codex/develop-v2.65", release)
        self.assertIn("default: medium", release)
        self.assertIn("tests.v265.test_graph_runtime", release)
        self.assertIn("tests.v265.test_current_release_closure", release)


if __name__ == "__main__":
    unittest.main()
