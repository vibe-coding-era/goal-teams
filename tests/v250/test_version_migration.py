from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV250VersionMigration(unittest.TestCase):
    def test_v263_current_identity_is_complete_and_predecessors_are_not_default(self) -> None:
        self.assertEqual(
            "V2.63",
            (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        )

        active = json.loads(
            (ROOT / "references/current/ACTIVE.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("V2.63", active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.63/activation-manifest.json",
            active["activation_manifest"],
        )

        profile = json.loads(
            (ROOT / "references/release-profiles/v2.63.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("V2.63", profile["version"])
        self.assertEqual("v2.63", profile["tag"])
        self.assertEqual("V2.62", profile["published_before"])
        self.assertEqual("codex/develop-v2.63", profile["candidate_branch"])

        for relative in (
            "references/current/generations/V2.63/activation-manifest.json",
            "schemas/v2.50/release-control.schema.json",
            "scripts/v250/s4_executor.py",
            "tests/v250/test_s4_executor.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

        package_manifest = (
            ROOT / "scripts/install/package-manifest.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("prefix references/current/generations/V2.63/", package_manifest)
        self.assertIn("prefix schemas/v2.50/", package_manifest)
        self.assertIn("prefix scripts/v250/", package_manifest)
        self.assertIn("prefix tests/v250/", package_manifest)
        self.assertIn("prefix schemas/v2.63/", package_manifest)
        self.assertIn("prefix scripts/v263/", package_manifest)
        self.assertIn("prefix tests/v263/", package_manifest)
        self.assertNotIn(
            "prefix references/current/generations/V2.62/",
            package_manifest,
        )
        self.assertNotIn("prefix scripts/v262/", package_manifest)
        self.assertNotIn("prefix tests/v262/", package_manifest)
        self.assertNotIn(
            "prefix references/current/generations/V2.49/",
            package_manifest,
        )
        self.assertNotIn("prefix scripts/v249/", package_manifest)
        self.assertNotIn("prefix tests/v249/", package_manifest)
        self.assertNotIn("prefix references/current/generations/V2.6/", package_manifest)
        self.assertNotIn("prefix scripts/v26/", package_manifest)
        self.assertNotIn("prefix tests/v26/", package_manifest)


if __name__ == "__main__":
    unittest.main()
