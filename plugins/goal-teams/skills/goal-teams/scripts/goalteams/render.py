"""Markdown projections: TaskList.md, benchmark.md, dashboard, report, packet."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from .state import State, Task
from .util import GTError, md_cell, shorten

STATE_PREFIX = ".goal-teams"

TEXT: Dict[str, Dict[str, str]] = {
    "zh": {
        "sep": "：",
        "task": "任务", "members": "成员", "progress": "进度", "result": "结果",
        "benchmark": "Benchmark", "next_loop": "下一轮 LOOP", "next_task": "下一个任务",
        "lead": "Goal Lead",
        "board": "◆ Goal-Teams 任务执行看板",
        "board_counts": "已完成任务 {a}/{b}{subs}｜[完整任务]({tasklist})｜{plan}",
        "board_subs": "｜已完成子任务 {c}/{d}",
        "plan_frozen": "计划 r{rev}（已冻结）", "plan_draft": "计划 r{rev}（未冻结）", "plan_none": "计划未冻结",
        "board_head": "| 优先级 | 任务 / 子任务 | Subagent 成员 | 进度 |",
        "all_done": "本轮全部完成；当前无进行中或剩余任务。",
        "no_tasks": "尚未登记任务（gt task add）。",
        "parallel": "（并行）",
        "st_pending": "待开始", "st_ready": "就绪", "st_in_progress": "进行中", "st_done": "待评审",
        "st_done_plain": "已完成（未评审）", "st_blocked": "阻塞：{reason}", "st_blocked_ext": "外部阻塞：{reason}",
        "st_accepted": "已验收", "st_cancelled": "已取消", "st_stale": "评审已过期（需重新评审）",
        "parent_progress": "{state}｜子任务 {done}/{total}",
        "context": "◆ Context / Knowledge / Tools",
        "context_head": "| 核心规则 | 项目知识 | 代码库 | MCP/CLI/API |",
        "loop": "◆ LOOP：第 {n} 轮 / 预计 {m} 轮",
        "p": "P ｜ 计划 / 下一轮目标", "d": "D ｜ 执行 / 本轮执行", "c": "C ｜ 检查 / 执行结果", "a": "A ｜ 改进 / 调整行动",
        "d_text": "开始 {s}｜完成 {d}｜验收 {a}｜新证据 {e}",
        "c_text": "新增 Evidence {e}｜缺口 {g}｜阻塞 {b}｜[benchmark.md]({bm})",
        "a_text": "决策 `{decision}`{reason}｜[loop-review.md]({lr})",
        "p_remaining": "完成剩余任务：{items}",
        "p_none": "无剩余任务",
        "decision_pending": "待决策",
        "progress_text": "第 {n} 轮/共 {m} 轮｜任务 {a}/{b}{subs}",
        "progress_subs": "｜子任务 {c}/{d}",
        "bench_text": "TDD 红绿 {pairs} 对{waiting}｜检查 通过 {p}·失败 {f}｜评审 通过 {rp}·驳回 {rf}｜越界文件 {oos}｜阻塞 {b}｜[benchmark.md]({bm})",
        "bench_waiting": "（{n} 个待 Green）",
        "bench_self": "（自评 {n}）",
        "improve": "LOOP 改进建议：",
        "improve_none": "暂无新增建议（本目标未记录反思）。",
        "summary_missing": "（本轮摘要未提供：gt report --summary \"...\"）",
        "next_missing": "（未填写下一步：gt report --next \"...\" 或 gt loop decide ... --next）",
        "warn": "⚠ gt：",
        "w_no_decision": "本轮尚未记录决策（gt loop decide continue|replan|stop）",
        "w_no_summary": "缺少本轮摘要",
        "w_no_next": "缺少下一步说明",
        "w_no_tasks": "还没有登记任务",
        "w_chain": "账本完整性检查失败：{n} 处（gt verify）",
        "w_stale": "评审已过期（文件在评审后变化）：{ids}",
        "w_plan": "计划未冻结（gt plan freeze）",
        "w_estimate": "预计轮次已自动上调到 {m}",
        "w_flaky": "不稳定通过：{a} 失败后同一命令在 {b} 通过",
        "w_self": "自评通过（单 Agent 模式，独立性较弱）：{ids}",
        "w_retired": "已撤销检查失败 {id}：{reason}",
        "w_reset": "账本链头在 seq {seq} 被重置：{reason}",
        "w_declared": "声明为命令输出、不计入源码的文件：{paths}",
        "outcome_achieved": "目标达成（gt check 通过）",
        "outcome_broken": "目标结束时达成；之后有变化，gt check 现在未通过：{reason}",
        "outcome_retired": "（其中撤销过检查失败 {ids}，见下方说明）",
        "outcome_stopped": "已停止（未全部达成）",
        "outcome_blocked": "因阻塞停止",
        "outcome_user": "按用户要求停止",
    },
    "en": {
        "sep": ": ",
        "task": "Task", "members": "Members", "progress": "Progress", "result": "Result",
        "benchmark": "Benchmark", "next_loop": "Next LOOP", "next_task": "Next task",
        "lead": "Goal Lead",
        "board": "◆ Goal-Teams task board",
        "board_counts": "tasks done {a}/{b}{subs} | [full TaskList]({tasklist}) | {plan}",
        "board_subs": " | subtasks done {c}/{d}",
        "plan_frozen": "plan r{rev} (frozen)", "plan_draft": "plan r{rev} (draft)", "plan_none": "plan not frozen",
        "board_head": "| Priority | Task / subtask | Subagent member | Progress |",
        "all_done": "All registered tasks are complete; nothing is in progress or remaining.",
        "no_tasks": "No tasks registered yet (gt task add).",
        "parallel": " (parallel)",
        "st_pending": "pending", "st_ready": "ready", "st_in_progress": "in progress", "st_done": "awaiting review",
        "st_done_plain": "done (not reviewed)", "st_blocked": "blocked: {reason}", "st_blocked_ext": "external blocker: {reason}",
        "st_accepted": "accepted", "st_cancelled": "cancelled", "st_stale": "review stale (review again)",
        "parent_progress": "{state} | subtasks {done}/{total}",
        "context": "◆ Context / Knowledge / Tools",
        "context_head": "| Core rules | Project knowledge | Codebase | MCP/CLI/API |",
        "loop": "◆ LOOP: round {n} / est. {m}",
        "p": "P | Plan / next goal", "d": "D | Do / this round", "c": "C | Check / results", "a": "A | Act / adjustments",
        "d_text": "started {s} | done {d} | accepted {a} | new evidence {e}",
        "c_text": "new evidence {e} | gaps {g} | blocked {b} | [benchmark.md]({bm})",
        "a_text": "decision `{decision}`{reason} | [loop-review.md]({lr})",
        "p_remaining": "finish remaining: {items}",
        "p_none": "nothing remaining",
        "decision_pending": "pending",
        "progress_text": "round {n}/{m} | tasks {a}/{b}{subs}",
        "progress_subs": " | subtasks {c}/{d}",
        "bench_text": "TDD red/green pairs {pairs}{waiting} | checks passed {p}·failed {f} | reviews passed {rp}·rejected {rf} | out-of-scope files {oos} | blocked {b} | [benchmark.md]({bm})",
        "bench_waiting": " ({n} waiting for Green)",
        "bench_self": " ({n} self)",
        "improve": "LOOP improvement suggestions:",
        "improve_none": "No new suggestions (no reflection recorded for this goal).",
        "summary_missing": "(no summary for this round: gt report --summary \"...\")",
        "next_missing": "(next step missing: gt report --next \"...\" or gt loop decide ... --next)",
        "warn": "⚠ gt: ",
        "w_no_decision": "no decision recorded for this round (gt loop decide continue|replan|stop)",
        "w_no_summary": "summary missing",
        "w_no_next": "next step missing",
        "w_no_tasks": "no tasks registered",
        "w_chain": "ledger integrity check failed in {n} place(s) (gt verify)",
        "w_stale": "review is stale (files changed after review): {ids}",
        "w_plan": "plan is not frozen (gt plan freeze)",
        "w_estimate": "round estimate was raised to {m}",
        "w_flaky": "unstable pass: {a} failed, then the same command passed in {b}",
        "w_self": "self-reviewed (single-agent mode, weaker independence): {ids}",
        "w_retired": "failed check {id} was withdrawn: {reason}",
        "w_reset": "the ledger head was reset at seq {seq}: {reason}",
        "w_declared": "files declared as command output and left out of the source: {paths}",
        "outcome_achieved": "goal achieved (gt check passed)",
        "outcome_broken": "achieved when the goal ended; things changed since and gt check now fails: {reason}",
        "outcome_retired": " (failed checks {ids} were withdrawn, see below)",
        "outcome_stopped": "stopped (not fully achieved)",
        "outcome_blocked": "stopped because blocked",
        "outcome_user": "stopped at the user's request",
    },
}


def tr(lang: str) -> Dict[str, str]:
    return TEXT.get(lang, TEXT["zh"])


def link(label: str, target: str) -> str:
    return "[%s](%s)" % (label.replace("]", ")").replace("[", "("), target.replace(" ", "%20"))


# ---------------------------------------------------------------- task labels
def state_label(state: State, task: Task, t: Dict[str, str]) -> str:
    if task.stale:
        return t["st_stale"]
    if task.state == "blocked":
        key = "st_blocked_ext" if task.external else "st_blocked"
        return t[key].format(reason=shorten(task.reason or "?", 40))
    if task.state == "pending" and state.is_ready(task):
        return t["st_ready"]
    if task.state == "done" and not task.validator:
        return t["st_done_plain"]
    return t.get("st_" + task.state, task.state)


def remaining_rows(state: State) -> List[Tuple[Task, bool]]:
    """``[(task, is_subtask)]`` for parents not fully complete and their open subtasks."""
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    parents = sorted(state.parents(), key=lambda t: (order.get(t.priority, 9), t.created_seq))
    rows: List[Tuple[Task, bool]] = []
    for parent in parents:
        if state.fully_complete(parent):
            continue
        rows.append((parent, False))
        for child in state.children(parent.id):
            if not child.complete:
                rows.append((child, True))
    return rows


def board(state: State, t: Dict[str, str]) -> str:
    counts = state.counts()
    plan = state.plan
    if plan.get("frozen"):
        plan_text = t["plan_frozen"].format(rev=plan["revision"])
    elif plan.get("revision"):
        plan_text = t["plan_draft"].format(rev=plan["revision"])
    else:
        plan_text = t["plan_none"]
    subs = t["board_subs"].format(c=counts["subtasks_done"], d=counts["subtasks_total"]) \
        if counts["subtasks_total"] else ""
    head = "**%s**%s%s" % (t["board"], t["sep"], t["board_counts"].format(
        a=counts["tasks_done"], b=counts["tasks_total"], subs=subs,
        tasklist=STATE_PREFIX + "/TaskList.md", plan=plan_text))
    if not state.active_tasks():
        return head + "\n\n" + t["no_tasks"]
    rows = remaining_rows(state)
    if not rows and not state.blocked():
        return head + "\n\n" + t["all_done"]
    parallel = state.parallel_ids()
    lines = [head, "", t["board_head"], "|---|---|---|---|"]
    for task, is_sub in rows:
        owner = task.owner or "lead"
        member = "`%s`%s" % (owner, t["parallel"] if task.id in parallel else "")
        if is_sub:
            name = "↳ %s" % md_cell(task.title)
            progress = state_label(state, task, t)
            priority = ""
        else:
            name = "**%s**" % md_cell(task.title)
            kids = state.children(task.id)
            label = state_label(state, task, t)
            progress = t["parent_progress"].format(state=label, done=sum(1 for k in kids if k.complete),
                                                   total=len(kids)) if kids else label
            priority = task.priority
        lines.append("| %s | %s | %s | %s |" % (priority, name, member, md_cell(progress)))
    return "\n".join(lines)


def _entry(item: Dict[str, Any]) -> str:
    label = md_cell(item.get("label", ""))
    target = item.get("link")
    return link(label, target) if target else "`%s`" % label


def context_table(state: State, config: Dict[str, Any], lang: str, web: Optional[str]) -> str:
    t = tr(lang)
    goal = state.goal or {}
    rules = ["SKILL.md"] + list((goal.get("route") or {}).get("rules", []))
    columns: List[List[str]] = [["`%s`" % r for r in rules], [link("memory.md", STATE_PREFIX + "/memory.md")], [], []]
    name = config.get("project") or "project"
    columns[2].append(link(name, web) if web else "`%s`" % md_cell(name))
    columns[3].append("CLI%s`gt`" % t["sep"])
    index = {"rule": 0, "knowledge": 1, "code": 2, "tool": 3}
    for item in state.context:
        column = index.get(item.get("kind"))
        if column is not None:
            columns[column].append(_entry(item))
    lines = ["**%s**" % t["context"], "", t["context_head"], "|---|---|---|---|",
             "| %s |" % " | ".join(" · ".join(c) for c in columns)]
    return "\n".join(lines)


def round_stats(state: State, round_number: int) -> Dict[str, int]:
    started = done = accepted = 0
    for event in state.round_events.get(round_number, []):
        data = event.get("data") or {}
        if event.get("type") == "task.state":
            if data.get("to") == "in_progress":
                started += 1
            elif data.get("to") == "done":
                done += 1
        elif event.get("type") == "review" and data.get("verdict") == "pass" and data.get("task") != "@goal":
            accepted += 1
    return {"started": started, "done": done, "accepted": accepted, "evidence": state.evidence_in_round(round_number)}


def gaps(state: State, oos: Optional[int]) -> int:
    failed = len(state.open_failures())
    rejected = sum(1 for task in state.active_tasks() if task.reviews and task.reviews[-1].get("verdict") == "fail"
                   and task.state != "accepted")
    return failed + rejected + (oos or 0)


def loop_view(state: State, lang: str, round_number: int, decision: Optional[Dict[str, Any]],
              oos: Optional[int] = None) -> str:
    t = tr(lang)
    stats = round_stats(state, round_number)
    if decision and decision.get("next"):
        plan_text = decision["next"]
    else:
        open_tasks = [task for task, _ in remaining_rows(state)][:3]
        plan_text = (t["p_remaining"].format(items=("、" if lang == "zh" else ", ").join(
            "%s %s" % (x.id, shorten(x.title, 24)) for x in open_tasks))
                     if open_tasks else t["p_none"])
    reason = ""
    if decision and decision.get("reason"):
        reason = ("｜" if lang == "zh" else " | ") + shorten(decision["reason"], 60)
    name = decision.get("decision") if decision else t["decision_pending"]
    lines = [
        "**%s**" % t["loop"].format(n=round_number, m=max(state.estimate, round_number)),
        "",
        "- **%s**%s%s" % (t["p"], t["sep"], md_cell(plan_text)),
        "- **%s**%s%s" % (t["d"], t["sep"], t["d_text"].format(s=stats["started"], d=stats["done"],
                                                              a=stats["accepted"], e=stats["evidence"])),
        "- **%s**%s%s" % (t["c"], t["sep"], t["c_text"].format(e=stats["evidence"], g=gaps(state, oos),
                                                              b=len(state.blocked()), bm=STATE_PREFIX + "/benchmark.md")),
        "- **%s**%s%s" % (t["a"], t["sep"], t["a_text"].format(decision=name, reason=reason,
                                                              lr=STATE_PREFIX + "/loop-review.md")),
    ]
    return "\n".join(lines)


def reported_round(state: State) -> Tuple[int, Optional[Dict[str, Any]]]:
    """The round a report describes and its decision (None = not decided yet)."""
    last = state.last_decision()
    if state.goal and state.goal.get("status") == "stopped":
        if last and last.get("decision") == "stop":
            return last["round"], last
        return state.round, None  # closed by gt finish: no round decision to quote
    quiet = {"report", "context.add", "reflect", "memory", "preflight", "config"}
    current_activity = [e for e in state.round_events.get(state.round, []) if e.get("type") not in quiet]
    if last and last["round"] == state.round - 1 and not current_activity:
        return last["round"], last
    return state.round, None


def dashboard(state: State, config: Dict[str, Any], lang: str, web: Optional[str],
              round_number: Optional[int] = None, decision: Optional[Dict[str, Any]] = None,
              oos: Optional[int] = None) -> str:
    t = tr(lang)
    if round_number is None:
        round_number, decision = reported_round(state)
    parts = [board(state, t), context_table(state, config, lang, web), loop_view(state, lang, round_number, decision, oos)]
    if state.running:
        parts.insert(1, "⚠ %s" % (("有 %d 条命令已开始但没有回执（可能被中断，或仍在运行）：%s" if lang == "zh" else
                                   "%d command(s) started without a receipt (interrupted, or still running): %s") % (
            len(state.running), "; ".join("seq %d %s" % (seq, r.get("kind")) for seq, r in list(state.running.items())[:5]))))
    return "\n\n".join(parts)


def tdd_pairs(state: State) -> Tuple[int, int]:
    """``(completed Red→Green pairs, tasks with a Red still waiting for Green)``."""
    ok = sum(1 for r in state.receipts.values() if r.get("type") == "tdd.green" and r.get("outcome") == "green_ok")
    waiting = 0
    for task in state.active_tasks():
        red = state.latest_red(task.id)
        green = state.latest(task.id, "tdd.green", "green_ok")
        if red and (green is None or green["seq"] < red["seq"]):
            waiting += 1
    return ok, waiting


def benchmark_line(state: State, t: Dict[str, str], oos: Optional[int] = None) -> str:
    pairs, waiting = tdd_pairs(state)
    runs = [r for r in state.receipts.values() if r.get("type") == "run"]
    passed = sum(1 for r in runs if r.get("passed"))
    failed = len(runs) - passed
    reviews = [rv for task in state.tasks.values() for rv in task.reviews] + state.goal_reviews
    rp = sum(1 for rv in reviews if rv.get("verdict") == "pass")
    own = sum(1 for rv in reviews if rv.get("verdict") == "pass" and rv.get("self"))
    rp_text = "%d%s" % (rp, t["bench_self"].format(n=own) if own else "")
    return t["bench_text"].format(pairs=pairs, waiting=t["bench_waiting"].format(n=waiting) if waiting else "",
                                  p=passed, f=failed, rp=rp_text, rf=len(reviews) - rp,
                                  oos="?" if oos is None else oos, b=len(state.blocked()),
                                  bm=STATE_PREFIX + "/benchmark.md")


def improvements(state: State, t: Dict[str, str]) -> str:
    actions: List[str] = []
    for item in reversed(state.reflections):
        for action in item.get("actions", []):
            if action not in actions:
                actions.append(action)
    if not actions:
        return "%s%s" % (t["improve"], t["improve_none"])
    return t["improve"] + "\n" + "\n".join("- %s" % a for a in actions[:3])


def report(state: State, config: Dict[str, Any], lang: str, web: Optional[str], summary: Optional[str],
           task_text: Optional[str], members_text: Optional[str], next_text: Optional[str],
           extra_warnings: List[str], oos: Optional[int] = None,
           broken: Optional[str] = None) -> Tuple[str, List[str], Dict[str, Any]]:
    t = tr(lang)
    sep = t["sep"]
    warnings = list(extra_warnings)
    round_number, decision = reported_round(state)
    if decision is None:
        warnings.append(t["w_no_decision"])
    if not summary:
        warnings.append(t["w_no_summary"])
    if not state.active_tasks():
        warnings.append(t["w_no_tasks"])
    if state.estimate_raised:
        warnings.append(t["w_estimate"].format(m=state.estimate))
    goal = state.goal or {}
    counts = state.counts()
    joiner = "、" if lang == "zh" else ", "
    members = members_text or joiner.join([t["lead"]] + state.members(round_number))
    subs = t["progress_subs"].format(c=counts["subtasks_done"], d=counts["subtasks_total"]) \
        if counts["subtasks_total"] else ""
    progress = t["progress_text"].format(n=round_number, m=max(state.estimate, round_number),
                                         a=counts["tasks_done"], b=counts["tasks_total"], subs=subs)
    stopped = bool(decision and decision.get("decision") == "stop")
    nxt = next_text or (decision or {}).get("next")
    if not nxt:
        warnings.append(t["w_no_next"])
        nxt = t["next_missing"]
    result_parts = [summary or t["summary_missing"],
                    dashboard(state, config, lang, web, round_number, decision, oos)]
    if stopped:
        outcome = (decision or {}).get("outcome") or "stopped"
        key = {"achieved": "outcome_achieved", "blocked": "outcome_blocked", "user_stopped": "outcome_user"}.get(
            outcome, "outcome_stopped")
        line = t["outcome_broken"].format(reason=broken) if key == "outcome_achieved" and broken else t[key]
        if key == "outcome_achieved" and state.retired:
            line += t["outcome_retired"].format(ids=", ".join(sorted(state.retired)))
        result_parts.append(line)
        result_parts.append(improvements(state, t))
    if warnings:
        result_parts.append("\n".join("> %s%s" % (t["warn"], w) for w in warnings))
    fields = [
        (t["task"], task_text or goal.get("title") or "?"),
        (t["members"], members),
        (t["progress"], progress),
        (t["result"], "\n\n".join(result_parts)),
        (t["benchmark"], benchmark_line(state, t, oos)),
        (t["next_task"] if stopped else t["next_loop"], nxt),
    ]
    body = "\n\n".join("%s%s%s" % (label, sep, value) for label, value in fields)
    meta = {"round": round_number, "decision": (decision or {}).get("decision"), "stopped": stopped}
    return body, warnings, meta


# ---------------------------------------------------------------- files
def _frontmatter(kind: str, title: str) -> str:
    return "---\ntype: %s\ntitle: %s\ngenerated_by: gt\n---\n" % (kind, md_cell(title))


def tasklist_md(state: State, config: Dict[str, Any]) -> str:
    goal = state.goal or {}
    t = TEXT["zh"]
    title = goal.get("title") or config.get("project") or "Goal Teams"
    out = [_frontmatter("Goal Teams TaskList", title), "# TaskList — %s\n" % md_cell(title)]
    if goal:
        status = goal.get("status")
        out.append("- 目标状态：%s%s" % ("进行中" if status == "active" else "已结束",
                                     "（%s）" % goal.get("outcome") if goal.get("outcome") else ""))
        plan = state.plan
        plan_text = ("r%d（已校验）" % plan["revision"]) if plan.get("frozen") else (
            "r%d（有未整体校验的改动）" % plan["revision"] if plan.get("revision") else "无计划")
        out.append("- 模式：%s · 风险：%s · 轮次：第 %d 轮 / 预计 %d 轮 · 计划：%s" % (
            goal.get("mode"), goal.get("risk"), state.round, max(state.estimate, state.round), plan_text))
        out.append("- 完成标准（Done Criteria）：")
        if plan.get("graph"):
            from . import graph_budget
            try:
                budget = graph_budget.status(state)
                out.append("- 冻结任务图：%d 个任务 · 总工作单元 %d · 加权关键路径 %d" %
                           (len(plan["graph"]["task_ids"]), plan["graph"]["total_budget_wu"], plan["graph"]["critical_path_wu"]))
                for task_id, row in budget["tasks"].items():
                    out.append("  - %s 剩余预算：%s" % (task_id, row["remaining"]))
            except (GTError, ValueError, RuntimeError) as exc:
                out.append("- 任务图预算不可用：%s" % exc)
        for item in goal.get("criteria", []):
            out.append("  %s. %s%s" % (item["id"], item["text"], "（--check）" if item.get("check") else ""))
        out.append("")
    out.append("## 任务\n")
    out.append("| ID | 任务 | 父任务 | 负责 | 验证 | 依赖 | 状态 | 验收标准 | 证据 | 评审 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for task in state.tasks.values():
        evidence = [r["id"] for r in state.receipts_of(task.id) if r.get("type") != "diff"]
        review = task.reviews[-1] if task.reviews else None
        review_text = "%s %s%s" % (review.get("by"), review.get("verdict"), "（自评）" if review.get("self") else "") \
            if review else ""
        out.append("| %s |" % " | ".join(md_cell(x) for x in [
            task.id, task.title, task.parent or "", task.owner or "", task.validator or "",
            ",".join(task.deps), state_label(state, task, t), task.accept or "",
            ", ".join(evidence[-6:]), review_text]))
    blocked = state.blocked()
    if blocked:
        out.append("\n## 阻塞\n")
        for task in blocked:
            out.append("- %s：%s%s → 影响后继：%s" % (task.id, task.reason or "", "（外部）" if task.external else "",
                                                 "、".join(state.descendants(task.id)) or "无"))
    layers, path, width, cycle = state.dag()
    if state.active_tasks():
        out.append("\n## 计划\n")
        out.append("- 分层（同层可并行）：%s" % " · ".join(
            "L%d: %s" % (i + 1, ", ".join(layer)) for i, layer in enumerate(layers)))
        out.append("- 关键路径：%s（%d）· 最大并行宽度：%d" % (" → ".join(path), len(path), width))
        if cycle:
            out.append("- ⚠ 依赖成环：%s" % ", ".join(cycle))
    return "\n".join(out).rstrip() + "\n"


def benchmark_md(state: State, config: Dict[str, Any], axes: Optional[Dict[str, str]] = None,
                 oos: Optional[int] = None) -> str:
    goal = state.goal or {}
    title = goal.get("title") or config.get("project") or "Goal Teams"
    t = TEXT["zh"]
    out = [_frontmatter("Goal Teams Benchmark", title), "# Benchmark — %s\n" % md_cell(title)]
    out.append("> " + benchmark_line(state, t, oos).replace("｜[benchmark.md](.goal-teams/benchmark.md)", ""))
    out.append("\n## 证据清单\n")
    out.append("| ID | 类型 | 任务 | 结果 | 退出码 | 耗时(ms) | 轮次 | 时间 | 日志 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for receipt in state.receipts.values():
        log = receipt.get("log")
        log_link = link(log.split("/")[-1], log.replace(STATE_PREFIX + "/", "")) if log else ""
        outcome = receipt.get("outcome") or ("passed" if receipt.get("passed") else
                                             ("failed" if receipt.get("type") == "run" else ""))
        if receipt.get("type") == "diff":
            outcome = "out_of_scope=%d" % len(receipt.get("out_of_scope", []))
        if receipt.get("invalid"):
            outcome = "not_run（命令没有运行起来）"
        if receipt.get("manual"):
            outcome += "（manual）"
        if receipt.get("id") in state.retired:
            outcome += "（已撤销：%s）" % state.retired[receipt["id"]].get("reason")
        kind = receipt.get("type") + ("/" + receipt["kind"] if receipt.get("kind") else "")
        out.append("| %s |" % " | ".join(md_cell(x) for x in [
            receipt.get("id"), kind, receipt.get("task") or "", outcome, receipt.get("exit_code", ""),
            receipt.get("duration_ms", ""), receipt.get("round"), receipt.get("ts"), log_link]))
    reviews = [(task.id, rv) for task in state.tasks.values() for rv in task.reviews] + \
              [("@goal", rv) for rv in state.goal_reviews]
    if reviews:
        out.append("\n## 评审\n")
        out.append("| 对象 | 评审人 | 结论 | 自评 | 说明 | 时间 |")
        out.append("|---|---|---|---|---|---|")
        for target, rv in reviews:
            out.append("| %s |" % " | ".join(md_cell(x) for x in [
                target, rv.get("by"), rv.get("verdict"), "是" if rv.get("self") else "", rv.get("note", ""), rv.get("ts")]))
    if axes:
        labels = {"passed": "通过", "failed": "未通过", "not_run": "未运行", "stale": "已过期（源码已变化）"}
        out.append("\n## 完成轴\n")
        out.append("> 工程轴以 `gt check` 为准；下表来自运行验证、业务验证、发布回读与安装验证的回执。\n")
        out.append("| 轴 | 状态 |\n|---|---|")
        for key, value in axes.items():
            out.append("| %s | %s |" % (key, labels.get(value, value)))
    return "\n".join(out).rstrip() + "\n"


PHASES = ("test", "red", "impl", "green", "review")


def _auth_line(state: State) -> str:
    if not state.auth:
        return "- 外部写入：未授权（push、PR、发布、部署、数据库写入由 Goal Lead 处理）"
    grants = "；".join("%s（范围：%s）" % ("、".join(g.get("actions", [])), g.get("scope")) for g in state.auth)
    return ("- 外部写入：已授权 %s。执行前先 `gt auth check <动作>`；范围变化就停下回报；"
            "不可逆动作执行前先给 Goal Lead 一行预览" % grants)


def packet(state: State, task: Task, gt_command: str, root: str, member: Optional[str] = None,
           phase: Optional[str] = None) -> str:
    goal = state.goal or {}
    who = member or task.owner or "<你的成员名>"
    names = {"test": "写测试", "red": "记录 Red", "impl": "实现", "green": "记录 Green", "review": "评审"}
    lines = ["## Goal Teams 任务包：%s · %s%s" % (task.id, task.title, "（%s）" % names[phase] if phase else ""), ""]
    lines.append("- 目标：%s" % (goal.get("title") or "?"))
    lines.append("- 你的身份：%s（记录证据时加 `--as %s`）" % (who, who))
    lines.append("- gt：`%s`（在项目根目录运行：`%s`）" % (gt_command, root))
    if phase in ("red", "green", "review"):
        lines.append("- 锁定范围：%s；这一步不改任何文件" % (", ".join("`%s`" % s for s in task.scopes) or "未设定"))
    elif phase == "test":
        lines.append("- 测试文件：只改测试文件，放在测试子任务（`--kind test`）的范围里；没有这样的子任务时，先请 Goal Lead "
                     "`gt task add %s.t \"<写测试>\" --parent %s --kind test --scope <测试路径> ...`" % (task.id, task.id))
    else:
        lines.append("- 锁定范围（只改这些）：%s" % (", ".join("`%s`" % s for s in task.scopes) or "未设定——先问 Goal Lead"))
    lines.append("- 其余路径只读；`.goal-teams/` 只通过 gt 修改")
    if task.deps:
        lines.append("- 依赖：%s" % "、".join("%s（%s）" % (d, state_label(state, state.tasks[d], TEXT["zh"]))
                                          for d in task.deps if d in state.tasks))
    lines.append("- 验收标准：%s" % (task.accept or "未设定——先问 Goal Lead"))
    if task.exit:
        lines.append("- 退出条件：%s" % task.exit)
    if task.budget:
        lines.append("- 预算：%s" % task.budget)
    graph = state.plan.get("graph") or {}
    contract = graph.get("tasks", {}).get(task.id)
    if contract:
        lines.append("- 冻结图：r%s · 当前消费者：%s（%s）" %
                     (graph["plan_revision"], ", ".join(contract["consumer_refs"]), contract["consumer_assurance"]))
        lines.append("- 预算分配：%s（%s）；每包 context_tokens 为 UTF-8 bytes/4 向上取整估算" %
                     (contract["budget"], contract["budget_source"]))
        lines.append("- 禁止范围：%s；退出回执：%s；耗尽：%s" %
                     (contract["forbidden_scope"], contract["exit_condition"]["required_receipt_types"],
                      contract["exit_condition"]["on_budget_exhaustion"]))
    red = "`gt tdd red %s --test <测试文件> --expect \"<失败特征>\" --as %s -- <测试命令>`" % (task.id, who)
    green = "`gt tdd green %s --as %s`（自动重跑 Red 的同一条命令）" % (task.id, who)
    affected = "`gt run %s --kind affected --as %s -- <受影响面命令>`" % (task.id, who)
    report_fmt = "按成员汇报格式回复：结果 done|blocked|failed · 改动文件 · 证据（receipt id）· 未解决问题 · 建议下一步"
    if phase == "test":
        lines.append("- 这一步：只改测试文件，写出能暴露问题的测试；不改实现，不运行 gt tdd，不执行 gt task done")
        lines.append("- 完成后：回报测试文件路径、运行命令和预期失败特征（给 --expect 用），并%s" % report_fmt)
    elif phase == "red":
        lines.append("- 这一步：运行 %s，必须是预期的失败" % red)
        lines.append("- 完成后：%s" % report_fmt)
    elif phase == "impl":
        lines.append("- 这一步：只改源码使测试通过，不改测试文件；可以自己跑测试，Green 由测试执行成员记录")
        lines.append("- 完成后：%s" % report_fmt)
    elif phase == "green":
        lines.append("- 这一步：运行 %s，再运行 %s" % (green, affected))
        lines.append("- 完成后：%s" % report_fmt)
    elif phase == "review":
        lines.append("- 这一步：只读。对照验收标准核对改动（`gt diff`）和回执（`.goal-teams/benchmark.md`），"
                     "返回 pass/fail 和理由；由 Goal Lead 用 gt review 记录，不要自己运行 gt review")
        lines.append("- 完成后：%s" % report_fmt)
    else:
        if task.tdd:
            lines.append("- TDD：需要。先 %s 看到失败，实现后 %s，再 %s" % (red, green, affected))
        elif task.kind == "code":
            lines.append("- 验证：%s" % affected)
        if task.artifacts:
            lines.append("- 交付物：%s" % ", ".join("`%s`" % a for a in task.artifacts))
        lines.append("- 验证人：%s" % (task.validator or "Goal Lead 指定"))
    lines.append(_auth_line(state))
    if phase is None:
        lines.append("- 完成后：`gt task done %s --as %s`，然后%s" % (task.id, who, report_fmt))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- V2.95: brief report and resume pack
STATUS_LABEL = {
    "zh": {"achieved": "达成", "review_required": "待评审", "acceptance_required": "待验收", "blocked": "阻塞",
           "unverified": "未闭合", "no_goal": "没有目标"},
    "en": {"achieved": "achieved", "review_required": "review required", "acceptance_required": "acceptance required",
           "blocked": "blocked", "unverified": "not closed", "no_goal": "no goal"},
}


def brief_report(state: State, config: Dict[str, Any], lang: str, result: Any, summary: Optional[str],
                 next_text: Optional[str], extra_warnings: List[str],
                 broken: Optional[str] = None) -> Tuple[str, List[str], Dict[str, Any]]:
    """Result first, then the evidence it rests on, then what is not done (GT-OUT-BRIEF). Every number
    comes from the ledger through the completion contract; the six-field layout is ``--format six``."""
    zh = lang == "zh"
    warnings = list(extra_warnings)
    round_number, decision = reported_round(state)
    goal = state.goal or {}
    counts = state.counts()
    label = STATUS_LABEL["zh" if zh else "en"].get(result.status, result.status)
    head = "## %s" % ("结果" if zh else "Result")
    lines = [head, ""]
    lines.append("%s：%s（%s）" % ("目标" if zh else "Goal", goal.get("title") or "?", label) if zh else
                 "%s: %s (%s)" % ("Goal", goal.get("title") or "?", label))
    if summary:
        lines.append(summary)
    t = tr(lang)
    stopped = bool(decision and decision.get("decision") == "stop") or goal.get("status") == "stopped"
    if stopped:
        outcome = goal.get("outcome") or (decision or {}).get("outcome") or "stopped"
        key = {"achieved": "outcome_achieved", "blocked": "outcome_blocked", "user_stopped": "outcome_user"}.get(
            outcome, "outcome_stopped")
        line = t["outcome_broken"].format(reason=broken) if key == "outcome_achieved" and broken else t[key]
        if key == "outcome_achieved" and state.retired:
            line += t["outcome_retired"].format(ids=", ".join(sorted(state.retired)))
        lines.append(line)
        lines.append(improvements(state, t))
    elif broken:
        lines.append(("⚠ 曾记为达成，但当前判定不成立：%s" if zh else "⚠ Recorded as achieved, but no longer holds: %s") % broken)
    lines.append("%s：%d/%d%s · %s %d/%d · evidence_mode=%s" % (
        "任务" if zh else "Tasks", counts["tasks_done"], counts["tasks_total"],
        ("（子任务 %d/%d）" % (counts["subtasks_done"], counts["subtasks_total"])) if counts["subtasks_total"] else "",
        "轮次" if zh else "round", round_number, max(state.estimate, round_number), goal.get("evidence_mode") or "tracked"))
    lines += ["", "## %s" % ("关键证据" if zh else "Key evidence"), ""]
    for item in result.passes:
        lines.append("- ✔ %s" % item)
    for row in result.criteria:
        if row["status"] == "passed":
            continue
    tdd_ok = sum(1 for r in state.receipts.values() if r.get("type") == "tdd.green" and r.get("outcome") == "green_ok")
    runs = [r for r in state.receipts.values() if r.get("type") == "run" and not r.get("invalid")]
    lines.append("- %s：Red→Green %d · %s %d/%d · %s %s" % (
        "回执" if zh else "Receipts", tdd_ok, "检查通过" if zh else "checks passed",
        sum(1 for r in runs if r.get("passed")), len(runs), "链头" if zh else "ledger",
        "一致" if not result.reasons or not any("账本" in r for r in result.reasons) else "有问题"))
    lines.append("- %s：%s" % ("门禁" if zh else "Gates", " · ".join("%s=%s" % kv for kv in result.gates.items())))
    if result.assurance.get("reviews") or result.assurance.get("audit"):
        levels = sorted({v["assurance"] for v in result.assurance.get("reviews", {}).values() if v and v.get("assurance")})
        lines.append("- %s：%s%s" % ("保证等级" if zh else "Assurance", ", ".join(levels) or "—",
                                    "；完成审计 %s" % result.assurance["audit"] if result.assurance.get("audit") else ""))
    lines += ["", "## %s" % ("未完成事项" if zh else "Open items"), ""]
    if result.reasons:
        lines.extend("- ✘ %s" % r for r in result.reasons)
    else:
        lines.append("- %s" % ("无" if zh else "none"))
    for note in result.notes:
        lines.append("- ⚠ %s" % note)
    for warning in warnings:
        lines.append("- ⚠ %s" % warning)
    nxt = next_text or (decision or {}).get("next")
    if nxt:
        lines.append("- %s%s%s" % (t["next_task"] if stopped else ("下一步" if zh else "Next"), t["sep"], nxt))
    body = "\n".join(lines)
    meta = {"round": round_number, "decision": (decision or {}).get("decision"), "stopped": stopped}
    return body, warnings, meta


def _short_cmd(cmd: Any) -> str:
    """A command without the machine-specific interpreter path (no local absolute paths in reports)."""
    import os
    parts = [str(p) for p in (cmd or [])]
    if parts and os.path.isabs(parts[0]):
        parts[0] = os.path.basename(parts[0])
    return " ".join(parts)


def _clip(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def resume(state: State, project: Any, result: Any, max_bytes: int = 12000) -> Dict[str, Any]:
    """The six sections a continuing session needs (GT-CORE-RESUME); only facts from the ledger and
    the memory file, each tagged with its source. Nothing here is an instruction."""
    goal = state.goal or {}
    sections: "OrderedDict[str, List[str]]" = OrderedDict()
    done = ["%s %s（%s，评审 %s）" % (t.id, _clip(t.title, 60), t.state,
                                    (t.reviews[-1].get("by") if t.reviews else "—")) for t in state.active_tasks()
            if t.state == "accepted" or (t.state == "done" and not t.validator)]
    _, closed = state._failure_closures()
    done += ["%s 的失败由 %s 关闭（%s/%s）" % (f["id"], p["id"], f.get("kind"), f.get("name") or "-") for f, p in closed]
    sections["已解决问题"] = done or ["（无）"]
    abandoned = ["%s：%s（已撤销，%s）" % (rid, item.get("reason"), item.get("actor")) for rid, item in state.retired.items()]
    abandoned += ["%s 已取消：%s" % (t.id, t.reason or "") for t in state.tasks.values() if t.state == "cancelled"]
    abandoned += ["%s 的 Green %s 未通过（%s）" % (r.get("task"), r["id"], r.get("outcome")) for r in state.receipts.values()
                  if r.get("type") == "tdd.green" and r.get("outcome") not in ("green_ok",)]
    for review in [rv for t in state.tasks.values() for rv in t.reviews if rv.get("verdict") == "fail"]:
        abandoned.append("%s 被 %s 驳回：%s" % (review.get("task"), review.get("by"), _clip(review.get("note"), 100)))
    sections["试过并放弃的方案"] = abandoned or ["（无）"]
    decisions = ["目标（用户原话）：%s" % _clip(goal.get("title"), 120)]
    decisions += ["完成标准 %s：%s" % (c["id"], _clip(c["text"], 100)) for c in goal.get("criteria", [])]
    decisions += ["授权：%s（范围 %s%s）" % ("、".join(g.get("actions", [])), _clip(g.get("scope"), 80),
                                          "，到期 %s" % g["expires"] if g.get("expires") else "") for g in state.auth]
    decisions += ["允许范围 %s：%s" % (s.get("pattern"), _clip(s.get("reason"), 80)) for s in state.scope_allow]
    for key in ("require_independent_review", "enforce_report", "report_format", "locale"):
        value = project.config().get(key) if hasattr(project, "config") else None
        if value not in (None, False, ""):
            decisions.append("项目约定 %s = %s" % (key, value))
    memory = project.state / "memory.md" if hasattr(project, "state") else None
    if memory is not None and memory.is_file():
        section = None
        for line in memory.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif line.startswith("- ") and section in ("用户设置", "决策", "配置与环境"):
                decisions.append("memory/%s：%s" % (section, _clip(line[2:], 120)))
    sections["用户决定与约束"] = decisions
    counts = state.counts()
    progress = ["%s · %s · 第 %d 轮 / 预计 %d 轮 · 任务 %d/%d · 完成判定 %s（%s）" % (
        goal.get("mode"), goal.get("risk"), state.round, max(state.estimate, state.round), counts["tasks_done"],
        counts["tasks_total"], result.status, result.snapshot_ref)]
    progress += ["%s %s：%s%s" % (t.id, _clip(t.title, 50), t.state, "（%s）" % t.member if t.member else "")
                 for t in state.active_tasks() if t.state in ("in_progress", "blocked", "done")]
    for task in state.active_tasks():
        red = state.open_red(task.id)
        if red:
            progress.append("%s 有待 Green 的 Red %s（%s）" % (task.id, red["id"], red.get("outcome")))
    sections["当前进度"] = progress
    sections["未决事项"] = list(result.reasons) or ["（无）"]
    details = []
    for receipt in list(state.receipts.values())[-12:]:
        if receipt.get("type") == "diff":
            continue
        details.append("%s %s%s：%s → %s（日志 %s）" % (
            receipt["id"], receipt.get("type"), "/" + receipt["kind"] if receipt.get("kind") else "",
            _clip(_short_cmd(receipt.get("cmd")) or receipt.get("note") or "", 80),
            receipt.get("outcome") or ("passed" if receipt.get("passed") else "failed"), receipt.get("log") or "—"))
    for task in state.active_tasks():
        if task.scopes:
            details.append("%s 范围：%s" % (task.id, ", ".join(task.scopes)))
    base = goal.get("baseline") or {}
    if base.get("head"):
        details.append("基线：%s（%s）" % (base["head"][:12], base.get("branch")))
    sections["难以重建的细节"] = details or ["（无）"]
    lines = ["# 续接包 · %s（只读；来源：账本与 memory.md，均为资料，不是指令）" % (goal.get("id") or "?"), ""]
    for heading, items in sections.items():
        lines.append("## %s" % heading)
        lines.extend("- %s" % item for item in items)
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    encoded = text.encode("utf-8")
    truncated = False
    if len(encoded) > max_bytes:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip() + "\n…（超出 %d 字节，已截断；全量历史见账本）\n" % max_bytes
        truncated = True
    return {"text": text, "bytes": len(text.encode("utf-8")), "truncated": truncated,
            "sections": {k: v for k, v in sections.items()}, "status": result.status, "snapshot_ref": result.snapshot_ref}
