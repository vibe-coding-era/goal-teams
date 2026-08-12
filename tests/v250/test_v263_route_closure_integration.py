from __future__ import annotations

import copy
import pathlib
import unittest

from scripts.v250.generation_runtime import load_candidate_generation
from scripts.v250.route_closure import (
    RouteClosureError,
    compile_derived_route_closure,
    compile_route_closure,
    validate_declared_route_closure,
)
from scripts.v250.route_derivation import derive_route
from tests.v250.v263_candidate_fixture import inactive_candidate_fixture


ROOT = pathlib.Path(__file__).resolve().parents[2]


def facts(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "project_size": "medium",
        "workflow_phase": "development",
        "stage": "candidate",
        "release_intent": True,
        "implementation_scope_complete": False,
        "risk": "medium",
        "failure_consequence": "medium",
        "reversibility": "reversible",
        "compliance": "none",
        "external_write": False,
        "security_sensitive": False,
        "ui_or_desktop": False,
        "agent_runtime": False,
        "environment_check_required": True,
        "authorization_state": "granted",
        "facts_source_sha256": "a" * 64,
    }
    value.update(overrides)
    return value


class TestV263RouteClosureIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._candidate_context = inactive_candidate_fixture(ROOT)
        cls.candidate_fixture = cls._candidate_context.__enter__()
        fixture = cls.candidate_fixture
        cls.generation = load_candidate_generation(
            fixture.root,
            generation_id="V2.63",
            activation_manifest_path=fixture.activation_path,
            expected_activation_sha256=fixture.activation_sha256,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._candidate_context.close()

    def test_runtime_closure_requires_digest_valid_derived_route_receipt(self) -> None:
        derived = derive_route(facts())
        closure = compile_derived_route_closure(
            self.candidate_fixture.root, self.generation, derived
        )

        self.assertEqual(derived["route_id"], closure["route_id"])
        self.assertEqual(derived["receipt_sha256"], closure["derived_route_sha256"])
        self.assertEqual("facts_derived", closure["route_selection_mode"])

        tampered = copy.deepcopy(derived)
        tampered["route_id"] = "V250-ROUTE-SMALL-DEVELOPMENT"
        with self.assertRaises(RouteClosureError) as error:
            compile_derived_route_closure(
                self.candidate_fixture.root, self.generation, tampered
            )
        self.assertEqual("E_V263_DERIVED_ROUTE_DIGEST", error.exception.code)

    def test_direct_route_id_is_offline_only_for_v263(self) -> None:
        with self.assertRaises(RouteClosureError) as runtime_bypass:
            compile_route_closure(
                self.candidate_fixture.root,
                self.generation,
                route_id="V250-ROUTE-MEDIUM-DEVELOPMENT",
            )
        self.assertEqual("E_V263_ROUTE_FACTS_REQUIRED", runtime_bypass.exception.code)

        offline = validate_declared_route_closure(
            self.candidate_fixture.root,
            self.generation,
            route_id="V250-ROUTE-MEDIUM-DEVELOPMENT",
        )
        self.assertEqual("offline_manifest_audit", offline["route_selection_mode"])

    def test_derived_gates_must_match_manifest_controls(self) -> None:
        derived = derive_route(facts())
        derived["required_gates"] = ["tdd"]
        from scripts.v250.generation_runtime import canonical_json_digest

        derived["receipt_sha256"] = canonical_json_digest(
            {key: value for key, value in derived.items() if key != "receipt_sha256"}
        )
        with self.assertRaises(RouteClosureError) as mismatch:
            compile_derived_route_closure(
                self.candidate_fixture.root, self.generation, derived
            )
        self.assertEqual("E_V263_DERIVED_ROUTE_REPLAY", mismatch.exception.code)


if __name__ == "__main__":
    unittest.main()
