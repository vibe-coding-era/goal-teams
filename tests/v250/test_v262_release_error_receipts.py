from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/release/skill_release.py"


class TestV262ReleaseErrorReceipts(unittest.TestCase):
    def test_predecessor_plan_failure_preserves_cli_command_identity(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "plan",
                "--version",
                "V2.6",
                "--commit",
                "1" * 40,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, result.returncode)
        receipt = json.loads(result.stdout)
        self.assertEqual("E_SKILL_RELEASE_PREDECESSOR_FLOW_UNAVAILABLE", receipt["error_code"])
        self.assertEqual("plan", receipt["command"])
        self.assertEqual(0, receipt["persistent_local_mutation_count"])
        self.assertEqual(0, receipt["external_mutation_count"])


if __name__ == "__main__":
    unittest.main()
