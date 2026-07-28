#!/usr/bin/env python3
"""Validate V2.47 CodeAgent runtime selection and overlay coverage."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "references" / "codeagent-runtime-manifest.json"
EXPECTED_IDS = [
    "codex",
    "claude-code",
    "cursor",
    "kimi-code",
    "glm",
    "qwen-code",
    "qoder",
    "trae",
]
SOURCE_ID_RE = re.compile(r"^\|\s*([A-Z]+-[0-9]{2})\s*\|", re.MULTILINE)
TRAE_REQUIRED_PROBE_FIELDS = {
    "surface",
    "version",
    "skill_schema_fields",
    "skill_roots",
    "instruction_files",
    "manual_skill_invocation",
    "sandbox_mode",
}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value


def require_exact_keys(
    value: dict[str, Any],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    keys = set(value)
    if missing := sorted(required - keys):
        fail(f"{label} missing fields: {missing}")
    if unknown := sorted(keys - required - optional):
        fail(f"{label} unknown fields: {unknown}")


def select_runtime(
    runtime_ids: list[str],
    model_provider: str | None,
    known_runtime_ids: set[str],
    capability_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = list(dict.fromkeys(runtime_ids))
    unknown = [runtime_id for runtime_id in normalized if runtime_id not in known_runtime_ids]
    if unknown:
        return {"state": "blocked", "reason": "unknown_runtime", "overlay_count": 0}
    if len(normalized) > 1:
        return {
            "state": "blocked",
            "reason": "conflicting_runtime_facts",
            "overlay_count": 0,
        }
    if not normalized:
        return {
            "state": "blocked",
            "reason": (
                "host_runtime_required"
                if model_provider == "glm"
                else "unknown_runtime"
            ),
            "overlay_count": 0,
        }
    runtime_id = normalized[0]
    if runtime_id == "glm":
        return {
            "state": "blocked",
            "reason": "host_runtime_required",
            "overlay_count": 0,
        }
    if runtime_id == "trae":
        complete = isinstance(capability_facts, dict) and (
            set(capability_facts) == TRAE_REQUIRED_PROBE_FIELDS
        )
        if complete:
            for field in ("skill_schema_fields", "skill_roots", "instruction_files"):
                complete = complete and isinstance(capability_facts[field], list) and bool(
                    capability_facts[field]
                )
            for field in (
                "surface",
                "version",
                "manual_skill_invocation",
                "sandbox_mode",
            ):
                complete = complete and isinstance(capability_facts[field], str) and bool(
                    capability_facts[field]
                )
        if not complete:
            return {
                "state": "blocked",
                "reason": "capability_probe_required",
                "overlay_count": 0,
            }
    return {"state": "selected", "runtime_id": runtime_id, "overlay_count": 1}


def validate(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"manifest unreadable: {exc}")

    if manifest.get("schema_version") != "goal-teams-codeagent-runtime-v2.47":
        fail("schema_version mismatch")
    require_exact_keys(
        manifest,
        {
            "schema_version",
            "product_version",
            "schema",
            "validator",
            "common_rules",
            "official_source_index",
            "selection",
            "runtime_denominator",
            "runtimes",
            "p0_selection_fixtures",
        },
        set(),
        "manifest",
    )
    if manifest.get("product_version") != "V2.47":
        fail("product_version mismatch")
    for field in ("schema", "validator", "common_rules", "official_source_index"):
        relative = manifest.get(field)
        if not isinstance(relative, str) or not (ROOT / relative).is_file():
            fail(f"missing declared file for {field}: {relative!r}")

    selection = require_mapping(manifest.get("selection"), "selection")
    require_exact_keys(
        selection,
        {
            "mode",
            "profile_count",
            "unknown_runtime",
            "conflicting_runtime_facts",
            "model_provider_is_not_runtime",
            "load_order",
        },
        set(),
        "selection",
    )
    expected_selection = {
        "mode": "detected_runtime_only",
        "profile_count": 1,
        "unknown_runtime": "blocked",
        "conflicting_runtime_facts": "blocked",
        "model_provider_is_not_runtime": True,
        "load_order": [
            "portable_core",
            "normal_rules",
            "common_rules",
            "one_runtime_overlay",
            "task_dynamic_tail",
        ],
    }
    if selection != expected_selection:
        fail("selection contract drift")

    denominator = manifest.get("runtime_denominator")
    if denominator != EXPECTED_IDS:
        fail("runtime denominator/order drift")

    source_text = (ROOT / manifest["official_source_index"]).read_text(encoding="utf-8")
    indexed_source_ids = set(SOURCE_ID_RE.findall(source_text))
    runtimes = manifest.get("runtimes")
    if not isinstance(runtimes, list) or len(runtimes) != len(EXPECTED_IDS):
        fail("runtime entries must exactly cover denominator")
    by_id: dict[str, dict[str, Any]] = {}
    source_refs: set[str] = set()
    for runtime in runtimes:
        item = require_mapping(runtime, "runtime")
        require_exact_keys(
            item,
            {
                "runtime_id",
                "runtime_kind",
                "adapter_state",
                "detection_facts",
                "skill_roots",
                "instruction_files",
                "manual_invocation",
                "overlay",
                "source_ids",
            },
            set(),
            "runtime",
        )
        runtime_id = item.get("runtime_id")
        if runtime_id in by_id or runtime_id not in EXPECTED_IDS:
            fail(f"duplicate or unknown runtime_id: {runtime_id!r}")
        by_id[runtime_id] = item
        overlay = item.get("overlay")
        if not isinstance(overlay, str) or not (ROOT / overlay).is_file():
            fail(f"{runtime_id} overlay missing: {overlay!r}")
        if not isinstance(item.get("detection_facts"), list) or not item["detection_facts"]:
            fail(f"{runtime_id} detection facts missing")
        source_ids = item.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            fail(f"{runtime_id} source IDs missing")
        missing_sources = set(source_ids) - indexed_source_ids
        if missing_sources:
            fail(f"{runtime_id} source IDs not indexed: {sorted(missing_sources)}")
        source_refs.update(source_ids)

    if list(by_id) != EXPECTED_IDS:
        fail("runtime entries must preserve denominator order")
    glm = by_id["glm"]
    if (
        glm.get("runtime_kind") != "model_provider"
        or glm.get("adapter_state") != "provider_only_requires_host_runtime"
        or glm.get("skill_roots") != []
        or glm.get("instruction_files") != []
    ):
        fail("GLM must remain provider-only and host-bound")
    trae = by_id["trae"]
    if trae.get("adapter_state") != "capability_probe_required":
        fail("TRAE must fail closed pending public schema/runtime probe")
    for runtime_id, item in by_id.items():
        if runtime_id not in {"glm", "trae"} and (
            item.get("runtime_kind") != "agent_runtime"
            or item.get("adapter_state") != "contract_mapped_not_runtime_verified"
        ):
            fail(f"{runtime_id} adapter state overclaims runtime verification")

    fixtures = manifest.get("p0_selection_fixtures")
    if not isinstance(fixtures, list) or len(fixtures) < 5:
        fail("selection fixtures incomplete")
    fixture_ids: set[str] = set()
    executed = 0
    known_hosts = set(EXPECTED_IDS) - {"glm"}
    for fixture in fixtures:
        item = require_mapping(fixture, "fixture")
        require_exact_keys(
            item,
            {"fixture_id", "runtime_ids", "model_provider", "expected"},
            {"capability_facts"},
            "fixture",
        )
        fixture_id = item.get("fixture_id")
        if not isinstance(fixture_id, str) or fixture_id in fixture_ids:
            fail(f"invalid or duplicate fixture_id: {fixture_id!r}")
        fixture_ids.add(fixture_id)
        runtime_ids = item.get("runtime_ids")
        if not isinstance(runtime_ids, list) or not all(
            isinstance(value, str) for value in runtime_ids
        ):
            fail(f"{fixture_id} runtime_ids invalid")
        expected = require_mapping(item.get("expected"), f"{fixture_id}.expected")
        actual = select_runtime(
            runtime_ids,
            item.get("model_provider"),
            known_hosts,
            item.get("capability_facts"),
        )
        if actual != expected:
            fail(f"{fixture_id} failed: {actual!r} != {expected!r}")
        executed += 1

    return {
        "ok": True,
        "runtime_count": len(by_id),
        "official_source_count": len(indexed_source_ids),
        "referenced_source_count": len(source_refs),
        "overlay_count": len({item["overlay"] for item in by_id.values()}),
        "fixture_count": executed,
        "full_adapter_verified_count": 0,
        "full_regression_executed": False,
    }


if __name__ == "__main__":
    selected = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else DEFAULT_MANIFEST
    if len(sys.argv) > 2:
        fail("usage: validate-v247-codeagent-runtime.py [manifest.json]")
    json.dump(validate(selected), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
