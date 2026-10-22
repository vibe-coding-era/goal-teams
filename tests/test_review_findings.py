"""Regressions for the independent review of develop-v2.9 (findings 1–11)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest

from tests.test_gt import FIXED, HAS_GIT, SCRIPTS, UNITTEST, Repo, medium_goal, settle

sys.path.insert(0, str(SCRIPTS))

PY = sys.executable
TRUE = [PY, "-c", "pass"]
FALSE = [PY, "-c", "import sys; sys.exit(1)"]


def direct_goal(repo: Repo, *extra: str) -> None:
    repo.ok("init")
    repo.ok("goal", "g", "--mode", "direct", *extra)
    repo.ok("task", "add", "T1", "x", "--scope", "src/calc.py", "--accept", "a", "--exit", "e")


@unittest.skipUnless(HAS_GIT, "git required")
class FindingTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_1_a_check_criterion_needs_its_own_command(self):
        repo = self.repo
        direct_goal(repo, "--done", "tests pass", "--check", " ".join(FALSE), "--impact", "config_change")
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--", *TRUE)
        repo.ok("task", "done", "T1")
        refused = repo.gt("run", "-", "--kind", "acceptance", "--name", "C1", "--manual", "--result", "pass", "--note", "x")
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(repo.gt("run", "-", "--kind", "acceptance", "--name", "C1", "--", *TRUE).returncode, 2)
        finish = repo.gt("--json", "finish")
        self.assertEqual(finish.returncode, 1)
        self.assertEqual(json.loads(finish.stdout)["criteria"][0]["status"], "failed", "the criterion's own command ran and failed")

    def test_1b_editing_a_check_criterion_text_makes_it_run_again(self):
        repo = self.repo
        direct_goal(repo, "--done", "tests pass", "--check", " ".join(UNITTEST), "--impact", "config_change")
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        repo.ok("rerun")
        self.assertEqual(json.loads(repo.gt("--json", "check").stdout)["criteria"][0]["status"], "passed")
        repo.ok("goal", "--edit-done", "C1", "all tests pass, including new ones")
        self.assertEqual(json.loads(repo.gt("--json", "check").stdout)["criteria"][0]["status"], "not_run")

    def test_2_concurrent_dispatch_runs_a_once_operation_once(self):
        repo = self.repo
        direct_goal(repo)
        repo.ok("auth", "grant", "--actions", "push", "--scope", "x")
        op = json.loads(repo.ok("--json", "operation", "prepare", "--action", "push", "--target", "origin x"))["id"]
        marker = repo.path / "side-effects.txt"
        effect = [PY, "-c", "import time; open(%r, 'a').write('x'); time.sleep(0.5)" % str(marker)]
        threads = [threading.Thread(target=repo.gt, args=("operation", "dispatch", op, "--", *effect)) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(marker.read_text(), "x", "exactly one side effect")
        self.assertEqual(len([e for e in repo.events() if e["type"] == "operation.dispatched"]), 1)

    def test_3_a_registered_readback_cannot_be_replaced(self):
        repo = self.repo
        direct_goal(repo)
        repo.ok("auth", "grant", "--actions", "push", "--scope", "x")
        self.assertEqual(repo.gt("operation", "prepare", "--action", "push", "--target", "origin main", "--required").returncode, 2)
        op = json.loads(repo.ok("--json", "operation", "prepare", "--action", "push", "--target", "origin main",
                                "--readback", " ".join(FALSE), "--required"))["id"]
        repo.gt("operation", "dispatch", op, "--", PY, "-c", "import sys; sys.exit(3)")
        self.assertEqual(repo.gt("operation", "confirm", op, "--", *TRUE).returncode, 2)
        repo.gt("operation", "confirm", op)
        ops = json.loads(repo.ok("--json", "operation", "list"))
        self.assertEqual(ops[0]["state"], "failed")

    def test_4_subsessions_cannot_decide(self):
        repo = self.repo
        medium_goal(repo)
        sub = {"GT_SUBSESSION": "1"}
        for args in (("goal", "accept", "--item", "C1", "--result", "pass", "--quote", "ok"),
                     ("review", "T1", "--by", "goal_reviewer", "--verdict", "pass"), ("finish",),
                     ("retire", "R1", "--reason", "whatever"), ("scope", "allow", "**", "--reason", "x"),
                     ("task", "add", "T9", "x"), ("goal", "easy", "--replace", "--mode", "direct"),
                     ("plan", "apply"), ("verify", "--reset-head", "--reason", "xxxx")):
            result = repo.gt(*args, env=sub)
            self.assertEqual(result.returncode, 3, "%s: %s" % (args, result.stderr))
        self.assertEqual(repo.gt("propose", "--kind", "scope", "--text", "需要改 README", env=sub).returncode, 0)
        self.assertEqual(repo.gt("goal", "--show", env=sub).returncode, 0)
        self.assertEqual(repo.gt("run", "-", "--kind", "release", "--", *TRUE, env=sub).returncode, 3)

    def test_5_human_verdicts_are_self_reported_and_independent_reviews_need_a_note(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--mode", "tracked", "--risk", "high", "--done", "d")
        repo.ok("task", "add", "T1", "x", "--owner", "goal_backend", "--validator", "goal_reviewer", "--scope", "src/calc.py",
                "--accept", "a", "--exit", "e")
        repo.ok("task", "done", "T1")
        self.assertEqual(repo.gt("review", "T1", "--by", "goal_reviewer", "--verdict", "pass").returncode, 2)
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass", "--note", "核对了 calc.py 与 R3")
        repo.ok("review", "@goal", "--by", "用户", "--verdict", "pass", "--note", "用户说可以")
        reviews = [e["data"] for e in repo.events() if e["type"] == "review"]
        self.assertEqual(reviews[-1]["assurance"], "self_reported")

    def test_6_behaviour_change_without_tdd_is_not_achieved(self):
        repo = self.repo
        direct_goal(repo)
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--", *TRUE)
        repo.ok("task", "done", "T1")
        finish = json.loads(repo.gt("--json", "finish").stdout)
        self.assertFalse(finish["goal_achieved"])
        self.assertEqual(finish["gates"]["tdd"], "failed")
        self.assertIn("Red→Green", "\n".join(finish["reasons"]))

    def test_7_mode_does_not_change_quality_outcomes(self):
        outcomes = {}
        for mode in ("direct", "tracked"):
            repo = Repo()
            try:
                repo.ok("init")
                repo.ok("goal", "g", "--mode", mode, "--impact", "config_change")
                repo.ok("task", "add", "T1", "x", "--accept", "a", "--exit", "e")
                repo.write("src/calc.py", FIXED)
                repo.ok("run", "T1", "--kind", "affected", "--", *TRUE)
                repo.ok("task", "done", "T1")
                result = json.loads(repo.gt("--json", "check").stdout)
                from goalteams import policy
                quality = {g for g, rule in policy.gates_of({"mode": mode}).items() if rule.kind != "coordination"}
                outcomes[mode] = {g: v for g, v in result["gates"].items() if g in quality}
            finally:
                repo.close()
        self.assertEqual(outcomes["direct"], outcomes["tracked"])

    def test_8_every_entry_agrees_on_a_release_goal(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "ship", "--mode", "direct", "--release", "--impact", "config_change", "--done", "shipped")
        repo.ok("task", "add", "T1", "x", "--scope", "src/calc.py", "--accept", "a", "--exit", "e", "--validator", "goal_reviewer",
                "--owner", "goal_backend")
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--", *TRUE)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass", "--note", "ok")
        repo.ok("run", "-", "--kind", "regression", "--", *TRUE)
        repo.ok("review", "@goal", "--by", "goal_security", "--verdict", "pass", "--note", "ok")
        build = [PY, "-c", "import os; os.makedirs('dist', exist_ok=True); open('dist/a.tgz', 'w').write('x')"]
        repo.ok("run", "-", "--kind", "build", "--artifact", "dist/a.tgz", "--", *build)
        accept = json.loads(repo.ok("--json", "goal", "accept", "--item", "C1", "--result", "pass", "--quote", "ok"))
        check = repo.gt("--json", "check")
        nxt = repo.gt("--json", "loop", "next")
        self.assertEqual(accept["completion"], json.loads(check.stdout)["status"])
        self.assertEqual(check.returncode, 1)
        self.assertNotEqual(json.loads(nxt.stdout)["decision"], "achieved")
        ready = json.loads(repo.gt("--json", "check", "--release").stdout)
        self.assertEqual((ready["status"], ready["goal_achieved"]), ("ready", False))

    def test_10_confirming_a_mismatched_red_is_what_the_ledger_says(self):
        repo = self.repo
        repo.ok("init")
        repo.ok("goal", "g", "--mode", "direct")
        from tests.test_gt import TEST_NEW
        repo.write("tests/test_calc.py", TEST_NEW)
        repo.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "NoSuchText", "--", *UNITTEST)
        red = [e["data"] for e in repo.events() if e["type"] == "tdd.red"][-1]
        self.assertEqual(red["outcome"], "red_expect_mismatch")
        repo.ok("tdd", "confirm", red["id"], "--expect", "AssertionError")
        repo.write("src/calc.py", FIXED)
        self.assertEqual(repo.gt("tdd", "green", "T1").returncode, 0, "the confirmed Red pairs with a Green")

    def test_11_affected_is_not_passed_without_finished_code(self):
        repo = self.repo
        direct_goal(repo, "--impact", "config_change")
        result = json.loads(repo.gt("--json", "check").stdout)
        self.assertEqual(result["gates"]["affected"], "not_run")


if __name__ == "__main__":
    unittest.main()
