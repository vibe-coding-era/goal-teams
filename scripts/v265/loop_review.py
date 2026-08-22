"""Typed, append-only proactive LOOP reviews for Goal Teams V2.65.

The module writes only beneath an explicitly supplied user-project root.  A
review is a signed candidate/observation record, not Task state, authority, or
an instruction to modify a Prompt, Skill, Graph, or external system.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

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
    self_digest,
    unique_string_list,
)


class LoopReviewError(ValueError):
    """A Review or its append-only ledger violates the V2.65 contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


E_REQUIRED = "E_V265_REVIEW_REQUIRED"
E_SCHEMA = "E_V265_REVIEW_SCHEMA"
E_TRIGGER = "E_V265_REVIEW_TRIGGER"
E_EVIDENCE = "E_V265_REVIEW_EVIDENCE"
E_CANDIDATE = "E_V265_REVIEW_CANDIDATE"
E_DUPLICATE_LOOP_END = "E_V265_REVIEW_DUPLICATE_LOOP_END"
E_DUPLICATE_ISSUE = "E_V265_REVIEW_DUPLICATE_ISSUE"
E_FINGERPRINT = "E_V265_REVIEW_FINGERPRINT"
E_APPEND_CAS = "E_V265_REVIEW_APPEND_CAS"
E_STATE_DRIFT = "E_V265_REVIEW_STATE_DRIFT"
E_PATH = "E_V265_REVIEW_PATH"

ZERO_SHA256 = "0" * 64

UNSIGNED_REVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "review_id",
        "trigger",
        "project_id",
        "artifact_version",
        "skill_version",
        "loop_id",
        "loop_round",
        "sequence",
        "occurred_at",
        "graph_revision",
        "plan_revision",
        "task_exact_set_sha256",
        "source_revision",
        "task_refs",
        "evidence_refs",
        "issue_key",
        "loop_result",
        "observed_facts",
        "assumptions",
        "uncertainty",
        "retained_practices",
        "root_cause_primary",
        "root_cause_secondary",
        "dimensions",
        "candidate",
        "review_outcome",
        "status",
        "previous_review_sha256",
    }
)
SIGNED_REVIEW_FIELDS = UNSIGNED_REVIEW_FIELDS | frozenset(
    {"issue_fingerprint", "review_sha256"}
)
LOOP_RESULT_FIELDS = frozenset(
    {
        "decision",
        "achieved",
        "blocked_items",
        "failed_items",
        "not_run_items",
        "open_gaps",
    }
)
DIMENSION_FIELDS = frozenset(
    {
        "state",
        "finding",
        "evidence_refs",
        "improvement",
        "expected_benefit",
        "validation_method",
        "risk",
    }
)
CANDIDATE_FIELDS = frozenset(
    {
        "candidate_id",
        "consumer_refs",
        "scope_allowlist",
        "risk",
        "budget_wu",
        "validation_plan",
        "rollback_condition",
        "required_authorization",
    }
)
STATE_FIELDS = frozenset(
    {
        "schema_version",
        "revision",
        "file_sha256",
        "last_review_sha256",
        "review_count",
        "loop_end_keys",
        "issue_fingerprints",
        "header_sha256",
        "state_sha256",
    }
)

DIMENSION_NAMES = (
    "prompt",
    "context",
    "skill",
    "graph",
    "materials",
    "harness",
    "evidence",
    "members",
    "tools",
    "workflow",
    "runtime",
    "cost",
)
DIMENSION_NAME_SET = frozenset(DIMENSION_NAMES)
ROOT_CAUSES = frozenset(
    {
        "graph_contract",
        "route_or_edge",
        "prompt",
        "context",
        "skill",
        "capability_or_permission",
        "scheduler",
        "runtime_or_recovery",
        "harness_or_oracle",
        "evidence",
        "requirement",
        "member_coordination",
        "external_dependency",
        "unknown",
    }
)
REVIEW_OUTCOMES = frozenset(
    {
        "no_change",
        "observed_only",
        "backlog_candidate",
        "experiment_candidate",
        "next_loop_candidate",
        "skill_improvement_candidate",
        "required_fix",
        "new_scope_required",
        "blocked",
        "rejected",
    }
)
CANDIDATE_OUTCOMES = frozenset(
    {
        "backlog_candidate",
        "experiment_candidate",
        "next_loop_candidate",
        "skill_improvement_candidate",
        "required_fix",
        "new_scope_required",
    }
)
STATUSES = frozenset(
    {"open", "candidate_only", "rejected", "blocked", "closed", "review_incomplete"}
)
TRIGGERS = frozenset({"loop_end", "problem_detected", "user_correction"})
DECISIONS = frozenset({"continue", "replan", "stop"})
DIMENSION_STATES = frozenset({"no_finding", "observed", "candidate"})
PLACEHOLDER_ISSUES = frozenset(
    {"", "unknown", "n/a", "na", "none", "null", "todo", "tbd", "placeholder"}
)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")

FRAME_BEGIN_PREFIX = b"<!-- goal-teams-loop-review-begin:"
FRAME_END_PREFIX = b"<!-- goal-teams-loop-review-end:"
FRAME_COMMENT_SUFFIX = b" -->\n"
SIGNED_PAYLOAD_MARKER = b"### Signed review payload\n\n```json\n"


def _error(code: str, message: str) -> LoopReviewError:
    return LoopReviewError(code, message)


def _exact(
    value: object,
    fields: frozenset[str],
    label: str,
    *,
    code: str = E_SCHEMA,
) -> dict[str, Any]:
    return exact_mapping(
        value,
        fields,
        error=lambda message: _error(code, message),
        label=label,
    )


def _strings(
    value: object,
    label: str,
    *,
    non_empty: bool = False,
    set_like: bool = False,
    code: str = E_SCHEMA,
) -> list[str]:
    result = unique_string_list(
        value,
        error=lambda message: _error(code, message),
        label=label,
        non_empty=non_empty,
        sort_output=False,
    )
    if set_like and result != sorted(result):
        raise _error(code, f"{label} must be in lexical order")
    return result


def _one_line(
    value: object,
    label: str,
    *,
    identifier: bool = False,
    code: str = E_SCHEMA,
) -> str:
    if not is_non_empty_string(value) or not isinstance(value, str):
        raise _error(code, f"{label} must be a non-empty string")
    if value != value.strip() or "\r" in value or "\n" in value:
        raise _error(code, f"{label} must be a trimmed single-line string")
    if identifier and not ID_RE.fullmatch(value):
        raise _error(code, f"{label} is not a canonical identifier")
    return value


def _optional_prose(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not is_non_empty_string(value) or not isinstance(value, str):
        raise _error(E_SCHEMA, f"{label} must be null or a non-empty string")
    return value


def _validate_dimension(value: object, name: str) -> dict[str, Any]:
    dimension = _exact(value, DIMENSION_FIELDS, f"dimensions.{name}")
    state = dimension["state"]
    if state not in DIMENSION_STATES:
        raise _error(E_SCHEMA, f"dimensions.{name}.state is invalid")
    evidence_refs = _strings(
        dimension["evidence_refs"],
        f"dimensions.{name}.evidence_refs",
    )
    prose_fields = (
        "finding",
        "improvement",
        "expected_benefit",
        "validation_method",
        "risk",
    )
    for field in prose_fields:
        dimension[field] = _optional_prose(
            dimension[field], f"dimensions.{name}.{field}"
        )

    if state == "no_finding":
        if evidence_refs or any(dimension[field] is not None for field in prose_fields):
            raise _error(
                E_SCHEMA,
                f"dimensions.{name} no_finding must not carry findings or Evidence",
            )
    elif state == "observed":
        if dimension["finding"] is None or not evidence_refs:
            raise _error(
                E_EVIDENCE,
                f"dimensions.{name} observed state requires a finding and Evidence",
            )
    else:
        if not evidence_refs or any(dimension[field] is None for field in prose_fields):
            raise _error(
                E_CANDIDATE,
                f"dimensions.{name} candidate state requires every field",
            )
    dimension["evidence_refs"] = evidence_refs
    return dimension


def _validate_candidate(value: object) -> dict[str, Any]:
    candidate = _exact(value, CANDIDATE_FIELDS, "candidate")
    candidate["candidate_id"] = _one_line(
        candidate["candidate_id"], "candidate.candidate_id", identifier=True
    )
    candidate["consumer_refs"] = _strings(
        candidate["consumer_refs"],
        "candidate.consumer_refs",
        set_like=True,
    )
    candidate["scope_allowlist"] = _strings(
        candidate["scope_allowlist"],
        "candidate.scope_allowlist",
        set_like=True,
    )
    for field in (
        "risk",
        "validation_plan",
        "rollback_condition",
        "required_authorization",
    ):
        candidate[field] = _one_line(candidate[field], f"candidate.{field}")
    if not is_int(candidate["budget_wu"], minimum=1):
        raise _error(E_SCHEMA, "candidate.budget_wu must be a positive integer")
    if candidate["required_authorization"].strip().lower() in {
        "none",
        "automatic",
        "auto_apply",
        "apply_now",
    }:
        raise _error(E_CANDIDATE, "candidate cannot authorize its own application")
    return candidate


def _normalize_issue_key(value: object) -> str:
    issue = _one_line(value, "issue_key")
    normalized = " ".join(issue.lower().split())
    if normalized in PLACEHOLDER_ISSUES:
        raise _error(E_TRIGGER, "issue_key must identify a material non-placeholder issue")
    return normalized


def _fingerprint(review: Mapping[str, Any]) -> str:
    if review["trigger"] == "loop_end":
        material = {
            "artifact_version": review["artifact_version"],
            "kind": "loop_end",
            "loop_id": review["loop_id"],
            "loop_round": review["loop_round"],
            "project_id": review["project_id"],
        }
    else:
        material = {
            "artifact_version": review["artifact_version"],
            "issue_key": _normalize_issue_key(review["issue_key"]),
            "project_id": review["project_id"],
            "root_cause_primary": review["root_cause_primary"],
            "task_refs": sorted(review["task_refs"]),
        }
    try:
        return canonical_sha256(material)
    except CanonicalValueError as exc:
        raise _error(E_FINGERPRINT, "issue fingerprint input is not canonical JSON") from exc


def _validate_review_body(value: object, *, signed: bool) -> dict[str, Any]:
    fields = SIGNED_REVIEW_FIELDS if signed else UNSIGNED_REVIEW_FIELDS
    review = _exact(value, fields, "loop review")
    if review["schema_version"] != "goal-teams-loop-review-v2.65":
        raise _error(E_SCHEMA, "loop review schema_version differs")

    for field in ("review_id", "project_id", "artifact_version", "skill_version"):
        review[field] = _one_line(review[field], field)
    review["loop_id"] = _one_line(review["loop_id"], "loop_id", identifier=True)
    review["source_revision"] = _one_line(review["source_revision"], "source_revision")
    for field in ("loop_round", "sequence", "graph_revision", "plan_revision"):
        if not is_int(review[field], minimum=1):
            raise _error(E_SCHEMA, f"{field} must be a positive integer")
    expected_review_id = (
        f"LOOP-REVIEW-{review['loop_id']}-R{review['loop_round']}-{review['sequence']}"
    )
    if review["review_id"] != expected_review_id:
        raise _error(E_SCHEMA, "review_id does not bind loop_id, round and sequence")
    review["occurred_at"] = require_utc_timestamp(
        review["occurred_at"], error=lambda message: _error(E_SCHEMA, message), label="occurred_at"
    )
    if not is_sha256(review["task_exact_set_sha256"]):
        raise _error(E_SCHEMA, "task_exact_set_sha256 is invalid")
    if not is_sha256(review["previous_review_sha256"]):
        raise _error(E_SCHEMA, "previous_review_sha256 is invalid")

    review["task_refs"] = _strings(
        review["task_refs"], "task_refs", non_empty=True, set_like=True
    )
    review["evidence_refs"] = _strings(review["evidence_refs"], "evidence_refs")
    review["observed_facts"] = _strings(
        review["observed_facts"], "observed_facts", non_empty=True
    )
    review["assumptions"] = _strings(review["assumptions"], "assumptions")
    review["uncertainty"] = _strings(review["uncertainty"], "uncertainty")
    review["retained_practices"] = _strings(
        review["retained_practices"], "retained_practices"
    )

    trigger = review["trigger"]
    if trigger not in TRIGGERS:
        raise _error(E_SCHEMA, "trigger is invalid")
    if trigger == "loop_end":
        if review["issue_key"] is not None:
            raise _error(E_TRIGGER, "loop_end review must not carry issue_key")
    else:
        _normalize_issue_key(review["issue_key"])
        if not review["evidence_refs"]:
            raise _error(E_EVIDENCE, "problem/user-correction review requires Evidence")

    loop_result = _exact(review["loop_result"], LOOP_RESULT_FIELDS, "loop_result")
    if loop_result["decision"] not in DECISIONS:
        raise _error(E_SCHEMA, "loop_result.decision is invalid")
    if not isinstance(loop_result["achieved"], bool):
        raise _error(E_SCHEMA, "loop_result.achieved must be a boolean")
    for field in ("blocked_items", "failed_items", "not_run_items", "open_gaps"):
        loop_result[field] = _strings(
            loop_result[field], f"loop_result.{field}", set_like=True
        )
    if loop_result["achieved"]:
        if loop_result["decision"] != "stop" or any(
            loop_result[field]
            for field in ("blocked_items", "failed_items", "not_run_items", "open_gaps")
        ):
            raise _error(E_SCHEMA, "achieved loop result contradicts open or non-passed items")
    review["loop_result"] = loop_result

    primary = review["root_cause_primary"]
    if primary not in ROOT_CAUSES:
        raise _error(E_SCHEMA, "root_cause_primary is invalid")
    secondary = _strings(
        review["root_cause_secondary"], "root_cause_secondary", set_like=True
    )
    if any(item not in ROOT_CAUSES for item in secondary) or primary in secondary:
        raise _error(E_SCHEMA, "root_cause_secondary is invalid or repeats the primary cause")
    review["root_cause_secondary"] = secondary

    if not isinstance(review["dimensions"], Mapping) or set(review["dimensions"]) != DIMENSION_NAME_SET:
        raise _error(E_SCHEMA, "dimensions must contain exactly the twelve V2.65 dimensions")
    dimensions = {
        name: _validate_dimension(review["dimensions"][name], name)
        for name in DIMENSION_NAMES
    }
    review["dimensions"] = dimensions

    outcome = review["review_outcome"]
    status = review["status"]
    if outcome not in REVIEW_OUTCOMES or status not in STATUSES:
        raise _error(E_SCHEMA, "review_outcome or status is invalid")
    candidate_dimensions = [
        name for name, dimension in dimensions.items() if dimension["state"] == "candidate"
    ]
    observed_dimensions = [
        name for name, dimension in dimensions.items() if dimension["state"] == "observed"
    ]
    if outcome in CANDIDATE_OUTCOMES:
        if review["candidate"] is None or status != "candidate_only" or not candidate_dimensions:
            raise _error(E_CANDIDATE, "candidate outcome requires candidate-only details and dimension")
        review["candidate"] = _validate_candidate(review["candidate"])
        if outcome == "backlog_candidate":
            if review["candidate"]["consumer_refs"]:
                raise _error(E_CANDIDATE, "backlog_candidate must not claim a current consumer")
        elif not review["candidate"]["consumer_refs"]:
            raise _error(E_CANDIDATE, "active candidate outcome requires a current consumer")
    else:
        if review["candidate"] is not None or candidate_dimensions:
            raise _error(E_CANDIDATE, "non-candidate outcome cannot carry a candidate")
    if outcome == "skill_improvement_candidate" and dimensions["skill"]["state"] != "candidate":
        raise _error(E_CANDIDATE, "Skill improvement candidate requires Skill dimension candidate")
    if outcome == "no_change" and (observed_dimensions or candidate_dimensions):
        raise _error(E_CANDIDATE, "no_change contradicts observed or candidate dimensions")
    if outcome == "observed_only" and not observed_dimensions:
        raise _error(E_CANDIDATE, "observed_only requires an observed dimension")

    if status == "candidate_only" and outcome not in CANDIDATE_OUTCOMES:
        raise _error(E_CANDIDATE, "candidate_only status requires a candidate outcome")
    if status == "rejected" and outcome != "rejected":
        raise _error(E_CANDIDATE, "rejected status and outcome differ")
    if status == "blocked" and outcome != "blocked":
        raise _error(E_CANDIDATE, "blocked status and outcome differ")
    if status == "review_incomplete":
        if trigger != "loop_end" or not review["evidence_refs"] or not review["observed_facts"]:
            raise _error(E_EVIDENCE, "review_incomplete requires a loop-end failure fact and Evidence")
    elif outcome == "no_change" and status != "closed":
        raise _error(E_CANDIDATE, "no_change must be closed unless review generation was incomplete")

    evidence_required = bool(observed_dimensions or candidate_dimensions) or status == "review_incomplete"
    if evidence_required and not review["evidence_refs"]:
        raise _error(E_EVIDENCE, "review findings require top-level Evidence")
    return review


def build_loop_review(review: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an unsigned Review and add its fingerprint and self-digest."""

    candidate = _validate_review_body(review, signed=False)
    candidate["issue_fingerprint"] = _fingerprint(candidate)
    try:
        candidate["review_sha256"] = canonical_sha256(candidate)
    except CanonicalValueError as exc:
        raise _error(E_SCHEMA, "loop review is not canonical JSON") from exc
    return copy.deepcopy(candidate)


def validate_loop_review(review: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a deep copy of an exact signed Review."""

    candidate = _validate_review_body(review, signed=True)
    expected_fingerprint = _fingerprint(candidate)
    if (
        not is_sha256(candidate["issue_fingerprint"])
        or candidate["issue_fingerprint"] != expected_fingerprint
    ):
        raise _error(E_FINGERPRINT, "derived issue_fingerprint differs")
    try:
        expected_review_sha256 = self_digest(candidate, "review_sha256")
    except CanonicalValueError as exc:
        raise _error(E_FINGERPRINT, "loop review is not canonical JSON") from exc
    if not is_sha256(candidate["review_sha256"]) or candidate["review_sha256"] != expected_review_sha256:
        raise _error(E_FINGERPRINT, "review_sha256 differs")
    return copy.deepcopy(candidate)


def validate_round_review(
    reviews: Sequence[Mapping[str, Any]],
    *,
    loop_id: str,
    loop_round: int,
) -> dict[str, Any]:
    """Require exactly one final loop-end Review for a LOOP round."""

    loop_id = _one_line(loop_id, "loop_id", identifier=True)
    if not is_int(loop_round, minimum=1):
        raise _error(E_SCHEMA, "loop_round must be a positive integer")
    if not isinstance(reviews, Sequence) or isinstance(reviews, (str, bytes, bytearray)):
        raise _error(E_SCHEMA, "reviews must be a sequence")
    validated = [validate_loop_review(review) for review in reviews]
    if not validated:
        raise _error(E_REQUIRED, "round has no loop-end Review")
    if any(review["loop_id"] != loop_id or review["loop_round"] != loop_round for review in validated):
        raise _error(E_SCHEMA, "round Review binding differs")
    review_ids = [review["review_id"] for review in validated]
    if len(review_ids) != len(set(review_ids)):
        raise _error(E_SCHEMA, "round repeats a Review ID")
    ordered = sorted(validated, key=lambda review: review["sequence"])
    if [review["sequence"] for review in ordered] != sorted(
        {review["sequence"] for review in ordered}
    ):
        raise _error(E_SCHEMA, "round Review sequence repeats")
    for previous, current in zip(ordered, ordered[1:]):
        if current["previous_review_sha256"] != previous["review_sha256"]:
            raise _error(E_FINGERPRINT, "round Review digest chain differs")
    loop_end = [review for review in ordered if review["trigger"] == "loop_end"]
    if not loop_end:
        raise _error(E_REQUIRED, "round has no loop-end Review")
    if len(loop_end) != 1:
        raise _error(E_DUPLICATE_LOOP_END, "round has more than one loop-end Review")
    if ordered[-1]["review_id"] != loop_end[0]["review_id"]:
        raise _error(E_TRIGGER, "loop-end Review must be final in the round")
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-loop-review-round-receipt-v2.65",
        "loop_id": loop_id,
        "loop_round": loop_round,
        "review_ids": [review["review_id"] for review in ordered],
        "loop_end_review_id": loop_end[0]["review_id"],
        "valid": True,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


def _render_header(review: Mapping[str, Any]) -> bytes:
    for field in ("project_id", "artifact_version", "skill_version"):
        _one_line(review[field], field)
    return (
        "# LOOP Review\n\n"
        f"- project: {review['project_id']}\n"
        f"- artifact_version: {review['artifact_version']}\n"
        f"- skill_version: {review['skill_version']}\n"
        f"- created_at: {review['occurred_at']}\n"
        "- format: goal-teams-loop-review-v2.65\n"
    ).encode("utf-8")


def _frame_metadata(review: Mapping[str, Any], payload_bytes: int) -> dict[str, Any]:
    return {
        "payload_bytes": payload_bytes,
        "review_id": review["review_id"],
        "review_sha256": review["review_sha256"],
    }


def _markdown_value(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _render_summary(review: Mapping[str, Any]) -> bytes:
    lines = [
        f"## {review['review_id']}",
        "",
        "### 基本信息",
        "",
    ]
    for field in (
        "trigger",
        "project_id",
        "artifact_version",
        "skill_version",
        "loop_id",
        "loop_round",
        "sequence",
        "occurred_at",
        "graph_revision",
        "plan_revision",
        "task_exact_set_sha256",
        "source_revision",
        "task_refs",
        "evidence_refs",
        "issue_key",
        "issue_fingerprint",
    ):
        lines.append(f"- {field}: {_markdown_value(review[field])}")
    lines.extend(("", "### 本轮结果", ""))
    for field in (
        "decision",
        "achieved",
        "blocked_items",
        "failed_items",
        "not_run_items",
        "open_gaps",
    ):
        lines.append(f"- {field}: {_markdown_value(review['loop_result'][field])}")
    lines.extend(("", "### 事实与保留项", ""))
    for field in (
        "observed_facts",
        "assumptions",
        "uncertainty",
        "retained_practices",
        "root_cause_primary",
        "root_cause_secondary",
    ):
        lines.append(f"- {field}: {_markdown_value(review[field])}")
    lines.extend(("", "### 十二维反思", ""))
    for name in DIMENSION_NAMES:
        lines.extend((f"#### {name}", ""))
        dimension = review["dimensions"][name]
        for field in (
            "state",
            "finding",
            "evidence_refs",
            "improvement",
            "expected_benefit",
            "validation_method",
            "risk",
        ):
            lines.append(f"- {field}: {_markdown_value(dimension[field])}")
        lines.append("")
    lines.extend(("### 改进决策", ""))
    for field in ("review_outcome", "status", "candidate", "previous_review_sha256", "review_sha256"):
        lines.append(f"- {field}: {_markdown_value(review[field])}")
    lines.extend(("", "### Signed review payload", ""))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_frame(review: Mapping[str, Any]) -> bytes:
    payload = canonical_json_bytes(review)
    metadata = canonical_json_bytes(_frame_metadata(review, len(payload)))
    return b"".join(
        (
            b"\n",
            FRAME_BEGIN_PREFIX,
            metadata,
            FRAME_COMMENT_SUFFIX,
            _render_summary(review),
            b"```json\n",
            payload,
            b"\n```\n",
            FRAME_END_PREFIX,
            metadata,
            FRAME_COMMENT_SUFFIX,
        )
    )


def _parse_header(raw: bytes) -> tuple[dict[str, str], bytes, int]:
    lines = raw.splitlines(keepends=True)
    if len(lines) < 7:
        raise _error(E_STATE_DRIFT, "Markdown header is incomplete")
    prefixes = (
        b"- project: ",
        b"- artifact_version: ",
        b"- skill_version: ",
        b"- created_at: ",
    )
    if lines[0] != b"# LOOP Review\n" or lines[1] != b"\n":
        raise _error(E_STATE_DRIFT, "Markdown header differs")
    values: list[str] = []
    for line, prefix in zip(lines[2:6], prefixes):
        if not line.startswith(prefix) or not line.endswith(b"\n"):
            raise _error(E_STATE_DRIFT, "Markdown header identity differs")
        try:
            values.append(line[len(prefix) : -1].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise _error(E_STATE_DRIFT, "Markdown header is not UTF-8") from exc
    if lines[6] != b"- format: goal-teams-loop-review-v2.65\n":
        raise _error(E_STATE_DRIFT, "Markdown format identity differs")
    header = b"".join(lines[:7])
    identities = {
        "project_id": values[0],
        "artifact_version": values[1],
        "skill_version": values[2],
        "created_at": values[3],
    }
    for field in ("project_id", "artifact_version", "skill_version"):
        _one_line(identities[field], f"header.{field}", code=E_STATE_DRIFT)
    require_utc_timestamp(
        identities["created_at"],
        error=lambda message: _error(E_STATE_DRIFT, message),
        label="header.created_at",
    )
    return identities, header, len(header)


def _parse_metadata_line(line: bytes, prefix: bytes) -> dict[str, Any]:
    if not line.startswith(prefix) or not line.endswith(FRAME_COMMENT_SUFFIX):
        raise _error(E_STATE_DRIFT, "Review frame marker differs")
    raw = line[len(prefix) : -len(FRAME_COMMENT_SUFFIX)]
    try:
        metadata = parse_json_bytes(raw)
    except (CanonicalValueError, ValueError) as exc:
        raise _error(E_STATE_DRIFT, "Review frame metadata is invalid") from exc
    expected_fields = frozenset({"payload_bytes", "review_id", "review_sha256"})
    try:
        result = _exact(metadata, expected_fields, "frame metadata", code=E_STATE_DRIFT)
    except LoopReviewError:
        raise
    if not is_int(result["payload_bytes"], minimum=1):
        raise _error(E_STATE_DRIFT, "Review frame payload byte count is invalid")
    if not is_non_empty_string(result["review_id"]) or not is_sha256(result["review_sha256"]):
        raise _error(E_STATE_DRIFT, "Review frame identity is invalid")
    if canonical_json_bytes(result) != raw:
        raise _error(E_STATE_DRIFT, "Review frame metadata is not canonical")
    return result


def _parse_document(raw: bytes) -> tuple[dict[str, str], bytes, list[dict[str, Any]], list[bytes]]:
    identities, header, position = _parse_header(raw)
    reviews: list[dict[str, Any]] = []
    frames: list[bytes] = []
    while position < len(raw):
        frame_start = position
        if not raw.startswith(b"\n", position):
            raise _error(E_STATE_DRIFT, "unexpected bytes follow a complete Review frame")
        position += 1
        begin_end = raw.find(b"\n", position)
        if begin_end < 0:
            raise _error(E_STATE_DRIFT, "Review begin marker is incomplete")
        begin_line = raw[position : begin_end + 1]
        begin_metadata = _parse_metadata_line(begin_line, FRAME_BEGIN_PREFIX)
        position = begin_end + 1

        payload_marker = raw.find(SIGNED_PAYLOAD_MARKER, position)
        if payload_marker < 0:
            raise _error(E_STATE_DRIFT, "Review signed payload marker is absent")
        position = payload_marker + len(SIGNED_PAYLOAD_MARKER)
        payload_end = raw.find(b"\n```\n", position)
        if payload_end < 0:
            raise _error(E_STATE_DRIFT, "Review payload frame is incomplete")
        payload = raw[position:payload_end]
        position = payload_end + len(b"\n```\n")

        end_end = raw.find(b"\n", position)
        if end_end < 0:
            raise _error(E_STATE_DRIFT, "Review end marker is incomplete")
        end_line = raw[position : end_end + 1]
        end_metadata = _parse_metadata_line(end_line, FRAME_END_PREFIX)
        position = end_end + 1
        if end_metadata != begin_metadata or len(payload) != begin_metadata["payload_bytes"]:
            raise _error(E_STATE_DRIFT, "Review frame markers or payload byte count differ")
        try:
            parsed = parse_json_bytes(payload)
            review = validate_loop_review(parsed)
        except (CanonicalValueError, LoopReviewError, ValueError) as exc:
            raise _error(E_STATE_DRIFT, "embedded Review does not validate") from exc
        if canonical_json_bytes(review) != payload:
            raise _error(E_STATE_DRIFT, "embedded Review is not canonical")
        if (
            review["review_id"] != begin_metadata["review_id"]
            or review["review_sha256"] != begin_metadata["review_sha256"]
        ):
            raise _error(E_STATE_DRIFT, "embedded Review identity differs from frame")
        frame = raw[frame_start:position]
        if frame != _render_frame(review):
            raise _error(E_STATE_DRIFT, "Review frame is not deterministic")
        reviews.append(review)
        frames.append(frame)
    if not reviews:
        raise _error(E_STATE_DRIFT, "Markdown has a header but no Review frame")
    seen_ids: set[str] = set()
    seen_issues: set[str] = set()
    closed_rounds: set[str] = set()
    for index, review in enumerate(reviews, start=1):
        if review["sequence"] != index:
            raise _error(E_STATE_DRIFT, "Review sequence is not contiguous")
        expected_previous = ZERO_SHA256 if index == 1 else reviews[index - 2]["review_sha256"]
        if review["previous_review_sha256"] != expected_previous:
            raise _error(E_STATE_DRIFT, "Review digest chain differs")
        if review["review_id"] in seen_ids:
            raise _error(E_STATE_DRIFT, "Review ID repeats")
        seen_ids.add(review["review_id"])
        for field in ("project_id", "artifact_version", "skill_version"):
            if review[field] != identities[field]:
                raise _error(E_STATE_DRIFT, "Review identity differs from immutable header")
        round_key = f"{review['loop_id']}:{review['loop_round']}"
        if round_key in closed_rounds:
            raise _error(E_STATE_DRIFT, "Review appears after its LOOP round closed")
        if review["trigger"] == "loop_end":
            closed_rounds.add(round_key)
        elif review["issue_fingerprint"] in seen_issues:
            raise _error(E_STATE_DRIFT, "material issue fingerprint repeats")
        else:
            seen_issues.add(review["issue_fingerprint"])
    if reviews[0]["occurred_at"] != identities["created_at"]:
        raise _error(E_STATE_DRIFT, "Review header created_at differs from first Review")
    return identities, header, reviews, frames


def _validate_sidecar(value: object) -> dict[str, Any]:
    state = _exact(value, STATE_FIELDS, "loop review sidecar", code=E_STATE_DRIFT)
    if state["schema_version"] != "goal-teams-loop-review-state-v2.65":
        raise _error(E_STATE_DRIFT, "sidecar schema_version differs")
    for field in ("revision", "review_count"):
        if not is_int(state[field], minimum=1):
            raise _error(E_STATE_DRIFT, f"sidecar {field} is invalid")
    if state["revision"] != state["review_count"]:
        raise _error(E_STATE_DRIFT, "sidecar revision and review_count differ")
    for field in ("file_sha256", "last_review_sha256", "header_sha256", "state_sha256"):
        if not is_sha256(state[field]):
            raise _error(E_STATE_DRIFT, f"sidecar {field} is invalid")
    state["loop_end_keys"] = _strings(
        state["loop_end_keys"],
        "sidecar.loop_end_keys",
        set_like=True,
        code=E_STATE_DRIFT,
    )
    state["issue_fingerprints"] = _strings(
        state["issue_fingerprints"],
        "sidecar.issue_fingerprints",
        set_like=True,
        code=E_STATE_DRIFT,
    )
    try:
        expected = self_digest(state, "state_sha256")
    except CanonicalValueError as exc:
        raise _error(E_STATE_DRIFT, "sidecar is not canonical JSON") from exc
    if state["state_sha256"] != expected:
        raise _error(E_STATE_DRIFT, "sidecar self-digest differs")
    return state


def _state_for_document(header: bytes, reviews: Sequence[Mapping[str, Any]], file_bytes: bytes) -> dict[str, Any]:
    loop_end_keys = sorted(
        f"{review['loop_id']}:{review['loop_round']}"
        for review in reviews
        if review["trigger"] == "loop_end"
    )
    issue_fingerprints = sorted(
        review["issue_fingerprint"]
        for review in reviews
        if review["trigger"] != "loop_end"
    )
    state: dict[str, Any] = {
        "schema_version": "goal-teams-loop-review-state-v2.65",
        "revision": len(reviews),
        "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "last_review_sha256": reviews[-1]["review_sha256"],
        "review_count": len(reviews),
        "loop_end_keys": loop_end_keys,
        "issue_fingerprints": issue_fingerprints,
        "header_sha256": hashlib.sha256(header).hexdigest(),
    }
    state["state_sha256"] = canonical_sha256(state)
    return state


def _resolve_paths(
    project_root: Path | str,
    relative_path: str,
    *,
    create_parent: bool,
) -> tuple[Path, Path, Path, Path, str]:
    try:
        root = Path(project_root)
    except (TypeError, ValueError) as exc:
        raise _error(E_PATH, "project_root is invalid") from exc
    if not root.is_absolute() or not root.exists() or not root.is_dir() or root.is_symlink():
        raise _error(E_PATH, "project_root must be an existing absolute real directory")
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise _error(E_PATH, "project_root cannot be resolved") from exc
    if resolved_root != root or os.path.realpath(os.fspath(root)) != os.fspath(root):
        raise _error(E_PATH, "project_root must not cross a symlink or alias")
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise _error(E_PATH, "relative_path must be a non-empty POSIX path")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts) or parts[-1] != "loop-review.md":
        raise _error(E_PATH, "relative_path must safely end in loop-review.md")
    target = root.joinpath(*parts)
    try:
        if os.path.commonpath((os.fspath(root), os.fspath(target))) != os.fspath(root):
            raise _error(E_PATH, "Review output escapes project_root")
    except ValueError as exc:
        raise _error(E_PATH, "Review output path differs from project_root") from exc

    current = root
    for part in parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise _error(E_PATH, "Review output crosses a symlink or non-directory")
        elif create_parent:
            try:
                current.mkdir(mode=0o700, exist_ok=True)
            except OSError as exc:
                raise _error(E_PATH, "Review output parent cannot be created") from exc
            if current.is_symlink() or not current.is_dir():
                raise _error(E_PATH, "created Review output parent is unsafe")
        else:
            raise _error(E_PATH, "Review output parent does not exist")
    state_path = Path(f"{target}.state.json")
    lock_path = Path(f"{target}.lock")
    for path in (target, state_path, lock_path):
        if path.is_symlink():
            raise _error(E_PATH, "Review output, sidecar, or lock is a symlink")
        if path.exists() and not path.is_file():
            raise _error(E_PATH, "Review output, sidecar, or lock is not a regular file")
    return root, target, state_path, lock_path, "/".join(parts)


class _ExclusiveLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "_ExclusiveLock":
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            self.fd = os.open(self.path, flags, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except OSError as exc:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise _error(E_PATH, "Review lock cannot be acquired safely") from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def _read_sidecar(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        parsed = parse_json_bytes(raw)
        state = _validate_sidecar(parsed)
    except LoopReviewError:
        raise
    except (OSError, CanonicalValueError, ValueError) as exc:
        raise _error(E_STATE_DRIFT, "sidecar cannot be read or parsed") from exc
    if raw != canonical_json_bytes(state):
        raise _error(E_STATE_DRIFT, "sidecar bytes are not canonical")
    return state, raw


def _load_consistent(
    target: Path, state_path: Path
) -> tuple[bytes, dict[str, Any] | None, dict[str, str] | None, bytes | None, list[dict[str, Any]], list[bytes]]:
    target_exists = target.exists()
    state_exists = state_path.exists()
    if target_exists != state_exists:
        raise _error(E_STATE_DRIFT, "Markdown and sidecar existence differs")
    if not target_exists:
        return b"", None, None, None, [], []
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise _error(E_STATE_DRIFT, "Markdown cannot be read") from exc
    state, _ = _read_sidecar(state_path)
    if hashlib.sha256(raw).hexdigest() != state["file_sha256"]:
        raise _error(E_STATE_DRIFT, "Markdown digest differs from sidecar")
    identities, header, reviews, frames = _parse_document(raw)
    expected = _state_for_document(header, reviews, raw)
    if state != expected:
        raise _error(E_STATE_DRIFT, "Markdown content and sidecar projection differ")
    return raw, state, identities, header, reviews, frames


def _validate_append_transition(
    review: Mapping[str, Any],
    *,
    identities: Mapping[str, str] | None,
    reviews: Sequence[Mapping[str, Any]],
    state: Mapping[str, Any] | None,
) -> None:
    if identities is not None:
        for field in ("project_id", "artifact_version", "skill_version"):
            if review[field] != identities[field]:
                raise _error(E_APPEND_CAS, f"Review {field} differs from immutable header")
    expected_sequence = len(reviews) + 1
    expected_previous = ZERO_SHA256 if state is None else state["last_review_sha256"]
    if review["sequence"] != expected_sequence or review["previous_review_sha256"] != expected_previous:
        raise _error(E_APPEND_CAS, "Review sequence or previous digest differs")
    loop_end_key = f"{review['loop_id']}:{review['loop_round']}"
    existing_loop_end_keys = set(state["loop_end_keys"]) if state is not None else set()
    if loop_end_key in existing_loop_end_keys:
        raise _error(E_DUPLICATE_LOOP_END, "LOOP round is already closed")
    if review["trigger"] != "loop_end":
        existing_fingerprints = set(state["issue_fingerprints"]) if state is not None else set()
        if review["issue_fingerprint"] in existing_fingerprints:
            raise _error(E_DUPLICATE_ISSUE, "material issue fingerprint already exists")


def _append_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "ab", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise _error(E_STATE_DRIFT, "Markdown append or fsync failed") from exc


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise _error(E_STATE_DRIFT, "Review directory fsync failed") from exc


def _write_sidecar(path: Path, state: Mapping[str, Any]) -> bytes:
    raw = canonical_json_bytes(state)
    temp_path: str | None = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".loop-review-state-", dir=path.parent)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
        temp_path = None
        _fsync_directory(path.parent)
        if path.read_bytes() != raw:
            raise _error(E_STATE_DRIFT, "sidecar exact readback differs")
    except LoopReviewError:
        raise
    except OSError as exc:
        raise _error(E_STATE_DRIFT, "sidecar atomic replacement failed") from exc
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
    return raw


def append_loop_review(
    project_root: Path | str,
    relative_path: str,
    review: Mapping[str, Any],
    *,
    expected_previous_file_sha256: str,
    expected_state_revision: int,
) -> dict[str, Any]:
    """Append one signed Review using file/sidecar CAS and durable fsync."""

    signed = validate_loop_review(review)
    if not is_sha256(expected_previous_file_sha256) or not is_int(
        expected_state_revision, minimum=0
    ):
        raise _error(E_APPEND_CAS, "caller CAS values are invalid")
    _, target, state_path, lock_path, normalized_relative = _resolve_paths(
        project_root, relative_path, create_parent=True
    )
    with _ExclusiveLock(lock_path):
        raw_before, state, identities, header, reviews, _ = _load_consistent(
            target, state_path
        )
        current_revision = 0 if state is None else state["revision"]
        current_file_sha256 = ZERO_SHA256 if state is None else state["file_sha256"]
        if (
            expected_state_revision != current_revision
            or expected_previous_file_sha256 != current_file_sha256
        ):
            raise _error(E_APPEND_CAS, "caller CAS values differ from current Review state")
        _validate_append_transition(
            signed, identities=identities, reviews=reviews, state=state
        )
        if state is None:
            header = _render_header(signed)
            append_bytes = header + _render_frame(signed)
        else:
            assert header is not None
            append_bytes = _render_frame(signed)
        _append_file(target, append_bytes)
        try:
            raw_after = target.read_bytes()
        except OSError as exc:
            raise _error(E_STATE_DRIFT, "Markdown exact readback failed") from exc
        if raw_after != raw_before + append_bytes:
            raise _error(E_STATE_DRIFT, "Markdown exact readback differs")
        next_reviews = [*reviews, signed]
        next_state = _state_for_document(header, next_reviews, raw_after)
        sidecar_raw = _write_sidecar(state_path, next_state)
        if hashlib.sha256(raw_after).hexdigest() != next_state["file_sha256"]:
            raise _error(E_STATE_DRIFT, "Markdown digest differs after sidecar commit")
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-loop-review-append-receipt-v2.65",
            "review_id": signed["review_id"],
            "relative_path": normalized_relative,
            "state_revision_before": current_revision,
            "state_revision_after": next_state["revision"],
            "file_sha256_before": current_file_sha256,
            "file_sha256_after": next_state["file_sha256"],
            "review_sha256": signed["review_sha256"],
            "bytes_appended": len(append_bytes),
            "sidecar_sha256": hashlib.sha256(sidecar_raw).hexdigest(),
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt


def reconcile_loop_review(
    project_root: Path | str,
    relative_path: str,
) -> dict[str, Any]:
    """Advance a stale sidecar over exactly one complete, valid Review frame."""

    _, target, state_path, lock_path, normalized_relative = _resolve_paths(
        project_root, relative_path, create_parent=False
    )
    with _ExclusiveLock(lock_path):
        target_exists = target.exists()
        state_exists = state_path.exists()
        if not target_exists:
            if state_exists:
                raise _error(E_STATE_DRIFT, "sidecar exists without Markdown")
            receipt: dict[str, Any] = {
                "schema_version": "goal-teams-loop-review-reconcile-receipt-v2.65",
                "relative_path": normalized_relative,
                "state_revision_before": 0,
                "state_revision_after": 0,
                "file_sha256": ZERO_SHA256,
                "last_review_sha256": ZERO_SHA256,
                "reconciled_review_id": None,
            }
            receipt["receipt_sha256"] = canonical_sha256(receipt)
            return receipt
        try:
            raw = target.read_bytes()
            identities, header, reviews, frames = _parse_document(raw)
        except LoopReviewError:
            raise
        except OSError as exc:
            raise _error(E_STATE_DRIFT, "Markdown cannot be read for reconciliation") from exc

        if state_exists:
            state, _ = _read_sidecar(state_path)
            before_revision = state["revision"]
            if len(reviews) < before_revision:
                raise _error(E_STATE_DRIFT, "Markdown lost frames recorded by sidecar")
            prefix = header + b"".join(frames[:before_revision])
            prefix_state = _state_for_document(header, reviews[:before_revision], prefix)
            if prefix_state != state:
                raise _error(E_STATE_DRIFT, "sidecar does not match the Markdown prefix")
        else:
            state = None
            before_revision = 0

        if len(reviews) == before_revision:
            assert state is not None
            if hashlib.sha256(raw).hexdigest() != state["file_sha256"]:
                raise _error(E_STATE_DRIFT, "Markdown digest differs without a new frame")
            reconciled_review_id: str | None = None
            next_state = state
        elif len(reviews) == before_revision + 1:
            new_review = reviews[-1]
            prior_reviews = reviews[:-1]
            _validate_append_transition(
                new_review,
                identities=identities,
                reviews=prior_reviews,
                state=state,
            )
            next_state = _state_for_document(header, reviews, raw)
            _write_sidecar(state_path, next_state)
            reconciled_review_id = new_review["review_id"]
        else:
            raise _error(E_STATE_DRIFT, "more than one unseen Review follows the sidecar head")

        receipt = {
            "schema_version": "goal-teams-loop-review-reconcile-receipt-v2.65",
            "relative_path": normalized_relative,
            "state_revision_before": before_revision,
            "state_revision_after": next_state["revision"],
            "file_sha256": next_state["file_sha256"],
            "last_review_sha256": next_state["last_review_sha256"],
            "reconciled_review_id": reconciled_review_id,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt


def inspect_loop_review(
    project_root: Path | str,
    relative_path: str,
) -> dict[str, Any]:
    """Return a deep, read-only snapshot of one consistent Review document.

    The function shares the writer's path, symlink, frame and sidecar checks.  It
    never creates a directory or file and never repairs inconsistent state.
    """

    _, target, state_path, _lock_path, normalized_relative = _resolve_paths(
        project_root, relative_path, create_parent=False
    )
    raw, state, identities, _header, reviews, _frames = _load_consistent(
        target, state_path
    )
    return {
        "schema_version": "goal-teams-loop-review-inspection-v2.65",
        "relative_path": normalized_relative,
        "exists": state is not None,
        "project_id": None if identities is None else identities["project_id"],
        "artifact_version": None if identities is None else identities["artifact_version"],
        "skill_version": None if identities is None else identities["skill_version"],
        "review_state_revision": 0 if state is None else state["revision"],
        "review_file_sha256": ZERO_SHA256 if state is None else state["file_sha256"],
        "last_review_sha256": ZERO_SHA256 if state is None else state["last_review_sha256"],
        "review_ids": [review["review_id"] for review in reviews],
        "reviews": copy.deepcopy(reviews),
        "raw_bytes_sha256": hashlib.sha256(raw).hexdigest(),
    }
