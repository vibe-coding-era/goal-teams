#!/usr/bin/env python3
"""Deterministic public-release scanner for Goal Teams V2.40.

The scanner is deliberately independent from the release state machine.  It
accepts only immutable Git identities, an already materialized package
snapshot, the fixed four public assets, canonical release text, a reviewed
false-positive baseline, and the expected scanner blob digest.  Its receipt
contains no wall-clock fields or local absolute paths.
"""

from __future__ import annotations

import ast
import hashlib
import gzip
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import tokenize
import types
import unicodedata
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


def _require_python_311(version_info: Sequence[int] | None = None) -> None:
    import sys

    observed = sys.version_info if version_info is None else version_info
    if tuple(observed[:2]) < (3, 11):
        raise SystemExit("E_PUBLIC_SCAN_PYTHON: Python 3.11+ required")


_require_python_311()


SCHEMA_VERSION = "goal-teams-public-scan-receipt-v2"
BASELINE_SCHEMA_VERSION = "goal-teams-public-scan-baseline-v2"
OKF_GENERATED_PATH = "references/okf-conformance-manifest.json"
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
FINDING_KINDS = frozenset({"secret", "absolute_home", "private_provenance"})
BASELINE_REASONS = frozenset(
    {
        "detector_literal",
        "protocol_vocabulary",
        "synthetic_fixture",
    }
)
ASSERTION_FIELDS = frozenset(
    {
        "path",
        "file_sha256",
        "detector_id",
        "kind",
        "occurrence_id",
        "occurrence_set_sha256",
        "reason",
    }
)
REVIEW_FIELDS = frozenset(
    {
        "reviewer_type",
        "independent",
        "decision",
        "review_id",
        "reviewer_member_id",
        "reviewer_run_id",
        "reviewed_at",
        "assertion_set_sha256",
        "occurrence_set_sha256",
    }
)
DETECTOR_LITERAL_PATHS = frozenset(
    {
        "scripts/release/public_scan.py",
        "scripts/v23/v236_security.py",
        "scripts/v23/v236_trust.py",
        "tests/v23/test_distribution_security.py",
        "tests/v23/test_v236_security_redaction.py",
        "tests/v23/test_v240_public_scan.py",
    }
)
SYNTHETIC_FIXTURE_PATHS = frozenset(
    {
        "scripts/checks/check-security-fixtures.py",
        "scripts/v23/goalteams_v23.py",
    }
)
SNAPSHOT_OUTER_PATHS = frozenset(
    {
        "_release.json",
        "_files.sha256",
        "_artifacts/SHA256SUMS",
    }
)
PRIVATE_PROVENANCE_RE = re.compile(
    r"(?i)(?:\btool_call\b|\btransport_handle\b|\braw_log\b|"
    r"\bspawn_agent\b|(?:^|[/\\])\.netrc\b)"
)
MAX_GIT_OBJECT_BYTES = 16 * 1024 * 1024
MAX_GIT_SCAN_BYTES = 256 * 1024 * 1024
MAX_SNAPSHOT_FILE_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_TAR_STREAM_BYTES = MAX_SNAPSHOT_BYTES + 32 * 1024 * 1024
TAR_LIMITS = {
    "member_count": 2048,
    "max_path_bytes": 240,
    "max_single_file_bytes": 16 * 1024 * 1024,
    "max_total_uncompressed_bytes": 128 * 1024 * 1024,
    "max_compression_ratio": 100,
}
_GOAL_TEAMS_FROZEN_SCANNER_SOURCE_BYTES = globals().get(
    "_GOAL_TEAMS_FROZEN_SCANNER_SOURCE_BYTES"
)
_IMPORTED_SCANNER_BLOB_SHA256: str | None = None
_SAFE_GIT_ENV = {
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_NO_LAZY_FETCH": "1",
}
_INERT_GIT_ENV = frozenset({"GIT_PAGER"})


class PublicScanError(RuntimeError):
    """Fail-closed scanner error with a stable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message or 'public scan rejected input'}")


def _fail(code: str, message: str = "") -> None:
    raise PublicScanError(code, message)


if (
    _GOAL_TEAMS_FROZEN_SCANNER_SOURCE_BYTES is not None
    and type(_GOAL_TEAMS_FROZEN_SCANNER_SOURCE_BYTES) is not bytes
):
    _fail(
        "E_PUBLIC_SCAN_CHECKER_DIGEST",
        "injected frozen scanner source is not immutable bytes",
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _occurrence_identity_row(value: Mapping[str, Any]) -> dict[str, str]:
    """Return the closed identity surface shared by findings and assertions."""

    fields = (
        "path",
        "file_sha256",
        "detector_id",
        "kind",
        "occurrence_id",
        "occurrence_set_sha256",
    )
    row: dict[str, str] = {}
    for field in fields:
        item = value.get(field)
        if not isinstance(item, str):
            _fail("E_PUBLIC_SCAN_OCCURRENCE_SCHEMA", f"{field} is not a string")
        row[field] = item
    return row


def occurrence_set_sha256(occurrences: Sequence[Mapping[str, Any]]) -> str:
    """Hash an exact, order-independent set of occurrence identities."""

    rows = [_occurrence_identity_row(item) for item in occurrences]
    rows.sort(
        key=lambda item: (
            item["path"],
            item["file_sha256"],
            item["detector_id"],
            item["kind"],
            item["occurrence_id"],
            item["occurrence_set_sha256"],
        )
    )
    if len({_canonical_bytes(item) for item in rows}) != len(rows):
        _fail("E_PUBLIC_SCAN_OCCURRENCE_DUPLICATE", "duplicate occurrence identity")
    return _canonical_sha256(rows)


def assertion_set_sha256(assertions: Sequence[Mapping[str, Any]]) -> str:
    """Hash normalized reviewed assertions, including each review reason."""

    rows: list[dict[str, str]] = []
    for assertion in assertions:
        row = _occurrence_identity_row(assertion)
        reason = assertion.get("reason")
        if not isinstance(reason, str):
            _fail("E_PUBLIC_SCAN_BASELINE_REASON", "assertion reason is not a string")
        row["reason"] = reason
        rows.append(row)
    rows.sort(
        key=lambda item: (
            item["path"],
            item["file_sha256"],
            item["detector_id"],
            item["kind"],
            item["occurrence_id"],
            item["occurrence_set_sha256"],
            item["reason"],
        )
    )
    if len({_canonical_bytes(item) for item in rows}) != len(rows):
        _fail("E_PUBLIC_SCAN_BASELINE_DUPLICATE", "duplicate assertion")
    return _canonical_sha256(rows)


def receipt_hash(receipt: Mapping[str, Any]) -> str:
    """Hash a receipt without trusting or recursively hashing its hash field."""

    value = dict(receipt)
    value.pop("receipt_sha256", None)
    return _canonical_sha256(value)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _fail("E_PUBLIC_SCAN_BASELINE_JSON", f"duplicate key: {key}")
        value[key] = item
    return value


def load_baseline(baseline_bytes: bytes) -> dict[str, Any]:
    """Load baseline bytes with duplicate-key and encoding rejection."""

    if not isinstance(baseline_bytes, bytes):
        _fail("E_PUBLIC_SCAN_BASELINE_BYTES", "baseline must be bytes")
    if not baseline_bytes or not baseline_bytes.endswith(b"\n"):
        _fail("E_PUBLIC_SCAN_BASELINE_CANONICAL", "baseline requires final newline")
    try:
        text = baseline_bytes.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_strict_object)
    except UnicodeDecodeError as exc:
        _fail("E_PUBLIC_SCAN_BASELINE_ENCODING", str(exc))
    except json.JSONDecodeError as exc:
        _fail("E_PUBLIC_SCAN_BASELINE_JSON", str(exc))
    if not isinstance(value, dict):
        _fail("E_PUBLIC_SCAN_BASELINE_SCHEMA", "baseline is not an object")
    return value


def _safe_logical_path(value: Any, code: str) -> str:
    if not isinstance(value, str):
        _fail(code, "path is not a string")
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
        or unicodedata.normalize("NFC", value) != value
    ):
        _fail(code, f"unsafe logical path: {value!r}")
    return value


def _is_tests_or_examples_surface(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and parts[0] in {"tests", "examples"}


def _is_synthetic_fixture_surface(path: str) -> bool:
    return _is_tests_or_examples_surface(path) or path in SYNTHETIC_FIXTURE_PATHS


def _is_readme_surface(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name == "readme" or name.startswith("readme.")


def _is_changelog_surface(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name == "changelog" or name.startswith("changelog.")


def _is_unwaivable_surface(path: str) -> bool:
    return path in {
        "release/tag-message",
        "release/title",
        "release/body",
    } or _is_readme_surface(path) or _is_changelog_surface(path)


def _baseline_repository_path(path: str) -> str | None:
    for prefix in ("git/final/", "snapshot/", "tar/"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    parts = PurePosixPath(path).parts
    if (
        len(parts) >= 5
        and parts[:3] == ("git", "history", "blobs")
        and SHA40_RE.fullmatch(parts[3]) is not None
    ):
        return PurePosixPath(*parts[4:]).as_posix()
    if (
        len(parts) >= 5
        and parts[:3] == ("git", "history", "tree-paths")
        and re.fullmatch(r"[0-9]{6}", parts[3]) is not None
    ):
        return PurePosixPath(*parts[4:]).as_posix()
    return None


def validate_baseline(
    baseline: Mapping[str, Any], *, version: str | None = None
) -> dict[str, Any]:
    """Validate a closed baseline accepted by an independent release reviewer."""

    if not isinstance(baseline, Mapping):
        _fail("E_PUBLIC_SCAN_BASELINE_SCHEMA", "baseline is not an object")
    if set(baseline) != {"schema_version", "version", "review", "assertions"}:
        _fail("E_PUBLIC_SCAN_BASELINE_SCHEMA", "baseline fields are not closed")
    observed_version = baseline.get("version")
    if (
        baseline.get("schema_version") != BASELINE_SCHEMA_VERSION
        or not isinstance(observed_version, str)
        or VERSION_RE.fullmatch(observed_version) is None
        or (version is not None and observed_version != version)
    ):
        _fail("E_PUBLIC_SCAN_BASELINE_VERSION", "baseline version drift")
    review = baseline.get("review")
    if not isinstance(review, Mapping) or set(review) != REVIEW_FIELDS:
        _fail("E_PUBLIC_SCAN_BASELINE_REVIEW", "review fields are not closed")
    review_id = review.get("review_id")
    member_id = review.get("reviewer_member_id")
    run_id = review.get("reviewer_run_id")
    reviewed_at = review.get("reviewed_at")
    if (
        review.get("reviewer_type") != "independent_release_reviewer"
        or review.get("independent") is not True
        or review.get("decision") != "accepted"
        or not isinstance(review_id, str)
        or re.fullmatch(r"[A-Za-z0-9._-]{3,128}", review_id) is None
        or not isinstance(member_id, str)
        or re.fullmatch(r"[A-Za-z0-9._:/-]{3,256}", member_id) is None
        or not isinstance(run_id, str)
        or re.fullmatch(r"[A-Za-z0-9._:/-]{3,256}", run_id) is None
        or not isinstance(reviewed_at, str)
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            reviewed_at,
        )
        is None
    ):
        _fail(
            "E_PUBLIC_SCAN_BASELINE_REVIEW",
            "independent release review is not accepted",
        )
    assertions = baseline.get("assertions")
    if not isinstance(assertions, list):
        _fail("E_PUBLIC_SCAN_BASELINE_ASSERTION", "assertions must be an array")
    normalized: list[dict[str, str]] = []
    identities: set[tuple[str, ...]] = set()
    for assertion in assertions:
        if not isinstance(assertion, Mapping) or set(assertion) != ASSERTION_FIELDS:
            _fail(
                "E_PUBLIC_SCAN_BASELINE_ASSERTION",
                "assertion fields are not closed",
            )
        path = _safe_logical_path(
            assertion.get("path"), "E_PUBLIC_SCAN_BASELINE_PATH"
        )
        file_digest = assertion.get("file_sha256")
        detector_id = assertion.get("detector_id")
        kind = assertion.get("kind")
        occurrence_id = assertion.get("occurrence_id")
        occurrence_digest = assertion.get("occurrence_set_sha256")
        reason = assertion.get("reason")
        if not isinstance(file_digest, str) or SHA256_RE.fullmatch(file_digest) is None:
            _fail("E_PUBLIC_SCAN_BASELINE_DIGEST", "assertion digest is invalid")
        if not isinstance(detector_id, str) or re.fullmatch(
            r"[a-z][a-z0-9_.-]{2,127}", detector_id
        ) is None:
            _fail("E_PUBLIC_SCAN_BASELINE_DETECTOR", "detector id is invalid")
        if kind not in FINDING_KINDS:
            _fail("E_PUBLIC_SCAN_BASELINE_KINDS", "finding kind is invalid")
        if not isinstance(occurrence_id, str) or SHA256_RE.fullmatch(occurrence_id) is None:
            _fail("E_PUBLIC_SCAN_BASELINE_OCCURRENCE", "occurrence id is invalid")
        if not isinstance(occurrence_digest, str) or SHA256_RE.fullmatch(
            occurrence_digest
        ) is None:
            _fail(
                "E_PUBLIC_SCAN_BASELINE_OCCURRENCE",
                "occurrence-set digest is invalid",
            )
        if reason not in BASELINE_REASONS:
            _fail("E_PUBLIC_SCAN_BASELINE_REASON", "reason is outside the enum")
        if _is_unwaivable_surface(path):
            _fail("E_PUBLIC_SCAN_BASELINE_FORBIDDEN", "surface cannot be waived")
        if (
            reason == "detector_literal"
            and _baseline_repository_path(path) not in DETECTOR_LITERAL_PATHS
        ):
            _fail(
                "E_PUBLIC_SCAN_BASELINE_REASON",
                "detector_literal is limited to the fixed detector sources",
            )
        repository_path = _baseline_repository_path(path)
        if reason == "synthetic_fixture" and (
            repository_path is None
            or not _is_synthetic_fixture_surface(repository_path)
        ):
            _fail(
                "E_PUBLIC_SCAN_BASELINE_REASON",
                "synthetic_fixture is limited to tests/examples",
            )
        if reason == "protocol_vocabulary" and kind != "private_provenance":
            _fail(
                "E_PUBLIC_SCAN_BASELINE_REASON",
                "protocol_vocabulary requires private_provenance",
            )
        identity = (
            path,
            file_digest,
            detector_id,
            str(kind),
            occurrence_id,
            occurrence_digest,
        )
        if identity in identities:
            _fail("E_PUBLIC_SCAN_BASELINE_DUPLICATE", "duplicate assertion")
        identities.add(identity)
        normalized.append(
            {
                "path": path,
                "file_sha256": file_digest,
                "detector_id": detector_id,
                "kind": str(kind),
                "occurrence_id": occurrence_id,
                "occurrence_set_sha256": occurrence_digest,
                "reason": str(reason),
            }
        )
    normalized.sort(
        key=lambda item: (
            item["path"],
            item["file_sha256"],
            item["detector_id"],
            item["kind"],
            item["occurrence_id"],
            item["occurrence_set_sha256"],
            item["reason"],
        )
    )
    computed_assertion_digest = assertion_set_sha256(normalized)
    computed_occurrence_digest = occurrence_set_sha256(normalized)
    if review.get("assertion_set_sha256") != computed_assertion_digest:
        _fail(
            "E_PUBLIC_SCAN_BASELINE_REVIEW",
            "review assertion-set digest differs from normalized assertions",
        )
    if review.get("occurrence_set_sha256") != computed_occurrence_digest:
        _fail(
            "E_PUBLIC_SCAN_BASELINE_REVIEW",
            "review occurrence-set digest differs from normalized assertions",
        )
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "version": observed_version,
        "review": dict(review),
        "assertions": normalized,
    }


def _git_environment() -> dict[str, str]:
    unexpected = sorted(
        key
        for key, value in os.environ.items()
        if key.startswith("GIT_")
        and key not in _INERT_GIT_ENV
        and (key not in _SAFE_GIT_ENV or value != _SAFE_GIT_ENV[key])
    )
    if unexpected:
        _fail(
            "E_PUBLIC_SCAN_GIT_ENV",
            "caller-controlled Git environment is forbidden: " + ",".join(unexpected),
        )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(_SAFE_GIT_ENV)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    return environment


def _run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=root,
        input=None,
        capture_output=True,
        check=False,
        env=_git_environment(),
    )
    if check and result.returncode != 0:
        _fail("E_PUBLIC_SCAN_GIT", f"fixed Git command failed: {args[0]}")
    return result


def _resolved_git_path(root: Path, value: bytes, code: str) -> Path:
    try:
        text = value.decode("utf-8").strip()
    except UnicodeDecodeError:
        _fail(code, "Git administrative path is not UTF-8")
    if not text:
        _fail(code, "Git administrative path is empty")
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _validate_git_repository(root: Path) -> None:
    git_dir = _resolved_git_path(
        root,
        _run_git(root, "rev-parse", "--git-dir").stdout,
        "E_PUBLIC_SCAN_GIT_REPOSITORY",
    )
    common_dir = _resolved_git_path(
        root,
        _run_git(root, "rev-parse", "--git-common-dir").stdout,
        "E_PUBLIC_SCAN_GIT_REPOSITORY",
    )
    replacement_refs = _run_git(
        root,
        "for-each-ref",
        "--format=%(refname)",
        "refs/replace/",
    ).stdout.strip()
    if replacement_refs:
        _fail("E_PUBLIC_SCAN_GIT_REPLACE", "Git replacement refs are forbidden")
    for administrative_root in {git_dir, common_dir}:
        grafts = administrative_root / "info" / "grafts"
        if grafts.exists() or grafts.is_symlink():
            _fail("E_PUBLIC_SCAN_GIT_GRAFTS", "legacy Git grafts are forbidden")
    shallow = _run_git(root, "rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow != b"false":
        _fail("E_PUBLIC_SCAN_GIT_SHALLOW", "shallow repositories are forbidden")
    partial = _run_git(
        root,
        "config",
        "--local",
        "--get-regexp",
        r"^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter))$",
        check=False,
    )
    if partial.returncode not in {0, 1}:
        _fail("E_PUBLIC_SCAN_GIT_PARTIAL", "partial-clone config cannot be read")
    if partial.returncode == 0 and partial.stdout.strip():
        _fail("E_PUBLIC_SCAN_GIT_PARTIAL", "partial/promisor repositories are forbidden")


def _require_commit(root: Path, value: str, label: str) -> str:
    if not isinstance(value, str) or SHA40_RE.fullmatch(value) is None:
        _fail("E_PUBLIC_SCAN_GIT_IDENTITY", f"{label} is not a 40-hex commit")
    object_type = _run_git(root, "cat-file", "-t", value).stdout.strip()
    if object_type != b"commit":
        _fail("E_PUBLIC_SCAN_GIT_IDENTITY", f"{label} is not a commit object")
    return value


def _decode_git_path(value: bytes) -> str:
    try:
        path = value.decode("utf-8")
    except UnicodeDecodeError:
        _fail("E_PUBLIC_SCAN_GIT_PATH", "Git path is not UTF-8")
    return _safe_logical_path(path, "E_PUBLIC_SCAN_GIT_PATH")


def _ls_tree(root: Path, revision: str) -> list[dict[str, str]]:
    raw = _run_git(root, "ls-tree", "-rz", "--full-tree", revision).stdout
    rows: list[dict[str, str]] = []
    paths: set[str] = set()
    for record in raw.split(b"\x00"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        except (ValueError, UnicodeDecodeError):
            _fail("E_PUBLIC_SCAN_GIT_TREE", "malformed ls-tree record")
        path = _decode_git_path(raw_path)
        if path in paths:
            _fail("E_PUBLIC_SCAN_GIT_TREE", "duplicate Git path")
        paths.add(path)
        if object_type == "blob":
            if SHA40_RE.fullmatch(object_id) is None:
                _fail("E_PUBLIC_SCAN_GIT_TREE", "invalid blob object id")
            if mode not in {"100644", "100755"}:
                _fail(
                    "E_PUBLIC_SCAN_GIT_TREE",
                    f"non-regular Git entry is forbidden: {path}",
                )
            rows.append(
                {
                    "mode": mode,
                    "type": object_type,
                    "object_id": object_id,
                    "path": path,
                }
            )
        elif object_type == "commit":
            _fail("E_PUBLIC_SCAN_GITLINK", f"gitlink is forbidden: {path}")
        else:
            _fail("E_PUBLIC_SCAN_GIT_TREE", f"unsupported Git object type: {object_type}")
    return sorted(rows, key=lambda item: item["path"])


def _read_git_object(root: Path, object_id: str, object_type: str) -> bytes:
    size_raw = _run_git(root, "cat-file", "-s", object_id).stdout.strip()
    try:
        size = int(size_raw)
    except ValueError:
        _fail("E_PUBLIC_SCAN_GIT_OBJECT", "invalid Git object size")
    if size < 0 or size > MAX_GIT_OBJECT_BYTES:
        _fail("E_PUBLIC_SCAN_GIT_LIMIT", "Git object exceeds fixed size limit")
    data = _run_git(root, "cat-file", object_type, object_id).stdout
    if len(data) != size:
        _fail("E_PUBLIC_SCAN_GIT_OBJECT", "Git object size changed")
    return data


def _security_module(
    root: Path, candidate_commit: str, expected_detector_digest: str
):
    detector_path = "scripts/v23/v236_security.py"
    row = next(
        (item for item in _ls_tree(root, candidate_commit) if item["path"] == detector_path),
        None,
    )
    if row is None or row.get("mode") not in {"100644", "100755"}:
        _fail("E_PUBLIC_SCAN_DETECTOR", "frozen detector blob is missing")
    source = _read_git_object(root, str(row["object_id"]), "blob")
    detector_digest = _sha256(source)
    if detector_digest != expected_detector_digest:
        _fail("E_PUBLIC_SCAN_DETECTOR", "frozen detector differs from approval")
    module = types.ModuleType("goal_teams_public_scan_security")
    module.__file__ = detector_path
    try:
        exec(
            compile(source, module.__file__, "exec"),
            module.__dict__,
        )
    except Exception as exc:
        _fail("E_PUBLIC_SCAN_DETECTOR", type(exc).__name__)
    required = (
        "contains_secret",
        "HOME_PATH_RE",
        "PRIVATE_KEY_RE",
        "COMMON_TOKEN_RE",
    )
    if any(not hasattr(module, name) for name in required):
        _fail("E_PUBLIC_SCAN_DETECTOR", "frozen detector API is incomplete")
    return module, detector_digest


def _surface_repository_paths(
    path: str, appearances: list[dict[str, str]] | None
) -> list[str]:
    if appearances:
        return sorted({item["path"] for item in appearances})
    for prefix in ("git/final/", "snapshot/", "tar/"):
        if path.startswith(prefix):
            return [path[len(prefix) :]]
    return []


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for match in re.finditer("\n", text):
        offsets.append(match.end())
    return offsets


def _node_span(node: ast.AST, offsets: Sequence[int], text: str) -> tuple[int, int] | None:
    line = getattr(node, "lineno", None)
    end_line = getattr(node, "end_lineno", None)
    column = getattr(node, "col_offset", None)
    end_column = getattr(node, "end_col_offset", None)
    if not all(isinstance(item, int) for item in (line, end_line, column, end_column)):
        return None
    if line < 1 or end_line < 1 or line > len(offsets) or end_line > len(offsets):
        return None
    lines = text.splitlines(keepends=True)
    try:
        start_column = len(lines[line - 1].encode("utf-8")[:column].decode("utf-8"))
        end_column_chars = len(
            lines[end_line - 1].encode("utf-8")[:end_column].decode("utf-8")
        )
    except (UnicodeDecodeError, IndexError):
        return None
    start = min(len(text), offsets[line - 1] + start_column)
    end = min(len(text), offsets[end_line - 1] + end_column_chars)
    return (start, end) if 0 <= start <= end <= len(text) else None


def _detector_literal_spans(text: str, repository_paths: Sequence[str]) -> list[tuple[int, int]]:
    """Locate only concrete regular-expression detector pattern definitions.

    A fixed detector source path is only the first boundary.  The literal must
    also be the pattern body assigned to a ``*_RE``/``*_REGEX`` name (including
    an equivalent keyword argument), must compile as a regular expression, and
    must actually contain regex syntax.  This deliberately excludes arbitrary
    calls named ``compile`` and broad test variables named ``DETECTOR_*``.
    """

    if not repository_paths or any(path not in DETECTOR_LITERAL_PATHS for path in repository_paths):
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    offsets = _line_offsets(text)
    spans: list[tuple[int, int]] = []

    def detector_name(value: str) -> bool:
        upper = value.upper()
        return upper.endswith(("_RE", "_REGEX", "_PATTERN_RE"))

    def constant_pattern(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            return (
                node.value.decode("utf-8", "surrogateescape")
                if isinstance(node.value, bytes)
                else node.value
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = constant_pattern(node.left)
            right = constant_pattern(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    def pattern_body(node: ast.AST) -> ast.AST | None:
        if isinstance(node, ast.Call):
            function = node.func
            qualified = ""
            if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
                qualified = f"{function.value.id}.{function.attr}"
            if qualified != "re.compile" or not node.args:
                return None
            return node.args[0]
        return node

    production_semantics = re.compile(
        r"(?i)(?:^|[^a-z0-9])(?:actual[-_. ]*production|production|prod|"
        r"live|customer|bank|real)(?:[^a-z0-9]|$)"
    )

    def concrete_pattern(node: ast.AST) -> bool:
        value = constant_pattern(node)
        if value is None or production_semantics.search(value):
            return False
        if re.search(r"[\\\[\](){}?*+|^$]", value) is None:
            return False
        try:
            re.compile(value)
        except (re.error, OverflowError):
            return False
        for occurrence in _generic_credential_occurrences(value):
            scalar = str(occurrence["value"])
            if not _safe_reference(scalar) and not _closed_dummy_value(scalar):
                return False
        return True

    candidates: list[tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [target.id for target in targets if isinstance(target, ast.Name)]
            candidates.extend((name, node.value) for name in names)
        elif isinstance(node, ast.Call):
            candidates.extend(
                (keyword.arg, keyword.value)
                for keyword in node.keywords
                if keyword.arg is not None
            )
    for name, value in candidates:
        wrapped_detector = isinstance(value, ast.Call) and pattern_body(value) is not None
        if not detector_name(name) and not (name.isupper() and wrapped_detector):
            continue
        body = pattern_body(value)
        if body is None or not concrete_pattern(body):
            continue
        span = _node_span(body, offsets, text)
        if span is not None:
            spans.append(span)
    return sorted(set(spans))


def _closed_dummy_value(value: str) -> bool:
    stripped = value.strip().strip('"\'')
    if re.fullmatch(r"0{32,128}", stripped) is not None:
        return True
    dummy = (
        r"(?:dummy-fixture|synthetic-fixture|test-only-fixture)"
        r"(?:[-_.][a-z0-9]+){0,8}"
    )
    production_semantics = re.compile(
        r"(?i)(?:^|[-_.])(?:actual|real|prod|production|live|bank|customer)"
        r"(?:$|[-_.])"
    )
    if production_semantics.search(stripped) is not None:
        return False
    normalized_parts = [
        part for part in re.split(r"[-_.]", stripped.lower()) if part
    ]
    semantic_roots = ("actual", "bank", "customer", "live", "prod", "production", "real")
    if any(
        any(root in part for root in semantic_roots)
        for part in normalized_parts
    ):
        return False
    if re.fullmatch(rf"(?i)(?:basic|bearer|digest|token)\s+{dummy}", stripped):
        return True
    if re.fullmatch(rf"(?i)(?:cookie|csrf|session|session_id)={dummy}", stripped):
        return True
    if re.fullmatch(rf"(?i){dummy}", stripped) is not None:
        return True
    if re.fullmatch(
        rf"(?i)(?:access_token|api_key|apikey|password|secret|session|token)={dummy}",
        stripped,
    ) is not None:
        return True
    return False


def _safe_reference_default(value: Any) -> bool:
    """Accept only inert placeholders as a textual reference default."""

    if value is None or isinstance(value, bool):
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return bool(
        not stripped
        or re.fullmatch(
            r"(?i)(?:false|true|null|none|nil|unset|not[_ -]?set)", stripped
        )
        or re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", stripped)
        or re.fullmatch(r"\$\{[^{}]+\}", stripped)
        or re.fullmatch(
            r"\{\{\s*(?:secrets?|env|vault)\.[^{}]+\s*\}\}", stripped, re.I
        )
        or re.fullmatch(r"(?i)(?:env|secret|vault)://\S+", stripped)
        or re.fullmatch(r"\[REDACTED(?::[0-9a-f]{16})?\]", stripped)
        or _closed_dummy_value(stripped)
    )


def _safe_string_reference_call(value: str) -> bool:
    """Parse the closed getenv/mapping-get syntax accepted inside strings.

    A textual expression is documentation, not executable data flow.  It is
    nevertheless unsafe to waive an arbitrary literal default merely because
    the surrounding text looks like ``getenv(...)`` or ``mapping.get(...)``.
    """

    try:
        node = ast.parse(value, mode="eval").body
    except (SyntaxError, ValueError):
        return False
    if not isinstance(node, ast.Call):
        return False

    def dotted_name(candidate: ast.AST) -> str:
        if isinstance(candidate, ast.Name):
            return candidate.id
        if isinstance(candidate, ast.Attribute):
            prefix = dotted_name(candidate.value)
            return f"{prefix}.{candidate.attr}" if prefix else ""
        return ""

    qualified = dotted_name(node.func)
    if qualified not in {"getenv", "os.getenv"} and not (
        qualified.endswith(".get")
        and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\.get",
            qualified,
        )
    ):
        return False
    if not 1 <= len(node.args) <= 2 or any(
        isinstance(argument, ast.Starred) for argument in node.args
    ):
        return False
    key = node.args[0]
    if not (
        isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:/-]{0,255}", key.value)
    ):
        return False
    if any(
        keyword.arg not in {"default", "fallback"}
        for keyword in node.keywords
    ):
        return False
    defaults = list(node.args[1:]) + [keyword.value for keyword in node.keywords]
    if len(defaults) > 1:
        return False
    if not defaults:
        return True
    default = defaults[0]
    return isinstance(default, ast.Constant) and _safe_reference_default(default.value)


def _safe_reference(value: str) -> bool:
    stripped = value.strip().strip('"\'')
    return bool(
        not stripped
        or re.fullmatch(r"(?i)(?:false|true|null|none|nil|unset|not[_ -]?set)", stripped)
        or re.fullmatch(r"(?i)(?:basic|bearer|digest|token)", stripped)
        or re.fullmatch(r"(?:TASK|RUN|CP|AC|SEC|GT)-[A-Z0-9_.-]+", stripped)
        or re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", stripped)
        or re.fullmatch(r"\$\{[^{}]+\}", stripped)
        or re.fullmatch(r"\{\{\s*(?:secrets?|env|vault)\.[^{}]+\s*\}\}", stripped, re.I)
        or re.fullmatch(r"(?i)(?:env|secret|vault)://\S+", stripped)
        or _safe_string_reference_call(stripped)
        or re.fullmatch(r"(?i)env\[[^\r\n]+\]", stripped)
        or re.fullmatch(r"[|>][1-9]?[+-]?", stripped)
        or re.fullmatch(r"\[REDACTED(?::[0-9a-f]{16})?\]", stripped)
    )


def _sensitive_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if normalized in {
        "contains_secret", "detect_secret", "has_secret", "is_secret", "redact_secret",
        "continuation_token", "next_page_token", "page_token", "pagination_token",
    }:
        return False
    exact = {
        "access_key", "access_token", "api_key", "apikey", "auth",
        "authorization", "client_secret", "cookie", "credential", "password",
        "passwd", "private_key", "pwd", "refresh_token", "secret", "secret_key",
        "session_token", "signature", "token", "tls_key", "x_api_key",
    }
    return normalized in exact or normalized.endswith(
        ("_access_key", "_access_token", "_api_key", "_auth_token", "_client_secret",
         "_credential", "_password", "_private_key", "_refresh_token", "_secret",
         "_secret_key", "_session_token", "_signature", "_token")
    )


def _python_literal_credential_occurrences(
    text: str, repository_paths: Sequence[str] = ()
) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    offsets = _line_offsets(text)
    rows: list[dict[str, Any]] = []
    detector_spans = _detector_literal_spans(text, repository_paths)

    def static_text(node: ast.AST) -> str | None:
        """Fold only closed string/bytes literals; never evaluate Python code."""

        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            return (
                node.value.decode("utf-8", "surrogateescape")
                if isinstance(node.value, bytes)
                else node.value
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = static_text(node.left)
            right = static_text(node.right)
            if left is not None and right is not None and len(left) + len(right) <= MAX_GIT_OBJECT_BYTES:
                return left + right
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            string_node: ast.AST | None = None
            count: int | None = None
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, (str, bytes)):
                string_node = node.left
                count = node.right.value if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int) else None
            elif isinstance(node.right, ast.Constant) and isinstance(node.right.value, (str, bytes)):
                string_node = node.right
                count = node.left.value if isinstance(node.left, ast.Constant) and isinstance(node.left.value, int) else None
            if string_node is not None and count is not None and 0 <= count <= MAX_GIT_OBJECT_BYTES:
                item = static_text(string_node)
                if item is not None and len(item) * count <= MAX_GIT_OBJECT_BYTES:
                    return item * count
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                    continue
                if (
                    isinstance(part, ast.FormattedValue)
                    and isinstance(part.value, ast.Constant)
                    and isinstance(part.value.value, (str, int, float, bool, type(None)))
                    and part.format_spec is None
                ):
                    parts.append(str(part.value.value))
                    continue
                return None
            value = "".join(parts)
            return value if len(value) <= MAX_GIT_OBJECT_BYTES else None
        return None

    def add(node: ast.AST, value: str, *, force: bool = False) -> None:
        span = _node_span(node, offsets, text)
        if span is not None and (force or not _safe_reference(value)):
            rows.append({"start": span[0], "end": span[1], "value": value})

    def add_sensitive_scalar(node: ast.AST, value: str) -> None:
        """Prefer the decoded scalar inside a header/key-value fixture."""

        occurrences = _generic_credential_occurrences(value)
        if occurrences:
            for occurrence in occurrences:
                add(node, str(occurrence["value"]))
            return
        add(node, value)

    def add_generic_static_occurrences(node: ast.AST, value: str) -> None:
        for occurrence in _generic_credential_occurrences(value):
            add(node, str(occurrence["value"]))

    def target_keys(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            return [node.attr]
        if isinstance(node, ast.Subscript):
            key = static_text(node.slice)
            return [key] if key is not None else []
        if isinstance(node, (ast.Tuple, ast.List)):
            return [key for child in node.elts for key in target_keys(child)]
        return []

    def binding_names(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, (ast.Tuple, ast.List)):
            return [name for child in node.elts for name in binding_names(child)]
        return []

    # Keep the tiny amount of data flow needed to prove aliases safe or unsafe
    # lexical.  This catches ``parts = [<literal>]; password = ''.join(parts)``
    # without conflating identically named locals in unrelated functions.
    scope_parent: dict[ast.AST, ast.AST] = {}
    scope_bindings: dict[
        ast.AST, dict[str, list[tuple[int, int, ast.AST, ast.AST]]]
    ] = {
        tree: {}
    }
    scope_parameters: dict[ast.AST, set[str]] = {tree: set()}
    node_scope: dict[ast.AST, ast.AST] = {}
    node_parent: dict[ast.AST, ast.AST] = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def record_binding(scope: ast.AST, name: str, owner: ast.AST, value: ast.AST) -> None:
        scope_bindings.setdefault(scope, {}).setdefault(name, []).append(
            (
                int(getattr(owner, "lineno", 0)),
                int(getattr(owner, "col_offset", 0)),
                value,
                owner,
            )
        )

    def record_target_binding(
        scope: ast.AST, target: ast.AST, owner: ast.AST, value: ast.AST
    ) -> None:
        if isinstance(target, ast.Name):
            record_binding(scope, target.id, owner, value)
            return
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for child_target, child_value in zip(target.elts, value.elts):
                record_target_binding(scope, child_target, owner, child_value)
            return
        for name in binding_names(target):
            record_binding(scope, name, owner, value)

    def parameter_names(arguments: ast.arguments) -> set[str]:
        return {
            argument.arg
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *([arguments.vararg] if arguments.vararg is not None else []),
                *([arguments.kwarg] if arguments.kwarg is not None else []),
            )
        }

    def register(node: ast.AST, scope: ast.AST) -> None:
        node_scope[node] = scope
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record_target_binding(scope, target, node, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            record_target_binding(scope, node.target, node, node.value)
        elif isinstance(node, ast.NamedExpr):
            record_target_binding(scope, node.target, node, node.value)
        elif isinstance(node, ast.AugAssign):
            for name in binding_names(node.target):
                record_binding(scope, name, node, node.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # A function definition binds its name at this exact lexical
            # position.  Recording it avoids a whole-tree, last-name-wins
            # lookup that can miss an earlier definition or an alias call.
            record_binding(scope, node.name, node, node)
        elif isinstance(node, ast.ClassDef):
            record_binding(scope, node.name, node, node)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested = node
            scope_parent[nested] = scope
            scope_bindings.setdefault(nested, {})
            scope_parameters[nested] = parameter_names(node.args)
            for decorator in node.decorator_list:
                register(decorator, scope)
            for default in (*node.args.defaults, *[item for item in node.args.kw_defaults if item is not None]):
                register(default, scope)
            if node.returns is not None:
                register(node.returns, scope)
            for statement in node.body:
                register(statement, nested)
            return
        if isinstance(node, ast.Lambda):
            nested = node
            scope_parent[nested] = scope
            scope_bindings.setdefault(nested, {})
            scope_parameters[nested] = parameter_names(node.args)
            for default in (*node.args.defaults, *[item for item in node.args.kw_defaults if item is not None]):
                register(default, scope)
            register(node.body, nested)
            return
        if isinstance(node, ast.ClassDef):
            nested = node
            scope_parent[nested] = scope
            scope_bindings.setdefault(nested, {})
            scope_parameters[nested] = set()
            for decorator in node.decorator_list:
                register(decorator, scope)
            for base in node.bases:
                register(base, scope)
            for keyword in node.keywords:
                register(keyword.value, scope)
            for statement in node.body:
                register(statement, nested)
            return
        for child in ast.iter_child_nodes(node):
            register(child, scope)

    register(tree, tree)

    def binding_for(name: str, reference: ast.AST) -> ast.AST | None:
        scope = node_scope.get(reference, tree)
        reference_position = (
            int(getattr(reference, "lineno", 1 << 30)),
            int(getattr(reference, "col_offset", 1 << 30)),
        )
        while True:
            if name in scope_parameters.get(scope, set()):
                return None
            candidates = scope_bindings.get(scope, {}).get(name, [])
            prior = [item for item in candidates if item[:2] <= reference_position]
            if prior:
                return max(prior, key=lambda item: item[:2])[2]
            parent = scope_parent.get(scope)
            if parent is None:
                return None
            scope = parent

    def local_binding_entries(
        name: str, reference: ast.AST
    ) -> tuple[ast.AST, list[tuple[int, int, ast.AST, ast.AST]]] | None:
        scope = node_scope.get(reference, tree)
        reference_position = (
            int(getattr(reference, "lineno", 1 << 30)),
            int(getattr(reference, "col_offset", 1 << 30)),
        )
        while True:
            if name in scope_parameters.get(scope, set()):
                return None
            candidates = scope_bindings.get(scope, {}).get(name, [])
            prior = [item for item in candidates if item[:2] <= reference_position]
            if prior:
                return scope, prior
            parent = scope_parent.get(scope)
            if parent is None:
                return None
            scope = parent

    def binding_is_control_flow_uncertain(owner: ast.AST, scope: ast.AST) -> bool:
        current = node_parent.get(owner)
        uncertain_types = (
            ast.AsyncFor,
            ast.ExceptHandler,
            ast.For,
            ast.If,
            ast.IfExp,
            ast.Match,
            ast.Try,
            ast.While,
            ast.comprehension,
        )
        try_star = getattr(ast, "TryStar", ast.Try)
        while current is not None and current is not scope:
            if isinstance(current, (*uncertain_types, try_star)):
                return True
            current = node_parent.get(current)
        return False

    def effective_binding_entries(
        name: str, reference: ast.AST
    ) -> tuple[ast.AST, list[tuple[int, int, ast.AST, ast.AST]]] | None:
        """Return the binding that reaches a call plus later branch candidates."""

        resolved = local_binding_entries(name, reference)
        if resolved is None:
            return None
        scope, entries = resolved
        ordered = sorted(entries, key=lambda item: item[:2])
        last_certain = -1
        for index, (_line, _column, _value, owner) in enumerate(ordered):
            if not binding_is_control_flow_uncertain(owner, scope):
                last_certain = index
        selected = ordered[last_certain:] if last_certain >= 0 else ordered
        return scope, selected

    def stable_binding_node(name: str, reference: ast.AST) -> ast.AST | None:
        resolved = local_binding_entries(name, reference)
        if resolved is None:
            return None
        scope, entries = resolved
        if len(entries) != 1:
            return None
        _line, _column, value, owner = entries[0]
        if binding_is_control_flow_uncertain(owner, scope):
            return None
        return value

    def stable_sequence_elements(
        node: ast.AST,
        reference: ast.AST,
        seen: frozenset[tuple[int, str]] = frozenset(),
    ) -> list[ast.AST] | None:
        if isinstance(node, (ast.List, ast.Tuple)):
            return list(node.elts)
        if not isinstance(node, ast.Name):
            return None
        scope = node_scope.get(reference, tree)
        identity = (id(scope), node.id)
        if identity in seen:
            return None
        resolved = local_binding_entries(node.id, reference)
        if resolved is None:
            return None
        binding_scope, entries = resolved
        if len(entries) != 1:
            return None
        line, column, initial, owner = entries[0]
        if binding_is_control_flow_uncertain(owner, binding_scope):
            return None
        initial_elements = stable_sequence_elements(
            initial, initial, seen | {identity}
        )
        if initial_elements is None:
            return None
        result = list(initial_elements)
        reference_position = (
            int(getattr(reference, "lineno", 1 << 30)),
            int(getattr(reference, "col_offset", 1 << 30)),
        )
        mutations: list[tuple[int, int, ast.Call]] = []
        for candidate in ast.walk(binding_scope):
            if not isinstance(candidate, ast.Call) or node_scope.get(candidate) is not binding_scope:
                continue
            function = candidate.func
            if not (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == node.id
            ):
                continue
            position = (
                int(getattr(candidate, "lineno", 0)),
                int(getattr(candidate, "col_offset", 0)),
            )
            if (line, column) < position < reference_position:
                mutations.append((*position, candidate))
        for _line, _column, mutation in sorted(mutations, key=lambda item: item[:2]):
            owner = mutation
            if binding_is_control_flow_uncertain(owner, binding_scope):
                return None
            method = mutation.func.attr if isinstance(mutation.func, ast.Attribute) else ""
            if method == "append" and len(mutation.args) == 1 and not mutation.keywords:
                result.append(mutation.args[0])
            elif method == "extend" and len(mutation.args) == 1 and not mutation.keywords:
                extension = stable_sequence_elements(
                    mutation.args[0], mutation, seen | {identity}
                )
                if extension is None:
                    return None
                result.extend(extension)
            else:
                return None
        return result

    def key_alias_candidates(
        node: ast.AST, seen: frozenset[tuple[int, str]] = frozenset()
    ) -> set[str] | None:
        direct = static_text(node)
        if direct is not None:
            return {direct}
        if isinstance(node, ast.Name):
            scope = node_scope.get(node, tree)
            identity = (id(scope), node.id)
            if identity in seen:
                return None
            resolved = local_binding_entries(node.id, node)
            if resolved is None:
                return None
            _binding_scope, entries = resolved
            candidates: set[str] = set()
            for _line, _column, binding, _owner in entries:
                item = key_alias_candidates(binding, seen | {identity})
                if item is not None:
                    candidates.update(item)
            return candidates or None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = key_alias_candidates(node.left, seen)
            right = key_alias_candidates(node.right, seen)
            if left is None or right is None or len(left) != 1 or len(right) != 1:
                return None
            return {next(iter(left)) + next(iter(right))}
        if isinstance(node, ast.Subscript):
            index = node.slice.value if isinstance(node.slice, ast.Constant) else None
            container = node.value
            if isinstance(container, ast.Name):
                binding = stable_binding_node(container.id, container)
                if binding is None:
                    return None
                container = binding
            if (
                isinstance(index, int)
                and isinstance(container, (ast.Tuple, ast.List))
                and -len(container.elts) <= index < len(container.elts)
            ):
                return key_alias_candidates(container.elts[index], seen)
            if isinstance(index, str) and isinstance(container, ast.Dict):
                matches = [
                    value_node
                    for key_node, value_node in zip(container.keys, container.values)
                    if key_node is not None and static_text(key_node) == index
                ]
                if len(matches) == 1:
                    return key_alias_candidates(matches[0], seen)
            return None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            matches: list[ast.AST] = []
            for candidate in ast.walk(tree):
                if not isinstance(candidate, ast.ClassDef) or candidate.name != node.value.id:
                    continue
                for statement in candidate.body:
                    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                        value_node = statement.value
                        if value_node is None:
                            continue
                        if any(
                            isinstance(target, ast.Name) and target.id == node.attr
                            for target in targets
                        ):
                            matches.append(value_node)
            if len(matches) == 1:
                return key_alias_candidates(matches[0], seen)
            return None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join" and len(node.args) == 1 and not node.keywords:
            separator = static_text(node.func.value)
            elements = stable_sequence_elements(node.args[0], node, seen)
            if separator is None or elements is None:
                return None
            parts: list[str] = []
            for element in elements:
                candidate = key_alias_candidates(element, seen)
                if candidate is None or len(candidate) != 1:
                    return None
                parts.append(next(iter(candidate)))
            return {separator.join(parts)}
        # Branches, calls, parameters and reassigned names are deliberately
        # unknown.  Mutation sites treat unknown keys fail-closed when their
        # value embeds a literal credential.
        return None

    def resolved_static_text(
        node: ast.AST, seen: frozenset[tuple[int, str]] = frozenset()
    ) -> str | None:
        value = static_text(node)
        if value is not None:
            return value
        if isinstance(node, ast.Name):
            scope = node_scope.get(node, tree)
            identity = (id(scope), node.id)
            if identity in seen:
                return None
            binding = binding_for(node.id, node)
            return (
                resolved_static_text(binding, seen | {identity})
                if binding is not None
                else None
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = resolved_static_text(node.left, seen)
            right = resolved_static_text(node.right, seen)
            if left is not None and right is not None and len(left) + len(right) <= MAX_GIT_OBJECT_BYTES:
                return left + right
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                elif isinstance(part, ast.FormattedValue) and part.format_spec is None:
                    item = resolved_static_text(part.value, seen)
                    if item is None:
                        return None
                    parts.append(item)
                else:
                    return None
            value = "".join(parts)
            return value if len(value) <= MAX_GIT_OBJECT_BYTES else None
        return None

    def call_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = call_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    import_aliases: dict[str, str] = {}
    for imported in ast.walk(tree):
        if isinstance(imported, ast.ImportFrom) and imported.module in {
            "builtins",
            "functools",
            "operator",
        }:
            for alias in imported.names:
                import_aliases[alias.asname or alias.name] = f"{imported.module}.{alias.name}"
        elif isinstance(imported, ast.Import):
            for alias in imported.names:
                if alias.name in {"builtins", "functools", "operator"}:
                    import_aliases[alias.asname or alias.name] = alias.name

    def canonical_call_name(node: ast.AST) -> str:
        qualified = call_name(node)
        head, separator, tail = qualified.partition(".")
        replacement = import_aliases.get(head)
        if replacement is None:
            return qualified
        return replacement + (separator + tail if separator else "")

    def static_operational_argument(node: ast.AST, allowed: set[str]) -> bool:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return True
        value = resolved_static_text(node)
        return value is not None and value in allowed

    production_semantics = re.compile(
        r"(?i)(?:^|[-_. ])(?:actual|real|prod|production|live|bank|customer)"
        r"(?:$|[-_. ])"
    )

    def metadata_text_safe(value: str) -> bool:
        return (
            production_semantics.search(value) is None
            and not _generic_credential_occurrences(value)
        )

    def safe_schema_descriptor(node: ast.AST) -> bool:
        """Recognize a JSON-Schema value descriptor, never a credential value."""

        if not isinstance(node, ast.Dict):
            return False
        pairs: list[tuple[str, ast.AST]] = []
        for key_node, value_node in zip(node.keys, node.values):
            key = static_text(key_node) if key_node is not None else None
            if key is None:
                return False
            pairs.append((key, value_node))
        keys = [key for key, _value in pairs]
        allowed = {
            "$ref", "additionalProperties", "allOf", "anyOf",
            "description", "format", "items", "maxItems", "maxLength",
            "maximum", "minItems", "minLength", "minimum", "not", "oneOf",
            "pattern", "properties", "required", "title", "type",
        }
        if "type" not in keys or not keys or not set(keys) <= allowed:
            return False
        scalar_types = {"array", "boolean", "integer", "null", "number", "object", "string"}
        for key, value_node in pairs:
            value = static_text(value_node)
            if key == "type":
                if value not in scalar_types:
                    return False
            elif key in {"description", "title", "$ref"}:
                if value is None or not metadata_text_safe(value):
                    return False
            elif key == "format":
                if value not in {
                    "byte", "date", "date-time", "duration", "email", "hostname",
                    "idn-email", "idn-hostname", "ipv4", "ipv6", "iri", "iri-reference",
                    "json-pointer", "password", "regex", "relative-json-pointer", "time",
                    "uri", "uri-reference", "uri-template", "uuid",
                }:
                    return False
            elif key == "pattern":
                if value is None or production_semantics.search(value):
                    return False
                try:
                    re.compile(value)
                except (re.error, OverflowError):
                    return False
            elif key in {"minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"}:
                if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, (int, float)):
                    return False
            elif key == "additionalProperties":
                if not (
                    isinstance(value_node, ast.Constant)
                    and isinstance(value_node.value, bool)
                ) and not safe_schema_descriptor(value_node):
                    return False
            elif key == "required":
                if not isinstance(value_node, (ast.List, ast.Tuple)) or not all(
                    static_text(item) is not None for item in value_node.elts
                ):
                    return False
            elif key == "properties":
                if not isinstance(value_node, ast.Dict) or not all(
                    child is not None and safe_schema_descriptor(child)
                    for child in value_node.values
                ):
                    return False
            elif key in {"items", "not"}:
                if not safe_schema_descriptor(value_node):
                    return False
            elif key in {"allOf", "anyOf", "oneOf"}:
                if not isinstance(value_node, (ast.List, ast.Tuple)) or not all(
                    safe_schema_descriptor(item) for item in value_node.elts
                ):
                    return False
        return True

    def safe_authorization_mapping(node: ast.AST) -> bool:
        """Recognize the release operation-authorization envelope shape."""

        if not isinstance(node, ast.Dict):
            return False
        pairs: dict[str, ast.AST] = {}
        for key_node, value_node in zip(node.keys, node.values):
            key = static_text(key_node) if key_node is not None else None
            if key is None or key in pairs:
                return False
            pairs[key] = value_node
        if set(pairs) != {
            "expected_after_sha256",
            "expected_before",
            "intent_sha256",
            "mode",
            "parameters",
            "parameters_sha256",
        }:
            return False
        mode = resolved_static_text(pairs["mode"])
        if mode not in {"execute_github", "execute_local", "prepare", "verify"}:
            return False
        return all(
            not has_unproven_literal(value_node)
            for key, value_node in pairs.items()
            if key != "mode"
        )

    def binding_may_embed_literal(node: ast.AST) -> bool:
        return isinstance(
            node,
            (
                ast.Constant,
                ast.JoinedStr,
                ast.BinOp,
                ast.BoolOp,
                ast.Compare,
                ast.Dict,
                ast.IfExp,
                ast.Lambda,
                ast.List,
                ast.Name,
                ast.Set,
                ast.Tuple,
            ),
        )

    def safe_crypto_digest(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call) or node.args or node.keywords:
            return False
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"digest", "hexdigest"}:
            return False
        constructor = node.func.value
        if not isinstance(constructor, ast.Call) or call_name(constructor.func) != "hmac.new":
            return False
        if len(constructor.args) < 2 or resolved_static_text(constructor.args[0]) is not None:
            return False
        for child in ast.walk(constructor):
            if not isinstance(child, ast.Constant) or not isinstance(child.value, (str, bytes)):
                continue
            value = (
                child.value.decode("utf-8", "surrogateescape")
                if isinstance(child.value, bytes)
                else child.value
            )
            if production_semantics.search(value) or _generic_credential_occurrences(value):
                return False
        return True

    def safe_path_expression(node: ast.AST) -> bool:
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            return False
        values = [
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        ]
        roots = {
            child.id.lower()
            for child in ast.walk(node)
            if isinstance(child, ast.Name)
        }
        root_like = bool(
            roots & {"base", "directory", "repo", "root", "workspace"}
        ) or any(
            name.endswith(("_candidate", "_candidates", "_dir", "_directory", "_path", "_root"))
            for name in roots
        )
        leaf_like = any(
            re.search(r"\.[A-Za-z0-9]{1,12}$", value)
            or re.fullmatch(r"candidate-v[0-9]+", value, re.I)
            for value in values
        )
        return bool(values) and root_like and leaf_like and all(
            production_semantics.search(value) is None
            and not _generic_credential_occurrences(value)
            for value in values
        )

    def safe_detector_compile(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call) or call_name(node.func) != "re.compile" or not node.args:
            return False
        span = _node_span(node.args[0], offsets, text)
        return span is not None and span in detector_spans

    def safe_dynamic_reference(
        node: ast.AST, seen: frozenset[int] = frozenset()
    ) -> bool:
        if isinstance(node, ast.Subscript):
            return not has_unproven_literal(node.value, seen)
        if not isinstance(node, ast.Call):
            return False
        function = node.func
        function_name = (
            function.attr
            if isinstance(function, ast.Attribute)
            else function.id
            if isinstance(function, ast.Name)
            else ""
        )
        if function_name in {"get", "getenv"} and node.args:
            if resolved_static_text(node.args[0]) is None or len(node.args) > 2:
                return False
            if any(
                keyword.arg not in {"default", "fallback"}
                for keyword in node.keywords
            ):
                return False
            defaults = list(node.args[1:])
            defaults.extend(
                keyword.value
                for keyword in node.keywords
                if keyword.arg in {"default", "fallback"}
            )
            return (
                isinstance(function, ast.Attribute)
                and not has_unproven_literal(function.value, seen)
                and all(
                    (value := resolved_static_text(default)) is not None
                    and (_safe_reference(value) or _closed_dummy_value(value))
                    for default in defaults
                )
            )
        if isinstance(function, ast.Attribute) and function.attr in {
            "group", "groupdict", "groups",
        }:
            return (
                not has_unproven_literal(function.value, seen)
                and all(
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, (str, int))
                    for argument in node.args
                )
                and not node.keywords
            )
        if isinstance(function, ast.Attribute) and function.attr in {
            "split", "rsplit", "partition", "rpartition",
        }:
            return (
                not has_unproven_literal(function.value, seen)
                and all(
                    static_operational_argument(argument, {"", ":", "=", "@", ";", ","})
                    for argument in node.args
                )
                and not node.keywords
            )
        if isinstance(function, ast.Attribute) and function.attr == "join":
            separator = static_text(function.value)
            return (
                separator in {"", ":", "=", "@", ";", ",", "\n"}
                and bool(node.args)
                and all(not has_unproven_literal(argument, seen) for argument in node.args)
                and not node.keywords
            )
        if isinstance(function, ast.Attribute) and function.attr == "encode":
            return (
                not has_unproven_literal(function.value, seen)
                and all(
                    static_operational_argument(
                        argument, {"ascii", "utf-8", "utf8", "surrogateescape"}
                    )
                    for argument in node.args
                )
                and not node.keywords
            )
        qualified_name = call_name(function)
        if qualified_name in {"_digest_bytes", "hashlib.sha256"}:
            return (
                bool(node.args)
                and all(
                    not has_unproven_literal(argument, seen)
                    for argument in node.args
                )
                and not node.keywords
            )
        return False

    def has_unproven_literal(
        node: ast.AST, seen: frozenset[int] = frozenset()
    ) -> bool:
        identity = id(node)
        if identity in seen:
            return False
        nested_seen = seen | {identity}
        if isinstance(node, ast.Name):
            elements = stable_sequence_elements(node, node)
            if elements is not None and any(
                has_unproven_literal(element, nested_seen) for element in elements
            ):
                return True
            resolved = local_binding_entries(node.id, node)
            if resolved is None:
                return False
            scope, entries = resolved
            return any(
                binding_may_embed_literal(binding)
                and has_unproven_literal(binding, nested_seen)
                for _line, _column, binding, owner in entries
                if len(entries) != 1
                or binding_is_control_flow_uncertain(owner, scope)
                or binding is entries[0][2]
            )
        value = resolved_static_text(node)
        if value is not None:
            return not (_safe_reference(value) or _closed_dummy_value(value))
        if safe_schema_descriptor(node):
            return False
        if safe_path_expression(node):
            return False
        if safe_dynamic_reference(node, nested_seen):
            return False
        return any(
            has_unproven_literal(child, nested_seen)
            for child in ast.iter_child_nodes(node)
            if not isinstance(child, (ast.Load, ast.Store, ast.Del))
        )

    def inspect_sensitive_value(
        node: ast.AST,
        *,
        key_hint: str = "",
        seen: frozenset[int] = frozenset(),
    ) -> None:
        identity = id(node)
        if identity in seen:
            return
        nested_seen = seen | {identity}
        if isinstance(node, ast.Name) and stable_binding_node(node.id, node) is None:
            resolved = local_binding_entries(node.id, node)
            if resolved is not None:
                _scope, entries = resolved
                for _line, _column, binding, _owner in entries:
                    inspect_sensitive_value(
                        binding, key_hint=key_hint, seen=nested_seen
                    )
                return
        value = (
            resolved_static_text(node)
            if not isinstance(node, ast.Name)
            or stable_binding_node(node.id, node) is not None
            else None
        )
        if value is not None:
            add_sensitive_scalar(node, value)
            return
        if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.Tuple)) and not (
            expression_has_production_marker(node)
        ):
            # Structured authorization/receipt metadata is not itself a
            # scalar credential.  Sensitive children are inspected by their
            # own keyed sinks; an explicit production credential marker keeps
            # a container fail-closed.
            return
        if safe_schema_descriptor(node):
            return
        if safe_detector_compile(node) or safe_crypto_digest(node) or safe_path_expression(node):
            return
        if _sensitive_key(key_hint) and key_hint.lower() == "authorization":
            if safe_authorization_mapping(node):
                return
        if safe_dynamic_reference(node) or not has_unproven_literal(node):
            return
        source = ast.get_source_segment(text, node)
        add(
            node,
            source if isinstance(source, str) and source else "<literal-expression>",
            force=True,
        )

    def expression_has_production_marker(node: ast.AST) -> bool:
        values: list[str] = []
        resolved = resolved_static_text(node)
        if resolved is not None:
            values.append(resolved)
        values.extend(
            child.value.decode("utf-8", "surrogateescape")
            if isinstance(child.value, bytes)
            else child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant)
            and isinstance(child.value, (str, bytes))
        )
        credential_semantics = re.compile(
            r"(?i)(?:^|[^a-z0-9])(?:access[-_. ]*key|access[-_. ]*token|"
            r"api[-_. ]*key|auth(?:orization)?|client[-_. ]*secret|cookie|"
            r"credential|pass(?:word|wd)?|private[-_. ]*key|pwd|refresh[-_. ]*token|"
            r"secret|session[-_. ]*token|signature|token|tls[-_. ]*key)"
            r"(?:[^a-z0-9]|$)"
        )
        return any(
            production_semantics.search(value) is not None
            and (
                credential_semantics.search(value) is not None
                or bool(_generic_credential_occurrences(value))
            )
            for value in values
        )

    def inspect_keyed_mutation(key_node: ast.AST, value_node: ast.AST) -> None:
        candidates = key_alias_candidates(key_node)
        if any(_sensitive_key(item) for item in candidates or set()) or (
            candidates is None and expression_has_production_marker(value_node)
        ):
            inspect_sensitive_value(value_node, key_hint="credential")

    def stable_container(node: ast.AST, reference: ast.AST) -> ast.AST | None:
        if isinstance(node, (ast.Dict, ast.List, ast.Tuple)):
            return node
        if isinstance(node, ast.Name):
            return stable_binding_node(node.id, reference)
        return None

    def closed_dict_comprehension_pairs(
        node: ast.DictComp,
    ) -> list[tuple[ast.AST, ast.AST]] | None:
        if len(node.generators) != 1:
            return None
        generator = node.generators[0]
        if generator.is_async or generator.ifs:
            return None
        elements = stable_sequence_elements(generator.iter, node)
        if elements is None:
            return None

        def bind_pattern(
            target: ast.AST,
            value: ast.AST,
            environment: dict[str, ast.AST],
        ) -> bool:
            if isinstance(target, ast.Name):
                environment[target.id] = value
                return True
            value_container = stable_container(value, node)
            if (
                isinstance(target, (ast.List, ast.Tuple))
                and isinstance(value_container, (ast.List, ast.Tuple))
                and len(target.elts) == len(value_container.elts)
            ):
                return all(
                    bind_pattern(child_target, child_value, environment)
                    for child_target, child_value in zip(
                        target.elts, value_container.elts
                    )
                )
            return False

        pairs: list[tuple[ast.AST, ast.AST]] = []
        for element in elements:
            environment: dict[str, ast.AST] = {}
            if not bind_pattern(generator.target, element, environment):
                return None
            key_node = (
                environment.get(node.key.id, node.key)
                if isinstance(node.key, ast.Name)
                else node.key
            )
            value_node = (
                environment.get(node.value.id, node.value)
                if isinstance(node.value, ast.Name)
                else node.value
            )
            pairs.append((key_node, value_node))
        return pairs

    def update_pairs(
        node: ast.AST,
        reference: ast.AST,
        seen: frozenset[int] = frozenset(),
    ) -> list[tuple[ast.AST, ast.AST]] | None:
        identity = id(node)
        if identity in seen:
            return None
        nested_seen = seen | {identity}
        if isinstance(node, ast.DictComp):
            return closed_dict_comprehension_pairs(node)
        container = stable_container(node, reference)
        if container is None:
            if isinstance(node, ast.Call) and call_name(node.func) in {"dict", "builtins.dict"} and len(node.args) == 1 and not node.keywords:
                return update_pairs(node.args[0], node, nested_seen)
            return None
        if isinstance(container, ast.Dict):
            if any(key is None for key in container.keys):
                return None
            return [
                (key, value)
                for key, value in zip(container.keys, container.values)
                if key is not None
            ]
        if not isinstance(container, (ast.List, ast.Tuple)):
            return None
        pairs: list[tuple[ast.AST, ast.AST]] = []
        for element in container.elts:
            pair_node = stable_container(element, reference)
            if not isinstance(pair_node, (ast.List, ast.Tuple)) or len(pair_node.elts) != 2:
                return None
            pairs.append((pair_node.elts[0], pair_node.elts[1]))
        return pairs

    def resolved_sink_function(
        function: ast.AST, reference: ast.AST, seen: frozenset[str] = frozenset()
    ) -> tuple[str, int, int] | tuple[str, int, int, int] | None:
        qualified = canonical_call_name(function)
        if qualified in {"setattr", "builtins.setattr", "object.__setattr__", "operator.setitem"}:
            return ("key_value", 1, 2)
        if isinstance(function, ast.Attribute) and function.attr in {"__setitem__", "setdefault"}:
            return ("key_value", 0, 1)
        if isinstance(function, ast.Attribute) and function.attr == "update":
            return ("pairs", 0, -1, -1)
        if qualified in {"dict", "builtins.dict"}:
            return ("pairs", 0, -1, -1)
        if isinstance(function, ast.Name) and function.id not in seen:
            resolved = effective_binding_entries(function.id, reference)
            if resolved is not None:
                _scope, entries = resolved
                sinks = [
                    sink
                    for _line, _column, binding, _owner in entries
                    if (
                        sink := resolved_sink_function(
                            binding, reference, seen | {function.id}
                        )
                    )
                    is not None
                ]
                if sinks:
                    return sinks[0]
        if (
            isinstance(function, ast.Call)
            and canonical_call_name(function.func) in {"getattr", "builtins.getattr"}
            and len(function.args) >= 2
        ):
            attribute = resolved_static_text(function.args[1])
            if attribute in {"__setitem__", "setdefault"}:
                return ("key_value", 0, 1)
            if attribute == "update":
                return ("pairs", 0, -1, -1)
        return None

    def resolved_local_classes(
        candidate: ast.AST,
        reference: ast.AST,
        seen: frozenset[tuple[int, str, str]] = frozenset(),
    ) -> list[ast.ClassDef]:
        if isinstance(candidate, ast.ClassDef):
            return [candidate]
        if not isinstance(candidate, ast.Name):
            return []
        scope = node_scope.get(reference, tree)
        identity = (id(scope), candidate.id, "class")
        if identity in seen:
            return []
        resolved = effective_binding_entries(candidate.id, reference)
        if resolved is None:
            return []
        _binding_scope, entries = resolved
        classes: list[ast.ClassDef] = []
        for _line, _column, binding, _owner in entries:
            classes.extend(
                resolved_local_classes(binding, binding, seen | {identity})
            )
        return list(dict.fromkeys(classes))

    def resolved_class_receivers(
        candidate: ast.AST,
        reference: ast.AST,
        seen: frozenset[tuple[int, str, str]] = frozenset(),
    ) -> list[tuple[ast.ClassDef, bool]]:
        if isinstance(candidate, ast.ClassDef):
            return [(candidate, False)]
        if isinstance(candidate, ast.Call) and not candidate.keywords:
            return [
                (class_node, True)
                for class_node in resolved_local_classes(candidate.func, candidate)
            ]
        if not isinstance(candidate, ast.Name):
            return []
        scope = node_scope.get(reference, tree)
        identity = (id(scope), candidate.id, "receiver")
        if identity in seen:
            return []
        resolved = effective_binding_entries(candidate.id, reference)
        if resolved is None:
            return []
        _binding_scope, entries = resolved
        receivers: list[tuple[ast.ClassDef, bool]] = []
        for _line, _column, binding, _owner in entries:
            if isinstance(binding, ast.ClassDef):
                receivers.append((binding, False))
            else:
                receivers.extend(
                    resolved_class_receivers(binding, binding, seen | {identity})
                )
        return list(dict.fromkeys(receivers))

    def method_bound_offset(
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        instance_receiver: bool,
    ) -> int:
        decorators = {canonical_call_name(item) for item in function.decorator_list}
        if "staticmethod" in decorators or "builtins.staticmethod" in decorators:
            return 0
        if "classmethod" in decorators or "builtins.classmethod" in decorators:
            return 1
        return 1 if instance_receiver else 0

    def local_class_methods(
        class_node: ast.ClassDef,
        name: str,
        seen: frozenset[int] = frozenset(),
    ) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
        """Resolve a method through the closed set of local base classes."""

        identity = id(class_node)
        if identity in seen:
            return []
        direct = [
            statement
            for statement in class_node.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name == name
        ]
        if direct:
            return [direct[-1]]
        nested_seen = seen | {identity}
        for base_expression in class_node.bases:
            base_classes = resolved_local_classes(base_expression, base_expression)
            if not base_classes:
                # An external base makes the method owner undecidable; stay
                # inside the explicitly supported local-class boundary.
                return []
            inherited: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
            for base_class in base_classes:
                inherited.extend(
                    local_class_methods(base_class, name, nested_seen)
                )
            if inherited:
                return list(dict.fromkeys(inherited))
        return []

    def resolved_method_callables(
        receiver: ast.AST,
        name: str,
        reference: ast.AST,
    ) -> list[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, int]
    ]:
        methods: list[
            tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, int]
        ] = []
        for class_node, is_instance in resolved_class_receivers(
            receiver, reference
        ):
            for method in local_class_methods(class_node, name):
                methods.append(
                    (method, method_bound_offset(method, is_instance))
                )
        return list(dict.fromkeys(methods))

    def resolved_local_callables(
        function: ast.AST,
        reference: ast.AST,
        seen: frozenset[tuple[int, str, str]] = frozenset(),
    ) -> list[
        tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, int]
    ]:
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return [(function, 0)]
        if isinstance(function, ast.Attribute):
            return resolved_method_callables(
                function.value, function.attr, function
            )
        if (
            isinstance(function, ast.Call)
            and canonical_call_name(function.func) in {"getattr", "builtins.getattr"}
            and len(function.args) == 2
            and not function.keywords
        ):
            attribute = resolved_static_text(function.args[1])
            if attribute is not None:
                return resolved_method_callables(
                    function.args[0], attribute, function
                )
            return []
        if not isinstance(function, ast.Name):
            return []
        scope = node_scope.get(reference, tree)
        identity = (id(scope), function.id, "callable")
        if identity in seen:
            return []
        resolved = effective_binding_entries(function.id, reference)
        if resolved is None:
            return []
        _binding_scope, entries = resolved
        functions: list[
            tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, int]
        ] = []
        for _line, _column, binding, _owner in entries:
            functions.extend(
                resolved_local_callables(binding, binding, seen | {identity})
            )
        return list(dict.fromkeys(functions))

    def callable_parameter(
        function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
        name: str,
    ) -> tuple[str, int] | None:
        positional = [*function.args.posonlyargs, *function.args.args]
        for index, argument in enumerate(positional):
            if argument.arg == name:
                return ("positional", index)
        for index, argument in enumerate(function.args.kwonlyargs):
            if argument.arg == name:
                return ("keyword_only", index)
        return None

    def helper_sink_summary(
        function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
    ) -> list[tuple[str | None, str | None, str]]:
        summaries: list[tuple[str | None, str | None, str]] = []

        def record_summary(key_node: ast.AST, value_node: ast.AST) -> None:
            if not isinstance(value_node, ast.Name):
                return
            if callable_parameter(function, value_node.id) is None:
                return
            if isinstance(key_node, ast.Name):
                if callable_parameter(function, key_node.id) is not None:
                    summaries.append((key_node.id, None, value_node.id))
                    return
            candidates = key_alias_candidates(key_node)
            sensitive = sorted(
                item for item in candidates or set() if _sensitive_key(item)
            )
            if sensitive:
                summaries.append((None, sensitive[0], value_node.id))

        for statement in ast.walk(function):
            if node_scope.get(statement) is not function:
                continue
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                value_node = statement.value
                if value_node is None:
                    continue
                for target in targets:
                    if isinstance(target, ast.Subscript):
                        record_summary(target.slice, value_node)
                    else:
                        keys = target_keys(target)
                        sensitive = next(
                            (key for key in keys if _sensitive_key(key)), None
                        )
                        if sensitive is not None:
                            record_summary(ast.Constant(value=sensitive), value_node)
                continue
            if not isinstance(statement, ast.Call):
                continue
            sink = resolved_sink_function(statement.func, statement)
            if sink is not None and sink[0] == "key_value":
                _kind, key_index, value_index = sink
                if key_index < len(statement.args) and value_index < len(statement.args):
                    record_summary(
                        statement.args[key_index], statement.args[value_index]
                    )
            elif sink is not None and sink[0] == "pairs":
                for argument in statement.args:
                    for key_node, value_node in update_pairs(argument, statement) or []:
                        record_summary(key_node, value_node)
                for keyword in statement.keywords:
                    if keyword.arg is None:
                        for key_node, value_node in update_pairs(
                            keyword.value, statement
                        ) or []:
                            record_summary(key_node, value_node)
                    else:
                        record_summary(ast.Constant(value=keyword.arg), keyword.value)
        return list(dict.fromkeys(summaries))

    def call_parameter_argument(
        call: ast.Call,
        function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
        name: str,
        bound_offset: int,
    ) -> ast.AST | None:
        parameter = callable_parameter(function, name)
        if parameter is None:
            return None
        kind, index = parameter
        keyword_value = next(
            (keyword.value for keyword in call.keywords if keyword.arg == name),
            None,
        )
        if keyword_value is not None:
            return keyword_value
        if kind == "keyword_only":
            return function.args.kw_defaults[index]
        positional = [*function.args.posonlyargs, *function.args.args]
        explicit_index = index - bound_offset
        if 0 <= explicit_index < len(call.args):
            return call.args[explicit_index]
        default_offset = len(positional) - len(function.args.defaults)
        if index >= default_offset:
            return function.args.defaults[index - default_offset]
        return None

    def helper_return_values(
        call: ast.Call,
    ) -> list[ast.AST] | None:
        functions = resolved_local_callables(call.func, call)
        if not functions:
            return None
        resolved: list[ast.AST] = []
        for function, bound_offset in functions:
            returns = (
                [function.body]
                if isinstance(function, ast.Lambda)
                else [
                    node.value
                    for node in ast.walk(function)
                    if isinstance(node, ast.Return)
                    and node.value is not None
                    and node_scope.get(node) is function
                ]
            )
            for value in returns:
                if isinstance(value, ast.Name):
                    if callable_parameter(function, value.id) is not None:
                        argument = call_parameter_argument(
                            call, function, value.id, bound_offset
                        )
                        if argument is None:
                            continue
                        resolved.append(argument)
                        continue
                    binding = stable_binding_node(value.id, value)
                    if binding is not None:
                        if (
                            binding_may_embed_literal(binding)
                            or expression_has_production_marker(binding)
                        ):
                            resolved.append(binding)
                        continue
                resolved.append(value)
        return resolved or None

    def helper_return_mapping_pairs(
        call: ast.Call,
    ) -> list[tuple[ast.AST, ast.AST]]:
        resolved_pairs: list[tuple[ast.AST, ast.AST]] = []
        for function, bound_offset in resolved_local_callables(call.func, call):
            returns = (
                [function.body]
                if isinstance(function, ast.Lambda)
                else [
                    node.value
                    for node in ast.walk(function)
                    if isinstance(node, ast.Return)
                    and node.value is not None
                    and node_scope.get(node) is function
                ]
            )
            for returned in returns:
                if isinstance(returned, ast.Name) and callable_parameter(
                    function, returned.id
                ) is None:
                    binding = stable_binding_node(returned.id, returned)
                    if binding is not None:
                        returned = binding
                pairs = update_pairs(returned, returned)
                if pairs is None:
                    continue
                for key_node, value_node in pairs:
                    if isinstance(key_node, ast.Name) and callable_parameter(
                        function, key_node.id
                    ) is not None:
                        argument = call_parameter_argument(
                            call, function, key_node.id, bound_offset
                        )
                        if argument is None:
                            continue
                        key_node = argument
                    if isinstance(value_node, ast.Name) and callable_parameter(
                        function, value_node.id
                    ) is not None:
                        argument = call_parameter_argument(
                            call, function, value_node.id, bound_offset
                        )
                        if argument is None:
                            continue
                        value_node = argument
                    resolved_pairs.append((key_node, value_node))
        return resolved_pairs

    def is_partial_factory(
        function: ast.AST,
        reference: ast.AST,
        seen: frozenset[tuple[int, str]] = frozenset(),
    ) -> bool:
        if canonical_call_name(function) == "functools.partial":
            return True
        if not isinstance(function, ast.Name):
            return False
        scope = node_scope.get(reference, tree)
        identity = (id(scope), function.id)
        if identity in seen:
            return False
        resolved = effective_binding_entries(function.id, reference)
        return bool(
            resolved is not None
            and any(
                is_partial_factory(binding, binding, seen | {identity})
                for _line, _column, binding, _owner in resolved[1]
            )
        )

    def resolved_partial_constructors(
        function: ast.AST,
        reference: ast.AST,
        seen: frozenset[tuple[int, str]] = frozenset(),
    ) -> list[ast.Call]:
        if isinstance(function, ast.Call) and is_partial_factory(
            function.func, function
        ):
            return [function]
        if not isinstance(function, ast.Name):
            return []
        scope = node_scope.get(reference, tree)
        identity = (id(scope), function.id)
        if identity in seen:
            return []
        resolved = effective_binding_entries(function.id, reference)
        if resolved is None:
            return []
        constructors: list[ast.Call] = []
        for _line, _column, binding, _owner in resolved[1]:
            constructors.extend(
                resolved_partial_constructors(binding, binding, seen | {identity})
            )
        return list(dict.fromkeys(constructors))

    def inspect_partial_invocation(call: ast.Call) -> None:
        for constructor in resolved_partial_constructors(call.func, call):
            if not constructor.args:
                continue
            sink = resolved_sink_function(constructor.args[0], constructor)
            if sink is None:
                continue
            combined = [*constructor.args[1:], *call.args]
            if sink[0] == "key_value":
                _kind, key_index, value_index = sink
                if key_index < len(combined) and value_index < len(combined):
                    inspect_keyed_mutation(
                        combined[key_index], combined[value_index]
                    )
            elif sink[0] == "pairs":
                for argument in combined:
                    for key_node, value_node in update_pairs(argument, call) or []:
                        inspect_keyed_mutation(key_node, value_node)
                for keyword in (*constructor.keywords, *call.keywords):
                    if keyword.arg is not None:
                        inspect_keyed_mutation(
                            ast.Constant(value=keyword.arg), keyword.value
                        )

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            keys = [key for target in targets for key in target_keys(target)]
            value_node = node.value
            resolved_value = resolved_static_text(value_node)
            if resolved_value is not None:
                add_generic_static_occurrences(value_node, resolved_value)
            if isinstance(value_node, ast.Call):
                for key_node, returned_value in helper_return_mapping_pairs(
                    value_node
                ):
                    inspect_keyed_mutation(key_node, returned_value)
            for key in keys:
                if _sensitive_key(key):
                    inspect_sensitive_value(value_node, key_hint=key)
                    if isinstance(value_node, ast.Call):
                        for returned in helper_return_values(value_node) or []:
                            inspect_sensitive_value(returned, key_hint=key)
                    break
            for target in targets:
                for candidate in ast.walk(target):
                    if isinstance(candidate, ast.Subscript):
                        inspect_keyed_mutation(candidate.slice, value_node)
        if isinstance(node, (ast.NamedExpr, ast.AugAssign)):
            for key in target_keys(node.target):
                if _sensitive_key(key):
                    inspect_sensitive_value(node.value, key_hint=key)
                    break
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr):
                pairs = update_pairs(node.value, node)
                if pairs is None:
                    if expression_has_production_marker(node.value):
                        inspect_sensitive_value(node.value, key_hint="credential")
                else:
                    for key_node, value_node in pairs:
                        inspect_keyed_mutation(key_node, value_node)
        if isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is not None:
                    inspect_keyed_mutation(key_node, value_node)
        if isinstance(node, ast.DictComp):
            for key_node, value_node in closed_dict_comprehension_pairs(node) or []:
                inspect_keyed_mutation(key_node, value_node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = node.args
            positional = [*arguments.posonlyargs, *arguments.args]
            for argument, default in zip(
                positional[-len(arguments.defaults) :] if arguments.defaults else [],
                arguments.defaults,
            ):
                if (
                    _sensitive_key(argument.arg)
                ):
                    inspect_sensitive_value(default, key_hint=argument.arg)
            for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
                if (
                    default is not None
                    and _sensitive_key(argument.arg)
                ):
                    inspect_sensitive_value(default, key_hint=argument.arg)
        if isinstance(node, ast.Call):
            inspect_partial_invocation(node)
            sink = resolved_sink_function(node.func, node)
            if sink is not None and sink[0] == "key_value":
                _kind, key_index, value_index = sink
                if key_index < len(node.args) and value_index < len(node.args):
                    inspect_keyed_mutation(
                        node.args[key_index], node.args[value_index]
                    )
            elif sink is not None and sink[0] == "pairs" and node.args:
                for argument in node.args:
                    pairs = update_pairs(argument, node)
                    if pairs is None:
                        if expression_has_production_marker(argument):
                            inspect_sensitive_value(argument, key_hint="credential")
                        continue
                    for key_node, value_node in pairs:
                        inspect_keyed_mutation(key_node, value_node)
            if sink is not None and sink[0] == "pairs":
                for keyword in node.keywords:
                    if keyword.arg is None:
                        pairs = update_pairs(keyword.value, node)
                        if pairs is None:
                            if expression_has_production_marker(keyword.value):
                                inspect_sensitive_value(
                                    keyword.value, key_hint="credential"
                                )
                            continue
                        for key_node, value_node in pairs:
                            inspect_keyed_mutation(key_node, value_node)
                    else:
                        inspect_keyed_mutation(
                            ast.Constant(value=keyword.arg), keyword.value
                        )

            for helper, bound_offset in resolved_local_callables(node.func, node):
                for key_name, fixed_key, value_name in helper_sink_summary(helper):
                    key_argument = (
                        call_parameter_argument(
                            node, helper, key_name, bound_offset
                        )
                        if key_name is not None
                        else ast.Constant(value=fixed_key)
                    )
                    value_argument = call_parameter_argument(
                        node, helper, value_name, bound_offset
                    )
                    if key_argument is not None and value_argument is not None:
                        inspect_keyed_mutation(key_argument, value_argument)

            if call_name(node.func) in {"compile", "builtins.compile", "eval", "builtins.eval", "exec", "builtins.exec"} and node.args:
                compiled_source = resolved_static_text(node.args[0])
                if compiled_source is not None:
                    add_generic_static_occurrences(node.args[0], compiled_source)
            if call_name(node.func) in {"setattr", "builtins.setattr"} and len(node.args) >= 3:
                key = static_text(node.args[1])
                if key is not None and _sensitive_key(key):
                    inspect_sensitive_value(node.args[2], key_hint=key)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "__setitem__" and len(node.args) >= 2:
                key = static_text(node.args[0])
                if key is not None and _sensitive_key(key):
                    inspect_sensitive_value(node.args[1], key_hint=key)
            for keyword in node.keywords:
                if (
                    keyword.arg is not None
                    and _sensitive_key(keyword.arg)
                ):
                    inspect_sensitive_value(keyword.value, key_hint=keyword.arg)
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            literal = node.value.decode("utf-8", "surrogateescape") if isinstance(node.value, bytes) else node.value
            span = _node_span(node, offsets, text)
            if span is not None:
                for occurrence in _generic_credential_occurrences(literal):
                    value = str(occurrence["value"])
                    if not _safe_reference(value):
                        rows.append({"start": span[0], "end": span[1], "value": value})
    return rows


def _python_literal_and_comment_view(
    text: str, *, include_literals: bool = True
) -> str | None:
    """Mask executable Python while retaining literal/comment bytes and offsets.

    Credential syntax in identifiers such as an authorization variable loaded
    from a mapping
    is not a credential literal.  Actual embedded credentials still reside in a
    string/bytes literal or comment, while statically concatenated assignments
    are handled by the AST detector above.
    """

    try:
        compile(text, "<public-scan>", "exec", ast.PyCF_ONLY_AST)
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        keep: list[tuple[int, int]] = []
        offsets = _line_offsets(text)
        wanted = {tokenize.COMMENT}
        if include_literals:
            wanted.add(tokenize.STRING)
        for token in tokens:
            if token.type not in wanted:
                continue
            (start_line, start_column), (end_line, end_column) = (
                token.start,
                token.end,
            )
            if not (
                1 <= start_line <= len(offsets)
                and 1 <= end_line <= len(offsets)
            ):
                return None
            keep.append(
                (
                    offsets[start_line - 1] + start_column,
                    offsets[end_line - 1] + end_column,
                )
            )
    except (IndentationError, SyntaxError, tokenize.TokenError, UnicodeError):
        return None
    masked = [character if character in "\r\n" else " " for character in text]
    for start, end in keep:
        if not (0 <= start <= end <= len(text)):
            return None
        masked[start:end] = text[start:end]
    return "".join(masked)


def _json_credential_occurrences(text: str) -> list[dict[str, Any]]:
    class _ObjectPairs(list[tuple[str, Any]]):
        pass

    try:
        value = json.loads(text, object_pairs_hook=_ObjectPairs)
    except (json.JSONDecodeError, RecursionError):
        return []
    wanted: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, _ObjectPairs):
            for key, child in item:
                if _sensitive_key(str(key)) and isinstance(child, str) and not _safe_reference(child):
                    wanted.append(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    rows: list[dict[str, Any]] = []
    cursor = 0
    for secret in wanted:
        encoded = json.dumps(secret, ensure_ascii=False)
        start = text.find(encoded, cursor)
        if start < 0:
            start = text.find(encoded)
        if start >= 0:
            rows.append({"start": start, "end": start + len(encoded), "value": secret})
            cursor = start + len(encoded)
    return rows


def _generic_credential_occurrences(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    patterns = (
        re.compile(r"(?im)^(?P<key>authorization|proxy-authorization|cookie|set-cookie|x-api-key)\s*:\s*(?P<value>[^\r\n]+)$"),
        re.compile(
            r"(?i)(?<![A-Za-z0-9_.?&-])"
            r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*[:=]\s*"
            r"(?P<value>\$\{[^{}\r\n]+\}|\{\{[^{}\r\n]+\}\}|"
            r"\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s&;,}\]\r\n]+)"
        ),
        re.compile(r"(?i)\b(?P<key>bearer)\s+(?P<value>[A-Za-z0-9._~+/-]{8,}={0,2})"),
        re.compile(r"(?i)[?&](?P<key>access_token|api_key|apikey|password|secret|token)=(?P<value>[^&#\s]+)"),
    )
    seen: set[tuple[int, int, str]] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            key = match.group("key")
            value = match.group("value").strip()
            if (key.lower() == "bearer" or _sensitive_key(key)) and not _safe_reference(value):
                start, end = match.span("value")
                identity = (start, end, value)
                if identity not in seen:
                    seen.add(identity)
                    candidates.append({"start": start, "end": end, "value": value})
    # Prefer the narrow decoded value over a broad header value that contains
    # it (for example ``Authorization: Bearer <value>`` or cookie assignments).
    # This preserves every disjoint credential while giving synthetic-fixture
    # classification the actual scalar instead of surrounding syntax.
    rows: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda row: (int(row["end"]) - int(row["start"]), int(row["start"])),
    ):
        start = int(candidate["start"])
        end = int(candidate["end"])
        if any(
            start <= int(existing["start"])
            and int(existing["end"]) <= end
            for existing in rows
        ):
            continue
        rows.append(candidate)
    rows.sort(key=lambda row: (int(row["start"]), int(row["end"]), str(row["value"])))
    return rows


def _credential_occurrences(text: str, repository_paths: Sequence[str]) -> list[dict[str, Any]]:
    suffixes = {PurePosixPath(path).suffix.lower() for path in repository_paths}
    structured: list[dict[str, Any]] = []
    generic_text = text
    if suffixes and suffixes <= {".py"}:
        try:
            ast.parse(text)
        except (SyntaxError, ValueError):
            pass
        else:
            structured = _python_literal_credential_occurrences(text, repository_paths)
            generic_text = (
                _python_literal_and_comment_view(text, include_literals=False) or text
            )
    elif suffixes and suffixes <= {".json"}:
        try:
            json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            pass
        else:
            structured = _json_credential_occurrences(text)

    generic = _generic_credential_occurrences(generic_text)
    # Generic syntax catches credentials embedded in literals/comments, while
    # structured parsing safely folds closed Python string concatenations and
    # catches quoted JSON/dict keys.  Keep both and discard only a broad AST
    # span already covered by a more precise generic span.
    # Structured Python/JSON parsing yields the decoded credential value.  It
    # takes precedence over a broader source-token regex span so a closed dummy
    # fixture cannot accidentally become non-waivable merely because its source
    # literal also contains an escaped newline or closing quote.
    rows = list(structured)
    for row in generic:
        start = int(row["start"])
        end = int(row["end"])
        if any(
            not (end <= int(existing["start"]) or start >= int(existing["end"]))
            for existing in structured
        ):
            continue
        rows.append(row)
    unique = {
        (int(row["start"]), int(row["end"]), str(row["value"])): row
        for row in rows
    }
    return [unique[key] for key in sorted(unique)]


def _shared_detector_has_unexplained_secret(
    *,
    security: Any,
    value: str,
    source: str,
    occurrences: Sequence[Mapping[str, Any]],
    ignored_spans: Sequence[tuple[int, int]] = (),
) -> bool:
    """Return true when the shared detector sees material no local rule explains.

    A single recognized token must not suppress the fail-closed fallback for a
    second secret class that this scanner does not yet model.  Replace merged
    recognized spans with an explicit safe marker while retaining their line
    boundaries, then ask the shared detector to classify the remainder.
    """

    if not security.contains_secret(value):
        return False
    spans: list[tuple[int, int]] = list(ignored_spans)
    for item in occurrences:
        if item.get("source") != source or item.get("kind") != "secret":
            continue
        start = item.get("start")
        end = item.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
            or end > len(value)
        ):
            continue
        spans.append((start, end))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    if not merged:
        return True
    parts: list[str] = []
    cursor = 0
    for start, end in merged:
        parts.append(value[cursor:start])
        line_endings = "".join(char for char in value[start:end] if char in "\r\n")
        parts.append("[REDACTED]" + line_endings)
        cursor = end
    parts.append(value[cursor:])
    return security.contains_secret("".join(parts))


def _detect(
    *,
    security: Any,
    path: str,
    data: bytes,
    appearances: list[dict[str, str]] | None,
    scan_content: bool = True,
) -> list[dict[str, Any]]:
    text = data.decode("utf-8", errors="surrogateescape") if scan_content else ""
    repository_paths = _surface_repository_paths(path, appearances)
    path_text = "\n".join(repository_paths or [path])
    python_view = (
        _python_literal_and_comment_view(text)
        if repository_paths
        and {PurePosixPath(item).suffix.lower() for item in repository_paths}
        <= {".py"}
        else None
    )
    detector_spans = _detector_literal_spans(text, repository_paths)
    raw: list[dict[str, Any]] = []

    for source in (("content", "path") if scan_content else ("path",)):
        value_text = text if source == "content" else path_text
        for match in security.PRIVATE_KEY_RE.finditer(value_text):
            raw.append({"source": source, "detector_id": "private_key", "kind": "secret",
                        "start": match.start(), "end": match.end(), "value": match.group(0)})
        for match in security.COMMON_TOKEN_RE.finditer(value_text):
            raw.append({"source": source, "detector_id": "provider_token", "kind": "secret",
                        "start": match.start(), "end": match.end(), "value": match.group(0)})
        for match in security.HOME_PATH_RE.finditer(value_text):
            raw.append({"source": source, "detector_id": "absolute_home", "kind": "absolute_home",
                        "start": match.start(), "end": match.end(), "value": match.group(0)})
        for match in PRIVATE_PROVENANCE_RE.finditer(value_text):
            raw.append({"source": source, "detector_id": "private_provenance", "kind": "private_provenance",
                        "start": match.start(), "end": match.end(), "value": match.group(0)})
    if scan_content:
        for row in _credential_occurrences(text, repository_paths):
            raw.append({"source": "content", "detector_id": "credential_literal", "kind": "secret", **row})
    if scan_content and _shared_detector_has_unexplained_secret(
        security=security,
        value=python_view if python_view is not None else text,
        source="content",
        occurrences=raw,
        ignored_spans=detector_spans,
    ):
        raw.append({"source": "content", "detector_id": "shared_detector_unclassified",
                    "kind": "secret", "start": 0, "end": len(text), "value": text})
    if _shared_detector_has_unexplained_secret(
        security=security,
        value=path_text,
        source="path",
        occurrences=raw,
    ):
        raw.append({"source": "path", "detector_id": "shared_detector_unclassified",
                    "kind": "secret", "start": 0, "end": len(path_text), "value": path_text})

    unique: dict[tuple[str, str, str, int, int, str], dict[str, Any]] = {}
    for item in raw:
        value_digest = _sha256(str(item["value"]).encode("utf-8", "surrogateescape"))
        key = (item["source"], item["detector_id"], item["kind"], item["start"], item["end"], value_digest)
        unique[key] = {**item, "value_sha256": value_digest}
    raw = list(unique.values())
    file_digest = _sha256(data)
    descriptors: list[dict[str, Any]] = []
    for item in raw:
        descriptor = {
            "source": item["source"], "detector_id": item["detector_id"], "kind": item["kind"],
            "start": item["start"], "end": item["end"], "value_sha256": item["value_sha256"],
        }
        descriptor["occurrence_id"] = _canonical_sha256(descriptor)
        descriptors.append(descriptor)
    surface_occurrence_digest = _canonical_sha256(sorted(
        descriptors,
        key=lambda item: (item["source"], item["detector_id"], item["kind"], item["start"], item["end"], item["value_sha256"]),
    ))
    findings: list[dict[str, Any]] = []
    for item, descriptor in zip(raw, descriptors):
        source = item["source"]
        value = str(item["value"])
        detector_literal = source == "content" and any(
            start <= item["start"] and item["end"] <= end for start, end in detector_spans
        )
        synthetic = (
            source == "content"
            and item["detector_id"] not in {"private_key", "provider_token"}
            and bool(repository_paths)
            and all(_is_synthetic_fixture_surface(repo_path) for repo_path in repository_paths)
            and _closed_dummy_value(value)
        )
        protocol = (
            item["kind"] == "private_provenance"
            and source == "content"
            and bool(repository_paths)
            and all(not _is_unwaivable_surface(repo_path) for repo_path in repository_paths)
        )
        allowed_reasons: list[str] = []
        if detector_literal:
            allowed_reasons.append("detector_literal")
        if synthetic:
            allowed_reasons.append("synthetic_fixture")
        if protocol:
            allowed_reasons.append("protocol_vocabulary")
        hard_reasons: list[str] = []
        if _is_unwaivable_surface(path):
            hard_reasons.append("unwaivable_surface")
        if item["detector_id"] == "private_key":
            hard_reasons.append("private_key")
        if item["detector_id"] == "provider_token":
            hard_reasons.append("provider_token")
        if item["kind"] == "absolute_home":
            hard_reasons.append("private_home")
        if source == "path" and item["kind"] == "private_provenance":
            hard_reasons.append("private_provenance_path")
        if item["kind"] == "secret" and not allowed_reasons:
            hard_reasons.append("credential")
        if hard_reasons:
            allowed_reasons = []
        waivable = not hard_reasons and bool(allowed_reasons)
        findings.append({
            "path": path,
            "file_sha256": file_digest,
            "sha256": file_digest,
            "detector_id": item["detector_id"],
            "kind": item["kind"],
            "finding_kinds": [item["kind"]],
            "occurrence_id": descriptor["occurrence_id"],
            "occurrence_set_sha256": surface_occurrence_digest,
            "finding_sources": [source],
            "synthetic_fixture_eligible": synthetic,
            "allowed_reasons": sorted(set(allowed_reasons)),
            "waivable": waivable,
            "non_waivable": not waivable,
            "non_waivable_reasons": sorted(set(hard_reasons)),
        })
    return sorted(findings, key=lambda item: (item["path"], item["detector_id"], item["kind"], item["occurrence_id"]))


def _surface_record(
    *,
    security: Any,
    path: str,
    data: bytes,
    source_kind: str,
    object_id: str | None = None,
    appearances: list[dict[str, str]] | None = None,
    scan_content: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    logical = _safe_logical_path(path, "E_PUBLIC_SCAN_SURFACE_PATH")
    record: dict[str, Any] = {
        "path": logical,
        "source_kind": source_kind,
        "sha256": _sha256(data),
        "size": len(data),
    }
    if object_id is not None:
        record["object_id"] = object_id
    if appearances is not None:
        normalized_appearances = sorted(
            (
                {"commit": item["commit"], "path": item["path"]}
                for item in appearances
            ),
            key=lambda item: (item["commit"], item["path"]),
        )
        record["appearances"] = normalized_appearances
    findings = _detect(
        security=security,
        path=logical,
        data=data,
        appearances=appearances,
        scan_content=scan_content,
    )
    return record, findings


def _scan_git(
    root: Path,
    base_commit: str,
    candidate_commit: str,
    security: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ancestry = _run_git(
        root, "merge-base", "--is-ancestor", base_commit, candidate_commit, check=False
    )
    if ancestry.returncode != 0:
        _fail("E_PUBLIC_SCAN_GIT_ANCESTRY", "base is not an ancestor")
    revisions_raw = _run_git(
        root,
        "rev-list",
        "--reverse",
        "--topo-order",
        f"{base_commit}..{candidate_commit}",
    ).stdout
    try:
        revisions = [line for line in revisions_raw.decode("ascii").splitlines() if line]
    except UnicodeDecodeError:
        _fail("E_PUBLIC_SCAN_GIT", "rev-list output is not ASCII")
    if any(SHA40_RE.fullmatch(commit) is None for commit in revisions):
        _fail("E_PUBLIC_SCAN_GIT", "rev-list returned an invalid commit")

    base_blobs = {row["object_id"] for row in _ls_tree(root, base_commit)}
    introduced: dict[str, list[dict[str, str]]] = {}
    commit_surfaces: list[tuple[int, str, bytes]] = []
    history_path_rows: list[tuple[int, str, dict[str, str]]] = []
    scanned_bytes = 0
    for revision_index, commit in enumerate(revisions, start=1):
        raw_commit = _read_git_object(root, commit, "commit")
        scanned_bytes += len(raw_commit)
        if scanned_bytes > MAX_GIT_SCAN_BYTES:
            _fail("E_PUBLIC_SCAN_GIT_LIMIT", "Git scan exceeds fixed total limit")
        commit_surfaces.append((revision_index, commit, raw_commit))
        for row in _ls_tree(root, commit):
            history_path_rows.append((revision_index, commit, row))
            object_id = row["object_id"]
            if object_id not in base_blobs:
                introduced.setdefault(object_id, []).append(
                    {"commit": commit, "path": row["path"]}
                )

    blob_cache: dict[str, bytes] = {}

    def blob(object_id: str) -> bytes:
        nonlocal scanned_bytes
        if object_id not in blob_cache:
            blob_cache[object_id] = _read_git_object(root, object_id, "blob")
            scanned_bytes += len(blob_cache[object_id])
            if scanned_bytes > MAX_GIT_SCAN_BYTES:
                _fail("E_PUBLIC_SCAN_GIT_LIMIT", "Git scan exceeds fixed total limit")
        return blob_cache[object_id]

    surfaces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for revision_index, commit, data in commit_surfaces:
        record, finding = _surface_record(
            security=security,
            path=f"git/history/commits/{revision_index:06d}",
            data=data,
            source_kind="git_commit_raw",
            object_id=commit,
        )
        surfaces.append(record)
        findings.extend(finding)
    for revision_index, commit, row in history_path_rows:
        path_data = (
            row["mode"] + "\0" + row["object_id"] + "\0" + row["path"]
        ).encode("utf-8")
        record, finding = _surface_record(
            security=security,
            path=(
                f"git/history/tree-paths/{revision_index:06d}/{row['path']}"
            ),
            data=path_data,
            source_kind="git_history_tree_path",
            object_id=row["object_id"],
            appearances=[{"commit": commit, "path": row["path"]}],
        )
        record["mode"] = row["mode"]
        surfaces.append(record)
        findings.extend(finding)
    for object_id, appearances in sorted(introduced.items()):
        appearances = sorted(
            {(item["commit"], item["path"]) for item in appearances},
            key=lambda item: item,
        )
        normalized = [
            {"commit": commit, "path": path} for commit, path in appearances
        ]
        first_path = normalized[0]["path"]
        record, finding = _surface_record(
            security=security,
            path=f"git/history/blobs/{object_id}/{first_path}",
            data=blob(object_id),
            source_kind="git_introduced_blob",
            object_id=object_id,
            appearances=normalized,
        )
        surfaces.append(record)
        findings.extend(finding)

    final_rows = _ls_tree(root, candidate_commit)
    for row in final_rows:
        data = blob(row["object_id"])
        record, finding = _surface_record(
            security=security,
            path=f"git/final/{row['path']}",
            data=data,
            source_kind="git_final_blob",
            object_id=row["object_id"],
            appearances=[{"commit": candidate_commit, "path": row["path"]}],
        )
        surfaces.append(record)
        findings.extend(finding)
    return surfaces, findings, {
        "new_commit_count": len(revisions),
        "introduced_blob_count": len(introduced),
        "history_tree_path_count": len(history_path_rows),
        "final_blob_path_count": len(final_rows),
    }


def _read_regular_file(path: Path, *, max_bytes: int, code: str) -> bytes:
    try:
        path_before = path.lstat()
    except OSError:
        _fail(code, "file is missing")
    if (
        not stat.S_ISREG(path_before.st_mode)
        or stat.S_ISLNK(path_before.st_mode)
        or path_before.st_size > max_bytes
        or path_before.st_nlink != 1
        or path_before.st_uid != os.geteuid()
        or path_before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        _fail(code, "file is not a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        _fail(code, "file cannot be opened securely")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > max_bytes
            or before.st_nlink != 1
            or before.st_uid != os.geteuid()
            or before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            _fail(code, "opened object is not a bounded private regular file")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                _fail(code, "file ended while scanning")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail(code, "file grew while scanning")
        after = os.fstat(descriptor)
        data = b"".join(chunks)
    except OSError:
        _fail(code, "file cannot be read stably")
    finally:
        os.close(descriptor)
    try:
        path_after = path.lstat()
    except OSError:
        _fail(code, "file path disappeared while scanning")
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode", "st_nlink", "st_uid")
    if any(getattr(path_before, field) != getattr(before, field) for field in identity):
        _fail(code, "file identity changed before secure open")
    if any(getattr(before, field) != getattr(after, field) for field in identity):
        _fail(code, "file changed while scanning")
    if any(getattr(after, field) != getattr(path_after, field) for field in identity):
        _fail(code, "file path was replaced while scanning")
    if len(data) != before.st_size:
        _fail(code, "file size changed while scanning")
    return data


def _scanner_source_bytes() -> bytes:
    """Return the immutable import source or securely read the standalone file."""

    if type(_GOAL_TEAMS_FROZEN_SCANNER_SOURCE_BYTES) is bytes:
        if len(_GOAL_TEAMS_FROZEN_SCANNER_SOURCE_BYTES) > MAX_GIT_OBJECT_BYTES:
            _fail("E_PUBLIC_SCAN_CHECKER_DIGEST", "frozen scanner source is too large")
        return _GOAL_TEAMS_FROZEN_SCANNER_SOURCE_BYTES
    return _read_regular_file(
        Path(__file__),
        max_bytes=MAX_GIT_OBJECT_BYTES,
        code="E_PUBLIC_SCAN_CHECKER_DIGEST",
    )


if _IMPORTED_SCANNER_BLOB_SHA256 is None:
    _IMPORTED_SCANNER_BLOB_SHA256 = _sha256(_scanner_source_bytes())


def _snapshot_census(snapshot_root: Path) -> tuple[tuple[Any, ...], ...]:
    rows: list[tuple[Any, ...]] = []

    def add(path: Path, relative: str, expected: str) -> None:
        try:
            metadata = path.lstat()
        except OSError:
            _fail("E_PUBLIC_SCAN_SNAPSHOT_CHANGED", "snapshot member disappeared")
        if path.is_symlink():
            _fail("E_PUBLIC_SCAN_SNAPSHOT_TYPE", "snapshot contains symlink")
        if expected == "directory" and not stat.S_ISDIR(metadata.st_mode):
            _fail("E_PUBLIC_SCAN_SNAPSHOT_TYPE", "snapshot directory type drift")
        if expected == "file" and not stat.S_ISREG(metadata.st_mode):
            _fail("E_PUBLIC_SCAN_SNAPSHOT_TYPE", "snapshot contains special file")
        content_digest = None
        if expected == "file":
            content_digest = _sha256(
                _read_regular_file(
                    path,
                    max_bytes=MAX_SNAPSHOT_FILE_BYTES,
                    code="E_PUBLIC_SCAN_SNAPSHOT_CHANGED",
                )
            )
        rows.append(
            (
                expected,
                relative,
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                content_digest,
            )
        )

    add(snapshot_root, ".", "directory")

    def walk_error(_error: OSError) -> None:
        _fail("E_PUBLIC_SCAN_SNAPSHOT_CHANGED", "snapshot traversal failed")

    for current, directory_names, file_names in os.walk(
        snapshot_root, topdown=True, followlinks=False, onerror=walk_error
    ):
        directory = Path(current)
        directory_names.sort()
        for name in directory_names:
            child = directory / name
            relative = _safe_logical_path(
                child.relative_to(snapshot_root).as_posix(),
                "E_PUBLIC_SCAN_SNAPSHOT_PATH",
            )
            add(child, relative, "directory")
        for name in sorted(file_names):
            child = directory / name
            relative = _safe_logical_path(
                child.relative_to(snapshot_root).as_posix(),
                "E_PUBLIC_SCAN_SNAPSHOT_PATH",
            )
            add(child, relative, "file")
    return tuple(sorted(rows, key=lambda item: (item[1], item[0])))


def _snapshot_mode(metadata_mode: int) -> str:
    permissions = stat.S_IMODE(metadata_mode)
    if permissions not in {0o644, 0o755}:
        _fail("E_PUBLIC_SCAN_SNAPSHOT_MODE", "snapshot mode is not canonical")
    return f"100{permissions:03o}"


def _snapshot_package_path(path: str, version: str) -> bool:
    return path not in SNAPSHOT_OUTER_PATHS and path != (
        f"_artifacts/goal-teams-{version}.tar.gz"
    )


def _scan_snapshot(
    snapshot_root: Path, version: str, security: Any
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    set[str],
    dict[str, dict[str, Any]],
]:
    if not snapshot_root.is_dir() or snapshot_root.is_symlink():
        _fail("E_PUBLIC_SCAN_SNAPSHOT_ROOT", "snapshot root is not a directory")
    surfaces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    paths: set[str] = set()
    package_entries: dict[str, dict[str, Any]] = {}
    total = 0
    before = _snapshot_census(snapshot_root)
    for kind, relative, _dev, _ino, metadata_mode, _size, _mtime, _content_digest in before:
        if kind != "file":
            continue
        child = snapshot_root / relative
        if relative in paths:
            _fail("E_PUBLIC_SCAN_SNAPSHOT_DUPLICATE", "duplicate snapshot path")
        data = _read_regular_file(
            child,
            max_bytes=MAX_SNAPSHOT_FILE_BYTES,
            code="E_PUBLIC_SCAN_SNAPSHOT_TYPE",
        )
        total += len(data)
        if total > MAX_SNAPSHOT_BYTES:
            _fail("E_PUBLIC_SCAN_SNAPSHOT_LIMIT", "snapshot exceeds total limit")
        mode = _snapshot_mode(int(metadata_mode))
        paths.add(relative)
        record, finding = _surface_record(
            security=security,
            path=f"snapshot/{relative}",
            data=data,
            source_kind="package_snapshot_file",
            scan_content=relative
            != f"_artifacts/goal-teams-{version}.tar.gz",
        )
        record["mode"] = mode
        surfaces.append(record)
        if _snapshot_package_path(relative, version):
            package_entries[relative] = {
                "sha256": _sha256(data),
                "size": len(data),
                "mode": mode,
            }
        findings.extend(finding)
    after = _snapshot_census(snapshot_root)
    if before != after:
        _fail("E_PUBLIC_SCAN_SNAPSHOT_CHANGED", "snapshot membership changed while scanning")
    if OKF_GENERATED_PATH not in paths:
        _fail("E_PUBLIC_SCAN_OKF_MISSING", "generated OKF is absent from snapshot")
    return surfaces, findings, paths, package_entries


def _safe_tar_relative(name: str, version: str) -> str:
    prefix = f"goal-teams-{version}"
    expected_prefix = prefix + "/"
    if not name.startswith(expected_prefix):
        _fail("E_PUBLIC_SCAN_TAR_PATH", "tar member is outside package prefix")
    relative = name[len(expected_prefix) :]
    if len(relative.encode("utf-8")) > TAR_LIMITS["max_path_bytes"]:
        _fail("E_PUBLIC_SCAN_TAR_LIMIT", "tar path exceeds fixed limit")
    return _safe_logical_path(relative, "E_PUBLIC_SCAN_TAR_PATH")


def _gunzip_canonical_candidate(tar_data: bytes) -> bytes:
    if (
        len(tar_data) < 18
        or tar_data[:4] != b"\x1f\x8b\x08\x00"
        or tar_data[4:8] != b"\x00\x00\x00\x00"
        or tar_data[8:10] != b"\x02\xff"
    ):
        _fail("E_PUBLIC_SCAN_GZIP_METADATA", "gzip header is not canonical")
    chunks: list[bytes] = []
    total = 0
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(tar_data), mode="rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_TAR_STREAM_BYTES:
                    _fail("E_PUBLIC_SCAN_TAR_LIMIT", "tar stream exceeds fixed limit")
                chunks.append(chunk)
    except PublicScanError:
        raise
    except (EOFError, OSError, zlib.error) as exc:
        _fail("E_PUBLIC_SCAN_TAR_FORMAT", type(exc).__name__)
    return b"".join(chunks)


def _canonical_archive_bytes(
    version: str, entries: list[tuple[str, bytes, int]]
) -> tuple[bytes, bytes]:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for relative, data, mode in sorted(entries, key=lambda item: item[0]):
            info = tarfile.TarInfo(f"goal-teams-{version}/{relative}")
            info.size = len(data)
            info.mode = mode
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as stream:
        stream.write(raw.getvalue())
    return raw.getvalue(), compressed.getvalue()


def _scan_tar(
    tar_data: bytes, version: str, security: Any
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    set[str],
    dict[str, dict[str, Any]],
]:
    surfaces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    paths: set[str] = set()
    regular_paths: set[str] = set()
    collision_keys: set[str] = set()
    entries: dict[str, dict[str, Any]] = {}
    canonical_entries: list[tuple[str, bytes, int]] = []
    ordered_paths: list[str] = []
    total = 0
    raw_tar = _gunzip_canonical_candidate(tar_data)
    try:
        with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
            for member_count, member in enumerate(archive, start=1):
                if member_count > TAR_LIMITS["member_count"]:
                    _fail("E_PUBLIC_SCAN_TAR_LIMIT", "tar member count exceeds limit")
                relative = _safe_tar_relative(member.name, version)
                collision = unicodedata.normalize("NFC", relative).casefold()
                if relative in paths or collision in collision_keys:
                    _fail("E_PUBLIC_SCAN_TAR_DUPLICATE", "duplicate tar path")
                paths.add(relative)
                collision_keys.add(collision)
                if member.pax_headers:
                    _fail("E_PUBLIC_SCAN_TAR_TYPE", "pax metadata is forbidden")
                if member.type != tarfile.REGTYPE or not member.isfile():
                    _fail("E_PUBLIC_SCAN_TAR_TYPE", "link/device/special member")
                if (
                    member.mode not in {0o644, 0o755}
                    or member.mtime != 0
                    or member.uid != 0
                    or member.gid != 0
                    or member.uname != "root"
                    or member.gname != "root"
                    or member.linkname
                ):
                    _fail("E_PUBLIC_SCAN_TAR_METADATA", "tar metadata is not canonical")
                regular_paths.add(relative)
                ordered_paths.append(relative)
                if (
                    member.size < 0
                    or member.size > TAR_LIMITS["max_single_file_bytes"]
                ):
                    _fail("E_PUBLIC_SCAN_TAR_LIMIT", "tar file exceeds fixed limit")
                total += member.size
                if total > TAR_LIMITS["max_total_uncompressed_bytes"]:
                    _fail("E_PUBLIC_SCAN_TAR_LIMIT", "tar total exceeds fixed limit")
                stream = archive.extractfile(member)
                if stream is None:
                    _fail("E_PUBLIC_SCAN_TAR_READ", "regular member is unreadable")
                chunks: list[bytes] = []
                read_size = 0
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    read_size += len(chunk)
                    if read_size > member.size:
                        _fail("E_PUBLIC_SCAN_TAR_READ", "member grew while reading")
                if read_size != member.size:
                    _fail("E_PUBLIC_SCAN_TAR_READ", "member is truncated")
                data = b"".join(chunks)
                mode = f"100{member.mode:03o}"
                entries[relative] = {
                    "sha256": _sha256(data),
                    "size": len(data),
                    "mode": mode,
                }
                canonical_entries.append((relative, data, member.mode))
                record, finding = _surface_record(
                    security=security,
                    path=f"tar/{relative}",
                    data=data,
                    source_kind="release_tar_member",
                )
                record["mode"] = mode
                surfaces.append(record)
                findings.extend(finding)
    except PublicScanError:
        raise
    except (tarfile.TarError, OSError) as exc:
        _fail("E_PUBLIC_SCAN_TAR_FORMAT", type(exc).__name__)
    if ordered_paths != sorted(ordered_paths):
        _fail("E_PUBLIC_SCAN_TAR_CANONICAL", "tar member order is not canonical")
    canonical_tar, canonical_gzip = _canonical_archive_bytes(version, canonical_entries)
    if raw_tar != canonical_tar or tar_data != canonical_gzip:
        _fail("E_PUBLIC_SCAN_TAR_CANONICAL", "tar/gzip bytes are not canonical")
    if total and total / max(1, len(tar_data)) > TAR_LIMITS["max_compression_ratio"]:
        _fail("E_PUBLIC_SCAN_TAR_LIMIT", "tar compression ratio exceeds limit")
    if OKF_GENERATED_PATH not in regular_paths:
        _fail("E_PUBLIC_SCAN_OKF_MISSING", "generated OKF is absent from tar")
    return surfaces, findings, regular_paths, entries


def _scan_outer_surfaces(
    *,
    asset_paths: Mapping[str, Path],
    version: str,
    tag_message: str,
    release_title: str,
    release_body: str,
    security: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bytes]:
    expected = {
        f"goal-teams-{version}.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    }
    if set(asset_paths) != expected:
        _fail("E_PUBLIC_SCAN_ASSET_SET", "assets are not the fixed four")
    surfaces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    tar_data: bytes | None = None
    for name in sorted(expected):
        path = Path(asset_paths[name])
        data = _read_regular_file(
            path, max_bytes=MAX_SNAPSHOT_BYTES, code="E_PUBLIC_SCAN_ASSET_FILE"
        )
        if name.endswith(".tar.gz"):
            tar_data = data
            record = {
                "path": f"asset/{name}",
                "source_kind": "outer_release_asset",
                "sha256": _sha256(data),
                "size": len(data),
            }
            surfaces.append(record)
            continue
        record, finding = _surface_record(
            security=security,
            path=f"asset/{name}",
            data=data,
            source_kind="outer_release_asset",
        )
        surfaces.append(record)
        findings.extend(finding)
    if tar_data is None:
        _fail("E_PUBLIC_SCAN_ASSET_SET", "tar asset is absent")
    for name, value in (
        ("release/tag-message", tag_message),
        ("release/title", release_title),
        ("release/body", release_body),
    ):
        if not isinstance(value, str):
            _fail("E_PUBLIC_SCAN_RELEASE_TEXT", "release text must be a string")
        record, finding = _surface_record(
            security=security,
            path=name,
            data=value.encode("utf-8"),
            source_kind="canonical_release_text",
        )
        surfaces.append(record)
        findings.extend(finding)
    return surfaces, findings, tar_data


def _candidate_reasons(finding: Mapping[str, Any]) -> list[str]:
    reasons = finding.get("allowed_reasons")
    return list(reasons) if isinstance(reasons, list) else []


def _apply_baseline(
    findings: list[dict[str, Any]], baseline: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    assertions = baseline["assertions"]
    identity_fields = (
        "path",
        "file_sha256",
        "detector_id",
        "kind",
        "occurrence_id",
        "occurrence_set_sha256",
    )
    by_identity = {
        tuple(item[field] for field in identity_fields): item for item in assertions
    }
    used: set[tuple[str, ...]] = set()
    waived: list[dict[str, Any]] = []
    unwaived: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for finding in sorted(
        findings,
        key=lambda item: (
            item["path"],
            item["file_sha256"],
            item["detector_id"],
            item["kind"],
            item["occurrence_id"],
        ),
    ):
        identity = tuple(finding[field] for field in identity_fields)
        assertion = by_identity.get(identity)
        reason_is_compatible = bool(
            assertion is not None
            and assertion.get("reason") in finding.get("allowed_reasons", [])
        )
        if (
            assertion is not None
            and finding["waivable"] is True
            and bool(finding.get("allowed_reasons"))
            and reason_is_compatible
        ):
            used.add(identity)
            waived.append(
                {
                    "path": finding["path"],
                    "file_sha256": finding["file_sha256"],
                    "sha256": finding["file_sha256"],
                    "detector_id": finding["detector_id"],
                    "kind": finding["kind"],
                    "finding_kinds": [finding["kind"]],
                    "occurrence_id": finding["occurrence_id"],
                    "occurrence_set_sha256": finding["occurrence_set_sha256"],
                    "reason": assertion["reason"],
                }
            )
            continue
        unwaived.append(finding)
        candidates.append(
            {
                "path": finding["path"],
                "file_sha256": finding["file_sha256"],
                "sha256": finding["file_sha256"],
                "detector_id": finding["detector_id"],
                "kind": finding["kind"],
                "finding_kinds": [finding["kind"]],
                "occurrence_id": finding["occurrence_id"],
                "occurrence_set_sha256": finding["occurrence_set_sha256"],
                "waivable": finding["waivable"],
                "allowed_reasons": (
                    _candidate_reasons(finding)
                    if finding["waivable"] is True
                    else []
                ),
            }
        )
        errors.append(
            "unwaived_finding:"
            + finding["path"]
            + ":"
            + finding["file_sha256"]
            + ":"
            + finding["occurrence_id"]
        )
    for identity, assertion in sorted(by_identity.items()):
        if identity not in used:
            errors.append(
                "stale_baseline_assertion:"
                + assertion["path"]
                + ":"
                + assertion["file_sha256"]
                + ":"
                + assertion["occurrence_id"]
            )
    return waived, unwaived, candidates, sorted(errors)


def _assert_portable(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_portable(key)
            _assert_portable(item)
    elif isinstance(value, list):
        for item in value:
            _assert_portable(item)
    elif isinstance(value, str):
        absolute_home_receipt_re = re.compile(
            r"(?:/" + r"Users/|/" + r"home/[^/]+/|[A-Za-z]:\\" + r"Users\\)"
        )
        if absolute_home_receipt_re.search(value):
            _fail("E_PUBLIC_SCAN_RECEIPT_PATH", "receipt contains an absolute home")


def scan_surfaces(
    *,
    source_root: str | os.PathLike[str],
    base_commit: str,
    candidate_commit: str,
    candidate_tree: str,
    version: str,
    snapshot_root: str | os.PathLike[str],
    asset_paths: Mapping[str, str | os.PathLike[str]],
    tag_message: str,
    release_title: str,
    release_body: str,
    checker_digest: str,
    expected_detector_digest: str,
    baseline_bytes: bytes,
) -> dict[str, Any]:
    """Scan every public release surface and return a deterministic receipt."""

    if not isinstance(version, str) or VERSION_RE.fullmatch(version) is None:
        _fail("E_PUBLIC_SCAN_VERSION", "version is invalid")
    if not isinstance(checker_digest, str) or SHA256_RE.fullmatch(checker_digest) is None:
        _fail("E_PUBLIC_SCAN_CHECKER_DIGEST", "checker digest is invalid")
    if (
        not isinstance(expected_detector_digest, str)
        or SHA256_RE.fullmatch(expected_detector_digest) is None
    ):
        _fail("E_PUBLIC_SCAN_DETECTOR", "detector digest is invalid")
    scanner_bytes = _scanner_source_bytes()
    scanner_blob_sha256 = _sha256(scanner_bytes)
    if scanner_blob_sha256 != _IMPORTED_SCANNER_BLOB_SHA256:
        _fail("E_PUBLIC_SCAN_CHECKER_DIGEST", "scanner changed after import")
    if checker_digest != scanner_blob_sha256:
        _fail("E_PUBLIC_SCAN_CHECKER_DIGEST", "running scanner differs from approval")
    baseline_raw_sha256 = _sha256(baseline_bytes)
    baseline = validate_baseline(load_baseline(baseline_bytes), version=version)

    source_path = Path(source_root).expanduser()
    if source_path.is_symlink():
        _fail("E_PUBLIC_SCAN_SOURCE_ROOT", "source root is a symlink")
    root = source_path.resolve()
    if not root.is_dir() or root.is_symlink():
        _fail("E_PUBLIC_SCAN_SOURCE_ROOT", "source root is not a directory")
    _validate_git_repository(root)
    base = _require_commit(root, base_commit, "base_commit")
    candidate = _require_commit(root, candidate_commit, "candidate_commit")
    if not isinstance(candidate_tree, str) or SHA40_RE.fullmatch(candidate_tree) is None:
        _fail("E_PUBLIC_SCAN_GIT_IDENTITY", "candidate_tree is not 40-hex")
    actual_tree = _run_git(root, "rev-parse", f"{candidate}^{{tree}}").stdout.strip()
    if actual_tree.decode("ascii", errors="ignore") != candidate_tree:
        _fail("E_PUBLIC_SCAN_GIT_IDENTITY", "candidate tree drift")

    security, detector_blob_sha256 = _security_module(
        root, candidate, expected_detector_digest
    )
    surfaces: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    git_surfaces, git_findings, git_summary = _scan_git(
        root, base, candidate, security
    )
    surfaces.extend(git_surfaces)
    findings.extend(git_findings)

    snapshot_path = Path(snapshot_root).expanduser()
    if snapshot_path.is_symlink():
        _fail("E_PUBLIC_SCAN_SNAPSHOT_ROOT", "snapshot root is a symlink")
    (
        snapshot_surfaces,
        snapshot_findings,
        snapshot_paths,
        snapshot_package_entries,
    ) = _scan_snapshot(
        snapshot_path.resolve(), version, security
    )
    surfaces.extend(snapshot_surfaces)
    findings.extend(snapshot_findings)

    normalized_assets = {name: Path(path) for name, path in asset_paths.items()}
    outer_surfaces, outer_findings, tar_data = _scan_outer_surfaces(
        asset_paths=normalized_assets,
        version=version,
        tag_message=tag_message,
        release_title=release_title,
        release_body=release_body,
        security=security,
    )
    surfaces.extend(outer_surfaces)
    findings.extend(outer_findings)
    snapshot_tar_path = (
        f"snapshot/_artifacts/goal-teams-{version}.tar.gz"
    )
    snapshot_tar_record = next(
        (
            record
            for record in snapshot_surfaces
            if record.get("path") == snapshot_tar_path
        ),
        None,
    )
    if snapshot_tar_record is not None and (
        snapshot_tar_record.get("sha256") != _sha256(tar_data)
        or snapshot_tar_record.get("size") != len(tar_data)
    ):
        _fail(
            "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH",
            "snapshot canonical tar asset differs from the validated outer asset",
        )
    tar_surfaces, tar_findings, tar_paths, tar_entries = _scan_tar(
        tar_data, version, security
    )
    surfaces.extend(tar_surfaces)
    findings.extend(tar_findings)

    if snapshot_package_entries != tar_entries:
        _fail(
            "E_PUBLIC_SCAN_SNAPSHOT_TAR_MISMATCH",
            "snapshot and tar path/content/mode identities differ",
        )

    if OKF_GENERATED_PATH not in snapshot_paths or OKF_GENERATED_PATH not in tar_paths:
        _fail("E_PUBLIC_SCAN_OKF_MISSING", "generated OKF was not scanned twice")
    logical_paths = [record["path"] for record in surfaces]
    if len(logical_paths) != len(set(logical_paths)):
        _fail("E_PUBLIC_SCAN_SURFACE_DUPLICATE", "surface paths are not unique")
    surfaces.sort(key=lambda item: item["path"])
    waived, unwaived, candidates, errors = _apply_baseline(findings, baseline)
    scanned_occurrence_set_sha256 = occurrence_set_sha256(findings)
    baseline_assertions_sha256 = _canonical_sha256(baseline["assertions"])
    baseline_assertion_set_digest = assertion_set_sha256(baseline["assertions"])
    baseline_occurrence_set_digest = occurrence_set_sha256(baseline["assertions"])
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "passed": not errors,
        "identity": {
            "version": version,
            "base_commit": base,
            "candidate_commit": candidate,
            "candidate_tree": candidate_tree,
            "asset_names": sorted(normalized_assets),
        },
        "trust_bindings": {
            "scanner_blob_sha256": scanner_blob_sha256,
            "detector_blob_sha256": detector_blob_sha256,
            "baseline_blob_sha256": baseline_raw_sha256,
            "baseline_assertion_count": len(baseline["assertions"]),
            "baseline_assertions_sha256": baseline_assertions_sha256,
            "baseline_assertion_set_sha256": baseline_assertion_set_digest,
            "baseline_occurrence_set_sha256": baseline_occurrence_set_digest,
            "baseline_review_sha256": _canonical_sha256(baseline["review"]),
        },
        "coverage": {
            **git_summary,
            "snapshot_file_count": len(snapshot_paths),
            "snapshot_package_file_count": len(snapshot_package_entries),
            "tar_regular_file_count": len(tar_surfaces),
            "outer_asset_count": len(normalized_assets),
            "release_text_count": 3,
            "surface_count": len(surfaces),
            "snapshot_tar_identity_sha256": _canonical_sha256(tar_entries),
            "occurrence_set_sha256": scanned_occurrence_set_sha256,
        },
        "occurrence_set_sha256": scanned_occurrence_set_sha256,
        "surfaces": surfaces,
        "waived_findings": waived,
        "unwaived_findings": unwaived,
        "baseline_candidate_rows": candidates,
        "errors": errors,
    }
    _assert_portable(receipt)
    receipt["receipt_sha256"] = receipt_hash(receipt)
    return receipt


__all__ = [
    "assertion_set_sha256",
    "BASELINE_SCHEMA_VERSION",
    "FINDING_KINDS",
    "PublicScanError",
    "load_baseline",
    "occurrence_set_sha256",
    "receipt_hash",
    "scan_surfaces",
    "validate_baseline",
]
