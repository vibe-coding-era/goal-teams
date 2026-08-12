from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV263AgentsReleaseCommand(unittest.TestCase):
    def test_release_command_names_the_v263_handoff_not_legacy_v248(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(
            "--route-facts-receipt <trusted-route-facts-receipt.json>",
            text,
        )
        self.assertIn(
            "--derived-route-receipt <trusted-derived-route-receipt.json>",
            text,
        )
        self.assertIn(
            "--controller-handoff-receipt <externally-issued-v263-controller-handoff.json>",
            text,
        )
        self.assertNotIn("externally-issued-v248-handoff", text)


if __name__ == "__main__":
    unittest.main()
