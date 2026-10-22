"""Finite per-task budgets, projected from the same durable ledger as execution.

A work unit is one admitted command operation, not elapsed time or money.
The first execution and a new Red consume an attempt; Green and subsequent checks
consume revalidation. Context is a per-packet ceiling, not a cumulative bill.
"""
from __future__ import annotations

from typing import Any, Dict

from .util import GTError, EXIT, canonical_json, sha256_text

DEFAULT_LIMITS = {"work_units": 32, "attempts": 16, "revalidations": 16, "context_tokens": 12000}
AXES = ("work_units", "attempts", "revalidations")


def digest(value: Any) -> str:
    return sha256_text(canonical_json(value))


def limits(value: Any) -> Dict[str, int]:
    # Old textual budgets remain notes. The finite policy allocation is explicit in the frozen graph.
    if value is None or isinstance(value, str):
        return dict(DEFAULT_LIMITS)
    if not isinstance(value, dict) or set(value) != set(DEFAULT_LIMITS):
        raise GTError("任务预算必须包含 work_units / attempts / revalidations / context_tokens。")
    for key, amount in value.items():
        if type(amount) is not int or amount < (0 if key == "revalidations" else 1):
            raise GTError("任务预算 %s 必须是%s整数。" % (key, "非负" if key == "revalidations" else "正"))
    return dict(value)


def _validate(charge: Dict[str, Any]) -> None:
    fields = {"schema", "goal_id", "task_id", "graph_digest", "plan_revision", "operation", "kind", "amounts", "sha256"}
    if not isinstance(charge, dict) or set(charge) != fields or charge.get("schema") != "goal-teams/graph-charge@1":
        raise GTError("预算事件结构无效。")
    payload = {k: v for k, v in charge.items() if k != "sha256"}
    if digest(payload) != charge["sha256"]:
        raise GTError("预算事件摘要不匹配。")
    if type(charge["plan_revision"]) is not int or charge["plan_revision"] < 0:
        raise GTError("预算事件 revision 无效。")
    for key in ("goal_id", "task_id", "operation", "graph_digest"):
        if not isinstance(charge[key], str) or not charge[key].strip():
            raise GTError("预算事件 %s 缺失。" % key)
    expected = {"work_units": 1, "attempts": int(charge["kind"] == "implementation"),
                "revalidations": int(charge["kind"] == "revalidation")}
    if charge["kind"] not in ("implementation", "revalidation") or charge["amounts"] != expected:
        raise GTError("预算事件消费类型或额度无效。")
    if any(type(x) is not int for x in charge["amounts"].values()):
        raise GTError("预算消费必须是整数。")


def status(state: Any) -> Dict[str, Any]:
    graph = state.plan.get("graph")
    if not isinstance(graph, dict):
        return {"schema": "goal-teams/graph-budget@1", "tasks": {}, "errors": ["任务图尚未冻结"]}
    used: Dict[str, Dict[str, int]] = {}
    operations = set()
    for event in state.graph_charges:
        _validate(event)
        if event["goal_id"] != (state.goal or {}).get("id"):
            raise GTError("预算事件属于另一目标。")
        if event["operation"] in operations:
            raise GTError("预算事件重复消费：%s。" % event["operation"])
        operations.add(event["operation"])
        totals = used.setdefault(event["task_id"], {a: 0 for a in AXES})
        for key in AXES:
            totals[key] += event["amounts"][key]
    tasks = {}
    for task_id, contract in graph["tasks"].items():
        allocated = limits(contract["budget"])
        consumed = used.get(task_id, {a: 0 for a in AXES})
        remaining = {a: allocated[a] - consumed[a] for a in AXES}
        if any(n < 0 for n in remaining.values()):
            raise GTError("任务 %s 的新预算小于已消费额度；不能通过重计划抹掉历史。" % task_id)
        tasks[task_id] = {"allocated": allocated, "consumed": dict(consumed), "remaining": remaining,
                          "exhausted": [a for a in AXES if remaining[a] == 0],
                          "on_exhaustion": contract["exit_condition"]["on_budget_exhaustion"]}
    result = {"schema": "goal-teams/graph-budget@1", "graph_digest": graph["sha256"], "tasks": tasks,
              "events": len(state.graph_charges), "errors": list(getattr(state, "graph_errors", []))}
    result["sha256"] = digest(result)
    return result


def charge(state: Any, task_id: str, kind: str, operation: str) -> Dict[str, Any]:
    if kind not in ("implementation", "revalidation"):
        raise GTError("未知预算消费类型。")
    if any(e.get("operation") == operation for e in state.graph_charges):
        raise GTError("预算操作已经记账：%s。" % operation, code=EXIT.conflict)
    snapshot = status(state)
    if snapshot["errors"] or task_id not in snapshot["tasks"]:
        raise GTError("任务图或预算状态无效，不能启动操作。", code=EXIT.blocked)
    amounts = {"work_units": 1, "attempts": int(kind == "implementation"), "revalidations": int(kind == "revalidation")}
    row = snapshot["tasks"][task_id]
    if any(amounts[a] > row["remaining"][a] for a in AXES):
        raise GTError("任务 %s 预算耗尽（%s）；%s，操作未执行。" %
                      (task_id, row["remaining"], row["on_exhaustion"]), code=EXIT.blocked)
    result = {"schema": "goal-teams/graph-charge@1", "goal_id": state.goal["id"], "task_id": task_id,
              "graph_digest": state.plan["graph"]["sha256"], "plan_revision": state.plan["revision"],
              "operation": operation, "kind": kind, "amounts": amounts}
    result["sha256"] = digest(result)
    return result


def observe(state: Any, event: Dict[str, Any]) -> None:
    """Reducer hook: a malformed or unbound charge is a completion blocker, never ignored."""
    try:
        _validate(event)
        expected = charge(state, event["task_id"], event["kind"], event["operation"])
        if expected != event:
            raise GTError("预算事件未绑定当时的冻结任务图。")
        state.graph_charges.append(event)
    except (GTError, KeyError, TypeError) as exc:
        state.graph_errors.append(str(exc))
