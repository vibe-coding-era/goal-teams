from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.v250.route_derivation import derive_route


ROOT = Path(__file__).resolve().parents[2]


def release_facts(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "project_size": "medium",
        "workflow_phase": "release",
        "stage": "released",
        "release_intent": True,
        "implementation_scope_complete": True,
        "risk": "high",
        "failure_consequence": "high",
        "reversibility": "partially_reversible",
        "compliance": "none",
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


class TestV263ReleaseRouteDerivation(unittest.TestCase):
    def test_release_route_controls_are_an_exact_manifest_union(self) -> None:
        prompt = json.loads(
            (
                ROOT
                / "references/current/generations/V2.65/prompt-manifest.json"
            ).read_text(encoding="utf-8")
        )
        derived = derive_route(release_facts())
        route = prompt["routes"]["V250-ROUTE-MEDIUM-RELEASE"]

        self.assertEqual("V250-ROUTE-MEDIUM-RELEASE", derived["route_id"])
        self.assertEqual(
            set(route["required_gates"]) | set(route["conditional_gates"]),
            set(derived["required_gates"]) | set(derived["conditional_gates"]),
        )
        self.assertTrue(set(route["required_gates"]).issubset(derived["required_gates"]))
        self.assertIn("fresh_runtime_transition", derived["required_gates"])
        self.assertIn("project_start_authorization", derived["required_gates"])
        self.assertNotIn("runtime_capability", derived["required_gates"])
        self.assertNotIn("ui_e2e", derived["required_gates"])

    def test_medium_and_large_release_routes_differ_only_by_s3(self) -> None:
        medium = derive_route(release_facts())
        large = derive_route(release_facts(project_size="large"))
        self.assertEqual("V250-ROUTE-LARGE-RELEASE", large["route_id"])
        self.assertNotIn("s3", medium["required_gates"])
        self.assertIn("s3", large["required_gates"])


if __name__ == "__main__":
    unittest.main()
