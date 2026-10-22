"""A predecessor's exit is evaluated on current files and unresolved failures at dispatch."""
import json
import sys
import unittest

from tests.test_gt import Repo


class LiveGraphAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.repo.ok("init")
        self.repo.ok("goal", "Dependency validation", "--impact", "config_change")
        self.repo.ok("task", "add", "A", "first", "--scope", "src/**")
        self.repo.ok("task", "add", "B", "second", "--scope", "tests/**", "--deps", "A")
        self.command = [sys.executable, "-c", "import os,sys;sys.exit(int(os.getenv('GRAPH_FAIL','0')))"]
        self.repo.ok("run", "A", "--kind", "affected", "--name", "predecessor", "--", *self.command)
        self.repo.ok("task", "done", "A")

    def assert_successor_blocked(self):
        before = len([e for e in self.repo.events() if e["type"] == "run.started"])
        result = self.repo.gt("run", "B", "--kind", "affected", "--", sys.executable, "-c", "print('SUCCESSOR_EXECUTED')")
        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertNotIn("SUCCESSOR_EXECUTED", result.stdout)
        self.assertEqual(before, len([e for e in self.repo.events() if e["type"] == "run.started"]))
        self.assertNotEqual(0, self.repo.gt("task", "start", "B", "--force", "--reason", "try bypass").returncode)
        status = json.loads(self.repo.gt("graph", "status", "--json").stdout)
        self.assertNotIn("B", status["ready_tasks"])

    def refresh_and_dispatch(self):
        self.repo.ok("run", "A", "--kind", "affected", "--name", "predecessor", "--", *self.command)
        self.repo.ok("run", "B", "--kind", "affected", "--", sys.executable, "-c", "print('revalidated')")

    def test_new_failure_overrules_historical_pass_until_same_command_recovers(self):
        failed = self.repo.gt("run", "A", "--kind", "affected", "--name", "predecessor", "--", *self.command,
                              env={"GRAPH_FAIL": "1"})
        self.assertNotEqual(0, failed.returncode)
        self.assert_successor_blocked()
        self.refresh_and_dispatch()

    def test_current_source_change_requires_fresh_predecessor_before_dispatch(self):
        self.repo.write("src/calc.py", "# source changed after the predecessor passed\n")
        self.assert_successor_blocked()
        self.refresh_and_dispatch()

    def test_successor_own_scope_change_does_not_invalidate_predecessor(self):
        self.repo.write("tests/test_calc.py", "# successor owns this changed test file\n")
        self.repo.ok("run", "B", "--kind", "affected", "--", sys.executable, "-c", "print('own scope works')")


class LiveReviewAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.repo.ok("init")
        self.repo.ok("goal", "Reviewed document dependency", "--impact", "config_change")
        self.repo.ok("task", "add", "D", "document", "--kind", "doc", "--scope", "README.md",
                     "--owner", "goal_docs", "--validator", "goal_reviewer")
        self.repo.ok("task", "add", "B", "consumer", "--scope", "src/**", "--deps", "D")
        self.repo.ok("task", "done", "D")
        self.repo.ok("review", "D", "--by", "goal_reviewer", "--verdict", "pass")

    def test_reviewed_predecessor_content_change_blocks_dispatch_until_reviewed_again(self):
        self.repo.write("README.md", "# changed reviewed content\n")
        result = self.repo.gt("run", "B", "--kind", "affected", "--", sys.executable, "-c", "print('must not run')")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(any(e["type"] == "run.started" for e in self.repo.events()))
        self.repo.ok("review", "D", "--by", "goal_reviewer", "--verdict", "pass")
        self.repo.ok("run", "B", "--kind", "affected", "--", sys.executable, "-c", "print('review refreshed')")

    def test_independent_successor_change_preserves_reviewed_predecessor(self):
        self.repo.write("src/calc.py", "# successor implementation change\n")
        self.repo.ok("run", "B", "--kind", "affected", "--", sys.executable, "-c", "print('own scope works')")
