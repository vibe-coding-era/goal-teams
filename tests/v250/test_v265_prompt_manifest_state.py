from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.v250.generation_runtime import (
    GenerationSnapshot,
    canonical_json_digest,
    sha256_bytes,
)
from scripts.v250.prompt_compiler import PromptCompilerError, compile_runtime_prompt_artifact
from scripts.v250.route_derivation import derive_route


SHA = "a" * 64


class TestV265PromptManifestState(unittest.TestCase):
    def test_inactive_candidate_and_self_authored_snapshot_cannot_claim_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = "rules/core.md"
            (root / "rules").mkdir()
            (root / relative).write_bytes(b"core\n")
            route = derive_route(
                {
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
                    "facts_source_sha256": SHA,
                }
            )
            manifest = {
                "schema_version": "goal-teams-prompt-manifest-v2.50",
                "generation_id": "V2.65",
                "manifest_state": "inactive_candidate",
                "routes": {
                    route["route_id"]: {
                        "workflow_phase": route["workflow_phase"],
                        "ordered_refs": [relative],
                    }
                },
            }
            raw = json.dumps(
                manifest, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            payload = {
                "session_id": "GEN-SESSION-265-STATE",
                "selected_root_realpath": root.resolve().as_posix(),
                "source_commit": None,
                "source_tree": None,
                "active_sha256": SHA,
                "activation_manifest_sha256": SHA,
                "rule_manifest_sha256": SHA,
                "prompt_manifest_sha256": sha256_bytes(raw),
                "generation_id": "V2.65",
                "member_digests": ((relative, sha256_bytes((root / relative).read_bytes())),),
                "captured_at": "2026-08-22T00:00:00+08:00",
            }
            snapshot = GenerationSnapshot(
                **payload,
                snapshot_sha256=canonical_json_digest(payload),
            )

            with self.assertRaises(PromptCompilerError) as caught:
                compile_runtime_prompt_artifact(
                    root,
                    generation_snapshot=snapshot,
                    derived_route_receipt=route,
                    prompt_manifest_bytes=raw,
                    member_packet=b"role=fixture\n",
                )
            self.assertEqual(
                "E_V263_PROMPT_LOADER_SESSION_REQUIRED", caught.exception.code
            )


if __name__ == "__main__":
    unittest.main()
