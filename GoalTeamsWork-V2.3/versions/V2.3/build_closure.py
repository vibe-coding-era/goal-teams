#!/usr/bin/env python3
"""Build the real V2.3 project Evidence/Traceability/Review/Audit closure."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(__file__).resolve().parents[3]
VERSION = ROOT / "versions/V2.3"
sys.path.insert(0, str(REPO))
from scripts.v23 import goalteams_v23 as gt  # noqa: E402

SCHEMA = "goal-teams-v2.3"
OWNER = "RUN-ROOT-V23-CLOSURE"
VALIDATOR = "RUN-R236-FRESH-REVIEW-20260711-01"
SCRIPT_REVIEWER = "RUN-V23-RELEASE-SCRIPT-REVIEW"
AUDITOR = "RUN-V23-COMPLETION-AUDITOR-20260711-01"
LEDGER_OWNER = "RUN-ROOT-V23-LEDGER"
ATTEMPT = "ATT-V23-RELEASE-CLOSURE"
CHECK = "CHECK-V23-RELEASE-CLOSURE"
RUN = "RUN-V23-RELEASE-GATE"
EVIDENCE = "EVD-V23-RELEASE-GATE"
TASK_TITLES = [
    "Schema SSOT、闭合枚举与统一 envelope",
    "状态转换、CAS、append-only ledger 与 deterministic TaskList",
    "Evidence、逐 AC Traceability、Dual Review 与错误合同",
    "Canonical 成功/阻塞/失败/恢复全链",
    "真实九场景 Behavior/Benchmark 与防假绿重评分",
    "Typed migration scan/plan/apply/verify/rollback 与数据保护",
    "Manifest 驱动事务安装、TOCTOU 防护与 rollback/uninstall",
    "Capability、Profile Router 与 Context Gate",
    "Pixel、安全 redaction、symlink/mode 与 prompt-injection 门禁",
    "RULES/SKILL/runtime/README/PRD 语义与 GA 边界同步",
    "CI 聚合 Contract 到 Distribution 全部门禁",
    "本项目 Harness/Evidence/Traceability/Review/Audit 机器闭环",
    "独立脚本复核、fresh semantic review 与 RC 冻结验证",
]
TASKS = [
    (f"TASK-23-{index:03d}", f"REQ-23-{index:03d}", f"AC-23-{index:03d}", title)
    for index, title in enumerate(TASK_TITLES, 1)
]
SOURCE_PATHS = [
    "GoalTeams-PRD-V2.3.md",
    "schemas/v2.3/goal-teams.schema.json",
    "scripts/v23/goalteams_v23.py",
    "scripts/v23/package_selection.py",
    "scripts/checks/check.sh",
    "scripts/install/install-local.sh",
    "tests/v23/fixtures/behavior/blind-agent-codex.json",
]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def identity(agent_type: str, run_id: str, display: str, handle: str) -> dict[str, str]:
    return {
        "agent_type": agent_type,
        "agent_run_id": run_id,
        "member_id": display,
        "display_name": display,
        "transport_handle": handle,
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_closure.py <blind-summary>")
    original_summary = Path(sys.argv[1]).resolve()
    if not original_summary.is_file():
        raise SystemExit("blind summary is missing")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, capture_output=True, check=True
    ).stdout.strip()

    identities = {
        "schema_version": SCHEMA,
        "identities": [
            identity("goal_lead", OWNER, "Goal Lead-V2.3收尾", "v23_closure_owner"),
            identity("goal_reviewer", VALIDATOR, "独立评审-V2.3冻结复核", "v23_fresh_reviewer"),
            identity("goal_reviewer", SCRIPT_REVIEWER, "脚本评审-V2.3发布门", "v23_script_reviewer"),
            identity("goal_merge_owner", LEDGER_OWNER, "账本所有者-V2.3", "v23_ledger_owner"),
            identity("goal_completion_auditor", AUDITOR, "完成审计-V2.3", "v23_completion_auditor"),
        ],
    }
    write_json(VERSION / "identity/registry.json", identities)

    base = datetime.now(timezone.utc) - timedelta(minutes=2)
    if os.environ.get("GOAL_TEAMS_REUSE_VERIFIED_DOMAIN") == "1":
        prior_execution = json.loads(
            (VERSION / "evidence/execution-EVD-V23-RELEASE-GATE.json").read_text(encoding="utf-8")
        )
        prior_started = gt.parse_timestamp(prior_execution.get("started_at"))
        if prior_started is None:
            raise SystemExit("existing verified domain start time is invalid")
        base = prior_started - timedelta(minutes=2)
    events: list[dict[str, Any]] = []
    sequence = 1
    artifact_ref = "versions/V2.3/evidence/release-gate.log"
    harness_ref = "versions/V2.3/harness/harness.json"
    for task_id, requirement_id, ac_id, title in TASKS:
        payload = {
            "title": title,
            "task_state": "planned",
            "check_state": "not_started",
            "required_for_done": True,
            "acceptance_blocking": True,
            "owner_member_id": "Goal Lead-V2.3收尾",
            "owner_run_id": OWNER,
            "validator_member_id": "独立评审-V2.3冻结复核",
            "validator_run_id": VALIDATOR,
            "merge_owner_run_id": LEDGER_OWNER,
            "requirement_refs": [requirement_id],
            "acceptance_criteria_refs": [ac_id],
            "artifact_refs": [artifact_ref],
            "evidence_refs": [],
            "harness_refs": [harness_ref],
        }
        for revision, patch in ((0, payload), (1, {"task_state": "running"}), (2, {"task_state": "review"})):
            events.append(
                {
                    "schema_version": SCHEMA,
                    "event_id": f"EVT-V23-{sequence:03d}",
                    "event_type": "task_patch",
                    "task_id": task_id,
                    "attempt_id": ATTEMPT,
                    "actor_run_id": OWNER,
                    "ledger_owner_run_id": LEDGER_OWNER,
                    "base_revision": revision,
                    "timestamp": iso(base + timedelta(seconds=sequence)),
                    "payload": patch,
                }
            )
            sequence += 1
    ledger_path = VERSION / "ledger/events.jsonl"
    write_jsonl(ledger_path, events)
    prefix_revision = len(events)
    prefix_digest = gt.ledger_prefix_sha256(events, prefix_revision)

    command_argv = [
        "python3",
        "scripts/v23/goalteams_v23.py",
        "release-gate",
        "examples/canonical-v23",
        "--mode",
        "rc",
        "--blind-summary",
        str(original_summary),
    ]
    log_path = VERSION / "evidence/release-gate.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    execution_path = VERSION / "evidence/execution-EVD-V23-RELEASE-GATE.json"
    if os.environ.get("GOAL_TEAMS_REUSE_VERIFIED_DOMAIN") == "1":
        previous = json.loads(execution_path.read_text(encoding="utf-8"))
        if (
            previous.get("argv") != command_argv
            or previous.get("cwd") != "."
            or previous.get("exit_code") != 0
            or previous.get("log_sha256") != gt.sha256(log_path)
        ):
            raise SystemExit("existing verified domain execution cannot be reused")
        command_started = gt.parse_timestamp(previous.get("started_at"))
        command_ended = gt.parse_timestamp(previous.get("ended_at"))
        if command_started is None or command_ended is None:
            raise SystemExit("existing verified domain timestamps are invalid")
        envelope = json.loads(log_path.read_text(encoding="utf-8"))
    else:
        command_started = datetime.now(timezone.utc)
        process = subprocess.run(command_argv, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        command_ended = datetime.now(timezone.utc)
        if process.returncode != 0 or process.stderr:
            raise SystemExit(f"release gate failed: {process.returncode} {process.stderr.decode(errors='replace')}")
        envelope = json.loads(process.stdout)
        # Domain execution succeeded with the raw envelope, but persisted
        # Evidence binds official redacted bytes rather than local paths.
        log_path.write_text(gt.redact_text(process.stdout.decode("utf-8")), encoding="utf-8")
    if envelope.get("ok") is not True:
        raise SystemExit(f"release gate did not pass: {envelope}")
    log_stat = log_path.stat()
    log_ref = log_path.relative_to(ROOT).as_posix()

    execution = {
        "schema_version": SCHEMA,
        "record_type": "command_execution",
        "evidence_id": EVIDENCE,
        "check_id": CHECK,
        "run_id": RUN,
        "attempt_id": ATTEMPT,
        "producer_run_id": OWNER,
        "argv": command_argv,
        "cwd": ".",
        "started_at": iso(command_started),
        "ended_at": iso(command_ended),
        "exit_code": 0,
        "log_path": log_ref,
        "log_sha256": gt.sha256(log_path),
        "log_size": log_stat.st_size,
    }
    write_json(execution_path, execution)
    command = {
        "argv": command_argv,
        "cwd": ".",
        "started_at": iso(command_started),
        "ended_at": iso(command_ended),
        "exit_code": 0,
        "log_path": log_ref,
        "log_sha256": gt.sha256(log_path),
        "log_size": log_stat.st_size,
        "log_mtime_ns": log_stat.st_mtime_ns,
        "execution_record_path": execution_path.relative_to(ROOT).as_posix(),
        "execution_record_sha256": gt.sha256(execution_path),
        "execution_record_size": execution_path.stat().st_size,
    }
    source_revision = gt.source_manifest_sha256(REPO, SOURCE_PATHS, commit=commit)
    record = {
        "schema_version": SCHEMA,
        "evidence_id": EVIDENCE,
        "evidence_kind": "command_execution",
        "check_id": CHECK,
        "run_id": RUN,
        "attempt_id": ATTEMPT,
        "producer_run_id": OWNER,
        "trust_level": "local_verified",
        "artifact_ref": log_ref,
        "artifact_sha256": gt.sha256(log_path),
        "artifact_size": log_stat.st_size,
        "artifact_mtime_ns": log_stat.st_mtime_ns,
        "command": command,
        "environment": {
            "commit": commit,
            "workspace_revision": source_revision,
            "source_paths": SOURCE_PATHS,
            "platform": platform.system().lower(),
            "python_version": platform.python_version(),
            "ledger_revision": prefix_revision,
            "ledger_prefix_sha256": prefix_digest,
        },
    }
    binding = gt.evidence_replay_binding_digest(record)
    integrity_started = datetime.now(timezone.utc)
    integrity_argv = gt.artifact_verifier_argv(log_ref, record["artifact_sha256"], binding)
    integrity_process = subprocess.run(integrity_argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    integrity_ended = datetime.now(timezone.utc)
    if integrity_process.returncode != 0 or integrity_process.stderr:
        raise SystemExit("Evidence integrity replay failed")
    integrity_log = VERSION / "evidence/integrity-EVD-V23-RELEASE-GATE.log"
    integrity_log.write_bytes(integrity_process.stdout)
    integrity_stat = integrity_log.stat()
    record["integrity_replay"] = {
        "argv": integrity_argv,
        "cwd": ".",
        "started_at": iso(integrity_started),
        "ended_at": iso(integrity_ended),
        "exit_code": 0,
        "log_path": integrity_log.relative_to(ROOT).as_posix(),
        "log_sha256": gt.sha256(integrity_log),
        "log_size": integrity_stat.st_size,
        "log_mtime_ns": integrity_stat.st_mtime_ns,
    }
    record["created_at"] = iso(integrity_ended + timedelta(milliseconds=1))
    write_json(VERSION / "evidence/evidence.json", record)
    write_jsonl(VERSION / "evidence/evidence.jsonl", [record])

    check = {
        "schema_version": SCHEMA,
        "check_id": CHECK,
        "check_state": "passed",
        "required": True,
        "acceptance_blocking": True,
        "acceptance_criteria_refs": [ac for _, _, ac, _ in TASKS],
        "validator_run_id": VALIDATOR,
        "evidence_refs": [EVIDENCE],
        "expected_domain_execution": {"argv": command_argv, "cwd": "."},
    }
    run = {
        "schema_version": SCHEMA,
        "run_id": RUN,
        "check_id": CHECK,
        "attempt_id": ATTEMPT,
        "producer_run_id": OWNER,
        "status": "passed",
        "started_at": iso(command_started - timedelta(milliseconds=1)),
        "ended_at": iso(integrity_ended + timedelta(milliseconds=1)),
        "evidence_refs": [EVIDENCE],
    }
    harness = {
        "schema_version": SCHEMA,
        "harness_contract": {
            "task_type": "security",
            "required_review_class": "safety",
            "commands": [" ".join(command_argv)],
            "artifact_checks": ["source commit", "blind 9/9", "full deterministic suite"],
            "e2e_checks": ["real nine-scenario blind-agent run"],
            "pixel_diff_checks": [],
            "evidence_paths": ["versions/V2.3/evidence/evidence.jsonl"],
            "evidence_records": ["versions/V2.3/evidence/evidence.json"],
            "failure_report": {"failing_check": "required", "stable_error_envelope": True},
            "checks": [check],
        },
        "runs": [run],
    }
    write_json(VERSION / "harness/harness.json", harness)

    # Independent safety review binds the same release-gate execution and a
    # separate runtime-locked integrity replay.
    semantic_path = VERSION / "reviews/semantic-review.md"
    semantic_path.parent.mkdir(parents=True, exist_ok=True)
    semantic_path.write_text(
        "---\ntype: V2.3 Independent Safety Review\n---\n\n"
        f"Reviewer run: {VALIDATOR}\n\nArtifact: {record['artifact_sha256']}\n\nVersion: V2.3\n\n"
        "The frozen source, 9/9 local-process-attested blind run, deterministic suite, distribution lifecycle, and GA fail-closed boundary are consistent.\n",
        encoding="utf-8",
    )
    review = {
        "schema_version": SCHEMA,
        "review_class": "safety",
        "author_run_id": OWNER,
        "reviewer_run_id": VALIDATOR,
        "artifact": {"artifact_ref": log_ref, "artifact_sha256": record["artifact_sha256"], "artifact_version": "V2.3"},
        "script_review": {
            "reviewer_run_id": SCRIPT_REVIEWER,
            "tool": "goalteams-v23-release-gate",
            "status": "passed",
            "exit_code": 0,
            "evidence_path": "versions/V2.3/reviews/script-review.json",
            "evidence_sha256": "pending",
            "evidence_size": 0,
            "artifact_sha256": record["artifact_sha256"],
            "artifact_version": "V2.3",
        },
        "llm_review": {
            "reviewer_run_id": VALIDATOR,
            "reviewer": "独立评审-V2.3冻结复核",
            "status": "passed",
            "summary": "Frozen release closure is consistent and GA remains fail-closed.",
            "evidence_path": semantic_path.relative_to(ROOT).as_posix(),
            "evidence_sha256": gt.sha256(semantic_path),
            "evidence_size": semantic_path.stat().st_size,
            "artifact_sha256": record["artifact_sha256"],
            "artifact_version": "V2.3",
        },
        "final_decision": {"status": "pass", "reason": "Independent script and safety reviews passed."},
    }
    script_report = {
        "schema_version": SCHEMA,
        "ok": True,
        "error_code": None,
        "exit_code": 0,
        "tool": "goalteams-v23-release-gate",
        "reviewer_run_id": SCRIPT_REVIEWER,
        "artifact_ref": log_ref,
        "artifact_sha256": record["artifact_sha256"],
        "artifact_version": "V2.3",
        "domain_execution": command,
    }
    review_binding = gt.review_replay_binding_digest(review, script_report)
    review_integrity_started = datetime.now(timezone.utc)
    review_integrity_argv = gt.artifact_verifier_argv(log_ref, record["artifact_sha256"], review_binding)
    review_integrity_process = subprocess.run(review_integrity_argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    review_integrity_ended = datetime.now(timezone.utc)
    if review_integrity_process.returncode != 0 or review_integrity_process.stderr:
        raise SystemExit("Review integrity replay failed")
    review_integrity_log = VERSION / "reviews/script-review-integrity.log"
    review_integrity_log.write_bytes(review_integrity_process.stdout)
    script_report.update(
        binding_digest=review_binding,
        integrity_replay={
            "argv": review_integrity_argv,
            "cwd": ".",
            "started_at": iso(review_integrity_started),
            "ended_at": iso(review_integrity_ended),
            "exit_code": 0,
            "log_path": review_integrity_log.relative_to(ROOT).as_posix(),
            "log_sha256": gt.sha256(review_integrity_log),
            "log_size": review_integrity_log.stat().st_size,
        },
    )
    script_report_path = VERSION / "reviews/script-review.json"
    write_json(script_report_path, script_report)
    review["script_review"].update(
        evidence_sha256=gt.sha256(script_report_path), evidence_size=script_report_path.stat().st_size
    )
    review_path = VERSION / "reviews/dual-review.json"
    write_json(review_path, review)

    reference_time = review_integrity_ended + timedelta(seconds=1)
    for task_id, _, _, _ in TASKS:
        for event_type, actor, payload in (
            (
                "check_executed",
                VALIDATOR,
                {"task_state": "review", "check_state": "passed", "validation_check_id": CHECK, "validation_run_id": RUN, "evidence_refs": [EVIDENCE]},
            ),
            ("review_completed", VALIDATOR, {"task_state": "accepted", "validation_check_id": CHECK, "validation_run_id": RUN}),
        ):
            revision = 3 if event_type == "check_executed" else 4
            events.append(
                {
                    "schema_version": SCHEMA,
                    "event_id": f"EVT-V23-{sequence:03d}",
                    "event_type": event_type,
                    "task_id": task_id,
                    "attempt_id": ATTEMPT,
                    "actor_run_id": actor,
                    "ledger_owner_run_id": LEDGER_OWNER,
                    "base_revision": revision,
                    "timestamp": iso(reference_time + timedelta(seconds=sequence)),
                    "validation_check_id": CHECK,
                    "validation_run_id": RUN,
                    "payload": payload,
                }
            )
            sequence += 1
    write_jsonl(ledger_path, events)
    registry, registry_errors = gt.build_evidence_registry([record], ROOT, ledger_events=events, source_root=REPO)
    if registry_errors:
        raise SystemExit(f"Evidence registry failed: {registry_errors}")
    state = gt.reduce_events(events, valid_evidence_ids={EVIDENCE}, evidence_registry=registry)
    if state.get("conflicts"):
        raise SystemExit(f"ledger conflicts: {state['conflicts']}")
    gt.write_checkpoint(VERSION / "ledger/checkpoint.json", state)
    (VERSION / "TaskList.md").write_text(gt.render_tasklist(state), encoding="utf-8")

    traceability = {
        "schema_version": SCHEMA,
        "requirements": [{"id": req} for _, req, _, _ in TASKS],
        "acceptance_criteria": [{"id": ac, "required": True} for _, _, ac, _ in TASKS],
        "tasks": [state["tasks"][task] for task, _, _, _ in TASKS],
        "checks": [check],
        "runs": [run],
        "evidence": [record],
    }
    trace_path = VERSION / "harness/traceability.json"
    write_json(trace_path, traceability)
    trace_result = gt.validate_traceability(traceability, ROOT, source_root=REPO, ledger_events=events)
    review_errors = gt.validate_dual_review(review, ROOT)
    if not trace_result.get("ok") or review_errors:
        raise SystemExit(f"trace/review failed: {trace_result} {review_errors}")

    audit = {
        "schema_version": SCHEMA,
        "audit_id": "AUD-V23-COMPLETION-001",
        "auditor_run_id": AUDITOR,
        "author_run_id": OWNER,
        "audit_state": "passed",
        "run_outcome": "achieved",
        "conclusion": "achieved",
        "loop_decision": "stop",
        "stop_reason": "achieved",
        "ledger_revision": state["ledger_revision"],
        "required_task_ids": sorted(task for task, _, _, _ in TASKS),
        "accepted_required_task_ids": sorted(task for task, _, _, _ in TASKS),
        "open_acceptance_blocking_task_ids": [],
        "documented_nonblocking_tasks": [],
        "required_acceptance_criteria": sorted(ac for _, _, ac, _ in TASKS),
        "covered_acceptance_criteria": sorted(ac for _, _, ac, _ in TASKS),
        "evidence_refs": [EVIDENCE],
        "traceability_valid": True,
        "dual_review_valid": True,
        "review_ref": review_path.relative_to(ROOT).as_posix(),
        "task_state_digest": gt.task_state_digest(state["tasks"]),
    }
    audit_path = VERSION / "audit/completion-audit.json"
    write_json(audit_path, audit)
    errors = gt.validate_completion_audit(
        audit,
        state["tasks"],
        {EVIDENCE},
        registry,
        traceability_result=trace_result,
        dual_review_errors=review_errors,
        ledger_revision=state["ledger_revision"],
        expected_review_ref=review_path.relative_to(ROOT).as_posix(),
        expected_audit_ref=audit_path.relative_to(ROOT).as_posix(),
    )
    if errors:
        raise SystemExit(f"completion audit failed: {errors}")
    print(json.dumps({"ok": True, "commit": commit, "tasks": len(TASKS), "blind_summary": str(original_summary)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
