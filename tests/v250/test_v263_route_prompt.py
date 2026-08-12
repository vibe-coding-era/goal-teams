from __future__ import annotations

import base64
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v250.prompt_compiler import PromptCompilerError, compile_prompt_artifact
from scripts.v250.route_derivation import RouteDerivationError, derive_route


SHA_A = "a" * 64
SHA_B = "b" * 64


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
        "facts_source_sha256": SHA_A,
    }
    facts.update(overrides)
    return facts


def prompt_frame(kind: str, label: str, raw: bytes) -> bytes:
    digest = hashlib.sha256(raw).hexdigest()
    header = f"<<<GT-FRAME {kind} {label} {len(raw)} {digest}>>>\n".encode("utf-8")
    return header + raw + b"\n<<<GT-END>>>\n"


class TestV263RouteDerivation(unittest.TestCase):
    def test_high_risk_small_cannot_be_lite_or_caller_selected(self) -> None:
        facts = route_facts(risk="high", failure_consequence="high")
        receipt = derive_route(facts)

        self.assertEqual("V250-ROUTE-SMALL-DEVELOPMENT", receipt["route_id"])
        self.assertEqual("high", receipt["assurance_floor"])
        self.assertNotEqual("lite", receipt["assurance_floor"])
        self.assertIn("independent_review", receipt["required_gates"])
        self.assertEqual(SHA_A, receipt["facts_source_sha256"])

        with self.assertRaises(RouteDerivationError) as downgrade:
            derive_route(facts, requested_assurance="lite")
        self.assertEqual("E_V263_ROUTE_ASSURANCE_DOWNGRADE", downgrade.exception.code)

        caller_selected = route_facts(route_id="V250-ROUTE-SMALL-DEVELOPMENT")
        with self.assertRaises(RouteDerivationError) as caller_route:
            derive_route(caller_selected)
        self.assertEqual("E_V263_ROUTE_CALLER_SELECTED", caller_route.exception.code)

    def test_ui_and_agent_runtime_facts_select_specialized_routes(self) -> None:
        ui = derive_route(route_facts(project_size="medium", ui_or_desktop=True))
        self.assertEqual("V250-ROUTE-UI-DESKTOP", ui["route_id"])
        self.assertIn("ui_e2e", ui["required_gates"])
        self.assertIn("runtime_capability", ui["required_gates"])

        runtime = derive_route(route_facts(project_size="medium", agent_runtime=True))
        self.assertEqual("V250-ROUTE-AGENT-RUNTIME", runtime["route_id"])
        self.assertIn("runtime_capability", runtime["required_gates"])

    def test_release_requires_complete_scope_and_external_write_authorization(self) -> None:
        incomplete = route_facts(
            project_size="medium",
            workflow_phase="release",
            release_intent=True,
            implementation_scope_complete=False,
        )
        with self.assertRaises(RouteDerivationError) as release_error:
            derive_route(incomplete)
        self.assertEqual("E_V263_ROUTE_RELEASE_INCOMPLETE", release_error.exception.code)

        external = route_facts(external_write=True, authorization_state="missing")
        with self.assertRaises(RouteDerivationError) as auth_error:
            derive_route(external)
        self.assertEqual("E_V263_ROUTE_AUTHORIZATION", auth_error.exception.code)

        authorized = derive_route(
            route_facts(external_write=True, authorization_state="granted")
        )
        self.assertIn("project_start_authorization", authorized["required_gates"])

    def test_route_receipt_digest_is_canonical_and_input_order_independent(self) -> None:
        facts = route_facts(project_size="large", agent_runtime=True)
        reversed_facts = dict(reversed(list(facts.items())))
        first = derive_route(facts)
        second = derive_route(reversed_facts)
        self.assertEqual(first, second)
        self.assertRegex(first["facts_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(first["receipt_sha256"], r"^[0-9a-f]{64}$")


class TestV263PromptCompiler(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        files = {
            "bootstrap/SKILL.md": "引导\n".encode(),
            "owners/a.md": b"alpha\n",
            "owners/b.md": "βeta\n".encode(),
        }
        for relative, raw in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def compile(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "repo_root": self.root,
            "bootstrap_refs": ["bootstrap/SKILL.md"],
            "ordered_refs": ["owners/a.md", "owners/b.md"],
            "member_packet": "role=worker\n",
            "generation_snapshot_sha256": SHA_A,
            "derived_route_sha256": SHA_B,
        }
        values.update(overrides)
        return compile_prompt_artifact(**values)

    def test_prompt_has_exact_framing_order_and_recomputable_digest(self) -> None:
        artifact = self.compile()
        expected = b"GOAL-TEAMS-PROMPT-ARTIFACT-V1\n"
        expected += prompt_frame("bootstrap", "bootstrap/SKILL.md", "引导\n".encode())
        expected += prompt_frame("owner", "owners/a.md", b"alpha\n")
        expected += prompt_frame("owner", "owners/b.md", "βeta\n".encode())
        expected += prompt_frame("member", "@member_packet", b"role=worker\n")

        observed = base64.b64decode(artifact["compiled_prompt_base64"], validate=True)
        self.assertEqual(expected, observed)
        self.assertEqual(len(expected), artifact["compiled_prompt_bytes"])
        self.assertEqual(hashlib.sha256(expected).hexdigest(), artifact["compiled_prompt_sha256"])
        self.assertEqual(
            ["bootstrap/SKILL.md", "owners/a.md", "owners/b.md"],
            [entry["path"] for entry in artifact["path_entries"]],
        )

        repeated = self.compile()
        self.assertEqual(artifact, repeated)

    def test_duplicate_ref_is_rejected_instead_of_silent_deduplication(self) -> None:
        with self.assertRaises(PromptCompilerError) as duplicate:
            self.compile(ordered_refs=["owners/a.md", "owners/a.md"])
        self.assertEqual("E_V263_PROMPT_DUPLICATE_REF", duplicate.exception.code)

        with self.assertRaises(PromptCompilerError) as cross_group:
            self.compile(
                bootstrap_refs=["owners/a.md"],
                ordered_refs=["owners/a.md", "owners/b.md"],
            )
        self.assertEqual("E_V263_PROMPT_DUPLICATE_REF", cross_group.exception.code)

    def test_prompt_plan_schema_exposes_actual_byte_digest_contract(self) -> None:
        schema_path = Path("schemas/v2.50/route-prompt.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertIn("projectRouteFacts", schema["$defs"])
        self.assertIn("derivedRouteReceipt", schema["$defs"])
        artifact = schema["$defs"]["promptArtifact"]
        self.assertIn("compiled_prompt_sha256", artifact["required"])
        self.assertIn("compiled_prompt_base64", artifact["required"])
        self.assertFalse(artifact["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
