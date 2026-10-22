"""Current exit evidence, rather than a state label, releases dependent work."""
import unittest

from tests.test_gt import Repo
from tests.test_v295_graph_contract import sample
from goalteams import graph_contract
from goalteams.models import Task
from goalteams.util import GTError


class GraphDependencyTests(unittest.TestCase):
    def freeze(self, state):
        state.plan["graph"] = graph_contract.compile_state(state)

    def test_complete_predecessor_without_exit_receipt_cannot_release_successor(self):
        state = sample()
        self.freeze(state)
        state.tasks["A"].state = "accepted"
        self.assertNotIn("B", graph_contract.ready_tasks(state))
        with self.assertRaises(GTError):
            graph_contract.require_ready(state, "B")

    def test_aggregate_default_requires_own_review_and_children_exit(self):
        state = sample()
        state.tasks["P"] = Task("P", "aggregate", scopes=["src/**"], owner="lead", validator="qa")
        state.tasks["A"].parent = "P"
        self.freeze(state)
        self.assertEqual(["review"], state.plan["graph"]["tasks"]["P"]["exit_condition"]["required_receipt_types"])
        state.tasks["A"].state = "accepted"
        state.tasks["P"].state = "accepted"
        state.tasks["P"].reviews = [{"verdict": "pass", "binds": {"graph_digest": state.plan["graph"]["sha256"]}}]
        self.assertTrue(graph_contract.exit_problems(state, state.tasks["P"]))
        state.receipts["R1"] = {"id": "R1", "type": "run", "task": "A", "passed": True,
                                "code_digest": state.graph_code_digest,
                                "graph_digest": state.plan["graph"]["sha256"]}
        self.assertEqual([], graph_contract.exit_problems(state, state.tasks["P"]))
        state.tasks["P"].reviews = []
        self.assertTrue(graph_contract.exit_problems(state, state.tasks["P"]))

    def test_parent_with_uncovered_scope_still_needs_own_evidence(self):
        state = sample()
        state.tasks["P"] = Task("P", "aggregate plus own work", scopes=["src/**", "other/**"])
        state.tasks["A"].parent = "P"
        self.freeze(state)
        self.assertEqual(["evidence"], state.plan["graph"]["tasks"]["P"]["exit_condition"]["required_receipt_types"])

    def test_cli_force_cannot_release_done_predecessor_without_evidence(self):
        repo = Repo()
        self.addCleanup(repo.close)
        repo.ok("init")
        repo.ok("goal", "Config", "--impact", "config_change")
        repo.ok("task", "add", "A", "first", "--scope", "src/**")
        repo.ok("task", "add", "B", "next", "--scope", "src/**", "--deps", "A")
        repo.ok("task", "done", "A")
        result = repo.gt("task", "start", "B", "--force", "--reason", "skip")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("依赖", result.stderr)
