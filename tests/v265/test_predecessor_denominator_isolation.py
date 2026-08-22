from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATION = ROOT / "references/current/generations/V2.65"


class TestV265PredecessorDenominatorIsolation(unittest.TestCase):
    def test_v263_test_root_matches_published_activation_exactly(self) -> None:
        predecessor = json.loads(
            (
                ROOT
                / "references/current/generations/V2.63/activation-manifest.json"
            ).read_text(encoding="utf-8")
        )
        expected = {
            item["path"]: item["sha256"]
            for entries in predecessor["root_sets"].values()
            for item in entries
            if item["path"].startswith("tests/v263/")
            and Path(item["path"]).name.startswith("test_")
            and item["path"].endswith(".py")
        }
        self.assertEqual(7, len(expected))
        self.assertEqual(
            expected,
            {
                path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                for path in expected
            },
        )

    def test_current_s1_executes_only_current_and_shared_roots(self) -> None:
        command = json.loads(
            (GENERATION / "contracts/release-command-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        denominator = command["release"]["s1"]["current_full_regression_denominator"]
        self.assertEqual(["tests/v250", "tests/v265"], denominator["test_roots"])
        self.assertEqual(
            ["tests/v263"], denominator["published_predecessor_test_roots"]
        )
        self.assertEqual(0, denominator["predecessor_test_invocation_limit"])
        self.assertEqual(
            "references/current/generations/V2.65/contracts/predecessor-release-identity.json",
            denominator["predecessor_release_identity_path"],
        )

        for relative in (
            ".github/workflows/check.yml",
            ".github/workflows/release-gate.yml",
        ):
            workflow = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("tests.v263.", workflow, relative)
        checker = (ROOT / "scripts/checks/check.sh").read_text(encoding="utf-8")
        self.assertNotIn("discover -s tests/v263", checker)


if __name__ == "__main__":
    unittest.main()
