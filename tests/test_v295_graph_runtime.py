"""The graph gates actual CLI work, not just an optional diagram."""
import json
import subprocess
import sys
import unittest

from tests.test_gt import Repo, FIXED, TEST_NEW, UNITTEST


class GraphRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def goal(self, mode="tracked"):
        self.repo.ok("init")
        self.repo.ok("goal", "Validate calculator", "--mode", mode, "--impact", "config_change",
                     "--done", "tests pass", "--check", " ".join(UNITTEST))

    def plan(self, **overrides):
        task = {"id": "A", "title": "calculator", "owner": "dev", "validator": "qa",
                "scope": ["src/**", "tests/**"], "accept": "tests pass", "exit": "current passing evidence"}
        task.update(overrides)
        self.repo.write(".goal-teams/plan.json", json.dumps({"tasks": [task]}))
        return self.repo.gt("plan", "apply")

    def test_direct_automatically_freezes_graph_and_command_consumes_budget(self):
        self.repo.ok("run", "A", "--kind", "affected", "--", *UNITTEST)
        events = self.repo.events()
        frozen = [e for e in events if e["type"] == "graph.frozen"]
        self.assertTrue(frozen)
        started = [e for e in events if e["type"] == "run.started"][-1]
        self.assertIn("graph_charge", started["data"])
        self.assertEqual(1, started["data"]["graph_charge"]["amounts"]["attempts"])

    def test_budget_exhaustion_prevents_subprocess_and_survives_reapply(self):
        self.goal()
        budget = {"work_units": 1, "attempts": 1, "revalidations": 1, "context_tokens": 12000}
        self.assertEqual(0, self.plan(budget=budget).returncode)
        self.repo.ok("run", "A", "--kind", "affected", "--", *UNITTEST)
        self.assertEqual(0, self.plan(budget=budget).returncode)
        result = self.repo.gt("run", "A", "--kind", "affected", "--", sys.executable, "-c",
                              "open('escape.txt','w').write('bad')")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.repo.path / "escape.txt").exists())

    def test_dependency_gate_cannot_be_bypassed_by_force_or_evidence(self):
        self.goal()
        a = {"id": "A", "title": "first", "scope": ["src/**"], "accept": "ready", "exit": "check"}
        b = dict(a, id="B", title="second", deps=["A"])
        self.repo.write(".goal-teams/plan.json", json.dumps({"tasks": [a, b]}))
        self.repo.ok("plan", "apply")
        self.assertNotEqual(0, self.repo.gt("task", "start", "B", "--force", "--reason", "skip").returncode)
        result = self.repo.gt("run", "B", "--kind", "affected", "--", sys.executable, "-c", "print('must not run')")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(any(e["type"] == "run.started" for e in self.repo.events()))

    def test_forbidden_scope_is_not_overridden_by_scope_allow(self):
        self.goal()
        self.assertEqual(0, self.plan(forbidden_scope=["src/secrets.py"]).returncode)
        self.repo.write("src/secrets.py", "private = 1\n")
        self.repo.ok("scope", "allow", "src/secrets.py", "--reason", "needed for test")
        self.assertNotEqual(0, self.repo.gt("diff").returncode)

    def test_packet_context_budget_is_consumed_by_real_packet_command(self):
        self.goal()
        budget = {"work_units": 10, "attempts": 10, "revalidations": 10, "context_tokens": 1}
        self.assertEqual(0, self.plan(budget=budget).returncode)
        self.assertNotEqual(0, self.repo.gt("task", "packet", "A").returncode)

    def test_plan_apply_freezes_the_entire_active_exact_set(self):
        self.goal()
        self.assertEqual(0, self.plan().returncode)
        self.repo.write(".goal-teams/plan.json", json.dumps({"tasks": [{"id": "B", "title": "docs", "kind": "doc",
                              "accept": "docs ready", "exit": "review"}]}))
        self.repo.ok("plan", "apply")
        latest = [e for e in self.repo.events() if e["type"] == "plan.applied"][-1]
        self.assertEqual(["A", "B"], latest["data"]["graph"]["task_ids"])

    def test_default_budget_covers_real_red_green_and_affected(self):
        self.repo.write("tests/test_calc.py", TEST_NEW)
        self.repo.ok("tdd", "red", "A", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        self.repo.write("src/calc.py", FIXED)
        self.repo.ok("tdd", "green", "A")
        self.repo.ok("run", "A", "--kind", "affected", "--", *UNITTEST)
        self.repo.ok("finish")
        charges = [e["data"]["graph_charge"] for e in self.repo.events() if e["type"] == "run.started"]
        self.assertEqual(3, len(charges))
        self.assertGreaterEqual(sum(c["amounts"].get("work_units", 0) for c in charges), 3)

    def test_concurrent_last_budget_unit_has_one_winner(self):
        self.goal()
        budget = {"work_units": 1, "attempts": 1, "revalidations": 1, "context_tokens": 12000}
        self.assertEqual(0, self.plan(budget=budget).returncode)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.repo.gt("run", "A", "--kind", "affected", "--", *UNITTEST), range(2)))
        self.assertEqual(1, sum(r.returncode == 0 for r in results))
        self.assertEqual(1, len([e for e in self.repo.events() if e["type"] == "run.started"]))
