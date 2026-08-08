from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestV262ProjectionCli(unittest.TestCase):
    def test_direct_script_check_entrypoint_is_repo_root_independent(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/v262/project_host_assets.py"),
                "--check",
            ],
            cwd=ROOT.parent,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["ok"], receipt)


if __name__ == "__main__":
    unittest.main()
