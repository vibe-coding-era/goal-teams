from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV265CurrentCompatibilityClosure(unittest.TestCase):
    def test_v265_compatibility_assets_are_complete(self) -> None:
        base = ROOT / "references/compatibility/v2.65"
        expected = {
            "manifest.json",
            "hosts/claude-code/overlay.md",
            "hosts/codex/overlay.md",
            "models/kimi-k3/route.json",
            "providers/deepseek/route.json",
            "role-projections.json",
            "roles/canonical-roles.json",
            "roles/goal-lead.md",
            "roles/goal-reviewer.md",
        }
        for relative in expected:
            self.assertTrue((base / relative).is_file(), relative)
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("goal-teams-compatibility-v2.65-v1", manifest["schema_version"])
        self.assertEqual("V2.65", manifest["product_version"])

    def test_compatibility_execution_and_schemas_share_v265_identity(self) -> None:
        from scripts.v265 import compatibility

        self.assertEqual("goal-teams-compatibility-v2.65-v1", compatibility.SCHEMA_VERSION)
        self.assertEqual("goal-teams-runtime-binding-v2.65-v1", compatibility.RECEIPT_SCHEMA_VERSION)
        for relative in (
            "schemas/v2.65/compatibility-manifest.schema.json",
            "schemas/v2.65/runtime-binding.schema.json",
            "scripts/v265/project_host_assets.py",
            "scripts/v265/role_projections.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
