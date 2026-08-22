from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.v250 import generation_runtime
from scripts.v250 import refresh_generation_manifests as refresh
from tests.v250.v265_activation_fixture import V265ActivationFixture


REPO = pathlib.Path(__file__).resolve().parents[2]
ACTIVE = pathlib.Path("references/current/ACTIVE.json")
REFRESH = pathlib.Path("scripts/v250/refresh_generation_manifests.py")


class TestV265ActivationLifecycleHardening(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name) / "repo"
        self.fixture = V265ActivationFixture.copy_from(REPO, self.root)
        prepared = self.prepare_active()
        self.assertEqual(0, prepared.returncode, prepared.stdout)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_refresh(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.fixture.run_refresh(*arguments)

    def prepare_active(self) -> subprocess.CompletedProcess[str]:
        result = self.fixture.prepare_v265()
        self.active_raw = self.fixture.base_active_raw
        self.active_sha256 = self.fixture.base_active_sha256
        self.activation_sha256 = self.fixture.base_activation_sha256
        return result

    def test_check_state_cannot_turn_candidate_write_into_prepared_active(self) -> None:
        result = self.run_refresh(
            "--write",
            "--generation-id",
            "V2.65",
            "--base-activation-sha256",
            self.activation_sha256,
            "--check-state",
            "active",
        )
        self.assertNotEqual(0, result.returncode, result.stdout)

    def test_activate_rejects_non_rfc3339_timestamp_before_pointer_write(self) -> None:
        prepare = self.prepare_active()
        self.assertEqual(0, prepare.returncode, prepare.stdout)
        prepared = self.root / "references/current/generations/V2.65/activation-manifest.json"
        prepared_sha256 = hashlib.sha256(prepared.read_bytes()).hexdigest()
        result = self.run_refresh(
            "--activate",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-active-sha256",
            self.active_sha256,
            "--base-activation-sha256",
            self.activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_sha256,
            "--activated-at",
            "2026-08-22 17:45:00+08:00",
        )
        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertEqual(self.active_raw, (self.root / ACTIVE).read_bytes())

    def test_prepare_rejects_inconsistent_active_pointer_semantics_without_writes(self) -> None:
        protected = tuple(
            pathlib.Path(f"references/current/generations/V2.65/{name}")
            for name in (
                "rule-manifest.json",
                "prompt-manifest.json",
                "activation-manifest.json",
            )
        )
        protected_before = {path: (self.root / path).read_bytes() for path in protected}
        valid = json.loads(self.active_raw)
        mutations = (
            dict(valid, schema_version="goal-teams-active-generation-v0"),
            dict(valid, state="active_rollback"),
            dict(valid, generation_id="V9.9"),
        )
        for active in mutations:
            with self.subTest(active=active):
                (self.root / ACTIVE).write_text(
                    json.dumps(active, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                active_digest = hashlib.sha256((self.root / ACTIVE).read_bytes()).hexdigest()
                result = self.run_refresh(
                    "--prepare-active",
                    "--generation-id",
                    "V2.65",
                    "--predecessor",
                    "V2.63",
                    "--base-active-sha256",
                    active_digest,
                    "--base-activation-sha256",
                    self.activation_sha256,
                )
                self.assertNotEqual(0, result.returncode, result.stdout)
                for path, raw in protected_before.items():
                    self.assertEqual(raw, (self.root / path).read_bytes(), path)
                self.fixture.restore_v263_base()

    def test_activate_reverifies_prepared_members_immediately_before_write(self) -> None:
        prepare = self.prepare_active()
        self.assertEqual(0, prepare.returncode, prepare.stdout)
        prepared = self.root / "references/current/generations/V2.65/activation-manifest.json"
        prepared_sha256 = hashlib.sha256(prepared.read_bytes()).hexdigest()
        original_loader = generation_runtime.load_prepared_generation
        calls = 0

        def load_then_mutate(*args, **kwargs):
            nonlocal calls
            calls += 1
            result = original_loader(*args, **kwargs)
            if calls == 1:
                member = self.root / "references/current/generations/V2.65/core.md"
                member.write_bytes(member.read_bytes() + b"drift\n")
            return result

        argv = [
            str(self.root / REFRESH),
            "--activate",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-active-sha256",
            self.active_sha256,
            "--base-activation-sha256",
            self.activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_sha256,
            "--activated-at",
            "2026-08-22T17:45:00+08:00",
        ]
        with mock.patch.object(refresh, "ROOT", self.root), mock.patch.object(
            sys, "argv", argv
        ), mock.patch.object(
            generation_runtime,
            "load_prepared_generation",
            side_effect=load_then_mutate,
        ), self.assertRaises(Exception):
            refresh.main()
        self.assertGreaterEqual(calls, 2)
        self.assertEqual(self.active_raw, (self.root / ACTIVE).read_bytes())

    def test_activate_rolls_back_pointer_when_post_write_readback_fails(self) -> None:
        prepare = self.prepare_active()
        self.assertEqual(0, prepare.returncode, prepare.stdout)
        prepared = self.root / "references/current/generations/V2.65/activation-manifest.json"
        prepared_sha256 = hashlib.sha256(prepared.read_bytes()).hexdigest()
        original_atomic_write = refresh._atomic_write
        corrupted = False

        def write_then_corrupt(relative: pathlib.Path, raw: bytes) -> None:
            nonlocal corrupted
            original_atomic_write(relative, raw)
            if relative == ACTIVE and not corrupted:
                corrupted = True
                member = self.root / "references/current/generations/V2.65/core.md"
                member.write_bytes(member.read_bytes() + b"post-write-drift\n")

        argv = [
            str(self.root / REFRESH),
            "--activate",
            "--generation-id",
            "V2.65",
            "--predecessor",
            "V2.63",
            "--base-active-sha256",
            self.active_sha256,
            "--base-activation-sha256",
            self.activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_sha256,
            "--activated-at",
            "2026-08-22T17:45:00+08:00",
        ]
        with mock.patch.object(refresh, "ROOT", self.root), mock.patch.object(
            sys, "argv", argv
        ), mock.patch.object(refresh, "_atomic_write", side_effect=write_then_corrupt), self.assertRaises(
            Exception
        ):
            refresh.main()
        self.assertTrue(corrupted)
        self.assertEqual(self.active_raw, (self.root / ACTIVE).read_bytes())


if __name__ == "__main__":
    unittest.main()
