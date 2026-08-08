from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV262PublishedProjection(unittest.TestCase):
    def test_release_current_projects_the_exact_published_v262_identity(self) -> None:
        manifest = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual("goal-teams-release-manifest-v2.62", manifest["schema_version"])
        self.assertEqual("V2.62", manifest["product_version"])
        self.assertEqual("V2.5", manifest["core_policy_version"])
        self.assertEqual("V2.3", manifest["legacy_data_schema_version"])
        self.assertEqual("release", manifest["status"])
        self.assertEqual(
            {
                "tag": "v2.62",
                "release_id": 367112913,
                "state": "published",
                "source_commit": "bd4eedfc0623e74b74efeaf157edf92ce2be1e74",
                "source_tree": "58d11881eeda2f0a018fcc4273ce2f3982977f94",
                "public_assets": [
                    "goal-teams-V2.62.tar.gz",
                    "SHA256SUMS",
                    "_release.json",
                    "_files.sha256",
                ],
            },
            manifest["release_identity"],
        )
        self.assertFalse(any(key.startswith("candidate_") for key in manifest))

        readme = (ROOT / "release/current/README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# Goal Teams V2.62 Release\n"))
        self.assertIn("V2.62 is the current published product release.", readme)
        self.assertNotIn("V2.62 release candidate", readme)
        for asset in manifest["release_identity"]["public_assets"]:
            self.assertIn(f"`{asset}`", readme)


if __name__ == "__main__":
    unittest.main()
