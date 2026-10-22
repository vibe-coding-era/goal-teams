"""V2.95 completion regressions: pending checks, per-task TDD and unknown side effects."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_gt import GT, HAS_GIT, SCRIPTS, Repo, UNITTEST, red_green

sys.path.insert(0, str(SCRIPTS))
from goalteams import completion, supervisor, graph_contract
from goalteams.models import Snapshot, Task, TaskFacts
from goalteams.state import State


def snapshot(impact="behavior_change"):
    state = State()
    state.goal = {"id": "G1", "title": "completion fixture", "status": "active", "mode": "direct", "risk": "normal", "domains": ["code"],
                  "impact": impact, "phase": "development", "criteria": []}
    state.tasks["T1"] = Task("T1", "first behavior", state="done", tdd=True)
    state.tasks["T2"] = Task("T2", "second behavior", state="done", tdd=False)
    state.receipts["R1"] = {"id": "R1", "type": "tdd.red", "task": "T1", "outcome": "red_verified", "seq": 1}
    state.receipts["R2"] = {"id": "R2", "type": "tdd.green", "task": "T1", "outcome": "green_ok", "red": "R1", "seq": 2}
    state.receipts["R0"] = {"id": "R0", "type": "run", "kind": "affected", "task": "T2", "passed": True, "seq": 0}
    return Snapshot(state.goal, "source", "code", {t: TaskFacts(fresh_pass="R2") for t in state.tasks},
                    {"available": True, "scoped": True, "files": 0}, [], [], {}, state=state)


def freeze_snapshot(snap):
    """Bind explicitly supplied synthetic evidence to the compiled fixture graph."""
    snap.state.plan["graph"] = graph_contract.compile_state(snap.state)
    snap.state.graph_code_digest = snap.code_digest
    digest = snap.state.plan["graph"]["sha256"]
    for receipt in snap.state.receipts.values():
        receipt["graph_digest"] = digest
        receipt.setdefault("code_digest", snap.code_digest)
    for task in snap.state.tasks.values():
        for review in task.reviews:
            review.setdefault("binds", {})["graph_digest"] = digest
    return snap


def judge_snapshot(snap):
    freeze_snapshot(snap)
    return completion.evaluate(snap)

class RequiredTDDTests(unittest.TestCase):
    def test_unflagged_behavior_task_cannot_hide_behind_another_tasks_green(self):
        snap = snapshot()
        result = judge_snapshot(snap)
        self.assertFalse(result.ok, result.as_dict())
        self.assertEqual(result.gates["tdd"], "failed")
        self.assertTrue(any("T2" in reason and "Red" in reason for reason in result.reasons), result.reasons)

    def test_second_task_with_its_own_tdd_is_accepted_without_opt_in_flag(self):
        snap = snapshot()
        snap.state.receipts["R3"] = {"id": "R3", "type": "tdd.red", "task": "T2", "outcome": "red_verified", "seq": 3}
        snap.state.receipts["R4"] = {"id": "R4", "type": "tdd.green", "task": "T2", "outcome": "green_ok", "red": "R3", "seq": 4}
        result = judge_snapshot(snap)
        self.assertTrue(result.ok, result.reasons)
        self.assertEqual(result.gates["tdd"], "passed")

    def test_configuration_change_does_not_require_tdd(self):
        snap = snapshot("config_change")
        result = judge_snapshot(snap)
        self.assertTrue(result.ok, result.reasons)
        self.assertEqual(result.gates["tdd"], "not_required")

    def test_parent_fully_covered_by_code_children_needs_no_duplicate_tdd(self):
        snap = snapshot()
        snap.state.tasks["T2"].kind = "doc"
        snap.state.tasks["T2"].reviews.append({"verdict": "pass", "by": "reviewer"})
        snap.state.tasks["P"] = Task("P", "aggregate", state="done")
        snap.state.receipts["RP"] = {"id": "RP", "type": "run", "kind": "affected", "task": "P", "passed": True, "seq": 5}
        snap.state.tasks["T1"].parent = "P"
        snap.tasks["P"] = TaskFacts(needs_own_evidence=False)
        result = judge_snapshot(snap)
        self.assertTrue(result.ok, result.reasons)

    def test_inflight_command_blocks_shared_judge(self):
        snap = snapshot("config_change")
        snap.state.running[9] = {"task": "T1", "kind": "affected", "cmd": ["test"], "goal": "G1"}
        result = judge_snapshot(snap)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("9" in reason for reason in result.reasons), result.reasons)

    def test_unknown_operation_precedes_achieved_in_supervisor_decision(self):
        snap = snapshot("config_change")
        snap.state.operations["OP1"] = {"id": "OP1", "state": "unknown", "required": False}
        result = judge_snapshot(snap)
        # Optional operations remain optional in the ordinary completion contract.
        self.assertTrue(result.ok, result.reasons)
        decision = supervisor.decide(snap.state, result, {"rounds": 3}, 0)
        self.assertEqual(decision["decision"], "blocked")
        self.assertIn("OP1", decision["reason"])

    def test_confirmed_optional_operation_does_not_block_supervisor(self):
        snap = snapshot("config_change")
        snap.state.operations["OP1"] = {"id": "OP1", "state": "confirmed", "required": False}
        decision = supervisor.decide(snap.state, judge_snapshot(snap), {"rounds": 3}, 0)
        self.assertEqual(decision["decision"], "achieved")


@unittest.skipUnless(HAS_GIT, "git required")
class CompletionCLITests(unittest.TestCase):
    def ready_repo(self):
        repo = Repo()
        self.addCleanup(repo.close)
        repo.ok("init")
        repo.ok("goal", "configuration verification", "--mode", "direct", "--impact", "config_change")
        repo.ok("task", "add", "T1", "configuration", "--scope", "src/calc.py", "--accept", "tests pass", "--exit", "tested")
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        self.assertTrue(json.loads(repo.ok("--json", "check"))["ok"])
        return repo

    def test_finish_waits_for_current_check_and_keeps_later_failure(self):
        for no_rerun, exit_code in ((False, 1), (True, 1), (False, 0)):
            with self.subTest(no_rerun=no_rerun, exit_code=exit_code):
                repo = self.ready_repo()
                ready = repo.path / ".goal-teams" / "test-ready"
                release = repo.path / ".goal-teams" / "test-release"
                command = ("from pathlib import Path; import time,sys; "
                           "Path('.goal-teams/test-ready').write_text('ready'); "
                           "deadline=time.monotonic()+15; "
                           "exec(\"while not Path('.goal-teams/test-release').exists() and time.monotonic()<deadline: time.sleep(.02)\"); "
                           "print('controlled check result'); sys.exit(%d)" % exit_code)
                proc = subprocess.Popen([sys.executable, str(GT), "run", "T1", "--kind", "affected", "--name", "inflight",
                                         "--", sys.executable, "-c", command], cwd=repo.path, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and time.monotonic() < deadline and proc.poll() is None:
                        time.sleep(.02)
                    self.assertTrue(ready.exists(), "the real command did not start")
                    args = ["--json", "finish"] + (["--no-rerun"] if no_rerun else [])
                    result = repo.gt(*args)
                finally:
                    release.write_text("continue")
                    stdout, stderr = proc.communicate(timeout=20)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(any(e["type"] == "goal.finished" for e in repo.events()))
                latest = [e["data"] for e in repo.events() if e["type"] == "run"][-1]
                self.assertNotIn("late", latest, (stdout, stderr, latest))
                checked = repo.gt("--json", "check")
                self.assertEqual(checked.returncode, 0 if exit_code == 0 else 1, checked.stdout + checked.stderr)
                if exit_code == 0:
                    repo.ok("finish")

    def test_unknown_optional_operation_blocks_loop_before_host_launch(self):
        repo = self.ready_repo()
        repo.ok("auth", "grant", "--actions", "push", "--scope", "synthetic test; no external write")
        op = json.loads(repo.ok("--json", "operation", "prepare", "--action", "push", "--target", "synthetic remote"))["id"]
        repo.gt("operation", "dispatch", op, "--", sys.executable, "-c", "import sys; sys.exit(2)")
        host = repo.path / ".goal-teams" / "fake-host.py"
        host.write_text("raise RuntimeError('must not launch while operation is unknown')\n")
        result = repo.gt("--json", "loop", "run", "--host", "fake", "--rounds", "1", env={"GT_FAKE_HOST": str(host)})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["outcome"], "blocked", payload)
        self.assertEqual(payload["rounds_used"], 0, payload)
        self.assertIn(op, payload["detail"])
        self.assertFalse(any(e["type"] == "goal.finished" for e in repo.events()))
