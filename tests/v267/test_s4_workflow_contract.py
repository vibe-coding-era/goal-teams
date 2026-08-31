"""V2.67 S2-S4 and phase-aware workflow Red denominator."""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path
from types import ModuleType

from scripts.release import skill_release


ROOT = Path(__file__).resolve().parents[2]
TARGET = "V2.67"
ASSETS = (
    "SHA256SUMS",
    "_files.sha256",
    "_release.json",
    "goal-teams-V2.67.tar.gz",
)


class TestV267S4WorkflowContract(unittest.TestCase):
    def _module(self, name: str) -> ModuleType:
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as exc:
            self.fail(f"E_TEST_V267_MODULE_MISSING:{name}:{exc}")

    @staticmethod
    def _route(project_size: str) -> dict[str, object]:
        return {
            "project_size": project_size,
            "workflow_phase": "release",
            "release_intent": True,
            "implementation_scope_complete": True,
            "stage": "released",
            "s1_current": True,
        }

    def test_s2_single_build_s3_large_only_and_s4_identity(self) -> None:
        flow = self._module("scripts.v267.release_flow")
        s4 = self._module("scripts.v267.s4_executor")

        medium = flow.derive_release_plan(self._route("medium"))
        self.assertEqual(TARGET, medium["generation_id"])
        self.assertEqual(1, medium["invocation_limits"]["s2_build"])
        self.assertFalse(
            medium["gates"]["s2"]["second_build_comparison_attempted"]
        )
        self.assertEqual(
            "not_verified_by_v250_policy",
            medium["gates"]["s2"]["reproducibility"],
        )
        self.assertEqual(
            "not_run_by_v250_policy",
            medium["gates"]["s2"]["s2_security_checks"],
        )
        self.assertEqual("not_required", medium["gates"]["s3"]["check_state"])
        self.assertEqual(0, medium["gates"]["s3"]["s3_process_invocation_count"])

        large = flow.derive_release_plan(self._route("large"))
        self.assertEqual("required", large["gates"]["s3"]["gate_requirement"])
        self.assertEqual(1, large["gates"]["s3"]["s3_process_invocation_count"])
        self.assertEqual(
            "project_start_authorization_receipt",
            large["gates"]["s4"]["authorization_source"],
        )
        self.assertFalse(
            large["gates"]["s4"]["additional_user_confirmation_required"]
        )

        self.assertEqual(TARGET, s4.VERSION)
        self.assertEqual("v2.67", s4.TAG)
        self.assertEqual("Goal Teams V2.67", s4.TITLE)
        self.assertEqual(ASSETS, s4.CANONICAL_ASSET_NAMES)
        self.assertEqual(
            Path("references/release-profiles/v2.67.json"),
            s4.RELEASE_PROFILE_RELATIVE,
        )
        self.assertTrue(s4.CANONICAL_RELEASE_URL.endswith("/tag/v2.67"))

    def test_v266_predecessor_cannot_reuse_v267_current_release_flow(self) -> None:
        self.assertEqual(TARGET, skill_release.ACTIVE_SIMPLE_VERSION)
        with self.assertRaises(skill_release.SkillReleaseError) as caught:
            skill_release._release_flow_module("V2.66")
        self.assertEqual(
            "E_SKILL_RELEASE_PREDECESSOR_FLOW_UNAVAILABLE",
            caught.exception.receipt["error_code"],
        )
        current = skill_release._release_flow_module(TARGET)
        self.assertEqual(TARGET, current.CURRENT_RELEASE_VERSION)

    def test_checkpoint_resume_selects_only_unconfirmed_install_successor(self) -> None:
        s4 = self._module("scripts.v267.s4_executor")
        journal = [
            {"step_id": step_id, "state": "confirmed"}
            for step_id, *_ in s4.JOURNAL_LAYOUT[:-1]
        ]
        journal.append({"step_id": "install", "state": "attempted"})
        self.assertEqual(
            ("install",),
            tuple(s4.derive_resume_operation_ids(journal)),
        )

    def test_workflows_are_v267_and_keep_external_s4_outside_actions(self) -> None:
        check = (ROOT / ".github/workflows/check.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github/workflows/release-gate.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("Active V2.67 pre-release exact Development gate", check)
        self.assertIn("--generation-id V2.67", check)
        self.assertIn("tests.v267.", check)
        self.assertNotIn("tests.v266.", check)

        self.assertIn("Goal Teams V2.67 phase-aware verification", release)
        self.assertIn("codex/develop-v2.67", release)
        self.assertIn("Installed V2.66 host-issued V2.67 controller handoff", release)
        self.assertIn('"V2.67"', release)
        self.assertIn("--version V2.67", release)
        self.assertIn("release/versions/V2.67", release)
        self.assertIn("goal-teams-V2.67.tar.gz", release)
        self.assertIn("authorized_operation_plan_not_executed", release)
        self.assertIn("external_side_effect_count", release)
        self.assertIn("actions/upload-artifact@", release)
        self.assertNotIn("gh release create", release)
        self.assertNotIn("scripts/v267/s4_executor.py execute", release)
        self.assertNotIn("tests.v266.", release)


if __name__ == "__main__":
    unittest.main()
