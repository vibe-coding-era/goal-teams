from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest

from scripts.v263.role_projections import check_role_projections
from scripts.v250 import okf_conformance


ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_package_checker():
    path = ROOT / "scripts/checks/check-package-manifest.py"
    spec = importlib.util.spec_from_file_location("check_package_manifest_v263", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load package checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV263DeliveryClosure(unittest.TestCase):
    def test_role_projection_plan_and_generated_assets_are_closed(self) -> None:
        verdict = check_role_projections(ROOT)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(
            {
                "references/compatibility/v2.63/projections/codex/subagents/goal-lead.toml",
                "references/compatibility/v2.63/projections/codex/subagents/goal-reviewer.toml",
                "references/compatibility/v2.63/projections/claude-code/.claude/agents/goal-lead.md",
                "references/compatibility/v2.63/projections/claude-code/.claude/agents/goal-reviewer.md",
            },
            set(verdict["projected_paths"]),
        )

    def test_activation_contains_v263_compatibility_execution_and_schema(self) -> None:
        active = json.loads((ROOT / "references/current/ACTIVE.json").read_text(encoding="utf-8"))
        activation = json.loads((ROOT / active["activation_manifest"]).read_text(encoding="utf-8"))
        allowlist = set(activation["current_default_allowlist"])
        for required in (
            "references/compatibility/v2.63/manifest.json",
            "references/compatibility/v2.63/role-projections.json",
            "schemas/v2.63/compatibility-manifest.schema.json",
            "scripts/v263/compatibility.py",
            "scripts/v263/role_projections.py",
            "tests/v263/test_delivery_closure.py",
        ):
            self.assertIn(required, allowlist)

    def test_default_package_is_a_valid_v263_current_closure(self) -> None:
        checker = load_package_checker()
        verdict = checker.validate_manifest(
            ROOT / "scripts/install/package-manifest.txt", replay=False
        )
        self.assertTrue(verdict["passed"], verdict)

    def test_default_package_markdown_passes_okf_preview(self) -> None:
        policy = okf_conformance.load_policy(ROOT)
        package_paths = okf_conformance._payload_paths(ROOT, policy)
        verdict = okf_conformance.scan_paths(
            [path for path in package_paths if path.suffix == ".md"],
            policy,
            {"root": ROOT, "mode": "package-preview"},
        )
        self.assertTrue(verdict["passed"], verdict["findings"])

    def test_non_readme_current_identity_surfaces_are_v263(self) -> None:
        expected = {
            "SKILL.md": ("Goal Teams V2.63",),
            ".agents/skills/goal-teams/SKILL.md": ("V2.63",),
            "RULES.md": ("V2.63",),
            "goal-teams.md": ("V2.63",),
            "AGENTS.md": ("产品版本：`V2.63`",),
            "agents/openai.yaml": ("Goal Teams V2.63",),
        }
        for relative, needles in expected.items():
            with self.subTest(path=relative):
                body = (ROOT / relative).read_text(encoding="utf-8")
                for needle in needles:
                    self.assertIn(needle, body)


if __name__ == "__main__":
    unittest.main()
