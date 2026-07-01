#!/usr/bin/env python3
"""Check V1.94 member prompt package layout."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ROLES = [
    "requirements-analyst",
    "product",
    "backend",
    "frontend",
    "unit-test-designer",
    "unit-test-runner",
    "api-integration-test-designer",
    "api-integration-test-runner",
    "e2e-test-designer",
    "e2e-test-runner",
    "qa",
    "docs",
    "reviewer",
    "completion-auditor",
]
REQUIRED_MEMBER_FILES = ["prompt.md", "template.md", "workflow.md", "scripts.md"]


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def main() -> None:
    members_root = ROOT / "prompts" / "members"
    if not (members_root / "shared.md").is_file():
        fail("prompts/members/shared.md is required")
    for role in ROLES:
        role_dir = members_root / role
        if not role_dir.is_dir():
            fail(f"Missing member directory: {role_dir}")
        for filename in REQUIRED_MEMBER_FILES:
            path = role_dir / filename
            if not path.is_file():
                fail(f"Missing member package file: {path}")
            text = path.read_text(encoding="utf-8")
            if len(text.strip()) < 40:
                fail(f"Member package file is too small: {path}")
            if filename == "scripts.md" and "scripts/" not in text:
                fail(f"Member scripts file must reference deterministic scripts: {path}")
        flat_file = members_root / f"{role}.md"
        if flat_file.exists():
            fail(f"Flat member prompt should be migrated into directory package: {flat_file}")
    print(f"Member layout validation passed for {len(ROLES)} roles.")


if __name__ == "__main__":
    main()
