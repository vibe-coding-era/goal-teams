from __future__ import annotations

import copy
import unittest

from scripts.v250.generation_runtime import canonical_json_digest
from scripts.v250.route_closure import (
    RouteClosureError,
    _validate_derived_route_receipt,
)
from scripts.v250.route_derivation import derive_route


def facts(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "project_size": "large",
        "workflow_phase": "development",
        "stage": "candidate",
        "release_intent": True,
        "implementation_scope_complete": False,
        "risk": "critical",
        "failure_consequence": "critical",
        "reversibility": "irreversible",
        "compliance": "regulated",
        "external_write": True,
        "security_sensitive": True,
        "ui_or_desktop": False,
        "agent_runtime": True,
        "environment_check_required": True,
        "authorization_state": "granted",
        "facts_source_sha256": "a" * 64,
    }
    value.update(overrides)
    return value


class TestV263RouteClosureTrustBoundary(unittest.TestCase):
    def test_closure_cannot_bypass_exact_facts_replay(self) -> None:
        original = derive_route(facts())
        downgraded = derive_route(
            facts(
                project_size="small",
                risk="low",
                failure_consequence="low",
                reversibility="reversible",
                compliance="none",
                external_write=False,
                security_sensitive=False,
                agent_runtime=False,
                environment_check_required=False,
                authorization_state="not_required",
            )
        )
        attacked = copy.deepcopy(original)
        for field in (
            "project_size",
            "workflow_phase",
            "stage",
            "route_id",
            "assurance_floor",
            "effective_assurance",
            "required_gates",
            "conditional_gates",
            "exclusion_reasons",
        ):
            attacked[field] = copy.deepcopy(downgraded[field])
        attacked["receipt_sha256"] = canonical_json_digest(
            {key: value for key, value in attacked.items() if key != "receipt_sha256"}
        )
        generation = {
            "generation_id": "V2.65",
            "prompt_manifest": {
                "routes": {
                    downgraded["route_id"]: {
                        "workflow_phase": downgraded["workflow_phase"],
                        "required_gates": downgraded["required_gates"],
                        "conditional_gates": downgraded["conditional_gates"],
                    }
                }
            },
        }

        with self.assertRaises(RouteClosureError) as caught:
            _validate_derived_route_receipt(generation, attacked)
        self.assertEqual("E_V263_DERIVED_ROUTE_REPLAY", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
