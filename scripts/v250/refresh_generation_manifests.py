#!/usr/bin/env python3
"""Refresh the deterministic V2.51 Current projection and activation digests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GENERATION_ROOT = Path("references/current/generations/V2.51")
RULE_PATH = GENERATION_ROOT / "rule-manifest.json"
PROMPT_PATH = GENERATION_ROOT / "prompt-manifest.json"
ACTIVATION_PATH = GENERATION_ROOT / "activation-manifest.json"
ACTIVE_PATH = Path("references/current/ACTIVE.json")
BASELINE_PATH = Path("references/current/generations/V2.48/activation-manifest.json")
REPLAY_PATH = Path("references/legacy-replay/manifest.json")
ACTIVATED_AT = "2026-08-06T12:00:00+08:00"


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load(relative: Path) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {relative.as_posix()}")
    return value


def _entry(relative: str, virtual: dict[str, bytes]) -> dict[str, Any]:
    raw = virtual.get(relative)
    if raw is None:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"unsafe or missing activation member: {relative}")
        raw = path.read_bytes()
    return {"path": relative, "sha256": _sha256(raw), "bytes": len(raw)}


def _refreshed_rule_manifest() -> dict[str, Any]:
    value = _load(RULE_PATH)
    owners = value.get("owners")
    if not isinstance(owners, list):
        raise ValueError("rule manifest owners must be an array")
    for owner in owners:
        if not isinstance(owner, dict) or not isinstance(owner.get("path"), str):
            raise ValueError("invalid rule owner")
        raw = (ROOT / owner["path"]).read_bytes()
        owner["source_sha256"] = _sha256(raw)
    return value


def _refreshed_prompt_manifest() -> dict[str, Any]:
    value = _load(PROMPT_PATH)
    routes = value.get("routes")
    if not isinstance(routes, dict):
        raise ValueError("prompt routes must be an object")
    for route in routes.values():
        if not isinstance(route, dict) or not isinstance(route.get("ordered_refs"), list):
            raise ValueError("invalid prompt route")
        ordered = list(dict.fromkeys(route["ordered_refs"]))
        route["expected_loaded_rule_bytes"] = sum(
            (ROOT / relative).stat().st_size for relative in ordered
        )
    return value


def _ensure_execution_members(value: dict[str, Any]) -> None:
    root_sets = value.get("root_sets")
    if not isinstance(root_sets, dict):
        raise ValueError("activation root_sets must be an object")
    execution = root_sets.get("execution")
    if not isinstance(execution, list):
        raise ValueError("activation execution root must be an array")
    declared = {
        item.get("path") for item in execution if isinstance(item, dict)
    }
    bootstrap = {
        item.get("path")
        for item in root_sets.get("bootstrap", [])
        if isinstance(item, dict)
    }
    dynamic = {
        path.relative_to(ROOT).as_posix()
        for pattern in ("scripts/v250/*.py", "tests/v250/*.py")
        for path in ROOT.glob(pattern)
        if path.is_file() and not path.is_symlink()
    }
    for relative in sorted(dynamic - declared - bootstrap):
        execution.append({"path": relative, "sha256": "", "bytes": 0})
    execution.sort(key=lambda item: str(item.get("path", "")))


def _refreshed_activation(
    rule_manifest: dict[str, Any], prompt_manifest: dict[str, Any]
) -> dict[str, Any]:
    value = _load(ACTIVATION_PATH)
    value["schema_version"] = "goal-teams-activation-manifest-v2.50"
    value["generation_id"] = "V2.51"
    value["generation_state"] = "active"
    value["baseline_generation_id"] = "V2.48"
    value["identity"] = {
        "loaded_runtime_product_version": "V2.51",
        "route_contract_schema_version": "goal-teams-project-route-v2.50",
        "target_policy_generation": "V2.51",
    }
    _ensure_execution_members(value)

    rule_raw = _json_bytes(rule_manifest)
    prompt_raw = _json_bytes(prompt_manifest)
    virtual = {
        RULE_PATH.as_posix(): rule_raw,
        PROMPT_PATH.as_posix(): prompt_raw,
    }
    root_sets = value["root_sets"]
    schema_paths = {
        "schemas/release-engine-profile.schema.json",
        *(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.glob("schemas/v2.50/*.json")
            if path.is_file() and not path.is_symlink()
        ),
    }
    root_sets["schemas_and_validators"] = [
        {"path": relative, "sha256": "", "bytes": 0}
        for relative in sorted(schema_paths)
    ]
    for root_name in ("bootstrap", "current", "execution", "schemas_and_validators"):
        entries = root_sets.get(root_name)
        if not isinstance(entries, list):
            raise ValueError(f"invalid root set: {root_name}")
        root_sets[root_name] = [
            _entry(str(item["path"]), virtual) for item in entries
        ]

    owners = rule_manifest.get("owners", [])
    owner_binding = sorted(
        (
            {"path": owner["path"], "sha256": owner["source_sha256"]}
            for owner in owners
        ),
        key=lambda item: item["path"],
    )
    value["semantic_owner_set_digest"] = _canonical_digest(owner_binding)
    value["rule_index_digest"] = _sha256(rule_raw)
    value["prompt_plan_digest"] = _sha256(prompt_raw)
    schema_entries = sorted(
        root_sets["schemas_and_validators"], key=lambda item: item["path"]
    )
    value["schema_and_validator_digest"] = _canonical_digest(schema_entries)
    contract_entries = sorted(
        (
            item
            for item in root_sets["current"]
            if item["path"].startswith(
                "references/current/generations/V2.51/contracts/"
            )
            and item["path"].endswith(".json")
        ),
        key=lambda item: item["path"],
    )
    value["fixture_and_completion_contract_digest"] = _canonical_digest(
        contract_entries
    )
    writers = ["scripts/v250/refresh_generation_manifests.py"]
    value["projection_writer_allowlist"] = writers
    value["projection_writer_allowlist_digest"] = _canonical_digest(
        sorted(writers)
    )

    replay_raw = (ROOT / REPLAY_PATH).read_bytes()
    replay = _load(REPLAY_PATH)
    legacy = value.get("legacy_classification")
    if not isinstance(legacy, dict):
        raise ValueError("legacy classification must be an object")
    prefixes = set(legacy.get("path_prefixes", []))
    prefixes.discard("references/current/generations/V2.51/")
    prefixes.update(
        {
            "references/current/generations/V2.50/",
            "references/current/generations/V2.49/",
            "schemas/v2.49/",
            "scripts/v249/",
            "tests/v249/",
        }
    )
    exact = set(legacy.get("exact_paths", []))
    exact.discard("references/profiles/goal-teams-self-release-v2.51.md")
    exact.discard("references/release-profiles/v2.51.json")
    exact.update(
        {
            "references/profiles/goal-teams-self-release-v2.50.md",
            "references/release-profiles/v2.50.json",
            "references/profiles/goal-teams-self-release-v2.49.md",
            "references/release-profiles/v2.49.json",
            "scripts/checks/check-v249.py",
            "scripts/checks/run-v249-release-security-review.py",
            "scripts/checks/validate-v249-generation.py",
            "scripts/checks/validate-v249-test-gate.py",
        }
    )
    legacy["path_prefixes"] = sorted(prefixes)
    legacy["exact_paths"] = sorted(exact)
    legacy["replay_manifest_sha256"] = _sha256(replay_raw)
    value["optional_replay_allowlist_digest"] = replay[
        "optional_replay_allowlist_digest"
    ]

    baseline_raw = (ROOT / BASELINE_PATH).read_bytes()
    value["rollback"] = {
        "activation_manifest_path": BASELINE_PATH.as_posix(),
        "activation_manifest_sha256": _sha256(baseline_raw),
        "window_status": "open",
    }
    members = {
        item["path"]
        for entries in root_sets.values()
        for item in entries
    }
    allowlist = sorted(
        members | {ACTIVE_PATH.as_posix(), ACTIVATION_PATH.as_posix()}
    )
    value["current_default_allowlist"] = allowlist
    value["current_default_allowlist_digest"] = _canonical_digest(allowlist)
    payload = dict(value)
    payload.pop("manifest_payload_sha256", None)
    value["manifest_payload_sha256"] = _canonical_digest(payload)
    return value


def _refreshed_active(activation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-active-generation-v1",
        "generation_id": "V2.51",
        "activation_manifest": ACTIVATION_PATH.as_posix(),
        "activation_manifest_sha256": _sha256(_json_bytes(activation)),
        "state": "active_current",
        "updated_at": ACTIVATED_AT,
    }


def _write(relative: Path, value: dict[str, Any]) -> None:
    (ROOT / relative).write_bytes(_json_bytes(value))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    rule = _refreshed_rule_manifest()
    prompt = _refreshed_prompt_manifest()
    activation = _refreshed_activation(rule, prompt)
    active = _refreshed_active(activation)
    expected = {
        RULE_PATH: rule,
        PROMPT_PATH: prompt,
        ACTIVATION_PATH: activation,
        ACTIVE_PATH: active,
    }
    drift = [
        relative.as_posix()
        for relative, value in expected.items()
        if _load(relative) != value
    ]
    if args.check:
        print(json.dumps({"ok": not drift, "drift": drift}, ensure_ascii=False))
        return 0 if not drift else 1
    for relative, value in expected.items():
        _write(relative, value)
    print(
        json.dumps(
            {
                "ok": True,
                "updated": drift,
                "activation_manifest_sha256": active[
                    "activation_manifest_sha256"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
