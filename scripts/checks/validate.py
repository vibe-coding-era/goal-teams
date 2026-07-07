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


ROOT = Path(__file__).resolve().parents[2]
CURRENT_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
STARTUP_LINE = (
    f"我是 Goal Teams Leader {CURRENT_VERSION}，使用 Goal + Plan 模式帮你完成规划、执行和交付应用开发，"
    "并使用 Harness + SPEC 做为过程与结果产物的约束："
)
PLAN_HISTORY_LINE = "在开始规划前，如果有什么历史文档、历史经验或参考资料需要输入吗？"
CHINESE_CORE_LINE = (
    "默认全程中文表格化输出计划、tasklist、SPEC、进度、成员包、最终总结、生成文档、代码注释、"
    "面向用户的字符串、测试名和测试用例说明；"
)

REQUIRED_FILES = [
    "AGENTS.md",
    "RULES.md",
    "VERSION",
    "SKILL.md",
    "README.md",
    "README.en.md",
    "goal-teams.md",
    "CHANGELOG.md",
    "agents/openai.yaml",
    "references/goal-teams-runtime.md",
    "references/default-AGENTS.md",
    "references/goal-teams-automation-protocol.md",
    "references/goal-teams-production-pipeline.md",
    "references/goal-teams-scripted-tooling.md",
    "references/google-okf-bilingual-spec.md",
    "references/ui-e2e-pixel-protocol.md",
    "references/ui-visual-contract-protocol.md",
    "references/subagent-dispatch-protocol.md",
    "references/dual-review-protocol.md",
    "prompts/lead/core.md",
    "prompts/lead/planning.md",
    "prompts/lead/loop.md",
    "prompts/lead/requirement-card.md",
    "prompts/lead/dispatch.md",
    "prompts/lead/audit.md",
    "prompts/lead/completion.md",
    "prompts/members/shared.md",
    "prompts/members/requirements-analyst/prompt.md",
    "prompts/members/product/prompt.md",
    "prompts/members/backend/prompt.md",
    "prompts/members/frontend/prompt.md",
    "prompts/members/unit-test-designer/prompt.md",
    "prompts/members/unit-test-runner/prompt.md",
    "prompts/members/api-integration-test-designer/prompt.md",
    "prompts/members/api-integration-test-runner/prompt.md",
    "prompts/members/e2e-test-designer/prompt.md",
    "prompts/members/e2e-test-runner/prompt.md",
    "prompts/members/qa/prompt.md",
    "prompts/members/docs/prompt.md",
    "prompts/members/reviewer/prompt.md",
    "prompts/members/completion-auditor/prompt.md",
    "prompts/packets/member-goal-packet.md",
    "prompts/packets/handoff-artifacts.md",
    "prompts/packets/page-spec-card.md",
    "prompts/packets/memory.md",
    "prompts/packets/html-prototype-mock.md",
    "prompts/packets/requirement-card.md",
    "prompts/packets/doc-capsule.md",
    "prompts/packets/harness-contract.md",
    "prompts/packets/team-plan-table.md",
    "prompts/packets/dual-review-record.md",
    "scripts/check.sh",
    "scripts/validate.py",
    "scripts/install-local.sh",
    "scripts/check-version-sync.py",
    "scripts/check-agent-names.py",
    "scripts/validate-harness.py",
    "scripts/pixel-diff.py",
    "scripts/benchmark-runner.py",
    "scripts/checks/check.sh",
    "scripts/checks/validate.py",
    "scripts/checks/check-version-sync.py",
    "scripts/checks/check-agent-names.py",
    "scripts/checks/check-member-layout.py",
    "scripts/harness/validate-harness.py",
    "scripts/harness/pixel-diff.py",
    "scripts/benchmark/benchmark-runner.py",
    "scripts/review/compare-artifacts.py",
    "scripts/review/validate-dual-review.py",
    "scripts/install/install-local.sh",
    "scripts/check-member-layout.py",
    "scripts/compare-artifacts.py",
    "scripts/validate-dual-review.py",
    "examples/mini-goal-run/README.md",
    "examples/mini-goal-run/.codex/goal-teams/INDEX.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/INDEX.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/tasklist.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/progress.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/decisions.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/README.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/setup.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/run.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/checks.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/report.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/automation-protocol.sample.yaml",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/evidence-ledger.sample.json",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/pipeline-gates.sample.yaml",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/requirement-card.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/requirement-spec-card.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/PRD.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/architecture-design.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/HTML-prototype.html",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/test-plan.md",
    "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/acceptance.md",
    "benchmarks/README.md",
    "benchmarks/tasks/GT-BENCH-001/task.md",
    "benchmarks/tasks/GT-BENCH-001/harness.md",
    "benchmarks/tasks/GT-BENCH-001/scoring.md",
    "benchmarks/tasks/GT-BENCH-001/expected-artifacts.md",
    "benchmarks/tasks/GT-BENCH-002/task.md",
    "benchmarks/tasks/GT-BENCH-002/harness.md",
    "benchmarks/tasks/GT-BENCH-002/scoring.md",
    "benchmarks/tasks/GT-BENCH-002/expected-artifacts.md",
    "benchmarks/tasks/GT-BENCH-003/task.md",
    "benchmarks/tasks/GT-BENCH-003/harness.md",
    "benchmarks/tasks/GT-BENCH-003/scoring.md",
    "benchmarks/tasks/GT-BENCH-003/expected-artifacts.md",
    "benchmarks/tasks/GT-BENCH-004/task.md",
    "benchmarks/tasks/GT-BENCH-004/harness.md",
    "benchmarks/tasks/GT-BENCH-004/scoring.md",
    "benchmarks/tasks/GT-BENCH-004/expected-artifacts.md",
]

EXPECTED_SUBAGENTS = {
    "goal-backend.toml": "goal_backend",
    "goal-completion-auditor.toml": "goal_completion_auditor",
    "goal-docs.toml": "goal_docs",
    "goal-e2e-test-designer.toml": "goal_e2e_test_designer",
    "goal-e2e-test-runner.toml": "goal_e2e_test_runner",
    "goal-frontend.toml": "goal_frontend",
    "goal-api-integration-test-designer.toml": "goal_api_integration_test_designer",
    "goal-api-integration-test-runner.toml": "goal_api_integration_test_runner",
    "goal-product.toml": "goal_product",
    "goal-qa.toml": "goal_qa",
    "goal-requirements-analyst.toml": "goal_requirements_analyst",
    "goal-reviewer.toml": "goal_reviewer",
    "goal-unit-test-designer.toml": "goal_unit_test_designer",
    "goal-unit-test-runner.toml": "goal_unit_test_runner",
}

EXPECTED_ROLE_PREFIXES = {
    "goal_backend": "后端",
    "goal_completion_auditor": "收尾",
    "goal_docs": "文档",
    "goal_e2e_test_designer": "E2E用例",
    "goal_e2e_test_runner": "E2E执行",
    "goal_frontend": "前端",
    "goal_api_integration_test_designer": "API集成测试",
    "goal_api_integration_test_runner": "API集成测试",
    "goal_product": "产品",
    "goal_qa": "测试",
    "goal_requirements_analyst": "需求分析",
    "goal_reviewer": "评审",
    "goal_unit_test_designer": "单测设计",
    "goal_unit_test_runner": "单测执行",
}

KEY_RULES = [
    f"Goal Teams Leader {CURRENT_VERSION}",
    STARTUP_LINE,
    "RULES.md",
    "Response Contract",
    "响应规范",
    "Execute first",
    "执行优先",
    "Report facts only",
    "只汇报事实",
    "Not verified",
    PLAN_HISTORY_LINE,
    CHINESE_CORE_LINE,
    "需求卡片",
    "核心目标",
    "关键功能",
    "用户故事",
    "功能验收标准",
    "作为",
    "我想要",
    "以便",
    "边界",
    "约束",
    "风险",
    "spec/requirement-card.md",
    "GoalTeamsWork-<project_version>",
    "versions/<artifact_version>",
    "TaskList.md",
    "memory.md",
    "author: GoalTeams",
    "Google OKF",
    "Open Knowledge Format",
    "Knowledge Catalog",
    "references/google-okf-bilingual-spec.md",
    "prompts/packets/memory.md",
    "prompts/packets/html-prototype-mock.md",
    "HTML Prototype MOCK",
    "组件库",
    "component_library",
    "application/okf+yaml",
    "data-component-library",
    "prompts/lead/requirement-card.md",
    "prompts/packets/requirement-card.md",
    "中文优先",
    "Requirement Specification Card",
    "Harness Contract",
    "Benchmark",
    "Skill Improvement Loop",
    "Lead LOOP",
    "Loop Decision",
    "Loop Gate",
    "loop-state.json",
    "prompts/lead/loop.md",
    "complete | continue_same_scope | replan | blocked_needs_user | stop_budget | deferred",
    "block_completion_when_evidence_missing",
    "stop_when_budget_exceeded",
    "harness.yaml",
    "evidence.jsonl",
    "pipeline-state.json",
    "approval_gate",
    "Build -> Verify -> Package -> Release Gate -> Observe -> Promote/Rollback",
    "Release Gate",
    "safety gate",
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
    "Reviewer C",
    "transport handle",
    "右边栏",
    "goal_*",
    "成员：<中文展示名>",
    "界面级任务",
    "E2E",
    "复刻",
    "像素级对比",
    "基准图",
    "diff 图",
    "scripts/install-local.sh",
    "scripts/install/install-local.sh",
    "scripts/check-version-sync.py",
    "scripts/checks/check-version-sync.py",
    "scripts/check-agent-names.py",
    "scripts/checks/check-agent-names.py",
    "scripts/validate-harness.py",
    "scripts/harness/validate-harness.py",
    "scripts/pixel-diff.py",
    "scripts/harness/pixel-diff.py",
    "scripts/benchmark-runner.py",
    "scripts/benchmark/benchmark-runner.py",
    "references/goal-teams-scripted-tooling.md",
    "references/ui-e2e-pixel-protocol.md",
    "references/ui-visual-contract-protocol.md",
    "references/subagent-dispatch-protocol.md",
    "references/dual-review-protocol.md",
    "prompts/lead/core.md",
    "prompts/lead/requirement-card.md",
    "prompts/members/shared.md",
    "prompts/members/backend/prompt.md",
    "prompts/members/backend/template.md",
    "prompts/members/backend/workflow.md",
    "prompts/members/backend/scripts.md",
    "prompts/packets/member-goal-packet.md",
    "prompts/packets/handoff-artifacts.md",
    "prompts/packets/page-spec-card.md",
    "prompts/packets/memory.md",
    "prompts/packets/html-prototype-mock.md",
    "prompts/packets/requirement-card.md",
    "prompts/packets/dual-review-record.md",
    "Single Source of Truth",
    "page-spec-card.md",
    "Page Specification Card",
    "UI 视觉防漏协议",
    "组件级视觉契约",
    "交互状态矩阵",
    "locked screenshot",
    "unlocked real DOM screenshot",
    "局部 crop",
    "几何断言",
    "owner_subagent",
    "validator_subagent",
    "handoff_status",
    "independent_check_status",
    "Budget Gate",
    "Conflict Policy",
    "证据不足不能完成",
    "LLM + 脚本",
    "双重复核",
    "scripts/review/compare-artifacts.py",
    "scripts/review/validate-dual-review.py",
    "scripts/checks/check-member-layout.py",
    "GT-BENCH-003",
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
    "index.md",
    "tasklist.md",
    "后端架构设计",
    "frontend_architecture_design",
    "backend_architecture_design",
    "后端 TDD",
    "backend_unit_test_cases",
    "backend_unit_test_execution",
    "goal_unit_test_designer",
    "goal_unit_test_runner",
    "API 集成测试脚本生成",
    "api_integration_test_script",
    "api_integration_test_execution",
    "goal_api_integration_test_designer",
    "goal_api_integration_test_runner",
    "Python + pytest",
    "E2E 测试用例",
    "e2e_test_cases",
    "e2e_test_execution",
    "goal_e2e_test_designer",
    "goal_e2e_test_runner",
    "BugFix",
    "test_report",
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
    "RULES.md",
    "agents/openai.yaml",
    "references/goal-teams-runtime.md",
    "references/default-AGENTS.md",
    "references/goal-teams-automation-protocol.md",
    "references/goal-teams-production-pipeline.md",
    "references/goal-teams-scripted-tooling.md",
    "references/google-okf-bilingual-spec.md",
    "references/ui-e2e-pixel-protocol.md",
    "references/ui-visual-contract-protocol.md",
    "references/subagent-dispatch-protocol.md",
    "references/dual-review-protocol.md",
    "subagents/goal-*.toml",
    "goal-teams.md",
    "AGENTS.md",
    "scripts/check.sh",
    "scripts/validate.py",
    "scripts/install-local.sh",
    "scripts/check-version-sync.py",
    "scripts/check-agent-names.py",
    "scripts/check-member-layout.py",
    "scripts/validate-harness.py",
    "scripts/pixel-diff.py",
    "scripts/compare-artifacts.py",
    "scripts/validate-dual-review.py",
    "scripts/benchmark-runner.py",
    "scripts/checks/",
    "scripts/harness/",
    "scripts/benchmark/",
    "scripts/review/",
    "scripts/install/",
    "prompts/",
    "prompts/lead/core.md",
    "prompts/lead/requirement-card.md",
    "prompts/members/shared.md",
    "prompts/members/backend/prompt.md",
    "prompts/members/backend/template.md",
    "prompts/members/unit-test-designer/prompt.md",
    "prompts/members/unit-test-runner/prompt.md",
    "prompts/members/api-integration-test-designer/prompt.md",
    "prompts/members/api-integration-test-runner/prompt.md",
    "prompts/members/e2e-test-designer/prompt.md",
    "prompts/members/e2e-test-runner/prompt.md",
    "prompts/packets/member-goal-packet.md",
    "prompts/packets/handoff-artifacts.md",
    "prompts/packets/page-spec-card.md",
    "prompts/packets/memory.md",
    "prompts/packets/html-prototype-mock.md",
    "prompts/packets/requirement-card.md",
    "prompts/packets/dual-review-record.md",
    "examples/mini-goal-run",
    "benchmarks/",
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
    if not re.fullmatch(r"V\d+\.\d+", version):
        fail(f"VERSION should look like Vx.y, got {version!r}")
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
    markdown_body = skill[match.end():]
    line_count = len(markdown_body.splitlines())
    if line_count > 190:
        fail(f"SKILL.md body should stay as a compact progressive loader, got {line_count} lines")
    for route in (
        "RULES.md",
        "prompts/lead/core.md",
        "prompts/lead/planning.md",
        "prompts/lead/requirement-card.md",
        "prompts/members/shared.md",
        "prompts/members/backend/prompt.md",
        "prompts/members/backend/template.md",
        "prompts/members/unit-test-designer/prompt.md",
        "prompts/members/unit-test-runner/prompt.md",
        "prompts/members/api-integration-test-designer/prompt.md",
        "prompts/members/api-integration-test-runner/prompt.md",
        "prompts/members/e2e-test-designer/prompt.md",
        "prompts/members/e2e-test-runner/prompt.md",
        "prompts/packets/member-goal-packet.md",
        "prompts/packets/handoff-artifacts.md",
        "prompts/packets/page-spec-card.md",
        "prompts/packets/memory.md",
        "prompts/packets/html-prototype-mock.md",
        "prompts/packets/requirement-card.md",
        "prompts/packets/dual-review-record.md",
        "references/ui-visual-contract-protocol.md",
        "references/google-okf-bilingual-spec.md",
        "scripts/harness/pixel-diff.py",
        "scripts/review/validate-dual-review.py",
    ):
        if route not in markdown_body:
            fail(f"SKILL.md progressive loading route missing {route}")


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
        if "transport handle" not in data["developer_instructions"]:
            fail(f"{path} does not mention transport handle for runtime nicknames")
        if expected_name in {"goal_frontend", "goal_e2e_test_designer", "goal_e2e_test_runner", "goal_qa", "goal_reviewer", "goal_completion_auditor"}:
            for snippet in ("E2E", "像素级对比"):
                if snippet not in data["developer_instructions"]:
                    fail(f"{path} missing UI verification rule: {snippet}")
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
    combined = "\n".join(
        read(path)
        for path in [
            "VERSION",
            "RULES.md",
            "goal-teams.md",
            "SKILL.md",
            "references/goal-teams-runtime.md",
            "agents/openai.yaml",
            "references/default-AGENTS.md",
            "references/goal-teams-scripted-tooling.md",
            "references/google-okf-bilingual-spec.md",
            "references/ui-e2e-pixel-protocol.md",
            "references/ui-visual-contract-protocol.md",
            "references/subagent-dispatch-protocol.md",
            "references/dual-review-protocol.md",
            "prompts/lead/core.md",
            "prompts/lead/planning.md",
            "prompts/lead/loop.md",
            "prompts/lead/requirement-card.md",
            "prompts/lead/dispatch.md",
            "prompts/lead/audit.md",
            "prompts/lead/completion.md",
            "prompts/members/shared.md",
            "prompts/members/requirements-analyst/prompt.md",
            "prompts/members/product/prompt.md",
            "prompts/members/backend/prompt.md",
            "prompts/members/backend/template.md",
            "prompts/members/backend/workflow.md",
            "prompts/members/backend/scripts.md",
            "prompts/members/frontend/prompt.md",
            "prompts/members/frontend/template.md",
            "prompts/members/frontend/workflow.md",
            "prompts/members/frontend/scripts.md",
            "prompts/members/unit-test-designer/prompt.md",
            "prompts/members/unit-test-designer/template.md",
            "prompts/members/unit-test-designer/workflow.md",
            "prompts/members/unit-test-designer/scripts.md",
            "prompts/members/unit-test-runner/prompt.md",
            "prompts/members/unit-test-runner/template.md",
            "prompts/members/unit-test-runner/workflow.md",
            "prompts/members/unit-test-runner/scripts.md",
            "prompts/members/api-integration-test-designer/prompt.md",
            "prompts/members/api-integration-test-designer/template.md",
            "prompts/members/api-integration-test-designer/workflow.md",
            "prompts/members/api-integration-test-designer/scripts.md",
            "prompts/members/api-integration-test-runner/prompt.md",
            "prompts/members/api-integration-test-runner/template.md",
            "prompts/members/api-integration-test-runner/workflow.md",
            "prompts/members/api-integration-test-runner/scripts.md",
            "prompts/members/e2e-test-designer/prompt.md",
            "prompts/members/e2e-test-designer/template.md",
            "prompts/members/e2e-test-designer/workflow.md",
            "prompts/members/e2e-test-designer/scripts.md",
            "prompts/members/e2e-test-runner/prompt.md",
            "prompts/members/e2e-test-runner/template.md",
            "prompts/members/e2e-test-runner/workflow.md",
            "prompts/members/e2e-test-runner/scripts.md",
            "prompts/members/qa/prompt.md",
            "prompts/members/qa/template.md",
            "prompts/members/qa/workflow.md",
            "prompts/members/qa/scripts.md",
            "prompts/members/docs/prompt.md",
            "prompts/members/reviewer/prompt.md",
            "prompts/members/completion-auditor/prompt.md",
            "prompts/packets/member-goal-packet.md",
            "prompts/packets/handoff-artifacts.md",
            "prompts/packets/page-spec-card.md",
            "prompts/packets/memory.md",
            "prompts/packets/html-prototype-mock.md",
            "prompts/packets/requirement-card.md",
            "prompts/packets/doc-capsule.md",
            "prompts/packets/harness-contract.md",
            "prompts/packets/team-plan-table.md",
            "prompts/packets/dual-review-record.md",
            "README.md",
            "README.en.md",
            "CHANGELOG.md",
        ]
    )
    for rule in KEY_RULES:
        if rule not in combined:
            fail(f"Key rule missing from docs: {rule}")
    for path in [
        "SKILL.md",
        "references/goal-teams-runtime.md",
        "prompts/lead/core.md",
        "agents/openai.yaml",
        "README.md",
        "README.en.md",
        "goal-teams.md",
        "examples/mini-goal-run/README.md",
        "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md",
    ]:
        if STARTUP_LINE not in read(path):
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
    example_plan = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/plan.md")
    if STARTUP_LINE not in example_plan:
        fail(f"Example plan must use the current {CURRENT_VERSION} startup line")
    requirement_card = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/requirement-card.md")
    for snippet in ("核心目标", "关键功能", "用户故事", "功能验收标准", "边界", "约束", "风险"):
        if snippet not in requirement_card:
            fail(f"Example requirement card missing {snippet}")
    requirement_spec = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/requirement-spec-card.md")
    prd = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/PRD.md")
    test_plan = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/test-plan.md")
    for snippet in ("用户故事", "功能验收标准", "US-001", "AC-001"):
        if snippet not in requirement_spec:
            fail(f"Example requirement specification missing {snippet}")
        if snippet not in prd:
            fail(f"Example PRD missing {snippet}")
    for snippet in ("AC-001", "AC-002", "AC-003"):
        if snippet not in test_plan:
            fail(f"Example test plan missing functional acceptance coverage: {snippet}")
    if "spec/requirement-card.md" not in example_plan:
        fail("Example plan must reference the requirement card path")
    example_tasklist = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/tasklist.md")
    for snippet in (
        "Harness Contract",
        "GT-001",
        "GT-006",
        "GT-008",
        "not_applicable_reason",
        "Handoff Artifact Ledger",
        "prompts/packets/handoff-artifacts.md",
        "Owner Subagent",
        "Validator Subagent",
        "Independent Check Status",
    ):
        if snippet not in example_tasklist:
            fail(f"Example tasklist missing Harness coverage: {snippet}")
    html = read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/HTML-prototype.html")
    if "<!doctype html>" not in html.lower():
        fail("Example HTML prototype must be a complete HTML document")
    harness = "\n".join(
        read(path)
        for path in [
            "examples/mini-goal-run/README.md",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/README.md",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/setup.md",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/run.md",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/checks.md",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/report.md",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/automation-protocol.sample.yaml",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/pipeline-gates.sample.yaml",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/progress.md",
            "examples/mini-goal-run/.codex/goal-teams/versions/V0.1/spec/acceptance.md",
        ]
    )
    for snippet in (
        "setup -> run -> checks -> report",
        "Harness",
        "GT-006",
        "acceptance",
        "sample_only",
        "pipeline",
        "no_runner",
    ):
        if snippet not in harness:
            fail(f"Example Harness missing {snippet}")
    evidence_sample = json.loads(
        read("examples/mini-goal-run/.codex/goal-teams/versions/V0.1/harness/evidence-ledger.sample.json")
    )
    if not evidence_sample.get("sample_only"):
        fail("Example evidence ledger must be marked sample_only")
    if "artifacts" not in evidence_sample or not evidence_sample["artifacts"]:
        fail("Example evidence ledger must include artifact records")
    state_path = ROOT / "examples/mini-goal-run/.codex/goal-teams/team-state.json"
    if state_path.exists():
        json.loads(state_path.read_text(encoding="utf-8"))
    benchmark = "\n".join(
        read(path)
        for path in [
            "benchmarks/README.md",
            "benchmarks/tasks/GT-BENCH-001/task.md",
            "benchmarks/tasks/GT-BENCH-001/harness.md",
            "benchmarks/tasks/GT-BENCH-001/scoring.md",
            "benchmarks/tasks/GT-BENCH-001/expected-artifacts.md",
            "benchmarks/tasks/GT-BENCH-002/task.md",
            "benchmarks/tasks/GT-BENCH-002/harness.md",
            "benchmarks/tasks/GT-BENCH-002/scoring.md",
            "benchmarks/tasks/GT-BENCH-002/expected-artifacts.md",
            "benchmarks/tasks/GT-BENCH-003/task.md",
            "benchmarks/tasks/GT-BENCH-003/harness.md",
            "benchmarks/tasks/GT-BENCH-003/scoring.md",
            "benchmarks/tasks/GT-BENCH-003/expected-artifacts.md",
            "benchmarks/tasks/GT-BENCH-004/task.md",
            "benchmarks/tasks/GT-BENCH-004/harness.md",
            "benchmarks/tasks/GT-BENCH-004/scoring.md",
            "benchmarks/tasks/GT-BENCH-004/expected-artifacts.md",
        ]
    )
    for snippet in (
        "GT-BENCH-001",
        "GT-BENCH-002",
        "GT-BENCH-003",
        "GT-BENCH-004",
        "baseline",
        "goal-teams",
        "goal-teams-v2.1-loop",
        "scoring",
        "tokens",
        "release gate",
        "pipeline-gates",
        "pixel",
        "Loop Decision",
        "Loop Gate",
        "loop-state.json",
        "complete",
        "continue_same_scope",
        "replan",
        "blocked_needs_user",
        "stop_budget",
        "deferred",
    ):
        if snippet not in benchmark:
            fail(f"Benchmark template missing {snippet}")


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
