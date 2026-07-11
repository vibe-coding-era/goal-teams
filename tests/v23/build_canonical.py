#!/usr/bin/env python3
"""Regenerate the checked-in V2.3 canonical chain from executable facts."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.v23.common import ROOT, gt, sha256_path


CANONICAL = ROOT / "examples" / "canonical-v23"
VERSION = CANONICAL / "versions" / "V2.3"
LEDGER_OWNER = "RUN-CAN-LEDGER-OWNER"
OWNER = "RUN-CAN-OWNER"
VALIDATOR = "RUN-CAN-REVIEWER"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for value in values
        ),
        encoding="utf-8",
    )


def normalize_fixture_modes() -> None:
    """Keep generated fixture files aligned with their canonical Git index mode."""
    for path in sorted(CANONICAL.rglob("*")):
        if path.is_file() and not path.is_symlink():
            path.chmod(0o644)


def identity(
    agent_type: str,
    run_id: str,
    member_id: str,
    display_name: str,
    transport: str,
) -> dict[str, str]:
    return {
        "agent_type": agent_type,
        "agent_run_id": run_id,
        "member_id": member_id,
        "display_name": display_name,
        "transport_handle": transport,
    }


def event(
    number: int,
    task_id: str,
    revision: int,
    state: str,
    attempt_id: str,
    *,
    actor: str = OWNER,
    event_type: str = "task_patch",
    payload: dict[str, Any] | None = None,
    validation_check_id: str | None = None,
    validation_run_id: str | None = None,
) -> dict[str, Any]:
    body = {"task_state": state}
    body.update(payload or {})
    value: dict[str, Any] = {
        "schema_version": "goal-teams-v2.3",
        "event_id": f"EVT-CAN-{number:03d}",
        "event_type": event_type,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "actor_run_id": actor,
        "ledger_owner_run_id": LEDGER_OWNER,
        "base_revision": revision,
        "timestamp": f"2026-07-10T00:00:{number:02d}Z",
        "payload": body,
    }
    if validation_check_id is not None:
        value["validation_check_id"] = validation_check_id
        body["validation_check_id"] = validation_check_id
    if validation_run_id is not None:
        value["validation_run_id"] = validation_run_id
        body["validation_run_id"] = validation_run_id
    return value


def initial_payload(
    title: str,
    requirement: str,
    ac: str,
    *,
    required: bool,
    blocking: bool,
    artifacts: list[str],
) -> dict[str, Any]:
    return {
        "title": title,
        "required_for_done": required,
        "acceptance_blocking": blocking,
        "owner_member_id": "实现-Canonical",
        "owner_run_id": OWNER,
        "validator_member_id": "评审-Canonical",
        "validator_run_id": VALIDATOR,
        "merge_owner_run_id": LEDGER_OWNER,
        "check_state": "not_started",
        "requirement_refs": [requirement],
        "acceptance_criteria_refs": [ac],
        "artifact_refs": artifacts,
        "evidence_refs": [],
        "harness_refs": ["versions/V2.3/harness/harness.json"],
    }


def make_events() -> list[dict[str, Any]]:
    success = "TASK-CAN-SUCCESS"
    failure_recovery = "TASK-CAN-FAILURE-RECOVERY"
    blocked = "TASK-CAN-BLOCKED"
    blocked_recovery = "TASK-CAN-BLOCKED-RECOVERY"
    events = [
        event(
            1,
            success,
            0,
            "planned",
            "ATT-CAN-SUCCESS",
            payload=initial_payload(
                "Required success branch",
                "REQ-CAN-001",
                "AC-CAN-001",
                required=True,
                blocking=True,
                artifacts=["versions/V2.3/evidence/artifact.txt"],
            ),
        ),
        event(2, success, 1, "running", "ATT-CAN-SUCCESS"),
        event(
            3,
            success,
            2,
            "review",
            "ATT-CAN-SUCCESS",
        ),
        event(
            4,
            success,
            3,
            "review",
            "ATT-CAN-SUCCESS",
            actor=VALIDATOR,
            event_type="check_executed",
            payload={"check_state": "passed", "evidence_refs": ["EVD-CAN-001"]},
            validation_check_id="CHECK-CAN-SUCCESS",
            validation_run_id="RUN-CAN-SUCCESS",
        ),
        event(
            5,
            success,
            4,
            "accepted",
            "ATT-CAN-SUCCESS",
            actor=VALIDATOR,
            event_type="review_completed",
            validation_check_id="CHECK-CAN-SUCCESS",
            validation_run_id="RUN-CAN-SUCCESS",
        ),
        event(
            6,
            blocked,
            0,
            "planned",
            "ATT-CAN-BLOCKED",
            payload=initial_payload(
                "Optional blocked branch",
                "REQ-CAN-003",
                "AC-CAN-003",
                required=False,
                blocking=False,
                artifacts=[],
            ),
        ),
        event(
            7,
            blocked,
            1,
            "blocked",
            "ATT-CAN-BLOCKED",
            payload={"blocked_reason": "documented optional dependency unavailable"},
        ),
        event(
            8,
            failure_recovery,
            0,
            "planned",
            "ATT-CAN-FAILURE",
            payload={
                **initial_payload(
                    "Historical check failure and recovery branch",
                    "REQ-CAN-004",
                    "AC-CAN-004",
                    required=False,
                    blocking=False,
                    artifacts=[],
                ),
                "nonblocking_reason": "historical recovery branch remains explicitly nonblocking and unaccepted",
            },
        ),
        event(9, failure_recovery, 1, "running", "ATT-CAN-FAILURE"),
        event(
            10,
            failure_recovery,
            2,
            "review",
            "ATT-CAN-FAILURE",
        ),
        event(
            11,
            failure_recovery,
            3,
            "review",
            "ATT-CAN-FAILURE",
            actor=VALIDATOR,
            event_type="check_executed",
            payload={"check_state": "failed", "evidence_refs": []},
            validation_check_id="CHECK-CAN-RECOVERY",
            validation_run_id="RUN-CAN-RECOVERY-FAILED",
        ),
        event(
            12,
            failure_recovery,
            4,
            "running",
            "ATT-CAN-RECOVERY",
            payload={"recovery_of_attempt_id": "ATT-CAN-FAILURE"},
        ),
        event(
            13,
            failure_recovery,
            5,
            "review",
            "ATT-CAN-RECOVERY",
        ),
        event(
            14,
            failure_recovery,
            6,
            "review",
            "ATT-CAN-RECOVERY",
            actor=VALIDATOR,
            event_type="check_executed",
            payload={"check_state": "failed", "evidence_refs": []},
            validation_check_id="CHECK-CAN-RECOVERY",
            validation_run_id="RUN-CAN-RECOVERY-FAILED",
        ),
        event(
            15,
            blocked_recovery,
            0,
            "planned",
            "ATT-CAN-BLOCKED-RECOVERY",
            payload=initial_payload(
                "Required blocked then recovered branch",
                "REQ-CAN-002",
                "AC-CAN-002",
                required=True,
                blocking=True,
                artifacts=["versions/V2.3/evidence/recovery.txt"],
            ),
        ),
        event(16, blocked_recovery, 1, "running", "ATT-CAN-BLOCKED-RECOVERY"),
        event(
            17,
            blocked_recovery,
            2,
            "blocked",
            "ATT-CAN-BLOCKED-RECOVERY",
            payload={"blocked_reason": "transient dependency"},
        ),
        event(
            18,
            blocked_recovery,
            3,
            "running",
            "ATT-CAN-BLOCKED-RECOVERY",
            payload={"blocked_reason": None, "recovery_note": "dependency restored"},
        ),
        event(
            19,
            blocked_recovery,
            4,
            "review",
            "ATT-CAN-BLOCKED-RECOVERY",
        ),
        event(
            20,
            blocked_recovery,
            5,
            "review",
            "ATT-CAN-BLOCKED-RECOVERY",
            actor=VALIDATOR,
            event_type="check_executed",
            payload={"check_state": "passed", "evidence_refs": ["EVD-CAN-002"]},
            validation_check_id="CHECK-CAN-RECOVERY",
            validation_run_id="RUN-CAN-RECOVERY-PASSED",
        ),
        event(
            21,
            blocked_recovery,
            6,
            "accepted",
            "ATT-CAN-BLOCKED-RECOVERY",
            actor=VALIDATOR,
            event_type="review_completed",
            validation_check_id="CHECK-CAN-RECOVERY",
            validation_run_id="RUN-CAN-RECOVERY-PASSED",
        ),
    ]
    return events


def execution_record(record: dict[str, Any]) -> dict[str, Any]:
    command = record["command"]
    return {
        "schema_version": "goal-teams-v2.3",
        "record_type": "command_execution",
        "evidence_id": record["evidence_id"],
        "check_id": record["check_id"],
        "run_id": record["run_id"],
        "attempt_id": record["attempt_id"],
        "producer_run_id": record["producer_run_id"],
        "argv": command["argv"],
        "cwd": command["cwd"],
        "started_at": command["started_at"],
        "ended_at": command["ended_at"],
        "exit_code": command["exit_code"],
        "log_path": command["log_path"],
        "log_sha256": command["log_sha256"],
        "log_size": command["log_size"],
    }


def make_evidence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_root = VERSION / "evidence"
    (evidence_root / "verify_artifact.py").unlink(missing_ok=True)
    artifacts = {
        "success": evidence_root / "artifact.txt",
        "recovery": evidence_root / "recovery.txt",
    }
    artifacts["success"].write_bytes(b"canonical success artifact\n")
    artifacts["recovery"].write_bytes(b"canonical recovery artifact\n")
    specs = [
        (
            "success",
            "EVD-CAN-001",
            "CHECK-CAN-SUCCESS",
            "RUN-CAN-SUCCESS",
            "ATT-CAN-SUCCESS",
            3,
            "2026-07-10T00:00:04Z",
            "2026-07-10T00:00:03Z",
            "2026-07-10T00:00:04Z",
            "run.log",
        ),
        (
            "recovery",
            "EVD-CAN-002",
            "CHECK-CAN-RECOVERY",
            "RUN-CAN-RECOVERY-PASSED",
            "ATT-CAN-BLOCKED-RECOVERY",
            19,
            "2026-07-10T00:00:20Z",
            "2026-07-10T00:00:19Z",
            "2026-07-10T00:00:20Z",
            "recovery.log",
        ),
    ]
    records: list[dict[str, Any]] = []
    for mode, evidence_id, check_id, run_id, attempt_id, prefix_revision, created, started, ended, log_name in specs:
        artifact = artifacts[mode]
        artifact_stat = artifact.stat()
        artifact_ref = str(artifact.relative_to(CANONICAL))
        record = {
            "schema_version": "goal-teams-v2.3",
            "evidence_id": evidence_id,
            "check_id": check_id,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "artifact_ref": artifact_ref,
            "artifact_sha256": sha256_path(artifact),
            "artifact_size": artifact_stat.st_size,
            "artifact_mtime_ns": artifact_stat.st_mtime_ns,
            "producer_run_id": OWNER,
            "created_at": created,
            "trust_level": "local_verified",
            "evidence_kind": "command_execution",
            "portable_fixture": True,
            "artifact_transport": "git",
            "mtime_policy": "transport_agnostic",
            "environment": {
                "commit": "HEAD",
                "workspace_revision": "HEAD",
                "platform": sys.platform,
                "python_version": sys.version.split()[0],
                "ledger_revision": prefix_revision,
                "ledger_prefix_sha256": gt.ledger_prefix_sha256(events, prefix_revision),
            },
        }
        domain_argv = [
            "python3",
            "-m",
            "json.tool",
            "versions/V2.3/identity/registry.json",
        ]
        domain_proc = subprocess.run(
            domain_argv, cwd=CANONICAL, capture_output=True, check=False
        )
        if domain_proc.returncode != 0 or domain_proc.stderr:
            raise RuntimeError(
                f"canonical domain command failed: {domain_proc.returncode} {domain_proc.stderr!r}"
            )
        log = evidence_root / log_name
        log.write_bytes(domain_proc.stdout)
        log_stat = log.stat()
        record["command"] = {
            "argv": domain_argv,
            "cwd": ".",
            "started_at": started,
            "ended_at": ended,
            "exit_code": domain_proc.returncode,
            "log_path": str(log.relative_to(CANONICAL)),
            "log_sha256": sha256_path(log),
            "log_size": log_stat.st_size,
            "log_mtime_ns": log_stat.st_mtime_ns,
        }
        execution_path = evidence_root / f"execution-{evidence_id}.json"
        write_json(execution_path, execution_record(record))
        record["command"].update(
            {
                "execution_record_path": str(execution_path.relative_to(CANONICAL)),
                "execution_record_sha256": sha256_path(execution_path),
                "execution_record_size": execution_path.stat().st_size,
            }
        )
        binding_digest = gt.evidence_replay_binding_digest(record)
        integrity_argv = gt.artifact_verifier_argv(
            artifact_ref,
            record["artifact_sha256"],
            binding_digest,
        )
        integrity_proc = subprocess.run(
            integrity_argv, cwd=CANONICAL, capture_output=True, check=False
        )
        if integrity_proc.returncode != 0 or integrity_proc.stderr:
            raise RuntimeError(
                f"canonical integrity replay failed: {integrity_proc.returncode} {integrity_proc.stderr!r}"
            )
        integrity_log = evidence_root / f"integrity-{evidence_id}.log"
        integrity_log.write_bytes(integrity_proc.stdout)
        integrity_stat = integrity_log.stat()
        record["integrity_replay"] = {
            "argv": integrity_argv,
            "cwd": ".",
            "started_at": ended,
            "ended_at": created,
            "exit_code": integrity_proc.returncode,
            "log_path": str(integrity_log.relative_to(CANONICAL)),
            "log_sha256": sha256_path(integrity_log),
            "log_size": integrity_stat.st_size,
            "log_mtime_ns": integrity_stat.st_mtime_ns,
        }
        records.append(record)
    write_jsonl(evidence_root / "evidence.jsonl", records)
    write_json(evidence_root / "evidence.json", records[0])
    write_json(evidence_root / "evidence-recovery.json", records[1])
    (evidence_root / "failed-run.log").write_text(
        "historical recovery check failed before the successful retry\n", encoding="utf-8"
    )
    return records


def make_harness(records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    checks = [
        {
            "schema_version": "goal-teams-v2.3",
            "check_id": "CHECK-CAN-SUCCESS",
            "check_state": "passed",
            "required": True,
            "acceptance_blocking": True,
            "acceptance_criteria_refs": ["AC-CAN-001"],
            "validator_run_id": VALIDATOR,
            "evidence_refs": ["EVD-CAN-001"],
            "expected_domain_execution": {
                "argv": records[0]["command"]["argv"],
                "cwd": records[0]["command"]["cwd"],
            },
        },
        {
            "schema_version": "goal-teams-v2.3",
            "check_id": "CHECK-CAN-RECOVERY",
            "check_state": "passed",
            "required": True,
            "acceptance_blocking": True,
            "acceptance_criteria_refs": ["AC-CAN-002"],
            "validator_run_id": VALIDATOR,
            "evidence_refs": ["EVD-CAN-002"],
            "expected_domain_execution": {
                "argv": records[1]["command"]["argv"],
                "cwd": records[1]["command"]["cwd"],
            },
        },
        {
            "schema_version": "goal-teams-v2.3",
            "check_id": "CHECK-CAN-UI-BEHAVIOR",
            "check_state": "not_required",
            "required": False,
            "acceptance_blocking": False,
            "acceptance_criteria_refs": ["AC-CAN-003", "AC-CAN-004"],
            "validator_run_id": VALIDATOR,
            "evidence_refs": [],
            "not_applicable_reason": "Optional branches do not block the canonical completion claim.",
            "reviewer_run_id": VALIDATOR,
        },
    ]
    runs = [
        {
            "schema_version": "goal-teams-v2.3",
            "run_id": "RUN-CAN-SUCCESS",
            "check_id": "CHECK-CAN-SUCCESS",
            "attempt_id": "ATT-CAN-SUCCESS",
            "producer_run_id": OWNER,
            "status": "passed",
            "started_at": "2026-07-10T00:00:02Z",
            "ended_at": "2026-07-10T00:00:04Z",
            "evidence_refs": ["EVD-CAN-001"],
        },
        {
            "schema_version": "goal-teams-v2.3",
            "run_id": "RUN-CAN-RECOVERY-FAILED",
            "check_id": "CHECK-CAN-RECOVERY",
            "attempt_id": "ATT-CAN-BLOCKED-RECOVERY",
            "producer_run_id": OWNER,
            "status": "failed",
            "started_at": "2026-07-10T00:00:14Z",
            "ended_at": "2026-07-10T00:00:15Z",
            "log_path": "versions/V2.3/evidence/failed-run.log",
            "evidence_refs": [],
        },
        {
            "schema_version": "goal-teams-v2.3",
            "run_id": "RUN-CAN-RECOVERY-PASSED",
            "check_id": "CHECK-CAN-RECOVERY",
            "attempt_id": "ATT-CAN-BLOCKED-RECOVERY",
            "producer_run_id": OWNER,
            "status": "passed",
            "started_at": "2026-07-10T00:00:18Z",
            "ended_at": "2026-07-10T00:00:20Z",
            "recovery_of_run_id": "RUN-CAN-RECOVERY-FAILED",
            "evidence_refs": ["EVD-CAN-002"],
        },
    ]
    harness = {
        "schema_version": "goal-teams-v2.3",
        "harness_contract": {
            "task_type": "replica",
            "required_review_class": "comparison",
            "checks": checks,
            "commands": [
                "python3 scripts/v23/goalteams_v23.py validate-canonical examples/canonical-v23",
                "python3 scripts/checks/check-v23.py",
            ],
            "artifact_checks": [
                "ledger replay",
                "TaskList byte equivalence",
                "artifact, log, and command-execution SHA-256",
            ],
            "e2e_checks": ["ui-replica pixel evidence", "fresh benchmark execution"],
            "pixel_diff_checks": [
                {
                    "ui_mode": "replica",
                    "color_tolerance": 3,
                    "changed_ratio_threshold": 0.0,
                    "mae_threshold": 0.0,
                    "critical_regions_required": True,
                    "environment_required": True,
                    "baseline_approval_required": True,
                }
            ],
            "evidence_paths": [
                "versions/V2.3/evidence/evidence.jsonl",
                "versions/V2.3/reviews/dual-review.json",
                "versions/V2.3/audit/completion-audit.json",
            ],
            "evidence_records": [
                "versions/V2.3/evidence/evidence.json",
                "versions/V2.3/evidence/evidence-recovery.json",
            ],
            "failure_report": {"failing_check": "required", "stable_error_envelope": True},
        },
        "runs": runs,
    }
    write_json(VERSION / "harness" / "harness.json", harness)
    return harness, checks, runs


def make_pixel_evidence() -> dict[str, Any]:
    behavior_root = VERSION / "behavior"
    pixel_root = behavior_root / "evidence" / "ui-replica"
    pixel_root.mkdir(parents=True, exist_ok=True)
    ppm = b"P6\n2 2\n255\n" + bytes([20, 40, 60, 20, 40, 60, 80, 100, 120, 80, 100, 120])
    baseline = pixel_root / "baseline.ppm"
    actual = pixel_root / "actual.ppm"
    baseline.write_bytes(ppm)
    actual.write_bytes(ppm)
    environment = {
        "browser": "Chromium",
        "browser_version": "fixture-1",
        "viewport": "2x2",
        "dpr": 1,
        "fonts": ["Goal Teams Fixture Sans"],
        "os": "portable-fixture",
    }
    baseline_env = pixel_root / "baseline-environment.json"
    actual_env = pixel_root / "actual-environment.json"
    approval = pixel_root / "baseline-approval.json"
    write_json(baseline_env, environment)
    write_json(actual_env, environment)
    write_json(
        approval,
        {
            "reviewer_run_id": "RUN-CAN-PIXEL-REVIEWER",
            "approved_at": "2026-07-10T00:00:00Z",
            "reason": "Independent approval of deterministic canonical replica baseline.",
            "baseline_sha256": sha256_path(baseline),
        },
    )
    diff = pixel_root / "diff.ppm"
    args = [
        sys.executable,
        str(ROOT / "scripts" / "harness" / "pixel-diff.py"),
        "evidence/ui-replica/baseline.ppm",
        "evidence/ui-replica/actual.ppm",
        "--ui-mode",
        "replica",
        "--threshold",
        "0",
        "--mae-threshold",
        "0",
        "--baseline-environment",
        "evidence/ui-replica/baseline-environment.json",
        "--actual-environment",
        "evidence/ui-replica/actual-environment.json",
        "--baseline-approval",
        "evidence/ui-replica/baseline-approval.json",
        "--diff",
        "evidence/ui-replica/diff.ppm",
    ]
    proc = subprocess.run(args, cwd=behavior_root, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)
    report = json.loads(proc.stdout)
    if report.get("passed") is not True:
        raise RuntimeError(str(report))
    report_path = pixel_root / "pixel-report.json"
    write_json(report_path, report)
    return {
        "report": str(report_path.relative_to(behavior_root)),
        "report_sha256": sha256_path(report_path),
        "baseline": str(baseline.relative_to(behavior_root)),
        "baseline_sha256": sha256_path(baseline),
        "actual": str(actual.relative_to(behavior_root)),
        "actual_sha256": sha256_path(actual),
        "diff": str(diff.relative_to(behavior_root)),
        "diff_sha256": sha256_path(diff),
        "baseline_environment": str(baseline_env.relative_to(behavior_root)),
        "actual_environment": str(actual_env.relative_to(behavior_root)),
        "baseline_approval": str(approval.relative_to(behavior_root)),
    }


def refresh_behavior(pixel: dict[str, Any]) -> None:
    behavior_root = VERSION / "behavior"
    evidence_root = behavior_root / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    for path in sorted(behavior_root.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        scenario = doc.get("scenario_id")
        if not isinstance(scenario, str):
            continue
        scenario_dir = evidence_root / scenario
        scenario_dir.mkdir(parents=True, exist_ok=True)
        trace_path = scenario_dir / "trace.jsonl"
        log_path = scenario_dir / "subject.log"
        score_path = scenario_dir / "score.json"
        trace_path.write_text(
            json.dumps(
                {"scenario_id": scenario, "step": "deterministic-contract-executed", "result": "passed"},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        log_path.write_text(f"{scenario}: deterministic contract fixture passed\n", encoding="utf-8")
        input_hash = gt.canonical_json_sha256(doc["input"])
        output_hash = gt.canonical_json_sha256(doc["output"])
        write_json(
            score_path,
            {
                "schema_version": "goal-teams-behavior-score-v2.3",
                "scenario_id": scenario,
                "scorer_run_id": doc["scorer_run_id"],
                "input_sha256": input_hash,
                "output_sha256": output_hash,
                "rubric_version": "behavior-v2.3",
                "decision": "pass",
                "quality": 1.0,
                "release_eligible": False,
            },
        )
        ended = doc["ended_at"]
        generated = ended[:-1] + ".500000Z" if ended.endswith("Z") else ended
        doc.update(
            {
                "evaluation_class": "deterministic_contract",
                "release_eligible": False,
                "executed": True,
                "result": "passed",
                "environment": {
                    "commit": "HEAD",
                    "platform": sys.platform,
                    "python_version": sys.version.split()[0],
                },
                "provenance": {
                    "runner_id": "goal-teams-benchmark-contract-runner",
                    "runner_version": "V2.3",
                    "run_nonce": f"CANONICAL-{scenario}-20260710",
                    "generated_at": generated,
                    "input_sha256": input_hash,
                    "output_sha256": output_hash,
                    "expected_exit_code": 0,
                    "command": {
                        "argv": ["goalteams-contract-runner", scenario],
                        "cwd": ".",
                        "exit_code": 0,
                        "log_path": str(log_path.relative_to(behavior_root)),
                        "log_sha256": sha256_path(log_path),
                    },
                },
                "trace": [
                    {"path": str(trace_path.relative_to(behavior_root)), "sha256": sha256_path(trace_path)}
                ],
                "evidence": [
                    {"path": str(log_path.relative_to(behavior_root)), "sha256": sha256_path(log_path)}
                ],
                "score": {
                    "quality": 1.0,
                    "rubric_version": "behavior-v2.3",
                    "scorer_run_id": doc["scorer_run_id"],
                    "evidence_path": str(score_path.relative_to(behavior_root)),
                    "evidence_sha256": sha256_path(score_path),
                },
            }
        )
        if scenario == "ui-replica":
            doc["pixel_validation"] = pixel
            doc["evidence"].append({"path": pixel["report"], "sha256": pixel["report_sha256"]})
        write_json(path, doc)


def make_reviews() -> tuple[dict[str, Any], list[str]]:
    artifact = VERSION / "evidence" / "artifact.txt"
    artifact_ref = str(artifact.relative_to(CANONICAL))
    artifact_hash = sha256_path(artifact)
    baseline = VERSION / "evidence" / "baseline" / "artifact.txt"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_bytes(artifact.read_bytes())
    baseline_ref = str(baseline.relative_to(CANONICAL))
    reviews = VERSION / "reviews"
    script_path = reviews / "script-review.json"
    semantic_path = reviews / "semantic-review.md"
    semantic_path.write_text(
        "---\n"
        "type: Semantic Review\n"
        "title: Canonical V2.3 independent semantic review\n"
        "reviewer_run_id: RUN-CAN-SEMANTIC-REVIEWER\n"
        "artifact_version: V2.3\n"
        f"artifact_sha256: {artifact_hash}\n"
        "---\n\n"
        "# Independent semantic review\n\n"
        "Observation: Required tasks, Evidence bindings, failure recovery, and nonblocking exceptions are explicit.\n\n"
        "Conclusion: The reviewed artifact is semantically consistent with the V2.3 acceptance claim.\n",
        encoding="utf-8",
    )
    review = {
        "schema_version": "goal-teams-v2.3",
        "review_class": "comparison",
        "author_run_id": OWNER,
        "reviewer_run_id": "RUN-CAN-SEMANTIC-REVIEWER",
        "artifact": {
            "artifact_ref": artifact_ref,
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
        },
        "script_review": {
            "reviewer_run_id": "RUN-CAN-SCRIPT-REVIEWER",
            "tool": "compare-artifacts",
            "status": "passed",
            "exit_code": 0,
            "evidence_path": str(script_path.relative_to(CANONICAL)),
            "evidence_sha256": "0" * 64,
            "evidence_size": 1,
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
        },
        "llm_review": {
            "reviewer_run_id": "RUN-CAN-SEMANTIC-REVIEWER",
            "reviewer": "语义评审-Canonical",
            "status": "passed",
            "evidence_path": str(semantic_path.relative_to(CANONICAL)),
            "evidence_sha256": sha256_path(semantic_path),
            "evidence_size": semantic_path.stat().st_size,
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
            "summary": "需求、状态分支、Evidence 与风险语义一致。",
        },
        "final_decision": {
            "status": "pass",
            "reason": "Independent script and semantic reviews bind to the same artifact hash and version.",
        },
    }
    domain_argv = [
        "python3",
        "../../scripts/review/compare-artifacts.py",
        artifact_ref,
        baseline_ref,
    ]
    domain_proc = subprocess.run(
        domain_argv, cwd=CANONICAL, capture_output=True, check=False
    )
    if domain_proc.returncode != 0 or domain_proc.stderr:
        raise RuntimeError(
            f"script review domain command failed: {domain_proc.returncode} {domain_proc.stderr!r}"
        )
    log = reviews / "script-review.log"
    log.write_bytes(domain_proc.stdout)
    script_record = {
        "schema_version": "goal-teams-v2.3",
        "ok": True,
        "error_code": None,
        "exit_code": 0,
        "tool": "compare-artifacts",
        "reviewer_run_id": "RUN-CAN-SCRIPT-REVIEWER",
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_hash,
        "artifact_version": "V2.3",
        "domain_execution": {
            "argv": domain_argv,
            "cwd": ".",
            "started_at": "2026-07-10T00:00:21Z",
            "ended_at": "2026-07-10T00:00:22Z",
            "exit_code": domain_proc.returncode,
            "log_path": str(log.relative_to(CANONICAL)),
            "log_sha256": sha256_path(log),
            "log_size": log.stat().st_size,
        },
        "comparison_inputs": {
            "actual_ref": artifact_ref,
            "actual_sha256": artifact_hash,
            "baseline_ref": baseline_ref,
            "baseline_sha256": sha256_path(baseline),
            "baseline_approver_run_id": "RUN-REPOSITORY-OWNER-FIXTURE",
            "baseline_approved_at": "2026-07-10T00:00:20Z",
        },
        "comparison_mode": "exact_hash_match",
        "tool_ref": "scripts/review/compare-artifacts.py",
        "tool_sha256": sha256_path(ROOT / "scripts" / "review" / "compare-artifacts.py"),
    }
    binding_digest = gt.review_replay_binding_digest(review, script_record)
    script_record["binding_digest"] = binding_digest
    integrity_argv = gt.artifact_verifier_argv(
        artifact_ref,
        artifact_hash,
        binding_digest,
    )
    integrity_proc = subprocess.run(
        integrity_argv, cwd=CANONICAL, capture_output=True, check=False
    )
    if integrity_proc.returncode != 0 or integrity_proc.stderr:
        raise RuntimeError(
            f"script review integrity replay failed: {integrity_proc.returncode} {integrity_proc.stderr!r}"
        )
    integrity_log = reviews / "script-review-integrity.log"
    integrity_log.write_bytes(integrity_proc.stdout)
    script_record["integrity_replay"] = {
        "argv": integrity_argv,
        "cwd": ".",
        "started_at": "2026-07-10T00:00:22Z",
        "ended_at": "2026-07-10T00:00:23Z",
        "exit_code": integrity_proc.returncode,
        "log_path": str(integrity_log.relative_to(CANONICAL)),
        "log_sha256": sha256_path(integrity_log),
        "log_size": integrity_log.stat().st_size,
    }
    write_json(script_path, script_record)
    review["script_review"].update(
        {
            "evidence_sha256": sha256_path(script_path),
            "evidence_size": script_path.stat().st_size,
        }
    )
    write_json(reviews / "dual-review.json", review)
    errors = gt.validate_dual_review(review, CANONICAL)
    if errors:
        raise RuntimeError(f"generated review invalid: {errors}")
    return review, errors


def main() -> int:
    identity_doc = {
        "schema_version": "goal-teams-v2.3",
        "identities": [
            identity("goal_backend", OWNER, "实现-Canonical", "实现-Canonical", "canonical_owner"),
            identity("goal_reviewer", VALIDATOR, "评审-Canonical", "评审-Canonical", "canonical_reviewer"),
            identity(
                "goal_merge_owner",
                LEDGER_OWNER,
                "合并所有者-Canonical",
                "合并所有者-Canonical",
                "canonical_ledger_owner",
            ),
            identity(
                "goal_reviewer",
                "RUN-CAN-SCRIPT-REVIEWER",
                "脚本评审-Canonical",
                "脚本评审-Canonical",
                "canonical_script_reviewer",
            ),
            identity(
                "goal_reviewer",
                "RUN-CAN-SEMANTIC-REVIEWER",
                "语义评审-Canonical",
                "语义评审-Canonical",
                "canonical_semantic_reviewer",
            ),
            identity(
                "goal_completion_auditor",
                "RUN-CAN-COMPLETION-AUDITOR",
                "完成审计-Canonical",
                "完成审计-Canonical",
                "canonical_completion_auditor",
            ),
            identity(
                "goal_reviewer",
                "RUN-CAN-PIXEL-REVIEWER",
                "像素评审-Canonical",
                "像素评审-Canonical",
                "canonical_pixel_reviewer",
            ),
            identity(
                "repository_owner",
                "RUN-REPOSITORY-OWNER-FIXTURE",
                "仓库所有者-授权夹具",
                "仓库所有者-授权夹具",
                "canonical_repository_owner_fixture",
            ),
        ],
    }
    write_json(VERSION / "identity" / "registry.json", identity_doc)
    registry, identity_errors = gt.validate_identity_registry(identity_doc)
    if identity_errors or len(registry) != len(identity_doc["identities"]):
        raise RuntimeError(f"identity registry invalid: {identity_errors}")

    events = make_events()
    ledger_path = VERSION / "ledger" / "events.jsonl"
    write_jsonl(ledger_path, events)
    ledger_hash = sha256_path(ledger_path)
    evidence_records = make_evidence(events)
    evidence_registry, evidence_errors = gt.build_evidence_registry(
        evidence_records,
        CANONICAL,
        ledger_events=events,
        allow_portable_fixture=True,
    )
    if evidence_errors:
        raise RuntimeError(f"evidence invalid: {evidence_errors}")
    valid_evidence_ids = {
        key for key, value in evidence_registry.items() if value.get("valid_for_acceptance") is True
    }
    state = gt.reduce_events(
        events,
        valid_evidence_ids=valid_evidence_ids,
        evidence_registry=evidence_registry,
        ledger_owner_run_id=LEDGER_OWNER,
    )
    if state["conflicts"]:
        raise RuntimeError(f"ledger invalid: {state['conflicts']}")
    gt.write_checkpoint(VERSION / "ledger" / "checkpoint.json", state)
    (VERSION / "TaskList.md").write_text(gt.render_tasklist(state), encoding="utf-8")

    _, checks, runs = make_harness(evidence_records)
    trace = {
        "schema_version": "goal-teams-v2.3",
        "requirements": [
            {"id": "REQ-CAN-001"},
            {"id": "REQ-CAN-002"},
            {"id": "REQ-CAN-003"},
            {"id": "REQ-CAN-004"},
        ],
        "acceptance_criteria": [
            {"id": "AC-CAN-001", "required": True},
            {"id": "AC-CAN-002", "required": True},
            {"id": "AC-CAN-003", "required": False},
            {"id": "AC-CAN-004", "required": False},
        ],
        "tasks": [copy.deepcopy(state["tasks"][key]) for key in sorted(state["tasks"])],
        "checks": copy.deepcopy(checks),
        "runs": copy.deepcopy(runs),
        "evidence": copy.deepcopy(evidence_records),
    }
    write_json(VERSION / "harness" / "traceability.json", trace)
    trace_result = gt.validate_traceability(
        trace,
        CANONICAL,
        valid_evidence_ids,
        evidence_registry,
        ledger_events=events,
        allow_portable_fixture=True,
    )
    if not trace_result["ok"]:
        raise RuntimeError(f"traceability invalid: {trace_result}")

    _, review_errors = make_reviews()
    audit = {
        "schema_version": "goal-teams-v2.3",
        "audit_id": "AUD-CAN-001",
        "auditor_run_id": "RUN-CAN-COMPLETION-AUDITOR",
        "author_run_id": OWNER,
        "ledger_revision": state["ledger_revision"],
        "audit_state": "passed",
        "run_outcome": gt.goal_outcome(
            list(state["tasks"].values()), "passed", valid_evidence_ids, evidence_registry
        ),
        "loop_decision": "stop",
        "stop_reason": "achieved",
        "task_state_digest": gt.task_state_digest(state["tasks"]),
        "traceability_valid": True,
        "dual_review_valid": True,
        "required_task_ids": ["TASK-CAN-BLOCKED-RECOVERY", "TASK-CAN-SUCCESS"],
        "accepted_required_task_ids": ["TASK-CAN-BLOCKED-RECOVERY", "TASK-CAN-SUCCESS"],
        "open_acceptance_blocking_task_ids": [],
        "documented_nonblocking_tasks": [
            {
                "task_id": "TASK-CAN-BLOCKED",
                "task_state": "blocked",
                "reason": "documented optional dependency unavailable",
            },
            {
                "task_id": "TASK-CAN-FAILURE-RECOVERY",
                "task_state": "review",
                "reason": "historical recovery branch remains explicitly nonblocking and unaccepted",
            },
        ],
        "required_acceptance_criteria": ["AC-CAN-001", "AC-CAN-002"],
        "covered_acceptance_criteria": ["AC-CAN-001", "AC-CAN-002"],
        "evidence_refs": ["EVD-CAN-001", "EVD-CAN-002"],
        "review_ref": "versions/V2.3/reviews/dual-review.json",
        "conclusion": "achieved",
    }
    write_json(VERSION / "audit" / "completion-audit.json", audit)
    audit_errors = gt.validate_completion_audit(
        audit,
        state["tasks"],
        valid_evidence_ids,
        evidence_registry,
        traceability_result=trace_result,
        dual_review_errors=review_errors,
        require_release_closure=True,
        ledger_revision=state["ledger_revision"],
    )
    if audit_errors:
        raise RuntimeError(f"audit invalid: {audit_errors}")

    pixel = make_pixel_evidence()
    refresh_behavior(pixel)
    normalize_fixture_modes()
    errors = gt.validate_canonical(CANONICAL)
    if errors:
        raise RuntimeError(f"canonical invalid after generation: {errors}")
    print(json.dumps({"ok": True, "ledger_sha256": ledger_hash, "events": len(events)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
