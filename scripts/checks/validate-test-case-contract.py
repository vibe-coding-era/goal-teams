#!/usr/bin/env python3
"""Canonical deterministic validator for Goal Teams V2.35 test-case contracts."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "scripts" / "v23" / "v235_policy.py"
FIXTURE_PATH = ROOT / "tests" / "v23" / "fixtures" / "v235" / "test-cases.json"


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
    return {
        "passed": valid.get("ok") is True and not failures,
        "valid_cases_executed": len(fixtures.get("valid_cases", [])),
        "negative_cases_executed": len(fixtures.get("invalid_cases", [])),
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
            payload = policy.validate_test_case_document(
                _read_strict(policy, Path(args.path))
            )
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
