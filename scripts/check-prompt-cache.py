#!/usr/bin/env python3
"""Compatibility entrypoint for the V2.38 prompt-cache check."""

from pathlib import Path
import runpy
import sys

previous = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    runpy.run_path(
        str(Path(__file__).resolve().parent / "checks" / "check-prompt-cache.py"),
        run_name="__main__",
    )
finally:
    sys.dont_write_bytecode = previous
