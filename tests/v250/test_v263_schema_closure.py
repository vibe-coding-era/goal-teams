from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.v250.control_registry import export_control_registry


ROOT = Path(__file__).resolve().parents[2]


class TestV263SchemaClosure(unittest.TestCase):
    def test_control_registry_export_is_canonical_and_schema_bound(self) -> None:
        registry = export_control_registry()
        self.assertEqual("goal-teams-control-registry-v2.65", registry["schema_version"])
        self.assertIn("full_regression", registry["vocabularies"]["gate"])
        self.assertEqual(
            "full_regression", registry["aliases"]["gate"]["final_full_regression"]
        )
        self.assertEqual(
            "project_start_authorization",
            registry["aliases"]["gate"]["authorization"],
        )
        self.assertEqual(sorted(registry["assets"], key=lambda item: item["path_pattern"]), registry["assets"])

    def test_active_discovery_and_prompt_manifest_schemas_are_strict(self) -> None:
        required = {
            "control-registry.schema.json": "controlRegistry",
            "active-generation.schema.json": "activeGeneration",
            "discovery-snapshot.schema.json": "generationSnapshot",
            "prompt-manifest.schema.json": "promptManifest",
        }
        for filename, definition in required.items():
            with self.subTest(filename=filename):
                schema = json.loads(
                    (ROOT / "schemas/v2.50" / filename).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    "https://json-schema.org/draft/2020-12/schema", schema["$schema"]
                )
                self.assertIn(definition, schema["$defs"])
                target = schema["$defs"][definition]
                self.assertFalse(target["additionalProperties"])
                self.assertTrue(target["required"])

    def test_prompt_manifest_schema_requires_unique_order_and_canonical_gate_ids(self) -> None:
        schema = json.loads(
            (ROOT / "schemas/v2.50/prompt-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        route = schema["$defs"]["route"]
        self.assertTrue(route["properties"]["ordered_refs"]["uniqueItems"])
        gate = schema["$defs"]["gateId"]
        self.assertNotIn("final_full_regression", gate["enum"])
        self.assertIn("full_regression", gate["enum"])


if __name__ == "__main__":
    unittest.main()
