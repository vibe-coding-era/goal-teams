"""Repository-side V2.63 RuntimeSession and host-load contracts.

This module can correlate an observation with a compiled prompt plan.  It does
not execute a real host or Provider and therefore cannot produce independent or
Provider-verified evidence.
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import Any, Mapping

from scripts.v250.discovery_policy import (
    DiscoveryDecision,
    DiscoveryPolicyError,
    validate_discovery_decision,
)
from scripts.v250.generation_runtime import (
    GenerationLoadError,
    GenerationRuntimeSession,
    GenerationSnapshot,
    canonical_json_digest,
    sha256_bytes,
    validate_generation_runtime_session,
)
from scripts.v250.prompt_compiler import (
    PROMPT_HEADER,
    build_prompt_plan_from_artifact,
    validate_derived_route_receipt,
    validate_generation_snapshot,
)


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FRAME_HEADER_RE = re.compile(
    rb"^<<<GT-FRAME (bootstrap|owner|member) ([^ \r\n]+) ([0-9]+) ([0-9a-f]{64})>>>$"
)
PROMPT_ARTIFACT_FIELDS = frozenset(
    {
        "schema_version",
        "framing",
        "compiler_mode",
        "prompt_manifest_sha256",
        "route_id",
        "generation_snapshot_sha256",
        "derived_route_sha256",
        "bootstrap_refs",
        "ordered_refs",
        "path_entries",
        "member_packet_sha256",
        "member_packet_bytes",
        "prompt_plan_sha256",
        "compiled_prompt_sha256",
        "compiled_prompt_bytes",
        "compiled_prompt_base64",
        "proof_strength",
        "receipt_sha256",
    }
)
HOST_LOAD_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "host_execution_id",
        "selected_root_realpath",
        "opened_files",
        "observation_source",
        "actor_relationship",
        "external_independent",
        "cryptographic_host_attestation",
        "provider_prompt_assembly",
    }
)
_TRUSTED_RUNTIME_ENTRY_ISSUER = object()


class RuntimeSessionError(ValueError):
    """Stable fail-closed runtime-session contract error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise RuntimeSessionError(code, message)


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail("E_V263_RUNTIME_DIGEST", f"{field} must be lowercase SHA-256")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("E_V263_RUNTIME_FIELD", f"{field} must be non-empty text")
    return value


def _parse_compiled_frames(raw: bytes) -> list[dict[str, Any]]:
    if not raw.startswith(PROMPT_HEADER):
        _fail("E_V263_PROMPT_FRAME", "compiled prompt header differs")
    cursor = len(PROMPT_HEADER)
    frames: list[dict[str, Any]] = []
    end_marker = b"\n<<<GT-END>>>\n"
    while cursor < len(raw):
        header_end = raw.find(b"\n", cursor)
        if header_end < 0:
            _fail("E_V263_PROMPT_FRAME", "prompt frame header is unterminated")
        header = raw[cursor:header_end]
        match = FRAME_HEADER_RE.fullmatch(header)
        if match is None:
            _fail("E_V263_PROMPT_FRAME", "prompt frame header is invalid")
        kind = match.group(1).decode("ascii")
        label = match.group(2).decode("utf-8")
        byte_count = int(match.group(3))
        digest = match.group(4).decode("ascii")
        payload_start = header_end + 1
        payload_end = payload_start + byte_count
        if payload_end > len(raw) or raw[payload_end : payload_end + len(end_marker)] != end_marker:
            _fail("E_V263_PROMPT_FRAME", "prompt frame length or terminator differs")
        payload = raw[payload_start:payload_end]
        if sha256_bytes(payload) != digest:
            _fail("E_V263_PROMPT_FRAME", "prompt frame payload digest differs")
        frames.append(
            {
                "kind": kind,
                "label": label,
                "bytes": byte_count,
                "sha256": digest,
                "payload": payload,
            }
        )
        cursor = payload_end + len(end_marker)
    if not frames:
        _fail("E_V263_PROMPT_FRAME", "compiled prompt has no frames")
    return frames


def _validate_prompt_artifact(
    artifact: Mapping[str, Any], *, require_trusted_runtime: bool = False
) -> list[dict[str, Any]]:
    if not isinstance(artifact, Mapping) or artifact.get("schema_version") != (
        "goal-teams-prompt-artifact-v2.65"
    ):
        _fail("E_V263_PROMPT_ARTIFACT", "invalid prompt artifact")
    if set(artifact) != PROMPT_ARTIFACT_FIELDS:
        _fail(
            "E_V263_PROMPT_ARTIFACT",
            "prompt artifact has missing or unknown fields",
        )
    artifact_payload = {
        key: value for key, value in artifact.items() if key != "receipt_sha256"
    }
    if artifact.get("receipt_sha256") != canonical_json_digest(artifact_payload):
        _fail("E_V263_PROMPT_ARTIFACT", "prompt artifact receipt digest differs")
    if artifact.get("proof_strength") != "repository_compiled":
        _fail("E_V263_PROMPT_ARTIFACT", "prompt artifact proof strength differs")
    compiler_mode = artifact.get("compiler_mode")
    if compiler_mode not in {"offline_fixture", "trusted_runtime"}:
        _fail("E_V263_PROMPT_ARTIFACT", "prompt compiler mode differs")
    if require_trusted_runtime and compiler_mode != "trusted_runtime":
        _fail(
            "E_V263_RUNTIME_TRUSTED_PROMPT_REQUIRED",
            "runtime entry requires a manifest-derived trusted prompt plan",
        )
    if compiler_mode == "trusted_runtime":
        _sha(artifact.get("prompt_manifest_sha256"), "prompt_manifest_sha256")
        _nonempty(artifact.get("route_id"), "route_id")
    elif artifact.get("prompt_manifest_sha256") is not None or artifact.get("route_id") is not None:
        _fail(
            "E_V263_PROMPT_ARTIFACT",
            "offline artifact cannot claim prompt-manifest or route derivation",
        )
    _sha(artifact.get("generation_snapshot_sha256"), "generation_snapshot_sha256")
    _sha(artifact.get("derived_route_sha256"), "derived_route_sha256")
    encoded = artifact.get("compiled_prompt_base64")
    if not isinstance(encoded, str):
        _fail("E_V263_PROMPT_ARTIFACT", "compiled_prompt_base64 is required")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeSessionError(
            "E_V263_PROMPT_ARTIFACT", "compiled prompt base64 is invalid"
        ) from exc
    if artifact.get("compiled_prompt_bytes") != len(raw):
        _fail("E_V263_PROMPT_ARTIFACT", "compiled prompt byte count differs")
    if artifact.get("compiled_prompt_sha256") != sha256_bytes(raw):
        _fail("E_V263_PROMPT_ARTIFACT", "compiled prompt digest differs")
    entries = artifact.get("path_entries")
    if not isinstance(entries, list) or not entries:
        _fail("E_V263_PROMPT_ARTIFACT", "path_entries must be a non-empty array")
    paths: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            _fail("E_V263_PROMPT_ARTIFACT", "invalid path entry")
        kind = entry.get("kind")
        path = entry.get("path")
        digest = entry.get("sha256")
        byte_count = entry.get("bytes")
        if kind not in {"bootstrap", "owner"}:
            _fail("E_V263_PROMPT_ARTIFACT", "invalid path entry kind")
        if not isinstance(path, str) or not path or path in paths:
            _fail("E_V263_PROMPT_ARTIFACT", "duplicate or invalid path entry")
        _sha(digest, f"path_entries[{path}].sha256")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            _fail("E_V263_PROMPT_ARTIFACT", "invalid path entry byte count")
        paths.add(path)
        normalized.append(
            {"kind": kind, "path": path, "sha256": digest, "bytes": byte_count}
        )
    bootstrap_refs = artifact.get("bootstrap_refs")
    ordered_refs = artifact.get("ordered_refs")
    if not isinstance(bootstrap_refs, list) or not isinstance(ordered_refs, list):
        _fail("E_V263_PROMPT_ARTIFACT", "prompt refs must be arrays")
    if compiler_mode == "offline_fixture" and not bootstrap_refs:
        _fail("E_V263_PROMPT_ARTIFACT", "offline bootstrap refs are required")
    if not ordered_refs:
        _fail("E_V263_PROMPT_ARTIFACT", "ordered refs are required")
    all_refs = bootstrap_refs + ordered_refs
    if (
        not all(isinstance(item, str) and item for item in all_refs)
        or len(all_refs) != len(set(all_refs))
        or all_refs != [entry["path"] for entry in normalized]
        or [entry["kind"] for entry in normalized]
        != ["bootstrap"] * len(bootstrap_refs) + ["owner"] * len(ordered_refs)
    ):
        _fail("E_V263_PROMPT_ARTIFACT", "prompt refs and path entries differ")

    frames = _parse_compiled_frames(raw)
    if len(frames) != len(normalized) + 1:
        _fail("E_V263_PROMPT_FRAME", "compiled frame count differs")
    for frame, entry in zip(frames[:-1], normalized, strict=True):
        if (
            frame["kind"] != entry["kind"]
            or frame["label"] != entry["path"]
            or frame["sha256"] != entry["sha256"]
            or frame["bytes"] != entry["bytes"]
        ):
            _fail("E_V263_PROMPT_FRAME", "compiled path frame differs from plan")
    member = frames[-1]
    if (
        member["kind"] != "member"
        or member["label"] != "@member_packet"
        or member["sha256"] != artifact.get("member_packet_sha256")
        or member["bytes"] != artifact.get("member_packet_bytes")
    ):
        _fail("E_V263_PROMPT_MEMBER", "compiled member frame differs from plan")
    _sha(artifact.get("member_packet_sha256"), "member_packet_sha256")
    if (
        not isinstance(artifact.get("member_packet_bytes"), int)
        or isinstance(artifact.get("member_packet_bytes"), bool)
        or artifact["member_packet_bytes"] < 1
    ):
        _fail("E_V263_PROMPT_MEMBER", "member packet byte count is invalid")
    plan = build_prompt_plan_from_artifact(artifact)
    if artifact.get("prompt_plan_sha256") != canonical_json_digest(plan):
        _fail("E_V263_PROMPT_PLAN", "prompt plan digest differs")
    return normalized


def validate_prompt_artifact_integrity(
    artifact: Mapping[str, Any], *, require_trusted_runtime: bool = False
) -> dict[str, Any]:
    """Recompute receipt, plan, member, and every framed payload binding."""

    entries = _validate_prompt_artifact(
        artifact, require_trusted_runtime=require_trusted_runtime
    )
    return {
        "ok": True,
        "compiler_mode": artifact["compiler_mode"],
        "path_entries": entries,
        "prompt_plan_sha256": artifact["prompt_plan_sha256"],
        "member_packet_sha256": artifact["member_packet_sha256"],
        "compiled_prompt_sha256": artifact["compiled_prompt_sha256"],
    }


def validate_host_load_observation(
    prompt_artifact: Mapping[str, Any], observation: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate exact path order/digests while preserving bounded assurance."""

    expected = _validate_prompt_artifact(prompt_artifact)
    if not isinstance(observation, Mapping) or observation.get("schema_version") != (
        "goal-teams-host-load-observation-v2.65"
    ):
        _fail("E_V263_HOST_LOAD_OBSERVATION", "invalid host-load observation")
    if set(observation) != HOST_LOAD_OBSERVATION_FIELDS:
        _fail(
            "E_V263_HOST_LOAD_OBSERVATION",
            "host-load observation has missing or unknown fields",
        )
    _nonempty(observation.get("host_execution_id"), "host_execution_id")
    root = _nonempty(
        observation.get("selected_root_realpath"), "selected_root_realpath"
    )
    if not Path(root).is_absolute():
        _fail("E_V263_HOST_LOAD_ROOT", "selected_root_realpath must be absolute")
    _nonempty(observation.get("observation_source"), "observation_source")
    if observation.get("actor_relationship") != "correlated":
        _fail("E_V263_HOST_PROOF_FORBIDDEN", "repository contract is correlated")
    if observation.get("external_independent") is not False:
        _fail("E_V263_HOST_PROOF_FORBIDDEN", "external independence is not proven")
    if observation.get("cryptographic_host_attestation") is not False:
        _fail("E_V263_HOST_PROOF_FORBIDDEN", "host attestation is not proven")
    if observation.get("provider_prompt_assembly") != "unavailable":
        _fail(
            "E_V263_PROVIDER_PROOF_FORBIDDEN",
            "repository observation cannot verify Provider prompt assembly",
        )

    opened = observation.get("opened_files")
    if not isinstance(opened, list):
        _fail("E_V263_HOST_LOAD_OBSERVATION", "opened_files must be an array")
    expected_paths = [entry["path"] for entry in expected]
    observed_paths = [
        entry.get("path") if isinstance(entry, Mapping) else None for entry in opened
    ]
    if len(observed_paths) < len(expected_paths):
        _fail("E_V263_HOST_LOAD_MISSING", "host observation is missing planned files")
    if len(observed_paths) > len(expected_paths):
        _fail("E_V263_HOST_LOAD_EXTRA", "host observation contains unplanned files")
    if observed_paths != expected_paths:
        if set(observed_paths) == set(expected_paths):
            _fail("E_V263_HOST_LOAD_ORDER", "host file order differs from prompt plan")
        if set(expected_paths) - set(observed_paths):
            _fail("E_V263_HOST_LOAD_MISSING", "host observation is missing planned files")
        _fail("E_V263_HOST_LOAD_EXTRA", "host observation contains unplanned files")

    for planned, observed in zip(expected, opened, strict=True):
        if not isinstance(observed, Mapping):
            _fail("E_V263_HOST_LOAD_OBSERVATION", "invalid opened file entry")
        if observed.get("kind") != planned["kind"]:
            _fail("E_V263_HOST_LOAD_KIND", f"kind differs for {planned['path']}")
        if observed.get("sha256") != planned["sha256"]:
            _fail("E_V263_HOST_LOAD_DIGEST", f"digest differs for {planned['path']}")
        if observed.get("bytes") != planned["bytes"]:
            _fail("E_V263_HOST_LOAD_BYTES", f"byte count differs for {planned['path']}")

    return {
        "ok": True,
        "planned_observed_match": True,
        "opened_file_count": len(opened),
        "opened_paths": expected_paths,
        "host_load_observation_sha256": canonical_json_digest(dict(observation)),
        "proof_strength": "correlated",
        "provider_prompt_assembly": "unavailable",
    }


def compile_runtime_session_receipt(
    *,
    runtime_session_id: str,
    discovery_decision_sha256: str,
    generation_snapshot_sha256: str,
    derived_route_sha256: str,
    prompt_artifact: Mapping[str, Any],
    host_load_observation: Mapping[str, Any],
    host_execution_id: str,
    _trusted_entry_issuer: object | None = None,
) -> dict[str, Any]:
    """Compile correlated evidence for either trusted runtime or offline fixtures.

    ``offline_fixture`` artifacts remain accepted here only for compatibility
    with structural tests.  Their receipt is explicitly labelled and is never
    a trusted runtime entry.  Use :func:`start_runtime_session` for runtime.
    """

    session_id = _nonempty(runtime_session_id, "runtime_session_id")
    execution_id = _nonempty(host_execution_id, "host_execution_id")
    discovery_digest = _sha(
        discovery_decision_sha256, "discovery_decision_sha256"
    )
    generation_digest = _sha(
        generation_snapshot_sha256, "generation_snapshot_sha256"
    )
    route_digest = _sha(derived_route_sha256, "derived_route_sha256")
    _validate_prompt_artifact(prompt_artifact)
    if prompt_artifact.get("generation_snapshot_sha256") != generation_digest:
        _fail("E_V263_RUNTIME_BINDING", "generation snapshot binding differs")
    if prompt_artifact.get("derived_route_sha256") != route_digest:
        _fail("E_V263_RUNTIME_BINDING", "derived route binding differs")
    if host_load_observation.get("host_execution_id") != execution_id:
        _fail("E_V263_RUNTIME_BINDING", "host execution ID differs")
    validation = validate_host_load_observation(
        prompt_artifact, host_load_observation
    )
    compiler_mode = prompt_artifact["compiler_mode"]
    if (
        compiler_mode == "trusted_runtime"
        and _trusted_entry_issuer is not _TRUSTED_RUNTIME_ENTRY_ISSUER
    ):
        _fail(
            "E_V263_RUNTIME_PROVENANCE_REQUIRED",
            "trusted receipts can only be created by start_runtime_session",
        )
    trusted_runtime = compiler_mode == "trusted_runtime"

    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-runtime-session-receipt-v2.65",
        "runtime_session_id": session_id,
        "host_execution_id": execution_id,
        "discovery_decision_sha256": discovery_digest,
        "generation_snapshot_sha256": generation_digest,
        "derived_route_sha256": route_digest,
        "prompt_artifact_sha256": _sha(
            prompt_artifact.get("receipt_sha256"), "prompt_artifact.receipt_sha256"
        ),
        "prompt_plan_sha256": _sha(
            prompt_artifact.get("prompt_plan_sha256"), "prompt_plan_sha256"
        ),
        "compiled_prompt_sha256": _sha(
            prompt_artifact.get("compiled_prompt_sha256"), "compiled_prompt_sha256"
        ),
        "host_load_observation_sha256": validation[
            "host_load_observation_sha256"
        ],
        "selected_root_realpath": host_load_observation[
            "selected_root_realpath"
        ],
        "opened_paths": validation["opened_paths"],
        "planned_observed_match": True,
        "prompt_compiler_mode": compiler_mode,
        "trusted_runtime_entry": trusted_runtime,
        "delivery_state": {
            "repository": "repository_compiled",
            "host": "host_received",
            "provider": "unavailable",
        },
        "host_delivery_assurance": "correlated",
        "capability_state": "repository_only",
        "proof_strength": "correlated",
        "actor_relationship": "correlated",
        "host_runtime_verified": False,
        "external_independent": False,
        "cryptographic_host_attestation": False,
        "provider_prompt_assembly": "unavailable",
    }
    receipt["receipt_sha256"] = canonical_json_digest(receipt)
    return receipt


def start_runtime_session(
    *,
    runtime_session_id: str,
    discovery_decision: DiscoveryDecision | None = None,
    generation_runtime_session: GenerationRuntimeSession | None = None,
    discovery_decision_sha256: str | None = None,
    generation_snapshot: GenerationSnapshot | None = None,
    derived_route_receipt: Mapping[str, Any],
    prompt_artifact: Mapping[str, Any],
    host_load_observation: Mapping[str, Any],
    host_execution_id: str,
) -> dict[str, Any]:
    """Sole trusted runtime entry; all route and prompt inputs are revalidated."""

    try:
        if (
            discovery_decision is None
            or generation_runtime_session is None
            or discovery_decision_sha256 is not None
            or generation_snapshot is not None
        ):
            _fail(
                "E_V263_RUNTIME_PROVENANCE_REQUIRED",
                "trusted runtime requires loader and discovery capabilities",
            )
        decision = validate_discovery_decision(discovery_decision)
        snapshot = validate_generation_runtime_session(generation_runtime_session)
        snapshot = validate_generation_snapshot(snapshot)
        route = validate_derived_route_receipt(derived_route_receipt)
    except (ValueError, GenerationLoadError, DiscoveryPolicyError) as exc:
        code = getattr(exc, "code", "E_V263_RUNTIME_BINDING")
        raise RuntimeSessionError(code, str(exc)) from exc
    selected = decision.selected
    discovery_bindings = {
        "selected_root_realpath": selected.root_realpath,
        "generation_id": selected.generation_id,
        "source_commit": selected.source_commit,
        "source_tree": selected.source_tree,
        "active_sha256": selected.active_sha256,
        "activation_manifest_sha256": selected.activation_sha256,
        "prompt_manifest_sha256": selected.prompt_manifest_sha256,
    }
    snapshot_bindings = {
        "selected_root_realpath": snapshot.selected_root_realpath,
        "generation_id": snapshot.generation_id,
        "source_commit": snapshot.source_commit,
        "source_tree": snapshot.source_tree,
        "active_sha256": snapshot.active_sha256,
        "activation_manifest_sha256": snapshot.activation_manifest_sha256,
        "prompt_manifest_sha256": snapshot.prompt_manifest_sha256,
    }
    if discovery_bindings != snapshot_bindings:
        _fail(
            "E_V263_RUNTIME_DISCOVERY_BINDING",
            "discovery selection differs from loader generation snapshot",
        )
    if (
        host_load_observation.get("selected_root_realpath")
        != snapshot.selected_root_realpath
    ):
        _fail(
            "E_V263_RUNTIME_ROOT_BINDING",
            "host observation root differs from discovery and loader roots",
        )
    _validate_prompt_artifact(prompt_artifact, require_trusted_runtime=True)
    if prompt_artifact.get("generation_snapshot_sha256") != snapshot.snapshot_sha256:
        _fail("E_V263_RUNTIME_BINDING", "trusted generation snapshot binding differs")
    if prompt_artifact.get("derived_route_sha256") != route.get("receipt_sha256"):
        _fail("E_V263_RUNTIME_BINDING", "trusted derived route binding differs")
    if prompt_artifact.get("route_id") != route.get("route_id"):
        _fail("E_V263_RUNTIME_BINDING", "trusted route ID differs")
    if prompt_artifact.get("prompt_manifest_sha256") != snapshot.prompt_manifest_sha256:
        _fail("E_V263_RUNTIME_BINDING", "trusted prompt manifest binding differs")
    receipt = compile_runtime_session_receipt(
        runtime_session_id=runtime_session_id,
        discovery_decision_sha256=decision.decision_sha256,
        generation_snapshot_sha256=snapshot.snapshot_sha256,
        derived_route_sha256=route["receipt_sha256"],
        prompt_artifact=prompt_artifact,
        host_load_observation=host_load_observation,
        host_execution_id=host_execution_id,
        _trusted_entry_issuer=_TRUSTED_RUNTIME_ENTRY_ISSUER,
    )
    if receipt.get("trusted_runtime_entry") is not True:
        _fail(
            "E_V263_RUNTIME_TRUSTED_PROMPT_REQUIRED",
            "runtime session did not preserve trusted prompt provenance",
        )
    return receipt


__all__ = [
    "RuntimeSessionError",
    "compile_runtime_session_receipt",
    "start_runtime_session",
    "validate_host_load_observation",
    "validate_prompt_artifact_integrity",
]
