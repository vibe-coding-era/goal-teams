"""V2.67 fresh runtime transition and S0 predecessor identity Red denominator."""

from __future__ import annotations

import copy
import datetime as dt
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TARGET = "V2.67"
PREDECESSOR = "V2.66"
VALIDATION_TIME = dt.datetime(2026, 8, 26, 8, 5, tzinfo=dt.timezone.utc)
PUBLISHED_V266_IDENTITY = {
    "tag": "v2.66",
    "release_id": 377935171,
    "state": "published",
    "source_commit": "a9925d787afaf428e20caa2058641da49c6d89d4",
    "source_tree": "8d62a263584c9772d8f94d85cf9d5272efd2ec29",
    "public_assets": [
        "goal-teams-V2.66.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    ],
}


class TestV267ReleaseRuntimeTransition(unittest.TestCase):
    def _runtime(self) -> ModuleType:
        try:
            return importlib.import_module("scripts.v267.runtime_transition")
        except ModuleNotFoundError as exc:
            self.fail(f"E_TEST_V267_RUNTIME_MODULE_MISSING:{exc}")

    def _installed_state(
        self, runtime: ModuleType, identity: dict[str, object]
    ) -> dict[str, object]:
        value = {
            "source_commit": identity["source_commit"],
            "source_tree": identity["source_tree"],
            "tag": identity["tag"],
            "release_id": identity["release_id"],
        }
        value["state_sha256"] = runtime._canonical_sha256(
            value, digest_field="state_sha256"
        )
        return value

    def _handoff(
        self, runtime: ModuleType, identity: dict[str, object]
    ) -> dict[str, object]:
        payload = {
            "repository": "vibe-coding-era/goal-teams",
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "authorization_id": "AUTH-V267-S0",
            "authorization_receipt_sha256": "a" * 64,
            "authorization_intent_sha256": "b" * 64,
            "previous_controller_product_version": PREDECESSOR,
            "previous_run_id": "V266-HOST-RUN-0001",
            "nonce": "nonce-v267-controller-handoff-000001",
            "issued_at": "2026-08-26T08:00:00+00:00",
            "expires_at": "2026-08-26T08:10:00+00:00",
            "installed_v266_current_state": self._installed_state(runtime, identity),
            "github_signing_identity": {
                "account": runtime.PINNED_GITHUB_ACCOUNT,
                "key_id": runtime.PINNED_GITHUB_KEY_ID,
                "public_key": runtime.PINNED_GITHUB_PUBLIC_KEY,
                "public_key_fingerprint": runtime.PINNED_GITHUB_FINGERPRINT,
                "ssh_signature_namespace": runtime.HANDOFF_SIGNATURE_NAMESPACE,
            },
        }
        return {
            "schema_version": runtime.HANDOFF_SCHEMA_VERSION,
            "signed_payload": payload,
            "payload_sha256": runtime.object_sha256(payload),
            "ssh_signature": "externally-issued-signature",
        }

    def _write_predecessor_contract(
        self, runtime: ModuleType, root: Path, identity: dict[str, object]
    ) -> None:
        path = root / (
            "references/current/generations/V2.67/contracts/"
            "predecessor-release-identity.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": (
                        "goal-teams-predecessor-release-identity-v2.67"
                    ),
                    "generation_id": TARGET,
                    "predecessor_product_version": PREDECESSOR,
                    "release_identity": identity,
                    "release_identity_sha256": runtime.object_sha256(identity),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def test_runtime_and_schema_bind_installed_v266_to_loaded_v267(self) -> None:
        runtime = self._runtime()
        self.assertEqual(PREDECESSOR, runtime.PREVIOUS_CONTROLLER_PRODUCT_VERSION)
        self.assertEqual(TARGET, runtime.LOADED_RUNTIME_PRODUCT_VERSION)
        self.assertEqual("v2.66", runtime.PREVIOUS_CONTROLLER_RELEASE_TAG)
        self.assertEqual(
            "goal-teams-v2.67-controller-handoff", runtime.HANDOFF_SIGNATURE_NAMESPACE
        )
        self.assertEqual(
            "references/current/generations/V2.67/contracts/"
            "predecessor-release-identity.json",
            runtime.PREDECESSOR_RELEASE_IDENTITY_PATH,
        )
        self.assertIn(
            "scripts/v267/release_identity.py",
            runtime.REQUIRED_STATIC_INPUT_PATHS,
        )
        self.assertIn(
            "scripts/checks/check-v267.py",
            runtime.REQUIRED_STATIC_INPUT_PATHS,
        )
        self.assertNotIn(
            "scripts/checks/check-v250.py",
            runtime.REQUIRED_STATIC_INPUT_PATHS,
        )
        activation = json.loads(
            (
                ROOT
                / "references/current/generations/V2.67/activation-manifest.json"
            ).read_text(encoding="utf-8")
        )
        member_paths = {
            item["path"]
            for rows in activation["root_sets"].values()
            for item in rows
        }
        self.assertTrue(
            set(runtime.REQUIRED_STATIC_INPUT_PATHS).issubset(member_paths),
            sorted(set(runtime.REQUIRED_STATIC_INPUT_PATHS) - member_paths),
        )

        schema_path = ROOT / "schemas/v2.67/runtime-transition-receipt.schema.json"
        self.assertTrue(schema_path.is_file(), "E_TEST_V267_RUNTIME_SCHEMA_MISSING")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        handoff = schema["$defs"]["controllerHandoffReceipt"]
        payload = handoff["properties"]["signed_payload"]
        self.assertEqual(
            {"const": PREDECESSOR},
            payload["properties"]["previous_controller_product_version"],
        )
        self.assertIn("installed_v266_current_state", payload["required"])
        self.assertNotIn("installed_v263_current_state", payload["properties"])
        self.assertEqual(
            {"const": "v2.66"},
            payload["properties"]["installed_v266_current_state"]["properties"][
                "tag"
            ],
        )
        self.assertEqual(
            {"const": TARGET}, schema["properties"]["generation_id"]
        )
        self.assertEqual(
            {"const": TARGET},
            schema["properties"]["loaded_runtime_product_version"],
        )

    def test_exact_published_v266_handoff_passes_signature_boundary(self) -> None:
        runtime = self._runtime()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_predecessor_contract(runtime, root, PUBLISHED_V266_IDENTITY)
            handoff = self._handoff(runtime, PUBLISHED_V266_IDENTITY)
            with mock.patch.object(
                runtime, "_verify_handoff_signature", return_value=True
            ):
                verdict = runtime.validate_controller_handoff(
                    handoff,
                    validation_time=VALIDATION_TIME,
                    root=root,
                )
        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_authorized_local_predecessor_observation_needs_no_ssh_signature(self) -> None:
        runtime = self._runtime()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_predecessor_contract(runtime, root, PUBLISHED_V266_IDENTITY)
            authorization = {
                "authorization_id": "AUTH-V267-LOCAL",
                "intent_sha256": "a" * 64,
            }
            observation = runtime.build_authorized_local_predecessor_observation(
                source_commit="1" * 40,
                source_tree="2" * 40,
                authorization=authorization,
                authorization_receipt_sha256="b" * 64,
                root=root,
                issued_at="2026-08-26T08:00:00+00:00",
            )
            verdict = runtime.validate_controller_handoff(
                observation,
                expected_source_commit="1" * 40,
                expected_source_tree="2" * 40,
                expected_authorization_id=authorization["authorization_id"],
                expected_authorization_receipt_sha256="b" * 64,
                expected_authorization_intent_sha256="a" * 64,
                validation_time=VALIDATION_TIME,
                root=root,
            )
        self.assertTrue(verdict["ok"], verdict["errors"])
        self.assertTrue(verdict["local_observation"])

    def test_resealed_v263_or_tampered_v266_controller_is_rejected(self) -> None:
        runtime = self._runtime()
        for case in ("v263", "release_id", "source_commit", "state_sha256"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_predecessor_contract(runtime, root, PUBLISHED_V266_IDENTITY)
                handoff = self._handoff(runtime, PUBLISHED_V266_IDENTITY)
                payload = handoff["signed_payload"]
                installed = payload["installed_v266_current_state"]
                if case == "v263":
                    payload["previous_controller_product_version"] = "V2.63"
                elif case == "release_id":
                    installed["release_id"] = 1
                    installed["state_sha256"] = runtime._canonical_sha256(
                        installed, digest_field="state_sha256"
                    )
                elif case == "source_commit":
                    installed["source_commit"] = "f" * 40
                    installed["state_sha256"] = runtime._canonical_sha256(
                        installed, digest_field="state_sha256"
                    )
                else:
                    installed["state_sha256"] = "f" * 64
                handoff["payload_sha256"] = runtime.object_sha256(payload)
                with mock.patch.object(
                    runtime, "_verify_handoff_signature", return_value=True
                ):
                    verdict = runtime.validate_controller_handoff(
                        handoff,
                        validation_time=VALIDATION_TIME,
                        root=root,
                    )
            self.assertFalse(verdict["ok"], case)


if __name__ == "__main__":
    unittest.main()
