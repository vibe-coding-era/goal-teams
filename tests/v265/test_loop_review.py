from __future__ import annotations

import copy
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

ZERO_SHA256 = "0" * 64
SHA = {letter: letter * 64 for letter in "abcdef0123456789"}
TASK_EXACT_SET_SHA256 = "24eb97b2048a795cbeeb459c6ceabbb3f1476f3baa36ee08cdb0a4d6fde8a4f5"
DIMENSION_NAMES = (
    "prompt",
    "context",
    "skill",
    "graph",
    "materials",
    "harness",
    "evidence",
    "members",
    "tools",
    "workflow",
    "runtime",
    "cost",
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _target(module_name: str) -> Any:
    """Keep case discovery positive while candidate implementation is absent."""

    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == module_name or missing.startswith("scripts.v265"):
            raise AssertionError(
                f"E_TEST_V265_TARGET_MISSING:{module_name}"
            ) from exc
        raise


def _no_finding_dimension() -> dict[str, object]:
    return {
        "state": "no_finding",
        "finding": None,
        "evidence_refs": [],
        "improvement": None,
        "expected_benefit": None,
        "validation_method": None,
        "risk": None,
    }


def _dimensions() -> dict[str, object]:
    return {name: _no_finding_dimension() for name in DIMENSION_NAMES}


def _review(
    *,
    loop_round: int,
    sequence: int,
    trigger: str,
    previous_review_sha256: str,
    issue_key: str | None = None,
    review_outcome: str = "no_change",
    status: str = "closed",
) -> dict[str, object]:
    loop_id = "LOOP-V265-USER-1"
    review = {
        "schema_version": "goal-teams-loop-review-v2.65",
        "review_id": f"LOOP-REVIEW-{loop_id}-R{loop_round}-{sequence}",
        "trigger": trigger,
        "project_id": "user-project-v265",
        "artifact_version": "V2.65",
        "skill_version": "V2.65-candidate",
        "loop_id": loop_id,
        "loop_round": loop_round,
        "sequence": sequence,
        "occurred_at": f"2026-08-22T10:{sequence:02d}:00Z",
        "graph_revision": 1,
        "plan_revision": 6,
        "task_exact_set_sha256": TASK_EXACT_SET_SHA256,
        "source_revision": "candidate:c145b713",
        "task_refs": ["GT265-04"],
        "evidence_refs": [f"evidence:review:{sequence}"],
        "issue_key": issue_key,
        "loop_result": {
            "decision": "continue" if loop_round == 1 else "stop",
            "achieved": False,
            "blocked_items": [],
            "failed_items": [],
            "not_run_items": ["runtime_business_validation"],
            "open_gaps": ["runtime_business_validation"],
        },
        "observed_facts": ["current Development evidence was reviewed"],
        "assumptions": [],
        "uncertainty": ["real Host execution remains not_run"],
        "retained_practices": ["preserve immutable test bytes"],
        "root_cause_primary": "unknown" if trigger == "loop_end" else "context",
        "root_cause_secondary": [],
        "dimensions": _dimensions(),
        "candidate": None,
        "review_outcome": review_outcome,
        "status": status,
        "previous_review_sha256": previous_review_sha256,
    }
    if trigger != "loop_end":
        review["dimensions"]["context"] = {
            "state": "observed",
            "finding": "the same stale context was observed",
            "evidence_refs": [f"evidence:context:{sequence}"],
            "improvement": None,
            "expected_benefit": None,
            "validation_method": None,
            "risk": "stale context can misroute work",
        }
    return review


def _skill_candidate() -> dict[str, object]:
    review = _review(
        loop_round=1,
        sequence=1,
        trigger="problem_detected",
        previous_review_sha256=ZERO_SHA256,
        issue_key="skill trigger accepted ambiguous runtime intent",
        review_outcome="skill_improvement_candidate",
        status="candidate_only",
    )
    review["root_cause_primary"] = "skill"
    review["dimensions"]["context"] = _no_finding_dimension()
    review["dimensions"]["skill"] = {
        "state": "candidate",
        "finding": "runtime trigger was ambiguous",
        "evidence_refs": ["evidence:route:false-positive"],
        "improvement": "require an observed runtime capability fact",
        "expected_benefit": "fewer false runtime routes",
        "validation_method": "compare the fixed route denominator",
        "risk": "older callers remain unverified",
    }
    review["candidate"] = {
        "candidate_id": "CANDIDATE-SKILL-1",
        "consumer_refs": ["consumer:v265-user"],
        "scope_allowlist": ["SKILL.md:runtime-trigger"],
        "risk": "route compatibility may narrow",
        "budget_wu": 2,
        "validation_plan": "baseline/candidate route fixture comparison",
        "rollback_condition": "candidate regresses a required route",
        "required_authorization": "separate_skill_improvement_task",
    }
    return review


def _compiled_graph(*, context_tokens: int = 512) -> dict[str, object]:
    def resource(resource_id: str) -> dict[str, object]:
        payload = f"bytes:{resource_id}".encode("utf-8")
        return {
            "resource_id": resource_id,
            "resource_type": "repository_file",
            "source_ref": f"tests/v265/resources/{resource_id.replace(':', '-')}.txt",
            "revision": "revision:1",
            "expected_sha256": hashlib.sha256(payload).hexdigest(),
            "schema_ref": "schema:context:v1",
            "freshness_policy": {"mode": "max_age", "max_age_seconds": 60},
            "sensitivity": "internal",
            "permission_ref": f"permission:{resource_id}",
            "token_budget": 128,
            "producer_node_id": None,
            "consumer_node_ids": ["A"] if resource_id.endswith(":required") else [],
        }

    normalized = {
        "schema_version": "goal-teams-graph-contract-v2.65",
        "graph_id": "GRAPH-V265-CONTEXT-FIXTURE",
        "graph_revision": 1,
        "plan_binding": {
            "plan_id": "GT-V265-CONTEXT-FIXTURE",
            "plan_revision": 6,
            "task_exact_set_sha256": TASK_EXACT_SET_SHA256,
            "compiled_task_plan_sha256": SHA["b"],
            "task_plan_validation_sha256": SHA["c"],
        },
        "supersedes_graph_sha256": None,
        "nodes": [
            {
                "node_id": "A",
                "task_refs": ["TASK-A"],
                "node_type": "action",
                "owner_identity": "owner:A",
                "validator_identity": "validator:A",
                "action_ref": "action:A",
                "resource_refs": {
                    "required": ["resource:A:required"],
                    "recommended": [],
                    "generated": [],
                    "upstream_artifacts": [],
                    "forbidden": ["resource:A:forbidden"],
                },
                "input_ports": [],
                "output_ports": [],
                "scope_allowlist": ["scope/A/**"],
                "forbidden_scope": ["README.md", "release/**"],
                "budget": {
                    "work_units": 1,
                    "attempts": 1,
                    "revalidations": 0,
                    "context_tokens": context_tokens,
                },
                "timeout_seconds": 30,
                "retry_policy": {
                    "max_attempts": 1,
                    "retryable_outcomes": [],
                    "backoff_seconds": [],
                },
                "gate_refs": [],
                "exit_condition_ref": "exit:TASK-A",
                "recovery_policy": {"mode": "none", "edge_id": None},
                "fan_in": None,
            }
        ],
        "edges": [],
        "resources": [
            resource("resource:A:forbidden"),
            resource("resource:A:required"),
        ],
        "gates": [],
        "actions": [
            {
                "action_id": "action:A",
                "runner": "host_adapter",
                "effect": "read",
                "tool_allowlist": ["callback"],
                "network_policy": "deny",
                "workspace_policy": "read_only",
                "input_schema_ref": "schema:action:A:input",
                "output_schema_ref": "schema:action:A:output",
                "idempotency_required": False,
            }
        ],
    }
    compiled_graph = {
        **normalized,
        "task_node_map": {"TASK-A": "A"},
        "predecessor_map": {"A": []},
        "fan_in_map": {"A": None},
        "topological_order": ["A"],
        "ready_roots": ["A"],
        "execution_edge_ids": [],
        "lineage_edge_ids": [],
        "graph_contract_sha256": _canonical_sha256(normalized),
    }
    compiled_graph["receipt_sha256"] = _canonical_sha256(compiled_graph)
    return compiled_graph


def _resource_observation(
    resource: dict[str, object],
    payload: bytes,
    *,
    fetched_at: str = "2026-08-22T10:00:00Z",
    permission_ref: str | None = None,
) -> dict[str, object]:
    return {
        "resource_id": resource["resource_id"],
        "observed_revision": resource["revision"],
        "observed_sha256": hashlib.sha256(payload).hexdigest(),
        "fetched_at": fetched_at,
        "permission_ref": permission_ref or resource["permission_ref"],
        "producer_receipt_sha256": (
            SHA["b"] if resource["resource_type"] == "upstream_artifact" else None
        ),
    }


class TestV265LoopReviewAndContext(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temp.name).resolve() / "user-project"
        self.project_root.mkdir()
        self.relative_path = "GoalTeamsWork/versions/V2.65/loop-review.md"
        self.review_path = self.project_root / self.relative_path

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build(self, review: dict[str, object]) -> tuple[Any, dict[str, object]]:
        module = _target("scripts.v265.loop_review")
        built = module.build_loop_review(review)
        validated = module.validate_loop_review(built)
        self.assertEqual(built, validated)
        self.assertRegex(built["issue_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertRegex(built["review_sha256"], r"^[0-9a-f]{64}$")
        return module, built

    def _append(
        self,
        module: Any,
        review: dict[str, object],
        *,
        previous_file_sha256: str,
        state_revision: int,
    ) -> dict[str, object]:
        return module.append_loop_review(
            self.project_root,
            self.relative_path,
            review,
            expected_previous_file_sha256=previous_file_sha256,
            expected_state_revision=state_revision,
        )

    def test_round_requires_one_final_loop_end_or_incomplete_review(self) -> None:
        module, problem = self._build(
            _review(
                loop_round=1,
                sequence=1,
                trigger="problem_detected",
                previous_review_sha256=ZERO_SHA256,
                issue_key="stale context entered the node",
                review_outcome="observed_only",
                status="open",
            )
        )
        with self.assertRaises(module.LoopReviewError) as caught:
            module.validate_round_review(
                [problem],
                loop_id="LOOP-V265-USER-1",
                loop_round=1,
            )
        self.assertEqual("E_V265_REVIEW_REQUIRED", caught.exception.code)

        module, loop_end = self._build(
            _review(
                loop_round=1,
                sequence=2,
                trigger="loop_end",
                previous_review_sha256=problem["review_sha256"],
            )
        )
        round_receipt = module.validate_round_review(
            [problem, loop_end],
            loop_id="LOOP-V265-USER-1",
            loop_round=1,
        )
        self.assertEqual(
            {
                "schema_version",
                "loop_id",
                "loop_round",
                "review_ids",
                "loop_end_review_id",
                "valid",
                "receipt_sha256",
            },
            set(round_receipt),
        )
        self.assertTrue(round_receipt["valid"])
        self.assertEqual(loop_end["review_id"], round_receipt["loop_end_review_id"])

        incomplete = _review(
            loop_round=2,
            sequence=3,
            trigger="loop_end",
            previous_review_sha256=loop_end["review_sha256"],
            status="review_incomplete",
        )
        incomplete["observed_facts"] = ["review generation failed"]
        incomplete["evidence_refs"] = ["evidence:review-generation-failure"]
        _, incomplete_built = self._build(incomplete)
        self.assertTrue(
            module.validate_round_review(
                [incomplete_built],
                loop_id="LOOP-V265-USER-1",
                loop_round=2,
            )["valid"]
        )

    def test_fingerprint_is_stable_across_rounds_and_duplicate_issue_is_rejected(self) -> None:
        module, first = self._build(
            _review(
                loop_round=1,
                sequence=1,
                trigger="problem_detected",
                previous_review_sha256=ZERO_SHA256,
                issue_key="stale context entered the node",
                review_outcome="observed_only",
                status="open",
            )
        )
        module, recurrence = self._build(
            _review(
                loop_round=2,
                sequence=2,
                trigger="problem_detected",
                previous_review_sha256=first["review_sha256"],
                issue_key="stale context entered the node",
                review_outcome="observed_only",
                status="open",
            )
        )
        self.assertEqual(first["issue_fingerprint"], recurrence["issue_fingerprint"])
        receipt = self._append(
            module,
            first,
            previous_file_sha256=ZERO_SHA256,
            state_revision=0,
        )
        before = self.review_path.read_bytes()
        with self.assertRaises(module.LoopReviewError) as caught:
            self._append(
                module,
                recurrence,
                previous_file_sha256=receipt["file_sha256_after"],
                state_revision=1,
            )
        self.assertEqual("E_V265_REVIEW_DUPLICATE_ISSUE", caught.exception.code)
        self.assertEqual(before, self.review_path.read_bytes())

    def test_all_twelve_dimensions_are_exact_and_explicit(self) -> None:
        _, built = self._build(
            _review(
                loop_round=1,
                sequence=1,
                trigger="loop_end",
                previous_review_sha256=ZERO_SHA256,
            )
        )
        self.assertEqual(set(DIMENSION_NAMES), set(built["dimensions"]))
        for name in DIMENSION_NAMES:
            self.assertEqual("no_finding", built["dimensions"][name]["state"])

        module = _target("scripts.v265.loop_review")
        missing = _review(
            loop_round=1,
            sequence=1,
            trigger="loop_end",
            previous_review_sha256=ZERO_SHA256,
        )
        missing["dimensions"].pop("prompt")
        with self.assertRaises(module.LoopReviewError) as caught:
            module.build_loop_review(missing)
        self.assertEqual("E_V265_REVIEW_SCHEMA", caught.exception.code)

        hidden_reasoning = _review(
            loop_round=1,
            sequence=1,
            trigger="loop_end",
            previous_review_sha256=ZERO_SHA256,
        )
        hidden_reasoning["chain_of_thought"] = "forbidden private reasoning"
        with self.assertRaises(module.LoopReviewError) as caught:
            module.build_loop_review(hidden_reasoning)
        self.assertEqual("E_V265_REVIEW_SCHEMA", caught.exception.code)

    def test_candidate_outcome_is_consistent_and_never_auto_applies_skill(self) -> None:
        _, built = self._build(_skill_candidate())
        self.assertEqual("skill_improvement_candidate", built["review_outcome"])
        self.assertEqual("candidate_only", built["status"])
        self.assertEqual(
            "separate_skill_improvement_task",
            built["candidate"]["required_authorization"],
        )
        self.assertEqual("candidate", built["dimensions"]["skill"]["state"])

        module = _target("scripts.v265.loop_review")
        contradictory = _skill_candidate()
        contradictory["candidate"] = None
        with self.assertRaises(module.LoopReviewError) as caught:
            module.build_loop_review(contradictory)
        self.assertEqual("E_V265_REVIEW_CANDIDATE", caught.exception.code)

        auto_apply = _skill_candidate()
        auto_apply["candidate"]["apply_now"] = True
        with self.assertRaises(module.LoopReviewError) as caught:
            module.build_loop_review(auto_apply)
        self.assertEqual("E_V265_REVIEW_SCHEMA", caught.exception.code)

        for deferred_status in ("experimenting", "adopted"):
            with self.subTest(status=deferred_status):
                deferred = _skill_candidate()
                deferred["status"] = deferred_status
                with self.assertRaises(module.LoopReviewError) as caught:
                    module.build_loop_review(deferred)
                self.assertEqual("E_V265_REVIEW_SCHEMA", caught.exception.code)

    def test_markdown_append_is_prefix_preserving_cas_guarded_and_project_local(self) -> None:
        module, first = self._build(
            _review(
                loop_round=1,
                sequence=1,
                trigger="loop_end",
                previous_review_sha256=ZERO_SHA256,
            )
        )
        receipt1 = self._append(
            module,
            first,
            previous_file_sha256=ZERO_SHA256,
            state_revision=0,
        )
        first_bytes = self.review_path.read_bytes()
        self.assertTrue(first_bytes.startswith(b"# LOOP Review\n\n"))
        self.assertEqual(ZERO_SHA256, receipt1["file_sha256_before"])
        self.assertEqual(hashlib.sha256(first_bytes).hexdigest(), receipt1["file_sha256_after"])
        self.assertEqual(1, receipt1["state_revision_after"])

        module, second = self._build(
            _review(
                loop_round=2,
                sequence=2,
                trigger="loop_end",
                previous_review_sha256=first["review_sha256"],
            )
        )
        receipt2 = self._append(
            module,
            second,
            previous_file_sha256=receipt1["file_sha256_after"],
            state_revision=1,
        )
        self.assertTrue(self.review_path.read_bytes().startswith(first_bytes))
        self.assertEqual(2, receipt2["state_revision_after"])

        with self.assertRaises(module.LoopReviewError) as caught:
            self._append(
                module,
                second,
                previous_file_sha256=ZERO_SHA256,
                state_revision=1,
            )
        self.assertEqual("E_V265_REVIEW_APPEND_CAS", caught.exception.code)

        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        with self.assertRaises(module.LoopReviewError) as caught:
            module.append_loop_review(
                self.project_root,
                "../outside/loop-review.md",
                second,
                expected_previous_file_sha256=ZERO_SHA256,
                expected_state_revision=0,
            )
        self.assertEqual("E_V265_REVIEW_PATH", caught.exception.code)

    def test_duplicate_loop_end_and_markdown_sidecar_crash_drift_fail_closed(self) -> None:
        module, first = self._build(
            _review(
                loop_round=1,
                sequence=1,
                trigger="loop_end",
                previous_review_sha256=ZERO_SHA256,
            )
        )
        receipt = self._append(
            module,
            first,
            previous_file_sha256=ZERO_SHA256,
            state_revision=0,
        )
        duplicate_input = _review(
            loop_round=1,
            sequence=2,
            trigger="loop_end",
            previous_review_sha256=first["review_sha256"],
        )
        duplicate_input["review_id"] = "LOOP-REVIEW-LOOP-V265-USER-1-R1-2"
        module, duplicate = self._build(duplicate_input)
        with self.assertRaises(module.LoopReviewError) as caught:
            self._append(
                module,
                duplicate,
                previous_file_sha256=receipt["file_sha256_after"],
                state_revision=1,
            )
        self.assertEqual("E_V265_REVIEW_DUPLICATE_LOOP_END", caught.exception.code)

        with self.review_path.open("ab") as handle:
            handle.write(b"\n<!-- incomplete crash frame -->\n")
        with self.assertRaises(module.LoopReviewError) as caught:
            module.reconcile_loop_review(self.project_root, self.relative_path)
        self.assertEqual("E_V265_REVIEW_STATE_DRIFT", caught.exception.code)

    def test_capsule_selects_only_validated_reviews_and_enforces_item_and_byte_budgets(self) -> None:
        loop_review = _target("scripts.v265.loop_review")
        context = _target("scripts.v265.context_compiler")
        first = loop_review.build_loop_review(
            _review(
                loop_round=1,
                sequence=1,
                trigger="loop_end",
                previous_review_sha256=ZERO_SHA256,
            )
        )
        active_input = _skill_candidate()
        active_input["sequence"] = 2
        active_input["review_id"] = "LOOP-REVIEW-LOOP-V265-USER-1-R1-2"
        active_input["previous_review_sha256"] = first["review_sha256"]
        active_input["observed_facts"] = ["FULL-HISTORY-MARKER-MUST-NOT-LEAK"]
        active = loop_review.build_loop_review(active_input)
        capsule = context.compile_review_capsule(
            [first, active],
            capsule_id="CAPSULE-V265-1",
            active_review_ids=[active["review_id"]],
            max_items=20,
            max_bytes=4096,
            compiled_at="2026-08-22T10:30:00Z",
        )
        self.assertEqual(
            {
                "schema_version",
                "capsule_id",
                "source_review_ids",
                "source_review_sha256s",
                "retained_practices",
                "active_adjustments",
                "open_gaps",
                "forbidden_retries",
                "required_evidence",
                "compiled_at",
                "capsule_sha256",
            },
            set(capsule),
        )
        self.assertEqual([active["review_id"]], capsule["source_review_ids"])
        self.assertNotIn(
            "FULL-HISTORY-MARKER-MUST-NOT-LEAK",
            json.dumps(capsule, ensure_ascii=False, sort_keys=True),
        )
        budget_cases = (
            ("items", 1, 4096),
            ("bytes", 20, 32),
        )
        for name, max_items, max_bytes in budget_cases:
            with self.subTest(capsule_budget=name):
                with self.assertRaises(context.ContextCompilerError) as caught:
                    context.compile_review_capsule(
                        [first, active],
                        capsule_id=f"CAPSULE-V265-{name.upper()}",
                        active_review_ids=[active["review_id"]],
                        max_items=max_items,
                        max_bytes=max_bytes,
                        compiled_at="2026-08-22T10:30:00Z",
                    )
                self.assertEqual(
                    "E_V265_REVIEW_CAPSULE_BUDGET",
                    caught.exception.code,
                )

        tampered = copy.deepcopy(active)
        tampered["observed_facts"] = ["tampered after review signing"]
        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_review_capsule(
                [tampered],
                capsule_id="CAPSULE-V265-TAMPERED",
                active_review_ids=[tampered["review_id"]],
                max_items=20,
                max_bytes=4096,
                compiled_at="2026-08-22T10:30:00Z",
            )
        self.assertEqual("E_V265_CONTEXT_CAPSULE", caught.exception.code)

        unsigned = _skill_candidate()
        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_review_capsule(
                [unsigned],
                capsule_id="CAPSULE-V265-UNVALIDATED",
                active_review_ids=[unsigned["review_id"]],
                max_items=20,
                max_bytes=4096,
                compiled_at="2026-08-22T10:30:00Z",
            )
        self.assertEqual("E_V265_CONTEXT_CAPSULE", caught.exception.code)

    def test_context_bundle_is_declared_current_permitted_digest_bound_and_budgeted(self) -> None:
        context = _target("scripts.v265.context_compiler")
        graph = _compiled_graph()
        required = next(
            resource
            for resource in graph["resources"]
            if resource["resource_id"] == "resource:A:required"
        )
        payload = b"bytes:resource:A:required"
        payloads = {required["resource_id"]: payload}
        observations = {
            required["resource_id"]: _resource_observation(required, payload)
        }
        bundle = context.compile_context_bundle(
            bundle_id="BUNDLE-CONTEXT-A",
            compiled_graph=graph,
            node_id="A",
            resource_payloads=payloads,
            resource_observations=observations,
            review_capsule=None,
            compiled_at="2026-08-22T10:00:30Z",
        )
        validation = context.validate_context_bundle(
            bundle,
            compiled_graph=graph,
            node_id="A",
            validated_at="2026-08-22T10:00:45Z",
        )
        self.assertTrue(validation["valid"])
        self.assertEqual((len(payload) + 3) // 4, bundle["estimated_tokens"])

        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_context_bundle(
                bundle_id="BUNDLE-DIGEST-DRIFT",
                compiled_graph=graph,
                node_id="A",
                resource_payloads={required["resource_id"]: b"tampered payload"},
                resource_observations=observations,
                review_capsule=None,
                compiled_at="2026-08-22T10:00:30Z",
            )
        self.assertEqual("E_V265_CONTEXT_DIGEST", caught.exception.code)

        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_context_bundle(
                bundle_id="BUNDLE-MISSING",
                compiled_graph=graph,
                node_id="A",
                resource_payloads={},
                resource_observations={},
                review_capsule=None,
                compiled_at="2026-08-22T10:00:30Z",
            )
        self.assertEqual("E_V265_CONTEXT_RESOURCE_MISSING", caught.exception.code)

        undeclared_payload = b"undeclared"
        undeclared_observation = {
            "resource_id": "resource:undeclared",
            "observed_revision": "revision:1",
            "observed_sha256": hashlib.sha256(undeclared_payload).hexdigest(),
            "fetched_at": "2026-08-22T10:00:00Z",
            "permission_ref": "permission:undeclared",
            "producer_receipt_sha256": None,
        }
        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_context_bundle(
                bundle_id="BUNDLE-UNDECLARED",
                compiled_graph=graph,
                node_id="A",
                resource_payloads={**payloads, "resource:undeclared": undeclared_payload},
                resource_observations={
                    **observations,
                    "resource:undeclared": undeclared_observation,
                },
                review_capsule=None,
                compiled_at="2026-08-22T10:00:30Z",
            )
        self.assertEqual("E_V265_CONTEXT_UNDECLARED_RESOURCE", caught.exception.code)

        forbidden = next(
            resource
            for resource in graph["resources"]
            if resource["resource_id"] == "resource:A:forbidden"
        )
        forbidden_payload = b"bytes:resource:A:forbidden"
        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_context_bundle(
                bundle_id="BUNDLE-FORBIDDEN",
                compiled_graph=graph,
                node_id="A",
                resource_payloads={**payloads, forbidden["resource_id"]: forbidden_payload},
                resource_observations={
                    **observations,
                    forbidden["resource_id"]: _resource_observation(
                        forbidden, forbidden_payload
                    ),
                },
                review_capsule=None,
                compiled_at="2026-08-22T10:00:30Z",
            )
        self.assertEqual("E_V265_CONTEXT_FORBIDDEN_RESOURCE", caught.exception.code)

        stale_observations = copy.deepcopy(observations)
        stale_observations[required["resource_id"]]["fetched_at"] = "2026-08-22T09:00:00Z"
        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_context_bundle(
                bundle_id="BUNDLE-STALE",
                compiled_graph=graph,
                node_id="A",
                resource_payloads=payloads,
                resource_observations=stale_observations,
                review_capsule=None,
                compiled_at="2026-08-22T10:00:30Z",
            )
        self.assertEqual("E_V265_CONTEXT_STALE", caught.exception.code)

        denied_observations = copy.deepcopy(observations)
        denied_observations[required["resource_id"]]["permission_ref"] = "permission:other"
        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_context_bundle(
                bundle_id="BUNDLE-DENIED",
                compiled_graph=graph,
                node_id="A",
                resource_payloads=payloads,
                resource_observations=denied_observations,
                review_capsule=None,
                compiled_at="2026-08-22T10:00:30Z",
            )
        self.assertEqual("E_V265_CONTEXT_PERMISSION", caught.exception.code)

        tiny_graph = _compiled_graph(context_tokens=1)
        tiny_required = next(
            resource
            for resource in tiny_graph["resources"]
            if resource["resource_id"] == "resource:A:required"
        )
        with self.assertRaises(context.ContextCompilerError) as caught:
            context.compile_context_bundle(
                bundle_id="BUNDLE-TOO-LARGE",
                compiled_graph=tiny_graph,
                node_id="A",
                resource_payloads={tiny_required["resource_id"]: payload},
                resource_observations={
                    tiny_required["resource_id"]: _resource_observation(
                        tiny_required, payload
                    )
                },
                review_capsule=None,
                compiled_at="2026-08-22T10:00:30Z",
            )
        self.assertEqual("E_V265_CONTEXT_TOKEN_BUDGET", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
