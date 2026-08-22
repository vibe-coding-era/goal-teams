"""Append-only V2.63 task-state reducer with CAS and binding checks.

The canonical event stream is the writable fact source.  Projections are
deterministic, read-only results and never authorize a transition by
themselves.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ZERO_SHA256 = "0" * 64
REQUIRED_BINDINGS = (
    "source_sha256",
    "route_sha256",
    "contract_sha256",
    "task_exact_set_sha256",
    "environment_sha256",
    "authorization_lineage_sha256",
)
LEGACY_BINDINGS = tuple(
    field for field in REQUIRED_BINDINGS if field != "authorization_lineage_sha256"
)
DEFAULT_STATES = {
    "task": "pending",
    "check": "not_run",
    "evidence": "not_run",
    "audit": "not_run",
    "run": "not_run",
    "goal": "pending",
}
TRANSITIONS = {
    "task": {
        "pending": {"active", "blocked"},
        "active": {"accepted", "failed", "blocked", "stale"},
        "failed": {"active", "blocked"},
        "blocked": {"active"},
        "stale": {"active"},
        "accepted": {"stale"},
    },
    "check": {
        "not_run": {"passed", "failed", "blocked", "not_required"},
        "failed": {"passed", "blocked"},
        "blocked": {"passed", "failed"},
        "passed": {"stale"},
        "stale": {"passed", "failed", "blocked"},
        "not_required": set(),
    },
    "evidence": {
        "not_run": {"valid", "invalid", "blocked"},
        "valid": {"stale", "invalid"},
        "stale": {"valid", "invalid"},
        "invalid": {"valid"},
        "blocked": {"valid", "invalid"},
    },
    "audit": {
        "not_run": {"passed", "failed", "blocked"},
        "failed": {"passed", "blocked"},
        "blocked": {"passed", "failed"},
        "passed": {"stale"},
        "stale": {"passed", "failed", "blocked"},
    },
    "run": {
        "not_run": {"passed", "failed", "blocked"},
        "failed": {"passed", "blocked"},
        "blocked": {"passed", "failed"},
        "passed": {"stale"},
        "stale": {"passed", "failed", "blocked"},
    },
    "goal": {
        "pending": {"active", "blocked"},
        "active": {"achieved", "blocked", "failed"},
        "blocked": {"active"},
        "failed": {"active", "blocked"},
        "achieved": {"stale"},
        "stale": {"active"},
    },
}
WRITER_ALLOWLIST = {
    "task": {"goal_lead", "state_reducer"},
    "check": {"goal_lead", "validator", "state_reducer"},
    "evidence": {"goal_lead", "validator", "state_reducer"},
    "audit": {"goal_lead", "completion_auditor", "state_reducer"},
    "run": {"goal_lead", "runner", "state_reducer"},
    "goal": {"goal_lead", "completion_auditor", "state_reducer"},
}
COMPLETION_STATUSES = {
    "passed",
    "failed",
    "blocked",
    "not_run",
    "not_required",
    "stale",
    "invalid",
    "unavailable",
}
TASK_PROJECTION_STATES = {
    "pending",
    "active",
    "accepted",
    "completed",
    "failed",
    "blocked",
    "stale",
    "cancelled",
}
VALIDATION_RECEIPT_TYPES = {
    "task_verification",
    "task_exit",
    "development_denominator",
    "git_scope",
    "runtime_observation",
    "business_validation",
    "release_gate",
    "release_publication",
    "installation_readback",
    "open_gap_audit",
}
BUDGET_TYPES = ("work_unit", "attempt", "revalidation")


class StateReducerError(ValueError):
    """Stable fail-closed task-state error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _non_empty_strings(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_non_empty(item) for item in value)
        and len(value) == len(set(value))
    )


def _validated_bindings(
    value: Mapping[str, Any], *, allow_legacy_api: bool = False
) -> dict[str, str]:
    observed_fields = set(value)
    if allow_legacy_api and observed_fields == set(LEGACY_BINDINGS):
        value = {**value, "authorization_lineage_sha256": ZERO_SHA256}
        observed_fields = set(value)
    if observed_fields != set(REQUIRED_BINDINGS):
        raise StateReducerError(
            "E_V263_STATE_BINDING", "event bindings must use the exact binding set"
        )
    result: dict[str, str] = {}
    for field in REQUIRED_BINDINGS:
        digest = value.get(field)
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise StateReducerError(
                "E_V263_STATE_BINDING", f"invalid binding digest: {field}"
            )
        result[field] = digest
    return result


def _validate_observations(
    receipt_type: str, status: str, observations: Mapping[str, Any]
) -> None:
    exact_fields: dict[str, set[str]] = {
        "task_verification": {
            "task_id",
            "verification_contract_sha256",
            "outcome",
        },
        "task_exit": {
            "task_id",
            "exit_condition_sha256",
            "verification_receipt_sha256",
            "condition_met",
        },
        "development_denominator": {
            "phase",
            "exact_task_ids",
            "denominator_sha256",
        },
        "git_scope": {
            "baseline_sha256",
            "working_state_sha256",
            "in_scope",
        },
        "runtime_observation": {
            "exact_task_ids",
            "observation_sha256",
            "host_execution_id",
            "fresh",
        },
        "business_validation": {
            "oracle_contract_sha256",
            "observation_sha256",
            "oracle_identity",
            "accepted",
        },
        "release_gate": {
            "exact_task_ids",
            "frozen_identity_sha256",
            "gate_receipt_sha256",
        },
        "release_publication": {
            "tag_name",
            "release_id",
            "expected_tag_target_sha256",
            "observed_tag_target_sha256",
            "expected_asset_ids",
            "observed_asset_ids",
        },
        "installation_readback": {
            "expected_source_sha256",
            "observed_source_sha256",
            "expected_artifact_sha256",
            "observed_artifact_sha256",
            "expected_version",
            "observed_version",
            "expected_canonical_path",
            "observed_canonical_path",
        },
        "open_gap_audit": {"open_gap_ids"},
    }
    if set(observations) != exact_fields[receipt_type]:
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT",
            f"{receipt_type} observations differ from the typed contract",
        )

    sha_fields = {
        "verification_contract_sha256",
        "exit_condition_sha256",
        "verification_receipt_sha256",
        "denominator_sha256",
        "baseline_sha256",
        "working_state_sha256",
        "observation_sha256",
        "oracle_contract_sha256",
        "frozen_identity_sha256",
        "gate_receipt_sha256",
        "expected_tag_target_sha256",
        "observed_tag_target_sha256",
        "expected_source_sha256",
        "observed_source_sha256",
        "expected_artifact_sha256",
        "observed_artifact_sha256",
    }
    for field in sha_fields & set(observations):
        if not _sha256(observations[field]):
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT", f"invalid observation digest: {field}"
            )
    for field in (
        "task_id",
        "phase",
        "host_execution_id",
        "oracle_identity",
        "tag_name",
        "release_id",
        "expected_version",
        "observed_version",
        "expected_canonical_path",
        "observed_canonical_path",
    ):
        if field in observations and not _non_empty(observations[field]):
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT", f"invalid observation: {field}"
            )
    for field in (
        "exact_task_ids",
        "expected_asset_ids",
        "observed_asset_ids",
    ):
        if field in observations and not _non_empty_strings(observations[field], allow_empty=True):
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT", f"invalid observation list: {field}"
            )
    if "open_gap_ids" in observations and not _non_empty_strings(
        observations["open_gap_ids"], allow_empty=True
    ):
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "invalid open gap exact set"
        )
    for field in ("condition_met", "in_scope", "fresh", "accepted"):
        if field in observations and type(observations[field]) is not bool:
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT", f"invalid exact boolean: {field}"
            )
    if receipt_type == "task_verification" and observations.get("outcome") not in {
        "passed",
        "failed",
        "blocked",
    }:
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "invalid verification outcome"
        )
    if receipt_type == "development_denominator" and observations.get("phase") != "development":
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "development denominator phase differs"
        )

    if status == "passed":
        required_true = {
            "task_exit": "condition_met",
            "git_scope": "in_scope",
            "runtime_observation": "fresh",
            "business_validation": "accepted",
        }
        boolean_field = required_true.get(receipt_type)
        if boolean_field and observations.get(boolean_field) is not True:
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT",
                f"passed {receipt_type} contradicts {boolean_field}",
            )
        if receipt_type == "task_verification" and observations.get("outcome") != "passed":
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT",
                "passed task verification contradicts its outcome",
            )
        if receipt_type == "open_gap_audit" and observations.get("open_gap_ids"):
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT", "passed gap audit has open gaps"
            )
        if receipt_type == "release_publication":
            if (
                observations["expected_tag_target_sha256"]
                != observations["observed_tag_target_sha256"]
                or observations["expected_asset_ids"]
                != observations["observed_asset_ids"]
            ):
                raise StateReducerError(
                    "E_V263_VALIDATION_RECEIPT",
                    "publication tag target or asset exact set differs",
                )
        if receipt_type == "installation_readback":
            pairs = (
                ("expected_source_sha256", "observed_source_sha256"),
                ("expected_artifact_sha256", "observed_artifact_sha256"),
                ("expected_version", "observed_version"),
                ("expected_canonical_path", "observed_canonical_path"),
            )
            if any(observations[expected] != observations[observed] for expected, observed in pairs):
                raise StateReducerError(
                    "E_V263_VALIDATION_RECEIPT",
                    "canonical installation exact readback differs",
                )


def make_validation_receipt(
    *,
    receipt_type: str,
    subject_id: str,
    status: str,
    bindings: Mapping[str, Any],
    evidence_refs: Iterable[str],
    observations: Mapping[str, Any],
    validator_identity: str,
    issued_at: str,
) -> dict[str, Any]:
    """Build a typed validation receipt; validation is repeated by every consumer."""

    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-validation-receipt-v2.65",
        "receipt_type": receipt_type,
        "subject_id": subject_id,
        "status": status,
        "bindings": _validated_bindings(bindings),
        "evidence_refs": list(evidence_refs),
        "observations": copy.deepcopy(dict(observations)),
        "validator_identity": validator_identity,
        "issued_at": issued_at,
    }
    receipt["receipt_digest"] = _digest(receipt)
    return validate_validation_receipt(receipt)


def validate_validation_receipt(
    receipt: Mapping[str, Any], *, expected_bindings: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    required = {
        "schema_version",
        "receipt_type",
        "subject_id",
        "status",
        "bindings",
        "evidence_refs",
        "observations",
        "validator_identity",
        "issued_at",
        "receipt_digest",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != required:
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt fields differ"
        )
    if receipt.get("schema_version") != "goal-teams-validation-receipt-v2.65":
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt schema differs"
        )
    receipt_type = receipt.get("receipt_type")
    if receipt_type not in VALIDATION_RECEIPT_TYPES:
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "unknown validation receipt type"
        )
    if not _non_empty(receipt.get("subject_id")) or not _non_empty(
        receipt.get("validator_identity")
    ) or not _non_empty(receipt.get("issued_at")):
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt identity differs"
        )
    if receipt.get("status") not in COMPLETION_STATUSES:
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt status differs"
        )
    refs = receipt.get("evidence_refs")
    if not _non_empty_strings(refs):
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt evidence differs"
        )
    bindings = receipt.get("bindings")
    if not isinstance(bindings, Mapping):
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt bindings differ"
        )
    validated_bindings = _validated_bindings(bindings)
    if expected_bindings is not None and validated_bindings != _validated_bindings(
        expected_bindings
    ):
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt binding differs"
        )
    observations = receipt.get("observations")
    if not isinstance(observations, Mapping):
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT", "validation receipt observations differ"
        )
    _validate_observations(str(receipt_type), str(receipt["status"]), observations)
    payload = dict(receipt)
    observed = payload.pop("receipt_digest")
    if not _sha256(observed) or _digest(payload) != observed:
        raise StateReducerError(
            "E_V263_VALIDATION_RECEIPT_DIGEST", "validation receipt digest differs"
        )
    return copy.deepcopy(dict(receipt))


def _index_validation_receipts(
    receipts: Iterable[Mapping[str, Any]], *, expected_bindings: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    by_digest: dict[str, dict[str, Any]] = {}
    by_subject: dict[tuple[str, str], dict[str, Any]] = {}
    for receipt in receipts:
        validated = validate_validation_receipt(
            receipt, expected_bindings=expected_bindings
        )
        digest = validated["receipt_digest"]
        key = (validated["receipt_type"], validated["subject_id"])
        if digest in by_digest or key in by_subject:
            raise StateReducerError(
                "E_V263_VALIDATION_RECEIPT_DUPLICATE",
                "validation receipt identity is duplicated",
            )
        by_digest[digest] = validated
        by_subject[key] = validated
    return by_digest, by_subject


def make_state_event(
    *,
    event_id: str,
    event_seq: int,
    event_type: str,
    axis: str,
    entity_id: str,
    previous_event_sha256: str,
    cas_base_revision: int,
    before_state: str,
    requested_state: str,
    bindings: Mapping[str, Any],
    actor_identity: str,
    actor_relationship: str,
    evidence_refs: Iterable[str],
    occurred_at: str,
) -> dict[str, Any]:
    """Build a canonical event; reducer validation remains authoritative."""

    event = {
        "schema_version": "goal-teams-state-event-v2.65",
        "event_id": event_id,
        "event_seq": event_seq,
        "event_type": event_type,
        "axis": axis,
        "entity_id": entity_id,
        "previous_event_sha256": previous_event_sha256,
        "cas_base_revision": cas_base_revision,
        "before_state": before_state,
        "requested_state": requested_state,
        "bindings": _validated_bindings(bindings, allow_legacy_api=True),
        "actor_identity": actor_identity,
        "actor_relationship": actor_relationship,
        "evidence_refs": list(evidence_refs),
        "occurred_at": occurred_at,
    }
    event["event_sha256"] = _digest(event)
    return event


def _validate_event_shape(event: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "event_id",
        "event_seq",
        "event_type",
        "axis",
        "entity_id",
        "previous_event_sha256",
        "cas_base_revision",
        "before_state",
        "requested_state",
        "bindings",
        "actor_identity",
        "actor_relationship",
        "evidence_refs",
        "occurred_at",
        "event_sha256",
    }
    if set(event) != required:
        raise StateReducerError("E_V263_STATE_EVENT", "event fields differ")
    if event.get("schema_version") != "goal-teams-state-event-v2.65":
        raise StateReducerError("E_V263_STATE_EVENT", "unknown event schema")
    for field in (
        "event_id",
        "event_type",
        "axis",
        "entity_id",
        "before_state",
        "requested_state",
        "actor_identity",
        "actor_relationship",
        "occurred_at",
    ):
        if not isinstance(event.get(field), str) or not event[field]:
            raise StateReducerError("E_V263_STATE_EVENT", f"invalid {field}")
    for field in ("event_seq", "cas_base_revision"):
        if (
            not isinstance(event.get(field), int)
            or isinstance(event[field], bool)
            or event[field] < 0
        ):
            raise StateReducerError("E_V263_STATE_EVENT", f"invalid {field}")
    for field in ("previous_event_sha256", "event_sha256"):
        if not isinstance(event.get(field), str) or not SHA256_RE.fullmatch(event[field]):
            raise StateReducerError("E_V263_STATE_EVENT", f"invalid {field}")
    refs = event.get("evidence_refs")
    if not isinstance(refs, list) or not refs or not all(
        isinstance(item, str) and item for item in refs
    ):
        raise StateReducerError("E_V263_STATE_EVENT", "invalid evidence refs")
    bindings = event.get("bindings")
    if not isinstance(bindings, Mapping):
        raise StateReducerError("E_V263_STATE_BINDING", "bindings must be an object")
    _validated_bindings(bindings)
    payload = dict(event)
    observed = payload.pop("event_sha256")
    if _digest(payload) != observed:
        raise StateReducerError("E_V263_STATE_EVENT_DIGEST", "event digest differs")


def reduce_state_events(
    events: Iterable[Mapping[str, Any]],
    *,
    expected_bindings: Mapping[str, Any],
    validation_receipts: Iterable[Mapping[str, Any]] | None = None,
    compiled_task_plan: Mapping[str, Any] | None = None,
    task_plan_validation_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay canonical events into a deterministic read-only projection."""

    bindings = _validated_bindings(expected_bindings, allow_legacy_api=True)
    strict_receipts = validation_receipts is not None
    receipts_by_digest: dict[str, dict[str, Any]] = {}
    receipts_by_subject: dict[tuple[str, str], dict[str, Any]] = {}
    compiled_tasks: dict[str, Mapping[str, Any]] = {}
    validated_plan_receipt_digest: str | None = None
    if strict_receipts:
        if compiled_task_plan is None or task_plan_validation_receipt is None:
            raise StateReducerError(
                "E_V263_STATE_PLAN_BINDING",
                "authoritative reduction requires a compiled task plan receipt",
            )
        from scripts.v250.task_plan_compiler import (  # pylint: disable=import-outside-toplevel
            TaskPlanError,
            validate_compiled_task_plan,
        )

        try:
            expected_plan_validation = validate_compiled_task_plan(compiled_task_plan)
        except TaskPlanError as exc:
            raise StateReducerError(
                "E_V263_STATE_PLAN_BINDING", "compiled task plan is invalid"
            ) from exc
        if dict(task_plan_validation_receipt) != expected_plan_validation:
            raise StateReducerError(
                "E_V263_STATE_PLAN_BINDING",
                "task plan validation receipt differs",
            )
        if bindings["task_exact_set_sha256"] != compiled_task_plan.get(
            "task_exact_set_digest"
        ):
            raise StateReducerError(
                "E_V263_STATE_PLAN_BINDING", "task exact-set binding differs"
            )
        compiled_tasks = {
            str(task["task_id"]): task for task in compiled_task_plan["tasks"]
        }
        validated_plan_receipt_digest = expected_plan_validation["receipt_digest"]
        receipts_by_digest, receipts_by_subject = _index_validation_receipts(
            validation_receipts, expected_bindings=bindings
        )
    axes: dict[str, dict[str, str]] = {axis: {} for axis in DEFAULT_STATES}
    accepted_task_receipts: dict[str, dict[str, str]] = {}
    revision = 0
    previous = ZERO_SHA256
    event_count = 0
    for event_count, event in enumerate(events, start=1):
        if not isinstance(event, Mapping):
            raise StateReducerError("E_V263_STATE_EVENT", "event must be an object")
        _validate_event_shape(event)
        if event["event_seq"] != event_count:
            raise StateReducerError("E_V263_STATE_SEQUENCE", "event sequence differs")
        if event["previous_event_sha256"] != previous:
            raise StateReducerError("E_V263_STATE_HASH_CHAIN", "previous digest differs")
        if event["cas_base_revision"] != revision:
            raise StateReducerError("E_V263_STATE_CAS", "CAS revision differs")
        if dict(event["bindings"]) != bindings:
            raise StateReducerError("E_V263_STATE_BINDING", "event binding differs")
        axis = str(event["axis"])
        if axis not in TRANSITIONS or event["event_type"] != f"{axis}.transition":
            raise StateReducerError("E_V263_STATE_TRANSITION", "unknown axis or event type")
        if event["actor_identity"] not in WRITER_ALLOWLIST[axis]:
            raise StateReducerError("E_V263_STATE_WRITER", "actor cannot write this axis")
        entity = str(event["entity_id"])
        before = axes[axis].get(entity, DEFAULT_STATES[axis])
        if event["before_state"] != before:
            raise StateReducerError("E_V263_STATE_TRANSITION", "before state differs")
        requested = str(event["requested_state"])
        if requested not in TRANSITIONS[axis].get(before, set()):
            raise StateReducerError(
                "E_V263_STATE_TRANSITION", f"illegal {axis}: {before} -> {requested}"
            )
        if strict_receipts and axis == "task" and requested == "accepted":
            task = compiled_tasks.get(entity)
            if task is None:
                raise StateReducerError(
                    "E_V263_STATE_TASK_EXACT_SET", "accepted task is not in the exact set"
                )
            verification = receipts_by_subject.get(("task_verification", entity))
            exit_receipt = receipts_by_subject.get(("task_exit", entity))
            if verification is None or exit_receipt is None:
                raise StateReducerError(
                    "E_V263_STATE_TASK_RECEIPT",
                    "accepted task lacks verification or exit receipt",
                )
            if verification["status"] != "passed" or exit_receipt["status"] != "passed":
                raise StateReducerError(
                    "E_V263_STATE_TASK_RECEIPT",
                    "accepted task receipt did not pass",
                )
            if verification["observations"] != {
                "task_id": entity,
                "verification_contract_sha256": _digest(task["verification"]),
                "outcome": "passed",
            }:
                raise StateReducerError(
                    "E_V263_STATE_TASK_RECEIPT",
                    "task verification receipt is not bound to the frozen contract",
                )
            expected_exit = {
                "task_id": entity,
                "exit_condition_sha256": _digest(task["exit_condition"]),
                "verification_receipt_sha256": verification["receipt_digest"],
                "condition_met": True,
            }
            if exit_receipt["observations"] != expected_exit:
                raise StateReducerError(
                    "E_V263_STATE_TASK_RECEIPT",
                    "task exit receipt is not bound to verification and exit contract",
                )
            required_refs = {
                f"sha256:{verification['receipt_digest']}",
                f"sha256:{exit_receipt['receipt_digest']}",
            }
            if not required_refs.issubset(set(event["evidence_refs"])):
                raise StateReducerError(
                    "E_V263_STATE_TASK_RECEIPT",
                    "accepted event does not cite both typed receipts",
                )
            accepted_task_receipts[entity] = {
                "verification_receipt_sha256": verification["receipt_digest"],
                "exit_receipt_sha256": exit_receipt["receipt_digest"],
            }
        axes[axis][entity] = requested
        revision += 1
        previous = str(event["event_sha256"])

    projection: dict[str, Any] = {
        "schema_version": "goal-teams-state-projection-v2.65",
        "revision": revision,
        "event_count": event_count,
        "last_event_sha256": previous,
        "bindings": bindings,
        "axes": axes,
        "projection_writer": "scripts.v250.state_reducer",
        "validation_authority": (
            "authoritative" if strict_receipts else "unverified_compatibility"
        ),
        "accepted_task_receipts": accepted_task_receipts,
    }
    if validated_plan_receipt_digest is not None:
        projection["task_plan_validation_receipt_digest"] = (
            validated_plan_receipt_digest
        )
    projection["projection_sha256"] = _digest(projection)
    return projection


def rebuild_projection(
    events: Iterable[Mapping[str, Any]],
    *,
    expected_bindings: Mapping[str, Any],
    expected_projection_sha256: str,
    validation_receipts: Iterable[Mapping[str, Any]] | None = None,
    compiled_task_plan: Mapping[str, Any] | None = None,
    task_plan_validation_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    projection = reduce_state_events(
        events,
        expected_bindings=expected_bindings,
        validation_receipts=validation_receipts,
        compiled_task_plan=compiled_task_plan,
        task_plan_validation_receipt=task_plan_validation_receipt,
    )
    if projection["projection_sha256"] != expected_projection_sha256:
        raise StateReducerError(
            "E_V263_STATE_REPLAY_MISMATCH", "reconstructed projection differs"
        )
    return projection


def validate_state_projection(
    events: Iterable[Mapping[str, Any]],
    *,
    expected_bindings: Mapping[str, Any],
    supplied_projection: Mapping[str, Any],
    validation_receipts: Iterable[Mapping[str, Any]],
    compiled_task_plan: Mapping[str, Any],
    task_plan_validation_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Replay and bind an authoritative state projection to typed receipts."""

    event_list = list(events)
    receipt_list = list(validation_receipts)
    rebuilt = reduce_state_events(
        event_list,
        expected_bindings=expected_bindings,
        validation_receipts=receipt_list,
        compiled_task_plan=compiled_task_plan,
        task_plan_validation_receipt=task_plan_validation_receipt,
    )
    if dict(supplied_projection) != rebuilt:
        raise StateReducerError(
            "E_V263_STATE_REPLAY_MISMATCH", "supplied state projection differs"
        )
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-state-projection-validation-receipt-v1",
        "projection_sha256": rebuilt["projection_sha256"],
        "last_event_sha256": rebuilt["last_event_sha256"],
        "event_count": rebuilt["event_count"],
        "bindings_sha256": _digest(rebuilt["bindings"]),
        "task_exact_set_sha256": rebuilt["bindings"]["task_exact_set_sha256"],
        "task_plan_validation_receipt_digest": task_plan_validation_receipt[
            "receipt_digest"
        ],
        "accepted_task_receipts_sha256": _digest(
            rebuilt["accepted_task_receipts"]
        ),
        "observed_task_ids": sorted(rebuilt["axes"]["task"]),
        "validator": "scripts.v250.state_reducer.validate_state_projection",
        "valid": True,
    }
    receipt["receipt_digest"] = _digest(receipt)
    return receipt


def _all_accepted(states: Mapping[str, str]) -> bool:
    return bool(states) and all(value == "accepted" for value in states.values())


def make_budget_event(
    *,
    event_id: str,
    event_seq: int,
    previous_event_sha256: str,
    cas_base_revision: int,
    task_id: str,
    consumption_type: str,
    amount: int,
    task_exact_set_digest: str,
    compiled_plan_receipt_digest: str,
    evidence_refs: Iterable[str],
    occurred_at: str,
) -> dict[str, Any]:
    """Create a consumption request whose only projection writer is the reducer."""

    event: dict[str, Any] = {
        "schema_version": "goal-teams-budget-event-v1",
        "event_id": event_id,
        "event_seq": event_seq,
        "previous_event_sha256": previous_event_sha256,
        "cas_base_revision": cas_base_revision,
        "task_id": task_id,
        "consumption_type": consumption_type,
        "amount": amount,
        "task_exact_set_digest": task_exact_set_digest,
        "compiled_plan_receipt_digest": compiled_plan_receipt_digest,
        "actor_identity": "state_reducer",
        "evidence_refs": list(evidence_refs),
        "occurred_at": occurred_at,
    }
    event["event_sha256"] = _digest(event)
    return event


def _validate_budget_event(event: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "event_id",
        "event_seq",
        "previous_event_sha256",
        "cas_base_revision",
        "task_id",
        "consumption_type",
        "amount",
        "task_exact_set_digest",
        "compiled_plan_receipt_digest",
        "actor_identity",
        "evidence_refs",
        "occurred_at",
        "event_sha256",
    }
    if not isinstance(event, Mapping) or set(event) != required:
        raise StateReducerError("E_V263_BUDGET_EVENT", "budget event fields differ")
    if event.get("schema_version") != "goal-teams-budget-event-v1":
        raise StateReducerError("E_V263_BUDGET_EVENT", "budget event schema differs")
    for field in ("event_id", "task_id", "occurred_at"):
        if not _non_empty(event.get(field)):
            raise StateReducerError("E_V263_BUDGET_EVENT", f"invalid {field}")
    for field in ("event_seq", "cas_base_revision"):
        if (
            not isinstance(event.get(field), int)
            or isinstance(event[field], bool)
            or event[field] < (1 if field == "event_seq" else 0)
        ):
            raise StateReducerError("E_V263_BUDGET_EVENT", f"invalid {field}")
    if (
        not isinstance(event.get("amount"), int)
        or isinstance(event["amount"], bool)
        or event["amount"] <= 0
    ):
        raise StateReducerError("E_V263_BUDGET_EVENT", "invalid amount")
    if event.get("consumption_type") not in BUDGET_TYPES:
        raise StateReducerError("E_V263_BUDGET_EVENT", "invalid consumption type")
    if event.get("actor_identity") != "state_reducer":
        raise StateReducerError(
            "E_V263_BUDGET_WRITER", "only state_reducer may write the budget ledger"
        )
    for field in (
        "previous_event_sha256",
        "task_exact_set_digest",
        "compiled_plan_receipt_digest",
        "event_sha256",
    ):
        if not _sha256(event.get(field)):
            raise StateReducerError("E_V263_BUDGET_EVENT", f"invalid {field}")
    if not _non_empty_strings(event.get("evidence_refs")):
        raise StateReducerError("E_V263_BUDGET_EVENT", "invalid evidence refs")
    payload = dict(event)
    observed = payload.pop("event_sha256")
    if _digest(payload) != observed:
        raise StateReducerError(
            "E_V263_BUDGET_EVENT_DIGEST", "budget event digest differs"
        )


def reduce_budget_events(
    compiled_task_plan: Mapping[str, Any],
    task_plan_validation_receipt: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive all remaining WU/attempt/revalidation values from immutable events."""

    from scripts.v250.task_plan_compiler import (  # pylint: disable=import-outside-toplevel
        TaskPlanError,
        validate_compiled_task_plan,
    )

    try:
        expected_plan_validation = validate_compiled_task_plan(compiled_task_plan)
    except TaskPlanError as exc:
        raise StateReducerError(
            "E_V263_BUDGET_PLAN_BINDING", "compiled task plan is invalid"
        ) from exc
    if dict(task_plan_validation_receipt) != expected_plan_validation:
        raise StateReducerError(
            "E_V263_BUDGET_PLAN_BINDING", "task plan validation receipt differs"
        )
    task_contracts = {
        str(task["task_id"]): task for task in compiled_task_plan["tasks"]
    }
    allocated = {
        task_id: {
            "work_unit": task["budget_wu"],
            "attempt": task["attempt_budget"],
            "revalidation": task["revalidation_budget"],
        }
        for task_id, task in task_contracts.items()
    }
    consumed = {
        task_id: {budget_type: 0 for budget_type in BUDGET_TYPES}
        for task_id in task_contracts
    }
    revision = 0
    previous = ZERO_SHA256
    event_count = 0
    for event_count, event in enumerate(events, start=1):
        _validate_budget_event(event)
        if event["event_seq"] != event_count:
            raise StateReducerError(
                "E_V263_BUDGET_SEQUENCE", "budget event sequence differs"
            )
        if event["previous_event_sha256"] != previous:
            raise StateReducerError(
                "E_V263_BUDGET_HASH_CHAIN", "budget previous digest differs"
            )
        if event["cas_base_revision"] != revision:
            raise StateReducerError("E_V263_BUDGET_CAS", "budget CAS revision differs")
        if event["task_exact_set_digest"] != compiled_task_plan["task_exact_set_digest"]:
            raise StateReducerError(
                "E_V263_BUDGET_PLAN_BINDING", "budget task exact set differs"
            )
        if event["compiled_plan_receipt_digest"] != compiled_task_plan["receipt_digest"]:
            raise StateReducerError(
                "E_V263_BUDGET_PLAN_BINDING", "budget compiled receipt differs"
            )
        task_id = str(event["task_id"])
        if task_id not in task_contracts:
            raise StateReducerError(
                "E_V263_BUDGET_TASK", "budget event task is outside the exact set"
            )
        budget_type = str(event["consumption_type"])
        next_consumed = consumed[task_id][budget_type] + int(event["amount"])
        if next_consumed > allocated[task_id][budget_type]:
            raise StateReducerError(
                "E_V263_BUDGET_EXCEEDED",
                f"{task_id} {budget_type} exceeds its frozen budget",
            )
        consumed[task_id][budget_type] = next_consumed
        revision += 1
        previous = str(event["event_sha256"])

    tasks: dict[str, Any] = {}
    for task_id, task in task_contracts.items():
        remaining = {
            budget_type: allocated[task_id][budget_type]
            - consumed[task_id][budget_type]
            for budget_type in BUDGET_TYPES
        }
        exhausted = [
            budget_type for budget_type in BUDGET_TYPES if remaining[budget_type] == 0
        ]
        tasks[task_id] = {
            "allocated": allocated[task_id],
            "consumed": consumed[task_id],
            "remaining": remaining,
            "exhausted_budget_types": exhausted,
            "exhaustion_projection": (
                task["exit_condition"]["on_budget_exhaustion"]
                if exhausted
                else "not_required"
            ),
        }
    projection: dict[str, Any] = {
        "schema_version": "goal-teams-budget-projection-v1",
        "revision": revision,
        "event_count": event_count,
        "last_event_sha256": previous,
        "task_exact_set_digest": compiled_task_plan["task_exact_set_digest"],
        "compiled_plan_receipt_digest": compiled_task_plan["receipt_digest"],
        "task_plan_validation_receipt_digest": task_plan_validation_receipt[
            "receipt_digest"
        ],
        "tasks": tasks,
        "projection_writer": "state_reducer",
    }
    projection["projection_digest"] = _digest(projection)
    return projection


def validate_budget_projection(
    compiled_task_plan: Mapping[str, Any],
    task_plan_validation_receipt: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    supplied_projection: Mapping[str, Any],
) -> dict[str, Any]:
    event_list = list(events)
    rebuilt = reduce_budget_events(
        compiled_task_plan, task_plan_validation_receipt, event_list
    )
    if dict(supplied_projection) != rebuilt:
        raise StateReducerError(
            "E_V263_BUDGET_REPLAY_MISMATCH", "budget projection differs"
        )
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-budget-validation-receipt-v1",
        "projection_digest": rebuilt["projection_digest"],
        "task_exact_set_digest": rebuilt["task_exact_set_digest"],
        "compiled_plan_receipt_digest": rebuilt["compiled_plan_receipt_digest"],
        "task_plan_validation_receipt_digest": rebuilt[
            "task_plan_validation_receipt_digest"
        ],
        "event_count": rebuilt["event_count"],
        "last_event_sha256": rebuilt["last_event_sha256"],
        "validator": "scripts.v250.state_reducer.validate_budget_projection",
        "valid": True,
    }
    receipt["receipt_digest"] = _digest(receipt)
    return receipt


def completion_projection(
    *,
    development_task_states: Mapping[str, str] | None = None,
    runtime_task_states: Mapping[str, str] | None = None,
    release_task_states: Mapping[str, str] | None = None,
    development_denominator: str | None = None,
    git_scope_state: str | None = None,
    runtime_observation_state: str | None = None,
    business_validation_state: str | None = None,
    release_gate_state: str | None = None,
    internal_open_gap_count: int = 0,
    release_execution_state: str = "not_run",
    compiled_task_plan: Mapping[str, Any] | None = None,
    task_plan_validation_receipt: Mapping[str, Any] | None = None,
    state_events: Iterable[Mapping[str, Any]] | None = None,
    state_projection: Mapping[str, Any] | None = None,
    state_projection_validation_receipt: Mapping[str, Any] | None = None,
    budget_events: Iterable[Mapping[str, Any]] | None = None,
    budget_projection: Mapping[str, Any] | None = None,
    validation_receipts: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Revalidate receipts and project orthogonal completion facts.

    The original free-form parameters remain parseable only so older callers fail
    closed with an explicit compatibility projection.  They never authorize a
    completion axis.
    """

    authoritative_inputs = (
        compiled_task_plan,
        task_plan_validation_receipt,
        state_events,
        state_projection,
        state_projection_validation_receipt,
        budget_events,
        budget_projection,
        validation_receipts,
    )
    if not any(value is not None for value in authoritative_inputs):
        status_fields = {
            "development_denominator": development_denominator,
            "git_scope_state": git_scope_state,
            "runtime_observation_state": runtime_observation_state,
            "business_validation_state": business_validation_state,
            "release_gate_state": release_gate_state,
            "release_execution_state": release_execution_state,
        }
        for field, value in status_fields.items():
            if value is not None and value not in COMPLETION_STATUSES:
                raise StateReducerError(
                    "E_V263_COMPLETION_STATUS",
                    f"unknown completion status for {field}",
                )
        for field, states in (
            ("development_task_states", development_task_states),
            ("runtime_task_states", runtime_task_states),
            ("release_task_states", release_task_states),
        ):
            if states is not None and (
                not isinstance(states, Mapping)
                or any(
                    not isinstance(task_id, str)
                    or not task_id
                    or state not in TASK_PROJECTION_STATES
                    for task_id, state in states.items()
                )
            ):
                raise StateReducerError(
                    "E_V263_COMPLETION_STATUS", f"invalid task state in {field}"
                )
        if (
            not isinstance(internal_open_gap_count, int)
            or isinstance(internal_open_gap_count, bool)
            or internal_open_gap_count < 0
        ):
            raise StateReducerError(
                "E_V263_COMPLETION_STATUS",
                "internal_open_gap_count must be non-negative",
            )
        return {
            "authoritative": False,
            "authority": "unverified_compatibility",
            "engineering_complete": False,
            "runtime_complete": False,
            "business_validated": False,
            "release_ready": False,
            "release_published": False,
            "installation_current": False,
            "internal_open_gap_count": internal_open_gap_count,
        }

    if any(value is None for value in authoritative_inputs):
        raise StateReducerError(
            "E_V263_COMPLETION_INPUT",
            "authoritative completion requires plan, state, budget, and receipt replay inputs",
        )

    from scripts.v250.task_plan_compiler import (  # pylint: disable=import-outside-toplevel
        TaskPlanError,
        validate_compiled_task_plan,
    )

    try:
        expected_plan_validation = validate_compiled_task_plan(compiled_task_plan)
    except TaskPlanError as exc:
        raise StateReducerError(
            "E_V263_COMPLETION_PLAN", "compiled task plan is invalid"
        ) from exc
    if dict(task_plan_validation_receipt) != expected_plan_validation:
        raise StateReducerError(
            "E_V263_COMPLETION_PLAN", "task plan validation receipt differs"
        )

    event_list = list(state_events)
    budget_event_list = list(budget_events)
    receipt_list = list(validation_receipts)
    expected_bindings = state_projection.get("bindings")
    if not isinstance(expected_bindings, Mapping):
        raise StateReducerError(
            "E_V263_COMPLETION_STATE", "state projection bindings are missing"
        )
    if expected_bindings.get("task_exact_set_sha256") != compiled_task_plan.get(
        "task_exact_set_digest"
    ):
        raise StateReducerError(
            "E_V263_COMPLETION_STATE", "state projection exact-set binding differs"
        )
    rebuilt_state = reduce_state_events(
        event_list,
        expected_bindings=expected_bindings,
        validation_receipts=receipt_list,
        compiled_task_plan=compiled_task_plan,
        task_plan_validation_receipt=task_plan_validation_receipt,
    )
    if dict(state_projection) != rebuilt_state:
        raise StateReducerError(
            "E_V263_STATE_REPLAY_MISMATCH", "state projection differs"
        )
    expected_state_validation = validate_state_projection(
        event_list,
        expected_bindings=expected_bindings,
        supplied_projection=state_projection,
        validation_receipts=receipt_list,
        compiled_task_plan=compiled_task_plan,
        task_plan_validation_receipt=task_plan_validation_receipt,
    )
    if dict(state_projection_validation_receipt) != expected_state_validation:
        raise StateReducerError(
            "E_V263_COMPLETION_STATE_RECEIPT",
            "state projection validation receipt differs",
        )
    if rebuilt_state.get("validation_authority") != "authoritative":
        raise StateReducerError(
            "E_V263_COMPLETION_STATE", "state projection is not authoritative"
        )

    exact_task_ids = list(compiled_task_plan["task_ids"])
    observed_task_ids = list(rebuilt_state["axes"]["task"])
    if set(observed_task_ids) != set(exact_task_ids) or len(observed_task_ids) != len(
        exact_task_ids
    ):
        raise StateReducerError(
            "E_V263_COMPLETION_TASK_EXACT_SET",
            "state task IDs differ from the compiled exact set",
        )
    phase_sets = compiled_task_plan["phase_exact_sets"]
    if expected_plan_validation["phase_exact_task_ids"] != phase_sets:
        raise StateReducerError(
            "E_V263_COMPLETION_TASK_EXACT_SET", "phase exact task IDs differ"
        )
    phase_states = {
        phase: {
            task_id: rebuilt_state["axes"]["task"][task_id]
            for task_id in task_ids
        }
        for phase, task_ids in phase_sets.items()
    }

    rebuilt_budget = reduce_budget_events(
        compiled_task_plan, task_plan_validation_receipt, budget_event_list
    )
    if dict(budget_projection) != rebuilt_budget:
        raise StateReducerError(
            "E_V263_BUDGET_REPLAY_MISMATCH", "budget projection differs"
        )
    if set(rebuilt_budget["tasks"]) != set(exact_task_ids):
        raise StateReducerError(
            "E_V263_COMPLETION_TASK_EXACT_SET", "budget task IDs differ"
        )

    _, receipts_by_subject = _index_validation_receipts(
        receipt_list, expected_bindings=expected_bindings
    )

    def receipt_for(
        receipt_type: str, subject_id: str
    ) -> Mapping[str, Any] | None:
        receipt = receipts_by_subject.get((receipt_type, subject_id))
        return receipt if receipt is not None and receipt["status"] == "passed" else None

    plan_id = str(compiled_task_plan["plan_id"])
    denominator = receipt_for("development_denominator", "development")
    git_scope = receipt_for("git_scope", plan_id)
    runtime = receipt_for("runtime_observation", "runtime")
    business = receipt_for("business_validation", plan_id)
    release_gate = receipt_for("release_gate", "release")
    publication_candidates = [
        receipt
        for (receipt_type, _), receipt in receipts_by_subject.items()
        if receipt_type == "release_publication" and receipt["status"] == "passed"
    ]
    install_candidates = [
        receipt
        for (receipt_type, _), receipt in receipts_by_subject.items()
        if receipt_type == "installation_readback" and receipt["status"] == "passed"
    ]
    gap_audit = receipt_for("open_gap_audit", plan_id)

    if denominator is not None and denominator["observations"]["exact_task_ids"] != phase_sets[
        "development"
    ]:
        raise StateReducerError(
            "E_V263_COMPLETION_TASK_EXACT_SET",
            "development denominator exact task IDs differ",
        )
    if runtime is not None and runtime["observations"]["exact_task_ids"] != phase_sets[
        "runtime"
    ]:
        raise StateReducerError(
            "E_V263_COMPLETION_TASK_EXACT_SET",
            "runtime observation exact task IDs differ",
        )
    if release_gate is not None and release_gate["observations"]["exact_task_ids"] != phase_sets[
        "release"
    ]:
        raise StateReducerError(
            "E_V263_COMPLETION_TASK_EXACT_SET", "release gate exact task IDs differ"
        )
    for publication in publication_candidates:
        if publication["observations"]["observed_tag_target_sha256"] != expected_bindings[
            "source_sha256"
        ]:
            raise StateReducerError(
                "E_V263_COMPLETION_PUBLICATION",
                "publication tag target is not the bound source",
            )
    for installation in install_candidates:
        if installation["observations"]["observed_source_sha256"] != expected_bindings[
            "source_sha256"
        ]:
            raise StateReducerError(
                "E_V263_COMPLETION_INSTALLATION",
                "installation source is not the bound source",
            )

    open_gap_ids = (
        list(gap_audit["observations"]["open_gap_ids"])
        if gap_audit is not None
        else []
    )
    engineering = (
        _all_accepted(phase_states["development"])
        and denominator is not None
        and git_scope is not None
        and gap_audit is not None
        and not open_gap_ids
    )
    runtime_complete = _all_accepted(phase_states["runtime"]) and runtime is not None
    business_validated = business is not None
    release_ready = (
        _all_accepted(phase_states["release"]) and release_gate is not None
    )
    release_published = len(publication_candidates) == 1
    installation_current = len(install_candidates) == 1
    return {
        "authoritative": True,
        "authority": "receipt_replay",
        "engineering_complete": engineering,
        "runtime_complete": runtime_complete,
        "business_validated": business_validated,
        "release_ready": release_ready,
        "release_published": release_published,
        "installation_current": installation_current,
        "internal_open_gap_count": len(open_gap_ids),
        "phase_exact_task_ids": copy.deepcopy(phase_sets),
        "compiled_plan_receipt_digest": compiled_task_plan["receipt_digest"],
        "task_plan_validation_receipt_digest": task_plan_validation_receipt[
            "receipt_digest"
        ],
        "state_projection_digest": rebuilt_state["projection_sha256"],
        "state_projection_validation_receipt_digest": expected_state_validation[
            "receipt_digest"
        ],
        "budget_projection_digest": rebuilt_budget["projection_digest"],
        "validation_receipt_digests": sorted(
            receipt["receipt_digest"] for receipt in receipt_list
        ),
    }


__all__ = [
    "StateReducerError",
    "completion_projection",
    "make_budget_event",
    "make_state_event",
    "make_validation_receipt",
    "rebuild_projection",
    "reduce_budget_events",
    "reduce_state_events",
    "validate_budget_projection",
    "validate_state_projection",
    "validate_validation_receipt",
]
