"""Compile a deterministic V2.63 PromptArtifact from exact repository bytes."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.v250.generation_runtime import (
    GenerationRuntimeSession,
    GenerationSnapshot,
    GenerationLoadError,
    canonical_json_digest,
    resolve_repo_file,
    sha256_bytes,
    validate_generation_runtime_session,
)
from scripts.v250.route_derivation import RouteDerivationError, derive_route


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROMPT_HEADER = b"GOAL-TEAMS-PROMPT-ARTIFACT-V1\n"
ROUTE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "derivation_version",
        "facts",
        "facts_sha256",
        "facts_source_sha256",
        "project_size",
        "workflow_phase",
        "stage",
        "route_id",
        "assurance_floor",
        "effective_assurance",
        "required_gates",
        "conditional_gates",
        "exclusion_reasons",
        "receipt_sha256",
    }
)


class PromptCompilerError(ValueError):
    """Stable fail-closed prompt compiler error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise PromptCompilerError(code, message)


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail("E_V263_PROMPT_DIGEST", f"{field} must be lowercase SHA-256")
    return value


def _refs(
    value: Sequence[str], field: str, *, allow_empty: bool = False
) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail("E_V263_PROMPT_REFS", f"{field} must be an array")
    result = list(value)
    if (not result and not allow_empty) or not all(
        isinstance(item, str) and item for item in result
    ):
        _fail("E_V263_PROMPT_REFS", f"{field} must contain non-empty paths")
    return result


def _frame(kind: str, label: str, raw: bytes) -> bytes:
    header = (
        f"<<<GT-FRAME {kind} {label} {len(raw)} {sha256_bytes(raw)}>>>\n"
    ).encode("utf-8")
    return header + raw + b"\n<<<GT-END>>>\n"


def _read_prompt_file(root: Path | str, relative_path: str) -> bytes:
    try:
        raw = resolve_repo_file(root, relative_path).read_bytes()
    except GenerationLoadError as exc:
        raise PromptCompilerError("E_V263_PROMPT_PATH", exc.message) from exc
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptCompilerError(
            "E_V263_PROMPT_ENCODING", f"prompt input is not UTF-8: {relative_path}"
        ) from exc
    return raw


def validate_generation_snapshot(snapshot: GenerationSnapshot) -> GenerationSnapshot:
    """Validate a loader-produced immutable generation snapshot."""

    if not isinstance(snapshot, GenerationSnapshot):
        _fail(
            "E_V263_PROMPT_GENERATION_SNAPSHOT",
            "generation_snapshot must be a GenerationSnapshot",
        )
    payload = {
        "session_id": snapshot.session_id,
        "selected_root_realpath": snapshot.selected_root_realpath,
        "source_commit": snapshot.source_commit,
        "source_tree": snapshot.source_tree,
        "active_sha256": snapshot.active_sha256,
        "activation_manifest_sha256": snapshot.activation_manifest_sha256,
        "rule_manifest_sha256": snapshot.rule_manifest_sha256,
        "prompt_manifest_sha256": snapshot.prompt_manifest_sha256,
        "generation_id": snapshot.generation_id,
        "member_digests": snapshot.member_digests,
        "captured_at": snapshot.captured_at,
    }
    if snapshot.snapshot_sha256 != canonical_json_digest(payload):
        _fail(
            "E_V263_PROMPT_GENERATION_SNAPSHOT",
            "generation snapshot digest differs",
        )
    for field in (
        "active_sha256",
        "activation_manifest_sha256",
        "rule_manifest_sha256",
        "prompt_manifest_sha256",
        "snapshot_sha256",
    ):
        _digest(getattr(snapshot, field), f"generation_snapshot.{field}")
    if snapshot.generation_id not in {"V2.63", "V2.65"}:
        _fail(
            "E_V263_PROMPT_GENERATION_SNAPSHOT",
            "trusted runtime prompt requires a supported Current generation",
        )
    if not Path(snapshot.selected_root_realpath).is_absolute():
        _fail(
            "E_V263_PROMPT_GENERATION_SNAPSHOT",
            "selected_root_realpath must be absolute",
        )
    seen: set[str] = set()
    for item in snapshot.member_digests:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or item[0] in seen
        ):
            _fail(
                "E_V263_PROMPT_GENERATION_SNAPSHOT",
                "member digest bindings are invalid",
            )
        _digest(item[1], f"generation_snapshot.member_digests[{item[0]}]")
        seen.add(item[0])
    return snapshot


def validate_derived_route_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact canonical receipt produced by route derivation."""

    if (
        not isinstance(receipt, Mapping)
        or set(receipt) != ROUTE_RECEIPT_FIELDS
        or receipt.get("derivation_version") not in {"V2.63", "V2.65"}
        or receipt.get("schema_version")
        != f"goal-teams-derived-route-receipt-{str(receipt.get('derivation_version')).lower()}"
    ):
        _fail("E_V263_PROMPT_ROUTE_RECEIPT", "invalid derived route receipt")
    value = dict(receipt)
    claimed = _digest(value.pop("receipt_sha256", None), "route.receipt_sha256")
    if claimed != canonical_json_digest(value):
        _fail("E_V263_PROMPT_ROUTE_RECEIPT", "derived route digest differs")
    _digest(receipt.get("facts_sha256"), "route.facts_sha256")
    _digest(receipt.get("facts_source_sha256"), "route.facts_source_sha256")
    if not isinstance(receipt.get("route_id"), str) or not receipt["route_id"]:
        _fail("E_V263_PROMPT_ROUTE_RECEIPT", "route_id is required")
    for field in ("required_gates", "conditional_gates", "exclusion_reasons"):
        value = receipt.get(field)
        if (
            not isinstance(value, list)
            or not all(isinstance(item, str) and item for item in value)
            or len(value) != len(set(value))
        ):
            _fail("E_V263_PROMPT_ROUTE_RECEIPT", f"invalid {field}")
    facts = receipt.get("facts")
    try:
        replayed = derive_route(
            facts,
            requested_assurance=receipt.get("effective_assurance"),
            generation_id=str(receipt.get("derivation_version")),
        )
    except RouteDerivationError as exc:
        raise PromptCompilerError("E_V263_PROMPT_ROUTE_REPLAY", exc.message) from exc
    if replayed != dict(receipt):
        _fail(
            "E_V263_PROMPT_ROUTE_REPLAY",
            "derived route differs from exact replay of embedded facts",
        )
    return dict(receipt)


def _prompt_plan(
    *,
    compiler_mode: str,
    prompt_manifest_sha256: str | None,
    route_id: str | None,
    generation_snapshot_sha256: str,
    derived_route_sha256: str,
    bootstrap_refs: list[str],
    ordered_refs: list[str],
    path_entries: list[dict[str, Any]],
    member_packet_sha256: str,
    member_packet_bytes: int,
) -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-prompt-plan-v2.65",
        "framing": "GOAL-TEAMS-PROMPT-ARTIFACT-V1",
        "compiler_mode": compiler_mode,
        "prompt_manifest_sha256": prompt_manifest_sha256,
        "route_id": route_id,
        "generation_snapshot_sha256": generation_snapshot_sha256,
        "derived_route_sha256": derived_route_sha256,
        "bootstrap_refs": bootstrap_refs,
        "ordered_refs": ordered_refs,
        "path_entries": path_entries,
        "member_packet_sha256": member_packet_sha256,
        "member_packet_bytes": member_packet_bytes,
    }


def build_prompt_plan_from_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical plan payload that every validator must recompute."""

    return _prompt_plan(
        compiler_mode=artifact.get("compiler_mode"),
        prompt_manifest_sha256=artifact.get("prompt_manifest_sha256"),
        route_id=artifact.get("route_id"),
        generation_snapshot_sha256=artifact.get("generation_snapshot_sha256"),
        derived_route_sha256=artifact.get("derived_route_sha256"),
        bootstrap_refs=artifact.get("bootstrap_refs"),
        ordered_refs=artifact.get("ordered_refs"),
        path_entries=artifact.get("path_entries"),
        member_packet_sha256=artifact.get("member_packet_sha256"),
        member_packet_bytes=artifact.get("member_packet_bytes"),
    )


def _compile(
    repo_root: Path | str,
    *,
    bootstrap_refs: Sequence[str],
    ordered_refs: Sequence[str],
    member_packet: str | bytes,
    generation_snapshot_sha256: str,
    derived_route_sha256: str,
    compiler_mode: str,
    prompt_manifest_sha256: str | None,
    route_id: str | None,
    expected_path_digests: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    generation_digest = _digest(
        generation_snapshot_sha256, "generation_snapshot_sha256"
    )
    route_digest = _digest(derived_route_sha256, "derived_route_sha256")
    bootstrap = _refs(
        bootstrap_refs,
        "bootstrap_refs",
        allow_empty=compiler_mode == "trusted_runtime",
    )
    owners = _refs(ordered_refs, "ordered_refs")
    all_refs = bootstrap + owners
    duplicates = sorted({path for path in all_refs if all_refs.count(path) > 1})
    if duplicates:
        _fail(
            "E_V263_PROMPT_DUPLICATE_REF",
            "duplicate refs are forbidden: " + ", ".join(duplicates),
        )

    if isinstance(member_packet, str):
        member_raw = member_packet.encode("utf-8")
    elif isinstance(member_packet, bytes):
        member_raw = member_packet
        try:
            member_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PromptCompilerError(
                "E_V263_PROMPT_ENCODING", "member_packet is not UTF-8"
            ) from exc
    else:
        _fail("E_V263_PROMPT_MEMBER", "member_packet must be text or bytes")
    if not member_raw:
        _fail("E_V263_PROMPT_MEMBER", "member_packet must not be empty")

    compiled = bytearray(PROMPT_HEADER)
    path_entries: list[dict[str, Any]] = []
    for kind, paths in (("bootstrap", bootstrap), ("owner", owners)):
        for relative_path in paths:
            raw = _read_prompt_file(repo_root, relative_path)
            digest = sha256_bytes(raw)
            if (
                expected_path_digests is not None
                and expected_path_digests.get(relative_path) != digest
            ):
                _fail(
                    "E_V263_PROMPT_SNAPSHOT_MEMBER",
                    f"path is absent from or differs from generation snapshot: {relative_path}",
                )
            entry = {
                "kind": kind,
                "path": relative_path,
                "sha256": digest,
                "bytes": len(raw),
            }
            path_entries.append(entry)
            compiled.extend(_frame(kind, relative_path, raw))
    compiled.extend(_frame("member", "@member_packet", member_raw))
    compiled_bytes = bytes(compiled)
    member_digest = sha256_bytes(member_raw)

    plan = _prompt_plan(
        compiler_mode=compiler_mode,
        prompt_manifest_sha256=prompt_manifest_sha256,
        route_id=route_id,
        generation_snapshot_sha256=generation_digest,
        derived_route_sha256=route_digest,
        bootstrap_refs=bootstrap,
        ordered_refs=owners,
        path_entries=path_entries,
        member_packet_sha256=member_digest,
        member_packet_bytes=len(member_raw),
    )
    artifact: dict[str, Any] = {
        "schema_version": "goal-teams-prompt-artifact-v2.65",
        "framing": plan["framing"],
        "compiler_mode": compiler_mode,
        "prompt_manifest_sha256": prompt_manifest_sha256,
        "route_id": route_id,
        "generation_snapshot_sha256": generation_digest,
        "derived_route_sha256": route_digest,
        "bootstrap_refs": bootstrap,
        "ordered_refs": owners,
        "path_entries": path_entries,
        "member_packet_sha256": member_digest,
        "member_packet_bytes": len(member_raw),
        "prompt_plan_sha256": canonical_json_digest(plan),
        "compiled_prompt_sha256": sha256_bytes(compiled_bytes),
        "compiled_prompt_bytes": len(compiled_bytes),
        "compiled_prompt_base64": base64.b64encode(compiled_bytes).decode("ascii"),
        "proof_strength": "repository_compiled",
    }
    artifact["receipt_sha256"] = canonical_json_digest(artifact)
    return artifact


def compile_prompt_artifact(
    repo_root: Path | str,
    *,
    bootstrap_refs: Sequence[str],
    ordered_refs: Sequence[str],
    member_packet: str | bytes,
    generation_snapshot_sha256: str,
    derived_route_sha256: str,
) -> dict[str, Any]:
    """Compile an explicit offline/test artifact.

    This compatibility surface intentionally yields ``offline_fixture`` and is
    rejected by :func:`runtime_session.start_runtime_session`.  Runtime callers
    must use :func:`compile_runtime_prompt_artifact`.
    """

    return _compile(
        repo_root,
        bootstrap_refs=bootstrap_refs,
        ordered_refs=ordered_refs,
        member_packet=member_packet,
        generation_snapshot_sha256=generation_snapshot_sha256,
        derived_route_sha256=derived_route_sha256,
        compiler_mode="offline_fixture",
        prompt_manifest_sha256=None,
        route_id=None,
    )


def compile_runtime_prompt_artifact(
    repo_root: Path | str,
    *,
    generation_runtime_session: GenerationRuntimeSession | None = None,
    generation_snapshot: GenerationSnapshot | None = None,
    derived_route_receipt: Mapping[str, Any],
    prompt_manifest_bytes: bytes,
    member_packet: str | bytes,
) -> dict[str, Any]:
    """Compile the sole trusted plan from loader, route, manifest, and member bytes."""

    if generation_runtime_session is None or generation_snapshot is not None:
        _fail(
            "E_V263_PROMPT_LOADER_SESSION_REQUIRED",
            "trusted runtime requires a loader-issued generation session",
        )
    try:
        snapshot = validate_generation_runtime_session(generation_runtime_session)
    except GenerationLoadError as exc:
        raise PromptCompilerError(
            "E_V263_PROMPT_LOADER_SESSION_REQUIRED", exc.message
        ) from exc
    snapshot = validate_generation_snapshot(snapshot)
    if Path(repo_root).resolve().as_posix() != snapshot.selected_root_realpath:
        _fail(
            "E_V263_PROMPT_GENERATION_ROOT",
            "repository root differs from generation snapshot",
        )
    route = validate_derived_route_receipt(derived_route_receipt)
    if not isinstance(prompt_manifest_bytes, bytes):
        _fail("E_V263_PROMPT_MANIFEST", "prompt_manifest_bytes must be bytes")
    manifest_digest = sha256_bytes(prompt_manifest_bytes)
    if manifest_digest != snapshot.prompt_manifest_sha256:
        _fail("E_V263_PROMPT_MANIFEST", "prompt manifest digest differs")
    try:
        manifest = json.loads(prompt_manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptCompilerError(
            "E_V263_PROMPT_MANIFEST", "prompt manifest is invalid JSON"
        ) from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "goal-teams-prompt-manifest-v2.50"
        or manifest.get("generation_id") != snapshot.generation_id
        or manifest.get("manifest_state") != "active_current"
    ):
        _fail("E_V263_PROMPT_MANIFEST", "prompt manifest identity differs")
    routes = manifest.get("routes")
    route_id = route["route_id"]
    route_plan = routes.get(route_id) if isinstance(routes, dict) else None
    if not isinstance(route_plan, dict):
        _fail("E_V263_PROMPT_ROUTE", "derived route is absent from prompt manifest")
    if route_plan.get("workflow_phase") != route.get("workflow_phase"):
        _fail("E_V263_PROMPT_ROUTE", "route workflow phase differs")
    ordered_refs = route_plan.get("ordered_refs")
    refs = _refs(ordered_refs, "prompt_manifest.routes.ordered_refs")
    snapshot_members = dict(snapshot.member_digests)
    generation = generation_runtime_session.generation
    activation = generation.get("activation_manifest")
    root_sets = activation.get("root_sets") if isinstance(activation, Mapping) else None
    bootstrap_entries = (
        root_sets.get("bootstrap") if isinstance(root_sets, Mapping) else None
    )
    if not isinstance(bootstrap_entries, (list, tuple)) or not bootstrap_entries:
        _fail(
            "E_V263_PROMPT_BOOTSTRAP",
            "trusted runtime requires activation-bound bootstrap refs",
        )
    bootstrap_refs: list[str] = []
    for entry in bootstrap_entries:
        if not isinstance(entry, Mapping) or set(entry) < {"path"}:
            _fail("E_V263_PROMPT_BOOTSTRAP", "invalid activation bootstrap entry")
        path = entry.get("path")
        if not isinstance(path, str) or not path or path in bootstrap_refs:
            _fail("E_V263_PROMPT_BOOTSTRAP", "invalid activation bootstrap path")
        bootstrap_refs.append(path)
    unmanaged = sorted(set(bootstrap_refs + refs) - set(snapshot_members))
    if unmanaged:
        _fail(
            "E_V263_PROMPT_SNAPSHOT_MEMBER",
            "prompt manifest references unbound generation members: "
            + ", ".join(unmanaged),
        )
    return _compile(
        repo_root,
        bootstrap_refs=bootstrap_refs,
        ordered_refs=refs,
        member_packet=member_packet,
        generation_snapshot_sha256=snapshot.snapshot_sha256,
        derived_route_sha256=route["receipt_sha256"],
        compiler_mode="trusted_runtime",
        prompt_manifest_sha256=manifest_digest,
        route_id=route_id,
        expected_path_digests=snapshot_members,
    )


__all__ = [
    "PROMPT_HEADER",
    "PromptCompilerError",
    "build_prompt_plan_from_artifact",
    "compile_prompt_artifact",
    "compile_runtime_prompt_artifact",
    "validate_derived_route_receipt",
    "validate_generation_snapshot",
]
