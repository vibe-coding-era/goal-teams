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
        dimensions = {
            dimension["id"]: {
                "checks": {
                    check_id: {"status": status, "evidence_refs": [ref]}
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
                    "event_id": f"resolved-{index:03d}",
                    "issue_id": issue["id"],
                    "event_type": "resolved",
                    "dimension": issue["dimension"],
                    "summary": issue["summary"],
                    "severity": "high",
                    "status": "resolved",
                    "artifact_refs": [],
                    "evidence_refs": ["proof.json"],
                    "agent_run_id": "independent-reviewer",
                    "timestamp": "2026-07-23T00:00:00+08:00",
                }
            )
        ledger.write_text(
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
            encoding="utf-8",
        )
        return {
            "schema_version": score_module.EVIDENCE_SCHEMA,
            "product_version": "V2.44",
            "manifest_sha256": digest(MANIFEST),
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
            events[-1]["status"] = "open"
            events[-1]["event_type"] = "reopened"
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
        self.assertEqual(["GT244-TEST-013"], result["issue_summary"]["unresolved_issue_ids"])


if __name__ == "__main__":
    unittest.main()
