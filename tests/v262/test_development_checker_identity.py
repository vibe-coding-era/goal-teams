from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestV262DevelopmentCheckerIdentity(unittest.TestCase):
    def test_development_checker_reports_active_v262_identity(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/checks/check-v250.py", "--phase", "development"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual("V2.62", result["release_plan"]["generation_id"])
        self.assertIn("v2.62", result["schema_version"])


if __name__ == "__main__":
    unittest.main()
