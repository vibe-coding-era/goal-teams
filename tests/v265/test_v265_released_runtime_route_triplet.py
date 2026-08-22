from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.v250.generation_runtime import canonical_json_digest
from scripts.v250.route_closure import (
    RouteClosureError,
    compile_derived_route_closure,
    validate_declared_route_closure,
    validate_released_runtime_route_triplet,
)
from scripts.v250.route_derivation import derive_route


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ROUTE_ID = "V250-ROUTE-MEDIUM-RELEASE"


def canonical_raw(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def release_facts(source_sha256: str, **overrides: object) -> dict[str, object]:
    value = {
        "project_size": "medium",
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
        "facts_source_sha256": source_sha256,
    }
    value.update(overrides)
    return value


class TestV265ReleasedRuntimeRouteTriplet(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rule_path = "references/current/generations/V2.65/core.md"
        raw = b"# V2.65 test rule\n"
        path = self.root / self.rule_path
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
        self.facts_source = {
            "schema_version": "goal-teams-project-route-facts-source-v2.65",
            "repository": "vibe-coding-era/goal-teams",
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "workflow_run_id": "100",
            "workflow_run_attempt": "1",
            "project_start_authorization_receipt_sha256": "3" * 64,
        }
        self.facts = release_facts(canonical_json_digest(self.facts_source))
        self.derived = derive_route(self.facts, generation_id="V2.65")
        owner = {
            "owner_id": "core",
            "path": self.rule_path,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "owned_rule_ids": ["GT265-TEST-RULE"],
            "route_membership": [ROUTE_ID],
            "dependencies": [],
        }
        self.generation = {
            "generation_id": "V2.65",
            "activation_digest_verified": True,
            "member_digests_verified": True,
            "prompt_manifest": {
                "routes": {
                    ROUTE_ID: {
                        "workflow_phase": "release",
                        "ordered_refs": [self.rule_path],
                        "required_gates": self.derived["required_gates"],
                        "conditional_gates": self.derived["conditional_gates"],
                        "expected_loaded_rule_bytes": len(raw),
                        "max_loaded_rule_bytes": len(raw),
                    }
                }
            },
            "rule_manifest": {"owners": [owner]},
            "current_default_allowlist": [self.rule_path],
            "legacy_exact_paths": [],
            "legacy_path_prefixes": [],
            "activation_manifest": {
                "budgets": {"max_route_rule_bytes": len(raw)}
            },
        }
        self.closure = compile_derived_route_closure(
            self.root, self.generation, self.derived
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def facts_raw(self, facts: dict[str, object] | None = None) -> bytes:
        selected = facts or self.facts
        return canonical_raw(
            {
                "facts_source": self.facts_source,
                "project_route_facts": selected,
                "project_route_facts_sha256": canonical_json_digest(selected),
            }
        )

    def validate(self, **overrides: object) -> dict[str, object]:
        return validate_released_runtime_route_triplet(
            self.root,
            self.generation,
            project_route_facts_raw=overrides.get("facts_raw", self.facts_raw()),
            derived_route_receipt_raw=overrides.get(
                "derived_raw", canonical_raw(self.derived)
            ),
            route_closure_raw=overrides.get(
                "closure_raw", canonical_raw(self.closure)
            ),
            expected_stage="released",
            expected_workflow_phase="release",
            expected_project_size=str(overrides.get("project_size", "medium")),
            expected_route_id=(
                "V250-ROUTE-LARGE-RELEASE"
                if overrides.get("project_size") == "large"
                else ROUTE_ID
            ),
        )

    def test_v265_current_route_surface_exists_before_released_triplet(self) -> None:
        generation = REPOSITORY_ROOT / "references/current/generations/V2.65"
        self.assertTrue(generation.is_dir(), "E_TEST_V265_CURRENT_GENERATION_MISSING")
        self.assertTrue(
            (generation / "contracts/release-command-manifest.json").is_file(),
            "E_TEST_V265_RELEASE_ROUTE_CONTRACT_MISSING",
        )

    def test_exact_facts_derived_receipt_and_closure_are_bound(self) -> None:
        result = self.validate()
        self.assertEqual(self.facts, result["project_route_facts"])
        self.assertEqual(
            self.derived["receipt_sha256"], result["derived_route_sha256"]
        )
        self.assertEqual("facts_derived", result["route_selection_mode"])
        self.assertEqual(ROUTE_ID, result["route_id"])

    def test_offline_missing_noncanonical_and_wrong_phase_fail_closed(self) -> None:
        offline = validate_declared_route_closure(
            self.root, self.generation, route_id=ROUTE_ID
        )
        development = release_facts(
            canonical_json_digest(self.facts_source),
            workflow_phase="development",
            implementation_scope_complete=False,
        )
        development_derived = derive_route(
            development, generation_id="V2.65"
        )
        for case in (
            {"closure_raw": canonical_raw(offline)},
            {"facts_raw": b""},
            {
                "facts_raw": json.dumps(
                    json.loads(self.facts_raw()), indent=2
                ).encode()
            },
            {
                "facts_raw": self.facts_raw(development),
                "derived_raw": canonical_raw(development_derived),
            },
            {"project_size": "large"},
        ):
            with self.subTest(case=tuple(case)):
                with self.assertRaises(RouteClosureError):
                    self.validate(**case)

    def test_resealed_tampered_closure_cannot_replace_recompile(self) -> None:
        attacked = copy.deepcopy(self.closure)
        attacked["loaded_rule_bytes"] += 1
        attacked["closure_digest"] = canonical_json_digest(
            {k: v for k, v in attacked.items() if k != "closure_digest"}
        )
        with self.assertRaises(RouteClosureError):
            self.validate(closure_raw=canonical_raw(attacked))


if __name__ == "__main__":
    unittest.main()
