"""Adversarial JSON-type regressions for V2.35 public validators."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from tests.v23.common import ROOT, parse_envelope, run_cli


POLICY_PATH = ROOT / "scripts" / "v23" / "v235_policy.py"
TEST_CASE_FIXTURE = ROOT / "tests" / "v23" / "fixtures" / "v235" / "test-cases.json"
PUBLIC_TEST_CASE_VALIDATOR = ROOT / "scripts" / "validate-test-case-contract.py"


def load_policy() -> Any:
    spec = importlib.util.spec_from_file_location(
        "goalteams_v235_fail_closed_policy_under_test", POLICY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(POLICY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_public_validator(path: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(PUBLIC_TEST_CASE_VALIDATOR), str(path)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_object(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"expected one JSON object: rc={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        ) from exc
    if not isinstance(value, dict):
        raise AssertionError(f"expected object, got {type(value).__name__}")
    return value


class V235FailClosedTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_policy()
        cls.fixtures = json.loads(TEST_CASE_FIXTURE.read_text(encoding="utf-8"))

    def assert_rejected(self, result: dict[str, Any], expected_code: str) -> None:
        self.assertFalse(result.get("ok"), result)
        self.assertEqual(result.get("error_code"), expected_code, result)
        self.assertEqual(result.get("mutation_count"), 0, result)

    def test_specialist_and_release_nested_types_return_stable_rejections(self) -> None:
        registry = copy.deepcopy(self.fixtures["specialist_registry"])
        registry["identities"][0]["capabilities"] = [{}]
        security = copy.deepcopy(self.fixtures["specialist_proposals"]["security"])
        security["coverage"] = [{}]
        sqa = copy.deepcopy(self.fixtures["specialist_proposals"]["sqa"])
        sqa["classifications"] = [{}]
        release = copy.deepcopy(self.fixtures["release_audit_gate"]["valid"])
        release["release_commit"] = 42
        cases: tuple[
            tuple[str, Callable[[Any], dict[str, Any]], dict[str, Any], str], ...
        ] = (
            (
                "capabilities-object",
                self.policy.validate_specialist_capability_registry,
                registry,
                "E_V235_SPECIALIST_CAPABILITY",
            ),
            (
                "security-coverage-object",
                self.policy.validate_specialist_proposal,
                security,
                "E_V235_SECURITY_SCOPE",
            ),
            (
                "sqa-classifications-object",
                self.policy.validate_specialist_proposal,
                sqa,
                "E_V235_SQA_ARCHIVE_CONTRACT",
            ),
            (
                "release-commit-integer",
                self.policy.evaluate_release_audit_gate,
                release,
                "E_V235_RELEASE_TASK",
            ),
        )
        for name, validator, document, expected_code in cases:
            with self.subTest(case=name):
                self.assert_rejected(validator(document), expected_code)

    def test_green_gate_object_identity_fields_return_stable_rejection(self) -> None:
        for field in ("runner_run_id", "designer_run_id", "implementer_run_id"):
            candidate = copy.deepcopy(self.fixtures["green_gate"]["valid"])
            candidate[field] = {}
            with self.subTest(field=field):
                self.assert_rejected(
                    self.policy.evaluate_green_gate(candidate),
                    "E_V235_GREEN_INDEPENDENCE",
                )

    def test_specialist_dispatch_owner_and_actor_reuse_fail_closed(self) -> None:
        registry = self.fixtures["specialist_registry"]
        for mode in ("missing", "wrong"):
            candidate = copy.deepcopy(registry)
            if mode == "missing":
                candidate["identities"][0].pop("dispatch_owner_agent_type")
            else:
                candidate["identities"][0]["dispatch_owner_agent_type"] = "goal_security"
            with self.subTest(dispatch_owner=mode):
                self.assert_rejected(
                    self.policy.validate_specialist_capability_registry(candidate),
                    "E_V235_SPECIALIST_PERMISSION",
                )

        valid_lifecycle = [
            {"state": "proposed", "actor_run_id": "RUN-SPECIALIST-01"},
            {"state": "reviewed", "actor_run_id": "RUN-REVIEW-01"},
            {"state": "applied", "actor_run_id": "RUN-IMPLEMENT-01"},
            {
                "state": "verified",
                "actor_run_id": "RUN-QA-01",
                "regression_evidence_id": "EVID-REGRESSION-01",
                "holdout_evidence_id": "EVID-HOLDOUT-01",
            },
        ]
        for reused_at in (2, 3):
            candidate = copy.deepcopy(valid_lifecycle)
            candidate[reused_at]["actor_run_id"] = candidate[0]["actor_run_id"]
            with self.subTest(proposed_actor_reused_at=candidate[reused_at]["state"]):
                self.assert_rejected(
                    self.policy.validate_specialist_improvement_lifecycle(candidate),
                    "E_V235_SPECIALIST_LIFECYCLE",
                )

    def test_implementation_gate_identity_fields_are_required_strings(self) -> None:
        targets = (
            ("contract", "owner_run_id"),
            ("contract", "validator_run_id"),
            ("architecture", "owner_run_id"),
            ("architecture", "validator_run_id"),
            ("environment", "owner_run_id"),
            ("environment", "validator_run_id"),
            ("red_evidence", "designer_run_id"),
            (None, "implementer_run_id"),
        )
        for section, field in targets:
            for malformed in (None, {}):
                candidate = copy.deepcopy(self.fixtures["implementation_gate"]["valid"])
                target = candidate if section is None else candidate[section]
                if malformed is None:
                    target.pop(field)
                    mode = "missing"
                else:
                    target[field] = malformed
                    mode = "object"
                with self.subTest(section=section or "root", field=field, mode=mode):
                    self.assert_rejected(
                        self.policy.evaluate_implementation_gate(candidate),
                        "E_V235_GATE_INDEPENDENCE",
                    )

    def malformed_test_cases(self) -> list[tuple[str, dict[str, Any], str]]:
        cases: list[tuple[str, dict[str, Any], str]] = []
        for malformed in ({}, []):
            suffix = "object" if isinstance(malformed, dict) else "list"
            test_kind = copy.deepcopy(self.fixtures["valid_cases"][0])
            test_kind["test_kind"] = copy.deepcopy(malformed)
            cases.append(
                (f"test-kind-{suffix}", test_kind, "E_V235_TEST_CASE_REQUIRED")
            )
            processing = copy.deepcopy(self.fixtures["valid_cases"][0])
            processing["processing"]["kind"] = copy.deepcopy(malformed)
            cases.append(
                (
                    f"processing-kind-{suffix}",
                    processing,
                    "E_V235_PROCESSING_NOT_EXECUTABLE",
                )
            )
            comparator = copy.deepcopy(self.fixtures["valid_cases"][0])
            comparator["assertions"][0]["comparator"] = copy.deepcopy(malformed)
            cases.append(
                (
                    f"assertion-comparator-{suffix}",
                    comparator,
                    "E_V235_COMPARATOR_UNKNOWN",
                )
            )
        return cases

    def test_canonical_test_case_policy_rejects_unhashable_nested_types(self) -> None:
        for name, document, expected_code in self.malformed_test_cases():
            with self.subTest(case=name):
                self.assert_rejected(
                    self.policy.validate_test_case_contract(document), expected_code
                )

    def test_cli_test_case_validator_rejects_unhashable_nested_types_in_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed-test-case.json"
            for name, document, expected_code in self.malformed_test_cases():
                path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
                proc = run_cli("validate-test-case", str(path))
                with self.subTest(case=name):
                    self.assertEqual(proc.returncode, 1, (proc.stdout, proc.stderr))
                    result = parse_envelope(proc)
                    self.assert_rejected(result, expected_code)
                    self.assertEqual(len(proc.stdout.strip().splitlines()), 1)

    def test_public_test_case_script_rejects_unhashable_nested_types_in_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed-test-case.json"
            for name, document, expected_code in self.malformed_test_cases():
                path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
                proc = run_public_validator(path)
                with self.subTest(case=name):
                    self.assertEqual(proc.returncode, 1, (proc.stdout, proc.stderr))
                    result = parse_object(proc)
                    self.assert_rejected(result, expected_code)
                    self.assertEqual(len(proc.stdout.strip().splitlines()), 1)

    def test_route_malformed_json_preserves_legacy_parse_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed-route.json"
            path.write_text('{"schema_version":', encoding="utf-8")
            proc = run_cli("route", str(path))
        self.assertEqual(proc.returncode, 1, (proc.stdout, proc.stderr))
        result = parse_envelope(proc)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_JSON_PARSE", result)


if __name__ == "__main__":
    unittest.main()
