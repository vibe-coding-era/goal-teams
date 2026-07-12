#!/usr/bin/env python3
"""Check Goal Teams subagent naming rules."""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    print("Python 3.11+ is required for tomllib", file=sys.stderr)
    sys.exit(2)


ROOT = Path(__file__).resolve().parents[2]
ROLE_PREFIXES = {
    "goal_backend": "后端",
    "goal_completion_auditor": "收尾",
    "goal_docs": "文档",
    "goal_frontend": "前端",
    "goal_unit_test_designer": "单测设计",
    "goal_unit_test_runner": "单测执行",
    "goal_api_integration_test_designer": "API集成测试",
    "goal_api_integration_test_runner": "API集成测试",
    "goal_e2e_test_designer": "E2E用例",
    "goal_e2e_test_runner": "E2E执行",
    "goal_product": "产品",
    "goal_qa": "测试",
    "goal_requirements_analyst": "需求分析",
    "goal_reviewer": "评审",
    "goal_security": "安全",
    "goal_performance": "性能",
    "goal_refactor": "重构",
    "goal_sqa": "质量保证",
}
SPECIALIST_NAMES = {"goal_security", "goal_performance", "goal_refactor", "goal_sqa"}
ENGLISH_NICKNAME_RE = re.compile(r"\b(?:Reviewer|QA|Implementer|Researcher)\s+[A-Z]\b")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def check_file(path: Path) -> None:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    name = data.get("name")
    if name not in ROLE_PREFIXES:
        fail(f"{path} has unexpected name {name!r}")
    instructions = data.get("developer_instructions", "")
    for required in ("transport handle", "成员：<中文展示名>", "member_id", "display_name"):
        if required not in instructions:
            fail(f"{path} missing naming rule: {required}")
    if name in SPECIALIST_NAMES:
        if data.get("sandbox_mode") != "read-only":
            fail(f"{path} specialist must use sandbox_mode=read-only")
        for required in (
            "coordination_depth: 1",
            "can_spawn_subagents: false",
            "can_dispatch: false",
            "dispatch_owner_agent_type: goal_lead",
            "handoff_mode: proposal_only",
            "不要创建嵌套团队",
            "独立校验",
        ):
            if required not in instructions:
                fail(f"{path} missing specialist capability rule: {required}")
    for candidate in data.get("nickname_candidates", []):
        if ENGLISH_NICKNAME_RE.search(candidate):
            fail(f"{path} contains English runtime nickname candidate: {candidate}")
        if not candidate.startswith(ROLE_PREFIXES[name] + "-"):
            fail(f"{path} nickname should start with {ROLE_PREFIXES[name]}-: {candidate}")
        if not re.search(r"[\u4e00-\u9fff]", candidate):
            fail(f"{path} nickname should be Chinese-visible: {candidate}")


def main() -> None:
    files = sorted((ROOT / "subagents").glob("goal-*.toml"))
    if len(files) != len(ROLE_PREFIXES):
        fail(f"Expected {len(ROLE_PREFIXES)} goal subagents, found {len(files)}")
    for path in files:
        check_file(path)
    print("Agent naming validation passed.")


if __name__ == "__main__":
    main()
