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
    value: dict[str, object] = {
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


class TestV263ReleasedRuntimeRouteTriplet(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rule_path = "references/current/generations/V2.63/core.md"
        raw = b"# V2.63 test rule\n"
        path = self.root / self.rule_path
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)

        self.facts_source = {
            "schema_version": "goal-teams-project-route-facts-source-v2.63",
            "repository": "vibe-coding-era/goal-teams",
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "workflow_run_id": "100",
            "workflow_run_attempt": "1",
            "project_start_authorization_receipt_sha256": "3" * 64,
        }
        self.facts = release_facts(canonical_json_digest(self.facts_source))
        self.derived = derive_route(self.facts)
        owner = {
            "owner_id": "core",
            "path": self.rule_path,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "owned_rule_ids": ["GT263-TEST-RULE"],
            "route_membership": [ROUTE_ID],
            "dependencies": [],
        }
        self.generation = {
            "generation_id": "V2.63",
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

    def validate(
        self,
        *,
        facts_raw: bytes | None = None,
        derived_raw: bytes | None = None,
        closure_raw: bytes | None = None,
        project_size: str = "medium",
    ) -> dict[str, object]:
        return validate_released_runtime_route_triplet(
            self.root,
            self.generation,
            project_route_facts_raw=(
                self.facts_raw() if facts_raw is None else facts_raw
            ),
            derived_route_receipt_raw=(
                canonical_raw(self.derived) if derived_raw is None else derived_raw
            ),
            route_closure_raw=(
                canonical_raw(self.closure) if closure_raw is None else closure_raw
            ),
            expected_stage="released",
            expected_workflow_phase="release",
            expected_project_size=project_size,
            expected_route_id=(
                "V250-ROUTE-LARGE-RELEASE"
                if project_size == "large"
                else ROUTE_ID
            ),
        )

    def test_exact_facts_derived_receipt_and_facts_derived_closure_are_bound(self) -> None:
        result = self.validate()

        self.assertEqual(self.facts, result["project_route_facts"])
        self.assertEqual(
            canonical_json_digest(self.facts), result["project_route_facts_sha256"]
        )
        self.assertEqual(
            self.derived["receipt_sha256"], result["derived_route_sha256"]
        )
        self.assertEqual("facts_derived", result["route_selection_mode"])
        self.assertEqual(ROUTE_ID, result["route_id"])

    def test_offline_missing_and_non_normalized_evidence_fail_closed(self) -> None:
        offline = validate_declared_route_closure(
            self.root, self.generation, route_id=ROUTE_ID
        )
        cases = (
            {"closure_raw": canonical_raw(offline)},
            {"facts_raw": b""},
            {"derived_raw": b""},
            {
                "facts_raw": json.dumps(
                    json.loads(self.facts_raw()), ensure_ascii=False, indent=2
                ).encode("utf-8")
            },
        )
        for case in cases:
            with self.subTest(case=tuple(case)):
                with self.assertRaises(RouteClosureError):
                    self.validate(**case)

    def test_stage_phase_size_and_expected_route_mismatch_fail_closed(self) -> None:
        stage_facts = release_facts(
            canonical_json_digest(self.facts_source), stage="candidate"
        )
        stage_derived = derive_route(stage_facts)
        stage_closure = compile_derived_route_closure(
            self.root, self.generation, stage_derived
        )
        with self.assertRaises(RouteClosureError):
            self.validate(
                facts_raw=self.facts_raw(stage_facts),
                derived_raw=canonical_raw(stage_derived),
                closure_raw=canonical_raw(stage_closure),
            )

        development_facts = release_facts(
            canonical_json_digest(self.facts_source),
            workflow_phase="development",
            implementation_scope_complete=False,
        )
        development_derived = derive_route(development_facts)
        with self.assertRaises(RouteClosureError):
            self.validate(
                facts_raw=self.facts_raw(development_facts),
                derived_raw=canonical_raw(development_derived),
            )

        with self.assertRaises(RouteClosureError):
            self.validate(project_size="large")

    def test_resealed_tampered_closure_cannot_replace_exact_recompile(self) -> None:
        attacked = copy.deepcopy(self.closure)
        attacked["loaded_rule_bytes"] += 1
        attacked["closure_digest"] = canonical_json_digest(
            {
                key: value
                for key, value in attacked.items()
                if key != "closure_digest"
            }
        )

        with self.assertRaises(RouteClosureError):
            self.validate(closure_raw=canonical_raw(attacked))


if __name__ == "__main__":
    unittest.main()
