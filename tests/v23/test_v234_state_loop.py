"""V2.34 LOOP, persistence, V2.3 compatibility and bottleneck TDD tests.

The production module is loaded lazily so unittest discovery remains healthy
before ``scripts/v23/v234_state.py`` exists.  A missing module is therefore an
ordinary red test with a precise message, not a discovery/import failure.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v23.common import ROOT, gt, task_event


V234_MODULE_PATH = ROOT / "scripts" / "v23" / "v234_state.py"
FIXED_HASH_A = "a" * 64
FIXED_HASH_B = "b" * 64
FIXED_HASH_C = "c" * 64
FIXED_NOW = "2026-07-11T08:00:00Z"
OWNER_RUN = "RUN-RUNTIME-DEV-V234-01"
VALIDATOR_RUN = "RUN-QA-V234-01"

_V234: Any | None = None
_V234_LOAD_ERROR: BaseException | None = None
_STATE_PROOFS: dict[str, dict[str, Any]] = {}


def require_v234(test: unittest.TestCase):
    """Load the module under test without breaking test discovery."""
    global _V234, _V234_LOAD_ERROR
    if _V234 is None and _V234_LOAD_ERROR is None:
        try:
            spec = importlib.util.spec_from_file_location(
                "goalteams_v234_state_under_test", V234_MODULE_PATH
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {V234_MODULE_PATH}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            _V234 = module
        except BaseException as exc:  # surfaced as a deterministic red assertion
            _V234_LOAD_ERROR = exc
    if _V234_LOAD_ERROR is not None:
        test.fail(
            "V2.34 production module is not available yet: "
            f"{type(_V234_LOAD_ERROR).__name__}: {_V234_LOAD_ERROR}"
        )
    return _V234


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def synthetic_contract_text(revision: int = 2) -> str:
    rows = []
    for number in range(1, 53):
        rows.append(
            f"| ASSERT-V234-{number:03d} | deterministic assertion {number:03d} | "
            "true | unittest verifier | frozen |"
        )
    return "\n".join(
        [
            "---",
            "type: V2.34 Execution Contract",
            f"contract_revision: {revision}",
            "assertion_content_state: frozen",
            "required_assertion_count: 52",
            "owner_run_id: RUN-REQ-CONTRACT-V234-01",
            "validator_run_id: RUN-REVIEW-DESIGN-V234-01",
            "---",
            "",
            "# Synthetic V2.34 Contract",
            "",
            "| ID | 可测试断言 | Required | 计划验证器 | 内容状态 |",
            "| --- | --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )


def initialize_bundle(
    test: unittest.TestCase,
    directory: str,
    *,
    iteration: int = 1,
    attempt: int = 1,
    phase: str = "gather",
) -> tuple[Any, Path, Path, dict[str, Any]]:
    v234 = require_v234(test)
    repo_root = Path(directory)
    state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
    state_root.mkdir(parents=True)
    contract_path = state_root / "contract.md"
    contract_path.write_text(synthetic_contract_text(), encoding="utf-8")
    ledger_event = task_event(
        "EVT-V234-TEST-001",
        "TASK-V234-STATE-TEST",
        0,
        "planned",
        attempt_id="ATT-V234-STATE-TEST-01",
    )
    ledger_events = [ledger_event]
    checkpoint = gt.reduce_events(
        ledger_events, valid_evidence_ids=set(), evidence_registry={}
    )
    test.assertEqual(checkpoint["conflicts"], [])
    checkpoint_bytes = json.dumps(
        checkpoint,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    result = v234.initialize_state_bundle(
        state_root,
        repo_root=repo_root,
        loop_id="LOOP-V234-TEST",
        contract_path=contract_path,
        ledger_binding={
            "revision": 1,
            "prefix_sha256": gt.ledger_prefix_sha256(ledger_events, 1),
            "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
            "last_event_id": ledger_event["event_id"],
        },
        actor_run_id=OWNER_RUN,
        initial_loop={"iteration": iteration, "attempt": attempt, "phase": phase},
        ledger_events=ledger_events,
        checkpoint_bytes=checkpoint_bytes,
    )
    test.assertIsInstance(result, dict)
    _STATE_PROOFS[str(state_root.resolve())] = {
        "ledger_events": ledger_events,
        "checkpoint": checkpoint,
    }
    return v234, repo_root, state_root, result


def state_proof(state_root: Path) -> dict[str, Any]:
    return copy.deepcopy(_STATE_PROOFS[str(state_root.resolve())])


def marker(state_root: Path) -> dict[str, Any]:
    return json.loads((state_root / "feature_list.json").read_text(encoding="utf-8"))


def assert_error_code(
    test: unittest.TestCase, result: dict[str, Any], expected: str
) -> None:
    test.assertFalse(result.get("ok", False), result)
    test.assertEqual(result.get("error_code"), expected, result)


class V234LoopTests(unittest.TestCase):
    def test_v234_phase_enum_and_normal_edges(self) -> None:
        """ASSERT-V234-007"""
        v234 = require_v234(self)
        self.assertEqual(
            tuple(v234.V234_PHASES), ("gather", "reason", "act", "verify", "repeat")
        )
        self.assertEqual(
            set(map(tuple, v234.V234_NORMAL_EDGES)),
            {
                ("gather", "reason"),
                ("reason", "act"),
                ("act", "verify"),
                ("verify", "repeat"),
                ("repeat", "gather"),
            },
        )

    def test_structured_stop_edges_preserve_v23_semantics(self) -> None:
        """ASSERT-V234-008"""
        v234 = require_v234(self)
        for phase in v234.V234_PHASES:
            with self.subTest(phase=phase):
                valid = v234.validate_loop_transition(
                    {"phase": phase, "iteration": 3, "attempt": 1},
                    {
                        "loop_decision": "stop",
                        "run_outcome": "blocked",
                        "stop_reason": "authorization_required",
                    },
                )
                self.assertTrue(valid["ok"], valid)
                self.assertNotEqual(valid["next_state"]["run_outcome"], "achieved")
                missing_reason = v234.validate_loop_transition(
                    {"phase": phase, "iteration": 3, "attempt": 1},
                    {"loop_decision": "stop", "run_outcome": "blocked"},
                )
                assert_error_code(self, missing_reason, "E_V234_STOP_STRUCTURE")

    def test_illegal_phase_or_iteration_change_is_no_commit(self) -> None:
        """ASSERT-V234-009"""
        v234 = require_v234(self)
        bad_requests = [
            ({"phase": "gather", "iteration": 1, "attempt": 1}, {"to_phase": "act"}),
            ({"phase": "verify", "iteration": 2, "attempt": 1}, {"to_phase": "act"}),
            ({"phase": "gather", "iteration": 1, "attempt": 1}, {"to_phase": "unknown"}),
            (
                {"phase": "act", "iteration": 1, "attempt": 1},
                {"to_phase": "verify", "iteration": 2},
            ),
        ]
        for current, request in bad_requests:
            with self.subTest(current=current, request=request):
                result = v234.validate_loop_transition(current, request)
                assert_error_code(self, result, "E_V234_PHASE_TRANSITION")
                self.assertNotIn("next_state", result)

    def test_persist_before_effect_ordering(self) -> None:
        """ASSERT-V234-010"""
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, initialized = initialize_bundle(self, directory)
            before = marker(state_root)
            observed: list[tuple[int, str]] = []

            def side_effect() -> None:
                persisted = marker(state_root)
                observed.append(
                    (persisted["bundle_revision"], persisted["loop"]["phase"])
                )

            result = v234.transition_state_bundle(
                state_root,
                to_phase="reason",
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                actor_run_id=OWNER_RUN,
                side_effect=side_effect,
                **state_proof(state_root),
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(observed, [(before["bundle_revision"] + 1, "reason")])
            self.assertGreater(result["bundle_revision"], initialized["bundle_revision"])

    def test_recovery_is_deterministic_and_idempotent(self) -> None:
        """ASSERT-V234-014"""
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, _ = initialize_bundle(self, directory)
            first = v234.recover_state_bundle(state_root)
            second = v234.recover_state_bundle(state_root)
            for key in ("state", "next_phase", "iteration", "attempt", "open_gaps"):
                self.assertEqual(first[key], second[key], key)
            self.assertEqual(first["side_effects_replayed"], 0)
            self.assertEqual(second["side_effects_replayed"], 0)

        with self.subTest(case="ledger_refresh_before_write"), tempfile.TemporaryDirectory() as directory:
            v234 = require_v234(self)
            repo_root = Path(directory)
            state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
            state_root.mkdir(parents=True)
            contract_path = state_root / "contract.md"
            contract_path.write_text(synthetic_contract_text(), encoding="utf-8")
            first_event = task_event(
                "EVT-V234-REFRESH-001",
                "TASK-V234-REFRESH",
                0,
                "planned",
                attempt_id="ATT-V234-REFRESH-01",
            )
            events = [first_event]
            checkpoint = gt.reduce_events(
                events, valid_evidence_ids=set(), evidence_registry={}
            )
            self.assertEqual(checkpoint["conflicts"], [])
            checkpoint_bytes = json.dumps(
                checkpoint,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            binding = {
                "revision": 1,
                "prefix_sha256": gt.ledger_prefix_sha256(events, 1),
                "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
                "last_event_id": first_event["event_id"],
            }
            initialized = v234.initialize_state_bundle(
                state_root,
                repo_root=repo_root,
                loop_id="LOOP-V234-REFRESH",
                contract_path=contract_path,
                ledger_binding=binding,
                actor_run_id=OWNER_RUN,
                ledger_events=events,
                checkpoint_bytes=checkpoint_bytes,
            )
            self.assertTrue(initialized["ok"], initialized)

            second_event = task_event(
                "EVT-V234-REFRESH-002",
                "TASK-V234-REFRESH",
                1,
                "running",
                attempt_id="ATT-V234-REFRESH-01",
            )
            advanced_events = [first_event, second_event]
            advanced_checkpoint = gt.reduce_events(
                advanced_events, valid_evidence_ids=set(), evidence_registry={}
            )
            self.assertEqual(advanced_checkpoint["conflicts"], [])
            stale = v234.validate_state_bundle(
                state_root,
                ledger_events=advanced_events,
                checkpoint=advanced_checkpoint,
            )
            self.assertEqual(stale["state"], "stale", stale)
            before = marker(state_root)
            blind_write = v234.transition_state_bundle(
                state_root,
                to_phase="reason",
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                actor_run_id=OWNER_RUN,
            )
            assert_error_code(
                self, blind_write, "E_V234_LEDGER_REFRESH_REQUIRED"
            )
            self.assertEqual(marker(state_root)["bundle_digest"], before["bundle_digest"])

            refreshed = v234.reconcile_state_bundle(
                state_root,
                mode="replay",
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                ledger_events=advanced_events,
                checkpoint=advanced_checkpoint,
                actor_run_id=OWNER_RUN,
            )
            self.assertTrue(refreshed["ok"], refreshed)
            self.assertEqual(marker(state_root)["ledger"]["revision"], 2)
            advanced = marker(state_root)
            transitioned = v234.transition_state_bundle(
                state_root,
                to_phase="reason",
                expected_bundle_revision=advanced["bundle_revision"],
                expected_bundle_digest=advanced["bundle_digest"],
                actor_run_id=OWNER_RUN,
                ledger_events=advanced_events,
                checkpoint=advanced_checkpoint,
            )
            self.assertTrue(transitioned["ok"], transitioned)

            implementation_created = task_event(
                "EVT-V234-HISTORIC-IMPL-001",
                "TASK-V234-HISTORIC-IMPL",
                0,
                "planned",
                attempt_id="ATT-V234-HISTORIC-IMPL-01",
            )
            implementation_created["payload"].update(
                {
                    "state_gate_profile": "goal-teams-v2.34-state-v1",
                    "execution_class": "implementation",
                }
            )
            implementation_running = task_event(
                "EVT-V234-HISTORIC-IMPL-002",
                "TASK-V234-HISTORIC-IMPL",
                1,
                "running",
                attempt_id="ATT-V234-HISTORIC-IMPL-01",
                payload={
                    "v234_gate_binding": {
                        "bundle_revision": before["bundle_revision"],
                        "bundle_digest": before["bundle_digest"],
                        "contract_revision": 2,
                        "contract_sha256": "1" * 64,
                        "assertion_set_sha256": "2" * 64,
                        "external_review_sha256": "3" * 64,
                        "architecture_sha256": "4" * 64,
                        "environment_report_sha256": "5" * 64,
                    }
                },
            )
            nonimplementation = task_event(
                "EVT-V234-LATER-DOC-001",
                "TASK-V234-LATER-DOC",
                0,
                "planned",
                attempt_id="ATT-V234-LATER-DOC-01",
            )
            historic_errors = gt._validate_v234_implementation_events(
                [implementation_created, implementation_running, nonimplementation],
                str(state_root),
                candidate_event_id=nonimplementation["event_id"],
            )
            self.assertEqual(
                historic_errors,
                [],
                "later nonimplementation appends must not revalidate a historical gate against a newer state revision",
            )

    def test_v234_extension_preserves_v23_state_contract(self) -> None:
        """ASSERT-V234-017"""
        v234 = require_v234(self)
        self.assertEqual(set(v234.V23_TASK_STATES), set(gt.TASK_STATES))
        self.assertEqual(set(v234.V23_CHECK_STATES), set(gt.CHECK_STATES))
        self.assertEqual(set(v234.V23_LOOP_DECISIONS), set(gt.LOOP_DECISIONS))
        self.assertEqual(set(v234.V23_RUN_OUTCOMES), set(gt.RUN_OUTCOMES))
        self.assertFalse(
            {"complete", "done", "approved", "success"}
            & set(v234.V234_CONVENIENCE_STATES)
        )

    def test_iteration_and_attempt_accounting(self) -> None:
        """ASSERT-V234-022"""
        v234 = require_v234(self)
        retry = v234.validate_loop_transition(
            {"phase": "verify", "iteration": 8, "attempt": 1},
            {"retry": True},
        )
        self.assertTrue(retry["ok"], retry)
        self.assertEqual(retry["next_state"]["iteration"], 8)
        self.assertEqual(retry["next_state"]["attempt"], 2)
        repeat = v234.validate_loop_transition(
            {
                "phase": "repeat",
                "iteration": 8,
                "attempt": 2,
                "verify_committed": True,
                "loop_decision": "continue",
                "run_outcome": "partial",
            },
            {"to_phase": "gather"},
        )
        self.assertTrue(repeat["ok"], repeat)
        self.assertEqual(repeat["next_state"]["iteration"], 9)
        self.assertEqual(repeat["next_state"]["attempt"], 1)


class V234BottleneckTests(unittest.TestCase):
    def test_bottleneck_candidate_filter_and_categories(self) -> None:
        """ASSERT-V234-041"""
        v234 = require_v234(self)
        gaps = [
            {"gap_id": "G-1", "category": "implementation", "resolved": False, "blocks_required": True, "blocking_ac_count": 1, "downstream_required_feature_count": 1, "opened_bundle_revision": 1, "evidence_refs": ["E-1"]},
            {"gap_id": "G-2", "category": "implementation", "resolved": True, "blocks_required": True, "blocking_ac_count": 99, "downstream_required_feature_count": 99, "opened_bundle_revision": 1, "evidence_refs": ["E-2"]},
            {"gap_id": "G-3", "category": "review", "resolved": False, "blocks_required": False, "blocking_ac_count": 99, "downstream_required_feature_count": 99, "opened_bundle_revision": 1, "evidence_refs": ["E-3"]},
        ]
        result = v234.select_bottleneck(gaps)
        self.assertEqual(result["gap_id"], "G-1")
        self.assertEqual(
            set(v234.V234_BOTTLENECK_CATEGORIES),
            {"contract", "planning", "architecture", "environment", "implementation", "verification", "review", "authorization", "delivery"},
        )

    def test_bottleneck_four_level_deterministic_tuple(self) -> None:
        """ASSERT-V234-042"""
        v234 = require_v234(self)
        gaps = [
            {"gap_id": "G-Z", "category": "review", "resolved": False, "blocks_required": True, "blocking_ac_count": 3, "downstream_required_feature_count": 5, "opened_bundle_revision": 2, "evidence_refs": ["E-Z"]},
            {"gap_id": "G-B", "category": "verification", "resolved": False, "blocks_required": True, "blocking_ac_count": 3, "downstream_required_feature_count": 5, "opened_bundle_revision": 1, "evidence_refs": ["E-B"]},
            {"gap_id": "G-A", "category": "planning", "resolved": False, "blocks_required": True, "blocking_ac_count": 3, "downstream_required_feature_count": 5, "opened_bundle_revision": 1, "evidence_refs": ["E-A"]},
            {"gap_id": "G-HIGH", "category": "implementation", "resolved": False, "blocks_required": True, "blocking_ac_count": 4, "downstream_required_feature_count": 1, "opened_bundle_revision": 9, "evidence_refs": ["E-H"]},
        ]
        for ordering in (gaps, list(reversed(gaps)), [gaps[2], gaps[0], gaps[3], gaps[1]]):
            self.assertEqual(v234.select_bottleneck(ordering)["gap_id"], "G-HIGH")
        without_high = gaps[:-1]
        self.assertEqual(v234.select_bottleneck(without_high)["gap_id"], "G-A")

    def test_bottleneck_recomputed_each_verify(self) -> None:
        """ASSERT-V234-043"""
        v234 = require_v234(self)
        record = v234.recompute_bottleneck(
            previous={"gap_id": "G-OLD", "category": "implementation"},
            gaps=[{"gap_id": "G-NEW", "category": "verification", "resolved": False, "blocks_required": True, "blocking_ac_count": 2, "downstream_required_feature_count": 4, "opened_bundle_revision": 7, "evidence_refs": ["E-VERIFY"]}],
            iteration=4,
            phase="verify",
            assessment_id="BNA-V234-004",
        )
        self.assertEqual(record["previous"]["gap_id"], "G-OLD")
        self.assertEqual(record["current"]["gap_id"], "G-NEW")
        self.assertEqual(record["evidence_refs"], ["E-VERIFY"])
        self.assertTrue(record["progress_projection"])
        self.assertEqual(record["log_event"]["event_type"], "BOTTLENECK")

    def test_bottleneck_none_and_movement_fixtures(self) -> None:
        """ASSERT-V234-044"""
        v234 = require_v234(self)
        self.assertIsNone(v234.select_bottleneck([]))
        planning = [{"gap_id": "G-P", "category": "planning", "resolved": False, "blocks_required": True, "blocking_ac_count": 1, "downstream_required_feature_count": 2, "opened_bundle_revision": 1, "evidence_refs": ["E-P"]}]
        verification = [{"gap_id": "G-V", "category": "verification", "resolved": False, "blocks_required": True, "blocking_ac_count": 1, "downstream_required_feature_count": 2, "opened_bundle_revision": 2, "evidence_refs": ["E-V"]}]
        self.assertEqual(v234.select_bottleneck(planning)["category"], "planning")
        self.assertEqual(v234.select_bottleneck(verification)["category"], "verification")


if __name__ == "__main__":
    unittest.main()
