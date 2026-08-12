"""Compile bounded V2.63 task plans, blocker receipts, and audit findings."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence


class TaskPlanError(RuntimeError):
    """A task plan cannot be compiled without weakening its contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


REQUIRED_TASK_FIELDS = {
    "task_id",
    "requirement_refs",
    "consumer_refs",
    "owner",
    "validator",
    "scope_allowlist",
    "forbidden_scope",
    "depends_on",
    "budget_wu",
    "attempt_budget",
    "revalidation_budget",
    "inputs",
    "outputs",
    "verification",
    "business_oracle",
    "exit_condition",
    "failure_artifacts",
}
PHASES = ("development", "runtime", "release")
ADMISSION_GATES = (
    "current_consumer_confirmed",
    "observable_acceptance_defined",
    "scope_locked",
    "budget_bound",
    "exit_condition_frozen",
)
ADMISSION_FIELDS = {*ADMISSION_GATES, "evidence_refs"}
VERIFICATION_FIELDS = {
    "verification_id",
    "verification_type",
    "method",
    "expected_result",
    "evidence_refs",
}
BUSINESS_ORACLE_FIELDS = {
    "oracle_id",
    "oracle_type",
    "acceptance_criteria",
    "evidence_refs",
}
EXIT_CONDITION_FIELDS = {
    "exit_id",
    "exit_type",
    "required_receipt_types",
    "on_budget_exhaustion",
}
PLACEHOLDER_RE = re.compile(r"(?:^|[^a-z0-9])(todo|tbd|maybe|none|n/a|unknown)(?:$|[^a-z0-9])", re.I)


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _meaningful_string(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    normalized = value.strip().lower()
    return normalized not in {"待定", "稍后", "无", "暂无"} and not PLACEHOLDER_RE.search(
        normalized
    )


def _string_list(value: Any, *, non_empty: bool) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not non_empty)
        and all(_non_empty_string(item) for item in value)
    )


def _meaningful_string_list(value: Any, *, non_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not non_empty)
        and all(_meaningful_string(item) for item in value)
        and len(value) == len(set(value))
    )


def _is_legacy_task_contract(task: Mapping[str, Any]) -> bool:
    return (
        "admission" not in task
        and _string_list(task.get("verification"), non_empty=True)
        and _non_empty_string(task.get("business_oracle"))
        and _non_empty_string(task.get("exit_condition"))
    )


def _validate_authoritative_task_contract(task: Mapping[str, Any], task_id: str) -> None:
    admission = task.get("admission")
    if not isinstance(admission, Mapping) or set(admission) != ADMISSION_FIELDS:
        raise TaskPlanError(
            "E_V263_TASK_ADMISSION",
            f"task {task_id} requires the exact consumer admission gate",
        )
    if any(type(admission.get(gate)) is not bool or not admission[gate] for gate in ADMISSION_GATES):
        raise TaskPlanError(
            "E_V263_TASK_ADMISSION",
            f"task {task_id} requires all five admission gates to be true",
        )
    if not _meaningful_string_list(admission.get("evidence_refs")):
        raise TaskPlanError(
            "E_V263_TASK_ADMISSION",
            f"task {task_id} requires admission evidence_refs",
        )

    verification = task.get("verification")
    if not isinstance(verification, list) or not verification:
        raise TaskPlanError(
            "E_V263_TASK_VERIFICATION", f"task {task_id} requires typed verification"
        )
    verification_ids: set[str] = set()
    for item in verification:
        if not isinstance(item, Mapping) or set(item) != VERIFICATION_FIELDS:
            raise TaskPlanError(
                "E_V263_TASK_VERIFICATION",
                f"task {task_id} has an invalid verification contract",
            )
        if any(
            not _meaningful_string(item.get(field))
            for field in (
                "verification_id",
                "verification_type",
                "method",
                "expected_result",
            )
        ) or not _meaningful_string_list(item.get("evidence_refs")):
            raise TaskPlanError(
                "E_V263_TASK_VERIFICATION",
                f"task {task_id} verification contains a placeholder",
            )
        verification_id = str(item["verification_id"])
        if verification_id in verification_ids:
            raise TaskPlanError(
                "E_V263_TASK_VERIFICATION",
                f"task {task_id} repeats verification_id {verification_id}",
            )
        verification_ids.add(verification_id)

    oracle = task.get("business_oracle")
    if not isinstance(oracle, Mapping) or set(oracle) != BUSINESS_ORACLE_FIELDS:
        raise TaskPlanError(
            "E_V263_TASK_BUSINESS_ORACLE",
            f"task {task_id} requires a typed business oracle",
        )
    if any(
        not _meaningful_string(oracle.get(field))
        for field in ("oracle_id", "oracle_type")
    ) or not _meaningful_string_list(
        oracle.get("acceptance_criteria")
    ) or not _meaningful_string_list(oracle.get("evidence_refs")):
        raise TaskPlanError(
            "E_V263_TASK_BUSINESS_ORACLE",
            f"task {task_id} business oracle contains a placeholder",
        )

    exit_condition = task.get("exit_condition")
    if not isinstance(exit_condition, Mapping) or set(exit_condition) != EXIT_CONDITION_FIELDS:
        raise TaskPlanError(
            "E_V263_TASK_EXIT_CONDITION",
            f"task {task_id} requires a typed exit condition",
        )
    if any(
        not _meaningful_string(exit_condition.get(field))
        for field in ("exit_id", "exit_type")
    ) or not _meaningful_string_list(exit_condition.get("required_receipt_types")):
        raise TaskPlanError(
            "E_V263_TASK_EXIT_CONDITION",
            f"task {task_id} exit condition contains a placeholder",
        )
    if exit_condition.get("on_budget_exhaustion") not in {"replan", "blocked"}:
        raise TaskPlanError(
            "E_V263_TASK_EXIT_CONDITION",
            f"task {task_id} must freeze replan or blocked on budget exhaustion",
        )


def _validate_task_shape(task: Any, index: int) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise TaskPlanError("E_V263_TASK_SHAPE", f"task at index {index} is not an object")
    missing = sorted(REQUIRED_TASK_FIELDS - set(task))
    if missing:
        raise TaskPlanError(
            "E_V263_TASK_REQUIRED",
            f"task at index {index} is missing: {', '.join(missing)}",
        )
    task_id = task.get("task_id")
    if not _non_empty_string(task_id):
        raise TaskPlanError("E_V263_TASK_ID", f"task at index {index} has no task_id")
    for field in ("requirement_refs", "consumer_refs", "scope_allowlist"):
        if not _string_list(task.get(field), non_empty=True):
            raise TaskPlanError(
                f"E_V263_TASK_{field.upper()}",
                f"task {task_id} requires a non-empty {field}",
            )
    for field in ("forbidden_scope", "depends_on", "failure_artifacts"):
        if not _string_list(task.get(field), non_empty=False):
            raise TaskPlanError(
                f"E_V263_TASK_{field.upper()}",
                f"task {task_id} has an invalid {field}",
            )
    for field in ("owner", "validator"):
        if not _non_empty_string(task.get(field)):
            raise TaskPlanError(
                f"E_V263_TASK_{field.upper()}",
                f"task {task_id} requires {field}",
            )
    for field in ("budget_wu", "attempt_budget"):
        value = task.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise TaskPlanError(
                f"E_V263_TASK_{field.upper()}",
                f"task {task_id} requires a positive {field}",
            )
    revalidation = task.get("revalidation_budget")
    if not isinstance(revalidation, int) or isinstance(revalidation, bool) or revalidation < 0:
        raise TaskPlanError(
            "E_V263_TASK_REVALIDATION_BUDGET",
            f"task {task_id} requires a non-negative revalidation_budget",
        )
    inputs = task.get("inputs")
    outputs = task.get("outputs")
    if not isinstance(inputs, list) or not inputs or not all(isinstance(item, dict) for item in inputs):
        raise TaskPlanError("E_V263_TASK_INPUTS", f"task {task_id} requires inputs")
    if not isinstance(outputs, list) or not outputs or not all(isinstance(item, dict) for item in outputs):
        raise TaskPlanError("E_V263_TASK_OUTPUTS", f"task {task_id} requires outputs")
    if _is_legacy_task_contract(task):
        pass
    else:
        _validate_authoritative_task_contract(task, task_id)
    output_ids: set[str] = set()
    for output in outputs:
        output_id = output.get("output_id")
        if not _non_empty_string(output_id) or output_id in output_ids:
            raise TaskPlanError(
                "E_V263_OUTPUT_ID",
                f"task {task_id} has an invalid or duplicate output_id",
            )
        output_ids.add(output_id)
        if output.get("required", True) and not _string_list(
            output.get("consumer_refs"), non_empty=True
        ):
            raise TaskPlanError(
                "E_V263_OUTPUT_WITHOUT_CONSUMER",
                f"required output {output_id} has no consumer",
            )
        if "consumer_refs" in output and not _string_list(
            output.get("consumer_refs"), non_empty=False
        ):
            raise TaskPlanError(
                "E_V263_OUTPUT_CONSUMERS",
                f"output {output_id} has invalid consumers",
            )
    return copy.deepcopy(task)


def _topological_layers(
    task_ids: Sequence[str], dependency_map: Mapping[str, Sequence[str]]
) -> tuple[list[str], list[list[str]]]:
    children: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    indegree = {task_id: len(dependency_map[task_id]) for task_id in task_ids}
    for task_id, dependencies in dependency_map.items():
        for dependency in dependencies:
            children[dependency].append(task_id)
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    layers: list[list[str]] = []
    while ready:
        layer = list(ready)
        layers.append(layer)
        order.extend(layer)
        next_ready: list[str] = []
        for task_id in layer:
            for child in sorted(children[task_id]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    next_ready.append(child)
        ready = sorted(next_ready)
    if len(order) != len(task_ids):
        cyclic = sorted(task_id for task_id, degree in indegree.items() if degree > 0)
        raise TaskPlanError(
            "E_V263_TASK_DAG_CYCLE", "task graph contains a cycle: " + ", ".join(cyclic)
        )
    return order, layers


def _critical_path(
    ordered_task_ids: Sequence[str],
    dependency_map: Mapping[str, Sequence[str]],
    budgets: Mapping[str, int],
    included: set[str] | None = None,
) -> int:
    selected = set(ordered_task_ids) if included is None else included
    longest: dict[str, int] = {}
    for task_id in ordered_task_ids:
        if task_id not in selected:
            continue
        predecessor_lengths = [
            longest[dependency]
            for dependency in dependency_map[task_id]
            if dependency in selected
        ]
        longest[task_id] = budgets[task_id] + max(predecessor_lengths, default=0)
    return max(longest.values(), default=0)


def _validate_phase_sets(
    value: Any, task_ids: Sequence[str]
) -> dict[str, list[str]]:
    if not isinstance(value, dict) or set(value) != set(PHASES):
        raise TaskPlanError(
            "E_V263_PHASE_EXACT_SET", "phase_exact_sets must contain development, runtime, and release"
        )
    known = set(task_ids)
    result: dict[str, list[str]] = {}
    combined: list[str] = []
    for phase in PHASES:
        members = value[phase]
        if not _string_list(members, non_empty=False) or len(set(members)) != len(members):
            raise TaskPlanError(
                "E_V263_PHASE_EXACT_SET", f"phase {phase} has invalid or duplicate members"
            )
        unknown = sorted(set(members) - known)
        if unknown:
            raise TaskPlanError(
                "E_V263_PHASE_UNKNOWN_TASK",
                f"phase {phase} contains unknown tasks: {', '.join(unknown)}",
            )
        result[phase] = list(members)
        combined.extend(members)
    duplicate_members = sorted(
        task_id for task_id in known if combined.count(task_id) > 1
    )
    missing_members = sorted(known - set(combined))
    if duplicate_members or missing_members:
        raise TaskPlanError(
            "E_V263_PHASE_PARTITION",
            "phase sets must partition the exact set; duplicates="
            + ",".join(duplicate_members)
            + "; missing="
            + ",".join(missing_members),
        )
    return result


def compile_task_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and compile a consumer-backed immutable TaskExactSet DAG."""

    if not isinstance(plan, Mapping):
        raise TaskPlanError("E_V263_PLAN_SHAPE", "task plan must be an object")
    if plan.get("schema_version") != "goal-teams-task-plan-v1":
        raise TaskPlanError("E_V263_PLAN_SCHEMA", "unsupported task plan schema_version")
    if not _non_empty_string(plan.get("plan_id")):
        raise TaskPlanError("E_V263_PLAN_ID", "plan_id is required")
    revision = plan.get("plan_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
        raise TaskPlanError("E_V263_PLAN_REVISION", "plan_revision must be positive")
    raw_tasks = plan.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise TaskPlanError("E_V263_PLAN_TASKS", "tasks must be a non-empty array")
    tasks = [_validate_task_shape(task, index) for index, task in enumerate(raw_tasks)]
    legacy_flags = [_is_legacy_task_contract(task) for task in tasks]
    if any(legacy_flags) and not all(legacy_flags):
        raise TaskPlanError(
            "E_V263_PLAN_MIXED_AUTHORITY",
            "authoritative and compatibility task contracts cannot share one exact set",
        )
    contract_authority = (
        "unverified_compatibility" if all(legacy_flags) else "authoritative"
    )
    task_ids = [task["task_id"] for task in tasks]
    duplicates = sorted(task_id for task_id in set(task_ids) if task_ids.count(task_id) > 1)
    if duplicates:
        raise TaskPlanError(
            "E_V263_TASK_ID_DUPLICATE", "duplicate task IDs: " + ", ".join(duplicates)
        )
    known = set(task_ids)
    for task in tasks:
        consumer_refs = list(task["consumer_refs"])
        for output in task["outputs"]:
            consumer_refs.extend(output.get("consumer_refs", []))
        for consumer_ref in consumer_refs:
            if consumer_ref.startswith("task:") and consumer_ref[5:] not in known:
                raise TaskPlanError(
                    "E_V263_TASK_CONSUMER_MISSING",
                    f"task {task['task_id']} references missing consumer {consumer_ref}",
                )
    dependency_map: dict[str, list[str]] = {}
    for task in tasks:
        task_id = task["task_id"]
        dependencies = list(task["depends_on"])
        if len(dependencies) != len(set(dependencies)):
            raise TaskPlanError(
                "E_V263_TASK_DEPENDENCY_DUPLICATE", f"task {task_id} repeats a dependency"
            )
        missing = sorted(set(dependencies) - known)
        if missing:
            raise TaskPlanError(
                "E_V263_TASK_DEPENDENCY_MISSING",
                f"task {task_id} has missing dependencies: {', '.join(missing)}",
            )
        dependency_map[task_id] = dependencies
    order, layers = _topological_layers(task_ids, dependency_map)
    phase_sets = _validate_phase_sets(plan.get("phase_exact_sets"), task_ids)
    phase_index = {phase: index for index, phase in enumerate(PHASES)}
    task_phase = {
        task_id: phase
        for phase, members in phase_sets.items()
        for task_id in members
    }
    for task_id, dependencies in dependency_map.items():
        for dependency in dependencies:
            if phase_index[task_phase[dependency]] > phase_index[task_phase[task_id]]:
                raise TaskPlanError(
                    "E_V263_PHASE_DEPENDENCY_ORDER",
                    f"task {task_id} in {task_phase[task_id]} depends on later-phase "
                    f"task {dependency} in {task_phase[dependency]}",
                )
    budgets = {task["task_id"]: task["budget_wu"] for task in tasks}
    phase_metrics = {
        phase: {
            "task_count": len(members),
            "budget_wu": sum(budgets[task_id] for task_id in members),
            "critical_path_wu": _critical_path(
                order, dependency_map, budgets, set(members)
            ),
        }
        for phase, members in phase_sets.items()
    }
    exact_set = {
        "schema_version": plan["schema_version"],
        "plan_id": plan["plan_id"],
        "plan_revision": revision,
        "tasks": tasks,
        "phase_exact_sets": phase_sets,
    }
    receipt: dict[str, Any] = {
        **exact_set,
        "contract_authority": contract_authority,
        "task_count": len(tasks),
        "task_ids": list(task_ids),
        "dependency_map": dependency_map,
        "topological_order": order,
        "ready_layers": layers,
        "total_budget_wu": sum(budgets.values()),
        "critical_path_wu": _critical_path(order, dependency_map, budgets),
        "maximum_parallel_width": max((len(layer) for layer in layers), default=0),
        "phase_metrics": phase_metrics,
        "task_exact_set_digest": _canonical_digest(exact_set),
    }
    receipt["receipt_digest"] = _canonical_digest(receipt)
    return receipt


def validate_compiled_task_plan(
    compiled_plan: Mapping[str, Any], *, require_authoritative: bool = True
) -> dict[str, Any]:
    """Rebuild a compiled plan and return a digest-bound typed validation receipt."""

    if not isinstance(compiled_plan, Mapping):
        raise TaskPlanError("E_V263_PLAN_RECEIPT_INVALID", "compiled plan is not an object")
    canonical_plan = {
        "schema_version": compiled_plan.get("schema_version"),
        "plan_id": compiled_plan.get("plan_id"),
        "plan_revision": compiled_plan.get("plan_revision"),
        "tasks": copy.deepcopy(compiled_plan.get("tasks")),
        "phase_exact_sets": copy.deepcopy(compiled_plan.get("phase_exact_sets")),
    }
    try:
        rebuilt = compile_task_plan(canonical_plan)
    except TaskPlanError as exc:
        raise TaskPlanError(
            "E_V263_PLAN_RECEIPT_INVALID", "compiled task plan cannot be rebuilt"
        ) from exc
    if dict(compiled_plan) != rebuilt:
        raise TaskPlanError(
            "E_V263_PLAN_RECEIPT_INVALID", "compiled task plan receipt differs"
        )
    if require_authoritative and rebuilt.get("contract_authority") != "authoritative":
        raise TaskPlanError(
            "E_V263_PLAN_UNVERIFIED",
            "compatibility task plans cannot authorize completion",
        )
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-task-plan-validation-receipt-v1",
        "plan_id": rebuilt["plan_id"],
        "plan_revision": rebuilt["plan_revision"],
        "task_exact_set_digest": rebuilt["task_exact_set_digest"],
        "compiled_receipt_digest": rebuilt["receipt_digest"],
        "phase_exact_task_ids": copy.deepcopy(rebuilt["phase_exact_sets"]),
        "contract_authority": rebuilt["contract_authority"],
        "validator": "scripts.v250.task_plan_compiler.validate_compiled_task_plan",
        "valid": True,
    }
    receipt["receipt_digest"] = _canonical_digest(receipt)
    return receipt


def compile_blocker_receipt(
    compiled_plan: Mapping[str, Any],
    *,
    blocked_task_ids: Sequence[str],
    task_states: Mapping[str, str],
    blocker: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind an external blocker to only its DAG descendant closure."""

    required = {
        "blocker_id",
        "blocker_type",
        "external_owner",
        "first_observed_at",
        "status",
        "evidence",
        "recovery_condition",
        "revalidation_method",
    }
    if not isinstance(blocker, Mapping) or required - set(blocker):
        raise TaskPlanError("E_V263_BLOCKER_SHAPE", "blocker fields are incomplete")
    if not blocked_task_ids or not all(_non_empty_string(item) for item in blocked_task_ids):
        raise TaskPlanError("E_V263_BLOCKER_TASKS", "blocked_task_ids are required")
    canonical_plan = {
        "schema_version": compiled_plan.get("schema_version"),
        "plan_id": compiled_plan.get("plan_id"),
        "plan_revision": compiled_plan.get("plan_revision"),
        "tasks": copy.deepcopy(compiled_plan.get("tasks")),
        "phase_exact_sets": copy.deepcopy(compiled_plan.get("phase_exact_sets")),
    }
    try:
        rebuilt_plan = compile_task_plan(canonical_plan)
    except TaskPlanError as exc:
        raise TaskPlanError(
            "E_V263_BLOCKER_PLAN", "compiled task plan cannot be rebuilt"
        ) from exc
    if dict(compiled_plan) != rebuilt_plan:
        raise TaskPlanError("E_V263_BLOCKER_PLAN", "compiled task plan is invalid")
    task_ids = list(rebuilt_plan["task_ids"])
    order = list(rebuilt_plan["topological_order"])
    dependency_map = rebuilt_plan["dependency_map"]
    unknown = sorted(set(blocked_task_ids) - set(task_ids))
    if unknown:
        raise TaskPlanError(
            "E_V263_BLOCKER_UNKNOWN_TASK", "unknown blocked tasks: " + ", ".join(unknown)
        )
    children: dict[str, list[str]] = defaultdict(list)
    for task_id, dependencies in dependency_map.items():
        for dependency in dependencies:
            children[dependency].append(task_id)
    affected = set(blocked_task_ids)
    pending = list(blocked_task_ids)
    while pending:
        current = pending.pop()
        for child in children[current]:
            if child not in affected:
                affected.add(child)
                pending.append(child)
    terminal_states = {"accepted", "completed", "cancelled", "blocked"}
    continuable: list[str] = []
    for task_id in order:
        if task_id in affected or task_states.get(task_id) in terminal_states:
            continue
        dependencies = dependency_map[task_id]
        if all(task_states.get(dependency) in {"accepted", "completed"} for dependency in dependencies):
            continuable.append(task_id)
    unrelated_blocked = [
        task_id
        for task_id in order
        if task_id not in affected and task_states.get(task_id) == "blocked"
    ]
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-blocker-receipt-v1",
        "task_exact_set_digest": compiled_plan.get("task_exact_set_digest"),
        "blocker": copy.deepcopy(dict(blocker)),
        "blocked_task_ids": sorted(set(blocked_task_ids)),
        "affected_task_ids": [task_id for task_id in order if task_id in affected],
        "continuable_task_ids": continuable,
        "unrelated_blocked_task_ids": unrelated_blocked,
    }
    receipt["receipt_digest"] = _canonical_digest(receipt)
    return receipt


def classify_audit_finding(
    finding: Mapping[str, Any],
    *,
    compiled_plan: Mapping[str, Any] | None = None,
    task_plan_validation_receipt: Mapping[str, Any] | None = None,
    budget_events: Sequence[Mapping[str, Any]] | None = None,
    budget_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a finding without silently expanding scope, authority, or budget."""

    if not isinstance(finding, Mapping) or not _non_empty_string(finding.get("finding_id")):
        raise TaskPlanError("E_V263_FINDING_SHAPE", "finding_id is required")
    boolean_fields = (
        "evidence_verified",
        "in_locked_scope",
        "consumer_confirmed",
        "authorization_boundary_unchanged",
    )
    if any(type(finding.get(field)) is not bool for field in boolean_fields):
        raise TaskPlanError(
            "E_V263_FINDING_BOOLEAN", "finding gate fields must be exact booleans"
        )
    strict_inputs = (
        compiled_plan,
        task_plan_validation_receipt,
        budget_events,
        budget_projection,
    )
    strict_requested = any(value is not None for value in strict_inputs)
    if strict_requested and any(value is None for value in strict_inputs):
        raise TaskPlanError(
            "E_V263_FINDING_BUDGET_BINDING",
            "authoritative finding admission requires plan and budget replay inputs",
        )
    forbidden_remaining = {
        "budget_wu_remaining",
        "work_unit_budget_remaining",
        "attempt_budget_remaining",
        "revalidation_budget_remaining",
    }
    if strict_requested and forbidden_remaining & set(finding):
        raise TaskPlanError(
            "E_V263_FINDING_CALLER_REMAINING",
            "caller-supplied remaining budget is forbidden",
        )
    checks = (
        (
            not finding.get("evidence_verified"),
            "observed_only",
            "E_V263_FINDING_UNVERIFIED",
        ),
        (
            not finding.get("in_locked_scope"),
            "new_revision_required",
            "E_V263_FINDING_SCOPE_CHANGE",
        ),
        (
            not finding.get("consumer_confirmed"),
            "backlog_candidate",
            "E_V263_FINDING_NO_CONSUMER",
        ),
    )
    for condition, classification, reason in checks:
        if condition:
            return _finding_result(
                finding,
                False,
                classification,
                reason,
                authoritative=compiled_plan is not None,
            )

    if strict_requested:
        validation = validate_compiled_task_plan(compiled_plan)
        if dict(task_plan_validation_receipt) != validation:
            raise TaskPlanError(
                "E_V263_FINDING_BUDGET_BINDING",
                "task plan validation receipt differs",
            )
        # Local import avoids making the plan compiler depend on reducer module load order.
        from scripts.v250.state_reducer import (  # pylint: disable=import-outside-toplevel
            StateReducerError,
            reduce_budget_events,
        )

        try:
            rebuilt_budget = reduce_budget_events(
                compiled_plan,
                task_plan_validation_receipt,
                budget_events,
            )
        except StateReducerError as exc:
            raise TaskPlanError(
                "E_V263_FINDING_BUDGET_BINDING", "budget replay failed"
            ) from exc
        if dict(budget_projection) != rebuilt_budget:
            raise TaskPlanError(
                "E_V263_FINDING_BUDGET_BINDING", "budget projection differs"
            )
        task_id = finding.get("task_id")
        if not _non_empty_string(task_id) or task_id not in rebuilt_budget["tasks"]:
            raise TaskPlanError(
                "E_V263_FINDING_TASK", "authoritative finding requires a current task_id"
            )
        estimate_fields = (
            "estimated_work_units",
            "estimated_attempts",
            "estimated_revalidations",
        )
        if any(
            not isinstance(finding.get(field), int)
            or isinstance(finding.get(field), bool)
            or finding[field] < 0
            for field in estimate_fields
        ):
            raise TaskPlanError(
                "E_V263_FINDING_BUDGET_SHAPE", "finding estimates are invalid"
            )
        remaining = rebuilt_budget["tasks"][task_id]["remaining"]
        estimates = {
            "work_unit": finding["estimated_work_units"],
            "attempt": finding["estimated_attempts"],
            "revalidation": finding["estimated_revalidations"],
        }
        if any(estimates[key] > remaining[key] for key in estimates):
            return _finding_result(
                finding,
                False,
                "blocked",
                "E_V263_FINDING_BUDGET_EXHAUSTED",
                authoritative=True,
                derived_budget_remaining=remaining,
            )
        if not finding.get("authorization_boundary_unchanged"):
            return _finding_result(
                finding,
                False,
                "blocked",
                "E_V263_FINDING_AUTHORIZATION_BOUNDARY",
                authoritative=True,
                derived_budget_remaining=remaining,
            )
        return _finding_result(
            finding,
            True,
            "admitted",
            "V263_FINDING_ADMITTED",
            authoritative=True,
            derived_budget_remaining=remaining,
        )

    budget_fields = (
        "estimated_attempts",
        "attempt_budget_remaining",
        "estimated_revalidations",
        "revalidation_budget_remaining",
    )
    if any(
        not isinstance(finding.get(field), int)
        or isinstance(finding.get(field), bool)
        or finding.get(field) < 0
        for field in budget_fields
    ):
        raise TaskPlanError("E_V263_FINDING_BUDGET_SHAPE", "finding budgets are invalid")
    if (
        finding["estimated_attempts"] > finding["attempt_budget_remaining"]
        or finding["estimated_revalidations"]
        > finding["revalidation_budget_remaining"]
    ):
        return _finding_result(
            finding,
            False,
            "blocked",
            "E_V263_FINDING_BUDGET_EXHAUSTED",
            authoritative=False,
        )
    if not finding.get("authorization_boundary_unchanged"):
        return _finding_result(
            finding,
            False,
            "blocked",
            "E_V263_FINDING_AUTHORIZATION_BOUNDARY",
            authoritative=False,
        )
    return _finding_result(
        finding,
        True,
        "admitted",
        "V263_FINDING_ADMITTED",
        authoritative=False,
    )


def _finding_result(
    finding: Mapping[str, Any],
    admitted: bool,
    classification: str,
    reason_code: str,
    *,
    authoritative: bool = False,
    derived_budget_remaining: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "goal-teams-finding-admission-v1",
        "finding_id": finding["finding_id"],
        "finding_digest": _canonical_digest(dict(finding)),
        "admitted": admitted,
        "classification": classification,
        "reason_code": reason_code,
        "target": "current_exact_set" if admitted else classification,
        "authoritative": authoritative,
        "decision_authority": (
            "authoritative_reducer" if authoritative else "unverified_compatibility"
        ),
    }
    if derived_budget_remaining is not None:
        result["derived_budget_remaining"] = copy.deepcopy(
            dict(derived_budget_remaining)
        )
    result["decision_digest"] = _canonical_digest(result)
    return result


__all__ = [
    "TaskPlanError",
    "classify_audit_finding",
    "compile_blocker_receipt",
    "compile_task_plan",
    "validate_compiled_task_plan",
]
