from __future__ import annotations

import hashlib
import importlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CURRENT_VERSION = "V2.67"
PUBLISHED_PREDECESSOR_VERSION = "V2.66"
KG_HISTORY_VERSION = "V2.63"
KG_HISTORY_GENERATION = (
    ROOT / "references" / "current" / "generations" / KG_HISTORY_VERSION
)
KG_HISTORY_ACTIVATION_SHA256 = (
    "ac4619b7eca55bd6416af7b319899ba53c4292090339d37a217ab52f313aa294"
)
SHARED_V265_RUNTIME_FILES = {
    "file schemas/v2.65/context-bundle.schema.json",
    "file schemas/v2.65/graph-contract.schema.json",
    "file schemas/v2.65/graph-runtime.schema.json",
    "file schemas/v2.65/host-capability.schema.json",
    "file schemas/v2.65/loop-coordinator.schema.json",
    "file schemas/v2.65/loop-review.schema.json",
    "file schemas/v2.65/member-packet.schema.json",
    "file scripts/v265/__init__.py",
    "file scripts/v265/canonical.py",
    "file scripts/v265/context_compiler.py",
    "file scripts/v265/graph_contract.py",
    "file scripts/v265/graph_runtime.py",
    "file scripts/v265/host_adapter.py",
    "file scripts/v265/loop_coordinator.py",
    "file scripts/v265/loop_review.py",
    "file scripts/v265/member_packet.py",
    "file scripts/v265/runtime_controller.py",
    "file scripts/v265/runtime_store.py",
}
PROTECTED_README_SHA256 = {
    "README.md": "122b693ef2cb864d1fd9d63a4aeabf5ef9f0ee4bd05f22fcbced4470b7772e60",
    "README.en.md": "b31c0a6d58375282f0ec60e06d74bb7a33179828e0f2def65c4c5c3743f33ec3",
}


def _target(testcase: unittest.TestCase):
    try:
        return importlib.import_module("scripts.v250.okf_document_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "scripts.v250.okf_document_graph":
            testcase.fail("E_KG262_TARGET_MISSING: scripts.v250.okf_document_graph")
        raise


class TestV262VersionMigration(unittest.TestCase):
    def test_product_current_is_v267_over_published_v265_predecessor(self) -> None:
        self.assertEqual(CURRENT_VERSION, (ROOT / "VERSION").read_text().strip())
        active = json.loads(
            (ROOT / "references/current/ACTIVE.json").read_text(encoding="utf-8")
        )
        self.assertEqual(CURRENT_VERSION, active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.67/activation-manifest.json",
            active["activation_manifest"],
        )
        activation_path = ROOT / active["activation_manifest"]
        self.assertTrue(activation_path.is_file())
        self.assertEqual(
            active["activation_manifest_sha256"],
            hashlib.sha256(activation_path.read_bytes()).hexdigest(),
        )
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        self.assertEqual(CURRENT_VERSION, activation["generation_id"])
        self.assertEqual(
            CURRENT_VERSION,
            activation["identity"]["loaded_runtime_product_version"],
        )
        self.assertEqual(
            CURRENT_VERSION, activation["identity"]["target_policy_generation"]
        )

        release = json.loads(
            (ROOT / "release/current/manifest.json").read_text(encoding="utf-8")
        )
        if release["product_version"] == PUBLISHED_PREDECESSOR_VERSION:
            self.assertEqual(CURRENT_VERSION, release["candidate_product_version"])
            self.assertEqual(
                "development_candidate_not_published",
                release["candidate_release_state"],
            )
        else:
            self.assertEqual(CURRENT_VERSION, release["product_version"])
            self.assertEqual("published", release["release_identity"]["state"])
        self.assertEqual("V2.5", release["core_policy_version"])
        self.assertEqual("V2.3", release["legacy_data_schema_version"])
        release_readme = (ROOT / "release/current/README.md").read_text()
        self.assertIn(release["product_version"], release_readme)

    def test_skill_identity_and_frontmatter_are_closed_without_touching_readmes(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        frontmatter = skill.split("---", 2)[1]
        keys = [
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if line.strip()
        ]
        self.assertEqual(["name", "description"], keys)
        self.assertIn("Goal Teams V2.67", skill)
        self.assertIn("我是 Goal Teams Lead V2.67。", skill)
        self.assertIn(
            "V2.67",
            (ROOT / ".agents/skills/goal-teams/SKILL.md").read_text(encoding="utf-8"),
        )
        self.assertIn("产品版本：`V2.67`", (ROOT / "AGENTS.md").read_text())
        self.assertIn("V2.67", (ROOT / "agents/openai.yaml").read_text())
        for path, expected in PROTECTED_README_SHA256.items():
            self.assertEqual(
                expected,
                hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                f"human-owned {path} changed",
            )

    def test_v262_predecessor_preserves_knowledge_graph_owner_and_prompt_isolation(self) -> None:
        activation = KG_HISTORY_GENERATION / "activation-manifest.json"
        self.assertEqual(
            KG_HISTORY_ACTIVATION_SHA256,
            hashlib.sha256(activation.read_bytes()).hexdigest(),
        )
        predecessor = json.loads(activation.read_text(encoding="utf-8"))
        generation_owned = [
            entry
            for entries in predecessor["root_sets"].values()
            for entry in entries
            if entry["path"].startswith(
                "references/current/generations/V2.63/"
            )
        ]
        self.assertEqual(23, len(generation_owned))
        for entry in generation_owned:
            with self.subTest(path=entry["path"]):
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest(),
                )
        owner = KG_HISTORY_GENERATION / "functions" / "knowledge-graph.md"
        self.assertTrue(owner.is_file())
        self.assertIn("Observe-only", owner.read_text(encoding="utf-8"))
        prompt_manifest = json.loads(
            (KG_HISTORY_GENERATION / "prompt-manifest.json").read_text(encoding="utf-8")
        )
        rule_manifest = json.loads(
            (KG_HISTORY_GENERATION / "rule-manifest.json").read_text(encoding="utf-8")
        )
        rendered = json.dumps(
            {"prompt": prompt_manifest, "rule": rule_manifest},
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertIn("functions/knowledge-graph.md", rendered)
        self.assertNotIn("legacy-replay", rendered)
        owner_mentions = [
            path
            for path in KG_HISTORY_GENERATION.rglob("*.md")
            if "OKF Document Graph" in path.read_text(encoding="utf-8")
        ]
        self.assertIn(owner, owner_mentions)

    def test_execution_core_stays_v250_and_default_package_is_v267_only(self) -> None:
        package = (ROOT / "scripts/install/package-manifest.txt").read_text(
            encoding="utf-8"
        )
        package_lines = set(package.splitlines())
        self.assertIn("prefix references/current/generations/V2.67/", package_lines)
        self.assertIn("prefix references/compatibility/v2.67/", package_lines)
        self.assertIn(
            "file references/profiles/goal-teams-self-release-v2.67.md",
            package_lines,
        )
        self.assertIn("file references/release-profiles/v2.67.json", package_lines)
        self.assertIn("prefix scripts/v250/", package)
        self.assertIn("prefix schemas/v2.50/", package)
        self.assertIn("prefix tests/v250/", package)
        self.assertEqual(
            SHARED_V265_RUNTIME_FILES,
            {
                line
                for line in package_lines
                if line.startswith(("file schemas/v2.65/", "file scripts/v265/"))
            },
        )
        self.assertIn("prefix schemas/v2.67/", package_lines)
        self.assertIn("prefix scripts/v267/", package_lines)
        self.assertIn("prefix tests/v267/", package_lines)
        self.assertNotIn("prefix references/current/generations/V2.65/", package)
        self.assertNotIn("prefix references/compatibility/v2.65/", package)
        self.assertNotIn("references/profiles/goal-teams-self-release-v2.65.md", package)
        self.assertNotIn("references/release-profiles/v2.65.json", package)
        self.assertNotIn("prefix scripts/v265/", package)
        self.assertNotIn("prefix schemas/v2.65/", package)
        self.assertNotIn("prefix tests/v265/", package)
        self.assertNotIn("prefix references/current/generations/V2.63/", package)
        self.assertNotIn("prefix scripts/v263/", package)
        self.assertNotIn("prefix schemas/v2.63/", package)
        self.assertNotIn("prefix tests/v263/", package)
        self.assertNotIn("references/legacy-replay", package)
        self.assertTrue(
            (ROOT / "schemas/v2.50/okf-document-graph.schema.json").is_file()
        )
        self.assertTrue((ROOT / "scripts/v250/okf_document_graph.py").is_file())
        self.assertTrue((ROOT / "scripts/v265").is_dir())
        self.assertTrue((ROOT / "schemas/v2.65").is_dir())
        self.assertTrue((ROOT / "tests/v263").is_dir())
        self.assertTrue((ROOT / "references/compatibility/v2.65").is_dir())

    def test_v262_predecessor_profile_and_changelog_remain_preserved(self) -> None:
        profile = json.loads(
            (ROOT / "references/release-profiles/v2.63.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(KG_HISTORY_VERSION, profile["version"])
        self.assertIn("Goal Teams V2.63", profile["release_title"])
        self.assertIn(
            "V2.63",
            (ROOT / "references/profiles/goal-teams-self-release-v2.63.md").read_text(),
        )
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("V2.63", changelog)
        self.assertIn("OKF Document Graph", changelog)
        self.assertIn("No database", changelog)
        self.assertIn("Observe-only", changelog)

    def test_runtime_module_exports_only_the_frozen_public_entrypoints(self) -> None:
        kg = _target(self)
        for name in (
            "GraphSecurityError",
            "normalize_nfc17",
            "pct_segment",
            "load_current_graph",
            "load_replay_graph",
        ):
            self.assertTrue(hasattr(kg, name), name)


if __name__ == "__main__":
    unittest.main()
