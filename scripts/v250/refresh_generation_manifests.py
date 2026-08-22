#!/usr/bin/env python3
"""Stage, validate, and optionally activate a deterministic Current generation.

The default writer refreshes a non-active candidate and never changes
``references/current/ACTIVE.json``.  ``--activate`` is the only ACTIVE writer;
it requires an exact base activation digest and replaces ACTIVE last.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ACTIVE_PATH = Path("references/current/ACTIVE.json")
REPLAY_PATH = Path("references/legacy-replay/manifest.json")
WRITER = "scripts/v250/refresh_generation_manifests.py"
PACKAGE_MANIFEST = Path("scripts/install/package-manifest.txt")
CORE_POLICY_VERSION = "V2.5"
LEGACY_DATA_SCHEMA_VERSION = "V2.3"
DEFAULT_ACTIVE_LOCK_TIMEOUT_SECONDS = 10.0
MAX_ACTIVE_LOCK_TIMEOUT_SECONDS = 300.0


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe repository path: {value!r}")
    return Path(*path.parts)


def _load(relative: Path) -> dict[str, Any]:
    try:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load object: {relative.as_posix()}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {relative.as_posix()}")
    return value


def _predecessor_window_status(predecessor: dict[str, Any]) -> str:
    """Open rollback only while every predecessor member still verifies."""

    root_sets = predecessor.get("root_sets")
    if not isinstance(root_sets, dict) or not root_sets:
        return "closed"
    observed_member = False
    for entries in root_sets.values():
        if not isinstance(entries, list):
            return "closed"
        for entry in entries:
            if not isinstance(entry, dict):
                return "closed"
            relative = entry.get("path")
            expected = entry.get("sha256")
            if not isinstance(relative, str) or not isinstance(expected, str):
                return "closed"
            try:
                raw = (ROOT / _safe_relative(relative)).read_bytes()
            except OSError:
                return "closed"
            if _sha256(raw) != expected:
                return "closed"
            observed_member = True
    return "open" if observed_member else "closed"


def _generation_paths(generation_id: str) -> dict[str, Path]:
    if not generation_id.startswith("V") or generation_id.count(".") != 1:
        raise ValueError("generation id must use V<major>.<minor>")
    suffix = generation_id[1:].lower()
    compact = suffix.replace(".", "")
    root = Path(f"references/current/generations/{generation_id}")
    return {
        "root": root,
        "rule": root / "rule-manifest.json",
        "prompt": root / "prompt-manifest.json",
        "activation": root / "activation-manifest.json",
        "compatibility": Path(f"references/compatibility/v{suffix}"),
        "profile": Path(f"references/profiles/goal-teams-self-release-v{suffix}.md"),
        "release_profile": Path(f"references/release-profiles/v{suffix}.json"),
        "product_scripts": Path(f"scripts/v{compact}"),
        "product_schemas": Path(f"schemas/v{suffix}"),
        "product_tests": Path(f"tests/v{compact}"),
    }


def _refreshed_rule_manifest(paths: dict[str, Path], generation_id: str) -> dict[str, Any]:
    value = _load(paths["rule"])
    value["generation_id"] = generation_id
    owners = value.get("owners")
    if not isinstance(owners, list) or not owners:
        raise ValueError("rule manifest owners must be a non-empty array")
    seen_paths: set[str] = set()
    seen_rule_ids: set[str] = set()
    for owner in owners:
        if not isinstance(owner, dict) or not isinstance(owner.get("path"), str):
            raise ValueError("invalid rule owner")
        relative = owner["path"]
        _safe_relative(relative)
        if relative in seen_paths:
            raise ValueError(f"duplicate owner path: {relative}")
        seen_paths.add(relative)
        dependencies = owner.get("dependencies")
        if not isinstance(dependencies, list):
            raise ValueError(f"owner dependencies must be an array: {relative}")
        normalized_dependencies: list[dict[str, Any]] = []
        for dependency in dependencies:
            if isinstance(dependency, str):
                normalized_dependencies.append(
                    {"kind": "required", "owner_id": dependency}
                )
            elif isinstance(dependency, dict):
                normalized_dependencies.append(dict(dependency))
            else:
                raise ValueError(f"invalid owner dependency: {relative}")
        owner["dependencies"] = normalized_dependencies
        raw = (ROOT / relative).read_bytes()
        owner["source_sha256"] = _sha256(raw)
        for rule_id in owner.get("owned_rule_ids", []):
            if not isinstance(rule_id, str) or not rule_id or rule_id in seen_rule_ids:
                raise ValueError(f"invalid or duplicate rule id: {rule_id!r}")
            seen_rule_ids.add(rule_id)
    return value


def _refreshed_prompt_manifest(paths: dict[str, Path], generation_id: str) -> dict[str, Any]:
    value = _load(paths["prompt"])
    value["generation_id"] = generation_id
    value["manifest_state"] = (
        "active_current" if value.get("manifest_state") == "active_current" else "inactive_candidate"
    )
    if generation_id in {"V2.63", "V2.65"}:
        value["path_deduplication_rule"] = "reject_duplicate_repo_relative_posix_paths"
    routes = value.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise ValueError("prompt routes must be a non-empty object")
    allowlist = value.get("current_rule_allowlist")
    if not isinstance(allowlist, list) or len(allowlist) != len(set(allowlist)):
        raise ValueError("prompt current rule allowlist is invalid")
    allowed = set(allowlist)
    for route in routes.values():
        if not isinstance(route, dict) or not isinstance(route.get("ordered_refs"), list):
            raise ValueError("invalid prompt route")
        ordered = route["ordered_refs"]
        if len(ordered) != len(set(ordered)):
            raise ValueError("duplicate prompt route ref")
        if any(ref not in allowed for ref in ordered):
            raise ValueError("prompt route escapes Current rule allowlist")
        route["ordered_refs"] = ordered
        route["expected_loaded_rule_bytes"] = sum(
            (ROOT / _safe_relative(relative)).stat().st_size for relative in ordered
        )
    return value


def _glob_files(pattern: str) -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.glob(pattern)
        if path.is_file() and not path.is_symlink()
    }


def _is_regular_repository_source(relative: str) -> bool:
    """Accept only a physically present regular file below the repository root."""

    try:
        safe = _safe_relative(relative)
        cursor = ROOT.resolve(strict=True)
        parts = safe.parts
        for index, part in enumerate(parts):
            cursor = cursor / part
            metadata = cursor.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                return False
            if index == len(parts) - 1:
                return stat.S_ISREG(metadata.st_mode)
            if not stat.S_ISDIR(metadata.st_mode):
                return False
    except (OSError, ValueError):
        return False
    return False


def _package_selected_paths(
    generation_id: str | None = None,
    activation: dict[str, Any] | None = None,
) -> set[str]:
    """Select the live Current package or an exact predecessor fixture."""

    live_package = generation_id is None
    current_version = (
        None
        if live_package
        else (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    )
    if not live_package and generation_id != current_version:
        if activation is None:
            activation = _load(
                Path(
                    f"references/current/generations/{generation_id}/"
                    "activation-manifest.json"
                )
            )
        if generation_id != "V2.63" or activation.get("generation_id") != generation_id:
            raise ValueError("unsupported historical package fixture generation")
        allowlist = activation.get("current_default_allowlist")
        supplement = activation.get("package_supplement_allowlist")
        if (
            not isinstance(allowlist, list)
            or not isinstance(supplement, list)
            or not all(isinstance(path, str) for path in allowlist + supplement)
        ):
            raise ValueError("historical package fixture closure is missing")
        selected = set(allowlist) | set(supplement)
        forbidden_prefixes = (
            "references/current/generations/V2.65/",
            "references/compatibility/v2.65/",
            "schemas/v2.65/",
            "scripts/v265/",
            "tests/v265/",
        )
        if any(path.startswith(forbidden_prefixes) for path in selected):
            raise ValueError("historical package fixture contains Current V2.65 paths")
        missing = sorted(
            path for path in selected if not _is_regular_repository_source(path)
        )
        if missing:
            raise ValueError(
                "historical package fixture path is missing: " + ", ".join(missing)
            )
        return selected

    # Expand the live Current package manifest to its exact repository path set.

    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        source_paths = {
            relative
            for item in result.stdout.split(b"\0")
            if item
            for relative in (item.decode("utf-8"),)
            if _is_regular_repository_source(relative)
        }
    else:
        source_paths = {
            relative
            for path in ROOT.rglob("*")
            for relative in (path.relative_to(ROOT).as_posix(),)
            if _is_regular_repository_source(relative)
        }
    selected: set[str] = set()
    for number, raw in enumerate(
        (ROOT / PACKAGE_MANIFEST).read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or fields[0] not in {"file", "prefix", "generated"}:
            raise ValueError(f"invalid package manifest row: {number}")
        kind, value = fields
        if kind == "generated":
            continue
        if kind == "file":
            if value not in source_paths:
                raise ValueError(f"package file is missing: {value}")
            selected.add(value)
            continue
        matches = {path for path in source_paths if path.startswith(value)}
        if not matches:
            raise ValueError(f"package prefix is empty: {value}")
        selected.update(matches)
    return selected


def _member(relative: str, virtual: dict[str, bytes]) -> dict[str, Any]:
    safe = _safe_relative(relative)
    raw = virtual.get(relative)
    if raw is None:
        path = ROOT / safe
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"unsafe or missing activation member: {relative}")
        raw = path.read_bytes()
    return {"path": relative, "sha256": _sha256(raw), "bytes": len(raw)}


def _existing_paths(activation: dict[str, Any], root_name: str) -> set[str]:
    root_sets = activation.get("root_sets")
    if not isinstance(root_sets, dict) or not isinstance(root_sets.get(root_name), list):
        raise ValueError(f"activation root set missing: {root_name}")
    paths = {
        item.get("path")
        for item in root_sets[root_name]
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if len(paths) != len(root_sets[root_name]):
        raise ValueError(f"invalid or duplicate activation root: {root_name}")
    return paths


def _legacy_classification(
    activation: dict[str, Any], generation_id: str, predecessor: str
) -> dict[str, Any]:
    replay_raw = (ROOT / REPLAY_PATH).read_bytes()
    legacy = activation.get("legacy_classification")
    if not isinstance(legacy, dict):
        raise ValueError("legacy classification must be an object")
    prefixes = set(legacy.get("path_prefixes", []))
    suffix = predecessor[1:].lower()
    compact = suffix.replace(".", "")
    prefixes.update(
        {
            f"references/current/generations/{predecessor}/",
            f"references/compatibility/v{suffix}/",
            f"scripts/v{compact}/",
            f"schemas/v{suffix}/",
            f"tests/v{compact}/",
        }
    )
    prefixes.discard(f"references/current/generations/{generation_id}/")
    exact = set(legacy.get("exact_paths", []))
    exact.update(
        {
            f"references/profiles/goal-teams-self-release-v{suffix}.md",
            f"references/release-profiles/v{suffix}.json",
        }
    )
    current_suffix = generation_id[1:].lower()
    exact.discard(f"references/profiles/goal-teams-self-release-v{current_suffix}.md")
    exact.discard(f"references/release-profiles/v{current_suffix}.json")
    return {
        "path_prefixes": sorted(prefixes),
        "exact_paths": sorted(exact),
        "replay_manifest_sha256": _sha256(replay_raw),
    }


def _refreshed_activation(
    paths: dict[str, Path],
    generation_id: str,
    predecessor: str,
    state: str,
    rule: dict[str, Any],
    prompt: dict[str, Any],
) -> dict[str, Any]:
    value = _load(paths["activation"])
    current_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    historical_target = generation_id != current_version
    frozen_root_paths = {
        root_name: _existing_paths(value, root_name)
        for root_name in (
            "bootstrap",
            "current",
            "execution",
            "schemas_and_validators",
        )
    }
    frozen_package_activation = {
        "generation_id": value.get("generation_id"),
        "current_default_allowlist": list(
            value.get("current_default_allowlist", [])
        ),
        "package_supplement_allowlist": list(
            value.get("package_supplement_allowlist", [])
        ),
    }
    value["schema_version"] = "goal-teams-activation-manifest-v2.50"
    value["generation_id"] = generation_id
    value["generation_state"] = state
    value["baseline_generation_id"] = predecessor
    value["identity"] = {
        "loaded_runtime_product_version": generation_id,
        "core_policy_version": CORE_POLICY_VERSION,
        "legacy_data_schema_version": LEGACY_DATA_SCHEMA_VERSION,
        "route_contract_schema_version": "goal-teams-project-route-v2.50",
        "target_policy_generation": generation_id,
    }

    rule_raw = _json_bytes(rule)
    prompt_raw = _json_bytes(prompt)
    virtual = {
        paths["rule"].as_posix(): rule_raw,
        paths["prompt"].as_posix(): prompt_raw,
    }
    if historical_target:
        bootstrap = frozen_root_paths["bootstrap"]
        current = frozen_root_paths["current"]
        execution = frozen_root_paths["execution"]
        schemas = frozen_root_paths["schemas_and_validators"]
    else:
        bootstrap = frozen_root_paths["bootstrap"]
        current = frozen_root_paths["current"]
        # Publication projection changes after S4 and therefore cannot be a
        # runtime activation member. It remains an explicit package supplement.
        current.discard("release/current/manifest.json")
        current.update({paths["rule"].as_posix(), paths["prompt"].as_posix()})
        current.update(owner["path"] for owner in rule["owners"])
        current.update(
            {paths["profile"].as_posix(), paths["release_profile"].as_posix()}
        )
        current.update(_glob_files(f"{paths['root'].as_posix()}/contracts/*"))

        execution = set()
        for pattern in (
            "scripts/v250/*.py",
            "tests/v250/*.py",
            f"{paths['product_scripts'].as_posix()}/*.py",
            f"{paths['product_tests'].as_posix()}/*.py",
            f"{paths['compatibility'].as_posix()}/**/*",
            "subagents/goal-*.toml",
        ):
            execution.update(_glob_files(pattern))
        execution.update(
            {
                "scripts/check.sh",
                "scripts/checks/check-okf.py",
                "scripts/checks/check-package-manifest.py",
                "scripts/checks/check-v250.py",
                "scripts/checks/check.sh",
                "scripts/checks/run-v250-release-security-review.py",
                "scripts/checks/validate-v250-generation.py",
                "scripts/checks/validate-v250-test-gate.py",
                "scripts/checks/validate.py",
                "scripts/install-local.sh",
                "scripts/install/install-local.sh",
                "scripts/install/package-manifest.txt",
                "scripts/install/replay-package-manifest.txt",
                "scripts/release/build-release.py",
                "scripts/release/release_config.py",
                "scripts/release/skill_release.py",
                "scripts/release/validate-release.py",
                "subagents/common-developer-instructions.txt",
            }
        )
        schemas = {"schemas/release-engine-profile.schema.json"}
        schemas.update(_glob_files("schemas/v2.50/*.json"))
        schemas.update(
            _glob_files(f"{paths['product_schemas'].as_posix()}/*.json")
        )
    root_sets = {
        "bootstrap": [_member(relative, virtual) for relative in sorted(bootstrap)],
        "current": [_member(relative, virtual) for relative in sorted(current)],
        "execution": [_member(relative, virtual) for relative in sorted(execution - bootstrap)],
        "schemas_and_validators": [_member(relative, virtual) for relative in sorted(schemas)],
    }
    value["root_sets"] = root_sets
    value["rule_manifest_path"] = paths["rule"].as_posix()
    value["prompt_manifest_path"] = paths["prompt"].as_posix()

    owner_binding = sorted(
        ({"path": owner["path"], "sha256": owner["source_sha256"]} for owner in rule["owners"]),
        key=lambda item: item["path"],
    )
    value["semantic_owner_set_digest"] = _canonical_digest(owner_binding)
    value["rule_index_digest"] = _sha256(rule_raw)
    value["prompt_plan_digest"] = _sha256(prompt_raw)
    value["schema_and_validator_digest"] = _canonical_digest(root_sets["schemas_and_validators"])
    contract_entries = sorted(
        (
            item
            for item in root_sets["current"]
            if item["path"].startswith(paths["root"].as_posix() + "/contracts/")
            and item["path"].endswith(".json")
        ),
        key=lambda item: item["path"],
    )
    value["fixture_and_completion_contract_digest"] = _canonical_digest(contract_entries)
    value["projection_writer_allowlist"] = [WRITER]
    value["projection_writer_allowlist_digest"] = _canonical_digest([WRITER])
    replay = _load(REPLAY_PATH)
    value["optional_replay_allowlist_digest"] = replay["optional_replay_allowlist_digest"]
    value["legacy_classification"] = _legacy_classification(value, generation_id, predecessor)

    predecessor_activation = Path(
        f"references/current/generations/{predecessor}/activation-manifest.json"
    )
    predecessor_raw = (ROOT / predecessor_activation).read_bytes()
    predecessor_value = _load(predecessor_activation)
    value["rollback"] = {
        "activation_manifest_path": predecessor_activation.as_posix(),
        "activation_manifest_sha256": _sha256(predecessor_raw),
        "window_status": _predecessor_window_status(predecessor_value),
    }
    members = {
        item["path"] for entries in root_sets.values() for item in entries
    }
    allowlist = sorted(
        members | {ACTIVE_PATH.as_posix(), paths["activation"].as_posix()}
    )
    legacy = value["legacy_classification"]
    overlap = {
        member
        for member in members
        if member in set(legacy["exact_paths"])
        or any(member.startswith(prefix) for prefix in legacy["path_prefixes"])
    }
    if overlap:
        raise ValueError(f"Current and Legacy overlap: {sorted(overlap)}")
    value["current_default_allowlist"] = allowlist
    value["current_default_allowlist_digest"] = _canonical_digest(allowlist)
    selected_package_paths = _package_selected_paths(
        generation_id,
        frozen_package_activation if historical_target else value,
    )
    missing_package_paths = sorted(set(allowlist) - selected_package_paths)
    if missing_package_paths:
        raise ValueError(
            "activation allowlist is not selected by package manifest: "
            + ", ".join(missing_package_paths)
        )
    package_supplement = sorted(selected_package_paths - set(allowlist))
    value["package_supplement_allowlist"] = package_supplement
    value["package_supplement_allowlist_digest"] = _canonical_digest(
        package_supplement
    )
    payload = dict(value)
    payload.pop("manifest_payload_sha256", None)
    value["manifest_payload_sha256"] = _canonical_digest(payload)
    return value


def _active_value(
    paths: dict[str, Path],
    generation_id: str,
    activation_sha256: str,
    activated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-active-generation-v1",
        "generation_id": generation_id,
        "activation_manifest": paths["activation"].as_posix(),
        "activation_manifest_sha256": activation_sha256,
        "state": "active_current",
        "updated_at": activated_at,
    }


def _validate_activated_at(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("activated_at must be supplied explicitly")
    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        value,
    ):
        raise ValueError("activated_at must be an RFC 3339 date-time")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("activated_at must be an RFC 3339 date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("activated_at must include an explicit UTC offset")
    return value


def _validate_lock_timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or value > MAX_ACTIVE_LOCK_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "lock timeout must be a finite number from 0 through "
            f"{MAX_ACTIVE_LOCK_TIMEOUT_SECONDS:g} seconds"
        )
    return float(value)


def _exact_active_path(root: Path | None = None) -> Path:
    """Return the exact regular ACTIVE path without following path symlinks."""

    selected_root = ROOT if root is None else root
    try:
        root_path = selected_root.resolve(strict=True)
        relative_parent = ACTIVE_PATH.parent
        parent = (root_path / relative_parent).resolve(strict=True)
        parent.relative_to(root_path)
        lexical = parent / ACTIVE_PATH.name
        metadata = lexical.lstat()
    except (OSError, ValueError) as exc:
        raise ValueError("exact ACTIVE path is unsafe or unreadable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("exact ACTIVE path must be a regular file without symlinks")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ValueError("exact ACTIVE path is unsafe or unreadable") from exc
    if resolved != lexical:
        raise ValueError("exact ACTIVE path must not escape through symlinks")
    return lexical


def _active_lock_directory() -> Path:
    try:
        # Use one host-wide canonical root, independent of each process's
        # TMPDIR, so every process targeting the same physical ACTIVE path
        # computes the same lock location.
        temporary_root = Path("/tmp").resolve(strict=True)
    except OSError as exc:
        raise ValueError("ACTIVE lock temporary root is unsafe") from exc
    directory = temporary_root / f"goal-teams-active-locks-{os.getuid()}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ValueError("ACTIVE lock directory cannot be created") from exc
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise ValueError("ACTIVE lock directory is unsafe") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or directory.resolve(strict=True) != directory
    ):
        raise ValueError("ACTIVE lock directory is unsafe")
    return directory


def _active_lock_path(root: Path | None = None) -> Path:
    exact_active = _exact_active_path(root)
    lock_name = hashlib.sha256(os.fsencode(str(exact_active))).hexdigest() + ".lock"
    return _active_lock_directory() / lock_name


def _validate_lock_descriptor(
    descriptor: int, directory_descriptor: int, lock_name: str
) -> None:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(
            lock_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise ValueError("ACTIVE lock file is unsafe") from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or opened.st_dev != named.st_dev
        or opened.st_ino != named.st_ino
        or opened.st_uid != os.getuid()
        or opened.st_nlink != 1
        or stat.S_IMODE(opened.st_mode) != 0o600
    ):
        raise ValueError("ACTIVE lock file is unsafe")


@contextlib.contextmanager
def _active_writer_lock(timeout_seconds: float):
    """Hold one cross-process lock for the exact ACTIVE identity path."""

    timeout = _validate_lock_timeout(timeout_seconds)
    lock_path = _active_lock_path()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ValueError("ACTIVE lock requires no-follow file support")
    directory_descriptor = os.open(lock_path.parent, directory_flags | no_follow)
    descriptor: int | None = None
    acquired = False
    try:
        directory_metadata = os.fstat(directory_descriptor)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != os.getuid()
            or stat.S_IMODE(directory_metadata.st_mode) & 0o077
        ):
            raise ValueError("ACTIVE lock directory is unsafe")
        flags = os.O_CREAT | os.O_RDWR | no_follow
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(
                lock_path.name,
                flags,
                0o600,
                dir_fd=directory_descriptor,
            )
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise ValueError("ACTIVE lock file is unsafe") from exc
            raise ValueError("ACTIVE lock file cannot be opened safely") from exc
        _validate_lock_descriptor(descriptor, directory_descriptor, lock_path.name)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"ACTIVE lock timeout after {timeout:g} seconds"
                    ) from exc
                time.sleep(min(0.05, remaining))
        # Revalidate both the exact pointer and the lock inode after waiting.
        _exact_active_path()
        _validate_lock_descriptor(descriptor, directory_descriptor, lock_path.name)
        yield lock_path
    finally:
        if descriptor is not None:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        os.close(directory_descriptor)


def _validate_base(
    expected_activation_digest: str | None,
    expected_active_digest: str | None = None,
    expected_generation_id: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    try:
        active_raw = _exact_active_path().read_bytes()
        active = json.loads(active_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("current ACTIVE identity is unreadable") from exc
    if not isinstance(active, dict):
        raise ValueError("current ACTIVE identity is invalid")
    observed_active_digest = _sha256(active_raw)
    if (
        expected_active_digest is not None
        and observed_active_digest != expected_active_digest
    ):
        raise ValueError("raw ACTIVE CAS mismatch")
    activation_path = active.get("activation_manifest")
    recorded = active.get("activation_manifest_sha256")
    generation_id = active.get("generation_id")
    if (
        set(active)
        != {
            "schema_version",
            "generation_id",
            "activation_manifest",
            "activation_manifest_sha256",
            "state",
            "updated_at",
        }
        or active.get("schema_version") != "goal-teams-active-generation-v1"
        or active.get("state") != "active_current"
        or not isinstance(generation_id, str)
        or not generation_id.startswith("V")
        or generation_id.count(".") != 1
        or (
            expected_generation_id is not None
            and generation_id != expected_generation_id
        )
        or not isinstance(activation_path, str)
        or activation_path
        != f"references/current/generations/{generation_id}/activation-manifest.json"
        or not isinstance(recorded, str)
        or not re.fullmatch(r"[0-9a-f]{64}", recorded)
    ):
        raise ValueError("current ACTIVE identity is invalid")
    _validate_activated_at(active.get("updated_at"))
    activation_raw = (ROOT / _safe_relative(activation_path)).read_bytes()
    observed = _sha256(activation_raw)
    if observed != recorded:
        raise ValueError("current ACTIVE activation digest does not match disk")
    try:
        activation = json.loads(activation_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("current ACTIVE activation is invalid") from exc
    if (
        not isinstance(activation, dict)
        or activation.get("schema_version")
        != "goal-teams-activation-manifest-v2.50"
        or activation.get("generation_id") != generation_id
        or activation.get("generation_state") != "active"
    ):
        raise ValueError("current ACTIVE activation semantics are inconsistent")
    if (
        expected_activation_digest is not None
        and recorded != expected_activation_digest
    ):
        raise ValueError("base activation CAS mismatch")
    return active, active_raw


def _atomic_write(relative: Path, raw: bytes) -> None:
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.stage-", delete=False
    ) as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
        staged = Path(handle.name)
    try:
        json.loads(staged.read_text(encoding="utf-8"))
        os.replace(staged, target)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(target.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        staged.unlink(missing_ok=True)


def _rollback_active_if_unchanged(written_raw: bytes, previous_raw: bytes) -> None:
    """Rollback only our exact pointer bytes; never overwrite a newer writer."""

    current_raw = _exact_active_path().read_bytes()
    if current_raw != written_raw:
        raise RuntimeError(
            "ACTIVE rollback conflict: current pointer is not this writer's bytes; "
            "concurrent state was preserved"
        )
    _atomic_write(ACTIVE_PATH, previous_raw)
    if _exact_active_path().read_bytes() != previous_raw:
        raise RuntimeError("ACTIVE rollback readback failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--prepare-active", action="store_true")
    mode.add_argument("--activate", action="store_true")
    mode.add_argument("--refresh-active", action="store_true")
    parser.add_argument("--generation-id", default=(ROOT / "VERSION").read_text().strip())
    parser.add_argument("--predecessor", default="V2.62")
    parser.add_argument("--base-activation-sha256")
    parser.add_argument("--base-active-sha256")
    parser.add_argument("--expected-prepared-activation-sha256")
    parser.add_argument("--activated-at")
    parser.add_argument(
        "--lock-timeout-seconds",
        type=float,
        default=DEFAULT_ACTIVE_LOCK_TIMEOUT_SECONDS,
        help=(
            "maximum seconds to wait for the exact ACTIVE writer lock "
            f"(default: {DEFAULT_ACTIVE_LOCK_TIMEOUT_SECONDS:g})"
        ),
    )
    parser.add_argument(
        "--check-state",
        choices=("inactive_candidate", "active"),
        default="inactive_candidate",
    )
    args = parser.parse_args()
    try:
        args.lock_timeout_seconds = _validate_lock_timeout(args.lock_timeout_seconds)
    except ValueError as exc:
        parser.error(str(exc))
    if (
        args.write
        or args.prepare_active
        or args.activate
        or args.refresh_active
    ) and not args.base_activation_sha256:
        parser.error("writer modes require --base-activation-sha256")
    if (
        args.prepare_active or args.activate or args.refresh_active
    ) and not args.base_active_sha256:
        parser.error("active writer modes require --base-active-sha256")
    if args.activate and not args.expected_prepared_activation_sha256:
        parser.error("--activate requires --expected-prepared-activation-sha256")
    if args.activate and not args.activated_at:
        parser.error("--activate requires --activated-at")
    if args.refresh_active and not args.activated_at:
        parser.error("--refresh-active requires --activated-at")
    if not args.check and args.check_state != "inactive_candidate":
        parser.error("--check-state is valid only with --check")

    paths = _generation_paths(args.generation_id)

    # Every manifest writer shares the same lock because candidate/prepared
    # output is derived from ACTIVE and may otherwise race an activation.
    # Read-only checks deliberately do not serialize writers.
    if args.write or args.prepare_active or args.activate or args.refresh_active:
        with _active_writer_lock(args.lock_timeout_seconds):
            return _run_locked(args, paths)
    return _run_locked(args, paths)


def _derive_projection(
    paths: dict[str, Path],
    *,
    generation_id: str,
    predecessor: str,
    state: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    rule = _refreshed_rule_manifest(paths, generation_id)
    prompt = _refreshed_prompt_manifest(paths, generation_id)
    if generation_id in {"V2.63", "V2.65"}:
        from scripts.v250.semantic_closure import validate_route_controls

        for route in prompt["routes"].values():
            workflow_phase = route.get("workflow_phase")
            semantic_phase = (
                "development" if workflow_phase == "startup" else workflow_phase
            )
            controls = validate_route_controls(
                {
                    "workflow_phase": semantic_phase,
                    "required_gates": route.get("required_gates", []),
                    "conditional_gates": route.get("conditional_gates", []),
                }
            )
            route["required_gates"] = controls["required_gates"]
            route["conditional_gates"] = controls["conditional_gates"]
    prompt["manifest_state"] = (
        "active_current" if state == "active" else "inactive_candidate"
    )
    activation = _refreshed_activation(
        paths, generation_id, predecessor, state, rule, prompt
    )
    return rule, prompt, activation


def _run_locked(args: argparse.Namespace, paths: dict[str, Path]) -> int:
    """Execute after writer modes have acquired the exact ACTIVE lock."""

    if args.refresh_active:
        activated_at = _validate_activated_at(args.activated_at)
        _current, active_raw_before = _validate_base(
            args.base_activation_sha256,
            args.base_active_sha256,
            args.generation_id,
        )
        existing_activation = _load(paths["activation"])
        if existing_activation.get("baseline_generation_id") != args.predecessor:
            raise ValueError("active refresh predecessor differs")
        rule, prompt, activation = _derive_projection(
            paths,
            generation_id=args.generation_id,
            predecessor=args.predecessor,
            state="active",
        )
        expected = {
            paths["rule"]: rule,
            paths["prompt"]: prompt,
            paths["activation"]: activation,
        }
        drift = [
            relative.as_posix()
            for relative, value in expected.items()
            if _load(relative) != value
        ]
        _current_again, active_raw_after = _validate_base(
            args.base_activation_sha256,
            args.base_active_sha256,
            args.generation_id,
        )
        if active_raw_after != active_raw_before:
            raise ValueError("raw ACTIVE changed during active refresh")
        previous_projection = {
            relative: (ROOT / relative).read_bytes() for relative in expected
        }
        activation_raw = _json_bytes(activation)
        activation_digest = _sha256(activation_raw)
        active = _active_value(
            paths, args.generation_id, activation_digest, activated_at
        )
        written_active_raw = _json_bytes(active)
        pointer_written = False
        try:
            for relative, value in expected.items():
                _atomic_write(relative, _json_bytes(value))
            from scripts.v250.generation_runtime import (
                load_generation,
                load_prepared_generation,
            )

            load_prepared_generation(
                ROOT,
                generation_id=args.generation_id,
                activation_manifest_path=paths["activation"].as_posix(),
                expected_activation_sha256=activation_digest,
            )
            _atomic_write(ACTIVE_PATH, written_active_raw)
            pointer_written = True
            loaded = load_generation(ROOT)
            if (
                _exact_active_path().read_bytes() != written_active_raw
                or loaded.get("generation_id") != args.generation_id
                or loaded.get("activation_manifest_sha256") != activation_digest
                or loaded.get("selection_mode") != "active_pointer"
                or loaded.get("selected_via_active_pointer") is not True
            ):
                raise ValueError("refreshed active generation readback mismatch")
        except Exception:
            if pointer_written:
                _rollback_active_if_unchanged(
                    written_active_raw, active_raw_before
                )
            for relative, raw in previous_projection.items():
                _atomic_write(relative, raw)
            if _exact_active_path().read_bytes() != active_raw_before:
                raise RuntimeError("active refresh rollback readback failed")
            raise
        print(
            json.dumps(
                {
                    "ok": True,
                    "generation_id": args.generation_id,
                    "generation_state": "active",
                    "updated": drift,
                    "active_updated": True,
                    "activation_manifest_sha256": activation_digest,
                    "base_active_sha256": args.base_active_sha256,
                    "base_activation_sha256": args.base_activation_sha256,
                    "activated_at": activated_at,
                },
                ensure_ascii=False,
            )
        )
        return 0

    # Activation is deliberately pointer-only.  It does not refresh or rewrite
    # the prepared rule, prompt, or activation manifest.
    if args.activate:
        activated_at = _validate_activated_at(args.activated_at)
        _base, active_raw_before = _validate_base(
            args.base_activation_sha256,
            args.base_active_sha256,
            args.predecessor,
        )
        prepared_raw = (ROOT / paths["activation"]).read_bytes()
        prepared_digest = _sha256(prepared_raw)
        if prepared_digest != args.expected_prepared_activation_sha256:
            raise ValueError("prepared activation CAS mismatch")

        from scripts.v250.generation_runtime import load_prepared_generation

        load_prepared_generation(
            ROOT,
            generation_id=args.generation_id,
            activation_manifest_path=paths["activation"].as_posix(),
            expected_activation_sha256=prepared_digest,
        )
        _current, active_raw_after = _validate_base(
            args.base_activation_sha256,
            args.base_active_sha256,
            args.predecessor,
        )
        if active_raw_after != active_raw_before:
            raise ValueError("raw ACTIVE changed during pointer activation")
        # Verify the exact prepared member closure once more immediately before
        # the pointer write, after the second base-pointer CAS.
        load_prepared_generation(
            ROOT,
            generation_id=args.generation_id,
            activation_manifest_path=paths["activation"].as_posix(),
            expected_activation_sha256=prepared_digest,
        )
        active = _active_value(
            paths,
            args.generation_id,
            prepared_digest,
            activated_at,
        )
        written_raw = _json_bytes(active)
        try:
            _atomic_write(ACTIVE_PATH, written_raw)
            from scripts.v250.generation_runtime import load_generation

            loaded = load_generation(ROOT)
            if (
                _exact_active_path().read_bytes() != written_raw
                or loaded.get("generation_id") != args.generation_id
                or loaded.get("activation_manifest_sha256") != prepared_digest
                or loaded.get("selection_mode") != "active_pointer"
                or loaded.get("selected_via_active_pointer") is not True
            ):
                raise ValueError("activated generation exact readback mismatch")
        except Exception:
            _rollback_active_if_unchanged(written_raw, active_raw_before)
            raise
        print(
            json.dumps(
                {
                    "ok": True,
                    "generation_id": args.generation_id,
                    "generation_state": "active",
                    "updated": [],
                    "active_updated": True,
                    "activation_manifest_sha256": prepared_digest,
                    "base_active_sha256": args.base_active_sha256,
                    "base_activation_sha256": args.base_activation_sha256,
                    "activated_at": activated_at,
                },
                ensure_ascii=False,
            )
        )
        return 0

    expected_base_generation = (
        args.generation_id
        if args.check and args.check_state == "active"
        else args.predecessor
    )
    _before, _active_raw = _validate_base(
        args.base_activation_sha256,
        args.base_active_sha256 if args.prepare_active else None,
        expected_base_generation,
    )
    state = (
        "active"
        if args.prepare_active or (args.check and args.check_state == "active")
        else "inactive_candidate"
    )
    rule, prompt, activation = _derive_projection(
        paths,
        generation_id=args.generation_id,
        predecessor=args.predecessor,
        state=state,
    )
    expected = {
        paths["rule"]: rule,
        paths["prompt"]: prompt,
        paths["activation"]: activation,
    }
    drift = [
        relative.as_posix()
        for relative, value in expected.items()
        if _load(relative) != value
    ]
    if args.check:
        print(json.dumps({"ok": not drift, "drift": drift, "active_unchanged": True}, ensure_ascii=False))
        return 0 if not drift else 1

    for relative, value in expected.items():
        _atomic_write(relative, _json_bytes(value))
    print(
        json.dumps(
            {
                "ok": True,
                "generation_id": args.generation_id,
                "generation_state": state,
                "updated": drift,
                "active_updated": False,
                "activation_manifest_sha256": _sha256(_json_bytes(activation)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
