#!/usr/bin/env python3
"""Standalone Goal Teams V2.45 Release Engineer deterministic runtime."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PACKAGE_ROOT = SCRIPT.parents[1]
KITS_ROOT = PACKAGE_ROOT / "kits"
CATALOG_PATH = KITS_ROOT / "catalog.json"

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
ACCEPTED_EVIDENCE_STATES = {"passed", "accepted", "verified"}
MINIMUM_EVIDENCE_KINDS = frozenset(
    {
        "unit_test",
        "api_integration",
        "e2e",
        "review",
        "completion_audit",
        "artifact",
        "package",
        "sbom",
        "provenance",
        "signature",
    }
)
FORBIDDEN_PERMISSION_TOKENS = {"*", "admin", "administrator", "root", "owner", "dba", "superuser"}

DANGEROUS_PATTERNS = (
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bDROP\s+(?:DATABASE|SCHEMA|TABLE|VIEW|COLLECTION|PARTITION)\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bTRUNCATE\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bDELETE\s+FROM\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bALTER\b[\s\S]{0,160}\bDROP\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bCASCADE\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bflyway\b[\s\S]{0,80}\bclean\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bprisma\b[\s\S]{0,80}\b(?:reset|db\s+push\s+--force-reset)\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\b(?:create-drop|auto[_-]?drop|schema[_-]?reset)\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bREPLACE\s+INTO\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bALTER\b[\s\S]{0,160}\bTTL\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bretention\b[\s\S]{0,120}\b(?:delete|expire|purge)\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bkubectl\s+delete\s+(?:pvc|persistentvolume)\b", re.I)),
    ("E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION", re.compile(r"\bUPDATE\b(?![\s\S]{0,300}\bWHERE\b)", re.I)),
    ("E_V245_RE_DANGEROUS_SCRIPT_OPERATION", re.compile(r"\brm\s+-[^\n]*r[^\n]*f\b", re.I)),
    ("E_V245_RE_DANGEROUS_SCRIPT_OPERATION", re.compile(r"\bcurl\b[^\n|]*\|\s*(?:ba)?sh\b", re.I)),
    ("E_V245_RE_DANGEROUS_SCRIPT_OPERATION", re.compile(r"\beval\s+", re.I)),
)

FULL_TEST_PATTERNS = (
    re.compile(r"\bpytest\b", re.I),
    re.compile(r"\bcargo\s+test\b", re.I),
    re.compile(r"\bgo\s+test\b", re.I),
    re.compile(r"\bnpm\s+test\b", re.I),
    re.compile(r"\bpnpm\s+test\b", re.I),
    re.compile(r"\byarn\s+test\b", re.I),
    re.compile(r"\b(?:mvn|mvnw)\b[^\n]*\btest\b", re.I),
    re.compile(r"\bgradle\w*\b[^\n]*\btest\b", re.I),
)

INDIRECT_OR_DATABASE_COMMANDS = (
    re.compile(r"(?i)(?<![A-Za-z0-9_-])(?:psql|mysql|mariadb|sqlite3|mongosh|redis-cli|sqlcmd)(?![A-Za-z0-9_-])"),
    re.compile(r"(?i)(?<![A-Za-z0-9_-])(?:bash|sh|zsh|python(?:3)?|node|ruby|perl|pwsh|powershell)(?![A-Za-z0-9_-])"),
    re.compile(r"(?im)^[ \t]*(?:source|\.)\s+[^\n]+"),
    re.compile(r"(?im)^[ \t]*exec\s+[^\n]+"),
    re.compile(r"(?im)^[ \t]*[A-Za-z0-9_./-]+\s+.*(?:--file|-f)\s+[^\n]+\.(?:sql|js)\b"),
)

UNVERIFIABLE_BASH_CLOSURE_PATTERNS = (
    # Adapters use a small static Bash dialect. Assignments can assemble a
    # forbidden command or SQL token after source scanning, so they fail
    # closed even when the assigned fragments look harmless in isolation.
    re.compile(
        r"(?im)^[ \t]*(?:"
        r"(?:export|readonly|declare|typeset|local)[ \t]+"
        r"|[A-Za-z_][A-Za-z0-9_]*[+?:-]?="
        r")"
    ),
    # These wrappers alter command position or add another interpretation
    # surface that the scanner cannot close.
    re.compile(r"(?im)(?:^|[;&|])[ \t]*(?:command|env|builtin|nohup|xargs)\b"),
    # Control flow, functions, aliases and dynamic input make the reachable
    # command set depend on runtime state.
    re.compile(
        r"(?im)^[ \t]*(?:"
        r"if|then|elif|else|fi|while|until|for|select|case|esac|do|done|"
        r"function|alias|unalias|read|mapfile"
        r")\b"
    ),
    re.compile(r"(?im)^[ \t]*[A-Za-z_][A-Za-z0-9_]*[ \t]*\(\)[ \t]*\{"),
    # Reject command/process/arithmetic substitution, indirect expansion,
    # ANSI-C quoting, line-spliced tokens and adjacent quote concatenation.
    re.compile(r"\$\(|`|<\(|>\(|\$\(\(|\$\{!|\$'"),
    re.compile(r"\\\r?\n"),
    re.compile(r"(?:'[^'\r\n]*'|\"[^\"\r\n]*\")[ \t]*(?:'|\")"),
    # Environment variables remain allowed in arguments, but a variable in
    # command position is not a statically identified host adapter.
    re.compile(r"(?im)^[ \t]*(?:\"\$[A-Za-z_{]|\$[A-Za-z_{])"),
)

STATIC_ADAPTER_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:=,@%+-]+")
ALLOWED_ADAPTER_ENV_TOKEN_RE = re.compile(
    r"\$GOAL_TEAMS_RELEASE_(?:"
    r"EXECUTION_ID|MODE|OPERATION|TARGET_ENVIRONMENT|SURFACE"
    r")"
)
SAFE_ADAPTER_BUILTINS = frozenset({"exit", "true", "false"})
APPROVED_HOST_COMMAND_BASENAME = "goal-teams-release-host-v245"
APPROVED_TOOLCHAIN_HOST_COMMAND_BASENAME = (
    "goal-teams-release-toolchain-host-v245"
)
TRUSTED_TOOLCHAIN_PROVENANCE_SIGNERS = frozenset(
    {"goal-teams-trusted-toolchain-authority"}
)
TRUSTED_TOOLCHAIN_SOURCE_PREFIXES = (
    "signed-release:",
    "system-package:",
    "hermetic-image:",
)
EXECUTION_INTERPRETER_PATH = Path("/bin/bash")
MERGED_USR_BIN_PATH = Path("/usr/bin")
MERGED_USR_BIN_TARGETS = frozenset({"usr/bin", "/usr/bin"})
TOOLCHAIN_KIT_MATRIX = {
    "java-maven-v1": ("java", "maven"),
    "java-gradle-v1": ("java", "gradle"),
    "rust-cargo-v1": ("rust", "cargo"),
    "go-modules-v1": ("go", "go-modules"),
    "python-pip-v1": ("python", "pip"),
    "python-uv-v1": ("python", "uv"),
    "python-poetry-v1": ("python", "poetry"),
    "node-npm-v1": ("node", "npm"),
    "node-pnpm-v1": ("node", "pnpm"),
    "node-yarn-v1": ("node", "yarn"),
}
TOOLCHAIN_PREFETCH_INPUTS = [
    "approved_plan_path",
    "approved_plan_digest",
    "working_directory",
    "dependency_bundle",
    "dependency_requirements",
]
TOOLCHAIN_BUILD_INPUTS = [
    *TOOLCHAIN_PREFETCH_INPUTS,
    "artifact_path",
    "prefetch_receipt",
]
TOOLCHAIN_PREFETCH_RECEIPT_FIELDS = [
    "action_id",
    "action_manifest_sha256",
    "dependency_bundle_digest",
    "execution_id",
    "full_test_execution_count",
    "host_attestation",
    "host_executable_sha256",
    "network_policy",
    "observed_at",
    "plan_digest",
    "schema_version",
    "status",
]
TOOLCHAIN_BUILD_RECEIPT_FIELDS = [
    "action_id",
    "action_manifest_sha256",
    "artifact_digest",
    "dependency_bundle_digest",
    "execution_id",
    "full_test_execution_count",
    "host_attestation",
    "host_executable_sha256",
    "network_policy",
    "observed_at",
    "plan_digest",
    "schema_version",
    "status",
]
TOOLCHAIN_EXECUTION_CONTRACT = {
    "approved_plan_path": "GOAL_TEAMS_RELEASE_PLAN_PATH",
    "approved_plan_digest": "GOAL_TEAMS_RELEASE_PLAN_DIGEST",
    "working_directory": "GOAL_TEAMS_RELEASE_PROJECT_ROOT",
    "dependency_bundle": "GOAL_TEAMS_RELEASE_DEPENDENCY_BUNDLE",
    "dependency_requirements": "GOAL_TEAMS_RELEASE_DEPENDENCY_REQUIREMENTS",
    "artifact_path": "GOAL_TEAMS_RELEASE_ARTIFACT_PATH",
    "prefetch_receipt": "GOAL_TEAMS_RELEASE_PREFETCH_RECEIPT",
    "action_receipt": "GOAL_TEAMS_RELEASE_TOOLCHAIN_RECEIPT",
    "receipt_schema": "goal-teams-toolchain-action-receipt-v2.45",
    "network_policy": {"prefetch": "prefetch_only", "build": "offline_required"},
    "full_test_execution_count": 0,
}


def _load_shared_security() -> Any:
    root = SCRIPT.parents[4]
    path = root / "scripts" / "v23" / "v236_security.py"
    spec = importlib.util.spec_from_file_location(
        "goal_teams_release_engineer_v236_security", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("shared security module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SHARED_SECURITY = _load_shared_security()
TRUSTED_APPROVAL_PUBLIC_KEY_HEX = (
    "f719e979bb59b9bdc3c026e737ef78a08bdb9fd5fe763f2e7e64e260f68e3e4b"
)
TRUSTED_APPROVAL_KEY_ID = hashlib.sha256(
    bytes.fromhex(TRUSTED_APPROVAL_PUBLIC_KEY_HEX)
).hexdigest()


def _load_ed25519_verifier() -> Any:
    root = SCRIPT.parents[4]
    path = root / "scripts" / "release" / "ed25519_verify.py"
    spec = importlib.util.spec_from_file_location(
        "goal_teams_release_engineer_ed25519_verify", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Ed25519 verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ED25519_VERIFY = _load_ed25519_verifier()


class ReleaseError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        secondary_findings: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.secondary_findings = secondary_findings or []

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "goal-teams-release-engineer-error-v2.45",
            "passed": False,
            "error_code": self.code,
            "message": self.message,
            "secondary_findings": sorted(
                self.secondary_findings,
                key=lambda item: (str(item.get("path", "")), str(item.get("error_code", ""))),
            ),
        }
        if self.path is not None:
            result["path"] = self.path
        return result


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def object_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError("E_V245_RE_INPUT_MISSING", "required JSON input is missing", path=str(path)) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "input is not valid UTF-8 JSON", path=str(path)) from exc
    if not isinstance(value, dict):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "input root must be an object", path=str(path))
    return value


def atomic_write(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: Any, *, mode: int = 0o644) -> None:
    atomic_write(path, canonical_bytes(value) + b"\n", mode=mode)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"{field} must be a non-empty ISO-8601 time")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"{field} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def require_fields(value: dict[str, Any], fields: tuple[str, ...], code: str = "E_V245_RE_INPUT_INVALID") -> None:
    missing = [field for field in fields if field not in value or value[field] in (None, "")]
    if missing:
        raise ReleaseError(code, f"missing required fields: {', '.join(missing)}")


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"{field} must be a lowercase SHA-256")
    return value


def require_safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"{field} is not a safe identifier")
    return value


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_no_symlink_chain(path: Path, stop: Path) -> None:
    current = path
    while True:
        if current.exists() and stat.S_ISLNK(current.lstat().st_mode):
            raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "path must not contain symlinks", path=str(current))
        if current == stop:
            return
        if current.parent == current:
            raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "path is not contained by project root", path=str(path))
        current = current.parent


def validate_root_owned_parent_chain(path: Path, code: str) -> None:
    current = path.parent
    while True:
        try:
            observed = current.lstat()
        except OSError as exc:
            raise ReleaseError(
                code,
                "trusted executable parent directory is unavailable",
                path=str(current),
            ) from exc
        if (
            not stat.S_ISDIR(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or observed.st_uid != 0
            or observed.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise ReleaseError(
                code,
                "every trusted executable parent must be a root-owned non-symlink directory that is not group/world writable",
                path=str(current),
            )
        if current.parent == current:
            return
        current = current.parent


def resolve_project_and_release_root(project_raw: Any, release_raw: Any) -> tuple[Path, Path]:
    if not isinstance(project_raw, str) or not Path(project_raw).is_absolute():
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "project_root must be an absolute path")
    if not isinstance(release_raw, str) or not Path(release_raw).is_absolute():
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "release_root must be an absolute path")
    project_input = Path(project_raw)
    release_input = Path(release_raw)
    if ".." in project_input.parts or ".." in release_input.parts:
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "project_root and release_root must not contain parent traversal")
    if not project_input.exists() or not project_input.is_dir() or project_input.is_symlink():
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "project_root must be an existing non-symlink directory")
    project = project_input.resolve(strict=True)
    if project_input != project:
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "project_root must use its canonical non-symlink path")
    if not is_within(release_input, project):
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "release_root must be a lexical child of project_root", path=str(release_input))
    ensure_no_symlink_chain(release_input, project)
    release = release_input.resolve(strict=False)
    if release == project or not is_within(release, project):
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "release_root must be a child of project_root", path=str(release))
    if "release" not in {part.lower() for part in release.relative_to(project).parts}:
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "release_root path must include a release directory", path=str(release))
    forbidden = {Path("/").resolve(), Path.home().resolve(), project.parent.resolve()}
    if release in forbidden:
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "release_root resolves to a forbidden broad path", path=str(release))
    ensure_no_symlink_chain(release, project)
    return project, release


def resolve_project_file(raw: Any, project: Path, field: str, *, executable: bool = False) -> Path:
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"{field} must be an absolute path")
    path = Path(raw)
    if ".." in path.parts or not is_within(path, project):
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", f"{field} must be a canonical child of project_root", path=str(path))
    ensure_no_symlink_chain(path, project)
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise ReleaseError("E_V245_RE_INPUT_MISSING", f"{field} must be an existing non-symlink file", path=str(path))
    resolved = path.resolve(strict=True)
    if not is_within(resolved, project):
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", f"{field} must be inside project_root", path=str(path))
    ensure_no_symlink_chain(resolved, project)
    if executable and not os.access(resolved, os.X_OK):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"{field} must be executable", path=str(path))
    return resolved


def redact(text: str) -> str:
    return SHARED_SECURITY.redact_text(
        text,
        hmac_key=None,
        redact_home_paths=True,
    )[:4000]


def scan_dangerous_text(text: str, *, path: str) -> None:
    findings: list[dict[str, Any]] = []
    for code, pattern in DANGEROUS_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            findings.append({"error_code": code, "path": path, "match": match.group(0)[:80]})
    if findings:
        primary = findings[0]
        raise ReleaseError(
            str(primary["error_code"]),
            "dangerous database or script operation is forbidden",
            path=path,
            secondary_findings=findings[1:],
        )


def scan_full_test_commands(text: str, *, path: str) -> None:
    for pattern in FULL_TEST_PATTERNS:
        if pattern.search(text):
            raise ReleaseError(
                "E_V245_RE_FULL_TEST_EXECUTION_FORBIDDEN",
                "Release Engineer scripts must not run full test suites",
                path=path,
            )


def scan_adapter_indirection(
    text: str,
    *,
    path: str,
    allowed_host_commands: dict[str, str] | None = None,
) -> None:
    host_commands = allowed_host_commands or {}
    lines = text.splitlines(keepends=True)
    scan_text = "".join(lines[1:]) if lines and lines[0].startswith("#!") else text
    for line in scan_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "set -euo pipefail":
            continue
        tokens = stripped.split()
        if not tokens or any(
            STATIC_ADAPTER_TOKEN_RE.fullmatch(token) is None
            and ALLOWED_ADAPTER_ENV_TOKEN_RE.fullmatch(token) is None
            for token in tokens
        ):
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "project adapter lines must contain only static allowlisted tokens or whole approved GOAL_TEAMS_RELEASE_* arguments",
                path=path,
            )
        if STATIC_ADAPTER_TOKEN_RE.fullmatch(tokens[0]) is None:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "project adapter command position must be a static executable token",
                path=path,
            )
        if tokens[0] in SAFE_ADAPTER_BUILTINS:
            if tokens not in (["true"], ["false"], ["exit", "0"], ["exit", "1"]):
                raise ReleaseError(
                    "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                    "safe shell builtin arguments are outside the closed adapter schema",
                    path=path,
                )
        elif tokens[0] in host_commands:
            if tokens != [tokens[0], host_commands[tokens[0]]]:
                raise ReleaseError(
                    "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                    "host-mediated command arguments must be the single catalog action_id",
                    path=path,
                )
        else:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "project adapters may invoke only safe shell builtins or the catalog-defined release host command",
                path=path,
            )
    for pattern in (*INDIRECT_OR_DATABASE_COMMANDS, *UNVERIFIABLE_BASH_CLOSURE_PATTERNS):
        match = pattern.search(scan_text)
        if match is not None:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "project adapters must use the static Bash subset and may not invoke database clients, interpreters, dynamic commands, or indirect scripts; use a reviewed host-mediated adapter",
                path=path,
                secondary_findings=[
                    {
                        "error_code": "E_V245_RE_DATABASE_DESTRUCTIVE_OPERATION",
                        "path": path,
                        "match": match.group(0)[:80],
                    }
                ],
            )


def scan_permissions(capabilities: Any) -> list[str]:
    if not isinstance(capabilities, list) or any(not isinstance(item, str) or not item for item in capabilities):
        raise ReleaseError("E_V245_RE_PERMISSION_EXCESS", "requested_capabilities must be a list of strings")
    normalized = [item.strip().lower() for item in capabilities]
    for value in normalized:
        tokens = set(re.split(r"[^a-z0-9*]+", value))
        if FORBIDDEN_PERMISSION_TOKENS & tokens:
            raise ReleaseError("E_V245_RE_PERMISSION_EXCESS", "wildcard or administrative permission is forbidden")
    return sorted(set(str(item) for item in capabilities))


def load_catalog() -> dict[str, Any]:
    catalog = load_json(CATALOG_PATH)
    if catalog.get("schema_version") != "goal-teams-release-kit-catalog-v2.45":
        raise ReleaseError("E_V245_RE_KIT_CATALOG_INVALID", "unsupported release kit catalog schema")
    return catalog


def catalog_path(relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ReleaseError("E_V245_RE_KIT_PATH_UNSAFE", "kit path must be a safe relative path")
    unresolved = KITS_ROOT / relative
    ensure_no_symlink_chain(unresolved, KITS_ROOT)
    path = unresolved.resolve(strict=True)
    if not is_within(path, KITS_ROOT.resolve(strict=True)) or path.is_symlink() or not path.is_file():
        raise ReleaseError("E_V245_RE_KIT_PATH_UNSAFE", "kit path escapes package", path=relative)
    return path


def select_catalog_entry(entries: Any, key: str, value: str, code: str) -> dict[str, Any]:
    if not isinstance(entries, list):
        raise ReleaseError("E_V245_RE_KIT_CATALOG_INVALID", f"catalog {key} collection must be a list")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get(key) == value]
    if len(matches) != 1:
        raise ReleaseError(code, f"expected one approved kit for {key}={value}")
    entry = matches[0]
    if entry.get("lifecycle", "approved") != "approved":
        raise ReleaseError("E_V245_RE_KIT_NOT_APPROVED", f"kit for {key}={value} is not approved")
    return entry


def validate_evidence_host_attestation(payload: dict[str, Any]) -> None:
    attestation = payload.get("host_attestation")
    required = {
        "schema_version",
        "algorithm",
        "issuer",
        "key_id",
        "evidence_kind",
        "bindings_sha256",
        "issued_at",
        "challenge_id",
        "signature",
    }
    bindings = {
        field: payload.get(field)
        for field in (
            "schema_version",
            "kind",
            "status",
            "candidate_binding",
            "observed_at",
            "issuer",
            "assertions",
        )
    }
    if (
        not isinstance(attestation, dict)
        or set(attestation) != required
        or attestation.get("schema_version")
        != "goal-teams-release-evidence-host-attestation-v2.45"
        or attestation.get("algorithm") != "Ed25519"
        or attestation.get("issuer") != "goal-teams-trusted-host"
        or attestation.get("key_id") != TRUSTED_APPROVAL_KEY_ID
        or attestation.get("evidence_kind") != payload.get("kind")
        or attestation.get("bindings_sha256") != object_digest(bindings)
        or not isinstance(attestation.get("challenge_id"), str)
        or not attestation["challenge_id"]
    ):
        raise ReleaseError(
            "E_V245_RE_EVIDENCE_ATTESTATION_REQUIRED",
            "release evidence requires an exact trusted-host attestation",
        )
    issued_at = parse_time(attestation.get("issued_at"), "host_attestation.issued_at")
    observed_at = parse_time(payload.get("observed_at"), "evidence.observed_at")
    now = dt.datetime.now(dt.timezone.utc)
    if issued_at < observed_at - dt.timedelta(minutes=5) or issued_at > now + dt.timedelta(minutes=5):
        raise ReleaseError(
            "E_V245_RE_EVIDENCE_ATTESTATION_REQUIRED",
            "release evidence attestation is outside its observation window",
        )
    unsigned = dict(attestation)
    signature_hex = unsigned.pop("signature", None)
    domain = b"goal-teams/release-engineer/v2.45/evidence-attestation/ed25519/v1"
    try:
        valid = ED25519_VERIFY.verify(
            bytes.fromhex(TRUSTED_APPROVAL_PUBLIC_KEY_HEX),
            domain + b"\x00" + canonical_bytes(unsigned),
            bytes.fromhex(str(signature_hex)),
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ReleaseError(
            "E_V245_RE_EVIDENCE_ATTESTATION_REQUIRED",
            "release evidence trusted-host signature is invalid",
        )


def check_evidence(request: dict[str, Any]) -> dict[str, Any]:
    require_fields(request, ("project_root", "candidate", "environment_documents", "required_evidence_kinds", "evidence"))
    project_raw = request["project_root"]
    if not isinstance(project_raw, str) or not Path(project_raw).is_absolute():
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "project_root must be absolute")
    project = Path(project_raw).resolve(strict=True)
    if not project.is_dir() or project.is_symlink():
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "project_root must be a non-symlink directory")

    candidate = request["candidate"]
    environment = request["environment_documents"]
    if not isinstance(candidate, dict) or not isinstance(environment, dict):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "candidate and environment_documents must be objects")
    require_fields(candidate, ("release_identity", "source_commit", "source_tree_digest", "artifact_digest"))
    require_fields(
        environment,
        ("set_digest", "documents", "target_name", "target_document_path", "target_document_digest"),
    )
    require_sha256(candidate["source_tree_digest"], "candidate.source_tree_digest")
    require_sha256(candidate["artifact_digest"], "candidate.artifact_digest")
    if not isinstance(candidate["source_commit"], str) or COMMIT_SHA.fullmatch(candidate["source_commit"]) is None:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "candidate.source_commit must be a 40-character lowercase commit SHA")
    require_sha256(environment["set_digest"], "environment_documents.set_digest")
    require_sha256(environment["target_document_digest"], "environment_documents.target_document_digest")
    documents = environment["documents"]
    required_environments = {"local", "development", "test", "staging", "production"}
    if not isinstance(documents, dict) or set(documents) != required_environments:
        raise ReleaseError(
            "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
            "architecture-stage environment document set must contain local, development, test, staging, and production",
        )
    observed_document_set: dict[str, dict[str, Any]] = {}
    findings: list[dict[str, Any]] = []
    for name in sorted(required_environments):
        spec = documents[name]
        if not isinstance(spec, dict):
            raise ReleaseError("E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED", f"environment document spec is invalid: {name}")
        require_fields(
            spec,
            (
                "schema_version",
                "path",
                "sha256",
                "created_at",
                "architecture_baseline_commit",
                "issuer",
            ),
            "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
        )
        if spec["schema_version"] != "goal-teams-environment-document-v2.45":
            raise ReleaseError(
                "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
                f"environment document schema is invalid: {name}",
            )
        created_at = parse_time(
            spec["created_at"],
            f"environment_documents.documents.{name}.created_at",
        )
        if created_at > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
            raise ReleaseError(
                "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
                f"environment document creation time is invalid: {name}",
            )
        baseline_commit = spec["architecture_baseline_commit"]
        if not isinstance(baseline_commit, str) or COMMIT_SHA.fullmatch(baseline_commit) is None:
            raise ReleaseError(
                "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
                f"environment document architecture baseline is invalid: {name}",
            )
        issuer = spec["issuer"]
        if (
            not isinstance(issuer, dict)
            or not isinstance(issuer.get("role"), str)
            or not issuer["role"]
            or not isinstance(issuer.get("run_id"), str)
            or not issuer["run_id"]
        ):
            raise ReleaseError(
                "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
                f"environment document issuer is invalid: {name}",
            )
        path = resolve_project_file(spec["path"], project, f"environment_documents.documents.{name}.path")
        expected = require_sha256(spec["sha256"], f"environment_documents.documents.{name}.sha256")
        observed_document_set[name] = {
            "schema_version": spec["schema_version"],
            "path": str(path),
            "sha256": expected,
            "created_at": spec["created_at"],
            "architecture_baseline_commit": baseline_commit,
            "issuer": issuer,
        }
        if file_digest(path) != expected:
            findings.append({"kind": f"environment_document:{name}", "state": "digest_mismatch", "path": str(path)})
    if object_digest(observed_document_set) != environment["set_digest"]:
        findings.append({"kind": "environment_document_set", "state": "digest_mismatch"})
    target_name = environment["target_name"]
    if target_name not in required_environments:
        raise ReleaseError("E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED", "target environment document is not in the required set")
    document_path = resolve_project_file(environment["target_document_path"], project, "target_document_path")
    if file_digest(document_path) != environment["target_document_digest"]:
        findings.append({"kind": "environment_document", "state": "digest_mismatch", "path": str(document_path)})
    target_spec = observed_document_set[target_name]
    if (
        target_spec["path"] != str(document_path)
        or target_spec["sha256"] != environment["target_document_digest"]
    ):
        findings.append({"kind": "environment_document", "state": "target_binding_mismatch", "path": str(document_path)})

    required_kinds = request["required_evidence_kinds"]
    evidence = request["evidence"]
    if not isinstance(required_kinds, list) or not required_kinds or any(not isinstance(item, str) for item in required_kinds):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "required_evidence_kinds must be a non-empty string list")
    requested_kinds = set(required_kinds)
    if not MINIMUM_EVIDENCE_KINDS.issubset(requested_kinds):
        missing_minimum = sorted(MINIMUM_EVIDENCE_KINDS - requested_kinds)
        raise ReleaseError(
            "E_V245_RE_EVIDENCE_DENOMINATOR_REDUCED",
            "required_evidence_kinds may extend but must not reduce the fixed release evidence denominator: "
            + ", ".join(missing_minimum),
        )
    if not isinstance(evidence, list):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "evidence must be a list")
    by_kind: dict[str, list[dict[str, Any]]] = {}
    checked: list[dict[str, Any]] = []
    issuer_runs: dict[str, list[str]] = {}
    allowed_bindings = {
        candidate["source_commit"],
        candidate["source_tree_digest"],
        candidate["artifact_digest"],
    }
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            findings.append({"kind": f"evidence[{index}]", "state": "invalid"})
            continue
        kind = item.get("kind")
        if isinstance(kind, str):
            by_kind.setdefault(kind, []).append(item)
        try:
            require_fields(
                item,
                (
                    "kind",
                    "status",
                    "path",
                    "sha256",
                    "candidate_binding",
                    "observed_at",
                    "issuer",
                ),
            )
            path = resolve_project_file(item["path"], project, f"evidence[{index}].path")
            expected_digest = require_sha256(item["sha256"], f"evidence[{index}].sha256")
            state = "valid"
            observed_at = parse_time(item["observed_at"], "observed_at")
            now = dt.datetime.now(dt.timezone.utc)
            issuer = item["issuer"]
            try:
                evidence_payload = load_json(path)
            except ReleaseError:
                evidence_payload = {}
            if file_digest(path) != expected_digest:
                state = "digest_mismatch"
            elif item["status"] not in ACCEPTED_EVIDENCE_STATES:
                state = f"status_{item['status']}"
            elif item["candidate_binding"] not in allowed_bindings:
                state = "candidate_binding_mismatch"
            elif observed_at > now + dt.timedelta(minutes=5):
                state = "observed_at_in_future"
            elif now - observed_at > dt.timedelta(hours=24):
                state = "stale"
            elif (
                not isinstance(issuer, dict)
                or not isinstance(issuer.get("role"), str)
                or not issuer.get("role")
                or not isinstance(issuer.get("run_id"), str)
                or not issuer.get("run_id")
            ):
                state = "issuer_invalid"
            elif (
                evidence_payload.get("schema_version")
                != "goal-teams-release-evidence-item-v2.45"
                or evidence_payload.get("kind") != item["kind"]
                or evidence_payload.get("status") != item["status"]
                or evidence_payload.get("candidate_binding")
                != item["candidate_binding"]
                or evidence_payload.get("observed_at") != item["observed_at"]
                or evidence_payload.get("issuer") != issuer
                or not isinstance(evidence_payload.get("assertions"), list)
                or not evidence_payload["assertions"]
                or any(
                    not isinstance(assertion, dict)
                    or assertion.get("passed") is not True
                    or not isinstance(assertion.get("name"), str)
                    or not assertion["name"]
                    for assertion in evidence_payload["assertions"]
                )
            ):
                state = "typed_evidence_invalid"
            elif item.get("expires_at") is not None and parse_time(item["expires_at"], "expires_at") <= dt.datetime.now(dt.timezone.utc):
                state = "expired"
            else:
                try:
                    validate_evidence_host_attestation(evidence_payload)
                except ReleaseError:
                    state = "trusted_host_attestation_invalid"
            if state == "valid":
                issuer_runs.setdefault(str(issuer["run_id"]), []).append(str(item["kind"]))
            checked.append(
                {
                    "kind": item["kind"],
                    "path": str(path),
                    "sha256": expected_digest,
                    "state": state,
                    "observed_at": item["observed_at"],
                    "issuer": issuer,
                }
            )
            if state != "valid":
                findings.append({"kind": item["kind"], "state": state, "path": str(path)})
        except ReleaseError as exc:
            findings.append({"kind": str(kind or f"evidence[{index}]"), "state": exc.code, "path": exc.path})

    for run_id, kinds in sorted(issuer_runs.items()):
        if len(kinds) > 1:
            findings.append(
                {
                    "kind": "evidence_independence",
                    "state": "issuer_run_reused",
                    "run_id": run_id,
                    "evidence_kinds": sorted(kinds),
                }
            )

    for kind in sorted(requested_kinds):
        if kind not in by_kind:
            findings.append({"kind": kind, "state": "missing"})

    report = {
        "schema_version": "goal-teams-final-release-evidence-report-v2.45",
        "candidate": candidate,
        "environment_documents": {
            **environment,
            "documents": observed_document_set,
        },
        "checked_at": now_utc(),
        "checked_existing_evidence": sorted(checked, key=lambda item: (item["kind"], item["path"])),
        "full_test_execution_count": 0,
        "evidence_status": "ready" if not findings else "not_ready",
        "findings": sorted(findings, key=lambda item: (str(item.get("kind", "")), str(item.get("path", "")), str(item.get("state", "")))),
        "release_intent_source": request.get("release_intent_source", "none"),
        "next_gate": "plan" if not findings else "original_owner_evidence_required",
    }
    report["report_digest"] = object_digest(report)
    return report


def validate_host_commands(
    value: Any,
    project: Path,
    adapter_name: str,
) -> list[dict[str, Any]]:
    host_policy = load_json(CATALOG_PATH).get("host_command")
    if (
        not isinstance(host_policy, dict)
        or host_policy.get("identity") != "goal-teams-release-host-v245"
        or host_policy.get("invocation_schema") != "absolute_path action_id"
        or sorted(host_policy.get("action_ids", []))
        != ["backup", "benchmark", "deploy", "rollback", "verify"]
        or adapter_name not in host_policy["action_ids"]
    ):
        raise ReleaseError(
            "E_V245_RE_KIT_CATALOG_INVALID",
            "catalog host command policy is missing or drifted",
        )
    if value is None:
        return []
    if not isinstance(value, list):
        raise ReleaseError(
            "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
            f"adapter {adapter_name} host_commands must be a list",
        )
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                f"adapter {adapter_name} host command {index} must be an object",
            )
        if set(item) != {"path", "sha256", "capability", "action_id"}:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "host-mediated command fields are closed",
            )
        require_fields(item, ("path", "sha256", "capability", "action_id"))
        raw_path = item["path"]
        if not isinstance(raw_path, str) or not raw_path or not Path(raw_path).is_absolute():
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "host-mediated command path must be absolute",
            )
        lexical = Path(raw_path)
        if ".." in lexical.parts:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "host-mediated command path must not contain traversal",
                path=raw_path,
            )
        current = Path(lexical.anchor)
        for part in lexical.parts[1:]:
            current = current / part
            if current.is_symlink():
                raise ReleaseError(
                    "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                    "host-mediated command path must not contain symlinks",
                    path=raw_path,
                )
        try:
            resolved = lexical.resolve(strict=True)
        except OSError as exc:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "host-mediated command must exist",
                path=raw_path,
            ) from exc
        if (
            resolved != lexical
            or not resolved.is_file()
            or not os.access(resolved, os.X_OK)
            or is_within(resolved, project)
            or resolved.name != APPROVED_HOST_COMMAND_BASENAME
        ):
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "host-mediated command must be the catalog-defined canonical release host executable outside project_root",
                path=raw_path,
            )
        validate_root_owned_parent_chain(
            resolved,
            "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
        )
        observed_stat = resolved.stat()
        mode = observed_stat.st_mode
        if observed_stat.st_uid != 0 or mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "host-mediated command must be root-owned and not group/world writable",
                path=raw_path,
            )
        digest_value = require_sha256(
            item["sha256"],
            f"adapters.{adapter_name}.host_commands[{index}].sha256",
        )
        if file_digest(resolved) != digest_value:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_DIGEST_DRIFT",
                "host-mediated command digest drift",
                path=raw_path,
            )
        if item["capability"] != adapter_name:
            raise ReleaseError(
                "E_V245_RE_PERMISSION_EXCESS",
                "host-mediated command capability differs from adapter role",
                path=raw_path,
            )
        if item["action_id"] != adapter_name:
            raise ReleaseError(
                "E_V245_RE_PERMISSION_EXCESS",
                "host-mediated command action_id differs from adapter role",
                path=raw_path,
            )
        command = str(resolved)
        if command in seen:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
                "duplicate host-mediated command",
                path=raw_path,
            )
        seen.add(command)
        validated.append(
            {
                "path": command,
                "sha256": digest_value,
                "capability": adapter_name,
                "action_id": adapter_name,
            }
        )
    return sorted(validated, key=lambda item: item["path"])


def validate_execution_interpreter_layout(path: Path, resolved: Path) -> str:
    if path != EXECUTION_INTERPRETER_PATH:
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "execution interpreter invocation path must be fixed to /bin/bash",
            path=str(path),
        )
    if resolved == path and not path.is_symlink():
        return "canonical"
    if path.is_symlink():
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "the /bin/bash executable itself must not be a symlink",
            path=str(path),
        )
    bin_path = path.parent
    try:
        bin_stat = bin_path.lstat()
        bin_target = os.readlink(bin_path)
    except OSError as exc:
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "non-canonical /bin/bash is not a trusted merged-/usr layout",
            path=str(path),
        ) from exc
    if (
        not stat.S_ISLNK(bin_stat.st_mode)
        or bin_stat.st_uid != 0
        or bin_target not in MERGED_USR_BIN_TARGETS
        or resolved != MERGED_USR_BIN_PATH / "bash"
    ):
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "only the root-owned /bin to /usr/bin merged-/usr alias is permitted",
            path=str(path),
        )
    return "merged_usr"


def validate_execution_interpreter(
    frozen: Any | None = None,
) -> dict[str, Any]:
    path = EXECUTION_INTERPRETER_PATH
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "fixed /bin/bash interpreter is unavailable",
        ) from exc
    layout = validate_execution_interpreter_layout(path, resolved)
    if (
        path.resolve(strict=True) != resolved
        or not resolved.is_file()
        or resolved.is_symlink()
    ):
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "resolved execution interpreter must be a stable regular file",
            path=str(path),
        )
    validate_root_owned_parent_chain(
        resolved,
        "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
    )
    observed_stat = resolved.lstat()
    if (
        not stat.S_ISREG(observed_stat.st_mode)
        or observed_stat.st_uid != 0
        or observed_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(resolved, os.X_OK)
    ):
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "execution interpreter must be root-owned, executable, and not group/world writable",
            path=str(path),
        )
    binding = {
        "path": str(path),
        "resolved_path": str(resolved),
        "layout": layout,
        "sha256": file_digest(resolved),
        "owner_uid": observed_stat.st_uid,
        "mode": stat.S_IMODE(observed_stat.st_mode),
    }
    if frozen is not None and frozen != binding:
        raise ReleaseError(
            "E_V245_RE_EXECUTION_INTERPRETER_UNTRUSTED",
            "execution interpreter identity drifted after plan approval",
            path=str(path),
        )
    return binding


def validate_toolchain_host_command(
    value: Any,
    project: Path,
    language_kit: dict[str, Any],
) -> dict[str, Any]:
    catalog = load_json(CATALOG_PATH)
    policy = catalog.get("toolchain_host_command")
    expected_prefetch = f"prefetch-{language_kit.get('id', '')}"
    expected_build = f"build-{language_kit.get('id', '')}"
    if (
        not isinstance(policy, dict)
        or set(policy)
        != {
            "identity",
            "invocation_schema",
            "provenance_schema",
            "action_manifest",
            "action_ids",
        }
        or policy.get("identity")
        != "goal-teams-release-toolchain-host-v245"
        or policy.get("invocation_schema") != "absolute_path action_id"
        or policy.get("provenance_schema")
        != "goal-teams-toolchain-provenance-v2.45"
        or language_kit.get("prefetch_action") != expected_prefetch
        or language_kit.get("build_action") != expected_build
        or expected_prefetch not in policy.get("action_ids", [])
        or expected_build not in policy.get("action_ids", [])
    ):
        raise ReleaseError(
            "E_V245_RE_KIT_CATALOG_INVALID",
            "catalog toolchain host command policy is missing or drifted",
        )
    action_manifest_path = catalog_path(policy.get("action_manifest"))
    action_manifest = load_json(action_manifest_path)
    manifest_actions = action_manifest.get("actions")
    expected_action_ids = {
        f"{phase}-{kit_id}"
        for kit_id in TOOLCHAIN_KIT_MATRIX
        for phase in ("prefetch", "build")
    }
    if (
        action_manifest.get("schema_version")
        != "goal-teams-toolchain-action-manifest-v2.45"
        or action_manifest.get("manifest_version") != "1.0.0"
        or action_manifest.get("execution_contract")
        != TOOLCHAIN_EXECUTION_CONTRACT
        or not isinstance(manifest_actions, list)
        or len(manifest_actions) != len(expected_action_ids)
        or {
            item.get("id")
            for item in manifest_actions
            if isinstance(item, dict)
        }
        != expected_action_ids
        or expected_action_ids != set(policy["action_ids"])
    ):
        raise ReleaseError(
            "E_V245_RE_KIT_CATALOG_INVALID",
            "toolchain action manifest is missing or drifted",
        )
    for action in manifest_actions:
        if (
            not isinstance(action, dict)
            or set(action)
            != {
                "id",
                "language",
                "build_tool",
                "phase",
                "strategy",
                "required_inputs",
                "network_policy",
                "full_test_execution_count",
                "required_receipt_fields",
            }
        ):
            raise ReleaseError(
                "E_V245_RE_KIT_CATALOG_INVALID",
                "toolchain action fields are not closed",
            )
        action_id = action["id"]
        phase, separator, kit_id = str(action_id).partition("-")
        expected_pair = TOOLCHAIN_KIT_MATRIX.get(kit_id)
        expected_inputs = (
            TOOLCHAIN_PREFETCH_INPUTS
            if phase == "prefetch"
            else TOOLCHAIN_BUILD_INPUTS
        )
        expected_receipt_fields = (
            TOOLCHAIN_PREFETCH_RECEIPT_FIELDS
            if phase == "prefetch"
            else TOOLCHAIN_BUILD_RECEIPT_FIELDS
        )
        expected_network = (
            "prefetch_only" if phase == "prefetch" else "offline_required"
        )
        if (
            separator != "-"
            or expected_pair is None
            or phase not in {"prefetch", "build"}
            or (action["language"], action["build_tool"]) != expected_pair
            or action["phase"] != phase
            or action["required_inputs"] != expected_inputs
            or action["required_receipt_fields"] != expected_receipt_fields
            or action["network_policy"] != expected_network
            or action["full_test_execution_count"] != 0
            or not isinstance(action["strategy"], str)
            or not action["strategy"].strip()
        ):
            raise ReleaseError(
                "E_V245_RE_KIT_CATALOG_INVALID",
                f"toolchain action semantic contract drift: {action_id}",
            )
    input_fields = set(value) if isinstance(value, dict) else set()
    base_fields = {
        "path",
        "sha256",
        "identity",
        "prefetch_action",
        "build_action",
        "provenance",
    }
    if (
        not isinstance(value, dict)
        or frozenset(input_fields)
        not in {
            frozenset(base_fields),
            frozenset(base_fields | {"provenance_digest"}),
        }
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_HOST_REQUIRED",
            "build-enabled plans require one exact catalog-defined toolchain host command",
        )
    require_fields(
        value,
        (
            "path",
            "sha256",
            "identity",
            "prefetch_action",
            "build_action",
            "provenance",
        ),
        "E_V245_RE_TOOLCHAIN_HOST_REQUIRED",
    )
    if (
        value["identity"] != policy["identity"]
        or value["prefetch_action"] != expected_prefetch
        or value["build_action"] != expected_build
    ):
        raise ReleaseError(
            "E_V245_RE_PERMISSION_EXCESS",
            "toolchain host identity or action differs from the selected language kit",
        )
    raw_path = value["path"]
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or not Path(raw_path).is_absolute()
        or ".." in Path(raw_path).parts
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_HOST_UNTRUSTED",
            "toolchain host path must be canonical and absolute",
            path=str(raw_path),
        )
    lexical = Path(raw_path)
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ReleaseError(
                "E_V245_RE_TOOLCHAIN_HOST_UNTRUSTED",
                "toolchain host path must not contain symlinks",
                path=raw_path,
            )
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_HOST_UNTRUSTED",
            "toolchain host executable does not exist",
            path=raw_path,
        ) from exc
    if (
        resolved != lexical
        or not resolved.is_file()
        or not os.access(resolved, os.X_OK)
        or is_within(resolved, project)
        or resolved.name != APPROVED_TOOLCHAIN_HOST_COMMAND_BASENAME
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_HOST_UNTRUSTED",
            "toolchain host must be the canonical approved executable outside project_root",
            path=raw_path,
        )
    validate_root_owned_parent_chain(
        resolved,
        "E_V245_RE_TOOLCHAIN_HOST_UNTRUSTED",
    )
    observed_stat = resolved.stat()
    if (
        observed_stat.st_uid != 0
        or observed_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_HOST_UNTRUSTED",
            "toolchain host must be root-owned and not group/world writable",
            path=raw_path,
        )
    expected_digest = require_sha256(
        value["sha256"], "toolchain_host_command.sha256"
    )
    if file_digest(resolved) != expected_digest:
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_HOST_DIGEST_DRIFT",
            "toolchain host executable digest drift",
            path=raw_path,
        )
    provenance = value["provenance"]
    required_provenance = {
        "schema_version",
        "source",
        "version",
        "manifest_sha256",
        "signature_status",
        "signer_identity",
        "host_attestation",
    }
    if (
        not isinstance(provenance, dict)
        or set(provenance) != required_provenance
        or provenance.get("schema_version") != policy["provenance_schema"]
        or provenance.get("signature_status") != "verified"
        or provenance.get("signer_identity")
        not in TRUSTED_TOOLCHAIN_PROVENANCE_SIGNERS
        or not any(
            str(provenance.get("source", "")).startswith(prefix)
            for prefix in TRUSTED_TOOLCHAIN_SOURCE_PREFIXES
        )
        or any(
            not isinstance(provenance.get(field), str)
            or not provenance[field].strip()
            for field in ("source", "version", "signer_identity")
        )
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
            "toolchain source, version, signer, and verified signature state must be frozen",
        )
    require_sha256(
        provenance.get("manifest_sha256"),
        "toolchain_host_command.provenance.manifest_sha256",
    )
    if provenance["manifest_sha256"] != file_digest(action_manifest_path):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
            "toolchain provenance is not bound to the selected action manifest",
        )
    provenance_bindings = {
        "identity": policy["identity"],
        "executable_sha256": expected_digest,
        "prefetch_action": expected_prefetch,
        "build_action": expected_build,
        "manifest_sha256": provenance["manifest_sha256"],
        "source": provenance["source"],
        "version": provenance["version"],
        "signer_identity": provenance["signer_identity"],
    }
    attestation = provenance.get("host_attestation")
    attestation_fields = {
        "schema_version",
        "algorithm",
        "issuer",
        "key_id",
        "bindings_sha256",
        "issued_at",
        "expires_at",
        "challenge_id",
        "signature",
    }
    if (
        not isinstance(attestation, dict)
        or set(attestation) != attestation_fields
        or attestation.get("schema_version")
        != "goal-teams-toolchain-provenance-attestation-v2.45"
        or attestation.get("algorithm") != "Ed25519"
        or attestation.get("issuer") != "goal-teams-trusted-host"
        or attestation.get("key_id") != TRUSTED_APPROVAL_KEY_ID
        or attestation.get("bindings_sha256")
        != object_digest(provenance_bindings)
        or not isinstance(attestation.get("challenge_id"), str)
        or not attestation["challenge_id"]
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
            "toolchain provenance requires an exact trusted-host attestation",
        )
    issued_at = parse_time(
        attestation.get("issued_at"),
        "toolchain_host_command.provenance.host_attestation.issued_at",
    )
    expires_at = parse_time(
        attestation.get("expires_at"),
        "toolchain_host_command.provenance.host_attestation.expires_at",
    )
    current_time = dt.datetime.now(dt.timezone.utc)
    if (
        issued_at > current_time + dt.timedelta(minutes=5)
        or expires_at <= current_time
        or expires_at <= issued_at
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
            "toolchain provenance attestation is outside its validity window",
        )
    unsigned_attestation = dict(attestation)
    signature_hex = unsigned_attestation.pop("signature", None)
    domain = (
        "goal-teams/release-engineer/v2.45/toolchain-provenance/"
        "host-attestation/ed25519/v1"
    ).encode("utf-8")
    try:
        attestation_valid = ED25519_VERIFY.verify(
            bytes.fromhex(TRUSTED_APPROVAL_PUBLIC_KEY_HEX),
            domain + b"\x00" + canonical_bytes(unsigned_attestation),
            bytes.fromhex(str(signature_hex)),
        )
    except (TypeError, ValueError):
        attestation_valid = False
    if not attestation_valid:
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
            "toolchain provenance trusted-host signature is invalid",
        )
    provenance_digest = object_digest(provenance)
    if (
        value.get("provenance_digest") is not None
        and value["provenance_digest"] != provenance_digest
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_PROVENANCE_INVALID",
            "toolchain provenance digest drift",
        )
    return {
        "path": str(resolved),
        "sha256": expected_digest,
        "identity": policy["identity"],
        "prefetch_action": expected_prefetch,
        "build_action": expected_build,
        "provenance": dict(provenance),
        "provenance_digest": provenance_digest,
    }


def validate_adapter_spec(spec: Any, project: Path, name: str) -> dict[str, Any] | None:
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", f"adapter {name} must be an object")
    require_fields(spec, ("path", "sha256"))
    path = resolve_project_file(spec["path"], project, f"adapters.{name}.path", executable=True)
    expected = require_sha256(spec["sha256"], f"adapters.{name}.sha256")
    observed = file_digest(path)
    if observed != expected:
        raise ReleaseError("E_V245_RE_ADAPTER_DIGEST_DRIFT", f"adapter {name} digest drift", path=str(path))
    try:
        adapter_text = path.read_bytes().decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReleaseError(
            "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
            "project adapters must be reviewable UTF-8 Bash source, not binary executables",
            path=str(path),
        ) from exc
    first_line = adapter_text.splitlines()[0] if adapter_text.splitlines() else ""
    if first_line != "#!/bin/bash" or "\x00" in adapter_text:
        raise ReleaseError(
            "E_V245_RE_ADAPTER_CLOSURE_UNVERIFIED",
            "project adapters must be reviewable UTF-8 Bash source with exact #!/bin/bash",
            path=str(path),
        )
    host_commands = validate_host_commands(spec.get("host_commands"), project, name)
    scan_dangerous_text(adapter_text, path=str(path))
    scan_full_test_commands(adapter_text, path=str(path))
    scan_adapter_indirection(
        adapter_text,
        path=str(path),
        allowed_host_commands={
            item["path"]: item["action_id"] for item in host_commands
        },
    )
    capabilities = scan_permissions(spec.get("capabilities", []))
    return {
        "path": str(path),
        "sha256": expected,
        "capabilities": capabilities,
        "idempotent": bool(spec.get("idempotent", False)),
        "host_commands": host_commands,
    }


def load_kit_json(relative: Any) -> dict[str, Any]:
    path = catalog_path(relative)
    value = load_json(path)
    return value


def discover_scripts(request: dict[str, Any]) -> dict[str, Any]:
    require_fields(request, ("project_root", "release_root"))
    project, release_root = resolve_project_and_release_root(request["project_root"], request["release_root"])
    candidates: list[dict[str, Any]] = []
    invalid_bundles: list[dict[str, Any]] = []
    managed_scripts: set[Path] = set()
    scripts_root = release_root / "runs"
    if scripts_root.is_dir():
        ensure_no_symlink_chain(scripts_root, project)
        for manifest_path in sorted(scripts_root.glob("*/scripts/*/script-bundle-manifest.json")):
            try:
                ensure_no_symlink_chain(manifest_path, project)
                validation = validate_bundle_root(manifest_path.parent)
                manifest = load_json(manifest_path)
                candidates.append(
                    {
                        "bundle_root": str(manifest_path.parent),
                        "script_bundle_version": manifest["script_bundle_version"],
                        "script_bundle_digest": validation["script_bundle_digest"],
                        "lifecycle_status": manifest.get("lifecycle_status", "unknown"),
                        "plan_digest": manifest.get("plan_digest"),
                        "target_environment": manifest.get("target_environment"),
                        "release_surface": manifest.get("release_surface"),
                        "language_kit_id": manifest.get("language_kit_id"),
                        "created_at": manifest.get("created_at"),
                    }
                )
                for step in manifest.get("steps", []):
                    if isinstance(step, dict) and isinstance(step.get("filename"), str):
                        managed_scripts.add((manifest_path.parent / step["filename"]).resolve(strict=False))
            except (ReleaseError, OSError) as exc:
                invalid_bundles.append(
                    {
                        "manifest_path": str(manifest_path),
                        "error_code": exc.code if isinstance(exc, ReleaseError) else type(exc).__name__,
                    }
                )
    unmanaged_scripts: list[dict[str, Any]] = []
    if release_root.is_dir():
        script_suffixes = {
            ".sh",
            ".zsh",
            ".fish",
            ".py",
            ".rb",
            ".pl",
            ".ps1",
            ".bat",
            ".cmd",
            ".sql",
        }
        for path in sorted(release_root.rglob("*")):
            if path.is_symlink():
                unmanaged_scripts.append({"path": str(path), "state": "unsafe_symlink"})
                continue
            if not path.is_file() or path.resolve(strict=False) in managed_scripts:
                continue
            mode = stat.S_IMODE(path.lstat().st_mode)
            if path.suffix.lower() in script_suffixes or mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                unmanaged_scripts.append(
                    {
                        "path": str(path),
                        "sha256": file_digest(path),
                        "state": "unmanaged",
                    }
                )
    report = {
        "schema_version": "goal-teams-release-script-discovery-v2.45",
        "project_root": str(project),
        "release_root": str(release_root),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "invalid_bundles": invalid_bundles,
        "unmanaged_scripts": unmanaged_scripts,
        "clarification_required": bool(candidates or invalid_bundles or unmanaged_scripts),
        "allowed_decisions": [
            "execute_exact_approved_run",
            "derive_new_version",
            "inspect_or_migrate_unmanaged",
            "ignore",
        ],
        "note": "No existing bundle is authorized by discovery alone; state exact version and digest, then obtain user confirmation.",
    }
    report["report_digest"] = object_digest(report)
    return report


def validate_script_discovery_decision(
    discovery: dict[str, Any],
    decision: Any,
) -> dict[str, Any]:
    if not discovery["clarification_required"]:
        return {"action": "not_applicable", "discovery_report_digest": discovery["report_digest"]}
    if not isinstance(decision, dict):
        raise ReleaseError(
            "E_V245_RE_SCRIPT_REUSE_CONFIRMATION_REQUIRED",
            "existing script bundles require an explicit user decision before planning",
        )
    require_fields(
        decision,
        ("action", "discovery_report_digest", "confirmation_source"),
        "E_V245_RE_SCRIPT_REUSE_CONFIRMATION_REQUIRED",
    )
    if decision["discovery_report_digest"] != discovery["report_digest"]:
        raise ReleaseError("E_V245_RE_SCRIPT_REUSE_CONFIRMATION_STALE", "script discovery report digest drift")
    action = decision["action"]
    if action not in discovery["allowed_decisions"]:
        raise ReleaseError("E_V245_RE_SCRIPT_REUSE_CONFIRMATION_REQUIRED", "unsupported existing-script decision")
    if action == "execute_exact_approved_run":
        selected = decision.get("script_bundle_digest")
        matches = [item for item in discovery["candidates"] if item["script_bundle_digest"] == selected]
        if len(matches) != 1:
            raise ReleaseError("E_V245_RE_SCRIPT_REUSE_CONFIRMATION_STALE", "selected existing script digest is unavailable")
        raise ReleaseError(
            "E_V245_RE_EXISTING_SCRIPT_SELECTED",
            "execute the selected existing approved run; a new plan must not be generated",
            path=matches[0]["bundle_root"],
        )
    if action == "derive_new_version":
        selected = decision.get("script_bundle_digest")
        if not any(item["script_bundle_digest"] == selected for item in discovery["candidates"]):
            raise ReleaseError("E_V245_RE_SCRIPT_REUSE_CONFIRMATION_STALE", "derive source script digest is unavailable")
    if action == "inspect_or_migrate_unmanaged":
        raise ReleaseError(
            "E_V245_RE_UNMANAGED_SCRIPT_REVIEW_REQUIRED",
            "unmanaged or invalid local scripts require human review before planning",
        )
    return dict(decision)


def plan_release(request: dict[str, Any]) -> dict[str, Any]:
    require_fields(
        request,
        (
            "project_root",
            "release_root",
            "release_run_id",
            "evidence_report",
            "language",
            "build_tool",
            "environment",
            "surface",
            "artifact_path",
            "surface_identity",
        ),
    )
    project, release_root = resolve_project_and_release_root(request["project_root"], request["release_root"])
    release_run_id = require_safe_id(request["release_run_id"], "release_run_id")
    discovery = discover_scripts({"project_root": str(project), "release_root": str(release_root)})
    existing_script_decision = validate_script_discovery_decision(
        discovery,
        request.get("existing_script_decision"),
    )
    report_path = resolve_project_file(request["evidence_report"], project, "evidence_report")
    report = load_json(report_path)
    if report.get("schema_version") != "goal-teams-final-release-evidence-report-v2.45":
        raise ReleaseError("E_V245_RE_FINAL_EVIDENCE_REQUIRED", "unsupported final evidence report")
    report_payload = dict(report)
    report_digest = report_payload.pop("report_digest", None)
    if not isinstance(report_digest, str) or report_digest != object_digest(report_payload):
        raise ReleaseError("E_V245_RE_FINAL_EVIDENCE_BINDING", "final evidence report digest is invalid")
    if report.get("evidence_status") != "ready" or report.get("full_test_execution_count") != 0:
        raise ReleaseError("E_V245_RE_FINAL_EVIDENCE_REQUIRED", "final release evidence is not ready")

    language = str(request["language"])
    build_tool = str(request["build_tool"])
    environment_name = str(request["environment"])
    surface_name = str(request["surface"])
    if report["environment_documents"].get("target_name") != environment_name:
        raise ReleaseError("E_V245_RE_ENVIRONMENT_BINDING_INVALID", "evidence environment does not match requested target")
    artifact_path = resolve_project_file(request["artifact_path"], project, "artifact_path")
    if file_digest(artifact_path) != report["candidate"]["artifact_digest"]:
        raise ReleaseError("E_V245_RE_ARTIFACT_DIGEST_DRIFT", "artifact_path does not match candidate artifact digest")
    catalog = load_catalog()
    language_matches = [
        entry
        for entry in catalog.get("language_adapters", [])
        if isinstance(entry, dict)
        and entry.get("language") == language
        and entry.get("build_tool") == build_tool
    ]
    if len(language_matches) != 1:
        raise ReleaseError("E_V245_RE_KIT_NO_MATCH", "no exact language/build tool kit match")
    language_kit = language_matches[0]
    if language_kit.get("lifecycle") != "approved":
        raise ReleaseError("E_V245_RE_KIT_NOT_APPROVED", "language kit is not approved")
    environment_kit = select_catalog_entry(catalog.get("environments"), "name", environment_name, "E_V245_RE_KIT_NO_MATCH")
    surface_kit = select_catalog_entry(catalog.get("surfaces"), "name", surface_name, "E_V245_RE_KIT_NO_MATCH")
    environment_recipe = load_kit_json(environment_kit.get("plan"))
    surface_recipe = load_kit_json(surface_kit.get("plan"))
    if environment_recipe.get("build_allowed"):
        toolchain_host_command = validate_toolchain_host_command(
            request.get("toolchain_host_command"),
            project,
            language_kit,
        )
    else:
        if request.get("toolchain_host_command") is not None:
            raise ReleaseError(
                "E_V245_RE_PERMISSION_EXCESS",
                "toolchain host command is forbidden when the target environment does not allow builds",
            )
        toolchain_host_command = None
    surface_identity = request["surface_identity"]
    if not isinstance(surface_identity, dict):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "surface_identity must be an object")
    surface_identity_fields = {
        "application": ("configuration_identity",),
        "container-kubernetes": ("namespace", "workload"),
        "wechat-miniprogram": ("appid", "code_version"),
        "github-skill": ("repository", "tag", "expected_installed_tree_digest"),
    }[surface_name]
    require_fields(surface_identity, surface_identity_fields)
    if surface_name == "github-skill":
        require_sha256(
            surface_identity["expected_installed_tree_digest"],
            "surface_identity.expected_installed_tree_digest",
        )
    surface_identity_digest = object_digest(surface_identity)
    rollback_identity = request.get("rollback_identity")
    rollback_identity_digest = object_digest(rollback_identity)
    if environment_name in {"staging", "production"}:
        if not isinstance(rollback_identity, dict):
            raise ReleaseError(
                "E_V245_RE_ROLLBACK_TARGET_REQUIRED",
                "staging and production plans require an exact previous-good rollback identity",
            )
        rollback_fields = {
            "application": ("artifact_digest", "configuration_identity"),
            "container-kubernetes": (
                "oci_index_digest",
                "namespace",
                "workload",
            ),
            "wechat-miniprogram": ("appid", "code_version"),
            "github-skill": (
                "repository",
                "tag",
                "tag_commit",
                "asset_digest",
                "expected_installed_tree_digest",
            ),
        }[surface_name]
        require_fields(rollback_identity, rollback_fields)
        for digest_field in {
            "application": ("artifact_digest",),
            "container-kubernetes": ("oci_index_digest",),
            "wechat-miniprogram": (),
            "github-skill": ("asset_digest", "expected_installed_tree_digest"),
        }[surface_name]:
            require_sha256(
                rollback_identity[digest_field],
                f"rollback_identity.{digest_field}",
            )
        if surface_name == "github-skill" and (
            not isinstance(rollback_identity["tag_commit"], str)
            or COMMIT_SHA.fullmatch(rollback_identity["tag_commit"]) is None
        ):
            raise ReleaseError(
                "E_V245_RE_ROLLBACK_TARGET_REQUIRED",
                "rollback_identity.tag_commit must be a 40-character lowercase commit SHA",
            )
        rollback_identity_digest = object_digest(rollback_identity)

    adapters_input = request.get("adapters", {})
    if not isinstance(adapters_input, dict):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "adapters must be an object")
    adapters = {
        name: validate_adapter_spec(adapters_input.get(name), project, name)
        for name in ("backup", "benchmark", "deploy", "verify", "rollback")
    }
    required_adapters = {"benchmark", "deploy", "verify"}
    if environment_kit.get("backup_required"):
        required_adapters.add("backup")
    if environment_name in {"staging", "production"}:
        required_adapters.add("rollback")
    missing_adapters = sorted(name for name in required_adapters if adapters[name] is None)

    gates = request.get("gates", {})
    if not isinstance(gates, dict):
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "gates must be an object")
    if environment_name == "production":
        restore = gates.get("restore_proof")
        if not isinstance(restore, dict):
            missing_adapters.append("restore_proof")
        else:
            restore_path = resolve_project_file(restore.get("path"), project, "gates.restore_proof.path")
            restore_sha = require_sha256(restore.get("sha256"), "gates.restore_proof.sha256")
            if file_digest(restore_path) != restore_sha or restore.get("status") != "passed":
                raise ReleaseError("E_V245_RE_BACKUP_RESTORE_UNVERIFIED", "production restore proof is not current")
            gates = dict(gates)
            gates["restore_proof"] = {"path": str(restore_path), "sha256": restore_sha, "status": "passed"}

    selected_paths = [
        str(language_kit["prefetch_template"]),
        str(language_kit["build_template"]),
        str(catalog["toolchain_host_command"]["action_manifest"]),
        *[str(value) for value in catalog.get("common_templates", {}).values()],
        str(environment_kit["plan"]),
        str(surface_kit["plan"]),
    ]
    selected_templates = []
    for relative in selected_paths:
        path = catalog_path(relative)
        selected_templates.append({"path": relative, "sha256": file_digest(path)})

    requested_capabilities: list[str] = ["release_preflight", "benchmark_baseline", "deploy_target", "post_release_verify"]
    if environment_recipe.get("build_allowed"):
        requested_capabilities.extend(["dependency_prefetch", "isolated_build", "artifact_identity_verify"])
    else:
        requested_capabilities.append("artifact_identity_verify")
    if environment_kit.get("backup_required"):
        requested_capabilities.append("backup_create")
    if environment_name in {"staging", "production"}:
        requested_capabilities.append("rollback_execute")
    for spec in adapters.values():
        if spec is not None:
            requested_capabilities.extend(spec["capabilities"])
    requested_capabilities = scan_permissions(requested_capabilities)
    kit_selection = {
        "language_kit_id": language_kit["id"],
        "environment_kit_id": environment_kit["id"],
        "surface_kit_id": surface_kit["id"],
        "selected_templates": selected_templates,
    }
    kit_selection_digest = object_digest(kit_selection)

    run_root = release_root / "runs" / release_run_id
    ensure_no_symlink_chain(run_root, project)
    plan_dir = run_root / "plan"
    plan_path = plan_dir / "release-plan.json"
    if run_root.exists():
        raise ReleaseError("E_V245_RE_RUN_ALREADY_EXISTS", "release run id already exists", path=str(run_root))

    plan: dict[str, Any] = {
        "schema_version": "goal-teams-release-plan-v2.45",
        "plan_version": "1.0.0",
        "release_run_id": release_run_id,
        "project_root": str(project),
        "release_root": str(release_root),
        "run_root": str(run_root),
        "evidence_report": {"path": str(report_path), "sha256": file_digest(report_path), "report_digest": report_digest},
        "candidate": report["candidate"],
        "artifact_path": str(artifact_path),
        "environment_documents": report["environment_documents"],
        "language_kit": language_kit,
        "toolchain_host_command": toolchain_host_command,
        "environment_kit": environment_kit,
        "environment_recipe": environment_recipe,
        "surface_kit": surface_kit,
        "surface_recipe": surface_recipe,
        "surface_identity": surface_identity,
        "surface_identity_digest": surface_identity_digest,
        "rollback_identity": rollback_identity,
        "rollback_identity_digest": rollback_identity_digest,
        "selected_templates": selected_templates,
        "kit_selection_digest": kit_selection_digest,
        "adapters": adapters,
        "execution_interpreter": validate_execution_interpreter(),
        "gates": gates,
        "requested_capabilities": requested_capabilities,
        "max_auto_loop_attempts": int(request.get("max_auto_loop_attempts", 3)),
        "release_intent_source": report.get("release_intent_source", "none"),
        "script_discovery": discovery,
        "existing_script_decision": existing_script_decision,
        "missing_requirements": sorted(set(missing_adapters)),
        "plan_state": "blocked" if missing_adapters else "awaiting_plan_approval",
        "created_at": now_utc(),
    }
    if not 1 <= plan["max_auto_loop_attempts"] <= 10:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "max_auto_loop_attempts must be between 1 and 10")
    plan["plan_digest"] = object_digest(plan)
    plan_markdown = (
        "# Release Plan\n\n"
        f"- release_run_id: `{release_run_id}`\n"
        f"- plan_digest: `{plan['plan_digest']}`\n"
        f"- state: `{plan['plan_state']}`\n"
        f"- language/build tool: `{language}` / `{build_tool}`\n"
        f"- environment: `{environment_name}`\n"
        f"- surface: `{surface_name}`\n"
        f"- missing requirements: `{', '.join(plan['missing_requirements']) or 'none'}`\n"
        "- full test execution: `forbidden`\n"
        "- script generation: requires exact plan approval\n"
    )
    write_json(plan_path, plan)
    atomic_write(plan_dir / "release-plan.md", plan_markdown.encode("utf-8"))
    return {"passed": True, "plan_path": str(plan_path), "plan": plan}


def verify_plan_digest(plan: dict[str, Any]) -> str:
    supplied = plan.get("plan_digest")
    payload = dict(plan)
    payload.pop("plan_digest", None)
    if not isinstance(supplied, str) or supplied != object_digest(payload):
        raise ReleaseError("E_V245_RE_PLAN_DIGEST_DRIFT", "release plan digest drift")
    return supplied


def validate_expiry(value: dict[str, Any]) -> None:
    if parse_time(value.get("expires_at"), "expires_at") <= dt.datetime.now(dt.timezone.utc):
        raise ReleaseError("E_V245_RE_APPROVAL_EXPIRED", "approval is expired")


def validate_host_approval(
    approval: dict[str, Any],
    approval_type: str,
    expected_bindings: dict[str, Any],
) -> None:
    acceptance = approval.get("host_acceptance")
    required = {
        "schema_version",
        "algorithm",
        "issuer",
        "key_id",
        "approval_type",
        "approval_id",
        "issued_at",
        "expires_at",
        "challenge_id",
        "bindings_sha256",
        "database_safety_attested",
        "least_privilege_attested",
        "human_confirmation_attested",
        "execution_isolation_attested",
        "credential_scrubbing_attested",
        "signature",
    }
    if not isinstance(acceptance, dict) or set(acceptance) != required:
        raise ReleaseError(
            "E_V245_RE_TRUSTED_APPROVAL_REQUIRED",
            "script generation and live execution require an exact trusted-host signed human approval",
        )
    if (
        acceptance.get("schema_version")
        != "goal-teams-release-engineer-host-approval-v2.45"
        or acceptance.get("algorithm") != "Ed25519"
        or acceptance.get("issuer") != "goal-teams-trusted-host"
        or acceptance.get("key_id") != TRUSTED_APPROVAL_KEY_ID
        or acceptance.get("approval_type") != approval_type
        or acceptance.get("approval_id") != approval.get("approval_id")
        or acceptance.get("expires_at") != approval.get("expires_at")
        or acceptance.get("bindings_sha256") != object_digest(expected_bindings)
        or acceptance.get("database_safety_attested") is not True
        or acceptance.get("least_privilege_attested") is not True
        or acceptance.get("human_confirmation_attested") is not True
        or acceptance.get("execution_isolation_attested") is not True
        or acceptance.get("credential_scrubbing_attested") is not True
        or not isinstance(acceptance.get("challenge_id"), str)
        or not acceptance["challenge_id"]
    ):
        raise ReleaseError(
            "E_V245_RE_TRUSTED_APPROVAL_INVALID",
            "trusted-host approval identity or safety binding is invalid",
        )
    issued_at = parse_time(acceptance.get("issued_at"), "host_acceptance.issued_at")
    expires_at = parse_time(
        acceptance.get("expires_at"), "host_acceptance.expires_at"
    )
    now = dt.datetime.now(dt.timezone.utc)
    if issued_at > now + dt.timedelta(minutes=5) or expires_at <= now:
        raise ReleaseError(
            "E_V245_RE_TRUSTED_APPROVAL_INVALID",
            "trusted-host approval is outside its validity window",
        )
    unsigned = dict(acceptance)
    signature_hex = unsigned.pop("signature", None)
    domain = (
        f"goal-teams/release-engineer/v2.45/{approval_type}/"
        "human-approval/ed25519/v1"
    ).encode("utf-8")
    try:
        valid = ED25519_VERIFY.verify(
            bytes.fromhex(TRUSTED_APPROVAL_PUBLIC_KEY_HEX),
            domain + b"\x00" + canonical_bytes(unsigned),
            bytes.fromhex(str(signature_hex)),
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ReleaseError(
            "E_V245_RE_TRUSTED_APPROVAL_INVALID",
            "trusted-host approval signature is invalid",
        )


def validate_plan_approval(approval: dict[str, Any], plan: dict[str, Any]) -> None:
    require_fields(
        approval,
        (
            "approval_type",
            "approval_id",
            "plan_digest",
            "candidate_artifact_digest",
            "source_commit",
            "source_tree_digest",
            "environment_document_digest",
            "environment_document_set_digest",
            "target_environment",
            "release_surface",
            "kit_selection_digest",
            "surface_identity_digest",
            "rollback_identity_digest",
            "release_root",
            "approver",
            "expires_at",
        ),
        "E_V245_RE_PLAN_APPROVAL_REQUIRED",
    )
    validate_expiry(approval)
    if approval["approval_type"] != "plan":
        raise ReleaseError("E_V245_RE_PLAN_APPROVAL_REQUIRED", "approval_type must be plan")
    expected = {
        "plan_digest": plan["plan_digest"],
        "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
        "source_commit": plan["candidate"]["source_commit"],
        "source_tree_digest": plan["candidate"]["source_tree_digest"],
        "environment_document_digest": plan["environment_documents"]["target_document_digest"],
        "environment_document_set_digest": plan["environment_documents"]["set_digest"],
        "target_environment": plan["environment_kit"]["name"],
        "release_surface": plan["surface_kit"]["name"],
        "kit_selection_digest": plan["kit_selection_digest"],
        "surface_identity_digest": plan["surface_identity_digest"],
        "rollback_identity_digest": plan["rollback_identity_digest"],
        "release_root": plan["release_root"],
    }
    for field, value in expected.items():
        if approval.get(field) != value:
            raise ReleaseError("E_V245_RE_PLAN_APPROVAL_STALE", f"plan approval binding drift: {field}")
    validate_host_approval(approval, "plan", expected)


def quote(value: str) -> str:
    return shlex.quote(value)


def adapter_values(plan: dict[str, Any], name: str) -> tuple[str, str]:
    spec = plan["adapters"].get(name)
    if spec is None:
        return "", ""
    return str(spec["path"]), str(spec["sha256"])


def render_template(path: Path, values: dict[str, str]) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", text)))
    if unresolved:
        raise ReleaseError("E_V245_RE_SCRIPT_RENDER_INCOMPLETE", f"unresolved template placeholders: {unresolved}", path=str(path))
    scan_dangerous_text(text, path=str(path))
    scan_full_test_commands(text, path=str(path))
    return text


def required_checks(plan: dict[str, Any]) -> str:
    project = Path(plan["project_root"])
    kit = plan["language_kit"]
    lines = []
    for relative in kit.get("required_files", []):
        target = project / relative
        lines.append(f"test -f {quote(str(target))}")
    any_files = [project / relative for relative in kit.get("required_files_any", [])]
    if any_files:
        expression = " && ".join(f"[[ ! -e {quote(str(path))} ]]" for path in any_files)
        lines.append(f"if {expression}; then echo 'required_build_file_missing' >&2; exit 41; fi")
    return "\n".join(lines)


def compose_bundle(request: dict[str, Any]) -> dict[str, Any]:
    require_fields(request, ("plan_path", "plan_approval_path", "script_bundle_version"))
    plan_input = Path(str(request["plan_path"]))
    plan_path = plan_input.resolve(strict=False)
    approval_path = Path(str(request["plan_approval_path"])).resolve(strict=False)
    plan = load_json(plan_path)
    verify_plan_digest(plan)
    if plan.get("plan_state") != "awaiting_plan_approval":
        raise ReleaseError("E_V245_RE_PLAN_NOT_READY", "release plan is not ready for approval")
    approval = load_json(approval_path)
    validate_plan_approval(approval, plan)
    project, release_root = resolve_project_and_release_root(plan["project_root"], plan["release_root"])
    validate_execution_interpreter(plan.get("execution_interpreter"))
    if plan["environment_recipe"].get("build_allowed"):
        if (
            validate_toolchain_host_command(
                plan.get("toolchain_host_command"),
                project,
                plan["language_kit"],
            )
            != plan["toolchain_host_command"]
        ):
            raise ReleaseError(
                "E_V245_RE_TOOLCHAIN_HOST_DIGEST_DRIFT",
                "toolchain host no longer matches the approved plan",
            )
    elif plan.get("toolchain_host_command") is not None:
        raise ReleaseError(
            "E_V245_RE_PERMISSION_EXCESS",
            "toolchain host command is forbidden for this environment",
        )
    for adapter_name, frozen_spec in plan["adapters"].items():
        if validate_adapter_spec(frozen_spec, project, adapter_name) != frozen_spec:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_DIGEST_DRIFT",
                f"adapter {adapter_name} no longer matches the approved plan",
            )
    if not is_within(plan_input, release_root):
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "plan must be stored inside release_root")
    ensure_no_symlink_chain(plan_input, project)
    version = require_safe_id(request["script_bundle_version"], "script_bundle_version")
    bundle_root = Path(plan["run_root"]) / "scripts" / version
    if bundle_root.exists():
        raise ReleaseError("E_V245_RE_SCRIPT_VERSION_CONFLICT", "script bundle version already exists", path=str(bundle_root))
    ensure_no_symlink_chain(bundle_root, project)

    dependency_bundle = Path(plan["run_root"]) / "dependencies"
    toolchain_receipts = Path(plan["run_root"]) / "toolchain-receipts"
    if plan["environment_recipe"].get("build_allowed"):
        ensure_no_symlink_chain(toolchain_receipts, project)
        toolchain_receipts.mkdir(mode=0o700, exist_ok=True)
    action_manifest_path = catalog_path(
        load_catalog()["toolchain_host_command"]["action_manifest"]
    )
    values = {
        "PLAN_PATH_Q": quote(str(plan_path)),
        "PLAN_DIGEST_Q": quote(plan["plan_digest"]),
        "PROJECT_ROOT_Q": quote(str(project)),
        "RELEASE_RUN_ROOT_Q": quote(plan["run_root"]),
        "DEPENDENCY_BUNDLE_Q": quote(str(dependency_bundle / "packages")),
        "DEPENDENCY_REQUIREMENTS_Q": quote(str(dependency_bundle / "requirements.lock.txt")),
        "ARTIFACT_PATH_Q": quote(plan["artifact_path"]),
        "ARTIFACT_SHA256_Q": quote(plan["candidate"]["artifact_digest"]),
        "REQUIRED_FILE_CHECKS": required_checks(plan),
        "BACKUP_REQUIRED_Q": quote("true" if plan["environment_kit"].get("backup_required") else "false"),
        "TOOLCHAIN_HOST_Q": quote(
            plan["toolchain_host_command"]["path"]
            if plan.get("toolchain_host_command")
            else ""
        ),
        "TOOLCHAIN_HOST_SHA256_Q": quote(
            plan["toolchain_host_command"]["sha256"]
            if plan.get("toolchain_host_command")
            else ""
        ),
        "TOOLCHAIN_PREFETCH_ACTION_Q": quote(
            plan["toolchain_host_command"]["prefetch_action"]
            if plan.get("toolchain_host_command")
            else ""
        ),
        "TOOLCHAIN_BUILD_ACTION_Q": quote(
            plan["toolchain_host_command"]["build_action"]
            if plan.get("toolchain_host_command")
            else ""
        ),
        "TOOLCHAIN_PREFETCH_RECEIPT_Q": quote(
            str(
                toolchain_receipts
                / f"{plan['language_kit']['prefetch_action']}.json"
            )
        ),
        "TOOLCHAIN_BUILD_RECEIPT_Q": quote(
            str(
                toolchain_receipts
                / f"{plan['language_kit']['build_action']}.json"
            )
        ),
        "TOOLCHAIN_ACTION_MANIFEST_SHA256_Q": quote(
            file_digest(action_manifest_path)
        ),
    }
    for adapter_name in ("backup", "benchmark", "deploy", "verify", "rollback"):
        adapter_path, adapter_sha = adapter_values(plan, adapter_name)
        values[f"{adapter_name.upper()}_ADAPTER_Q"] = quote(adapter_path)
        values[f"{adapter_name.upper()}_ADAPTER_SHA256_Q"] = quote(adapter_sha)

    catalog = load_catalog()
    steps = [("00-preflight.sh", catalog["common_templates"]["preflight"], True, False, "release_preflight")]
    if plan["environment_recipe"].get("build_allowed"):
        steps.extend(
            [
                ("20-prefetch-dependencies.sh", plan["language_kit"]["prefetch_template"], True, False, "dependency_prefetch"),
                ("40-build.sh", plan["language_kit"]["build_template"], True, False, "isolated_build"),
                ("45-artifact-identity.sh", catalog["common_templates"]["artifact_identity"], True, False, "artifact_identity_verify"),
            ]
        )
    else:
        steps.append(("30-artifact-identity.sh", catalog["common_templates"]["artifact_identity"], True, False, "artifact_identity_verify"))
    if plan["environment_kit"].get("backup_required"):
        steps.append(("50-backup.sh", catalog["common_templates"]["backup"], False, True, "backup_create"))
    steps.extend(
        [
            ("60-benchmark-baseline.sh", catalog["common_templates"]["benchmark"], False, False, "benchmark_baseline"),
            ("70-deploy.sh", catalog["common_templates"]["deploy"], False, True, "deploy_target"),
            ("80-post-release-verify.sh", catalog["common_templates"]["verify"], True, False, "post_release_verify"),
            ("90-rollback.sh", catalog["common_templates"]["rollback"], False, True, "rollback_execute"),
        ]
    )

    rendered: list[dict[str, Any]] = []
    rendered_bytes: dict[str, bytes] = {}
    for filename, relative, idempotent, external_write, capability in steps:
        template = catalog_path(relative)
        content = render_template(template, values)
        data = content.encode("utf-8")
        rendered_bytes[filename] = data
        rendered.append(
            {
                "filename": filename,
                "template_path": relative,
                "template_sha256": file_digest(template),
                "sha256": hashlib.sha256(data).hexdigest(),
                "idempotent": idempotent,
                "external_write": external_write,
                "capability": capability,
            }
        )

    bundle_manifest: dict[str, Any] = {
        "schema_version": "goal-teams-release-script-bundle-v2.45",
        "script_bundle_version": version,
        "lifecycle_status": "approved_for_exact_plan",
        "plan_digest": plan["plan_digest"],
        "plan_approval_id": approval["approval_id"],
        "plan_approval_path": str(approval_path),
        "plan_approval_digest": file_digest(approval_path),
        "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
        "environment_document_digest": plan["environment_documents"]["target_document_digest"],
        "target_environment": plan["environment_kit"]["name"],
        "release_surface": plan["surface_kit"]["name"],
        "surface_identity_digest": plan["surface_identity_digest"],
        "rollback_identity_digest": plan["rollback_identity_digest"],
        "language_kit_id": plan["language_kit"]["id"],
        "toolchain_host_command_digest": (
            object_digest(plan["toolchain_host_command"])
            if plan.get("toolchain_host_command")
            else None
        ),
        "requested_capabilities": plan["requested_capabilities"],
        "steps": rendered,
        "created_at": now_utc(),
    }
    bundle_manifest["script_bundle_digest"] = object_digest(bundle_manifest)

    bundle_root.mkdir(parents=True)
    for filename, data in rendered_bytes.items():
        atomic_write(bundle_root / filename, data, mode=0o750)
    write_json(bundle_root / "script-bundle-manifest.json", bundle_manifest)
    index = (
        "# Release Script Bundle\n\n"
        f"- version: `{version}`\n"
        f"- digest: `{bundle_manifest['script_bundle_digest']}`\n"
        f"- plan: `{plan['plan_digest']}`\n"
        f"- environment: `{plan['environment_kit']['name']}`\n"
        f"- language kit: `{plan['language_kit']['id']}`\n"
        "- changes: generated from approved built-in Release Kit modules\n"
        "- direct template execution: forbidden\n"
    )
    atomic_write(bundle_root / "index.md", index.encode("utf-8"))
    validate_bundle_root(bundle_root)
    return {
        "passed": True,
        "bundle_root": str(bundle_root),
        "script_bundle_digest": bundle_manifest["script_bundle_digest"],
        "manifest": bundle_manifest,
    }


def verify_bundle_digest(manifest: dict[str, Any]) -> str:
    supplied = manifest.get("script_bundle_digest")
    payload = dict(manifest)
    payload.pop("script_bundle_digest", None)
    if not isinstance(supplied, str) or supplied != object_digest(payload):
        raise ReleaseError("E_V245_RE_SCRIPT_DIGEST_DRIFT", "script bundle manifest digest drift")
    return supplied


def validate_bundle_root(bundle_root: Path) -> dict[str, Any]:
    bundle_input = bundle_root
    if bundle_input.is_symlink():
        raise ReleaseError("E_V245_RE_SCRIPT_BUNDLE_INVALID", "bundle root must be a non-symlink directory")
    bundle_root = bundle_input.resolve(strict=True)
    if is_within(bundle_root, KITS_ROOT.resolve(strict=True)):
        raise ReleaseError("E_V245_RE_TEMPLATE_EXECUTION_FORBIDDEN", "template paths can never be executed")
    if bundle_root.is_symlink() or not bundle_root.is_dir():
        raise ReleaseError("E_V245_RE_SCRIPT_BUNDLE_INVALID", "bundle root must be a non-symlink directory")
    manifest = load_json(bundle_root / "script-bundle-manifest.json")
    verify_bundle_digest(manifest)
    scan_permissions(manifest.get("requested_capabilities", []))
    steps = manifest.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ReleaseError("E_V245_RE_SCRIPT_BUNDLE_INVALID", "bundle steps must be a non-empty list")
    observed = []
    for step in steps:
        if not isinstance(step, dict):
            raise ReleaseError("E_V245_RE_SCRIPT_BUNDLE_INVALID", "bundle step must be an object")
        require_fields(step, ("filename", "sha256", "template_path", "template_sha256", "idempotent", "external_write", "capability"))
        filename = step["filename"]
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ReleaseError("E_V245_RE_SCRIPT_BUNDLE_INVALID", "step filename must be a basename")
        path = bundle_root / filename
        if not path.is_file() or path.is_symlink():
            raise ReleaseError("E_V245_RE_SCRIPT_BUNDLE_INVALID", "step script is missing or unsafe", path=str(path))
        if file_digest(path) != require_sha256(step["sha256"], "step.sha256"):
            raise ReleaseError("E_V245_RE_SCRIPT_DIGEST_DRIFT", "step digest drift", path=str(path))
        template = catalog_path(step["template_path"])
        if file_digest(template) != require_sha256(step["template_sha256"], "step.template_sha256"):
            raise ReleaseError("E_V245_RE_KIT_DIGEST_DRIFT", "template digest drift", path=str(template))
        text = path.read_text(encoding="utf-8")
        if "{{" in text or "}}" in text:
            raise ReleaseError("E_V245_RE_SCRIPT_RENDER_INCOMPLETE", "rendered script contains unresolved placeholder", path=str(path))
        scan_dangerous_text(text, path=str(path))
        scan_full_test_commands(text, path=str(path))
        observed.append({"filename": filename, "sha256": step["sha256"]})
    return {
        "passed": True,
        "bundle_root": str(bundle_root),
        "script_bundle_digest": manifest["script_bundle_digest"],
        "steps": observed,
    }


def validate_execution_approval(
    approval: dict[str, Any],
    manifest: dict[str, Any],
    plan: dict[str, Any],
    *,
    mode: str,
    operation: str,
) -> None:
    require_fields(
        approval,
        (
            "approval_type",
            "approval_id",
            "execution_id",
            "mode",
            "operation",
            "plan_approval_id",
            "plan_digest",
            "script_bundle_digest",
            "candidate_artifact_digest",
            "source_commit",
            "source_tree_digest",
            "environment_document_digest",
            "environment_document_set_digest",
            "target_environment",
            "release_surface",
            "kit_selection_digest",
            "surface_identity_digest",
            "rollback_identity_digest",
            "requested_capabilities",
            "approver",
            "expires_at",
        ),
        "E_V245_RE_EXEC_APPROVAL_REQUIRED",
    )
    validate_expiry(approval)
    if approval["approval_type"] != "execution":
        raise ReleaseError("E_V245_RE_EXEC_APPROVAL_REQUIRED", "approval_type must be execution")
    expected = {
        "execution_id": approval["execution_id"],
        "mode": mode,
        "operation": operation,
        "plan_approval_id": manifest["plan_approval_id"],
        "plan_digest": plan["plan_digest"],
        "script_bundle_digest": manifest["script_bundle_digest"],
        "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
        "source_commit": plan["candidate"]["source_commit"],
        "source_tree_digest": plan["candidate"]["source_tree_digest"],
        "environment_document_digest": plan["environment_documents"]["target_document_digest"],
        "environment_document_set_digest": plan["environment_documents"]["set_digest"],
        "target_environment": plan["environment_kit"]["name"],
        "release_surface": plan["surface_kit"]["name"],
        "kit_selection_digest": plan["kit_selection_digest"],
        "surface_identity_digest": plan["surface_identity_digest"],
        "rollback_identity_digest": plan["rollback_identity_digest"],
    }
    for field, value in expected.items():
        if approval.get(field) != value:
            raise ReleaseError("E_V245_RE_EXEC_APPROVAL_STALE", f"execution approval binding drift: {field}")
    approved_capabilities = scan_permissions(approval["requested_capabilities"])
    if approved_capabilities != scan_permissions(plan["requested_capabilities"]):
        raise ReleaseError("E_V245_RE_EXEC_APPROVAL_STALE", "execution capability binding drift")
    validate_host_approval(
        approval,
        "execution",
        {**expected, "requested_capabilities": approved_capabilities},
    )


def step_receipt(
    *,
    step: dict[str, Any],
    attempt: int,
    status: str,
    exit_code: int | None,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    return {
        "step": step["filename"],
        "capability": step["capability"],
        "attempt": attempt,
        "status": status,
        "exit_code": exit_code,
        "stdout": redact(stdout),
        "stderr": redact(stderr),
        "observed_at": now_utc(),
    }


def validate_gate_receipt(
    plan: dict[str, Any],
    gate_name: str,
    *,
    execution_id: str,
    operation: str,
    intent_created_at: str,
) -> dict[str, Any]:
    gates = plan.get("gates", {})
    spec = gates.get(gate_name)
    if not isinstance(spec, dict):
        code = {
            "backup_receipt": "E_V245_RE_BACKUP_REQUIRED",
            "benchmark_baseline": "E_V245_RE_BENCHMARK_REQUIRED",
            "post_release_verification": "E_V245_RE_OBSERVATION_REQUIRED",
        }[gate_name]
        raise ReleaseError(code, f"{gate_name} gate receipt is required")
    project = Path(plan["project_root"])
    path = resolve_project_file(spec.get("path"), project, f"gates.{gate_name}.path")
    observed_digest = file_digest(path)
    if spec.get("sha256") is not None and observed_digest != require_sha256(
        spec.get("sha256"), f"gates.{gate_name}.sha256"
    ):
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", f"{gate_name} receipt digest drift")
    payload = load_json(path)
    require_fields(
        payload,
        (
            "schema_version",
            "gate",
            "status",
            "execution_id",
            "operation",
            "target_environment",
            "candidate_artifact_digest",
            "environment_document_digest",
            "observed_at",
            "assertions",
        ),
        "E_V245_RE_GATE_BINDING_INVALID",
    )
    if (
        payload.get("schema_version")
        != "goal-teams-release-gate-receipt-v2.45"
        or payload.get("gate") != gate_name
        or payload.get("execution_id") != execution_id
        or payload.get("operation") != operation
    ):
        raise ReleaseError(
            "E_V245_RE_GATE_BINDING_INVALID",
            f"{gate_name} execution binding mismatch",
        )
    assertions = payload.get("assertions")
    if (
        not isinstance(assertions, list)
        or not assertions
        or any(
            not isinstance(assertion, dict)
            or not isinstance(assertion.get("name"), str)
            or not assertion["name"]
            or assertion.get("passed") is not True
            for assertion in assertions
        )
    ):
        raise ReleaseError(
            "E_V245_RE_GATE_NOT_PASSED",
            f"{gate_name} requires non-empty passed assertions",
        )
    observed_at = parse_time(payload.get("observed_at"), f"{gate_name}.observed_at")
    intent_at = parse_time(intent_created_at, "execution_intent.created_at")
    current = dt.datetime.now(dt.timezone.utc)
    if (
        observed_at < intent_at - dt.timedelta(minutes=5)
        or observed_at > current + dt.timedelta(minutes=5)
    ):
        raise ReleaseError(
            "E_V245_RE_GATE_BINDING_INVALID",
            f"{gate_name} observation is outside the current execution window",
        )
    if payload.get("status") not in ACCEPTED_EVIDENCE_STATES:
        code = "E_V245_RE_BENCHMARK_INCONCLUSIVE" if gate_name == "benchmark_baseline" else "E_V245_RE_GATE_NOT_PASSED"
        raise ReleaseError(code, f"{gate_name} status is not passed")
    if payload.get("target_environment") != plan["environment_kit"]["name"]:
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", f"{gate_name} environment binding mismatch")
    if payload.get("candidate_artifact_digest") != plan["candidate"]["artifact_digest"]:
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", f"{gate_name} candidate binding mismatch")
    if payload.get("environment_document_digest") != plan["environment_documents"]["target_document_digest"]:
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", f"{gate_name} environment document binding mismatch")
    if gate_name == "benchmark_baseline":
        require_sha256(
            payload.get("baseline_data_digest"),
            "benchmark_baseline.baseline_data_digest",
        )
    result = {
        "gate": gate_name,
        "path": str(path),
        "sha256": observed_digest,
        "status": payload["status"],
        "target_environment": payload["target_environment"],
        "candidate_artifact_digest": payload["candidate_artifact_digest"],
        "environment_document_digest": payload["environment_document_digest"],
        "execution_id": payload["execution_id"],
        "operation": payload["operation"],
        "observed_at": payload["observed_at"],
        "assertions": assertions,
    }
    if gate_name == "benchmark_baseline":
        result["baseline_data_digest"] = payload["baseline_data_digest"]
    if payload.get("backup_scope_digest") is not None:
        result["backup_scope_digest"] = require_sha256(
            payload["backup_scope_digest"],
            f"{gate_name}.backup_scope_digest",
        )
    return result


def validate_restore_proof(plan: dict[str, Any]) -> dict[str, Any] | None:
    if plan["environment_kit"]["name"] != "production":
        return None
    spec = plan.get("gates", {}).get("restore_proof")
    if not isinstance(spec, dict):
        raise ReleaseError("E_V245_RE_BACKUP_RESTORE_UNVERIFIED", "production restore proof is required")
    project = Path(plan["project_root"])
    path = resolve_project_file(spec.get("path"), project, "gates.restore_proof.path")
    expected_digest = require_sha256(spec.get("sha256"), "gates.restore_proof.sha256")
    if file_digest(path) != expected_digest:
        raise ReleaseError("E_V245_RE_BACKUP_RESTORE_UNVERIFIED", "production restore proof digest drift")
    payload = load_json(path)
    require_fields(
        payload,
        (
            "status",
            "target_environment",
            "environment_document_digest",
            "backup_scope_digest",
            "restore_point_id",
            "verified_at",
        ),
        "E_V245_RE_BACKUP_RESTORE_UNVERIFIED",
    )
    if (
        payload.get("status") != "passed"
        or payload.get("target_environment") != "production"
        or payload.get("environment_document_digest") != plan["environment_documents"]["target_document_digest"]
    ):
        raise ReleaseError("E_V245_RE_BACKUP_RESTORE_UNVERIFIED", "production restore proof is not current")
    require_sha256(payload["backup_scope_digest"], "restore_proof.backup_scope_digest")
    verified_at = parse_time(payload["verified_at"], "restore_proof.verified_at")
    current = dt.datetime.now(dt.timezone.utc)
    max_age_hours = int(spec.get("max_age_hours", 720))
    if (
        max_age_hours < 1
        or verified_at > current + dt.timedelta(minutes=5)
        or verified_at < current - dt.timedelta(hours=max_age_hours)
    ):
        raise ReleaseError("E_V245_RE_BACKUP_RESTORE_UNVERIFIED", "production restore proof is stale")
    return {
        "path": str(path),
        "sha256": expected_digest,
        "backup_scope_digest": payload["backup_scope_digest"],
        "restore_point_id": payload["restore_point_id"],
        "verified_at": payload["verified_at"],
    }


def validate_environment_document_binding(plan: dict[str, Any]) -> None:
    project = Path(plan["project_root"])
    environment = plan.get("environment_documents", {})
    documents = environment.get("documents")
    required = {"local", "development", "test", "staging", "production"}
    if not isinstance(documents, dict) or set(documents) != required:
        raise ReleaseError("E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED", "environment document set is incomplete")
    observed: dict[str, dict[str, str]] = {}
    for name in sorted(required):
        spec = documents[name]
        if not isinstance(spec, dict):
            raise ReleaseError("E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED", f"environment document is invalid: {name}")
        require_fields(
            spec,
            (
                "schema_version",
                "path",
                "sha256",
                "created_at",
                "architecture_baseline_commit",
                "issuer",
            ),
            "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
        )
        if spec["schema_version"] != "goal-teams-environment-document-v2.45":
            raise ReleaseError(
                "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
                f"environment document schema is invalid: {name}",
            )
        parse_time(spec["created_at"], f"environment_documents.documents.{name}.created_at")
        if (
            not isinstance(spec["architecture_baseline_commit"], str)
            or COMMIT_SHA.fullmatch(spec["architecture_baseline_commit"]) is None
        ):
            raise ReleaseError(
                "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
                f"environment architecture baseline is invalid: {name}",
            )
        issuer = spec["issuer"]
        if (
            not isinstance(issuer, dict)
            or not isinstance(issuer.get("role"), str)
            or not issuer["role"]
            or not isinstance(issuer.get("run_id"), str)
            or not issuer["run_id"]
        ):
            raise ReleaseError(
                "E_V245_RE_ENVIRONMENT_DOCUMENT_REQUIRED",
                f"environment document issuer is invalid: {name}",
            )
        path = resolve_project_file(spec.get("path"), project, f"environment_documents.documents.{name}.path")
        expected = require_sha256(spec.get("sha256"), f"environment_documents.documents.{name}.sha256")
        if file_digest(path) != expected:
            raise ReleaseError("E_V245_RE_ENVIRONMENT_BINDING_INVALID", f"environment document digest drift: {name}")
        observed[name] = {
            "schema_version": spec["schema_version"],
            "path": str(path),
            "sha256": expected,
            "created_at": spec["created_at"],
            "architecture_baseline_commit": spec["architecture_baseline_commit"],
            "issuer": issuer,
        }
    if object_digest(observed) != environment.get("set_digest"):
        raise ReleaseError("E_V245_RE_ENVIRONMENT_BINDING_INVALID", "environment document set digest drift")
    target = environment.get("target_name")
    if (
        target not in observed
        or observed[target]["path"] != environment.get("target_document_path")
        or observed[target]["sha256"] != environment.get("target_document_digest")
    ):
        raise ReleaseError("E_V245_RE_ENVIRONMENT_BINDING_INVALID", "target environment document binding drift")


def validate_surface_readback(
    plan: dict[str, Any],
    gate_receipt: dict[str, Any],
    *,
    operation: str,
) -> None:
    payload = load_json(Path(gate_receipt["path"]))
    readback = payload.get("surface_readback")
    state = payload.get("surface_state")
    if not isinstance(readback, dict) or not isinstance(state, str):
        raise ReleaseError("E_V245_RE_PLATFORM_READBACK_PENDING", "surface-specific readback is required")
    required = plan["surface_recipe"].get("required_readback", [])
    missing = [field for field in required if readback.get(field) in (None, "")]
    if missing:
        raise ReleaseError("E_V245_RE_PLATFORM_READBACK_PENDING", f"surface readback missing: {', '.join(missing)}")
    terminal_state = {
        "application": "verified",
        "container-kubernetes": "business_verified",
        "wechat-miniprogram": "online_version_readback",
        "github-skill": "installed_identity_verified",
    }[plan["surface_kit"]["name"]]
    if state != terminal_state:
        raise ReleaseError("E_V245_RE_PLATFORM_READBACK_PENDING", f"surface state is not ready: {state}")
    surface = plan["surface_kit"]["name"]
    expected_identity = (
        plan["surface_identity"]
        if operation == "release"
        else plan.get("rollback_identity")
    )
    if not isinstance(expected_identity, dict):
        raise ReleaseError(
            "E_V245_RE_ROLLBACK_TARGET_REQUIRED",
            "rollback requires an exact, plan-bound rollback identity",
        )
    expected_artifact = (
        plan["candidate"]["artifact_digest"]
        if operation == "release"
        else expected_identity.get("artifact_digest")
    )
    if surface == "application" and readback.get("artifact_digest") != expected_artifact:
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", "application artifact readback digest mismatch")
    if surface == "application" and readback.get("configuration_identity") != expected_identity["configuration_identity"]:
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", "application configuration identity mismatch")
    if surface == "application" and (
        readback.get("external_health") != "passed"
        or readback.get("business_invariants") != "passed"
    ):
        raise ReleaseError(
            "E_V245_RE_PLATFORM_READBACK_PENDING",
            "application health and business invariants must both pass",
        )
    expected_oci = (
        plan["candidate"]["artifact_digest"]
        if operation == "release"
        else expected_identity.get("oci_index_digest")
    )
    if surface == "container-kubernetes" and readback.get("oci_index_digest") != expected_oci:
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", "OCI index readback digest mismatch")
    if surface == "container-kubernetes" and (
        readback.get("namespace") != expected_identity["namespace"]
        or readback.get("workload") != expected_identity["workload"]
    ):
        raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", "Kubernetes target identity mismatch")
    if surface == "wechat-miniprogram" and (
        readback.get("review_status") != "passed"
        or readback.get("appid") != expected_identity["appid"]
        or readback.get("online_version") != expected_identity["code_version"]
    ):
        raise ReleaseError("E_V245_RE_PLATFORM_READBACK_PENDING", "WeChat online identity is not verified")
    if surface == "github-skill":
        expected_commit = (
            plan["candidate"]["source_commit"]
            if operation == "release"
            else expected_identity.get("tag_commit")
        )
        expected_asset = (
            plan["candidate"]["artifact_digest"]
            if operation == "release"
            else expected_identity.get("asset_digest")
        )
        if (
            readback.get("repository") != expected_identity["repository"]
            or readback.get("tag") != expected_identity["tag"]
            or readback.get("tag_commit") != expected_commit
            or readback.get("asset_digest") != expected_asset
            or readback.get("download_digest") != expected_asset
            or readback.get("installed_tree_digest")
            != expected_identity["expected_installed_tree_digest"]
        ):
            raise ReleaseError("E_V245_RE_GATE_BINDING_INVALID", "GitHub release asset readback digest mismatch")


def acquire_lock(path: Path, execution_id: str) -> int:
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ReleaseError("E_V245_RE_CONCURRENT_EXECUTION", "another execution is active", path=str(path)) from exc


def build_scrubbed_execution_env(
    plan: dict[str, Any],
    *,
    execution_id: str,
    mode: str,
    operation: str,
) -> dict[str, str]:
    execution_home = Path(plan["run_root"]) / "execution-home" / execution_id
    execution_home.mkdir(parents=True, exist_ok=False, mode=0o700)
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(execution_home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GOAL_TEAMS_RELEASE_EXECUTION_ID": execution_id,
        "GOAL_TEAMS_RELEASE_MODE": mode,
        "GOAL_TEAMS_RELEASE_OPERATION": operation,
        "GOAL_TEAMS_RELEASE_TARGET_ENVIRONMENT": plan["environment_kit"]["name"],
        "GOAL_TEAMS_RELEASE_SURFACE": plan["surface_kit"]["name"],
    }


def validate_toolchain_action_receipt(
    plan: dict[str, Any],
    *,
    execution_id: str,
    phase: str,
    expected_dependency_bundle_digest: str | None = None,
) -> dict[str, Any]:
    if phase not in {"prefetch", "build"}:
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt phase is invalid",
        )
    toolchain = plan.get("toolchain_host_command")
    if not isinstance(toolchain, dict):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt has no approved host binding",
        )
    action_id = toolchain[f"{phase}_action"]
    project = Path(plan["project_root"])
    expected_path = (
        Path(plan["run_root"]) / "toolchain-receipts" / f"{action_id}.json"
    )
    path = resolve_project_file(
        str(expected_path),
        project,
        f"toolchain_receipts.{phase}",
    )
    if path != expected_path or path.is_symlink():
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt path drifted",
            path=str(path),
        )
    payload = load_json(path)
    expected_fields = set(
        TOOLCHAIN_PREFETCH_RECEIPT_FIELDS
        if phase == "prefetch"
        else TOOLCHAIN_BUILD_RECEIPT_FIELDS
    )
    if set(payload) != expected_fields:
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt fields are not closed",
            path=str(path),
        )
    action_manifest_path = catalog_path(
        load_catalog()["toolchain_host_command"]["action_manifest"]
    )
    expected_manifest_digest = file_digest(action_manifest_path)
    expected_network = (
        "prefetch_only" if phase == "prefetch" else "offline_required"
    )
    dependency_digest = require_sha256(
        payload.get("dependency_bundle_digest"),
        f"toolchain_receipts.{phase}.dependency_bundle_digest",
    )
    if (
        payload.get("schema_version")
        != "goal-teams-toolchain-action-receipt-v2.45"
        or payload.get("action_id") != action_id
        or payload.get("status") != "passed"
        or payload.get("execution_id") != execution_id
        or payload.get("plan_digest") != plan["plan_digest"]
        or payload.get("host_executable_sha256") != toolchain["sha256"]
        or payload.get("action_manifest_sha256") != expected_manifest_digest
        or payload.get("network_policy") != expected_network
        or payload.get("full_test_execution_count") != 0
        or (
            expected_dependency_bundle_digest is not None
            and dependency_digest != expected_dependency_bundle_digest
        )
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt binding, offline policy, or test count drifted",
            path=str(path),
        )
    observed_at = parse_time(
        payload.get("observed_at"),
        f"toolchain_receipts.{phase}.observed_at",
    )
    current_time = dt.datetime.now(dt.timezone.utc)
    if (
        observed_at > current_time + dt.timedelta(minutes=5)
        or observed_at < current_time - dt.timedelta(minutes=15)
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt is not current",
            path=str(path),
        )
    if phase == "build":
        artifact_digest = require_sha256(
            payload.get("artifact_digest"),
            "toolchain_receipts.build.artifact_digest",
        )
        artifact_path = Path(plan["artifact_path"])
        if (
            artifact_digest != plan["candidate"]["artifact_digest"]
            or file_digest(artifact_path) != artifact_digest
        ):
            raise ReleaseError(
                "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
                "toolchain build receipt artifact digest drifted",
                path=str(path),
            )
    attestation = payload.get("host_attestation")
    required_attestation = {
        "schema_version",
        "algorithm",
        "issuer",
        "key_id",
        "bindings_sha256",
        "issued_at",
        "challenge_id",
        "signature",
    }
    receipt_bindings = dict(payload)
    receipt_bindings.pop("host_attestation", None)
    if (
        not isinstance(attestation, dict)
        or set(attestation) != required_attestation
        or attestation.get("schema_version")
        != "goal-teams-toolchain-action-receipt-attestation-v2.45"
        or attestation.get("algorithm") != "Ed25519"
        or attestation.get("issuer") != "goal-teams-trusted-host"
        or attestation.get("key_id") != TRUSTED_APPROVAL_KEY_ID
        or attestation.get("bindings_sha256") != object_digest(receipt_bindings)
        or not isinstance(attestation.get("challenge_id"), str)
        or not attestation["challenge_id"]
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt requires an exact trusted-host attestation",
            path=str(path),
        )
    issued_at = parse_time(
        attestation.get("issued_at"),
        f"toolchain_receipts.{phase}.host_attestation.issued_at",
    )
    if (
        issued_at > current_time + dt.timedelta(minutes=5)
        or issued_at < current_time - dt.timedelta(minutes=15)
    ):
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt attestation is not current",
            path=str(path),
        )
    unsigned = dict(attestation)
    signature_hex = unsigned.pop("signature", None)
    domain = (
        "goal-teams/release-engineer/v2.45/toolchain-action-receipt/"
        "host-attestation/ed25519/v1"
    ).encode("utf-8")
    try:
        receipt_attestation_ok = ED25519_VERIFY.verify(
            bytes.fromhex(TRUSTED_APPROVAL_PUBLIC_KEY_HEX),
            domain + b"\x00" + canonical_bytes(unsigned),
            bytes.fromhex(str(signature_hex)),
        )
    except (TypeError, ValueError):
        receipt_attestation_ok = False
    if not receipt_attestation_ok:
        raise ReleaseError(
            "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
            "toolchain receipt trusted-host signature is invalid",
            path=str(path),
        )
    return {
        "phase": phase,
        "path": str(path),
        "sha256": file_digest(path),
        "action_id": action_id,
        "dependency_bundle_digest": dependency_digest,
        "artifact_digest": payload.get("artifact_digest"),
        "network_policy": expected_network,
        "full_test_execution_count": 0,
    }


def execute_bundle(request: dict[str, Any]) -> dict[str, Any]:
    require_fields(request, ("bundle_root", "plan_path", "execution_approval_path"))
    bundle_input = Path(str(request["bundle_root"]))
    bundle_root = bundle_input.resolve(strict=True)
    validation = validate_bundle_root(bundle_root)
    manifest = load_json(bundle_root / "script-bundle-manifest.json")
    plan = load_json(Path(str(request["plan_path"])).resolve(strict=False))
    verify_plan_digest(plan)
    project, release_root = resolve_project_and_release_root(plan["project_root"], plan["release_root"])
    validate_execution_interpreter(plan.get("execution_interpreter"))
    if plan["environment_recipe"].get("build_allowed"):
        if (
            validate_toolchain_host_command(
                plan.get("toolchain_host_command"),
                project,
                plan["language_kit"],
            )
            != plan["toolchain_host_command"]
        ):
            raise ReleaseError(
                "E_V245_RE_TOOLCHAIN_HOST_DIGEST_DRIFT",
                "toolchain host no longer matches the approved plan",
            )
    elif plan.get("toolchain_host_command") is not None:
        raise ReleaseError(
            "E_V245_RE_PERMISSION_EXCESS",
            "toolchain host command is forbidden for this environment",
        )
    ensure_no_symlink_chain(bundle_input, project)
    expected_scripts_root = Path(plan["run_root"]).resolve(strict=True) / "scripts"
    if not is_within(bundle_root, expected_scripts_root) or not is_within(bundle_root, release_root):
        raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "script bundle must be inside the approved release run")
    ensure_no_symlink_chain(bundle_root, project)
    approval = load_json(Path(str(request["execution_approval_path"])).resolve(strict=False))
    plan_approval_path = resolve_project_file(
        manifest.get("plan_approval_path"),
        project,
        "script_bundle.plan_approval_path",
    )
    if file_digest(plan_approval_path) != require_sha256(
        manifest.get("plan_approval_digest"),
        "script_bundle.plan_approval_digest",
    ):
        raise ReleaseError("E_V245_RE_PLAN_APPROVAL_STALE", "plan approval digest drift")
    plan_approval = load_json(plan_approval_path)
    validate_plan_approval(plan_approval, plan)
    if plan_approval.get("approval_id") != manifest.get("plan_approval_id"):
        raise ReleaseError("E_V245_RE_PLAN_APPROVAL_STALE", "script bundle plan approval id drift")
    mode = request.get("mode", "dry-run")
    operation = request.get("operation", "release")
    if mode not in {"dry-run", "live"} or operation not in {"release", "rollback"}:
        raise ReleaseError("E_V245_RE_INPUT_INVALID", "mode or operation is invalid")
    validate_execution_approval(
        approval,
        manifest,
        plan,
        mode=mode,
        operation=operation,
    )
    manifest_bindings = {
        "plan_digest": plan["plan_digest"],
        "candidate_artifact_digest": plan["candidate"]["artifact_digest"],
        "environment_document_digest": plan["environment_documents"]["target_document_digest"],
        "target_environment": plan["environment_kit"]["name"],
        "release_surface": plan["surface_kit"]["name"],
        "surface_identity_digest": plan["surface_identity_digest"],
        "rollback_identity_digest": plan["rollback_identity_digest"],
        "language_kit_id": plan["language_kit"]["id"],
        "toolchain_host_command_digest": (
            object_digest(plan["toolchain_host_command"])
            if plan.get("toolchain_host_command")
            else None
        ),
    }
    for field, value in manifest_bindings.items():
        if manifest.get(field) != value:
            raise ReleaseError("E_V245_RE_SCRIPT_DIGEST_DRIFT", f"script bundle plan binding drift: {field}")
    for adapter_name, frozen_spec in plan["adapters"].items():
        if validate_adapter_spec(frozen_spec, project, adapter_name) != frozen_spec:
            raise ReleaseError(
                "E_V245_RE_ADAPTER_DIGEST_DRIFT",
                f"adapter {adapter_name} no longer matches the approved plan",
            )
    validate_environment_document_binding(plan)
    restore_proof = validate_restore_proof(plan)
    if operation == "rollback" and "rollback_execute" not in approval["requested_capabilities"]:
        raise ReleaseError("E_V245_RE_ROLLBACK_AUTHORIZATION_REQUIRED", "rollback capability is not approved")

    receipts_root = Path(plan["run_root"]) / "receipts" / str(approval["execution_id"])
    if receipts_root.exists():
        raise ReleaseError(
            "E_V245_RE_EXEC_APPROVAL_REPLAY",
            "execution_id has already been consumed",
            path=str(receipts_root),
        )
    lock_path = Path(plan["run_root"]) / ".execution.lock"
    lock_fd = acquire_lock(lock_path, str(approval["execution_id"]))
    try:
        os.write(lock_fd, str(approval["execution_id"]).encode("utf-8"))
        os.close(lock_fd)
        intent = {
            "schema_version": "goal-teams-release-execution-intent-v2.45",
            "execution_id": approval["execution_id"],
            "approval_id": approval["approval_id"],
            "plan_digest": plan["plan_digest"],
            "script_bundle_digest": manifest["script_bundle_digest"],
            "mode": mode,
            "operation": operation,
            "created_at": now_utc(),
        }
        write_json(receipts_root / "intent.json", intent)
        execution_env = build_scrubbed_execution_env(
            plan,
            execution_id=str(approval["execution_id"]),
            mode=mode,
            operation=operation,
        )

        normal_steps = [step for step in manifest["steps"] if step["filename"] != "90-rollback.sh"]
        if operation == "rollback":
            by_name = {step["filename"]: step for step in manifest["steps"]}
            selected_steps = [by_name["90-rollback.sh"], by_name["80-post-release-verify.sh"]]
        else:
            selected_steps = normal_steps
        if mode == "dry-run":
            result = {
                "schema_version": "goal-teams-release-execution-result-v2.45",
                "execution_id": approval["execution_id"],
                "mode": mode,
                "operation": operation,
                "execution_state": "dry_run_validated",
                "external_write_count": 0,
                "would_execute": [step["filename"] for step in selected_steps],
                "validation": validation,
                "completed_at": now_utc(),
            }
            write_json(receipts_root / "result.json", result)
            return {"passed": True, "result_path": str(receipts_root / "result.json"), "result": result}

        max_attempts = int(plan.get("max_auto_loop_attempts", 3))
        receipts: list[dict[str, Any]] = []
        gate_receipts: list[dict[str, Any]] = []
        verified_toolchain_receipts: list[dict[str, Any]] = []
        external_write_count = 0
        for step in selected_steps:
            if step["capability"] not in approval["requested_capabilities"]:
                raise ReleaseError("E_V245_RE_EXEC_APPROVAL_STALE", f"step capability is not approved: {step['capability']}")
            path = bundle_root / step["filename"]
            attempts = max_attempts if step["idempotent"] and not step["external_write"] else 1
            final_receipt: dict[str, Any] | None = None
            for attempt in range(1, attempts + 1):
                completed = subprocess.run(
                    [plan["execution_interpreter"]["path"], str(path)],
                    cwd=plan["project_root"],
                    env=execution_env,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=int(request.get("step_timeout_seconds", 900)),
                )
                if step["external_write"]:
                    external_write_count += 1
                final_receipt = step_receipt(
                    step=step,
                    attempt=attempt,
                    status="passed" if completed.returncode == 0 else "failed",
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
                receipts.append(final_receipt)
                write_json(receipts_root / f"{step['filename']}.attempt-{attempt}.json", final_receipt)
                if completed.returncode == 0:
                    break
            if final_receipt is None or final_receipt["status"] != "passed":
                loop_state = {
                    "schema_version": "goal-teams-release-loop-state-v2.45",
                    "execution_id": approval["execution_id"],
                    "failed_step": step["filename"],
                    "attempts": attempts,
                    "loop_decision": "stop",
                    "run_outcome": "blocked",
                    "stop_reason": "authorization_required" if step["external_write"] else "max_attempts",
                    "updated_at": now_utc(),
                }
                write_json(Path(plan["run_root"]) / "loop" / "loop-state.json", loop_state)
                raise ReleaseError(
                    "E_V245_RE_LOOP_AUTHORIZATION_REQUIRED" if step["external_write"] else "E_V245_RE_LOOP_MAX_ATTEMPTS",
                    f"step failed after {attempts} attempt(s)",
                    path=str(path),
                )
            if step["filename"] == "20-prefetch-dependencies.sh":
                verified_toolchain_receipts.append(
                    validate_toolchain_action_receipt(
                        plan,
                        execution_id=str(approval["execution_id"]),
                        phase="prefetch",
                    )
                )
            elif step["filename"] == "40-build.sh":
                prefetch_receipt = next(
                    (
                        item
                        for item in verified_toolchain_receipts
                        if item["phase"] == "prefetch"
                    ),
                    None,
                )
                if prefetch_receipt is None:
                    raise ReleaseError(
                        "E_V245_RE_TOOLCHAIN_RECEIPT_INVALID",
                        "build requires the verified prefetch dependency digest",
                    )
                verified_toolchain_receipts.append(
                    validate_toolchain_action_receipt(
                        plan,
                        execution_id=str(approval["execution_id"]),
                        phase="build",
                        expected_dependency_bundle_digest=prefetch_receipt[
                            "dependency_bundle_digest"
                        ],
                    )
                )
            if step["filename"] == "50-backup.sh" and plan["environment_kit"].get("backup_required"):
                backup_gate = validate_gate_receipt(
                    plan,
                    "backup_receipt",
                    execution_id=str(approval["execution_id"]),
                    operation=operation,
                    intent_created_at=intent["created_at"],
                )
                if restore_proof is not None and backup_gate.get("backup_scope_digest") != restore_proof["backup_scope_digest"]:
                    raise ReleaseError("E_V245_RE_BACKUP_RESTORE_UNVERIFIED", "backup scope is not covered by restore proof")
                gate_receipts.append(backup_gate)
            elif step["filename"] == "60-benchmark-baseline.sh":
                gate_receipts.append(
                    validate_gate_receipt(
                        plan,
                        "benchmark_baseline",
                        execution_id=str(approval["execution_id"]),
                        operation=operation,
                        intent_created_at=intent["created_at"],
                    )
                )
            elif step["filename"] == "80-post-release-verify.sh":
                post_gate = validate_gate_receipt(
                    plan,
                    "post_release_verification",
                    execution_id=str(approval["execution_id"]),
                    operation=operation,
                    intent_created_at=intent["created_at"],
                )
                validate_surface_readback(plan, post_gate, operation=operation)
                gate_receipts.append(post_gate)

        result = {
            "schema_version": "goal-teams-release-execution-result-v2.45",
            "execution_id": approval["execution_id"],
            "mode": mode,
            "operation": operation,
            "execution_state": "completed",
            "observation_state": "pending_independent_validation",
            "independent_validation_state": "pending",
            "external_write_count": external_write_count,
            "receipts": receipts,
            "gate_receipts": gate_receipts,
            "toolchain_action_receipts": verified_toolchain_receipts,
            "completed_at": now_utc(),
        }
        write_json(receipts_root / "result.json", result)
        return {"passed": True, "result_path": str(receipts_root / "result.json"), "result": result}
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def status(request: dict[str, Any]) -> dict[str, Any]:
    require_fields(request, ("project_root", "release_root", "release_run_id"))
    _, release_root = resolve_project_and_release_root(request["project_root"], request["release_root"])
    run_id = require_safe_id(request["release_run_id"], "release_run_id")
    run_root = release_root / "runs" / run_id
    if not run_root.is_dir():
        raise ReleaseError("E_V245_RE_RUN_NOT_FOUND", "release run does not exist", path=str(run_root))
    result: dict[str, Any] = {
        "passed": True,
        "run_root": str(run_root),
        "plan": None,
        "script_bundles": [],
        "loop_state": None,
        "execution_results": [],
    }
    plan_path = run_root / "plan" / "release-plan.json"
    if plan_path.is_file():
        plan = load_json(plan_path)
        result["plan"] = {"path": str(plan_path), "digest": plan.get("plan_digest"), "state": plan.get("plan_state")}
    scripts_root = run_root / "scripts"
    if scripts_root.is_dir():
        for manifest_path in sorted(scripts_root.glob("*/script-bundle-manifest.json")):
            manifest = load_json(manifest_path)
            result["script_bundles"].append(
                {
                    "path": str(manifest_path.parent),
                    "version": manifest.get("script_bundle_version"),
                    "digest": manifest.get("script_bundle_digest"),
                }
            )
    loop_path = run_root / "loop" / "loop-state.json"
    if loop_path.is_file():
        result["loop_state"] = load_json(loop_path)
    receipts_root = run_root / "receipts"
    if receipts_root.is_dir():
        for result_path in sorted(receipts_root.glob("*/result.json")):
            result["execution_results"].append({"path": str(result_path), "result": load_json(result_path)})
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    for command in ("check-evidence", "discover-scripts", "plan", "compose", "execute", "status"):
        child = subparsers.add_parser(command)
        child.add_argument("--input", type=Path, required=True)
        if command == "check-evidence":
            child.add_argument("--output", type=Path)
    validate = subparsers.add_parser("validate-bundle")
    validate.add_argument("--bundle-root", type=Path, required=True)
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "validate-bundle":
        return validate_bundle_root(args.bundle_root)
    request = load_json(args.input)
    if args.command == "check-evidence":
        report = check_evidence(request)
        if args.output is not None:
            project = Path(str(request["project_root"])).resolve(strict=True)
            output = args.output.resolve(strict=False)
            if not is_within(output, project):
                raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "evidence report output must be inside project root")
            if "release" not in {part.lower() for part in output.relative_to(project).parts}:
                raise ReleaseError("E_V245_RE_RELEASE_ROOT_ESCAPE", "evidence report output must be inside a release directory")
            if output.exists():
                raise ReleaseError("E_V245_RE_RUN_ALREADY_EXISTS", "evidence report output must not overwrite an existing file", path=str(output))
            ensure_no_symlink_chain(output, project)
            write_json(output, report)
        return {"passed": report["evidence_status"] == "ready", "report": report, "output": str(args.output) if args.output else None}
    if args.command == "discover-scripts":
        return {"passed": True, "report": discover_scripts(request)}
    if args.command == "plan":
        return plan_release(request)
    if args.command == "compose":
        return compose_bundle(request)
    if args.command == "execute":
        return execute_bundle(request)
    if args.command == "status":
        return status(request)
    raise ReleaseError("E_V245_RE_INPUT_INVALID", "unknown command")


def main() -> int:
    try:
        result = run(parser().parse_args())
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("passed", False) else 1
    except ReleaseError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False, sort_keys=True))
        return 2
    except subprocess.TimeoutExpired as exc:
        error = ReleaseError("E_V245_RE_STEP_TIMEOUT", "release step timed out", path=str(exc.cmd))
        print(json.dumps(error.payload(), ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:  # pragma: no cover - fail-closed runtime boundary
        error = ReleaseError("E_V245_RE_RUNTIME", type(exc).__name__)
        print(json.dumps(error.payload(), ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
