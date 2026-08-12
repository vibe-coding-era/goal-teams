from __future__ import annotations

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v250 import runtime_transition
from scripts.v250.runtime_transition import _canonical_sha256


SCHEMA_PATH = Path(__file__).resolve().parents[2] / (
    "schemas/v2.50/runtime-transition-receipt.schema.json"
)
VALIDATION_TIME = dt.datetime(2026, 8, 12, 8, 5, tzinfo=dt.timezone.utc)
PUBLISHED_V262_IDENTITY = {
    "tag": "v2.62",
    "release_id": 367112913,
    "state": "published",
    "source_commit": "bd4eedfc0623e74b74efeaf157edf92ce2be1e74",
    "source_tree": "58d11881eeda2f0a018fcc4273ce2f3982977f94",
    "public_assets": [
        "goal-teams-V2.62.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    ],
}


def _installed_state(identity: dict[str, object]) -> dict[str, object]:
    value: dict[str, object] = {
        "source_commit": identity["source_commit"],
        "source_tree": identity["source_tree"],
        "tag": identity["tag"],
        "release_id": identity["release_id"],
    }
    value["state_sha256"] = _canonical_sha256(
        value, digest_field="state_sha256"
    )
    return value


def _handoff(identity: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {
        "repository": "vibe-coding-era/goal-teams",
        "source_commit": "1" * 40,
        "source_tree": "2" * 40,
        "authorization_id": "AUTH-V263-S0",
        "authorization_receipt_sha256": "a" * 64,
        "authorization_intent_sha256": "b" * 64,
        "previous_controller_product_version": "V2.62",
        "previous_run_id": "V262-HOST-RUN-0001",
        "nonce": "nonce-v263-controller-handoff-000001",
        "issued_at": "2026-08-12T08:00:00+00:00",
        "expires_at": "2026-08-12T08:10:00+00:00",
        "installed_v262_current_state": _installed_state(identity),
        "github_signing_identity": {
            "account": runtime_transition.PINNED_GITHUB_ACCOUNT,
            "key_id": runtime_transition.PINNED_GITHUB_KEY_ID,
            "public_key": runtime_transition.PINNED_GITHUB_PUBLIC_KEY,
            "public_key_fingerprint": runtime_transition.PINNED_GITHUB_FINGERPRINT,
            "ssh_signature_namespace": runtime_transition.HANDOFF_SIGNATURE_NAMESPACE,
        },
    }
    return {
        "schema_version": runtime_transition.HANDOFF_SCHEMA_VERSION,
        "signed_payload": payload,
        "payload_sha256": runtime_transition.object_sha256(payload),
        "ssh_signature": "externally-issued-signature",
    }


def _write_predecessor_contract(root: Path, identity: dict[str, object]) -> None:
    path = root / (
        "references/current/generations/V2.63/contracts/"
        "predecessor-release-identity.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "goal-teams-predecessor-release-identity-v2.63",
                "generation_id": "V2.63",
                "predecessor_product_version": "V2.62",
                "release_identity": identity,
                "release_identity_sha256": runtime_transition.object_sha256(identity),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


class TestV263S0ControllerIdentity(unittest.TestCase):
    def test_schema_names_the_exact_v262_controller_without_pinning_mutable_ids(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        payload = schema["$defs"]["controllerHandoffReceipt"]["properties"][
            "signed_payload"
        ]
        properties = payload["properties"]

        self.assertEqual(
            {"const": "V2.62"},
            properties["previous_controller_product_version"],
        )
        self.assertIn("installed_v262_current_state", payload["required"])
        self.assertNotIn("installed_v26_current_state", properties)
        installed = properties["installed_v262_current_state"]["properties"]
        self.assertEqual({"const": "v2.62"}, installed["tag"])
        self.assertNotIn("const", installed["release_id"])
        self.assertNotIn("const", installed["source_commit"])
        self.assertNotIn("const", installed["source_tree"])
        self.assertEqual("V2.62", runtime_transition.PREVIOUS_CONTROLLER_PRODUCT_VERSION)
        self.assertEqual("V2.63", runtime_transition.LOADED_RUNTIME_PRODUCT_VERSION)

    def test_handoff_matches_published_v262_identity_and_canonical_state_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_predecessor_contract(root, PUBLISHED_V262_IDENTITY)
            handoff = _handoff(PUBLISHED_V262_IDENTITY)
            with mock.patch.object(
                runtime_transition, "_verify_handoff_signature", return_value=True
            ):
                verdict = runtime_transition.validate_controller_handoff(
                    handoff,
                    validation_time=VALIDATION_TIME,
                    root=root,
                )

        self.assertTrue(verdict["ok"], verdict["errors"])

    def test_self_consistent_noncanonical_or_unpublished_controller_is_rejected(self) -> None:
        cases = ("release_id", "source_commit", "state_sha256", "published_state")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                published = copy.deepcopy(PUBLISHED_V262_IDENTITY)
                _write_predecessor_contract(root, published)
                handoff = _handoff(published)
                installed = handoff["signed_payload"]["installed_v262_current_state"]
                if case == "release_id":
                    installed["release_id"] = 1
                    installed["state_sha256"] = _canonical_sha256(
                        installed, digest_field="state_sha256"
                    )
                elif case == "source_commit":
                    installed["source_commit"] = "f" * 40
                    installed["state_sha256"] = _canonical_sha256(
                        installed, digest_field="state_sha256"
                    )
                elif case == "state_sha256":
                    installed["state_sha256"] = "f" * 64
                else:
                    published["state"] = "draft"
                    _write_predecessor_contract(root, published)
                payload = handoff["signed_payload"]
                handoff["payload_sha256"] = runtime_transition.object_sha256(payload)
                with mock.patch.object(
                    runtime_transition, "_verify_handoff_signature", return_value=True
                ):
                    verdict = runtime_transition.validate_controller_handoff(
                        handoff,
                        validation_time=VALIDATION_TIME,
                        root=root,
                    )

            self.assertFalse(verdict["ok"])
            self.assertIn(
                "E_V250_CONTROLLER_HANDOFF_INSTALLED_STATE", verdict["errors"]
            )


if __name__ == "__main__":
    unittest.main()
