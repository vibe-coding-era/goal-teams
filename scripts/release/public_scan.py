#!/usr/bin/env python3
"""Deterministic public-release scanner for Goal Teams V2.40.

The scanner is deliberately independent from the release state machine.  It
accepts only immutable Git identities, an already materialized package
snapshot, the fixed four public assets, canonical release text, a reviewed
false-positive baseline, and the expected scanner blob digest.  Its receipt
contains no wall-clock fields or local absolute paths.
"""

from __future__ import annotations

import hashlib
import gzip
import io
import json
import os
import re
import stat
import subprocess
import tarfile
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


SCHEMA_VERSION = "goal-teams-public-scan-receipt-v1"
BASELINE_SCHEMA_VERSION = "goal-teams-public-scan-baseline-v1"
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
        "placeholder_home",
    }
)
DETECTOR_LITERAL_PATHS = frozenset(
    {
        "scripts/release/public_scan.py",
        "scripts/v23/v236_security.py",
        "tests/v23/test_v236_security_redaction.py",
        "tests/v23/test_v240_public_scan.py",
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
_IMPORTED_SCANNER_BLOB_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
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


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _is_readme_surface(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return name == "readme.md" or name == "readme.en.md"


def _is_unwaivable_surface(path: str) -> bool:
    return path in {
        "release/tag-message",
        "release/title",
        "release/body",
    } or _is_readme_surface(path)


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
    if not isinstance(review, Mapping) or set(review) != {
        "reviewer_type",
        "independent",
        "decision",
        "review_id",
    }:
        _fail("E_PUBLIC_SCAN_BASELINE_REVIEW", "review fields are not closed")
    review_id = review.get("review_id")
    if (
        review.get("reviewer_type") != "independent_release_reviewer"
        or review.get("independent") is not True
        or review.get("decision") != "accepted"
        or not isinstance(review_id, str)
        or re.fullmatch(r"[A-Za-z0-9._-]{3,128}", review_id) is None
    ):
        _fail(
            "E_PUBLIC_SCAN_BASELINE_REVIEW",
            "independent release review is not accepted",
        )
    assertions = baseline.get("assertions")
    if not isinstance(assertions, list):
        _fail("E_PUBLIC_SCAN_BASELINE_ASSERTION", "assertions must be an array")
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[str, str, tuple[str, ...]]] = set()
    for assertion in assertions:
        if not isinstance(assertion, Mapping) or set(assertion) != {
            "path",
            "sha256",
            "finding_kinds",
            "reason",
        }:
            _fail(
                "E_PUBLIC_SCAN_BASELINE_ASSERTION",
                "assertion fields are not closed",
            )
        path = _safe_logical_path(
            assertion.get("path"), "E_PUBLIC_SCAN_BASELINE_PATH"
        )
        digest = assertion.get("sha256")
        kinds = assertion.get("finding_kinds")
        reason = assertion.get("reason")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            _fail("E_PUBLIC_SCAN_BASELINE_DIGEST", "assertion digest is invalid")
        if (
            not isinstance(kinds, list)
            or not kinds
            or any(not isinstance(kind, str) or kind not in FINDING_KINDS for kind in kinds)
            or kinds != sorted(set(kinds))
        ):
            _fail("E_PUBLIC_SCAN_BASELINE_KINDS", "finding kinds are not exact")
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
            or not _is_tests_or_examples_surface(repository_path)
        ):
            _fail(
                "E_PUBLIC_SCAN_BASELINE_REASON",
                "synthetic_fixture is limited to tests/examples",
            )
        if reason == "placeholder_home" and kinds != ["absolute_home"]:
            _fail(
                "E_PUBLIC_SCAN_BASELINE_REASON",
                "placeholder_home only covers absolute_home",
            )
        if reason == "protocol_vocabulary" and "private_provenance" not in kinds:
            _fail(
                "E_PUBLIC_SCAN_BASELINE_REASON",
                "protocol_vocabulary requires private_provenance",
            )
        identity = (path, digest, tuple(kinds))
        if identity in identities:
            _fail("E_PUBLIC_SCAN_BASELINE_DUPLICATE", "duplicate assertion")
        identities.add(identity)
        normalized.append(
            {
                "path": path,
                "sha256": digest,
                "finding_kinds": list(kinds),
                "reason": reason,
            }
        )
    normalized.sort(
        key=lambda item: (
            item["path"],
            item["sha256"],
            tuple(item["finding_kinds"]),
            item["reason"],
        )
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


def _synthetic_fixture_context(
    path: str,
    appearances: list[dict[str, str]] | None,
    text: str,
    security: Any,
) -> bool:
    repository_paths = _surface_repository_paths(path, appearances)
    if not repository_paths or any(
        not _is_tests_or_examples_surface(item) for item in repository_paths
    ):
        return False
    secret_lines = [
        line for line in text.splitlines() if security.contains_secret(line)
    ]
    if security.contains_secret(text) and not secret_lines:
        return False
    markers = (
        "dummy",
        "fake",
        "fixture",
        "not-a-real",
        "placeholder",
        "synthetic",
        "test-only",
        "example.invalid",
    )
    return bool(secret_lines) and all(
        any(marker in line.lower() for marker in markers)
        for line in secret_lines
    )


def _detector_literal_context(
    path: str, appearances: list[dict[str, str]] | None
) -> bool:
    repository_paths = _surface_repository_paths(path, appearances)
    return bool(repository_paths) and all(
        item in DETECTOR_LITERAL_PATHS for item in repository_paths
    )


def _protocol_vocabulary_context(
    path: str,
    appearances: list[dict[str, str]] | None,
    text: str,
    security: Any,
) -> bool:
    repository_paths = _surface_repository_paths(path, appearances)
    if not repository_paths or any(
        PurePosixPath(item).parts[0] not in {"references", "prompts"}
        for item in repository_paths
    ):
        return False
    secret_lines = [
        line for line in text.splitlines() if security.contains_secret(line)
    ]
    placeholder_markers = (
        "<",
        "{{",
        "${",
        "[redacted]",
        "dummy",
        "example",
        "fake",
        "fixture",
        "placeholder",
        "synthetic",
    )
    return not secret_lines or all(
        any(marker in line.lower() for marker in placeholder_markers)
        for line in secret_lines
    )


def _placeholder_home_context(security: Any, text: str) -> bool:
    matches = [match.group(0) for match in security.HOME_PATH_RE.finditer(text)]
    if not matches:
        return False
    allowed = {
        "/users/example",
        "/users/user",
        "/users/username",
        "/home/example",
        "/home/user",
        "/home/username",
        r"c:\users\example",
        r"c:\users\user",
        r"c:\users\username",
    }
    return all(item.lower() in allowed for item in matches)


def _detect(
    *,
    security: Any,
    path: str,
    data: bytes,
    appearances: list[dict[str, str]] | None,
) -> dict[str, Any] | None:
    text = data.decode("utf-8", errors="surrogateescape")
    repository_paths = _surface_repository_paths(path, appearances)
    path_text = "\n".join(repository_paths or [path])
    kinds: list[str] = []
    finding_sources: list[str] = []
    content_secret = security.contains_secret(text)
    path_secret = security.contains_secret(path_text)
    if content_secret or path_secret:
        kinds.append("secret")
        if content_secret:
            finding_sources.append("content")
        if path_secret:
            finding_sources.append("path")
    content_home = bool(security.HOME_PATH_RE.search(text))
    path_home = bool(security.HOME_PATH_RE.search(path_text))
    if content_home or path_home:
        kinds.append("absolute_home")
        if content_home:
            finding_sources.append("content")
        if path_home:
            finding_sources.append("path")
    content_provenance = bool(PRIVATE_PROVENANCE_RE.search(text))
    path_provenance = bool(PRIVATE_PROVENANCE_RE.search(path_text))
    if content_provenance or path_provenance:
        kinds.append("private_provenance")
        if content_provenance:
            finding_sources.append("content")
        if path_provenance:
            finding_sources.append("path")
    kinds = sorted(set(kinds))
    if not kinds:
        return None
    combined = text + "\n" + path_text
    private_key = bool(security.PRIVATE_KEY_RE.search(combined))
    provider_token = bool(security.COMMON_TOKEN_RE.search(combined))
    synthetic = _synthetic_fixture_context(
        path, appearances, text, security
    )
    detector_literal = _detector_literal_context(path, appearances)
    protocol_vocabulary = _protocol_vocabulary_context(
        path, appearances, text, security
    )
    placeholder_home = _placeholder_home_context(security, combined)
    allowed_reasons: list[str] = []
    if detector_literal:
        allowed_reasons.append("detector_literal")
    if synthetic:
        allowed_reasons.append("synthetic_fixture")
    if "private_provenance" in kinds and protocol_vocabulary:
        allowed_reasons.append("protocol_vocabulary")
    if kinds == ["absolute_home"] and placeholder_home:
        allowed_reasons.append("placeholder_home")
    hard_reasons: list[str] = []
    if _is_unwaivable_surface(path):
        hard_reasons.append("unwaivable_surface")
    if private_key:
        hard_reasons.append("private_key")
    if provider_token:
        hard_reasons.append("provider_token")
    if "secret" in kinds and not {
        "detector_literal",
        "synthetic_fixture",
        "protocol_vocabulary",
    }.intersection(allowed_reasons):
        hard_reasons.append("credential")
    if "absolute_home" in kinds and not placeholder_home and not detector_literal:
        hard_reasons.append("private_home")
    if path_provenance:
        hard_reasons.append("private_provenance_path")
    if hard_reasons:
        allowed_reasons = []
    return {
        "path": path,
        "sha256": _sha256(data),
        "finding_kinds": kinds,
        "finding_sources": sorted(set(finding_sources)),
        "synthetic_fixture_eligible": synthetic,
        "allowed_reasons": sorted(set(allowed_reasons)),
        "non_waivable": bool(hard_reasons),
        "non_waivable_reasons": sorted(hard_reasons),
    }


def _surface_record(
    *,
    security: Any,
    path: str,
    data: bytes,
    source_kind: str,
    object_id: str | None = None,
    appearances: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
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
    finding = _detect(
        security=security,
        path=logical,
        data=data,
        appearances=appearances,
    )
    return record, finding


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
        if finding:
            findings.append(finding)
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
        if finding:
            findings.append(finding)
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
        if finding:
            findings.append(finding)

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
        if finding:
            findings.append(finding)
    return surfaces, findings, {
        "new_commit_count": len(revisions),
        "introduced_blob_count": len(introduced),
        "history_tree_path_count": len(history_path_rows),
        "final_blob_path_count": len(final_rows),
    }


def _read_regular_file(path: Path, *, max_bytes: int, code: str) -> bytes:
    try:
        before = path.lstat()
    except OSError:
        _fail(code, "file is missing")
    if not stat.S_ISREG(before.st_mode) or path.is_symlink() or before.st_size > max_bytes:
        _fail(code, "file is not a bounded regular file")
    try:
        data = path.read_bytes()
        after = path.lstat()
    except OSError:
        _fail(code, "file cannot be read stably")
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in identity):
        _fail(code, "file changed while scanning")
    if len(data) != before.st_size:
        _fail(code, "file size changed while scanning")
    return data


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
        rows.append(
            (
                expected,
                relative,
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
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
    for kind, relative, _dev, _ino, metadata_mode, _size, _mtime in before:
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
        )
        record["mode"] = mode
        surfaces.append(record)
        if _snapshot_package_path(relative, version):
            package_entries[relative] = {
                "sha256": _sha256(data),
                "size": len(data),
                "mode": mode,
            }
        if finding:
            findings.append(finding)
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
                if finding:
                    findings.append(finding)
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
        if finding:
            findings.append(finding)
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
        if finding:
            findings.append(finding)
    return surfaces, findings, tar_data


def _candidate_reasons(finding: Mapping[str, Any]) -> list[str]:
    reasons = finding.get("allowed_reasons")
    return list(reasons) if isinstance(reasons, list) else []


def _apply_baseline(
    findings: list[dict[str, Any]], baseline: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    assertions = baseline["assertions"]
    by_identity = {
        (
            item["path"],
            item["sha256"],
            tuple(item["finding_kinds"]),
        ): item
        for item in assertions
    }
    used: set[tuple[str, str, tuple[str, ...]]] = set()
    waived: list[dict[str, Any]] = []
    unwaived: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for finding in sorted(
        findings,
        key=lambda item: (
            item["path"], item["sha256"], tuple(item["finding_kinds"])
        ),
    ):
        identity = (
            finding["path"],
            finding["sha256"],
            tuple(finding["finding_kinds"]),
        )
        assertion = by_identity.get(identity)
        reason_is_compatible = bool(
            assertion is not None
            and assertion.get("reason") in finding.get("allowed_reasons", [])
        )
        if (
            assertion is not None
            and finding["non_waivable"] is not True
            and reason_is_compatible
        ):
            used.add(identity)
            waived.append(
                {
                    "path": finding["path"],
                    "sha256": finding["sha256"],
                    "finding_kinds": finding["finding_kinds"],
                    "reason": assertion["reason"],
                }
            )
            continue
        unwaived.append(finding)
        candidates.append(
            {
                "path": finding["path"],
                "sha256": finding["sha256"],
                "finding_kinds": finding["finding_kinds"],
                "waivable": finding["non_waivable"] is not True,
                "allowed_reasons": (
                    _candidate_reasons(finding)
                    if finding["non_waivable"] is not True
                    else []
                ),
            }
        )
        errors.append(
            "unwaived_finding:"
            + finding["path"]
            + ":"
            + finding["sha256"]
        )
    for identity, assertion in sorted(by_identity.items()):
        if identity not in used:
            errors.append(
                "stale_baseline_assertion:"
                + assertion["path"]
                + ":"
                + assertion["sha256"]
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
        if re.search(r"(?:/Users/|/home/[^/]+/|[A-Za-z]:\\Users\\)", value):
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
    scanner_bytes = _read_regular_file(
        Path(__file__),
        max_bytes=MAX_GIT_OBJECT_BYTES,
        code="E_PUBLIC_SCAN_CHECKER_DIGEST",
    )
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
        },
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
    "BASELINE_SCHEMA_VERSION",
    "FINDING_KINDS",
    "PublicScanError",
    "load_baseline",
    "receipt_hash",
    "scan_surfaces",
    "validate_baseline",
]
