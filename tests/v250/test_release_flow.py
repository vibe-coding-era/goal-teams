from __future__ import annotations

import unittest

from scripts.v250.release_flow import (
    build_s2_receipt,
    canonical_sha256,
    derive_release_plan,
    validate_release_gate_bindings,
    validate_s2_receipt,
)


SOURCE = "1" * 40
TREE = "2" * 40


def passed_gate(gate_id: str) -> dict:
    value = {
        "gate_id": gate_id,
        "source_commit": SOURCE,
        "source_tree": TREE,
        "check_state": "passed",
        "evidence_state": "current",
    }
    value["receipt_sha256"] = canonical_sha256(value)
    return value


def public_assets() -> list[dict]:
    return [
        {"name": "SHA256SUMS", "size": 10, "sha256": "a" * 64},
        {"name": "_files.sha256", "size": 20, "sha256": "b" * 64},
        {"name": "_release.json", "size": 30, "sha256": "c" * 64},
        {"name": "goal-teams-V2.62.tar.gz", "size": 42, "sha256": "d" * 64},
    ]


class TestV250ReleaseFlow(unittest.TestCase):
    def test_release_readiness_runs_once_at_final_release(self) -> None:
        plan = derive_release_plan({
            "project_size": "medium",
            "workflow_phase": "release",
            "release_intent": True,
            "implementation_scope_complete": True,
            "stage": "released",
        })
        self.assertEqual(["full_regression", "release_security_review"], plan["s1_gates"])
        self.assertEqual(1, plan["invocation_limits"]["full_regression"])
        self.assertEqual(1, plan["invocation_limits"]["release_security_review"])

    def test_s2_is_one_build_without_reproducibility_or_security_claim(self) -> None:
        receipt = build_s2_receipt(
            source_commit=SOURCE,
            source_tree=TREE,
            asset_set_id="ASSET-1",
            assets=public_assets(),
        )
        self.assertEqual(1, receipt["build_invocation_count_for_asset_set"])
        self.assertFalse(receipt["second_build_comparison_attempted"])
        self.assertEqual("not_verified_by_v250_policy", receipt["reproducibility"])
        self.assertEqual("not_run_by_v250_policy", receipt["s2_security_checks"])
        self.assertFalse(receipt["legacy_double_build_gate_loaded"])
        self.assertFalse(receipt["legacy_s2_security_gate_loaded"])
        self.assertTrue(
            validate_s2_receipt(
                receipt,
                source_commit=SOURCE,
                source_tree=TREE,
                asset_set_id="ASSET-1",
                asset_set_digest=receipt["asset_set_digest"],
            )["ok"]
        )

    def test_s2_rejects_incomplete_or_tampered_asset_set(self) -> None:
        with self.assertRaisesRegex(ValueError, "four-asset"):
            build_s2_receipt(
                source_commit=SOURCE,
                source_tree=TREE,
                asset_set_id="ASSET-1",
                assets=public_assets()[:1],
            )
        receipt = build_s2_receipt(
            source_commit=SOURCE,
            source_tree=TREE,
            asset_set_id="ASSET-1",
            assets=public_assets(),
        )
        receipt["assets"][0]["size"] += 1
        verdict = validate_s2_receipt(
            receipt,
            source_commit=SOURCE,
            source_tree=TREE,
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_S2_RECEIPT_DIGEST", verdict["errors"])

    def test_s3_is_large_release_only_after_current_s1(self) -> None:
        cases = [
            ("small", True, True, "not_required"),
            ("medium", True, True, "not_required"),
            ("large", False, True, "not_required"),
            ("large", True, False, "blocked"),
            ("large", True, True, "required"),
        ]
        for size, release_intent, s1_current, expected in cases:
            plan = derive_release_plan({
                "project_size": size,
                "workflow_phase": "release",
                "release_intent": release_intent,
                "implementation_scope_complete": True,
                "stage": "released",
                "s1_current": s1_current,
            })
            self.assertEqual(expected, plan["gates"]["s3"]["gate_requirement"])
            if expected != "required":
                self.assertEqual(0, plan["gates"]["s3"]["s3_process_invocation_count"])
                self.assertEqual([], plan["gates"]["s3"]["child_argv"])

    def test_stale_release_gate_binding_is_rejected(self) -> None:
        regression = passed_gate("full_regression")
        security = passed_gate("release_security_review")
        security["source_tree"] = "f" * 40
        verdict = validate_release_gate_bindings(SOURCE, TREE, regression, security)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_RELEASE_GATE_STALE", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
