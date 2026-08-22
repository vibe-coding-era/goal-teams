"""Host-neutral protocol and bounded local Callback adapter for V2.65."""

from __future__ import annotations

import copy
import hashlib
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable, Mapping, Protocol

from scripts.v265.canonical import (
    canonical_sha256,
    exact_mapping,
    is_int,
    is_non_empty_string,
    is_sha256,
    require_utc_timestamp,
    timestamp_value,
    unique_string_list,
)


class HostAdapterError(ValueError):
    """Stable Host Adapter failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _error(code: str, message: str) -> HostAdapterError:
    return HostAdapterError(code, message)


class HostAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    @property
    def proof_strength(self) -> str: ...

    @property
    def trusted_issuer_ids(self) -> frozenset[str]: ...

    def verify_capability(
        self, request: Mapping[str, Any], capability_receipt: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def prepare(
        self, dispatch: Mapping[str, Any], *, prepared_at: str
    ) -> dict[str, Any]: ...

    def execute(
        self,
        handle: Mapping[str, Any],
        dispatch: Mapping[str, Any],
        *,
        started_at: str,
    ) -> dict[str, Any]: ...

    def spawn(self, dispatch: Mapping[str, Any]) -> dict[str, Any]: ...

    def wait(
        self, handle: Mapping[str, Any], *, timeout_seconds: int
    ) -> dict[str, Any]: ...

    def cancel(self, handle: Mapping[str, Any]) -> dict[str, Any]: ...

    def probe_handle(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
        host_handle_id: str,
        observed_at: str,
    ) -> dict[str, Any]: ...

    def verify_approval(
        self, interrupt: Mapping[str, Any], approval_receipt: Mapping[str, Any]
    ) -> dict[str, Any]: ...


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
DISPATCH_FIELDS = frozenset(
    {"schema_version", "run_id", "node_id", "task_id", "attempt", "action_ref", "member_packet",
     "context_bundle", "capability_receipt", "capability_decision", "idempotency_key"}
)
DECISION_FIELDS = frozenset(
    {
        "schema_version", "verified", "issuer", "issuer_key_id",
        "issuer_assurance", "actor_relationship", "proof_strength",
        "permission_effect", "freshness_state", "scope_sha256", "node_id",
        "capability_receipt_sha256", "request_sha256", "reason_code",
        "decision_sha256",
    }
)
PACKET_FIELDS = frozenset(
    {
        "schema_version", "packet_id", "graph_id", "graph_revision",
        "graph_contract_sha256", "plan_id", "plan_revision",
        "task_exact_set_sha256", "node_id", "task_id", "owner_identity",
        "owner_run_id", "validator_identity", "validator_run_id", "action_ref",
        "scope_sha256", "context_bundle_sha256",
        "context_validation_receipt_sha256", "capability_receipt_sha256",
        "capability_request_sha256", "capability_decision_sha256", "issued_at",
        "packet_sha256",
    }
)
CONTEXT_FIELDS = frozenset(
    {
        "schema_version", "bundle_id", "graph_contract_sha256", "node_id",
        "resources", "review_capsule_sha256", "total_bytes", "estimated_tokens",
        "token_estimate_algorithm", "compiled_at", "bundle_sha256",
    }
)
HANDLE_FIELDS = frozenset(
    {
        "schema_version", "adapter_id", "host_handle_id", "run_id", "node_id",
        "attempt", "transport", "proof_strength", "dispatch_sha256", "state",
        "prepared_at", "handle_sha256",
    }
)


def _exact(value: object, fields: frozenset[str], label: str) -> dict[str, Any]:
    return exact_mapping(
        value,
        fields,
        error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
        label=label,
    )


def _self_digest(value: Mapping[str, Any], field: str, code: str) -> None:
    if not is_sha256(value.get(field)) or canonical_sha256(
        {key: item for key, item in value.items() if key != field}
    ) != value[field]:
        raise _error(code, f"{field} differs")


def _strings(value: object, label: str, *, non_empty: bool = False) -> list[str]:
    return unique_string_list(
        value,
        error=lambda message: _error("E_V265_HOST_CAPABILITY", message),
        label=label,
        non_empty=non_empty,
        sort_output=True,
    )


def _scope_sha256(capability: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "scope_allowlist": capability["scope_allowlist"],
            "forbidden_scope": capability["forbidden_scope"],
        }
    )


class CallbackHostAdapter:
    """Bounded thread callback adapter with fixture-only assurance."""

    def __init__(
        self,
        callbacks: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]],
        *,
        adapter_id: str = "callback_fixture",
        max_workers: int = 1,
        clock: Callable[[], str],
    ) -> None:
        if not isinstance(callbacks, Mapping) or not all(
            is_non_empty_string(key) and callable(value) for key, value in callbacks.items()
        ):
            raise _error("E_V265_HOST_OBSERVATION", "callbacks must be an action mapping")
        if not is_non_empty_string(adapter_id) or not is_int(max_workers, minimum=1) or not callable(clock):
            raise _error("E_V265_HOST_OBSERVATION", "Callback adapter configuration is invalid")
        self._adapter_id = adapter_id
        self._callbacks = dict(callbacks)
        self._max_workers = max_workers
        self._clock = clock
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gt-v265")
        self._lock = threading.RLock()
        self._futures: dict[str, Future[dict[str, Any]]] = {}
        self._handles: dict[str, dict[str, Any]] = {}
        self._dispatches: dict[str, dict[str, Any]] = {}
        self._states: dict[str, str] = {}

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    @property
    def proof_strength(self) -> str:
        return "fixture_only"

    @property
    def trusted_issuer_ids(self) -> frozenset[str]:
        return frozenset({"callback_fixture"})

    def verify_capability(
        self, request: Mapping[str, Any], capability_receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            req = _exact(request, REQUEST_FIELDS, "Capability Request")
            cap = _exact(capability_receipt, CAPABILITY_FIELDS, "Capability Receipt")
            _self_digest(req, "request_sha256", "E_V265_HOST_CAPABILITY")
            _self_digest(cap, "receipt_sha256", "E_V265_HOST_CAPABILITY")
        except HostAdapterError as exc:
            raise _error("E_V265_HOST_CAPABILITY", exc.message) from exc
        scope_allowlist = _strings(
            cap["scope_allowlist"], "Capability scope_allowlist", non_empty=True
        )
        forbidden_scope = _strings(
            cap["forbidden_scope"], "Capability forbidden_scope"
        )
        tools = _strings(cap["tool_allowlist"], "Capability tool_allowlist", non_empty=True)
        if (
            req["schema_version"] != "goal-teams-host-capability-request-v2.65"
            or cap["schema_version"] != "goal-teams-host-capability-receipt-v2.65"
            or not all(
                is_non_empty_string(req[field])
                for field in ("run_id", "node_id", "task_id", "action_ref", "owner_run_id")
            )
            or not is_int(req["attempt"], minimum=1)
            or not is_sha256(req["graph_contract_sha256"])
            or not is_sha256(req["context_bundle_sha256"])
            or cap["issuer"] != "callback_fixture"
            or cap["issuer_key_id"] != "callback_fixture:key:1"
            or cap["issuer_assurance"] != "repository_fixture"
            or cap["actor_relationship"] != "self"
            or cap["proof_strength"] != "fixture_only"
            or cap["permission_effect"] != "local_execution"
            or cap["network_policy"] != "deny"
            or cap["workspace_policy"] != "node_scope"
            or tools != ["callback"]
            or cap["freshness_state"] != "current"
            or cap["attestation_ref"] is not None
            or not is_non_empty_string(cap["capability_id"])
            or not is_non_empty_string(cap["host_execution_id"])
            or not is_non_empty_string(cap["workspace_realpath"])
            or cap["scope_sha256"] != _scope_sha256(cap)
            or scope_allowlist != cap["scope_allowlist"]
            or forbidden_scope != cap["forbidden_scope"]
            or req["capability_receipt_sha256"] != cap["receipt_sha256"]
            or req["node_id"] != cap["node_id"]
            or req["owner_run_id"] != cap["owner_run_id"]
            or req["graph_contract_sha256"] != cap["graph_contract_sha256"]
            or req["scope_sha256"] != cap["scope_sha256"]
        ):
            raise _error("E_V265_HOST_CAPABILITY", "Callback adapter cannot verify requested Capability")
        requested_at = require_utc_timestamp(
            req["requested_at"],
            error=lambda message: _error("E_V265_HOST_CAPABILITY", message),
            label="requested_at",
        )
        for field in ("not_before", "issued_at", "expires_at"):
            require_utc_timestamp(
                cap[field],
                error=lambda message: _error("E_V265_HOST_CAPABILITY", message),
            label=field,
            )
        instant = timestamp_value(requested_at)
        if not (
            timestamp_value(cap["not_before"])
            <= timestamp_value(cap["issued_at"])
            <= instant
            <= timestamp_value(cap["expires_at"])
        ):
            raise _error("E_V265_HOST_CAPABILITY", "Capability is outside validity window")
        decision: dict[str, Any] = {
            "schema_version": "goal-teams-host-capability-decision-v2.65",
            "verified": True,
            "issuer": cap["issuer"],
            "issuer_key_id": cap["issuer_key_id"],
            "issuer_assurance": cap["issuer_assurance"],
            "actor_relationship": cap["actor_relationship"],
            "proof_strength": cap["proof_strength"],
            "permission_effect": cap["permission_effect"],
            "freshness_state": cap["freshness_state"],
            "scope_sha256": cap["scope_sha256"],
            "node_id": cap["node_id"],
            "capability_receipt_sha256": cap["receipt_sha256"],
            "request_sha256": req["request_sha256"],
            "reason_code": "verified_by_callback_fixture",
        }
        decision["decision_sha256"] = canonical_sha256(decision)
        return decision

    def _run_callback(
        self,
        *,
        handle_id: str,
        callback: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        dispatch: Mapping[str, Any],
        started_at: str,
    ) -> dict[str, Any]:
        try:
            raw = callback(copy.deepcopy(dict(dispatch)))
            if not isinstance(raw, Mapping):
                raise TypeError("callback result is not an object")
            outcome = raw.get("outcome")
            artifacts = raw.get("artifact_receipts")
            evidence = raw.get("evidence_refs")
            side_effects = raw.get("side_effects")
            if outcome not in {
                "completed", "partial", "failed", "unverified", "skipped", "blocked", "cancelled", "stale"
            } or not isinstance(artifacts, list) or not isinstance(evidence, list) or not isinstance(side_effects, list):
                raise ValueError("callback result fields differ")
            if side_effects:
                raise HostAdapterError(
                    "E_V265_HOST_CAPABILITY", "Callback adapter forbids external side effects"
                )
        except HostAdapterError:
            raise
        except Exception as exc:  # callback boundary deliberately sanitizes details
            outcome = "failed"
            artifacts = []
            side_effects = []
            evidence = [
                "sha256:"
                + hashlib.sha256(type(exc).__name__.encode("utf-8")).hexdigest()
            ]
        finished_at = self._clock()
        result: dict[str, Any] = {
            "schema_version": "goal-teams-host-outcome-v2.65",
            "host_handle_id": handle_id,
            "outcome": outcome,
            "artifact_receipts": copy.deepcopy(artifacts),
            "evidence_refs": list(evidence),
            "side_effects": copy.deepcopy(side_effects),
            "started_at": started_at,
            "finished_at": finished_at,
        }
        result["observation_sha256"] = canonical_sha256(result)
        return result

    def _validated_dispatch(
        self, dispatch: Mapping[str, Any], *, observed_at: str
    ) -> dict[str, Any]:
        value = _exact(dispatch, DISPATCH_FIELDS, "Host Dispatch")
        if value["schema_version"] != "goal-teams-host-dispatch-v2.65":
            raise _error("E_V265_HOST_OBSERVATION", "Host Dispatch schema differs")
        action_ref = value["action_ref"]
        if self._callbacks.get(action_ref) is None:
            raise _error("E_V265_HOST_OBSERVATION", "Host Dispatch action has no callback")
        try:
            packet = _exact(value["member_packet"], PACKET_FIELDS, "Member Packet")
            capability = _exact(
                value["capability_receipt"], CAPABILITY_FIELDS, "Capability Receipt"
            )
            decision = _exact(
                value["capability_decision"], DECISION_FIELDS, "Capability Decision"
            )
            context = _exact(value["context_bundle"], CONTEXT_FIELDS, "Context Bundle")
            _self_digest(packet, "packet_sha256", "E_V265_HOST_CAPABILITY")
            _self_digest(capability, "receipt_sha256", "E_V265_HOST_CAPABILITY")
            _self_digest(decision, "decision_sha256", "E_V265_HOST_CAPABILITY")
            _self_digest(context, "bundle_sha256", "E_V265_HOST_CAPABILITY")
        except HostAdapterError as exc:
            raise _error("E_V265_HOST_CAPABILITY", exc.message) from exc
        scope_allowlist = _strings(
            capability["scope_allowlist"],
            "Capability scope_allowlist",
            non_empty=True,
        )
        forbidden_scope = _strings(
            capability["forbidden_scope"], "Capability forbidden_scope"
        )
        tools = _strings(
            capability["tool_allowlist"], "Capability tool_allowlist", non_empty=True
        )
        for field in ("not_before", "issued_at", "expires_at"):
            require_utc_timestamp(
                capability[field],
                error=lambda message: _error("E_V265_HOST_CAPABILITY", message),
                label=f"capability.{field}",
            )
        require_utc_timestamp(
            packet["issued_at"],
            error=lambda message: _error("E_V265_HOST_CAPABILITY", message),
            label="member_packet.issued_at",
        )
        require_utc_timestamp(
            context["compiled_at"],
            error=lambda message: _error("E_V265_HOST_CAPABILITY", message),
            label="context_bundle.compiled_at",
        )
        instant = timestamp_value(observed_at)
        if (
            context.get("schema_version") != "goal-teams-context-bundle-v2.65"
            or packet.get("schema_version") != "goal-teams-member-packet-v2.65"
            or capability.get("schema_version")
            != "goal-teams-host-capability-receipt-v2.65"
            or decision.get("schema_version")
            != "goal-teams-host-capability-decision-v2.65"
            or capability.get("issuer") != "callback_fixture"
            or capability.get("issuer_key_id") != "callback_fixture:key:1"
            or capability.get("issuer_assurance") != "repository_fixture"
            or capability.get("actor_relationship") != "self"
            or capability.get("proof_strength") != "fixture_only"
            or capability.get("freshness_state") != "current"
            or capability.get("permission_effect") != "local_execution"
            or capability.get("attestation_ref") is not None
            or capability.get("network_policy") != "deny"
            or capability.get("workspace_policy") != "node_scope"
            or tools != ["callback"]
            or scope_allowlist != capability.get("scope_allowlist")
            or forbidden_scope != capability.get("forbidden_scope")
            or capability.get("scope_sha256") != _scope_sha256(capability)
            or not is_non_empty_string(capability.get("workspace_realpath"))
            or decision.get("issuer") != capability.get("issuer")
            or decision.get("issuer_key_id") != capability.get("issuer_key_id")
            or decision.get("issuer_assurance") != capability.get("issuer_assurance")
            or decision.get("actor_relationship")
            != capability.get("actor_relationship")
            or decision.get("proof_strength") != "fixture_only"
            or decision.get("permission_effect") != "local_execution"
            or decision.get("freshness_state") != "current"
            or decision.get("verified") is not True
            or not is_non_empty_string(decision.get("reason_code"))
            or decision.get("capability_receipt_sha256")
            != capability.get("receipt_sha256")
            or decision.get("scope_sha256") != capability.get("scope_sha256")
            or decision.get("node_id") != capability.get("node_id")
            or decision.get("request_sha256")
            != packet.get("capability_request_sha256")
            or packet.get("node_id") != value["node_id"]
            or packet.get("task_id") != value["task_id"]
            or packet.get("action_ref") != action_ref
            or packet.get("owner_run_id") != capability.get("owner_run_id")
            or packet.get("owner_run_id") == packet.get("validator_run_id")
            or packet.get("scope_sha256") != capability.get("scope_sha256")
            or packet.get("capability_receipt_sha256")
            != capability.get("receipt_sha256")
            or packet.get("capability_decision_sha256")
            != decision.get("decision_sha256")
            or packet.get("context_bundle_sha256") != context.get("bundle_sha256")
            or packet.get("graph_contract_sha256")
            != capability.get("graph_contract_sha256")
            or context.get("graph_contract_sha256")
            != packet.get("graph_contract_sha256")
            or context.get("node_id") != value["node_id"]
            or capability.get("node_id") != value["node_id"]
            or not is_int(value["attempt"], minimum=1)
            or not is_non_empty_string(value["run_id"])
            or not is_non_empty_string(value["idempotency_key"])
            or not is_int(packet.get("graph_revision"), minimum=1)
            or not is_int(packet.get("plan_revision"), minimum=1)
            or not all(
                is_non_empty_string(packet.get(field))
                for field in (
                    "packet_id",
                    "graph_id",
                    "plan_id",
                    "owner_identity",
                    "validator_identity",
                    "owner_run_id",
                    "validator_run_id",
                )
            )
            or not all(
                is_sha256(packet.get(field))
                for field in (
                    "graph_contract_sha256",
                    "task_exact_set_sha256",
                    "scope_sha256",
                    "context_bundle_sha256",
                    "context_validation_receipt_sha256",
                    "capability_receipt_sha256",
                    "capability_request_sha256",
                    "capability_decision_sha256",
                )
            )
            or not (
                timestamp_value(capability["not_before"])
                <= timestamp_value(capability["issued_at"])
                <= instant
                <= timestamp_value(capability["expires_at"])
            )
        ):
            raise _error("E_V265_HOST_CAPABILITY", "Host Dispatch Capability Decision differs")
        return copy.deepcopy(value)

    def prepare(
        self, dispatch: Mapping[str, Any], *, prepared_at: str
    ) -> dict[str, Any]:
        prepared_at = require_utc_timestamp(
            prepared_at,
            error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
            label="prepared_at",
        )
        value = self._validated_dispatch(dispatch, observed_at=prepared_at)
        handle_id = f"CALLBACK-{uuid.uuid4().hex}"
        handle: dict[str, Any] = {
            "schema_version": "goal-teams-host-handle-v2.65",
            "adapter_id": self.adapter_id,
            "host_handle_id": handle_id,
            "run_id": value["run_id"],
            "node_id": value["node_id"],
            "attempt": value["attempt"],
            "transport": "thread_future",
            "proof_strength": "fixture_only",
            "dispatch_sha256": canonical_sha256(value),
            "state": "prepared",
            "prepared_at": prepared_at,
        }
        handle["handle_sha256"] = canonical_sha256(handle)
        with self._lock:
            self._handles[handle_id] = copy.deepcopy(handle)
            self._dispatches[handle_id] = copy.deepcopy(value)
            self._states[handle_id] = "prepared"
        return copy.deepcopy(handle)

    def execute(
        self,
        handle: Mapping[str, Any],
        dispatch: Mapping[str, Any],
        *,
        started_at: str,
    ) -> dict[str, Any]:
        value = _exact(handle, HANDLE_FIELDS, "Host Handle")
        _self_digest(value, "handle_sha256", "E_V265_HOST_CAPABILITY")
        started_at = require_utc_timestamp(
            started_at,
            error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
            label="started_at",
        )
        dispatch_value = self._validated_dispatch(dispatch, observed_at=started_at)
        handle_id = value["host_handle_id"]
        with self._lock:
            stored = self._handles.get(handle_id)
            stored_dispatch = self._dispatches.get(handle_id)
            state = self._states.get(handle_id)
        if (
            stored != value
            or state != "prepared"
            or stored_dispatch != dispatch_value
            or value["dispatch_sha256"] != canonical_sha256(dispatch_value)
        ):
            raise _error("E_V265_HOST_LIFECYCLE", "Host Handle is not prepared")
        callback = self._callbacks[dispatch_value["action_ref"]]
        future = self._executor.submit(
            self._run_callback,
            handle_id=handle_id,
            callback=callback,
            dispatch=copy.deepcopy(dispatch_value),
            started_at=started_at,
        )
        with self._lock:
            self._futures[handle_id] = future
            self._states[handle_id] = "running"
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-host-execution-receipt-v2.65",
            "adapter_id": self.adapter_id,
            "host_handle_id": handle_id,
            "handle_sha256": value["handle_sha256"],
            "dispatch_sha256": value["dispatch_sha256"],
            "state": "running",
            "started_at": started_at,
            "proof_strength": "fixture_only",
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def spawn(self, dispatch: Mapping[str, Any]) -> dict[str, Any]:
        prepared_at = self._clock()
        handle = self.prepare(dispatch, prepared_at=prepared_at)
        self.execute(handle, dispatch, started_at=prepared_at)
        return handle

    def _future_for(self, handle: Mapping[str, Any]) -> tuple[dict[str, Any], Future[dict[str, Any]]]:
        value = _exact(handle, HANDLE_FIELDS, "Host Handle")
        _self_digest(value, "handle_sha256", "E_V265_HOST_OBSERVATION")
        if value["adapter_id"] != self.adapter_id or value["transport"] != "thread_future":
            raise _error("E_V265_HOST_OBSERVATION", "Host Handle binding differs")
        with self._lock:
            future = self._futures.get(value["host_handle_id"])
            stored = self._handles.get(value["host_handle_id"])
        if future is None or stored != value:
            raise _error("E_V265_HOST_OBSERVATION", "Host Handle is unknown")
        return value, future

    def wait(self, handle: Mapping[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
        if not is_int(timeout_seconds, minimum=1):
            raise _error("E_V265_HOST_OBSERVATION", "timeout_seconds must be positive")
        value, future = self._future_for(handle)
        try:
            result = future.result(timeout=timeout_seconds)
        except FutureTimeout as exc:
            raise _error("E_V265_HOST_TIMEOUT", "Callback wait timed out") from exc
        finally:
            if future.done():
                with self._lock:
                    self._futures.pop(value["host_handle_id"], None)
                    self._states[value["host_handle_id"]] = "terminal"
        return copy.deepcopy(result)

    def cancel(self, handle: Mapping[str, Any]) -> dict[str, Any]:
        value, future = self._future_for(handle)
        if not future.cancel():
            raise _error("E_V265_HOST_CANCEL_UNCONFIRMED", "running callback could not be cancelled")
        with self._lock:
            self._futures.pop(value["host_handle_id"], None)
            self._states[value["host_handle_id"]] = "cancelled"
        result: dict[str, Any] = {
            "schema_version": "goal-teams-host-cancel-result-v2.65",
            "host_handle_id": value["host_handle_id"],
            "cancelled": True,
            "observed_state": "cancelled_before_start",
            "reason_code": "future_cancelled",
        }
        result["decision_sha256"] = canonical_sha256(result)
        return result

    def probe_handle(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
        host_handle_id: str,
        observed_at: str,
    ) -> dict[str, Any]:
        require_utc_timestamp(
            observed_at,
            error=lambda message: _error("E_V265_HOST_OBSERVATION", message),
            label="observed_at",
        )
        with self._lock:
            handle = self._handles.get(host_handle_id)
            state = self._states.get(host_handle_id)
            future = self._futures.get(host_handle_id)
        if handle is None:
            observed = "indeterminate"
        elif (
            handle["run_id"] != run_id
            or handle["node_id"] != node_id
            or handle["attempt"] != attempt
        ):
            observed = "indeterminate"
        elif future is not None and future.done():
            observed = "terminal"
        else:
            observed = state or "indeterminate"
        if observed not in {
            "prepared", "running", "terminal", "cancelled", "absent", "indeterminate"
        }:
            observed = "indeterminate"
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-host-probe-receipt-v2.65",
            "adapter_id": self.adapter_id,
            "host_handle_id": host_handle_id,
            "run_id": run_id,
            "node_id": node_id,
            "attempt": attempt,
            "observed_state": observed,
            "quiescent": observed in {"terminal", "cancelled", "absent"},
            "observed_at": observed_at,
            "evidence_refs": ["evidence:callback-probe"],
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def readback(
        self,
        handle: Mapping[str, Any],
        dispatch: Mapping[str, Any],
        outcome: Mapping[str, Any],
        *,
        observed_at: str,
    ) -> dict[str, Any]:
        raise _error(
            "E_V265_HOST_CAPABILITY",
            "Callback adapter cannot attest external side-effect readback",
        )

    def verify_approval(
        self, interrupt: Mapping[str, Any], approval_receipt: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(interrupt, Mapping) or not isinstance(approval_receipt, Mapping):
            raise _error("E_V265_HOST_CAPABILITY", "Approval inputs must be typed objects")
        raise _error("E_V265_HOST_CAPABILITY", "Callback adapter cannot verify external approval")

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)


__all__ = ["CallbackHostAdapter", "HostAdapter", "HostAdapterError"]
