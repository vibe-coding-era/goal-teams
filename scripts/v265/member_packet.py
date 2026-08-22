"""Compile V2.65 Member Packets from validated Graph and Host evidence.

The functions in this module perform structural and lineage validation only.
They do not authenticate a Host issuer and never upgrade repository evidence to
external authority.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.v265.canonical import (
    CanonicalValueError,
    canonical_sha256,
    exact_mapping,
    is_int,
    is_non_empty_string,
    is_sha256,
    require_utc_timestamp,
    self_digest,
    timestamp_value,
    unique_string_list,
)


class MemberPacketError(ValueError):
    """A Member Packet is not bound to its validated dispatch inputs."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


E_BINDING = "E_V265_MEMBER_BINDING"
E_IDENTITY = "E_V265_MEMBER_IDENTITY"
E_SCOPE = "E_V265_MEMBER_SCOPE"
E_CAPABILITY = "E_V265_MEMBER_CAPABILITY"
E_CONTEXT = "E_V265_MEMBER_CONTEXT"
E_DIGEST = "E_V265_MEMBER_DIGEST"
E_RAW = "E_V265_MEMBER_RAW_PACKET_FORBIDDEN"


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
PACKET_FIELDS = frozenset(
    {
        "schema_version",
        "packet_id",
        "graph_id",
        "graph_revision",
        "graph_contract_sha256",
        "plan_id",
        "plan_revision",
        "task_exact_set_sha256",
        "node_id",
        "task_id",
        "owner_identity",
        "owner_run_id",
        "validator_identity",
        "validator_run_id",
        "action_ref",
        "scope_sha256",
        "context_bundle_sha256",
        "context_validation_receipt_sha256",
        "capability_receipt_sha256",
        "capability_request_sha256",
        "capability_decision_sha256",
        "issued_at",
        "packet_sha256",
    }
)
CONTEXT_FIELDS = frozenset(
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
CONTEXT_VALIDATION_FIELDS = frozenset(
    {
        "schema_version",
        "bundle_id",
        "node_id",
        "graph_contract_sha256",
        "bundle_sha256",
        "valid",
        "validator",
        "validated_at",
        "receipt_sha256",
    }
)
CAPABILITY_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "capability_id",
        "issuer",
        "issuer_key_id",
        "issuer_assurance",
        "actor_relationship",
        "proof_strength",
        "host_execution_id",
        "node_id",
        "owner_run_id",
        "graph_contract_sha256",
        "scope_allowlist",
        "forbidden_scope",
        "scope_sha256",
        "tool_allowlist",
        "network_policy",
        "workspace_policy",
        "workspace_realpath",
        "not_before",
        "issued_at",
        "expires_at",
        "freshness_state",
        "permission_effect",
        "attestation_ref",
        "receipt_sha256",
    }
)
CAPABILITY_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "node_id",
        "task_id",
        "attempt",
        "action_ref",
        "owner_run_id",
        "graph_contract_sha256",
        "scope_sha256",
        "context_bundle_sha256",
        "capability_receipt_sha256",
        "requested_at",
        "request_sha256",
    }
)
CAPABILITY_DECISION_FIELDS = frozenset(
    {
        "schema_version",
        "verified",
        "issuer",
        "issuer_key_id",
        "issuer_assurance",
        "actor_relationship",
        "proof_strength",
        "permission_effect",
        "freshness_state",
        "scope_sha256",
        "node_id",
        "capability_receipt_sha256",
        "request_sha256",
        "reason_code",
        "decision_sha256",
    }
)

ISSUER_ASSURANCE = frozenset(
    {"repository_fixture", "host_correlated", "externally_attested"}
)
ACTOR_RELATIONSHIPS = frozenset({"self", "correlated", "independent"})
PROOF_STRENGTHS = frozenset({"fixture_only", "correlated", "externally_attested"})
PERMISSION_EFFECTS = frozenset({"none", "local_execution", "external_side_effects"})


def _error(code: str, message: str) -> MemberPacketError:
    return MemberPacketError(code, message)


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
) -> list[str]:
    return unique_string_list(
        value,
        error=lambda message: _error(code, message),
        label=label,
        non_empty=non_empty,
        sort_output=True,
    )


def _required_string(value: object, label: str, *, code: str) -> str:
    if not is_non_empty_string(value):
        raise _error(code, f"{label} must be a non-empty string")
    return str(value)


def _require_self_digest(
    value: Mapping[str, Any], field: str, *, code: str, label: str
) -> None:
    supplied = value.get(field)
    try:
        expected = self_digest(value, field)
    except CanonicalValueError as exc:
        raise _error(code, f"{label} is not canonical JSON") from exc
    if not is_sha256(supplied) or supplied != expected:
        raise _error(code, f"{label} self-digest differs")


def _validated_graph(compiled_graph: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = _exact(
        compiled_graph,
        GRAPH_COMPILED_FIELDS,
        "compiled_graph",
        code=E_BINDING,
    )
    if graph["schema_version"] != "goal-teams-graph-contract-v2.65":
        raise _error(E_BINDING, "compiled Graph schema_version differs")
    normalized_input = {field: copy.deepcopy(graph[field]) for field in GRAPH_INPUT_FIELDS}
    try:
        if graph["graph_contract_sha256"] != canonical_sha256(normalized_input):
            raise _error(E_BINDING, "compiled Graph contract digest differs")
        _require_self_digest(graph, "receipt_sha256", code=E_BINDING, label="compiled Graph")
    except CanonicalValueError as exc:
        raise _error(E_BINDING, "compiled Graph is not canonical JSON") from exc
    if not isinstance(graph["nodes"], list):
        raise _error(E_BINDING, "compiled Graph nodes are invalid")
    node_by_id = {
        node.get("node_id"): node
        for node in graph["nodes"]
        if isinstance(node, Mapping) and is_non_empty_string(node.get("node_id"))
    }
    if len(node_by_id) != len(graph["nodes"]):
        raise _error(E_BINDING, "compiled Graph Node identities are invalid")
    return graph, node_by_id


def _scope_digest(node: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "scope_allowlist": copy.deepcopy(node["scope_allowlist"]),
            "forbidden_scope": copy.deepcopy(node["forbidden_scope"]),
        }
    )


def _canonical_directory(value: Path | str, label: str) -> Path:
    try:
        path = Path(value)
    except (TypeError, ValueError) as exc:
        raise _error(E_SCOPE, f"{label} is invalid") from exc
    if not path.is_absolute() or not path.exists() or not path.is_dir():
        raise _error(E_SCOPE, f"{label} must be an existing absolute directory")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise _error(E_SCOPE, f"{label} crosses a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _error(E_SCOPE, f"{label} cannot be resolved") from exc
    if resolved != path:
        raise _error(E_SCOPE, f"{label} is not canonical")
    return resolved


def _validate_scope_pattern(
    pattern: str,
    *,
    workspace: Path,
    authorized_root: Path,
) -> None:
    if not isinstance(pattern, str) or not pattern or "\\" in pattern:
        raise _error(E_SCOPE, "scope pattern must be a non-empty POSIX path")
    parts = pattern.split("/")
    if pattern.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise _error(E_SCOPE, "scope pattern is absolute or contains an unsafe component")
    glob_index = next(
        (index for index, part in enumerate(parts) if any(mark in part for mark in "*?[")),
        len(parts),
    )
    current = workspace
    for part in parts[:glob_index]:
        current = current / part
        if current.is_symlink():
            raise _error(E_SCOPE, "scope literal prefix crosses a symlink")
    try:
        resolved = current.resolve(strict=False)
        resolved.relative_to(workspace)
        resolved.relative_to(authorized_root)
    except (OSError, ValueError) as exc:
        raise _error(E_SCOPE, "scope literal prefix escapes workspace authority") from exc


def _validate_workspace_authority(
    capability: Mapping[str, Any],
    *,
    scope_allowlist: list[str],
    forbidden_scope: list[str],
    authorized_workspace_root: Path | str | None,
) -> None:
    if authorized_workspace_root is None:
        return
    root = _canonical_directory(authorized_workspace_root, "authorized_workspace_root")
    workspace = _canonical_directory(
        capability["workspace_realpath"], "capability workspace_realpath"
    )
    try:
        workspace.relative_to(root)
    except ValueError as exc:
        raise _error(E_SCOPE, "capability workspace escapes authorized root") from exc
    for pattern in [*scope_allowlist, *forbidden_scope]:
        _validate_scope_pattern(
            pattern,
            workspace=workspace,
            authorized_root=root,
        )


def _validated_context(
    context_bundle: Mapping[str, Any],
    *,
    graph_receipt_sha256: str,
    node_id: str,
) -> dict[str, Any]:
    bundle = _exact(context_bundle, CONTEXT_FIELDS, "context_bundle", code=E_CONTEXT)
    if bundle["schema_version"] != "goal-teams-context-bundle-v2.65":
        raise _error(E_CONTEXT, "Context Bundle schema_version differs")
    _require_self_digest(bundle, "bundle_sha256", code=E_CONTEXT, label="Context Bundle")
    if (
        bundle["graph_contract_sha256"] != graph_receipt_sha256
        or bundle["node_id"] != node_id
    ):
        raise _error(E_CONTEXT, "Context Bundle Graph or Node binding differs")
    if bundle["token_estimate_algorithm"] != "utf8_bytes_ceiling_div4":
        raise _error(E_CONTEXT, "Context Bundle token estimate algorithm differs")
    require_utc_timestamp(
        bundle["compiled_at"],
        error=lambda message: _error(E_CONTEXT, message),
        label="context_bundle.compiled_at",
    )
    return bundle


def _validated_context_receipt(
    receipt: Mapping[str, Any],
    *,
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    result = _exact(
        receipt,
        CONTEXT_VALIDATION_FIELDS,
        "context_validation_receipt",
        code=E_CONTEXT,
    )
    _require_self_digest(
        result,
        "receipt_sha256",
        code=E_CONTEXT,
        label="Context validation receipt",
    )
    if (
        result["schema_version"]
        != "goal-teams-context-validation-receipt-v2.65"
        or result["bundle_id"] != bundle["bundle_id"]
        or result["node_id"] != bundle["node_id"]
        or result["graph_contract_sha256"] != bundle["graph_contract_sha256"]
        or result["bundle_sha256"] != bundle["bundle_sha256"]
        or result["valid"] is not True
        or result["validator"]
        != "scripts.v265.context_compiler.validate_context_bundle"
    ):
        raise _error(E_CONTEXT, "Context validation receipt differs")
    require_utc_timestamp(
        result["validated_at"],
        error=lambda message: _error(E_CONTEXT, message),
        label="context_validation_receipt.validated_at",
    )
    return result


def _validated_capability_receipt(
    receipt: Mapping[str, Any],
    *,
    graph_receipt_sha256: str,
    node: Mapping[str, Any],
    owner_run_id: str,
    dispatch_at: str,
    action: Mapping[str, Any],
    authorized_workspace_root: Path | str | None,
) -> dict[str, Any]:
    capability = _exact(
        receipt,
        CAPABILITY_RECEIPT_FIELDS,
        "capability_receipt",
        code=E_CAPABILITY,
    )
    _require_self_digest(
        capability,
        "receipt_sha256",
        code=E_CAPABILITY,
        label="Capability Receipt",
    )
    if capability["schema_version"] != "goal-teams-host-capability-receipt-v2.65":
        raise _error(E_CAPABILITY, "Capability Receipt schema_version differs")
    for field in ("capability_id", "issuer", "issuer_key_id", "host_execution_id"):
        _required_string(capability[field], f"capability_receipt.{field}", code=E_CAPABILITY)
    if capability["issuer_assurance"] not in ISSUER_ASSURANCE:
        raise _error(E_CAPABILITY, "Capability issuer assurance is invalid")
    if capability["actor_relationship"] not in ACTOR_RELATIONSHIPS:
        raise _error(E_CAPABILITY, "Capability actor relationship is invalid")
    if capability["proof_strength"] not in PROOF_STRENGTHS:
        raise _error(E_CAPABILITY, "Capability proof strength is invalid")
    if capability["permission_effect"] not in PERMISSION_EFFECTS:
        raise _error(E_CAPABILITY, "Capability permission effect is invalid")
    if capability["freshness_state"] != "current":
        raise _error(E_CAPABILITY, "Capability Receipt is not current")

    scope_allowlist = _strings(
        capability["scope_allowlist"],
        "capability_receipt.scope_allowlist",
        code=E_CAPABILITY,
        non_empty=True,
    )
    forbidden_scope = _strings(
        capability["forbidden_scope"],
        "capability_receipt.forbidden_scope",
        code=E_CAPABILITY,
    )
    tools = _strings(
        capability["tool_allowlist"],
        "capability_receipt.tool_allowlist",
        code=E_CAPABILITY,
        non_empty=True,
    )
    expected_scope_sha256 = _scope_digest(node)
    if (
        scope_allowlist != node["scope_allowlist"]
        or forbidden_scope != node["forbidden_scope"]
        or capability["scope_sha256"] != expected_scope_sha256
        or capability["node_id"] != node["node_id"]
        or capability["owner_run_id"] != owner_run_id
        or capability["graph_contract_sha256"] != graph_receipt_sha256
        or tools != action["tool_allowlist"]
        or capability["network_policy"] != action["network_policy"]
        or capability["workspace_policy"] != action["workspace_policy"]
    ):
        raise _error(E_CAPABILITY, "Capability Receipt dispatch binding differs")
    _required_string(
        capability["workspace_realpath"],
        "capability_receipt.workspace_realpath",
        code=E_CAPABILITY,
    )
    _validate_workspace_authority(
        capability,
        scope_allowlist=scope_allowlist,
        forbidden_scope=forbidden_scope,
        authorized_workspace_root=authorized_workspace_root,
    )
    if action["effect"] in {"read", "local_write"}:
        if capability["permission_effect"] != "local_execution":
            raise _error(E_CAPABILITY, "local Action requires local_execution permission")
    elif (
        capability["permission_effect"] != "external_side_effects"
        or capability["issuer_assurance"] != "externally_attested"
        or capability["proof_strength"] != "externally_attested"
        or capability["actor_relationship"] != "independent"
        or not is_non_empty_string(capability["attestation_ref"])
    ):
        raise _error(E_CAPABILITY, "external Action lacks independent attestation")
    if action["effect"] != "external_write" and capability["attestation_ref"] is not None:
        _required_string(
            capability["attestation_ref"],
            "capability_receipt.attestation_ref",
            code=E_CAPABILITY,
        )

    for field in ("not_before", "issued_at", "expires_at"):
        require_utc_timestamp(
            capability[field],
            error=lambda message: _error(E_CAPABILITY, message),
            label=f"capability_receipt.{field}",
        )
    not_before = timestamp_value(capability["not_before"])
    issued = timestamp_value(capability["issued_at"])
    expires = timestamp_value(capability["expires_at"])
    dispatch = timestamp_value(dispatch_at)
    if not (not_before <= issued <= dispatch <= expires):
        raise _error(E_CAPABILITY, "Capability Receipt validity window does not cover dispatch")
    return capability


def _validated_capability_request(
    request: Mapping[str, Any],
    *,
    graph_receipt_sha256: str,
    node: Mapping[str, Any],
    owner_run_id: str,
    context_bundle_sha256: str,
    capability_receipt_sha256: str,
    dispatch_at: str,
) -> dict[str, Any]:
    result = _exact(
        request,
        CAPABILITY_REQUEST_FIELDS,
        "capability_request",
        code=E_CAPABILITY,
    )
    _require_self_digest(
        result,
        "request_sha256",
        code=E_CAPABILITY,
        label="Capability Request",
    )
    if result["schema_version"] != "goal-teams-host-capability-request-v2.65":
        raise _error(E_CAPABILITY, "Capability Request schema_version differs")
    _required_string(result["run_id"], "capability_request.run_id", code=E_CAPABILITY)
    if not is_int(result["attempt"], minimum=1):
        raise _error(E_CAPABILITY, "Capability Request attempt must be positive")
    requested_at = require_utc_timestamp(
        result["requested_at"],
        error=lambda message: _error(E_CAPABILITY, message),
        label="capability_request.requested_at",
    )
    if timestamp_value(requested_at) > timestamp_value(dispatch_at):
        raise _error(E_CAPABILITY, "Capability Request occurs after dispatch")
    expected = {
        "node_id": node["node_id"],
        "task_id": node["task_refs"][0],
        "action_ref": node["action_ref"],
        "owner_run_id": owner_run_id,
        "graph_contract_sha256": graph_receipt_sha256,
        "scope_sha256": _scope_digest(node),
        "context_bundle_sha256": context_bundle_sha256,
        "capability_receipt_sha256": capability_receipt_sha256,
    }
    if any(result[field] != value for field, value in expected.items()):
        raise _error(E_CAPABILITY, "Capability Request dispatch binding differs")
    return result


def _validated_capability_decision(
    decision: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    capability: Mapping[str, Any],
    action: Mapping[str, Any],
) -> dict[str, Any]:
    result = _exact(
        decision,
        CAPABILITY_DECISION_FIELDS,
        "capability_decision",
        code=E_CAPABILITY,
    )
    _require_self_digest(
        result,
        "decision_sha256",
        code=E_CAPABILITY,
        label="Capability Decision",
    )
    if (
        result["schema_version"] != "goal-teams-host-capability-decision-v2.65"
        or result["verified"] is not True
        or not is_non_empty_string(result["reason_code"])
    ):
        raise _error(E_CAPABILITY, "Capability Decision is not a verified decision")
    expected = {
        "issuer": capability["issuer"],
        "issuer_key_id": capability["issuer_key_id"],
        "issuer_assurance": capability["issuer_assurance"],
        "actor_relationship": capability["actor_relationship"],
        "proof_strength": capability["proof_strength"],
        "permission_effect": capability["permission_effect"],
        "freshness_state": capability["freshness_state"],
        "scope_sha256": capability["scope_sha256"],
        "node_id": capability["node_id"],
        "capability_receipt_sha256": capability["receipt_sha256"],
        "request_sha256": request["request_sha256"],
    }
    if any(result[field] != value for field, value in expected.items()):
        raise _error(E_CAPABILITY, "Capability Decision lineage differs")
    required_permission = (
        "external_side_effects" if action["effect"] == "external_write" else "local_execution"
    )
    if result["permission_effect"] != required_permission:
        raise _error(E_CAPABILITY, "Capability Decision permission does not satisfy Action")
    return result


def _action_for_node(graph: Mapping[str, Any], node: Mapping[str, Any]) -> dict[str, Any]:
    matches = [
        action
        for action in graph["actions"]
        if isinstance(action, Mapping) and action.get("action_id") == node.get("action_ref")
    ]
    if len(matches) != 1:
        raise _error(E_BINDING, "compiled Node action binding differs")
    return copy.deepcopy(dict(matches[0]))


def _validate_common_inputs(
    *,
    compiled_graph: Mapping[str, Any],
    node_id: str,
    owner_run_id: str,
    validator_run_id: str,
    context_bundle: Mapping[str, Any],
    capability_receipt: Mapping[str, Any],
    capability_request: Mapping[str, Any],
    capability_decision: Mapping[str, Any],
    dispatch_at: str,
    authorized_workspace_root: Path | str | None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    graph, node_by_id = _validated_graph(compiled_graph)
    node_id = _required_string(node_id, "node_id", code=E_BINDING)
    node = node_by_id.get(node_id)
    if node is None:
        raise _error(E_BINDING, f"compiled Graph has no Node {node_id}")
    owner_run_id = _required_string(owner_run_id, "owner_run_id", code=E_IDENTITY)
    validator_run_id = _required_string(
        validator_run_id, "validator_run_id", code=E_IDENTITY
    )
    if owner_run_id == validator_run_id:
        raise _error(E_IDENTITY, "Owner and Validator run identities must differ")
    dispatch_at = require_utc_timestamp(
        dispatch_at,
        error=lambda message: _error(E_BINDING, message),
        label="issued_at",
    )
    action = _action_for_node(graph, node)
    bundle = _validated_context(
        context_bundle,
        graph_receipt_sha256=graph["receipt_sha256"],
        node_id=node_id,
    )
    capability = _validated_capability_receipt(
        capability_receipt,
        graph_receipt_sha256=graph["receipt_sha256"],
        node=node,
        owner_run_id=owner_run_id,
        dispatch_at=dispatch_at,
        action=action,
        authorized_workspace_root=authorized_workspace_root,
    )
    request = _validated_capability_request(
        capability_request,
        graph_receipt_sha256=graph["receipt_sha256"],
        node=node,
        owner_run_id=owner_run_id,
        context_bundle_sha256=bundle["bundle_sha256"],
        capability_receipt_sha256=capability["receipt_sha256"],
        dispatch_at=dispatch_at,
    )
    decision = _validated_capability_decision(
        capability_decision,
        request=request,
        capability=capability,
        action=action,
    )
    return graph, node, action, bundle, capability, request, decision


def compile_member_packet(
    *,
    packet_id: str,
    compiled_graph: Mapping[str, Any],
    node_id: str,
    owner_run_id: str,
    validator_run_id: str,
    context_bundle: Mapping[str, Any],
    context_validation_receipt: Mapping[str, Any],
    capability_receipt: Mapping[str, Any],
    capability_request: Mapping[str, Any],
    capability_decision: Mapping[str, Any],
    issued_at: str,
    authorized_workspace_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build canonical Member Packet bytes only from validated typed inputs."""

    packet_id = _required_string(packet_id, "packet_id", code=E_BINDING)
    (
        graph,
        node,
        _action,
        bundle,
        capability,
        request,
        decision,
    ) = _validate_common_inputs(
        compiled_graph=compiled_graph,
        node_id=node_id,
        owner_run_id=owner_run_id,
        validator_run_id=validator_run_id,
        context_bundle=context_bundle,
        capability_receipt=capability_receipt,
        capability_request=capability_request,
        capability_decision=capability_decision,
        dispatch_at=issued_at,
        authorized_workspace_root=authorized_workspace_root,
    )
    context_validation = _validated_context_receipt(
        context_validation_receipt, bundle=bundle
    )
    plan_binding = graph["plan_binding"]
    packet: dict[str, Any] = {
        "schema_version": "goal-teams-member-packet-v2.65",
        "packet_id": packet_id,
        "graph_id": graph["graph_id"],
        "graph_revision": graph["graph_revision"],
        "graph_contract_sha256": graph["receipt_sha256"],
        "plan_id": plan_binding["plan_id"],
        "plan_revision": plan_binding["plan_revision"],
        "task_exact_set_sha256": plan_binding["task_exact_set_sha256"],
        "node_id": node["node_id"],
        "task_id": node["task_refs"][0],
        "owner_identity": node["owner_identity"],
        "owner_run_id": owner_run_id,
        "validator_identity": node["validator_identity"],
        "validator_run_id": validator_run_id,
        "action_ref": node["action_ref"],
        "scope_sha256": _scope_digest(node),
        "context_bundle_sha256": bundle["bundle_sha256"],
        "context_validation_receipt_sha256": context_validation["receipt_sha256"],
        "capability_receipt_sha256": capability["receipt_sha256"],
        "capability_request_sha256": request["request_sha256"],
        "capability_decision_sha256": decision["decision_sha256"],
        "issued_at": issued_at,
    }
    packet["packet_sha256"] = canonical_sha256(packet)
    return packet


def validate_member_packet(
    packet: Mapping[str, Any],
    *,
    compiled_graph: Mapping[str, Any],
    context_bundle: Mapping[str, Any],
    capability_receipt: Mapping[str, Any],
    capability_request: Mapping[str, Any],
    capability_decision: Mapping[str, Any],
    authorized_workspace_root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate Packet lineage without accepting raw or caller-assembled bytes."""

    if not isinstance(packet, Mapping):
        raise _error(E_RAW, "raw or uncompiled Member Packet bytes are forbidden")
    candidate = _exact(packet, PACKET_FIELDS, "packet", code=E_BINDING)
    _require_self_digest(candidate, "packet_sha256", code=E_DIGEST, label="Member Packet")
    if candidate["schema_version"] != "goal-teams-member-packet-v2.65":
        raise _error(E_BINDING, "Member Packet schema_version differs")
    issued_at = require_utc_timestamp(
        candidate["issued_at"],
        error=lambda message: _error(E_BINDING, message),
        label="packet.issued_at",
    )
    preliminary_graph, preliminary_nodes = _validated_graph(compiled_graph)
    preliminary_node = preliminary_nodes.get(candidate["node_id"])
    if preliminary_node is None:
        raise _error(E_BINDING, "Member Packet Node is absent from compiled Graph")
    preliminary_plan = preliminary_graph["plan_binding"]
    preliminary_expected = {
        "graph_id": preliminary_graph["graph_id"],
        "graph_revision": preliminary_graph["graph_revision"],
        "graph_contract_sha256": preliminary_graph["receipt_sha256"],
        "plan_id": preliminary_plan["plan_id"],
        "plan_revision": preliminary_plan["plan_revision"],
        "task_exact_set_sha256": preliminary_plan["task_exact_set_sha256"],
        "node_id": preliminary_node["node_id"],
        "task_id": preliminary_node["task_refs"][0],
        "owner_identity": preliminary_node["owner_identity"],
        "validator_identity": preliminary_node["validator_identity"],
        "action_ref": preliminary_node["action_ref"],
    }
    if any(candidate[field] != value for field, value in preliminary_expected.items()):
        raise _error(E_BINDING, "Member Packet Graph, Plan, Node or Task binding differs")
    (
        graph,
        node,
        _action,
        bundle,
        capability,
        request,
        decision,
    ) = _validate_common_inputs(
        compiled_graph=compiled_graph,
        node_id=candidate["node_id"],
        owner_run_id=candidate["owner_run_id"],
        validator_run_id=candidate["validator_run_id"],
        context_bundle=context_bundle,
        capability_receipt=capability_receipt,
        capability_request=capability_request,
        capability_decision=capability_decision,
        dispatch_at=issued_at,
        authorized_workspace_root=authorized_workspace_root,
    )
    plan_binding = graph["plan_binding"]
    binding_expected = {
        "graph_id": graph["graph_id"],
        "graph_revision": graph["graph_revision"],
        "graph_contract_sha256": graph["receipt_sha256"],
        "plan_id": plan_binding["plan_id"],
        "plan_revision": plan_binding["plan_revision"],
        "task_exact_set_sha256": plan_binding["task_exact_set_sha256"],
        "node_id": node["node_id"],
        "task_id": node["task_refs"][0],
        "owner_identity": node["owner_identity"],
        "validator_identity": node["validator_identity"],
        "action_ref": node["action_ref"],
    }
    if any(candidate[field] != value for field, value in binding_expected.items()):
        raise _error(E_BINDING, "Member Packet Graph, Plan, Node or Task binding differs")
    if candidate["owner_run_id"] == candidate["validator_run_id"]:
        raise _error(E_IDENTITY, "Member Packet run identities are equal")
    if candidate["scope_sha256"] != _scope_digest(node):
        raise _error(E_SCOPE, "Member Packet scope digest differs")
    if candidate["context_bundle_sha256"] != bundle["bundle_sha256"]:
        raise _error(E_CONTEXT, "Member Packet Context binding differs")
    if not is_sha256(candidate["context_validation_receipt_sha256"]):
        raise _error(E_CONTEXT, "Member Packet Context validation digest is invalid")
    capability_expected = {
        "capability_receipt_sha256": capability["receipt_sha256"],
        "capability_request_sha256": request["request_sha256"],
        "capability_decision_sha256": decision["decision_sha256"],
    }
    if any(candidate[field] != value for field, value in capability_expected.items()):
        raise _error(E_CAPABILITY, "Member Packet Capability lineage differs")

    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-member-packet-validation-receipt-v2.65",
        "packet_id": candidate["packet_id"],
        "node_id": candidate["node_id"],
        "packet_sha256": candidate["packet_sha256"],
        "graph_contract_sha256": candidate["graph_contract_sha256"],
        "context_bundle_sha256": candidate["context_bundle_sha256"],
        "capability_receipt_sha256": candidate["capability_receipt_sha256"],
        "capability_request_sha256": candidate["capability_request_sha256"],
        "capability_decision_sha256": candidate["capability_decision_sha256"],
        "valid": True,
        "validator": "scripts.v265.member_packet.validate_member_packet",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt
