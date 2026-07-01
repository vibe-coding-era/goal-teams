#!/usr/bin/env python3
"""Compatibility wrapper for scripts/benchmark/benchmark-runner.py."""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "benchmark" / "benchmark-runner.py"), run_name="__main__")
