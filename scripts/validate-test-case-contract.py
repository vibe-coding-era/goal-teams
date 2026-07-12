#!/usr/bin/env python3
"""Compatibility entrypoint for the canonical V2.35 test-case validator."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).resolve().parent / "checks" / "validate-test-case-contract.py"),
        run_name="__main__",
    )
