"""The completion and supervisor consumers enforce the frozen graph's boundaries."""
from __future__ import annotations
import unittest
from tests.test_v295_completion import snapshot, freeze_snapshot
from goalteams import completion, graph_contract, supervisor
from goalteams.models import Task, TaskFacts


def ready_branch():
    snap = snapshot("config_change")
    state = snap.state
    state.tasks["T1"].state = "blocked"
    state.tasks["T1"].reason = "external service unavailable"
    state.tasks["T1"].external = True
    state.tasks["T2"].state = "pending"
    state.tasks["T2"].deps = ["T1"]
    state.tasks["T3"] = Task("T3", "independent task", state="pending")
    snap.tasks["T3"] = TaskFacts()
    state.plan["graph"] = graph_contract.compile_state(state)
    return snap


class RuntimeGraphTests(unittest.TestCase):
    def test_unfrozen_exact_set_blocks_an_otherwise_complete_goal(self):
        snap = snapshot("config_change")
        result = completion.evaluate(snap)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("图" in reason for reason in result.reasons), result.reasons)

    def test_changed_task_spec_invalidates_frozen_completion(self):
        snap = snapshot("config_change")
        freeze_snapshot(snap)
        self.assertTrue(completion.evaluate(snap).ok)
        snap.state.tasks["T2"].accept = "new acceptance"
        self.assertFalse(completion.evaluate(snap).ok)

    def test_corrupt_graph_budget_blocks_completion(self):
        snap = snapshot("config_change")
        freeze_snapshot(snap)
        snap.state.graph_errors.append("synthetic malformed charge")
        result = completion.evaluate(snap)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")

    def test_external_blocker_only_stops_its_successor_closure(self):
        snap = ready_branch()
        self.assertEqual(graph_contract.ready_tasks(snap.state), ["T3"])
        self.assertEqual(graph_contract.blocked_closure(snap.state), ["T1", "T2"])
        result = completion.evaluate(snap)
        self.assertFalse(result.ok)
        decision = supervisor.decide(snap.state, result, {"rounds": 3}, 0)
        self.assertEqual(decision["decision"], "continue", decision)
        self.assertEqual(decision["ready_tasks"], ["T3"])
        self.assertEqual(decision["blocked_closure"], ["T1", "T2"])

    def test_independent_work_does_not_override_corrupt_ledger(self):
        snap = ready_branch()
        snap.verify_problems.append("ledger head mismatch")
        decision = supervisor.decide(snap.state, completion.evaluate(snap), {"rounds": 3}, 0)
        self.assertEqual(decision["decision"], "blocked")

    def test_independent_work_does_not_override_inflight_check(self):
        snap = ready_branch()
        snap.state.running[9] = {"task": "T3", "kind": "affected", "cmd": ["test"], "goal": "G1"}
        decision = supervisor.decide(snap.state, completion.evaluate(snap), {"rounds": 3}, 0)
        self.assertEqual(decision["decision"], "blocked")
