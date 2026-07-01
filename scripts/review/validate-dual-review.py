#!/usr/bin/env python3
"""Validate LLM + script dual-review records."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REQUIRED_TOP_KEYS = {"artifact", "script_review", "llm_review", "final_decision"}
ALLOWED_DECISIONS = {"pass", "conditional", "blocked"}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"{path}: dual review record must be a JSON object")
    return data


def validate(data: dict[str, Any], label: str) -> None:
    missing = sorted(REQUIRED_TOP_KEYS - set(data))
    if missing:
        fail(f"{label}: missing keys: {', '.join(missing)}")
    script_review = data["script_review"]
    llm_review = data["llm_review"]
    final_decision = data["final_decision"]
    if not isinstance(script_review, dict):
        fail(f"{label}: script_review must be an object")
    if not isinstance(llm_review, dict):
        fail(f"{label}: llm_review must be an object")
    for key in ("tool", "status", "evidence_path"):
        if not script_review.get(key):
            fail(f"{label}: script_review.{key} is required")
    for key in ("reviewer", "status", "evidence_path", "summary"):
        if not llm_review.get(key):
            fail(f"{label}: llm_review.{key} is required")
    decision = final_decision.get("status") if isinstance(final_decision, dict) else None
    if decision not in ALLOWED_DECISIONS:
        fail(f"{label}: final_decision.status must be one of {sorted(ALLOWED_DECISIONS)}")
    if script_review.get("status") != "passed" and decision == "pass":
        fail(f"{label}: final decision cannot pass when script review did not pass")
    if llm_review.get("status") != "passed" and decision == "pass":
        fail(f"{label}: final decision cannot pass when LLM review did not pass")


def self_test() -> None:
    payload = {
        "artifact": "example",
        "script_review": {"tool": "compare-artifacts", "status": "passed", "evidence_path": "report.json"},
        "llm_review": {
            "reviewer": "评审-示例复核",
            "status": "passed",
            "evidence_path": "review.md",
            "summary": "结构与语义一致",
        },
        "final_decision": {"status": "pass", "reason": "both reviewers passed"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dual-review.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        validate(load_json(path), str(path))
    print("Dual-review validation self-test passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.paths:
        parser.error("at least one dual-review JSON file is required unless --self-test is used")
    for item in args.paths:
        path = Path(item)
        validate(load_json(path), str(path))
    print(f"Dual-review validation passed for {len(args.paths)} records.")


if __name__ == "__main__":
    main()
