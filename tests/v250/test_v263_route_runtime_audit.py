from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v250.generation_runtime import canonical_json_digest, sha256_bytes
from scripts.v250.prompt_compiler import (
    compile_prompt_artifact,
    compile_runtime_prompt_artifact,
)
from scripts.v250.route_derivation import RouteDerivationError, derive_route
from scripts.v250.runtime_session import (
    RuntimeSessionError,
    start_runtime_session,
    validate_prompt_artifact_integrity,
)
from scripts.v250.turn_receipt import (
    TurnReceiptError,
    create_authorized_delta,
    create_runtime_turn_receipt,
)
from tests.v250.test_v263_trust_boundary_hardening import RuntimeFixture


SHA = {letter: letter * 64 for letter in "abcdef0123456789"}


def route_facts(**overrides: object) -> dict[str, object]:
    facts: dict[str, object] = {
        "project_size": "small",
        "workflow_phase": "development",
        "stage": "candidate",
        "release_intent": False,
        "implementation_scope_complete": False,
        "risk": "low",
        "failure_consequence": "low",
        "reversibility": "reversible",
        "compliance": "none",
        "external_write": False,
        "security_sensitive": False,
        "ui_or_desktop": False,
        "agent_runtime": False,
        "environment_check_required": False,
        "authorization_state": "not_required",
        "facts_source_sha256": SHA["a"],
    }
    facts.update(overrides)
    return facts


def context_digest(value: object) -> str:
    return canonical_json_digest(value)


def current_bindings(delta: object, **overrides: str) -> dict[str, str]:
    value = {
        "generation_snapshot_sha256": SHA["a"],
        "derived_route_sha256": SHA["b"],
        "task_exact_set_sha256": SHA["c"],
        "locked_scope_sha256": SHA["d"],
        "authorization_lineage_sha256": SHA["e"],
        "context_sha256": SHA["f"],
        "context_delta_sha256": context_digest(delta),
    }
    value.update(overrides)
    return value


class TestV263RouteContradictions(unittest.TestCase):
    def test_discussion_rejects_execution_and_release_facts(self) -> None:
        conflicts = (
            {"release_intent": True},
            {"implementation_scope_complete": True},
            {"external_write": True, "authorization_state": "granted"},
            {"ui_or_desktop": True},
            {"agent_runtime": True},
            {"environment_check_required": True},
            {"authorization_state": "granted"},
        )
        for conflict in conflicts:
            with self.subTest(conflict=conflict):
                facts = route_facts(
                    project_size="discussion",
                    workflow_phase="discussion",
                    **conflict,
                )
                with self.assertRaises(RouteDerivationError) as error:
                    derive_route(facts)
                self.assertEqual(
                    "E_V263_ROUTE_DISCUSSION_CONFLICT", error.exception.code
                )


class TestV263TrustedPromptRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = RuntimeFixture(self.root)
        self.refs = self.fixture.refs
        self.route = self.fixture.route
        self.manifest = self.fixture.prompt_manifest
        self.manifest_raw = self.fixture.prompt_raw
        self.session = self.fixture.session
        self.decision = self.fixture.decision
        self.snapshot = self.session.snapshot

    def tearDown(self) -> None:
        self.temp.cleanup()

    def artifact(self) -> dict[str, object]:
        return compile_runtime_prompt_artifact(
            self.root,
            generation_runtime_session=self.session,
            derived_route_receipt=self.route,
            prompt_manifest_bytes=self.manifest_raw,
            member_packet="role=runtime\n",
        )

    def observation(self, artifact: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": "goal-teams-host-load-observation-v2.63",
            "host_execution_id": "HOST-EXEC-263-AUDIT",
            "selected_root_realpath": self.root.resolve().as_posix(),
            "opened_files": copy.deepcopy(artifact["path_entries"]),
            "observation_source": "repository_integration_fixture",
            "actor_relationship": "correlated",
            "external_independent": False,
            "cryptographic_host_attestation": False,
            "provider_prompt_assembly": "unavailable",
        }

    def test_runtime_plan_is_uniquely_derived_from_verified_inputs(self) -> None:
        artifact = self.artifact()
        self.assertEqual("trusted_runtime", artifact["compiler_mode"])
        self.assertEqual(["SKILL.md"], artifact["bootstrap_refs"])
        self.assertEqual(self.refs, artifact["ordered_refs"])
        self.assertEqual(self.route["route_id"], artifact["route_id"])
        self.assertEqual(
            sha256_bytes(self.manifest_raw), artifact["prompt_manifest_sha256"]
        )

        changed_manifest = self.manifest_raw.replace(b"testing.md", b"changed.md")
        with self.assertRaises(Exception):
            compile_runtime_prompt_artifact(
                self.root,
                generation_runtime_session=self.session,
                derived_route_receipt=self.route,
                prompt_manifest_bytes=changed_manifest,
                member_packet="role=runtime\n",
            )

    def test_runtime_validator_recomputes_plan_member_and_frames(self) -> None:
        artifact = self.artifact()
        validate_prompt_artifact_integrity(artifact, require_trusted_runtime=True)
        mutations = {
            "plan": ("prompt_plan_sha256", SHA["0"]),
            "member": ("member_packet_sha256", SHA["0"]),
        }
        for name, (field, value) in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(artifact)
                changed[field] = value
                changed["receipt_sha256"] = canonical_json_digest(
                    {key: item for key, item in changed.items() if key != "receipt_sha256"}
                )
                with self.assertRaises(RuntimeSessionError):
                    validate_prompt_artifact_integrity(
                        changed, require_trusted_runtime=True
                    )

        path_changed = copy.deepcopy(artifact)
        path_changed["path_entries"][0]["sha256"] = SHA["0"]
        path_changed["receipt_sha256"] = canonical_json_digest(
            {key: item for key, item in path_changed.items() if key != "receipt_sha256"}
        )
        with self.assertRaises(RuntimeSessionError):
            validate_prompt_artifact_integrity(
                path_changed, require_trusted_runtime=True
            )

    def test_runtime_entry_rejects_offline_plan_and_exposes_bounded_states(self) -> None:
        offline = compile_prompt_artifact(
            self.root,
            bootstrap_refs=[self.refs[0]],
            ordered_refs=[self.refs[1]],
            member_packet="role=offline\n",
            generation_snapshot_sha256=self.snapshot.snapshot_sha256,
            derived_route_sha256=self.route["receipt_sha256"],
        )
        with self.assertRaises(RuntimeSessionError) as offline_error:
            start_runtime_session(
                runtime_session_id="SESSION-OFFLINE",
                discovery_decision=self.decision,
                generation_runtime_session=self.session,
                derived_route_receipt=self.route,
                prompt_artifact=offline,
                host_load_observation=self.observation(offline),
                host_execution_id="HOST-EXEC-263-AUDIT",
            )
        self.assertEqual(
            "E_V263_RUNTIME_TRUSTED_PROMPT_REQUIRED", offline_error.exception.code
        )

        trusted = self.artifact()
        receipt = start_runtime_session(
            runtime_session_id="SESSION-TRUSTED",
            discovery_decision=self.decision,
            generation_runtime_session=self.session,
            derived_route_receipt=self.route,
            prompt_artifact=trusted,
            host_load_observation=self.observation(trusted),
            host_execution_id="HOST-EXEC-263-AUDIT",
        )
        self.assertEqual(
            {
                "repository": "repository_compiled",
                "host": "host_received",
                "provider": "unavailable",
            },
            receipt["delivery_state"],
        )
        self.assertEqual("correlated", receipt["host_delivery_assurance"])
        self.assertEqual("repository_only", receipt["capability_state"])
        self.assertFalse(receipt["host_runtime_verified"])


class TestV263ExternalAuthorizationAndContextDelta(unittest.TestCase):
    def first_turn(self, delta: object) -> dict[str, object]:
        return create_runtime_turn_receipt(
            turn_id="TURN-AUDIT-1",
            previous_turn_receipt=None,
            bindings=current_bindings(delta),
            action={"type": "local_code_write", "target": "scripts/v250"},
            decision="continue",
            evidence_refs=["EVIDENCE-AUDIT-1"],
            context_delta=delta,
        )

    def authorization(
        self, previous: dict[str, object], lineage: str
    ) -> dict[str, object]:
        receipt: dict[str, object] = {
            "schema_version": "goal-teams-external-authorization-receipt-v2.63",
            "receipt_id": "AUTH-AUDIT-263-1",
            "issuer": "codex_host",
            "proof_strength": "externally_issued",
            "action_allowlist": ["github_push"],
            "target_scope": ["origin"],
            "authorization_lineage_sha256": lineage,
            "previous_turn_receipt_sha256": previous["receipt_sha256"],
        }
        receipt["receipt_sha256"] = canonical_json_digest(receipt)
        return receipt

    def test_delta_does_not_self_sign_and_runtime_requires_external_receipt(self) -> None:
        first_delta = {"loaded": ["core"]}
        first = self.first_turn(first_delta)
        next_delta = {"loaded": ["core", "testing"]}
        bindings = current_bindings(
            next_delta,
            context_sha256=SHA["0"],
            authorization_lineage_sha256=SHA["1"],
        )
        action = {"type": "github_push", "target": "origin"}
        unverified = create_authorized_delta(
            previous_turn_receipt=first,
            next_bindings=bindings,
            next_action=action,
            decision="replan",
            reason="offline proposal only",
            authorization_lineage_sha256=SHA["1"],
            authorization_evidence_refs=["AUTH-REFERENCE-ONLY"],
        )
        self.assertFalse(unverified["authorization_verified"])
        self.assertEqual("none", unverified["permission_effect"])
        with self.assertRaises(TurnReceiptError) as missing:
            create_runtime_turn_receipt(
                turn_id="TURN-AUDIT-2-MISSING",
                previous_turn_receipt=first,
                bindings=bindings,
                action=action,
                decision="replan",
                evidence_refs=["EVIDENCE-AUDIT-2"],
                authorized_delta=unverified,
                context_delta=next_delta,
            )
        self.assertEqual("E_V263_TURN_AUTH_REQUIRED", missing.exception.code)

        authorization = self.authorization(first, SHA["1"])
        verified = create_authorized_delta(
            previous_turn_receipt=first,
            next_bindings=bindings,
            next_action=action,
            decision="replan",
            reason="externally authorized transition",
            authorization_lineage_sha256=SHA["1"],
            authorization_evidence_refs=["AUTH-AUDIT-263-1"],
            authorization_receipt=authorization,
            expected_authorization_receipt_sha256=authorization["receipt_sha256"],
            trusted_issuer_allowlist=["codex_host"],
        )
        self.assertFalse(verified["authorization_verified"])
        self.assertEqual("none", verified["permission_effect"])
        with self.assertRaises(TurnReceiptError) as repository_auth:
            create_runtime_turn_receipt(
                turn_id="TURN-AUDIT-2",
                previous_turn_receipt=first,
                bindings=bindings,
                action=action,
                decision="replan",
                evidence_refs=["EVIDENCE-AUDIT-2"],
                authorized_delta=verified,
                context_delta=next_delta,
            )
        self.assertEqual("E_V263_TURN_AUTH_REQUIRED", repository_auth.exception.code)

    def test_actual_context_delta_must_match_binding(self) -> None:
        expected = {"turn": 1}
        with self.assertRaises(TurnReceiptError) as mismatch:
            create_runtime_turn_receipt(
                turn_id="TURN-AUDIT-CONTEXT-MISMATCH",
                previous_turn_receipt=None,
                bindings=current_bindings(expected),
                action={"type": "local_code_write", "target": "scripts/v250"},
                decision="continue",
                evidence_refs=["EVIDENCE-AUDIT-CONTEXT"],
                context_delta={"turn": 2},
            )
        self.assertEqual("E_V263_TURN_CONTEXT_DELTA", mismatch.exception.code)

    def test_schema_exposes_authorization_delivery_and_delta_states(self) -> None:
        route_schema = json.loads(
            Path("schemas/v2.50/route-prompt.schema.json").read_text()
        )
        runtime_schema = json.loads(
            Path("schemas/v2.50/runtime-session-turn.schema.json").read_text()
        )
        self.assertIn(
            "compiler_mode", route_schema["$defs"]["promptArtifact"]["required"]
        )
        self.assertIn(
            "delivery_state",
            runtime_schema["$defs"]["runtimeSessionReceipt"]["required"],
        )
        self.assertIn("externalAuthorizationReceipt", runtime_schema["$defs"])
        self.assertIn(
            "context_delta_sha256",
            runtime_schema["$defs"]["turnBindingsV263"]["required"],
        )


if __name__ == "__main__":
    unittest.main()
