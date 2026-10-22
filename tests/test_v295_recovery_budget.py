"""Reducer-level supplement: interrupted work is charged, and recovery never refunds it."""
from __future__ import annotations
import copy
import unittest
from tests.test_v295_completion import snapshot, freeze_snapshot
from goalteams import graph_budget, run_recovery


class InterruptedBudgetTests(unittest.TestCase):
    def test_settlement_preserves_spent_budget_and_rerun_charges_one_revalidation(self):
        snap = freeze_snapshot(snapshot("config_change"))
        state = snap.state
        start = {"task": "T1", "kind": "affected", "name": "check", "cmd": ["test"], "goal": "G1", "pid": 999999,
                 "graph_charge": graph_budget.charge(state, "T1", "revalidation", "run:5")}
        state._on_run_started({"actor": "lead"}, start, 5)
        before = graph_budget.status(state)
        data = {"started": 5, "original": copy.deepcopy(state.running[5]), "goal": "G1", "reason": "worker stopped",
                "passed": False, "confirmed_stopped": True, "pid_observation": "not_alive"}
        run_recovery.observe(state, {"actor": "lead"}, data, 6)
        self.assertEqual(graph_budget.status(state), before)
        self.assertNotIn(5, state.running)
        self.assertEqual(state.recovery_errors, [])
        retry = dict(start, graph_charge=graph_budget.charge(state, "T1", "revalidation", "run:7"))
        state._on_run_started({"actor": "lead"}, retry, 7)
        state._receipt({"type": "run", "actor": "lead"}, {
            "id": "R8", "started": 7, "task": "T1", "kind": "affected", "name": "check", "cmd": ["test"],
            "passed": True, "code_digest": snap.code_digest, "graph_digest": state.plan["graph"]["sha256"]}, 8)
        after = graph_budget.status(state)["tasks"]["T1"]["consumed"]
        self.assertEqual(after["work_units"], before["tasks"]["T1"]["consumed"]["work_units"] + 1)
        self.assertEqual(after["revalidations"], before["tasks"]["T1"]["consumed"]["revalidations"] + 1)
        self.assertEqual(after["attempts"], before["tasks"]["T1"]["consumed"]["attempts"])
        self.assertEqual(run_recovery.open_interruptions(snap), [])
