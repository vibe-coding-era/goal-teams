"""V2.34 four-axis scoring and structured divergence TDD tests."""

from __future__ import annotations

import copy
import json
import math
import unittest
from typing import Any

from tests.v23.test_v234_state_loop import (
    FIXED_HASH_A,
    OWNER_RUN,
    VALIDATOR_RUN,
    assert_error_code,
    require_v234,
)


CRITERIA = {
    "design": ("DES-1", "DES-2", "DES-3", "DES-4"),
    "originality": ("ORG-1", "ORG-2", "ORG-3", "ORG-4"),
    "craft": ("CRF-1", "CRF-2", "CRF-3", "CRF-4"),
    "functionality": ("FUN-1", "FUN-2", "FUN-3", "FUN-4"),
}


def score_record(
    *,
    statuses: dict[str, tuple[str, str, str, str]] | None = None,
    reviewer_run_id: str = VALIDATOR_RUN,
) -> dict[str, Any]:
    statuses = statuses or {dimension: ("passed",) * 4 for dimension in CRITERIA}
    dimensions: dict[str, Any] = {}
    for dimension, criteria in CRITERIA.items():
        items = []
        for index, criterion_id in enumerate(criteria):
            status = statuses[dimension][index]
            items.append(
                {
                    "criterion_id": criterion_id,
                    "weight": 0.25,
                    "status": status,
                    "artifact_sha256": FIXED_HASH_A,
                    "evidence_refs": [f"EVD-{criterion_id}"],
                    "rationale": f"fixture for {criterion_id}",
                }
            )
        dimensions[dimension] = {
            "score": sum(item["status"] == "passed" for item in items) / 4,
            "items": items,
        }
    return {
        "rubric_version": "v234-rubric-revision-1",
        "artifact_id": "candidate-v234",
        "artifact_sha256": FIXED_HASH_A,
        "artifact_owner_run_id": OWNER_RUN,
        "dimensions": dimensions,
        "reviewer_member_id": "MEMBER-QA-V234",
        "reviewer_run_id": reviewer_run_id,
        "assessed_at": "2026-07-11T08:00:00Z",
        "evidence_refs": [f"EVD-{criterion}" for values in CRITERIA.values() for criterion in values],
    }


def intent_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_id": "LOG-INTENT-001",
        "parent_event_id": "LOG-COMMIT-000",
        "parent_event_digest": "b" * 64,
        "event_type": "INTENT",
        "bundle_revision": 3,
        "iteration": 1,
        "attempt": 1,
        "phase": "reason",
        "actor_run_id": OWNER_RUN,
        "timestamp": "2026-07-11T08:00:00Z",
        "intent_id": "INTENT-V234-001",
        "expected_constraints": ["gate:passed", "scope:scripts/v23"],
        "required_assertion_refs": ["ASSERT-V234-036", "ASSERT-V234-037"],
        "allowed_outcomes": ["partial"],
        "action_scope": ["scripts/v23"],
        "prompt_ref": "prompts/lead/loop.md",
        "prompt_sha256": "c" * 64,
        "assertion_refs": ["ASSERT-V234-036", "ASSERT-V234-037"],
        "line_number": 12,
    }
    event.update(overrides)
    return event


def judgment_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_id": "LOG-JUDGMENT-001",
        "parent_event_id": "LOG-INTENT-001",
        "parent_event_digest": "d" * 64,
        "event_type": "JUDGMENT",
        "bundle_revision": 3,
        "iteration": 1,
        "attempt": 1,
        "phase": "reason",
        "actor_run_id": OWNER_RUN,
        "timestamp": "2026-07-11T08:01:00Z",
        "intent_id": "INTENT-V234-001",
        "judgment": "Proceed within the frozen scope.",
        "expected_constraints": ["gate:passed", "scope:scripts/v23"],
        "judgment_constraints": ["gate:passed", "scope:scripts/v23"],
        "gate_decision": "passed",
        "action_scope": ["scripts/v23"],
        "prompt_ref": "prompts/lead/loop.md",
        "assertion_refs": ["ASSERT-V234-036", "ASSERT-V234-037"],
        "outcome": "partial",
        "evidence_refs": ["EVD-JUDGMENT-001"],
        "line_number": 13,
    }
    event.update(overrides)
    return event


class V234ScoreTests(unittest.TestCase):
    def test_score_dimension_and_numeric_schema(self) -> None:
        """ASSERT-V234-031"""
        v234 = require_v234(self)
        self.assertTrue(v234.validate_quality_scores(score_record())["ok"])
        bad_values = (True, "1.0", -0.01, 1.01, math.nan, math.inf, -math.inf)
        for value in bad_values:
            record = score_record()
            record["dimensions"]["design"]["score"] = value
            with self.subTest(value=value):
                self.assertFalse(v234.validate_quality_scores(record)["ok"])
        missing = score_record()
        missing["dimensions"].pop("craft")
        extra = score_record()
        extra["dimensions"]["polish"] = copy.deepcopy(extra["dimensions"]["craft"])
        self.assertFalse(v234.validate_quality_scores(missing)["ok"])
        self.assertFalse(v234.validate_quality_scores(extra)["ok"])

    def test_score_is_recomputed_from_fixed_rubric(self) -> None:
        """ASSERT-V234-032"""
        v234 = require_v234(self)
        statuses = {dimension: ("passed", "failed", "passed", "failed") for dimension in CRITERIA}
        record = score_record(statuses=statuses)
        result = v234.validate_quality_scores(record)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["computed_scores"], {dimension: 0.5 for dimension in CRITERIA})
        record["dimensions"]["design"]["score"] = 0.75
        assert_error_code(self, v234.validate_quality_scores(record), "E_V234_SCORE_RECOMPUTE")
        wrong_weight = score_record()
        wrong_weight["dimensions"]["design"]["items"][0]["weight"] = 0.5
        self.assertFalse(v234.validate_quality_scores(wrong_weight)["ok"])

    def test_score_item_provenance_and_independence(self) -> None:
        """ASSERT-V234-033"""
        v234 = require_v234(self)
        for mutation in ("missing_hash", "missing_evidence", "wrong_criterion", "self_review"):
            record = score_record()
            if mutation == "missing_hash":
                record["dimensions"]["design"]["items"][0].pop("artifact_sha256")
            elif mutation == "missing_evidence":
                record["dimensions"]["design"]["items"][0]["evidence_refs"] = []
            elif mutation == "wrong_criterion":
                record["dimensions"]["design"]["items"][0]["criterion_id"] = "FUN-1"
            else:
                record["reviewer_run_id"] = OWNER_RUN
            with self.subTest(mutation=mutation):
                self.assertFalse(v234.validate_quality_scores(record)["ok"])

    def test_unverified_and_no_threshold_semantics(self) -> None:
        """ASSERT-V234-034"""
        v234 = require_v234(self)
        unverified_status = {dimension: ("passed", "failed", "unverified", "failed") for dimension in CRITERIA}
        unverified = v234.validate_quality_scores(score_record(statuses=unverified_status))
        self.assertFalse(unverified["ok"], unverified)
        self.assertEqual(unverified["computed_scores"]["design"], 0.25)
        self.assertEqual(unverified["check_state"], "failed")
        all_failed = {dimension: ("failed",) * 4 for dimension in CRITERIA}
        low = v234.validate_quality_scores(score_record(statuses=all_failed))
        self.assertTrue(low["ok"], low)
        self.assertEqual(low["computed_scores"], {dimension: 0.0 for dimension in CRITERIA})
        self.assertFalse(low["implicit_release_threshold"])

    def test_scores_never_replace_completion_evidence(self) -> None:
        """ASSERT-V234-035"""
        v234 = require_v234(self)
        record = score_record()
        for failed_check in ("unit", "api", "e2e", "harness", "review", "completion_audit"):
            checks = {name: True for name in ("unit", "api", "e2e", "harness", "review", "completion_audit")}
            checks[failed_check] = False
            result = v234.scores_satisfy_completion(record, checks)
            with self.subTest(failed_check=failed_check):
                self.assertFalse(result["completion_allowed"], result)
                self.assertIn(failed_check, result["gaps"])


class V234DiagnosticsTests(unittest.TestCase):
    def test_divergence_frame_schema_and_grepability(self) -> None:
        """ASSERT-V234-036"""
        v234 = require_v234(self)
        judgment = judgment_event()
        line = v234.encode_log_event(judgment)
        self.assertTrue(line.startswith("GTLOG {"), line)
        encoded = json.loads(line.removeprefix("GTLOG "))
        for field in (
            "event_id", "parent_event_id", "intent_id", "expected_constraints",
            "judgment", "action_scope", "prompt_ref", "assertion_refs", "outcome",
        ):
            self.assertIn(field, encoded)
        self.assertRegex(encoded["event_digest"], r"^[0-9a-f]{64}$")

    def test_divergence_deterministic_rule_fixtures(self) -> None:
        """ASSERT-V234-037"""
        v234 = require_v234(self)
        fixtures = {
            "required_assertion_missing": judgment_event(assertion_refs=["ASSERT-V234-036"]),
            "gate_conflict": judgment_event(gate_decision="failed"),
            "action_scope_out_of_bounds": judgment_event(action_scope=["docs"]),
            "outcome_not_allowed": judgment_event(outcome="achieved"),
            "constraint_judgment_incompatible": judgment_event(judgment_constraints=["gate:failed"]),
        }
        for expected_type, judgment in fixtures.items():
            report = v234.diagnose_log_events([intent_event(), judgment])
            with self.subTest(expected_type=expected_type):
                self.assertEqual(report["divergences"][0]["divergence_type"], expected_type)
        no_semantic_guess = judgment_event(judgment="Completely different free prose.")
        self.assertEqual(
            v234.diagnose_log_events([intent_event(), no_semantic_guess])["divergences"], []
        )

    def test_divergence_scanner_first_frame_golden(self) -> None:
        """ASSERT-V234-038"""
        v234 = require_v234(self)
        first = judgment_event(
            event_id="LOG-JUDGMENT-FIRST",
            outcome="achieved",
            line_number=21,
        )
        later = judgment_event(
            event_id="LOG-JUDGMENT-LATER",
            outcome="blocked",
            action_scope=["outside"],
            line_number=33,
        )
        report = v234.diagnose_log_events([intent_event(line_number=20), first, later])
        self.assertEqual(len(report["divergences"]), 1)
        divergence = report["divergences"][0]
        self.assertEqual(divergence["line_number"], 21)
        self.assertEqual(divergence["event_id"], "LOG-JUDGMENT-FIRST")
        for field in ("intent_id", "divergence_type", "expected", "actual", "prompt_ref", "assertion_refs"):
            self.assertTrue(divergence.get(field), field)
        empty = v234.diagnose_log_events([intent_event(), judgment_event()])
        self.assertEqual(empty, {"divergences": []})

    def test_prompt_patch_scope_and_hash_binding(self) -> None:
        """ASSERT-V234-039"""
        v234 = require_v234(self)
        divergence = {
            "divergence_id": "DIV-V234-001",
            "prompt_ref": "prompts/lead/loop.md",
            "assertion_refs": ["ASSERT-V234-039"],
        }
        patch = {
            "divergence_id": "DIV-V234-001",
            "patch_id": "PATCH-V234-001",
            "prompt_ref": "prompts/lead/loop.md",
            "before_sha256": "a" * 64,
            "after_sha256": "b" * 64,
            "patch_ref": "patches/PATCH-V234-001.diff",
            "actor_run_id": OWNER_RUN,
            "reason": "bind the missing constraint",
            "status": "proposed",
        }
        self.assertTrue(
            v234.validate_prompt_patch(patch, divergence, ["prompts/lead/loop.md"])["ok"]
        )
        for mutation, value in (
            ("prompt_ref", "prompts/members/backend/prompt.md"),
            ("before_sha256", "not-a-hash"),
            ("actor_run_id", ""),
        ):
            bad = dict(patch)
            bad[mutation] = value
            with self.subTest(mutation=mutation):
                self.assertFalse(
                    v234.validate_prompt_patch(
                        bad, divergence, ["prompts/lead/loop.md"]
                    )["ok"]
                )

    def test_prompt_patch_lifecycle_and_holdout(self) -> None:
        """ASSERT-V234-040"""
        v234 = require_v234(self)
        base = {
            "patch_id": "PATCH-V234-001",
            "divergence_id": "DIV-V234-001",
            "prompt_ref": "prompts/lead/loop.md",
        }
        valid = [
            {**base, "status": "proposed"},
            {**base, "status": "applied"},
            {**base, "status": "verified", "regression_passed": True, "holdout_passed": True, "validator_run_id": VALIDATOR_RUN},
        ]
        self.assertTrue(v234.validate_prompt_patch_lifecycle(valid)["ok"])
        missing_holdout = copy.deepcopy(valid)
        missing_holdout[-1]["holdout_passed"] = False
        assert_error_code(
            self,
            v234.validate_prompt_patch_lifecycle(missing_holdout),
            "E_V234_PROMPT_PATCH_VERIFICATION",
        )
        invalid_state = [{**base, "status": "accepted"}]
        self.assertFalse(v234.validate_prompt_patch_lifecycle(invalid_state)["ok"])
        reverted = [{**base, "status": "proposed"}, {**base, "status": "reverted"}]
        self.assertTrue(v234.validate_prompt_patch_lifecycle(reverted)["ok"])


if __name__ == "__main__":
    unittest.main()
