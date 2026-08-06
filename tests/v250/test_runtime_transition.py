from __future__ import annotations

import copy
import datetime as dt
import hashlib
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v250 import runtime_transition
from scripts.v250.runtime_transition import (
    _canonical_sha256,
    observe_transition,
    validate_controller_handoff,
    validate_transition,
)


SOURCE = "1" * 40
TREE = "2" * 40
CAPTURED_AT = "2026-08-01T08:05:00+00:00"
VALIDATION_TIME = dt.datetime(2026, 8, 1, 8, 5, tzinfo=dt.timezone.utc)
ROUTE_ID = "V250-ROUTE-LARGE-RELEASE"
HANDOFF_NONCE = "nonce-v250-controller-handoff-000001"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def _write(root: Path, relative: str, raw: bytes) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _activation_payload_sha256(value: dict) -> str:
    payload = dict(value)
    payload.pop("manifest_payload_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _prepare_observer_inputs(root: Path) -> tuple[Path, Path, Path]:
    bootstrap_paths = {
        ".agents/skills/goal-teams/SKILL.md": b"wrapper\n",
        "AGENTS.md": b"agents\n",
        "RULES.md": b"rules\n",
        "SKILL.md": b"skill\n",
    }
    current_paths = {
        "references/current/generations/V2.51/core.md": b"core\n",
        "references/current/generations/V2.51/prompt-manifest.json": b"",
        "references/profiles/goal-teams-self-release-v2.51.md": b"profile\n",
        "references/release-profiles/v2.51.json": b"{}\n",
        "references/current/generations/V2.51/contracts/release-route-manifest.json": b"{}\n",
        "references/current/generations/V2.51/contracts/release-command-manifest.json": b"{}\n",
    }
    execution_paths = {
        "scripts/checks/check-v250.py": b"checker\n",
        "scripts/v250/runtime_host_adapter.py": b"host-adapter\n",
        "scripts/v250/runtime_transition.py": b"observer\n",
    }
    schema_paths = {
        "schemas/v2.50/runtime-transition-receipt.schema.json": (
            runtime_transition.ROOT
            / "schemas/v2.50/runtime-transition-receipt.schema.json"
        ).read_bytes(),
    }
    prompt = {
        "schema_version": "goal-teams-prompt-manifest-v2.50",
        "generation_id": "V2.51",
        "manifest_state": "active_current",
        "routes": {
            ROUTE_ID: {
                "workflow_phase": "release",
                "ordered_refs": ["references/current/generations/V2.51/core.md"],
            }
        },
    }
    current_paths[
        "references/current/generations/V2.51/prompt-manifest.json"
    ] = _json_bytes(prompt)

    entries: dict[str, list[dict[str, object]]] = {
        "bootstrap": [],
        "current": [],
        "execution": [],
        "schemas_and_validators": [],
    }
    for root_set, paths in (
        ("bootstrap", bootstrap_paths),
        ("current", current_paths),
        ("execution", execution_paths),
        ("schemas_and_validators", schema_paths),
    ):
        for relative, raw in paths.items():
            digest = _write(root, relative, raw)
            entries[root_set].append(
                {"path": relative, "sha256": digest, "bytes": len(raw)}
            )

    activation = {
        "schema_version": "goal-teams-activation-manifest-v2.50",
        "generation_id": "V2.51",
        "generation_state": "active",
        "identity": {
            "loaded_runtime_product_version": "V2.51",
            "route_contract_schema_version": "goal-teams-project-route-v2.50",
            "target_policy_generation": "V2.51",
        },
        "root_sets": entries,
        "prompt_manifest_path": "references/current/generations/V2.51/prompt-manifest.json",
    }
    activation["manifest_payload_sha256"] = _activation_payload_sha256(activation)
    activation_path = "references/current/generations/V2.51/activation-manifest.json"
    activation_raw = _json_bytes(activation)
    activation_digest = _write(root, activation_path, activation_raw)
    active = {
        "schema_version": "goal-teams-active-generation-v1",
        "generation_id": "V2.51",
        "activation_manifest": activation_path,
        "activation_manifest_sha256": activation_digest,
        "state": "active_current",
    }
    _write(root, "references/current/ACTIVE.json", _json_bytes(active))

    route = {
        "generation_id": "V2.51",
        "route_id": ROUTE_ID,
        "loaded_paths": ["references/current/generations/V2.51/core.md"],
        "path_digests": {
            "references/current/generations/V2.51/core.md": hashlib.sha256(
                b"core\n"
            ).hexdigest()
        },
        "legacy_intersection": [],
    }
    route["closure_digest"] = _canonical_sha256(route, digest_field="closure_digest")
    route_path = root / "docs/route-receipt.json"
    route_path.parent.mkdir(parents=True)
    route_path.write_bytes(_json_bytes(route))

    intent = {
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.51",
        "action_allowlist": ["fresh_runtime_transition"],
    }
    authorization = {
        "schema_version": "goal-teams-project-start-authorization-v2.50",
        "receipt_id": "AUTH-V250-TEST",
        "authorization_id": "AUTH-V250-TEST",
        "authorization_state": "granted_once_at_project_start",
        "authorization_lineage_preserved": True,
        "repository": {"name_with_owner": "vibe-coding-era/goal-teams"},
        "version": "V2.51",
        "action_allowlist": ["fresh_runtime_transition"],
        "intent": intent,
        "intent_sha256": _canonical_sha256(intent),
    }
    authorization_path = root / "docs/authorization-receipt.json"
    authorization_path.write_bytes(_json_bytes(authorization))

    adapter_path = root / "docs/trusted-runtime-adapter.py"
    adapter_path.write_bytes(b"# trusted host adapter\n")
    return route_path, authorization_path, adapter_path


def _handoff(authorization_path: Path) -> dict:
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    signed_payload = {
        "repository": "vibe-coding-era/goal-teams",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "authorization_id": authorization["authorization_id"],
        "authorization_receipt_sha256": hashlib.sha256(
            authorization_path.read_bytes()
        ).hexdigest(),
        "authorization_intent_sha256": authorization["intent_sha256"],
        "previous_controller_product_version": "V2.50",
        "previous_run_id": "V248-HOST-RUN-0001",
        "nonce": HANDOFF_NONCE,
        "issued_at": "2026-08-01T08:00:00+00:00",
        "expires_at": "2026-08-01T08:10:00+00:00",
        "installed_v250_current_state": {
            "state_sha256": "3" * 64,
            "source_commit": "4" * 40,
            "source_tree": "5" * 40,
            "tag": "v2.50",
            "release_id": 362135071,
        },
        "github_signing_identity": {
            "account": "vibe-coding-era",
            "key_id": 152596014,
            "public_key": (
                "ssh-ed25519 "
                "AAAAC3NzaC1lZDI1NTE5AAAAIJ7qqfn52U2nhALTYS8ofXEwJwIq6GispivX9W/NG2Ot"
            ),
            "public_key_fingerprint": (
                "SHA256:fEM2bYLJFOSvNA78soiWLvrSUaWxANVr1HIVl6AAirE"
            ),
            "ssh_signature_namespace": "goal-teams-v2.51-controller-handoff",
        },
    }
    return {
        "schema_version": "goal-teams-v2.51-controller-handoff-receipt-v1",
        "signed_payload": signed_payload,
        "payload_sha256": _canonical_sha256(signed_payload),
        "ssh_signature": (
            "-----BEGIN SSH SIGNATURE-----\n"
            "Zm9yZ2VkLXRlc3Qtc2lnbmF0dXJl\n"
            "-----END SSH SIGNATURE-----\n"
        ),
    }


def _launch(handoff: dict, adapter_path: Path) -> dict:
    value = {
        "schema_version": "goal-teams-v2.51-runtime-launch-receipt-v1",
        "controller_handoff_receipt_sha256": runtime_transition.object_sha256(handoff),
        "controller_handoff_payload_sha256": handoff["payload_sha256"],
        "nonce": HANDOFF_NONCE,
        "parent_pid": os.getppid(),
        "expected_child_pid": os.getpid(),
        "host_execution_id": "GITHUB-RUN-10001",
        "new_run_id": "V250-RUNTIME-RUN-0001",
        "launched_at": CAPTURED_AT,
        "adapter_identity": "codex-host-runtime-adapter",
        "adapter_code_sha256": hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
    }
    value["receipt_sha256"] = _canonical_sha256(value)
    return value


def _observe(root: Path) -> dict:
    route_path, authorization_path, adapter_path = _prepare_observer_inputs(root)
    handoff = _handoff(authorization_path)
    launch = _launch(handoff, adapter_path)
    with mock.patch.object(
        runtime_transition, "_verify_handoff_signature", return_value=True
    ):
        return observe_transition(
            stage="released",
            source_commit=SOURCE,
            source_tree=TREE,
            project_size="large",
            route_receipt_path=route_path,
            authorization_receipt_path=authorization_path,
            adapter_identity="codex-host-runtime-adapter",
            adapter_code_path=adapter_path,
            controller_handoff_receipt=handoff,
            runtime_launch_receipt=launch,
            captured_at=CAPTURED_AT,
            transition_id="TRANSITION-1",
            validation_time=VALIDATION_TIME,
            root=root,
        )


class TestV250RuntimeTransition(unittest.TestCase):
    def _validate(self, value: dict, root: Path, **overrides: object) -> dict:
        kwargs = {
            "expected_stage": "released",
            "allow_release": True,
            "expected_source_commit": SOURCE,
            "expected_source_tree": TREE,
            "expected_project_size": "large",
            "validation_time": VALIDATION_TIME,
            "root": root,
        }
        kwargs.update(overrides)
        with mock.patch.object(
            runtime_transition, "_verify_handoff_signature", return_value=True
        ):
            return validate_transition(value, **kwargs)

    def test_released_receipt_binds_signed_handoff_launch_and_current_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            verdict = self._validate(value, root)

        self.assertTrue(verdict["ok"], verdict["errors"])
        self.assertTrue(verdict["may_enter_s0"])
        self.assertEqual(
            "V2.50",
            value["controller_handoff_receipt"]["signed_payload"][
                "previous_controller_product_version"
            ],
        )
        self.assertEqual(
            "V250-RUNTIME-RUN-0001", value["runtime_launch_receipt"]["new_run_id"]
        )
        self.assertEqual("V2.51", value["loaded_runtime_product_version"])
        self.assertEqual("host_adapter_popen_child", value["fresh_process_kind"])
        self.assertNotIn("previous_run_id", value)
        self.assertNotIn("new_run_id", value)
        self.assertNotIn("previous_controller_product_version", value)
        self.assertIn("AGENTS.md", value["loaded_paths"])
        self.assertIn(
            "schemas/v2.50/runtime-transition-receipt.schema.json",
            value["loaded_paths"],
        )
        self.assertFalse(verdict["external_independence_proven"])

    def test_downloaded_receipts_can_override_expired_runner_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            route_raw = (root / "docs/route-receipt.json").read_bytes()
            authorization_raw = (
                root / "docs/authorization-receipt.json"
            ).read_bytes()
            portable_route = root / "downloaded/release-route-receipt.json"
            portable_authorization = root / "downloaded/authorization.json"
            portable_route.parent.mkdir(parents=True)
            portable_route.write_bytes(route_raw)
            portable_authorization.write_bytes(authorization_raw)
            value["route_receipt_path"] = "/expired-runner/route-receipt.json"
            value["authorization_receipt_path"] = (
                "/expired-runner/authorization.json"
            )
            value["receipt_sha256"] = _canonical_sha256(value)

            stale = self._validate(value, root)
            portable = self._validate(
                value,
                root,
                route_receipt_path_override=portable_route,
                authorization_receipt_path_override=portable_authorization,
            )

        self.assertFalse(stale["ok"])
        self.assertIn(
            "E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT_DIGEST", stale["errors"]
        )
        self.assertIn(
            "E_V250_RUNTIME_TRANSITION_AUTHORIZATION_RECEIPT_DIGEST",
            stale["errors"],
        )
        self.assertTrue(portable["ok"], portable["errors"])

    def test_forged_signature_is_rejected_by_fixed_owner_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, authorization_path, _ = _prepare_observer_inputs(root)
            handoff = _handoff(authorization_path)
            verdict = validate_controller_handoff(
                handoff,
                expected_repository="vibe-coding-era/goal-teams",
                expected_source_commit=SOURCE,
                expected_source_tree=TREE,
                expected_authorization_id="AUTH-V250-TEST",
                expected_authorization_receipt_sha256=hashlib.sha256(
                    authorization_path.read_bytes()
                ).hexdigest(),
                expected_authorization_intent_sha256=json.loads(
                    authorization_path.read_text(encoding="utf-8")
                )["intent_sha256"],
                validation_time=VALIDATION_TIME,
            )

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_CONTROLLER_HANDOFF_SIGNATURE", verdict["errors"])

    def test_missing_handoff_or_launch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            for field, error in (
                ("controller_handoff_receipt", "E_V250_CONTROLLER_HANDOFF_REQUIRED"),
                ("runtime_launch_receipt", "E_V250_RUNTIME_LAUNCH_REQUIRED"),
            ):
                drifted = copy.deepcopy(value)
                drifted.pop(field)
                drifted["receipt_sha256"] = _canonical_sha256(drifted)
                verdict = self._validate(drifted, root)
                self.assertFalse(verdict["ok"])
                self.assertIn(error, verdict["errors"])

    def test_nonce_pid_parent_host_execution_and_run_drift_fail_closed(self) -> None:
        drift_cases = (
            ("nonce", "different-nonce-controller-handoff"),
            ("parent_pid", 999999),
            ("expected_child_pid", 999998),
            ("host_execution_id", "GITHUB-RUN-DRIFT"),
            ("new_run_id", "V248-HOST-RUN-0001"),
        )
        for field, replacement in drift_cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                value = _observe(root)
                value["runtime_launch_receipt"][field] = replacement
                value["runtime_launch_receipt"]["receipt_sha256"] = _canonical_sha256(
                    value["runtime_launch_receipt"]
                )
                value["runtime_launch_receipt_sha256"] = runtime_transition.object_sha256(
                    value["runtime_launch_receipt"]
                )
                value["receipt_sha256"] = _canonical_sha256(value)
                verdict = self._validate(value, root)
                self.assertFalse(verdict["ok"])
                self.assertIn("E_V250_RUNTIME_LAUNCH_LINEAGE", verdict["errors"])

    def test_expired_or_identity_drifted_handoff_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            payload = value["controller_handoff_receipt"]["signed_payload"]
            payload["expires_at"] = "2026-08-01T08:04:59+00:00"
            value["controller_handoff_receipt"]["payload_sha256"] = _canonical_sha256(
                payload
            )
            value["controller_handoff_receipt_sha256"] = runtime_transition.object_sha256(
                value["controller_handoff_receipt"]
            )
            value["receipt_sha256"] = _canonical_sha256(value)
            verdict = self._validate(value, root)

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_CONTROLLER_HANDOFF_EXPIRED", verdict["errors"])

    def test_self_consistent_host_execution_reseal_fails_external_expectation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            value["runtime_launch_receipt"]["host_execution_id"] = "GITHUB-RUN-DRIFT"
            value["runtime_launch_receipt"]["receipt_sha256"] = _canonical_sha256(
                value["runtime_launch_receipt"]
            )
            value["runtime_launch_receipt_sha256"] = runtime_transition.object_sha256(
                value["runtime_launch_receipt"]
            )
            value["host_execution_id"] = "GITHUB-RUN-DRIFT"
            value["receipt_sha256"] = _canonical_sha256(value)
            verdict = self._validate(
                value,
                root,
                expected_host_execution_id="GITHUB-RUN-10001",
            )

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_RUNTIME_LAUNCH_LINEAGE", verdict["errors"])

    def test_handoff_source_authorization_installed_state_and_signer_drift_fail(self) -> None:
        cases = (
            (
                lambda payload: payload.__setitem__("source_commit", "f" * 40),
                "E_V250_CONTROLLER_HANDOFF_IDENTITY_DRIFT",
            ),
            (
                lambda payload: payload.__setitem__("authorization_id", "AUTH-DRIFT"),
                "E_V250_CONTROLLER_HANDOFF_AUTHORIZATION_DRIFT",
            ),
            (
                lambda payload: payload["installed_v250_current_state"].__setitem__(
                    "tag", "v2.47"
                ),
                "E_V250_CONTROLLER_HANDOFF_INSTALLED_STATE",
            ),
            (
                lambda payload: payload["github_signing_identity"].__setitem__(
                    "key_id", 1
                ),
                "E_V250_CONTROLLER_HANDOFF_SIGNER_DRIFT",
            ),
        )
        for mutate, expected_error in cases:
            with self.subTest(error=expected_error), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                value = _observe(root)
                handoff = value["controller_handoff_receipt"]
                mutate(handoff["signed_payload"])
                handoff["payload_sha256"] = _canonical_sha256(
                    handoff["signed_payload"]
                )
                value["controller_handoff_receipt_sha256"] = (
                    runtime_transition.object_sha256(handoff)
                )
                launch = value["runtime_launch_receipt"]
                launch["controller_handoff_receipt_sha256"] = (
                    runtime_transition.object_sha256(handoff)
                )
                launch["controller_handoff_payload_sha256"] = handoff[
                    "payload_sha256"
                ]
                launch["receipt_sha256"] = _canonical_sha256(launch)
                value["runtime_launch_receipt_sha256"] = (
                    runtime_transition.object_sha256(launch)
                )
                value["receipt_sha256"] = _canonical_sha256(value)
                verdict = self._validate(value, root)
                self.assertFalse(verdict["ok"])
                self.assertIn(expected_error, verdict["errors"])

    def test_raw_lineage_parameters_and_fields_are_forbidden(self) -> None:
        parameters = inspect.signature(observe_transition).parameters
        for forbidden in (
            "previous_controller_product_version",
            "loaded_runtime_product_version",
            "previous_run_id",
            "new_run_id",
        ):
            self.assertNotIn(forbidden, parameters)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            value["previous_run_id"] = "RAW-INJECTED"
            value["receipt_sha256"] = _canonical_sha256(value)
            verdict = self._validate(value, root)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_RUNTIME_TRANSITION_RAW_LINEAGE", verdict["errors"])

    def test_unknown_top_level_field_cannot_be_resealed_into_s0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            value["raw_untrusted_claim"] = {
                "external_independent": True,
                "child_ack_verified": True,
            }
            value["receipt_sha256"] = _canonical_sha256(value)
            verdict = self._validate(value, root)

        self.assertFalse(verdict["ok"])
        self.assertFalse(verdict["may_enter_s0"])
        self.assertIn(
            "E_V250_RUNTIME_TRANSITION_SCHEMA_FIELDS", verdict["errors"]
        )

    def test_schema_self_expansion_cannot_reseal_an_unknown_field_into_s0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            schema_path = (
                root / "schemas/v2.50/runtime-transition-receipt.schema.json"
            )
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["required"].append("raw_untrusted_claim")
            schema["properties"]["raw_untrusted_claim"] = {"type": "object"}
            schema_path.write_bytes(_json_bytes(schema))
            value["raw_untrusted_claim"] = {
                "external_independent": True,
                "child_ack_verified": True,
            }
            value["receipt_sha256"] = _canonical_sha256(value)
            verdict = self._validate(value, root)

        self.assertFalse(verdict["ok"])
        self.assertFalse(verdict["may_enter_s0"])
        self.assertIn(
            "E_V250_RUNTIME_TRANSITION_MEMBER_DIGEST:"
            "schemas/v2.50/runtime-transition-receipt.schema.json",
            verdict["errors"],
        )

    def test_current_route_and_adapter_drift_still_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            (root / "references/current/generations/V2.51/core.md").write_text(
                "drift\n", encoding="utf-8"
            )
            verdict = self._validate(value, root)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_RUNTIME_TRANSITION_CURRENT_DIGEST", verdict["errors"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = _observe(root)
            adapter = Path(value["adapter_code_path"])
            if not adapter.is_absolute():
                adapter = root / adapter
            adapter.write_bytes(adapter.read_bytes() + b"drift\n")
            verdict = self._validate(value, root)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_RUNTIME_TRANSITION_ADAPTER_CODE_DIGEST", verdict["errors"])


if __name__ == "__main__":
    unittest.main()
