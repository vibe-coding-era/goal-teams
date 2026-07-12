#!/usr/bin/env python3
"""V2.36 acceptance bindings shared by completion and focused tests.

This module contains no signer and no secret-loading path.  The trusted host
adapter supplies already-authenticated route/identity results; this layer binds
them to the protected snapshot and the exact Evidence/ledger/checkpoint inputs
consumed by Review, Harness, and Completion Audit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


ACCEPTANCE_BINDING_SCHEMA_VERSION = "goal-teams-v2.36-acceptance-binding-v1"
ACCEPTANCE_CORE_BINDING_SCHEMA_VERSION = (
    "goal-teams-v2.36-acceptance-core-binding-v1"
)
ACCEPTANCE_INPUT_SNAPSHOT_SCHEMA_VERSION = (
    "goal-teams-v2.36-acceptance-input-snapshot-v1"
)
PRODUCT_VERSION = "V2.36"
POLICY_PROFILES = {
    "goal-teams-core-v2.5",
    "goal-teams-self-release-v2.36",
}
EXECUTION_PROFILES = {"lite", "standard", "full", "regulated"}
REVIEW_CLASSES = {"semantic", "comparison", "safety"}
REVIEW_CLASS_ALLOWED_ACTUAL = {
    "semantic": {"semantic", "comparison", "safety"},
    "comparison": {"comparison", "safety"},
    "safety": {"safety"},
}
GATE_STATES = {"required", "conditional", "not_required"}
GATE_RESULT_STATES = {"passed", "not_required"}
V236_GATE_KEYS = frozenset(
    {
        "architecture",
        "completion_audit",
        "contract",
        "e2e",
        "environment",
        "evidence",
        "full_regression",
        "independent_review",
        "independent_tests",
        "integration",
        "pixel_comparison",
        "release_evidence",
        "targeted_regression",
        "targeted_validation",
        "tdd",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PATH_FIELD = re.compile(
    r"(?:^path$|_path$|_paths$|_ref$|_refs$|^artifact$|^artifacts$|^source_paths$)"
)
_PATH_SUFFIX = re.compile(
    r"(?i)\.(?:json|jsonl|md|txt|log|out|xml|html?|ya?ml|toml|csv|tsv|png|jpe?g|webp|pdf|py|js|mjs|cjs|ts|tsx|jsx|sh|sql|bin|wasm|zip|tar|gz|tgz|mp4|mov|pptx|docx|xlsx|sqlite|db)$"
)
_PATH_CONTAINER_FIELDS = frozenset(
    {
        "artifact",
        "artifacts",
        "attachment",
        "attachments",
        "file",
        "files",
        "log",
        "logs",
        "output",
        "outputs",
        "report",
        "reports",
        "source_paths",
        "evidence_paths",
    }
)
_MARKDOWN_REF = re.compile(r"`([^`\r\n]+)`")
_MARKDOWN_INLINE_LINK = re.compile(
    r"!?\[[^\]\r\n]*\]\(\s*(?:<([^>\r\n]+)>|([^\s)\r\n]+))"
)
_MARKDOWN_REFERENCE_DEFINITION = re.compile(
    r"(?m)^\s{0,3}\[[^\]\r\n]+\]:\s*(?:<([^>\r\n]+)>|([^\s\r\n]+))"
)
_YAML_KEY_VALUE = re.compile(r"^([^:#][^:]*?):(?:\s*(.*))?$")
_MACOS_SYSTEM_ALIASES = {
    "/etc": "/private/etc",
    "/tmp": "/private/tmp",
    "/var": "/private/var",
}
_MAX_SNAPSHOT_FILES = 20_000
_MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
_ACCEPTANCE_BINDING_KEYS = frozenset(
    {"v236_acceptance_binding", "v236_acceptance_core_binding"}
)
_RAW_HASH_MODE = "raw_sha256"
_PROJECTED_HASH_MODE = "canonical_json_without_acceptance_bindings"


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("E_V236_ACCEPTANCE_INPUT_DUPLICATE_KEY")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_json_loads(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_PARSE") from exc


def _without_acceptance_bindings(value: Any) -> Any:
    """Remove only the two exact circular binding keys from JSON content."""

    if isinstance(value, dict):
        return {
            key: _without_acceptance_bindings(item)
            for key, item in value.items()
            if key not in _ACCEPTANCE_BINDING_KEYS
        }
    if isinstance(value, list):
        return [_without_acceptance_bindings(item) for item in value]
    return value


def _snapshot_content(path: Path, *, projected: bool) -> tuple[str, bytes]:
    content = path.read_bytes()
    if not projected:
        return _RAW_HASH_MODE, content
    try:
        document = _strict_json_loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_PARSE") from exc
    return (
        _PROJECTED_HASH_MODE,
        _canonical_json_bytes(_without_acceptance_bindings(document)),
    )


def _resolve_acceptance_root(root: Path | str) -> tuple[Path, Path]:
    """Resolve a root while rejecting every user-controlled symlink component.

    macOS exposes three stable system aliases at the filesystem root.  Those
    exact aliases are accepted only when they resolve to Apple's canonical
    ``/private`` targets; no other intermediate or final symlink is trusted.
    """

    lexical = Path(os.path.abspath(os.fspath(root)))
    if not lexical.is_absolute() or not lexical.anchor:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_ROOT")
    cursor = Path(lexical.anchor)
    lexical_cursor = Path(lexical.anchor)
    try:
        for part in lexical.parts[1:]:
            lexical_cursor = lexical_cursor / part
            candidate = cursor / part
            metadata = os.lstat(candidate)
            if stat.S_ISLNK(metadata.st_mode):
                expected = _MACOS_SYSTEM_ALIASES.get(
                    lexical_cursor.as_posix()
                )
                resolved = candidate.resolve(strict=True)
                if (
                    sys.platform != "darwin"
                    or expected is None
                    or resolved != Path(expected)
                ):
                    raise ValueError("E_V236_ACCEPTANCE_INPUT_ROOT")
                cursor = resolved
            else:
                cursor = candidate
        base = cursor.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_ROOT") from exc
    if not base.is_dir():
        raise ValueError("E_V236_ACCEPTANCE_INPUT_ROOT")
    return lexical, base


def _regular_contained_file(
    root: Path,
    candidate: Path,
    *,
    lexical_root: Path | None = None,
) -> Path:
    root = root.resolve(strict=True)
    try:
        if candidate.is_absolute():
            supplied = Path(os.path.abspath(os.fspath(candidate)))
            relative: Path | None = None
            if lexical_root is not None:
                try:
                    relative = supplied.relative_to(lexical_root)
                except ValueError:
                    pass
            if relative is None:
                relative = supplied.relative_to(root)
            # Rebuild from the canonical root so system aliases such as
            # macOS /var -> /private/var do not look like containment escapes,
            # while symlinks inside the accepted root remain visible to lstat.
            lexical = root / relative
        else:
            relative = candidate
            lexical = root / relative
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_PATH") from exc
    cursor = root
    try:
        for part in relative.parts:
            cursor = cursor / part
            metadata = os.lstat(cursor)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("E_V236_ACCEPTANCE_INPUT_PATH")
        metadata = os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except OSError as exc:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_PATH") from exc
    except (RuntimeError, ValueError) as exc:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_PATH") from exc
    if not stat.S_ISREG(metadata.st_mode) or resolved.stat().st_nlink != 1:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_PATH")
    return resolved


def _looks_like_path(value: str) -> bool:
    if not value or "\x00" in value or value.startswith(("http://", "https://")):
        return False
    without_fragment = value.split("#", 1)[0]
    return bool(
        "/" in without_fragment
        or without_fragment.startswith(".")
        or _PATH_SUFFIX.search(without_fragment)
        or without_fragment == "TaskList.md"
    )


def _document_path_references(
    value: Any,
    *,
    field: str | None = None,
    path_context: bool = False,
) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            references.update(
                _document_path_references(
                    item,
                    field=key_text,
                    path_context=(
                        path_context
                        or bool(_PATH_FIELD.search(key_text))
                        or key_text.lower() in _PATH_CONTAINER_FIELDS
                    ),
                )
            )
        return references
    if isinstance(value, list):
        for item in value:
            references.update(
                _document_path_references(
                    item, field=field, path_context=path_context
                )
            )
        return references
    if (
        isinstance(value, str)
        and isinstance(field, str)
        and (path_context or _PATH_FIELD.search(field))
        and _looks_like_path(value)
    ):
        references.add(value.split("#", 1)[0])
    return references


def _yaml_uncomment(value: str) -> str:
    quote: str | None = None
    escaped = False
    output: list[str] = []
    for character in value:
        if escaped:
            output.append(character)
            escaped = False
            continue
        if character == "\\" and quote == '"':
            output.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            output.append(character)
            continue
        if character == "#" and quote is None:
            break
        output.append(character)
    return "".join(output).strip()


def _yaml_list_items(value: str) -> list[str]:
    """Return scalar items from a conservative YAML flow-style list."""

    stripped = _yaml_uncomment(value)
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return [stripped]
    body = stripped[1:-1]
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for character in body:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\" and quote == '"':
            current.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            current.append(character)
            continue
        if character == "," and quote is None:
            items.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    items.append("".join(current).strip())
    return items


def _yaml_scalar(value: str) -> str:
    value = _yaml_uncomment(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        if quote == '"':
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                decoded = value[1:-1]
            value = decoded if isinstance(decoded, str) else ""
        else:
            value = value[1:-1].replace("''", "'")
    return value.strip()


def _yaml_path_references(text: str, *, frontmatter: bool) -> set[str]:
    """Extract common OKF path/ref scalars and lists without executing YAML.

    This intentionally implements only the frontmatter subset used by Goal
    Teams: indentation, mappings, block sequences, and flow-style scalar
    lists.  Tags, anchors, aliases, and arbitrary YAML types are never loaded.
    """

    lines = text.splitlines()
    if frontmatter:
        if not lines or lines[0].strip() != "---":
            return set()
        closing = next(
            (
                index
                for index, line in enumerate(lines[1:], 1)
                if line.strip() in {"---", "..."}
            ),
            None,
        )
        if closing is None:
            raise ValueError("E_V236_ACCEPTANCE_INPUT_PARSE")
        lines = lines[1:closing]

    references: set[str] = set()
    # Each entry is (mapping indentation, inherited path context).
    contexts: list[tuple[int, bool]] = [(-1, False)]
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            raise ValueError("E_V236_ACCEPTANCE_INPUT_PARSE")
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        content = raw_line[indent:]
        while len(contexts) > 1 and indent <= contexts[-1][0]:
            contexts.pop()
        inherited = contexts[-1][1]
        sequence_value = False
        if content.startswith("-") and (
            len(content) == 1 or content[1].isspace()
        ):
            sequence_value = True
            content = content[1:].strip()
            if not content:
                continue

        match = _YAML_KEY_VALUE.match(content)
        if match:
            key = match.group(1).strip().strip("'\"")
            raw_value = (match.group(2) or "").strip()
            path_context = bool(
                inherited
                or _PATH_FIELD.search(key)
                or key.lower() in _PATH_CONTAINER_FIELDS
            )
            if not raw_value:
                contexts.append((indent, path_context))
                continue
            if path_context:
                for item in _yaml_list_items(raw_value):
                    candidate = _yaml_scalar(item).split("#", 1)[0]
                    if _looks_like_path(candidate):
                        references.add(candidate)
            continue

        if sequence_value and inherited:
            for item in _yaml_list_items(content):
                candidate = _yaml_scalar(item).split("#", 1)[0]
                if _looks_like_path(candidate):
                    references.add(candidate)
    return references


def _file_references(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    documents: list[Any] = []
    if path.suffix == ".json":
        documents.append(_strict_json_loads(text))
    elif path.suffix == ".jsonl":
        for line in text.splitlines():
            if not line.strip():
                continue
            documents.append(_strict_json_loads(line))
    references: set[str] = set()
    for document in documents:
        references.update(_document_path_references(document))
    if path.suffix.lower() in {".md", ".txt"}:
        references.update(_yaml_path_references(text, frontmatter=True))
        references.update(
            candidate
            for candidate in _MARKDOWN_REF.findall(text)
            if _looks_like_path(candidate)
        )
        for pattern in (
            _MARKDOWN_INLINE_LINK,
            _MARKDOWN_REFERENCE_DEFINITION,
        ):
            for match in pattern.finditer(text):
                candidate = next(
                    (value for value in match.groups() if value is not None),
                    "",
                ).split("#", 1)[0]
                if _looks_like_path(candidate):
                    references.add(candidate)
    elif path.suffix.lower() in {".yaml", ".yml"}:
        references.update(_yaml_path_references(text, frontmatter=False))
    return references


def _resolve_reference(
    root: Path,
    source: Path,
    value: str,
    *,
    lexical_root: Path | None = None,
) -> Path:
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [source.parent / raw, root / raw]
    for candidate in candidates:
        try:
            return _regular_contained_file(
                root, candidate, lexical_root=lexical_root
            )
        except ValueError:
            continue
    raise ValueError("E_V236_ACCEPTANCE_INPUT_REFERENCE")


def build_acceptance_input_snapshot(
    root: Path | str,
    *,
    required_paths: Mapping[str, Path | str],
) -> dict[str, Any]:
    """Hash-close all completion inputs and their referenced local artifacts.

    Discovery is filesystem based, not Git based, so ignored GoalTeamsWork
    evidence and logs are covered.  Callers cannot provide a selected manifest;
    they only name the mandatory roots and this function follows path/ref fields.
    """

    lexical_root, base = _resolve_acceptance_root(root)
    if not isinstance(required_paths, Mapping):
        raise ValueError("E_V236_ACCEPTANCE_INPUT_ROOT")
    required_labels = {
        "evidence",
        "review",
        "harness",
        "audit",
        "ledger",
        "checkpoint",
        "traceability",
        "tasklist",
    }
    if set(required_paths) != required_labels:
        raise ValueError("E_V236_ACCEPTANCE_INPUT_REQUIRED")

    required_inputs: dict[str, str] = {}
    queue: list[Path] = []
    projected_paths: set[str] = set()
    for label in sorted(required_paths):
        path = _regular_contained_file(
            base,
            Path(required_paths[label]),
            lexical_root=lexical_root,
        )
        relative = path.relative_to(base).as_posix()
        required_inputs[label] = relative
        queue.append(path)
        if label in {"review", "harness", "audit"}:
            projected_paths.add(relative)

    files: dict[str, dict[str, Any]] = {}
    total_size = 0
    while queue:
        path = queue.pop(0)
        relative = path.relative_to(base).as_posix()
        if relative in files:
            continue
        metadata = path.stat()
        hash_mode, content = _snapshot_content(
            path, projected=relative in projected_paths
        )
        total_size += len(content)
        if len(files) >= _MAX_SNAPSHOT_FILES or total_size > _MAX_SNAPSHOT_BYTES:
            raise ValueError("E_V236_ACCEPTANCE_INPUT_LIMIT")
        files[relative] = {
            "path": relative,
            "mode": format(stat.S_IMODE(metadata.st_mode), "04o"),
            "hash_mode": hash_mode,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for reference in sorted(_file_references(path)):
            queue.append(
                _resolve_reference(
                    base,
                    path,
                    reference,
                    lexical_root=lexical_root,
                )
            )

    records = [files[path] for path in sorted(files)]
    core = {
        "schema_version": ACCEPTANCE_INPUT_SNAPSHOT_SCHEMA_VERSION,
        "required_inputs": required_inputs,
        "files": records,
        "file_count": len(records),
        "total_size": total_size,
    }
    return {**core, "snapshot_sha256": canonical_json_sha256(core)}


def validate_acceptance_input_snapshot(
    root: Path | str, snapshot: Any
) -> list[str]:
    if not isinstance(snapshot, dict):
        return ["E_V236_ACCEPTANCE_INPUT_SNAPSHOT"]
    try:
        rebuilt = build_acceptance_input_snapshot(
            root,
            required_paths=snapshot.get("required_inputs", {}),
        )
    except (OSError, TypeError, ValueError):
        return ["E_V236_ACCEPTANCE_INPUT_SNAPSHOT"]
    return [] if rebuilt == snapshot else ["E_V236_ACCEPTANCE_INPUT_DRIFT"]


def _declares_v236(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("product_version") == PRODUCT_VERSION:
            return True
        if value.get("policy_profile") in POLICY_PROFILES:
            return True
        schema = value.get("schema_version")
        if isinstance(schema, str) and "v2.36" in schema.lower():
            return True
        return any(_declares_v236(item) for item in value.values())
    if isinstance(value, list):
        return any(_declares_v236(item) for item in value)
    return False


def requires_v236_acceptance(
    values: Iterable[Any],
    *,
    verified_goal_teams_target: bool,
    v236_arguments_present: bool = False,
) -> bool:
    """Derive the current acceptance generation without trusting one selector."""

    return bool(
        verified_goal_teams_target
        or v236_arguments_present
        or any(_declares_v236(value) for value in values)
    )


def build_acceptance_binding(
    *,
    acceptance_root: Path | str,
    route_receipt: dict[str, Any],
    route_validation: dict[str, Any],
    snapshot_receipt: dict[str, Any],
    identity_registry: dict[str, Any],
    evidence_registry_path: Path | str,
    ledger_path: Path | str,
    checkpoint_path: Path | str,
    traceability_path: Path | str,
    tasklist_path: Path | str,
    acceptance_input_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if validate_acceptance_input_snapshot(
        acceptance_root, acceptance_input_snapshot
    ):
        raise ValueError("E_V236_ACCEPTANCE_INPUT_SNAPSHOT")
    route = route_validation.get("route", route_validation)
    if not isinstance(route, dict):
        raise ValueError("E_V236_ACCEPTANCE_ROUTE")
    binding = {
        "schema_version": ACCEPTANCE_BINDING_SCHEMA_VERSION,
        "product_version": PRODUCT_VERSION,
        "route_receipt_sha256": canonical_json_sha256(route_receipt),
        "route_digest": route.get("route_digest"),
        "actual_target_fingerprint": route.get("actual_target_fingerprint"),
        "actual_target_kind": route.get("actual_target_kind"),
        "release": route.get("release"),
        "protected_snapshot_receipt_sha256": snapshot_receipt.get("receipt_sha256"),
        "snapshot_tree": snapshot_receipt.get("snapshot_tree"),
        "attested_identity_registry_sha256": canonical_json_sha256(identity_registry),
        "evidence_registry_sha256": file_sha256(evidence_registry_path),
        "ledger_sha256": file_sha256(ledger_path),
        "checkpoint_sha256": file_sha256(checkpoint_path),
        "traceability_sha256": file_sha256(traceability_path),
        "tasklist_sha256": file_sha256(tasklist_path),
        "acceptance_input_snapshot_sha256": acceptance_input_snapshot.get(
            "snapshot_sha256"
        ),
        "trusted_release_base": route.get("trusted_release_base"),
        "policy_profile": route.get("policy_profile"),
        "state_gate_profile": route.get("state_gate_profile"),
        "execution_profile": route.get("execution_profile"),
        "required_review_class": route.get("required_review_class"),
        "gates": route.get("gates"),
        "gate_scopes": route.get("gate_scopes"),
        "execution_contract_sha256": route.get("execution_contract_sha256"),
    }
    snapshot_core = {
        key: value
        for key, value in acceptance_input_snapshot.items()
        if key != "snapshot_sha256"
    }
    snapshot_files = acceptance_input_snapshot.get("files")
    tasklist_relative = (
        acceptance_input_snapshot.get("required_inputs", {}).get("tasklist")
        if isinstance(acceptance_input_snapshot.get("required_inputs"), dict)
        else None
    )
    tasklist_records = [
        record
        for record in snapshot_files or []
        if isinstance(record, dict) and record.get("path") == tasklist_relative
    ]
    if (
        any(
            (not isinstance(value, str) or not value)
            for key, value in binding.items()
            if key not in {"release", "gates", "gate_scopes"}
        )
        or type(binding["release"]) is not bool
        or binding["policy_profile"] not in POLICY_PROFILES
        or binding["state_gate_profile"] != binding["policy_profile"]
        or binding["execution_profile"] not in EXECUTION_PROFILES
        or binding["required_review_class"] not in REVIEW_CLASSES
        or not isinstance(binding["gates"], dict)
        or set(binding["gates"]) != V236_GATE_KEYS
        or any(value not in GATE_STATES for value in binding["gates"].values())
        or not isinstance(binding["gate_scopes"], dict)
        or any(
            key not in binding["gates"] or not isinstance(value, str) or not value
            for key, value in binding["gate_scopes"].items()
        )
        or any(
            not isinstance(binding["gate_scopes"].get(key), str)
            or not binding["gate_scopes"][key]
            for key, state in binding["gates"].items()
            if state == "conditional"
        )
        or not _HEX64.fullmatch(binding["execution_contract_sha256"])
        or binding["trusted_release_base"] != snapshot_receipt.get("baseline_commit")
        or binding["actual_target_fingerprint"]
        != snapshot_receipt.get("repository_fingerprint")
        or binding["actual_target_kind"]
        not in {"generic_project", "goal_teams_repository"}
        or (
            binding["actual_target_kind"] == "goal_teams_repository"
            and binding["release"] is True
            and binding["policy_profile"] != "goal-teams-self-release-v2.36"
        )
        or (
            binding["policy_profile"] == "goal-teams-self-release-v2.36"
            and (
                binding["actual_target_kind"] != "goal_teams_repository"
                or binding["release"] is not True
            )
        )
        or acceptance_input_snapshot.get("schema_version")
        != ACCEPTANCE_INPUT_SNAPSHOT_SCHEMA_VERSION
        or acceptance_input_snapshot.get("snapshot_sha256")
        != canonical_json_sha256(snapshot_core)
        or len(tasklist_records) != 1
        or tasklist_records[0].get("sha256") != binding["tasklist_sha256"]
    ):
        raise ValueError("E_V236_ACCEPTANCE_BINDING")
    if validate_acceptance_input_snapshot(
        acceptance_root, acceptance_input_snapshot
    ):
        raise ValueError("E_V236_ACCEPTANCE_INPUT_SNAPSHOT")
    return binding


def _execution_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "execution_profile",
        "required_review_class",
        "gates",
        "gate_scopes",
        "execution_contract_sha256",
    )
    return {key: value.get(key) for key in keys}


_LEGACY_RUNTIME: Any | None = None


def _load_legacy_runtime() -> Any:
    """Load the V2.3 validators lazily to avoid the runtime import cycle."""

    global _LEGACY_RUNTIME
    if _LEGACY_RUNTIME is not None:
        return _LEGACY_RUNTIME
    import importlib.util

    path = Path(__file__).resolve().with_name("goalteams_v23.py")
    spec = importlib.util.spec_from_file_location(
        "_goalteams_v236_acceptance_legacy_runtime", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("E_V236_ACCEPTANCE_LEGACY_RUNTIME")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _LEGACY_RUNTIME = module
    return module


def _validated_evidence_registry(
    evidence_records: Iterable[dict[str, Any]],
    *,
    evidence_root: Path | str | None,
    ledger_events: list[dict[str, Any]] | None,
    source_root: Path | str | None,
    expected_commit: str | None,
    expected_workspace_revision: str | None,
    claimed_valid_evidence_ids: set[str],
) -> tuple[Any, list[dict[str, Any]], set[str], list[str]]:
    """Derive acceptance-eligible Evidence IDs from full legacy validation.

    A caller-provided ID set is only a consistency claim.  It never grants
    validity and must exactly match the registry derived from the raw records.
    """

    runtime = _load_legacy_runtime()
    try:
        records = list(evidence_records)
        claimed_ids = set(claimed_valid_evidence_ids)
    except TypeError:
        empty = runtime.ValidatedEvidenceRegistry({}, None)
        return (
            empty,
            [],
            set(),
            ["E_V236_ACCEPTANCE_EVIDENCE_VALIDATION_CONTEXT"],
        )
    if (
        evidence_root is None
        or not isinstance(ledger_events, list)
        or any(not isinstance(record, dict) for record in records)
    ):
        empty = runtime.ValidatedEvidenceRegistry({}, None)
        return (
            empty,
            records,
            set(),
            ["E_V236_ACCEPTANCE_EVIDENCE_VALIDATION_CONTEXT"],
        )
    try:
        registry, legacy_errors = runtime.build_evidence_registry(
            records,
            Path(evidence_root),
            expected_commit=expected_commit,
            expected_workspace_revision=expected_workspace_revision,
            ledger_events=ledger_events,
            source_root=Path(source_root) if source_root is not None else None,
            # Completion acceptance never admits transport-only canonical
            # fixtures.  That legacy escape hatch remains scoped to the
            # canonical validator and cannot be enabled by this API's caller.
            allow_portable_fixture=False,
        )
    except (OSError, TypeError, ValueError):
        empty = runtime.ValidatedEvidenceRegistry({}, None)
        return empty, records, set(), ["E_V236_ACCEPTANCE_EVIDENCE_SEMANTICS"]
    derived_ids = {
        evidence_id
        for evidence_id, entry in registry.items()
        if isinstance(entry, dict) and entry.get("valid_for_acceptance") is True
    }
    errors = [
        f"E_V236_ACCEPTANCE_EVIDENCE_SEMANTICS:{error}"
        for error in legacy_errors
    ]
    if not records or not derived_ids:
        errors.append("E_V236_ACCEPTANCE_EVIDENCE_REQUIRED")
    if claimed_ids != derived_ids:
        errors.append("E_V236_ACCEPTANCE_EVIDENCE_REGISTRY_MISMATCH")
    return registry, records, derived_ids, sorted(set(errors))


def _validate_route_execution_contract(
    *,
    expected: dict[str, Any],
    route_validation: dict[str, Any],
    harness: dict[str, Any],
    tasks: Mapping[str, Any],
    completion_inputs: dict[str, Any],
    evidence_registry: Any,
    valid_evidence_ids: set[str],
    audit: dict[str, Any],
) -> list[str]:
    """Compare the rederived route contract with Harness, tasks, and proofs."""

    errors: list[str] = []
    route = route_validation.get("route", route_validation)
    expected_execution = _execution_binding(expected)
    if not isinstance(route, dict) or _execution_binding(route) != expected_execution:
        errors.append("E_V236_ACCEPTANCE_ROUTE_EXECUTION_BINDING")
    harness_contract = (
        harness.get("harness_contract") if isinstance(harness, dict) else None
    )
    harness_execution = (
        harness_contract.get("v236_execution_contract")
        if isinstance(harness_contract, dict)
        else None
    )
    gate_checks = (
        harness_contract.get("v236_gate_checks")
        if isinstance(harness_contract, dict)
        else None
    )
    harness_checks_value = (
        harness_contract.get("checks")
        if isinstance(harness_contract, dict)
        else None
    )
    harness_checks: dict[str, dict[str, Any]] = {}
    malformed_harness_checks = not isinstance(harness_checks_value, list)
    runtime = _load_legacy_runtime()
    for item in harness_checks_value if isinstance(harness_checks_value, list) else []:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("check_id"), str)
            or not item["check_id"]
            or item["check_id"] in harness_checks
        ):
            malformed_harness_checks = True
            continue
        harness_checks[item["check_id"]] = item
        for error in runtime.validate_check(
            item, evidence_registry=evidence_registry
        ):
            errors.append(
                f"E_V236_ACCEPTANCE_CHECK_SEMANTICS:{item['check_id']}:{error}"
            )
    if (
        harness_execution != expected_execution
        or not isinstance(gate_checks, dict)
        or malformed_harness_checks
        or not isinstance(harness_contract, dict)
        or harness_contract.get("required_review_class")
        != expected.get("required_review_class")
    ):
        errors.append("E_V236_ACCEPTANCE_HARNESS_GATE_BINDING")
        gate_checks = gate_checks if isinstance(gate_checks, dict) else {}
    if not isinstance(tasks, Mapping):
        errors.append("E_V236_ACCEPTANCE_GATE_TASKS")
        tasks = {}
    for task_id, task in tasks.items():
        if not isinstance(task_id, str) or not isinstance(task, dict):
            errors.append("E_V236_ACCEPTANCE_TASK_SEMANTICS:unknown:E_TASK_TYPE")
            continue
        if task.get("task_id") != task_id:
            errors.append(
                f"E_V236_ACCEPTANCE_TASK_SEMANTICS:{task_id}:E_TASK_ID_BINDING"
            )
        for error in runtime.validate_task(task, evidence_registry=evidence_registry):
            errors.append(
                f"E_V236_ACCEPTANCE_TASK_SEMANTICS:{task_id}:{error}"
            )
    if not isinstance(completion_inputs, dict):
        return sorted(set(errors + ["E_V236_ACCEPTANCE_GATE_RESULTS_REQUIRED"]))
    gate_results = completion_inputs.get("v236_gate_results")
    if _execution_binding(completion_inputs) != expected_execution:
        errors.append("E_V236_ACCEPTANCE_REVIEW_CLASS")
    gates = expected.get("gates")
    if not isinstance(gates, dict) or not isinstance(gate_results, dict):
        return sorted(set(errors + ["E_V236_ACCEPTANCE_GATE_RESULTS_REQUIRED"]))
    if set(gate_checks) != set(gates):
        errors.append("E_V236_ACCEPTANCE_HARNESS_GATE_BINDING")
    if set(gate_results) != set(gates):
        errors.append("E_V236_ACCEPTANCE_GATE_RESULTS_REQUIRED")
        if expected.get("execution_profile") in {"full", "regulated"}:
            errors.append("E_V236_ACCEPTANCE_FULL_GATE_COVERAGE")

    for gate, requirement in sorted(gates.items()):
        result = gate_results.get(gate)
        if not isinstance(result, dict):
            errors.append(f"E_V236_ACCEPTANCE_GATE_RESULT:{gate}")
            continue
        state = result.get("state")
        evidence_refs = result.get("evidence_refs")
        task_refs = result.get("task_refs")
        check_refs = result.get("check_refs")
        expected_checks = gate_checks.get(gate)
        if (
            state not in GATE_RESULT_STATES
            or not isinstance(evidence_refs, list)
            or any(not isinstance(value, str) or not value for value in evidence_refs)
            or not isinstance(task_refs, list)
            or any(not isinstance(value, str) or not value for value in task_refs)
            or not isinstance(check_refs, list)
            or any(not isinstance(value, str) or not value for value in check_refs)
            or expected_checks != check_refs
        ):
            errors.append(f"E_V236_ACCEPTANCE_GATE_RESULT:{gate}")
            continue
        if gate == "completion_audit":
            if evidence_refs or task_refs or check_refs or expected_checks:
                errors.append(
                    "E_V236_ACCEPTANCE_COMPLETION_AUDIT_SELF_REFERENCE"
                )
            if (
                requirement != "required"
                or state != "passed"
                or result.get("external_gate") is not True
                or result.get("audit_state") != "passed"
                or result.get("acceptance_binding_sha256")
                != canonical_json_sha256(expected)
                or not isinstance(audit, dict)
                or audit.get("audit_state") != "passed"
                or audit.get("v236_acceptance_binding") != expected
            ):
                errors.append("E_V236_ACCEPTANCE_COMPLETION_AUDIT")
            continue
        if any(
            check_ref not in harness_checks
            or harness_checks[check_ref].get(
                "check_state", harness_checks[check_ref].get("state")
            )
            != "passed"
            or harness_checks[check_ref].get("evidence_refs") != evidence_refs
            for check_ref in check_refs
        ):
            errors.append(f"E_V236_ACCEPTANCE_GATE_CHECK:{gate}")
        if any(evidence_ref not in valid_evidence_ids for evidence_ref in evidence_refs):
            errors.append(f"E_V236_ACCEPTANCE_GATE_EVIDENCE:{gate}")
        if state == "passed" and (
            not evidence_refs or not check_refs or not task_refs
        ):
            errors.append(f"E_V236_ACCEPTANCE_GATE_PROOF:{gate}")
        if requirement == "required" and state != "passed":
            errors.append(f"E_V236_ACCEPTANCE_GATE_REQUIRED:{gate}")
        elif requirement == "not_required" and state != "not_required":
            errors.append(f"E_V236_ACCEPTANCE_GATE_NOT_REQUIRED:{gate}")
        elif requirement == "conditional" and state == "not_required" and (
            not isinstance(result.get("reason"), str) or not result["reason"].strip()
            or result.get("impact_decision") != "not_applicable"
            or result.get("impact_scope") != expected.get("gate_scopes", {}).get(gate)
        ):
            errors.append(f"E_V236_ACCEPTANCE_GATE_CONDITIONAL:{gate}")
        if state == "not_required" and (
            evidence_refs or check_refs or task_refs
        ):
            errors.append(f"E_V236_ACCEPTANCE_GATE_RESULT:{gate}")
        for task_id in task_refs:
            task = tasks.get(task_id)
            if (
                not isinstance(task, dict)
                or task.get("task_state") != "accepted"
                or task.get("check_state") not in {"passed", "not_required"}
            ):
                errors.append(f"E_V236_ACCEPTANCE_GATE_TASK:{gate}")
            elif (
                task.get("validation_check_id") not in check_refs
                or not isinstance(task.get("evidence_refs"), list)
                or any(
                    evidence_ref not in task["evidence_refs"]
                    for evidence_ref in evidence_refs
                )
            ):
                errors.append(f"E_V236_ACCEPTANCE_GATE_TASK_BINDING:{gate}")
    return sorted(set(errors))


def validate_route_execution_contract(
    *,
    expected: dict[str, Any],
    route_validation: dict[str, Any],
    harness: dict[str, Any],
    tasks: Mapping[str, Any],
    completion_inputs: dict[str, Any],
    evidence_records: Iterable[dict[str, Any]],
    valid_evidence_ids: set[str],
    audit: dict[str, Any],
    evidence_root: Path | str | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    source_root: Path | str | None = None,
    expected_commit: str | None = None,
    expected_workspace_revision: str | None = None,
) -> list[str]:
    """Validate raw Evidence, then resolve every gate to valid legacy objects."""

    registry, records, derived_ids, errors = _validated_evidence_registry(
        evidence_records,
        evidence_root=evidence_root,
        ledger_events=ledger_events,
        source_root=source_root,
        expected_commit=expected_commit,
        expected_workspace_revision=expected_workspace_revision,
        claimed_valid_evidence_ids=valid_evidence_ids,
    )
    evidence_expected = build_acceptance_core_binding(expected)
    bound_ids = {
        record["evidence_id"]
        for record in records
        if isinstance(record, dict)
        and record.get("evidence_id") in derived_ids
        and isinstance(record.get("environment"), dict)
        and record["environment"].get("v236_acceptance_core_binding")
        == evidence_expected
    }
    for evidence_id in sorted(derived_ids - bound_ids):
        errors.append(f"E_V236_ACCEPTANCE_EVIDENCE_BINDING:{evidence_id}")
    errors.extend(
        _validate_route_execution_contract(
            expected=expected,
            route_validation=route_validation,
            harness=harness,
            tasks=tasks,
            completion_inputs=completion_inputs,
            evidence_registry=registry,
            valid_evidence_ids=bound_ids,
            audit=audit,
        )
    )
    return sorted(set(errors))


def validate_acceptance_bindings(
    *,
    expected: dict[str, Any],
    audit: dict[str, Any],
    review: dict[str, Any],
    harness: dict[str, Any],
    evidence_records: Iterable[dict[str, Any]],
    valid_evidence_ids: set[str],
    route_validation: dict[str, Any],
    tasks: Mapping[str, Any],
    completion_inputs: dict[str, Any],
    evidence_root: Path | str | None = None,
    ledger_events: list[dict[str, Any]] | None = None,
    source_root: Path | str | None = None,
    expected_commit: str | None = None,
    expected_workspace_revision: str | None = None,
) -> list[str]:
    errors: list[str] = []
    for label, document in (
        ("AUDIT", audit),
        ("REVIEW", review),
        ("HARNESS", harness),
    ):
        if not isinstance(document, dict) or document.get("v236_acceptance_binding") != expected:
            errors.append(f"E_V236_ACCEPTANCE_{label}_BINDING")

    required_review_class = expected.get("required_review_class")
    actual_review_class = review.get("review_class") if isinstance(review, dict) else None
    if actual_review_class not in REVIEW_CLASS_ALLOWED_ACTUAL.get(
        required_review_class, set()
    ):
        errors.append("E_V236_ACCEPTANCE_REVIEW_CLASS")

    registry, records, derived_ids, registry_errors = _validated_evidence_registry(
        evidence_records,
        evidence_root=evidence_root,
        ledger_events=ledger_events,
        source_root=source_root,
        expected_commit=expected_commit,
        expected_workspace_revision=expected_workspace_revision,
        claimed_valid_evidence_ids=valid_evidence_ids,
    )
    errors.extend(registry_errors)
    evidence_expected = build_acceptance_core_binding(expected)
    bound_evidence_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("evidence_id") not in derived_ids:
            continue
        environment = record.get("environment")
        if (
            not isinstance(environment, dict)
            or environment.get("v236_acceptance_core_binding") != evidence_expected
        ):
            errors.append(
                f"E_V236_ACCEPTANCE_EVIDENCE_BINDING:{record.get('evidence_id', 'unknown')}"
            )
        else:
            bound_evidence_ids.add(record["evidence_id"])
    if not bound_evidence_ids:
        errors.append("E_V236_ACCEPTANCE_EVIDENCE_REQUIRED")
    errors.extend(
        _validate_route_execution_contract(
            expected=expected,
            route_validation=route_validation,
            harness=harness,
            tasks=tasks,
            completion_inputs=completion_inputs,
            evidence_registry=registry,
            valid_evidence_ids=bound_evidence_ids,
            audit=audit,
        )
    )
    return sorted(set(errors))


def build_acceptance_core_binding(expected: dict[str, Any]) -> dict[str, Any]:
    """Return the non-circular binding shared by every current Evidence record."""

    keys = (
        "product_version",
        "route_receipt_sha256",
        "route_digest",
        "actual_target_fingerprint",
        "actual_target_kind",
        "release",
        "protected_snapshot_receipt_sha256",
        "snapshot_tree",
        "attested_identity_registry_sha256",
        "trusted_release_base",
        "policy_profile",
        "state_gate_profile",
        "execution_profile",
        "required_review_class",
        "gates",
        "gate_scopes",
        "execution_contract_sha256",
    )
    if any(key not in expected for key in keys):
        raise ValueError("E_V236_ACCEPTANCE_BINDING")
    return {
        "schema_version": ACCEPTANCE_CORE_BINDING_SCHEMA_VERSION,
        **{key: expected[key] for key in keys},
    }
