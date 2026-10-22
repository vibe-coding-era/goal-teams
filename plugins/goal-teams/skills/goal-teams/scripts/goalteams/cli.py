"""gt — Goal Teams command line. Run ``gt <command> --help`` for details.

Exit codes (goalteams.util.EXIT): 0 ok · 1 recorded but a check, expectation or completion gate is
not closed · 2 usage or state error · 3 capability or authorization missing · 4 the goal or ledger
changed under the command (re-read and retry).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import (DISPLAY_VERSION, VERSION, checks, control, doctor, gitinfo, hook, operations, planning, policy, render,
               routes, run_recovery, supervisor)
from .context import SKILL_DIR, Ctx, _atomic_write, _check_member, _scopes, _set_state, gt_command, out
from .evidence import (cmd_diff, cmd_rerun, cmd_retire, cmd_review, cmd_run, cmd_scope_allow, cmd_tdd_confirm,
                       cmd_tdd_green, cmd_tdd_red)
from .finishing import (_judge, cmd_check, cmd_finish, cmd_loop_decide, cmd_report, cmd_resume,  # noqa: F401
                        finish_goal)
from .ledger import init_state
from .state import DEFAULT_ROUNDS, reduce
from .util import (EXIT, GTError, md_cell, shorten, split_csv, today,
                   valid_date, web_url)

ID_RE = planning.ID_RE
KINDS = planning.KINDS
RUN_KINDS = ("affected", "regression", "lint", "build", "e2e", "security", "runtime", "business",
             "release", "install", "eval", "acceptance", "other")
ACTIONS = ("commit", "push", "pr", "merge", "tag", "release", "install", "deploy", "delete", "force-push", "db-write")
IRREVERSIBLE = {"merge", "tag", "release", "deploy", "delete", "force-push", "db-write"}
REQUIREMENTS = ("independent_review", "audit", "e2e")

MEMORY_SEED = """---
type: Goal Teams Memory
title: 项目记忆
---

# 项目记忆

> 记录重要的用户设置、配置、技术选型与上下文摘要。新内容追加在对应小节末尾（`gt memory add`）。

## 用户设置

## 配置与环境

## 决策

## 上下文摘要

## 待办
"""

LOOP_REVIEW_SEED = """---
type: Goal Teams Loop Review
title: LOOP 反思
---

# LOOP 反思

> 只在发现问题或目标结束时记录（`gt reflect`），每次最多 3 条可执行改进。
> 这里的改进只是候选：修改全局 Skill、提示词、权限或发布规则需要单独立项、授权和验证。
"""


# --------------------------------------------------------------------------- init / goal / route
def cmd_init(ctx: Ctx) -> int:
    project = ctx.project
    created = init_state(project, ctx.args.project, ctx.args.locale)
    if not created:
        out(ctx, "已初始化：%s（无改动）" % project.state, {"created": False, "state": str(project.state)})
        return EXIT.ok
    (project.state / "memory.md").write_text(MEMORY_SEED, encoding="utf-8")
    (project.state / "loop-review.md").write_text(LOOP_REVIEW_SEED, encoding="utf-8")
    work = project.work_tree
    git: Dict[str, Any] = {"repo": gitinfo.is_repo(work)}
    if git["repo"]:
        git.update({"head": gitinfo.head(work), "branch": gitinfo.branch(work),
                    "default_branch": gitinfo.default_branch(work), "remotes": gitinfo.remotes(work)})
    ctx.append("init", {"project": ctx.config["project"], "locale": ctx.config.get("locale"), "git": git,
                        "gt_version": VERSION})
    out(ctx, "已初始化 %s：config.json、ledger.jsonl、TaskList.md、memory.md、loop-review.md。\n"
             "下一步：gt goal \"<目标>\" --done \"<完成标准>\" [--mode tracked]" % project.state,
        {"created": True, "state": str(project.state)})
    return EXIT.ok


def _routing_from_args(args: argparse.Namespace, current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """mode/risk/domains/impact/phase from the new flags, with the previous release's flags as synonyms."""
    current = current or {}
    legacy = policy.from_legacy(args.size, ui=bool(getattr(args, "ui", False)), release=bool(getattr(args, "release", False)),
                                agent=bool(getattr(args, "agent", False)),
                                risk=getattr(args, "risk", None) or "normal") if getattr(args, "size", None) else {}
    mode = getattr(args, "mode", None) or legacy.get("mode") or current.get("mode") or "direct"
    risk = getattr(args, "risk", None) or legacy.get("risk") or current.get("risk") or "normal"
    domains = list(current.get("domains") or [])
    for item in (getattr(args, "domain", None) or []) + legacy.get("domains", []):
        if item not in domains:
            domains.append(item)
    if getattr(args, "ui", False) and "ui" not in domains:
        domains.append("ui")
    if getattr(args, "agent", False) and "agent" not in domains:
        domains.append("agent")
    impact = getattr(args, "impact", None) or current.get("impact") or "behavior_change"
    phase = "release" if getattr(args, "release", False) else (getattr(args, "phase", None) or current.get("phase") or "development")
    requirements = list(current.get("user_requirements") or [])
    for item in getattr(args, "require", None) or []:
        if item not in requirements:
            requirements.append(item)
    return {"mode": mode, "risk": risk, "domains": domains or ["code"], "impact": impact, "phase": phase,
            "user_requirements": requirements}


def _criteria_from_args(args: argparse.Namespace) -> List[Dict[str, Any]]:
    texts = list(args.done or [])
    checks_ = [shlex.split(c) for c in (args.check or [])]
    if checks_ and not texts:
        raise GTError("--check 需要对应的 --done 完成标准。")
    if len(checks_) > len(texts):
        raise GTError("--check 比 --done 多：第 n 个 --check 对应第 n 个 --done；没有命令的完成标准用 gt goal accept 人工验收。")
    for argv in checks_:
        if not argv:
            raise GTError("--check 不能为空。")
    items = []
    for index, text in enumerate(texts, start=1):
        check = checks_[index - 1] if index <= len(checks_) else None
        items.append({"id": "C%d" % index, "text": text, "check": check})
    return items


def cmd_goal(ctx: Ctx) -> int:
    args = ctx.args
    ctx.project.require()
    state = ctx.state()
    if args.show:
        if state.goal is None:
            raise GTError("还没有目标。", hint='gt goal "<目标>" --done "<完成标准>" [--mode tracked]')
        goal = state.goal
        lines = ["目标：%s（%s · %s · %s）" % (goal["title"], goal.get("mode"), goal.get("risk"), goal.get("status")),
                 "领域：%s · 影响：%s · 阶段：%s" % (", ".join(goal.get("domains") or []), goal.get("impact"), goal.get("phase")),
                 "轮次：第 %d 轮 / 预计 %d 轮" % (state.round, max(state.estimate, state.round)),
                 "完成标准："] + ["  %s. %s%s" % (c["id"], c["text"], "（--check %s）" % " ".join(c["check"]) if c.get("check") else "")
                                for c in goal.get("criteria", [])]
        lines.append("规则：%s" % ", ".join(["SKILL.md"] + (goal.get("route") or {}).get("rules", [])))
        required = [n for n, g in (goal.get("gates") or {}).items() if g.get("required")]
        lines.append("门禁：%s" % (", ".join(required) or "无"))
        base = goal.get("baseline") or {}
        lines.append("基线：%s" % (base.get("head") or "无 git"))
        out(ctx, "\n".join(lines), goal)
        return EXIT.ok
    updating = args.add_done or args.edit_done or (not args.title and (args.mode or args.size or args.domain or args.impact
                                                                       or args.release or args.risk or args.require))
    if updating:
        control.guard_subsession_write("gt goal 的完成标准、风险与模式修改")
        if state.goal is None or state.goal.get("status") != "active":
            raise GTError("没有进行中的目标可以更新。")
        data: Dict[str, Any] = {}
        if args.add_done:
            data["add_done"] = [{"text": t, "check": shlex.split(args.check[0]) if args.check else None} for t in args.add_done]
        if args.edit_done:
            cid, text = args.edit_done
            if cid not in {c["id"] for c in state.goal.get("criteria", [])}:
                raise GTError("没有完成标准 %s。" % cid, hint="已有：%s" % ", ".join(c["id"] for c in state.goal.get("criteria", [])))
            data["edit_done"] = {"id": cid, "text": text}
        if args.mode or args.size or args.domain or args.impact or args.release or args.risk or args.require:
            facts = _routing_from_args(args, state.goal)
            if facts["mode"] == "direct" and state.goal.get("mode") == "tracked" and not args.downgrade:
                raise GTError("tracked 不会自动降回 direct。", hint="如果用户明确要求，加 --downgrade --reason \"...\"。")
            if facts["risk"] == "normal" and state.goal.get("risk") == "high" and not args.downgrade:
                raise GTError("风险只会自动上调。", hint="如果用户明确要求降级，加 --downgrade --reason \"...\"。")
            if args.downgrade and not args.reason:
                raise GTError("降级需要 --reason 说明用户的要求。")
            described = routes.describe(facts["mode"], facts["risk"], facts["domains"], facts["impact"], facts["phase"],
                                        facts["user_requirements"], ctx.config)
            data.update({k: facts[k] for k in ("mode", "risk", "domains", "impact", "phase", "user_requirements")})
            data.update({"size": described["size"], "flags": described["flags"], "gates": described["gates"],
                         "route": {"rules": described["rules"], "team": described["team"]}})
            if args.downgrade:
                data["downgrade_reason"] = args.reason
        ctx.append("goal.update", data, expect=ctx.expect_same_goal(ctx.goal_id()))
        out(ctx, "目标已更新。", data)
        return EXIT.ok
    if not args.title:
        raise GTError("缺少目标标题。", hint='gt goal "<目标>" --done "<完成标准>" [--mode tracked]')
    if state.goal is not None and state.goal.get("status") == "active" and not args.replace:
        raise GTError("已有进行中的目标：%s" % state.goal["title"],
                      hint="先 gt finish（或 gt loop decide stop），或加 --replace 明确替换。")
    facts = _routing_from_args(args)
    described = routes.describe(facts["mode"], facts["risk"], facts["domains"], facts["impact"], facts["phase"],
                                facts["user_requirements"], ctx.config)
    work = ctx.project.work_tree
    baseline: Dict[str, Any] = {"head": None, "branch": None}
    if gitinfo.is_repo(work):
        baseline = {"head": gitinfo.head(work), "branch": gitinfo.branch(work), "dirty": gitinfo.status_counts(work)}
    goal_id = "G%d" % (len(state.goal_history) + (1 if state.goal else 0) + 1)
    criteria = _criteria_from_args(args)
    data = {"id": goal_id, "title": args.title, "criteria": criteria, "mode": facts["mode"], "risk": facts["risk"],
            "domains": described["domains"], "impact": facts["impact"], "phase": facts["phase"],
            "user_requirements": facts["user_requirements"], "size": described["size"],
            "rounds": args.rounds or DEFAULT_ROUNDS.get(facts["mode"], 3), "flags": described["flags"],
            "gates": described["gates"], "route": {"rules": described["rules"], "team": described["team"]},
            "baseline": baseline, "evidence_mode": "tracked"}
    if state.goal is not None and state.goal.get("status") == "active":
        data["replaces"] = state.goal.get("id")
    ctx.append("goal", data)
    notes = []
    if not criteria:
        notes.append("⚠ 还没有完成标准：gt goal --add-done \"<可观察的完成标准>\"" +
                     ("（tracked 必需）" if facts["mode"] == "tracked" else ""))
    if (baseline.get("dirty") or {}).get("changed") or (baseline.get("dirty") or {}).get("untracked"):
        notes.append("⚠ 开始时工作区已有未提交改动，它们会出现在 gt diff 中。")
    required = [n for n, g in described["gates"].items() if g["required"]]
    text = "目标 %s 已建立（%s · %s · %s）。\n需要读取：%s\n门禁：%s\n%s" % (
        goal_id, facts["mode"], facts["risk"], ", ".join(described["domains"]),
        ", ".join(["SKILL.md"] + described["rules"]), ", ".join(required) or "无", "\n".join(notes))
    out(ctx, text.rstrip(), data)
    return EXIT.ok


def cmd_goal_accept(ctx: Ctx) -> int:
    """Record the verdict on one done criterion with its source. Written by the session, so the assurance
    is self_reported whatever ``--quote`` says; reports say so (INV03)."""
    args = ctx.args
    state = ctx.active_goal_required()
    criteria = {c["id"]: c for c in state.goal.get("criteria") or []}
    if args.item not in criteria:
        raise GTError("没有完成标准 %s。" % args.item, hint="已有：%s" % (", ".join(criteria) or "无（gt goal --add-done）"))
    if criteria[args.item].get("check"):
        raise GTError("%s 有 --check 命令，由 gt finish 运行判定，不接受人工验收。" % args.item)
    if not args.quote or len(args.quote.strip()) < 2:
        raise GTError("缺少 --quote：写下用户的原话或结论来源（会原样进入汇报）。")
    from .completion import item_digest
    live = checks.Live(ctx.project, state)
    data = {"item": args.item, "result": args.result, "quote": args.quote.strip(), "source": args.source,
            "assurance": "self_reported",
            "binds": {"item_digest": item_digest(criteria[args.item].get("text") or ""), "source_digest": live.source(),
                      "tree": ctx.project.tree_label()}}
    ctx.append("goal.accept", data, expect=ctx.expect_same_goal(ctx.goal_id()))
    result = checks.judge(ctx.project, ctx.state(refresh=True))
    text = "%s 验收：%s（由会话记录，assurance=self_reported，未经用户系统确认）\n完成判定：%s" % (
        args.item, args.result, result.status)
    out(ctx, text, dict(data, completion=result.status))
    return EXIT.ok if args.result == "pass" else EXIT.unverified


def cmd_route(ctx: Ctx) -> int:
    args = ctx.args
    if not (args.mode or args.size):
        if ctx.project.exists() and ctx.state().goal:
            goal = ctx.state().goal
            facts = routes.describe(goal.get("mode") or "tracked", goal.get("risk") or "normal", goal.get("domains") or [],
                                    goal.get("impact") or "behavior_change", goal.get("phase") or "development",
                                    goal.get("user_requirements") or [], ctx.config)
        else:
            raise GTError("缺少 --mode。", hint="gt route --mode direct|tracked [--risk high] [--domain ui|agent|desktop] "
                                               "[--impact docs_only|presentation_only] [--release]")
    else:
        spec = _routing_from_args(args)
        facts = routes.describe(spec["mode"], spec["risk"], spec["domains"], spec["impact"], spec["phase"],
                                spec["user_requirements"], ctx.config if ctx.project.exists() else None)
    rules = ["SKILL.md"] + list(facts.get("rules", []))
    total = 0
    lines = ["路由：%s · 风险 %s · 领域 %s · 影响 %s · 阶段 %s" % (
        facts.get("mode"), facts.get("risk"), ", ".join(facts.get("domains") or []), facts.get("impact"), facts.get("phase"))]
    lines.append("需要读取：")
    for rel in rules:
        path = SKILL_DIR / rel
        size = path.stat().st_size if path.is_file() else 0
        total += size
        lines.append("  - %s（%d 字节）" % (rel, size))
    lines.append("  合计 %d 字节" % total)
    lines.append("门禁：")
    for name, gate in facts.get("gates", {}).items():
        mark = "✔" if gate["required"] else "—"
        lines.append("  %s %s：%s%s" % (mark, name, gate["reason"], "（≥ %s）" % gate["min_assurance"] if gate.get("min_assurance") and gate["required"] and name in ("review", "audit") else ""))
    team = facts.get("team", [])
    lines.append("建议成员：%s" % ("、".join(team) if team else "Goal Lead 独立完成"))
    lines.append("状态：%s" % ("gt goal 建立（tracked）" if facts.get("mode") == "tracked" else "第一条取证命令自动建立最小状态（direct）"))
    lines.append("升级信号：%s" % "；".join(routes.ESCALATION_SIGNALS))
    out(ctx, "\n".join(lines), dict(facts, rules=rules, bytes=total))
    return EXIT.ok


# --------------------------------------------------------------------------- auth
def cmd_auth_grant(ctx: Ctx) -> int:
    control.guard_subsession_write("gt auth grant")
    ctx.active_goal_required()
    actions = split_csv(ctx.args.actions)
    unknown = [a for a in actions if a not in ACTIONS]
    if not actions or unknown:
        raise GTError("动作无效：%s" % (", ".join(unknown) or "（空）"), hint="可用：%s" % ", ".join(ACTIONS))
    if not ctx.args.scope:
        raise GTError("缺少 --scope（授权覆盖的仓库/版本/范围/停止条件）。")
    if ctx.args.expires and not valid_date(ctx.args.expires):
        raise GTError("--expires 必须是 YYYY-MM-DD 日期：%s" % ctx.args.expires)
    data = {"actions": actions, "scope": ctx.args.scope, "repo": ctx.args.repo, "expires": ctx.args.expires,
            "note": ctx.args.note}
    ctx.append("auth.grant", data)
    irreversible = [a for a in actions if a in IRREVERSIBLE]
    out(ctx, "已记录一次性授权：%s\n范围：%s%s" % (
        ", ".join(actions), ctx.args.scope,
        "\n不可逆动作（执行前先给用户一行预览）：%s" % ", ".join(irreversible) if irreversible else ""), data)
    return EXIT.ok


def cmd_auth_show(ctx: Ctx) -> int:
    state = ctx.goal_required()
    if not state.auth:
        out(ctx, "本目标没有外部写入授权。", [])
        return EXIT.ok
    lines = ["- %s · 范围：%s%s" % (", ".join(g["actions"]), g.get("scope"),
                                  " · 到期 %s" % g["expires"] if g.get("expires") else "") for g in state.auth]
    out(ctx, "\n".join(lines), state.auth)
    return EXIT.ok


def cmd_auth_check(ctx: Ctx) -> int:
    state = ctx.goal_required()
    action = ctx.args.action
    grant = state.auth_covers(action)
    expired = bool(grant and grant.get("expires") and grant["expires"] < today())
    if grant is None or expired:
        out(ctx, "未授权：%s%s。请先向用户一次性说明仓库、动作、范围和停止条件并取得确认，再 gt auth grant。" % (
            action, "（授权已过期）" if expired else ""), {"authorized": False, "action": action})
        return EXIT.blocked
    origin = next((r["url"] for r in gitinfo.remotes(ctx.project.work_tree) if r["name"] == "origin"), None)
    granted_repo = grant.get("repo")
    if granted_repo and origin and (web_url(granted_repo) or granted_repo) != (web_url(origin) or origin):
        out(ctx, "未授权：%s 的授权绑定仓库 %s，当前 origin 是 %s。仓库变了，请重新向用户确认。" % (
            action, granted_repo, origin), {"authorized": False, "action": action, "reason": "repo_mismatch",
                                             "granted_repo": granted_repo, "origin": origin})
        return EXIT.blocked
    note = "；不可逆：执行前先给用户一行预览（做什么、在哪里、如何回滚）" if action in IRREVERSIBLE else ""
    verified = "动作、有效期" + ("、仓库 %s" % granted_repo if granted_repo else "")
    unverified = "范围“%s”由你核对（gt 只比对动作、有效期和仓库）" % grant.get("scope")
    if not granted_repo:
        unverified = "授权未绑定仓库（gt auth grant --repo 可绑定）；" + unverified
    out(ctx, "已授权：%s（已核对：%s；%s）%s" % (action, verified, unverified, note),
        {"authorized": True, "action": action, "irreversible": action in IRREVERSIBLE, "grant": grant,
         "verified": ["action", "expiry"] + (["repo"] if granted_repo else []), "unverified": ["scope"]})
    return EXIT.ok


# --------------------------------------------------------------------------- tasks
def _graph_task_args(args) -> Dict[str, Any]:
    fields = {}
    for flag, key in (("consumer", "consumer_refs"), ("requirement", "requirement_refs"), ("forbid", "forbidden_scope")):
        value = getattr(args, flag, None)
        if value is not None:
            fields[key] = value
    budget_json = getattr(args, "budget_json", None)
    if budget_json is not None:
        try:
            fields["budget"] = json.loads(budget_json)
        except ValueError as exc:
            raise GTError("--budget-json 不是有效JSON：%s" % exc)
        from .graph_budget import limits
        limits(fields["budget"])
    return fields


def cmd_task_add(ctx: Ctx) -> int:
    args = ctx.args
    raw = {"id": args.id, "title": args.title, "parent": args.parent, "owner": args.owner, "validator": args.validator,
           "deps": args.deps or [], "priority": args.priority or "P1", "scopes": args.scope or [], "accept": args.accept,
           "exit": args.exit, "budget": args.budget, "tdd": bool(args.tdd), "kind": args.kind or "code",
           "artifacts": args.artifact or []}
    raw.update(_graph_task_args(args))
    spec, warnings = planning.add_task(ctx, raw)
    revision = ctx.state(refresh=True).plan["revision"]
    notes = ["⚠ %s" % w for w in warnings]
    out(ctx, "已添加任务 %s：%s（计划 r%d）%s" % (spec["id"], spec["title"], revision, ("\n" + "\n".join(notes)) if notes else ""),
        dict(spec, revision=revision))
    return EXIT.ok


def cmd_task_edit(ctx: Ctx) -> int:
    args = ctx.args
    ctx.active_goal_required()
    task = ctx.task(args.id)
    changes: Dict[str, Any] = {}
    for key in ("title", "priority", "accept", "exit", "budget", "kind"):
        value = getattr(args, key)
        if value is not None:
            changes[key] = value
    for key in ("owner", "validator"):
        value = getattr(args, key)
        if value is not None:
            changes[key] = _check_member(value)
    if args.deps is not None:
        changes["deps"] = split_csv(args.deps)
    if args.add_scope:
        changes["scopes"] = task.scopes + [s for s in _scopes(args.add_scope) if s not in task.scopes]
    if args.add_artifact:
        changes["artifacts"] = task.artifacts + [s for s in args.add_artifact if s not in task.artifacts]
    if args.tdd is not None:
        changes["tdd"] = args.tdd == "on"
    changes.update(_graph_task_args(args))
    warnings = planning.edit_task(ctx, task, changes)
    revision = ctx.state(refresh=True).plan["revision"]
    notes = ["⚠ %s" % w for w in warnings]
    out(ctx, "已修改 %s：%s（计划 r%d）%s" % (task.id, ", ".join(sorted(changes)), revision,
                                           ("\n" + "\n".join(notes)) if notes else ""), dict(changes, revision=revision))
    return EXIT.ok


def cmd_task_start(ctx: Ctx) -> int:
    state = ctx.active_goal_required()
    task = ctx.task(ctx.args.id)
    if task.state not in ("pending", "in_progress"):
        raise GTError("%s 当前是 %s，不能开始。" % (task.id, task.state),
                      hint="阻塞用 gt task unblock；被驳回的任务已自动回到进行中。")
    waiting = [d for d in task.deps if d in state.tasks and state.tasks[d].active and not state.tasks[d].complete]
    if waiting and not ctx.args.force:
        raise GTError("依赖尚未完成：%s" % ", ".join(waiting), hint="确有必要时加 --force --reason \"...\"")
    _set_state(ctx, task, "in_progress", member=ctx.actor if ctx.actor != "lead" else task.owner,
               forced=bool(waiting) or None, note=ctx.args.reason)
    out(ctx, "%s → 进行中%s" % (task.id, "（强制，依赖未完成：%s）" % ", ".join(waiting) if waiting else ""))
    return EXIT.ok


def cmd_task_done(ctx: Ctx) -> int:
    """Mark a task done. Structural problems are refused; missing evidence is reported as warnings —
    the hard gate is gt finish / gt check, which judge the final code (GT-CORE-FINISH)."""
    state = ctx.active_goal_required()
    task = ctx.task(ctx.args.id)
    if task.state not in ("pending", "in_progress"):
        raise GTError("%s 当前是 %s，不能标记完成。" % (task.id, task.state))
    open_children = ["%s（%s）" % (c.id, "评审已过期" if c.stale else c.state)
                     for c in state.children(task.id) if not c.complete]
    if open_children:
        raise GTError("子任务未完成：%s" % ", ".join(open_children))
    warnings: List[str] = []
    last = state.latest_green(task.id)
    if last is not None and last.get("outcome") != "green_ok":
        warnings.append("最近一次 Green（%s）没有通过：%s" % (last["id"], last.get("outcome")))
    if task.tdd:
        green = state.latest(task.id, "tdd.green", "green_ok")
        red = state.open_red(task.id)
        if green is None:
            warnings.append("需要 TDD 证据：gt tdd red，再 gt tdd green")
        elif red is not None:
            warnings.append("在 Green 之后又有成立的 Red（%s）：先让它 Green" % red["id"])
        elif checks.test_files_changed(ctx.project, green):
            warnings.append("测试文件在 Green 之后变了：新的行为重新 Red/Green；补用例写进新文件并用 affected 记录")
    live = checks.Live(ctx.project, state)
    fresh = checks.fresh_impl_pass(live, state, task)
    if task.tdd and fresh is None:
        warnings.append("实现在最后一次 Green 之后又改了：gt rerun %s（或 gt tdd green %s）" % (task.id, task.id))
    elif task.kind == "code" and fresh is None and checks.needs_own_evidence(live, state, task):
        warnings.append("还没有在当前实现上通过的测试记录：gt run %s --kind affected -- <命令>" % task.id)
    _set_state(ctx, task, "done", note=ctx.args.note)
    nxt = "等待 %s 评审（gt review %s --by %s --verdict pass|fail）" % (task.validator, task.id, task.validator) \
        if task.validator else "无验证人：记为已完成（gt finish 按策略判断是否需要评审）"
    text = "%s → 完成。%s" % (task.id, nxt)
    if warnings:
        text += "\n" + "\n".join("⚠ %s（gt finish 会要求）" % w for w in warnings)
    out(ctx, text, {"task": task.id, "warnings": warnings})
    return EXIT.ok


def cmd_task_block(ctx: Ctx) -> int:
    state = ctx.active_goal_required()
    task = ctx.task(ctx.args.id)
    if task.state in ("accepted", "cancelled"):
        raise GTError("%s 已经是 %s。" % (task.id, task.state))
    _set_state(ctx, task, "blocked", reason=ctx.args.reason, external=bool(ctx.args.external) or None)
    affected = ctx.state().descendants(task.id)
    out(ctx, "%s → 阻塞%s：%s\n影响的后继任务：%s" % (
        task.id, "（外部）" if ctx.args.external else "", ctx.args.reason, "、".join(affected) or "无"))
    return EXIT.ok


def cmd_task_unblock(ctx: Ctx) -> int:
    ctx.active_goal_required()
    task = ctx.task(ctx.args.id)
    if task.state != "blocked":
        raise GTError("%s 没有阻塞。" % task.id)
    _set_state(ctx, task, "unblocked", note=ctx.args.note)
    out(ctx, "%s 已解除阻塞 → %s" % (task.id, ctx.task(task.id).state))
    return EXIT.ok


def cmd_task_cancel(ctx: Ctx) -> int:
    ctx.active_goal_required()
    task = ctx.task(ctx.args.id)
    if task.state == "accepted":
        raise GTError("%s 已验收，不能取消。" % task.id)
    _set_state(ctx, task, "cancelled", reason=ctx.args.reason)
    out(ctx, "%s → 已取消：%s（计划升为 r%d；取消不缩小完成分母，汇报会列出）" % (
        task.id, ctx.args.reason, ctx.state(refresh=True).plan["revision"]))
    return EXIT.ok


def cmd_task_list(ctx: Ctx) -> int:
    state = ctx.goal_required()
    t = render.tr(ctx.lang)
    rows = ["| ID | 任务 | 负责 | 验证 | 依赖 | 状态 |", "|---|---|---|---|---|---|"]
    for task in state.tasks.values():
        rows.append("| %s |" % " | ".join(md_cell(x) for x in [
            ("  ↳ " if task.parent else "") + task.id, shorten(task.title, 40), task.owner or "",
            task.validator or "", ",".join(task.deps), render.state_label(state, task, t)]))
    payload = [dict(vars(task)) for task in state.tasks.values()]
    out(ctx, "\n".join(rows) if state.tasks else "没有任务。", payload)
    return EXIT.ok


def cmd_task_packet(ctx: Ctx) -> int:
    from . import graph_contract
    state = graph_contract.ensure_frozen(ctx)
    task = ctx.task(ctx.args.id)
    member = _check_member(ctx.args.for_) or task.owner
    text = render.packet(state, task, gt_command(), str(ctx.project.root), member=member)
    receipt = graph_contract.context_receipt(state, task.id, text)
    out(ctx, text.rstrip(), {"task": task.id, "member": member, "packet": text, "context_receipt": receipt})
    return EXIT.ok


# --------------------------------------------------------------------------- plan
def cmd_graph_status(ctx: Ctx) -> int:
    from . import graph_contract, graph_budget
    state = ctx.goal_required()
    problems = graph_contract.completion_problems(state)
    try:
        budget = graph_budget.status(state)
    except GTError as exc:
        budget = {"tasks": {}, "errors": [str(exc)]}
    result = {"graph": state.plan.get("graph"), "budget": budget, "problems": problems,
              "ready_tasks": graph_contract.ready_tasks(state), "blocked_closure": graph_contract.blocked_closure(state)}
    lines = ["任务图 r%d：%s" % (state.plan["revision"], "；".join(problems) if problems else "当前冻结绑定通过")]
    for key, row in budget["tasks"].items():
        lines.append("%s 剩余：%s（context_tokens每包上限 %s）" % (key, row["remaining"], row["allocated"]["context_tokens"]))
    lines.append("可继续任务：%s；阻塞闭包：%s" % (result["ready_tasks"], result["blocked_closure"]))
    out(ctx, "\n".join(lines), result)
    return EXIT.unverified if problems else EXIT.ok


def cmd_graph_finding(ctx: Ctx) -> int:
    from . import graph_contract
    control.require_operator("gt graph finding")
    state = graph_contract.ensure_frozen(ctx)
    problems = ctx.project.verify()
    if problems:
        raise GTError("账本/证据校验失败：%s" % "；".join(problems), code=EXIT.unverified)
    try:
        finding = json.loads(Path(ctx.args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GTError("读不到 finding JSON：%s" % exc)
    source = checks.collect(ctx.project, state).source_digest
    decision = graph_contract.classify_finding(state, finding, current_source_digest=source)
    def expect(current):
        if any(x.get("finding", {}).get("finding_id") == finding["finding_id"] for x in current.graph_findings):
            raise GTError("finding ID 已记录，不能重复准入。", code=EXIT.conflict)
        current_source = checks.collect(ctx.project, current).source_digest
        if graph_contract.classify_finding(current, finding, current_source_digest=current_source) != decision:
            raise GTError("finding 准入期间源码/任务图/预算漂移。", code=EXIT.conflict)
    ctx.append("graph.finding", {"finding": finding, "decision": decision}, expect=expect)
    out(ctx, "finding %s：%s（未修改TaskExactSet；实际修复命令仍逐次消耗预算）" %
        (finding["finding_id"], decision["classification"]), decision)
    return EXIT.ok if decision["admitted"] else EXIT.unverified


plan_problems = planning.plan_problems


DEFAULT_PLAN = "plan.json"  # inside .goal-teams/, so it never shows up as an out-of-scope change


def cmd_plan_apply(ctx: Ctx) -> int:
    args = ctx.args
    path = Path(args.file) if args.file else ctx.project.state / DEFAULT_PLAN
    if args.file or (path.is_file() and getattr(args, "sub", "") == "apply"):
        plan = planning.load_plan_file(path)
        result = planning.apply_plan(ctx, plan, args.note)
    else:
        result = planning.apply_current(ctx, args.note)
    layers, path, width = result["layers"], result["critical_path"], result["width"]
    text = ["计划 r%d 已校验并记录：新增 %d、修改 %d；%d 层，关键路径 %s（%d），最大并行宽度 %d。" % (
        result["revision"], len(result["added"]), len(result["edited"]), len(layers), " → ".join(path) or "—", len(path), width)]
    text.extend("⚠ %s" % w for w in result["warnings"])
    out(ctx, "\n".join(text), result)
    return EXIT.ok


def cmd_plan_show(ctx: Ctx) -> int:
    state = ctx.goal_required()
    layers, path, width, cycle = state.dag()
    errors, warnings = plan_problems(state)
    plan = state.plan
    lines = ["计划 r%d（%s）" % (plan["revision"], "整体已校验" if plan.get("frozen") else "有未整体校验的手工改动")]
    lines.extend("  L%d：%s" % (i + 1, ", ".join(layer)) for i, layer in enumerate(layers))
    lines.append("关键路径：%s（%d）· 最大并行宽度：%d" % (" → ".join(path) or "—", len(path), width))
    if plan.get("changes_since_apply"):
        lines.append("上次 apply 后的变更：%s" % "；".join(plan["changes_since_apply"]))
    lines.extend("✘ %s" % e for e in errors)
    lines.extend("⚠ %s" % w for w in warnings)
    out(ctx, "\n".join(lines), {"plan": plan, "layers": layers, "critical_path": path, "width": width,
                                "cycle": cycle, "errors": errors, "warnings": warnings})
    return EXIT.ok


# --------------------------------------------------------------------------- loop / finish / report
def cmd_status(ctx: Ctx) -> int:
    state = ctx.goal_required()
    text = render.dashboard(state, ctx.config, ctx.lang, ctx.web(), oos=ctx.oos())
    payload = {"goal": state.goal, "round": state.round, "estimate": state.estimate,
               "counts": state.counts(), "plan": state.plan, "blocked": [t.id for t in state.blocked()]}
    out(ctx, text, payload)
    return EXIT.ok


def cmd_reflect(ctx: Ctx) -> int:
    args = ctx.args
    state = ctx.goal_required()
    actions = args.action or []
    if len(actions) > 3:
        raise GTError("每次最多 3 条改进（--action）。")
    data = {"kind": args.kind, "observation": args.observation, "actions": actions}
    ctx.append("reflect", data)
    lines = ["", "## %s · 第 %d 轮 · %s" % (today(), state.round, args.kind), "", "- 观察：%s" % args.observation]
    if actions:
        lines.append("- 改进（候选）：")
        lines.extend("  %d. %s" % (i, a) for i, a in enumerate(actions, 1))
    else:
        lines.append("- 改进：无（no_finding）")
    with open(ctx.project.state / "loop-review.md", "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    out(ctx, "已记录反思到 .goal-teams/loop-review.md（%d 条改进）。" % len(actions), data)
    return EXIT.ok


def cmd_doctor(ctx: Ctx) -> int:
    info = doctor.run(ctx.project)
    if ctx.project.exists() and ctx.state().goal is not None:
        ctx.append("preflight", {k: v for k, v in info.items() if k not in ("root", "work_tree")})
    out(ctx, doctor.format_text(info), info)
    return EXIT.unverified if info["blockers"] else EXIT.ok


def cmd_context_add(ctx: Ctx) -> int:
    ctx.goal_required()
    link = ctx.args.link
    if link and not re.match(r"^https?://", link):
        full = (Path.cwd() / link).resolve()
        try:
            link = full.relative_to(ctx.project.root).as_posix()
        except ValueError:
            raise GTError("--link 必须是项目内路径或 http(s) 链接（不要暴露本机绝对路径）。")
        if not full.exists():
            raise GTError("--link 指向的文件不存在：%s" % ctx.args.link)
    data = {"kind": ctx.args.kind, "label": ctx.args.label, "link": link}
    ctx.append("context.add", data)
    out(ctx, "已加入 Context：%s %s" % (ctx.args.kind, ctx.args.label), data)
    return EXIT.ok


def cmd_memory_add(ctx: Ctx) -> int:
    ctx.project.require()
    path = ctx.project.state / "memory.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else MEMORY_SEED
    heading = "## " + ctx.args.section
    entry = "- %s %s" % (today(), ctx.args.text.strip())
    if heading in text:
        start = text.index(heading) + len(heading)
        nxt = text.find("\n## ", start)
        if nxt == -1:
            text = text.rstrip("\n") + "\n" + entry + "\n"
        else:
            text = text[:nxt].rstrip("\n") + "\n" + entry + "\n" + text[nxt:]
    else:
        text = text.rstrip("\n") + "\n\n" + heading + "\n" + entry + "\n"
    _atomic_write(path, text)
    ctx.append("memory", {"section": ctx.args.section, "text": ctx.args.text})
    out(ctx, "已写入 memory.md（%s）。" % ctx.args.section)
    return EXIT.ok


def cmd_verify(ctx: Ctx) -> int:
    ctx.project.require()
    if ctx.args.reset_head:
        control.guard_subsession_write("gt verify --reset-head")
        reason = (ctx.args.reason or "").strip()
        if len(reason) < 4:
            raise GTError("重置链头需要 --reason 说明原因（会记入账本，并出现在 gt check 和汇报里）。")
        found = ctx.project.verify()
        ctx.project.append("head.reset", {"reason": reason, "problems": found[:20]}, ctx.actor, reset_head=True,
                           after=ctx._regenerate_safe)
        out(ctx, "已在账本中记录链头重置（原因：%s）。重置前的问题：%s" % (reason, "；".join(found) or "无"))
        return EXIT.ok
    problems = ctx.project.verify()
    warnings = ctx.project.log_warnings(list(reduce(ctx.project.events()).receipts.values())) if not problems else []
    text = ("账本完整：%d 条事件，链头一致。" % len(ctx.project.read_lines())) if not problems else \
        "账本问题：\n- " + "\n- ".join(problems)
    if warnings:
        text += "\n" + "\n".join("⚠ %s" % w for w in warnings)
    out(ctx, text, {"ok": not problems, "problems": problems, "warnings": warnings})
    return EXIT.ok if not problems else EXIT.unverified


CONFIG_KEYS: Dict[str, Tuple[str, ...]] = {
    "project": (),
    "locale": ("zh", "en"),
    "enforce_report": ("true", "false"),
    "require_independent_review": ("true", "false"),
    "report_format": ("brief", "six"),
    "git.branch": ("feature", "current"),
    "git.branch_prefix": (),
    "git.remote_protocol": ("inherit", "ssh", "https"),
}


def cmd_config_show(ctx: Ctx) -> int:
    ctx.project.require()
    config = ctx.config
    lines = ["%s = %s" % (key, json.dumps(_config_get(config, key), ensure_ascii=False)) for key in CONFIG_KEYS]
    out(ctx, "\n".join(lines), config)
    return EXIT.ok


def _config_get(config: Dict[str, Any], key: str) -> Any:
    value: Any = config
    for part in key.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def cmd_config_set(ctx: Ctx) -> int:
    control.guard_subsession_write("gt config set")
    ctx.project.require()
    key, raw = ctx.args.key, ctx.args.value
    if key not in CONFIG_KEYS:
        raise GTError("不能设置 %s。" % key, hint="可设置：%s" % ", ".join(CONFIG_KEYS))
    choices = CONFIG_KEYS[key]
    if choices and raw not in choices:
        raise GTError("%s 只能是：%s" % (key, " | ".join(choices)))
    value: Any = (raw == "true") if key in ("enforce_report", "require_independent_review") else raw
    config = json.loads(ctx.project.config_path.read_text(encoding="utf-8"))
    target = config
    parts = key.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value
    ctx.project.write_config(config)
    ctx.append("config", {"key": key, "value": value})
    out(ctx, "已设置 %s = %s" % (key, json.dumps(value, ensure_ascii=False)), {"key": key, "value": value})
    return EXIT.ok


def cmd_version(ctx: Ctx) -> int:
    print("gt %s（Goal Teams %s）" % (VERSION, DISPLAY_VERSION))
    return EXIT.ok


def cmd_hook_stop(ctx: Ctx) -> int:
    return hook.stop()


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    # SUPPRESS keeps a global flag given before the sub-command from being reset by the sub-parser.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS, help="项目根目录（默认自动查找）")
    common.add_argument("--as", dest="as_", metavar="NAME", default=argparse.SUPPRESS,
                        help="记录事件的成员名（默认 GT_ACTOR 或 lead）")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="输出 JSON")
    common.add_argument("--lang", choices=("zh", "en"), default=argparse.SUPPRESS, help="输出语言")

    parser = argparse.ArgumentParser(prog="gt", description="Goal Teams 账本、完成判定与汇报工具（%s）。" % DISPLAY_VERSION,
                                     parents=[common])
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name: str, handler: Callable[[Ctx], int], help_text: str, target: Any = sub) -> argparse.ArgumentParser:
        p = target.add_parser(name, help=help_text, description=help_text, parents=[common])
        p.set_defaults(handler=handler)
        return p

    def routing_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--mode", choices=policy.MODES, help="direct（默认）或 tracked")
        p.add_argument("--risk", choices=policy.RISKS)
        p.add_argument("--domain", action="append", choices=policy.DOMAINS, help="可重复：ui、desktop、agent、api、data")
        p.add_argument("--impact", choices=policy.IMPACTS)
        p.add_argument("--release", action="store_true", help="阶段 = release（发布门禁）")
        p.add_argument("--require", action="append", choices=REQUIREMENTS, help="用户明确要求：independent_review、audit、e2e")
        p.add_argument("--size", choices=routes.SIZES, help=argparse.SUPPRESS)  # legacy synonym
        p.add_argument("--ui", action="store_true", help=argparse.SUPPRESS)
        p.add_argument("--agent", action="store_true", help=argparse.SUPPRESS)

    p = add("init", cmd_init, "创建 .goal-teams/ 状态目录（幂等；direct 可省略，第一条取证命令会自动建立）")
    p.add_argument("--project")
    p.add_argument("--locale", choices=("zh", "en"))

    p = add("goal", cmd_goal, "建立/查看/更新目标（gt goal accept 记录逐项验收）")
    p.add_argument("title", nargs="?")
    p.add_argument("--done", action="append", help="可观察的完成标准，可重复（编号 C1、C2…）")
    p.add_argument("--check", action="append", help="证明第 n 个 --done 的命令（按顺序对应；没有命令的标准用 gt goal accept 人工验收）")
    routing_flags(p)
    p.add_argument("--rounds", type=int)
    p.add_argument("--show", action="store_true")
    p.add_argument("--add-done", action="append")
    p.add_argument("--edit-done", nargs=2, metavar=("ID", "TEXT"), help="修改完成标准文本（旧验收会过期）")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--downgrade", action="store_true")
    p.add_argument("--reason", help="降级原因（用户的要求）")

    p = add("goal-accept", cmd_goal_accept, "记录完成标准的人工验收（gt goal accept ...）")
    p.add_argument("--item", required=True, help="完成标准编号，如 C1")
    p.add_argument("--result", choices=("pass", "fail"), required=True)
    p.add_argument("--quote", required=True, help="用户原话或结论来源，原样进入汇报")
    p.add_argument("--source", help="来源标识（会话、链接）")

    p = add("route", cmd_route, "按事实给出要读的规则、门禁和成员（不需要状态）")
    routing_flags(p)

    auth = add("auth", None, "外部写入的一次性授权").add_subparsers(dest="sub", metavar="<sub>")
    p = add("grant", cmd_auth_grant, "记录用户已确认的授权", auth)
    p.add_argument("--actions", action="append", required=True, help=",".join(ACTIONS))
    p.add_argument("--scope", required=True)
    p.add_argument("--repo")
    p.add_argument("--expires", help="YYYY-MM-DD")
    p.add_argument("--note")
    add("show", cmd_auth_show, "查看授权", auth)
    p = add("check", cmd_auth_check, "检查某个动作是否已授权（未授权退出码 3）", auth)
    p.add_argument("action", choices=ACTIONS)

    task = add("task", None, "任务").add_subparsers(dest="sub", metavar="<sub>")
    p = add("add", cmd_task_add, "添加任务（经计划服务校验，计划版本 +1）", task)
    p.add_argument("id")
    p.add_argument("title")
    for flag in ("--parent", "--owner", "--validator", "--priority", "--accept", "--exit", "--budget"):
        p.add_argument(flag)
    p.add_argument("--deps", action="append")
    p.add_argument("--scope", action="append")
    p.add_argument("--artifact", action="append")
    p.add_argument("--tdd", action="store_true")
    p.add_argument("--kind", choices=KINDS)
    for flag in ("--consumer", "--requirement", "--forbid"):
        p.add_argument(flag, action="append")
    p.add_argument("--budget-json")
    p = add("edit", cmd_task_edit, "修改任务字段（规格变化使旧评审过期）", task)
    p.add_argument("id")
    for flag in ("--title", "--owner", "--validator", "--priority", "--accept", "--exit", "--budget"):
        p.add_argument(flag)
    p.add_argument("--deps", action="append")
    p.add_argument("--add-scope", action="append")
    p.add_argument("--add-artifact", action="append")
    p.add_argument("--tdd", choices=("on", "off"))
    p.add_argument("--kind", choices=KINDS)
    for flag in ("--consumer", "--requirement", "--forbid"):
        p.add_argument(flag, action="append")
    p.add_argument("--budget-json")
    p = add("start", cmd_task_start, "开始任务", task)
    p.add_argument("id")
    p.add_argument("--force", action="store_true")
    p.add_argument("--reason")
    p = add("done", cmd_task_done, "负责人标记完成（缺证据只提醒；硬门禁在 gt finish）", task)
    p.add_argument("id")
    p.add_argument("--note")
    p = add("block", cmd_task_block, "标记阻塞", task)
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.add_argument("--external", action="store_true")
    p = add("unblock", cmd_task_unblock, "解除阻塞", task)
    p.add_argument("id")
    p.add_argument("--note")
    p = add("cancel", cmd_task_cancel, "取消任务", task)
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    add("list", cmd_task_list, "列出任务", task)
    p = add("packet", cmd_task_packet, "生成派发给成员的任务包", task)
    p.add_argument("id")
    p.add_argument("--for", dest="for_", metavar="MEMBER", help="任务包写给谁（默认负责人）")

    plan = add("plan", None, "计划（依赖图）").add_subparsers(dest="sub", metavar="<sub>")
    p = add("apply", cmd_plan_apply, "校验并原子提交计划：gt plan apply plan.json（不带文件 = 校验当前任务集）", plan)
    p.add_argument("file", nargs="?")
    p.add_argument("--note")
    p = add("freeze", cmd_plan_apply, argparse.SUPPRESS, plan)  # legacy synonym of plan apply without a file
    p.add_argument("--note")
    p.set_defaults(file=None)
    add("show", cmd_plan_show, "查看分层、关键路径与问题", plan)

    tdd = add("tdd", None, "TDD Red/Green 证据").add_subparsers(dest="sub", metavar="<sub>")
    p = add("red", cmd_tdd_red, "运行测试并要求失败：gt tdd red T --test F [--expect 正则] -- <命令>", tdd)
    p.add_argument("task")
    p.add_argument("--test", action="append")
    p.add_argument("--expect", help="失败输出中应出现的正则；给了就直接 red_verified，否则稍后 gt tdd confirm")
    p.add_argument("--timeout", type=float)
    p.add_argument("--output", action="append", help="命令生成的输出文件（测试报告等），Green 会沿用")
    p = add("green", cmd_tdd_green, "实现后重跑 Red 的同一条命令并要求通过：gt tdd green T", tdd)
    p.add_argument("task")
    p.add_argument("--timeout", type=float)
    p = add("confirm", cmd_tdd_confirm, "核对一条 red_observed 的失败原因（读原始日志，不重跑）：gt tdd confirm R --expect 正则", tdd)
    p.add_argument("receipt", metavar="R")
    p.add_argument("--expect", required=True)
    p.add_argument("--note")

    p = add("rerun", cmd_rerun, "在当前代码上重跑各任务最后一次通过的 Green/affected 命令")
    p.add_argument("tasks", nargs="*", metavar="T", help="任务 ID（默认：缺少当前代码上通过记录的代码任务）")
    p.add_argument("--timeout", type=float)
    p = add("retire", cmd_retire, "撤销一次错误的检查失败（命令写错等），原因会写进检查和汇报")
    p.add_argument("receipt", metavar="R")
    p.add_argument("--reason", required=True)
    p = add("run", cmd_run, "运行检查并记录证据：gt run T --kind affected -- <命令>")
    p.add_argument("task", help="任务 ID，或 - 表示目标级")
    p.add_argument("--kind", choices=RUN_KINDS, required=True)
    p.add_argument("--name")
    p.add_argument("--timeout", type=float)
    p.add_argument("--manual", action="store_true")
    p.add_argument("--result", choices=("pass", "fail"))
    p.add_argument("--note")
    p.add_argument("--evidence")
    p.add_argument("--artifact", action="append", help="记录构建产物的名称、大小和 SHA-256（可重复）")
    p.add_argument("--output", action="append", help="命令生成的输出文件（测试报告、覆盖率），不算源码（可重复）")

    p = add("diff", cmd_diff, "对比目标基线的真实改动与锁定范围（只读；--record 记为证据）")
    p.add_argument("--record", action="store_true", help="把这次对比记入账本")
    scope = add("scope", None, "范围").add_subparsers(dest="sub", metavar="<sub>")
    p = add("allow", cmd_scope_allow, "允许额外路径（需要理由）", scope)
    p.add_argument("pattern")
    p.add_argument("--reason", required=True)

    p = add("review", cmd_review, "记录评审结论（评审人≠负责人）；--file 批量")
    p.add_argument("task", nargs="?", help="任务 ID，或 @goal 表示目标级审计")
    p.add_argument("--by")
    p.add_argument("--verdict", choices=("pass", "fail"))
    p.add_argument("--note")
    p.add_argument("--self", dest="self_", action="store_true")
    p.add_argument("--file", help='JSON：[{"task": "T1", "by": "goal_reviewer", "verdict": "pass", "note": "..."}]')

    loop = add("loop", None, "轮次与监督器").add_subparsers(dest="sub", metavar="<sub>")
    p = add("decide", cmd_loop_decide, "手动结束本轮：continue|replan|stop（达成请用 gt finish）", loop)
    p.add_argument("decision", choices=("continue", "replan", "stop"))
    p.add_argument("--next")
    p.add_argument("--reason")
    p.add_argument("--outcome", choices=("achieved", "stopped", "blocked", "user_stopped"))
    p = add("next", supervisor.cmd_loop_next, "确定性判定本轮：achieved|continue|stalled|blocked|budget_exhausted（幂等记录）", loop)
    p.add_argument("--stop", action="store_true", help="非 continue 时把目标记为结束")
    p = add("run", supervisor.cmd_loop_run, "监督器：每轮一个无头会话，预算、截止、租约、判定都在进程外", loop)
    p.add_argument("--host", choices=("claude", "codex", "fake"), required=True)
    p.add_argument("--rounds", type=int)
    p.add_argument("--minutes", type=float)
    p.add_argument("--round-minutes", dest="round_minutes", type=float)
    p.add_argument("--check-minutes", dest="check_minutes", type=float)
    p.add_argument("--host-arg", dest="host_arg", action="append", help="透传给宿主命令的参数（可重复）")
    p.add_argument("--dry-run", action="store_true")
    p = add("probe", supervisor.cmd_loop_probe, "宿主能力报告：逐项说明 probe_passed / documented / unavailable", loop)
    p.add_argument("--host", choices=("claude", "codex", "fake"), required=True)
    p.add_argument("--host-arg", dest="host_arg", action="append")

    ctl = add("control", None, "控制面：预算、允许工具、提案（只有操作者能改）").add_subparsers(dest="sub", metavar="<sub>")
    p = add("set", control.cmd_control_set, "设置预算与允许工具（子会话不能执行）", ctl)
    p.add_argument("--rounds", type=int)
    p.add_argument("--minutes", type=float)
    p.add_argument("--round-minutes", dest="round_minutes", type=float)
    p.add_argument("--check-minutes", dest="check_minutes", type=float)
    p.add_argument("--grace-seconds", dest="grace_seconds", type=float)
    p.add_argument("--allow-tool", dest="allow_tool", action="append")
    p.add_argument("--note")
    add("show", control.cmd_control_show, "查看控制面、租约与提案", ctl)
    p = add("approve", control.cmd_control_approve, "批准提案（不自动生效，还需操作者执行对应命令）", ctl)
    p.add_argument("proposal", metavar="P")
    p.add_argument("--note")
    p = add("reject", control.cmd_control_reject, "拒绝提案", ctl)
    p.add_argument("proposal", metavar="P")
    p.add_argument("--note")
    p = add("propose", control.cmd_propose, "子会话或成员提交提案：scope|budget|auth|criteria|plan")
    p.add_argument("--kind", choices=control.PROPOSAL_KINDS, required=True)
    p.add_argument("--text", required=True)

    p = add("finish", cmd_finish, "收尾：补跑过期证据 → 共享判定 → 记录达成（幂等；不评审、不构建、不外部写入）")
    p.add_argument("--release", action="store_true", help="加发布前门禁")
    p.add_argument("--timeout", type=float)
    p.add_argument("--no-rerun", action="store_true", help="只判定，不补跑")
    add("status", cmd_status, "看板（任务 / Context / P-D-C-A）")
    p = add("report", cmd_report, "汇报：结果、关键证据、未完成事项（--format six 为六字段）")
    p.add_argument("--summary", help="本轮摘要；- 表示从 stdin 读取")
    p.add_argument("--format", choices=("brief", "six"))
    p.add_argument("--task")
    p.add_argument("--members")
    p.add_argument("--next")
    p = add("resume", cmd_resume, "续接包：已解决、试过并放弃、用户决定与约束、当前进度、未决事项、难以重建的细节（只读；--readback 先对账外部操作）")
    p.add_argument("--max-bytes", type=int, default=12000)
    p.add_argument("--readback", action="store_true", help="先运行未结外部操作登记的回读命令并记录结论")
    p.add_argument("--timeout", type=float)

    oper = add("operation", None, "外部操作：先登记意图，执行后回读确认").add_subparsers(dest="sub", metavar="<sub>")
    p = add("prepare", operations.cmd_prepare, "登记一次外部操作的意图（需要 gt auth grant 覆盖该动作）", oper)
    p.add_argument("--action", choices=ACTIONS, required=True)
    p.add_argument("--target", required=True, help="精确目标：仓库、tag、Release、环境")
    p.add_argument("--expect", help="期望的版本或摘要")
    p.add_argument("--idempotent", choices=operations.IDEMPOTENCY, default="once")
    p.add_argument("--readback", help="回读命令（exit 0 = 目标存在且符合预期；1 = 不存在；其他 = 回读失败）")
    p.add_argument("--required", action="store_true", help="目标达成前必须 confirmed")
    p.add_argument("--note")
    p = add("dispatch", operations.cmd_dispatch, "执行已登记的操作：gt operation dispatch OP -- <命令>", oper)
    p.add_argument("operation", metavar="OP")
    p.add_argument("--timeout", type=float)
    p = add("confirm", operations.cmd_confirm, "回读确认已执行的操作：gt operation confirm OP [-- <回读命令>]", oper)
    p.add_argument("operation", metavar="OP")
    p.add_argument("--timeout", type=float)
    p = add("reconcile", operations.cmd_reconcile, "结果不明或中断后按意图回读对账，不重放：gt operation reconcile OP [-- <回读命令>]", oper)
    p.add_argument("operation", metavar="OP")
    p.add_argument("--timeout", type=float)
    add("list", operations.cmd_list, "列出外部操作及状态", oper)
    p = add("reflect", cmd_reflect, "记录反思（最多 3 条改进）")
    p.add_argument("observation")
    p.add_argument("--action", action="append")
    p.add_argument("--kind", choices=("round", "problem", "stop"), default="problem")
    p = add("check", cmd_check, "只读完成判定（未达成退出码 1）")
    p.add_argument("--release", action="store_true")
    add("doctor", cmd_doctor, "环境预检（可选）")
    ctxp = add("context", None, "Context 表").add_subparsers(dest="sub", metavar="<sub>")
    p = add("add", cmd_context_add, "登记实际用到的规则/知识/代码库/工具", ctxp)
    p.add_argument("kind", choices=("rule", "knowledge", "code", "tool"))
    p.add_argument("label")
    p.add_argument("--link")
    mem = add("memory", None, "项目记忆").add_subparsers(dest="sub", metavar="<sub>")
    p = add("add", cmd_memory_add, "追加到 memory.md", mem)
    p.add_argument("text")
    p.add_argument("--section", default="决策", choices=("用户设置", "配置与环境", "决策", "上下文摘要", "待办"))
    p = add("verify", cmd_verify, "校验账本哈希链、链头与证据日志")
    p.add_argument("--reset-head", action="store_true", help="确认原因后，在账本里记下链头重置（需要 --reason）")
    p.add_argument("--reason")
    cfg = add("config", None, "项目约定（.goal-teams/config.json）").add_subparsers(dest="sub", metavar="<sub>")
    add("show", cmd_config_show, "查看项目约定", cfg)
    p = add("set", cmd_config_set, "设置项目约定：%s" % ", ".join(CONFIG_KEYS), cfg)
    p.add_argument("key", choices=tuple(CONFIG_KEYS))
    p.add_argument("value")
    graph = add("graph", None, "冻结任务图与细粒度预算").add_subparsers(dest="sub", metavar="<sub>")
    add("status", cmd_graph_status, "只读查询图、预算与阻塞闭包", graph)
    p = add("finding", cmd_graph_finding, "核对真实复现、范围、消费者与预算后记录finding准入", graph)
    p.add_argument("file")
    p = add("recover-run", run_recovery.cmd_recover_run, "操作员确认命令已停止并记录中断；仍需真实重跑")
    p.add_argument("started", type=int)
    p.add_argument("--reason", required=True)
    p.add_argument("--confirm-stopped", action="store_true")
    add("version", cmd_version, "版本")
    hk = add("hook", None, "宿主钩子（内部使用）").add_subparsers(dest="sub", metavar="<sub>")
    add("stop", cmd_hook_stop, "Claude Code Stop 钩子", hk)
    return parser


# What a supervised sub-session (GT_SUBSESSION=1) may run: do the work, record evidence, read state, propose.
SUBSESSION_ALLOWED = {cmd_tdd_red, cmd_tdd_green, cmd_run, cmd_rerun, cmd_diff, cmd_status, cmd_task_list, cmd_task_packet,
                      cmd_task_start, cmd_task_done, cmd_task_block, cmd_plan_show, cmd_check, cmd_resume, cmd_verify,
                      cmd_memory_add, cmd_context_add, cmd_version, cmd_route, cmd_auth_show, cmd_auth_check,
                      control.cmd_propose, control.cmd_control_show, operations.cmd_list, cmd_graph_status}
SUBSESSION_NAMES = {"tdd red/green", "run", "rerun", "diff", "status", "task list/packet/start/done/block", "plan show",
                    "check", "resume", "verify", "memory add", "context add", "propose"}


def _rewrite_argv(argv: List[str]) -> List[str]:
    """``gt goal accept ...`` is a sub-command in spirit; argparse sees the title positional first."""
    for index, token in enumerate(argv):
        if token.startswith("-"):
            continue
        if token == "goal" and index + 1 < len(argv) and argv[index + 1] == "accept":
            return argv[:index] + ["goal-accept"] + argv[index + 2:]
        break
    return argv


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    command: List[str] = []
    if "--" in argv:
        index = argv.index("--")
        argv, command = argv[:index], argv[index + 1:]
    parser = build_parser()
    args = parser.parse_args(_rewrite_argv(argv))
    args.cmd = command
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT.usage
    if command and handler not in (cmd_tdd_red, cmd_tdd_green, cmd_run, operations.cmd_dispatch, operations.cmd_confirm,
                                   operations.cmd_reconcile):
        print("gt: 这个命令不接受 -- 之后的参数", file=sys.stderr)
        return EXIT.usage
    if handler is cmd_hook_stop:
        try:
            return hook.stop()
        except Exception:  # never break the host's stop flow
            return 0
    if control.in_subsession() and handler not in SUBSESSION_ALLOWED and not (handler is cmd_goal and args.show):
        print("gt: 监督器的子会话只能做工作和记录证据（%s）；评审、验收、收尾、扩范围、改计划、撤销失败、外部操作等由操作者决定，"
              "需要时 gt propose。" % ", ".join(sorted(SUBSESSION_NAMES)), file=sys.stderr)
        return EXIT.blocked
    try:
        ctx = Ctx(args)
        return handler(ctx)
    except GTError as exc:
        print("gt: %s" % exc.message, file=sys.stderr)
        if exc.hint:
            print("    %s" % exc.hint, file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        return 130
