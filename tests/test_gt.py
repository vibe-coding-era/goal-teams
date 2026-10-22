"""End-to-end and unit tests for the gt CLI (stdlib unittest, Python 3.9+)."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugins" / "goal-teams" / "skills" / "goal-teams" / "scripts"
GT = SCRIPTS / "gt.py"
sys.path.insert(0, str(SCRIPTS))

from goalteams import hook, routes  # noqa: E402
from goalteams.ledger import Project  # noqa: E402
from goalteams.util import glob_to_regex, matches_any, sanitize_url, web_url  # noqa: E402

HAS_GIT = shutil.which("git") is not None
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST_OK = (
    "import sys, unittest\nsys.path.insert(0, 'src')\nfrom calc import add\n\n"
    "class T(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n"
)
TEST_NEW = TEST_OK + "\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
UNITTEST = [sys.executable, "-m", "unittest", "-q", "tests.test_calc"]


class Repo:
    """A throwaway project; ``git`` controls whether it is a git repository."""

    def __init__(self, git: bool = True) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gt-test-")
        self.path = Path(self._tmp.name) / "proj"
        (self.path / "src").mkdir(parents=True)
        (self.path / "tests").mkdir()
        (self.path / "src" / "calc.py").write_text(BUGGY, encoding="utf-8")
        (self.path / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (self.path / "tests" / "test_calc.py").write_text(TEST_OK, encoding="utf-8")
        (self.path / "README.md").write_text("# demo\n", encoding="utf-8")
        (self.path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        self.git = git
        if git:
            self.run_git("init", "-q")
            self.run_git("config", "user.name", "t")
            self.run_git("config", "user.email", "t@example.invalid")
            self.run_git("add", "-A")
            self.run_git("commit", "-qm", "init")

    def run_git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True)

    def gt(self, *args: str, stdin: str = "", env: dict = None) -> subprocess.CompletedProcess:
        environment = dict(os.environ, GT_NOW="2026-10-18T08:00:00Z", PYTHONDONTWRITEBYTECODE="1")
        environment.pop("GT_ACTOR", None)
        environment.update(env or {})
        return subprocess.run([sys.executable, str(GT), *args], cwd=self.path, capture_output=True,
                              text=True, encoding="utf-8", input=stdin, env=environment)

    def ok(self, *args: str, **kw) -> str:
        result = self.gt(*args, **kw)
        if result.returncode != 0:
            raise AssertionError("gt %s failed (%d):\n%s\n%s" % (" ".join(args), result.returncode,
                                                                result.stdout, result.stderr))
        return result.stdout

    def write(self, rel: str, text: str) -> None:
        path = self.path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def events(self):
        return [json.loads(line) for line in (self.path / ".goal-teams" / "ledger.jsonl").read_text(
            encoding="utf-8").splitlines()]

    def close(self) -> None:
        self._tmp.cleanup()


def medium_goal(repo: Repo, tdd: bool = True, check: bool = True) -> None:
    """A tracked goal with one task (the V2.7 ``--size medium`` spelling still works). The done criterion
    carries a ``--check`` command so ``gt rerun`` / ``gt finish`` can prove it on the final code."""
    repo.ok("init")
    args = ["goal", "修复 add", "--done", "add(2,3)==5", "--size", "medium", "--rounds", "2"]
    if check:
        args += ["--check", " ".join(UNITTEST)]
    if not tdd:  # a goal without TDD tasks says so honestly: not a behaviour change
        args += ["--impact", "config_change"]
    repo.ok(*args)
    args = ["task", "add", "T1", "修复 add", "--owner", "goal_backend", "--validator", "goal_reviewer",
            "--scope", "src/calc.py", "--scope", "tests/test_calc.py", "--accept", "add(2,3)==5",
            "--exit", "测试通过"]
    if tdd:
        args.append("--tdd")
    repo.ok(*args)


def settle(repo: Repo) -> str:
    """Run the criteria's --check commands (and any stale task evidence) on the current code."""
    return repo.ok("rerun")


def red_green(repo: Repo) -> None:
    repo.write("tests/test_calc.py", TEST_NEW)
    repo.ok("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError",
            "--as", "goal_unit_test_runner", "--", *UNITTEST)
    repo.write("src/calc.py", FIXED)
    repo.ok("tdd", "green", "T1", "--as", "goal_unit_test_runner", "--", *UNITTEST)


class UtilTests(unittest.TestCase):
    def test_glob(self):
        self.assertTrue(glob_to_regex("src/**").match("src/a/b.py"))
        self.assertTrue(glob_to_regex("src/**/x.py").match("src/x.py"))
        self.assertTrue(glob_to_regex("src/**/x.py").match("src/a/b/x.py"))
        self.assertTrue(glob_to_regex("src/auth").match("src/auth/login.py"))
        self.assertFalse(glob_to_regex("src/auth").match("src/authz.py"))
        self.assertTrue(glob_to_regex("*.md").match("README.md"))
        self.assertFalse(glob_to_regex("*.md").match("docs/a.md"))
        self.assertTrue(glob_to_regex("tests/test_[!x]*.py").match("tests/test_a.py"))
        self.assertTrue(matches_any(".github/workflows/ci.yml", [".github/**"]))

    def test_urls_never_keep_credentials(self):
        self.assertEqual(sanitize_url("https://user:tok@github.com/a/b.git"), "https://github.com/a/b.git")
        self.assertEqual(web_url("git@github.com:a/b.git"), "https://github.com/a/b")
        self.assertEqual(web_url("https://x:y@gitlab.com/g/p.git"), "https://gitlab.com/g/p")

    def test_routes_keep_the_mode_and_tighten_the_gates(self):
        route = routes.derive("small", risk="high")
        self.assertEqual(route["mode"], "direct", "risk never changes the mode (AC01)")
        self.assertEqual(route["gates"]["review"]["min_assurance"], "correlated_reviewer")
        self.assertTrue(route["gates"]["audit"]["required"])
        route = routes.derive("small", release=True)
        self.assertEqual(route["mode"], "direct")
        self.assertIn("rules/release.md", route["rules"])
        self.assertTrue(route["gates"]["readback"]["required"])
        self.assertEqual(routes.derive("small")["rules"], routes.BASE_RULES["direct"])
        self.assertEqual(routes.derive("medium")["rules"], routes.BASE_RULES["tracked"])
        self.assertIn("rules/ui.md", routes.derive("large", ui=True)["rules"])
        self.assertEqual(routes.derive("large")["risk"], "high")
        self.assertEqual(routes.derive("discussion", ui=True)["rules"], [])


@unittest.skipUnless(HAS_GIT, "git is required")
class FlowTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_full_medium_flow_reaches_achieved(self):
        repo = self.repo
        medium_goal(repo)
        out = repo.ok("plan", "apply")
        self.assertIn("已校验并记录", out)
        red_green(repo)
        repo.ok("task", "done", "T1", "--as", "goal_backend")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass", "--note", "ok")
        settle(repo)
        check = repo.gt("check")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        repo.ok("reflect", "Red 先于实现，流程顺畅", "--action", "把 --expect 写进任务包模板", "--kind", "stop")
        out = repo.ok("loop", "decide", "stop", "--next", "无")
        self.assertIn("achieved", out)
        brief = repo.ok("report", "--summary", "修复完成。")
        self.assertIn("## 结果", brief)
        self.assertIn("目标达成", brief)
        report = repo.ok("report", "--format", "six", "--summary", "修复完成。")
        labels = [line.split("：", 1)[0] for line in report.splitlines()
                  if line.split("：", 1)[0] in ("任务", "成员", "进度", "结果", "Benchmark", "下一轮 LOOP", "下一个任务")]
        self.assertEqual(labels, ["任务", "成员", "进度", "结果", "Benchmark", "下一个任务"])
        self.assertIn("第 1 轮/共 2 轮", report)
        self.assertIn("本轮全部完成", report)
        self.assertIn("LOOP 改进建议", report)
        self.assertIn("把 --expect 写进任务包模板", report)
        self.assertIn("目标达成", report)
        self.assertNotIn(str(repo.path), report, "report must not leak absolute paths")
        self.assertEqual(repo.gt("verify").returncode, 0)
        tasklist = (repo.path / ".goal-teams" / "TaskList.md").read_text(encoding="utf-8")
        self.assertIn("| T1 | 修复 add |", tasklist)

    def test_red_must_fail(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", TEST_OK)
        result = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError",
                         "--", *UNITTEST)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Red 不成立", result.stdout)
        receipts = [e for e in repo.events() if e["type"] == "tdd.red"]
        self.assertEqual(receipts[-1]["data"]["outcome"], "red_unexpected_pass")

    def test_red_expect_mismatch_is_not_a_red(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", "import nonexistent_module\n")
        result = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError",
                         "--", *UNITTEST)
        self.assertEqual(result.returncode, 1)
        self.assertEqual([e for e in repo.events() if e["type"] == "tdd.red"][-1]["data"]["outcome"],
                         "red_expect_mismatch")

    def test_green_rejects_changed_test_file(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", TEST_NEW)
        repo.ok("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        repo.write("src/calc.py", FIXED)
        repo.write("tests/test_calc.py", TEST_NEW + "\n# tweaked\n")
        result = repo.gt("tdd", "green", "T1", "--", *UNITTEST)
        self.assertEqual(result.returncode, 1)
        self.assertIn("新的测试用例", result.stdout)

    def test_green_requires_source_change(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", TEST_NEW)
        repo.ok("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        repo.run_git("commit", "--allow-empty", "-qm", "bump")  # history alone is not an implementation
        result = repo.gt("tdd", "green", "T1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual([e for e in repo.events() if e["type"] == "tdd.green"][-1]["data"]["outcome"],
                         "green_source_unchanged")

    def test_green_must_rerun_reds_command(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", TEST_NEW)
        repo.ok("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        repo.write("src/calc.py", FIXED)
        before = len(repo.events())
        result = repo.gt("tdd", "green", "T1", "--", sys.executable, "-c", "print('pretend pass')")
        self.assertEqual(result.returncode, 2)
        self.assertIn("同一条命令", result.stderr)
        self.assertEqual(len(repo.events()), before, "a refused Green records nothing")
        self.assertIn("Green 成立", repo.ok("tdd", "green", "T1"))

    def test_green_requires_red(self):
        repo = self.repo
        medium_goal(repo)
        result = repo.gt("tdd", "green", "T1", "--", *UNITTEST)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Red", result.stderr)

    def test_tdd_task_done_without_green_warns_and_finish_blocks(self):
        repo = self.repo
        medium_goal(repo)
        result = repo.gt("task", "done", "T1")
        self.assertEqual(result.returncode, 0, "done records; the hard gate is finish")
        self.assertIn("TDD", result.stdout)
        self.assertIn("gt finish 会要求", result.stdout)
        finish = repo.gt("--json", "finish")
        self.assertEqual(finish.returncode, 1)
        self.assertIn("缺少有效的 Red→Green 证据", "\n".join(json.loads(finish.stdout)["reasons"]))

    def test_reviewer_must_differ_from_owner(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "done", "T1")
        result = repo.gt("review", "T1", "--by", "goal_backend", "--verdict", "pass")
        self.assertEqual(result.returncode, 2)
        repo.ok("review", "T1", "--by", "goal_backend", "--verdict", "pass", "--self")
        review = [e for e in repo.events() if e["type"] == "review"][-1]["data"]
        self.assertTrue(review["self"])

    def test_owner_and_validator_must_differ(self):
        repo = self.repo
        medium_goal(repo)
        result = repo.gt("task", "add", "T2", "x", "--owner", "a", "--validator", "a")
        self.assertEqual(result.returncode, 2)

    def test_review_fail_reopens_and_requires_note(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "done", "T1")
        self.assertEqual(repo.gt("review", "T1", "--by", "goal_reviewer", "--verdict", "fail").returncode, 2)
        result = repo.gt("review", "T1", "--by", "goal_reviewer", "--verdict", "fail", "--note", "缺测试")
        self.assertEqual(result.returncode, 1)
        self.assertIn("in_progress", result.stdout)

    def test_out_of_scope_change_fails_check_until_allowed(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        repo.write("src/calc.py", FIXED)
        repo.write("docs/notes.md", "x\n")
        diff = repo.gt("diff")
        self.assertEqual(diff.returncode, 1)
        self.assertIn("docs/notes.md", diff.stdout)
        self.assertFalse([e for e in repo.events() if e["type"] == "diff"], "plain gt diff must not record")
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("越界", check.stdout)
        repo.ok("scope", "allow", "docs/**", "--reason", "用户要求补充说明")
        self.assertEqual(repo.gt("diff", "--record").returncode, 0)
        self.assertTrue([e for e in repo.events() if e["type"] == "diff"])
        settle(repo)
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)

    def test_review_goes_stale_when_scope_files_change(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        settle(repo)
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        repo.write("src/calc.py", FIXED + "# later edit\n")
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("评审已过期", check.stdout)
        repo.ok("loop", "decide", "continue", "--next", "重新评审")
        self.assertIn("评审已过期", repo.ok("report", "--summary", "x"))
        self.assertIn("评审已过期", repo.ok("report", "--format", "six", "--summary", "x"))

    def test_plan_apply_validates_tracked_tasks(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--done", "d", "--mode", "tracked")
        out = repo.ok("task", "add", "T1", "x", "--owner", "goal_backend")
        for missing in ("accept", "scope", "exit"):
            self.assertIn(missing, out, "a manual add warns about the gaps")
        result = repo.gt("plan", "apply")
        self.assertEqual(result.returncode, 2, "validating the whole set refuses an incomplete tracked plan")
        for missing in ("accept", "scope", "exit"):
            self.assertIn(missing, result.stderr)
        check = repo.gt("check")
        self.assertIn("计划问题", check.stdout)

    def test_structural_change_after_apply_bumps_revision(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")                       # r2: the task add was r1
        out = repo.ok("task", "add", "T2", "文档", "--kind", "doc", "--owner", "goal_docs", "--accept", "a",
                      "--validator", "goal_reviewer", "--deps", "T1")
        self.assertIn("r3", out)
        status = repo.ok("status")
        self.assertIn("计划 r3", status)
        self.assertIn("计划 r4 已校验", repo.ok("plan", "apply"))

    def test_dependency_cycle_is_rejected(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "add", "T2", "b", "--deps", "T1", "--accept", "a")
        result = repo.gt("task", "edit", "T1", "--deps", "T2")
        self.assertEqual(result.returncode, 2)
        self.assertIn("成环", result.stderr)

    def test_external_blocker_reports_successors_and_blocks_completion(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "add", "T2", "接口联调", "--deps", "T1", "--accept", "a")
        out = repo.ok("task", "block", "T1", "--reason", "等第三方密钥", "--external")
        self.assertIn("T2", out)
        self.assertIn("外部阻塞", repo.ok("status"))
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("阻塞", check.stdout)
        repo.ok("task", "unblock", "T1")
        self.assertNotIn("外部阻塞", repo.ok("status"))

    def test_start_waits_for_dependencies(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "add", "T2", "b", "--deps", "T1", "--accept", "a")
        self.assertEqual(repo.gt("task", "start", "T2").returncode, 2)
        self.assertNotEqual(repo.gt("task", "start", "T2", "--force", "--reason", "并行准备").returncode, 0)
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        repo.ok("task", "start", "T2")

    def test_cannot_claim_achieved_when_check_fails(self):
        repo = self.repo
        medium_goal(repo)
        result = repo.gt("loop", "decide", "stop", "--outcome", "achieved")
        self.assertEqual(result.returncode, 1)
        self.assertIn("不能记为达成", result.stderr)
        out = repo.ok("loop", "decide", "stop", "--outcome", "blocked", "--next", "等待凭证")
        self.assertIn("blocked", out)
        report = repo.ok("report", "--summary", "被外部依赖阻塞。")
        self.assertIn("因阻塞停止", report)
        self.assertIn("下一个任务：等待凭证", report)
        self.assertIn("下一个任务：等待凭证", repo.ok("report", "--format", "six", "--summary", "被外部依赖阻塞。"))

    def test_rounds_estimate_and_no_evidence_warning(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("loop", "decide", "continue", "--next", "a")
        out = repo.ok("loop", "decide", "continue", "--next", "b")
        self.assertIn("连续两轮没有新证据", out)
        report = repo.ok("report", "--format", "six", "--summary", "s")
        self.assertIn("第 2 轮/共 3 轮", report)
        self.assertIn("预计轮次已自动上调", report)
        self.assertIn("轮次 2/3", repo.ok("report", "--summary", "s"))

    def test_report_without_decision_warns_but_still_renders(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        result = repo.gt("report", "--format", "six")
        self.assertEqual(result.returncode, 0)
        self.assertIn("本轮尚未记录决策", result.stdout)
        self.assertIn("本轮摘要未提供", result.stdout)
        self.assertIn("下一轮 LOOP：", result.stdout)
        brief = repo.gt("report")
        self.assertEqual(brief.returncode, 0)
        self.assertNotIn("本轮尚未记录决策", brief.stdout, "the brief report does not nag about round ceremony")
        self.assertIn("## 未完成事项", brief.stdout)

    def test_report_english_and_summary_from_stdin(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("loop", "decide", "continue", "--next", "next step")
        report = repo.ok("report", "--format", "six", "--summary", "-", "--lang", "en", stdin="Did things.\n")
        for label in ("Task: ", "Members: ", "Progress: round 1/2", "Result: Did things.", "Benchmark: ",
                      "Next LOOP: next step"):
            self.assertIn(label, report)
        brief = repo.ok("report", "--summary", "-", "--lang", "en", stdin="Did things.\n")
        for label in ("## Result", "Did things.", "## Key evidence", "## Open items", "Next: next step"):
            self.assertIn(label, brief)

    def test_parallel_marker_comes_from_dependencies(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "add", "T2", "前端", "--owner", "goal_frontend", "--accept", "a")
        repo.ok("task", "add", "T3", "依赖 T1", "--owner", "goal_docs", "--deps", "T1", "--accept", "a")
        repo.ok("task", "start", "T1")
        repo.ok("task", "start", "T2")
        status = repo.ok("status")
        self.assertIn("`goal_backend`（并行）", status)
        self.assertIn("`goal_frontend`（并行）", status)
        self.assertNotIn("`goal_docs`（并行）", status)

    def test_auth_check(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        self.assertEqual(repo.gt("auth", "check", "push").returncode, 3)
        repo.ok("auth", "grant", "--actions", "commit,push,tag", "--scope", "origin/main，版本 1.0")
        out = repo.ok("auth", "check", "push")
        self.assertIn("已授权", out)
        self.assertIn("预览", repo.ok("auth", "check", "tag"))
        self.assertEqual(repo.gt("auth", "check", "deploy").returncode, 3)
        self.assertEqual(repo.gt("auth", "grant", "--actions", "launch-rockets", "--scope", "x").returncode, 2)

    def test_packet_and_context(self):
        repo = self.repo
        medium_goal(repo)
        packet = repo.ok("task", "packet", "T1")
        self.assertIn("src/calc.py", packet)
        self.assertIn("gt tdd red T1", packet)
        self.assertIn("--as goal_backend", packet)
        outside = Path(repo.path).parent / "outside.md"
        outside.write_text("x", encoding="utf-8")
        self.assertEqual(repo.gt("context", "add", "knowledge", "外部", "--link", str(outside)).returncode, 2)
        repo.ok("context", "add", "knowledge", "README", "--link", "README.md")
        repo.ok("context", "add", "tool", "MCP：filesystem")
        status = repo.ok("status")
        self.assertIn("[README](README.md)", status)
        self.assertIn("MCP：filesystem", status)

    def test_memory_add_goes_under_section(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("memory", "add", "选用 SQLite", "--section", "决策")
        text = (repo.path / ".goal-teams" / "memory.md").read_text(encoding="utf-8")
        section = text.split("## 决策", 1)[1].split("## ", 1)[0]
        self.assertIn("选用 SQLite", section)

    def test_init_is_idempotent_and_goal_requires_title(self):
        repo = self.repo
        repo.ok("init")
        self.assertIn("无改动", repo.ok("init"))
        self.assertEqual(repo.gt("goal").returncode, 2)
        repo.ok("goal", "a", "--done", "d")
        self.assertEqual(repo.gt("goal", "b").returncode, 2, "second active goal needs --replace")
        repo.ok("goal", "b", "--done", "d", "--replace")

    def test_json_outputs(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        for args in (("status", "--json"), ("check", "--json"), ("route", "--size", "large", "--json"),
                     ("--json", "task", "list"), ("doctor", "--json")):
            result = repo.gt(*args)
            json.loads(result.stdout)

    def test_global_flags_before_subcommand(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("--as", "goal_backend", "task", "start", "T1")
        event = [e for e in repo.events() if e["type"] == "task.state"][-1]
        self.assertEqual(event["actor"], "goal_backend")

    def test_ledger_tampering_is_detected(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        path = repo.path / ".goal-teams" / "ledger.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace("修复 add", "改写过的目标")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = repo.gt("verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("prev", result.stdout)
        self.assertIn("账本完整性检查失败", repo.ok("report"))

    def test_partial_tail_line_is_dropped_before_append(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        path = repo.path / ".goal-teams" / "ledger.jsonl"
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"seq": 99, "broken')
        repo.ok("task", "start", "T1")
        self.assertEqual(repo.gt("verify").returncode, 0)

    def test_doctor_reports_branch_and_runners(self):
        repo = self.repo
        out = repo.ok("doctor")
        self.assertIn("python: ", out)
        self.assertIn("可以开始", out)

    def test_hook_is_silent_unless_opted_in_and_blocks_once(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        payload = json.dumps({"cwd": str(repo.path), "last_assistant_message": "done"})
        self.assertEqual(repo.ok("hook", "stop", stdin=payload).strip(), "")
        config = repo.path / ".goal-teams" / "config.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        data["enforce_report"] = True
        config.write_text(json.dumps(data), encoding="utf-8")
        first = repo.ok("hook", "stop", stdin=payload)
        self.assertEqual(json.loads(first)["decision"], "block")
        self.assertEqual(repo.ok("hook", "stop", stdin=payload).strip(), "", "blocks at most once per state")
        active = json.dumps({"cwd": str(repo.path), "stop_hook_active": True})
        self.assertEqual(repo.ok("hook", "stop", stdin=active).strip(), "")
        repo.ok("report", "--summary", "s")
        repo.ok("task", "start", "T1")
        self.assertEqual(json.loads(repo.ok("hook", "stop", stdin=payload))["decision"], "block")
        self.assertEqual(repo.ok("hook", "stop", stdin="not json").strip(), "")

    def test_hook_function_handles_missing_project(self):
        self.assertEqual(hook.stop(io.StringIO(json.dumps({"cwd": tempfile.gettempdir()}))), 0)

    def test_subtasks_count_and_parent_completion(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--done", "d", "--size", "medium")
        repo.ok("task", "add", "P", "父任务", "--accept", "a", "--kind", "doc")
        repo.ok("task", "add", "P.1", "子任务", "--parent", "P", "--accept", "a", "--kind", "doc")
        self.assertEqual(repo.gt("task", "done", "P").returncode, 2, "parent waits for subtasks")
        repo.ok("task", "done", "P.1")
        repo.ok("review", "P.1", "--by", "goal_reviewer", "--verdict", "pass")
        repo.ok("task", "done", "P")
        repo.ok("review", "P", "--by", "goal_reviewer", "--verdict", "pass")
        status = repo.ok("status")
        self.assertIn("已完成任务 1/1｜已完成子任务 1/1", status)
        self.assertIn("本轮全部完成", status)


class NonGitTests(unittest.TestCase):
    def test_flow_without_git(self):
        repo = Repo(git=False)
        try:
            medium_goal(repo)
            red_green(repo)
            self.assertIn("gt diff 不可用", repo.ok("diff"))
            green = [e for e in repo.events() if e["type"] == "tdd.green"][-1]["data"]
            self.assertEqual(green["source_method"], "walk")
            self.assertEqual(green["outcome"], "green_ok")
        finally:
            repo.close()

    def test_commands_outside_project_explain_how_to_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, str(GT), "status"], cwd=tmp, capture_output=True, text=True,
                                    encoding="utf-8")
            self.assertEqual(result.returncode, 2)
            self.assertIn("gt init", result.stderr)


@unittest.skipUnless(HAS_GIT, "git is required")
class ProjectRootTests(unittest.TestCase):
    def test_linked_worktree_shares_main_state(self):
        repo = Repo()
        try:
            repo.ok("init")
            worktree = repo.path.parent / "wt"
            repo.run_git("worktree", "add", "-q", str(worktree), "-b", "member")
            project = Project(Path(subprocess.run(
                [sys.executable, "-c", "import sys; sys.path.insert(0, %r); from goalteams.ledger import find_root; "
                 "from pathlib import Path; print(find_root(Path.cwd()))" % str(SCRIPTS)],
                cwd=worktree, capture_output=True, text=True).stdout.strip()))
            self.assertEqual(project.root.resolve(), repo.path.resolve())
        finally:
            repo.close()


if __name__ == "__main__":
    unittest.main()
