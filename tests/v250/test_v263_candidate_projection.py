"""V2.65 candidate projection over the published V2.63 release."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV263CandidateProjection(unittest.TestCase):
    def test_release_current_is_strict_candidate_or_strict_published_projection(self) -> None:
        manifest = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn(manifest.get("product_version"), {"V2.63", "V2.65"})
        self.assertEqual("V2.5", manifest["core_policy_version"])
        self.assertEqual("V2.3", manifest["legacy_data_schema_version"])
        self.assertEqual("release", manifest["status"])
        readme = (ROOT / "release/current/README.md").read_text(encoding="utf-8")
        if manifest["product_version"] == "V2.63":
            self.assertEqual(
                {
                    "candidate_product_version": "V2.65",
                    "candidate_release_state": "development_candidate_not_published",
                    "candidate_profile": "references/release-profiles/v2.65.json",
                },
                {
                    field: manifest.get(field)
                    for field in (
                        "candidate_product_version",
                        "candidate_release_state",
                        "candidate_profile",
                    )
                },
            )
            self.assertEqual("goal-teams-release-manifest-v2.63", manifest["schema_version"])
            self.assertEqual("v2.63", manifest["release_identity"]["tag"])
            self.assertEqual(369846737, manifest["release_identity"]["release_id"])
            self.assertTrue(readme.startswith("# Goal Teams V2.63 Release\n"))
            self.assertIn("V2.65 is an unpublished development candidate", readme)
        else:
            self.assertEqual("goal-teams-release-manifest-v2.65", manifest["schema_version"])
            self.assertTrue(
                {"candidate_product_version", "candidate_release_state", "candidate_profile"}.isdisjoint(manifest)
            )
            identity = manifest["release_identity"]
            self.assertEqual("v2.65", identity.get("tag"))
            self.assertEqual("published", identity.get("state"))
            self.assertIsInstance(identity.get("release_id"), int)
            self.assertGreater(identity["release_id"], 0)
            self.assertRegex(identity.get("source_commit", ""), r"^[0-9a-f]{40}$")
            self.assertRegex(identity.get("source_tree", ""), r"^[0-9a-f]{40}$")
            self.assertTrue(readme.startswith("# Goal Teams V2.65 Release\n"))

        self.assertEqual(
            [
                f"goal-teams-{manifest['product_version']}.tar.gz",
                "SHA256SUMS",
                "_release.json",
                "_files.sha256",
            ],
            manifest["release_identity"]["public_assets"],
        )
        for asset in manifest["release_identity"]["public_assets"]:
            self.assertIn(f"`{asset}`", readme)

    def test_release_projection_is_not_an_activation_or_runtime_static_input(self) -> None:
        from scripts.v250 import refresh_generation_manifests as refresh

        paths = refresh._generation_paths("V2.65")
        rule = refresh._refreshed_rule_manifest(paths, "V2.65")
        prompt = refresh._refreshed_prompt_manifest(paths, "V2.65")
        activation = refresh._refreshed_activation(
            paths,
            "V2.65",
            "V2.63",
            "inactive_candidate",
            rule,
            prompt,
        )
        members = {
            item["path"]
            for entries in activation["root_sets"].values()
            for item in entries
        }
        self.assertNotIn("release/current/manifest.json", members)
        self.assertNotIn("release/current/README.md", members)

        from scripts.release import skill_release

        self.assertNotIn(
            "release/current/manifest.json",
            skill_release.runtime_static_input_paths("V2.65"),
        )


if __name__ == "__main__":
    unittest.main()
