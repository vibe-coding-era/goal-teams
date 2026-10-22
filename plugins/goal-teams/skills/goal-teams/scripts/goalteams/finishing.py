"""Finishing a goal: the shared judgement, gt check, gt finish, gt report, gt resume, gt loop decide.

All of them read checks.judge (completion.evaluate); none defines its own notion of success (INV08).
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional

from . import checks, operations, render
from .context import Ctx, _set_state, out
from .evidence import repair_evidence
from .state import State
from .util import EXIT, GTError, pretty_json, read_stdin_text, sha256_text


def _release_phase(state: State) -> bool:
    return bool((state.goal.get("phase") == "release") or (state.goal.get("flags") or {}).get("release"))


def _judge(ctx: Ctx, state: State, release: bool = False, pre_publish: bool = False):
    """The shared judgement. A release-phase goal always carries its release gates; ``pre_publish``
    (gt check --release) asks "ready to publish?", so the readback is not yet required."""
    if pre_publish:
        return checks.judge(ctx.project, state, release=True, published=False)
    return checks.judge(ctx.project, state, release=release)


def cmd_loop_decide(ctx: Ctx) -> int:
    args = ctx.args
    state = ctx.active_goal_required()
    data: Dict[str, Any] = {"decision": args.decision, "next": args.next, "reason": args.reason}
    notes: List[str] = []
    if args.decision == "stop":
        result = _judge(ctx, state)
        if args.outcome == "achieved" and not result.ok:
            raise GTError("不能记为达成：\n- " + "\n- ".join(result.reasons), code=EXIT.unverified,
                          hint="如实使用 --outcome stopped|blocked|user_stopped，或先补齐证据（gt finish）。")
        outcome = args.outcome or ("achieved" if result.ok else "stopped")
        data["outcome"] = outcome
        data["open_reasons"] = result.reasons[:20]
        data["snapshot_ref"] = result.snapshot_ref
        notes.append("目标结束：%s" % outcome)
        if result.reasons:
            notes.append("未闭合：%s" % "；".join(result.reasons[:5]))
    else:
        current = state.evidence_in_round(state.round)
        previous = state.evidence_in_round(state.round - 1) if state.round > 1 else None
        if current == 0 and previous == 0:
            notes.append("⚠ 连续两轮没有新证据：建议 replan 或 stop（并 gt reflect 记录原因）")
        if state.round + 1 > state.estimate:
            notes.append("预计轮次将上调到 %d" % (state.round + 1))
    goal_id = ctx.goal_id()

    def expect(current: State) -> None:
        ctx.expect_same_goal(goal_id)(current)
        if data.get("outcome") == "achieved":
            if current.goal.get("status") != "active":
                raise GTError("目标在此期间已被结束。", code=EXIT.conflict)
            fresh = _judge(ctx, current)
            if not fresh.ok or fresh.snapshot_ref != data["snapshot_ref"]:
                raise GTError("判定期间源码或账本有变化（%s → %s），本次未记录；请重新运行 gt loop decide。" % (
                    data["snapshot_ref"], fresh.snapshot_ref), code=EXIT.conflict)

    ctx.append("loop.decide", data, expect=expect)
    notes.append("下一步：gt report，把输出作为回复的依据")
    out(ctx, "第 %d 轮决策：%s。\n%s" % (state.round, args.decision, "\n".join(notes)), data)
    return EXIT.ok


def _read_text_arg(value: Optional[str]) -> Optional[str]:
    if value == "-":
        return read_stdin_text().strip()
    return value


def _report_warnings(ctx: Ctx, state: State) -> List[str]:
    warnings: List[str] = []
    t = render.tr(ctx.lang)
    problems = ctx.project.verify()
    if problems:
        warnings.append(t["w_chain"].format(n=len(problems)))
    stale = [task.id for task in state.active_tasks() if task.stale]
    if stale:
        warnings.append(t["w_stale"].format(ids=", ".join(stale)))
    for failed, passed in state.flaky():
        warnings.append(t["w_flaky"].format(a=failed["id"], b=passed["id"]))
    self_reviewed = [task.id for task in state.active_tasks()
                     if task.reviews and task.reviews[-1].get("self") and task.reviews[-1].get("verdict") == "pass"]
    if self_reviewed:
        warnings.append(t["w_self"].format(ids=", ".join(self_reviewed)))
    warnings.extend(ctx.project.log_warnings(list(state.receipts.values())))
    for rid, item in state.retired.items():
        warnings.append(t["w_retired"].format(id=rid, reason=item.get("reason")))
    for reset in state.head_resets:
        warnings.append(t["w_reset"].format(seq=reset.get("seq"), reason=reset.get("reason")))
    declared = sorted(checks.Live(ctx.project, state).areas.generated)
    if declared:
        warnings.append(t["w_declared"].format(paths=", ".join(declared[:10])))
    return warnings


def cmd_report(ctx: Ctx) -> int:
    args = ctx.args
    ctx.project.require()
    state = ctx.goal_required()
    warnings = _report_warnings(ctx, state)
    result = _judge(ctx, state)
    broken = None
    last = state.last_decision()
    finished = (state.goal.get("finished") or {}).get("outcome") == "achieved"
    if state.goal.get("status") == "stopped" and ((last and last.get("outcome") == "achieved") or finished) and not result.ok:
        broken = result.reasons[0]
    summary = _read_text_arg(args.summary)
    fmt = args.format or ctx.config.get("report_format") or "brief"
    if fmt == "six":
        body, warns, meta = render.report(state, ctx.config, ctx.lang, ctx.web(), summary, args.task, args.members,
                                          args.next, warnings, oos=ctx.oos(), broken=broken)
    else:
        body, warns, meta = render.brief_report(state, ctx.config, ctx.lang, result, summary, args.next, warnings,
                                                broken=broken)
    meta.update({"status": result.status, "snapshot_ref": result.snapshot_ref, "format": fmt})
    ctx.append("report", {"round": meta["round"], "decision": meta.get("decision"), "sha256": sha256_text(body),
                          "lang": ctx.lang, "warnings": len(warns), "format": fmt, "status": result.status,
                          "snapshot_ref": result.snapshot_ref})
    if ctx.json:
        print(pretty_json({"body": body, "warnings": warns, "meta": meta, "completion": result.as_dict()}))
    else:
        print(body)
    for warning in warns:
        print("gt: %s" % warning, file=sys.stderr)
    return EXIT.ok


STATUS_TEXT = {"achieved": "达成 ✔", "review_required": "待评审", "acceptance_required": "待验收",
               "blocked": "阻塞", "unverified": "未闭合 ✘", "no_goal": "没有目标"}


def _completion_lines(result, heading: str) -> List[str]:
    axes_text = {"passed": "通过", "failed": "未通过", "not_run": "未运行", "stale": "已过期", "not_required": "不适用"}
    lines = ["%s：%s（%s）" % (heading, STATUS_TEXT.get(result.status, result.status), result.snapshot_ref)]
    lines.extend("✔ %s" % p for p in result.passes)
    lines.extend("✘ %s" % r for r in result.reasons)
    lines.extend("⚠ %s" % n for n in result.notes)
    lines.append("门禁：" + " · ".join("%s=%s" % (k, axes_text.get(v, v)) for k, v in result.gates.items()))
    lines.append("完成轴：" + " · ".join("%s=%s" % (k, axes_text.get(v, v)) for k, v in result.axes.items()))
    return lines


def cmd_check(ctx: Ctx) -> int:
    state = ctx.goal_required()
    if ctx.args.release:
        # pre-publish readiness: every gate except the readback; never reported as the goal being achieved
        result = _judge(ctx, state, pre_publish=True)
        lines = _completion_lines(result, "发布前检查")
        lines[0] = "发布前检查：%s（%s）" % ("就绪：可以执行发布，回读通过后目标才算达成" if result.ok else "未就绪 ✘",
                                       result.snapshot_ref)
        payload = {k: v for k, v in result.as_dict().items() if k != "diff"}
        payload.update(status="ready" if result.ok else result.status, ok=result.ok, goal_achieved=False)
        out(ctx, "\n".join(lines), payload)
        return EXIT.ok if result.ok else EXIT.unverified
    result = _judge(ctx, state)
    payload = {k: v for k, v in result.as_dict().items() if k != "diff"}
    out(ctx, "\n".join(_completion_lines(result, "完成检查")), payload)
    return EXIT.ok if result.ok else EXIT.unverified


def _direct_auto_done(ctx: Ctx) -> List[str]:
    """direct mode has no hand-off, so finish marks a task done itself when the task's own evidence
    (a passing Green/affected on the current code) is there. tracked goals keep the explicit step."""
    state = ctx.state(refresh=True)
    if (state.goal or {}).get("mode") != "direct":
        return []
    lines: List[str] = []
    live = checks.Live(ctx.project, state)
    for task in state.active_tasks():
        if task.state != "in_progress" or task.validator:
            continue
        if task.kind == "code" and checks.fresh_pass(live, state, task) is None:
            continue
        if task.tdd and state.open_red(task.id) is not None:
            continue
        _set_state(ctx, task, "done", note="gt finish：当前代码上有通过记录，自动标记完成（direct）")
        lines.append("%s 自动标记完成（direct：当前代码上有通过记录）" % task.id)
    return lines


def finish_goal(ctx: Ctx, release: bool = False, timeout: Optional[float] = None, no_rerun: bool = False,
                close_guard: Optional[Callable[[State], None]] = None):
    """The finish path shared by gt finish and the supervisor: top up evidence that is safe to repeat,
    judge with the shared contract, record goal.finished under the lock when achieved.
    Returns ``(result, repaired_lines, recorded)``."""
    state = ctx.state(refresh=True)
    if close_guard is not None:
        close_guard(state)
    result = _judge(ctx, state, release=release)
    repaired = repair_evidence(ctx, state, result, timeout) if not no_rerun else []
    repaired += _direct_auto_done(ctx)
    if repaired:
        state = ctx.state(refresh=True)
        result = _judge(ctx, state, release=release)
    recorded = False
    if result.ok:
        goal_id = ctx.goal_id()
        source = result.snapshot_ref

        def expect(current: State) -> None:
            ctx.expect_same_goal(goal_id)(current)
            if close_guard is not None:
                close_guard(current)
            if current.goal.get("status") != "active":
                raise GTError("目标在此期间已被结束。", code=EXIT.conflict)
            fresh = checks.judge(ctx.project, current, release=release)
            if not fresh.ok or fresh.snapshot_ref != source:
                raise GTError("判定期间源码或账本有变化（%s → %s），本次未记录；请重新运行 gt finish。" % (
                    source, fresh.snapshot_ref), code=EXIT.conflict)

        ctx.append("goal.finished", {"outcome": "achieved", "snapshot_ref": result.snapshot_ref, "gates": result.gates,
                                     "assurance": result.assurance, "criteria": [
                                         {k: r[k] for k in ("id", "status", "assurance")} for r in result.criteria]},
                   expect=expect)
        recorded = True
    return result, repaired, recorded


def cmd_finish(ctx: Ctx) -> int:
    """Close the goal: top up missing or stale evidence that is safe to repeat, judge once more with
    the shared contract, record the outcome. Idempotent; never runs reviews, builds or external writes."""
    state = ctx.goal_required()
    if state.goal.get("status") != "active":
        result = _judge(ctx, state, release=ctx.args.release)
        out(ctx, "\n".join(_completion_lines(result, "目标已结束（%s）" % state.goal.get("outcome"))),
            {k: v for k, v in result.as_dict().items() if k != "diff"})
        return EXIT.ok if result.ok else EXIT.unverified
    result, repaired, _ = finish_goal(ctx, ctx.args.release, ctx.args.timeout, ctx.args.no_rerun)
    lines = ["重跑：%s" % r for r in repaired]
    lines.extend(_completion_lines(result, "收尾"))
    if not result.ok:
        lines.append("gt finish 可重复运行；补齐上面的项后再来一次。" if result.status != "review_required"
                     else "等待评审：gt review <任务> --by <验证人> --verdict pass，然后再 gt finish。")
    payload = {k: v for k, v in result.as_dict().items() if k != "diff"}
    payload["repaired"] = repaired
    out(ctx, "\n".join(lines), payload)
    return EXIT.ok if result.ok else EXIT.unverified


def cmd_resume(ctx: Ctx) -> int:
    """A continuation pack from the ledger (six sections). Read-only, except ``--readback``, which runs
    the stored readback of every unsettled external operation and records the verdicts first."""
    state = ctx.goal_required()
    lines: List[str] = []
    if ctx.args.readback and state.goal.get("status") == "active":
        lines = operations.reconcile_pending(ctx, ctx.args.timeout)
        state = ctx.state(refresh=True)
    result = _judge(ctx, state)
    pack = render.resume(state, ctx.project, result, ctx.args.max_bytes)
    if lines:
        pack["readback"] = lines
        pack["text"] = "## 回读\n" + "\n".join("- %s" % line for line in lines) + "\n\n" + pack["text"]
    out(ctx, pack["text"], pack)
    return EXIT.ok
