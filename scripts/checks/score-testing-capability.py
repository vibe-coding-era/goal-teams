#!/usr/bin/env python3
"""Fail-closed V2.44 API/E2E testing-capability score projection."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "references" / "testing-capability-manifest.json"
BENCHMARK_SCORER = (
    ROOT / "scripts" / "benchmark" / "v244_testing_capability_scorer.py"
)
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
    f"GT244-TEST-{index:03d}" for index in range(1, 35)
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
FULL_CHECK_LOG_SUFFIX = (
    "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/full-check.log"
)
SCHEMA_LOG_SUFFIX = (
    "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/schema-validation.log"
)
COMPLETION_AUDIT_SUFFIX = (
    "docs/GoalTeamsWork-V2.44/versions/V2.44/evidence/completion-audit.json"
)
ISSUE_EVIDENCE_BY_ID = {
    "GT244-TEST-001": ("schemas/v2.44/integration-test-plan.schema.json",),
    "GT244-TEST-002": ("schemas/v2.44/test-case.schema.json",),
    "GT244-TEST-003": ("schemas/v2.44/test-case.schema.json",),
    "GT244-TEST-004": ("scripts/checks/validate-test-case-contract.py",),
    "GT244-TEST-005": (
        "schemas/v2.44/test-run-result.schema.json",
        "scripts/checks/validate-test-case-contract.py",
    ),
    "GT244-TEST-006": (
        "scripts/benchmark/v244_testing_capability_runner.py",
        "scripts/benchmark/v244_testing_capability_scorer.py",
    ),
    "GT244-TEST-007": ("references/test-case-assertion-protocol.md",),
    "GT244-TEST-008": ("references/test-case-assertion-protocol.md",),
    "GT244-TEST-009": (
        "prompts/members/qa/prompt.md",
        "prompts/members/reviewer/prompt.md",
    ),
    "GT244-TEST-010": ("references/prompt-cache-manifest.json",),
    "GT244-TEST-011": ("schemas/v2.44/test-run-result.schema.json",),
    "GT244-TEST-012": (
        "scripts/benchmark/v244_testing_capability_runner.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-013": (
        "scripts/benchmark/v244_testing_capability_browser.cjs",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-014": (
        "scripts/checks/score-testing-capability.py",
        "tests/v23/test_v244_testing_capability_score.py",
    ),
    "GT244-TEST-015": (
        "scripts/checks/score-testing-capability.py",
        "prompts/packets/testing-capability-issue-ledger.md",
    ),
    "GT244-TEST-016": (
        "scripts/checks/validate-test-case-contract.py",
        "tests/v23/test_v244_test_contracts.py",
    ),
    "GT244-TEST-017": (
        "scripts/checks/validate-test-case-contract.py",
        "tests/v23/test_v244_test_contracts.py",
    ),
    "GT244-TEST-018": (
        "scripts/checks/validate-test-case-contract.py",
        "tests/v23/test_v244_test_contracts.py",
    ),
    "GT244-TEST-019": (
        "scripts/benchmark/v244_testing_capability_scorer.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-020": (
        "scripts/benchmark/v244_testing_capability_runner.py",
        "scripts/benchmark/v244_testing_capability_scorer.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-021": (
        "schemas/v2.44/integration-test-plan.schema.json",
        "schemas/v2.44/test-run-result.schema.json",
        "scripts/checks/validate-test-case-contract.py",
        "tests/v23/test_v244_test_contracts.py",
    ),
    "GT244-TEST-022": (
        "schemas/v2.44/integration-test-plan.schema.json",
        "scripts/checks/validate-test-case-contract.py",
        "tests/v23/test_v244_test_contracts.py",
    ),
    "GT244-TEST-023": (
        "schemas/v2.44/test-case.schema.json",
        "scripts/checks/validate-test-case-contract.py",
        "tests/v23/test_v244_test_contracts.py",
    ),
    "GT244-TEST-024": (
        "scripts/checks/score-testing-capability.py",
        "tests/v23/test_v244_testing_capability_score.py",
    ),
    "GT244-TEST-025": (
        "scripts/checks/score-testing-capability.py",
        "tests/v23/test_v244_testing_capability_score.py",
    ),
    "GT244-TEST-026": (
        "scripts/checks/score-testing-capability.py",
        "tests/v23/test_v244_testing_capability_score.py",
    ),
    "GT244-TEST-027": (
        "scripts/benchmark/v244_testing_capability_browser.cjs",
        "scripts/benchmark/v244_testing_capability_scorer.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-028": (
        "scripts/checks/score-testing-capability.py",
        "tests/v23/test_v244_testing_capability_score.py",
    ),
    "GT244-TEST-029": (
        "scripts/benchmark/benchmark-runner.py",
        "tests/v23/test_migration_behavior.py",
    ),
    "GT244-TEST-030": (
        "scripts/checks/validate-test-case-contract.py",
        "tests/v23/test_v244_test_contracts.py",
    ),
    "GT244-TEST-031": (
        "scripts/benchmark/v244_testing_capability_runner.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-032": (
        "scripts/benchmark/v244_testing_capability_runner.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-033": (
        "benchmarks/tasks/GT-BENCH-005/reference_app.py",
        "scripts/benchmark/v244_testing_capability_runner.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
    "GT244-TEST-034": (
        "benchmarks/tasks/GT-BENCH-005/reference_app.py",
        "tests/v23/test_v244_testing_capability_benchmark.py",
    ),
}


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
    expected = [
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
    simplified = [
        (row.get("mode"), row.get("expected_detected_by"))
        for row in rows
        if isinstance(row, dict)
    ]
    if simplified != expected:
        raise ScoreError("benchmark summary changed canonical modes or defects")
    reference = [row for row in rows if row.get("mode") == "reference"]
    defects = [row for row in rows if row.get("mode") != "reference"]
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
    for row in rows:
        score_ref = row.get("score_ref")
        evidence_ref = row.get("evidence_ref")
        if not isinstance(score_ref, str) or not isinstance(evidence_ref, str):
            raise ScoreError("benchmark row lacks score/evidence refs")
        score_path = safe_relative_path(path.parent, score_ref)
        evidence_path = safe_relative_path(path.parent, evidence_ref)
        score = load_json(score_path)
        if (
            score.get("provenance_verified") is not True
            or score.get("score") != row.get("score")
            or score.get("not_run_count") != row.get("not_run_count")
            or score.get("canonical_manifest_sha256")
            != "3ace7d9b01e3ca08daf7eef294a5dbfc1c482805faf2426087e223c17bfb6cfe"
        ):
            raise ScoreError("benchmark score provenance is invalid")
        spec = importlib.util.spec_from_file_location(
            "v244_testing_capability_scorer_for_overall_score",
            BENCHMARK_SCORER,
        )
        if spec is None or spec.loader is None:
            raise ScoreError("benchmark scorer cannot be loaded")
        benchmark_scorer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(benchmark_scorer)
        try:
            recomputed = benchmark_scorer.score_evidence(
                benchmark_scorer.load_object(evidence_path),
                evidence_root=evidence_path.parent,
            )
        except benchmark_scorer.ScoreError as exc:
            raise ScoreError("benchmark raw evidence cannot be recomputed") from exc
        if (
            recomputed.get("run_id") != score.get("run_id")
            or recomputed.get("score") != score.get("score")
            or recomputed.get("status") != score.get("status")
            or recomputed.get("not_run_count") != score.get("not_run_count")
            or recomputed.get("provenance_verified") is not True
        ):
            raise ScoreError("benchmark score differs from recomputed raw evidence")


def _require_text_tokens(path: Path, tokens: tuple[str, ...]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ScoreError(f"cannot inspect evidence content: {path}") from exc
    if any(token not in text for token in tokens):
        raise ScoreError(f"evidence content does not prove its claim: {path}")


def validate_full_check_log(path: Path, source_commit: str) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ScoreError("full check receipt cannot be read") from exc
    required = (
        f"Goal Teams source commit: {source_commit}",
        "test_missing_source_git_identity_fails_closed",
        "test_scorer_rejects_valid_black_png_not_bound_to_browser_trace",
        "test_resolved_issue_requires_issue_specific_independent_evidence",
        "OK (skipped=15)",
        "V2.3 unittest and canonical mutation release gates passed.",
        "Deterministic contract validation passed for 5 packages and 9 fixture scenarios",
        "Installer lifecycle checks passed: dirty/dry-run/install/update/failure/rollback/uninstall.",
    )
    match = re.search(r"^Ran ([0-9]+) tests in ", text, re.MULTILINE)
    if (
        len(text.splitlines()) < 800
        or any(token not in text for token in required)
        or match is None
        or int(match.group(1)) < 689
        or re.search(r"^FAILED \(", text, re.MULTILINE)
        or re.search(r"^ERROR: ", text, re.MULTILINE)
    ):
        raise ScoreError("full check receipt is incomplete or contains failures")


def validate_source_artifact(path: Path, suffix: str) -> None:
    if suffix.endswith("integration-test-plan.schema.json"):
        schema = load_json(path)
        required = set(schema.get("required", []))
        if (
            schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
            or schema.get("properties", {})
            .get("schema_version", {})
            .get("const")
            != "goal-teams-integration-test-plan-v2.44"
            or not {
                "revision",
                "owner_identity",
                "validator_identity",
                "risk_coverage",
                "api_case_refs",
                "e2e_case_refs",
            }
            <= required
        ):
            raise ScoreError("integration test plan schema semantics are invalid")
    elif suffix.endswith("test-case.schema.json"):
        schema = load_json(path)
        required = set(schema.get("required", []))
        rendered = canonical_bytes(schema)
        if (
            schema.get("properties", {})
            .get("schema_version", {})
            .get("const")
            != "goal-teams-test-case-v2.44"
            or not {"test_file_refs", "assertions", "cleanup"} <= required
            or any(
                token not in rendered
                for token in (
                    b"risk_scenario",
                    b"oracle_assertion_ref",
                    b"concurrency",
                    b"error_recovery",
                )
            )
        ):
            raise ScoreError("test case schema semantics are invalid")
    elif suffix.endswith("test-run-result.schema.json"):
        schema = load_json(path)
        required = set(schema.get("required", []))
        if (
            schema.get("properties", {})
            .get("schema_version", {})
            .get("const")
            != "goal-teams-test-run-result-v2.44"
            or not {
                "source_binding",
                "runner_identity",
                "attempts",
                "retry",
                "flake",
                "cleanup",
                "replay",
            }
            <= required
        ):
            raise ScoreError("test run result schema semantics are invalid")
    elif suffix.endswith("prompt-cache-manifest.json"):
        manifest = load_json(path)
        routes = manifest.get("routes")
        if (
            not isinstance(routes, dict)
            or "api_integration_testing_repository" not in routes
            or "e2e_testing_repository" not in routes
        ):
            raise ScoreError("specialized prompt routes are missing")
    elif suffix.endswith("api-integration-test-runner/prompt.md"):
        _require_text_tokens(
            path,
            ("runner identity", "test-run-result", "真实 discovery", "fail→pass"),
        )
    elif suffix.endswith("e2e-test-runner/prompt.md"):
        _require_text_tokens(
            path,
            ("runner identity", "test-run-result", "真实 discovery", "fail→pass"),
        )
    elif suffix.endswith("prompts/members/qa/prompt.md"):
        _require_text_tokens(
            path,
            ("风险分母", "sha256", "test-run-result", "blocked/not_run"),
        )
    elif suffix.endswith("test-case-assertion-protocol.md"):
        _require_text_tokens(
            path,
            (
                "authorization",
                "idempotency",
                "concurrency",
                "compensation",
                "error recovery",
                "oracle",
            ),
        )
    elif suffix.endswith("validate-test-case-contract.py"):
        _require_text_tokens(
            path,
            (
                "E_V244_TEST_DISCOVERY",
                "E_V244_RUN_ASSERTION_EVALUATION",
                "E_V244_ARTIFACT_INTEGRITY",
                "_evaluate_comparator",
            ),
        )
    elif suffix.endswith("test_v244_test_contracts.py"):
        _require_text_tokens(
            path,
            (
                "test_each_risk_requires_dedicated_executable_scenario_and_oracle",
                "test_run_result_recomputes_every_supported_comparator",
                "test_run_result_checks_every_artifact_group",
            ),
        )


def current_source_commit() -> str | None:
    """Return the trusted source checkout HEAD, or None outside a Git checkout."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if head.returncode != 0:
        return None
    value = head.stdout.strip()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def validate_verification_summary(
    evidence_root: Path, binding: Any, source_commit: Any
) -> tuple[dict[str, str], dict[str, Any]]:
    ref = validate_ref(evidence_root, binding)
    if not ref["path"].endswith(VERIFICATION_SUFFIX):
        raise ScoreError("verification summary path is not canonical")
    summary = load_json(safe_relative_path(evidence_root, ref["path"]))
    receipts = summary.get("receipts")
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
        or not isinstance(receipts, dict)
        or set(receipts)
        != {
            "full_check",
            "schema_validation",
            "benchmark_runs",
            "independent_review",
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
    if current_source_commit() != source_commit:
        raise ScoreError("verification source commit is not current HEAD")
    full_ref = validate_ref(evidence_root, receipts["full_check"])
    schema_ref = validate_ref(evidence_root, receipts["schema_validation"])
    review_ref = validate_ref(evidence_root, receipts["independent_review"])
    benchmark_refs = receipts["benchmark_runs"]
    if (
        not full_ref["path"].endswith(FULL_CHECK_LOG_SUFFIX)
        or not schema_ref["path"].endswith(SCHEMA_LOG_SUFFIX)
        or not review_ref["path"].endswith(COMPLETION_AUDIT_SUFFIX)
        or not isinstance(benchmark_refs, list)
        or len(benchmark_refs) != 2
    ):
        raise ScoreError("verification receipt paths are not canonical")
    full_log = safe_relative_path(evidence_root, full_ref["path"])
    validate_full_check_log(full_log, source_commit)
    _require_text_tokens(
        safe_relative_path(evidence_root, schema_ref["path"]),
        ("Ajv strict", "3 schemas", "4 canonical examples", "PASS"),
    )
    audit = load_json(safe_relative_path(evidence_root, review_ref["path"]))
    if (
        audit.get("schema_version")
        != "goal-teams-testing-capability-completion-audit-v2.44"
        or audit.get("source_commit") != source_commit
        or audit.get("status") != "passed"
        or audit.get("member_id") != review.get("member_id")
        or audit.get("run_id") != review.get("run_id")
        or audit.get("findings") != []
        or audit.get("resolved_issue_ids") != sorted(REQUIRED_ISSUE_IDS)
    ):
        raise ScoreError("independent completion audit receipt is invalid")
    verified_benchmarks = [validate_ref(evidence_root, item) for item in benchmark_refs]
    for item in verified_benchmarks:
        validate_benchmark_summary(safe_relative_path(evidence_root, item["path"]))
    return ref, {
        "review_ref": review_ref,
        "review_run_id": review["run_id"],
    }


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
        else:
            for path in matches:
                validate_source_artifact(
                    safe_relative_path(evidence_root, path), suffix
                )
    return verified


def load_issue_projection(
    evidence_root: Path,
    ledger_binding: Any,
    manifest: dict[str, Any],
    *,
    review_ref: dict[str, str],
    review_run_id: str,
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
            verified_resolution = [
                validate_ref(evidence_root, item) for item in refs
            ]
            required_suffixes = ISSUE_EVIDENCE_BY_ID.get(issue_id)
            paths = [item["path"] for item in verified_resolution]
            if (
                not required_suffixes
                or event["agent_run_id"] != review_run_id
                or review_ref not in verified_resolution
                or any(
                    not any(path.endswith(suffix) for path in paths)
                    for suffix in required_suffixes
                )
            ):
                raise ScoreError(
                    f"resolved issue lacks issue-specific independent evidence at line {line_number}"
                )
            resolved_evidence[issue_id] = verified_resolution
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
    _verification_ref, verification = validate_verification_summary(
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
        evidence_root,
        evidence.get("issue_ledger"),
        manifest,
        review_ref=verification["review_ref"],
        review_run_id=verification["review_run_id"],
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
