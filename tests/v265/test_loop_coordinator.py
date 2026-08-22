from __future__ import annotations

import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v265.test_loop_review import ZERO_SHA256, _review


ARCHITECTURE_SHA256 = (
    "5f350bae868f842bc02d00b67ba44c577765c3f9a7f9ed080ada31e81f3c486f"
)
HARDENING_PLAN_REVISION = 3
HARDENING_TASK_EXACT_SET_SHA256 = (
    "d0f5bbf75cadf24338028d477b0e1ccc40c29b8aeb0c642cdc988d2600ebf496"
)


def _target() -> Any:
    try:
        return importlib.import_module("scripts.v265.loop_coordinator")
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == "scripts.v265.loop_coordinator" or missing.startswith(
            "scripts.v265"
        ):
            raise AssertionError(
                "E_TEST_V265_TARGET_MISSING:scripts.v265.loop_coordinator"
            ) from exc
        raise


def _descriptor(*, loop_round: int = 1) -> dict[str, object]:
    return {
        "round_id": f"ROUND-H265-LOOP-{loop_round}",
        "project_id": "user-project-v265",
        "artifact_version": "V2.65",
        "skill_version": "V2.65-candidate",
        "loop_id": "LOOP-V265-USER-1",
        "loop_round": loop_round,
        "task_exact_set_sha256": HARDENING_TASK_EXACT_SET_SHA256,
        "graph_revision": 1,
        "plan_revision": HARDENING_PLAN_REVISION,
        "source_revision": "candidate:c145b713",
        "started_at": f"2026-08-22T11:{loop_round:02d}:00Z",
        "max_capsule_items": 32,
        "max_capsule_bytes": 32768,
    }


def _unsigned_review(
    *,
    trigger: str,
    sequence: int,
    previous_review_sha256: str,
    issue_key: str | None = None,
    loop_round: int = 1,
) -> dict[str, object]:
    value = _review(
        loop_round=loop_round,
        sequence=sequence,
        trigger=trigger,
        previous_review_sha256=previous_review_sha256,
        issue_key=issue_key,
        review_outcome="observed_only" if trigger != "loop_end" else "no_change",
        status="open" if trigger != "loop_end" else "closed",
    )
    value["plan_revision"] = HARDENING_PLAN_REVISION
    value["task_exact_set_sha256"] = HARDENING_TASK_EXACT_SET_SHA256
    value["task_refs"] = ["H265-04R"]
    value["source_revision"] = "candidate:c145b713"
    return value


class TestV265LoopCoordinator(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp.name).resolve() / "user-project"
        self.project_root.mkdir()
        self.relative_path = "GoalTeamsWork/versions/V2.65/loop-review.md"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _begin(self, module: Any) -> dict[str, object]:
        receipt = module.begin_round(
            self.project_root,
            self.relative_path,
            _descriptor(),
            expected_coordinator_revision=0,
        )
        self.assertEqual(
            {
                "schema_version",
                "operation",
                "round_id",
                "loop_id",
                "loop_round",
                "coordinator_revision_before",
                "coordinator_revision_after",
                "review_state_revision",
                "review_file_sha256",
                "review_id",
                "pending_issue_key",
                "next_action_ready",
                "finalized",
                "capsule_relative_path",
                "capsule_sha256",
                "loop_decision",
                "receipt_sha256",
            },
            set(receipt),
        )
        self.assertEqual("begin_round", receipt["operation"])
        self.assertTrue(receipt["next_action_ready"])
        self.assertFalse(receipt["finalized"])
        self.assertIsNone(receipt["loop_decision"])
        self.assertRegex(ARCHITECTURE_SHA256, r"^[0-9a-f]{64}$")
        return receipt

    def test_begin_round_persists_exact_cas_state_and_rejects_path_escape(self) -> None:
        module = _target()
        receipt = self._begin(module)
        state_path = self.project_root / f"{self.relative_path}.coordinator.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual("goal-teams-loop-coordinator-state-v2.65", state["schema_version"])
        self.assertEqual("active", state["status"])
        self.assertEqual(receipt["coordinator_revision_after"], state["coordinator_revision"])
        self.assertEqual(HARDENING_TASK_EXACT_SET_SHA256, state["descriptor"]["task_exact_set_sha256"])

        with self.assertRaises(module.LoopCoordinatorError) as caught:
            module.begin_round(
                self.project_root,
                "../loop-review.md",
                _descriptor(loop_round=2),
                expected_coordinator_revision=receipt["coordinator_revision_after"],
            )
        self.assertEqual("E_V265_REVIEW_PATH", caught.exception.code)

    def test_problem_flag_blocks_next_action_until_exact_review_is_durable(self) -> None:
        module = _target()
        begun = self._begin(module)
        issue_key = "host execution preceded durable start"
        flagged = module.flag_problem(
            self.project_root,
            self.relative_path,
            issue_key=issue_key,
            evidence_refs=["evidence:authority:audit"],
            occurred_at="2026-08-22T11:01:00Z",
            expected_coordinator_revision=begun["coordinator_revision_after"],
        )
        self.assertFalse(flagged["next_action_ready"])
        self.assertEqual(issue_key, flagged["pending_issue_key"])

        premature = _unsigned_review(
            trigger="loop_end",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
        )
        with self.assertRaises(module.LoopCoordinatorError) as caught:
            module.finalize_round(
                self.project_root,
                self.relative_path,
                premature,
                active_review_ids=[premature["review_id"]],
                compiled_at="2026-08-22T11:02:00Z",
                expected_coordinator_revision=flagged["coordinator_revision_after"],
            )
        self.assertEqual("E_V265_LOOP_COORDINATOR_REVIEW_REQUIRED", caught.exception.code)

        problem = _unsigned_review(
            trigger="problem_detected",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
            issue_key=issue_key,
        )
        recorded = module.record_problem_review(
            self.project_root,
            self.relative_path,
            problem,
            expected_coordinator_revision=flagged["coordinator_revision_after"],
        )
        self.assertTrue(recorded["next_action_ready"])
        self.assertIsNone(recorded["pending_issue_key"])
        self.assertEqual(problem["review_id"], recorded["review_id"])
        markdown = (self.project_root / self.relative_path).read_text(encoding="utf-8")
        self.assertEqual(1, markdown.count(f"## {problem['review_id']}\n"))
        self.assertEqual(1, markdown.count("<!-- goal-teams-loop-review-begin:"))
        self.assertEqual(1, markdown.count("<!-- goal-teams-loop-review-end:"))

    def test_finalize_returns_signed_loop_decision_and_bounded_capsule_reference(self) -> None:
        module = _target()
        begun = self._begin(module)
        loop_end = _unsigned_review(
            trigger="loop_end",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
        )
        finalized = module.finalize_round(
            self.project_root,
            self.relative_path,
            loop_end,
            active_review_ids=[loop_end["review_id"]],
            compiled_at="2026-08-22T11:02:00Z",
            expected_coordinator_revision=begun["coordinator_revision_after"],
        )
        self.assertTrue(finalized["finalized"])
        self.assertFalse(finalized["next_action_ready"])
        self.assertEqual("continue", finalized["loop_decision"])
        self.assertRegex(finalized["capsule_sha256"], r"^[0-9a-f]{64}$")
        capsule_path = self.project_root / finalized["capsule_relative_path"]
        capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
        self.assertEqual(finalized["capsule_sha256"], capsule["capsule_sha256"])
        self.assertEqual([loop_end["review_id"]], capsule["source_review_ids"])

        with self.assertRaises(module.LoopCoordinatorError) as caught:
            module.finalize_round(
                self.project_root,
                self.relative_path,
                copy.deepcopy(loop_end),
                active_review_ids=[loop_end["review_id"]],
                compiled_at="2026-08-22T11:02:00Z",
                expected_coordinator_revision=finalized["coordinator_revision_after"],
            )
        self.assertEqual("E_V265_LOOP_COORDINATOR_STATE", caught.exception.code)

    def test_finalize_reconciles_cross_file_failure_without_duplicate_loop_end(self) -> None:
        module = _target()
        begun = self._begin(module)
        loop_end = _unsigned_review(
            trigger="loop_end",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
        )
        capsule_path = self.project_root / f"{self.relative_path}.capsule.json"
        capsule_path.parent.mkdir(parents=True, exist_ok=True)
        capsule_path.mkdir()
        with self.assertRaises(module.LoopCoordinatorError) as caught:
            module.finalize_round(
                self.project_root,
                self.relative_path,
                loop_end,
                active_review_ids=[loop_end["review_id"]],
                compiled_at="2026-08-22T11:02:00Z",
                expected_coordinator_revision=begun["coordinator_revision_after"],
            )
        self.assertEqual("E_V265_REVIEW_PATH", caught.exception.code)

        coordinator_path = self.project_root / f"{self.relative_path}.coordinator.json"
        pending = json.loads(coordinator_path.read_text(encoding="utf-8"))
        self.assertEqual("committing_finalize", pending["status"])
        capsule_path.rmdir()
        reconciled = module.reconcile_round(
            self.project_root,
            self.relative_path,
            expected_coordinator_revision=pending["coordinator_revision"],
        )
        self.assertTrue(reconciled["finalized"])
        self.assertEqual("continue", reconciled["loop_decision"])
        markdown = (self.project_root / self.relative_path).read_text(encoding="utf-8")
        self.assertEqual(1, markdown.count(f"## {loop_end['review_id']}\n"))
        self.assertEqual(1, markdown.count("<!-- goal-teams-loop-review-begin:"))
        self.assertEqual(1, markdown.count("<!-- goal-teams-loop-review-end:"))
        self.assertTrue(capsule_path.is_file())


if __name__ == "__main__":
    unittest.main()
