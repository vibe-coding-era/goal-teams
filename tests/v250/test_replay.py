from __future__ import annotations

import unittest

from scripts.v250.test_gate import validate_current_route_closure


class TestV250ReplayIsolation(unittest.TestCase):
    def test_current_route_without_legacy_input_passes(self) -> None:
        verdict = validate_current_route_closure(
            ["references/current/testing.md", "references/current/loop.md"]
        )

        self.assertTrue(verdict["ok"])
        self.assertEqual([], verdict["legacy_intersection"])

    def test_current_route_rejects_legacy_input(self) -> None:
        verdict = validate_current_route_closure(
            [
                "references/current/testing.md",
                "references/legacy-replay/V2.48/rules-testing.md",
            ]
        )

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_GENERATION_REPLAY_LEAK", verdict["errors"])

    def test_explicit_replay_may_load_legacy_input(self) -> None:
        legacy_path = "references/legacy-replay/V2.48/rules-testing.md"
        verdict = validate_current_route_closure(
            [legacy_path], replay_version="V2.48"
        )

        self.assertTrue(verdict["ok"])
        self.assertEqual([legacy_path], verdict["legacy_intersection"])


if __name__ == "__main__":
    unittest.main()
