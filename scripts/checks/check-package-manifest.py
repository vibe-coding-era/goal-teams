#!/usr/bin/env python3
"""Read-only structural validation for Current or Replay package manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
CURRENT_MANIFEST = ROOT / "scripts/install/package-manifest.txt"
REPLAY_MANIFEST = ROOT / "scripts/install/replay-package-manifest.txt"
ACTIVE_PATH = "references/current/ACTIVE.json"
ACTIVE_SCHEMA = "goal-teams-active-generation-v1"
ACTIVATION_SCHEMA = "goal-teams-activation-manifest-v2.50"
GENERATION_ID_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_CURRENT_PREFIXES = {"references/", "schemas/", "scripts/", "tests/v23/"}
FORBIDDEN_CURRENT_PATH_MARKERS = (
    "references/legacy-replay/",
    "references/profiles/goal-teams-self-release-v2.36.md",
    "references/profiles/goal-teams-self-release-v2.48.md",
    "references/profiles/goal-teams-self-release-v2.49.md",
    "references/release-profiles/v2.48.json",
    "references/release-profiles/v2.49.json",
    "references/profiles/goal-teams-self-release-v2.50.md",
    "references/release-profiles/v2.50.json",
    "references/profiles/goal-teams-self-release-v2.52.md",
    "references/release-profiles/v2.52.json",
    "references/profiles/goal-teams-self-release-v2.6.md",
    "references/release-profiles/v2.6.json",
    "references/current/generations/V2.49/",
    "references/current/generations/V2.50/",
    "references/current/generations/V2.52/",
    "references/current/generations/V2.6/",
    "references/compatibility/v2.6/",
    "schemas/v2.36/",
    "schemas/v2.48/",
    "schemas/v2.49/",
    "schemas/v2.6/",
    "scripts/v23/",
    "scripts/v249/",
    "scripts/v26/",
    "tests/v23/",
    "tests/v249/",
    "tests/v26/",
)
ALLOWED_REPLAY_SHARED_PATHS = {
    "schemas/v2.50/legacy-replay-manifest.schema.json",
    "scripts/v250/replay_runner.py",
}


def _safe_path(value: str, *, prefix: bool) -> bool:
    path = PurePosixPath(value.rstrip("/"))
    return bool(
        value
        and (value.endswith("/") is prefix)
        and "\\" not in value
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _source_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        candidates = {
            item.decode("utf-8")
            for item in result.stdout.split(b"\0")
            if item
        }
    else:
        candidates = {
            path.relative_to(root).as_posix() for path in root.rglob("*")
        }
    return {
        relative
        for relative in candidates
        if _resolve_regular_package_file(root, relative) is not None
    }


def _selected_paths(root: Path, rules: list[tuple[str, str]]) -> tuple[set[str], list[str]]:
    source_paths = _source_paths(root)
    selected: set[str] = set()
    errors: list[str] = []
    for kind, value in rules:
        if kind == "generated":
            continue
        if kind == "file":
            if value not in source_paths:
                errors.append(f"E_PACKAGE_MANIFEST_FILE_MISSING:{value}")
            else:
                selected.add(value)
            continue
        matches = {path for path in source_paths if path.startswith(value)}
        if not matches:
            errors.append(f"E_PACKAGE_MANIFEST_PREFIX_EMPTY:{value}")
        selected.update(matches)
    return selected, errors


def _canonical_json_digest(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _resolve_regular_package_file(root: Path, relative: str) -> Path | None:
    if not _safe_path(relative, prefix=False):
        return None
    resolved_root = root.resolve()
    cursor = resolved_root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    try:
        cursor.resolve().relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return cursor if cursor.is_file() else None


def _read_active_pointer(root: Path) -> tuple[dict[str, object] | None, list[str]]:
    active_file = _resolve_regular_package_file(root, ACTIVE_PATH)
    if active_file is None:
        return None, ["E_CURRENT_PACKAGE_ACTIVE_POINTER_UNAVAILABLE"]
    try:
        active = json.loads(active_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, ["E_CURRENT_PACKAGE_ACTIVE_POINTER_UNAVAILABLE"]
    if not isinstance(active, dict):
        return None, ["E_CURRENT_PACKAGE_ACTIVE_POINTER_INVALID"]
    generation_id = active.get("generation_id")
    activation_path = active.get("activation_manifest")
    digest = active.get("activation_manifest_sha256")
    if (
        active.get("schema_version") != ACTIVE_SCHEMA
        or active.get("state") != "active_current"
        or not isinstance(generation_id, str)
        or not GENERATION_ID_RE.fullmatch(generation_id)
        or not isinstance(activation_path, str)
        or not _safe_path(activation_path, prefix=False)
        or activation_path
        != f"references/current/generations/{generation_id}/activation-manifest.json"
        or not isinstance(digest, str)
        or not SHA256_RE.fullmatch(digest)
    ):
        return None, ["E_CURRENT_PACKAGE_ACTIVE_POINTER_INVALID"]
    return active, []


def _generation_package_closure(
    root: Path,
    selected: set[str],
    *,
    generation_id: str,
    activation_path: str,
    expected_activation_sha256: str,
    allowed_generation_states: frozenset[str],
    error_prefix: str,
) -> list[str]:
    """Validate one digest-selected generation without consulting VERSION."""

    errors: list[str] = []
    if activation_path not in selected:
        return [f"{error_prefix}_ACTIVATION_NOT_SELECTED:{activation_path}"]
    activation_file = _resolve_regular_package_file(root, activation_path)
    if activation_file is None:
        return [f"{error_prefix}_ACTIVATION_UNAVAILABLE:{activation_path}"]
    try:
        activation_raw = activation_file.read_bytes()
        activation = json.loads(activation_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [f"{error_prefix}_ACTIVATION_UNAVAILABLE:{activation_path}"]
    if hashlib.sha256(activation_raw).hexdigest() != expected_activation_sha256:
        errors.append(f"{error_prefix}_ACTIVATION_DIGEST_MISMATCH:{activation_path}")
    if not isinstance(activation, dict):
        errors.append(f"{error_prefix}_ACTIVATION_INVALID:{activation_path}")
        return errors
    if (
        activation.get("schema_version") != ACTIVATION_SCHEMA
        or activation.get("generation_id") != generation_id
        or activation.get("generation_state") not in allowed_generation_states
    ):
        errors.append(f"{error_prefix}_GENERATION_MISMATCH:{generation_id}")

    expected_payload_digest = activation.get("manifest_payload_sha256")
    payload = dict(activation)
    payload.pop("manifest_payload_sha256", None)
    if (
        not isinstance(expected_payload_digest, str)
        or not SHA256_RE.fullmatch(expected_payload_digest)
        or _canonical_json_digest(payload) != expected_payload_digest
    ):
        errors.append(f"{error_prefix}_PAYLOAD_DIGEST_MISMATCH")

    root_sets = activation.get("root_sets")
    if not isinstance(root_sets, dict):
        errors.append(f"{error_prefix}_ROOT_SETS_INVALID")
        return errors
    members: set[str] = set()
    for root_name in (
        "bootstrap",
        "current",
        "execution",
        "schemas_and_validators",
    ):
        entries = root_sets.get(root_name)
        if not isinstance(entries, list):
            errors.append(f"{error_prefix}_ROOT_SET_INVALID:{root_name}")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"{error_prefix}_MEMBER_INVALID:{root_name}")
                continue
            relative = entry.get("path")
            expected_digest = entry.get("sha256")
            expected_bytes = entry.get("bytes")
            if (
                not isinstance(relative, str)
                or not _safe_path(relative, prefix=False)
                or not isinstance(expected_digest, str)
                or not SHA256_RE.fullmatch(expected_digest)
                or not isinstance(expected_bytes, int)
                or isinstance(expected_bytes, bool)
                or expected_bytes < 0
            ):
                errors.append(f"{error_prefix}_MEMBER_INVALID:{root_name}")
                continue
            if relative in members:
                errors.append(f"{error_prefix}_MEMBER_DUPLICATE:{relative}")
                continue
            members.add(relative)
            if relative not in selected:
                errors.append(f"{error_prefix}_MEMBER_NOT_SELECTED:{relative}")
                continue
            member_file = _resolve_regular_package_file(root, relative)
            if member_file is None:
                errors.append(f"{error_prefix}_MEMBER_UNAVAILABLE:{relative}")
                continue
            try:
                raw = member_file.read_bytes()
            except OSError:
                errors.append(f"{error_prefix}_MEMBER_UNAVAILABLE:{relative}")
                continue
            if hashlib.sha256(raw).hexdigest() != expected_digest:
                errors.append(f"{error_prefix}_MEMBER_DIGEST_MISMATCH:{relative}")
            if len(raw) != expected_bytes:
                errors.append(f"{error_prefix}_MEMBER_SIZE_MISMATCH:{relative}")
    if not members:
        errors.append(f"{error_prefix}_GENERATION_EMPTY")

    for field in ("rule_manifest_path", "prompt_manifest_path"):
        relative = activation.get(field)
        if not isinstance(relative, str) or relative not in members:
            errors.append(f"{error_prefix}_{field.upper()}_UNBOUND")

    allowlist = activation.get("current_default_allowlist")
    if (
        not isinstance(allowlist, list)
        or not all(isinstance(path, str) for path in allowlist)
        or len(allowlist) != len(set(allowlist))
    ):
        errors.append(f"{error_prefix}_ALLOWLIST_INVALID")
        return errors
    expected_allowlist_digest = activation.get("current_default_allowlist_digest")
    if (
        not isinstance(expected_allowlist_digest, str)
        or not SHA256_RE.fullmatch(expected_allowlist_digest)
        or _canonical_json_digest(sorted(allowlist)) != expected_allowlist_digest
    ):
        errors.append(f"{error_prefix}_ALLOWLIST_DIGEST_MISMATCH")
    required_allowlist = members | {ACTIVE_PATH, activation_path}
    for relative in sorted(required_allowlist - set(allowlist)):
        errors.append(f"{error_prefix}_ALLOWLIST_REQUIRED_MISSING:{relative}")
    for relative in sorted(set(allowlist) - selected):
        errors.append(f"{error_prefix}_ALLOWLIST_NOT_SELECTED:{relative}")
    supplement = activation.get("package_supplement_allowlist")
    if (
        not isinstance(supplement, list)
        or not all(
            isinstance(path, str) and _safe_path(path, prefix=False)
            for path in supplement
        )
        or len(supplement) != len(set(supplement))
        or set(supplement) & set(allowlist)
    ):
        errors.append(f"{error_prefix}_SUPPLEMENT_INVALID")
        return errors
    expected_supplement_digest = activation.get(
        "package_supplement_allowlist_digest"
    )
    if (
        not isinstance(expected_supplement_digest, str)
        or not SHA256_RE.fullmatch(expected_supplement_digest)
        or _canonical_json_digest(sorted(supplement))
        != expected_supplement_digest
    ):
        errors.append(f"{error_prefix}_SUPPLEMENT_DIGEST_MISMATCH")
    expected_selected = set(allowlist) | set(supplement)
    for relative in sorted(set(supplement) - selected):
        errors.append(f"{error_prefix}_SUPPLEMENT_NOT_SELECTED:{relative}")
    for relative in sorted(selected - expected_selected):
        errors.append(f"{error_prefix}_SELECTED_UNDECLARED:{relative}")
    return errors


def _active_package_closure(root: Path, selected: set[str]) -> list[str]:
    """Validate the package against its selected ACTIVE pointer, never VERSION."""

    if ACTIVE_PATH not in selected:
        return ["E_CURRENT_PACKAGE_ACTIVE_POINTER_NOT_SELECTED"]
    active, pointer_errors = _read_active_pointer(root)
    if pointer_errors:
        return pointer_errors
    assert active is not None
    generation_id = active["generation_id"]
    activation_path = active["activation_manifest"]
    expected_activation_sha256 = active["activation_manifest_sha256"]
    assert isinstance(generation_id, str)
    assert isinstance(activation_path, str)
    assert isinstance(expected_activation_sha256, str)
    return _generation_package_closure(
        root,
        selected,
        generation_id=generation_id,
        activation_path=activation_path,
        expected_activation_sha256=expected_activation_sha256,
        allowed_generation_states=frozenset({"active"}),
        error_prefix="E_CURRENT_PACKAGE_ACTIVE",
    )


def _candidate_package_closure(
    root: Path,
    selected: set[str],
    *,
    generation_id: str,
    expected_activation_sha256: str,
) -> list[str]:
    """Validate an explicitly digest-selected prospective Current generation.

    This route intentionally does not read ACTIVE or VERSION. It accepts the
    pre-cutover ``inactive_candidate`` state and the ACTIVE-last prospective
    ``active`` state so the same exact package selection can be checked on
    either side of pointer cutover.
    """

    if not GENERATION_ID_RE.fullmatch(generation_id):
        return ["E_CANDIDATE_PACKAGE_GENERATION_INVALID"]
    if not SHA256_RE.fullmatch(expected_activation_sha256):
        return ["E_CANDIDATE_PACKAGE_ACTIVATION_SHA256_INVALID"]
    activation_path = (
        f"references/current/generations/{generation_id}/activation-manifest.json"
    )
    return _generation_package_closure(
        root,
        selected,
        generation_id=generation_id,
        activation_path=activation_path,
        expected_activation_sha256=expected_activation_sha256,
        allowed_generation_states=frozenset({"inactive_candidate", "active"}),
        error_prefix="E_CANDIDATE_PACKAGE",
    )


def _legacy_intersection(
    root: Path,
    selected: set[str],
    activation: dict[str, object] | Path,
) -> list[str]:
    try:
        value = (
            activation
            if isinstance(activation, dict)
            else json.loads(activation.read_text(encoding="utf-8"))
        )
        classification = value["legacy_classification"]
        prefixes = classification["path_prefixes"]
        exact = set(classification["exact_paths"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return ["E_V250_LEGACY_CLASSIFICATION_UNAVAILABLE"]
    return sorted(
        path
        for path in selected
        if path in exact or any(path.startswith(prefix) for prefix in prefixes)
    )


def _candidate_identity(root: Path) -> tuple[str, str, str]:
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "V2.63"
    if not version.startswith("V") or version.count(".") != 1:
        version = "V2.63"
    suffix = version[1:].lower()
    compact = suffix.replace(".", "")
    return version, suffix, compact


def _candidate_activation(root: Path) -> Path:
    version, _, _ = _candidate_identity(root)
    return root / f"references/current/generations/{version}/activation-manifest.json"


def _replay_required_paths(root: Path) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    replay_path = root / "references/legacy-replay/manifest.json"
    active_path = root / "references/current/ACTIVE.json"
    required = {
        "references/legacy-replay/INDEX.md",
        "references/legacy-replay/manifest.json",
        "references/current/generations/V2.48/activation-manifest.json",
    }
    try:
        raw = replay_path.read_bytes()
        replay = json.loads(raw.decode("utf-8"))
        active = json.loads(active_path.read_text(encoding="utf-8"))
        activation_path = root / active["activation_manifest"]
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        expected_replay_sha = activation["legacy_classification"]["replay_manifest_sha256"]
        if hashlib.sha256(raw).hexdigest() != expected_replay_sha:
            errors.append("E_REPLAY_PACKAGE_ACTIVE_BINDING")
        allowlist = replay["optional_replay_allowlist"]
        if not isinstance(allowlist, list) or not all(isinstance(item, str) for item in allowlist):
            raise TypeError("optional replay allowlist")
        required.update(allowlist)
        for entry in replay["replays"]:
            for field in (
                "schema_paths",
                "validator_paths",
                "transitive_dependency_paths",
                "fixture_paths",
            ):
                values = entry.get(field, [])
                if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                    raise TypeError(field)
                required.update(values)
            profile_path = entry.get("profile_path")
            if not isinstance(profile_path, str):
                raise TypeError("profile_path")
            required.add(profile_path)
            for item in entry.get("content_digests", []):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    raise TypeError("content_digests")
                required.add(item["path"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        errors.append("E_REPLAY_PACKAGE_CONTRACT_UNAVAILABLE")

    try:
        baseline = json.loads(
            (root / "references/current/generations/V2.48/activation-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        if baseline.get("schema_version") != "goal-teams-baseline-activation-manifest-v2.50":
            raise TypeError("baseline schema")
        for field in ("semantic_owner_paths", "execution_identity_paths"):
            for item in baseline[field]:
                required.add(item["path"])
        required.update(baseline["subagent_config_digests"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        errors.append("E_REPLAY_PACKAGE_BASELINE_UNAVAILABLE")
    return required, errors


def validate_manifest(
    path: Path,
    *,
    replay: bool,
    candidate_generation: str | None = None,
    activation_sha256: str | None = None,
) -> dict[str, object]:
    errors: list[str] = []
    rules: list[tuple[str, str]] = []
    candidate_requested = (
        candidate_generation is not None or activation_sha256 is not None
    )
    if not path.is_file() or path.is_symlink():
        return {"passed": False, "errors": ["E_PACKAGE_MANIFEST_MISSING"]}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or fields[0] not in {"file", "prefix", "generated"}:
            errors.append(f"E_PACKAGE_MANIFEST_ROW:{number}")
            continue
        kind, value = fields
        if not _safe_path(value, prefix=kind == "prefix"):
            errors.append(f"E_PACKAGE_MANIFEST_PATH:{number}")
            continue
        if value.startswith(("docs/", "develops/", "GoalTeamsWork-")):
            errors.append(f"E_PACKAGE_MANIFEST_LOCAL_ONLY:{number}")
        rules.append((kind, value))
    if len(rules) != len(set(rules)):
        errors.append("E_PACKAGE_MANIFEST_DUPLICATE")
    values = {value for _, value in rules}
    selected, selection_errors = _selected_paths(ROOT, rules)
    errors.extend(selection_errors)
    if replay:
        if candidate_requested:
            errors.append("E_PACKAGE_MANIFEST_REPLAY_CANDIDATE_CONFLICT")
        if not selected:
            errors.append("E_REPLAY_PACKAGE_MANIFEST_EMPTY")
        required, contract_errors = _replay_required_paths(ROOT)
        errors.extend(contract_errors)
        missing = sorted(required - selected)
        errors.extend(f"E_REPLAY_PACKAGE_REQUIRED_MISSING:{path}" for path in missing)
        unexpected = sorted(selected - required - ALLOWED_REPLAY_SHARED_PATHS)
        errors.extend(f"E_REPLAY_PACKAGE_UNDECLARED:{path}" for path in unexpected)
        current_version, current_suffix, current_compact = _candidate_identity(ROOT)
        current_leaks = sorted(
            path
            for path in selected
            if (
                path.startswith(f"references/current/generations/{current_version}/")
                or path.startswith(f"references/compatibility/v{current_suffix}/")
                or path.startswith(
                    f"references/profiles/goal-teams-self-release-v{current_suffix}"
                )
                or path.startswith(f"references/release-profiles/v{current_suffix}")
                or path.startswith(f"scripts/v{current_compact}/")
                or path.startswith(f"schemas/v{current_suffix}/")
                or path.startswith("scripts/v250/")
                or path.startswith("schemas/v2.50/")
            )
            and path not in ALLOWED_REPLAY_SHARED_PATHS
        )
        errors.extend(f"E_REPLAY_PACKAGE_CURRENT_LEAK:{path}" for path in current_leaks)
        legacy_intersection = sorted(selected - ALLOWED_REPLAY_SHARED_PATHS)
    else:
        version: str | None = None
        activation_path: str | None = None
        identity_error = "E_CURRENT_PACKAGE_NON_ACTIVE_IDENTITY:"
        if candidate_requested:
            identity_error = "E_CANDIDATE_PACKAGE_NON_CANDIDATE_IDENTITY:"
            if candidate_generation is None or activation_sha256 is None:
                errors.append("E_CANDIDATE_PACKAGE_IDENTITY_INCOMPLETE")
            else:
                errors.extend(
                    _candidate_package_closure(
                        ROOT,
                        selected,
                        generation_id=candidate_generation,
                        expected_activation_sha256=activation_sha256,
                    )
                )
                if GENERATION_ID_RE.fullmatch(candidate_generation):
                    version = candidate_generation
                    activation_path = (
                        "references/current/generations/"
                        f"{version}/activation-manifest.json"
                    )
        else:
            errors.extend(_active_package_closure(ROOT, selected))
            active, _pointer_errors = _read_active_pointer(ROOT)
            if active is not None:
                version = str(active["generation_id"])
                activation_path = str(active["activation_manifest"])
        if version is not None and activation_path is not None:
            suffix = version[1:].lower()
            compact = suffix.replace(".", "")
            required_rules = {
                ("file", ACTIVE_PATH),
                ("prefix", f"references/current/generations/{version}/"),
                ("prefix", f"references/compatibility/v{suffix}/"),
                ("prefix", "scripts/v250/"),
                ("prefix", f"scripts/v{compact}/"),
                ("prefix", "schemas/v2.50/"),
                ("prefix", f"schemas/v{suffix}/"),
            }
            for required in sorted(required_rules):
                if required not in rules:
                    errors.append(
                        f"E_CURRENT_PACKAGE_MANIFEST_REQUIRED:{required[1]}"
                    )
            identity_rules = {
                f"references/current/generations/{version}/",
                f"references/compatibility/v{suffix}/",
                f"scripts/v{compact}/",
                f"schemas/v{suffix}/",
                f"references/profiles/goal-teams-self-release-v{suffix}.md",
                f"references/release-profiles/v{suffix}.json",
            }
            identity_prefixes = (
                "references/current/generations/",
                "references/compatibility/v",
                "references/profiles/goal-teams-self-release-v",
                "references/release-profiles/v",
            )
            for kind, value in rules:
                is_product_script = (
                    kind == "prefix"
                    and value.startswith("scripts/v")
                    and value != "scripts/v250/"
                )
                is_product_schema = (
                    kind == "prefix"
                    and value.startswith("schemas/v")
                    and value != "schemas/v2.50/"
                )
                if (
                    value.startswith(identity_prefixes)
                    or is_product_script
                    or is_product_schema
                ) and value not in identity_rules:
                    errors.append(identity_error + value)
            for required_path in (
                f"references/profiles/goal-teams-self-release-v{suffix}.md",
                f"references/release-profiles/v{suffix}.json",
                "scripts/checks/check-v250.py",
                "scripts/install/install-local.sh",
            ):
                if ("file", required_path) not in rules:
                    errors.append(
                        f"E_CURRENT_PACKAGE_MANIFEST_REQUIRED:{required_path}"
                    )
            if activation_path in selected:
                try:
                    activation_file = _resolve_regular_package_file(
                        ROOT, activation_path
                    )
                    if activation_file is None:
                        raise OSError("activation manifest is not a regular file")
                    activation_value = json.loads(
                        activation_file.read_text(encoding="utf-8")
                    )
                    if not isinstance(activation_value, dict):
                        raise TypeError("activation manifest")
                    legacy_intersection = _legacy_intersection(
                        ROOT, selected, activation_value
                    )
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    TypeError,
                ):
                    errors.append("E_V250_LEGACY_CLASSIFICATION_UNAVAILABLE")
                    legacy_intersection = []
            else:
                legacy_intersection = []
        else:
            legacy_intersection = []
        for kind, value in rules:
            if kind == "prefix" and value in FORBIDDEN_CURRENT_PREFIXES:
                errors.append(f"E_CURRENT_PACKAGE_MANIFEST_WIDE_PREFIX:{value}")
            if any(
                value == marker or value.startswith(marker)
                for marker in FORBIDDEN_CURRENT_PATH_MARKERS
            ):
                errors.append(f"E_CURRENT_PACKAGE_MANIFEST_LEGACY:{value}")
        if legacy_intersection:
            errors.extend(
                f"E_CURRENT_PACKAGE_LEGACY_REACHABLE:{path}"
                for path in legacy_intersection
            )
    return {
        "schema_version": "goal-teams-package-manifest-check-v2.50",
        "passed": not errors,
        "errors": errors,
        "manifest": path.relative_to(ROOT).as_posix(),
        "mode": "replay" if replay else ("candidate" if candidate_requested else "current"),
        "candidate_generation": candidate_generation if candidate_requested else None,
        "activation_sha256": activation_sha256 if candidate_requested else None,
        "rule_count": len(rules),
        "selected_path_count": len(selected),
        "legacy_intersection": legacy_intersection,
        "external_side_effect_count": 0,
    }


def _generation_argument(value: str) -> str:
    if not GENERATION_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("must match V<major>.<minor>")
    return value


def _sha256_argument(value: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("must be exactly 64 lowercase hex characters")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--manifest", type=Path)
    candidate = parser.add_argument_group("prospective Current generation")
    candidate.add_argument(
        "--candidate-generation",
        type=_generation_argument,
        help="explicit prospective generation identity; never inferred from VERSION",
    )
    candidate.add_argument(
        "--activation-sha256",
        type=_sha256_argument,
        help="exact raw SHA-256 of the prospective activation manifest",
    )
    return parser


def parse_args() -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args()
    paired = (args.candidate_generation is None) == (args.activation_sha256 is None)
    if not paired:
        parser.error(
            "--candidate-generation and --activation-sha256 must be supplied together"
        )
    if args.replay and args.candidate_generation is not None:
        parser.error("prospective Current generation options cannot be used with --replay")
    return args


def main() -> int:
    args = parse_args()
    path = (args.manifest or (REPLAY_MANIFEST if args.replay else CURRENT_MANIFEST)).resolve()
    result = validate_manifest(
        path,
        replay=args.replay,
        candidate_generation=args.candidate_generation,
        activation_sha256=args.activation_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
