"""Shared command context: project, state, actor, output and projections."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import checks, gitinfo, render
from .ledger import Project, find_root, init_state
from .state import State, Task, reduce
from .util import EXIT, GTError, normalize_scope, pretty_json, web_url

SKILL_DIR = Path(__file__).resolve().parents[2]
GT_SCRIPT = SKILL_DIR / "scripts" / "gt.py"


class Ctx:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project = Project(find_root(Path.cwd(), getattr(args, "root", None)))
        self._state: Optional[State] = None

    @property
    def actor(self) -> str:
        return getattr(self.args, "as_", None) or os.environ.get("GT_ACTOR") or "lead"

    @property
    def config(self) -> Dict[str, Any]:
        return self.project.config()

    @property
    def lang(self) -> str:
        return getattr(self.args, "lang", None) or self.config.get("locale") or "zh"

    @property
    def json(self) -> bool:
        return bool(getattr(self.args, "json", False))

    def state(self, refresh: bool = False) -> State:
        if self._state is None or refresh:
            state = reduce(self.project.events())
            if state.goal is not None and self.project.exists():
                checks.annotate(self.project, state)  # stale reviews are not complete
            self._state = state
        return self._state

    def goal_required(self) -> State:
        self.project.require()
        state = self.state()
        if state.goal is None:
            raise GTError("还没有目标。", hint='先运行 gt goal "<目标>" --done "<完成标准>" --size medium')
        return state

    def active_goal_required(self) -> State:
        state = self.goal_required()
        if state.goal.get("status") != "active":
            raise GTError("目标已结束（%s）。" % state.goal.get("outcome"),
                          hint="开始新目标：gt goal \"<目标>\" ...")
        return state

    def append(self, event_type: str, data: Any,
               prepare: Optional[Callable[[int, str], Tuple[Dict[str, Any], Callable[[], None]]]] = None,
               expect: Optional[Callable[[State], None]] = None) -> Dict[str, Any]:
        """Append an event; ``expect(state)`` re-checks a precondition on the state as it is under
        the lock, so two contexts that read the same stale snapshot cannot both get through."""
        checker = None
        if expect is not None:
            def checker(events: List[Dict[str, Any]]) -> None:
                expect(reduce(events))
        return self.project.append(event_type, data, self.actor, prepare, after=self._regenerate_safe,
                                   expect=checker)

    def goal_id(self) -> Optional[str]:
        goal = self.state().goal
        return goal.get("id") if goal else None

    def expect_same_goal(self, goal_id: Optional[str]) -> Callable[[State], None]:
        def check(state: State) -> None:
            current = state.goal.get("id") if state.goal else None
            if current != goal_id:
                raise GTError("目标在此期间被替换（%s → %s），本次操作未记录；请在当前目标上重新执行。" % (goal_id, current),
                              code=EXIT.conflict)
        return check

    def expect_task(self, task_id: str, goal_id: Optional[str], states: Tuple[str, ...] = ()) -> Callable[[State], None]:
        def check(state: State) -> None:
            self.expect_same_goal(goal_id)(state)
            task = state.tasks.get(task_id)
            if task is None or not task.active:
                raise GTError("任务 %s 在此期间被取消或删除，本次操作未记录。" % task_id, code=EXIT.conflict)
            if states and task.state not in states:
                raise GTError("任务 %s 在此期间变成了 %s，本次操作未记录；请重新查看 gt task list。" % (task_id, task.state),
                              code=EXIT.conflict)
        return check

    def _regenerate_safe(self) -> None:
        """Projections are regenerated under the ledger lock; failing to write them never fails the command."""
        try:
            self.regenerate()
        except Exception as exc:  # noqa: BLE001 - best effort, the ledger is the record
            print("gt: 未能更新 TaskList.md / benchmark.md：%s" % exc, file=sys.stderr)

    def regenerate(self) -> None:
        # A fresh reduced state and one filesystem snapshot drive both projections.
        # append still invokes this under its ledger lock; never cache Live across calls.
        state = reduce(self.project.events())
        snapshot = checks.collect(self.project, state)
        self._state = state
        config = snapshot.config
        diff = snapshot.diff
        oos = len(diff["out_of_scope"]) if diff.get("available") and diff.get("scoped") else None
        _atomic_write(self.project.state / "TaskList.md", render.tasklist_md(state, config))
        _atomic_write(self.project.state / "benchmark.md", render.benchmark_md(
            state, config, axes=checks.receipt_axes(self.project, state, snapshot=snapshot) if state.goal else None,
            oos=oos))

    def oos(self) -> Optional[int]:
        """Live count of out-of-scope changed files (None when unknown)."""
        state = self.state()
        if state.goal is None:
            return None
        diff = checks.live_diff(self.project, state)
        if not diff.get("available") or not diff.get("scoped"):
            return None
        return len(diff["out_of_scope"])

    def task(self, task_id: str) -> Task:
        state = self.state()
        task = state.tasks.get(task_id)
        if task is None:
            known = ", ".join(list(state.tasks)[:20]) or "（无）"
            raise GTError("没有任务 %s。" % task_id, hint="已有任务：%s" % known)
        return task

    def web(self) -> Optional[str]:
        for remote in gitinfo.remotes(self.project.work_tree):
            if remote["name"] == "origin":
                return web_url(remote["url"])
        return None


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def out(ctx: Ctx, text: str, payload: Any = None) -> None:
    if ctx.json and payload is not None:
        print(pretty_json(payload))
    else:
        print(text)


def _scopes(values: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    for value in values or []:
        scope = normalize_scope(value)
        if scope not in out:
            out.append(scope)
    return out


def _check_member(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    name = name.strip()
    if name.startswith("goal-teams:"):
        name = name.split(":", 1)[1]
    return name or None


def _set_state(ctx: Ctx, task: Task, target: str, **extra: Any) -> None:
    from . import graph_contract
    if target in ("in_progress", "done"):
        state = graph_contract.ensure_frozen(ctx)
        graph_contract.require_ready(state, task.id)
    data = {"id": task.id, "to": target}
    data.update({k: v for k, v in extra.items() if v is not None})
    # the transition was validated on a snapshot; make sure it still holds under the lock
    allowed = {"in_progress": ("pending", "in_progress"), "done": ("pending", "in_progress"),
               "blocked": ("pending", "in_progress", "done", "blocked"), "unblocked": ("blocked",),
               "cancelled": ("pending", "in_progress", "done", "blocked")}
    check_task = ctx.expect_task(task.id, ctx.goal_id(), allowed.get(target, ()))
    def expect(current):
        check_task(current)
        if target in ("in_progress", "done"):
            checks.annotate(ctx.project, current)
            graph_contract.require_ready(current, task.id)
    ctx.append("task.state", data, expect=expect)


def ensure_direct_state(ctx: Ctx, task_id: Optional[str], tdd: bool = False, title: Optional[str] = None) -> bool:
    """direct mode's lazy state (GT-CORE-DIRECT): the first evidence command in a project without a
    goal creates the state directory, a minimal direct goal and the task it names — without questions.
    Returns True when something was created. tracked goals never get tasks invented for them."""
    from . import routes
    from .util import now_iso
    created = False
    project = ctx.project
    if not project.exists():
        init_state(project, None, None)
        work = project.work_tree
        git: Dict[str, Any] = {"repo": gitinfo.is_repo(work)}
        if git["repo"]:
            git.update({"head": gitinfo.head(work), "branch": gitinfo.branch(work)})
        from . import VERSION
        ctx.append("init", {"project": ctx.config["project"], "locale": ctx.config.get("locale"), "git": git,
                            "gt_version": VERSION, "auto": True})
        created = True
    state = ctx.state(refresh=True)
    if state.goal is None or state.goal.get("status") != "active":
        facts = routes.describe("direct")
        work = project.work_tree
        baseline: Dict[str, Any] = {"head": None, "branch": None}
        if gitinfo.is_repo(work):
            baseline = {"head": gitinfo.head(work), "branch": gitinfo.branch(work), "dirty": gitinfo.status_counts(work)}
        goal_id = "G%d" % (len(state.goal_history) + (1 if state.goal else 0) + 1)
        data = {"id": goal_id, "title": title or "直接执行（%s）" % now_iso()[:10], "criteria": [], "mode": "direct",
                "risk": "normal", "domains": facts["domains"], "impact": "behavior_change", "phase": "development",
                "size": "small", "flags": facts["flags"], "gates": facts["gates"],
                "route": {"rules": facts["rules"], "team": facts["team"]}, "baseline": baseline, "auto": True,
                "evidence_mode": "tracked"}
        if state.goal is not None and state.goal.get("status") == "active":
            data["replaces"] = state.goal.get("id")
        ctx.append("goal", data)
        created = True
        print("gt: 已为 direct 工作自动建立最小状态（%s，目标 %s）；不需要计划或看板。" % (project.state, goal_id), file=sys.stderr)
    state = ctx.state(refresh=True)
    if task_id and task_id not in state.tasks and (state.goal.get("mode") == "direct"):
        from .planning import add_task
        add_task(ctx, {"id": task_id, "title": title or task_id, "owner": ctx.actor if ctx.actor != "lead" else None,
                       "tdd": tdd, "kind": "code"})
        ctx.state(refresh=True)
        created = True
    return created


def gt_command() -> str:
    """The exact interpreter running gt now, so packets work on Windows (no ``python3`` there)."""
    return '"%s" "%s"' % (sys.executable or "python3", GT_SCRIPT)


def _cwd_rel(ctx: Ctx, path: Path) -> str:
    """The working directory relative to the work tree (so a receipt can be re-run in another tree)."""
    try:
        return path.resolve().relative_to(ctx.project.work_tree).as_posix() or "."
    except ValueError:
        return str(path)
