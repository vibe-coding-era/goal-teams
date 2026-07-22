#!/usr/bin/env python3
"""Compatibility entry point for the V2.43 engineering-metrics calculator."""

from __future__ import annotations

import runpy
from pathlib import Path


runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "v23" / "engineering_metrics.py"),
    run_name="__main__",
)
