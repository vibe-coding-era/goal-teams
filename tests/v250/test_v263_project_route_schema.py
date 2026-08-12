from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV263ProjectRouteSchema(unittest.TestCase):
    def test_checker_route_facts_cover_every_route_derivation_input(self) -> None:
        schema = json.loads(
            (ROOT / "schemas/v2.50/project-route.schema.json").read_text(
                encoding="utf-8"
            )
        )
        properties = schema["properties"]
        required = set(schema["required"])
        derived_facts = {
            "project_size",
            "workflow_phase",
            "release_intent",
            "implementation_scope_complete",
            "risk",
            "failure_consequence",
            "reversibility",
            "compliance",
            "external_write",
            "security_sensitive",
            "ui_or_desktop",
            "agent_runtime",
            "environment_check_required",
            "authorization_state",
            "facts_source_sha256",
        }
        self.assertTrue(derived_facts.issubset(properties))
        self.assertTrue(derived_facts.issubset(required))
        self.assertEqual(
            ["discussion", "development", "release_readiness", "release"],
            properties["workflow_phase"]["enum"],
        )
        self.assertEqual(
            ["low", "medium", "high", "critical"],
            properties["risk"]["enum"],
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
