"""Regression checks for V2.41 environment planning and portable-core boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class V241EnvironmentAndRuntimeContractTests(unittest.TestCase):
    def test_environment_plan_covers_both_environments_without_deployment_authority(self) -> None:
        text = read("prompts/packets/environment-configuration-plan.md")
        for marker in (
            "Development Configuration Plan",
            "Production Configuration Plan",
            "禁止记录值",
            "不等于部署授权",
        ):
            self.assertIn(marker, text)

    def test_architecture_handoff_requires_environment_plan(self) -> None:
        handoff = read("prompts/packets/handoff-artifacts.md")
        self.assertIn("environment_configuration_plan", handoff)
        self.assertIn("每份适用 Architecture Design 必须写入", handoff)
        for role in ("backend", "frontend"):
            self.assertIn(
                "Development Configuration Plan",
                read(f"prompts/members/{role}/workflow.md"),
            )

    def test_formal_planning_requires_confirmed_flow_selection(self) -> None:
        requirement_card = read("prompts/packets/requirement-card.md")
        team_plan = read("prompts/packets/team-plan-table.md")
        self.assertIn("确认状态", requirement_card)
        self.assertIn("不得生成正式 Plan、Teams 规划表或派发成员", requirement_card)
        self.assertIn("flow_confirmation=confirmed", team_plan)

    def test_portable_core_does_not_overclaim_adapter_compatibility(self) -> None:
        contract = read("references/agent-runtime-capability-contract.md")
        core = read("prompts/lead/core.md")
        self.assertIn("Runtime Adapter", contract)
        self.assertIn("不能声称全功能兼容", contract)
        self.assertIn("Codex 的 `$goal-teams`", core)
        self.assertIn("不能宣称所有 Agent 已完整兼容", core)


if __name__ == "__main__":
    unittest.main()
