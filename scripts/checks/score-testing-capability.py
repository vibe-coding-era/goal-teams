#!/usr/bin/env python3
"""Fail-closed V2.44 API/E2E testing-capability score projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "references" / "testing-capability-manifest.json"
EVIDENCE_SCHEMA = "goal-teams-testing-capability-evidence-v2.44"
SCORE_SCHEMA = "goal-teams-testing-capability-score-v2.44"
ISSUE_SCHEMA = "goal-teams-testing-issue-event-v2.44"
ISSUE_RE = re.compile(r"^GT244-TEST-[0-9]{3}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PASS = "passed"
STATUSES = {"not_run", "failed", "partial", PASS}
CANONICAL_TARGET = 100
CANONICAL_ANTI_GAMING = {
    "blocked_counts_as_passed": False,
    "not_run_counts_as_passed": False,
    "unavailable_counts_as_passed": False,
    "retry_pass_hides_initial_failure": False,
    "missing_denominator_allowed": False,
    "prose_or_exit_code_is_behavior_oracle": False,
    "issue_deletion_allowed": False,
}
CANONICAL_RUBRIC = {
    "role_independence": (
        15,
        ("independent_test_roles", "specialized_prompt_routes"),
    ),
    "machine_contracts": (
        20,
        (
            "integration_test_plan_schema",
            "typed_test_case_schema",
            "test_run_result_schema",
            "semantic_positive_negative",
            "file_identity_validation",
        ),
    ),
    "api_testing": (
        15,
        (
            "api_typed_fields",
            "api_risk_model",
            "api_reference_behavior",
            "api_seeded_defects",
        ),
    ),
    "e2e_testing": (
        15,
        (
            "e2e_typed_fields",
            "e2e_resilience_model",
            "e2e_reference_behavior",
            "e2e_seeded_defects",
        ),
    ),
    "run_evidence": (
        15,
        (
            "runner_source_identity",
            "attempt_history",
            "observed_assertions",
            "retry_flake_preservation",
            "cleanup_replay",
        ),
    ),
    "risk_environment_data_coverage": (
        10,
        (
            "risk_denominator",
            "environment_data_binding",
            "case_coverage_mapping",
            "qa_reviewer_denominator",
        ),
    ),
    "real_behavior_benchmark": (
        10,
        (
            "reference_ten_of_ten",
            "seeded_defect_detection",
            "reference_repeatability",
            "benchmark_cleanup",
        ),
    ),
}
REQUIRED_ISSUE_IDS = {
    f"GT244-TEST-{index:03d}" for index in range(1, 25)
}
CHECK_EVIDENCE_SUFFIXES = {
    "independent_test_roles": (
        "prompts/members/api-integration-test-runner/prompt.md",
        "prompts/members/e2e-test-runner/prompt.md",
    ),
    "specialized_prompt_routes": ("references/prompt-cache-manifest.json",),
    "integration_test_plan_schema": (
        "schemas/v2.44/integration-test-plan.schema.json",
    ),
    "typed_test_case_schema": ("schemas/v2.44/test-case.schema.json",),
    "test_run_result_schema": ("schemas/v2.44/test-run-result.schema.json",),
    "semantic_positive_negative": ("tests/v23/test_v244_test_contracts.py",),
    "file_identity_validation": (
        "scripts/checks/validate-test-case-contract.py",
    ),
    "api_typed_fields": ("schemas/v2.44/test-case.schema.json",),
    "api_risk_model": ("references/test-case-assertion-protocol.md",),
    "api_reference_behavior": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
    "api_seeded_defects": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
    "e2e_typed_fields": ("schemas/v2.44/test-case.schema.json",),
    "e2e_resilience_model": ("references/test-case-assertion-protocol.md",),
    "e2e_reference_behavior": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
    "e2e_seeded_defects": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
    "runner_source_identity": ("schemas/v2.44/test-run-result.schema.json",),
    "attempt_history": ("schemas/v2.44/test-run-result.schema.json",),
    "observed_assertions": ("scripts/checks/validate-test-case-contract.py",),
    "retry_flake_preservation": (
        "tests/v23/test_v244_test_contracts.py",
    ),
    "cleanup_replay": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
    "risk_denominator": (
        "schemas/v2.44/integration-test-plan.schema.json",
    ),
    "environment_data_binding": (
        "schemas/v2.44/integration-test-plan.schema.json",
    ),
    "case_coverage_mapping": (
        "scripts/checks/validate-test-case-contract.py",
    ),
    "qa_reviewer_denominator": ("prompts/members/qa/prompt.md",),
    "reference_ten_of_ten": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
    "seeded_defect_detection": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
    "reference_repeatability": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-2/self-check-summary.json",
    ),
    "benchmark_cleanup": (
        "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/benchmark-final-1/self-check-summary.json",
    ),
}
VERIFICATION_SUFFIX = (
    "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/verification-summary.json"
)


class ScoreError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScoreError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ScoreError(f"expected JSON object: {path}")
    return value


def validate_canonical_manifest(manifest: dict[str, Any]) -> None:
    if (
        manifest.get("schema_version")
        != "goal-teams-testing-capability-v2.44"
        or manifest.get("product_version") != "V2.44"
        or manifest.get("target_score") != CANONICAL_TARGET
        or manifest.get("score_statuses")
        != ["not_run", "failed", "partial", "passed"]
        or manifest.get("anti_gaming") != CANONICAL_ANTI_GAMING
    ):
        raise ScoreError("manifest does not match canonical rubric")
    dimensions = manifest.get("dimensions")
    if not isinstance(dimensions, list) or len(dimensions) != len(CANONICAL_RUBRIC):
        raise ScoreError("manifest does not match canonical rubric")
    observed: dict[str, tuple[int, tuple[str, ...]]] = {}
    for item in dimensions:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "name_zh",
            "weight",
            "required_checks",
        }:
            raise ScoreError("manifest does not match canonical rubric")
        if (
            not isinstance(item.get("id"), str)
            or not isinstance(item.get("name_zh"), str)
            or not item["name_zh"]
            or not isinstance(item.get("weight"), int)
            or not isinstance(item.get("required_checks"), list)
            or not all(isinstance(value, str) for value in item["required_checks"])
        ):
            raise ScoreError("manifest does not match canonical rubric")
        observed[item["id"]] = (
            item["weight"],
            tuple(item["required_checks"]),
        )
    if observed != CANONICAL_RUBRIC:
        raise ScoreError("manifest does not match canonical rubric")
    issues = manifest.get("known_issues")
    if not isinstance(issues, list):
        raise ScoreError("manifest known issues are invalid")
    issue_ids = {
        item.get("id")
        for item in issues
        if isinstance(item, dict) and set(item) == {"id", "dimension", "summary"}
    }
    if len(issue_ids) != len(issues) or not REQUIRED_ISSUE_IDS <= issue_ids:
        raise ScoreError("manifest known issue set is incomplete")


def safe_relative_path(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str):
        raise ScoreError("evidence path must be a string")
    relative = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ScoreError(f"unsafe evidence path: {raw!r}")
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ScoreError(f"evidence path escapes root: {raw!r}") from exc
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ScoreError(f"evidence file missing or unsafe: {raw}") from exc
        if stat.S_ISLNK(mode):
            raise ScoreError(f"evidence path contains symlink: {raw}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise ScoreError(f"evidence parent is not a directory: {raw}")
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise ScoreError(f"evidence file missing or unsafe: {raw}")
    return candidate


def validate_ref(root: Path, value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ScoreError("evidence ref must contain exactly path and sha256")
    digest = value.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ScoreError("evidence ref has invalid sha256")
    path = safe_relative_path(root, value.get("path"))
    actual = file_sha256(path)
    if actual != digest:
        raise ScoreError(f"evidence digest drift: {value['path']}")
    return {"path": value["path"], "sha256": digest}


def validate_benchmark_summary(path: Path) -> None:
    summary = load_json(path)
    rows = summary.get("candidate_runs")
    if (
        summary.get("schema_version")
        != "goal-teams-testing-capability-self-check-v2.44"
        or summary.get("status") != "passed"
        or summary.get("behavior_run") != "executed"
        or summary.get("reference_repeatable") is not True
        or summary.get("not_run_count_total") != 0
        or summary.get("all_services_terminated") is not True
        or not isinstance(rows, list)
        or len(rows) != 9
    ):
        raise ScoreError("benchmark summary is not a complete passing run")
    reference = [row for row in rows if isinstance(row, dict) and row.get("mode") == "reference"]
    defects = [row for row in rows if isinstance(row, dict) and row.get("mode") != "reference"]
    if (
        len(reference) != 1
        or reference[0].get("score") != 10.0
        or reference[0].get("not_run_count") != 0
        or len(defects) != 8
        or any(
            row.get("not_run_count") != 0
            or row.get("service_terminated") is not True
            or row.get("detected") != row.get("expected_detected_by")
            for row in defects
        )
    ):
        raise ScoreError("benchmark summary does not prove canonical behavior")


def validate_verification_summary(
    evidence_root: Path, binding: Any, source_commit: Any
) -> dict[str, str]:
    ref = validate_ref(evidence_root, binding)
    if not ref["path"].endswith(VERIFICATION_SUFFIX):
        raise ScoreError("verification summary path is not canonical")
    summary = load_json(safe_relative_path(evidence_root, ref["path"]))
    if (
        not isinstance(source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or summary.get("schema_version")
        != "goal-teams-testing-capability-verification-v2.44"
        or summary.get("product_version") != "V2.44"
        or summary.get("source_commit") != source_commit
        or summary.get("full_check") != {
            "status": "passed",
            "failed": 0,
            "errors": 0,
        }
        or summary.get("schema_validation") != {"status": "passed"}
        or summary.get("benchmark_replay") != {
            "status": "passed",
            "runs": 2,
            "not_run": 0,
        }
    ):
        raise ScoreError("verification summary is incomplete or mismatched")
    review = summary.get("independent_review")
    if (
        not isinstance(review, dict)
        or review.get("status") != "passed"
        or not isinstance(review.get("member_id"), str)
        or not review["member_id"]
        or review.get("member_id") == "goal-lead-v244"
        or not isinstance(review.get("run_id"), str)
        or not review["run_id"]
    ):
        raise ScoreError("independent review is missing")
    return ref


def validate_check_evidence(
    evidence_root: Path, check_id: str, refs: list[Any]
) -> list[dict[str, str]]:
    required = CHECK_EVIDENCE_SUFFIXES.get(check_id)
    if required is None:
        raise ScoreError(f"no canonical evidence rule for check: {check_id}")
    verified = [validate_ref(evidence_root, item) for item in refs]
    paths = [item["path"] for item in verified]
    for suffix in required:
        matches = [path for path in paths if path.endswith(suffix)]
        if not matches:
            raise ScoreError(f"check evidence is unrelated: {check_id}")
        if suffix.endswith("self-check-summary.json"):
            for path in matches:
                validate_benchmark_summary(safe_relative_path(evidence_root, path))
    return verified


def load_issue_projection(
    evidence_root: Path, ledger_binding: Any, manifest: dict[str, Any]
) -> tuple[dict[str, str], dict[str, Any]]:
    if not isinstance(ledger_binding, dict) or set(ledger_binding) != {
        "path",
        "sha256",
    }:
        raise ScoreError("issue_ledger must contain exactly path and sha256")
    ledger_ref = validate_ref(evidence_root, ledger_binding)
    ledger_path = safe_relative_path(evidence_root, ledger_ref["path"])
    manifest_issues = {
        item["id"]: item
        for item in manifest.get("known_issues", [])
        if isinstance(item, dict)
        and set(item) == {"id", "dimension", "summary"}
        and isinstance(item.get("id"), str)
    }
    seen_events: set[str] = set()
    projection: dict[str, str] = {}
    resolved_evidence: dict[str, list[dict[str, str]]] = {}
    discovered: set[str] = set()
    event_fields = {
        "schema_version",
        "event_id",
        "issue_id",
        "event_type",
        "dimension",
        "summary",
        "severity",
        "status",
        "artifact_refs",
        "evidence_refs",
        "agent_run_id",
        "timestamp",
    }
    event_statuses = {
        "discovered": "open",
        "started": "in_progress",
        "resolved": "resolved",
        "reopened": "open",
    }
    for line_number, raw in enumerate(
        ledger_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScoreError(f"invalid issue ledger JSONL line {line_number}") from exc
        if (
            not isinstance(event, dict)
            or set(event) != event_fields
            or event.get("schema_version") != ISSUE_SCHEMA
        ):
            raise ScoreError(f"invalid issue event at line {line_number}")
        event_id = event.get("event_id")
        issue_id = event.get("issue_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen_events:
            raise ScoreError(f"duplicate or missing event_id at line {line_number}")
        if not isinstance(issue_id, str) or not ISSUE_RE.fullmatch(issue_id):
            raise ScoreError(f"invalid issue_id at line {line_number}")
        expected = manifest_issues.get(issue_id)
        if expected is None:
            raise ScoreError(f"unknown issue at line {line_number}")
        if (
            event.get("dimension") != expected["dimension"]
            or event.get("summary") != expected["summary"]
        ):
            raise ScoreError(f"issue metadata mismatch at line {line_number}")
        event_type = event.get("event_type")
        status = event.get("status")
        if event_type not in event_statuses or status != event_statuses[event_type]:
            raise ScoreError(f"invalid issue status at line {line_number}")
        if (
            not isinstance(event.get("severity"), str)
            or event["severity"] not in {"low", "medium", "high", "critical"}
            or not isinstance(event.get("artifact_refs"), list)
            or not isinstance(event.get("evidence_refs"), list)
            or not isinstance(event.get("agent_run_id"), str)
            or not event["agent_run_id"]
            or not isinstance(event.get("timestamp"), str)
            or not event["timestamp"]
        ):
            raise ScoreError(f"invalid issue event metadata at line {line_number}")
        previous_status = projection.get(issue_id)
        if event_type == "discovered":
            if previous_status is not None:
                raise ScoreError(f"duplicate issue discovery at line {line_number}")
            discovered.add(issue_id)
        elif issue_id not in discovered:
            raise ScoreError(f"issue transition before discovery at line {line_number}")
        elif event_type == "started" and previous_status != "open":
            raise ScoreError(f"invalid issue transition at line {line_number}")
        elif event_type == "resolved" and previous_status not in {"open", "in_progress"}:
            raise ScoreError(f"invalid issue transition at line {line_number}")
        elif event_type == "reopened" and previous_status != "resolved":
            raise ScoreError(f"invalid issue transition at line {line_number}")
        if status == "resolved":
            refs = event.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                raise ScoreError(f"resolved issue lacks evidence at line {line_number}")
            resolved_evidence[issue_id] = [
                validate_ref(evidence_root, item) for item in refs
            ]
        seen_events.add(event_id)
        projection[issue_id] = status

    known = set(manifest_issues)
    if known != set(projection):
        raise ScoreError(
            "known issue ledger mismatch: "
            f"missing={sorted(known - projection.keys())}, "
            f"extra={sorted(projection.keys() - known)}"
        )
    unresolved = sorted(
        issue_id for issue_id, status in projection.items() if status != "resolved"
    )
    return projection, {
        "ref": ledger_ref,
        "event_count": len(seen_events),
        "issue_count": len(projection),
        "known_issue_count": len(known),
        "unresolved_issue_ids": unresolved,
        "resolved_evidence": resolved_evidence,
    }


def score(
    evidence: dict[str, Any],
    manifest: dict[str, Any],
    *,
    evidence_root: Path,
    manifest_digest: str,
) -> dict[str, Any]:
    validate_canonical_manifest(manifest)
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ScoreError("unsupported evidence schema")
    validate_verification_summary(
        evidence_root,
        evidence.get("verification_summary"),
        evidence.get("source_commit"),
    )
    if evidence.get("product_version") != manifest.get("product_version"):
        raise ScoreError("product version mismatch")
    if evidence.get("manifest_sha256") != manifest_digest:
        raise ScoreError("manifest digest mismatch")
    anti_gaming = manifest.get("anti_gaming")
    if not isinstance(anti_gaming, dict) or any(anti_gaming.values()):
        raise ScoreError("anti-gaming manifest must keep every bypass disabled")

    dimensions = manifest.get("dimensions")
    supplied = evidence.get("dimensions")
    if not isinstance(dimensions, list) or not isinstance(supplied, dict):
        raise ScoreError("dimensions missing")
    expected_ids = [item.get("id") for item in dimensions if isinstance(item, dict)]
    if len(expected_ids) != len(dimensions) or set(supplied) != set(expected_ids):
        raise ScoreError("dimension set mismatch")
    if sum(item.get("weight", 0) for item in dimensions) != manifest.get("target_score"):
        raise ScoreError("dimension weights do not equal target score")

    score_rows: list[dict[str, Any]] = []
    total = 0
    all_refs: list[dict[str, str]] = []
    for dimension in dimensions:
        dimension_id = dimension["id"]
        weight = dimension.get("weight")
        required = dimension.get("required_checks")
        provided = supplied[dimension_id]
        checks = provided.get("checks") if isinstance(provided, dict) else None
        if (
            not isinstance(weight, int)
            or weight <= 0
            or not isinstance(required, list)
            or not required
            or len(set(required)) != len(required)
            or not isinstance(checks, dict)
            or set(checks) != set(required)
        ):
            raise ScoreError(f"invalid dimension contract: {dimension_id}")
        check_rows: list[dict[str, Any]] = []
        for check_id in required:
            check = checks[check_id]
            if not isinstance(check, dict) or set(check) != {"status", "evidence_refs"}:
                raise ScoreError(f"invalid check shape: {dimension_id}.{check_id}")
            status = check.get("status")
            refs = check.get("evidence_refs")
            if status not in STATUSES or not isinstance(refs, list) or not refs:
                raise ScoreError(f"invalid check result: {dimension_id}.{check_id}")
            verified_refs = validate_check_evidence(
                evidence_root, check_id, refs
            )
            all_refs.extend(verified_refs)
            check_rows.append(
                {
                    "check_id": check_id,
                    "status": status,
                    "evidence_refs": verified_refs,
                }
            )
        dimension_passed = all(row["status"] == PASS for row in check_rows)
        earned = weight if dimension_passed else 0
        total += earned
        score_rows.append(
            {
                "dimension_id": dimension_id,
                "name_zh": dimension.get("name_zh"),
                "status": PASS if dimension_passed else "failed",
                "earned": earned,
                "possible": weight,
                "checks": check_rows,
            }
        )

    projection, issue_summary = load_issue_projection(
        evidence_root, evidence.get("issue_ledger"), manifest
    )
    achieved = (
        total == manifest.get("target_score")
        and not issue_summary["unresolved_issue_ids"]
        and all(row["status"] == PASS for row in score_rows)
    )
    return {
        "schema_version": SCORE_SCHEMA,
        "product_version": manifest["product_version"],
        "status": "achieved" if achieved else "failed",
        "score": total,
        "target_score": manifest["target_score"],
        "dimensions": score_rows,
        "issue_projection": projection,
        "issue_summary": issue_summary,
        "verified_evidence_ref_count": len(all_refs),
        "manifest_sha256": manifest_digest,
        "anti_gaming": anti_gaming,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="return zero even when the evidence does not achieve 100/100",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_json(DEFAULT_MANIFEST)
        manifest_digest = file_sha256(DEFAULT_MANIFEST)
        result = score(
            load_json(args.evidence),
            manifest,
            evidence_root=args.evidence_root.resolve(),
            manifest_digest=manifest_digest,
        )
    except ScoreError as exc:
        result = {
            "schema_version": SCORE_SCHEMA,
            "status": "failed",
            "score": 0,
            "error": str(exc),
        }
    rendered = canonical_bytes(result).decode("utf-8") + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result.get("status") == "achieved" or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
