#!/usr/bin/env python3
"""Observe and validate V2.51 fresh-runtime transition receipts.

The observer must be launched as a fresh process for the exact candidate or
released identity.  It binds the approved Current prompt closure, trusted
route, project-start authorization, host adapter, and run lineage.  Its
assurance remains I1/correlated; it never claims external independence.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
PREVIOUS_CONTROLLER_PRODUCT_VERSION = "V2.50"
LOADED_RUNTIME_PRODUCT_VERSION = "V2.51"
REPOSITORY = "vibe-coding-era/goal-teams"
HANDOFF_SCHEMA_VERSION = "goal-teams-v2.51-controller-handoff-receipt-v1"
LAUNCH_SCHEMA_VERSION = "goal-teams-v2.51-runtime-launch-receipt-v1"
CHILD_ACK_SCHEMA_VERSION = "goal-teams-v2.51-runtime-child-ack-v1"
PINNED_GITHUB_ACCOUNT = "vibe-coding-era"
PINNED_GITHUB_KEY_ID = 152596014
PINNED_GITHUB_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIJ7qqfn52U2nhALTYS8ofXEwJwIq6GispivX9W/NG2Ot"
)
PINNED_GITHUB_FINGERPRINT = (
    "SHA256:fEM2bYLJFOSvNA78soiWLvrSUaWxANVr1HIVl6AAirE"
)
HANDOFF_SIGNATURE_NAMESPACE = "goal-teams-v2.51-controller-handoff"
ACTIVE_PATH = "references/current/ACTIVE.json"
POLICY_PROFILE_PATH = "references/profiles/goal-teams-self-release-v2.51.md"
RELEASE_PROFILE_PATH = "references/release-profiles/v2.51.json"
RELEASE_ROUTE_MANIFEST_PATH = (
    "references/current/generations/V2.51/contracts/release-route-manifest.json"
)
RELEASE_COMMAND_MANIFEST_PATH = (
    "references/current/generations/V2.51/contracts/release-command-manifest.json"
)
RUNTIME_TRANSITION_SCHEMA_PATH = (
    "schemas/v2.50/runtime-transition-receipt.schema.json"
)
REQUIRED_STATIC_INPUT_PATHS = (
    ".agents/skills/goal-teams/SKILL.md",
    "AGENTS.md",
    "RULES.md",
    "SKILL.md",
    POLICY_PROFILE_PATH,
    RELEASE_PROFILE_PATH,
    RELEASE_ROUTE_MANIFEST_PATH,
    RELEASE_COMMAND_MANIFEST_PATH,
    RUNTIME_TRANSITION_SCHEMA_PATH,
    "scripts/checks/check-v250.py",
    "scripts/v250/runtime_host_adapter.py",
    "scripts/v250/runtime_transition.py",
)
ROUTE_BY_STAGE_AND_SIZE = {
    ("candidate", "discussion"): "V250-ROUTE-DISCUSSION",
    ("candidate", "small"): "V250-ROUTE-SMALL-DEVELOPMENT",
    ("candidate", "medium"): "V250-ROUTE-MEDIUM-DEVELOPMENT",
    ("candidate", "large"): "V250-ROUTE-LARGE-DEVELOPMENT",
    # V2.51 has no separate Small Release prompt route.  Small Release uses
    # the stricter Medium Release prompt closure rather than inventing one.
    ("released", "small"): "V250-ROUTE-MEDIUM-RELEASE",
    ("released", "medium"): "V250-ROUTE-MEDIUM-RELEASE",
    ("released", "large"): "V250-ROUTE-LARGE-RELEASE",
}


def _canonical_sha256(
    value: Mapping[str, Any], *, digest_field: str = "receipt_sha256"
) -> str:
    payload = dict(value)
    payload.pop(digest_field, None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def object_sha256(value: Mapping[str, Any]) -> str:
    """Digest the complete object, including any nested receipt digest."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _repo_file(root: Path, relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise ValueError("E_V250_RUNTIME_TRANSITION_PATH")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("E_V250_RUNTIME_TRANSITION_PATH")
    candidate = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"E_V250_RUNTIME_TRANSITION_INPUT:{relative}")
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("E_V250_RUNTIME_TRANSITION_PATH") from exc
    if not candidate.is_file():
        raise ValueError(f"E_V250_RUNTIME_TRANSITION_INPUT:{relative}")
    return candidate


def _evidence_file(path: Path | str, root: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("E_V250_RUNTIME_TRANSITION_EVIDENCE_PATH")
    return candidate.resolve()


def _path_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_json_file(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("E_V250_RUNTIME_TRANSITION_JSON")
    return value, raw


def _read_repo_json(root: Path, relative: str) -> tuple[dict[str, Any], bytes]:
    return _read_json_file(_repo_file(root, relative))


def _runtime_transition_field_contract(root: Path) -> frozenset[str]:
    """Load the schema-owned exact top-level field set fail closed."""

    try:
        schema, _ = _read_repo_json(root, RUNTIME_TRANSITION_SCHEMA_PATH)
        properties = schema.get("properties")
        required = schema.get("required")
        if (
            schema.get("additionalProperties") is not False
            or not isinstance(properties, dict)
            or not isinstance(required, list)
            or any(not isinstance(field, str) for field in required)
            or set(required) != set(properties)
        ):
            raise ValueError("invalid schema field contract")
        return frozenset(properties)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("E_V250_RUNTIME_TRANSITION_SCHEMA_CONTRACT") from exc


def _activation_member_digests(activation: Mapping[str, Any]) -> dict[str, str]:
    root_sets = activation.get("root_sets")
    if not isinstance(root_sets, dict):
        raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVATION")
    result: dict[str, str] = {}
    for root_set in ("bootstrap", "current", "execution", "schemas_and_validators"):
        entries = root_sets.get(root_set)
        if not isinstance(entries, list):
            raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVATION")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVATION")
            path = entry.get("path")
            digest = entry.get("sha256")
            if (
                not isinstance(path, str)
                or not isinstance(digest, str)
                or SHA256_RE.fullmatch(digest) is None
                or (path in result and result[path] != digest)
            ):
                raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVATION")
            result[path] = digest
    return result


def _normalize_timestamp(value: str | None) -> str:
    if value is None:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if not isinstance(value, str) or not value:
        raise ValueError("E_V250_RUNTIME_TRANSITION_CAPTURED_AT")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("E_V250_RUNTIME_TRANSITION_CAPTURED_AT") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("E_V250_RUNTIME_TRANSITION_CAPTURED_AT")
    return value


def _validate_run_id(value: object) -> bool:
    return isinstance(value, str) and RUN_ID_RE.fullmatch(value) is not None


def _load_route_context(
    *,
    root: Path,
    stage: str,
    project_size: str,
    route_receipt_path: Path | str,
    loaded_runtime_product_version: str,
) -> dict[str, Any]:
    active, active_raw = _read_repo_json(root, ACTIVE_PATH)
    if (
        active.get("schema_version") != "goal-teams-active-generation-v1"
        or active.get("generation_id") != "V2.51"
        or active.get("state") != "active_current"
    ):
        raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVE")
    activation_path = active.get("activation_manifest")
    if not isinstance(activation_path, str):
        raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVE")
    activation, activation_raw = _read_repo_json(root, activation_path)
    activation_digest = _sha256(activation_raw)
    if active.get("activation_manifest_sha256") != activation_digest:
        raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVE_DIGEST")
    if (
        activation.get("schema_version")
        != "goal-teams-activation-manifest-v2.50"
        or activation.get("generation_id") != "V2.51"
        or activation.get("generation_state") != "active"
        or activation.get("manifest_payload_sha256")
        != _canonical_sha256(activation, digest_field="manifest_payload_sha256")
    ):
        raise ValueError("E_V250_RUNTIME_TRANSITION_ACTIVATION")
    identity = activation.get("identity")
    if (
        not isinstance(identity, dict)
        or identity.get("loaded_runtime_product_version")
        != loaded_runtime_product_version
        or identity.get("route_contract_schema_version")
        != "goal-teams-project-route-v2.50"
        or identity.get("target_policy_generation") != "V2.51"
        or "controller_product_version" in identity
    ):
        raise ValueError("E_V250_RUNTIME_TRANSITION_VERSION_AXIS")
    member_digests = _activation_member_digests(activation)

    prompt_manifest_path = activation.get("prompt_manifest_path")
    if not isinstance(prompt_manifest_path, str):
        raise ValueError("E_V250_RUNTIME_TRANSITION_PROMPT_MANIFEST")
    prompt_manifest, prompt_manifest_raw = _read_repo_json(root, prompt_manifest_path)
    if (
        prompt_manifest.get("schema_version")
        != "goal-teams-prompt-manifest-v2.50"
        or prompt_manifest.get("generation_id") != "V2.51"
        or prompt_manifest.get("manifest_state") != "active_current"
    ):
        raise ValueError("E_V250_RUNTIME_TRANSITION_PROMPT_MANIFEST")

    route_path = _evidence_file(route_receipt_path, root)
    route_receipt, route_raw = _read_json_file(route_path)
    expected_route_id = ROUTE_BY_STAGE_AND_SIZE.get((stage, project_size))
    if expected_route_id is None or route_receipt.get("route_id") != expected_route_id:
        raise ValueError("E_V250_RUNTIME_TRANSITION_ROUTE")
    routes = prompt_manifest.get("routes")
    route_plan = routes.get(expected_route_id) if isinstance(routes, dict) else None
    if not isinstance(route_plan, dict):
        raise ValueError("E_V250_RUNTIME_TRANSITION_ROUTE")
    expected_current_paths = route_plan.get("ordered_refs")
    route_loaded_paths = route_receipt.get("loaded_paths")
    route_digests = route_receipt.get("path_digests")
    if (
        route_receipt.get("generation_id") != "V2.51"
        or not isinstance(expected_current_paths, list)
        or not expected_current_paths
        or not all(isinstance(item, str) and item for item in expected_current_paths)
        or route_loaded_paths != expected_current_paths
        or not isinstance(route_digests, dict)
        or set(route_digests) != set(expected_current_paths)
        or route_receipt.get("legacy_intersection") != []
        or route_receipt.get("closure_digest")
        != _canonical_sha256(route_receipt, digest_field="closure_digest")
    ):
        raise ValueError("E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT")

    current_digests: dict[str, str] = {}
    for relative in expected_current_paths:
        path = _repo_file(root, relative)
        observed = _sha256(path.read_bytes())
        if (
            route_digests.get(relative) != observed
            or member_digests.get(relative) != observed
        ):
            raise ValueError("E_V250_RUNTIME_TRANSITION_CURRENT_DIGEST")
        current_digests[relative] = observed

    required_paths = set(REQUIRED_STATIC_INPUT_PATHS)
    required_paths.add(prompt_manifest_path)
    required_paths.update(expected_current_paths)
    input_digests: dict[str, str] = {
        ACTIVE_PATH: _sha256(active_raw),
        activation_path: activation_digest,
    }
    for relative in sorted(required_paths):
        raw = _repo_file(root, relative).read_bytes()
        observed = _sha256(raw)
        if member_digests.get(relative) != observed:
            raise ValueError(f"E_V250_RUNTIME_TRANSITION_MEMBER_DIGEST:{relative}")
        input_digests[relative] = observed

    return {
        "activation_manifest_path": activation_path,
        "prompt_manifest_path": prompt_manifest_path,
        "route_id": expected_route_id,
        "route_receipt_path": _path_label(route_path, root),
        "route_receipt_sha256": _sha256(route_raw),
        "route_closure_digest": route_receipt["closure_digest"],
        "current_loaded_paths": list(expected_current_paths),
        "current_input_digests": current_digests,
        "input_digests": dict(sorted(input_digests.items())),
    }


def _load_authorization(
    path: Path | str, *, root: Path
) -> tuple[dict[str, Any], str, str]:
    resolved = _evidence_file(path, root)
    value, raw = _read_json_file(resolved)
    intent = value.get("intent")
    authorization_id = value.get("authorization_id")
    actions = value.get("action_allowlist")
    repository = value.get("repository")
    if (
        value.get("schema_version")
        != "goal-teams-project-start-authorization-v2.50"
        or not isinstance(authorization_id, str)
        or not authorization_id
        or value.get("receipt_id") != authorization_id
        or value.get("authorization_state")
        != "granted_once_at_project_start"
        or value.get("authorization_lineage_preserved") is not True
        or value.get("version") != "V2.51"
        or not isinstance(repository, dict)
        or repository.get("name_with_owner") != "vibe-coding-era/goal-teams"
        or not isinstance(actions, list)
        or "fresh_runtime_transition" not in actions
        or not isinstance(intent, dict)
        or value.get("intent_sha256") != _canonical_sha256(intent)
    ):
        raise ValueError("E_V250_RUNTIME_TRANSITION_AUTHORIZATION")
    return value, _path_label(resolved, root), _sha256(raw)


def _append_if(errors: list[str], condition: bool, code: str) -> None:
    if condition:
        errors.append(code)


def _parse_timestamp(value: object, error_code: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(error_code)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(error_code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(error_code)
    return parsed.astimezone(dt.timezone.utc)


def _validation_clock(value: dt.datetime | None) -> dt.datetime:
    observed = value or dt.datetime.now(dt.timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("E_V250_CONTROLLER_HANDOFF_TIME")
    return observed.astimezone(dt.timezone.utc)


def _verify_handoff_signature(
    signed_payload: Mapping[str, Any], signature: str
) -> bool:
    """Verify the V2.50 handoff with the one pinned owner SSH public key."""

    if not isinstance(signature, str) or not signature.strip():
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="goal-teams-v250-handoff-") as directory:
            temp = Path(directory)
            allowed = temp / "allowed_signers"
            signature_path = temp / "handoff.sig"
            allowed.write_text(
                f"{PINNED_GITHUB_ACCOUNT} {PINNED_GITHUB_PUBLIC_KEY}\n",
                encoding="utf-8",
            )
            signature_path.write_text(signature, encoding="utf-8")
            result = subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed),
                    "-I",
                    PINNED_GITHUB_ACCOUNT,
                    "-n",
                    HANDOFF_SIGNATURE_NAMESPACE,
                    "-s",
                    str(signature_path),
                ],
                input=_canonical_bytes(signed_payload),
                check=False,
                capture_output=True,
            )
    except (OSError, UnicodeError):
        return False
    return result.returncode == 0


def validate_controller_handoff(
    receipt: object,
    *,
    expected_repository: str | None = None,
    expected_source_commit: str | None = None,
    expected_source_tree: str | None = None,
    expected_authorization_id: str | None = None,
    expected_authorization_receipt_sha256: str | None = None,
    expected_authorization_intent_sha256: str | None = None,
    validation_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Validate the externally issued, host-signed V2.50 handoff."""

    errors: list[str] = []
    if not isinstance(receipt, dict):
        return {
            "ok": False,
            "passed": False,
            "errors": ["E_V250_CONTROLLER_HANDOFF_REQUIRED"],
            "payload": {},
        }
    value = receipt
    expected_top_fields = {
        "schema_version",
        "signed_payload",
        "payload_sha256",
        "ssh_signature",
    }
    _append_if(
        errors,
        set(value) != expected_top_fields
        or value.get("schema_version") != HANDOFF_SCHEMA_VERSION,
        "E_V250_CONTROLLER_HANDOFF_SCHEMA",
    )
    payload = value.get("signed_payload")
    if not isinstance(payload, dict):
        errors.append("E_V250_CONTROLLER_HANDOFF_SCHEMA")
        payload = {}
    expected_payload_fields = {
        "repository",
        "source_commit",
        "source_tree",
        "authorization_id",
        "authorization_receipt_sha256",
        "authorization_intent_sha256",
        "previous_controller_product_version",
        "previous_run_id",
        "nonce",
        "issued_at",
        "expires_at",
        "installed_v250_current_state",
        "github_signing_identity",
    }
    _append_if(
        errors,
        set(payload) != expected_payload_fields,
        "E_V250_CONTROLLER_HANDOFF_SCHEMA",
    )
    _append_if(
        errors,
        payload.get("repository") != REPOSITORY
        or (
            expected_repository is not None
            and payload.get("repository") != expected_repository
        )
        or not isinstance(payload.get("source_commit"), str)
        or COMMIT_RE.fullmatch(str(payload.get("source_commit", ""))) is None
        or not isinstance(payload.get("source_tree"), str)
        or COMMIT_RE.fullmatch(str(payload.get("source_tree", ""))) is None
        or (
            expected_source_commit is not None
            and payload.get("source_commit") != expected_source_commit
        )
        or (
            expected_source_tree is not None
            and payload.get("source_tree") != expected_source_tree
        ),
        "E_V250_CONTROLLER_HANDOFF_IDENTITY_DRIFT",
    )
    _append_if(
        errors,
        payload.get("previous_controller_product_version")
        != PREVIOUS_CONTROLLER_PRODUCT_VERSION
        or "controller_version" in payload,
        "E_V250_CONTROLLER_HANDOFF_VERSION",
    )
    _append_if(
        errors,
        not _validate_run_id(payload.get("previous_run_id")),
        "E_V250_CONTROLLER_HANDOFF_RUN_LINEAGE",
    )
    _append_if(
        errors,
        not isinstance(payload.get("nonce"), str)
        or NONCE_RE.fullmatch(str(payload.get("nonce", ""))) is None,
        "E_V250_CONTROLLER_HANDOFF_NONCE",
    )
    _append_if(
        errors,
        not isinstance(payload.get("authorization_id"), str)
        or not payload.get("authorization_id")
        or not isinstance(payload.get("authorization_receipt_sha256"), str)
        or SHA256_RE.fullmatch(
            str(payload.get("authorization_receipt_sha256", ""))
        )
        is None
        or not isinstance(payload.get("authorization_intent_sha256"), str)
        or SHA256_RE.fullmatch(
            str(payload.get("authorization_intent_sha256", ""))
        )
        is None
        or (
            expected_authorization_id is not None
            and payload.get("authorization_id") != expected_authorization_id
        )
        or (
            expected_authorization_receipt_sha256 is not None
            and payload.get("authorization_receipt_sha256")
            != expected_authorization_receipt_sha256
        )
        or (
            expected_authorization_intent_sha256 is not None
            and payload.get("authorization_intent_sha256")
            != expected_authorization_intent_sha256
        ),
        "E_V250_CONTROLLER_HANDOFF_AUTHORIZATION_DRIFT",
    )

    installed = payload.get("installed_v250_current_state")
    expected_installed_fields = {
        "state_sha256",
        "source_commit",
        "source_tree",
        "tag",
        "release_id",
    }
    _append_if(
        errors,
        not isinstance(installed, dict)
        or set(installed) != expected_installed_fields
        or SHA256_RE.fullmatch(str(installed.get("state_sha256", ""))) is None
        or COMMIT_RE.fullmatch(str(installed.get("source_commit", ""))) is None
        or COMMIT_RE.fullmatch(str(installed.get("source_tree", ""))) is None
        or installed.get("tag") != "v2.50"
        or not isinstance(installed.get("release_id"), int)
        or isinstance(installed.get("release_id"), bool)
        or installed.get("release_id", 0) < 1,
        "E_V250_CONTROLLER_HANDOFF_INSTALLED_STATE",
    )

    signer = payload.get("github_signing_identity")
    expected_signer_fields = {
        "account",
        "key_id",
        "public_key",
        "public_key_fingerprint",
        "ssh_signature_namespace",
    }
    _append_if(
        errors,
        not isinstance(signer, dict)
        or set(signer) != expected_signer_fields
        or signer.get("account") != PINNED_GITHUB_ACCOUNT
        or signer.get("key_id") != PINNED_GITHUB_KEY_ID
        or signer.get("public_key") != PINNED_GITHUB_PUBLIC_KEY
        or signer.get("public_key_fingerprint") != PINNED_GITHUB_FINGERPRINT
        or signer.get("ssh_signature_namespace") != HANDOFF_SIGNATURE_NAMESPACE,
        "E_V250_CONTROLLER_HANDOFF_SIGNER_DRIFT",
    )

    claimed_payload_digest = value.get("payload_sha256")
    _append_if(
        errors,
        not isinstance(claimed_payload_digest, str)
        or SHA256_RE.fullmatch(claimed_payload_digest) is None
        or claimed_payload_digest != object_sha256(payload),
        "E_V250_CONTROLLER_HANDOFF_PAYLOAD_DIGEST",
    )
    now = _validation_clock(validation_time)
    try:
        issued = _parse_timestamp(payload.get("issued_at"), "E_V250_CONTROLLER_HANDOFF_TIME")
        expires = _parse_timestamp(
            payload.get("expires_at"), "E_V250_CONTROLLER_HANDOFF_TIME"
        )
        if issued >= expires:
            errors.append("E_V250_CONTROLLER_HANDOFF_TIME")
        if now < issued:
            errors.append("E_V250_CONTROLLER_HANDOFF_TIME_DRIFT")
        if now >= expires:
            errors.append("E_V250_CONTROLLER_HANDOFF_EXPIRED")
    except ValueError as exc:
        errors.append(str(exc))

    if not _verify_handoff_signature(payload, str(value.get("ssh_signature", ""))):
        errors.append("E_V250_CONTROLLER_HANDOFF_SIGNATURE")

    deduplicated = list(dict.fromkeys(errors))
    return {
        "ok": not deduplicated,
        "passed": not deduplicated,
        "errors": deduplicated,
        "payload": payload,
        "receipt_sha256": object_sha256(value),
    }


def validate_runtime_launch(
    receipt: object,
    *,
    controller_handoff_receipt: Mapping[str, Any],
    expected_adapter_identity: str | None = None,
    expected_adapter_code_sha256: str | None = None,
    expected_host_execution_id: str | None = None,
    actual_parent_pid: int | None = None,
    actual_child_pid: int | None = None,
) -> dict[str, Any]:
    """Validate the adapter-created launch receipt and its process lineage."""

    if not isinstance(receipt, dict):
        return {
            "ok": False,
            "passed": False,
            "errors": ["E_V250_RUNTIME_LAUNCH_REQUIRED"],
        }
    value = receipt
    errors: list[str] = []
    expected_fields = {
        "schema_version",
        "controller_handoff_receipt_sha256",
        "controller_handoff_payload_sha256",
        "nonce",
        "parent_pid",
        "expected_child_pid",
        "host_execution_id",
        "new_run_id",
        "launched_at",
        "adapter_identity",
        "adapter_code_sha256",
        "receipt_sha256",
    }
    _append_if(
        errors,
        set(value) != expected_fields
        or value.get("schema_version") != LAUNCH_SCHEMA_VERSION,
        "E_V250_RUNTIME_LAUNCH_SCHEMA",
    )
    handoff_payload = controller_handoff_receipt.get("signed_payload")
    handoff_payload = handoff_payload if isinstance(handoff_payload, dict) else {}
    parent_pid = value.get("parent_pid")
    child_pid = value.get("expected_child_pid")
    previous_run_id = handoff_payload.get("previous_run_id")
    _append_if(
        errors,
        value.get("controller_handoff_receipt_sha256")
        != object_sha256(controller_handoff_receipt)
        or value.get("controller_handoff_payload_sha256")
        != controller_handoff_receipt.get("payload_sha256")
        or value.get("nonce") != handoff_payload.get("nonce")
        or not isinstance(parent_pid, int)
        or isinstance(parent_pid, bool)
        or parent_pid < 1
        or not isinstance(child_pid, int)
        or isinstance(child_pid, bool)
        or child_pid < 1
        or parent_pid == child_pid
        or (actual_parent_pid is not None and parent_pid != actual_parent_pid)
        or (actual_child_pid is not None and child_pid != actual_child_pid)
        or not _validate_run_id(value.get("host_execution_id"))
        or (
            expected_host_execution_id is not None
            and value.get("host_execution_id") != expected_host_execution_id
        )
        or not _validate_run_id(value.get("new_run_id"))
        or value.get("new_run_id") == previous_run_id,
        "E_V250_RUNTIME_LAUNCH_LINEAGE",
    )
    _append_if(
        errors,
        not isinstance(value.get("adapter_identity"), str)
        or not value.get("adapter_identity")
        or (
            expected_adapter_identity is not None
            and value.get("adapter_identity") != expected_adapter_identity
        )
        or SHA256_RE.fullmatch(str(value.get("adapter_code_sha256", ""))) is None
        or (
            expected_adapter_code_sha256 is not None
            and value.get("adapter_code_sha256") != expected_adapter_code_sha256
        ),
        "E_V250_RUNTIME_LAUNCH_ADAPTER",
    )
    try:
        launched = _parse_timestamp(
            value.get("launched_at"), "E_V250_RUNTIME_LAUNCH_TIME"
        )
        issued = _parse_timestamp(
            handoff_payload.get("issued_at"), "E_V250_RUNTIME_LAUNCH_TIME"
        )
        expires = _parse_timestamp(
            handoff_payload.get("expires_at"), "E_V250_RUNTIME_LAUNCH_TIME"
        )
        if launched < issued or launched >= expires:
            errors.append("E_V250_RUNTIME_LAUNCH_TIME")
    except ValueError as exc:
        errors.append(str(exc))
    _append_if(
        errors,
        not isinstance(value.get("receipt_sha256"), str)
        or value.get("receipt_sha256") != _canonical_sha256(value),
        "E_V250_RUNTIME_LAUNCH_DIGEST",
    )
    deduplicated = list(dict.fromkeys(errors))
    return {"ok": not deduplicated, "passed": not deduplicated, "errors": deduplicated}


def observe_transition(
    *,
    stage: str,
    source_commit: str,
    source_tree: str,
    project_size: str,
    route_receipt_path: Path | str,
    authorization_receipt_path: Path | str,
    adapter_identity: str,
    adapter_code_path: Path | str,
    controller_handoff_receipt: object,
    runtime_launch_receipt: object,
    captured_at: str | None = None,
    transition_id: str | None = None,
    validation_time: dt.datetime | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Bind Current inputs only after the signed handoff and real child launch."""

    root = root.resolve()
    if stage not in {"candidate", "released"}:
        raise ValueError("E_V250_RUNTIME_TRANSITION_STAGE")
    if project_size not in {"discussion", "small", "medium", "large"}:
        raise ValueError("E_V250_RUNTIME_TRANSITION_PROJECT_SIZE")
    if stage == "released" and project_size == "discussion":
        raise ValueError("E_V250_RUNTIME_TRANSITION_PROJECT_SIZE")
    if COMMIT_RE.fullmatch(source_commit) is None or COMMIT_RE.fullmatch(source_tree) is None:
        raise ValueError("E_V250_RUNTIME_TRANSITION_IDENTITY")
    if not isinstance(adapter_identity, str) or not adapter_identity.strip():
        raise ValueError("E_V250_RUNTIME_TRANSITION_ADAPTER_IDENTITY")
    if not isinstance(controller_handoff_receipt, dict):
        raise ValueError("E_V250_CONTROLLER_HANDOFF_REQUIRED")
    if not isinstance(runtime_launch_receipt, dict):
        raise ValueError("E_V250_RUNTIME_LAUNCH_REQUIRED")

    authorization, authorization_path_label, authorization_digest = _load_authorization(
        authorization_receipt_path, root=root
    )
    handoff_verdict = validate_controller_handoff(
        controller_handoff_receipt,
        expected_repository=REPOSITORY,
        expected_source_commit=source_commit,
        expected_source_tree=source_tree,
        expected_authorization_id=authorization["authorization_id"],
        expected_authorization_receipt_sha256=authorization_digest,
        expected_authorization_intent_sha256=authorization["intent_sha256"],
        validation_time=validation_time,
    )
    if not handoff_verdict["ok"]:
        raise ValueError(handoff_verdict["errors"][0])

    adapter_path = _evidence_file(adapter_code_path, root)
    adapter_digest = _sha256(adapter_path.read_bytes())
    launch_verdict = validate_runtime_launch(
        runtime_launch_receipt,
        controller_handoff_receipt=controller_handoff_receipt,
        expected_adapter_identity=adapter_identity.strip(),
        expected_adapter_code_sha256=adapter_digest,
        actual_parent_pid=os.getppid(),
        actual_child_pid=os.getpid(),
    )
    if not launch_verdict["ok"]:
        raise ValueError(launch_verdict["errors"][0])

    route = _load_route_context(
        root=root,
        stage=stage,
        project_size=project_size,
        route_receipt_path=route_receipt_path,
        loaded_runtime_product_version=LOADED_RUNTIME_PRODUCT_VERSION,
    )
    captured = _normalize_timestamp(
        captured_at or str(runtime_launch_receipt.get("launched_at", ""))
    )
    input_digests = route["input_digests"]
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-v2.51-runtime-transition-receipt-v1",
        "transition_id": transition_id or f"V250-TRANSITION-{uuid.uuid4().hex}",
        "stage": stage,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "generation_id": "V2.51",
        "loaded_runtime_product_version": LOADED_RUNTIME_PRODUCT_VERSION,
        "project_size": project_size,
        "route_id": route["route_id"],
        "route_receipt_path": route["route_receipt_path"],
        "route_receipt_sha256": route["route_receipt_sha256"],
        "route_closure_digest": route["route_closure_digest"],
        "authorization_receipt_path": authorization_path_label,
        "authorization_receipt_sha256": authorization_digest,
        "authorization_id": authorization["authorization_id"],
        "authorization_lineage_preserved": True,
        "authorization_intent_sha256": authorization["intent_sha256"],
        "adapter_identity": adapter_identity.strip(),
        "adapter_code_path": _path_label(adapter_path, root),
        "adapter_code_sha256": adapter_digest,
        "controller_handoff_receipt": copy.deepcopy(controller_handoff_receipt),
        "controller_handoff_receipt_sha256": object_sha256(
            controller_handoff_receipt
        ),
        "controller_handoff_signature_verified": True,
        "runtime_launch_receipt": copy.deepcopy(runtime_launch_receipt),
        "runtime_launch_receipt_sha256": object_sha256(runtime_launch_receipt),
        "host_execution_id": runtime_launch_receipt["host_execution_id"],
        "captured_at": captured,
        "fresh_process_observed": True,
        "fresh_process_kind": "host_adapter_popen_child",
        "runner_pid": runtime_launch_receipt["expected_child_pid"],
        "orchestrator_pid": runtime_launch_receipt["parent_pid"],
        "actor_assurance": "I1",
        "actor_relationship": "correlated",
        "independence_claim": False,
        "external_independent": False,
        "cryptographic_host_attestation": False,
        "activation_manifest_path": route["activation_manifest_path"],
        "prompt_manifest_path": route["prompt_manifest_path"],
        "release_profile_path": RELEASE_PROFILE_PATH,
        "policy_profile_path": POLICY_PROFILE_PATH,
        "release_route_manifest_path": RELEASE_ROUTE_MANIFEST_PATH,
        "release_command_manifest_path": RELEASE_COMMAND_MANIFEST_PATH,
        "root_agents_sha256": input_digests["AGENTS.md"],
        "root_skill_sha256": input_digests["SKILL.md"],
        "active_pointer_sha256": input_digests[ACTIVE_PATH],
        "activation_manifest_sha256": input_digests[route["activation_manifest_path"]],
        "prompt_manifest_sha256": input_digests[route["prompt_manifest_path"]],
        "release_profile_sha256": input_digests[RELEASE_PROFILE_PATH],
        "policy_profile_sha256": input_digests[POLICY_PROFILE_PATH],
        "release_route_manifest_sha256": input_digests[RELEASE_ROUTE_MANIFEST_PATH],
        "release_command_manifest_sha256": input_digests[
            RELEASE_COMMAND_MANIFEST_PATH
        ],
        "current_loaded_paths": route["current_loaded_paths"],
        "current_input_digests": route["current_input_digests"],
        "input_digests": input_digests,
        "loaded_paths": sorted(input_digests),
        "receipt_state": "current",
    }
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    return receipt


def validate_transition(
    receipt: object,
    *,
    expected_stage: str,
    allow_release: bool,
    expected_source_commit: str | None = None,
    expected_source_tree: str | None = None,
    expected_project_size: str | None = None,
    expected_route_receipt_sha256: str | None = None,
    expected_authorization_receipt_sha256: str | None = None,
    expected_authorization_id: str | None = None,
    expected_adapter_identity: str | None = None,
    expected_adapter_code_sha256: str | None = None,
    expected_host_execution_id: str | None = None,
    route_receipt_path_override: Path | str | None = None,
    authorization_receipt_path_override: Path | str | None = None,
    validation_time: dt.datetime | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Strict shared Runtime/S0 validator; re-read all live bound inputs."""

    if expected_stage not in {"candidate", "released"}:
        raise ValueError("expected_stage must be candidate or released")
    errors: list[str] = []
    blocked_code: str | None = None
    value = receipt if isinstance(receipt, dict) else {}
    if not isinstance(receipt, dict):
        errors.append("E_V250_RUNTIME_TRANSITION_RECEIPT")
    try:
        expected_fields = _runtime_transition_field_contract(root.resolve())
    except ValueError as exc:
        errors.append(str(exc))
    else:
        _append_if(
            errors,
            set(value) != expected_fields,
            "E_V250_RUNTIME_TRANSITION_SCHEMA_FIELDS",
        )
    _append_if(
        errors,
        value.get("schema_version")
        != "goal-teams-v2.51-runtime-transition-receipt-v1",
        "E_V250_RUNTIME_TRANSITION_SCHEMA",
    )
    _append_if(
        errors,
        any(
            field in value
            for field in (
                "controller_version",
                "previous_controller_product_version",
                "previous_run_id",
                "new_run_id",
            )
        ),
        "E_V250_RUNTIME_TRANSITION_RAW_LINEAGE",
    )
    if value.get("fresh_process_observed") is not True:
        errors.append("E_V250_FRESH_RUNTIME_REQUIRED")
        blocked_code = "fresh_runtime_transition_unavailable"
    _append_if(
        errors,
        value.get("fresh_process_kind") != "host_adapter_popen_child"
        or not isinstance(value.get("runner_pid"), int)
        or isinstance(value.get("runner_pid"), bool)
        or value.get("runner_pid", 0) < 1
        or not isinstance(value.get("orchestrator_pid"), int)
        or isinstance(value.get("orchestrator_pid"), bool)
        or value.get("orchestrator_pid", 0) < 1
        or value.get("runner_pid") == value.get("orchestrator_pid"),
        "E_V250_RUNTIME_TRANSITION_PROCESS",
    )
    _append_if(
        errors,
        value.get("stage") != expected_stage,
        "E_V250_RUNTIME_TRANSITION_STAGE",
    )
    _append_if(
        errors,
        value.get("generation_id") != "V2.51"
        or value.get("loaded_runtime_product_version")
        != LOADED_RUNTIME_PRODUCT_VERSION,
        "E_V250_RUNTIME_TRANSITION_VERSION_AXIS",
    )
    _append_if(
        errors,
        value.get("receipt_state") != "current",
        "E_V250_RUNTIME_TRANSITION_STALE",
    )
    _append_if(
        errors,
        value.get("actor_assurance") != "I1"
        or value.get("actor_relationship") != "correlated"
        or value.get("independence_claim") is not False
        or value.get("external_independent") is not False
        or value.get("cryptographic_host_attestation") is not False,
        "E_V250_RUNTIME_TRANSITION_ASSURANCE",
    )

    source_commit = value.get("source_commit")
    source_tree = value.get("source_tree")
    _append_if(
        errors,
        not isinstance(source_commit, str)
        or COMMIT_RE.fullmatch(source_commit) is None
        or not isinstance(source_tree, str)
        or COMMIT_RE.fullmatch(source_tree) is None
        or (
            expected_source_commit is not None
            and source_commit != expected_source_commit
        )
        or (expected_source_tree is not None and source_tree != expected_source_tree),
        "E_V250_RUNTIME_TRANSITION_IDENTITY",
    )
    project_size = value.get("project_size")
    _append_if(
        errors,
        project_size not in {"discussion", "small", "medium", "large"}
        or (expected_project_size is not None and project_size != expected_project_size),
        "E_V250_RUNTIME_TRANSITION_PROJECT_SIZE",
    )
    try:
        _parse_timestamp(
            value.get("captured_at"), "E_V250_RUNTIME_TRANSITION_CAPTURED_AT"
        )
    except ValueError as exc:
        errors.append(str(exc))

    digests = value.get("input_digests")
    loaded_paths = value.get("loaded_paths")
    current_paths = value.get("current_loaded_paths")
    current_digests = value.get("current_input_digests")
    _append_if(
        errors,
        not isinstance(digests, dict)
        or not digests
        or any(
            not isinstance(item, str) or SHA256_RE.fullmatch(item) is None
            for item in (digests.values() if isinstance(digests, dict) else [])
        ),
        "E_V250_RUNTIME_TRANSITION_DIGEST",
    )
    _append_if(
        errors,
        not isinstance(loaded_paths, list)
        or not isinstance(digests, dict)
        or loaded_paths != sorted(digests)
        or not {"AGENTS.md", "SKILL.md", ACTIVE_PATH}.issubset(
            set(loaded_paths if isinstance(loaded_paths, list) else [])
        ),
        "E_V250_RUNTIME_TRANSITION_LOADED_PATHS",
    )
    _append_if(
        errors,
        not isinstance(current_paths, list)
        or not current_paths
        or len(current_paths) != len(set(current_paths))
        or not isinstance(current_digests, dict)
        or set(current_digests if isinstance(current_digests, dict) else {})
        != set(current_paths if isinstance(current_paths, list) else []),
        "E_V250_RUNTIME_TRANSITION_CURRENT_DIGEST",
    )
    expected_aliases = {
        "root_agents_sha256": "AGENTS.md",
        "root_skill_sha256": "SKILL.md",
        "active_pointer_sha256": ACTIVE_PATH,
        "activation_manifest_sha256": value.get("activation_manifest_path"),
        "prompt_manifest_sha256": value.get("prompt_manifest_path"),
        "release_profile_sha256": RELEASE_PROFILE_PATH,
        "policy_profile_sha256": POLICY_PROFILE_PATH,
        "release_route_manifest_sha256": RELEASE_ROUTE_MANIFEST_PATH,
        "release_command_manifest_sha256": RELEASE_COMMAND_MANIFEST_PATH,
    }
    if isinstance(digests, dict):
        _append_if(
            errors,
            any(
                not isinstance(path, str) or value.get(field) != digests.get(path)
                for field, path in expected_aliases.items()
            ),
            "E_V250_RUNTIME_TRANSITION_APPROVED_PROMPT_DIGEST",
        )

    root = root.resolve()
    observed_context: dict[str, Any] | None = None
    route_evidence_current = False
    route_receipt_input = (
        route_receipt_path_override
        if route_receipt_path_override is not None
        else str(value.get("route_receipt_path", ""))
    )
    try:
        route_evidence = _evidence_file(route_receipt_input, root)
        route_evidence_current = value.get("route_receipt_sha256") == _sha256(
            route_evidence.read_bytes()
        )
        if not route_evidence_current:
            errors.append("E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT_DIGEST")
    except (OSError, ValueError):
        errors.append("E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT_DIGEST")
    try:
        observed_context = _load_route_context(
            root=root,
            stage=str(value.get("stage", "")),
            project_size=str(project_size or ""),
            route_receipt_path=route_receipt_input,
            loaded_runtime_product_version=LOADED_RUNTIME_PRODUCT_VERSION,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        code = str(exc)
        if not route_evidence_current or "ROUTE" in code:
            errors.append("E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT_DIGEST")
        else:
            errors.append(
                code
                if code.startswith("E_V250_")
                else "E_V250_RUNTIME_TRANSITION_CURRENT_INPUT"
            )
    if observed_context is not None:
        _append_if(
            errors,
            value.get("route_id") != observed_context["route_id"]
            or value.get("route_receipt_sha256")
            != observed_context["route_receipt_sha256"]
            or value.get("route_closure_digest")
            != observed_context["route_closure_digest"]
            or (
                expected_route_receipt_sha256 is not None
                and value.get("route_receipt_sha256")
                != expected_route_receipt_sha256
            ),
            "E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT_DIGEST",
        )
        _append_if(
            errors,
            current_paths != observed_context["current_loaded_paths"]
            or current_digests != observed_context["current_input_digests"],
            "E_V250_RUNTIME_TRANSITION_CURRENT_DIGEST",
        )
        _append_if(
            errors,
            digests != observed_context["input_digests"]
            or loaded_paths != sorted(observed_context["input_digests"]),
            "E_V250_RUNTIME_TRANSITION_LOADED_PATHS",
        )

    authorization: dict[str, Any] | None = None
    authorization_digest: str | None = None
    authorization_receipt_input = (
        authorization_receipt_path_override
        if authorization_receipt_path_override is not None
        else str(value.get("authorization_receipt_path", ""))
    )
    try:
        authorization, authorization_label, authorization_digest = _load_authorization(
            authorization_receipt_input, root=root
        )
        _append_if(
            errors,
            (
                authorization_receipt_path_override is None
                and value.get("authorization_receipt_path") != authorization_label
            )
            or value.get("authorization_receipt_sha256") != authorization_digest
            or value.get("authorization_id") != authorization.get("authorization_id")
            or value.get("authorization_lineage_preserved") is not True
            or value.get("authorization_intent_sha256")
            != authorization.get("intent_sha256")
            or (
                expected_authorization_receipt_sha256 is not None
                and authorization_digest != expected_authorization_receipt_sha256
            )
            or (
                expected_authorization_id is not None
                and authorization.get("authorization_id") != expected_authorization_id
            ),
            "E_V250_RUNTIME_TRANSITION_AUTHORIZATION_RECEIPT_DIGEST",
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        errors.append("E_V250_RUNTIME_TRANSITION_AUTHORIZATION_RECEIPT_DIGEST")

    adapter_digest: str | None = None
    try:
        adapter_path = _evidence_file(str(value.get("adapter_code_path", "")), root)
        adapter_digest = _sha256(adapter_path.read_bytes())
        _append_if(
            errors,
            value.get("adapter_code_path") != _path_label(adapter_path, root)
            or value.get("adapter_code_sha256") != adapter_digest
            or (
                expected_adapter_code_sha256 is not None
                and adapter_digest != expected_adapter_code_sha256
            )
            or (
                expected_adapter_identity is not None
                and value.get("adapter_identity") != expected_adapter_identity
            ),
            "E_V250_RUNTIME_TRANSITION_ADAPTER_CODE_DIGEST",
        )
    except (OSError, ValueError):
        errors.append("E_V250_RUNTIME_TRANSITION_ADAPTER_CODE_DIGEST")

    handoff = value.get("controller_handoff_receipt")
    if not isinstance(handoff, dict):
        errors.append("E_V250_CONTROLLER_HANDOFF_REQUIRED")
        handoff = {}
    else:
        _append_if(
            errors,
            value.get("controller_handoff_receipt_sha256") != object_sha256(handoff)
            or value.get("controller_handoff_signature_verified") is not True,
            "E_V250_CONTROLLER_HANDOFF_DIGEST",
        )
        handoff_verdict = validate_controller_handoff(
            handoff,
            expected_repository=REPOSITORY,
            expected_source_commit=source_commit if isinstance(source_commit, str) else None,
            expected_source_tree=source_tree if isinstance(source_tree, str) else None,
            expected_authorization_id=(
                authorization.get("authorization_id") if authorization else None
            ),
            expected_authorization_receipt_sha256=authorization_digest,
            expected_authorization_intent_sha256=(
                authorization.get("intent_sha256") if authorization else None
            ),
            validation_time=validation_time,
        )
        errors.extend(handoff_verdict["errors"])

    launch = value.get("runtime_launch_receipt")
    if not isinstance(launch, dict):
        errors.append("E_V250_RUNTIME_LAUNCH_REQUIRED")
        launch = {}
    else:
        _append_if(
            errors,
            value.get("runtime_launch_receipt_sha256") != object_sha256(launch),
            "E_V250_RUNTIME_LAUNCH_DIGEST",
        )
        launch_verdict = validate_runtime_launch(
            launch,
            controller_handoff_receipt=handoff,
            expected_adapter_identity=str(value.get("adapter_identity", "")),
            expected_adapter_code_sha256=adapter_digest,
            expected_host_execution_id=(
                expected_host_execution_id or str(value.get("host_execution_id", ""))
            ),
        )
        errors.extend(launch_verdict["errors"])
        _append_if(
            errors,
            value.get("runner_pid") != launch.get("expected_child_pid")
            or value.get("orchestrator_pid") != launch.get("parent_pid")
            or value.get("host_execution_id") != launch.get("host_execution_id")
            or value.get("captured_at") != launch.get("launched_at"),
            "E_V250_RUNTIME_LAUNCH_LINEAGE",
        )

    claimed = value.get("receipt_sha256")
    _append_if(
        errors,
        not isinstance(claimed, str)
        or SHA256_RE.fullmatch(claimed) is None
        or claimed != _canonical_sha256(value),
        "E_V250_RUNTIME_TRANSITION_RECEIPT_DIGEST",
    )
    deduplicated = list(dict.fromkeys(errors))
    ok = not deduplicated
    return {
        "ok": ok,
        "passed": ok,
        "errors": deduplicated,
        "blocked_code": blocked_code,
        "may_enter_s0": bool(
            ok
            and allow_release
            and expected_stage == "released"
            and value.get("stage") == "released"
        ),
        "external_independence_proven": False,
        "actor_assurance": "I1" if ok else value.get("actor_assurance"),
        "receipt_sha256": value.get("receipt_sha256"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--stage", choices=("candidate", "released"), required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument(
        "--project-size",
        choices=("discussion", "small", "medium", "large"),
        required=True,
    )
    parser.add_argument("--route-receipt", type=Path, required=True)
    parser.add_argument("--authorization-receipt", type=Path, required=True)
    parser.add_argument("--adapter-identity", required=True)
    parser.add_argument("--adapter-code", type=Path, required=True)
    parser.add_argument("--transition-id")
    return parser.parse_args()


def _child_ack(
    receipt: Mapping[str, Any],
    handoff: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> dict[str, Any]:
    ack: dict[str, Any] = {
        "schema_version": CHILD_ACK_SCHEMA_VERSION,
        "acknowledged": True,
        "child_pid": os.getpid(),
        "parent_pid": os.getppid(),
        "nonce": launch.get("nonce"),
        "host_execution_id": launch.get("host_execution_id"),
        "new_run_id": launch.get("new_run_id"),
        "controller_handoff_receipt_sha256": object_sha256(handoff),
        "runtime_launch_receipt_sha256": object_sha256(launch),
        "runtime_transition_receipt_sha256": receipt.get("receipt_sha256"),
        "runtime_transition_receipt": copy.deepcopy(dict(receipt)),
    }
    ack["ack_sha256"] = _canonical_sha256(ack, digest_field="ack_sha256")
    return ack


def main() -> int:
    args = parse_args()
    try:
        if not args.child:
            raise ValueError("E_V250_RUNTIME_CHILD_MODE_REQUIRED")
        envelope = json.loads(sys.stdin.read())
        if not isinstance(envelope, dict) or set(envelope) != {
            "controller_handoff_receipt",
            "runtime_launch_receipt",
        }:
            raise ValueError("E_V250_RUNTIME_STDIN_RECEIPTS_REQUIRED")
        handoff = envelope["controller_handoff_receipt"]
        launch = envelope["runtime_launch_receipt"]
        receipt = observe_transition(
            stage=args.stage,
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            project_size=args.project_size,
            route_receipt_path=args.route_receipt,
            authorization_receipt_path=args.authorization_receipt,
            adapter_identity=args.adapter_identity,
            adapter_code_path=args.adapter_code,
            controller_handoff_receipt=handoff,
            runtime_launch_receipt=launch,
            captured_at=(launch.get("launched_at") if isinstance(launch, dict) else None),
            transition_id=args.transition_id,
        )
        result = _child_ack(receipt, handoff, launch)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": CHILD_ACK_SCHEMA_VERSION,
                    "acknowledged": False,
                    "error_code": str(exc),
                    "external_independence": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
