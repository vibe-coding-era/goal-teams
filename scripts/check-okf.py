#!/usr/bin/env python3
"""Compatibility entry point for scripts/checks/check-okf.py."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


if __name__ == "__main__":
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        runpy.run_path(
            str(Path(__file__).resolve().parent / "checks" / "check-okf.py"),
            run_name="__main__",
        )
    finally:
        sys.dont_write_bytecode = previous
