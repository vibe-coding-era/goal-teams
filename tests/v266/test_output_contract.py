from __future__ import annotations

import copy
import hashlib
import importlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
FIXTURE = "tests/v266/fixtures/dashboard"


def _fixture(name: str) -> str:
    return f"{FIXTURE}/{name}"


def _sha(name: str) -> str:
    return hashlib.sha256((ROOT / _fixture(name)).read_bytes()).hexdigest()


def _target():
    try:
        return importlib.import_module("scripts.v266.output_dashboard")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v266" or str(exc.name).startswith("scripts.v266."):
            raise AssertionError("E_TEST_V266_OUTPUT_TARGET_MISSING") from exc
        raise


def _view() -> dict[str, object]:
    return {
        "schema_version": "goal-teams-output-dashboard-v2.66",
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


class TestV266OutputContract(unittest.TestCase):
    def test_skill_and_rules_declare_v266_output_control(self) -> None:
        self.assertEqual("V2.66", (ROOT / "VERSION").read_text().strip())
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        rules = (ROOT / "RULES.md").read_text(encoding="utf-8")
        task_state = (
            ROOT
            / "references/current/generations/V2.66/contracts/task-state.md"
        ).read_text(encoding="utf-8")
        for text in (skill, rules, task_state):
            self.assertIn("◆ Goal-Teams 任务执行看板", text)
            self.assertIn("◆ Context / Knowledge / Tools", text)
            self.assertIn("P ｜ 计划 / 下一轮目标", text)
            self.assertIn("loop-review.md", text)
            self.assertIn("Banchmark.md", text)
        self.assertIn("## 输出控制", skill)

    def test_serializer_emits_exact_dashboard_context_pdca_order(self) -> None:
        target = _target()
        rendered = target.serialize_dashboard(_view(), loop_decision="continue", repo_root=ROOT)
        ordered = [
            "◆ Goal-Teams 任务执行看板",
            "◆ Context / Knowledge / Tools",
            "◆ LOOP：第 2 轮 / 预计 4 轮",
            "P ｜ 计划 / 下一轮目标",
            "D ｜ 执行 / 本轮执行",
            "C ｜ 检查 / 执行结果",
            "A ｜ 改进 / 调整行动",
        ]
        positions = [rendered.index(label) for label in ordered]
        self.assertEqual(sorted(positions), positions)
        self.assertNotIn("◆ Banchmark", rendered)
        from scripts.v250.output_contract import validate_output

        outer = {
            "任务": "实施 V2.66 输出控制",
            "成员": "Goal Lead",
            "进度": "第 2 轮/共 4 轮",
            "结果": rendered,
            "Banchmark": "Development candidate",
            "下一轮 LOOP": "继续验证",
        }
        self.assertTrue(validate_output(outer, loop_decision="continue")["ok"])

    def test_dashboard_only_shows_active_parent_and_subtask_rows(self) -> None:
        target = _target()
        rendered = target.serialize_dashboard(_view(), loop_decision="continue", repo_root=ROOT)
        self.assertIn("| 优先级 | 任务 / 子任务 | Subagent 成员 | 进度 |", rendered)
        self.assertNotIn("执行层级", rendered)
        self.assertIn("↳ Token 刷新", rendered)
        self.assertIn("进行中 2｜剩余 3", rendered)
        self.assertNotIn("已完成 |", rendered)

        invalid = _view()
        invalid["dashboard"]["active_rows"].append(  # type: ignore[index]
            {
                "row_kind": "task",
                "task_id": "DONE",
                "parent_task_id": None,
                "priority": "P2",
                "name": "已结束任务",
                "members": ["goal_backend"],
                "parallel": False,
                "in_progress": 0,
                "remaining": 0,
            }
        )
        verdict = target.validate_dashboard(invalid, loop_decision="continue", repo_root=ROOT)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_ACTIVE_ROWS", verdict["errors"])

    def test_parallel_marker_is_fact_bound(self) -> None:
        target = _target()
        rendered = target.serialize_dashboard(_view(), loop_decision="continue", repo_root=ROOT)
        self.assertIn("`goal_backend`（并行）", rendered)
        self.assertIn("`goal_api_integration_test_runner` |", rendered)
        self.assertNotIn("`goal_api_integration_test_runner`（并行）", rendered)

    def test_context_entries_are_links_and_codebase_is_project_name_only(self) -> None:
        target = _target()
        rendered = target.serialize_dashboard(_view(), loop_decision="continue", repo_root=ROOT)
        self.assertIn("| 核心规则 | 项目知识 | 代码库 | MCP/CLI/API |", rendered)
        self.assertIn(f"[SKILL.md]({ROOT / 'SKILL.md'})", rendered)
        self.assertIn(f"[memory.md]({ROOT / _fixture('memory.md')})", rendered)
        self.assertIn("[goal-teams](https://github.com/vibe-coding-era/goal-teams)", rendered)
        self.assertNotIn("login_api.py", rendered)

        missing_memory = _view()
        missing_memory["context"]["project_knowledge"] = [  # type: ignore[index]
            item
            for item in missing_memory["context"]["project_knowledge"]  # type: ignore[index]
            if item["label"] != "memory.md"
        ]
        verdict = target.validate_dashboard(missing_memory, loop_decision="continue", repo_root=ROOT)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_PROJECT_MEMORY", verdict["errors"])

        invalid = _view()
        invalid["context"]["core_rules"][0]["href"] = "{Skill链接}"  # type: ignore[index]
        verdict = target.validate_dashboard(invalid, loop_decision="continue", repo_root=ROOT)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_LINK", verdict["errors"])

    def test_loop_heading_and_pdca_lines_are_exact(self) -> None:
        target = _target()
        rendered = target.serialize_dashboard(_view(), loop_decision="continue", repo_root=ROOT)
        self.assertIn("**◆ LOOP：第 2 轮 / 预计 4 轮**", rendered)
        labels = (
            "P ｜ 计划 / 下一轮目标",
            "D ｜ 执行 / 本轮执行",
            "C ｜ 检查 / 执行结果",
            "A ｜ 改进 / 调整行动",
        )
        for label in labels:
            self.assertIn(f"`{label}` ", rendered)
            self.assertNotIn(f"`{label}：`", rendered)
        self.assertIn("新增 Evidence 4｜缺口 3｜阻塞 1", rendered)
        self.assertIn(f"[Banchmark.md]({ROOT / _fixture('Banchmark.md')})", rendered)
        self.assertIn(f"[loop-review.md]({ROOT / _fixture('loop-review.md')})", rendered)
        self.assertIn("决策 `continue`｜改进反思：", rendered)
        self.assertNotIn("LOOP 改进建议", rendered)

        invalid = _view()
        invalid["loop"]["current_round"] = 5  # type: ignore[index]
        verdict = target.validate_dashboard(invalid, loop_decision="continue", repo_root=ROOT)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_LOOP_ROUND", verdict["errors"])

    def test_unbound_or_preview_success_fails_closed(self) -> None:
        target = _target()
        preview = _view()
        preview["mode"] = "preview"
        verdict = target.validate_dashboard(preview, loop_decision="continue", repo_root=ROOT)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_PREVIEW_STATE", verdict["errors"])

        stale = _view()
        stale["bindings"]["freshness"] = "stale"  # type: ignore[index]
        verdict = target.validate_dashboard(stale, loop_decision="continue", repo_root=ROOT)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_BINDING", verdict["errors"])

        fake_preview = _view()
        fake_preview["mode"] = "preview"
        fake_preview["dashboard"].update(  # type: ignore[union-attr]
            {
                "completed_tasks": 0,
                "total_tasks": 0,
                "completed_subtasks": 0,
                "total_subtasks": 0,
                "active_rows": [],
            }
        )
        fake_preview["loop"].update(  # type: ignore[union-attr]
            {
                "plan": "全部验收完成",
                "do": "全部测试通过",
                "new_evidence_count": 0,
                "gap_count": 0,
                "blocked_count": 0,
                "decision": "stop",
            }
        )
        verdict = target.validate_dashboard(fake_preview, loop_decision="stop", repo_root=ROOT)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_PREVIEW_STATE", verdict["errors"])

    def test_execution_facts_match_state_evidence_and_ready_layers(self) -> None:
        target = _target()

        completed_with_active = _view()
        completed_with_active["dashboard"]["completed_tasks"] = 4  # type: ignore[index]
        verdict = target.validate_dashboard(
            completed_with_active, loop_decision="continue", repo_root=ROOT
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_STATE_MISMATCH", verdict["errors"])

        invented_evidence = _view()
        invented_evidence["loop"]["new_evidence_count"] = 99  # type: ignore[index]
        verdict = target.validate_dashboard(
            invented_evidence, loop_decision="continue", repo_root=ROOT
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_EVIDENCE_MISMATCH", verdict["errors"])

        invented_parallelism = _view()
        invented_parallelism["dashboard"]["active_rows"][-1]["parallel"] = True  # type: ignore[index]
        verdict = target.validate_dashboard(
            invented_parallelism, loop_decision="continue", repo_root=ROOT
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_READY_LAYERS", verdict["errors"])

    def test_completed_stop_allows_empty_ready_layers(self) -> None:
        target = _target()
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            shutil.copytree(ROOT / FIXTURE, repo_root / FIXTURE)
            complete = _view()
            fixture_names = ("requirements.md", "architecture.md", "memory.md")
            complete["context"]["core_rules"] = [  # type: ignore[index]
                {"label": name, "href": _fixture(name)} for name in fixture_names
            ]
            complete["dashboard"].update(  # type: ignore[union-attr]
                {
                    "completed_tasks": 4,
                    "completed_subtasks": 14,
                    "active_rows": [],
                }
            )
            complete["loop"].update(  # type: ignore[union-attr]
                {
                    "current_round": 4,
                    "estimated_total_rounds": 4,
                    "plan": "not_required（本轮已停止）",
                    "do": "全部 Development 验证已完成",
                    "new_evidence_count": 0,
                    "gap_count": 0,
                    "blocked_count": 0,
                    "decision": "stop",
                }
            )
            state = {
                "schema_version": "goal-teams-dashboard-state-v1",
                "dashboard": {
                    "completed_tasks": 4,
                    "total_tasks": 4,
                    "completed_subtasks": 14,
                    "total_subtasks": 14,
                    "active_rows": [],
                    "ready_layers": [],
                },
                "loop": {
                    "current_round": 4,
                    "estimated_total_rounds": 4,
                    "plan": "not_required（本轮已停止）",
                    "do": "全部 Development 验证已完成",
                    "gap_count": 0,
                    "blocked_count": 0,
                    "decision": "stop",
                },
            }
            state_path = repo_root / _fixture("state-machine.json")
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            evidence_path = repo_root / _fixture("evidence.json")
            evidence_path.write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-dashboard-evidence-v1",
                        "new_evidence_count": 0,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            complete["bindings"]["state_machine_sha256"] = hashlib.sha256(  # type: ignore[index]
                state_path.read_bytes()
            ).hexdigest()
            complete["bindings"]["evidence_sha256"] = hashlib.sha256(  # type: ignore[index]
                evidence_path.read_bytes()
            ).hexdigest()
            verdict = target.validate_dashboard(
                complete, loop_decision="stop", repo_root=repo_root
            )
            self.assertTrue(verdict["ok"], verdict["errors"])
            rendered = target.serialize_dashboard(
                complete, loop_decision="stop", repo_root=repo_root
            )
            self.assertIn("决策 `stop`｜LOOP 改进建议：", rendered)
            self.assertNotIn("决策 `stop`｜改进反思：", rendered)
            self.assertIn("[loop-review.md]", rendered)

    def test_preview_never_enters_execution_renderer(self) -> None:
        target = _target()
        safe_preview = _view()
        safe_preview["mode"] = "preview"
        safe_preview["dashboard"].update(  # type: ignore[union-attr]
            {
                "completed_tasks": 0,
                "total_tasks": 0,
                "completed_subtasks": 0,
                "total_subtasks": 0,
                "active_rows": [],
            }
        )
        safe_preview["loop"].update(  # type: ignore[union-attr]
            {
                "plan": "not_created",
                "do": "not_run",
                "new_evidence_count": 0,
                "gap_count": 0,
                "blocked_count": 0,
                "decision": "continue",
            }
        )
        verdict = target.validate_dashboard(
            safe_preview, loop_decision="continue", repo_root=ROOT
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V266_OUTPUT_PREVIEW_STATE", verdict["errors"])

    def test_v266_schema_is_strict_and_matches_renderer(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:  # pragma: no cover - environment gate
            self.fail(f"E_TEST_V266_JSONSCHEMA_UNAVAILABLE:{exc}")
        schema = json.loads(
            (ROOT / "schemas/v2.66/output-dashboard.schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        self.assertEqual([], list(validator.iter_errors(_view())))
        extra = _view()
        extra["unexpected"] = True
        self.assertTrue(list(validator.iter_errors(extra)))
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
