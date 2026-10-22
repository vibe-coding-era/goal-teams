"""Evidence commands: TDD Red/Green, check runs, re-runs, diff against scope, reviews."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import checks, gitinfo, runner
from .context import Ctx, _check_member, _cwd_rel, _set_state, ensure_direct_state, out
from .models import RED_INVALID, RED_OBSERVED, RED_PAIRABLE, RED_VERIFIED
from .state import State, Task
from .util import EXIT, GTError, sha256_file, sha256_text

# Exit codes that mean the command never ran: such a receipt is kept but is not a test result.
NOT_RUN = {126: "命令不可执行", 127: "命令不存在"}


def _record_command(ctx: Ctx, event_type: str,
                    build: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
                    argv: List[str], timeout: Optional[float], cwd: Optional[Path] = None,
                    task: Optional[Task] = None, exclude: List[str] = (), extra_artifacts: List[str] = (),
                    outputs: List[str] = (), kind: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Run ``argv`` and append a receipt whose fields come from ``build(result, facts)``.

    A ``run.started`` event goes into the ledger before the command runs (so an interrupted command
    stays visible), bound to the goal, the plan revision and the task's spec digest. When the receipt
    lands, those bindings are re-checked under the lock: a receipt whose task spec changed meanwhile,
    or whose goal was closed, is recorded with ``late`` and kept apart from the current acceptance
    (AC12). ``facts`` are the digests of the tree the command ran against (taken before it ran),
    leaving out the artifacts and outputs this run declares.
    """
    from . import graph_contract, graph_budget, render
    state = graph_contract.ensure_frozen(ctx) if task is not None else ctx.state()
    goal_id = state.goal.get("id") if state.goal else None
    spec_at_start = checks.spec_digest(task) if task is not None else None
    admission = {}
    graph_binding = None
    if task is not None:
        graph_contract.require_ready(state, task.id)
        packet = render.packet(state, task, "gt", str(ctx.project.root))
        context = graph_contract.context_receipt(state, task.id, packet)
        graph_binding = state.plan["graph"]["sha256"]
        prior = any(r.get("task") == task.id for r in state.receipts.values())
        charge_kind = "implementation" if event_type == "tdd.red" or not prior else "revalidation"
    def admit(current):
        ctx.expect_same_goal(goal_id)(current)
        if task is not None:
            checks.annotate(ctx.project, current)
            graph_contract.require_ready(current, task.id)
            if current.plan["graph"]["sha256"] != graph_binding or checks.spec_digest(current.tasks[task.id]) != spec_at_start:
                raise GTError("命令准入时任务图发生变化。", code=EXIT.conflict)
            graph_budget.charge(current, task.id, charge_kind, "run:pending")
        admission["state"] = current
    def prepare_started(seq, prev):
        data = {"task": task.id if task is not None else None, "kind": kind or event_type, "cmd": list(argv), "goal": goal_id,
                "plan_revision": state.plan.get("revision"), "spec_digest": spec_at_start, "tree": ctx.project.tree_label(),
                "pid": os.getpid(), "name": getattr(ctx.args, "name", None)}
        if task is not None:
            data["graph_charge"] = graph_budget.charge(admission["state"], task.id, charge_kind, "run:%d" % seq)
            data["graph_context"] = context
        return data, lambda: None
    started = ctx.append("run.started", None, prepare_started, expect=admit)
    pending = runner.tmp_log(ctx.project.evidence_dir)
    cwd = (cwd or Path.cwd()).resolve()
    work = ctx.project.work_tree
    head = gitinfo.head(work) if gitinfo.is_repo(work) else None
    before = gitinfo.tree_ids(work)
    result = runner.execute(argv, cwd, pending, timeout)
    declared = list(extra_artifacts) + list(outputs)
    changed = checks.undeclared_changes(ctx.project, state, before[0], gitinfo.tree_ids(work)[0], declared)
    facts = checks.receipt_facts(ctx.project, state, task, exclude, declared, before)
    holder: Dict[str, Any] = {}
    late: Dict[str, str] = {}

    def expect(current: State) -> None:
        """Under the lock: the goal may have moved on while the command ran. Never refuse — the
        receipt is kept either way — but mark what it can no longer vouch for."""
        now_goal = current.goal.get("id") if current.goal else None
        if goal_id is not None and now_goal != goal_id:
            return  # the reducer files it under the replaced goal
        if current.goal is not None and current.goal.get("status") != "active":
            late["reason"] = "goal_closed"
        elif task is not None:
            now_task = current.tasks.get(task.id)
            if now_task is None or not now_task.active:
                late["reason"] = "task_gone"
            elif checks.spec_digest(now_task) != spec_at_start:
                late["reason"] = "spec_changed"
            elif (current.plan.get("graph") or {}).get("sha256") != graph_binding:
                late["reason"] = "spec_changed"

    def prepare(seq: int, prev: str) -> Tuple[Dict[str, Any], Callable[[], None]]:
        receipt_id = "R%d" % seq
        name = "%s.log" % receipt_id
        final = ctx.project.evidence_dir / name
        if final.exists():
            _keep_orphan(ctx, final)
        data = {"id": receipt_id, "goal": goal_id, "cwd": _cwd_rel(ctx, cwd), "tree": ctx.project.tree_label(),
                "head": head, "log": ".goal-teams/evidence/%s" % name, "started": started["seq"],
                "plan_revision": state.plan.get("revision")}
        if task is not None:
            data["graph_digest"] = graph_binding
            data["graph_charge_sha256"] = started["data"]["graph_charge"]["sha256"]
        data.update({k: v for k, v in result.items() if not k.startswith("_")})
        if outputs:
            data["outputs"] = list(outputs)
        data.update(build(result, facts))
        if late.get("reason"):
            data["late"] = late["reason"]
        holder.update(data)
        return data, lambda: os.replace(pending, final)

    try:
        ctx.append(event_type, None, prepare, expect=expect)
    finally:
        if pending.exists():
            pending.unlink()
    now = ctx.state(refresh=True).goal
    if goal_id is not None and (now is None or now.get("id") != goal_id):
        print("gt: ⚠ 目标在命令运行期间被替换：这条记录属于 %s，已保存在账本里，但不计入当前目标。" % goal_id,
              file=sys.stderr)
    elif holder.get("late"):
        why = {"goal_closed": "目标已在命令运行期间结束", "spec_changed": "任务规格（验收、验证人、依赖、范围）在命令运行期间变化",
               "task_gone": "任务在命令运行期间被取消"}[holder["late"]]
        print("gt: ⚠ %s：这条记录（%s）已保存，但不计入当前验收（late=%s）。需要的话在当前规格上重跑。" % (
            why, holder["id"], holder["late"]), file=sys.stderr)
    if changed:
        print("gt: ⚠ 命令改写了未声明的文件 %s：它们算源码，这条记录会立刻过期。只有没人读取的测试报告、覆盖率"
              "才能用 --output 声明（或加进 .gitignore）；代码或测试读取的生成文件，应该由测试命令自己生成，"
              "或提交进仓库。" % ", ".join(changed[:6]), file=sys.stderr)
    return holder, result


def _keep_orphan(ctx: Ctx, path: Path) -> None:
    """A log for this seq already exists, so it belongs to another history (a branch switch, a
    restored ledger, a recorded head reset). Keep it under evidence/orphans/ instead of overwriting."""
    folder = ctx.project.evidence_dir / "orphans"
    folder.mkdir(exist_ok=True)
    number = 1
    while (folder / ("%s.%d.log" % (path.stem, number))).exists():
        number += 1
    target = folder / ("%s.%d.log" % (path.stem, number))
    os.replace(path, target)
    print("gt: %s 不属于当前账本，已移到 .goal-teams/evidence/orphans/%s" % (path.name, target.name), file=sys.stderr)


def _test_identity(ctx: Ctx, paths: List[str]) -> Tuple[str, List[Dict[str, str]]]:
    rels = []
    for raw in paths:
        full = (Path.cwd() / raw).resolve()
        if not full.is_file():
            raise GTError("测试文件不存在：%s" % raw)
        try:
            rels.append(full.relative_to(ctx.project.work_tree).as_posix())
        except ValueError:
            raise GTError("测试文件不在项目内：%s" % raw)
    return gitinfo.files_digest(ctx.project.work_tree, rels)


def _auto_start(ctx: Ctx, task: Task) -> None:
    task = ctx.task(task.id)
    if task.state == "pending":
        _set_state(ctx, task, "in_progress", member=ctx.actor if ctx.actor != "lead" else task.owner,
                   note="自动开始（首次记录 TDD 证据）")


INVALID_RED = dict(NOT_RUN)
INVALID_RED[124] = "命令超时"


def cmd_tdd_red(ctx: Ctx) -> int:
    runner.check_pattern(ctx.args.expect)
    if not ctx.args.test:
        raise GTError("缺少 --test：Red/Green 需要绑定具体测试文件。",
                      hint="gt tdd red %s --test tests/test_x.py --expect \"AssertionError\" -- <测试命令>" % ctx.args.task)
    if not ctx.args.cmd:
        raise GTError("缺少测试命令。", hint="gt tdd red %s --test <文件> --expect \"...\" -- <测试命令>" % ctx.args.task)
    ensure_direct_state(ctx, ctx.args.task, tdd=True, title="TDD：%s" % ", ".join(ctx.args.test))
    state = ctx.active_goal_required()
    task = ctx.task(ctx.args.task)
    if task.state in ("accepted", "cancelled"):
        raise GTError("%s 已经是 %s。" % (task.id, task.state))
    test_digest, test_files = _test_identity(ctx, ctx.args.test)
    paths = [f["path"] for f in test_files]
    outputs = _output_rels(ctx, ctx.args.output or [], Path.cwd().resolve())

    def build(result: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
        matched = runner.expect_matches(result["_output"], ctx.args.expect)
        if result["timed_out"] or result["exit_code"] in INVALID_RED:
            outcome = RED_INVALID
        elif result["exit_code"] == 0:
            outcome = "red_unexpected_pass"
        elif matched is False:
            outcome = "red_expect_mismatch"
        elif matched is True:
            outcome = RED_VERIFIED
        else:
            outcome = RED_OBSERVED
        return dict(facts, task=task.id, test_files=test_files, test_digest=test_digest,
                    expect=ctx.args.expect, expect_matched=matched, outcome=outcome)

    receipt, result = _record_command(ctx, "tdd.red", build, ctx.args.cmd, ctx.args.timeout, task=task,
                                      exclude=paths, outputs=outputs)
    ok = receipt["outcome"] in (RED_VERIFIED, RED_OBSERVED) and not receipt.get("late")
    if ok:
        _auto_start(ctx, task)
    message = {
        RED_VERIFIED: "Red 成立并已核对失败原因（red_verified）",
        RED_OBSERVED: "Red 成立，失败原因未核对（red_observed）：可以继续开发，收尾前 gt tdd confirm %s --expect \"<失败特征>\"" % receipt["id"],
        "red_unexpected_pass": "Red 不成立：测试直接通过了——先写出能失败的测试",
        "red_expect_mismatch": "Red 不成立：失败原因与 --expect 不符（可能是环境/语法错误）",
        RED_INVALID: "Red 不成立：%s，这不是测试失败" % INVALID_RED.get(receipt["exit_code"], "命令超时"),
    }[receipt["outcome"]]
    runner.print_tail(result, "%s · %s · exit %d · 日志 %s" % (receipt["id"], message, receipt["exit_code"], receipt["log"]))
    return EXIT.ok if ok else EXIT.unverified


def cmd_tdd_confirm(ctx: Ctx) -> int:
    """Check the failure reason of an observed Red against its original log; never re-runs anything."""
    state = ctx.active_goal_required()
    receipt = state.receipts.get(ctx.args.receipt)
    if receipt is None or receipt.get("type") != "tdd.red":
        raise GTError("没有 Red 回执 %s。" % ctx.args.receipt)
    log = ctx.project.root / (receipt.get("log") or "")
    if not receipt.get("log") or not log.is_file():
        raise GTError("%s 的日志不存在了（%s），无法核对。" % (receipt["id"], receipt.get("log")), code=EXIT.unverified)
    if sha256_file(log) != receipt.get("log_sha256"):
        raise GTError("%s 的日志在记录后被修改，不能据此确认；原始日志的 sha256 记在账本里。" % receipt["id"],
                      code=EXIT.unverified)
    if receipt.get("outcome") == RED_VERIFIED:
        raise GTError("%s 已经是 red_verified，不需要再确认。" % receipt["id"])
    if receipt.get("outcome") not in RED_PAIRABLE and receipt.get("outcome") != "red_expect_mismatch":
        raise GTError("%s 的结果是 %s：不是可核对的失败（命令没跑起来、超时或测试直接通过），不能确认。" % (
            receipt["id"], receipt.get("outcome")))
    runner.check_pattern(ctx.args.expect)
    if not ctx.args.expect:
        raise GTError("缺少 --expect：写出失败日志里应出现的失败特征（如 AssertionError 或期望值）。")
    text = log.read_text(encoding="utf-8", errors="replace")
    body = text.split("\n\n", 1)[1] if "\n\n" in text else text
    own = "\n".join(line for line in body.splitlines() if not line.startswith(("# exit:", "[gt] ")))
    matched = bool(runner.expect_matches(own, ctx.args.expect))
    data = {"red": receipt["id"], "task": receipt.get("task"), "expect": ctx.args.expect, "matched": matched,
            "note": ctx.args.note, "log_sha256": receipt.get("log_sha256")}
    ctx.append("tdd.confirm", data, expect=ctx.expect_same_goal(ctx.goal_id()))
    if matched:
        out(ctx, "%s 已确认为 red_verified：失败日志匹配 %r%s" % (
            receipt["id"], ctx.args.expect, "（%s）" % ctx.args.note if ctx.args.note else ""), data)
        return EXIT.ok
    out(ctx, "%s 未确认：失败日志不匹配 %r（仍是 %s；检查失败原因是否真是预期行为）" % (
        receipt["id"], ctx.args.expect, receipt.get("outcome")), data)
    return EXIT.unverified


def _run_dir(ctx: Ctx, receipt: Dict[str, Any]) -> Path:
    """Where a receipt's command ran, mapped into the current work tree."""
    recorded = receipt.get("cwd") or "."
    path = Path(recorded) if os.path.isabs(recorded) else ctx.project.work_tree / recorded
    if not path.is_dir():
        raise GTError("%s 的运行目录不存在了：%s" % (receipt["id"], recorded))
    return path


def _green(ctx: Ctx, state: State, task: Task, timeout: Optional[float]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    red = state.latest_red(task.id)
    if red is None:
        raise GTError("%s 还没有成立的 Red。" % task.id, hint="先 gt tdd red %s --test <文件> -- <命令>" % task.id)
    run_dir = _run_dir(ctx, red)
    paths = [f["path"] for f in red.get("test_files", [])]
    test_digest, test_files = gitinfo.files_digest(ctx.project.work_tree, paths)

    def build(result: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
        if test_digest != red.get("test_digest"):
            outcome = "green_test_changed"
        elif facts["source_digest"] == red.get("source_digest"):
            outcome = "green_source_unchanged"
        elif red.get("impl_digest") and facts.get("impl_digest") == red.get("impl_digest"):
            outcome = "green_scope_unchanged"
        elif result["timed_out"] or result["exit_code"] in NOT_RUN:
            outcome = "green_not_run"
        elif result["exit_code"] == 0:
            outcome = "green_ok"
        else:
            outcome = "green_failed"
        return dict(facts, task=task.id, red=red["id"], test_files=test_files, test_digest=test_digest,
                    outcome=outcome)

    return _record_command(ctx, "tdd.green", build, list(red.get("cmd") or []), timeout, cwd=run_dir,
                           task=task, exclude=paths, outputs=list(red.get("outputs") or []))


GREEN_TEXT = {
    "green_ok": "Green 成立：同一测试在实现后通过",
    "green_failed": "Green 未通过：继续实现，或确认测试本身",
    "green_not_run": "Green 没有运行起来（命令不存在、不可执行或超时）",
    "green_test_changed": "测试文件在 Red 之后被修改：这是新的测试用例，请重新 gt tdd red",
    "green_source_unchanged": "源码内容与 Red 时相同：没有实现就不算 Green（提交、暂存不算改动）",
    "green_scope_unchanged": "本任务范围内的实现与 Red 时相同：测试、测试数据、测试任务的范围和其他任务的文件都不算实现",
}


def cmd_tdd_green(ctx: Ctx) -> int:
    state = ctx.active_goal_required()
    task = ctx.task(ctx.args.task)
    red = state.latest_red(task.id)
    if red is not None and ctx.args.cmd and list(ctx.args.cmd) != list(red.get("cmd") or []):
        raise GTError("Green 必须重跑 Red（%s）的同一条命令：%s" % (red["id"], " ".join(red.get("cmd") or [])),
                      hint="省略 -- 之后的部分即可自动复用；要换测试命令就重新做 Red。")
    receipt, result = _green(ctx, state, task, ctx.args.timeout)
    runner.print_tail(result, "%s · %s · exit %d · 日志 %s" % (
        receipt["id"], GREEN_TEXT[receipt["outcome"]], receipt["exit_code"], receipt["log"]))
    return EXIT.ok if receipt["outcome"] == "green_ok" and not receipt.get("late") else EXIT.unverified


def _artifacts(ctx: Ctx, paths: List[str], cwd: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Name, size and SHA-256 of each produced artifact (GT-REL-BUILD); missing ones are reported."""
    found: List[Dict[str, Any]] = []
    missing: List[str] = []
    for rel in _artifact_rels(ctx, paths, cwd):
        full = ctx.project.work_tree / rel
        if not full.is_file():
            missing.append(rel)
            continue
        found.append({"path": rel, "size": full.stat().st_size, "sha256": sha256_file(full)})
    return found, missing


def _artifact_rels(ctx: Ctx, paths: List[str], cwd: Path, flag: str = "--artifact") -> List[str]:
    """Build outputs only: inside the project, not tracked by git, outside code and test scopes."""
    if not paths:
        return []
    work = ctx.project.work_tree
    tracked = set(gitinfo.tracked(work)) if gitinfo.is_repo(work) else set()
    state = ctx.state()
    code = checks.code_scopes(state)
    rels = []
    for raw in paths:
        full = (cwd / raw).resolve()
        try:
            rel = full.relative_to(work).as_posix()
        except ValueError:
            raise GTError("%s 必须在项目内：%s" % (flag, raw))
        if rel in tracked:
            raise GTError("%s %s 是 git 跟踪的文件：只能声明命令生成的文件。" % (flag, rel))
        baseline = ((state.goal or {}).get("baseline") or {}).get("head")
        if gitinfo.paths_in_commit(work, baseline, [rel]):
            raise GTError("%s %s 在目标开始时就是项目里的文件：只能声明命令新生成的文件。" % (flag, rel))
        if code and checks.matches_any(rel, code):
            raise GTError("%s %s 在代码或测试任务的范围里：生成的文件应写到输出目录（如 dist/、reports/）。" % (flag, rel))
        rels.append(rel)
    return rels


SOURCE_SUFFIXES = (".py", ".pyi", ".pyx", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
                   ".kt", ".kts", ".scala", ".rb", ".php", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs",
                   ".swift", ".m", ".mm", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".lua", ".pl", ".pm", ".r",
                   ".dart", ".ex", ".exs", ".erl", ".hs", ".ml", ".clj", ".groovy", ".vue", ".svelte",
                   ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env")


def _output_rels(ctx: Ctx, paths: List[str], cwd: Path) -> List[str]:
    """Declared command outputs (test reports, coverage): like build artifacts, and never source code
    or configuration, so code cannot depend on them."""
    rels = _artifact_rels(ctx, paths, cwd, "--output")
    for rel in rels:
        if rel.lower().endswith(SOURCE_SUFFIXES):
            raise GTError("--output %s 看起来是源码或配置：命令输出不能是代码会读取的文件。" % rel)
    return rels


def _run(ctx: Ctx, state: State, task_id: Optional[str], kind: str, name: Optional[str], argv: List[str],
         timeout: Optional[float], cwd: Path, artifacts: List[str],
         outputs: List[str] = (), extra: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    task = state.tasks.get(task_id) if task_id else None
    declared = _artifact_rels(ctx, artifacts, cwd)
    outs = _output_rels(ctx, list(outputs), cwd)
    exclude = checks.red_tests(state, task) if task is not None else []

    last_build = checks.latest_build(state) if kind == "release" else None

    def build(result: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(facts, task=task_id, kind=kind, name=name, passed=result["exit_code"] == 0, **(extra or {}))
        if last_build is not None:  # a readback vouches for exactly the assets that were built
            data["build"] = last_build["id"]
            data["assets_digest"] = checks.asset_set_digest(last_build)
        if result["exit_code"] in NOT_RUN:
            data["invalid"] = True
        if artifacts:
            found, missing = _artifacts(ctx, artifacts, cwd)
            data["artifacts"] = found
            if missing:
                data["missing_artifacts"] = missing
                data["passed"] = False
        return data

    return _record_command(ctx, "run", build, argv, timeout, cwd=cwd, task=task, exclude=exclude,
                           extra_artifacts=declared, outputs=outs, kind=kind)


def _run_label(receipt: Dict[str, Any]) -> str:
    if receipt.get("invalid"):
        return "%s · %s 没有运行起来（%s）· 不算检查结果 · 日志 %s" % (
            receipt["id"], receipt["kind"], NOT_RUN.get(receipt["exit_code"], "exit %d" % receipt["exit_code"]),
            receipt["log"])
    return "%s · %s %s · exit %d · 日志 %s" % (receipt["id"], receipt["kind"],
                                              "通过" if receipt["passed"] else "失败", receipt["exit_code"],
                                              receipt["log"])


def cmd_run(ctx: Ctx) -> int:
    args = ctx.args
    from .control import in_subsession
    if in_subsession() and args.kind in ("release", "build", "security", "regression", "install"):
        raise GTError("发布类检查（%s）由操作者记录，子会话不能执行。" % args.kind, code=EXIT.blocked)
    if args.kind == "acceptance":
        raise GTError("完成标准的 --check 由 gt finish / gt rerun 运行；不能手工记录 acceptance。",
                      hint="没有命令的完成标准用 gt goal accept；要改命令，向操作者提议修改完成标准。")
    task_id = None if args.task in ("-", "@goal") else args.task
    ensure_direct_state(ctx, task_id, title="检查：%s" % args.kind)
    state = ctx.active_goal_required()
    task = ctx.task(task_id) if task_id is not None else None
    if args.manual:
        if args.result not in ("pass", "fail"):
            raise GTError("--manual 需要 --result pass|fail 和 --note。")
        if not args.note:
            raise GTError("--manual 需要 --note 说明怎么验证的。")
        if args.cmd:
            raise GTError("--manual 不运行命令；去掉 -- 之后的部分。")
        if args.artifact:
            raise GTError("--artifact 只用于运行命令的检查（构建产物）。")
        if args.evidence and not re.match(r"^https?://", args.evidence):
            full = (Path.cwd() / args.evidence).resolve()
            try:
                full.relative_to(ctx.project.work_tree)
            except ValueError:
                raise GTError("--evidence 必须是项目内的文件或 http(s) 链接：%s" % args.evidence)
            if not full.exists():
                raise GTError("--evidence 指向的文件不存在：%s" % args.evidence)
        facts = checks.receipt_facts(ctx.project, state, task)
        last_build = checks.latest_build(state) if args.kind == "release" else None
        holder: Dict[str, Any] = {}

        def prepare(seq: int, prev: str) -> Tuple[Dict[str, Any], Callable[[], None]]:
            data = dict(facts, id="R%d" % seq, goal=ctx.goal_id(), task=task_id, kind=args.kind, name=args.name,
                        manual=True, passed=args.result == "pass", note=args.note, evidence=args.evidence,
                        tree=ctx.project.tree_label())
            if last_build is not None:
                data["build"] = last_build["id"]
                data["assets_digest"] = checks.asset_set_digest(last_build)
            holder.update(data)
            return data, lambda: None

        ctx.append("run", None, prepare)
        out(ctx, "%s · 人工证据（%s）：%s" % (holder["id"], args.result, args.note), holder)
        return 0 if args.result == "pass" else 1
    if not args.cmd:
        raise GTError("缺少要运行的命令。", hint="gt run %s --kind %s -- <命令>；人工核对用 --manual --result --note" % (
            args.task, args.kind))
    receipt, result = _run(ctx, state, task_id, args.kind, args.name, args.cmd, args.timeout,
                           Path.cwd().resolve(), args.artifact or [], args.output or [])
    lines = []
    for item in receipt.get("artifacts") or []:
        lines.append("产物 %s · %d 字节 · sha256 %s" % (item["path"], item["size"], item["sha256"]))
    for path in receipt.get("missing_artifacts") or []:
        lines.append("✘ 产物不存在：%s" % path)
    runner.print_tail(result, "\n".join(lines + [_run_label(receipt)]))
    if receipt.get("invalid"):
        return EXIT.usage
    if receipt.get("late"):
        return EXIT.unverified
    return EXIT.ok if receipt["passed"] else EXIT.unverified


def repair_evidence(ctx: Ctx, state: State, result: Any, timeout: Optional[float],
                    tasks: Optional[List[str]] = None) -> List[str]:
    """Re-run, on the current code, what is safe to repeat: the last passing Green/affected command of
    each code task that lacks a pass on the current code, and the criteria's --check commands that
    have no current pass. Never reviews, builds or external writes. Shared by gt rerun and gt finish."""
    lines: List[str] = []
    live = checks.Live(ctx.project, state)
    wanted = list(tasks or [])
    if not wanted:
        wanted = [t.id for t in state.active_tasks()
                  if t.kind == "code" and t.state in ("in_progress", "done", "accepted")
                  and any(checks.is_pass(r) for r in state.receipts_of(t.id))
                  and checks.needs_own_evidence(live, state, t)
                  and checks.fresh_pass(live, state, t) is None]
    for task_id in wanted:
        task = ctx.task(task_id)
        state = ctx.state(refresh=True)
        last = next((r for r in reversed(state.receipts_of(task.id)) if checks.is_pass(r)), None)
        if last is None:
            lines.append("✘ %s：没有可以重跑的通过记录（先 gt tdd red/green 或 gt run %s --kind affected）" % (
                task.id, task.id))
            continue
        if last["type"] == "tdd.green":
            receipt, _ = _green(ctx, state, task, timeout)
            ok = receipt["outcome"] == "green_ok"
            lines.append("%s %s：%s（%s）" % ("✔" if ok else "✘", task.id, GREEN_TEXT[receipt["outcome"]], receipt["id"]))
        else:
            receipt, _ = _run(ctx, state, task.id, "affected", last.get("name"), list(last.get("cmd") or []),
                              timeout, _run_dir(ctx, last), [], list(last.get("outputs") or []))
            ok = bool(receipt["passed"])
            lines.append("%s %s：%s" % ("✔" if ok else "✘", task.id, _run_label(receipt)))
    rows = getattr(result, "criteria", None)
    if rows is None:
        rows = [dict(c, status=_criterion_state(ctx, c)) for c in (state.goal or {}).get("criteria", [])]
    for row in rows:
        if row.get("check") and row.get("status") in ("not_run", "stale"):
            state = ctx.state(refresh=True)
            from .completion import item_digest
            receipt, _ = _run(ctx, state, None, "acceptance", row["id"], list(row["check"]), timeout,
                              ctx.project.work_tree, [], [], extra={"criterion_digest": item_digest(row.get("text") or "")})
            lines.append("%s %s：--check %s" % ("✔" if receipt["passed"] else "✘", row["id"], _run_label(receipt)))
    return lines


def _criterion_state(ctx: Ctx, criterion: Dict[str, Any]) -> str:
    from .completion import criterion_status
    snapshot = checks.collect(ctx.project, ctx.state(refresh=True))
    return criterion_status(snapshot, criterion)[0]


def cmd_rerun(ctx: Ctx) -> int:
    """Re-run, on the current code, the last passing Green/affected command of each task and the
    criteria's --check commands that lack a current pass."""
    state = ctx.active_goal_required()
    lines = repair_evidence(ctx, state, None, ctx.args.timeout, ctx.args.tasks)
    if not lines:
        out(ctx, "所有代码任务和完成标准都有在当前代码上通过的记录，不需要重跑。", {"rerun": []})
        return EXIT.ok
    failed = sum(1 for line in lines if line.startswith("✘"))
    out(ctx, "\n".join(lines), {"rerun": lines, "failed": failed})
    return EXIT.unverified if failed else EXIT.ok


def cmd_retire(ctx: Ctx) -> int:
    """Withdraw a failed check that was a mistake (wrong command, wrong path); the reason is reported."""
    state = ctx.active_goal_required()
    receipt = state.receipts.get(ctx.args.receipt)
    if receipt is None or receipt.get("type") != "run":
        raise GTError("没有检查回执 %s（只能撤销 gt run 的失败）。" % ctx.args.receipt)
    if receipt.get("passed"):
        raise GTError("%s 是通过的检查，不需要撤销。" % receipt["id"])
    if receipt["id"] in state.retired:
        raise GTError("%s 已经撤销过。" % receipt["id"])
    if not ctx.args.reason or len(ctx.args.reason.strip()) < 4:
        raise GTError("撤销需要 --reason 说明为什么这次失败不算（会写进 gt check 和汇报）。")
    ctx.append("retire", {"id": receipt["id"], "reason": ctx.args.reason.strip()})
    out(ctx, "已撤销 %s：%s（gt check 和 gt report 会列出这次撤销）" % (receipt["id"], ctx.args.reason.strip()))
    return 0


def cmd_diff(ctx: Ctx) -> int:
    state = ctx.active_goal_required()
    diff = checks.live_diff(ctx.project, state)
    if not diff.get("available"):
        out(ctx, "gt diff 不可用：%s" % diff.get("reason"), diff)
        return 0
    payload = {k: v for k, v in diff.items() if k != "available"}
    payload["changed"] = payload["changed"][:500]
    payload["untracked"] = payload["untracked"][:500]
    payload["digest"] = sha256_text(json.dumps(diff, sort_keys=True))
    holder: Dict[str, Any] = dict(payload, id="（未记录）")
    if ctx.args.record:
        def prepare(seq: int, prev: str) -> Tuple[Dict[str, Any], Callable[[], None]]:
            data = dict(payload, id="D%d" % seq, task=None)
            holder.update(data)
            return data, lambda: None

        ctx.append("diff", None, prepare)
    lines = ["%s · 基线 %s → 当前：%d 个文件有变化（含未跟踪 %d）" % (
        holder["id"], (diff["baseline"] or "空仓库")[:12], diff["files"], len(diff["untracked"]))]
    for item in diff["changed"][:40]:
        lines.append("  %s %s" % (item["status"], item["path"]))
    for path in diff["untracked"][:20]:
        lines.append("  ? %s" % path)
    if diff["artifacts"]:
        lines.append("  构建产物（--artifact 声明，不算源码）：%s" % ", ".join(diff["artifacts"][:10]))
    if diff["hidden"]:
        lines.append("✘ %d 个文件被设为 assume-unchanged/skip-worktree，gt 看不到它们的改动：%s" % (
            len(diff["hidden"]), ", ".join(diff["hidden"][:10])))
        lines.append("  恢复：git update-index --no-assume-unchanged / --no-skip-worktree <文件>")
    if not diff["scoped"]:
        lines.append("⚠ 没有锁定范围：给任务加 --scope 后才能判断越界")
    elif diff["out_of_scope"]:
        lines.append("✘ 越界：%s" % ", ".join(diff["out_of_scope"][:20]))
        lines.append("  测试报告这类命令输出：加进 .gitignore，或在 gt run / gt tdd red 上用 --output 声明")
        lines.append("  确属必要：gt scope allow <路径> --reason \"...\"；否则撤回这些改动")
    else:
        lines.append("✔ 全部在锁定范围内（范围是全部任务的并集）")
    if diff["unstarted"]:
        lines.append("⚠ 这些改动只落在尚未开始的任务范围内：%s" % ", ".join(diff["unstarted"][:10]))
    out(ctx, "\n".join(lines), holder)
    return 1 if diff["out_of_scope"] or diff["hidden"] else 0


def cmd_scope_allow(ctx: Ctx) -> int:
    ctx.active_goal_required()
    if not ctx.args.reason:
        raise GTError("缺少 --reason。")
    ctx.append("scope.allow", {"pattern": ctx.args.pattern, "reason": ctx.args.reason})
    out(ctx, "已允许范围：%s（%s）" % (ctx.args.pattern, ctx.args.reason))
    return 0


def _review_assurance(by: str, self_review: bool) -> str:
    """What produced the verdict: the implementer (self), another member or session of the same model
    (correlated_reviewer), or a claim the session wrote down about an outside actor (self_reported).
    Host-verified and external levels need records this CLI cannot produce (INV03)."""
    if self_review:
        return "self"
    if by.lower() in HUMAN_NAMES or any(word in by for word in ("用户", "维护者", "人工", "客户", "老板")):
        return "self_reported"
    return "correlated_reviewer"


# A review "by" a human is a verdict the session relays: self_reported, never stronger.
HUMAN_NAMES = {"user", "owner", "maintainer", "human", "customer", "client", "pm", "me"}


def _needs_independent(state: State, task_ref: str) -> bool:
    from . import policy
    gates = policy.gates_of(state.goal or {})
    gate = gates["audit"] if task_ref == "@goal" else gates["review"]
    return gate.required and gate.min_assurance not in (None, "self")


def record_review(ctx: Ctx, task_ref: str, by: Optional[str], verdict: str, note: Optional[str],
                  self_review: bool) -> Dict[str, Any]:
    state = ctx.active_goal_required()
    by = _check_member(by)
    if not by:
        raise GTError("缺少 --by。")
    if verdict not in ("pass", "fail"):
        raise GTError("verdict 只能是 pass 或 fail。")
    if verdict == "fail" and not note:
        raise GTError("驳回需要 --note 说明原因。")
    if verdict == "pass" and not self_review and not (note or "").strip() and _needs_independent(state, task_ref):
        raise GTError("这个评审要求独立复核（高风险、发布或项目要求）：通过时用 --note 写下评审人核对了什么。",
                      hint="gt review %s --by %s --verdict pass --note \"<核对了哪些文件、证据和验收项>\"" % (task_ref, by))
    if by.lower() == "lead" and not self_review:
        raise GTError("Goal Lead 不是独立评审人。",
                      hint="派验证成员评审；单 Agent 宿主上确实只能自评时加 --self（会标记为自评）。")
    assurance = _review_assurance(by, self_review)
    if task_ref == "@goal":
        source = checks.Live(ctx.project, state).source()
        data = {"task": "@goal", "by": by, "verdict": verdict, "note": note, "self": bool(self_review),
                "assurance": assurance, "binds": {"source_digest": source, "tree": ctx.project.tree_label()}}
        ctx.append("review", data, expect=ctx.expect_same_goal(ctx.goal_id()))
        return data
    task = ctx.task(task_ref)
    if task.state == "cancelled":
        raise GTError("%s 已取消，不能评审。" % task.id)
    owner = (task.owner or "lead").lower()
    if by.lower() == owner and not self_review:
        raise GTError("评审人不能是负责人（%s）。" % by,
                      hint="单 Agent 宿主上确实只能自评时加 --self（会标记为自评，独立性较弱）。")
    if verdict == "pass" and task.validator and by.lower() != task.validator.lower() and not self_review:
        raise GTError("%s 的验证人是 %s，不是 %s。" % (task.id, task.validator, by),
                      hint="要换验证人先 gt task edit %s --validator %s（会记入账本）。" % (task.id, by))
    if verdict == "pass" and task.state not in ("done", "accepted"):
        raise GTError("%s 当前是 %s：先 gt task done，再评审通过。" % (task.id, task.state))
    binds = checks.review_binding(ctx.project, state, task)
    data = {"task": task.id, "by": by, "verdict": verdict, "note": note, "self": bool(self_review),
            "assurance": assurance, "binds": binds}
    states = ("done", "accepted") if verdict == "pass" else ()
    ctx.append("review", data, expect=ctx.expect_task(task.id, ctx.goal_id(), states))
    return data


def cmd_review(ctx: Ctx) -> int:
    args = ctx.args
    if args.file:
        if args.task or args.by or args.verdict:
            raise GTError("--file 与单条评审参数不能同时使用。")
        try:
            items = json.loads(Path(args.file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GTError("读不到评审文件：%s" % exc,
                          hint='格式：[{"task": "T1", "by": "goal_reviewer", "verdict": "pass", "note": "..."}]')
        if isinstance(items, dict):
            items = items.get("reviews") or []
        if not isinstance(items, list) or not items:
            raise GTError("评审文件需要非空列表。")
        ensure_direct_state(ctx, None, title="评审")
        results = []
        failed = 0
        for item in items:
            data = record_review(ctx, str(item.get("task") or ""), item.get("by"), str(item.get("verdict") or ""),
                                 item.get("note"), bool(item.get("self")))
            results.append(data)
            failed += data["verdict"] != "pass"
        lines = ["%s 评审：%s（%s，assurance=%s）" % (d["task"], d["verdict"], d["by"], d["assurance"]) for d in results]
        out(ctx, "\n".join(lines), results)
        return EXIT.unverified if failed else EXIT.ok
    if not args.task or not args.by or not args.verdict:
        raise GTError("缺少参数。", hint="gt review <任务|@goal> --by <评审人> --verdict pass|fail [--note ...]，或 gt review --file reviews.json")
    ensure_direct_state(ctx, None if args.task == "@goal" else args.task, title="评审")
    data = record_review(ctx, args.task, args.by, args.verdict, args.note, bool(args.self_))
    if args.task == "@goal":
        out(ctx, "目标评审已记录：%s %s（assurance=%s；绑定当前源码，源码再变化需重新评审）" % (
            data["by"], data["verdict"], data["assurance"]), data)
    else:
        result = ctx.task(data["task"]).state
        out(ctx, "%s 评审：%s → %s（assurance=%s）" % (data["task"], data["verdict"], result, data["assurance"]), data)
    return EXIT.ok if data["verdict"] == "pass" else EXIT.unverified
