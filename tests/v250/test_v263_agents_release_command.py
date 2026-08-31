from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV263AgentsReleaseCommand(unittest.TestCase):
    def test_release_command_uses_authorized_local_predecessor_observation(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(
            "--route-facts-receipt <trusted-route-facts-receipt.json>",
            text,
        )
        self.assertIn(
            "--derived-route-receipt <trusted-derived-route-receipt.json>",
            text,
        )
        self.assertNotIn("--controller-handoff-receipt", text)
        self.assertIn("一次授权绑定的本地已安装 V2.66 状态", text)
        self.assertNotIn("externally-issued-v248-handoff", text)


if __name__ == "__main__":
    unittest.main()
