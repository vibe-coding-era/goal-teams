from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v250.prompt_compiler import compile_prompt_artifact
from scripts.v250.runtime_session import (
    RuntimeSessionError,
    compile_runtime_session_receipt,
    validate_host_load_observation,
)
from scripts.v250.turn_receipt import (
    TurnReceiptError,
    create_authorized_delta,
    create_turn_receipt,
)


SHA = {letter: letter * 64 for letter in "abcdef0123456789"}


class TestV263RuntimeSession(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative, raw in {
            "bootstrap/SKILL.md": b"skill\n",
            "owners/core.md": b"core\n",
            "owners/runtime.md": b"runtime\n",
        }.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.artifact = compile_prompt_artifact(
            self.root,
            bootstrap_refs=["bootstrap/SKILL.md"],
            ordered_refs=["owners/core.md", "owners/runtime.md"],
            member_packet="role=runtime\n",
            generation_snapshot_sha256=SHA["a"],
            derived_route_sha256=SHA["b"],
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def observation(self) -> dict[str, object]:
        return {
            "schema_version": "goal-teams-host-load-observation-v2.65",
            "host_execution_id": "HOST-EXEC-263-1",
            "selected_root_realpath": str(self.root.resolve()),
            "opened_files": copy.deepcopy(self.artifact["path_entries"]),
            "observation_source": "repository_integration_fixture",
            "actor_relationship": "correlated",
            "external_independent": False,
            "cryptographic_host_attestation": False,
            "provider_prompt_assembly": "unavailable",
        }

    def test_host_observation_missing_or_out_of_order_fails_closed(self) -> None:
        missing = self.observation()
        missing["opened_files"] = missing["opened_files"][:-1]
        with self.assertRaises(RuntimeSessionError) as missing_error:
            validate_host_load_observation(self.artifact, missing)
        self.assertEqual("E_V263_HOST_LOAD_MISSING", missing_error.exception.code)

        reordered = self.observation()
        reordered["opened_files"][0], reordered["opened_files"][1] = (
            reordered["opened_files"][1],
            reordered["opened_files"][0],
        )
        with self.assertRaises(RuntimeSessionError) as order_error:
            validate_host_load_observation(self.artifact, reordered)
        self.assertEqual("E_V263_HOST_LOAD_ORDER", order_error.exception.code)

        digest_drift = self.observation()
        digest_drift["opened_files"][1]["sha256"] = SHA["f"]
        with self.assertRaises(RuntimeSessionError) as digest_error:
            validate_host_load_observation(self.artifact, digest_drift)
        self.assertEqual("E_V263_HOST_LOAD_DIGEST", digest_error.exception.code)

    def test_repository_session_receipt_never_claims_host_or_provider_proof(self) -> None:
        observation = self.observation()
        receipt = compile_runtime_session_receipt(
            runtime_session_id="SESSION-263-1",
            discovery_decision_sha256=SHA["c"],
            generation_snapshot_sha256=SHA["a"],
            derived_route_sha256=SHA["b"],
            prompt_artifact=self.artifact,
            host_load_observation=observation,
            host_execution_id="HOST-EXEC-263-1",
        )

        self.assertEqual("correlated", receipt["proof_strength"])
        self.assertEqual("correlated", receipt["actor_relationship"])
        self.assertFalse(receipt["host_runtime_verified"])
        self.assertFalse(receipt["external_independent"])
        self.assertFalse(receipt["cryptographic_host_attestation"])
        self.assertEqual("unavailable", receipt["provider_prompt_assembly"])
        self.assertTrue(receipt["planned_observed_match"])
        self.assertRegex(receipt["receipt_sha256"], r"^[0-9a-f]{64}$")

        elevated = self.observation()
        elevated["provider_prompt_assembly"] = "verified"
        with self.assertRaises(RuntimeSessionError) as proof_error:
            compile_runtime_session_receipt(
                runtime_session_id="SESSION-263-FORGED",
                discovery_decision_sha256=SHA["c"],
                generation_snapshot_sha256=SHA["a"],
                derived_route_sha256=SHA["b"],
                prompt_artifact=self.artifact,
                host_load_observation=elevated,
                host_execution_id="HOST-EXEC-263-1",
            )
        self.assertEqual("E_V263_PROVIDER_PROOF_FORBIDDEN", proof_error.exception.code)

    def test_runtime_schema_keeps_repository_assurance_bounded(self) -> None:
        schema = json.loads(
            Path("schemas/v2.50/runtime-session-turn.schema.json").read_text(
                encoding="utf-8"
            )
        )
        session = schema["$defs"]["runtimeSessionReceipt"]
        self.assertEqual({"const": "correlated"}, session["properties"]["proof_strength"])
        self.assertEqual(
            {"const": "unavailable"},
            session["properties"]["provider_prompt_assembly"],
        )
        self.assertEqual({"const": False}, session["properties"]["host_runtime_verified"])


def turn_bindings(**overrides: str) -> dict[str, str]:
    value = {
        "generation_snapshot_sha256": SHA["a"],
        "derived_route_sha256": SHA["b"],
        "task_exact_set_sha256": SHA["c"],
        "locked_scope_sha256": SHA["d"],
        "authorization_lineage_sha256": SHA["e"],
        "context_sha256": SHA["f"],
    }
    value.update(overrides)
    return value


class TestV263TurnReceipt(unittest.TestCase):
    def first_turn(self) -> dict[str, object]:
        return create_turn_receipt(
            turn_id="TURN-263-1",
            previous_turn_receipt=None,
            bindings=turn_bindings(),
            action={"type": "local_code_write", "target": "scripts/v250"},
            decision="continue",
            evidence_refs=["EVIDENCE-RED-1"],
        )

    def test_silent_route_context_scope_or_action_drift_is_rejected(self) -> None:
        first = self.first_turn()
        drifts = {
            "route": (
                turn_bindings(derived_route_sha256=SHA["0"]),
                {"type": "local_code_write", "target": "scripts/v250"},
            ),
            "context": (
                turn_bindings(context_sha256=SHA["0"]),
                {"type": "local_code_write", "target": "scripts/v250"},
            ),
            "scope": (
                turn_bindings(locked_scope_sha256=SHA["0"]),
                {"type": "local_code_write", "target": "scripts/v250"},
            ),
            "action": (
                turn_bindings(),
                {"type": "github_push", "target": "origin"},
            ),
        }
        for name, (bindings, action) in drifts.items():
            with self.subTest(name=name):
                with self.assertRaises(TurnReceiptError) as error:
                    create_turn_receipt(
                        turn_id=f"TURN-263-2-{name}",
                        previous_turn_receipt=first,
                        bindings=bindings,
                        action=action,
                        decision="continue",
                        evidence_refs=["EVIDENCE-GREEN-1"],
                    )
                self.assertEqual("E_V263_TURN_SILENT_DRIFT", error.exception.code)

    def test_authorized_delta_exactly_binds_previous_new_and_auth_lineage(self) -> None:
        first = self.first_turn()
        next_bindings = turn_bindings(
            locked_scope_sha256=SHA["0"],
            context_sha256=SHA["1"],
            authorization_lineage_sha256=SHA["2"],
        )
        next_action = {"type": "github_push", "target": "origin"}
        delta = create_authorized_delta(
            previous_turn_receipt=first,
            next_bindings=next_bindings,
            next_action=next_action,
            decision="replan",
            reason="user authorized the expanded scope and external action",
            authorization_lineage_sha256=SHA["2"],
            authorization_evidence_refs=["AUTH-263-EXPANSION"],
        )
        second = create_turn_receipt(
            turn_id="TURN-263-2",
            previous_turn_receipt=first,
            bindings=next_bindings,
            action=next_action,
            decision="replan",
            evidence_refs=["EVIDENCE-REPLAN-1"],
            authorized_delta=delta,
        )

        self.assertEqual(first["receipt_sha256"], second["previous_turn_receipt_sha256"])
        self.assertEqual(delta["receipt_sha256"], second["authorized_delta_sha256"])
        self.assertEqual(
            [
                "action.target",
                "action.type",
                "bindings.authorization_lineage_sha256",
                "bindings.context_sha256",
                "bindings.locked_scope_sha256",
            ],
            delta["changed_fields"],
        )

        wrong_lineage = copy.deepcopy(delta)
        wrong_lineage["authorization_lineage_sha256"] = SHA["3"]
        wrong_lineage["receipt_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in wrong_lineage.items() if key != "receipt_sha256"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self.assertRaises(TurnReceiptError) as auth_error:
            create_turn_receipt(
                turn_id="TURN-263-3",
                previous_turn_receipt=first,
                bindings=next_bindings,
                action=next_action,
                decision="replan",
                evidence_refs=["EVIDENCE-REPLAN-2"],
                authorized_delta=wrong_lineage,
            )
        self.assertEqual("E_V263_TURN_AUTH_LINEAGE", auth_error.exception.code)

    def test_unchanged_turn_extends_hash_chain_without_delta(self) -> None:
        first = self.first_turn()
        second = create_turn_receipt(
            turn_id="TURN-263-2-STABLE",
            previous_turn_receipt=first,
            bindings=turn_bindings(),
            action={"type": "local_code_write", "target": "scripts/v250"},
            decision="continue",
            evidence_refs=["EVIDENCE-GREEN-1"],
        )
        self.assertEqual(first["receipt_sha256"], second["previous_turn_receipt_sha256"])
        self.assertIsNone(second["authorized_delta_sha256"])
        self.assertRegex(second["receipt_sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
