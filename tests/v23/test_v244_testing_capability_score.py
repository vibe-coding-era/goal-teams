from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "checks" / "score-testing-capability.py"
MANIFEST = ROOT / "references" / "testing-capability-manifest.json"


def load_module():
    spec = importlib.util.spec_from_file_location("v244_score", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score_module = load_module()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestingCapabilityScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        discovered_commit = score_module.current_source_commit()
        self.source_commit = discovered_commit or ("0" * 40)
        self.commit_patch = mock.patch.object(
            score_module,
            "current_source_commit",
            return_value=self.source_commit,
        )
        self.commit_patch.start()
        self.addCleanup(self.commit_patch.stop)
        self.real_full_check_validator = score_module.validate_full_check_log
        self.real_benchmark_validator = score_module.validate_benchmark_summary
        self.full_check_patch = mock.patch.object(
            score_module, "validate_full_check_log", return_value=None
        )
        self.benchmark_patch = mock.patch.object(
            score_module, "validate_benchmark_summary", return_value=None
        )
        self.full_check_patch.start()
        self.benchmark_patch.start()
        self.addCleanup(self.full_check_patch.stop)
        self.addCleanup(self.benchmark_patch.stop)

    def make_bundle(self, root: Path, *, status: str = "passed") -> dict:
        proof = root / "proof.json"
        proof.write_text('{"observed":true}\n', encoding="utf-8")
        source_commit = self.source_commit
        modes = [
            ("reference", []),
            ("api_auth_bypass", ["API-AUTH-001"]),
            ("api_idempotency_broken", ["API-IDEMPOTENCY-001"]),
            ("api_concurrency_race", ["API-CONCURRENCY-001"]),
            ("api_eventual_consistency_stale", ["API-CONSISTENCY-001"]),
            ("e2e_session_lost", ["E2E-SESSION-001"]),
            ("e2e_double_click", ["E2E-DOUBLE-CLICK-001"]),
            ("e2e_refresh_drops_state", ["E2E-REFRESH-001"]),
            ("e2e_error_no_recovery", ["E2E-RECOVERY-001"]),
        ]
        benchmark_summary = {
            "schema_version": "goal-teams-testing-capability-self-check-v2.44",
            "status": "passed",
            "behavior_run": "executed",
            "reference_repeatable": True,
            "not_run_count_total": 0,
            "all_services_terminated": True,
            "candidate_runs": [
                {
                    "mode": mode,
                    "score": 10.0 if mode == "reference" else 9.0,
                    "not_run_count": 0,
                    "service_terminated": True,
                    "detected": expected,
                    "expected_detected_by": expected,
                    "score_ref": f"{mode}/score.json",
                    "evidence_ref": f"{mode}/evidence.json",
                }
                for mode, expected in modes
            ],
        }

        def materialize_suffix(suffix: str) -> dict[str, str]:
            path = root / suffix
            path.parent.mkdir(parents=True, exist_ok=True)
            if suffix.endswith("self-check-summary.json"):
                path.write_text(
                    json.dumps(benchmark_summary, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                for row in benchmark_summary["candidate_runs"]:
                    score_path = path.parent / row["score_ref"]
                    score_path.parent.mkdir(parents=True, exist_ok=True)
                    score_path.write_text(
                        json.dumps(
                            {
                                "provenance_verified": True,
                                "run_id": "00000000-0000-4000-8000-000000000000",
                                "score": row["score"],
                                "status": "complete",
                                "not_run_count": 0,
                                "canonical_manifest_sha256": (
                                    "3ace7d9b01e3ca08daf7eef294a5dbfc1c482805faf2426087e223c17bfb6cfe"
                                ),
                            },
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    evidence_path = path.parent / row["evidence_ref"]
                    evidence_path.write_text("{}\n", encoding="utf-8")
            elif not path.exists():
                source = ROOT / suffix
                if not source.is_file():
                    raise AssertionError(f"missing canonical test source: {suffix}")
                shutil.copyfile(source, path)
            return {"path": suffix, "sha256": digest(path)}

        check_refs = {}
        for check_id, suffixes in score_module.CHECK_EVIDENCE_SUFFIXES.items():
            check_refs[check_id] = [
                materialize_suffix(suffix) for suffix in suffixes
            ]

        full_log = root / score_module.FULL_CHECK_LOG_SUFFIX
        full_log.parent.mkdir(parents=True, exist_ok=True)
        full_log.write_text(
            "Ran 683 tests in 1.0s\nOK (skipped=15)\n"
            "Installer lifecycle checks passed\n",
            encoding="utf-8",
        )
        schema_log = root / score_module.SCHEMA_LOG_SUFFIX
        schema_log.write_text(
            "Ajv strict: 3 schemas and 4 canonical examples PASS\n",
            encoding="utf-8",
        )
        audit_path = root / score_module.COMPLETION_AUDIT_SUFFIX
        audit_path.write_text(
            json.dumps(
                {
                    "schema_version": (
                        "goal-teams-testing-capability-completion-audit-v2.44"
                    ),
                    "source_commit": source_commit,
                    "status": "passed",
                    "member_id": "completion-auditor-v244-test",
                    "run_id": "completion-audit-test-run",
                    "findings": [],
                    "resolved_issue_ids": sorted(score_module.REQUIRED_ISSUE_IDS),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        review_ref = {
            "path": score_module.COMPLETION_AUDIT_SUFFIX,
            "sha256": digest(audit_path),
        }
        benchmark_refs = [
            materialize_suffix(
                "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/"
                f"benchmark-final-{index}/self-check-summary.json"
            )
            for index in (1, 2)
        ]
        verification_path = root / score_module.VERIFICATION_SUFFIX
        verification_path.parent.mkdir(parents=True, exist_ok=True)
        verification_path.write_text(
            json.dumps(
                {
                    "schema_version": "goal-teams-testing-capability-verification-v2.44",
                    "product_version": "V2.44",
                    "source_commit": source_commit,
                    "full_check": {"status": "passed", "failed": 0, "errors": 0},
                    "schema_validation": {"status": "passed"},
                    "benchmark_replay": {
                        "status": "passed",
                        "runs": 2,
                        "not_run": 0,
                    },
                    "independent_review": {
                        "status": "passed",
                        "member_id": "completion-auditor-v244-test",
                        "run_id": "completion-audit-test-run",
                    },
                    "receipts": {
                        "full_check": {
                            "path": score_module.FULL_CHECK_LOG_SUFFIX,
                            "sha256": digest(full_log),
                        },
                        "schema_validation": {
                            "path": score_module.SCHEMA_LOG_SUFFIX,
                            "sha256": digest(schema_log),
                        },
                        "benchmark_runs": benchmark_refs,
                        "independent_review": review_ref,
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        dimensions = {
            dimension["id"]: {
                "checks": {
                    check_id: {
                        "status": status,
                        "evidence_refs": check_refs[check_id],
                    }
                    for check_id in dimension["required_checks"]
                }
            }
            for dimension in self.manifest["dimensions"]
        }
        ledger = root / "issues.jsonl"
        events = []
        for index, issue in enumerate(self.manifest["known_issues"], start=1):
            issue_refs = [
                materialize_suffix(suffix)
                for suffix in score_module.ISSUE_EVIDENCE_BY_ID[issue["id"]]
            ]
            events.append(
                {
                    "schema_version": score_module.ISSUE_SCHEMA,
                    "event_id": f"discovered-{index:03d}",
                    "issue_id": issue["id"],
                    "event_type": "discovered",
                    "dimension": issue["dimension"],
                    "summary": issue["summary"],
                    "severity": "high",
                    "status": "open",
                    "artifact_refs": [],
                    "evidence_refs": [],
                    "agent_run_id": "goal-lead",
                    "timestamp": "2026-07-23T00:00:00+08:00",
                }
            )
            events.append(
                {
                    "schema_version": score_module.ISSUE_SCHEMA,
                    "event_id": f"resolved-{index:03d}",
                    "issue_id": issue["id"],
                    "event_type": "resolved",
                    "dimension": issue["dimension"],
                    "summary": issue["summary"],
                    "severity": "high",
                    "status": "resolved",
                    "artifact_refs": [],
                    "evidence_refs": [review_ref, *issue_refs],
                    "agent_run_id": "completion-audit-test-run",
                    "timestamp": "2026-07-23T00:00:01+08:00",
                }
            )
        ledger.write_text(
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
            encoding="utf-8",
        )
        return {
            "schema_version": score_module.EVIDENCE_SCHEMA,
            "product_version": "V2.44",
            "source_commit": source_commit,
            "manifest_sha256": digest(MANIFEST),
            "verification_summary": {
                "path": score_module.VERIFICATION_SUFFIX,
                "sha256": digest(verification_path),
            },
            "issue_ledger": {"path": "issues.jsonl", "sha256": digest(ledger)},
            "dimensions": dimensions,
        }

    def test_all_validated_checks_and_resolved_issues_project_to_100(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            result = score_module.score(
                evidence,
                self.manifest,
                evidence_root=root,
                manifest_digest=digest(MANIFEST),
            )
        self.assertEqual("achieved", result["status"])
        self.assertEqual(100, result["score"])

    def test_missing_source_git_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            with mock.patch.object(
                score_module, "current_source_commit", return_value=None
            ):
                with self.assertRaisesRegex(
                    score_module.ScoreError, "not current HEAD"
                ):
                    score_module.score(
                        evidence,
                        self.manifest,
                        evidence_root=root,
                        manifest_digest=digest(MANIFEST),
                    )

    def test_not_run_check_earns_zero_for_the_whole_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            evidence["dimensions"]["e2e_testing"]["checks"][
                "e2e_reference_behavior"
            ]["status"] = "not_run"
            result = score_module.score(
                evidence,
                self.manifest,
                evidence_root=root,
                manifest_digest=digest(MANIFEST),
            )
        self.assertEqual("failed", result["status"])
        self.assertEqual(85, result["score"])

    def test_modified_rubric_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            weakened = json.loads(json.dumps(self.manifest))
            weakened["dimensions"] = [
                {
                    "id": "role_independence",
                    "name_zh": "伪造单项",
                    "weight": 100,
                    "required_checks": ["independent_test_roles"],
                }
            ]
            evidence["dimensions"] = {
                "role_independence": {
                    "checks": {
                        "independent_test_roles": {
                            "status": "passed",
                            "evidence_refs": [
                                {
                                    "path": "proof.json",
                                    "sha256": digest(root / "proof.json"),
                                }
                            ],
                        }
                    }
                }
            }
            with self.assertRaisesRegex(score_module.ScoreError, "canonical rubric"):
                score_module.score(
                    evidence,
                    weakened,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

    def test_digest_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            target = root / "schemas/v2.44/integration-test-plan.schema.json"
            target.write_text('{"observed":false}\n', encoding="utf-8")
            with self.assertRaisesRegex(score_module.ScoreError, "digest drift"):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

    def test_matching_path_with_semantically_empty_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            target = root / "schemas/v2.44/integration-test-plan.schema.json"
            target.write_text(
                '{"check_id":"integration_test_plan_schema"}\n',
                encoding="utf-8",
            )
            ref = evidence["dimensions"]["machine_contracts"]["checks"][
                "integration_test_plan_schema"
            ]["evidence_refs"][0]
            ref["sha256"] = digest(target)
            with self.assertRaisesRegex(
                score_module.ScoreError, "schema semantics"
            ):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

    def test_self_reported_verification_without_receipt_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            log = root / score_module.FULL_CHECK_LOG_SUFFIX
            log.write_text("passed\n", encoding="utf-8")
            with self.assertRaisesRegex(
                score_module.ScoreError, "incomplete or contains failures"
            ):
                self.real_full_check_validator(log, evidence["source_commit"])

    def test_empty_benchmark_evidence_cannot_prove_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_bundle(root)
            summary = (
                root
                / "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/"
                "benchmark-final-1/self-check-summary.json"
            )
            with self.assertRaisesRegex(
                score_module.ScoreError, "raw evidence cannot be recomputed"
            ):
                self.real_benchmark_validator(summary)

    def test_unrelated_file_cannot_prove_a_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            unrelated = root / "unrelated.json"
            unrelated.write_text('{"passed":true}\n', encoding="utf-8")
            evidence["dimensions"]["machine_contracts"]["checks"][
                "integration_test_plan_schema"
            ]["evidence_refs"] = [
                {"path": "unrelated.json", "sha256": digest(unrelated)}
            ]
            with self.assertRaisesRegex(score_module.ScoreError, "unrelated"):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

    def test_symlinked_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            proof = outside / "proof.json"
            proof.write_text('{"observed":true}\n', encoding="utf-8")
            (root / "alias").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(score_module.ScoreError, "contains symlink"):
                score_module.validate_ref(
                    root,
                    {"path": "alias/proof.json", "sha256": digest(proof)},
                )

    def test_unresolved_issue_prevents_achievement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            ledger = root / "issues.jsonl"
            events = [json.loads(line) for line in ledger.read_text().splitlines()]
            events.pop()
            ledger.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            evidence["issue_ledger"]["sha256"] = digest(ledger)
            result = score_module.score(
                evidence,
                self.manifest,
                evidence_root=root,
                manifest_digest=digest(MANIFEST),
            )
        self.assertEqual("failed", result["status"])
        self.assertEqual(100, result["score"])
        self.assertEqual(
            ["GT244-TEST-032"],
            result["issue_summary"]["unresolved_issue_ids"],
        )

    def test_resolved_only_history_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            ledger = root / "issues.jsonl"
            events = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
            ]
            ledger.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                    if event["event_type"] == "resolved"
                ),
                encoding="utf-8",
            )
            evidence["issue_ledger"]["sha256"] = digest(ledger)
            with self.assertRaisesRegex(score_module.ScoreError, "before discovery"):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

    def test_resolved_evidence_is_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            ledger = root / "issues.jsonl"
            events = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
            ]
            events[-1]["evidence_refs"] = ["proof.json"]
            ledger.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            evidence["issue_ledger"]["sha256"] = digest(ledger)
            with self.assertRaisesRegex(score_module.ScoreError, "evidence ref"):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

    def test_resolved_issue_requires_issue_specific_independent_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            ledger = root / "issues.jsonl"
            events = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
            ]
            target = next(
                event
                for event in events
                if event["issue_id"] == "GT244-TEST-027"
                and event["event_type"] == "resolved"
            )
            review_ref = target["evidence_refs"][0]
            unrelated = root / "scripts/checks/score-testing-capability.py"
            target["evidence_refs"] = [
                review_ref,
                {
                    "path": "scripts/checks/score-testing-capability.py",
                    "sha256": digest(unrelated),
                },
            ]
            ledger.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            evidence["issue_ledger"]["sha256"] = digest(ledger)
            with self.assertRaisesRegex(
                score_module.ScoreError, "issue-specific independent"
            ):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

    def test_issue_metadata_must_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = self.make_bundle(root)
            ledger = root / "issues.jsonl"
            events = [
                json.loads(line)
                for line in ledger.read_text(encoding="utf-8").splitlines()
            ]
            events[0]["dimension"] = "e2e_testing"
            ledger.write_text(
                "".join(
                    json.dumps(event, separators=(",", ":")) + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            evidence["issue_ledger"]["sha256"] = digest(ledger)
            with self.assertRaisesRegex(score_module.ScoreError, "metadata mismatch"):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )


if __name__ == "__main__":
    unittest.main()
