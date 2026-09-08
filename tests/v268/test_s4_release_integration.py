"""V2.68 plan-only Actions, exact four assets and installed-observation continuity."""

from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV268S4ReleaseIntegration(unittest.TestCase):
    def test_medium_s3_is_zero_and_large_remains_conditional(self) -> None:
        flow = importlib.import_module("scripts.v268.release_flow")
        route = {"project_size": "medium", "workflow_phase": "release", "release_intent": True, "implementation_scope_complete": True, "stage": "released", "s1_current": True}
        plan = flow.derive_release_plan(route)
        self.assertEqual("V2.68", plan["generation_id"])
        self.assertEqual(1, plan["invocation_limits"]["s2_build"])
        self.assertEqual(0, plan["gates"]["s3"]["s3_process_invocation_count"])
        self.assertEqual("not_required", plan["gates"]["s3"]["check_state"])
        self.assertFalse(plan["gates"]["s4"]["additional_user_confirmation_required"])
        self.assertEqual(1, flow.derive_release_plan({**route, "project_size": "large"})["gates"]["s3"]["s3_process_invocation_count"])

    def test_exact_s4_identity_and_install_only_resume(self) -> None:
        s4 = importlib.import_module("scripts.v268.s4_executor")
        self.assertEqual("V2.68", s4.VERSION)
        self.assertEqual("v2.68", s4.TAG)
        self.assertEqual("Goal Teams V2.68", s4.TITLE)
        self.assertEqual(("SHA256SUMS", "_files.sha256", "_release.json", "goal-teams-V2.68.tar.gz"), s4.CANONICAL_ASSET_NAMES)
        journal = [{"step_id": step, "state": "confirmed"} for step, *_ in s4.JOURNAL_LAYOUT[:-1]]
        journal.append({"step_id": "install", "state": "attempted"})
        self.assertEqual(("install",), tuple(s4.derive_resume_operation_ids(journal)))

    def test_continuation_preserves_observation_and_route_triplet(self) -> None:
        release = importlib.import_module("scripts.release.skill_release")
        names = release.continuation_formal_receipts("V2.68")
        for name in ("installed-predecessor-observation.json", "release-route-facts.json", "release-route-derived.json", "release-route-receipt.json", "released-runtime-transition.json"):
            self.assertIn(name, names)
        self.assertNotIn("github-owner-key-validation.json", names)
        self.assertNotIn("controller-handoff.json", names)

    def test_workflows_bind_new_version_and_real_predecessor_without_s4_writes(self) -> None:
        workflow = (ROOT / ".github/workflows/release-gate.yml").read_text()
        check = (ROOT / ".github/workflows/check.yml").read_text()
        for marker in ("codex/develop-v2.68", "--version V2.68", "scripts/checks/check-v268.py", "scripts/v268/runtime_host_adapter.py", "--predecessor-observation-receipt", "installed-predecessor-observation.json", "predecessor_observation_receipt_json", "goal-teams-v268-release-", "authorized_operation_plan_not_executed"):
            self.assertTrue(marker in workflow, marker)
        self.assertFalse("gh release create" in workflow, "Actions must be plan-only")
        self.assertFalse("scripts/v268/s4_executor.py execute" in workflow, "S4 successor must remain outside Actions")
        self.assertFalse("tests.v267." in workflow, "predecessor suite must not execute")
        self.assertTrue("tests.v268." in check, "V2.68 current suite missing")
        self.assertFalse("tests.v267." in check, "predecessor suite must not execute")

    def test_public_assets_and_runtime_schema_stay_explicit(self) -> None:
        base = ROOT / "references/current/generations/V2.68/contracts"
        public = json.loads((base / "public-asset-map.json").read_text())
        self.assertEqual("release/versions/V2.68", public["source_root"])
        self.assertEqual({"goal-teams-V2.68.tar.gz", "SHA256SUMS", "_release.json", "_files.sha256"}, {entry["name"] for entry in public["assets"]})
        command = json.loads((base / "release-command-manifest.json").read_text())
        self.assertEqual(0, command["release"]["s4"]["external_write_invocation_count"])
        self.assertEqual(1, command["release"]["s2"]["build_invocation_limit_per_asset_set"])
        schema = json.loads((ROOT / "schemas/v2.68/release-control.schema.json").read_text())
        self.assertEqual({"const": "V2.68"}, schema["properties"]["version"])
        self.assertTrue((ROOT / "schemas/v2.68/installed-predecessor-observation.schema.json").is_file())


if __name__ == "__main__": unittest.main()
