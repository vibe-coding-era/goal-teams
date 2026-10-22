"""Explicit operator settlement of orphan commands; interruption is never passing evidence.

The PID observation covers the gt worker only. --confirm-stopped is the operator's
confirmation that its descendants were stopped too, not an OS-level guarantee.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from .util import EXIT, GTError, pid_alive


def observe(state: Any, event: Dict[str, Any], data: Dict[str, Any], seq: int) -> None:
    """Replay a settlement only against its still-current exact run.started event."""
    started = data.get("started")
    original = state.running.get(started) if type(started) is int else None
    goal = state.goal or {}
    if (original is None or data.get("original") != original or data.get("goal") != goal.get("id")
            or goal.get("status") != "active" or data.get("passed") is not False
            or data.get("confirmed_stopped") is not True or data.get("pid_observation") != "not_alive"
            or not isinstance(data.get("reason"), str) or not data["reason"].strip()):
        state.recovery_errors.append("中断结算未绑定当前命令：seq %s" % seq)
        return
    state.running.pop(started)
    state.interrupted_runs.append(dict(data, seq=seq, ts=event.get("ts"), actor=event.get("actor")))


def open_interruptions(snapshot: Any) -> List[Dict[str, Any]]:
    """A later real success of the same command on current code closes the interruption gap."""
    state = snapshot.state
    opened = []
    for interruption in state.interrupted_runs:
        original = interruption["original"]
        task_id, kind = original.get("task"), original.get("kind")
        task = state.tasks.get(task_id)
        if task is not None and not task.active:
            continue
        matching = []
        for receipt in state.receipts.values():
            if (receipt.get("seq", 0) <= interruption["seq"] or receipt.get("task") != task_id
                    or list(receipt.get("cmd") or []) != list(original.get("cmd") or [])
                    or ("name" in original and receipt.get("name") != original["name"])
                    or receipt.get("manual") or receipt.get("invalid") or receipt.get("late")
                    or receipt.get("id") in state.retired or receipt.get("code_digest") != snapshot.code_digest):
                continue
            if task_id and receipt.get("graph_digest") != (state.plan.get("graph") or {}).get("sha256"):
                continue
            actual_kind = receipt.get("kind") if receipt.get("type") == "run" else receipt.get("type")
            if kind == "tdd.red" and actual_kind == "tdd.green" and receipt.get("outcome") == "green_ok":
                # Red runs on the failing source. Its paired Green, necessarily on changed
                # source, is the current-code proof that this recovered test now passes.
                red = state.receipts.get(receipt.get("red")) or {}
                if (red.get("seq", 0) > interruption["seq"] and red.get("task") == task_id
                        and red.get("type") == "tdd.red" and red.get("outcome") == "red_verified"
                        and list(red.get("cmd") or []) == list(original.get("cmd") or [])
                        and not red.get("manual") and not red.get("invalid") and not red.get("late")
                        and red.get("id") not in state.retired and red.get("graph_digest") == receipt.get("graph_digest")):
                    matching.append(receipt)
                continue
            if actual_kind != kind:
                continue
            passed = (receipt.get("outcome") == "red_verified" if kind == "tdd.red" else
                      receipt.get("outcome") == "green_ok" if kind == "tdd.green" else receipt.get("passed") is True)
            if passed:
                matching.append(receipt)
        if not matching:
            opened.append(interruption)
    return opened


def cmd_recover_run(ctx: Any) -> int:
    from . import control
    from .context import out

    control.require_operator("gt recover-run")
    state = ctx.active_goal_required()
    reason = (ctx.args.reason or "").strip()
    if not reason or not ctx.args.confirm_stopped:
        raise GTError("必须提供原因，并以 --confirm-stopped 确认命令及其后代进程均已停止。", code=EXIT.blocked)
    started = ctx.args.started
    original = copy.deepcopy(state.running.get(started))
    if original is None:
        raise GTError("seq %s 不是当前未结算命令；不能重复结算。" % started, code=EXIT.conflict)
    goal_id = state.goal["id"]

    def expect(current):
        ctx.expect_same_goal(goal_id)(current)
        if current.goal.get("status") != "active" or current.running.get(started) != original:
            raise GTError("命令已结算或目标已关闭；本次未记录。", code=EXIT.conflict)
        pid = original.get("pid")
        if type(pid) is not int or pid_alive(pid) is not False:
            raise GTError("命令进程仍存活或状态未知；请停止进程后再显式结算。", code=EXIT.blocked)

    expect(state)
    data = {"started": started, "original": original, "goal": goal_id, "reason": reason,
            "confirmed_stopped": True, "pid_observation": "not_alive", "assurance": "operator_cli",
            "passed": False}
    ctx.append("run.interrupted", data, expect=expect)
    out(ctx, "seq %s 已记为中断；旧通过记录不能覆盖此缺口，须在当前代码上重新运行同一命令。" % started, data)
    return EXIT.ok
