#!/usr/bin/env python3
"""Validate the Goal Teams skill package structure."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    print("Python 3.11+ is required for tomllib", file=sys.stderr)
    sys.exit(2)


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "AGENTS.md",
    "SKILL.md",
    "README.md",
    "README.en.md",
    "goal-teams.md",
    "CHANGELOG.md",
    "agents/openai.yaml",
    "references/goal-teams-runtime.md",
    "references/default-AGENTS.md",
    "scripts/check.sh",
    "scripts/validate.py",
    "examples/mini-goal-run/README.md",
    "examples/mini-goal-run/.codex/goal-teams/INDEX.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/INDEX.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/tasklist.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/progress.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/decisions.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/requirement-spec-card.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/PRD.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/architecture-design.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/HTML-prototype.html",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/test-plan.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/acceptance.md",
]

EXPECTED_SUBAGENTS = {
    "goal-backend.toml": "goal_backend",
    "goal-docs.toml": "goal_docs",
    "goal-frontend.toml": "goal_frontend",
    "goal-product.toml": "goal_product",
    "goal-qa.toml": "goal_qa",
    "goal-requirements-analyst.toml": "goal_requirements_analyst",
    "goal-reviewer.toml": "goal_reviewer",
}

KEY_RULES = [
    "Requirement Specification Card",
    "references/default-AGENTS.md",
    "Teams 规划表",
    "后端-WIKI 列表后端开发",
    "独立校验",
    "中文",
    "版本",
    "INDEX.md",
    "tasklist.md",
]

README_RELEASE_ITEMS = [
    "SKILL.md",
    "agents/openai.yaml",
    "references/goal-teams-runtime.md",
    "references/default-AGENTS.md",
    "subagents/goal-*.toml",
    "goal-teams.md",
    "AGENTS.md",
    "scripts/check.sh",
    "scripts/validate.py",
    "examples/mini-goal-run",
    "CHANGELOG.md",
    "README.md",
    "README.en.md",
]


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_required_files() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        fail("Missing required files: " + ", ".join(missing))


def check_skill_frontmatter() -> None:
    skill = read("SKILL.md")
    match = re.match(r"^---\n(?P<body>.*?)\n---\n", skill, flags=re.S)
    if not match:
        fail("SKILL.md must start with YAML frontmatter")
    body = match.group("body")
    for key in ("name: goal-teams", "description:"):
        if key not in body:
            fail(f"SKILL.md frontmatter missing {key!r}")
    if len(body.split("description:", 1)[1].strip()) < 80:
        fail("SKILL.md description is too short for skill discovery")


def check_subagents() -> None:
    subagent_dir = ROOT / "subagents"
    actual = {path.name for path in subagent_dir.glob("goal-*.toml")}
    expected = set(EXPECTED_SUBAGENTS)
    if actual != expected:
        fail(f"Subagent set mismatch. expected={sorted(expected)} actual={sorted(actual)}")
    for filename, expected_name in EXPECTED_SUBAGENTS.items():
        path = subagent_dir / filename
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in ("name", "description", "developer_instructions"):
            if key not in data:
                fail(f"{path} missing {key}")
        if data["name"] != expected_name:
            fail(f"{path} name should be {expected_name}, got {data['name']}")
        if "Chinese" not in data["developer_instructions"] and "中文" not in data["developer_instructions"]:
            fail(f"{path} does not mention Chinese output")
        if "validation" not in data["developer_instructions"] and "校验" not in data["developer_instructions"]:
            fail(f"{path} does not mention independent validation")


def check_readmes() -> None:
    zh = read("README.md")
    en = read("README.en.md")
    for item in README_RELEASE_ITEMS:
        if item not in zh:
            fail(f"README.md release/usage docs missing {item}")
        if item not in en:
            fail(f"README.en.md release/usage docs missing {item}")
    for snippet in ("./scripts/check.sh", "examples/mini-goal-run", "goal-teams.md"):
        if snippet not in zh or snippet not in en:
            fail(f"READMEs must mention {snippet}")


def check_key_rules() -> None:
    combined = "\n".join(
        read(path)
        for path in [
            "goal-teams.md",
            "SKILL.md",
            "references/goal-teams-runtime.md",
            "references/default-AGENTS.md",
            "README.md",
            "README.en.md",
        ]
    )
    for rule in KEY_RULES:
        if rule not in combined:
            fail(f"Key rule missing from docs: {rule}")
    stale_examples = ["需求分析-规格卡", "产品-PRD", "前端-订单页面", "测试-验收证据"]
    for stale in stale_examples:
        if stale in combined:
            fail(f"Stale generic member-name example found: {stale}")


def check_example() -> None:
    html = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/HTML-prototype.html")
    if "<!doctype html>" not in html.lower():
        fail("Example HTML prototype must be a complete HTML document")
    state_path = ROOT / "examples/mini-goal-run/.codex/goal-teams/team-state.json"
    if state_path.exists():
        json.loads(state_path.read_text(encoding="utf-8"))


def main() -> None:
    check_required_files()
    check_skill_frontmatter()
    check_subagents()
    check_readmes()
    check_key_rules()
    check_example()
    print("Goal Teams validation passed.")


if __name__ == "__main__":
    main()
