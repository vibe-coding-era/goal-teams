from __future__ import annotations

import unittest

from scripts.v250.loop_bootstrap import (
    LoopBootstrapError,
    plan_loop_round,
    validate_loop_bootstrap_receipt,
)
from scripts.v250.test_gate import derive_gate_plan


SHA = "a" * 64


def facts(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "loop_id": "LOOP-V263-1",
        "round": 1,
        "project_size": "medium",
        "product_version": "V2.63",
        "source_commit": "b" * 40,
        "toolchain_digest": "c" * 64,
        "dependency_digest": "d" * 64,
        "task_exact_set_digest": SHA,
    }
    value.update(overrides)
    return value


class TestV263LoopRegistryIntegration(unittest.TestCase):
    def test_v263_freezes_exact_set_before_assignment_and_preflight(self) -> None:
        with self.assertRaises(LoopBootstrapError) as missing:
            plan_loop_round(facts(task_exact_set_digest=None))
        self.assertEqual("E_V263_TASK_EXACT_SET_REQUIRED", missing.exception.code)

        plan = plan_loop_round(facts())
        self.assertEqual(
            [
                "tasklist",
                "task_exact_set_freeze",
                "task_assignment",
                "environment_preflight",
            ],
            plan["required_order"],
        )
        self.assertEqual(SHA, plan["task_exact_set_digest"])

    def test_v263_receipt_requires_exact_set_event_and_binding(self) -> None:
        receipt = {
            "bootstrap_events": [
                {"step": "tasklist", "revision": 1},
                {"step": "task_exact_set_freeze", "revision": 2},
                {"step": "task_assignment", "revision": 3},
                {"step": "environment_preflight", "revision": 4},
            ],
            "tasklist_created": True,
            "tasks_assigned": True,
            "environment_checked": True,
            "checker_agent_type": "goal_release_engineer",
            "checker_run_id": "checker-1",
            "lead_run_id": "lead-1",
            "implementation_owner_run_id": "impl-1",
            "project_size": "medium",
            "product_version": "V2.63",
            "branch_namespace": "codex",
            "development_branch": "codex/develop-v2.63",
            "compatible_existing_environment": False,
            "environment_action": "create",
            "task_exact_set_digest": SHA,
        }
        verdict = validate_loop_bootstrap_receipt(receipt)
        self.assertTrue(verdict["passed"])
        self.assertEqual(SHA, verdict["task_exact_set_digest"])

        receipt["bootstrap_events"] = [
            event
            for event in receipt["bootstrap_events"]
            if event["step"] != "task_exact_set_freeze"
        ]
        with self.assertRaises(LoopBootstrapError) as missing:
            validate_loop_bootstrap_receipt(receipt)
        self.assertEqual("E_V263_TASK_EXACT_SET_REQUIRED", missing.exception.code)

    def test_gate_plan_uses_canonical_registry_vocabulary(self) -> None:
        plan = derive_gate_plan(
            {
                "project_size": "medium",
                "workflow_phase": "development",
                "release_intent": True,
                "implementation_scope_complete": False,
            }
        )
        self.assertTrue(plan["ok"])
        self.assertEqual(["tdd", "incremental"], plan["blocking_gates"])
        self.assertNotIn("final_full_regression", plan["gates"])


if __name__ == "__main__":
    unittest.main()
