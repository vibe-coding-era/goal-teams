#!/usr/bin/env python3
"""The fixed acceptance matrix (tests/acceptance.json): validate it, run it, print it.

  python3 tools/acceptance.py            # validate: 36 items, known statuses, every named test exists
  python3 tools/acceptance.py --run      # also run the named tests and settle each item's actual result
  python3 tools/acceptance.py --table    # print the matrix as a Markdown table

A claimed ``passed`` or ``partial`` item must name at least one test; ``--run`` reports the actual
outcome next to the claim so a claim can never outrun its evidence. Items are never deleted: a
retired risk stays in the file as ``not_required`` with a reason.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tests" / "acceptance.json"
STATUSES = ("passed", "partial", "not_run", "not_required", "blocked", "failed", "stale")
EXPECTED_IDS = ["AC%02d" % n for n in range(1, 37)]


def load() -> Dict[str, Any]:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def resolve(ref: str) -> Tuple[Any, str]:
    """``module.Class.test_method`` -> (TestCase class, method name); raises when it does not exist."""
    module_name, class_name, method = ref.rsplit(".", 2)
    sys.path.insert(0, str(ROOT))
    module = __import__("tests." + module_name, fromlist=[class_name])
    cls = getattr(module, class_name)
    if not hasattr(cls, method):
        raise AttributeError("%s has no %s" % (class_name, method))
    return cls, method


def validate(data: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    items = data.get("items") or []
    ids = [item.get("id") for item in items]
    if ids != EXPECTED_IDS:
        problems.append("items must be exactly AC01..AC36 in order (got %d: %s)" % (len(ids), ", ".join(map(str, ids[:5]))))
    for item in items:
        tag = item.get("id", "?")
        status = item.get("status")
        if status not in STATUSES:
            problems.append("%s: unknown status %r" % (tag, status))
        if not item.get("behavior"):
            problems.append("%s: missing behavior" % tag)
        if not item.get("reviews"):
            problems.append("%s: missing review references" % tag)
        if status in ("passed", "partial") and not item.get("tests"):
            problems.append("%s: claims %s but names no test" % (tag, status))
        if status == "not_required" and not item.get("reason"):
            problems.append("%s: not_required needs a reason" % tag)
        for ref in item.get("tests") or []:
            try:
                resolve(ref)
            except Exception as exc:  # noqa: BLE001 - any failure to resolve is a broken reference
                problems.append("%s: test %s cannot be resolved (%s)" % (tag, ref, exc))
    return problems


def run_tests(refs: List[str]) -> Dict[str, str]:
    """Run each referenced test once; ``{ref: "passed" | "failed" | "skipped"}``."""
    results: Dict[str, str] = {}
    for ref in refs:
        cls, method = resolve(ref)
        suite = unittest.TestSuite([cls(method)])
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        if result.skipped:
            results[ref] = "skipped"
        elif result.wasSuccessful():
            results[ref] = "passed"
        else:
            results[ref] = "failed"
    return results


def settle(item: Dict[str, Any], results: Dict[str, str]) -> str:
    """The actual status of an item given its tests' outcomes (the claim is never trusted blindly)."""
    refs = item.get("tests") or []
    if item.get("status") == "not_required":
        return "not_required"
    if not refs:
        return "not_run"
    outcomes = [results.get(ref, "not_run") for ref in refs]
    if any(o == "failed" for o in outcomes):
        return "failed"
    if any(o in ("skipped", "not_run") for o in outcomes):
        return "not_run"
    return "passed" if item.get("status") == "passed" else "partial"


def table(data: Dict[str, Any], results: Dict[str, str] = None) -> str:
    rows = ["| ID | 行为 | 评审 | 声明 | %s测试 |" % ("实测 | " if results is not None else ""),
            "|---|---|---|---|%s---|" % ("---|" if results is not None else "")]
    for item in data["items"]:
        cells = [item["id"], item["behavior"], " ".join(item["reviews"]), item["status"]]
        if results is not None:
            cells.append(settle(item, results))
        cells.append("<br>".join(item.get("tests") or []) or (item.get("note") or item.get("reason") or "—"))
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="store_true", help="run every named test and settle the actual status")
    parser.add_argument("--table", action="store_true", help="print the matrix as Markdown")
    parser.add_argument("--json", action="store_true", help="print the settled matrix as JSON")
    args = parser.parse_args(argv)
    data = load()
    problems = validate(data)
    if problems:
        print("acceptance.json problems:\n- " + "\n- ".join(problems))
        return 1
    results = None
    if args.run:
        refs = sorted({ref for item in data["items"] for ref in item.get("tests") or []})
        results = run_tests(refs)
    if args.table:
        print(table(data, results))
    elif args.json:
        out = [dict(item, actual=settle(item, results or {})) for item in data["items"]]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        counts: Dict[str, int] = {}
        for item in data["items"]:
            key = settle(item, results) if results is not None else item["status"]
            counts[key] = counts.get(key, 0) + 1
        label = "actual" if results is not None else "claimed"
        print("acceptance matrix: %d items, %s: %s" % (
            len(data["items"]), label, ", ".join("%s=%d" % kv for kv in sorted(counts.items()))))
        if results is not None:
            mismatch = [item["id"] for item in data["items"]
                        if item["status"] in ("passed", "partial") and settle(item, results) != item["status"]]
            if mismatch:
                print("claims not backed by a passing test: %s" % ", ".join(mismatch))
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
