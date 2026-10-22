"""V2.9 P4: control plane, LOOP supervisor with a scripted host, leases, budgets, stalled detection
(AC17, AC19–AC23, AC32)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.test_gt import FIXED, GT, HAS_GIT, SCRIPTS, TEST_NEW, UNITTEST, Repo

sys.path.insert(0, str(SCRIPTS))
from goalteams.context import Ctx  # noqa: E402
from goalteams.ledger import Project  # noqa: E402
from goalteams.supervisor import expect_lease  # noqa: E402
from goalteams.util import GTError  # noqa: E402

PY = sys.executable
CHECK = " ".join(UNITTEST)


def script(folder: Path, name: str, body: str) -> str:
    path = folder / name
    header = "import json, subprocess, sys, time\nGT = %r\nPY = %r\nUNITTEST = %r\nFIXED = %r\nTEST_NEW = %r\n" % (
        str(GT), PY, UNITTEST, FIXED, TEST_NEW)
    header += "def gt(*a):\n    return subprocess.run([PY, GT, *a], capture_output=True, text=True)\n"
    path.write_text(header + textwrap.dedent(body), encoding="utf-8")
    return str(path)


FIXER = """
open('tests/test_calc.py', 'w').write(TEST_NEW)
r = gt('tdd', 'red', 'T1', '--test', 'tests/test_calc.py', '--expect', 'AssertionError', '--', *UNITTEST)
assert r.returncode == 0, r.stdout + r.stderr
open('src/calc.py', 'w').write(FIXED)
g = gt('tdd', 'green', 'T1')
assert g.returncode == 0, g.stdout + g.stderr
print('GT_FAKE_USAGE ' + json.dumps({"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.01}))
"""
NOOP = """
print('GT_FAKE_USAGE ' + json.dumps({"input_tokens": 5, "output_tokens": 1, "cost_usd": 0.001}))
"""
SLEEPER = """
time.sleep(20)
"""
PROPOSER = """
out = {}
out['control_set'] = gt('control', 'set', '--rounds', '9').returncode
out['propose'] = gt('propose', '--kind', 'budget', '--text', '再给两轮').returncode
out['auth'] = gt('auth', 'grant', '--actions', 'push', '--scope', 'x').returncode
out['edit_done'] = gt('goal', '--add-done', '偷偷加一条').returncode
out['config'] = gt('config', 'set', 'require_independent_review', 'false').returncode
out['tdd'] = gt('run', 'T1', '--kind', 'affected', '--', PY, '-c', 'pass').returncode
open('.goal-teams/proposer.json', 'w').write(json.dumps(out))
"""


@unittest.skipUnless(HAS_GIT, "git required")
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.scripts = Path(tempfile.mkdtemp(prefix="gt-fake-host-"))
        self.repo.ok("init")
        self.repo.ok("goal", "修复 add", "--mode", "direct", "--done", "add(2,3)==5", "--check", CHECK)
        self.repo.ok("task", "add", "T1", "修复 add", "--tdd", "--scope", "src/calc.py", "--scope", "tests/test_calc.py",
                     "--accept", "add(2,3)==5", "--exit", "Green")

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.scripts, ignore_errors=True)

    def run_loop(self, body: str, *args: str):
        host = script(self.scripts, "host.py", body)
        return self.repo.gt("--json", "loop", "run", "--host", "fake", *args, env={"GT_FAKE_HOST": host})

    def events(self, kind: str):
        return [e["data"] for e in self.repo.events() if e["type"] == kind]

    def test_one_round_reaches_achieved_through_finish(self):  # AC32
        result = self.run_loop(FIXER, "--rounds", "2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["outcome"], "achieved")
        self.assertEqual(payload["rounds_used"], 1)
        rounds = self.events("loop.round")
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["usage"]["cost_usd"], 0.01)
        self.assertEqual(rounds[0]["exit_code"], 0)
        self.assertEqual(self.events("loop.lease")[0]["epoch"], 1)
        self.assertEqual(self.events("loop.lease.end")[-1]["outcome"], "achieved")
        self.assertEqual(self.events("goal.finished")[-1]["outcome"], "achieved")
        reservations = self.events("loop.reserve")
        self.assertEqual([r["round"] for r in reservations], [1])
        self.assertIn("evidence_mode=tracked", self.repo.ok("report"))

    def test_two_rounds_without_progress_are_stalled(self):  # AC22
        result = self.run_loop(NOOP, "--rounds", "5")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["outcome"], "stalled")
        self.assertEqual(payload["rounds_used"], 2)
        decisions = [d["decision"] for d in self.events("loop.next")]
        self.assertEqual(decisions, ["continue", "stalled"])
        goal = json.loads(self.repo.ok("--json", "goal", "--show"))
        self.assertEqual(goal["status"], "active", "stalled is not terminal: a new plan revision resumes it")
        self.assertEqual(self.events("loop.lease.end")[-1]["outcome"], "stalled")

    def test_round_budget_is_exhausted_before_a_second_session(self):  # AC20
        result = self.run_loop(NOOP, "--rounds", "1")
        self.assertEqual(json.loads(result.stdout)["outcome"], "budget_exhausted")
        self.assertEqual(len(self.events("loop.round")), 1)
        again = self.run_loop(NOOP, "--rounds", "1")
        payload = json.loads(again.stdout)
        self.assertEqual(payload["outcome"], "budget_exhausted")
        self.assertEqual(len(self.events("loop.round")), 1, "history is kept; a new run does not reset the budget")

    def test_unsettled_reservation_is_charged_at_its_upper_bound(self):  # AC20, AC21
        Project(self.repo.path).append("loop.reserve", {"epoch": 0, "round": 1, "kind": "session", "minutes": 10}, "lead")
        result = self.run_loop(NOOP, "--rounds", "1")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["outcome"], "budget_exhausted")
        self.assertEqual(self.events("loop.round"), [], "the crashed reservation already used the one round")

    def test_overrunning_round_is_terminated_and_the_deadline_does_not_move(self):  # AC19, AC20
        result = self.run_loop(SLEEPER, "--rounds", "3", "--minutes", "0.04", "--round-minutes", "0.04")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["outcome"], "timed_out", result.stdout)
        rounds = self.events("loop.round")
        self.assertEqual(len(rounds), 1)
        self.assertTrue(rounds[0]["timed_out"])
        self.assertEqual(rounds[0]["exit_code"], 124)
        self.assertLess(rounds[0]["duration_ms"], 10000, "the sleeper did not get its 20 s")
        lease = self.events("loop.lease")[0]
        again = self.run_loop(NOOP, "--rounds", "3")
        self.assertEqual(json.loads(again.stdout)["outcome"], "timed_out", "a later run inherits the absolute deadline")
        self.assertEqual(self.events("loop.lease")[-1]["deadline_at"], lease["deadline_at"])

    def test_second_supervisor_is_refused_while_the_first_is_alive_and_takes_over_a_dead_one(self):  # AC11, AC23
        Project(self.repo.path).append("loop.lease", {"epoch": 1, "pid": os.getpid(), "host": "fake", "budget": {},
                                                      "deadline_at": "2999-01-01T00:00:00Z"}, "lead")
        result = self.run_loop(NOOP, "--rounds", "1")
        self.assertEqual(result.returncode, 3)
        self.assertIn("已有监督器在运行", result.stderr)
        Project(self.repo.path).append("loop.lease", {"epoch": 2, "pid": 999999, "host": "fake", "budget": {},
                                                      "deadline_at": "2999-01-01T00:00:00Z"}, "lead")
        result = self.run_loop(NOOP, "--rounds", "1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lease = self.events("loop.lease")[-1]
        self.assertEqual((lease["epoch"], lease["takeover_from"]), (3, 2))

    def test_an_old_epoch_cannot_write_after_a_takeover(self):  # AC11, AC23
        project = Project(self.repo.path)
        project.append("loop.lease", {"epoch": 1, "pid": 999999, "host": "fake", "budget": {}, "deadline_at": "2999-01-01T00:00:00Z"}, "lead")
        project.append("loop.lease", {"epoch": 2, "pid": 999998, "host": "fake", "budget": {}, "deadline_at": "2999-01-01T00:00:00Z"}, "lead")
        import argparse
        ctx = Ctx(argparse.Namespace(root=str(self.repo.path)))
        with self.assertRaises(GTError) as caught:
            ctx.append("loop.round", {"epoch": 1, "round": 1, "exit_code": 0}, expect=expect_lease(1))
        self.assertEqual(caught.exception.code, 4)
        ctx.append("loop.round", {"epoch": 2, "round": 1, "exit_code": 0, "duration_ms": 1}, expect=expect_lease(2))

    def test_subsession_can_only_propose(self):  # AC17
        result = self.run_loop(PROPOSER, "--rounds", "1")
        outcomes = json.loads((self.repo.path / ".goal-teams" / "proposer.json").read_text(encoding="utf-8"))
        self.assertEqual(outcomes, {"control_set": 3, "propose": 0, "auth": 3, "edit_done": 3, "config": 3, "tdd": 0})
        proposals = self.events("control.proposal")
        self.assertEqual(len(proposals), 1)
        self.assertTrue(proposals[0]["subsession"])
        pid = proposals[0]["id"]
        denied = self.repo.gt("control", "approve", pid, env={"GT_SUBSESSION": "1"})
        self.assertEqual(denied.returncode, 3)
        self.repo.ok("control", "approve", pid, "--note", "同意再给两轮")
        self.assertEqual(json.loads(self.repo.ok("--json", "control", "show"))["budget"]["rounds"], 3, "approval alone changes nothing")
        self.repo.ok("control", "set", "--rounds", "5")
        self.assertEqual(json.loads(self.repo.ok("--json", "control", "show"))["budget"]["rounds"], 5)
        self.assertEqual(result.returncode, 1)

    def test_unsettled_external_operation_blocks_the_loop(self):  # AC23, AC32
        self.repo.ok("auth", "grant", "--actions", "push", "--scope", "x")
        op = json.loads(self.repo.ok("--json", "operation", "prepare", "--action", "push", "--target", "origin x"))["id"]
        self.repo.gt("operation", "dispatch", op, "--", PY, "-c", "import sys; sys.exit(2)")
        result = self.run_loop(NOOP, "--rounds", "3")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["outcome"], "blocked")
        self.assertIn(op, payload["detail"])
        self.assertEqual(len(self.events("loop.round")), 0, "no session starts while a side effect is unknown")

    def test_probe_reports_capabilities_honestly(self):  # AC31 (host side)
        host = script(self.scripts, "host.py", NOOP)
        report = json.loads(self.repo.ok("--json", "loop", "probe", "--host", "fake", env={"GT_FAKE_HOST": host}))
        self.assertEqual(report["mode"], "cooperative")
        self.assertEqual(report["items"]["command_available"]["status"], "probe_passed")
        self.assertEqual(report["items"]["headless_launch"]["status"], "unknown")
        self.assertEqual(report["items"]["cancel"]["status"], "documented")
        self.assertEqual(report["items"]["process_containment"]["status"], "unavailable")
        self.assertEqual(report["items"]["predispatch_tool_limit"]["status"], "unavailable")
        missing = self.repo.gt("loop", "probe", "--host", "fake", env={"GT_FAKE_HOST": "/nonexistent/host.py"})
        self.assertEqual(missing.returncode, 3)

    def test_dry_run_takes_no_lease(self):
        result = self.run_loop(NOOP, "--dry-run")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.events("loop.lease"), [])
        self.assertIn("deadline_at", json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()


class AdapterUsageTests(unittest.TestCase):  # AC21
    def test_claude_stream_without_a_result_is_unknown_and_with_one_is_reported(self):
        from goalteams.adapters.claude import ClaudeAdapter
        adapter = ClaudeAdapter()
        truncated = '{"type":"system","subtype":"init"}\n{"type":"assistant","message":{}}\n{"type":"res'
        self.assertEqual(adapter.collect_usage(truncated)["status"], "unknown")
        full = truncated[:-12] + '\n{"type":"result","num_turns":3,"total_cost_usd":0.12,"usage":{"input_tokens":10,"output_tokens":4}}\n'
        usage = adapter.collect_usage(full)
        self.assertEqual((usage["status"], usage["turns"], usage["cost_usd"]), ("reported", 3, 0.12))

    def test_codex_sums_turns_and_never_invents_a_cost(self):
        from goalteams.adapters.codex import CodexAdapter
        adapter = CodexAdapter()
        log = ('{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":2}}\n'
               'not json\n{"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":1}}\n')
        usage = adapter.collect_usage(log)
        self.assertEqual((usage["turns"], usage["input_tokens"], usage["output_tokens"], usage["cost_usd"]), (2, 12, 3, None))
        self.assertEqual(adapter.collect_usage("")["status"], "unknown")
