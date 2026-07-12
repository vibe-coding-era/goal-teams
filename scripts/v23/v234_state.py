#!/usr/bin/env python3
"""Goal Teams V2.34 recoverable LOOP and delivery control plane.

The V2.3 ledger remains authoritative for task/check acceptance.  This module
implements the revision-bound, four-file recovery projection described by the
V2.34 contract.  Its destructive operations are deliberately narrow: reset
can only quarantine a pre-authorized disposable candidate and delivery can
only publish sanitized copies below ``docs/archive/V2.34``.
"""

from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

try:
    from scripts.v23 import version_binding as _version_binding
except ModuleNotFoundError:  # Direct execution from scripts/v23.
    import version_binding as _version_binding  # type: ignore[no-redef]

try:
    from scripts.v23.v236_security import contains_secret as _contains_secret
    from scripts.v23.v236_security import redact_text as _redact_text
except ModuleNotFoundError:  # Direct execution from scripts/v23.
    from v236_security import contains_secret as _contains_secret  # type: ignore[no-redef]
    from v236_security import redact_text as _redact_text  # type: ignore[no-redef]


V234_STATE_SCHEMA = "goal-teams-v2.34-state-v1"
V234_CLI_SCHEMA = "goal-teams-v2.34-cli-v1"
V234_PHASES = ("gather", "reason", "act", "verify", "repeat")
V234_NORMAL_EDGES = (
    ("gather", "reason"),
    ("reason", "act"),
    ("act", "verify"),
    ("verify", "repeat"),
    ("repeat", "gather"),
)
V23_TASK_STATES = frozenset({"planned", "running", "review", "accepted", "blocked", "deferred", "cancelled"})
V23_CHECK_STATES = frozenset({"not_started", "not_required", "running", "passed", "failed", "blocked", "waived"})
V23_LOOP_DECISIONS = frozenset({"continue", "replan", "stop"})
V23_RUN_OUTCOMES = frozenset({"partial", "blocked", "aborted", "achieved"})
V234_CONVENIENCE_STATES: tuple[str, ...] = ()
V234_BOTTLENECK_CATEGORIES = (
    "contract", "planning", "architecture", "environment", "implementation",
    "verification", "review", "authorization", "delivery",
)
PRESERVED_PRIVATE_ARTIFACT_CLASSES = (
    "ledger", "evidence", "review", "audit", "provenance",
)

_STOP_REASONS = frozenset(
    {
        "achieved", "user_input_required", "authorization_required",
        "budget_exceeded", "deferred", "aborted",
    }
)
_SCORE_DIMENSIONS = ("design", "originality", "craft", "functionality")
_SCORE_CRITERIA = {
    "design": ("DES-1", "DES-2", "DES-3", "DES-4"),
    "originality": ("ORG-1", "ORG-2", "ORG-3", "ORG-4"),
    "craft": ("CRF-1", "CRF-2", "CRF-3", "CRF-4"),
    "functionality": ("FUN-1", "FUN-2", "FUN-3", "FUN-4"),
}
_SCORE_STATUSES = frozenset({"passed", "failed", "unverified"})
_PATCH_STATES = frozenset({"proposed", "applied", "verified", "reverted"})
_DELIVERY_REQUIREMENTS = (
    "contract_gate_current", "architecture_gate_current", "environment_gate_current",
    "required_tasks_accepted", "required_checks_passed", "current_evidence_and_reviews",
    "bundle_consistent", "reset_lineage_current", "rebuilt_candidate_digest_current",
    "full_tests_passed", "archive_preflight_passed", "completion_audit_passed",
    "scores_valid", "prompt_lifecycle_closed", "bottleneck_current",
    "version_sync_passed", "publish_guard_passed", "roadmap_unchanged",
    "worktree_scope_preserved",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DERIVED_CONTRACT_KEYS = frozenset(
    {"reviewer_decision", "gate_state", "task_state", "check_state", "contract_sha256", "assertion_set_sha256", "accepted"}
)
_INVOCATION_NOISE = re.compile(
    r"(?:spawn_agent|tool_call|transport_handle|/root/[A-Za-z0-9_.\-/]+|RUN-INTERNAL-[A-Za-z0-9_-]+)"
)
_ABSOLUTE_HOME_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+(?:/[^\s]*)?")
_PROCESS_PATH_PARTS = frozenset(
    {"ledger", "evidence", "audit", "review", "reviews", "harness", "identity", "provenance", ".goalteams-state", ".goalteams-quarantine"}
)
_PROTECTED_CANDIDATE_SNAPSHOT_SCHEMA = "goal-teams-v2.34-protected-candidate-snapshot-v1"
_V234_REQUIRED_CANDIDATE_PATHS = frozenset(
    {"VERSION", "scripts/v23/v234_state.py", "scripts/v23/goalteams_v23.py"}
)
_V234_PRODUCT_EXACT_PATHS = frozenset(
    {
        ".gitignore", "CHANGELOG.md", "README.md", "README.en.md", "SKILL.md",
        "VERSION", "goal-teams.md", "agents/openai.yaml",
        "docs/change-history.md", "docs/change-history.en.md",
        "docs/release-contents.md", "docs/release-contents.en.md",
        "docs/v2.34-completion.md", "docs/v2.34-completion.en.md",
    }
)
_V234_PRODUCT_PREFIXES = (
    "docs/archive/V2.34/", "examples/", "prompts/", "schemas/v2.3/", "scripts/",
)
_V235_PRODUCT_EXACT_PATHS = frozenset(
    {
        *_V234_PRODUCT_EXACT_PATHS,
        "docs/v2.35-release-summary.md",
        "docs/v2.35-release-summary.en.md",
    }
)
_V235_REQUIRED_CANDIDATE_PATHS = frozenset(
    {"VERSION", "scripts/v23/v234_state.py", "scripts/v23/goalteams_v23.py", "scripts/v23/version_binding.py"}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_path(path: Path) -> str:
    return _digest_bytes(path.read_bytes())


def _ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, "error_code": None, **data}


def _error(code: str, *, errors: Iterable[Any] | None = None, **data: Any) -> dict[str, Any]:
    return {"ok": False, "error_code": code, "errors": list(errors or [code]), **data}


def _binding_result(
    repo_root: Path | str, supplied: dict[str, Any] | None,
    *, marker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one binding before any lock, directory, or archive mutation."""
    if supplied is not None:
        normalized_input = bool(
            isinstance(supplied, dict)
            and supplied.get("schema_version") == _version_binding.NORMALIZED_SCHEMA
        )
        if normalized_input:
            structural = _version_binding.validate_normalized_binding(supplied)
            if not structural.get("ok"):
                return structural
            if supplied.get("explicit") is not True:
                result = _version_binding.normalize_version_binding(None, repo_root=repo_root)
            else:
                descriptor = {
                    "schema_version": _version_binding.DESCRIPTOR_SCHEMA,
                    "project_version": supplied.get("project_version"),
                    "release_version": supplied.get("release_version"),
                    "artifact_version": supplied.get("artifact_version"),
                    "contract_ref": supplied.get("contract_ref"),
                    "contract_sha256": supplied.get("contract_sha256"),
                    "contract_revision": supplied.get("contract_revision"),
                    "review_ref": supplied.get("review_ref"),
                    "review_sha256": supplied.get("review_sha256"),
                    "review_state": supplied.get("review_state"),
                }
                result = _version_binding.normalize_version_binding(
                    descriptor, repo_root=repo_root
                )
        else:
            result = _version_binding.normalize_version_binding(supplied, repo_root=repo_root)
        if not result.get("ok"):
            return result
        normalized = result["binding"]
        if normalized_input and normalized != supplied:
            return _version_binding._error("E_V235_VERSION_BINDING_MISMATCH")
        if marker is not None:
            embedded = _marker_binding(marker)
            if not embedded.get("ok"):
                return embedded
            if embedded["binding"].get("binding_digest") != normalized.get("binding_digest"):
                return _version_binding._error("E_V235_VERSION_BINDING_MISMATCH")
        return result
    if marker is not None:
        embedded = _marker_binding(marker)
        if not embedded.get("ok") or embedded["binding"].get("explicit") is not True:
            return embedded
        # An explicit marker is trusted provenance, not a permanent approval.
        # Re-read its exact contract and current independent review on every
        # public operation that has repository context.
        return _binding_result(repo_root, embedded["binding"], marker=marker)
    return _version_binding.normalize_version_binding(None, repo_root=repo_root)


def _marker_binding(marker: dict[str, Any]) -> dict[str, Any]:
    embedded = marker.get("version_binding")
    if embedded is None:
        normalized = _version_binding.default_version_binding()
        if (
            marker.get("project_version", normalized["project_version"]) != normalized["project_version"]
            or marker.get("artifact_version", normalized["artifact_version"]) != normalized["artifact_version"]
            or marker.get("release_version", normalized["release_version"]) != normalized["release_version"]
        ):
            return _version_binding._error("E_V235_VERSION_BINDING_MISMATCH")
        return _version_binding._ok(normalized)
    result = _version_binding.validate_normalized_binding(embedded)
    if not result.get("ok"):
        return result
    normalized = result["binding"]
    if (
        marker.get("project_version") != normalized["project_version"]
        or marker.get("artifact_version") != normalized["artifact_version"]
        or marker.get("release_version") != normalized["release_version"]
    ):
        return _version_binding._error("E_V235_VERSION_BINDING_MISMATCH")
    return result


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _acquire_state_lock(state_root: Path) -> int:
    lock_root = state_root / ".goalteams-state"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / "state.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _release_state_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _write_temp(path: Path, data: bytes, transaction_id: str) -> Path:
    safe_token = _digest_bytes(str(transaction_id).encode("utf-8"))[:16]
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.{safe_token}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(raw_path)
    try:
        if temp_path.parent.resolve() != path.parent.resolve():
            raise OSError("transaction temporary escaped target directory")
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("unsafe transaction temporary")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if temp_path.exists() and not temp_path.is_symlink():
            temp_path.unlink()
        raise
    return temp_path


def _regular_single_link(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def _replace_verified(temp_path: Path, destination: Path, *, allow_missing: bool = False) -> None:
    destination_safe = _regular_single_link(destination)
    if allow_missing and not destination.exists() and not destination.is_symlink():
        destination_safe = True
    if not _regular_single_link(temp_path) or not destination_safe:
        raise OSError("unsafe state transaction target")
    os.replace(temp_path, destination)
    if not _regular_single_link(destination):
        raise OSError("unsafe state transaction result")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_verified(temp_path, path, allow_missing=True)
        _fsync_directory(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))


def _marker_digest(marker: dict[str, Any]) -> str:
    projected = copy.deepcopy(marker)
    projected.pop("bundle_digest", None)
    return _digest_bytes(_canonical_bytes(projected))


def _encode_progress(marker: dict[str, Any]) -> bytes:
    projection = {
        "schema_version": marker["schema_version"],
        "project_version": marker["project_version"],
        "artifact_version": marker["artifact_version"],
        "loop_run_id": marker["loop_run_id"],
        "bundle_revision": marker["bundle_revision"],
        "loop": marker["loop"],
        "ledger": marker["ledger"],
        "open_gaps": marker.get("open_gaps", []),
        "bottleneck": marker.get("bottleneck"),
        "delivery": marker.get("delivery", {"state": "not_ready"}),
    }
    if "version_binding" in marker:
        projection["release_version"] = marker["release_version"]
        projection["version_binding"] = copy.deepcopy(marker["version_binding"])
    return (
        "# Goal Teams V2.34 Progress\n\n"
        + "GTSTATE "
        + _canonical_bytes(projection).decode("ascii")
        + "\n"
    ).encode("utf-8")


def _decode_progress(data: bytes) -> dict[str, Any]:
    for line in data.decode("utf-8").splitlines():
        if line.startswith("GTSTATE "):
            value = json.loads(line.removeprefix("GTSTATE "))
            if isinstance(value, dict):
                return value
    raise ValueError("missing GTSTATE projection")


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(event)
    projected.pop("event_digest", None)
    return projected


def encode_log_event(event: dict[str, Any]) -> str:
    """Encode one canonical, grep-addressable GTLOG frame."""
    encoded = _event_payload(event)
    encoded["event_digest"] = _digest_bytes(_canonical_bytes(encoded))
    return "GTLOG " + _canonical_bytes(encoded).decode("ascii")


def _parse_log(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    prior: dict[str, Any] | None = None
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return [], ["E_V234_LOG_ENCODING"]
    for line_number, line in enumerate(lines, 1):
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith("GTLOG "):
            errors.append(f"E_V234_LOG_FRAME:{line_number}")
            continue
        try:
            event = json.loads(line.removeprefix("GTLOG "))
        except json.JSONDecodeError:
            errors.append(f"E_V234_LOG_JSON:{line_number}")
            continue
        if not isinstance(event, dict):
            errors.append(f"E_V234_LOG_FRAME:{line_number}")
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen:
            errors.append(f"E_V234_LOG_DUPLICATE_ID:{line_number}")
        else:
            seen.add(event_id)
        supplied = event.get("event_digest")
        if supplied != _digest_bytes(_canonical_bytes(_event_payload(event))):
            errors.append(f"E_V234_LOG_DIGEST:{line_number}")
        if prior is not None and (
            event.get("parent_event_id") != prior.get("event_id")
            or event.get("parent_event_digest") != prior.get("event_digest")
        ):
            errors.append(f"E_V234_LOG_CHAIN:{line_number}")
        event.setdefault("line_number", line_number)
        events.append(event)
        prior = event
    if data and not data.endswith(b"\n"):
        errors.append("E_V234_LOG_TRUNCATED")
    return events, errors


def _append_encoded_event(log_bytes: bytes, event: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    events, errors = _parse_log(log_bytes)
    if errors:
        raise ValueError(errors[0])
    if events:
        event.setdefault("parent_event_id", events[-1]["event_id"])
        event.setdefault("parent_event_digest", events[-1]["event_digest"])
    else:
        event.setdefault("parent_event_id", None)
        event.setdefault("parent_event_digest", None)
    line = encode_log_event(event)
    encoded = json.loads(line.removeprefix("GTLOG "))
    prefix = log_bytes if not log_bytes or log_bytes.endswith(b"\n") else log_bytes + b"\n"
    return prefix + line.encode("ascii") + b"\n", encoded


def _base_marker(
    *, loop_id: str, contract_bytes: bytes, ledger_binding: dict[str, Any],
    actor_run_id: str, initial_loop: dict[str, Any],
    legacy_import: dict[str, Any] | None = None,
    normalized_binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bytes]:
    binding = normalized_binding or _version_binding.default_version_binding()
    loop = {
        "iteration": int(initial_loop.get("iteration", 1)),
        "attempt": int(initial_loop.get("attempt", 1)),
        "phase": str(initial_loop.get("phase", "gather")),
        "loop_decision": "continue",
        "run_outcome": "partial",
        "stop_reason": "none",
        "verify_committed": False,
    }
    event = {
        "event_id": "LOG-V234-LEGACY-IMPORT-000001" if legacy_import else "LOG-V234-STATE-000001",
        "event_type": "LEGACY_IMPORT" if legacy_import else "STATE_COMMIT",
        "bundle_revision": 1,
        "iteration": loop["iteration"],
        "attempt": loop["attempt"],
        "phase": loop["phase"],
        "actor_run_id": actor_run_id,
        "timestamp": _now(),
        "intent_id": "INTENT-V234-LEGACY-IMPORT" if legacy_import else "INTENT-V234-BOOTSTRAP",
        "expected_constraints": ["four-file-marker-last", "legacy-digest-exact"] if legacy_import else ["four-file-marker-last"],
        "judgment": "Import exact legacy bytes by hash into a frozen recovery projection." if legacy_import else "Initialize a frozen revision-bound recovery projection.",
        "action_scope": ["feature_list.json", "progress.md", "contract.md", "log.md"],
        "prompt_ref": "prompts/lead/loop.md",
        "assertion_refs": ["ASSERT-V234-010", "ASSERT-V234-012", "ASSERT-V234-013", "ASSERT-V234-015"] if legacy_import else ["ASSERT-V234-010", "ASSERT-V234-012", "ASSERT-V234-013"],
        "outcome": "partial",
        **({"legacy_import": legacy_import} if legacy_import else {}),
    }
    log_bytes, commit_event = _append_encoded_event(b"", event)
    parsed = parse_contract_document(contract_bytes.decode("utf-8"))
    if not parsed.get("ok"):
        raise ValueError("invalid V2.34 contract")
    marker = {
        "schema_version": V234_STATE_SCHEMA,
        "project_version": binding["project_version"],
        "artifact_version": binding["artifact_version"],
        "loop_run_id": loop_id,
        "bundle_revision": 1,
        "loop": loop,
        "ledger": copy.deepcopy(ledger_binding),
        "contract": {
            "contract_revision": parsed["contract_revision"],
            "contract_sha256": _digest_bytes(contract_bytes),
            "assertion_set_sha256": parsed["assertion_set_sha256"],
            "preimplementation_gate_state": "not_started",
        },
        "open_gaps": [],
        "bottleneck": None,
        "reset": {"state": "not_due", "completed_iteration": None},
        "delivery": {"state": "not_ready"},
        "log_commit_event_id": commit_event["event_id"],
        "log_commit_event_digest": commit_event["event_digest"],
    }
    if binding.get("explicit") is True:
        marker["release_version"] = binding["release_version"]
        marker["version_binding"] = copy.deepcopy(binding)
    marker["contract_sha256"] = _digest_bytes(contract_bytes)
    marker["log_sha256"] = _digest_bytes(log_bytes)
    progress = _encode_progress(marker)
    marker["progress_sha256"] = _digest_bytes(progress)
    marker["bundle_digest"] = _marker_digest(marker)
    return marker, log_bytes


def _legacy_file_records(paths: dict[str, Path]) -> list[dict[str, Any]]:
    return [
        {"path": name, "sha256": _digest_path(paths[name]), "size": paths[name].stat().st_size}
        for name in sorted(paths)
    ]


def _legacy_derived_claim(value: Any, parent_key: str = "") -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {"preimplementation_gate_state", "gate_state", "implementation_gate"} and item in {"passed", "open", True}:
                return True
            if normalized == "task_state" and item == "accepted":
                return True
            if normalized == "check_state" and item == "passed":
                return True
            if normalized == "run_outcome" and item == "achieved":
                return True
            if normalized == "accepted" and item is True:
                return True
            if _legacy_derived_claim(item, normalized):
                return True
    elif isinstance(value, list):
        return any(_legacy_derived_claim(item, parent_key) for item in value)
    return False


def _ledger_replay_binding_valid(
    ledger_binding: dict[str, Any], ledger_events: list[dict[str, Any]] | None,
    checkpoint_bytes: bytes | None,
) -> bool:
    if not isinstance(ledger_events, list) or not ledger_events or checkpoint_bytes is None:
        return False
    try:
        checkpoint = json.loads(checkpoint_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(checkpoint, dict):
        return False
    checkpoint["_source_sha256"] = _digest_bytes(checkpoint_bytes)
    replay_binding, errors = _validate_ledger_checkpoint(ledger_events, checkpoint)
    return not errors and replay_binding == ledger_binding


def _initialize_state_bundle_locked(
    root: Path | str, *, repo_root: Path | str, loop_id: str,
    contract_path: Path | str, ledger_binding: dict[str, Any], actor_run_id: str,
    initial_loop: dict[str, Any] | None = None, adopt_legacy_digest: str | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    checkpoint_bytes: bytes | None = None,
    normalized_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the four-file bundle exactly once, with the marker replaced last."""
    state_root = Path(root)
    repository = Path(repo_root)
    try:
        if not state_root.is_dir() or state_root.is_symlink() or not repository.is_dir():
            return _error("E_V234_STATE_ROOT")
        paths = {name: state_root / name for name in ("feature_list.json", "progress.md", "contract.md", "log.md")}
        source = Path(contract_path)
        state_existing = {
            name: path.exists() or path.is_symlink() for name, path in paths.items()
        }
        if not source.is_file() or source.is_symlink():
            return _error("E_V234_CONTRACT_INPUT")
        fresh_contract_in_place = (
            source == paths["contract.md"]
            and state_existing["contract.md"]
            and not any(state_existing[name] for name in ("feature_list.json", "progress.md", "log.md"))
        )
        legacy_mode = all(state_existing.values())
        if any(state_existing.values()) and not fresh_contract_in_place and not legacy_mode:
            return _error("E_V234_LEGACY_FILES", observed_files=sorted(name for name, present in state_existing.items() if present))
        legacy_import: dict[str, Any] | None = None
        receipt_path: Path | None = None
        if legacy_mode:
            if any(path.is_symlink() or not path.is_file() for path in paths.values()):
                return _error("E_V234_LEGACY_FILES")
            records = _legacy_file_records(paths)
            observed_digest = _digest_bytes(_canonical_bytes(records))
            if adopt_legacy_digest is None:
                return _error("E_V234_LEGACY_ADOPTION_REQUIRED", observed_legacy_digest=observed_digest)
            if not _valid_hash(adopt_legacy_digest) or adopt_legacy_digest != observed_digest:
                return _error("E_V234_LEGACY_DIGEST", observed_legacy_digest=observed_digest)
            if source.resolve() != paths["contract.md"].resolve():
                return _error("E_V234_LEGACY_CONTRACT")
            try:
                legacy_feature = _json_object(paths["feature_list.json"])
            except (OSError, ValueError, json.JSONDecodeError):
                return _error("E_V234_LEGACY_STATE")
            if _legacy_derived_claim(legacy_feature):
                return _error("E_V234_LEGACY_DERIVED_STATE")
            if not _ledger_replay_binding_valid(ledger_binding, ledger_events, checkpoint_bytes):
                return _error("E_V234_LEGACY_LEDGER_REPLAY")
            legacy_import = {
                "legacy_digest": observed_digest,
                "files": records,
                "progress_sha256": next(item["sha256"] for item in records if item["path"] == "progress.md"),
                "log_sha256": next(item["sha256"] for item in records if item["path"] == "log.md"),
            }
            receipt_path = state_root / ".goalteams-state" / "receipts" / f"legacy-import-{observed_digest}.json"
        elif adopt_legacy_digest is not None:
            return _error("E_V234_LEGACY_FILES")
        contract_bytes = source.read_bytes()
        contract_validation = validate_contract_document(contract_bytes.decode("utf-8"))
        if not contract_validation.get("ok") or contract_validation.get("contract_revision") != 2:
            return _error("E_V234_LEGACY_CONTRACT" if legacy_mode else "E_V234_CONTRACT_INPUT")
        marker, log_bytes = _base_marker(
            loop_id=loop_id, contract_bytes=contract_bytes, ledger_binding=ledger_binding,
            actor_run_id=actor_run_id, initial_loop=initial_loop or {},
            legacy_import=legacy_import,
            normalized_binding=normalized_binding,
        )
        progress_bytes = _encode_progress(marker)
        transaction_id = f"TXN-V234-INIT-{os.getpid()}-{marker['bundle_revision']}"
        candidates = {
            "contract.md": contract_bytes,
            "log.md": log_bytes,
            "progress.md": progress_bytes,
            "feature_list.json": json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        }
        for name in ("contract.md", "log.md", "progress.md", "feature_list.json"):
            temp_path = _write_temp(paths[name], candidates[name], transaction_id)
            _replace_verified(temp_path, paths[name], allow_missing=True)
            _fsync_directory(state_root)
        if legacy_import is not None and receipt_path is not None:
            receipt = {
                "schema_version": "goal-teams-v2.34-legacy-import-receipt-v1",
                "transaction_id": transaction_id,
                "actor_run_id": actor_run_id,
                "legacy_import": legacy_import,
                "new_bundle_revision": marker["bundle_revision"],
                "new_bundle_digest": marker["bundle_digest"],
                "ledger": ledger_binding,
                "recorded_at": _now(),
            }
            _atomic_json(receipt_path, receipt)
        return _ok(
            schema_version=V234_CLI_SCHEMA, bundle_revision=marker["bundle_revision"],
            bundle_digest=marker["bundle_digest"], ledger_revision=marker["ledger"].get("revision"),
            transaction_id=transaction_id,
            legacy_imported=legacy_import is not None,
            legacy_import_receipt=str(receipt_path) if receipt_path is not None else None,
            **(
                {"version_binding_digest": normalized_binding["binding_digest"]}
                if isinstance(normalized_binding, dict) and normalized_binding.get("explicit") is True else {}
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error("E_V234_STATE_INIT", errors=[{"error": "E_V234_STATE_INIT", "type": type(exc).__name__}])


def initialize_state_bundle(
    root: Path | str, *, repo_root: Path | str, loop_id: str,
    contract_path: Path | str, ledger_binding: dict[str, Any], actor_run_id: str,
    initial_loop: dict[str, Any] | None = None, adopt_legacy_digest: str | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    checkpoint_bytes: bytes | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    binding_result = _binding_result(repo_root, version_binding)
    if not binding_result.get("ok"):
        return binding_result
    try:
        descriptor = _acquire_state_lock(state_root)
    except OSError:
        return _error("E_V234_STATE_LOCK_UNAVAILABLE")
    try:
        return _initialize_state_bundle_locked(
            state_root, repo_root=repo_root, loop_id=loop_id,
            contract_path=contract_path, ledger_binding=ledger_binding,
            actor_run_id=actor_run_id, initial_loop=initial_loop,
            adopt_legacy_digest=adopt_legacy_digest,
            ledger_events=ledger_events, checkpoint_bytes=checkpoint_bytes,
            normalized_binding=binding_result["binding"],
        )
    finally:
        _release_state_lock(descriptor)


def load_state_bundle(root: Path | str) -> dict[str, Any]:
    state_root = Path(root)
    marker = _json_object(state_root / "feature_list.json")
    marker["_progress_bytes"] = (state_root / "progress.md").read_bytes()
    marker["_contract_bytes"] = (state_root / "contract.md").read_bytes()
    marker["_log_bytes"] = (state_root / "log.md").read_bytes()
    return marker


def _pending_journals(state_root: Path) -> list[Path]:
    transaction_root = state_root / ".goalteams-state" / "transactions"
    if not transaction_root.is_dir() or transaction_root.is_symlink():
        return []
    pending: list[Path] = []
    for journal in sorted(transaction_root.glob("*/journal.json")):
        try:
            value = _json_object(journal)
        except (OSError, ValueError, json.JSONDecodeError):
            pending.append(journal)
            continue
        if value.get("phase") != "committed":
            pending.append(journal)
    return pending


def _journal_binding_errors(
    state_root: Path, normalized_binding: dict[str, Any]
) -> list[str]:
    if normalized_binding.get("explicit") is not True:
        return []
    errors: list[str] = []
    patterns = (
        ".goalteams-state/transactions/*/journal.json",
        ".goalteams-state/deliveries/*/journal.json",
    )
    for pattern in patterns:
        for journal_path in sorted(state_root.glob(pattern)):
            try:
                journal = _json_object(journal_path)
                if journal.get("version_binding_digest") != normalized_binding["binding_digest"]:
                    errors.append(f"E_V235_VERSION_BINDING_JOURNAL:{journal_path.name}")
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append(f"E_V235_VERSION_BINDING_JOURNAL:{journal_path.name}")
    return errors


def _record_divergent_hashes(state_root: Path, scope: str, records: list[dict[str, Any]]) -> str:
    payload = {
        "schema_version": "goal-teams-v2.34-divergence-receipt-v1",
        "scope": scope,
        "records": records,
        "recorded_at": _now(),
    }
    receipt_id = _digest_bytes(_canonical_bytes(payload))
    path = state_root / ".goalteams-state" / "divergence" / f"{receipt_id}.json"
    _atomic_json(path, payload)
    return str(path)


def validate_state_bundle(
    root: Path | str, *, ledger_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    names = ("feature_list.json", "progress.md", "contract.md", "log.md")
    missing = [name for name in names if not (state_root / name).is_file() or (state_root / name).is_symlink()]
    if missing:
        return _error("E_V234_STATE_FILES", state="blocked", errors=[f"E_V234_STATE_FILE:{name}" for name in missing])
    errors: list[str] = []
    try:
        marker = _json_object(state_root / "feature_list.json")
        marker_binding = _marker_binding(marker)
        if not marker_binding.get("ok"):
            return marker_binding
        if marker_binding["binding"].get("explicit") is True and repo_root is None:
            return _version_binding._error("E_V235_VERSION_BINDING_PROVENANCE")
        binding_result = _binding_result(
            repo_root or state_root, version_binding, marker=marker
        )
        if not binding_result.get("ok"):
            return binding_result
        progress_bytes = (state_root / "progress.md").read_bytes()
        contract_bytes = (state_root / "contract.md").read_bytes()
        log_bytes = (state_root / "log.md").read_bytes()
        if marker.get("schema_version") != V234_STATE_SCHEMA:
            errors.append("E_V234_STATE_SCHEMA")
        if marker.get("bundle_digest") != _marker_digest(marker):
            errors.append("E_V234_BUNDLE_DIGEST")
        for field, data in (
            ("progress_sha256", progress_bytes), ("contract_sha256", contract_bytes), ("log_sha256", log_bytes),
        ):
            if marker.get(field) != _digest_bytes(data):
                errors.append(f"E_V234_{field.upper()}")
        if marker.get("contract", {}).get("contract_sha256") != _digest_bytes(contract_bytes):
            errors.append("E_V234_CONTRACT_DIGEST")
        progress = _decode_progress(progress_bytes)
        progress_fields = [
            "schema_version", "project_version", "artifact_version", "loop_run_id",
            "bundle_revision", "loop", "ledger",
        ]
        if binding_result["binding"].get("explicit") is True:
            progress_fields.extend(("release_version", "version_binding"))
        for field in progress_fields:
            if progress.get(field) != marker.get(field):
                errors.append(f"E_V234_PROGRESS_BINDING:{field}")
        events, log_errors = _parse_log(log_bytes)
        errors.extend(log_errors)
        errors.extend(_journal_binding_errors(state_root, binding_result["binding"]))
        if not events or events[-1].get("event_id") != marker.get("log_commit_event_id") or events[-1].get("event_digest") != marker.get("log_commit_event_digest"):
            errors.append("E_V234_LOG_COMMIT_BINDING")
        if not isinstance(marker.get("ledger"), dict) or not all(
            marker["ledger"].get(key) for key in ("revision", "prefix_sha256", "checkpoint_sha256", "last_event_id")
        ):
            errors.append("E_V234_LEDGER_BINDING")
        pending = _pending_journals(state_root)
        if pending:
            return _error(
                "E_V234_RECOVERABLE_PENDING", state="recoverable_pending",
                errors=["E_V234_RECOVERABLE_PENDING", *errors],
                bundle_revision=marker.get("bundle_revision"), bundle_digest=marker.get("bundle_digest"),
            )
        if errors:
            return _error(
                "E_V234_RECONCILE_REQUIRED", state="reconcile_required", errors=sorted(set(errors)),
                bundle_revision=marker.get("bundle_revision"), bundle_digest=marker.get("bundle_digest"),
            )
        state = "ledger_unverified"
        if ledger_events is not None or checkpoint is not None:
            if ledger_events is None or checkpoint is None:
                return _error(
                    "E_V234_LEDGER_INPUT", state="blocked", errors=["E_V234_LEDGER_INPUT"],
                    bundle_revision=marker["bundle_revision"], bundle_digest=marker["bundle_digest"],
                )
            current_binding, ledger_errors = _validate_ledger_checkpoint(ledger_events, checkpoint)
            if ledger_errors or current_binding is None:
                return _error(
                    "E_V234_CHECKPOINT_REPLAY", state="blocked", errors=ledger_errors,
                    bundle_revision=marker["bundle_revision"], bundle_digest=marker["bundle_digest"],
                )
            marker_binding = marker["ledger"]
            marker_revision = marker_binding.get("revision")
            if marker_revision == current_binding["revision"]:
                if marker_binding != current_binding:
                    return _error(
                        "E_V234_LEDGER_BINDING", state="reconcile_required",
                        errors=["E_V234_LEDGER_BINDING"],
                        bundle_revision=marker["bundle_revision"], bundle_digest=marker["bundle_digest"],
                    )
                state = "valid"
            elif isinstance(marker_revision, int) and 0 < marker_revision < current_binding["revision"]:
                if (
                    marker_binding.get("prefix_sha256") != _ledger_prefix(ledger_events, marker_revision)
                    or marker_binding.get("last_event_id") != ledger_events[marker_revision - 1].get("event_id")
                    or not _valid_hash(marker_binding.get("checkpoint_sha256"))
                ):
                    return _error(
                        "E_V234_LEDGER_PREFIX", state="blocked", errors=["E_V234_LEDGER_PREFIX"],
                        bundle_revision=marker["bundle_revision"], bundle_digest=marker["bundle_digest"],
                    )
                state = "stale"
            else:
                return _error(
                    "E_V234_LEDGER_REVISION", state="blocked", errors=["E_V234_LEDGER_REVISION"],
                    bundle_revision=marker["bundle_revision"], bundle_digest=marker["bundle_digest"],
                )
        return _ok(
            state=state, errors=[], bundle_revision=marker["bundle_revision"],
            bundle_digest=marker["bundle_digest"], ledger_revision=marker["ledger"]["revision"], marker=marker,
            **(
                {"version_binding_digest": binding_result["binding"]["binding_digest"]}
                if binding_result["binding"].get("explicit") is True else {}
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _error(
            "E_V234_RECONCILE_REQUIRED", state="reconcile_required",
            errors=[{"error": "E_V234_STATE_PARSE", "type": type(exc).__name__}],
        )


def validate_loop_transition(current: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    phase = current.get("phase")
    iteration = current.get("iteration")
    attempt = current.get("attempt")
    if phase not in V234_PHASES or not isinstance(iteration, int) or iteration < 1 or iteration > 11 or not isinstance(attempt, int) or attempt < 1:
        return _error("E_V234_PHASE_TRANSITION")
    if request.get("loop_decision") == "stop":
        outcome = request.get("run_outcome")
        reason = request.get("stop_reason")
        if outcome not in V23_RUN_OUTCOMES - {"achieved"} or reason not in _STOP_REASONS - {"achieved"}:
            return _error("E_V234_STOP_STRUCTURE")
        next_state = {**current, "loop_decision": "stop", "run_outcome": outcome, "stop_reason": reason}
        return _ok(next_state=next_state)
    if request.get("run_outcome") == "achieved":
        return _error("E_V234_ACHIEVED_RESERVED")
    if request.get("retry") is True:
        return _ok(next_state={**current, "attempt": attempt + 1})
    target = request.get("to_phase")
    if (phase, target) not in V234_NORMAL_EDGES:
        return _error("E_V234_PHASE_TRANSITION")
    if iteration == 9 and phase == "reason" and target == "act" and current.get("reset_gate_current") is not True:
        return _error("E_V234_RESET_REQUIRED")
    if iteration == 11 and phase == "verify" and target == "repeat":
        return _error("E_V234_DELIVERY_REQUIRED")
    if iteration == 11 and phase == "repeat" and target == "gather":
        return _error("E_V234_CONTRACT_EXHAUSTED")
    requested_iteration = request.get("iteration", iteration)
    next_state = {**current, "phase": target}
    if phase == "repeat" and target == "gather":
        if current.get("verify_committed") is not True or current.get("loop_decision") not in {"continue", "replan"}:
            return _error("E_V234_PHASE_TRANSITION")
        expected_iteration = iteration + 1
        if requested_iteration not in {iteration, expected_iteration}:
            return _error("E_V234_PHASE_TRANSITION")
        next_state.update(iteration=expected_iteration, attempt=1, verify_committed=False)
    elif requested_iteration != iteration:
        return _error("E_V234_PHASE_TRANSITION")
    if target == "repeat":
        next_state["verify_committed"] = True
    return _ok(next_state=next_state)


def _transaction_journal_path(state_root: Path, transaction_id: str) -> Path:
    return state_root / ".goalteams-state" / "transactions" / transaction_id / "journal.json"


def _commit_bundle_bytes(
    state_root: Path, *, old_marker: dict[str, Any], new_marker: dict[str, Any],
    new_log: bytes, new_progress: bytes, transaction_id: str,
    replace_contract: bytes | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        lock_descriptor = _acquire_state_lock(state_root)
    except OSError:
        return _error("E_V234_STATE_LOCK_UNAVAILABLE")
    try:
        current_marker = _json_object(state_root / "feature_list.json")
        if (
            current_marker.get("bundle_revision") != old_marker.get("bundle_revision")
            or current_marker.get("bundle_digest") != old_marker.get("bundle_digest")
        ):
            return _error("E_V234_CAS_CONFLICT")
        return _commit_bundle_bytes_locked(
            state_root, old_marker=old_marker, new_marker=new_marker, new_log=new_log,
            new_progress=new_progress, transaction_id=transaction_id,
            replace_contract=replace_contract,
            repo_root=repo_root, version_binding=version_binding,
        )
    finally:
        _release_state_lock(lock_descriptor)


def _commit_bundle_bytes_locked(
    state_root: Path, *, old_marker: dict[str, Any], new_marker: dict[str, Any],
    new_log: bytes, new_progress: bytes, transaction_id: str,
    replace_contract: bytes | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    marker_binding = _marker_binding(new_marker)
    if not marker_binding.get("ok"):
        return marker_binding
    if marker_binding["binding"].get("explicit") is True:
        if repo_root is None:
            return _version_binding._error("E_V235_VERSION_BINDING_PROVENANCE")
        current_binding = _binding_result(
            repo_root, version_binding, marker=new_marker
        )
        if not current_binding.get("ok"):
            return current_binding
    candidates: list[tuple[str, bytes]] = []
    if replace_contract is not None:
        candidates.append(("contract.md", replace_contract))
    candidates.extend(
        [
            ("log.md", new_log),
            ("progress.md", new_progress),
            ("feature_list.json", json.dumps(new_marker, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"),
        ]
    )
    temp_paths = {name: _write_temp(state_root / name, data, transaction_id) for name, data in candidates}
    journal_path = _transaction_journal_path(state_root, transaction_id)
    journal = {
        "schema_version": V234_STATE_SCHEMA,
        "transaction_id": transaction_id,
        "phase": "prepared",
        "expected_bundle_revision": old_marker["bundle_revision"],
        "expected_bundle_digest": old_marker["bundle_digest"],
        "target_bundle_revision": new_marker["bundle_revision"],
        "target_bundle_digest": new_marker["bundle_digest"],
        "targets": {
            name: {
                "old_sha256": _digest_path(state_root / name),
                "new_sha256": _digest_bytes(data),
                "new_base64": base64.b64encode(data).decode("ascii"),
            }
            for name, data in candidates
        },
    }
    if marker_binding["binding"].get("explicit") is True:
        journal["version_binding_digest"] = marker_binding["binding"]["binding_digest"]
    _atomic_json(journal_path, journal)
    for name, _ in candidates:
        _replace_verified(temp_paths[name], state_root / name)
        _fsync_directory(state_root)
    journal["phase"] = "marker_replaced"
    _atomic_json(journal_path, journal)
    validation = validate_state_bundle(
        state_root, repo_root=repo_root, version_binding=version_binding,
    )
    # The current journal is intentionally still pending during validation.
    if validation.get("state") not in {"valid", "ledger_unverified", "recoverable_pending"}:
        return _error("E_V234_STATE_COMMIT", validation=validation)
    journal["phase"] = "committed"
    _atomic_json(journal_path, journal)
    return _ok(
        bundle_revision=new_marker["bundle_revision"], bundle_digest=new_marker["bundle_digest"],
        ledger_revision=new_marker.get("ledger", {}).get("revision"), transaction_id=transaction_id,
        **(
            {"version_binding_digest": marker_binding["binding"]["binding_digest"]}
            if marker_binding["binding"].get("explicit") is True else {}
        ),
    )


def transition_state_bundle(
    root: Path | str, *, to_phase: str | None = None,
    expected_bundle_revision: int, expected_bundle_digest: str, actor_run_id: str,
    side_effect: Callable[[], Any] | None = None, transition: dict[str, Any] | None = None,
    evidence_registry: dict[str, Any] | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    identity_registry: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    validation = validate_state_bundle(
        state_root, ledger_events=ledger_events, checkpoint=checkpoint,
        repo_root=repo_root, version_binding=version_binding,
    )
    if not validation.get("ok") or validation.get("state") != "valid":
        return _state_write_error(validation)
    marker = validation["marker"]
    if marker["bundle_revision"] != expected_bundle_revision or marker["bundle_digest"] != expected_bundle_digest:
        return _error("E_V234_CAS_CONFLICT")
    request = dict(transition or {})
    if to_phase is not None:
        request["to_phase"] = to_phase
    loop_context = copy.deepcopy(marker["loop"])
    if loop_context.get("iteration") == 9 and loop_context.get("phase") == "reason" and request.get("to_phase") == "act":
        reset_gate = evaluate_reset_gate(
            marker, target="act", evidence_registry=evidence_registry or {},
            ledger_events=ledger_events or [], identity_registry=identity_registry or {}, checkpoint=checkpoint,
        )
        loop_context["reset_gate_current"] = reset_gate.get("ok") is True
    loop_result = validate_loop_transition(loop_context, request)
    if not loop_result.get("ok"):
        return loop_result
    new_marker = copy.deepcopy(marker)
    new_marker["bundle_revision"] += 1
    new_loop = loop_result["next_state"]
    new_loop.pop("reset_gate_current", None)
    new_marker["loop"] = new_loop
    log_bytes = (state_root / "log.md").read_bytes()
    event = {
        "event_id": f"LOG-V234-STATE-{new_marker['bundle_revision']:06d}",
        "event_type": "STATE_COMMIT",
        "bundle_revision": new_marker["bundle_revision"],
        "iteration": new_marker["loop"]["iteration"],
        "attempt": new_marker["loop"]["attempt"],
        "phase": new_marker["loop"]["phase"],
        "actor_run_id": actor_run_id,
        "timestamp": _now(),
        "intent_id": f"INTENT-V234-STATE-{new_marker['bundle_revision']:06d}",
        "expected_constraints": ["persist-before-effect", "marker-last"],
        "judgment": "Commit the validated LOOP transition before side effects.",
        "action_scope": ["feature_list.json", "progress.md", "log.md"],
        "prompt_ref": "prompts/lead/loop.md",
        "assertion_refs": ["ASSERT-V234-009", "ASSERT-V234-010"],
        "outcome": new_marker["loop"].get("run_outcome", "partial"),
    }
    new_log, committed_event = _append_encoded_event(log_bytes, event)
    new_marker["log_commit_event_id"] = committed_event["event_id"]
    new_marker["log_commit_event_digest"] = committed_event["event_digest"]
    new_marker["log_sha256"] = _digest_bytes(new_log)
    new_progress = _encode_progress(new_marker)
    new_marker["progress_sha256"] = _digest_bytes(new_progress)
    new_marker["bundle_digest"] = _marker_digest(new_marker)
    transaction_id = f"TXN-V234-STATE-{new_marker['bundle_revision']:06d}-{os.getpid()}"
    result = _commit_bundle_bytes(
        state_root, old_marker=marker, new_marker=new_marker, new_log=new_log,
        new_progress=new_progress, transaction_id=transaction_id,
        repo_root=repo_root, version_binding=version_binding,
    )
    if result.get("ok") and side_effect is not None:
        side_effect()
    return result


def recover_state_bundle(
    root: Path | str, *, repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validate_state_bundle(
        root, repo_root=repo_root, version_binding=version_binding,
    )
    marker = None
    try:
        marker = _json_object(Path(root) / "feature_list.json")
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    loop = marker.get("loop", {}) if marker else {}
    phase = loop.get("phase")
    next_phase = dict(V234_NORMAL_EDGES).get(phase)
    return {
        "ok": validation.get("ok", False),
        "state": validation.get("state", "blocked"),
        "next_phase": next_phase,
        "iteration": loop.get("iteration"),
        "attempt": loop.get("attempt"),
        "open_gaps": marker.get("open_gaps", []) if marker else [],
        "side_effects_replayed": 0,
        "errors": validation.get("errors", []),
    }


def _state_write_error(validation: dict[str, Any]) -> dict[str, Any]:
    if str(validation.get("error_code", "")).startswith("E_V235_VERSION_BINDING_"):
        return validation
    if validation.get("state") in {"stale", "ledger_unverified"}:
        return _error("E_V234_LEDGER_REFRESH_REQUIRED", validation=validation)
    return _error("E_V234_STATE_INVALID", validation=validation)


def _reconcile_state_bundle_locked(
    root: Path | str, *, mode: str, expected_bundle_revision: int,
    expected_bundle_digest: str, ledger_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None, actor_run_id: str | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    if mode not in {"auto", "replay"}:
        return _error("E_V234_RECONCILE_MODE")
    if mode == "replay":
        validation = validate_state_bundle(
            state_root, ledger_events=ledger_events, checkpoint=checkpoint,
            repo_root=repo_root, version_binding=version_binding,
        )
        if validation.get("state") not in {"stale", "valid"}:
            return _error("E_V234_RECONCILE_EVIDENCE", validation=validation)
        marker = validation["marker"]
        if marker.get("bundle_revision") != expected_bundle_revision or marker.get("bundle_digest") != expected_bundle_digest:
            return _error("E_V234_CAS_CONFLICT")
        if validation.get("state") == "valid":
            return _ok(
                state="valid", idempotent=True, bundle_revision=marker["bundle_revision"],
                bundle_digest=marker["bundle_digest"],
            )
        current_binding, errors = _validate_ledger_checkpoint(ledger_events or [], checkpoint or {})
        if errors or current_binding is None or not actor_run_id:
            return _error("E_V234_RECONCILE_EVIDENCE", errors=errors or ["E_V234_RECONCILE_ACTOR"])
        new_marker = copy.deepcopy(marker)
        new_marker["bundle_revision"] += 1
        new_marker["ledger"] = current_binding
        event = {
            "event_id": f"LOG-V234-LEDGER-REFRESH-{new_marker['bundle_revision']:06d}",
            "event_type": "LEDGER_REFRESH",
            "bundle_revision": new_marker["bundle_revision"],
            "iteration": new_marker.get("loop", {}).get("iteration"),
            "attempt": new_marker.get("loop", {}).get("attempt"),
            "phase": new_marker.get("loop", {}).get("phase"),
            "actor_run_id": actor_run_id,
            "timestamp": _now(),
            "intent_id": f"INTENT-V234-LEDGER-REFRESH-{new_marker['bundle_revision']:06d}",
            "expected_constraints": ["ledger:replayed", "checkpoint:exact", "marker:last"],
            "judgment": "Refresh the state projection from the verified append-only ledger.",
            "action_scope": ["feature_list.json", "progress.md", "log.md"],
            "prompt_ref": "prompts/lead/loop.md",
            "assertion_refs": ["ASSERT-V234-012", "ASSERT-V234-015"],
            "outcome": new_marker.get("loop", {}).get("run_outcome", "partial"),
            "previous_ledger_revision": marker.get("ledger", {}).get("revision"),
            "current_ledger_revision": current_binding["revision"],
        }
        new_log, appended = _append_encoded_event((state_root / "log.md").read_bytes(), event)
        new_marker["log_commit_event_id"] = appended["event_id"]
        new_marker["log_commit_event_digest"] = appended["event_digest"]
        new_marker["log_sha256"] = _digest_bytes(new_log)
        new_progress = _encode_progress(new_marker)
        new_marker["progress_sha256"] = _digest_bytes(new_progress)
        new_marker["bundle_digest"] = _marker_digest(new_marker)
        result = _commit_bundle_bytes_locked(
            state_root, old_marker=marker, new_marker=new_marker, new_log=new_log,
            new_progress=new_progress,
            transaction_id=f"TXN-V234-LEDGER-REFRESH-{new_marker['bundle_revision']:06d}-{os.getpid()}",
            repo_root=repo_root, version_binding=version_binding,
        )
        if result.get("ok"):
            result["state"] = "valid"
            result["idempotent"] = False
        return result
    validation = validate_state_bundle(
        state_root, repo_root=repo_root, version_binding=version_binding,
    )
    if validation.get("state") != "recoverable_pending":
        return _error("E_V234_RECONCILE_EVIDENCE")
    # Only an internally prepared journal whose parent marker matches the CAS
    # may be rolled forward.  A forged high revision is never selected.
    journals = _pending_journals(state_root)
    if len(journals) != 1:
        return _error("E_V234_RECONCILE_EVIDENCE")
    try:
        journal = _json_object(journals[0])
        if (
            journal.get("expected_bundle_revision") != expected_bundle_revision
            or journal.get("expected_bundle_digest") != expected_bundle_digest
        ):
            return _error("E_V234_RECONCILE_EVIDENCE")
        for name in ("log.md", "progress.md", "feature_list.json"):
            target = journal.get("targets", {}).get(name)
            if not isinstance(target, dict) or not _valid_hash(target.get("new_sha256")):
                return _error("E_V234_RECONCILE_EVIDENCE")
            current = state_root / name
            if not current.is_file() or current.is_symlink():
                return _error("E_V234_RECONCILE_EVIDENCE")
            current_sha = _digest_path(current)
            if current_sha not in {target.get("old_sha256"), target.get("new_sha256")}:
                receipt = _record_divergent_hashes(
                    state_root, "state_reconcile",
                    [{"path": name, "observed_sha256": current_sha, "old_sha256": target.get("old_sha256"), "new_sha256": target.get("new_sha256")}],
                )
                return _error("E_V234_RECONCILE_EVIDENCE", divergence_receipt=receipt)
            if current_sha != target["new_sha256"]:
                data = base64.b64decode(target["new_base64"], validate=True)
                if _digest_bytes(data) != target["new_sha256"]:
                    return _error("E_V234_RECONCILE_EVIDENCE")
                temp = _write_temp(current, data, journal["transaction_id"] + "-replay")
                _replace_verified(temp, current)
                _fsync_directory(state_root)
        journal["phase"] = "committed"
        _atomic_json(journals[0], journal)
        final = validate_state_bundle(
            state_root, repo_root=repo_root, version_binding=version_binding,
        )
        if not final.get("ok"):
            return _error("E_V234_RECONCILE_EVIDENCE", validation=final)
        return _ok(
            state="valid", bundle_revision=final["bundle_revision"],
            bundle_digest=final["bundle_digest"], transaction_id=journal["transaction_id"],
        )
    except (OSError, ValueError, json.JSONDecodeError, KeyError):
        return _error("E_V234_RECONCILE_EVIDENCE")


def reconcile_state_bundle(
    root: Path | str, *, mode: str, expected_bundle_revision: int,
    expected_bundle_digest: str, ledger_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None, actor_run_id: str | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    try:
        pre_marker = _json_object(state_root / "feature_list.json")
        structural = _marker_binding(pre_marker)
    except (OSError, ValueError, json.JSONDecodeError):
        structural = None
    if isinstance(structural, dict) and structural.get("ok") and structural["binding"].get("explicit") is True:
        if repo_root is None:
            return _version_binding._error("E_V235_VERSION_BINDING_PROVENANCE")
        preflight = _binding_result(repo_root, version_binding, marker=pre_marker)
        if not preflight.get("ok"):
            return preflight
    try:
        descriptor = _acquire_state_lock(state_root)
    except OSError:
        return _error("E_V234_STATE_LOCK_UNAVAILABLE")
    try:
        return _reconcile_state_bundle_locked(
            state_root, mode=mode, expected_bundle_revision=expected_bundle_revision,
            expected_bundle_digest=expected_bundle_digest,
            ledger_events=ledger_events, checkpoint=checkpoint, actor_run_id=actor_run_id,
            repo_root=repo_root, version_binding=version_binding,
        )
    finally:
        _release_state_lock(descriptor)


def append_log_event(
    root: Path | str, event: dict[str, Any], *, expected_bundle_revision: int,
    expected_bundle_digest: str,
    ledger_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    validation = validate_state_bundle(
        state_root, ledger_events=ledger_events, checkpoint=checkpoint,
        repo_root=repo_root, version_binding=version_binding,
    )
    if not validation.get("ok"):
        return _state_write_error(validation)
    marker = validation["marker"]
    if marker["bundle_revision"] != expected_bundle_revision or marker["bundle_digest"] != expected_bundle_digest:
        return _error("E_V234_CAS_CONFLICT")
    events, errors = _parse_log((state_root / "log.md").read_bytes())
    if errors:
        return _error("E_V234_LOG_INVALID", errors=errors)
    if any(item.get("event_id") == event.get("event_id") for item in events):
        return _error("E_V234_LOG_DUPLICATE_ID")
    new_marker = copy.deepcopy(marker)
    new_marker["bundle_revision"] += 1
    candidate = copy.deepcopy(event)
    candidate["bundle_revision"] = new_marker["bundle_revision"]
    try:
        new_log, appended = _append_encoded_event((state_root / "log.md").read_bytes(), candidate)
    except ValueError:
        return _error("E_V234_LOG_INVALID")
    new_marker["log_commit_event_id"] = appended["event_id"]
    new_marker["log_commit_event_digest"] = appended["event_digest"]
    new_marker["log_sha256"] = _digest_bytes(new_log)
    new_progress = _encode_progress(new_marker)
    new_marker["progress_sha256"] = _digest_bytes(new_progress)
    new_marker["bundle_digest"] = _marker_digest(new_marker)
    return _commit_bundle_bytes(
        state_root, old_marker=marker, new_marker=new_marker, new_log=new_log,
        new_progress=new_progress,
        transaction_id=f"TXN-V234-LOG-{new_marker['bundle_revision']:06d}-{os.getpid()}",
        repo_root=repo_root, version_binding=version_binding,
    )


def _commit_projection_update(
    root: Path | str, *, expected_bundle_revision: int, expected_bundle_digest: str,
    actor_run_id: str, event_type: str, assertion_refs: list[str],
    mutation: Callable[[dict[str, Any]], None], event_data: dict[str, Any] | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    validation = validate_state_bundle(
        state_root, ledger_events=ledger_events, checkpoint=checkpoint,
        repo_root=repo_root, version_binding=version_binding,
    )
    if not validation.get("ok"):
        return _state_write_error(validation)
    marker = validation["marker"]
    if marker["bundle_revision"] != expected_bundle_revision or marker["bundle_digest"] != expected_bundle_digest:
        return _error("E_V234_CAS_CONFLICT")
    new_marker = copy.deepcopy(marker)
    new_marker["bundle_revision"] += 1
    mutation(new_marker)
    event = {
        "event_id": f"LOG-V234-{event_type}-{new_marker['bundle_revision']:06d}",
        "event_type": event_type,
        "bundle_revision": new_marker["bundle_revision"],
        "iteration": new_marker.get("loop", {}).get("iteration"),
        "attempt": new_marker.get("loop", {}).get("attempt"),
        "phase": new_marker.get("loop", {}).get("phase"),
        "actor_run_id": actor_run_id,
        "timestamp": _now(),
        "intent_id": f"INTENT-V234-{event_type}-{new_marker['bundle_revision']:06d}",
        "expected_constraints": assertion_refs,
        "judgment": f"Persist validated {event_type} projection.",
        "action_scope": ["feature_list.json", "progress.md", "log.md"],
        "prompt_ref": "prompts/lead/loop.md",
        "assertion_refs": assertion_refs,
        "outcome": new_marker.get("loop", {}).get("run_outcome", "partial"),
        **(event_data or {}),
    }
    new_log, appended = _append_encoded_event((state_root / "log.md").read_bytes(), event)
    new_marker["log_commit_event_id"] = appended["event_id"]
    new_marker["log_commit_event_digest"] = appended["event_digest"]
    new_marker["log_sha256"] = _digest_bytes(new_log)
    new_progress = _encode_progress(new_marker)
    new_marker["progress_sha256"] = _digest_bytes(new_progress)
    new_marker["bundle_digest"] = _marker_digest(new_marker)
    return _commit_bundle_bytes(
        state_root, old_marker=marker, new_marker=new_marker, new_log=new_log,
        new_progress=new_progress,
        transaction_id=f"TXN-V234-{event_type}-{new_marker['bundle_revision']:06d}-{os.getpid()}",
        repo_root=repo_root, version_binding=version_binding,
    )


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        result[key.strip()] = raw.strip().strip('"').strip("'")
    return result


def parse_contract_document(text: str) -> dict[str, Any]:
    """Parse the immutable five-column assertion table without a YAML dependency."""
    metadata = _frontmatter(text)
    assertions: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not re.match(r"^\|\s*ASSERT-V234-[0-9]{3}\s*\|", line):
            continue
        columns = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(columns) != 5:
            return _error("E_V234_CONTRACT_ASSERTION_SCHEMA")
        identifier, assertion, required, verifier, content_state = columns
        assertions.append(
            {
                "id": identifier,
                "assertion": assertion,
                "required": required.lower() == "true",
                "planned_verifier": verifier,
                "content_state": content_state,
            }
        )
    try:
        revision = int(metadata.get("contract_revision", "0"))
        expected_count = int(metadata.get("required_assertion_count", "0"))
    except ValueError:
        return _error("E_V234_CONTRACT_METADATA")
    expected_ids = [f"ASSERT-V234-{number:03d}" for number in range(1, 53)]
    if (
        metadata.get("type") != "V2.34 Execution Contract"
        or revision < 1
        or expected_count != 52
        or len(assertions) != 52
        or [item["id"] for item in assertions] != expected_ids
        or any(
            not item["assertion"]
            or item["required"] is not True
            or not item["planned_verifier"]
            or item["content_state"] != "frozen"
            for item in assertions
        )
    ):
        return _error("E_V234_CONTRACT_ASSERTION_SCHEMA")
    return _ok(
        contract_revision=revision,
        assertion_content_state=metadata.get("assertion_content_state"),
        owner_run_id=metadata.get("owner_run_id") or metadata.get("owner_agent_run_id"),
        validator_run_id=metadata.get("validator_run_id") or metadata.get("validator_agent_run_id"),
        assertions=assertions,
        assertion_set_sha256=_digest_bytes(_canonical_bytes(assertions)),
        metadata=metadata,
    )


def validate_contract_document(
    text: str, *, previous_contract_text: str | None = None,
    external_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = _frontmatter(text)
    if _DERIVED_CONTRACT_KEYS & set(metadata):
        return _error("E_V234_CONTRACT_DERIVED_STATE")
    parsed = parse_contract_document(text)
    if not parsed.get("ok"):
        return parsed
    if parsed.get("assertion_content_state") != "frozen":
        return _error("E_V234_CONTRACT_ASSERTION_SCHEMA")
    if previous_contract_text is not None and text.encode("utf-8") != previous_contract_text.encode("utf-8"):
        previous = parse_contract_document(previous_contract_text)
        if previous.get("ok") and previous.get("contract_revision") == parsed.get("contract_revision"):
            return _error("E_V234_CONTRACT_REVISION_REQUIRED")
    return parsed


def _identity_present(registry: dict[str, Any], run_id: Any) -> bool:
    if not isinstance(run_id, str) or not run_id:
        return False
    runs = registry.get("runs")
    if isinstance(runs, dict) and run_id in runs:
        return True
    identities = registry.get("identities")
    if isinstance(identities, list):
        return any(
            isinstance(item, dict) and item.get("agent_run_id") == run_id
            for item in identities
        )
    return run_id in registry


def _ledger_prefix(events: list[dict[str, Any]], revision: int) -> str | None:
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0 or revision > len(events):
        return None
    projection = [
        {key: value for key, value in event.items() if key != "event_digest"}
        for event in events[:revision]
    ]
    return _digest_bytes(_canonical_bytes(projection))


def _checkpoint_digest(checkpoint: dict[str, Any]) -> str:
    supplied = checkpoint.get("_source_sha256")
    if _valid_hash(supplied):
        return str(supplied)
    projected = {key: value for key, value in checkpoint.items() if not str(key).startswith("_")}
    return _digest_bytes(_canonical_bytes(projected))


def _runtime_v23_schema_hash() -> str | None:
    """Return the hash of the canonical V2.3 schema shipped with this runtime.

    A checkpoint-provided hash is provenance, not authority.  Reading the
    repository schema here prevents a caller from changing both a checkpoint
    and its externally supplied digest and thereby blessing a different state
    language during recovery/adoption.
    """
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "v2.3" / "goal-teams.schema.json"
    try:
        if not _regular_single_link(schema_path):
            return None
        return _digest_path(schema_path)
    except OSError:
        return None


def _validate_ledger_checkpoint(
    ledger_events: list[dict[str, Any]], checkpoint: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not isinstance(ledger_events, list) or not ledger_events or not isinstance(checkpoint, dict):
        return None, ["E_V234_LEDGER_INPUT"]
    revision = checkpoint.get("ledger_revision")
    if checkpoint.get("schema_version") != "goal-teams-v2.3":
        errors.append("E_V234_CHECKPOINT_SCHEMA")
    runtime_schema_hash = _runtime_v23_schema_hash()
    if runtime_schema_hash is None or checkpoint.get("schema_source_hash") != runtime_schema_hash:
        errors.append("E_V234_CHECKPOINT_SCHEMA")
    if revision != len(ledger_events) or checkpoint.get("revision") not in {None, revision}:
        errors.append("E_V234_LEDGER_REVISION")
    event_digests: dict[str, str] = {}
    seen: list[str] = []
    for event in ledger_events:
        if not isinstance(event, dict) or event.get("schema_version") != "goal-teams-v2.3":
            errors.append("E_V234_LEDGER_EVENT")
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in event_digests:
            errors.append("E_V234_LEDGER_EVENT")
            continue
        digest = _digest_bytes(_canonical_bytes({key: value for key, value in event.items() if key != "event_digest"}))
        if event.get("event_digest") is not None and event.get("event_digest") != digest:
            errors.append("E_V234_LEDGER_EVENT_DIGEST")
        event_digests[event_id] = digest
        seen.append(event_id)
    if checkpoint.get("event_digests") != event_digests:
        errors.append("E_V234_CHECKPOINT_REPLAY")
    if checkpoint.get("seen_events") != seen:
        errors.append("E_V234_CHECKPOINT_REPLAY")
    tasks = checkpoint.get("tasks")
    if checkpoint.get("conflicts") != [] or not isinstance(tasks, dict) or not tasks:
        errors.append("E_V234_CHECKPOINT_REPLAY")
    # Canonical ``reduce_events`` checkpoints historically omit a top-level
    # ``last_event_id``; when a producer supplies it, it must still agree with
    # the replay.  The authoritative ordering remains ``seen_events``.
    if checkpoint.get("last_event_id") is not None and checkpoint.get("last_event_id") != (seen[-1] if seen else None):
        errors.append("E_V234_CHECKPOINT_REPLAY")
    owners = {event.get("ledger_owner_run_id") for event in ledger_events if event.get("ledger_owner_run_id")}
    if len(owners) != 1 or checkpoint.get("ledger_owner_run_id") != next(iter(owners), None):
        errors.append("E_V234_CHECKPOINT_OWNER")
    if errors:
        return None, sorted(set(errors))
    binding = {
        "revision": revision,
        "prefix_sha256": _ledger_prefix(ledger_events, revision),
        "checkpoint_sha256": _checkpoint_digest(checkpoint),
        "last_event_id": seen[-1],
    }
    return binding, []


def _validated_registry(
    wrapper: dict[str, Any], ledger_events: list[dict[str, Any]], checkpoint: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    if not isinstance(wrapper, dict) or wrapper.get("schema_version") != "goal-teams-v2.34-validated-evidence-registry-v1":
        return None, "E_V234_EVIDENCE_REGISTRY"
    records = wrapper.get("records")
    valid_ids = wrapper.get("valid_evidence_ids")
    if not isinstance(records, dict) or not isinstance(valid_ids, list) or set(valid_ids) != set(records):
        return None, "E_V234_EVIDENCE_REGISTRY"
    if wrapper.get("records_sha256") != _digest_bytes(_canonical_bytes(records)):
        return None, "E_V234_EVIDENCE_REGISTRY"
    registry_path = Path(str(wrapper.get("registry_source_path", "")))
    evidence_root = Path(str(wrapper.get("evidence_root", "")))
    source_root_value = wrapper.get("source_root")
    source_root = Path(str(source_root_value)) if source_root_value else None
    try:
        if (
            not registry_path.is_file() or registry_path.is_symlink()
            or _digest_path(registry_path) != wrapper.get("registry_source_sha256")
            or not evidence_root.is_dir() or evidence_root.is_symlink()
        ):
            return None, "E_V234_EVIDENCE_REGISTRY"
        raw_records = {
            item["evidence_id"]: item
            for line in registry_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
            for item in [json.loads(line)]
            if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)
        }
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
        return None, "E_V234_EVIDENCE_REGISTRY"
    validation_receipts = wrapper.get("validation")
    if not isinstance(validation_receipts, dict) or set(validation_receipts) != set(records):
        return None, "E_V234_EVIDENCE_REGISTRY"
    revision = wrapper.get("ledger_revision")
    prefix = _ledger_prefix(ledger_events, revision)
    if (
        prefix is None
        or wrapper.get("ledger_prefix_sha256") != prefix
        or checkpoint.get("ledger_revision") != revision
        or checkpoint.get("conflicts") not in ([], None)
        or wrapper.get("checkpoint_sha256") != _checkpoint_digest(checkpoint)
    ):
        return None, "E_V234_EVIDENCE_LEDGER"
    event_digests = {
        str(event.get("event_id")): _digest_bytes(_canonical_bytes({key: value for key, value in event.items() if key != "event_digest"}))
        for event in ledger_events[:revision]
    }
    if checkpoint.get("event_digests") != event_digests:
        return None, "E_V234_EVIDENCE_LEDGER"
    for evidence_id, record in records.items():
        receipt = validation_receipts.get(evidence_id, {})
        raw = raw_records.get(evidence_id)
        if (
            not isinstance(record, dict) or not isinstance(raw, dict)
            or any(record.get(key) != value for key, value in raw.items())
            or record.get("evidence_id") != evidence_id
            or record.get("trust_level") != "local_verified"
            or receipt != {"structurally_valid": True, "valid_for_acceptance": True, "current": True}
            or record.get("structurally_valid") is not True
            or record.get("valid_for_acceptance") is not True
        ):
            return None, "E_V234_EVIDENCE_REGISTRY"
        try:
            artifact = evidence_root.joinpath(*PurePosixPath(str(record["artifact_ref"])).parts)
            command = record.get("command", {})
            replay = record.get("integrity_replay", {})
            bound_files = (
                (artifact, record.get("artifact_sha256"), record.get("artifact_size")),
                (evidence_root.joinpath(*PurePosixPath(str(command["log_path"])).parts), command.get("log_sha256"), command.get("log_size")),
                (evidence_root.joinpath(*PurePosixPath(str(command["execution_record_path"])).parts), command.get("execution_record_sha256"), command.get("execution_record_size")),
                (evidence_root.joinpath(*PurePosixPath(str(replay["log_path"])).parts), replay.get("log_sha256"), replay.get("log_size")),
            )
            for path, digest, size in bound_files:
                if (
                    not path.resolve().is_relative_to(evidence_root.resolve())
                    or not _regular_single_link(path)
                    or _digest_path(path) != digest
                    or path.stat().st_size != size
                ):
                    return None, "E_V234_EVIDENCE_FILES"
            if command.get("exit_code") != 0 or replay.get("exit_code") != 0:
                return None, "E_V234_EVIDENCE_FILES"
            if source_root is not None:
                for relative in record.get("source_paths", record.get("environment", {}).get("source_paths", [])):
                    source = source_root.joinpath(*PurePosixPath(str(relative)).parts)
                    if not source.resolve().is_relative_to(source_root.resolve()) or not _regular_single_link(source):
                        return None, "E_V234_EVIDENCE_FILES"
        except (OSError, KeyError, ValueError):
            return None, "E_V234_EVIDENCE_FILES"
    return records, None


def evaluate_contract_gate(
    contract: str | dict[str, Any], identity_registry: dict[str, Any],
    ledger_events: list[dict[str, Any]], review_record: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(contract, dict):
        contract_text = contract.get("text", "")
    else:
        contract_text = contract
    parsed = validate_contract_document(contract_text)
    if not parsed.get("ok"):
        return parsed
    owner_run_id = parsed.get("owner_run_id") or review_record.get("owner_run_id")
    validator_run_id = review_record.get("validator_run_id")
    if (
        not _identity_present(identity_registry, owner_run_id)
        or not _identity_present(identity_registry, validator_run_id)
        or owner_run_id == validator_run_id
    ):
        return _error("E_V234_CONTRACT_REVIEW_IDENTITY")
    review_core = {key: value for key, value in review_record.items() if key != "record_sha256"}
    review_sha = _digest_bytes(_canonical_bytes(review_core))
    assertions = review_record.get("assertions")
    if (
        review_record.get("decision") != "passed"
        or review_record.get("contract_revision") != parsed["contract_revision"]
        or review_record.get("contract_sha256") != _digest_bytes(contract_text.encode("utf-8"))
        or review_record.get("assertion_set_sha256") != parsed["assertion_set_sha256"]
        or review_record.get("record_sha256") != review_sha
        or not isinstance(assertions, list)
        or [item.get("assertion_id") for item in assertions] != [item["id"] for item in parsed["assertions"]]
        or any(item.get("decision") != "accepted" for item in assertions)
    ):
        return _error("E_V234_CONTRACT_REVIEW")
    candidates = [
        event for event in ledger_events
        if event.get("event_type") == "check_executed"
        and isinstance(event.get("payload"), dict)
        and isinstance(event["payload"].get("v234_contract_gate"), dict)
    ]
    if not candidates:
        return _error("E_V234_CONTRACT_GATE")
    event = candidates[-1]
    payload = event["payload"]
    extension = payload["v234_contract_gate"]
    if event.get("actor_run_id") != validator_run_id or event.get("actor_run_id") == owner_run_id:
        return _error("E_V234_CONTRACT_REVIEW_IDENTITY")
    expected = {
        "preimplementation_gate_state": "passed",
        "contract_revision": parsed["contract_revision"],
        "contract_sha256": _digest_bytes(contract_text.encode("utf-8")),
        "assertion_set_sha256": parsed["assertion_set_sha256"],
        "external_review_ref": review_record.get("review_ref"),
        "external_review_sha256": review_sha,
        "reviewed_ledger_revision": review_record.get("reviewed_ledger_revision"),
        "reviewed_ledger_prefix_sha256": review_record.get("reviewed_ledger_prefix_sha256"),
        "decision": "passed",
    }
    if (
        payload.get("task_state") != "review"
        or payload.get("check_state") == "passed"
        or any(extension.get(key) != value for key, value in expected.items())
        or not isinstance(extension.get("decided_at"), str)
    ):
        return _error("E_V234_CONTRACT_GATE")
    return _ok(
        task_state="review", check_state=payload.get("check_state"),
        preimplementation_gate_state="passed", accepted=False,
        contract_revision=parsed["contract_revision"],
        contract_sha256=expected["contract_sha256"],
        assertion_set_sha256=parsed["assertion_set_sha256"],
        external_review_sha256=review_sha,
        gate_event_id=event.get("event_id"),
    )


def run_guarded_implementation_action(gate: dict[str, Any], action: Callable[[], Any]) -> dict[str, Any]:
    if not gate.get("ok") or gate.get("preimplementation_gate_state") != "passed":
        return _error("E_V234_IMPLEMENTATION_GATE", mutation_count=0)
    result = action()
    return _ok(mutation_count=1, result=result)


def evaluate_final_contract_acceptance(
    bootstrap_gate: dict[str, Any], *, strict_evidence: dict[str, Any] | None,
    check_event: dict[str, Any] | None, review_event: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence_id = strict_evidence.get("evidence_id") if isinstance(strict_evidence, dict) else None
    accepted = bool(
        bootstrap_gate.get("ok")
        and bootstrap_gate.get("preimplementation_gate_state") == "passed"
        and strict_evidence
        and strict_evidence.get("trust_level") == "local_verified"
        and strict_evidence.get("current") is True
        and check_event
        and check_event.get("event_type") == "check_executed"
        and check_event.get("check_state") == "passed"
        and evidence_id in check_event.get("evidence_refs", [])
        and review_event
        and review_event.get("event_type") == "review_completed"
        and review_event.get("task_state") == "accepted"
        and check_event.get("actor_run_id") == review_event.get("actor_run_id")
    )
    return _ok(accepted=accepted) if accepted else _error("E_V234_CONTRACT_ACCEPTANCE", accepted=False)


def validate_environment_readiness(
    record: dict[str, Any], architecture: dict[str, Any], identity_registry: dict[str, Any],
) -> dict[str, Any]:
    if (
        architecture.get("state") != "accepted"
        or architecture.get("review_state") != "passed"
        or architecture.get("owner_run_id") == architecture.get("validator_run_id")
        or record.get("architecture_sha256") != architecture.get("artifact_sha256")
        or record.get("architecture_accepted_event_id") != architecture.get("accepted_event_id")
    ):
        return _error("E_V234_ARCHITECTURE_GATE")
    required = (
        "architecture_ref", "architecture_sha256", "workspace_fingerprint", "tool_versions",
        "dependency_checks", "permission_checks", "service_checks", "gaps", "remediation",
        "execution_logs", "conclusion", "owner_run_id", "validator_run_id",
    )
    if any(key not in record for key in required) or record.get("conclusion") not in {"ready", "needs_remediation", "blocked"}:
        return _error("E_V234_ENVIRONMENT_SCHEMA")
    if (
        not _valid_hash(record.get("workspace_fingerprint"))
        or not isinstance(record.get("tool_versions"), dict)
        or not record["tool_versions"]
        or not isinstance(record.get("execution_logs"), list)
        or not record["execution_logs"]
        or record.get("owner_run_id") == record.get("validator_run_id")
        or not _identity_present(identity_registry, record.get("owner_run_id"))
        or not _identity_present(identity_registry, record.get("validator_run_id"))
    ):
        return _error("E_V234_ENVIRONMENT_SCHEMA")
    unsafe = {"system_install", "credential_write", "external_write", "destructive_config"}
    for remediation in record.get("remediation", []):
        if remediation.get("kind") in unsafe and remediation.get("authority") != "granted":
            return _error("E_V234_REMEDIATION_AUTHORIZATION", conclusion="blocked")
    return _ok(conclusion=record["conclusion"], workspace_fingerprint=record["workspace_fingerprint"])


def evaluate_implementation_gate(
    bundle: dict[str, Any], task_id: str, ledger_events: list[dict[str, Any]],
    evidence_registry: dict[str, Any], *, checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = bundle.get("contract", {})
    environment = bundle.get("development_environment", {})
    architecture = environment.get("architecture", {})
    check = environment.get("check", {})
    if contract.get("preimplementation_gate_state") != "passed" or architecture.get("state") != "accepted":
        return _error("E_V234_IMPLEMENTATION_GATE")
    if checkpoint is None:
        return _error("E_V234_EVIDENCE_LEDGER")
    records, registry_error = _validated_registry(evidence_registry, ledger_events, checkpoint)
    if registry_error:
        return _error(registry_error)
    refs = check.get("evidence_refs", [])
    evidence = records.get(refs[0]) if records is not None and isinstance(refs, list) and len(refs) == 1 else None
    environment_binding = evidence.get("environment", {}) if isinstance(evidence, dict) else {}
    if (
        check.get("state") != "ready"
        or check.get("based_on_architecture_sha256") != architecture.get("artifact_sha256")
        or not evidence
        or evidence.get("trust_level") != "local_verified"
        or evidence.get("artifact_sha256") != check.get("report_sha256")
        or environment_binding.get("workspace_fingerprint") != check.get("workspace_fingerprint")
        or environment_binding.get("ledger_prefix_sha256") != _ledger_prefix(
            ledger_events, environment_binding.get("ledger_revision")
        )
        or environment_binding.get("ledger_revision", 0) > evidence_registry.get("ledger_revision", -1)
        or evidence.get("producer_run_id") == bundle.get("implementation_owner_run_id")
    ):
        return _error("E_V234_ENVIRONMENT_STALE")
    binding = {
        "bundle_revision": bundle.get("bundle_revision"),
        "bundle_digest": bundle.get("bundle_digest"),
        "contract_revision": contract.get("contract_revision"),
        "contract_sha256": contract.get("contract_sha256"),
        "assertion_set_sha256": contract.get("assertion_set_sha256"),
        "external_review_sha256": contract.get("external_review_sha256"),
        "architecture_sha256": architecture.get("artifact_sha256"),
        "environment_report_sha256": check.get("report_sha256"),
        "workspace_fingerprint": check.get("workspace_fingerprint"),
    }
    return _ok(task_id=task_id, gate_state="open", v234_gate_binding=binding)


def validate_quality_scores(record: dict[str, Any]) -> dict[str, Any]:
    dimensions = record.get("dimensions")
    computed: dict[str, float] = {}
    errors: list[str] = []
    if record.get("rubric_version") != "v234-rubric-revision-1" or not _valid_hash(record.get("artifact_sha256")):
        errors.append("E_V234_SCORE_SCHEMA")
    if record.get("artifact_owner_run_id") == record.get("reviewer_run_id") or not record.get("reviewer_run_id"):
        errors.append("E_V234_SCORE_IDENTITY")
    if not isinstance(dimensions, dict) or set(dimensions) != set(_SCORE_DIMENSIONS):
        return _error("E_V234_SCORE_SCHEMA", computed_scores=computed, check_state="failed", implicit_release_threshold=False)
    unverified = False
    for dimension in _SCORE_DIMENSIONS:
        entry = dimensions.get(dimension, {})
        score = entry.get("score")
        items = entry.get("items")
        if (
            not isinstance(score, (int, float)) or isinstance(score, bool)
            or not math.isfinite(score) or not 0 <= score <= 1
            or not isinstance(items, list) or len(items) != 4
        ):
            errors.append("E_V234_SCORE_SCHEMA")
            computed[dimension] = 0.0
            continue
        passed = 0
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append("E_V234_SCORE_SCHEMA")
                continue
            status_value = item.get("status")
            if (
                item.get("criterion_id") != _SCORE_CRITERIA[dimension][index]
                or item.get("weight") != 0.25
                or status_value not in _SCORE_STATUSES
                or item.get("artifact_sha256") != record.get("artifact_sha256")
                or not isinstance(item.get("evidence_refs"), list)
                or not item.get("evidence_refs")
                or not item.get("rationale")
            ):
                errors.append("E_V234_SCORE_SCHEMA")
            if status_value == "passed":
                passed += 1
            elif status_value == "unverified":
                unverified = True
        computed[dimension] = passed / 4
        if score != computed[dimension]:
            errors.append("E_V234_SCORE_RECOMPUTE")
    if unverified:
        errors.append("E_V234_SCORE_UNVERIFIED")
    code = "E_V234_SCORE_RECOMPUTE" if "E_V234_SCORE_RECOMPUTE" in errors else (errors[0] if errors else "OK")
    if errors:
        return _error(code, errors=sorted(set(errors)), computed_scores=computed, check_state="failed", implicit_release_threshold=False)
    return _ok(computed_scores=computed, check_state="passed", implicit_release_threshold=False)


def scores_satisfy_completion(record: dict[str, Any], checks: dict[str, bool]) -> dict[str, Any]:
    score_result = validate_quality_scores(record)
    gaps = sorted(key for key, value in checks.items() if value is not True)
    if not score_result.get("ok"):
        gaps.append("scores")
    return {
        "completion_allowed": not gaps,
        "gaps": gaps,
        "scores": score_result,
    }


def diagnose_log_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    intents = {event.get("intent_id"): event for event in events if event.get("event_type") == "INTENT"}
    seen_intents: set[str] = set()
    divergences: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "JUDGMENT":
            continue
        intent_id = event.get("intent_id")
        if intent_id in seen_intents or intent_id not in intents:
            continue
        intent = intents[intent_id]
        required = set(intent.get("required_assertion_refs", intent.get("assertion_refs", [])))
        actual_assertions = set(event.get("assertion_refs", []))
        expected_constraints = set(intent.get("expected_constraints", []))
        actual_constraints = set(event.get("judgment_constraints", event.get("expected_constraints", [])))
        expected_scope = set(intent.get("action_scope", []))
        actual_scope = set(event.get("action_scope", []))
        allowed = set(intent.get("allowed_outcomes", []))
        divergence_type = None
        expected: Any = None
        actual: Any = None
        if not required.issubset(actual_assertions):
            divergence_type, expected, actual = "required_assertion_missing", sorted(required), sorted(actual_assertions)
        elif any(constraint.startswith("gate:") for constraint in expected_constraints) and event.get("gate_decision") != next(
            (constraint.split(":", 1)[1] for constraint in expected_constraints if constraint.startswith("gate:")), event.get("gate_decision")
        ):
            divergence_type, expected, actual = "gate_conflict", sorted(expected_constraints), event.get("gate_decision")
        elif not actual_scope.issubset(expected_scope):
            divergence_type, expected, actual = "action_scope_out_of_bounds", sorted(expected_scope), sorted(actual_scope)
        elif event.get("outcome") not in allowed:
            divergence_type, expected, actual = "outcome_not_allowed", sorted(allowed), event.get("outcome")
        elif not expected_constraints.issubset(actual_constraints):
            divergence_type, expected, actual = "constraint_judgment_incompatible", sorted(expected_constraints), sorted(actual_constraints)
        if divergence_type:
            seen_intents.add(str(intent_id))
            divergences.append(
                {
                    "divergence_id": f"DIV-{event.get('event_id')}",
                    "line_number": event.get("line_number"),
                    "event_id": event.get("event_id"),
                    "intent_id": intent_id,
                    "divergence_type": divergence_type,
                    "expected": expected,
                    "actual": actual,
                    "prompt_ref": event.get("prompt_ref") or intent.get("prompt_ref"),
                    "assertion_refs": sorted(required or actual_assertions),
                }
            )
    return {"divergences": divergences}


def validate_prompt_patch(
    patch: dict[str, Any], divergence: dict[str, Any], locked_scope: list[str],
) -> dict[str, Any]:
    valid = bool(
        patch.get("divergence_id") == divergence.get("divergence_id")
        and patch.get("prompt_ref") == divergence.get("prompt_ref")
        and patch.get("prompt_ref") in locked_scope
        and _valid_hash(patch.get("before_sha256"))
        and _valid_hash(patch.get("after_sha256"))
        and patch.get("before_sha256") != patch.get("after_sha256")
        and patch.get("patch_ref")
        and patch.get("actor_run_id")
        and patch.get("reason")
        and patch.get("status") in _PATCH_STATES
    )
    return _ok() if valid else _error("E_V234_PROMPT_PATCH_SCOPE")


def validate_prompt_patch_lifecycle(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records or any(record.get("status") not in _PATCH_STATES for record in records):
        return _error("E_V234_PROMPT_PATCH_STATE")
    base = (records[0].get("patch_id"), records[0].get("divergence_id"), records[0].get("prompt_ref"))
    if any((record.get("patch_id"), record.get("divergence_id"), record.get("prompt_ref")) != base for record in records):
        return _error("E_V234_PROMPT_PATCH_STATE")
    statuses = [record["status"] for record in records]
    valid_sequences = (
        ["proposed"], ["proposed", "applied"], ["proposed", "applied", "verified"],
        ["proposed", "reverted"], ["proposed", "applied", "reverted"],
    )
    if statuses not in valid_sequences:
        return _error("E_V234_PROMPT_PATCH_STATE")
    if statuses[-1] == "verified" and not (
        records[-1].get("regression_passed") is True
        and records[-1].get("holdout_passed") is True
        and records[-1].get("validator_run_id")
    ):
        return _error("E_V234_PROMPT_PATCH_VERIFICATION")
    return _ok(final_state=statuses[-1])


def select_bottleneck(gaps: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        gap for gap in gaps
        if isinstance(gap, dict)
        and gap.get("resolved") is False
        and gap.get("blocks_required") is True
        and gap.get("category") in V234_BOTTLENECK_CATEGORIES
        and isinstance(gap.get("blocking_ac_count"), int)
        and isinstance(gap.get("downstream_required_feature_count"), int)
        and isinstance(gap.get("opened_bundle_revision"), int)
        and isinstance(gap.get("gap_id"), str)
    ]
    if not candidates:
        return None
    return copy.deepcopy(
        min(
            candidates,
            key=lambda gap: (
                -gap["blocking_ac_count"], -gap["downstream_required_feature_count"],
                gap["opened_bundle_revision"], gap["gap_id"],
            ),
        )
    )


def recompute_bottleneck(
    *, previous: dict[str, Any] | None, gaps: list[dict[str, Any]],
    iteration: int, phase: str, assessment_id: str,
) -> dict[str, Any]:
    current = select_bottleneck(gaps)
    evidence_refs = sorted(
        {
            ref for gap in gaps if isinstance(gap, dict)
            for ref in gap.get("evidence_refs", []) if isinstance(ref, str)
        }
    )
    metrics = [
        {
            key: gap.get(key) for key in (
                "gap_id", "category", "blocking_ac_count",
                "downstream_required_feature_count", "opened_bundle_revision",
            )
        }
        for gap in gaps if isinstance(gap, dict) and gap.get("resolved") is False and gap.get("blocks_required") is True
    ]
    return {
        "assessment_id": assessment_id,
        "iteration": iteration,
        "phase": phase,
        "previous": copy.deepcopy(previous),
        "current": current,
        "candidate_metrics": metrics,
        "selection_reason": "deterministic_tuple" if current else "no_required_blocking_gap",
        "evidence_refs": evidence_refs,
        "progress_projection": True,
        "log_event": {"event_type": "BOTTLENECK", "assessment_id": assessment_id, "previous": previous, "current": current},
    }


def _tree_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
        elif stat.S_ISDIR(metadata.st_mode):
            entries.append({"path": relative, "kind": "directory"})
        elif stat.S_ISREG(metadata.st_mode):
            entries.append(
                {
                    "path": relative, "kind": "file",
                    "sha256": _digest_path(path), "size": metadata.st_size,
                }
            )
        else:
            entries.append({"path": relative, "kind": "special"})
    return entries


def _tree_digest(root: Path) -> str:
    return _digest_bytes(_canonical_bytes(_tree_entries(root)))


def _reset_failure(code: str, *, authorization: bool = False) -> dict[str, Any]:
    if authorization:
        return _error(
            code, mutation_count=0, task_state="blocked", check_state="blocked",
            loop_decision="stop", run_outcome="blocked", stop_reason="authorization_required",
        )
    return _error(code, mutation_count=0, task_state="running", check_state="failed", run_outcome="partial")


def _relative_parts(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(character) < 32 for character in value):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.parts


def _component_has_symlink(root: Path, relative_parts: tuple[str, ...]) -> bool:
    current = root
    for part in relative_parts:
        current = current / part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return True
        except FileNotFoundError:
            return False
    return False


def _contains_symlink_or_special(root: Path) -> bool:
    for path in root.rglob("*"):
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            return True
    return False


def _authorization_scope(authorization: dict[str, Any]) -> str:
    scope = {
        "candidate_root": authorization.get("disposable_candidate_root"),
        "candidate_id": authorization.get("candidate_id"),
        "candidate_path": authorization.get("candidate_path"),
        "operation": authorization.get("operation"),
        "contract_revision": authorization.get("contract_revision"),
    }
    # V2.34 authorizations created before task binding was made explicit did
    # not include task_id in the scope digest.  Keep those immutable records
    # replayable, while binding every newly explicit task_id into the scope.
    if authorization.get("task_id") is not None:
        scope["task_id"] = authorization.get("task_id")
    return _digest_bytes(
        _canonical_bytes(scope)
    )


def _reset_authorization_event(
    authorization: dict[str, Any], ledger_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    matching = [
        event for event in ledger_events
        if event.get("event_id") == authorization.get("authorization_event_id")
    ]
    return matching[0] if len(matching) == 1 else None


def _reset_authorization_task_id(
    authorization: dict[str, Any], ledger_events: list[dict[str, Any]],
) -> str | None:
    event = _reset_authorization_event(authorization, ledger_events)
    event_task_id = event.get("task_id") if isinstance(event, dict) else None
    authorized_task_id = authorization.get("task_id")
    if not isinstance(event_task_id, str) or not event_task_id:
        return None
    if authorized_task_id is not None and authorized_task_id != event_task_id:
        return None
    return event_task_id


def _reset_authorization_valid(
    authorization: dict[str, Any], bundle: dict[str, Any], candidate_id: str,
    identity_registry: dict[str, Any], ledger_events: list[dict[str, Any]],
    *, implementation_actor_run_id: str | None = None,
) -> bool:
    core = {key: value for key, value in authorization.items() if key != "record_sha256"}
    if (
        authorization.get("record_sha256") != _digest_bytes(_canonical_bytes(core))
        or authorization.get("candidate_id") != candidate_id
        or authorization.get("operation") != "quarantine"
        or authorization.get("authorized_scope_digest") != _authorization_scope(authorization)
        or authorization.get("contract_revision") != bundle.get("contract", {}).get("contract_revision")
        or authorization.get("contract_sha256") != bundle.get("contract", {}).get("contract_sha256")
        or not authorization.get("authorization_event_id")
        or not authorization.get("authorized_at")
        or not _identity_present(identity_registry, authorization.get("authorized_by_run_id"))
        or authorization.get("authorized_by_run_id") == implementation_actor_run_id
    ):
        return False
    event = _reset_authorization_event(authorization, ledger_events)
    if event is None or _reset_authorization_task_id(authorization, ledger_events) is None:
        return False
    extension = event.get("payload", {}).get("v234_reset_authorization") if isinstance(event.get("payload"), dict) else None
    expected = {
        "authorization_id": authorization.get("authorization_id"),
        "authorization_record_sha256": authorization.get("record_sha256"),
        "authorized_by_run_id": authorization.get("authorized_by_run_id"),
        "contract_revision": authorization.get("contract_revision"),
        "contract_sha256": authorization.get("contract_sha256"),
        "operation": "quarantine",
    }
    return bool(
        event.get("event_type") == "artifact_created"
        and event.get("actor_run_id") == authorization.get("authorized_by_run_id")
        and isinstance(extension, dict)
        and all(extension.get(key) == value for key, value in expected.items())
    )


def evaluate_reset_gate(
    bundle: dict[str, Any], *, target: str,
    evidence_registry: dict[str, Any], ledger_events: list[dict[str, Any]],
    identity_registry: dict[str, Any], checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reset = bundle.get("reset", {})
    if target not in {"act", "iteration_10", "delivery"}:
        return _error("E_V234_RESET_TARGET", mutation_count=0)
    if reset.get("state") != "quarantined" or reset.get("completed_iteration") != 9:
        return _error("E_V234_RESET_REQUIRED", mutation_count=0, run_outcome="partial")
    if checkpoint is None:
        return _error("E_V234_RESET_EVIDENCE", mutation_count=0, run_outcome="partial")
    records, registry_error = _validated_registry(evidence_registry, ledger_events, checkpoint)
    task_projection = checkpoint.get("tasks", {}).get(reset.get("task_id"), {}) if isinstance(checkpoint, dict) else {}
    evidence_refs = task_projection.get("evidence_refs", []) if isinstance(task_projection, dict) else []
    candidates = [
        record for evidence_id, record in (records or {}).items()
        if evidence_id in evidence_refs
        and (
            record.get("reset_event_id") == reset.get("reset_event_id")
            or record.get("environment", {}).get("reset_event_id") == reset.get("reset_event_id")
        )
    ]
    evidence = candidates[0] if len(candidates) == 1 else None
    evidence_environment = evidence.get("environment", {}) if isinstance(evidence, dict) else {}
    expected = {
        "reset_bundle_revision": reset.get("reset_bundle_revision"),
        "reset_bundle_digest": reset.get("reset_bundle_digest"),
        "contract_revision": reset.get("contract_revision"),
        "contract_sha256": reset.get("contract_sha256"),
        "reset_event_id": reset.get("reset_event_id"),
        "receipt_sha256": reset.get("receipt_sha256"),
        "manifest_sha256": reset.get("manifest_sha256"),
    }
    reset_lineage = {
        "reset_ledger_revision": reset.get("ledger_revision"),
        "reset_ledger_prefix_sha256": reset.get("ledger_prefix_sha256"),
    }
    if (
        registry_error is not None
        or not evidence
        or evidence.get("trust_level") != "local_verified"
        or task_projection.get("task_state") != "accepted"
        or task_projection.get("check_state") != "passed"
        or any(evidence_environment.get(key, evidence.get(key)) != value for key, value in expected.items())
        or any(
            evidence_environment.get(key, evidence.get(key)) != value
            for key, value in reset_lineage.items()
        )
        or evidence.get("producer_run_id") == reset.get("actor_run_id")
        or not _identity_present(identity_registry, evidence.get("producer_run_id"))
    ):
        return _error("E_V234_RESET_EVIDENCE", mutation_count=0, run_outcome="partial")
    return _ok(mutation_count=0, reset_event_id=reset.get("reset_event_id"))


def plan_controlled_reset(
    bundle: dict[str, Any], candidate_id: str, authorization: dict[str, Any] | None,
    *, repo_root: Path | str, state_root: Path | str,
    artifact_root: Path | str | None = None,
    identity_registry: dict[str, Any] | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = Path(repo_root).absolute()
    state = Path(state_root).absolute()
    artifact = Path(artifact_root).absolute() if artifact_root is not None else None
    binding_result = _binding_result(repository, version_binding, marker=bundle)
    if not binding_result.get("ok"):
        return binding_result
    normalized_binding = binding_result["binding"]
    if not _CANDIDATE_ID.fullmatch(candidate_id or ""):
        return _reset_failure("E_V234_RESET_CANDIDATE_ID")
    if authorization is None:
        return _reset_failure("E_V234_RESET_AUTHORIZATION", authorization=True)
    if not _reset_authorization_valid(
        authorization, bundle, candidate_id, identity_registry or {}, ledger_events or []
    ):
        return _reset_failure("E_V234_RESET_AUTHORIZATION", authorization=True)
    reset_task_id = _reset_authorization_task_id(authorization, ledger_events or [])
    if reset_task_id is None:
        return _reset_failure("E_V234_RESET_AUTHORIZATION", authorization=True)
    candidate_root_raw = authorization.get("disposable_candidate_root")
    if candidate_root_raw in {".", "..", ""}:
        return _reset_failure("E_V234_RESET_PROTECTED_ROOT")
    root_parts = _relative_parts(candidate_root_raw)
    if root_parts is None:
        return _reset_failure("E_V234_RESET_PROTECTED_ROOT")
    target = repository.joinpath(*root_parts, candidate_id)
    if not target.exists() and not target.is_symlink():
        return _reset_failure("E_V234_RESET_TARGET_MISSING")
    if _component_has_symlink(repository, (*root_parts, candidate_id)):
        return _reset_failure("E_V234_RESET_SYMLINK")
    try:
        repository_real = repository.resolve(strict=True)
        target_real = target.resolve(strict=True)
        state_real = state.resolve(strict=True)
        artifact_real = artifact.resolve(strict=True) if artifact is not None else None
    except OSError:
        return _reset_failure("E_V234_RESET_PREFLIGHT")
    protected = [repository_real, state_real, repository_real / ".git", repository_real / "docs"]
    if artifact_real is not None:
        protected.append(artifact_real)
    candidate_root = repository_real.joinpath(*root_parts)
    protected.append(candidate_root)
    if (
        target_real in protected
        or target_real == repository_real
        or target_real == state_real
        or target_real.is_relative_to(state_real)
        or artifact_real is not None and (target_real == artifact_real or target_real.is_relative_to(artifact_real))
        or target_real == repository_real / "docs"
        or target_real.is_relative_to(repository_real / "docs")
        or not target_real.is_relative_to(repository_real)
        or target_real.parent != candidate_root
    ):
        return _reset_failure("E_V234_RESET_PROTECTED_ROOT")
    if not target.is_dir() or target.is_symlink():
        return _reset_failure("E_V234_RESET_PREFLIGHT")
    if _contains_symlink_or_special(target):
        return _reset_failure("E_V234_RESET_SYMLINK")
    expected_candidate_path = PurePosixPath(*root_parts, candidate_id).as_posix()
    if (
        authorization.get("candidate_path") != expected_candidate_path
        or authorization.get("authorized_scope_digest") != _authorization_scope(authorization)
        or authorization.get("contract_revision") != bundle.get("contract", {}).get("contract_revision")
        or authorization.get("contract_sha256") != bundle.get("contract", {}).get("contract_sha256")
    ):
        return _reset_failure("E_V234_RESET_AUTHORIZATION", authorization=True)
    if authorization.get("ownership_verified") is not True:
        return _reset_failure("E_V234_RESET_OWNERSHIP", authorization=True)
    if authorization.get("permission_verified") is not True:
        return _reset_failure("E_V234_RESET_PERMISSION", authorization=True)
    if authorization.get("expected_realpath") != str(target_real):
        return _reset_failure("E_V234_RESET_PREFLIGHT")
    actual_manifest = sorted(
        path.relative_to(target).as_posix()
        for path in target.rglob("*") if path.is_file() and not path.is_symlink()
    )
    if actual_manifest != sorted(authorization.get("manifest_paths", [])):
        return _reset_failure("E_V234_RESET_UNREGISTERED_CHANGE")
    digest = _tree_digest(target)
    if authorization.get("before_tree_sha256") != digest:
        return _reset_failure("E_V234_RESET_DIGEST")
    reset_id = authorization.get("reset_id")
    if not isinstance(reset_id, str) or not _CANDIDATE_ID.fullmatch(reset_id):
        return _reset_failure("E_V234_RESET_AUTHORIZATION", authorization=True)
    quarantine = repository_real / ".goalteams-quarantine" / reset_id / candidate_id
    quarantine_ancestors: list[dict[str, Any]] = []
    current = repository_real
    for component in (".goalteams-quarantine", reset_id):
        current = current / component
        if current.exists() or current.is_symlink():
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                return _reset_failure("E_V234_RESET_SYMLINK")
            if not current.resolve().is_relative_to(repository_real):
                return _reset_failure("E_V234_RESET_PROTECTED_ROOT")
            quarantine_ancestors.append(
                {"path": current.relative_to(repository_real).as_posix(), "st_dev": metadata.st_dev, "st_ino": metadata.st_ino, "mode": stat.S_IMODE(metadata.st_mode)}
            )
        else:
            break
    if quarantine.exists() or quarantine.is_symlink():
        return _reset_failure("E_V234_RESET_QUARANTINE_CONFLICT")
    try:
        metadata = os.lstat(target)
    except OSError:
        return _reset_failure("E_V234_RESET_PREFLIGHT")
    plan = {
        "plan_version": "v234-reset-plan-v1",
        "task_id": reset_task_id,
        "candidate_id": candidate_id,
        "candidate_path": expected_candidate_path,
        "candidate_realpath": str(target_real),
        "candidate_root_realpath": str(candidate_root),
        "quarantine_realpath": str(quarantine),
        "quarantine_ancestors": quarantine_ancestors,
        "before_tree_sha256": digest,
        "entry_count": len(_tree_entries(target)),
        "st_dev": metadata.st_dev,
        "st_ino": metadata.st_ino,
        "mode": stat.S_IMODE(metadata.st_mode),
        "reset_id": reset_id,
        "authorization_id": authorization.get("authorization_id"),
        "authorized_scope_digest": authorization.get("authorized_scope_digest"),
        "contract_revision": authorization.get("contract_revision"),
        "contract_sha256": authorization.get("contract_sha256"),
        "planned_bundle_revision": bundle.get("bundle_revision"),
        "planned_bundle_digest": bundle.get("bundle_digest"),
    }
    if normalized_binding.get("explicit") is True:
        plan["version_binding_digest"] = normalized_binding["binding_digest"]
    plan["plan_sha256"] = _digest_bytes(_canonical_bytes(plan))
    return _ok(plan=plan, mutation_count=0)


def _open_quarantine_parent(
    repository: Path, reset_id: str, plan: dict[str, Any],
) -> tuple[int, Path]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(repository, flags)
    recorded = {item["path"]: item for item in plan.get("quarantine_ancestors", []) if isinstance(item, dict)}
    relative_parts: list[str] = []
    try:
        for component in (".goalteams-quarantine", reset_id):
            relative_parts.append(component)
            relative = PurePosixPath(*relative_parts).as_posix()
            expected = recorded.get(relative)
            try:
                metadata = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
                exists = True
            except FileNotFoundError:
                exists = False
                metadata = None
            if exists:
                if expected is None or metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    raise OSError("quarantine ancestor changed")
                if (
                    metadata.st_dev != expected.get("st_dev")
                    or metadata.st_ino != expected.get("st_ino")
                    or stat.S_IMODE(metadata.st_mode) != expected.get("mode")
                ):
                    raise OSError("quarantine ancestor identity drift")
            else:
                if expected is not None:
                    raise OSError("quarantine ancestor disappeared")
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        parent = repository.joinpath(*relative_parts)
        if parent.resolve() != parent or not parent.resolve().is_relative_to(repository):
            raise OSError("quarantine escaped repository")
        return descriptor, parent
    except Exception:
        os.close(descriptor)
        raise


def _apply_controlled_reset_locked(
    bundle: dict[str, Any], plan: dict[str, Any], authorization: dict[str, Any],
    *, repo_root: Path | str, state_root: Path | str, actor_run_id: str,
    expected_bundle_revision: int | None = None, expected_bundle_digest: str | None = None,
    identity_registry: dict[str, Any] | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
    normalized_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = Path(repo_root).absolute().resolve()
    state = Path(state_root).absolute().resolve()
    binding = normalized_binding or _version_binding.default_version_binding()
    state_validation = validate_state_bundle(
        state, ledger_events=ledger_events, checkpoint=checkpoint,
        repo_root=repository, version_binding=binding,
    )
    if not state_validation.get("ok") or state_validation.get("state") != "valid":
        result = _state_write_error(state_validation)
        result["mutation_count"] = 0
        return result
    persisted_marker = state_validation["marker"]
    if (
        persisted_marker.get("bundle_revision") != bundle.get("bundle_revision")
        or persisted_marker.get("bundle_digest") != bundle.get("bundle_digest")
    ):
        return _error("E_V234_CAS_CONFLICT", mutation_count=0)
    if expected_bundle_revision is not None and expected_bundle_revision != bundle.get("bundle_revision"):
        return _error("E_V234_CAS_CONFLICT", mutation_count=0)
    if expected_bundle_digest is not None and expected_bundle_digest != bundle.get("bundle_digest"):
        return _error("E_V234_CAS_CONFLICT", mutation_count=0)
    plan_core = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if plan.get("plan_sha256") != _digest_bytes(_canonical_bytes(plan_core)):
        return _error("E_V234_RESET_TOCTOU", mutation_count=0)
    if binding.get("explicit") is True and plan.get("version_binding_digest") != binding["binding_digest"]:
        return _version_binding._error("E_V235_VERSION_BINDING_MISMATCH")
    if (
        authorization.get("authorization_id") != plan.get("authorization_id")
        or authorization.get("authorized_scope_digest") != plan.get("authorized_scope_digest")
        or authorization.get("operation") != "quarantine"
    ):
        return _error("E_V234_RESET_AUTHORIZATION", mutation_count=0)
    if not _reset_authorization_valid(
        authorization, bundle, str(plan.get("candidate_id", "")),
        identity_registry or {}, ledger_events or [],
        implementation_actor_run_id=actor_run_id,
    ):
        return _error("E_V234_RESET_AUTHORIZATION", mutation_count=0)
    reset_task_id = _reset_authorization_task_id(authorization, ledger_events or [])
    checkpoint_task = (
        checkpoint.get("tasks", {}).get(reset_task_id)
        if isinstance(checkpoint, dict) and isinstance(checkpoint.get("tasks"), dict)
        else None
    )
    if (
        reset_task_id is None
        or plan.get("task_id") != reset_task_id
        or not isinstance(checkpoint_task, dict)
    ):
        return _error("E_V234_RESET_AUTHORIZATION", mutation_count=0)
    candidate = Path(plan.get("candidate_realpath", ""))
    quarantine = Path(plan.get("quarantine_realpath", ""))
    try:
        if (
            not candidate.is_relative_to(repository)
            or candidate == repository
            or candidate == state
            or candidate.is_relative_to(state)
            or candidate.is_symlink()
            or not candidate.is_dir()
            or quarantine.exists()
            or quarantine.is_symlink()
        ):
            return _error("E_V234_RESET_TOCTOU", mutation_count=0)
        metadata = os.lstat(candidate)
        if (
            metadata.st_dev != plan.get("st_dev")
            or metadata.st_ino != plan.get("st_ino")
            or stat.S_IMODE(metadata.st_mode) != plan.get("mode")
            or _tree_digest(candidate) != plan.get("before_tree_sha256")
            or _contains_symlink_or_special(candidate)
        ):
            return _error("E_V234_RESET_TOCTOU", mutation_count=0)
        parent_descriptor, parent = _open_quarantine_parent(repository, str(plan["reset_id"]), plan)
        try:
            parent_metadata = os.fstat(parent_descriptor)
            if os.lstat(candidate).st_dev != parent_metadata.st_dev:
                return _error("E_V234_RESET_CROSS_DEVICE", mutation_count=0)
            try:
                os.stat(str(plan["candidate_id"]), dir_fd=parent_descriptor, follow_symlinks=False)
                return _error("E_V234_RESET_QUARANTINE_CONFLICT", mutation_count=0)
            except FileNotFoundError:
                pass
            os.replace(candidate, str(plan["candidate_id"]), dst_dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
        reset_event_id = f"EVT-V234-RESET-{authorization.get('reset_id')}"
        manifest = {
            "task_id": reset_task_id,
            "source_realpath": str(candidate),
            "quarantine_realpath": str(quarantine),
            "before_tree_sha256": plan["before_tree_sha256"],
            "timestamp": _now(),
            "actor_run_id": actor_run_id,
            "contract_revision": plan["contract_revision"],
            "contract_sha256": plan["contract_sha256"],
            "reset_event_id": reset_event_id,
            "authorization_id": authorization.get("authorization_id"),
            "recovery_command": f"mv -- {quarantine} {candidate}",
        }
        if binding.get("explicit") is True:
            manifest["version_binding_digest"] = binding["binding_digest"]
        manifest_name = f"manifest-{plan['candidate_id']}.json"
        manifest_path = parent / manifest_name
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        manifest_parent_descriptor = os.open(
            parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            manifest_descriptor = os.open(
                manifest_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=manifest_parent_descriptor,
            )
            try:
                os.write(manifest_descriptor, manifest_bytes)
                os.fsync(manifest_descriptor)
            finally:
                os.close(manifest_descriptor)
        finally:
            os.close(manifest_parent_descriptor)
        manifest_sha = _digest_path(manifest_path)
        receipt = {
            "task_id": reset_task_id,
            "reset_event_id": reset_event_id,
            "manifest_sha256": manifest_sha,
            "plan_sha256": plan["plan_sha256"],
            "bundle_revision": bundle.get("bundle_revision"),
            "bundle_digest": bundle.get("bundle_digest"),
        }
        if binding.get("explicit") is True:
            receipt["version_binding_digest"] = binding["binding_digest"]
        receipt["receipt_sha256"] = _digest_bytes(_canonical_bytes(receipt))
        new_marker = copy.deepcopy(persisted_marker)
        new_marker["bundle_revision"] += 1
        new_marker["reset"] = {
            "state": "quarantined",
            "completed_iteration": 9,
            "task_id": reset_task_id,
            "reset_event_id": reset_event_id,
            "attempt_id": persisted_marker.get("loop", {}).get("attempt_id"),
            "actor_run_id": actor_run_id,
            "authorization_id": authorization.get("authorization_id"),
            "authorization_record_sha256": authorization.get("record_sha256"),
            "receipt_sha256": receipt["receipt_sha256"],
            "manifest_sha256": manifest_sha,
            "reset_bundle_revision": persisted_marker.get("bundle_revision"),
            "reset_bundle_digest": persisted_marker.get("bundle_digest"),
            "contract_revision": persisted_marker.get("contract", {}).get("contract_revision"),
            "contract_sha256": persisted_marker.get("contract", {}).get("contract_sha256"),
            "ledger_revision": persisted_marker.get("ledger", {}).get("revision"),
            "ledger_prefix_sha256": persisted_marker.get("ledger", {}).get("prefix_sha256"),
        }
        if binding.get("explicit") is True:
            new_marker["reset"]["version_binding_digest"] = binding["binding_digest"]
        reset_log_event = {
            "event_id": f"LOG-V234-RESET-{new_marker['bundle_revision']:06d}",
            "event_type": "RESET_QUARANTINED",
            "bundle_revision": new_marker["bundle_revision"],
            "iteration": 9,
            "attempt": new_marker.get("loop", {}).get("attempt", 1),
            "phase": new_marker.get("loop", {}).get("phase", "reason"),
            "actor_run_id": actor_run_id,
            "timestamp": _now(),
            "intent_id": f"INTENT-V234-RESET-{reset_event_id}",
            "expected_constraints": ["authorization:bound", "quarantine:no-follow", "state:marker-last"],
            "judgment": "Quarantine the authorized disposable candidate and persist immutable lineage.",
            "action_scope": [plan["candidate_path"], ".goalteams-quarantine", "feature_list.json", "progress.md", "log.md"],
            "prompt_ref": "prompts/lead/loop.md",
            "assertion_refs": ["ASSERT-V234-023", "ASSERT-V234-024", "ASSERT-V234-025", "ASSERT-V234-026"],
            "outcome": "partial",
            "reset_event_id": reset_event_id,
            "receipt_sha256": receipt["receipt_sha256"],
            "manifest_sha256": manifest_sha,
        }
        new_log, appended = _append_encoded_event((state / "log.md").read_bytes(), reset_log_event)
        new_marker["log_commit_event_id"] = appended["event_id"]
        new_marker["log_commit_event_digest"] = appended["event_digest"]
        new_marker["log_sha256"] = _digest_bytes(new_log)
        new_progress = _encode_progress(new_marker)
        new_marker["progress_sha256"] = _digest_bytes(new_progress)
        new_marker["bundle_digest"] = _marker_digest(new_marker)
        state_commit = _commit_bundle_bytes_locked(
            state, old_marker=persisted_marker, new_marker=new_marker,
            new_log=new_log, new_progress=new_progress,
            transaction_id=f"TXN-V234-RESET-{new_marker['bundle_revision']:06d}-{os.getpid()}",
            repo_root=repository, version_binding=binding,
        )
        if not state_commit.get("ok"):
            return _error(
                "E_V234_RESET_STATE_COMMIT", mutation_count=2,
                manifest=manifest, receipt=receipt, state_commit=state_commit,
            )
        return _ok(
            manifest=manifest, receipt=receipt, mutation_count=3,
            bundle_revision=state_commit["bundle_revision"],
            bundle_digest=state_commit["bundle_digest"],
            transaction_id=state_commit["transaction_id"],
            **(
                {"version_binding_digest": binding["binding_digest"]}
                if binding.get("explicit") is True else {}
            ),
        )
    except (OSError, ValueError):
        return _error("E_V234_RESET_TOCTOU", mutation_count=0)


def apply_controlled_reset(
    bundle: dict[str, Any], plan: dict[str, Any], authorization: dict[str, Any],
    *, repo_root: Path | str, state_root: Path | str, actor_run_id: str,
    expected_bundle_revision: int | None = None, expected_bundle_digest: str | None = None,
    identity_registry: dict[str, Any] | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = Path(state_root)
    repository = Path(repo_root).absolute().resolve()
    try:
        pre_marker = _json_object(state / "feature_list.json")
    except (OSError, ValueError, json.JSONDecodeError):
        pre_marker = bundle
    binding_result = _binding_result(
        repository, version_binding, marker=pre_marker
    )
    if not binding_result.get("ok"):
        return binding_result
    try:
        descriptor = _acquire_state_lock(state)
    except OSError:
        return _error("E_V234_STATE_LOCK_UNAVAILABLE", mutation_count=0)
    try:
        return _apply_controlled_reset_locked(
            bundle, plan, authorization, repo_root=repo_root, state_root=state,
            actor_run_id=actor_run_id,
            expected_bundle_revision=expected_bundle_revision,
            expected_bundle_digest=expected_bundle_digest,
            identity_registry=identity_registry, ledger_events=ledger_events,
            checkpoint=checkpoint,
            normalized_binding=binding_result["binding"],
        )
    finally:
        _release_state_lock(descriptor)


def repair_reset_task_binding(
    root: Path | str, authorization: dict[str, Any], *, actor_run_id: str,
    expected_bundle_revision: int, expected_bundle_digest: str,
    identity_registry: dict[str, Any], ledger_events: list[dict[str, Any]],
    checkpoint: dict[str, Any],
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repair only the task projection of an already quarantined reset.

    The target is derived from the immutable authorization ledger event rather
    than supplied by the caller.  This makes recovery safe for early V2.34
    receipts whose state projection used the generic TASK-V234-RESET default.
    """
    state_root = Path(root)
    validation = validate_state_bundle(
        state_root, ledger_events=ledger_events, checkpoint=checkpoint,
        repo_root=repo_root, version_binding=version_binding,
    )
    if not validation.get("ok") or validation.get("state") != "valid":
        return _state_write_error(validation)
    marker = validation["marker"]
    if (
        marker.get("bundle_revision") != expected_bundle_revision
        or marker.get("bundle_digest") != expected_bundle_digest
    ):
        return _error("E_V234_CAS_CONFLICT", mutation_count=0)
    reset = marker.get("reset", {})
    target_task_id = _reset_authorization_task_id(authorization, ledger_events)
    checkpoint_task = (
        checkpoint.get("tasks", {}).get(target_task_id)
        if isinstance(checkpoint, dict) and isinstance(checkpoint.get("tasks"), dict)
        else None
    )
    if (
        reset.get("state") != "quarantined"
        or reset.get("completed_iteration") != 9
        or target_task_id is None
        or not _identity_present(identity_registry, actor_run_id)
        or not isinstance(checkpoint_task, dict)
        or reset.get("authorization_id") != authorization.get("authorization_id")
        or reset.get("authorization_record_sha256") != authorization.get("record_sha256")
        or reset.get("reset_event_id") != f"EVT-V234-RESET-{authorization.get('reset_id')}"
        or not _reset_authorization_valid(
            authorization, marker, str(authorization.get("candidate_id", "")),
            identity_registry, ledger_events,
        )
    ):
        return _error("E_V234_RESET_TASK_BINDING", mutation_count=0)
    previous_task_id = reset.get("task_id")
    if previous_task_id == target_task_id:
        return _ok(
            mutation_count=0, idempotent=True, task_id=target_task_id,
            bundle_revision=marker["bundle_revision"],
            bundle_digest=marker["bundle_digest"],
        )

    def bind_reset_task(value: dict[str, Any]) -> None:
        value["reset"]["task_id"] = target_task_id

    result = _commit_projection_update(
        state_root,
        expected_bundle_revision=expected_bundle_revision,
        expected_bundle_digest=expected_bundle_digest,
        actor_run_id=actor_run_id,
        event_type="RESET_TASK_REBOUND",
        assertion_refs=["ASSERT-V234-023", "ASSERT-V234-024", "ASSERT-V234-026"],
        mutation=bind_reset_task,
        event_data={
            "previous_task_id": previous_task_id,
            "task_id": target_task_id,
            "authorization_event_id": authorization.get("authorization_event_id"),
            "reset_event_id": reset.get("reset_event_id"),
        },
        ledger_events=ledger_events,
        checkpoint=checkpoint,
        repo_root=repo_root,
        version_binding=version_binding,
    )
    if result.get("ok"):
        result.update(
            mutation_count=1, idempotent=False, task_id=target_task_id,
            previous_task_id=previous_task_id,
        )
    return result


def validate_purge_authorization(
    reset_authorization: dict[str, Any], purge_authorization: dict[str, Any] | None,
) -> dict[str, Any]:
    valid = bool(
        purge_authorization
        and purge_authorization.get("operation") == "purge"
        and purge_authorization.get("explicit") is True
        and purge_authorization.get("authorization_id")
        and purge_authorization.get("authorization_id") != reset_authorization.get("authorization_id")
    )
    return _ok() if valid else _error("E_V234_PURGE_AUTHORIZATION")


def _json_record_matches(path_value: Any, expected: Any) -> bool:
    """Require a regular on-disk JSON record to equal its supplied projection."""
    try:
        path = Path(str(path_value))
        if not _regular_single_link(path):
            return False
        return _json_object(path) == expected
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _completion_proof_errors(
    proof: dict[str, Any], source_context: dict[str, Any], *, bundle: dict[str, Any] | None,
    archive_descriptor: list[dict[str, Any]] | None,
    normalized_binding: dict[str, Any] | None = None,
) -> list[str]:
    """Validate release facts from immutable files, never caller booleans.

    The proof is deliberately a compact projection.  Every security-relevant
    value is re-read from ``source_context`` so a caller cannot turn a failed
    gate into success by replacing a JSON ``true`` value.
    """
    errors: list[str] = []
    binding = normalized_binding or (
        _marker_binding(bundle).get("binding")
        if isinstance(bundle, dict) else _version_binding.default_version_binding()
    )
    binding_validation = _version_binding.validate_normalized_binding(binding)
    if not binding_validation.get("ok"):
        return ["version_binding"]
    binding = binding_validation["binding"]
    if binding.get("explicit") is True and (
        source_context.get("version_binding_digest") not in {None, binding["binding_digest"]}
        or (
            source_context.get("version_binding") is not None
            and source_context.get("version_binding") != binding
        )
    ):
        errors.append("version_binding")
    if not isinstance(proof, dict) or proof.get("schema_version") != "goal-teams-v2.34-completion-proof-v1":
        return ["completion_proof"]
    projected = {key: value for key, value in proof.items() if key != "proof_digest"}
    if proof.get("proof_digest") != _digest_bytes(_canonical_bytes(projected)):
        errors.append("proof_digest")
    if not isinstance(source_context, dict):
        return [*errors, "source_context"]
    if not _json_record_matches(source_context.get("completion_proof_path"), proof):
        errors.append("completion_proof_file")

    events = source_context.get("ledger_events")
    checkpoint = source_context.get("checkpoint")
    registry = source_context.get("evidence_registry")
    if not isinstance(events, list) or not isinstance(checkpoint, dict):
        return [*errors, "ledger"]
    revision = checkpoint.get("ledger_revision")
    prefix = _ledger_prefix(events, revision)
    event_digests = {
        str(event.get("event_id")): _digest_bytes(_canonical_bytes({key: value for key, value in event.items() if key != "event_digest"}))
        for event in events[:revision] if isinstance(revision, int)
    }
    if (
        not isinstance(revision, int) or revision <= 0 or revision > len(events)
        or checkpoint.get("revision") != revision
        or checkpoint.get("last_event_id") != events[revision - 1].get("event_id")
        or checkpoint.get("event_digests") != event_digests
        or checkpoint.get("conflicts") not in ([], None)
    ):
        errors.append("ledger")
    records, registry_error = _validated_registry(registry, events, checkpoint)
    if registry_error or records is None:
        errors.append("evidence")
        records = {}

    identities = source_context.get("identity_registry")
    if not isinstance(identities, dict):
        errors.append("identity")
    review = source_context.get("review_record")
    audit = source_context.get("audit_record")
    if not isinstance(review, dict) or not _json_record_matches(source_context.get("review_path"), review):
        errors.append("review")
    if not isinstance(audit, dict) or not _json_record_matches(source_context.get("audit_path"), audit):
        errors.append("audit")
    if isinstance(review, dict) and isinstance(audit, dict):
        review_core = {key: value for key, value in review.items() if key != "record_sha256"}
        audit_core = {key: value for key, value in audit.items() if key != "record_sha256"}
        review_path = Path(str(source_context.get("review_path", "")))
        review_file_sha256 = _digest_path(review_path) if _regular_single_link(review_path) else None
        if (
            review.get("record_sha256") != _digest_bytes(_canonical_bytes(review_core))
            or review.get("state") != "passed"
            or audit.get("record_sha256") != _digest_bytes(_canonical_bytes(audit_core))
            or audit.get("state") != "passed"
            or audit.get("run_outcome_candidate") != "achieved"
            or audit.get("author_run_id") == audit.get("auditor_run_id")
            or not _identity_present(identities or {}, audit.get("auditor_run_id"))
            or review.get("validator_run_id") == review.get("author_run_id")
            or proof.get("review_id") != review.get("review_id")
            or proof.get("completion_audit_id") != audit.get("audit_id")
            or audit.get("review_id") != review.get("review_id")
            or audit.get("ledger_revision") != proof.get("ledger_revision")
            or audit.get("ledger_revision") != revision
            or audit.get("bundle_revision") != proof.get("bundle_revision")
            or audit.get("bundle_digest") != proof.get("bundle_digest")
            or audit.get("task_state_digest") != _digest_bytes(_canonical_bytes(checkpoint.get("tasks", {})))
            or audit.get("review_sha256") != review_file_sha256
        ):
            errors.append("review_audit")

    required = proof.get("required_task_ids")
    tasks_value = checkpoint.get("tasks", {}) if isinstance(checkpoint, dict) else {}
    tasks = tasks_value if isinstance(tasks_value, dict) else {}
    expected_required = sorted(
        task_id for task_id, task in tasks.items()
        if isinstance(task_id, str) and isinstance(task, dict)
        and (task.get("required_for_done") is True or task.get("acceptance_blocking") is True)
    )
    if (
        not isinstance(required, list) or not required
        or any(not isinstance(item, str) for item in required)
        or (all(isinstance(item, str) for item in required) and len(required) != len(set(required)))
        or (all(isinstance(item, str) for item in required) and sorted(required) != expected_required)
        or any(
        not isinstance(item, str)
        or not isinstance(tasks.get(item), dict)
        or tasks[item].get("task_state") != "accepted"
        or tasks[item].get("check_state") != "passed"
        for item in required
        )
    ):
        errors.append("required_tasks")
    evidence_ids = proof.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids or any(item not in records for item in evidence_ids):
        errors.append("evidence_ids")
    if isinstance(audit, dict) and (
        not isinstance(audit.get("required_task_ids"), list)
        or any(not isinstance(item, str) for item in audit.get("required_task_ids", []))
        or (
            all(isinstance(item, str) for item in audit.get("required_task_ids", []))
            and sorted(audit.get("required_task_ids", [])) != expected_required
        )
        or (
            all(isinstance(item, str) for item in audit.get("required_task_ids", []))
            and len(audit.get("required_task_ids", [])) != len(set(audit.get("required_task_ids", [])))
        )
        or not isinstance(evidence_ids, list)
        or not isinstance(audit.get("evidence_refs"), list)
        or any(not isinstance(item, str) for item in audit.get("evidence_refs", []))
        or any(not isinstance(item, str) for item in evidence_ids)
        or (
            all(isinstance(item, str) for item in audit.get("evidence_refs", []))
            and all(isinstance(item, str) for item in evidence_ids)
            and sorted(audit.get("evidence_refs", [])) != sorted(evidence_ids)
        )
        or (
            all(isinstance(item, str) for item in audit.get("evidence_refs", []))
            and len(audit.get("evidence_refs", [])) != len(set(audit.get("evidence_refs", [])))
        )
    ):
        errors.append("review_audit")

    if bundle is not None:
        loop = bundle.get("loop", {})
        if (
            loop.get("iteration") != 11 or loop.get("phase") != "verify"
            or loop.get("run_outcome") == "achieved"
            or proof.get("bundle_revision") != bundle.get("bundle_revision")
            or proof.get("bundle_digest") != bundle.get("bundle_digest")
        ):
            errors.append("bundle")
        reset = proof.get("reset", {})
        marker_reset = bundle.get("reset", {})
        if not isinstance(reset, dict) or any(
            reset.get(key) != marker_reset.get(key)
            for key in ("reset_event_id", "receipt_sha256", "manifest_sha256", "evidence_id")
        ):
            errors.append("reset")
    else:
        reset = proof.get("reset", {})
        reset_evidence = records.get(reset.get("evidence_id")) if isinstance(reset, dict) else None
        reset_environment = reset_evidence.get("environment", {}) if isinstance(reset_evidence, dict) else {}
        if not isinstance(reset, dict) or not isinstance(reset_evidence, dict) or any(
            reset.get(key) != reset_environment.get(key, reset_evidence.get(key))
            for key in ("reset_event_id", "receipt_sha256", "manifest_sha256")
        ):
            errors.append("reset")

    repo = Path(str(source_context.get("repo_root", "")))
    candidate = proof.get("rebuilt_candidate", {})
    try:
        candidate_path = repo.joinpath(*PurePosixPath(str(candidate.get("artifact_ref", ""))).parts)
        if (
            not isinstance(candidate, dict) or not _regular_single_link(candidate_path)
            or _digest_path(candidate_path) != candidate.get("artifact_sha256")
            or candidate.get("evidence_id") not in records
        ):
            errors.append("rebuilt_candidate")
    except (OSError, ValueError):
        errors.append("rebuilt_candidate")
    repository_check = proof.get("repository_check", {})
    if not isinstance(repository_check, dict) or repository_check.get("evidence_id") not in records:
        errors.append("repository_check")

    scores = proof.get("quality_scores")
    if not isinstance(scores, dict) or not validate_quality_scores(scores).get("ok"):
        errors.append("scores")
    lifecycle = proof.get("prompt_lifecycle")
    if not isinstance(lifecycle, list) or any(
        item.get("required") is True and item.get("status") != "verified"
        for item in lifecycle if isinstance(item, dict)
    ):
        errors.append("prompt_lifecycle")
    bottleneck = proof.get("bottleneck", {})
    if not isinstance(bottleneck, dict) or bottleneck.get("iteration") != 11 or bottleneck.get("phase") != "verify":
        errors.append("bottleneck")
    if (
        proof.get("version") != binding["project_version"]
        or not validate_version_sync(repo, expected_version=binding["project_version"]).get("ok")
        or (
            binding.get("explicit") is True
            and proof.get("version_binding_digest") != binding["binding_digest"]
        )
    ):
        errors.append("version")
    try:
        roadmap_path = Path(str(source_context.get("roadmap_path", "")))
        if not _regular_single_link(roadmap_path) or _digest_path(roadmap_path) != proof.get("roadmap_sha256"):
            errors.append("roadmap")
    except OSError:
        errors.append("roadmap")
    guard = source_context.get("worktree_guard")
    if (
        not isinstance(guard, dict) or proof.get("worktree_guard_sha256") != guard.get("guard_sha256")
        or not validate_worktree_guard(repo, guard, allowed_paths=[]).get("ok")
    ):
        errors.append("worktree")
    if archive_descriptor is not None and proof.get("archive_descriptor_sha256") != _digest_bytes(_canonical_bytes(archive_descriptor)):
        errors.append("archive")
    snapshot = source_context.get("candidate_snapshot_receipt")
    snapshot_path = source_context.get("candidate_snapshot_path")
    if snapshot is not None or snapshot_path is not None:
        if (
            not isinstance(snapshot, dict)
            or not _json_record_matches(snapshot_path, snapshot)
            or proof.get("candidate_snapshot_receipt_sha256") != snapshot.get("receipt_sha256")
            or not publish_guard(
                repo, mode="snapshot", snapshot_receipt=snapshot,
                version_binding=binding,
            ).get("ok")
        ):
            errors.append("publish")
    else:
        baseline = source_context.get("baseline_commit")
        candidate_commit = source_context.get("candidate_commit")
        if not isinstance(baseline, str) or not isinstance(candidate_commit, str) or not publish_guard(
            repo, mode="commit", commit=candidate_commit, baseline_commit=baseline,
            version_binding=binding,
        ).get("ok"):
            errors.append("publish")
    return sorted(set(errors))


def evaluate_delivery_gate(
    bundle: dict[str, Any], completion_proof: dict[str, Any],
    archive_descriptor: list[dict[str, Any]], *, source_context: dict[str, Any] | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    loop = bundle.get("loop", {})
    if loop.get("iteration") != 11 or loop.get("phase") != "verify":
        return _error("E_V234_DELIVERY_ITERATION", gaps=["delivery_iteration"], run_outcome="partial", next_iteration=None)
    marker_binding = _marker_binding(bundle)
    if not marker_binding.get("ok"):
        return marker_binding
    repository_context = (source_context or {}).get("repo_root")
    if marker_binding["binding"].get("explicit") is True and repository_context is None:
        return _version_binding._error("E_V235_VERSION_BINDING_PROVENANCE")
    binding_result = _binding_result(
        repository_context or ".", version_binding, marker=bundle,
    )
    if not binding_result.get("ok"):
        return binding_result
    errors = _completion_proof_errors(
        completion_proof, source_context or {}, bundle=bundle, archive_descriptor=archive_descriptor,
        normalized_binding=binding_result["binding"],
    )
    if errors:
        return _error("E_V234_COMPLETION_PROOF", gaps=errors, run_outcome="partial", next_iteration=None, archive_created=False)
    return _ok(gaps=[], run_outcome_candidate="achieved", next_iteration=None, ledger_revision=completion_proof.get("ledger_revision"))


def validate_archive_eligibility(
    descriptors: list[dict[str, Any]], completion: dict[str, Any], *,
    repo_root: Path | str | None = None,
    completion_proof: dict[str, Any] | None = None,
    source_context: dict[str, Any] | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit = completion.get("completion_audit", {})
    global_ready = bool(
        completion.get("run_outcome_candidate") == "achieved"
        and audit.get("state") == "passed"
        and audit.get("validator_run_id")
        and audit.get("sha256")
    )
    if repo_root is None:
        return _error("E_V234_ARCHIVE_SOURCE", artifact_ids=[], ineligible_artifact_ids=[str(item.get("source_artifact_id")) for item in descriptors])
    binding_result = _binding_result(repo_root, version_binding)
    if not binding_result.get("ok"):
        return binding_result
    normalized_binding = binding_result["binding"]
    proof_errors: list[str] = []
    if completion_proof is not None or source_context is not None:
        proof_errors = _completion_proof_errors(
            completion_proof or {}, source_context or {}, bundle=None, archive_descriptor=descriptors,
            normalized_binding=normalized_binding,
        )
    if proof_errors:
        return _error(
            "E_V234_ARCHIVE_ELIGIBILITY", artifact_ids=[],
            ineligible_artifact_ids=[str(item.get("source_artifact_id")) for item in descriptors],
            errors=proof_errors,
        )
    repository = Path(repo_root).absolute().resolve()
    eligible: list[str] = []
    ineligible: list[str] = []
    for descriptor in descriptors:
        artifact_id = descriptor.get("source_artifact_id")
        source_ref = descriptor.get("source_ref")
        archive_ref = descriptor.get("archive_ref")
        source_safe = _safe_archive_ref(source_ref)
        archive_safe = _safe_archive_ref(archive_ref) and PurePosixPath(str(archive_ref)).as_posix() != "manifest.json"
        file_safe = False
        if source_safe:
            source_path = repository.joinpath(*PurePosixPath(str(source_ref)).parts)
            try:
                content = source_path.read_text(encoding="utf-8")
                file_safe = bool(
                    _regular_single_link(source_path)
                    and source_path.resolve().is_relative_to(repository)
                    and not _contains_secret(content)
                    and not _ABSOLUTE_HOME_PATH.search(content)
                )
            except (OSError, UnicodeDecodeError):
                file_safe = False
        valid = bool(
            global_ready
            and (
                normalized_binding.get("explicit") is not True
                or completion.get("version_binding_digest") in {None, normalized_binding["binding_digest"]}
            )
            and isinstance(artifact_id, str) and artifact_id
            and descriptor.get("publication_state") == "completed"
            and descriptor.get("visibility") == "public"
            and descriptor.get("artifact_version") == normalized_binding["artifact_version"]
            and (
                normalized_binding.get("explicit") is not True
                or descriptor.get("version_binding_digest") in {None, normalized_binding["binding_digest"]}
            )
            and descriptor.get("classification") == "public_completion_doc"
            and descriptor.get("accepted") is True
            and descriptor.get("validator_run_id")
            and descriptor.get("contract_revision") == completion.get("contract_revision")
            and source_safe and archive_safe and file_safe
        )
        (eligible if valid else ineligible).append(str(artifact_id))
    if not descriptors or ineligible:
        return _error(
            "E_V234_ARCHIVE_ELIGIBILITY", artifact_ids=eligible,
            ineligible_artifact_ids=ineligible,
        )
    return _ok(artifact_ids=eligible, ineligible_artifact_ids=[])


def sanitize_public_text(text: str) -> str:
    """Create a public-safe copy using the shared credential redactor."""
    retained = [
        line for line in text.splitlines()
        if not _INVOCATION_NOISE.search(line) and not _ABSOLUTE_HOME_PATH.search(line)
    ]
    result = _redact_text("\n".join(retained))
    if text.endswith("\n"):
        result += "\n"
    return result


def _decode_public_text(content: bytes) -> str | None:
    """Decode one public candidate or reject binary/ambiguous byte streams."""
    try:
        decoded = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    # Sanitization is a text transform.  Passing through C0/C1 controls would
    # turn it into an uninspected binary copy, so reject them fail closed.
    if any(
        (code < 32 and code not in {9, 10, 13}) or 127 <= code <= 159
        for code in map(ord, decoded)
    ):
        return None
    return decoded


def sanitize_public_copy(source: Path | str, destination: Path | str) -> dict[str, Any]:
    source_path = Path(source)
    destination_path = Path(destination)
    try:
        if not source_path.is_file() or source_path.is_symlink() or source_path.stat().st_nlink != 1:
            return _error("E_V234_ARCHIVE_SOURCE")
        original = source_path.read_bytes()
        decoded = _decode_public_text(original)
        if decoded is None:
            return _error("E_V236_PUBLIC_COPY_NON_TEXT")
        sanitized_text = sanitize_public_text(decoded)
        # A public copy is only writable after the shared detector confirms
        # that the transformed text contains no remaining credential syntax.
        if _contains_secret(sanitized_text):
            return _error("E_V236_PUBLIC_COPY_REDACTION_FAILED")
        sanitized = sanitized_text.encode("utf-8")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw = tempfile.mkstemp(prefix=f".{destination_path.name}.", suffix=".tmp", dir=destination_path.parent)
        temp_path = Path(raw)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(sanitized)
                stream.flush()
                os.fsync(stream.fileno())
            _replace_verified(temp_path, destination_path, allow_missing=True)
            _fsync_directory(destination_path.parent)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return _ok(
            source_sha256=_digest_bytes(original), public_sha256=_digest_bytes(sanitized),
            size=len(sanitized),
        )
    except OSError:
        return _error("E_V234_ARCHIVE_SOURCE")


def _archive_tree_digest(root: Path) -> str:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _digest_path(path),
                    "size": path.stat().st_size,
                }
            )
    return _digest_bytes(_canonical_bytes(entries))


def _safe_archive_ref(value: Any) -> bool:
    parts = _relative_parts(value)
    return bool(parts) and not any(
        part.startswith("GoalTeamsWork-") or part.lower() in _PROCESS_PATH_PARTS
        for part in parts
    )


def _prepare_archive(
    repo_root: Path, delivery_id: str, descriptors: list[dict[str, Any]],
    completion: dict[str, Any], *, completion_proof: dict[str, Any] | None = None,
    source_context: dict[str, Any] | None = None,
    normalized_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding = normalized_binding or _version_binding.default_version_binding()
    eligibility = validate_archive_eligibility(
        descriptors, completion, repo_root=repo_root,
        completion_proof=completion_proof, source_context=source_context,
        version_binding=binding,
    )
    if not eligibility.get("ok"):
        return eligibility
    if not _CANDIDATE_ID.fullmatch(delivery_id or ""):
        if binding.get("explicit") is True:
            return _version_binding._error("E_V235_VERSION_BINDING_PATH")
        return _error("E_V234_ARCHIVE_ID")
    if binding.get("explicit") is True:
        archive_path = _version_binding.public_archive_path(
            repo_root, binding, delivery_id=delivery_id
        )
        if not archive_path.get("ok"):
            return archive_path
    parent = repo_root.joinpath(*PurePosixPath(binding["archive_prefix"]).parts)
    temp_root = parent / f".{delivery_id}.tmp"
    archive_root = parent / delivery_id
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if temp_root.exists() or temp_root.is_symlink():
            return _error("E_V234_ARCHIVE_CONFLICT")
        temp_root.mkdir(mode=0o700)
        manifest_items: list[dict[str, Any]] = []
        seen_archive_refs: set[str] = set()
        for descriptor in descriptors:
            source_ref = descriptor.get("source_ref")
            archive_ref = descriptor.get("archive_ref")
            if (
                not _safe_archive_ref(source_ref)
                or not _safe_archive_ref(archive_ref)
                or PurePosixPath(str(archive_ref)).as_posix() == "manifest.json"
                or archive_ref in seen_archive_refs
            ):
                raise ValueError("unsafe archive descriptor")
            seen_archive_refs.add(str(archive_ref))
            source = repo_root.joinpath(*PurePosixPath(source_ref).parts)
            if (
                not source.is_file() or source.is_symlink() or source.stat().st_nlink != 1
                or not source.resolve().is_relative_to(repo_root.resolve())
                or any(part.startswith("GoalTeamsWork-") for part in PurePosixPath(source_ref).parts)
            ):
                raise ValueError("unsafe source")
            raw = source.read_bytes()
            decoded_source = _decode_public_text(raw)
            if (
                decoded_source is None
                or _contains_secret(decoded_source)
                or _ABSOLUTE_HOME_PATH.search(decoded_source)
            ):
                raise ValueError("secret source")
            destination = temp_root.joinpath(*PurePosixPath(archive_ref).parts)
            result = sanitize_public_copy(source, destination)
            if not result.get("ok"):
                raise ValueError("sanitization failed")
            if _digest_path(destination) != result["public_sha256"]:
                raise ValueError("public hash mismatch")
            media_type = mimetypes.guess_type(destination.name)[0] or "application/octet-stream"
            manifest_items.append(
                {
                    "source_artifact_id": descriptor["source_artifact_id"],
                    "public_relative_path": PurePosixPath(archive_ref).as_posix(),
                    "source_sha256": result["source_sha256"],
                    "public_sha256": result["public_sha256"],
                    "classification": descriptor["classification"],
                    "validator_run_id": descriptor["validator_run_id"],
                    "contract_revision": descriptor["contract_revision"],
                    "size": result["size"],
                    "media_type": media_type,
                    "generated_at": completion.get("generated_at", "2026-07-11T00:00:00Z"),
                }
            )
        manifest = {
            "schema_version": "goal-teams-v2.34-public-archive-v1",
            "delivery_id": delivery_id,
            "artifact_version": binding["artifact_version"],
            "contract_revision": completion.get("contract_revision"),
            "completion_audit_sha256": completion.get("completion_audit", {}).get("sha256"),
            "artifacts": manifest_items,
        }
        if binding.get("explicit") is True:
            manifest["release_version"] = binding["release_version"]
            manifest["version_binding_digest"] = binding["binding_digest"]
        manifest_path = temp_root / "manifest.json"
        manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
        with manifest_path.open("rb") as stream:
            os.fsync(stream.fileno())
        _fsync_directory(temp_root)
        for item in manifest_items:
            public_path = temp_root.joinpath(*PurePosixPath(item["public_relative_path"]).parts)
            if not _regular_single_link(public_path) or _digest_path(public_path) != item["public_sha256"]:
                raise ValueError("manifest public hash mismatch")
        desired_tree = _archive_tree_digest(temp_root)
        return _ok(
            temp_root=temp_root, archive_root=archive_root, manifest=manifest,
            manifest_sha256=_digest_path(manifest_path), archive_tree_sha256=desired_tree,
            **(
                {"version_binding_digest": binding["binding_digest"]}
                if binding.get("explicit") is True else {}
            ),
        )
    except (OSError, ValueError, KeyError):
        if temp_root.is_dir() and not temp_root.is_symlink():
            shutil.rmtree(temp_root)
        return _error("E_V234_ARCHIVE_SOURCE")


def create_public_archive(
    repo_root: Path | str, *, delivery_id: str,
    descriptors: list[dict[str, Any]], completion: dict[str, Any],
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = Path(repo_root).absolute().resolve()
    binding_result = _binding_result(repository, version_binding)
    if not binding_result.get("ok"):
        return binding_result
    normalized_binding = binding_result["binding"]
    if normalized_binding.get("explicit") is True:
        archive_path = _version_binding.public_archive_path(
            repository, normalized_binding, delivery_id=delivery_id
        )
        if not archive_path.get("ok"):
            return archive_path
    prepared = _prepare_archive(
        repository, delivery_id, descriptors, completion,
        normalized_binding=normalized_binding,
    )
    if not prepared.get("ok"):
        return prepared
    temp_root = Path(prepared["temp_root"])
    archive_root = Path(prepared["archive_root"])
    try:
        current_binding = _binding_result(repository, normalized_binding)
        if not current_binding.get("ok"):
            if temp_root.is_dir() and not temp_root.is_symlink():
                shutil.rmtree(temp_root)
            return current_binding
        if archive_root.exists() or archive_root.is_symlink():
            if archive_root.is_dir() and not archive_root.is_symlink() and _archive_tree_digest(archive_root) == prepared["archive_tree_sha256"]:
                shutil.rmtree(temp_root)
                return _ok(
                    idempotent=True, archive_ref=archive_root.relative_to(repository).as_posix(),
                    manifest_sha256=prepared["manifest_sha256"], archive_tree_sha256=prepared["archive_tree_sha256"],
                    **(
                        {"version_binding_digest": normalized_binding["binding_digest"]}
                        if normalized_binding.get("explicit") is True else {}
                    ),
                )
            shutil.rmtree(temp_root)
            return _error("E_V234_ARCHIVE_CONFLICT")
        os.replace(temp_root, archive_root)
        _fsync_directory(archive_root.parent)
        return _ok(
            idempotent=False, archive_ref=archive_root.relative_to(repository).as_posix(),
            manifest_sha256=prepared["manifest_sha256"], archive_tree_sha256=prepared["archive_tree_sha256"],
            **(
                {"version_binding_digest": normalized_binding["binding_digest"]}
                if normalized_binding.get("explicit") is True else {}
            ),
        )
    except OSError:
        if temp_root.is_dir() and not temp_root.is_symlink():
            shutil.rmtree(temp_root)
        return _error("E_V234_ARCHIVE_COMMIT")


def _delivery_journal_path(state_root: Path, delivery_id: str) -> Path:
    return state_root / ".goalteams-state" / "deliveries" / delivery_id / "journal.json"


def _deliver_locked(
    root: Path | str, *, repo_root: Path | str, delivery_id: str,
    transaction_id: str, descriptors: list[dict[str, Any]], completion: dict[str, Any],
    delivery_inputs: dict[str, Any], expected_bundle_revision: int,
    expected_bundle_digest: str, actor_run_id: str,
    fault_injector: Callable[[str], Any] | None = None,
    source_context: dict[str, Any] | None = None,
    normalized_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    repository = Path(repo_root).absolute().resolve()
    binding = normalized_binding or _version_binding.default_version_binding()
    validation = validate_state_bundle(
        state_root, repo_root=repository, version_binding=binding,
    )
    if not validation.get("ok"):
        return _state_write_error(validation)
    marker = validation["marker"]
    marker_binding = _marker_binding(marker)
    if (
        not marker_binding.get("ok")
        or marker_binding["binding"].get("binding_digest") != binding.get("binding_digest")
    ):
        return _version_binding._error("E_V235_VERSION_BINDING_MISMATCH")
    gate = evaluate_delivery_gate(
        marker, delivery_inputs, descriptors, source_context=source_context,
        version_binding=binding,
    )
    if not gate.get("ok"):
        return gate
    prepared = _prepare_archive(
        repository, delivery_id, descriptors, completion,
        completion_proof=delivery_inputs if source_context is not None else None,
        source_context=source_context,
        normalized_binding=binding,
    )
    if not prepared.get("ok"):
        return prepared
    temp_root = Path(prepared["temp_root"])
    archive_root = Path(prepared["archive_root"])
    if archive_root.exists() or archive_root.is_symlink():
        same_tree = archive_root.is_dir() and not archive_root.is_symlink() and _archive_tree_digest(archive_root) == prepared["archive_tree_sha256"]
        shutil.rmtree(temp_root)
        if not same_tree:
            return _error("E_V234_ARCHIVE_CONFLICT")
        delivery = marker.get("delivery", {})
        if (
            marker.get("loop", {}).get("run_outcome") == "achieved"
            and delivery.get("delivery_id") == delivery_id
            and delivery.get("transaction_id") == transaction_id
            and delivery.get("archive_tree_sha256") == prepared["archive_tree_sha256"]
        ):
            return _ok(
                idempotent=True, achieved=True, bundle_revision=marker["bundle_revision"],
                bundle_digest=marker["bundle_digest"], transaction_id=transaction_id,
                **(
                    {"version_binding_digest": binding["binding_digest"]}
                    if binding.get("explicit") is True else {}
                ),
            )
        return _error("E_V234_ARCHIVE_CONFLICT")
    if marker["bundle_revision"] != expected_bundle_revision or marker["bundle_digest"] != expected_bundle_digest:
        shutil.rmtree(temp_root)
        return _error("E_V234_CAS_CONFLICT")
    new_marker = copy.deepcopy(marker)
    new_marker["bundle_revision"] += 1
    new_marker["loop"].update(loop_decision="stop", run_outcome="achieved", stop_reason="achieved")
    new_marker["delivery"] = {
        "state": "delivered", "delivery_id": delivery_id, "transaction_id": transaction_id,
        "archive_ref": archive_root.relative_to(repository).as_posix(),
        "archive_tree_sha256": prepared["archive_tree_sha256"],
        "manifest_sha256": prepared["manifest_sha256"],
        "completion_audit_sha256": completion.get("completion_audit", {}).get("sha256"),
    }
    if binding.get("explicit") is True:
        new_marker["delivery"]["version_binding_digest"] = binding["binding_digest"]
    event = {
        "event_id": f"LOG-V234-DELIVERY-{delivery_id}",
        "event_type": "DELIVERY_COMMIT",
        "bundle_revision": new_marker["bundle_revision"],
        "iteration": 11, "attempt": new_marker["loop"].get("attempt", 1), "phase": "verify",
        "actor_run_id": actor_run_id, "timestamp": _now(),
        "intent_id": f"INTENT-V234-DELIVERY-{delivery_id}",
        "expected_constraints": ["iteration:11", "completion-audit:passed", "marker-last"],
        "judgment": "Publish the sanitized archive before committing achieved.",
        "action_scope": [archive_root.relative_to(repository).as_posix(), "feature_list.json", "progress.md", "log.md"],
        "prompt_ref": "prompts/lead/completion.md",
        "assertion_refs": ["ASSERT-V234-028", "ASSERT-V234-029", "ASSERT-V234-046"],
        "outcome": "achieved",
    }
    new_log, appended = _append_encoded_event((state_root / "log.md").read_bytes(), event)
    new_marker["log_commit_event_id"] = appended["event_id"]
    new_marker["log_commit_event_digest"] = appended["event_digest"]
    new_marker["log_sha256"] = _digest_bytes(new_log)
    new_progress = _encode_progress(new_marker)
    new_marker["progress_sha256"] = _digest_bytes(new_progress)
    new_marker["bundle_digest"] = _marker_digest(new_marker)
    files = {
        "log.md": new_log,
        "progress.md": new_progress,
        "feature_list.json": json.dumps(new_marker, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n",
    }
    temp_paths = {name: _write_temp(state_root / name, data, transaction_id) for name, data in files.items()}
    journal_path = _delivery_journal_path(state_root, delivery_id)
    journal = {
        "schema_version": "goal-teams-v2.34-delivery-journal-v1",
        "phase": "prepared", "delivery_id": delivery_id, "transaction_id": transaction_id,
        "expected_bundle_revision": marker["bundle_revision"], "expected_bundle_digest": marker["bundle_digest"],
        "target_bundle_revision": new_marker["bundle_revision"], "target_bundle_digest": new_marker["bundle_digest"],
        "archive_ref": archive_root.relative_to(repository).as_posix(),
        "archive_tree_sha256": prepared["archive_tree_sha256"],
        "manifest_sha256": prepared["manifest_sha256"],
        "new_files": {
            name: {
                "old_sha256": _digest_path(state_root / name),
                "sha256": _digest_bytes(data),
                "base64": base64.b64encode(data).decode("ascii"),
            }
            for name, data in files.items()
        },
    }
    if binding.get("explicit") is True:
        journal["version_binding_digest"] = binding["binding_digest"]
    _atomic_json(journal_path, journal)
    try:
        os.replace(temp_root, archive_root)
        if fault_injector:
            fault_injector("archive_renamed")
        _fsync_directory(archive_root.parent)
        if fault_injector:
            fault_injector("docs_parent_fsynced")
        for name, point in (
            ("log.md", "log_replaced"), ("progress.md", "progress_replaced"),
            ("feature_list.json", "feature_marker_replaced"),
        ):
            _replace_verified(temp_paths[name], state_root / name)
            _fsync_directory(state_root)
            if fault_injector:
                fault_injector(point)
        final_validation = validate_state_bundle(
            state_root, repo_root=repository, version_binding=binding,
        )
        if not final_validation.get("ok") or final_validation.get("state") not in {"valid", "ledger_unverified"}:
            raise OSError("delivery state failed final validation")
        journal["phase"] = "committed"
        _atomic_json(journal_path, journal)
        return _ok(
            idempotent=False, achieved=True, bundle_revision=new_marker["bundle_revision"],
            bundle_digest=new_marker["bundle_digest"], ledger_revision=new_marker.get("ledger", {}).get("revision"),
            transaction_id=transaction_id,
            **(
                {"version_binding_digest": binding["binding_digest"]}
                if binding.get("explicit") is True else {}
            ),
        )
    except Exception:
        # The complete journal and same-directory staged bytes intentionally
        # remain for fail-closed recovery.  Fault-injection exceptions retain
        # their type so tests and callers can prove the crash boundary.
        raise


def deliver(
    root: Path | str, *, repo_root: Path | str, delivery_id: str,
    transaction_id: str, descriptors: list[dict[str, Any]], completion: dict[str, Any],
    delivery_inputs: dict[str, Any], expected_bundle_revision: int,
    expected_bundle_digest: str, actor_run_id: str,
    fault_injector: Callable[[str], Any] | None = None,
    source_context: dict[str, Any] | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    repository = Path(repo_root).absolute().resolve()
    try:
        pre_marker = _json_object(state_root / "feature_list.json")
    except (OSError, ValueError, json.JSONDecodeError):
        pre_marker = None
    binding_result = _binding_result(
        repository, version_binding, marker=pre_marker if pre_marker is not None else None,
    )
    if not binding_result.get("ok"):
        return binding_result
    normalized_binding = binding_result["binding"]
    if normalized_binding.get("explicit") is True:
        path_result = _version_binding.public_archive_path(
            repository, normalized_binding, delivery_id=delivery_id
        )
        if not path_result.get("ok"):
            return path_result
    try:
        descriptor = _acquire_state_lock(state_root)
    except OSError:
        return _error("E_V234_STATE_LOCK_UNAVAILABLE")
    try:
        return _deliver_locked(
            state_root, repo_root=repo_root, delivery_id=delivery_id,
            transaction_id=transaction_id, descriptors=descriptors, completion=completion,
            delivery_inputs=delivery_inputs,
            expected_bundle_revision=expected_bundle_revision,
            expected_bundle_digest=expected_bundle_digest,
            actor_run_id=actor_run_id, fault_injector=fault_injector,
            source_context=source_context,
            normalized_binding=normalized_binding,
        )
    finally:
        _release_state_lock(descriptor)


def _recover_delivery_locked(
    root: Path | str, *, repo_root: Path | str, delivery_id: str, mode: str,
    descriptors: list[dict[str, Any]] | None = None,
    completion: dict[str, Any] | None = None,
    delivery_inputs: dict[str, Any] | None = None,
    actor_run_id: str | None = None,
    normalized_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    repository = Path(repo_root).absolute().resolve()
    binding = normalized_binding or _version_binding.default_version_binding()
    journal_path = _delivery_journal_path(state_root, delivery_id)
    archive_root = repository.joinpath(
        *PurePosixPath(binding["archive_prefix"]).parts, delivery_id
    )
    if not journal_path.is_file() or journal_path.is_symlink():
        return _error(
            "E_V234_DELIVERY_ORPHAN", state="reconcile_required", achieved=False,
        )
    try:
        journal = _json_object(journal_path)
        if (
            journal.get("delivery_id") != delivery_id
            or (
                binding.get("explicit") is True
                and journal.get("version_binding_digest") != binding["binding_digest"]
            )
            or not archive_root.is_dir() or archive_root.is_symlink()
            or _archive_tree_digest(archive_root) != journal.get("archive_tree_sha256")
        ):
            return _error("E_V234_DELIVERY_JOURNAL", state="reconcile_required", achieved=False)
        marker = _json_object(state_root / "feature_list.json")
        current_binding = _binding_result(repository, binding, marker=marker)
        if not current_binding.get("ok"):
            return current_binding
        marker_binding = _marker_binding(marker)
        if (
            not marker_binding.get("ok")
            or marker_binding["binding"].get("binding_digest") != binding.get("binding_digest")
        ):
            return _version_binding._error("E_V235_VERSION_BINDING_MISMATCH")
        if (
            marker.get("loop", {}).get("run_outcome") == "achieved"
            and marker.get("delivery", {}).get("delivery_id") == delivery_id
            and marker.get("bundle_digest") == journal.get("target_bundle_digest")
        ):
            if journal.get("phase") != "committed":
                journal["phase"] = "committed"
                _atomic_json(journal_path, journal)
            return _ok(
                state="valid", idempotent=True, achieved=True,
                bundle_revision=marker["bundle_revision"], bundle_digest=marker["bundle_digest"],
                transaction_id=journal.get("transaction_id"), journal_verified=True,
                **(
                    {"version_binding_digest": binding["binding_digest"]}
                    if binding.get("explicit") is True else {}
                ),
            )
        if mode == "inspect":
            return {
                "ok": True, "error_code": None, "state": "recoverable_pending",
                "achieved": False, "journal_verified": True,
            }
        if mode != "auto" or journal.get("phase") not in {"prepared", "marker_replaced"}:
            return _error("E_V234_DELIVERY_JOURNAL", state="reconcile_required", achieved=False)
        for name in ("log.md", "progress.md", "feature_list.json"):
            record = journal.get("new_files", {}).get(name)
            if not isinstance(record, dict):
                return _error("E_V234_DELIVERY_JOURNAL", state="reconcile_required", achieved=False)
            data = base64.b64decode(record.get("base64", ""), validate=True)
            if _digest_bytes(data) != record.get("sha256"):
                return _error("E_V234_DELIVERY_JOURNAL", state="reconcile_required", achieved=False)
            path = state_root / name
            if not path.is_file() or path.is_symlink():
                return _error("E_V234_DELIVERY_JOURNAL", state="reconcile_required", achieved=False)
            current_sha = _digest_path(path)
            if current_sha not in {record.get("old_sha256"), record.get("sha256")}:
                receipt = _record_divergent_hashes(
                    state_root, "delivery_recovery",
                    [{"path": name, "observed_sha256": current_sha, "old_sha256": record.get("old_sha256"), "new_sha256": record.get("sha256")}],
                )
                return _error(
                    "E_V234_DELIVERY_JOURNAL", state="reconcile_required",
                    achieved=False, divergence_receipt=receipt,
                )
            if current_sha != record["sha256"]:
                temp = _write_temp(path, data, str(journal["transaction_id"]) + "-recover")
                _replace_verified(temp, path)
                _fsync_directory(state_root)
        journal["phase"] = "committed"
        _atomic_json(journal_path, journal)
        final = validate_state_bundle(
            state_root, repo_root=repository, version_binding=binding,
        )
        if not final.get("ok") or final["marker"].get("loop", {}).get("run_outcome") != "achieved":
            return _error("E_V234_DELIVERY_JOURNAL", state="reconcile_required", achieved=False)
        return _ok(
            state="valid", idempotent=False, achieved=True, journal_verified=True,
            bundle_revision=final["bundle_revision"], bundle_digest=final["bundle_digest"],
            transaction_id=journal.get("transaction_id"),
            **(
                {"version_binding_digest": binding["binding_digest"]}
                if binding.get("explicit") is True else {}
            ),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, base64.binascii.Error):
        return _error("E_V234_DELIVERY_JOURNAL", state="reconcile_required", achieved=False)


def recover_delivery(
    root: Path | str, *, repo_root: Path | str, delivery_id: str, mode: str,
    descriptors: list[dict[str, Any]] | None = None,
    completion: dict[str, Any] | None = None,
    delivery_inputs: dict[str, Any] | None = None,
    actor_run_id: str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_root = Path(root)
    repository = Path(repo_root).absolute().resolve()
    try:
        pre_marker = _json_object(state_root / "feature_list.json")
    except (OSError, ValueError, json.JSONDecodeError):
        pre_marker = None
    binding_result = _binding_result(
        repository, version_binding, marker=pre_marker if pre_marker is not None else None,
    )
    if not binding_result.get("ok"):
        return binding_result
    normalized_binding = binding_result["binding"]
    if normalized_binding.get("explicit") is True:
        path_result = _version_binding.public_archive_path(
            repository, normalized_binding, delivery_id=delivery_id
        )
        if not path_result.get("ok"):
            return path_result
    try:
        descriptor = _acquire_state_lock(state_root)
    except OSError:
        return _error("E_V234_STATE_LOCK_UNAVAILABLE", state="blocked", achieved=False)
    try:
        return _recover_delivery_locked(
            state_root, repo_root=repo_root, delivery_id=delivery_id, mode=mode,
            descriptors=descriptors, completion=completion,
            delivery_inputs=delivery_inputs, actor_run_id=actor_run_id,
            normalized_binding=normalized_binding,
        )
    finally:
        _release_state_lock(descriptor)


def _git(repo: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
    )


def _git_with_env(
    repo: Path, arguments: list[str], environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments], cwd=repo, env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30,
    )


def _v234_product_path(
    relative: str, normalized_binding: dict[str, Any] | None = None,
) -> bool:
    """Return whether a path belongs to the versioned V2.34 product surface."""
    binding = normalized_binding or _version_binding.default_version_binding()
    parts = _relative_parts(relative)
    if not parts or parts[0].startswith("GoalTeamsWork-"):
        return False
    if relative == "references/skill-authoring-guide.md":
        # This is an optional user-provided reference, not a Goal Teams release file.
        return False
    exact_paths = _V235_PRODUCT_EXACT_PATHS if binding.get("explicit") is True else _V234_PRODUCT_EXACT_PATHS
    if relative in exact_paths:
        return True
    if relative.startswith("references/"):
        return True
    if relative.startswith("tests/v23/"):
        versions = "v23[45]" if binding.get("explicit") is True else "v234"
        return bool(re.fullmatch(rf"tests/v23/test_{versions}_[A-Za-z0-9_.-]+\.py", relative))
    prefixes = _V234_PRODUCT_PREFIXES
    if binding.get("explicit") is True:
        prefixes = (
            f"docs/archive/{binding['release_version']}/", "examples/", "prompts/",
            "schemas/v2.3/", "schemas/v2.35/", "scripts/", "subagents/",
        )
    return any(relative.startswith(prefix) for prefix in prefixes)


def _candidate_path_requirements(
    paths: list[str], normalized_binding: dict[str, Any] | None = None,
) -> list[str]:
    binding = normalized_binding or _version_binding.default_version_binding()
    available = set(paths)
    required = _V235_REQUIRED_CANDIDATE_PATHS if binding.get("explicit") is True else _V234_REQUIRED_CANDIDATE_PATHS
    gaps = sorted(required - available)
    test_version = "v235" if binding.get("explicit") is True else "v234"
    if not any(
        re.fullmatch(rf"tests/v23/test_{test_version}_[A-Za-z0-9_.-]+\.py", path)
        for path in paths
    ):
        gaps.append(f"tests/v23/test_{test_version}_*.py")
    return gaps


def _repository_protection_state(repository: Path) -> dict[str, Any] | None:
    head = _git(repository, ["rev-parse", "--verify", "HEAD^{commit}"])
    branch = _git(repository, ["symbolic-ref", "-q", "HEAD"])
    refs = _git(
        repository,
        [
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/heads/",
            "refs/remotes/",
            "refs/tags/",
        ],
    )
    index_name = _git(repository, ["rev-parse", "--git-path", "index"])
    if head.returncode != 0 or index_name.returncode != 0 or refs.returncode != 0:
        return None
    raw_index = index_name.stdout.decode("utf-8", errors="strict").strip()
    index_path = Path(raw_index)
    if not index_path.is_absolute():
        index_path = repository / index_path
    index_record: dict[str, Any]
    if index_path.exists() or index_path.is_symlink():
        if not _regular_single_link(index_path):
            return None
        index_record = {
            "exists": True,
            "sha256": _digest_path(index_path),
            "size": index_path.stat().st_size,
        }
    else:
        index_record = {"exists": False}
    return {
        "head_commit": head.stdout.decode("ascii").strip(),
        "head_symbolic_ref": branch.stdout.decode("utf-8").strip() if branch.returncode == 0 else None,
        # Codex desktop creates volatile refs/codex/turn-diffs/* checkpoints
        # while a turn is running.  They are neither publishable refs nor user
        # branch state, so binding them makes every honest snapshot instantly
        # stale.  Protect only conventional release-bearing ref namespaces.
        "refs_sha256": _digest_bytes(refs.stdout),
        "index": index_record,
    }


def _discover_v234_product_changes(
    repository: Path, baseline_commit: str,
    normalized_binding: dict[str, Any] | None = None,
) -> tuple[str | None, list[str] | None, str | None]:
    resolved = _git(repository, ["rev-parse", "--verify", f"{baseline_commit}^{{commit}}"])
    head = _git(repository, ["rev-parse", "--verify", "HEAD^{commit}"])
    if resolved.returncode != 0 or head.returncode != 0:
        return None, None, "E_V234_SNAPSHOT_BASELINE"
    baseline = resolved.stdout.decode("ascii").strip()
    if _git(repository, ["merge-base", "--is-ancestor", baseline, head.stdout.decode("ascii").strip()]).returncode != 0:
        return None, None, "E_V234_SNAPSHOT_BASELINE"
    tracked = _git(repository, ["diff", "--name-only", "--no-renames", "-z", baseline, "--"])
    untracked = _git(repository, ["ls-files", "--others", "--exclude-standard", "-z"])
    if tracked.returncode != 0 or untracked.returncode != 0:
        return None, None, "E_V234_SNAPSHOT_GIT"
    try:
        candidates = {
            item.decode("utf-8")
            for output in (tracked.stdout, untracked.stdout)
            for item in output.split(b"\0") if item
        }
    except UnicodeDecodeError:
        return None, None, "E_V234_SNAPSHOT_PATH"
    changed = sorted(
        path for path in candidates if _v234_product_path(path, normalized_binding)
    )
    if not changed:
        return baseline, None, "E_V234_SNAPSHOT_EMPTY_DELTA"
    gaps = _candidate_path_requirements(changed, normalized_binding)
    if gaps:
        return baseline, None, "E_V234_SNAPSHOT_REQUIRED_PRODUCT_DELTA"
    return baseline, changed, None


def _isolated_candidate_snapshot_core(
    repository: Path, baseline_commit: str,
    normalized_binding: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    binding = normalized_binding or _version_binding.default_version_binding()
    before = _repository_protection_state(repository)
    if before is None:
        return None, "E_V234_SNAPSHOT_REPOSITORY", []
    baseline, product_paths, discovery_error = _discover_v234_product_changes(
        repository, baseline_commit, binding
    )
    if discovery_error or baseline is None or product_paths is None:
        return None, discovery_error or "E_V234_SNAPSHOT_GIT", []
    objects_name = _git(repository, ["rev-parse", "--git-path", "objects"])
    baseline_tree = _git(repository, ["rev-parse", "--verify", f"{baseline}^{{tree}}"])
    if objects_name.returncode != 0 or baseline_tree.returncode != 0:
        return None, "E_V234_SNAPSHOT_GIT", []
    raw_objects = Path(objects_name.stdout.decode("utf-8", errors="strict").strip())
    main_objects = raw_objects if raw_objects.is_absolute() else repository / raw_objects
    records: list[dict[str, Any]] = []
    candidate_tree_oid = ""
    with tempfile.TemporaryDirectory(prefix="goalteams-v234-snapshot-") as directory:
        isolated_root = Path(directory)
        isolated_objects = isolated_root / "objects"
        (isolated_objects / "info").mkdir(parents=True)
        (isolated_objects / "pack").mkdir()
        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = str(isolated_root / "index")
        environment["GIT_OBJECT_DIRECTORY"] = str(isolated_objects)
        alternates = str(main_objects.absolute().resolve())
        if environment.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            alternates += os.pathsep + environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"]
        environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = alternates
        if _git_with_env(repository, ["read-tree", baseline], environment).returncode != 0:
            return None, "E_V234_SNAPSHOT_GIT", []
        for offset in range(0, len(product_paths), 128):
            result = _git_with_env(
                repository, ["add", "-A", "--", *product_paths[offset:offset + 128]], environment
            )
            if result.returncode != 0:
                return None, "E_V234_SNAPSHOT_GIT", []
        written = _git_with_env(repository, ["write-tree"], environment)
        if written.returncode != 0:
            return None, "E_V234_SNAPSHOT_GIT", []
        candidate_tree_oid = written.stdout.decode("ascii").strip()
        baseline_tree_oid = baseline_tree.stdout.decode("ascii").strip()
        if candidate_tree_oid == baseline_tree_oid:
            return None, "E_V234_SNAPSHOT_EMPTY_DELTA", []
        names_result = _git_with_env(
            repository,
            ["diff", "--name-only", "--no-renames", "-z", baseline_tree_oid, candidate_tree_oid],
            environment,
        )
        if names_result.returncode != 0:
            return None, "E_V234_SNAPSHOT_GIT", []
        try:
            changed_paths = sorted(
                item.decode("utf-8") for item in names_result.stdout.split(b"\0") if item
            )
        except UnicodeDecodeError:
            return None, "E_V234_SNAPSHOT_PATH", []
        if changed_paths != product_paths:
            return None, "E_V234_SNAPSHOT_SCOPE", changed_paths
        for relative in changed_paths:
            row_result = _git_with_env(
                repository, ["ls-tree", "-z", candidate_tree_oid, "--", relative], environment
            )
            if row_result.returncode != 0:
                return None, "E_V234_SNAPSHOT_GIT", []
            rows = [row for row in row_result.stdout.split(b"\0") if row]
            current = repository.joinpath(*PurePosixPath(relative).parts)
            if not rows:
                if current.exists() or current.is_symlink():
                    return None, "E_V234_SNAPSHOT_SOURCE_MISMATCH", [relative]
                records.append({"path": relative, "present": False, "status": "deleted"})
                continue
            if len(rows) != 1 or b"\t" not in rows[0] or not _regular_single_link(current):
                return None, "E_V234_SNAPSHOT_SOURCE_MISMATCH", [relative]
            metadata, encoded_path = rows[0].split(b"\t", 1)
            try:
                mode, object_type, object_oid = metadata.decode("ascii").split(" ")
                tree_path = encoded_path.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                return None, "E_V234_SNAPSHOT_GIT", [relative]
            if object_type != "blob" or tree_path != relative:
                return None, "E_V234_SNAPSHOT_GIT", [relative]
            blob = _git_with_env(repository, ["show", f"{candidate_tree_oid}:{relative}"], environment)
            if blob.returncode != 0 or blob.stdout != current.read_bytes():
                return None, "E_V234_SNAPSHOT_SOURCE_MISMATCH", [relative]
            records.append(
                {
                    "path": relative,
                    "present": True,
                    "status": "added_or_modified",
                    "mode": mode,
                    "blob_oid": object_oid,
                    "sha256": _digest_bytes(blob.stdout),
                    "size": len(blob.stdout),
                }
            )
    after = _repository_protection_state(repository)
    if after is None or after != before:
        return None, "E_V234_SNAPSHOT_REPOSITORY_MUTATED", []
    core = {
        "schema_version": _PROTECTED_CANDIDATE_SNAPSHOT_SCHEMA,
        "mode": "isolated_index_tree",
        "baseline_commit": baseline,
        "baseline_tree_oid": baseline_tree.stdout.decode("ascii").strip(),
        "candidate_tree_oid": candidate_tree_oid,
        "changed_paths": product_paths,
        "path_records": records,
        "product_manifest_sha256": _digest_bytes(_canonical_bytes(records)),
        "protected_repository_state": before,
    }
    if binding.get("explicit") is True:
        core["version_binding"] = copy.deepcopy(binding)
        core["version_binding_digest"] = binding["binding_digest"]
    return core, None, []


def create_protected_candidate_snapshot(
    repo_root: Path | str, *, baseline_commit: str, receipt_path: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a current-worktree tree receipt without touching index, refs, or history."""
    repository = Path(repo_root).absolute().resolve()
    binding_result = _binding_result(repository, version_binding)
    if not binding_result.get("ok"):
        return binding_result
    core, error, details = _isolated_candidate_snapshot_core(
        repository, baseline_commit, binding_result["binding"]
    )
    if error or core is None:
        return _error(error or "E_V234_SNAPSHOT_GIT", affected_paths=details, mutation_count=0)
    current_binding = _binding_result(repository, binding_result["binding"])
    if not current_binding.get("ok"):
        return current_binding
    receipt = {**core, "receipt_sha256": _digest_bytes(_canonical_bytes(core))}
    if receipt_path is not None:
        destination = Path(receipt_path).absolute()
        if (
            not destination.parent.is_dir()
            or destination.parent.is_symlink()
            or (destination.exists() or destination.is_symlink()) and not _regular_single_link(destination)
        ):
            return _error("E_V234_SNAPSHOT_RECEIPT_PATH", mutation_count=0)
        resolved_destination = destination.parent.resolve() / destination.name
        try:
            resolved_destination.relative_to((repository / ".git").resolve())
            return _error("E_V234_SNAPSHOT_RECEIPT_PATH", mutation_count=0)
        except ValueError:
            pass
        try:
            _atomic_json(resolved_destination, receipt)
        except OSError:
            return _error("E_V234_SNAPSHOT_RECEIPT_WRITE", mutation_count=0)
    return _ok(receipt=receipt, mutation_count=1 if receipt_path is not None else 0)


def validate_protected_candidate_snapshot(
    repo_root: Path | str, receipt: dict[str, Any], *,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = Path(repo_root).absolute().resolve()
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != _PROTECTED_CANDIDATE_SNAPSHOT_SCHEMA
        or receipt.get("mode") != "isolated_index_tree"
    ):
        return _error("E_V234_SNAPSHOT_RECEIPT")
    embedded_binding = receipt.get("version_binding")
    binding_result = _binding_result(
        repository,
        version_binding if version_binding is not None else embedded_binding,
    )
    if not binding_result.get("ok"):
        return binding_result
    normalized_binding = binding_result["binding"]
    if normalized_binding.get("explicit") is True and receipt.get("version_binding_digest") != normalized_binding["binding_digest"]:
        return _version_binding._error("E_V235_VERSION_BINDING_DIGEST")
    supplied_core = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _digest_bytes(_canonical_bytes(supplied_core)):
        return _error("E_V234_SNAPSHOT_RECEIPT")
    baseline = receipt.get("baseline_commit")
    if not isinstance(baseline, str):
        return _error("E_V234_SNAPSHOT_RECEIPT")
    current_core, error, details = _isolated_candidate_snapshot_core(
        repository, baseline, normalized_binding
    )
    if error or current_core is None:
        return _error(error or "E_V234_SNAPSHOT_STALE", affected_paths=details)
    if current_core != supplied_core:
        return _error("E_V234_SNAPSHOT_STALE")
    return _ok(
        mode="snapshot", checked_paths=receipt["changed_paths"],
        candidate_tree_oid=receipt["candidate_tree_oid"],
        receipt_sha256=receipt["receipt_sha256"],
    )


def _publish_path_denied(relative: str, content: bytes) -> bool:
    parts = PurePosixPath(relative).parts
    lowered = {part.lower() for part in parts}
    if not parts or parts[0].startswith("GoalTeamsWork-"):
        return True
    if lowered & {
        ".goalteams-state", ".goalteams-quarantine", "ledger", "evidence", "audit",
        "reviews", "harness", "identity", "provenance", "secrets", "credentials",
    }:
        return True
    if parts[-1].lower() in {"progress.md", "log.md", "contract.md", ".env"}:
        return True
    decoded = _decode_public_text(content)
    if decoded is None:
        return True
    return bool(_contains_secret(decoded) or _INVOCATION_NOISE.search(decoded))


def publish_guard(
    repo_root: Path | str, *, mode: str, commit: str | None = None,
    baseline_commit: str | None = None,
    snapshot_receipt: dict[str, Any] | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repository = Path(repo_root).absolute().resolve()
    embedded_binding = (
        snapshot_receipt.get("version_binding")
        if isinstance(snapshot_receipt, dict) else None
    )
    binding_result = _binding_result(
        repository,
        version_binding if version_binding is not None else embedded_binding,
    )
    if not binding_result.get("ok"):
        return binding_result
    normalized_binding = binding_result["binding"]
    if mode == "snapshot":
        validation = validate_protected_candidate_snapshot(
            repository, snapshot_receipt if isinstance(snapshot_receipt, dict) else {},
            version_binding=normalized_binding,
        )
        if not validation.get("ok"):
            return _error(
                "E_V234_PUBLISH_SNAPSHOT", snapshot_error=validation.get("error_code"),
                checked_paths=validation.get("checked_paths", []), denied_paths=[],
            )
        return _ok(
            denied_paths=[], checked_paths=validation["checked_paths"], mode=mode,
            candidate_tree_oid=validation["candidate_tree_oid"],
            receipt_sha256=validation["receipt_sha256"],
            **(
                {"version_binding_digest": normalized_binding["binding_digest"]}
                if normalized_binding.get("explicit") is True else {}
            ),
        )
    if mode == "index":
        names_result = _git(repository, ["diff", "--cached", "--name-only", "-z"])
        if names_result.returncode != 0:
            return _error("E_V234_PUBLISH_GIT")
        names = [item.decode("utf-8") for item in names_result.stdout.split(b"\0") if item]
        content_command = lambda name: _git(repository, ["show", f":{name}"])
    elif mode == "commit" and commit:
        if baseline_commit:
            ancestry = _git(repository, ["merge-base", "--is-ancestor", baseline_commit, commit])
            if ancestry.returncode != 0:
                return _error("E_V234_PUBLISH_BASELINE")
            names_result = _git(repository, ["diff", "--name-only", "-z", baseline_commit, commit])
        else:
            parent = _git(repository, ["rev-parse", "--verify", f"{commit}^"])
            if parent.returncode == 0:
                parent_id = parent.stdout.decode("ascii").strip()
                names_result = _git(repository, ["diff", "--name-only", "-z", parent_id, commit])
            else:
                names_result = _git(
                    repository,
                    ["diff-tree", "--root", "--no-commit-id", "-r", "--name-only", "-z", commit],
                )
        if names_result.returncode != 0:
            return _error("E_V234_PUBLISH_GIT")
        names = [item.decode("utf-8") for item in names_result.stdout.split(b"\0") if item]
        content_command = lambda name: _git(repository, ["show", f"{commit}:{name}"])
    else:
        return _error("E_V234_PUBLISH_MODE")
    if mode == "commit" and not names:
        return _error(
            "E_V234_PUBLISH_EMPTY_DELTA", denied_paths=[], checked_paths=[], mode=mode
        )
    denied: list[str] = []
    for name in names:
        result = content_command(name)
        content = result.stdout if result.returncode == 0 else b""
        if result.returncode != 0 or _publish_path_denied(name, content):
            denied.append(name)
    if denied:
        return _error("E_V234_PUBLISH_GUARD", denied_paths=sorted(denied), checked_paths=sorted(names))
    return _ok(
        denied_paths=[], checked_paths=sorted(names), mode=mode,
        **(
            {"version_binding_digest": normalized_binding["binding_digest"]}
            if normalized_binding.get("explicit") is True else {}
        ),
    )


def capture_worktree_guard(repo_root: Path | str, *, protected_paths: list[str]) -> dict[str, Any]:
    repository = Path(repo_root).absolute().resolve()
    records: dict[str, dict[str, Any]] = {}
    for relative in protected_paths:
        if not _safe_archive_ref(relative):
            continue
        path = repository.joinpath(*PurePosixPath(relative).parts)
        if path.is_file() and not path.is_symlink():
            records[relative] = {"exists": True, "sha256": _digest_path(path), "size": path.stat().st_size}
        else:
            records[relative] = {"exists": False}
    return {
        "schema_version": "goal-teams-v2.34-worktree-guard-v1",
        "repo_root": str(repository),
        "protected": records,
        "guard_sha256": _digest_bytes(_canonical_bytes(records)),
    }


def validate_worktree_guard(
    repo_root: Path | str, guard: dict[str, Any], *, allowed_paths: list[str],
) -> dict[str, Any]:
    repository = Path(repo_root).absolute().resolve()
    protected = guard.get("protected", {})
    if guard.get("repo_root") != str(repository) or guard.get("guard_sha256") != _digest_bytes(_canonical_bytes(protected)):
        return _error("E_V234_WORKTREE_GUARD", changed_protected_paths=[])
    changed: list[str] = []
    for relative, prior in protected.items():
        path = repository.joinpath(*PurePosixPath(relative).parts)
        if prior.get("exists") is True:
            if not path.is_file() or path.is_symlink() or _digest_path(path) != prior.get("sha256"):
                changed.append(relative)
        elif path.exists() or path.is_symlink():
            changed.append(relative)
    if changed:
        return _error("E_V234_WORKTREE_SCOPE", changed_protected_paths=sorted(changed))
    return _ok(changed_protected_paths=[], allowed_paths=sorted(allowed_paths))


def validate_version_sync(repo_root: Path | str, *, expected_version: str) -> dict[str, Any]:
    repository = Path(repo_root).absolute().resolve()
    checked = [
        "VERSION", "SKILL.md", "README.md", "README.en.md",
        "scripts/v23/goalteams_v23.py", "agents/openai.yaml",
    ]
    stale: list[str] = []
    patterns = {
        "SKILL.md": (
            rf"(?:当前版本|产品)\s*`{re.escape(expected_version)}`",
            rf"Goal Teams Lead {re.escape(expected_version)}",
        ),
        "README.md": (rf"当前版本：`{re.escape(expected_version)}`",),
        "README.en.md": (rf"Current version: `{re.escape(expected_version)}`",),
        "scripts/v23/goalteams_v23.py": (rf"PRODUCT_VERSION\s*=\s*[\"']{re.escape(expected_version)}[\"']",),
        "agents/openai.yaml": (rf"Goal Teams {re.escape(expected_version)}",),
    }
    for relative in checked:
        path = repository / relative
        if not path.is_file() or path.is_symlink():
            stale.append(relative)
            continue
        text = path.read_text(encoding="utf-8")
        if relative == "VERSION":
            if text.strip() != expected_version:
                stale.append(relative)
        elif not all(re.search(pattern, text) for pattern in patterns[relative]):
            stale.append(relative)
    if stale:
        return _error("E_V234_VERSION_SYNC", checked_paths=checked, stale_current_version_markers=sorted(stale))
    return _ok(checked_paths=checked, stale_current_version_markers=[])


def validate_release_closure(
    completion_proof: dict[str, Any], *, source_context: dict[str, Any] | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supplied_binding = version_binding
    if supplied_binding is None and isinstance(source_context, dict):
        candidate = source_context.get("version_binding")
        supplied_binding = candidate if isinstance(candidate, dict) else None
    binding_result = _binding_result(
        (source_context or {}).get("repo_root", "."), supplied_binding
    )
    if not binding_result.get("ok"):
        return binding_result
    errors = _completion_proof_errors(
        completion_proof, source_context or {}, bundle=None, archive_descriptor=None,
        normalized_binding=binding_result["binding"],
    )
    if errors:
        return _error("E_V234_RELEASE_CLOSURE", gaps=errors)
    return _ok(gaps=[])
