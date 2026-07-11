#!/usr/bin/env python3
"""Run the independent V2.3 unittest and mutation release-gate suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = ROOT / "tests" / "v23"


def main() -> int:
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        str(TEST_DIR),
        "-p",
        "test_*.py",
        "-v",
    ]
    proc = subprocess.run(command, cwd=ROOT, check=False)
    if proc.returncode != 0:
        print("V2.3 release gates failed closed; see unittest failures above.", file=sys.stderr)
        return proc.returncode
    print("V2.3 unittest and canonical mutation release gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
