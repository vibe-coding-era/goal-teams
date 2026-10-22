"""Planning service: every change to the task set goes through the same validation and revision.

``gt plan apply plan.json`` validates the whole plan in memory and commits it as one
``plan.applied`` event (any invalid task rejects the whole file). ``gt task add/edit/cancel``
call the same validation on a trial state, so a manual edit can never bypass the revision counter
or sneak in a cycle, an unknown dependency or a duplicate id (AC06).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import checks, gitinfo
from .context import Ctx, _check_member, _scopes
from .models import TASK_INPUT_FIELDS, Task
from .state import State, reduce
from .util import EXIT, GTError, matches_any, split_csv

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KINDS = ("code", "test", "doc", "review", "ops")
PLAN_SCHEMA = "goal-teams/plan@1"


# --------------------------------------------------------------------------- validation
def plan_problems(state: State) -> Tuple[List[str], List[str]]:
    """``(errors, warnings)`` of the active task set. Errors block ``plan apply`` and the plan gate;
    warnings are reported. tracked goals need validator/scope/exit on code and test tasks."""
    errors: List[str] = []
    warnings: List[str] = []
    goal = state.goal or {}
    strict = (goal.get("mode") or "tracked") == "tracked"
    tasks = state.active_tasks()
    if not tasks:
        errors.append("没有任务")
    layers, path, width, cycle = state.dag()
    if cycle:
        errors.append("依赖成环：%s" % ", ".join(cycle))
    for task in tasks:
        missing = [d for d in task.deps if d not in state.tasks]
        if missing:
            errors.append("%s 的依赖不存在：%s" % (task.id, ", ".join(missing)))
        if not task.accept:
            (errors if strict else warnings).append("%s 缺少验收标准（accept）" % task.id)
        if task.kind in ("code", "test"):
            for field, flag in (("scopes", "scope"), ("exit", "exit")):
                if not getattr(task, field):
                    (errors if strict else warnings).append("%s 缺少 %s" % (task.id, flag))
        if task.owner and task.owner == task.validator:
            errors.append("%s 的负责人和验证人相同" % task.id)
        if task.parent and task.parent not in state.tasks:
            errors.append("%s 的父任务不存在：%s" % (task.id, task.parent))
    return errors, warnings


def _test_scope_overlaps(ctx: Ctx, state: State) -> List[str]:
    """A test task's scope must not swallow code files, and code files that look like tests do not
    count as implementation: both would make Green impossible."""
    tests = [t for t in state.active_tasks() if t.kind == "test" and t.scopes]
    code = [t for t in state.active_tasks() if t.kind == "code" and t.scopes]
    if not code:
        return []
    files = gitinfo.project_files(ctx.project.work_tree)
    out = []
    for task in code:
        lookalikes = [p for p in files if matches_any(p, task.scopes)
                      and any(seg in ("fixtures", "testdata") for seg in p.split("/")[:-1])
                      and p.lower().endswith((".py", ".js", ".ts", ".go", ".rb", ".java", ".rs"))]
        if lookalikes:
            out.append("%s 的范围里有像测试或测试数据的代码文件 %s：它们的改动不算实现；"
                       "测试读取的数据文件请用 --test 绑定" % (task.id, ", ".join(lookalikes[:5])))
    for test in tests:
        hits = [p for p in files if matches_any(p, test.scopes) and not matches_any(p, checks.TEST_PATTERNS)
                and any(matches_any(p, c.scopes) for c in code)]
        if hits:
            out.append("%s（测试任务）的范围包含代码文件 %s：这些文件的改动不再算实现，Green 会失败；"
                       "测试任务的范围只放测试文件" % (test.id, ", ".join(hits[:5])))
    return out


def normalize_task(raw: Dict[str, Any], existing: Optional[Task] = None) -> Dict[str, Any]:
    """A task spec from a plan file or the CLI, normalized and type-checked (no state yet)."""
    if not isinstance(raw, dict):
        raise GTError("任务条目必须是对象：%r" % (raw,))
    unknown = sorted(set(raw) - set(TASK_INPUT_FIELDS) - {"scope", "artifact"})
    if unknown:
        raise GTError("任务 %s 有未知字段：%s" % (raw.get("id"), ", ".join(unknown)),
                      hint="可用字段：%s" % ", ".join(TASK_INPUT_FIELDS))
    task_id = str(raw.get("id") or "")
    if not ID_RE.match(task_id) or task_id.startswith("@"):
        raise GTError("任务 ID 只能包含字母、数字、. _ -，最长 64：%r" % task_id)
    data: Dict[str, Any] = {"id": task_id}
    title = raw.get("title", existing.title if existing else None)
    if not title:
        raise GTError("任务 %s 缺少标题。" % task_id)
    data["title"] = str(title)
    scopes = raw.get("scopes", raw.get("scope"))
    data["scopes"] = _scopes(list(scopes) if isinstance(scopes, (list, tuple)) else ([scopes] if scopes else [])) \
        if scopes is not None else (list(existing.scopes) if existing else [])
    deps = raw.get("deps")
    if deps is None:
        data["deps"] = list(existing.deps) if existing else []
    else:
        data["deps"] = split_csv(deps if isinstance(deps, (list, tuple)) else [str(deps)])
    artifacts = raw.get("artifacts", raw.get("artifact"))
    data["artifacts"] = list(artifacts) if artifacts else (list(existing.artifacts) if existing else [])
    for key in ("parent", "accept", "exit", "budget", "requirement_refs", "consumer_refs", "forbidden_scope", "exit_condition"):
        data[key] = raw.get(key, getattr(existing, key) if existing else None)
    data["forbidden_scope"] = data["forbidden_scope"] or []
    from .graph_budget import limits
    limits(data["budget"])
    for key in ("owner", "validator"):
        data[key] = _check_member(raw.get(key)) if key in raw else (getattr(existing, key) if existing else None)
    data["priority"] = str(raw.get("priority", existing.priority if existing else "P1"))
    tdd = raw.get("tdd", existing.tdd if existing else False)
    data["tdd"] = tdd if isinstance(tdd, bool) else str(tdd).lower() in ("1", "true", "on", "yes")
    kind = raw.get("kind", existing.kind if existing else "code")
    if kind not in KINDS:
        raise GTError("任务 %s 的 kind 必须是 %s" % (task_id, "|".join(KINDS)))
    data["kind"] = kind
    if data["owner"] and data["owner"] == data["validator"]:
        raise GTError("任务 %s 的负责人和验证人不能是同一个成员。" % task_id)
    if task_id in data["deps"]:
        raise GTError("任务 %s 不能依赖自己。" % task_id)
    return data


def trial(state_events: List[Dict[str, Any]], extra_events: List[Dict[str, Any]]) -> State:
    """Reduce the ledger plus not-yet-written events: validation happens on the result, not on files."""
    seq = (int(state_events[-1].get("seq", len(state_events))) if state_events else 0)
    events = list(state_events)
    for offset, event in enumerate(extra_events, start=1):
        events.append(dict(event, seq=seq + offset))
    return reduce(events)


def validate_task_set(ctx: Ctx, extra_events: List[Dict[str, Any]], strict_errors: bool = True) -> Tuple[State, List[str]]:
    """Apply ``extra_events`` to a trial state and validate the task set. Returns the trial state and
    warnings; raises on structural errors (unknown dependency, cycle, duplicate, same owner/validator)."""
    state = trial(ctx.project.events(), extra_events)
    errors, warnings = plan_problems(state)
    structural = [e for e in errors if any(key in e for key in ("成环", "依赖不存在", "父任务不存在", "相同", "没有任务"))]
    if structural:
        raise GTError("计划无效：\n- " + "\n- ".join(structural), hint="没有写入任何事件；修正后重试。")
    if strict_errors and errors:
        raise GTError("计划无效：\n- " + "\n- ".join(errors), hint="没有写入任何事件；修正后重试。")
    warnings = warnings + [e for e in errors if e not in structural] if not strict_errors else warnings
    return state, warnings


# --------------------------------------------------------------------------- plan file
def load_plan_file(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GTError("读不到计划文件：%s" % exc)
    except ValueError as exc:
        raise GTError("计划文件不是有效 JSON：%s" % exc, hint='格式：{"tasks": [{"id": "T1", "title": "...", ...}]}')
    if isinstance(data, list):
        data = {"tasks": data}
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list) or not data["tasks"]:
        raise GTError("计划文件需要非空的 tasks 列表。", hint='格式：{"tasks": [{"id": "T1", "title": "...", ...}]}')
    if data.get("schema") not in (None, PLAN_SCHEMA):
        raise GTError("计划文件 schema 不是 %s：%s" % (PLAN_SCHEMA, data.get("schema")))
    return data


def apply_plan(ctx: Ctx, plan: Dict[str, Any], note: Optional[str] = None) -> Dict[str, Any]:
    """Validate the whole plan on a trial state, then commit it as one ``plan.applied`` event."""
    state = ctx.active_goal_required()
    specs: List[Dict[str, Any]] = []
    seen = set()
    for raw in plan["tasks"]:
        existing = state.tasks.get(str(raw.get("id") or ""))
        spec = normalize_task(raw, existing)
        if spec["id"] in seen:
            raise GTError("计划文件里 %s 出现了两次。" % spec["id"])
        seen.add(spec["id"])
        if existing is not None and not existing.active:
            raise GTError("%s 已取消，不能在计划里复用它的 ID。" % spec["id"])
        specs.append(spec)
    adds = [s for s in specs if s["id"] not in state.tasks]
    edits = [s for s in specs if s["id"] in state.tasks]
    ids = {s["id"] for s in specs} | set(state.tasks)
    for spec in specs:
        if spec.get("parent") and spec["parent"] not in ids:
            raise GTError("%s 的父任务不存在：%s" % (spec["id"], spec["parent"]))
        if spec.get("parent") and spec["parent"] in {s["id"] for s in specs if s.get("parent")}:
            raise GTError("只支持两层：%s 的父任务 %s 已经是子任务。" % (spec["id"], spec["parent"]))
    revision = state.plan["revision"] + 1
    event = {"type": "plan.applied", "data": {"revision": revision, "tasks": specs, "note": note}}
    trial_state, warnings = validate_task_set(ctx, [event])
    from . import graph_contract, graph_budget
    graph = graph_contract.compile_state(trial_state)
    trial_state.plan["graph"] = graph
    graph_budget.status(trial_state)
    layers, path, width, _ = trial_state.dag()
    warnings = warnings + _test_scope_overlaps(ctx, trial_state)
    goal_id = ctx.goal_id()

    def expect(current: State) -> None:
        ctx.expect_same_goal(goal_id)(current)
        if current.plan["revision"] != state.plan["revision"]:
            raise GTError("计划在此期间变成了 r%d，本次未写入；请重新读取后再 apply。" % current.plan["revision"],
                          code=EXIT.conflict)
        for spec in adds:
            if spec["id"] in current.tasks:
                raise GTError("任务 %s 刚被另一个进程添加，本次未写入。" % spec["id"], code=EXIT.conflict)

    data = dict(event["data"], layers=layers, critical_path=path, width=width, source="file" if plan.get("tasks") else "manual",
                added=[s["id"] for s in adds], edited=[s["id"] for s in edits], graph=graph)
    ctx.append("plan.applied", data, expect=expect)
    return {"revision": revision, "added": data["added"], "edited": data["edited"], "layers": layers,
            "critical_path": path, "width": width, "warnings": warnings}


def apply_current(ctx: Ctx, note: Optional[str] = None) -> Dict[str, Any]:
    """``gt plan freeze`` compatibility: validate the current task set and record it as a revision."""
    state = ctx.active_goal_required()
    specs = [normalize_task({"id": t.id, "title": t.title}, t) for t in state.active_tasks()]
    if not specs:
        raise GTError("没有任务可以校验。", hint="gt plan apply plan.json，或 gt task add ...")
    return apply_plan(ctx, {"tasks": specs}, note)


# --------------------------------------------------------------------------- manual edits
def add_task(ctx: Ctx, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    state = ctx.active_goal_required()
    spec = normalize_task(raw)
    if spec["id"] in state.tasks:
        raise GTError("任务 %s 已存在。" % spec["id"], hint="修改用 gt task edit %s ..." % spec["id"])
    if spec.get("parent"):
        parent = state.tasks.get(spec["parent"])
        if parent is None:
            raise GTError("父任务 %s 不存在。" % spec["parent"])
        if parent.parent:
            raise GTError("只支持两层：%s 已经是子任务。" % spec["parent"])
    missing = [d for d in spec["deps"] if d not in state.tasks]
    if missing:
        raise GTError("依赖不存在：%s" % ", ".join(missing), hint="先添加被依赖的任务。")
    event = {"type": "task.add", "data": spec}
    _, warnings = validate_task_set(ctx, [event], strict_errors=False)
    goal_id = ctx.goal_id()

    def expect(current: State) -> None:
        ctx.expect_same_goal(goal_id)(current)
        if spec["id"] in current.tasks:
            raise GTError("任务 %s 刚被另一个进程添加，本次未记录。" % spec["id"], code=EXIT.conflict,
                          hint="gt task list 查看后再决定。")

    ctx.append("task.add", spec, expect=expect)
    return spec, [w for w in warnings if w.startswith(spec["id"] + " ")]


def edit_task(ctx: Ctx, task: Task, changes: Dict[str, Any]) -> List[str]:
    if not changes:
        raise GTError("没有要修改的字段。")
    owner = changes.get("owner", task.owner)
    validator = changes.get("validator", task.validator)
    if owner and owner == validator:
        raise GTError("负责人和验证人不能是同一个成员。")
    if "deps" in changes and task.id in changes["deps"]:
        raise GTError("任务不能依赖自己。")
    event = {"type": "task.edit", "data": {"id": task.id, "changes": changes}}
    _, warnings = validate_task_set(ctx, [event], strict_errors=False)
    ctx.append("task.edit", event["data"], expect=ctx.expect_task(task.id, ctx.goal_id()))
    return [w for w in warnings if w.startswith(task.id + " ")]
