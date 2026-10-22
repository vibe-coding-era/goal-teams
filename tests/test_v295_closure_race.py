"""Real CLI evidence landing after judgement cannot be hidden by a legacy achieved stop."""
from __future__ import annotations
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

from tests.test_gt import HAS_GIT, Repo, UNITTEST
from goalteams import cli
from goalteams.context import Ctx


@unittest.skipUnless(HAS_GIT, "git required")
class ClosureRaceTests(unittest.TestCase):
    def ready_repo(self):
        repo = Repo()
        self.addCleanup(repo.close)
        repo.ok("init")
        repo.ok("goal", "Closure transaction", "--mode", "direct", "--impact", "config_change")
        repo.ok("task", "add", "T1", "configuration", "--scope", "src/**")
        repo.ok("run", "T1", "--kind", "affected", "--name", "baseline", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        self.assertTrue(json.loads(repo.ok("--json", "check"))["ok"])
        return repo

    def interleave(self, repo, command, event, other_command):
        append = Ctx.append
        landed = []
        def schedule(ctx, event_type, data, *args, **kwargs):
            if event_type == event and not landed:
                landed.append(repo.gt(*other_command))
            return append(ctx, event_type, data, *args, **kwargs)
        with patch.object(Ctx, "append", schedule), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["--root", str(repo.path), *command])
        self.assertEqual(len(landed), 1)
        return rc, landed[0]

    def test_achieved_stop_rejects_a_real_failure_landed_after_judgement(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                repo = self.ready_repo()
                command = ["loop", "decide", "stop"] + (["--outcome", "achieved"] if explicit else [])
                rc, run = self.interleave(repo, command, "loop.decide", [
                    "run", "T1", "--kind", "affected", "--name", "concurrent", "--", sys.executable, "-c", "raise SystemExit(1)"])
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertEqual(rc, 4, "a stale achieved decision must conflict")
                self.assertFalse(any(e["type"] == "loop.decide" for e in repo.events()))
                self.assertEqual(repo.gt("--json", "check").returncode, 1)
                self.assertEqual(json.loads(repo.ok("--json", "goal", "--show"))["status"], "active")

    def test_achieved_stop_rejects_changed_snapshot_even_if_new_evidence_passes(self):
        repo = self.ready_repo()
        rc, run = self.interleave(repo, ["loop", "decide", "stop", "--outcome", "achieved"], "loop.decide", [
            "run", "T1", "--kind", "affected", "--name", "concurrent", "--", sys.executable, "-c", "pass"])
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(rc, 4)
        self.assertFalse(any(e["type"] == "loop.decide" for e in repo.events()))
        repo.ok("loop", "decide", "stop", "--outcome", "achieved")

    def test_another_terminal_decision_cannot_be_overwritten_by_achieved(self):
        repo = self.ready_repo()
        rc, stopped = self.interleave(repo, ["loop", "decide", "stop", "--outcome", "achieved"], "loop.decide", [
            "loop", "decide", "stop", "--outcome", "user_stopped"])
        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(rc, 4)
        decisions = [e["data"]["outcome"] for e in repo.events() if e["type"] == "loop.decide"]
        self.assertEqual(decisions, ["user_stopped"])

    def test_finish_control_also_rejects_the_same_failure_schedule(self):
        repo = self.ready_repo()
        rc, run = self.interleave(repo, ["finish", "--no-rerun"], "goal.finished", [
            "run", "T1", "--kind", "affected", "--name", "concurrent", "--", sys.executable, "-c", "raise SystemExit(1)"])
        self.assertEqual(run.returncode, 1)
        self.assertEqual(rc, 4)
        self.assertFalse(any(e["type"] == "goal.finished" for e in repo.events()))

    def test_explicit_stopped_outcome_still_records_open_failures(self):
        repo = self.ready_repo()
        rc, run = self.interleave(repo, ["loop", "decide", "stop", "--outcome", "stopped"], "loop.decide", [
            "run", "T1", "--kind", "affected", "--name", "concurrent", "--", sys.executable, "-c", "raise SystemExit(1)"])
        self.assertEqual(run.returncode, 1)
        self.assertEqual(rc, 0)
        self.assertEqual([e["data"]["outcome"] for e in repo.events() if e["type"] == "loop.decide"], ["stopped"])
        self.assertEqual(repo.gt("--json", "check").returncode, 1)

    def test_current_success_still_records_achieved(self):
        repo = self.ready_repo()
        repo.ok("loop", "decide", "stop", "--outcome", "achieved")
        self.assertTrue(json.loads(repo.ok("--json", "check"))["ok"])
        self.assertEqual([e["data"]["outcome"] for e in repo.events() if e["type"] == "loop.decide"], ["achieved"])
