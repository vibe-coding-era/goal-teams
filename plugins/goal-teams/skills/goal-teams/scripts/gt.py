#!/usr/bin/env python3
"""Goal Teams ``gt`` CLI entry point (Python 3.9+, stdlib only).

Usage: python3 <skill-dir>/scripts/gt.py <command> [options]   (gt --help)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from goalteams.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
