from __future__ import annotations

import hashlib
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestV26ProductIdentity(unittest.TestCase):
    def test_active_generation_and_version_are_bound_to_v26(self) -> None:
        self.assertEqual("V2.6", (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        active = json.loads((ROOT / "references/current/ACTIVE.json").read_text(encoding="utf-8"))
        self.assertEqual("V2.6", active["generation_id"])
        manifest = ROOT / active["activation_manifest"]
        self.assertTrue(manifest.is_file())
        self.assertEqual(active["activation_manifest_sha256"], hashlib.sha256(manifest.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
