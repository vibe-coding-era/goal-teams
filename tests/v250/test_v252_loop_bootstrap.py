from __future__ import annotations

import unittest

from scripts.v250.loop_bootstrap import (
    LoopBootstrapError,
    plan_loop_round,
    validate_loop_bootstrap_receipt,
)


class TestV252LoopBootstrap(unittest.TestCase):
    def _facts(self, **overrides: object) -> dict[str, object]:
        facts: dict[str, object] = {
            "loop_id": "LOOP-V252-001",
            "round": 1,
            "product_version": "V2.6",
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

    def test_round_one_orders_tasklist_assignment_and_environment_preflight(self) -> None:
        plan = plan_loop_round(self._facts())

        self.assertEqual(
            ["tasklist", "task_assignment", "environment_preflight"],
            plan["required_order"],
        )
        self.assertEqual("goal_release_engineer", plan["environment_checker"])
        self.assertEqual("environment_preflight", plan["environment_mode"])
        self.assertEqual("required", plan["development_environment_check"])
        self.assertEqual("create", plan["environment_action"])
        self.assertEqual("codex/develop-v2.6", plan["development_branch"])

    def test_small_keeps_preflight_but_does_not_require_version_branch(self) -> None:
        plan = plan_loop_round(self._facts(project_size="small"))

        self.assertEqual("required", plan["environment_preflight"])
        self.assertEqual("not_required", plan["development_environment_check"])
        self.assertEqual("not_required", plan["development_branch"])

    def test_user_can_require_full_environment_check_for_small(self) -> None:
        plan = plan_loop_round(
            self._facts(project_size="small", environment_check_requested=True)
        )

        self.assertEqual("required", plan["development_environment_check"])
        self.assertEqual("not_required", plan["development_branch"])

    def test_current_compatible_environment_is_reused(self) -> None:
        existing = {
            "path": "/repo/develops/v2.6",
            "identity": "ENV-252-A",
            "current": True,
            "compatible": True,
            "product_version": "V2.6",
            "source_commit": "1" * 40,
            "toolchain_digest": "2" * 64,
            "dependency_digest": "3" * 64,
        }
        plan = plan_loop_round(self._facts(existing_environment=existing))

        self.assertEqual("reuse", plan["environment_action"])
        self.assertEqual(existing, plan["reused_environment"])
        self.assertFalse(plan["created_new_environment"])

    def test_later_round_requires_bootstrap_receipt_reference(self) -> None:
        with self.assertRaises(LoopBootstrapError) as caught:
            plan_loop_round(self._facts(round=2))
        self.assertEqual("E_V26_LOOP_BOOTSTRAP_RECEIPT_REQUIRED", caught.exception.code)

        plan = plan_loop_round(self._facts(round=2, bootstrap_receipt_ref="sha256:abc"))
        self.assertEqual("reuse_bootstrap", plan["action"])

    def test_receipt_rejects_missing_first_round_fact_and_non_independent_checker(self) -> None:
        base = {
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
            "product_version": "V2.6",
            "development_branch": "codex/develop-v2.6",
            "environment_action": "create",
            "compatible_existing_environment": False,
        }
        for field, code in (
            ("tasklist_created", "E_V26_LOOP_ROUND_ONE_TASKLIST"),
            ("tasks_assigned", "E_V26_LOOP_ROUND_ONE_ASSIGNMENT"),
            ("environment_checked", "E_V26_LOOP_ROUND_ONE_ENVIRONMENT_CHECK"),
        ):
            receipt = dict(base)
            receipt[field] = False
            with self.subTest(field=field), self.assertRaises(LoopBootstrapError) as caught:
                validate_loop_bootstrap_receipt(receipt)
            self.assertEqual(code, caught.exception.code)

        receipt = dict(base)
        receipt["checker_run_id"] = receipt["implementation_owner_run_id"]
        with self.assertRaises(LoopBootstrapError) as caught:
            validate_loop_bootstrap_receipt(receipt)
        self.assertEqual("E_V26_ENV_CHECKER_INDEPENDENT", caught.exception.code)

    def test_receipt_requires_reuse_and_exact_version_branch(self) -> None:
        receipt = {
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
            "product_version": "V2.6",
            "development_branch": "main",
            "environment_action": "create",
            "compatible_existing_environment": False,
        }
        with self.assertRaises(LoopBootstrapError) as caught:
            validate_loop_bootstrap_receipt(receipt)
        self.assertEqual("E_V26_DEVELOPMENT_BRANCH", caught.exception.code)

        receipt["development_branch"] = "codex/develop-v2.6"
        receipt["compatible_existing_environment"] = True
        with self.assertRaises(LoopBootstrapError) as caught:
            validate_loop_bootstrap_receipt(receipt)
        self.assertEqual("E_V26_EXISTING_ENV_REUSE_REQUIRED", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
