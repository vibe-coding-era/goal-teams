"""Compile declared, bounded V2.65 Context Bundles and Review Capsules.

The compiler consumes caller-supplied bytes only.  It never discovers files,
builds a Provider prompt, or loads the complete ``loop-review.md`` history.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
from collections.abc import Mapping, Sequence
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
    timestamp_value,
    unique_string_list,
)


class ContextCompilerError(ValueError):
    """A Context input cannot be compiled without weakening its declaration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


E_MISSING = "E_V265_CONTEXT_RESOURCE_MISSING"
E_UNDECLARED = "E_V265_CONTEXT_UNDECLARED_RESOURCE"
E_FORBIDDEN = "E_V265_CONTEXT_FORBIDDEN_RESOURCE"
E_DIGEST = "E_V265_CONTEXT_DIGEST"
E_STALE = "E_V265_CONTEXT_STALE"
E_PERMISSION = "E_V265_CONTEXT_PERMISSION"
E_TOKEN = "E_V265_CONTEXT_TOKEN_BUDGET"
E_CAPSULE = "E_V265_CONTEXT_CAPSULE"
E_CAPSULE_BUDGET = "E_V265_REVIEW_CAPSULE_BUDGET"

GRAPH_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "graph_id",
        "graph_revision",
        "plan_binding",
        "supersedes_graph_sha256",
        "nodes",
        "edges",
        "resources",
        "gates",
        "actions",
    }
)
GRAPH_COMPILED_FIELDS = GRAPH_INPUT_FIELDS | frozenset(
    {
        "task_node_map",
        "predecessor_map",
        "fan_in_map",
        "topological_order",
        "ready_roots",
        "execution_edge_ids",
        "lineage_edge_ids",
        "graph_contract_sha256",
        "receipt_sha256",
    }
)
NODE_FIELDS = frozenset(
    {
        "node_id",
        "task_refs",
        "node_type",
        "owner_identity",
        "validator_identity",
        "action_ref",
        "resource_refs",
        "input_ports",
        "output_ports",
        "scope_allowlist",
        "forbidden_scope",
        "budget",
        "timeout_seconds",
        "retry_policy",
        "gate_refs",
        "exit_condition_ref",
        "recovery_policy",
        "fan_in",
    }
)
RESOURCE_REF_FIELDS = frozenset(
    {"required", "recommended", "generated", "upstream_artifacts", "forbidden"}
)
BUDGET_FIELDS = frozenset({"work_units", "attempts", "revalidations", "context_tokens"})
RESOURCE_FIELDS = frozenset(
    {
        "resource_id",
        "resource_type",
        "source_ref",
        "revision",
        "expected_sha256",
        "schema_ref",
        "freshness_policy",
        "sensitivity",
        "permission_ref",
        "token_budget",
        "producer_node_id",
        "consumer_node_ids",
    }
)
FRESHNESS_FIELDS = frozenset({"mode", "max_age_seconds"})
OBSERVATION_FIELDS = frozenset(
    {
        "resource_id",
        "observed_revision",
        "observed_sha256",
        "fetched_at",
        "permission_ref",
        "producer_receipt_sha256",
    }
)
COMPILED_RESOURCE_FIELDS = frozenset(
    {
        "resource_id",
        "resource_type",
        "source_ref",
        "revision",
        "sha256",
        "bytes",
        "estimated_tokens",
        "freshness_state",
        "sensitivity",
        "permission_ref",
        "producer_node_id",
        "producer_receipt_sha256",
        "content_base64",
    }
)
BUNDLE_FIELDS = frozenset(
    {
        "schema_version",
        "bundle_id",
        "graph_contract_sha256",
        "node_id",
        "resources",
        "review_capsule_sha256",
        "total_bytes",
        "estimated_tokens",
        "token_estimate_algorithm",
        "compiled_at",
        "bundle_sha256",
    }
)
CAPSULE_FIELDS = frozenset(
    {
        "schema_version",
        "capsule_id",
        "source_review_ids",
        "source_review_sha256s",
        "retained_practices",
        "active_adjustments",
        "open_gaps",
        "forbidden_retries",
        "required_evidence",
        "compiled_at",
        "capsule_sha256",
    }
)

SENSITIVITIES = frozenset({"public", "internal", "confidential", "restricted"})
RESOURCE_TYPES = frozenset(
    {
        "repository_file",
        "user_input",
        "rule",
        "upstream_artifact",
        "generated_context",
        "review_capsule",
    }
)


def _error(code: str, message: str) -> ContextCompilerError:
    return ContextCompilerError(code, message)


def _exact(
    value: object,
    fields: frozenset[str],
    label: str,
    *,
    code: str,
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
    code: str,
    non_empty: bool = False,
    set_like: bool = True,
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


def _required_string(value: object, label: str, *, code: str) -> str:
    if not is_non_empty_string(value) or not isinstance(value, str):
        raise _error(code, f"{label} must be a non-empty string")
    return value


def _require_self_digest(value: Mapping[str, Any], field: str, *, code: str, label: str) -> None:
    try:
        expected = self_digest(value, field)
    except CanonicalValueError as exc:
        raise _error(code, f"{label} is not canonical JSON") from exc
    if not is_sha256(value.get(field)) or value[field] != expected:
        raise _error(code, f"{label} self-digest differs")


def _validated_graph(compiled_graph: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    graph = _exact(compiled_graph, GRAPH_COMPILED_FIELDS, "compiled_graph", code=E_DIGEST)
    if graph["schema_version"] != "goal-teams-graph-contract-v2.65":
        raise _error(E_DIGEST, "compiled Graph schema_version differs")
    normalized = {field: copy.deepcopy(graph[field]) for field in GRAPH_INPUT_FIELDS}
    try:
        if graph["graph_contract_sha256"] != canonical_sha256(normalized):
            raise _error(E_DIGEST, "compiled Graph contract digest differs")
        _require_self_digest(graph, "receipt_sha256", code=E_DIGEST, label="compiled Graph")
    except CanonicalValueError as exc:
        raise _error(E_DIGEST, "compiled Graph is not canonical JSON") from exc
    if not isinstance(graph["nodes"], list) or not isinstance(graph["resources"], list):
        raise _error(E_DIGEST, "compiled Graph Node or Resource collection is invalid")
    node_by_id: dict[str, Any] = {}
    for raw_node in graph["nodes"]:
        node = _exact(raw_node, NODE_FIELDS, "compiled Graph Node", code=E_DIGEST)
        node_id = _required_string(node["node_id"], "node_id", code=E_DIGEST)
        if node_id in node_by_id:
            raise _error(E_DIGEST, "compiled Graph repeats a Node ID")
        refs = _exact(node["resource_refs"], RESOURCE_REF_FIELDS, "Node resource_refs", code=E_DIGEST)
        for category in RESOURCE_REF_FIELDS:
            refs[category] = _strings(
                refs[category], f"resource_refs.{category}", code=E_DIGEST
            )
        flattened = [item for category in RESOURCE_REF_FIELDS for item in refs[category]]
        if len(flattened) != len(set(flattened)):
            raise _error(E_DIGEST, "Node resource_ref categories overlap")
        node["resource_refs"] = refs
        budget = _exact(node["budget"], BUDGET_FIELDS, "Node budget", code=E_DIGEST)
        if not is_int(budget["context_tokens"], minimum=1):
            raise _error(E_DIGEST, "Node context token budget is invalid")
        node["budget"] = budget
        node_by_id[node_id] = node
    resource_by_id: dict[str, Any] = {}
    for raw_resource in graph["resources"]:
        resource = _validate_resource_declaration(raw_resource)
        resource_id = resource["resource_id"]
        if resource_id in resource_by_id:
            raise _error(E_DIGEST, "compiled Graph repeats a Resource ID")
        resource_by_id[resource_id] = resource
    return graph, node_by_id, resource_by_id


def _validate_resource_declaration(value: object) -> dict[str, Any]:
    resource = _exact(value, RESOURCE_FIELDS, "Resource", code=E_DIGEST)
    for field in ("resource_id", "source_ref", "revision", "schema_ref", "permission_ref"):
        resource[field] = _required_string(resource[field], f"Resource.{field}", code=E_DIGEST)
    if resource["resource_type"] not in RESOURCE_TYPES:
        raise _error(E_DIGEST, "Resource type is invalid")
    if resource["sensitivity"] not in SENSITIVITIES:
        raise _error(E_DIGEST, "Resource sensitivity is invalid")
    if resource["expected_sha256"] is not None and not is_sha256(resource["expected_sha256"]):
        raise _error(E_DIGEST, "Resource expected_sha256 is invalid")
    if not is_int(resource["token_budget"], minimum=1):
        raise _error(E_TOKEN, "Resource token budget is invalid")
    if resource["producer_node_id"] is not None and not is_non_empty_string(resource["producer_node_id"]):
        raise _error(E_DIGEST, "Resource producer_node_id is invalid")
    resource["consumer_node_ids"] = _strings(
        resource["consumer_node_ids"], "Resource.consumer_node_ids", code=E_DIGEST
    )
    freshness = _exact(
        resource["freshness_policy"], FRESHNESS_FIELDS, "Resource freshness_policy", code=E_DIGEST
    )
    mode = freshness["mode"]
    if mode not in {"immutable", "max_age", "runtime"}:
        raise _error(E_DIGEST, "Resource freshness mode is invalid")
    if mode == "max_age":
        if not is_int(freshness["max_age_seconds"], minimum=1):
            raise _error(E_DIGEST, "max_age Resource requires a positive age")
    elif freshness["max_age_seconds"] is not None:
        raise _error(E_DIGEST, "non-max-age Resource must use null max_age_seconds")
    if mode == "immutable" and resource["expected_sha256"] is None:
        raise _error(E_DIGEST, "immutable Resource requires expected_sha256")
    if mode == "runtime" and not is_non_empty_string(resource["producer_node_id"]):
        raise _error(E_DIGEST, "runtime Resource requires a producer")
    resource["freshness_policy"] = freshness
    return resource


def _validate_observation(
    value: object,
    *,
    resource_id: str,
    resource: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    observation = _exact(value, OBSERVATION_FIELDS, "Resource observation", code=E_DIGEST)
    if observation["resource_id"] != resource_id:
        raise _error(E_DIGEST, "Resource observation identity differs")
    if observation["observed_revision"] != resource["revision"]:
        raise _error(E_DIGEST, "Resource observation revision differs")
    if not is_sha256(observation["observed_sha256"]):
        raise _error(E_DIGEST, "Resource observed_sha256 is invalid")
    fetched_at = require_utc_timestamp(
        observation["fetched_at"],
        error=lambda message: _error(E_STALE, message),
        label="Resource observation fetched_at",
    )
    if observation["permission_ref"] != resource["permission_ref"]:
        raise _error(E_PERMISSION, "Resource permission binding differs")
    producer_receipt = observation["producer_receipt_sha256"]
    if producer_receipt is not None and not is_sha256(producer_receipt):
        raise _error(E_DIGEST, "producer_receipt_sha256 is invalid")
    if resource["resource_type"] == "upstream_artifact" and producer_receipt is None:
        raise _error(E_DIGEST, "upstream Resource requires producer receipt")
    policy = resource["freshness_policy"]
    observed_time = timestamp_value(observed_at)
    fetched_time = timestamp_value(fetched_at)
    age = (observed_time - fetched_time).total_seconds()
    if age < 0:
        raise _error(E_STALE, "Resource observation is from the future")
    if policy["mode"] == "max_age" and age > policy["max_age_seconds"]:
        raise _error(E_STALE, "Resource observation exceeds max_age policy")
    return observation


def _decode_payload(value: object, resource_id: str) -> bytes:
    if not isinstance(value, bytes):
        raise _error(E_DIGEST, f"Resource {resource_id} payload must be bytes")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error(E_DIGEST, f"Resource {resource_id} payload must be UTF-8") from exc
    return value


def _compile_resource(
    resource: Mapping[str, Any],
    payload: bytes,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    if observation["observed_sha256"] != digest:
        raise _error(E_DIGEST, "Resource payload and observation digest differ")
    if resource["expected_sha256"] is not None and resource["expected_sha256"] != digest:
        raise _error(E_DIGEST, "Resource payload differs from declared digest")
    estimated_tokens = (len(payload) + 3) // 4
    if estimated_tokens > resource["token_budget"]:
        raise _error(E_TOKEN, "Resource exceeds its declared token budget")
    return {
        "resource_id": resource["resource_id"],
        "resource_type": resource["resource_type"],
        "source_ref": resource["source_ref"],
        "revision": resource["revision"],
        "sha256": digest,
        "bytes": len(payload),
        "estimated_tokens": estimated_tokens,
        "freshness_state": "current",
        "sensitivity": resource["sensitivity"],
        "permission_ref": resource["permission_ref"],
        "producer_node_id": resource["producer_node_id"],
        "producer_receipt_sha256": observation["producer_receipt_sha256"],
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }


def _validated_capsule(value: Mapping[str, Any]) -> dict[str, Any]:
    capsule = _exact(value, CAPSULE_FIELDS, "Review Capsule", code=E_CAPSULE)
    if capsule["schema_version"] != "goal-teams-review-capsule-v2.65":
        raise _error(E_CAPSULE, "Review Capsule schema_version differs")
    _required_string(capsule["capsule_id"], "capsule_id", code=E_CAPSULE)
    capsule["source_review_ids"] = _strings(
        capsule["source_review_ids"], "source_review_ids", code=E_CAPSULE, non_empty=True
    )
    capsule["source_review_sha256s"] = _strings(
        capsule["source_review_sha256s"],
        "source_review_sha256s",
        code=E_CAPSULE,
        non_empty=True,
        set_like=False,
    )
    if len(capsule["source_review_ids"]) != len(capsule["source_review_sha256s"]):
        raise _error(E_CAPSULE, "Review Capsule source lists differ in length")
    if any(not is_sha256(item) for item in capsule["source_review_sha256s"]):
        raise _error(E_CAPSULE, "Review Capsule source digest is invalid")
    for field in (
        "retained_practices",
        "active_adjustments",
        "open_gaps",
        "forbidden_retries",
        "required_evidence",
    ):
        capsule[field] = _strings(capsule[field], field, code=E_CAPSULE)
    capsule["compiled_at"] = require_utc_timestamp(
        capsule["compiled_at"], error=lambda message: _error(E_CAPSULE, message), label="compiled_at"
    )
    _require_self_digest(capsule, "capsule_sha256", code=E_CAPSULE, label="Review Capsule")
    return capsule


def compile_review_capsule(
    reviews: Sequence[Mapping[str, Any]],
    *,
    capsule_id: str,
    active_review_ids: Sequence[str],
    max_items: int,
    max_bytes: int,
    compiled_at: str,
) -> dict[str, Any]:
    """Compile only explicitly selected signed Review fields into a capsule."""

    capsule_id = _required_string(capsule_id, "capsule_id", code=E_CAPSULE)
    if not is_int(max_items, minimum=1) or not is_int(max_bytes, minimum=1):
        raise _error(E_CAPSULE_BUDGET, "Review Capsule budgets must be positive integers")
    compiled_at = require_utc_timestamp(
        compiled_at, error=lambda message: _error(E_CAPSULE, message), label="compiled_at"
    )
    if not isinstance(reviews, Sequence) or isinstance(reviews, (str, bytes, bytearray)):
        raise _error(E_CAPSULE, "reviews must be a sequence")
    try:
        from scripts.v265.loop_review import LoopReviewError, validate_loop_review

        validated_reviews = [validate_loop_review(review) for review in reviews]
    except (LoopReviewError, TypeError, ValueError, CanonicalValueError) as exc:
        raise _error(E_CAPSULE, "Review Capsule source is unsigned or invalid") from exc
    by_id: dict[str, dict[str, Any]] = {}
    for review in validated_reviews:
        if review["review_id"] in by_id:
            raise _error(E_CAPSULE, "Review Capsule source repeats a Review ID")
        by_id[review["review_id"]] = review
    selected_ids = _strings(
        list(active_review_ids),
        "active_review_ids",
        code=E_CAPSULE,
        non_empty=True,
    )
    if any(review_id not in by_id for review_id in selected_ids):
        raise _error(E_CAPSULE, "Review Capsule selected source is absent")
    selected = [by_id[review_id] for review_id in selected_ids]
    identity = {
        (review["project_id"], review["artifact_version"], review["skill_version"])
        for review in selected
    }
    if len(identity) != 1:
        raise _error(E_CAPSULE, "Review Capsule crosses project, artifact, or Skill identity")

    retained: set[str] = set()
    adjustments: set[str] = set()
    gaps: set[str] = set()
    forbidden_retries: set[str] = set()
    required_evidence: set[str] = set()
    for review in selected:
        retained.update(review["retained_practices"])
        gaps.update(review["loop_result"]["open_gaps"])
        for dimension in review["dimensions"].values():
            if dimension["state"] == "candidate":
                adjustments.add(dimension["improvement"])
                required_evidence.add(dimension["validation_method"])
        candidate = review["candidate"]
        if candidate is not None:
            required_evidence.add(candidate["validation_plan"])
        if review["review_outcome"] in {"rejected", "blocked"}:
            forbidden_retries.add(review["issue_fingerprint"])

    capsule: dict[str, Any] = {
        "schema_version": "goal-teams-review-capsule-v2.65",
        "capsule_id": capsule_id,
        "source_review_ids": selected_ids,
        "source_review_sha256s": [by_id[review_id]["review_sha256"] for review_id in selected_ids],
        "retained_practices": sorted(retained),
        "active_adjustments": sorted(adjustments),
        "open_gaps": sorted(gaps),
        "forbidden_retries": sorted(forbidden_retries),
        "required_evidence": sorted(required_evidence),
        "compiled_at": compiled_at,
    }
    item_count = sum(
        len(capsule[field])
        for field in (
            "retained_practices",
            "active_adjustments",
            "open_gaps",
            "forbidden_retries",
            "required_evidence",
        )
    )
    if item_count > max_items:
        raise _error(E_CAPSULE_BUDGET, "Review Capsule exceeds its item budget")
    capsule["capsule_sha256"] = canonical_sha256(capsule)
    if len(canonical_json_bytes(capsule)) > max_bytes:
        raise _error(E_CAPSULE_BUDGET, "Review Capsule exceeds its byte budget")
    return _validated_capsule(capsule)


def compile_context_bundle(
    *,
    bundle_id: str,
    compiled_graph: Mapping[str, Any],
    node_id: str,
    resource_payloads: Mapping[str, bytes],
    resource_observations: Mapping[str, Mapping[str, Any]],
    review_capsule: Mapping[str, Any] | None,
    compiled_at: str,
) -> dict[str, Any]:
    """Compile the exact declared Context bytes for one Graph Node."""

    bundle_id = _required_string(bundle_id, "bundle_id", code=E_DIGEST)
    node_id = _required_string(node_id, "node_id", code=E_DIGEST)
    compiled_at = require_utc_timestamp(
        compiled_at, error=lambda message: _error(E_STALE, message), label="compiled_at"
    )
    graph, node_by_id, resource_by_id = _validated_graph(compiled_graph)
    if node_id not in node_by_id:
        raise _error(E_UNDECLARED, "Context Node is absent from compiled Graph")
    node = node_by_id[node_id]
    refs = node["resource_refs"]
    required_ids = set(refs["required"])
    forbidden_ids = set(refs["forbidden"])
    allowed_ids = set().union(
        refs["required"], refs["recommended"], refs["generated"], refs["upstream_artifacts"]
    )
    if any(resource_id not in resource_by_id for resource_id in allowed_ids | forbidden_ids):
        raise _error(E_UNDECLARED, "Node references an absent Resource declaration")
    if any(
        node_id not in resource_by_id[resource_id]["consumer_node_ids"]
        for resource_id in allowed_ids
    ):
        raise _error(E_UNDECLARED, "Resource consumer binding differs from Context Node")
    if not isinstance(resource_payloads, Mapping) or not isinstance(resource_observations, Mapping):
        raise _error(E_DIGEST, "Resource payloads and observations must be mappings")
    payload_ids = set(resource_payloads)
    observation_ids = set(resource_observations)
    if not all(isinstance(item, str) and item for item in payload_ids | observation_ids):
        raise _error(E_UNDECLARED, "Resource mapping key is invalid")
    if payload_ids != observation_ids:
        raise _error(E_DIGEST, "Resource payload and observation exact sets differ")
    if payload_ids & forbidden_ids:
        raise _error(E_FORBIDDEN, "forbidden Context Resource was supplied")
    if payload_ids - allowed_ids:
        raise _error(E_UNDECLARED, "undeclared Context Resource was supplied")

    capsule: dict[str, Any] | None = None
    capsule_resource_ids = {
        resource_id
        for resource_id in allowed_ids
        if resource_by_id[resource_id]["resource_type"] == "review_capsule"
    }
    if review_capsule is not None:
        capsule = _validated_capsule(review_capsule)
        if len(capsule_resource_ids) != 1:
            raise _error(E_CAPSULE, "Review Capsule must bind exactly one declared Resource")
        capsule_resource_id = next(iter(capsule_resource_ids))
        capsule_payload = canonical_json_bytes(capsule)
        if capsule_resource_id in payload_ids:
            if resource_payloads[capsule_resource_id] != capsule_payload:
                raise _error(E_CAPSULE, "Review Capsule Resource bytes differ")
        else:
            resource_payloads = dict(resource_payloads)
            resource_observations = dict(resource_observations)
            declaration = resource_by_id[capsule_resource_id]
            resource_payloads[capsule_resource_id] = capsule_payload
            resource_observations[capsule_resource_id] = {
                "resource_id": capsule_resource_id,
                "observed_revision": declaration["revision"],
                "observed_sha256": hashlib.sha256(capsule_payload).hexdigest(),
                "fetched_at": capsule["compiled_at"],
                "permission_ref": declaration["permission_ref"],
                "producer_receipt_sha256": capsule["capsule_sha256"],
            }
            payload_ids.add(capsule_resource_id)
            observation_ids.add(capsule_resource_id)
    elif required_ids & capsule_resource_ids:
        raise _error(E_MISSING, "required Review Capsule Resource is absent")

    missing = required_ids - payload_ids
    if missing:
        raise _error(E_MISSING, f"required Context Resources are absent: {sorted(missing)}")
    compiled_resources: list[dict[str, Any]] = []
    for resource_id in sorted(payload_ids):
        resource = resource_by_id[resource_id]
        payload = _decode_payload(resource_payloads[resource_id], resource_id)
        observation = _validate_observation(
            resource_observations[resource_id],
            resource_id=resource_id,
            resource=resource,
            observed_at=compiled_at,
        )
        compiled_resources.append(_compile_resource(resource, payload, observation))
    total_bytes = sum(resource["bytes"] for resource in compiled_resources)
    estimated_tokens = sum(resource["estimated_tokens"] for resource in compiled_resources)
    if estimated_tokens > node["budget"]["context_tokens"]:
        raise _error(E_TOKEN, "Context Bundle exceeds the Node token budget")
    bundle: dict[str, Any] = {
        "schema_version": "goal-teams-context-bundle-v2.65",
        "bundle_id": bundle_id,
        "graph_contract_sha256": graph["receipt_sha256"],
        "node_id": node_id,
        "resources": compiled_resources,
        "review_capsule_sha256": None if capsule is None else capsule["capsule_sha256"],
        "total_bytes": total_bytes,
        "estimated_tokens": estimated_tokens,
        "token_estimate_algorithm": "utf8_bytes_ceiling_div4",
        "compiled_at": compiled_at,
    }
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    return copy.deepcopy(bundle)


def _decode_compiled_resource(value: object) -> tuple[dict[str, Any], bytes]:
    resource = _exact(value, COMPILED_RESOURCE_FIELDS, "compiled Context Resource", code=E_DIGEST)
    for field in ("resource_id", "resource_type", "source_ref", "revision", "sensitivity", "permission_ref"):
        _required_string(resource[field], f"compiled Resource.{field}", code=E_DIGEST)
    if not is_sha256(resource["sha256"]):
        raise _error(E_DIGEST, "compiled Resource digest is invalid")
    if not is_int(resource["bytes"], minimum=0) or not is_int(resource["estimated_tokens"], minimum=0):
        raise _error(E_DIGEST, "compiled Resource byte/token count is invalid")
    if resource["freshness_state"] != "current":
        raise _error(E_STALE, "compiled Resource freshness is not current")
    if resource["producer_node_id"] is not None and not is_non_empty_string(resource["producer_node_id"]):
        raise _error(E_DIGEST, "compiled Resource producer is invalid")
    if resource["producer_receipt_sha256"] is not None and not is_sha256(
        resource["producer_receipt_sha256"]
    ):
        raise _error(E_DIGEST, "compiled Resource producer receipt is invalid")
    if not isinstance(resource["content_base64"], str):
        raise _error(E_DIGEST, "compiled Resource content_base64 is invalid")
    try:
        payload = base64.b64decode(resource["content_base64"], validate=True)
        payload.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise _error(E_DIGEST, "compiled Resource content is not canonical UTF-8 base64") from exc
    if base64.b64encode(payload).decode("ascii") != resource["content_base64"]:
        raise _error(E_DIGEST, "compiled Resource base64 is not canonical")
    if (
        len(payload) != resource["bytes"]
        or hashlib.sha256(payload).hexdigest() != resource["sha256"]
        or (len(payload) + 3) // 4 != resource["estimated_tokens"]
    ):
        raise _error(E_DIGEST, "compiled Resource content binding differs")
    return resource, payload


def validate_context_bundle(
    bundle: Mapping[str, Any],
    *,
    compiled_graph: Mapping[str, Any],
    node_id: str,
    validated_at: str,
) -> dict[str, Any]:
    """Rebuild a Context Bundle's declarations, bytes and budget bindings."""

    graph, node_by_id, resource_by_id = _validated_graph(compiled_graph)
    node_id = _required_string(node_id, "node_id", code=E_DIGEST)
    if node_id not in node_by_id:
        raise _error(E_UNDECLARED, "Context Node is absent from compiled Graph")
    candidate = _exact(bundle, BUNDLE_FIELDS, "Context Bundle", code=E_DIGEST)
    if candidate["schema_version"] != "goal-teams-context-bundle-v2.65":
        raise _error(E_DIGEST, "Context Bundle schema_version differs")
    _required_string(candidate["bundle_id"], "bundle_id", code=E_DIGEST)
    if candidate["graph_contract_sha256"] != graph["receipt_sha256"] or candidate["node_id"] != node_id:
        raise _error(E_DIGEST, "Context Bundle Graph or Node binding differs")
    if candidate["token_estimate_algorithm"] != "utf8_bytes_ceiling_div4":
        raise _error(E_DIGEST, "Context Bundle token estimate algorithm differs")
    candidate["compiled_at"] = require_utc_timestamp(
        candidate["compiled_at"], error=lambda message: _error(E_STALE, message), label="compiled_at"
    )
    validated_at = require_utc_timestamp(
        validated_at, error=lambda message: _error(E_STALE, message), label="validated_at"
    )
    if timestamp_value(validated_at) < timestamp_value(candidate["compiled_at"]):
        raise _error(E_STALE, "Context validation predates compilation")
    _require_self_digest(candidate, "bundle_sha256", code=E_DIGEST, label="Context Bundle")
    if not isinstance(candidate["resources"], list):
        raise _error(E_DIGEST, "Context Bundle resources must be an array")
    compiled_resources: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    for raw_resource in candidate["resources"]:
        compiled, payload = _decode_compiled_resource(raw_resource)
        resource_id = compiled["resource_id"]
        if resource_id in payloads:
            raise _error(E_DIGEST, "Context Bundle repeats a Resource ID")
        payloads[resource_id] = payload
        compiled_resources.append(compiled)
    if [item["resource_id"] for item in compiled_resources] != sorted(payloads):
        raise _error(E_DIGEST, "Context Bundle Resources are not in lexical order")
    node = node_by_id[node_id]
    refs = node["resource_refs"]
    allowed_ids = set().union(
        refs["required"], refs["recommended"], refs["generated"], refs["upstream_artifacts"]
    )
    supplied_ids = set(payloads)
    if supplied_ids & set(refs["forbidden"]):
        raise _error(E_FORBIDDEN, "Context Bundle contains a forbidden Resource")
    if supplied_ids - allowed_ids:
        raise _error(E_UNDECLARED, "Context Bundle contains an undeclared Resource")
    if set(refs["required"]) - supplied_ids:
        raise _error(E_MISSING, "Context Bundle omits a required Resource")
    for compiled in compiled_resources:
        declaration = resource_by_id.get(compiled["resource_id"])
        if declaration is None:
            raise _error(E_UNDECLARED, "Context Bundle Resource declaration is absent")
        expected = {
            "resource_type": declaration["resource_type"],
            "source_ref": declaration["source_ref"],
            "revision": declaration["revision"],
            "sensitivity": declaration["sensitivity"],
            "permission_ref": declaration["permission_ref"],
            "producer_node_id": declaration["producer_node_id"],
        }
        if any(compiled[field] != value for field, value in expected.items()):
            raise _error(E_PERMISSION, "compiled Resource declaration or permission differs")
        if declaration["expected_sha256"] is not None and compiled["sha256"] != declaration["expected_sha256"]:
            raise _error(E_DIGEST, "compiled Resource differs from expected digest")
        if compiled["estimated_tokens"] > declaration["token_budget"]:
            raise _error(E_TOKEN, "compiled Resource exceeds its token budget")
        if (
            declaration["resource_type"] == "upstream_artifact"
            and compiled["producer_receipt_sha256"] is None
        ):
            raise _error(E_DIGEST, "upstream Resource producer receipt is absent")
        policy = declaration["freshness_policy"]
        if policy["mode"] == "max_age":
            elapsed = (
                timestamp_value(validated_at) - timestamp_value(candidate["compiled_at"])
            ).total_seconds()
            if elapsed > policy["max_age_seconds"]:
                raise _error(E_STALE, "Context Resource expired after compilation")
    total_bytes = sum(resource["bytes"] for resource in compiled_resources)
    estimated_tokens = sum(resource["estimated_tokens"] for resource in compiled_resources)
    if candidate["total_bytes"] != total_bytes or candidate["estimated_tokens"] != estimated_tokens:
        raise _error(E_DIGEST, "Context Bundle aggregate counts differ")
    if estimated_tokens > node["budget"]["context_tokens"]:
        raise _error(E_TOKEN, "Context Bundle exceeds the Node token budget")
    review_resources = [
        resource for resource in compiled_resources if resource["resource_type"] == "review_capsule"
    ]
    if candidate["review_capsule_sha256"] is None:
        if review_resources:
            raise _error(E_CAPSULE, "Context Bundle omits its Review Capsule binding")
    else:
        if not is_sha256(candidate["review_capsule_sha256"]) or len(review_resources) != 1:
            raise _error(E_CAPSULE, "Context Bundle Review Capsule binding differs")
        try:
            capsule_object = parse_json_bytes(
                payloads[review_resources[0]["resource_id"]]
            )
            capsule = _validated_capsule(capsule_object)
        except (ValueError, CanonicalValueError, ContextCompilerError) as exc:
            raise _error(E_CAPSULE, "embedded Review Capsule is invalid") from exc
        if capsule["capsule_sha256"] != candidate["review_capsule_sha256"]:
            raise _error(E_CAPSULE, "embedded Review Capsule digest differs")
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-context-validation-receipt-v2.65",
        "bundle_id": candidate["bundle_id"],
        "node_id": node_id,
        "graph_contract_sha256": candidate["graph_contract_sha256"],
        "bundle_sha256": candidate["bundle_sha256"],
        "valid": True,
        "validator": "scripts.v265.context_compiler.validate_context_bundle",
        "validated_at": validated_at,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt
