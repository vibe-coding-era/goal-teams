"""Compile and validate the static V2.65 typed Graph contract.

The compiler is intentionally pure: it validates immutable TaskExactSet
bindings and emits deterministic maps consumed by the runtime, but it neither
mutates runtime state nor invokes a Host adapter.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from scripts.v250.task_plan_compiler import TaskPlanError, validate_compiled_task_plan
from scripts.v265.canonical import (
    CanonicalValueError,
    canonical_json_bytes,
    canonical_sha256,
    exact_mapping,
    is_int,
    is_json_scalar,
    is_non_empty_string,
    is_sha256,
    unique_string_list,
)


class GraphContractError(ValueError):
    """A Graph contract cannot be compiled without weakening its bindings."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


E_SCHEMA = "E_V265_GRAPH_SCHEMA"
E_BINDING = "E_V265_GRAPH_BINDING"
E_TASK_COVERAGE = "E_V265_GRAPH_TASK_COVERAGE"
E_OWNER_VALIDATOR = "E_V265_GRAPH_OWNER_VALIDATOR"
E_TASK_BINDING = "E_V265_GRAPH_TASK_BINDING"
E_DUPLICATE = "E_V265_GRAPH_DUPLICATE_ID"
E_EDGE_ENDPOINT = "E_V265_GRAPH_EDGE_ENDPOINT"
E_EDGE_TYPE = "E_V265_GRAPH_EDGE_TYPE"
E_CYCLE = "E_V265_GRAPH_CYCLE"
E_FAN_IN = "E_V265_GRAPH_FAN_IN"
E_DATA = "E_V265_GRAPH_DATA_BINDING"
E_GATE = "E_V265_GRAPH_GATE_BINDING"
E_ACTION = "E_V265_GRAPH_ACTION_BINDING"
E_RESOURCE = "E_V265_GRAPH_RESOURCE_BINDING"
E_TRAVERSAL = "E_V265_GRAPH_TRAVERSAL_BUDGET"
E_RECEIPT = "E_V265_GRAPH_RECEIPT_INVALID"


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
GRAPH_DERIVED_FIELDS = frozenset(
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
PLAN_BINDING_FIELDS = frozenset(
    {
        "plan_id",
        "plan_revision",
        "task_exact_set_sha256",
        "compiled_task_plan_sha256",
        "task_plan_validation_sha256",
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
INPUT_PORT_FIELDS = frozenset({"port_id", "schema_ref", "required", "sensitivity"})
OUTPUT_PORT_FIELDS = frozenset(INPUT_PORT_FIELDS | {"consumer_node_ids"})
BUDGET_FIELDS = frozenset(
    {"work_units", "attempts", "revalidations", "context_tokens"}
)
RETRY_FIELDS = frozenset(
    {"max_attempts", "retryable_outcomes", "backoff_seconds"}
)
RECOVERY_FIELDS = frozenset({"mode", "edge_id"})
FAN_IN_FIELDS = frozenset(
    {"mode", "edge_ids", "quorum_count", "quorum_ratio_basis_points"}
)
EDGE_FIELDS = frozenset(
    {
        "edge_id",
        "edge_type",
        "source_node_id",
        "target_node_id",
        "accepted_outcomes",
        "gate_ref",
        "data_bindings",
        "traversal_budget",
    }
)
DATA_BINDING_FIELDS = frozenset(
    {"output_port_id", "input_port_id", "schema_ref"}
)
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
GATE_FIELDS = frozenset(
    {
        "gate_id",
        "gate_type",
        "authority_ref",
        "required_evidence_types",
        "condition",
        "timeout_seconds",
        "on_timeout_outcome",
    }
)
CONDITION_FIELDS = frozenset({"fact_ref", "operator", "expected_value"})
ACTION_FIELDS = frozenset(
    {
        "action_id",
        "runner",
        "effect",
        "tool_allowlist",
        "network_policy",
        "workspace_policy",
        "input_schema_ref",
        "output_schema_ref",
        "idempotency_required",
    }
)

NODE_TYPES = frozenset({"action", "validation", "human_gate", "terminal"})
EDGE_TYPES = frozenset(
    {
        "dependency",
        "data",
        "success",
        "failure",
        "blocked",
        "unverified",
        "repeat",
        "human_approved",
        "recovery",
        "supersedes",
    }
)
FORWARD_EDGE_TYPES = frozenset(
    {
        "dependency",
        "data",
        "success",
        "failure",
        "blocked",
        "unverified",
        "human_approved",
    }
)
CONTROL_EDGE_TYPES = FORWARD_EDGE_TYPES - {"data"}
TERMINAL_OUTCOMES = frozenset(
    {
        "completed",
        "partial",
        "failed",
        "unverified",
        "skipped",
        "blocked",
        "cancelled",
        "stale",
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
PHASES = ("development", "runtime", "release")


def _error(code: str, message: str) -> GraphContractError:
    return GraphContractError(code, message)


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
    code: str = E_SCHEMA,
    non_empty: bool = False,
    ordered: bool = False,
) -> list[str]:
    return unique_string_list(
        value,
        error=lambda message: _error(code, message),
        label=label,
        non_empty=non_empty,
        sort_output=not ordered,
    )


def _required_string(value: object, label: str, *, code: str = E_SCHEMA) -> str:
    if not is_non_empty_string(value):
        raise _error(code, f"{label} must be a non-empty string")
    return str(value)


def _ensure_unique(records: list[dict[str, Any]], field: str, label: str) -> None:
    ids = [record[field] for record in records]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise _error(E_DUPLICATE, f"duplicate {label} IDs: {', '.join(duplicates)}")


def _validated_plan(
    compiled_task_plan: Mapping[str, Any],
    task_plan_validation_receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(compiled_task_plan, Mapping) or not isinstance(
        task_plan_validation_receipt, Mapping
    ):
        raise _error(E_BINDING, "compiled plan and validation receipt are required")
    try:
        rebuilt = validate_compiled_task_plan(compiled_task_plan)
        supplied_bytes = canonical_json_bytes(dict(task_plan_validation_receipt))
        rebuilt_bytes = canonical_json_bytes(rebuilt)
    except (TaskPlanError, CanonicalValueError) as exc:
        raise _error(E_BINDING, "V2.63 task plan validation failed") from exc
    if supplied_bytes != rebuilt_bytes:
        raise _error(E_BINDING, "task plan validation receipt differs from recomputation")
    return copy.deepcopy(dict(compiled_task_plan)), copy.deepcopy(rebuilt)


def _normalize_plan_binding(
    value: object,
    compiled_plan: Mapping[str, Any],
    plan_validation: Mapping[str, Any],
) -> dict[str, Any]:
    binding = _exact(value, PLAN_BINDING_FIELDS, "plan_binding")
    expected = {
        "plan_id": compiled_plan["plan_id"],
        "plan_revision": compiled_plan["plan_revision"],
        "task_exact_set_sha256": compiled_plan["task_exact_set_digest"],
        "compiled_task_plan_sha256": compiled_plan["receipt_digest"],
        "task_plan_validation_sha256": plan_validation["receipt_digest"],
    }
    if binding != expected:
        raise _error(E_BINDING, "plan_binding differs from the validated V2.63 plan")
    return expected


def _normalize_intrinsic_plan_binding(value: object) -> dict[str, Any]:
    """Normalize only the self-contained identity fields of a plan binding."""

    binding = _exact(value, PLAN_BINDING_FIELDS, "plan_binding")
    plan_id = _required_string(binding["plan_id"], "plan_binding.plan_id")
    if not is_int(binding["plan_revision"], minimum=1):
        raise _error(E_BINDING, "plan_binding.plan_revision must be positive")
    for field in (
        "task_exact_set_sha256",
        "compiled_task_plan_sha256",
        "task_plan_validation_sha256",
    ):
        if not is_sha256(binding[field]):
            raise _error(E_BINDING, f"plan_binding.{field} is invalid")
    return {
        "plan_id": plan_id,
        "plan_revision": binding["plan_revision"],
        "task_exact_set_sha256": binding["task_exact_set_sha256"],
        "compiled_task_plan_sha256": binding["compiled_task_plan_sha256"],
        "task_plan_validation_sha256": binding["task_plan_validation_sha256"],
    }


def _normalize_port(
    value: object,
    *,
    output: bool,
    node_id: str,
    index: int,
) -> dict[str, Any]:
    label = f"node {node_id} {'output' if output else 'input'} port {index}"
    port = _exact(value, OUTPUT_PORT_FIELDS if output else INPUT_PORT_FIELDS, label)
    result = {
        "port_id": _required_string(port["port_id"], f"{label}.port_id"),
        "schema_ref": _required_string(port["schema_ref"], f"{label}.schema_ref"),
        "required": port["required"],
        "sensitivity": port["sensitivity"],
    }
    if type(result["required"]) is not bool:
        raise _error(E_SCHEMA, f"{label}.required must be boolean")
    if result["sensitivity"] not in SENSITIVITIES:
        raise _error(E_SCHEMA, f"{label}.sensitivity is invalid")
    if output:
        result["consumer_node_ids"] = _strings(
            port["consumer_node_ids"], f"{label}.consumer_node_ids"
        )
    return result


def _normalize_node(value: object, index: int) -> dict[str, Any]:
    node = _exact(value, NODE_FIELDS, f"node {index}")
    node_id = _required_string(node["node_id"], f"node {index}.node_id")
    task_refs = _strings(node["task_refs"], f"node {node_id}.task_refs", non_empty=True)
    if len(task_refs) != 1:
        raise _error(E_TASK_COVERAGE, f"node {node_id} must bind exactly one task")
    node_type = node["node_type"]
    if node_type not in NODE_TYPES:
        raise _error(E_SCHEMA, f"node {node_id}.node_type is invalid")

    resource_refs = _exact(
        node["resource_refs"], RESOURCE_REF_FIELDS, f"node {node_id}.resource_refs"
    )
    normalized_resource_refs = {
        key: _strings(
            resource_refs[key], f"node {node_id}.resource_refs.{key}"
        )
        for key in sorted(RESOURCE_REF_FIELDS)
    }
    flattened = [item for values in normalized_resource_refs.values() for item in values]
    if len(flattened) != len(set(flattened)):
        raise _error(E_RESOURCE, f"node {node_id} resource reference sets overlap")

    raw_inputs = node["input_ports"]
    raw_outputs = node["output_ports"]
    if not isinstance(raw_inputs, list) or not isinstance(raw_outputs, list):
        raise _error(E_SCHEMA, f"node {node_id} ports must be arrays")
    input_ports = [
        _normalize_port(item, output=False, node_id=node_id, index=port_index)
        for port_index, item in enumerate(raw_inputs)
    ]
    output_ports = [
        _normalize_port(item, output=True, node_id=node_id, index=port_index)
        for port_index, item in enumerate(raw_outputs)
    ]
    for ports, direction in ((input_ports, "input"), (output_ports, "output")):
        port_ids = [port["port_id"] for port in ports]
        if len(port_ids) != len(set(port_ids)):
            raise _error(E_DATA, f"node {node_id} repeats a {direction} port ID")
        ports.sort(key=lambda item: item["port_id"])

    budget = _exact(node["budget"], BUDGET_FIELDS, f"node {node_id}.budget")
    if not is_int(budget["work_units"], minimum=1):
        raise _error(E_SCHEMA, f"node {node_id} work_units must be positive")
    if not is_int(budget["attempts"], minimum=1):
        raise _error(E_SCHEMA, f"node {node_id} attempts must be positive")
    if not is_int(budget["revalidations"], minimum=0):
        raise _error(E_SCHEMA, f"node {node_id} revalidations must be non-negative")
    if not is_int(budget["context_tokens"], minimum=1):
        raise _error(E_SCHEMA, f"node {node_id} context_tokens must be positive")

    retry = _exact(node["retry_policy"], RETRY_FIELDS, f"node {node_id}.retry_policy")
    if not is_int(retry["max_attempts"], minimum=1):
        raise _error(E_SCHEMA, f"node {node_id} max_attempts must be positive")
    retryable_outcomes = _strings(
        retry["retryable_outcomes"],
        f"node {node_id}.retry_policy.retryable_outcomes",
    )
    if not set(retryable_outcomes) <= TERMINAL_OUTCOMES:
        raise _error(E_SCHEMA, f"node {node_id} has an invalid retryable outcome")
    backoff = retry["backoff_seconds"]
    if not isinstance(backoff, list) or any(
        not is_int(item, minimum=0) for item in backoff
    ):
        raise _error(E_SCHEMA, f"node {node_id} backoff_seconds is invalid")
    if retry["max_attempts"] != budget["attempts"] or len(backoff) != budget[
        "attempts"
    ] - 1:
        raise _error(E_TASK_BINDING, f"node {node_id} retry budget is inconsistent")

    recovery = _exact(
        node["recovery_policy"], RECOVERY_FIELDS, f"node {node_id}.recovery_policy"
    )
    if recovery["mode"] not in {"none", "retry", "edge"}:
        raise _error(E_TRAVERSAL, f"node {node_id} recovery mode is invalid")
    if recovery["mode"] == "edge":
        recovery["edge_id"] = _required_string(
            recovery["edge_id"], f"node {node_id}.recovery_policy.edge_id", code=E_TRAVERSAL
        )
    elif recovery["edge_id"] is not None:
        raise _error(E_TRAVERSAL, f"node {node_id} recovery edge must be null")

    fan_in: dict[str, Any] | None
    if node["fan_in"] is None:
        fan_in = None
    else:
        fan_in = _exact(node["fan_in"], FAN_IN_FIELDS, f"node {node_id}.fan_in")
        if fan_in["mode"] not in {"all", "any", "quorum"}:
            raise _error(E_FAN_IN, f"node {node_id} fan-in mode is invalid")
        fan_in["edge_ids"] = _strings(
            fan_in["edge_ids"], f"node {node_id}.fan_in.edge_ids", code=E_FAN_IN, non_empty=True
        )

    if not is_int(node["timeout_seconds"], minimum=1):
        raise _error(E_SCHEMA, f"node {node_id}.timeout_seconds must be positive")

    return {
        "node_id": node_id,
        "task_refs": task_refs,
        "node_type": node_type,
        "owner_identity": _required_string(
            node["owner_identity"], f"node {node_id}.owner_identity"
        ),
        "validator_identity": _required_string(
            node["validator_identity"], f"node {node_id}.validator_identity"
        ),
        "action_ref": _required_string(node["action_ref"], f"node {node_id}.action_ref"),
        "resource_refs": normalized_resource_refs,
        "input_ports": input_ports,
        "output_ports": output_ports,
        "scope_allowlist": _strings(
            node["scope_allowlist"], f"node {node_id}.scope_allowlist", non_empty=True
        ),
        "forbidden_scope": _strings(
            node["forbidden_scope"], f"node {node_id}.forbidden_scope"
        ),
        "budget": {
            "work_units": budget["work_units"],
            "attempts": budget["attempts"],
            "revalidations": budget["revalidations"],
            "context_tokens": budget["context_tokens"],
        },
        "timeout_seconds": node["timeout_seconds"],
        "retry_policy": {
            "max_attempts": retry["max_attempts"],
            "retryable_outcomes": retryable_outcomes,
            "backoff_seconds": list(backoff),
        },
        "gate_refs": _strings(node["gate_refs"], f"node {node_id}.gate_refs"),
        "exit_condition_ref": _required_string(
            node["exit_condition_ref"], f"node {node_id}.exit_condition_ref"
        ),
        "recovery_policy": recovery,
        "fan_in": fan_in,
    }


def _normalize_data_binding(value: object, edge_id: str, index: int) -> dict[str, Any]:
    item = _exact(
        value,
        DATA_BINDING_FIELDS,
        f"edge {edge_id} data binding {index}",
    )
    return {
        field: _required_string(
            item[field], f"edge {edge_id} data binding {index}.{field}", code=E_DATA
        )
        for field in ("output_port_id", "input_port_id", "schema_ref")
    }


def _normalize_edge(value: object, index: int) -> dict[str, Any]:
    edge = _exact(value, EDGE_FIELDS, f"edge {index}")
    edge_id = _required_string(edge["edge_id"], f"edge {index}.edge_id")
    if edge_id.startswith("retry_policy:"):
        raise _error(
            E_TRAVERSAL,
            f"edge {edge_id} uses the reserved Node retry namespace",
        )
    edge_type = edge["edge_type"]
    if edge_type not in EDGE_TYPES:
        raise _error(E_EDGE_TYPE, f"edge {edge_id} has unknown type {edge_type!r}")
    raw_bindings = edge["data_bindings"]
    if not isinstance(raw_bindings, list):
        raise _error(E_SCHEMA, f"edge {edge_id}.data_bindings must be an array")
    bindings = [
        _normalize_data_binding(item, edge_id, item_index)
        for item_index, item in enumerate(raw_bindings)
    ]
    keys = [
        (item["output_port_id"], item["input_port_id"], item["schema_ref"])
        for item in bindings
    ]
    if len(keys) != len(set(keys)):
        raise _error(E_DATA, f"edge {edge_id} repeats a data binding")
    bindings.sort(
        key=lambda item: (
            item["output_port_id"], item["input_port_id"], item["schema_ref"]
        )
    )
    gate_ref = edge["gate_ref"]
    if gate_ref is not None:
        gate_ref = _required_string(gate_ref, f"edge {edge_id}.gate_ref", code=E_GATE)
    if not is_int(edge["traversal_budget"], minimum=0):
        raise _error(E_TRAVERSAL, f"edge {edge_id}.traversal_budget is invalid")
    return {
        "edge_id": edge_id,
        "edge_type": edge_type,
        "source_node_id": _required_string(
            edge["source_node_id"], f"edge {edge_id}.source_node_id", code=E_EDGE_ENDPOINT
        ),
        "target_node_id": _required_string(
            edge["target_node_id"], f"edge {edge_id}.target_node_id", code=E_EDGE_ENDPOINT
        ),
        "accepted_outcomes": _strings(
            edge["accepted_outcomes"], f"edge {edge_id}.accepted_outcomes", code=E_EDGE_TYPE
        ),
        "gate_ref": gate_ref,
        "data_bindings": bindings,
        "traversal_budget": edge["traversal_budget"],
    }


def _normalize_resource(value: object, index: int) -> dict[str, Any]:
    resource = _exact(value, RESOURCE_FIELDS, f"resource {index}")
    resource_id = _required_string(resource["resource_id"], f"resource {index}.resource_id")
    resource_type = resource["resource_type"]
    if resource_type not in RESOURCE_TYPES:
        raise _error(E_RESOURCE, f"resource {resource_id} has an invalid type")
    expected = resource["expected_sha256"]
    if expected is not None and not is_sha256(expected):
        raise _error(E_RESOURCE, f"resource {resource_id} expected_sha256 is invalid")
    freshness = _exact(
        resource["freshness_policy"],
        FRESHNESS_FIELDS,
        f"resource {resource_id}.freshness_policy",
        code=E_RESOURCE,
    )
    mode = freshness["mode"]
    age = freshness["max_age_seconds"]
    if mode not in {"immutable", "max_age", "runtime"}:
        raise _error(E_RESOURCE, f"resource {resource_id} freshness mode is invalid")
    if mode == "immutable" and (not is_sha256(expected) or age is not None):
        raise _error(E_RESOURCE, f"immutable resource {resource_id} needs a digest and null age")
    if mode == "max_age" and not is_int(age, minimum=1):
        raise _error(E_RESOURCE, f"max-age resource {resource_id} needs a positive age")
    if mode == "runtime" and age is not None:
        raise _error(E_RESOURCE, f"runtime resource {resource_id} must have null age")
    if resource["sensitivity"] not in SENSITIVITIES:
        raise _error(E_RESOURCE, f"resource {resource_id} sensitivity is invalid")
    if not is_int(resource["token_budget"], minimum=1):
        raise _error(E_RESOURCE, f"resource {resource_id} token_budget must be positive")
    producer = resource["producer_node_id"]
    if producer is not None:
        producer = _required_string(
            producer, f"resource {resource_id}.producer_node_id", code=E_RESOURCE
        )
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "source_ref": _required_string(
            resource["source_ref"], f"resource {resource_id}.source_ref", code=E_RESOURCE
        ),
        "revision": _required_string(
            resource["revision"], f"resource {resource_id}.revision", code=E_RESOURCE
        ),
        "expected_sha256": expected,
        "schema_ref": _required_string(
            resource["schema_ref"], f"resource {resource_id}.schema_ref", code=E_RESOURCE
        ),
        "freshness_policy": {"mode": mode, "max_age_seconds": age},
        "sensitivity": resource["sensitivity"],
        "permission_ref": _required_string(
            resource["permission_ref"],
            f"resource {resource_id}.permission_ref",
            code=E_RESOURCE,
        ),
        "token_budget": resource["token_budget"],
        "producer_node_id": producer,
        "consumer_node_ids": _strings(
            resource["consumer_node_ids"],
            f"resource {resource_id}.consumer_node_ids",
            code=E_RESOURCE,
        ),
    }


def _normalize_gate(value: object, index: int) -> dict[str, Any]:
    gate = _exact(value, GATE_FIELDS, f"gate {index}")
    gate_id = _required_string(gate["gate_id"], f"gate {index}.gate_id")
    gate_type = gate["gate_type"]
    if gate_type not in {"evidence", "human_approval", "condition"}:
        raise _error(E_GATE, f"gate {gate_id} has an invalid type")
    authority = gate["authority_ref"]
    condition = gate["condition"]
    if gate_type == "human_approval":
        authority = _required_string(
            authority, f"gate {gate_id}.authority_ref", code=E_GATE
        )
        if condition is not None:
            raise _error(E_GATE, f"human gate {gate_id} cannot contain a condition")
    elif authority is not None:
        raise _error(E_GATE, f"non-human gate {gate_id} cannot claim authority")

    normalized_condition: dict[str, Any] | None = None
    if gate_type == "condition":
        normalized_condition = _exact(
            condition, CONDITION_FIELDS, f"gate {gate_id}.condition", code=E_GATE
        )
        normalized_condition["fact_ref"] = _required_string(
            normalized_condition["fact_ref"],
            f"gate {gate_id}.condition.fact_ref",
            code=E_GATE,
        )
        operator = normalized_condition["operator"]
        expected = normalized_condition["expected_value"]
        if operator not in {"equals", "not_equals", "present", "absent"}:
            raise _error(E_GATE, f"gate {gate_id} condition operator is invalid")
        if operator in {"present", "absent"} and expected is not None:
            raise _error(E_GATE, f"gate {gate_id} presence condition expects null")
        if operator in {"equals", "not_equals"} and not is_json_scalar(expected):
            raise _error(E_GATE, f"gate {gate_id} expected_value must be a JSON scalar")
    elif condition is not None:
        raise _error(E_GATE, f"gate {gate_id} condition must be null")
    if not is_int(gate["timeout_seconds"], minimum=1):
        raise _error(E_GATE, f"gate {gate_id} timeout_seconds must be positive")
    if gate["on_timeout_outcome"] not in {
        "blocked",
        "failed",
        "waiting_user",
        "cancelled",
    }:
        raise _error(E_GATE, f"gate {gate_id} timeout outcome is invalid")
    required_evidence_types = _strings(
        gate["required_evidence_types"],
        f"gate {gate_id}.required_evidence_types",
        code=E_GATE,
    )
    if gate_type == "evidence" and not required_evidence_types:
        raise _error(E_GATE, f"evidence gate {gate_id} requires Evidence types")
    if gate_type == "human_approval" and required_evidence_types != [
        "approval_receipt"
    ]:
        raise _error(
            E_GATE,
            f"human gate {gate_id} requires exactly approval_receipt",
        )
    return {
        "gate_id": gate_id,
        "gate_type": gate_type,
        "authority_ref": authority,
        "required_evidence_types": required_evidence_types,
        "condition": normalized_condition,
        "timeout_seconds": gate["timeout_seconds"],
        "on_timeout_outcome": gate["on_timeout_outcome"],
    }


def _normalize_action(value: object, index: int) -> dict[str, Any]:
    action = _exact(value, ACTION_FIELDS, f"action {index}")
    action_id = _required_string(action["action_id"], f"action {index}.action_id")
    if action["runner"] != "host_adapter":
        raise _error(E_ACTION, f"action {action_id} runner must be host_adapter")
    if action["effect"] not in {"read", "local_write", "external_write"}:
        raise _error(E_ACTION, f"action {action_id} effect is invalid")
    if action["network_policy"] not in {"deny", "declared"}:
        raise _error(E_ACTION, f"action {action_id} network policy is invalid")
    if action["workspace_policy"] not in {
        "read_only",
        "node_scope",
        "isolated_worktree",
    }:
        raise _error(E_ACTION, f"action {action_id} workspace policy is invalid")
    if type(action["idempotency_required"]) is not bool:
        raise _error(E_ACTION, f"action {action_id} idempotency flag must be boolean")
    if action["effect"] == "external_write" and not action["idempotency_required"]:
        raise _error(E_ACTION, f"external action {action_id} requires idempotency")
    return {
        "action_id": action_id,
        "runner": "host_adapter",
        "effect": action["effect"],
        "tool_allowlist": _strings(
            action["tool_allowlist"],
            f"action {action_id}.tool_allowlist",
            code=E_ACTION,
            non_empty=True,
        ),
        "network_policy": action["network_policy"],
        "workspace_policy": action["workspace_policy"],
        "input_schema_ref": _required_string(
            action["input_schema_ref"], f"action {action_id}.input_schema_ref", code=E_ACTION
        ),
        "output_schema_ref": _required_string(
            action["output_schema_ref"],
            f"action {action_id}.output_schema_ref",
            code=E_ACTION,
        ),
        "idempotency_required": action["idempotency_required"],
    }


def _validate_task_bindings(
    nodes: list[dict[str, Any]], compiled_plan: Mapping[str, Any]
) -> dict[str, str]:
    tasks = {task["task_id"]: task for task in compiled_plan["tasks"]}
    task_refs = [node["task_refs"][0] for node in nodes]
    if len(task_refs) != len(set(task_refs)) or set(task_refs) != set(tasks):
        raise _error(E_TASK_COVERAGE, "TaskExactSet is not covered exactly once")
    task_node_map: dict[str, str] = {}
    for node in nodes:
        task_id = node["task_refs"][0]
        task = tasks[task_id]
        if (
            node["owner_identity"] == node["validator_identity"]
            or task["owner"] == task["validator"]
            or node["owner_identity"] != task["owner"]
            or node["validator_identity"] != task["validator"]
        ):
            raise _error(
                E_OWNER_VALIDATOR,
                f"node {node['node_id']} owner/validator differs from frozen task",
            )
        expected_scope = sorted(task["scope_allowlist"])
        expected_forbidden = sorted(task["forbidden_scope"])
        expected_budget = (
            task["budget_wu"],
            task["attempt_budget"],
            task["revalidation_budget"],
        )
        actual_budget = (
            node["budget"]["work_units"],
            node["budget"]["attempts"],
            node["budget"]["revalidations"],
        )
        exit_contract = task["exit_condition"]
        expected_exit = exit_contract["exit_id"] if isinstance(exit_contract, Mapping) else exit_contract
        if (
            node["scope_allowlist"] != expected_scope
            or node["forbidden_scope"] != expected_forbidden
            or actual_budget != expected_budget
            or node["exit_condition_ref"] != expected_exit
        ):
            raise _error(E_TASK_BINDING, f"node {node['node_id']} differs from frozen task")
        task_node_map[task_id] = node["node_id"]
    return {task_id: task_node_map[task_id] for task_id in sorted(task_node_map)}


def _intrinsic_task_node_map(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Derive one-to-one Task/Node identity without asserting plan authority."""

    task_node_map: dict[str, str] = {}
    for node in nodes:
        task_id = node["task_refs"][0]
        if task_id in task_node_map:
            raise _error(E_TASK_COVERAGE, f"task {task_id} maps to multiple Nodes")
        if node["owner_identity"] == node["validator_identity"]:
            raise _error(
                E_OWNER_VALIDATOR,
                f"node {node['node_id']} owner and validator must differ",
            )
        task_node_map[task_id] = node["node_id"]
    return {task_id: task_node_map[task_id] for task_id in sorted(task_node_map)}


def _validate_output_consumers(nodes: list[dict[str, Any]]) -> None:
    node_ids = {node["node_id"] for node in nodes}
    for node in nodes:
        for port in node["output_ports"]:
            if any(consumer not in node_ids for consumer in port["consumer_node_ids"]):
                raise _error(E_DATA, f"node {node['node_id']} output consumer is missing")


def _validate_input_port_coverage(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    """Require every inbound port to have the contract's exact Data cardinality."""

    counts: dict[tuple[str, str], int] = {}
    for edge in edges:
        if edge["edge_type"] != "data":
            continue
        target = edge["target_node_id"]
        for binding in edge["data_bindings"]:
            key = (target, binding["input_port_id"])
            counts[key] = counts.get(key, 0) + 1
    for node in nodes:
        for port in node["input_ports"]:
            count = counts.get((node["node_id"], port["port_id"]), 0)
            if (port["required"] and count != 1) or (
                not port["required"] and count > 1
            ):
                raise _error(
                    E_DATA,
                    f"node {node['node_id']} input {port['port_id']} has {count} Data bindings",
                )


def _validate_action_and_gate_refs(
    nodes: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    gates: list[dict[str, Any]],
) -> None:
    action_by_id = {item["action_id"]: item for item in actions}
    gate_by_id = {item["gate_id"]: item for item in gates}
    for node in nodes:
        if node["action_ref"] not in action_by_id:
            raise _error(E_ACTION, f"node {node['node_id']} action is missing")
        for gate_ref in node["gate_refs"]:
            if gate_ref not in gate_by_id:
                raise _error(E_GATE, f"node {node['node_id']} gate {gate_ref} is missing")
        if node["node_type"] == "human_gate" and not any(
            gate_by_id[gate_ref]["gate_type"] == "human_approval"
            for gate_ref in node["gate_refs"]
        ):
            raise _error(E_GATE, f"human node {node['node_id']} lacks a human gate")


def _validate_resource_bindings(
    nodes: list[dict[str, Any]], resources: list[dict[str, Any]]
) -> None:
    node_ids = {node["node_id"] for node in nodes}
    resource_by_id = {item["resource_id"]: item for item in resources}
    derived_consumers: dict[str, set[str]] = {resource_id: set() for resource_id in resource_by_id}
    for node in nodes:
        node_id = node["node_id"]
        refs = node["resource_refs"]
        for category, resource_ids in refs.items():
            for resource_id in resource_ids:
                resource = resource_by_id.get(resource_id)
                if resource is None:
                    raise _error(E_RESOURCE, f"node {node_id} references missing resource {resource_id}")
                if category == "forbidden":
                    if node_id in resource["consumer_node_ids"] or resource[
                        "producer_node_id"
                    ] == node_id:
                        raise _error(E_RESOURCE, f"forbidden resource {resource_id} binds node {node_id}")
                    continue
                derived_consumers[resource_id].add(node_id)
                if category == "generated" and (
                    resource["resource_type"] != "generated_context"
                    or resource["producer_node_id"] != node_id
                ):
                    raise _error(E_RESOURCE, f"generated resource {resource_id} has wrong producer")
                if category == "upstream_artifacts" and (
                    resource["resource_type"] != "upstream_artifact"
                    or resource["producer_node_id"] is None
                    or resource["producer_node_id"] == node_id
                ):
                    raise _error(E_RESOURCE, f"upstream resource {resource_id} has wrong producer")

    for resource in resources:
        resource_id = resource["resource_id"]
        producer = resource["producer_node_id"]
        consumers = resource["consumer_node_ids"]
        if producer is not None and producer not in node_ids:
            raise _error(E_RESOURCE, f"resource {resource_id} producer is missing")
        if any(consumer not in node_ids for consumer in consumers):
            raise _error(E_RESOURCE, f"resource {resource_id} consumer is missing")
        if resource["freshness_policy"]["mode"] == "runtime" and producer is None:
            raise _error(E_RESOURCE, f"runtime resource {resource_id} lacks a producer")
        if resource["resource_type"] in {"upstream_artifact", "generated_context"} and producer is None:
            raise _error(E_RESOURCE, f"generated resource {resource_id} lacks a producer")
        if consumers != sorted(derived_consumers[resource_id]):
            raise _error(E_RESOURCE, f"resource {resource_id} consumer binding differs")


def _validate_edge_types_and_bindings(
    edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    task_node_map: Mapping[str, str],
    compiled_plan: Mapping[str, Any] | None,
    supersedes_graph_sha256: str | None,
) -> tuple[dict[str, list[str]], list[str], list[str], list[str]]:
    node_by_id = {node["node_id"]: node for node in nodes}
    gate_by_id = {gate["gate_id"]: gate for gate in gates}
    phase_by_task = (
        {
            task_id: phase
            for phase, task_ids in compiled_plan["phase_exact_sets"].items()
            for task_id in task_ids
        }
        if compiled_plan is not None
        else {}
    )
    phase_index = {phase: index for index, phase in enumerate(PHASES)}
    node_task = {node_id: task_id for task_id, node_id in task_node_map.items()}
    plan_order = (
        {
            task_node_map[task_id]: index
            for index, task_id in enumerate(compiled_plan["topological_order"])
        }
        if compiled_plan is not None
        else {}
    )
    forward_edges: list[dict[str, Any]] = []
    execution_ids: list[str] = []
    lineage_ids: list[str] = []

    for edge in edges:
        edge_id = edge["edge_id"]
        edge_type = edge["edge_type"]
        source = edge["source_node_id"]
        target = edge["target_node_id"]
        outcomes = edge["accepted_outcomes"]
        gate_ref = edge["gate_ref"]
        bindings = edge["data_bindings"]
        budget = edge["traversal_budget"]

        if edge_type == "supersedes":
            if (
                supersedes_graph_sha256 is None
                or source not in node_by_id
                or target in node_by_id
                or outcomes
                or gate_ref is not None
                or bindings
                or budget != 0
            ):
                raise _error(E_EDGE_ENDPOINT, f"supersedes edge {edge_id} is invalid")
            lineage_ids.append(edge_id)
            continue

        if source not in node_by_id or target not in node_by_id:
            raise _error(E_EDGE_ENDPOINT, f"edge {edge_id} endpoint is missing")
        if edge_type in FORWARD_EDGE_TYPES:
            if source == target:
                raise _error(E_EDGE_ENDPOINT, f"forward edge {edge_id} self-targets")
            if compiled_plan is not None:
                source_phase = phase_by_task[node_task[source]]
                target_phase = phase_by_task[node_task[target]]
                if phase_index[source_phase] > phase_index[target_phase]:
                    raise _error(E_EDGE_ENDPOINT, f"edge {edge_id} inverts phase order")
            forward_edges.append(edge)
        elif edge_type in {"repeat", "recovery"}:
            if compiled_plan is not None:
                source_phase = phase_by_task[node_task[source]]
                target_phase = phase_by_task[node_task[target]]
                if source_phase != target_phase:
                    raise _error(E_EDGE_ENDPOINT, f"edge {edge_id} crosses phases")
                if edge_type == "repeat":
                    if plan_order[target] > plan_order[source]:
                        raise _error(E_EDGE_ENDPOINT, f"repeat edge {edge_id} targets a later node")
                elif source == target or plan_order[target] >= plan_order[source]:
                    raise _error(E_EDGE_ENDPOINT, f"recovery edge {edge_id} must target an earlier node")
        execution_ids.append(edge_id)

        fixed_outcomes = {
            "dependency": ["completed"],
            "success": ["completed"],
            "failure": ["failed"],
            "blocked": ["blocked"],
            "unverified": ["unverified"],
            "human_approved": ["completed"],
        }
        if edge_type in fixed_outcomes and outcomes != fixed_outcomes[edge_type]:
            raise _error(E_EDGE_TYPE, f"edge {edge_id} outcomes contradict its type")
        if edge_type == "data" and (
            not outcomes or not set(outcomes) <= {"completed", "partial"}
        ):
            raise _error(E_EDGE_TYPE, f"data edge {edge_id} outcomes are invalid")
        if edge_type in {"repeat", "recovery"} and (
            not outcomes or not set(outcomes) <= TERMINAL_OUTCOMES
        ):
            raise _error(E_EDGE_TYPE, f"edge {edge_id} traversal outcomes are invalid")

        if edge_type == "human_approved":
            if gate_ref not in gate_by_id or gate_by_id[gate_ref]["gate_type"] != "human_approval":
                raise _error(E_GATE, f"edge {edge_id} lacks a valid human gate")
        elif gate_ref is not None:
            raise _error(E_EDGE_TYPE, f"edge {edge_id} must have a null gate_ref")

        if edge_type == "data":
            if not bindings or budget != 0:
                raise _error(E_DATA, f"data edge {edge_id} has invalid bindings or budget")
        elif bindings:
            raise _error(E_EDGE_TYPE, f"non-data edge {edge_id} contains data bindings")

        if edge_type in {"repeat", "recovery"}:
            if budget <= 0:
                raise _error(E_TRAVERSAL, f"edge {edge_id} requires a positive traversal budget")
        elif budget != 0:
            raise _error(E_EDGE_TYPE, f"edge {edge_id} must have zero traversal budget")

    control_pairs = {
        (edge["source_node_id"], edge["target_node_id"])
        for edge in forward_edges
        if edge["edge_type"] in CONTROL_EDGE_TYPES
    }
    for edge in forward_edges:
        if edge["edge_type"] != "data":
            continue
        source_node = node_by_id[edge["source_node_id"]]
        target_node = node_by_id[edge["target_node_id"]]
        if (source_node["node_id"], target_node["node_id"]) not in control_pairs:
            raise _error(E_DATA, f"data edge {edge['edge_id']} lacks a control dependency")
        output_by_id = {port["port_id"]: port for port in source_node["output_ports"]}
        input_by_id = {port["port_id"]: port for port in target_node["input_ports"]}
        for binding in edge["data_bindings"]:
            output = output_by_id.get(binding["output_port_id"])
            input_port = input_by_id.get(binding["input_port_id"])
            if (
                output is None
                or input_port is None
                or binding["schema_ref"] != output["schema_ref"]
                or binding["schema_ref"] != input_port["schema_ref"]
                or output["sensitivity"] != input_port["sensitivity"]
                or target_node["node_id"] not in output["consumer_node_ids"]
            ):
                raise _error(E_DATA, f"data edge {edge['edge_id']} port binding differs")

    predecessor_sets: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    children: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    inbound_edge_ids: dict[str, list[str]] = {node_id: [] for node_id in node_by_id}
    for edge in forward_edges:
        source = edge["source_node_id"]
        target = edge["target_node_id"]
        predecessor_sets[target].add(source)
        children[source].add(target)
        inbound_edge_ids[target].append(edge["edge_id"])

    indegree = {node_id: len(predecessors) for node_id, predecessors in predecessor_sets.items()}
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        current = list(ready)
        order.extend(current)
        next_ready: list[str] = []
        for node_id in current:
            for child in sorted(children[node_id]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    next_ready.append(child)
        ready = sorted(next_ready)
    if len(order) != len(node_by_id):
        raise _error(E_CYCLE, "forward execution graph contains a cycle")

    if compiled_plan is not None:
        for task_id, expected_dependencies in compiled_plan["dependency_map"].items():
            node_id = task_node_map[task_id]
            expected_nodes = sorted(task_node_map[item] for item in expected_dependencies)
            actual_nodes = sorted(predecessor_sets[node_id])
            if actual_nodes != expected_nodes:
                raise _error(E_TASK_BINDING, f"node {node_id} predecessors differ from frozen task DAG")
    else:
        order_index = {node_id: index for index, node_id in enumerate(order)}
        for edge in edges:
            if edge["edge_type"] not in {"repeat", "recovery"}:
                continue
            source = edge["source_node_id"]
            target = edge["target_node_id"]
            if edge["edge_type"] == "repeat" and order_index[target] > order_index[source]:
                raise _error(E_EDGE_ENDPOINT, f"repeat edge {edge['edge_id']} targets a later node")
            if edge["edge_type"] == "recovery" and (
                source == target or order_index[target] >= order_index[source]
            ):
                raise _error(E_EDGE_ENDPOINT, f"recovery edge {edge['edge_id']} must target an earlier node")

    predecessor_map = {
        node_id: sorted(predecessor_sets[node_id]) for node_id in sorted(node_by_id)
    }
    inbound_sorted = {
        node_id: sorted(inbound_edge_ids[node_id]) for node_id in sorted(node_by_id)
    }
    return predecessor_map, order, sorted(execution_ids), sorted(lineage_ids), inbound_sorted


def _validate_fan_in_and_recovery(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    inbound_edge_ids: Mapping[str, list[str]],
) -> dict[str, dict[str, Any] | None]:
    edge_by_id = {edge["edge_id"]: edge for edge in edges}
    fan_in_map: dict[str, dict[str, Any] | None] = {}
    referenced_recovery_edges: set[str] = set()
    for node in nodes:
        node_id = node["node_id"]
        inbound = list(inbound_edge_ids[node_id])
        fan_in = node["fan_in"]
        if not inbound:
            if fan_in is not None:
                raise _error(E_FAN_IN, f"root node {node_id} must have null fan_in")
            fan_in_map[node_id] = None
        else:
            if fan_in is None or fan_in["edge_ids"] != inbound:
                raise _error(E_FAN_IN, f"node {node_id} fan-in edge set differs")
            edge_count = len(inbound)
            count = fan_in["quorum_count"]
            ratio = fan_in["quorum_ratio_basis_points"]
            mode = fan_in["mode"]
            if mode in {"all", "any"}:
                if count is not None or ratio is not None:
                    raise _error(E_FAN_IN, f"node {node_id} {mode} fan-in has quorum fields")
            elif (
                (count is None) == (ratio is None)
                or (count is not None and not is_int(count, minimum=1))
                or (ratio is not None and not is_int(ratio, minimum=1))
                or (count is not None and count > edge_count)
                or (ratio is not None and ratio > 10000)
            ):
                raise _error(E_FAN_IN, f"node {node_id} quorum is invalid")
            fan_in_map[node_id] = copy.deepcopy(fan_in)

        recovery = node["recovery_policy"]
        if recovery["mode"] == "retry" and node["budget"]["attempts"] < 2:
            raise _error(E_TRAVERSAL, f"node {node_id} retry recovery lacks an attempt budget")
        if recovery["mode"] == "edge":
            edge = edge_by_id.get(recovery["edge_id"])
            if edge is None or edge["edge_type"] != "recovery" or edge["source_node_id"] != node_id:
                raise _error(E_TRAVERSAL, f"node {node_id} recovery edge is invalid")
            referenced_recovery_edges.add(edge["edge_id"])
    all_recovery_edges = {
        edge["edge_id"] for edge in edges if edge["edge_type"] == "recovery"
    }
    if all_recovery_edges != referenced_recovery_edges:
        raise _error(E_TRAVERSAL, "every recovery edge must be owned by its source node")
    return {node_id: fan_in_map[node_id] for node_id in sorted(fan_in_map)}


def compile_graph_contract(
    document: Mapping[str, Any],
    *,
    compiled_task_plan: Mapping[str, Any],
    task_plan_validation_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile a deterministic ten-field Graph into its static runtime maps."""

    compiled_plan, plan_validation = _validated_plan(
        compiled_task_plan, task_plan_validation_receipt
    )
    graph = _exact(document, GRAPH_INPUT_FIELDS, "graph")
    if graph["schema_version"] != "goal-teams-graph-contract-v2.65":
        raise _error(E_SCHEMA, "unsupported graph schema_version")
    graph_id = _required_string(graph["graph_id"], "graph_id")
    if not is_int(graph["graph_revision"], minimum=1):
        raise _error(E_SCHEMA, "graph_revision must be a positive integer")
    plan_binding = _normalize_plan_binding(
        graph["plan_binding"], compiled_plan, plan_validation
    )
    supersedes = graph["supersedes_graph_sha256"]
    if supersedes is not None and not is_sha256(supersedes):
        raise _error(E_SCHEMA, "supersedes_graph_sha256 must be null or SHA-256")

    collections = {
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "resources": graph["resources"],
        "gates": graph["gates"],
        "actions": graph["actions"],
    }
    if not isinstance(collections["nodes"], list) or not collections["nodes"]:
        raise _error(E_SCHEMA, "nodes must be a non-empty array")
    for name in ("edges", "resources", "gates", "actions"):
        if not isinstance(collections[name], list):
            raise _error(E_SCHEMA, f"{name} must be an array")

    try:
        nodes = [_normalize_node(item, index) for index, item in enumerate(collections["nodes"])]
        edges = [_normalize_edge(item, index) for index, item in enumerate(collections["edges"])]
        resources = [
            _normalize_resource(item, index)
            for index, item in enumerate(collections["resources"])
        ]
        gates = [_normalize_gate(item, index) for index, item in enumerate(collections["gates"])]
        actions = [
            _normalize_action(item, index)
            for index, item in enumerate(collections["actions"])
        ]
    except CanonicalValueError as exc:
        raise _error(E_SCHEMA, "graph contains a non-canonical JSON value") from exc

    _ensure_unique(nodes, "node_id", "Node")
    _ensure_unique(edges, "edge_id", "Edge")
    _ensure_unique(resources, "resource_id", "Resource")
    _ensure_unique(gates, "gate_id", "Gate")
    _ensure_unique(actions, "action_id", "Action")
    nodes.sort(key=lambda item: item["node_id"])
    edges.sort(key=lambda item: item["edge_id"])
    resources.sort(key=lambda item: item["resource_id"])
    gates.sort(key=lambda item: item["gate_id"])
    actions.sort(key=lambda item: item["action_id"])

    task_node_map = _validate_task_bindings(nodes, compiled_plan)
    _validate_output_consumers(nodes)
    _validate_action_and_gate_refs(nodes, actions, gates)
    _validate_resource_bindings(nodes, resources)
    (
        predecessor_map,
        topological_order,
        execution_edge_ids,
        lineage_edge_ids,
        inbound_edge_ids,
    ) = _validate_edge_types_and_bindings(
        edges,
        nodes,
        gates,
        task_node_map,
        compiled_plan,
        supersedes,
    )
    _validate_input_port_coverage(nodes, edges)
    fan_in_map = _validate_fan_in_and_recovery(nodes, edges, inbound_edge_ids)
    ready_roots = sorted(
        node_id for node_id, predecessors in predecessor_map.items() if not predecessors
    )

    normalized_graph: dict[str, Any] = {
        "schema_version": "goal-teams-graph-contract-v2.65",
        "graph_id": graph_id,
        "graph_revision": graph["graph_revision"],
        "plan_binding": plan_binding,
        "supersedes_graph_sha256": supersedes,
        "nodes": nodes,
        "edges": edges,
        "resources": resources,
        "gates": gates,
        "actions": actions,
    }
    try:
        graph_digest = canonical_sha256(normalized_graph)
    except CanonicalValueError as exc:
        raise _error(E_SCHEMA, "graph is not canonical JSON") from exc
    compiled: dict[str, Any] = {
        **normalized_graph,
        "task_node_map": task_node_map,
        "predecessor_map": predecessor_map,
        "fan_in_map": fan_in_map,
        "topological_order": topological_order,
        "ready_roots": ready_roots,
        "execution_edge_ids": execution_edge_ids,
        "lineage_edge_ids": lineage_edge_ids,
        "graph_contract_sha256": graph_digest,
    }
    compiled["receipt_sha256"] = canonical_sha256(compiled)
    return compiled


def _rebuild_graph_intrinsic(compiled_graph: Mapping[str, Any]) -> dict[str, Any]:
    graph = _exact(
        compiled_graph,
        GRAPH_INPUT_FIELDS | GRAPH_DERIVED_FIELDS,
        "compiled Graph",
        code=E_RECEIPT,
    )
    if graph["schema_version"] != "goal-teams-graph-contract-v2.65":
        raise _error(E_RECEIPT, "compiled Graph schema_version differs")
    graph_id = _required_string(graph["graph_id"], "graph_id", code=E_RECEIPT)
    if not is_int(graph["graph_revision"], minimum=1):
        raise _error(E_RECEIPT, "compiled Graph revision is invalid")
    plan_binding = _normalize_intrinsic_plan_binding(graph["plan_binding"])
    supersedes = graph["supersedes_graph_sha256"]
    if supersedes is not None and not is_sha256(supersedes):
        raise _error(E_RECEIPT, "compiled Graph supersedes digest is invalid")

    collections = {
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "resources": graph["resources"],
        "gates": graph["gates"],
        "actions": graph["actions"],
    }
    if not isinstance(collections["nodes"], list) or not collections["nodes"]:
        raise _error(E_RECEIPT, "compiled Graph Nodes are absent")
    for name in ("edges", "resources", "gates", "actions"):
        if not isinstance(collections[name], list):
            raise _error(E_RECEIPT, f"compiled Graph {name} is not an array")

    nodes = [_normalize_node(item, index) for index, item in enumerate(collections["nodes"])]
    edges = [_normalize_edge(item, index) for index, item in enumerate(collections["edges"])]
    resources = [
        _normalize_resource(item, index)
        for index, item in enumerate(collections["resources"])
    ]
    gates = [_normalize_gate(item, index) for index, item in enumerate(collections["gates"])]
    actions = [
        _normalize_action(item, index)
        for index, item in enumerate(collections["actions"])
    ]
    _ensure_unique(nodes, "node_id", "Node")
    _ensure_unique(edges, "edge_id", "Edge")
    _ensure_unique(resources, "resource_id", "Resource")
    _ensure_unique(gates, "gate_id", "Gate")
    _ensure_unique(actions, "action_id", "Action")
    nodes.sort(key=lambda item: item["node_id"])
    edges.sort(key=lambda item: item["edge_id"])
    resources.sort(key=lambda item: item["resource_id"])
    gates.sort(key=lambda item: item["gate_id"])
    actions.sort(key=lambda item: item["action_id"])

    task_node_map = _intrinsic_task_node_map(nodes)
    _validate_output_consumers(nodes)
    _validate_action_and_gate_refs(nodes, actions, gates)
    _validate_resource_bindings(nodes, resources)
    (
        predecessor_map,
        topological_order,
        execution_edge_ids,
        lineage_edge_ids,
        inbound_edge_ids,
    ) = _validate_edge_types_and_bindings(
        edges,
        nodes,
        gates,
        task_node_map,
        None,
        supersedes,
    )
    _validate_input_port_coverage(nodes, edges)
    fan_in_map = _validate_fan_in_and_recovery(nodes, edges, inbound_edge_ids)
    ready_roots = sorted(
        node_id for node_id, predecessors in predecessor_map.items() if not predecessors
    )
    normalized_graph: dict[str, Any] = {
        "schema_version": "goal-teams-graph-contract-v2.65",
        "graph_id": graph_id,
        "graph_revision": graph["graph_revision"],
        "plan_binding": plan_binding,
        "supersedes_graph_sha256": supersedes,
        "nodes": nodes,
        "edges": edges,
        "resources": resources,
        "gates": gates,
        "actions": actions,
    }
    supplied_input = {field: copy.deepcopy(graph[field]) for field in GRAPH_INPUT_FIELDS}
    if canonical_json_bytes(supplied_input) != canonical_json_bytes(normalized_graph):
        raise _error(E_RECEIPT, "compiled Graph input is not canonically normalized")
    graph_digest = canonical_sha256(normalized_graph)
    derived = {
        "task_node_map": task_node_map,
        "predecessor_map": predecessor_map,
        "fan_in_map": fan_in_map,
        "topological_order": topological_order,
        "ready_roots": ready_roots,
        "execution_edge_ids": execution_edge_ids,
        "lineage_edge_ids": lineage_edge_ids,
    }
    for field, expected in derived.items():
        if graph[field] != expected:
            raise _error(E_RECEIPT, f"compiled Graph {field} differs")
    if graph["graph_contract_sha256"] != graph_digest:
        raise _error(E_RECEIPT, "compiled Graph input digest differs")
    rebuilt: dict[str, Any] = {
        **normalized_graph,
        **derived,
        "graph_contract_sha256": graph_digest,
    }
    rebuilt["receipt_sha256"] = canonical_sha256(rebuilt)
    if graph["receipt_sha256"] != rebuilt["receipt_sha256"]:
        raise _error(E_RECEIPT, "compiled Graph receipt digest differs")
    return rebuilt


def validate_graph_intrinsic(
    compiled_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate only self-contained compiled-Graph facts and canonical maps."""

    try:
        if not isinstance(compiled_graph, Mapping):
            raise _error(E_RECEIPT, "compiled Graph must be an object")
        rebuilt = _rebuild_graph_intrinsic(compiled_graph)
        derived = {
            field: copy.deepcopy(rebuilt[field])
            for field in (
                "task_node_map",
                "predecessor_map",
                "fan_in_map",
                "topological_order",
                "ready_roots",
                "execution_edge_ids",
                "lineage_edge_ids",
            )
        }
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-graph-intrinsic-validation-v2.65",
            "graph_id": rebuilt["graph_id"],
            "graph_revision": rebuilt["graph_revision"],
            "graph_contract_sha256": rebuilt["graph_contract_sha256"],
            "compiled_graph_receipt_sha256": rebuilt["receipt_sha256"],
            "derived_map_sha256": canonical_sha256(derived),
            "valid": True,
            "validator": "scripts.v265.graph_contract.validate_graph_intrinsic",
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt
    except GraphContractError as exc:
        if exc.code == E_RECEIPT:
            raise
        raise _error(E_RECEIPT, "compiled Graph intrinsic validation failed") from exc
    except (CanonicalValueError, KeyError, TypeError, ValueError) as exc:
        raise _error(E_RECEIPT, "compiled Graph intrinsic value is invalid") from exc


def validate_compiled_graph_contract(
    compiled_graph: Mapping[str, Any],
    *,
    compiled_task_plan: Mapping[str, Any],
    task_plan_validation_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild a compiled Graph and return a digest-bound validation receipt."""

    if not isinstance(compiled_graph, Mapping) or set(compiled_graph) != set(
        GRAPH_INPUT_FIELDS | GRAPH_DERIVED_FIELDS
    ):
        raise _error(E_RECEIPT, "compiled Graph field set is invalid")
    document = {
        field: copy.deepcopy(compiled_graph[field]) for field in GRAPH_INPUT_FIELDS
    }
    try:
        rebuilt = compile_graph_contract(
            document,
            compiled_task_plan=compiled_task_plan,
            task_plan_validation_receipt=task_plan_validation_receipt,
        )
        if canonical_json_bytes(dict(compiled_graph)) != canonical_json_bytes(rebuilt):
            raise _error(E_RECEIPT, "compiled Graph differs from deterministic rebuild")
    except GraphContractError as exc:
        if exc.code == E_RECEIPT:
            raise
        raise _error(E_RECEIPT, "compiled Graph cannot be rebuilt exactly") from exc
    except CanonicalValueError as exc:
        raise _error(E_RECEIPT, "compiled Graph is not canonical JSON") from exc

    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-graph-validation-receipt-v2.65",
        "graph_id": rebuilt["graph_id"],
        "graph_revision": rebuilt["graph_revision"],
        "task_exact_set_sha256": rebuilt["plan_binding"]["task_exact_set_sha256"],
        "compiled_graph_receipt_sha256": rebuilt["receipt_sha256"],
        "validator": "scripts.v265.graph_contract.validate_compiled_graph_contract",
        "valid": True,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt
