#!/usr/bin/env python3
"""Validate the V2.47 flow/P0 strategy without executing product tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "references" / "flow-test-strategy-manifest.json"
ALLOWED_COMPARATORS = {"equals", "sequence_equals"}
FLOW_IDS = {"small", "medium", "large"}
PRODUCT_IDS = {
    "portable_core",
    "documentation",
    "cli",
    "backend",
    "api",
    "ui_original",
    "ui_replica",
    "desktop",
    "flow_routing",
    "ledger_harness_evidence",
    "prompt_cache_incremental_ssot",
    "runtime_compatibility",
    "response_contract",
    "self_release_guard",
}
PRODUCT_ROUTE_CHECKS = {
    "documentation": ["okf", "ssot_projection", "link_integrity"],
    "cli": ["command_contract", "incremental", "p0_smoke"],
    "backend": ["targeted_behavior", "incremental", "p0_smoke"],
    "api": ["typed_contract", "business_assertion", "incremental", "p0_smoke"],
    "ui_original": ["affected_user_path", "dom_visible_state", "p0_smoke"],
    "ui_replica": ["e2e", "pixel_comparison", "p0_smoke"],
    "desktop": ["app_launch", "critical_native_path", "platform_tuple"],
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


def resolve_ref(document: dict[str, Any], ref: str, prefix: str) -> Any:
    if not ref.startswith(prefix + "."):
        fail(f"invalid reference {ref!r}")
    value: Any = document
    for part in ref.split("."):
        if not isinstance(value, dict) or part not in value:
            fail(f"unresolved reference {ref!r}")
        value = value[part]
    return value


def execute_case(
    case: dict[str, Any], flows: dict[str, Any]
) -> dict[str, Any]:
    input_data = case["input"]
    kind = case["processing"].get("kind")
    if kind == "compile_test_strategy":
        flow = input_data["flow_selection"]
        policy = flows[flow]
        if flow == "medium":
            return {
                "required_suites": policy["required_during_work"],
                "clarification": "required",
                "full_regression_state": policy["unconfirmed_state"],
            }
        if flow == "large":
            return {
                "final_full_regression": policy["final_full_regression"],
                "reuse_prior_results": policy[
                    "reuse_prior_incremental_or_smoke_in_full_run"
                ],
                "denominator": "complete_frozen_regression_catalog",
            }
        return {
            "required_suites": policy["required_during_work"],
            "final_full_regression": policy["final_full_regression"],
        }
    if kind == "route_product_surface":
        return {"required_checks": PRODUCT_ROUTE_CHECKS[input_data["surface_id"]]}
    if kind == "select_runtime_profile":
        runtime_id = input_data["runtime_id"]
        if runtime_id == "unknown":
            return {"state": "blocked", "full_adapter_claim": False}
        return {
            "common_rules_loaded": True,
            "special_rules_id": runtime_id,
            "capability_claim": "manifest_bounded",
        }
    if kind == "derive_flow_test_gate":
        return {
            "user_clarification_required": (
                input_data["flow_selection"] == "medium"
                and input_data["phase"] == "final"
            )
        }
    if kind == "apply_scope_change_policy":
        return {
            "required_tasks": list(input_data["current_required_tasks"]),
            "proposal_only": [input_data["discovered_task"]],
        }
    if kind == "compile_incremental_document":
        return {
            "stable_prefix_unchanged": True,
            "single_writable_ssot": True,
            "projection_order": list(input_data["fragments"]),
        }
    if kind == "render_user_update":
        tail_field = (
            "下一轮 LOOP"
            if input_data.get("task_state") == "running"
            else "下一个任务"
        )
        return {
            "fields": ["任务", "成员", "进度", "结果", "Banchmark", tail_field],
            "private_reasoning_exposed": False,
        }
    if kind == "evaluate_authority":
        blocked = input_data.get("external_action") == "publish"
        return {"state": "blocked" if blocked else "allowed", "mutation_count": 0}
    fail(f"{case['case_id']} processing.kind is not executable: {kind!r}")


def validate(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"manifest unreadable: {exc}")

    if manifest.get("schema_version") != "goal-teams-flow-test-strategy-v2.47":
        fail("schema_version mismatch")
    require_exact_keys(
        manifest,
        {
            "schema_version",
            "product_version",
            "schema",
            "validator",
            "test_suites",
            "flow_policies",
            "product_surface_denominator",
            "p0_execution_scope",
            "p0_cases",
        },
        set(),
        "manifest",
    )
    if manifest.get("product_version") != "V2.47":
        fail("product_version mismatch")
    if (
        manifest.get("p0_execution_scope")
        != "deterministic_contract_smoke"
    ):
        fail("p0 execution scope mismatch")
    for relative in (manifest.get("schema"), manifest.get("validator")):
        if not isinstance(relative, str) or not (ROOT / relative).is_file():
            fail(f"missing declared dependency: {relative!r}")

    suites = require_mapping(manifest.get("test_suites"), "test_suites")
    if set(suites) != {"incremental", "p0_smoke", "full_regression"}:
        fail("test suite denominator drift")
    for suite_id, suite in suites.items():
        record = require_mapping(suite, f"test_suites.{suite_id}")
        require_exact_keys(
            record, {"denominator", "prior_result_reuse"}, set(), suite_id
        )
        if not all(isinstance(record[field], str) and record[field] for field in record):
            fail(f"{suite_id} fields must be non-empty strings")
    if suites["full_regression"].get("prior_result_reuse") != "forbidden_for_current_run":
        fail("full regression must reject prior result reuse")

    flows = require_mapping(manifest.get("flow_policies"), "flow_policies")
    if set(flows) != FLOW_IDS:
        fail("flow policy denominator drift")
    expected = {
        "small": ("not_required", False),
        "medium": ("user_choice", True),
        "large": ("required", False),
    }
    for flow_id, (full_state, clarify) in expected.items():
        policy = require_mapping(flows[flow_id], f"flow_policies.{flow_id}")
        require_exact_keys(
            policy,
            {
                "required_during_work",
                "final_full_regression",
                "user_clarification_required",
                "reuse_prior_incremental_or_smoke_in_full_run",
            },
            {"unconfirmed_state"},
            f"flow_policies.{flow_id}",
        )
        if policy.get("required_during_work") != ["incremental", "p0_smoke"]:
            fail(f"{flow_id} must require incremental + p0_smoke")
        if policy.get("final_full_regression") != full_state:
            fail(f"{flow_id} final full regression mismatch")
        if policy.get("user_clarification_required") is not clarify:
            fail(f"{flow_id} clarification gate mismatch")
        if policy.get("reuse_prior_incremental_or_smoke_in_full_run") is not False:
            fail(f"{flow_id} may not reuse prior results in a full run")
    if flows["medium"].get("unconfirmed_state") != "awaiting_user_choice":
        fail("medium unconfirmed full regression must block for user choice")

    denominator = manifest.get("product_surface_denominator")
    if not isinstance(denominator, list) or set(denominator) != PRODUCT_IDS:
        fail("product surface denominator drift")

    cases = manifest.get("p0_cases")
    if not isinstance(cases, list) or not cases:
        fail("p0_cases must be a non-empty array")
    seen_cases: set[str] = set()
    flow_coverage: set[str] = set()
    product_coverage: set[str] = set()
    assertion_count = 0
    for case in cases:
        item = require_mapping(case, "p0_case")
        require_exact_keys(
            item,
            {
                "case_id",
                "scope_kind",
                "scope_id",
                "input",
                "processing",
                "expected_output",
                "assertions",
            },
            set(),
            "p0_case",
        )
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_cases:
            fail(f"duplicate or invalid case_id: {case_id!r}")
        seen_cases.add(case_id)
        for field in ("input", "processing", "expected_output"):
            if not isinstance(item.get(field), dict) or not item[field]:
                fail(f"{case_id} missing non-empty {field}")
        scope_kind = item.get("scope_kind")
        scope_id = item.get("scope_id")
        if scope_kind == "flow":
            if scope_id not in FLOW_IDS:
                fail(f"{case_id} has unknown flow scope")
            flow_coverage.add(scope_id)
        elif scope_kind == "product":
            if scope_id not in PRODUCT_IDS:
                fail(f"{case_id} has unknown product scope")
            product_coverage.add(scope_id)
        else:
            fail(f"{case_id} has unknown scope_kind")
        assertions = item.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            fail(f"{case_id} missing assertions")
        seen_assertions: set[str] = set()
        for assertion in assertions:
            record = require_mapping(assertion, f"{case_id}.assertion")
            require_exact_keys(
                record,
                {"assertion_id", "actual_ref", "comparator", "expected_ref"},
                set(),
                f"{case_id}.assertion",
            )
            assertion_id = record.get("assertion_id")
            if (
                not isinstance(assertion_id, str)
                or not assertion_id
                or assertion_id in seen_assertions
            ):
                fail(f"{case_id} duplicate or invalid assertion_id")
            seen_assertions.add(assertion_id)
            if record.get("comparator") not in ALLOWED_COMPARATORS:
                fail(f"{case_id} comparator is not allowed")
            if not str(record.get("actual_ref", "")).startswith("observed_output."):
                fail(f"{case_id} actual_ref is not observable")
            if not str(record.get("expected_ref", "")).startswith("expected_output."):
                fail(f"{case_id} expected_ref is not bound")
            assertion_count += 1
        observed = execute_case(item, flows)
        envelope = {
            "observed_output": observed,
            "expected_output": item["expected_output"],
        }
        for assertion in assertions:
            actual = resolve_ref(
                envelope, assertion["actual_ref"], "observed_output"
            )
            expected_value = resolve_ref(
                envelope, assertion["expected_ref"], "expected_output"
            )
            comparator = assertion["comparator"]
            passed = (
                actual == expected_value
                if comparator == "equals"
                else isinstance(actual, list)
                and isinstance(expected_value, list)
                and actual == expected_value
            )
            if not passed:
                fail(
                    f"{case_id}/{assertion['assertion_id']} failed: "
                    f"{actual!r} != {expected_value!r}"
                )

    if flow_coverage != FLOW_IDS:
        fail(f"flow P0 coverage incomplete: {sorted(FLOW_IDS - flow_coverage)}")
    if product_coverage != PRODUCT_IDS:
        fail(f"product P0 coverage incomplete: {sorted(PRODUCT_IDS - product_coverage)}")

    return {
        "ok": True,
        "schema_version": manifest["schema_version"],
        "flow_count": len(flow_coverage),
        "product_count": len(product_coverage),
        "case_count": len(cases),
        "assertion_count": assertion_count,
        "evaluated_contract_case_count": len(cases),
        "execution_scope": manifest["p0_execution_scope"],
        "full_regression_executed": False,
    }


if __name__ == "__main__":
    selected = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else DEFAULT_MANIFEST
    if len(sys.argv) > 2:
        fail("usage: validate-v247-flow-test-strategy.py [manifest.json]")
    json.dump(validate(selected), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
