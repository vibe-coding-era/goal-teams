"""Finding admission consumes real current CLI receipts, never boolean assertions alone."""
import json
import sys
import unittest

from tests.test_gt import Repo, TEST_NEW, UNITTEST


class GraphFindingTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def finding(self, receipt, **overrides):
        value = {"finding_id": "F1", "task_id": "A", "evidence_verified": True,
                 "in_locked_scope": True, "consumer_confirmed": True,
                 "authorization_boundary_unchanged": True, "evidence_refs": [receipt],
                 "estimated_work_units": 1, "estimated_attempts": 1, "estimated_revalidations": 1,
                 "paths": ["src/calc.py"]}
        value.update(overrides)
        self.repo.write(".goal-teams/finding.json", json.dumps(value))
        return self.repo.gt("graph", "finding", ".goal-teams/finding.json", "--json")

    def setup_task(self):
        self.repo.ok("init")
        self.repo.ok("goal", "Fix calculator", "--impact", "config_change")
        self.repo.ok("task", "add", "A", "fix", "--scope", "src/**", "--scope", "tests/**")

    def test_verified_red_is_current_reproduction_even_with_separate_test_digest(self):
        self.setup_task()
        self.repo.write("tests/test_calc.py", TEST_NEW)
        self.repo.ok("tdd", "red", "A", "--test", "tests/test_calc.py", "--expect", "AssertionError", "--", *UNITTEST)
        receipt = [e["data"]["id"] for e in self.repo.events() if e["type"] == "tdd.red"][-1]
        result = self.finding(receipt)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        decision = json.loads(result.stdout)
        self.assertTrue(decision["admitted"])
        self.assertEqual("operator_declaration", decision["authorization_assurance"])
        self.assertEqual("declared_current_goal", decision["consumer_assurance"])

    def test_fake_outside_stale_and_overbudget_findings_never_expand_graph(self):
        self.setup_task()
        self.assertNotEqual(0, self.repo.gt("run", "A", "--kind", "affected", "--", sys.executable, "-c", "raise AssertionError('repro')").returncode)
        receipt = [e["data"]["id"] for e in self.repo.events() if e["type"] == "run"][-1]
        for index, changes in enumerate(({"evidence_refs": ["R999"]}, {"paths": ["private/secret"]}, {"estimated_work_units": 999})):
            result = self.finding(receipt, finding_id="F%d" % index, **changes)
            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertFalse(json.loads(result.stdout)["admitted"])
        self.repo.write("src/calc.py", "# changed since reproduction\n")
        result = self.finding(receipt, finding_id="F-stale")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(json.loads(result.stdout)["admitted"])
        graph_events = [e for e in self.repo.events() if e["type"] == "graph.frozen"]
        self.assertEqual(1, len(graph_events))
        self.assertEqual(["A"], graph_events[0]["data"]["graph"]["task_ids"])
