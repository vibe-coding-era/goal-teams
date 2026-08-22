from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.v250 import s4_executor


ROOT = Path(__file__).resolve().parents[2]
TARGET = "V2.65"
PREDECESSOR = "V2.63"


class TestV265S4Executor(unittest.TestCase):
    def test_s4_runtime_constants_are_bound_to_v265(self) -> None:
        self.assertEqual(TARGET, s4_executor.VERSION)
        self.assertEqual("v2.65", s4_executor.TAG)
        self.assertEqual("Goal Teams V2.65", s4_executor.TITLE)
        self.assertEqual(
            Path("references/release-profiles/v2.65.json"),
            s4_executor.RELEASE_PROFILE_RELATIVE,
        )
        self.assertTrue(s4_executor.CANONICAL_RELEASE_URL.endswith("/tag/v2.65"))

    def test_s4_requires_exact_v265_release_profile(self) -> None:
        path = ROOT / "references/release-profiles/v2.65.json"
        self.assertTrue(path.is_file(), "E_TEST_V265_S4_PROFILE_MISSING")
        profile = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(TARGET, profile["version"])
        self.assertEqual(PREDECESSOR, profile["published_before"])
        self.assertEqual("v2.65", profile["tag"])
        self.assertEqual("codex/develop-v2.65", profile["candidate_branch"])

    def test_s4_does_not_prebuild_candidate_snapshot_before_s2(self) -> None:
        snapshot = ROOT / "release/versions/V2.65"
        self.assertFalse(
            snapshot.exists(),
            "S2 must build the exact merged released SHA once; Development cannot prebuild it",
        )


if __name__ == "__main__":
    unittest.main()
