"""External operations: an intent is persisted before anything runs, results are confirmed by readback.

State machine (INV06, AC24/AC25):

    prepared -> dispatched -> executed  -> confirmed
                           -> unknown   -> (reconcile) confirmed | failed
                           -> failed    -> (retry only when the intent is retry_safe)

``gt operation prepare`` records what is about to be done (action, exact target, expectation,
idempotency, readback command) under an authorization grant. ``dispatch`` re-checks the grant,
records the dispatch, runs the command, records the result: exit 0 is *executed* (not yet
confirmed), anything else is *unknown* — a failed push may still have pushed. ``confirm`` and
``reconcile`` run the readback: exit 0 means the target is there as expected (confirmed), exit 1
means it is not (failed, clean), anything else keeps *unknown*. Nothing is ever re-run blindly.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import runner
from .context import Ctx, out
from .state import State
from .util import EXIT, GTError, today

IDEMPOTENCY = ("once", "retry_safe")
TERMINAL = ("confirmed",)
RETRYABLE = ("failed",)


def _grant_for(ctx: Ctx, state: State, action: str) -> Dict[str, Any]:
    from . import gitinfo
    from .util import web_url
    grant = state.auth_covers(action)
    if grant is None:
        raise GTError("未授权：%s 没有 gt auth grant 记录。先向用户一次性说明仓库、动作、范围和停止条件。" % action,
                      code=EXIT.blocked)
    if grant.get("expires") and grant["expires"] < today():
        raise GTError("授权已过期（%s）：%s 需要重新确认。" % (grant["expires"], action), code=EXIT.blocked)
    origin = next((r["url"] for r in gitinfo.remotes(ctx.project.work_tree) if r["name"] == "origin"), None)
    granted = grant.get("repo")
    if granted and origin and (web_url(granted) or granted) != (web_url(origin) or origin):
        raise GTError("授权绑定仓库 %s，当前 origin 是 %s；仓库变了，请重新确认。" % (granted, origin), code=EXIT.blocked)
    return grant


def _op(state: State, op_id: str) -> Dict[str, Any]:
    op = state.operations.get(op_id)
    if op is None:
        raise GTError("没有外部操作 %s。" % op_id, hint="gt operation list 查看；gt operation prepare 登记新的意图。")
    return op


def cmd_prepare(ctx: Ctx) -> int:
    args = ctx.args
    state = ctx.active_goal_required()
    if args.idempotent not in IDEMPOTENCY:
        raise GTError("--idempotent 只能是 once 或 retry_safe。")
    if not args.target or len(args.target.strip()) < 3:
        raise GTError("缺少 --target：写出精确目标（仓库、tag、Release、环境），不是类别。")
    grant = _grant_for(ctx, state, args.action)
    readback = shlex.split(args.readback) if args.readback else None
    if args.required and not readback:
        raise GTError("--required 的操作必须登记 --readback：没有回读命令就无法确认它真的完成。")
    holder: Dict[str, Any] = {}

    def prepare(seq: int, prev: str) -> Tuple[Dict[str, Any], Any]:
        data = {"id": "OP%d" % seq, "action": args.action, "target": args.target.strip(), "expect": args.expect,
                "idempotency": args.idempotent, "readback": readback, "required": bool(args.required),
                "grant_seq": grant.get("seq"), "goal": ctx.goal_id(), "note": args.note}
        holder.update(data)
        return data, lambda: None

    ctx.append("operation.prepared", None, prepare, expect=ctx.expect_same_goal(ctx.goal_id()))
    out(ctx, "已登记外部操作 %s：%s → %s（%s%s）。执行：gt operation dispatch %s -- <命令>" % (
        holder["id"], args.action, holder["target"], args.idempotent, "，必需" if args.required else "",
        holder["id"]), holder)
    return EXIT.ok


def _run_logged(ctx: Ctx, argv: List[str], timeout: Optional[float], label: str) -> Tuple[Dict[str, Any], Path]:
    pending = runner.tmp_log(ctx.project.evidence_dir)
    result = runner.execute(argv, Path.cwd().resolve(), pending, timeout)
    final = ctx.project.evidence_dir / ("%s.log" % label)
    number = 1
    while final.exists():
        final = ctx.project.evidence_dir / ("%s.%d.log" % (label, number))
        number += 1
    os.replace(pending, final)
    return result, final


def cmd_dispatch(ctx: Ctx) -> int:
    args = ctx.args
    state = ctx.active_goal_required()
    op = _op(state, args.operation)
    if op["state"] == "prepared":
        pass
    elif op["state"] in RETRYABLE and op.get("idempotency") == "retry_safe":
        pass
    elif op["state"] in RETRYABLE:
        raise GTError("%s 上次失败，但意图是 once（不可安全重试）：先 gt operation reconcile 回读，确认未执行后用新的意图重做。" % op["id"],
                      code=EXIT.blocked)
    else:
        raise GTError("%s 当前是 %s，不能再次执行：结果不明时先 gt operation reconcile %s -- <回读命令>。" % (
            op["id"], op["state"], op["id"]), code=EXIT.blocked)
    if not args.cmd:
        raise GTError("缺少要执行的命令。", hint="gt operation dispatch %s -- <命令>" % op["id"])
    _grant_for(ctx, state, op["action"])  # the grant may have expired or the repo changed since prepare
    seen_state = op["state"]
    goal_id = ctx.goal_id()

    def expect(current: State) -> None:
        """Under the lock: only one dispatch wins; a concurrent one sees the state moved and stops."""
        ctx.expect_same_goal(goal_id)(current)
        now = current.operations.get(op["id"]) or {}
        if now.get("state") != seen_state:
            raise GTError("%s 在此期间已变成 %s：另一个进程已经执行或改变了它，本次不执行。" % (op["id"], now.get("state")),
                          code=EXIT.conflict)

    ctx.append("operation.dispatched", {"id": op["id"], "cmd": list(args.cmd), "pid": os.getpid()}, expect=expect)
    result, log = _run_logged(ctx, args.cmd, args.timeout, "%s-dispatch" % op["id"])
    verdict = "executed" if result["exit_code"] == 0 else "unknown"
    data = {"id": op["id"], "state": verdict, "exit_code": result["exit_code"], "timed_out": result["timed_out"],
            "log": ".goal-teams/evidence/%s" % log.name, "log_sha256": result["log_sha256"],
            "summary": result["summary"]}
    ctx.append("operation.result", data, expect=ctx.expect_same_goal(ctx.goal_id()))
    text = {"executed": "命令已执行（exit 0）；目标状态要靠回读确认：gt operation confirm %s" % op["id"],
            "unknown": "命令退出码 %d：副作用可能已发生也可能没有，结果 unknown；回读后再决定：gt operation reconcile %s -- <回读命令>" % (
                result["exit_code"], op["id"])}[verdict]
    runner.print_tail(result, "%s · %s · 日志 %s" % (op["id"], text, data["log"]))
    return EXIT.ok if verdict == "executed" else EXIT.unverified


def _readback(ctx: Ctx, op: Dict[str, Any], argv: List[str], timeout: Optional[float], event: str) -> int:
    result, log = _run_logged(ctx, argv, timeout, "%s-readback" % op["id"])
    if result["exit_code"] == 0:
        verdict = "confirmed"
    elif result["exit_code"] == 1:
        verdict = "failed"
    else:
        verdict = "unknown"
    data = {"id": op["id"], "verdict": verdict, "cmd": list(argv), "exit_code": result["exit_code"],
            "timed_out": result["timed_out"], "log": ".goal-teams/evidence/%s" % log.name,
            "log_sha256": result["log_sha256"], "summary": result["summary"]}
    ctx.append(event, data, expect=ctx.expect_same_goal(ctx.goal_id()))
    text = {"confirmed": "回读确认目标与预期一致（confirmed）",
            "failed": "回读显示目标不存在（failed）：%s" % ("可按原意图重试" if op.get("idempotency") == "retry_safe"
                                                         else "意图是 once，重做要登记新的意图"),
            "unknown": "回读本身失败（exit %d），结果仍是 unknown；不要重放，先弄清远端状态" % result["exit_code"]}[verdict]
    runner.print_tail(result, "%s · %s · 日志 %s" % (op["id"], text, data["log"]))
    return EXIT.ok if verdict == "confirmed" else EXIT.unverified


def cmd_confirm(ctx: Ctx) -> int:
    args = ctx.args
    state = ctx.active_goal_required()
    op = _op(state, args.operation)
    if op["state"] == "confirmed":
        out(ctx, "%s 已经 confirmed。" % op["id"], op)
        return EXIT.ok
    if op["state"] not in ("executed", "unknown", "dispatched"):
        raise GTError("%s 当前是 %s：还没有执行，无从确认。" % (op["id"], op["state"]))
    return _readback(ctx, op, _readback_argv(op, args.cmd), args.timeout, "operation.confirmed")


def cmd_reconcile(ctx: Ctx) -> int:
    """After a crash or an unclear result: read the remote back; never re-run the operation itself."""
    args = ctx.args
    state = ctx.active_goal_required()
    op = _op(state, args.operation)
    if op["state"] == "confirmed":
        out(ctx, "%s 已经 confirmed，无需对账。" % op["id"], op)
        return EXIT.ok
    if op["state"] == "prepared":
        raise GTError("%s 还没有 dispatch，没有可对账的副作用。" % op["id"])
    return _readback(ctx, op, _readback_argv(op, args.cmd), args.timeout, "operation.reconciled")


def _readback_argv(op: Dict[str, Any], given: List[str]) -> List[str]:
    """The registered readback is the only one that can confirm a registered intent; an ad-hoc one is
    allowed only for intents registered without a readback (and never for required ones)."""
    registered = list(op.get("readback") or [])
    if registered:
        if given and list(given) != registered:
            raise GTError("%s 登记的回读命令是 %s；不能用别的命令确认。" % (op["id"], " ".join(registered)), code=EXIT.usage)
        return registered
    if op.get("required"):
        raise GTError("%s 是必需操作但没有登记回读命令，无法确认。" % op["id"], code=EXIT.blocked)
    if not given:
        raise GTError("缺少回读命令：prepare 时没有 --readback，请在 -- 之后给出。")
    return list(given)


def cmd_list(ctx: Ctx) -> int:
    state = ctx.goal_required()
    rows = ["| ID | 动作 | 目标 | 状态 | 幂等 | 必需 |", "|---|---|---|---|---|---|"]
    for op in state.operations.values():
        rows.append("| %s | %s | %s | %s | %s | %s |" % (op["id"], op.get("action"), op.get("target"), op["state"],
                                                        op.get("idempotency"), "是" if op.get("required") else ""))
    out(ctx, "\n".join(rows) if state.operations else "没有登记的外部操作。", list(state.operations.values()))
    return EXIT.ok


def pending_readbacks(state: State) -> List[Dict[str, Any]]:
    """Operations whose outcome is not settled and that carry a readback command (for gt resume --readback)."""
    return [op for op in state.operations.values()
            if op["state"] in ("dispatched", "executed", "unknown") and op.get("readback")]


def reconcile_pending(ctx: Ctx, timeout: Optional[float]) -> List[str]:
    lines: List[str] = []
    for op in pending_readbacks(ctx.state(refresh=True)):
        code = _readback(ctx, op, list(op["readback"]), timeout, "operation.reconciled")
        state = ctx.state(refresh=True).operations[op["id"]]["state"]
        lines.append("%s %s：%s → %s" % ("✔" if code == EXIT.ok else "✘", op["id"], op.get("target"), state))
    return lines


def completion_reasons(state: State) -> Tuple[List[str], List[str]]:
    """``(reasons, notes)`` about external operations for the completion contract."""
    reasons: List[str] = []
    notes: List[str] = []
    for op in state.operations.values():
        if op["state"] == "confirmed":
            continue
        text = "外部操作 %s（%s → %s）%s" % (op["id"], op.get("action"), op.get("target"), {
            "prepared": "已登记未执行", "dispatched": "已派发、结果未记录（可能中断）：先 gt operation reconcile",
            "executed": "已执行、未回读确认：gt operation confirm", "unknown": "结果不明：gt operation reconcile，不要重放",
            "failed": "回读显示未执行"}.get(op["state"], op["state"]))
        (reasons if op.get("required") else notes).append(text)
    return reasons, notes
