from __future__ import annotations

import hashlib
import importlib
import json
import fcntl
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v265.test_loop_coordinator import _descriptor, _unsigned_review
from tests.v265.test_loop_review import ZERO_SHA256


CONTRACT_SHA256 = "cd2fd2b1540d886b29a4ccb7fbd79bfc87814024e5d3601b3417522f53a3428f"
PLAN_REVISION = 1
TASK_EXACT_SET_SHA256 = "1f3dd08b9a58f3123edb909c8dc027c3fd1d1ee599e96d29ae768164b75dd95d"


def _target(name: str) -> Any:
    return importlib.import_module(name)


def _deduplicate_worker(
    connection: Any,
    project_root: str,
    relative_path: str,
    unsigned_review: dict[str, object],
    expected_revision: int,
) -> None:
    module = importlib.import_module("scripts.v265.loop_coordinator")
    connection.send(("ready", None))
    try:
        receipt = module.record_problem_review(
            Path(project_root),
            relative_path,
            unsigned_review,
            expected_coordinator_revision=expected_revision,
        )
        connection.send(("ok", receipt))
    except Exception as exc:  # child boundary returns only stable type/code
        connection.send(("error", (type(exc).__name__, getattr(exc, "code", None))))
    finally:
        connection.close()


class TestV265LoopCoordinatorMultiRound(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp.name).resolve() / "user-project"
        self.project_root.mkdir()
        self.relative_path = "GoalTeamsWork/versions/V2.65/loop-review.md"
        self.coordinator = _target("scripts.v265.loop_coordinator")
        self.review = _target("scripts.v265.loop_review")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _begin(self, loop_round: int, revision: int) -> dict[str, object]:
        return self.coordinator.begin_round(
            self.project_root,
            self.relative_path,
            _descriptor(loop_round=loop_round),
            expected_coordinator_revision=revision,
        )

    def _inspection(self) -> dict[str, object]:
        return self.review.inspect_loop_review(self.project_root, self.relative_path)

    def test_two_rounds_retain_distinct_immutable_capsules(self) -> None:
        self.assertRegex(CONTRACT_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(1, PLAN_REVISION)
        self.assertRegex(TASK_EXACT_SET_SHA256, r"^[0-9a-f]{64}$")

        first = self._begin(1, 0)
        end_one = _unsigned_review(
            trigger="loop_end",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
            loop_round=1,
        )
        final_one = self.coordinator.finalize_round(
            self.project_root,
            self.relative_path,
            end_one,
            active_review_ids=[end_one["review_id"]],
            compiled_at="2026-08-22T11:02:00Z",
            expected_coordinator_revision=first["coordinator_revision_after"],
        )
        capsule_one = self.project_root / final_one["capsule_relative_path"]
        bytes_one = capsule_one.read_bytes()

        second = self._begin(2, final_one["coordinator_revision_after"])
        inspection = self._inspection()
        end_two = _unsigned_review(
            trigger="loop_end",
            sequence=2,
            previous_review_sha256=inspection["last_review_sha256"],
            loop_round=2,
        )
        try:
            final_two = self.coordinator.finalize_round(
                self.project_root,
                self.relative_path,
                end_two,
                active_review_ids=[end_two["review_id"]],
                compiled_at="2026-08-22T11:03:00Z",
                expected_coordinator_revision=second["coordinator_revision_after"],
            )
        except self.coordinator.LoopCoordinatorError as exc:
            self.fail(f"E_TEST_V265_SECOND_ROUND_CAPSULE_BLOCKED:{exc.code}")
        capsule_two = self.project_root / final_two["capsule_relative_path"]
        round_id_sha256 = hashlib.sha256(
            _descriptor(loop_round=2)["round_id"].encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(capsule_one, capsule_two)
        self.assertTrue(str(capsule_two).endswith(f".capsule.{round_id_sha256}.json"))
        self.assertEqual(bytes_one, capsule_one.read_bytes())
        self.assertTrue(capsule_two.is_file())
        bytes_two = capsule_two.read_bytes()
        self.assertNotEqual(bytes_one, bytes_two)
        capsule_one_value = json.loads(bytes_one)
        capsule_two_value = json.loads(bytes_two)
        self.assertEqual([end_one["review_id"]], capsule_one_value["source_review_ids"])
        self.assertEqual([end_two["review_id"]], capsule_two_value["source_review_ids"])
        self.assertEqual(final_one["capsule_sha256"], capsule_one_value["capsule_sha256"])
        self.assertEqual(final_two["capsule_sha256"], capsule_two_value["capsule_sha256"])
        state = json.loads(
            (self.project_root / f"{self.relative_path}.coordinator.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(final_two["capsule_relative_path"], state["capsule_relative_path"])
        self.assertEqual(final_two["capsule_sha256"], state["capsule_sha256"])
        markdown = (self.project_root / self.relative_path).read_text(encoding="utf-8")
        self.assertEqual(1, markdown.count(f"## {end_one['review_id']}\n"))
        self.assertEqual(1, markdown.count(f"## {end_two['review_id']}\n"))

    def test_flagged_evidence_is_merged_into_the_signed_problem_review(self) -> None:
        begun = self._begin(1, 0)
        flagged_refs = ["evidence:flag:a", "evidence:flag:z"]
        flagged = self.coordinator.flag_problem(
            self.project_root,
            self.relative_path,
            issue_key="repeated Gate bypass",
            evidence_refs=flagged_refs,
            occurred_at="2026-08-22T11:01:00Z",
            expected_coordinator_revision=begun["coordinator_revision_after"],
        )
        unsigned = _unsigned_review(
            trigger="problem_detected",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
            issue_key="repeated Gate bypass",
            loop_round=1,
        )
        unsigned_before = json.loads(json.dumps(unsigned))
        recorded = self.coordinator.record_problem_review(
            self.project_root,
            self.relative_path,
            unsigned,
            expected_coordinator_revision=flagged["coordinator_revision_after"],
        )
        self.assertTrue(recorded["next_action_ready"])
        self.assertEqual(unsigned_before, unsigned)
        reviews = self._inspection()["reviews"]
        self.assertEqual(1, len(reviews))
        self.assertEqual(
            sorted(set([*unsigned["evidence_refs"], *flagged_refs])),
            reviews[0]["evidence_refs"],
        )

    def test_duplicate_problem_deduplicates_before_intent_and_round_can_continue(self) -> None:
        issue_key = "same host timeout recurred"
        first = self._begin(1, 0)
        flagged_one = self.coordinator.flag_problem(
            self.project_root,
            self.relative_path,
            issue_key=issue_key,
            evidence_refs=["evidence:timeout:first"],
            occurred_at="2026-08-22T11:01:00Z",
            expected_coordinator_revision=first["coordinator_revision_after"],
        )
        problem_one = _unsigned_review(
            trigger="problem_detected",
            sequence=1,
            previous_review_sha256=ZERO_SHA256,
            issue_key=issue_key,
            loop_round=1,
        )
        recorded_one = self.coordinator.record_problem_review(
            self.project_root,
            self.relative_path,
            problem_one,
            expected_coordinator_revision=flagged_one["coordinator_revision_after"],
        )
        inspection = self._inspection()
        end_one = _unsigned_review(
            trigger="loop_end",
            sequence=2,
            previous_review_sha256=inspection["last_review_sha256"],
            loop_round=1,
        )
        final_one = self.coordinator.finalize_round(
            self.project_root,
            self.relative_path,
            end_one,
            active_review_ids=[problem_one["review_id"], end_one["review_id"]],
            compiled_at="2026-08-22T11:02:00Z",
            expected_coordinator_revision=recorded_one["coordinator_revision_after"],
        )

        second = self._begin(2, final_one["coordinator_revision_after"])
        flagged_two = self.coordinator.flag_problem(
            self.project_root,
            self.relative_path,
            issue_key=issue_key,
            evidence_refs=["evidence:timeout:second"],
            occurred_at="2026-08-22T11:03:00Z",
            expected_coordinator_revision=second["coordinator_revision_after"],
        )
        before = self._inspection()
        duplicate = _unsigned_review(
            trigger="problem_detected",
            sequence=3,
            previous_review_sha256=before["last_review_sha256"],
            issue_key=issue_key,
            loop_round=2,
        )
        review_lock = self.project_root / f"{self.relative_path}.lock"
        lock_fd = os.open(review_lock, os.O_RDWR | os.O_CREAT, 0o600)
        context = multiprocessing.get_context("fork")
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(
            target=_deduplicate_worker,
            args=(
                child_connection,
                str(self.project_root),
                self.relative_path,
                duplicate,
                flagged_two["coordinator_revision_after"],
            ),
        )
        result: tuple[str, object]
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            process.start()
            self.assertTrue(parent_connection.poll(2), "duplicate worker did not start")
            self.assertEqual(("ready", None), parent_connection.recv())
            if parent_connection.poll(1):
                result = parent_connection.recv()
            else:
                blocked_state = json.loads(
                    (
                        self.project_root
                        / f"{self.relative_path}.coordinator.json"
                    ).read_text(encoding="utf-8")
                )
                result = ("blocked", blocked_state)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            parent_connection.close()
            child_connection.close()
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
        if result[0] == "blocked":
            self.assertNotEqual(
                "committing_problem",
                result[1]["status"],
                "duplicate fingerprint persisted an intent before deduplication",
            )
            self.fail("E_TEST_V265_DUPLICATE_PROBLEM_BLOCKED_ON_REVIEW_APPEND")
        if result[0] != "ok":
            self.fail(f"E_TEST_V265_DUPLICATE_PROBLEM_TRAPPED:{result[1]}")
        deduplicated = result[1]
        self.assertTrue(deduplicated["next_action_ready"])
        self.assertEqual(problem_one["review_id"], deduplicated["review_id"])
        self.assertEqual(
            flagged_two["coordinator_revision_after"] + 1,
            deduplicated["coordinator_revision_after"],
        )
        after = self._inspection()
        self.assertEqual(before["review_state_revision"], after["review_state_revision"])
        coordinator_state = json.loads(
            (self.project_root / f"{self.relative_path}.coordinator.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("active", coordinator_state["status"])
        self.assertIsNone(coordinator_state["pending_issue_key"])
        self.assertEqual([], coordinator_state["pending_evidence_refs"])
        self.assertIsNone(coordinator_state["pending_operation"])
        self.assertIsNone(coordinator_state["pending_review_id"])
        self.assertIsNone(coordinator_state["pending_review_sha256"])
        self.assertIsNone(coordinator_state["pending_capsule_sha256"])
        markdown = (self.project_root / self.relative_path).read_text(encoding="utf-8")
        self.assertEqual(1, markdown.count(f"## {problem_one['review_id']}\n"))
        self.assertNotIn(f"## {duplicate['review_id']}\n", markdown)

        end_two = _unsigned_review(
            trigger="loop_end",
            sequence=3,
            previous_review_sha256=after["last_review_sha256"],
            loop_round=2,
        )
        completed_two = self.coordinator.finalize_round(
            self.project_root,
            self.relative_path,
            end_two,
            active_review_ids=[end_two["review_id"]],
            compiled_at="2026-08-22T11:04:00Z",
            expected_coordinator_revision=deduplicated["coordinator_revision_after"],
        )
        self.assertTrue(completed_two["finalized"])
        self.assertEqual("stop", completed_two["loop_decision"])


if __name__ == "__main__":
    unittest.main()
