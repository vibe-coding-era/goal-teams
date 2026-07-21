"""V2.41 flow confirmation is a hard gate before Plan or member dispatch."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT, gt, parse_envelope, run_cli


class FlowClarificationPolicyTests(unittest.TestCase):
    def test_unconfirmed_proposal_cannot_open_plan_or_dispatch(self) -> None:
        policy = gt.flow_clarification_policy({"proposed_flow": "small"})
        self.assertEqual(policy["state"], "awaiting_confirmation")
        self.assertFalse(policy["plan_allowed"])
        self.assertFalse(policy["teams_allowed"])
        self.assertFalse(policy["subagent_dispatch_allowed"])

    def test_confirmed_selection_opens_only_the_selected_flow(self) -> None:
        policy = gt.flow_clarification_policy(
            {"proposed_flow": "small", "selected_flow": "medium", "confirmed": True}
        )
        self.assertEqual(policy["state"], "confirmed")
        self.assertEqual(policy["project_size"], "medium")
        self.assertTrue(policy["plan_allowed"])
        self.assertTrue(policy["subagent_dispatch_allowed"])

    def test_numbered_selection_maps_to_confirmed_flow_or_safe_minimal_path(self) -> None:
        for selected, expected in ((1, "small"), ("2", "medium"), ("3", "large")):
            with self.subTest(selected=selected):
                policy = gt.flow_clarification_policy(
                    {"proposed_flow": "small", "selected_flow": selected, "confirmed": True}
                )
                self.assertEqual(policy["state"], "confirmed")
                self.assertEqual(policy["selected_flow"], expected)
        direct = gt.flow_clarification_policy(
            {"proposed_flow": "small", "selected_flow": "5", "confirmed": True}
        )
        self.assertEqual(direct["state"], "skipped")
        custom = gt.flow_clarification_policy(
            {"proposed_flow": "small", "selected_flow": "4", "confirmed": True}
        )
        self.assertEqual(custom["state"], "awaiting_customization")
        self.assertFalse(custom["plan_allowed"])

    def test_skip_never_creates_goal_teams_plan_or_members(self) -> None:
        policy = gt.flow_clarification_policy(
            {"proposed_flow": "large", "selected_flow": "skipped", "confirmed": True}
        )
        self.assertEqual(policy["state"], "skipped")
        self.assertFalse(policy["plan_allowed"])
        self.assertFalse(policy["subagent_dispatch_allowed"])

    def test_invalid_selection_fails_closed_at_cli_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "invalid-flow.json"
            fixture.write_text(
                json.dumps({"proposed_flow": "small", "selected_flow": "xlarge", "confirmed": True}),
                encoding="utf-8",
            )
            proc = run_cli("flow-clarification-policy", str(fixture))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(parse_envelope(proc)["error_code"], "E_FLOW_CLARIFICATION_SELECTION")

    def test_protocol_keeps_all_three_user_paths_and_mermaid(self) -> None:
        text = (ROOT / "references" / "flow-clarification-protocol.md").read_text(encoding="utf-8")
        for marker in ("小迭代流程", "中迭代流程", "大迭代流程", "```mermaid"):
            self.assertIn(marker, text)

    def test_project_flow_reference_exposes_numbered_choices_and_staffing_ranges(self) -> None:
        text = (ROOT / "references" / "project-flow-selection.md").read_text(encoding="utf-8")
        for marker in (
            "小型需求/BugFix",
            "中型项目",
            "大型系统",
            "直接改",
            "可能的 Subagent：0–1 个。",
            "可能的 Subagent：2–4 个。",
            "可能的 Subagent：5–8 个。",
            "选项 `1`、`2`、`3` 分别规范化为 `small`、`medium`、`large`",
        ):
            self.assertIn(marker, text)

    def test_skill_turns_internal_rules_into_user_facing_intake_questions(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for marker in (
            "不得向用户粘贴、复述或逐条解释 `RULES.md`",
            "文件作用",
            "输入/输出格式",
            "规模与大小",
            "为避免误用流程，请确认：",
            "references/project-flow-selection.md",
            "1=小型需求/BugFix",
            "5=直接改",
        ):
            self.assertIn(marker, skill)
