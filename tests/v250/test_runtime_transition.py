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
from scripts.v250.route_closure import compile_derived_route_closure
from scripts.v250.route_derivation import derive_route


SOURCE = "1" * 40
TREE = "2" * 40
CAPTURED_AT = "2026-08-01T08:05:00+00:00"
VALIDATION_TIME = dt.datetime(2026, 8, 1, 8, 5, tzinfo=dt.timezone.utc)
ROUTE_ID = "V250-ROUTE-LARGE-RELEASE"
HANDOFF_NONCE = "nonce-v250-controller-handoff-000001"
PUBLISHED_V262_IDENTITY = {
    "tag": "v2.63",
    "release_id": 369846737,
    "state": "published",
    "source_commit": "8e246e4b7bb7c44bd6aa514eb273590d925b32b0",
    "source_tree": "33c0af795a549ec6121919a18f42a04a797463a2",
    "public_assets": [
        "goal-teams-V2.63.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    ],
}


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


def _prepare_observer_inputs(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    bootstrap_paths = {
        ".agents/skills/goal-teams/SKILL.md": b"wrapper\n",
        "AGENTS.md": b"agents\n",
        "RULES.md": b"rules\n",
        "SKILL.md": b"skill\n",
    }
    core_path = "references/current/generations/V2.65/core.md"
    core_raw = b"core\n"
    facts_source = {
        "schema_version": "goal-teams-project-route-facts-source-v2.65",
        "repository": "vibe-coding-era/goal-teams",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "workflow_run_id": "10001",
        "workflow_run_attempt": "1",
        "project_start_authorization_receipt_sha256": "3" * 64,
    }
    project_route_facts = {
        "project_size": "large",
        "workflow_phase": "release",
        "stage": "released",
        "release_intent": True,
        "implementation_scope_complete": True,
        "risk": "high",
        "failure_consequence": "high",
        "reversibility": "partially_reversible",
        "compliance": "none",
        "external_write": True,
        "security_sensitive": True,
        "ui_or_desktop": False,
        "agent_runtime": True,
        "environment_check_required": True,
        "authorization_state": "granted",
        "facts_source_sha256": _canonical_sha256(facts_source),
    }
    derived_route = derive_route(project_route_facts)
    owner = {
        "owner_id": "core",
        "path": core_path,
        "source_sha256": hashlib.sha256(core_raw).hexdigest(),
        "owned_rule_ids": ["GT263-RUNTIME-TEST"],
        "route_membership": [ROUTE_ID],
        "dependencies": [],
    }
    rule_manifest = {"owners": [owner]}
    rule_manifest_path = (
        "references/current/generations/V2.65/rule-manifest.json"
    )
    current_paths = {
        core_path: core_raw,
        rule_manifest_path: _json_bytes(rule_manifest),
        "references/current/generations/V2.65/prompt-manifest.json": b"",
        "references/profiles/goal-teams-self-release-v2.65.md": b"profile\n",
        "references/release-profiles/v2.65.json": b"{}\n",
        "references/current/generations/V2.65/contracts/release-route-manifest.json": b"{}\n",
        "references/current/generations/V2.65/contracts/release-command-manifest.json": b"{}\n",
        "references/current/generations/V2.65/contracts/predecessor-release-identity.json": _json_bytes(
            {
                "schema_version": "goal-teams-predecessor-release-identity-v2.65",
                "generation_id": "V2.65",
                "predecessor_product_version": "V2.63",
                "release_identity": PUBLISHED_V262_IDENTITY,
                "release_identity_sha256": hashlib.sha256(
                    json.dumps(
                        PUBLISHED_V262_IDENTITY,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
        ),
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
        "generation_id": "V2.65",
        "manifest_state": "active_current",
        "routes": {
            ROUTE_ID: {
                "workflow_phase": "release",
                "ordered_refs": [core_path],
                "required_gates": derived_route["required_gates"],
                "conditional_gates": derived_route["conditional_gates"],
                "expected_loaded_rule_bytes": len(core_raw),
                "max_loaded_rule_bytes": len(core_raw),
            }
        },
    }
    current_paths[
        "references/current/generations/V2.65/prompt-manifest.json"
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

    # Mutable published projection remains available to prove it is not part
    # of the V2.65 runtime or predecessor-controller identity closure.
    _write(
        root,
        "release/current/manifest.json",
        _json_bytes(
            {
                "schema_version": "goal-teams-release-manifest-v2.63",
                "product_version": "V2.63",
                "release_identity": PUBLISHED_V262_IDENTITY,
                "status": "release",
            }
        ),
    )

    activation = {
        "schema_version": "goal-teams-activation-manifest-v2.50",
        "generation_id": "V2.65",
        "generation_state": "active",
        "identity": {
            "loaded_runtime_product_version": "V2.65",
            "route_contract_schema_version": "goal-teams-project-route-v2.50",
            "target_policy_generation": "V2.65",
        },
        "root_sets": entries,
        "rule_manifest_path": rule_manifest_path,
        "prompt_manifest_path": "references/current/generations/V2.65/prompt-manifest.json",
        "current_default_allowlist": [core_path],
        "legacy_classification": {"exact_paths": [], "path_prefixes": []},
        "budgets": {"max_route_rule_bytes": len(core_raw)},
    }
    activation["manifest_payload_sha256"] = _activation_payload_sha256(activation)
    activation_path = "references/current/generations/V2.65/activation-manifest.json"
    activation_raw = _json_bytes(activation)
    activation_digest = _write(root, activation_path, activation_raw)
    active = {
        "schema_version": "goal-teams-active-generation-v1",
        "generation_id": "V2.65",
        "activation_manifest": activation_path,
        "activation_manifest_sha256": activation_digest,
        "state": "active_current",
    }
    _write(root, "references/current/ACTIVE.json", _json_bytes(active))

    generation = {
        "generation_id": "V2.65",
        "activation_digest_verified": True,
        "member_digests_verified": True,
        "activation_manifest": activation,
        "prompt_manifest": prompt,
        "rule_manifest": rule_manifest,
        "current_default_allowlist": [core_path],
        "legacy_exact_paths": [],
        "legacy_path_prefixes": [],
    }
    route = compile_derived_route_closure(root, generation, derived_route)
    route_facts_path = root / "docs/release-route-facts.json"
    derived_route_path = root / "docs/release-route-derived.json"
    route_path = root / "docs/release-route-receipt.json"
    route_path.parent.mkdir(parents=True)
    route_facts_path.write_bytes(
        json.dumps(
            {
                "facts_source": facts_source,
                "project_route_facts": project_route_facts,
                "project_route_facts_sha256": _canonical_sha256(
                    project_route_facts
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    derived_route_path.write_bytes(
        json.dumps(
            derived_route,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    route_path.write_bytes(
        json.dumps(
            route,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )

    intent = {
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.65",
        "action_allowlist": ["fresh_runtime_transition"],
    }
    authorization = {
        "schema_version": "goal-teams-project-start-authorization-v2.50",
        "receipt_id": "AUTH-V250-TEST",
        "authorization_id": "AUTH-V250-TEST",
        "authorization_state": "granted_once_at_project_start",
        "authorization_lineage_preserved": True,
        "repository": {"name_with_owner": "vibe-coding-era/goal-teams"},
        "version": "V2.65",
        "action_allowlist": ["fresh_runtime_transition"],
        "intent": intent,
        "intent_sha256": _canonical_sha256(intent),
    }
    authorization_path = root / "docs/authorization-receipt.json"
    authorization_path.write_bytes(_json_bytes(authorization))

    adapter_path = root / "docs/trusted-runtime-adapter.py"
    adapter_path.write_bytes(b"# trusted host adapter\n")
    return (
        route_facts_path,
        derived_route_path,
        route_path,
        authorization_path,
        adapter_path,
    )


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
        "previous_controller_product_version": "V2.63",
        "previous_run_id": "V251-HOST-RUN-0001",
        "nonce": HANDOFF_NONCE,
        "issued_at": "2026-08-01T08:00:00+00:00",
        "expires_at": "2026-08-01T08:10:00+00:00",
        "installed_v263_current_state": {
            "source_commit": PUBLISHED_V262_IDENTITY["source_commit"],
            "source_tree": PUBLISHED_V262_IDENTITY["source_tree"],
            "tag": PUBLISHED_V262_IDENTITY["tag"],
            "release_id": PUBLISHED_V262_IDENTITY["release_id"],
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
            "ssh_signature_namespace": "goal-teams-v2.65-controller-handoff",
        },
    }
    installed = signed_payload["installed_v263_current_state"]
    installed["state_sha256"] = _canonical_sha256(
        installed, digest_field="state_sha256"
    )
    return {
        "schema_version": "goal-teams-v2.65-controller-handoff-receipt-v1",
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
        "schema_version": "goal-teams-v2.65-runtime-launch-receipt-v1",
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
    (
        route_facts_path,
        derived_route_path,
        route_path,
        authorization_path,
        adapter_path,
    ) = _prepare_observer_inputs(root)
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
            route_facts_receipt_path=route_facts_path,
            derived_route_receipt_path=derived_route_path,
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
            "V2.63",
            value["controller_handoff_receipt"]["signed_payload"][
                "previous_controller_product_version"
            ],
        )
        self.assertEqual(
            "V250-RUNTIME-RUN-0001", value["runtime_launch_receipt"]["new_run_id"]
        )
        self.assertEqual("V2.65", value["loaded_runtime_product_version"])
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
            facts_raw = (root / "docs/release-route-facts.json").read_bytes()
            derived_raw = (root / "docs/release-route-derived.json").read_bytes()
            route_raw = (root / "docs/release-route-receipt.json").read_bytes()
            authorization_raw = (
                root / "docs/authorization-receipt.json"
            ).read_bytes()
            portable_facts = root / "downloaded/release-route-facts.json"
            portable_derived = root / "downloaded/release-route-derived.json"
            portable_route = root / "downloaded/release-route-receipt.json"
            portable_authorization = root / "downloaded/authorization.json"
            portable_route.parent.mkdir(parents=True)
            portable_facts.write_bytes(facts_raw)
            portable_derived.write_bytes(derived_raw)
            portable_route.write_bytes(route_raw)
            portable_authorization.write_bytes(authorization_raw)
            value["route_facts_receipt_path"] = (
                "/expired-runner/release-route-facts.json"
            )
            value["derived_route_receipt_path"] = (
                "/expired-runner/release-route-derived.json"
            )
            value["route_receipt_path"] = "/expired-runner/route-receipt.json"
            value["authorization_receipt_path"] = (
                "/expired-runner/authorization.json"
            )
            value["receipt_sha256"] = _canonical_sha256(value)

            stale = self._validate(value, root)
            portable = self._validate(
                value,
                root,
                route_facts_receipt_path_override=portable_facts,
                derived_route_receipt_path_override=portable_derived,
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
            _, _, _, authorization_path, _ = _prepare_observer_inputs(root)
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
                root=root,
            )

        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_CONTROLLER_HANDOFF_SIGNATURE", verdict["errors"])

    def test_handoff_identity_ignores_mutable_release_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, authorization_path, _ = _prepare_observer_inputs(root)
            handoff = _handoff(authorization_path)
            projection = root / "release/current/manifest.json"
            projection.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(
                runtime_transition, "_verify_handoff_signature", return_value=True
            ):
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
                    root=root,
                )
        self.assertTrue(verdict["ok"], verdict["errors"])

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
            ("new_run_id", "V251-HOST-RUN-0001"),
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
                lambda payload: payload.__setitem__(
                    "previous_controller_product_version", "V2.65"
                ),
                "E_V250_CONTROLLER_HANDOFF_VERSION",
            ),
            (
                lambda payload: payload.__setitem__("source_commit", "f" * 40),
                "E_V250_CONTROLLER_HANDOFF_IDENTITY_DRIFT",
            ),
            (
                lambda payload: payload.__setitem__("authorization_id", "AUTH-DRIFT"),
                "E_V250_CONTROLLER_HANDOFF_AUTHORIZATION_DRIFT",
            ),
            (
                lambda payload: payload["installed_v263_current_state"].__setitem__(
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
            (root / "references/current/generations/V2.65/core.md").write_text(
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
