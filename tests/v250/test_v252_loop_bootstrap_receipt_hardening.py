from __future__ import annotations

import unittest

from scripts.v250.loop_bootstrap import (
    LoopBootstrapError,
    plan_loop_round,
    validate_loop_bootstrap_receipt,
)


class TestV252LoopBootstrapReceiptHardening(unittest.TestCase):
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
            "source_commit": "1" * 40,
            "toolchain_digest": "2" * 64,
            "dependency_digest": "3" * 64,
            "development_branch": "codex/develop-v2.62",
            "environment_action": "reuse",
            "compatible_existing_environment": True,
        }

    def test_reuse_receipt_requires_matching_exact_identity(self) -> None:
        receipt = self._receipt()

        with self.assertRaises(LoopBootstrapError) as caught:
            validate_loop_bootstrap_receipt(receipt)
        self.assertEqual("E_V26_EXISTING_ENV_IDENTITY", caught.exception.code)

        receipt["reused_environment"] = {
            "product_version": "V2.62",
            "source_commit": "1" * 40,
            "toolchain_digest": "2" * 64,
            "dependency_digest": "4" * 64,
        }
        with self.assertRaises(LoopBootstrapError) as caught:
            validate_loop_bootstrap_receipt(receipt)
        self.assertEqual("E_V26_EXISTING_ENV_IDENTITY", caught.exception.code)

        receipt["reused_environment"]["dependency_digest"] = "3" * 64
        self.assertTrue(validate_loop_bootstrap_receipt(receipt)["ok"])

    def test_default_namespace_round_trips_between_plan_and_receipt(self) -> None:
        plan = plan_loop_round(
            {
                "loop_id": "LOOP-V252-NAMESPACE",
                "round": 1,
                "product_version": "V2.62",
                "project_size": "medium",
                "source_commit": "1" * 40,
                "toolchain_digest": "2" * 64,
                "dependency_digest": "3" * 64,
            }
        )
        self.assertEqual("codex", plan["branch_namespace"])
        self.assertEqual("codex/develop-v2.62", plan["development_branch"])

        receipt = self._receipt()
        receipt["environment_action"] = "create"
        receipt["compatible_existing_environment"] = False
        self.assertTrue(validate_loop_bootstrap_receipt(receipt)["ok"])


if __name__ == "__main__":
    unittest.main()
