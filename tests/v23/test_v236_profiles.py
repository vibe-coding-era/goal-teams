"""V2.36 Core V2.5, self-release Profile and tiered route regressions."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "scripts" / "v23" / "v235_policy.py"


def load_policy():
    spec = importlib.util.spec_from_file_location("goalteams_v236_policy_test", POLICY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V2.36 policy")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load_policy()


def route_request(**updates):
    request = {
        "schema_version": "goal-teams-project-route-v2.36",
        "product_version": "V2.36",
        "target_kind": "generic_project",
        "project_size": "small",
        "work_type": "bugfix",
        "release": False,
        "ui": False,
        "backend": False,
        "api": False,
        "cli": True,
        "tests": True,
        "risk": "low",
        "security_sensitive": False,
        "external_write": False,
        "auth": False,
        "payment": False,
        "migration": False,
        "destructive": False,
        "ui_mode": "none",
        "specialist_requests": [],
    }
    request.update(updates)
    return request


class V236ProfileDerivationTests(unittest.TestCase):
    def test_generic_route_defaults_to_core_and_omission_cannot_skip_gate(self) -> None:
        result = policy.normalize_project_route(route_request())
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["policy_profile"], "goal-teams-core-v2.5")
        self.assertEqual(result["state_gate_profile"], "goal-teams-core-v2.5")
        self.assertEqual(result["task_type"], "cli")
        self.assertIn("references/goal-teams-core-v2.5.md", result["rule_set"])

    def test_explicit_state_gate_is_assertion_not_selector(self) -> None:
        matching = policy.normalize_project_route(
            route_request(state_gate_profile="goal-teams-core-v2.5")
        )
        self.assertTrue(matching["ok"], matching)
        mismatch = policy.normalize_project_route(
            route_request(state_gate_profile="goal-teams-self-release-v2.36")
        )
        self.assertFalse(mismatch["ok"], mismatch)
        self.assertEqual(
            mismatch["error_code"], "E_V236_STATE_GATE_PROFILE_MISMATCH"
        )

    def test_only_verified_goal_teams_release_derives_self_release_profile(self) -> None:
        release = policy.normalize_project_route(
            route_request(
                target_kind="goal_teams_repository",
                project_size="large",
                work_type="feature",
                release=True,
                cli=False,
                backend=True,
                api=True,
            )
        )
        self.assertTrue(release["ok"], release)
        self.assertEqual(release["task_type"], "goal_teams_self_release")
        self.assertEqual(
            release["policy_profile"], "goal-teams-self-release-v2.36"
        )
        self.assertEqual(release["profile"], "full")
        self.assertIn(
            "references/profiles/goal-teams-self-release-v2.36.md",
            release["rule_set"],
        )
        maintenance = policy.normalize_project_route(
            route_request(target_kind="goal_teams_repository", release=False)
        )
        self.assertTrue(maintenance["ok"], maintenance)
        self.assertEqual(maintenance["policy_profile"], "goal-teams-core-v2.5")
        backend_maintenance = policy.normalize_project_route(
            route_request(
                target_kind="goal_teams_repository",
                release=False,
                cli=False,
                backend=True,
                project_size="medium",
            )
        )
        self.assertTrue(backend_maintenance["ok"], backend_maintenance)
        self.assertEqual(backend_maintenance["task_type"], "backend")
        self.assertEqual(
            backend_maintenance["policy_profile"], "goal-teams-core-v2.5"
        )

    def test_execution_contract_binds_profile_gates_and_review_class(self) -> None:
        result = policy.normalize_project_route(
            route_request(security_sensitive=True)
        )
        self.assertTrue(result["ok"], result)
        contract = result["execution_contract"]
        self.assertEqual(contract["execution_profile"], "regulated")
        self.assertEqual(contract["required_review_class"], "safety")
        self.assertEqual(contract["gates"], result["gates"])
        self.assertEqual(contract["gate_scopes"], result["gate_scopes"])
        self.assertEqual(
            policy.validate_v236_execution_contract(result)[
                "execution_contract_sha256"
            ],
            result["execution_contract_sha256"],
        )

        stripped = copy.deepcopy(result)
        del stripped["gates"]["full_regression"]
        invalid = policy.validate_v236_execution_contract(stripped)
        self.assertFalse(invalid["ok"], invalid)

    def test_every_conditional_gate_has_a_bound_impact_scope(self) -> None:
        for updates in (
            {},
            {"project_size": "medium"},
            {
                "project_size": "medium",
                "backend": True,
                "cli": False,
            },
        ):
            with self.subTest(updates=updates):
                result = policy.normalize_project_route(route_request(**updates))
                self.assertTrue(result["ok"], result)
                conditional = {
                    gate
                    for gate, state in result["gates"].items()
                    if state == "conditional"
                }
                self.assertTrue(conditional)
                self.assertTrue(
                    all(result["gate_scopes"].get(gate) for gate in conditional)
                )
                forged = copy.deepcopy(result)
                del forged["gate_scopes"][next(iter(conditional))]
                self.assertFalse(
                    policy.validate_v236_execution_contract(forged)["ok"]
                )

    def test_goal_teams_release_cannot_be_resigned_as_core_route(self) -> None:
        result = policy.normalize_project_route(
            route_request(
                target_kind="goal_teams_repository",
                release=True,
                project_size="large",
            )
        )
        self.assertEqual(
            result["policy_profile"], "goal-teams-self-release-v2.36"
        )
        forged = copy.deepcopy(result)
        forged["policy_profile"] = "goal-teams-core-v2.5"
        forged["state_gate_profile"] = "goal-teams-core-v2.5"
        self.assertFalse(
            policy.validate_v236_execution_contract(forged)["ok"]
        )

    def test_profile_selector_rejects_self_release_for_generic_repository(self) -> None:
        result = policy.derive_policy_profile(
            {
                "schema_version": "goal-teams-policy-profile-selector-v2.36",
                "product_version": "V2.36",
                "target_kind": "generic_project",
                "task_type": "goal_teams_self_release",
                "release": True,
            }
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V236_PROFILE_TARGET_MISMATCH")

    def test_profile_selector_binds_release_to_goal_teams_task_type(self) -> None:
        base = {
            "schema_version": "goal-teams-policy-profile-selector-v2.36",
            "product_version": "V2.36",
            "target_kind": "goal_teams_repository",
        }
        missing = policy.derive_policy_profile({**base, "task_type": "cli"})
        self.assertEqual(missing["error_code"], "E_V236_PROFILE_REQUIRED")
        mismatch = policy.derive_policy_profile(
            {**base, "task_type": "cli", "release": True}
        )
        self.assertEqual(
            mismatch["error_code"], "E_V236_RELEASE_TASK_TYPE_MISMATCH"
        )
        maintenance = policy.derive_policy_profile(
            {**base, "task_type": "backend", "release": False}
        )
        self.assertTrue(maintenance["ok"], maintenance)
        self.assertEqual(maintenance["policy_profile"], "goal-teams-core-v2.5")


class V236TieredRouteTests(unittest.TestCase):
    def test_small_low_risk_cli_is_lite_not_full(self) -> None:
        result = policy.normalize_project_route(route_request())
        self.assertEqual(result["profile"], "lite", result)
        self.assertEqual(result["gates"]["architecture"], "not_required")
        self.assertEqual(result["gates"]["environment"], "conditional")
        self.assertEqual(result["gates"]["targeted_regression"], "required")
        self.assertEqual(result["gates"]["evidence"], "required")

    def test_medium_or_backend_is_standard_with_conditional_architecture(self) -> None:
        for patch in (
            {"project_size": "medium"},
            {"backend": True, "cli": False},
        ):
            with self.subTest(patch=patch):
                result = policy.normalize_project_route(route_request(**patch))
                self.assertEqual(result["profile"], "standard", result)
                self.assertEqual(result["gates"]["architecture"], "conditional")
                self.assertEqual(result["gates"]["environment"], "required")
                self.assertEqual(result["gates"]["independent_tests"], "required")

    def test_standard_backend_only_bugfix_keeps_integration_impact_conditional(self) -> None:
        request = route_request(
            project_size="medium",
            work_type="bugfix",
            backend=True,
            cli=False,
        )
        result = policy.normalize_project_route(request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["profile"], "standard")
        self.assertEqual(result["gates"]["tdd"], "required")
        self.assertEqual(result["gates"]["targeted_regression"], "required")
        self.assertEqual(result["gates"]["integration"], "conditional")
        self.assertEqual(
            result["gate_scopes"]["integration"],
            "api_data_or_cross_component_boundary_changed",
        )

    def test_standard_api_bugfix_still_requires_integration(self) -> None:
        request = route_request(
            project_size="medium",
            work_type="bugfix",
            api=True,
            cli=False,
        )
        result = policy.normalize_project_route(request)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["profile"], "standard")
        self.assertEqual(result["gates"]["integration"], "required")

    def test_standard_api_feature_requires_integration_boundary_proof(self) -> None:
        result = policy.normalize_project_route(
            route_request(
                project_size="medium",
                work_type="feature",
                api=True,
                cli=False,
            )
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["profile"], "standard")
        self.assertEqual(result["gates"]["integration"], "required")
        self.assertEqual(result["gates"]["tdd"], "conditional")
        self.assertEqual(
            result["gate_scopes"]["tdd"], "implementation_logic_changed"
        )

    def test_large_release_is_full_and_security_override_is_regulated(self) -> None:
        full = policy.normalize_project_route(
            route_request(project_size="large", work_type="feature", release=True)
        )
        self.assertEqual(full["profile"], "full", full)
        for gate in (
            "architecture",
            "environment",
            "independent_tests",
            "evidence",
            "full_regression",
            "release_evidence",
        ):
            self.assertEqual(full["gates"][gate], "required", (gate, full))
        regulated = policy.normalize_project_route(
            route_request(security_sensitive=True)
        )
        self.assertEqual(regulated["profile"], "regulated", regulated)
        self.assertEqual(regulated["required_review_class"], "safety")
        self.assertEqual(regulated["specialists"]["security"], "required")
        self.assertEqual(regulated["gates"]["architecture"], "required")

    def test_original_ui_can_be_lite_without_pixel_reference(self) -> None:
        result = policy.normalize_project_route(
            route_request(ui=True, ui_mode="original", cli=False)
        )
        self.assertEqual(result["profile"], "lite", result)
        self.assertEqual(result["task_type"], "ui_original")
        self.assertEqual(result["gates"]["e2e"], "required")
        self.assertEqual(result["gates"]["pixel_comparison"], "not_required")
        self.assertIn("references/rules-ui.md", result["rule_set"])
        self.assertNotIn(
            "references/ui-e2e-pixel-protocol.md", result["rule_set"]
        )

    def test_replica_ui_is_full_and_loads_pixel_protocol(self) -> None:
        result = policy.normalize_project_route(
            route_request(ui=True, ui_mode="replica", cli=False)
        )
        self.assertEqual(result["profile"], "full", result)
        self.assertEqual(result["task_type"], "ui_replica")
        self.assertEqual(result["required_review_class"], "comparison")
        self.assertEqual(result["gates"]["pixel_comparison"], "required")
        self.assertIn(
            "references/ui-e2e-pixel-protocol.md", result["rule_set"]
        )

    def test_ui_mode_conflict_and_derived_output_injection_fail_closed(self) -> None:
        conflict = policy.normalize_project_route(
            route_request(ui=False, ui_mode="original")
        )
        self.assertEqual(conflict["error_code"], "E_V236_UI_MODE_CONFLICT")
        injected = route_request()
        injected["policy_profile"] = "goal-teams-self-release-v2.36"
        result = policy.normalize_project_route(injected)
        self.assertEqual(result["error_code"], "E_V236_ROUTE_UNKNOWN_FIELD")

    def test_route_is_deterministic_and_v235_compatibility_is_unchanged(self) -> None:
        request = route_request(ui=True, ui_mode="original", cli=False)
        self.assertEqual(
            policy.normalize_project_route(copy.deepcopy(request)),
            policy.normalize_project_route(copy.deepcopy(request)),
        )
        legacy = route_request()
        legacy.pop("product_version")
        legacy.pop("target_kind")
        legacy.pop("ui_mode")
        legacy["schema_version"] = "goal-teams-project-route-v2.35"
        result = policy.normalize_project_route(legacy)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schema_version"], "goal-teams-project-route-v2.35")
        self.assertNotIn("policy_profile", result)


class V236RuleIsolationTests(unittest.TestCase):
    def test_self_release_rules_are_profile_scoped_in_prompts(self) -> None:
        for relative in (
            "prompts/lead/audit.md",
            "prompts/lead/completion.md",
            "prompts/lead/loop.md",
            "prompts/members/shared.md",
            "prompts/members/reviewer/prompt.md",
            "prompts/members/qa/prompt.md",
            "prompts/members/completion-auditor/prompt.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                if "iteration 9" in text or "第 9" in text or "52 条" in text:
                    self.assertIn("goal-teams-self-release-v2.37", text)

    def test_core_and_profile_references_exist(self) -> None:
        core = ROOT / "references" / "goal-teams-core-v2.5.md"
        profile = (
            ROOT
            / "references"
            / "profiles"
            / "goal-teams-self-release-v2.37.md"
        )
        self.assertTrue(core.is_file())
        self.assertTrue(profile.is_file())
        self.assertIn("goal-teams-core-v2.5", core.read_text(encoding="utf-8"))
        profile_text = profile.read_text(encoding="utf-8")
        self.assertIn("goal-teams-self-release-v2.37", profile_text)
        self.assertIn("52 条", profile_text)
        self.assertIn("iteration 9", profile_text)
        self.assertIn("iteration 11", profile_text)

    def test_v236_route_schemas_match_runtime_ids(self) -> None:
        schema_root = ROOT / "schemas" / "v2.36"
        route = json.loads(
            (schema_root / "project-route.schema.json").read_text(encoding="utf-8")
        )
        selector = json.loads(
            (schema_root / "policy-profile-selector.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            route["properties"]["schema_version"]["const"],
            policy.PROJECT_ROUTE_SCHEMA_V236,
        )
        self.assertEqual(
            selector["properties"]["schema_version"]["const"],
            policy.PROFILE_SELECTOR_SCHEMA_V236,
        )
        self.assertIn("release", selector["required"])
        execution = json.loads(
            (schema_root / "execution-contract.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(execution["$id"], policy.EXECUTION_CONTRACT_SCHEMA_V236)


if __name__ == "__main__":
    unittest.main()
