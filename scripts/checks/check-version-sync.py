#!/usr/bin/env python3
"""Check version and startup identity synchronization."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

VERSION_FILES = [
    "SKILL.md",
    "goal-teams.md",
    "references/goal-teams-runtime.md",
    "prompts/lead/core.md",
    "agents/openai.yaml",
    "README.md",
    "README.en.md",
    "examples/mini-goal-run/README.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md",
]


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    version = read("VERSION").strip()
    if not re.fullmatch(r"V\d+\.\d+", version):
        fail(f"VERSION must look like Vx.y, got {version!r}")

    startup = (
        f"我是 Goal Teams Leader {version}，使用 Goal + Plan 模式帮你完成规划、执行和交付，"
        "并使用 Harness + SPEC 做为过程与结果产物的约束："
    )
    skill_versions = set(re.findall(r"\bV\d+(?:\.\d+)+\b", read("SKILL.md")))
    unexpected_skill_versions = sorted(found for found in skill_versions if found != version)
    if unexpected_skill_versions:
        fail(
            "SKILL.md version strings must match VERSION "
            f"{version!r}; unexpected: {', '.join(unexpected_skill_versions)}"
        )
    for path in VERSION_FILES:
        text = read(path)
        if version not in text:
            fail(f"{path} does not mention current version {version}")
        if startup not in text:
            fail(f"{path} missing current startup line")

    openai = read("agents/openai.yaml")
    if f'Goal Teams {version}' not in openai:
        fail("agents/openai.yaml display_name is not synchronized")
    if f"使用 $goal-teams {version}" not in openai:
        fail("agents/openai.yaml default prompt is not synchronized")

    print(f"Version synchronization passed for {version}.")


if __name__ == "__main__":
    main()
