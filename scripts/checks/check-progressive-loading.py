#!/usr/bin/env python3
"""Validate progressive member indexes, context budgets, and local-only docs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ROOT / "prompts" / "members"
ROLE_FILES = ("prompt.md", "template.md", "workflow.md", "scripts.md")
MAX_SINGLE_MARKDOWN_BYTES = 64 * 1024
MAX_MEMBER_INDEX_BYTES = 4 * 1024


def fail(message: str) -> None:
    print(json.dumps({"passed": False, "error": message}, ensure_ascii=False))
    raise SystemExit(1)


def main() -> None:
    errors: list[str] = []
    for role_dir in sorted(path for path in MEMBERS.iterdir() if path.is_dir()):
        index = role_dir / "INDEX.md"
        if not index.is_file():
            errors.append(f"missing member index: {index.relative_to(ROOT)}")
            continue
        text = index.read_text(encoding="utf-8")
        if index.stat().st_size > MAX_MEMBER_INDEX_BYTES:
            errors.append(f"member index too large: {index.relative_to(ROOT)}")
        for name in ROLE_FILES:
            if f"`{name}`" not in text:
                errors.append(f"member index missing {name}: {index.relative_to(ROOT)}")
        for field in ("role:", "description:", "triggers:", "rules:", "forbidden:", "inputs:", "outputs:", "validator:"):
            if field not in text:
                errors.append(f"member index missing {field}: {index.relative_to(ROOT)}")
        if "具体职责与完成边界以" in text:
            errors.append(f"member index uses placeholder description: {index.relative_to(ROOT)}")

    oversized = []
    for path in ROOT.rglob("*.md"):
        if any(part in {".git", "docs"} or part.startswith("GoalTeamsWork-") for part in path.parts):
            continue
        if path.stat().st_size > MAX_SINGLE_MARKDOWN_BYTES:
            oversized.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size})
    if oversized:
        errors.append(f"oversized shipped markdown: {oversized}")

    tracked_docs = []
    if (ROOT / ".git").exists():
        tracked_docs = subprocess.run(
            ["git", "ls-files", "docs"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.splitlines()
    elif (ROOT / "docs").exists():
        errors.append("gitless install package contains local-only docs")
    if tracked_docs:
        errors.append(f"docs must be local-only, but Git tracks: {tracked_docs}")

    result = {
        "schema_version": "goal-teams-progressive-loading-v2.38",
        "member_count": len([path for path in MEMBERS.iterdir() if path.is_dir()]),
        "max_single_markdown_bytes": MAX_SINGLE_MARKDOWN_BYTES,
        "max_member_index_bytes": MAX_MEMBER_INDEX_BYTES,
        "tracked_docs": tracked_docs,
        "passed": not errors,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
