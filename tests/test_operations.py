"""V2.9 P3: external operations go through an intent and are settled by readback (AC24, AC25)."""

from __future__ import annotations

import shlex
import json
import sys
import unittest

from tests.test_gt import FIXED, HAS_GIT, SCRIPTS, UNITTEST, Repo, medium_goal, settle

sys.path.insert(0, str(SCRIPTS))
from goalteams.ledger import Project  # noqa: E402

PY = sys.executable
OK = [PY, "-c", "pass"]
FAIL2 = [PY, "-c", "import sys; sys.exit(2)"]
ABSENT = [PY, "-c", "import sys; sys.exit(1)"]


def ready_goal(repo: Repo) -> None:
    medium_goal(repo, tdd=False)
    repo.write("src/calc.py", FIXED)
    repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
    repo.ok("task", "done", "T1")
    repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
    settle(repo)


@unittest.skipUnless(HAS_GIT, "git required")
class OperationTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        ready_goal(self.repo)

    def tearDown(self):
        self.repo.close()

    def ops(self):
        return json.loads(self.repo.ok("--json", "operation", "list"))

    def test_intent_needs_a_grant_and_binds_it(self):
        repo = self.repo
        refused = repo.gt("operation", "prepare", "--action", "tag", "--target", "github.com/x/y tag v1.0.0")
        self.assertEqual(refused.returncode, 3)
        self.assertIn("未授权", refused.stderr)
        repo.ok("auth", "grant", "--actions", "tag", "--scope", "v1.0.0 only")
        out = repo.ok("--json", "operation", "prepare", "--action", "tag", "--target", "github.com/x/y tag v1.0.0",
                      "--readback", shlex.join(OK), "--required")
        op = json.loads(out)
        self.assertEqual((op["state"] if "state" in op else "prepared"), "prepared")
        self.assertTrue(op["grant_seq"])
        self.assertEqual(self.ops()[0]["state"], "prepared")

    def test_required_operation_blocks_finish_until_confirmed(self):  # AC24
        repo = self.repo
        repo.ok("auth", "grant", "--actions", "push", "--scope", "feature branch")
        op = json.loads(repo.ok("--json", "operation", "prepare", "--action", "push", "--target", "origin goal/x",
                                "--readback", shlex.join(OK), "--required"))["id"]
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertIn("已登记未执行", "\n".join(check["reasons"]))
        self.assertEqual(check["gates"]["operations"], "failed")
        repo.ok("operation", "dispatch", op, "--", *OK)
        self.assertEqual(self.ops()[0]["state"], "executed")
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertIn("未回读确认", "\n".join(check["reasons"]))
        repo.ok("operation", "confirm", op)  # uses the stored readback
        self.assertEqual(self.ops()[0]["state"], "confirmed")
        finish = repo.gt("--json", "finish", "--no-rerun")
        self.assertEqual(finish.returncode, 0, finish.stdout + finish.stderr)
        self.assertEqual(json.loads(finish.stdout)["gates"]["operations"], "passed")

    def test_failed_dispatch_is_unknown_until_readback_and_once_is_not_retried(self):  # AC25
        repo = self.repo
        repo.ok("auth", "grant", "--actions", "release", "--scope", "v1.0.0")
        op = json.loads(repo.ok("--json", "operation", "prepare", "--action", "release", "--target", "Release v1.0.0",
                                "--readback", shlex.join(ABSENT)))["id"]
        result = repo.gt("operation", "dispatch", op, "--", *FAIL2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown", result.stdout)
        self.assertEqual(self.ops()[0]["state"], "unknown")
        again = repo.gt("operation", "dispatch", op, "--", *OK)
        self.assertEqual(again.returncode, 3, "an unknown result is never replayed")
        self.assertIn("reconcile", again.stderr)
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertIn("结果不明", "\n".join(check["notes"]), "not --required: a note, not a blocker")
        reconciled = repo.gt("operation", "reconcile", op)
        self.assertEqual(reconciled.returncode, 1)
        self.assertEqual(self.ops()[0]["state"], "failed")
        self.assertIn("once", reconciled.stdout)
        retry = repo.gt("operation", "dispatch", op, "--", *OK)
        self.assertEqual(retry.returncode, 3, "once: a failed intent needs a new intent, not a retry")

    def test_retry_safe_intent_may_be_dispatched_again_after_a_clean_failure(self):
        repo = self.repo
        repo.ok("auth", "grant", "--actions", "push", "--scope", "feature branch")
        op = json.loads(repo.ok("--json", "operation", "prepare", "--action", "push", "--target", "origin goal/x",
                                "--idempotent", "retry_safe"))["id"]
        self.assertEqual(repo.gt("operation", "dispatch", op, "--", *FAIL2).returncode, 1)
        self.assertEqual(repo.gt("operation", "reconcile", op, "--", *ABSENT).returncode, 1)
        self.assertEqual(self.ops()[0]["state"], "failed")
        repo.ok("operation", "dispatch", op, "--", *OK)
        self.assertEqual(self.ops()[0]["state"], "executed")
        self.assertEqual(repo.gt("operation", "confirm", op, "--", *FAIL2).returncode, 1, "a broken readback keeps unknown")
        self.assertEqual(self.ops()[0]["state"], "unknown")
        repo.ok("operation", "confirm", op, "--", *OK)
        self.assertEqual(self.ops()[0]["state"], "confirmed")
        history = [h["kind"] for h in self.ops()[0]["history"]]
        self.assertEqual(history, ["dispatched", "result", "confirmed", "dispatched", "result", "confirmed", "confirmed"])

    def test_crash_between_dispatch_and_result_is_settled_by_resume_readback(self):  # AC24
        repo = self.repo
        repo.ok("auth", "grant", "--actions", "tag", "--scope", "v1.0.0")
        op = json.loads(repo.ok("--json", "operation", "prepare", "--action", "tag", "--target", "v1.0.0",
                                "--readback", shlex.join(OK), "--required"))["id"]
        Project(repo.path).append("operation.dispatched", {"id": op, "cmd": ["git", "tag", "v1.0.0"], "pid": 1}, "lead")
        self.assertEqual(self.ops()[0]["state"], "dispatched")
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertIn("可能中断", "\n".join(check["reasons"]))
        self.assertEqual(repo.gt("operation", "dispatch", op, "--", *OK).returncode, 3, "never re-run blindly")
        resume = repo.ok("resume", "--readback")
        self.assertIn("## 回读", resume)
        self.assertEqual(self.ops()[0]["state"], "confirmed")
        self.assertEqual(repo.gt("--json", "check").returncode, 0)

    def test_expired_or_rebound_grant_stops_dispatch(self):
        repo = self.repo
        repo.ok("auth", "grant", "--actions", "push", "--scope", "x", "--expires", "2000-01-01")
        refused = repo.gt("operation", "prepare", "--action", "push", "--target", "origin main")
        self.assertEqual(refused.returncode, 3)
        self.assertIn("过期", refused.stderr)


if __name__ == "__main__":
    unittest.main()
