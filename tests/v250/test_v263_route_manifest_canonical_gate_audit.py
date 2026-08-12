from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.v250.control_registry import resolve_control_term
from scripts.v250.route_derivation import derive_route


SHA = "a" * 64


def facts(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "project_size": "small",
        "workflow_phase": "development",
        "stage": "candidate",
        "release_intent": False,
        "implementation_scope_complete": False,
        "risk": "low",
        "failure_consequence": "low",
        "reversibility": "reversible",
        "compliance": "none",
        "external_write": False,
        "security_sensitive": False,
        "ui_or_desktop": False,
        "agent_runtime": False,
        "environment_check_required": False,
        "authorization_state": "not_required",
        "facts_source_sha256": SHA,
    }
    value.update(overrides)
    return value


def canonical_gates(values: object) -> set[str]:
    assert isinstance(values, list)
    return {resolve_control_term("gate", item) for item in values}


class TestV263DerivedRouteCanonicalGateClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        manifest = json.loads(
            Path(
                "references/current/generations/V2.63/prompt-manifest.json"
            ).read_text()
        )
        cls.routes = manifest["routes"]

    def assert_manifest_closed(self, receipt: dict[str, object]) -> None:
        route = self.routes[receipt["route_id"]]
        required = canonical_gates(receipt["required_gates"])
        conditional = canonical_gates(receipt["conditional_gates"])
        manifest_required = canonical_gates(route["required_gates"])
        manifest_union = manifest_required | canonical_gates(
            route["conditional_gates"]
        )
        self.assertLessEqual(manifest_required, required)
        self.assertFalse(required & conditional)
        self.assertLessEqual(required | conditional, manifest_union)

    def test_development_baselines_match_manifest_and_never_schedule_release(self) -> None:
        cases = (
            facts(project_size="small", release_intent=True),
            facts(project_size="medium", release_intent=True),
            facts(project_size="large", release_intent=True),
            facts(project_size="medium", ui_or_desktop=True, release_intent=True),
            facts(project_size="medium", agent_runtime=True, release_intent=True),
        )
        for case in cases:
            with self.subTest(case=case):
                receipt = derive_route(case)
                self.assert_manifest_closed(receipt)
                all_gates = canonical_gates(receipt["required_gates"]) | canonical_gates(
                    receipt["conditional_gates"]
                )
                self.assertNotIn("full_regression", all_gates)
                self.assertNotIn("release_security_review", all_gates)

    def test_fact_triggers_promote_only_manifest_conditionals(self) -> None:
        environment = derive_route(
            facts(project_size="small", environment_check_required=True)
        )
        self.assertIn("development_environment_check", environment["required_gates"])
        self.assertNotIn(
            "development_environment_check", environment["conditional_gates"]
        )
        self.assert_manifest_closed(environment)

        authorization = derive_route(
            facts(external_write=True, authorization_state="granted")
        )
        self.assertIn(
            "project_start_authorization", authorization["required_gates"]
        )
        self.assertNotIn(
            "project_start_authorization", authorization["conditional_gates"]
        )
        self.assert_manifest_closed(authorization)

    def test_high_risk_small_preserves_assurance_with_canonical_gate(self) -> None:
        receipt = derive_route(facts(risk="high", failure_consequence="high"))
        self.assertEqual("high", receipt["assurance_floor"])
        self.assertIn("independent_review", receipt["required_gates"])
        self.assert_manifest_closed(receipt)


if __name__ == "__main__":
    unittest.main()
