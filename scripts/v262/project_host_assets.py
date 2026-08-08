#!/usr/bin/env python3
"""Generate or check deterministic V2.62 host-role projections."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v262.role_projections import check_role_projections, project_role_projections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = (
        check_role_projections(ROOT)
        if args.check
        else project_role_projections(ROOT)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not args.check or result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
