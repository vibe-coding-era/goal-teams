from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "references/current/generations/V2.65"


class TestV265CurrentGenerationClosure(unittest.TestCase):
    def test_graph_and_loop_rules_have_current_consumers(self) -> None:
        required = {
            "functions/graph-engineering.md",
            "contracts/loop-evolution.md",
        }
        for relative in required:
            self.assertTrue((GEN / relative).is_file(), relative)

        rule = json.loads((GEN / "rule-manifest.json").read_text(encoding="utf-8"))
        prompt = json.loads((GEN / "prompt-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("V2.65", rule["generation_id"])
        self.assertEqual("V2.65", prompt["generation_id"])
        owner_paths = {owner["path"] for owner in rule["owners"]}
        allowlist = set(prompt["current_rule_allowlist"])
        for relative in required:
            path = f"references/current/generations/V2.65/{relative}"
            self.assertIn(path, owner_paths)
            self.assertIn(path, allowlist)
            self.assertTrue(any(path in route["ordered_refs"] for route in prompt["routes"].values()))

    def test_activation_closes_v265_runtime_and_excludes_predecessor_current(self) -> None:
        activation = json.loads((GEN / "activation-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("V2.65", activation["generation_id"])
        self.assertEqual("V2.63", activation["baseline_generation_id"])
        self.assertEqual("active", activation["generation_state"])
        self.assertEqual("V2.65", activation["identity"]["loaded_runtime_product_version"])
        self.assertEqual("V2.5", activation["identity"]["core_policy_version"])
        self.assertEqual("V2.3", activation["identity"]["legacy_data_schema_version"])
        members = {
            item["path"]: item
            for entries in activation["root_sets"].values()
            for item in entries
        }
        required = {
            "scripts/v265/graph_contract.py",
            "scripts/v265/graph_runtime.py",
            "scripts/v265/runtime_controller.py",
            "scripts/v265/runtime_store.py",
            "scripts/v265/loop_coordinator.py",
            "schemas/v2.65/graph-contract.schema.json",
            "schemas/v2.65/graph-runtime.schema.json",
            "schemas/v2.65/loop-review.schema.json",
            "references/compatibility/v2.65/manifest.json",
        }
        self.assertTrue(required.issubset(members))
        for relative in required:
            raw = (ROOT / relative).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), members[relative]["sha256"])
            self.assertEqual(len(raw), members[relative]["bytes"])
        forbidden_prefixes = (
            "references/current/generations/V2.63/",
            "references/compatibility/v2.63/",
            "scripts/v263/",
            "schemas/v2.63/",
        )
        self.assertFalse(
            [path for path in members if path.startswith(forbidden_prefixes)],
            "predecessor paths entered Current root sets",
        )

    def test_manifest_payload_and_active_digest_are_canonical(self) -> None:
        activation_path = GEN / "activation-manifest.json"
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        payload = dict(activation)
        payload.pop("manifest_payload_sha256")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            activation["manifest_payload_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
