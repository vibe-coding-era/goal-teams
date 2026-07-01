#!/usr/bin/env python3
"""Compatibility wrapper for scripts/checks/check-version-sync.py."""

from __future__ import annotations

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "checks" / "check-version-sync.py"), run_name="__main__")
