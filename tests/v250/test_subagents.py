from __future__ import annotations

import copy
import unittest

from scripts.v250.test_gate import (
    build_tdd_chain,
    validate_subagent_assurance,
    validate_test_chain,
)


class TestV250SubagentAssurance(unittest.TestCase):
    def test_independent_reviewer_with_complete_assurance_passes(self) -> None:
        verdict = validate_subagent_assurance(
            delivery_run_ids=["run-implementer", "run-test-runner"],
            reviewer_run_id="run-independent-reviewer",
            required_actor_assurances=["runner", "reviewer"],
            provided_actor_assurances=["runner", "reviewer"],
        )

        self.assertTrue(verdict["ok"])

    def test_self_review_fails_tg08(self) -> None:
        verdict = validate_subagent_assurance(
            delivery_run_ids=["run-implementer"],
            reviewer_run_id="run-implementer",
            required_actor_assurances=["reviewer"],
            provided_actor_assurances=["reviewer"],
        )

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_TG08_ASSURANCE", verdict["errors"])
        self.assertEqual("reviewer_not_independent", verdict["reason"])

    def test_missing_actor_assurance_fails_tg08(self) -> None:
        verdict = validate_subagent_assurance(
            delivery_run_ids=["run-implementer"],
            reviewer_run_id="run-independent-reviewer",
            required_actor_assurances=["runner", "reviewer"],
            provided_actor_assurances=["runner"],
        )

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_TG08_ASSURANCE", verdict["errors"])
        self.assertEqual(["reviewer"], verdict["missing_actor_assurances"])


class TestV250RetryClassification(unittest.TestCase):
    def test_fail_then_pass_retry_cannot_be_reported_as_passed(self) -> None:
        chain = build_tdd_chain(
            "DEN-FLAKE",
            "TC-FLAKE",
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "4" * 64,
        )
        mutated = copy.deepcopy(chain)
        green = mutated["runs"][1]
        green["attempts"] = [
            {"attempt_id": "ATT-2-1", "outcome": "failed"},
            {"attempt_id": "ATT-2-2", "outcome": "passed"},
        ]

        verdict = validate_test_chain(mutated)

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_TDD_FLAKE_MISCLASSIFIED", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
