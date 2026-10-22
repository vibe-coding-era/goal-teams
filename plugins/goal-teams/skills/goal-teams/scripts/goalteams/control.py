"""Control plane (cooperative mode): budgets, allowed tools and proposals, kept apart from project config.

Three things are kept distinct (INV10): what the ledger *records*, what counts as a *trusted decision*
(the operator at the CLI, or an approval they recorded), and what is *enforced* (nothing in cooperative
mode — a sub-session that unsets ``GT_SUBSESSION`` is not stopped by this file; the capability report
says so). A model sub-session can only *propose* changes to scope, budget, authorization or criteria
(``gt propose``); the operator approves or rejects them (``gt control approve|reject``), and only the
operator sets the control snapshot (``gt control set``).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from .context import Ctx, out
from .state import State
from .util import EXIT, GTError

SUBSESSION_ENV = "GT_SUBSESSION"
PROPOSAL_KINDS = ("scope", "budget", "auth", "criteria", "plan")
# Initial defaults (plan decision D12): parameters to be measured, not proven optima.
DEFAULT_BUDGET: Dict[str, Any] = {"rounds": 3, "minutes": 30, "round_minutes": 10, "check_minutes": 2, "grace_seconds": 5}


def in_subsession() -> bool:
    return bool(os.environ.get(SUBSESSION_ENV))


def require_operator(what: str) -> None:
    """Refuse control-plane writes from a supervised sub-session (AC17). Cooperative: this is a
    convention the supervisor sets up, not an OS boundary."""
    if in_subsession():
        raise GTError("%s 只能由操作者（启动监督器的会话）执行；子会话请用 gt propose 提交提案。" % what, code=EXIT.blocked)


def budget_of(state: State) -> Dict[str, Any]:
    budget = dict(DEFAULT_BUDGET)
    budget.update((state.control or {}).get("budget") or {})
    return budget


def cmd_control_set(ctx: Ctx) -> int:
    args = ctx.args
    require_operator("gt control set")
    state = ctx.active_goal_required()
    budget = budget_of(state)
    changes: Dict[str, Any] = {}
    for key, flag in (("rounds", "rounds"), ("minutes", "minutes"), ("round_minutes", "round_minutes"),
                      ("check_minutes", "check_minutes"), ("grace_seconds", "grace_seconds")):
        value = getattr(args, flag)
        if value is not None:
            if value <= 0:
                raise GTError("--%s 必须大于 0。" % flag.replace("_", "-"))
            changes[key] = value
    data: Dict[str, Any] = {"budget": dict(budget, **changes)}
    if args.allow_tool is not None:
        data["tools"] = list(args.allow_tool)
    if args.note:
        data["note"] = args.note
    if not changes and args.allow_tool is None:
        raise GTError("没有要设置的项。", hint="gt control set --rounds 3 --minutes 30 --round-minutes 10 --check-minutes 2")
    data["source"] = "operator_cli"
    ctx.append("control.set", data, expect=ctx.expect_same_goal(ctx.goal_id()))
    out(ctx, "控制面已更新：预算 %s%s（来源：操作者命令行；cooperative 模式不保证子会话无法绕过）" % (
        ", ".join("%s=%s" % kv for kv in data["budget"].items()),
        "；允许工具 %s" % ", ".join(data["tools"]) if "tools" in data else ""), data)
    return EXIT.ok


def cmd_control_show(ctx: Ctx) -> int:
    state = ctx.goal_required()
    control = dict(state.control or {})
    control["budget"] = budget_of(state)
    control["proposals"] = list(state.proposals.values())
    control["lease"] = state.lease
    lines = ["预算：%s" % ", ".join("%s=%s" % kv for kv in control["budget"].items()),
             "允许工具：%s" % (", ".join(control.get("tools") or []) or "（未限定）"),
             "租约：%s" % ("epoch %s，pid %s，%s" % (state.lease.get("epoch"), state.lease.get("pid"), state.lease.get("status"))
                       if state.lease else "无")]
    for item in control["proposals"]:
        lines.append("提案 %s（%s，%s）：%s" % (item["id"], item.get("kind"), item.get("state"), item.get("text")))
    out(ctx, "\n".join(lines), control)
    return EXIT.ok


def cmd_propose(ctx: Ctx) -> int:
    """Anyone, sub-sessions included, may propose; nothing changes until the operator approves."""
    args = ctx.args
    ctx.active_goal_required()
    if args.kind not in PROPOSAL_KINDS:
        raise GTError("--kind 只能是 %s。" % "|".join(PROPOSAL_KINDS))
    if not args.text or len(args.text.strip()) < 4:
        raise GTError("缺少提案内容（--text）。")
    holder: Dict[str, Any] = {}

    def prepare(seq: int, prev: str) -> Tuple[Dict[str, Any], Any]:
        data = {"id": "P%d" % seq, "kind": args.kind, "text": args.text.strip(), "by": ctx.actor,
                "subsession": in_subsession(), "goal": ctx.goal_id()}
        holder.update(data)
        return data, lambda: None

    ctx.append("control.proposal", None, prepare, expect=ctx.expect_same_goal(ctx.goal_id()))
    out(ctx, "已记录提案 %s（%s）：%s\n它不会自动生效；操作者 gt control approve %s 后，再用对应命令修改。" % (
        holder["id"], args.kind, holder["text"], holder["id"]), holder)
    return EXIT.ok


def _decide(ctx: Ctx, verdict: str) -> int:
    require_operator("gt control %s" % verdict)
    state = ctx.active_goal_required()
    proposal = state.proposals.get(ctx.args.proposal)
    if proposal is None:
        raise GTError("没有提案 %s。" % ctx.args.proposal)
    if proposal.get("state") != "open":
        raise GTError("提案 %s 已经 %s。" % (proposal["id"], proposal.get("state")))
    data = {"id": proposal["id"], "verdict": verdict, "note": ctx.args.note, "by": ctx.actor}
    ctx.append("control.decision", data, expect=ctx.expect_same_goal(ctx.goal_id()))
    follow = {"scope": "gt task edit <T> --add-scope ... 或 gt scope allow ...", "budget": "gt control set ...",
              "auth": "向用户确认后 gt auth grant ...", "criteria": "gt goal --edit-done / --add-done ...",
              "plan": "gt plan apply ..."}[proposal["kind"]]
    out(ctx, "提案 %s 已%s。%s" % (proposal["id"], "批准" if verdict == "approved" else "拒绝",
                                ("生效还需要操作者执行：%s" % follow) if verdict == "approved" else ""), data)
    return EXIT.ok


def cmd_control_approve(ctx: Ctx) -> int:
    return _decide(ctx, "approved")


def cmd_control_reject(ctx: Ctx) -> int:
    return _decide(ctx, "rejected")


def guard_subsession_write(what: str) -> None:
    """Called by the commands a sub-session must not run directly (auth grant, criteria edits, config)."""
    require_operator(what)
