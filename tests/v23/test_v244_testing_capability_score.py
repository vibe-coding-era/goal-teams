from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


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

    def make_bundle(self, root: Path, *, status: str = "passed") -> dict:
        proof = root / "proof.json"
        proof.write_text('{"observed":true}\n', encoding="utf-8")
        ref = {"path": "proof.json", "sha256": digest(proof)}
        benchmark_summary = {
            "schema_version": "goal-teams-testing-capability-self-check-v2.44",
            "status": "passed",
            "behavior_run": "executed",
            "reference_repeatable": True,
            "not_run_count_total": 0,
            "all_services_terminated": True,
            "candidate_runs": [
                {
                    "mode": "reference",
                    "score": 10.0,
                    "not_run_count": 0,
                    "service_terminated": True,
                    "detected": [],
                    "expected_detected_by": [],
                },
                *[
                    {
                        "mode": f"defect-{index}",
                        "score": 9.0,
                        "not_run_count": 0,
                        "service_terminated": True,
                        "detected": [f"DEFECT-{index}"],
                        "expected_detected_by": [f"DEFECT-{index}"],
                    }
                    for index in range(1, 9)
                ],
            ],
        }
        check_refs = {}
        for check_id, suffixes in score_module.CHECK_EVIDENCE_SUFFIXES.items():
            refs = []
            for suffix in suffixes:
                path = root / suffix
                path.parent.mkdir(parents=True, exist_ok=True)
                if suffix.endswith("self-check-summary.json"):
                    path.write_text(
                        json.dumps(benchmark_summary, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif not path.exists():
                    path.write_text(
                        json.dumps({"check_id": check_id}, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                refs.append({"path": suffix, "sha256": digest(path)})
            check_refs[check_id] = refs
        verification_path = root / score_module.VERIFICATION_SUFFIX
        verification_path.parent.mkdir(parents=True, exist_ok=True)
        verification_path.write_text(
            json.dumps(
                {
                    "schema_version": "goal-teams-testing-capability-verification-v2.44",
                    "product_version": "V2.44",
                    "source_commit": "b" * 40,
                    "full_check": {"status": "passed", "failed": 0, "errors": 0},
                    "schema_validation": {"status": "passed"},
                    "benchmark_replay": {
                        "status": "passed",
                        "runs": 2,
                        "not_run": 0,
                    },
                    "independent_review": {
                        "status": "passed",
                        "member_id": "independent-reviewer",
                        "run_id": "review-run-1",
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
                    "evidence_refs": [ref],
                    "agent_run_id": "independent-reviewer",
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
            "source_commit": "b" * 40,
            "manifest_sha256": digest(MANIFEST),
            "verification_summary": {
                "path": score_module.VERIFICATION_SUFFIX,
                "sha256": digest(verification_path),
            },
            "issue_ledger": {"path": "issues.jsonl", "sha256": digest(ledger)},
            "dimensions": dimensions,
        }

    def test_all_checks_and_resolved_issues_achieve_100(self) -> None:
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
            (root / "proof.json").write_text('{"observed":false}\n', encoding="utf-8")
            with self.assertRaisesRegex(score_module.ScoreError, "digest drift"):
                score_module.score(
                    evidence,
                    self.manifest,
                    evidence_root=root,
                    manifest_digest=digest(MANIFEST),
                )

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
        self.assertEqual(["GT244-TEST-024"], result["issue_summary"]["unresolved_issue_ids"])

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
