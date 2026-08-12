from __future__ import annotations

import copy
import hashlib
import json
import unittest

from scripts.v250.state_reducer import (
    StateReducerError,
    make_budget_event,
    reduce_budget_events,
)
from scripts.v250.task_plan_compiler import (
    TaskPlanError,
    classify_audit_finding,
    compile_task_plan,
    validate_compiled_task_plan,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _task(task_id: str = "P01") -> dict[str, object]:
    return {
        "task_id": task_id,
        "requirement_refs": ["REQ-V263-PREDICTABLE"],
        "consumer_refs": ["consumer:goal-lead"],
        "admission": {
            "current_consumer_confirmed": True,
            "observable_acceptance_defined": True,
            "scope_locked": True,
            "budget_bound": True,
            "exit_condition_frozen": True,
            "evidence_refs": ["receipt:consumer-demand-1"],
        },
        "owner": f"owner:{task_id}",
        "validator": f"validator:{task_id}",
        "scope_allowlist": [f"scope/{task_id}/**"],
        "forbidden_scope": ["README.md"],
        "depends_on": [],
        "budget_wu": 2,
        "attempt_budget": 2,
        "revalidation_budget": 1,
        "inputs": [{"input_id": f"input:{task_id}"}],
        "outputs": [
            {
                "output_id": f"output:{task_id}",
                "consumer_refs": ["consumer:goal-lead"],
                "required": True,
            }
        ],
        "verification": [
            {
                "verification_id": f"verification:{task_id}",
                "verification_type": "test",
                "method": f"python3 -m unittest {task_id}",
                "expected_result": "all assertions pass",
                "evidence_refs": ["receipt:frozen-test-digest"],
            }
        ],
        "business_oracle": {
            "oracle_id": f"oracle:{task_id}",
            "oracle_type": "consumer_acceptance",
            "acceptance_criteria": ["consumer-observable result is present"],
            "evidence_refs": ["receipt:oracle-contract"],
        },
        "exit_condition": {
            "exit_id": f"exit:{task_id}",
            "exit_type": "receipts_closed",
            "required_receipt_types": ["task_verification", "task_exit"],
            "on_budget_exhaustion": "replan",
        },
        "failure_artifacts": [f"failure:{task_id}"],
    }


def _plan(task: dict[str, object] | None = None) -> dict[str, object]:
    selected = task or _task()
    return {
        "schema_version": "goal-teams-task-plan-v1",
        "plan_id": "GT-V263-AUTHORITY",
        "plan_revision": 1,
        "tasks": [selected],
        "phase_exact_sets": {
            "development": [str(selected["task_id"])],
            "runtime": [],
            "release": [],
        },
    }


class V263TaskPlanAuthorityTests(unittest.TestCase):
    def test_consumer_admission_requires_five_exact_true_gates_and_evidence(self) -> None:
        gate_names = (
            "current_consumer_confirmed",
            "observable_acceptance_defined",
            "scope_locked",
            "budget_bound",
            "exit_condition_frozen",
        )
        for gate in gate_names:
            with self.subTest(gate=gate):
                task = _task()
                task["admission"][gate] = "true"
                with self.assertRaises(TaskPlanError) as raised:
                    compile_task_plan(_plan(task))
                self.assertEqual("E_V263_TASK_ADMISSION", raised.exception.code)

        no_evidence = _task()
        no_evidence["admission"]["evidence_refs"] = []
        with self.assertRaises(TaskPlanError) as raised:
            compile_task_plan(_plan(no_evidence))
        self.assertEqual("E_V263_TASK_ADMISSION", raised.exception.code)

    def test_typed_contracts_reject_placeholder_todo_maybe_and_none(self) -> None:
        mutations = []
        verification = _task()
        verification["verification"][0]["expected_result"] = "TODO"
        mutations.append(verification)
        oracle = _task()
        oracle["business_oracle"]["acceptance_criteria"] = ["maybe"]
        mutations.append(oracle)
        exit_condition = _task()
        exit_condition["exit_condition"]["exit_id"] = "none"
        mutations.append(exit_condition)
        for task in mutations:
            with self.subTest(task=task):
                with self.assertRaises(TaskPlanError):
                    compile_task_plan(_plan(task))

    def test_compiled_plan_is_rebuilt_and_has_a_typed_validation_receipt(self) -> None:
        compiled = compile_task_plan(_plan())
        self.assertEqual("authoritative", compiled["contract_authority"])
        validation = validate_compiled_task_plan(compiled)
        self.assertEqual("goal-teams-task-plan-validation-receipt-v1", validation["schema_version"])
        self.assertTrue(validation["valid"])
        self.assertEqual(compiled["receipt_digest"], validation["compiled_receipt_digest"])
        self.assertEqual(compiled["phase_exact_sets"], validation["phase_exact_task_ids"])
        self.assertRegex(validation["receipt_digest"], r"^[0-9a-f]{64}$")

        tampered = copy.deepcopy(compiled)
        tampered["phase_exact_sets"]["development"] = ["FAKE"]
        tampered["receipt_digest"] = _digest(
            {key: value for key, value in tampered.items() if key != "receipt_digest"}
        )
        with self.assertRaises(TaskPlanError) as raised:
            validate_compiled_task_plan(tampered)
        self.assertEqual("E_V263_PLAN_RECEIPT_INVALID", raised.exception.code)

    def test_legacy_plan_is_explicitly_unverified_and_cannot_validate_authoritatively(self) -> None:
        legacy = _task()
        legacy.pop("admission")
        legacy["verification"] = ["verify:P01"]
        legacy["business_oracle"] = "oracle:P01"
        legacy["exit_condition"] = "exit:P01"
        compiled = compile_task_plan(_plan(legacy))
        self.assertEqual("unverified_compatibility", compiled["contract_authority"])
        with self.assertRaises(TaskPlanError) as raised:
            validate_compiled_task_plan(compiled)
        self.assertEqual("E_V263_PLAN_UNVERIFIED", raised.exception.code)

    def test_budget_reducer_is_the_only_writer_and_derives_remaining_values(self) -> None:
        compiled = compile_task_plan(_plan())
        validation = validate_compiled_task_plan(compiled)
        first = make_budget_event(
            event_id="budget-1",
            event_seq=1,
            previous_event_sha256="0" * 64,
            cas_base_revision=0,
            task_id="P01",
            consumption_type="work_unit",
            amount=2,
            task_exact_set_digest=compiled["task_exact_set_digest"],
            compiled_plan_receipt_digest=compiled["receipt_digest"],
            evidence_refs=["receipt:work-1"],
            occurred_at="2026-08-12T16:00:00Z",
        )
        projection = reduce_budget_events(compiled, validation, [first])
        self.assertEqual(0, projection["tasks"]["P01"]["remaining"]["work_unit"])
        self.assertEqual("replan", projection["tasks"]["P01"]["exhaustion_projection"])
        self.assertEqual("state_reducer", projection["projection_writer"])

        spoofed = dict(first)
        spoofed["remaining_work_unit"] = 999
        spoofed["event_sha256"] = _digest(
            {key: value for key, value in spoofed.items() if key != "event_sha256"}
        )
        with self.assertRaises(StateReducerError) as raised:
            reduce_budget_events(compiled, validation, [spoofed])
        self.assertEqual("E_V263_BUDGET_EVENT", raised.exception.code)

    def test_finding_budget_remaining_is_reduced_not_caller_supplied(self) -> None:
        compiled = compile_task_plan(_plan())
        validation = validate_compiled_task_plan(compiled)
        budget_event = make_budget_event(
            event_id="budget-1",
            event_seq=1,
            previous_event_sha256="0" * 64,
            cas_base_revision=0,
            task_id="P01",
            consumption_type="attempt",
            amount=2,
            task_exact_set_digest=compiled["task_exact_set_digest"],
            compiled_plan_receipt_digest=compiled["receipt_digest"],
            evidence_refs=["receipt:attempt-1"],
            occurred_at="2026-08-12T16:00:00Z",
        )
        projection = reduce_budget_events(compiled, validation, [budget_event])
        finding = {
            "finding_id": "FINDING-STRICT",
            "task_id": "P01",
            "evidence_verified": True,
            "in_locked_scope": True,
            "consumer_confirmed": True,
            "authorization_boundary_unchanged": True,
            "estimated_work_units": 0,
            "estimated_attempts": 1,
            "estimated_revalidations": 0,
        }
        result = classify_audit_finding(
            finding,
            compiled_plan=compiled,
            task_plan_validation_receipt=validation,
            budget_events=[budget_event],
            budget_projection=projection,
        )
        self.assertFalse(result["admitted"])
        self.assertTrue(result["authoritative"])
        self.assertEqual("E_V263_FINDING_BUDGET_EXHAUSTED", result["reason_code"])
        self.assertEqual(0, result["derived_budget_remaining"]["attempt"])

        caller_spoof = {**finding, "attempt_budget_remaining": 999}
        with self.assertRaises(TaskPlanError) as raised:
            classify_audit_finding(
                caller_spoof,
                compiled_plan=compiled,
                task_plan_validation_receipt=validation,
                budget_events=[budget_event],
                budget_projection=projection,
            )
        self.assertEqual("E_V263_FINDING_CALLER_REMAINING", raised.exception.code)

    def test_legacy_finding_decision_is_never_authoritative(self) -> None:
        result = classify_audit_finding(
            {
                "finding_id": "FINDING-LEGACY",
                "evidence_verified": True,
                "in_locked_scope": True,
                "consumer_confirmed": True,
                "estimated_attempts": 1,
                "attempt_budget_remaining": 1,
                "estimated_revalidations": 0,
                "revalidation_budget_remaining": 0,
                "authorization_boundary_unchanged": True,
            }
        )
        self.assertFalse(result["authoritative"])
        self.assertEqual("unverified_compatibility", result["decision_authority"])


if __name__ == "__main__":
    unittest.main()
