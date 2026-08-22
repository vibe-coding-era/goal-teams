"""V2.65 Runtime orchestration across pure reducer, SQLite, and Host Adapter."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.v265.canonical import (
    canonical_sha256,
    is_int,
    is_non_empty_string,
    timestamp_value,
)
from scripts.v265.graph_runtime import (
    GraphRuntimeError,
    evaluate_next,
    make_graph_event,
    reduce_graph_events,
    validate_runtime_graph_contract,
)
from scripts.v265.member_packet import MemberPacketError, compile_member_packet
from scripts.v265.runtime_store import SQLiteRuntimeStore
from scripts.v265.host_adapter import HostAdapterError


def _utc(value: Any) -> str:
    if not isinstance(value, str):
        raise GraphRuntimeError("E_V265_RUNTIME_EVENT", "timestamp must be text")
    timestamp_value(value)
    return value


def _format_utc(value: Any) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class RuntimeController:
    """Single-writer V2.65 reference RuntimeController."""

    def __init__(
        self,
        *,
        compiled_graph: Mapping[str, Any],
        store: SQLiteRuntimeStore,
        host_adapter: Any,
        run_bindings: Mapping[str, str],
        max_workers: int,
        authorized_workspace_root: Path | str | None = None,
    ) -> None:
        validate_runtime_graph_contract(compiled_graph)
        if not is_int(max_workers, minimum=1):
            raise GraphRuntimeError("E_V265_RUNTIME_EVENT", "max_workers must be positive")
        execution_capable = callable(getattr(host_adapter, "prepare", None)) and callable(
            getattr(host_adapter, "execute", None)
        )
        if execution_capable and not callable(
            getattr(host_adapter, "probe_handle", None)
        ):
            raise GraphRuntimeError(
                "E_V265_HOST_LIFECYCLE",
                "execution Host must provide probe_handle",
            )
        authorized_root: Path | None = None
        selected_workspace_root = (
            store.runtime_root
            if authorized_workspace_root is None
            else authorized_workspace_root
        )
        if selected_workspace_root is not None:
            candidate = Path(selected_workspace_root)
            if (
                not candidate.is_absolute()
                or not candidate.exists()
                or not candidate.is_dir()
                or candidate.is_symlink()
                or candidate.resolve(strict=True) != candidate
            ):
                raise GraphRuntimeError(
                    "E_V265_MEMBER_SCOPE", "authorized workspace root is unsafe"
                )
            authorized_root = candidate
        self.compiled_graph = copy.deepcopy(dict(compiled_graph))
        self.store = store
        self.host_adapter = host_adapter
        self.run_bindings = copy.deepcopy(dict(run_bindings))
        self.max_workers = max_workers
        self.authorized_workspace_root = authorized_root
        self._live_handles: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._live_dispatches: dict[tuple[str, str, int], dict[str, Any]] = {}

    def _assert_workspace(
        self, capability_receipt: Mapping[str, Any], node: Mapping[str, Any]
    ) -> None:
        if self.authorized_workspace_root is None:
            return
        raw = capability_receipt.get("workspace_realpath")
        if not is_non_empty_string(raw):
            raise GraphRuntimeError("E_V265_MEMBER_SCOPE", "workspace realpath is absent")
        path = Path(str(raw))
        if not path.is_absolute():
            raise GraphRuntimeError("E_V265_MEMBER_SCOPE", "workspace path is relative")
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            if current.is_symlink():
                raise GraphRuntimeError(
                    "E_V265_MEMBER_SCOPE", "workspace path crosses a symlink"
                )
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.authorized_workspace_root)
        except (OSError, ValueError) as exc:
            raise GraphRuntimeError(
                "E_V265_MEMBER_SCOPE", "workspace path escapes authorized root"
            ) from exc
        if not resolved.is_dir() or resolved != path:
            raise GraphRuntimeError("E_V265_MEMBER_SCOPE", "workspace path is not canonical")
        pattern_root = (
            resolved.parents[1]
            if resolved.parent.name == "scope" and len(resolved.parents) > 1
            else resolved
        )
        for pattern in [*node["scope_allowlist"], *node["forbidden_scope"]]:
            if not isinstance(pattern, str) or not pattern or "\\" in pattern:
                raise GraphRuntimeError(
                    "E_V265_MEMBER_SCOPE", "scope pattern is invalid"
                )
            parts = pattern.split("/")
            if pattern.startswith("/") or any(
                part in {"", ".", ".."} for part in parts
            ):
                raise GraphRuntimeError(
                    "E_V265_MEMBER_SCOPE", "scope pattern escapes workspace"
                )
            glob_index = next(
                (
                    index
                    for index, part in enumerate(parts)
                    if any(mark in part for mark in "*?[")
                ),
                len(parts),
            )
            current = pattern_root
            for part in parts[:glob_index]:
                current = current / part
                if current.is_symlink():
                    raise GraphRuntimeError(
                        "E_V265_MEMBER_SCOPE", "scope prefix crosses a symlink"
                    )
            try:
                current.resolve(strict=False).relative_to(
                    self.authorized_workspace_root
                )
            except (OSError, ValueError) as exc:
                raise GraphRuntimeError(
                    "E_V265_MEMBER_SCOPE", "scope prefix escapes authority"
                ) from exc

    def _projection(self, run_id: str) -> dict[str, Any]:
        return reduce_graph_events(
            self.compiled_graph,
            self.store.load_events(run_id),
            expected_bindings=self.run_bindings,
        )

    def _head(self, run_id: str, expected_revision: int | None = None) -> dict[str, Any]:
        head = self.store.read_run_head(run_id)
        if expected_revision is not None and head["revision"] != expected_revision:
            raise GraphRuntimeError("E_V265_RUNTIME_CAS", "controller revision differs")
        return head

    def _event(
        self,
        *,
        run_id: str,
        event_type: str,
        node_id: str | None,
        attempt: int,
        payload: Mapping[str, Any],
        evidence_refs: Sequence[str],
        actor_identity: str,
        occurred_at: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        head = self._head(run_id, expected_revision)
        return make_graph_event(
            run_id=run_id,
            event_id=f"EVENT-{run_id}-{expected_revision + 1}",
            event_seq=expected_revision + 1,
            event_type=event_type,
            node_id=node_id,
            attempt=attempt,
            cas_base_revision=expected_revision,
            previous_event_sha256=head["last_event_sha256"],
            bindings=self.run_bindings,
            payload=payload,
            evidence_refs=evidence_refs,
            actor_identity=actor_identity,
            actor_relationship="authorized_writer",
            occurred_at=occurred_at,
        )

    def _mutation(
        self,
        *,
        operation: str,
        run_id: str,
        node_id: str | None,
        event: Mapping[str, Any],
        store_receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        projection = self._projection(run_id)
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-controller-mutation-receipt-v2.65",
            "operation": operation,
            "run_id": run_id,
            "node_id": node_id,
            "event": copy.deepcopy(dict(event)),
            "store_receipt": copy.deepcopy(dict(store_receipt)),
            "revision": projection["revision"],
            "projection_sha256": projection["projection_sha256"],
            "host_quiescence_assurance": "not_applicable",
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def _append_controller_event(
        self,
        *,
        run_id: str,
        node_id: str,
        event_type: str,
        attempt: int,
        payload: Mapping[str, Any],
        evidence_refs: Sequence[str],
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        event = self._event(
            run_id=run_id,
            event_type=event_type,
            node_id=node_id,
            attempt=attempt,
            payload=payload,
            evidence_refs=evidence_refs,
            actor_identity="runtime_controller",
            occurred_at=_utc(now),
            expected_revision=expected_revision,
        )
        store_receipt = self.store.append_event(
            run_id, event, expected_revision=expected_revision
        )
        return self._mutation(
            operation=event_type,
            run_id=run_id,
            node_id=node_id,
            event=event,
            store_receipt=store_receipt,
        )

    def create_run(self, *, run_id: str, created_at: str) -> dict[str, Any]:
        store_receipt = self.store.create_run(
            run_id,
            self.compiled_graph,
            self.run_bindings,
            created_at=_utc(created_at),
        )
        event = self.store.load_events(run_id)[0]
        return self._mutation(
            operation="run.created",
            run_id=run_id,
            node_id=None,
            event=event,
            store_receipt=store_receipt,
        )

    def evaluate_next(self, *, run_id: str, now: str) -> list[dict[str, Any]]:
        return evaluate_next(
            self.compiled_graph,
            self.store.load_events(run_id),
            expected_bindings=self.run_bindings,
            now=_utc(now),
        )

    def _ensure_ready_event(
        self, *, run_id: str, node_id: str, now: str, expected_revision: int
    ) -> int:
        projection = self._projection(run_id)
        if projection["nodes"][node_id]["execution_state"] == "ready":
            return expected_revision
        descriptor = next(
            (item for item in self.evaluate_next(run_id=run_id, now=now) if item["node_id"] == node_id),
            None,
        )
        if descriptor is None:
            raise GraphRuntimeError("E_V265_RUNTIME_PREDECESSOR", "Node is not ready")
        event = self._event(
            run_id=run_id,
            event_type="node.ready",
            node_id=node_id,
            attempt=descriptor["next_attempt"],
            payload={
                key: descriptor[key]
                for key in (
                    "satisfied_edge_ids",
                    "fan_in_mode",
                    "required_edge_count",
                    "satisfied_edge_count",
                )
            },
            evidence_refs=["evidence:ready-evaluation"],
            actor_identity="runtime_controller",
            occurred_at=now,
            expected_revision=expected_revision,
        )
        self.store.append_event(run_id, event, expected_revision=expected_revision)
        return expected_revision + 1

    def claim_node(
        self,
        *,
        run_id: str,
        node_id: str,
        worker_id: str,
        lease_seconds: int,
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        now = _utc(now)
        head = self._head(run_id, expected_revision)
        projection = self._projection(run_id)
        node = next((item for item in self.compiled_graph["nodes"] if item["node_id"] == node_id), None)
        if node is None:
            raise GraphRuntimeError("E_V265_RUNTIME_EVENT", "Node is absent")
        state = projection["nodes"][node_id]
        if state["attempt"] >= node["budget"]["attempts"]:
            raise GraphRuntimeError("E_V265_RUNTIME_ATTEMPT_BUDGET", "Node attempt budget is exhausted")
        if state["execution_state"] != "ready":
            raise GraphRuntimeError("E_V265_RUNTIME_TRANSITION", "Node is not ready")
        if not is_non_empty_string(worker_id) or not is_int(lease_seconds, minimum=1):
            raise GraphRuntimeError("E_V265_RUNTIME_LEASE", "lease request is invalid")
        attempt = state["attempt"] + 1
        expires = _format_utc(timestamp_value(now) + timedelta(seconds=lease_seconds))
        event = self._event(
            run_id=run_id,
            event_type="node.claimed",
            node_id=node_id,
            attempt=attempt,
            payload={
                "worker_id": worker_id,
                "lease_id": f"LEASE-{run_id}-{node_id}-{attempt}",
                "lease_expires_at": expires,
            },
            evidence_refs=["evidence:lease-claim"],
            actor_identity="runtime_controller",
            occurred_at=now,
            expected_revision=head["revision"],
        )
        store_receipt = self.store.claim_lease(
            run_id, event, expected_revision=head["revision"]
        )
        return self._mutation(
            operation="node.claimed",
            run_id=run_id,
            node_id=node_id,
            event=event,
            store_receipt=store_receipt,
        )

    def _prepare_dispatch(
        self,
        *,
        run_id: str,
        node_id: str,
        owner_run_id: str,
        validator_run_id: str,
        context_bundle: Mapping[str, Any],
        context_validation_receipt: Mapping[str, Any],
        capability_receipt: Mapping[str, Any],
        idempotency_key: str,
        now: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        projection = self._projection(run_id)
        state = projection["nodes"][node_id]
        node = next(item for item in self.compiled_graph["nodes"] if item["node_id"] == node_id)
        self._assert_workspace(capability_receipt, node)
        trusted_issuers = getattr(self.host_adapter, "trusted_issuer_ids", frozenset())
        if capability_receipt.get("issuer") not in trusted_issuers:
            raise GraphRuntimeError(
                "E_V265_MEMBER_CAPABILITY", "Capability issuer is not trusted by Host"
            )
        request: dict[str, Any] = {
            "schema_version": "goal-teams-host-capability-request-v2.65",
            "run_id": run_id,
            "node_id": node_id,
            "task_id": node["task_refs"][0],
            "attempt": state["attempt"],
            "action_ref": node["action_ref"],
            "owner_run_id": owner_run_id,
            "graph_contract_sha256": self.compiled_graph["receipt_sha256"],
            "scope_sha256": canonical_sha256(
                {
                    "scope_allowlist": node["scope_allowlist"],
                    "forbidden_scope": node["forbidden_scope"],
                }
            ),
            "context_bundle_sha256": context_bundle["bundle_sha256"],
            "capability_receipt_sha256": capability_receipt["receipt_sha256"],
            "requested_at": now,
        }
        request["request_sha256"] = canonical_sha256(request)
        decision = self.host_adapter.verify_capability(request, capability_receipt)
        try:
            packet = compile_member_packet(
                packet_id=f"PACKET-{run_id}-{node_id}-{state['attempt']}",
                compiled_graph=self.compiled_graph,
                node_id=node_id,
                owner_run_id=owner_run_id,
                validator_run_id=validator_run_id,
                context_bundle=context_bundle,
                context_validation_receipt=context_validation_receipt,
                capability_receipt=capability_receipt,
                capability_request=request,
                capability_decision=decision,
                issued_at=now,
                authorized_workspace_root=self.authorized_workspace_root,
            )
        except MemberPacketError as exc:
            raise GraphRuntimeError(exc.code, exc.message) from exc
        dispatch = {
            "schema_version": "goal-teams-host-dispatch-v2.65",
            "run_id": run_id,
            "node_id": node_id,
            "task_id": node["task_refs"][0],
            "attempt": state["attempt"],
            "action_ref": node["action_ref"],
            "member_packet": packet,
            "context_bundle": copy.deepcopy(dict(context_bundle)),
            "capability_receipt": copy.deepcopy(dict(capability_receipt)),
            "capability_decision": copy.deepcopy(dict(decision)),
            "idempotency_key": idempotency_key,
        }
        return request, decision, packet, dispatch, state

    def _start_with_handle(
        self,
        *,
        run_id: str,
        node_id: str,
        owner_run_id: str,
        validator_run_id: str,
        context_bundle: Mapping[str, Any],
        capability_receipt: Mapping[str, Any],
        request: Mapping[str, Any],
        decision: Mapping[str, Any],
        packet: Mapping[str, Any],
        handle: Mapping[str, Any],
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        projection = self._projection(run_id)
        state = projection["nodes"][node_id]
        event = self._event(
            run_id=run_id,
            event_type="node.started",
            node_id=node_id,
            attempt=state["attempt"],
            payload={
                "owner_run_id": owner_run_id,
                "validator_run_id": validator_run_id,
                "member_packet": copy.deepcopy(dict(packet)),
                "context_bundle_sha256": context_bundle["bundle_sha256"],
                "capability_receipt": copy.deepcopy(dict(capability_receipt)),
                "capability_request": copy.deepcopy(dict(request)),
                "capability_decision": copy.deepcopy(dict(decision)),
                "host_handle_id": handle["host_handle_id"],
            },
            evidence_refs=["evidence:host-dispatch"],
            actor_identity=owner_run_id,
            occurred_at=now,
            expected_revision=expected_revision,
        )
        store_receipt = self.store.record_attempt(
            run_id, event, expected_revision=expected_revision
        )
        return self._mutation(
            operation="node.started",
            run_id=run_id,
            node_id=node_id,
            event=event,
            store_receipt=store_receipt,
        )

    def start_node(
        self,
        *,
        run_id: str,
        node_id: str,
        lease_id: str,
        owner_run_id: str,
        validator_run_id: str,
        context_bundle: Mapping[str, Any],
        context_validation_receipt: Mapping[str, Any],
        capability_receipt: Mapping[str, Any],
        now: str,
        expected_revision: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        now = _utc(now)
        state = self._projection(run_id)["nodes"][node_id]
        if state["lease_id"] != lease_id:
            raise GraphRuntimeError("E_V265_RUNTIME_LEASE", "lease ID differs")
        selected_key = idempotency_key or f"IDEMPOTENCY-{run_id}-{node_id}-{state['attempt']}"
        request, decision, packet, dispatch, _ = self._prepare_dispatch(
            run_id=run_id,
            node_id=node_id,
            owner_run_id=owner_run_id,
            validator_run_id=validator_run_id,
            context_bundle=context_bundle,
            context_validation_receipt=context_validation_receipt,
            capability_receipt=capability_receipt,
            idempotency_key=selected_key,
            now=now,
        )
        prepare = getattr(self.host_adapter, "prepare", None)
        execute = getattr(self.host_adapter, "execute", None)
        if not callable(prepare) or not callable(execute):
            raise GraphRuntimeError(
                "E_V265_HOST_LIFECYCLE", "Host lacks prepare/execute lifecycle"
            )
        handle = prepare(dispatch, prepared_at=now)
        prepared = self._append_controller_event(
            run_id=run_id,
            node_id=node_id,
            event_type="host.prepared",
            attempt=state["attempt"],
            payload={
                "host_handle": copy.deepcopy(dict(handle)),
                "dispatch_sha256": canonical_sha256(dispatch),
            },
            evidence_refs=["evidence:host-prepared"],
            now=now,
            expected_revision=expected_revision,
        )
        start = self._start_with_handle(
            run_id=run_id,
            node_id=node_id,
            owner_run_id=owner_run_id,
            validator_run_id=validator_run_id,
            context_bundle=context_bundle,
            capability_receipt=capability_receipt,
            request=request,
            decision=decision,
            packet=packet,
            handle=handle,
            now=now,
            expected_revision=prepared["revision"],
        )
        revision = start["revision"]
        action = next(
            item
            for item in self.compiled_graph["actions"]
            if item["action_id"] == dispatch["action_ref"]
        )
        if action["effect"] == "external_write":
            intent = self._append_controller_event(
                run_id=run_id,
                node_id=node_id,
                event_type="side_effect.intent",
                attempt=state["attempt"],
                payload={
                    "idempotency_key": selected_key,
                    "action_sha256": canonical_sha256(action),
                },
                evidence_refs=["evidence:side-effect-intent"],
                now=now,
                expected_revision=revision,
            )
            revision = intent["revision"]
        execution_receipt = execute(handle, dispatch, started_at=now)
        execution = self._append_controller_event(
            run_id=run_id,
            node_id=node_id,
            event_type="host.execution_started",
            attempt=state["attempt"],
            payload={
                "host_handle_sha256": handle["handle_sha256"],
                "execution_receipt": copy.deepcopy(dict(execution_receipt)),
            },
            evidence_refs=["evidence:host-execution"],
            now=now,
            expected_revision=revision,
        )
        key = (run_id, node_id, int(state["attempt"]))
        self._live_handles[key] = copy.deepcopy(dict(handle))
        self._live_dispatches[key] = copy.deepcopy(dict(dispatch))
        return execution

    def heartbeat(
        self,
        *,
        run_id: str,
        node_id: str,
        lease_id: str,
        new_expires_at: str,
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        state = self._projection(run_id)["nodes"][node_id]
        event = self._event(
            run_id=run_id,
            event_type="node.heartbeat",
            node_id=node_id,
            attempt=state["attempt"],
            payload={"lease_id": lease_id, "previous_expires_at": state["lease_expires_at"], "new_expires_at": new_expires_at},
            evidence_refs=["evidence:heartbeat"],
            actor_identity="runtime_controller",
            occurred_at=_utc(now),
            expected_revision=expected_revision,
        )
        store_receipt = self.store.renew_lease(run_id, event, expected_revision=expected_revision)
        return self._mutation(operation="node.heartbeat", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)

    def _record_host_observation(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
        observation_type: str,
        host_handle_id: str,
        observation_receipt: Mapping[str, Any],
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        digest_field = (
            "decision_sha256" if observation_type == "cancel" else "receipt_sha256"
        )
        return self._append_controller_event(
            run_id=run_id,
            node_id=node_id,
            event_type="host.observation_recorded",
            attempt=attempt,
            payload={
                "observation_type": observation_type,
                "host_handle_id": host_handle_id,
                "observation_receipt": copy.deepcopy(dict(observation_receipt)),
                "observation_sha256": observation_receipt[digest_field],
            },
            evidence_refs=[f"evidence:host-{observation_type}"],
            now=now,
            expected_revision=expected_revision,
        )

    def complete_node(
        self,
        *,
        run_id: str,
        node_id: str,
        lease_id: str,
        artifact_receipts: Sequence[Mapping[str, Any]],
        evidence_refs: Sequence[str],
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        state = self._projection(run_id)["nodes"][node_id]
        if state["lease_id"] != lease_id:
            raise GraphRuntimeError("E_V265_RUNTIME_LEASE", "lease ID differs")
        event = self._event(
            run_id=run_id,
            event_type="node.outcome_recorded",
            node_id=node_id,
            attempt=state["attempt"],
            payload={"outcome": "completed", "owner_run_id": state["owner_run_id"], "artifact_receipts": list(artifact_receipts)},
            evidence_refs=evidence_refs,
            actor_identity=state["owner_run_id"],
            occurred_at=_utc(now),
            expected_revision=expected_revision,
        )
        store_receipt = self.store.record_attempt(run_id, event, expected_revision=expected_revision)
        return self._mutation(operation="node.outcome_recorded", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)

    def fail_node(
        self,
        *,
        run_id: str,
        node_id: str,
        lease_id: str,
        outcome: str,
        failure_artifacts: Sequence[Mapping[str, Any]],
        evidence_refs: Sequence[str],
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        state = self._projection(run_id)["nodes"][node_id]
        if outcome not in {"failed", "partial", "unverified"} or state["lease_id"] != lease_id:
            raise GraphRuntimeError("E_V265_RUNTIME_OUTCOME", "failure Outcome or lease differs")
        event = self._event(
            run_id=run_id, event_type="node.outcome_recorded", node_id=node_id, attempt=state["attempt"],
            payload={"outcome": outcome, "owner_run_id": state["owner_run_id"], "artifact_receipts": list(failure_artifacts)},
            evidence_refs=evidence_refs, actor_identity=state["owner_run_id"], occurred_at=_utc(now), expected_revision=expected_revision,
        )
        store_receipt = self.store.record_attempt(run_id, event, expected_revision=expected_revision)
        return self._mutation(operation="node.outcome_recorded", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)

    def block_node(self, *, run_id: str, node_id: str, blocker_id: str, evidence_refs: Sequence[str], now: str, expected_revision: int) -> dict[str, Any]:
        state = self._projection(run_id)["nodes"][node_id]
        event = self._event(
            run_id=run_id, event_type="node.blocked", node_id=node_id, attempt=max(1, state["attempt"]),
            payload={"blocker_id": blocker_id}, evidence_refs=evidence_refs, actor_identity="runtime_controller",
            occurred_at=_utc(now), expected_revision=expected_revision,
        )
        store_receipt = self.store.append_event(run_id, event, expected_revision=expected_revision)
        return self._mutation(operation="node.blocked", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)

    def validate_node(self, *, run_id: str, node_id: str, validator_run_id: str, validation_receipt: Mapping[str, Any], now: str, expected_revision: int) -> dict[str, Any]:
        state = self._projection(run_id)["nodes"][node_id]
        event = self._event(
            run_id=run_id, event_type="node.validation_recorded", node_id=node_id, attempt=state["attempt"],
            payload={"validation_state": validation_receipt["validation_state"], "validator_run_id": validator_run_id,
                     "validation_receipt": copy.deepcopy(dict(validation_receipt)), "observed_outcome": validation_receipt["observed_outcome"]},
            evidence_refs=validation_receipt["evidence_refs"], actor_identity=validator_run_id,
            occurred_at=_utc(now), expected_revision=expected_revision,
        )
        store_receipt = self.store.record_attempt(run_id, event, expected_revision=expected_revision)
        return self._mutation(operation="node.validation_recorded", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)

    @staticmethod
    def _with_quiescence_assurance(
        receipt: Mapping[str, Any], assurance: str
    ) -> dict[str, Any]:
        result = copy.deepcopy(dict(receipt))
        result["host_quiescence_assurance"] = assurance
        result["receipt_sha256"] = canonical_sha256(
            {key: value for key, value in result.items() if key != "receipt_sha256"}
        )
        return result

    def _quiescence_before_control(
        self,
        *,
        run_id: str,
        node_id: str,
        now: str,
        expected_revision: int,
        evidence_refs: Sequence[str],
        allow_legacy_interrupt: bool,
    ) -> tuple[bool, int, dict[str, Any] | None, str, list[str]]:
        projection = self._projection(run_id)
        state = projection["nodes"][node_id]
        handle_id = str(state["host_handle_id"])
        key = (run_id, node_id, int(state["attempt"]))
        handle = self._live_handles.get(key)
        durable_handle = projection["host_handles"].get(handle_id)
        revision = expected_revision
        linked_evidence = list(evidence_refs)
        quiescent = False
        assurance = "unconfirmed"

        if handle is not None:
            cancel_result: Mapping[str, Any] | None = None
            try:
                cancel_result = self.host_adapter.cancel(handle)
            except HostAdapterError:
                cancel_result = None
            if cancel_result is not None:
                observed = self._record_host_observation(
                    run_id=run_id,
                    node_id=node_id,
                    attempt=state["attempt"],
                    observation_type="cancel",
                    host_handle_id=handle_id,
                    observation_receipt=cancel_result,
                    now=now,
                    expected_revision=revision,
                )
                revision = observed["revision"]
                linked_evidence.append(
                    f"sha256:{cancel_result['decision_sha256']}"
                )
                quiescent = bool(cancel_result.get("cancelled"))
            if not quiescent:
                probe = self.host_adapter.probe_handle(
                    run_id=run_id,
                    node_id=node_id,
                    attempt=state["attempt"],
                    host_handle_id=handle_id,
                    observed_at=now,
                )
                observed = self._record_host_observation(
                    run_id=run_id,
                    node_id=node_id,
                    attempt=state["attempt"],
                    observation_type="probe",
                    host_handle_id=handle_id,
                    observation_receipt=probe,
                    now=now,
                    expected_revision=revision,
                )
                revision = observed["revision"]
                linked_evidence.append(f"sha256:{probe['receipt_sha256']}")
                quiescent = probe.get("quiescent") is True
            assurance = "confirmed" if quiescent else "unconfirmed"
        elif durable_handle is not None:
            probe_handle = getattr(self.host_adapter, "probe_handle", None)
            if callable(probe_handle):
                probe = probe_handle(
                    run_id=run_id,
                    node_id=node_id,
                    attempt=state["attempt"],
                    host_handle_id=handle_id,
                    observed_at=now,
                )
                observed = self._record_host_observation(
                    run_id=run_id,
                    node_id=node_id,
                    attempt=state["attempt"],
                    observation_type="probe",
                    host_handle_id=handle_id,
                    observation_receipt=probe,
                    now=now,
                    expected_revision=revision,
                )
                revision = observed["revision"]
                linked_evidence.append(f"sha256:{probe['receipt_sha256']}")
                quiescent = probe.get("quiescent") is True
                assurance = "confirmed" if quiescent else "unconfirmed"
        else:
            approval_only = (
                not callable(getattr(self.host_adapter, "prepare", None))
                and not callable(getattr(self.host_adapter, "execute", None))
                and callable(getattr(self.host_adapter, "verify_approval", None))
                and getattr(self.host_adapter, "proof_strength", None)
                == "externally_attested"
            )
            if approval_only and allow_legacy_interrupt:
                return True, revision, None, "not_observed", linked_evidence

        if quiescent:
            return True, revision, None, assurance, linked_evidence
        blocked = self.block_node(
            run_id=run_id,
            node_id=node_id,
            blocker_id=f"host_quiescence_unconfirmed:{handle_id}",
            evidence_refs=linked_evidence or ["evidence:host-quiescence"],
            now=now,
            expected_revision=revision,
        )
        blocked = self._with_quiescence_assurance(blocked, "unconfirmed")
        return False, blocked["revision"], blocked, "unconfirmed", linked_evidence

    def interrupt(self, *, run_id: str, node_id: str, gate_id: str, interrupt_id: str, reason: str, evidence_refs: Sequence[str], now: str, expected_revision: int) -> dict[str, Any]:
        now = _utc(now)
        self._head(run_id, expected_revision)
        quiescent, revision, blocked, assurance, linked_evidence = self._quiescence_before_control(
            run_id=run_id,
            node_id=node_id,
            now=now,
            expected_revision=expected_revision,
            evidence_refs=evidence_refs,
            allow_legacy_interrupt=True,
        )
        if not quiescent:
            assert blocked is not None
            return blocked
        state = self._projection(run_id)["nodes"][node_id]
        event = self._event(
            run_id=run_id, event_type="node.interrupted", node_id=node_id, attempt=state["attempt"],
            payload={"interrupt_id": interrupt_id, "gate_id": gate_id, "reason": reason,
                     "capability_receipt_sha256": state["capability_receipt_sha256"]},
            evidence_refs=linked_evidence, actor_identity="runtime_controller", occurred_at=now, expected_revision=revision,
        )
        store_receipt = self.store.record_interrupt(run_id, event, expected_revision=revision)
        receipt = self._mutation(operation="node.interrupted", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)
        return self._with_quiescence_assurance(receipt, assurance)

    def resume(self, *, run_id: str, node_id: str, interrupt_id: str, approval_receipt: Mapping[str, Any], now: str, expected_revision: int) -> dict[str, Any]:
        now = _utc(now)
        interrupts = {item["interrupt_id"]: item for item in self.store.read_interrupts(run_id)}
        interrupt = interrupts.get(interrupt_id)
        if interrupt is None or interrupt["node_id"] != node_id or interrupt["state"] != "waiting_user":
            raise GraphRuntimeError("E_V265_RUNTIME_GATE", "interrupt identity differs")
        node = next(item for item in self.compiled_graph["nodes"] if item["node_id"] == node_id)
        if (
            approval_receipt.get("issuer") not in self.host_adapter.trusted_issuer_ids
            or approval_receipt.get("interrupt_id") != interrupt_id
            or approval_receipt.get("gate_id") != interrupt["gate_id"]
            or approval_receipt.get("scope_sha256") != canonical_sha256({"scope_allowlist": node["scope_allowlist"], "forbidden_scope": node["forbidden_scope"]})
            or approval_receipt.get("decision") != "approve"
            or canonical_sha256({key: value for key, value in approval_receipt.items() if key != "receipt_sha256"}) != approval_receipt.get("receipt_sha256")
            or not (timestamp_value(approval_receipt["not_before"]) <= timestamp_value(approval_receipt["issued_at"]) <= timestamp_value(now) <= timestamp_value(approval_receipt["expires_at"]))
        ):
            raise GraphRuntimeError("E_V265_RUNTIME_GATE", "Approval Receipt binding differs")
        decision = self.host_adapter.verify_approval(interrupt, approval_receipt)
        if (
            decision.get("verified") is not True
            or decision.get("interrupt_id") != interrupt_id
            or decision.get("approval_receipt_sha256") != approval_receipt["receipt_sha256"]
            or decision.get("scope_sha256") != approval_receipt["scope_sha256"]
            or decision.get("expires_at") != approval_receipt["expires_at"]
            or canonical_sha256({key: value for key, value in decision.items() if key != "decision_sha256"}) != decision.get("decision_sha256")
        ):
            raise GraphRuntimeError("E_V265_RUNTIME_GATE", "Approval Decision binding differs")
        state = self._projection(run_id)["nodes"][node_id]
        event = self._event(
            run_id=run_id, event_type="node.resumed", node_id=node_id, attempt=state["attempt"],
            payload={"interrupt_id": interrupt_id, "approval_receipt": copy.deepcopy(dict(approval_receipt)),
                     "approval_decision": copy.deepcopy(dict(decision)), "decision": "approve"},
            evidence_refs=["evidence:approval"], actor_identity="runtime_controller", occurred_at=now, expected_revision=expected_revision,
        )
        store_receipt = self.store.resolve_interrupt(run_id, event, expected_revision=expected_revision)
        return self._mutation(operation="node.resumed", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)

    def cancel(self, *, run_id: str, node_id: str, reason: str, evidence_refs: Sequence[str], now: str, expected_revision: int) -> dict[str, Any]:
        now = _utc(now)
        self._head(run_id, expected_revision)
        quiescent, revision, blocked, assurance, linked_evidence = self._quiescence_before_control(
            run_id=run_id,
            node_id=node_id,
            now=now,
            expected_revision=expected_revision,
            evidence_refs=evidence_refs,
            allow_legacy_interrupt=False,
        )
        if not quiescent:
            assert blocked is not None
            return blocked
        state = self._projection(run_id)["nodes"][node_id]
        event = self._event(
            run_id=run_id, event_type="node.cancelled", node_id=node_id, attempt=max(1, state["attempt"]),
            payload={"reason": reason}, evidence_refs=linked_evidence, actor_identity="runtime_controller",
            occurred_at=now, expected_revision=revision,
        )
        store_receipt = self.store.append_event(run_id, event, expected_revision=revision)
        receipt = self._mutation(operation="node.cancelled", run_id=run_id, node_id=node_id, event=event, store_receipt=store_receipt)
        return self._with_quiescence_assurance(receipt, assurance)

    def _indeterminate_probe_receipt(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt: int,
        host_handle_id: str,
        observed_at: str,
        reason: str,
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-host-probe-receipt-v2.65",
            "adapter_id": str(getattr(self.host_adapter, "adapter_id", "unknown-host")),
            "host_handle_id": host_handle_id,
            "run_id": run_id,
            "node_id": node_id,
            "attempt": attempt,
            "observed_state": "indeterminate",
            "quiescent": False,
            "observed_at": observed_at,
            "evidence_refs": [f"evidence:probe-{reason}"],
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def recover(self, *, run_id: str, now: str) -> dict[str, Any]:
        now = _utc(now)
        self.store.verify_run(run_id)
        before_head = self._head(run_id)
        before = before_head["revision"]
        checkpoint = self.store.load_checkpoint(run_id)
        expired: list[str] = []
        reconciliation: list[str] = []
        projection = self._projection(run_id)
        durable_handles = sorted(
            projection["host_handles"].items(), key=lambda item: item[0]
        )
        for handle_id, durable_handle in durable_handles:
            if durable_handle.get("state") not in {"prepared", "running"}:
                continue
            node_id = str(durable_handle["node_id"])
            state = projection["nodes"][node_id]
            attempt = int(durable_handle["attempt"])
            probe_handle = getattr(self.host_adapter, "probe_handle", None)
            if callable(probe_handle):
                try:
                    probe = probe_handle(
                        run_id=run_id,
                        node_id=node_id,
                        attempt=attempt,
                        host_handle_id=str(handle_id),
                        observed_at=now,
                    )
                except HostAdapterError:
                    probe = self._indeterminate_probe_receipt(
                        run_id=run_id,
                        node_id=node_id,
                        attempt=attempt,
                        host_handle_id=str(handle_id),
                        observed_at=now,
                        reason="error",
                    )
            else:
                probe = self._indeterminate_probe_receipt(
                    run_id=run_id,
                    node_id=node_id,
                    attempt=attempt,
                    host_handle_id=str(handle_id),
                    observed_at=now,
                    reason="missing",
                )
            head = self._head(run_id)
            observed = self._record_host_observation(
                run_id=run_id,
                node_id=node_id,
                attempt=attempt,
                observation_type="probe",
                host_handle_id=str(handle_id),
                observation_receipt=probe,
                now=now,
                expected_revision=head["revision"],
            )
            if probe.get("quiescent") is not True:
                blocked = self.block_node(
                    run_id=run_id,
                    node_id=node_id,
                    blocker_id=f"host_quiescence_unconfirmed:{handle_id}",
                    evidence_refs=[f"sha256:{probe['receipt_sha256']}"],
                    now=now,
                    expected_revision=observed["revision"],
                )
                projection = self._projection(run_id)
            else:
                projection = self._projection(run_id)
        for key, record in sorted(projection["idempotency"].items()):
            if record["state"] != "pending":
                continue
            node_id = record["node_id"]
            state = projection["nodes"][node_id]
            head = self._head(run_id)
            event = self._event(
                run_id=run_id, event_type="side_effect.reconciliation_required", node_id=node_id,
                attempt=state["attempt"], payload={"idempotency_key": key, "reason_code": "restart_pending_result_unknown"},
                evidence_refs=["evidence:recovery-pending-side-effect"], actor_identity="runtime_controller",
                occurred_at=now, expected_revision=head["revision"],
            )
            self.store.append_event(run_id, event, expected_revision=head["revision"])
            reconciliation.append(node_id)
            projection = self._projection(run_id)
        for node_id, state in sorted(projection["nodes"].items()):
            if state["execution_state"] not in {"claimed", "active"} or state["lease_expires_at"] is None:
                continue
            if timestamp_value(state["lease_expires_at"]) >= timestamp_value(now):
                continue
            node = next(item for item in self.compiled_graph["nodes"] if item["node_id"] == node_id)
            decision = "ready" if state["attempt"] < node["budget"]["attempts"] else "failed"
            head = self._head(run_id)
            event = self._event(
                run_id=run_id, event_type="node.lease_expired", node_id=node_id, attempt=state["attempt"],
                payload={"lease_id": state["lease_id"], "lease_expires_at": state["lease_expires_at"], "recovery_decision": decision},
                evidence_refs=["evidence:lease-expiry"], actor_identity="runtime_controller", occurred_at=now,
                expected_revision=head["revision"],
            )
            self.store.release_lease(run_id, event, expected_revision=head["revision"])
            expired.append(node_id)
            projection = self._projection(run_id)
        ready_ids = sorted(
            node_id
            for node_id, state in projection["nodes"].items()
            if state["execution_state"] == "ready"
        )
        result: dict[str, Any] = {
            "schema_version": "goal-teams-runtime-recovery-receipt-v2.65",
            "run_id": run_id,
            "checkpoint_revision": 0 if checkpoint is None else checkpoint["revision"],
            "replayed_event_count": len(self.store.load_events(run_id)),
            "expired_lease_node_ids": expired,
            "reconciliation_required_node_ids": sorted(set(reconciliation)),
            "ready_node_ids": ready_ids,
            "revision_before": before,
            "revision_after": projection["revision"],
            "projection_sha256": projection["projection_sha256"],
        }
        result["receipt_sha256"] = canonical_sha256(result)
        return result

    def schedule_retry(
        self,
        *,
        run_id: str,
        node_id: str,
        source_edge_id: str,
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        now = _utc(now)
        self._head(run_id, expected_revision)
        projection = self._projection(run_id)
        state = projection["nodes"].get(node_id)
        if state is None:
            raise GraphRuntimeError("E_V265_RUNTIME_EVENT", "retry Node is absent")
        traversal_count = projection["traversal_counts"].get(source_edge_id, 0) + 1
        if source_edge_id == f"retry_policy:{node_id}":
            next_attempt = state["attempt"] + 1
        else:
            edge = next(
                (
                    item
                    for item in self.compiled_graph["edges"]
                    if item["edge_id"] == source_edge_id
                    and item["edge_type"] in {"repeat", "recovery"}
                ),
                None,
            )
            if edge is None or edge["source_node_id"] != node_id:
                raise GraphRuntimeError(
                    "E_V265_RUNTIME_ATTEMPT_BUDGET", "retry Edge differs"
                )
            next_attempt = (
                projection["nodes"][edge["target_node_id"]]["attempt"] + 1
            )
        event = self._event(
            run_id=run_id,
            event_type="node.retry_scheduled",
            node_id=node_id,
            attempt=state["attempt"],
            payload={
                "source_edge_id": source_edge_id,
                "traversal_count": traversal_count,
                "next_attempt": next_attempt,
            },
            evidence_refs=["evidence:retry-policy"],
            actor_identity="runtime_controller",
            occurred_at=now,
            expected_revision=expected_revision,
        )
        store_receipt = self.store.append_event(
            run_id, event, expected_revision=expected_revision
        )
        return self._mutation(
            operation="node.retry_scheduled",
            run_id=run_id,
            node_id=node_id,
            event=event,
            store_receipt=store_receipt,
        )

    def run_ready_wave(
        self,
        *,
        run_id: str,
        dispatch_inputs: Mapping[str, Mapping[str, Any]],
        now: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        now = _utc(now)
        self._head(run_id, expected_revision)
        descriptors = self.evaluate_next(run_id=run_id, now=now)
        ready_ids = [item["node_id"] for item in descriptors]
        started: list[str] = []
        completed: list[str] = []
        failed: list[str] = []
        blocked: list[str] = []
        revision = expected_revision
        halt_wave = False

        for offset in range(0, len(descriptors), self.max_workers):
            batch = descriptors[offset : offset + self.max_workers]
            batch_ids: list[str] = []
            for descriptor in batch:
                node_id = descriptor["node_id"]
                values = dispatch_inputs.get(node_id)
                if not isinstance(values, Mapping):
                    raise GraphRuntimeError(
                        "E_V265_RUNTIME_EVENT", "dispatch input is absent"
                    )
                revision = self._ensure_ready_event(
                    run_id=run_id,
                    node_id=node_id,
                    now=now,
                    expected_revision=revision,
                )
                claim = self.claim_node(
                    run_id=run_id,
                    node_id=node_id,
                    worker_id=values["worker_id"],
                    lease_seconds=values["lease_seconds"],
                    now=now,
                    expected_revision=revision,
                )
                revision = claim["revision"]
                start = self.start_node(
                    run_id=run_id,
                    node_id=node_id,
                    lease_id=claim["event"]["payload"]["lease_id"],
                    owner_run_id=values["owner_run_id"],
                    validator_run_id=values["validator_run_id"],
                    context_bundle=values["context_bundle"],
                    context_validation_receipt=values[
                        "context_validation_receipt"
                    ],
                    capability_receipt=values["capability_receipt"],
                    idempotency_key=values["idempotency_key"],
                    now=now,
                    expected_revision=revision,
                )
                revision = start["revision"]
                started.append(node_id)
                batch_ids.append(node_id)

            for node_id in batch_ids:
                current_state = self._projection(run_id)["nodes"][node_id]
                key = (run_id, node_id, int(current_state["attempt"]))
                handle = self._live_handles[key]
                dispatch = self._live_dispatches[key]
                node = next(
                    item
                    for item in self.compiled_graph["nodes"]
                    if item["node_id"] == node_id
                )
                action = next(
                    item
                    for item in self.compiled_graph["actions"]
                    if item["action_id"] == dispatch["action_ref"]
                )
                try:
                    outcome = self.host_adapter.wait(
                        handle, timeout_seconds=node["timeout_seconds"]
                    )
                except HostAdapterError as exc:
                    if action["effect"] == "external_write" and exc.code != "E_V265_HOST_TIMEOUT":
                        reconciliation = self._append_controller_event(
                            run_id=run_id,
                            node_id=node_id,
                            event_type="side_effect.reconciliation_required",
                            attempt=int(dispatch["attempt"]),
                            payload={
                                "idempotency_key": dispatch["idempotency_key"],
                                "reason_code": "external_wait_unconfirmed",
                            },
                            evidence_refs=["evidence:external-wait-error"],
                            now=now,
                            expected_revision=revision,
                        )
                        revision = reconciliation["revision"]
                        failed.append(node_id)
                        halt_wave = True
                        continue
                    if exc.code != "E_V265_HOST_TIMEOUT":
                        raise
                    quiescent, revision, blocked_receipt, assurance, linked = self._quiescence_before_control(
                        run_id=run_id,
                        node_id=node_id,
                        now=now,
                        expected_revision=revision,
                        evidence_refs=["evidence:host-timeout"],
                        allow_legacy_interrupt=False,
                    )
                    if quiescent:
                        state = self._projection(run_id)["nodes"][node_id]
                        cancel_event = self._event(
                            run_id=run_id,
                            event_type="node.cancelled",
                            node_id=node_id,
                            attempt=state["attempt"],
                            payload={"reason": "host_timeout"},
                            evidence_refs=linked,
                            actor_identity="runtime_controller",
                            occurred_at=now,
                            expected_revision=revision,
                        )
                        store_receipt = self.store.append_event(
                            run_id, cancel_event, expected_revision=revision
                        )
                        cancelled = self._mutation(
                            operation="node.cancelled",
                            run_id=run_id,
                            node_id=node_id,
                            event=cancel_event,
                            store_receipt=store_receipt,
                        )
                        revision = cancelled["revision"]
                    else:
                        assert blocked_receipt is not None
                        revision = blocked_receipt["revision"]
                    blocked.append(node_id)
                    halt_wave = True
                    continue

                if action["effect"] == "external_write":
                    try:
                        readback = self.host_adapter.readback(
                            handle,
                            dispatch,
                            outcome,
                            observed_at=outcome["finished_at"],
                        )
                    except HostAdapterError:
                        reconciliation = self._append_controller_event(
                            run_id=run_id,
                            node_id=node_id,
                            event_type="side_effect.reconciliation_required",
                            attempt=int(dispatch["attempt"]),
                            payload={
                                "idempotency_key": dispatch["idempotency_key"],
                                "reason_code": "external_readback_error",
                            },
                            evidence_refs=["evidence:external-readback-error"],
                            now=outcome["finished_at"],
                            expected_revision=revision,
                        )
                        revision = reconciliation["revision"]
                        failed.append(node_id)
                        halt_wave = True
                        continue
                    observed = self._record_host_observation(
                        run_id=run_id,
                        node_id=node_id,
                        attempt=int(dispatch["attempt"]),
                        observation_type="readback",
                        host_handle_id=str(handle["host_handle_id"]),
                        observation_receipt=readback,
                        now=outcome["finished_at"],
                        expected_revision=revision,
                    )
                    revision = observed["revision"]
                    if readback["observed_state"] == "confirmed":
                        confirmation = self._append_controller_event(
                            run_id=run_id,
                            node_id=node_id,
                            event_type="side_effect.confirmed",
                            attempt=int(dispatch["attempt"]),
                            payload={
                                "idempotency_key": dispatch["idempotency_key"],
                                "result_digest": readback["result_digest"],
                                "readback_receipt_sha256": readback["receipt_sha256"],
                            },
                            evidence_refs=["evidence:external-readback"],
                            now=outcome["finished_at"],
                            expected_revision=revision,
                        )
                        revision = confirmation["revision"]
                    else:
                        reconciliation = self._append_controller_event(
                            run_id=run_id,
                            node_id=node_id,
                            event_type="side_effect.reconciliation_required",
                            attempt=int(dispatch["attempt"]),
                            payload={
                                "idempotency_key": dispatch["idempotency_key"],
                                "reason_code": "external_readback_unconfirmed",
                            },
                            evidence_refs=["evidence:external-readback"],
                            now=outcome["finished_at"],
                            expected_revision=revision,
                        )
                        revision = reconciliation["revision"]
                        failed.append(node_id)
                        halt_wave = True
                        continue

                state = self._projection(run_id)["nodes"][node_id]
                if outcome["outcome"] == "completed":
                    receipt = self.complete_node(
                        run_id=run_id,
                        node_id=node_id,
                        lease_id=state["lease_id"],
                        artifact_receipts=outcome["artifact_receipts"],
                        evidence_refs=outcome["evidence_refs"],
                        now=outcome["finished_at"],
                        expected_revision=revision,
                    )
                    completed.append(node_id)
                elif outcome["outcome"] == "blocked":
                    receipt = self.block_node(
                        run_id=run_id,
                        node_id=node_id,
                        blocker_id="host-blocked",
                        evidence_refs=outcome["evidence_refs"],
                        now=outcome["finished_at"],
                        expected_revision=revision,
                    )
                    blocked.append(node_id)
                else:
                    receipt = self.fail_node(
                        run_id=run_id,
                        node_id=node_id,
                        lease_id=state["lease_id"],
                        outcome=outcome["outcome"],
                        failure_artifacts=outcome["artifact_receipts"],
                        evidence_refs=outcome["evidence_refs"],
                        now=outcome["finished_at"],
                        expected_revision=revision,
                    )
                    failed.append(node_id)
                revision = receipt["revision"]

            if halt_wave:
                break

        projection = self._projection(run_id)
        result: dict[str, Any] = {
            "schema_version": "goal-teams-runtime-wave-receipt-v2.65",
            "run_id": run_id,
            "ready_node_ids": ready_ids,
            "started_node_ids": started,
            "completed_node_ids": completed,
            "failed_node_ids": failed,
            "blocked_node_ids": blocked,
            "max_workers": self.max_workers,
            "revision_before": expected_revision,
            "revision_after": projection["revision"],
            "projection_sha256": projection["projection_sha256"],
        }
        result["receipt_sha256"] = canonical_sha256(result)
        return result


__all__ = ["RuntimeController"]
