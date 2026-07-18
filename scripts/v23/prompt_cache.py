#!/usr/bin/env python3
"""V2.38 ordered prompt planning and observer-usage normalization.

Route-static digests identify only Goal Teams-controlled files.  Runtime and
stable-prefix digests are emitted only from a host-supplied final ordered
prompt manifest; route plans never impersonate the provider request.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping


MANIFEST_RELATIVE_PATH = "references/prompt-cache-manifest.json"
SCHEMA_VERSION = "goal-teams-prompt-cache-v2.38"


class PromptCacheContractError(ValueError):
    """Raised when a prompt manifest cannot be reproduced safely."""


class _DuplicateJsonKeyError(ValueError):
    pass


def _strict_json_loads(raw: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKeyError(key)
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=reject_duplicates)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _relative_path(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise PromptCacheContractError("E_PROMPT_MANIFEST_PATH")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != raw:
        raise PromptCacheContractError("E_PROMPT_MANIFEST_PATH")
    return raw


def _safe_file(root: Path, relative: str) -> Path:
    relative = _relative_path(relative)
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        try:
            metadata = cursor.lstat()
        except OSError as exc:
            raise PromptCacheContractError(
                f"E_PROMPT_MANIFEST_MISSING:{relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PromptCacheContractError(f"E_PROMPT_MANIFEST_SYMLINK:{relative}")
    if not cursor.is_file():
        raise PromptCacheContractError(f"E_PROMPT_MANIFEST_FILE:{relative}")
    try:
        cursor.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PromptCacheContractError(f"E_PROMPT_MANIFEST_ESCAPE:{relative}") from exc
    return cursor


def load_prompt_manifest(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    path = _safe_file(root, MANIFEST_RELATIVE_PATH)
    try:
        manifest = _strict_json_loads(path.read_text(encoding="utf-8"))
    except _DuplicateJsonKeyError as exc:
        raise PromptCacheContractError("E_PROMPT_MANIFEST_DUPLICATE_KEY") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptCacheContractError("E_PROMPT_MANIFEST_JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise PromptCacheContractError("E_PROMPT_MANIFEST_SCHEMA")
    budget = manifest.get("budget_policy")
    if (
        not isinstance(budget, dict)
        or budget.get("schema_version") != "goal-teams-route-context-budget-v1"
        or not isinstance(budget.get("minimum_headroom_bytes"), int)
        or isinstance(budget.get("minimum_headroom_bytes"), bool)
        or budget["minimum_headroom_bytes"] < 0
        or not isinstance(budget.get("minimum_headroom_ratio"), (int, float))
        or isinstance(budget.get("minimum_headroom_ratio"), bool)
        or not 0 <= budget["minimum_headroom_ratio"] < 1
        or not isinstance(budget.get("dynamic_packet_max_bytes"), int)
        or budget["dynamic_packet_max_bytes"] <= 0
        or not isinstance(budget.get("max_segment_count"), int)
        or budget["max_segment_count"] <= 0
        or not isinstance(budget.get("max_file_count"), int)
        or budget["max_file_count"] <= 0
        or budget.get("token_budget_status") not in {"measured", "estimated", "unavailable"}
        or budget.get("exceed_action") not in {"block", "replan"}
    ):
        raise PromptCacheContractError("E_PROMPT_MANIFEST_BUDGET")
    routes = manifest.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise PromptCacheContractError("E_PROMPT_MANIFEST_ROUTES")
    for route_id, route in routes.items():
        if not isinstance(route_id, str) or not route_id or not isinstance(route, dict):
            raise PromptCacheContractError("E_PROMPT_MANIFEST_ROUTE")
        refs = route.get("ordered_refs")
        limit = route.get("limit_bytes")
        labels = route.get("dynamic_tail_labels", [])
        if (
            not isinstance(refs, list)
            or not refs
            or len(refs) != len(set(refs))
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
            or not isinstance(labels, list)
            or not all(isinstance(item, str) and item for item in labels)
        ):
            raise PromptCacheContractError(f"E_PROMPT_MANIFEST_ROUTE:{route_id}")
        for relative in refs:
            _relative_path(relative)
    order = manifest.get("reference_order", [])
    if not isinstance(order, list) or len(order) != len(set(order)):
        raise PromptCacheContractError("E_PROMPT_MANIFEST_ORDER")
    for relative in order:
        _relative_path(relative)
    return manifest


def _route_budget_receipt(
    manifest: dict[str, Any],
    route_id: str,
    route_bytes: int,
    ordered_refs: list[str],
    dynamic_tail_labels: list[str],
    limit: int,
) -> dict[str, Any]:
    policy = manifest["budget_policy"]
    minimum_headroom = max(
        int(policy["minimum_headroom_bytes"]),
        math.ceil(limit * float(policy["minimum_headroom_ratio"])),
    )
    headroom = limit - route_bytes
    segment_count = len(ordered_refs) + len(dynamic_tail_labels)
    violations: list[str] = []
    if route_bytes > limit:
        violations.append("stable_route_max_bytes")
    if headroom < minimum_headroom:
        violations.append("minimum_headroom")
    if len(ordered_refs) > int(policy["max_file_count"]):
        violations.append("max_file_count")
    if segment_count > int(policy["max_segment_count"]):
        violations.append("max_segment_count")
    return {
        "schema_version": policy["schema_version"],
        "route_id": route_id,
        "declared": {
            "stable_route_max_bytes": limit,
            "minimum_headroom_bytes": minimum_headroom,
            "minimum_headroom_ratio": policy["minimum_headroom_ratio"],
            "dynamic_packet_max_bytes": policy["dynamic_packet_max_bytes"],
            "max_segment_count": policy["max_segment_count"],
            "max_file_count": policy["max_file_count"],
            "token_budget_status": policy["token_budget_status"],
            "max_estimated_tokens": policy.get("max_estimated_tokens"),
            "budget_source": policy.get("budget_source"),
            "exceed_action": policy["exceed_action"],
        },
        "actual": {
            "stable_route_bytes": route_bytes,
            "headroom_bytes": headroom,
            "file_count": len(ordered_refs),
            "segment_count": segment_count,
            "dynamic_packet_bytes": None,
            "dynamic_packet_status": "unavailable_until_final_assembly",
            "estimated_tokens": None,
        },
        "violations": violations,
        "passed": not violations,
        "final_action": policy["exceed_action"] if violations else "report_only_dynamic_unavailable",
    }


def order_prompt_refs(root: Path, refs: Iterable[str]) -> list[str]:
    """Order an existing legacy set without changing its membership."""

    manifest = load_prompt_manifest(root)
    incoming = list(refs)
    if len(incoming) != len(set(incoming)):
        raise PromptCacheContractError("E_PROMPT_REFS_DUPLICATE")
    order = list(manifest.get("reference_order", []))
    position = {path: index for index, path in enumerate(order)}
    unknown = sorted(set(incoming) - set(position))
    if unknown:
        raise PromptCacheContractError(f"E_PROMPT_REFS_UNMANAGED:{','.join(unknown)}")
    return sorted(incoming, key=position.__getitem__)


def build_prompt_identity(root: Path, route_id: str) -> dict[str, Any]:
    root = Path(root).resolve()
    manifest = load_prompt_manifest(root)
    route = manifest["routes"].get(route_id)
    if not isinstance(route, dict):
        raise PromptCacheContractError(f"E_PROMPT_ROUTE_UNKNOWN:{route_id}")
    ordered_refs = list(route["ordered_refs"])
    labels = list(route.get("dynamic_tail_labels", []))
    prefix_payload = {
        "schema_version": SCHEMA_VERSION,
        "route_id": route_id,
        "ordered_refs": ordered_refs,
        "dynamic_tail_labels": labels,
    }
    route_static = hashlib.sha256()
    route_static.update(b"goal-teams-route-static-v2.38\0")
    route_static.update(route_id.encode("utf-8") + b"\0")
    files: dict[str, dict[str, Any]] = {}
    route_bytes = 0
    for relative in ordered_refs:
        data = _safe_file(root, relative).read_bytes()
        route_bytes += len(data)
        file_sha = _sha256(data)
        files[relative] = {"bytes": len(data), "sha256": file_sha}
        route_static.update(relative.encode("utf-8") + b"\0")
        route_static.update(str(len(data)).encode("ascii") + b"\0")
        route_static.update(data)
        route_static.update(b"\0")
    limit = int(route["limit_bytes"])
    budget_receipt = _route_budget_receipt(
        manifest, route_id, route_bytes, ordered_refs, labels, limit
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_identity_version": "V2.38",
        "route_id": route_id,
        "ordered_refs": ordered_refs,
        "dynamic_tail_labels": labels,
        "prefix_manifest_sha256": _sha256(_canonical_bytes(prefix_payload)),
        "route_static_digest": route_static.hexdigest(),
        "manifest_status": "unavailable",
        "digest_scope": "partial",
        "identity_scope": "route_static_only",
        "stable_prefix_digest": None,
        "runtime_prompt_digest": None,
        "missing_segment_classes": [
            "host_system_developer",
            "runtime_dynamic_tail",
            "user_input",
            "tool_results",
            "provider_adapter_injections",
        ],
        "route_bytes": route_bytes,
        "limit_bytes": limit,
        "passed": budget_receipt["passed"],
        "budget_receipt": budget_receipt,
        "files": files,
        "provider_cache_key": None,
    }


def build_prompt_identity_for_refs(
    root: Path,
    route_id: str,
    ordered_refs: Iterable[str],
) -> dict[str, Any]:
    """Compile an ordered subset such as a signed structured policy rule set."""

    root = Path(root).resolve()
    manifest = load_prompt_manifest(root)
    route = manifest["routes"].get(route_id)
    if not isinstance(route, dict) or route.get("selection_mode") != "ordered_subset_of_policy_rule_set":
        raise PromptCacheContractError(f"E_PROMPT_ROUTE_NOT_SUBSET:{route_id}")
    refs = list(ordered_refs)
    if not refs or len(refs) != len(set(refs)):
        raise PromptCacheContractError("E_PROMPT_REFS_DUPLICATE")
    canonical_order = order_prompt_refs(root, refs)
    if refs != canonical_order:
        raise PromptCacheContractError("E_PROMPT_REFS_ORDER")
    allowed = set(route["ordered_refs"])
    unmanaged = sorted(set(refs) - allowed)
    if unmanaged:
        raise PromptCacheContractError(f"E_PROMPT_REFS_UNMANAGED:{','.join(unmanaged)}")
    labels = list(route.get("dynamic_tail_labels", []))
    prefix_payload = {
        "schema_version": SCHEMA_VERSION,
        "route_id": route_id,
        "ordered_refs": refs,
        "dynamic_tail_labels": labels,
    }
    route_static = hashlib.sha256()
    route_static.update(b"goal-teams-route-static-v2.38\0")
    route_static.update(route_id.encode("utf-8") + b"\0")
    files: dict[str, dict[str, Any]] = {}
    route_bytes = 0
    for relative in refs:
        data = _safe_file(root, relative).read_bytes()
        route_bytes += len(data)
        files[relative] = {"bytes": len(data), "sha256": _sha256(data)}
        route_static.update(relative.encode("utf-8") + b"\0")
        route_static.update(str(len(data)).encode("ascii") + b"\0")
        route_static.update(data)
        route_static.update(b"\0")
    limit = int(route["limit_bytes"])
    budget_receipt = _route_budget_receipt(
        manifest, route_id, route_bytes, refs, labels, limit
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_identity_version": "V2.38",
        "route_id": route_id,
        "selection_mode": route["selection_mode"],
        "ordered_refs": refs,
        "dynamic_tail_labels": labels,
        "prefix_manifest_sha256": _sha256(_canonical_bytes(prefix_payload)),
        "route_static_digest": route_static.hexdigest(),
        "manifest_status": "unavailable",
        "digest_scope": "partial",
        "identity_scope": "route_static_only",
        "stable_prefix_digest": None,
        "runtime_prompt_digest": None,
        "missing_segment_classes": [
            "host_system_developer",
            "runtime_dynamic_tail",
            "user_input",
            "tool_results",
            "provider_adapter_injections",
        ],
        "route_bytes": route_bytes,
        "limit_bytes": limit,
        "passed": budget_receipt["passed"],
        "budget_receipt": budget_receipt,
        "files": files,
        "provider_cache_key": None,
    }


def _domain_digest(domain: bytes, value: Any) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    digest.update(_canonical_bytes(value))
    return digest.hexdigest()


def _safe_segment_source_ref(source_type: Any, source_ref: Any) -> bool:
    if (
        not isinstance(source_ref, str)
        or not source_ref
        or len(source_ref) > 512
        or any(ord(character) < 33 or character.isspace() for character in source_ref)
    ):
        return False
    if source_type == "file":
        try:
            relative = _relative_path(source_ref)
        except PromptCacheContractError:
            return False
        allowed_names = {"VERSION", "AGENTS.md", "RULES.md", "SKILL.md"}
        allowed_suffixes = {
            ".md",
            ".json",
            ".jsonl",
            ".toml",
            ".yaml",
            ".yml",
            ".txt",
            ".py",
            ".sh",
            ".lock",
        }
        return relative in allowed_names or PurePosixPath(relative).suffix in allowed_suffixes
    if ":" not in source_ref:
        return False
    scheme, value = source_ref.split(":", 1)
    if not value:
        return False
    if scheme == "sha256":
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )
    if scheme == "opaque":
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )
    allowed_schemes = {
        "host": {"host", "opaque", "redacted"},
        "provider_adapter": {"provider", "opaque", "redacted"},
        "user": {"opaque", "redacted"},
        "tool": {"opaque", "redacted"},
        "runtime": {"opaque", "redacted"},
        "generated": {"generated", "opaque", "redacted"},
    }
    if scheme not in allowed_schemes.get(str(source_type), set()):
        return False
    lowered = value.casefold()
    if any(
        marker in lowered
        for marker in (
            "sk-", "ghp_", "github_pat_", "akia", "bearer", "to" + "ken=", "password"
        )
    ):
        return False
    return len(value) <= 128 and all(
        character.isalnum() or character in "._-" for character in value
    )


def build_ordered_prompt_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    """Digest a host-observed final ordered prompt manifest.

    The caller, not this repository module, owns the final request assembly
    boundary.  Only segment metadata and content hashes are accepted so raw
    prompts and secrets are not persisted by this helper.
    """

    if not isinstance(manifest, dict) or manifest.get("schema_version") != "goal-teams-ordered-prompt-manifest-v1":
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_SCHEMA")
    allowed_manifest_fields = {
        "schema_version",
        "manifest_id",
        "product_version",
        "agent_run_id",
        "turn_id",
        "route_id",
        "policy_profile",
        "manifest_status",
        "digest_scope",
        "missing_segment_classes",
        "stable_segment_count",
        "dynamic_segment_count",
        "platform_managed_segment_count",
        "canonicalization",
        "segments",
    }
    if set(manifest) != allowed_manifest_fields:
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_UNKNOWN_FIELD")
    identity_fields = (
        "manifest_id",
        "product_version",
        "agent_run_id",
        "turn_id",
        "route_id",
        "policy_profile",
    )
    if any(
        not isinstance(manifest.get(field), str)
        or not manifest[field].strip()
        or len(manifest[field]) > 256
        or any(ord(character) < 32 for character in manifest[field])
        for field in identity_fields
    ):
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_IDENTITY")
    if manifest["product_version"] != "V2.38":
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_VERSION")
    status = manifest.get("manifest_status")
    scope = manifest.get("digest_scope")
    missing = manifest.get("missing_segment_classes", [])
    allowed_missing_classes = {
        "host_system_developer",
        "skill_auto_load",
        "route_references",
        "member_common",
        "member_role",
        "member_goal_packet",
        "runtime_dynamic_tail",
        "user_input",
        "tool_results",
        "provider_adapter_injections",
    }
    if (
        not isinstance(missing, list)
        or not all(
            isinstance(item, str) and item in allowed_missing_classes
            for item in missing
        )
        or len(missing) != len(set(missing))
    ):
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_MISSING")
    if not (
        (status == "available" and scope == "complete" and not missing)
        or (status == "partial" and scope == "partial" and bool(missing))
    ):
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_SCOPE")
    declared_counts = {
        "stable": manifest.get("stable_segment_count"),
        "dynamic": manifest.get("dynamic_segment_count"),
        "platform_managed": manifest.get("platform_managed_segment_count"),
    }
    if (
        manifest.get("canonicalization") != "utf8-lf-json-jcs-v1"
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in declared_counts.values()
        )
    ):
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_CANONICAL")
    segments = manifest.get("segments")
    if not isinstance(segments, list) or not segments:
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_SEGMENTS")
    normalized: list[dict[str, Any]] = []
    dynamic_seen = False
    goal_stable_seen = False
    segment_ids: set[str] = set()
    allowed_segment_fields = {
        "order",
        "segment_id",
        "segment_class",
        "source_type",
        "source_ref",
        "content_sha256",
        "byte_count",
        "token_count",
        "token_count_status",
        "inclusion_reason",
        "inclusion_state",
        "redaction_state",
    }
    for expected_order, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("order") != expected_order:
            raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_ORDER")
        if set(segment) != allowed_segment_fields:
            raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_SEGMENT_FIELD")
        segment_id = segment.get("segment_id")
        segment_class = segment.get("segment_class")
        content_sha256 = segment.get("content_sha256")
        byte_count = segment.get("byte_count")
        inclusion_state = segment.get("inclusion_state", "included")
        source_type = segment.get("source_type")
        source_ref = segment.get("source_ref")
        inclusion_reason = segment.get("inclusion_reason")
        redaction_state = segment.get("redaction_state")
        token_count = segment.get("token_count")
        token_count_status = segment.get("token_count_status")
        if (
            any(
                required not in segment
                for required in (
                    "order",
                    "segment_id",
                    "segment_class",
                    "source_type",
                    "source_ref",
                    "content_sha256",
                    "byte_count",
                    "token_count",
                    "token_count_status",
                    "inclusion_reason",
                    "inclusion_state",
                    "redaction_state",
                )
            )
            or
            not isinstance(segment_id, str)
            or not segment_id
            or len(segment_id) > 128
            or not all(
                character.isalnum() or character in "._:-"
                for character in segment_id
            )
            or segment_id in segment_ids
            or segment_class not in {"stable", "dynamic", "platform_managed"}
            or not isinstance(content_sha256, str)
            or len(content_sha256) != 64
            or any(character not in "0123456789abcdef" for character in content_sha256)
            or not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 0
            or inclusion_state not in {"included", "omitted", "redacted"}
            or source_type not in {
                "file",
                "host",
                "user",
                "tool",
                "runtime",
                "provider_adapter",
                "generated",
            }
            or not _safe_segment_source_ref(source_type, source_ref)
            or not isinstance(inclusion_reason, str)
            or not inclusion_reason
            or len(inclusion_reason) > 128
            or not all(
                character.isalnum() or character in "._:-"
                for character in inclusion_reason
            )
            or redaction_state not in {
                "content_not_persisted",
                "metadata_only",
                "redacted",
            }
            or token_count_status not in {"measured", "estimated", "unavailable"}
            or (
                token_count_status == "unavailable"
                and token_count is not None
            )
            or (
                token_count_status in {"measured", "estimated"}
                and (
                    not isinstance(token_count, int)
                    or isinstance(token_count, bool)
                    or token_count < 0
                )
            )
        ):
            raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_SEGMENT")
        source_types_by_class = {
            "platform_managed": {"host", "provider_adapter"},
            "stable": {"file", "generated"},
            "dynamic": {"file", "user", "tool", "runtime", "generated"},
        }
        if source_type not in source_types_by_class[segment_class]:
            raise PromptCacheContractError(
                "E_ORDERED_PROMPT_MANIFEST_SOURCE_CLASS"
            )
        segment_ids.add(segment_id)
        if inclusion_state != "omitted":
            if segment_class == "platform_managed":
                if goal_stable_seen or dynamic_seen:
                    raise PromptCacheContractError(
                        "E_ORDERED_PROMPT_PLATFORM_MANAGED_ORDER"
                    )
            elif segment_class == "stable":
                if dynamic_seen:
                    raise PromptCacheContractError(
                        "E_ORDERED_PROMPT_STABLE_AFTER_DYNAMIC"
                    )
                goal_stable_seen = True
            else:
                dynamic_seen = True
        normalized_segment = {
            "order": expected_order,
            "segment_id": segment_id,
            "segment_class": segment_class,
            "content_sha256": content_sha256,
            "byte_count": byte_count,
            "inclusion_state": inclusion_state,
            "source_type": source_type,
            "source_ref": source_ref,
            "inclusion_reason": inclusion_reason,
            "redaction_state": redaction_state,
            "token_count": token_count,
            "token_count_status": token_count_status,
        }
        normalized.append(normalized_segment)
    actual_counts = {
        segment_class: sum(
            item["segment_class"] == segment_class for item in normalized
        )
        for segment_class in ("stable", "dynamic", "platform_managed")
    }
    if actual_counts != declared_counts:
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_COUNT")
    effective_segments: list[dict[str, Any]] = []
    for item in normalized:
        if item["inclusion_state"] == "omitted":
            continue
        projected = dict(item)
        projected["order"] = len(effective_segments)
        effective_segments.append(projected)
    stable_prefix = [
        item
        for item in effective_segments
        if item["segment_class"] in {"platform_managed", "stable"}
    ]
    manifest_payload = {
        "schema_version": manifest["schema_version"],
        "manifest_id": manifest.get("manifest_id"),
        "product_version": manifest.get("product_version"),
        "agent_run_id": manifest.get("agent_run_id"),
        "turn_id": manifest.get("turn_id"),
        "route_id": manifest.get("route_id"),
        "policy_profile": manifest.get("policy_profile"),
        "manifest_status": status,
        "digest_scope": scope,
        "missing_segment_classes": missing,
        "stable_segment_count": declared_counts["stable"],
        "dynamic_segment_count": declared_counts["dynamic"],
        "platform_managed_segment_count": declared_counts["platform_managed"],
        "canonicalization": manifest["canonicalization"],
        "segments": normalized,
    }
    return {
        "schema_version": "goal-teams-runtime-prompt-identity-v2.38",
        "manifest_id": manifest["manifest_id"],
        "product_version": manifest["product_version"],
        "agent_run_id": manifest["agent_run_id"],
        "turn_id": manifest["turn_id"],
        "route_id": manifest["route_id"],
        "policy_profile": manifest["policy_profile"],
        "manifest_status": status,
        "digest_scope": scope,
        "missing_segment_classes": list(missing),
        "ordered_prompt_manifest_sha256": _sha256(_canonical_bytes(manifest_payload)),
        "stable_prefix_digest": _domain_digest(
            b"goal-teams-stable-prefix-v1\0", stable_prefix
        ),
        "runtime_prompt_digest": _domain_digest(
            b"goal-teams-runtime-prompt-v1\0", effective_segments
        ),
        "stable_segment_count": sum(
            item["segment_class"] == "stable" for item in normalized
        ),
        "platform_managed_segment_count": sum(
            item["segment_class"] == "platform_managed" for item in normalized
        ),
        "stable_prefix_segment_count": len(stable_prefix),
        "effective_segment_count": len(effective_segments),
        "provider_cache_key": None,
    }


def _usage_integer(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def aggregate_usage_events(jsonl_text: str) -> dict[str, Any]:
    """Normalize Codex turn aggregates without inventing request-level hits."""

    parser_version = "goal-teams-codex-usage-parser-v2.38.1"
    adapter_registry_version = "goal-teams-event-adapter-registry-v1"
    supported_schema_versions = {None, "codex-turn-completed-v1"}
    supported_adapter_versions = {None, "codex-cli-jsonl-v1"}
    terminal_events_observed = 0
    completed_turns = 0
    telemetry_turns = 0
    input_tokens = 0
    covered_input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    reasoning_output_tokens = 0
    invalid_events = 0
    unsupported_events = 0
    duplicate_events = 0
    conflicting_events = 0
    ambiguous_duplicate_candidates = 0
    events_without_stable_id = 0
    malformed_lines = 0
    turns_with_cached_input = 0
    grouped: dict[str, dict[str, Any]] = {}
    unkeyed_payload_counts: dict[str, int] = {}
    for raw in jsonl_text.splitlines():
        if not raw.strip():
            continue
        try:
            event = _strict_json_loads(raw)
        except (json.JSONDecodeError, _DuplicateJsonKeyError):
            malformed_lines += 1
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        terminal_events_observed += 1
        canonical = _canonical_bytes(event)
        identifiers = [
            event.get(field)
            for field in ("event_id", "turn_id", "id")
            if field in event
        ]
        if identifiers and isinstance(identifiers[0], str) and identifiers[0]:
            event_key = f"id:{identifiers[0]}"
        else:
            events_without_stable_id += 1
            payload_digest = _sha256(canonical)
            prior_count = unkeyed_payload_counts.get(payload_digest, 0)
            if prior_count:
                ambiguous_duplicate_candidates += 1
            unkeyed_payload_counts[payload_digest] = prior_count + 1
            # Equal unkeyed terminal payloads may be different legitimate
            # turns.  Preserve each observation, flag identity ambiguity, and
            # never claim duplicate detection coverage.
            event_key = f"unkeyed:{terminal_events_observed}:{payload_digest}"
        previous = grouped.get(event_key)
        if previous is None:
            grouped[event_key] = {
                "event": event,
                "canonical": canonical,
                "conflict": False,
            }
        elif previous["canonical"] == canonical:
            duplicate_events += 1
        else:
            previous["conflict"] = True
            conflicting_events += 1

    for group in grouped.values():
        completed_turns += 1
        event = group["event"]
        if group["conflict"]:
            invalid_events += 1
            continue
        identifiers = [
            event.get(field)
            for field in ("event_id", "turn_id", "id")
            if field in event
        ]
        if (
            len(identifiers) > 1
            or any(not isinstance(value, str) or not value for value in identifiers)
        ):
            invalid_events += 1
            continue
        event_schema_version = event.get(
            "event_schema_version", event.get("schema_version", event.get("version"))
        )
        adapter_version = event.get("adapter_version")
        if (
            event_schema_version not in supported_schema_versions
            or adapter_version not in supported_adapter_versions
        ):
            unsupported_events += 1
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            invalid_events += 1
            continue
        observed_input = _usage_integer(usage.get("input_tokens"))
        observed_cached = _usage_integer(usage.get("cached_input_tokens"))
        observed_output = _usage_integer(usage.get("output_tokens"))
        observed_reasoning = _usage_integer(usage.get("reasoning_output_tokens"))
        if (
            observed_input is None
            or observed_cached is None
            or observed_cached > observed_input
            or ("output_tokens" in usage and observed_output is None)
            or ("reasoning_output_tokens" in usage and observed_reasoning is None)
        ):
            invalid_events += 1
            continue
        telemetry_turns += 1
        input_tokens += observed_input
        covered_input_tokens += observed_input
        cached_input_tokens += observed_cached
        output_tokens += observed_output or 0
        reasoning_output_tokens += observed_reasoning or 0
        if observed_cached > 0:
            turns_with_cached_input += 1
    telemetry_coverage = (
        telemetry_turns / completed_turns if completed_turns else 0.0
    )
    cached_share = (
        cached_input_tokens / covered_input_tokens if covered_input_tokens else None
    )
    if not completed_turns or not telemetry_turns:
        status = "unavailable"
    elif (
        telemetry_turns == completed_turns
        and not invalid_events
        and not unsupported_events
        and not duplicate_events
        and not conflicting_events
        and not events_without_stable_id
        and not malformed_lines
    ):
        status = "available"
    else:
        status = "partial"
    return {
        "schema_version": "goal-teams-observer-telemetry-v2.38",
        "evidence_eligible": False,
        "evidence_class": "diagnostic_non_evidence",
        "parser_version": parser_version,
        "adapter_registry_version": adapter_registry_version,
        "supported_event_schema_versions": ["legacy-unversioned", "codex-turn-completed-v1"],
        "visibility": "observer",
        "status": status,
        "raw_jsonl_sha256": _sha256(jsonl_text.encode("utf-8")),
        "terminal_events_observed": terminal_events_observed,
        "completed_turns": completed_turns,
        "telemetry_turns": telemetry_turns,
        "turn_completed_count": completed_turns,
        "usage_observed_count": telemetry_turns,
        "input_tokens": input_tokens,
        "covered_input_tokens": covered_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": covered_input_tokens - cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "cached_input_share": cached_share,
        "turns_with_cached_input": turns_with_cached_input,
        "turn_cache_presence": (
            turns_with_cached_input / telemetry_turns if telemetry_turns else None
        ),
        "telemetry_coverage": telemetry_coverage,
        "invalid_events": invalid_events,
        "invalid_turns": invalid_events,
        "unsupported_events": unsupported_events,
        "unsupported_turns": unsupported_events,
        "unavailable_turns": completed_turns - telemetry_turns,
        "duplicate_events": duplicate_events,
        "conflicting_events": conflicting_events,
        "ambiguous_duplicate_candidates": ambiguous_duplicate_candidates,
        "events_without_stable_id": events_without_stable_id,
        "event_identity_coverage": (
            (completed_turns - events_without_stable_id) / completed_turns
            if completed_turns
            else 0.0
        ),
        "duplicate_detection_status": (
            "available" if completed_turns and not events_without_stable_id else "partial"
        ),
        "malformed_lines": malformed_lines,
        "request_hit_rate": None,
        "request_hit_rate_reason": "turn_aggregate_cannot_estimate_request_hit_rate",
        "metric_semantics": "token_weighted_cached_input_share_not_request_hit_rate",
    }


def build_cache_probe_plan(root: Path, route_id: str, repeats: int = 5) -> dict[str, Any]:
    """Build a non-executing cold/warm A/B plan with frozen control dimensions."""

    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise PromptCacheContractError("E_CACHE_PROBE_REPEATS")
    identity = build_prompt_identity(root, route_id)
    cohorts = []
    for cohort_id, mutation_scope in (
        ("baseline_current", "none"),
        ("dynamic_suffix_change", "dynamic_tail"),
        ("stable_prefix_candidate", "stable_prefix"),
    ):
        invocations = [
            {"ordinal": 0, "repetition_state": "first_seen_reference", "mutation_scope": mutation_scope}
        ]
        invocations.extend(
            {
                "ordinal": ordinal,
                "repetition_state": "immediate_repeat",
                "mutation_scope": mutation_scope,
            }
            for ordinal in range(1, repeats + 1)
        )
        cohorts.append(
            {
                "cohort_id": cohort_id,
                "mutation_scope": mutation_scope,
                "invocations": invocations,
            }
        )
    return {
        "schema_version": "goal-teams-cache-probe-plan-v2.38",
        "execution_state": "planned_not_executed",
        "live_ab_status": "unavailable",
        "cache_namespace_control": "unavailable",
        "current_candidate_binding_status": "unavailable_plan_only",
        "schedule_status": "unavailable_plan_only",
        "prompt_identity": identity,
        "first_seen_references_per_cohort": 1,
        "warm_repeats_per_cohort": repeats,
        "cohorts": cohorts,
        "fixed_controls": [
            "product_version",
            "model",
            "cli_sha256",
            "package_tree_digest",
            "effective_config_manifest_sha256",
            "permissions",
            "workdir_shape",
            "scorer_and_harness",
        ],
        "primary_metrics": [
            "uncached_input_tokens_per_accepted_task",
            "total_input_tokens",
            "quality_pass_rate",
            "latency",
        ],
        "secondary_metrics": ["cached_input_share", "telemetry_coverage"],
        "request_hit_rate_supported": False,
    }


# V2.39 adds a separate, fail-closed evidence contract.  The V2.38 helpers
# above remain byte- and API-compatible for historical replay.
HOST_CAPABILITY_SCHEMA_V239 = "goal-teams-host-capability-receipt-v2.39"
ORDERED_PROMPT_SCHEMA_V239 = "goal-teams-ordered-prompt-manifest-v2"
HOST_ATTESTATION_SCHEMA_V239 = "goal-teams-host-attestation-v2.39"
CACHE_STATUS_SCHEMA_V239 = "goal-teams-cache-status-v2.39"
RAW_USAGE_RECEIPT_SCHEMA_V239 = "goal-teams-raw-usage-receipt-v2.39"
PRODUCTION_CACHE_POLICY_RELATIVE_PATH = "references/prompt-cache-trust-policy.json"

_HOST_CAPABILITIES = {
    "final_request_boundary",
    "effective_config_attestation",
    "provider_usage_events",
    "cache_namespace_control",
    "request_hit_semantics",
}
_HOST_CAPABILITY_STATUSES = {"available", "unavailable", "unsupported"}
_EVIDENCE_ORIGINS = {
    "host_runtime",
    "synthetic_fixture",
    "declaration_only",
}


class _PackageBoundAttestationRegistry(dict):
    """Registry produced only by the package policy loader.

    This is not a Python-process security boundary.  It prevents the public
    verifier API from treating an arbitrary caller dictionary as a production
    trust root; release identity and external Evidence remain the real trust
    boundary.
    """


class _PackageBoundProductionPolicyReceipt(dict):
    """Opaque marker for a production policy bound to a package identity."""


class _VerifiedPackageIdentityReceipt(dict):
    """Opaque marker issued by release/install identity verification."""


class _VerifiedAuthorizationReceipt(dict):
    """Opaque marker for verified production live-probe authorization."""


class _BoundReceipt(dict):
    """Dict-compatible receipt with an internal immutable creation snapshot."""

    _BINDING_ATTRIBUTES = {"_public_snapshot", "_private_snapshot"}

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._BINDING_ATTRIBUTES and hasattr(self, name):
            raise AttributeError(f"{name} is immutable")
        object.__setattr__(self, name, value)


class _TestOnlyAdapterReceipt(_BoundReceipt):
    """Synthetic adapter receipt that is never Evidence eligible."""


class _RuntimePromptIdentityV239(_BoundReceipt):
    """Closed V2.39 identity minted by the ordered-manifest validator."""


class _FinalizedRawUsageReceipt(_BoundReceipt):
    """Opaque marker returned after reopening and hashing finalized raw bytes."""


class _FinalizedNormalizedUsageReceipt(_BoundReceipt):
    """Opaque marker returned after reopening normalized bytes."""


class _V238SourceArtifactReceipt(_BoundReceipt):
    """Opaque marker for a safely opened, read-only V2.38 artifact."""


def _seal_bound_receipt(
    receipt: _BoundReceipt, *, private: Mapping[str, Any] | None = None
) -> _BoundReceipt:
    """Bind public scalar metadata and private filesystem identity once."""

    object.__setattr__(
        receipt,
        "_public_snapshot",
        MappingProxyType(copy.deepcopy(dict(receipt))),
    )
    object.__setattr__(
        receipt,
        "_private_snapshot",
        MappingProxyType(dict(private or {})),
    )
    return receipt


def _validated_bound_receipt(
    receipt: Any, expected_type: type[_BoundReceipt], error_code: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Reject public-field mutation and return the immutable creation binding."""

    if not isinstance(receipt, expected_type):
        raise PromptCacheContractError(error_code)
    public = getattr(receipt, "_public_snapshot", None)
    private = getattr(receipt, "_private_snapshot", None)
    if (
        not isinstance(public, MappingProxyType)
        or not isinstance(private, MappingProxyType)
        or dict(receipt) != dict(public)
    ):
        raise PromptCacheContractError(error_code)
    return public, private


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _bounded_identifier(value: Any, *, maximum: int = 256) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and not any(ord(character) < 32 for character in value)
    )


def _safe_metadata_identifier(value: Any, *, maximum: int = 256) -> bool:
    """Allow bounded metadata while excluding paths, URIs and secret markers."""

    if not _bounded_identifier(value, maximum=maximum) or value.strip() != value:
        return False
    lowered = value.casefold()
    if (
        lowered.startswith("file:")
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or value.startswith(("\\\\", "//"))
    ):
        return False
    return not any(
        marker in lowered
        for marker in (
            "sk-live-",
            "sk-proj-",
            "ghp_",
            "github_pat_",
            "akia",
            "bearer ",
            "password=",
            "api_key=",
            "access_token=",
            "refresh_token=",
            "client_secret=",
            "private_key=",
            "secret_key=",
            "session_token=",
            "cookie=",
        )
    )


def _safe_reason_code(value: Any) -> bool:
    return (
        _safe_metadata_identifier(value, maximum=128)
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def build_host_capability_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and hash a closed V2.39 host capability declaration.

    A capability receipt describes visibility only.  It is never an
    attestation and cannot by itself upgrade host or live trust state.
    """

    if not isinstance(payload, dict):
        raise PromptCacheContractError("E_HOST_CAPABILITY_SCHEMA")
    allowed_fields = {
        "schema_version",
        "receipt_id",
        "product_version",
        "host_adapter_id",
        "host_adapter_version",
        "evidence_origin",
        "capabilities",
        "redaction_state",
    }
    unknown = set(payload) - allowed_fields
    if unknown:
        raise PromptCacheContractError("E_HOST_CAPABILITY_UNKNOWN_FIELD")
    if set(payload) != allowed_fields:
        raise PromptCacheContractError("E_HOST_CAPABILITY_REQUIRED_FIELD")
    if (
        payload.get("schema_version") != HOST_CAPABILITY_SCHEMA_V239
        or payload.get("product_version") != "V2.39"
        or payload.get("evidence_origin") not in _EVIDENCE_ORIGINS
        or payload.get("redaction_state") != "metadata_only"
        or any(
            not _safe_metadata_identifier(payload.get(field))
            for field in ("receipt_id", "host_adapter_id", "host_adapter_version")
        )
    ):
        raise PromptCacheContractError("E_HOST_CAPABILITY_SCHEMA")

    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        raise PromptCacheContractError("E_HOST_CAPABILITY_SCHEMA")
    unknown_capabilities = set(capabilities) - _HOST_CAPABILITIES
    if unknown_capabilities:
        raise PromptCacheContractError("E_HOST_CAPABILITY_UNKNOWN")
    if set(capabilities) != _HOST_CAPABILITIES:
        raise PromptCacheContractError("E_HOST_CAPABILITY_MISSING")

    normalized_capabilities: dict[str, dict[str, Any]] = {}
    for capability_name in sorted(_HOST_CAPABILITIES):
        value = capabilities[capability_name]
        expected_fields = {"status", "reason"}
        if capability_name == "provider_usage_events":
            expected_fields.add("granularity")
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise PromptCacheContractError(
                f"E_HOST_CAPABILITY_SCHEMA:{capability_name}"
            )
        if value.get("status") not in _HOST_CAPABILITY_STATUSES:
            raise PromptCacheContractError(
                f"E_HOST_CAPABILITY_STATUS:{capability_name}"
            )
        if not _safe_reason_code(value.get("reason")):
            raise PromptCacheContractError(
                f"E_HOST_CAPABILITY_REASON:{capability_name}"
            )
        normalized = {
            "status": value["status"],
            "reason": value["reason"],
        }
        if capability_name == "provider_usage_events":
            if value.get("granularity") not in {"turn", "request", "none"}:
                raise PromptCacheContractError("E_HOST_CAPABILITY_GRANULARITY")
            if value["status"] != "available" and value["granularity"] != "none":
                raise PromptCacheContractError("E_HOST_CAPABILITY_GRANULARITY")
            normalized["granularity"] = value["granularity"]
        normalized_capabilities[capability_name] = normalized

    normalized_payload = {
        "schema_version": HOST_CAPABILITY_SCHEMA_V239,
        "receipt_id": payload["receipt_id"],
        "product_version": "V2.39",
        "host_adapter_id": payload["host_adapter_id"],
        "host_adapter_version": payload["host_adapter_version"],
        "evidence_origin": payload["evidence_origin"],
        "capabilities": normalized_capabilities,
        "redaction_state": "metadata_only",
    }
    return {
        **normalized_payload,
        "receipt_sha256": _sha256(_canonical_bytes(normalized_payload)),
    }


def _validated_capability_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict) or "receipt_sha256" not in receipt:
        raise PromptCacheContractError("E_HOST_CAPABILITY_RECEIPT")
    source = dict(receipt)
    claimed_hash = source.pop("receipt_sha256")
    rebuilt = build_host_capability_receipt(source)
    if not _is_sha256(claimed_hash) or rebuilt["receipt_sha256"] != claimed_hash:
        raise PromptCacheContractError("E_HOST_CAPABILITY_RECEIPT_HASH")
    return rebuilt


def build_ordered_prompt_identity_v239(
    manifest: dict[str, Any], capability_receipt: dict[str, Any]
) -> dict[str, Any]:
    """Build a V2.39 host-observed identity without trusting its origin.

    Partial observations always retain a manifest hash but never emit stable
    or runtime prompt digests.
    """

    receipt = _validated_capability_receipt(capability_receipt)
    if not isinstance(manifest, dict):
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_SCHEMA")
    allowed_fields = {
        "schema_version",
        "manifest_id",
        "product_version",
        "agent_run_id",
        "turn_id",
        "route_id",
        "policy_profile",
        "capability_receipt_sha256",
        "request_binding_id",
        "assembly_boundary",
        "host_adapter_identity_sha256",
        "evidence_origin",
        "manifest_status",
        "digest_scope",
        "missing_segment_classes",
        "stable_segment_count",
        "dynamic_segment_count",
        "platform_managed_segment_count",
        "canonicalization",
        "segments",
    }
    if set(manifest) != allowed_fields:
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_UNKNOWN_FIELD")
    if (
        manifest.get("schema_version") != ORDERED_PROMPT_SCHEMA_V239
        or manifest.get("product_version") != "V2.39"
        or manifest.get("assembly_boundary") != "pre_provider_send"
        or manifest.get("evidence_origin") not in _EVIDENCE_ORIGINS
        or manifest.get("evidence_origin") != receipt["evidence_origin"]
        or manifest.get("capability_receipt_sha256")
        != receipt["receipt_sha256"]
        or not _is_sha256(manifest.get("host_adapter_identity_sha256"))
        or not _safe_metadata_identifier(manifest.get("request_binding_id"))
    ):
        raise PromptCacheContractError("E_ORDERED_PROMPT_MANIFEST_BINDING")

    # Reuse the hardened V2.38 ordered-segment validator.  Product/schema are
    # projected only for validation; all V2.39 hashes bind the unprojected
    # manifest, and the legacy function remains unchanged.
    projected = {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key
        not in {
            "capability_receipt_sha256",
            "request_binding_id",
            "assembly_boundary",
            "host_adapter_identity_sha256",
            "evidence_origin",
        }
    }
    projected["schema_version"] = "goal-teams-ordered-prompt-manifest-v1"
    projected["product_version"] = "V2.38"
    validated = build_ordered_prompt_identity(projected)

    status = manifest["manifest_status"]
    final_boundary_available = (
        receipt["capabilities"]["final_request_boundary"]["status"] == "available"
    )
    if status == "available" and not final_boundary_available:
        raise PromptCacheContractError("E_ORDERED_PROMPT_CAPABILITY")
    complete = (
        status == "available"
        and manifest["digest_scope"] == "complete"
        and not manifest["missing_segment_classes"]
        and final_boundary_available
    )
    result = {
        "schema_version": "goal-teams-runtime-prompt-identity-v2.39",
        "manifest_id": manifest["manifest_id"],
        "product_version": "V2.39",
        "agent_run_id": manifest["agent_run_id"],
        "turn_id": manifest["turn_id"],
        "route_id": manifest["route_id"],
        "policy_profile": manifest["policy_profile"],
        "manifest_status": status,
        "digest_scope": "complete" if complete else "partial",
        "missing_segment_classes": list(manifest["missing_segment_classes"]),
        "ordered_prompt_manifest_sha256": _sha256(_canonical_bytes(manifest)),
        "capability_receipt_sha256": receipt["receipt_sha256"],
        "request_binding_id": manifest["request_binding_id"],
        "assembly_boundary": "pre_provider_send",
        "host_adapter_identity_sha256": manifest[
            "host_adapter_identity_sha256"
        ],
        "evidence_origin": manifest["evidence_origin"],
        "stable_prefix_digest": (
            validated["stable_prefix_digest"] if complete else None
        ),
        "runtime_prompt_digest": (
            validated["runtime_prompt_digest"] if complete else None
        ),
        "stable_segment_count": validated["stable_segment_count"],
        "platform_managed_segment_count": validated[
            "platform_managed_segment_count"
        ],
        "stable_prefix_segment_count": validated[
            "stable_prefix_segment_count"
        ],
        "effective_segment_count": validated["effective_segment_count"],
        "host_observation_trust_state": "unverified",
        "provider_cache_key": None,
    }
    result["identity_sha256"] = _sha256(_canonical_bytes(result))
    return _seal_bound_receipt(_RuntimePromptIdentityV239(result))


def _policy_has_forbidden_executable_fields(value: Any, *, key: str = "") -> bool:
    forbidden = {
        "callback",
        "module",
        "module_path",
        "import",
        "shell",
        "command",
        "executable",
        "executable_path",
        "trust_class",
    }
    if key in forbidden or callable(value):
        return True
    if isinstance(value, dict):
        return any(
            _policy_has_forbidden_executable_fields(child, key=str(child_key))
            for child_key, child in value.items()
        )
    if isinstance(value, list):
        return any(_policy_has_forbidden_executable_fields(child) for child in value)
    return False


def load_production_cache_policy(
    package_root: Path, package_identity_receipt: dict[str, Any]
) -> dict[str, Any]:
    """Load the canonical data-only policy from a verified package identity.

    Plain caller dictionaries are deliberately rejected even when their hash
    fields happen to match.  The initial V2.39 package does not issue a
    production package-identity receipt, so this path stays fail closed.
    """

    if not isinstance(package_identity_receipt, _VerifiedPackageIdentityReceipt):
        raise PromptCacheContractError("E_CACHE_POLICY_PACKAGE_BINDING")
    package_root = Path(package_root).resolve()
    policy_path = _safe_file(package_root, PRODUCTION_CACHE_POLICY_RELATIVE_PATH)
    raw = policy_path.read_bytes()
    try:
        policy = _strict_json_loads(raw.decode("utf-8"))
    except (_DuplicateJsonKeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptCacheContractError("E_CACHE_POLICY_SCHEMA") from exc
    expected_policy_fields = {
        "schema_version",
        "product_version",
        "policy_revision",
        "enabled",
        "verifiers",
        "adapters",
        "authorization_issuers",
        "authorization_policy",
        "nonce_policy",
    }
    if (
        not isinstance(policy, dict)
        or set(policy) != expected_policy_fields
        or policy.get("schema_version")
        != "goal-teams-prompt-cache-trust-policy-v2.39"
        or policy.get("product_version") != "V2.39"
        or _policy_has_forbidden_executable_fields(policy)
    ):
        raise PromptCacheContractError("E_CACHE_POLICY_SCHEMA")
    loader_sha = _sha256(Path(__file__).read_bytes())
    checker_path = package_root / "scripts" / "checks" / "check-prompt-cache.py"
    if not checker_path.is_file() or checker_path.is_symlink():
        raise PromptCacheContractError("E_CACHE_POLICY_CHECKER_BINDING")
    checker_sha = _sha256(checker_path.read_bytes())
    if (
        package_identity_receipt.get("schema_version")
        != "goal-teams-package-identity-v1"
        or package_identity_receipt.get("product_version") != "V2.39"
        or package_identity_receipt.get("policy_sha256") != _sha256(raw)
        or package_identity_receipt.get("loader_sha256") != loader_sha
        or package_identity_receipt.get("checker_sha256") != checker_sha
        or not _is_sha256(package_identity_receipt.get("package_tree_digest"))
        or package_identity_receipt.get("caller_declared") is not False
    ):
        raise PromptCacheContractError("E_CACHE_POLICY_CHECKER_BINDING")
    payload = {
        "schema_version": "goal-teams-production-cache-policy-receipt-v2.39",
        "product_version": "V2.39",
        "policy_revision": policy["policy_revision"],
        "policy_sha256": _sha256(raw),
        "loader_sha256": loader_sha,
        "checker_sha256": checker_sha,
        "package_tree_digest": package_identity_receipt["package_tree_digest"],
        "enabled": policy["enabled"],
        "verifiers": copy.deepcopy(policy["verifiers"]),
        "adapters": copy.deepcopy(policy["adapters"]),
        "authorization_issuers": copy.deepcopy(policy["authorization_issuers"]),
        "authorization_policy": copy.deepcopy(policy["authorization_policy"]),
        "nonce_policy": copy.deepcopy(policy["nonce_policy"]),
    }
    payload["receipt_sha256"] = _sha256(_canonical_bytes(payload))
    return _PackageBoundProductionPolicyReceipt(payload)


def verify_host_attestation(
    attestation: dict[str, Any], *,
    production_policy_receipt: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify an attestation against a registered verifier.

    Caller-injected registries are accepted only for synthetic tests and can
    never produce a trusted host state.  Production policy receipts must come
    from :func:`load_production_cache_policy`.
    """

    if production_policy_receipt is not None:
        if registry is not None or not isinstance(
            production_policy_receipt, _PackageBoundProductionPolicyReceipt
        ):
            raise PromptCacheContractError("E_CACHE_ATTESTATION_CALLER_REGISTRY")
        # No production verifier is enabled in the initial V2.39 policy.
        raise PromptCacheContractError("E_CACHE_ATTESTATION_VERIFIER_UNAVAILABLE")
    if registry is None:
        raise PromptCacheContractError("E_CACHE_ATTESTATION_CALLER_REGISTRY")
    if (
        not isinstance(attestation, dict)
        or set(attestation) != {"schema_version", "attestation_id", "binding", "proof"}
        or attestation.get("schema_version") != HOST_ATTESTATION_SCHEMA_V239
        or not _safe_metadata_identifier(attestation.get("attestation_id"))
        or not isinstance(attestation.get("binding"), dict)
        or not isinstance(attestation.get("proof"), dict)
    ):
        raise PromptCacheContractError("E_HOST_ATTESTATION_SCHEMA")
    binding = attestation["binding"]
    binding_fields = {
        "verifier_id",
        "verifier_version",
        "verifier_code_sha256",
        "evidence_origin",
        "subject",
        "nonce",
        "issued_at",
        "expires_at",
    }
    subject_fields = {
        "capability_receipt_sha256",
        "ordered_prompt_manifest_sha256",
        "runtime_prompt_digest",
        "effective_config_manifest_sha256",
        "executable_sha256",
        "adapter_identity_sha256",
    }
    if (
        set(binding) != binding_fields
        or binding.get("evidence_origin") not in _EVIDENCE_ORIGINS
        or any(
            not _safe_metadata_identifier(binding.get(field))
            for field in (
                "verifier_id",
                "verifier_version",
                "nonce",
                "issued_at",
                "expires_at",
            )
        )
        or not _is_sha256(binding.get("verifier_code_sha256"))
        or not isinstance(binding.get("subject"), dict)
        or set(binding["subject"]) != subject_fields
        or not all(_is_sha256(value) for value in binding["subject"].values())
        or set(attestation["proof"]) != {"algorithm", "value"}
        or not all(
            _bounded_identifier(attestation["proof"].get(field), maximum=512)
            for field in ("algorithm", "value")
        )
    ):
        raise PromptCacheContractError("E_HOST_ATTESTATION_SCHEMA")
    if binding["issued_at"] >= binding["expires_at"]:
        raise PromptCacheContractError("E_HOST_ATTESTATION_TIME")
    if not isinstance(registry, dict) or not isinstance(registry.get("verifiers"), dict):
        raise PromptCacheContractError("E_HOST_ATTESTATION_REGISTRY")
    verifier = registry["verifiers"].get(binding["verifier_id"])
    if verifier is None:
        raise PromptCacheContractError("E_HOST_ATTESTATION_VERIFIER_UNKNOWN")
    if not isinstance(verifier, dict):
        raise PromptCacheContractError("E_HOST_ATTESTATION_REGISTRY")
    if (
        verifier.get("version") != binding["verifier_version"]
        or verifier.get("code_sha256") != binding["verifier_code_sha256"]
        or binding["evidence_origin"]
        not in verifier.get("allowed_evidence_origins", [])
    ):
        raise PromptCacheContractError("E_HOST_ATTESTATION_BINDING")
    trust_class = verifier.get("trust_class")
    if trust_class == "production" and not isinstance(
        registry, _PackageBoundAttestationRegistry
    ):
        raise PromptCacheContractError("E_HOST_ATTESTATION_REGISTRY_UNTRUSTED")
    if trust_class not in {"production", "synthetic_test_only"}:
        raise PromptCacheContractError("E_HOST_ATTESTATION_TRUST_CLASS")
    used_nonces = registry.get("used_nonces")
    if not isinstance(used_nonces, set):
        raise PromptCacheContractError("E_HOST_ATTESTATION_NONCE_REGISTRY")
    if binding["nonce"] in used_nonces:
        raise PromptCacheContractError("E_HOST_ATTESTATION_REPLAY")

    if trust_class == "synthetic_test_only":
        verifier_function = verifier.get("verify")
        if not callable(verifier_function):
            raise PromptCacheContractError("E_HOST_ATTESTATION_VERIFIER")
        try:
            verified = verifier_function(copy.deepcopy(attestation)) is True
        except Exception as exc:
            raise PromptCacheContractError("E_HOST_ATTESTATION_PROOF") from exc
    else:
        # V2.39 intentionally ships no in-process production proof algorithm.
        # A future package-bound external verifier can add a new explicit
        # policy algorithm without accepting a caller callback.
        verified = False
    if not verified:
        raise PromptCacheContractError("E_HOST_ATTESTATION_PROOF")
    used_nonces.add(binding["nonce"])
    test_only = trust_class == "synthetic_test_only"
    result = {
        "schema_version": "goal-teams-host-attestation-verification-v2.39",
        "attestation_id": attestation["attestation_id"],
        "verification_status": "verified",
        "verifier_id": binding["verifier_id"],
        "verifier_version": binding["verifier_version"],
        "evidence_origin": binding["evidence_origin"],
        "subject_sha256": _sha256(_canonical_bytes(binding["subject"])),
        "trust_scope": "structural_only" if test_only else "host_runtime",
        "host_integration_state": "partial" if test_only else "trusted",
        "test_only": test_only,
    }
    result["verification_sha256"] = _sha256(_canonical_bytes(result))
    return result


def verify_live_authorization(
    authorization_bytes: bytes,
    *,
    production_policy_receipt: dict[str, Any],
    replay_state: dict[str, Any],
) -> dict[str, Any]:
    """Verify a production live-probe authorization without copying secrets."""

    raw_hash = (
        _sha256(authorization_bytes)
        if isinstance(authorization_bytes, bytes)
        else None
    )
    if not isinstance(production_policy_receipt, _PackageBoundProductionPolicyReceipt):
        return {
            "schema_version": "goal-teams-live-probe-authorization-verification-v2.39",
            "status": "not_authorized",
            "error_code": "E_CACHE_POLICY_PACKAGE_BINDING",
            "authorization_raw_sha256": raw_hash,
            "evidence_eligible": False,
            "claim_scope": "none",
        }
    if not isinstance(authorization_bytes, bytes):
        return {
            "schema_version": "goal-teams-live-probe-authorization-verification-v2.39",
            "status": "invalid",
            "error_code": "E_CACHE_AUTH_PROOF",
            "authorization_raw_sha256": None,
            "evidence_eligible": False,
            "claim_scope": "none",
        }
    if not isinstance(replay_state, dict):
        return {
            "schema_version": "goal-teams-live-probe-authorization-verification-v2.39",
            "status": "invalid",
            "error_code": "E_CACHE_AUTH_PROOF",
            "authorization_raw_sha256": raw_hash,
            "evidence_eligible": False,
            "claim_scope": "none",
        }
    # V2.39 ships no enabled issuer or verifier.  Do not parse a caller flag
    # into authorization; report the absent issuer without exposing payload.
    return {
        "schema_version": "goal-teams-live-probe-authorization-verification-v2.39",
        "status": "not_authorized",
        "error_code": "E_CACHE_AUTH_ISSUER",
        "authorization_raw_sha256": raw_hash,
        "production_policy_receipt_sha256": production_policy_receipt.get(
            "receipt_sha256"
        ),
        "evidence_eligible": False,
        "claim_scope": "none",
    }


def build_cache_status_axes(
    *,
    structural_delivery_state: str,
    host_integration_state: str,
    live_cache_validation_state: str,
    request_hit_rate_support_state: str,
) -> dict[str, Any]:
    """Build four independent status axes and a conservative claim scope."""

    allowed = {
        "structural_delivery_state": {"passed", "failed", "not_run"},
        "host_integration_state": {
            "trusted",
            "partial",
            "unavailable",
            "unsupported",
            "invalid",
        },
        "live_cache_validation_state": {
            "passed",
            "partial",
            "insufficient_sample",
            "not_authorized",
            "unavailable",
            "failed",
        },
        "request_hit_rate_support_state": {
            "supported",
            "unavailable",
            "unsupported",
            "invalid",
        },
    }
    values = {
        "structural_delivery_state": structural_delivery_state,
        "host_integration_state": host_integration_state,
        "live_cache_validation_state": live_cache_validation_state,
        "request_hit_rate_support_state": request_hit_rate_support_state,
    }
    if any(values[name] not in choices for name, choices in allowed.items()):
        raise PromptCacheContractError("E_CACHE_STATUS_AXIS")
    if (
        host_integration_state == "trusted"
        or live_cache_validation_state == "passed"
        or request_hit_rate_support_state == "supported"
    ):
        # V2.39 ships no enabled production verifier, issuer or adapter.
        # Caller-selected strings therefore cannot mint a trusted/live state.
        raise PromptCacheContractError("E_CACHE_STATUS_EVIDENCE")
    if (
        structural_delivery_state == "passed"
        and host_integration_state == "trusted"
        and live_cache_validation_state == "passed"
    ):
        claim_scope = "live_cache_validated"
    elif structural_delivery_state == "passed":
        claim_scope = "structural_only"
    else:
        claim_scope = "none"
    result = {
        "schema_version": CACHE_STATUS_SCHEMA_V239,
        **values,
        "claim_scope": claim_scope,
        "optimization_claim_allowed": claim_scope == "live_cache_validated",
        "request_hit_rate_claim_allowed": (
            claim_scope == "live_cache_validated"
            and request_hit_rate_support_state == "supported"
        ),
    }
    result["status_sha256"] = _sha256(_canonical_bytes(result))
    return result


def _contains_prohibited_usage_material(value: Any, *, key: str = "") -> bool:
    prohibited_keys = {
        "prompt",
        "raw_prompt",
        "system_prompt",
        "user_prompt",
        "message",
        "messages",
        "content",
        "secret",
        "credential",
        "api_key",
        "authorization",
        "headers",
        "request_body",
        "response_body",
        "path",
        "file_path",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "session_token",
        "security_token",
        "client_secret",
        "private_key",
        "secret_key",
        "password",
        "passphrase",
        "cookie",
        "set_cookie",
        "aws_access_key_id",
        "aws_secret_access_key",
    }
    normalized_key = key.casefold().replace("-", "_")
    if normalized_key in prohibited_keys:
        return True
    if isinstance(value, dict):
        return any(
            _contains_prohibited_usage_material(item, key=str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_prohibited_usage_material(item) for item in value)
    if isinstance(value, str):
        candidate = value.strip()
        lowered = candidate.casefold()
        if (
            lowered.startswith("file:")
            or PurePosixPath(candidate).is_absolute()
            or PureWindowsPath(candidate).is_absolute()
            or candidate.startswith(("\\\\", "//"))
        ):
            return True
        return any(
            marker in lowered
            for marker in (
                "sk-live-",
                "sk-proj-",
                "ghp_",
                "github_pat_",
                "bearer ",
                "password=",
                "api_key=",
                "access_token=",
                "refresh_token=",
                "client_secret=",
                "private_key=",
                "aws_access_key_id=",
                "aws_secret_access_key=",
                "session_token=",
                "sessionid=",
                "cookie=",
                "-----begin private key-----",
                "-----begin rsa private key-----",
                "-----begin ec private key-----",
            )
        )
    return False


def _validate_usage_only_event_shape(event: Mapping[str, Any], event_schema: str) -> None:
    """Enforce the closed V2.39 raw usage event contract.

    A denylist is only a secondary guard.  Persisted raw Evidence is limited to
    the fields needed to reproduce cache-token accounting so arbitrary prompt,
    request, filesystem, or credential-bearing data cannot hide behind a new
    key name.
    """

    if event_schema != "codex-turn-completed-v1":
        raise PromptCacheContractError("E_CACHE_USAGE_SCHEMA")
    if set(event) != {"type", "event_id", "usage"}:
        raise PromptCacheContractError("E_CACHE_RAW_SECURITY")
    if event.get("type") != "turn.completed" or not isinstance(event.get("usage"), dict):
        raise PromptCacheContractError("E_CACHE_USAGE_SCHEMA")
    usage = event["usage"]
    allowed_usage = {
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    }
    if not {"input_tokens", "cached_input_tokens"}.issubset(usage):
        raise PromptCacheContractError("E_CACHE_USAGE_SCHEMA")
    if not set(usage).issubset(allowed_usage):
        raise PromptCacheContractError("E_CACHE_RAW_SECURITY")
    parsed_usage = {field: _usage_integer(raw) for field, raw in usage.items()}
    if any(value is None for value in parsed_usage.values()) or (
        parsed_usage["cached_input_tokens"] > parsed_usage["input_tokens"]
    ):
        raise PromptCacheContractError("E_CACHE_USAGE_SCHEMA")


def _validated_raw_usage_receipt(
    adapter_receipt: Any, jsonl_text: str
) -> dict[str, Any] | None:
    if adapter_receipt == {}:
        return None
    if not isinstance(adapter_receipt, _FinalizedRawUsageReceipt):
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_UNTRUSTED")
    # This legacy string API is diagnostic-only even when the caller also
    # holds a finalized receipt.  Production metrics must consume the
    # normalize_usage_events -> aggregate_normalized_events chain.
    return None


def aggregate_request_usage_events(
    jsonl_text: str, *, adapter_receipt: dict[str, Any]
) -> dict[str, Any]:
    """Legacy string diagnostic; never a V2.39 Evidence metric source."""

    if not isinstance(jsonl_text, str):
        raise PromptCacheContractError("E_CACHE_RAW_BYTES")
    receipt = _validated_raw_usage_receipt(adapter_receipt, jsonl_text)
    turn_summary = aggregate_usage_events(jsonl_text)
    result = {
        **turn_summary,
        "schema_version": "goal-teams-request-usage-summary-v2.39",
        "evidence_eligible": False,
        "evidence_class": "diagnostic_non_evidence",
        "raw_evidence_state": (
            "immutable_persisted_and_hashed" if receipt else "unverified"
        ),
        "raw_events_sha256": _sha256(jsonl_text.encode("utf-8")),
        "request_hit_rate": None,
        "request_hit_rate_numerator": None,
        "request_hit_rate_denominator": None,
        "request_hit_rate_support_state": "unsupported",
        "request_hit_rate_reason": "adapter_receipt_missing_or_unverified",
        "request_identity_group_count": 0,
        "invalid_request_events": 0,
    }
    return result


def _validated_v238_cache_identity_record(parsed: Any) -> Mapping[str, Any]:
    """Bind an exact V2.38 cache-identity schema without exposing its payload."""

    if (
        not isinstance(parsed, dict)
        or parsed.get("schema_version") != "goal-teams-cache-identity-v2.38"
    ):
        raise PromptCacheContractError("E_V238_REPLAY_SCHEMA")
    return parsed


def replay_v238_cache_record_test_only_non_evidence(
    record: dict[str, Any] | bytes | str
) -> dict[str, Any]:
    """Legacy in-memory replay retained only for diagnostic fixtures."""

    if isinstance(record, bytes):
        source_bytes = record
        input_form = "raw_bytes"
        try:
            parsed = _strict_json_loads(source_bytes.decode("utf-8"))
        except (_DuplicateJsonKeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PromptCacheContractError("E_V238_REPLAY_JSON") from exc
    elif isinstance(record, str):
        source_bytes = record.encode("utf-8")
        input_form = "raw_text"
        try:
            parsed = _strict_json_loads(record)
        except (_DuplicateJsonKeyError, json.JSONDecodeError) as exc:
            raise PromptCacheContractError("E_V238_REPLAY_JSON") from exc
    elif isinstance(record, dict):
        parsed = copy.deepcopy(record)
        source_bytes = _canonical_bytes(parsed)
        input_form = "canonical_object"
    else:
        raise PromptCacheContractError("E_V238_REPLAY_TYPE")
    parsed = _validated_v238_cache_identity_record(parsed)
    source_schema = parsed["schema_version"]
    result = {
        "schema_version": "goal-teams-cache-replay-sidecar-v2.39",
        "evidence_eligible": False,
        "evidence_class": "diagnostic_non_evidence",
        "evidence_scope": "source_bytes_only",
        "semantic_validation_state": "unavailable",
        "source_schema_version": source_schema,
        "source_record_sha256": _sha256(source_bytes),
        "source_record_input_form": input_form,
        "legacy_payload_state": "omitted_sensitive_by_contract",
        "structural_delivery_state": "passed",
        "host_integration_state": "unavailable",
        "live_cache_validation_state": "unavailable",
        "request_hit_rate_support_state": "unsupported",
        "request_hit_rate": None,
        "stable_prefix_digest": None,
        "runtime_prompt_digest": None,
        "missing_capabilities": [
            "host_capability_receipt",
            "ordered_runtime_prompt_identity_v2.39",
            "trusted_host_attestation",
            "request_hit_semantics",
        ],
        "migration_action": "read_only_sidecar",
    }
    result["sidecar_sha256"] = _sha256(_canonical_bytes(result))
    return result


def _path_contains_symlink(path: Path, *, stop: Path | None = None) -> bool:
    """Return true when an existing path component is a symlink."""

    path = Path(path).absolute()
    stop = Path(stop).absolute() if stop is not None else Path(path.anchor)
    cursor = path
    parts: list[Path] = []
    while True:
        parts.append(cursor)
        if cursor == stop or cursor == cursor.parent:
            break
        cursor = cursor.parent
    for item in reversed(parts):
        try:
            if stat.S_ISLNK(item.lstat().st_mode):
                return True
        except FileNotFoundError:
            continue
    return False


def _safe_output_root_for_evidence(output_root: Path) -> Path:
    if not isinstance(output_root, Path):
        output_root = Path(output_root)
    if not output_root.is_absolute() or _path_contains_symlink(
        output_root, stop=output_root
    ):
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    resolved = output_root.resolve()
    source_root = Path(__file__).resolve().parents[2]
    if (
        resolved == source_root
        or resolved in source_root.parents
        or source_root in resolved.parents
    ):
        try:
            relative = resolved.relative_to(source_root)
        except ValueError:
            raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
        if not relative.parts or not (
            relative.parts[0].startswith("GoalTeamsWork-")
            or relative.parts[0] == "docs"
        ):
            raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    if any(part in {"release", ".git"} for part in resolved.parts):
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    if not resolved.is_dir():
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    return resolved


def _ensure_safe_evidence_subdir(root: Path, name: str) -> Path:
    """Create one evidence directory without following a pre-existing link."""

    if name not in {"raw", "normalized"}:
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    path = root / name
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT") from exc
    if _path_contains_symlink(path, stop=root):
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    return path


def _read_usage_source(source_stream: Any) -> bytes | None:
    if isinstance(source_stream, bytes):
        return source_stream
    if hasattr(source_stream, "read") and callable(source_stream.read):
        value = source_stream.read()
        if isinstance(value, bytes):
            return value
    return None


def build_test_only_adapter_receipt(
    *,
    adapter_id: str = "synthetic-usage-adapter",
    adapter_version: str = "1",
    event_schema: str = "codex-turn-completed-v1",
    capture_invocation_id: str = "synthetic-capture",
    capture_sequence: int = 1,
) -> dict[str, Any]:
    """Return a structural-only adapter receipt for deterministic tests."""

    if (
        not all(
            _safe_metadata_identifier(value)
            for value in (
                adapter_id,
                adapter_version,
                event_schema,
                capture_invocation_id,
            )
        )
        or not isinstance(capture_sequence, int)
        or isinstance(capture_sequence, bool)
        or capture_sequence < 0
    ):
        raise PromptCacheContractError("E_CACHE_ADAPTER_TEST_RECEIPT")
    policy_payload = {
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "event_schema": event_schema,
        "normalizer_kind": "builtin_usage_only_v1",
        "evidence_origin": "synthetic_fixture",
    }
    result = _TestOnlyAdapterReceipt(
        {
            "schema_version": "goal-teams-usage-adapter-receipt-v2.39",
            **policy_payload,
            "capture_invocation_id": capture_invocation_id,
            "capture_sequence": capture_sequence,
            "adapter_policy_sha256": _sha256(_canonical_bytes(policy_payload)),
            "evidence_origin": "synthetic_fixture",
            "evidence_eligible": False,
            "claim_scope": "structural_only",
        }
    )
    return _seal_bound_receipt(result)


def _validated_test_adapter_receipt(
    receipt: Any,
) -> Mapping[str, Any]:
    public, private = _validated_bound_receipt(
        receipt,
        _TestOnlyAdapterReceipt,
        "E_CACHE_ADAPTER_RECEIPT_BINDING",
    )
    expected_fields = {
        "schema_version",
        "adapter_id",
        "adapter_version",
        "event_schema",
        "normalizer_kind",
        "capture_invocation_id",
        "capture_sequence",
        "adapter_policy_sha256",
        "evidence_origin",
        "evidence_eligible",
        "claim_scope",
    }
    metadata_fields = (
        "adapter_id",
        "adapter_version",
        "event_schema",
        "capture_invocation_id",
    )
    if (
        private
        or set(public) != expected_fields
        or public.get("schema_version")
        != "goal-teams-usage-adapter-receipt-v2.39"
        or public.get("normalizer_kind") != "builtin_usage_only_v1"
        or public.get("evidence_origin") != "synthetic_fixture"
        or public.get("evidence_eligible") is not False
        or public.get("claim_scope") != "structural_only"
        or not _is_sha256(public.get("adapter_policy_sha256"))
        or not all(_safe_metadata_identifier(public.get(field)) for field in metadata_fields)
        or not isinstance(public.get("capture_sequence"), int)
        or isinstance(public.get("capture_sequence"), bool)
        or public["capture_sequence"] < 0
    ):
        raise PromptCacheContractError("E_CACHE_ADAPTER_RECEIPT_BINDING")
    policy_payload = {
        "adapter_id": public["adapter_id"],
        "adapter_version": public["adapter_version"],
        "event_schema": public["event_schema"],
        "normalizer_kind": public["normalizer_kind"],
        "evidence_origin": public["evidence_origin"],
    }
    if _sha256(_canonical_bytes(policy_payload)) != public["adapter_policy_sha256"]:
        raise PromptCacheContractError("E_CACHE_ADAPTER_RECEIPT_BINDING")
    return public


def persist_usage_events(
    source_stream: Any, output_root: Path, adapter_receipt: dict[str, Any]
) -> dict[str, Any]:
    """Persist usage-only bytes with exclusive create and a finalized receipt.

    Direct strings or caller dictionaries remain a diagnostic compatibility
    path and are never written or Evidence eligible.
    """

    raw_bytes = _read_usage_source(source_stream)
    if raw_bytes is None or not isinstance(adapter_receipt, _TestOnlyAdapterReceipt):
        diagnostic_bytes = (
            source_stream.encode("utf-8")
            if isinstance(source_stream, str)
            else b""
        )
        return {
            "schema_version": "goal-teams-usage-persist-diagnostic-v2.39",
            "evidence_eligible": False,
            "evidence_class": "diagnostic_non_evidence",
            "raw_input_sha256": _sha256(diagnostic_bytes),
            "persisted": False,
            "request_hit_rate": None,
        }
    adapter = _validated_test_adapter_receipt(adapter_receipt)
    if len(raw_bytes) > 16 * 1024 * 1024:
        raise PromptCacheContractError("E_CACHE_RAW_SIZE")
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptCacheContractError("E_CACHE_RAW_ENCODING") from exc
    event_count = 0
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        try:
            event = _strict_json_loads(line)
        except (_DuplicateJsonKeyError, json.JSONDecodeError) as exc:
            raise PromptCacheContractError("E_CACHE_RAW_JSONL") from exc
        if not isinstance(event, dict) or _contains_prohibited_usage_material(event):
            raise PromptCacheContractError("E_CACHE_RAW_SECURITY")
        _validate_usage_only_event_shape(event, adapter["event_schema"])
        event_count += 1
    if not event_count:
        raise PromptCacheContractError("E_CACHE_RAW_EMPTY")
    root = _safe_output_root_for_evidence(Path(output_root))
    raw_dir = _ensure_safe_evidence_subdir(root, "raw")
    sequence = adapter["capture_sequence"]
    raw_relative = f"raw/events-{sequence:06d}.jsonl"
    receipt_relative = f"raw/receipt-{sequence:06d}.json"
    raw_path = root / raw_relative
    receipt_path = root / receipt_relative
    try:
        with raw_path.open("xb") as handle:
            handle.write(raw_bytes)
    except FileExistsError as exc:
        raise PromptCacheContractError("E_CACHE_RAW_EXCLUSIVE_CREATE") from exc
    if _ensure_safe_evidence_subdir(root, "raw") != raw_dir or _path_contains_symlink(
        raw_path, stop=root
    ):
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    receipt_payload = {
        "schema_version": RAW_USAGE_RECEIPT_SCHEMA_V239,
        "raw_path": raw_relative,
        "byte_size": len(raw_bytes),
        "sha256": _sha256(raw_bytes),
        "adapter_id": adapter["adapter_id"],
        "adapter_version": adapter["adapter_version"],
        "event_schema": adapter["event_schema"],
        "capture_invocation_id": adapter["capture_invocation_id"],
        "capture_sequence": sequence,
        "exclusive_create": True,
        "finalize_state": "finalized",
        "adapter_policy_sha256": adapter["adapter_policy_sha256"],
        "evidence_origin": "synthetic_fixture",
        "evidence_eligible": False,
    }
    try:
        with receipt_path.open("x", encoding="utf-8") as handle:
            json.dump(
                receipt_payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
    except FileExistsError as exc:
        raise PromptCacheContractError("E_CACHE_RAW_EXCLUSIVE_CREATE") from exc
    if _ensure_safe_evidence_subdir(root, "raw") != raw_dir or _path_contains_symlink(
        receipt_path, stop=root
    ):
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    return load_raw_usage_receipt(receipt_path)


def load_raw_usage_receipt(receipt_path: Path) -> dict[str, Any]:
    """Reopen a data-only raw receipt and verify path, bytes and hash."""

    receipt_path = Path(receipt_path).absolute()
    receipt_boundary = receipt_path.parent.parent
    if _path_contains_symlink(receipt_path, stop=receipt_boundary) or not receipt_path.is_file():
        raise PromptCacheContractError("E_CACHE_RAW_SYMLINK")
    try:
        receipt = _strict_json_loads(receipt_path.read_text(encoding="utf-8"))
    except (_DuplicateJsonKeyError, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_SCHEMA") from exc
    expected_fields = {
        "schema_version",
        "raw_path",
        "byte_size",
        "sha256",
        "adapter_id",
        "adapter_version",
        "event_schema",
        "capture_invocation_id",
        "capture_sequence",
        "exclusive_create",
        "finalize_state",
        "adapter_policy_sha256",
        "evidence_origin",
        "evidence_eligible",
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != expected_fields
        or receipt.get("schema_version") != RAW_USAGE_RECEIPT_SCHEMA_V239
        or receipt.get("exclusive_create") is not True
        or receipt.get("finalize_state") != "finalized"
        or not isinstance(receipt.get("byte_size"), int)
        or isinstance(receipt.get("byte_size"), bool)
        or receipt["byte_size"] < 0
        or not _is_sha256(receipt.get("sha256"))
        or not _is_sha256(receipt.get("adapter_policy_sha256"))
        or receipt.get("evidence_origin")
        not in {"host_runtime", "synthetic_fixture"}
        or not isinstance(receipt.get("evidence_eligible"), bool)
        or not all(
            _safe_metadata_identifier(receipt.get(field))
            for field in (
                "adapter_id",
                "adapter_version",
                "event_schema",
                "capture_invocation_id",
            )
        )
        or not isinstance(receipt.get("capture_sequence"), int)
        or isinstance(receipt.get("capture_sequence"), bool)
        or receipt["capture_sequence"] < 0
    ):
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_SCHEMA")
    try:
        raw_relative = _relative_path(receipt.get("raw_path"))
    except PromptCacheContractError as exc:
        raise PromptCacheContractError("E_CACHE_RAW_PATH") from exc
    # Canonical receipts live below <output_root>/raw/.  The receipt may have
    # any safe filename, but its raw path is always output-root-relative.
    if receipt_path.parent.name != "raw":
        raise PromptCacheContractError("E_CACHE_RAW_PATH")
    output_root = receipt_path.parent.parent.resolve()
    raw_path = output_root.joinpath(*PurePosixPath(raw_relative).parts)
    try:
        raw_path.absolute().relative_to(output_root.absolute())
    except ValueError as exc:
        raise PromptCacheContractError("E_CACHE_RAW_PATH") from exc
    if _path_contains_symlink(raw_path, stop=output_root):
        raise PromptCacheContractError("E_CACHE_RAW_SYMLINK")
    if not raw_path.is_file():
        raise PromptCacheContractError("E_CACHE_RAW_PATH")
    raw_bytes = raw_path.read_bytes()
    if len(raw_bytes) != receipt["byte_size"] or _sha256(raw_bytes) != receipt["sha256"]:
        raise PromptCacheContractError("E_CACHE_RAW_HASH_DRIFT")
    result = _FinalizedRawUsageReceipt(copy.deepcopy(receipt))
    return _seal_bound_receipt(
        result,
        private={
            "output_root": output_root,
            "raw_path": raw_path,
            "receipt_path": receipt_path,
        },
    )


def _reopen_finalized_raw_receipt(receipt: _FinalizedRawUsageReceipt) -> bytes:
    public, private = _validated_bound_receipt(
        receipt,
        _FinalizedRawUsageReceipt,
        "E_CACHE_RAW_RECEIPT_BINDING",
    )
    if set(private) != {"output_root", "raw_path", "receipt_path"}:
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_BINDING")
    raw_path = private["raw_path"]
    output_root = private["output_root"]
    receipt_path = private["receipt_path"]
    if not all(isinstance(value, Path) for value in (raw_path, output_root, receipt_path)):
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_BINDING")
    try:
        expected_raw = output_root.joinpath(
            *PurePosixPath(_relative_path(public.get("raw_path"))).parts
        )
        receipt_path.relative_to(output_root)
    except (PromptCacheContractError, ValueError) as exc:
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_BINDING") from exc
    if raw_path != expected_raw:
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_BINDING")
    if _path_contains_symlink(raw_path, stop=output_root) or not raw_path.is_file():
        raise PromptCacheContractError("E_CACHE_RAW_SYMLINK")
    raw_bytes = raw_path.read_bytes()
    if len(raw_bytes) != public["byte_size"] or _sha256(raw_bytes) != public["sha256"]:
        raise PromptCacheContractError("E_CACHE_RAW_HASH_DRIFT")
    return raw_bytes


def normalize_usage_events(
    raw_receipt: dict[str, Any], adapter_receipt: dict[str, Any]
) -> dict[str, Any]:
    """Normalize a finalized raw receipt using the built-in usage parser."""

    if not isinstance(raw_receipt, _FinalizedRawUsageReceipt):
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_UNTRUSTED")
    if not isinstance(adapter_receipt, _TestOnlyAdapterReceipt):
        raise PromptCacheContractError("E_CACHE_ADAPTER_RECEIPT_UNTRUSTED")
    raw_object = raw_receipt
    raw_public, raw_private = _validated_bound_receipt(
        raw_object,
        _FinalizedRawUsageReceipt,
        "E_CACHE_RAW_RECEIPT_BINDING",
    )
    adapter_public = _validated_test_adapter_receipt(adapter_receipt)
    raw_receipt = raw_public
    adapter_receipt = adapter_public
    if (
        set(raw_receipt)
        != {
            "schema_version",
            "raw_path",
            "byte_size",
            "sha256",
            "adapter_id",
            "adapter_version",
            "event_schema",
            "capture_invocation_id",
            "capture_sequence",
            "exclusive_create",
            "finalize_state",
            "adapter_policy_sha256",
            "evidence_origin",
            "evidence_eligible",
        }
        or raw_receipt.get("schema_version") != RAW_USAGE_RECEIPT_SCHEMA_V239
        or raw_receipt.get("evidence_origin") != "synthetic_fixture"
        or raw_receipt.get("evidence_eligible") is not False
    ):
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_BINDING")
    for field in (
        "adapter_id",
        "adapter_version",
        "event_schema",
        "capture_invocation_id",
        "capture_sequence",
        "adapter_policy_sha256",
    ):
        if raw_receipt.get(field) != adapter_receipt.get(field):
            raise PromptCacheContractError("E_CACHE_ADAPTER_RECEIPT_BINDING")
    raw_bytes = _reopen_finalized_raw_receipt(raw_object)
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromptCacheContractError("E_CACHE_RAW_ENCODING") from exc
    parser_version = "goal-teams-usage-normalizer-v2.39.0"
    normalized_by_id: dict[str, dict[str, Any]] = {}
    event_fingerprints: dict[str, str] = {}
    conflicted_ids: set[str] = set()
    duplicate_events = 0
    raw_event_count = 0
    for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            event = _strict_json_loads(raw_line)
        except (_DuplicateJsonKeyError, json.JSONDecodeError) as exc:
            raise PromptCacheContractError("E_CACHE_RAW_JSONL") from exc
        if not isinstance(event, dict) or _contains_prohibited_usage_material(event):
            raise PromptCacheContractError("E_CACHE_RAW_SECURITY")
        _validate_usage_only_event_shape(event, raw_receipt["event_schema"])
        usage = event.get("usage")
        if not isinstance(usage, dict):
            raise PromptCacheContractError("E_CACHE_USAGE_SCHEMA")
        input_tokens = _usage_integer(usage.get("input_tokens"))
        cached_tokens = _usage_integer(usage.get("cached_input_tokens"))
        if input_tokens is None or cached_tokens is None or cached_tokens > input_tokens:
            raise PromptCacheContractError("E_CACHE_USAGE_SCHEMA")
        event_id = event.get("event_id")
        if not _bounded_identifier(event_id):
            raise PromptCacheContractError("E_CACHE_USAGE_EVENT_ID")
        raw_event_count += 1
        fingerprint = _sha256(
            _canonical_bytes(
                {
                    "type": event["type"],
                    "event_id": event_id,
                    "usage": usage,
                }
            )
        )
        if event_id in conflicted_ids:
            continue
        prior = event_fingerprints.get(event_id)
        if prior == fingerprint:
            duplicate_events += 1
            continue
        if prior is not None:
            conflicted_ids.add(event_id)
            event_fingerprints.pop(event_id, None)
            normalized_by_id.pop(event_id, None)
            continue
        event_fingerprints[event_id] = fingerprint
        normalized_by_id[event_id] = {
            "schema_version": "goal-teams-normalized-usage-event-v2.39",
            "raw_sha256": raw_receipt["sha256"],
            "raw_line_number": line_number,
            "event_id": event_id,
            "adapter_id": raw_receipt["adapter_id"],
            "adapter_version": raw_receipt["adapter_version"],
            "event_schema": raw_receipt["event_schema"],
            "capture_invocation_id": raw_receipt["capture_invocation_id"],
            "adapter_policy_sha256": raw_receipt["adapter_policy_sha256"],
            "parser_version": parser_version,
            "source_paths": {
                "input_tokens": "usage.input_tokens",
                "cached_input_tokens": "usage.cached_input_tokens",
            },
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "uncached_input_tokens": input_tokens - cached_tokens,
        }
    normalized_events = sorted(
        normalized_by_id.values(), key=lambda value: int(value["raw_line_number"])
    )
    normalized_bytes = b"".join(
        _canonical_bytes(event) + b"\n" for event in normalized_events
    )
    if set(raw_private) != {"output_root", "raw_path", "receipt_path"}:
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_BINDING")
    output_root = raw_private["output_root"]
    if not isinstance(output_root, Path):
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_BINDING")
    normalized_dir = _ensure_safe_evidence_subdir(output_root, "normalized")
    sequence = raw_receipt["capture_sequence"]
    relative = f"normalized/events-{sequence:06d}.jsonl"
    path = output_root / relative
    try:
        with path.open("xb") as handle:
            handle.write(normalized_bytes)
    except FileExistsError as exc:
        raise PromptCacheContractError("E_CACHE_NORMALIZED_EXCLUSIVE_CREATE") from exc
    if _ensure_safe_evidence_subdir(
        output_root, "normalized"
    ) != normalized_dir or _path_contains_symlink(path, stop=output_root):
        raise PromptCacheContractError("E_CACHE_RAW_OUTPUT_ROOT")
    result = _FinalizedNormalizedUsageReceipt(
        {
            "schema_version": "goal-teams-normalized-usage-receipt-v2.39",
            "normalized_path": relative,
            "byte_size": len(normalized_bytes),
            "sha256": _sha256(normalized_bytes),
            "raw_path": raw_receipt["raw_path"],
            "raw_sha256": raw_receipt["sha256"],
            "adapter_id": raw_receipt["adapter_id"],
            "adapter_version": raw_receipt["adapter_version"],
            "event_schema": raw_receipt["event_schema"],
            "capture_invocation_id": raw_receipt["capture_invocation_id"],
            "adapter_policy_sha256": raw_receipt["adapter_policy_sha256"],
            "parser_version": parser_version,
            "event_count": len(normalized_events),
            "raw_event_count": raw_event_count,
            "duplicate_events": duplicate_events,
            "conflicting_events": len(conflicted_ids),
            "duplicate_detection_state": (
                "conflicted" if conflicted_ids else "complete"
            ),
            "evidence_origin": raw_receipt["evidence_origin"],
            "evidence_eligible": False,
            "claim_scope": "structural_only",
        }
    )
    return _seal_bound_receipt(
        result,
        private={"output_root": output_root, "normalized_path": path},
    )


def _validated_runtime_prompt_identity_v239(identity: Any) -> Mapping[str, Any]:
    public, private = _validated_bound_receipt(
        identity,
        _RuntimePromptIdentityV239,
        "E_CACHE_METRICS_IDENTITY",
    )
    expected_fields = {
        "schema_version",
        "manifest_id",
        "product_version",
        "agent_run_id",
        "turn_id",
        "route_id",
        "policy_profile",
        "manifest_status",
        "digest_scope",
        "missing_segment_classes",
        "ordered_prompt_manifest_sha256",
        "capability_receipt_sha256",
        "request_binding_id",
        "assembly_boundary",
        "host_adapter_identity_sha256",
        "evidence_origin",
        "stable_prefix_digest",
        "runtime_prompt_digest",
        "stable_segment_count",
        "platform_managed_segment_count",
        "stable_prefix_segment_count",
        "effective_segment_count",
        "host_observation_trust_state",
        "provider_cache_key",
        "identity_sha256",
    }
    metadata_fields = (
        "manifest_id",
        "agent_run_id",
        "turn_id",
        "route_id",
        "policy_profile",
        "request_binding_id",
    )
    count_fields = (
        "stable_segment_count",
        "platform_managed_segment_count",
        "stable_prefix_segment_count",
        "effective_segment_count",
    )
    if (
        private
        or set(public) != expected_fields
        or public.get("schema_version") != "goal-teams-runtime-prompt-identity-v2.39"
        or public.get("product_version") != "V2.39"
        or public.get("manifest_status") not in {"available", "partial"}
        or public.get("digest_scope") not in {"complete", "partial"}
        or public.get("assembly_boundary") != "pre_provider_send"
        or public.get("evidence_origin") not in _EVIDENCE_ORIGINS
        or public.get("host_observation_trust_state") != "unverified"
        or public.get("provider_cache_key") is not None
        or not all(_safe_metadata_identifier(public.get(field)) for field in metadata_fields)
        or any(
            not isinstance(public.get(field), int)
            or isinstance(public.get(field), bool)
            or public[field] < 0
            for field in count_fields
        )
        or not all(
            _is_sha256(public.get(field))
            for field in (
                "ordered_prompt_manifest_sha256",
                "capability_receipt_sha256",
                "host_adapter_identity_sha256",
                "identity_sha256",
            )
        )
        or not isinstance(public.get("missing_segment_classes"), list)
        or not all(
            _safe_metadata_identifier(value)
            for value in public.get("missing_segment_classes", [])
        )
    ):
        raise PromptCacheContractError("E_CACHE_METRICS_IDENTITY")
    complete = public["digest_scope"] == "complete"
    if complete:
        if (
            public["manifest_status"] != "available"
            or public["missing_segment_classes"]
            or not _is_sha256(public.get("stable_prefix_digest"))
            or not _is_sha256(public.get("runtime_prompt_digest"))
        ):
            raise PromptCacheContractError("E_CACHE_METRICS_IDENTITY")
    elif (
        public.get("stable_prefix_digest") is not None
        or public.get("runtime_prompt_digest") is not None
    ):
        raise PromptCacheContractError("E_CACHE_METRICS_IDENTITY")
    unhashed = dict(public)
    claimed = unhashed.pop("identity_sha256")
    if _sha256(_canonical_bytes(unhashed)) != claimed:
        raise PromptCacheContractError("E_CACHE_METRICS_IDENTITY")
    return public


def aggregate_normalized_events(
    normalized_receipt: dict[str, Any], identity: dict[str, Any]
) -> dict[str, Any]:
    """Aggregate a trusted normalized receipt without crossing identities."""

    if not isinstance(normalized_receipt, _FinalizedNormalizedUsageReceipt):
        raise PromptCacheContractError("E_CACHE_RAW_RECEIPT_UNTRUSTED")
    normalized_public, normalized_private = _validated_bound_receipt(
        normalized_receipt,
        _FinalizedNormalizedUsageReceipt,
        "E_CACHE_NORMALIZED_RECEIPT_BINDING",
    )
    identity = _validated_runtime_prompt_identity_v239(identity)
    normalized_receipt = normalized_public
    expected_receipt_fields = {
        "schema_version",
        "normalized_path",
        "byte_size",
        "sha256",
        "raw_path",
        "raw_sha256",
        "adapter_id",
        "adapter_version",
        "event_schema",
        "capture_invocation_id",
        "adapter_policy_sha256",
        "parser_version",
        "event_count",
        "raw_event_count",
        "duplicate_events",
        "conflicting_events",
        "duplicate_detection_state",
        "evidence_origin",
        "evidence_eligible",
        "claim_scope",
    }
    count_fields = (
        "byte_size",
        "event_count",
        "raw_event_count",
        "duplicate_events",
        "conflicting_events",
    )
    if (
        set(normalized_receipt) != expected_receipt_fields
        or normalized_receipt.get("schema_version")
        != "goal-teams-normalized-usage-receipt-v2.39"
        or normalized_receipt.get("evidence_origin") != "synthetic_fixture"
        or normalized_receipt.get("evidence_eligible") is not False
        or normalized_receipt.get("claim_scope") != "structural_only"
        or normalized_receipt.get("duplicate_detection_state")
        not in {"complete", "conflicted"}
        or not _is_sha256(normalized_receipt.get("sha256"))
        or not _is_sha256(normalized_receipt.get("raw_sha256"))
        or not _is_sha256(normalized_receipt.get("adapter_policy_sha256"))
        or not _safe_metadata_identifier(
            normalized_receipt.get("capture_invocation_id")
        )
        or any(
            not isinstance(normalized_receipt.get(field), int)
            or isinstance(normalized_receipt.get(field), bool)
            or normalized_receipt[field] < 0
            for field in count_fields
        )
    ):
        raise PromptCacheContractError("E_CACHE_NORMALIZED_RECEIPT_BINDING")
    if set(normalized_private) != {"output_root", "normalized_path"}:
        raise PromptCacheContractError("E_CACHE_NORMALIZED_RECEIPT_BINDING")
    path = normalized_private["normalized_path"]
    root = normalized_private["output_root"]
    if not isinstance(path, Path) or not isinstance(root, Path):
        raise PromptCacheContractError("E_CACHE_NORMALIZED_RECEIPT_BINDING")
    try:
        normalized_relative = _relative_path(normalized_receipt["normalized_path"])
        expected_path = root.joinpath(*PurePosixPath(normalized_relative).parts)
    except PromptCacheContractError as exc:
        raise PromptCacheContractError("E_CACHE_NORMALIZED_RECEIPT_BINDING") from exc
    if path != expected_path:
        raise PromptCacheContractError("E_CACHE_NORMALIZED_RECEIPT_BINDING")
    if _path_contains_symlink(path, stop=root) or not path.is_file():
        raise PromptCacheContractError("E_CACHE_NORMALIZED_PATH")
    normalized_bytes = path.read_bytes()
    if (
        len(normalized_bytes) != normalized_receipt["byte_size"]
        or _sha256(normalized_bytes) != normalized_receipt["sha256"]
    ):
        raise PromptCacheContractError("E_CACHE_NORMALIZED_HASH_DRIFT")
    input_tokens = 0
    cached_tokens = 0
    count = 0
    seen_event_ids: set[str] = set()
    expected_event_fields = {
        "schema_version",
        "raw_sha256",
        "raw_line_number",
        "event_id",
        "adapter_id",
        "adapter_version",
        "event_schema",
        "capture_invocation_id",
        "adapter_policy_sha256",
        "parser_version",
        "source_paths",
        "input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
    }
    for raw_line in normalized_bytes.decode("utf-8").splitlines():
        if not raw_line.strip():
            continue
        event = _strict_json_loads(raw_line)
        event_id = event.get("event_id") if isinstance(event, dict) else None
        if (
            not isinstance(event, dict)
            or set(event) != expected_event_fields
            or event.get("schema_version")
            != "goal-teams-normalized-usage-event-v2.39"
            or event.get("raw_sha256") != normalized_receipt["raw_sha256"]
            or event.get("adapter_id") != normalized_receipt["adapter_id"]
            or event.get("adapter_version") != normalized_receipt["adapter_version"]
            or event.get("event_schema") != normalized_receipt["event_schema"]
            or event.get("capture_invocation_id")
            != normalized_receipt["capture_invocation_id"]
            or event.get("adapter_policy_sha256")
            != normalized_receipt["adapter_policy_sha256"]
            or event.get("parser_version") != normalized_receipt["parser_version"]
            or event.get("source_paths")
            != {
                "input_tokens": "usage.input_tokens",
                "cached_input_tokens": "usage.cached_input_tokens",
            }
            or not _bounded_identifier(event_id)
            or event_id in seen_event_ids
        ):
            raise PromptCacheContractError("E_CACHE_NORMALIZED_BINDING")
        observed_input = _usage_integer(event.get("input_tokens"))
        observed_cached = _usage_integer(event.get("cached_input_tokens"))
        observed_uncached = _usage_integer(event.get("uncached_input_tokens"))
        if (
            observed_input is None
            or observed_cached is None
            or observed_uncached is None
            or observed_cached > observed_input
            or observed_uncached != observed_input - observed_cached
        ):
            raise PromptCacheContractError("E_CACHE_NORMALIZED_BINDING")
        seen_event_ids.add(event_id)
        input_tokens += observed_input
        cached_tokens += observed_cached
        count += 1
    if count != normalized_receipt["event_count"]:
        raise PromptCacheContractError("E_CACHE_NORMALIZED_RECEIPT_BINDING")
    if (
        normalized_receipt["capture_invocation_id"]
        != identity["request_binding_id"]
        or normalized_receipt["adapter_policy_sha256"]
        != identity["host_adapter_identity_sha256"]
    ):
        raise PromptCacheContractError("E_CACHE_METRICS_IDENTITY_BINDING")
    identity_count = count + normalized_receipt["conflicting_events"]
    identity_sha = identity["identity_sha256"]
    metrics = {
        "schema_version": "goal-teams-cache-metrics-receipt-v2.39",
        "normalized_sha256": normalized_receipt["sha256"],
        "identity_sha256": identity_sha,
        "request_binding_id": identity["request_binding_id"],
        "adapter_identity_sha256": identity["host_adapter_identity_sha256"],
        "sample_count": count,
        "raw_event_count": normalized_receipt["raw_event_count"],
        "duplicate_events": normalized_receipt["duplicate_events"],
        "conflicting_events": normalized_receipt["conflicting_events"],
        "duplicate_detection_state": normalized_receipt[
            "duplicate_detection_state"
        ],
        "usage_status": (
            "partial"
            if normalized_receipt["conflicting_events"]
            else ("available" if count else "unavailable")
        ),
        "total_input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": input_tokens - cached_tokens,
        "cached_input_share": cached_tokens / input_tokens if input_tokens else None,
        "telemetry_coverage": count / identity_count if identity_count else 0.0,
        "request_hit_rate": None,
        "request_hit_rate_numerator": None,
        "request_hit_rate_denominator": None,
        "request_hit_rate_support_state": "unsupported",
        "request_hit_rate_reason": "turn_aggregate_has_no_request_semantics",
        "evidence_origin": "synthetic_fixture",
        "evidence_eligible": False,
        "claim_scope": "structural_only",
    }
    metrics["metrics_sha256"] = _sha256(_canonical_bytes(metrics))
    return metrics


def open_v238_cache_artifact(
    path: Path, expected_sha256: str, allowed_root: Path
) -> dict[str, Any]:
    """Open and bind a V2.38 artifact by its original immutable bytes."""

    path = Path(path).absolute()
    allowed_root = Path(allowed_root).absolute()
    if (
        not _is_sha256(expected_sha256)
        or _path_contains_symlink(allowed_root, stop=allowed_root)
        or _path_contains_symlink(path, stop=allowed_root)
    ):
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_PATH")
    try:
        relative = path.relative_to(allowed_root)
    except ValueError as exc:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_PATH") from exc
    if not relative.parts or not path.is_file():
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_PATH")
    source_bytes = path.read_bytes()
    actual_sha = _sha256(source_bytes)
    if actual_sha != expected_sha256:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_HASH")
    try:
        parsed = _strict_json_loads(source_bytes.decode("utf-8"))
    except (_DuplicateJsonKeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_JSON") from exc
    try:
        parsed = _validated_v238_cache_identity_record(parsed)
    except PromptCacheContractError as exc:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_SCHEMA") from exc
    result = _V238SourceArtifactReceipt(
        {
            "schema_version": "goal-teams-v238-source-artifact-receipt-v1",
            "source_artifact_ref": relative.as_posix(),
            "size": len(source_bytes),
            "source_schema_version": parsed["schema_version"],
            "source_record_sha256": actual_sha,
            "read_only": True,
        }
    )
    return _seal_bound_receipt(
        result,
        private={"source_path": path, "allowed_root": allowed_root},
    )


def replay_v238_cache_record(source_artifact_receipt: dict[str, Any]) -> dict[str, Any]:
    """Replay only a safely opened V2.38 source artifact receipt."""

    public, private = _validated_bound_receipt(
        source_artifact_receipt,
        _V238SourceArtifactReceipt,
        "E_CACHE_REPLAY_SOURCE_TYPE",
    )
    expected_fields = {
        "schema_version",
        "source_artifact_ref",
        "size",
        "source_schema_version",
        "source_record_sha256",
        "read_only",
    }
    if (
        set(public) != expected_fields
        or set(private) != {"source_path", "allowed_root"}
        or public.get("schema_version")
        != "goal-teams-v238-source-artifact-receipt-v1"
        or public.get("source_schema_version")
        != "goal-teams-cache-identity-v2.38"
        or public.get("read_only") is not True
        or not isinstance(public.get("size"), int)
        or isinstance(public.get("size"), bool)
        or public["size"] < 0
        or not _is_sha256(public.get("source_record_sha256"))
    ):
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_TYPE")
    path = private["source_path"]
    root = private["allowed_root"]
    if not isinstance(path, Path) or not isinstance(root, Path):
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_TYPE")
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_PATH") from exc
    if relative != public["source_artifact_ref"]:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_PATH")
    if _path_contains_symlink(path, stop=root) or not path.is_file():
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_PATH")
    source_bytes = path.read_bytes()
    if (
        len(source_bytes) != public["size"]
        or _sha256(source_bytes)
        != public["source_record_sha256"]
    ):
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_HASH")
    try:
        parsed = _strict_json_loads(source_bytes.decode("utf-8"))
    except (_DuplicateJsonKeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_JSON") from exc
    try:
        parsed = _validated_v238_cache_identity_record(parsed)
    except PromptCacheContractError as exc:
        raise PromptCacheContractError("E_CACHE_REPLAY_SOURCE_SCHEMA") from exc
    result = {
        "schema_version": "goal-teams-cache-replay-sidecar-v2.39",
        "source_schema_version": public["source_schema_version"],
        "source_artifact_ref": public["source_artifact_ref"],
        "source_record_sha256": public["source_record_sha256"],
        "source_record_size": public["size"],
        "evidence_origin": "v238_source_artifact_raw_bytes",
        "evidence_eligible": True,
        "evidence_scope": "source_bytes_only",
        "semantic_validation_state": "unavailable",
        "legacy_payload_state": "omitted_sensitive_by_contract",
        "structural_delivery_state": "passed",
        "host_integration_state": "unavailable",
        "live_cache_validation_state": "unavailable",
        "request_hit_rate_support_state": "unsupported",
        "request_hit_rate": None,
        "stable_prefix_digest": None,
        "runtime_prompt_digest": None,
        "missing_capabilities": [
            "host_capability_receipt",
            "ordered_runtime_prompt_identity_v2.39",
            "trusted_host_attestation",
            "request_hit_semantics",
        ],
        "migration_action": "read_only_sidecar",
    }
    result["sidecar_sha256"] = _sha256(_canonical_bytes(result))
    return result


__all__ = [
    "PromptCacheContractError",
    "aggregate_normalized_events",
    "aggregate_request_usage_events",
    "aggregate_usage_events",
    "build_test_only_adapter_receipt",
    "build_cache_status_axes",
    "build_ordered_prompt_identity",
    "build_ordered_prompt_identity_v239",
    "build_host_capability_receipt",
    "build_prompt_identity",
    "build_prompt_identity_for_refs",
    "build_cache_probe_plan",
    "load_production_cache_policy",
    "load_raw_usage_receipt",
    "load_prompt_manifest",
    "normalize_usage_events",
    "open_v238_cache_artifact",
    "order_prompt_refs",
    "persist_usage_events",
    "replay_v238_cache_record",
    "replay_v238_cache_record_test_only_non_evidence",
    "verify_live_authorization",
    "verify_host_attestation",
]
