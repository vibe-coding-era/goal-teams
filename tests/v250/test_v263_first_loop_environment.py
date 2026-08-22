from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV263FirstLoopEnvironment(unittest.TestCase):
    def test_product_identity_and_active_generation_are_v263(self) -> None:
        self.assertEqual("V2.65", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        active = json.loads(
            (ROOT / "references/current/ACTIVE.json").read_text(encoding="utf-8")
        )
        self.assertEqual("V2.65", active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.65/activation-manifest.json",
            active["activation_manifest"],
        )

    def test_bilingual_readmes_introduce_all_previously_omitted_members(self) -> None:
        readmes = {
            "zh": (ROOT / "README.md").read_text(encoding="utf-8"),
            "en": (ROOT / "README.en.md").read_text(encoding="utf-8"),
        }
        expected = {
            "goal_performance",
            "goal_security",
            "goal_sqa",
            "goal_refactor",
            "goal_release_engineer",
        }
        for language, text in readmes.items():
            with self.subTest(language=language):
                for member_id in expected:
                    self.assertIn(f"`{member_id}`", text)

    def test_first_loop_contract_creates_tasklist_assigns_and_checks_environment(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        core = (
            ROOT / "references/current/generations/V2.65/core.md"
        ).read_text(encoding="utf-8")
        for text in (skill, core):
            self.assertIn("第一轮", text)
            self.assertIn("TaskList", text)
            self.assertIn("分配任务", text)
            self.assertIn("环境", text)

    def test_environment_check_is_independent_reusable_and_version_branched(self) -> None:
        architecture = (
            ROOT
            / "references/current/generations/V2.65/functions/architecture-implementation.md"
        ).read_text(encoding="utf-8")
        common = (ROOT / "subagents/common-developer-instructions.txt").read_text(
            encoding="utf-8"
        )
        combined = architecture + "\n" + common
        self.assertIn("goal_release_engineer", combined)
        self.assertIn("environment_preflight", combined)
        self.assertIn("复用", architecture)
        self.assertIn("codex/develop-v<major.minor>", architecture)
        self.assertIn("Small", architecture)
        self.assertIn("用户指定", architecture)

        for relative in (
            "prompts/members/release-engineer/INDEX.md",
            "prompts/members/release-engineer/prompt.md",
            "prompts/members/release-engineer/workflow.md",
            "prompts/members/release-engineer/template.md",
            "subagents/goal-release-engineer.toml",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
