from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts.v250 import refresh_generation_manifests as refresh
from scripts.v250.generation_runtime import (
    GenerationLoadError,
    load_generation,
    load_prepared_generation,
)
from tests.v250.v263_activation_fixture import V263ActivationFixture


REPO = pathlib.Path(__file__).resolve().parents[2]
ACTIVE = pathlib.Path("references/current/ACTIVE.json")
V263_ACTIVATION = pathlib.Path(
    "references/current/generations/V2.63/activation-manifest.json"
)
V263_PROMPT = pathlib.Path(
    "references/current/generations/V2.63/prompt-manifest.json"
)
V263_RULE = pathlib.Path(
    "references/current/generations/V2.63/rule-manifest.json"
)
VALIDATOR = pathlib.Path("scripts/checks/validate-v250-generation.py")
ACTIVATED_AT = "2026-08-12T17:45:00+08:00"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class TestV263ActivationLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name) / "repo"
        self.fixture = V263ActivationFixture.copy_from(REPO, self.root)
        prepared = self.fixture.prepare_v263()
        self.assertEqual(0, prepared.returncode, prepared.stdout)
        self.base_active_sha256 = self.fixture.base_active_sha256
        self.base_activation_sha256 = self.fixture.base_activation_sha256
        self.assertEqual(
            self.fixture.base_active_raw,
            (self.root / ACTIVE).read_bytes(),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_refresh(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.fixture.run_refresh(*arguments)

    def prepare_active(self) -> str:
        before = (self.root / ACTIVE).read_bytes()
        result = self.fixture.prepare_v263()
        self.assertEqual(0, result.returncode, result.stdout)
        self.base_active_sha256 = self.fixture.base_active_sha256
        self.base_activation_sha256 = self.fixture.base_activation_sha256
        self.assertEqual(before, (self.root / ACTIVE).read_bytes())
        activation_raw = (self.root / V263_ACTIVATION).read_bytes()
        activation = json.loads(activation_raw)
        prompt = json.loads((self.root / V263_PROMPT).read_bytes())
        self.assertEqual("active", activation["generation_state"])
        self.assertEqual("active_current", prompt["manifest_state"])
        members = {
            entry["path"]
            for entries in activation["root_sets"].values()
            for entry in entries
        }
        self.assertNotIn("release/current/manifest.json", members)
        self.assertNotIn(
            "release/current/manifest.json",
            activation["current_default_allowlist"],
        )
        return sha256(activation_raw)

    def test_prepare_then_pointer_only_activate_uses_three_way_cas(self) -> None:
        prepared_digest = self.prepare_active()
        prepared_bytes = {
            path: (self.root / path).read_bytes()
            for path in (V263_RULE, V263_PROMPT, V263_ACTIVATION)
        }
        active_before = (self.root / ACTIVE).read_bytes()

        wrong = self.run_refresh(
            "--activate",
            "--generation-id",
            "V2.63",
            "--base-active-sha256",
            "0" * 64,
            "--base-activation-sha256",
            self.base_activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_digest,
            "--activated-at",
            ACTIVATED_AT,
        )
        self.assertNotEqual(0, wrong.returncode, wrong.stdout)
        self.assertEqual(active_before, (self.root / ACTIVE).read_bytes())

        activated = self.run_refresh(
            "--activate",
            "--generation-id",
            "V2.63",
            "--base-active-sha256",
            self.base_active_sha256,
            "--base-activation-sha256",
            self.base_activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_digest,
            "--activated-at",
            ACTIVATED_AT,
        )
        self.assertEqual(0, activated.returncode, activated.stdout)
        active = json.loads((self.root / ACTIVE).read_bytes())
        self.assertEqual("V2.63", active["generation_id"])
        self.assertEqual(prepared_digest, active["activation_manifest_sha256"])
        self.assertEqual(ACTIVATED_AT, active["updated_at"])
        for path, raw in prepared_bytes.items():
            self.assertEqual(raw, (self.root / path).read_bytes(), path)

        repeated = self.run_refresh(
            "--activate",
            "--generation-id",
            "V2.63",
            "--base-active-sha256",
            self.base_active_sha256,
            "--base-activation-sha256",
            self.base_activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_digest,
            "--activated-at",
            ACTIVATED_AT,
        )
        self.assertNotEqual(0, repeated.returncode, repeated.stdout)

    def test_active_loader_rejects_candidate_and_release_projection_is_external(self) -> None:
        candidate = self.run_refresh(
            "--write",
            "--generation-id",
            "V2.63",
            "--predecessor",
            "V2.62",
            "--base-activation-sha256",
            self.base_activation_sha256,
        )
        self.assertEqual(0, candidate.returncode, candidate.stdout)
        candidate_raw = (self.root / V263_ACTIVATION).read_bytes()
        active = json.loads((self.root / ACTIVE).read_bytes())
        active.update(
            {
                "generation_id": "V2.63",
                "activation_manifest": V263_ACTIVATION.as_posix(),
                "activation_manifest_sha256": sha256(candidate_raw),
            }
        )
        (self.root / ACTIVE).write_text(
            json.dumps(active, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(GenerationLoadError) as caught:
            load_generation(self.root)
        self.assertEqual("E_V250_ACTIVE_STATE", caught.exception.code)

        # Restore the exact base pointer, prepare, explicitly verify the prepared
        # active generation, then activate it.
        self.fixture.restore_v262_base()
        prepared_digest = self.prepare_active()
        prepared = load_prepared_generation(
            self.root,
            generation_id="V2.63",
            activation_manifest_path=V263_ACTIVATION.as_posix(),
            expected_activation_sha256=prepared_digest,
        )
        self.assertEqual("prepared_active_expected_digest", prepared["selection_mode"])
        activated = self.run_refresh(
            "--activate",
            "--generation-id",
            "V2.63",
            "--base-active-sha256",
            self.base_active_sha256,
            "--base-activation-sha256",
            self.base_activation_sha256,
            "--expected-prepared-activation-sha256",
            prepared_digest,
            "--activated-at",
            ACTIVATED_AT,
        )
        self.assertEqual(0, activated.returncode, activated.stdout)
        generation = load_generation(self.root)
        self.assertEqual("active", generation["activation_manifest"]["generation_state"])

        release_projection = self.root / "release/current/manifest.json"
        release_projection.write_text("{}\n", encoding="utf-8")
        generation_after_projection = load_generation(self.root)
        self.assertEqual(
            generation["activation_manifest_sha256"],
            generation_after_projection["activation_manifest_sha256"],
        )

    def test_validator_requires_explicit_candidate_or_active_selection(self) -> None:
        candidate = self.run_refresh(
            "--write",
            "--generation-id",
            "V2.63",
            "--predecessor",
            "V2.62",
            "--base-activation-sha256",
            self.base_activation_sha256,
        )
        self.assertEqual(0, candidate.returncode, candidate.stdout)
        candidate_digest = sha256((self.root / V263_ACTIVATION).read_bytes())
        candidate_validation = subprocess.run(
            [
                sys.executable,
                str(self.root / VALIDATOR),
                "--generation-id",
                "V2.63",
                "--selection",
                "candidate",
                "--expected-activation-sha256",
                candidate_digest,
                "--json",
            ],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, candidate_validation.returncode, candidate_validation.stdout)
        self.assertEqual(
            "candidate",
            json.loads(candidate_validation.stdout)["selection"],
        )

        implicit = subprocess.run(
            [
                sys.executable,
                str(self.root / VALIDATOR),
                "--generation-id",
                "V2.63",
                "--json",
            ],
            cwd=self.root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertNotEqual(0, implicit.returncode, implicit.stdout)
        self.assertIn("--selection", implicit.stdout)

    def test_atomic_write_fsyncs_the_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            relative = pathlib.Path("nested/value.json")
            with mock.patch.object(refresh, "ROOT", root), mock.patch.object(
                refresh.os, "open", wraps=os.open
            ) as opened:
                refresh._atomic_write(relative, b'{"ok": true}\n')
            self.assertTrue(
                any(
                    pathlib.Path(call.args[0]) == (root / relative).parent
                    for call in opened.call_args_list
                ),
                opened.call_args_list,
            )


if __name__ == "__main__":
    unittest.main()
