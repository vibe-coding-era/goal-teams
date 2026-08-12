from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v250.discovery_policy import (
    DiscoveryCandidateSpec,
    DiscoveryDecision,
    DiscoveryPolicyError,
    discover_and_select,
)
from scripts.v250.generation_runtime import (
    ACTIVE_PATH,
    GenerationRuntimeSession,
    GenerationSnapshot,
    canonical_json_digest,
    sha256_bytes,
)
from scripts.v250.prompt_compiler import (
    PromptCompilerError,
    compile_runtime_prompt_artifact,
    validate_derived_route_receipt,
)
from scripts.v250.route_derivation import derive_route
from scripts.v250.runtime_session import RuntimeSessionError, start_runtime_session
from scripts.v250.turn_receipt import (
    TurnReceiptError,
    create_authorized_delta,
    create_runtime_turn_receipt,
)


SHA = {value: value * 64 for value in "0123456789abcdef"}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def route_facts(**overrides: object) -> dict[str, object]:
    facts: dict[str, object] = {
        "project_size": "large",
        "workflow_phase": "development",
        "stage": "candidate",
        "release_intent": True,
        "implementation_scope_complete": False,
        "risk": "critical",
        "failure_consequence": "critical",
        "reversibility": "irreversible",
        "compliance": "regulated",
        "external_write": True,
        "security_sensitive": True,
        "ui_or_desktop": False,
        "agent_runtime": True,
        "environment_check_required": True,
        "authorization_state": "granted",
        "facts_source_sha256": SHA["a"],
    }
    facts.update(overrides)
    return facts


def current_bindings(context_delta: object, **overrides: str) -> dict[str, str]:
    bindings = {
        "generation_snapshot_sha256": SHA["1"],
        "derived_route_sha256": SHA["2"],
        "task_exact_set_sha256": SHA["3"],
        "locked_scope_sha256": SHA["4"],
        "authorization_lineage_sha256": SHA["5"],
        "context_sha256": SHA["6"],
        "context_delta_sha256": canonical_json_digest(context_delta),
    }
    bindings.update(overrides)
    return bindings


class RuntimeFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.refs = ["rules/core.md", "rules/testing.md"]
        for relative, raw in {
            "SKILL.md": b"---\nname: goal-teams\ndescription: fixture\n---\n",
            self.refs[0]: b"core\n",
            self.refs[1]: b"testing\n",
        }.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

        self.route = derive_route(route_facts())
        self.prompt_manifest = {
            "schema_version": "goal-teams-prompt-manifest-v2.50",
            "generation_id": "V2.63",
            "manifest_state": "active_current",
            "routes": {
                self.route["route_id"]: {
                    "workflow_phase": self.route["workflow_phase"],
                    "ordered_refs": self.refs,
                    "required_gates": self.route["required_gates"],
                    "conditional_gates": self.route["conditional_gates"],
                }
            },
        }
        self.prompt_raw = _canonical_bytes(self.prompt_manifest)
        prompt_relative = (
            "references/current/generations/V2.63/prompt-manifest.json"
        )
        prompt_path = root / prompt_relative
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_bytes(self.prompt_raw)

        activation_relative = (
            "references/current/generations/V2.63/activation-manifest.json"
        )
        activation = {
            "schema_version": "goal-teams-activation-manifest-v2.50",
            "generation_id": "V2.63",
            "identity": {
                "loaded_runtime_product_version": "V2.63",
                "target_policy_generation": "V2.63",
            },
            "prompt_manifest_path": prompt_relative,
            "prompt_plan_digest": sha256_bytes(self.prompt_raw),
        }
        activation_raw = _canonical_bytes(activation)
        (root / activation_relative).write_bytes(activation_raw)
        self.activation_sha256 = sha256_bytes(activation_raw)

        active = {
            "schema_version": "goal-teams-active-generation-v1",
            "generation_id": "V2.63",
            "activation_manifest": activation_relative,
            "activation_manifest_sha256": self.activation_sha256,
            "state": "active_current",
        }
        active_path = root / ACTIVE_PATH
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_raw = _canonical_bytes(active)
        active_path.write_bytes(active_raw)
        self.active_sha256 = sha256_bytes(active_raw)

        spec = DiscoveryCandidateSpec(
            root=root,
            root_kind="canonical_install",
            expected_activation_sha256=self.activation_sha256,
            discovery_order=0,
            source_commit="1" * 40,
            source_tree="2" * 40,
        )
        self.decision = discover_and_select((spec,))
        generation = {
            "active_sha256": self.active_sha256,
            "activation_manifest_sha256": self.activation_sha256,
            "rule_manifest_sha256": SHA["7"],
            "prompt_manifest_sha256": sha256_bytes(self.prompt_raw),
            "generation_id": "V2.63",
            "member_digests": {
                path: sha256_bytes((root / path).read_bytes())
                for path in ["SKILL.md", *self.refs]
            },
            "activation_manifest": {
                "root_sets": {"bootstrap": [{"path": "SKILL.md"}]}
            },
        }
        with mock.patch(
            "scripts.v250.generation_runtime.load_generation",
            return_value=generation,
        ):
            self.session = GenerationRuntimeSession.initialize(
                root,
                session_id="GEN-SESSION-263-TRUST",
                source_commit="1" * 40,
                source_tree="2" * 40,
                captured_at="2026-08-12T00:00:00+00:00",
            )

    def artifact(self) -> dict[str, object]:
        return compile_runtime_prompt_artifact(
            self.root,
            generation_runtime_session=self.session,
            derived_route_receipt=self.route,
            prompt_manifest_bytes=self.prompt_raw,
            member_packet="role=runtime\n",
        )

    def observation(
        self, artifact: dict[str, object], *, selected_root: str | None = None
    ) -> dict[str, object]:
        return {
            "schema_version": "goal-teams-host-load-observation-v2.63",
            "host_execution_id": "HOST-EXEC-263-TRUST",
            "selected_root_realpath": selected_root or self.root.resolve().as_posix(),
            "opened_files": copy.deepcopy(artifact["path_entries"]),
            "observation_source": "repository_integration_fixture",
            "actor_relationship": "correlated",
            "external_independent": False,
            "cryptographic_host_attestation": False,
            "provider_prompt_assembly": "unavailable",
        }


class TestV263DerivedRouteTrustBoundary(unittest.TestCase):
    def test_receipt_carries_exact_normalized_facts(self) -> None:
        facts = route_facts()
        receipt = derive_route(dict(reversed(list(facts.items()))))

        self.assertEqual(facts, receipt["facts"])
        self.assertEqual(canonical_json_digest(facts), receipt["facts_sha256"])
        self.assertEqual(receipt, validate_derived_route_receipt(receipt))

    def test_re_signed_summary_cannot_downgrade_replayed_facts(self) -> None:
        critical = derive_route(route_facts())
        attacker_route = derive_route(
            route_facts(
                project_size="small",
                risk="low",
                failure_consequence="low",
                reversibility="reversible",
                compliance="none",
                external_write=False,
                security_sensitive=False,
                agent_runtime=False,
                environment_check_required=False,
                authorization_state="not_required",
            )
        )
        attacked = copy.deepcopy(critical)
        for field in (
            "project_size",
            "workflow_phase",
            "route_id",
            "assurance_floor",
            "effective_assurance",
            "required_gates",
            "conditional_gates",
            "exclusion_reasons",
        ):
            attacked[field] = copy.deepcopy(attacker_route[field])
        attacked["receipt_sha256"] = canonical_json_digest(
            {key: value for key, value in attacked.items() if key != "receipt_sha256"}
        )

        with self.assertRaises(PromptCompilerError) as caught:
            validate_derived_route_receipt(attacked)
        self.assertEqual("E_V263_PROMPT_ROUTE_REPLAY", caught.exception.code)

    def test_facts_with_missing_extra_or_changed_values_are_rejected(self) -> None:
        receipt = derive_route(route_facts())
        mutations = []
        missing = copy.deepcopy(receipt)
        missing["facts"].pop("risk")
        mutations.append(missing)
        extra = copy.deepcopy(receipt)
        extra["facts"]["caller_route"] = "small"
        mutations.append(extra)
        changed = copy.deepcopy(receipt)
        changed["facts"]["risk"] = "low"
        mutations.append(changed)
        for value in mutations:
            value["receipt_sha256"] = canonical_json_digest(
                {key: item for key, item in value.items() if key != "receipt_sha256"}
            )
            with self.subTest(facts=value["facts"]):
                with self.assertRaises(PromptCompilerError):
                    validate_derived_route_receipt(value)

    def test_schema_requires_embedded_exact_facts(self) -> None:
        schema = json.loads(Path("schemas/v2.50/route-prompt.schema.json").read_text())
        receipt = schema["$defs"]["derivedRouteReceipt"]
        self.assertIn("facts", receipt["required"])
        self.assertEqual(
            {"$ref": "#/$defs/projectRouteFacts"}, receipt["properties"]["facts"]
        )
        self.assertIn("stage", schema["$defs"]["projectRouteFacts"]["required"])


class TestV263RuntimeProvenanceBoundary(unittest.TestCase):
    def test_public_self_authored_snapshot_is_never_trusted_runtime_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "rules/core.md"
            (root / "rules").mkdir()
            (root / relative).write_bytes(b"core\n")
            route = derive_route(route_facts())
            manifest = {
                "schema_version": "goal-teams-prompt-manifest-v2.50",
                "generation_id": "V2.63",
                "manifest_state": "active_current",
                "routes": {
                    route["route_id"]: {
                        "workflow_phase": route["workflow_phase"],
                        "ordered_refs": [relative],
                    }
                },
            }
            manifest_raw = _canonical_bytes(manifest)
            payload = {
                "session_id": "FORGED-SNAPSHOT",
                "selected_root_realpath": root.resolve().as_posix(),
                "source_commit": None,
                "source_tree": None,
                "active_sha256": SHA["1"],
                "activation_manifest_sha256": SHA["2"],
                "rule_manifest_sha256": SHA["3"],
                "prompt_manifest_sha256": sha256_bytes(manifest_raw),
                "generation_id": "V2.63",
                "member_digests": (
                    (relative, sha256_bytes((root / relative).read_bytes())),
                ),
                "captured_at": "2026-08-12T00:00:00+00:00",
            }
            forged = GenerationSnapshot(
                **payload,
                snapshot_sha256=canonical_json_digest(payload),
            )

            with self.assertRaises(PromptCompilerError) as caught:
                compile_runtime_prompt_artifact(
                    root,
                    generation_snapshot=forged,
                    derived_route_receipt=route,
                    prompt_manifest_bytes=manifest_raw,
                    member_packet="role=forged\n",
                )
            self.assertEqual(
                "E_V263_PROMPT_LOADER_SESSION_REQUIRED", caught.exception.code
            )

    def test_runtime_binds_loader_session_discovery_and_host_root_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            artifact = fixture.artifact()
            self.assertEqual(["SKILL.md"], artifact["bootstrap_refs"])

            with self.assertRaises(RuntimeSessionError) as wrong_root:
                start_runtime_session(
                    runtime_session_id="SESSION-WRONG-ROOT",
                    discovery_decision=fixture.decision,
                    generation_runtime_session=fixture.session,
                    derived_route_receipt=fixture.route,
                    prompt_artifact=artifact,
                    host_load_observation=fixture.observation(
                        artifact, selected_root="/tmp/forged-goal-teams"
                    ),
                    host_execution_id="HOST-EXEC-263-TRUST",
                )
            self.assertEqual("E_V263_RUNTIME_ROOT_BINDING", wrong_root.exception.code)

            receipt = start_runtime_session(
                runtime_session_id="SESSION-BOUND",
                discovery_decision=fixture.decision,
                generation_runtime_session=fixture.session,
                derived_route_receipt=fixture.route,
                prompt_artifact=artifact,
                host_load_observation=fixture.observation(artifact),
                host_execution_id="HOST-EXEC-263-TRUST",
            )
            self.assertEqual(
                fixture.decision.decision_sha256,
                receipt["discovery_decision_sha256"],
            )
            self.assertEqual(
                fixture.session.snapshot.selected_root_realpath,
                receipt["selected_root_realpath"],
            )

    def test_caller_cannot_construct_a_discovery_decision_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            artifact = fixture.artifact()
            with self.assertRaises((DiscoveryPolicyError, RuntimeSessionError)):
                forged = DiscoveryDecision(
                    selected=fixture.decision.selected,
                    candidates=fixture.decision.candidates,
                    selection_rule=fixture.decision.selection_rule,
                )
                start_runtime_session(
                    runtime_session_id="SESSION-FORGED-DISCOVERY",
                    discovery_decision=forged,
                    generation_runtime_session=fixture.session,
                    derived_route_receipt=fixture.route,
                    prompt_artifact=artifact,
                    host_load_observation=fixture.observation(artifact),
                    host_execution_id="HOST-EXEC-263-TRUST",
                )


class TestV263AuthorizationTrustBoundary(unittest.TestCase):
    def test_repository_canonical_json_never_mints_external_authority(self) -> None:
        first_delta = {"loaded": ["core"]}
        first = create_runtime_turn_receipt(
            turn_id="TURN-TRUST-1",
            previous_turn_receipt=None,
            bindings=current_bindings(first_delta),
            action={"type": "local_code_write", "target": "scripts/v250"},
            decision="continue",
            evidence_refs=["EVIDENCE-TRUST-1"],
            context_delta=first_delta,
        )
        next_delta = {"loaded": ["core", "testing"]}
        bindings = current_bindings(
            next_delta,
            authorization_lineage_sha256=SHA["8"],
        )
        action = {"type": "github_push", "target": "origin"}
        self_authored = {
            "schema_version": "goal-teams-external-authorization-receipt-v2.63",
            "receipt_id": "SELF-AUTHORED-JSON",
            "issuer": "codex_host",
            "proof_strength": "externally_issued",
            "action_allowlist": ["github_push"],
            "target_scope": ["origin"],
            "authorization_lineage_sha256": SHA["8"],
            "previous_turn_receipt_sha256": first["receipt_sha256"],
        }
        self_authored["receipt_sha256"] = canonical_json_digest(self_authored)

        offline = create_authorized_delta(
            previous_turn_receipt=first,
            next_bindings=bindings,
            next_action=action,
            decision="replan",
            reason="repository JSON cannot prove external authorization",
            authorization_lineage_sha256=SHA["8"],
            authorization_evidence_refs=["SELF-AUTHORED-JSON"],
            authorization_receipt=self_authored,
            expected_authorization_receipt_sha256=self_authored["receipt_sha256"],
            trusted_issuer_allowlist=["codex_host"],
        )
        self.assertFalse(offline["authorization_verified"])
        self.assertEqual("none", offline["permission_effect"])
        self.assertEqual("unverified", offline["authorization_proof_strength"])

        with self.assertRaises(TurnReceiptError) as caught:
            create_runtime_turn_receipt(
                turn_id="TURN-TRUST-2",
                previous_turn_receipt=first,
                bindings=bindings,
                action=action,
                decision="replan",
                evidence_refs=["EVIDENCE-TRUST-2"],
                context_delta=next_delta,
                authorized_delta=offline,
            )
        self.assertEqual("E_V263_TURN_AUTH_REQUIRED", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
