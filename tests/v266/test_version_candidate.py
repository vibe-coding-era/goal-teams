from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = "V2.66"
PREDECESSOR = "V2.65"
GEN = ROOT / "references/current/generations/V2.66"
PROTECTED_READMES = {
    "README.md": "b41fe4de55832b561b077fff0a4c41659bc11058c560ba6b01f982003c6089af",
    "README.en.md": "b31c0a6d58375282f0ec60e06d74bb7a33179828e0f2def65c4c5c3743f33ec3",
}
SHARED_RUNTIME = {
    "scripts/v265/__init__.py",
    "scripts/v265/canonical.py",
    "scripts/v265/context_compiler.py",
    "scripts/v265/graph_contract.py",
    "scripts/v265/graph_runtime.py",
    "scripts/v265/host_adapter.py",
    "scripts/v265/loop_coordinator.py",
    "scripts/v265/loop_review.py",
    "scripts/v265/member_packet.py",
    "scripts/v265/runtime_controller.py",
    "scripts/v265/runtime_store.py",
}
SHARED_SCHEMAS = {
    "schemas/v2.65/context-bundle.schema.json",
    "schemas/v2.65/graph-contract.schema.json",
    "schemas/v2.65/graph-runtime.schema.json",
    "schemas/v2.65/host-capability.schema.json",
    "schemas/v2.65/loop-coordinator.schema.json",
    "schemas/v2.65/loop-review.schema.json",
    "schemas/v2.65/member-packet.schema.json",
}


class TestV266VersionCandidate(unittest.TestCase):
    def test_product_identity_and_human_readme_boundary(self) -> None:
        self.assertEqual(TARGET, (ROOT / "VERSION").read_text().strip())
        for relative in (
            "SKILL.md",
            "RULES.md",
            "goal-teams.md",
            "AGENTS.md",
            "agents/openai.yaml",
            ".agents/skills/goal-teams/SKILL.md",
            "subagents/common-developer-instructions.txt",
        ):
            self.assertIn(TARGET, (ROOT / relative).read_text(encoding="utf-8"), relative)
        for relative, digest in PROTECTED_READMES.items():
            self.assertEqual(digest, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest())

    def test_active_selects_v266_while_published_release_stays_predecessor(self) -> None:
        active = json.loads((ROOT / "references/current/ACTIVE.json").read_text())
        self.assertEqual(TARGET, active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.66/activation-manifest.json",
            active["activation_manifest"],
        )
        activation = json.loads((GEN / "activation-manifest.json").read_text())
        prompt = json.loads((GEN / "prompt-manifest.json").read_text())
        self.assertEqual(TARGET, activation["generation_id"])
        self.assertEqual(PREDECESSOR, activation["baseline_generation_id"])
        self.assertEqual("active", activation["generation_state"])
        self.assertEqual("active_current", prompt["manifest_state"])
        self.assertEqual(
            active["activation_manifest_sha256"],
            hashlib.sha256((GEN / "activation-manifest.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(TARGET, activation["identity"]["loaded_runtime_product_version"])
        self.assertEqual(PREDECESSOR, activation["identity"]["execution_asset_generation"])

    def test_v266_rule_and_prompt_close_output_owner(self) -> None:
        rule = json.loads((GEN / "rule-manifest.json").read_text())
        prompt = json.loads((GEN / "prompt-manifest.json").read_text())
        path = "references/current/generations/V2.66/contracts/output-dashboard.md"
        self.assertEqual(TARGET, rule["generation_id"])
        self.assertEqual(TARGET, prompt["generation_id"])
        owner = next(item for item in rule["owners"] if item["path"] == path)
        self.assertEqual("CONTRACT-OUTPUT-DASHBOARD-V266", owner["owner_id"])
        self.assertIn("GT266-OUTPUT-PDCA", owner["owned_rule_ids"])
        self.assertIn(path, prompt["current_rule_allowlist"])
        for route in prompt["routes"].values():
            self.assertIn(path, route["ordered_refs"])

    def test_activation_reuses_exact_v265_execution_without_legacy_overlap(self) -> None:
        activation = json.loads((GEN / "activation-manifest.json").read_text())
        members = {
            item["path"]
            for entries in activation["root_sets"].values()
            for item in entries
        }
        self.assertTrue(SHARED_RUNTIME.issubset(members))
        self.assertTrue(SHARED_SCHEMAS.issubset(members))
        self.assertIn("scripts/v266/output_dashboard.py", members)
        self.assertIn("schemas/v2.66/output-dashboard.schema.json", members)
        self.assertIn("tests/v266/test_output_contract.py", members)
        for forbidden in (
            "references/current/generations/V2.65/",
            "references/compatibility/v2.65/",
            "scripts/v265/compatibility.py",
            "scripts/v265/project_host_assets.py",
            "scripts/v265/role_projections.py",
            "schemas/v2.65/compatibility-manifest.schema.json",
            "schemas/v2.65/runtime-binding.schema.json",
        ):
            self.assertFalse(any(path == forbidden or path.startswith(forbidden) for path in members))
        legacy = activation["legacy_classification"]
        for path in SHARED_RUNTIME | SHARED_SCHEMAS:
            self.assertNotIn(path, legacy["exact_paths"])
            self.assertFalse(any(path.startswith(prefix) for prefix in legacy["path_prefixes"]))

    def test_package_manifest_selects_policy_adapters_and_exact_shared_runtime(self) -> None:
        package = (ROOT / "scripts/install/package-manifest.txt").read_text(encoding="utf-8")
        for marker in (
            "product V2.66, core policy V2.5, Graph execution contract V2.65, legacy data schema V2.3",
            "prefix references/current/generations/V2.66/",
            "prefix references/compatibility/v2.66/",
            "references/profiles/goal-teams-self-release-v2.66.md",
            "references/release-profiles/v2.66.json",
            "prefix scripts/v266/",
            "prefix schemas/v2.66/",
            "prefix tests/v266/",
        ):
            self.assertIn(marker, package)
        for path in SHARED_RUNTIME | SHARED_SCHEMAS:
            self.assertIn(f"file {path}", package)
        for forbidden in (
            "prefix scripts/v265/",
            "prefix schemas/v2.65/",
            "prefix tests/v265/",
            "prefix references/current/generations/V2.65/",
            "prefix references/compatibility/v2.65/",
        ):
            self.assertNotIn(forbidden, package)

    def test_profiles_and_public_projection_remain_truthful(self) -> None:
        profile = json.loads(
            (ROOT / "references/release-profiles/v2.66.json").read_text()
        )
        self.assertEqual(TARGET, profile["version"])
        self.assertEqual(PREDECESSOR, profile["published_before"])
        self.assertFalse(profile["external_writes_allowed"])
        published = json.loads((ROOT / "release/current/manifest.json").read_text())
        self.assertEqual(PREDECESSOR, published["product_version"])
        self.assertNotEqual("published", profile.get("candidate_release_state"))
        self.assertIn("## V2.66 Development Candidate", (ROOT / "CHANGELOG.md").read_text())

    def test_generated_subagents_are_v266(self) -> None:
        paths = sorted((ROOT / "subagents").glob("goal-*.toml"))
        self.assertGreater(len(paths), 10)
        for path in paths:
            body = path.read_text(encoding="utf-8")
            self.assertIn('# common_prefix_generation = "V2.66"', body, path.name)
            self.assertIn("Goal Teams V2.66", body, path.name)


if __name__ == "__main__":
    unittest.main()
