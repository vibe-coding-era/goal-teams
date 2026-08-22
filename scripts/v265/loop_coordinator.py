"""Crash-reconcilable, project-local LOOP Review coordination for V2.65."""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.v265.canonical import (
    CanonicalValueError,
    canonical_json_bytes,
    canonical_sha256,
    exact_mapping,
    is_int,
    is_non_empty_string,
    is_sha256,
    parse_json_bytes,
    require_utc_timestamp,
    unique_string_list,
)
from scripts.v265.context_compiler import compile_review_capsule
from scripts.v265.loop_review import (
    LoopReviewError,
    ZERO_SHA256,
    _ExclusiveLock,
    _resolve_paths,
    _write_sidecar,
    append_loop_review,
    build_loop_review,
    inspect_loop_review,
    reconcile_loop_review,
    validate_round_review,
)


E_CAS = "E_V265_LOOP_COORDINATOR_CAS"
E_REQUIRED = "E_V265_LOOP_COORDINATOR_REVIEW_REQUIRED"
E_STATE = "E_V265_LOOP_COORDINATOR_STATE"
E_PATH = "E_V265_REVIEW_PATH"


class LoopCoordinatorError(ValueError):
    """A LOOP coordination transition cannot be made authoritative."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _error(code: str, message: str) -> LoopCoordinatorError:
    return LoopCoordinatorError(code, message)


DESCRIPTOR_FIELDS = frozenset(
    {
        "round_id",
        "project_id",
        "artifact_version",
        "skill_version",
        "loop_id",
        "loop_round",
        "task_exact_set_sha256",
        "graph_revision",
        "plan_revision",
        "source_revision",
        "started_at",
        "max_capsule_items",
        "max_capsule_bytes",
    }
)
STATE_FIELDS = frozenset(
    {
        "schema_version",
        "descriptor",
        "status",
        "pending_issue_key",
        "pending_evidence_refs",
        "pending_operation",
        "pending_review_id",
        "pending_review_sha256",
        "pending_capsule_sha256",
        "review_ids",
        "review_state_revision",
        "review_file_sha256",
        "next_sequence",
        "previous_review_sha256",
        "coordinator_revision",
        "capsule_relative_path",
        "capsule_sha256",
        "last_receipt_sha256",
        "state_sha256",
    }
)
RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "round_id",
        "loop_id",
        "loop_round",
        "coordinator_revision_before",
        "coordinator_revision_after",
        "review_state_revision",
        "review_file_sha256",
        "review_id",
        "pending_issue_key",
        "next_action_ready",
        "finalized",
        "capsule_relative_path",
        "capsule_sha256",
        "loop_decision",
        "receipt_sha256",
    }
)
PENDING_OPERATION_FIELDS = frozenset(
    {
        "operation",
        "coordinator_revision_before",
        "signed_review",
        "active_review_ids",
        "compiled_at",
        "capsule",
    }
)
STATUSES = frozenset(
    {"active", "problem_pending", "committing_problem", "committing_finalize", "finalized"}
)


def _exact(value: object, fields: frozenset[str], label: str) -> dict[str, Any]:
    return exact_mapping(
        value,
        fields,
        error=lambda message: _error(E_STATE, message),
        label=label,
    )


def _strings(value: object, label: str, *, non_empty: bool = False) -> list[str]:
    return unique_string_list(
        value,
        error=lambda message: _error(E_STATE, message),
        label=label,
        non_empty=non_empty,
        sort_output=False,
    )


def _descriptor(value: object) -> dict[str, Any]:
    result = _exact(value, DESCRIPTOR_FIELDS, "round descriptor")
    for field in (
        "round_id",
        "project_id",
        "artifact_version",
        "skill_version",
        "loop_id",
        "source_revision",
    ):
        if not is_non_empty_string(result[field]):
            raise _error(E_STATE, f"descriptor {field} must be a non-empty string")
    for field in (
        "loop_round",
        "graph_revision",
        "plan_revision",
        "max_capsule_items",
        "max_capsule_bytes",
    ):
        if not is_int(result[field], minimum=1):
            raise _error(E_STATE, f"descriptor {field} must be positive")
    if not is_sha256(result["task_exact_set_sha256"]):
        raise _error(E_STATE, "descriptor TaskExactSet digest is invalid")
    result["started_at"] = require_utc_timestamp(
        result["started_at"],
        error=lambda message: _error(E_STATE, message),
        label="descriptor.started_at",
    )
    return result


def _pending_operation(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    result = _exact(value, PENDING_OPERATION_FIELDS, "pending operation")
    if result["operation"] not in {"record_problem_review", "finalize_round"}:
        raise _error(E_STATE, "pending operation kind is invalid")
    if not is_int(result["coordinator_revision_before"], minimum=0):
        raise _error(E_STATE, "pending operation revision is invalid")
    if not isinstance(result["signed_review"], Mapping):
        raise _error(E_STATE, "pending signed Review is absent")
    result["signed_review"] = copy.deepcopy(dict(result["signed_review"]))
    result["active_review_ids"] = _strings(
        result["active_review_ids"], "pending active_review_ids"
    )
    if result["operation"] == "finalize_round":
        result["compiled_at"] = require_utc_timestamp(
            result["compiled_at"],
            error=lambda message: _error(E_STATE, message),
            label="pending compiled_at",
        )
        if not isinstance(result["capsule"], Mapping):
            raise _error(E_STATE, "pending Capsule is absent")
        result["capsule"] = copy.deepcopy(dict(result["capsule"]))
    elif result["compiled_at"] is not None or result["capsule"] is not None:
        raise _error(E_STATE, "problem Review cannot carry a Capsule")
    return result


def _validated_state(value: object) -> dict[str, Any]:
    state = _exact(value, STATE_FIELDS, "Coordinator state")
    if state["schema_version"] != "goal-teams-loop-coordinator-state-v2.65":
        raise _error(E_STATE, "Coordinator state schema differs")
    state["descriptor"] = _descriptor(state["descriptor"])
    if state["status"] not in STATUSES:
        raise _error(E_STATE, "Coordinator status is invalid")
    for field in (
        "review_state_revision",
        "next_sequence",
        "coordinator_revision",
    ):
        minimum = 1 if field in {"next_sequence", "coordinator_revision"} else 0
        if not is_int(state[field], minimum=minimum):
            raise _error(E_STATE, f"Coordinator {field} is invalid")
    state["pending_evidence_refs"] = _strings(
        state["pending_evidence_refs"], "pending_evidence_refs"
    )
    state["review_ids"] = _strings(state["review_ids"], "review_ids")
    state["pending_operation"] = _pending_operation(state["pending_operation"])
    for field in (
        "review_file_sha256",
        "previous_review_sha256",
        "last_receipt_sha256",
        "state_sha256",
    ):
        if not is_sha256(state[field]):
            raise _error(E_STATE, f"Coordinator {field} is invalid")
    for field in ("pending_review_sha256", "pending_capsule_sha256", "capsule_sha256"):
        if state[field] is not None and not is_sha256(state[field]):
            raise _error(E_STATE, f"Coordinator {field} is invalid")
    for field in ("pending_issue_key", "pending_review_id", "capsule_relative_path"):
        if state[field] is not None and not is_non_empty_string(state[field]):
            raise _error(E_STATE, f"Coordinator {field} is invalid")
    expected = canonical_sha256(
        {key: item for key, item in state.items() if key != "state_sha256"}
    )
    if state["state_sha256"] != expected:
        raise _error(E_STATE, "Coordinator state self-digest differs")
    return state


def _state_bytes(state: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(state)


def _safe_paths(
    project_root: Path | str,
    relative_path: str,
    *,
    create_parent: bool,
) -> tuple[Path, str, Path, Path, Path]:
    try:
        root, target, _review_state, _review_lock, normalized = _resolve_paths(
            project_root, relative_path, create_parent=create_parent
        )
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc
    coordinator = Path(f"{target}.coordinator.json")
    lock = Path(f"{target}.coordinator.lock")
    capsule = Path(f"{target}.capsule.json")
    for path in (coordinator, lock, capsule):
        if path.is_symlink():
            raise _error(E_PATH, "Coordinator output crosses a symlink")
        if path.exists() and not path.is_file():
            if path == capsule:
                continue
            raise _error(E_PATH, "Coordinator output is not a regular file")
    return root, normalized, coordinator, lock, capsule


def _capsule_location(
    legacy_path: Path,
    relative_path: str,
    descriptor: Mapping[str, Any],
) -> tuple[Path, str]:
    if descriptor["loop_round"] == 1:
        return legacy_path, f"{relative_path}.capsule.json"
    round_id_sha256 = hashlib.sha256(
        descriptor["round_id"].encode("utf-8")
    ).hexdigest()
    filename = f"{legacy_path.name[:-5]}.{round_id_sha256}.json"
    return legacy_path.with_name(filename), (
        f"{relative_path}.capsule.{round_id_sha256}.json"
    )


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise _error(E_PATH, "Coordinator state path is unsafe")
    try:
        raw = path.read_bytes()
        parsed = parse_json_bytes(raw)
        state = _validated_state(parsed)
    except LoopCoordinatorError:
        raise
    except (OSError, CanonicalValueError, ValueError) as exc:
        raise _error(E_STATE, "Coordinator state cannot be read") from exc
    if raw != _state_bytes(state):
        raise _error(E_STATE, "Coordinator state is not canonical JSON")
    return state


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    try:
        _write_sidecar(path, state)
    except LoopReviewError as exc:
        raise _error(E_STATE, exc.message) from exc


def _inspection(project_root: Path | str, relative_path: str) -> dict[str, Any]:
    try:
        return inspect_loop_review(project_root, relative_path)
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc


def _receipt(
    *,
    operation: str,
    descriptor: Mapping[str, Any],
    before: int,
    after: int,
    inspection: Mapping[str, Any],
    review_id: str | None,
    pending_issue_key: str | None,
    next_action_ready: bool,
    finalized: bool,
    capsule_relative_path: str | None,
    capsule_sha256: str | None,
    loop_decision: str | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": "goal-teams-loop-coordinator-receipt-v2.65",
        "operation": operation,
        "round_id": descriptor["round_id"],
        "loop_id": descriptor["loop_id"],
        "loop_round": descriptor["loop_round"],
        "coordinator_revision_before": before,
        "coordinator_revision_after": after,
        "review_state_revision": inspection["review_state_revision"],
        "review_file_sha256": inspection["review_file_sha256"],
        "review_id": review_id,
        "pending_issue_key": pending_issue_key,
        "next_action_ready": next_action_ready,
        "finalized": finalized,
        "capsule_relative_path": capsule_relative_path,
        "capsule_sha256": capsule_sha256,
        "loop_decision": loop_decision,
    }
    value["receipt_sha256"] = canonical_sha256(value)
    if set(value) != set(RECEIPT_FIELDS):
        raise _error(E_STATE, "Coordinator Receipt field set differs")
    return value


def _commit_state(path: Path, state: dict[str, Any], receipt: Mapping[str, Any]) -> None:
    state["last_receipt_sha256"] = receipt["receipt_sha256"]
    state["state_sha256"] = canonical_sha256(
        {key: item for key, item in state.items() if key != "state_sha256"}
    )
    _write_state(path, state)


def _assert_revision(state: Mapping[str, Any] | None, expected: int) -> int:
    current = 0 if state is None else int(state["coordinator_revision"])
    if not is_int(expected, minimum=0) or expected != current:
        raise _error(E_CAS, "Coordinator revision differs")
    return current


def _assert_review_identity(
    signed: Mapping[str, Any], descriptor: Mapping[str, Any]
) -> None:
    pairs = {
        "project_id": descriptor["project_id"],
        "artifact_version": descriptor["artifact_version"],
        "skill_version": descriptor["skill_version"],
        "loop_id": descriptor["loop_id"],
        "loop_round": descriptor["loop_round"],
        "task_exact_set_sha256": descriptor["task_exact_set_sha256"],
        "graph_revision": descriptor["graph_revision"],
        "plan_revision": descriptor["plan_revision"],
        "source_revision": descriptor["source_revision"],
    }
    if any(signed.get(field) != value for field, value in pairs.items()):
        raise _error(E_STATE, "Review identity differs from active round")


def _signed_review(
    unsigned: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    trigger: str,
) -> dict[str, Any]:
    if not isinstance(unsigned, Mapping):
        raise _error(E_STATE, "unsigned Review must be an object")
    candidate = copy.deepcopy(dict(unsigned))
    if (
        candidate.get("sequence") != state["next_sequence"]
        or candidate.get("previous_review_sha256") != state["previous_review_sha256"]
        or candidate.get("trigger") != trigger
    ):
        raise _error(E_CAS, "Review sequence, previous digest, or trigger differs")
    try:
        signed = build_loop_review(candidate)
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc
    _assert_review_identity(signed, state["descriptor"])
    return signed


def _problem_review_with_flagged_evidence(
    unsigned: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(unsigned, Mapping):
        raise _error(E_STATE, "unsigned Review must be an object")
    candidate = copy.deepcopy(dict(unsigned))
    evidence_refs = candidate.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not all(
        is_non_empty_string(item) for item in evidence_refs
    ):
        raise _error(E_STATE, "unsigned problem Review evidence_refs are invalid")
    candidate["evidence_refs"] = sorted(
        set([*evidence_refs, *state["pending_evidence_refs"]])
    )
    return candidate


def _deduplicate_problem(
    coordinator_path: Path,
    state: Mapping[str, Any],
    inspection: Mapping[str, Any],
    existing_review: Mapping[str, Any],
    *,
    before: int,
) -> dict[str, Any]:
    after = before + 1
    next_state = copy.deepcopy(dict(state))
    next_state["status"] = "active"
    next_state["pending_issue_key"] = None
    next_state["pending_evidence_refs"] = []
    next_state["pending_operation"] = None
    next_state["pending_review_id"] = None
    next_state["pending_review_sha256"] = None
    next_state["pending_capsule_sha256"] = None
    next_state["coordinator_revision"] = after
    receipt = _receipt(
        operation="record_problem_review",
        descriptor=state["descriptor"],
        before=before,
        after=after,
        inspection=inspection,
        review_id=existing_review["review_id"],
        pending_issue_key=None,
        next_action_ready=True,
        finalized=False,
        capsule_relative_path=None,
        capsule_sha256=None,
        loop_decision=None,
    )
    _commit_state(coordinator_path, next_state, receipt)
    return receipt


def _round_reviews(
    inspection: Mapping[str, Any], descriptor: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(review)
        for review in inspection["reviews"]
        if review["loop_id"] == descriptor["loop_id"]
        and review["loop_round"] == descriptor["loop_round"]
    ]


def _append_or_verify(
    project_root: Path | str,
    relative_path: str,
    signed: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        inspection = _inspection(project_root, relative_path)
    except LoopCoordinatorError as exc:
        if exc.code != "E_V265_REVIEW_STATE_DRIFT":
            raise
        # append_loop_review durably fsyncs the Markdown frame before replacing
        # its sidecar.  A process loss in that window leaves exactly one unseen
        # frame which the Review journal can validate and project.  Reconcile it
        # before comparing the stored Coordinator intent; malformed, unrelated,
        # or multi-frame drift still fails closed in the Review reconciler or in
        # the exact review_id/review_sha256 checks below.
        try:
            reconcile_loop_review(project_root, relative_path)
        except LoopReviewError as review_exc:
            raise _error(review_exc.code, review_exc.message) from review_exc
        inspection = _inspection(project_root, relative_path)
    matches = [
        review
        for review in inspection["reviews"]
        if review["review_id"] == signed["review_id"]
    ]
    if matches:
        if len(matches) != 1 or matches[0]["review_sha256"] != signed["review_sha256"]:
            raise _error(E_STATE, "existing Review identity conflicts with pending intent")
        return inspection
    try:
        append_loop_review(
            project_root,
            relative_path,
            signed,
            expected_previous_file_sha256=inspection["review_file_sha256"],
            expected_state_revision=inspection["review_state_revision"],
        )
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc
    return _inspection(project_root, relative_path)


def _write_capsule(path: Path, capsule: Mapping[str, Any]) -> None:
    raw = canonical_json_bytes(capsule)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise _error(E_PATH, "Capsule output path is unsafe")
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise _error(E_PATH, "Capsule cannot be read") from exc
        if existing != raw:
            raise _error(E_STATE, "existing Capsule differs from pending intent")
        return
    try:
        _write_sidecar(path, capsule)
    except LoopReviewError as exc:
        raise _error(E_PATH, exc.message) from exc


def _intent_state(
    state: Mapping[str, Any],
    *,
    operation: str,
    signed: Mapping[str, Any],
    active_review_ids: Sequence[str],
    compiled_at: str | None,
    capsule: Mapping[str, Any] | None,
) -> dict[str, Any]:
    next_state = copy.deepcopy(dict(state))
    next_state["status"] = (
        "committing_problem" if operation == "record_problem_review" else "committing_finalize"
    )
    next_state["pending_operation"] = {
        "operation": operation,
        "coordinator_revision_before": state["coordinator_revision"],
        "signed_review": copy.deepcopy(dict(signed)),
        "active_review_ids": list(active_review_ids),
        "compiled_at": compiled_at,
        "capsule": None if capsule is None else copy.deepcopy(dict(capsule)),
    }
    next_state["pending_review_id"] = signed["review_id"]
    next_state["pending_review_sha256"] = signed["review_sha256"]
    next_state["pending_capsule_sha256"] = (
        None if capsule is None else capsule["capsule_sha256"]
    )
    next_state["coordinator_revision"] = state["coordinator_revision"] + 1
    next_state["state_sha256"] = canonical_sha256(
        {key: item for key, item in next_state.items() if key != "state_sha256"}
    )
    return next_state


def _complete_pending(
    project_root: Path | str,
    relative_path: str,
    coordinator_path: Path,
    capsule_path: Path,
    state: Mapping[str, Any],
    *,
    receipt_operation: str,
    receipt_before: int,
    final_revision: int,
) -> dict[str, Any]:
    pending = _pending_operation(state["pending_operation"])
    if pending is None:
        raise _error(E_STATE, "Coordinator pending operation is absent")
    signed = pending["signed_review"]
    inspection = _append_or_verify(project_root, relative_path, signed)
    descriptor = state["descriptor"]
    operation = pending["operation"]
    capsule: dict[str, Any] | None = pending["capsule"]
    capsule_relative_path: str | None = None
    if operation == "finalize_round":
        assert capsule is not None
        capsule_path, capsule_relative_path = _capsule_location(
            capsule_path, relative_path, descriptor
        )
        _write_capsule(capsule_path, capsule)
        try:
            validate_round_review(
                _round_reviews(inspection, descriptor),
                loop_id=descriptor["loop_id"],
                loop_round=descriptor["loop_round"],
            )
        except LoopReviewError as exc:
            raise _error(exc.code, exc.message) from exc

    final_state = copy.deepcopy(dict(state))
    final_state["status"] = "finalized" if operation == "finalize_round" else "active"
    final_state["pending_issue_key"] = None
    final_state["pending_evidence_refs"] = []
    final_state["pending_operation"] = None
    final_state["pending_review_id"] = None
    final_state["pending_review_sha256"] = None
    final_state["pending_capsule_sha256"] = None
    final_state["review_ids"] = [
        review["review_id"] for review in _round_reviews(inspection, descriptor)
    ]
    final_state["review_state_revision"] = inspection["review_state_revision"]
    final_state["review_file_sha256"] = inspection["review_file_sha256"]
    final_state["next_sequence"] = inspection["review_state_revision"] + 1
    final_state["previous_review_sha256"] = inspection["last_review_sha256"]
    final_state["coordinator_revision"] = final_revision
    final_state["capsule_relative_path"] = capsule_relative_path
    final_state["capsule_sha256"] = None if capsule is None else capsule["capsule_sha256"]
    loop_decision = (
        signed["loop_result"]["decision"] if operation == "finalize_round" else None
    )
    receipt = _receipt(
        operation=receipt_operation,
        descriptor=descriptor,
        before=receipt_before,
        after=final_revision,
        inspection=inspection,
        review_id=signed["review_id"],
        pending_issue_key=None,
        next_action_ready=operation == "record_problem_review",
        finalized=operation == "finalize_round",
        capsule_relative_path=final_state["capsule_relative_path"],
        capsule_sha256=final_state["capsule_sha256"],
        loop_decision=loop_decision,
    )
    _commit_state(coordinator_path, final_state, receipt)
    return receipt


def begin_round(
    project_root: Path | str,
    relative_path: str,
    descriptor: Mapping[str, Any],
    *,
    expected_coordinator_revision: int,
) -> dict[str, Any]:
    root, normalized, coordinator, lock, _capsule = _safe_paths(
        project_root, relative_path, create_parent=True
    )
    desc = _descriptor(descriptor)
    try:
        with _ExclusiveLock(lock):
            previous = _read_state(coordinator)
            before = _assert_revision(previous, expected_coordinator_revision)
            if previous is not None and previous["status"] != "finalized":
                raise _error(E_STATE, "another LOOP round is still active")
            inspection = _inspection(root, normalized)
            if inspection["exists"] and (
                inspection["project_id"] != desc["project_id"]
                or inspection["artifact_version"] != desc["artifact_version"]
                or inspection["skill_version"] != desc["skill_version"]
            ):
                raise _error(E_STATE, "Review document identity differs from round")
            after = before + 1
            state: dict[str, Any] = {
                "schema_version": "goal-teams-loop-coordinator-state-v2.65",
                "descriptor": desc,
                "status": "active",
                "pending_issue_key": None,
                "pending_evidence_refs": [],
                "pending_operation": None,
                "pending_review_id": None,
                "pending_review_sha256": None,
                "pending_capsule_sha256": None,
                "review_ids": [],
                "review_state_revision": inspection["review_state_revision"],
                "review_file_sha256": inspection["review_file_sha256"],
                "next_sequence": inspection["review_state_revision"] + 1,
                "previous_review_sha256": inspection["last_review_sha256"],
                "coordinator_revision": after,
                "capsule_relative_path": None,
                "capsule_sha256": None,
                "last_receipt_sha256": ZERO_SHA256,
                "state_sha256": ZERO_SHA256,
            }
            receipt = _receipt(
                operation="begin_round",
                descriptor=desc,
                before=before,
                after=after,
                inspection=inspection,
                review_id=None,
                pending_issue_key=None,
                next_action_ready=True,
                finalized=False,
                capsule_relative_path=None,
                capsule_sha256=None,
                loop_decision=None,
            )
            _commit_state(coordinator, state, receipt)
            return receipt
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc


def flag_problem(
    project_root: Path | str,
    relative_path: str,
    *,
    issue_key: str,
    evidence_refs: Sequence[str],
    occurred_at: str,
    expected_coordinator_revision: int,
) -> dict[str, Any]:
    root, normalized, coordinator, lock, _capsule = _safe_paths(
        project_root, relative_path, create_parent=False
    )
    if not is_non_empty_string(issue_key):
        raise _error(E_STATE, "issue_key must be non-empty")
    refs = _strings(list(evidence_refs), "problem evidence_refs", non_empty=True)
    occurred = require_utc_timestamp(
        occurred_at,
        error=lambda message: _error(E_STATE, message),
        label="problem occurred_at",
    )
    try:
        with _ExclusiveLock(lock):
            state = _read_state(coordinator)
            if state is None:
                raise _error(E_STATE, "Coordinator round is absent")
            before = _assert_revision(state, expected_coordinator_revision)
            if state["status"] != "active":
                raise _error(E_STATE, "Coordinator is not ready for a problem")
            inspection = _inspection(root, normalized)
            if (
                inspection["review_state_revision"] != state["review_state_revision"]
                or inspection["review_file_sha256"] != state["review_file_sha256"]
            ):
                raise _error(E_CAS, "Review state drifted before problem flag")
            after = before + 1
            next_state = copy.deepcopy(state)
            next_state["status"] = "problem_pending"
            next_state["pending_issue_key"] = issue_key
            next_state["pending_evidence_refs"] = refs
            # The factual timestamp is validated at the API boundary; the exact
            # coordinator state reserves pending_operation for cross-file writes.
            next_state["pending_operation"] = None
            next_state["coordinator_revision"] = after
            receipt = _receipt(
                operation="flag_problem",
                descriptor=state["descriptor"],
                before=before,
                after=after,
                inspection=inspection,
                review_id=None,
                pending_issue_key=issue_key,
                next_action_ready=False,
                finalized=False,
                capsule_relative_path=None,
                capsule_sha256=None,
                loop_decision=None,
            )
            _commit_state(coordinator, next_state, receipt)
            return receipt
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc


def record_problem_review(
    project_root: Path | str,
    relative_path: str,
    unsigned_review: Mapping[str, Any],
    *,
    expected_coordinator_revision: int,
) -> dict[str, Any]:
    root, normalized, coordinator, lock, capsule_path = _safe_paths(
        project_root, relative_path, create_parent=False
    )
    try:
        with _ExclusiveLock(lock):
            state = _read_state(coordinator)
            if state is None:
                raise _error(E_STATE, "Coordinator round is absent")
            before = _assert_revision(state, expected_coordinator_revision)
            if state["status"] == "problem_pending":
                pass
            elif state["status"].startswith("committing_"):
                raise _error(E_STATE, "pending Coordinator intent requires reconcile_round")
            else:
                raise _error(E_REQUIRED, "no problem Review is currently required")
            candidate = _problem_review_with_flagged_evidence(unsigned_review, state)
            signed = _signed_review(candidate, state, trigger="problem_detected")
            if signed["issue_key"] != state["pending_issue_key"]:
                raise _error(E_REQUIRED, "problem Review issue_key differs")
            inspection = _inspection(root, normalized)
            if (
                inspection["review_state_revision"] != state["review_state_revision"]
                or inspection["review_file_sha256"] != state["review_file_sha256"]
            ):
                raise _error(E_CAS, "Review state drifted before problem Review")
            duplicates = [
                review
                for review in inspection["reviews"]
                if review["issue_fingerprint"] == signed["issue_fingerprint"]
            ]
            if len(duplicates) > 1:
                raise _error(E_STATE, "duplicate Review fingerprint is ambiguous")
            if duplicates:
                return _deduplicate_problem(
                    coordinator,
                    state,
                    inspection,
                    duplicates[0],
                    before=before,
                )
            intent = _intent_state(
                state,
                operation="record_problem_review",
                signed=signed,
                active_review_ids=[],
                compiled_at=None,
                capsule=None,
            )
            _write_state(coordinator, intent)
            return _complete_pending(
                root,
                normalized,
                coordinator,
                capsule_path,
                intent,
                receipt_operation="record_problem_review",
                receipt_before=before,
                final_revision=intent["coordinator_revision"],
            )
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc


def finalize_round(
    project_root: Path | str,
    relative_path: str,
    unsigned_review: Mapping[str, Any],
    *,
    active_review_ids: Sequence[str],
    compiled_at: str,
    expected_coordinator_revision: int,
) -> dict[str, Any]:
    root, normalized, coordinator, lock, capsule_path = _safe_paths(
        project_root, relative_path, create_parent=False
    )
    try:
        with _ExclusiveLock(lock):
            state = _read_state(coordinator)
            if state is None:
                raise _error(E_STATE, "Coordinator round is absent")
            before = _assert_revision(state, expected_coordinator_revision)
            if state["status"] == "problem_pending":
                raise _error(E_REQUIRED, "problem Review must be appended before finalization")
            if state["status"] != "active":
                raise _error(E_STATE, "Coordinator round cannot be finalized")
            signed = _signed_review(unsigned_review, state, trigger="loop_end")
            inspection = _inspection(root, normalized)
            if (
                inspection["review_state_revision"] != state["review_state_revision"]
                or inspection["review_file_sha256"] != state["review_file_sha256"]
            ):
                raise _error(E_CAS, "Review state drifted before finalization")
            selected_ids = _strings(
                list(active_review_ids), "active_review_ids", non_empty=True
            )
            all_reviews = [*inspection["reviews"], signed]
            capsule = compile_review_capsule(
                all_reviews,
                capsule_id=f"CAPSULE-{state['descriptor']['round_id']}",
                active_review_ids=selected_ids,
                max_items=state["descriptor"]["max_capsule_items"],
                max_bytes=state["descriptor"]["max_capsule_bytes"],
                compiled_at=compiled_at,
            )
            intent = _intent_state(
                state,
                operation="finalize_round",
                signed=signed,
                active_review_ids=selected_ids,
                compiled_at=compiled_at,
                capsule=capsule,
            )
            _write_state(coordinator, intent)
            return _complete_pending(
                root,
                normalized,
                coordinator,
                capsule_path,
                intent,
                receipt_operation="finalize_round",
                receipt_before=before,
                final_revision=intent["coordinator_revision"],
            )
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc


def reconcile_round(
    project_root: Path | str,
    relative_path: str,
    *,
    expected_coordinator_revision: int,
) -> dict[str, Any]:
    root, normalized, coordinator, lock, capsule_path = _safe_paths(
        project_root, relative_path, create_parent=False
    )
    try:
        with _ExclusiveLock(lock):
            state = _read_state(coordinator)
            if state is None:
                raise _error(E_STATE, "Coordinator round is absent")
            before = _assert_revision(state, expected_coordinator_revision)
            if state["status"] not in {"committing_problem", "committing_finalize"}:
                raise _error(E_STATE, "Coordinator has no recoverable intent")
            return _complete_pending(
                root,
                normalized,
                coordinator,
                capsule_path,
                state,
                receipt_operation="reconcile_round",
                receipt_before=before,
                final_revision=before + 1,
            )
    except LoopReviewError as exc:
        raise _error(exc.code, exc.message) from exc


__all__ = [
    "LoopCoordinatorError",
    "begin_round",
    "finalize_round",
    "flag_problem",
    "reconcile_round",
    "record_problem_review",
]
