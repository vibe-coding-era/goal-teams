"""Consumer-backed exact task sets and bounded DAG admission for the project ledger.

Retains predecessor task-plan invariants, not its generation or host runtime. Hashes
bind local facts; they do not authenticate reviewers or external acceptance.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from . import graph_budget
from .util import GTError, EXIT, normalize_scope, matches_any


def _refs(value: Any, default: List[str], label: str) -> List[str]:
    values = default if value is None else value
    if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
        raise GTError("%s 必须包含当前引用，不能留空。" % label)
    if len(values) != len(set(values)):
        raise GTError("%s 含重复引用。" % label)
    return sorted(values)


def compile_state(state: Any) -> Dict[str, Any]:
    goal = state.goal or {}
    if not goal.get("id") or not str(goal.get("title") or "").strip():
        raise GTError("任务图缺少当前目标及其请求。")
    active = {t.id: t for t in state.active_tasks()}
    if not active:
        raise GTError("任务图没有 active 任务。")
    criteria = {c["id"] for c in goal.get("criteria", [])}
    tasks = {}
    for task_id in sorted(active):
        task = active[task_id]
        consumers = _refs(task.consumer_refs, ["goal:" + goal["id"]], "consumer_refs")
        requirements = _refs(task.requirement_refs, ["goal:" + goal["id"]], "requirement_refs")
        for ref in consumers + requirements:
            prefix, _, key = ref.partition(":")
            valid = (prefix == "goal" and key == goal["id"]) or (prefix == "criterion" and key in criteria) or (prefix == "task" and key in active)
            if not valid:
                raise GTError("任务 %s 引用了不存在的当前消费者/需求：%s。" % (task_id, ref))
        dependencies = list(task.deps)
        children = [t.id for t in active.values() if t.parent == task_id]
        if len(dependencies) != len(set(dependencies)) or set(dependencies) - set(active):
            raise GTError("任务 %s 的依赖重复、不存在或已取消。" % task_id)
        if task.parent and task.parent not in active:
            raise GTError("任务 %s 的父任务不存在或已取消。" % task_id)
        if task.owner and task.owner == task.validator:
            raise GTError("任务负责人和验证人不能相同。")
        forbidden = task.forbidden_scope or []
        if not isinstance(forbidden, list) or any(not isinstance(p, str) for p in forbidden):
            raise GTError("forbidden_scope 必须是路径列表。")
        forbidden = sorted(set(normalize_scope(p) for p in forbidden))
        # Only a declared aggregate whose full scope is delegated gets the review default.
        # The live completion collector still checks whether the parent has its own changes.
        child_scopes = {scope for child in children for scope in active[child].scopes}
        aggregate = bool(children and task.scopes and not task.tdd and set(task.scopes) <= child_scopes)
        condition = task.exit_condition or {"required_receipt_types": ["evidence" if task.kind in ("code", "test") and not aggregate else "review"],
                                             "on_budget_exhaustion": "blocked"}
        if not isinstance(condition, dict) or set(condition) != {"required_receipt_types", "on_budget_exhaustion"}:
            raise GTError("exit_condition 必须包含 required_receipt_types 和 on_budget_exhaustion。")
        receipt_types = condition["required_receipt_types"]
        allowed = {"evidence", "review", "tdd", "affected"}
        if not isinstance(receipt_types, list) or not receipt_types or len(set(receipt_types)) != len(receipt_types) or not set(receipt_types) <= allowed:
            raise GTError("退出条件需要受支持且不重复的回执类型。")
        if condition["on_budget_exhaustion"] not in ("blocked", "replan"):
            raise GTError("预算耗尽只能 blocked 或 replan。")
        tasks[task_id] = {"spec": copy.deepcopy(task.spec()), "requirement_refs": requirements,
                          "consumer_refs": consumers, "consumer_assurance": "declared_current_goal" if task.consumer_refs is None else "declared_reference",
                          "dependencies": sorted(set(dependencies + children)), "scope_allowlist": sorted(task.scopes),
                          "forbidden_scope": forbidden, "budget": graph_budget.limits(task.budget),
                          "budget_source": "explicit" if isinstance(task.budget, dict) else "finite_policy_default",
                          "exit_source": "explicit" if task.exit_condition else ("aggregate_review_default" if aggregate else "kind_default"),
                          "exit_condition": copy.deepcopy(condition)}
    pending = {key: set(row["dependencies"]) for key, row in tasks.items()}
    layers, order = [], []
    while pending:
        layer = sorted(k for k, deps in pending.items() if not deps)
        if not layer:
            raise GTError("任务图依赖成环。")
        layers.append(layer)
        order.extend(layer)
        for key in layer:
            del pending[key]
        for deps in pending.values():
            deps.difference_update(layer)
    lengths = {}
    for key in order:
        lengths[key] = tasks[key]["budget"]["work_units"] + max((lengths[d] for d in tasks[key]["dependencies"]), default=0)
    identity = {k: copy.deepcopy(goal.get(k)) for k in ("id", "title", "mode", "impact", "criteria")}
    result = {"schema": "goal-teams/task-graph@1", "goal": identity, "plan_revision": state.plan["revision"],
              "task_ids": sorted(tasks), "tasks": tasks, "topological_order": order, "ready_layers": layers,
              "maximum_parallel_width": max(map(len, layers)),
              "total_budget_wu": sum(t["budget"]["work_units"] for t in tasks.values()),
              "critical_path_wu": max(lengths.values())}
    result["sha256"] = graph_budget.digest(result)
    return result


def structural_problems(state: Any) -> List[str]:
    if not state.active_tasks():
        return []  # the ordinary completion contract reports no tasks
    try:
        expected = compile_state(state)
        if state.plan.get("graph") != expected:
            return ["任务图未冻结或已漂移：需要对当前 TaskExactSet 重新编译。"]
        return list(graph_budget.status(state)["errors"])
    except (GTError, ValueError, TypeError, KeyError) as exc:
        return ["任务图/预算无效：%s" % exc]


def exit_problems(state: Any, task: Any, dependency: bool = False) -> List[str]:
    if not task.complete:
        return []
    graph = state.plan["graph"]
    required = graph["tasks"][task.id]["exit_condition"]["required_receipt_types"]
    receipts = [r for r in state.receipts.values() if r.get("task") == task.id and not r.get("late")
                and r.get("graph_digest") == graph["sha256"] and r.get("id") not in state.retired]
    current_code = getattr(state, "graph_code_digest", None)
    current_scope = getattr(state, "graph_scope_digests", {}).get(task.id)
    def current(receipt):
        if dependency and task.scopes and current_scope and receipt.get("task_scope_digest"):
            return receipt["task_scope_digest"] == current_scope
        return bool(current_code and receipt.get("code_digest") == current_code)
    good = [r for r in receipts if not r.get("manual") and current(r)
            and (r.get("passed") is True or r.get("outcome") == "green_ok")]
    checks = {"evidence": bool(good), "affected": any(r.get("kind") == "affected" for r in good),
              "tdd": any(r.get("outcome") == "green_ok" for r in good) and any(r.get("outcome") == "red_verified" for r in receipts),
              "review": bool(task.reviews and task.reviews[-1].get("verdict") == "pass"
                             and (task.reviews[-1].get("binds") or {}).get("graph_digest") == graph["sha256"])}
    problems = ["任务 %s 的退出条件缺少当前 %s 回执。" % (task.id, kind) for kind in required if not checks[kind]]
    if any(r.get("task") == task.id for r in state.open_failures()):
        problems.append("任务 %s 仍有未闭合的失败命令。" % task.id)
    latest_green = state.latest_green(task.id)
    if latest_green and latest_green.get("outcome") != "green_ok":
        problems.append("任务 %s 最近一次 Green 未通过。" % task.id)
    if state.open_red(task.id):
        problems.append("任务 %s 仍有未闭合的 Red。" % task.id)
    for dep in graph["tasks"][task.id]["dependencies"]:
        if not state.tasks[dep].complete or exit_problems(state, state.tasks[dep], dependency=True):
            problems.append("任务 %s 的前驱 %s 尚未满足退出条件。" % (task.id, dep))
    return problems


def completion_problems(state: Any) -> List[str]:
    problems = structural_problems(state)
    if problems or not state.active_tasks():
        return problems
    return [reason for task in state.active_tasks() for reason in exit_problems(state, task)]


def ensure_frozen(ctx: Any) -> Any:
    state = ctx.state(refresh=True)
    compiled = compile_state(state)
    if state.plan.get("graph") == compiled:
        if state.graph_errors:
            raise GTError("任务图事件损坏：%s" % "; ".join(state.graph_errors), code=EXIT.blocked)
        return state
    goal_id = state.goal["id"]
    def expect(current):
        ctx.expect_same_goal(goal_id)(current)
        if compile_state(current) != compiled:
            raise GTError("冻结期间任务规格变化；请重新读取。", code=EXIT.conflict)
        trial = copy.deepcopy(current)
        trial.plan["graph"] = compiled
        graph_budget.status(trial)  # a revision cannot erase spent work
    ctx.append("graph.frozen", {"graph": compiled}, expect=expect)
    return ctx.state(refresh=True)


def blocked_closure(state: Any) -> List[str]:
    active = {t.id: t for t in state.active_tasks()}
    affected = {t.id for t in active.values() if t.state == "blocked"}
    changed = True
    while changed:
        changed = False
        for t in active.values():
            deps = set(t.deps) | {c.id for c in active.values() if c.parent == t.id}
            if t.id not in affected and deps & affected:
                affected.add(t.id)
                changed = True
    return sorted(affected)


def ready_tasks(state: Any) -> List[str]:
    if structural_problems(state):
        return []
    blocked = set(blocked_closure(state))
    budgets = graph_budget.status(state)["tasks"]
    ready = []
    for task in state.active_tasks():
        if task.id in blocked or (task.complete and not exit_problems(state, task)) or task.state not in ("pending", "in_progress", "done", "accepted"):
            continue
        deps = state.plan["graph"]["tasks"][task.id]["dependencies"]
        remaining = budgets[task.id]["remaining"]
        if all(state.tasks[d].complete and not exit_problems(state, state.tasks[d], dependency=True) for d in deps) and remaining["work_units"] > 0 and (remaining["attempts"] > 0 or remaining["revalidations"] > 0):
            ready.append(task.id)
    return sorted(ready)


def require_ready(state: Any, task_id: str) -> None:
    problems = structural_problems(state)
    if problems:
        raise GTError("；".join(problems), code=EXIT.blocked)
    task = state.tasks.get(task_id)
    if task is None or not task.active or task_id in blocked_closure(state):
        raise GTError("任务不在可执行图中或被 blocker 阻塞。", code=EXIT.blocked)
    deps = state.plan["graph"]["tasks"][task_id]["dependencies"]
    waiting = [d for d in deps if not state.tasks[d].complete or exit_problems(state, state.tasks[d], dependency=True)]
    if waiting:
        raise GTError("任务图依赖尚未通过：%s；不能用 --force 越过。" % ", ".join(waiting), code=EXIT.blocked)


def context_receipt(state: Any, task_id: str, text: str) -> Dict[str, Any]:
    if structural_problems(state):
        raise GTError("上下文包需要当前冻结任务图。", code=EXIT.blocked)
    raw = text.encode("utf-8")
    estimate = (len(raw) + 3) // 4
    limit = state.plan["graph"]["tasks"][task_id]["budget"]["context_tokens"]
    if estimate > limit:
        raise GTError("任务 %s 上下文预算超限：估算 %d > %d。" % (task_id, estimate, limit), code=EXIT.blocked)
    return {"task_id": task_id, "graph_digest": state.plan["graph"]["sha256"], "bytes": len(raw),
            "estimated_tokens": estimate, "limit": limit, "algorithm": "ceil_utf8_bytes_div_4",
            "payload_sha256": graph_budget.sha256_text(text)}


def classify_finding(state: Any, finding: Dict[str, Any], current_source_digest: str = None) -> Dict[str, Any]:
    if structural_problems(state):
        raise GTError("finding 需要当前冻结任务图。")
    if not isinstance(finding, dict) or not finding.get("finding_id") or finding.get("task_id") not in state.plan["graph"]["tasks"]:
        raise GTError("finding 必须绑定当前任务与唯一 ID。")
    if any("remaining" in k for k in finding):
        raise GTError("禁止调用者提交剩余预算；必须重放账本。")
    gates = {"evidence_verified": "observed_only", "in_locked_scope": "new_revision_required",
             "consumer_confirmed": "backlog_candidate", "authorization_boundary_unchanged": "blocked"}
    for key, outcome in gates.items():
        if type(finding.get(key)) is not bool:
            raise GTError("finding 准入字段必须为布尔值。")
        if not finding[key]:
            return {"admitted": False, "classification": outcome, "reason": key}
    if not isinstance(finding.get("evidence_refs"), list) or not finding["evidence_refs"]:
        raise GTError("finding 必须有复现证据引用。")
    task = state.tasks[finding["task_id"]]
    paths = finding.get("paths")
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise GTError("finding 必须列出实际修复路径。")
    for path in paths:
        normalized = normalize_scope(path)
        if normalized != path or not matches_any(path, task.scopes) or matches_any(path, task.forbidden_scope):
            return {"admitted": False, "classification": "new_revision_required", "reason": "scope_not_proven"}
    for ref in finding["evidence_refs"]:
        receipt = state.receipts.get(ref)
        if not receipt or receipt.get("task") != task.id or receipt.get("late") or ref in state.retired:
            return {"admitted": False, "classification": "observed_only", "reason": "missing_current_reproduction"}
        failed = (receipt.get("type") == "tdd.red" and receipt.get("outcome") == "red_verified") or (
            receipt.get("type") == "run" and receipt.get("passed") is False and receipt.get("exit_code") not in (124, 126, 127))
        # Red's source digest excludes its test files; code_digest binds the entire
        # tested tree, including those files, just as the live snapshot does.
        reproduced_tree = receipt.get("code_digest", receipt.get("source_digest"))
        if (not failed or not current_source_digest or reproduced_tree != current_source_digest
                or receipt.get("graph_digest") != state.plan["graph"]["sha256"]):
            return {"admitted": False, "classification": "observed_only", "reason": "stale_or_unverified_reproduction"}
    remaining = graph_budget.status(state)["tasks"][finding["task_id"]]["remaining"]
    mapping = {"work_units": "estimated_work_units", "attempts": "estimated_attempts", "revalidations": "estimated_revalidations"}
    for axis, key in mapping.items():
        amount = finding.get(key)
        if type(amount) is not int or amount < 0:
            raise GTError("finding 预计成本必须是非负整数。")
        if amount > remaining[axis]:
            return {"admitted": False, "classification": "blocked", "reason": "budget_exhausted", "remaining": remaining}
    return {"admitted": True, "classification": "admitted", "remaining": remaining,
            "consumer_assurance": state.plan["graph"]["tasks"][finding["task_id"]]["consumer_assurance"],
            "authorization_assurance": "operator_declaration",
            "graph_digest": state.plan["graph"]["sha256"], "finding_sha256": graph_budget.digest(finding)}
