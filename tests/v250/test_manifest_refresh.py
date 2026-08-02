from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV250ManifestRefresh(unittest.TestCase):
    def test_generation_manifests_are_deterministically_current(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/v250/refresh_generation_manifests.py",
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
