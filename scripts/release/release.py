#!/usr/bin/env python3
"""Goal Teams V2.40 release-policy engine and single release entry.

The public functions in this module are deterministic policy boundaries.  Live
Git/filesystem/GitHub observations are collected by fixed read-only adapters;
caller JSON supplies expected scope and explicit write authorization, never
success facts.  External mutation belongs to a separately authenticated adapter.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
try:
    import pwd
except ModuleNotFoundError:  # pragma: no cover - production release hosts are Unix
    pwd = None  # type: ignore[assignment]
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


def _require_python_311(version_info: Sequence[int] | None = None) -> None:
    """Fail before release-state or external operations on unsupported Python."""

    observed = sys.version_info if version_info is None else version_info
    if tuple(observed[:2]) < (3, 11):
        raise SystemExit("E_V240_PYTHON_VERSION: Python 3.11+ required")


_require_python_311()

try:
    import fcntl  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - release hosts are Unix
    fcntl = None


README_START = "<!-- goal-teams-release:start -->"
README_END = "<!-- goal-teams-release:end -->"
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
CHECKPOINT_RE = re.compile(r"^CP(?:0[0-9]|1[0-8])$")
V236_GOAL_TEAMS_TRUSTED_RELEASE_BASE = "c91e33737cc13c68bb5cb34c572fa05e7849f1e4"
FIXED_GITHUB_REPOSITORY_ID = 1249985345
RELEASE_ROOT = Path(__file__).resolve().parents[2]
PROMOTION_SCHEMA_PATH = (
    RELEASE_ROOT / "schemas" / "release-promotion-state.schema.json"
)

TAR_LIMITS = {
    "member_count": 2048,
    "max_path_bytes": 240,
    "max_single_file_bytes": 16 * 1024 * 1024,
    "total_uncompressed_bytes": 128 * 1024 * 1024,
    "compression_ratio": 100,
}

PUBLIC_RELEASE_SURFACES = {
    "release_asset",
    "tag_message",
    "tracked_release_note",
    "tracked_readme",
}
CANONICAL_RELEASE_TITLE = "Goal Teams V2.40"
CANONICAL_RELEASE_BODY = (
    "Goal Teams V2.40. See release/current/README.md in the tagged source."
)
CANONICAL_TAG_MESSAGE = "Goal Teams V2.40"
PUBLIC_SCAN_RELATIVE = "scripts/release/public_scan.py"
PUBLIC_SCAN_DETECTOR_RELATIVE = "scripts/v23/v236_security.py"
PUBLIC_SCAN_BASELINE_RELATIVE = (
    "references/public-release-scan-baseline-v2.40.json"
)


class PolicyError(RuntimeError):
    """A policy failure with a stable, machine-readable zero-effect receipt."""

    def __init__(self, error_code: str, message: str = "", **details: Any) -> None:
        receipt: dict[str, Any] = {
            "passed": False,
            "error_code": error_code,
            "mutation_count": 0,
            "external_side_effect_count": 0,
        }
        receipt.update(details)
        self.receipt = receipt
        super().__init__(f"{error_code}: {message or 'release policy rejected input'}")


def _fail(error_code: str, message: str = "", **details: Any) -> None:
    raise PolicyError(error_code, message, **details)


def _success(**details: Any) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "passed": True,
        "mutation_count": 0,
        "external_side_effect_count": 0,
    }
    receipt.update(details)
    return receipt


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sanitized_git_environment(
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Remove caller-controlled Git redirection and disable replace objects."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if extra:
        if any(key.startswith("GIT_") for key in extra):
            _fail("E_V240_GIT_OBJECT_GRAPH", "internal Git environment override")
        environment.update(extra)
    return environment


def _no_replace_git_argv(argv: Sequence[str]) -> list[str]:
    values = list(argv)
    if values and Path(values[0]).name == "git":
        if len(values) < 2 or values[1] != "--no-replace-objects":
            values.insert(1, "--no-replace-objects")
    return values


def _run_git_unchecked(
    argv: Sequence[str],
    *,
    cwd: Path,
    text: bool = False,
    timeout: float | None = None,
    capture_output: bool = True,
    stdout: Any = None,
    stderr: Any = None,
) -> subprocess.CompletedProcess[Any]:
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": _sanitized_git_environment(),
        "text": text,
        "check": False,
        "timeout": timeout,
    }
    if capture_output:
        kwargs["capture_output"] = True
    else:
        kwargs["stdout"] = stdout
        kwargs["stderr"] = stderr
    return subprocess.run(_no_replace_git_argv(argv), **kwargs)


_DANGEROUS_GIT_ENV = frozenset(
    {
        "GIT_DIR",
        "GIT_COMMON_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_CONFIG",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_COUNT",
    }
)


def _assert_unmodified_git_object_graph(root: Path) -> dict[str, Any]:
    """Reject local Git features that can rewrite or omit frozen objects."""

    poisoned = sorted(key for key in _DANGEROUS_GIT_ENV if key in os.environ)
    if poisoned:
        _fail(
            "E_V240_GIT_OBJECT_GRAPH",
            f"caller Git environment is not trusted: {poisoned}",
        )
    common_result = _run_git_unchecked(
        ("git", "rev-parse", "--git-common-dir"), cwd=root, text=True
    )
    if common_result.returncode != 0:
        _fail("E_V240_GIT_OBJECT_GRAPH", "cannot resolve Git common directory")
    common = Path(common_result.stdout.strip())
    if not common.is_absolute():
        common = (root / common).resolve()
    forbidden_paths = [
        common / "info" / "grafts",
        common / "objects" / "info" / "alternates",
    ]
    if any(path.exists() or path.is_symlink() for path in forbidden_paths):
        _fail("E_V240_GIT_OBJECT_GRAPH", "Git graft/alternate object source exists")
    if any((common / "objects" / "pack").glob("*.promisor")):
        _fail("E_V240_GIT_OBJECT_GRAPH", "partial-clone promisor pack exists")
    replacements = _run_git_unchecked(
        ("git", "for-each-ref", "--format=%(refname)", "refs/replace/"),
        cwd=root,
        text=True,
    )
    if replacements.returncode != 0 or replacements.stdout.strip():
        _fail("E_V240_GIT_OBJECT_GRAPH", "Git replace refs are forbidden")
    shallow = _run_git_unchecked(
        ("git", "rev-parse", "--is-shallow-repository"),
        cwd=root,
        text=True,
    )
    if shallow.returncode != 0 or shallow.stdout.strip() != "false":
        _fail("E_V240_GIT_OBJECT_GRAPH", "shallow repositories are forbidden")
    configuration = _run_git_unchecked(
        ("git", "config", "--local", "--name-only", "--list"),
        cwd=root,
        text=True,
    )
    if configuration.returncode != 0:
        _fail("E_V240_GIT_OBJECT_GRAPH", "cannot inspect local Git configuration")
    risky_names = {
        line.strip().lower()
        for line in configuration.stdout.splitlines()
        if line.strip()
    }
    if any(
        name == "extensions.partialclone"
        or (name.startswith("remote.") and name.endswith(".promisor"))
        or (name.startswith("remote.") and name.endswith(".partialclonefilter"))
        for name in risky_names
    ):
        _fail("E_V240_GIT_OBJECT_GRAPH", "partial-clone configuration is forbidden")
    return {
        "git_common_dir_sha256": hashlib.sha256(
            str(common).encode("utf-8")
        ).hexdigest(),
        "replace_ref_count": 0,
        "shallow": False,
        "partial_clone": False,
    }


def _validate_release_intent_metadata(
    expected_before: Mapping[str, Any],
    candidate_commit: Any,
    *,
    require_release_id: bool,
) -> None:
    """Require canonical Release metadata in the persisted operation intent."""

    candidate = _require_sha40(
        candidate_commit, "E_V240_RELEASE_SOURCE_IDENTITY"
    )
    if (
        expected_before.get("targetCommitish") != candidate
        or expected_before.get("name") != CANONICAL_RELEASE_TITLE
        or expected_before.get("body") != CANONICAL_RELEASE_BODY
    ):
        _fail(
            "E_V240_STATE_EXPECTED_BEFORE",
            "Release intent target/title/body is not canonical",
        )
    release_id = expected_before.get("release_id")
    if require_release_id and (
        not isinstance(release_id, int)
        or isinstance(release_id, bool)
        or release_id < 1
    ):
        _fail(
            "E_V240_STATE_EXPECTED_BEFORE",
            "publish intent lacks the verified Draft release id",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any, error_code: str) -> datetime:
    if not isinstance(value, str):
        _fail(error_code, "timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(error_code, f"invalid timestamp: {value!r}")
    if parsed.tzinfo is None:
        _fail(error_code, "timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _require_sha40(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or SHA40_RE.fullmatch(value) is None:
        _fail(error_code, "expected an immutable lowercase 40-hex commit")
    return value


def _require_sha256(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail(error_code, "expected a lowercase SHA-256 digest")
    return value


def _load_promotion_schema() -> dict[str, Any]:
    try:
        value = json.loads(PROMOTION_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("E_V240_STATE_SCHEMA", f"cannot load promotion schema: {exc}")
    if not isinstance(value, dict):
        _fail("E_V240_STATE_SCHEMA", "promotion schema is not an object")
    return value


def validate_readme_projection(root: str | os.PathLike[str], version: str) -> dict[str, Any]:
    """Validate the unique controlled release block in both root READMEs."""

    if not isinstance(version, str) or VERSION_RE.fullmatch(version) is None:
        _fail("E_V240_README_VERSION", "invalid expected version")
    root_path = Path(root)
    records: dict[str, Any] = {}
    for name in ("README.md", "README.en.md"):
        path = root_path / name
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _fail("E_V240_README_MARKER", f"{name}: {exc}")
        start_count = text.count(README_START)
        end_count = text.count(README_END)
        if start_count != 1 or end_count != 1:
            _fail(
                "E_V240_README_MARKER",
                f"{name} must contain exactly one controlled block",
            )
        start = text.index(README_START)
        end = text.index(README_END, start) + len(README_END)
        block = text[start:end]
        declared = re.search(r"\*\*(V[0-9]+\.[0-9]+)\*\*", block)
        if declared is None or declared.group(1) != version:
            _fail("E_V240_README_VERSION", f"{name} release version drift")
        found_versions = {
            match.upper()
            for match in re.findall(r"\b[Vv][0-9]+\.[0-9]+\b", block)
        }
        if found_versions - {version.upper()}:
            _fail(
                "E_V240_README_STALE_IDENTITY",
                f"{name} contains another current release identity",
            )
        if "release/current/README.md" not in block:
            _fail(
                "E_V240_README_CURRENT_LINK",
                f"{name} does not link release/current/README.md",
            )
        records[name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "marker_count": start_count,
        }
    return _success(version=version, files=records)


def require_frozen_commit(value: str, *, object_type: str = "commit") -> dict[str, Any]:
    commit = _require_sha40(value, "E_V240_FROZEN_COMMIT")
    if object_type != "commit":
        _fail(
            "E_V240_FROZEN_OBJECT_TYPE",
            f"Git object {commit} is {object_type!r}, not a commit",
        )
    return _success(commit=commit, frozen=True, object_type="commit")


def validate_frozen_release_record(
    record: Mapping[str, Any], version: str, candidate_commit: str
) -> dict[str, Any]:
    candidate = _require_sha40(
        candidate_commit, "E_V240_RELEASE_SOURCE_IDENTITY"
    )
    if (
        not isinstance(record, Mapping)
        or record.get("version") != version
        or record.get("source_commit") != candidate
        or SHA40_RE.fullmatch(str(record.get("source_commit", ""))) is None
        or SHA40_RE.fullmatch(str(record.get("source_git_tree_id", ""))) is None
    ):
        _fail(
            "E_V240_RELEASE_SOURCE_IDENTITY",
            "release record is not bound to the frozen commit and version",
        )
    return _success(
        version=version,
        source_commit=candidate,
        source_git_tree_id=record["source_git_tree_id"],
        identity_authority="source_commit",
    )


def validate_workspace_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on topology facts collected by the workspace doctor."""

    if bool(facts.get("canonical_dirty")):
        _fail("E_V240_WORKTREE_DIRTY", "canonical root is dirty")
    if bool(facts.get("dirty")):
        _fail("E_V240_WORKTREE_DIRTY", "candidate worktree is dirty")
    if facts.get("candidate_location") != "develops/v2.40":
        _fail(
            "E_V240_WORKTREE_LOCATION",
            "candidate must live at develops/v2.40",
        )
    if (
        facts.get("candidate_branch") != facts.get("expected_candidate_branch")
        or facts.get("candidate_branch") != "codex/v2.40"
    ):
        _fail("E_V240_WORKTREE_BRANCH", "candidate branch is not codex/v2.40")
    if not bool(facts.get("candidate_descends_from_remote_main")):
        _fail(
            "E_V240_CANDIDATE_ANCESTRY",
            "candidate is not a descendant of frozen remote main",
        )
    if list(facts.get("tracked_local_only_paths") or []):
        _fail(
            "E_V240_LOCAL_PATH_TRACKED",
            "a local-only path is tracked",
        )
    if list(facts.get("parent_version_copies") or []):
        _fail("E_V240_PARENT_COPY", "version copy exists outside the repository")
    if bool(facts.get("tag_exists")):
        _fail("E_V240_TAG_EXISTS", "release tag already exists")
    if bool(facts.get("release_exists")):
        _fail("E_V240_RELEASE_EXISTS", "GitHub Release already exists")
    tools = facts.get("tools")
    if not isinstance(tools, Mapping) or not all(
        bool(tools.get(name)) for name in ("git", "gh", "python_3_11")
    ):
        _fail("E_V240_TOOL_UNAVAILABLE", "a required release tool is unavailable")
    if facts.get("canonical_root_role") != "stable" or facts.get(
        "canonical_branch"
    ) != "main":
        _fail("E_V240_WORKTREE_LOCATION", "canonical root is not stable main")
    worktrees = facts.get("worktrees")
    if worktrees is not None:
        if not isinstance(worktrees, list) or len(worktrees) < 2:
            _fail("E_V240_WORKTREE_LOCATION", "live worktree inventory is incomplete")
        stable = [
            item
            for item in worktrees
            if isinstance(item, Mapping) and item.get("role") == "stable"
        ]
        candidates = [
            item
            for item in worktrees
            if isinstance(item, Mapping) and item.get("role") == "active_candidate"
        ]
        legacy = [
            item
            for item in worktrees
            if isinstance(item, Mapping)
            and item.get("role") not in {"stable", "active_candidate"}
        ]
        if len(stable) != 1 or len(candidates) != 1:
            _fail("E_V240_WORKTREE_LOCATION", "stable/candidate worktree roles are not unique")
        if any(
            item.get("role") != "archived_non_active"
            or item.get("active") is not False
            for item in legacy
        ):
            _fail("E_V240_WORKTREE_LOCATION", "legacy worktree is not archived/non-active")
    candidate = _require_sha40(
        facts.get("candidate_commit"), "E_V240_FROZEN_COMMIT"
    )
    remote_main = _require_sha40(
        facts.get("remote_main_commit"), "E_V240_REMOTE_MAIN_LEASE"
    )
    check_names = [
        "canonical_root_role",
        "canonical_branch",
        "canonical_worktree_clean",
        "candidate_location",
        "candidate_branch",
        "worktree_clean",
        "candidate_ancestry",
        "local_only_paths_untracked",
        "parent_copy_absent",
        "tag_absent",
        "release_absent",
        "required_tools",
        "immutable_candidate_commit",
    ]
    return _success(
        candidate_commit=candidate,
        remote_main_commit=remote_main,
        checks=[{"name": name, "status": "passed"} for name in check_names],
    )


def commit_checkpoint(
    state_path: str | os.PathLike[str],
    checkpoint_id: str,
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    """Write a checkpoint marker only after a verified receipt.

    This is the sole policy helper in this module that mutates a file.  The
    write is atomic and happens only after all validation has completed.
    """

    path = Path(state_path)
    if (
        not isinstance(verification, Mapping)
        or verification.get("verified") is not True
        or SHA40_RE.fullmatch(str(verification.get("candidate_commit", "")))
        is None
        or SHA256_RE.fullmatch(str(verification.get("receipt_sha256", "")))
        is None
    ):
        _fail(
            "E_V240_CHECKPOINT_UNVERIFIED",
            "checkpoint marker requires a verified, digest-bound receipt",
        )
    try:
        original = path.read_bytes()
        state = json.loads(original)
    except (OSError, json.JSONDecodeError) as exc:
        _fail("E_V240_CHECKPOINT_UNVERIFIED", f"cannot read state: {exc}")
    checkpoints = state.get("checkpoints")
    if not isinstance(checkpoints, dict) or checkpoint_id not in checkpoints:
        _fail("E_V240_CHECKPOINT_ORDER", "checkpoint is not present in state")
    record = checkpoints[checkpoint_id]
    if (
        verification["candidate_commit"] != state.get("candidate_commit")
        or record.get("candidate_commit") != state.get("candidate_commit")
    ):
        _fail("E_V240_CHECKPOINT_UNVERIFIED", "candidate binding drift")
    if record.get("status") == "passed":
        if record.get("receipt_sha256") != verification["receipt_sha256"]:
            _fail(
                "E_V240_CHECKPOINT_UNVERIFIED",
                "completed checkpoint receipt does not match",
            )
        result = copy.deepcopy(state)
        result["already_completed"] = True
        result["mutation_count"] = 0
        result["external_side_effect_count"] = 0
        result["passed"] = True
        return result
    if state.get("current_checkpoint") != checkpoint_id:
        _fail(
            "E_V240_CHECKPOINT_ORDER",
            f"expected {state.get('current_checkpoint')}, got {checkpoint_id}",
        )
    updated = copy.deepcopy(state)
    updated_record = updated["checkpoints"][checkpoint_id]
    updated_record["status"] = "passed"
    updated_record["receipt_sha256"] = verification["receipt_sha256"]
    updated_record["completed_at"] = str(
        verification.get("completed_at") or _utc_now()
    )
    updated["current_checkpoint"] = checkpoint_id
    updated["updated_at"] = _utc_now()
    payload = (
        json.dumps(updated, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    temp_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temp_name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    result = copy.deepcopy(updated)
    result["already_completed"] = False
    result["passed"] = True
    result["mutation_count"] = 1
    result["external_side_effect_count"] = 0
    return result


def plan_resume(state_path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("E_V240_STATE_SCHEMA", f"cannot read promotion state: {exc}")
    checkpoints = state.get("checkpoints")
    if not isinstance(checkpoints, dict):
        _fail("E_V240_STATE_SCHEMA", "checkpoints must be an object")
    skipped = [
        checkpoint_id
        for checkpoint_id, record in checkpoints.items()
        if isinstance(record, Mapping) and record.get("status") == "passed"
    ]
    next_checkpoint = next(
        (
            checkpoint_id
            for checkpoint_id, record in checkpoints.items()
            if not isinstance(record, Mapping) or record.get("status") != "passed"
        ),
        "CP18",
    )
    next_record = checkpoints.get(next_checkpoint, {})
    actions = [
        operation.get("operation_id")
        for operation in next_record.get("operations", [])
        if isinstance(operation, Mapping)
    ]
    return _success(
        next_checkpoint=next_checkpoint,
        skip_side_effects=skipped,
        actions=actions,
    )


def validate_remote_lease(
    expected_main_commit: str,
    observed_main_commit: str,
    candidate_commit: str,
) -> dict[str, Any]:
    expected = _require_sha40(
        expected_main_commit, "E_V240_REMOTE_MAIN_LEASE"
    )
    observed = _require_sha40(
        observed_main_commit, "E_V240_REMOTE_MAIN_LEASE"
    )
    candidate = _require_sha40(candidate_commit, "E_V240_REMOTE_MAIN_LEASE")
    if observed != expected:
        _fail(
            "E_V240_REMOTE_MAIN_LEASE",
            "remote main moved after the lease was frozen",
            expected_main_commit=expected,
            observed_main_commit=observed,
        )
    return _success(
        expected_main_commit=expected,
        observed_main_commit=observed,
        candidate_commit=candidate,
    )


def evaluate_ci_conclusions(
    jobs: Sequence[Mapping[str, Any]],
    head_sha: str,
    required_jobs: Sequence[str],
) -> dict[str, Any]:
    expected_sha = _require_sha40(head_sha, "E_V240_CI_SHA_MISMATCH")
    by_name: dict[str, Mapping[str, Any]] = {}
    for job in jobs:
        name = job.get("name")
        if isinstance(name, str):
            by_name[name] = job
    missing = sorted(set(required_jobs) - set(by_name))
    if missing:
        _fail(
            "E_V240_CI_REQUIRED_MISSING",
            f"required jobs missing: {', '.join(missing)}",
            missing_jobs=missing,
        )
    selected = [by_name[name] for name in required_jobs]
    if any(job.get("head_sha") != expected_sha for job in selected):
        _fail("E_V240_CI_SHA_MISMATCH", "job head SHA is not the frozen commit")
    not_success = {
        str(job.get("name")): job.get("conclusion")
        for job in selected
        if job.get("conclusion") != "success"
    }
    if not_success:
        _fail(
            "E_V240_CI_NOT_SUCCESS",
            "one or more required jobs did not succeed",
            conclusions=not_success,
        )
    return _success(
        head_sha=expected_sha,
        successful_jobs=sorted(set(required_jobs)),
    )


def validate_draft_assets(
    version: str,
    expected: Mapping[str, Mapping[str, Any]],
    observed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    required = {
        f"goal-teams-{version}.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    }
    if set(expected) != required or set(observed) != required:
        _fail(
            "E_V240_DRAFT_ASSET_SET",
            "Draft must contain the exact four release assets",
        )
    for name in sorted(required):
        expected_record = expected[name]
        observed_record = observed[name]
        if (
            expected_record.get("sha256") != observed_record.get("sha256")
            or expected_record.get("size") != observed_record.get("size")
            or SHA256_RE.fullmatch(str(expected_record.get("sha256", ""))) is None
        ):
            _fail(
                "E_V240_DRAFT_ASSET_IDENTITY",
                f"downloaded asset identity drift: {name}",
                asset=name,
            )
    return _success(
        version=version,
        asset_names=sorted(required),
        verification="downloaded_byte_identity",
    )


def validate_install_identity(
    release_receipt: Mapping[str, Any], install_state: Mapping[str, Any]
) -> dict[str, Any]:
    if install_state.get("source_kind") != "github_release_asset":
        _fail("E_V240_INSTALL_SOURCE_KIND", "install did not use a Release asset")
    if install_state.get("source_dirty") is not False:
        _fail("E_V240_INSTALL_DIRTY", "install source is dirty or unproven")
    if install_state.get("source_commit") != release_receipt.get("source_commit"):
        _fail("E_V240_INSTALL_COMMIT", "installed commit drift")
    if install_state.get("release_tag") != release_receipt.get("tag"):
        _fail("E_V240_INSTALL_TAG", "installed tag drift")
    if install_state.get("release_id") != release_receipt.get("release_id"):
        _fail("E_V240_INSTALL_RELEASE", "installed Release ID drift")
    if install_state.get("release_asset_sha256") != release_receipt.get(
        "artifact_sha256"
    ):
        _fail("E_V240_INSTALL_ASSET", "installed asset digest drift")
    return _success(
        source_kind="github_release_asset",
        source_commit=install_state["source_commit"],
        release_tag=install_state["release_tag"],
        release_id=install_state["release_id"],
        asset_sha256=install_state["release_asset_sha256"],
    )


def validate_tar_limits(summary: Mapping[str, Any]) -> dict[str, Any]:
    checks = (
        ("member_count", TAR_LIMITS["member_count"], "E_V240_TAR_LIMIT_MEMBERS"),
        ("max_path_bytes", TAR_LIMITS["max_path_bytes"], "E_V240_TAR_LIMIT_PATH"),
        (
            "max_single_file_bytes",
            TAR_LIMITS["max_single_file_bytes"],
            "E_V240_TAR_LIMIT_SINGLE_FILE",
        ),
        (
            "total_uncompressed_bytes",
            TAR_LIMITS["total_uncompressed_bytes"],
            "E_V240_TAR_LIMIT_TOTAL",
        ),
    )
    for field, limit, error_code in checks:
        value = summary.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            _fail(error_code, f"{field} is not a non-negative integer")
        if value > limit:
            _fail(error_code, f"{field} exceeds fixed limit {limit}")
    compressed = summary.get("compressed_bytes")
    total = summary.get("total_uncompressed_bytes")
    if (
        not isinstance(compressed, int)
        or isinstance(compressed, bool)
        or compressed <= 0
        or not isinstance(total, int)
        or total / compressed > TAR_LIMITS["compression_ratio"]
    ):
        _fail(
            "E_V240_TAR_LIMIT_RATIO",
            "archive compression ratio exceeds the fixed 100:1 limit",
        )
    return _success(limits=dict(TAR_LIMITS), summary=dict(summary))


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _canonical_codex_home() -> Path:
    """Return the OS-account Codex home or fail before production install.

    ``Path.home()`` trusts the mutable HOME environment on Unix.  Release
    completion instead binds the real/effective uid, passwd database home and
    every existing path component.  CODEX_HOME is only a matching assertion;
    it can never redirect the production target.
    """

    if pwd is None or not hasattr(os, "getuid") or not hasattr(os, "geteuid"):
        _fail("E_V240_INSTALL_TARGET", "canonical Codex home requires a Unix account")
    uid = os.getuid()
    if uid != os.geteuid():
        _fail("E_V240_INSTALL_TARGET", "real/effective uid mismatch")
    if "SUDO_UID" in os.environ or "SUDO_USER" in os.environ:
        _fail("E_V240_INSTALL_TARGET", "sudo environment cannot authorize actual install")
    try:
        account = pwd.getpwuid(uid)
    except (KeyError, OSError) as exc:
        _fail("E_V240_INSTALL_TARGET", f"passwd home unavailable: {exc}")
    raw_home = getattr(account, "pw_dir", None)
    if not isinstance(raw_home, str) or not raw_home:
        _fail("E_V240_INSTALL_TARGET", "passwd home is empty")
    home = Path(raw_home)
    if not home.is_absolute() or str(home) != raw_home:
        _fail("E_V240_INSTALL_TARGET", "passwd home is not canonical absolute text")
    if os.environ.get("HOME") != raw_home:
        _fail("E_V240_INSTALL_TARGET", "HOME differs from passwd home")

    cursor = Path(home.anchor)
    for part in home.parts[1:]:
        cursor /= part
        try:
            metadata = cursor.lstat()
        except OSError as exc:
            _fail("E_V240_INSTALL_TARGET", f"passwd home ancestor unavailable: {exc}")
        if stat.S_ISLNK(metadata.st_mode):
            _fail("E_V240_INSTALL_TARGET", "passwd home has a symlink ancestor")
    try:
        home_metadata = home.lstat()
    except OSError as exc:
        _fail("E_V240_INSTALL_TARGET", f"passwd home unavailable: {exc}")
    if not stat.S_ISDIR(home_metadata.st_mode) or home_metadata.st_uid != uid:
        _fail("E_V240_INSTALL_TARGET", "passwd home owner/type mismatch")

    codex_home = home / ".codex"
    configured = os.environ.get("CODEX_HOME")
    if configured is not None and configured != str(codex_home):
        _fail("E_V240_INSTALL_TARGET", "CODEX_HOME differs from canonical passwd target")
    if codex_home.exists() or codex_home.is_symlink():
        metadata = codex_home.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            _fail("E_V240_INSTALL_TARGET", "canonical CODEX_HOME is a symlink")
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != uid:
            _fail("E_V240_INSTALL_TARGET", "canonical CODEX_HOME owner/type mismatch")
    return codex_home


def validate_safe_ancestors(
    target: str | os.PathLike[str], allowed_root: str | os.PathLike[str]
) -> dict[str, Any]:
    """Validate containment and reject every existing symlink ancestor."""

    target_path = Path(target).absolute()
    allowed_path = Path(allowed_root).absolute()
    if not _path_is_within(target_path, allowed_path):
        _fail("E_V240_TARGET_OUTSIDE", "target is outside the allowed root")
    if allowed_path.is_symlink():
        _fail("E_V240_SYMLINK_ANCESTOR", f"symlink root: {allowed_path}")
    relative = target_path.relative_to(allowed_path)
    cursor = allowed_path
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail("E_V240_SYMLINK_ANCESTOR", f"symlink ancestor: {cursor}")
    resolved_allowed = allowed_path.resolve(strict=False)
    resolved_target = target_path.resolve(strict=False)
    if not _path_is_within(resolved_target, resolved_allowed):
        _fail("E_V240_TARGET_OUTSIDE", "resolved target escapes allowed root")
    return _success(
        target=str(target_path),
        allowed_root=str(allowed_path),
        ancestors_safe=True,
    )


def _normalized_tar_name(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name)
    if "\x00" in normalized or "\\" in normalized:
        _fail("E_V240_TAR_UNSAFE_PATH", "NUL or backslash in archive path")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail("E_V240_TAR_UNSAFE_PATH", f"unsafe archive path: {name!r}")
    return path.as_posix()


def safe_extract_release_tar(
    archive_path: str | os.PathLike[str],
    target: str | os.PathLike[str],
    allowed_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Preflight an entire tar archive before writing any target path."""

    archive_file = Path(archive_path)
    target_path = Path(target)
    validate_safe_ancestors(target_path, allowed_root)
    if target_path.exists() and any(target_path.iterdir()):
        _fail("E_V240_TAR_TARGET_NOT_EMPTY", "target directory is not empty")
    try:
        archive = tarfile.open(archive_file, mode="r:*")
    except (OSError, tarfile.TarError) as exc:
        _fail("E_V240_TAR_INVALID", str(exc))
    prepared: list[tuple[tarfile.TarInfo, str]] = []
    seen: set[str] = set()
    total = 0
    max_single = 0
    max_path = 0
    try:
        members = archive.getmembers()
        for member in members:
            if any(
                key in member.pax_headers
                for key in ("path", "linkpath", "GNU.sparse.name")
            ):
                _fail(
                    "E_V240_TAR_PAX_OVERRIDE",
                    f"PAX path override for {member.name!r}",
                )
            if member.issym() or member.islnk():
                _fail("E_V240_TAR_LINK", f"link member: {member.name!r}")
            if not (member.isfile() or member.isdir()):
                _fail("E_V240_TAR_TYPE", f"unsupported member: {member.name!r}")
            normalized = _normalized_tar_name(member.name)
            collision_key = normalized.casefold()
            if collision_key in seen:
                _fail("E_V240_TAR_DUPLICATE", f"duplicate member: {normalized}")
            seen.add(collision_key)
            path_bytes = len(normalized.encode("utf-8"))
            max_path = max(max_path, path_bytes)
            if member.isfile():
                if member.size < 0:
                    _fail("E_V240_TAR_INVALID", "negative file size")
                total += member.size
                max_single = max(max_single, member.size)
            prepared.append((member, normalized))
        summary = {
            "member_count": len(members),
            "max_path_bytes": max_path,
            "max_single_file_bytes": max_single,
            "total_uncompressed_bytes": total,
            "compressed_bytes": max(1, archive_file.stat().st_size),
        }
        validate_tar_limits(summary)
        # Revalidate immediately before the first write.
        validate_safe_ancestors(target_path, allowed_root)
        target_path.mkdir(parents=True, exist_ok=True)
        for member, normalized in prepared:
            destination = target_path.joinpath(*PurePosixPath(normalized).parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                _fail("E_V240_TAR_INVALID", f"cannot read {normalized}")
            with source, destination.open("xb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
    finally:
        archive.close()
    return _success(
        extracted_members=len(prepared),
        target=str(target_path),
        mutation_count=len(prepared),
    )


def validate_remote_promotion_lock(
    expected: Mapping[str, Any], observed: Mapping[str, Any]
) -> dict[str, Any]:
    required = (
        "active",
        "target_ref",
        "candidate_commit",
        "bypass_actor_id",
        "ruleset_sha256",
    )
    if (
        expected.get("active") is not True
        or observed.get("active") is not True
        or any(expected.get(field) != observed.get(field) for field in required)
    ):
        _fail("E_V240_PROMOTION_LOCK", "remote promotion lock drift")
    return _success(
        active=True,
        target_ref=observed["target_ref"],
        candidate_commit=observed["candidate_commit"],
        bypass_actor_id=observed["bypass_actor_id"],
        ruleset_sha256=observed["ruleset_sha256"],
    )


def classify_remote_resource(
    resource_kind: str,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any] | None,
    *,
    prior_intent: bool,
) -> dict[str, Any]:
    if resource_kind not in {"tag", "release"}:
        _fail("E_V240_REMOTE_RESOURCE_CONFLICT", "unsupported remote resource")
    if observed is None:
        return _success(
            resource_kind=resource_kind,
            classification="absent",
            permitted_action="create",
        )
    if dict(observed) == dict(expected) and prior_intent:
        return _success(
            resource_kind=resource_kind,
            classification="exact",
            permitted_action="adopt",
        )
    _fail(
        "E_V240_REMOTE_RESOURCE_CONFLICT",
        f"{resource_kind} exists with a different or unowned identity",
    )


def recover_operation(
    intent: Mapping[str, Any] | None,
    observed: Mapping[str, Any],
    *,
    marker_present: bool,
) -> dict[str, Any]:
    if marker_present:
        return _success(
            recovery_action="already_marked",
            replayed_side_effect=False,
        )
    classification = observed.get("classification")
    if classification == "absent":
        if intent is None:
            _fail(
                "E_V240_PUBLISHED_RECOVERY_INTENT",
                "absent resource has no persisted intent",
            )
        return _success(
            recovery_action="execute_persisted_intent",
            replayed_side_effect=False,
        )
    if classification != "exact" or intent is None:
        _fail(
            "E_V240_PUBLISHED_RECOVERY_INTENT",
            "recovery cannot adopt without an exact prior intent",
        )
    for field in ("release_id", "source_commit", "asset_digests"):
        if field in observed and observed.get(field) != intent.get(field):
            _fail(
                "E_V240_PUBLISHED_RECOVERY_INTENT",
                f"recovery identity mismatch: {field}",
            )
    if observed.get("release_state") == "published" and not intent.get(
        "operation_id"
    ) == "CP17.release_publish":
        _fail(
            "E_V240_PUBLISHED_RECOVERY_INTENT",
            "published Release is not bound to CP17.release_publish",
        )
    return _success(
        recovery_action="adopt_marker",
        replayed_side_effect=False,
        operation_id=intent.get("operation_id"),
    )


def validate_ci_receipt(
    receipt: Mapping[str, Any], approval: Mapping[str, Any]
) -> dict[str, Any]:
    release_actor_id = approval.get("release_actor_id")
    receipt_actor_id = receipt.get("actor_id")
    triggering_actor_id = receipt.get("triggering_actor_id")
    if (
        not isinstance(release_actor_id, int)
        or isinstance(release_actor_id, bool)
        or release_actor_id < 1
        or not isinstance(receipt_actor_id, int)
        or isinstance(receipt_actor_id, bool)
        or receipt_actor_id != release_actor_id
        or not isinstance(triggering_actor_id, int)
        or isinstance(triggering_actor_id, bool)
        or triggering_actor_id != release_actor_id
    ):
        _fail(
            "E_V240_CI_TRUST_BINDING",
            "CI actor/triggering actor differs from approval",
        )
    for field in (
        "head_sha",
        "workflow_path",
        "workflow_blob_sha",
    ):
        if receipt.get(field) != approval.get(field):
            _fail("E_V240_CI_TRUST_BINDING", f"CI binding drift: {field}")
    approved_workflow_id = approval.get("workflow_id")
    if approved_workflow_id is not None and receipt.get("workflow_id") != approved_workflow_id:
        _fail("E_V240_CI_TRUST_BINDING", "CI binding drift: workflow_id")
    for field in ("workflow_id", "run_id", "run_attempt"):
        value = receipt.get(field)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
        ):
            _fail("E_V240_CI_TRUST_BINDING", f"live {field} is invalid")
    jobs = receipt.get("jobs")
    if not isinstance(jobs, Sequence) or isinstance(jobs, (str, bytes)):
        _fail("E_V240_CI_TRUST_BINDING", "CI jobs are missing")
    required = list(approval.get("required_jobs") or [])
    by_name = {
        job.get("name"): job
        for job in jobs
        if isinstance(job, Mapping) and isinstance(job.get("name"), str)
    }
    if set(by_name) != set(required):
        _fail("E_V240_CI_TRUST_BINDING", "CI job set differs from approval")
    for name in required:
        job = by_name[name]
        if (
            job.get("head_sha") != approval.get("head_sha")
            or job.get("conclusion") != "success"
        ):
            _fail("E_V240_CI_TRUST_BINDING", f"untrusted CI job: {name}")
    return _success(
        head_sha=receipt["head_sha"],
        workflow_path=receipt["workflow_path"],
        workflow_blob_sha=receipt["workflow_blob_sha"],
        workflow_id=receipt["workflow_id"],
        run_id=receipt.get("run_id"),
        run_attempt=receipt.get("run_attempt"),
        actor_id=release_actor_id,
        triggering_actor_id=release_actor_id,
        required_jobs=required,
    )


def _validate_ci_state_authority(
    state: Mapping[str, Any],
    approval: Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> int:
    """Bind CI approval and live run actor to the CP03 GitHub authority."""

    authority = state.get("github_authority")
    actor_id = authority.get("actor_id") if isinstance(authority, Mapping) else None
    if (
        not isinstance(actor_id, int)
        or isinstance(actor_id, bool)
        or actor_id < 1
        or approval.get("release_actor_id") != actor_id
        or (
            receipt is not None
            and (
                not isinstance(receipt.get("actor_id"), int)
                or isinstance(receipt.get("actor_id"), bool)
                or receipt.get("actor_id") != actor_id
                or not isinstance(receipt.get("triggering_actor_id"), int)
                or isinstance(receipt.get("triggering_actor_id"), bool)
                or receipt.get("triggering_actor_id") != actor_id
            )
        )
    ):
        _fail(
            "E_V240_CI_TRUST_BINDING",
            "CI release actor differs from promotion-state GitHub authority",
        )
    return actor_id


def _schema_operation_plan(schema: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    plan = schema.get("x-operation-plan")
    if not isinstance(plan, dict):
        _fail("E_V240_STATE_SCHEMA", "schema has no operation plan")
    result: dict[str, list[dict[str, Any]]] = {}
    for checkpoint_id, operations in plan.items():
        if not isinstance(operations, list):
            _fail("E_V240_STATE_SCHEMA", "operation plan is malformed")
        result[checkpoint_id] = [
            {
                "sequence": operation.get("sequence"),
                "operation_id": operation.get("operation_id"),
                "action": operation.get("action"),
            }
            for operation in operations
            if isinstance(operation, Mapping)
        ]
    return result


def validate_promotion_state(
    state: Mapping[str, Any], expected: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Validate Draft-schema invariants plus the executable semantic contract."""

    if not isinstance(state, Mapping):
        _fail("E_V240_STATE_SCHEMA", "promotion state must be an object")
    schema = _load_promotion_schema()
    semantic = schema.get("x-semantic-validator")
    if not isinstance(semantic, Mapping):
        _fail("E_V240_STATE_SCHEMA", "semantic validator contract is missing")
    exact_order = list(semantic.get("exact_checkpoint_order") or [])
    schema_plan = _schema_operation_plan(schema)
    phase_map = dict(semantic.get("checkpoint_phase_after_pass") or {})
    external_actions = set(
        semantic.get("external_actions_require_expected_before") or []
    )
    if exact_order != [f"CP{index:02d}" for index in range(19)]:
        _fail("E_V240_STATE_SCHEMA", "checkpoint order contract drift")
    if list(schema_plan) != exact_order or list(phase_map) != exact_order:
        _fail("E_V240_STATE_SCHEMA", "plan/phase map is not CP00-CP18 exact")

    if expected is not None:
        identity_fields = (
            "repository",
            "version",
            "candidate_commit",
            "transition_map_version",
        )
        if any(state.get(field) != expected.get(field) for field in identity_fields):
            _fail("E_V240_STATE_FORGED", "top-level release identity drift")
        expected_plan = expected.get("operation_plan")
        if expected_plan is not None and expected_plan != schema_plan:
            _fail("E_V240_STATE_SCHEMA", "caller expectation weakens schema plan")
        expected_phase = expected.get("checkpoint_phase_after_pass")
        if expected_phase is not None and dict(expected_phase) != phase_map:
            _fail("E_V240_STATE_SCHEMA", "caller expectation weakens phase map")
    for field in (
        "repository",
        "version",
        "candidate_commit",
        "transition_map_version",
    ):
        if state.get(field) is None:
            _fail("E_V240_STATE_SCHEMA", f"missing {field}")
    candidate = _require_sha40(
        state.get("candidate_commit"), "E_V240_STATE_FORGED"
    )
    checkpoints = state.get("checkpoints")
    if not isinstance(checkpoints, dict) or not checkpoints:
        _fail("E_V240_STATE_CHECKPOINT_GAP", "checkpoint prefix is empty")
    observed_ids = list(checkpoints)
    if observed_ids != exact_order[: len(observed_ids)]:
        _fail(
            "E_V240_STATE_CHECKPOINT_GAP",
            "checkpoints must be an exact CP00-CP18 prefix without gaps",
        )
    first_non_passed: str | None = None
    highest_passed: str | None = None
    seen_non_passed = False
    for checkpoint_id in observed_ids:
        record = checkpoints[checkpoint_id]
        if not isinstance(record, Mapping):
            _fail("E_V240_STATE_FORGED", f"{checkpoint_id} is not an object")
        if (
            record.get("checkpoint_id") != checkpoint_id
            or record.get("candidate_commit") != candidate
        ):
            _fail("E_V240_STATE_FORGED", f"{checkpoint_id} identity drift")
        status = record.get("status")
        if status == "passed":
            if seen_non_passed:
                _fail(
                    "E_V240_STATE_CHECKPOINT_GAP",
                    "a passed checkpoint follows a non-passed checkpoint",
                )
            highest_passed = checkpoint_id
            if (
                SHA256_RE.fullmatch(str(record.get("receipt_sha256", ""))) is None
                or not record.get("completed_at")
            ):
                _fail(
                    "E_V240_STATE_FORGED",
                    f"{checkpoint_id} lacks marker-last evidence",
                )
        else:
            seen_non_passed = True
            if first_non_passed is None:
                first_non_passed = checkpoint_id
        operations = record.get("operations")
        expected_operations = schema_plan[checkpoint_id]
        if not isinstance(operations, list) or len(operations) != len(
            expected_operations
        ):
            _fail(
                "E_V240_STATE_OPERATION_PLAN",
                f"{checkpoint_id} operation count drift",
            )
        for index, (operation, planned) in enumerate(
            zip(operations, expected_operations), start=1
        ):
            if not isinstance(operation, Mapping):
                _fail(
                    "E_V240_STATE_OPERATION_PLAN",
                    f"{checkpoint_id} operation is not an object",
                )
            intent = operation.get("intent")
            observed_plan = {
                "sequence": operation.get("sequence"),
                "operation_id": operation.get("operation_id"),
                "action": intent.get("action") if isinstance(intent, Mapping) else None,
            }
            if (
                observed_plan != planned
                or operation.get("sequence") != index
                or not isinstance(intent, Mapping)
                or intent.get("operation_id") != operation.get("operation_id")
            ):
                _fail(
                    "E_V240_STATE_OPERATION_PLAN",
                    f"{checkpoint_id} exact operation plan drift",
                )
            action = intent.get("action")
            if action in external_actions and not isinstance(
                intent.get("expected_before"), Mapping
            ):
                _fail(
                    "E_V240_STATE_EXPECTED_BEFORE",
                    f"{operation.get('operation_id')} lacks expected_before",
                )
            operation_status = operation.get("status")
            readback_any = operation.get("readback")
            if isinstance(readback_any, Mapping):
                details_any = readback_any.get("details")
                if (
                    not isinstance(details_any, Mapping)
                    or readback_any.get("state_sha256")
                    != _canonical_json_sha256(details_any)
                ):
                    _fail(
                        "E_V240_STATE_RECEIPT_CHAIN",
                        f"{operation.get('operation_id')} readback digest drift",
                    )
                receipt_any = operation.get("receipt_sha256")
                if receipt_any is not None and receipt_any != _canonical_json_sha256(
                    {"intent": intent, "readback": readback_any}
                ):
                    _fail(
                        "E_V240_STATE_RECEIPT_CHAIN",
                        f"{operation.get('operation_id')} operation receipt drift",
                    )
            if status == "passed":
                readback = readback_any
                if (
                    operation_status != "passed"
                    or not isinstance(readback, Mapping)
                    or readback.get("classification") != "exact"
                    or SHA256_RE.fullmatch(
                        str(operation.get("receipt_sha256", ""))
                    )
                    is None
                    or not operation.get("completed_at")
                ):
                    _fail(
                        "E_V240_STATE_FORGED",
                        f"{operation.get('operation_id')} lacks exact evidence",
                    )
            elif operation_status == "passed":
                _fail(
                    "E_V240_STATE_CHECKPOINT_GAP",
                    "passed operation belongs to a non-passed checkpoint",
                )
        if status == "passed":
            expected_checkpoint_receipt = _canonical_json_sha256(
                [operation.get("receipt_sha256") for operation in operations]
            )
            if record.get("receipt_sha256") != expected_checkpoint_receipt:
                _fail(
                    "E_V240_STATE_RECEIPT_CHAIN",
                    f"{checkpoint_id} checkpoint receipt drift",
                )
    computed_current = (
        first_non_passed
        if first_non_passed is not None
        else "CP18"
    )
    if state.get("current_checkpoint") != computed_current:
        _fail(
            "E_V240_STATE_CHECKPOINT_GAP",
            "current checkpoint is not the first non-passed checkpoint",
        )
    if highest_passed is None:
        if computed_current != "CP00" or state.get("phase") != "DRIFTED":
            _fail("E_V240_STATE_PHASE", "unstarted state must be DRIFTED at CP00")
        highest_number = -1
    else:
        if state.get("phase") != phase_map.get(highest_passed):
            _fail("E_V240_STATE_PHASE", "phase does not match highest passed checkpoint")
        highest_number = int(highest_passed[2:])
    if highest_number >= 3:
        authority = state.get("github_authority")
        if not isinstance(authority, Mapping):
            _fail("E_V240_STATE_FORGED", "GitHub authority is missing")
        validate_github_live_authority(authority, authority)
    if highest_number >= 14:
        remote_lock = state.get("remote_lock")
        if (
            not isinstance(remote_lock, Mapping)
            or remote_lock.get("candidate_commit") != candidate
        ):
            _fail("E_V240_STATE_FORGED", "remote promotion lock is missing")
    allowed_top_level = set(schema.get("properties") or {})
    if set(state) - allowed_top_level:
        _fail("E_V240_STATE_FORGED", "state contains uncontracted authority fields")
    return _success(
        schema_version=state.get("schema_version"),
        candidate_commit=candidate,
        current_checkpoint=computed_current,
        phase=state.get("phase"),
        validated_checkpoints=observed_ids,
        semantic_validator=semantic.get("validator_id"),
    )


def validate_github_live_authority(
    observed: Mapping[str, Any], binding: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare a fresh CP14 observation with its exact CP03 authority binding."""

    for field in ("actor_id", "actor_login"):
        if observed.get(field) != binding.get(field):
            _fail("E_V240_GITHUB_ACTOR_BINDING", f"actor drift: {field}")
    for field in (
        "api_host",
        "repository_id",
        "repository_full_name",
        "origin_binding",
        "origin_binding_sha256",
    ):
        if observed.get(field) != binding.get(field):
            _fail(
                "E_V240_GITHUB_REPOSITORY_BINDING",
                f"repository drift: {field}",
            )
    if observed.get("permission") != "admin" or binding.get("permission") != "admin":
        _fail("E_V240_GITHUB_ADMIN_REQUIRED", "admin permission is required")
    observed_actions = observed.get("authorized_external_actions")
    binding_actions = binding.get("authorized_external_actions")
    if (
        not isinstance(observed_actions, list)
        or observed_actions != binding_actions
        or len(set(observed_actions)) != len(observed_actions)
    ):
        _fail(
            "E_V240_GITHUB_ACTION_UNAUTHORIZED",
            "authorized external action set drift",
        )
    immutable = observed.get("immutable_endpoint_capability")
    immutable_binding = binding.get("immutable_endpoint_capability")
    if (
        not isinstance(immutable, Mapping)
        or immutable.get("read") is not True
        or immutable.get("enable") is not True
        or immutable.get("enabled") is not True
        or immutable != immutable_binding
    ):
        _fail(
            "E_V240_GITHUB_IMMUTABLE_CAPABILITY",
            "immutable Release endpoint capability drift",
        )
    ruleset = observed.get("ruleset_capability")
    ruleset_binding = binding.get("ruleset_capability")
    if (
        not isinstance(ruleset, Mapping)
        or ruleset.get("read") is not True
        or ruleset.get("write") is not True
        or ruleset.get("bypass_actor_supported") is not True
        or ruleset != ruleset_binding
    ):
        _fail(
            "E_V240_GITHUB_RULESET_CAPABILITY",
            "ruleset endpoint capability drift",
        )
    if not isinstance(observed.get("observed_at"), str) or not isinstance(
        binding.get("observed_at"), str
    ):
        _fail(
            "E_V240_GITHUB_AUTHORITY_BINDING",
            "both CP03 and CP14 observations require observed_at",
        )
    actor = {
        "actor_id": observed.get("actor_id"),
        "actor_login": observed.get("actor_login"),
    }
    if (
        observed.get("api_host") != "github.com"
        or observed.get("repository_full_name") != "vibe-coding-era/goal-teams"
        or observed.get("repository_id") != FIXED_GITHUB_REPOSITORY_ID
    ):
        _fail("E_V240_GITHUB_REPOSITORY_BINDING", "fixed GitHub repository identity drift")
    origin_binding = observed.get("origin_binding")
    if (
        not isinstance(origin_binding, Mapping)
        or origin_binding.get("api_host") != "github.com"
        or origin_binding.get("repository") != "vibe-coding-era/goal-teams"
        or origin_binding.get("url_rewrite_count") != 0
        or origin_binding.get("origin_binding_sha256")
        != _canonical_json_sha256(
            {key: value for key, value in origin_binding.items() if key != "origin_binding_sha256"}
        )
        or observed.get("origin_binding_sha256") != origin_binding.get("origin_binding_sha256")
    ):
        _fail("E_V240_GITHUB_TRANSPORT_BINDING", "fixed origin transport identity drift")
    repository = {
        "api_host": observed.get("api_host"),
        "repository_id": observed.get("repository_id"),
        "repository_full_name": observed.get("repository_full_name"),
        "origin_binding": copy.deepcopy(origin_binding),
    }
    capabilities = {
        "immutable_endpoint_capability": copy.deepcopy(immutable),
        "ruleset_capability": copy.deepcopy(ruleset),
    }
    digest_fields = {
        "actor_binding_sha256": _canonical_json_sha256(actor),
        "repository_binding_sha256": _canonical_json_sha256(repository),
        "capability_binding_sha256": _canonical_json_sha256(capabilities),
        "authorized_actions_sha256": _canonical_json_sha256(observed_actions),
    }
    if any(
        observed.get(field) != digest
        or binding.get(field) != digest
        for field, digest in digest_fields.items()
    ):
        _fail("E_V240_GITHUB_AUTHORITY_BINDING", "authority digest drift")
    observed_receipt_source = dict(observed)
    observed_receipt_sha = observed_receipt_source.pop("receipt_sha256", None)
    binding_receipt_source = dict(binding)
    binding_receipt_sha = binding_receipt_source.pop("receipt_sha256", None)
    if (
        observed_receipt_sha != _canonical_json_sha256(observed_receipt_source)
        or binding_receipt_sha != _canonical_json_sha256(binding_receipt_source)
    ):
        _fail("E_V240_GITHUB_AUTHORITY_BINDING", "authority receipt digest drift")
    return _success(**copy.deepcopy(dict(observed)))


def redact_private_ignored_log(
    private_record: Mapping[str, Any],
    *,
    expected_input_sha256: str,
    sanitizer_sha256: str,
    redacted_fields: Sequence[str],
) -> dict[str, Any]:
    surface = private_record.get("surface_kind")
    if surface in PUBLIC_RELEASE_SURFACES:
        _fail(
            "E_V240_PUBLIC_REDACTION_FORBIDDEN",
            "public Release surfaces must fail, never redact",
        )
    path = private_record.get("path")
    if (
        surface != "private_log"
        or private_record.get("ignored") is not True
        or not isinstance(path, str)
        or not path.startswith("docs/")
        or "\\" in path
        or ".." in PurePosixPath(path).parts
    ):
        _fail(
            "E_V240_REDACTION_SCOPE",
            "redaction is limited to ignored docs/ private logs",
        )
    actual_input_sha = _canonical_json_sha256(private_record)
    if expected_input_sha256 != actual_input_sha:
        _fail("E_V240_REDACTION_DIGEST", "private input digest drift")
    _require_sha256(sanitizer_sha256, "E_V240_REDACTION_DIGEST")
    fields = private_record.get("fields")
    if not isinstance(fields, Mapping):
        _fail("E_V240_REDACTION_SCOPE", "private log fields are missing")
    normalized_fields = sorted(set(redacted_fields))
    if any(field not in fields for field in normalized_fields):
        _fail("E_V240_REDACTION_SCOPE", "redacted field is not present")
    public_fields = copy.deepcopy(dict(fields))
    for field in normalized_fields:
        public_fields[field] = "[REDACTED]"
    output_sha = _canonical_json_sha256(public_fields)
    return _success(
        scope="ignored_private_logs_only",
        public_release_surface_policy="fail_closed_no_redaction",
        private_input_sha256=actual_input_sha,
        sanitizer_sha256=sanitizer_sha256,
        redacted_fields=normalized_fields,
        public_fields=public_fields,
        public_output_sha256=output_sha,
    )


_SECRET_PATTERNS = (
    re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)cookie\s*:\s*\S+"),
    re.compile(r"(?i)(?:api[_-]?key|token|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9-]{8,}\b"),
    re.compile(r"https?://[^/\s:@]+:[^@\s]+@"),
)
_HOME_PATH_RE = re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home)/[^\s\"']+")


def scan_public_payload(payloads: Mapping[str, Any]) -> dict[str, Any]:
    security = _load_security_module()
    scanned: list[str] = []
    for name, value in payloads.items():
        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8")
            except UnicodeDecodeError:
                _fail("E_V240_PUBLIC_SECRET", f"non-UTF-8 public payload: {name}")
        else:
            text = str(value)
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS) or security.contains_secret(text):
            _fail("E_V240_PUBLIC_SECRET", f"secret-like content in {name}")
        if _HOME_PATH_RE.search(text) or security.HOME_PATH_RE.search(text):
            _fail("E_V240_PUBLIC_ABSOLUTE_PATH", f"absolute home path in {name}")
        if any(
            marker in text.lower()
            for marker in (
                "tool_call",
                "transport_handle",
                "raw_log",
                ".netrc",
                "spawn_agent",
            )
        ):
            _fail("E_V240_PUBLIC_SECRET", f"private provenance in {name}")
        scanned.append(str(name))
    return _success(scanned_files=sorted(scanned))


def scan_private_evidence_payload(payloads: Mapping[str, Any]) -> dict[str, Any]:
    """Scan ignored local evidence for credentials without banning provenance.

    Private Goal Teams evidence legitimately contains fields such as
    ``transport_handle`` and local source paths.  It remains untracked and is
    never a public release surface, but credential material is still rejected
    by the shared V2.36 detector.  Binary evidence is bound by digest and file
    boundaries rather than decoded as public text.
    """

    security = _load_security_module()
    scanned: list[str] = []
    text_files: list[str] = []
    binary_files: list[str] = []
    for name, value in payloads.items():
        data = value if isinstance(value, bytes) else str(value).encode("utf-8")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            binary_files.append(str(name))
        else:
            if security.contains_secret(text):
                _fail("E_V240_PRIVATE_SECRET", f"secret-like content in {name}")
            text_files.append(str(name))
        scanned.append(str(name))
    return _success(
        scanned_files=sorted(scanned),
        text_files=sorted(text_files),
        binary_files=sorted(binary_files),
    )


def validate_release_bundle(
    expected_assets: Mapping[str, Any],
    observed_assets: Mapping[str, Any],
    target: str | os.PathLike[str],
    allowed_root: str | os.PathLike[str],
) -> dict[str, Any]:
    validate_safe_ancestors(target, allowed_root)
    if _canonical_json_bytes(expected_assets) != _canonical_json_bytes(
        observed_assets
    ):
        _fail("E_V240_BUNDLE_TAMPER", "Release bundle asset identity drift")
    return _success(
        asset_names=sorted(expected_assets),
        target=str(Path(target)),
        write_authorized=False,
    )


def validate_remote_immutability(facts: Mapping[str, Any]) -> dict[str, Any]:
    if (
        facts.get("immutable_release_enabled") is not True
        or facts.get("release_state") != "published"
        or facts.get("release_immutable") is not True
    ):
        _fail(
            "E_V240_RELEASE_IMMUTABILITY",
            "published Release is not repository-immutable",
        )
    if (
        facts.get("tag_ruleset_active") is not True
        or facts.get("tag_update_allowed") is not False
        or facts.get("tag_deletion_allowed") is not False
    ):
        _fail("E_V240_TAG_RULESET", "release tag can be updated or deleted")
    return _success(
        release_immutable=True,
        tag_immutable=True,
        release_state="published",
    )


# ---------------------------------------------------------------------------
# Executable V2.40 orchestration layer
# ---------------------------------------------------------------------------


LOCAL_PREPARE_CHECKPOINTS = {"CP09", "CP10"}
_CLOSE_CAPABILITY = object()
STATE_UPDATE_FIELDS: dict[str, set[str]] = {
    "CP03": {"github_authority"},
    "CP13": {"ci_runs"},
    "CP14": {"github_authority", "remote_lock"},
    "CP16": {"remote_identity"},
    "CP17": {"remote_identity", "install_identity", "ci_runs"},
}
LOCAL_OPERATION_IDS = {
    "CP00.scope_freeze",
    "CP01.legacy_recovery",
    "CP02.topology_validate",
    "CP04.development_identity",
    "CP05.contract_validate",
    "CP05.workflow_approve",
    "CP06.static_gates",
    "CP07.quality_gates",
    "CP08.candidate_identity",
    "CP08.rc_commit",
    "CP09.build_primary",
    "CP09.build_reproducibility",
    "CP10.asset_validate",
    "CP10.snapshot_seal",
    "CP11.local_bundle_rehearsal",
    "CP14.promotion_lease",
    "CP16.remote_bundle_rehearsal",
    "CP17.actual_install",
    "CP17.independent_audit",
    "CP18.archive_close",
}


def _workspace_root() -> Path:
    result = _run_git_unchecked(
        ("git", "rev-parse", "--git-common-dir"),
        cwd=RELEASE_ROOT,
        text=True,
    )
    if result.returncode != 0:
        _fail("E_V240_WORKSPACE_ROOT", "cannot resolve Git common directory")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = (RELEASE_ROOT / common).resolve()
    return common.parent.resolve()


def _allowed_state_path(path: Path) -> Path:
    workspace = _workspace_root()
    absolute = path.expanduser().absolute()
    allowed = [workspace / "docs", workspace / "develops"]
    for root in allowed:
        if _path_is_within(absolute, root.absolute()):
            validate_safe_ancestors(absolute, root)
            return absolute
    _fail(
        "E_V240_STATE_PATH",
        "promotion state must be local-only under repository docs/ or develops/",
    )


def _file_digest_or_none(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        _fail("E_V240_STATE_CAS", "state path is not a regular file")
    return _sha256_file(path)


def _load_state_cas(
    state_path: str | os.PathLike[str], expected_sha256: str | None
) -> tuple[Path, dict[str, Any], str]:
    path = _allowed_state_path(Path(state_path))
    actual = _file_digest_or_none(path)
    if actual is None:
        _fail("E_V240_STATE_CAS", "promotion state does not exist")
    if expected_sha256 is not None:
        _require_sha256(expected_sha256, "E_V240_STATE_CAS")
        if actual != expected_sha256:
            _fail(
                "E_V240_STATE_CAS",
                "promotion state changed since the caller read it",
                expected_state_sha256=expected_sha256,
                observed_state_sha256=actual,
            )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("E_V240_STATE_SCHEMA", f"cannot load promotion state: {exc}")
    if not isinstance(value, dict):
        _fail("E_V240_STATE_SCHEMA", "promotion state is not an object")
    validate_promotion_state(value)
    return path, value, actual


def _atomic_state_write(
    path: Path,
    state: Mapping[str, Any],
    *,
    expected_sha256: str | None,
) -> str:
    path = _allowed_state_path(path)
    if fcntl is None:
        _fail("E_V240_STATE_LOCK", "advisory file locking is unavailable")
    payload = (json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    validate_safe_ancestors(lock_path, path.parent)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        _fail("E_V240_STATE_LOCK", f"cannot open state lock: {exc}")
    with os.fdopen(descriptor, "a+b", closefd=True) as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        try:
            # The digest comparison and replace are one advisory critical
            # section.  Two release.py processes using the same public entry
            # cannot both consume the same expected state generation.
            actual = _file_digest_or_none(path)
            if actual != expected_sha256:
                _fail(
                    "E_V240_STATE_CAS",
                    "state compare-and-swap lease failed",
                    expected_state_sha256=expected_sha256,
                    observed_state_sha256=actual,
                )
            temp_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
                ) as stream:
                    temp_name = stream.name
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
                temp_name = None
                directory_flags = os.O_RDONLY
                if hasattr(os, "O_DIRECTORY"):
                    directory_flags |= os.O_DIRECTORY
                directory_fd = os.open(path.parent, directory_flags)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temp_name is not None:
                    try:
                        os.unlink(temp_name)
                    except FileNotFoundError:
                        pass
        finally:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
    return hashlib.sha256(payload).hexdigest()


def _initialize_state_from_input(config: Mapping[str, Any]) -> Path:
    state_path_value = config.get("state_path")
    if not isinstance(state_path_value, str):
        _fail("E_V240_CLI_INPUT", "state_path is required")
    path = _allowed_state_path(Path(state_path_value))
    if path.exists():
        return path
    _fail(
        "E_V240_STATE_CAS",
        "promotion state is absent; create it through release.py start",
    )


def _new_checkpoint_record(
    identity: Mapping[str, Any],
    checkpoint_id: str,
    expected_before_by_operation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    schema = _load_promotion_schema()
    operation_plan = _schema_operation_plan(schema)
    if checkpoint_id not in operation_plan:
        _fail("E_V240_CHECKPOINT_ORDER", f"unknown checkpoint: {checkpoint_id}")
    external = set(
        schema["x-semantic-validator"][
            "external_actions_require_expected_before"
        ]
    )
    before_map = expected_before_by_operation or {}
    if not isinstance(before_map, Mapping):
        _fail("E_V240_STATE_EXPECTED_BEFORE", "next checkpoint expected-before map is invalid")
    created_at = _utc_now()
    operations: list[dict[str, Any]] = []
    for planned in operation_plan[checkpoint_id]:
        operation_id = str(planned["operation_id"])
        action = str(planned["action"])
        expected_before = before_map.get(operation_id)
        if action in external and not isinstance(expected_before, Mapping):
            _fail(
                "E_V240_STATE_EXPECTED_BEFORE",
                f"exact expected-before is required when creating {operation_id}",
            )
        binding: dict[str, Any] = {
            "repository": identity["repository"],
            "version": identity["version"],
            "candidate_commit": identity["candidate_commit"],
            "operation_id": operation_id,
            "action": action,
        }
        if isinstance(expected_before, Mapping):
            binding["expected_before"] = copy.deepcopy(dict(expected_before))
        intent = {
            "intent_id": "INT-V240-"
            + operation_id.replace(".", "-").replace("_", "-").upper(),
            "operation_id": operation_id,
            "action": action,
            "idempotency_key": _canonical_json_sha256(
                {"transition_map": "goal-teams-v2.40-transition-map-v1", **binding}
            ),
            "inputs_sha256": _canonical_json_sha256(binding),
            "created_at": created_at,
        }
        if isinstance(expected_before, Mapping):
            intent["expected_before"] = copy.deepcopy(dict(expected_before))
        operations.append(
            {
                "operation_id": operation_id,
                "sequence": planned["sequence"],
                "status": "pending",
                "intent": intent,
            }
        )
    if set(before_map) - {operation["operation_id"] for operation in operations}:
        _fail("E_V240_STATE_EXPECTED_BEFORE", "expected-before map contains another checkpoint")
    return {
        "checkpoint_id": checkpoint_id,
        "status": "pending",
        "candidate_commit": identity["candidate_commit"],
        "operations": operations,
    }


def _append_next_checkpoint(
    state: dict[str, Any], checkpoint_id: str, config: Mapping[str, Any]
) -> None:
    number = int(checkpoint_id[2:])
    if number >= 18:
        return
    next_id = f"CP{number + 1:02d}"
    checkpoints = state["checkpoints"]
    if next_id in checkpoints:
        return
    expected_before = config.get("next_checkpoint_expected_before")
    checkpoints[next_id] = _new_checkpoint_record(
        state,
        next_id,
        expected_before if isinstance(expected_before, Mapping) else {},
    )


def _validate_scope_receipt(
    scope: Mapping[str, Any],
    *,
    repository: str,
    version: str,
    base: str,
    candidate: str,
) -> dict[str, Any]:
    workspace = _workspace_root()
    candidate_root = (workspace / "develops" / "v2.40").resolve()
    if RELEASE_ROOT.resolve() != candidate_root:
        _fail("E_V240_SCOPE_FREEZE", "scope must be frozen from canonical candidate worktree")
    spec_root = RELEASE_ROOT / "GoalTeamsWork-V2.40" / "versions" / "V2.40" / "spec"
    spec_names = (
        "PRD.md",
        "acceptance.md",
        "architecture-design.md",
        "requirement-card.md",
        "test-plan.md",
        "promotion-state-contract.json",
    )
    spec_rows = []
    for name in spec_names:
        path = spec_root / name
        if not path.is_file() or path.is_symlink():
            _fail("E_V240_SCOPE_FREEZE", f"scope SPEC file missing: {name}")
        spec_rows.append({"path": name, "sha256": _sha256_file(path)})
    spec_sha = _canonical_json_sha256(spec_rows)
    route_path = spec_root / "current-route-receipt.json"
    if not route_path.is_file() or route_path.is_symlink():
        _fail("E_V240_SCOPE_FREEZE", "current route receipt is missing")
    route = json.loads(route_path.read_text(encoding="utf-8"))
    target = route.get("target") if isinstance(route, Mapping) else None
    locked_scope = route.get("locked_scope") if isinstance(route, Mapping) else None
    route_sha = _sha256_file(route_path)
    if (
        route.get("status") != "current"
        or route.get("target_product_version") != version
        or route.get("required_review_class") != "safety"
        or not isinstance(target, Mapping)
        or target.get("repository") != repository
        or target.get("base_main_commit") != base
        or target.get("candidate_branch") != "codex/v2.40"
        or not isinstance(locked_scope, list)
        or not locked_scope
    ):
        _fail("E_V240_SCOPE_FREEZE", "current route does not bind the V2.40 release")
    if (
        scope.get("repository") != repository
        or scope.get("version") != version
        or scope.get("candidate_commit") != candidate
        or scope.get("owner_run_id") != "RUN-V240-LEAD"
        or scope.get("locked_scope") != locked_scope
        or scope.get("route_receipt_sha256") != route_sha
        or scope.get("spec_sha256") != spec_sha
        or not isinstance(scope.get("done_criteria"), list)
        or not scope.get("done_criteria")
    ):
        _fail("E_V240_SCOPE_FREEZE", "scope receipt differs from SPEC/route/owner/locked scope")
    return {
        "scope_sha256": _canonical_json_sha256(scope),
        "spec_sha256": spec_sha,
        "spec_rows": spec_rows,
        "route_receipt_sha256": route_sha,
        "owner_run_id": "RUN-V240-LEAD",
        "locked_scope_sha256": _canonical_json_sha256(locked_scope),
    }


def start_release(config: Mapping[str, Any]) -> dict[str, Any]:
    """Create the state from immutable Git facts and execute CP00."""

    state_path_value = config.get("state_path")
    if not isinstance(state_path_value, str):
        _fail("E_V240_CLI_INPUT", "start requires state_path")
    path = _allowed_state_path(Path(state_path_value))
    if path.exists():
        _fail("E_V240_STATE_CAS", "start refuses to replace an existing state")
    repository = config.get("repository")
    version = config.get("version")
    base = _require_sha40(config.get("base_main_commit"), "E_V240_REMOTE_MAIN_LEASE")
    candidate = _require_sha40(config.get("candidate_commit"), "E_V240_FROZEN_COMMIT")
    candidate_tree = _require_sha40(
        config.get("candidate_tree"), "E_V240_RELEASE_SOURCE_IDENTITY"
    )
    if repository != "vibe-coding-era/goal-teams" or version != "V2.40":
        _fail("E_V240_RELEASE_SOURCE_IDENTITY", "start is scoped to Goal Teams V2.40")
    scope = config.get("scope")
    if not isinstance(scope, Mapping):
        _fail("E_V240_SCOPE_FREEZE", "start requires a scope receipt")
    _validate_scope_receipt(
        scope,
        repository=str(repository),
        version=str(version),
        base=base,
        candidate=candidate,
    )
    now = _utc_now()
    state: dict[str, Any] = {
        "schema_version": "goal-teams-release-promotion-v2.40",
        "repository": repository,
        "version": version,
        "tag": "v2.40",
        "base_main_commit": base,
        "candidate_commit": candidate,
        "candidate_tree": candidate_tree,
        "phase": "DRIFTED",
        "current_checkpoint": "CP00",
        "transition_map_version": "goal-teams-v2.40-transition-map-v1",
        "checkpoints": {},
        "github_authority": None,
        "sanitization_receipts": [],
        "created_at": now,
        "updated_at": now,
    }
    state["checkpoints"]["CP00"] = _new_checkpoint_record(state, "CP00")
    _verify_frozen_git_identity(state)
    validate_promotion_state(state)
    digest = _atomic_state_write(path, state, expected_sha256=None)
    operation = state["checkpoints"]["CP00"]["operations"][0]
    command = {
        "expected_state_sha256": digest,
        "checkpoint_id": "CP00",
        "operation_authorizations": {
            operation["operation_id"]: {
                "intent_sha256": _canonical_json_sha256(operation["intent"]),
                "mode": "execute_local",
                "parameters": {
                    "scope": copy.deepcopy(dict(scope)),
                    "scope_sha256": _canonical_json_sha256(scope),
                },
            }
        },
    }
    receipt = execute_current_checkpoint(path, command, allowed_checkpoints={"CP00"})
    receipt["command"] = "start"
    return receipt


def _snapshot_tree_digest(root: Path) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        _fail("E_V240_PREPARE_BUILD", f"snapshot directory is absent: {root}")
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            _fail("E_V240_PREPARE_BUILD", f"snapshot contains symlink: {path}")
        if not path.is_file():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode not in {0o644, 0o755}:
            _fail("E_V240_PREPARE_BUILD", f"unexpected snapshot mode: {path}")
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "mode": f"100{mode:03o}",
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return {
        "tree_sha256": _canonical_json_sha256(rows),
        "file_count": len(rows),
        "rows_sha256": _canonical_json_sha256(rows),
    }


def _run_fixed(
    argv: Sequence[str],
    *,
    cwd: Path = RELEASE_ROOT,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = _no_replace_git_argv(argv)
    merged = (
        _sanitized_git_environment()
        if command and Path(command[0]).name == "git"
        else os.environ.copy()
    )
    merged["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        if command and Path(command[0]).name == "git" and any(
            key.startswith("GIT_") for key in env
        ):
            _fail("E_V240_GIT_OBJECT_GRAPH", "Git environment override rejected")
        merged.update(env)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(
            "E_V240_ADAPTER_COMMAND",
            f"fixed command failed ({Path(argv[0]).name} rc={result.returncode})",
            stdout=result.stdout[-2000:],
            stderr=result.stderr[-2000:],
        )
    return result


def _git_status_porcelain(path: Path) -> str:
    """Return every non-ignored worktree change, including untracked files."""

    return _run_fixed(
        ("git", "status", "--porcelain=v1", "--untracked-files=all"), cwd=path
    ).stdout


def _require_clean_candidate_checkout(state: Mapping[str, Any]) -> dict[str, Any]:
    """Bind working-tree checkers to the immutable candidate checkout."""

    workspace = _workspace_root()
    candidate_path = (workspace / "develops" / "v2.40").resolve()
    if RELEASE_ROOT.resolve() != candidate_path or not candidate_path.is_dir():
        _fail(
            "E_V240_WORKTREE_LOCATION",
            "candidate check must execute from canonical develops/v2.40",
        )
    head = _run_fixed(("git", "rev-parse", "HEAD"), cwd=candidate_path).stdout.strip()
    branch = _run_fixed(
        ("git", "rev-parse", "--abbrev-ref", "HEAD"), cwd=candidate_path
    ).stdout.strip()
    status = _git_status_porcelain(candidate_path)
    if head != state.get("candidate_commit"):
        _fail("E_V240_RC_IDENTITY", "candidate checkout HEAD drift")
    if branch != "codex/v2.40":
        _fail("E_V240_WORKTREE_BRANCH", "candidate checkout branch drift")
    if status:
        _fail(
            "E_V240_WORKTREE_DIRTY",
            "candidate checkout has tracked or non-ignored untracked changes",
            status_sha256=hashlib.sha256(status.encode()).hexdigest(),
        )
    return {
        "path": str(candidate_path),
        "branch": branch,
        "head": head,
        "clean": True,
        "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _parse_worktree_inventory(workspace: Path) -> list[dict[str, Any]]:
    result = _run_git_unchecked(
        ("git", "worktree", "list", "--porcelain", "-z"),
        cwd=workspace,
    )
    if result.returncode != 0:
        _fail("E_V240_WORKTREE_LOCATION", "cannot collect live worktree inventory")
    records: list[dict[str, Any]] = []
    for raw_record in result.stdout.split(b"\0\0"):
        fields = [field for field in raw_record.split(b"\0") if field]
        if not fields:
            continue
        record: dict[str, Any] = {}
        for field in fields:
            decoded = field.decode("utf-8", errors="strict")
            key, separator, value = decoded.partition(" ")
            record[key] = value if separator else True
        path_value = record.get("worktree")
        if not isinstance(path_value, str):
            _fail("E_V240_WORKTREE_LOCATION", "worktree inventory path is missing")
        branch_ref = record.get("branch")
        branch = (
            branch_ref.removeprefix("refs/heads/")
            if isinstance(branch_ref, str)
            else "DETACHED"
        )
        records.append(
            {
                "path": str(Path(path_value).resolve()),
                "head": record.get("HEAD"),
                "branch": branch,
                "locked": bool(record.get("locked")),
                "prunable": bool(record.get("prunable")),
            }
        )
    return records


def _github_resource(path: str, *, not_found_ok: bool = False) -> Any:
    if os.environ.get("GH_HOST") not in {None, "", "github.com"}:
        _fail("E_V240_GITHUB_HOST_BINDING", "GH_HOST must be empty or exactly github.com")
    result = subprocess.run(
        [
            "gh", "api", "-H", "Accept: application/vnd.github+json", path,
            "--hostname", "github.com",
        ],
        cwd=_workspace_root(),
        env={**os.environ, "GH_HOST": "github.com"},
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        diagnostic = (result.stdout + "\n" + result.stderr).lower()
        if not_found_ok and ("http 404" in diagnostic or "not found" in diagnostic):
            return None
        _fail(
            "E_V240_TOOL_UNAVAILABLE",
            "GitHub live topology readback failed",
            stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        _fail("E_V240_TOOL_UNAVAILABLE", "GitHub live topology readback is not JSON")


_DOCTOR_EXPECTED_SCOPE = {
    "repository": "vibe-coding-era/goal-teams",
    "version": "V2.40",
    "tag": "v2.40",
    "canonical_branch": "main",
    "candidate_location": "develops/v2.40",
    "candidate_branch": "codex/v2.40",
}


def collect_workspace_facts(
    state: Mapping[str, Any], expected_scope: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Collect CP02 topology from Git/filesystem/GitHub, never caller facts."""

    scope = dict(expected_scope or {})
    if set(scope) - set(_DOCTOR_EXPECTED_SCOPE):
        _fail("E_V240_WORKTREE_LOCATION", "workspace expected scope has unknown fields")
    effective_scope = dict(_DOCTOR_EXPECTED_SCOPE)
    effective_scope.update(scope)
    if effective_scope != _DOCTOR_EXPECTED_SCOPE:
        _fail("E_V240_WORKTREE_LOCATION", "workspace expected scope weakens V2.40 topology")
    if any(state.get(key) != _DOCTOR_EXPECTED_SCOPE[key] for key in ("repository", "version", "tag")):
        _fail("E_V240_RELEASE_SOURCE_IDENTITY", "state differs from fixed doctor scope")

    workspace = _workspace_root()
    candidate_path = (workspace / "develops" / "v2.40").resolve()
    candidate_checkout = _require_clean_candidate_checkout(state)
    root_branch = _run_fixed(
        ("git", "rev-parse", "--abbrev-ref", "HEAD"), cwd=workspace
    ).stdout.strip()
    root_head = _run_fixed(("git", "rev-parse", "HEAD"), cwd=workspace).stdout.strip()
    root_status = _git_status_porcelain(workspace)

    raw_worktrees = _parse_worktree_inventory(workspace)
    worktrees: list[dict[str, Any]] = []
    for record in raw_worktrees:
        path = Path(str(record["path"]))
        if path == workspace.resolve():
            role = "stable"
            active = True
        elif path == candidate_path:
            role = "active_candidate"
            active = True
        else:
            if not _path_is_within(path, workspace / "develops"):
                _fail("E_V240_WORKTREE_LOCATION", "worktree exists outside canonical develops/")
            if record.get("branch") in {"main", "codex/v2.40"}:
                _fail("E_V240_WORKTREE_LOCATION", "legacy worktree uses an active release branch")
            role = "archived_non_active"
            active = False
        worktrees.append({**record, "role": role, "active": active})

    stable = [record for record in worktrees if record["role"] == "stable"]
    candidate_records = [
        record for record in worktrees if record["role"] == "active_candidate"
    ]
    if len(stable) != 1 or len(candidate_records) != 1:
        _fail("E_V240_WORKTREE_LOCATION", "canonical root/candidate registration is not unique")

    tracked = _run_fixed(
        ("git", "ls-files", "-z", "--", "docs", "develops"), cwd=workspace
    ).stdout
    tracked_local = sorted(item for item in tracked.split("\0") if item)
    parent_copies = sorted(
        str(path.absolute())
        for path in workspace.parent.iterdir()
        if path.absolute() != workspace.absolute()
        and path.name.lower().startswith("goal-teams")
    )

    tools = {
        "git": shutil.which("git") is not None,
        "gh": shutil.which("gh") is not None,
        "python_3_11": sys.version_info >= (3, 11),
    }
    if not all(tools.values()):
        # Preserve the exact tool facts in the policy failure path below.
        remote_main_commit = None
        remote_tag = None
        release = None
    else:
        adapter = _github_adapter_for_state(
            state, {"execute_external_writes": False}
        )
        remote_main_commit = adapter._remote_ref("refs/heads/main")
        remote_tag = adapter._remote_tag_identity(str(state["tag"]))
        release = _github_resource(
            f"repos/{state['repository']}/releases/tags/{state['tag']}",
            not_found_ok=True,
        )
    ancestry = _run_git_unchecked(
        (
            "git",
            "merge-base",
            "--is-ancestor",
            str(state["base_main_commit"]),
            str(state["candidate_commit"]),
        ),
        cwd=workspace,
    )
    if ancestry.returncode not in {0, 1}:
        _fail("E_V240_CANDIDATE_ANCESTRY", "cannot verify candidate ancestry")
    local_tag = _run_git_unchecked(
        (
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/tags/{state['tag']}",
        ),
        cwd=workspace,
    )
    if local_tag.returncode not in {0, 1}:
        _fail("E_V240_TAG_EXISTS", "cannot inspect local release tag")

    return {
        "canonical_root_role": "stable",
        "canonical_root": str(workspace),
        "canonical_branch": root_branch,
        "canonical_head": root_head,
        "canonical_dirty": bool(root_status),
        "canonical_status_sha256": hashlib.sha256(root_status.encode()).hexdigest(),
        "candidate_location": "develops/v2.40",
        "candidate_path": str(candidate_path),
        "candidate_branch": candidate_checkout["branch"],
        "expected_candidate_branch": "codex/v2.40",
        "dirty": candidate_checkout["clean"] is not True,
        "candidate_commit": candidate_checkout["head"],
        "remote_main_commit": remote_main_commit,
        "candidate_descends_from_remote_main": ancestry.returncode == 0,
        "tracked_local_only_paths": tracked_local,
        "parent_version_copies": parent_copies,
        "tag_exists": local_tag.returncode == 0 or remote_tag is not None,
        "release_exists": release is not None,
        "tools": tools,
        "worktrees": worktrees,
        "collector_sha256": _sha256_file(Path(__file__).resolve()),
    }


def doctor_release(config: Mapping[str, Any]) -> dict[str, Any]:
    if "workspace_facts" in config:
        _fail("E_V240_CLI_INPUT", "doctor rejects caller-supplied workspace facts")
    state_path = config.get("state_path")
    if not isinstance(state_path, str):
        _fail("E_V240_CLI_INPUT", "doctor requires state_path")
    expected = config.get("expected_state_sha256")
    if not isinstance(expected, str):
        _fail("E_V240_STATE_CAS", "doctor requires expected_state_sha256")
    _, state, digest = _load_state_cas(state_path, expected)
    _verify_frozen_git_identity(state)
    expected_scope = config.get("expected_scope")
    if expected_scope is not None and not isinstance(expected_scope, Mapping):
        _fail("E_V240_CLI_INPUT", "expected_scope must be an object")
    facts = collect_workspace_facts(state, expected_scope)
    receipt = validate_workspace_facts(facts)
    if (
        receipt.get("candidate_commit") != state.get("candidate_commit")
        or receipt.get("remote_main_commit") != state.get("base_main_commit")
    ):
        _fail("E_V240_CANDIDATE_ANCESTRY", "live topology differs from frozen state")
    return _success(
        command="doctor",
        state_sha256=digest,
        workspace_facts_sha256=_canonical_json_sha256(facts),
        workspace_doctor=receipt,
        worktrees=facts["worktrees"],
    )


def _verify_frozen_git_identity(state: Mapping[str, Any]) -> dict[str, str]:
    _assert_unmodified_git_object_graph(RELEASE_ROOT)
    candidate = _require_sha40(
        state.get("candidate_commit"), "E_V240_FROZEN_COMMIT"
    )
    kind = _run_fixed(
        ("git", "cat-file", "-t", candidate), cwd=RELEASE_ROOT
    ).stdout.strip()
    require_frozen_commit(candidate, object_type=kind)
    base = _require_sha40(state.get("base_main_commit"), "E_V240_REMOTE_MAIN_LEASE")
    base_kind = _run_fixed(("git", "cat-file", "-t", base), cwd=RELEASE_ROOT).stdout.strip()
    require_frozen_commit(base, object_type=base_kind)
    ancestry = _run_git_unchecked(
        ("git", "merge-base", "--is-ancestor", base, candidate),
        cwd=RELEASE_ROOT,
    )
    if ancestry.returncode != 0:
        _fail("E_V240_CANDIDATE_ANCESTRY", "frozen base is not an ancestor of candidate")
    tree = _run_fixed(
        ("git", "rev-parse", f"{candidate}^{{tree}}"), cwd=RELEASE_ROOT
    ).stdout.strip()
    if tree != state.get("candidate_tree"):
        _fail("E_V240_RELEASE_SOURCE_IDENTITY", "candidate tree binding drift")
    version_bytes = _run_fixed(
        ("git", "show", f"{candidate}:VERSION"), cwd=RELEASE_ROOT
    ).stdout.strip()
    if version_bytes != state.get("version"):
        _fail("E_V240_RELEASE_SOURCE_IDENTITY", "candidate VERSION binding drift")
    return {
        "candidate_commit": candidate,
        "candidate_tree": tree,
        "base_main_commit": base,
    }


def _checker_surface_digest(commit: str) -> dict[str, Any]:
    commit = _require_sha40(commit, "E_V240_CI_TRUST_BINDING")
    result = _run_fixed(
        ("git", "ls-tree", "-r", "-z", commit), cwd=RELEASE_ROOT
    )
    raw = result.stdout
    rows: list[dict[str, str]] = []
    for record in raw.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, kind, object_id = metadata.split(" ", 2)
        if kind != "blob":
            continue
        if (
            path.startswith("scripts/")
            or path.startswith(".github/workflows/")
            or path.startswith("schemas/")
            or path.startswith("references/")
            or path == "AGENTS.md"
        ):
            rows.append({"path": path, "mode": mode, "blob": object_id})
    required = {
        "scripts/check.sh",
        "scripts/release/build-release.py",
        "scripts/release/validate-release.py",
        "scripts/release/release.py",
        "scripts/release/github_adapter.py",
        PUBLIC_SCAN_RELATIVE,
        "scripts/install/install-local.sh",
        "scripts/checks/check-workspace-boundaries.py",
        "scripts/v23/v236_security.py",
        ".github/workflows/release-gate.yml",
        "schemas/release-promotion-state.schema.json",
        "AGENTS.md",
        "references/release-packaging-protocol.md",
        "references/profiles/goal-teams-self-release-v2.40.md",
        PUBLIC_SCAN_BASELINE_RELATIVE,
    }
    observed = {row["path"] for row in rows}
    missing = sorted(required - observed)
    if missing:
        _fail("E_V240_CI_TRUST_BINDING", f"checker surface is incomplete: {missing}")
    return {
        "checker_tree_sha256": _canonical_json_sha256(rows),
        "checker_file_count": len(rows),
        "checker_rows_sha256": _canonical_json_sha256(rows),
    }


def _build_snapshot(
    state: Mapping[str, Any], output_root: Path
) -> dict[str, Any]:
    version = str(state["version"])
    candidate = str(state["candidate_commit"])
    workspace = _workspace_root()
    validate_safe_ancestors(output_root, workspace)
    target = output_root / version
    if target.exists():
        record_path = target / "_release.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _fail("E_V240_PREPARE_BUILD", f"stale build root is not reusable: {exc}")
        validate_frozen_release_record(record, version, candidate)
    else:
        _run_fixed(
            (
                sys.executable,
                str(RELEASE_ROOT / "scripts" / "release" / "build-release.py"),
                "--version",
                version,
                "--commit",
                candidate,
                "--source-ref",
                candidate,
                "--output-root",
                str(output_root),
            )
        )
    digest = _snapshot_tree_digest(target)
    record = json.loads((target / "_release.json").read_text(encoding="utf-8"))
    validate_frozen_release_record(record, version, candidate)
    return {
        **digest,
        "output_root": str(output_root),
        "snapshot_path": str(target),
        "source_commit": candidate,
        "source_git_tree_id": record.get("source_git_tree_id"),
        "artifact_sha256": record.get("artifact", {}).get("sha256"),
    }


def _canonical_snapshot(state: Mapping[str, Any]) -> Path:
    return _workspace_root() / "release" / "versions" / str(state["version"])


def _canonical_release_assets(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    root = _canonical_snapshot(state)
    names = {
        f"goal-teams-{state['version']}.tar.gz": root
        / "_artifacts"
        / f"goal-teams-{state['version']}.tar.gz",
        "SHA256SUMS": root / "_artifacts" / "SHA256SUMS",
        "_release.json": root / "_release.json",
        "_files.sha256": root / "_files.sha256",
    }
    result: dict[str, dict[str, Any]] = {}
    for name, path in sorted(names.items()):
        if not path.is_file() or path.is_symlink():
            _fail("E_V240_DRAFT_ASSET_SET", f"canonical release asset missing: {name}")
        result[name] = {"sha256": _sha256_file(path), "size": path.stat().st_size}
    return result


def _revalidate_canonical_release(state: Mapping[str, Any]) -> dict[str, Any]:
    sealed = _operation_details(state, "CP10", "CP10.snapshot_seal")
    expected_assets = sealed.get("assets")
    expected_set_sha = sealed.get("asset_set_sha256")
    observed_assets = _canonical_release_assets(state)
    if (
        expected_assets != observed_assets
        or expected_set_sha != _canonical_json_sha256(observed_assets)
    ):
        _fail("E_V240_DRAFT_ASSET_IDENTITY", "canonical assets differ from CP10 seal")
    result = _run_fixed(
        (
            sys.executable,
            str(RELEASE_ROOT / "scripts" / "release" / "validate-release.py"),
            "--version",
            str(state["version"]),
        )
    )
    try:
        validation = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        _fail("E_V240_RELEASE_VALIDATION", f"validator returned invalid JSON: {exc}")
    receipt_sha = _canonical_json_sha256(validation)
    if (
        not isinstance(validation, Mapping)
        or validation.get("passed") is not True
        or receipt_sha != sealed.get("validator_receipt_sha256")
    ):
        _fail("E_V240_RELEASE_VALIDATION", "canonical validator receipt differs from CP10")
    public_scan_receipt = _run_public_release_scan(
        state, _canonical_snapshot(state)
    )
    if public_scan_receipt != sealed.get("public_scan_receipt"):
        _fail(
            "E_V240_PUBLIC_SCAN",
            "canonical public scan receipt differs from CP10 seal",
        )
    return {
        "assets": observed_assets,
        "asset_set_sha256": expected_set_sha,
        "validator_receipt_sha256": receipt_sha,
        "public_scan_receipt_sha256": public_scan_receipt[
            "receipt_sha256"
        ],
    }


def _assemble_release_bundle(
    state: Mapping[str, Any], bundle_root: Path
) -> dict[str, Any]:
    validate_safe_ancestors(bundle_root, _workspace_root())
    source = _canonical_snapshot(state)
    names = {
        f"goal-teams-{state['version']}.tar.gz": source
        / "_artifacts"
        / f"goal-teams-{state['version']}.tar.gz",
        "SHA256SUMS": source / "_artifacts" / "SHA256SUMS",
        "_release.json": source / "_release.json",
        "_files.sha256": source / "_files.sha256",
    }
    bundle_root.mkdir(parents=True, exist_ok=True)
    for name, source_path in names.items():
        target = bundle_root / name
        if target.exists():
            if not target.is_file() or target.is_symlink() or _sha256_file(target) != _sha256_file(source_path):
                _fail("E_V240_BUNDLE_TAMPER", f"existing bundle asset conflicts: {name}")
            continue
        if not source_path.is_file() or source_path.is_symlink():
            _fail("E_V240_DRAFT_ASSET_SET", f"release asset missing: {name}")
        shutil.copyfile(source_path, target)
        target.chmod(0o644)
    return {
        "bundle_path": str(bundle_root),
        "assets": {
            name: {"sha256": _sha256_file(bundle_root / name), "size": (bundle_root / name).stat().st_size}
            for name in sorted(names)
        },
    }


def _load_audit_module() -> Any:
    path = RELEASE_ROOT / "scripts" / "release" / "audit-release.py"
    spec = importlib.util.spec_from_file_location("goal_teams_v240_audit", path)
    if spec is None or spec.loader is None:
        _fail("E_V240_AUDIT_LOAD", "cannot load independent auditor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_github_adapter() -> Any:
    path = RELEASE_ROOT / "scripts" / "release" / "github_adapter.py"
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_github_adapter", path
    )
    if spec is None or spec.loader is None:
        _fail("E_V240_ADAPTER_LOAD", "cannot load GitHub adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_security_module() -> Any:
    path = RELEASE_ROOT / "scripts" / "v23" / "v236_security.py"
    spec = importlib.util.spec_from_file_location("goal_teams_v240_security", path)
    if spec is None or spec.loader is None:
        _fail("E_V240_PUBLIC_SECRET", "cannot load shared security scanner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_public_scan_module() -> Any:
    path = RELEASE_ROOT / PUBLIC_SCAN_RELATIVE
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_public_scan", path
    )
    if spec is None or spec.loader is None:
        _fail("E_V240_PUBLIC_SCAN", "cannot load frozen public release scanner")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        _fail("E_V240_PUBLIC_SCAN", f"cannot import public scanner: {type(exc).__name__}")
    return module


def _git_blob_bytes(commit: str, path: str) -> bytes:
    result = _run_git_unchecked(
        ("git", "show", f"{commit}:{path}"),
        cwd=RELEASE_ROOT,
    )
    if result.returncode != 0:
        _fail("E_V240_AUDIT_OBSERVATIONS_REQUIRED", f"cannot read {path} at {commit}")
    return result.stdout


def _public_scan_trust_bindings(state: Mapping[str, Any]) -> dict[str, Any]:
    """Bind scanner, detector and reviewed baseline to frozen Git blobs."""

    candidate = _require_sha40(
        state.get("candidate_commit"), "E_V240_PUBLIC_SCAN"
    )
    paths = (
        PUBLIC_SCAN_RELATIVE,
        PUBLIC_SCAN_DETECTOR_RELATIVE,
        PUBLIC_SCAN_BASELINE_RELATIVE,
    )
    blobs: dict[str, bytes] = {
        relative: _git_blob_bytes(candidate, relative) for relative in paths
    }
    for relative, expected in blobs.items():
        path = RELEASE_ROOT / relative
        if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
            _fail(
                "E_V240_PUBLIC_SCAN",
                f"working checker input differs from frozen blob: {relative}",
            )
    module = _load_public_scan_module()
    try:
        normalized = module.validate_baseline(
            module.load_baseline(blobs[PUBLIC_SCAN_BASELINE_RELATIVE]),
            version=str(state["version"]),
        )
    except Exception as exc:
        _fail(
            "E_V240_PUBLIC_SCAN_BASELINE",
            f"frozen public scan baseline is invalid: {type(exc).__name__}",
        )
    assertions = normalized.get("assertions")
    review = normalized.get("review")
    if not isinstance(assertions, list) or not isinstance(review, Mapping):
        _fail("E_V240_PUBLIC_SCAN_BASELINE", "baseline normalization is incomplete")
    return {
        "candidate_commit": candidate,
        "candidate_tree": state.get("candidate_tree"),
        "base_main_commit": state.get("base_main_commit"),
        "scanner_path": PUBLIC_SCAN_RELATIVE,
        "scanner_blob_sha256": hashlib.sha256(
            blobs[PUBLIC_SCAN_RELATIVE]
        ).hexdigest(),
        "detector_path": PUBLIC_SCAN_DETECTOR_RELATIVE,
        "detector_blob_sha256": hashlib.sha256(
            blobs[PUBLIC_SCAN_DETECTOR_RELATIVE]
        ).hexdigest(),
        "baseline_path": PUBLIC_SCAN_BASELINE_RELATIVE,
        "baseline_blob_sha256": hashlib.sha256(
            blobs[PUBLIC_SCAN_BASELINE_RELATIVE]
        ).hexdigest(),
        "baseline_assertion_count": len(assertions),
        "baseline_assertions_sha256": _canonical_json_sha256(assertions),
        "baseline_review_sha256": _canonical_json_sha256(review),
    }


def _run_public_release_scan(
    state: Mapping[str, Any], snapshot_root: Path
) -> dict[str, Any]:
    """Run the frozen complete public-surface scanner and fail closed."""

    bindings = _public_scan_trust_bindings(state)
    assets = {
        name: path
        for name, path in {
            f"goal-teams-{state['version']}.tar.gz": snapshot_root
            / "_artifacts"
            / f"goal-teams-{state['version']}.tar.gz",
            "SHA256SUMS": snapshot_root / "_artifacts" / "SHA256SUMS",
            "_release.json": snapshot_root / "_release.json",
            "_files.sha256": snapshot_root / "_files.sha256",
        }.items()
    }
    module = _load_public_scan_module()
    baseline_bytes = _git_blob_bytes(
        str(state["candidate_commit"]), PUBLIC_SCAN_BASELINE_RELATIVE
    )
    try:
        receipt = module.scan_surfaces(
            source_root=RELEASE_ROOT,
            base_commit=str(state["base_main_commit"]),
            candidate_commit=str(state["candidate_commit"]),
            candidate_tree=str(state["candidate_tree"]),
            version=str(state["version"]),
            snapshot_root=snapshot_root,
            asset_paths=assets,
            tag_message=CANONICAL_TAG_MESSAGE,
            release_title=CANONICAL_RELEASE_TITLE,
            release_body=CANONICAL_RELEASE_BODY,
            checker_digest=bindings["scanner_blob_sha256"],
            expected_detector_digest=bindings["detector_blob_sha256"],
            baseline_bytes=baseline_bytes,
        )
    except Exception as exc:
        _fail(
            "E_V240_PUBLIC_SCAN",
            f"public release scanner failed: {type(exc).__name__}: {exc}",
        )
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("passed") is not True
        or receipt.get("errors") != []
        or receipt.get("unwaived_findings") != []
        or receipt.get("trust_bindings", {}).get("scanner_blob_sha256")
        != bindings["scanner_blob_sha256"]
        or receipt.get("trust_bindings", {}).get("detector_blob_sha256")
        != bindings["detector_blob_sha256"]
        or receipt.get("trust_bindings", {}).get("baseline_blob_sha256")
        != bindings["baseline_blob_sha256"]
    ):
        _fail(
            "E_V240_PUBLIC_SCAN",
            "public release surfaces contain unapproved or unbound findings",
            public_scan_receipt_sha256=(
                receipt.get("receipt_sha256")
                if isinstance(receipt, Mapping)
                else None
            ),
        )
    return copy.deepcopy(dict(receipt))


def _tar_blob_bytes(archive_path: Path, version: str, relative: str) -> bytes:
    expected = f"goal-teams-{version}/{relative}"
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            matches = [member for member in archive.getmembers() if member.name == expected]
            if len(matches) != 1 or not matches[0].isfile():
                _fail("E_V240_AUDIT_OBSERVATIONS_REQUIRED", f"asset lacks {relative}")
            stream = archive.extractfile(matches[0])
            if stream is None:
                _fail("E_V240_AUDIT_OBSERVATIONS_REQUIRED", f"cannot read asset {relative}")
            return stream.read()
    except tarfile.TarError as exc:
        _fail("E_V240_AUDIT_OBSERVATIONS_REQUIRED", f"invalid published tar: {exc}")


def _validate_installed_package_tree(
    installed_root: Path,
    bundle: Path,
    install_state: Mapping[str, Any],
) -> dict[str, Any]:
    manifest_path = bundle / "_files.sha256"
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _fail("E_V240_INSTALL_IDENTITY", f"published file manifest missing: {exc}")
    expected: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(lines, start=1):
        fields = line.split("\t")
        if len(fields) != 4:
            _fail("E_V240_INSTALL_IDENTITY", f"invalid V2.40 manifest row {line_number}")
        digest, mode, size_raw, relative = fields
        if (
            SHA256_RE.fullmatch(digest) is None
            or mode not in {"100644", "100755"}
            or re.fullmatch(r"0|[1-9][0-9]*", size_raw) is None
            or relative in expected
            or PurePosixPath(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
        ):
            _fail("E_V240_INSTALL_IDENTITY", f"unsafe V2.40 manifest row {line_number}")
        expected[relative] = {"sha256": digest, "mode": mode, "size": int(size_raw)}
    if not installed_root.is_dir() or installed_root.is_symlink():
        _fail("E_V240_INSTALL_IDENTITY", "installed skill tree is not a directory")
    actual_files = {
        path.relative_to(installed_root).as_posix(): path
        for path in installed_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if set(actual_files) != set(expected):
        _fail("E_V240_INSTALL_IDENTITY", "installed file set differs from published manifest")
    builder_rows: list[dict[str, Any]] = []
    for relative, record in sorted(expected.items()):
        path = actual_files[relative]
        if path.is_symlink() or not path.is_file():
            _fail("E_V240_INSTALL_IDENTITY", f"installed path is not a regular file: {relative}")
        mode = f"100{stat.S_IMODE(path.stat().st_mode):03o}"
        if (
            _sha256_file(path) != record["sha256"]
            or path.stat().st_size != record["size"]
            or mode != record["mode"]
        ):
            _fail("E_V240_INSTALL_IDENTITY", f"installed file identity drift: {relative}")
        builder_rows.append({"path": relative, **record})
    tree_input = b"".join(
        f"{row['path']}\0{row['mode']}\0{row['size']}\0{row['sha256']}\n".encode()
        for row in builder_rows
    )
    builder_tree_sha = hashlib.sha256(tree_input).hexdigest()
    record = json.loads((bundle / "_release.json").read_text(encoding="utf-8"))
    if (
        builder_tree_sha != record.get("tree_sha256")
        or install_state.get("source_tree_digest") != builder_tree_sha
        or install_state.get("bundle_tree_sha256") != builder_tree_sha
    ):
        _fail("E_V240_INSTALL_IDENTITY", "installed builder tree digest drift")

    snapshot_records: list[dict[str, Any]] = []
    for child in sorted(installed_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = child.relative_to(installed_root).as_posix()
        if child.is_symlink():
            _fail("E_V240_INSTALL_IDENTITY", f"installed tree contains symlink: {relative}")
        if child.is_file():
            snapshot_records.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": stat.S_IMODE(child.stat().st_mode),
                    "sha256": _sha256_file(child),
                    "size": child.stat().st_size,
                }
            )
        elif child.is_dir():
            snapshot_records.append(
                {
                    "path": relative,
                    "type": "directory",
                    "mode": stat.S_IMODE(child.stat().st_mode),
                }
            )
        else:
            _fail("E_V240_INSTALL_IDENTITY", f"unsupported installed tree node: {relative}")
    installed_digest = _canonical_json_sha256(snapshot_records)
    if install_state.get("skill_tree_digest") != installed_digest:
        _fail("E_V240_INSTALL_IDENTITY", "installed full-tree digest differs from installer state")
    return {
        "builder_tree_sha256": builder_tree_sha,
        "installed_tree_sha256": installed_digest,
        "file_count": len(expected),
    }


def _adopt_exact_actual_install(
    state: Mapping[str, Any],
    bundle: Path,
    download_details: Mapping[str, Any],
    codex_home: Path,
) -> dict[str, Any] | None:
    """Adopt an already exact production install after marker loss."""

    current_path = codex_home / "state" / "goal-teams" / "current.json"
    if not current_path.exists():
        return None
    if not current_path.is_file() or current_path.is_symlink():
        _fail("E_V240_INSTALL_IDENTITY", "canonical installed-state path is unsafe")
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("E_V240_INSTALL_IDENTITY", f"canonical installed state is unreadable: {exc}")
    if not isinstance(current, Mapping):
        _fail("E_V240_INSTALL_IDENTITY", "canonical installed state is malformed")
    # A prior release is a legitimate install-before state.  The installer may
    # upgrade it exactly once.  A current-candidate state must be wholly exact;
    # otherwise replay would hide tampering or a partial prior install.
    if current.get("source_commit") != state.get("candidate_commit"):
        return None
    if (
        current.get("source_kind") != "github_release_asset"
        or current.get("repository") != state.get("repository")
        or current.get("release_tag") != state.get("tag")
        or current.get("release_id") != download_details.get("release_id")
        or current.get("release_state") != "published"
        or current.get("release_assets") != download_details.get("assets")
    ):
        _fail(
            "E_V240_INSTALL_IDENTITY",
            "candidate is installed but canonical identity conflicts with Published assets",
        )
    installed_root = codex_home / "skills" / "goal-teams"
    tree = _validate_installed_package_tree(installed_root, bundle, current)
    tar_name = f"goal-teams-{state['version']}.tar.gz"
    tar_asset = next(
        (
            asset
            for asset in download_details.get("assets", [])
            if isinstance(asset, Mapping) and asset.get("name") == tar_name
        ),
        None,
    )
    if not isinstance(tar_asset, Mapping):
        _fail("E_V240_INSTALL_IDENTITY", "published tar asset identity is missing")
    source = {
        "source_kind": "github_release_asset",
        "repository": state["repository"],
        "release_tag": state["tag"],
        "release_id": download_details["release_id"],
        "release_state": "published",
        "commit": state["candidate_commit"],
        "release_assets": copy.deepcopy(download_details["assets"]),
        "release_asset_sha256": tar_asset.get("sha256"),
    }
    synthetic_report = {
        "schema_version": "goal-teams-install-adoption-v2.40",
        "status": "installed",
        "source": source,
        "adopted_after_marker_loss": True,
        "installed_tree_sha256": tree["installed_tree_sha256"],
    }
    return _exact_readback(
        "installed_tree",
        {
            "install_report": synthetic_report,
            "install_report_sha256": _canonical_json_sha256(synthetic_report),
            "install_state": copy.deepcopy(dict(current)),
            "install_state_sha256": _sha256_file(current_path),
            "codex_home": str(codex_home),
            "canonical_target": True,
            "adopted_after_marker_loss": True,
        },
    )


def collect_live_audit_observation(state: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the five-point audit only from live/read-only surfaces."""

    adapter = _github_adapter_for_state(state, {"execute_external_writes": False})
    main_commit = adapter._remote_ref("refs/heads/main")
    tag_object = adapter._remote_ref(f"refs/tags/{state['tag']}")
    tag_commit = adapter._remote_ref(f"refs/tags/{state['tag']}", peel=True)
    if (
        main_commit != state.get("candidate_commit")
        or tag_commit != state.get("candidate_commit")
        or tag_object is None
        or tag_object == state.get("candidate_commit")
    ):
        _fail("E_V240_FIVE_POINT_IDENTITY", "live main/tag identity drift")
    release_publish_operation = _checkpoint_operation(
        state, "CP17", "CP17.release_publish"
    )
    release_publish_expected = release_publish_operation.get("intent", {}).get(
        "expected_before"
    )
    if not isinstance(release_publish_expected, Mapping):
        _fail("E_V240_STATE_EXPECTED_BEFORE", "publish intent identity is missing")
    release_observation = adapter.observe(
        operation_id="CP17.release_publish",
        action="release_publish",
        expected_before=release_publish_expected,
        parameters={},
    )
    release_live = release_observation.get("details")
    latest_live = adapter._latest_release()
    if (
        release_observation.get("classification") != "exact"
        or not isinstance(release_live, Mapping)
        or release_live.get("databaseId") != state.get("remote_identity", {}).get("release_id")
        or release_live.get("isDraft") is not False
        or release_live.get("isImmutable") is not True
        or release_live.get("tagName") != state.get("tag")
        or not isinstance(latest_live, Mapping)
        or latest_live.get("id") != release_live.get("databaseId")
        or latest_live.get("tag_name") != state.get("tag")
    ):
        _fail("E_V240_LATEST_RELEASE", "live immutable Latest Release drift")

    tag_ruleset_details = _operation_details(state, "CP14", "CP14.tag_ruleset")
    stored_tag_ruleset = tag_ruleset_details.get("ruleset")
    if (
        not isinstance(stored_tag_ruleset, Mapping)
        or not isinstance(stored_tag_ruleset.get("name"), str)
    ):
        _fail("E_V240_TAG_RULESET", "stored tag ruleset binding is missing")
    live_tag_ruleset = adapter._ruleset_by_name(stored_tag_ruleset["name"])
    if not isinstance(live_tag_ruleset, Mapping):
        _fail("E_V240_TAG_RULESET", "live tag ruleset is absent")
    adapter._validate_ruleset_payload("tag_ruleset_create", live_tag_ruleset)
    normalize_ruleset = _load_github_adapter().normalize_ruleset
    normalized_live_tag_ruleset = normalize_ruleset(live_tag_ruleset)
    if normalized_live_tag_ruleset != normalize_ruleset(stored_tag_ruleset):
        _fail("E_V240_TAG_RULESET", "live tag ruleset differs from CP14 binding")
    tag_ruleset_sha256 = _canonical_json_sha256(normalized_live_tag_ruleset)

    published_operation = _checkpoint_operation(
        state, "CP17", "CP17.published_asset_download"
    )
    expected_before = published_operation.get("intent", {}).get("expected_before")
    if not isinstance(expected_before, Mapping):
        _fail("E_V240_STATE_EXPECTED_BEFORE", "published download intent missing")
    download = adapter.observe(
        operation_id="CP17.published_asset_download",
        action="published_asset_download",
        expected_before=expected_before,
        parameters={},
    )
    if download.get("classification") != "exact":
        _fail("E_V240_DRAFT_ASSET_IDENTITY", "published assets are not exact")
    download_details = download.get("details")
    if not isinstance(download_details, Mapping):
        _fail("E_V240_DRAFT_ASSET_IDENTITY", "published download details missing")
    bundle = Path(str(download_details.get("bundle_path", "")))
    record = json.loads((bundle / "_release.json").read_text(encoding="utf-8"))
    asset_commit = record.get("source_commit")
    if asset_commit != state.get("candidate_commit"):
        _fail("E_V240_FIVE_POINT_IDENTITY", "published asset source commit drift")

    install_details = _operation_details(state, "CP17", "CP17.actual_install")
    codex_home_value = install_details.get("codex_home")
    if not isinstance(codex_home_value, str):
        _fail("E_V240_INSTALL_IDENTITY", "actual install target receipt missing")
    codex_home = Path(codex_home_value).expanduser().absolute()
    if codex_home != _canonical_codex_home() or install_details.get("canonical_target") is not True:
        _fail("E_V240_INSTALL_TARGET", "audit target is not canonical ~/.codex")
    install_state_path = codex_home / "state" / "goal-teams" / "current.json"
    if not install_state_path.is_file() or install_state_path.is_symlink():
        _fail("E_V240_INSTALL_IDENTITY", "live installed state missing")
    install_state = json.loads(install_state_path.read_text(encoding="utf-8"))
    if (
        install_state.get("source_kind") != "github_release_asset"
        or install_state.get("source_commit") != state.get("candidate_commit")
        or install_state.get("release_id") != release_live.get("databaseId")
        or install_state.get("release_assets") != download_details.get("assets")
    ):
        _fail("E_V240_INSTALL_IDENTITY", "live installed state differs from Release download")
    installed_root = codex_home / "skills" / "goal-teams"
    _validate_installed_package_tree(installed_root, bundle, install_state)

    candidate_ci: dict[str, Any] | None = None
    post_ci: dict[str, Any] | None = None
    ci_provenance: dict[str, dict[str, Any]] = {}
    for checkpoint_id, operation_id, stage in (
        ("CP13", "CP13.candidate_ci", "candidate"),
        ("CP17", "CP17.post_release_ci", "post_release"),
    ):
        operation = _checkpoint_operation(state, checkpoint_id, operation_id)
        intent = operation.get("intent")
        expected = intent.get("expected_before") if isinstance(intent, Mapping) else None
        approval = expected.get("ci_approval") if isinstance(expected, Mapping) else None
        stored_run = _operation_details(state, checkpoint_id, operation_id).get("ci_run")
        if not isinstance(approval, Mapping) or not isinstance(stored_run, Mapping):
            _fail("E_V240_CI_TRUST_BINDING", f"{stage} CI binding missing")
        release_actor_id = _validate_ci_state_authority(
            state, approval, stored_run
        )
        live_ci = adapter.observe(
            operation_id=operation_id,
            action="ci_wait" if stage == "candidate" else "post_release_ci",
            expected_before=expected,
            parameters={
                "run_id": stored_run.get("run_id"),
                **(
                    {"_release_intent": intent.get("idempotency_key")}
                    if stage == "post_release"
                    else {}
                ),
            },
        )
        ci_receipt = live_ci.get("details", {}).get("ci_receipt")
        if not isinstance(ci_receipt, Mapping):
            _fail("E_V240_CI_TRUST_BINDING", f"{stage} live CI receipt missing")
        validate_ci_receipt(ci_receipt, approval)
        _validate_ci_state_authority(state, approval, ci_receipt)
        expected_event = "push" if stage == "candidate" else "workflow_dispatch"
        expected_release_intent = (
            intent.get("idempotency_key") if stage == "post_release" else None
        )
        if (
            ci_receipt.get("event") != expected_event
            or not isinstance(ci_receipt.get("actor_id"), int)
            or ci_receipt.get("actor_id", 0) < 1
            or not isinstance(ci_receipt.get("triggering_actor_id"), int)
            or ci_receipt.get("triggering_actor_id", 0) < 1
            or not isinstance(ci_receipt.get("run_id"), int)
            or ci_receipt.get("run_id") != stored_run.get("run_id")
            or not isinstance(ci_receipt.get("run_attempt"), int)
            or ci_receipt.get("run_attempt") != stored_run.get("run_attempt")
            or ci_receipt.get("workflow_id") != stored_run.get("workflow_id")
            or not isinstance(ci_receipt.get("created_at"), str)
            or (
                stage == "post_release"
                and (
                    ci_receipt.get("release_intent") != expected_release_intent
                    or ci_receipt.get("display_title")
                    != f"Goal Teams V2.40 release {expected_release_intent}"
                )
            )
        ):
            _fail(
                "E_V240_CI_TRUST_BINDING",
                f"{stage} live event/actor/run provenance drift",
            )
        if stage == "post_release":
            published_at = _operation_details(
                state, "CP17", "CP17.release_publish"
            ).get("publishedAt")
            intent_created = operation.get("intent", {}).get("created_at")
            run_created = _parse_utc(
                ci_receipt.get("created_at"), "E_V240_POST_RELEASE_CI"
            )
            if (
                run_created <= _parse_utc(published_at, "E_V240_POST_RELEASE_CI")
                or run_created
                <= _parse_utc(intent_created, "E_V240_POST_RELEASE_CI")
            ):
                _fail("E_V240_POST_RELEASE_CI", "live post-release CI predates publish/intent")
        stage_receipt = {
            "event": ci_receipt["event"],
            "actor_id": ci_receipt["actor_id"],
            "triggering_actor_id": ci_receipt["triggering_actor_id"],
            "workflow_id": ci_receipt["workflow_id"],
            "run_id": ci_receipt["run_id"],
            "run_attempt": ci_receipt["run_attempt"],
            "created_at": ci_receipt["created_at"],
            "head_sha": ci_receipt["head_sha"],
            "workflow_path": ci_receipt["workflow_path"],
            "workflow_blob_sha": ci_receipt["workflow_blob_sha"],
            "jobs": [
                {
                    "name": job["name"],
                    "head_sha": job["head_sha"],
                    "conclusion": job["conclusion"],
                }
                for job in ci_receipt["jobs"]
            ],
        }
        ci_provenance[stage] = copy.deepcopy(stage_receipt)
        if stage == "candidate":
            candidate_ci = stage_receipt
        else:
            post_ci = stage_receipt

    published_at = _operation_details(
        state, "CP17", "CP17.release_publish"
    ).get("publishedAt")
    if (
        not isinstance(candidate_ci, Mapping)
        or not isinstance(post_ci, Mapping)
        or candidate_ci.get("run_id") == post_ci.get("run_id")
        or candidate_ci.get("workflow_blob_sha") != post_ci.get("workflow_blob_sha")
        or _parse_utc(candidate_ci.get("created_at"), "E_V240_CANDIDATE_CI")
        >= _parse_utc(published_at, "E_V240_POST_RELEASE_CI")
    ):
        _fail("E_V240_CI_TRUST_BINDING", "candidate/post-release CI provenance chain drift")

    readme_sha256: dict[str, dict[str, str]] = {}
    tar_path = bundle / f"goal-teams-{state['version']}.tar.gz"
    for name in ("README.en.md", "README.md"):
        main_bytes = _git_blob_bytes(str(main_commit), name)
        tag_bytes = _git_blob_bytes(str(tag_commit), name)
        release_bytes = _git_blob_bytes(str(tag_commit), name)
        asset_bytes = _tar_blob_bytes(tar_path, str(state["version"]), name)
        installed_path = installed_root / name
        if not installed_path.is_file() or installed_path.is_symlink():
            _fail("E_V240_README_BYTE_IDENTITY", f"installed {name} missing")
        readme_sha256[name] = {
            "main": hashlib.sha256(main_bytes).hexdigest(),
            "tag": hashlib.sha256(tag_bytes).hexdigest(),
            "release": hashlib.sha256(release_bytes).hexdigest(),
            "asset": hashlib.sha256(asset_bytes).hexdigest(),
            "installed": _sha256_file(installed_path),
        }
    return {
        "version": state["version"],
        "tag": state["tag"],
        "commits": {
            "main": main_commit,
            "tag": tag_commit,
            "release": tag_commit,
            "asset": asset_commit,
            "installed": install_state.get("source_commit"),
        },
        "readme_sha256": readme_sha256,
        "latest_release_tag": latest_live.get("tag_name"),
        "release_published_at": published_at,
        "release_actor_id": release_actor_id,
        "ci": {"candidate": candidate_ci, "post_release": post_ci},
        "ci_provenance": ci_provenance,
        "remote_protections": {
            "tag_ruleset_sha256": tag_ruleset_sha256,
            "tag_ruleset_name": stored_tag_ruleset["name"],
        },
    }


def _run_independent_audit(observation: Mapping[str, Any]) -> dict[str, Any]:
    try:
        base = _load_audit_module().audit_release_identity(observation)
    except Exception as exc:
        attached = getattr(exc, "receipt", None)
        if isinstance(attached, Mapping):
            _fail(str(attached.get("error_code", "E_V240_AUDIT")), str(exc))
        raise
    if not isinstance(base, Mapping) or base.get("passed") is not True:
        _fail("E_V240_AUDIT", "independent auditor did not return a passed receipt")
    receipt = copy.deepcopy(dict(base))
    receipt["ci_provenance"] = copy.deepcopy(observation.get("ci_provenance"))
    receipt["remote_protections"] = copy.deepcopy(
        observation.get("remote_protections")
    )
    receipt["observation_sha256"] = _canonical_json_sha256(observation)
    receipt["receipt_sha256"] = _canonical_json_sha256(receipt)
    return receipt


def _git_worktree_facts(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return {"exists": False}
    branch = _run_fixed(
        ("git", "rev-parse", "--abbrev-ref", "HEAD"), cwd=path
    ).stdout.strip()
    head = _run_fixed(("git", "rev-parse", "HEAD"), cwd=path).stdout.strip()
    status = _git_status_porcelain(path)
    return {
        "exists": True,
        "path": str(path.resolve()),
        "branch": branch,
        "head": head,
        "clean": status == "",
        "tracked_clean": status == "",
        "status_includes_untracked": True,
        "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
        "tracked_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _receipt_passed(value: Mapping[str, Any]) -> bool:
    statuses = {
        str(value.get(key, "")).lower()
        for key in (
            "status",
            "state",
            "check_state",
            "review_state",
            "audit_state",
            "verdict",
            "decision",
            "result",
        )
    }
    return value.get("passed") is True or bool(
        statuses & {"passed", "accepted", "approved", "complete", "completed"}
    )


def _directory_tree_receipt(root: Path) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        _fail("E_V240_CLOSE_SSOT", f"SSOT tree is absent: {root.name}")
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            _fail("E_V240_CLOSE_SSOT", f"SSOT tree contains symlink: {relative}")
        if path.is_file():
            rows.append(
                {
                    "path": relative,
                    "mode": stat.S_IMODE(path.stat().st_mode),
                    "size": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return {
        "tree_sha256": _canonical_json_sha256(rows),
        "file_count": len(rows),
        "rows_sha256": _canonical_json_sha256(rows),
    }


def _run_ssot_validator(argv: Sequence[str], workspace: Path) -> dict[str, Any]:
    result = subprocess.run(
        list(argv),
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        _fail(
            "E_V240_CLOSE_SSOT",
            f"formal SSOT validator failed: {Path(argv[0]).name}",
            stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
            stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
        )
    return {
        "argv_sha256": _canonical_json_sha256(list(argv)),
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "exit_code": result.returncode,
        "stdout": result.stdout,
    }


def _run_ssot_completion_host_boundary(
    argv: Sequence[str], workspace: Path
) -> dict[str, Any]:
    """Prove that the candidate-side V2.36 Completion gate stays fail closed.

    Goal Teams self-release is deliberately not allowed to turn its own
    ``completion-audit`` command into an authoritative acceptance result.  The
    V2.40 release host therefore validates the exact host-adapter rejection,
    after independently recomputing the archived ledger, TaskList, Evidence,
    Harness, Review, Audit and release receipts at the outer boundary.
    """

    result = subprocess.run(
        list(argv),
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError:
        _fail(
            "E_V240_CLOSE_SSOT",
            "formal Completion host boundary output is not JSON",
            stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
            stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
        )
    expected_errors = ["E_V236_HOST_ADAPTER_REQUIRED"]
    if (
        result.returncode != 1
        or result.stderr
        or not isinstance(envelope, Mapping)
        or envelope.get("ok") is not False
        or envelope.get("error_code") != "E_COMPLETION_AUDIT"
        or envelope.get("errors") != expected_errors
    ):
        _fail(
            "E_V240_CLOSE_SSOT",
            "candidate-side Completion did not enforce the host-adapter boundary",
            stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
            stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
        )
    return {
        "argv_sha256": _canonical_json_sha256(list(argv)),
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "exit_code": result.returncode,
        "expected_error_code": "E_V236_HOST_ADAPTER_REQUIRED",
        "host_boundary_enforced": True,
    }


def _requires_v236_completion_host_boundary(workspace: Path) -> bool:
    """Match the V2.36 trusted self-release identity without caller claims."""

    try:
        ancestor = _run_git_unchecked(
            (
                "git",
                "-C",
                str(workspace),
                "merge-base",
                "--is-ancestor",
                V236_GOAL_TEAMS_TRUSTED_RELEASE_BASE,
                "HEAD",
            ),
            cwd=workspace,
            capture_output=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        skill = _run_git_unchecked(
            (
                "git",
                "-C",
                str(workspace),
                "show",
                f"{V236_GOAL_TEAMS_TRUSTED_RELEASE_BASE}:SKILL.md",
            ),
            cwd=workspace,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(
        ancestor.returncode == 0
        and skill.returncode == 0
        and re.search(r"(?m)^name:\s*goal-teams\s*$", skill.stdout) is not None
    )


def _validate_archived_goal_teams_ssot(
    archive_root: Path, state: Mapping[str, Any]
) -> dict[str, Any]:
    ssot = archive_root / "GoalTeamsWork-V2.40" / "versions" / "V2.40"
    required = {
        "TaskList.md": ssot / "TaskList.md",
        "ledger_checkpoint": ssot / "ledger" / "checkpoint.json",
        "ledger_events": ssot / "ledger" / "events.jsonl",
        "harness": ssot / "harness" / "harness.json",
        "traceability": ssot / "harness" / "traceability.json",
        "evidence": ssot / "evidence" / "evidence.jsonl",
        "dual_review": ssot / "reviews" / "dual-review.json",
        "identity_registry": ssot / "identity" / "registry.json",
        "completion_audit": ssot / "audit" / "completion-audit.json",
    }
    if any(not path.is_file() or path.is_symlink() for path in required.values()):
        _fail(
            "E_V240_CLOSE_SSOT",
            "archived Goal Teams SSOT/Completion Audit is incomplete",
        )
    checkpoint = json.loads(required["ledger_checkpoint"].read_text(encoding="utf-8"))
    tasks = checkpoint.get("tasks") if isinstance(checkpoint, Mapping) else None
    if not isinstance(tasks, Mapping) or not tasks or checkpoint.get("conflicts") not in ([], None):
        _fail("E_V240_CLOSE_SSOT", "archived ledger task projection is invalid")
    required_tasks = {
        task_id: task
        for task_id, task in tasks.items()
        if isinstance(task, Mapping) and task.get("required_for_done") is True
    }
    if not required_tasks or any(
        task.get("task_state") != "accepted"
        or task.get("check_state") != "passed"
        or not task.get("evidence_refs")
        for task in required_tasks.values()
    ):
        _fail(
            "E_V240_CLOSE_SSOT",
            "a required Goal Teams task/check/evidence is not accepted",
        )
    evidence_records: dict[str, Mapping[str, Any]] = {}
    evidence_record_digests: dict[str, str] = {}
    for line_number, line in enumerate(
        required["evidence"].read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            _fail("E_V240_CLOSE_SSOT", f"invalid evidence JSONL line: {line_number}")
        evidence_id = record.get("evidence_id") if isinstance(record, Mapping) else None
        if (
            not isinstance(evidence_id, str)
            or not evidence_id
            or evidence_id in evidence_records
        ):
            _fail("E_V240_CLOSE_SSOT", "evidence registry id is missing or duplicated")
        evidence_records[evidence_id] = record
        evidence_record_digests[evidence_id] = _canonical_json_sha256(record)
    if not evidence_records:
        _fail("E_V240_CLOSE_SSOT", "archived evidence registry is empty")

    referenced_artifacts: list[dict[str, Any]] = []
    work_root = archive_root / "GoalTeamsWork-V2.40"
    workspace = _workspace_root()

    def resolve_ref(ref: str, task_id: str, field: str) -> Path:
        if (
            not ref
            or PurePosixPath(ref).is_absolute()
            or "\\" in ref
            or ".." in PurePosixPath(ref).parts
        ):
            _fail("E_V240_CLOSE_SSOT", f"unsafe {field} in {task_id}")
        candidates = [work_root / ref, workspace / ref]
        target = next((path for path in candidates if path.exists()), None)
        if target is None or target.is_symlink():
            _fail("E_V240_CLOSE_SSOT", f"missing {field} in {task_id}: {ref}")
        return target

    for task_id, task in sorted(required_tasks.items()):
        task_artifact_refs = task.get("artifact_refs")
        if not isinstance(task_artifact_refs, list) or not task_artifact_refs:
            _fail("E_V240_CLOSE_SSOT", f"{task_id} has no artifact_refs")
        for field in ("artifact_refs", "harness_refs"):
            refs = task.get(field)
            if not isinstance(refs, list) or not refs:
                _fail("E_V240_CLOSE_SSOT", f"{task_id} has no {field}")
            for ref in refs:
                if not isinstance(ref, str):
                    _fail("E_V240_CLOSE_SSOT", f"unsafe {field} in {task_id}")
                target = resolve_ref(ref, task_id, field)
                identity = (
                    {"sha256": _sha256_file(target), "size": target.stat().st_size}
                    if target.is_file()
                    else _directory_tree_receipt(target)
                )
                referenced_artifacts.append(
                    {"task_id": task_id, "field": field, "ref": ref, **identity}
                )
        evidence_refs = task.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            _fail("E_V240_CLOSE_SSOT", f"{task_id} has no evidence_refs")
        for evidence_id in evidence_refs:
            if not isinstance(evidence_id, str) or not evidence_id:
                _fail("E_V240_CLOSE_SSOT", f"unsafe evidence_refs in {task_id}")
            record = evidence_records.get(evidence_id)
            if not isinstance(record, Mapping):
                _fail(
                    "E_V240_CLOSE_SSOT",
                    f"missing evidence registry id in {task_id}: {evidence_id}",
                )
            artifact_ref = record.get("artifact_ref")
            artifact_sha = record.get("artifact_sha256")
            artifact_size = record.get("artifact_size")
            if (
                record.get("trust_level") != "local_verified"
                or record.get("current") is False
                or not isinstance(artifact_ref, str)
                or artifact_ref not in task_artifact_refs
                or not isinstance(artifact_sha, str)
                or SHA256_RE.fullmatch(artifact_sha) is None
                or not isinstance(artifact_size, int)
                or isinstance(artifact_size, bool)
                or artifact_size < 0
            ):
                _fail(
                    "E_V240_CLOSE_SSOT",
                    f"evidence registry binding is not current/local for {task_id}: {evidence_id}",
                )
            target = resolve_ref(artifact_ref, task_id, "evidence artifact_ref")
            if (
                not target.is_file()
                or _sha256_file(target) != artifact_sha
                or target.stat().st_size != artifact_size
            ):
                _fail(
                    "E_V240_CLOSE_SSOT",
                    f"evidence artifact bytes drift in {task_id}: {evidence_id}",
                )
            referenced_artifacts.append(
                {
                    "task_id": task_id,
                    "field": "evidence_refs",
                    "ref": evidence_id,
                    "artifact_ref": artifact_ref,
                    "artifact_sha256": artifact_sha,
                    "artifact_size": artifact_size,
                    "evidence_record_sha256": evidence_record_digests[evidence_id],
                }
            )
    events = [
        line
        for line in required["ledger_events"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(events) != len(checkpoint.get("seen_events", [])):
        _fail("E_V240_CLOSE_SSOT", "archived ledger/event projection count drift")
    for line in events:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            _fail("E_V240_CLOSE_SSOT", "archived ledger event is invalid JSON")
        if not isinstance(event, Mapping) or event.get("event_id") not in checkpoint.get(
            "seen_events", []
        ):
            _fail("E_V240_CLOSE_SSOT", "archived ledger event is not checkpoint-bound")

    harness = json.loads(required["harness"].read_text(encoding="utf-8"))
    contract = harness.get("harness_contract") if isinstance(harness, Mapping) else None
    checks = contract.get("checks") if isinstance(contract, Mapping) else None
    runs = harness.get("runs") if isinstance(harness, Mapping) else None
    if not isinstance(checks, list) or not checks or not isinstance(runs, list) or not runs:
        _fail("E_V240_CLOSE_SSOT", "archived Harness checks/runs are missing")
    harness_bindings: list[dict[str, Any]] = []
    for task_id, task in sorted(required_tasks.items()):
        check_id = task.get("validation_check_id")
        run_id = task.get("validation_run_id")
        evidence_refs = task.get("evidence_refs")
        matching_checks = [
            check
            for check in checks
            if isinstance(check, Mapping) and check.get("check_id") == check_id
        ]
        matching_runs = [
            run
            for run in runs
            if isinstance(run, Mapping)
            and run.get("run_id") == run_id
            and run.get("check_id") == check_id
        ]
        check_evidence_refs = (
            matching_checks[0].get("evidence_refs")
            if len(matching_checks) == 1
            else None
        )
        run_evidence_refs = (
            matching_runs[0].get("evidence_refs") if len(matching_runs) == 1 else None
        )
        if (
            not isinstance(check_id, str)
            or not check_id
            or not isinstance(run_id, str)
            or not run_id
            or len(matching_checks) != 1
            or len(matching_runs) != 1
            or not _receipt_passed(matching_checks[0])
            or not _receipt_passed(matching_runs[0])
            or not isinstance(evidence_refs, list)
            or not isinstance(check_evidence_refs, list)
            or not isinstance(run_evidence_refs, list)
            or not set(evidence_refs).issubset(set(check_evidence_refs))
            or not set(evidence_refs).issubset(set(run_evidence_refs))
        ):
            _fail(
                "E_V240_CLOSE_SSOT",
                f"required task Harness binding is not passed/current: {task_id}",
            )
        harness_bindings.append(
            {
                "task_id": task_id,
                "check_id": check_id,
                "run_id": run_id,
                "evidence_refs": sorted(evidence_refs),
            }
        )

    review_dir = ssot / "reviews"
    review_receipts: list[Mapping[str, Any]] = []
    if review_dir.is_dir():
        for path in sorted(review_dir.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                _fail("E_V240_CLOSE_SSOT", f"review receipt is invalid: {path.name}")
            if isinstance(value, Mapping):
                review_receipts.append(value)
    roles = {
        str(receipt.get("role") or receipt.get("review_class") or "").lower()
        for receipt in review_receipts
        if _receipt_passed(receipt)
        and receipt.get("source_commit") == state.get("candidate_commit")
        and receipt.get("version") == state.get("version")
        and receipt.get("independent") is True
    }
    if not any("review" in role for role in roles) or not any("qa" in role for role in roles):
        _fail("E_V240_CLOSE_SSOT", "current independent review/QA receipts are missing")

    completion = json.loads(required["completion_audit"].read_text(encoding="utf-8"))
    if (
        not isinstance(completion, Mapping)
        or not _receipt_passed(completion)
        or completion.get("source_commit") != state.get("candidate_commit")
        or completion.get("version") != state.get("version")
        or completion.get("independent") is not True
    ):
        _fail("E_V240_CLOSE_SSOT", "Completion Audit is not current/independent/passed")

    reducer = workspace / "scripts" / "v23" / "goalteams_v23.py"
    ledger_owner = checkpoint.get("ledger_owner_run_id")
    reduce_result = _run_ssot_validator(
        (
            sys.executable,
            str(reducer),
            "reduce-ledger",
            str(required["ledger_events"]),
            "--ledger-owner-run-id",
            str(ledger_owner),
            "--evidence-jsonl",
            str(required["evidence"]),
            "--evidence-root",
            str(work_root),
            "--source-root",
            str(workspace),
        ),
        workspace,
    )
    try:
        reduced_envelope = json.loads(reduce_result.pop("stdout"))
    except json.JSONDecodeError:
        _fail("E_V240_CLOSE_SSOT", "formal ledger reducer output is not JSON")
    if (
        not isinstance(reduced_envelope, Mapping)
        or reduced_envelope.get("ok") is not True
        or reduced_envelope.get("state") != checkpoint
    ):
        _fail("E_V240_CLOSE_SSOT", "formal ledger replay differs from checkpoint")
    render_result = _run_ssot_validator(
        (
            sys.executable,
            str(reducer),
            "render-tasklist",
            str(required["ledger_checkpoint"]),
            "--evidence-jsonl",
            str(required["evidence"]),
            "--evidence-root",
            str(work_root),
            "--source-root",
            str(workspace),
            "--ledger",
            str(required["ledger_events"]),
        ),
        workspace,
    )
    try:
        rendered_envelope = json.loads(render_result.pop("stdout"))
    except json.JSONDecodeError:
        _fail("E_V240_CLOSE_SSOT", "formal TaskList renderer output is not JSON")
    if rendered_envelope.get("tasklist") != required["TaskList.md"].read_text(encoding="utf-8"):
        _fail("E_V240_CLOSE_SSOT", "formal TaskList projection differs")
    completion_argv = (
        sys.executable,
        str(reducer),
        "completion-audit",
        str(required["completion_audit"]),
        str(required["ledger_checkpoint"]),
        "--evidence-jsonl",
        str(required["evidence"]),
        "--evidence-root",
        str(work_root),
        "--source-root",
        str(workspace),
        "--traceability",
        str(required["traceability"]),
        "--review",
        str(required["dual_review"]),
        "--identity-registry",
        str(required["identity_registry"]),
        "--harness",
        str(required["harness"]),
        "--ledger",
        str(required["ledger_events"]),
        "--tasklist",
        str(required["TaskList.md"]),
    )
    if not _requires_v236_completion_host_boundary(workspace):
        _fail(
            "E_V240_CLOSE_SSOT",
            "CP18 requires the trusted Goal Teams self-release lineage",
        )
    completion_result = _run_ssot_completion_host_boundary(
        completion_argv,
        workspace,
    )
    completion_result.pop("stdout", None)
    full_gate = _run_ssot_validator(
        (sys.executable, str(workspace / "scripts" / "checks" / "check-v23.py")),
        workspace,
    )
    full_gate.pop("stdout", None)
    validator_blobs = {
        path: _run_fixed(
            ("git", "rev-parse", f"{state['candidate_commit']}:{path}"), cwd=workspace
        ).stdout.strip()
        for path in (
            "scripts/v23/goalteams_v23.py",
            "scripts/checks/check-v23.py",
            "scripts/release/release.py",
        )
    }
    digests = {name: _sha256_file(path) for name, path in required.items()}
    digests["reviews"] = _canonical_json_sha256(
        [
            {
                "path": path.relative_to(archive_root).as_posix(),
                "sha256": _sha256_file(path),
            }
            for path in sorted(review_dir.glob("*.json"))
        ]
    )
    result = {
        "required_task_count": len(required_tasks),
        "ledger_revision": checkpoint.get("ledger_revision"),
        "ssot_digests": digests,
        "referenced_artifacts_sha256": _canonical_json_sha256(referenced_artifacts),
        "required_harness_bindings_sha256": _canonical_json_sha256(harness_bindings),
        "archived_goal_teams_work": _directory_tree_receipt(
            archive_root / "GoalTeamsWork-V2.40"
        ),
        "formal_validators": {
            "reduce_ledger": reduce_result,
            "render_tasklist": render_result,
            "completion_audit": completion_result,
            "check_v23": full_gate,
            "validator_blobs": validator_blobs,
        },
    }
    result["ssot_receipt_sha256"] = _canonical_json_sha256(result)
    return result


def _path_is_git_ignored_untracked(workspace: Path, path: Path) -> bool:
    relative = path.relative_to(workspace).as_posix()
    ignored = _run_git_unchecked(
        ("git", "check-ignore", "--no-index", "--quiet", "--", relative),
        cwd=workspace,
    )
    tracked = _run_git_unchecked(
        ("git", "ls-files", "--error-unmatch", "--", relative),
        cwd=workspace,
    )
    return ignored.returncode == 0 and tracked.returncode == 1


def _scan_close_evidence(
    workspace: Path,
    archive_root: Path,
    archive_path: Path,
    manifest_files: Sequence[Path],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    release_evidence = archive_root / "release-evidence"
    if not release_evidence.is_dir() or not any(
        path.is_file() for path in release_evidence.rglob("*")
    ):
        _fail("E_V240_CLOSE_ARCHIVE", "canonical release-evidence directory is empty")
    actual_files = sorted(
        path
        for path in archive_root.rglob("*")
        if path.is_file() and path != archive_path
    )
    if [path.relative_to(archive_root).as_posix() for path in actual_files] != [
        path.relative_to(archive_root).as_posix() for path in sorted(manifest_files)
    ]:
        _fail("E_V240_CLOSE_ARCHIVE", "archive manifest does not cover every evidence file")
    ignored_paths = [archive_path, *actual_files]
    if any(not _path_is_git_ignored_untracked(workspace, path) for path in ignored_paths):
        _fail("E_V240_CLOSE_ARCHIVE", "archive evidence is not ignored and untracked")

    private_payloads: dict[str, bytes] = {
        path.relative_to(archive_root).as_posix(): path.read_bytes()
        for path in actual_files
    }
    private_payloads[archive_path.name] = archive_path.read_bytes()
    private_scan = scan_private_evidence_payload(private_payloads)
    assets = _revalidate_canonical_release(state)
    canonical = _canonical_snapshot(state)
    public_paths = {
        "release/goal-teams-V2.40.tar.gz": canonical
        / "_artifacts"
        / "goal-teams-V2.40.tar.gz",
        "release/SHA256SUMS": canonical / "_artifacts" / "SHA256SUMS",
        "release/_release.json": canonical / "_release.json",
        "release/_files.sha256": canonical / "_files.sha256",
        "tracked/README.md": workspace / "README.md",
        "tracked/README.en.md": workspace / "README.en.md",
    }

    def file_set_rows(paths: Mapping[str, Path]) -> list[dict[str, Any]]:
        return [
            {
                "path": name,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for name, path in sorted(paths.items())
        ]

    public_rows = file_set_rows(public_paths)
    private_rows = file_set_rows(
        {
            path.relative_to(archive_root).as_posix(): path
            for path in [archive_path, *actual_files]
        }
    )
    checker_paths = [
        Path(__file__).resolve(),
        workspace / PUBLIC_SCAN_RELATIVE,
        workspace / "scripts" / "v23" / "v236_security.py",
        workspace / PUBLIC_SCAN_BASELINE_RELATIVE,
    ]
    checker_rows = [
        {
            "path": path.relative_to(workspace).as_posix(),
            "sha256": _sha256_file(path),
        }
        for path in checker_paths
    ]
    cp05_approval = _operation_details(state, "CP05", "CP05.workflow_approve").get(
        "ci_approval"
    )
    checker_surface = _checker_surface_digest(str(state["candidate_commit"]))
    if (
        not isinstance(cp05_approval, Mapping)
        or cp05_approval.get("checker_tree_sha256")
        != checker_surface["checker_tree_sha256"]
        or cp05_approval.get("checker_file_count")
        != checker_surface["checker_file_count"]
        or cp05_approval.get("public_scan_bindings")
        != _public_scan_trust_bindings(state)
    ):
        _fail("E_V240_CLOSE_ARCHIVE", "scanner checker surface differs from CP05")
    receipt = {
        "scope": "strict_public_release_surface_and_ignored_private_evidence",
        "public_release_surface_policy": "fail_closed_no_redaction",
        "private_evidence_policy": "shared_secret_detector_with_schema_provenance_allowed",
        "checker_rows": checker_rows,
        "checker_sha256": _canonical_json_sha256(checker_rows),
        "cp05_checker_tree_sha256": checker_surface["checker_tree_sha256"],
        "cp05_checker_file_count": checker_surface["checker_file_count"],
        "public_checker_tree_sha256": checker_surface["checker_tree_sha256"],
        "private_checker_tree_sha256": checker_surface["checker_tree_sha256"],
        "ignored_paths_sha256": _canonical_json_sha256(
            [path.relative_to(workspace).as_posix() for path in ignored_paths]
        ),
        "public_scan_receipt_sha256": assets[
            "public_scan_receipt_sha256"
        ],
        "private_scanned_files": private_scan["scanned_files"],
        "private_binary_files": private_scan["binary_files"],
        "public_file_set_sha256": _canonical_json_sha256(public_rows),
        "private_file_set_sha256": _canonical_json_sha256(private_rows),
        "asset_set_sha256": assets["asset_set_sha256"],
        "validator_receipt_sha256": assets["validator_receipt_sha256"],
    }
    receipt["receipt_sha256"] = _canonical_json_sha256(receipt)
    return receipt


def _validate_close_local_boundary(
    state: Mapping[str, Any],
    audit_receipt: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    workspace = _workspace_root()
    if RELEASE_ROOT.resolve() != workspace.resolve():
        _fail(
            "E_V240_CLOSE_FINALIZER",
            "close must run from canonical root after candidate worktree removal",
        )
    if any(
        key in config
        for key in (
            "cleanup_policy",
            "deferred_cleanup_receipt_path",
            "remove_develops_after_process_exit",
        )
    ):
        _fail(
            "E_V240_CLOSE_WORKTREE",
            "caller-deferred cleanup cannot authorize CLOSED",
        )
    archive_value = config.get("archive_index_path")
    if not isinstance(archive_value, str):
        _fail("E_V240_CLOSE_ARCHIVE", "close archive index is required")
    archive_path = Path(archive_value).expanduser().absolute()
    archive_root = workspace / "docs" / "archive" / "releases" / str(state["version"])
    if archive_path.parent != archive_root:
        _fail(
            "E_V240_CLOSE_ARCHIVE",
            "close index must be directly under docs/archive/releases/V2.40",
        )
    validate_safe_ancestors(archive_path, archive_root)
    if not archive_path.is_file() or archive_path.is_symlink():
        _fail("E_V240_CLOSE_ARCHIVE", "close archive index is not a regular file")
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    audit_sha = _canonical_json_sha256(audit_receipt)
    if (
        not isinstance(archive, Mapping)
        or archive.get("schema_version") != "goal-teams-release-close-v2.40"
        or archive.get("version") != state.get("version")
        or archive.get("source_commit") != state.get("candidate_commit")
        or archive.get("audit_receipt_sha256") != audit_sha
        or archive.get("status") != "completed"
    ):
        _fail("E_V240_CLOSE_ARCHIVE", "close archive identity/status drift")
    files = archive.get("files")
    if not isinstance(files, list) or not files:
        _fail("E_V240_CLOSE_ARCHIVE", "close archive file manifest is empty")
    observed_paths: set[str] = set()
    manifest_paths: list[Path] = []
    for record in files:
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            _fail("E_V240_CLOSE_ARCHIVE", "close archive file record malformed")
        file_path = archive_root / record["path"]
        validate_safe_ancestors(file_path, archive_root)
        relative = file_path.relative_to(archive_root).as_posix()
        if relative in observed_paths:
            _fail("E_V240_CLOSE_ARCHIVE", "duplicate close archive file")
        observed_paths.add(relative)
        if (
            not file_path.is_file()
            or file_path.is_symlink()
            or _sha256_file(file_path) != record.get("sha256")
            or file_path.stat().st_size != record.get("size")
        ):
            _fail("E_V240_CLOSE_ARCHIVE", f"close archive file drift: {relative}")
        manifest_paths.append(file_path)

    root_facts = _git_worktree_facts(workspace)
    candidate_path = (workspace / "develops" / "v2.40").resolve()
    worktrees = _parse_worktree_inventory(workspace)
    candidate_entries = [
        record
        for record in worktrees
        if Path(str(record["path"])).resolve() == candidate_path
        or record.get("branch") == "codex/v2.40"
    ]
    if (
        root_facts.get("branch") == "main"
        and root_facts.get("head") == state.get("candidate_commit")
        and root_facts.get("clean") is True
    ) is not True:
        _fail(
            "E_V240_CLOSE_WORKTREE",
            "canonical root must be clean main at the promoted candidate",
        )
    if candidate_path.exists() or candidate_path.is_symlink() or candidate_entries:
        _fail(
            "E_V240_CLOSE_WORKTREE",
            "develops/v2.40 still exists or remains registered",
        )
    ssot_receipt = _validate_archived_goal_teams_ssot(archive_root, state)
    if ssot_receipt.get("archived_goal_teams_work") != audit_receipt.get(
        "goal_teams_work_tree"
    ):
        _fail(
            "E_V240_CLOSE_SSOT",
            "archived GoalTeamsWork tree differs from pre-removal audit binding",
        )
    scanner_receipt = _scan_close_evidence(
        workspace, archive_root, archive_path, manifest_paths, state
    )
    receipt = {
        "passed": True,
        "candidate_commit": state["candidate_commit"],
        "audit_receipt_sha256": audit_sha,
        "archive_index_sha256": _sha256_file(archive_path),
        "root_facts": root_facts,
        "candidate_worktree_path": str(candidate_path),
        "candidate_worktree_absent": True,
        "candidate_worktree_entry_absent": True,
        "cleanup_verified": True,
        "scanner_receipt": scanner_receipt,
        "scanner_receipt_sha256": scanner_receipt["receipt_sha256"],
        "ssot_receipt": ssot_receipt,
        "ssot_receipt_sha256": ssot_receipt["ssot_receipt_sha256"],
    }
    receipt["receipt_sha256"] = _canonical_json_sha256(receipt)
    return receipt


def _exact_readback(source: str, details: Mapping[str, Any]) -> dict[str, Any]:
    copied = copy.deepcopy(dict(details))
    return {
        "classification": "exact",
        "source": source,
        "observed_at": _utc_now(),
        "state_sha256": _canonical_json_sha256(copied),
        "details": copied,
    }


def _replay_recovery_bundle_live(
    *,
    workspace: Path,
    label: str,
    receipt: Mapping[str, Any],
    files: Mapping[str, Path],
    manifest_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    develops = workspace / "develops"
    develops.mkdir(parents=True, exist_ok=True)
    replay_path = Path(tempfile.mkdtemp(prefix=f".v240-replay-{label}-", dir=develops))
    replay_path.rmdir()
    staging = Path(tempfile.mkdtemp(prefix=f".v240-untracked-{label}-", dir=develops))
    registered = False
    try:
        _run_fixed(
            ("git", "worktree", "add", "--detach", str(replay_path), str(receipt["head"])),
            cwd=workspace,
        )
        registered = True
        if files["staged"].stat().st_size:
            _run_fixed(
                ("git", "apply", "--index", "--whitespace=nowarn", str(files["staged"])),
                cwd=replay_path,
            )
        if files["unstaged"].stat().st_size:
            _run_fixed(
                ("git", "apply", "--whitespace=nowarn", str(files["unstaged"])),
                cwd=replay_path,
            )
        safe_extract_release_tar(files["archive"], staging, develops)
        for relative in sorted(manifest_rows):
            source = staging / relative
            target = replay_path / relative
            validate_safe_ancestors(source, staging)
            validate_safe_ancestors(target, replay_path)
            if target.exists() or target.is_symlink():
                _fail("E_V240_RECOVERY_BUNDLE", f"replay untracked path collides: {label}/{relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        status = _run_fixed(
            (
                "git",
                "status",
                "--porcelain=v2",
                "--branch",
                "--untracked-files=normal",
            ),
            cwd=replay_path,
        ).stdout
        staged = _run_git_unchecked(
            ("git", "diff", "--cached", "--binary"),
            cwd=replay_path,
        )
        unstaged = _run_git_unchecked(
            ("git", "diff", "--binary"),
            cwd=replay_path,
        )
        if staged.returncode != 0 or unstaged.returncode != 0:
            _fail("E_V240_RECOVERY_BUNDLE", f"replay diff failed: {label}")
        if (
            [line for line in status.splitlines() if not line.startswith("#")]
            != [
                line
                for line in files["status"].read_text(encoding="utf-8").splitlines()
                if not line.startswith("#")
            ]
            or hashlib.sha256(staged.stdout).hexdigest()
            != receipt.get("staged_patch_sha256")
            or hashlib.sha256(unstaged.stdout).hexdigest()
            != receipt.get("unstaged_patch_sha256")
        ):
            _fail("E_V240_RECOVERY_BUNDLE", f"live restore replay differs: {label}")
        for relative, row in manifest_rows.items():
            target = replay_path / relative
            if (
                not target.is_file()
                or target.is_symlink()
                or target.stat().st_size != row.get("size")
                or _sha256_file(target) != row.get("sha256")
            ):
                _fail("E_V240_RECOVERY_BUNDLE", f"live replay file differs: {label}/{relative}")
        return {
            "method": "detached_worktree_patch_and_untracked_replay",
            "head": receipt["head"],
            "status_sha256": hashlib.sha256(status.encode()).hexdigest(),
            "status_entry_count": len(
                [line for line in status.splitlines() if line and not line.startswith("#")]
            ),
            "untracked_count": len(manifest_rows),
        }
    finally:
        if registered:
            _run_git_unchecked(
                ("git", "worktree", "remove", "--force", str(replay_path)),
                cwd=workspace,
            )
        if replay_path.exists():
            shutil.rmtree(replay_path, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
        inventory = _parse_worktree_inventory(workspace)
        if any(Path(str(record["path"])).resolve() == replay_path.resolve() for record in inventory):
            _fail("E_V240_RECOVERY_BUNDLE", f"temporary replay worktree leaked: {label}")


def _execute_local_operation(
    operation_id: str,
    state: Mapping[str, Any],
    parameters: Mapping[str, Any],
    state_path: Path,
) -> dict[str, Any]:
    workspace = _workspace_root()
    scratch = workspace / "docs" / "release-state" / str(state["version"]) / str(state["candidate_commit"])
    validate_safe_ancestors(scratch, workspace / "docs")
    if operation_id == "CP00.scope_freeze":
        scope = parameters.get("scope")
        if not isinstance(scope, Mapping) or parameters.get("scope_sha256") != _canonical_json_sha256(scope):
            _fail("E_V240_SCOPE_FREEZE", "scope receipt digest is missing or forged")
        receipt = _validate_scope_receipt(
            scope,
            repository=str(state["repository"]),
            version=str(state["version"]),
            base=str(state["base_main_commit"]),
            candidate=str(state["candidate_commit"]),
        )
        return _exact_readback("local_filesystem", receipt)
    if operation_id == "CP01.legacy_recovery":
        if parameters:
            _fail(
                "E_V240_RECOVERY_BUNDLE",
                "CP01 uses the fixed pre-v2.40 recovery trust root, not caller files",
            )
        recovery_root = workspace / "docs" / "recovery" / "pre-v2.40"
        validate_safe_ancestors(recovery_root, workspace / "docs")
        labels = {
            "root-old-worktree": workspace,
            "v2.38-worktree": workspace / "develops" / "v2.38",
        }
        verified: dict[str, Any] = {}
        for label, source_worktree in labels.items():
            bundle = recovery_root / label
            required = {
                "receipt": bundle / "receipt.json",
                "staged": bundle / "staged.patch",
                "unstaged": bundle / "unstaged.patch",
                "status": bundle / "status.txt",
                "archive": bundle / "untracked.tar",
                "manifest": bundle / "untracked-manifest.json",
            }
            if any(not path.is_file() or path.is_symlink() for path in required.values()):
                _fail("E_V240_RECOVERY_BUNDLE", f"fixed recovery bundle incomplete: {label}")
            receipt = json.loads(required["receipt"].read_text(encoding="utf-8"))
            manifest = json.loads(required["manifest"].read_text(encoding="utf-8"))
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("schema_version") != "goal-teams-worktree-recovery-v1"
                or receipt.get("label") != label
                or Path(str(receipt.get("worktree", ""))).absolute()
                != source_worktree.absolute()
                or not isinstance(manifest, list)
            ):
                _fail("E_V240_RECOVERY_BUNDLE", f"fixed recovery receipt drift: {label}")
            expected_hashes = {
                "staged": receipt.get("staged_patch_sha256"),
                "unstaged": receipt.get("unstaged_patch_sha256"),
                "archive": receipt.get("untracked_archive_sha256"),
            }
            for key, expected_sha in expected_hashes.items():
                if _sha256_file(required[key]) != expected_sha:
                    _fail("E_V240_RECOVERY_BUNDLE", f"recovery {key} hash drift: {label}")
            manifest_rows: dict[str, Mapping[str, Any]] = {}
            for row in manifest:
                if (
                    not isinstance(row, Mapping)
                    or not isinstance(row.get("path"), str)
                    or PurePosixPath(row["path"]).is_absolute()
                    or ".." in PurePosixPath(row["path"]).parts
                    or row["path"] in manifest_rows
                ):
                    _fail("E_V240_RECOVERY_BUNDLE", f"unsafe untracked manifest: {label}")
                manifest_rows[row["path"]] = row
            try:
                with tarfile.open(required["archive"], "r:*") as archive:
                    members = [member for member in archive.getmembers() if member.isfile()]
                    if {member.name for member in members} != set(manifest_rows):
                        _fail("E_V240_RECOVERY_BUNDLE", f"untracked archive set drift: {label}")
                    for member in members:
                        stream = archive.extractfile(member)
                        data = stream.read() if stream is not None else b""
                        row = manifest_rows[member.name]
                        if (
                            len(data) != row.get("size")
                            or hashlib.sha256(data).hexdigest() != row.get("sha256")
                        ):
                            _fail("E_V240_RECOVERY_BUNDLE", f"untracked archive bytes drift: {label}")
            except (OSError, tarfile.TarError) as exc:
                _fail("E_V240_RECOVERY_BUNDLE", f"cannot inspect recovery archive: {exc}")

            if not source_worktree.is_dir():
                _fail("E_V240_RECOVERY_BUNDLE", f"source worktree disappeared: {label}")
            live_head = _run_fixed(("git", "rev-parse", "HEAD"), cwd=source_worktree).stdout.strip()
            live_branch = _run_fixed(
                ("git", "rev-parse", "--abbrev-ref", "HEAD"), cwd=source_worktree
            ).stdout.strip()
            live_status = _run_fixed(
                (
                    "git",
                    "status",
                    "--porcelain=v2",
                    "--branch",
                    "--untracked-files=normal",
                ),
                cwd=source_worktree,
            ).stdout
            live_staged = _run_git_unchecked(
                ("git", "diff", "--cached", "--binary"),
                cwd=source_worktree,
            )
            live_unstaged = _run_git_unchecked(
                ("git", "diff", "--binary"),
                cwd=source_worktree,
            )
            if live_staged.returncode != 0 or live_unstaged.returncode != 0:
                _fail("E_V240_RECOVERY_BUNDLE", f"cannot re-read source changes: {label}")
            status_count = len(
                [
                    line
                    for line in live_status.splitlines()
                    if line and not line.startswith("#")
                ]
            )
            if (
                live_head != receipt.get("head")
                or live_branch != receipt.get("branch")
                or live_status.encode() != required["status"].read_bytes()
                or status_count != receipt.get("status_entry_count")
                or hashlib.sha256(live_staged.stdout).hexdigest()
                != receipt.get("staged_patch_sha256")
                or hashlib.sha256(live_unstaged.stdout).hexdigest()
                != receipt.get("unstaged_patch_sha256")
            ):
                _fail("E_V240_RECOVERY_BUNDLE", f"source worktree drift since recovery: {label}")
            for relative, row in manifest_rows.items():
                source = source_worktree / relative
                validate_safe_ancestors(source, source_worktree)
                if (
                    not source.is_file()
                    or source.is_symlink()
                    or source.stat().st_size != row.get("size")
                    or _sha256_file(source) != row.get("sha256")
                ):
                    _fail("E_V240_RECOVERY_BUNDLE", f"source untracked file drift: {label}/{relative}")
            replay_receipt = _replay_recovery_bundle_live(
                workspace=workspace,
                label=label,
                receipt=receipt,
                files=required,
                manifest_rows=manifest_rows,
            )
            verified[label] = {
                "receipt_sha256": _sha256_file(required["receipt"]),
                "manifest_sha256": _sha256_file(required["manifest"]),
                "status_sha256": _sha256_file(required["status"]),
                "status_entry_count": status_count,
                "untracked_count": len(manifest_rows),
                "live_replay": replay_receipt,
            }

        rehearsal_path = recovery_root / "restore-rehearsal-receipt.json"
        if not rehearsal_path.is_file() or rehearsal_path.is_symlink():
            _fail("E_V240_RECOVERY_BUNDLE", "fixed restore rehearsal receipt missing")
        rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
        results = rehearsal.get("results") if isinstance(rehearsal, Mapping) else None
        if (
            rehearsal.get("schema_version") != "goal-teams-recovery-rehearsal-v1"
            or rehearsal.get("passed") is not True
            or rehearsal.get("temporary_worktrees_removed") is not True
            or not isinstance(results, list)
            or {result.get("label") for result in results if isinstance(result, Mapping)}
            != set(labels)
            or any(not isinstance(result, Mapping) or result.get("passed") is not True for result in results)
        ):
            _fail("E_V240_RECOVERY_BUNDLE", "restore rehearsal receipt is not exact/passed")
        for result in results:
            label = str(result["label"])
            receipt = json.loads(
                (recovery_root / label / "receipt.json").read_text(encoding="utf-8")
            )
            if (
                result.get("source_head") != receipt.get("head")
                or result.get("staged_patch_sha256") != receipt.get("staged_patch_sha256")
                or result.get("unstaged_patch_sha256") != receipt.get("unstaged_patch_sha256")
                or result.get("untracked_archive_sha256")
                != receipt.get("untracked_archive_sha256")
                or result.get("untracked_manifest_sha256")
                != verified[label]["manifest_sha256"]
                or result.get("replayed_status_entry_count")
                != receipt.get("status_entry_count")
                or result.get("replayed_untracked_count") != receipt.get("untracked_count")
            ):
                _fail("E_V240_RECOVERY_BUNDLE", f"restore rehearsal binding drift: {label}")
        return _exact_readback(
            "local_filesystem",
            {
                "recovery_bundles": verified,
                "restore_rehearsal_sha256": _sha256_file(rehearsal_path),
                "restore_rehearsal_method": rehearsal.get("method"),
            },
        )
    if operation_id == "CP02.topology_validate":
        if "workspace_facts" in parameters:
            _fail(
                "E_V240_WORKTREE_LOCATION",
                "CP02 rejects caller-supplied workspace facts",
            )
        expected_scope = parameters.get("expected_scope")
        if expected_scope is not None and not isinstance(expected_scope, Mapping):
            _fail("E_V240_WORKTREE_LOCATION", "CP02 expected_scope is malformed")
        facts = collect_workspace_facts(state, expected_scope)
        receipt = validate_workspace_facts(facts)
        if receipt.get("candidate_commit") != state.get("candidate_commit") or receipt.get("remote_main_commit") != state.get("base_main_commit"):
            _fail("E_V240_CANDIDATE_ANCESTRY", "topology facts differ from state identity")
        return _exact_readback(
            "local_filesystem",
            {
                "workspace_doctor": receipt,
                "workspace_facts_sha256": _canonical_json_sha256(facts),
                "worktrees": copy.deepcopy(facts["worktrees"]),
            },
        )
    if operation_id == "CP04.development_identity":
        checkout = _require_clean_candidate_checkout(state)
        validate_readme_projection(RELEASE_ROOT, str(state["version"]))
        result = _run_fixed(
            (
                sys.executable,
                str(RELEASE_ROOT / "scripts" / "checks" / "check-version-sync.py"),
                "--mode",
                "candidate",
            )
        )
        return _exact_readback(
            "local_filesystem",
            {
                "version_sync_stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                "candidate_checkout": checkout,
            },
        )
    if operation_id == "CP05.contract_validate":
        checkout = _require_clean_candidate_checkout(state)
        schema = _load_promotion_schema()
        if list(_schema_operation_plan(schema)) != [f"CP{index:02d}" for index in range(19)]:
            _fail("E_V240_STATE_SCHEMA", "promotion contract checkpoint order drift")
        public_scan_bindings = _public_scan_trust_bindings(state)
        return _exact_readback(
            "local_filesystem",
            {
                "promotion_schema_sha256": _sha256_file(PROMOTION_SCHEMA_PATH),
                "semantic_validator": schema["x-semantic-validator"]["validator_id"],
                "public_scan_bindings": public_scan_bindings,
                "candidate_checkout": checkout,
            },
        )
    if operation_id == "CP05.workflow_approve":
        checkout = _require_clean_candidate_checkout(state)
        approval = parameters.get("ci_approval")
        if not isinstance(approval, Mapping):
            _fail("E_V240_CI_TRUST_BINDING", "CI approval receipt is required")
        reviewer = approval.get("reviewer")
        if (
            not isinstance(reviewer, Mapping)
            or reviewer.get("role") != "independent_release_reviewer"
            or not isinstance(reviewer.get("member_id"), str)
            or not reviewer.get("member_id")
            or not isinstance(reviewer.get("run_id"), str)
            or reviewer.get("run_id") in {"", "RUN-V240-LEAD"}
            or reviewer.get("independent") is not True
            or reviewer.get("decision") != "accepted"
            or reviewer.get("source_commit") != state.get("candidate_commit")
        ):
            _fail(
                "E_V240_CI_TRUST_BINDING",
                "workflow approval lacks an independent current reviewer identity",
            )
        _parse_utc(reviewer.get("reviewed_at"), "E_V240_CI_TRUST_BINDING")
        _validate_ci_state_authority(state, approval)
        workflow_path = ".github/workflows/release-gate.yml"
        expected_blob = _run_fixed(
            ("git", "rev-parse", f"{state['candidate_commit']}:{workflow_path}"),
            cwd=RELEASE_ROOT,
        ).stdout.strip()
        checker_surface = _checker_surface_digest(str(state["candidate_commit"]))
        public_scan_bindings = _public_scan_trust_bindings(state)
        if (
            approval.get("head_sha") != state.get("candidate_commit")
            or approval.get("workflow_path") != workflow_path
            or approval.get("workflow_blob_sha") != expected_blob
            or approval.get("required_jobs")
            != ["check-ubuntu", "check-macos", "release-asset-gate"]
            or approval.get("checker_tree_sha256")
            != checker_surface["checker_tree_sha256"]
            or approval.get("checker_file_count")
            != checker_surface["checker_file_count"]
            or approval.get("public_scan_bindings") != public_scan_bindings
        ):
            _fail(
                "E_V240_CI_TRUST_BINDING",
                "CI approval does not bind the frozen workflow and public scanner",
            )
        return _exact_readback(
            "local_filesystem",
            {
                "ci_approval": copy.deepcopy(dict(approval)),
                "ci_approval_sha256": _canonical_json_sha256(approval),
                "candidate_checkout": checkout,
            },
        )
    if operation_id == "CP06.static_gates":
        checkout = _require_clean_candidate_checkout(state)
        commands = (
            (
                "git",
                "diff",
                "--check",
                str(state["base_main_commit"]),
                str(state["candidate_commit"]),
            ),
            (sys.executable, str(RELEASE_ROOT / "scripts" / "checks" / "check-ci-pins.py")),
            (sys.executable, str(RELEASE_ROOT / "scripts" / "checks" / "check-version-sync.py"), "--mode", "candidate"),
            (
                sys.executable,
                str(RELEASE_ROOT / "scripts" / "checks" / "check-workspace-boundaries.py"),
            ),
            (sys.executable, str(RELEASE_ROOT / "scripts" / "checks" / "validate.py")),
            (
                sys.executable,
                "-m",
                "unittest",
                "tests.v23.test_v236_security_redaction",
            ),
        )
        receipts = []
        for command in commands:
            result = _run_fixed(command)
            receipts.append(hashlib.sha256((result.stdout + result.stderr).encode()).hexdigest())
        return _exact_readback(
            "local_filesystem",
            {
                "static_gate_receipts": receipts,
                "diff_range": f"{state['base_main_commit']}..{state['candidate_commit']}",
                "candidate_checkout": checkout,
            },
        )
    if operation_id == "CP07.quality_gates":
        checkout = _require_clean_candidate_checkout(state)
        commands = (
            (str(RELEASE_ROOT / "scripts" / "check.sh"),),
            (sys.executable, str(RELEASE_ROOT / "scripts" / "checks" / "check-v23.py")),
            (sys.executable, str(RELEASE_ROOT / "scripts" / "benchmark" / "benchmark-runner.py"), "--check-only"),
            (sys.executable, str(RELEASE_ROOT / "scripts" / "checks" / "check-install-lifecycle.py")),
        )
        receipts = []
        for command in commands:
            result = _run_fixed(command)
            receipts.append(hashlib.sha256((result.stdout + result.stderr).encode()).hexdigest())
        return _exact_readback(
            "local_filesystem",
            {"quality_gate_receipts": receipts, "candidate_checkout": checkout},
        )
    if operation_id in {"CP08.candidate_identity", "CP08.rc_commit"}:
        checkout = _require_clean_candidate_checkout(state)
        identity = _verify_frozen_git_identity(state)
        manifest_path = "scripts/install/package-manifest.txt"
        workflow_path = ".github/workflows/release-gate.yml"
        manifest_blob = _run_fixed(
            ("git", "rev-parse", f"{state['candidate_commit']}:{manifest_path}"),
            cwd=RELEASE_ROOT,
        ).stdout.strip()
        workflow_blob = _run_fixed(
            ("git", "rev-parse", f"{state['candidate_commit']}:{workflow_path}"),
            cwd=RELEASE_ROOT,
        ).stdout.strip()
        checker = _checker_surface_digest(str(state["candidate_commit"]))
        return _exact_readback(
            "local_filesystem",
            {
                **identity,
                "head": checkout["head"],
                "worktree_clean": True,
                "package_manifest_blob": manifest_blob,
                "package_manifest_sha256": hashlib.sha256(
                    _git_blob_bytes(str(state["candidate_commit"]), manifest_path)
                ).hexdigest(),
                "workflow_blob_sha": workflow_blob,
                **checker,
            },
        )
    if operation_id in {"CP09.build_primary", "CP09.build_reproducibility"}:
        label = "primary" if operation_id.endswith("primary") else "reproducibility"
        details = _build_snapshot(state, scratch / "builds" / label)
        if label == "reproducibility":
            primary = _snapshot_tree_digest(
                scratch / "builds" / "primary" / str(state["version"])
            )
            if primary["tree_sha256"] != details["tree_sha256"]:
                _fail("E_V240_BUILD_REPRODUCIBILITY", "isolated builds differ")
        return _exact_readback("local_filesystem", details)
    if operation_id == "CP10.asset_validate":
        canonical_root = workspace / "release" / "versions"
        target = canonical_root / str(state["version"])
        if not target.exists():
            _run_fixed(
                (
                    sys.executable,
                    str(RELEASE_ROOT / "scripts" / "release" / "build-release.py"),
                    "--version",
                    str(state["version"]),
                    "--commit",
                    str(state["candidate_commit"]),
                    "--source-ref",
                    str(state["candidate_commit"]),
                )
            )
        record = json.loads((target / "_release.json").read_text(encoding="utf-8"))
        validate_frozen_release_record(
            record, str(state["version"]), str(state["candidate_commit"])
        )
        canonical_digest = _snapshot_tree_digest(target)
        primary = _operation_details(state, "CP09", "CP09.build_primary")
        reproducibility = _operation_details(
            state, "CP09", "CP09.build_reproducibility"
        )
        for prior in (primary, reproducibility):
            if any(
                canonical_digest.get(field) != prior.get(field)
                for field in ("tree_sha256", "file_count", "rows_sha256")
            ):
                _fail(
                    "E_V240_BUILD_REPRODUCIBILITY",
                    "canonical snapshot differs from an isolated CP09 build",
                )
        result = _run_fixed(
            (
                sys.executable,
                str(RELEASE_ROOT / "scripts" / "release" / "validate-release.py"),
                "--version",
                str(state["version"]),
            )
        )
        try:
            validation = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            _fail("E_V240_RELEASE_VALIDATION", f"validator returned invalid JSON: {exc}")
        if not isinstance(validation, Mapping) or validation.get("passed") is not True:
            _fail("E_V240_RELEASE_VALIDATION", "release validator did not pass")
        public_scan_receipt = _run_public_release_scan(state, target)
        return _exact_readback(
            "local_filesystem",
            {
                **canonical_digest,
                "validator_receipt_sha256": _canonical_json_sha256(validation),
                "public_scan_receipt": public_scan_receipt,
                "public_scan_receipt_sha256": public_scan_receipt[
                    "receipt_sha256"
                ],
                "source_commit": state["candidate_commit"],
            },
        )
    if operation_id == "CP10.snapshot_seal":
        target = _canonical_snapshot(state)
        record = json.loads((target / "_release.json").read_text(encoding="utf-8"))
        validate_frozen_release_record(
            record, str(state["version"]), str(state["candidate_commit"])
        )
        if record.get("sealed") is not True or record.get("identity_authority") != "source_commit":
            _fail("E_V240_SNAPSHOT_SEAL", "canonical snapshot is not sealed")
        validator_details = _operation_details(
            state, "CP10", "CP10.asset_validate"
        )
        public_scan_receipt = _run_public_release_scan(state, target)
        if public_scan_receipt != validator_details.get("public_scan_receipt"):
            _fail(
                "E_V240_PUBLIC_SCAN",
                "snapshot-seal scan differs from asset-validation scan",
            )
        assets = _canonical_release_assets(state)
        return _exact_readback(
            "local_filesystem",
            {
                **_snapshot_tree_digest(target),
                "release_record_sha256": _sha256_file(target / "_release.json"),
                "assets": assets,
                "asset_set_sha256": _canonical_json_sha256(assets),
                "validator_receipt_sha256": validator_details.get("validator_receipt_sha256"),
                "public_scan_receipt": public_scan_receipt,
                "public_scan_receipt_sha256": public_scan_receipt[
                    "receipt_sha256"
                ],
            },
        )
    if operation_id in {"CP11.local_bundle_rehearsal", "CP16.remote_bundle_rehearsal"}:
        if operation_id.startswith("CP16"):
            download_operation = next(
                (
                    operation
                    for operation in state["checkpoints"]["CP16"]["operations"]
                    if operation.get("operation_id") == "CP16.asset_download_verify"
                ),
                None,
            )
            download_details = (
                download_operation.get("readback", {}).get("details", {})
                if isinstance(download_operation, Mapping)
                else {}
            )
            bundle_value = download_details.get("bundle_path")
            identity_value = download_details.get("release_identity_path")
            if not isinstance(bundle_value, str) or not isinstance(identity_value, str):
                _fail("E_V240_INSTALL_IDENTITY", "CP16 rehearsal lacks Draft download receipt")
            bundle = Path(bundle_value).expanduser().absolute()
            identity = Path(identity_value).expanduser().absolute()
            validate_safe_ancestors(bundle, workspace / "docs")
            validate_safe_ancestors(identity, workspace / "docs")
            if _sha256_file(identity) != download_details.get("release_identity_sha256"):
                _fail("E_V240_INSTALL_IDENTITY", "Draft identity receipt digest drift")
        else:
            bundle = scratch / "bundle"
            bundle_receipt = _assemble_release_bundle(state, bundle)
            record = json.loads((_canonical_snapshot(state) / "_release.json").read_text(encoding="utf-8"))
            identity_payload = {
                "source_kind": "local_release_bundle",
                "repository": state["repository"],
                "version": state["version"],
                "release_tag": state["tag"],
                "release_id": 0,
                "release_state": "local",
                "source_commit": state["candidate_commit"],
                "source_git_tree_id": record["source_git_tree_id"],
                "assets": [
                    {"name": name, "asset_id": 0, "download_sha256": value["sha256"], **value}
                    for name, value in bundle_receipt["assets"].items()
                ],
            }
            identity = scratch / "local-release-identity.json"
            if identity.exists():
                existing = json.loads(identity.read_text(encoding="utf-8"))
                if existing != identity_payload:
                    _fail("E_V240_BUNDLE_TAMPER", "local rehearsal identity conflicts")
            else:
                identity.write_text(
                    json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
        codex_home = scratch / ("rehearsal-local" if operation_id.startswith("CP11") else "rehearsal-remote") / "codex-home"
        report = codex_home.parent / "install-report.json"
        result = _run_fixed(
            (
                str(RELEASE_ROOT / "scripts" / "install" / "install-local.sh"),
                "--release-bundle",
                str(bundle),
                "--release-identity",
                str(identity),
            ),
            env={
                "CODEX_HOME": str(codex_home),
                "INSTALL_REPORT": str(report),
                "GOAL_TEAMS_RELEASE_REHEARSAL": "1",
                "GOAL_TEAMS_INSTALL_TEST_VALIDATION": "1",
            },
        )
        if not report.is_file():
            _fail("E_V240_INSTALL_IDENTITY", "installer did not write its report")
        install_report = json.loads(report.read_text(encoding="utf-8"))
        if install_report.get("status") != "installed":
            _fail("E_V240_INSTALL_IDENTITY", "rehearsal install did not complete")
        return _exact_readback(
            "installed_tree",
            {
                "install_report_sha256": _sha256_file(report),
                "source_commit": state["candidate_commit"],
                "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            },
        )
    if operation_id == "CP14.promotion_lease":
        if "observed_main_commit" in parameters:
            _fail(
                "E_V240_REMOTE_MAIN_LEASE",
                "promotion lease rejects caller-supplied remote main",
            )
        observed = _github_adapter_for_state(
            state, {"execute_external_writes": False}
        )._remote_ref("refs/heads/main")
        if not isinstance(observed, str) or SHA40_RE.fullmatch(observed) is None:
            _fail("E_V240_REMOTE_MAIN_LEASE", "fixed REST/origin main receipt is absent")
        _verify_frozen_git_identity(state)
        validate_remote_lease(
            str(state["base_main_commit"]), str(observed), str(state["candidate_commit"])
        )
        return _exact_readback(
            "git_ls_remote",
            {
                "remote_main_commit": observed,
                "candidate_commit": state["candidate_commit"],
                "source": "fixed github.com REST ref cross-checked with origin ls-remote",
            },
        )
    if operation_id == "CP17.actual_install":
        if parameters.get("execute_actual_install") is not True or os.environ.get("GOAL_TEAMS_RELEASE_INSTALL") != "1":
            _fail(
                "E_V240_ACTUAL_INSTALL_NOT_AUTHORIZED",
                "actual install requires explicit input and GOAL_TEAMS_RELEASE_INSTALL=1",
            )
        if "codex_home" in parameters:
            _fail(
                "E_V240_INSTALL_TARGET",
                "production actual_install rejects caller-selected CODEX_HOME",
            )
        if (
            parameters.get("test_validation") is True
            or os.environ.get("GOAL_TEAMS_INSTALL_TEST_VALIDATION") == "1"
        ):
            _fail(
                "E_V240_INSTALL_TARGET",
                "test-validation targets cannot satisfy production actual_install",
            )
        download_operation = next(
            (
                operation
                for operation in state["checkpoints"]["CP17"]["operations"]
                if operation.get("operation_id") == "CP17.published_asset_download"
            ),
            None,
        )
        download_details = (
            download_operation.get("readback", {}).get("details", {})
            if isinstance(download_operation, Mapping)
            else {}
        )
        bundle_value = download_details.get("bundle_path")
        identity_value = download_details.get("release_identity_path")
        if not isinstance(bundle_value, str) or not isinstance(identity_value, str):
            _fail("E_V240_INSTALL_IDENTITY", "actual install lacks published download receipt")
        bundle = Path(bundle_value).expanduser().absolute()
        identity = Path(identity_value).expanduser().absolute()
        validate_safe_ancestors(bundle, workspace / "docs")
        validate_safe_ancestors(identity, workspace / "docs")
        if _sha256_file(identity) != download_details.get("release_identity_sha256"):
            _fail("E_V240_INSTALL_IDENTITY", "published identity receipt digest drift")
        identity_payload = json.loads(identity.read_text(encoding="utf-8"))
        if (
            identity_payload.get("source_kind") != "github_release_asset"
            or identity_payload.get("release_state") != "published"
            or identity_payload.get("release_id") != download_details.get("release_id")
            or identity_payload.get("assets") != download_details.get("assets")
        ):
            _fail("E_V240_INSTALL_IDENTITY", "published download/install identity drift")
        codex_home_path = _canonical_codex_home()
        adopted = _adopt_exact_actual_install(
            state, bundle, download_details, codex_home_path
        )
        if adopted is not None:
            return adopted
        env: dict[str, str] = {"CODEX_HOME": str(codex_home_path)}
        reports_root = codex_home_path / "state" / "goal-teams" / "reports"
        before_reports = (
            {path for path in reports_root.glob("*.json") if path.is_file()}
            if reports_root.is_dir()
            else set()
        )
        _run_fixed(
            (
                str(RELEASE_ROOT / "scripts" / "install" / "install-local.sh"),
                "--release-bundle",
                str(bundle),
                "--release-identity",
                str(identity),
            ),
            env=env,
        )
        after_reports = (
            {path for path in reports_root.glob("*.json") if path.is_file()}
            if reports_root.is_dir()
            else set()
        )
        created_reports = sorted(
            after_reports - before_reports, key=lambda path: path.stat().st_mtime_ns
        )
        if len(created_reports) != 1:
            _fail("E_V240_INSTALL_IDENTITY", "actual installer did not create exactly one default report")
        report = created_reports[0]
        install_report = json.loads(report.read_text(encoding="utf-8"))
        current_install_state_path = codex_home_path / "state" / "goal-teams" / "current.json"
        if not current_install_state_path.is_file() or current_install_state_path.is_symlink():
            _fail("E_V240_INSTALL_IDENTITY", "installed current-state receipt missing")
        current_install_state = json.loads(
            current_install_state_path.read_text(encoding="utf-8")
        )
        return _exact_readback(
            "installed_tree",
            {
                "install_report": install_report,
                "install_report_sha256": _sha256_file(report),
                "install_state": current_install_state,
                "install_state_sha256": _sha256_file(current_install_state_path),
                "codex_home": str(codex_home_path),
                "canonical_target": True,
                "adopted_after_marker_loss": False,
            },
        )
    if operation_id == "CP17.independent_audit":
        observation = collect_live_audit_observation(state)
        receipt = _run_independent_audit(observation)
        work_tree = _directory_tree_receipt(RELEASE_ROOT / "GoalTeamsWork-V2.40")
        receipt["goal_teams_work_tree"] = work_tree
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = _canonical_json_sha256(receipt)
        return _exact_readback("github_api", {"audit_receipt": receipt})
    if operation_id == "CP18.archive_close":
        audit_receipt = parameters.get("audit_receipt")
        close_boundary = parameters.get("close_boundary_receipt")
        archive_index_path = parameters.get("archive_index_path")
        if not isinstance(audit_receipt, Mapping) or audit_receipt.get("passed") is not True:
            _fail("E_V240_CLOSE_AUDIT", "independent audit receipt is not passed")
        if audit_receipt.get("source_commit") != state.get("candidate_commit"):
            _fail("E_V240_CLOSE_AUDIT", "audit commit differs from frozen candidate")
        if not isinstance(close_boundary, Mapping):
            _fail("E_V240_CLOSE_ARCHIVE", "close boundary receipt missing")
        if not isinstance(archive_index_path, str):
            _fail("E_V240_CLOSE_ARCHIVE", "fresh close archive path missing")
        boundary_source = dict(close_boundary)
        boundary_sha = boundary_source.pop("receipt_sha256", None)
        if (
            close_boundary.get("passed") is not True
            or close_boundary.get("candidate_commit") != state.get("candidate_commit")
            or close_boundary.get("audit_receipt_sha256")
            != _canonical_json_sha256(audit_receipt)
            or boundary_sha != _canonical_json_sha256(boundary_source)
            or close_boundary.get("cleanup_verified") is not True
            or close_boundary.get("candidate_worktree_absent") is not True
            or close_boundary.get("candidate_worktree_entry_absent") is not True
            or not isinstance(close_boundary.get("scanner_receipt_sha256"), str)
            or not isinstance(close_boundary.get("ssot_receipt_sha256"), str)
        ):
            _fail("E_V240_CLOSE_ARCHIVE", "close boundary receipt drift")
        # The permanent ruleset mutation precedes this local operation.  The
        # archive, canonical root and worktree registry therefore have a real
        # TOCTOU window after close_release() performs its first validation.
        # Recompute the complete boundary now, immediately before CLOSED, and
        # require byte-for-byte deterministic agreement with the pre-finalize
        # receipt.  A finalized remote policy is recoverable; a false CLOSED
        # marker is not.
        fresh_boundary = _validate_close_local_boundary(
            state,
            audit_receipt,
            {"archive_index_path": archive_index_path},
        )
        if fresh_boundary != close_boundary:
            _fail(
                "E_V240_CLOSE_ARCHIVE",
                "close boundary changed after promotion lock finalization",
            )
        return _exact_readback(
            "local_filesystem",
            {
                "closed_identity_sha256": _canonical_json_sha256(audit_receipt),
                "candidate_commit": state["candidate_commit"],
                "close_boundary_receipt_sha256": boundary_sha,
                "post_finalize_boundary_revalidated": True,
                "cleanup_verified": True,
                "scanner_receipt_sha256": close_boundary["scanner_receipt_sha256"],
                "ssot_receipt_sha256": close_boundary["ssot_receipt_sha256"],
            },
        )
    _fail("E_V240_LOCAL_OPERATION_UNSUPPORTED", f"unsupported fixed local operation: {operation_id}")


def _github_adapter_for_state(
    state: Mapping[str, Any], config: Mapping[str, Any]
) -> Any:
    authority = state.get("github_authority")
    if not isinstance(authority, Mapping) and state.get("current_checkpoint") not in {
        "CP02",
        "CP03",
    }:
        _fail("E_V240_GITHUB_AUTHORITY_BINDING", "promotion state has no authority binding")
    if not isinstance(authority, Mapping):
        authority = {}
        checkpoint = state.get("checkpoints", {}).get("CP03", {})
        operations = checkpoint.get("operations") if isinstance(checkpoint, Mapping) else None
        if isinstance(operations, list):
            for operation in operations:
                candidate = (
                    operation.get("readback", {}).get("details", {}).get("authority")
                    if isinstance(operation, Mapping)
                    else None
                )
                if isinstance(candidate, Mapping):
                    authority = candidate
    module = _load_github_adapter()
    return module.GitHubAdapter(
        source_root=RELEASE_ROOT,
        workspace_root=_workspace_root(),
        repository=str(state["repository"]),
        version=str(state["version"]),
        candidate_commit=str(state["candidate_commit"]),
        base_main_commit=str(state["base_main_commit"]),
        authority=authority,
        execute_external_writes=config.get("execute_external_writes") is True,
    )


def _operation_authorization(
    operation: Mapping[str, Any], config: Mapping[str, Any]
) -> Mapping[str, Any]:
    authorizations = config.get("operation_authorizations")
    operation_id = operation.get("operation_id")
    if not isinstance(authorizations, Mapping):
        _fail("E_V240_OPERATION_AUTHORIZATION", "operation_authorizations is required")
    authorization = authorizations.get(operation_id)
    if not isinstance(authorization, Mapping):
        _fail("E_V240_OPERATION_AUTHORIZATION", f"authorization missing: {operation_id}")
    intent = operation.get("intent")
    if not isinstance(intent, Mapping) or authorization.get("intent_sha256") != _canonical_json_sha256(intent):
        _fail("E_V240_OPERATION_AUTHORIZATION", f"intent digest drift: {operation_id}")
    expected_before = intent.get("expected_before")
    supplied_before = authorization.get("expected_before")
    if isinstance(expected_before, Mapping) and supplied_before != expected_before:
        _fail("E_V240_STATE_EXPECTED_BEFORE", f"expected-before drift: {operation_id}")
    return authorization


def _critical_readback_identity(action: str, details: Mapping[str, Any]) -> Any:
    if action in {"github_authority_verify", "ruleset_capability_verify"}:
        authority = details.get("authority")
        if not isinstance(authority, Mapping):
            return None
        return {
            field: copy.deepcopy(authority.get(field))
            for field in (
                "api_host",
                "actor_id",
                "actor_login",
                "repository_id",
                "repository_full_name",
                "origin_binding",
                "origin_binding_sha256",
                "permission",
                "immutable_endpoint_capability",
                "ruleset_capability",
                "authorized_external_actions",
                "actor_binding_sha256",
                "repository_binding_sha256",
                "capability_binding_sha256",
                "authorized_actions_sha256",
            )
        }
    fields_by_action = {
        "candidate_push": ("ref", "remote_commit"),
        "tag_push": ("tag", "tag_object", "peeled_commit"),
        "main_promote": ("ref", "remote_commit"),
        "immutable_release_enable": ("enabled",),
        "immutable_release_verify": ("enabled",),
        "promotion_lock_create": ("ruleset_name", "ruleset_sha256"),
        "tag_ruleset_create": ("ruleset_name", "ruleset_sha256"),
        "promotion_lock_finalize": ("ruleset_name", "ruleset_sha256"),
        "draft_create": (
            "databaseId",
            "isDraft",
            "tagName",
            "targetCommitish",
            "resolvedTargetCommit",
            "name",
            "body",
        ),
        "asset_upload": ("asset", "asset_id", "sha256", "size", "release_id"),
        "asset_download_verify": ("release_id", "release_state", "asset_set_sha256", "assets"),
        "release_publish": (
            "databaseId",
            "isDraft",
            "isImmutable",
            "tagName",
            "targetCommitish",
            "resolvedTargetCommit",
            "name",
            "body",
            "tagObject",
            "peeledCommit",
            "latest",
            "asset_set_sha256",
            "assets",
        ),
        "published_asset_download": ("release_id", "release_state", "asset_set_sha256", "assets"),
        "ci_wait": ("ci_receipt",),
        "post_release_ci": ("ci_receipt",),
    }
    fields = fields_by_action.get(action)
    if fields is None:
        return copy.deepcopy(dict(details))
    return {field: copy.deepcopy(details.get(field)) for field in fields}


def _persist_operation_readback(
    path: Path,
    state: dict[str, Any],
    checkpoint_id: str,
    operation_index: int,
    readback: Mapping[str, Any],
    expected_digest: str,
) -> str:
    if (
        readback.get("classification") != "exact"
        or readback.get("source")
        not in {"local_filesystem", "git_ls_remote", "github_api", "github_actions_api", "installed_tree"}
        or SHA256_RE.fullmatch(str(readback.get("state_sha256", ""))) is None
    ):
        _fail("E_V240_OPERATION_READBACK", "operation does not have exact live readback")
    operation = state["checkpoints"][checkpoint_id]["operations"][operation_index]
    receipt_source = {"intent": operation["intent"], "readback": readback}
    operation["readback"] = copy.deepcopy(dict(readback))
    operation["receipt_sha256"] = _canonical_json_sha256(receipt_source)
    state["updated_at"] = _utc_now()
    return _atomic_state_write(path, state, expected_sha256=expected_digest)


def _checkpoint_operation(
    state: Mapping[str, Any], checkpoint_id: str, operation_id: str
) -> Mapping[str, Any]:
    checkpoint = state.get("checkpoints", {}).get(checkpoint_id, {})
    operations = checkpoint.get("operations") if isinstance(checkpoint, Mapping) else None
    if not isinstance(operations, list):
        _fail("E_V240_STATE_DERIVATION", f"checkpoint operations missing: {checkpoint_id}")
    matches = [
        operation
        for operation in operations
        if isinstance(operation, Mapping) and operation.get("operation_id") == operation_id
    ]
    if len(matches) != 1:
        _fail("E_V240_STATE_DERIVATION", f"operation receipt missing: {operation_id}")
    return matches[0]


def _operation_details(
    state: Mapping[str, Any], checkpoint_id: str, operation_id: str
) -> Mapping[str, Any]:
    operation = _checkpoint_operation(state, checkpoint_id, operation_id)
    readback = operation.get("readback")
    if not isinstance(readback, Mapping) or readback.get("classification") != "exact":
        _fail("E_V240_STATE_DERIVATION", f"exact readback missing: {operation_id}")
    details = readback.get("details")
    if not isinstance(details, Mapping):
        _fail("E_V240_STATE_DERIVATION", f"readback details missing: {operation_id}")
    return details


def _derive_remote_identity(
    state: Mapping[str, Any], *, published: bool
) -> dict[str, Any]:
    download_id = (
        "CP17.published_asset_download" if published else "CP16.asset_download_verify"
    )
    checkpoint_id = "CP17" if published else "CP16"
    download = _operation_details(state, checkpoint_id, download_id)
    assets = download.get("assets")
    if not isinstance(assets, list) or len(assets) != 4:
        _fail("E_V240_STATE_DERIVATION", "fixed four downloaded assets are missing")
    for asset in assets:
        if (
            not isinstance(asset, Mapping)
            or not isinstance(asset.get("asset_id"), int)
            or asset.get("asset_id", 0) < 1
            or asset.get("sha256") != asset.get("download_sha256")
        ):
            _fail("E_V240_STATE_DERIVATION", "downloaded REST asset identity is invalid")
    tag = _operation_details(state, "CP15", "CP15.tag_push")
    tag_ruleset = _operation_details(state, "CP14", "CP14.tag_ruleset")
    ruleset = tag_ruleset.get("ruleset")
    if not isinstance(ruleset, Mapping) or not isinstance(ruleset.get("id"), int):
        _fail("E_V240_STATE_DERIVATION", "permanent tag ruleset identity missing")
    if published:
        release = _operation_details(state, "CP17", "CP17.release_publish")
        if (
            release.get("isImmutable") is not True
            or release.get("latest") is not True
            or release.get("databaseId") != download.get("release_id")
            or release.get("tagName") != state.get("tag")
            or release.get("resolvedTargetCommit") != state.get("candidate_commit")
            or release.get("name") != CANONICAL_RELEASE_TITLE
            or release.get("body") != CANONICAL_RELEASE_BODY
            or release.get("peeledCommit") != state.get("candidate_commit")
            or release.get("tagObject") in {None, state.get("candidate_commit")}
            or release.get("asset_set_sha256")
            != download.get("asset_set_sha256")
            or release.get("assets") != download.get("assets")
        ):
            _fail("E_V240_STATE_DERIVATION", "published Release readbacks disagree")
    else:
        release = _operation_details(state, "CP16", "CP16.draft_create")
        if (
            release.get("isDraft") is not True
            or release.get("databaseId") != download.get("release_id")
            or release.get("tagName") != state.get("tag")
            or release.get("resolvedTargetCommit") != state.get("candidate_commit")
            or release.get("name") != CANONICAL_RELEASE_TITLE
            or release.get("body") != CANONICAL_RELEASE_BODY
        ):
            _fail("E_V240_STATE_DERIVATION", "Draft Release readbacks disagree")
    return {
        "main_commit": state["candidate_commit"] if published else state["base_main_commit"],
        "tag_object": tag.get("tag_object"),
        "tag_commit": tag.get("peeled_commit"),
        "release_id": download.get("release_id"),
        "release_state": "published" if published else "draft",
        "latest": published,
        "immutable": published,
        "immutable_release_enabled": True,
        "tag_ruleset_id": ruleset["id"],
        "assets": copy.deepcopy(assets),
    }


def _derive_install_identity(state: Mapping[str, Any]) -> dict[str, Any]:
    details = _operation_details(state, "CP17", "CP17.actual_install")
    report = details.get("install_report")
    install_state = details.get("install_state")
    if not isinstance(report, Mapping) or report.get("status") != "installed":
        _fail("E_V240_STATE_DERIVATION", "actual install report is not installed")
    if not isinstance(install_state, Mapping):
        _fail("E_V240_STATE_DERIVATION", "actual installed-state receipt missing")
    source = report.get("source")
    if not isinstance(source, Mapping):
        _fail("E_V240_STATE_DERIVATION", "actual install source receipt missing")
    downloaded = _operation_details(state, "CP17", "CP17.published_asset_download")
    remote = _derive_remote_identity(state, published=True)
    if (
        source.get("source_kind") != "github_release_asset"
        or source.get("repository") != state.get("repository")
        or source.get("release_tag") != state.get("tag")
        or source.get("release_id") != remote["release_id"]
        or source.get("release_state") != "published"
        or source.get("commit") != state.get("candidate_commit")
        or source.get("release_assets") != remote["assets"]
        or install_state.get("source_commit") != state.get("candidate_commit")
        or install_state.get("release_id") != remote["release_id"]
        or install_state.get("release_assets") != remote["assets"]
    ):
        _fail("E_V240_INSTALL_IDENTITY", "installer report differs from published REST/download identity")
    tar_name = f"goal-teams-{state['version']}.tar.gz"
    tar_asset = next(asset for asset in remote["assets"] if asset["name"] == tar_name)
    if source.get("release_asset_sha256") != tar_asset["sha256"]:
        _fail("E_V240_INSTALL_IDENTITY", "installed tar digest differs from published download")
    return {
        "source_kind": "github_release_asset",
        "repository": state["repository"],
        "version": state["version"],
        "tag": state["tag"],
        "release_id": remote["release_id"],
        "source_commit": state["candidate_commit"],
        "source_git_tree_id": install_state.get("source_git_tree_id"),
        "asset_sha256": tar_asset["sha256"],
        "installed_tree_sha256": install_state.get("skill_tree_digest"),
        "state_sha256": details.get("install_state_sha256"),
    }


def _derive_checkpoint_state_updates(
    state: Mapping[str, Any], checkpoint_id: str
) -> dict[str, Any]:
    """Derive authority state only from exact receipts in this state file."""

    if checkpoint_id == "CP03":
        authority = _operation_details(
            state, "CP03", "CP03.ruleset_capability_verify"
        ).get("authority")
        if not isinstance(authority, Mapping):
            _fail("E_V240_STATE_DERIVATION", "CP03 final authority readback missing")
        validate_github_live_authority(authority, authority)
        return {"github_authority": copy.deepcopy(dict(authority))}
    if checkpoint_id == "CP13":
        ci_run = _operation_details(state, "CP13", "CP13.candidate_ci").get("ci_run")
        if not isinstance(ci_run, Mapping):
            _fail("E_V240_STATE_DERIVATION", "candidate CI receipt missing")
        return {"ci_runs": [copy.deepcopy(dict(ci_run))]}
    if checkpoint_id == "CP14":
        authority = _operation_details(
            state, "CP14", "CP14.github_authority_revalidate"
        ).get("authority")
        ruleset_details = _operation_details(
            state, "CP14", "CP14.main_promotion_lock"
        )
        ruleset = ruleset_details.get("ruleset")
        if not isinstance(authority, Mapping) or not isinstance(ruleset, Mapping):
            _fail("E_V240_STATE_DERIVATION", "CP14 authority/lock readback missing")
        validate_github_live_authority(authority, state.get("github_authority", {}))
        remote_lock = {
            "ruleset_id": ruleset.get("id"),
            "name": ruleset.get("name"),
            "target_ref": "refs/heads/main",
            "candidate_commit": state["candidate_commit"],
            "bypass_actor_id": authority.get("actor_id"),
            "ruleset_sha256": ruleset_details.get("ruleset_sha256"),
            "observed_at": _checkpoint_operation(
                state, "CP14", "CP14.main_promotion_lock"
            ).get("readback", {}).get("observed_at"),
        }
        validate_remote_promotion_lock(
            {
                "active": True,
                "target_ref": remote_lock["target_ref"],
                "candidate_commit": remote_lock["candidate_commit"],
                "bypass_actor_id": remote_lock["bypass_actor_id"],
                "ruleset_sha256": remote_lock["ruleset_sha256"],
            },
            {
                "active": ruleset.get("enforcement") == "active",
                "target_ref": remote_lock["target_ref"],
                "candidate_commit": remote_lock["candidate_commit"],
                "bypass_actor_id": remote_lock["bypass_actor_id"],
                "ruleset_sha256": remote_lock["ruleset_sha256"],
            },
        )
        return {
            "github_authority": copy.deepcopy(dict(authority)),
            "remote_lock": remote_lock,
        }
    if checkpoint_id == "CP16":
        return {"remote_identity": _derive_remote_identity(state, published=False)}
    if checkpoint_id == "CP17":
        existing_ci = [
            copy.deepcopy(run)
            for run in state.get("ci_runs", [])
            if isinstance(run, Mapping) and run.get("stage") == "candidate"
        ]
        post_ci = _operation_details(state, "CP17", "CP17.post_release_ci").get("ci_run")
        if len(existing_ci) != 1 or not isinstance(post_ci, Mapping):
            _fail("E_V240_STATE_DERIVATION", "candidate/post-release CI chain missing")
        return {
            "remote_identity": _derive_remote_identity(state, published=True),
            "install_identity": _derive_install_identity(state),
            "ci_runs": [existing_ci[0], copy.deepcopy(dict(post_ci))],
        }
    return {}


def execute_current_checkpoint(
    state_path: str | os.PathLike[str],
    config: Mapping[str, Any],
    *,
    allowed_checkpoints: set[str] | None = None,
    recover_only: bool = False,
    _close_capability: object | None = None,
) -> dict[str, Any]:
    """Execute one checkpoint using persisted intents and marker-last CAS.

    This public API is intentionally checkpoint-scoped.  It never skips a
    checkpoint and never accepts an arbitrary command.  A crash can leave an
    operation readback on an ``in_progress`` checkpoint; the next invocation
    adopts that exact readback without replaying the side effect.
    """

    expected_digest = config.get("expected_state_sha256")
    if not isinstance(expected_digest, str):
        _fail("E_V240_STATE_CAS", "expected_state_sha256 is required")
    path, state, digest = _load_state_cas(state_path, expected_digest)
    _verify_frozen_git_identity(state)
    checkpoint_id = str(state.get("current_checkpoint"))
    if checkpoint_id == "CP18" and _close_capability is not _CLOSE_CAPABILITY:
        _fail(
            "E_V240_CLOSE_REQUIRED",
            "CP18 can only be executed by release.py close after live audit",
        )
    if allowed_checkpoints is not None and checkpoint_id not in allowed_checkpoints:
        _fail("E_V240_CHECKPOINT_ORDER", f"checkpoint {checkpoint_id} is not allowed for this command")
    checkpoint_number = int(checkpoint_id[2:])
    if 4 <= checkpoint_number <= 17:
        # All code-bearing gates and remote promotion calls must execute from
        # the exact clean candidate checkout.  Ignored docs/release evidence
        # remains allowed by Git, while any tracked or non-ignored untracked
        # checker drift fails before an operation can be adopted or replayed.
        _require_clean_candidate_checkout(state)
    if 12 <= checkpoint_number <= 17:
        # Recompute the full frozen public-surface receipt before every
        # checkpoint that observes or mutates GitHub.  CP12 is the first
        # public write; later stages cannot rely on a stale CP10 marker.
        _revalidate_canonical_release(state)
    requested = config.get("checkpoint_id")
    if requested is not None and requested != checkpoint_id:
        _fail("E_V240_CHECKPOINT_ORDER", f"expected {checkpoint_id}, got {requested}")
    checkpoint = state["checkpoints"].get(checkpoint_id)
    if not isinstance(checkpoint, dict) or checkpoint.get("status") == "passed":
        _fail("E_V240_CHECKPOINT_ORDER", f"checkpoint cannot be advanced: {checkpoint_id}")

    operations = checkpoint.get("operations")
    if not isinstance(operations, list):
        _fail("E_V240_STATE_OPERATION_PLAN", "checkpoint operations are missing")
    for operation in operations:
        _operation_authorization(operation, config)

    # Persist all intents before the first possible side effect.
    if checkpoint.get("status") == "pending":
        checkpoint["status"] = "in_progress"
        for operation in operations:
            operation["status"] = "in_progress"
        state["updated_at"] = _utc_now()
        digest = _atomic_state_write(path, state, expected_sha256=digest)

    external_effects = 0
    github_adapter: Any | None = None
    for index, operation in enumerate(operations):
        authorization = _operation_authorization(operation, config)
        operation_id = str(operation["operation_id"])
        intent = operation["intent"]
        action = str(intent["action"])
        parameters = authorization.get("parameters")
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, Mapping):
            _fail("E_V240_OPERATION_AUTHORIZATION", f"parameters are not an object: {operation_id}")
        parameters = dict(parameters)
        if action == "post_release_ci":
            if "_release_intent" in parameters:
                _fail("E_V240_CI_INTENT", "release intent is internal and cannot be supplied by the caller")
            release_intent = intent.get("idempotency_key")
            if not isinstance(release_intent, str) or SHA256_RE.fullmatch(release_intent) is None:
                _fail("E_V240_CI_INTENT", "persisted post-release operation idempotency key is invalid")
            parameters["_release_intent"] = release_intent
        mode = authorization.get("mode")
        existing = operation.get("readback")
        existing_receipt = operation.get("receipt_sha256")
        if (
            isinstance(existing, Mapping)
            and existing.get("classification") == "exact"
            and SHA256_RE.fullmatch(str(existing_receipt or "")) is not None
        ):
            expected_receipt = _canonical_json_sha256(
                {"intent": intent, "readback": existing}
            )
            if existing_receipt != expected_receipt:
                _fail("E_V240_OPERATION_READBACK", f"stored receipt drift: {operation_id}")
            existing_details = existing.get("details")
            if not isinstance(existing_details, Mapping):
                _fail("E_V240_OPERATION_READBACK", f"stored readback details missing: {operation_id}")
            if checkpoint_id == "CP14" and action == "github_authority_verify":
                observed_authority = existing_details.get("authority")
                binding = state.get("github_authority")
                if not isinstance(observed_authority, Mapping) or not isinstance(binding, Mapping):
                    _fail("E_V240_GITHUB_AUTHORITY_BINDING", "stored CP14 authority missing")
                validate_github_live_authority(observed_authority, binding)
            if checkpoint_id == "CP03" and action == "ruleset_capability_verify":
                observed_authority = existing_details.get("authority")
                if not isinstance(observed_authority, Mapping):
                    _fail("E_V240_GITHUB_AUTHORITY_BINDING", "stored CP03 authority missing")
                validate_github_live_authority(observed_authority, observed_authority)
            if operation_id not in LOCAL_OPERATION_IDS:
                if github_adapter is None:
                    github_adapter = _github_adapter_for_state(state, config)
                expected_before = intent.get("expected_before")
                if not isinstance(expected_before, Mapping):
                    _fail("E_V240_STATE_EXPECTED_BEFORE", f"stored external intent lacks expected-before: {operation_id}")
                try:
                    fresh_parameters = dict(parameters)
                    if action == "promotion_lock_finalize":
                        fresh_parameters["_post_mutation"] = True
                    fresh = github_adapter.observe(
                        operation_id=operation_id,
                        action=action,
                        expected_before=expected_before,
                        parameters=fresh_parameters,
                    )
                except Exception as exc:
                    receipt = getattr(exc, "receipt", None)
                    if isinstance(receipt, Mapping):
                        _fail(str(receipt.get("error_code", "E_V240_ADAPTER")), str(exc))
                    raise
                fresh_details = fresh.get("details")
                stored_identity = _critical_readback_identity(action, existing_details)
                fresh_identity = (
                    _critical_readback_identity(action, fresh_details)
                    if isinstance(fresh_details, Mapping)
                    else None
                )
                if checkpoint_id == "CP03" and action == "github_authority_verify":
                    def cp03_bootstrap_identity(value: Any) -> Any:
                        if not isinstance(value, Mapping):
                            return None
                        authority = value.get("authority")
                        if not isinstance(authority, Mapping):
                            return None
                        immutable_capability = authority.get("immutable_endpoint_capability")
                        ruleset_capability = authority.get("ruleset_capability")
                        return {
                            "actor_id": authority.get("actor_id"),
                            "actor_login": authority.get("actor_login"),
                            "repository_id": authority.get("repository_id"),
                            "repository_full_name": authority.get("repository_full_name"),
                            "permission": authority.get("permission"),
                            "authorized_external_actions": authority.get("authorized_external_actions"),
                            "immutable_read": immutable_capability.get("read") if isinstance(immutable_capability, Mapping) else None,
                            "immutable_enable": immutable_capability.get("enable") if isinstance(immutable_capability, Mapping) else None,
                            "ruleset": ruleset_capability,
                        }
                    stored_identity = cp03_bootstrap_identity(existing_details)
                    fresh_identity = cp03_bootstrap_identity(fresh_details)
                if (
                    fresh.get("classification") != "exact"
                    or not isinstance(fresh_details, Mapping)
                    or fresh_identity != stored_identity
                ):
                    _fail(
                        "E_V240_RECOVERY_STALE_READBACK",
                        f"fresh live identity differs from stored exact readback: {operation_id}",
                    )
            continue
        if operation_id in LOCAL_OPERATION_IDS:
            if mode != "execute_local":
                _fail("E_V240_OPERATION_AUTHORIZATION", f"local execution mode required: {operation_id}")
            readback = _execute_local_operation(
                operation_id, state, parameters, path
            )
        else:
            if mode not in {"observe", "execute_github"}:
                _fail("E_V240_OPERATION_AUTHORIZATION", f"GitHub adapter mode required: {operation_id}")
            if github_adapter is None:
                github_adapter = _github_adapter_for_state(state, config)
            expected_before = intent.get("expected_before")
            if not isinstance(expected_before, Mapping):
                _fail("E_V240_STATE_EXPECTED_BEFORE", f"GitHub operation lacks expected-before: {operation_id}")
            if action in {"draft_create", "release_publish"}:
                _validate_release_intent_metadata(
                    expected_before,
                    state.get("candidate_commit"),
                    require_release_id=action == "release_publish",
                )
            sealed_assets: dict[str, Any] | None = None
            if (
                checkpoint_id == "CP16"
                and action in {"draft_create", "asset_upload", "asset_download_verify"}
            ) or action in {"release_publish", "published_asset_download"}:
                sealed_assets = _revalidate_canonical_release(state)
                if expected_before.get("asset_set_sha256") != sealed_assets["asset_set_sha256"]:
                    _fail("E_V240_DRAFT_ASSET_IDENTITY", "operation asset-set binding differs from CP10")
                if expected_before.get("validator_receipt_sha256") != sealed_assets["validator_receipt_sha256"]:
                    _fail("E_V240_RELEASE_VALIDATION", "operation validator binding differs from CP10")
            if action == "asset_upload":
                asset_names = {
                    "CP16.asset_upload_tar": f"goal-teams-{state['version']}.tar.gz",
                    "CP16.asset_upload_sums": "SHA256SUMS",
                    "CP16.asset_upload_release": "_release.json",
                    "CP16.asset_upload_files": "_files.sha256",
                }
                name = asset_names.get(operation_id)
                expected_asset = (
                    sealed_assets.get("assets", {}).get(name)
                    if isinstance(sealed_assets, Mapping) and isinstance(name, str)
                    else None
                )
                if (
                    not isinstance(expected_asset, Mapping)
                    or expected_before.get("asset_sha256") != expected_asset.get("sha256")
                    or expected_before.get("asset_size") != expected_asset.get("size")
                ):
                    _fail("E_V240_DRAFT_ASSET_IDENTITY", f"upload intent differs from CP10 asset: {name}")
            if action == "release_publish":
                verified_draft = _operation_details(
                    state, "CP16", "CP16.asset_download_verify"
                )
                if (
                    expected_before.get("draft_asset_set_sha256")
                    != verified_draft.get("asset_set_sha256")
                    or expected_before.get("release_id")
                    != verified_draft.get("release_id")
                    or expected_before.get("candidate_commit")
                    != state.get("candidate_commit")
                    or expected_before.get("tag") != state.get("tag")
                    or sealed_assets is None
                    or expected_before.get("draft_asset_set_sha256")
                    != sealed_assets.get("asset_set_sha256")
                ):
                    _fail("E_V240_DRAFT_ASSET_IDENTITY", "publish intent is not bound to CP16 verified Draft")
            try:
                if mode == "observe":
                    readback = github_adapter.observe(
                        operation_id=operation_id,
                        action=action,
                        expected_before=expected_before,
                        parameters=parameters,
                    )
                else:
                    if recover_only and config.get("resume_external_writes") is not True:
                        _fail(
                            "E_V240_RECOVERY_WRITE_NOT_AUTHORIZED",
                            "recover requires resume_external_writes=true before replay",
                        )
                    readback = github_adapter.execute(
                        operation_id=operation_id,
                        action=action,
                        expected_before=expected_before,
                        parameters=parameters,
                    )
                    external_effects += int(readback.get("external_side_effect_count", 0))
            except Exception as exc:
                receipt = getattr(exc, "receipt", None)
                if isinstance(receipt, Mapping):
                    _fail(
                        str(receipt.get("error_code", "E_V240_ADAPTER")),
                        str(exc),
                        external_side_effect_count=receipt.get("external_side_effect_count", 0),
                    )
                raise
        if action in {"ci_wait", "post_release_ci"}:
            approval = intent.get("expected_before", {}).get("ci_approval")
            ci_receipt = readback.get("details", {}).get("ci_receipt")
            if not isinstance(approval, Mapping) or not isinstance(ci_receipt, Mapping):
                _fail("E_V240_CI_TRUST_BINDING", f"CI approval/live receipt missing: {operation_id}")
            if approval.get("required_jobs") != [
                "check-ubuntu",
                "check-macos",
                "release-asset-gate",
            ]:
                _fail("E_V240_CI_TRUST_BINDING", "CI approval does not use the fixed three-job contract")
            approved_at_cp05 = _operation_details(
                state, "CP05", "CP05.workflow_approve"
            ).get("ci_approval")
            if approval != approved_at_cp05:
                _fail("E_V240_CI_TRUST_BINDING", "CI intent differs from CP05 independent approval")
            _validate_ci_state_authority(state, approval, ci_receipt)
            checker_surface = _checker_surface_digest(str(state["candidate_commit"]))
            if (
                approval.get("checker_tree_sha256")
                != checker_surface["checker_tree_sha256"]
                or approval.get("checker_file_count")
                != checker_surface["checker_file_count"]
                or approval.get("public_scan_bindings")
                != _public_scan_trust_bindings(state)
            ):
                _fail("E_V240_CI_TRUST_BINDING", "CI checker trust root drift")
            validate_ci_receipt(ci_receipt, approval)
            expected_event = "push" if action == "ci_wait" else "workflow_dispatch"
            if (
                ci_receipt.get("event") != expected_event
                or not isinstance(ci_receipt.get("actor_id"), int)
                or ci_receipt.get("actor_id", 0) < 1
                or not isinstance(ci_receipt.get("triggering_actor_id"), int)
                or ci_receipt.get("triggering_actor_id", 0) < 1
                or not isinstance(ci_receipt.get("created_at"), str)
                or not isinstance(ci_receipt.get("run_id"), int)
                or not isinstance(ci_receipt.get("run_attempt"), int)
            ):
                _fail("E_V240_CI_TRUST_BINDING", "CI event/actor/run identity drift")
            if action == "post_release_ci":
                release_intent = intent.get("idempotency_key")
                expected_display_title = f"Goal Teams V2.40 release {release_intent}"
                if (
                    ci_receipt.get("release_intent") != release_intent
                    or ci_receipt.get("display_title") != expected_display_title
                ):
                    _fail("E_V240_CI_INTENT", "post-release CI intent/title identity drift")
                published_at = _operation_details(
                    state, "CP17", "CP17.release_publish"
                ).get("publishedAt")
                run_created = _parse_utc(
                    ci_receipt.get("created_at"), "E_V240_POST_RELEASE_CI"
                )
                if (
                    run_created
                    <= _parse_utc(published_at, "E_V240_POST_RELEASE_CI")
                    or run_created
                    <= _parse_utc(intent.get("created_at"), "E_V240_POST_RELEASE_CI")
                ):
                    _fail(
                        "E_V240_POST_RELEASE_CI",
                        "post-release CI run does not postdate publish and its intent",
                    )
            ci_run = {
                "stage": "candidate" if action == "ci_wait" else "post_release",
                "workflow_path": ci_receipt["workflow_path"],
                "workflow_blob_sha": ci_receipt["workflow_blob_sha"],
                "workflow_approval_sha256": _canonical_json_sha256(approval),
                "workflow_id": ci_receipt["workflow_id"],
                "run_id": ci_receipt["run_id"],
                "run_attempt": ci_receipt["run_attempt"],
                "event": ci_receipt.get("event"),
                "actor_id": ci_receipt.get("actor_id"),
                "triggering_actor_id": ci_receipt.get("triggering_actor_id"),
                "head_sha": ci_receipt["head_sha"],
                "jobs": copy.deepcopy(ci_receipt["jobs"]),
                "created_at": ci_receipt.get("created_at"),
                **(
                    {
                        "release_intent": ci_receipt.get("release_intent"),
                        "display_title": ci_receipt.get("display_title"),
                    }
                    if action == "post_release_ci"
                    else {}
                ),
            }
            readback = copy.deepcopy(dict(readback))
            readback["details"]["ci_run"] = ci_run
            readback["state_sha256"] = _canonical_json_sha256(readback["details"])
        if action in {"asset_download_verify", "published_asset_download"}:
            sealed = _revalidate_canonical_release(state)
            downloaded_details = readback.get("details")
            if (
                not isinstance(downloaded_details, Mapping)
                or downloaded_details.get("asset_set_sha256")
                != sealed["asset_set_sha256"]
            ):
                _fail("E_V240_DRAFT_ASSET_IDENTITY", "downloaded asset set differs from CP10 seal")
        if readback.get("classification") != "exact":
            _fail(
                "E_V240_OPERATION_NOT_EXACT",
                f"live state is {readback.get('classification')}: {operation_id}",
            )
        digest = _persist_operation_readback(
            path, state, checkpoint_id, index, readback, digest
        )
        if (
            checkpoint_id == "CP03"
            and action == "github_authority_verify"
            and github_adapter is not None
        ):
            bootstrapped = readback.get("details", {}).get("authority")
            if not isinstance(bootstrapped, Mapping):
                _fail("E_V240_GITHUB_AUTHORITY_BINDING", "CP03 authority bootstrap readback missing")
            github_adapter.authority = copy.deepcopy(dict(bootstrapped))
        if (
            checkpoint_id == "CP03"
            and action == "immutable_release_enable"
            and github_adapter is not None
        ):
            enabled_authority = readback.get("details", {}).get("authority")
            if not isinstance(enabled_authority, Mapping):
                _fail("E_V240_GITHUB_AUTHORITY_BINDING", "post-enable authority readback missing")
            validate_github_live_authority(enabled_authority, enabled_authority)
            github_adapter.authority = copy.deepcopy(dict(enabled_authority))
        if action == "github_authority_verify" and checkpoint_id == "CP14":
            live_authority = readback.get("details", {}).get("authority")
            binding = state.get("github_authority")
            if not isinstance(live_authority, Mapping) or not isinstance(binding, Mapping):
                _fail("E_V240_GITHUB_AUTHORITY_BINDING", "CP14 authority binding missing")
            validate_github_live_authority(live_authority, binding)
        if action == "ruleset_capability_verify" and checkpoint_id == "CP03":
            final_authority = readback.get("details", {}).get("authority")
            if not isinstance(final_authority, Mapping):
                _fail("E_V240_GITHUB_AUTHORITY_BINDING", "CP03 final authority readback missing")
            validate_github_live_authority(final_authority, final_authority)

    if checkpoint_id == "CP09":
        build_digests = {
            operation.get("readback", {}).get("details", {}).get("tree_sha256")
            for operation in operations
        }
        if len(build_digests) != 1 or None in build_digests:
            _fail("E_V240_BUILD_REPRODUCIBILITY", "isolated build receipts differ")

    if config.get("state_updates") not in (None, {}):
        _fail(
            "E_V240_STATE_UPDATE",
            "caller-supplied authority/lock/identity/CI state is forbidden",
        )
    derived_updates = _derive_checkpoint_state_updates(state, checkpoint_id)
    if set(derived_updates) - STATE_UPDATE_FIELDS.get(checkpoint_id, set()):
        _fail("E_V240_STATE_DERIVATION", f"uncontracted derived state at {checkpoint_id}")
    for field, value in derived_updates.items():
        state[field] = copy.deepcopy(value)

    completed_at = _utc_now()
    for operation in operations:
        operation["status"] = "passed"
        operation["completed_at"] = completed_at
    checkpoint["status"] = "passed"
    checkpoint["completed_at"] = completed_at
    checkpoint["receipt_sha256"] = _canonical_json_sha256(
        [operation["receipt_sha256"] for operation in operations]
    )
    _append_next_checkpoint(state, checkpoint_id, config)
    schema = _load_promotion_schema()
    phase_map = schema["x-semantic-validator"]["checkpoint_phase_after_pass"]
    state["phase"] = phase_map[checkpoint_id]
    checkpoint_number = int(checkpoint_id[2:])
    state["current_checkpoint"] = (
        "CP18" if checkpoint_number == 18 else f"CP{checkpoint_number + 1:02d}"
    )
    state["updated_at"] = completed_at
    validate_promotion_state(state)
    digest = _atomic_state_write(path, state, expected_sha256=digest)
    return _success(
        command="recover" if recover_only else "promote",
        checkpoint=checkpoint_id,
        next_checkpoint=state["current_checkpoint"],
        phase=state["phase"],
        state_path=str(path),
        state_sha256=digest,
        mutation_count=2 + len(operations),
        external_side_effect_count=external_effects,
    )


def prepare_release(config: Mapping[str, Any]) -> dict[str, Any]:
    """Build twice, validate, seal, and persist CP09/CP10 receipts."""

    path = _initialize_state_from_input(config)
    expected = config.get("expected_state_sha256")
    if expected is None:
        expected = _file_digest_or_none(path)
    if not isinstance(expected, str):
        _fail("E_V240_STATE_CAS", "cannot bind prepared state")
    receipts: list[dict[str, Any]] = []
    while True:
        _, state, actual = _load_state_cas(path, expected)
        current = str(state["current_checkpoint"])
        if current not in LOCAL_PREPARE_CHECKPOINTS:
            break
        operations = state["checkpoints"][current]["operations"]
        local_config = dict(config)
        local_config["expected_state_sha256"] = actual
        local_config["checkpoint_id"] = current
        local_config["operation_authorizations"] = {
            operation["operation_id"]: {
                "intent_sha256": _canonical_json_sha256(operation["intent"]),
                "expected_before": operation["intent"].get("expected_before"),
                "mode": "execute_local",
                "parameters": {},
            }
            for operation in operations
        }
        receipt = execute_current_checkpoint(
            path, local_config, allowed_checkpoints=LOCAL_PREPARE_CHECKPOINTS
        )
        receipts.append(receipt)
        expected = receipt["state_sha256"]
    if not receipts:
        _fail("E_V240_CHECKPOINT_ORDER", "prepare requires current CP09 or CP10")
    return _success(
        command="prepare",
        state_path=str(path),
        state_sha256=expected,
        completed_checkpoints=[receipt["checkpoint"] for receipt in receipts],
        next_checkpoint=receipts[-1]["next_checkpoint"],
        mutation_count=sum(int(receipt["mutation_count"]) for receipt in receipts),
        external_side_effect_count=0,
    )


def close_release(config: Mapping[str, Any]) -> dict[str, Any]:
    """Run the independent audit gate, then close CP18 through the same CAS."""

    state_path = config.get("state_path")
    if not isinstance(state_path, str):
        _fail("E_V240_CLI_INPUT", "state_path is required")
    loaded_path, state, _ = _load_state_cas(
        state_path,
        config.get("expected_state_sha256")
        if isinstance(config.get("expected_state_sha256"), str)
        else None,
    )
    workspace = _workspace_root()
    if not _path_is_within(loaded_path, workspace / "docs"):
        _fail(
            "E_V240_CLOSE_FINALIZER",
            "close state must survive candidate removal under canonical root docs/",
        )
    observation = collect_live_audit_observation(state)
    audit_receipt = _run_independent_audit(observation)
    stored_audit = _operation_details(
        state, "CP17", "CP17.independent_audit"
    ).get("audit_receipt")
    if not isinstance(stored_audit, Mapping) or not isinstance(
        stored_audit.get("goal_teams_work_tree"), Mapping
    ):
        _fail("E_V240_CLOSE_AUDIT", "pre-removal GoalTeamsWork audit binding is missing")
    fresh_base = dict(audit_receipt)
    fresh_base.pop("receipt_sha256", None)
    stored_base = dict(stored_audit)
    stored_base.pop("receipt_sha256", None)
    stored_tree = stored_base.pop("goal_teams_work_tree", None)
    if fresh_base != stored_base:
        _fail("E_V240_CLOSE_AUDIT", "fresh close audit differs from CP17 audit facts")
    audit_receipt["goal_teams_work_tree"] = copy.deepcopy(stored_tree)
    audit_receipt.pop("receipt_sha256", None)
    audit_receipt["receipt_sha256"] = _canonical_json_sha256(audit_receipt)
    close_boundary_receipt = _validate_close_local_boundary(
        state, audit_receipt, config
    )
    adapter = _github_adapter_for_state(state, {"execute_external_writes": False})
    immutable = adapter.observe(
        operation_id="CP14.immutable_release_verify",
        action="immutable_release_verify",
        expected_before=_checkpoint_operation(
            state, "CP14", "CP14.immutable_release_verify"
        )["intent"]["expected_before"],
        parameters={},
    )
    tag_ruleset_details = _operation_details(state, "CP14", "CP14.tag_ruleset")
    stored_ruleset = tag_ruleset_details.get("ruleset")
    if not isinstance(stored_ruleset, Mapping) or not isinstance(stored_ruleset.get("name"), str):
        _fail("E_V240_TAG_RULESET", "tag ruleset receipt missing")
    live_ruleset = adapter._ruleset_by_name(stored_ruleset["name"])
    normalize_ruleset = _load_github_adapter().normalize_ruleset
    if (
        not isinstance(live_ruleset, Mapping)
        or normalize_ruleset(live_ruleset) != normalize_ruleset(stored_ruleset)
    ):
        _fail("E_V240_TAG_RULESET", "live tag ruleset differs from frozen receipt")
    adapter._validate_ruleset_payload("tag_ruleset_create", live_ruleset)
    rule_types = {rule.get("type") for rule in normalize_ruleset(live_ruleset)["rules"]}
    live_release = adapter._release_json()
    remote_immutability = {
        "immutable_release_enabled": immutable.get("classification") == "exact",
        "release_state": "published",
        "release_immutable": isinstance(live_release, Mapping)
        and live_release.get("isImmutable") is True,
        "tag_ruleset_active": live_ruleset.get("enforcement") == "active",
        "tag_update_allowed": "update" not in rule_types,
        "tag_deletion_allowed": "deletion" not in rule_types,
    }
    validate_remote_immutability(remote_immutability)
    if state.get("current_checkpoint") != "CP18" or state.get("phase") != "INSTALLED_VERIFIED":
        _fail("E_V240_CHECKPOINT_ORDER", "close requires CP17 INSTALLED_VERIFIED")
    checkpoint = state["checkpoints"]["CP18"]
    authorizations = config.get("operation_authorizations")
    if not isinstance(authorizations, Mapping):
        _fail("E_V240_OPERATION_AUTHORIZATION", "CP18 authorizations are required")
    amended = copy.deepcopy(dict(config))
    amended_authorizations = copy.deepcopy(dict(authorizations))
    archive = amended_authorizations.get("CP18.archive_close")
    if not isinstance(archive, dict):
        _fail("E_V240_OPERATION_AUTHORIZATION", "archive close authorization is missing")
    parameters = archive.setdefault("parameters", {})
    if not isinstance(parameters, dict):
        _fail("E_V240_OPERATION_AUTHORIZATION", "archive close parameters are invalid")
    parameters["audit_receipt"] = audit_receipt
    parameters["close_boundary_receipt"] = close_boundary_receipt
    archive_index_path = config.get("archive_index_path")
    if not isinstance(archive_index_path, str):
        _fail("E_V240_CLOSE_ARCHIVE", "close archive index is required")
    parameters["archive_index_path"] = archive_index_path
    amended["operation_authorizations"] = amended_authorizations
    receipt = execute_current_checkpoint(
        state_path,
        amended,
        allowed_checkpoints={"CP18"},
        _close_capability=_CLOSE_CAPABILITY,
    )
    receipt["command"] = "close"
    receipt["audit_receipt_sha256"] = _canonical_json_sha256(audit_receipt)
    receipt["release_state"] = "closed"
    return receipt


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Goal Teams V2.40 single release entry. Policy commands never "
            "infer or fabricate external GitHub success."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("start", "create the immutable state and execute CP00 scope freeze"),
        ("doctor", "collect and validate live canonical workspace topology"),
        ("prepare", "prepare a frozen local release candidate"),
        ("promote", "promote under an authenticated live adapter"),
        ("status", "observe promotion state without mutation"),
        ("recover", "reconcile intent with live readback"),
        ("close", "close only after independent live audit"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--input",
            type=Path,
            required=True,
            help=(
                "JSON command envelope or observation input; external writes "
                "also require per-operation authorization and environment opt-in"
            ),
        )
    return parser


def _load_cli_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        _fail("E_V240_CLI_INPUT", "CLI input must be a JSON object")
    return value


def _status_from_config(config: Mapping[str, Any]) -> dict[str, Any]:
    state_path = config.get("state_path")
    if not isinstance(state_path, str):
        _fail("E_V240_CLI_INPUT", "status requires state_path")
    expected = config.get("expected_state_sha256")
    if expected is not None and not isinstance(expected, str):
        _fail("E_V240_STATE_CAS", "expected_state_sha256 is invalid")
    path, state, digest = _load_state_cas(state_path, expected)
    resume = plan_resume(path)
    return _success(
        command="status",
        state_path=str(path),
        state_sha256=digest,
        phase=state["phase"],
        current_checkpoint=state["current_checkpoint"],
        next_checkpoint=resume["next_checkpoint"],
        actions=resume["actions"],
        skip_side_effects=resume["skip_side_effects"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = _load_cli_object(args.input)
        if args.command == "start":
            result = start_release(config)
        elif args.command == "doctor":
            result = doctor_release(config)
        elif args.command == "prepare":
            result = prepare_release(config)
        elif args.command == "promote":
            state_path = config.get("state_path")
            if not isinstance(state_path, str):
                _fail("E_V240_CLI_INPUT", "promote requires state_path")
            result = execute_current_checkpoint(state_path, config)
            result["command"] = "promote"
        elif args.command == "status":
            result = _status_from_config(config)
        elif args.command == "recover":
            state_path = config.get("state_path")
            if not isinstance(state_path, str):
                _fail("E_V240_CLI_INPUT", "recover requires state_path")
            result = execute_current_checkpoint(
                state_path, config, recover_only=True
            )
            result["command"] = "recover"
        elif args.command == "close":
            result = close_release(config)
        else:  # argparse prevents this; retain a fail-closed boundary.
            _fail("E_V240_CLI_INPUT", f"unknown release command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except PolicyError as exc:
        print(json.dumps(exc.receipt, ensure_ascii=False, sort_keys=True))
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        receipt = PolicyError("E_V240_CLI_INPUT", str(exc)).receipt
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        attached = getattr(exc, "receipt", None)
        if isinstance(attached, Mapping):
            print(json.dumps(dict(attached), ensure_ascii=False, sort_keys=True))
        else:
            receipt = PolicyError(
                "E_V240_CLI_INTERNAL", f"{type(exc).__name__}: {exc}"
            ).receipt
            print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
