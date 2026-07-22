#!/usr/bin/env python3
"""Execute and score Goal Teams V2.3 benchmark scenarios with provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
V23_MODULE_DIR = ROOT / "scripts" / "v23"
if str(V23_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(V23_MODULE_DIR))

from package_selection import (  # noqa: E402
    BLIND_PACKAGE_ALLOWLIST,
    PackageSelectionError,
    blind_path_allowed,
    build_blind_package_selection,
)
from engineering_metrics import (  # noqa: E402
    load_history_summaries as load_engineering_metrics_history,
    load_input_payload as load_engineering_metrics_input,
    load_manifest as load_engineering_metrics_manifest,
    write_outputs as write_engineering_metrics_outputs,
)
from prompt_cache import aggregate_usage_events, build_prompt_identity  # noqa: E402

V23_TOOL = ROOT / "scripts" / "v23" / "goalteams_v23.py"
TASKS_DIR = ROOT / "benchmarks" / "tasks"
REQUIRED_FILES = ["task.md", "harness.md", "scoring.md", "expected-artifacts.md"]
REQUIRED_TERMS = ["baseline", "goal-teams", "scoring"]
BLIND_SCHEMA_VERSION = "goal-teams-blind-eval-v2.3"
BLIND_BOOTSTRAP_REFS = ("AGENTS.md", "SKILL.md", "RULES.md")
BLIND_SUBJECT_PREAMBLE = """你正在盲评当前隔离目录中实际暂存的 Goal Teams V2.3 Skill 包。
必须先读取 AGENTS.md、SKILL.md、RULES.md，再按 SKILL.md 的渐进式路由读取完成本场景所需 references；禁止读取当前隔离目录之外的文件。
不得创建或修改任何文件，不得尝试寻找评分器、manifest、tests、benchmarks 或 canonical answers。
最终只能输出一个严格 JSON 对象，禁止 Markdown 围栏或附加文字；除场景指定字段外，必须额外包含 loaded_refs 数组，列出实际读取的仓库相对路径。

场景：
"""
class BlindEvalError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_path(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nonnegative_int(value: Any) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _observer_telemetry(jsonl_text: str) -> dict[str, Any]:
    """Preserve parser evidence while adding only runner-owned provenance."""

    observed = dict(aggregate_usage_events(jsonl_text))
    adapter_versions: set[str] = set()
    event_schema_versions: set[str] = set()
    legacy_adapter_observed = False
    legacy_schema_observed = False
    for raw in jsonl_text.splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        adapter_version = event.get("adapter_version")
        if isinstance(adapter_version, str) and adapter_version:
            adapter_versions.add(adapter_version)
        elif adapter_version is None:
            legacy_adapter_observed = True
        event_schema_version = event.get(
            "event_schema_version", event.get("schema_version", event.get("version"))
        )
        if isinstance(event_schema_version, str) and event_schema_version:
            event_schema_versions.add(event_schema_version)
        elif event_schema_version is None:
            legacy_schema_observed = True
    if legacy_adapter_observed:
        adapter_versions.add("legacy-unversioned")
    if legacy_schema_observed:
        event_schema_versions.add("legacy-unversioned")
    observed.update(
        {
            "schema_version": "goal-teams-observer-telemetry-v2.38",
            "visibility": "observer",
            "source": "codex_exec_jsonl",
            "observed_adapter_versions": sorted(adapter_versions),
            "observed_event_schema_versions": sorted(event_schema_versions),
            "turn_completed_count": _nonnegative_int(observed.get("completed_turns")),
            "usage_observed_count": _nonnegative_int(observed.get("telemetry_turns")),
        }
    )
    return observed


def _summarize_identity_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    telemetry_records = [
        record.get("observer_telemetry", {})
        for record in records
        if isinstance(record.get("observer_telemetry"), dict)
    ]
    completed_turns = sum(
        _nonnegative_int(item.get("turn_completed_count")) for item in telemetry_records
    )
    telemetry_turns = sum(
        _nonnegative_int(item.get("usage_observed_count")) for item in telemetry_records
    )
    input_tokens = sum(_nonnegative_int(item.get("input_tokens")) for item in telemetry_records)
    covered_input_tokens = sum(
        _nonnegative_int(item.get("covered_input_tokens")) for item in telemetry_records
    )
    cached_input_tokens = sum(
        _nonnegative_int(item.get("cached_input_tokens")) for item in telemetry_records
    )
    uncached_input_tokens = sum(
        _nonnegative_int(item.get("uncached_input_tokens")) for item in telemetry_records
    )
    output_tokens = sum(_nonnegative_int(item.get("output_tokens")) for item in telemetry_records)
    reasoning_output_tokens = sum(
        _nonnegative_int(item.get("reasoning_output_tokens"))
        for item in telemetry_records
    )
    invalid_events = sum(
        _nonnegative_int(item.get("invalid_events")) for item in telemetry_records
    )
    unsupported_events = sum(
        _nonnegative_int(item.get("unsupported_events")) for item in telemetry_records
    )
    duplicate_events = sum(
        _nonnegative_int(item.get("duplicate_events")) for item in telemetry_records
    )
    conflicting_events = sum(
        _nonnegative_int(item.get("conflicting_events")) for item in telemetry_records
    )
    malformed_lines = sum(
        _nonnegative_int(item.get("malformed_lines")) for item in telemetry_records
    )
    unavailable_turns = sum(
        _nonnegative_int(item.get("unavailable_turns")) for item in telemetry_records
    )
    ambiguous_duplicate_candidates = sum(
        _nonnegative_int(item.get("ambiguous_duplicate_candidates"))
        for item in telemetry_records
    )
    events_without_stable_id = sum(
        _nonnegative_int(item.get("events_without_stable_id"))
        for item in telemetry_records
    )
    turns_with_cached_input = sum(
        _nonnegative_int(item.get("turns_with_cached_input"))
        for item in telemetry_records
    )
    passed_count = sum(record.get("result") == "passed" for record in records)
    if (
        records
        and len(telemetry_records) == len(records)
        and all(
            _observer_telemetry_verification(item)["status"] == "complete"
            for item in telemetry_records
        )
    ):
        status = "available"
    elif telemetry_turns > 0 or any(item.get("status") == "partial" for item in telemetry_records):
        status = "partial"
    else:
        status = "unavailable"
    return {
        "schema_version": "goal-teams-observer-telemetry-summary-v2.38",
        "visibility": "observer",
        "source": "codex_exec_jsonl",
        "status": status,
        "scenario_count": len(records),
        "passed_scenario_count": passed_count,
        "turn_completed_count": completed_turns,
        "usage_observed_count": telemetry_turns,
        "input_tokens": input_tokens,
        "covered_input_tokens": covered_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "cached_input_share": (
            cached_input_tokens / covered_input_tokens if covered_input_tokens > 0 else None
        ),
        "telemetry_coverage": telemetry_turns / completed_turns if completed_turns > 0 else 0.0,
        "turns_with_cached_input": turns_with_cached_input,
        "turn_cache_presence": (
            turns_with_cached_input / telemetry_turns if telemetry_turns > 0 else None
        ),
        "invalid_events": invalid_events,
        "unsupported_events": unsupported_events,
        "duplicate_events": duplicate_events,
        "conflicting_events": conflicting_events,
        "malformed_lines": malformed_lines,
        "unavailable_turns": unavailable_turns,
        "ambiguous_duplicate_candidates": ambiguous_duplicate_candidates,
        "events_without_stable_id": events_without_stable_id,
        "duplicate_detection_status": (
            "available"
            if telemetry_records
            and len(telemetry_records) == len(records)
            and all(
                item.get("duplicate_detection_status") == "available"
                for item in telemetry_records
            )
            else "partial"
        ),
        "uncached_input_tokens_per_passed_scenario": (
            uncached_input_tokens / passed_count if passed_count > 0 else None
        ),
        "quality_pass_rate": passed_count / len(records) if records else 0.0,
        "request_hit_rate": None,
        "request_hit_rate_reason": "turn_aggregate_cannot_estimate_request_hit_rate",
        "metric_semantics": "token_weighted_input_share_from_turn_aggregates",
        "parser_versions": sorted(
            {
                str(item["parser_version"])
                for item in telemetry_records
                if isinstance(item.get("parser_version"), str)
                and item.get("parser_version")
            }
        ),
        "adapter_registry_versions": sorted(
            {
                str(item["adapter_registry_version"])
                for item in telemetry_records
                if isinstance(item.get("adapter_registry_version"), str)
                and item.get("adapter_registry_version")
            }
        ),
        "observed_adapter_versions": sorted(
            {
                str(version)
                for item in telemetry_records
                for version in item.get("observed_adapter_versions", [])
                if isinstance(version, str) and version
            }
        ),
        "observed_event_schema_versions": sorted(
            {
                str(version)
                for item in telemetry_records
                for version in item.get("observed_event_schema_versions", [])
                if isinstance(version, str) and version
            }
        ),
        "raw_jsonl_sha256s": sorted(
            {
                str(item["raw_jsonl_sha256"])
                for item in telemetry_records
                if isinstance(item.get("raw_jsonl_sha256"), str)
                and item.get("raw_jsonl_sha256")
            }
        ),
    }


def _summarize_observer_telemetry(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        cache_identity = record.get("cache_identity")
        observer_telemetry = record.get("observer_telemetry")
        telemetry_complete = bool(
            isinstance(observer_telemetry, dict)
            and observer_telemetry.get("cache_analytics_status") == "supported"
            and _observer_telemetry_verification(observer_telemetry)["status"]
            == "complete"
        )
        supported = bool(
            isinstance(cache_identity, dict)
            and cache_identity.get("cache_analytics_status") == "supported"
            and isinstance(cache_identity.get("identity_sha256"), str)
            and cache_identity.get("identity_sha256")
            and telemetry_complete
        )
        if supported:
            group_key = f"supported:{cache_identity['identity_sha256']}"
        else:
            scenario_id = record.get("scenario_id")
            group_key = f"unsupported:{index}:{scenario_id}"
            if isinstance(cache_identity, dict):
                cache_identity = dict(cache_identity)
                if cache_identity.get("cache_analytics_status") == "supported":
                    missing_fields = list(
                        cache_identity.get("missing_identity_fields", [])
                    )
                    if "observer_telemetry.verification" not in missing_fields:
                        missing_fields.append("observer_telemetry.verification")
                    cache_identity.update(
                        {
                            "cache_analytics_status": "unsupported",
                            "cache_analytics_reason": "observer_telemetry_incomplete",
                            "identity_status": "incomplete",
                            "identity_sha256": None,
                            "missing_identity_fields": missing_fields,
                        }
                    )
            else:
                cache_identity = {
                    "schema_version": "goal-teams-cache-identity-v2.38",
                    "cache_analytics_status": "unsupported",
                    "cache_analytics_reason": "cache_identity_missing",
                    "identity_sha256": None,
                    "partial_identity_sha256": None,
                    "missing_identity_fields": ["cache_identity"],
                }
        group = grouped.setdefault(
            group_key,
            {"cache_identity": cache_identity, "records": []},
        )
        group["records"].append(record)

    identity_groups: list[dict[str, Any]] = []
    for group_key in sorted(grouped):
        group = grouped[group_key]
        group_records = group["records"]
        telemetry = _summarize_identity_group(group_records)
        cache_identity = group["cache_identity"]
        telemetry.update(
            {
                "cache_identity": cache_identity,
                "cache_analytics_status": cache_identity.get(
                    "cache_analytics_status", "unsupported"
                ),
                "cache_analytics_reason": cache_identity.get(
                    "cache_analytics_reason", "cache_identity_missing"
                ),
                "scenario_ids": sorted(
                    str(record.get("scenario_id")) for record in group_records
                ),
            }
        )
        if telemetry["cache_analytics_status"] != "supported":
            telemetry["cached_input_share"] = None
            telemetry["turn_cache_presence"] = None
            telemetry["uncached_input_tokens_per_passed_scenario"] = None
        identity_groups.append(telemetry)

    aggregate_permitted = bool(
        len(identity_groups) == 1
        and identity_groups[0].get("cache_analytics_status") == "supported"
        and identity_groups[0].get("status") == "available"
    )
    if aggregate_permitted:
        only = identity_groups[0]
        cache_status = "supported"
        cache_reason = "single_complete_cache_identity"
    elif not identity_groups or any(
        group.get("cache_analytics_status") == "unsupported"
        for group in identity_groups
    ):
        only = {}
        cache_status = "unsupported"
        cache_reason = "missing_or_incomplete_cache_identity"
    else:
        only = {}
        cache_status = "grouped"
        cache_reason = "multiple_cache_identities"
    passed_count = sum(record.get("result") == "passed" for record in records)
    metric_fields = (
        "turn_completed_count",
        "usage_observed_count",
        "input_tokens",
        "covered_input_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "cached_input_share",
        "telemetry_coverage",
        "turns_with_cached_input",
        "turn_cache_presence",
        "invalid_events",
        "unsupported_events",
        "duplicate_events",
        "conflicting_events",
        "malformed_lines",
        "unavailable_turns",
        "ambiguous_duplicate_candidates",
        "events_without_stable_id",
        "uncached_input_tokens_per_passed_scenario",
    )
    result = {
        "schema_version": "goal-teams-observer-telemetry-summary-v2.38",
        "visibility": "observer",
        "source": "codex_exec_jsonl",
        "status": only.get("status", "unavailable"),
        "cache_analytics_status": cache_status,
        "cache_analytics_reason": cache_reason,
        "cross_identity_aggregation": False,
        "identity_group_count": len(identity_groups),
        "identity_groups": identity_groups,
        "scenario_count": len(records),
        "passed_scenario_count": passed_count,
        "quality_pass_rate": passed_count / len(records) if records else 0.0,
        "request_hit_rate": None,
        "request_hit_rate_reason": "turn_aggregate_cannot_estimate_request_hit_rate",
        "metric_semantics": "token_weighted_input_share_grouped_by_complete_identity",
        "by_scenario": {
            str(record.get("scenario_id")): record.get("observer_telemetry")
            for record in records
            if isinstance(record.get("scenario_id"), str)
            and isinstance(record.get("observer_telemetry"), dict)
        },
    }
    for field in metric_fields:
        result[field] = only.get(field) if aggregate_permitted else None
    return result


def _command_model_identity(command: list[str]) -> dict[str, Any]:
    candidates: list[tuple[str, str]] = []
    index = 1
    while index < len(command):
        token = command[index]
        if token in {"--model", "-m"}:
            if index + 1 >= len(command) or not command[index + 1]:
                return {
                    "status": "unsupported",
                    "model": None,
                    "source": "command_argv",
                    "reason": "model_argument_missing_value",
                }
            candidates.append((token, command[index + 1]))
            index += 2
            continue
        if token.startswith("--model="):
            candidates.append(("--model", token.split("=", 1)[1]))
        elif token in {"--config", "-c"} and index + 1 < len(command):
            override = command[index + 1]
            if override.startswith("model="):
                candidates.append((token, override.split("=", 1)[1]))
            index += 1
        elif token.startswith("--config=model="):
            candidates.append(("--config", token.split("=", 2)[2]))
        index += 1
    normalized = [value.strip().strip("\"'") for _, value in candidates]
    normalized = [value for value in normalized if value]
    unique = sorted(set(normalized))
    if not unique:
        return {
            "status": "unsupported",
            "model": None,
            "source": "command_argv",
            "reason": "model_not_explicit_in_command",
        }
    if len(unique) != 1:
        return {
            "status": "unsupported",
            "model": None,
            "source": "command_argv",
            "reason": "conflicting_model_arguments",
            "candidate_count": len(unique),
        }
    return {
        "status": "bound",
        "model": unique[0],
        "source": "command_argv",
        "argument_sha256": digest_bytes(canonical_bytes(candidates)),
    }


def _effective_config_trace_verification(
    trace_proof: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate an optional host-produced trace without trusting a CLI declaration."""

    if trace_proof is None:
        return {
            "status": "unavailable",
            "trace_proof_sha256": None,
            "reason": "host_effective_config_trace_not_provided",
        }
    return {
        "status": "invalid_untrusted",
        "trace_proof_sha256": None,
        "reason": "self_reported_trace_proof_not_accepted",
    }


def _effective_codex_config_identity(
    command: list[str],
    *,
    codex_home: Path | None = None,
    trace_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hash config inputs while keeping CLI declarations distinct from trace proof."""

    ignored = "--ignore-user-config" in command
    trace_verification = _effective_config_trace_verification(trace_proof)
    # No host-attestation verifier is wired into this runner yet.  A CLI flag,
    # caller-supplied mapping, or plain hash is a declaration, never proof.
    if ignored:
        entries: list[dict[str, Any]] = []
        return {
            "schema_version": "goal-teams-effective-codex-config-v2.38",
            "isolation_mode": "user_config_ignore_declared",
            "declaration_status": "declared",
            "verification_status": "partial",
            "effective_config_verified": False,
            "isolation_verified": False,
            "trace_proof_status": trace_verification["status"],
            "trace_proof_sha256": trace_verification["trace_proof_sha256"],
            "verification_reason": trace_verification["reason"],
            "user_config_ignored": True,
            "local_config_scanned": False,
            "file_count": 0,
            "class_counts": {name: 0 for name in ("config", "agents", "skills", "plugins")},
            "effective_manifest_sha256": digest_bytes(canonical_bytes(entries)),
            "entries": entries,
            "path_disclosure": "sha256_and_class_only",
            "raw_config_persisted": False,
        }

    home = Path(
        codex_home
        if codex_home is not None
        else os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    ).expanduser()
    entries: list[dict[str, Any]] = []
    seen: set[Path] = set()

    def add_file(path: Path, config_class: str) -> None:
        try:
            if path in seen or not path.is_file() or path.is_symlink():
                return
            relative = path.relative_to(home).as_posix()
        except (OSError, ValueError):
            return
        seen.add(path)
        entries.append(
            {
                "path_sha256": digest_bytes(relative.encode("utf-8")),
                "class": config_class,
                "size": path.stat().st_size,
                "content_sha256": digest_path(path),
            }
        )

    add_file(home / "config.toml", "config")
    for config_class in ("config", "agents", "skills", "plugins"):
        base = home / config_class
        if not base.is_dir() or base.is_symlink():
            continue
        for directory, directory_names, file_names in os.walk(base, followlinks=False):
            directory_path = Path(directory)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not (directory_path / name).is_symlink()
            )
            for name in sorted(file_names):
                add_file(directory_path / name, config_class)
    entries.sort(key=lambda item: (item["class"], item["path_sha256"]))
    class_counts = {
        name: sum(entry["class"] == name for entry in entries)
        for name in ("config", "agents", "skills", "plugins")
    }
    return {
        "schema_version": "goal-teams-effective-codex-config-v2.38",
        "isolation_mode": "local_config_manifest_observed",
        "declaration_status": "observed_local_manifest",
        "verification_status": "partial",
        "effective_config_verified": False,
        "isolation_verified": False,
        "trace_proof_status": trace_verification["status"],
        "trace_proof_sha256": trace_verification["trace_proof_sha256"],
        "verification_reason": trace_verification["reason"],
        "user_config_ignored": False,
        "local_config_scanned": True,
        "file_count": len(entries),
        "class_counts": class_counts,
        "effective_manifest_sha256": digest_bytes(canonical_bytes(entries)),
        "entries": entries,
        "path_disclosure": "sha256_and_class_only",
        "raw_config_persisted": False,
    }


def _nonempty_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _observer_telemetry_verification(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless observer evidence is complete and ambiguity-free."""

    counter_fields = (
        "invalid_events",
        "unsupported_events",
        "duplicate_events",
        "conflicting_events",
        "malformed_lines",
        "unavailable_turns",
        "ambiguous_duplicate_candidates",
        "events_without_stable_id",
    )
    failures: list[str] = []
    if telemetry.get("status") != "available":
        failures.append("status")
    for field in counter_fields:
        value = telemetry.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value != 0:
            failures.append(field)
    if telemetry.get("duplicate_detection_status") != "available":
        failures.append("duplicate_detection_status")
    if telemetry.get("observed_adapter_versions") != ["codex-cli-jsonl-v1"]:
        failures.append("observed_adapter_versions")
    if telemetry.get("observed_event_schema_versions") != [
        "codex-turn-completed-v1"
    ]:
        failures.append("observed_event_schema_versions")
    coverage = telemetry.get("telemetry_coverage")
    if not isinstance(coverage, (int, float)) or isinstance(coverage, bool) or coverage != 1:
        failures.append("telemetry_coverage")
    return {
        "status": "complete" if not failures else "incomplete",
        "required_status": "available",
        "required_duplicate_detection_status": "available",
        "required_observed_adapter_versions": ["codex-cli-jsonl-v1"],
        "required_observed_event_schema_versions": ["codex-turn-completed-v1"],
        "required_telemetry_coverage": 1.0,
        "required_zero_counters": list(counter_fields),
        "failure_fields": failures,
    }


def _build_cache_record_identity(
    *,
    staged_root: Path,
    manifest: dict[str, Any],
    scenario: dict[str, Any],
    adapter: dict[str, Any],
    command: list[str],
    prompt_identity: dict[str, Any],
    provider_version: str,
    executable_sha256: str,
    staged_package_sha256: str,
    effective_config: dict[str, Any],
    observer_telemetry: dict[str, Any],
) -> dict[str, Any]:
    version_path = staged_root / "VERSION"
    product_version = None
    if version_path.is_file() and not version_path.is_symlink():
        try:
            product_version = _nonempty_string(version_path.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeDecodeError):
            product_version = None
    policy_profile = _nonempty_string(
        scenario.get("policy_profile", manifest.get("policy_profile"))
    )
    gate_profile = _nonempty_string(
        scenario.get("gate_profile", manifest.get("gate_profile"))
    )
    adapter_type = _nonempty_string(adapter.get("type"))
    provider = _nonempty_string(adapter.get("provider"))
    agent_identity = {
        "agent_type": adapter_type,
        "provider": provider,
        "declared_agent": _nonempty_string(adapter.get("agent_identity")),
    }
    route_identity = {
        "route_id": _nonempty_string(prompt_identity.get("route_id")),
        "scenario_class": _nonempty_string(scenario.get("scenario_class")) or "core",
    }
    model_identity = _command_model_identity(command)
    command_identity_sha256 = digest_bytes(
        canonical_bytes(adapter.get("command", []))
    )
    adapter_payload = {
        "adapter_type": adapter_type,
        "provider": provider,
        "provider_version_sha256": digest_bytes(provider_version.encode("utf-8")),
        "executable_sha256": executable_sha256,
        "command_identity_sha256": command_identity_sha256,
    }
    adapter_identity = {
        **adapter_payload,
        "adapter_identity_sha256": digest_bytes(canonical_bytes(adapter_payload)),
    }
    parser_identity = {
        "parser_version": _nonempty_string(observer_telemetry.get("parser_version")),
        "adapter_registry_version": _nonempty_string(
            observer_telemetry.get("adapter_registry_version")
        ),
        "observed_adapter_versions": list(
            observer_telemetry.get("observed_adapter_versions", [])
        ),
        "observed_event_schema_versions": list(
            observer_telemetry.get("observed_event_schema_versions", [])
        ),
    }
    trace_claimed = bool(
        effective_config.get("trace_proof_sha256")
        or effective_config.get("trace_proof_status") == "available"
        or effective_config.get("effective_config_verified") is True
        or effective_config.get("verification_status") == "complete"
    )
    effective_config_verification = {
        "declared_verification_status": effective_config.get("verification_status"),
        "verification_status": "partial",
        "effective_config_verified": False,
        "attestation_verifier_status": "unavailable",
        "trace_proof_status": (
            "invalid_untrusted" if trace_claimed else "unavailable"
        ),
        "trace_proof_sha256": None,
    }
    observer_verification = _observer_telemetry_verification(observer_telemetry)
    digest_identity = {
        "prefix_manifest_sha256": prompt_identity.get("prefix_manifest_sha256"),
        "route_static_digest": prompt_identity.get("route_static_digest"),
        "stable_prefix_digest": prompt_identity.get("stable_prefix_digest"),
        "runtime_prompt_digest": prompt_identity.get("runtime_prompt_digest"),
        "manifest_status": prompt_identity.get("manifest_status"),
        "digest_scope": prompt_identity.get("digest_scope"),
        "staged_package_sha256": staged_package_sha256,
        "effective_config_manifest_sha256": effective_config.get(
            "effective_manifest_sha256"
        ),
        "effective_config_verification": effective_config_verification,
    }
    identity_payload = {
        "product_version": product_version,
        "policy_profile": policy_profile,
        "gate_profile": gate_profile,
        "agent_identity": agent_identity,
        "route_identity": route_identity,
        "model_identity": model_identity,
        "adapter_identity": adapter_identity,
        "parser_identity": parser_identity,
        "digest_identity": digest_identity,
    }
    missing: list[str] = []
    if product_version is None:
        missing.append("product_version")
    if policy_profile is None:
        missing.append("policy_profile")
    if gate_profile is None:
        missing.append("gate_profile")
    if adapter_type is None or provider is None:
        missing.append("agent_identity")
    if route_identity["route_id"] is None:
        missing.append("route_identity.route_id")
    if model_identity.get("status") != "bound":
        missing.append("model_identity.model")
    if not parser_identity["parser_version"]:
        missing.append("parser_identity.parser_version")
    if not parser_identity["adapter_registry_version"]:
        missing.append("parser_identity.adapter_registry_version")
    if not _nonempty_string(digest_identity.get("runtime_prompt_digest")):
        missing.append("digest_identity.runtime_prompt_digest")
    if not _nonempty_string(digest_identity.get("effective_config_manifest_sha256")):
        missing.append("digest_identity.effective_config_manifest_sha256")
    # Cache conclusions stay disabled until a real host-attestation verifier is
    # wired in.  Caller-provided booleans and hashes are not an authority.
    missing.append("digest_identity.effective_config_verification")
    missing.extend(
        f"observer_telemetry.{field}"
        for field in observer_verification["failure_fields"]
    )
    partial_identity_sha256 = digest_bytes(canonical_bytes(identity_payload))
    supported = not missing
    if observer_verification["status"] != "complete":
        cache_reason = "observer_telemetry_incomplete"
    elif "digest_identity.effective_config_verification" in missing:
        cache_reason = "effective_config_verification_incomplete"
    elif missing:
        cache_reason = "missing_required_identity"
    else:
        cache_reason = "complete_identity_and_telemetry"
    return {
        "schema_version": "goal-teams-cache-identity-v2.38",
        **identity_payload,
        "observer_telemetry_verification": observer_verification,
        "identity_sha256": partial_identity_sha256 if supported else None,
        "partial_identity_sha256": partial_identity_sha256,
        "identity_status": "complete" if supported else "incomplete",
        "missing_identity_fields": missing,
        "cache_analytics_status": "supported" if supported else "unsupported",
        "cache_analytics_reason": cache_reason,
    }


def _bind_observer_cache_identity(
    telemetry: dict[str, Any],
    cache_identity: dict[str, Any],
) -> dict[str, Any]:
    bound = dict(telemetry)
    telemetry_verification = _observer_telemetry_verification(telemetry)
    identity_supported = cache_identity.get("cache_analytics_status") == "supported"
    supported = identity_supported and telemetry_verification["status"] == "complete"
    reason = (
        cache_identity.get("cache_analytics_reason", "missing_required_identity")
        if not identity_supported
        else (
            "complete_identity_and_telemetry"
            if supported
            else "observer_telemetry_incomplete"
        )
    )
    bound.update(
        {
            "cache_analytics_status": "supported" if supported else "unsupported",
            "cache_analytics_reason": reason,
            "cache_identity_sha256": (
                cache_identity.get("identity_sha256") if supported else None
            ),
            "observer_telemetry_verification": telemetry_verification,
            "cache_conclusion": {
                "status": "supported" if supported else "unsupported",
                "reason": reason,
                "cached_input_share": (
                    bound.get("cached_input_share") if supported else None
                ),
                "turn_cache_presence": (
                    bound.get("turn_cache_presence") if supported else None
                ),
            },
        }
    )
    return bound


def _build_benchmark_prompt_identity_report(
    source_root: Path,
    staged_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the subject identity from staged bytes and compare source separately."""

    subject_identity = build_prompt_identity(staged_root, "benchmark")
    source_identity = build_prompt_identity(source_root, "benchmark")
    compared_fields = (
        "ordered_refs",
        "dynamic_tail_labels",
        "prefix_manifest_sha256",
        "route_static_digest",
        "stable_prefix_digest",
        "runtime_prompt_digest",
        "manifest_status",
        "digest_scope",
        "route_bytes",
        "limit_bytes",
        "passed",
        "files",
    )
    mismatch_fields = [
        field
        for field in compared_fields
        if source_identity.get(field) != subject_identity.get(field)
    ]
    comparison = {
        "schema_version": "goal-teams-source-stage-prompt-identity-v2.38",
        "subject_identity_scope": "staged_package",
        "diagnostic_identity_scope": "source_repository",
        "identities_match": not mismatch_fields,
        "mismatch_fields": mismatch_fields,
        "source_prefix_manifest_sha256": source_identity["prefix_manifest_sha256"],
        "source_route_static_digest": source_identity.get("route_static_digest"),
        "source_runtime_prompt_digest": source_identity.get("runtime_prompt_digest"),
        "source_route_bytes": source_identity["route_bytes"],
        "staged_prefix_manifest_sha256": subject_identity["prefix_manifest_sha256"],
        "staged_route_static_digest": subject_identity.get("route_static_digest"),
        "staged_runtime_prompt_digest": subject_identity.get("runtime_prompt_digest"),
        "staged_route_bytes": subject_identity["route_bytes"],
    }
    return subject_identity, comparison


def repository_commit() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unavailable"


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def check_tasks() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task_dir in sorted(TASKS_DIR.glob("GT-BENCH-*")):
        missing = [name for name in REQUIRED_FILES if not (task_dir / name).is_file()]
        combined = "\n".join(
            (task_dir / name).read_text(encoding="utf-8")
            for name in REQUIRED_FILES
            if (task_dir / name).is_file()
        )
        combined_lower = combined.lower()
        missing_terms = [term for term in REQUIRED_TERMS if term.lower() not in combined_lower]
        rows.append(
            {
                "task": task_dir.name,
                "missing_files": missing,
                "missing_terms": missing_terms,
                "status": "package_structural_valid",
                "behavior_run": "not_counted_until_executed",
            }
        )
    if not rows:
        fail("No benchmark tasks found")
    failures = [row for row in rows if row["missing_files"] or row["missing_terms"]]
    if failures:
        fail(json.dumps(failures, ensure_ascii=False, indent=2))
    return rows


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    scenario_class: str
    command_name: str
    input_value: Any
    expected_returncode: int
    scorer: Callable[[dict[str, Any]], bool]
    prepare: Callable[[Path, Any], list[str]]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _attach_benchmark_engineering_metrics(
    record: dict[str, Any],
    scenario_dir: Path,
    *,
    evaluation_id: str,
    execution_mode: str,
    rubric_digest: str,
    model_and_config_identity: str,
    manifest: dict[str, Any],
    history: Sequence[Mapping[str, Any]],
) -> None:
    """Generate one honest metrics sidecar/summary/OKF report for a scenario.

    Benchmark quality scoring is deliberately not converted into FPAR.  Only
    explicitly collected metric events can make a metric final.
    """

    metrics_dir = scenario_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=False)
    run_identity = {
        "run_id": str(record["subject_run_id"]),
        "completed_at": str(record["ended_at"]),
        "repository_or_project_id": "goal-teams-benchmark",
        "project_version": "V2.43",
        "artifact_version": evaluation_id,
        "goal_teams_version": "V2.43",
        "benchmark": {
            "scenario_id": str(record["scenario_id"]),
            "execution_mode": execution_mode,
            "rubric_digest": rubric_digest,
            "model_and_config_identity": model_and_config_identity,
        },
    }
    events_path = metrics_dir / "metric-events.jsonl"
    events_path.write_text(
        json.dumps({"type": "run_identity", "run": run_identity}, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    summary_path = metrics_dir / "metric-summary.json"
    report_path = metrics_dir / "engineering-metrics.md"
    summary = write_engineering_metrics_outputs(
        load_engineering_metrics_input(events_path),
        history,
        summary_path,
        report_path,
        manifest,
    )
    relative_events = "metrics/metric-events.jsonl"
    relative_summary = "metrics/metric-summary.json"
    relative_report = "metrics/engineering-metrics.md"
    record["engineering_metrics"] = {
        **summary,
        "events_path": relative_events,
        "events_sha256": digest_path(events_path),
        "summary_path": relative_summary,
        "summary_sha256": digest_path(summary_path),
        "report_path": relative_report,
        "report_sha256": digest_path(report_path),
    }


def prepare_json_command(command: str, *, trailing: list[str] | None = None):
    def prepare(root: Path, value: Any) -> list[str]:
        write_json(root / "input.json", value)
        return [command, "input.json", *(trailing or [])]

    return prepare


def prepare_ledger(root: Path, value: Any) -> list[str]:
    events = value["events"]
    (root / "events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8"
    )
    return ["reduce-ledger", "events.jsonl"]


def prepare_forged_evidence(root: Path, value: Any) -> list[str]:
    (root / "artifact.txt").write_text("artifact\n", encoding="utf-8")
    (root / "run.log").write_text("run\n", encoding="utf-8")
    artifact_stat = (root / "artifact.txt").stat()
    log_stat = (root / "run.log").stat()
    payload = {
        "schema_version": "goal-teams-v2.3",
        "evidence_id": "EVD-FORGED",
        "check_id": "CHECK-FORGED",
        "run_id": "RUN-FORGED",
        "attempt_id": "ATT-FORGED",
        "artifact_ref": "artifact.txt",
        "artifact_sha256": "0" * 64,
        "artifact_size": artifact_stat.st_size,
        "artifact_mtime_ns": artifact_stat.st_mtime_ns,
        "producer_run_id": "RUN-FORGED",
        "created_at": "2026-07-10T00:00:01Z",
        "trust_level": "local_verified",
        "command": {
            "argv": ["false"],
            "cwd": ".",
            "started_at": "2026-07-10T00:00:00Z",
            "ended_at": "2026-07-10T00:00:01Z",
            "exit_code": 0,
            "log_path": "run.log",
            "log_sha256": digest_path(root / "run.log"),
            "log_size": log_stat.st_size,
            "log_mtime_ns": log_stat.st_mtime_ns,
        },
        "environment": {
            "commit": repository_commit(),
            "workspace_revision": repository_commit(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
    }
    write_json(root / "evidence.json", payload)
    return ["validate-evidence", "evidence.json", "--root", "."]


def prepare_self_review(root: Path, value: Any) -> list[str]:
    artifact = root / "artifact.txt"
    artifact.write_text("review target\n", encoding="utf-8")
    artifact_hash = digest_path(artifact)
    write_json(
        root / "script-review.json",
        {"ok": True, "exit_code": 0, "artifact_sha256": artifact_hash, "artifact_version": "V2.3"},
    )
    (root / "semantic-review.md").write_text("---\ntype: Semantic Review\n---\npass\n", encoding="utf-8")
    review = {
        "schema_version": "goal-teams-v2.3",
        "review_class": "comparison",
        "author_run_id": "RUN-SAME",
        "reviewer_run_id": "RUN-SAME",
        "artifact": {
            "artifact_ref": "artifact.txt",
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
        },
        "script_review": {
            "reviewer_run_id": "RUN-SCRIPT",
            "tool": "validate-artifact",
            "status": "passed",
            "exit_code": 0,
            "evidence_path": "script-review.json",
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
        },
        "llm_review": {
            "reviewer_run_id": "RUN-SAME",
            "reviewer": "self",
            "status": "passed",
            "evidence_path": "semantic-review.md",
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
            "summary": "invalid self review fixture",
        },
        "final_decision": {"status": "pass", "reason": "fixture"},
    }
    write_json(root / "review.json", review)
    return ["validate-dual-review", "review.json", "--root", "."]


def event(event_id: str, task_id: str, revision: int, state: str) -> dict[str, Any]:
    owner_run_id = f"RUN-BENCH-OWNER-{task_id}"
    payload: dict[str, Any] = {"task_state": state}
    if revision == 0:
        payload.update(
            {
                "title": task_id,
                "required_for_done": False,
                "acceptance_blocking": False,
                "owner_member_id": f"owner-{task_id}",
                "owner_run_id": owner_run_id,
                "validator_member_id": f"validator-{task_id}",
                "validator_run_id": f"RUN-BENCH-VALIDATOR-{task_id}",
                "merge_owner_run_id": "RUN-BENCH-LEDGER-OWNER",
                "check_state": "not_started",
                "requirement_refs": [],
                "acceptance_criteria_refs": [],
                "artifact_refs": [],
                "evidence_refs": [],
                "harness_refs": [],
            }
        )
    return {
        "schema_version": "goal-teams-v2.3",
        "event_id": event_id,
        "event_type": "task_patch",
        "task_id": task_id,
        "attempt_id": f"ATT-{event_id}",
        "actor_run_id": owner_run_id,
        "ledger_owner_run_id": "RUN-BENCH-LEDGER-OWNER",
        "base_revision": revision,
        "timestamp": "2026-07-10T00:00:00Z",
        "payload": payload,
    }


def parse_cli_output(output: dict[str, Any]) -> dict[str, Any]:
    value = output.get("envelope")
    return value if isinstance(value, dict) else {}


def route_profile(profile: str):
    return lambda output: parse_cli_output(output).get("route", {}).get("profile") == profile


def capability_field(key: str, expected: Any):
    return lambda output: parse_cli_output(output).get("capability", {}).get(key) == expected


def scenarios() -> list[Scenario]:
    full_capability = json.loads((ROOT / "tests/v23/fixtures/capability/full.json").read_text(encoding="utf-8"))
    restricted_capability = json.loads((ROOT / "tests/v23/fixtures/capability/restricted.json").read_text(encoding="utf-8"))
    telemetry_unavailable = dict(full_capability, telemetry="unavailable")
    recovery_events = [
        event("E1", "TASK-RECOVERY", 0, "planned"),
        event("E2", "TASK-RECOVERY", 1, "running"),
        event("E3", "TASK-RECOVERY", 2, "blocked"),
        event("E4", "TASK-RECOVERY", 3, "running"),
    ]
    conflict_events = [
        event("E1", "TASK-CONFLICT", 0, "planned"),
        event("E2", "TASK-CONFLICT", 0, "running"),
    ]
    return [
        Scenario("plan-preview", "core", "route", {"risk": "low"}, 0, route_profile("lite"), prepare_json_command("route")),
        Scenario("backend-cli", "core", "route", {"backend": True, "tests": True}, 0, route_profile("full"), prepare_json_command("route")),
        Scenario("ui-replica", "core", "route", {"ui": True, "replica": True}, 0, route_profile("full"), prepare_json_command("route")),
        Scenario(
            "long-task-recovery",
            "core",
            "reduce-ledger",
            {"events": recovery_events},
            0,
            lambda output: parse_cli_output(output).get("state", {}).get("tasks", {}).get("TASK-RECOVERY", {}).get("task_state") == "running",
            prepare_ledger,
        ),
        Scenario(
            "revision-conflict",
            "stress",
            "reduce-ledger",
            {"events": conflict_events},
            1,
            lambda output: (
                parse_cli_output(output).get("error_code") == "E_REVISION_CONFLICT"
                and bool(parse_cli_output(output).get("state", {}).get("conflicts"))
            ),
            prepare_ledger,
        ),
        Scenario(
            "forged-evidence",
            "stress",
            "validate-evidence",
            {"mutation": "artifact hash mismatch"},
            1,
            lambda output: parse_cli_output(output).get("ok") is False,
            prepare_forged_evidence,
        ),
        Scenario(
            "self-review",
            "stress",
            "validate-dual-review",
            {"mutation": "author and reviewer share run id"},
            1,
            lambda output: parse_cli_output(output).get("ok") is False,
            prepare_self_review,
        ),
        Scenario(
            "telemetry-unavailable",
            "stress",
            "capability",
            telemetry_unavailable,
            0,
            capability_field("budget_metric", "round_time_member_file_size"),
            prepare_json_command("capability"),
        ),
        Scenario(
            "no-custom-agent",
            "stress",
            "capability",
            restricted_capability,
            0,
            capability_field("dispatch_mode", "generic_subagent_or_serial"),
            prepare_json_command("capability"),
        ),
    ]


def execute_scenario(scenario: Scenario, root: Path) -> dict[str, Any]:
    scenario_root = root / scenario.scenario_id
    scenario_root.mkdir(parents=True)
    argv = scenario.prepare(scenario_root, scenario.input_value)
    started_at = utc_now()
    proc = subprocess.run(
        [sys.executable, str(V23_TOOL), *argv],
        cwd=scenario_root,
        text=True,
        capture_output=True,
        check=False,
    )
    ended_at = utc_now()
    log_path = scenario_root / "subject-run.log"
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        envelope = {"parse_error": True, "stdout": proc.stdout}
    output = {"returncode": proc.returncode, "envelope": envelope}
    trace_path = scenario_root / "trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "command": scenario.command_name,
                "argv": argv,
                "expected_returncode": scenario.expected_returncode,
                "actual_returncode": proc.returncode,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    passed = proc.returncode == scenario.expected_returncode and scenario.scorer(output)
    score_path = scenario_root / "score.json"
    write_json(
        score_path,
        {
            "quality": 1.0 if passed else 0.0,
            "decision": "pass" if passed else "fail",
            "scorer_run_id": f"SCORER-{scenario.scenario_id}",
        },
    )
    record = {
        "schema_version": "goal-teams-v2.3",
        "scenario_id": scenario.scenario_id,
        "scenario_class": scenario.scenario_class,
        "input": scenario.input_value,
        "output": output,
        "executed": True,
        "result": "passed" if passed else "failed",
        "subject_run_id": f"SUBJECT-{scenario.scenario_id}",
        "scorer_run_id": f"SCORER-{scenario.scenario_id}",
        "started_at": started_at,
        "ended_at": ended_at,
        "environment": {
            "commit": repository_commit(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
        "provenance": {
            "runner_id": "goal-teams-benchmark-runner",
            "runner_version": "V2.3",
            "run_nonce": f"CONTRACT-{uuid.uuid4().hex}",
            "generated_at": utc_now(),
            "expected_exit_code": scenario.expected_returncode,
            "input_sha256": digest_bytes(canonical_bytes(scenario.input_value)),
            "output_sha256": digest_bytes(canonical_bytes(output)),
            "command": {
                "argv": [sys.executable, str(V23_TOOL), *argv],
                "cwd": ".",
                "exit_code": proc.returncode,
                "log_path": "subject-run.log",
                "log_sha256": digest_path(log_path),
            },
        },
        "trace": [{"path": "trace.jsonl", "sha256": digest_path(trace_path)}],
        "evidence": [{"path": "subject-run.log", "sha256": digest_path(log_path)}],
        "score": {
            "quality": 1.0 if passed else 0.0,
            "rubric_version": "behavior-v2.3",
            "scorer_run_id": f"SCORER-{scenario.scenario_id}",
            "evidence_path": "score.json",
            "evidence_sha256": digest_path(score_path),
        },
    }
    record_path = scenario_root / "record.json"
    write_json(record_path, record)
    validation = subprocess.run(
        [sys.executable, str(V23_TOOL), "validate-behavior", "record.json", "--root", "."],
        cwd=scenario_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if validation.returncode != 0:
        fail(f"{scenario.scenario_id} behavior record invalid: {validation.stdout}{validation.stderr}")
    if not passed:
        fail(f"{scenario.scenario_id} scorer failed: {json.dumps(output, ensure_ascii=False)}")
    return {
        "run": scenario.scenario_id,
        "scenario_class": scenario.scenario_class,
        "status": "executed_validated",
        "quality": 1.0,
    }


def execute_behavior_runs() -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="goal-teams-behavior-") as td:
        root = Path(td)
        return [execute_scenario(scenario, root) for scenario in scenarios()]


def _resolve_argv(argv: Any, output_last_message: Path | None = None) -> list[str]:
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "adapter command must be a non-empty string list")
    executable = shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
    if not executable or not Path(executable).is_file():
        raise BlindEvalError("E_BLIND_AGENT_RUNNER_MISSING", f"runner executable not found: {argv[0]}")
    replacements = {"{output_last_message}": str(output_last_message)} if output_last_message else {}
    return [str(executable), *(replacements.get(item, item) for item in argv[1:])]


def _workspace_status_digest() -> str:
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=False,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        return digest_bytes(proc.stdout)
    return digest_bytes(
        canonical_bytes(
            {
                "mode": "non_git_filesystem",
                "source_tree_sha256": _filesystem_source_digest(ROOT),
            }
        )
    )


_SOURCE_DIGEST_EXCLUDED_PARTS = frozenset(
    {
        ".codex",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "output",
        "outputs",
        "temp",
        "tmp",
    }
)


def _source_path_is_dynamic(relative: Path) -> bool:
    return bool(
        any(
            part in _SOURCE_DIGEST_EXCLUDED_PARTS
            or part.startswith("GoalTeamsWork-")
            for part in relative.parts
        )
        or relative.suffix in {".pyc", ".pyo"}
        or relative.name == ".DS_Store"
    )


def _filesystem_source_digest(root: Path) -> str:
    """Hash a non-Git installed package without treating runtime output as source."""
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if _source_path_is_dynamic(relative):
            continue
        data = path.read_bytes()
        entries.append(
            {
                "path": relative.as_posix(),
                "size": len(data),
                "sha256": digest_bytes(data),
            }
        )
    return digest_bytes(canonical_bytes(entries))


def _source_tree_digest() -> str:
    """Hash every tracked/unignored source file so dirty-state changes cannot hide."""
    proc = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        text=False,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return _filesystem_source_digest(ROOT)
    digest = hashlib.sha256()
    for raw in sorted(item for item in proc.stdout.split(b"\0") if item):
        relative = os.fsdecode(raw)
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def _blind_path_is_forbidden(relative: str) -> bool:
    return not blind_path_allowed(relative)


def _blind_path_is_allowlisted(relative: str) -> bool:
    return any(
        relative == allowed or relative.startswith(allowed.rstrip("/") + "/")
        for allowed in BLIND_PACKAGE_ALLOWLIST
    )


def _blind_package_selection(root: Path = ROOT) -> dict[str, Any]:
    try:
        return build_blind_package_selection(root)
    except PackageSelectionError as exc:
        raise BlindEvalError("E_PACKAGE_IDENTITY", str(exc)) from exc


def _tree_manifest(root: Path) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if ".git" in relative_path.parts:
            continue
        if path.is_symlink():
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_NONREGULAR",
                f"symlink is forbidden in blind package tree: {relative_path.as_posix()}",
            )
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_NONREGULAR",
                f"non-regular entry is forbidden in blind package tree: {relative_path.as_posix()}",
            )
        permissions = stat.S_IMODE(mode)
        if permissions not in {0o644, 0o755}:
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_MODE",
                f"non-canonical file mode in blind package tree: {relative_path.as_posix()}",
            )
        entries.append(
            {
                "path": relative_path.as_posix(),
                "mode": "100755" if permissions == 0o755 else "100644",
                "size": path.stat().st_size,
                "sha256": digest_path(path),
            }
        )
    return entries, digest_bytes(canonical_bytes(entries))


def _stage_blind_package(destination: Path) -> dict[str, Any]:
    selection = _blind_package_selection(ROOT)
    destination.mkdir(parents=True, exist_ok=False)
    for selected_entry in selection["blind_safe_entries"]:
        relative = selected_entry["path"]
        expected_mode = selected_entry["mode"]
        if expected_mode not in {"100644", "100755"}:
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_MODE",
                f"tracked package path has unsupported Git mode {expected_mode}: {relative}",
            )
        source = ROOT / relative
        if source.is_symlink() or not source.exists():
            raise BlindEvalError("E_BLIND_AGENT_STAGE", f"tracked package path is missing or unsafe: {relative}")
        source_mode = source.lstat().st_mode
        if not stat.S_ISREG(source_mode):
            raise BlindEvalError("E_BLIND_AGENT_STAGE", f"tracked package path is not a regular file: {relative}")
        file_mode = stat.S_IMODE(source_mode)
        expected_permissions = 0o755 if expected_mode == "100755" else 0o644
        if file_mode != expected_permissions:
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_MODE",
                f"Git index/worktree mode drift for package path: {relative}",
            )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    entries, package_digest = _tree_manifest(destination)
    staged_paths = [entry["path"] for entry in entries]
    if entries != selection["files"] or package_digest != selection["package_sha256"]:
        raise BlindEvalError(
            "E_PACKAGE_IDENTITY",
            "staged bytes or modes differ from the pre-copy package selection",
        )
    leaked = [entry["path"] for entry in entries if _blind_path_is_forbidden(entry["path"])]
    if leaked:
        raise BlindEvalError("E_BLIND_AGENT_STAGE_LEAK", f"forbidden package paths staged: {leaked}")
    if staged_paths != selection["blind_safe_paths"]:
        raise BlindEvalError(
            "E_BLIND_AGENT_STAGE_SELECTION",
            "staged paths differ from the installer manifest Git-index projection",
        )
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    subprocess.run(["git", "config", "user.email", "blind-eval@example.invalid"], cwd=destination, check=True)
    subprocess.run(["git", "config", "user.name", "Goal Teams Blind Eval"], cwd=destination, check=True)
    subprocess.run(["git", "add", "--all"], cwd=destination, check=True)
    subprocess.run(["git", "commit", "-qm", "stage Goal Teams V2.3 package"], cwd=destination, check=True)
    staged_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=destination, text=True, capture_output=True, check=True
    ).stdout.strip()
    return {
        "source_commit": repository_commit(),
        "package_manifest_path": selection["package_manifest_path"],
        "package_manifest_sha256": selection["package_manifest_sha256"],
        "installer_tracked_paths_sha256": selection["installer_tracked_paths_sha256"],
        "installer_tracked_entries_sha256": selection["installer_tracked_entries_sha256"],
        "blind_safe_paths_sha256": selection["blind_safe_paths_sha256"],
        "blind_safe_entries_sha256": selection["blind_safe_entries_sha256"],
        "forbidden_exclusions": selection["forbidden_exclusions"],
        "forbidden_exclusions_sha256": selection["forbidden_exclusions_sha256"],
        "blind_safe_allowlist": selection["blind_safe_allowlist"],
        "blind_safe_allowlist_sha256": selection["blind_safe_allowlist_sha256"],
        "excluded_untracked": selection["excluded_untracked"],
        "file_count": len(entries),
        "files": entries,
        "package_sha256": package_digest,
        "staged_git_commit": staged_commit,
    }


def _commit_subject_input(workspace: Path, subject_input: dict[str, Any]) -> str:
    write_json(workspace / "scenario-input.json", subject_input)
    subprocess.run(["git", "add", "scenario-input.json"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "add blind scenario input"], cwd=workspace, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workspace, text=True, capture_output=True, check=True
    ).stdout.strip()


def _load_blind_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", f"invalid manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != BLIND_SCHEMA_VERSION:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "blind eval manifest schema mismatch")
    if not isinstance(payload.get("adapter"), dict) or not isinstance(payload.get("scenarios"), list) or not payload["scenarios"]:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "blind eval manifest requires adapter and scenarios")
    return payload


_MISSING = object()


def _effective_blind_scorer(scorer: Any) -> Any:
    if not isinstance(scorer, dict):
        return scorer
    effective = json.loads(json.dumps(scorer, ensure_ascii=False))
    allowed = effective.get("allowed_fields")
    required = effective.get("required_fields")
    if isinstance(allowed, list) and "loaded_refs" not in allowed:
        allowed.append("loaded_refs")
    if isinstance(required, list) and not any(
        isinstance(item, dict) and item.get("path") == "loaded_refs" for item in required
    ):
        required.append(
            {
                "path": "loaded_refs",
                "value_type": "array",
                "contains_all": list(BLIND_BOOTSTRAP_REFS),
            }
        )
    return effective


def _json_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _typed(value: Any, expected: str) -> bool:
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return False


def _score_blind_output(
    output: str,
    scorer: Any,
    subject_input: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not isinstance(scorer, dict):
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "scenario scorer must be an object")
    if scorer.get("type") != "json_contract":
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "blind scorer type must be json_contract")
    required = scorer.get("required_fields")
    allowed = scorer.get("allowed_fields")
    forbidden = scorer.get("forbidden_fields", [])
    bindings = scorer.get("input_bindings", [])
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in required)
        or not isinstance(allowed, list)
        or not all(isinstance(item, str) and item for item in allowed)
        or not isinstance(forbidden, list)
        or not all(isinstance(item, str) and item for item in forbidden)
        or not isinstance(bindings, list)
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("input_path"), str)
            and isinstance(item.get("output_path"), str)
            for item in bindings
        )
    ):
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "typed blind scorer fields are invalid")
    rubric_sha256 = digest_bytes(canonical_bytes(scorer))
    try:
        parsed = json.loads(output.strip())
    except json.JSONDecodeError as exc:
        return False, {
            "error_code": "E_BLIND_AGENT_OUTPUT_JSON",
            "parse_error": str(exc),
            "rubric_sha256": rubric_sha256,
        }
    if not isinstance(parsed, dict):
        return False, {
            "error_code": "E_BLIND_AGENT_OUTPUT_TYPE",
            "observed_type": type(parsed).__name__,
            "rubric_sha256": rubric_sha256,
        }
    violations: list[dict[str, Any]] = []
    for contract in required:
        path = contract["path"]
        value = _json_path(parsed, path)
        expected_type = contract.get("value_type")
        if value is _MISSING:
            violations.append({"path": path, "violation": "missing"})
            continue
        if not isinstance(expected_type, str) or not _typed(value, expected_type):
            violations.append(
                {"path": path, "violation": "type", "expected": expected_type, "observed": type(value).__name__}
            )
            continue
        if "equals" in contract and value != contract["equals"]:
            violations.append({"path": path, "violation": "equals"})
        if "enum" in contract and (not isinstance(contract["enum"], list) or value not in contract["enum"]):
            violations.append({"path": path, "violation": "enum"})
        if contract.get("nonempty") is True and not value:
            violations.append({"path": path, "violation": "nonempty"})
        minimum = contract.get("min_length")
        if minimum is not None and (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or not hasattr(value, "__len__")
            or len(value) < minimum
        ):
            violations.append({"path": path, "violation": "min_length"})
        contains_all = contract.get("contains_all")
        if contains_all is not None and (
            not isinstance(value, list)
            or not isinstance(contains_all, list)
            or not all(item in value for item in contains_all)
        ):
            violations.append({"path": path, "violation": "contains_all"})
    unexpected = sorted(set(parsed) - set(allowed))
    forbidden_present = sorted(path for path in forbidden if _json_path(parsed, path) is not _MISSING)
    for binding in bindings:
        expected = _json_path(subject_input or {}, binding["input_path"])
        observed = _json_path(parsed, binding["output_path"])
        if expected is _MISSING or observed is _MISSING or observed != expected:
            violations.append({"path": binding["output_path"], "violation": "input_binding"})
    if unexpected:
        violations.append({"paths": unexpected, "violation": "unexpected_fields"})
    if forbidden_present:
        violations.append({"paths": forbidden_present, "violation": "forbidden_fields"})
    return not violations, {
        "error_code": None if not violations else "E_BLIND_AGENT_OUTPUT_CONTRACT",
        "parsed_json": parsed,
        "violations": violations,
        "rubric_sha256": rubric_sha256,
        "required_field_count": len(required),
        "allowed_fields": sorted(allowed),
    }


def execute_blind_agent_eval(
    manifest_path: Path,
    output_dir: Path,
    *,
    release_gate: bool,
    selected_scenarios: set[str] | None = None,
    effective_config_trace_proof: dict[str, Any] | None = None,
    engineering_metrics_history: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    manifest = _load_blind_manifest(manifest_path)
    adapter = manifest["adapter"]
    adapter_type = adapter.get("type")
    provider = adapter.get("provider")
    if adapter_type not in {"codex_cli", "fixture"} or not isinstance(provider, str) or not provider:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "adapter type/provider is invalid")
    scenarios_to_run = [
        scenario
        for scenario in manifest["scenarios"]
        if isinstance(scenario, dict)
        and (not selected_scenarios or scenario.get("scenario_id") in selected_scenarios)
    ]
    required_ids = {
        scenario.get("scenario_id")
        for scenario in manifest["scenarios"]
        if isinstance(scenario, dict) and scenario.get("required") is True
    }
    selected_ids = {scenario.get("scenario_id") for scenario in scenarios_to_run}
    if not scenarios_to_run or (release_gate and not required_ids <= selected_ids):
        raise BlindEvalError("E_BLIND_AGENT_INCOMPLETE", "release eval must execute every required scenario")
    try:
        output_dir.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise BlindEvalError(
            "E_BLIND_AGENT_OUTPUT_SCOPE",
            "blind output must be persistent and outside the source repository",
        )
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise BlindEvalError("E_BLIND_AGENT_OUTPUT_EXISTS", "output directory must be new for this invocation") from exc
    invocation_id = f"BLIND-{uuid.uuid4().hex}"
    source_commit = repository_commit()
    source_status_before = _workspace_status_digest()
    source_tree_before = _source_tree_digest()
    runner_path = Path(__file__).resolve()
    runner_provenance = {
        "path": str(runner_path),
        "sha256": digest_path(runner_path),
        "size": runner_path.stat().st_size,
    }
    effective_rubrics = {
        str(scenario.get("scenario_id")): _effective_blind_scorer(scenario.get("scorer"))
        for scenario in scenarios_to_run
    }
    rubric_sha256 = digest_bytes(
        canonical_bytes(
            [
                {
                    "scenario_id": scenario_id,
                    "rubric_sha256": digest_bytes(canonical_bytes(rubric)),
                }
                for scenario_id, rubric in sorted(effective_rubrics.items())
            ]
        )
    )
    records: list[dict[str, Any]] = []
    record_refs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="goal-teams-v23-isolated-") as td:
        isolation_root = Path(td).resolve()
        staged_root = isolation_root / "staged-package"
        stage = _stage_blind_package(staged_root)
        prompt_identity, source_stage_prompt_identity = (
            _build_benchmark_prompt_identity_report(ROOT, staged_root)
        )
        base_command = _resolve_argv(adapter.get("command"))
        effective_codex_config = _effective_codex_config_identity(
            base_command,
            trace_proof=effective_config_trace_proof,
        )
        engineering_metrics_manifest = load_engineering_metrics_manifest()
        shutil.copytree(
            staged_root,
            output_dir / "staged-package",
            ignore=shutil.ignore_patterns(".git"),
        )
        write_json(output_dir / "stage-manifest.json", stage)
        stage_manifest_hash = digest_path(output_dir / "stage-manifest.json")
        version_argv = _resolve_argv(adapter.get("version_command"))
        version_proc = subprocess.run(
            version_argv, cwd=staged_root, text=True, capture_output=True, check=False
        )
        provider_version = (version_proc.stdout + version_proc.stderr).strip()
        executable = Path(base_command[0]).resolve()
        executable_sha256 = digest_path(executable)
        provider_provenance = {
            "adapter_type": adapter_type,
            "provider": provider,
            "provider_trust_level": "local_process_attested",
            "provider_version": provider_version,
            "version_argv": version_argv,
            "version_exit_code": version_proc.returncode,
            "executable": str(executable),
            "executable_sha256": executable_sha256,
            "invocation_id": invocation_id,
            "source_commit": source_commit,
            "staged_package_sha256": stage["package_sha256"],
            "staged_package_commit": stage["staged_git_commit"],
            "stage_manifest_sha256": stage_manifest_hash,
            "package_manifest_sha256": stage["package_manifest_sha256"],
            "installer_tracked_entries_sha256": stage["installer_tracked_entries_sha256"],
            "blind_safe_entries_sha256": stage["blind_safe_entries_sha256"],
            "forbidden_exclusions_sha256": stage["forbidden_exclusions_sha256"],
            "blind_safe_allowlist_sha256": stage["blind_safe_allowlist_sha256"],
        }
        for scenario in scenarios_to_run:
            scenario_id = scenario.get("scenario_id")
            prompt = scenario.get("prompt")
            context = scenario.get("subject_input", {})
            if (
                not isinstance(scenario_id, str)
                or not scenario_id
                or not isinstance(prompt, str)
                or not prompt
                or not isinstance(context, dict)
            ):
                raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "scenario id/prompt/subject_input is invalid")
            scenario_dir = output_dir / scenario_id
            scenario_dir.mkdir()
            subject_prompt = BLIND_SUBJECT_PREAMBLE + prompt
            subject_input = {
                "scenario_id": scenario_id,
                "prompt": subject_prompt,
                "context": context,
                "bootstrap_refs_required": list(BLIND_BOOTSTRAP_REFS),
                "response_contract": "one strict JSON object; no Markdown fences or prose",
            }
            write_json(scenario_dir / "input.json", subject_input)
            workspace = isolation_root / "workspaces" / scenario_id
            workspace.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged_root, workspace)
            scenario_commit = _commit_subject_input(workspace, subject_input)
            workspace_entries_before, workspace_digest_before = _tree_manifest(workspace)
            output_last_message = scenario_dir / "output.txt"
            command = _resolve_argv(adapter.get("command"), output_last_message)
            source_tree_pre_scenario = _source_tree_digest()
            source_status_pre_scenario = _workspace_status_digest()
            started_at = utc_now()
            proc = subprocess.run(
                command,
                cwd=workspace,
                input=subject_prompt,
                text=True,
                capture_output=True,
                check=False,
            )
            ended_at = utc_now()
            observer_telemetry = _observer_telemetry(proc.stdout)
            cache_identity = _build_cache_record_identity(
                staged_root=staged_root,
                manifest=manifest,
                scenario=scenario,
                adapter=adapter,
                command=command,
                prompt_identity=prompt_identity,
                provider_version=provider_version,
                executable_sha256=executable_sha256,
                staged_package_sha256=stage["package_sha256"],
                effective_config=effective_codex_config,
                observer_telemetry=observer_telemetry,
            )
            observer_telemetry = _bind_observer_cache_identity(
                observer_telemetry, cache_identity
            )
            (scenario_dir / "stdout.log").write_text(proc.stdout, encoding="utf-8")
            (scenario_dir / "stderr.log").write_text(proc.stderr, encoding="utf-8")
            if not output_last_message.is_file():
                output_last_message.write_text(proc.stdout, encoding="utf-8")
            output_text = output_last_message.read_text(encoding="utf-8")
            _, workspace_digest_after = _tree_manifest(workspace)
            workspace_commit_after = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
            source_tree_post_scenario = _source_tree_digest()
            source_status_post_scenario = _workspace_status_digest()
            effective_rubric = effective_rubrics[scenario_id]
            score_passed, score_details = _score_blind_output(output_text, effective_rubric, subject_input)
            workspace_unchanged = workspace_digest_before == workspace_digest_after
            source_unchanged = (
                source_tree_pre_scenario == source_tree_post_scenario
                and source_status_pre_scenario == source_status_post_scenario
            )
            passed = proc.returncode == 0 and score_passed and workspace_unchanged and source_unchanged
            scorer_run_id = f"SCORER-{invocation_id}-{scenario_id}"
            subject_run_id = f"SUBJECT-{invocation_id}-{scenario_id}"
            rubric = effective_rubric
            (scenario_dir / "rubric.json").write_bytes(canonical_bytes(rubric))
            score = {
                "schema_version": "goal-teams-blind-score-v2.3",
                "quality": 1.0 if passed else 0.0,
                "decision": "pass" if passed else "fail",
                "scorer_run_id": scorer_run_id,
                "workspace_unchanged": workspace_unchanged,
                "source_repository_unchanged": source_unchanged,
                "rubric_path": "rubric.json",
                "rubric_sha256": digest_path(scenario_dir / "rubric.json"),
                **score_details,
            }
            write_json(scenario_dir / "score.json", score)
            evaluation_class = "blind_agent" if adapter_type == "codex_cli" else "pipeline_fixture"
            release_eligible = bool(
                evaluation_class == "blind_agent"
                and provider == "openai-codex-cli"
                and version_proc.returncode == 0
                and "codex-cli" in provider_version.lower()
                and passed
                and stage["file_count"] > 0
                and not any(
                    _blind_path_is_forbidden(entry["path"])
                    for entry in workspace_entries_before
                    if entry["path"] != "scenario-input.json"
                )
            )
            output_value = {
                "parsed_json": score_details.get("parsed_json"),
                "subject_exit_code": proc.returncode,
            }
            record = {
                "schema_version": "goal-teams-v2.3",
                "scenario_id": scenario_id,
                "scenario_class": scenario.get("scenario_class", "core"),
                "evaluation_class": evaluation_class,
                "provider_trust_level": "local_process_attested",
                "release_eligible": release_eligible,
                "prompt_identity": prompt_identity,
                "source_stage_prompt_identity": source_stage_prompt_identity,
                "cache_identity": cache_identity,
                "cache_conclusion": observer_telemetry["cache_conclusion"],
                "observer_telemetry": observer_telemetry,
                "input": subject_input,
                "output": output_value,
                "executed": True,
                "result": "passed" if passed else "failed",
                "subject_run_id": subject_run_id,
                "scorer_run_id": scorer_run_id,
                "started_at": started_at,
                "ended_at": ended_at,
                "environment": {
                    "commit": source_commit,
                    "platform": platform.platform(),
                    "python_version": platform.python_version(),
                    "effective_codex_config": effective_codex_config,
                },
                "provider_provenance": provider_provenance,
                "isolation": {
                    "isolated_workspace": True,
                    "workspace_id": f"{invocation_id}-{scenario_id}",
                    "execution_cwd": str(workspace),
                    "workspace_git_commit": scenario_commit,
                    "workspace_git_commit_before": scenario_commit,
                    "workspace_git_commit_after": workspace_commit_after,
                    "workspace_sha256_before": workspace_digest_before,
                    "workspace_sha256_after": workspace_digest_after,
                    "workspace_unchanged": workspace_unchanged,
                    "source_tree_sha256_before": source_tree_pre_scenario,
                    "source_tree_sha256_after": source_tree_post_scenario,
                    "source_status_sha256_before": source_status_pre_scenario,
                    "source_status_sha256_after": source_status_post_scenario,
                    "source_repository_unchanged": source_unchanged,
                    "scorer_staged_with_subject": False,
                    "manifest_staged_with_subject": False,
                    "answer_bearing_roots_staged": False,
                    "bootstrap_refs_required": list(BLIND_BOOTSTRAP_REFS),
                    "subject_declared_loaded_refs": score_details.get("parsed_json", {}).get("loaded_refs", [])
                    if isinstance(score_details.get("parsed_json"), dict)
                    else [],
                },
                "provenance": {
                    "runner_id": "goal-teams-blind-agent-runner",
                    "runner_version": "V2.3",
                    "run_nonce": f"{invocation_id}-{scenario_id}",
                    "generated_at": utc_now(),
                    "expected_exit_code": 0,
                    "input_sha256": digest_bytes(canonical_bytes(subject_input)),
                    "output_sha256": digest_bytes(canonical_bytes(output_value)),
                    "command": {
                        "argv": command,
                        "cwd": str(workspace),
                        "exit_code": proc.returncode,
                        "log_path": "stdout.log",
                        "log_sha256": digest_path(scenario_dir / "stdout.log"),
                        "stdout_path": "stdout.log",
                        "stdout_sha256": digest_path(scenario_dir / "stdout.log"),
                        "stderr_path": "stderr.log",
                        "stderr_sha256": digest_path(scenario_dir / "stderr.log"),
                    },
                },
                "trace": [{"path": "stdout.log", "sha256": digest_path(scenario_dir / "stdout.log")}],
                "evidence": [
                    {"path": "output.txt", "sha256": digest_path(output_last_message)},
                    {"path": "stderr.log", "sha256": digest_path(scenario_dir / "stderr.log")},
                    {"path": "rubric.json", "sha256": digest_path(scenario_dir / "rubric.json")},
                ],
                "score": {
                    "quality": score["quality"],
                    "rubric_version": "blind-agent-json-contract-v2.3",
                    "rubric_sha256": score["rubric_sha256"],
                    "evaluation_rubric_sha256": rubric_sha256,
                    "scorer_run_id": scorer_run_id,
                    "evidence_path": "score.json",
                    "evidence_sha256": digest_path(scenario_dir / "score.json"),
                },
            }
            model_and_config_identity = (
                str(cache_identity["identity_sha256"])
                if isinstance(cache_identity, dict)
                and isinstance(cache_identity.get("identity_sha256"), str)
                and cache_identity.get("identity_sha256")
                else digest_bytes(
                    canonical_bytes(
                        {
                            "provider": provider,
                            "provider_version": provider_version,
                            "effective_codex_config": effective_codex_config,
                        }
                    )
                )
            )
            _attach_benchmark_engineering_metrics(
                record,
                scenario_dir,
                evaluation_id=str(manifest.get("evaluation_id") or invocation_id),
                execution_mode=evaluation_class,
                rubric_digest=score["rubric_sha256"],
                model_and_config_identity=model_and_config_identity,
                manifest=engineering_metrics_manifest,
                history=engineering_metrics_history,
            )
            record_path = scenario_dir / "record.json"
            write_json(record_path, record)
            record_refs.append(
                {
                    "scenario_id": scenario_id,
                    "path": f"{scenario_id}/record.json",
                    "sha256": digest_path(record_path),
                    "size": record_path.stat().st_size,
                }
            )
            records.append(record)
    source_tree_after = _source_tree_digest()
    source_status_after = _workspace_status_digest()
    source_repository_unchanged = (
        source_tree_before == source_tree_after and source_status_before == source_status_after
    )
    write_json(output_dir / "manifest.json", manifest)
    source_provenance = {
        "source_commit": source_commit,
        "source_tree_digest_before": source_tree_before,
        "source_tree_digest_after": source_tree_after,
        "source_status_digest_before": source_status_before,
        "source_status_digest_after": source_status_after,
        "source_repository_unchanged": source_repository_unchanged,
    }
    staged_manifest = {
        "path": "stage-manifest.json",
        "sha256": digest_path(output_dir / "stage-manifest.json"),
        "size": (output_dir / "stage-manifest.json").stat().st_size,
        "package_root": "staged-package",
        "staged_tree_digest": stage["package_sha256"],
        "staged_git_commit": stage["staged_git_commit"],
        "package_manifest_path": stage["package_manifest_path"],
        "package_manifest_sha256": stage["package_manifest_sha256"],
        "installer_tracked_paths_sha256": stage["installer_tracked_paths_sha256"],
        "installer_tracked_entries_sha256": stage["installer_tracked_entries_sha256"],
        "blind_safe_paths_sha256": stage["blind_safe_paths_sha256"],
        "blind_safe_entries_sha256": stage["blind_safe_entries_sha256"],
        "forbidden_exclusions_sha256": stage["forbidden_exclusions_sha256"],
        "blind_safe_allowlist_sha256": stage["blind_safe_allowlist_sha256"],
    }
    # Bind the global source/stage/rubric facts into every record after all
    # subject invocations have completed, then refresh record hashes/sizes.
    for index, ref in enumerate(record_refs):
        record_path = output_dir / ref["path"]
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["source_provenance"] = source_provenance
        record["staged_manifest"] = staged_manifest
        record["evaluation_rubric_sha256"] = rubric_sha256
        record["runner_provenance"] = runner_provenance
        write_json(record_path, record)
        ref["sha256"] = digest_path(record_path)
        ref["size"] = record_path.stat().st_size
        records[index] = record
    passed_ids = {record["scenario_id"] for record in records if record["result"] == "passed"}
    release_eligible_ids = {record["scenario_id"] for record in records if record["release_eligible"]}
    observer_telemetry = _summarize_observer_telemetry(records)
    summary = {
        "schema_version": BLIND_SCHEMA_VERSION,
        "evaluation_id": manifest.get("evaluation_id"),
        "invocation_id": invocation_id,
        "evaluation_class": "blind_agent" if adapter_type == "codex_cli" else "pipeline_fixture",
        "provider_trust_level": "local_process_attested",
        "provider_provenance": provider_provenance,
        "manifest_source_path": str(manifest_path),
        "manifest_source_sha256": digest_path(manifest_path),
        "source_provenance": source_provenance,
        "staged_manifest": staged_manifest,
        "rubric_sha256": rubric_sha256,
        "runner_provenance": runner_provenance,
        "source_repository_unchanged": source_repository_unchanged,
        "required_scenarios": sorted(required_ids),
        "passed_scenarios": sorted(passed_ids),
        "release_eligible_scenarios": sorted(release_eligible_ids),
        "prompt_identity": prompt_identity,
        "source_stage_prompt_identity": source_stage_prompt_identity,
        "effective_codex_config": effective_codex_config,
        "observer_telemetry": observer_telemetry,
        "uncached_input_tokens_per_passed_scenario": observer_telemetry[
            "uncached_input_tokens_per_passed_scenario"
        ],
        "quality_pass_rate": observer_telemetry["quality_pass_rate"],
        "engineering_metrics": {
            "schema_version": engineering_metrics_manifest["metric_schema_version"],
            "calculator_version": engineering_metrics_manifest["calculator_version"],
            "algorithm_manifest_sha256": records[0]["engineering_metrics"][
                "algorithm_manifest_sha256"
            ],
            "scenario_count": len(records),
            "scenarios": [
                {
                    "scenario_id": record["scenario_id"],
                    "run_id": record["engineering_metrics"]["run"]["run_id"],
                    "summary_path": f"{record['scenario_id']}/metrics/metric-summary.json",
                    "report_path": f"{record['scenario_id']}/metrics/engineering-metrics.md",
                    "current": record["engineering_metrics"]["current"],
                    "previous": record["engineering_metrics"]["previous"],
                    "recent": record["engineering_metrics"]["recent"],
                }
                for record in records
            ],
            "note": "quality_pass_rate_is_not_first_pass_acceptance_rate",
        },
        "records": record_refs,
        "output_dir": str(output_dir.resolve()),
        "release_gate_passed": source_repository_unchanged and required_ids <= release_eligible_ids,
    }
    write_json(output_dir / "summary.json", summary)
    if release_gate and adapter_type != "codex_cli":
        raise BlindEvalError("E_BLIND_AGENT_FIXTURE", "fixture/mock runner cannot satisfy Behavior Release Gate")
    if release_gate and not summary["release_gate_passed"]:
        raise BlindEvalError("E_BLIND_AGENT_FAILED", "required blind-agent scenarios did not all pass")
    return summary


def write_report(rows: list[dict[str, object]], output: Path) -> None:
    payload = {
        "generated_at": utc_now(),
        "row_count": len(rows),
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".json":
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    metrics_manifest = load_engineering_metrics_manifest()
    lines = [
        "---",
        "type: Benchmark Report",
        "title: Goal Teams Benchmark Report",
        "description: Benchmark 结构校验、行为运行结果与 V2.43 工程指标算法说明。",
        "tags: [goal-teams, benchmark, engineering-metrics, okf]",
        f"timestamp: {json.dumps(payload['generated_at'])}",
        'okf_version: "0.1"',
        'project_version: "V2.43"',
        f"metric_schema_version: {json.dumps(metrics_manifest['metric_schema_version'])}",
        "source_ssot: references/engineering-metrics-manifest.json",
        "---",
        "",
        "# Goal Teams Benchmark Report",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- row_count: {len(rows)}",
        "",
        "| Item | Status | Behavior |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        item = row.get("task", row.get("run", "unknown"))
        lines.append(f"| {item} | {row['status']} | {row.get('behavior_run', 'fresh execution')} |")
    lines.extend(
        [
            "",
            "# V2.43 工程指标算法",
            "",
            "以下算法由 Benchmark 与普通任务完成报告共同使用。结构校验或 `quality_pass_rate` 不会被换算成 FPAR；只有显式指标事件才能产生数值。",
            "",
        ]
    )
    for metric in metrics_manifest["metrics"]:
        lines.extend(
            [
                f"## {metric['metric_id']} — {metric['full_name']} — {metric['chinese_name']}",
                "",
                f"- 公式：{metric['formula']}",
                f"- 分子：{metric['numerator_definition']}",
                f"- 分母：{metric['denominator_definition']}",
                f"- 排除项：{metric['exclusions']}",
                f"- 上一次：{metric['previous_rule']}",
                f"- 近期聚合：{metric['recent_aggregation_rule']}",
                f"- 可用性：{metric['availability_rule']}",
                "",
            ]
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["contract", "blind-agent"], default="contract")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument(
        "--metrics-history",
        action="append",
        default=[],
        help="prior metric-summary.json file or directory; may be repeated",
    )
    parser.add_argument("--output", default="benchmarks/runs/latest-report.md")
    args = parser.parse_args()
    try:
        if args.mode == "contract":
            if args.release_gate:
                raise BlindEvalError(
                    "E_BLIND_AGENT_REQUIRED",
                    "deterministic contract fixtures do not satisfy Behavior Release Gate",
                )
            package_rows = check_tasks()
            contract_rows = execute_behavior_runs()
            if not args.check_only:
                write_report(package_rows + contract_rows, ROOT / args.output)
            print(
                f"Deterministic contract validation passed for {len(package_rows)} packages and "
                f"{len(contract_rows)} fixture scenarios; this does not satisfy Behavior Gate."
            )
            return
        if args.manifest is None or args.output_dir is None:
            raise BlindEvalError(
                "E_BLIND_AGENT_ARGUMENTS",
                "blind-agent mode requires --manifest and a new persistent --output-dir",
            )
        summary = execute_blind_agent_eval(
            args.manifest.resolve(),
            args.output_dir.resolve(),
            release_gate=args.release_gate,
            selected_scenarios=set(args.scenario) or None,
            engineering_metrics_history=load_engineering_metrics_history(args.metrics_history),
        )
        print(json.dumps({"ok": True, "error_code": None, **summary}, ensure_ascii=False, sort_keys=True))
    except BlindEvalError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "schema_version": BLIND_SCHEMA_VERSION,
                    "error_code": exc.code,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
