#!/usr/bin/env python3
"""Goal Teams V2.36 protected Git snapshot and host-attestation primitives.

The snapshot API never accepts a caller-selected path list.  It constructs an
isolated Git index from every path tracked by the baseline or current index,
plus every non-ignored untracked path, and records the resulting Git tree.

The host-attestation and route-receipt APIs deliberately keep the trust key
outside evidence documents.  A host signs identity and derived route facts
with HMAC-SHA256.  V2.36 acceptance uses MAC-protected persistent challenge
state so replay is rejected across independent process calls.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, MutableSet


SNAPSHOT_RECEIPT_SCHEMA_VERSION = "goal-teams-v2.36-protected-git-tree-snapshot-v1"
HOST_ATTESTATION_SCHEMA_VERSION = "goal-teams-v2.36-agent-host-attestation-v1"
ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION = "goal-teams-v2.36-attested-identity-registry-v1"
PERSISTENT_CHALLENGE_STATE_SCHEMA_VERSION = "goal-teams-v2.36-persistent-challenge-state-v1"
HOST_ROUTE_RECEIPT_SCHEMA_VERSION = "goal-teams-v2.36-host-route-receipt-v1"
HMAC_ALGORITHM = "HMAC-SHA256"
IDENTITY_CORE_FIELDS = (
    "agent_type",
    "agent_run_id",
    "member_id",
    "display_name",
    "transport_handle",
)

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}$")
_FORBIDDEN_REGISTRY_KEYS = frozenset(
    {"trust_key", "hmac_key", "host_trust_key", "attestation_key", "secret_key"}
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "repository_fingerprint",
        "object_format",
        "content_mode",
        "baseline_ref",
        "baseline_commit",
        "baseline_tree",
        "snapshot_tree",
        "change_manifest",
        "change_manifest_sha256",
        "changed_paths",
        "untracked_paths",
        "tracked_path_count",
        "snapshot_entry_count",
        "repo_state_before",
        "repo_state_after",
        "created_at",
        "receipt_sha256",
    }
)
_ATTESTATION_FIELDS = frozenset(
    {
        "schema_version",
        "algorithm",
        "issuer",
        "run_id",
        "transport_handle",
        "nonce",
        "issued_at",
        "expires_at",
        "identity_core_sha256",
        "signature",
    }
)
_ROUTE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "algorithm",
        "issuer",
        "product_version",
        "actual_target_fingerprint",
        "actual_target_kind",
        "trusted_release_base",
        "task_type",
        "release",
        "policy_profile",
        "state_gate_profile",
        "execution_profile",
        "required_review_class",
        "gates",
        "gate_scopes",
        "execution_contract_sha256",
        "route_digest",
        "nonce",
        "issued_at",
        "expires_at",
        "signature",
    }
)
_CHALLENGE_STATE_FIELDS = frozenset(
    {"schema_version", "generation", "consumed_challenges", "state_mac"}
)
_CHALLENGE_RECORD_FIELDS = frozenset(
    {
        "challenge_sha256",
        "kind",
        "issuer",
        "proof_sha256",
        "consumed_at",
        "expires_at",
    }
)
_MAX_CHALLENGE_STATE_BYTES = 16 * 1024 * 1024
_MAX_CHALLENGE_RECORDS = 100_000


# Machine-readable schemas live beside the implementation so callers can
# validate without introducing a second schema loader into the V2.3 runtime.
SNAPSHOT_RECEIPT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": SNAPSHOT_RECEIPT_SCHEMA_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_RECEIPT_FIELDS),
    "properties": {
        "schema_version": {"const": SNAPSHOT_RECEIPT_SCHEMA_VERSION},
        "repository_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "object_format": {"enum": ["sha1", "sha256"]},
        "content_mode": {"const": "raw-worktree-bytes-no-filters"},
        "baseline_ref": {"type": "string", "minLength": 1},
        "baseline_commit": {"type": "string", "minLength": 40},
        "baseline_tree": {"type": "string", "minLength": 40},
        "snapshot_tree": {"type": "string", "minLength": 40},
        "change_manifest": {"type": "array"},
        "change_manifest_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "changed_paths": {"type": "array", "items": {"type": "string"}},
        "untracked_paths": {"type": "array", "items": {"type": "string"}},
        "tracked_path_count": {"type": "integer", "minimum": 0},
        "snapshot_entry_count": {"type": "integer", "minimum": 0},
        "repo_state_before": {"type": "object"},
        "repo_state_after": {"type": "object"},
        "created_at": {"type": "string", "format": "date-time"},
        "receipt_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

HOST_ATTESTATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": HOST_ATTESTATION_SCHEMA_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_ATTESTATION_FIELDS),
    "properties": {
        "schema_version": {"const": HOST_ATTESTATION_SCHEMA_VERSION},
        "algorithm": {"const": HMAC_ALGORITHM},
        "issuer": {"type": "string", "minLength": 1},
        "run_id": {"type": "string", "minLength": 1},
        "transport_handle": {"type": "string", "minLength": 1},
        "nonce": {"type": "string", "minLength": 1, "maxLength": 128},
        "issued_at": {"type": "string", "format": "date-time"},
        "expires_at": {"type": "string", "format": "date-time"},
        "identity_core_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "signature": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

HOST_ROUTE_RECEIPT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": HOST_ROUTE_RECEIPT_SCHEMA_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_ROUTE_RECEIPT_FIELDS),
    "properties": {
        "schema_version": {"const": HOST_ROUTE_RECEIPT_SCHEMA_VERSION},
        "algorithm": {"const": HMAC_ALGORITHM},
        "issuer": {"type": "string", "minLength": 1},
        "product_version": {"const": "V2.36"},
        "actual_target_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "actual_target_kind": {
            "enum": ["generic_project", "goal_teams_repository"]
        },
        "trusted_release_base": {
            "type": "string",
            "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
        },
        "task_type": {"type": "string", "minLength": 1},
        "release": {"type": "boolean"},
        "policy_profile": {"type": "string", "minLength": 1},
        "state_gate_profile": {"type": "string", "minLength": 1},
        "execution_profile": {
            "enum": ["lite", "standard", "full", "regulated"]
        },
        "required_review_class": {
            "enum": ["semantic", "comparison", "safety"]
        },
        "gates": {
            "type": "object",
            "minProperties": 15,
            "maxProperties": 15,
            "propertyNames": {
                "enum": [
                    "architecture", "completion_audit", "contract", "e2e",
                    "environment", "evidence", "full_regression",
                    "independent_review", "independent_tests", "integration",
                    "pixel_comparison", "release_evidence",
                    "targeted_regression", "targeted_validation", "tdd",
                ]
            },
            "additionalProperties": {
                "enum": ["required", "conditional", "not_required"]
            },
        },
        "gate_scopes": {
            "type": "object",
            "propertyNames": {
                "enum": [
                    "architecture", "completion_audit", "contract", "e2e",
                    "environment", "evidence", "full_regression",
                    "independent_review", "independent_tests", "integration",
                    "pixel_comparison", "release_evidence",
                    "targeted_regression", "targeted_validation", "tdd",
                ]
            },
            "additionalProperties": {"type": "string", "minLength": 1},
        },
        "execution_contract_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "route_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "nonce": {"type": "string", "minLength": 1, "maxLength": 128},
        "issued_at": {"type": "string", "format": "date-time"},
        "expires_at": {"type": "string", "format": "date-time"},
        "signature": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

PERSISTENT_CHALLENGE_STATE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PERSISTENT_CHALLENGE_STATE_SCHEMA_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": sorted(_CHALLENGE_STATE_FIELDS),
    "properties": {
        "schema_version": {"const": PERSISTENT_CHALLENGE_STATE_SCHEMA_VERSION},
        "generation": {"type": "integer", "minimum": 0},
        "consumed_challenges": {"type": "array", "maxItems": _MAX_CHALLENGE_RECORDS},
        "state_mac": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


class TrustContractError(Exception):
    """Internal fail-closed error carrying one stable public code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, "error_code": None, **data}


def _error(code: str, *errors: str, **data: Any) -> dict[str, Any]:
    return {"ok": False, "error_code": code, "errors": list(errors or (code,)), **data}


def _utc_text(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TrustContractError("E_V236_ATTESTATION_TIME")
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TrustContractError("E_V236_ATTESTATION_TIME")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise TrustContractError("E_V236_ATTESTATION_TIME") from exc
    if parsed.tzinfo is None:
        raise TrustContractError("E_V236_ATTESTATION_TIME")
    return parsed.astimezone(timezone.utc)


def _current_utc(value: datetime | None, error_code: str) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TrustContractError(error_code)
    return value.astimezone(timezone.utc)


def _git(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    extra_env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    if extra_env:
        environment.update(extra_env)
    process = subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    if check and process.returncode != 0:
        raise TrustContractError("E_V236_SNAPSHOT_GIT")
    return process


def _repository(root: Path | str) -> tuple[Path, Path, str]:
    requested = Path(root).absolute()
    if requested.is_symlink() or not requested.is_dir():
        raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY")
    requested = requested.resolve()
    top = _git(requested, "rev-parse", "--show-toplevel").stdout.rstrip(b"\n")
    try:
        top_path = Path(os.fsdecode(top)).resolve(strict=True)
    except (OSError, UnicodeError) as exc:
        raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY") from exc
    if top_path != requested:
        raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY")
    if _git(requested, "rev-parse", "--is-bare-repository").stdout.strip() != b"false":
        raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY")
    common_raw = os.fsdecode(_git(requested, "rev-parse", "--git-common-dir").stdout.strip())
    common = Path(common_raw)
    if not common.is_absolute():
        common = requested / common
    common = common.resolve(strict=True)
    object_format = os.fsdecode(
        _git(requested, "rev-parse", "--show-object-format").stdout.strip()
    )
    if object_format not in {"sha1", "sha256"}:
        raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY")
    return requested, common, object_format


def _safe_repo_path(value: str) -> bool:
    if not value or len(os.fsencode(value)) > 4096 or "\\" in value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 or 0xD800 <= ord(character) <= 0xDFFF for character in value):
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        return False
    parts = path.parts
    return bool(
        parts
        and all(
            part not in {"", ".", ".."}
            and part.lower() != ".git"
            and len(os.fsencode(part)) <= 255
            for part in parts
        )
    )


def _decode_path(raw: bytes) -> str:
    value = os.fsdecode(raw)
    if not _safe_repo_path(value):
        raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_PATH")
    return value


def _oid_valid(value: Any, object_format: str) -> bool:
    expected = 40 if object_format == "sha1" else 64
    return isinstance(value, str) and len(value) == expected and bool(re.fullmatch(r"[0-9a-f]+", value))


def _tree_entries(root: Path, tree: str, object_format: str) -> dict[str, dict[str, str]]:
    raw = _git(root, "ls-tree", "-rz", "--full-tree", tree).stdout
    entries: dict[str, dict[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_raw, object_type_raw, oid_raw = metadata.split(b" ", 2)
        except ValueError as exc:
            raise TrustContractError("E_V236_SNAPSHOT_GIT") from exc
        path = _decode_path(raw_path)
        mode = mode_raw.decode("ascii")
        object_type = object_type_raw.decode("ascii")
        oid = oid_raw.decode("ascii")
        if mode not in {"100644", "100755", "120000", "160000"}:
            raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_MODE")
        if object_type not in {"blob", "commit"} or not _oid_valid(oid, object_format):
            raise TrustContractError("E_V236_SNAPSHOT_GIT")
        if path in entries:
            raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_PATH")
        entries[path] = {"mode": mode, "object_id": oid}
    return entries


def _index_entries(root: Path, object_format: str) -> dict[str, dict[str, str]]:
    raw = _git(root, "ls-files", "--stage", "-z").stdout
    entries: dict[str, dict[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_raw, oid_raw, stage_raw = metadata.split(b" ", 2)
        except ValueError as exc:
            raise TrustContractError("E_V236_SNAPSHOT_INDEX") from exc
        path = _decode_path(raw_path)
        mode = mode_raw.decode("ascii")
        oid = oid_raw.decode("ascii")
        if stage_raw != b"0":
            raise TrustContractError("E_V236_SNAPSHOT_UNMERGED_INDEX")
        if mode not in {"100644", "100755", "120000", "160000"} or not _oid_valid(oid, object_format):
            raise TrustContractError("E_V236_SNAPSHOT_INDEX")
        if mode == "120000":
            raise TrustContractError("E_V236_SNAPSHOT_SYMLINK")
        if mode == "160000":
            raise TrustContractError("E_V236_SNAPSHOT_SUBMODULE")
        if path in entries:
            raise TrustContractError("E_V236_SNAPSHOT_UNMERGED_INDEX")
        entries[path] = {"mode": mode, "object_id": oid}
    return entries


def _untracked_paths(root: Path) -> list[str]:
    raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    paths = [_decode_path(item) for item in raw.split(b"\0") if item]
    if len(paths) != len(set(paths)):
        raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_PATH")
    return sorted(paths)


def _index_state(root: Path) -> dict[str, Any]:
    raw_path = os.fsdecode(_git(root, "rev-parse", "--git-path", "index").stdout.strip())
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    if path.is_symlink():
        raise TrustContractError("E_V236_SNAPSHOT_INDEX")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return {"exists": False, "sha256": None, "size": 0}
    except OSError as exc:
        raise TrustContractError("E_V236_SNAPSHOT_INDEX") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise TrustContractError("E_V236_SNAPSHOT_INDEX")
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY_DRIFT")
        return {
            "exists": True,
            "sha256": digest.hexdigest(),
            "size": metadata.st_size,
        }
    finally:
        os.close(descriptor)


def _repo_state(root: Path) -> dict[str, Any]:
    head_process = _git(root, "rev-parse", "--verify", "HEAD", check=False)
    if head_process.returncode != 0:
        raise TrustContractError("E_V236_SNAPSHOT_BASELINE")
    head_oid = os.fsdecode(head_process.stdout.strip())
    symbolic = _git(root, "symbolic-ref", "-q", "HEAD", check=False)
    head_ref = os.fsdecode(symbolic.stdout.strip()) if symbolic.returncode == 0 else None
    refs = sorted(
        line for line in _git(root, "for-each-ref", "--format=%(refname)%00%(objectname)").stdout.splitlines() if line
    )
    return {
        "head_oid": head_oid,
        "head_ref": head_ref,
        "refs_sha256": _sha256(b"\n".join(refs)),
        "refs_count": len(refs),
        "index": _index_state(root),
        "objects": _object_store_state(root),
    }


def _object_store_state(root: Path) -> dict[str, Any]:
    raw = os.fsdecode(_git(root, "rev-parse", "--git-path", "objects").stdout.strip())
    object_root = Path(raw)
    if not object_root.is_absolute():
        object_root = root / object_root
    object_root = object_root.resolve(strict=True)
    records: list[dict[str, Any]] = []
    for directory, names, files in os.walk(object_root, topdown=True, followlinks=False):
        names.sort()
        files.sort()
        directory_path = Path(directory)
        for name in list(names):
            path = directory_path / name
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise TrustContractError("E_V236_SNAPSHOT_OBJECT_STORE")
        for name in files:
            path = directory_path / name
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise TrustContractError("E_V236_SNAPSHOT_OBJECT_STORE")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                before = os.fstat(descriptor)
                digest = hashlib.sha256()
                while True:
                    block = os.read(descriptor, 1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            metadata_identity = (metadata.st_dev, metadata.st_ino, metadata.st_size)
            before_identity = (before.st_dev, before.st_ino, before.st_size)
            after_identity = (after.st_dev, after.st_ino, after.st_size)
            if metadata_identity != before_identity or before_identity != after_identity:
                raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY_DRIFT")
            records.append(
                {
                    "path": path.relative_to(object_root).as_posix(),
                    "size": metadata.st_size,
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "sha256": digest.hexdigest(),
                }
            )
    return {"file_count": len(records), "fingerprint": _sha256(_canonical_bytes(records))}


def _read_regular_file(root: Path, relative: str) -> tuple[bytes, int] | None:
    """Read one path through no-follow directory descriptors."""

    parts = PurePosixPath(relative).parts
    if os.open not in os.supports_dir_fd:
        return _read_regular_file_without_openat(root, relative)
    flags_directory = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags_directory)
    try:
        for component in parts[:-1]:
            try:
                next_descriptor = os.open(component, flags_directory, dir_fd=descriptor)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise TrustContractError("E_V236_SNAPSHOT_SYMLINK") from exc
            os.close(descriptor)
            descriptor = next_descriptor
        try:
            file_descriptor = os.open(
                parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor
            )
        except FileNotFoundError:
            return None
        except IsADirectoryError:
            return None
        except OSError as exc:
            raise TrustContractError("E_V236_SNAPSHOT_SYMLINK") from exc
        try:
            before = os.fstat(file_descriptor)
            if stat.S_ISLNK(before.st_mode):
                raise TrustContractError("E_V236_SNAPSHOT_SYMLINK")
            if not stat.S_ISREG(before.st_mode):
                raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_MODE")
            chunks: list[bytes] = []
            while True:
                block = os.read(file_descriptor, 1024 * 1024)
                if not block:
                    break
                chunks.append(block)
            after = os.fstat(file_descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                stat.S_IMODE(before.st_mode),
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                stat.S_IMODE(after.st_mode),
            ):
                raise TrustContractError("E_V236_SNAPSHOT_WORKTREE_DRIFT")
            return b"".join(chunks), before.st_mode
        finally:
            os.close(file_descriptor)
    finally:
        os.close(descriptor)


def _read_regular_file_without_openat(root: Path, relative: str) -> tuple[bytes, int] | None:
    """Portable no-symlink fallback for Python builds without ``openat``."""

    target = root.joinpath(*PurePosixPath(relative).parts)
    ancestor_state: list[tuple[Path, tuple[int, int, int]]] = []
    current = root
    try:
        for component in PurePosixPath(relative).parts[:-1]:
            current = current / component
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise TrustContractError("E_V236_SNAPSHOT_SYMLINK")
            ancestor_state.append(
                (current, (metadata.st_dev, metadata.st_ino, stat.S_IMODE(metadata.st_mode)))
            )
        target_metadata = os.lstat(target)
    except FileNotFoundError:
        return None
    if stat.S_ISDIR(target_metadata.st_mode):
        return None
    if stat.S_ISLNK(target_metadata.st_mode):
        raise TrustContractError("E_V236_SNAPSHOT_SYMLINK")
    if not stat.S_ISREG(target_metadata.st_mode):
        raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_MODE")
    try:
        if not _is_relative_to(target.resolve(strict=True), root):
            raise TrustContractError("E_V236_SNAPSHOT_SYMLINK")
        descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise TrustContractError("E_V236_SNAPSHOT_SYMLINK") from exc
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            stat.S_IMODE(before.st_mode),
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            stat.S_IMODE(after.st_mode),
        ):
            raise TrustContractError("E_V236_SNAPSHOT_WORKTREE_DRIFT")
    finally:
        os.close(descriptor)
    for path, expected in ancestor_state:
        metadata = os.lstat(path)
        observed = (metadata.st_dev, metadata.st_ino, stat.S_IMODE(metadata.st_mode))
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode) or observed != expected:
            raise TrustContractError("E_V236_SNAPSHOT_WORKTREE_DRIFT")
    return b"".join(chunks), before.st_mode


def _discover(
    root: Path, baseline_entries: dict[str, dict[str, str]], object_format: str
) -> tuple[dict[str, dict[str, str]], list[str], list[str]]:
    if _git(root, "config", "--bool", "core.sparseCheckout", check=False).stdout.strip() == b"true":
        raise TrustContractError("E_V236_SNAPSHOT_SPARSE_WORKTREE")
    current_index = _index_entries(root, object_format)
    untracked = _untracked_paths(root)
    all_paths = sorted(set(baseline_entries) | set(current_index) | set(untracked))
    return current_index, untracked, all_paths


def _blob_oid(content: bytes, object_format: str) -> str:
    constructor = hashlib.sha1 if object_format == "sha1" else hashlib.sha256
    digest = constructor()
    digest.update(f"blob {len(content)}\0".encode("ascii"))
    digest.update(content)
    return digest.hexdigest()


def _scan_worktree(
    root: Path,
    paths: Iterable[str],
    object_format: str,
    *,
    payload_root: Path | None = None,
) -> tuple[dict[str, dict[str, str]], dict[str, Path]]:
    entries: dict[str, dict[str, str]] = {}
    payloads: dict[str, Path] = {}
    for sequence, relative in enumerate(paths):
        value = _read_regular_file(root, relative)
        if value is None:
            continue
        content, mode_bits = value
        oid = _blob_oid(content, object_format)
        mode = "100755" if mode_bits & 0o111 else "100644"
        entries[relative] = {"mode": mode, "object_id": oid}
        if payload_root is not None:
            payload_path = payload_root / f"{sequence:012d}.blob"
            descriptor = os.open(payload_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            payloads[relative] = payload_path
    return entries, payloads


def _write_isolated_tree(
    root: Path,
    entries: dict[str, dict[str, str]],
    payloads: dict[str, Path],
    object_format: str,
    main_object_dir: Path,
) -> str:
    with tempfile.TemporaryDirectory(prefix="goalteams-v236-index-") as directory:
        index_path = Path(directory) / "isolated.index"
        object_path = Path(directory) / "objects"
        object_path.mkdir(mode=0o700)
        hash_environment = {
            "GIT_INDEX_FILE": str(index_path),
            "GIT_OBJECT_DIRECTORY": str(object_path),
        }
        read_environment = {
            **hash_environment,
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(main_object_dir),
        }
        ordered_paths = sorted(entries)
        if ordered_paths:
            path_input = b"".join(os.fsencode(str(payloads[path])) + b"\n" for path in ordered_paths)
            observed = [
                os.fsdecode(line)
                for line in _git(
                    root,
                    "hash-object",
                    "-w",
                    "--no-filters",
                    "--stdin-paths",
                    input_bytes=path_input,
                    extra_env=hash_environment,
                ).stdout.splitlines()
            ]
            expected = [entries[path]["object_id"] for path in ordered_paths]
            if observed != expected:
                raise TrustContractError("E_V236_SNAPSHOT_WORKTREE_DRIFT")
        # Alternates are exposed only to this read-only initialization.  Git
        # may "freshen" alternate loose objects during a write, so every
        # object-producing command below intentionally sees only the isolated
        # object directory.
        _git(root, "read-tree", "--empty", extra_env=read_environment)
        payload = b"".join(
            f"{entry['mode']} {entry['object_id']}\t".encode("ascii")
            + os.fsencode(path)
            + b"\0"
            for path, entry in sorted(entries.items())
        )
        if payload:
            _git(
                root,
                "update-index",
                "-z",
                "--index-info",
                input_bytes=payload,
                extra_env=hash_environment,
            )
        tree = os.fsdecode(_git(root, "write-tree", extra_env=hash_environment).stdout.strip())
    if not _oid_valid(tree, object_format):
        raise TrustContractError("E_V236_SNAPSHOT_GIT")
    return tree


def _change_manifest(
    before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        change_type = "added" if old is None else "deleted" if new is None else "modified"
        manifest.append({"path": path, "change_type": change_type, "before": old, "after": new})
    return manifest


def _resolve_baseline(root: Path, baseline: str, object_format: str) -> tuple[str, str]:
    if not isinstance(baseline, str) or not baseline or len(baseline) > 256 or "\x00" in baseline:
        raise TrustContractError("E_V236_SNAPSHOT_BASELINE")
    commit_process = _git(root, "rev-parse", "--verify", f"{baseline}^{{commit}}", check=False)
    if commit_process.returncode != 0:
        raise TrustContractError("E_V236_SNAPSHOT_BASELINE")
    commit = os.fsdecode(commit_process.stdout.strip())
    ancestor = _git(root, "merge-base", "--is-ancestor", commit, "HEAD", check=False)
    if ancestor.returncode != 0:
        raise TrustContractError("E_V236_SNAPSHOT_BASELINE_NOT_ANCESTOR")
    tree = os.fsdecode(_git(root, "rev-parse", "--verify", f"{commit}^{{tree}}").stdout.strip())
    if not _oid_valid(commit, object_format) or not _oid_valid(tree, object_format):
        raise TrustContractError("E_V236_SNAPSHOT_BASELINE")
    return commit, tree


def _build_tree(
    root: Path, baseline_tree: str, object_format: str, main_object_dir: Path
) -> tuple[str, dict[str, dict[str, str]], list[str], int]:
    baseline_entries = _tree_entries(root, baseline_tree, object_format)
    current_index, untracked, paths = _discover(root, baseline_entries, object_format)
    first_scan, _ = _scan_worktree(root, paths, object_format)
    with tempfile.TemporaryDirectory(prefix="goalteams-v236-payload-") as payload_directory:
        second_index, second_untracked, second_paths = _discover(root, baseline_entries, object_format)
        second_scan, payloads = _scan_worktree(
            root,
            second_paths,
            object_format,
            payload_root=Path(payload_directory),
        )
        if (
            current_index != second_index
            or untracked != second_untracked
            or paths != second_paths
            or first_scan != second_scan
        ):
            raise TrustContractError("E_V236_SNAPSHOT_WORKTREE_DRIFT")
        tree = _write_isolated_tree(
            root, first_scan, payloads, object_format, main_object_dir
        )
    return tree, first_scan, untracked, len(set(baseline_entries) | set(current_index))


def _repository_fingerprint(common_dir: Path, object_format: str) -> str:
    return _sha256(_canonical_bytes({"git_common_dir": str(common_dir), "object_format": object_format}))


def _receipt_digest(receipt: dict[str, Any]) -> str:
    return _sha256(_canonical_bytes({key: value for key, value in receipt.items() if key != "receipt_sha256"}))


def _atomic_receipt(path: Path, root: Path, receipt: dict[str, Any]) -> None:
    target = path.absolute()
    try:
        if _is_relative_to(target.resolve(strict=False), root):
            raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_PATH")
    except ValueError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_PATH")
    payload = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_PATH") from exc
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_protected_git_tree_snapshot(
    repo_root: Path | str,
    *,
    baseline: str = "HEAD",
    receipt_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create a complete baseline-to-worktree tree without mutating HEAD/refs/index."""

    try:
        root, common_dir, object_format = _repository(repo_root)
        state_before = _repo_state(root)
        baseline_commit, baseline_tree = _resolve_baseline(root, baseline, object_format)
        baseline_entries = _tree_entries(root, baseline_tree, object_format)
        snapshot_tree, snapshot_entries, untracked, tracked_count = _build_tree(
            root, baseline_tree, object_format, common_dir / "objects"
        )
        state_after = _repo_state(root)
        if state_before != state_after:
            raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY_DRIFT")
        manifest = _change_manifest(baseline_entries, snapshot_entries)
        if not manifest:
            raise TrustContractError("E_V236_SNAPSHOT_EMPTY_DELTA")
        receipt: dict[str, Any] = {
            "schema_version": SNAPSHOT_RECEIPT_SCHEMA_VERSION,
            "repository_fingerprint": _repository_fingerprint(common_dir, object_format),
            "object_format": object_format,
            "content_mode": "raw-worktree-bytes-no-filters",
            "baseline_ref": baseline,
            "baseline_commit": baseline_commit,
            "baseline_tree": baseline_tree,
            "snapshot_tree": snapshot_tree,
            "change_manifest": manifest,
            "change_manifest_sha256": _sha256(_canonical_bytes(manifest)),
            "changed_paths": [entry["path"] for entry in manifest],
            "untracked_paths": untracked,
            "tracked_path_count": tracked_count,
            "snapshot_entry_count": len(snapshot_entries),
            "repo_state_before": state_before,
            "repo_state_after": state_after,
            "created_at": _utc_text(now or datetime.now(timezone.utc)),
        }
        receipt["receipt_sha256"] = _receipt_digest(receipt)
        if receipt_path is not None:
            _atomic_receipt(Path(receipt_path), root, receipt)
        return _ok(receipt=receipt, mutation_count=1 if receipt_path is not None else 0)
    except TrustContractError as exc:
        return _error(exc.code, mutation_count=0)
    except (OSError, UnicodeError, ValueError) as exc:
        return _error("E_V236_SNAPSHOT_IO", type(exc).__name__, mutation_count=0)


def _validate_receipt_shape(receipt: Any, object_format: str) -> dict[str, Any]:
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if receipt.get("schema_version") != SNAPSHOT_RECEIPT_SCHEMA_VERSION:
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if receipt.get("object_format") != object_format or receipt.get("content_mode") != "raw-worktree-bytes-no-filters":
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    for key in ("baseline_commit", "baseline_tree", "snapshot_tree"):
        if not _oid_valid(receipt.get(key), object_format):
            raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if not isinstance(receipt.get("baseline_ref"), str) or not receipt["baseline_ref"]:
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    for key in ("repository_fingerprint", "change_manifest_sha256", "receipt_sha256"):
        if not isinstance(receipt.get(key), str) or not _HEX_SHA256.fullmatch(receipt[key]):
            raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if not isinstance(receipt.get("tracked_path_count"), int) or receipt["tracked_path_count"] < 0:
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if not isinstance(receipt.get("snapshot_entry_count"), int) or receipt["snapshot_entry_count"] < 0:
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    _parse_utc(receipt.get("created_at"))
    manifest = receipt.get("change_manifest")
    changed = receipt.get("changed_paths")
    untracked = receipt.get("untracked_paths")
    if not isinstance(manifest, list) or not isinstance(changed, list) or not isinstance(untracked, list):
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if any(not isinstance(path, str) or not _safe_repo_path(path) for path in [*changed, *untracked]):
        raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_PATH")
    if changed != sorted(set(changed)) or untracked != sorted(set(untracked)):
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    for entry in manifest:
        if not isinstance(entry, dict) or set(entry) != {"path", "change_type", "before", "after"}:
            raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
        if not isinstance(entry.get("path"), str) or not _safe_repo_path(entry["path"]):
            raise TrustContractError("E_V236_SNAPSHOT_UNSAFE_PATH")
        if entry.get("change_type") not in {"added", "modified", "deleted"}:
            raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if changed != [entry["path"] for entry in manifest]:
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_SCHEMA")
    if not manifest:
        raise TrustContractError("E_V236_SNAPSHOT_EMPTY_DELTA")
    if receipt["change_manifest_sha256"] != _sha256(_canonical_bytes(manifest)):
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_DIGEST")
    if receipt["receipt_sha256"] != _receipt_digest(receipt):
        raise TrustContractError("E_V236_SNAPSHOT_RECEIPT_DIGEST")
    return receipt


def validate_protected_git_tree_snapshot(
    repo_root: Path | str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild and compare the full current worktree against one receipt."""

    try:
        root, common_dir, object_format = _repository(repo_root)
        candidate = _validate_receipt_shape(copy.deepcopy(receipt), object_format)
        if candidate["repository_fingerprint"] != _repository_fingerprint(common_dir, object_format):
            raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY_MISMATCH")
        state_before = _repo_state(root)
        if state_before != candidate["repo_state_after"]:
            raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY_DRIFT")
        if os.fsdecode(_git(root, "cat-file", "-t", candidate["baseline_commit"]).stdout.strip()) != "commit":
            raise TrustContractError("E_V236_SNAPSHOT_BASELINE")
        if os.fsdecode(_git(root, "cat-file", "-t", candidate["baseline_tree"]).stdout.strip()) != "tree":
            raise TrustContractError("E_V236_SNAPSHOT_BASELINE")
        if _git(
            root,
            "merge-base",
            "--is-ancestor",
            candidate["baseline_commit"],
            "HEAD",
            check=False,
        ).returncode != 0:
            raise TrustContractError("E_V236_SNAPSHOT_BASELINE_NOT_ANCESTOR")
        expected_baseline_tree = os.fsdecode(
            _git(root, "rev-parse", "--verify", f"{candidate['baseline_commit']}^{{tree}}").stdout.strip()
        )
        if expected_baseline_tree != candidate["baseline_tree"]:
            raise TrustContractError("E_V236_SNAPSHOT_BASELINE")
        baseline_entries = _tree_entries(root, candidate["baseline_tree"], object_format)
        rebuilt_tree, rebuilt_entries, untracked, tracked_count = _build_tree(
            root, candidate["baseline_tree"], object_format, common_dir / "objects"
        )
        expected_manifest = _change_manifest(baseline_entries, rebuilt_entries)
        state_after = _repo_state(root)
        if state_before != state_after:
            raise TrustContractError("E_V236_SNAPSHOT_REPOSITORY_DRIFT")
        if (
            rebuilt_tree != candidate["snapshot_tree"]
            or expected_manifest != candidate["change_manifest"]
            or untracked != candidate["untracked_paths"]
            or tracked_count != candidate["tracked_path_count"]
            or len(rebuilt_entries) != candidate["snapshot_entry_count"]
        ):
            raise TrustContractError("E_V236_SNAPSHOT_INCOMPLETE")
        return _ok(
            snapshot_tree=rebuilt_tree,
            changed_paths=list(candidate["changed_paths"]),
            untracked_paths=list(candidate["untracked_paths"]),
            mutation_count=0,
        )
    except TrustContractError as exc:
        return _error(exc.code, mutation_count=0)
    except (OSError, UnicodeError, ValueError) as exc:
        return _error("E_V236_SNAPSHOT_IO", type(exc).__name__, mutation_count=0)


def identity_core(identity: Any) -> dict[str, str]:
    if not isinstance(identity, dict):
        raise TrustContractError("E_V236_IDENTITY")
    core: dict[str, str] = {}
    for field in IDENTITY_CORE_FIELDS:
        value = identity.get(field)
        if not isinstance(value, str) or not value.strip():
            raise TrustContractError("E_V236_IDENTITY")
        core[field] = value
    if not _SAFE_TOKEN.fullmatch(core["agent_run_id"]) or not _SAFE_TOKEN.fullmatch(core["transport_handle"]):
        raise TrustContractError("E_V236_IDENTITY")
    if core["agent_run_id"] == core["member_id"] or core["transport_handle"] in {
        core["member_id"],
        core["display_name"],
    }:
        raise TrustContractError("E_V236_IDENTITY")
    return core


def identity_core_sha256(identity: Any) -> str:
    return _sha256(_canonical_bytes(identity_core(identity)))


def _trust_key(value: Any) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TrustContractError("E_V236_TRUST_KEY")
    key = bytes(value)
    if len(key) < 32:
        raise TrustContractError("E_V236_TRUST_KEY")
    return key


def _load_v236_policy() -> Any:
    """Load the sibling policy module even when this file is loaded by path."""

    module = getattr(_load_v236_policy, "_module", None)
    if module is not None:
        return module
    path = Path(__file__).resolve().with_name("v235_policy.py")
    spec = importlib.util.spec_from_file_location("_goalteams_v236_trust_policy", path)
    if spec is None or spec.loader is None:
        raise TrustContractError("E_V236_ROUTE_POLICY")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError) as exc:
        raise TrustContractError("E_V236_ROUTE_POLICY") from exc
    setattr(_load_v236_policy, "_module", module)
    return module


def _state_mac_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "state_mac"}


def _state_mac(state: dict[str, Any], key: bytes) -> str:
    domain = b"goal-teams-v2.36-persistent-challenge-state\0"
    return hmac.new(key, domain + _canonical_bytes(_state_mac_payload(state)), hashlib.sha256).hexdigest()


def _new_challenge_state(key: bytes) -> dict[str, Any]:
    state: dict[str, Any] = {
        "schema_version": PERSISTENT_CHALLENGE_STATE_SCHEMA_VERSION,
        "generation": 0,
        "consumed_challenges": [],
    }
    state["state_mac"] = _state_mac(state, key)
    return state


def _state_location(value: Path | str) -> tuple[Path, str]:
    try:
        path = Path(value)
    except TypeError as exc:
        raise TrustContractError("E_V236_REPLAY_STATE_PATH") from exc
    if not path.is_absolute() or path.name in {"", ".", ".."} or len(os.fsencode(path.name)) > 255:
        raise TrustContractError("E_V236_REPLAY_STATE_PATH")
    parent = path.parent.absolute()
    try:
        resolved_parent = parent.resolve(strict=True)
    except OSError as exc:
        raise TrustContractError("E_V236_REPLAY_STATE_PATH") from exc
    # Reject a caller-controlled symlink as the immediate state directory.  A
    # platform may expose stable system aliases such as macOS ``/var``;
    # operate on the resolved directory descriptor so those aliases cannot be
    # swapped after validation.
    if parent.is_symlink():
        raise TrustContractError("E_V236_REPLAY_STATE_UNSAFE")
    parent = resolved_parent
    path = parent / path.name
    metadata = os.stat(parent, follow_symlinks=False)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise TrustContractError("E_V236_REPLAY_STATE_UNSAFE")
    try:
        state_metadata = os.lstat(path)
    except FileNotFoundError:
        state_metadata = None
    if state_metadata is not None and (
        stat.S_ISLNK(state_metadata.st_mode)
        or not stat.S_ISREG(state_metadata.st_mode)
        or state_metadata.st_nlink != 1
        or stat.S_IMODE(state_metadata.st_mode) != 0o600
        or (hasattr(os, "getuid") and state_metadata.st_uid != os.getuid())
    ):
        raise TrustContractError("E_V236_REPLAY_STATE_UNSAFE")
    return parent, path.name


def _validate_state_descriptor(descriptor: int) -> os.stat_result:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        raise TrustContractError("E_V236_REPLAY_STATE_UNSAFE")
    return metadata


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _validate_challenge_state(state: Any, key: bytes) -> dict[str, Any]:
    if not isinstance(state, dict) or set(state) != _CHALLENGE_STATE_FIELDS:
        raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
    if state.get("schema_version") != PERSISTENT_CHALLENGE_STATE_SCHEMA_VERSION:
        raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
    generation = state.get("generation")
    records = state.get("consumed_challenges")
    state_mac = state.get("state_mac")
    if (
        not isinstance(generation, int)
        or generation < 0
        or not isinstance(records, list)
        or len(records) > _MAX_CHALLENGE_RECORDS
        or not isinstance(state_mac, str)
        or not _HEX_SHA256.fullmatch(state_mac)
    ):
        raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
    previous = ""
    for record in records:
        if not isinstance(record, dict) or set(record) != _CHALLENGE_RECORD_FIELDS:
            raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
        if (
            not isinstance(record.get("challenge_sha256"), str)
            or not _HEX_SHA256.fullmatch(record["challenge_sha256"])
            or record["challenge_sha256"] <= previous
            or record.get("kind") not in {"host_attestation", "route_receipt"}
            or not isinstance(record.get("issuer"), str)
            or not _SAFE_TOKEN.fullmatch(record["issuer"])
            or not isinstance(record.get("proof_sha256"), str)
            or not _HEX_SHA256.fullmatch(record["proof_sha256"])
        ):
            raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
        try:
            consumed = _parse_utc(record.get("consumed_at"))
            expires = _parse_utc(record.get("expires_at"))
        except TrustContractError as exc:
            raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA") from exc
        if expires <= consumed:
            raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
        previous = record["challenge_sha256"]
    if not hmac.compare_digest(state_mac, _state_mac(state, key)):
        raise TrustContractError("E_V236_REPLAY_STATE_MAC")
    return state


def _read_challenge_state(parent_fd: int, name: str, key: bytes) -> dict[str, Any]:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        return _new_challenge_state(key)
    except OSError as exc:
        raise TrustContractError("E_V236_REPLAY_STATE_UNSAFE") from exc
    try:
        before = _validate_state_descriptor(descriptor)
        if before.st_size > _MAX_CHALLENGE_STATE_BYTES:
            raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
        chunks: list[bytes] = []
        remaining = _MAX_CHALLENGE_STATE_BYTES + 1
        while remaining:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        if remaining == 0 and os.read(descriptor, 1):
            raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA")
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise TrustContractError("E_V236_REPLAY_STATE_DRIFT")
    finally:
        os.close(descriptor)
    try:
        state = json.loads(b"".join(chunks).decode("utf-8"), object_pairs_hook=_strict_json_object)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise TrustContractError("E_V236_REPLAY_STATE_SCHEMA") from exc
    return _validate_challenge_state(state, key)


def _write_challenge_state(parent_fd: int, name: str, state: dict[str, Any]) -> None:
    payload = json.dumps(state, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > _MAX_CHALLENGE_STATE_BYTES:
        raise TrustContractError("E_V236_REPLAY_STATE_CAPACITY")
    temporary = f".{name}.tmp-{os.getpid()}-{os.urandom(8).hex()}"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        _validate_state_descriptor(descriptor)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise TrustContractError("E_V236_REPLAY_STATE_IO")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
    except TrustContractError:
        raise
    except OSError as exc:
        raise TrustContractError("E_V236_REPLAY_STATE_IO") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _challenge_record(
    *,
    kind: str,
    issuer: str,
    nonce: str,
    proof: dict[str, Any],
    consumed_at: datetime,
    expires_at: str,
    trust_key: bytes,
) -> dict[str, Any]:
    # The nonce is deliberately represented only by a keyed challenge digest
    # in persistent state.  The trust key is never serialized.
    challenge = hmac.new(
        trust_key,
        b"goal-teams-v2.36-challenge\0"
        + _canonical_bytes({"issuer": issuer, "nonce": nonce}),
        hashlib.sha256,
    ).hexdigest()
    return {
        "challenge_sha256": challenge,
        "kind": kind,
        "issuer": issuer,
        "proof_sha256": _sha256(_canonical_bytes(proof)),
        "consumed_at": _utc_text(consumed_at),
        "expires_at": expires_at,
    }


def _consume_persistent_challenges(
    state_path: Path | str,
    challenges: list[dict[str, Any]],
    *,
    trust_key: bytes,
    replay_error: str,
) -> dict[str, Any]:
    """Atomically check and consume one or more already-verified challenges."""

    try:
        key = _trust_key(trust_key)
        if not challenges:
            raise TrustContractError("E_V236_REPLAY_STATE_CHALLENGE")
        incoming: dict[str, dict[str, Any]] = {}
        for record in challenges:
            if not isinstance(record, dict) or set(record) != _CHALLENGE_RECORD_FIELDS:
                raise TrustContractError("E_V236_REPLAY_STATE_CHALLENGE")
            challenge = record.get("challenge_sha256")
            if not isinstance(challenge, str) or not _HEX_SHA256.fullmatch(challenge):
                raise TrustContractError("E_V236_REPLAY_STATE_CHALLENGE")
            if challenge in incoming:
                raise TrustContractError(replay_error)
            incoming[challenge] = record
        parent, name = _state_location(state_path)
        parent_fd = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            lock_name = f".{name}.lock"
            try:
                lock_fd = os.open(
                    lock_name,
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise TrustContractError("E_V236_REPLAY_STATE_UNSAFE") from exc
            try:
                _validate_state_descriptor(lock_fd)
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise TrustContractError("E_V236_REPLAY_STATE_BUSY") from exc
                state = _read_challenge_state(parent_fd, name, key)
                existing = {
                    record["challenge_sha256"] for record in state["consumed_challenges"]
                }
                if existing.intersection(incoming):
                    raise TrustContractError(replay_error)
                if len(existing) + len(incoming) > _MAX_CHALLENGE_RECORDS:
                    raise TrustContractError("E_V236_REPLAY_STATE_CAPACITY")
                state["consumed_challenges"] = sorted(
                    [*state["consumed_challenges"], *incoming.values()],
                    key=lambda item: item["challenge_sha256"],
                )
                state["generation"] += 1
                state["state_mac"] = _state_mac(state, key)
                _write_challenge_state(parent_fd, name, state)
                state_digest = _sha256(_canonical_bytes(state))
            finally:
                os.close(lock_fd)
        finally:
            os.close(parent_fd)
        return _ok(
            state_generation=state["generation"],
            state_sha256=state_digest,
            consumed_challenge_sha256=sorted(incoming),
            persistent_replay_protection=True,
        )
    except TrustContractError as exc:
        return _error(exc.code, persistent_replay_protection=False)
    except (OSError, UnicodeError, ValueError) as exc:
        return _error(
            "E_V236_REPLAY_STATE_IO",
            type(exc).__name__,
            persistent_replay_protection=False,
        )


def _attestation_payload(attestation: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in attestation.items() if key != "signature"}


def issue_agent_host_attestation(
    identity: dict[str, Any],
    *,
    trust_key: bytes,
    issuer: str,
    nonce: str,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Sign one identity.  The returned document never contains ``trust_key``."""

    try:
        key = _trust_key(trust_key)
        core = identity_core(identity)
        if not isinstance(issuer, str) or not _SAFE_TOKEN.fullmatch(issuer):
            raise TrustContractError("E_V236_ATTESTATION_ISSUER")
        if not isinstance(nonce, str) or not nonce or len(nonce) > 128 or not _SAFE_TOKEN.fullmatch(nonce):
            raise TrustContractError("E_V236_ATTESTATION_NONCE")
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise TrustContractError("E_V236_ATTESTATION_TIME")
        issued = issued_at or datetime.now(timezone.utc)
        expires = expires_at or (issued + timedelta(seconds=ttl_seconds))
        issued_text = _utc_text(issued)
        expires_text = _utc_text(expires)
        if _parse_utc(expires_text) <= _parse_utc(issued_text):
            raise TrustContractError("E_V236_ATTESTATION_TIME")
        payload: dict[str, Any] = {
            "schema_version": HOST_ATTESTATION_SCHEMA_VERSION,
            "algorithm": HMAC_ALGORITHM,
            "issuer": issuer,
            "run_id": core["agent_run_id"],
            "transport_handle": core["transport_handle"],
            "nonce": nonce,
            "issued_at": issued_text,
            "expires_at": expires_text,
            "identity_core_sha256": _sha256(_canonical_bytes(core)),
        }
        attestation = {
            **payload,
            "signature": hmac.new(key, _canonical_bytes(payload), hashlib.sha256).hexdigest(),
        }
        return _ok(attestation=attestation)
    except TrustContractError as exc:
        return _error(exc.code)


def verify_agent_host_attestation(
    identity: dict[str, Any],
    attestation: dict[str, Any],
    *,
    trust_key: bytes,
    expected_issuer: str,
    now: datetime | None = None,
    used_nonces: MutableSet[str] | None = None,
    clock_skew_seconds: int = 30,
) -> dict[str, Any]:
    """Verify one host proof and consume its nonce only after full success."""

    try:
        key = _trust_key(trust_key)
        core = identity_core(identity)
        if not isinstance(attestation, dict) or set(attestation) != _ATTESTATION_FIELDS:
            raise TrustContractError("E_V236_ATTESTATION_SCHEMA")
        if (
            attestation.get("schema_version") != HOST_ATTESTATION_SCHEMA_VERSION
            or attestation.get("algorithm") != HMAC_ALGORITHM
        ):
            raise TrustContractError("E_V236_ATTESTATION_SCHEMA")
        if not isinstance(expected_issuer, str) or attestation.get("issuer") != expected_issuer:
            raise TrustContractError("E_V236_ATTESTATION_ISSUER")
        if attestation.get("run_id") != core["agent_run_id"]:
            raise TrustContractError("E_V236_ATTESTATION_RUN")
        if attestation.get("transport_handle") != core["transport_handle"]:
            raise TrustContractError("E_V236_ATTESTATION_TRANSPORT")
        nonce = attestation.get("nonce")
        if not isinstance(nonce, str) or not nonce or len(nonce) > 128 or not _SAFE_TOKEN.fullmatch(nonce):
            raise TrustContractError("E_V236_ATTESTATION_NONCE")
        if used_nonces is not None and nonce in used_nonces:
            raise TrustContractError("E_V236_ATTESTATION_NONCE_REPLAY")
        identity_digest = _sha256(_canonical_bytes(core))
        if not hmac.compare_digest(str(attestation.get("identity_core_sha256", "")), identity_digest):
            raise TrustContractError("E_V236_ATTESTATION_IDENTITY")
        signature = attestation.get("signature")
        if not isinstance(signature, str) or not _HEX_SHA256.fullmatch(signature):
            raise TrustContractError("E_V236_ATTESTATION_SIGNATURE")
        expected_signature = hmac.new(
            key, _canonical_bytes(_attestation_payload(attestation)), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise TrustContractError("E_V236_ATTESTATION_SIGNATURE")
        issued = _parse_utc(attestation.get("issued_at"))
        expires = _parse_utc(attestation.get("expires_at"))
        current = _current_utc(now, "E_V236_ATTESTATION_TIME")
        if expires <= issued:
            raise TrustContractError("E_V236_ATTESTATION_TIME")
        if current + timedelta(seconds=clock_skew_seconds) < issued:
            raise TrustContractError("E_V236_ATTESTATION_NOT_YET_VALID")
        if current >= expires:
            raise TrustContractError("E_V236_ATTESTATION_EXPIRED")
        if used_nonces is not None:
            used_nonces.add(nonce)
        return _ok(
            run_id=core["agent_run_id"],
            transport_handle=core["transport_handle"],
            issuer=expected_issuer,
            nonce=nonce,
        )
    except TrustContractError as exc:
        return _error(exc.code)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _FORBIDDEN_REGISTRY_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _validate_attested_identity_registry_document(
    document: dict[str, Any],
    *,
    trust_key: bytes,
    expected_issuer: str,
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pure registry verification plus unconsumed challenge collection."""

    try:
        key = _trust_key(trust_key)
        if not isinstance(document, dict) or _contains_forbidden_key(document):
            raise TrustContractError("E_V236_ATTESTED_REGISTRY_SECRET")
        if document.get("schema_version") not in {
            "goal-teams-v2.3",
            ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION,
        } or not isinstance(document.get("identities"), list) or not document["identities"]:
            raise TrustContractError("E_V236_ATTESTED_REGISTRY_SCHEMA")
        registry: dict[str, dict[str, Any]] = {}
        transports: set[str] = set()
        nonces: set[str] = set()
        challenges: list[dict[str, Any]] = []
        current = _current_utc(now, "E_V236_ATTESTATION_TIME")
        for value in document["identities"]:
            core = identity_core(value)
            if core["agent_run_id"] in registry:
                raise TrustContractError("E_V236_ATTESTED_REGISTRY_RUN_DUPLICATE")
            if core["transport_handle"] in transports:
                raise TrustContractError("E_V236_ATTESTED_REGISTRY_TRANSPORT_DUPLICATE")
            proof = value.get("host_attestation") if isinstance(value, dict) else None
            verified = verify_agent_host_attestation(
                value,
                proof,
                trust_key=key,
                expected_issuer=expected_issuer,
                now=current,
                used_nonces=nonces,
            )
            if not verified.get("ok"):
                raise TrustContractError(str(verified.get("error_code") or "E_V236_ATTESTATION"))
            registry[core["agent_run_id"]] = copy.deepcopy(value)
            transports.add(core["transport_handle"])
            challenges.append(
                _challenge_record(
                    kind="host_attestation",
                    issuer=expected_issuer,
                    nonce=verified["nonce"],
                    proof=proof,
                    consumed_at=current,
                    expires_at=proof["expires_at"],
                    trust_key=key,
                )
            )
        return (
            _ok(
                registry=registry,
                attestation_count=len(registry),
                consumed_nonces=sorted(nonces),
            ),
            challenges,
        )
    except TrustContractError as exc:
        return _error(exc.code), []


def validate_attested_identity_registry(
    document: dict[str, Any],
    *,
    trust_key: bytes,
    expected_issuer: str,
    now: datetime | None = None,
    state_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify identities, retaining the historical pure-validation interface.

    Without ``state_path`` this function only detects duplicates inside this
    call and is explicitly *not* V2.36-acceptance eligible.  Passing an
    explicit protected state path delegates to the strict acceptance API.
    """

    if state_path is not None:
        return validate_attested_identity_registry_for_acceptance(
            document,
            trust_key=trust_key,
            expected_issuer=expected_issuer,
            state_path=state_path,
            now=now,
        )
    result, _ = _validate_attested_identity_registry_document(
        document,
        trust_key=trust_key,
        expected_issuer=expected_issuer,
        now=now,
    )
    if result.get("ok"):
        result.update(
            acceptance_eligible=False,
            replay_protection="single_call_only",
        )
    return result


def _host_reference_validate_attested_identity_registry(
    document: dict[str, Any],
    *,
    trust_key: bytes,
    expected_issuer: str,
    state_path: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Exercise host-side replay mechanics without creating an authority.

    This private reference helper is covered by tests so an external host can
    vendor the algorithm.  Its output is never a Goal Teams Completion verdict.
    """

    if not isinstance(document, dict) or document.get("schema_version") != ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION:
        return _error("E_V236_ATTESTED_REGISTRY_DOWNGRADE")
    result, challenges = _validate_attested_identity_registry_document(
        document,
        trust_key=trust_key,
        expected_issuer=expected_issuer,
        now=now,
    )
    if not result.get("ok"):
        return result
    consumed = _consume_persistent_challenges(
        state_path,
        challenges,
        trust_key=trust_key,
        replay_error="E_V236_ATTESTATION_NONCE_REPLAY",
    )
    if not consumed.get("ok"):
        return consumed
    return _ok(
        **{key: value for key, value in result.items() if key not in {"ok", "error_code"}},
        acceptance_eligible=False,
        host_reference_only=True,
        replay_protection="persistent_host_state",
        state_generation=consumed["state_generation"],
        state_sha256=consumed["state_sha256"],
        consumed_challenge_sha256=consumed["consumed_challenge_sha256"],
    )


def _derived_v236_route(route_request: Any) -> dict[str, Any]:
    if not isinstance(route_request, dict):
        raise TrustContractError("E_V236_ROUTE_RECEIPT_ROUTE")
    policy = _load_v236_policy()
    result = policy.normalize_project_route(copy.deepcopy(route_request))
    if not isinstance(result, dict) or not result.get("ok"):
        code = result.get("error_code") if isinstance(result, dict) else None
        raise TrustContractError(str(code or "E_V236_ROUTE_RECEIPT_ROUTE"))
    if result.get("schema_version") != "goal-teams-project-route-v2.36":
        raise TrustContractError("E_V236_ROUTE_RECEIPT_DOWNGRADE")
    return result


def _valid_route_host_fact(
    *,
    actual_target_fingerprint: Any,
    actual_target_kind: Any,
    trusted_release_base: Any,
) -> None:
    if (
        not isinstance(actual_target_fingerprint, str)
        or not _HEX_SHA256.fullmatch(actual_target_fingerprint)
    ):
        raise TrustContractError("E_V236_ROUTE_TARGET_FINGERPRINT")
    if actual_target_kind not in {"generic_project", "goal_teams_repository"}:
        raise TrustContractError("E_V236_ROUTE_TARGET_KIND")
    if not isinstance(trusted_release_base, str) or not _GIT_OBJECT_ID.fullmatch(trusted_release_base):
        raise TrustContractError("E_V236_ROUTE_RELEASE_BASE")


def _route_receipt_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key != "signature"}


def issue_v236_host_route_receipt(
    route_request: dict[str, Any],
    *,
    actual_target_fingerprint: str,
    actual_target_kind: str,
    trusted_release_base: str,
    trust_key: bytes,
    issuer: str,
    nonce: str,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Host-sign the actual target and the deterministically derived V2.36 route."""

    try:
        key = _trust_key(trust_key)
        _valid_route_host_fact(
            actual_target_fingerprint=actual_target_fingerprint,
            actual_target_kind=actual_target_kind,
            trusted_release_base=trusted_release_base,
        )
        if not isinstance(issuer, str) or not _SAFE_TOKEN.fullmatch(issuer):
            raise TrustContractError("E_V236_ROUTE_ISSUER")
        if not isinstance(nonce, str) or not nonce or len(nonce) > 128 or not _SAFE_TOKEN.fullmatch(nonce):
            raise TrustContractError("E_V236_ROUTE_NONCE")
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise TrustContractError("E_V236_ROUTE_TIME")
        route_candidate = copy.deepcopy(route_request)
        derived = _derived_v236_route(route_candidate)
        if derived["target_kind"] != actual_target_kind:
            raise TrustContractError("E_V236_ROUTE_TARGET_KIND")
        issued = issued_at or datetime.now(timezone.utc)
        expires = expires_at or (issued + timedelta(seconds=ttl_seconds))
        issued_text = _utc_text(issued)
        expires_text = _utc_text(expires)
        if _parse_utc(expires_text) <= _parse_utc(issued_text):
            raise TrustContractError("E_V236_ROUTE_TIME")
        payload: dict[str, Any] = {
            "schema_version": HOST_ROUTE_RECEIPT_SCHEMA_VERSION,
            "algorithm": HMAC_ALGORITHM,
            "issuer": issuer,
            "product_version": derived["product_version"],
            "actual_target_fingerprint": actual_target_fingerprint,
            "actual_target_kind": actual_target_kind,
            "trusted_release_base": trusted_release_base,
            "task_type": derived["task_type"],
            "release": bool(route_candidate["release"]),
            "route_digest": _sha256(_canonical_bytes(route_candidate)),
            "policy_profile": derived["policy_profile"],
            "state_gate_profile": derived["state_gate_profile"],
            "execution_profile": derived["profile"],
            "required_review_class": derived["required_review_class"],
            "gates": copy.deepcopy(derived["gates"]),
            "gate_scopes": copy.deepcopy(derived["gate_scopes"]),
            "execution_contract_sha256": derived[
                "execution_contract_sha256"
            ],
            "nonce": nonce,
            "issued_at": issued_text,
            "expires_at": expires_text,
        }
        receipt = {
            **payload,
            "signature": hmac.new(key, _canonical_bytes(payload), hashlib.sha256).hexdigest(),
        }
        return _ok(receipt=receipt)
    except TrustContractError as exc:
        code = "E_V236_ROUTE_TIME" if exc.code == "E_V236_ATTESTATION_TIME" else exc.code
        return _error(code)


def _verify_v236_host_route_receipt(
    route_request: dict[str, Any],
    receipt: dict[str, Any],
    *,
    actual_target_fingerprint: str,
    actual_target_kind: str,
    trusted_release_base: str,
    trust_key: bytes,
    expected_issuer: str,
    now: datetime | None = None,
    clock_skew_seconds: int = 30,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Pure cryptographic verification.  It does not consume the nonce."""

    try:
        key = _trust_key(trust_key)
        _valid_route_host_fact(
            actual_target_fingerprint=actual_target_fingerprint,
            actual_target_kind=actual_target_kind,
            trusted_release_base=trusted_release_base,
        )
        if not isinstance(receipt, dict) or set(receipt) != _ROUTE_RECEIPT_FIELDS:
            raise TrustContractError("E_V236_ROUTE_RECEIPT_SCHEMA")
        if (
            receipt.get("schema_version") != HOST_ROUTE_RECEIPT_SCHEMA_VERSION
            or receipt.get("algorithm") != HMAC_ALGORITHM
        ):
            raise TrustContractError("E_V236_ROUTE_RECEIPT_DOWNGRADE")
        if not isinstance(expected_issuer, str) or receipt.get("issuer") != expected_issuer:
            raise TrustContractError("E_V236_ROUTE_ISSUER")
        nonce = receipt.get("nonce")
        if not isinstance(nonce, str) or not nonce or len(nonce) > 128 or not _SAFE_TOKEN.fullmatch(nonce):
            raise TrustContractError("E_V236_ROUTE_NONCE")
        signature = receipt.get("signature")
        if not isinstance(signature, str) or not _HEX_SHA256.fullmatch(signature):
            raise TrustContractError("E_V236_ROUTE_SIGNATURE")
        expected_signature = hmac.new(
            key, _canonical_bytes(_route_receipt_payload(receipt)), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise TrustContractError("E_V236_ROUTE_SIGNATURE")
        # Recompute all routing decisions after authenticating the receipt.  No
        # receipt field is trusted as a selector.
        route_candidate = copy.deepcopy(route_request)
        derived = _derived_v236_route(route_candidate)
        expected = {
            "product_version": "V2.36",
            "actual_target_fingerprint": actual_target_fingerprint,
            "actual_target_kind": actual_target_kind,
            "trusted_release_base": trusted_release_base,
            "task_type": derived["task_type"],
            "release": bool(route_candidate["release"]),
            "route_digest": _sha256(_canonical_bytes(route_candidate)),
            "policy_profile": derived["policy_profile"],
            "state_gate_profile": derived["state_gate_profile"],
            "execution_profile": derived["profile"],
            "required_review_class": derived["required_review_class"],
            "gates": derived["gates"],
            "gate_scopes": derived["gate_scopes"],
            "execution_contract_sha256": derived[
                "execution_contract_sha256"
            ],
        }
        if derived["target_kind"] != actual_target_kind:
            raise TrustContractError("E_V236_ROUTE_TARGET_KIND")
        for field, value in expected.items():
            if receipt.get(field) != value:
                if field == "product_version":
                    raise TrustContractError("E_V236_ROUTE_RECEIPT_DOWNGRADE")
                if field == "trusted_release_base":
                    raise TrustContractError("E_V236_ROUTE_RELEASE_BASE")
                if field in {
                    "policy_profile",
                    "state_gate_profile",
                    "task_type",
                    "release",
                    "execution_profile",
                    "required_review_class",
                    "gates",
                    "gate_scopes",
                    "execution_contract_sha256",
                }:
                    raise TrustContractError("E_V236_ROUTE_DERIVATION_MISMATCH")
                if field in {"actual_target_fingerprint", "actual_target_kind"}:
                    raise TrustContractError("E_V236_ROUTE_TARGET_MISMATCH")
                raise TrustContractError("E_V236_ROUTE_DIGEST_MISMATCH")
        try:
            issued = _parse_utc(receipt.get("issued_at"))
            expires = _parse_utc(receipt.get("expires_at"))
        except TrustContractError as exc:
            raise TrustContractError("E_V236_ROUTE_TIME") from exc
        current = _current_utc(now, "E_V236_ROUTE_TIME")
        if expires <= issued:
            raise TrustContractError("E_V236_ROUTE_TIME")
        if current + timedelta(seconds=clock_skew_seconds) < issued:
            raise TrustContractError("E_V236_ROUTE_NOT_YET_VALID")
        if current >= expires:
            raise TrustContractError("E_V236_ROUTE_EXPIRED")
        challenge = _challenge_record(
            kind="route_receipt",
            issuer=expected_issuer,
            nonce=nonce,
            proof=receipt,
            consumed_at=current,
            expires_at=receipt["expires_at"],
            trust_key=key,
        )
        return (
            _ok(
                route_digest=expected["route_digest"],
                product_version="V2.36",
                actual_target_fingerprint=actual_target_fingerprint,
                actual_target_kind=actual_target_kind,
                task_type=derived["task_type"],
                release=bool(route_candidate["release"]),
                policy_profile=derived["policy_profile"],
                state_gate_profile=derived["state_gate_profile"],
                execution_profile=derived["profile"],
                required_review_class=derived["required_review_class"],
                gates=copy.deepcopy(derived["gates"]),
                gate_scopes=copy.deepcopy(derived["gate_scopes"]),
                execution_contract_sha256=derived[
                    "execution_contract_sha256"
                ],
                trusted_release_base=trusted_release_base,
            ),
            challenge,
        )
    except TrustContractError as exc:
        return _error(exc.code), None


def verify_v236_host_route_receipt(
    route_request: dict[str, Any],
    receipt: dict[str, Any],
    *,
    actual_target_fingerprint: str,
    actual_target_kind: str,
    trusted_release_base: str,
    trust_key: bytes,
    expected_issuer: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure route verification for preflight, never V2.36 acceptance.

    Candidate code may use this for diagnostics only.  A repository-external
    host must vendor/pin the reference mechanics and issue its own authoritative
    verdict; the public candidate acceptance APIs below always fail closed.
    """

    result, _ = _verify_v236_host_route_receipt(
        route_request,
        receipt,
        actual_target_fingerprint=actual_target_fingerprint,
        actual_target_kind=actual_target_kind,
        trusted_release_base=trusted_release_base,
        trust_key=trust_key,
        expected_issuer=expected_issuer,
        now=now,
    )
    if result.get("ok"):
        result.update(
            acceptance_eligible=False,
            replay_protection="none_preflight_only",
        )
    return result


def _host_reference_validate_v236_host_route_receipt(
    route_request: dict[str, Any],
    receipt: dict[str, Any],
    *,
    actual_target_fingerprint: str,
    actual_target_kind: str,
    trusted_release_base: str,
    trust_key: bytes,
    expected_issuer: str,
    state_path: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Exercise route replay mechanics for a repository-external host."""

    result, challenge = _verify_v236_host_route_receipt(
        route_request,
        receipt,
        actual_target_fingerprint=actual_target_fingerprint,
        actual_target_kind=actual_target_kind,
        trusted_release_base=trusted_release_base,
        trust_key=trust_key,
        expected_issuer=expected_issuer,
        now=now,
    )
    if not result.get("ok") or challenge is None:
        return result
    consumed = _consume_persistent_challenges(
        state_path,
        [challenge],
        trust_key=trust_key,
        replay_error="E_V236_ROUTE_NONCE_REPLAY",
    )
    if not consumed.get("ok"):
        return consumed
    return _ok(
        **{key: value for key, value in result.items() if key not in {"ok", "error_code"}},
        acceptance_eligible=False,
        host_reference_only=True,
        replay_protection="persistent_host_state",
        state_generation=consumed["state_generation"],
        state_sha256=consumed["state_sha256"],
        consumed_challenge_sha256=consumed["consumed_challenge_sha256"],
    )


def _host_reference_validate_v236_acceptance_bundle(
    route_request: dict[str, Any],
    route_receipt: dict[str, Any],
    identity_document: dict[str, Any],
    *,
    actual_target_fingerprint: str,
    actual_target_kind: str,
    trusted_release_base: str,
    trust_key: bytes,
    expected_issuer: str,
    state_path: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Exercise atomic host replay mechanics without granting authority.

    Completion gates should prefer this API so no partial nonce consumption can
    occur if either the route receipt or any agent identity fails validation.
    ``trusted_release_base`` is intended to be compared directly with the
    protected snapshot's ``baseline_commit`` by the caller.
    """

    if (
        not isinstance(identity_document, dict)
        or identity_document.get("schema_version")
        != ATTESTED_IDENTITY_REGISTRY_SCHEMA_VERSION
    ):
        return _error("E_V236_ATTESTED_REGISTRY_DOWNGRADE")
    try:
        current = _current_utc(now, "E_V236_ROUTE_TIME")
    except TrustContractError as exc:
        return _error(exc.code)
    route_result, route_challenge = _verify_v236_host_route_receipt(
        route_request,
        route_receipt,
        actual_target_fingerprint=actual_target_fingerprint,
        actual_target_kind=actual_target_kind,
        trusted_release_base=trusted_release_base,
        trust_key=trust_key,
        expected_issuer=expected_issuer,
        now=current,
    )
    if not route_result.get("ok") or route_challenge is None:
        return route_result
    identity_result, identity_challenges = _validate_attested_identity_registry_document(
        identity_document,
        trust_key=trust_key,
        expected_issuer=expected_issuer,
        now=current,
    )
    if not identity_result.get("ok"):
        return identity_result
    consumed = _consume_persistent_challenges(
        state_path,
        [route_challenge, *identity_challenges],
        trust_key=trust_key,
        replay_error="E_V236_ACCEPTANCE_NONCE_REPLAY",
    )
    if not consumed.get("ok"):
        return consumed
    return _ok(
        acceptance_eligible=False,
        host_reference_only=True,
        replay_protection="persistent_host_state",
        route={
            key: value
            for key, value in route_result.items()
            if key not in {"ok", "error_code"}
        },
        registry={
            key: value
            for key, value in identity_result.items()
            if key not in {"ok", "error_code"}
        },
        trusted_release_base=trusted_release_base,
        state_generation=consumed["state_generation"],
        state_sha256=consumed["state_sha256"],
        consumed_challenge_sha256=consumed["consumed_challenge_sha256"],
    )


def _host_adapter_required() -> dict[str, Any]:
    """Public candidate-side acceptance APIs are permanently fail-closed."""

    return _error(
        "E_V236_HOST_ADAPTER_REQUIRED",
        acceptance_eligible=False,
        host_adapter_required=True,
    )


def validate_attested_identity_registry_for_acceptance(
    document: dict[str, Any],
    *,
    trust_key: bytes,
    expected_issuer: str,
    state_path: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reject candidate-selected identity trust roots without touching state."""

    return _host_adapter_required()


def validate_v236_host_route_receipt_for_acceptance(
    route_request: dict[str, Any],
    receipt: dict[str, Any],
    *,
    actual_target_fingerprint: str,
    actual_target_kind: str,
    trusted_release_base: str,
    trust_key: bytes,
    expected_issuer: str,
    state_path: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reject candidate-selected route trust roots without touching state."""

    return _host_adapter_required()


def validate_v236_acceptance_bundle(
    route_request: dict[str, Any],
    route_receipt: dict[str, Any],
    identity_document: dict[str, Any],
    *,
    actual_target_fingerprint: str,
    actual_target_kind: str,
    trusted_release_base: str,
    trust_key: bytes,
    expected_issuer: str,
    state_path: Path | str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reject candidate-selected bundle trust roots without touching state."""

    return _host_adapter_required()


# Short aliases expose only diagnostic or fail-closed candidate APIs.
create_protected_snapshot = create_protected_git_tree_snapshot
validate_protected_snapshot = validate_protected_git_tree_snapshot
issue_host_attestation = issue_agent_host_attestation
verify_host_attestation = verify_agent_host_attestation
issue_host_route_receipt = issue_v236_host_route_receipt
verify_host_route_receipt = verify_v236_host_route_receipt
validate_host_route_receipt_for_acceptance = validate_v236_host_route_receipt_for_acceptance
