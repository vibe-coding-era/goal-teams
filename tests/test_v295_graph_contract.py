"""V2.95 retains bounded task graphs without importing the previous runtime."""
import copy
import importlib
import unittest

from tests.test_gt import SCRIPTS
from goalteams.models import Task
from goalteams.state import State
from goalteams.util import GTError


def sample():
    s = State()
    s.graph_code_digest = "fixture-code"
    s.goal = {"id": "G1", "title": "Deliver calculator", "mode": "tracked", "impact": "config_change",
              "criteria": [{"id": "C1", "text": "calculator works", "check": None}]}
    s.tasks["A"] = Task("A", "calculator", owner="dev", validator="qa", scopes=["src/**"],
                        accept="calculator works", exit="current passing evidence")
    s.tasks["B"] = Task("B", "documentation", owner="docs", validator="qa", scopes=["docs/**"],
                        accept="usage readable", exit="review passes", kind="doc", deps=["A"])
    s.tasks["C"] = Task("C", "independent", owner="dev", validator="qa", scopes=["config/**"],
                        accept="config valid", exit="check passes")
    s.plan["revision"] = 1
    return s


class GraphContractTests(unittest.TestCase):
    def setUp(self):
        self.graph = importlib.import_module("goalteams.graph_contract")
        self.budget = importlib.import_module("goalteams.graph_budget")

    def freeze(self, state):
        state.plan["graph"] = self.graph.compile_state(state)
        return state.plan["graph"]

    def test_graph_is_exact_and_rebuilt_from_tasks(self):
        s = sample()
        compiled = self.freeze(s)
        self.assertEqual(["A", "B", "C"], compiled["task_ids"])
        self.assertEqual([["A", "C"], ["B"]], compiled["ready_layers"])
        self.assertEqual([], self.graph.completion_problems(s))
        s.tasks["A"].scopes.append("private/**")
        self.assertTrue(self.graph.completion_problems(s))

    def test_missing_or_unknown_consumer_fails(self):
        for consumers in ([], ["task:missing"], ["criterion:missing"]):
            s = sample()
            s.tasks["A"].consumer_refs = consumers
            with self.subTest(consumers=consumers), self.assertRaises(GTError):
                self.graph.compile_state(s)

    def test_inferred_consumer_names_current_goal_without_claiming_acceptance(self):
        c = self.graph.compile_state(sample())
        self.assertEqual(["goal:G1"], c["tasks"]["A"]["consumer_refs"])
        self.assertEqual("declared_current_goal", c["tasks"]["A"]["consumer_assurance"])

    def test_cycle_and_cancelled_dependency_are_rejected(self):
        s = sample()
        s.tasks["A"].deps = ["B"]
        with self.assertRaises(GTError):
            self.graph.compile_state(s)
        s = sample()
        s.tasks["A"].state = "cancelled"
        with self.assertRaises(GTError):
            self.graph.compile_state(s)

    def test_budget_types_are_exact_positive_integers(self):
        for value in (True, 0, -1, "10"):
            s = sample()
            s.tasks["A"].budget = dict(self.budget.DEFAULT_LIMITS, attempts=value)
            with self.subTest(value=value), self.assertRaises(GTError):
                self.graph.compile_state(s)

    def test_weighted_critical_path(self):
        s = sample()
        for key, n in (("A", 2), ("B", 3), ("C", 4)):
            s.tasks[key].budget = dict(self.budget.DEFAULT_LIMITS, work_units=n)
        c = self.graph.compile_state(s)
        self.assertEqual(9, c["total_budget_wu"])
        self.assertEqual(5, c["critical_path_wu"])

    def test_blocker_only_closes_descendants(self):
        s = sample()
        self.freeze(s)
        s.tasks["A"].state = "blocked"
        s.tasks["A"].external = True
        self.assertEqual(["A", "B"], self.graph.blocked_closure(s))
        self.assertEqual(["C"], self.graph.ready_tasks(s))

    def test_context_limit_counts_utf8_bytes_and_binds_packet(self):
        s = sample()
        s.tasks["A"].budget = dict(self.budget.DEFAULT_LIMITS, context_tokens=2)
        self.freeze(s)
        receipt = self.graph.context_receipt(s, "A", "中文")
        self.assertEqual(2, receipt["estimated_tokens"])
        self.assertEqual(6, receipt["bytes"])
        with self.assertRaises(GTError):
            self.graph.context_receipt(s, "A", "中文中文")

    def test_finding_admission_requires_current_evidence_scope_consumer_and_budget(self):
        s = sample()
        self.freeze(s)
        s.receipts["R1"] = {"id": "R1", "type": "run", "task": "A", "passed": False,
                            "source_digest": "a" * 64, "graph_digest": s.plan["graph"]["sha256"]}
        finding = {"finding_id": "F1", "task_id": "A", "evidence_verified": True,
                   "in_locked_scope": True, "consumer_confirmed": True,
                   "authorization_boundary_unchanged": True, "evidence_refs": ["R1"],
                   "estimated_work_units": 1, "estimated_attempts": 1, "estimated_revalidations": 0,
                   "paths": ["src/calc.py"]}
        classify = lambda f: self.graph.classify_finding(s, f, current_source_digest="a" * 64)
        self.assertTrue(classify(finding)["admitted"])
        for key in ("evidence_verified", "in_locked_scope", "consumer_confirmed", "authorization_boundary_unchanged"):
            self.assertFalse(classify(dict(finding, **{key: False}))["admitted"])
        with self.assertRaises(GTError):
            classify(dict(finding, attempt_budget_remaining=999))
        self.assertFalse(classify(dict(finding, estimated_work_units=999))["admitted"])
        self.assertFalse(classify(dict(finding, evidence_refs=["R999"]))["admitted"])
        self.assertFalse(classify(dict(finding, paths=["private/key"]))["admitted"])
        self.assertFalse(self.graph.classify_finding(s, finding, current_source_digest="b" * 64)["admitted"])

    def test_completed_task_exit_predicate_requires_real_current_receipt(self):
        s = sample()
        self.freeze(s)
        s.tasks["A"].state = "accepted"
        self.assertTrue(self.graph.completion_problems(s))
        s.receipts["R1"] = {"id": "R1", "type": "run", "task": "A", "kind": "affected", "passed": True,
                            "code_digest": s.graph_code_digest,
                            "graph_digest": s.plan["graph"]["sha256"]}
        self.assertEqual([], self.graph.completion_problems(s))
        s.plan["revision"] += 1
        self.freeze(s)
        self.assertTrue(self.graph.completion_problems(s))

    def test_budget_replay_never_trusts_remaining_and_does_not_reset_on_revision(self):
        s = sample()
        self.freeze(s)
        charge = self.budget.charge(s, "A", "implementation", "op1")
        s.graph_charges.append(charge)
        self.assertEqual(1, self.budget.status(s)["tasks"]["A"]["consumed"]["attempts"])
        s.plan["revision"] += 1
        self.freeze(s)
        self.assertEqual(1, self.budget.status(s)["tasks"]["A"]["consumed"]["attempts"])
        with self.assertRaises(GTError):
            self.budget.charge(s, "A", "implementation", "op1")

    def test_atomic_multiaxis_charge_and_revalidation_limit(self):
        s = sample()
        s.tasks["A"].budget = dict(self.budget.DEFAULT_LIMITS, work_units=1, attempts=1, revalidations=0)
        self.freeze(s)
        with self.assertRaises(GTError):
            self.budget.charge(s, "A", "revalidation", "op0")
        self.assertEqual(0, self.budget.status(s)["tasks"]["A"]["consumed"]["work_units"])
        s.graph_charges.append(self.budget.charge(s, "A", "implementation", "op1"))
        with self.assertRaises(GTError):
            self.budget.charge(s, "A", "implementation", "op2")

    def test_forged_budget_charge_is_rejected(self):
        s = sample()
        self.freeze(s)
        event = self.budget.charge(s, "A", "implementation", "op1")
        event["amounts"]["attempts"] = -1
        s.graph_charges.append(event)
        with self.assertRaises(GTError):
            self.budget.status(s)
