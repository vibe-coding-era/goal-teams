#!/usr/bin/env python3
"""V2.39 fail-closed prompt-cache probe planner and production gate.

This module compiles a deterministic current/candidate schedule.  It never
accepts caller callbacks or adapter registries.  Production execution requires
opaque receipts issued by the package-bound policy and authorization gates;
the initial V2.39 policy has no enabled adapter or issuer, so execution remains
``not_authorized`` without touching provider code.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any


PROMPT_CACHE_PATH = Path(__file__).with_name("prompt_cache.py")
PLAN_SCHEMA = "goal-teams-live-cache-probe-plan-v2.39"
RUN_SCHEMA = "goal-teams-live-cache-probe-run-v2.39"


def _load_prompt_cache():
    name = "_goalteams_v239_cache_probe_prompt_cache"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, PROMPT_CACHE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load V2.39 prompt cache runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prompt_cache = _load_prompt_cache()
PromptCacheContractError = prompt_cache.PromptCacheContractError


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _identifier(value: Any, maximum: int = 256) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and not any(ord(character) < 32 for character in value)
    )


def _closed_mapping(value: Any, expected: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise PromptCacheContractError(code)
    return value


def build_live_probe_plan(
    current: dict[str, Any],
    candidate: dict[str, Any],
    controls: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Compile a pre-registered interleaved comparison schedule."""

    layout_fields = {"layout_id", "runtime_prompt_digest"}
    current = _closed_mapping(current, layout_fields, "E_CACHE_PROBE_CURRENT_SCHEMA")
    candidate = _closed_mapping(
        candidate, layout_fields, "E_CACHE_PROBE_CANDIDATE_SCHEMA"
    )
    for layout in (current, candidate):
        if not _identifier(layout.get("layout_id")) or not _is_sha256(
            layout.get("runtime_prompt_digest")
        ):
            raise PromptCacheContractError("E_CACHE_PROBE_LAYOUT")
    if current["layout_id"] == candidate["layout_id"]:
        raise PromptCacheContractError("E_CACHE_PROBE_LAYOUT_DUPLICATE")

    control_fields = {
        "product_version",
        "model",
        "config_sha256",
        "scorer_sha256",
        "harness_sha256",
    }
    controls = _closed_mapping(
        controls, control_fields, "E_CACHE_PROBE_CONTROLS_SCHEMA"
    )
    if (
        controls.get("product_version") != "V2.39"
        or not _identifier(controls.get("model"))
        or not all(
            _is_sha256(controls.get(field))
            for field in ("config_sha256", "scorer_sha256", "harness_sha256")
        )
    ):
        raise PromptCacheContractError("E_CACHE_PROBE_CONTROLS")

    policy = _closed_mapping(
        policy, {"adapter_id", "repeats", "budget"}, "E_CACHE_PROBE_POLICY_SCHEMA"
    )
    budget = policy.get("budget")
    if not isinstance(budget, dict) or set(budget) not in (
        {"max_invocations", "max_cost_amount"},
        {"max_invocations", "max_cost_usd"},
    ):
        raise PromptCacheContractError("E_CACHE_PROBE_BUDGET_SCHEMA")
    repeats = policy.get("repeats")
    max_invocations = budget.get("max_invocations")
    max_cost = budget.get("max_cost_amount", budget.get("max_cost_usd"))
    if (
        not _identifier(policy.get("adapter_id"))
        or not isinstance(repeats, int)
        or isinstance(repeats, bool)
        or repeats < 1
        or not isinstance(max_invocations, int)
        or isinstance(max_invocations, bool)
        or max_invocations < 0
        or not isinstance(max_cost, (int, float))
        or isinstance(max_cost, bool)
        or not math.isfinite(float(max_cost))
        or max_cost < 0
    ):
        raise PromptCacheContractError("E_CACHE_PROBE_POLICY")

    layouts = [copy.deepcopy(current), copy.deepcopy(candidate)]
    invocations: list[dict[str, Any]] = []
    ordinal = 0
    controls_sha = _sha256(_canonical_bytes(controls))
    for mutation_scope in ("none", "dynamic_suffix", "stable_prefix"):
        for repetition_index in range(repeats + 1):
            repetition_state = (
                "first_seen_reference"
                if repetition_index == 0
                else "immediate_repeat"
            )
            for layout in layouts:
                invocations.append(
                    {
                        "invocation_id": f"INV-V239-{ordinal + 1:04d}",
                        "ordinal": ordinal,
                        "layout_id": layout["layout_id"],
                        "runtime_prompt_digest": layout["runtime_prompt_digest"],
                        "mutation_scope": mutation_scope,
                        "repetition_state": repetition_state,
                        "repetition_index": repetition_index,
                        "adapter_id": policy["adapter_id"],
                        "controls_sha256": controls_sha,
                    }
                )
                ordinal += 1
    plan = {
        "schema_version": PLAN_SCHEMA,
        "execution_state": "planned_not_executed",
        "evaluation_class": "unexecuted",
        "adapter_id": policy["adapter_id"],
        "layouts": layouts,
        "controls": copy.deepcopy(controls),
        "controls_sha256": controls_sha,
        "policy": copy.deepcopy(policy),
        "invocations": invocations,
        "invocations_required": len(invocations),
        "budget_sufficient_for_full_plan": max_invocations >= len(invocations),
        "pre_registered_mutation_order": [
            "none",
            "dynamic_suffix",
            "stable_prefix",
        ],
        "request_hit_rate_support_state": "unavailable",
        "live_cache_validation_state": "not_authorized",
    }
    plan["plan_sha256"] = _sha256(_canonical_bytes(plan))
    return plan


def _validated_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA:
        raise PromptCacheContractError("E_CACHE_PROBE_PLAN_SCHEMA")
    claimed = plan.get("plan_sha256")
    unhashed = dict(plan)
    unhashed.pop("plan_sha256", None)
    if not _is_sha256(claimed) or claimed != _sha256(_canonical_bytes(unhashed)):
        raise PromptCacheContractError("E_CACHE_PROBE_PLAN_HASH")
    if (
        not isinstance(plan.get("invocations"), list)
        or not isinstance(plan.get("policy"), dict)
        or not isinstance(plan["policy"].get("budget"), dict)
        or plan.get("adapter_id") != plan["policy"].get("adapter_id")
    ):
        raise PromptCacheContractError("E_CACHE_PROBE_PLAN_SCHEMA")
    return copy.deepcopy(plan)


def _not_authorized(plan: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "schema_version": RUN_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "execution_state": "not_authorized",
        "execution_reason": reason,
        "evaluation_class": "none",
        "invocations_planned": len(plan["invocations"]),
        "invocations_completed": 0,
        "evidence": {"raw_events": []},
        "status_axes": prompt_cache.build_cache_status_axes(
            structural_delivery_state="passed",
            host_integration_state="unavailable",
            live_cache_validation_state="not_authorized",
            request_hit_rate_support_state="unavailable",
        ),
        "recommendation": {
            "recommended": False,
            "scope": "none",
            "reason": reason,
        },
    }


def execute_live_probe(
    plan: dict[str, Any],
    authorization_verification: dict[str, Any],
    production_policy_receipt: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    """Apply production authorization before any adapter or filesystem access."""

    plan = _validated_plan(plan)
    _ = output_root  # deliberately untouched until production gates succeed
    if not isinstance(
        authorization_verification, prompt_cache._VerifiedAuthorizationReceipt
    ) or not isinstance(
        production_policy_receipt, prompt_cache._PackageBoundProductionPolicyReceipt
    ):
        return _not_authorized(plan, "package_bound_authorization_required")
    if authorization_verification.get("status") != "authorized":
        return _not_authorized(plan, "authorization_not_verified")
    if not production_policy_receipt.get("enabled"):
        return _not_authorized(plan, "production_policy_disabled")
    # No built-in production adapter kind ships in V2.39.  Keeping this state
    # closed prevents a data-only policy from becoming an executable callback
    # channel before a later version adds and audits a fixed adapter kind.
    return _not_authorized(plan, "production_adapter_unavailable")


__all__ = [
    "PromptCacheContractError",
    "build_live_probe_plan",
    "execute_live_probe",
]
