"""Pure V2.65 Graph event validation, reduction, and readiness evaluation."""

from __future__ import annotations

import copy
import math
from datetime import timedelta
from typing import Any, Iterable, Mapping, Sequence

from scripts.v265.canonical import (
    canonical_sha256,
    exact_mapping,
    is_int,
    is_json_scalar,
    is_non_empty_string,
    is_sha256,
    require_utc_timestamp,
    timestamp_value,
    unique_string_list,
)


ZERO_SHA256 = "0" * 64
BINDING_FIELDS = frozenset(
    {
        "source_sha256",
        "route_sha256",
        "contract_sha256",
        "task_exact_set_sha256",
        "environment_sha256",
        "authorization_lineage_sha256",
    }
)
EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "event_id",
        "event_seq",
        "event_type",
        "node_id",
        "attempt",
        "cas_base_revision",
        "previous_event_sha256",
        "bindings",
        "payload",
        "evidence_refs",
        "actor_identity",
        "actor_relationship",
        "occurred_at",
        "event_sha256",
    }
)

PAYLOAD_FIELDS = {
    "run.created": frozenset({"graph_receipt_sha256"}),
    "gate.passed": frozenset(
        {"gate_id", "gate_receipt", "gate_decision_sha256", "decision"}
    ),
    "gate.rejected": frozenset(
        {"gate_id", "gate_receipt", "gate_decision_sha256", "decision"}
    ),
    "gate.timed_out": frozenset({"gate_id", "deadline", "on_timeout_outcome"}),
    "node.ready": frozenset(
        {
            "satisfied_edge_ids",
            "fan_in_mode",
            "required_edge_count",
            "satisfied_edge_count",
        }
    ),
    "node.claimed": frozenset({"worker_id", "lease_id", "lease_expires_at"}),
    "node.started": frozenset(
        {
            "owner_run_id",
            "validator_run_id",
            "member_packet",
            "context_bundle_sha256",
            "capability_receipt",
            "capability_request",
            "capability_decision",
            "host_handle_id",
        }
    ),
    "node.heartbeat": frozenset(
        {"lease_id", "previous_expires_at", "new_expires_at"}
    ),
    "node.outcome_recorded": frozenset(
        {"outcome", "owner_run_id", "artifact_receipts"}
    ),
    "node.validation_recorded": frozenset(
        {"validation_state", "validator_run_id", "validation_receipt", "observed_outcome"}
    ),
    "node.blocked": frozenset({"blocker_id"}),
    "node.interrupted": frozenset(
        {"interrupt_id", "gate_id", "reason", "capability_receipt_sha256"}
    ),
    "node.resumed": frozenset(
        {"interrupt_id", "approval_receipt", "approval_decision", "decision"}
    ),
    "node.cancelled": frozenset({"reason"}),
    "node.lease_expired": frozenset(
        {"lease_id", "lease_expires_at", "recovery_decision"}
    ),
    "node.retry_scheduled": frozenset(
        {"source_edge_id", "traversal_count", "next_attempt"}
    ),
    "side_effect.intent": frozenset({"idempotency_key", "action_sha256"}),
    "side_effect.confirmed": frozenset(
        {"idempotency_key", "result_digest", "readback_receipt_sha256"}
    ),
    "side_effect.reconciliation_required": frozenset(
        {"idempotency_key", "reason_code"}
    ),
    "checkpoint.created": frozenset({"checkpoint_revision", "projection_sha256"}),
    "node.stale": frozenset({"changed_binding_fields"}),
    "host.prepared": frozenset({"host_handle", "dispatch_sha256"}),
    "host.execution_started": frozenset(
        {"host_handle_sha256", "execution_receipt"}
    ),
    "host.observation_recorded": frozenset(
        {
            "observation_type",
            "host_handle_id",
            "observation_receipt",
            "observation_sha256",
        }
    ),
}

TERMINAL_OUTCOMES = frozenset(
    {"completed", "partial", "failed", "unverified", "skipped", "blocked", "cancelled", "stale"}
)
VALIDATION_STATES = frozenset({"not_run", "passed", "rejected", "stale"})

HOST_HANDLE_FIELDS = frozenset(
    {
        "schema_version",
        "adapter_id",
        "host_handle_id",
        "run_id",
        "node_id",
        "attempt",
        "transport",
        "proof_strength",
        "dispatch_sha256",
        "state",
        "prepared_at",
        "handle_sha256",
    }
)
HOST_EXECUTION_FIELDS = frozenset(
    {
        "schema_version",
        "adapter_id",
        "host_handle_id",
        "handle_sha256",
        "dispatch_sha256",
        "state",
        "started_at",
        "proof_strength",
        "receipt_sha256",
    }
)
HOST_PROBE_FIELDS = frozenset(
    {
        "schema_version",
        "adapter_id",
        "host_handle_id",
        "run_id",
        "node_id",
        "attempt",
        "observed_state",
        "quiescent",
        "observed_at",
        "evidence_refs",
        "receipt_sha256",
    }
)
HOST_CANCEL_FIELDS = frozenset(
    {
        "schema_version",
        "host_handle_id",
        "cancelled",
        "observed_state",
        "reason_code",
        "decision_sha256",
    }
)
HOST_READBACK_FIELDS = frozenset(
    {
        "schema_version",
        "adapter_id",
        "host_handle_id",
        "handle_sha256",
        "dispatch_sha256",
        "run_id",
        "node_id",
        "attempt",
        "idempotency_key",
        "action_sha256",
        "observed_state",
        "result_digest",
        "external_receipt_ref",
        "issuer",
        "issuer_assurance",
        "proof_strength",
        "attestation_ref",
        "observed_at",
        "receipt_sha256",
    }
)


class GraphRuntimeError(ValueError):
    """Stable fail-closed V2.65 Runtime error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _error(code: str, message: str) -> GraphRuntimeError:
    return GraphRuntimeError(code, message)


def _exact(value: object, fields: frozenset[str], label: str, code: str) -> dict[str, Any]:
    return exact_mapping(
        value,
        fields,
        error=lambda message: _error(code, message),
        label=label,
    )


def _strings(value: object, label: str, *, allow_empty: bool = True) -> list[str]:
    return unique_string_list(
        value,
        error=lambda message: _error("E_V265_RUNTIME_EVENT", message),
        label=label,
        non_empty=not allow_empty,
        sort_output=False,
    )


def _validate_bindings(value: Mapping[str, Any], graph: Mapping[str, Any]) -> dict[str, str]:
    result = _exact(value, BINDING_FIELDS, "runtime bindings", "E_V265_RUNTIME_EVENT")
    if not all(is_sha256(item) for item in result.values()):
        raise _error("E_V265_RUNTIME_EVENT", "runtime binding digest is invalid")
    if result["contract_sha256"] != graph.get("receipt_sha256"):
        raise _error("E_V265_RUNTIME_EVENT", "Graph contract binding differs")
    plan = graph.get("plan_binding")
    if not isinstance(plan, Mapping) or result["task_exact_set_sha256"] != plan.get(
        "task_exact_set_sha256"
    ):
        raise _error("E_V265_RUNTIME_EVENT", "TaskExactSet binding differs")
    return {key: str(result[key]) for key in sorted(BINDING_FIELDS)}


def validate_runtime_graph_contract(
    compiled_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Map the shared plan-independent Graph validator into Runtime Evidence."""

    from scripts.v265.graph_contract import (
        GraphContractError,
        validate_graph_intrinsic,
    )

    try:
        intrinsic = validate_graph_intrinsic(compiled_graph)
    except GraphContractError as exc:
        raise _error(
            "E_V265_RUNTIME_GRAPH_INTEGRITY",
            "compiled Graph intrinsic validation failed",
        ) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(
            "E_V265_RUNTIME_GRAPH_INTEGRITY", "compiled Graph is malformed"
        ) from exc
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-runtime-graph-integrity-receipt-v2.65",
        "graph_id": intrinsic["graph_id"],
        "graph_revision": intrinsic["graph_revision"],
        "graph_contract_sha256": intrinsic["graph_contract_sha256"],
        "compiled_graph_receipt_sha256": intrinsic[
            "compiled_graph_receipt_sha256"
        ],
        "derived_map_sha256": intrinsic["derived_map_sha256"],
        "validator": "scripts.v265.graph_runtime.validate_runtime_graph_contract",
        "valid": True,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt

def make_graph_event(
    *,
    run_id: str,
    event_id: str,
    event_seq: int,
    event_type: str,
    node_id: str | None,
    attempt: int,
    cas_base_revision: int,
    previous_event_sha256: str,
    bindings: Mapping[str, str],
    payload: Mapping[str, Any],
    evidence_refs: Sequence[str],
    actor_identity: str,
    actor_relationship: str,
    occurred_at: str,
) -> dict[str, Any]:
    """Build a hash-bound Event; semantic checks happen during reduction."""

    if not all(is_non_empty_string(item) for item in (run_id, event_id, event_type, actor_identity, actor_relationship)):
        raise _error("E_V265_RUNTIME_EVENT", "Event identity is invalid")
    if not is_int(event_seq, minimum=1) or not is_int(cas_base_revision, minimum=0):
        raise _error("E_V265_RUNTIME_EVENT", "Event sequence or CAS is invalid")
    if not is_int(attempt, minimum=0):
        raise _error("E_V265_RUNTIME_EVENT", "Event attempt is invalid")
    if not is_sha256(previous_event_sha256):
        raise _error("E_V265_RUNTIME_EVENT", "previous Event digest is invalid")
    require_utc_timestamp(
        occurred_at,
        error=lambda message: _error("E_V265_RUNTIME_EVENT", message),
        label="occurred_at",
    )
    if not isinstance(bindings, Mapping) or set(bindings) != set(BINDING_FIELDS):
        raise _error("E_V265_RUNTIME_EVENT", "Event bindings use the wrong exact field set")
    if not all(is_sha256(value) for value in bindings.values()):
        raise _error("E_V265_RUNTIME_EVENT", "Event binding digest is invalid")
    if not isinstance(payload, Mapping):
        raise _error("E_V265_RUNTIME_EVENT", "Event payload must be an object")
    refs = _strings(evidence_refs, "evidence_refs", allow_empty=False)
    event: dict[str, Any] = {
        "schema_version": "goal-teams-graph-event-v2.65",
        "run_id": run_id,
        "event_id": event_id,
        "event_seq": event_seq,
        "event_type": event_type,
        "node_id": node_id,
        "attempt": attempt,
        "cas_base_revision": cas_base_revision,
        "previous_event_sha256": previous_event_sha256,
        "bindings": copy.deepcopy(dict(bindings)),
        "payload": copy.deepcopy(dict(payload)),
        "evidence_refs": refs,
        "actor_identity": actor_identity,
        "actor_relationship": actor_relationship,
        "occurred_at": occurred_at,
    }
    event["event_sha256"] = canonical_sha256(event)
    return event


def _validated_event(
    value: Mapping[str, Any],
    *,
    graph: Mapping[str, Any],
    bindings: Mapping[str, str],
    expected_seq: int,
    expected_previous: str,
) -> dict[str, Any]:
    event = _exact(value, EVENT_FIELDS, "Graph Event", "E_V265_RUNTIME_EVENT")
    if event["schema_version"] != "goal-teams-graph-event-v2.65":
        raise _error("E_V265_RUNTIME_EVENT", "Event schema_version differs")
    if event["event_seq"] != expected_seq or event["cas_base_revision"] != expected_seq - 1:
        raise _error("E_V265_RUNTIME_CAS", "Event sequence or CAS revision differs")
    if event["previous_event_sha256"] != expected_previous:
        raise _error("E_V265_RUNTIME_HASH_CHAIN", "Event previous digest differs")
    claimed = event["event_sha256"]
    if not is_sha256(claimed) or canonical_sha256(
        {key: item for key, item in event.items() if key != "event_sha256"}
    ) != claimed:
        raise _error("E_V265_RUNTIME_EVENT_DIGEST", "Event self-digest differs")
    if dict(event["bindings"]) != dict(bindings):
        raise _error("E_V265_RUNTIME_EVENT", "Event bindings differ from run genesis")
    event_type = event["event_type"]
    expected_payload = PAYLOAD_FIELDS.get(event_type)
    if expected_payload is None:
        raise _error("E_V265_RUNTIME_EVENT", "unknown Event type")
    _exact(event["payload"], expected_payload, f"{event_type} payload", "E_V265_RUNTIME_EVENT")
    node_event = (
        event_type.startswith("node.")
        or event_type.startswith("side_effect.")
        or event_type.startswith("host.")
    )
    if node_event:
        if event["node_id"] not in {item["node_id"] for item in graph["nodes"]} or not is_int(
            event["attempt"], minimum=1
        ):
            raise _error("E_V265_RUNTIME_EVENT", "Node Event identity is invalid")
    elif event["node_id"] is not None or event["attempt"] != 0:
        raise _error("E_V265_RUNTIME_EVENT", "non-Node Event must use null Node and attempt zero")
    _strings(event["evidence_refs"], "Event evidence_refs", allow_empty=False)
    require_utc_timestamp(
        event["occurred_at"],
        error=lambda message: _error("E_V265_RUNTIME_EVENT", message),
        label="occurred_at",
    )
    return copy.deepcopy(event)


def _node_template() -> dict[str, Any]:
    return {
        "execution_state": "pending",
        "outcome": "pending",
        "validation_state": "not_run",
        "attempt": 0,
        "owner_run_id": None,
        "validator_run_id": None,
        "worker_id": None,
        "lease_id": None,
        "lease_expires_at": None,
        "member_packet_sha256": None,
        "context_bundle_sha256": None,
        "capability_receipt_sha256": None,
        "capability_request_sha256": None,
        "capability_decision_sha256": None,
        "approval_decision_sha256": None,
        "host_handle_id": None,
        "host_binding_assurance": "legacy_unobserved",
        "artifact_receipts": [],
        "evidence_refs": [],
    }


def _require_self_digest(value: Mapping[str, Any], field: str, code: str, label: str) -> None:
    claimed = value.get(field)
    if not is_sha256(claimed) or canonical_sha256(
        {key: item for key, item in value.items() if key != field}
    ) != claimed:
        raise _error(code, f"{label} self-digest differs")


def _node_by_id(graph: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    for node in graph["nodes"]:
        if node["node_id"] == node_id:
            return node
    raise _error("E_V265_RUNTIME_EVENT", "Node is absent from compiled Graph")


def _action_for_node(graph: Mapping[str, Any], node: Mapping[str, Any]) -> dict[str, Any]:
    for action in graph["actions"]:
        if action["action_id"] == node["action_ref"]:
            return action
    raise _error("E_V265_MEMBER_CAPABILITY", "Node Action is absent")


def _scope_sha(node: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "scope_allowlist": node["scope_allowlist"],
            "forbidden_scope": node["forbidden_scope"],
        }
    )


CAPABILITY_FIELDS = frozenset(
    {
        "schema_version", "capability_id", "issuer", "issuer_key_id", "issuer_assurance",
        "actor_relationship", "proof_strength", "host_execution_id", "node_id", "owner_run_id",
        "graph_contract_sha256", "scope_allowlist", "forbidden_scope", "scope_sha256",
        "tool_allowlist", "network_policy", "workspace_policy", "workspace_realpath", "not_before",
        "issued_at", "expires_at", "freshness_state", "permission_effect", "attestation_ref",
        "receipt_sha256",
    }
)
REQUEST_FIELDS = frozenset(
    {"schema_version", "run_id", "node_id", "task_id", "attempt", "action_ref", "owner_run_id",
     "graph_contract_sha256", "scope_sha256", "context_bundle_sha256", "capability_receipt_sha256",
     "requested_at", "request_sha256"}
)
DECISION_FIELDS = frozenset(
    {"schema_version", "verified", "issuer", "issuer_key_id", "issuer_assurance", "actor_relationship",
     "proof_strength", "permission_effect", "freshness_state", "scope_sha256", "node_id",
     "capability_receipt_sha256", "request_sha256", "reason_code", "decision_sha256"}
)
PACKET_FIELDS = frozenset(
    {
        "schema_version", "packet_id", "graph_id", "graph_revision", "graph_contract_sha256",
        "plan_id", "plan_revision", "task_exact_set_sha256", "node_id", "task_id",
        "owner_identity", "owner_run_id", "validator_identity", "validator_run_id", "action_ref",
        "scope_sha256", "context_bundle_sha256", "context_validation_receipt_sha256",
        "capability_receipt_sha256", "capability_request_sha256", "capability_decision_sha256",
        "issued_at", "packet_sha256",
    }
)


def _validate_started_payload(
    graph: Mapping[str, Any], event: Mapping[str, Any], node: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = event["payload"]
    capability = _exact(payload["capability_receipt"], CAPABILITY_FIELDS, "Capability Receipt", "E_V265_MEMBER_CAPABILITY")
    request = _exact(payload["capability_request"], REQUEST_FIELDS, "Capability Request", "E_V265_MEMBER_CAPABILITY")
    decision = _exact(payload["capability_decision"], DECISION_FIELDS, "Capability Decision", "E_V265_MEMBER_CAPABILITY")
    if not isinstance(payload["member_packet"], Mapping):
        raise _error("E_V265_MEMBER_RAW_PACKET_FORBIDDEN", "raw Member Packet is forbidden")
    packet = _exact(payload["member_packet"], PACKET_FIELDS, "Member Packet", "E_V265_MEMBER_BINDING")
    _require_self_digest(capability, "receipt_sha256", "E_V265_MEMBER_CAPABILITY", "Capability Receipt")
    _require_self_digest(request, "request_sha256", "E_V265_MEMBER_CAPABILITY", "Capability Request")
    _require_self_digest(decision, "decision_sha256", "E_V265_MEMBER_CAPABILITY", "Capability Decision")
    _require_self_digest(packet, "packet_sha256", "E_V265_MEMBER_DIGEST", "Member Packet")
    action = _action_for_node(graph, node)
    occurred = timestamp_value(event["occurred_at"])
    if (
        capability["schema_version"] != "goal-teams-host-capability-receipt-v2.65"
        or request["schema_version"] != "goal-teams-host-capability-request-v2.65"
        or decision["schema_version"] != "goal-teams-host-capability-decision-v2.65"
        or packet["schema_version"] != "goal-teams-member-packet-v2.65"
    ):
        raise _error("E_V265_MEMBER_CAPABILITY", "dispatch receipt schema differs")
    for field in ("not_before", "issued_at", "expires_at"):
        require_utc_timestamp(
            capability[field],
            error=lambda message: _error("E_V265_MEMBER_CAPABILITY", message),
            label=f"capability.{field}",
        )
    if not (
        timestamp_value(capability["not_before"])
        <= timestamp_value(capability["issued_at"])
        <= occurred
        <= timestamp_value(capability["expires_at"])
    ):
        raise _error("E_V265_MEMBER_CAPABILITY", "Capability Receipt is expired or not yet valid")
    expected_scope = _scope_sha(node)
    if (
        capability["node_id"] != node["node_id"]
        or capability["owner_run_id"] != payload["owner_run_id"]
        or capability["graph_contract_sha256"] != graph["receipt_sha256"]
        or capability["scope_allowlist"] != node["scope_allowlist"]
        or capability["forbidden_scope"] != node["forbidden_scope"]
        or capability["scope_sha256"] != expected_scope
        or capability["tool_allowlist"] != action["tool_allowlist"]
        or capability["network_policy"] != action["network_policy"]
        or capability["workspace_policy"] != action["workspace_policy"]
        or capability["freshness_state"] != "current"
    ):
        raise _error("E_V265_MEMBER_CAPABILITY", "Capability Receipt dispatch binding differs")
    required_permission = (
        "external_side_effects" if action["effect"] == "external_write" else "local_execution"
    )
    if capability["permission_effect"] != required_permission:
        raise _error("E_V265_MEMBER_CAPABILITY", "Capability permission does not satisfy Action")
    if action["effect"] == "external_write" and (
        capability["issuer_assurance"] != "externally_attested"
        or capability["proof_strength"] != "externally_attested"
        or capability["actor_relationship"] != "independent"
        or not is_non_empty_string(capability["attestation_ref"])
    ):
        raise _error("E_V265_MEMBER_CAPABILITY", "external Action lacks attestation")
    if request.get("capability_receipt_sha256") != capability["receipt_sha256"] or request.get(
        "node_id"
    ) != node["node_id"] or request.get("owner_run_id") != payload["owner_run_id"] or request.get(
        "context_bundle_sha256"
    ) != payload["context_bundle_sha256"] or request.get("graph_contract_sha256") != graph[
        "receipt_sha256"
    ] or request.get("scope_sha256") != expected_scope or request.get("run_id") != event[
        "run_id"
    ] or request.get("task_id") != node["task_refs"][0] or request.get("attempt") != event[
        "attempt"
    ] or request.get("action_ref") != node["action_ref"]:
        raise _error("E_V265_MEMBER_CAPABILITY", "Capability Request binding differs")
    require_utc_timestamp(
        request["requested_at"],
        error=lambda message: _error("E_V265_MEMBER_CAPABILITY", message),
        label="capability_request.requested_at",
    )
    if timestamp_value(request["requested_at"]) > occurred:
        raise _error("E_V265_MEMBER_CAPABILITY", "Capability Request occurs after start")
    if (
        decision.get("verified") is not True
        or decision.get("capability_receipt_sha256") != capability["receipt_sha256"]
        or decision.get("request_sha256") != request["request_sha256"]
        or decision.get("node_id") != node["node_id"]
        or decision.get("scope_sha256") != expected_scope
        or decision.get("freshness_state") != "current"
        or decision.get("issuer") != capability["issuer"]
        or decision.get("issuer_key_id") != capability["issuer_key_id"]
        or decision.get("issuer_assurance") != capability["issuer_assurance"]
        or decision.get("actor_relationship") != capability["actor_relationship"]
        or decision.get("proof_strength") != capability["proof_strength"]
        or decision.get("permission_effect") != capability["permission_effect"]
    ):
        raise _error("E_V265_MEMBER_CAPABILITY", "Capability Decision binding differs")
    if (
        packet.get("graph_contract_sha256") != graph["receipt_sha256"]
        or packet.get("node_id") != node["node_id"]
        or packet.get("task_id") != node["task_refs"][0]
        or packet.get("owner_identity") != node["owner_identity"]
        or packet.get("validator_identity") != node["validator_identity"]
        or packet.get("owner_run_id") != payload["owner_run_id"]
        or packet.get("validator_run_id") != payload["validator_run_id"]
        or packet.get("action_ref") != node["action_ref"]
        or packet.get("scope_sha256") != expected_scope
        or packet.get("context_bundle_sha256") != payload["context_bundle_sha256"]
        or packet.get("capability_receipt_sha256") != capability["receipt_sha256"]
        or packet.get("capability_request_sha256") != request["request_sha256"]
        or packet.get("capability_decision_sha256") != decision["decision_sha256"]
    ):
        raise _error("E_V265_MEMBER_BINDING", "Member Packet dispatch binding differs")
    require_utc_timestamp(
        packet["issued_at"],
        error=lambda message: _error("E_V265_MEMBER_BINDING", message),
        label="member_packet.issued_at",
    )
    if timestamp_value(packet["issued_at"]) > occurred:
        raise _error("E_V265_MEMBER_BINDING", "Member Packet occurs after start")
    if payload["owner_run_id"] == payload["validator_run_id"]:
        raise _error("E_V265_MEMBER_IDENTITY", "Owner and Validator runs must differ")
    return copy.deepcopy(dict(packet)), capability, request, decision


ARTIFACT_FIELDS = frozenset(
    {"schema_version", "receipt_id", "graph_contract_sha256", "run_id", "node_id", "attempt",
     "artifact_id", "output_port_id", "schema_ref", "artifact_sha256", "source_revision",
     "freshness_state", "sensitivity", "evidence_refs", "issued_at", "receipt_sha256"}
)


def _validate_artifacts(
    graph: Mapping[str, Any], event: Mapping[str, Any], node: Mapping[str, Any]
) -> list[dict[str, Any]]:
    raw = event["payload"]["artifact_receipts"]
    if not isinstance(raw, list):
        raise _error("E_V265_RUNTIME_OUTCOME", "artifact_receipts must be an array")
    ports = {item["port_id"]: item for item in node["output_ports"]}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        receipt = _exact(item, ARTIFACT_FIELDS, "Artifact Receipt", "E_V265_RUNTIME_OUTCOME")
        _require_self_digest(receipt, "receipt_sha256", "E_V265_RUNTIME_OUTCOME", "Artifact Receipt")
        port = ports.get(receipt["output_port_id"])
        if (
            port is None
            or receipt["output_port_id"] in seen
            or receipt["graph_contract_sha256"] != graph["receipt_sha256"]
            or receipt["run_id"] != event["run_id"]
            or receipt["node_id"] != node["node_id"]
            or receipt["attempt"] != event["attempt"]
            or receipt["schema_ref"] != port["schema_ref"]
            or receipt["sensitivity"] != port["sensitivity"]
            or receipt["freshness_state"] != "current"
            or not is_sha256(receipt["artifact_sha256"])
        ):
            raise _error("E_V265_RUNTIME_OUTCOME", "Artifact Receipt binding differs")
        _strings(receipt["evidence_refs"], "Artifact evidence_refs", allow_empty=False)
        seen.add(receipt["output_port_id"])
        results.append(copy.deepcopy(receipt))
    missing = sorted(port_id for port_id, port in ports.items() if port["required"] and port_id not in seen)
    if missing:
        raise _error("E_V265_RUNTIME_OUTCOME", f"required output receipts are absent: {missing}")
    return sorted(results, key=lambda item: item["output_port_id"])


VALIDATION_FIELDS = frozenset(
    {"schema_version", "receipt_id", "graph_contract_sha256", "node_id", "task_id", "attempt",
     "observed_outcome", "validation_state", "owner_run_id", "validator_identity", "validator_run_id",
     "actor_relationship", "artifact_receipt_sha256s", "evidence_refs", "issued_at", "receipt_sha256"}
)


def _validate_node_validation(
    graph: Mapping[str, Any], event: Mapping[str, Any], node: Mapping[str, Any], state: Mapping[str, Any]
) -> dict[str, Any]:
    receipt = _exact(
        event["payload"]["validation_receipt"],
        VALIDATION_FIELDS,
        "Node Validation Receipt",
        "E_V265_RUNTIME_VALIDATOR",
    )
    _require_self_digest(receipt, "receipt_sha256", "E_V265_RUNTIME_VALIDATOR", "Node Validation Receipt")
    artifact_digests = [item["receipt_sha256"] for item in state["artifact_receipts"]]
    if (
        receipt["graph_contract_sha256"] != graph["receipt_sha256"]
        or receipt["node_id"] != node["node_id"]
        or receipt["task_id"] != node["task_refs"][0]
        or receipt["attempt"] != state["attempt"]
        or receipt["observed_outcome"] != state["outcome"]
        or receipt["validation_state"] != event["payload"]["validation_state"]
        or receipt["owner_run_id"] != state["owner_run_id"]
        or receipt["validator_identity"] != node["validator_identity"]
        or receipt["validator_run_id"] != event["payload"]["validator_run_id"]
        or receipt["validator_run_id"] == state["owner_run_id"]
        or receipt["artifact_receipt_sha256s"] != artifact_digests
        or event["payload"]["observed_outcome"] != state["outcome"]
    ):
        raise _error("E_V265_RUNTIME_VALIDATOR", "Node Validation Receipt binding differs")
    return receipt


GATE_RECEIPT_FIELDS = frozenset(
    {"schema_version", "receipt_id", "graph_contract_sha256", "run_id", "gate_id", "gate_type",
     "decision", "authority_identity", "actor_relationship", "evidence_refs", "observed_facts",
     "issued_at", "expires_at", "receipt_sha256"}
)


def _validate_gate_receipt(
    graph: Mapping[str, Any], event: Mapping[str, Any]
) -> dict[str, Any]:
    payload = event["payload"]
    receipt = _exact(payload["gate_receipt"], GATE_RECEIPT_FIELDS, "Gate Receipt", "E_V265_RUNTIME_GATE")
    _require_self_digest(receipt, "receipt_sha256", "E_V265_RUNTIME_GATE", "Gate Receipt")
    gates = {item["gate_id"]: item for item in graph["gates"]}
    gate = gates.get(payload["gate_id"])
    if gate is None or gate["gate_type"] == "human_approval":
        raise _error("E_V265_RUNTIME_GATE", "Gate Receipt does not bind a non-human Gate")
    expected_decision = "passed" if event["event_type"] == "gate.passed" else "rejected"
    for field in ("issued_at", "expires_at"):
        require_utc_timestamp(
            receipt[field],
            error=lambda message: _error("E_V265_RUNTIME_GATE", message),
            label=f"gate_receipt.{field}",
        )
    if (
        receipt["schema_version"] != "goal-teams-gate-receipt-v2.65"
        or receipt["graph_contract_sha256"] != graph["receipt_sha256"]
        or receipt["run_id"] != event["run_id"]
        or receipt["gate_id"] != gate["gate_id"]
        or receipt["gate_type"] != gate["gate_type"]
        or receipt["decision"] != expected_decision
        or payload["decision"] != expected_decision
        or payload["gate_decision_sha256"] != receipt["receipt_sha256"]
        or event["actor_identity"] != receipt["authority_identity"]
        or timestamp_value(receipt["issued_at"])
        > timestamp_value(event["occurred_at"])
        or timestamp_value(event["occurred_at"])
        > timestamp_value(receipt["expires_at"])
    ):
        raise _error("E_V265_RUNTIME_GATE", "Gate Receipt binding or freshness differs")
    _strings(receipt["evidence_refs"], "Gate Receipt evidence_refs", allow_empty=False)
    if not isinstance(receipt["observed_facts"], Mapping):
        raise _error("E_V265_RUNTIME_GATE", "Gate observed_facts must be an object")
    observed = dict(receipt["observed_facts"])
    if gate["gate_type"] == "evidence":
        required = list(gate["required_evidence_types"])
        if set(observed) != set(required):
            raise _error("E_V265_RUNTIME_GATE", "Evidence Gate exact set differs")
        identities = list(observed.values())
        if (
            len(identities) != len(set(identities))
            or not all(is_sha256(item) for item in identities)
            or not receipt["evidence_refs"]
        ):
            raise _error("E_V265_RUNTIME_GATE", "Evidence Gate identities are invalid")
    elif gate["gate_type"] == "condition":
        fields = {
            "fact_ref",
            "operator",
            "expected_value",
            "observed_value",
            "matched",
        }
        if set(observed) != fields:
            raise _error("E_V265_RUNTIME_GATE", "Condition Gate observed facts differ")
        condition = gate["condition"]
        if (
            observed["fact_ref"] != condition["fact_ref"]
            or observed["operator"] != condition["operator"]
            or observed["expected_value"] != condition["expected_value"]
            or not is_json_scalar(observed["observed_value"])
            or type(observed["matched"]) is not bool
        ):
            raise _error("E_V265_RUNTIME_GATE", "Condition Gate binding differs")
        operator = condition["operator"]
        actual = observed["observed_value"]
        expected = condition["expected_value"]
        matched = {
            "equals": actual == expected,
            "not_equals": actual != expected,
            "present": actual is not None,
            "absent": actual is None,
        }[operator]
        if observed["matched"] is not matched or (expected_decision == "passed") is not matched:
            raise _error("E_V265_RUNTIME_GATE", "Condition Gate decision differs")
    return receipt


APPROVAL_FIELDS = frozenset(
    {"schema_version", "approval_id", "issuer", "issuer_key_id", "issuer_assurance", "actor_relationship",
     "proof_strength", "interrupt_id", "gate_id", "scope_sha256", "decision", "not_before", "issued_at",
     "expires_at", "permission_effect", "attestation_ref", "receipt_sha256"}
)
APPROVAL_DECISION_FIELDS = frozenset(
    {"schema_version", "verified", "issuer", "issuer_key_id", "issuer_assurance", "actor_relationship",
     "proof_strength", "permission_effect", "freshness_state", "scope_sha256", "interrupt_id",
     "approval_receipt_sha256", "expires_at", "reason_code", "decision_sha256"}
)


def _validate_approval(
    graph: Mapping[str, Any], event: Mapping[str, Any], node: Mapping[str, Any], interrupt: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = event["payload"]
    receipt = _exact(payload["approval_receipt"], APPROVAL_FIELDS, "Approval Receipt", "E_V265_RUNTIME_GATE")
    decision = _exact(payload["approval_decision"], APPROVAL_DECISION_FIELDS, "Approval Decision", "E_V265_RUNTIME_GATE")
    _require_self_digest(receipt, "receipt_sha256", "E_V265_RUNTIME_GATE", "Approval Receipt")
    _require_self_digest(decision, "decision_sha256", "E_V265_RUNTIME_GATE", "Approval Decision")
    gate = next(
        (item for item in graph["gates"] if item["gate_id"] == interrupt["gate_id"]),
        None,
    )
    for field in ("not_before", "issued_at", "expires_at"):
        require_utc_timestamp(
            receipt[field],
            error=lambda message: _error("E_V265_RUNTIME_GATE", message),
            label=f"approval_receipt.{field}",
        )
    require_utc_timestamp(
        decision["expires_at"],
        error=lambda message: _error("E_V265_RUNTIME_GATE", message),
        label="approval_decision.expires_at",
    )
    action = _action_for_node(graph, node)
    expected_permission = (
        "external_side_effects"
        if action["effect"] == "external_write"
        else "local_execution"
    )
    if (
        gate is None
        or gate["gate_type"] != "human_approval"
        or receipt["schema_version"]
        != "goal-teams-host-approval-receipt-v2.65"
        or decision["schema_version"]
        != "goal-teams-host-approval-decision-v2.65"
        or payload["decision"] != "approve"
        or receipt["decision"] != "approve"
        or receipt["interrupt_id"] != payload["interrupt_id"]
        or receipt["interrupt_id"] != interrupt["interrupt_id"]
        or receipt["gate_id"] != interrupt["gate_id"]
        or receipt["issuer"] != gate["authority_ref"]
        or receipt["issuer_assurance"] != "externally_attested"
        or receipt["actor_relationship"] != "independent"
        or receipt["proof_strength"] != "externally_attested"
        or receipt["permission_effect"] != expected_permission
        or not is_non_empty_string(receipt["attestation_ref"])
        or receipt["scope_sha256"] != _scope_sha(node)
        or decision["verified"] is not True
        or decision["interrupt_id"] != receipt["interrupt_id"]
        or decision["approval_receipt_sha256"] != receipt["receipt_sha256"]
        or decision["scope_sha256"] != receipt["scope_sha256"]
        or decision["issuer"] != receipt["issuer"]
        or decision["issuer_key_id"] != receipt["issuer_key_id"]
        or decision["issuer_assurance"] != receipt["issuer_assurance"]
        or decision["actor_relationship"] != receipt["actor_relationship"]
        or decision["proof_strength"] != receipt["proof_strength"]
        or decision["permission_effect"] != receipt["permission_effect"]
        or decision["freshness_state"] != "current"
        or decision["expires_at"] != receipt["expires_at"]
    ):
        raise _error("E_V265_RUNTIME_GATE", "Approval binding differs")
    occurred = timestamp_value(event["occurred_at"])
    if not (
        timestamp_value(receipt["not_before"])
        <= timestamp_value(receipt["issued_at"])
        <= occurred
        <= timestamp_value(receipt["expires_at"])
    ):
        raise _error("E_V265_RUNTIME_GATE", "Approval is expired or not yet valid")
    return receipt, decision


def _validate_host_handle(
    graph: Mapping[str, Any], event: Mapping[str, Any]
) -> dict[str, Any]:
    payload = event["payload"]
    handle = _exact(
        payload["host_handle"],
        HOST_HANDLE_FIELDS,
        "Host Handle",
        "E_V265_HOST_OBSERVATION",
    )
    _require_self_digest(
        handle, "handle_sha256", "E_V265_HOST_OBSERVATION", "Host Handle"
    )
    if (
        handle["schema_version"] != "goal-teams-host-handle-v2.65"
        or handle["state"] != "prepared"
        or handle["run_id"] != event["run_id"]
        or handle["node_id"] != event["node_id"]
        or handle["attempt"] != event["attempt"]
        or handle["dispatch_sha256"] != payload["dispatch_sha256"]
        or not is_sha256(handle["dispatch_sha256"])
    ):
        raise _error("E_V265_HOST_OBSERVATION", "prepared Host Handle binding differs")
    require_utc_timestamp(
        handle["prepared_at"],
        error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
        label="host_handle.prepared_at",
    )
    if timestamp_value(handle["prepared_at"]) > timestamp_value(event["occurred_at"]):
        raise _error("E_V265_HOST_OBSERVATION", "Host Handle occurs after Event")
    return handle


def _validate_host_execution(
    event: Mapping[str, Any], host: Mapping[str, Any]
) -> dict[str, Any]:
    payload = event["payload"]
    receipt = _exact(
        payload["execution_receipt"],
        HOST_EXECUTION_FIELDS,
        "Host Execution Receipt",
        "E_V265_HOST_OBSERVATION",
    )
    _require_self_digest(
        receipt,
        "receipt_sha256",
        "E_V265_HOST_OBSERVATION",
        "Host Execution Receipt",
    )
    if (
        receipt["schema_version"]
        != "goal-teams-host-execution-receipt-v2.65"
        or receipt["state"] != "running"
        or receipt["host_handle_id"] != host["host_handle_id"]
        or receipt["handle_sha256"] != host["handle_sha256"]
        or receipt["handle_sha256"] != payload["host_handle_sha256"]
        or receipt["dispatch_sha256"] != host["dispatch_sha256"]
        or receipt["adapter_id"] != host["adapter_id"]
        or receipt["proof_strength"] != host["proof_strength"]
    ):
        raise _error("E_V265_HOST_OBSERVATION", "Host Execution binding differs")
    require_utc_timestamp(
        receipt["started_at"],
        error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
        label="execution_receipt.started_at",
    )
    if timestamp_value(receipt["started_at"]) > timestamp_value(event["occurred_at"]):
        raise _error("E_V265_HOST_OBSERVATION", "Host Execution occurs after Event")
    return receipt


def _validate_host_observation(
    event: Mapping[str, Any], host: Mapping[str, Any]
) -> tuple[str, dict[str, Any], str]:
    payload = event["payload"]
    kind = payload["observation_type"]
    fields = {
        "probe": (HOST_PROBE_FIELDS, "receipt_sha256"),
        "cancel": (HOST_CANCEL_FIELDS, "decision_sha256"),
        "readback": (HOST_READBACK_FIELDS, "receipt_sha256"),
    }
    if kind not in fields:
        raise _error("E_V265_HOST_OBSERVATION", "Host observation type differs")
    receipt_fields, digest_field = fields[kind]
    receipt = _exact(
        payload["observation_receipt"],
        receipt_fields,
        "Host Observation Receipt",
        "E_V265_HOST_OBSERVATION",
    )
    _require_self_digest(
        receipt,
        digest_field,
        "E_V265_HOST_OBSERVATION",
        "Host Observation Receipt",
    )
    if (
        payload["host_handle_id"] != host["host_handle_id"]
        or receipt["host_handle_id"] != host["host_handle_id"]
        or payload["observation_sha256"] != receipt[digest_field]
    ):
        raise _error("E_V265_HOST_OBSERVATION", "Host observation binding differs")
    if kind == "probe":
        if (
            receipt["schema_version"] != "goal-teams-host-probe-receipt-v2.65"
            or receipt["adapter_id"] != host["adapter_id"]
            or receipt["run_id"] != host["run_id"]
            or receipt["node_id"] != host["node_id"]
            or receipt["attempt"] != host["attempt"]
            or receipt["observed_state"]
            not in {"prepared", "running", "terminal", "cancelled", "absent", "indeterminate"}
            or receipt["quiescent"]
            is not (receipt["observed_state"] in {"terminal", "cancelled", "absent"})
        ):
            raise _error("E_V265_HOST_OBSERVATION", "Host Probe binding differs")
        require_utc_timestamp(
            receipt["observed_at"],
            error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
            label="host_probe.observed_at",
        )
        _strings(receipt["evidence_refs"], "Host Probe evidence_refs", allow_empty=False)
        state = receipt["observed_state"]
    elif kind == "cancel":
        if (
            receipt["schema_version"] != "goal-teams-host-cancel-result-v2.65"
            or receipt["observed_state"]
            not in {"cancelled_before_start", "cancelled", "running", "terminal", "indeterminate"}
            or type(receipt["cancelled"]) is not bool
            or (receipt["cancelled"] is True)
            is not (receipt["observed_state"] in {"cancelled_before_start", "cancelled"})
        ):
            raise _error("E_V265_HOST_OBSERVATION", "Host Cancel binding differs")
        state = (
            "cancelled"
            if receipt["cancelled"] is True
            else receipt["observed_state"]
        )
    else:
        if (
            receipt["schema_version"]
            != "goal-teams-host-side-effect-readback-v2.65"
            or receipt["adapter_id"] != host["adapter_id"]
            or receipt["run_id"] != host["run_id"]
            or receipt["node_id"] != host["node_id"]
            or receipt["attempt"] != host["attempt"]
            or receipt["handle_sha256"] != host["handle_sha256"]
            or receipt["dispatch_sha256"] != host["dispatch_sha256"]
            or receipt["observed_state"]
            not in {"confirmed", "absent", "indeterminate"}
        ):
            raise _error("E_V265_HOST_OBSERVATION", "Host Readback binding differs")
        require_utc_timestamp(
            receipt["observed_at"],
            error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
            label="host_readback.observed_at",
        )
        if receipt["observed_state"] == "confirmed":
            if (
                not is_sha256(receipt["result_digest"])
                or not is_non_empty_string(receipt["external_receipt_ref"])
                or not is_non_empty_string(receipt["issuer"])
                or receipt["issuer_assurance"] != "externally_attested"
                or receipt["proof_strength"] != "externally_attested"
                or not is_non_empty_string(receipt["attestation_ref"])
            ):
                raise _error("E_V265_HOST_OBSERVATION", "Host Readback assurance differs")
        elif receipt["observed_state"] == "absent" and (
            receipt["result_digest"] is not None
            or receipt["external_receipt_ref"] is not None
        ):
            raise _error("E_V265_HOST_OBSERVATION", "absent Host Readback contains a result")
        state = host["state"]
    observed_at = receipt.get("observed_at")
    if observed_at is not None and timestamp_value(observed_at) > timestamp_value(
        event["occurred_at"]
    ):
        raise _error("E_V265_HOST_OBSERVATION", "Host observation occurs after Event")
    return kind, receipt, state


def _artifact_satisfies_edge(edge: Mapping[str, Any], nodes: Mapping[str, Any]) -> bool:
    source = nodes[edge["source_node_id"]]
    for binding in edge["data_bindings"]:
        found = any(
            item.get("output_port_id") == binding["output_port_id"]
            and item.get("schema_ref") == binding["schema_ref"]
            and item.get("freshness_state") == "current"
            for item in source["artifact_receipts"]
        )
        if not found:
            return False
    return True


def _edge_satisfied(
    edge: Mapping[str, Any], nodes: Mapping[str, Any], gate_states: Mapping[str, str]
) -> bool:
    source = nodes[edge["source_node_id"]]
    if source["validation_state"] != "passed" or source["outcome"] not in edge["accepted_outcomes"]:
        return False
    if edge["gate_ref"] is not None and gate_states.get(edge["gate_ref"], "pending") != "passed":
        return False
    return edge["edge_type"] != "data" or _artifact_satisfies_edge(edge, nodes)


def _ready_descriptor(
    graph: Mapping[str, Any], node: Mapping[str, Any], projection: Mapping[str, Any]
) -> dict[str, Any] | None:
    state = projection["nodes"][node["node_id"]]
    if state["execution_state"] != "pending":
        return None
    for gate_id in node["gate_refs"]:
        if projection["gate_states"].get(gate_id, "pending") != "passed":
            return None
    incoming_ids = graph["predecessor_map"].get(node["node_id"], [])
    edge_by_id = {item["edge_id"]: item for item in graph["edges"]}
    if not incoming_ids:
        return {
            "node_id": node["node_id"],
            "task_id": node["task_refs"][0],
            "satisfied_edge_ids": [],
            "fan_in_mode": "root",
            "required_edge_count": 0,
            "satisfied_edge_count": 0,
            "next_attempt": state["attempt"] + 1,
            "timeout_seconds": node["timeout_seconds"],
        }
    fan = node["fan_in"]
    edge_ids = fan["edge_ids"]
    required_inputs = {
        port["port_id"] for port in node["input_ports"] if port["required"]
    }
    required_data_edges: dict[str, list[str]] = {
        port_id: [] for port_id in required_inputs
    }
    for edge_id in edge_ids:
        edge = edge_by_id[edge_id]
        if edge["edge_type"] != "data":
            continue
        for binding in edge["data_bindings"]:
            input_port_id = binding["input_port_id"]
            if input_port_id in required_data_edges:
                required_data_edges[input_port_id].append(edge_id)
    if any(len(bound_edges) != 1 for bound_edges in required_data_edges.values()):
        return None
    if any(
        not _edge_satisfied(
            edge_by_id[bound_edges[0]],
            projection["nodes"],
            projection["gate_states"],
        )
        for bound_edges in required_data_edges.values()
    ):
        return None
    satisfied = [
        edge_id
        for edge_id in edge_ids
        if _edge_satisfied(edge_by_id[edge_id], projection["nodes"], projection["gate_states"])
    ]
    mode = fan["mode"]
    if mode == "all":
        required = len(edge_ids)
    elif mode == "any":
        required = 1
    elif fan["quorum_count"] is not None:
        required = fan["quorum_count"]
    else:
        required = math.ceil(len(edge_ids) * fan["quorum_ratio_basis_points"] / 10000)
    if len(satisfied) < required:
        return None
    return {
        "node_id": node["node_id"],
        "task_id": node["task_refs"][0],
        "satisfied_edge_ids": sorted(satisfied),
        "fan_in_mode": mode,
        "required_edge_count": required,
        "satisfied_edge_count": len(satisfied),
        "next_attempt": state["attempt"] + 1,
        "timeout_seconds": node["timeout_seconds"],
    }


def _initial_projection(graph: Mapping[str, Any], run_id: str, bindings: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-graph-projection-v2.65",
        "run_id": run_id,
        "revision": 0,
        "event_count": 0,
        "last_event_sha256": ZERO_SHA256,
        "bindings": copy.deepcopy(dict(bindings)),
        "nodes": {item["node_id"]: _node_template() for item in graph["nodes"]},
        "gate_states": {item["gate_id"]: "pending" for item in graph["gates"]},
        "idempotency": {},
        "interrupts": {},
        "traversal_counts": {},
        "host_handles": {},
    }


def _apply_event(
    graph: Mapping[str, Any],
    projection: dict[str, Any],
    event: Mapping[str, Any],
    terminal_at: dict[str, str],
    host_lineage: dict[str, dict[str, Any]],
) -> None:
    event_type = event["event_type"]
    payload = event["payload"]
    if event_type == "run.created":
        if projection["revision"] != 0 or payload["graph_receipt_sha256"] != graph["receipt_sha256"]:
            raise _error("E_V265_RUNTIME_TRANSITION", "run genesis differs")
        return
    if projection["revision"] == 0:
        raise _error("E_V265_RUNTIME_TRANSITION", "run.created must be first")
    if event_type.startswith("gate."):
        gate_id = payload["gate_id"]
        gate = next(
            (item for item in graph["gates"] if item["gate_id"] == gate_id),
            None,
        )
        if gate is None or gate_id not in projection["gate_states"]:
            raise _error("E_V265_RUNTIME_GATE", "Gate is absent")
        if projection["gate_states"][gate_id] != "pending":
            raise _error("E_V265_RUNTIME_GATE", "Gate is already terminal")
        if event_type in {"gate.passed", "gate.rejected"}:
            _validate_gate_receipt(graph, event)
            projection["gate_states"][gate_id] = "passed" if event_type == "gate.passed" else "rejected"
        else:
            deadline = require_utc_timestamp(
                payload["deadline"],
                error=lambda message: _error("E_V265_RUNTIME_GATE", message),
                label="deadline",
            )
            if (
                timestamp_value(event["occurred_at"]) < timestamp_value(deadline)
                or payload["on_timeout_outcome"] != gate["on_timeout_outcome"]
            ):
                raise _error(
                    "E_V265_RUNTIME_GATE", "Gate timeout deadline or outcome differs"
                )
            projection["gate_states"][gate_id] = "timed_out"
        return
    if event_type == "checkpoint.created":
        if payload["checkpoint_revision"] != projection["revision"]:
            raise _error("E_V265_RUNTIME_CHECKPOINT_STALE", "checkpoint revision differs")
        return

    node_id = event["node_id"]
    node = _node_by_id(graph, node_id)
    state = projection["nodes"][node_id]
    before = state["execution_state"]
    if event_type == "host.prepared":
        if before != "claimed":
            raise _error(
                "E_V265_HOST_LIFECYCLE", "Host prepare requires a claimed Node"
            )
        handle = _validate_host_handle(graph, event)
        handle_id = handle["host_handle_id"]
        if handle_id in projection["host_handles"]:
            raise _error("E_V265_HOST_LIFECYCLE", "Host Handle already exists")
        projection["host_handles"][handle_id] = {
            "run_id": event["run_id"],
            "node_id": node_id,
            "attempt": event["attempt"],
            "handle_sha256": handle["handle_sha256"],
            "dispatch_sha256": handle["dispatch_sha256"],
            "state": "prepared",
            "execution_receipt_sha256": None,
            "last_observation_type": None,
            "last_observation_sha256": None,
            "proof_strength": handle["proof_strength"],
            "prepared_at": handle["prepared_at"],
            "started_at": None,
        }
        host_lineage[handle_id] = copy.deepcopy(handle)
        state["host_handle_id"] = handle_id
        state["host_binding_assurance"] = "confirmed"
        return
    if event_type == "host.execution_started":
        handle_id = state["host_handle_id"]
        host = projection["host_handles"].get(handle_id)
        if before != "active" or host is None or host["state"] != "prepared":
            raise _error(
                "E_V265_HOST_LIFECYCLE", "Host execute requires a prepared active Node"
            )
        lineage = host_lineage.get(handle_id)
        if lineage is None:
            raise _error("E_V265_HOST_LIFECYCLE", "prepared Host lineage is absent")
        receipt = _validate_host_execution(event, lineage)
        host.update(
            {
                "state": "running",
                "execution_receipt_sha256": receipt["receipt_sha256"],
                "started_at": receipt["started_at"],
            }
        )
        return
    if event_type == "host.observation_recorded":
        handle_id = event["payload"]["host_handle_id"]
        host = projection["host_handles"].get(handle_id)
        if host is None or host["node_id"] != node_id or host["attempt"] != event["attempt"]:
            raise _error("E_V265_HOST_OBSERVATION", "Host observation Handle differs")
        lineage = host_lineage.get(handle_id)
        if lineage is None:
            raise _error("E_V265_HOST_OBSERVATION", "Host observation lineage is absent")
        if (
            event["payload"]["observation_type"] == "readback"
            and host["state"] != "running"
        ):
            raise _error(
                "E_V265_HOST_LIFECYCLE",
                "Host readback requires a running execution",
            )
        kind, receipt, observed_state = _validate_host_observation(event, lineage)
        if kind == "readback":
            # Readback attests the external result; it does not rewind the
            # already durable Host execution lifecycle to the inert Handle.
            observed_state = host["state"]
        if observed_state in {"terminal", "cancelled", "indeterminate"}:
            host["state"] = observed_state
        elif observed_state == "absent":
            host["state"] = "indeterminate"
        elif observed_state in {"prepared", "running"}:
            host["state"] = observed_state
        host["last_observation_type"] = kind
        digest_field = "decision_sha256" if kind == "cancel" else "receipt_sha256"
        host["last_observation_sha256"] = receipt[digest_field]
        if kind == "readback":
            lineage["_last_readback"] = copy.deepcopy(receipt)
        return
    if event_type == "node.ready":
        descriptor = _ready_descriptor(graph, node, projection)
        if descriptor is None:
            inbound = graph["predecessor_map"].get(node_id, [])
            if inbound:
                raise _error("E_V265_RUNTIME_PREDECESSOR", "predecessor, fan-in, Gate, or Data is unsatisfied")
            raise _error("E_V265_RUNTIME_GATE", "Node precondition Gate is unsatisfied")
        observed = {key: payload[key] for key in ("satisfied_edge_ids", "fan_in_mode", "required_edge_count", "satisfied_edge_count")}
        expected = {key: descriptor[key] for key in observed}
        if observed != expected:
            raise _error("E_V265_RUNTIME_FAN_IN", "ready Event predicate differs")
        state["execution_state"] = "ready"
    elif event_type == "node.claimed":
        if before != "ready":
            raise _error("E_V265_RUNTIME_TRANSITION", "only ready Node can be claimed")
        if event["attempt"] != state["attempt"] + 1 or event["attempt"] > node["budget"]["attempts"]:
            raise _error("E_V265_RUNTIME_ATTEMPT_BUDGET", "Node attempt budget is exhausted")
        require_utc_timestamp(payload["lease_expires_at"], error=lambda message: _error("E_V265_RUNTIME_LEASE", message), label="lease_expires_at")
        if timestamp_value(payload["lease_expires_at"]) <= timestamp_value(event["occurred_at"]):
            raise _error("E_V265_RUNTIME_LEASE", "lease does not extend past claim")
        state.update(
            {
                "execution_state": "claimed",
                "attempt": event["attempt"],
                "worker_id": payload["worker_id"],
                "lease_id": payload["lease_id"],
                "lease_expires_at": payload["lease_expires_at"],
            }
        )
    elif event_type == "node.started":
        if before != "claimed" or event["attempt"] != state["attempt"]:
            raise _error("E_V265_RUNTIME_TRANSITION", "only claimed Node can start")
        if timestamp_value(state["lease_expires_at"]) < timestamp_value(event["occurred_at"]):
            raise _error("E_V265_RUNTIME_LEASE_EXPIRED", "Node lease expired before start")
        packet, capability, request, decision = _validate_started_payload(graph, event, node)
        handle_id = payload["host_handle_id"]
        host = projection["host_handles"].get(handle_id)
        if host is not None:
            if (
                host["state"] != "prepared"
                or host["run_id"] != event["run_id"]
                or host["node_id"] != node_id
                or host["attempt"] != event["attempt"]
            ):
                raise _error("E_V265_HOST_LIFECYCLE", "node.started Host Handle differs")
            assurance = "confirmed"
        else:
            assurance = "legacy_unobserved"
        state.update(
            {
                "execution_state": "active",
                "owner_run_id": payload["owner_run_id"],
                "validator_run_id": payload["validator_run_id"],
                "member_packet_sha256": packet["packet_sha256"],
                "context_bundle_sha256": payload["context_bundle_sha256"],
                "capability_receipt_sha256": capability["receipt_sha256"],
                "capability_request_sha256": request["request_sha256"],
                "capability_decision_sha256": decision["decision_sha256"],
                "host_handle_id": handle_id,
                "host_binding_assurance": assurance,
            }
        )
    elif event_type == "node.heartbeat":
        if before not in {"claimed", "active"} or payload["lease_id"] != state["lease_id"] or payload["previous_expires_at"] != state["lease_expires_at"]:
            raise _error("E_V265_RUNTIME_LEASE", "heartbeat lease differs")
        if timestamp_value(payload["new_expires_at"]) <= timestamp_value(payload["previous_expires_at"]):
            raise _error("E_V265_RUNTIME_LEASE", "heartbeat does not extend lease")
        state["lease_expires_at"] = payload["new_expires_at"]
    elif event_type == "node.outcome_recorded":
        if before != "active" or payload["owner_run_id"] != state["owner_run_id"] or event["actor_identity"] != state["owner_run_id"]:
            raise _error("E_V265_RUNTIME_TRANSITION", "Outcome writer or state differs")
        if payload["outcome"] not in TERMINAL_OUTCOMES:
            raise _error("E_V265_RUNTIME_OUTCOME", "Outcome is not terminal")
        host_id = state["host_handle_id"]
        if (
            state["host_binding_assurance"] == "confirmed"
            and host_id in projection["host_handles"]
            and projection["host_handles"][host_id]["state"] != "running"
        ):
            raise _error(
                "E_V265_HOST_LIFECYCLE",
                "confirmed Host must start before a Node Outcome",
            )
        artifacts = _validate_artifacts(graph, event, node)
        state.update(
            {
                "execution_state": "terminal",
                "outcome": payload["outcome"],
                "validation_state": "not_run",
                "artifact_receipts": artifacts,
                "lease_id": None,
                "lease_expires_at": None,
                "evidence_refs": sorted(set(state["evidence_refs"] + list(event["evidence_refs"]))),
            }
        )
        terminal_at[node_id] = event["occurred_at"]
        if state["host_handle_id"] in projection["host_handles"]:
            projection["host_handles"][state["host_handle_id"]]["state"] = "terminal"
    elif event_type == "node.validation_recorded":
        if before != "terminal" or state["validation_state"] != "not_run":
            raise _error("E_V265_RUNTIME_TRANSITION", "Node Outcome is not awaiting validation")
        receipt = _validate_node_validation(graph, event, node, state)
        if event["actor_identity"] != receipt["validator_run_id"]:
            raise _error("E_V265_RUNTIME_VALIDATOR", "Validator actor differs")
        state["validation_state"] = receipt["validation_state"]
        state["validator_run_id"] = receipt["validator_run_id"]
        state["evidence_refs"] = sorted(set(state["evidence_refs"] + list(event["evidence_refs"])))
    elif event_type == "node.blocked":
        if before not in {"pending", "ready", "claimed", "active"}:
            raise _error("E_V265_RUNTIME_TRANSITION", "Node cannot be blocked from current state")
        state.update({"execution_state": "terminal", "outcome": "blocked", "lease_id": None, "lease_expires_at": None})
    elif event_type == "node.interrupted":
        if before != "active":
            raise _error("E_V265_RUNTIME_TRANSITION", "only active Node can be interrupted")
        gate_id = payload["gate_id"]
        gate = next((item for item in graph["gates"] if item["gate_id"] == gate_id), None)
        referenced = {gate_ref for item in graph["nodes"] for gate_ref in item["gate_refs"]}
        if (
            gate is None
            or gate["gate_type"] != "human_approval"
            or gate_id in referenced
            or projection["gate_states"].get(gate_id) != "pending"
        ):
            raise _error("E_V265_RUNTIME_GATE", "interrupt Gate is not a global human Gate")
        if payload["capability_receipt_sha256"] != state["capability_receipt_sha256"]:
            raise _error("E_V265_RUNTIME_GATE", "interrupt capability binding differs")
        projection["interrupts"][payload["interrupt_id"]] = {
            "run_id": event["run_id"],
            "interrupt_id": payload["interrupt_id"],
            "node_id": node_id,
            "gate_id": gate_id,
            "state": "waiting_user",
            "approval_receipt_sha256": None,
            "updated_at": event["occurred_at"],
        }
        state.update({"execution_state": "waiting_user", "outcome": "waiting_user", "lease_id": None, "lease_expires_at": None})
    elif event_type == "node.resumed":
        interrupt = projection["interrupts"].get(payload["interrupt_id"])
        if (
            before != "waiting_user"
            or interrupt is None
            or interrupt["state"] != "waiting_user"
            or interrupt["node_id"] != node_id
            or projection["gate_states"].get(interrupt["gate_id"]) != "pending"
        ):
            raise _error("E_V265_RUNTIME_GATE", "interrupt binding differs")
        receipt, decision = _validate_approval(graph, event, node, interrupt)
        interrupt.update({"state": "resolved", "approval_receipt_sha256": receipt["receipt_sha256"], "updated_at": event["occurred_at"]})
        projection["gate_states"][interrupt["gate_id"]] = "passed"
        state.update({"execution_state": "ready", "outcome": "pending", "approval_decision_sha256": decision["decision_sha256"]})
    elif event_type == "node.cancelled":
        if before not in {"pending", "ready", "claimed", "active", "waiting_user"}:
            raise _error("E_V265_RUNTIME_TRANSITION", "Node cannot be cancelled")
        state.update({"execution_state": "cancelled", "outcome": "cancelled", "lease_id": None, "lease_expires_at": None})
    elif event_type == "node.lease_expired":
        if before not in {"claimed", "active"} or payload["lease_id"] != state["lease_id"] or payload["lease_expires_at"] != state["lease_expires_at"]:
            raise _error("E_V265_RUNTIME_LEASE", "expired lease binding differs")
        if timestamp_value(payload["lease_expires_at"]) >= timestamp_value(event["occurred_at"]):
            raise _error("E_V265_RUNTIME_LEASE_EXPIRED", "lease has not expired")
        if payload["recovery_decision"] == "ready" and state["attempt"] < node["budget"]["attempts"]:
            state.update({"execution_state": "ready", "outcome": "pending", "lease_id": None, "lease_expires_at": None})
        else:
            state.update({"execution_state": "terminal", "outcome": "failed", "lease_id": None, "lease_expires_at": None})
    elif event_type == "node.retry_scheduled":
        if not is_int(payload["traversal_count"], minimum=1) or not is_int(
            payload["next_attempt"], minimum=1
        ):
            raise _error(
                "E_V265_RUNTIME_ATTEMPT_BUDGET",
                "retry traversal_count and next_attempt must be positive integers",
            )
        source_edge_id = payload["source_edge_id"]
        previous_count = projection["traversal_counts"].get(source_edge_id, 0)
        if (
            before != "terminal"
            or event["attempt"] != state["attempt"]
            or payload["traversal_count"] != previous_count + 1
            or node_id not in terminal_at
        ):
            raise _error("E_V265_RUNTIME_ATTEMPT_BUDGET", "retry source state differs")
        sentinel = f"retry_policy:{node_id}"
        if source_edge_id == sentinel:
            if (
                node["recovery_policy"]["mode"] != "retry"
                or state["outcome"] not in node["retry_policy"]["retryable_outcomes"]
                or state["validation_state"] not in {"not_run", "rejected", "stale"}
                or payload["traversal_count"] > node["retry_policy"]["max_attempts"] - 1
                or payload["next_attempt"] != state["attempt"] + 1
                or payload["next_attempt"] > node["budget"]["attempts"]
            ):
                raise _error("E_V265_RUNTIME_ATTEMPT_BUDGET", "retry-policy sentinel differs")
            backoff_index = state["attempt"] - 1
            backoff_seconds = node["retry_policy"]["backoff_seconds"]
            if backoff_index < 0 or backoff_index >= len(backoff_seconds):
                raise _error(
                    "E_V265_RUNTIME_ATTEMPT_BUDGET", "retry backoff budget is exhausted"
                )
            if timestamp_value(event["occurred_at"]) < timestamp_value(
                terminal_at[node_id]
            ) + timedelta(seconds=backoff_seconds[backoff_index]):
                raise _error(
                    "E_V265_RUNTIME_ATTEMPT_BUDGET", "retry backoff has not elapsed"
                )
            state.update(
                {
                    "execution_state": "ready",
                    "outcome": "pending",
                    "validation_state": "not_run",
                }
            )
        else:
            edge = next(
                (
                    item
                    for item in graph["edges"]
                    if item["edge_id"] == source_edge_id
                    and item["edge_type"] in {"repeat", "recovery"}
                ),
                None,
            )
            if (
                edge is None
                or edge["source_node_id"] != node_id
                or (
                    edge["edge_type"] == "recovery"
                    and (
                        node["recovery_policy"]["mode"] != "edge"
                        or node["recovery_policy"]["edge_id"] != source_edge_id
                    )
                )
                or state["validation_state"] != "passed"
                or state["outcome"] not in edge["accepted_outcomes"]
                or payload["traversal_count"] > edge["traversal_budget"]
            ):
                raise _error("E_V265_RUNTIME_ATTEMPT_BUDGET", "recovery Edge differs")
            target_id = edge["target_node_id"]
            target = projection["nodes"][target_id]
            if (
                payload["next_attempt"] != target["attempt"] + 1
                or payload["next_attempt"]
                > _node_by_id(graph, target_id)["budget"]["attempts"]
                or target["execution_state"] not in {"terminal", "cancelled", "stale"}
            ):
                raise _error("E_V265_RUNTIME_ATTEMPT_BUDGET", "recovery target differs")
            target.update(
                {
                    "execution_state": "ready",
                    "outcome": "pending",
                    "validation_state": "not_run",
                }
            )
        projection["traversal_counts"][source_edge_id] = payload["traversal_count"]
    elif event_type == "side_effect.intent":
        if before != "active":
            raise _error("E_V265_RUNTIME_TRANSITION", "side effect intent requires active Node")
        key = payload["idempotency_key"]
        if key in projection["idempotency"]:
            raise _error("E_V265_RUNTIME_IDEMPOTENCY", "idempotency key already exists")
        projection["idempotency"][key] = {"node_id": node_id, "state": "pending", "result_digest": None, "updated_at": event["occurred_at"]}
    elif event_type == "side_effect.confirmed":
        record = projection["idempotency"].get(payload["idempotency_key"])
        if record is None or record["node_id"] != node_id or record["state"] != "pending":
            raise _error("E_V265_RUNTIME_IDEMPOTENCY", "idempotency confirmation differs")
        action = _action_for_node(graph, node)
        if action["effect"] == "external_write":
            handle_id = state["host_handle_id"]
            lineage = host_lineage.get(handle_id, {})
            readback = lineage.get("_last_readback")
            host = projection["host_handles"].get(handle_id)
            if (
                not isinstance(readback, Mapping)
                or host is None
                or host["last_observation_type"] != "readback"
                or readback["observed_state"] != "confirmed"
                or readback["idempotency_key"] != payload["idempotency_key"]
                or readback["result_digest"] != payload["result_digest"]
                or readback["receipt_sha256"]
                != payload["readback_receipt_sha256"]
            ):
                raise _error(
                    "E_V265_RUNTIME_RECONCILIATION_REQUIRED",
                    "external confirmation lacks a matching Host readback",
                )
        record.update({"state": "confirmed", "result_digest": payload["result_digest"], "updated_at": event["occurred_at"]})
    elif event_type == "side_effect.reconciliation_required":
        record = projection["idempotency"].get(payload["idempotency_key"])
        if record is None or record["node_id"] != node_id or record["state"] != "pending":
            raise _error("E_V265_RUNTIME_RECONCILIATION_REQUIRED", "reconciliation key differs")
        record.update({"state": "reconciliation_required", "updated_at": event["occurred_at"]})
        state.update({"execution_state": "waiting_user", "outcome": "unverified", "lease_id": None, "lease_expires_at": None})
    elif event_type == "node.stale":
        if before not in {"terminal", "cancelled"}:
            raise _error("E_V265_RUNTIME_TRANSITION", "only terminal Node can become stale")
        state.update({"execution_state": "stale", "outcome": "stale", "validation_state": "stale"})
    else:
        raise _error("E_V265_RUNTIME_EVENT", "unsupported Event type")


def reduce_graph_events(
    compiled_graph: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    *,
    expected_bindings: Mapping[str, str],
) -> dict[str, Any]:
    """Rebuild a read-only projection from canonical Events."""

    validate_runtime_graph_contract(compiled_graph)
    graph = copy.deepcopy(dict(compiled_graph))
    bindings = _validate_bindings(expected_bindings, graph)
    event_list = list(events)
    if not event_list:
        raise _error("E_V265_RUNTIME_TRANSITION", "run Event stream is empty")
    run_id = event_list[0].get("run_id") if isinstance(event_list[0], Mapping) else None
    if not is_non_empty_string(run_id):
        raise _error("E_V265_RUNTIME_EVENT", "run ID is invalid")
    projection = _initial_projection(graph, str(run_id), bindings)
    terminal_at: dict[str, str] = {}
    host_lineage: dict[str, dict[str, Any]] = {}
    previous = ZERO_SHA256
    for seq, raw_event in enumerate(event_list, start=1):
        if not isinstance(raw_event, Mapping):
            raise _error("E_V265_RUNTIME_EVENT", "Event must be an object")
        event = _validated_event(
            raw_event,
            graph=graph,
            bindings=bindings,
            expected_seq=seq,
            expected_previous=previous,
        )
        if event["run_id"] != run_id:
            raise _error("E_V265_RUNTIME_EVENT", "Event run ID differs")
        _apply_event(graph, projection, event, terminal_at, host_lineage)
        projection["revision"] = seq
        projection["event_count"] = seq
        projection["last_event_sha256"] = event["event_sha256"]
        previous = event["event_sha256"]
    result = copy.deepcopy(projection)
    result["projection_sha256"] = canonical_sha256(result)
    return result


def evaluate_next(
    compiled_graph: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    *,
    expected_bindings: Mapping[str, str],
    now: str,
) -> list[dict[str, Any]]:
    """Return the deterministic current ready-set without mutating state."""

    require_utc_timestamp(
        now,
        error=lambda message: _error("E_V265_RUNTIME_EVENT", message),
        label="now",
    )
    projection = reduce_graph_events(
        compiled_graph, events, expected_bindings=expected_bindings
    )
    result = []
    for node in sorted(compiled_graph["nodes"], key=lambda item: item["node_id"]):
        descriptor = _ready_descriptor(compiled_graph, node, projection)
        if descriptor is not None:
            if descriptor["next_attempt"] > node["budget"]["attempts"]:
                continue
            result.append(descriptor)
    return result


__all__ = [
    "GraphRuntimeError",
    "ZERO_SHA256",
    "evaluate_next",
    "make_graph_event",
    "reduce_graph_events",
    "validate_runtime_graph_contract",
]
