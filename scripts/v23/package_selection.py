#!/usr/bin/env python3
"""Single-source blind package selection for the V2.3 runner and validator."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_MANIFEST_RELATIVE = "scripts/install/package-manifest.txt"
BLIND_PACKAGE_ALLOWLIST = (
    "AGENTS.md",
    "VERSION",
    "SKILL.md",
    "RULES.md",
    "goal-teams.md",
    "agents",
    "docs/change-history.en.md",
    "docs/change-history.md",
    "docs/archive/V2.34",
    "docs/release-contents.en.md",
    "docs/release-contents.md",
    "prompts",
    "references",
    "schemas/v2.3",
    "schemas/v2.43",
    "schemas/v2.44",
    "scripts/review",
    "scripts/v23",
    "subagents",
)
BLIND_PACKAGE_FORBIDDEN_PARTS = frozenset(
    {
        "tests",
        "benchmarks",
        "benchmark",
        "examples",
        "GoalTeamsWork-V2.3",
        "outputs",
        "output",
        ".codex",
        ".git",
        ".goalteams-state",
        ".goalteams-quarantine",
        "__pycache__",
    }
)
REQUIRED_INSTALLER_PATHS = frozenset(
    {"VERSION", "SKILL.md", "scripts/check.sh", PACKAGE_MANIFEST_RELATIVE}
)


class PackageSelectionError(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_list_digest(paths: list[str]) -> str:
    return _digest_bytes(b"".join(path.encode("utf-8") + b"\0" for path in paths))


def _validate_relative(raw: str) -> None:
    path = PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PackageSelectionError("E_PACKAGE_IDENTITY")


def _safe_regular_path(root: Path, relative: str) -> Path:
    """Resolve a repository file without following a symlink in any component."""
    _validate_relative(relative)
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise PackageSelectionError("E_PACKAGE_IDENTITY") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PackageSelectionError("E_PACKAGE_IDENTITY")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                raise PackageSelectionError("E_PACKAGE_IDENTITY")
        elif not stat.S_ISREG(metadata.st_mode):
            raise PackageSelectionError("E_PACKAGE_IDENTITY")
    return current


def _manifest_rules(root: Path) -> tuple[set[str], list[str], set[str], bytes]:
    path = _safe_regular_path(root, PACKAGE_MANIFEST_RELATIVE)
    manifest_bytes = path.read_bytes()
    try:
        lines = manifest_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise PackageSelectionError("E_PACKAGE_IDENTITY") from exc
    files: set[str] = set()
    prefixes: list[str] = []
    generated: set[str] = set()
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in {"file", "prefix", "generated"}:
            raise PackageSelectionError("E_PACKAGE_IDENTITY")
        kind, value = parts
        _validate_relative(value.rstrip("/"))
        if kind == "file":
            if value.endswith("/"):
                raise PackageSelectionError("E_PACKAGE_IDENTITY")
            files.add(value)
        elif kind == "generated":
            if value.endswith("/"):
                raise PackageSelectionError("E_PACKAGE_IDENTITY")
            generated.add(value)
        elif not value.endswith("/"):
            raise PackageSelectionError("E_PACKAGE_IDENTITY")
        else:
            prefixes.append(value)
    if generated and generated != {"references/okf-conformance-manifest.json"}:
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    return files, sorted(set(prefixes)), generated, manifest_bytes


def _git_output(root: Path, arguments: list[str]) -> bytes:
    git_input = Path("/usr/bin/git")
    git_path = git_input.resolve()
    if git_input.is_symlink() or git_path != git_input.absolute() or not git_path.is_file():
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    try:
        process = subprocess.run(
            [str(git_path), *arguments],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": os.environ.get("HOME", "/tmp"),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PackageSelectionError("E_PACKAGE_IDENTITY") from exc
    if process.returncode != 0:
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    return process.stdout


def _index_entries(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for row in (item for item in _git_output(root, ["ls-files", "--stage", "-z"]).split(b"\0") if item):
        try:
            metadata, raw_path = row.split(b"\t", 1)
            mode, object_id, stage_number = metadata.decode("ascii").split(" ", 2)
            relative = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PackageSelectionError("E_PACKAGE_IDENTITY") from exc
        _validate_relative(relative)
        if (
            stage_number != "0"
            or relative in entries
            or len(object_id) not in {40, 64}
            or any(character not in "0123456789abcdef" for character in object_id)
        ):
            raise PackageSelectionError("E_PACKAGE_IDENTITY")
        entries[relative] = mode
    return dict(sorted(entries.items()))


def _untracked_paths(root: Path) -> list[str]:
    try:
        paths = [
            item.decode("utf-8")
            for item in _git_output(
                root,
                ["ls-files", "--others", "--exclude-standard", "-z"],
            ).split(b"\0")
            if item
        ]
    except UnicodeDecodeError as exc:
        raise PackageSelectionError("E_PACKAGE_IDENTITY") from exc
    for relative in paths:
        _validate_relative(relative)
    return sorted(paths)


def _validated_install_entries(
    root: Path,
    selected_by_manifest: Any,
) -> dict[str, str]:
    """Reconstruct the index projection only inside installer staging validation.

    The transactional installer intentionally does not copy ``.git`` into its
    stage.  Its stage has already been compared byte-for-byte and mode-for-mode
    with the prepared Git projection, so nested validation may reconstruct that
    same projection from the isolated tree.  This fallback is never available
    to ordinary or release runs.
    """
    if os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") != "1":
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    entries: dict[str, str] = {}
    try:
        for current, directories, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in directories:
                path = current_path / name
                if path.is_symlink() or not path.is_dir():
                    raise PackageSelectionError("E_PACKAGE_IDENTITY")
            for name in filenames:
                path = current_path / name
                relative = path.relative_to(root).as_posix()
                if selected_by_manifest(relative):
                    _safe_regular_path(root, relative)
                    entries[relative] = normalized_git_mode(path)
    except OSError as exc:
        raise PackageSelectionError("E_PACKAGE_IDENTITY") from exc
    return dict(sorted(entries.items()))


def blind_path_allowed(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts or parts[0].startswith("GoalTeamsWork-"):
        return False
    if set(parts) & BLIND_PACKAGE_FORBIDDEN_PARTS:
        return False
    if len(parts) >= 2 and parts[0] == "scripts" and parts[1] == "benchmark":
        return False
    return any(
        relative == allowed or relative.startswith(allowed.rstrip("/") + "/")
        for allowed in BLIND_PACKAGE_ALLOWLIST
    )


def normalized_git_mode(path: Path) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PackageSelectionError("E_PACKAGE_IDENTITY") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    permissions = stat.S_IMODE(metadata.st_mode)
    if permissions == 0o644:
        return "100644"
    if permissions == 0o755:
        return "100755"
    raise PackageSelectionError("E_PACKAGE_IDENTITY")


def tree_manifest(root: Path) -> tuple[list[dict[str, Any]], str]:
    root = root.resolve()
    entries: list[dict[str, Any]] = []
    try:
        for current, directories, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            retained: list[str] = []
            for name in sorted(directories):
                path = current_path / name
                if path.is_symlink() or not path.is_dir():
                    raise PackageSelectionError("E_BLIND_AGENT_STAGE")
                if current_path == root and name == ".git":
                    continue
                retained.append(name)
            directories[:] = retained
            for name in sorted(filenames):
                path = current_path / name
                mode = normalized_git_mode(path)
                entries.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "mode": mode,
                        "size": path.stat().st_size,
                        "sha256": _digest_path(path),
                    }
                )
    except OSError as exc:
        raise PackageSelectionError("E_BLIND_AGENT_STAGE") from exc
    entries.sort(key=lambda item: item["path"])
    return entries, _digest_bytes(_canonical_bytes(entries))


def build_blind_package_selection(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files, prefixes, generated, manifest_bytes = _manifest_rules(root)

    def selected_by_manifest(relative: str) -> bool:
        return (
            relative in files
            or relative in generated
            or any(relative.startswith(prefix) for prefix in prefixes)
        )

    validated_install_projection = False
    try:
        index_entries = _index_entries(root)
    except PackageSelectionError:
        index_entries = _validated_install_entries(root, selected_by_manifest)
        validated_install_projection = True
    if not validated_install_projection and any(path in index_entries for path in generated):
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    if validated_install_projection and any(path not in index_entries for path in generated):
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    installer_paths = sorted(path for path in index_entries if selected_by_manifest(path))
    blind_paths = [path for path in installer_paths if blind_path_allowed(path)]
    if (
        not installer_paths
        or not blind_paths
        or any(path not in installer_paths for path in REQUIRED_INSTALLER_PATHS)
    ):
        raise PackageSelectionError("E_PACKAGE_IDENTITY")
    validated_paths: dict[str, Path] = {}
    for relative in installer_paths:
        path = _safe_regular_path(root, relative)
        if normalized_git_mode(path) != index_entries[relative]:
            raise PackageSelectionError("E_PACKAGE_IDENTITY")
        validated_paths[relative] = path
    installer_entries = [{"path": path, "mode": index_entries[path]} for path in installer_paths]
    blind_entries = [{"path": path, "mode": index_entries[path]} for path in blind_paths]
    file_entries: list[dict[str, Any]] = []
    for relative in blind_paths:
        path = validated_paths[relative]
        mode = index_entries[relative]
        file_entries.append(
            {
                "path": relative,
                "mode": mode,
                "size": path.stat().st_size,
                "sha256": _digest_path(path),
            }
        )
    excluded_untracked = [] if validated_install_projection else [
        path
        for path in _untracked_paths(root)
        if selected_by_manifest(path) and blind_path_allowed(path)
    ]
    forbidden = sorted(BLIND_PACKAGE_FORBIDDEN_PARTS)
    allowlist = list(BLIND_PACKAGE_ALLOWLIST)
    return {
        "package_manifest_path": PACKAGE_MANIFEST_RELATIVE,
        "package_manifest_sha256": _digest_bytes(manifest_bytes),
        "generated_required_paths": sorted(generated),
        "installer_tracked_paths": installer_paths,
        "installer_tracked_paths_sha256": _path_list_digest(installer_paths),
        "installer_tracked_entries": installer_entries,
        "installer_tracked_entries_sha256": _digest_bytes(_canonical_bytes(installer_entries)),
        "blind_safe_paths": blind_paths,
        "blind_safe_paths_sha256": _path_list_digest(blind_paths),
        "blind_safe_entries": blind_entries,
        "blind_safe_entries_sha256": _digest_bytes(_canonical_bytes(blind_entries)),
        "forbidden_exclusions": forbidden,
        "forbidden_exclusions_sha256": _digest_bytes(_canonical_bytes(forbidden)),
        "blind_safe_allowlist": allowlist,
        "blind_safe_allowlist_sha256": _digest_bytes(_canonical_bytes(allowlist)),
        "excluded_untracked": excluded_untracked,
        "files": file_entries,
        "package_sha256": _digest_bytes(_canonical_bytes(file_entries)),
    }
