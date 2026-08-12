"""Capture Git-observed V2.63 scope changes against an owned dirty baseline."""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Mapping, Sequence


class GitChangeError(RuntimeError):
    """Git evidence is incomplete, ambiguous, or outside the locked scope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _git(repo: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace").strip()
        raise GitChangeError("E_V263_GIT_COMMAND", str(detail or exc)) from exc


def _repo_root(repo_root: Path | str) -> Path:
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise GitChangeError("E_V263_GIT_REPO", "repository root is not a directory")
    observed = _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    if Path(observed).resolve() != root:
        raise GitChangeError("E_V263_GIT_REPO", "repository root must be the Git top level")
    return root


def _safe_relative_path(value: str) -> str:
    normalized = value.replace(os.sep, "/")
    parts = normalized.split("/")
    if not normalized or normalized.startswith("/") or ".." in parts or "." in parts:
        raise GitChangeError("E_V263_GIT_PATH", f"unsafe Git path: {value}")
    return normalized


def _content_sha256(root: Path, relative: str) -> str | None:
    target = root / relative
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(mode):
        raw = os.readlink(target).encode("utf-8", errors="surrogateescape")
    elif stat.S_ISREG(mode):
        raw = target.read_bytes()
    else:
        raise GitChangeError("E_V263_GIT_FILE_TYPE", f"unsupported changed path: {relative}")
    return hashlib.sha256(raw).hexdigest()


def _filesystem_mode(root: Path, relative: str) -> str | None:
    try:
        mode = (root / relative).lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(mode):
        return "120000"
    if stat.S_ISREG(mode):
        return "100755" if mode & stat.S_IXUSR else "100644"
    return None


def _raw_diff_entries(root: Path, base_commit: str) -> list[dict[str, Any]]:
    raw = _git(
        root,
        "diff",
        "--raw",
        "--no-abbrev",
        "-z",
        "--find-renames",
        base_commit,
        "--",
    )
    tokens = raw.split(b"\0")
    entries: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(tokens) and tokens[cursor]:
        header = tokens[cursor].decode("ascii", errors="strict")
        cursor += 1
        fields = header.split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise GitChangeError("E_V263_GIT_DIFF_PARSE", f"invalid raw diff header: {header}")
        old_mode = fields[0][1:]
        new_mode = fields[1]
        old_blob = fields[2]
        new_blob = fields[3]
        status_token = fields[4]
        status_code = status_token[0]
        if cursor >= len(tokens) or not tokens[cursor]:
            raise GitChangeError("E_V263_GIT_DIFF_PARSE", "raw diff path is missing")
        first_path = _safe_relative_path(
            tokens[cursor].decode("utf-8", errors="surrogateescape")
        )
        cursor += 1
        old_path: str | None = None
        path = first_path
        if status_code in {"R", "C"}:
            if cursor >= len(tokens) or not tokens[cursor]:
                raise GitChangeError("E_V263_GIT_DIFF_PARSE", "rename target is missing")
            old_path = first_path
            path = _safe_relative_path(
                tokens[cursor].decode("utf-8", errors="surrogateescape")
            )
            cursor += 1
        if status_code == "C":
            status_code = "A"
        if status_code not in {"M", "A", "D", "R", "T", "U"}:
            raise GitChangeError(
                "E_V263_GIT_STATUS", f"unsupported Git status: {status_token}"
            )
        entry: dict[str, Any] = {
            "status": status_code,
            "path": path,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "mode_changed": old_mode != new_mode,
            "old_blob": old_blob,
            "new_blob": new_blob,
            "content_sha256": _content_sha256(root, path),
        }
        if old_path is not None:
            entry["old_path"] = old_path
            entry["similarity"] = int(status_token[1:] or "0")
        entries.append(entry)
    return entries


def _untracked_entries(root: Path) -> list[dict[str, Any]]:
    raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--")
    result: list[dict[str, Any]] = []
    for token in raw.split(b"\0"):
        if not token:
            continue
        relative = _safe_relative_path(token.decode("utf-8", errors="surrogateescape"))
        result.append(
            {
                "status": "UNTRACKED",
                "path": relative,
                "old_mode": None,
                "new_mode": _filesystem_mode(root, relative),
                "mode_changed": False,
                "old_blob": None,
                "new_blob": None,
                "content_sha256": _content_sha256(root, relative),
            }
        )
    return result


def _working_entries(root: Path, base_commit: str) -> list[dict[str, Any]]:
    entries = _raw_diff_entries(root, base_commit) + _untracked_entries(root)
    entries.sort(key=lambda item: (item["path"], item["status"], item.get("old_path", "")))
    return entries


def _entry_comparison_value(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in entry.items() if key != "owner"}


def capture_git_baseline(
    repo_root: Path | str, *, dirty_owners: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Freeze commit/tree plus every pre-existing tracked or untracked change."""

    root = _repo_root(repo_root)
    base_commit = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    base_tree = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    entries = _working_entries(root, base_commit)
    owners = dict(dirty_owners or {})
    if any(not isinstance(owner, str) or not owner.strip() for owner in owners.values()):
        raise GitChangeError("E_V263_GIT_DIRTY_OWNER", "dirty baseline owners must be non-empty")
    dirty_paths = {entry["path"] for entry in entries}
    missing_owners = sorted(dirty_paths - set(owners))
    extra_owners = sorted(set(owners) - dirty_paths)
    if missing_owners:
        raise GitChangeError(
            "E_V263_GIT_DIRTY_OWNER",
            "dirty baseline paths require owners: " + ", ".join(missing_owners),
        )
    if extra_owners:
        raise GitChangeError(
            "E_V263_GIT_DIRTY_OWNER",
            "owners reference clean paths: " + ", ".join(extra_owners),
        )
    owned_entries: list[dict[str, Any]] = []
    for entry in entries:
        owned = copy.deepcopy(entry)
        owned["owner"] = owners[entry["path"]]
        owned_entries.append(owned)
    baseline: dict[str, Any] = {
        "schema_version": "goal-teams-git-baseline-v1",
        "base_commit": base_commit,
        "base_tree": base_tree,
        "initial_tracked_diff": [
            copy.deepcopy(entry) for entry in owned_entries if entry["status"] != "UNTRACKED"
        ],
        "initial_untracked_exact_set": sorted(
            entry["path"] for entry in owned_entries if entry["status"] == "UNTRACKED"
        ),
        "dirty_entries": owned_entries,
    }
    baseline["baseline_digest"] = _canonical_digest(baseline)
    return baseline


def _path_matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return fnmatch.fnmatchcase(path, pattern)


def _normalize_task_scopes(
    value: Mapping[str, Any],
) -> dict[str, dict[str, list[str]]]:
    if not isinstance(value, Mapping) or not value:
        raise GitChangeError("E_V263_GIT_SCOPES", "task scopes are required")
    result: dict[str, dict[str, list[str]]] = {}
    for task_id, declared in value.items():
        if isinstance(declared, Mapping):
            patterns = declared.get("scope_allowlist")
            forbidden = declared.get("forbidden_scope", [])
        else:
            patterns = declared
            forbidden = []
        if (
            not isinstance(task_id, str)
            or not task_id
            or not isinstance(patterns, Sequence)
            or isinstance(patterns, (str, bytes))
            or not patterns
            or not all(isinstance(pattern, str) and pattern for pattern in patterns)
        ):
            raise GitChangeError("E_V263_GIT_SCOPES", f"invalid scope for task {task_id}")
        if (
            not isinstance(forbidden, Sequence)
            or isinstance(forbidden, (str, bytes))
            or not all(isinstance(pattern, str) and pattern for pattern in forbidden)
        ):
            raise GitChangeError(
                "E_V263_GIT_SCOPES", f"invalid forbidden scope for task {task_id}"
            )
        for pattern in (*patterns, *forbidden):
            _safe_relative_path(pattern.replace("*", "x"))
        result[task_id] = {
            "scope_allowlist": list(patterns),
            "forbidden_scope": list(forbidden),
        }
    return result


def _attribute_entry(
    entry: Mapping[str, Any], scopes: Mapping[str, Mapping[str, Sequence[str]]]
) -> str:
    paths = [entry["path"]]
    if entry.get("old_path"):
        paths.append(entry["old_path"])
    candidates: list[str] = []
    forbidden_hits: list[str] = []
    for task_id, policy in scopes.items():
        allowed = policy["scope_allowlist"]
        forbidden = policy["forbidden_scope"]
        if not all(any(_path_matches(path, pattern) for pattern in allowed) for path in paths):
            continue
        if any(any(_path_matches(path, pattern) for pattern in forbidden) for path in paths):
            forbidden_hits.append(task_id)
            continue
        candidates.append(task_id)
    if not candidates:
        if forbidden_hits:
            raise GitChangeError(
                "E_V263_GIT_FORBIDDEN_SCOPE",
                "changed path is explicitly forbidden: "
                + ", ".join(paths)
                + " -> "
                + ", ".join(sorted(forbidden_hits)),
            )
        raise GitChangeError(
            "E_V263_GIT_SCOPE_DRIFT",
            "changed path is outside every task scope: " + ", ".join(paths),
        )
    if len(candidates) > 1:
        raise GitChangeError(
            "E_V263_GIT_MULTI_TASK",
            "changed path maps to multiple tasks: "
            + ", ".join(paths)
            + " -> "
            + ", ".join(sorted(candidates)),
        )
    return candidates[0]


def _synthetic_baseline_change(
    root: Path, baseline_entry: Mapping[str, Any]
) -> dict[str, Any]:
    relative = baseline_entry["path"]
    content_digest = _content_sha256(root, relative)
    mode = _filesystem_mode(root, relative)
    return {
        "status": "M" if content_digest is not None else "D",
        "path": relative,
        "old_mode": baseline_entry.get("new_mode"),
        "new_mode": mode,
        "mode_changed": baseline_entry.get("new_mode") != mode,
        "old_blob": baseline_entry.get("new_blob"),
        "new_blob": None,
        "content_sha256": content_digest,
        "dirty_baseline_changed": True,
    }


def compile_git_change_receipt(
    repo_root: Path | str,
    baseline: Mapping[str, Any],
    task_scopes: Mapping[str, Any],
) -> dict[str, Any]:
    """Collect current Git state, subtract unchanged dirty baseline, and gate scope."""

    root = _repo_root(repo_root)
    if not isinstance(baseline, Mapping) or baseline.get("schema_version") != "goal-teams-git-baseline-v1":
        raise GitChangeError("E_V263_GIT_BASELINE", "invalid Git baseline")
    expected_digest = _canonical_digest(
        {key: copy.deepcopy(value) for key, value in baseline.items() if key != "baseline_digest"}
    )
    if baseline.get("baseline_digest") != expected_digest:
        raise GitChangeError("E_V263_GIT_BASELINE_DIGEST", "Git baseline digest differs")
    base_commit = baseline.get("base_commit")
    if not isinstance(base_commit, str) or len(base_commit) != 40:
        raise GitChangeError("E_V263_GIT_BASELINE", "base_commit is invalid")
    scopes = _normalize_task_scopes(task_scopes)
    current_entries = _working_entries(root, base_commit)
    baseline_entries = baseline.get("dirty_entries")
    if not isinstance(baseline_entries, list):
        raise GitChangeError("E_V263_GIT_BASELINE", "dirty_entries are missing")
    baseline_by_path = {entry["path"]: entry for entry in baseline_entries}
    current_by_path = {entry["path"]: entry for entry in current_entries}
    changes: list[dict[str, Any]] = []
    for relative, current in current_by_path.items():
        initial = baseline_by_path.get(relative)
        if initial is None or _entry_comparison_value(initial) != _entry_comparison_value(current):
            changes.append(copy.deepcopy(current))
    for relative, initial in baseline_by_path.items():
        if relative not in current_by_path:
            changes.append(_synthetic_baseline_change(root, initial))
    changes.sort(key=lambda item: (item["path"], item["status"], item.get("old_path", "")))
    attributed: list[dict[str, Any]] = []
    for entry in changes:
        item = copy.deepcopy(entry)
        item["task_id"] = _attribute_entry(item, scopes)
        attributed.append(item)
    observed_head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    observed_tree = _git(root, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    working_state_sha256 = _canonical_digest(
        {
            "base_commit": base_commit,
            "observed_head": observed_head,
            "observed_head_tree": observed_tree,
            "working_entries": current_entries,
        }
    )
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-git-change-receipt-v1",
        "baseline_digest": baseline["baseline_digest"],
        "base_commit": base_commit,
        "base_tree": baseline.get("base_tree"),
        "observed_head": observed_head,
        "observed_tree": observed_tree,
        "working_state_sha256": working_state_sha256,
        "changes": attributed,
        "change_count": len(attributed),
        "changed_paths": sorted(
            {
                path
                for item in attributed
                for path in (item["path"], item.get("old_path"))
                if path is not None
            }
        ),
        "scope_gate": "passed",
        "attribution_complete": True,
    }
    receipt["receipt_digest"] = _canonical_digest(receipt)
    return receipt


__all__ = [
    "GitChangeError",
    "capture_git_baseline",
    "compile_git_change_receipt",
]
