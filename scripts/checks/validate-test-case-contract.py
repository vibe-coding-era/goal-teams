#!/usr/bin/env python3
"""Canonical deterministic validator for Goal Teams V2.35/V2.44 test contracts."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import re
import stat
import sys
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "scripts" / "v23" / "v235_policy.py"
FIXTURE_PATH = ROOT / "tests" / "v23" / "fixtures" / "v235" / "test-cases.json"
V244_FIXTURE_PATH = (
    ROOT / "tests" / "v23" / "fixtures" / "v244" / "test-contracts.json"
)
V244_TEST_CASE_SCHEMA = "goal-teams-test-case-v2.44"
V244_PLAN_SCHEMA = "goal-teams-integration-test-plan-v2.44"
V244_RUN_SCHEMA = "goal-teams-test-run-result-v2.44"
V244_FIXTURE_SCHEMA = "goal-teams-test-contract-fixtures-v2.44"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^V[0-9]+\.[0-9]+$")
_V244_COMPARATORS = frozenset(
    {
        "equals",
        "not_equals",
        "contains",
        "member_of",
        "less_than",
        "less_than_or_equal",
        "greater_than",
        "greater_than_or_equal",
        "json_subset",
        "sequence_equals",
        "sha256_equals",
        "status_code_equals",
        "visible",
        "not_visible",
    }
)
_API_RISKS = frozenset(
    {
        "authorization",
        "idempotency",
        "retry",
        "concurrency",
        "compensation",
        "final_consistency",
    }
)
_E2E_RISKS = frozenset(
    {"session", "permission", "refresh", "double_click", "error_recovery"}
)
_OPTIONAL_E2E_RISKS = frozenset(
    {"validation", "loading_disabled", "back_navigation", "multi_tab"}
)
_UNCOVERED_STATES = frozenset(
    {"uncovered", "blocked", "not_run", "unavailable", "unknown", "flaky"}
)
_DISCOVERY_KINDS = frozenset(
    {"pytest_node", "glob", "manifest", "command", "artifact"}
)
_TEST_DISCOVERY_KINDS = frozenset({"pytest_node", "glob"})
_DISCOVERY_CACHE: dict[tuple[str, str], bool] = {}
_API_RISK_ACTIONS = {
    "authorization": "authorization_probe",
    "idempotency": "repeat_request",
    "retry": "retry_after_transient_failure",
    "concurrency": "concurrent_request_batch",
    "compensation": "inject_partial_failure_and_compensate",
    "final_consistency": "poll_until_consistent",
}
_E2E_RISK_ACTIONS = {
    "session": "expire_session",
    "permission": "permission_probe",
    "refresh": "refresh",
    "double_click": "double_click",
    "error_recovery": "inject_network_error",
}


def _load_policy() -> Any:
    spec = importlib.util.spec_from_file_location("_goalteams_v235_policy_validator", POLICY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("V2.35 policy loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _remove_dotted(value: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    current: Any = value
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def _materialize_invalid(spec: dict[str, Any], fixtures: dict[str, Any]) -> dict[str, Any]:
    base = next(
        item for item in fixtures["valid_cases"] if item["case_id"] == spec["base_case_id"]
    )
    case = copy.deepcopy(base)
    case.update(copy.deepcopy(spec.get("patch", {})))
    for key in spec.get("remove", []):
        case.pop(key, None)
    for dotted in spec.get("remove_paths", []):
        _remove_dotted(case, dotted)
    if "assertion_patch" in spec:
        case["assertions"][0].update(copy.deepcopy(spec["assertion_patch"]))
    if "replace_assertions" in spec:
        case["assertions"] = copy.deepcopy(spec["replace_assertions"])
    return case


def _read_strict(policy: Any, path: Path) -> Any:
    return policy.strict_json_loads(path.read_text(encoding="utf-8"))


def _reject(code: str, **data: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": code,
        "errors": [code],
        "mutation_count": 0,
        **data,
    }


def _ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, "error_code": None, "mutation_count": 0, **data}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_text(item) for item in value)
        and len(value) == len(set(value))
    )


def _exact_keys(
    value: Any, required: set[str], optional: set[str] | None = None
) -> bool:
    return isinstance(value, dict) and set(value) == required | (optional or set())


def _required_optional_keys(
    value: Any, required: set[str], optional: set[str] | None = None
) -> bool:
    if not isinstance(value, dict):
        return False
    allowed = required | (optional or set())
    return required <= set(value) and set(value) <= allowed


def _artifact_ref(value: Any) -> bool:
    if not _exact_keys(value, {"path", "sha256", "discovery"}):
        return False
    path = value.get("path")
    if not _text(path) or path.startswith("/") or "\\" in path:
        return False
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False
    if not isinstance(value.get("sha256"), str) or not _HEX64.fullmatch(
        value["sha256"]
    ):
        return False
    discovery = value.get("discovery")
    return (
        _exact_keys(discovery, {"kind", "selector"})
        and discovery["kind"] in _DISCOVERY_KINDS
        and _text(discovery["selector"])
    )


def _artifact_refs(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_artifact_ref(item) for item in value)
    )


def _bound_regular_file(value: Any) -> Path | None:
    if not _artifact_ref(value):
        return None
    candidate = ROOT
    for part in PurePosixPath(value["path"]).parts:
        candidate = candidate / part
        try:
            mode = candidate.lstat().st_mode
        except (FileNotFoundError, OSError):
            return None
        if stat.S_ISLNK(mode):
            return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(ROOT)
    except (FileNotFoundError, RuntimeError, ValueError):
        return None
    if not stat.S_ISREG(resolved.lstat().st_mode):
        return None
    try:
        observed_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        return None
    return resolved if observed_sha256 == value["sha256"] else None


def _bound_artifact_refs(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        _artifact_refs(value, allow_empty=allow_empty)
        and all(_bound_regular_file(item) is not None for item in value)
    )


def _pytest_collect(selector: str, expected_path: str) -> bool:
    """Validate pytest-style nodes without requiring a host pytest install.

    Goal Teams is distributed as a dependency-free Skill. Discovery therefore
    parses the bound Python source and proves that the selected test function,
    class, or class method exists. Dynamic/plugin-generated nodes fail closed.
    """

    cache_key = (selector, expected_path)
    if cache_key in _DISCOVERY_CACHE:
        return _DISCOVERY_CACHE[cache_key]

    parts = selector.split("::")
    if not parts or parts[0] != expected_path or any(not part for part in parts):
        _DISCOVERY_CACHE[cache_key] = False
        return False
    target = ROOT / expected_path
    try:
        target.resolve(strict=True).relative_to(ROOT)
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=expected_path)
    except (FileNotFoundError, OSError, SyntaxError, UnicodeError, ValueError):
        _DISCOVERY_CACHE[cache_key] = False
        return False

    def definitions(body: list[ast.stmt]) -> dict[str, ast.AST]:
        return {
            item.name: item
            for item in body
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def is_test_node(node: ast.AST) -> bool:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name.startswith("test_")
        if isinstance(node, ast.ClassDef):
            return any(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name.startswith("test_")
                for item in node.body
            )
        return False

    selected: ast.AST | None = None
    body = tree.body
    for raw_name in parts[1:]:
        name = raw_name.split("[", 1)[0]
        selected = definitions(body).get(name)
        if selected is None:
            _DISCOVERY_CACHE[cache_key] = False
            return False
        body = selected.body if isinstance(selected, ast.ClassDef) else []

    if selected is None:
        passed = any(is_test_node(node) for node in definitions(tree.body).values())
    else:
        passed = is_test_node(selected)
    _DISCOVERY_CACHE[cache_key] = passed
    return passed


def _bound_test_file_refs(value: Any) -> tuple[bool, str | None]:
    if not _artifact_refs(value):
        return False, "E_V244_ARTIFACT_REF"
    for item in value:
        if _bound_regular_file(item) is None:
            return False, "E_V244_ARTIFACT_REF"
        discovery = item["discovery"]
        kind = discovery["kind"]
        selector = discovery["selector"]
        if kind not in _TEST_DISCOVERY_KINDS:
            return False, "E_V244_TEST_DISCOVERY"
        if kind == "pytest_node":
            if not (
                selector == item["path"]
                or selector.startswith(item["path"] + "::")
            ) or not _pytest_collect(selector, item["path"]):
                return False, "E_V244_TEST_DISCOVERY"
        else:
            try:
                matches = {
                    path.resolve()
                    for path in ROOT.glob(selector)
                    if path.is_file()
                }
            except (OSError, ValueError):
                return False, "E_V244_TEST_DISCOVERY"
            target = (ROOT / item["path"]).resolve()
            if target not in matches or not _pytest_collect(item["path"], item["path"]):
                return False, "E_V244_TEST_DISCOVERY"
    return True, None


def _strict_json_file(path: Path) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


def _load_bound_case_artifacts(
    refs: Any, expected_kind: str
) -> dict[str, dict[str, Any]] | None:
    if not _bound_artifact_refs(refs):
        return None
    cases: dict[str, dict[str, Any]] = {}
    for ref in refs:
        path = _bound_regular_file(ref)
        if path is None:
            return None
        try:
            document = _strict_json_file(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return None
        documents = document if isinstance(document, list) else [document]
        for case in documents:
            validated = validate_v244_test_case(case)
            case_id = case.get("case_id") if isinstance(case, dict) else None
            if (
                not validated.get("ok")
                or case.get("test_kind") != expected_kind
                or not _text(case_id)
                or case_id in cases
            ):
                return None
            cases[case_id] = case
    return cases


def _command(value: Any) -> bool:
    return (
        _exact_keys(value, {"argv", "cwd"})
        and _strings(value.get("argv"))
        and _text(value.get("cwd"))
    )


def _assertions(value: Any) -> tuple[bool, set[str]]:
    if not isinstance(value, list) or len(value) < 2:
        return False, set()
    assertion_ids: set[str] = set()
    comparators: list[str] = []
    for assertion in value:
        if not _required_optional_keys(
            assertion,
            {"assertion_id", "actual_ref", "comparator"},
            {"expected_ref", "expected_value"},
        ):
            return False, set()
        assertion_id = assertion.get("assertion_id")
        comparator = assertion.get("comparator")
        actual_ref = assertion.get("actual_ref")
        if (
            not _text(assertion_id)
            or assertion_id in assertion_ids
            or comparator not in _V244_COMPARATORS
            or not _text(actual_ref)
            or not actual_ref.startswith(("observed_output.", "execution.", "artifact."))
            or (("expected_ref" in assertion) == ("expected_value" in assertion))
            or (
                "expected_ref" in assertion
                and (
                    not _text(assertion["expected_ref"])
                    or not assertion["expected_ref"].startswith("expected.")
                )
            )
        ):
            return False, set()
        assertion_ids.add(assertion_id)
        comparators.append(comparator)
    if all(item == "status_code_equals" for item in comparators):
        return False, set()
    return True, assertion_ids


def _risk_coverage(
    value: Any,
    required_risks: frozenset[str],
    assertion_ids: set[str],
    scenario_actions: dict[str, str],
) -> bool:
    if not isinstance(value, dict) or set(value) != required_risks:
        return False
    expected_actions = (
        _API_RISK_ACTIONS if required_risks == _API_RISKS else _E2E_RISK_ACTIONS
    )
    used_scenarios: set[str] = set()
    used_oracles: set[str] = set()
    for risk_name, control in value.items():
        if not isinstance(control, dict):
            return False
        status = control.get("status")
        if status == "covered":
            scenario_ref = control.get("scenario_ref")
            oracle_ref = control.get("oracle_assertion_ref")
            if (
                not _exact_keys(
                    control,
                    {"status", "scenario_ref", "oracle_assertion_ref"},
                )
                or not _text(scenario_ref)
                or scenario_ref in used_scenarios
                or scenario_actions.get(scenario_ref) != expected_actions[risk_name]
                or not _text(oracle_ref)
                or oracle_ref not in assertion_ids
                or oracle_ref in used_oracles
            ):
                return False
            used_scenarios.add(scenario_ref)
            used_oracles.add(oracle_ref)
        elif status == "not_applicable":
            if not _exact_keys(control, {"status", "rationale"}) or not _text(
                control.get("rationale")
            ):
                return False
        else:
            return False
    return True


def _plan_risk_coverage(value: Any) -> tuple[bool, dict[str, int | float]]:
    empty_summary: dict[str, int | float] = {}
    if not _exact_keys(value, {"risks", "summary"}):
        return False, empty_summary
    risks = value.get("risks")
    if not isinstance(risks, list) or len(risks) < len(_API_RISKS | _E2E_RISKS):
        return False, empty_summary
    risk_ids: set[str] = set()
    categories: dict[str, set[str]] = {"api": set(), "e2e": set()}
    applicable = 0
    covered = 0
    not_applicable = 0
    for risk in risks:
        if not _required_optional_keys(
            risk,
            {
                "risk_id",
                "domain",
                "category",
                "source_ref",
                "severity",
                "applicability",
                "case_refs",
                "coverage_state",
            },
            {"not_applicable_reason", "review_acceptance_ref"},
        ):
            return False, empty_summary
        risk_id = risk.get("risk_id")
        domain = risk.get("domain")
        category = risk.get("category")
        if (
            not _text(risk_id)
            or risk_id in risk_ids
            or domain not in {"api", "e2e"}
            or (
                domain == "api"
                and category not in _API_RISKS
            )
            or (
                domain == "e2e"
                and category not in (_E2E_RISKS | _OPTIONAL_E2E_RISKS)
            )
            or not _text(risk.get("source_ref"))
            or risk.get("severity") not in {"critical", "high", "medium", "low"}
            or risk.get("applicability") not in {"applicable", "not_applicable"}
            or not _strings(risk.get("case_refs"), allow_empty=True)
        ):
            return False, empty_summary
        risk_ids.add(risk_id)
        categories[domain].add(category)
        if risk["applicability"] == "applicable":
            applicable += 1
            if (
                not risk["case_refs"]
                or risk.get("coverage_state")
                not in ({"covered"} | _UNCOVERED_STATES)
                or "not_applicable_reason" in risk
                or "review_acceptance_ref" in risk
            ):
                return False, empty_summary
            if risk["coverage_state"] == "covered":
                covered += 1
        else:
            not_applicable += 1
            if (
                risk["case_refs"]
                or risk.get("coverage_state") != "not_applicable"
                or not _text(risk.get("not_applicable_reason"))
                or not _text(risk.get("review_acceptance_ref"))
            ):
                return False, empty_summary
    if not _API_RISKS <= categories["api"] or not _E2E_RISKS <= categories["e2e"]:
        return False, empty_summary
    calculated: dict[str, int | float] = {
        "total": len(risks),
        "applicable": applicable,
        "covered": covered,
        "uncovered": applicable - covered,
        "not_applicable": not_applicable,
        "coverage_rate": covered / applicable if applicable else 1,
    }
    summary = value.get("summary")
    if (
        not _exact_keys(
            summary,
            {
                "total",
                "applicable",
                "covered",
                "uncovered",
                "not_applicable",
                "coverage_rate",
            },
        )
        or any(
            summary.get(field) != calculated[field]
            for field in (
                "total",
                "applicable",
                "covered",
                "uncovered",
                "not_applicable",
            )
        )
        or not isinstance(summary.get("coverage_rate"), (int, float))
        or isinstance(summary.get("coverage_rate"), bool)
        or abs(float(summary["coverage_rate"]) - float(calculated["coverage_rate"]))
        > 1e-12
    ):
        return False, empty_summary
    return True, calculated


def validate_v244_test_case(case: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "case_id",
        "test_kind",
        "acceptance_refs",
        "test_file_refs",
        "setup",
        "assertions",
        "cleanup",
    }
    if not _required_optional_keys(case, required, {"api", "e2e"}):
        return _reject("E_V244_TEST_CASE_SHAPE")
    if (
        case.get("schema_version") != V244_TEST_CASE_SCHEMA
        or not _text(case.get("case_id"))
        or case.get("test_kind") not in {"api", "e2e"}
        or not _strings(case.get("acceptance_refs"))
    ):
        return _reject("E_V244_TEST_CASE_REQUIRED")
    test_refs_ok, test_ref_error = _bound_test_file_refs(case.get("test_file_refs"))
    if not test_refs_ok:
        return _reject(test_ref_error or "E_V244_ARTIFACT_REF")
    setup = case.get("setup")
    if (
        not _exact_keys(setup, {"preconditions", "data_refs"})
        or not _strings(setup.get("preconditions"))
        or not _artifact_refs(setup.get("data_refs"))
    ):
        return _reject("E_V244_SETUP")
    assertions_ok, assertion_ids = _assertions(case.get("assertions"))
    if not assertions_ok:
        return _reject("E_V244_ASSERTION")
    cleanup = case.get("cleanup")
    if (
        not _exact_keys(
            cleanup, {"required", "steps", "verification_assertion_refs"}
        )
        or cleanup.get("required") is not True
        or not _strings(cleanup.get("steps"))
        or not _strings(cleanup.get("verification_assertion_refs"))
        or not set(cleanup["verification_assertion_refs"]) <= assertion_ids
    ):
        return _reject("E_V244_CLEANUP")

    kind = case["test_kind"]
    if kind == "api":
        if "e2e" in case or "api" not in case:
            return _reject("E_V244_TEST_KIND_BINDING")
        api = case["api"]
        if not _exact_keys(
            api,
            {
                "method",
                "path",
                "auth",
                "request",
                "pre_state",
                "processing",
                "expected",
                "risk_coverage",
            },
        ):
            return _reject("E_V244_API_SHAPE")
        auth = api.get("auth")
        if not _required_optional_keys(
            auth, {"mode", "persona"}, {"credential_ref"}
        ) or auth.get("mode") not in {
            "none",
            "bearer",
            "basic",
            "api_key",
            "cookie",
            "mTLS",
        }:
            return _reject("E_V244_API_AUTH")
        if (
            not _text(auth.get("persona"))
            or (auth["mode"] == "none" and "credential_ref" in auth)
            or (
                auth["mode"] != "none"
                and (
                    "credential_ref" not in auth
                    or not _text(auth.get("credential_ref"))
                )
            )
        ):
            return _reject("E_V244_API_AUTH")
        request = api.get("request")
        pre_state = api.get("pre_state")
        processing = api.get("processing")
        expected = api.get("expected")
        if (
            api.get("method")
            not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            or not _text(api.get("path"))
            or not api["path"].startswith("/")
            or not _exact_keys(
                request, {"headers", "path_params", "query", "body"}
            )
            or not all(
                isinstance(request.get(key), dict)
                for key in ("headers", "path_params", "query")
            )
            or not _exact_keys(pre_state, {"state_refs", "values"})
            or not _strings(pre_state.get("state_refs"))
            or not isinstance(pre_state.get("values"), dict)
            or not pre_state["values"]
            or not _exact_keys(
                processing, {"target", "consumed_input_refs", "risk_scenarios"}
            )
            or not _text(processing.get("target"))
            or not _strings(processing.get("consumed_input_refs"))
            or not _exact_keys(
                expected,
                {"status", "headers", "body", "post_state", "side_effects"},
            )
            or not isinstance(expected.get("status"), int)
            or isinstance(expected.get("status"), bool)
            or not 100 <= expected["status"] <= 599
            or not isinstance(expected.get("headers"), dict)
            or not isinstance(expected.get("post_state"), dict)
            or not expected["post_state"]
            or not _strings(expected.get("side_effects"))
        ):
            return _reject("E_V244_API_ORACLE")
        risk_scenarios = processing.get("risk_scenarios")
        scenario_actions: dict[str, str] = {}
        if not isinstance(risk_scenarios, list):
            return _reject("E_V244_API_RISK_SCENARIO")
        for scenario in risk_scenarios:
            if (
                not _exact_keys(
                    scenario, {"scenario_id", "action", "target", "input_refs"}
                )
                or not _text(scenario.get("scenario_id"))
                or scenario["scenario_id"] in scenario_actions
                or scenario.get("action") not in set(_API_RISK_ACTIONS.values())
                or not _text(scenario.get("target"))
                or not _strings(scenario.get("input_refs"))
            ):
                return _reject("E_V244_API_RISK_SCENARIO")
            scenario_actions[scenario["scenario_id"]] = scenario["action"]
        if set(scenario_actions.values()) != set(_API_RISK_ACTIONS.values()):
            return _reject("E_V244_API_RISK_SCENARIO")
        api_risks = api.get("risk_coverage")
        if not isinstance(api_risks, dict) or set(api_risks) != _API_RISKS:
            return _reject("E_V244_API_RISK_COVERAGE")
        if not _risk_coverage(
            api_risks, _API_RISKS, assertion_ids, scenario_actions
        ):
            return _reject("E_V244_API_RISK_SCENARIO")
    else:
        if "api" in case or "e2e" not in case:
            return _reject("E_V244_TEST_KIND_BINDING")
        e2e = case["e2e"]
        if not _exact_keys(
            e2e,
            {
                "persona",
                "session",
                "initial_state",
                "browser",
                "actions",
                "checkpoints",
                "final_state",
                "risk_coverage",
            },
        ):
            return _reject("E_V244_E2E_SHAPE")
        persona = e2e.get("persona")
        session = e2e.get("session")
        initial = e2e.get("initial_state")
        browser = e2e.get("browser")
        if (
            not _exact_keys(persona, {"role", "permissions"})
            or not _text(persona.get("role"))
            or not _strings(persona.get("permissions"))
            or not _exact_keys(session, {"state", "auth_ref", "refresh_policy"})
            or session.get("state")
            not in {"anonymous", "authenticated", "expired"}
            or not _text(session.get("auth_ref"))
            or not _text(session.get("refresh_policy"))
            or not _exact_keys(initial, {"route", "pre_state", "data_refs"})
            or not _text(initial.get("route"))
            or not isinstance(initial.get("pre_state"), dict)
            or not initial["pre_state"]
            or not _artifact_refs(initial.get("data_refs"))
            or not _exact_keys(browser, {"name", "version", "viewport"})
            or not _text(browser.get("name"))
            or not _text(browser.get("version"))
            or not _exact_keys(browser.get("viewport"), {"width", "height"})
            or any(
                not isinstance(browser["viewport"].get(axis), int)
                or isinstance(browser["viewport"].get(axis), bool)
                or browser["viewport"][axis] < 1
                for axis in ("width", "height")
            )
        ):
            return _reject("E_V244_E2E_INITIAL_STATE")
        actions = e2e.get("actions")
        if not isinstance(actions, list) or not actions:
            return _reject("E_V244_E2E_ACTION")
        step_ids: set[str] = set()
        scenario_actions: dict[str, str] = {}
        for action in actions:
            if not _required_optional_keys(
                action, {"step_id", "type", "target"}, {"value_ref"}
            ):
                return _reject("E_V244_E2E_ACTION")
            if (
                not _text(action.get("step_id"))
                or action["step_id"] in step_ids
                or action.get("type")
                not in {
                    "goto",
                    "click",
                    "double_click",
                    "fill",
                    "select",
                    "submit",
                    "refresh",
                    "wait",
                    "expire_session",
                    "permission_probe",
                    "inject_network_error",
                }
                or not _text(action.get("target"))
                or ("value_ref" in action and not _text(action.get("value_ref")))
            ):
                return _reject("E_V244_E2E_ACTION")
            step_ids.add(action["step_id"])
            scenario_actions[action["step_id"]] = action["type"]
        checkpoints = e2e.get("checkpoints")
        if not isinstance(checkpoints, list) or not checkpoints:
            return _reject("E_V244_E2E_CHECKPOINT")
        checkpoint_ids: set[str] = set()
        for checkpoint in checkpoints:
            if (
                not _exact_keys(
                    checkpoint,
                    {"checkpoint_id", "after_step_ref", "assertion_refs"},
                )
                or not _text(checkpoint.get("checkpoint_id"))
                or checkpoint["checkpoint_id"] in checkpoint_ids
                or checkpoint.get("after_step_ref") not in step_ids
                or not _strings(checkpoint.get("assertion_refs"))
                or not set(checkpoint["assertion_refs"]) <= assertion_ids
            ):
                return _reject("E_V244_E2E_CHECKPOINT")
            checkpoint_ids.add(checkpoint["checkpoint_id"])
        final_state = e2e.get("final_state")
        if (
            not _exact_keys(
                final_state,
                {"url", "dom", "visible", "interaction", "business", "side_effects"},
            )
            or not _text(final_state.get("url"))
            or any(
                not isinstance(final_state.get(field), dict)
                or not final_state[field]
                for field in ("dom", "visible", "interaction", "business")
            )
            or not _strings(final_state.get("side_effects"))
        ):
            return _reject("E_V244_E2E_FINAL_STATE")
        risks = e2e.get("risk_coverage")
        if not isinstance(risks, dict) or set(risks) != _E2E_RISKS:
            return _reject("E_V244_E2E_RISK_COVERAGE")
        if not _risk_coverage(
            risks, _E2E_RISKS, assertion_ids, scenario_actions
        ):
            return _reject("E_V244_E2E_RISK_SCENARIO")
    return _ok(
        contract_kind="test_case",
        case_id=case["case_id"],
        test_kind=kind,
        assertion_ids=sorted(assertion_ids),
    )


def validate_v244_plan(plan: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "plan_id",
        "revision",
        "project_version",
        "owner_identity",
        "validator_identity",
        "acceptance_refs",
        "scope",
        "environments",
        "data_strategy",
        "risk_coverage",
        "api_case_refs",
        "e2e_case_refs",
        "execution",
        "entry_criteria",
        "exit_criteria",
        "evidence_refs",
    }
    if not _exact_keys(plan, required):
        return _reject("E_V244_PLAN_SHAPE")
    if (
        plan.get("schema_version") != V244_PLAN_SCHEMA
        or not _text(plan.get("plan_id"))
        or not isinstance(plan.get("revision"), int)
        or isinstance(plan.get("revision"), bool)
        or plan["revision"] < 1
        or not isinstance(plan.get("project_version"), str)
        or not _VERSION.fullmatch(plan["project_version"])
        or plan["project_version"] != "V2.44"
        or not _strings(plan.get("acceptance_refs"))
    ):
        return _reject("E_V244_PLAN_REQUIRED")
    owner = plan.get("owner_identity")
    validator = plan.get("validator_identity")
    if (
        not _exact_keys(owner, {"agent_type", "member_id", "run_id"})
        or owner.get("agent_type") != "goal_api_integration_test_designer"
        or not _text(owner.get("member_id"))
        or not _text(owner.get("run_id"))
        or not _exact_keys(validator, {"agent_type", "member_id", "run_id"})
        or validator.get("agent_type") not in {"goal_qa", "goal_reviewer"}
        or not _text(validator.get("member_id"))
        or not _text(validator.get("run_id"))
        or owner["member_id"] == validator["member_id"]
        or owner["run_id"] == validator["run_id"]
    ):
        return _reject("E_V244_PLAN_IDENTITY")
    scope = plan.get("scope")
    if (
        not _exact_keys(scope, {"services", "user_journeys", "excluded_with_reason"})
        or not _strings(scope.get("services"))
        or not _strings(scope.get("user_journeys"))
        or not isinstance(scope.get("excluded_with_reason"), list)
        or any(
            not _exact_keys(item, {"scope", "reason"})
            or not _text(item.get("scope"))
            or not _text(item.get("reason"))
            for item in scope["excluded_with_reason"]
        )
    ):
        return _reject("E_V244_PLAN_SCOPE")
    environments = plan.get("environments")
    if not isinstance(environments, list) or not environments:
        return _reject("E_V244_PLAN_ENVIRONMENT")
    environment_ids: set[str] = set()
    for environment in environments:
        if (
            not _exact_keys(
                environment,
                {"environment_id", "base_url", "config_refs", "health_checks"},
            )
            or not _text(environment.get("environment_id"))
            or environment["environment_id"] in environment_ids
            or not _text(environment.get("base_url"))
            or not environment["base_url"].startswith(("http://", "https://"))
            or not _bound_artifact_refs(environment.get("config_refs"))
            or not _strings(environment.get("health_checks"))
        ):
            return _reject("E_V244_PLAN_ENVIRONMENT")
        environment_ids.add(environment["environment_id"])
    data = plan.get("data_strategy")
    if (
        not _exact_keys(data, {"seed_refs", "isolation", "reset", "sensitive_data"})
        or not _bound_artifact_refs(data.get("seed_refs"))
        or not _text(data.get("isolation"))
        or not _text(data.get("reset"))
        or data.get("sensitive_data") not in {"synthetic_only", "redacted_fixture"}
    ):
        return _reject("E_V244_PLAN_DATA")
    risks = plan.get("risk_coverage")
    risks_ok, risk_summary = _plan_risk_coverage(risks)
    if not risks_ok:
        return _reject("E_V244_PLAN_RISK_COVERAGE")
    if (
        not _bound_artifact_refs(plan.get("api_case_refs"))
        or not _bound_artifact_refs(plan.get("e2e_case_refs"))
        or not _bound_artifact_refs(plan.get("evidence_refs"))
    ):
        return _reject("E_V244_ARTIFACT_INTEGRITY")
    api_cases = _load_bound_case_artifacts(plan["api_case_refs"], "api")
    e2e_cases = _load_bound_case_artifacts(plan["e2e_case_refs"], "e2e")
    if not api_cases or not e2e_cases:
        return _reject("E_V244_PLAN_CASE_BINDING")
    all_cases = {**api_cases, **e2e_cases}
    if len(all_cases) != len(api_cases) + len(e2e_cases):
        return _reject("E_V244_PLAN_CASE_BINDING")
    for risk in risks["risks"]:
        if risk["applicability"] != "applicable":
            continue
        for case_id in risk["case_refs"]:
            case = all_cases.get(case_id)
            if case is None or case.get("test_kind") != risk["domain"]:
                return _reject("E_V244_PLAN_CASE_BINDING")
            controls = case[risk["domain"]]["risk_coverage"]
            control = controls.get(risk["category"])
            if control is None or control.get("status") != "covered":
                return _reject("E_V244_PLAN_CASE_BINDING")
    execution = plan.get("execution")
    if (
        not _exact_keys(
            execution,
            {
                "api_command",
                "e2e_command",
                "ordering",
                "parallelism",
                "timeout_seconds",
            },
        )
        or not _command(execution.get("api_command"))
        or not _command(execution.get("e2e_command"))
        or execution.get("ordering") not in {"api_before_e2e", "independent"}
        or not isinstance(execution.get("parallelism"), int)
        or isinstance(execution.get("parallelism"), bool)
        or execution["parallelism"] < 1
        or not isinstance(execution.get("timeout_seconds"), int)
        or isinstance(execution.get("timeout_seconds"), bool)
        or execution["timeout_seconds"] < 1
    ):
        return _reject("E_V244_PLAN_EXECUTION")
    if not _strings(plan.get("entry_criteria")):
        return _reject("E_V244_PLAN_ENTRY")
    if plan.get("exit_criteria") != {
        "required_pass_rate": 1,
        "max_failed": 0,
        "max_flaky": 0,
        "cleanup_required": True,
        "replay_required": True,
    }:
        return _reject("E_V244_PLAN_EXIT")
    return _ok(
        contract_kind="integration_test_plan",
        plan_id=plan["plan_id"],
        revision=plan["revision"],
        environment_ids=sorted(environment_ids),
        risk_summary=risk_summary,
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _json_subset(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _json_subset(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_json_subset(item, expected_item) for item in actual)
            for expected_item in expected
        )
    return actual == expected


def _evaluate_comparator(comparator: str, actual: Any, expected: Any) -> bool:
    try:
        if comparator == "equals":
            return actual == expected
        if comparator == "not_equals":
            return actual != expected
        if comparator == "contains":
            return expected in actual
        if comparator == "member_of":
            return actual in expected
        if comparator == "less_than":
            return actual < expected
        if comparator == "less_than_or_equal":
            return actual <= expected
        if comparator == "greater_than":
            return actual > expected
        if comparator == "greater_than_or_equal":
            return actual >= expected
        if comparator == "json_subset":
            return _json_subset(actual, expected)
        if comparator == "sequence_equals":
            return (
                isinstance(actual, list)
                and isinstance(expected, list)
                and actual == expected
            )
        if comparator == "sha256_equals":
            return (
                isinstance(actual, str)
                and isinstance(expected, str)
                and _HEX64.fullmatch(actual) is not None
                and actual == expected
            )
        if comparator == "status_code_equals":
            return (
                isinstance(actual, int)
                and not isinstance(actual, bool)
                and isinstance(expected, int)
                and not isinstance(expected, bool)
                and actual == expected
            )
        if comparator == "visible":
            return actual is True and expected is True
        if comparator == "not_visible":
            return actual is False and expected is False
    except (TypeError, ValueError):
        return False
    return False


def _all_run_artifact_refs(result: dict[str, Any]) -> list[dict[str, Any]] | None:
    refs: list[dict[str, Any]] = []
    try:
        refs.extend(
            [
                result["source_binding"]["protected_snapshot_ref"],
                result["runner_identity"]["host_attestation_ref"],
                result["plan_binding"]["artifact_ref"],
            ]
        )
        refs.extend(result["test_case_refs"])
        refs.extend(result["environment"]["config_refs"])
        refs.extend(result["data_refs"])
        refs.extend(result["artifacts"])
        for attempt in result["attempts"]:
            refs.extend(attempt["artifact_refs"])
        for failure in result["failures"]:
            refs.extend(failure["evidence_refs"])
        refs.extend(result["cleanup"]["evidence_refs"])
        refs.extend(result["replay"]["environment_refs"])
        refs.extend(result["replay"]["seed_refs"])
        refs.extend(result["replay"]["evidence_refs"])
    except (KeyError, TypeError):
        return None
    return refs


def validate_v244_run_result(result: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "run_id",
        "run_kind",
        "outcome",
        "source_binding",
        "runner_identity",
        "plan_binding",
        "test_case_refs",
        "case_ids",
        "command",
        "environment",
        "data_refs",
        "started_at",
        "ended_at",
        "duration_ms",
        "exit_code",
        "summary",
        "attempts",
        "failures",
        "artifacts",
        "retry",
        "flake",
        "cleanup",
        "replay",
    }
    if not _exact_keys(result, required):
        return _reject("E_V244_RUN_SHAPE")
    if (
        result.get("schema_version") != V244_RUN_SCHEMA
        or not _text(result.get("run_id"))
        or result.get("run_kind") not in {"api", "e2e"}
        or result.get("outcome")
        not in {"passed", "failed", "blocked", "flaky", "not_run"}
        or not _artifact_refs(result.get("test_case_refs"))
        or not _strings(result.get("case_ids"))
        or not _command(result.get("command"))
        or not _artifact_refs(result.get("data_refs"))
        or not _artifact_refs(result.get("artifacts"))
    ):
        return _reject("E_V244_RUN_REQUIRED")
    important_refs = _all_run_artifact_refs(result)
    if important_refs is None or not _bound_artifact_refs(important_refs):
        return _reject("E_V244_ARTIFACT_INTEGRITY")
    source = result.get("source_binding")
    if (
        not _exact_keys(
            source,
            {"commit", "tree", "protected_snapshot_ref", "snapshot_sha256"},
        )
        or not isinstance(source.get("commit"), str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source["commit"])
        is None
        or not isinstance(source.get("tree"), str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source["tree"])
        is None
        or not _artifact_ref(source.get("protected_snapshot_ref"))
        or not isinstance(source.get("snapshot_sha256"), str)
        or _HEX64.fullmatch(source["snapshot_sha256"]) is None
        or source["snapshot_sha256"]
        != source["protected_snapshot_ref"]["sha256"]
    ):
        return _reject("E_V244_RUN_SOURCE_BINDING")
    identity = result.get("runner_identity")
    if (
        not _exact_keys(
            identity,
            {
                "agent_type",
                "member_id",
                "run_id",
                "host_attestation_ref",
                "designer_member_id",
                "implementation_owner_member_id",
            },
        )
        or identity.get("agent_type")
        not in {"goal_api_integration_test_runner", "goal_e2e_test_runner"}
        or (
            result["run_kind"] == "api"
            and identity.get("agent_type") != "goal_api_integration_test_runner"
        )
        or (
            result["run_kind"] == "e2e"
            and identity.get("agent_type") != "goal_e2e_test_runner"
        )
        or any(
            not _text(identity.get(field))
            for field in (
                "member_id",
                "run_id",
                "designer_member_id",
                "implementation_owner_member_id",
            )
        )
        or identity["run_id"] != result["run_id"]
        or identity["member_id"]
        in {
            identity["designer_member_id"],
            identity["implementation_owner_member_id"],
        }
        or not _artifact_ref(identity.get("host_attestation_ref"))
    ):
        return _reject("E_V244_RUN_IDENTITY")
    plan = result.get("plan_binding")
    if (
        not _exact_keys(plan, {"plan_id", "revision", "sha256", "artifact_ref"})
        or not _text(plan.get("plan_id"))
        or not isinstance(plan.get("revision"), int)
        or isinstance(plan.get("revision"), bool)
        or plan["revision"] < 1
        or not isinstance(plan.get("sha256"), str)
        or _HEX64.fullmatch(plan["sha256"]) is None
        or not _artifact_ref(plan.get("artifact_ref"))
        or plan["sha256"] != plan["artifact_ref"]["sha256"]
    ):
        return _reject("E_V244_RUN_PLAN_BINDING")
    plan_path = _bound_regular_file(plan["artifact_ref"])
    try:
        bound_plan = (
            _strict_json_file(plan_path) if plan_path is not None else None
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        bound_plan = None
    validated_plan = validate_v244_plan(bound_plan)
    if (
        not validated_plan.get("ok")
        or bound_plan.get("plan_id") != plan["plan_id"]
        or bound_plan.get("revision") != plan["revision"]
        or plan["sha256"] != plan["artifact_ref"]["sha256"]
    ):
        return _reject("E_V244_RUN_PLAN_BINDING")
    bound_cases = _load_bound_case_artifacts(
        result["test_case_refs"], result["run_kind"]
    )
    if not bound_cases or set(bound_cases) != set(result["case_ids"]):
        return _reject("E_V244_RUN_CASE_BINDING")
    plan_case_refs = (
        bound_plan["api_case_refs"]
        if result["run_kind"] == "api"
        else bound_plan["e2e_case_refs"]
    )
    plan_cases = _load_bound_case_artifacts(plan_case_refs, result["run_kind"])
    plan_ref_bindings = {
        (item["path"], item["sha256"]) for item in plan_case_refs
    }
    run_ref_bindings = {
        (item["path"], item["sha256"]) for item in result["test_case_refs"]
    }
    if (
        not plan_cases
        or not set(bound_cases) <= set(plan_cases)
        or not run_ref_bindings <= plan_ref_bindings
    ):
        return _reject("E_V244_RUN_CASE_BINDING")
    environment = result.get("environment")
    if (
        not _exact_keys(
            environment,
            {
                "environment_id",
                "base_url",
                "runtime_fingerprint",
                "dependency_fingerprint",
                "config_refs",
            },
        )
        or not _text(environment.get("environment_id"))
        or not _text(environment.get("base_url"))
        or not environment["base_url"].startswith(("http://", "https://"))
        or not _text(environment.get("runtime_fingerprint"))
        or not _text(environment.get("dependency_fingerprint"))
        or not _artifact_refs(environment.get("config_refs"))
    ):
        return _reject("E_V244_RUN_ENVIRONMENT")
    started = _parse_datetime(result.get("started_at"))
    ended = _parse_datetime(result.get("ended_at"))
    duration = result.get("duration_ms")
    if (
        started is None
        or ended is None
        or started.tzinfo is None
        or ended.tzinfo is None
        or ended < started
        or not isinstance(duration, int)
        or isinstance(duration, bool)
        or duration < 0
        or round((ended - started).total_seconds() * 1000) != duration
    ):
        return _reject("E_V244_RUN_TIMING")
    summary = result.get("summary")
    count_fields = ("collected", "passed", "failed", "skipped", "flaky")
    if (
        not _exact_keys(summary, set(count_fields))
        or any(
            not isinstance(summary.get(field), int)
            or isinstance(summary.get(field), bool)
            or summary[field] < 0
            for field in count_fields
        )
        or summary["collected"] < 1
        or summary["passed"]
        + summary["failed"]
        + summary["skipped"]
        + summary["flaky"]
        != summary["collected"]
    ):
        return _reject("E_V244_RUN_SUMMARY")
    case_ids = set(result["case_ids"])
    attempts = result.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return _reject("E_V244_RUN_ATTEMPT")
    attempt_ids: set[str] = set()
    observed_ordinals: list[int] = []
    false_assertions: set[tuple[str, str, str]] = set()
    case_history: dict[str, list[str]] = {case_id: [] for case_id in case_ids}
    for attempt in attempts:
        if not _exact_keys(
            attempt,
            {
                "attempt_id",
                "ordinal",
                "reason",
                "started_at",
                "ended_at",
                "duration_ms",
                "exit_code",
                "outcome",
                "case_results",
                "artifact_refs",
            },
        ):
            return _reject("E_V244_RUN_ATTEMPT")
        attempt_id = attempt.get("attempt_id")
        ordinal = attempt.get("ordinal")
        attempt_started = _parse_datetime(attempt.get("started_at"))
        attempt_ended = _parse_datetime(attempt.get("ended_at"))
        attempt_duration = attempt.get("duration_ms")
        if (
            not _text(attempt_id)
            or attempt_id in attempt_ids
            or not isinstance(ordinal, int)
            or isinstance(ordinal, bool)
            or ordinal < 1
            or attempt.get("reason")
            not in {"initial", "diagnostic_retry", "clean_revalidation"}
            or (ordinal == 1 and attempt["reason"] != "initial")
            or (ordinal != 1 and attempt["reason"] == "initial")
            or attempt_started is None
            or attempt_ended is None
            or attempt_started.tzinfo is None
            or attempt_ended.tzinfo is None
            or attempt_started < started
            or attempt_ended > ended
            or attempt_ended < attempt_started
            or not isinstance(attempt_duration, int)
            or isinstance(attempt_duration, bool)
            or attempt_duration < 0
            or round((attempt_ended - attempt_started).total_seconds() * 1000)
            != attempt_duration
            or not isinstance(attempt.get("exit_code"), int)
            or isinstance(attempt.get("exit_code"), bool)
            or attempt.get("outcome")
            not in {"passed", "failed", "blocked", "not_run"}
            or not _artifact_refs(attempt.get("artifact_refs"))
        ):
            return _reject("E_V244_RUN_ATTEMPT")
        attempt_ids.add(attempt_id)
        observed_ordinals.append(ordinal)
        case_results = attempt.get("case_results")
        if not isinstance(case_results, list) or not case_results:
            return _reject("E_V244_RUN_CASE_RESULT")
        observed_case_ids: set[str] = set()
        attempt_outcomes: list[str] = []
        for case_result in case_results:
            if not _exact_keys(
                case_result,
                {
                    "case_id",
                    "outcome",
                    "consumed_inputs",
                    "observed",
                    "assertion_results",
                },
            ):
                return _reject("E_V244_RUN_CASE_RESULT")
            case_id = case_result.get("case_id")
            case_outcome = case_result.get("outcome")
            assertion_results = case_result.get("assertion_results")
            if (
                case_id not in case_ids
                or case_id in observed_case_ids
                or case_outcome not in {"passed", "failed", "blocked", "not_run"}
                or not isinstance(case_result.get("consumed_inputs"), dict)
                or not case_result["consumed_inputs"]
                or not isinstance(case_result.get("observed"), dict)
                or not case_result["observed"]
                or not isinstance(assertion_results, list)
                or not assertion_results
            ):
                return _reject("E_V244_RUN_CASE_RESULT")
            observed = case_result["observed"]
            if result["run_kind"] == "api":
                if (
                    not isinstance(observed.get("response"), dict)
                    or not isinstance(observed.get("post_state"), dict)
                    or not observed["post_state"]
                    or not _strings(observed.get("side_effects"))
                ):
                    return _reject("E_V244_RUN_API_OBSERVED")
            elif (
                not _text(observed.get("url"))
                or any(
                    not isinstance(observed.get(field), dict)
                    or not observed[field]
                    for field in ("dom", "visible", "interaction", "business")
                )
                or not _strings(
                    observed.get("console_errors"), allow_empty=True
                )
                or not _strings(
                    observed.get("network_errors"), allow_empty=True
                )
                or not _strings(observed.get("side_effects"))
            ):
                return _reject("E_V244_RUN_E2E_OBSERVED")
            observed_case_ids.add(case_id)
            attempt_outcomes.append(case_outcome)
            case_history[case_id].append(case_outcome)
            assertion_ids: set[str] = set()
            assertion_passes: list[bool] = []
            expected_assertions = {
                item["assertion_id"]: item
                for item in bound_cases[case_id]["assertions"]
            }
            for assertion in assertion_results:
                if (
                    not _exact_keys(
                        assertion,
                        {
                            "assertion_id",
                            "comparator",
                            "actual",
                            "expected",
                            "passed",
                        },
                    )
                    or not _text(assertion.get("assertion_id"))
                    or assertion["assertion_id"] in assertion_ids
                    or assertion.get("comparator") not in _V244_COMPARATORS
                    or not isinstance(assertion.get("passed"), bool)
                ):
                    return _reject("E_V244_RUN_ASSERTION_RESULT")
                expected_contract = expected_assertions.get(assertion["assertion_id"])
                if (
                    expected_contract is None
                    or expected_contract["comparator"] != assertion["comparator"]
                    or _evaluate_comparator(
                        assertion["comparator"],
                        assertion["actual"],
                        assertion["expected"],
                    )
                    is not assertion["passed"]
                ):
                    return _reject("E_V244_RUN_ASSERTION_EVALUATION")
                assertion_ids.add(assertion["assertion_id"])
                assertion_passes.append(assertion["passed"])
                if not assertion["passed"]:
                    false_assertions.add(
                        (attempt_id, case_id, assertion["assertion_id"])
                    )
            if assertion_ids != set(expected_assertions):
                return _reject("E_V244_RUN_ASSERTION_RESULT")
            if (
                (case_outcome == "passed" and not all(assertion_passes))
                or (case_outcome == "failed" and all(assertion_passes))
            ):
                return _reject("E_V244_RUN_ASSERTION_RESULT")
        if (
            (attempt["outcome"] == "passed" and (
                attempt["exit_code"] != 0
                or any(item != "passed" for item in attempt_outcomes)
            ))
            or (
                attempt["outcome"] == "failed"
                and (
                    attempt["exit_code"] == 0
                    or "failed" not in attempt_outcomes
                )
            )
        ):
            return _reject("E_V244_RUN_ATTEMPT")
    if observed_ordinals != list(range(1, len(attempts) + 1)):
        return _reject("E_V244_RUN_ATTEMPT")
    final_case_results = attempts[-1]["case_results"]
    if {item["case_id"] for item in final_case_results} != case_ids:
        return _reject("E_V244_RUN_CASE_RESULT")
    flake_cases = {
        case_id
        for case_id, history in case_history.items()
        if "failed" in history[:-1] and history[-1] == "passed"
    }
    final_outcomes = {
        item["case_id"]: item["outcome"] for item in final_case_results
    }
    calculated_summary = {
        "collected": len(case_ids),
        "passed": sum(
            outcome == "passed" and case_id not in flake_cases
            for case_id, outcome in final_outcomes.items()
        ),
        "failed": sum(outcome == "failed" for outcome in final_outcomes.values()),
        "skipped": sum(
            outcome in {"blocked", "not_run"} for outcome in final_outcomes.values()
        ),
        "flaky": len(flake_cases),
    }
    if summary != calculated_summary:
        return _reject("E_V244_RUN_SUMMARY")
    failures = result.get("failures")
    if not isinstance(failures, list):
        return _reject("E_V244_RUN_FAILURE")
    failure_keys: set[tuple[str, str, str]] = set()
    for failure in failures:
        if (
            not _exact_keys(
                failure,
                {
                    "attempt_id",
                    "case_id",
                    "assertion_id",
                    "message",
                    "evidence_refs",
                },
            )
            or failure.get("attempt_id") not in attempt_ids
            or not _text(failure.get("case_id"))
            or failure["case_id"] not in case_ids
            or not _text(failure.get("assertion_id"))
            or not _text(failure.get("message"))
            or not _artifact_refs(failure.get("evidence_refs"))
        ):
            return _reject("E_V244_RUN_FAILURE")
        failure_keys.add(
            (failure["attempt_id"], failure["case_id"], failure["assertion_id"])
        )
    if failure_keys != false_assertions or len(failure_keys) != len(failures):
        return _reject("E_V244_RUN_FAILURE")
    exit_code = result.get("exit_code")
    if (
        not isinstance(exit_code, int)
        or isinstance(exit_code, bool)
        or exit_code != attempts[-1]["exit_code"]
    ):
        return _reject("E_V244_RUN_EXIT")
    if calculated_summary["failed"]:
        calculated_outcome = "failed"
    elif any(
        outcome == "blocked" for outcome in final_outcomes.values()
    ):
        calculated_outcome = "blocked"
    elif any(
        outcome == "not_run" for outcome in final_outcomes.values()
    ):
        calculated_outcome = "not_run"
    elif flake_cases:
        calculated_outcome = "flaky"
    else:
        calculated_outcome = "passed"
    retry = result.get("retry")
    retried_case_ids = {
        case_result["case_id"]
        for attempt in attempts[1:]
        for case_result in attempt["case_results"]
    }
    if (
        not _exact_keys(
            retry,
            {"authorized", "attempted", "max_attempts", "reason_refs", "case_ids"},
        )
        or not isinstance(retry.get("authorized"), bool)
        or not isinstance(retry.get("attempted"), bool)
        or not isinstance(retry.get("max_attempts"), int)
        or isinstance(retry.get("max_attempts"), bool)
        or retry["max_attempts"] < 1
        or not _strings(retry.get("reason_refs"), allow_empty=True)
        or not _strings(retry.get("case_ids"), allow_empty=True)
        or not set(retry["case_ids"]) <= case_ids
        or set(retry["case_ids"]) != retried_case_ids
        or retry["attempted"] != (len(attempts) > 1)
        or retry["attempted"] != bool(retry["case_ids"])
        or (retry["attempted"] and (
            not retry["authorized"]
            or not retry["reason_refs"]
            or len(attempts) > retry["max_attempts"]
        ))
        or (not retry["attempted"] and (
            retry["authorized"]
            or retry["max_attempts"] != 1
            or retry["reason_refs"]
        ))
    ):
        return _reject("E_V244_RUN_RETRY")
    flake = result.get("flake")
    if (
        not _exact_keys(flake, {"detected", "case_ids", "classification"})
        or not isinstance(flake.get("detected"), bool)
        or not _strings(flake.get("case_ids"), allow_empty=True)
        or flake.get("classification") not in {"none", "suspected", "confirmed"}
        or flake["detected"] != bool(flake["case_ids"])
        or (not flake["detected"] and flake["classification"] != "none")
        or (flake["detected"] and flake["classification"] == "none")
        or set(flake["case_ids"]) != flake_cases
        or summary["flaky"] != len(flake_cases)
    ):
        return _reject("E_V244_RUN_FLAKE")
    cleanup = result.get("cleanup")
    if (
        not _exact_keys(
            cleanup, {"command", "status", "observed", "evidence_refs"}
        )
        or not _command(cleanup.get("command"))
        or cleanup.get("status") not in {"verified", "failed", "blocked"}
        or not isinstance(cleanup.get("observed"), dict)
        or not cleanup["observed"]
        or not _artifact_refs(cleanup.get("evidence_refs"))
        or (result["outcome"] == "passed" and cleanup["status"] != "verified")
    ):
        return _reject("E_V244_RUN_CLEANUP")
    replay = result.get("replay")
    if (
        not _exact_keys(
            replay,
            {
                "command",
                "environment_refs",
                "seed_refs",
                "deterministic",
                "evidence_refs",
            },
        )
        or not _command(replay.get("command"))
        or not _artifact_refs(replay.get("environment_refs"))
        or not _artifact_refs(replay.get("seed_refs"))
        or not isinstance(replay.get("deterministic"), bool)
        or not _artifact_refs(replay.get("evidence_refs"))
        or (result["outcome"] == "passed" and replay["deterministic"] is not True)
    ):
        return _reject("E_V244_RUN_REPLAY")
    if cleanup["status"] == "failed":
        calculated_outcome = "failed"
    elif cleanup["status"] == "blocked":
        calculated_outcome = "blocked"
    elif replay["deterministic"] is not True:
        calculated_outcome = "failed"
    if result["outcome"] != calculated_outcome:
        return _reject("E_V244_RUN_OUTCOME")
    return _ok(
        contract_kind="test_run_result",
        run_id=result["run_id"],
        outcome=result["outcome"],
        exit_code=exit_code,
        summary=summary,
        attempt_ids=sorted(attempt_ids),
    )


def validate_document(policy: Any, document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        return policy.validate_test_case_document(document)
    schema_version = document.get("schema_version")
    if schema_version == V244_TEST_CASE_SCHEMA:
        return validate_v244_test_case(document)
    if schema_version == V244_PLAN_SCHEMA:
        return validate_v244_plan(document)
    if schema_version == V244_RUN_SCHEMA:
        return validate_v244_run_result(document)
    if schema_version == V244_FIXTURE_SCHEMA:
        valid_refs = document.get("valid_artifact_refs")
        invalid_documents = document.get("invalid_documents")
        if (
            set(document)
            != {"schema_version", "valid_artifact_refs", "invalid_documents"}
            or not _bound_artifact_refs(valid_refs)
            or not isinstance(invalid_documents, list)
            or not invalid_documents
        ):
            return _reject("E_V244_FIXTURE_SHAPE")
        identifiers: list[str] = []
        for ref in valid_refs:
            path = _bound_regular_file(ref)
            try:
                item = _strict_json_file(path) if path is not None else None
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                return _reject("E_V244_FIXTURE_SHAPE")
            validated = validate_document(policy, item)
            if not validated.get("ok"):
                return validated
            identifiers.append(
                str(
                    validated.get("case_id")
                    or validated.get("plan_id")
                    or validated.get("run_id")
                )
            )
        if len(identifiers) != len(set(identifiers)):
            return _reject("E_V244_FIXTURE_SHAPE")
        invalid_ids: set[str] = set()
        for spec in invalid_documents:
            if (
                not _exact_keys(spec, {"case_id", "error_code", "document"})
                or not _text(spec.get("case_id"))
                or spec["case_id"] in invalid_ids
                or not _text(spec.get("error_code"))
            ):
                return _reject("E_V244_FIXTURE_SHAPE")
            observed = validate_document(policy, spec.get("document"))
            if (
                observed.get("ok") is not False
                or observed.get("error_code") != spec["error_code"]
            ):
                return _reject(
                    "E_V244_FIXTURE_EXPECTATION",
                    case_id=spec["case_id"],
                    expected=spec["error_code"],
                    observed=observed.get("error_code"),
                )
            invalid_ids.add(spec["case_id"])
        return _ok(
            validated_contract_ids=identifiers,
            count=len(identifiers),
            validated_negative_ids=sorted(invalid_ids),
            negative_count=len(invalid_ids),
        )
    if isinstance(schema_version, str) and "v2.44" in schema_version.lower():
        return _reject("E_V244_SCHEMA_VERSION")
    return policy.validate_test_case_document(document)


def _self_test(policy: Any) -> dict[str, Any]:
    fixtures = _read_strict(policy, FIXTURE_PATH)
    valid = policy.validate_test_case_document(fixtures)
    observed: list[str] = []
    failures: list[dict[str, str]] = []
    for spec in fixtures.get("invalid_cases", []):
        result = policy.validate_test_case_contract(_materialize_invalid(spec, fixtures))
        code = result.get("error_code")
        if isinstance(code, str):
            observed.append(code)
        if result.get("ok") is not False or code != spec.get("error_code"):
            failures.append(
                {
                    "case_id": str(spec.get("case_id")),
                    "expected": str(spec.get("error_code")),
                    "observed": str(code),
                }
            )
    v244_valid_count = 0
    v244_negative_count = 0
    if V244_FIXTURE_PATH.is_file():
        v244_fixtures = _read_strict(policy, V244_FIXTURE_PATH)
        v244_valid = validate_document(policy, v244_fixtures)
        v244_valid_count = len(v244_fixtures.get("valid_artifact_refs", []))
        for spec in v244_fixtures.get("invalid_documents", []):
            validated = validate_document(policy, spec.get("document"))
            code = validated.get("error_code")
            v244_negative_count += 1
            if isinstance(code, str):
                observed.append(code)
            if validated.get("ok") is not False or code != spec.get("error_code"):
                failures.append(
                    {
                        "case_id": str(spec.get("case_id")),
                        "expected": str(spec.get("error_code")),
                        "observed": str(code),
                    }
                )
        valid = {
            "ok": valid.get("ok") is True and v244_valid.get("ok") is True
        }
    return {
        "passed": valid.get("ok") is True and not failures,
        "valid_cases_executed": len(fixtures.get("valid_cases", [])),
        "negative_cases_executed": len(fixtures.get("invalid_cases", [])),
        "v244_valid_contracts_executed": v244_valid_count,
        "v244_negative_contracts_executed": v244_negative_count,
        "observed_error_codes": sorted(set(observed)),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    policy = _load_policy()
    try:
        if args.self_test:
            payload = _self_test(policy)
            rc = 0 if payload["passed"] else 1
        elif args.path:
            payload = validate_document(policy, _read_strict(policy, Path(args.path)))
            rc = 0 if payload.get("ok") is True else 1
        else:
            payload = {
                "ok": False,
                "error_code": "E_V235_TEST_CASE_REQUIRED",
                "errors": ["E_V235_TEST_CASE_REQUIRED"],
                "mutation_count": 0,
            }
            rc = 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, policy.DuplicateKeyError) as exc:
        payload = {
            "ok": False,
            "error_code": "E_V235_TEST_CASE_REQUIRED",
            "errors": ["E_V235_TEST_CASE_REQUIRED"],
            "input_error": type(exc).__name__,
            "mutation_count": 0,
        }
        rc = 1
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
