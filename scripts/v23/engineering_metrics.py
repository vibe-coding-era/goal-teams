#!/usr/bin/env python3
"""Deterministic V2.43 engineering-metrics calculator and OKF renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "references" / "engineering-metrics-manifest.json"
SCHEMA_VERSION = "goal-teams-engineering-metrics-v2.43"
CALCULATOR_VERSION = "V2.43"
FINAL = "final"
VALID_STATUSES = {
    "final", "provisional", "pending", "unavailable",
    "not_applicable", "insufficient_sample",
}
VALID_EVENT_TYPES = {
    "acceptance_attempt",
    "change_deployed",
    "change_rolled_back",
    "change_unit_declared",
    "context_segment_loaded",
    "context_segment_used",
    "cost_observed",
    "defect_escaped",
    "failure_detected",
    "failure_observation_closed",
    "failure_recovered",
    "goal_converged",
    "goal_observation_closed",
    "human_escalation",
    "human_escalation_observation_closed",
    "production_observation_closed",
    "repair_loop_completed",
    "review_defect_caught",
    "review_defect_missed",
    "review_observation_closed",
    "spec_ambiguity",
    "spec_ambiguity_observation_closed",
    "ssot_drift",
    "ssot_drift_observation_closed",
    "telemetry_coverage",
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class EngineeringMetricsError(ValueError):
    """Fail-closed input or contract error."""


class EngineeringMetricsManifest(dict[str, Any]):
    """Validated manifest with an exact source-bytes identity."""

    source_sha256: str


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    raw = value if isinstance(value, bytes) else _canonical_bytes(value)
    return hashlib.sha256(raw).hexdigest()


def _strict_load(path: Path) -> Any:
    seen_duplicate = False

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal seen_duplicate
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                seen_duplicate = True
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EngineeringMetricsError(f"E_METRICS_JSON:{path}") from exc
    if seen_duplicate:
        raise EngineeringMetricsError(f"E_METRICS_DUPLICATE_KEY:{path}")
    return value


def load_manifest(path: Path | str = MANIFEST_PATH) -> dict[str, Any]:
    source_path = Path(path)
    manifest = _strict_load(source_path)
    if not isinstance(manifest, dict):
        raise EngineeringMetricsError("E_METRICS_MANIFEST_TYPE")
    if manifest.get("metric_schema_version") != SCHEMA_VERSION:
        raise EngineeringMetricsError("E_METRICS_MANIFEST_SCHEMA")
    if manifest.get("calculator_version") != CALCULATOR_VERSION:
        raise EngineeringMetricsError("E_METRICS_MANIFEST_CALCULATOR")
    metrics = manifest.get("metrics")
    required_fields = {
        "metric_id", "full_name", "chinese_name", "unit", "aggregation",
        "formula", "numerator_definition", "denominator_definition",
        "exclusions", "current_task_rule", "previous_rule",
        "recent_aggregation_rule", "availability_rule",
    }
    if not isinstance(metrics, list) or len(metrics) != 12:
        raise EngineeringMetricsError("E_METRICS_MANIFEST_COUNT")
    ids: list[str] = []
    for metric in metrics:
        if not isinstance(metric, dict) or not required_fields.issubset(metric):
            raise EngineeringMetricsError("E_METRICS_MANIFEST_METRIC")
        if any(not isinstance(metric[field], str) or not metric[field] for field in required_fields):
            raise EngineeringMetricsError("E_METRICS_MANIFEST_FIELD")
        ids.append(metric["metric_id"])
    if len(ids) != len(set(ids)):
        raise EngineeringMetricsError("E_METRICS_MANIFEST_DUPLICATE_ID")
    statuses = manifest.get("statuses")
    if not isinstance(statuses, list) or set(statuses) != VALID_STATUSES:
        raise EngineeringMetricsError("E_METRICS_MANIFEST_STATUSES")
    validated = EngineeringMetricsManifest(manifest)
    try:
        validated.source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EngineeringMetricsError("E_METRICS_MANIFEST_READ") from exc
    return validated


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    # The public contract binds the exact machine-SSOT bytes, not a
    # re-serialization that could hide whitespace or ordering drift.
    source_digest = getattr(manifest, "source_sha256", None)
    if isinstance(source_digest, str) and _HEX64.fullmatch(source_digest):
        return source_digest
    canonical_manifest = _strict_load(MANIFEST_PATH)
    if manifest == canonical_manifest:
        try:
            return hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        except OSError as exc:
            raise EngineeringMetricsError("E_METRICS_MANIFEST_READ") from exc
    return _sha256(manifest)


def _require_string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineeringMetricsError(code)
    return value.strip()


def _number(value: Any, code: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineeringMetricsError(code)
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise EngineeringMetricsError(code)
    return result


def _timestamp(value: Any, code: str) -> str:
    raw = _require_string(value, code)
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EngineeringMetricsError(code) from exc
    return raw


def _event_id(event: Mapping[str, Any]) -> str:
    return _require_string(event.get("event_id"), "E_METRICS_EVENT_ID")


def _apply_corrections(raw_events: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_events, list):
        raise EngineeringMetricsError("E_METRICS_EVENTS")
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    corrections: list[dict[str, Any]] = []
    for raw in raw_events:
        if not isinstance(raw, dict):
            raise EngineeringMetricsError("E_METRICS_EVENT")
        event = dict(raw)
        event_id = _event_id(event)
        if event_id in by_id or any(item.get("event_id") == event_id for item in corrections):
            raise EngineeringMetricsError(f"E_METRICS_DUPLICATE_EVENT:{event_id}")
        event_type = _require_string(event.get("type"), "E_METRICS_EVENT_TYPE")
        if event_type == "correction":
            corrections.append(event)
        else:
            by_id[event_id] = event
            order.append(event_id)
    for correction in corrections:
        target = _require_string(
            correction.get("target_event_id"), "E_METRICS_CORRECTION_TARGET"
        )
        if target not in by_id:
            raise EngineeringMetricsError(f"E_METRICS_CORRECTION_MISSING:{target}")
        replacement = correction.get("replacement")
        if replacement is None:
            del by_id[target]
            continue
        if not isinstance(replacement, dict):
            raise EngineeringMetricsError("E_METRICS_CORRECTION_REPLACEMENT")
        updated = dict(replacement)
        updated["event_id"] = target
        _require_string(updated.get("type"), "E_METRICS_EVENT_TYPE")
        by_id[target] = updated
    resolved = [by_id[event_id] for event_id in order if event_id in by_id]
    for event in resolved:
        event_type = event.get("type")
        if event_type not in VALID_EVENT_TYPES:
            raise EngineeringMetricsError(f"E_METRICS_UNKNOWN_EVENT_TYPE:{event_type}")
    return resolved


def _cohort(run: Mapping[str, Any]) -> dict[str, str]:
    benchmark = run.get("benchmark")
    if benchmark is not None:
        if not isinstance(benchmark, dict):
            raise EngineeringMetricsError("E_METRICS_BENCHMARK_COHORT")
        return {
            "kind": "benchmark",
            "scenario_id": _require_string(benchmark.get("scenario_id"), "E_METRICS_SCENARIO"),
            "execution_mode": _require_string(benchmark.get("execution_mode"), "E_METRICS_MODE"),
            "rubric_digest": _require_string(benchmark.get("rubric_digest"), "E_METRICS_RUBRIC"),
            "model_and_config_identity": _require_string(
                benchmark.get("model_and_config_identity"), "E_METRICS_MODEL_IDENTITY"
            ),
            "metric_schema_version": SCHEMA_VERSION,
        }
    return {
        "kind": "task",
        "repository_or_project_id": _require_string(
            run.get("repository_or_project_id"), "E_METRICS_PROJECT_ID"
        ),
        "work_type": _require_string(run.get("work_type"), "E_METRICS_WORK_TYPE"),
        "execution_profile": _require_string(
            run.get("execution_profile"), "E_METRICS_EXECUTION_PROFILE"
        ),
        "metric_schema_version": SCHEMA_VERSION,
    }


def _result(
    metric_id: str,
    status: str,
    numerator: float | int | None,
    denominator: float | int | None,
    value: float | int | None,
    unit: str,
    refs: Iterable[str] = (),
    **extra: Any,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise EngineeringMetricsError("E_METRICS_STATUS")
    result: dict[str, Any] = {
        "metric_id": metric_id,
        "calculator_version": CALCULATOR_VERSION,
        "status": status,
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "unit": unit,
        "evidence_refs": sorted(set(refs)),
        "event_ids": [],
        "coverage": None,
        "observation_window": None,
        "weight_basis": None,
    }
    for key, item in extra.items():
        if item is not None:
            result[key] = item
    return result


def _events_of(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [event for event in events if event.get("type") == kind]


def _domain_coverage_events(events: Sequence[Mapping[str, Any]], domain: str) -> list[Mapping[str, Any]]:
    matched = _events_of(events, "goal_observation_closed") + _events_of(events, f"{domain}_observation_closed")
    for event in _events_of(events, "telemetry_coverage"):
        domains = event.get("domains")
        if event.get("complete", True) is True and isinstance(domains, list) and domain in domains:
            matched.append(event)
    return matched


def _unit_id(event: Mapping[str, Any], code: str = "E_METRICS_CHANGE_UNIT") -> str:
    return _require_string(event.get("change_unit_id"), code)


def _hash_signature(signature: str) -> str:
    return hashlib.sha256(signature.strip().lower().encode("utf-8")).hexdigest()


def _historical_signature_hashes(history: Sequence[Mapping[str, Any]], cohort: Mapping[str, Any], window: int) -> set[str]:
    comparable = _comparable_history(history, cohort)[-window:]
    found: set[str] = set()
    for summary in comparable:
        facts = summary.get("comparison_facts", {})
        hashes = facts.get("failure_signature_hashes", []) if isinstance(facts, dict) else []
        if isinstance(hashes, list):
            found.update(item for item in hashes if isinstance(item, str) and _HEX64.fullmatch(item))
    return found


def _calculate_current(
    events: Sequence[Mapping[str, Any]],
    history: Sequence[Mapping[str, Any]],
    cohort: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    metric_meta = {item["metric_id"]: item for item in manifest["metrics"]}
    current: dict[str, dict[str, Any]] = {}

    declared_events = _events_of(events, "change_unit_declared")
    declared: list[str] = []
    declared_refs: list[str] = []
    for event in declared_events:
        unit = _unit_id(event)
        if unit not in declared:
            declared.append(unit)
        declared_refs.append(_event_id(event))
    attempts: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in _events_of(events, "acceptance_attempt"):
        if event.get("independent_validator") is True:
            unit = _unit_id(event)
            if unit in declared:
                attempt = event.get("attempt")
                if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
                    raise EngineeringMetricsError("E_METRICS_ACCEPTANCE_ATTEMPT")
                if event.get("outcome") not in {"passed", "failed"}:
                    raise EngineeringMetricsError("E_METRICS_ACCEPTANCE_OUTCOME")
                attempts[unit].append(event)
    for unit_events in attempts.values():
        unit_events.sort(key=lambda event: (int(event.get("attempt", 10**9)), _event_id(event)))
    first_pass = sum(
        1 for unit in declared
        if attempts.get(unit) and attempts[unit][0].get("outcome") == "passed"
    )
    accepted = {
        unit for unit in declared
        if any(event.get("outcome") == "passed" for event in attempts.get(unit, []))
    }
    acceptance_refs = [_event_id(event) for values in attempts.values() for event in values]
    attempted_units = {unit for unit in declared if attempts.get(unit)}
    if declared and len(attempted_units) == len(declared):
        current["FPAR"] = _result(
            "FPAR", FINAL, first_pass, len(declared), first_pass / len(declared),
            metric_meta["FPAR"]["unit"], declared_refs + acceptance_refs,
            coverage=1.0,
        )
    elif declared:
        current["FPAR"] = _result(
            "FPAR", "pending", first_pass, len(declared), None,
            metric_meta["FPAR"]["unit"], declared_refs + acceptance_refs,
            coverage=len(attempted_units) / len(declared),
            unavailable_reason="formal_acceptance_incomplete",
        )
    else:
        current["FPAR"] = _result("FPAR", "unavailable", None, None, None, metric_meta["FPAR"]["unit"])

    loops = _events_of(events, "repair_loop_completed")
    converged = _events_of(events, "goal_converged")
    if converged:
        current["LCC"] = _result(
            "LCC", FINAL, len(loops), 1, float(len(loops)), metric_meta["LCC"]["unit"],
            [_event_id(item) for item in loops + converged],
        )
    else:
        current["LCC"] = _result(
            "LCC", "pending", len(loops), 0, None, metric_meta["LCC"]["unit"],
            [_event_id(item) for item in loops], lower_bound=len(loops),
        )

    escalation_exclusions = {"flow_selection", "planned_checkpoint", "ordinary_confirmation"}
    escalations = [
        event for event in _events_of(events, "human_escalation")
        if event.get("reason_type") not in escalation_exclusions
    ]
    her_coverage_events = _domain_coverage_events(events, "human_escalation")
    her_covered = bool(her_coverage_events)
    if not escalations and not her_covered:
        current["HER"] = _result(
            "HER", "unavailable", None, None, None, metric_meta["HER"]["unit"],
            unavailable_reason="missing_telemetry_coverage",
        )
    else:
        current["HER"] = _result(
            "HER", FINAL if her_covered else "provisional", int(bool(escalations)), 1,
            float(bool(escalations)), metric_meta["HER"]["unit"],
            [_event_id(item) for item in escalations + her_coverage_events],
            coverage=1.0 if her_covered else None,
        )
    ambiguities = [event for event in _events_of(events, "spec_ambiguity") if event.get("blocked") is True]
    sar_coverage_events = _domain_coverage_events(events, "spec_ambiguity")
    sar_covered = bool(sar_coverage_events)
    if not ambiguities and not sar_covered:
        current["SAR"] = _result(
            "SAR", "unavailable", None, None, None, metric_meta["SAR"]["unit"],
            unavailable_reason="missing_telemetry_coverage",
        )
    else:
        current["SAR"] = _result(
            "SAR", FINAL if sar_covered else "provisional", int(bool(ambiguities)), 1,
            float(bool(ambiguities)), metric_meta["SAR"]["unit"],
            [_event_id(item) for item in ambiguities + sar_coverage_events],
            coverage=1.0 if sar_covered else None,
        )

    trusted_costs: list[Mapping[str, Any]] = []
    for event in _events_of(events, "cost_observed"):
        if event.get("source_trust") in {"trusted", "derived"}:
            # Missing telemetry is not a trustworthy zero: both components
            # must be explicit even when one of them is genuinely 0.
            _number(event.get("model_cost"), "E_METRICS_MODEL_COST")
            _number(event.get("compute_cost"), "E_METRICS_COMPUTE_COST")
            if event.get("source_trust") == "derived":
                for field in (
                    "provider", "model", "region", "effective_at",
                    "pricing_snapshot_sha256", "usage_evidence_ref",
                ):
                    _require_string(event.get(field), f"E_METRICS_DERIVED_COST_{field.upper()}")
                if not _HEX64.fullmatch(str(event["pricing_snapshot_sha256"])):
                    raise EngineeringMetricsError("E_METRICS_DERIVED_COST_SNAPSHOT")
                _timestamp(event["effective_at"], "E_METRICS_DERIVED_COST_EFFECTIVE_AT")
            trusted_costs.append(event)
    currencies = {_require_string(item.get("currency"), "E_METRICS_CURRENCY") for item in trusted_costs}
    cost_coverage = min(
        (_number(item.get("coverage", 1.0), "E_METRICS_COST_COVERAGE") for item in trusted_costs),
        default=0.0,
    )
    if len(currencies) > 1 or not accepted or not trusted_costs:
        reason = "mixed_currency" if len(currencies) > 1 else "no_accepted_change_or_trusted_cost"
        current["CPAC"] = _result(
            "CPAC", "unavailable", None, len(accepted) if accepted else None, None,
            metric_meta["CPAC"]["unit"], [_event_id(item) for item in trusted_costs],
            unavailable_reason=reason,
        )
    else:
        total_cost = sum(
            _number(item.get("model_cost"), "E_METRICS_MODEL_COST")
            + _number(item.get("compute_cost"), "E_METRICS_COMPUTE_COST")
            for item in trusted_costs
        )
        currency = next(iter(currencies))
        state = FINAL if cost_coverage >= 1.0 else "provisional"
        current["CPAC"] = _result(
            "CPAC", state, total_cost, len(accepted), total_cost / len(accepted),
            metric_meta["CPAC"]["unit"], [_event_id(item) for item in trusted_costs],
            currency=currency, coverage=min(cost_coverage, 1.0),
        )

    deployed_events = _events_of(events, "change_deployed")
    deployed = {_unit_id(item) for item in deployed_events if _unit_id(item) in declared}
    production_closed = bool(_events_of(events, "production_observation_closed"))
    escaped = {
        _unit_id(item) for item in _events_of(events, "defect_escaped")
        if _unit_id(item) in deployed and item.get("independently_confirmed") is True
    }
    reverted = {
        _unit_id(item) for item in _events_of(events, "change_rolled_back")
        if _unit_id(item) in deployed
    }
    production_refs = [_event_id(item) for item in events if item.get("type") in {
        "change_deployed", "production_observation_closed", "defect_escaped", "change_rolled_back"
    }]
    expected_production_close = next(
        (
            item.get("observation_end_at") for item in deployed_events
            if isinstance(item.get("observation_end_at"), str) and item.get("observation_end_at")
        ),
        None,
    )
    production_window = {
        "days": int(manifest.get("default_observation_window_days", 14)),
        "closed": production_closed,
        "expected_close_at": expected_production_close,
    }
    for metric_id, affected in (("DER", escaped), ("RRR", reverted)):
        if not deployed:
            current[metric_id] = _result(
                metric_id, "not_applicable", None, None, None, metric_meta[metric_id]["unit"], production_refs,
                observation_window=production_window,
            )
        elif not production_closed:
            current[metric_id] = _result(
                metric_id, "pending", len(affected), len(deployed), None,
                metric_meta[metric_id]["unit"], production_refs, observation_window=production_window,
            )
        else:
            current[metric_id] = _result(
                metric_id, FINAL, len(affected), len(deployed), len(affected) / len(deployed),
                metric_meta[metric_id]["unit"], production_refs, observation_window=production_window,
            )

    loaded: dict[str, tuple[float, str, str]] = {}
    for event in _events_of(events, "context_segment_loaded"):
        segment = _require_string(event.get("segment_id"), "E_METRICS_SEGMENT_ID")
        if segment in loaded:
            raise EngineeringMetricsError(f"E_METRICS_DUPLICATE_SEGMENT:{segment}")
        basis = _require_string(event.get("weight_basis"), "E_METRICS_WEIGHT_BASIS")
        if basis not in {"tokens", "bytes"}:
            raise EngineeringMetricsError("E_METRICS_WEIGHT_BASIS")
        loaded[segment] = (_number(event.get("weight"), "E_METRICS_WEIGHT"), basis, _event_id(event))
    used = {
        _require_string(event.get("segment_id"), "E_METRICS_SEGMENT_ID")
        for event in _events_of(events, "context_segment_used")
    }
    unknown_used = sorted(used - set(loaded))
    if unknown_used:
        raise EngineeringMetricsError(f"E_METRICS_CONTEXT_USE_BINDING:{unknown_used[0]}")
    bases = {item[1] for item in loaded.values()}
    if not loaded or len(bases) != 1:
        current["CWR"] = _result(
            "CWR", "unavailable", None, None, None, metric_meta["CWR"]["unit"],
            [item[2] for item in loaded.values()],
            unavailable_reason="missing_provenance" if not loaded else "mixed_weight_basis",
        )
    else:
        total_weight = sum(item[0] for item in loaded.values())
        if total_weight <= 0:
            current["CWR"] = _result("CWR", "unavailable", None, None, None, metric_meta["CWR"]["unit"])
        else:
            unused_weight = sum(item[0] for key, item in loaded.items() if key not in used)
            current["CWR"] = _result(
                "CWR", FINAL, unused_weight, total_weight, unused_weight / total_weight,
                metric_meta["CWR"]["unit"],
                [item[2] for item in loaded.values()] + [
                    _event_id(item) for item in _events_of(events, "context_segment_used")
                ], weight_basis=next(iter(bases)),
            )

    drifts: dict[str, str] = {}
    for event in _events_of(events, "ssot_drift"):
        fingerprint = _require_string(event.get("fingerprint"), "E_METRICS_DRIFT_FINGERPRINT")
        drifts.setdefault(fingerprint, _event_id(event))
    sdi_coverage_events = _domain_coverage_events(events, "ssot_drift")
    sdi_covered = bool(sdi_coverage_events)
    if not drifts and not sdi_covered:
        current["SDI"] = _result(
            "SDI", "unavailable", None, None, None, metric_meta["SDI"]["unit"],
            unavailable_reason="missing_telemetry_coverage",
        )
    else:
        current["SDI"] = _result(
            "SDI", FINAL if sdi_covered else "provisional", len(drifts), 1,
            float(len(drifts)), metric_meta["SDI"]["unit"],
            list(drifts.values()) + [_event_id(item) for item in sdi_coverage_events],
            coverage=1.0 if sdi_covered else None,
        )

    failure_events = _events_of(events, "failure_detected")
    prior_hashes = _historical_signature_hashes(
        history, cohort, int(manifest.get("recent_window", 20))
    )
    seen_hashes = set(prior_hashes)
    failure_hashes: list[str] = []
    repeated = 0
    failure_by_id: dict[str, Mapping[str, Any]] = {}
    for event in failure_events:
        failure_id = _require_string(event.get("failure_id"), "E_METRICS_FAILURE_ID")
        if failure_id in failure_by_id:
            raise EngineeringMetricsError(f"E_METRICS_DUPLICATE_FAILURE:{failure_id}")
        signature_hash = _hash_signature(_require_string(event.get("signature"), "E_METRICS_SIGNATURE"))
        repeated += int(signature_hash in seen_hashes)
        seen_hashes.add(signature_hash)
        failure_hashes.append(signature_hash)
        failure_by_id[failure_id] = event
    failure_coverage_events = _domain_coverage_events(events, "failure")
    failure_covered = bool(failure_coverage_events)
    if not failure_events and not failure_covered:
        current["RFR"] = _result(
            "RFR", "unavailable", None, None, None, metric_meta["RFR"]["unit"],
            unavailable_reason="missing_telemetry_coverage",
        )
    else:
        rfr_value = repeated / len(failure_events) if failure_events else 0.0
        current["RFR"] = _result(
            "RFR", FINAL if failure_covered else "provisional", repeated, len(failure_events),
            rfr_value, metric_meta["RFR"]["unit"],
            [_event_id(item) for item in failure_events + failure_coverage_events],
            coverage=1.0 if failure_covered else None,
        )

    review_close_events = _events_of(events, "review_observation_closed")
    review_closed = bool(review_close_events)
    caught = [
        item for item in _events_of(events, "review_defect_caught")
        if item.get("independent_reviewer") is True and item.get("before_acceptance") is True
    ]
    missed = _events_of(events, "review_defect_missed")
    review_refs = [_event_id(item) for item in caught + missed + _events_of(events, "review_observation_closed")]
    expected_review_close = next(
        (
            item.get("observation_end_at") for item in caught + missed
            if isinstance(item.get("observation_end_at"), str) and item.get("observation_end_at")
        ),
        None,
    )
    review_window = {
        "days": int(manifest.get("default_observation_window_days", 14)),
        "closed": review_closed,
        "expected_close_at": expected_review_close,
    }
    if not review_closed:
        current["ARCR"] = _result(
            "ARCR", "pending", len(caught), len(caught) + len(missed), None,
            metric_meta["ARCR"]["unit"], review_refs, observation_window=review_window,
        )
    elif not caught and not missed:
        current["ARCR"] = _result(
            "ARCR", "not_applicable", None, None, None, metric_meta["ARCR"]["unit"], review_refs,
            observation_window=review_window,
        )
    else:
        current["ARCR"] = _result(
            "ARCR", FINAL, len(caught), len(caught) + len(missed),
            len(caught) / (len(caught) + len(missed)), metric_meta["ARCR"]["unit"], review_refs,
            observation_window=review_window,
        )

    recoveries: dict[str, Mapping[str, Any]] = {}
    for event in _events_of(events, "failure_recovered"):
        failure_id = _require_string(event.get("failure_id"), "E_METRICS_FAILURE_ID")
        if failure_id not in failure_by_id or failure_id in recoveries:
            raise EngineeringMetricsError(f"E_METRICS_RECOVERY_BINDING:{failure_id}")
        recoveries[failure_id] = event
    active_total = 0.0
    recovery_refs: list[str] = []
    for failure_id, recovery in recoveries.items():
        if "active_seconds" in recovery:
            seconds = _number(recovery["active_seconds"], "E_METRICS_ACTIVE_SECONDS")
        else:
            detected = datetime.fromisoformat(
                _timestamp(failure_by_id[failure_id].get("detected_at"), "E_METRICS_DETECTED_AT").replace("Z", "+00:00")
            )
            resumed = datetime.fromisoformat(
                _timestamp(recovery.get("resumed_at"), "E_METRICS_RESUMED_AT").replace("Z", "+00:00")
            )
            pause = _number(recovery.get("excluded_pause_seconds", 0), "E_METRICS_PAUSE_SECONDS")
            seconds = (resumed - detected).total_seconds() - pause
            if seconds < 0:
                raise EngineeringMetricsError("E_METRICS_RECOVERY_TIME")
        active_total += seconds
        recovery_refs.extend([_event_id(failure_by_id[failure_id]), _event_id(recovery)])
    if not failure_events and not failure_covered:
        current["MRT"] = _result(
            "MRT", "unavailable", None, None, None, metric_meta["MRT"]["unit"],
            unavailable_reason="missing_telemetry_coverage",
        )
    elif not failure_events:
        current["MRT"] = _result(
            "MRT", "not_applicable", None, None, None, metric_meta["MRT"]["unit"],
            [_event_id(item) for item in failure_coverage_events], coverage=1.0,
        )
    elif not recoveries:
        current["MRT"] = _result(
            "MRT", "pending", 0, 0, None, metric_meta["MRT"]["unit"],
            [_event_id(item) for item in failure_events], censored_count=len(failure_events),
        )
    else:
        state = FINAL if len(recoveries) == len(failure_events) else "provisional"
        current["MRT"] = _result(
            "MRT", state, active_total, len(recoveries), active_total / len(recoveries),
            metric_meta["MRT"]["unit"], recovery_refs,
            censored_count=len(failure_events) - len(recoveries),
        )

    event_index = {_event_id(event): event for event in events}
    for result in current.values():
        event_ids = list(result.get("evidence_refs", []))
        evidence_refs: set[str] = set()
        for event_id in event_ids:
            raw_refs = event_index.get(event_id, {}).get("evidence_refs", [])
            if raw_refs is None:
                raw_refs = []
            if not isinstance(raw_refs, list) or not all(isinstance(item, str) and item for item in raw_refs):
                raise EngineeringMetricsError(f"E_METRICS_EVIDENCE_REFS:{event_id}")
            evidence_refs.update(raw_refs)
        result["event_ids"] = sorted(event_ids)
        result["evidence_refs"] = sorted(evidence_refs)
    ordered = {item["metric_id"]: current[item["metric_id"]] for item in manifest["metrics"]}
    return ordered, {"failure_signature_hashes": sorted(set(failure_hashes))}


def _summary_timestamp(summary: Mapping[str, Any]) -> str:
    run = summary.get("run", {})
    return str(run.get("completed_at", "")) if isinstance(run, dict) else ""


def _comparable_history(history: Sequence[Mapping[str, Any]], cohort: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    comparable = [
        item for item in history
        if isinstance(item, Mapping)
        and item.get("schema_version") == SCHEMA_VERSION
        and isinstance(item.get("run"), Mapping)
        and item["run"].get("cohort") == cohort
    ]
    return sorted(comparable, key=lambda item: (_summary_timestamp(item), str(item.get("run", {}).get("run_id", ""))))


def _same_basis(metric_id: str, values: Sequence[Mapping[str, Any]]) -> bool:
    if metric_id == "CPAC":
        return len({item.get("currency") for item in values}) == 1
    if metric_id == "CWR":
        return len({item.get("weight_basis") for item in values}) == 1
    return True


def _historical_views(
    history: Sequence[Mapping[str, Any]],
    cohort: Mapping[str, Any],
    manifest: Mapping[str, Any],
    current_results: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    comparable = _comparable_history(history, cohort)
    window = int(manifest.get("recent_window", 20))
    minimum = int(manifest.get("minimum_recent_sample", 5))
    recent_runs = comparable[-window:]
    previous: dict[str, Any] = {}
    recent: dict[str, Any] = {}
    for meta in manifest["metrics"]:
        metric_id = meta["metric_id"]
        candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        for summary in comparable:
            current = summary.get("current", {})
            result = current.get(metric_id) if isinstance(current, Mapping) else None
            same_current_basis = True
            if metric_id == "CPAC" and current_results[metric_id].get("currency") is not None:
                same_current_basis = result.get("currency") == current_results[metric_id].get("currency") if isinstance(result, Mapping) else False
            if metric_id == "CWR" and current_results[metric_id].get("weight_basis") is not None:
                same_current_basis = result.get("weight_basis") == current_results[metric_id].get("weight_basis") if isinstance(result, Mapping) else False
            if isinstance(result, Mapping) and result.get("status") == FINAL and same_current_basis:
                candidates.append((summary, result))
        if candidates:
            source, result = candidates[-1]
            previous[metric_id] = dict(result) | {
                "source_run_id": source["run"]["run_id"],
                "source_completed_at": source["run"]["completed_at"],
            }
        else:
            previous[metric_id] = _result(
                metric_id, "unavailable", None, None, None, meta["unit"], unavailable_reason="no_previous_final"
            )

        samples: list[Mapping[str, Any]] = []
        for summary in recent_runs:
            current = summary.get("current", {})
            result = current.get(metric_id) if isinstance(current, Mapping) else None
            same_current_basis = True
            if metric_id == "CPAC" and current_results[metric_id].get("currency") is not None:
                same_current_basis = result.get("currency") == current_results[metric_id].get("currency") if isinstance(result, Mapping) else False
            if metric_id == "CWR" and current_results[metric_id].get("weight_basis") is not None:
                same_current_basis = result.get("weight_basis") == current_results[metric_id].get("weight_basis") if isinstance(result, Mapping) else False
            if isinstance(result, Mapping) and result.get("status") == FINAL and same_current_basis:
                samples.append(result)
        if not samples or not _same_basis(metric_id, samples):
            reason = "no_recent_final" if not samples else "mixed_aggregation_basis"
            recent[metric_id] = _result(
                metric_id, "unavailable", None, None, None, meta["unit"],
                unavailable_reason=reason, sample_count=len(samples), window_size=window,
            )
            continue
        numerator = sum(float(item["numerator"]) for item in samples if item.get("numerator") is not None)
        denominator = sum(float(item["denominator"]) for item in samples if item.get("denominator") is not None)
        if denominator == 0 and metric_id != "RFR":
            recent[metric_id] = _result(
                metric_id, "unavailable", numerator, denominator, None, meta["unit"],
                unavailable_reason="zero_pooled_denominator", sample_count=len(samples), window_size=window,
            )
            continue
        value = 0.0 if metric_id == "RFR" and denominator == 0 else numerator / denominator
        state = FINAL if len(samples) >= minimum else "insufficient_sample"
        extra: dict[str, Any] = {"sample_count": len(samples), "window_size": window}
        if metric_id == "CPAC":
            extra["currency"] = samples[0].get("currency")
        if metric_id == "CWR":
            extra["weight_basis"] = samples[0].get("weight_basis")
        recent[metric_id] = _result(
            metric_id, state, numerator, denominator, value, meta["unit"], **extra
        )
    return previous, recent


def calculate_metrics(
    payload: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]] = (),
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate all 12 metrics from a run event sidecar and prior summaries."""
    manifest = manifest if manifest is not None else load_manifest()
    run_raw = payload.get("run")
    if not isinstance(run_raw, Mapping):
        raise EngineeringMetricsError("E_METRICS_RUN")
    run_id = _require_string(run_raw.get("run_id"), "E_METRICS_RUN_ID")
    completed_at = _timestamp(run_raw.get("completed_at"), "E_METRICS_COMPLETED_AT")
    cohort = _cohort(run_raw)
    events = _apply_corrections(payload.get("events"))
    expected_manifest_digest = manifest_digest(manifest)
    for item in history:
        if not isinstance(item, Mapping):
            raise EngineeringMetricsError("E_METRICS_HISTORY_TYPE")
        if item.get("schema_version") == SCHEMA_VERSION:
            if item.get("algorithm_manifest_sha256") != expected_manifest_digest:
                raise EngineeringMetricsError("E_METRICS_HISTORY_MANIFEST_DRIFT")
            current = item.get("current")
            if not isinstance(current, Mapping) or any(
                metric["metric_id"] not in current for metric in manifest["metrics"]
            ):
                raise EngineeringMetricsError("E_METRICS_HISTORY_SHAPE")
    usable_history = [
        item for item in history
        if isinstance(item, Mapping)
        and not (isinstance(item.get("run"), Mapping) and item["run"].get("run_id") == run_id)
    ]
    current, facts = _calculate_current(events, usable_history, cohort, manifest)
    previous, recent = _historical_views(usable_history, cohort, manifest, current)
    run = {
        "run_id": run_id,
        "completed_at": completed_at,
        "repository_or_project_id": run_raw.get("repository_or_project_id"),
        "project_version": _require_string(run_raw.get("project_version"), "E_METRICS_PROJECT_VERSION"),
        "artifact_version": _require_string(run_raw.get("artifact_version"), "E_METRICS_ARTIFACT_VERSION"),
        "goal_teams_version": str(run_raw.get("goal_teams_version", CALCULATOR_VERSION)),
        "cohort": cohort,
        "cohort_digest": _sha256(cohort),
    }
    if run_raw.get("benchmark") is not None:
        run["benchmark"] = dict(run_raw["benchmark"])
    return {
        "schema_version": SCHEMA_VERSION,
        "calculator_version": CALCULATOR_VERSION,
        "algorithm_manifest_sha256": expected_manifest_digest,
        "generated_at": completed_at,
        "run": run,
        "current": current,
        "previous": previous,
        "recent": recent,
        "recent_sample_count": {
            metric_id: result.get("sample_count", 0) for metric_id, result in recent.items()
        },
        "comparison_facts": facts,
    }


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _format_value(result: Mapping[str, Any]) -> str:
    status = result.get("status")
    value = result.get("value")
    if value is None:
        if status == "pending" and "lower_bound" in result:
            return f"pending（≥{result['lower_bound']}）"
        return str(status)
    unit = result.get("unit")
    if unit == "ratio":
        rendered = f"{float(value) * 100:.1f}%"
    elif unit == "currency_per_accepted_change":
        rendered = f"{float(value):.2f} {result.get('currency', '')}".strip()
    elif unit == "seconds_per_recovery":
        rendered = f"{float(value):.2f} 秒"
    else:
        rendered = f"{float(value):.2f}"
    suffix: list[str] = []
    if status != FINAL:
        suffix.append(str(status))
    if "sample_count" in result:
        suffix.append(f"n={result['sample_count']}")
    return rendered if not suffix else f"{rendered}（{', '.join(suffix)}）"


def _yaml_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def render_okf_report(summary: Mapping[str, Any], manifest: Mapping[str, Any] | None = None) -> str:
    """Render a self-contained OKF report from one calculator summary."""
    manifest = manifest if manifest is not None else load_manifest()
    digest = manifest_digest(manifest)
    if summary.get("algorithm_manifest_sha256") != digest:
        raise EngineeringMetricsError("E_METRICS_REPORT_MANIFEST_DRIFT")
    run = summary.get("run")
    if not isinstance(run, Mapping):
        raise EngineeringMetricsError("E_METRICS_REPORT_RUN")
    if isinstance(run.get("benchmark"), Mapping):
        source_ssot = "metrics/metric-summary.json"
    else:
        artifact_version = _require_string(
            run.get("artifact_version"), "E_METRICS_REPORT_ARTIFACT_VERSION"
        )
        source_ssot = f"versions/{artifact_version}/metrics/metric-summary.json"
    title = f"{run.get('repository_or_project_id') or run.get('run_id')} 工程指标报告"
    lines = [
        "---",
        "type: Engineering Metrics Report",
        f"title: {_yaml_string(title)}",
        "description: 本轮任务的工程指标、历史对比、算法口径、数据覆盖和证据说明。",
        "tags: [goal-teams, engineering-metrics, benchmark, completion-report]",
        f"timestamp: {_yaml_string(summary.get('generated_at'))}",
        'okf_version: "0.1"',
        f"goal_teams_version: {_yaml_string(run.get('goal_teams_version'))}",
        f"project_version: {_yaml_string(run.get('project_version'))}",
        f"artifact_version: {_yaml_string(run.get('artifact_version'))}",
        f"run_id: {_yaml_string(run.get('run_id'))}",
        f"metric_schema_version: {_yaml_string(summary.get('schema_version'))}",
        f"calculator_version: {_yaml_string(summary.get('calculator_version'))}",
        f"algorithm_manifest_sha256: {_yaml_string(digest)}",
        f"source_ssot: {source_ssot}",
        "---",
        "",
        "# 工程指标报告",
        "",
        "# 摘要",
        "",
        "本报告由同一确定性计算器生成本次任务、上一次和近期聚合值。指标用于工程观测，不替代 SPEC、Harness、Evidence 或独立完成审计。",
        "",
        "# 运行身份与数据边界",
        "",
        f"- `run_id`: `{_md(run.get('run_id'))}`",
        f"- `cohort_digest`: `{_md(run.get('cohort_digest'))}`",
        f"- `calculator_version`: `{CALCULATOR_VERSION}`",
        f"- `algorithm_manifest_sha256`: `{digest}`",
        f"- 近期窗口：当前任务之前最近 {manifest.get('recent_window')} 个同 cohort 任务；少于 {manifest.get('minimum_recent_sample')} 个样本标记为 `insufficient_sample`。",
        "- `pending`、`unavailable` 和 `not_applicable` 不会作为零进入历史平均值。",
        "",
        "# 指标结果",
        "",
        "| 指标 | 本次任务数值 | 上一次的数值 | 近期平均值 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for meta in manifest["metrics"]:
        metric_id = meta["metric_id"]
        label = f"{metric_id} — {meta['full_name']} — {meta['chinese_name']}"
        lines.append(
            f"| {_md(label)} | {_md(_format_value(summary['current'][metric_id]))} | "
            f"{_md(_format_value(summary['previous'][metric_id]))} | "
            f"{_md(_format_value(summary['recent'][metric_id]))} |"
        )
    lines.extend([
        "",
        "# 状态、覆盖与刷新",
        "",
        "| 指标 | 状态 | 数据覆盖率 | 不可用原因或预计刷新时间 |",
        "| --- | --- | ---: | --- |",
    ])
    for meta in manifest["metrics"]:
        metric_id = meta["metric_id"]
        result = summary["current"][metric_id]
        window = result.get("observation_window")
        expected = window.get("expected_close_at") if isinstance(window, Mapping) else None
        reason = result.get("unavailable_reason")
        detail = reason or expected or ("未获取到" if result.get("status") == "pending" else "不适用")
        lines.append(
            f"| {metric_id} | `{_md(result.get('status'))}` | "
            f"`{_md(result.get('coverage'))}` | {_md(detail)} |"
        )
    lines.extend([
        "",
        "# 算法与统计口径",
        "",
        "近期比例与平均值均按相应指标的分子、分母合并计算，不对每次任务的百分比做算术平均。以下内容直接投影自算法 manifest。",
        "",
    ])
    for meta in manifest["metrics"]:
        metric_id = meta["metric_id"]
        result = summary["current"][metric_id]
        lines.extend([
            f"## {metric_id} — {meta['full_name']} — {meta['chinese_name']}",
            "",
            f"- **公式**：{meta['formula']}",
            f"- **分子定义**：{meta['numerator_definition']}",
            f"- **分母定义**：{meta['denominator_definition']}",
            f"- **排除项**：{meta['exclusions']}",
            f"- **本次任务规则**：{meta['current_task_rule']}",
            f"- **上一次规则**：{meta['previous_rule']}",
            f"- **近期聚合规则**：{meta['recent_aggregation_rule']}",
            f"- **可用状态规则**：{meta['availability_rule']}",
            f"- **本轮状态**：`{result['status']}`",
            f"- **本轮分子 / 分母**：`{result.get('numerator')}` / `{result.get('denominator')}`",
            f"- **数据覆盖率**：`{result.get('coverage')}`",
            f"- **观察窗**：`{json.dumps(result.get('observation_window'), ensure_ascii=False, sort_keys=True)}`",
            f"- **Event IDs**：{', '.join(f'`{_md(item)}`' for item in result.get('event_ids', [])) or '无'}",
            f"- **Evidence refs**：{', '.join(f'`{_md(item)}`' for item in result.get('evidence_refs', [])) or '无'}",
            "",
        ])
    lines.extend([
        "# 隐私与后续刷新",
        "",
        "- 报告仅保存结构化计数、证据引用和不可逆 failure signature digest，不保存 raw prompt、secret 或未脱敏日志。",
        f"- DER、RRR 等生产指标的默认观察窗为 {manifest.get('default_observation_window_days')} 天；观察窗关闭前保持 `pending`，迟到事实以 correction event 追加后重新生成报告。",
        "- 遥测缺失显示为 `unavailable`，未部署或无适用样本显示为 `not_applicable`，两者均不等于零。",
        "- `pending` 指标若没有可信 `expected_close_at`，预计刷新时间显示为未获取到，不进行推算。",
        "",
        "# 算法来源",
        "",
        f"- Manifest schema：`{manifest.get('schema_version')}`",
        f"- Manifest digest：`{digest}`",
        "- Source SSOT：`references/engineering-metrics-manifest.json`",
        "",
    ])
    return "\n".join(lines)


def write_outputs(
    payload: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    summary_path: Path,
    report_path: Path,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest if manifest is not None else load_manifest()
    summary = calculate_metrics(payload, history, manifest)
    summary_text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    report_text = render_okf_report(summary, manifest)
    if summary_path.resolve() == report_path.resolve():
        raise EngineeringMetricsError("E_METRICS_OUTPUT_COLLISION")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def stage(target: Path, content: str | bytes) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        staged = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content.encode("utf-8") if isinstance(content, str) else content)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            staged.unlink(missing_ok=True)
            raise
        return staged

    for target in (summary_path, report_path):
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise EngineeringMetricsError(f"E_METRICS_OUTPUT_TYPE:{target}")
    prior_summary = summary_path.read_bytes() if summary_path.exists() else None
    staged_summary = stage(summary_path, summary_text)
    staged_report: Path | None = None
    try:
        staged_report = stage(report_path, report_text)
        os.replace(staged_summary, summary_path)
        try:
            os.replace(staged_report, report_path)
        except Exception:
            if prior_summary is None:
                summary_path.unlink(missing_ok=True)
            else:
                restored = stage(summary_path, prior_summary)
                os.replace(restored, summary_path)
            raise
    finally:
        staged_summary.unlink(missing_ok=True)
        if staged_report is not None:
            staged_report.unlink(missing_ok=True)
    return summary


def load_history_summaries(paths: Sequence[str | Path]) -> list[Mapping[str, Any]]:
    """Load prior calculator summaries from explicit files or directories."""
    history: list[Mapping[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        candidates = sorted(path.glob("**/metric-summary.json")) if path.is_dir() else [path]
        for candidate in candidates:
            value = _strict_load(candidate)
            if not isinstance(value, dict):
                raise EngineeringMetricsError(f"E_METRICS_HISTORY:{candidate}")
            history.append(value)
    return history


def _strict_json_line(raw: str, line_number: int) -> Any:
    duplicate = False

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                duplicate = True
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        raise EngineeringMetricsError(f"E_METRICS_JSONL_LINE:{line_number}") from exc
    if duplicate:
        raise EngineeringMetricsError(f"E_METRICS_JSONL_DUPLICATE_KEY:{line_number}")
    return value


def load_input_payload(path: Path | str) -> dict[str, Any]:
    """Load either one JSON object or an append-only JSONL event sidecar.

    JSONL carries run metadata in exactly one record shaped as
    ``{"type":"run_identity","run":{...}}`` or ``{"run":{...}}``.
    All other records are metric events and remain in file order.
    """
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EngineeringMetricsError(f"E_METRICS_JSON:{source}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        # Reuse the duplicate-key rejecting loader for the accepted JSON path.
        strict = _strict_load(source)
        if not isinstance(strict, dict):
            raise EngineeringMetricsError("E_METRICS_INPUT")
        if strict.get("type") == "run_identity" and isinstance(strict.get("run"), dict):
            return {"run": strict["run"], "events": []}
        return strict
    run: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        record = _strict_json_line(line, line_number)
        if not isinstance(record, dict):
            raise EngineeringMetricsError(f"E_METRICS_JSONL_RECORD:{line_number}")
        candidate_run = record.get("run")
        is_run_record = "event_id" not in record and (
            record.get("type") == "run_identity" or set(record) == {"run"}
        )
        if is_run_record:
            if run is not None or not isinstance(candidate_run, dict):
                raise EngineeringMetricsError("E_METRICS_JSONL_RUN_IDENTITY")
            run = candidate_run
        else:
            events.append(record)
    if run is None:
        raise EngineeringMetricsError("E_METRICS_JSONL_RUN_IDENTITY")
    return {"run": run, "events": events}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="run event sidecar JSON")
    parser.add_argument("--history", action="append", default=[], help="prior summary file or directory")
    parser.add_argument("--summary", required=True, help="output metric-summary.json")
    parser.add_argument("--report", required=True, help="output engineering-metrics.md")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    args = parser.parse_args(argv)
    try:
        payload = load_input_payload(Path(args.input))
        manifest = load_manifest(Path(args.manifest))
        write_outputs(
            payload, load_history_summaries(args.history), Path(args.summary), Path(args.report), manifest
        )
    except (EngineeringMetricsError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
