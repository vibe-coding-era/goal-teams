from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v249 import runtime_host_adapter
from scripts.v249.runtime_transition import _canonical_sha256, object_sha256


SOURCE = "1" * 40
TREE = "2" * 40


def _authorization(path: Path) -> dict:
    intent = {
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.49",
        "action_allowlist": ["fresh_runtime_transition"],
    }
    value = {
        "schema_version": "goal-teams-project-start-authorization-v2.49",
        "receipt_id": "AUTH-V249-HOST",
        "authorization_id": "AUTH-V249-HOST",
        "authorization_state": "granted_once_at_project_start",
        "authorization_lineage_preserved": True,
        "repository": {"name_with_owner": "vibe-coding-era/goal-teams"},
        "version": "V2.49",
        "action_allowlist": ["fresh_runtime_transition"],
        "intent": intent,
        "intent_sha256": _canonical_sha256(intent),
    }
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return value


def _handoff() -> dict:
    payload = {
        "repository": "vibe-coding-era/goal-teams",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "authorization_id": "AUTH-V249-HOST",
        "authorization_receipt_sha256": "a" * 64,
        "authorization_intent_sha256": "b" * 64,
        "previous_controller_product_version": "V2.48",
        "previous_run_id": "V248-HOST-RUN",
        "nonce": "nonce-v249-controller-handoff-000001",
        "issued_at": "2026-08-01T08:00:00+00:00",
        "expires_at": "2026-08-01T08:10:00+00:00",
        "installed_v248_current_state": {
            "state_sha256": "c" * 64,
            "source_commit": "3" * 40,
            "source_tree": "4" * 40,
            "tag": "v2.48",
            "release_id": 362135071,
        },
        "github_signing_identity": {
            "account": runtime_host_adapter.PINNED_GITHUB_ACCOUNT,
            "key_id": runtime_host_adapter.PINNED_GITHUB_KEY_ID,
            "public_key": runtime_host_adapter.PINNED_GITHUB_PUBLIC_KEY,
            "public_key_fingerprint": runtime_host_adapter.PINNED_GITHUB_FINGERPRINT,
            "ssh_signature_namespace": runtime_host_adapter.HANDOFF_SIGNATURE_NAMESPACE,
        },
    }
    return {
        "schema_version": "goal-teams-v2.49-controller-handoff-receipt-v1",
        "signed_payload": payload,
        "payload_sha256": _canonical_sha256(payload),
        "ssh_signature": "signed-externally",
    }


class _FakeProcess:
    def __init__(self, *, ack_drift: str | None = None) -> None:
        self.pid = 4242
        self.returncode = 0
        self.ack_drift = ack_drift
        self.stdin_payload: dict | None = None

    def communicate(self, value: str) -> tuple[str, str]:
        self.stdin_payload = json.loads(value)
        handoff = self.stdin_payload["controller_handoff_receipt"]
        launch = self.stdin_payload["runtime_launch_receipt"]
        runtime_receipt = {"receipt_sha256": "d" * 64}
        ack = {
            "schema_version": "goal-teams-v2.49-runtime-child-ack-v1",
            "acknowledged": True,
            "child_pid": launch["expected_child_pid"],
            "parent_pid": launch["parent_pid"],
            "nonce": launch["nonce"],
            "host_execution_id": launch["host_execution_id"],
            "new_run_id": launch["new_run_id"],
            "controller_handoff_receipt_sha256": object_sha256(handoff),
            "runtime_launch_receipt_sha256": object_sha256(launch),
            "runtime_transition_receipt_sha256": runtime_receipt["receipt_sha256"],
            "runtime_transition_receipt": runtime_receipt,
        }
        if self.ack_drift:
            ack[self.ack_drift] = "drift"
        ack["ack_sha256"] = _canonical_sha256(ack, digest_field="ack_sha256")
        return json.dumps(ack), ""


class TestRuntimeHostAdapter(unittest.TestCase):
    def test_public_api_readback_matches_only_the_pinned_owner_key(self) -> None:
        exact = [
            {
                "id": runtime_host_adapter.PINNED_GITHUB_KEY_ID,
                "key": runtime_host_adapter.PINNED_GITHUB_PUBLIC_KEY,
            }
        ]
        verdict = runtime_host_adapter.validate_github_key_readback(exact)
        self.assertTrue(verdict["ok"], verdict["errors"])
        self.assertEqual(
            runtime_host_adapter.PINNED_GITHUB_FINGERPRINT,
            verdict["public_key_fingerprint"],
        )

        drifted = copy.deepcopy(exact)
        drifted[0]["key"] = "ssh-ed25519 AAAA"
        verdict = runtime_host_adapter.validate_github_key_readback(drifted)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_GITHUB_OWNER_KEY_DRIFT", verdict["errors"])

    def test_popen_child_receives_launch_only_after_actual_pid_and_ack_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path = root / "authorization.json"
            _authorization(authorization_path)
            route_path = root / "route.json"
            route_path.write_text("{}", encoding="utf-8")
            adapter_path = root / "runtime_host_adapter.py"
            adapter_path.write_text("# adapter\n", encoding="utf-8")
            process = _FakeProcess()
            popen_calls: list[tuple[list[str], dict]] = []

            def popen_factory(argv: list[str], **kwargs: object) -> _FakeProcess:
                popen_calls.append((argv, kwargs))
                return process

            with (
                mock.patch.object(
                    runtime_host_adapter,
                    "validate_controller_handoff",
                    return_value={"ok": True, "errors": []},
                ),
                mock.patch.object(
                    runtime_host_adapter,
                    "validate_transition",
                    return_value={"ok": True, "errors": [], "may_enter_s0": True},
                ),
            ):
                receipt = runtime_host_adapter.launch_runtime_transition(
                    stage="released",
                    source_commit=SOURCE,
                    source_tree=TREE,
                    project_size="large",
                    route_receipt_path=route_path,
                    authorization_receipt_path=authorization_path,
                    adapter_identity="github-actions-release-host-adapter",
                    adapter_code_path=adapter_path,
                    controller_handoff_receipt=_handoff(),
                    host_execution_id="987654321",
                    root=root,
                    popen_factory=popen_factory,
                )

        self.assertEqual({"receipt_sha256": "d" * 64}, receipt)
        self.assertEqual(1, len(popen_calls))
        argv, kwargs = popen_calls[0]
        self.assertIn("runtime_transition.py", " ".join(argv))
        self.assertIn("--child", argv)
        self.assertNotIn("--previous-run-id", argv)
        self.assertIs(subprocess.PIPE, kwargs["stdin"])
        self.assertIsNotNone(process.stdin_payload)
        launch = process.stdin_payload["runtime_launch_receipt"]
        self.assertEqual(process.pid, launch["expected_child_pid"])
        self.assertEqual("987654321", launch["host_execution_id"])

    def test_child_ack_pid_or_lineage_drift_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path = root / "authorization.json"
            _authorization(authorization_path)
            route_path = root / "route.json"
            route_path.write_text("{}", encoding="utf-8")
            adapter_path = root / "runtime_host_adapter.py"
            adapter_path.write_text("# adapter\n", encoding="utf-8")
            process = _FakeProcess(ack_drift="child_pid")
            with (
                mock.patch.object(
                    runtime_host_adapter,
                    "validate_controller_handoff",
                    return_value={"ok": True, "errors": []},
                ),
                mock.patch.object(
                    runtime_host_adapter,
                    "validate_transition",
                    return_value={"ok": True, "errors": [], "may_enter_s0": True},
                ),
                self.assertRaisesRegex(ValueError, "E_V249_RUNTIME_CHILD_ACK"),
            ):
                runtime_host_adapter.launch_runtime_transition(
                    stage="released",
                    source_commit=SOURCE,
                    source_tree=TREE,
                    project_size="large",
                    route_receipt_path=route_path,
                    authorization_receipt_path=authorization_path,
                    adapter_identity="github-actions-release-host-adapter",
                    adapter_code_path=adapter_path,
                    controller_handoff_receipt=_handoff(),
                    host_execution_id="987654321",
                    root=root,
                    popen_factory=lambda _argv, **_kwargs: process,
                )


if __name__ == "__main__":
    unittest.main()
