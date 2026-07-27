#!/usr/bin/env python3
"""Fail-closed semantic validator for Goal Teams V2.46 verification governance.

The public import API is ``validate_document(document, fixture_root=None)``.
It intentionally uses only the Python standard library so installed Skill
packages do not acquire a hidden jsonschema dependency.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "references" / "verification-governance-manifest.json"
DEFAULT_SCHEMA = ROOT / "schemas" / "v2.46" / "verification-governance.schema.json"
SCHEMA_VERSION = "goal-teams-verification-governance-v2.46"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROFILES = {"lite", "standard", "full", "regulated"}


class GovernanceError(ValueError):
    """Stable validation failure."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError("E_V246_SCHEMA", f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GovernanceError("E_V246_SCHEMA", f"{path} must contain an object")
    return value


def _id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ids(value: Any, *, nonempty: bool = False) -> bool:
    return bool(
        isinstance(value, list)
        and (not nonempty or value)
        and all(_id(item) for item in value)
        and len(value) == len(set(value))
    )


def _objects(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def _index_unique(
    rows: Iterable[Mapping[str, Any]], key: str, code: str
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not _id(value) or value in result:
            raise GovernanceError(code, f"{key} must be non-empty and unique")
        result[str(value)] = row
    return result


def _reachable_states(machine: Mapping[str, Any]) -> set[str]:
    initial = machine.get("initial")
    transitions = machine.get("transitions")
    if not _id(initial) or not isinstance(transitions, dict):
        return set()
    reached = {str(initial)}
    pending = [str(initial)]
    while pending:
        source = pending.pop()
        for target in transitions.get(source, []):
            if isinstance(target, str) and target not in reached:
                reached.add(target)
                pending.append(target)
    return reached


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != (
        "goal-teams-verification-governance-manifest-v2.46"
    ):
        raise GovernanceError("E_V246_MANIFEST", "manifest schema version drift")
    machines = manifest.get("state_machines")
    if not isinstance(machines, dict) or not machines:
        raise GovernanceError("E_V246_MANIFEST", "state_machines missing")
    for machine_id, machine_any in machines.items():
        if not isinstance(machine_any, dict):
            raise GovernanceError("E_V246_MANIFEST", f"{machine_id} malformed")
        states = machine_any.get("states")
        transitions = machine_any.get("transitions")
        if not _ids(states, nonempty=True) or not isinstance(transitions, dict):
            raise GovernanceError("E_V246_MANIFEST", f"{machine_id} state graph malformed")
        if set(transitions) != set(states):
            raise GovernanceError("E_V246_MANIFEST", f"{machine_id} transition keys drift")
        if any(
            not _ids(targets)
            or not set(targets) <= set(states)
            for targets in transitions.values()
        ):
            raise GovernanceError("E_V246_MANIFEST", f"{machine_id} transition target drift")
        if _reachable_states(machine_any) != set(states):
            raise GovernanceError("E_V246_MANIFEST", f"{machine_id} has unreachable state")
    compatibility = manifest.get("compatibility")
    if not isinstance(compatibility, dict) or (
        compatibility.get("legacy_records_are_immutable") is not True
        or compatibility.get("v246_is_append_only_projection") is not True
    ):
        raise GovernanceError("E_V246_MANIFEST", "legacy replay boundary weakened")
    anti_gaming = manifest.get("anti_gaming")
    if not isinstance(anti_gaming, dict) or any(
        value is not False for value in anti_gaming.values()
    ):
        raise GovernanceError("E_V246_MANIFEST", "anti-gaming policy weakened")
    task_completion = manifest.get("task_completion_receipt_contract")
    if (
        not isinstance(task_completion, dict)
        or task_completion.get("receipt_type") != "task_completion_audit"
        or not _ids(task_completion.get("required_fields"), nonempty=True)
        or not isinstance(task_completion.get("completion_predicates"), dict)
        or not task_completion["completion_predicates"]
        or any(
            value is not True
            for value in task_completion["completion_predicates"].values()
        )
        or task_completion.get("passing_conclusion") != "passed"
    ):
        raise GovernanceError(
            "E_V246_MANIFEST", "task completion receipt contract is malformed"
        )


def _validate_shape(document: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "bundle_id",
        "revision",
        "profile",
        "generated_at",
        "previous_bundle_ref",
        "history_baseline_evidence_ids",
        "historical_evidence_ids",
        "change_events",
        "impact_assessments",
        "evidence_applicability_events",
        "transition_receipts",
        "verification_contracts",
        "grill_reviews",
        "adversarial_risks",
        "acceptance_projection",
    }
    if set(document) != required:
        raise GovernanceError("E_V246_SCHEMA", "top-level fields differ from schema")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise GovernanceError("E_V246_SCHEMA", "bundle schema version drift")
    if not _id(document.get("bundle_id")):
        raise GovernanceError("E_V246_SCHEMA", "bundle_id missing")
    if not isinstance(document.get("revision"), int) or document["revision"] < 1:
        raise GovernanceError("E_V246_SCHEMA", "revision must be a positive integer")
    if document.get("profile") not in PROFILES or not _id(document.get("generated_at")):
        raise GovernanceError("E_V246_SCHEMA", "profile or generated_at invalid")
    if not _ids(document.get("history_baseline_evidence_ids")):
        raise GovernanceError("E_V246_SCHEMA", "baseline evidence ids malformed")
    if not _ids(document.get("historical_evidence_ids")):
        raise GovernanceError("E_V246_SCHEMA", "historical evidence ids malformed")
    previous_ref = document.get("previous_bundle_ref")
    if document["revision"] == 1 and previous_ref is not None:
        raise GovernanceError(
            "E_V246_HISTORY_REWRITE", "initial bundle must not claim a predecessor"
        )
    if document["revision"] > 1 and not isinstance(previous_ref, dict):
        raise GovernanceError(
            "E_V246_HISTORY_REWRITE", "revised bundle lacks a predecessor digest"
        )
    for key in (
        "change_events",
        "impact_assessments",
        "evidence_applicability_events",
        "transition_receipts",
        "verification_contracts",
        "grill_reviews",
        "adversarial_risks",
    ):
        if not _objects(document.get(key)):
            raise GovernanceError("E_V246_SCHEMA", f"{key} must be an object array")
    projection = document.get("acceptance_projection")
    if not isinstance(projection, dict) or projection.get("state") not in {
        "blocked",
        "achieved",
    }:
        raise GovernanceError("E_V246_SCHEMA", "acceptance_projection malformed")


def _resolve_local_ref(root_schema: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise GovernanceError("E_V246_SCHEMA", f"unsupported schema ref: {ref}")
    value: Any = root_schema
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise GovernanceError("E_V246_SCHEMA", f"unresolved schema ref: {ref}")
        value = value[part]
    if not isinstance(value, dict):
        raise GovernanceError("E_V246_SCHEMA", f"schema ref is not an object: {ref}")
    return value


def _schema_validate(
    value: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str = "$",
) -> None:
    """Validate the JSON-Schema subset used by the V2.46 bundle contract."""

    if "$ref" in schema:
        _schema_validate(
            value,
            _resolve_local_ref(root_schema, str(schema["$ref"])),
            root_schema,
            path,
        )
        return
    if "anyOf" in schema:
        options = schema.get("anyOf")
        if not isinstance(options, list) or not options:
            raise GovernanceError("E_V246_SCHEMA", f"{path} anyOf is malformed")
        for option in options:
            if not isinstance(option, dict):
                continue
            try:
                _schema_validate(value, option, root_schema, path)
            except GovernanceError:
                continue
            return
        raise GovernanceError("E_V246_SCHEMA", f"{path} matches no anyOf branch")
    if "const" in schema and value != schema["const"]:
        raise GovernanceError("E_V246_SCHEMA", f"{path} differs from const")
    if "enum" in schema and value not in schema["enum"]:
        raise GovernanceError("E_V246_SCHEMA", f"{path} is outside enum")
    schema_type = schema.get("type")
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(str(schema_type), True)
    if not type_ok:
        raise GovernanceError("E_V246_SCHEMA", f"{path} has wrong type")
    if isinstance(value, dict) and schema_type == "object":
        required = schema.get("required", [])
        if not isinstance(required, list) or any(key not in value for key in required):
            raise GovernanceError("E_V246_SCHEMA", f"{path} lacks required field")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise GovernanceError("E_V246_SCHEMA", f"{path} properties malformed")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise GovernanceError(
                    "E_V246_SCHEMA",
                    f"{path} contains unknown fields: {sorted(unknown)}",
                )
        for key, nested in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                _schema_validate(nested, child_schema, root_schema, f"{path}/{key}")
        minimum_properties = schema.get("minProperties")
        if isinstance(minimum_properties, int) and len(value) < minimum_properties:
            raise GovernanceError("E_V246_SCHEMA", f"{path} has too few properties")
    if isinstance(value, list) and schema_type == "array":
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            raise GovernanceError("E_V246_SCHEMA", f"{path} has too few items")
        if schema.get("uniqueItems") is True:
            encoded = [
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in value
            ]
            if len(encoded) != len(set(encoded)):
                raise GovernanceError("E_V246_SCHEMA", f"{path} has duplicate items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _schema_validate(item, item_schema, root_schema, f"{path}/{index}")
    if isinstance(value, str) and schema_type == "string":
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise GovernanceError("E_V246_SCHEMA", f"{path} is too short")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise GovernanceError("E_V246_SCHEMA", f"{path} does not match pattern")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise GovernanceError("E_V246_SCHEMA", f"{path} is not date-time") from exc
    if isinstance(value, int) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            raise GovernanceError("E_V246_SCHEMA", f"{path} is below minimum")


def _iter_artifact_refs(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            yield value
        for nested in value.values():
            yield from _iter_artifact_refs(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_artifact_refs(nested)


def _validate_artifact_refs(document: Mapping[str, Any], fixture_root: Path | None) -> None:
    for ref in _iter_artifact_refs(document):
        path_value = ref.get("path")
        digest = ref.get("sha256")
        if not _id(path_value) or SHA256_RE.fullmatch(str(digest or "")) is None:
            raise GovernanceError("E_V246_SCHEMA", "artifact ref malformed")
        pure = PurePosixPath(str(path_value))
        if pure.is_absolute() or ".." in pure.parts:
            raise GovernanceError("E_V246_SCHEMA", "artifact ref escapes root")
        if fixture_root is None:
            continue
        root = fixture_root.resolve()
        path = (root / pure).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise GovernanceError("E_V246_ARTIFACT", "artifact ref escapes fixture root") from exc
        if not path.is_file() or path.is_symlink():
            raise GovernanceError("E_V246_ARTIFACT", f"artifact missing: {pure}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise GovernanceError("E_V246_ARTIFACT", f"artifact hash mismatch: {pure}")


def _validate_predecessor_chain(
    document: Mapping[str, Any],
    fixture_root: Path | None,
    schema: Mapping[str, Any],
) -> None:
    """Prove append-only Evidence history against every digest-bound predecessor."""

    revision = int(document["revision"])
    previous_ref = document.get("previous_bundle_ref")
    if revision == 1:
        if previous_ref is not None:
            raise GovernanceError(
                "E_V246_HISTORY_REWRITE", "revision 1 cannot have a predecessor"
            )
        return
    if fixture_root is None or not isinstance(previous_ref, Mapping):
        raise GovernanceError(
            "E_V246_HISTORY_REWRITE",
            "revision greater than 1 requires a readable digest-bound predecessor",
        )
    pure = PurePosixPath(str(previous_ref.get("path", "")))
    previous_path = (fixture_root.resolve() / pure).resolve()
    try:
        previous_path.relative_to(fixture_root.resolve())
    except ValueError as exc:
        raise GovernanceError(
            "E_V246_HISTORY_REWRITE", "predecessor path escapes artifact root"
        ) from exc
    previous = _load_json(previous_path)
    _schema_validate(previous, schema, schema)
    _validate_shape(previous)
    _validate_artifact_refs(previous, fixture_root)
    if (
        previous.get("bundle_id") != document.get("bundle_id")
        or previous.get("revision") != revision - 1
    ):
        raise GovernanceError(
            "E_V246_HISTORY_REWRITE", "predecessor identity/revision is not contiguous"
        )
    prior_history = set(previous.get("historical_evidence_ids", []))
    current_history = set(document.get("historical_evidence_ids", []))
    if not prior_history <= current_history:
        raise GovernanceError(
            "E_V246_HISTORY_REWRITE",
            "historical Evidence was removed across bundle revisions",
        )
    if previous.get("history_baseline_evidence_ids") != document.get(
        "history_baseline_evidence_ids"
    ):
        raise GovernanceError(
            "E_V246_HISTORY_REWRITE",
            "history baseline changed across bundle revisions",
        )
    for field in (
        "historical_evidence_ids",
        "change_events",
        "impact_assessments",
        "evidence_applicability_events",
        "transition_receipts",
        "verification_contracts",
        "grill_reviews",
        "adversarial_risks",
    ):
        prior_rows = previous.get(field)
        current_rows = document.get(field)
        if (
            not isinstance(prior_rows, list)
            or not isinstance(current_rows, list)
            or current_rows[: len(prior_rows)] != prior_rows
        ):
            raise GovernanceError(
                "E_V246_HISTORY_REWRITE",
                f"append-only predecessor ledger was rewritten: {field}",
            )
    _validate_predecessor_chain(previous, fixture_root, schema)


def _latest_applicability(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        evidence_id = row.get("evidence_id")
        if not _id(evidence_id):
            raise GovernanceError("E_V246_SCHEMA", "applicability evidence_id missing")
        grouped.setdefault(str(evidence_id), []).append(row)
    latest: dict[str, Mapping[str, Any]] = {}
    for evidence_id, events in grouped.items():
        revisions = sorted(row.get("revision") for row in events)
        if (
            any(not isinstance(value, int) for value in revisions)
            or revisions != list(range(1, len(events) + 1))
            or any(row.get("expected_revision") != row.get("revision") - 1 for row in events)
        ):
            raise GovernanceError("E_V246_REVISION", f"applicability revision gap: {evidence_id}")
        ordered = sorted(events, key=lambda row: int(row["revision"]))
        for previous, current in zip(ordered, ordered[1:]):
            if current.get("supersedes_event_id") != previous.get("event_id"):
                raise GovernanceError(
                    "E_V246_REVISION", f"applicability supersedes gap: {evidence_id}"
                )
            if (
                previous.get("evidence_applicability_state") == "stale"
                or previous.get("revalidation_state")
                in {"retest_required", "scheduled", "running"}
                or previous.get("evidence_integrity_state") == "invalid"
            ) and (
                current.get("evidence_applicability_state") == "current"
                or current.get("revalidation_state") == "closed"
            ):
                raise GovernanceError(
                    "E_V246_EVIDENCE_REVIVAL",
                    f"Evidence id cannot be revived after impact: {evidence_id}",
                )
        latest[evidence_id] = ordered[-1]
        grouped[evidence_id] = ordered
    return latest, grouped


def _validate_changes_and_impacts(
    document: Mapping[str, Any],
    latest: Mapping[str, Mapping[str, Any]],
    history: Mapping[str, list[Mapping[str, Any]]],
) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    changes = _index_unique(document["change_events"], "change_id", "E_V246_SCHEMA")
    assessments = _index_unique(
        document["impact_assessments"], "assessment_id", "E_V246_SCHEMA"
    )
    impact_items: dict[str, Mapping[str, Any]] = {}
    blocking: list[str] = []
    for assessment in assessments.values():
        change_id = assessment.get("change_id")
        if change_id not in changes:
            raise GovernanceError("E_V246_TRACEABILITY", "impact references unknown change")
        if (
            not isinstance(assessment.get("revision"), int)
            or assessment.get("revision") != assessment.get("expected_revision") + 1
        ):
            raise GovernanceError("E_V246_REVISION", "impact assessment CAS mismatch")
        items = assessment.get("items")
        denominator = assessment.get("denominator_item_ids")
        if not _objects(items) or not _ids(denominator, nonempty=True):
            raise GovernanceError("E_V246_SCHEMA", "impact assessment malformed")
        item_index = _index_unique(items, "item_id", "E_V246_SCHEMA")
        if set(item_index) != set(denominator):
            raise GovernanceError(
                "E_V246_RISK_DENOMINATOR", "impact denominator differs from item set"
            )
        if set(impact_items) & set(item_index):
            raise GovernanceError("E_V246_SCHEMA", "impact item id reused")
        impact_items.update(item_index)
    for item_id, item in impact_items.items():
        impact_class = item.get("impact_class")
        path = item.get("dependency_path")
        evidence_ids = item.get("evidence_ids")
        check_state = item.get("current_check_state")
        run_conclusion = item.get("current_run_conclusion")
        if not _ids(path) or not _ids(evidence_ids):
            raise GovernanceError("E_V246_SCHEMA", f"impact item malformed: {item_id}")
        item_events = [
            event
            for evidence_id in evidence_ids
            for event in history.get(evidence_id, [])
            if event.get("impact_item_id") == item_id
        ]
        item_latest = [latest[evidence_id] for evidence_id in evidence_ids if evidence_id in latest]
        if any(
            event.get("impact_item_id") != item_id
            for event in item_latest
        ):
            raise GovernanceError(
                "E_V246_TRACEABILITY",
                "impact item borrowed Evidence bound to another item",
            )
        if impact_class == "unaffected":
            if path:
                raise GovernanceError(
                    "E_V246_IMPACT_PATH", "unaffected item must not claim dependency path"
                )
            if not evidence_ids or len(item_latest) != len(evidence_ids):
                raise GovernanceError(
                    "E_V246_IMPACT_SEMANTICS", "unaffected item needs historical evidence"
                )
            invalid_integrity = any(
                event.get("evidence_integrity_state") == "invalid"
                for event in item_latest
            )
            if invalid_integrity and not (
                check_state == "failed" and run_conclusion == "failed"
            ):
                raise GovernanceError(
                    "E_V246_IMPACT_SEMANTICS",
                    "invalid Evidence must project an actual failed current check/run",
                )
            if any(
                event.get("evidence_integrity_state") not in {"valid", "invalid"}
                or event.get("evidence_applicability_state") != "current"
                or event.get("revalidation_state") not in {"not_required", "closed"}
                for event in item_latest
            ):
                raise GovernanceError(
                    "E_V246_IMPACT_SEMANTICS", "unaffected evidence must remain current"
                )
            if invalid_integrity:
                blocking.append("evidence_integrity_invalid")
        elif impact_class == "affected":
            if len(path) < 2 or not evidence_ids or not item_events:
                raise GovernanceError(
                    "E_V246_IMPACT_PATH", "affected item lacks dependency chain/evidence"
                )
            if not any(
                event.get("evidence_integrity_state") == "valid"
                and event.get("evidence_applicability_state") == "stale"
                and event.get("revalidation_state") in {
                    "retest_required",
                    "scheduled",
                    "running",
                }
                for event in item_events
            ):
                raise GovernanceError(
                    "E_V246_IMPACT_SEMANTICS",
                    "affected evidence must first become stale and require retest",
                )
            if any(
                event.get("evidence_integrity_state") == "invalid"
                for event in item_events
            ):
                raise GovernanceError(
                    "E_V246_IMPACT_SEMANTICS",
                    "ordinary impact must not invalidate historical evidence",
                )
            replacements = [
                event
                for event in item_latest
                if event.get("evidence_integrity_state") == "valid"
                and event.get("evidence_applicability_state") == "current"
                and event.get("revalidation_state") == "closed"
                and event.get("supersedes_evidence_id") in evidence_ids
            ]
            stale_ids = {
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id in latest
                and latest[evidence_id].get("evidence_applicability_state") == "stale"
            }
            if not replacements or not any(
                event.get("supersedes_evidence_id") in stale_ids
                for event in replacements
            ):
                blocking.append("retest_required")
        elif impact_class == "new_requirement":
            if check_state == "not_started" and run_conclusion == "not_run":
                if evidence_ids:
                    raise GovernanceError(
                        "E_V246_IMPACT_SEMANTICS",
                        "not-run new requirement must not borrow historical evidence",
                    )
                blocking.append("new_requirement_not_run")
            elif check_state == "passed" and run_conclusion == "achieved":
                if not evidence_ids or any(
                    event.get("evidence_integrity_state") != "valid"
                    or event.get("evidence_applicability_state") != "current"
                    or event.get("revalidation_state") != "closed"
                    for event in item_latest
                ):
                    raise GovernanceError(
                        "E_V246_IMPACT_SEMANTICS",
                        "completed new requirement needs current closed evidence",
                    )
            else:
                blocking.append("new_requirement_incomplete")
        elif impact_class == "scope_change_pending":
            if not item.get("scope_change_approval_ref"):
                raise GovernanceError(
                    "E_V246_SCOPE_APPROVAL",
                    "scope-changing gate requires SPEC/Harness approval before admission",
                )
            else:
                raise GovernanceError(
                    "E_V246_SCOPE_APPROVAL",
                    "approved scope change must be reclassified with its actual impact",
                )
        elif impact_class == "undetermined":
            blocking.append("impact_undetermined")
        else:
            raise GovernanceError("E_V246_SCHEMA", f"unknown impact class: {impact_class}")
        if check_state in {"failed", "blocked"} or run_conclusion in {
            "failed",
            "blocked",
            "partial",
            "flaky",
            "aborted",
            "not_run",
        }:
            blocking.append(f"{item_id}:{check_state}:{run_conclusion}")
        if check_state != "passed" or run_conclusion != "achieved":
            blocking.append(
                f"{item_id}:required_threshold:{check_state}:{run_conclusion}"
            )
    return impact_items, blocking


def _validate_applicability_integrity(
    rows: Iterable[Mapping[str, Any]],
    historical_ids: set[str],
) -> None:
    for row in rows:
        required = {
            "event_id",
            "evidence_id",
            "impact_item_id",
            "evidence_integrity_state",
            "evidence_applicability_state",
            "revalidation_state",
            "reason_code",
            "evidence_refs",
            "actor_run_id",
            "run_id",
            "attempt_id",
            "revision",
            "expected_revision",
            "occurred_at",
        }
        if not required <= set(row) or row.get("evidence_id") not in historical_ids:
            raise GovernanceError("E_V246_TRACEABILITY", "applicability event is unbound")
        integrity = row.get("evidence_integrity_state")
        refs = row.get("evidence_refs")
        if not _objects(refs) or not refs:
            raise GovernanceError(
                "E_V246_TRACEABILITY",
                "applicability Evidence lacks a verifiable artifact binding",
            )
        if integrity == "invalid":
            if not _id(row.get("integrity_failure_code")) or not refs:
                raise GovernanceError(
                    "E_V246_INVALID_EVIDENCE",
                    "invalid evidence requires integrity failure proof",
                )
        elif row.get("integrity_failure_code") is not None:
            raise GovernanceError(
                "E_V246_INVALID_EVIDENCE",
                "integrity failure code is reserved for invalid evidence",
            )

    row_list = list(rows)
    latest, history = _latest_applicability(row_list)
    for row in row_list:
        predecessor_id = row.get("supersedes_evidence_id")
        if predecessor_id is None:
            continue
        evidence_id = row.get("evidence_id")
        predecessor = latest.get(str(predecessor_id))
        if (
            predecessor_id == evidence_id
            or predecessor is None
            or row.get("revision") != 1
            or predecessor.get("evidence_applicability_state") != "stale"
            or predecessor.get("revalidation_state")
            not in {"retest_required", "scheduled", "running"}
            or row.get("evidence_integrity_state") != "valid"
            or row.get("evidence_applicability_state") != "current"
            or row.get("revalidation_state") != "closed"
            or any(
                event.get("run_id") == row.get("run_id")
                or event.get("attempt_id") == row.get("attempt_id")
                for event in history[str(predecessor_id)]
            )
        ):
            raise GovernanceError(
                "E_V246_RETEST_IDENTITY",
                "retest must create new Evidence/run/attempt bound to stale predecessor",
            )


def _validate_task_completion_receipt(
    receipt: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    fixture_root: Path | None,
    bundle_id: str,
    bundle_revision: int,
    task_id: str,
    executor_run_id: str,
    auditor_run_id: str,
    evidence_ids: set[str],
) -> None:
    contract = manifest.get("task_completion_receipt_contract")
    if not isinstance(contract, dict) or fixture_root is None:
        raise GovernanceError(
            "E_V246_AUDIT_RECEIPT",
            "accepted task requires a readable typed completion audit",
        )
    path = (
        fixture_root.resolve()
        / PurePosixPath(str(receipt.get("path", "")))
    ).resolve()
    try:
        path.relative_to(fixture_root.resolve())
        payload = _load_json(path)
    except (ValueError, GovernanceError) as exc:
        raise GovernanceError(
            "E_V246_AUDIT_RECEIPT",
            "task completion audit is not readable JSON",
        ) from exc
    if (
        set(payload) != set(contract.get("required_fields", []))
        or payload.get("schema_version") != contract.get("schema_version")
        or payload.get("receipt_type") != contract.get("receipt_type")
        or payload.get("bundle_id") != bundle_id
        or payload.get("bundle_revision") != bundle_revision
        or payload.get("task_id") != task_id
        or payload.get("executor_run_id") != executor_run_id
        or payload.get("auditor_run_id") != auditor_run_id
        or set(payload.get("evidence_ids", [])) != evidence_ids
        or payload.get("completion_predicates")
        != contract.get("completion_predicates")
        or payload.get("conclusion") != contract.get("passing_conclusion")
        or auditor_run_id == executor_run_id
    ):
        raise GovernanceError(
            "E_V246_AUDIT_RECEIPT",
            "task acceptance is not independently derived from completion predicates",
        )


def _validate_transitions(
    rows: Iterable[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    applicability: Mapping[str, Mapping[str, Any]],
    fixture_root: Path | None,
    bundle_id: str,
    bundle_revision: int,
) -> list[str]:
    machines = manifest["state_machines"]
    receipts = _index_unique(rows, "receipt_id", "E_V246_SCHEMA")
    idempotency: set[str] = set()
    entity_heads: dict[tuple[str, str], tuple[int, str, str]] = {}
    task_executors: dict[str, str] = {}
    accepted_task_ids: set[str] = set()
    blocking: list[str] = []
    for receipt in receipts.values():
        machine_id = receipt.get("machine_id")
        machine = machines.get(machine_id)
        if not isinstance(machine, dict):
            raise GovernanceError("E_V246_TRANSITION", "unknown state machine")
        source = receipt.get("from_state")
        target = receipt.get("to_state")
        if target not in machine["transitions"].get(source, []):
            raise GovernanceError(
                "E_V246_TRANSITION", f"forbidden transition: {machine_id}:{source}->{target}"
            )
        expected = receipt.get("expected_revision")
        new = receipt.get("new_revision")
        if not isinstance(expected, int) or new != expected + 1:
            raise GovernanceError("E_V246_REVISION", "transition CAS revision mismatch")
        entity_id = receipt.get("entity_id")
        occurred_at = receipt.get("occurred_at")
        if not _id(entity_id) or not _id(occurred_at):
            raise GovernanceError("E_V246_SCHEMA", "transition entity/time missing")
        entity_key = (str(machine_id), str(entity_id))
        previous = entity_heads.get(entity_key)
        history_ref = receipt.get("history_ref")
        if previous is None and (
            expected != 0 or source != machine.get("initial")
        ) and not isinstance(history_ref, dict):
            raise GovernanceError(
                "E_V246_REVISION",
                "first transition must start at initial revision or bind protected history",
            )
        if previous is not None and (
            expected != previous[0]
            or source != previous[1]
            or str(occurred_at) < previous[2]
        ):
            raise GovernanceError(
                "E_V246_REVISION",
                "transition chain violates CAS, state continuity, or event order",
            )
        entity_heads[entity_key] = (new, str(target), str(occurred_at))
        supersedes_task_id = receipt.get("supersedes_task_id")
        if supersedes_task_id is not None and supersedes_task_id not in accepted_task_ids:
            raise GovernanceError(
                "E_V246_TRACEABILITY",
                "successor task does not reference an accepted predecessor",
            )
        key = receipt.get("idempotency_key")
        if not _id(key) or key in idempotency:
            raise GovernanceError("E_V246_REVISION", "idempotency key missing or reused")
        idempotency.add(str(key))
        guards = receipt.get("guard_results")
        evidence_refs = receipt.get("evidence_refs")
        if (
            not _objects(guards)
            or not guards
            or not _ids(evidence_refs, nonempty=True)
            or any(
                guard.get("passed") is not True
                or not _ids(guard.get("evidence_refs"), nonempty=True)
                for guard in guards
            )
        ):
            raise GovernanceError(
                "E_V246_TRANSITION_EVIDENCE", "transition lacks passing guards/evidence"
            )
        if not set(evidence_refs) <= set(applicability) or any(
            not set(guard.get("evidence_refs", [])) <= set(applicability)
            for guard in guards
        ):
            raise GovernanceError(
                "E_V246_TRANSITION_EVIDENCE",
                "transition references evidence outside the historical registry",
            )
        if (
            machine_id == "task_lifecycle"
            and source == "planned"
            and target == "running"
        ):
            task_executors[str(entity_id)] = str(receipt.get("actor_run_id"))
        if machine_id == "task_lifecycle" and target == "accepted":
            executor_run_id = receipt.get("executor_run_id")
            audit_ref = receipt.get("completion_audit_ref")
            actor_run_id = receipt.get("actor_run_id")
            if (
                not _id(executor_run_id)
                or not isinstance(audit_ref, dict)
                or actor_run_id == executor_run_id
                or (
                    str(entity_id) in task_executors
                    and task_executors[str(entity_id)] != executor_run_id
                )
            ):
                raise GovernanceError(
                    "E_V246_AUDIT_RECEIPT",
                    "accepted task lacks an independent executor/auditor binding",
                )
            _validate_task_completion_receipt(
                audit_ref,
                manifest=manifest,
                fixture_root=fixture_root,
                bundle_id=bundle_id,
                bundle_revision=bundle_revision,
                task_id=str(entity_id),
                executor_run_id=str(executor_run_id),
                auditor_run_id=str(actor_run_id),
                evidence_ids=set(evidence_refs),
            )
            accepted_task_ids.add(str(entity_id))
        side_effect = receipt.get("side_effect")
        if machine_id == "external_surface" and not isinstance(side_effect, dict):
            raise GovernanceError(
                "E_V246_SIDE_EFFECT_PROTOCOL", "external transition lacks side-effect binding"
            )
        event = receipt.get("transition_event")
        event_contract = manifest.get("transition_event_algorithm", {})
        aliases = (
            event_contract.get("aliases", {})
            if isinstance(event_contract, dict)
            else {}
        )
        edge_key = f"{machine_id}:{source}:{target}"
        canonical_event = f"{machine_id}.{source}.{target}"
        allowed_events = {canonical_event, *aliases.get(edge_key, [])}
        if event not in allowed_events:
            raise GovernanceError(
                "E_V246_TRANSITION",
                f"transition event is not declared for edge: {edge_key}",
            )
        if isinstance(side_effect, dict):
            classification = side_effect.get("readback_classification")
            recovery = side_effect.get("recovery_state")
            if classification == "exact" and recovery not in {"none", "recovered"}:
                raise GovernanceError(
                    "E_V246_SIDE_EFFECT_PROTOCOL", "exact readback has unresolved recovery"
                )
            if classification == "conflict" and recovery != "conflict":
                raise GovernanceError(
                    "E_V246_SIDE_EFFECT_PROTOCOL", "conflict readback must enter conflict"
                )
            if classification == "unavailable" and recovery not in {
                "reconciliation_required",
                "recovering",
            }:
                raise GovernanceError(
                    "E_V246_SIDE_EFFECT_PROTOCOL", "unavailable readback cannot imply success"
                )
            if recovery in {"reconciliation_required", "recovering", "conflict"}:
                blocking.append(f"recovery:{recovery}")
    return blocking


def _validate_contracts_and_reviews(
    document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    historical_ids: set[str],
    current_evidence_ids: set[str],
    acceptance_evidence_ids: set[str],
    acceptance_achieved: bool,
    impact_items: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    contracts = _index_unique(
        document["verification_contracts"], "contract_id", "E_V246_SCHEMA"
    )
    grills = _index_unique(document["grill_reviews"], "grill_id", "E_V246_SCHEMA")
    risks = _index_unique(document["adversarial_risks"], "risk_id", "E_V246_SCHEMA")
    blocking: list[str] = []
    catalog = set(manifest["adversarial_risk_catalog"])
    required_applicable_risk_ids = {
        risk_id
        for risk_id, risk in risks.items()
        if risk.get("required") is True and risk.get("applicable") is True
    }
    for contract in contracts.values():
        if contract.get("profile") != document.get("profile"):
            raise GovernanceError(
                "E_V246_TRACEABILITY",
                "bundle route profile differs from verification contract profile",
            )
        for field in (
            "requirement_refs",
            "acceptance_criteria_refs",
            "risk_denominator",
        ):
            if not _ids(contract.get(field), nonempty=True):
                raise GovernanceError("E_V246_SCHEMA", f"contract {field} malformed")
        roles = contract.get("role_bindings")
        if (
            not isinstance(roles, dict)
            or len(
                {
                    roles.get("designer_run_id"),
                    roles.get("runner_run_id"),
                    roles.get("reviewer_run_id"),
                }
            )
            != 3
        ):
            raise GovernanceError("E_V246_TRACEABILITY", "test roles are not independent")
        if contract.get("profile") in {"full", "regulated"}:
            required_roles = {
                roles.get("owner_run_id"),
                roles.get("designer_run_id"),
                roles.get("runner_run_id"),
                roles.get("reviewer_run_id"),
                roles.get("qa_run_id"),
                roles.get("completion_auditor_run_id"),
            }
            if None in required_roles or len(required_roles) != 6:
                raise GovernanceError(
                    "E_V246_TRACEABILITY",
                    "Full/Regulated contract lacks independent QA/auditor roles",
                )
        if contract.get("pass_thresholds") != {
            "required_checks": "all_passed",
            "required_runs": "achieved",
            "max_failed": 0,
            "max_blocked": 0,
            "max_not_run": 0,
            "max_flaky": 0,
        }:
            raise GovernanceError(
                "E_V246_CONTRACT_THRESHOLD",
                "test contract pass threshold can admit non-passing states",
            )
        if contract.get("waiver_policy") != {
            "required_allowed": False,
            "independent_approval_required": True,
        } or contract.get("change_approval_policy") != {
            "scope_change_requires_approval": True,
            "spec_harness_update_required": True,
        }:
            raise GovernanceError(
                "E_V246_SCOPE_APPROVAL",
                "waiver/change approval policy weakens fail-closed governance",
            )
        traceability = contract.get("traceability")
        if not _objects(traceability) or not traceability:
            raise GovernanceError("E_V246_TRACEABILITY", "contract traceability missing")
        for link in traceability:
            if (
                link.get("requirement_id") not in contract["requirement_refs"]
                or not set(link.get("acceptance_criteria_ids", []))
                <= set(contract["acceptance_criteria_refs"])
                or any(
                not _ids(link.get(field), nonempty=True)
                for field in (
                    "acceptance_criteria_ids",
                    "test_plan_ids",
                    "test_case_ids",
                    "harness_check_ids",
                    "run_ids",
                    "evidence_ids",
                )
                )
            ):
                raise GovernanceError("E_V246_TRACEABILITY", "traceability chain is incomplete")
            if not set(link.get("evidence_ids", [])) <= historical_ids:
                raise GovernanceError(
                    "E_V246_TRACEABILITY",
                    "traceability references evidence outside the historical registry",
                )
        denominator = set(contract["risk_denominator"])
        if not set(contract.get("unacceptable_risk_ids", [])) <= denominator:
            raise GovernanceError(
                "E_V246_RISK_DENOMINATOR",
                "unacceptable risk is outside the declared denominator",
            )
        if not denominator <= set(risks):
            raise GovernanceError(
                "E_V246_RISK_DENOMINATOR", "contract risk denominator is not represented"
            )
        if not required_applicable_risk_ids <= denominator:
            raise GovernanceError(
                "E_V246_RISK_DENOMINATOR",
                "required applicable adversarial risk was removed from the denominator",
            )
        if contract.get("profile") in {"full", "regulated"} and (
            denominator != set(risks)
            or {risk.get("category") for risk in risks.values()} != catalog
        ):
            raise GovernanceError(
                "E_V246_RISK_DENOMINATOR",
                "Full/Regulated contract does not cover the complete risk catalog",
            )
        if any(risks[risk_id].get("category") not in catalog for risk_id in denominator):
            raise GovernanceError("E_V246_RISK_DENOMINATOR", "risk category outside manifest")
        implementation_roles = {
            roles.get("owner_run_id"),
            roles.get("designer_run_id"),
            roles.get("runner_run_id"),
        }
        if any(
            risks[risk_id].get("reviewer_run_id") in implementation_roles
            for risk_id in denominator
        ):
            raise GovernanceError(
                "E_V246_TRACEABILITY",
                "adversarial risk reviewer is not independent from delivery roles",
            )
        contract_grills = [
            grill for grill in grills.values() if grill.get("contract_id") == contract["contract_id"]
        ]
        requirement_grills = {
            grill.get("requirement_id") for grill in contract_grills if grill.get("critical") is True
        }
        if not set(contract["requirement_refs"]) <= requirement_grills:
            raise GovernanceError(
                "E_V246_GRILL_EVIDENCE", "critical requirement lacks Grill review"
            )
    for grill in grills.values():
        contract = contracts.get(str(grill.get("contract_id")))
        if contract is None:
            raise GovernanceError("E_V246_TRACEABILITY", "Grill references unknown contract")
        basis = set(grill.get("basis_refs", []))
        allowed_basis = {
            str(grill.get("requirement_id")),
            *contract["acceptance_criteria_refs"],
        }
        if (
            grill.get("requirement_id") not in basis
            or not basis & set(contract["acceptance_criteria_refs"])
            or not basis <= allowed_basis
            or not set(grill.get("residual_risks", []))
            <= set(contract["risk_denominator"])
            or not _objects(grill.get("version_environment_refs"))
            or not grill.get("version_environment_refs")
        ):
            raise GovernanceError(
                "E_V246_GRILL_EVIDENCE",
                "Grill basis/environment/residual risk is not contract bound",
            )
        na = grill.get("na")
        if not isinstance(na, dict):
            raise GovernanceError("E_V246_SCHEMA", "Grill N/A record malformed")
        if na.get("claimed") is True:
            implementation_roles = {
                contract["role_bindings"].get("owner_run_id"),
                contract["role_bindings"].get("designer_run_id"),
                contract["role_bindings"].get("runner_run_id"),
            }
            if (
                grill.get("conclusion") != "not_applicable_accepted"
                or not _id(na.get("reason"))
                or na.get("impact_assessment_ref")
                not in {
                    assessment.get("assessment_id")
                    for assessment in document["impact_assessments"]
                }
                or not isinstance(na.get("approval_ref"), dict)
                or not _id(na.get("approver_run_id"))
                or na.get("approver_run_id") == grill.get("reviewer_run_id")
                or na.get("approver_run_id") in implementation_roles
                or grill.get("reviewer_run_id") in implementation_roles
            ):
                raise GovernanceError("E_V246_GRILL_NA", "Grill N/A lacks independent basis")
        if not set(grill.get("evidence_refs", [])) <= historical_ids:
            raise GovernanceError(
                "E_V246_GRILL_EVIDENCE",
                "Grill references evidence outside the historical registry",
            )
        elif grill.get("critical") is True and na.get("claimed") is not True and (
            grill.get("conclusion") != "answered_with_evidence"
            or not _ids(grill.get("evidence_refs"), nonempty=True)
            or (
                acceptance_achieved
                and not set(grill.get("evidence_refs", []))
                <= acceptance_evidence_ids
            )
        ):
            raise GovernanceError(
                "E_V246_GRILL_EVIDENCE",
                "critical Grill answer lacks current acceptance-bound evidence",
            )
    for risk in risks.values():
        applicable = risk.get("applicable") is True
        required = risk.get("required") is True
        coverage = risk.get("coverage_state")
        if not set(risk.get("evidence_refs", [])) <= historical_ids:
            raise GovernanceError(
                "E_V246_TRACEABILITY",
                "adversarial risk references evidence outside the historical registry",
            )
        if applicable and required:
            if coverage != "passed" or any(
                not _ids(risk.get(field), nonempty=True)
                for field in ("case_ids", "assertion_ids", "run_ids", "evidence_refs")
            ) or not _id(risk.get("reviewer_run_id")):
                blocking.append(f"adversarial_risk:{risk.get('risk_id')}:{coverage}")
            elif (
                acceptance_achieved
                and not set(risk.get("evidence_refs", []))
                <= acceptance_evidence_ids
            ):
                raise GovernanceError(
                    "E_V246_RISK_EVIDENCE",
                    "required adversarial risk lacks current acceptance-bound evidence",
                )
        elif coverage == "not_applicable":
            impact_bound = any(
                item.get("target_type") == "risk"
                and item.get("target_id") == risk.get("risk_id")
                and item.get("impact_class") == "unaffected"
                for item in impact_items.values()
            )
            if (
                risk.get("required") is True
                or not _id(risk.get("na_reason"))
                or not isinstance(risk.get("na_approval_ref"), dict)
                or not _id(risk.get("na_approver_run_id"))
                or not impact_bound
            ):
                raise GovernanceError(
                    "E_V246_RISK_DENOMINATOR",
                    "N/A risk lacks independent approval/impact binding or is required",
                )
            delivery_roles = {
                role
                for contract in contracts.values()
                for role_name, role in contract.get("role_bindings", {}).items()
                if role_name
                in {"owner_run_id", "designer_run_id", "runner_run_id"}
                and _id(role)
            }
            reviewer = risk.get("reviewer_run_id")
            approver = risk.get("na_approver_run_id")
            if (
                reviewer in delivery_roles
                or approver in delivery_roles
                or reviewer == approver
            ):
                raise GovernanceError(
                    "E_V246_RISK_DENOMINATOR",
                    "N/A approval/review is not independent from delivery",
                )
    return blocking


def _validate_acceptance(
    document: Mapping[str, Any],
    latest: Mapping[str, Mapping[str, Any]],
    blocking: list[str],
    fixture_root: Path | None,
    manifest: Mapping[str, Any],
) -> None:
    projection = document["acceptance_projection"]
    state = projection.get("state")
    if (
        not _id(projection.get("derived_by_run_id"))
        or not _ids(projection.get("acceptance_evidence_ids"), nonempty=True)
        or not _objects(projection.get("independent_review_refs"))
        or not _objects(projection.get("completion_audit_refs"))
        or not _ids(projection.get("reason_codes"))
    ):
        raise GovernanceError("E_V246_SCHEMA", "acceptance projection fields malformed")
    acceptance_evidence_ids = set(projection["acceptance_evidence_ids"])
    if not acceptance_evidence_ids <= set(latest):
        raise GovernanceError(
            "E_V246_ACCEPTANCE",
            "acceptance references unknown Evidence",
        )
    traced_evidence_ids = {
        evidence_id
        for contract in document["verification_contracts"]
        for link in contract.get("traceability", [])
        for evidence_id in link.get("evidence_ids", [])
    }
    if not acceptance_evidence_ids <= traced_evidence_ids:
        raise GovernanceError(
            "E_V246_TRACEABILITY",
            "acceptance Evidence is not bound through the current test contract",
        )
    stale_or_invalid = [
        evidence_id
        for evidence_id, event in latest.items()
        if evidence_id in acceptance_evidence_ids
        and (
        event.get("evidence_integrity_state") != "valid"
        or event.get("evidence_applicability_state") != "current"
        or event.get("revalidation_state") not in {"not_required", "closed"}
        )
    ]
    superseded_ids = {
        str(event.get("supersedes_evidence_id"))
        for event in latest.values()
        if _id(event.get("supersedes_evidence_id"))
    }
    if acceptance_evidence_ids & superseded_ids:
        raise GovernanceError(
            "E_V246_ACCEPTANCE",
            "acceptance cannot use superseded historical Evidence",
        )
    delivery_actors = {
        actor
        for contract in document["verification_contracts"]
        for role_name, actor in contract.get("role_bindings", {}).items()
        if role_name in {"owner_run_id", "designer_run_id", "runner_run_id"}
        if _id(actor)
    }
    declared_reviewers = {
        contract.get("role_bindings", {}).get("reviewer_run_id")
        for contract in document["verification_contracts"]
    }
    declared_auditors = {
        contract.get("role_bindings", {}).get("completion_auditor_run_id")
        for contract in document["verification_contracts"]
        if _id(
            contract.get("role_bindings", {}).get("completion_auditor_run_id")
        )
    }
    delivery_actors.update(
        event.get("actor_run_id")
        for event in document["change_events"]
        if _id(event.get("actor_run_id"))
    )
    delivery_actors.update(
        receipt.get("actor_run_id")
        for receipt in document["transition_receipts"]
        if _id(receipt.get("actor_run_id"))
    )
    review_actors: set[str] = set()
    audit_actors: set[str] = set()
    receipt_contract = manifest.get("review_audit_receipt_contract")
    if not isinstance(receipt_contract, dict):
        raise GovernanceError(
            "E_V246_MANIFEST", "review/audit receipt contract is missing"
        )
    expected_predicates = receipt_contract.get("completion_predicates")
    required_receipt_fields = set(receipt_contract.get("required_fields", []))
    if not isinstance(expected_predicates, dict) or not required_receipt_fields:
        raise GovernanceError(
            "E_V246_MANIFEST", "review/audit receipt contract is malformed"
        )
    for field, receipt_type, actor_set in (
        ("independent_review_refs", "independent_review", review_actors),
        ("completion_audit_refs", "completion_audit", audit_actors),
    ):
        for ref in projection[field]:
            if fixture_root is None:
                if state == "achieved":
                    raise GovernanceError(
                        "E_V246_AUDIT_RECEIPT",
                        "achieved review/audit requires a readable artifact root",
                    )
                continue
            path = (
                fixture_root.resolve()
                / PurePosixPath(str(ref.get("path", "")))
            ).resolve()
            try:
                path.relative_to(fixture_root.resolve())
                receipt = _load_json(path)
            except (ValueError, GovernanceError) as exc:
                raise GovernanceError(
                    "E_V246_AUDIT_RECEIPT",
                    "review/audit receipt is not readable JSON",
                ) from exc
            actor = receipt.get("actor_run_id")
            if (
                set(receipt) != required_receipt_fields
                or receipt.get("schema_version")
                != receipt_contract.get("schema_version")
                or receipt.get("receipt_type") != receipt_type
                or receipt.get("bundle_id") != document.get("bundle_id")
                or receipt.get("bundle_revision") != document.get("revision")
                or set(receipt.get("acceptance_evidence_ids", []))
                != acceptance_evidence_ids
                or receipt.get("completion_predicates") != expected_predicates
                or receipt.get("conclusion")
                != receipt_contract.get("passing_conclusion")
                or not _id(actor)
            ):
                raise GovernanceError(
                    "E_V246_AUDIT_RECEIPT",
                    "review/audit receipt is not bound to current completion facts",
                )
            actor_set.add(str(actor))
    if (
        review_actors & delivery_actors
        or audit_actors & delivery_actors
        or review_actors & audit_actors
        or not review_actors <= declared_reviewers
        or (declared_auditors and not audit_actors <= declared_auditors)
        or (
            state == "achieved"
            and (
                len(review_actors) != len(projection["independent_review_refs"])
                or len(audit_actors) != len(projection["completion_audit_refs"])
                or projection.get("derived_by_run_id") not in audit_actors
            )
        )
    ):
        raise GovernanceError(
            "E_V246_AUDIT_RECEIPT",
            "review/audit actors are not independently bound",
        )
    if (
        state == "achieved"
        and projection.get("derived_by_run_id") in delivery_actors
    ):
        raise GovernanceError(
            "E_V246_ACCEPTANCE",
            "completion state was directly declared by an in-graph actor",
        )
    if state == "achieved":
        if any(
            not document[field]
            for field in (
                "change_events",
                "impact_assessments",
                "evidence_applicability_events",
                "transition_receipts",
                "verification_contracts",
                "grill_reviews",
                "adversarial_risks",
            )
        ):
            raise GovernanceError(
                "E_V246_ACCEPTANCE",
                "achieved projection cannot be derived from empty verification chains",
            )
        if (
            blocking
            or stale_or_invalid
            or not projection["independent_review_refs"]
            or not projection["completion_audit_refs"]
        ):
            raise GovernanceError(
                "E_V246_ACCEPTANCE", "achieved projection lacks completion predicates"
            )
    elif not blocking and not stale_or_invalid:
        # A caller may intentionally stop before acceptance, but the reason must
        # remain explicit instead of silently looking complete.
        if not projection["reason_codes"]:
            raise GovernanceError(
                "E_V246_ACCEPTANCE", "blocked projection lacks a reason"
            )


def validate_document(
    document: Any,
    fixture_root: str | os.PathLike[str] | None = None,
    *,
    manifest_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Validate one V2.46 governance bundle and return a stable envelope."""

    try:
        if not isinstance(document, dict):
            raise GovernanceError("E_V246_SCHEMA", "document must be an object")
        manifest = _load_json(Path(manifest_path) if manifest_path else DEFAULT_MANIFEST)
        _validate_manifest(manifest)
        schema = _load_json(DEFAULT_SCHEMA)
        if schema.get("$defs") is None or schema.get("properties", {}).get(
            "schema_version", {}
        ).get("const") != SCHEMA_VERSION:
            raise GovernanceError("E_V246_SCHEMA", "schema source drift")
        _schema_validate(document, schema, schema)
        _validate_shape(document)
        root = Path(fixture_root) if fixture_root is not None else None
        if document.get("acceptance_projection", {}).get("state") == "achieved" and root is None:
            raise GovernanceError(
                "E_V246_ARTIFACT",
                "achieved validation requires a frozen artifact root",
            )
        _validate_artifact_refs(document, root)
        _validate_predecessor_chain(document, root, schema)
        baseline = set(document["history_baseline_evidence_ids"])
        historical = set(document["historical_evidence_ids"])
        if not baseline <= historical:
            raise GovernanceError(
                "E_V246_HISTORY_REWRITE", "historical evidence baseline was deleted"
            )
        latest, history = _latest_applicability(document["evidence_applicability_events"])
        _validate_applicability_integrity(
            document["evidence_applicability_events"], historical
        )
        if set(latest) != historical:
            raise GovernanceError(
                "E_V246_TRACEABILITY",
                "historical Evidence registry and applicability ledger differ",
            )
        impact_items, blocking = _validate_changes_and_impacts(
            document, latest, history
        )
        current_evidence_ids = {
            evidence_id
            for evidence_id, event in latest.items()
            if event.get("evidence_integrity_state") == "valid"
            and event.get("evidence_applicability_state") == "current"
            and event.get("revalidation_state") in {"not_required", "closed"}
        }
        acceptance_projection = document["acceptance_projection"]
        acceptance_evidence_ids = set(
            acceptance_projection["acceptance_evidence_ids"]
        )
        if any(
            event.get("impact_item_id") not in impact_items
            for event in document["evidence_applicability_events"]
        ):
            raise GovernanceError(
                "E_V246_TRACEABILITY", "applicability event references unknown impact item"
            )
        blocking.extend(
            _validate_transitions(
                document["transition_receipts"],
                manifest,
                latest,
                root,
                str(document["bundle_id"]),
                int(document["revision"]),
            )
        )
        blocking.extend(
            _validate_contracts_and_reviews(
                document,
                manifest,
                historical,
                current_evidence_ids,
                acceptance_evidence_ids,
                acceptance_projection["state"] == "achieved",
                impact_items,
            )
        )
        _validate_acceptance(
            document, latest, sorted(set(blocking)), root, manifest
        )
        stale_count = sum(
            event.get("evidence_applicability_state") == "stale"
            for event in latest.values()
        )
        retest_count = sum(
            event.get("revalidation_state") == "retest_required"
            for event in latest.values()
        )
        invalid_count = sum(
            event.get("evidence_integrity_state") == "invalid"
            for event in latest.values()
        )
        not_run_count = sum(
            item.get("current_run_conclusion") == "not_run"
            for item in impact_items.values()
        )
        failed_count = sum(
            item.get("current_check_state") == "failed"
            or item.get("current_run_conclusion") == "failed"
            for item in impact_items.values()
        )
        blocked_count = sum(
            item.get("current_check_state") == "blocked"
            or item.get("current_run_conclusion") == "blocked"
            for item in impact_items.values()
        )
        flaky_count = sum(
            item.get("current_run_conclusion") == "flaky"
            for item in impact_items.values()
        )
        return {
            "ok": True,
            "error_code": "OK",
            "errors": [],
            "summary": {
                "bundle_id": document["bundle_id"],
                "revision": document["revision"],
                "profile": document["profile"],
                "historical_evidence_count": len(historical),
                "stale_evidence_count": stale_count,
                "stale_count": stale_count,
                "current_evidence_count": len(latest) - stale_count,
                "current_count": len(latest) - stale_count,
                "retest_required_count": retest_count,
                "not_run_count": not_run_count,
                "invalid_evidence_count": invalid_count,
                "invalid_count": invalid_count,
                "failed_count": failed_count,
                "blocked_count": blocked_count,
                "flaky_count": flaky_count,
                "impact_item_count": len(impact_items),
                "transition_receipt_count": len(document["transition_receipts"]),
                "blocking_reasons": sorted(set(blocking)),
                "acceptance_state": document["acceptance_projection"]["state"],
            },
        }
    except GovernanceError as exc:
        return {
            "ok": False,
            "error_code": exc.code,
            "errors": [exc.code],
            "summary": {},
        }
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "error_code": "E_V246_SCHEMA",
            "errors": ["E_V246_SCHEMA"],
            "summary": {},
        }


def _artifact(path: str) -> dict[str, str]:
    return {"path": path, "sha256": "0" * 64}


def _canonical_self_test_document() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": "SELFTEST",
        "revision": 1,
        "profile": "standard",
        "generated_at": "2026-07-27T00:00:00Z",
        "previous_bundle_ref": None,
        "history_baseline_evidence_ids": ["EV-OLD"],
        "historical_evidence_ids": ["EV-OLD"],
        "change_events": [{
            "change_id": "CH-1",
            "change_type": "rule",
            "changed_artifact_ref": _artifact("rule.md"),
            "before_revision": 1,
            "after_revision": 2,
            "before_sha256": "1" * 64,
            "after_sha256": "2" * 64,
            "semantic_change_summary": "unrelated clarification",
            "actor_run_id": "RUN-LEAD",
            "occurred_at": "2026-07-27T00:00:00Z"
        }],
        "impact_assessments": [{
            "assessment_id": "IA-1",
            "change_id": "CH-1",
            "contract_revision": 1,
            "denominator_item_ids": ["ITEM-1"],
            "items": [{
                "item_id": "ITEM-1",
                "target_type": "test",
                "target_id": "TEST-1",
                "impact_class": "unaffected",
                "dependency_path": [],
                "evidence_ids": ["EV-OLD"],
                "current_check_state": "passed",
                "current_run_conclusion": "achieved"
            }],
            "reviewer_run_id": "RUN-REVIEW",
            "revision": 1,
            "expected_revision": 0
        }],
        "evidence_applicability_events": [{
            "event_id": "EAE-1",
            "evidence_id": "EV-OLD",
            "impact_item_id": "ITEM-1",
            "evidence_integrity_state": "valid",
            "evidence_applicability_state": "current",
            "revalidation_state": "not_required",
            "reason_code": "UNCHANGED_DEPENDENCY",
            "evidence_refs": [_artifact("evidence.json")],
            "actor_run_id": "RUN-REVIEW",
            "run_id": "RUN-ORIGINAL",
            "attempt_id": "ATTEMPT-1",
            "revision": 1,
            "expected_revision": 0,
            "occurred_at": "2026-07-27T00:00:01Z"
        }],
        "transition_receipts": [{
            "receipt_id": "TR-1",
            "machine_id": "check_execution",
            "entity_id": "CHECK-1",
            "transition_event": "CHECK_STARTED",
            "from_state": "not_started",
            "to_state": "running",
            "expected_revision": 0,
            "new_revision": 1,
            "guard_results": [{
                "guard_id": "G-1",
                "passed": True,
                "evidence_refs": ["EV-OLD"]
            }],
            "actor_run_id": "RUN-RUNNER",
            "reason_code": "EXECUTION_STARTED",
            "evidence_refs": ["EV-OLD"],
            "occurred_at": "2026-07-27T00:00:02Z",
            "idempotency_key": "IDEMP-1"
        }],
        "verification_contracts": [{
            "contract_id": "VC-1",
            "revision": 1,
            "profile": "standard",
            "requirement_refs": ["REQ-1"],
            "acceptance_criteria_refs": ["AC-1"],
            "risk_denominator": ["RISK-1"],
            "unacceptable_risk_ids": ["RISK-1"],
            "pass_thresholds": {
                "required_checks": "all_passed",
                "required_runs": "achieved",
                "max_failed": 0,
                "max_blocked": 0,
                "max_not_run": 0,
                "max_flaky": 0
            },
            "role_bindings": {
                "owner_run_id": "RUN-OWNER",
                "designer_run_id": "RUN-DESIGN",
                "runner_run_id": "RUN-RUNNER",
                "reviewer_run_id": "RUN-REVIEW"
            },
            "evidence_requirements": [{
                "kind": "command_execution",
                "artifact_hash_required": True,
                "version_environment_binding_required": True
            }],
            "waiver_policy": {
                "required_allowed": False,
                "independent_approval_required": True
            },
            "change_approval_policy": {
                "scope_change_requires_approval": True,
                "spec_harness_update_required": True
            },
            "traceability": [{
                "requirement_id": "REQ-1",
                "acceptance_criteria_ids": ["AC-1"],
                "test_plan_ids": ["PLAN-1"],
                "test_case_ids": ["CASE-1"],
                "harness_check_ids": ["CHECK-1"],
                "run_ids": ["RUN-1"],
                "evidence_ids": ["EV-OLD"]
            }]
        }],
        "grill_reviews": [{
            "grill_id": "GRILL-1",
            "contract_id": "VC-1",
            "requirement_id": "REQ-1",
            "critical": True,
            "definition": "Requirement is evidence bound",
            "basis_refs": ["REQ-1", "AC-1"],
            "version_environment_refs": [_artifact("environment.json")],
            "failure_path": "Block acceptance",
            "residual_risks": [],
            "na": {
                "claimed": False,
                "reason": "",
                "impact_assessment_ref": "",
                "approval_ref": None,
                "approver_run_id": ""
            },
            "evidence_refs": ["EV-OLD"],
            "reviewer_run_id": "RUN-REVIEW",
            "conclusion": "answered_with_evidence"
        }],
        "adversarial_risks": [{
            "risk_id": "RISK-1",
            "category": "forged_or_stale_evidence",
            "applicable": True,
            "required": True,
            "coverage_state": "passed",
            "case_ids": ["CASE-1"],
            "assertion_ids": ["ASSERT-1"],
            "run_ids": ["RUN-1"],
            "evidence_refs": ["EV-OLD"],
            "reviewer_run_id": "RUN-REVIEW",
            "na_reason": "",
            "na_approval_ref": None,
            "na_approver_run_id": ""
        }],
        "acceptance_projection": {
            "state": "achieved",
            "derived_by_run_id": "RUN-AUDIT",
            "acceptance_evidence_ids": ["EV-OLD"],
            "independent_review_refs": [_artifact("review.json")],
            "completion_audit_refs": [_artifact("audit.json")],
            "reason_codes": []
        }
    }


def self_test() -> dict[str, Any]:
    positive = _canonical_self_test_document()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        receipt_core = {
            "schema_version": "goal-teams-v246-review-receipt-v1",
            "bundle_id": positive["bundle_id"],
            "bundle_revision": positive["revision"],
            "acceptance_evidence_ids": positive["acceptance_projection"][
                "acceptance_evidence_ids"
            ],
            "completion_predicates": {
                "required_checks_passed": True,
                "required_runs_achieved": True,
                "evidence_current_valid": True,
                "risk_denominator_closed": True,
            },
            "conclusion": "passed",
        }
        for relative_path, content in {
            "review.json": {
                **receipt_core,
                "receipt_type": "independent_review",
                "actor_run_id": "RUN-REVIEW",
            },
            "audit.json": {
                **receipt_core,
                "receipt_type": "completion_audit",
                "actor_run_id": "RUN-AUDIT",
            },
        }.items():
            (root / relative_path).write_text(
                json.dumps(content, sort_keys=True), encoding="utf-8"
            )
        for ref in _iter_artifact_refs(positive):
            path = root / str(ref["path"])
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
            ref["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result = validate_document(positive, fixture_root=root)
        if not result["ok"]:
            raise GovernanceError("E_V246_SELF_TEST", f"positive fixture failed: {result}")
        negative_history = copy.deepcopy(positive)
        negative_history["historical_evidence_ids"] = []
        history_result = validate_document(negative_history, fixture_root=root)
        if history_result["error_code"] != "E_V246_HISTORY_REWRITE":
            raise GovernanceError("E_V246_SELF_TEST", "history rewrite negative fixture missed")
        negative_transition = copy.deepcopy(positive)
        negative_transition["transition_receipts"][0]["to_state"] = "passed"
        transition_result = validate_document(negative_transition, fixture_root=root)
        if transition_result["error_code"] != "E_V246_TRANSITION":
            raise GovernanceError("E_V246_SELF_TEST", "transition negative fixture missed")
        negative_stale = copy.deepcopy(positive)
        negative_stale["evidence_applicability_events"][0][
            "evidence_applicability_state"
        ] = "stale"
        stale_result = validate_document(negative_stale, fixture_root=root)
        if stale_result["error_code"] != "E_V246_IMPACT_SEMANTICS":
            raise GovernanceError("E_V246_SELF_TEST", "unaffected stale negative fixture missed")
    return {
        "ok": True,
        "passed": True,
        "error_code": "OK",
        "errors": [],
        "valid_cases_executed": 1,
        "invalid_cases_executed": 3,
        "summary": {"positive": 1, "negative": 3},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--fixture-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            result = self_test()
        except GovernanceError as exc:
            result = {
                "ok": False,
                "error_code": exc.code,
                "errors": [exc.code],
                "summary": {},
            }
    elif args.input:
        try:
            document = _load_json(args.input)
            result = validate_document(
                document,
                fixture_root=args.fixture_root,
                manifest_path=args.manifest,
            )
        except GovernanceError as exc:
            result = {
                "ok": False,
                "error_code": exc.code,
                "errors": [exc.code],
                "summary": {},
            }
    else:
        parser.error("--input or --self-test is required")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
