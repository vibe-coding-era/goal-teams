"""V2.9 P1: one completion contract, policy-derived gates, atomic plans, TDD confirm, assurance levels."""

from __future__ import annotations

import shlex
import json
import sys
import unittest

from tests.test_gt import FIXED, HAS_GIT, SCRIPTS, TEST_NEW, UNITTEST, Repo, red_green

sys.path.insert(0, str(SCRIPTS))
from goalteams import policy  # noqa: E402
from goalteams.util import GTError  # noqa: E402

PLAN = {
    "tasks": [
        {"id": "T1", "title": "修复 add", "owner": "goal_backend", "validator": "goal_reviewer",
         "scope": ["src/calc.py", "tests/test_calc.py"], "accept": "add(2,3)==5", "exit": "测试通过", "tdd": True},
        {"id": "T2", "title": "文档", "owner": "goal_backend", "validator": "goal_reviewer", "kind": "doc",
         "scope": ["README.md"], "accept": "README 说明 add", "exit": "评审通过", "deps": ["T1"]},
    ]
}


def tracked_goal(repo: Repo, risk: str = "normal", check: bool = True) -> None:
    repo.ok("init")
    args = ["goal", "修复 add", "--done", "add(2,3)==5", "--mode", "tracked", "--risk", risk]
    if check:
        args += ["--check", shlex.join(UNITTEST)]
    repo.ok(*args)


def write_plan(repo: Repo, plan: dict) -> str:
    repo.write(".goal-teams/plan.json", json.dumps(plan, ensure_ascii=False))
    return ".goal-teams/plan.json"


def apply_plan(repo: Repo, plan: dict = None) -> str:
    return repo.ok("plan", "apply", write_plan(repo, plan or PLAN))


class PolicyTests(unittest.TestCase):
    def test_mode_does_not_change_quality_gates(self):  # AC01
        direct = policy.required_gates("direct", "high", ["code", "ui"], "behavior_change", "development")
        tracked = policy.required_gates("tracked", "high", ["code", "ui"], "behavior_change", "development")
        quality = lambda gates: {n: (g.required, g.min_assurance) for n, g in gates.items() if g.kind != "coordination"}
        self.assertEqual(quality(direct), quality(tracked))
        self.assertTrue(tracked["plan"].required)
        self.assertFalse(direct["plan"].required)
        self.assertEqual(direct["plan"].kind, "coordination")
        self.assertTrue(direct["e2e"].required)
        self.assertEqual(direct["review"].min_assurance, "correlated_reviewer")

    def test_impact_decides_tdd_and_e2e_not_the_domain_label(self):  # AC02
        docs = policy.required_gates("direct", "normal", ["code", "ui"], "docs_only", "development")
        self.assertFalse(docs["tdd"].required)
        self.assertFalse(docs["e2e"].required)
        self.assertIn("文档", docs["tdd"].reason)
        style = policy.required_gates("tracked", "normal", ["ui"], "presentation_only", "development")
        self.assertFalse(style["e2e"].required)
        self.assertTrue(style["visual"].required)
        plain = policy.required_gates("direct", "normal", ["code"], "behavior_change", "development")
        self.assertFalse(plain["e2e"].required)
        self.assertFalse(plain["agent_eval"].required)
        self.assertEqual(plain["review"].min_assurance, "self")
        agent = policy.required_gates("direct", "normal", ["agent"], "behavior_change", "development")
        self.assertTrue(agent["agent_eval"].required)
        release = policy.required_gates("tracked", "normal", ["code"], "behavior_change", "release")
        for gate in ("regression", "build", "security", "readback"):
            self.assertTrue(release[gate].required, gate)
        self.assertEqual(release["review"].min_assurance, "correlated_reviewer")

    def test_legacy_sizes_map_to_mode_and_risk(self):
        self.assertEqual(policy.from_legacy("small")["mode"], "direct")
        self.assertEqual(policy.from_legacy("medium")["mode"], "tracked")
        large = policy.from_legacy("large", ui=True)
        self.assertEqual((large["mode"], large["risk"]), ("tracked", "high"))
        self.assertIn("ui", large["domains"])
        self.assertIn("rules/ui.md", policy.rule_files("tracked", ["ui"], "development"))

    def test_assurance_ranking(self):
        self.assertTrue(policy.assurance_at_least("correlated_reviewer", "self"))
        self.assertFalse(policy.assurance_at_least("self_reported", "correlated_reviewer"))
        with self.assertRaises(ValueError):
            policy.assurance_at_least("made_up", "self")


@unittest.skipUnless(HAS_GIT, "git required")
class PlanTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        tracked_goal(self.repo)

    def tearDown(self):
        self.repo.close()

    def test_plan_apply_is_atomic(self):  # AC06
        repo = self.repo
        broken = {"tasks": [dict(PLAN["tasks"][0]), dict(PLAN["tasks"][1], deps=["T9"])]}
        path = write_plan(repo, broken)
        before = len(repo.events())
        result = repo.gt("plan", "apply", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("T9", result.stderr)
        self.assertEqual(len(repo.events()), before, "an invalid plan changes nothing")
        out = apply_plan(repo)
        self.assertIn("r1", out)
        applied = [e for e in repo.events() if e["type"] == "plan.applied"]
        self.assertEqual(len(applied), 1)
        self.assertEqual([t["id"] for t in applied[0]["data"]["tasks"]], ["T1", "T2"])
        listing = json.loads(repo.ok("--json", "task", "list"))
        self.assertEqual([t["id"] for t in listing], ["T1", "T2"])

    def test_manual_edits_share_the_revision_counter(self):  # AC06
        repo = self.repo
        apply_plan(repo)
        repo.ok("task", "edit", "T1", "--accept", "add(2,3)==5 且 add(-1,1)==0")
        show = json.loads(repo.ok("--json", "plan", "show"))
        self.assertEqual(show["plan"]["revision"], 2)
        self.assertTrue(show["plan"]["changes_since_apply"])
        repo.ok("task", "add", "T3", "更多", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/more.py", "--accept", "x", "--exit", "y")
        self.assertEqual(json.loads(repo.ok("--json", "plan", "show"))["plan"]["revision"], 3)
        # re-applying the same file is a no-op for the tasks but records the validated revision
        out = apply_plan(repo)
        self.assertIn("r4", out)
        cycle = {"tasks": [dict(PLAN["tasks"][0], deps=["T2"]), dict(PLAN["tasks"][1])]}
        result = repo.gt("plan", "apply", write_plan(repo, cycle))
        self.assertEqual(result.returncode, 2)
        self.assertIn("成环", result.stderr)

    def test_tracked_goal_without_a_plan_is_not_complete_and_no_freeze_is_needed(self):
        repo = self.repo
        check = repo.gt("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("没有登记任务", check.stdout)
        apply_plan(repo)
        check = repo.gt("check")
        self.assertNotIn("冻结", check.stdout)
        self.assertIn("计划 r1", check.stdout)


@unittest.skipUnless(HAS_GIT, "git required")
class CompletionContractTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def finish_tracked(self, repo: Repo) -> None:
        tracked_goal(repo)
        apply_plan(repo, {"tasks": [PLAN["tasks"][0]]})
        red_green(repo)
        repo.ok("task", "done", "T1", "--as", "goal_backend")

    def test_every_entry_reads_the_same_result(self):  # AC05
        repo = self.repo
        self.finish_tracked(repo)
        finish = repo.gt("--json", "finish")   # tops up the criterion check, then judges
        check = repo.gt("--json", "check")     # read-only, same snapshot afterwards
        self.assertEqual((check.returncode, finish.returncode), (1, 1))
        check_json, finish_json = json.loads(check.stdout), json.loads(finish.stdout)
        self.assertEqual(check_json["status"], finish_json["status"])
        self.assertEqual(check_json["reasons"], finish_json["reasons"])
        self.assertEqual(check_json["snapshot_ref"], finish_json["snapshot_ref"])
        stop = repo.gt("loop", "decide", "stop", "--outcome", "achieved")
        self.assertEqual(stop.returncode, 1)
        report = json.loads(repo.ok("--json", "report"))
        self.assertEqual(report["meta"]["status"], check_json["status"])
        self.assertEqual(report["meta"]["snapshot_ref"], check_json["snapshot_ref"])

    def test_finish_waits_for_the_review_then_reuses_current_evidence(self):
        repo = self.repo
        self.finish_tracked(repo)
        first = repo.gt("--json", "finish")
        self.assertEqual(first.returncode, 1)
        self.assertEqual(json.loads(first.stdout)["status"], "review_required")
        runs_before = [e for e in repo.events() if e["type"] in ("run", "tdd.green")]
        repo.write(".goal-teams/reviews.json", json.dumps([{"task": "T1", "by": "goal_reviewer", "verdict": "pass", "note": "ok"}]))
        repo.ok("review", "--file", ".goal-teams/reviews.json")
        second = repo.gt("--json", "finish")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        payload = json.loads(second.stdout)
        self.assertEqual(payload["status"], "achieved")
        self.assertTrue(payload["goal_achieved"])
        runs_after = [e for e in repo.events() if e["type"] in ("run", "tdd.green")]
        self.assertEqual(len(runs_before), len(runs_after), "current evidence is reused, not re-run")
        self.assertEqual([e["type"] for e in repo.events()][-1], "goal.finished")
        again = repo.gt("--json", "finish")
        self.assertEqual(again.returncode, 0)
        self.assertEqual(len([e for e in repo.events() if e["type"] == "goal.finished"]), 1, "finish is idempotent")

    def test_finish_reruns_stale_evidence_and_criteria_checks(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "修复 add", "--done", "add(2,3)==5", "--check", shlex.join(UNITTEST), "--mode", "tracked")
        apply_plan(repo, {"tasks": [PLAN["tasks"][0]]})
        red_green(repo)
        repo.ok("task", "done", "T1", "--as", "goal_backend")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        repo.write("src/calc.py", FIXED + "\n# touched after green\n")
        result = repo.gt("--json", "finish")
        payload = json.loads(result.stdout)
        kinds = [e["data"].get("kind") or e["type"] for e in repo.events() if e["type"] in ("run", "tdd.green")]
        self.assertIn("tdd.green", kinds[-2:], "the stale Green was re-run on the final code")
        self.assertIn("acceptance", kinds, "the criterion's --check command was run")
        self.assertEqual(payload["status"], "review_required", payload)  # the review is stale now
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        final = json.loads(repo.ok("--json", "finish"))
        self.assertEqual(final["status"], "achieved")
        self.assertEqual(final["criteria"][0]["status"], "passed")

    def test_goal_accept_is_self_reported_and_goes_stale_when_the_criterion_changes(self):  # AC03, AC16
        repo = self.repo
        tracked_goal(repo, check=False)
        apply_plan(repo, {"tasks": [PLAN["tasks"][0]]})
        red_green(repo)
        repo.ok("task", "done", "T1", "--as", "goal_backend")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertEqual(check["status"], "acceptance_required")
        self.assertIn("C1", "\n".join(check["reasons"]))
        repo.ok("goal", "accept", "--item", "C1", "--result", "pass", "--quote", "用户：add(2,3) 返回 5 了")
        repo.ok("goal", "--add-done", "用户确认界面可用")
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertEqual(check["status"], "blocked", "new criteria invalidate the frozen task graph")
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertEqual(check["status"], "acceptance_required")
        accept = repo.ok("--json", "goal", "accept", "--item", "C2", "--result", "pass", "--quote", "用户：可以了")
        self.assertEqual(json.loads(accept)["assurance"], "self_reported")
        check = json.loads(repo.ok("--json", "check"))
        self.assertEqual(check["status"], "achieved")
        self.assertIn("未经用户系统确认", "\n".join(check["notes"]))
        repo.ok("goal", "--edit-done", "C2", "用户确认界面可用且无报错")
        check = repo.gt("--json", "check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("C2", "\n".join(json.loads(check.stdout)["reasons"]))
        self.assertIn("已过期", "\n".join(json.loads(check.stdout)["reasons"]))

    def test_review_assurance_is_recorded_from_facts_not_role_names(self):  # AC16
        repo = self.repo
        self.finish_tracked(repo)
        self.assertEqual(repo.gt("review", "T1", "--by", "goal_backend", "--verdict", "pass").returncode, 2)
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        reviews = [e["data"] for e in repo.events() if e["type"] == "review"]
        self.assertEqual(reviews[-1]["assurance"], "correlated_reviewer")
        repo.ok("review", "@goal", "--by", "user", "--verdict", "pass", "--note", "用户说 OK")
        reviews = [e["data"] for e in repo.events() if e["type"] == "review"]
        self.assertEqual(reviews[-1]["assurance"], "self_reported")
        repo.ok("review", "T1", "--by", "lead", "--verdict", "pass", "--self")
        reviews = [e["data"] for e in repo.events() if e["type"] == "review"]
        self.assertEqual(reviews[-1]["assurance"], "self")


@unittest.skipUnless(HAS_GIT, "git required")
class DirectModeTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_first_evidence_command_creates_the_minimal_state(self):
        repo = self.repo
        self.assertFalse((repo.path / ".goal-teams").exists())
        repo.write("tests/test_calc.py", TEST_NEW)
        red = repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--", *UNITTEST)
        self.assertEqual(red.returncode, 0, red.stdout + red.stderr)
        self.assertTrue((repo.path / ".goal-teams" / "ledger.jsonl").is_file())
        goal = json.loads(repo.ok("--json", "goal", "--show"))
        self.assertEqual(goal["mode"], "direct")
        self.assertEqual(goal["evidence_mode"], "tracked")
        reds = [e["data"] for e in repo.events() if e["type"] == "tdd.red"]
        self.assertEqual(reds[0]["outcome"], "red_observed")
        repo.write("src/calc.py", FIXED)
        repo.ok("tdd", "green", "T1")
        finish = repo.gt("--json", "finish")
        payload = json.loads(finish.stdout)
        self.assertEqual(finish.returncode, 1, payload)
        self.assertIn("red_observed", "\n".join(payload["reasons"]))
        repo.ok("tdd", "confirm", reds[0]["id"], "--expect", "AssertionError")
        finish = repo.gt("--json", "finish")
        self.assertEqual(finish.returncode, 0, finish.stdout + finish.stderr)
        self.assertEqual(json.loads(finish.stdout)["status"], "achieved")
        self.assertIn("evidence_mode=tracked", repo.ok("report"))

    def test_discussion_leaves_no_state_behind(self):
        repo = self.repo
        result = repo.gt("check")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((repo.path / ".goal-teams").exists())


@unittest.skipUnless(HAS_GIT, "git required")
class TddConfirmTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.ok("init")
        self.repo.ok("goal", "修复 add", "--done", "add(2,3)==5", "--mode", "direct")
        self.repo.write("tests/test_calc.py", TEST_NEW)

    def tearDown(self):
        self.repo.close()

    def red(self, *extra: str) -> dict:
        self.repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", *extra, "--", *UNITTEST)
        return [e["data"] for e in self.repo.events() if e["type"] == "tdd.red"][-1]

    def test_confirm_reads_the_original_log_and_refuses_tampering(self):  # AC08
        repo = self.repo
        red = self.red()
        self.assertEqual(red["outcome"], "red_observed")
        wrong = repo.gt("tdd", "confirm", red["id"], "--expect", "ImportError")
        self.assertEqual(wrong.returncode, 1)
        confirms = [e["data"] for e in repo.events() if e["type"] == "tdd.confirm"]
        self.assertEqual(confirms[-1]["matched"], False)
        repo.ok("tdd", "confirm", red["id"], "--expect", "AssertionError", "--note", "期望 5 得到 -1")
        confirms = [e["data"] for e in repo.events() if e["type"] == "tdd.confirm"]
        self.assertEqual(confirms[-1]["matched"], True)
        log = repo.path / red["log"]
        log.write_text(log.read_text(encoding="utf-8") + "AssertionError: forged\n", encoding="utf-8")
        tampered = repo.gt("tdd", "confirm", red["id"], "--expect", "forged")
        self.assertEqual(tampered.returncode, 1)
        self.assertIn("日志", tampered.stderr)
        self.assertEqual(len([e for e in repo.events() if e["type"] == "tdd.confirm"]), 2, "a tampered log records nothing")

    def test_expect_on_the_red_itself_verifies_at_once_and_invalid_reds_cannot_be_confirmed(self):
        repo = self.repo
        verified = self.red("--expect", "AssertionError")
        self.assertEqual(verified["outcome"], "red_verified")
        self.assertEqual(repo.gt("tdd", "confirm", verified["id"], "--expect", "x").returncode, 2)
        repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--", "no-such-command-xyz")
        invalid = [e["data"] for e in repo.events() if e["type"] == "tdd.red"][-1]
        self.assertEqual(invalid["outcome"], "red_invalid")
        self.assertEqual(repo.gt("tdd", "confirm", invalid["id"], "--expect", "found").returncode, 2)


@unittest.skipUnless(HAS_GIT, "git required")
class ResumeAndReportTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_resume_has_the_six_sections_and_report_formats(self):
        repo = self.repo
        tracked_goal(repo)
        apply_plan(repo, {"tasks": [PLAN["tasks"][0]]})
        repo.ok("auth", "grant", "--actions", "push", "--scope", "本仓库 feature 分支")
        red_green(repo)
        repo.ok("memory", "add", "用户要求不改公共 API", "--section", "用户设置")
        resume = repo.ok("resume")
        for heading in ("已解决", "试过并放弃", "用户决定与约束", "当前进度", "未决事项", "难以重建的细节"):
            self.assertIn(heading, resume)
        self.assertIn("不改公共 API", resume)
        self.assertIn("push", resume)
        payload = json.loads(repo.ok("--json", "resume"))
        self.assertIn("bytes", payload)
        brief = repo.ok("report")
        for heading in ("结果", "关键证据", "未完成"):
            self.assertIn(heading, brief)
        six = repo.ok("report", "--format", "six")
        self.assertIn("◆ Goal-Teams", six)

    def test_exit_codes_are_central(self):
        from goalteams.util import EXIT
        self.assertEqual((EXIT.ok, EXIT.unverified, EXIT.usage, EXIT.blocked, EXIT.conflict), (0, 1, 2, 3, 4))
        repo = self.repo
        tracked_goal(repo)
        self.assertEqual(repo.gt("auth", "check", "push").returncode, 3)
        self.assertEqual(repo.gt("task", "edit", "nope", "--title", "x").returncode, 2)
        self.assertEqual(GTError("x", code=EXIT.conflict).code, 4)


if __name__ == "__main__":
    unittest.main()
