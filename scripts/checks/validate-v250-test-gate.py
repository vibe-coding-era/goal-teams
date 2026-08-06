#!/usr/bin/env python3
"""Thin CLI for the V2.52 current-generation test-gate validator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v250.test_gate import build_tdd_chain, validate_test_chain


def _strict_load(path: Path) -> dict:
    def no_duplicates(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate key: {key}")
            value[key] = item
        return value

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
    if not isinstance(value, dict):
        raise ValueError("test chain must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            document = build_tdd_chain(
                "DEN-V250-SELF",
                "TC-V250-SELF",
                "1" * 64,
                "2" * 64,
                "3" * 64,
                "4" * 64,
            )
        elif args.path:
            document = _strict_load(Path(args.path))
        else:
            raise ValueError("path or --self-test is required")
        result = validate_test_chain(document)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result = {
            "ok": False,
            "error_code": "E_V250_TEST_CHAIN_INPUT",
            "errors": ["E_V250_TEST_CHAIN_INPUT"],
            "input_error": type(exc).__name__,
            "mutation_count": 0,
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
