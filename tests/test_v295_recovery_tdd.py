"""Interrupted Red recovery remains closed after its paired Green changes the source."""
from __future__ import annotations
import unittest
from tests.test_v295_completion import snapshot, freeze_snapshot
from goalteams import run_recovery


def recovered_red():
    snap = snapshot()
    snap.state.interrupted_runs.append({"started": 5, "seq": 6, "original": {
        "task": "T1", "kind": "tdd.red", "name": None, "cmd": ["test"]}})
    snap.state.receipts["R7"] = {"id": "R7", "type": "tdd.red", "task": "T1", "seq": 7,
        "outcome": "red_verified", "cmd": ["test"], "code_digest": "before-fix"}
    snap.state.receipts["R8"] = {"id": "R8", "type": "tdd.green", "task": "T1", "seq": 8,
        "outcome": "green_ok", "red": "R7", "cmd": ["test"], "code_digest": snap.code_digest}
    return freeze_snapshot(snap)


class InterruptedTDDTests(unittest.TestCase):
    def test_later_real_red_and_current_paired_green_close_interrupted_red(self):
        self.assertEqual(run_recovery.open_interruptions(recovered_red()), [])

    def test_unpaired_or_unverified_green_cannot_close_interrupted_red(self):
        for change in ("old_red", "unverified_red", "different_command", "stale_green"):
            with self.subTest(change=change):
                snap = recovered_red()
                if change == "old_red":
                    snap.state.receipts["R8"]["red"] = "R1"
                elif change == "unverified_red":
                    snap.state.receipts["R7"]["outcome"] = "red_observed"
                elif change == "different_command":
                    snap.state.receipts["R7"]["cmd"] = ["other"]
                else:
                    snap.state.receipts["R8"]["code_digest"] = "old-code"
                self.assertEqual(len(run_recovery.open_interruptions(snap)), 1)
