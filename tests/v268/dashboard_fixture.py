"""Portable V2.68 fixtures for the unchanged V2.67 dashboard input contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "tests/v268/fixtures/dashboard"


def _fixture(name: str) -> str:
    return f"{FIXTURE}/{name}"


def _sha(name: str) -> str:
    return hashlib.sha256((ROOT / _fixture(name)).read_bytes()).hexdigest()


def _view() -> dict[str, object]:
    return {
        "schema_version": "goal-teams-output-dashboard-v2.67",
        "mode": "execution",
        "project": "goal-teams",
        "dashboard": {
            "completed_tasks": 1,
            "total_tasks": 4,
            "completed_subtasks": 6,
            "total_subtasks": 14,
            "tasklist_ref": {
                "label": "完整任务",
                "href": _fixture("TaskList.md"),
            },
            "state_machine_ref": {
                "label": "状态机",
                "href": _fixture("state-machine.json"),
            },
            "active_rows": [
                {
                    "row_kind": "task",
                    "task_id": "AUTH",
                    "parent_task_id": None,
                    "priority": "P0",
                    "name": "账户登录与鉴权",
                    "members": ["goal_backend"],
                    "parallel": False,
                    "in_progress": 2,
                    "remaining": 3,
                },
                {
                    "row_kind": "subtask",
                    "task_id": "AUTH-TOKEN",
                    "parent_task_id": "AUTH",
                    "priority": "P0",
                    "name": "Token 刷新",
                    "members": ["goal_backend"],
                    "parallel": True,
                    "in_progress": 1,
                    "remaining": 1,
                },
                {
                    "row_kind": "subtask",
                    "task_id": "AUTH-SECURITY",
                    "parent_task_id": "AUTH",
                    "priority": "P0",
                    "name": "异常登录安全验证",
                    "members": ["goal_security"],
                    "parallel": True,
                    "in_progress": 1,
                    "remaining": 2,
                },
                {
                    "row_kind": "task",
                    "task_id": "SEARCH",
                    "parent_task_id": None,
                    "priority": "P1",
                    "name": "商品检索",
                    "members": ["goal_api_integration_test_runner"],
                    "parallel": False,
                    "in_progress": 1,
                    "remaining": 1,
                },
            ],
        },
        "context": {
            "core_rules": [
                {"label": "SKILL.md", "href": "SKILL.md"},
                {"label": "RULES.md", "href": "RULES.md"},
                {
                    "label": "ACTIVE.json",
                    "href": "references/current/ACTIVE.json",
                },
            ],
            "project_knowledge": [
                {"label": "requirements.md", "href": _fixture("requirements.md")},
                {"label": "architecture.md", "href": _fixture("architecture.md")},
                {"label": "memory.md", "href": _fixture("memory.md")},
            ],
            "codebase": {
                "label": "goal-teams",
                "href": "https://github.com/vibe-coding-era/goal-teams",
            },
            "tools": [
                {
                    "tool_kind": "MCP",
                    "label": "filesystem",
                    "href": _fixture("filesystem-mcp.md"),
                },
                {
                    "tool_kind": "CLI",
                    "label": "goal-teams check",
                    "href": _fixture("goal-teams-check.md"),
                },
                {
                    "tool_kind": "API",
                    "label": "POST /api/auth/login",
                    "href": _fixture("auth-login-api.md"),
                },
            ],
        },
        "loop": {
            "current_round": 2,
            "estimated_total_rounds": 4,
            "plan": "修复 Token 刷新并完成安全重验证",
            "do": "进行中任务 2｜进行中子任务 3",
            "new_evidence_count": 4,
            "gap_count": 3,
            "blocked_count": 1,
            "decision": "continue",
            "evidence_ref": {
                "label": "evidence.json",
                "href": _fixture("evidence.json"),
            },
            "banchmark_ref": {
                "label": "Banchmark.md",
                "href": _fixture("Banchmark.md"),
            },
            "loop_review_ref": {
                "label": "loop-review.md",
                "href": _fixture("loop-review.md"),
            },
        },
        "bindings": {
            "tasklist_sha256": _sha("TaskList.md"),
            "state_machine_sha256": _sha("state-machine.json"),
            "evidence_sha256": _sha("evidence.json"),
            "banchmark_sha256": _sha("Banchmark.md"),
            "loop_review_sha256": _sha("loop-review.md"),
            "freshness": "current",
        },
    }
