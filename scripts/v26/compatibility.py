"""Fail-closed V2.6 compatibility metadata and receipt handling."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import PurePosixPath, Path
from typing import Any


SCHEMA_VERSION = "goal-teams-compatibility-v2.6-v1"
RECEIPT_SCHEMA_VERSION = "goal-teams-runtime-binding-v2.6-v1"
NODE_KINDS = {"portable_core", "host", "provider", "model", "bridge", "role"}
VERIFICATION_STATES = {"not_run", "documented_only", "contract_mapped_not_runtime_verified", "runtime_passed", "blocked", "failed", "stale", "invalid"}


class CompatibilityError(ValueError):
    """Stable V2.6 compatibility validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise CompatibilityError("E_V26_LIST", f"{field} must be a non-empty string array")
    if len(value) != len(set(value)):
        raise CompatibilityError("E_V26_LIST_DUPLICATE", f"{field} contains duplicates")
    return list(value)


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CompatibilityError("E_V26_PATH_INVALID", "node path must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CompatibilityError("E_V26_PATH_ESCAPE", f"unsafe node path: {value!r}")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompatibilityError("E_V26_JSON", f"cannot load metadata: {path}") from exc
    if not isinstance(value, dict):
        raise CompatibilityError("E_V26_SHAPE", "metadata root must be an object")
    return value


def load_compatibility_metadata(path: Path | str) -> dict[str, Any]:
    """Load typed V2.6 metadata without resolving filesystem references."""

    value = _load_json(Path(path))
    if value.get("schema_version") != SCHEMA_VERSION:
        raise CompatibilityError("E_V26_SCHEMA", "unsupported compatibility metadata schema")
    nodes = value.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise CompatibilityError("E_V26_NODES", "nodes must be a non-empty array")
    node_ids: set[str] = set()
    validated_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise CompatibilityError("E_V26_NODE", "node must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise CompatibilityError("E_V26_NODE_ID", "node id must be a non-empty string")
        if node_id in node_ids:
            raise CompatibilityError("E_V26_NODE_ID_DUPLICATE", f"duplicate node id: {node_id}")
        kind = node.get("kind")
        if not isinstance(kind, str) or kind not in NODE_KINDS:
            raise CompatibilityError("E_V26_NODE_KIND", f"unsupported node kind: {kind!r}")
        state = node.get("state")
        if not isinstance(state, str) or not state:
            raise CompatibilityError("E_V26_NODE_STATE", f"node {node_id} lacks explicit state")
        validated = dict(node)
        validated["path"] = _safe_path(node.get("path"))
        validated["capabilities"] = _string_list(node.get("capabilities"), f"node {node_id}.capabilities")
        validated["depends_on"] = _string_list(node.get("depends_on"), f"node {node_id}.depends_on") if node.get("depends_on") else []
        if any(dependency not in node_ids for dependency in validated["depends_on"]):
            raise CompatibilityError("E_V26_DEPENDENCY_ORDER", f"node {node_id} depends on a later or unknown node")
        node_ids.add(node_id)
        validated_nodes.append(validated)
    routes = value.get("routes")
    if not isinstance(routes, list) or not routes:
        raise CompatibilityError("E_V26_ROUTES", "routes must be a non-empty array")
    route_keys: set[tuple[str, str]] = set()
    validated_routes: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            raise CompatibilityError("E_V26_ROUTE", "route must be an object")
        host_id, requested_model = route.get("host_id"), route.get("requested_model")
        if not isinstance(host_id, str) or not isinstance(requested_model, str):
            raise CompatibilityError("E_V26_ROUTE_IDENTITY", "route host and requested model are required")
        key = (host_id, requested_model)
        if key in route_keys:
            raise CompatibilityError("E_V26_ROUTE_DUPLICATE", f"duplicate route: {host_id}/{requested_model}")
        route_refs = _string_list(route.get("route_refs"), f"route {host_id}/{requested_model}.route_refs")
        if route_refs[0] != "portable-core" or host_id not in route_refs:
            raise CompatibilityError("E_V26_ROUTE_ORDER", "route must start at portable-core and include its host")
        if any(ref not in node_ids for ref in route_refs):
            raise CompatibilityError("E_V26_ROUTE_REF", "route has an unknown node reference")
        connection_class = route.get("connection_class")
        if connection_class not in {"direct_responses", "direct_anthropic", "bridge_required", "unsupported_direct"}:
            raise CompatibilityError("E_V26_CONNECTION_CLASS", "unsupported connection class")
        verification_state = route.get("verification_state")
        if verification_state not in VERIFICATION_STATES:
            raise CompatibilityError("E_V26_VERIFICATION_STATE", "unsupported verification state")
        if route.get("resolved_model") != requested_model:
            raise CompatibilityError("E_V26_MODEL_REWRITE", "metadata must not silently rewrite a requested model")
        if connection_class in {"bridge_required", "unsupported_direct"} and verification_state != "blocked":
            raise CompatibilityError("E_V26_BLOCKED_STATE", "non-direct route must remain blocked without approved runtime evidence")
        route_keys.add(key)
        validated_routes.append(dict(route, route_refs=route_refs))
    return dict(value, nodes=validated_nodes, routes=validated_routes)


def _route(metadata: dict[str, Any], host_id: str, requested_model: str) -> dict[str, Any]:
    for route in metadata["routes"]:
        if route["host_id"] == host_id and route["requested_model"] == requested_model:
            return dict(route)
    raise CompatibilityError("E_V26_ROUTE_UNKNOWN", f"no route for {host_id}/{requested_model}")


def resolve_route(metadata: dict[str, Any], host_id: str, requested_model: str) -> dict[str, Any]:
    route = _route(metadata, host_id, requested_model)
    nodes = {node["id"]: node for node in metadata["nodes"]}
    route_ref_digests = [
        {"id": ref, "sha256": _digest(nodes[ref])}
        for ref in route["route_refs"]
    ]
    digest_payload = {**route, "route_ref_digests": route_ref_digests}
    return dict(
        route,
        route_ref_digests=route_ref_digests,
        route_digest=_digest(digest_payload),
    )


def _valid_capture_time(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_runtime_binding_receipt(receipt: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return {"ok": False, "errors": ["E_V26_RECEIPT_SCHEMA"]}
    try:
        expected = resolve_route(metadata, receipt.get("host_id"), receipt.get("requested_model"))
    except CompatibilityError as exc:
        return {"ok": False, "errors": [exc.code]}
    run_id = receipt.get("binding_run_id")
    if not isinstance(run_id, str) or not run_id or len(run_id) > 256:
        errors.append("E_V26_RECEIPT_RUN_ID")
    if not _valid_capture_time(receipt.get("captured_at")):
        errors.append("E_V26_RECEIPT_CAPTURED_AT")
    if receipt.get("resolved_model") != expected["resolved_model"]:
        errors.append("E_V26_RECEIPT_RESOLVED_MODEL_REWRITE")
    if expected["connection_class"] == "bridge_required" and receipt.get("connection_class") != "bridge_required":
        errors.append("E_V26_RECEIPT_BRIDGE_AS_DIRECT")
    elif receipt.get("connection_class") != expected["connection_class"]:
        errors.append("E_V26_RECEIPT_CONNECTION_CLASS")
    if receipt.get("verification_state") != expected["verification_state"]:
        errors.append("E_V26_RECEIPT_VERIFICATION_STATE")
    if (
        receipt.get("route_refs") != expected["route_refs"]
        or receipt.get("route_ref_digests") != expected["route_ref_digests"]
        or receipt.get("route_digest") != expected["route_digest"]
    ):
        errors.append("E_V26_RECEIPT_ROUTE_DRIFT")
    return {"ok": not errors, "errors": errors, "connection_class": expected["connection_class"], "verification_state": expected["verification_state"], "requested_model": expected["requested_model"], "resolved_model": expected["resolved_model"]}
