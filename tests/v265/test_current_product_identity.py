from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV265CurrentProductIdentity(unittest.TestCase):
    def test_human_owned_readmes_remain_byte_identical(self) -> None:
        expected = {
            "README.md": "b41fe4de55832b561b077fff0a4c41659bc11058c560ba6b01f982003c6089af",
            "README.en.md": "b31c0a6d58375282f0ec60e06d74bb7a33179828e0f2def65c4c5c3743f33ec3",
        }
        for relative, digest in expected.items():
            self.assertEqual(digest, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest())

    def test_root_identity_surfaces_are_v265(self) -> None:
        self.assertEqual("V2.65", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        needles = {
            "AGENTS.md": ("V2.65", "产品版本：`V2.65`", "V2.63"),
            "RULES.md": ("Response Contract V2.65",),
            "SKILL.md": ("Goal Teams V2.65", "Goal Teams Lead V2.65"),
            ".agents/skills/goal-teams/SKILL.md": ("Goal Teams V2.65",),
            "goal-teams.md": ("Current V2.65",),
            "agents/openai.yaml": ("Goal Teams V2.65",),
            "subagents/common-developer-instructions.txt": ("Goal Teams V2.65",),
        }
        for relative, required in needles.items():
            body = (ROOT / relative).read_text(encoding="utf-8")
            for needle in required:
                self.assertIn(needle, body, relative)

    def test_active_pointer_binds_v265_activation_bytes(self) -> None:
        active = json.loads((ROOT / "references/current/ACTIVE.json").read_text(encoding="utf-8"))
        self.assertEqual("V2.65", active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.65/activation-manifest.json",
            active["activation_manifest"],
        )
        raw = (ROOT / active["activation_manifest"]).read_bytes()
        self.assertEqual(active["activation_manifest_sha256"], hashlib.sha256(raw).hexdigest())

    def test_all_generated_subagents_are_v265(self) -> None:
        paths = sorted((ROOT / "subagents").glob("*.toml"))
        self.assertGreater(len(paths), 10)
        for path in paths:
            body = path.read_text(encoding="utf-8")
            self.assertIn('# common_prefix_generation = "V2.65"', body, path.name)
            self.assertIn("Goal Teams V2.65", body, path.name)


if __name__ == "__main__":
    unittest.main()
