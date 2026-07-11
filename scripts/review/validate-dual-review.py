#!/usr/bin/env python3
"""Validate Goal Teams V2.3 LLM + script dual-review records."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "v23" / "goalteams_v23.py"
sys.path.insert(0, str(ROOT))
from scripts.v23 import goalteams_v23 as gt  # noqa: E402
REQUIRED_TOP_KEYS = {
    "schema_version",
    "review_class",
    "artifact",
    "script_review",
    "llm_review",
    "final_decision",
    "author_run_id",
    "reviewer_run_id",
}

def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)

def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"{path}: dual review record must be a JSON object")
    return data

def validate(data: dict[str, Any], label: str, root: Path) -> None:
    missing = sorted(REQUIRED_TOP_KEYS - set(data))
    if missing:
        fail(f"{label}: missing keys: {', '.join(missing)}")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as fh:
        json.dump(data, fh)
        tmp = fh.name
    try:
        proc = subprocess.run([sys.executable, str(TOOL), "validate-dual-review", tmp, "--root", str(root)], cwd=ROOT, text=True, capture_output=True)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if proc.returncode != 0:
        fail(proc.stdout.strip() or proc.stderr.strip())

def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix=".goalteams-review-selftest-", dir=ROOT) as td:
        root = Path(td)
        prefix = root.relative_to(ROOT).as_posix()
        artifact = root / "artifact.txt"
        artifact.write_text("ok", encoding="utf-8")
        baseline = root / "baseline" / "artifact.txt"
        baseline.parent.mkdir()
        baseline.write_text("ok", encoding="utf-8")
        artifact_ref = f"{prefix}/artifact.txt"
        baseline_ref = f"{prefix}/baseline/artifact.txt"
        artifact_sha256 = hashlib.sha256(b"ok").hexdigest()
        compare_log = root / "compare.log.json"
        compare_log_ref = f"{prefix}/compare.log.json"
        compare_tool = ROOT / "scripts" / "review" / "compare-artifacts.py"
        command_argv = [
            "python3",
            "scripts/review/compare-artifacts.py",
            artifact_ref,
            baseline_ref,
        ]
        command = subprocess.run(command_argv, cwd=ROOT, text=True, capture_output=True)
        if command.returncode != 0 or command.stderr:
            fail(f"self-test: compare-artifacts execution failed: {command.stderr.strip()}")
        compare_log.write_text(command.stdout, encoding="utf-8")
        compare_log_sha256 = hashlib.sha256(compare_log.read_bytes()).hexdigest()
        domain_execution = {
            "argv": command_argv,
            "cwd": ".",
            "started_at": "2026-07-10T00:00:00Z",
            "ended_at": "2026-07-10T00:00:01Z",
            "exit_code": command.returncode,
            "log_path": compare_log_ref,
            "log_sha256": compare_log_sha256,
            "log_size": compare_log.stat().st_size,
        }
        comparison_inputs = {
            "actual_ref": artifact_ref,
            "actual_sha256": artifact_sha256,
            "baseline_ref": baseline_ref,
            "baseline_sha256": artifact_sha256,
            "baseline_approver_run_id": "run-baseline-approver",
            "baseline_approved_at": "2026-07-09T23:59:59Z",
        }
        binding_review = {
            "schema_version": "goal-teams-v2.3",
            "review_class": "comparison",
            "author_run_id": "run-author",
            "reviewer_run_id": "run-reviewer",
            "artifact": {
                "artifact_ref": artifact_ref,
                "artifact_sha256": artifact_sha256,
                "artifact_version": "V2.3",
            },
            "script_review": {"reviewer_run_id": "run-script-reviewer"},
        }
        binding_report = {
            "domain_execution": domain_execution,
            "comparison_inputs": comparison_inputs,
            "comparison_mode": "exact_hash_match",
            "tool_ref": "scripts/review/compare-artifacts.py",
            "tool_sha256": hashlib.sha256(compare_tool.read_bytes()).hexdigest(),
        }
        binding_digest = gt.review_replay_binding_digest(binding_review, binding_report)
        integrity_argv = gt.artifact_verifier_argv(
            artifact_ref,
            artifact_sha256,
            binding_digest,
        )
        integrity = subprocess.run(integrity_argv, cwd=ROOT, capture_output=True)
        if integrity.returncode != 0 or integrity.stderr:
            fail(f"self-test: integrity replay failed: {integrity.stderr!r}")
        integrity_log = root / "integrity.log.json"
        integrity_log_ref = f"{prefix}/integrity.log.json"
        integrity_log.write_bytes(integrity.stdout)
        report = root / "report.json"
        report.write_text(
            json.dumps(
                {
                    "schema_version": "goal-teams-v2.3",
                    "ok": True,
                    "error_code": None,
                    "exit_code": 0,
                    "tool": "compare-artifacts",
                    "reviewer_run_id": "run-script-reviewer",
                    "artifact_ref": artifact_ref,
                    "artifact_sha256": artifact_sha256,
                    "artifact_version": "V2.3",
                    "domain_execution": domain_execution,
                    "comparison_inputs": comparison_inputs,
                    "comparison_mode": "exact_hash_match",
                    "tool_ref": "scripts/review/compare-artifacts.py",
                    "tool_sha256": hashlib.sha256(compare_tool.read_bytes()).hexdigest(),
                    "binding_digest": binding_digest,
                    "integrity_replay": {
                        "argv": integrity_argv,
                        "cwd": ".",
                        "started_at": "2026-07-10T00:00:01Z",
                        "ended_at": "2026-07-10T00:00:02Z",
                        "exit_code": integrity.returncode,
                        "log_path": integrity_log_ref,
                        "log_sha256": hashlib.sha256(integrity_log.read_bytes()).hexdigest(),
                        "log_size": integrity_log.stat().st_size,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        report_sha256 = hashlib.sha256(report.read_bytes()).hexdigest()
        report_ref = f"{prefix}/report.json"
        review = root / "review.md"
        review.write_text(
            "---\n"
            "type: Dual Review LLM Evidence\n"
            "title: self-test semantic review\n"
            "---\n\n"
            "# Review\n\n"
            "Reviewer run: run-reviewer\n\n"
            f"Artifact SHA-256: {artifact_sha256}\n\n"
            "Artifact version: V2.3\n\n"
            "Artifact semantics match the fixture contract.\n",
            encoding="utf-8",
        )
        review_sha256 = hashlib.sha256(review.read_bytes()).hexdigest()
        review_ref = f"{prefix}/review.md"
        payload = {
            "schema_version": "goal-teams-v2.3",
            "review_class": "comparison",
            "author_run_id": "run-author",
            "reviewer_run_id": "run-reviewer",
            "artifact": {
                "artifact_ref": artifact_ref,
                "artifact_sha256": artifact_sha256,
                "artifact_version": "V2.3",
            },
            "script_review": {
                "reviewer_run_id": "run-script-reviewer",
                "tool": "compare-artifacts",
                "status": "passed",
                "exit_code": 0,
                "evidence_path": report_ref,
                "evidence_sha256": report_sha256,
                "evidence_size": report.stat().st_size,
                "artifact_sha256": artifact_sha256,
                "artifact_version": "V2.3",
            },
            "llm_review": {
                "reviewer_run_id": "run-reviewer",
                "status": "passed",
                "evidence_path": review_ref,
                "evidence_sha256": review_sha256,
                "evidence_size": review.stat().st_size,
                "summary": "Artifact semantics match the fixture contract.",
                "artifact_sha256": artifact_sha256,
                "artifact_version": "V2.3",
            },
            "final_decision": {"status": "pass", "reason": "both applicable reviews passed"},
        }
        validate(payload, "self-test", ROOT)
        invalid = dict(payload)
        invalid["reviewer_run_id"] = "run-author"
        invalid_llm = dict(payload["llm_review"])
        invalid_llm["reviewer_run_id"] = "run-author"
        invalid["llm_review"] = invalid_llm
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as fh:
            json.dump(invalid, fh)
            invalid_path = Path(fh.name)
        try:
            proc = subprocess.run(
                [sys.executable, str(TOOL), "validate-dual-review", str(invalid_path), "--root", str(ROOT)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
        finally:
            invalid_path.unlink(missing_ok=True)
        if proc.returncode == 0 or "E_REVIEW_SELF" not in proc.stdout:
            fail("self-test: self-review mutation did not fail closed with E_REVIEW_SELF")
    print("Dual-review validation self-test passed.")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    if args.self_test:
        self_test(); return
    if not args.paths:
        parser.error("at least one dual-review JSON file is required unless --self-test is used")
    for item in args.paths:
        validate(load_json(Path(item)), item, Path(args.root))
    print(f"Dual-review validation passed for {len(args.paths)} records.")
if __name__ == "__main__":
    main()
