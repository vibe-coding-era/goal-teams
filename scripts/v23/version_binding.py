#!/usr/bin/env python3
"""Trusted V2.34-default / V2.35-explicit version binding.

This module is deliberately side-effect free.  It validates the exact delta
contract and its independent review before returning a normalized binding;
callers may then derive product paths from that single immutable fact source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any


DESCRIPTOR_SCHEMA = "goal-teams-version-binding-v1"
NORMALIZED_SCHEMA = "goal-teams-normalized-version-binding-v1"
DEFAULT_VERSION = "V2.34"
EXPLICIT_PROJECT_VERSION = "V2.35"
EXPLICIT_ARTIFACT_VERSION = "V2.35-run2"
EXPLICIT_CONTRACT_REVISION = 2

_VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
_ARTIFACT_RE = re.compile(r"^V[0-9]+\.[0-9]+(?:-run[0-9]+)?$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ENCODED_ESCAPE_RE = re.compile(r"%(?:00|2e|2f|5c)", re.IGNORECASE)
_ASSERTION_RE = re.compile(r"^ASSERT-V235-([0-9]{3})$")
_ASSERTION_SEMANTICS_SHA256 = frozenset(
    {
        # Accepted V2.35 run2 delta contract assertion projection.
        "5edacedfac991a86b02a269e90fea8ed6141a30ec1efe4ef6c3d8becd7f4a33c",
    }
)

_DESCRIPTOR_KEYS = frozenset(
    {
        "schema_version",
        "project_version",
        "release_version",
        "artifact_version",
        "contract_ref",
        "contract_sha256",
        "contract_revision",
        "review_ref",
        "review_sha256",
        "review_state",
    }
)
_NORMALIZED_KEYS = frozenset(
    {
        "schema_version",
        "explicit",
        "project_version",
        "release_version",
        "artifact_version",
        "archive_prefix",
        "contract_ref",
        "contract_sha256",
        "contract_revision",
        "review_ref",
        "review_sha256",
        "review_state",
        "contract_owner_run_id",
        "contract_validator_run_id",
        "review_owner_run_id",
        "review_validator_run_id",
        "binding_digest",
    }
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _error(code: str, **values: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": code,
        "errors": values.pop("errors", [code]),
        "mutation_count": 0,
        **values,
    }


def _ok(binding: dict[str, Any], **values: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "error_code": None,
        "binding": binding,
        "mutation_count": 0,
        **values,
    }


def _has_path_escape(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return True
    return bool(
        "\x00" in value
        or "\\" in value
        or "/" in value
        or ".." in value
        or _ENCODED_ESCAPE_RE.search(value)
    )


def _safe_segment(value: Any, *, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and not _has_path_escape(value) and bool(pattern.fullmatch(value))


def _safe_relative_ref(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return None
    if _ENCODED_ESCAPE_RE.search(value) or value.startswith("/"):
        return None
    path = PurePosixPath(value)
    parts = path.parts
    if not parts or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        return None
    if any(".." in part or _ENCODED_ESCAPE_RE.search(part) for part in parts):
        return None
    return tuple(parts)


def _regular_repo_file(repo_root: Path, reference: Any) -> Path | None:
    parts = _safe_relative_ref(reference)
    if parts is None:
        return None
    try:
        root_meta = os.lstat(repo_root)
        if stat.S_ISLNK(root_meta.st_mode) or not stat.S_ISDIR(root_meta.st_mode):
            return None
        current = repo_root
        for index, part in enumerate(parts):
            current = current / part
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode):
                return None
            if index < len(parts) - 1:
                if not stat.S_ISDIR(metadata.st_mode):
                    return None
            elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                return None
        return current
    except OSError:
        return None


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        if ":" not in line or line[:1].isspace():
            continue
        key, raw = line.split(":", 1)
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return {}


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    return None


def _contract_facts(raw: bytes) -> dict[str, Any] | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    metadata = _frontmatter(text)
    rows: dict[str, tuple[str, str, str]] = {}
    duplicate = False
    for line in text.splitlines():
        if not line.lstrip().startswith("| ASSERT-V235-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not _ASSERTION_RE.fullmatch(cells[0]):
            return None
        assertion_id = cells[0]
        if assertion_id in rows:
            duplicate = True
        rows[assertion_id] = (cells[1], cells[2].lower(), cells[-1].lower())
    expected = {f"ASSERT-V235-{number:03d}" for number in range(1, 37)}
    semantic_projection = [
        {
            "assertion_id": assertion_id,
            "assertion": rows[assertion_id][0],
            "required": rows[assertion_id][1],
            "state": rows[assertion_id][2],
        }
        for assertion_id in sorted(rows)
    ]
    semantic_digest = _digest_bytes(_canonical_bytes(semantic_projection))
    owner = metadata.get("owner_run_id")
    validator = metadata.get("validator_run_id")
    if (
        duplicate
        or set(rows) != expected
        or any(required != "true" or state != "frozen" for _, required, state in rows.values())
        or semantic_digest not in _ASSERTION_SEMANTICS_SHA256
        or metadata.get("project_version") != EXPLICIT_PROJECT_VERSION
        or metadata.get("artifact_version") != EXPLICIT_ARTIFACT_VERSION
        or _integer(metadata.get("contract_revision")) != EXPLICIT_CONTRACT_REVISION
        or metadata.get("assertion_content_state") != "frozen"
        or _integer(metadata.get("required_assertion_count")) != len(expected)
        or not isinstance(owner, str)
        or not owner
        or not isinstance(validator, str)
        or not validator
        or owner == validator
    ):
        return None
    return {
        "project_version": metadata["project_version"],
        "artifact_version": metadata["artifact_version"],
        "contract_revision": EXPLICIT_CONTRACT_REVISION,
        "owner_run_id": owner,
        "validator_run_id": validator,
    }


def _review_record(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
        if isinstance(value, dict):
            return value
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    metadata: dict[str, Any] = dict(_frontmatter(text))
    for line in text.splitlines():
        match = re.match(r"^\s*(?:[-*]\s*)?([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$", line)
        if match and match.group(1) not in metadata:
            metadata[match.group(1)] = match.group(2).strip("`\"'")
    for key in ("current",):
        if isinstance(metadata.get(key), str):
            metadata[key] = metadata[key].lower() == "true"
    for key in ("contract_revision",):
        converted = _integer(metadata.get(key))
        if converted is not None:
            metadata[key] = converted
    return metadata or None


def _normalized_digest(binding: dict[str, Any]) -> str:
    projected = {key: value for key, value in binding.items() if key != "binding_digest"}
    return _digest_bytes(_canonical_bytes(projected))


def default_version_binding() -> dict[str, Any]:
    binding = {
        "schema_version": NORMALIZED_SCHEMA,
        "explicit": False,
        "project_version": DEFAULT_VERSION,
        "release_version": DEFAULT_VERSION,
        "artifact_version": DEFAULT_VERSION,
        "archive_prefix": f"docs/archive/{DEFAULT_VERSION}",
        "contract_ref": None,
        "contract_sha256": None,
        "contract_revision": None,
        "review_ref": None,
        "review_sha256": None,
        "review_state": None,
        "contract_owner_run_id": None,
        "contract_validator_run_id": None,
        "review_owner_run_id": None,
        "review_validator_run_id": None,
    }
    binding["binding_digest"] = _normalized_digest(binding)
    return binding


def validate_normalized_binding(binding: Any) -> dict[str, Any]:
    if not isinstance(binding, dict) or set(binding) != _NORMALIZED_KEYS:
        return _error("E_V235_VERSION_BINDING_NORMALIZED")
    if binding.get("schema_version") != NORMALIZED_SCHEMA or not isinstance(binding.get("explicit"), bool):
        return _error("E_V235_VERSION_BINDING_NORMALIZED")
    if binding.get("binding_digest") != _normalized_digest(binding):
        return _error("E_V235_VERSION_BINDING_DIGEST")
    if any(
        not _safe_segment(binding.get(key), pattern=_ARTIFACT_RE if key == "artifact_version" else _VERSION_RE)
        for key in ("project_version", "release_version", "artifact_version")
    ):
        return _error("E_V235_VERSION_BINDING_PATH")
    expected_prefix = f"docs/archive/{binding['release_version']}"
    if binding.get("archive_prefix") != expected_prefix:
        return _error("E_V235_VERSION_BINDING_MISMATCH")
    if binding["explicit"]:
        if (
            binding.get("project_version") != EXPLICIT_PROJECT_VERSION
            or binding.get("release_version") != EXPLICIT_PROJECT_VERSION
            or binding.get("artifact_version") != EXPLICIT_ARTIFACT_VERSION
            or binding.get("contract_revision") != EXPLICIT_CONTRACT_REVISION
            or not _HASH_RE.fullmatch(str(binding.get("contract_sha256", "")))
            or not _HASH_RE.fullmatch(str(binding.get("review_sha256", "")))
            or binding.get("review_state") != "passed"
            or binding.get("contract_owner_run_id") == binding.get("contract_validator_run_id")
            or binding.get("review_owner_run_id") == binding.get("review_validator_run_id")
            or any(
                not isinstance(binding.get(key), str) or not binding.get(key)
                for key in (
                    "contract_ref", "review_ref", "contract_owner_run_id",
                    "contract_validator_run_id", "review_owner_run_id",
                    "review_validator_run_id",
                )
            )
        ):
            return _error("E_V235_VERSION_BINDING_NORMALIZED")
    elif binding != default_version_binding():
        return _error("E_V235_VERSION_BINDING_NORMALIZED")
    return _ok(dict(binding))


def normalize_version_binding(
    descriptor: dict[str, Any] | None, *, repo_root: Path | str
) -> dict[str, Any]:
    """Validate and normalize a descriptor without mutating the repository."""
    if descriptor is None:
        return _ok(default_version_binding())
    if not isinstance(descriptor, dict) or set(descriptor) != _DESCRIPTOR_KEYS:
        return _error("E_V235_VERSION_BINDING_DESCRIPTOR")
    if descriptor.get("schema_version") != DESCRIPTOR_SCHEMA:
        return _error("E_V235_VERSION_BINDING_DESCRIPTOR")

    for key, pattern in (
        ("project_version", _VERSION_RE),
        ("release_version", _VERSION_RE),
        ("artifact_version", _ARTIFACT_RE),
    ):
        value = descriptor.get(key)
        if _has_path_escape(value):
            return _error("E_V235_VERSION_BINDING_PATH")
        if not isinstance(value, str) or not pattern.fullmatch(value):
            return _error("E_V235_VERSION_BINDING_MISMATCH")
    if (
        descriptor["project_version"] != EXPLICIT_PROJECT_VERSION
        or descriptor["release_version"] != descriptor["project_version"]
        or descriptor["artifact_version"] != EXPLICIT_ARTIFACT_VERSION
    ):
        return _error("E_V235_VERSION_BINDING_MISMATCH")

    if _safe_relative_ref(descriptor.get("contract_ref")) is None or _safe_relative_ref(descriptor.get("review_ref")) is None:
        return _error("E_V235_VERSION_BINDING_PATH")
    repository = Path(repo_root).absolute()
    contract_path = _regular_repo_file(repository, descriptor["contract_ref"])
    review_path = _regular_repo_file(repository, descriptor["review_ref"])
    if contract_path is None or review_path is None:
        return _error("E_V235_VERSION_BINDING_PATH")
    try:
        contract_bytes = contract_path.read_bytes()
        review_bytes = review_path.read_bytes()
    except OSError:
        return _error("E_V235_VERSION_BINDING_PATH")
    contract_hash = _digest_bytes(contract_bytes)
    review_hash = _digest_bytes(review_bytes)
    if not _HASH_RE.fullmatch(str(descriptor.get("contract_sha256", ""))) or descriptor["contract_sha256"] != contract_hash:
        return _error("E_V235_VERSION_BINDING_CONTRACT")
    if not _HASH_RE.fullmatch(str(descriptor.get("review_sha256", ""))) or descriptor["review_sha256"] != review_hash:
        return _error("E_V235_VERSION_BINDING_REVIEW")

    contract = _contract_facts(contract_bytes)
    if contract is None:
        return _error("E_V235_VERSION_BINDING_CONTRACT_SEMANTICS")
    if (
        descriptor["project_version"] != contract["project_version"]
        or descriptor["release_version"] != contract["project_version"]
        or descriptor["artifact_version"] != contract["artifact_version"]
        or descriptor["contract_revision"] != contract["contract_revision"]
    ):
        return _error("E_V235_VERSION_BINDING_MISMATCH")

    review = _review_record(review_bytes)
    if review is None:
        return _error("E_V235_VERSION_BINDING_REVIEW")
    review_owner = review.get("owner_run_id", review.get("author_run_id"))
    review_validator = review.get("validator_run_id", review.get("reviewer_run_id"))
    if not isinstance(review_owner, str) or not review_owner or not isinstance(review_validator, str) or not review_validator:
        return _error("E_V235_VERSION_BINDING_REVIEW")
    if review_owner == review_validator:
        return _error("E_V235_VERSION_BINDING_INDEPENDENCE")
    if (
        descriptor.get("review_state") != "passed"
        or review.get("state") != "passed"
        or review.get("decision") != "approved"
        or review.get("current") is not True
        or review.get("artifact_ref") != descriptor["contract_ref"]
        or review.get("artifact_sha256") != contract_hash
        or review.get("contract_sha256") != contract_hash
        or _integer(review.get("contract_revision")) != EXPLICIT_CONTRACT_REVISION
    ):
        return _error("E_V235_VERSION_BINDING_REVIEW")

    normalized = {
        "schema_version": NORMALIZED_SCHEMA,
        "explicit": True,
        "project_version": descriptor["project_version"],
        "release_version": descriptor["release_version"],
        "artifact_version": descriptor["artifact_version"],
        "archive_prefix": f"docs/archive/{descriptor['release_version']}",
        "contract_ref": descriptor["contract_ref"],
        "contract_sha256": contract_hash,
        "contract_revision": EXPLICIT_CONTRACT_REVISION,
        "review_ref": descriptor["review_ref"],
        "review_sha256": review_hash,
        "review_state": "passed",
        "contract_owner_run_id": contract["owner_run_id"],
        "contract_validator_run_id": contract["validator_run_id"],
        "review_owner_run_id": review_owner,
        "review_validator_run_id": review_validator,
    }
    normalized["binding_digest"] = _normalized_digest(normalized)
    return _ok(normalized)


def public_archive_path(
    repo_root: Path | str, binding: dict[str, Any], *, delivery_id: str
) -> dict[str, Any]:
    """Compute the public archive path from release_version without mutation."""
    validation = validate_normalized_binding(binding)
    if not validation.get("ok"):
        return validation
    if not _safe_segment(delivery_id, pattern=_SEGMENT_RE):
        return _error("E_V235_VERSION_BINDING_PATH")
    repository = Path(repo_root).absolute()
    relative = PurePosixPath(binding["archive_prefix"]) / delivery_id
    current = repository
    try:
        root_meta = os.lstat(repository)
        if stat.S_ISLNK(root_meta.st_mode) or not stat.S_ISDIR(root_meta.st_mode):
            return _error("E_V235_VERSION_BINDING_PATH")
        for part in relative.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                metadata = os.lstat(current)
                if stat.S_ISLNK(metadata.st_mode):
                    return _error("E_V235_VERSION_BINDING_PATH")
                if not stat.S_ISDIR(metadata.st_mode):
                    return _error("E_V235_VERSION_BINDING_PATH")
    except OSError:
        return _error("E_V235_VERSION_BINDING_PATH")
    archive_ref = relative.as_posix()
    return {
        "ok": True,
        "error_code": None,
        "archive_ref": archive_ref,
        "archive_path": str(repository.joinpath(*relative.parts)),
        "release_version": binding["release_version"],
        "binding_digest": binding["binding_digest"],
        "mutation_count": 0,
    }
