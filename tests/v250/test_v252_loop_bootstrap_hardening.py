from __future__ import annotations

import unittest
from pathlib import Path

from scripts.v250.loop_bootstrap import (
    LoopBootstrapError,
    plan_loop_round,
    validate_loop_bootstrap_receipt,
)


ROOT = Path(__file__).resolve().parents[2]


class TestV252LoopBootstrapHardening(unittest.TestCase):
    def _facts(self, **overrides: object) -> dict[str, object]:
        facts: dict[str, object] = {
            "loop_id": "LOOP-V252-HARDEN",
            "round": 1,
            "product_version": "V2.62",
            "project_size": "medium",
            "plan_preview": False,
            "environment_check_requested": False,
            "lead_run_id": "RUN-LEAD",
            "implementation_owner_run_id": "RUN-IMPL",
            "source_commit": "1" * 40,
            "toolchain_digest": "2" * 64,
            "dependency_digest": "3" * 64,
            "branch_namespace": "codex",
            "existing_environment": None,
        }
        facts.update(overrides)
        return facts

    def _receipt(self) -> dict[str, object]:
        return {
            "bootstrap_events": [
                {"step": "tasklist", "revision": 1},
                {"step": "task_assignment", "revision": 2},
                {"step": "environment_preflight", "revision": 3},
            ],
            "tasklist_created": True,
            "tasks_assigned": True,
            "environment_checked": True,
            "checker_agent_type": "goal_release_engineer",
            "checker_run_id": "RUN-ENV",
            "lead_run_id": "RUN-LEAD",
            "implementation_owner_run_id": "RUN-IMPL",
            "project_size": "medium",
            "product_version": "V2.62",
            "branch_namespace": "codex",
            "development_branch": "codex/develop-v2.62",
            "environment_action": "create",
            "compatible_existing_environment": False,
        }

    def test_receipt_rejects_bootstrap_events_out_of_order(self) -> None:
        receipt = self._receipt()
        receipt["bootstrap_events"] = [
            {"step": "environment_preflight", "revision": 1},
            {"step": "tasklist", "revision": 2},
            {"step": "task_assignment", "revision": 3},
        ]

        with self.assertRaises(LoopBootstrapError) as caught:
            validate_loop_bootstrap_receipt(receipt)
        self.assertEqual("E_V26_LOOP_BOOTSTRAP_ORDER", caught.exception.code)

    def test_plan_preview_has_no_execution_bootstrap(self) -> None:
        plan = plan_loop_round(self._facts(plan_preview=True))

        self.assertEqual("not_applicable", plan["action"])
        self.assertEqual("plan_preview", plan["reason"])
        self.assertNotIn("development_branch", plan)

    def test_incompatible_existing_environment_falls_back_to_create(self) -> None:
        existing = {
            "path": "/repo/develops/v2.51",
            "identity": "ENV-251",
            "current": False,
            "compatible": False,
            "product_version": "V2.51",
            "source_commit": "0" * 40,
            "toolchain_digest": "0" * 64,
            "dependency_digest": "0" * 64,
        }

        plan = plan_loop_round(self._facts(existing_environment=existing))

        self.assertEqual("create", plan["environment_action"])
        self.assertTrue(plan["created_new_environment"])
        self.assertIn("identity_mismatch", plan["reuse_rejected_reasons"])

    def test_reuse_requires_exact_environment_identity(self) -> None:
        existing = {
            "path": "/repo/develops/v2.62",
            "identity": "ENV-252",
            "current": True,
            "compatible": True,
            "product_version": "V2.62",
            "source_commit": "1" * 40,
            "toolchain_digest": "2" * 64,
            "dependency_digest": "3" * 64,
        }
        self.assertEqual(
            "reuse",
            plan_loop_round(self._facts(existing_environment=existing))["environment_action"],
        )

        existing["dependency_digest"] = "4" * 64
        plan = plan_loop_round(self._facts(existing_environment=existing))
        self.assertEqual("create", plan["environment_action"])
        self.assertIn("dependency_digest", plan["reuse_rejected_reasons"])

    def test_branch_namespace_and_worktree_templates_are_separate(self) -> None:
        plan = plan_loop_round(self._facts())

        self.assertEqual("develop-v2.62", plan["logical_development_branch"])
        self.assertEqual("codex", plan["branch_namespace"])
        self.assertEqual("codex/develop-v2.62", plan["development_branch"])
        self.assertEqual("develops/v2.62", plan["development_worktree"])

    def test_environment_mode_stops_before_release_workflow(self) -> None:
        index = (ROOT / "prompts/members/release-engineer/INDEX.md").read_text(
            encoding="utf-8"
        )
        prompt = (ROOT / "prompts/members/release-engineer/prompt.md").read_text(
            encoding="utf-8"
        )
        workflow = (ROOT / "prompts/members/release-engineer/workflow.md").read_text(
            encoding="utf-8"
        )
        combined = index + prompt + workflow
        self.assertIn("environment_preflight 完成后立即停止", combined)
        self.assertIn("Release 模式唯一必读", combined)
        self.assertIn("不得进入 Mode B", combined)


if __name__ == "__main__":
    unittest.main()
