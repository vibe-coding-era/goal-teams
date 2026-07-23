#!/usr/bin/env python3
"""Fail-closed behavior scorer for GT-BENCH-005."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    ROOT / "benchmarks" / "fixtures" / "v2.44" / "testing-capability-cases.json"
)
EVIDENCE_SCHEMA = "goal-teams-testing-capability-evidence-v2.44"
SCORE_SCHEMA = "goal-teams-testing-capability-score-v2.44"
VALID_STATUSES = {"passed", "failed", "not_run"}


class ScoreError(ValueError):
    pass


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def oracle_pass(case_id: str, evidence: dict[str, Any]) -> bool:
    """Recompute outcomes from raw observations instead of trusting declared status."""

    if case_id == "API-AUTH-001":
        before = evidence.get("count_before")
        after = evidence.get("count_after")
        return (
            evidence.get("unauthenticated_status") == 401
            and _number(before)
            and _number(after)
            and after == before
        )
    if case_id == "API-IDEMPOTENCY-001":
        statuses = evidence.get("statuses")
        order_ids = evidence.get("order_ids")
        return (
            statuses == [201, 200]
            and isinstance(order_ids, list)
            and len(order_ids) == 2
            and order_ids[0] is not None
            and order_ids[0] == order_ids[1]
            and evidence.get("replay_header") == "true"
            and evidence.get("count_delta") == 1
        )
    if case_id == "API-CONCURRENCY-001":
        statuses = evidence.get("statuses")
        order_ids = evidence.get("order_ids")
        return (
            isinstance(statuses, list)
            and len(statuses) == 4
            and all(status in {200, 201} for status in statuses)
            and sum(status == 201 for status in statuses) == 1
            and isinstance(order_ids, list)
            and len(order_ids) == 4
            and all(order_id is not None for order_id in order_ids)
            and len(set(order_ids)) == 1
            and evidence.get("unique_order_ids") == 1
            and evidence.get("count_delta") == 1
        )
    if case_id == "API-CONSISTENCY-001":
        polls = evidence.get("polls")
        return (
            evidence.get("create_status") == 201
            and evidence.get("created_order_id") is not None
            and evidence.get("observed_within_window") is True
            and isinstance(polls, list)
            and len(polls) > 0
        )
    if case_id == "E2E-SESSION-001":
        return (
            evidence.get("auth_state_after_reload") == "signed in"
            and _screenshot_observed(evidence)
        )
    if case_id == "E2E-DOUBLE-CLICK-001":
        return evidence.get("delta") == 1 and _screenshot_observed(evidence)
    if case_id == "E2E-REFRESH-001":
        before = evidence.get("count_before_reload")
        after = evidence.get("count_after_reload")
        return (
            _number(before)
            and before > 0
            and _number(after)
            and after == before
            and _screenshot_observed(evidence)
        )
    if case_id == "E2E-RECOVERY-001":
        return (
            evidence.get("retry_visible_after_failure") is True
            and evidence.get("delta") == 1
            and _screenshot_observed(evidence)
        )
    raise ScoreError(f"oracle is not defined for {case_id}")


def _screenshot_observed(evidence: dict[str, Any]) -> bool:
    screenshot = evidence.get("screenshot")
    return isinstance(screenshot, str) and bool(screenshot) and Path(screenshot).is_file()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScoreError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScoreError(f"{path} must contain a JSON object")
    return value


def score_evidence(evidence: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ScoreError("unsupported evidence schema")
    if evidence.get("benchmark_id") != manifest.get("benchmark_id"):
        raise ScoreError("benchmark_id does not match manifest")
    raw_cases = evidence.get("cases")
    if not isinstance(raw_cases, list):
        raise ScoreError("evidence.cases must be an array")

    manifest_cases = manifest.get("cases")
    if not isinstance(manifest_cases, list):
        raise ScoreError("manifest.cases must be an array")
    expected = {
        item["case_id"]: item
        for item in manifest_cases
        if isinstance(item, dict) and isinstance(item.get("case_id"), str)
    }
    observed: dict[str, dict[str, Any]] = {}
    for item in raw_cases:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise ScoreError("every evidence case must be an object with case_id")
        case_id = item["case_id"]
        if case_id in observed:
            raise ScoreError(f"duplicate evidence case: {case_id}")
        if case_id not in expected:
            raise ScoreError(f"unexpected evidence case: {case_id}")
        status = item.get("status")
        if status not in VALID_STATUSES:
            raise ScoreError(f"invalid status for {case_id}: {status!r}")
        behavior_observed = item.get("behavior_observed")
        if not isinstance(behavior_observed, bool):
            raise ScoreError(f"behavior_observed must be boolean for {case_id}")
        if status in {"passed", "failed"} and not behavior_observed:
            raise ScoreError(f"{case_id} claims a behavior result without behavior evidence")
        if not isinstance(item.get("evidence"), dict):
            raise ScoreError(f"{case_id} must include an evidence object")
        if status in {"passed", "failed"}:
            derived = "passed" if oracle_pass(case_id, item["evidence"]) else "failed"
            if status != derived:
                raise ScoreError(
                    f"{case_id} declared {status} but behavior oracle derived {derived}"
                )
        observed[case_id] = item

    missing = sorted(set(expected) - set(observed))
    if missing:
        raise ScoreError(f"missing evidence cases: {', '.join(missing)}")

    scored_cases: list[dict[str, Any]] = []
    earned = 0.0
    by_layer: dict[str, dict[str, float | int]] = {}
    for case_id, contract in expected.items():
        result = observed[case_id]
        weight = contract.get("weight")
        layer = contract.get("layer")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise ScoreError(f"invalid manifest weight for {case_id}")
        if layer not in {"api", "e2e"}:
            raise ScoreError(f"invalid manifest layer for {case_id}")
        case_earned = float(weight) if result["status"] == "passed" else 0.0
        earned += case_earned
        layer_row = by_layer.setdefault(layer, {"earned": 0.0, "maximum": 0.0, "not_run": 0})
        layer_row["earned"] = float(layer_row["earned"]) + case_earned
        layer_row["maximum"] = float(layer_row["maximum"]) + float(weight)
        if result["status"] == "not_run":
            layer_row["not_run"] = int(layer_row["not_run"]) + 1
        scored_cases.append(
            {
                "case_id": case_id,
                "layer": layer,
                "status": result["status"],
                "weight": float(weight),
                "earned": case_earned,
                "behavior_observed": result["behavior_observed"],
                "oracle_recomputed": result["status"] != "not_run",
            }
        )

    maximum = float(manifest.get("maximum_score", -1))
    calculated_maximum = sum(float(item["weight"]) for item in manifest_cases)
    if abs(maximum - calculated_maximum) > 1e-9:
        raise ScoreError("manifest maximum_score does not equal case weights")
    if abs(maximum - 10.0) > 1e-9:
        raise ScoreError("GT-BENCH-005 score must remain a 10 point benchmark")
    not_run = sum(item["status"] == "not_run" for item in observed.values())
    return {
        "schema_version": SCORE_SCHEMA,
        "benchmark_id": manifest["benchmark_id"],
        "candidate": evidence.get("candidate"),
        "score": round(earned, 2),
        "maximum_score": maximum,
        "status": "complete" if not_run == 0 else "partial",
        "not_run_count": not_run,
        "by_layer": by_layer,
        "cases": scored_cases,
        "scoring_basis": "observed_api_and_browser_behavior_only",
        "non_behavior_inputs_counted": False,
        "declared_status_trusted_without_oracle": False,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = score_evidence(load_object(args.evidence), load_object(args.manifest))
    except ScoreError as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
