"""The one completion contract: a pure judge over a Snapshot (INV08).

``evaluate(snapshot, gates, capabilities, now)`` runs no command, reads no file and writes nothing.
``gt check``, ``gt finish``, ``gt report``, ``gt loop decide stop`` and ``gt goal accept`` all show
its result. Missing, failed, stale, blocked and invalid evidence are reported as such; nothing is
ever converted into ``passed`` (INV01), and a gate the policy does not require is ``not_required``
with its reason instead of disappearing.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import policy, graph_contract, run_recovery
from .models import ASSURANCE, RED_VERIFIED, CompletionResult, GateRule, Snapshot, Task
from .util import sha256_text

# Who may sign the completion audit (the user's relayed verdict is self_reported, and says so).
AUDITORS = ("goal_completion_auditor", "user")
AXIS_KINDS = ("runtime", "business", "release", "install")


def review_assurance(review: Dict[str, Any]) -> str:
    """The assurance a recorded review carries (legacy receipts without the field are inferred)."""
    level = review.get("assurance")
    if level in ASSURANCE:
        return level
    if review.get("self"):
        return "self"
    return "self_reported" if str(review.get("by") or "").lower() == "user" else "correlated_reviewer"


def latest_goal_reviews(state: Any) -> "OrderedDict[str, Dict[str, Any]]":
    """The latest @goal verdict of each reviewer (a later verdict replaces an earlier one)."""
    latest: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for review in state.goal_reviews:
        latest.pop(review.get("by"), None)
        latest[review.get("by")] = review
    return latest


def item_digest(text: str) -> str:
    return sha256_text(text or "")


def criterion_status(snapshot: Snapshot, criterion: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    """``(status, detail, assurance)`` of one done criterion on this snapshot."""
    state = snapshot.state
    cid, text = criterion["id"], criterion.get("text") or ""
    if criterion.get("check"):
        # only a command run of exactly this criterion's --check, made for this criterion text, counts
        runs = [r for r in state.criterion_runs(cid) if not r.get("manual")
                and list(r.get("cmd") or []) == list(criterion["check"])
                and r.get("criterion_digest") == item_digest(text)]
        if not runs:
            return "not_run", "%s：还没有运行 --check 命令（gt finish 会运行）" % cid, None
        last = runs[-1]
        if not last.get("passed"):
            return "failed", "%s：--check 命令未通过（%s）" % (cid, last["id"]), "command"
        if last.get("code_digest") != snapshot.code_digest:
            return "stale", "%s：--check 通过记录（%s）不是在当前代码上做的" % (cid, last["id"]), "command"
        return "passed", "%s：--check 通过（%s）" % (cid, last["id"]), "command"
    accepted = state.latest_acceptance(cid)
    if accepted is None:
        return "not_run", "%s：缺少验收（gt goal accept --item %s --result pass --quote \"<用户原话>\"）" % (cid, cid), None
    binds = accepted.get("binds") or {}
    level = accepted.get("assurance") or "self_reported"
    if accepted.get("result") != "pass":
        return "failed", "%s：验收未通过：%s" % (cid, accepted.get("quote") or ""), level
    if binds.get("item_digest") and binds["item_digest"] != item_digest(text):
        return "stale", "%s 的验收已过期：完成标准文本已修改，需重新验收" % cid, level
    if binds.get("source_digest") and binds["source_digest"] != snapshot.source_digest:
        return "stale", "%s 的验收已过期：验收后源码有变化，需重新验收" % cid, level
    return "passed", "%s：人工验收通过（assurance=%s）" % (cid, level), level


def _task_review(task: Task, gate: GateRule) -> Tuple[str, Optional[str], Optional[str]]:
    """``(status, reason, assurance)`` of the review requirement of one task."""
    passing = task.reviews[-1] if task.reviews and task.reviews[-1].get("verdict") == "pass" else None
    level = review_assurance(passing) if passing else None
    needs_review = bool(task.validator) or (gate.min_assurance or "self") != "self"
    if not needs_review:
        return ("not_required", None, level or "self")
    if passing is None:
        who = task.validator or "另一成员"
        return ("not_run", "%s 缺少评审（gt review %s --by %s --verdict pass）" % (task.id, task.id, who), None)
    if task.stale:
        return ("stale", "%s 的评审已过期：评审后范围内文件或任务规格（验收、验证人、依赖、范围）有变化，需重新评审" % task.id, level)
    if not policy.assurance_at_least(level, gate.min_assurance):
        return ("failed", "%s 的评审保证等级是 %s，低于要求的 %s（%s）" % (task.id, level, gate.min_assurance, gate.reason), level)
    return ("passed", None, level)


def _requires_tdd(snapshot: Snapshot, task: Task, gates: Dict[str, GateRule]) -> bool:
    """Behavior tasks cannot opt out by omitting --tdd; aggregate parents use their children."""
    if not gates["tdd"].required:
        return False
    facts = snapshot.tasks.get(task.id)
    return task.tdd or (task.kind == "code" and (facts is None or facts.needs_own_evidence))


def _task_reasons(snapshot: Snapshot, task: Task, gates: Dict[str, GateRule]) -> Tuple[List[str], Dict[str, Any]]:
    state = snapshot.state
    facts = snapshot.tasks.get(task.id)
    reasons: List[str] = []
    info: Dict[str, Any] = {"review": None}
    if task.state == "blocked":
        return ["%s 阻塞：%s%s" % (task.id, task.reason or "", "（外部）" if task.external else "")], info
    if task.state not in ("done", "accepted"):
        reasons.append("%s 未完成（%s）" % (task.id, task.state))
    status, reason, level = _task_review(task, gates["review"])
    info["review"] = {"status": status, "assurance": level}
    if reason:
        reasons.append(reason)
    last = state.latest_green(task.id)
    if last is not None and last.get("outcome") != "green_ok":
        reasons.append("%s 最近一次 Green（%s）没有通过：%s" % (task.id, last["id"], last.get("outcome")))
    if _requires_tdd(snapshot, task, gates):
        green = state.latest(task.id, "tdd.green", "green_ok")
        red = state.open_red(task.id)
        if green is None:
            reasons.append("%s 缺少有效的 Red→Green 证据" % task.id)
        elif red is not None:
            reasons.append("%s 在 Green 之后又有成立的 Red（%s），需要再次 Green" % (task.id, red["id"]))
        elif facts is not None and facts.green_test_changed:
            reasons.append("%s 的测试文件在 Green 之后被修改：新的行为要重新 Red→Green；"
                           "只是给已实现的行为补用例，就写进新的测试文件并用 affected 记录" % task.id)
        else:
            paired = state.receipts.get(green.get("red") or "")
            if paired is not None and paired.get("outcome") != RED_VERIFIED:
                reasons.append("%s 的 Red（%s）仍是 %s：失败原因未核对，不算有效 TDD（gt tdd confirm %s --expect \"<失败特征>\"）" % (
                    task.id, paired["id"], paired.get("outcome"), paired["id"]))
    if gates["affected"].required and task.kind == "code" and task.state in ("done", "accepted") \
            and facts is not None and facts.needs_own_evidence and facts.fresh_pass is None:
        reasons.append("%s 没有在最终代码上通过的测试记录（Green 或 affected）：之后代码又变了，或从未记录。"
                       "运行 gt rerun 在当前代码上重跑" % task.id)
    return reasons, info


def _axes(snapshot: Snapshot) -> Dict[str, str]:
    state = snapshot.state
    out: Dict[str, str] = {}
    for kind in AXIS_KINDS:
        runs = [r for r in state.receipts.values() if r.get("type") == "run" and r.get("kind") == kind
                and not r.get("invalid") and r.get("id") not in state.retired]
        if not runs:
            out[kind] = "not_run"
        elif not runs[-1].get("passed"):
            out[kind] = "failed"
        else:
            out[kind] = "passed" if runs[-1].get("source_digest") == snapshot.source_digest else "stale"
    return out


def _runs(snapshot: Snapshot, kind: str, digest_field: str = "source_digest") -> List[Dict[str, Any]]:
    state = snapshot.state
    current = snapshot.source_digest if digest_field == "source_digest" else snapshot.code_digest
    return [r for r in state.receipts.values() if r.get("type") == "run" and r.get("kind") == kind
            and r.get("passed") and r.get(digest_field) == current and r.get("id") not in state.retired]


def evaluate(snapshot: Snapshot, gates: Optional[Dict[str, GateRule]] = None,
             capabilities: Optional[Dict[str, Any]] = None, now: Optional[str] = None,
             release: bool = False, published: bool = False) -> CompletionResult:
    """Judge one snapshot. ``release`` adds the pre-publish gates even when the goal's phase is
    development; ``published`` also needs a passing readback on the current source."""
    goal = snapshot.goal
    state = snapshot.state
    if goal is None or state is None or state.goal is None:
        return CompletionResult("no_goal", False, False, False, reasons=["没有目标（gt goal）"])
    gates = gates or policy.gates_of(goal, snapshot.config)
    capabilities = capabilities or {}
    reasons: List[str] = []
    passes: List[str] = []
    notes: List[str] = []
    gate_status: Dict[str, str] = OrderedDict()
    assurance: Dict[str, Any] = {"reviews": {}, "audit": None, "acceptance": []}
    if snapshot.worktree_note:
        notes.append(snapshot.worktree_note)

    # --- structure: ledger integrity, unknown events, plan -------------------------------------
    problems = snapshot.verify_problems
    (reasons if problems else passes).append("账本完整性：%s" % ("%d 处问题（gt verify）" % len(problems) if problems else "通过"))
    if state.unknown_events:
        reasons.append("账本含 %d 条本版本不认识的事件类型（%s）：不能据此判定完成，请用写入它们的 gt 版本或升级" % (
            len(state.unknown_events), ", ".join(sorted({e["type"] for e in state.unknown_events})[:5])))
    gate_status["integrity"] = "failed" if problems or state.unknown_events else "passed"
    graph_problems = graph_contract.completion_problems(state)
    graph_invalid = graph_contract.structural_problems(state)
    reasons.extend(graph_problems)
    gate_status["task_graph"] = "failed" if graph_problems else "passed"
    interrupted = run_recovery.open_interruptions(snapshot)
    recovery_errors = state.recovery_errors
    reasons.extend(recovery_errors)
    reasons.extend("中断命令 seq %s 尚未在当前代码上以同一命令成功重跑（%s/%s）。" % (
        item["started"], item["original"].get("task") or "@goal", item["original"].get("kind")) for item in interrupted)
    gate_status["interrupted_runs"] = "failed" if interrupted or recovery_errors else "passed"
    for reset in state.head_resets:
        notes.append("账本链头在 seq %s 被重置（%s）：%s；重置前的问题：%s" % (
            reset.get("seq"), reset.get("actor"), reset.get("reason"), "；".join(reset.get("problems") or []) or "无"))
    if state.running:
        reasons.append("有 %d 条命令已开始但没有回执（可能被中断，或仍在运行）：%s；当前检查结束前不能关闭目标" % (
            len(state.running), "；".join("seq %d %s %s" % (seq, r.get("kind"), " ".join(r.get("cmd") or [])[:60])
                                         for seq, r in list(state.running.items())[:5])))
    tasks = state.active_tasks()
    if not tasks:
        reasons.append("没有登记任务")
    plan_gate = gates["plan"]
    if plan_gate.required:
        from .planning import plan_problems
        errors, _ = plan_problems(state)
        errors = [e for e in errors if e != "没有任务"]
        if errors:
            reasons.extend("计划问题：%s" % e for e in errors)
            gate_status["plan"] = "failed"
        elif tasks:
            passes.append("计划 r%d：%d 个任务，依赖与验收标准完整%s" % (
                state.plan["revision"], len(tasks),
                "" if state.plan.get("frozen") else "（手工改动 %d 处后未整体 apply）" % len(state.plan.get("changes_since_apply") or [])))
            gate_status["plan"] = "passed"
        else:
            gate_status["plan"] = "not_run"
    else:
        gate_status["plan"] = "not_required"

    # --- tasks: completion, review, TDD, fresh evidence ------------------------------------------
    review_levels: List[str] = []
    tdd_tasks = tdd_failed = affected_failed = 0
    for task in tasks:
        task_reasons, info = _task_reasons(snapshot, task, gates)
        reasons.extend(task_reasons)
        if info.get("review"):
            assurance["reviews"][task.id] = info["review"]
            if info["review"]["assurance"]:
                review_levels.append(info["review"]["assurance"])
        if _requires_tdd(snapshot, task, gates):
            tdd_tasks += 1
            tdd_failed += any("Red" in r or "Green" in r for r in task_reasons)
        affected_failed += any("没有在最终代码上通过" in r for r in task_reasons)
    if not gates["tdd"].required:
        gate_status["tdd"] = "not_required"
    elif not tdd_tasks:
        gate_status["tdd"] = "not_run"
        if any(t.kind == "code" for t in tasks):
            reasons.append("行为变更要求 Red→Green：给代码任务加 --tdd 并 gt tdd red/green；不是行为变更就如实设置影响"
                           "（gt goal --impact config_change|docs_only|presentation_only）")
    else:
        gate_status["tdd"] = "failed" if tdd_failed else "passed"
    if not gates["affected"].required:
        gate_status["affected"] = "not_required"
    elif affected_failed:
        gate_status["affected"] = "failed"
    else:
        finished_code = [t for t in tasks if t.kind == "code" and t.state in ("done", "accepted")]
        gate_status["affected"] = "passed" if finished_code else "not_run"
    review_states = [v["status"] for v in assurance["reviews"].values() if v]
    if any(s in ("not_run", "stale", "failed") for s in review_states):
        gate_status["review"] = "failed" if "failed" in review_states else ("stale" if "stale" in review_states else "not_run")
    elif review_states and any(s == "passed" for s in review_states):
        gate_status["review"] = "passed"
    else:
        gate_status["review"] = "not_required"
    self_reviewed = [t.id for t in tasks if t.reviews and t.reviews[-1].get("self") and t.reviews[-1].get("verdict") == "pass"]
    if self_reviewed:
        notes.append("自评通过（同一 Agent 复核自己的产出，不是独立验证）：%s。要求独立评审：gt config set "
                     "require_independent_review true" % ", ".join(self_reviewed))
    for receipt in state.open_failures():
        reasons.append("检查未通过：%s（%s/%s，任务 %s）" % (receipt["id"], receipt.get("kind"),
                                                       receipt.get("name") or "-", receipt.get("task") or "-"))
    for failed, passed in state.flaky():
        notes.append("不稳定通过：%s 失败后同一命令在同一份代码上于 %s 通过（GT-TEST-FLAKY，汇报里要写明）" % (
            failed["id"], passed["id"]))
    for rid, item in state.retired.items():
        notes.append("已撤销的检查失败：%s（%s）：%s" % (rid, item.get("actor"), item.get("reason")))
    if snapshot.generated:
        notes.append("声明为命令输出、不计入源码的文件：%s（代码或测试读取的文件不能这样声明）" % ", ".join(snapshot.generated[:10]))
    for receipt in state.receipts.values():
        if receipt.get("invalid"):
            notes.append("%s 没有运行起来（exit %s），不算检查结果" % (receipt["id"], receipt.get("exit_code")))

    # --- scope -----------------------------------------------------------------------------------
    diff = snapshot.diff or {}
    if diff.get("available"):
        if diff.get("hidden"):
            reasons.append("有 %d 个文件被设为 assume-unchanged/skip-worktree，gt 看不到它们的改动：%s" % (
                len(diff["hidden"]), ", ".join(diff["hidden"][:8])))
        if diff.get("out_of_scope"):
            reasons.append("越界改动 %d 个文件：%s" % (len(diff["out_of_scope"]), ", ".join(diff["out_of_scope"][:8])))
            gate_status["scope"] = "failed"
        elif diff.get("scoped"):
            passes.append("改动都在锁定范围内（%d 个文件）" % diff["files"])
            gate_status["scope"] = "passed"
        elif gates["scope"].required:
            reasons.append("没有锁定范围（gt task add/edit --scope ...）")
            gate_status["scope"] = "not_run"
        else:
            notes.append("范围：没有锁定范围，越界只能靠你自己核对 gt diff")
            gate_status["scope"] = "not_required"
    else:
        notes.append("范围检查：not_run（不是 git 仓库，gt diff 不可用）")
        gate_status["scope"] = "not_run"

    # --- goal-level reviews: audit, security -----------------------------------------------------
    latest = latest_goal_reviews(state)
    for by, review in latest.items():
        if review.get("verdict") == "fail":
            reasons.append("目标评审未通过：%s：%s" % (by, review.get("note") or ""))

    def fresh_goal_pass(names: Iterable[str], min_assurance: Optional[str]) -> List[Dict[str, Any]]:
        return [r for by, r in latest.items() if by in names and r.get("verdict") == "pass"
                and policy.assurance_at_least(review_assurance(r), min_assurance)
                and (r.get("binds") or {}).get("source_digest") == snapshot.source_digest]

    audit = gates["audit"]
    if audit.required:
        signed = [r for by, r in latest.items() if by in AUDITORS and r.get("verdict") == "pass"
                  and policy.assurance_at_least(review_assurance(r), audit.min_assurance)]
        fresh = fresh_goal_pass(AUDITORS, audit.min_assurance)
        if not signed:
            reasons.append("缺少完成审计：gt review @goal --by goal_completion_auditor ...（单 Agent 宿主可请用户审计：--by user，记为 self_reported）")
            gate_status["audit"] = "not_run"
        elif not fresh:
            reasons.append("完成审计已过期：审计后源码有变化，需要重新审计")
            gate_status["audit"] = "stale"
        else:
            levels = sorted({review_assurance(r) for r in fresh}, key=ASSURANCE.index)
            assurance["audit"] = levels[-1]
            passes.append("完成审计：通过（%s；assurance=%s）" % (", ".join(r["by"] for r in fresh), levels[-1]))
            gate_status["audit"] = "passed"
            if levels[-1] == "self_reported":
                notes.append("完成审计由会话转述用户结论（self_reported），未经宿主或外部系统确认")
    else:
        gate_status["audit"] = "not_required"

    current_code = snapshot.code_digest
    if gates["e2e"].required:
        e2e = [r for r in state.receipts.values() if r.get("type") == "run" and r.get("kind") == "e2e"
               and r.get("passed") and r.get("code_digest") == current_code and r.get("id") not in state.retired
               and (not r.get("manual") or r.get("evidence"))]
        (passes if e2e else reasons).append("E2E：%s" % (
            "通过（与当前源码一致）" if e2e else
            "缺少与当前源码一致的通过记录（UI 目标需要 gt run <T> --kind e2e；人工走查用 --manual --evidence）"))
        gate_status["e2e"] = "passed" if e2e else "not_run"
    else:
        gate_status["e2e"] = "not_required"
    if gates["visual"].required:
        visual = [r for r in state.receipts.values() if r.get("type") == "run" and r.get("kind") == "e2e"
                  and r.get("passed") and r.get("code_digest") == current_code and r.get("id") not in state.retired
                  and (not r.get("manual") or r.get("evidence"))]
        (passes if visual else reasons).append("视觉/结构核对：%s" % (
            "通过（与当前源码一致）" if visual else "缺少与当前源码一致的核对记录（gt run <T> --kind e2e --manual --evidence <截图或链接>）"))
        gate_status["visual"] = "passed" if visual else "not_run"
    else:
        gate_status["visual"] = "not_required"
    if gates["agent_eval"].required:
        evals = [r for r in state.receipts.values() if r.get("type") == "run" and r.get("kind") == "eval"
                 and r.get("passed") and not r.get("manual") and r.get("code_digest") == current_code
                 and r.get("id") not in state.retired]
        names = {r.get("name") for r in evals}
        ok = "baseline" in names and "agent" in names
        (passes if ok else reasons).append("Agent 评测：%s" % (
            "通过（基线与有 Agent 两组记录与当前源码一致）" if ok else
            "缺少与当前源码一致的两组评测记录（gt run <T> --kind eval --name baseline / --name agent）"))
        gate_status["agent_eval"] = "passed" if ok else "not_run"
    else:
        gate_status["agent_eval"] = "not_required"

    release_now = release or published or gates["regression"].required
    release_reasons: List[str] = []
    if gates["security"].required or release_now:
        security = [r for r in _runs(snapshot, "security") if not r.get("manual")] + \
            fresh_goal_pass(("goal_security",), "correlated_reviewer")
        target = passes if security else (reasons if gates["security"].kind == "quality" else release_reasons)
        target.append("安全评审：%s" % (
            "通过（与当前源码一致）" if security else
            "缺少与当前源码一致的记录（goal_security 的 gt review @goal，或 gt run - --kind security -- <扫描命令>）"))
        gate_status["security"] = "passed" if security else "not_run"
    else:
        gate_status["security"] = "not_required"

    # --- criteria --------------------------------------------------------------------------------
    criteria_rows: List[Dict[str, Any]] = []
    criteria = goal.get("criteria") or []
    criteria_ok = True
    for criterion in criteria:
        status, detail, level = criterion_status(snapshot, criterion)
        criteria_rows.append({"id": criterion["id"], "text": criterion.get("text"), "status": status, "detail": detail,
                              "assurance": level, "check": criterion.get("check")})
        if status != "passed":
            criteria_ok = False
        if level and level not in ("command",):
            assurance["acceptance"].append(level)
    gate_status["criteria"] = "passed" if criteria else ("not_run" if gates["criteria"].required else "not_required")
    if not criteria:
        gate_status["acceptance"] = "not_required"
        if gates["criteria"].required:
            reasons.append("没有完成标准（gt goal --add-done \"<可观察的完成标准>\"）")
            criteria_ok = False
        else:
            notes.append("没有声明完成标准：以工程门为准（要逐项验收请 gt goal --add-done）")
    else:
        gate_status["acceptance"] = "passed" if criteria_ok else (
            "failed" if any(r["status"] == "failed" for r in criteria_rows) else
            "stale" if any(r["status"] == "stale" for r in criteria_rows) else "not_run")
        if "self_reported" in assurance["acceptance"]:
            notes.append("人工验收记录由会话写入（assurance=self_reported），未经用户系统确认")
    criteria_reasons = [r["detail"] for r in criteria_rows if r["status"] != "passed"]
    criteria_passes = [r["detail"] for r in criteria_rows if r["status"] == "passed"]
    passes.extend(criteria_passes)

    from .operations import completion_reasons
    op_reasons, op_notes = completion_reasons(state)
    notes.extend(op_notes)
    gate_status["operations"] = "not_required" if not state.operations else ("failed" if op_reasons else "passed")
    engineering_reasons = list(reasons)
    engineering_ok = not engineering_reasons
    reasons.extend(op_reasons)
    if release_now:
        _release_gates(snapshot, published, release_reasons, passes, notes, gate_status)
    else:
        for name in ("regression", "build", "readback"):
            gate_status[name] = "not_required"
    reasons.extend(release_reasons)
    reasons.extend(criteria_reasons)

    result_axes = {"engineering": "passed" if engineering_ok else "failed"}
    result_axes.update(_axes(snapshot))
    review_blocking = [r for r in engineering_reasons if "评审" in r or "审计" in r]
    other_blocking = [r for r in reasons if r not in review_blocking and r not in criteria_reasons]
    achieved = not reasons
    if achieved:
        status = "achieved"
    elif (any(t.state == "blocked" for t in tasks) or problems or state.unknown_events or state.running
          or graph_invalid or interrupted or recovery_errors):
        status = "blocked"
    elif other_blocking:
        status = "unverified"
    elif review_blocking:
        status = "review_required"
    else:
        status = "acceptance_required"
    if review_levels:
        assurance["review_min"] = sorted(review_levels, key=ASSURANCE.index)[0]
    return CompletionResult(status, engineering_ok, criteria_ok, achieved, reasons, passes, notes, result_axes,
                            dict(gate_status), criteria_rows, assurance, snapshot.ref(), diff, snapshot.source_digest)


def _release_gates(snapshot: Snapshot, published: bool, reasons: List[str], passes: List[str],
                   notes: List[str], gate_status: Dict[str, str]) -> None:
    state = snapshot.state
    regression = [r for r in _runs(snapshot, "regression") if not r.get("manual")]
    (passes if regression else reasons).append("全量回归：%s" % (
        "通过（与当前源码一致）" if regression else "缺少与当前源码一致、由命令产生的通过记录"))
    gate_status["regression"] = "passed" if regression else "not_run"
    build = [r for r in _runs(snapshot, "build") if not r.get("manual") and r.get("artifacts")]
    if build and snapshot.build_drift:
        reasons.append("构建产物已变化或缺失：%s（不能沿用 %s 的构建记录，需重新构建）" % (
            ", ".join(snapshot.build_drift[:6]), build[-1]["id"]))
        build = []
        gate_status["build"] = "stale"
    else:
        gate_status["build"] = "passed" if build else "not_run"
    (passes if build else reasons).append("构建产物：%s" % (
        "通过（%s）" % ", ".join(a["path"] for a in build[-1]["artifacts"]) if build else
        "缺少与当前源码一致、产物仍在的构建记录（gt run - --kind build --artifact <产物> -- <构建命令>）"))
    assets = asset_set_digest(build[-1]) if build else None
    readback = [r for r in _runs(snapshot, "release") if (not r.get("manual") or r.get("evidence"))
                and (assets is None or r.get("assets_digest") == assets)]
    if published:
        (passes if readback else reasons).append("发布回读：%s" % (
            "通过" if readback else "缺少与当前源码一致的通过记录（发布后 gt run - --kind release -- <回读命令>）"))
        gate_status["readback"] = "passed" if readback else "not_run"
    else:
        gate_status["readback"] = "passed" if readback else "not_run"
        if not readback:
            notes.append("发布回读：not_run（发布后用 gt run - --kind release -- <回读命令> 记录；回读通过才说已发布）")
    del state  # the judge only reads


def asset_set_digest(receipt: Dict[str, Any]) -> str:
    """Identity of a build's exact asset set (paths and content), bound by the readback."""
    items = sorted("%s:%s:%s" % (a.get("path"), a.get("size"), a.get("sha256")) for a in receipt.get("artifacts") or [])
    return sha256_text("\n".join(items))
