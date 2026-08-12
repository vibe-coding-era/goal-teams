from __future__ import annotations

import copy
import unittest

from scripts.v250.task_plan_compiler import TaskPlanError, compile_task_plan


def _task(
    task_id: str,
    *,
    depends_on: list[str] | None = None,
    budget_wu: int = 1,
    output_consumers: list[str] | None = None,
) -> dict[str, object]:
    consumers = output_consumers or ["consumer:goal-lead"]
    return {
        "task_id": task_id,
        "requirement_refs": ["REQ-V263"],
        "consumer_refs": ["consumer:goal-lead"],
        "owner": f"owner:{task_id}",
        "validator": f"validator:{task_id}",
        "scope_allowlist": [f"scope/{task_id}/**"],
        "forbidden_scope": ["README.md"],
        "depends_on": list(depends_on or []),
        "budget_wu": budget_wu,
        "attempt_budget": 2,
        "revalidation_budget": 1,
        "inputs": [{"input_id": f"input:{task_id}"}],
        "outputs": [
            {
                "output_id": f"output:{task_id}",
                "consumer_refs": list(consumers),
                "required": True,
            }
        ],
        "verification": [f"verify:{task_id}"],
        "business_oracle": f"oracle:{task_id}",
        "exit_condition": f"exit:{task_id}",
        "failure_artifacts": [f"failure:{task_id}"],
    }


def _plan(tasks: list[dict[str, object]], phases: dict[str, list[str]] | None = None) -> dict[str, object]:
    task_ids = [str(task["task_id"]) for task in tasks]
    return {
        "schema_version": "goal-teams-task-plan-v1",
        "plan_id": "GT-V263-PLAN",
        "plan_revision": 1,
        "tasks": tasks,
        "phase_exact_sets": phases
        or {"development": task_ids, "runtime": [], "release": []},
    }


class TaskPlanCompilerTests(unittest.TestCase):
    def test_consumer_scope_budget_verification_and_exit_are_fail_closed(self) -> None:
        mutations = {
            "consumer_refs": [],
            "scope_allowlist": [],
            "budget_wu": 0,
            "verification": [],
            "exit_condition": "",
        }
        for field, invalid in mutations.items():
            with self.subTest(field=field):
                task = _task("A")
                task[field] = invalid
                with self.assertRaises(TaskPlanError):
                    compile_task_plan(_plan([task]))

    def test_duplicate_id_missing_dependency_and_cycle_are_rejected(self) -> None:
        invalid_plans = [
            _plan([_task("A"), _task("A")]),
            _plan([_task("A", depends_on=["MISSING"])]),
            _plan(
                [
                    _task("A", depends_on=["B"], output_consumers=["task:B"]),
                    _task("B", depends_on=["A"], output_consumers=["task:A"]),
                ]
            ),
        ]
        for plan in invalid_plans:
            with self.subTest(plan=plan):
                with self.assertRaises(TaskPlanError):
                    compile_task_plan(plan)

    def test_required_output_without_a_consumer_is_rejected(self) -> None:
        task = _task("A")
        task["outputs"] = [
            {"output_id": "output:A", "consumer_refs": [], "required": True}
        ]
        with self.assertRaises(TaskPlanError) as raised:
            compile_task_plan(_plan([task]))
        self.assertEqual("E_V263_OUTPUT_WITHOUT_CONSUMER", raised.exception.code)

    def test_program_exact_set_has_frozen_metrics_and_phase_sets(self) -> None:
        definitions = {
            "P00": ([], 2),
            "P01": (["P00"], 5),
            "P02": (["P01"], 4),
            "P03": (["P00"], 5),
            "P04": (["P02", "P03"], 5),
            "P05": (["P04"], 6),
            "P06": (["P00"], 6),
            "P07": (["P06"], 4),
            "P08": (["P06"], 4),
            "P09": (["P05", "P07", "P08"], 5),
            "P10": (["P03", "P06"], 5),
            "P11": (["P05", "P09", "P10"], 7),
            "P12": (["P11"], 6),
        }
        children: dict[str, list[str]] = {task_id: [] for task_id in definitions}
        for task_id, (dependencies, _) in definitions.items():
            for dependency in dependencies:
                children[dependency].append(task_id)
        tasks = [
            _task(
                task_id,
                depends_on=dependencies,
                budget_wu=budget,
                output_consumers=[f"task:{child}" for child in children[task_id]]
                or ["consumer:release-readback"],
            )
            for task_id, (dependencies, budget) in definitions.items()
        ]
        phases = {
            "development": [f"P{value:02d}" for value in range(11)],
            "runtime": ["P11"],
            "release": ["P12"],
        }

        receipt = compile_task_plan(_plan(tasks, phases))

        self.assertEqual(13, receipt["task_count"])
        self.assertEqual(64, receipt["total_budget_wu"])
        self.assertEqual(40, receipt["critical_path_wu"])
        self.assertEqual(4, receipt["maximum_parallel_width"])
        self.assertEqual(phases, receipt["phase_exact_sets"])
        self.assertEqual(
            {"task_count": 11, "budget_wu": 51, "critical_path_wu": 27},
            receipt["phase_metrics"]["development"],
        )
        self.assertEqual(
            {"task_count": 1, "budget_wu": 7, "critical_path_wu": 7},
            receipt["phase_metrics"]["runtime"],
        )
        self.assertEqual(
            {"task_count": 1, "budget_wu": 6, "critical_path_wu": 6},
            receipt["phase_metrics"]["release"],
        )
        self.assertRegex(receipt["task_exact_set_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(receipt, compile_task_plan(copy.deepcopy(_plan(tasks, phases))))


if __name__ == "__main__":
    unittest.main()
