#!/usr/bin/env python3
"""Require immutable, reviewed commit pins for external GitHub Actions."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOW = ROOT / ".github" / "workflows" / "check.yml"
EXPECTED_ACTIONS = {
    "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",  # v4.3.1
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",  # v5.6.0
}
USES_PATTERN = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)(?:\s+#.*)?$")
REMOTE_ACTION_PATTERN = re.compile(r"^(?P<action>[^@]+)@(?P<ref>[^@]+)$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def validate(workflow: Path) -> list[str]:
    if not workflow.is_file():
        return ["E_CI_WORKFLOW_MISSING"]
    errors: list[str] = []
    observed: dict[str, list[str]] = {}
    for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
        match = USES_PATTERN.match(line)
        if not match:
            continue
        target = match.group(1)
        if target.startswith("./"):
            continue
        remote = REMOTE_ACTION_PATTERN.match(target)
        if not remote:
            errors.append(f"E_CI_ACTION_REF:{number}")
            continue
        action = remote.group("action")
        ref = remote.group("ref")
        observed.setdefault(action, []).append(ref)
        if not COMMIT_PATTERN.fullmatch(ref):
            errors.append(f"E_CI_ACTION_NOT_IMMUTABLE:{action}:{number}")

    for action, expected_ref in EXPECTED_ACTIONS.items():
        refs = observed.get(action, [])
        if len(refs) != 1:
            errors.append(f"E_CI_ACTION_COUNT:{action}:{len(refs)}")
        elif refs[0] != expected_ref:
            errors.append(f"E_CI_ACTION_UNREVIEWED_SHA:{action}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    args = parser.parse_args()
    errors = validate(args.workflow.resolve())
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        raise SystemExit(1)
    print("GitHub Actions immutable commit pins validated.")


if __name__ == "__main__":
    main()
