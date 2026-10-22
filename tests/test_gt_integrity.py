"""Regression tests for the evidence-integrity gaps found in the V2.7 reviews."""

from __future__ import annotations

import shlex
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from tests.test_gt import FIXED, GT, HAS_GIT, SCRIPTS, TEST_NEW, UNITTEST, Repo, medium_goal, red_green, settle

sys.path.insert(0, str(SCRIPTS))
from goalteams import hook, runner  # noqa: E402
from goalteams.util import FileLock  # noqa: E402


def accepted_tdd_task(repo: Repo) -> None:
    medium_goal(repo)
    repo.ok("plan", "apply")
    red_green(repo)
    repo.ok("task", "done", "T1")
    repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
    settle(repo)


@unittest.skipUnless(HAS_GIT, "git required")
class TddIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_new_red_after_green_blocks_done_and_check(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("plan", "apply")
        red_green(repo)
        repo.run_git("checkout", "--", "src/calc.py")  # the fix is gone again
        repo.write("src/calc.py", "def add(a, b):\n    return a - b\n")
        repo.ok("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        done = repo.gt("task", "done", "T1")
        self.assertEqual(done.returncode, 0, "done only warns; finish/check is the gate")
        self.assertIn("又有成立的 Red", done.stdout)
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("又有成立的 Red", check.stdout)

    def test_reverting_after_green_is_caught(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("plan", "apply")
        red_green(repo)
        repo.write("src/calc.py", "def add(a, b):\n    return a - b\n")
        done = repo.gt("task", "done", "T1")
        self.assertEqual(done.returncode, 0)
        self.assertIn("最后一次 Green 之后又改了", done.stdout)
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("没有在最终代码上通过的测试记录", check.stdout)

    def test_accepted_task_needs_evidence_for_the_final_code(self):
        repo = self.repo
        accepted_tdd_task(repo)
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        repo.write("src/calc.py", FIXED + "\n\ndef helper():\n    return 1\n")
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("评审已过期", check.stdout)
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        settle(repo)
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)

    def test_code_task_without_any_test_run_fails_check(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        repo.write("src/calc.py", FIXED)
        out = repo.ok("task", "done", "T1")
        self.assertIn("还没有在当前实现上通过的测试记录", out)
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("没有在最终代码上通过的测试记录", check.stdout)
        self.assertEqual(repo.gt("loop", "decide", "stop", "--outcome", "achieved").returncode, 1)

    def test_red_without_expect_is_observed_and_bad_patterns_are_refused(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", TEST_NEW)
        before = len(repo.events())
        bad = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "(", "--", *UNITTEST)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(len(repo.events()), before, "nothing is recorded or started")
        observed = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--", *UNITTEST)
        self.assertEqual(observed.returncode, 0, "a Red without --expect is observed, to be confirmed before finish")
        self.assertIn("red_observed", observed.stdout)
        self.assertIn("gt tdd confirm", observed.stdout)
        self.assertEqual([e["data"]["outcome"] for e in repo.events() if e["type"] == "tdd.red"], ["red_observed"])

    def test_missing_command_or_timeout_is_not_a_red(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", TEST_NEW)
        result = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", ".",
                         "--", "no-such-command-xyz")
        self.assertEqual(result.returncode, 1)
        self.assertIn("命令不存在", result.stdout)
        result = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", ".", "--timeout", "0.5",
                         "--", sys.executable, "-c", "import time; time.sleep(5)")
        self.assertEqual(result.returncode, 1)
        outcomes = [e["data"]["outcome"] for e in repo.events() if e["type"] == "tdd.red"]
        self.assertEqual(outcomes, ["red_invalid", "red_invalid"])
        states = [e for e in repo.events() if e["type"] == "task.state"]
        self.assertEqual(states, [], "an invalid Red does not start the task")


@unittest.skipUnless(HAS_GIT, "git required")
class RunReceiptTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        medium_goal(self.repo, tdd=False)

    def tearDown(self):
        self.repo.close()

    def test_failure_is_closed_only_by_the_same_command(self):
        repo = self.repo
        failing = [sys.executable, "-c", "import sys; sys.exit(1)"]
        self.assertEqual(repo.gt("run", "T1", "--kind", "affected", "--", *failing).returncode, 1)
        repo.ok("run", "T1", "--kind", "affected", "--", sys.executable, "-c", "pass")
        repo.ok("run", "T1", "--kind", "affected", "--manual", "--result", "pass", "--note", "looked fine")
        self.assertIn("检查未通过", repo.gt("check").stdout)
        flaky = [sys.executable, "-c", "import os, sys; sys.exit(0 if os.environ.get('FLAKY_OK') else 1)"]
        self.assertEqual(repo.gt("run", "T1", "--kind", "affected", "--name", "f", "--", *flaky).returncode, 1)
        repo.ok("run", "T1", "--kind", "affected", "--name", "f", "--", *flaky, env={"FLAKY_OK": "1"})
        self.assertIn("不稳定通过", repo.gt("check").stdout)
        # a pass after the code changed is a fix, not flakiness
        fixed = [sys.executable, "-c", "import sys; sys.path.insert(0, 'src'); from calc import add; "
                 "sys.exit(0 if add(2, 3) == 5 else 1)"]
        self.assertEqual(repo.gt("run", "T1", "--kind", "affected", "--name", "g", "--", *fixed).returncode, 1)
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--name", "g", "--", *fixed)
        self.assertEqual(repo.gt("check").stdout.count("不稳定通过"), 1)

    def test_release_gates_need_command_receipts_on_the_current_source(self):
        repo = self.repo
        repo.ok("run", "-", "--kind", "regression", "--manual", "--result", "pass", "--note", "trust me")
        repo.ok("run", "-", "--kind", "build", "--", sys.executable, "-c", "pass")
        self.assertIn("构建产物：缺少", repo.gt("check", "--release").stdout, "a build needs --artifact")
        build = [sys.executable, "-c", "import os; os.makedirs('dist', exist_ok=True); open('dist/a.tgz', 'w').write('x')"]
        repo.ok("run", "-", "--kind", "build", "--artifact", "dist/a.tgz", "--", *build)
        check = repo.gt("check", "--release").stdout
        self.assertIn("全量回归：缺少", check)
        self.assertIn("构建产物：通过", check)
        self.assertNotIn("越界", check, "declared artifacts are not out-of-scope changes")
        self.assertIn("发布回读：not_run", check)
        repo.write("src/calc.py", FIXED)
        self.assertIn("构建产物：缺少", repo.gt("check", "--release").stdout)

    def test_artifacts_are_recorded_and_missing_ones_fail(self):
        repo = self.repo
        build = [sys.executable, "-c", "import os; os.makedirs('dist', exist_ok=True); open('dist/a.tgz', 'w').write('xyz')"]
        out = repo.ok("run", "-", "--kind", "build", "--artifact", "dist/a.tgz", "--", *build)
        self.assertIn("产物 dist/a.tgz", out)
        receipt = [e for e in repo.events() if e["type"] == "run"][-1]["data"]
        self.assertEqual(receipt["artifacts"][0]["size"], 3)
        tracked = repo.gt("run", "-", "--kind", "build", "--artifact", "README.md", "--", sys.executable, "-c", "pass")
        self.assertEqual(tracked.returncode, 2, "a tracked source file is not a build output")
        repo.write("src/gen.py", "x = 1\n")
        repo.ok("task", "edit", "T1", "--add-scope", "src/**")
        in_scope = repo.gt("run", "-", "--kind", "build", "--artifact", "src/gen.py", "--", sys.executable, "-c", "pass")
        self.assertEqual(in_scope.returncode, 2, "a file inside a code scope is not a build output")
        missing = repo.gt("run", "-", "--kind", "build", "--artifact", "dist/x.tar.gz", "--",
                          sys.executable, "-c", "pass")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("产物不存在", missing.stdout)

    def test_concurrent_runs_all_succeed(self):
        repo = self.repo
        results = []

        def one():
            results.append(repo.gt("run", "T1", "--kind", "lint", "--", sys.executable, "-c", "pass").returncode)

        threads = [threading.Thread(target=one) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [0] * 12)
        self.assertEqual(repo.gt("verify").returncode, 0)


@unittest.skipUnless(HAS_GIT, "git required")
class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        medium_goal(self.repo)

    def tearDown(self):
        self.repo.close()

    def ledger(self) -> Path:
        return self.repo.path / ".goal-teams" / "ledger.jsonl"

    def test_truncated_tail_is_detected(self):
        lines = self.ledger().read_text(encoding="utf-8").splitlines(keepends=True)
        self.ledger().write_text("".join(lines[:-1]), encoding="utf-8")
        result = self.repo.gt("verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("截断", result.stdout)

    def test_missing_final_newline_is_detected(self):
        raw = self.ledger().read_bytes()
        self.ledger().write_bytes(raw.rstrip(b"\n"))
        self.assertEqual(self.repo.gt("verify").returncode, 1)

    def test_rewritten_last_event_is_detected(self):
        lines = self.ledger().read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1])
        last["data"]["title"] = "forged"
        lines[-1] = json.dumps(last, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.ledger().write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = self.repo.gt("verify")
        self.assertEqual(result.returncode, 1)
        self.assertIn("改写", result.stdout)

    def test_crlf_checkout_keeps_the_chain_valid(self):
        raw = self.ledger().read_bytes()
        self.ledger().write_bytes(raw.replace(b"\n", b"\r\n"))
        self.assertEqual(self.repo.gt("verify").returncode, 0, self.repo.gt("verify").stdout)
        attributes = (self.repo.path / ".goal-teams" / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("-text", attributes)

    def test_orphan_evidence_log_is_reported_not_failed(self):
        # evidence/ is local: after switching branches, logs of the other history are normal
        (self.repo.path / ".goal-teams" / "evidence" / "R999.log").write_text("x", encoding="utf-8")
        result = self.repo.gt("verify")
        self.assertEqual(result.returncode, 0)
        self.assertIn("R999.log", result.stdout)


@unittest.skipUnless(HAS_GIT, "git required")
class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_independence_rules(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("plan", "apply")
        red_green(repo)
        repo.ok("task", "done", "T1")
        lead = repo.gt("review", "T1", "--by", "lead", "--verdict", "pass")
        self.assertEqual(lead.returncode, 2)
        other = repo.gt("review", "T1", "--by", "goal_qa", "--verdict", "pass")
        self.assertEqual(other.returncode, 2)
        self.assertIn("验证人是 goal_reviewer", other.stderr)
        repo.ok("review", "T1", "--by", "goal_backend", "--verdict", "pass", "--self")
        check = repo.gt("check").stdout
        self.assertIn("自评通过", check)
        repo.ok("loop", "decide", "continue", "--next", "n")
        report = repo.ok("report", "--summary", "s")
        self.assertIn("自评", report)

    def test_fail_review_does_not_resurrect_cancelled_or_blocked_tasks(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "add", "T2", "x", "--owner", "goal_frontend", "--validator", "goal_reviewer",
                "--scope", "web/**", "--accept", "a", "--exit", "e")
        repo.ok("task", "start", "T1")
        repo.ok("task", "block", "T1", "--reason", "等外部接口", "--external")
        self.assertEqual(repo.gt("review", "T1", "--by", "goal_reviewer", "--verdict", "fail",
                                 "--note", "missing case").returncode, 1)
        self.assertIn("外部阻塞", repo.ok("task", "list"))
        repo.ok("task", "cancel", "T2", "--reason", "不做了")
        self.assertEqual(repo.gt("review", "T2", "--by", "goal_reviewer", "--verdict", "fail",
                                 "--note", "x").returncode, 2)

    def test_stale_review_is_not_counted_as_done(self):
        repo = self.repo
        accepted_tdd_task(repo)
        self.assertIn("本轮全部完成", repo.ok("status"))
        repo.write("src/calc.py", FIXED + "# edit\n")
        status = repo.ok("status")
        self.assertIn("评审已过期", status)
        self.assertIn("已完成任务 0/1", status)

    def test_achieved_report_shows_later_breakage(self):
        repo = self.repo
        accepted_tdd_task(repo)
        repo.ok("loop", "decide", "stop", "--outcome", "achieved", "--next", "无")
        self.assertIn("目标达成", repo.ok("report", "--summary", "done"))
        repo.write("src/calc.py", FIXED + "# edit\n")
        self.assertIn("gt check 现在未通过", repo.ok("report", "--summary", "done"))

    def test_goal_reviews(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "big", "--done", "d", "--check", shlex.join(UNITTEST), "--size", "large")
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/calc.py", "--scope", "tests/test_calc.py", "--accept", "a", "--exit", "e", "--tdd")
        repo.ok("plan", "apply")
        red_green(repo)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass", "--note", "核对了改动与回执")
        settle(repo)
        self.assertEqual(repo.gt("review", "@goal", "--by", "lead", "--verdict", "pass", "--note", "核对了改动与回执").returncode, 2)
        repo.ok("review", "@goal", "--by", "goal_security", "--verdict", "pass", "--note", "核对了改动与回执")
        self.assertIn("缺少完成审计", repo.gt("check").stdout)
        repo.ok("review", "@goal", "--by", "goal_completion_auditor", "--verdict", "pass", "--note", "核对了改动与回执")
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        self.assertEqual(repo.gt("review", "@goal", "--by", "goal_completion_auditor", "--verdict", "fail",
                                 "--note", "gap").returncode, 1)
        self.assertIn("目标评审未通过", repo.gt("check").stdout)
        repo.ok("review", "@goal", "--by", "goal_completion_auditor", "--verdict", "pass", "--note", "核对了改动与回执")
        repo.write("README.md", "# demo\nmore\n")
        self.assertIn("完成审计已过期", repo.gt("check").stdout)

    def test_release_goal_needs_readback_to_be_achieved(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "ship", "--done", "d", "--check", shlex.join(UNITTEST), "--size", "medium", "--release")
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/calc.py", "--scope", "tests/test_calc.py", "--accept", "a", "--exit", "e", "--tdd")
        repo.ok("plan", "apply")
        red_green(repo)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass", "--note", "核对了改动与回执")
        settle(repo)
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertTrue(check["engineering_passed"], "release prerequisites are not engineering gates")
        self.assertFalse(check["goal_achieved"], "but a release goal is not achieved before its release gates")
        self.assertEqual(check["gates"]["regression"], "not_run")
        repo.ok("run", "-", "--kind", "regression", "--", *UNITTEST)
        repo.ok("review", "@goal", "--by", "goal_security", "--verdict", "pass", "--note", "核对了改动与回执")
        build = [sys.executable, "-c", "import os; os.makedirs('dist', exist_ok=True); open('dist/a.tgz', 'w').write('x')"]
        repo.ok("run", "-", "--kind", "build", "--artifact", "dist/a.tgz", "--", *build)
        self.assertEqual(repo.gt("check", "--release").returncode, 0, repo.gt("check", "--release").stdout)
        stop = repo.gt("loop", "decide", "stop", "--outcome", "achieved")
        self.assertEqual(stop.returncode, 1)
        self.assertIn("发布回读", stop.stderr)
        repo.ok("run", "-", "--kind", "release", "--", sys.executable, "-c", "pass")
        repo.ok("loop", "decide", "stop", "--outcome", "achieved", "--next", "无")


@unittest.skipUnless(HAS_GIT, "git required")
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_worktree_with_committed_state_records_into_main(self):
        repo = self.repo
        medium_goal(repo)
        repo.run_git("add", "-A")
        repo.run_git("commit", "-qm", "state")
        wt = repo.path.parent / "wt"
        repo.run_git("worktree", "add", "-q", "-b", "wt", str(wt))
        result = subprocess.run([sys.executable, str(GT), "context", "add", "tool", "pytest"], cwd=wt,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        main_events = repo.events()
        self.assertEqual(main_events[-1]["type"], "context.add")

    def test_hidden_files_fail_diff_and_check(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.write("README.md", "# demo\nsecret edit\n")
        repo.run_git("update-index", "--assume-unchanged", "README.md")
        diff = repo.gt("diff")
        self.assertEqual(diff.returncode, 1)
        self.assertIn("assume-unchanged", diff.stdout)
        self.assertIn("assume-unchanged", repo.gt("check").stdout)

    def test_scope_dot_means_whole_project(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--done", "d", "--size", "medium")
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", ".", "--accept", "a", "--exit", "e")
        repo.write("anything/new.txt", "x")
        self.assertIn("全部在锁定范围内", repo.ok("diff"))

    def test_config_memory_downgrade_and_expiry(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("config", "set", "enforce_report", "true")
        config = json.loads((repo.path / ".goal-teams" / "config.json").read_text(encoding="utf-8"))
        self.assertIs(config["enforce_report"], True)
        self.assertEqual(repo.gt("config", "set", "git.branch", "sometimes").returncode, 2)
        self.assertIn("enforce_report = true", repo.ok("config", "show"))
        repo.ok("memory", "add", "以后再做导出", "--section", "待办")
        self.assertIn("以后再做导出", (repo.path / ".goal-teams" / "memory.md").read_text(encoding="utf-8"))
        repo.ok("goal", "g", "--done", "d", "--size", "large")
        self.assertEqual(repo.gt("goal", "--size", "medium", "--downgrade").returncode, 2)
        repo.ok("goal", "--size", "medium", "--downgrade", "--reason", "用户要求按 medium 走")
        self.assertEqual(repo.gt("auth", "grant", "--actions", "push", "--scope", "s",
                                 "--expires", "next week").returncode, 2)

    def test_packets_for_members(self):
        repo = self.repo
        medium_goal(repo)
        packet = repo.ok("task", "packet", "T1", "--for", "goal_unit_test_runner")
        self.assertIn("--as goal_unit_test_runner", packet)
        self.assertIn("gt tdd red", packet)
        self.assertIn(sys.executable, packet)
        self.assertIn("未授权", packet)
        repo.ok("auth", "grant", "--actions", "push", "--scope", "origin goal/x")
        self.assertIn("已授权 push", repo.ok("task", "packet", "T1"))


@unittest.skipUnless(HAS_GIT, "git required")
class SecondRoundTests(unittest.TestCase):
    """Regressions for the second review round."""

    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def tdd_task_with_test_subtask(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("task", "add", "T1.t", "写测试", "--parent", "T1", "--kind", "test", "--owner", "goal_unit_test_designer",
                "--validator", "goal_reviewer", "--scope", "tests/**", "--accept", "a", "--exit", "e")
        # This node designs tests; its reviewed output is consumed by the parent's Red.
        repo.write(".goal-teams/plan.json", json.dumps({"tasks": [{"id": "T1.t", "exit_condition": {
            "required_receipt_types": ["review"], "on_budget_exhaustion": "blocked"}}]}))
        repo.ok("plan", "apply")
        repo.ok("task", "start", "T1.t")
        repo.write("tests/test_calc.py", TEST_NEW)
        repo.ok("task", "done", "T1.t")
        repo.ok("review", "T1.t", "--by", "goal_reviewer", "--verdict", "pass")
        red_green(repo)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        settle(repo)

    def test_parent_with_subtask_still_needs_evidence_on_final_code(self):
        repo = self.repo
        self.tdd_task_with_test_subtask()
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        repo.write("src/calc.py", "def add(a, b):\n    return a - b\n")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")  # the stale review is redone
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("没有在最终代码上通过的测试记录", check.stdout)
        self.assertEqual(repo.gt("rerun").returncode, 1)  # re-running exposes the failure
        self.assertIn("最近一次 Green", repo.gt("check").stdout)

    def test_newer_failing_green_blocks(self):
        repo = self.repo
        self.tdd_task_with_test_subtask()
        repo.write("src/calc.py", "def add(a, b):\n    return a * b\n")  # broken by a later edit
        self.assertEqual(repo.gt("tdd", "green", "T1").returncode, 1)
        self.assertIn("没有通过", repo.gt("check").stdout)

    def test_any_later_change_needs_a_rerun_even_docs(self):
        # a test may read the README; docs are not exempt, and gt rerun makes refreshing cheap
        repo = self.repo
        self.tdd_task_with_test_subtask()
        repo.ok("task", "add", "T2", "文档", "--kind", "doc", "--owner", "goal_docs", "--validator", "goal_reviewer",
                "--scope", "README.md", "--artifact", "README.md", "--accept", "a", "--deps", "T1")
        repo.ok("plan", "apply")
        repo.ok("review", "T1.t", "--by", "goal_reviewer", "--verdict", "pass")
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        repo.ok("task", "start", "T2")
        repo.write("README.md", "# demo\nusage\n")
        repo.ok("task", "done", "T2")
        repo.ok("review", "T2", "--by", "goal_reviewer", "--verdict", "pass")
        self.assertIn("没有在最终代码上通过的测试记录", repo.gt("check").stdout)
        repo.ok("rerun")
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        self.assertIn("不需要重跑", repo.ok("rerun"))

    def test_doc_task_cannot_hide_code_edits(self):
        repo = self.repo
        self.tdd_task_with_test_subtask()
        repo.write("src/helper.py", "def plus(a, b):\n    return a + b\n")
        repo.ok("task", "add", "T3", "说明", "--kind", "doc", "--owner", "goal_docs", "--validator", "goal_reviewer",
                "--scope", "src/helper.py", "--artifact", "src/helper.py", "--accept", "a")
        repo.ok("plan", "apply")
        repo.ok("review", "T1.t", "--by", "goal_reviewer", "--verdict", "pass")
        repo.ok("rerun")
        self.assertEqual(repo.gt("check").returncode, 1)  # T3 is not done yet, but T1 must still be fresh
        repo.write("src/helper.py", "def plus(a, b):\n    return a * b\n")
        self.assertIn("T1 没有在最终代码上通过的测试记录", repo.gt("check").stdout,
                      "a .py file owned by a doc task is still code")

    def test_manual_affected_is_not_fresh_evidence(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--manual", "--result", "pass", "--note", "looked fine")
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        self.assertIn("没有在最终代码上通过的测试记录", repo.gt("check").stdout)

    def test_green_needs_a_change_in_the_tasks_own_scope(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("task", "edit", "T1", "--add-scope", "tests/**")
        repo.ok("task", "add", "T1.t", "写测试", "--parent", "T1", "--kind", "test", "--owner", "goal_unit_test_designer",
                "--validator", "goal_reviewer", "--scope", "tests/**", "--accept", "a", "--exit", "e")
        repo.write(".goal-teams/plan.json", json.dumps({"tasks": [{"id": "T1.t", "exit_condition": {
            "required_receipt_types": ["review"], "on_budget_exhaustion": "blocked"}}]}))
        repo.ok("plan", "apply")
        repo.write("tests/test_calc.py", TEST_NEW)
        repo.ok("task", "done", "T1.t")
        repo.ok("review", "T1.t", "--by", "goal_reviewer", "--verdict", "pass")
        repo.ok("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        repo.write("tests/data.json", "{}")  # a fixture change is not an implementation
        repo.ok("review", "T1.t", "--by", "goal_reviewer", "--verdict", "pass")
        result = repo.gt("tdd", "green", "T1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("范围内的实现与 Red 时相同", result.stdout)

    def test_tampered_tail_blocks_appends(self):
        repo = self.repo
        medium_goal(repo)
        ledger = repo.path / ".goal-teams" / "ledger.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        ledger.write_text("".join(lines[:-1]), encoding="utf-8")
        refused = repo.gt("context", "add", "tool", "pytest")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("拒绝继续追加", refused.stderr)
        self.assertEqual(repo.gt("verify").returncode, 1, "detection survives the refused append")
        self.assertEqual(repo.gt("verify", "--reset-head").returncode, 2, "a reset needs a reason")
        repo.ok("verify", "--reset-head", "--reason", "测试中故意删掉了最后一行")
        repo.ok("context", "add", "tool", "pytest")
        self.assertIn("被重置", repo.gt("check").stdout)

    def test_missing_newline_is_repaired_not_dropped(self):
        repo = self.repo
        medium_goal(repo)
        ledger = repo.path / ".goal-teams" / "ledger.jsonl"
        before = len(repo.events())
        ledger.write_bytes(ledger.read_bytes().rstrip(b"\n"))
        repo.ok("context", "add", "tool", "pytest")
        self.assertEqual(len(repo.events()), before + 1)
        self.assertEqual(repo.gt("verify").returncode, 0)

    def test_logs_from_another_history_are_kept_not_overwritten(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")  # freeze before calculating the actual command/receipt sequence
        seq = len(repo.events()) + 2  # run.started takes the next seq; the receipt follows it
        old = repo.path / ".goal-teams" / "evidence" / ("R%d.log" % seq)
        old.write_text("old", encoding="utf-8")
        repo.ok("run", "T1", "--kind", "lint", "--", sys.executable, "-c", "pass")
        kept = repo.path / ".goal-teams" / "evidence" / "orphans" / ("R%d.1.log" % seq)
        self.assertEqual(kept.read_text(encoding="utf-8"), "old")
        self.assertNotEqual(old.read_text(encoding="utf-8"), "old")
        self.assertIn("不属于当前账本", repo.ok("verify"))

    def test_mistaken_runs_can_be_retired_and_typos_are_not_failures(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        typo = repo.gt("run", "T1", "--kind", "affected", "--", "pyhton3-no-such", "-m", "unittest")
        self.assertEqual(typo.returncode, 2)
        self.assertIn("没有运行起来", typo.stdout)
        wrong = repo.gt("run", "T1", "--kind", "affected", "--", sys.executable, "-c", "import sys; sys.exit(2)")
        self.assertEqual(wrong.returncode, 1)
        rid = [e for e in repo.events() if e["type"] == "run"][-1]["data"]["id"]
        self.assertIn("检查未通过：%s" % rid, repo.gt("check").stdout)
        self.assertEqual(repo.gt("retire", rid, "--reason", "x").returncode, 2, "a real reason is required")
        repo.ok("retire", rid, "--reason", "路径写错了，命令本身不对")
        check = repo.gt("check").stdout
        self.assertNotIn("检查未通过：%s" % rid, check)
        self.assertIn("已撤销的检查失败：%s" % rid, check)

    def test_failures_of_cancelled_tasks_do_not_block(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "add", "T2", "x", "--owner", "goal_frontend", "--validator", "goal_reviewer",
                "--scope", "web/**", "--accept", "a", "--exit", "e")
        repo.gt("run", "T2", "--kind", "affected", "--", sys.executable, "-c", "import sys; sys.exit(1)")
        repo.ok("task", "cancel", "T2", "--reason", "用户缩小了范围")
        self.assertNotIn("检查未通过", repo.gt("check").stdout)

    def test_new_test_file_bound_by_red_is_in_scope(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--done", "d", "--size", "medium")
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/calc.py", "--accept", "a", "--exit", "e", "--tdd")
        repo.write("tests/test_add_edge.py", TEST_NEW.replace("class T(", "class E("))
        self.assertIn("越界", repo.gt("diff").stdout)
        repo.ok("tdd", "red", "T1", "--test", "tests/test_add_edge.py", "--expect", "AssertionError",
                "--", sys.executable, "-m", "unittest", "-q", "tests.test_add_edge")
        self.assertNotIn("越界", repo.gt("diff").stdout)

    def test_check_from_a_linked_worktree_judges_the_main_tree(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("plan", "apply")
        wt = repo.path.parent / "wt2"
        repo.run_git("worktree", "add", "-q", "-b", "fix", str(wt))
        env = dict(os.environ, GT_NOW="2026-10-18T08:00:00Z", PYTHONDONTWRITEBYTECODE="1")

        def gt(*args):
            return subprocess.run([sys.executable, str(GT), *args], cwd=wt, capture_output=True, text=True,
                                  encoding="utf-8", env=env)

        (wt / "tests" / "test_calc.py").write_text(TEST_NEW, encoding="utf-8")
        self.assertEqual(gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError",
                            "--", *UNITTEST).returncode, 0)
        (wt / "src" / "calc.py").write_text(FIXED, encoding="utf-8")
        self.assertEqual(gt("tdd", "green", "T1").returncode, 0)
        self.assertEqual(gt("task", "done", "T1").returncode, 0)
        self.assertEqual(gt("review", "T1", "--by", "goal_reviewer", "--verdict", "pass").returncode, 0)
        check = gt("check")
        self.assertEqual(check.returncode, 1, check.stdout)
        self.assertIn("以主工作树为准", check.stdout)

    def test_nested_worktree_is_not_an_out_of_scope_change(self):
        repo = self.repo
        medium_goal(repo)
        repo.run_git("worktree", "add", "-q", "-b", "nested", str(repo.path / ".worktrees" / "a"))
        self.assertNotIn(".worktrees", repo.gt("diff").stdout)

    def test_test_outputs_do_not_stale_their_own_evidence(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        repo.write("src/calc.py", FIXED)
        report = [sys.executable, "-c", "import time; open('test-report.txt', 'w').write(str(time.time()))"]
        undeclared = repo.gt("run", "T1", "--kind", "affected", "--", *report)
        self.assertIn("未声明的文件 test-report.txt", undeclared.stderr)
        repo.ok("run", "T1", "--kind", "affected", "--output", "test-report.txt", "--", *report)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        receipt = [e for e in repo.events() if e["type"] == "run"][-1]["data"]
        self.assertEqual(receipt["outputs"], ["test-report.txt"])
        settle(repo)
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        repo.ok("rerun", "T1")  # the report changes again: still fresh
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)

    def test_regenerated_code_is_never_exempt(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("scope", "allow", "gen/**", "--reason", "生成的常量")
        repo.ok("plan", "apply")
        codegen = [sys.executable, "-c", "import os, sys; os.makedirs('gen', exist_ok=True); "
                   "open('gen/consts.py', 'w').write('OFFSET = %s\\n' % sys.argv[1])"]
        repo.ok("run", "-", "--kind", "other", "--name", "codegen", "--", *codegen, "0")
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        settle(repo)
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        repo.ok("run", "-", "--kind", "other", "--name", "codegen", "--", *codegen, "1")
        self.assertIn("没有在最终代码上通过的测试记录", repo.gt("check").stdout)
        self.assertEqual(repo.gt("run", "-", "--kind", "other", "--output", "gen/consts.py", "--", *codegen, "2").returncode,
                         2, "source files cannot be declared as outputs")

    def test_outputs_inside_code_scopes_are_still_code(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        repo.write("src/calc.py", FIXED)
        sneaky = [sys.executable, "-c", "open('src/calc.py', 'w').write('def add(a, b):\\n    return a - b\\n')"]
        repo.ok("run", "T1", "--kind", "affected", "--", *sneaky)
        receipt = [e for e in repo.events() if e["type"] == "run"][-1]["data"]
        self.assertNotIn("outputs", receipt)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        self.assertIn("没有在最终代码上通过的测试记录", repo.gt("check").stdout)

    def test_code_parent_covered_only_by_a_doc_child_needs_evidence(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--done", "d", "--size", "medium")
        repo.ok("task", "add", "P", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/**", "--accept", "a", "--exit", "e")
        repo.ok("task", "add", "P.d", "doc", "--parent", "P", "--kind", "doc", "--owner", "goal_docs",
                "--validator", "goal_reviewer", "--scope", "src/**", "--accept", "a")
        repo.ok("plan", "apply")
        repo.write("src/other.py", "broken = (\n")
        repo.ok("task", "done", "P.d")
        repo.ok("review", "P.d", "--by", "goal_reviewer", "--verdict", "pass")
        repo.ok("task", "done", "P")
        repo.ok("review", "P", "--by", "goal_reviewer", "--verdict", "pass")
        self.assertIn("P 没有在最终代码上通过的测试记录", repo.gt("check").stdout)

    def test_fixtures_in_the_tasks_own_scope_are_not_an_implementation(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("task", "edit", "T1", "--add-scope", "tests/**")
        repo.write("tests/test_calc.py", TEST_NEW)
        repo.ok("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        repo.write("tests/data/case.json", "{}")
        self.assertIn("范围内的实现与 Red 时相同", repo.gt("tdd", "green", "T1").stdout)

    def test_done_ignores_other_tasks_work_in_progress(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("task", "add", "T2", "other", "--owner", "goal_frontend", "--validator", "goal_reviewer",
                "--scope", "src/other.py", "--accept", "a", "--exit", "e")
        repo.ok("plan", "apply")
        red_green(repo)
        repo.write("src/other.py", "wip = 1\n")  # a parallel member is still working
        repo.ok("task", "done", "T1")

    def test_declarations_must_be_new_files_and_stay_visible(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.write("lib/helper.py", "def plus(a, b):\n    return a + b\n")
        repo.run_git("add", "lib/helper.py")
        repo.run_git("commit", "-qm", "helper")
        repo.ok("goal", "g2", "--done", "d", "--size", "medium", "--replace")  # baseline now has lib/helper.py
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/calc.py", "--accept", "a", "--exit", "e")
        repo.run_git("rm", "-q", "--cached", "lib/helper.py")
        flip = repo.gt("run", "-", "--kind", "build", "--artifact", "lib/helper.py", "--", sys.executable, "-c", "pass")
        self.assertEqual(flip.returncode, 2)
        self.assertIn("目标开始时就是项目里的文件", flip.stderr)
        report = [sys.executable, "-c", "open('test-report.txt', 'w').write('ok')"]
        repo.ok("run", "T1", "--kind", "affected", "--output", "test-report.txt", "--", *report)
        self.assertIn("声明为命令输出、不计入源码的文件：test-report.txt", repo.gt("check").stdout)
        repo.ok("loop", "decide", "continue", "--next", "n")
        self.assertIn("test-report.txt", repo.ok("report", "--summary", "s"))
        # a later code scope that covers the path ends the declaration
        repo.ok("task", "edit", "T1", "--add-scope", "test-report.txt")
        self.assertNotIn("声明为命令输出", repo.gt("check").stdout)

    def test_code_under_fixtures_is_flagged_at_freeze(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("task", "edit", "T1", "--add-scope", "src/**")
        repo.write("src/fixtures/impl.py", "x = 1\n")
        self.assertIn("像测试或测试数据的代码文件 src/fixtures/impl.py", repo.ok("plan", "apply"))

    def test_broad_test_scope_is_flagged_at_freeze(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("task", "add", "T1.t", "tests", "--parent", "T1", "--kind", "test", "--owner", "goal_unit_test_designer",
                "--validator", "goal_reviewer", "--scope", ".", "--accept", "a", "--exit", "e")
        self.assertIn("包含代码文件 src/calc.py", repo.ok("plan", "apply"))

    def test_retired_failures_are_in_the_outcome_line(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        repo.write("src/calc.py", FIXED)
        repo.gt("run", "T1", "--kind", "affected", "--name", "suite", "--", sys.executable, "-c", "import sys; sys.exit(1)")
        rid = [e for e in repo.events() if e["type"] == "run"][-1]["data"]["id"]
        repo.ok("retire", rid, "--reason", "环境里缺少数据库，和本次改动无关")
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        settle(repo)
        repo.ok("loop", "decide", "stop", "--outcome", "achieved", "--next", "无")
        self.assertIn("撤销过检查失败 %s" % rid, repo.ok("report", "--summary", "s"))

    def test_manual_readback_evidence_must_exist(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        bad = repo.gt("run", "-", "--kind", "release", "--manual", "--result", "pass", "--note", "n",
                      "--evidence", "trust me")
        self.assertEqual(bad.returncode, 2)
        repo.ok("run", "-", "--kind", "release", "--manual", "--result", "pass", "--note", "n",
                "--evidence", "https://example.com/releases/v1")

    def test_nits(self):
        repo = self.repo
        medium_goal(repo)
        repo.write("tests/test_calc.py", "import nonexistent_module\n")
        result = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "exit: 1", "--", *UNITTEST)
        self.assertEqual(result.returncode, 1, "gt's own log footer must not satisfy --expect")
        self.assertEqual(repo.gt("review", "@goal", "--by", "Lead", "--verdict", "pass").returncode, 2)
        repo.ok("goal", "--size", "large")
        self.assertIn("预计 5 轮", repo.ok("goal", "--show"))


@unittest.skipUnless(HAS_GIT, "git required")
class ExternalReviewTests(unittest.TestCase):
    """Regressions for the findings of the external review (R01, R02, R03, R05, R12)."""

    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_r01_spec_change_stales_the_review(self):
        repo = self.repo
        accepted_tdd_task(repo)
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        repo.ok("task", "edit", "T1", "--accept", "add(2,3)==6", "--validator", "goal_security")
        repo.ok("plan", "apply")
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("任务规格", check.stdout)
        self.assertIn("评审已过期", repo.ok("task", "list"))
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)  # new graph revision needs current evidence
        repo.ok("review", "T1", "--by", "goal_security", "--verdict", "pass")  # the new validator re-reviews
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)

    def test_r02_ui_and_agent_gates_block_completion(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--done", "d", "--check", shlex.join(UNITTEST), "--size", "medium", "--ui", "--agent")
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/calc.py", "--scope", "tests/test_calc.py", "--accept", "a", "--exit", "e", "--tdd")
        repo.ok("plan", "apply")
        red_green(repo)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        settle(repo)
        check = repo.gt("check").stdout
        self.assertIn("E2E：缺少", check)
        self.assertIn("Agent 评测：缺少", check)
        repo.ok("run", "T1", "--kind", "e2e", "--", sys.executable, "-c", "pass")
        repo.ok("run", "T1", "--kind", "eval", "--name", "baseline", "--", sys.executable, "-c", "pass")
        self.assertIn("Agent 评测：缺少", repo.gt("check").stdout, "one group is not a comparison")
        repo.ok("run", "T1", "--kind", "eval", "--name", "agent", "--", sys.executable, "-c", "pass")
        self.assertEqual(repo.gt("check").returncode, 0, repo.gt("check").stdout)
        repo.write("src/calc.py", FIXED + "# later\n")
        self.assertIn("E2E：缺少", repo.gt("check").stdout, "gates are bound to the source")

    def test_r02_plain_goals_are_not_gated(self):
        repo = self.repo
        accepted_tdd_task(repo)
        check = repo.gt("check").stdout
        self.assertNotIn("E2E", check)
        self.assertNotIn("Agent 评测", check)

    def release_ready(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "ship", "--done", "d", "--check", shlex.join(UNITTEST), "--size", "medium", "--release")
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/calc.py", "--scope", "tests/test_calc.py", "--accept", "a", "--exit", "e", "--tdd")
        repo.ok("plan", "apply")
        red_green(repo)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass", "--note", "核对了改动与回执")
        settle(repo)
        repo.ok("run", "-", "--kind", "regression", "--", *UNITTEST)
        repo.ok("review", "@goal", "--by", "goal_security", "--verdict", "pass", "--note", "核对了改动与回执")
        build = [sys.executable, "-c", "import os; os.makedirs('dist', exist_ok=True); open('dist/a.tgz', 'w').write('x')"]
        repo.ok("run", "-", "--kind", "build", "--artifact", "dist/a.tgz", "--", *build)
        self.assertEqual(repo.gt("check", "--release").returncode, 0, repo.gt("check", "--release").stdout)

    def test_r03_deleted_or_replaced_artifact_fails_the_release_check(self):
        repo = self.repo
        self.release_ready()
        (repo.path / "dist" / "a.tgz").write_text("y", encoding="utf-8")
        check = repo.gt("check", "--release")
        self.assertEqual(check.returncode, 1)
        self.assertIn("内容已变", check.stdout)
        (repo.path / "dist" / "a.tgz").unlink()
        self.assertIn("缺失", repo.gt("check", "--release").stdout)

    def test_r03_readback_is_bound_to_the_built_asset_set(self):
        repo = self.repo
        self.release_ready()
        repo.ok("run", "-", "--kind", "release", "--", sys.executable, "-c", "pass")
        receipt = [e for e in repo.events() if e["type"] == "run"][-1]["data"]
        self.assertTrue(receipt.get("assets_digest"))
        repo.ok("loop", "decide", "stop", "--outcome", "achieved", "--next", "无")
        # a rebuild with different assets after the readback invalidates it
        repo.ok("goal", "ship2", "--done", "d", "--size", "medium", "--release", "--replace")

    def test_r05_late_receipt_of_a_replaced_goal_is_kept_apart(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("plan", "apply")
        slow = subprocess.Popen([sys.executable, str(GT), "run", "T1", "--kind", "affected", "--",
                                 sys.executable, "-c", "import time; time.sleep(2.5)"], cwd=repo.path,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=dict(os.environ, GT_NOW="2026-10-18T08:00:00Z"))
        time.sleep(0.6)
        repo.ok("goal", "g2", "--done", "d", "--size", "medium", "--replace")
        repo.ok("task", "add", "T1", "new T1", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/calc.py", "--accept", "a", "--exit", "e")
        _, err = slow.communicate(timeout=30)
        self.assertEqual(slow.returncode, 0)
        self.assertIn("被替换", err)
        sys.path.insert(0, str(SCRIPTS))
        from goalteams.ledger import Project
        from goalteams.state import reduce
        state = reduce(Project(repo.path.resolve()).events())
        self.assertEqual([r["id"] for r in state.receipts_of("T1")], [])
        self.assertEqual(len(state.foreign_receipts), 1)

    def test_r05_concurrent_duplicate_ids_are_refused_under_the_lock(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        codes = []

        def one(i):
            codes.append(repo.gt("task", "add", "T9", "dup %d" % i, "--owner", "goal_backend",
                                 "--validator", "goal_reviewer", "--scope", "src/**", "--accept", "a",
                                 "--exit", "e").returncode)

        threads = [threading.Thread(target=one, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(codes.count(0), 1)
        self.assertEqual(sum(1 for e in repo.events() if e["type"] == "task.add" and e["data"]["id"] == "T9"), 1)

    def test_r05_state_change_is_rechecked_under_the_lock(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("task", "start", "T1")
        # a second context cancels the task between the snapshot and the append
        sys.path.insert(0, str(SCRIPTS))
        from goalteams.ledger import Project
        from goalteams.util import GTError
        project = Project(repo.path.resolve())
        project.append("task.state", {"id": "T1", "to": "cancelled", "reason": "x"}, "lead")
        result = repo.gt("task", "done", "T1")
        self.assertEqual(result.returncode, 2)
        del GTError

    def test_r12_auth_check_binds_the_repository(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.run_git("remote", "add", "origin", "https://github.com/example/other.git")
        repo.ok("auth", "grant", "--actions", "push", "--scope", "A only", "--repo", "git@github.com:example/A.git")
        result = repo.gt("auth", "check", "push")
        self.assertEqual(result.returncode, 3)
        self.assertIn("绑定仓库", result.stdout)
        repo.ok("auth", "grant", "--actions", "push", "--scope", "this repo", "--repo", "git@github.com:example/other.git")
        ok = repo.gt("auth", "check", "push")
        self.assertEqual(ok.returncode, 0)
        self.assertIn("由你核对", ok.stdout)

    def test_r12_self_review_can_be_refused_by_policy(self):
        repo = self.repo
        medium_goal(repo)
        repo.ok("plan", "apply")
        red_green(repo)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_backend", "--verdict", "pass", "--self")
        settle(repo)
        self.assertEqual(repo.gt("check").returncode, 0)
        repo.ok("config", "set", "require_independent_review", "true")
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("保证等级是 self", check.stdout)


class UnitTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "process groups are POSIX here")
    def test_timeout_stops_grandchildren(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "x.log"
            code = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', " \
                   "'import time; time.sleep(2); print(\"LA\" + \"TE-OUTPUT\", flush=True)']); time.sleep(10)"
            result = runner.execute([sys.executable, "-c", "import time\n" + code], Path(tmp), log, timeout=1)
            self.assertEqual(result["exit_code"], 124)
            time.sleep(2.5)
            self.assertNotIn("LATE-OUTPUT", log.read_text(encoding="utf-8"))

    def test_lock_of_a_dead_process_is_broken_at_once(self):
        import tempfile
        from goalteams import util
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".lock"
            proc = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True,
                                  text=True)
            path.write_text("%s %s 2026-01-01T00:00:00Z\n" % (proc.stdout.strip(), util._HOST), encoding="ascii")
            started = time.monotonic()
            with FileLock(path, timeout=5):
                pass
            self.assertLess(time.monotonic() - started, 2)

    def test_hook_ignores_non_object_payloads(self):
        self.assertEqual(hook.stop(io.StringIO("[1, 2]")), 0)
        self.assertEqual(hook.stop(io.StringIO("not json")), 0)


if __name__ == "__main__":
    unittest.main()
