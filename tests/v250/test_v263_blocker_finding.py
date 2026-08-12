from __future__ import annotations

import unittest

from scripts.v250.task_plan_compiler import (
    classify_audit_finding,
    compile_blocker_receipt,
    compile_task_plan,
)


def _task(task_id: str, depends_on: list[str], consumers: list[str]) -> dict[str, object]:
    return {
        "task_id": task_id,
        "requirement_refs": ["REQ-V263"],
        "consumer_refs": ["consumer:lead"],
        "owner": f"owner:{task_id}",
        "validator": f"validator:{task_id}",
        "scope_allowlist": [f"scope/{task_id}/**"],
        "forbidden_scope": ["README.md"],
        "depends_on": depends_on,
        "budget_wu": 1,
        "attempt_budget": 2,
        "revalidation_budget": 1,
        "inputs": [{"input_id": f"input:{task_id}"}],
        "outputs": [
            {
                "output_id": f"output:{task_id}",
                "consumer_refs": consumers,
                "required": True,
            }
        ],
        "verification": [f"verify:{task_id}"],
        "business_oracle": f"oracle:{task_id}",
        "exit_condition": f"exit:{task_id}",
        "failure_artifacts": [f"failure:{task_id}"],
    }


class BlockerAndFindingTests(unittest.TestCase):
    def test_blocker_propagates_only_to_descendants_and_side_branch_continues(self) -> None:
        tasks = [
            _task("A", [], ["task:B", "task:C"]),
            _task("B", ["A"], ["task:D"]),
            _task("C", ["A"], ["consumer:side-branch"]),
            _task("D", ["B"], ["consumer:final"]),
        ]
        plan = compile_task_plan(
            {
                "schema_version": "goal-teams-task-plan-v1",
                "plan_id": "GT-BLOCKER",
                "plan_revision": 1,
                "tasks": tasks,
                "phase_exact_sets": {
                    "development": ["A", "B", "C", "D"],
                    "runtime": [],
                    "release": [],
                },
            }
        )
        receipt = compile_blocker_receipt(
            plan,
            blocked_task_ids=["B"],
            task_states={"A": "accepted", "B": "pending", "C": "pending", "D": "pending"},
            blocker={
                "blocker_id": "BLOCK-1",
                "blocker_type": "external_service",
                "external_owner": "provider-team",
                "first_observed_at": "2026-08-12T00:00:00Z",
                "status": "open",
                "evidence": [{"receipt_id": "EV-1"}],
                "recovery_condition": "provider service is healthy",
                "revalidation_method": "rerun provider probe",
            },
        )

        self.assertEqual(["B", "D"], receipt["affected_task_ids"])
        self.assertEqual(["C"], receipt["continuable_task_ids"])
        self.assertEqual([], receipt["unrelated_blocked_task_ids"])
        self.assertRegex(receipt["receipt_digest"], r"^[0-9a-f]{64}$")

    def test_unverified_finding_remains_observed_only(self) -> None:
        result = classify_audit_finding(self._finding(evidence_verified=False))
        self.assertFalse(result["admitted"])
        self.assertEqual("observed_only", result["classification"])
        self.assertEqual("E_V263_FINDING_UNVERIFIED", result["reason_code"])

    def test_scope_authorization_and_budget_failures_are_classified(self) -> None:
        cases = [
            (
                self._finding(in_locked_scope=False),
                "new_revision_required",
                "E_V263_FINDING_SCOPE_CHANGE",
            ),
            (
                self._finding(authorization_boundary_unchanged=False),
                "blocked",
                "E_V263_FINDING_AUTHORIZATION_BOUNDARY",
            ),
            (
                self._finding(attempt_budget_remaining=0),
                "blocked",
                "E_V263_FINDING_BUDGET_EXHAUSTED",
            ),
        ]
        for finding, classification, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                result = classify_audit_finding(finding)
                self.assertFalse(result["admitted"])
                self.assertEqual(classification, result["classification"])
                self.assertEqual(reason_code, result["reason_code"])

    def test_consumer_gate_and_admitted_finding(self) -> None:
        backlog = classify_audit_finding(self._finding(consumer_confirmed=False))
        self.assertEqual("backlog_candidate", backlog["classification"])
        admitted = classify_audit_finding(self._finding())
        self.assertTrue(admitted["admitted"])
        self.assertEqual("admitted", admitted["classification"])
        self.assertEqual("current_exact_set", admitted["target"])

    @staticmethod
    def _finding(**overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "finding_id": "FINDING-1",
            "evidence_verified": True,
            "in_locked_scope": True,
            "consumer_confirmed": True,
            "estimated_attempts": 1,
            "attempt_budget_remaining": 1,
            "estimated_revalidations": 1,
            "revalidation_budget_remaining": 1,
            "authorization_boundary_unchanged": True,
        }
        value.update(overrides)
        return value


if __name__ == "__main__":
    unittest.main()
