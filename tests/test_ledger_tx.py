"""V2.9 P2: manifest, journal-based commit protocol, late receipts, unknown events (AC11–AC14)."""

from __future__ import annotations

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
from goalteams import VERSION  # noqa: E402
from goalteams.ledger import EVENT_SCHEMA, MANIFEST_SCHEMA, Project  # noqa: E402
from goalteams.util import GTError, canonical_json, sha256_text  # noqa: E402


def manifest_path(repo: Repo) -> Path:
    return repo.path / ".goal-teams" / "manifest.json"


@unittest.skipUnless(HAS_GIT, "git required")
class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_init_writes_a_manifest_and_events_carry_the_new_schema(self):  # AC14
        repo = self.repo
        repo.ok("init")
        manifest = json.loads(manifest_path(repo).read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], MANIFEST_SCHEMA)
        self.assertEqual(manifest["event_schema"], "goal-teams/event@2")
        self.assertEqual(manifest["min_reader"], "2.9.0")
        self.assertEqual(manifest["required_capabilities"], [])
        self.assertTrue(manifest["project"]["id"])
        self.assertEqual({e["schema"] for e in repo.events()}, {EVENT_SCHEMA})

    def test_a_newer_manifest_refuses_to_judge_or_append(self):  # AC14
        repo = self.repo
        medium_goal(repo)
        manifest = json.loads(manifest_path(repo).read_text(encoding="utf-8"))
        manifest["min_reader"] = "99.0.0"
        manifest_path(repo).write_text(json.dumps(manifest), encoding="utf-8")
        before = len(repo.events())
        check = repo.gt("check")
        self.assertEqual(check.returncode, 3, check.stdout + check.stderr)
        self.assertIn("min_reader", check.stderr)
        self.assertEqual(repo.gt("task", "add", "T2", "x", "--accept", "a").returncode, 3)
        self.assertEqual(len(repo.events()), before, "nothing is written to a ledger this version may not read")
        manifest["min_reader"] = VERSION
        manifest["required_capabilities"] = ["time-travel"]
        manifest_path(repo).write_text(json.dumps(manifest), encoding="utf-8")
        check = repo.gt("check")
        self.assertEqual(check.returncode, 3)
        self.assertIn("time-travel", check.stderr)

    def test_legacy_state_without_a_manifest_gets_one_on_the_next_append(self):
        repo = self.repo
        medium_goal(repo)
        manifest_path(repo).unlink()
        repo.ok("task", "add", "T2", "更多", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/more.py", "--accept", "x", "--exit", "y")
        self.assertTrue(manifest_path(repo).is_file())

    def test_unknown_event_type_is_reported_and_blocks_completion(self):  # AC14
        repo = self.repo
        medium_goal(repo)
        project = Project(repo.path)
        project.append("future.thing", {"x": 1}, "lead")
        check = repo.gt("--json", "check")
        self.assertEqual(check.returncode, 1)
        payload = json.loads(check.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("future.thing", "\n".join(payload["reasons"]))
        self.assertEqual(repo.gt("verify").returncode, 0, "the chain itself is intact")


@unittest.skipUnless(HAS_GIT, "git required")
class JournalTests(unittest.TestCase):
    """Crash injection at every write point of the commit protocol (AC13)."""

    def setUp(self):
        self.repo = Repo()
        medium_goal(self.repo)
        self.project = Project(self.repo.path)

    def tearDown(self):
        self.repo.close()

    def staged_event(self, event_type: str = "scope.allow", data=None):
        lines = self.project.read_lines()
        seq = json.loads(lines[-1])["seq"] + 1
        event = {"schema": EVENT_SCHEMA, "seq": seq, "ts": "2026-10-18T08:00:00Z", "type": event_type,
                 "actor": "lead", "data": data or {"pattern": "docs/**", "reason": "crash test"},
                 "prev": sha256_text(lines[-1])}
        line = canonical_json(event)
        return seq, line

    def write_journal(self, seq: int, line: str) -> None:
        head = self.project.read_head()
        self.project.journal_path.write_text(json.dumps({
            "prev_head": head, "seq": seq, "sha256": sha256_text(line), "type": json.loads(line)["type"]}),
            encoding="utf-8")

    def test_crash_after_journal_before_ledger_is_forgotten(self):
        seq, line = self.staged_event()
        self.write_journal(seq, line)
        before = len(self.repo.events())
        repo = self.repo
        repo.ok("task", "add", "T2", "x", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "src/more.py", "--accept", "a", "--exit", "e")
        self.assertFalse(self.project.journal_path.exists())
        events = repo.events()
        self.assertEqual(len(events), before + 1)
        self.assertEqual(events[-1]["type"], "task.add", "the staged event never happened; nothing is invented")
        self.assertEqual(repo.gt("verify").returncode, 0)

    def test_crash_after_ledger_before_head_is_completed_from_the_journal(self):
        seq, line = self.staged_event()
        self.write_journal(seq, line)
        with open(self.project.ledger_path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        self.assertEqual(self.repo.gt("verify").returncode, 1, "head is behind until recovery")
        repo = self.repo
        repo.ok("scope", "allow", "more/**", "--reason", "after recovery")
        self.assertFalse(self.project.journal_path.exists())
        head = self.project.read_head()
        self.assertEqual(head["seq"], seq + 1)
        events = repo.events()
        self.assertEqual([e["type"] for e in events[-2:]], ["scope.allow", "scope.allow"])
        self.assertEqual(repo.gt("verify").returncode, 0)

    def test_ledger_ahead_without_a_matching_journal_is_refused(self):
        seq, line = self.staged_event()
        with open(self.project.ledger_path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")   # written behind gt's back: no journal says so
        result = self.repo.gt("scope", "allow", "more/**", "--reason", "x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("ledger.head", result.stderr)
        self.assertEqual(self.repo.gt("verify").returncode, 1)

    def test_journal_naming_a_different_line_is_refused(self):
        seq, line = self.staged_event()
        self.write_journal(seq, line)
        other = canonical_json(dict(json.loads(line), data={"pattern": "x/**", "reason": "tampered"}))
        with open(self.project.ledger_path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(other + "\n")
        result = self.repo.gt("scope", "allow", "more/**", "--reason", "x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("journal", result.stderr)
        self.assertTrue(self.project.journal_path.exists(), "nothing is cleaned up silently")

    def test_partial_line_after_journal_is_dropped_and_forgotten(self):
        seq, line = self.staged_event()
        self.write_journal(seq, line)
        with open(self.project.ledger_path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line[: len(line) // 2])
        self.repo.ok("scope", "allow", "more/**", "--reason", "x")
        self.assertFalse(self.project.journal_path.exists())
        self.assertEqual(self.repo.gt("verify").returncode, 0)
        self.assertEqual([e["type"] for e in self.repo.events()][-1], "scope.allow")
        self.assertEqual(len([e for e in self.repo.events() if e["data"].get("pattern") == "docs/**"]), 0)


@unittest.skipUnless(HAS_GIT, "git required")
class LateReceiptTests(unittest.TestCase):
    """Receipts that land after the goal, plan or task they started under has moved on (AC12)."""

    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def run_slow_check(self, seconds: float = 2.5):
        repo = self.repo
        holder = {}
        prior_seq = max(e["seq"] for e in repo.events())

        def worker():
            holder["result"] = repo.gt("run", "T1", "--kind", "affected", "--name", "slow", "--", sys.executable, "-c",
                                       "import time, sys; time.sleep(%s); sys.exit(0)" % seconds)
        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            if any(e["type"] == "run.started" and e["seq"] > prior_seq for e in repo.events()):
                break
            time.sleep(0.05)
        return thread, holder

    def test_run_started_is_recorded_before_the_command_and_resolved_by_its_receipt(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        events = repo.events()
        started = [e for e in events if e["type"] == "run.started"]
        self.assertEqual(len(started), 1)
        receipt = [e for e in events if e["type"] == "run"][-1]
        self.assertEqual(receipt["data"]["started"], started[0]["seq"])
        self.assertEqual(started[0]["data"]["task"], "T1")
        self.assertEqual(started[0]["data"]["plan_revision"], 1)
        self.assertNotIn("进行中", repo.ok("status"))

    def test_receipt_landing_after_the_task_spec_changed_is_kept_apart(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        thread, holder = self.run_slow_check()
        repo.ok("task", "edit", "T1", "--accept", "add(2,3)==5 并且 add(0,0)==0")
        thread.join(timeout=30)
        result = holder["result"]
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("规格", result.stderr)
        receipt = [e for e in repo.events() if e["type"] == "run"][-1]["data"]
        self.assertEqual(receipt["late"], "spec_changed")
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertNotIn("slow", json.dumps(check["passes"], ensure_ascii=False))
        tasklist = (repo.path / ".goal-teams" / "TaskList.md").read_text(encoding="utf-8")
        row = next(line for line in tasklist.splitlines() if line.startswith("| T1 |"))
        self.assertNotIn(receipt["id"], row, "a late receipt is not evidence for the task")
        self.assertNotIn("已开始但没有回执", repo.ok("status"), "the late receipt still resolves its run.started")

    def test_finish_waits_for_running_receipt_before_closing(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        repo.write("src/calc.py", FIXED)
        repo.ok("run", "T1", "--kind", "affected", "--", *UNITTEST)
        repo.ok("task", "done", "T1")
        repo.ok("review", "T1", "--by", "goal_reviewer", "--verdict", "pass")
        settle(repo)
        thread, holder = self.run_slow_check()
        finish = repo.gt("finish", "--no-rerun")
        self.assertNotEqual(finish.returncode, 0, finish.stdout + finish.stderr)
        self.assertFalse(any(e["type"] == "goal.finished" for e in repo.events()))
        thread.join(timeout=30)
        self.assertEqual(holder["result"].returncode, 0)
        receipt = [e for e in repo.events() if e["type"] == "run"][-1]["data"]
        self.assertNotIn("late", receipt)
        repo.ok("finish", "--no-rerun")
        report = repo.ok("report")
        self.assertIn("目标达成", report)
        self.assertNotIn("gt check 现在未通过", report)

    def test_interrupted_command_leaves_a_visible_orphan(self):
        repo = self.repo
        medium_goal(repo, tdd=False)
        project = Project(repo.path)
        project.append("run.started", {"task": "T1", "kind": "affected", "cmd": ["sleep", "99"], "goal": "G1",
                                       "plan_revision": 1, "pid": 999999}, "lead")
        status = repo.ok("status")
        self.assertIn("已开始但没有回执", status)
        check = json.loads(repo.gt("--json", "check").stdout)
        self.assertEqual(check["status"], "blocked")
        self.assertIn("已开始但没有回执", "\n".join(check["reasons"]))


class BenchmarkToolTests(unittest.TestCase):
    def test_replay_benchmark_runs_quickly_on_a_small_ledger(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / "tools" / "bench_ledger.py"), "--events", "300", "--json"],
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["events"], 300)
        self.assertGreater(payload["replay_ms"], 0)
        self.assertIn("append_ms_per_event", payload)


if __name__ == "__main__":
    unittest.main()
