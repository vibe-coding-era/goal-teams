#!/usr/bin/env python3
"""Validate V2.38 compatibility plus V2.39 cache Evidence contracts."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "scripts" / "v23" / "prompt_cache.py"
COMPILER = ROOT / "scripts" / "v23" / "prompt_compilers.py"
CACHE_PROBE = ROOT / "scripts" / "v23" / "cache_probe.py"
MIN_AGENT_PREFIX_BYTES = 512
MIN_PACKET_TAIL_OFFSET = 0.80


def load_module(name: str, path: Path):
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def main() -> None:
    errors: list[str] = []
    runtime = load_module("_goalteams_prompt_cache_check", RUNTIME)
    compiler = load_module("_goalteams_prompt_compilers_check", COMPILER)
    cache_probe = load_module("_goalteams_cache_probe_check", CACHE_PROBE)
    required_runtime_apis = {
        "build_host_capability_receipt",
        "build_ordered_prompt_identity_v239",
        "load_production_cache_policy",
        "verify_host_attestation",
        "verify_live_authorization",
        "build_cache_status_axes",
        "persist_usage_events",
        "load_raw_usage_receipt",
        "normalize_usage_events",
        "aggregate_normalized_events",
        "open_v238_cache_artifact",
        "replay_v238_cache_record",
    }
    missing_runtime_apis = sorted(
        name for name in required_runtime_apis if not callable(getattr(runtime, name, None))
    )
    if missing_runtime_apis:
        errors.append("E_PROMPT_CACHE_V239_API:" + ",".join(missing_runtime_apis))
    missing_probe_apis = sorted(
        name
        for name in ("build_live_probe_plan", "execute_live_probe")
        if not callable(getattr(cache_probe, name, None))
    )
    if missing_probe_apis:
        errors.append("E_PROMPT_CACHE_V239_PROBE_API:" + ",".join(missing_probe_apis))
    trust_policy_path = ROOT / "references" / "prompt-cache-trust-policy.json"
    try:
        trust_policy_bytes = trust_policy_path.read_bytes()
        trust_policy = json.loads(trust_policy_bytes)
        if (
            not isinstance(trust_policy, dict)
            or trust_policy.get("schema_version")
            != "goal-teams-prompt-cache-trust-policy-v2.39"
            or trust_policy.get("product_version") != "V2.39"
            or trust_policy.get("enabled") is not False
            or trust_policy.get("verifiers") != []
            or trust_policy.get("adapters") != []
            or trust_policy.get("authorization_issuers") != []
        ):
            errors.append("E_PROMPT_CACHE_TRUST_POLICY")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"E_PROMPT_CACHE_TRUST_POLICY:{exc}")
        trust_policy = {}
        trust_policy_bytes = b""
    try:
        v239_plan = cache_probe.build_live_probe_plan(
            {"layout_id": "current", "runtime_prompt_digest": "a" * 64},
            {"layout_id": "candidate", "runtime_prompt_digest": "b" * 64},
            {
                "product_version": "V2.39",
                "model": "structural-check-only",
                "config_sha256": "c" * 64,
                "scorer_sha256": "d" * 64,
                "harness_sha256": "e" * 64,
            },
            {
                "adapter_id": "synthetic-check-only",
                "repeats": 1,
                "budget": {"max_invocations": 0, "max_cost_amount": 0},
            },
        )
        if (
            v239_plan.get("execution_state") != "planned_not_executed"
            or v239_plan.get("live_cache_validation_state") != "not_authorized"
            or {item.get("mutation_scope") for item in v239_plan["invocations"]}
            != {"none", "dynamic_suffix", "stable_prefix"}
        ):
            errors.append("E_PROMPT_CACHE_V239_PLAN")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"E_PROMPT_CACHE_V239_PLAN:{exc}")
        v239_plan = {}
    try:
        manifest = runtime.load_prompt_manifest(ROOT)
    except ValueError as exc:
        print(json.dumps({"passed": False, "errors": [str(exc)]}, ensure_ascii=False))
        raise SystemExit(1) from exc
    route_results: dict[str, object] = {}
    repository_scope = (
        ROOT / ".agents" / "skills" / "goal-teams" / "SKILL.md"
    ).is_file()
    for route_id in manifest["routes"]:
        if not repository_scope and "repository" in route_id:
            continue
        try:
            identity = runtime.build_prompt_identity(ROOT, route_id)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        route_results[route_id] = {
            "bytes": identity["route_bytes"],
            "limit_bytes": identity["limit_bytes"],
            "passed": identity["passed"],
            "prefix_manifest_sha256": identity["prefix_manifest_sha256"],
            "route_static_digest": identity["route_static_digest"],
            "manifest_status": identity["manifest_status"],
            "digest_scope": identity["digest_scope"],
            "runtime_prompt_digest": identity["runtime_prompt_digest"],
            "budget_receipt": identity["budget_receipt"],
        }
        if identity["runtime_prompt_digest"] is not None:
            errors.append(f"E_PROMPT_ROUTE_FALSE_RUNTIME_DIGEST:{route_id}")
        if not identity["passed"]:
            errors.append(f"E_PROMPT_ROUTE_BUDGET:{route_id}")

    try:
        agent_validation = compiler.validate_subagent_prefixes(ROOT)
        expansion = compiler.expand_subagent_prefixes(ROOT)
    except ValueError as exc:
        errors.append(str(exc))
        agent_validation = {
            "target_count": 0,
            "common_prefix_bytes": 0,
            "common_prefix_version": None,
            "common_prefix_sha256": None,
            "errors": [str(exc)],
        }
        expansion = {"changed": ["unavailable"]}
    errors.extend(agent_validation.get("errors", []))
    if expansion["changed"]:
        errors.append("E_SUBAGENT_EXPANSION_DRIFT:" + ",".join(expansion["changed"]))
    common_prefix_bytes = agent_validation["common_prefix_bytes"]
    if agent_validation["target_count"] < 18 or common_prefix_bytes < MIN_AGENT_PREFIX_BYTES:
        errors.append("E_PROMPT_AGENT_PREFIX")

    packet = (ROOT / "prompts" / "packets" / "member-goal-packet.md").read_text(
        encoding="utf-8"
    )
    marker = "<!-- goal-teams-dynamic-tail -->"
    offset = packet.find(marker)
    ratio = offset / len(packet) if offset >= 0 and packet else 0.0
    if offset < 0 or ratio < MIN_PACKET_TAIL_OFFSET or (
        "<" in packet and packet.find("<") < offset
    ):
        errors.append("E_PROMPT_PACKET_DYNAMIC_TAIL")
    packet_fixture = (
        ROOT / "tests" / "v23" / "fixtures" / "v238" / "member-goal-packet-assignment.json"
    )
    try:
        assignment = compiler.load_json_file_strict(packet_fixture)
        if not isinstance(assignment, dict):
            raise ValueError("E_PACKET_JSON_OBJECT_REQUIRED")
        packet_result = compiler.serialize_member_goal_packet(ROOT, assignment)
        combined_bytes = packet_result["packet_text"].encode("utf-8")
        if hashlib.sha256(combined_bytes).hexdigest() != packet_result["combined_packet_sha256"]:
            errors.append("E_PROMPT_PACKET_COMBINED_DIGEST")
        packet_budget = packet_result["dynamic_budget_receipt"]
        if (
            not packet_budget["passed"]
            or packet_budget["actual"]["dynamic_assignment_bytes"]
            != packet_result["dynamic_assignment_bytes"]
        ):
            errors.append("E_PROMPT_PACKET_DYNAMIC_BUDGET_RECEIPT")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"E_PROMPT_PACKET_COMPILE:{exc}")
        packet_result = {
            "stable_prefix_sha256": None,
            "dynamic_assignment_sha256": None,
            "combined_packet_sha256": None,
            "dynamic_budget_receipt": None,
        }

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if "references/prompt-cache-manifest.json" not in skill:
        errors.append("E_PROMPT_SKILL_MANIFEST_ROUTE")

    result = {
        "schema_version": "goal-teams-prompt-cache-check-v2.39",
        "route_count": len(route_results),
        "routes": route_results,
        "agent_count": agent_validation["target_count"],
        "agent_common_prefix_bytes": common_prefix_bytes,
        "common_prefix_version": agent_validation["common_prefix_version"],
        "common_prefix_sha256": agent_validation["common_prefix_sha256"],
        "subagent_expansion_changed": expansion["changed"],
        "packet_dynamic_tail_ratio": ratio,
        "packet_digests": {
            "stable_prefix_sha256": packet_result["stable_prefix_sha256"],
            "dynamic_assignment_sha256": packet_result["dynamic_assignment_sha256"],
            "combined_packet_sha256": packet_result["combined_packet_sha256"],
        },
        "packet_dynamic_budget_receipt": packet_result["dynamic_budget_receipt"],
        "v239_evidence_contract": {
            "runtime_api_count": len(required_runtime_apis) - len(missing_runtime_apis),
            "probe_api_count": 2 - len(missing_probe_apis),
            "trust_policy_sha256": hashlib.sha256(trust_policy_bytes).hexdigest(),
            "production_policy_enabled": trust_policy.get("enabled"),
            "production_verifier_count": len(trust_policy.get("verifiers", [])),
            "production_adapter_count": len(trust_policy.get("adapters", [])),
            "authorization_issuer_count": len(
                trust_policy.get("authorization_issuers", [])
            ),
            "probe_plan_sha256": v239_plan.get("plan_sha256"),
            "live_cache_validation_state": v239_plan.get(
                "live_cache_validation_state"
            ),
        },
        "passed": not errors,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
