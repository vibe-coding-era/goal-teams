#!/usr/bin/env python3
"""Audit the exact V2.62 released implementation in a fresh process.

This is an S1 release-security review, not an S2 security check.  It binds a
declared implementation denominator to one clean Git commit/tree, compares
every reviewed blob with the filesystem, and performs deterministic negative
scans over the actual release, installer, runtime, SSH, workflow, and command
execution surfaces.  The strongest honest actor assurance remains I1 with a
correlated relationship; process separation is not external independence.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    "references/current/generations/V2.62/contracts/"
    "release-security-review-manifest.json"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_MODE_RE = re.compile(r"^(100644|100755)$")

EXPECTED_ASSERTION_IDS = (
    "V250-SEC-EXACT-GIT-IDENTITY",
    "V250-SEC-DENOMINATOR-COMPLETE",
    "V250-SEC-GIT-OBJECT-FILESYSTEM",
    "V250-SEC-PATH-SYMLINK-MODE",
    "V250-SEC-DEPENDENCY-SURFACE",
    "V250-SEC-SECRET-NEGATIVE-SCAN",
    "V250-SEC-DANGEROUS-OPERATION-ALLOWLIST",
    "V250-SEC-COMMAND-EXECUTION-BOUNDARIES",
    "V250-SEC-GITHUB-GIT-SSH-ONLY",
    "V250-SEC-WORKFLOW-ACTION-PINS",
    "V250-SEC-S2-SECURITY-SEPARATION",
    "V250-SEC-FRESH-CORRELATED-PROCESS",
)

REQUIRED_CATEGORIES = frozenset(
    {
        "boundary",
        "command_execution",
        "contract",
        "dependency",
        "git_ssh",
        "installer",
        "packaging",
        "release_checker",
        "release_flow",
        "runtime",
        "s4",
        "security_review_runner",
        "workflow",
    }
)

# This code-side floor prevents a contract-only edit from silently shrinking
# the real review denominator.  Adding a new security surface requires both a
# code and contract change, while a missing/unknown target fails closed.
MANDATORY_REVIEW_TARGETS = frozenset(
    {
        ".github/workflows/check.yml",
        ".github/workflows/release-gate.yml",
        "references/current/generations/V2.62/contracts/public-asset-map.json",
        "references/current/generations/V2.62/contracts/release-command-manifest.json",
        "references/current/generations/V2.62/contracts/release-route-manifest.json",
        CONTRACT_PATH,
        "references/current/generations/V2.62/functions/knowledge-graph.md",
        "schemas/v2.50/okf-document-graph.schema.json",
        "schemas/v2.50/project-route.schema.json",
        "schemas/v2.50/release-control.schema.json",
        "scripts/checks/check-package-manifest.py",
        "scripts/checks/check.sh",
        "scripts/checks/check-v250.py",
        "scripts/checks/check-version-sync.py",
        "scripts/checks/check-workspace-boundaries.py",
        "scripts/checks/run-v250-release-security-review.py",
        "scripts/checks/validate-v250-generation.py",
        "scripts/checks/validate-v250-test-gate.py",
        "scripts/checks/validate.py",
        "scripts/install/install-local.sh",
        "scripts/release/build-release.py",
        "scripts/release/release_config.py",
        "scripts/release/skill_release.py",
        "scripts/release/validate-release.py",
        "scripts/v250/github_ssh.py",
        "scripts/v250/generate_subagents.py",
        "scripts/v250/generate_unicode17_nfc.py",
        "scripts/v250/generation_runtime.py",
        "scripts/v250/loop_bootstrap.py",
        "scripts/v250/okf_conformance.py",
        "scripts/v250/okf_document_graph.py",
        "scripts/v250/output_contract.py",
        "scripts/v250/refresh_generation_manifests.py",
        "scripts/v250/release_flow.py",
        "scripts/v250/repository_boundary.py",
        "scripts/v250/route_closure.py",
        "scripts/v250/runtime_host_adapter.py",
        "scripts/v250/runtime_transition.py",
        "scripts/v250/s4_executor.py",
        "scripts/v250/test_gate.py",
        "scripts/v250/unicode17_data.py",
        "scripts/v250/unicode17_nfc.py",
        "scripts/v262/compatibility.py",
        "scripts/v262/project_host_assets.py",
        "scripts/v262/role_projections.py",
    }
)

DEPENDENCY_BASENAME_PATTERNS = (
    "Pipfile",
    "Pipfile.lock",
    "bun.lock",
    "bun.lockb",
    "constraints*.txt",
    "deno.json",
    "deno.jsonc",
    "environment.yml",
    "environment.yaml",
    "jsr.json",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "package.json",
    "pdm.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements*.in",
    "requirements*.txt",
    "setup.cfg",
    "setup.py",
    "tox.ini",
    "uv.lock",
    "yarn.lock",
)

# Each occurrence becomes a stable callsite fingerprint.  Exact observed
# fingerprints must match the contract allowlist, so a new destructive,
# clobbering, file-writing, archive-extraction, or child-process call fails even
# when the contract and tests are otherwise unchanged.
DANGEROUS_OPERATION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("os_system", re.compile(r"\bos\.system\s*\(")),
    ("os_remove", re.compile(r"\bos\.(?:remove|unlink)\s*\(")),
    ("os_replace", re.compile(r"\bos\.replace\s*\(")),
    ("shutil_destructive", re.compile(r"\bshutil\.(?:rmtree|move|copytree)\s*\(")),
    ("path_destructive", re.compile(r"\.(?:unlink|rmdir|rename|replace)\s*\(")),
    ("mode_change", re.compile(r"\.(?:chmod|chown)\s*\(")),
    ("file_write", re.compile(r"\.write_(?:text|bytes)\s*\(")),
    ("archive_extract", re.compile(r"\.(?:extract|extractall)\s*\(")),
)

SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key_pem",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("github_classic_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    (
        "github_fine_grained_token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    (
        "authorization_literal",
        re.compile(r"(?i)\b(?:authorization\s*[:=]\s*)?(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{16,}"),
    ),
    (
        "credential_uri",
        re.compile(r"(?i)\b(?:https?|postgres(?:ql)?|mysql|redis)://[^/@:\s]+:[^/@\s]+@"),
    ),
    (
        "high_entropy_credential_assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)"
            r"\s*[:=]\s*['\"]([^'\"$\s]{16,})['\"]"
        ),
    ),
)


class SecurityReviewError(ValueError):
    """Stable fail-closed review error."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("receipt_sha256", None)
    return _sha256(_canonical_bytes(payload))


def _git(
    root: Path, *args: str, text: bool = False
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=text,
        env={
            **os.environ,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )


def _git_text(root: Path, *args: str) -> str:
    result = _git(root, *args, text=True)
    if result.returncode != 0:
        raise SecurityReviewError("E_V250_SECURITY_GIT_IDENTITY")
    return str(result.stdout).strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    result = _git(root, *args, text=False)
    if result.returncode != 0:
        raise SecurityReviewError("E_V250_SECURITY_GIT_OBJECT")
    return bytes(result.stdout)


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_PATH")
    pure = PurePosixPath(value)
    if pure.is_absolute() or str(pure) != value or any(part in {"", ".", ".."} for part in pure.parts):
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_PATH")
    return value


def _ls_tree(root: Path, source_commit: str) -> dict[str, dict[str, str]]:
    raw = _git_bytes(root, "ls-tree", "-r", "-z", "--full-tree", source_commit)
    entries: dict[str, dict[str, str]] = {}
    for record in raw.split(b"\x00"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ", 2)
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SecurityReviewError("E_V250_SECURITY_GIT_TREE") from exc
        if path in entries:
            raise SecurityReviewError("E_V250_SECURITY_GIT_TREE")
        entries[path] = {"mode": mode, "type": kind, "object_id": object_id}
    if not entries:
        raise SecurityReviewError("E_V250_SECURITY_GIT_TREE")
    return entries


def _verify_exact_identity(
    root: Path, source_commit: str, source_tree: str
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    if COMMIT_RE.fullmatch(source_commit) is None or COMMIT_RE.fullmatch(source_tree) is None:
        raise SecurityReviewError("E_V250_SECURITY_IDENTITY")
    observed_root = Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve()
    if observed_root != root.resolve():
        raise SecurityReviewError("E_V250_SECURITY_WORKTREE_ROOT")
    head_commit = _git_text(root, "rev-parse", "HEAD^{commit}")
    head_tree = _git_text(root, "rev-parse", f"{source_commit}^{{tree}}")
    if head_commit != source_commit:
        raise SecurityReviewError("E_V250_SECURITY_COMMIT_DRIFT")
    if head_tree != source_tree:
        raise SecurityReviewError("E_V250_SECURITY_TREE_DRIFT")
    status = _git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    diff = _git(root, "diff", "--quiet", source_commit, "--")
    cached = _git(root, "diff", "--cached", "--quiet", source_commit, "--")
    if status or diff.returncode != 0 or cached.returncode != 0:
        raise SecurityReviewError("E_V250_SECURITY_WORKTREE_DIRTY")
    tree_entries = _ls_tree(root, source_commit)
    return (
        {
            "binding_kind": "exact_clean_git_object_and_filesystem",
            "repository_root": ".",
            "head_commit": head_commit,
            "head_tree": head_tree,
            "status_porcelain_sha256": _sha256(status),
            "dirty_entry_count": 0,
            "untracked_entry_count": 0,
            "worktree_diff_returncode": diff.returncode,
            "index_diff_returncode": cached.returncode,
            "git_replace_objects_disabled": True,
            "lazy_fetch_disabled": True,
        },
        tree_entries,
    )


def _frozen_file(
    root: Path,
    source_commit: str,
    tree_entries: Mapping[str, Mapping[str, str]],
    path: str,
) -> tuple[bytes, dict[str, str]]:
    safe = _safe_path(path)
    entry = tree_entries.get(safe)
    if not isinstance(entry, Mapping):
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_MISSING")
    if entry.get("type") != "blob" or GIT_MODE_RE.fullmatch(str(entry.get("mode", ""))) is None:
        raise SecurityReviewError("E_V250_SECURITY_TARGET_TYPE")
    frozen = _git_bytes(root, "show", f"{source_commit}:{safe}")
    filesystem = root / safe
    try:
        metadata = filesystem.lstat()
    except OSError as exc:
        raise SecurityReviewError("E_V250_SECURITY_TARGET_MISSING") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SecurityReviewError("E_V250_SECURITY_TARGET_SYMLINK")
    try:
        filesystem.resolve().relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise SecurityReviewError("E_V250_SECURITY_TARGET_ESCAPE") from exc
    current = filesystem.read_bytes()
    if current != frozen:
        raise SecurityReviewError("E_V250_SECURITY_TARGET_CONTENT_DRIFT")
    return frozen, dict(entry)


def _load_manifest(
    root: Path,
    source_commit: str,
    tree_entries: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, Any], str]:
    frozen, _ = _frozen_file(root, source_commit, tree_entries, CONTRACT_PATH)
    try:
        value = json.loads(frozen.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_CONTRACT") from exc
    if not isinstance(value, dict):
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_CONTRACT")
    return value, _sha256(frozen)


def _validate_manifest(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != "goal-teams-v2.62-release-security-review-v2":
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_SCHEMA")
    if manifest.get("denominator_id") != "V250-RELEASE-SECURITY-IMPLEMENTATION":
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_ID")
    if manifest.get("unknown_or_missing_policy") != "fail_closed":
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_POLICY")
    if tuple(manifest.get("assertion_denominator", [])) != EXPECTED_ASSERTION_IDS:
        raise SecurityReviewError("E_V250_SECURITY_ASSERTION_DENOMINATOR")
    targets = manifest.get("review_targets")
    if not isinstance(targets, list) or not targets:
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_EMPTY")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    observed_categories: set[str] = set()
    allowed_kinds = {
        "json",
        "markdown",
        "python",
        "python_heredoc",
        "shell",
        "yaml",
    }
    for target in targets:
        if not isinstance(target, dict) or set(target) != {"path", "content_kind", "categories"}:
            raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_TARGET")
        path = _safe_path(target.get("path"))
        kind = target.get("content_kind")
        categories = target.get("categories")
        if path in seen or kind not in allowed_kinds or not isinstance(categories, list) or not categories:
            raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_TARGET")
        if categories != sorted(set(categories)) or not set(categories) <= REQUIRED_CATEGORIES:
            raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_CATEGORY")
        seen.add(path)
        observed_categories.update(categories)
        normalized.append({"path": path, "content_kind": kind, "categories": categories})
    if seen != MANDATORY_REVIEW_TARGETS or observed_categories != REQUIRED_CATEGORIES:
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_INCOMPLETE")
    if manifest.get("required_categories") != sorted(REQUIRED_CATEGORIES):
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_CATEGORY")
    declared = manifest.get("declared_dependency_files")
    allowed_imports = manifest.get("allowed_external_python_imports")
    if not isinstance(declared, list) or declared != sorted(set(declared)):
        raise SecurityReviewError("E_V250_SECURITY_DEPENDENCY_CONTRACT")
    if not isinstance(allowed_imports, list) or allowed_imports != sorted(set(allowed_imports)):
        raise SecurityReviewError("E_V250_SECURITY_DEPENDENCY_CONTRACT")
    for path in declared:
        _safe_path(path)
    dangerous = manifest.get("dangerous_operation_allowlist")
    if not isinstance(dangerous, dict) or set(dangerous) != {
        "allowed_callsite_fingerprints",
        "allowed_inventory_count",
        "allowed_inventory_sha256",
    }:
        raise SecurityReviewError("E_V250_SECURITY_DANGEROUS_ALLOWLIST")
    fingerprints = dangerous.get("allowed_callsite_fingerprints")
    if (
        not isinstance(fingerprints, list)
        or fingerprints != sorted(set(fingerprints))
        or any(not isinstance(item, str) or SHA256_RE.fullmatch(item) is None for item in fingerprints)
        or dangerous.get("allowed_inventory_count") != len(fingerprints)
        or dangerous.get("allowed_inventory_sha256") != _sha256(_canonical_bytes(fingerprints))
    ):
        raise SecurityReviewError("E_V250_SECURITY_DANGEROUS_ALLOWLIST")
    return sorted(normalized, key=lambda item: item["path"])


def _collect_reviewed_files(
    root: Path,
    source_commit: str,
    tree_entries: Mapping[str, Mapping[str, str]],
    targets: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    reviewed: list[dict[str, Any]] = []
    texts: dict[str, str] = {}
    for target in targets:
        path = str(target["path"])
        frozen, entry = _frozen_file(root, source_commit, tree_entries, path)
        try:
            text = frozen.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecurityReviewError("E_V250_SECURITY_TARGET_ENCODING") from exc
        if "\x00" in text:
            raise SecurityReviewError("E_V250_SECURITY_TARGET_ENCODING")
        digest = _sha256(frozen)
        texts[path] = text
        reviewed.append(
            {
                "path": path,
                "categories": list(target["categories"]),
                "content_kind": target["content_kind"],
                "git_mode": entry["mode"],
                "git_blob": entry["object_id"],
                "size": len(frozen),
                "sha256": digest,
                "filesystem_sha256": digest,
                "git_object_matches_filesystem": True,
                "symlink": False,
            }
        )
    return reviewed, texts


def _python_source(text: str, kind: str) -> str:
    if kind == "python":
        return text
    if kind != "python_heredoc":
        return ""
    marker = "exec \"$PYTHON_BIN\" - \"$ROOT\" \"$@\" <<'PY'\n"
    if marker not in text or not text.endswith("\nPY\n"):
        raise SecurityReviewError("E_V250_SECURITY_INSTALLER_HEREDOC")
    return text.split(marker, 1)[1].rsplit("\nPY\n", 1)[0] + "\n"


def _scan_dependencies(
    *,
    tree_entries: Mapping[str, Mapping[str, str]],
    targets: Sequence[Mapping[str, Any]],
    texts: Mapping[str, str],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    discovered_manifests = sorted(
        path
        for path, entry in tree_entries.items()
        if entry.get("type") == "blob"
        and any(fnmatch.fnmatchcase(PurePosixPath(path).name, pattern) for pattern in DEPENDENCY_BASENAME_PATTERNS)
    )
    declared_manifests = list(manifest["declared_dependency_files"])
    imported: list[dict[str, str]] = []
    unknown_imports: list[dict[str, str]] = []
    allowed_external = set(manifest["allowed_external_python_imports"])
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    for target in targets:
        path = str(target["path"])
        source = _python_source(texts[path], str(target["content_kind"]))
        if not source:
            continue
        try:
            syntax = ast.parse(source, filename=path)
        except SyntaxError as exc:
            raise SecurityReviewError("E_V250_SECURITY_PYTHON_SYNTAX") from exc
        names: set[str] = set()
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".", 1)[0])
        for name in sorted(names):
            state = "stdlib" if name in stdlib else "local" if name == "scripts" else "declared_external" if name in allowed_external else "unknown"
            item = {"path": path, "module": name, "state": state}
            imported.append(item)
            if state == "unknown":
                unknown_imports.append(item)
    findings: list[dict[str, Any]] = []
    if discovered_manifests != declared_manifests:
        findings.append(
            {
                "rule_id": "dependency_manifest_denominator_drift",
                "observed_sha256": _sha256(_canonical_bytes(discovered_manifests)),
                "expected_sha256": _sha256(_canonical_bytes(declared_manifests)),
            }
        )
    findings.extend(
        {
            "rule_id": "undeclared_python_import",
            "path": item["path"],
            "module": item["module"],
        }
        for item in unknown_imports
    )
    return {
        "passed": not findings,
        "discovered_dependency_files": discovered_manifests,
        "declared_dependency_files": declared_manifests,
        "python_imports": imported,
        "unknown_import_count": len(unknown_imports),
        "findings": findings,
    }


def _line_fingerprint(path: str, rule_id: str, normalized_line: str, ordinal: int) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "path": path,
                "rule_id": rule_id,
                "normalized_line": normalized_line,
                "occurrence_ordinal": ordinal,
            }
        )
    )


def _resolved_python_calls(
    targets: Sequence[Mapping[str, Any]], texts: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Resolve process-related module aliases and return every Python call."""

    calls: list[dict[str, Any]] = []
    process_modules = {"asyncio", "multiprocessing", "os", "pty", "subprocess"}
    for target in targets:
        path = str(target["path"])
        source = _python_source(texts[path], str(target["content_kind"]))
        if not source:
            continue
        syntax = ast.parse(source, filename=path)
        aliases: dict[str, str] = {}
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in process_modules:
                        aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.split(".", 1)[0] in process_modules
            ):
                for alias in node.names:
                    aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

        def resolved_name(function: ast.expr) -> str:
            if isinstance(function, ast.Name):
                return aliases.get(function.id, function.id)
            if isinstance(function, ast.Attribute):
                parts: list[str] = [function.attr]
                value = function.value
                while isinstance(value, ast.Attribute):
                    parts.append(value.attr)
                    value = value.value
                if isinstance(value, ast.Name):
                    root_name = aliases.get(value.id, value.id)
                    return ".".join([root_name, *reversed(parts)])
            return ""

        # Bind callable aliases, including the runtime host adapter's
        # ``popen_factory=subprocess.Popen`` default.  A conservative global
        # union is intentional: shadowing may create a false positive, but it
        # cannot make a child-process call disappear from the denominator.
        for _ in range(4):
            changed = False

            def bind_name(name: str, value: ast.expr | None) -> None:
                nonlocal changed
                if value is None:
                    return
                resolved = resolved_name(value)
                if _is_child_process_api(resolved) and aliases.get(name) != resolved:
                    aliases[name] = resolved
                    changed = True

            for node in ast.walk(syntax):
                if isinstance(node, ast.Assign):
                    for target_node in node.targets:
                        if isinstance(target_node, ast.Name):
                            bind_name(target_node.id, node.value)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    bind_name(node.target.id, node.value)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    positional = [*node.args.posonlyargs, *node.args.args]
                    defaults = node.args.defaults
                    if defaults:
                        for argument, default in zip(
                            positional[-len(defaults) :], defaults, strict=True
                        ):
                            bind_name(argument.arg, default)
                    for argument, default in zip(
                        node.args.kwonlyargs, node.args.kw_defaults, strict=True
                    ):
                        bind_name(argument.arg, default)
            if not changed:
                break

        source_lines = source.splitlines()
        for node in ast.walk(syntax):
            if not isinstance(node, ast.Call):
                continue
            function_name = resolved_name(node.func)
            end_line = int(getattr(node, "end_lineno", node.lineno) or node.lineno)
            segment = "\n".join(source_lines[node.lineno - 1 : end_line])
            normalized_segment = " ".join((segment or "").strip().split())
            calls.append(
                {
                    "path": path,
                    "line": node.lineno,
                    "function": function_name,
                    "normalized_segment": normalized_segment,
                    "shell_true": any(
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                        for keyword in node.keywords
                    ),
                }
            )
    return calls


def _is_child_process_api(function_name: str) -> bool:
    return bool(
        function_name.startswith("subprocess.")
        or function_name.startswith("asyncio.create_subprocess_")
        or function_name == "multiprocessing.Process"
        or function_name == "pty.spawn"
        or re.fullmatch(
            r"os\.(?:exec[A-Za-z0-9_]*|spawn[A-Za-z0-9_]*|fork|forkpty|posix_spawn|posix_spawnp)",
            function_name,
        )
    )


def _scan_dangerous_operations(
    texts: Mapping[str, str],
    targets: Sequence[Mapping[str, Any]],
    *,
    resolved_calls: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    occurrence: dict[tuple[str, str, str], int] = {}
    for path in sorted(texts):
        for line_number, line in enumerate(texts[path].splitlines(), start=1):
            normalized = " ".join(line.strip().split())
            if not normalized:
                continue
            for rule_id, pattern in DANGEROUS_OPERATION_RULES:
                for _ in pattern.finditer(line):
                    key = (path, rule_id, normalized)
                    ordinal = occurrence.get(key, 0) + 1
                    occurrence[key] = ordinal
                    observed.append(
                        {
                            "path": path,
                            "line": line_number,
                            "rule_id": rule_id,
                            "callsite_fingerprint": _line_fingerprint(path, rule_id, normalized, ordinal),
                        }
                    )
    # Child-process calls use the AST-resolved inventory as their sole source.
    # The original source segment is included in the fingerprint, so module and
    # from-import aliases cannot reuse an existing allowed API fingerprint.
    child_rule = "ast_resolved_child_process"
    child_calls = (
        list(resolved_calls)
        if resolved_calls is not None
        else _resolved_python_calls(targets, texts)
    )
    for call in child_calls:
        if not _is_child_process_api(str(call["function"])):
            continue
        normalized = f"{call['function']} :: {call['normalized_segment']}"
        key = (str(call["path"]), child_rule, normalized)
        ordinal = occurrence.get(key, 0) + 1
        occurrence[key] = ordinal
        observed.append(
            {
                "path": call["path"],
                "line": call["line"],
                "rule_id": child_rule,
                "resolved_api": call["function"],
                "callsite_fingerprint": _line_fingerprint(
                    str(call["path"]), child_rule, normalized, ordinal
                ),
            }
        )
    return observed


def _evaluate_dangerous_operations(
    texts: Mapping[str, str],
    manifest: Mapping[str, Any],
    *,
    resolved_calls: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    targets = manifest.get("review_targets")
    if not isinstance(targets, list):
        raise SecurityReviewError("E_V250_SECURITY_DENOMINATOR_TARGET")
    observed = _scan_dangerous_operations(
        texts, targets, resolved_calls=resolved_calls
    )
    observed_fingerprints = sorted(item["callsite_fingerprint"] for item in observed)
    expected = list(manifest["dangerous_operation_allowlist"]["allowed_callsite_fingerprints"])
    observed_set = set(observed_fingerprints)
    expected_set = set(expected)
    unknown = sorted(observed_set - expected_set)
    missing = sorted(expected_set - observed_set)
    expected_lookup = expected_set
    allowed = [
        {**item, "allow_state": "matched" if item["callsite_fingerprint"] in expected_lookup else "unknown"}
        for item in observed
    ]
    findings = [
        {"rule_id": "unknown_dangerous_operation", "callsite_fingerprint": item}
        for item in unknown
    ] + [
        {"rule_id": "missing_allowlisted_operation", "callsite_fingerprint": item}
        for item in missing
    ]
    return {
        "passed": not findings,
        "observed_count": len(observed),
        "allowed_count": sum(item["allow_state"] == "matched" for item in allowed),
        "inventory_sha256": _sha256(_canonical_bytes(observed_fingerprints)),
        "allowed_operations": allowed,
        "findings": findings,
    }


def _scan_secrets(texts: Mapping[str, str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for path in sorted(texts):
        for line_number, line in enumerate(texts[path].splitlines(), start=1):
            for rule_id, pattern in SECRET_RULES:
                if pattern.search(line):
                    findings.append(
                        {
                            "rule_id": rule_id,
                            "path": path,
                            "line": line_number,
                            "line_sha256": _sha256(line.encode("utf-8")),
                            "matched_value_redacted": True,
                        }
                    )
    return {
        "passed": not findings,
        "rule_count": len(SECRET_RULES),
        "scanned_file_count": len(texts),
        "finding_count": len(findings),
        "findings": findings,
    }


def _scan_command_boundaries(
    targets: Sequence[Mapping[str, Any]],
    texts: Mapping[str, str],
    *,
    resolved_calls: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    subprocess_calls: list[dict[str, Any]] = []
    allowed_child_process_apis = {"subprocess.Popen", "subprocess.run"}
    calls = (
        list(resolved_calls)
        if resolved_calls is not None
        else _resolved_python_calls(targets, texts)
    )
    for call in calls:
        function_name = str(call["function"])
        path = str(call["path"])
        line = int(call["line"])
        if function_name in {"eval", "exec", "os.system", "os.popen"}:
            findings.append({"rule_id": "forbidden_dynamic_execution", "path": path, "line": line, "function": function_name})
        if _is_child_process_api(function_name):
            subprocess_calls.append({"path": path, "line": line, "function": function_name, "shell_true": call["shell_true"]})
            if call["shell_true"]:
                findings.append({"rule_id": "subprocess_shell_true", "path": path, "line": line})
            if function_name not in allowed_child_process_apis:
                findings.append(
                    {
                        "rule_id": "unallowlisted_child_process_api",
                        "path": path,
                        "line": line,
                        "function": function_name,
                    }
                )
    return {
        "passed": not findings,
        "subprocess_call_count": len(subprocess_calls),
        "subprocess_calls": subprocess_calls,
        "findings": findings,
    }


def _scan_workflows_and_ssh(texts: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow_paths = sorted(path for path in texts if path.startswith(".github/workflows/"))
    action_pins: list[dict[str, Any]] = []
    workflow_findings: list[dict[str, Any]] = []
    ssh_findings: list[dict[str, Any]] = []
    for path in workflow_paths:
        text = texts[path]
        uses: list[tuple[str, str, str, bool]] = []
        for match in re.finditer(
            r"(?m)^\s*(?P<step>-\s+)?uses:\s*(?P<value>[^\s#]+)", text
        ):
            value = match.group("value")
            scope = "step" if match.group("step") else "job"
            if value.startswith("./"):
                uses.append((value, "local-source", scope, True))
                continue
            action, separator, revision = value.rpartition("@")
            uses.append((action if separator else value, revision if separator else "", scope, False))
        if not uses:
            workflow_findings.append({"rule_id": "workflow_action_denominator_empty", "path": path})
        for action, revision, scope, local_source in uses:
            pinned = local_source or COMMIT_RE.fullmatch(revision) is not None
            action_pins.append({"path": path, "action": action, "revision": revision, "scope": scope, "local_source": local_source, "pinned_full_sha": pinned})
            if not pinned:
                workflow_findings.append({"rule_id": "workflow_action_not_pinned", "path": path, "action": action, "scope": scope})
        checkout_count = sum(action == "actions/checkout" for action, _, _, _ in uses)
        ssh_key_count = len(re.findall(r"(?m)^\s+ssh-key:\s*\$\{\{\s*secrets\.[A-Za-z0-9_]+\s*\}\}\s*$", text))
        persist_false_count = len(re.findall(r"(?m)^\s+persist-credentials:\s*false\s*$", text))
        ssh_assertion_count = text.count('expected="git@github.com:${GITHUB_REPOSITORY}.git"')
        if checkout_count < 1 or ssh_key_count != checkout_count or persist_false_count != checkout_count or ssh_assertion_count != checkout_count:
            ssh_findings.append({"rule_id": "workflow_checkout_ssh_contract", "path": path})

    github_git_https: list[dict[str, Any]] = []
    for path, text in sorted(texts.items()):
        for line_number, line in enumerate(text.splitlines(), start=1):
            if re.search(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?(?:\s|['\"]|$)", line):
                # Browser/API/release URLs are allowed; only a Git payload URL
                # ending in .git is forbidden.
                if re.search(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", line):
                    github_git_https.append({"path": path, "line": line_number})
    if github_git_https:
        ssh_findings.extend({"rule_id": "github_git_https_forbidden", **item} for item in github_git_https)

    required_markers = {
        "scripts/v250/s4_executor.py": (
            'CANONICAL_REMOTE = "git@github.com:vibe-coding-era/goal-teams.git"',
            'GH_REPOSITORY = "github.com/vibe-coding-era/goal-teams"',
        ),
        "scripts/v250/github_ssh.py": (
            '"https_fallback_allowed": False',
            'return ["git", "push", remote_name, refspec]',
        ),
        "scripts/v250/release_flow.py": (
            'f"git@github.com:{repository}.git"',
        ),
    }
    for path, markers in required_markers.items():
        text = texts.get(path, "")
        for marker in markers:
            if marker not in text:
                ssh_findings.append({"rule_id": "github_ssh_semantic_marker_missing", "path": path, "marker_sha256": _sha256(marker.encode("utf-8"))})
    return (
        {"passed": not workflow_findings, "action_pins": action_pins, "findings": workflow_findings},
        {"passed": not ssh_findings, "workflow_checkout_count": sum(item["action"] == "actions/checkout" for item in action_pins), "findings": ssh_findings},
    )


def _assertion(assertion_id: str, passed: bool, **observed: Any) -> dict[str, Any]:
    return {"assertion_id": assertion_id, "passed": bool(passed), "observed": observed}


def run_review(
    *,
    source_commit: str,
    source_tree: str,
    reviewer_id: str,
    review_run_id: str,
    orchestrator_pid: int,
    root: Path = ROOT,
) -> dict[str, Any]:
    if not reviewer_id or not review_run_id or orchestrator_pid < 1:
        raise SecurityReviewError("E_V250_SECURITY_REVIEWER_IDENTITY")
    root = root.resolve()
    identity, tree_entries = _verify_exact_identity(root, source_commit, source_tree)
    manifest, manifest_sha256 = _load_manifest(root, source_commit, tree_entries)
    targets = _validate_manifest(manifest)
    reviewed_files, texts = _collect_reviewed_files(root, source_commit, tree_entries, targets)

    dependency = _scan_dependencies(tree_entries=tree_entries, targets=targets, texts=texts, manifest=manifest)
    secrets = _scan_secrets(texts)
    resolved_calls = _resolved_python_calls(targets, texts)
    dangerous = _evaluate_dangerous_operations(
        texts, manifest, resolved_calls=resolved_calls
    )
    commands = _scan_command_boundaries(
        targets, texts, resolved_calls=resolved_calls
    )
    workflows, git_ssh = _scan_workflows_and_ssh(texts)

    command_contract = json.loads(texts["references/current/generations/V2.62/contracts/release-command-manifest.json"])
    s2 = command_contract.get("release", {}).get("s2", {})
    s2_separation = bool(
        s2.get("security_check_invocation_limit") == 0
        and manifest.get("s2_security_substitute") is False
        and manifest.get("workflow_phase") == "release"
        and manifest.get("stage") == "released"
    )
    fresh_process = os.getpid() != orchestrator_pid

    reviewed_file_set_sha256 = _sha256(_canonical_bytes(reviewed_files))
    denominator: dict[str, Any] = {
        "denominator_id": manifest["denominator_id"],
        "generation_id": "V2.62",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "manifest_path": CONTRACT_PATH,
        "manifest_sha256": manifest_sha256,
        "target_count": len(targets),
        "target_paths": [item["path"] for item in targets],
        "required_categories": sorted(REQUIRED_CATEGORIES),
        "reviewed_file_set_sha256": reviewed_file_set_sha256,
        "unknown_or_missing_policy": "fail_closed",
    }
    denominator["denominator_sha256"] = _sha256(_canonical_bytes(denominator))

    assertions = [
        _assertion("V250-SEC-EXACT-GIT-IDENTITY", True, **identity),
        _assertion("V250-SEC-DENOMINATOR-COMPLETE", len(targets) == len(MANDATORY_REVIEW_TARGETS), target_count=len(targets), required_target_count=len(MANDATORY_REVIEW_TARGETS)),
        _assertion("V250-SEC-GIT-OBJECT-FILESYSTEM", all(item["git_object_matches_filesystem"] for item in reviewed_files), reviewed_file_count=len(reviewed_files)),
        _assertion("V250-SEC-PATH-SYMLINK-MODE", all(not item["symlink"] and GIT_MODE_RE.fullmatch(item["git_mode"]) for item in reviewed_files), symlink_count=sum(bool(item["symlink"]) for item in reviewed_files)),
        _assertion("V250-SEC-DEPENDENCY-SURFACE", dependency["passed"], dependency_file_count=len(dependency["discovered_dependency_files"]), python_import_count=len(dependency["python_imports"]), unknown_import_count=dependency["unknown_import_count"]),
        _assertion("V250-SEC-SECRET-NEGATIVE-SCAN", secrets["passed"], scanned_file_count=secrets["scanned_file_count"], rule_count=secrets["rule_count"], finding_count=secrets["finding_count"]),
        _assertion("V250-SEC-DANGEROUS-OPERATION-ALLOWLIST", dangerous["passed"], observed_count=dangerous["observed_count"], allowed_count=dangerous["allowed_count"], inventory_sha256=dangerous["inventory_sha256"], finding_count=len(dangerous["findings"])),
        _assertion("V250-SEC-COMMAND-EXECUTION-BOUNDARIES", commands["passed"], subprocess_call_count=commands["subprocess_call_count"], finding_count=len(commands["findings"])),
        _assertion("V250-SEC-GITHUB-GIT-SSH-ONLY", git_ssh["passed"], workflow_checkout_count=git_ssh["workflow_checkout_count"], finding_count=len(git_ssh["findings"])),
        _assertion("V250-SEC-WORKFLOW-ACTION-PINS", workflows["passed"], action_count=len(workflows["action_pins"]), finding_count=len(workflows["findings"])),
        _assertion("V250-SEC-S2-SECURITY-SEPARATION", s2_separation, s2_security_check_invocation_limit=s2.get("security_check_invocation_limit"), s1_release_security_review_invocation_count=1),
        _assertion("V250-SEC-FRESH-CORRELATED-PROCESS", fresh_process, runner_pid=os.getpid(), orchestrator_pid=orchestrator_pid, actor_assurance="I1", actor_relationship="correlated"),
    ]
    findings = sorted(
        [*dependency["findings"], *secrets["findings"], *dangerous["findings"], *commands["findings"], *git_ssh["findings"], *workflows["findings"]],
        key=lambda item: _canonical_bytes(item),
    )
    passed = all(item["passed"] for item in assertions) and not findings
    contract_digests = {
        item["path"]: item["sha256"]
        for item in reviewed_files
        if "contract" in item["categories"]
    }
    review_material = {
        "assertions": assertions,
        "findings": findings,
        "reviewed_file_set_sha256": reviewed_file_set_sha256,
        "dangerous_operation_inventory_sha256": dangerous["inventory_sha256"],
    }
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-v2.62-release-gate-receipt-v1",
        "gate_id": "release_security_review",
        "run_id": review_run_id,
        "review_run_id": review_run_id,
        "runner_role": "exact_released_implementation_security_reviewer",
        "reviewer_identity": {
            "reviewer_id": reviewer_id,
            "runner_path": "scripts/checks/run-v250-release-security-review.py",
            "runner_sha256": next(item["sha256"] for item in reviewed_files if item["path"] == "scripts/checks/run-v250-release-security-review.py"),
        },
        "source_commit": source_commit,
        "source_tree": source_tree,
        "identity_binding": identity,
        "review_denominator": denominator,
        "reviewed_files": reviewed_files,
        "reviewed_file_set_sha256": reviewed_file_set_sha256,
        "check_state": "passed" if passed else "failed",
        "evidence_state": "current",
        "run_outcome": "passed" if passed else "failed",
        "invocation_count_for_released_identity": 1,
        "fresh_process_observed": fresh_process,
        "fresh_separate_process": fresh_process,
        "runner_pid": os.getpid(),
        "orchestrator_pid": orchestrator_pid,
        "actor_assurance": "I1",
        "actor_relationship": "correlated",
        "external_independence": False,
        "independence_claim": False,
        "cryptographic_host_attestation": False,
        "independence_scope": "fresh_separate_process_only",
        "legacy_security_fixture_invocation_count": 0,
        "s2_security_check_invocation_count": 0,
        "s2_projection": "forbidden",
        "contract_digests": dict(sorted(contract_digests.items())),
        "assertions": assertions,
        "findings": findings,
        "finding_count": len(findings),
        "dependency_review": dependency,
        "secret_negative_scan": secrets,
        "dangerous_operation_review": dangerous,
        "command_execution_review": commands,
        "workflow_dependency_review": workflows,
        "git_ssh_review": git_ssh,
        "review_digest": _sha256(_canonical_bytes(review_material)),
    }
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--review-run-id", required=True)
    parser.add_argument("--orchestrator-pid", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = run_review(
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            reviewer_id=args.reviewer_id,
            review_run_id=args.review_run_id,
            orchestrator_pid=args.orchestrator_pid,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SecurityReviewError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "goal-teams-v2.62-release-gate-receipt-v1",
                    "gate_id": "release_security_review",
                    "passed": False,
                    "check_state": "failed",
                    "run_outcome": "failed",
                    "evidence_state": "invalid",
                    "error_code": str(exc),
                    "actor_assurance": "I1",
                    "actor_relationship": "correlated",
                    "external_independence": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["check_state"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
