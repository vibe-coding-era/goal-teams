from __future__ import annotations

import copy
import unittest

from scripts.v249.test_gate import build_tdd_chain, derive_gate_plan, validate_test_chain


class TestV249TestGate(unittest.TestCase):
    def test_tdd_red_and_green_are_distinct_ordered_receipts(self) -> None:
        chain = build_tdd_chain(
            denominator_id="DEN-MEDIUM-DEV-1",
            test_case_id="TC-TDD-1",
            test_file_digest="1" * 64,
            red_source_digest="2" * 64,
            green_source_digest="3" * 64,
            environment_digest="4" * 64,
        )
        red, green = chain["runs"]
        self.assertEqual("tdd_red", red["run_role"])
        self.assertEqual("failed", red["run_outcome"])
        self.assertEqual("tdd_green", green["run_role"])
        self.assertEqual("passed", green["run_outcome"])
        self.assertEqual(red["case_digest"], green["case_digest"])
        self.assertEqual(red["test_file_digest"], green["test_file_digest"])
        self.assertNotEqual(red["source_digest"], green["source_digest"])
        self.assertNotEqual(red["digest"], green["digest"])
        self.assertTrue(validate_test_chain(chain)["ok"])

    def test_case_drift_is_rejected(self) -> None:
        chain = build_tdd_chain("DEN-1", "TC-1", "1" * 64, "2" * 64, "3" * 64, "4" * 64)
        drifted = copy.deepcopy(chain)
        drifted["runs"][1]["case_digest"] = "f" * 64
        verdict = validate_test_chain(drifted)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_TDD_CASE_DRIFT", verdict["errors"])

    def test_development_denominator_excludes_release_gates(self) -> None:
        for size in ("medium", "large"):
            plan = derive_gate_plan({
                "project_size": size,
                "workflow_phase": "development",
                "release_intent": True,
                "implementation_scope_complete": False,
                "stage": "candidate",
            })
            self.assertEqual(["tdd", "incremental"], plan["blocking_gates"])
            for gate in ("full_regression", "release_security_review", "s0", "s1", "s2", "s3", "s4"):
                self.assertEqual("not_required", plan["gates"][gate]["gate_requirement"])
                self.assertEqual("not_run", plan["gates"][gate]["run_outcome"])


if __name__ == "__main__":
    unittest.main()
