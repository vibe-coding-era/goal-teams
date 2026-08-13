#!/usr/bin/env python3
"""External host adapter for the V2.62 -> V2.63 runtime handoff.

This module never creates or signs a controller handoff.  It accepts the
V2.63 receipt externally issued by the installed V2.62 host, verifies the
pinned owner key, launches a fresh V2.63 child with ``Popen``, sends the
launch contract only after the child PID exists, and verifies the child's
acknowledgement.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.v250.runtime_transition import (
    CHILD_ACK_SCHEMA_VERSION,
    HANDOFF_SIGNATURE_NAMESPACE,
    LAUNCH_SCHEMA_VERSION,
    PINNED_GITHUB_ACCOUNT,
    PINNED_GITHUB_FINGERPRINT,
    PINNED_GITHUB_KEY_ID,
    PINNED_GITHUB_PUBLIC_KEY,
    REPOSITORY,
    ROOT,
    _canonical_sha256,
    _evidence_file,
    _load_authorization,
    _path_label,
    _sha256,
    object_sha256,
    validate_controller_handoff,
    validate_transition,
)


CHILD_FAILURE_STDOUT_MAX_BYTES = 4096
CHILD_ERROR_UNAVAILABLE = "E_V250_RUNTIME_CHILD_ERROR_UNAVAILABLE"
CHILD_STDERR_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
KNOWN_RUNTIME_CHILD_ERROR_CODES = frozenset(
    {
        "E_V250_CONTROLLER_HANDOFF_AUTHORIZATION_DRIFT",
        "E_V250_CONTROLLER_HANDOFF_DIGEST",
        "E_V250_CONTROLLER_HANDOFF_EXPIRED",
        "E_V250_CONTROLLER_HANDOFF_IDENTITY_DRIFT",
        "E_V250_CONTROLLER_HANDOFF_INSTALLED_STATE",
        "E_V250_CONTROLLER_HANDOFF_NONCE",
        "E_V250_CONTROLLER_HANDOFF_PAYLOAD_DIGEST",
        "E_V250_CONTROLLER_HANDOFF_REQUIRED",
        "E_V250_CONTROLLER_HANDOFF_RUN_LINEAGE",
        "E_V250_CONTROLLER_HANDOFF_SCHEMA",
        "E_V250_CONTROLLER_HANDOFF_SIGNATURE",
        "E_V250_CONTROLLER_HANDOFF_SIGNER_DRIFT",
        "E_V250_CONTROLLER_HANDOFF_TIME",
        "E_V250_CONTROLLER_HANDOFF_TIME_DRIFT",
        "E_V250_CONTROLLER_HANDOFF_VERSION",
        "E_V250_FRESH_RUNTIME_REQUIRED",
        "E_V250_OWNER_DIGEST_DRIFT",
        "E_V250_ROUTE_ALLOWLIST",
        "E_V250_ROUTE_BUDGET",
        "E_V250_ROUTE_BYTE_DRIFT",
        "E_V250_ROUTE_GENERATION",
        "E_V250_ROUTE_LEGACY_REACHABLE",
        "E_V250_ROUTE_MANIFEST",
        "E_V250_ROUTE_MEMBERSHIP_DRIFT",
        "E_V250_ROUTE_NON_TEXT",
        "E_V250_ROUTE_REFS",
        "E_V250_ROUTE_SHAPE",
        "E_V250_ROUTE_UNKNOWN",
        "E_V250_ROUTE_UNMANAGED",
        "E_V250_ROUTE_UNVERIFIED_GENERATION",
        "E_V250_ROUTE_WITHOUT_OWNER",
        "E_V250_RULE_ID_DUPLICATE",
        "E_V250_RULE_INDEX",
        "E_V250_RULE_OWNER",
        "E_V250_RULE_OWNER_DUPLICATE",
        "E_V250_RUNTIME_CHILD_MODE_REQUIRED",
        "E_V250_RUNTIME_LAUNCH_ADAPTER",
        "E_V250_RUNTIME_LAUNCH_DIGEST",
        "E_V250_RUNTIME_LAUNCH_LINEAGE",
        "E_V250_RUNTIME_LAUNCH_REQUIRED",
        "E_V250_RUNTIME_LAUNCH_SCHEMA",
        "E_V250_RUNTIME_LAUNCH_TIME",
        "E_V250_RUNTIME_STDIN_RECEIPTS_REQUIRED",
        "E_V250_RUNTIME_TRANSITION_ACTIVATION",
        "E_V250_RUNTIME_TRANSITION_ACTIVE",
        "E_V250_RUNTIME_TRANSITION_ACTIVE_DIGEST",
        "E_V250_RUNTIME_TRANSITION_ADAPTER_CODE_DIGEST",
        "E_V250_RUNTIME_TRANSITION_ADAPTER_IDENTITY",
        "E_V250_RUNTIME_TRANSITION_APPROVED_PROMPT_DIGEST",
        "E_V250_RUNTIME_TRANSITION_ASSURANCE",
        "E_V250_RUNTIME_TRANSITION_AUTHORIZATION",
        "E_V250_RUNTIME_TRANSITION_AUTHORIZATION_RECEIPT_DIGEST",
        "E_V250_RUNTIME_TRANSITION_CAPTURED_AT",
        "E_V250_RUNTIME_TRANSITION_CURRENT_DIGEST",
        "E_V250_RUNTIME_TRANSITION_CURRENT_INPUT",
        "E_V250_RUNTIME_TRANSITION_DIGEST",
        "E_V250_RUNTIME_TRANSITION_EVIDENCE_PATH",
        "E_V250_RUNTIME_TRANSITION_IDENTITY",
        "E_V250_RUNTIME_TRANSITION_JSON",
        "E_V250_RUNTIME_TRANSITION_LOADED_PATHS",
        "E_V250_RUNTIME_TRANSITION_PATH",
        "E_V250_RUNTIME_TRANSITION_PROCESS",
        "E_V250_RUNTIME_TRANSITION_PROJECT_SIZE",
        "E_V250_RUNTIME_TRANSITION_PROMPT_MANIFEST",
        "E_V250_RUNTIME_TRANSITION_RAW_LINEAGE",
        "E_V250_RUNTIME_TRANSITION_RECEIPT",
        "E_V250_RUNTIME_TRANSITION_RECEIPT_DIGEST",
        "E_V250_RUNTIME_TRANSITION_ROUTE",
        "E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT",
        "E_V250_RUNTIME_TRANSITION_ROUTE_RECEIPT_DIGEST",
        "E_V250_RUNTIME_TRANSITION_SCHEMA",
        "E_V250_RUNTIME_TRANSITION_SCHEMA_CONTRACT",
        "E_V250_RUNTIME_TRANSITION_SCHEMA_FIELDS",
        "E_V250_RUNTIME_TRANSITION_STAGE",
        "E_V250_RUNTIME_TRANSITION_STALE",
        "E_V250_RUNTIME_TRANSITION_VERSION_AXIS",
        "E_V263_CONTROL_ALIAS",
        "E_V263_CONTROL_ALIAS_COLLISION",
        "E_V263_CONTROL_TERM",
        "E_V263_DEPENDENCY_DUPLICATE",
        "E_V263_DEPENDENCY_KIND",
        "E_V263_DEPENDENCY_SHAPE",
        "E_V263_DEPENDENCY_UNKNOWN",
        "E_V263_DERIVED_ROUTE_CONTROLS",
        "E_V263_DERIVED_ROUTE_DIGEST",
        "E_V263_DERIVED_ROUTE_RECEIPT",
        "E_V263_DERIVED_ROUTE_REPLAY",
        "E_V263_FACTS",
        "E_V263_FACT_DEPENDENCY",
        "E_V263_ORDERED_REF_DUPLICATE",
        "E_V263_ORDERED_REFS",
        "E_V263_OWNER_DUPLICATE",
        "E_V263_OWNER_SHAPE",
        "E_V263_PHASE_DEPENDENCY",
        "E_V263_REQUIRED_DEPENDENCY",
        "E_V263_ROUTE_CONTROL",
        "E_V263_ROUTE_FACTS_REQUIRED",
        "E_V263_ROUTE_ID",
        "E_V263_ROUTE_MEMBERSHIP",
        "E_V263_ROUTE_WITHOUT_OWNER",
        "E_V263_RUNTIME_ROUTE_CLOSURE",
        "E_V263_RUNTIME_ROUTE_EVIDENCE_JSON",
        "E_V263_RUNTIME_ROUTE_EVIDENCE_NORMALIZATION",
        "E_V263_RUNTIME_ROUTE_EVIDENCE_REQUIRED",
        "E_V263_RUNTIME_ROUTE_FACTS",
        "E_V263_RUNTIME_ROUTE_FACTS_BINDING",
        "E_V263_RUNTIME_ROUTE_FACTS_DIGEST",
        "E_V263_RUNTIME_ROUTE_IDENTITY",
        "E_V263_RUNTIME_ROUTE_RECOMPILE",
        "E_V263_SEMANTIC_SHAPE",
    }
)


def _reject_duplicate_json_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


class RuntimeChildFailure(ValueError):
    """Machine-safe parent-side projection of a failed runtime child."""

    def __init__(self, *, child_error_code: str, child_stderr_sha256: str) -> None:
        super().__init__("E_V250_RUNTIME_CHILD_FAILED")
        self.child_error_code = (
            child_error_code
            if child_error_code in KNOWN_RUNTIME_CHILD_ERROR_CODES
            else CHILD_ERROR_UNAVAILABLE
        )
        if CHILD_STDERR_SHA256_RE.fullmatch(child_stderr_sha256) is None:
            raise ValueError("E_V250_RUNTIME_CHILD_DIAGNOSTIC_INVALID")
        self.child_stderr_sha256 = child_stderr_sha256

    def parent_envelope(self) -> dict[str, Any]:
        return {
            "passed": False,
            "error_code": "E_V250_RUNTIME_CHILD_FAILED",
            "child_error_code": self.child_error_code,
            "child_stderr_sha256": self.child_stderr_sha256,
            "external_write_count": 0,
        }


def _child_failure_error_code(stdout: str) -> str:
    if not isinstance(stdout, str):
        return CHILD_ERROR_UNAVAILABLE
    try:
        stdout_bytes = stdout.encode("utf-8")
    except UnicodeEncodeError:
        return CHILD_ERROR_UNAVAILABLE
    if len(stdout_bytes) > CHILD_FAILURE_STDOUT_MAX_BYTES:
        return CHILD_ERROR_UNAVAILABLE
    try:
        value = json.loads(stdout, object_pairs_hook=_reject_duplicate_json_key)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return CHILD_ERROR_UNAVAILABLE
    expected_fields = {
        "schema_version",
        "acknowledged",
        "error_code",
        "external_independence",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_fields
        or value.get("schema_version") != CHILD_ACK_SCHEMA_VERSION
        or value.get("acknowledged") is not False
        or value.get("external_independence") is not False
        or not isinstance(value.get("error_code"), str)
    ):
        return CHILD_ERROR_UNAVAILABLE
    error_code = value["error_code"]
    if error_code not in KNOWN_RUNTIME_CHILD_ERROR_CODES:
        return CHILD_ERROR_UNAVAILABLE
    return error_code


def _public_key_fingerprint(public_key: str) -> str | None:
    fields = public_key.split()
    if len(fields) < 2:
        return None
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    encoded = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii")
    return f"SHA256:{encoded.rstrip('=')}"


def validate_github_key_readback(value: object) -> dict[str, Any]:
    """Validate the fixed public `/users/vibe-coding-era/keys` response."""

    errors: list[str] = []
    entries = value if isinstance(value, list) else []
    matching = [
        item
        for item in entries
        if isinstance(item, dict) and item.get("id") == PINNED_GITHUB_KEY_ID
    ]
    if len(matching) != 1:
        errors.append("E_V250_GITHUB_OWNER_KEY_MISSING")
        public_key = None
    else:
        public_key = matching[0].get("key")
    fingerprint = (
        _public_key_fingerprint(public_key) if isinstance(public_key, str) else None
    )
    if (
        public_key is not None
        and (
            public_key != PINNED_GITHUB_PUBLIC_KEY
            or fingerprint != PINNED_GITHUB_FINGERPRINT
        )
    ):
        errors.append("E_V250_GITHUB_OWNER_KEY_DRIFT")
    deduplicated = list(dict.fromkeys(errors))
    return {
        "ok": not deduplicated,
        "passed": not deduplicated,
        "errors": deduplicated,
        "github_account": PINNED_GITHUB_ACCOUNT,
        "github_key_id": PINNED_GITHUB_KEY_ID,
        "public_key_fingerprint": fingerprint,
    }


def build_runtime_launch_receipt(
    *,
    controller_handoff_receipt: Mapping[str, Any],
    parent_pid: int,
    expected_child_pid: int,
    host_execution_id: str,
    adapter_identity: str,
    adapter_code_sha256: str,
    launched_at: str | None = None,
) -> dict[str, Any]:
    payload = controller_handoff_receipt.get("signed_payload")
    if not isinstance(payload, dict):
        raise ValueError("E_V250_CONTROLLER_HANDOFF_REQUIRED")
    if not isinstance(host_execution_id, str) or not host_execution_id:
        raise ValueError("E_V250_RUNTIME_LAUNCH_LINEAGE")
    new_run_id = f"V250-RUNTIME-{uuid.uuid4().hex}"
    receipt: dict[str, Any] = {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "controller_handoff_receipt_sha256": object_sha256(
            controller_handoff_receipt
        ),
        "controller_handoff_payload_sha256": controller_handoff_receipt.get(
            "payload_sha256"
        ),
        "nonce": payload.get("nonce"),
        "parent_pid": parent_pid,
        "expected_child_pid": expected_child_pid,
        "host_execution_id": host_execution_id,
        "new_run_id": new_run_id,
        "launched_at": launched_at
        or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "adapter_identity": adapter_identity,
        "adapter_code_sha256": adapter_code_sha256,
    }
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    return receipt


def _validate_child_ack(
    ack: object,
    *,
    controller_handoff_receipt: Mapping[str, Any],
    runtime_launch_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(ack, dict):
        raise ValueError("E_V250_RUNTIME_CHILD_ACK")
    receipt = ack.get("runtime_transition_receipt")
    expected_fields = {
        "schema_version",
        "acknowledged",
        "child_pid",
        "parent_pid",
        "nonce",
        "host_execution_id",
        "new_run_id",
        "controller_handoff_receipt_sha256",
        "runtime_launch_receipt_sha256",
        "runtime_transition_receipt_sha256",
        "runtime_transition_receipt",
        "ack_sha256",
    }
    if (
        set(ack) != expected_fields
        or ack.get("schema_version") != CHILD_ACK_SCHEMA_VERSION
        or ack.get("acknowledged") is not True
        or ack.get("child_pid")
        != runtime_launch_receipt.get("expected_child_pid")
        or ack.get("parent_pid") != runtime_launch_receipt.get("parent_pid")
        or ack.get("nonce") != runtime_launch_receipt.get("nonce")
        or ack.get("host_execution_id")
        != runtime_launch_receipt.get("host_execution_id")
        or ack.get("new_run_id") != runtime_launch_receipt.get("new_run_id")
        or ack.get("controller_handoff_receipt_sha256")
        != object_sha256(controller_handoff_receipt)
        or ack.get("runtime_launch_receipt_sha256")
        != object_sha256(runtime_launch_receipt)
        or not isinstance(receipt, dict)
        or ack.get("runtime_transition_receipt_sha256")
        != receipt.get("receipt_sha256")
        or ack.get("ack_sha256")
        != _canonical_sha256(ack, digest_field="ack_sha256")
    ):
        raise ValueError("E_V250_RUNTIME_CHILD_ACK")
    return receipt


def launch_runtime_transition(
    *,
    stage: str,
    source_commit: str,
    source_tree: str,
    project_size: str,
    route_facts_receipt_path: Path | str,
    derived_route_receipt_path: Path | str,
    route_receipt_path: Path | str,
    authorization_receipt_path: Path | str,
    adapter_identity: str,
    adapter_code_path: Path | str,
    controller_handoff_receipt: Mapping[str, Any],
    host_execution_id: str,
    root: Path = ROOT,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    """Launch and verify one fresh child for the exact signed handoff."""

    root = root.resolve()
    authorization, _, authorization_digest = _load_authorization(
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
        root=root,
    )
    if not handoff_verdict.get("ok"):
        errors = handoff_verdict.get("errors") or ["E_V250_CONTROLLER_HANDOFF_REQUIRED"]
        raise ValueError(str(errors[0]))

    adapter_path = _evidence_file(adapter_code_path, root)
    adapter_digest = _sha256(adapter_path.read_bytes())
    child_script = Path(__file__).with_name("runtime_transition.py").resolve()
    argv = [
        sys.executable,
        str(child_script),
        "--child",
        "--stage",
        stage,
        "--source-commit",
        source_commit,
        "--source-tree",
        source_tree,
        "--project-size",
        project_size,
        "--route-facts-receipt",
        str(route_facts_receipt_path),
        "--derived-route-receipt",
        str(derived_route_receipt_path),
        "--route-receipt",
        str(route_receipt_path),
        "--authorization-receipt",
        str(authorization_receipt_path),
        "--adapter-identity",
        adapter_identity,
        "--adapter-code",
        str(adapter_code_path),
    ]
    process = popen_factory(
        argv,
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if not isinstance(process.pid, int) or process.pid < 1:
        raise ValueError("E_V250_RUNTIME_CHILD_PID")
    launch = build_runtime_launch_receipt(
        controller_handoff_receipt=controller_handoff_receipt,
        parent_pid=os.getpid(),
        expected_child_pid=process.pid,
        host_execution_id=host_execution_id,
        adapter_identity=adapter_identity,
        adapter_code_sha256=adapter_digest,
    )
    envelope = {
        "controller_handoff_receipt": controller_handoff_receipt,
        "runtime_launch_receipt": launch,
    }
    stdout, stderr = process.communicate(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n"
    )
    if process.returncode != 0:
        raise RuntimeChildFailure(
            child_error_code=_child_failure_error_code(stdout),
            child_stderr_sha256=hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        )
    try:
        ack = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("E_V250_RUNTIME_CHILD_ACK") from exc
    receipt = _validate_child_ack(
        ack,
        controller_handoff_receipt=controller_handoff_receipt,
        runtime_launch_receipt=launch,
    )
    verdict = validate_transition(
        receipt,
        expected_stage=stage,
        allow_release=stage == "released",
        expected_source_commit=source_commit,
        expected_source_tree=source_tree,
        expected_project_size=project_size,
        expected_authorization_receipt_sha256=authorization_digest,
        expected_authorization_id=authorization["authorization_id"],
        expected_adapter_identity=adapter_identity,
        expected_adapter_code_sha256=adapter_digest,
        expected_host_execution_id=host_execution_id,
        route_facts_receipt_path_override=route_facts_receipt_path,
        derived_route_receipt_path_override=derived_route_receipt_path,
        route_receipt_path_override=route_receipt_path,
        authorization_receipt_path_override=authorization_receipt_path,
        root=root,
    )
    if not verdict.get("ok") or (stage == "released" and not verdict.get("may_enter_s0")):
        raise ValueError("E_V250_RUNTIME_CHILD_RECEIPT_INVALID")
    return receipt


def _read_json(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("E_V250_RUNTIME_HOST_INPUT")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    key = subparsers.add_parser("verify-github-key")
    key.add_argument("--github-keys", type=Path, required=True)

    launch = subparsers.add_parser("launch")
    launch.add_argument("--stage", choices=("candidate", "released"), required=True)
    launch.add_argument("--source-commit", required=True)
    launch.add_argument("--source-tree", required=True)
    launch.add_argument(
        "--project-size",
        choices=("discussion", "small", "medium", "large"),
        required=True,
    )
    launch.add_argument("--route-facts-receipt", type=Path, required=True)
    launch.add_argument("--derived-route-receipt", type=Path, required=True)
    launch.add_argument("--route-receipt", type=Path, required=True)
    launch.add_argument("--authorization-receipt", type=Path, required=True)
    launch.add_argument("--adapter-identity", required=True)
    launch.add_argument("--adapter-code", type=Path, required=True)
    launch.add_argument("--controller-handoff-receipt", type=Path, required=True)
    launch.add_argument("--host-execution-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "verify-github-key":
            result = validate_github_key_readback(_read_json(args.github_keys))
            if not result["ok"]:
                raise ValueError(result["errors"][0])
        else:
            handoff = _read_json(args.controller_handoff_receipt)
            if not isinstance(handoff, dict):
                raise ValueError("E_V250_CONTROLLER_HANDOFF_REQUIRED")
            result = launch_runtime_transition(
                stage=args.stage,
                source_commit=args.source_commit,
                source_tree=args.source_tree,
                project_size=args.project_size,
                route_facts_receipt_path=args.route_facts_receipt,
                derived_route_receipt_path=args.derived_route_receipt,
                route_receipt_path=args.route_receipt,
                authorization_receipt_path=args.authorization_receipt,
                adapter_identity=args.adapter_identity,
                adapter_code_path=args.adapter_code,
                controller_handoff_receipt=handoff,
                host_execution_id=args.host_execution_id,
            )
    except RuntimeChildFailure as exc:
        result = exc.parent_envelope()
        print(json.dumps(result, sort_keys=True))
        return 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "passed": False,
                    "error_code": str(exc),
                    "external_write_count": 0,
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
