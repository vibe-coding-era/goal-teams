from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.v250.v265_activation_fixture import V265ActivationFixture


ROOT = Path(__file__).resolve().parents[2]
ACTIVE = Path("references/current/ACTIVE.json")
ACTIVATION = Path("references/current/generations/V2.65/activation-manifest.json")
RULE = Path("references/current/generations/V2.65/rule-manifest.json")
PROMPT = Path("references/current/generations/V2.65/prompt-manifest.json")
OWNER = Path("references/current/generations/V2.65/functions/graph-engineering.md")


class TestV265ActiveGenerationRefresh(unittest.TestCase):
    def setUp(self) -> None:
        (ROOT / "develops").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="v265-active-refresh-", dir=ROOT / "develops"
        )
        self.repo = Path(self.temporary.name) / "repo"
        environment = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CEILING_DIRECTORIES": self.temporary.name,
        }
        self.fixture = V265ActivationFixture.copy_from(
            ROOT, self.repo, environment=environment
        )
        prepared = self.fixture.prepare_v265()
        self.assertEqual(0, prepared.returncode, prepared.stdout)
        activated = self.fixture.run_refresh(
            "--activate",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-active-sha256",
            self.fixture.base_active_sha256,
            "--base-activation-sha256",
            self.fixture.base_activation_sha256,
            "--expected-prepared-activation-sha256",
            str(self.fixture.prepared_activation_sha256),
            "--activated-at",
            "2026-08-22T20:20:00+08:00",
        )
        self.assertEqual(0, activated.returncode, activated.stdout)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _active_identity(self) -> tuple[str, str]:
        active_raw = (self.repo / ACTIVE).read_bytes()
        active = json.loads(active_raw)
        return hashlib.sha256(active_raw).hexdigest(), active["activation_manifest_sha256"]

    def test_refresh_active_rebinds_changed_member_and_preserves_predecessor(self) -> None:
        base_active, base_activation = self._active_identity()
        owner = self.repo / OWNER
        owner.write_text(owner.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        refreshed = self.fixture.run_refresh(
            "--refresh-active",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-active-sha256",
            base_active,
            "--base-activation-sha256",
            base_activation,
            "--activated-at",
            "2026-08-22T20:21:00+08:00",
        )
        self.assertEqual(0, refreshed.returncode, refreshed.stdout)
        new_active, new_activation = self._active_identity()
        self.assertNotEqual(base_active, new_active)
        self.assertNotEqual(base_activation, new_activation)
        activation = json.loads((self.repo / ACTIVATION).read_text(encoding="utf-8"))
        self.assertEqual("V2.63", activation["baseline_generation_id"])
        member = next(
            item
            for entries in activation["root_sets"].values()
            for item in entries
            if item["path"] == OWNER.as_posix()
        )
        self.assertEqual(hashlib.sha256(owner.read_bytes()).hexdigest(), member["sha256"])

    def test_refresh_active_wrong_cas_changes_no_projection_bytes(self) -> None:
        base_active, base_activation = self._active_identity()
        before = {
            path: (self.repo / path).read_bytes()
            for path in (ACTIVE, ACTIVATION, RULE, PROMPT)
        }
        rejected = self.fixture.run_refresh(
            "--refresh-active",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-active-sha256",
            "0" * 64,
            "--base-activation-sha256",
            base_activation,
            "--activated-at",
            "2026-08-22T20:22:00+08:00",
        )
        self.assertNotEqual(0, rejected.returncode, rejected.stdout)
        self.assertEqual(
            before,
            {path: (self.repo / path).read_bytes() for path in before},
        )
        self.assertNotEqual("0" * 64, base_active)


if __name__ == "__main__":
    unittest.main()
