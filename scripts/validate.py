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
    "VERSION",
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
    "goal-completion-auditor.toml": "goal_completion_auditor",
    "goal-docs.toml": "goal_docs",
    "goal-frontend.toml": "goal_frontend",
    "goal-product.toml": "goal_product",
    "goal-qa.toml": "goal_qa",
    "goal-requirements-analyst.toml": "goal_requirements_analyst",
    "goal-reviewer.toml": "goal_reviewer",
}

EXPECTED_ROLE_PREFIXES = {
    "goal_backend": "后端",
    "goal_completion_auditor": "收尾",
    "goal_docs": "文档",
    "goal_frontend": "前端",
    "goal_product": "产品",
    "goal_qa": "测试",
    "goal_requirements_analyst": "需求分析",
    "goal_reviewer": "评审",
}

KEY_RULES = [
    "Goal Teams Leader V1.4",
    "我是 Goal Teams Leader V1.4，我会帮你完成以下工作：",
    "在开始规划前，有什么历史文档、历史经验或参考资料需要输入吗？",
    "中文优先",
    "Requirement Specification Card",
    "references/default-AGENTS.md",
    "Teams 规划表",
    "成员 / Skill/Subagent",
    "任务范围",
    "交付与标准",
    "验证安排",
    "workflow",
    "前置任务",
    "goal_completion_auditor",
    "自动续跑",
    "未完成工作",
    "后端-WIKI 列表后端开发",
    "browser-WIKI 列表页面验证",
    "运行时 subagent id",
    "skill_or_subagent",
    "独立校验",
    "直接执行",
    "数字选项",
    "确认并执行",
    "中文核心模型要点提示词",
    "资源消耗（用户 / tokens / 费用）",
    "中文",
    "版本",
    "INDEX.md",
    "tasklist.md",
]

CHINESE_SURFACE_FILES = [
    "SKILL.md",
    "references/goal-teams-runtime.md",
    "agents/openai.yaml",
]

STALE_ENGLISH_SURFACE_SNIPPETS = [
    "Use this skill when",
    "Core Model",
    "Mandatory Plan Mode",
    "SPEC First",
    "No Tasklist Assumption",
    "Teams Planning Confirmation",
    "When To Use",
    "Runtime Files",
    "Goal Team Workflow",
    "Stable Core Prompt",
    "Completion Rules",
    "This reference defines",
    "Runtime Shape",
    "Language And Persistence",
    "Tasklist Discovery And Creation",
    "Markdown Persistence Templates",
    "Confirmation Tables",
    "Progress Feedback Tables",
    "Cache-Friendly Prompt Layout",
    "Document Loading Manifest",
    "Safety And Coordination",
    "Completion Response",
    "Act as an independent",
    "Use Chinese by default",
    "Return files changed",
    "Member, Claimed Tasks",
    "| Member | Claimed Tasks | Status | Current Step | Evidence | Next |",
    "| Item | Status | Suggestion |",
    "| Artifact | Author | Validator | Method | Status | Evidence |",
]

README_RELEASE_ITEMS = [
    "VERSION",
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
    version = read("VERSION").strip()
    if version != "V1.4":
        fail(f"VERSION should be V1.4, got {version!r}")
    match = re.match(r"^---\n(?P<body>.*?)\n---\n", skill, flags=re.S)
    if not match:
        fail("SKILL.md must start with YAML frontmatter")
    body = match.group("body")
    fields = []
    values = {}
    for line in body.splitlines():
        if not line.strip():
            continue
        field_match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not field_match:
            fail(f"SKILL.md frontmatter has unsupported YAML line: {line!r}")
        field, value = field_match.groups()
        fields.append(field)
        values[field] = value.strip()
    if fields != ["name", "description"]:
        fail(f"SKILL.md frontmatter must contain only name and description, got {fields!r}")
    if values["name"] != "goal-teams":
        fail(f"SKILL.md frontmatter name should be 'goal-teams', got {values['name']!r}")
    if len(values["description"]) < 80:
        fail("SKILL.md description is too short for skill discovery")
    if not re.search(r"[\u4e00-\u9fff]", values["description"]):
        fail("SKILL.md description should be Chinese-first")
    if len(body) > 500:
        fail(f"SKILL.md frontmatter should stay compact, got {len(body)} characters")


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
        if "中文" not in data["description"] and "中文" not in data["developer_instructions"]:
            fail(f"{path} does not mention Chinese output")
        if "校验" not in data["developer_instructions"]:
            fail(f"{path} does not mention independent validation")
        role_prefix = EXPECTED_ROLE_PREFIXES[data["name"]]
        for candidate in data.get("nickname_candidates", []):
            if not candidate.startswith(role_prefix + "-"):
                fail(f"{path} nickname candidate should start with Chinese role prefix {role_prefix!r}: {candidate}")
        for stale in STALE_ENGLISH_SURFACE_SNIPPETS:
            if stale in data["description"] or stale in data["developer_instructions"]:
                fail(f"{path} contains stale English instruction: {stale}")


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
    startup_line = "我是 Goal Teams Leader V1.4，我会帮你完成以下工作："
    combined = "\n".join(
        read(path)
        for path in [
            "VERSION",
            "goal-teams.md",
            "SKILL.md",
            "references/goal-teams-runtime.md",
            "agents/openai.yaml",
            "references/default-AGENTS.md",
            "README.md",
            "README.en.md",
            "CHANGELOG.md",
        ]
    )
    for rule in KEY_RULES:
        if rule not in combined:
            fail(f"Key rule missing from docs: {rule}")
    for path in ["SKILL.md", "references/goal-teams-runtime.md", "agents/openai.yaml", "README.md", "README.en.md", "goal-teams.md"]:
        if startup_line not in read(path):
            fail(f"Startup line missing from {path}")
    stale_examples = [
        "需求分析-规格卡",
        "产品-PRD",
        "前端-订单页面",
        "测试-验收证据",
        "goal_requirements_analyst-WIKI 列表需求澄清",
        "goal_product-WIKI 列表 PRD",
        "goal_backend-WIKI 列表后端开发",
        "goal_frontend-WIKI 列表页面开发",
        "goal_qa-WIKI 列表验收测试",
        "goal_docs-WIKI 列表验收文档",
        "goal_reviewer-WIKI 列表代码审查",
        "goal_completion_auditor-WIKI 列表未完成工作检查",
        "subagent ID + 具体任务名",
        "| Member | Skill/Subagent | Goal Slice | Claimed Tasks | Locked Scope | Deliverable | Done Criteria | Docs/Tasklist Updates | Test Owner | Validator |",
        "| 成员 | Skill/Subagent | 目标切片 | 认领任务 | 锁定范围 | 交付物 | 完成标准 | 文档/tasklist 更新 | 测试 Owner | 校验者 |",
    ]
    for stale in stale_examples:
        if stale in combined:
            fail(f"Stale generic member-name example found: {stale}")


def check_chinese_surface() -> None:
    for path in CHINESE_SURFACE_FILES:
        text = read(path)
        if not re.search(r"[\u4e00-\u9fff]", text):
            fail(f"{path} should contain Chinese instructions")
        for stale in STALE_ENGLISH_SURFACE_SNIPPETS:
            if stale in text:
                fail(f"{path} contains stale English surface text: {stale}")

    for path in (ROOT / "subagents").glob("goal-*.toml"):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"[\u4e00-\u9fff]", text):
            fail(f"{path} should contain Chinese instructions")


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
    check_chinese_surface()
    check_example()
    print("Goal Teams validation passed.")


if __name__ == "__main__":
    main()
