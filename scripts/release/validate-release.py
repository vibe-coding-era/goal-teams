#!/usr/bin/env python3
"""Validate local release snapshots before GitHub publication."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath

SOURCE_ROOT = Path(__file__).resolve().parents[2]

_SAFE_GIT_ENV = {
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_TERMINAL_PROMPT": "0",
}
_INERT_GIT_ENV = frozenset({"GIT_PAGER"})


class V240GitTrustError(RuntimeError):
    """Reject a caller-controlled or incomplete Git object graph."""

    def __init__(self, message: str) -> None:
        self.receipt = {
            "passed": False,
            "error_code": "E_V240_GIT_OBJECT_GRAPH",
            "mutation_count": 0,
            "external_side_effect_count": 0,
        }
        super().__init__(f"E_V240_GIT_OBJECT_GRAPH: {message}")


def _git_environment() -> dict[str, str]:
    """Return a closed Git environment after rejecting redirection inputs."""

    poisoned = sorted(
        key
        for key, value in os.environ.items()
        if key.startswith("GIT_")
        and key not in _INERT_GIT_ENV
        and (key not in _SAFE_GIT_ENV or value != _SAFE_GIT_ENV[key])
    )
    if poisoned:
        raise V240GitTrustError(
            "caller-controlled Git environment is forbidden: "
            + ",".join(poisoned)
        )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(_SAFE_GIT_ENV)
    environment.update({"LC_ALL": "C", "LANG": "C"})
    return environment


def _run_git(
    *args: str,
    text: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    """Run one fixed Git command with replace objects and lazy fetch disabled."""

    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=SOURCE_ROOT,
        check=False,
        capture_output=True,
        text=text,
        env=_git_environment(),
    )
    if check and result.returncode != 0:
        result.check_returncode()
    return result


def _resolve_git_admin_path(value: str) -> Path:
    if not value:
        raise V240GitTrustError("Git administrative path is empty")
    path = Path(value)
    if not path.is_absolute():
        path = SOURCE_ROOT / path
    return path.resolve()


def _assert_trusted_git_repository() -> None:
    """Reject object substitution, omission, and external object sources."""

    git_dir_result = _run_git("rev-parse", "--git-dir", text=True)
    common_result = _run_git("rev-parse", "--git-common-dir", text=True)
    assert isinstance(git_dir_result.stdout, str)
    assert isinstance(common_result.stdout, str)
    git_dir = _resolve_git_admin_path(git_dir_result.stdout.strip())
    common_dir = _resolve_git_admin_path(common_result.stdout.strip())

    replacements = _run_git(
        "for-each-ref",
        "--format=%(refname)",
        "refs/replace/",
        text=True,
    )
    assert isinstance(replacements.stdout, str)
    if replacements.stdout.strip():
        raise V240GitTrustError("Git replacement refs are forbidden")

    for administrative_root in {git_dir, common_dir}:
        forbidden_paths = (
            administrative_root / "info" / "grafts",
            administrative_root / "objects" / "info" / "alternates",
            administrative_root / "objects" / "info" / "http-alternates",
            administrative_root / "shallow",
            administrative_root / "shallow.lock",
        )
        if any(path.exists() or path.is_symlink() for path in forbidden_paths):
            raise V240GitTrustError(
                "Git graft, alternate, or shallow object source exists"
            )
        pack_root = administrative_root / "objects" / "pack"
        if pack_root.is_dir() and any(pack_root.glob("*.promisor")):
            raise V240GitTrustError("partial-clone promisor pack exists")

    shallow = _run_git("rev-parse", "--is-shallow-repository", text=True)
    assert isinstance(shallow.stdout, str)
    if shallow.stdout.strip() != "false":
        raise V240GitTrustError("shallow repositories are forbidden")

    configuration = _run_git(
        "config",
        "--local",
        "--includes",
        "--name-only",
        "--list",
        text=True,
    )
    assert isinstance(configuration.stdout, str)
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
        raise V240GitTrustError("partial-clone configuration is forbidden")


def workspace_root() -> Path:
    try:
        result = _run_git("rev-parse", "--git-common-dir", text=True, check=False)
    except OSError:
        return SOURCE_ROOT
    # The strict four-column parser is part of Gitless package tests; live
    # release validation still requires Git to derive the frozen-source
    # expected payload map used for same-built-asset integrity checks.
    if result.returncode != 0:
        return SOURCE_ROOT
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = (SOURCE_ROOT / common).resolve()
    return common.parent


WORKSPACE_ROOT = workspace_root()
RELEASE_ROOT = WORKSPACE_ROOT / "release" / "versions"
META = {"_release.json", "_files.sha256", "_artifacts/SHA256SUMS"}
OKF_GENERATED_PATH = "references/okf-conformance-manifest.json"
OKF_RELEASE_VERSIONS = {"V2.39", "V2.40", "V2.44", "V2.45", "V2.46", "V2.48", "V2.49", "V2.50", "V2.52", "V2.6", "V2.62", "V2.63", "V2.65"}
STRICT_SNAPSHOT_SCHEMA = "goal-teams-release-snapshot-v2.40"
STRICT_SNAPSHOT_VERSIONS = {"V2.40", "V2.44", "V2.45", "V2.46", "V2.48", "V2.49", "V2.50", "V2.52", "V2.6", "V2.62", "V2.63", "V2.65"}
SUPPORTED_RELEASE_VERSIONS = {
    "V2.33", "V2.34", "V2.35", "V2.36", "V2.37", "V2.38", "V2.39",
    "V2.40", "V2.44", "V2.45", "V2.46", "V2.48", "V2.49", "V2.50", "V2.52", "V2.6", "V2.62", "V2.63", "V2.65",
}
MAX_TAR_MEMBERS = 2048
MAX_TAR_PATH_BYTES = 240
MAX_TAR_SINGLE_FILE_BYTES = 16 * 1024 * 1024
MAX_TAR_TOTAL_BYTES = 128 * 1024 * 1024
MAX_TAR_COMPRESSION_RATIO = 100
V263_PREDECESSOR_IDENTITY_PATH = Path(
    "references/current/generations/V2.63/contracts/"
    "predecessor-release-identity.json"
)
V263_PREDECESSOR_IDENTITY_SHA256 = (
    "e48e3b6ea14a95bfe83e82ac37ee1ce2260cf27cd9313724cbbd39445ee70295"
)
V265_PREDECESSOR_IDENTITY_PATH = Path(
    "references/current/generations/V2.65/contracts/"
    "predecessor-release-identity.json"
)
V265_PREDECESSOR_IDENTITY_SHA256 = (
    "b22f4ba29a5d3357c700b1920b3f6dd5e269d8c9c5b44b6d2064389c33b6fdff"
)


class V240FilesManifestError(RuntimeError):
    """A stable, zero-effect receipt for malformed V2.40 file manifests."""

    def __init__(self, message: str) -> None:
        self.receipt = {
            "passed": False,
            "error_code": "E_V240_FILES_MANIFEST_COLUMNS",
            "mutation_count": 0,
            "external_side_effect_count": 0,
        }
        super().__init__(f"E_V240_FILES_MANIFEST_COLUMNS: {message}")


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _v263_predecessor_release_identity() -> dict[str, object] | None:
    path = SOURCE_ROOT / V263_PREDECESSOR_IDENTITY_PATH
    if path.is_symlink() or not path.is_file():
        return None
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(contract, dict)
        or set(contract)
        != {
            "schema_version",
            "generation_id",
            "predecessor_product_version",
            "release_identity",
            "release_identity_sha256",
        }
        or contract.get("schema_version")
        != "goal-teams-predecessor-release-identity-v2.63"
        or contract.get("generation_id") != "V2.63"
        or contract.get("predecessor_product_version") != "V2.62"
        or contract.get("release_identity_sha256")
        != V263_PREDECESSOR_IDENTITY_SHA256
        or _canonical_json_sha256(contract.get("release_identity"))
        != V263_PREDECESSOR_IDENTITY_SHA256
    ):
        return None
    identity = contract.get("release_identity")
    return dict(identity) if isinstance(identity, dict) else None


def _v263_published_identity_valid(
    identity: object,
    version: str,
    *,
    exact_identity: dict[str, object] | None = None,
) -> bool:
    expected_assets = [
        f"goal-teams-{version}.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    ]
    return bool(
        isinstance(identity, dict)
        and set(identity)
        == {
            "tag",
            "release_id",
            "state",
            "source_commit",
            "source_tree",
            "public_assets",
        }
        and identity.get("tag") == version.lower()
        and identity.get("state") == "published"
        and not isinstance(identity.get("release_id"), bool)
        and isinstance(identity.get("release_id"), int)
        and identity["release_id"] > 0
        and re.fullmatch(
            r"[0-9a-f]{40}", str(identity.get("source_commit", ""))
        )
        is not None
        and re.fullmatch(
            r"[0-9a-f]{40}", str(identity.get("source_tree", ""))
        )
        is not None
        and identity.get("public_assets") == expected_assets
        and (exact_identity is None or identity == exact_identity)
    )


def _v265_predecessor_release_identity() -> dict[str, object] | None:
    path = SOURCE_ROOT / V265_PREDECESSOR_IDENTITY_PATH
    if path.is_symlink() or not path.is_file():
        return None
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(contract, dict)
        or contract.get("schema_version")
        != "goal-teams-predecessor-release-identity-v2.65"
        or contract.get("generation_id") != "V2.65"
        or contract.get("predecessor_product_version") != "V2.63"
        or contract.get("release_identity_sha256")
        != V265_PREDECESSOR_IDENTITY_SHA256
        or _canonical_json_sha256(contract.get("release_identity"))
        != V265_PREDECESSOR_IDENTITY_SHA256
    ):
        return None
    identity = contract.get("release_identity")
    return dict(identity) if isinstance(identity, dict) else None


def release_projection_state(
    version: str,
    current: object,
    *,
    allow_candidate: bool,
) -> str:
    """Distinguish a published projection from an isolated candidate."""

    if not isinstance(current, dict) or current.get("status") != "release":
        return "invalid"
    if version == "V2.65":
        candidate_keys = {
            key for key in current if str(key).startswith("candidate_")
        }
        if current.get("product_version") == "V2.65":
            if (
                current.get("schema_version")
                != "goal-teams-release-manifest-v2.65"
                or current.get("core_policy_version") != "V2.5"
                or current.get("legacy_data_schema_version") != "V2.3"
                or candidate_keys
                or not _v263_published_identity_valid(
                    current.get("release_identity"), "V2.65"
                )
            ):
                return "invalid"
            return "final"
        predecessor_identity = _v265_predecessor_release_identity()
        expected_candidate_keys = {
            "candidate_product_version",
            "candidate_release_state",
            "candidate_profile",
        }
        if (
            allow_candidate
            and current.get("product_version") == "V2.63"
            and current.get("schema_version")
            == "goal-teams-release-manifest-v2.63"
            and current.get("core_policy_version") == "V2.5"
            and current.get("legacy_data_schema_version") == "V2.3"
            and candidate_keys == expected_candidate_keys
            and current.get("candidate_product_version") == "V2.65"
            and current.get("candidate_release_state")
            in {"development_candidate_not_published", "v250_release_readiness"}
            and current.get("candidate_profile")
            == "references/release-profiles/v2.65.json"
            and predecessor_identity is not None
            and _v263_published_identity_valid(
                current.get("release_identity"),
                "V2.63",
                exact_identity=predecessor_identity,
            )
        ):
            return "candidate"
        return "invalid"
    if version == "V2.63":
        candidate_keys = {
            key for key in current if str(key).startswith("candidate_")
        }
        if current.get("product_version") == "V2.63":
            if (
                current.get("schema_version")
                != "goal-teams-release-manifest-v2.63"
                or current.get("core_policy_version") != "V2.5"
                or current.get("legacy_data_schema_version") != "V2.3"
                or candidate_keys
                or not _v263_published_identity_valid(
                    current.get("release_identity"), "V2.63"
                )
            ):
                return "invalid"
            return "final"
        expected_candidate_keys = {
            "candidate_product_version",
            "candidate_release_state",
            "candidate_profile",
        }
        predecessor_identity = _v263_predecessor_release_identity()
        if (
            allow_candidate
            and current.get("product_version") == "V2.62"
            and current.get("schema_version")
            == "goal-teams-release-manifest-v2.62"
            and current.get("core_policy_version") == "V2.5"
            and current.get("legacy_data_schema_version") == "V2.3"
            and candidate_keys == expected_candidate_keys
            and current.get("candidate_product_version") == "V2.63"
            and current.get("candidate_release_state")
            in {"development_candidate_not_published", "v250_release_readiness"}
            and current.get("candidate_profile")
            == "references/release-profiles/v2.63.json"
            and predecessor_identity is not None
            and _v263_published_identity_valid(
                current.get("release_identity"),
                "V2.62",
                exact_identity=predecessor_identity,
            )
        ):
            return "candidate"
        return "invalid"
    if current.get("product_version") == version:
        return "final"
    candidate_predecessors = {
        "V2.48": "V2.46",
        "V2.49": "V2.48",
        "V2.50": "V2.48",
        "V2.52": "V2.51",
        "V2.6": "V2.52",
        "V2.62": "V2.6",
        "V2.65": "V2.63",
    }
    candidate_states = {
        "V2.48": {"skill_simple_local_validation"},
        "V2.49": {
            "skill_simple_local_validation",
            "v249_release_readiness",
        },
        "V2.50": {"v250_release_readiness"},
        "V2.52": {"v250_release_readiness"},
        "V2.6": {"v250_release_readiness"},
        "V2.62": {"v250_release_readiness"},
        "V2.65": {"v250_release_readiness"},
    }
    if (
        allow_candidate
        and version in candidate_predecessors
        and current.get("product_version") == candidate_predecessors[version]
        and current.get("candidate_product_version") == version
        and current.get("candidate_release_state") in candidate_states[version]
    ):
        return "candidate"
    return "invalid"


def validate_v248_release_identity(
    expected: object, observed: object
) -> dict[str, object]:
    """Compare the exact V2.48 candidate/package identity."""

    required = {
        "version", "source_commit", "source_tree",
        "profile_sha256", "asset_set_digest",
    }
    if (
        not isinstance(expected, dict)
        or not isinstance(observed, dict)
        or set(expected) != required
        or set(observed) != required
        or expected.get("version") != "V2.48"
        or observed != expected
    ):
        return {
            "ok": False,
            "passed": False,
            "error_code": "E_V248_RELEASE_IDENTITY_DRIFT",
            "mutation_count": 0,
            "external_mutation_count": 0,
            "external_side_effect_count": 0,
        }
    return {
        "ok": True,
        "passed": True,
        "error_code": None,
        "identity_sha256": hashlib.sha256(
            json.dumps(
                expected, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "mutation_count": 0,
        "external_mutation_count": 0,
        "external_side_effect_count": 0,
    }


def validate_v249_release_identity(
    expected: object, observed: object
) -> dict[str, object]:
    """Compare an exact V2.49 released identity and its single asset set."""

    required = {
        "version",
        "source_commit",
        "source_tree",
        "profile_sha256",
        "asset_set_digest",
        "asset_set_id",
    }
    if (
        not isinstance(expected, dict)
        or not isinstance(observed, dict)
        or set(expected) != required
        or set(observed) != required
        or expected.get("version") != "V2.49"
        or observed != expected
    ):
        return {
            "ok": False,
            "passed": False,
            "error_code": "E_V249_RELEASE_IDENTITY_DRIFT",
            "mutation_count": 0,
            "external_mutation_count": 0,
            "external_side_effect_count": 0,
        }
    return {
        "ok": True,
        "passed": True,
        "error_code": None,
        "identity_sha256": hashlib.sha256(
            json.dumps(
                expected, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "mutation_count": 0,
        "external_mutation_count": 0,
        "external_side_effect_count": 0,
    }


def validate_v250_release_identity(
    expected: object, observed: object
) -> dict[str, object]:
    """Compare an exact v2.50 execution-layer released identity and asset set."""

    required = {
        "version",
        "source_commit",
        "source_tree",
        "profile_sha256",
        "asset_set_digest",
        "asset_set_id",
    }
    if (
        not isinstance(expected, dict)
        or not isinstance(observed, dict)
        or set(expected) != required
        or set(observed) != required
        or expected.get("version") not in {"V2.50", "V2.52", "V2.6", "V2.62", "V2.63", "V2.65"}
        or observed != expected
    ):
        return {
            "ok": False,
            "passed": False,
            "error_code": "E_V250_RELEASE_IDENTITY_DRIFT",
            "mutation_count": 0,
            "external_mutation_count": 0,
            "external_side_effect_count": 0,
        }
    return {
        "ok": True,
        "passed": True,
        "error_code": None,
        "identity_sha256": hashlib.sha256(
            json.dumps(
                expected, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        "mutation_count": 0,
        "external_mutation_count": 0,
        "external_side_effect_count": 0,
    }


def parse_v240_files_manifest(content: str) -> list[dict[str, object]]:
    """Parse the strict four-column V2.40 checksum/mode/size/path contract."""

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(content.splitlines(), start=1):
        fields = line.split("\t")
        if len(fields) != 4:
            raise V240FilesManifestError(f"line {line_number} must have four tab columns")
        expected_hash, expected_mode, expected_size_raw, relative = fields
        if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            raise V240FilesManifestError(f"line {line_number} has an invalid sha256")
        if expected_mode not in {"100644", "100755"}:
            raise V240FilesManifestError(f"line {line_number} has an invalid mode")
        if re.fullmatch(r"0|[1-9][0-9]*", expected_size_raw) is None:
            raise V240FilesManifestError(f"line {line_number} has an invalid size")
        try:
            relative = safe_manifest_path(relative)
        except RuntimeError as exc:
            raise V240FilesManifestError(str(exc)) from exc
        if relative in seen:
            raise V240FilesManifestError(f"duplicate path: {relative}")
        seen.add(relative)
        rows.append(
            {
                "sha256": expected_hash,
                "mode": expected_mode,
                "size": int(expected_size_raw),
                "path": relative,
            }
        )
    return rows


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_safe_tar(artifact: Path, version: str) -> list[tuple[str, str]]:
    """Preflight every member before callers trust archive contents."""

    prefix = f"goal-teams-{version}/"
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    total = 0
    with tarfile.open(artifact, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > MAX_TAR_MEMBERS:
            raise RuntimeError("tar member limit exceeded")
        for member in members:
            if not member.isfile() or member.issym() or member.islnk():
                raise RuntimeError(f"unsafe tar member type: {member.name}")
            if "path" in member.pax_headers or "linkpath" in member.pax_headers:
                raise RuntimeError(f"tar PAX path override: {member.name}")
            normalized = unicodedata.normalize("NFC", member.name)
            if normalized != member.name:
                raise RuntimeError(f"tar path is not NFC: {member.name}")
            if (
                "\\" in normalized
                or "\x00" in normalized
                or not normalized.startswith(prefix)
                or PurePosixPath(normalized).is_absolute()
                or any(part in {"", ".", ".."} for part in PurePosixPath(normalized).parts)
            ):
                raise RuntimeError(f"unsafe tar path: {member.name}")
            if len(normalized.encode("utf-8")) > MAX_TAR_PATH_BYTES:
                raise RuntimeError(f"tar path limit exceeded: {member.name}")
            identity = normalized.casefold()
            if identity in seen:
                raise RuntimeError(f"duplicate tar path: {member.name}")
            seen.add(identity)
            if member.size > MAX_TAR_SINGLE_FILE_BYTES:
                raise RuntimeError(f"tar single-file limit exceeded: {member.name}")
            total += member.size
            if total > MAX_TAR_TOTAL_BYTES:
                raise RuntimeError("tar total uncompressed limit exceeded")
            rows.append((member.name, normalized[len(prefix) :]))
        compressed = max(artifact.stat().st_size, 1)
        if total / compressed > MAX_TAR_COMPRESSION_RATIO:
            raise RuntimeError("tar compression-ratio limit exceeded")
    return rows


def git_bytes(*args: str) -> bytes:
    _assert_trusted_git_repository()
    result = _run_git(*args)
    assert isinstance(result.stdout, bytes)
    return result.stdout


def source_entries(commit: str) -> dict[str, tuple[str, bytes]]:
    result: dict[str, tuple[str, bytes]] = {}
    for raw in git_bytes("ls-tree", "-r", "-z", commit).split(b"\0"):
        if not raw:
            continue
        metadata, path_raw = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        if kind == "blob":
            result[path_raw.decode()] = (mode, git_bytes("cat-file", "blob", object_id))
    return result


def excluded(path: str) -> bool:
    return path.startswith(("docs/", "develops/", "GoalTeamsWork-", "GoalTeams-PRD-", "outputs/", ".goalteams-", ".codex/"))


def safe_manifest_path(value: str) -> str:
    normalized = value.rstrip("/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\\" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RuntimeError(f"unsafe source manifest path: {value}")
    return normalized


def trusted_release_files(
    commit: str,
) -> tuple[dict[str, tuple[str, bytes]], set[str], str]:
    entries = source_entries(commit)
    manifest = entries["scripts/install/package-manifest.txt"][1]
    exact: set[str] = set()
    prefixes: list[str] = []
    generated: set[str] = set()
    for raw in manifest.decode().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, value = line.split(maxsplit=1)
        if kind == "file" and not value.endswith("/"):
            exact.add(safe_manifest_path(value))
        elif kind == "prefix" and value.endswith("/"):
            safe_manifest_path(value)
            prefixes.append(value)
        elif kind == "generated" and not value.endswith("/"):
            generated.add(safe_manifest_path(value))
        else:
            raise RuntimeError(f"invalid source manifest rule: {line}")
    if generated and generated != {OKF_GENERATED_PATH}:
        raise RuntimeError(f"unsupported builder-generated assets: {sorted(generated)}")
    tracked_generated = generated & set(entries)
    if tracked_generated:
        raise RuntimeError(
            f"builder-generated assets are tracked in source: {sorted(tracked_generated)}"
        )
    selected = {p: entries[p] for p in entries if (p in exact or any(p.startswith(x) for x in prefixes)) and not excluded(p)}
    return selected, generated, hashlib.sha256(manifest).hexdigest()


def git_text(*args: str) -> str:
    _assert_trusted_git_repository()
    result = _run_git(*args, text=True)
    assert isinstance(result.stdout, str)
    return result.stdout.strip()


def write_expected_file(root: Path, relative: str, mode: str, data: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o755 if mode == "100755" else 0o644)


def okf_runtime_generation(version: str) -> str:
    """Return the packaged OKF runtime generation for a release version."""

    return "v250" if version in {"V2.50", "V2.52", "V2.6", "V2.62", "V2.63", "V2.65"} else "v249"


def materialize_expected_payload_map(
    commit: str,
) -> tuple[dict[str, tuple[str, bytes]], set[str], str, dict[str, object] | None]:
    """Derive the expected payload map for same-built-asset integrity checks.

    This function does not create a release archive or a second public asset
    set.  It materializes only a temporary validation tree and therefore makes
    no reproducibility claim.
    """

    trusted, generated, manifest_sha = trusted_release_files(commit)
    source_version = trusted.get("VERSION", ("", b""))[1].decode("utf-8").strip()
    if source_version in OKF_RELEASE_VERSIONS and generated != {OKF_GENERATED_PATH}:
        raise RuntimeError(
            f"{source_version} source does not require the canonical generated manifest"
        )
    if not generated:
        return trusted, generated, manifest_sha, None
    with tempfile.TemporaryDirectory(prefix="goal-teams-release-validate-") as directory:
        stage = Path(directory)
        for relative, (mode, data) in trusted.items():
            write_expected_file(stage, relative, mode, data)
        runtime_path = (
            stage
            / "scripts"
            / okf_runtime_generation(source_version)
            / "okf_conformance.py"
        )
        spec = importlib.util.spec_from_file_location(
            f"_goalteams_validate_okf_{commit[:16]}", runtime_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load frozen OKF runtime for integrity validation")
        module = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous
        policy = module.load_policy(stage)
        git_tree_id = git_text("rev-parse", f"{commit}^{{tree}}")
        manifest = module.build_package_manifest(
            stage,
            policy,
            source_binding={
                "commit_sha256": commit,
                "git_tree_id": git_tree_id,
                "package_manifest_sha256": manifest_sha,
            },
        )
        data = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        trusted = dict(trusted)
        trusted[OKF_GENERATED_PATH] = ("100644", data)
        summary: dict[str, object] = {
            "manifest_path": OKF_GENERATED_PATH,
            "manifest_sha256": hashlib.sha256(data).hexdigest(),
            "payload_tree_sha256": manifest["package"]["payload_tree_sha256"],
            "policy_sha256": manifest["policy"]["sha256"],
            "checker_bindings": manifest["checkers"],
            "package_completeness_state": "complete",
        }
        return trusted, generated, manifest_sha, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="append", help="Version to validate; default: every local version")
    parser.add_argument(
        "--release-root",
        type=Path,
        help="Explicit release root for frozen-source and boundary integrity validation",
    )
    parser.add_argument(
        "--isolated-no-docs-archive",
        action="store_true",
        help="Skip the local-only docs archive check; requires --release-root",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.isolated_no_docs_archive and args.release_root is None:
        raise SystemExit("--isolated-no-docs-archive requires --release-root")
    release_root = (args.release_root or RELEASE_ROOT).expanduser().resolve()
    if not release_root.is_dir() or release_root.is_symlink():
        raise SystemExit(f"release root is not a regular directory: {release_root}")
    versions = args.version or sorted(p.name for p in release_root.glob("V*") if p.is_dir())
    errors: list[str] = []
    results: list[dict[str, object]] = []
    for version in versions:
        if not re.fullmatch(r"V[0-9]+\.[0-9]+", version):
            errors.append(f"invalid release version: {version}")
            continue
        if version not in SUPPORTED_RELEASE_VERSIONS:
            errors.append(f"unsupported release version: {version}")
            continue
        root = release_root / version
        record_path, checksum_path = root / "_release.json", root / "_files.sha256"
        if not record_path.is_file() or not checksum_path.is_file():
            errors.append(f"{version}: release metadata missing")
            continue
        record = json.loads(record_path.read_text(encoding="utf-8"))
        strict_snapshot = version in STRICT_SNAPSHOT_VERSIONS
        if strict_snapshot and record.get("schema_version") != STRICT_SNAPSHOT_SCHEMA:
            errors.append(f"{version}: strict snapshot schema mismatch")
        if record.get("version") != version or (root / "VERSION").read_text(encoding="utf-8").strip() != version:
            errors.append(f"{version}: version mismatch")
        current_manifest = root / "release" / "current" / "manifest.json"
        if not current_manifest.is_file():
            errors.append(f"{version}: current release manifest missing")
        else:
            current = json.loads(current_manifest.read_text(encoding="utf-8"))
            projection_state = release_projection_state(
                version,
                current,
                allow_candidate=args.isolated_no_docs_archive,
            )
            if projection_state == "invalid":
                errors.append(f"{version}: current release manifest is not final")
        source_ref = str(record.get("source_ref") or "")
        commit = str(record.get("source_commit") or "")
        commit_ok = False
        if re.fullmatch(r"[0-9a-f]{40}", commit):
            _assert_trusted_git_repository()
            object_type = _run_git("cat-file", "-t", commit, text=True, check=False)
            assert isinstance(object_type.stdout, str)
            commit_ok = (
                object_type.returncode == 0
                and object_type.stdout.strip() == "commit"
            )
        if not commit_ok:
            errors.append(f"{version}: source_commit is not an immutable commit object")
        if strict_snapshot and (
            record.get("identity_authority") != "source_commit"
            or record.get("sealed") is not True
        ):
            errors.append(f"{version}: snapshot is not sealed to source_commit authority")

        listed: dict[str, dict[str, object]] = {}
        checksum_content = checksum_path.read_text(encoding="utf-8")
        manifest_lines: list[str]
        if strict_snapshot:
            try:
                parsed_v240 = parse_v240_files_manifest(checksum_content)
            except V240FilesManifestError as exc:
                errors.append(f"{version}: {exc}")
                parsed_v240 = []
            for row in parsed_v240:
                relative = str(row["path"])
                listed[relative] = {
                    "sha256": row["sha256"],
                    "mode": row["mode"],
                    "size": row["size"],
                }
            manifest_lines = []
        else:
            manifest_lines = checksum_content.splitlines()
        for line in manifest_lines:
            if "\t" in line:
                fields = line.split("\t", 3)
                if len(fields) != 4:
                    errors.append(f"{version}: invalid extended file manifest row")
                    continue
                expected_hash, expected_mode, expected_size_raw, relative = fields
                try:
                    expected_size: int | None = int(expected_size_raw)
                except ValueError:
                    errors.append(f"{version}: invalid file manifest size {relative}")
                    continue
            else:
                expected_hash, relative = line.split("  ", 1)
                expected_mode = None
                expected_size = None
            try:
                safe_manifest_path(relative)
            except RuntimeError:
                errors.append(f"{version}: unsafe file manifest path {relative}")
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                errors.append(f"{version}: invalid file manifest hash {relative}")
            if expected_mode is not None and expected_mode not in {"100644", "100755"}:
                errors.append(f"{version}: invalid file manifest mode {relative}")
            if expected_size is not None and expected_size < 0:
                errors.append(f"{version}: invalid file manifest size {relative}")
            if strict_snapshot and (expected_mode is None or expected_size is None):
                errors.append(f"{version}: extended mode/size file manifest is required")
            if relative in listed:
                errors.append(f"{version}: duplicate checksum path {relative}")
            listed[relative] = {
                "sha256": expected_hash,
                "mode": expected_mode,
                "size": expected_size,
            }
        files = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file() and not p.relative_to(root).as_posix().startswith("_artifacts/") and p.name not in META}
        mismatches = [
            path
            for path, file in files.items()
            if listed.get(path, {}).get("sha256") != digest(file)
            or (
                listed.get(path, {}).get("size") is not None
                and listed[path]["size"] != file.stat().st_size
            )
            or (
                listed.get(path, {}).get("mode") is not None
                and listed[path]["mode"]
                != f"100{stat.S_IMODE(file.stat().st_mode):03o}"
            )
        ]
        if set(files) != set(listed): errors.append(f"{version}: file manifest mismatch")
        if mismatches: errors.append(f"{version}: file hash mismatch {mismatches}")
        forbidden = [p for p in files if excluded(p)]
        if forbidden: errors.append(f"{version}: nonrelease paths present {forbidden}")

        if commit_ok:
            forbidden_source = [path for path in source_entries(commit) if excluded(path)]
            if forbidden_source:
                errors.append(f"{version}: frozen Git source contains nonrelease paths {forbidden_source}")
            try:
                trusted, generated, manifest_sha, expected_okf = (
                    materialize_expected_payload_map(commit)
                )
            except (OSError, RuntimeError, UnicodeDecodeError, KeyError, ValueError) as exc:
                errors.append(
                    f"{version}: frozen-source expected payload derivation failed: {type(exc).__name__}:{exc}"
                )
                trusted, generated, manifest_sha, expected_okf = {}, set(), "unavailable", None
            if set(trusted) != set(files):
                errors.append(f"{version}: release files differ from frozen source plus generated allowlist")
            source_mismatches = [p for p, (_, data) in trusted.items() if p not in files or hashlib.sha256(data).hexdigest() != digest(files[p])]
            if source_mismatches:
                errors.append(f"{version}: files differ from frozen-source expected payload {source_mismatches}")
            mode_mismatches = [
                path
                for path, (mode, _) in trusted.items()
                if path in files
                and (
                    (mode == "100755" and stat.S_IMODE(files[path].stat().st_mode) != 0o755)
                    or (mode == "100644" and stat.S_IMODE(files[path].stat().st_mode) != 0o644)
                )
            ]
            if mode_mismatches:
                errors.append(f"{version}: release file mode mismatch {mode_mismatches}")
            rows = [{"path": p, "mode": mode, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for p, (mode, data) in sorted(trusted.items())]
            tree_input = b"".join(f"{r['path']}\0{r['mode']}\0{r['size']}\0{r['sha256']}\n".encode() for r in rows)
            generated_rows = [row for row in rows if row["path"] in generated]
            expected_record = {
                "source_package_manifest_sha256": manifest_sha,
                "file_count": len(rows),
                "total_bytes": sum(int(r["size"]) for r in rows),
                "tree_sha256": hashlib.sha256(tree_input).hexdigest(),
            }
            if generated:
                expected_record.update(
                    {
                        "source_git_tree_id": git_text("rev-parse", f"{commit}^{{tree}}"),
                        "builder_generated_files": generated_rows,
                        "okf_conformance": expected_okf,
                    }
                )
            for key, expected in expected_record.items():
                if record.get(key) != expected:
                    errors.append(f"{version}: metadata {key} is not bound to frozen source")
            if generated:
                # Release metadata and archives intentionally live beside the
                # payload.  Materialize a temporary validation tree for the
                # strict complete-tree check; no archive or second public
                # asset set is created. Actual release bytes/modes are compared
                # with this expected map above and with the tar manifest below.
                with tempfile.TemporaryDirectory(
                    prefix="goal-teams-release-payload-replay-"
                ) as directory:
                    payload_root = Path(directory)
                    for relative, (mode, data) in trusted.items():
                        write_expected_file(payload_root, relative, mode, data)
                    checker = payload_root / "scripts" / "checks" / "check-okf.py"
                    replay = subprocess.run(
                        [
                            sys.executable,
                            str(checker),
                            "--root",
                            str(payload_root),
                            "--package-tree",
                            str(payload_root),
                        ],
                        cwd=payload_root,
                        text=True,
                        capture_output=True,
                        check=False,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    )
                    try:
                        replay_payload = json.loads(replay.stdout)
                    except json.JSONDecodeError:
                        replay_payload = {}
                    if (
                        replay.returncode != 0
                        or replay_payload.get("passed") is not True
                        or replay_payload.get("package_completeness_state") != "complete"
                    ):
                        errors.append(f"{version}: OKF package-tree replay failed")

        artifact_info = record.get("artifact", {})
        expected_artifact_path = f"_artifacts/goal-teams-{version}.tar.gz"
        if artifact_info.get("path") != expected_artifact_path:
            errors.append(f"{version}: artifact path must be {expected_artifact_path}")
        artifact = root / expected_artifact_path
        artifact_ok = artifact.is_file() and digest(artifact) == artifact_info.get("sha256") and artifact.stat().st_size == artifact_info.get("size")
        if not artifact_ok:
            errors.append(f"{version}: artifact metadata/hash mismatch")
        sums = root / "_artifacts" / "SHA256SUMS"
        expected_sum = f"{artifact_info.get('sha256')}  {artifact.name}\n"
        if not sums.is_file() or sums.read_text(encoding="utf-8") != expected_sum:
            errors.append(f"{version}: SHA256SUMS mismatch")
        tar_paths: set[str] = set()
        if artifact.is_file():
            try:
                safe_members = inspect_safe_tar(artifact, version)
                with tarfile.open(artifact, "r:gz") as archive:
                    for member_name, relative in safe_members:
                        member = archive.getmember(member_name)
                        tar_paths.add(relative)
                        stream = archive.extractfile(member)
                        if stream is None or hashlib.sha256(stream.read()).hexdigest() != listed.get(relative, {}).get("sha256"):
                            errors.append(f"{version}: tar content mismatch {relative}")
                        listed_mode = listed.get(relative, {}).get("mode")
                        listed_size = listed.get(relative, {}).get("size")
                        if listed_mode is not None and listed_mode != f"100{member.mode:03o}":
                            errors.append(f"{version}: tar manifest mode mismatch {relative}")
                        if listed_size is not None and listed_size != member.size:
                            errors.append(f"{version}: tar manifest size mismatch {relative}")
                        if commit_ok and relative in trusted:
                            expected_mode = 0o755 if trusted[relative][0] == "100755" else 0o644
                            if member.mode != expected_mode:
                                errors.append(f"{version}: tar mode mismatch {relative}")
                if tar_paths != set(listed): errors.append(f"{version}: tar manifest mismatch")
            except (RuntimeError, tarfile.TarError) as exc:
                errors.append(f"{version}: invalid tar archive: {exc}")
        archive_index = WORKSPACE_ROOT / "docs" / "archive" / "releases" / version / "archive-index.json"
        if args.isolated_no_docs_archive:
            archive_index = None
        elif not archive_index.is_file():
            errors.append(f"{version}: root docs archive missing")
        if archive_index is not None and archive_index.is_file():
            archive_record = json.loads(archive_index.read_text(encoding="utf-8"))
            if archive_record.get("source_commit") != record.get("source_commit") or archive_record.get("source_ref") != source_ref:
                errors.append(f"{version}: docs archive source binding mismatch")
            archive_root = archive_index.parent / "repository-docs"
            archive_listed = archive_record.get("files", [])
            archive_paths: set[str] = set()
            for item in archive_listed:
                path = str(item.get("path", ""))
                if path in archive_paths:
                    errors.append(f"{version}: duplicate docs archive path {path}")
                archive_paths.add(path)
                file = archive_root / path
                if not file.is_file() or file.stat().st_size != item.get("size") or digest(file) != item.get("sha256"):
                    errors.append(f"{version}: docs archive content mismatch {path}")
            actual_archive = {p.relative_to(archive_root).as_posix() for p in archive_root.rglob("*") if p.is_file()}
            if actual_archive != archive_paths or archive_record.get("file_count") != len(archive_paths):
                errors.append(f"{version}: docs archive manifest mismatch")
            if commit_ok:
                expected_archive = {p: data for p, (_, data) in source_entries(commit).items() if excluded(p)}
                if set(expected_archive) != archive_paths:
                    errors.append(f"{version}: docs archive differs from frozen Git exclusions")
                archive_source_mismatches = [p for p, data in expected_archive.items() if not (archive_root / p).is_file() or hashlib.sha256(data).hexdigest() != digest(archive_root / p)]
                if archive_source_mismatches:
                    errors.append(f"{version}: docs archive differs from frozen Git source {archive_source_mismatches}")
        results.append({"version": version, "files": len(files), "hash_mismatches": len(mismatches), "forbidden": len(forbidden), "artifact_ok": artifact_ok})
    payload = {
        "schema_version": "goal-teams-release-validation-v2",
        "passed": not errors,
        "validation_contract": {
            "validation_kind": "same_built_asset_frozen_source_and_boundary_integrity",
            "asset_build_invocation_count": 0,
            "second_build_comparison_attempted": False,
            "reproducibility_claim": False,
            "release_asset_set_mutation_count": 0,
        },
        "versions": results,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
