#!/usr/bin/env python3
"""Deterministic compilers for V2.38 stable-prefix prompt artifacts.

This module intentionally does not import ``prompt_cache.py``.  The cache
manifest is shared machine input, while compilation and validation remain a
separate concern with independently testable failure modes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


MANIFEST_PATH = "references/prompt-cache-manifest.json"
COMPILER_SCHEMA = "goal-teams-prompt-artifact-compilers-v2.38"
SUBAGENT_SCHEMA = "goal-teams-subagent-common-prefix-v2.38"
PACKET_SCHEMA = "goal-teams-member-goal-packet-v2.38"
COMMON_PREFIX_END = "以下角色说明是稳定公共合同之后的角色专属后缀。\n"
DEVELOPER_BLOCK_RE = re.compile(
    r'(?P<open>^developer_instructions\s*=\s*"""\n)'
    r"(?P<body>.*?)"
    r'(?P<close>\n"""\s*$)',
    flags=re.MULTILINE | re.DOTALL,
)
VERSION_RE = re.compile(
    r'^# common_prefix_version\s*=\s*"(?P<value>[^"]*)"\s*$', re.MULTILINE
)
HASH_RE = re.compile(
    r'^# common_prefix_sha256\s*=\s*"(?P<value>[0-9a-f]*)"\s*$', re.MULTILINE
)


class PromptCompilerError(ValueError):
    """Raised when a source, compiled artifact, or assignment is invalid."""

    def __init__(self, code: str, *, receipt: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.receipt = receipt


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json_file_strict(
    path: Path,
    *,
    duplicate_error: str = "E_PACKET_JSON_DUPLICATE_KEY",
    invalid_error: str = "E_PACKET_JSON_INVALID",
) -> Any:
    """Load JSON while rejecting duplicate keys at every object depth."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PromptCompilerError(duplicate_error)
            result[key] = value
        return result

    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text, object_pairs_hook=reject_duplicates)
    except PromptCompilerError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptCompilerError(invalid_error) from exc


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise PromptCompilerError("E_COMPILER_PATH_EMPTY")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "" in pure.parts:
        raise PromptCompilerError(f"E_COMPILER_PATH_UNSAFE:{relative}")
    path = root.joinpath(*pure.parts)
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise PromptCompilerError(f"E_COMPILER_PATH_ESCAPE:{relative}")
    return path


def _load_manifest_document(root: Path) -> dict[str, Any]:
    path = _safe_path(root, MANIFEST_PATH)
    manifest = load_json_file_strict(
        path,
        duplicate_error="E_COMPILER_MANIFEST_DUPLICATE_KEY",
        invalid_error="E_COMPILER_MANIFEST_READ",
    )
    if not isinstance(manifest, dict):
        raise PromptCompilerError("E_COMPILER_MANIFEST_OBJECT")
    return manifest


def load_compiler_contract(root: Path) -> dict[str, Any]:
    manifest = _load_manifest_document(root)
    contract = manifest.get("artifact_compilers")
    if not isinstance(contract, dict) or contract.get("schema_version") != COMPILER_SCHEMA:
        raise PromptCompilerError("E_COMPILER_MANIFEST_SCHEMA")
    if not isinstance(contract.get("subagent_common_prefix"), dict):
        raise PromptCompilerError("E_COMPILER_SUBAGENT_CONTRACT")
    if not isinstance(contract.get("member_goal_packet"), dict):
        raise PromptCompilerError("E_COMPILER_PACKET_CONTRACT")
    return contract


def load_common_prefix(root: Path) -> dict[str, Any]:
    config = load_compiler_contract(root)["subagent_common_prefix"]
    if config.get("schema_version") != SUBAGENT_SCHEMA:
        raise PromptCompilerError("E_SUBAGENT_PREFIX_SCHEMA")
    version = config.get("common_prefix_version")
    expected_hash = config.get("common_prefix_sha256")
    source_path = config.get("source_path")
    target_glob = config.get("target_glob")
    target_count = config.get("target_count")
    if not isinstance(version, str) or not version:
        raise PromptCompilerError("E_SUBAGENT_PREFIX_VERSION")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise PromptCompilerError("E_SUBAGENT_PREFIX_HASH")
    if not isinstance(source_path, str) or not isinstance(target_glob, str):
        raise PromptCompilerError("E_SUBAGENT_PREFIX_PATHS")
    target_pattern = PurePosixPath(target_glob)
    if target_pattern.is_absolute() or ".." in target_pattern.parts or not target_glob.endswith(".toml"):
        raise PromptCompilerError("E_SUBAGENT_PREFIX_TARGET_GLOB")
    if not isinstance(target_count, int) or target_count < 1:
        raise PromptCompilerError("E_SUBAGENT_PREFIX_TARGET_COUNT")
    source = _safe_path(root, source_path)
    if source.is_symlink():
        raise PromptCompilerError("E_SUBAGENT_PREFIX_SOURCE_SYMLINK")
    try:
        source_bytes = source.read_bytes()
        text = source_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PromptCompilerError("E_SUBAGENT_PREFIX_SOURCE_READ") from exc
    if b"\r" in source_bytes or not text.endswith(COMMON_PREFIX_END):
        raise PromptCompilerError("E_SUBAGENT_PREFIX_SOURCE_FORMAT")
    actual_hash = _sha256(source_bytes)
    if actual_hash != expected_hash:
        raise PromptCompilerError(
            f"E_SUBAGENT_PREFIX_SOURCE_DRIFT:expected={expected_hash}:actual={actual_hash}"
        )
    return {
        "schema_version": SUBAGENT_SCHEMA,
        "common_prefix_version": version,
        "common_prefix_sha256": actual_hash,
        "source_path": source_path,
        "target_glob": target_glob,
        "target_count": target_count,
        "text": text,
        "bytes": len(source_bytes),
    }


def validate_developer_instructions(common_prefix: str, value: str) -> list[str]:
    """Return stable error codes for one compiled developer instruction value."""

    if not isinstance(value, str) or not value:
        return ["E_SUBAGENT_INSTRUCTIONS_EMPTY"]
    if value.startswith(common_prefix):
        suffix = value[len(common_prefix) :]
        if not suffix.strip():
            return ["E_SUBAGENT_ROLE_SUFFIX_EMPTY"]
        if common_prefix in suffix:
            return ["E_SUBAGENT_COMMON_PREFIX_DUPLICATED"]
        return []
    if common_prefix in value:
        return ["E_SUBAGENT_ROLE_BEFORE_COMMON_PREFIX"]
    if COMMON_PREFIX_END in value:
        return ["E_SUBAGENT_COMMON_PREFIX_DRIFT"]
    return ["E_SUBAGENT_COMMON_PREFIX_MISSING"]


def _read_target(path: Path) -> tuple[str, dict[str, Any], re.Match[str]]:
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = tomllib.loads(raw)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PromptCompilerError(f"E_SUBAGENT_TOML_READ:{path.name}") from exc
    matches = list(DEVELOPER_BLOCK_RE.finditer(raw))
    if len(matches) != 1:
        raise PromptCompilerError(f"E_SUBAGENT_DEVELOPER_BLOCK:{path.name}")
    match = matches[0]
    # TOML multiline basic strings retain the newline immediately before the
    # closing delimiter; the raw regex keeps that newline in ``close``.
    if parsed.get("developer_instructions") != match.group("body") + "\n":
        raise PromptCompilerError(f"E_SUBAGENT_DEVELOPER_PARSE_MISMATCH:{path.name}")
    return raw, parsed, match


def _target_paths(root: Path, contract: Mapping[str, Any]) -> list[Path]:
    paths = sorted(root.glob(str(contract["target_glob"])))
    resolved_root = root.resolve()
    for path in paths:
        resolved = path.resolve()
        if (
            not path.is_file()
            or path.is_symlink()
            or resolved_root not in resolved.parents
        ):
            raise PromptCompilerError(f"E_SUBAGENT_TARGET_UNSAFE:{path.name}")
    return paths


def validate_subagent_prefixes(
    root: Path, target_paths: Iterable[Path] | None = None
) -> dict[str, Any]:
    contract = load_common_prefix(root)
    paths = list(target_paths) if target_paths is not None else _target_paths(root, contract)
    errors: list[str] = []
    targets: list[dict[str, Any]] = []
    if target_paths is None and len(paths) != contract["target_count"]:
        errors.append(
            f"E_SUBAGENT_TARGET_COUNT:expected={contract['target_count']}:actual={len(paths)}"
        )
    for path in paths:
        try:
            raw, parsed, _match = _read_target(path)
        except PromptCompilerError as exc:
            errors.append(str(exc))
            continue
        value = parsed.get("developer_instructions")
        value_errors = validate_developer_instructions(contract["text"], value)
        errors.extend(f"{code}:{path.name}" for code in value_errors)
        version_match = VERSION_RE.search(raw)
        hash_match = HASH_RE.search(raw)
        if version_match is None or version_match.group("value") != contract["common_prefix_version"]:
            errors.append(f"E_SUBAGENT_COMPILED_VERSION:{path.name}")
        if hash_match is None or hash_match.group("value") != contract["common_prefix_sha256"]:
            errors.append(f"E_SUBAGENT_COMPILED_HASH:{path.name}")
        targets.append(
            {
                "path": path.relative_to(root).as_posix()
                if root.resolve() in path.resolve().parents
                else path.name,
                "developer_instructions_sha256": _sha256(value.encode("utf-8"))
                if isinstance(value, str)
                else None,
                "passed": not value_errors,
            }
        )
    return {
        "schema_version": SUBAGENT_SCHEMA,
        "common_prefix_version": contract["common_prefix_version"],
        "common_prefix_sha256": contract["common_prefix_sha256"],
        "common_prefix_bytes": contract["bytes"],
        "target_count": len(paths),
        "targets": targets,
        "passed": not errors,
        "errors": errors,
    }


def _role_suffix(value: str, common_prefix: str, path: Path) -> str:
    if value.startswith(common_prefix):
        suffix = value[len(common_prefix) :]
    elif common_prefix in value:
        raise PromptCompilerError(f"E_SUBAGENT_ROLE_BEFORE_COMMON_PREFIX:{path.name}")
    else:
        marker_offset = value.find(COMMON_PREFIX_END)
        if marker_offset < 0:
            raise PromptCompilerError(f"E_SUBAGENT_ROLE_SUFFIX_UNRECOVERABLE:{path.name}")
        suffix = value[marker_offset + len(COMMON_PREFIX_END) :]
    if not suffix.strip():
        raise PromptCompilerError(f"E_SUBAGENT_ROLE_SUFFIX_EMPTY:{path.name}")
    return suffix


def render_subagent_target(root: Path, path: Path) -> str:
    contract = load_common_prefix(root)
    raw, parsed, match = _read_target(path)
    suffix = _role_suffix(parsed["developer_instructions"], contract["text"], path)
    body = contract["text"] + suffix
    rendered = raw[: match.start("body")] + body[:-1] + raw[match.end("body") :]
    # Receipts remain TOML comments so the host agent-config schema sees no
    # new runtime keys.  The manifest remains their machine SSOT.
    version_line = f'# common_prefix_version = "{contract["common_prefix_version"]}"'
    hash_line = f'# common_prefix_sha256 = "{contract["common_prefix_sha256"]}"'
    if VERSION_RE.search(rendered):
        rendered = VERSION_RE.sub(version_line, rendered, count=1)
    else:
        rendered = rendered.replace(match.group("open"), version_line + "\n" + match.group("open"), 1)
    if HASH_RE.search(rendered):
        rendered = HASH_RE.sub(hash_line, rendered, count=1)
    else:
        rendered = rendered.replace(version_line + "\n", version_line + "\n" + hash_line + "\n", 1)
    return rendered


def expand_subagent_prefixes(root: Path, *, write: bool = False) -> dict[str, Any]:
    contract = load_common_prefix(root)
    changed: list[str] = []
    outputs: dict[str, str] = {}
    for path in _target_paths(root, contract):
        rendered = render_subagent_target(root, path)
        relative = path.relative_to(root).as_posix()
        outputs[relative] = rendered
        if rendered != path.read_text(encoding="utf-8"):
            changed.append(relative)
    if write:
        for relative in changed:
            _atomic_write(_safe_path(root, relative), outputs[relative])
    result = {
        "schema_version": SUBAGENT_SCHEMA,
        "common_prefix_version": contract["common_prefix_version"],
        "common_prefix_sha256": contract["common_prefix_sha256"],
        "target_count": len(outputs),
        "changed": changed,
        "write": write,
        "outputs": outputs,
    }
    if write:
        validation = validate_subagent_prefixes(root)
        if not validation["passed"]:
            raise PromptCompilerError("E_SUBAGENT_EXPAND_POST_VALIDATION:" + ",".join(validation["errors"]))
    return result


def _packet_contract(root: Path) -> dict[str, Any]:
    manifest = _load_manifest_document(root)
    compiler_contract = manifest.get("artifact_compilers")
    if (
        not isinstance(compiler_contract, dict)
        or compiler_contract.get("schema_version") != COMPILER_SCHEMA
    ):
        raise PromptCompilerError("E_COMPILER_MANIFEST_SCHEMA")
    config = compiler_contract.get("member_goal_packet")
    if not isinstance(config, dict):
        raise PromptCompilerError("E_COMPILER_PACKET_CONTRACT")
    if config.get("schema_version") != PACKET_SCHEMA:
        raise PromptCompilerError("E_PACKET_SCHEMA")
    template_path = config.get("template_path")
    marker = config.get("dynamic_tail_marker")
    fields = config.get("ordered_dynamic_fields")
    legacy_map = config.get("legacy_key_map")
    if not isinstance(template_path, str) or not isinstance(marker, str) or not marker:
        raise PromptCompilerError("E_PACKET_TEMPLATE_CONTRACT")
    if not isinstance(fields, list) or not fields or any(not isinstance(v, str) or not v for v in fields):
        raise PromptCompilerError("E_PACKET_FIELDS")
    if len(fields) != len(set(fields)):
        raise PromptCompilerError("E_PACKET_FIELDS_DUPLICATE")
    if not isinstance(legacy_map, dict) or set(legacy_map.values()) != set(fields):
        raise PromptCompilerError("E_PACKET_LEGACY_MAP")
    template = _safe_path(root, template_path)
    try:
        template_text = template.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PromptCompilerError("E_PACKET_TEMPLATE_READ") from exc
    if template_text.count(marker) != 1:
        raise PromptCompilerError("E_PACKET_DYNAMIC_MARKER")
    budget_policy = manifest.get("budget_policy")
    dynamic_limit = (
        budget_policy.get("dynamic_packet_max_bytes")
        if isinstance(budget_policy, dict)
        else None
    )
    if (
        not isinstance(dynamic_limit, int)
        or isinstance(dynamic_limit, bool)
        or dynamic_limit < 1
    ):
        raise PromptCompilerError("E_PACKET_DYNAMIC_BUDGET_CONTRACT")
    marker_end = template_text.index(marker) + len(marker)
    stable_prefix = template_text[:marker_end]
    return {
        "schema_version": PACKET_SCHEMA,
        "template_path": template_path,
        "dynamic_tail_marker": marker,
        "ordered_dynamic_fields": fields,
        "legacy_key_map": legacy_map,
        "stable_prefix": stable_prefix,
        "dynamic_packet_max_bytes": dynamic_limit,
    }


def _canonical_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise PromptCompilerError(f"E_PACKET_FLOAT_UNSUPPORTED:{path}")
    if isinstance(value, list):
        return [_canonical_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise PromptCompilerError(f"E_PACKET_NON_STRING_KEY:{path}")
        return {
            key: _canonical_value(value[key], f"{path}.{key}")
            for key in sorted(value)
        }
    raise PromptCompilerError(f"E_PACKET_VALUE_TYPE:{path}:{type(value).__name__}")


def _canonical_assignment_for_fields(
    assignment: Mapping[str, Any], fields: Sequence[str]
) -> dict[str, Any]:
    missing = [field for field in fields if field not in assignment]
    extra = sorted(set(assignment) - set(fields))
    if missing:
        raise PromptCompilerError("E_PACKET_FIELDS_MISSING:" + ",".join(missing))
    if extra:
        raise PromptCompilerError("E_PACKET_FIELDS_UNKNOWN:" + ",".join(extra))
    return {field: _canonical_value(assignment[field], field) for field in fields}


def canonical_assignment(root: Path, assignment: Mapping[str, Any]) -> dict[str, Any]:
    contract = _packet_contract(root)
    return _canonical_assignment_for_fields(assignment, contract["ordered_dynamic_fields"])


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    ) + "\n"


def serialize_member_goal_packet(root: Path, assignment: Mapping[str, Any]) -> dict[str, Any]:
    """Compile an actual packet and return digests over its real byte surfaces."""

    contract = _packet_contract(root)
    canonical = _canonical_assignment_for_fields(
        assignment, contract["ordered_dynamic_fields"]
    )
    stable_bytes = contract["stable_prefix"].encode("utf-8")
    dynamic_bytes = _canonical_json(canonical).encode("utf-8")
    dynamic_actual = len(dynamic_bytes)
    dynamic_limit = contract["dynamic_packet_max_bytes"]
    budget_passed = dynamic_actual <= dynamic_limit
    budget_receipt = {
        "schema_version": "goal-teams-dynamic-packet-budget-receipt-v2.38",
        "source": "references/prompt-cache-manifest.json#/budget_policy/dynamic_packet_max_bytes",
        "declared": {"dynamic_packet_max_bytes": dynamic_limit},
        "actual": {"dynamic_assignment_bytes": dynamic_actual},
        "passed": budget_passed,
        "violations": []
        if budget_passed
        else ["E_PACKET_DYNAMIC_BUDGET_EXCEEDED"],
        "final_action": "accept" if budget_passed else "reject",
    }
    if not budget_passed:
        raise PromptCompilerError(
            "E_PACKET_DYNAMIC_BUDGET_EXCEEDED", receipt=budget_receipt
        )
    dynamic_digest = _sha256(dynamic_bytes)
    envelope = {
        "schema_version": PACKET_SCHEMA,
        "assignment": canonical,
        "dynamic_assignment_sha256": dynamic_digest,
    }
    rendered_tail = "\n\n## Dynamic Instance Tail\n\n```json\n" + _canonical_json(envelope) + "```\n"
    packet_bytes = stable_bytes + rendered_tail.encode("utf-8")
    return {
        "schema_version": PACKET_SCHEMA,
        "template_path": contract["template_path"],
        "stable_prefix_sha256": _sha256(stable_bytes),
        "dynamic_assignment_sha256": dynamic_digest,
        "combined_packet_sha256": _sha256(packet_bytes),
        "stable_prefix_bytes": len(stable_bytes),
        "dynamic_assignment_bytes": len(dynamic_bytes),
        "combined_packet_bytes": len(packet_bytes),
        "dynamic_budget_receipt": budget_receipt,
        "packet_text": packet_bytes.decode("utf-8"),
    }


def migrate_legacy_member_goal_packet(root: Path, legacy: Mapping[str, Any]) -> dict[str, Any]:
    """Map a legacy fixture without inventing hashes for the legacy source."""

    contract = _packet_contract(root)
    legacy_map = contract["legacy_key_map"]
    missing = [key for key in legacy_map if key not in legacy]
    if missing:
        raise PromptCompilerError("E_PACKET_LEGACY_FIELDS_MISSING:" + ",".join(missing))
    mapped = {target: legacy[source] for source, target in legacy_map.items()}
    source_bytes = json.dumps(
        _canonical_value(dict(legacy), "legacy"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    compiled = serialize_member_goal_packet(root, mapped)
    return {
        "schema_version": "goal-teams-member-goal-packet-migration-v2.38",
        "migration_state": "legacy_mapped",
        "legacy_schema_version": legacy.get("schema_version", "legacy/unversioned"),
        "legacy_source_sha256": _sha256(source_bytes),
        "legacy_digest_status": "legacy/unavailable",
        "legacy_stable_prefix_sha256": None,
        "legacy_dynamic_assignment_sha256": None,
        "legacy_combined_packet_sha256": None,
        "compiled": compiled,
    }


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o644
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _write_packet_outputs(result: Mapping[str, Any], output: Path, metadata: Path) -> None:
    _atomic_write(output, str(result["packet_text"]))
    public = {key: value for key, value in result.items() if key != "packet_text"}
    _atomic_write(metadata, json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check-subagents")
    check.set_defaults(write=False)
    expand = subparsers.add_parser("expand-subagents")
    expand.add_argument("--write", action="store_true")
    packet = subparsers.add_parser("compile-packet")
    packet.add_argument("--assignment", type=Path, required=True)
    packet.add_argument("--output", type=Path, required=True)
    packet.add_argument("--metadata", type=Path, required=True)
    migrate = subparsers.add_parser("migrate-packet")
    migrate.add_argument("--legacy", type=Path, required=True)
    migrate.add_argument("--output", type=Path, required=True)
    migrate.add_argument("--metadata", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "check-subagents":
            result = validate_subagent_prefixes(root)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["passed"] else 1
        if args.command == "expand-subagents":
            result = expand_subagent_prefixes(root, write=args.write)
            public = {key: value for key, value in result.items() if key != "outputs"}
            print(json.dumps(public, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "compile-packet":
            assignment = load_json_file_strict(args.assignment)
            if not isinstance(assignment, dict):
                raise PromptCompilerError("E_PACKET_JSON_OBJECT_REQUIRED")
            result = serialize_member_goal_packet(root, assignment)
            _write_packet_outputs(result, args.output, args.metadata)
            print(json.dumps({key: value for key, value in result.items() if key != "packet_text"}, sort_keys=True))
            return 0
        legacy = load_json_file_strict(args.legacy)
        if not isinstance(legacy, dict):
            raise PromptCompilerError("E_PACKET_JSON_OBJECT_REQUIRED")
        migration = migrate_legacy_member_goal_packet(root, legacy)
        _atomic_write(args.output, migration["compiled"]["packet_text"])
        migration_sidecar = {
            key: value for key, value in migration.items() if key != "compiled"
        }
        migration_sidecar["compiled"] = {
            key: value
            for key, value in migration["compiled"].items()
            if key != "packet_text"
        }
        _atomic_write(
            args.metadata,
            json.dumps(migration_sidecar, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        print(
            json.dumps(
                {key: value for key, value in migration.items() if key != "compiled"},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (PromptCompilerError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        failure = {"passed": False, "error": str(exc)}
        if isinstance(exc, PromptCompilerError) and exc.receipt is not None:
            failure["dynamic_budget_receipt"] = exc.receipt
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
