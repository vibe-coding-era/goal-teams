from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACTIVATION = ROOT / "references/current/generations/V2.65/activation-manifest.json"


class TestV263RollbackWindow(unittest.TestCase):
    def test_rollback_window_is_closed_when_predecessor_members_no_longer_verify(self) -> None:
        candidate = json.loads(ACTIVATION.read_text(encoding="utf-8"))
        rollback = candidate["rollback"]
        predecessor_path = ROOT / rollback["activation_manifest_path"]
        predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))

        mismatches: list[str] = []
        for entries in predecessor["root_sets"].values():
            for entry in entries:
                member = ROOT / entry["path"]
                if not member.is_file():
                    mismatches.append(entry["path"])
                    continue
                observed = hashlib.sha256(member.read_bytes()).hexdigest()
                if observed != entry["sha256"]:
                    mismatches.append(entry["path"])

        self.assertTrue(mismatches, "fixture must exercise a stale predecessor closure")
        self.assertEqual("closed", rollback["window_status"])


if __name__ == "__main__":
    unittest.main()
