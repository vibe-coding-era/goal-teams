"""Independent V2.33 tests for explicit previews and reference fallback."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT, gt, parse_envelope, run_cli


class PlanPreviewPolicyTests(unittest.TestCase):
    def test_preview_requires_explicit_planning_only_and_no_write_intent(self) -> None:
        policy = gt.plan_preview_policy({"request_text": "只规划，不创建文件"})
        self.assertTrue(policy["plan_preview"])
        self.assertEqual(policy["persistence"], "forbidden")
        self.assertEqual(policy["reason"], "explicit_planning_only_and_no_write")

    def test_ambiguous_or_executing_requests_cannot_become_preview(self) -> None:
        incomplete = gt.plan_preview_policy({"request_text": "只规划"})
        executing = gt.plan_preview_policy({"request_text": "只规划，不落盘，随后直接执行"})
        for policy in (incomplete, executing):
            self.assertFalse(policy["plan_preview"])
            self.assertEqual(policy["persistence"], "required_or_unspecified")
        self.assertEqual(incomplete["reason"], "explicit_pair_incomplete")
        self.assertEqual(executing["reason"], "execution_or_write_intent_present")

    def test_preview_route_declares_no_write_mode(self) -> None:
        route = gt.route({"risk": "low", "plan_preview": True})
        self.assertEqual(route["mode"], "plan_preview")
        self.assertFalse(route["writes_created"])
        self.assertEqual(gt.route({"risk": "low"})["mode"], "execute")

    def test_malformed_preview_policy_request_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "invalid-preview.json"
            fixture.write_text(json.dumps({"request_text": ["只规划", "不落盘"]}), encoding="utf-8")
            proc = run_cli("plan-preview-policy", str(fixture))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(parse_envelope(proc)["error_code"], "E_PLAN_PREVIEW_POLICY_TEXT")


class ReferenceAvailabilityPolicyTests(unittest.TestCase):
    @staticmethod
    def request(**overrides: object) -> dict[str, object]:
        request: dict[str, object] = {
            "required_refs": ["RULES.md"],
            "triggered_conditional_refs": [],
            "optional_refs": [],
            "available_refs": ["RULES.md"],
            "low_risk": True,
            "acceptance_blocking": False,
            "independent_validation_required": False,
        }
        request.update(overrides)
        return request

    def test_missing_required_or_triggered_reference_is_blocked(self) -> None:
        missing_required = gt.reference_policy(
            self.request(required_refs=["RULES.md", "references/invariants.md"])
        )
        missing_triggered = gt.reference_policy(
            self.request(triggered_conditional_refs=["references/rules-ui.md"])
        )
        for policy in (missing_required, missing_triggered):
            self.assertEqual(policy["state"], "blocked")
            self.assertEqual(policy["execution_mode"], "blocked")
            self.assertFalse(policy["acceptance_allowed"])

    def test_optional_reference_can_only_degrade_non_acceptance_work(self) -> None:
        safe = gt.reference_policy(
            self.request(optional_refs=["references/rules-ui.md"])
        )
        validation_required = gt.reference_policy(
            self.request(
                optional_refs=["references/rules-ui.md"],
                independent_validation_required=True,
            )
        )
        self.assertEqual(safe["state"], "degraded")
        self.assertEqual(safe["execution_mode"], "single_agent_degraded")
        self.assertFalse(safe["acceptance_allowed"])
        self.assertEqual(validation_required["state"], "degraded")
        self.assertEqual(validation_required["execution_mode"], "blocked")
        self.assertFalse(validation_required["acceptance_allowed"])

    def test_reference_policy_rejects_malformed_lists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "invalid-reference.json"
            fixture.write_text(
                json.dumps(self.request(required_refs="RULES.md")),
                encoding="utf-8",
            )
            proc = run_cli("reference-policy", str(fixture))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(parse_envelope(proc)["error_code"], "E_REFERENCE_POLICY_LIST")


if __name__ == "__main__":
    unittest.main()
