from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "scripts" / "checks" / "validate-test-case-contract.py"
V235_FIXTURE = ROOT / "tests" / "v23" / "fixtures" / "v235" / "test-cases.json"
SCHEMA_ROOT = ROOT / "schemas" / "v2.44"
SHA = "a" * 64
ARTIFACT_ROOT = ROOT / "tests" / "v23" / "fixtures" / "v244" / "artifacts"
GENERIC_ARTIFACT = "tests/v23/fixtures/v244/artifacts/evidence.json"
API_CASE_ARTIFACT = "tests/v23/fixtures/v244/artifacts/api-case.json"
E2E_CASE_ARTIFACT = "tests/v23/fixtures/v244/artifacts/e2e-case.json"
PLAN_ARTIFACT = "tests/v23/fixtures/v244/artifacts/integration-test-plan.json"


def load_validator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_goalteams_v244_test_contract_validator", VALIDATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("validator loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def artifact_ref(
    path: str = GENERIC_ARTIFACT,
    *,
    sha256: str = SHA,
    kind: str = "artifact",
    selector: str = "run.artifacts",
) -> dict[str, Any]:
    aliases = {
        "contracts/v2.44/api-cases.json": API_CASE_ARTIFACT,
        "contracts/v2.44/e2e-cases.json": E2E_CASE_ARTIFACT,
        "contracts/v2.44/integration-test-plan.json": PLAN_ARTIFACT,
    }
    requested_path = path
    path = aliases.get(path, path)
    if not (ROOT / path).is_file():
        path = GENERIC_ARTIFACT
    sha256 = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    return {
        "path": path,
        "sha256": sha256,
        "discovery": {
            "kind": kind,
            "selector": selector if requested_path == path else requested_path,
        },
    }


def _test_file_ref() -> dict[str, Any]:
    path = "tests/v23/test_v244_test_contracts.py"
    sha256 = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    return artifact_ref(
        path,
        sha256=sha256,
        kind="pytest_node",
        selector=path + "::V244TestContractTests",
    )


def covered(assertion_id: str) -> dict[str, Any]:
    return {"status": "covered", "assertion_refs": [assertion_id]}


def plan_risk(
    risk_id: str, domain: str, category: str, case_id: str
) -> dict[str, Any]:
    return {
        "risk_id": risk_id,
        "domain": domain,
        "category": category,
        "source_ref": "acceptance.AC-V244-" + risk_id,
        "severity": "high",
        "applicability": "applicable",
        "case_refs": [case_id],
        "coverage_state": "covered",
    }


def valid_api_case() -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-test-case-v2.44",
        "case_id": "TC-V244-API-001",
        "test_kind": "api",
        "acceptance_refs": ["AC-V244-API-001"],
        "test_file_refs": [_test_file_ref()],
        "setup": {
            "preconditions": ["synthetic order store is empty"],
            "data_refs": [artifact_ref("fixtures/v2.44/orders.json")],
        },
        "api": {
            "method": "POST",
            "path": "/api/orders",
            "auth": {
                "mode": "bearer",
                "persona": "buyer",
                "credential_ref": "environment.auth.buyer_token",
            },
            "request": {
                "headers": {"Idempotency-Key": "REQ-244-001"},
                "path_params": {},
                "query": {},
                "body": {"sku": "SKU-1", "quantity": 1},
            },
            "pre_state": {
                "state_refs": ["setup.synthetic_order_store"],
                "values": {"order_count": 0},
            },
            "processing": {
                "target": "order-api.POST./api/orders",
                "consumed_input_refs": [
                    "api.request.headers.Idempotency-Key",
                    "api.request.body",
                ],
            },
            "expected": {
                "status": 201,
                "headers": {"content-type": "application/json"},
                "body": {"state": "created"},
                "post_state": {"order_count": 1, "order_state": "created"},
                "side_effects": ["one durable order exists after replay"],
            },
            "risk_coverage": {
                "authorization": covered("A-V244-API-BUSINESS"),
                "idempotency": covered("A-V244-API-BUSINESS"),
                "retry": covered("A-V244-API-BUSINESS"),
                "concurrency": covered("A-V244-API-BUSINESS"),
                "compensation": covered("A-V244-API-BUSINESS"),
                "final_consistency": covered("A-V244-API-BUSINESS"),
            },
        },
        "assertions": [
            {
                "assertion_id": "A-V244-API-STATUS",
                "actual_ref": "execution.status_code",
                "comparator": "status_code_equals",
                "expected_ref": "expected.api.status",
            },
            {
                "assertion_id": "A-V244-API-BUSINESS",
                "actual_ref": "observed_output.order.state",
                "comparator": "equals",
                "expected_ref": "expected.api.body.state",
            },
            {
                "assertion_id": "A-V244-API-CLEANUP",
                "actual_ref": "observed_output.cleanup.order_count",
                "comparator": "equals",
                "expected_ref": "expected.cleanup.order_count",
            },
        ],
        "cleanup": {
            "required": True,
            "steps": ["delete synthetic orders by run id"],
            "verification_assertion_refs": ["A-V244-API-CLEANUP"],
        },
    }


def valid_e2e_case() -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-test-case-v2.44",
        "case_id": "TC-V244-E2E-001",
        "test_kind": "e2e",
        "acceptance_refs": ["AC-V244-E2E-001"],
        "test_file_refs": [_test_file_ref()],
        "setup": {
            "preconditions": ["buyer session fixture is available"],
            "data_refs": [artifact_ref("fixtures/v2.44/browser-state.json")],
        },
        "e2e": {
            "persona": {"role": "buyer", "permissions": ["order:create"]},
            "session": {
                "state": "authenticated",
                "auth_ref": "environment.auth.buyer_session",
                "refresh_policy": "refresh once on 401 then surface login",
            },
            "initial_state": {
                "route": "/orders/new",
                "pre_state": {"order_count": 0, "submit_enabled": True},
                "data_refs": [artifact_ref("fixtures/v2.44/browser-state.json")],
            },
            "browser": {
                "name": "chromium",
                "version": "pinned-by-lockfile",
                "viewport": {"width": 1280, "height": 720},
            },
            "actions": [
                {"step_id": "S1", "type": "goto", "target": "/orders/new"},
                {"step_id": "S2", "type": "refresh", "target": "page"},
                {
                    "step_id": "S3",
                    "type": "double_click",
                    "target": "[data-testid='submit-order']",
                },
            ],
            "checkpoints": [
                {
                    "checkpoint_id": "CP1",
                    "after_step_ref": "S3",
                    "assertion_refs": ["A-V244-E2E-ORDER"],
                }
            ],
            "final_state": {
                "url": "/orders/ORDER-1",
                "dom": {"order_status": "created"},
                "visible": {"confirmation": True},
                "interaction": {"submit_enabled": True},
                "business": {"order_count": 1},
                "side_effects": ["one durable order exists"],
            },
            "risk_coverage": {
                "session": covered("A-V244-E2E-ORDER"),
                "permission": covered("A-V244-E2E-ORDER"),
                "refresh": covered("A-V244-E2E-ORDER"),
                "double_click": covered("A-V244-E2E-ORDER"),
                "error_recovery": covered("A-V244-E2E-ORDER"),
            },
        },
        "assertions": [
            {
                "assertion_id": "A-V244-E2E-ORDER",
                "actual_ref": "observed_output.dom.order_count",
                "comparator": "equals",
                "expected_ref": "expected.e2e.order_count",
            },
            {
                "assertion_id": "A-V244-E2E-CLEANUP",
                "actual_ref": "observed_output.cleanup.order_count",
                "comparator": "equals",
                "expected_ref": "expected.cleanup.order_count",
            },
        ],
        "cleanup": {
            "required": True,
            "steps": ["delete browser-created order"],
            "verification_assertion_refs": ["A-V244-E2E-CLEANUP"],
        },
    }


def valid_plan() -> dict[str, Any]:
    risks = [
        plan_risk("API-AUTH", "api", "authorization", "TC-V244-API-001"),
        plan_risk("API-IDEMP", "api", "idempotency", "TC-V244-API-001"),
        plan_risk("API-RETRY", "api", "retry", "TC-V244-API-001"),
        plan_risk("API-CONCUR", "api", "concurrency", "TC-V244-API-001"),
        plan_risk("API-COMP", "api", "compensation", "TC-V244-API-001"),
        plan_risk("API-FINAL", "api", "final_consistency", "TC-V244-API-001"),
        plan_risk("E2E-SESSION", "e2e", "session", "TC-V244-E2E-001"),
        plan_risk("E2E-PERM", "e2e", "permission", "TC-V244-E2E-001"),
        plan_risk("E2E-REFRESH", "e2e", "refresh", "TC-V244-E2E-001"),
        plan_risk("E2E-DBL", "e2e", "double_click", "TC-V244-E2E-001"),
        plan_risk("E2E-RECOVER", "e2e", "error_recovery", "TC-V244-E2E-001"),
    ]
    return {
        "schema_version": "goal-teams-integration-test-plan-v2.44",
        "plan_id": "PLAN-V244-API-E2E",
        "project_version": "V2.44",
        "acceptance_refs": ["AC-V244-API-001", "AC-V244-E2E-001"],
        "scope": {
            "services": ["order-api", "order-web"],
            "user_journeys": ["buyer creates exactly one order"],
            "excluded_with_reason": [],
        },
        "environments": [
            {
                "environment_id": "local-v244",
                "base_url": "http://127.0.0.1:8244",
                "config_refs": [artifact_ref("config/v2.44/local.json")],
                "health_checks": ["GET /health returns 200 and ready=true"],
            }
        ],
        "data_strategy": {
            "seed_refs": [artifact_ref("fixtures/v2.44/orders.json")],
            "isolation": "one database namespace per run id",
            "reset": "delete namespace and verify zero rows",
            "sensitive_data": "synthetic_only",
        },
        "risk_coverage": {
            "risks": risks,
            "summary": {
                "total": 11,
                "applicable": 11,
                "covered": 11,
                "uncovered": 0,
                "not_applicable": 0,
                "coverage_rate": 1,
            },
        },
        "api_case_refs": [artifact_ref("contracts/v2.44/api-cases.json")],
        "e2e_case_refs": [artifact_ref("contracts/v2.44/e2e-cases.json")],
        "execution": {
            "api_command": {
                "argv": ["python3", "-m", "pytest", "tests/api"],
                "cwd": ".",
            },
            "e2e_command": {
                "argv": ["npx", "playwright", "test", "tests/e2e"],
                "cwd": ".",
            },
            "ordering": "api_before_e2e",
            "parallelism": 2,
            "timeout_seconds": 300,
        },
        "entry_criteria": ["health check passed", "synthetic seed hash verified"],
        "exit_criteria": {
            "required_pass_rate": 1,
            "max_failed": 0,
            "max_flaky": 0,
            "cleanup_required": True,
            "replay_required": True,
        },
        "evidence_refs": [artifact_ref("evidence/v2.44/test-run-result.json")],
    }


def valid_run_result() -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-test-run-result-v2.44",
        "run_id": "RUN-V244-001",
        "run_kind": "api",
        "outcome": "passed",
        "source_binding": {
            "commit": "b" * 40,
            "tree": "c" * 40,
            "protected_snapshot_ref": artifact_ref(
                "evidence/v2.44/protected-snapshot.json"
            ),
            "snapshot_sha256": artifact_ref(
                "evidence/v2.44/protected-snapshot.json"
            )["sha256"],
        },
        "runner_identity": {
            "agent_type": "goal_api_integration_test_runner",
            "member_id": "member-api-runner",
            "run_id": "RUN-V244-001",
            "host_attestation_ref": artifact_ref(
                "evidence/v2.44/runner-attestation.json"
            ),
            "designer_member_id": "member-api-designer",
            "implementation_owner_member_id": "member-backend",
        },
        "plan_binding": {
            "plan_id": "PLAN-V244-API-E2E",
            "revision": 1,
            "sha256": artifact_ref(
                "contracts/v2.44/integration-test-plan.json"
            )["sha256"],
            "artifact_ref": artifact_ref(
                "contracts/v2.44/integration-test-plan.json"
            ),
        },
        "test_case_refs": [artifact_ref("contracts/v2.44/api-cases.json")],
        "case_ids": ["TC-V244-API-001"],
        "command": {
            "argv": ["python3", "scripts/run-v244-tests.py"],
            "cwd": ".",
        },
        "environment": {
            "environment_id": "local-v244",
            "base_url": "http://127.0.0.1:8244",
            "runtime_fingerprint": "python=3.11.9;browser=chromium-127",
            "dependency_fingerprint": "lock-sha256:" + SHA,
            "config_refs": [artifact_ref("config/v2.44/local.json")],
        },
        "data_refs": [artifact_ref("fixtures/v2.44/orders.json")],
        "started_at": "2026-07-23T10:00:00Z",
        "ended_at": "2026-07-23T10:00:02.500Z",
        "duration_ms": 2500,
        "exit_code": 0,
        "summary": {
            "collected": 1,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "flaky": 0,
        },
        "attempts": [
            {
                "attempt_id": "ATTEMPT-V244-001",
                "ordinal": 1,
                "reason": "initial",
                "started_at": "2026-07-23T10:00:00Z",
                "ended_at": "2026-07-23T10:00:02.500Z",
                "duration_ms": 2500,
                "exit_code": 0,
                "outcome": "passed",
                "case_results": [
                    {
                        "case_id": "TC-V244-API-001",
                        "outcome": "passed",
                        "consumed_inputs": {
                            "idempotency_key": "REQ-244-001"
                        },
                        "observed": {
                            "response": {"status": 201, "body": {"state": "created"}},
                            "post_state": {"order_count": 1},
                            "side_effects": ["one durable order exists"],
                        },
                        "assertion_results": [
                            {
                                "assertion_id": "A-API-STATUS",
                                "comparator": "status_code_equals",
                                "actual": 201,
                                "expected": 201,
                                "passed": True,
                            },
                            {
                                "assertion_id": "A-API-AUTH",
                                "comparator": "equals",
                                "actual": True,
                                "expected": True,
                                "passed": True,
                            },
                            {
                                "assertion_id": "A-API-IDEMP",
                                "comparator": "equals",
                                "actual": 1,
                                "expected": 1,
                                "passed": True,
                            },
                            {
                                "assertion_id": "A-API-RETRY",
                                "comparator": "equals",
                                "actual": "created",
                                "expected": "created",
                                "passed": True,
                            },
                            {
                                "assertion_id": "A-API-CONCUR",
                                "comparator": "equals",
                                "actual": 1,
                                "expected": 1,
                                "passed": True,
                            },
                            {
                                "assertion_id": "A-API-COMP",
                                "comparator": "equals",
                                "actual": 0,
                                "expected": 0,
                                "passed": True,
                            },
                            {
                                "assertion_id": "A-API-FINAL",
                                "comparator": "equals",
                                "actual": "created",
                                "expected": "created",
                                "passed": True,
                            },
                            {
                                "assertion_id": "A-API-CLEANUP",
                                "comparator": "equals",
                                "actual": 0,
                                "expected": 0,
                                "passed": True,
                            }
                        ],
                    }
                ],
                "artifact_refs": [
                    artifact_ref("evidence/v2.44/attempt-001.json")
                ],
            }
        ],
        "failures": [],
        "artifacts": [artifact_ref("evidence/v2.44/junit.xml")],
        "retry": {
            "authorized": False,
            "attempted": False,
            "max_attempts": 1,
            "reason_refs": [],
            "case_ids": [],
        },
        "flake": {"detected": False, "case_ids": [], "classification": "none"},
        "cleanup": {
            "command": {
                "argv": ["python3", "scripts/cleanup-v244-tests.py"],
                "cwd": ".",
            },
            "status": "verified",
            "observed": {"remaining_synthetic_orders": 0},
            "evidence_refs": [artifact_ref("evidence/v2.44/cleanup.json")],
        },
        "replay": {
            "command": {
                "argv": ["python3", "scripts/run-v244-tests.py", "--replay"],
                "cwd": ".",
            },
            "environment_refs": [artifact_ref("config/v2.44/local.json")],
            "seed_refs": [artifact_ref("fixtures/v2.44/orders.json")],
            "deterministic": True,
            "evidence_refs": [artifact_ref("evidence/v2.44/replay.json")],
        },
    }


def valid_e2e_run_result() -> dict[str, Any]:
    result = valid_run_result()
    result["run_id"] = "RUN-V244-E2E-001"
    result["run_kind"] = "e2e"
    result["runner_identity"].update(
        {
            "agent_type": "goal_e2e_test_runner",
            "member_id": "member-e2e-runner",
            "run_id": "RUN-V244-E2E-001",
            "designer_member_id": "member-e2e-designer",
            "implementation_owner_member_id": "member-frontend",
        }
    )
    result["test_case_refs"] = [
        artifact_ref("contracts/v2.44/e2e-cases.json")
    ]
    result["case_ids"] = ["TC-V244-E2E-001"]
    result["command"] = {
        "argv": ["npx", "playwright", "test", "tests/e2e"],
        "cwd": ".",
    }
    result["attempts"][0]["attempt_id"] = "ATTEMPT-V244-E2E-001"
    result["attempts"][0]["case_results"] = [
        {
            "case_id": "TC-V244-E2E-001",
            "outcome": "passed",
            "consumed_inputs": {"persona": "buyer", "session": "authenticated"},
            "observed": {
                "url": "/orders/ORDER-1",
                "dom": {"order_status": "created"},
                "visible": {"confirmation": True},
                "interaction": {"submit_enabled": True},
                "business": {"order_count": 1},
                "console_errors": [],
                "network_errors": [],
                "side_effects": ["one durable order exists"],
            },
            "assertion_results": [
                {
                    "assertion_id": "A-E2E-SESSION",
                    "comparator": "equals",
                    "actual": True,
                    "expected": True,
                    "passed": True,
                },
                {
                    "assertion_id": "A-E2E-PERM",
                    "comparator": "equals",
                    "actual": True,
                    "expected": True,
                    "passed": True,
                },
                {
                    "assertion_id": "A-E2E-REFRESH",
                    "comparator": "equals",
                    "actual": True,
                    "expected": True,
                    "passed": True,
                },
                {
                    "assertion_id": "A-E2E-DOUBLE",
                    "comparator": "equals",
                    "actual": 1,
                    "expected": 1,
                    "passed": True,
                },
                {
                    "assertion_id": "A-E2E-RECOVERY",
                    "comparator": "equals",
                    "actual": True,
                    "expected": True,
                    "passed": True,
                },
                {
                    "assertion_id": "A-E2E-CLEANUP",
                    "comparator": "equals",
                    "actual": 0,
                    "expected": 0,
                    "passed": True,
                }
            ],
        }
    ]
    return result


def _load_static_contract(filename: str) -> dict[str, Any]:
    return json.loads((ARTIFACT_ROOT / filename).read_text(encoding="utf-8"))


def valid_api_case() -> dict[str, Any]:
    return _load_static_contract("api-case.json")


def valid_e2e_case() -> dict[str, Any]:
    return _load_static_contract("e2e-case.json")


def valid_plan() -> dict[str, Any]:
    return _load_static_contract("integration-test-plan.json")


class V244TestContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_validator()

    def assert_rejected(
        self, document: dict[str, Any], expected_code: str
    ) -> None:
        result = self.validator.validate_document(
            self.validator._load_policy(), document
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], expected_code, result)
        self.assertEqual(result["mutation_count"], 0, result)

    def test_schema_files_are_valid_and_accept_canonical_examples(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")
        examples = (
            ("integration-test-plan.schema.json", valid_plan()),
            ("test-case.schema.json", valid_api_case()),
            ("test-case.schema.json", valid_e2e_case()),
            ("test-run-result.schema.json", valid_run_result()),
            ("test-run-result.schema.json", valid_e2e_run_result()),
        )
        for filename, example in examples:
            with self.subTest(schema=filename):
                schema = json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator.check_schema(schema)
                jsonschema.Draft202012Validator(
                    schema, format_checker=jsonschema.FormatChecker()
                ).validate(example)

    def test_semantic_validator_accepts_plan_api_e2e_and_run_result(self) -> None:
        policy = self.validator._load_policy()
        for document, kind in (
            (valid_plan(), "integration_test_plan"),
            (valid_api_case(), "test_case"),
            (valid_e2e_case(), "test_case"),
            (valid_run_result(), "test_run_result"),
            (valid_e2e_run_result(), "test_run_result"),
        ):
            with self.subTest(kind=kind):
                result = self.validator.validate_document(policy, document)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["contract_kind"], kind, result)

    def test_validator_self_test_is_portable_without_pytest_executable(self) -> None:
        environment = os.environ.copy()
        environment["PATH"] = ""
        result = subprocess.run(
            [sys.executable, str(VALIDATOR_PATH), "--self-test"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"], payload)
        self.assertEqual(2, payload["v244_valid_contracts_executed"], payload)

    def test_v235_document_remains_compatible(self) -> None:
        policy = self.validator._load_policy()
        document = policy.strict_json_loads(V235_FIXTURE.read_text(encoding="utf-8"))
        result = self.validator.validate_document(policy, document)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["count"], 7, result)
        legacy_list = self.validator.validate_document(
            policy, document["valid_cases"][:2]
        )
        self.assertTrue(legacy_list["ok"], legacy_list)
        self.assertEqual(legacy_list["count"], 2, legacy_list)

    def test_api_rejects_unbound_or_bare_test_file_reference(self) -> None:
        bare = valid_api_case()
        bare["test_file_refs"] = ["tests/v23/test_v244_test_contracts.py"]
        self.assert_rejected(bare, "E_V244_ARTIFACT_REF")
        digest_drift = valid_api_case()
        digest_drift["test_file_refs"][0]["sha256"] = "0" * 64
        self.assert_rejected(digest_drift, "E_V244_ARTIFACT_REF")
        undiscoverable = valid_api_case()
        undiscoverable["test_file_refs"][0]["discovery"]["selector"] = (
            "tests/v23/other.py::test_other"
        )
        self.assert_rejected(undiscoverable, "E_V244_TEST_DISCOVERY")
        missing_node = valid_api_case()
        missing_node["test_file_refs"][0]["discovery"]["selector"] = (
            "tests/v23/test_v244_test_contracts.py::DOES_NOT_EXIST"
        )
        self.assert_rejected(missing_node, "E_V244_TEST_DISCOVERY")
        unverifiable_kind = valid_api_case()
        unverifiable_kind["test_file_refs"][0]["discovery"] = {
            "kind": "artifact",
            "selector": "self-reported",
        }
        self.assert_rejected(unverifiable_kind, "E_V244_TEST_DISCOVERY")
        glob_case = valid_api_case()
        glob_case["test_file_refs"][0]["discovery"] = {
            "kind": "glob",
            "selector": "tests/v23/fixtures/v244/artifacts/test_*.py",
        }
        accepted = self.validator.validate_document(
            self.validator._load_policy(), glob_case
        )
        self.assertTrue(accepted["ok"], accepted)
        empty_glob = valid_api_case()
        empty_glob["test_file_refs"][0]["discovery"] = {
            "kind": "glob",
            "selector": "tests/v23/fixtures/v244/artifacts/missing-*.py",
        }
        self.assert_rejected(empty_glob, "E_V244_TEST_DISCOVERY")

    def test_api_requires_auth_oracle_and_all_risk_dimensions(self) -> None:
        missing_credential = valid_api_case()
        missing_credential["api"]["auth"].pop("credential_ref")
        self.assert_rejected(missing_credential, "E_V244_API_AUTH")
        status_only = valid_api_case()
        status_only["assertions"] = [status_only["assertions"][0]] * 2
        self.assert_rejected(status_only, "E_V244_ASSERTION")
        missing_risk = valid_api_case()
        missing_risk["api"]["risk_coverage"].pop("concurrency")
        self.assert_rejected(missing_risk, "E_V244_API_RISK_COVERAGE")
        foreign_assertion = valid_api_case()
        foreign_assertion["api"]["risk_coverage"]["retry"][
            "oracle_assertion_ref"
        ] = "A-FOREIGN"
        self.assert_rejected(foreign_assertion, "E_V244_API_RISK_SCENARIO")
        missing_pre_state = valid_api_case()
        missing_pre_state["api"].pop("pre_state")
        self.assert_rejected(missing_pre_state, "E_V244_API_SHAPE")
        missing_post_state = valid_api_case()
        missing_post_state["api"]["expected"].pop("post_state")
        self.assert_rejected(missing_post_state, "E_V244_API_ORACLE")

    def test_e2e_binds_actions_checkpoints_and_resilience_risks(self) -> None:
        missing_refresh = valid_e2e_case()
        missing_refresh["e2e"]["actions"] = [
            action
            for action in missing_refresh["e2e"]["actions"]
            if action["type"] != "refresh"
        ]
        missing_refresh["e2e"]["checkpoints"] = [
            checkpoint
            for checkpoint in missing_refresh["e2e"]["checkpoints"]
            if checkpoint["after_step_ref"] != "S3"
        ]
        self.assert_rejected(missing_refresh, "E_V244_E2E_RISK_SCENARIO")
        unknown_step = valid_e2e_case()
        unknown_step["e2e"]["checkpoints"][0]["after_step_ref"] = "S404"
        self.assert_rejected(unknown_step, "E_V244_E2E_CHECKPOINT")
        missing_permission = valid_e2e_case()
        missing_permission["e2e"]["risk_coverage"].pop("permission")
        self.assert_rejected(missing_permission, "E_V244_E2E_RISK_COVERAGE")
        missing_session = valid_e2e_case()
        missing_session["e2e"].pop("session")
        self.assert_rejected(missing_session, "E_V244_E2E_SHAPE")
        missing_final = valid_e2e_case()
        missing_final["e2e"].pop("final_state")
        self.assert_rejected(missing_final, "E_V244_E2E_SHAPE")

    def test_plan_fails_closed_on_risk_exit_and_environment_drift(self) -> None:
        incomplete_risk = valid_plan()
        incomplete_risk["risk_coverage"]["risks"] = [
            risk
            for risk in incomplete_risk["risk_coverage"]["risks"]
            if risk["category"] != "compensation"
        ]
        incomplete_risk["risk_coverage"]["summary"]["total"] = 10
        incomplete_risk["risk_coverage"]["summary"]["applicable"] = 10
        incomplete_risk["risk_coverage"]["summary"]["covered"] = 10
        self.assert_rejected(incomplete_risk, "E_V244_PLAN_RISK_COVERAGE")
        forged_denominator = valid_plan()
        forged_denominator["risk_coverage"]["summary"]["covered"] = 10
        forged_denominator["risk_coverage"]["summary"]["uncovered"] = 1
        forged_denominator["risk_coverage"]["summary"]["coverage_rate"] = 10 / 11
        self.assert_rejected(forged_denominator, "E_V244_PLAN_RISK_COVERAGE")
        unreviewed_na = valid_plan()
        first_risk = unreviewed_na["risk_coverage"]["risks"][0]
        first_risk.update(
            {
                "applicability": "not_applicable",
                "case_refs": [],
                "coverage_state": "not_applicable",
                "not_applicable_reason": "endpoint is public",
            }
        )
        self.assert_rejected(unreviewed_na, "E_V244_PLAN_RISK_COVERAGE")
        reviewed_na = valid_plan()
        first_risk = reviewed_na["risk_coverage"]["risks"][0]
        first_risk.update(
            {
                "applicability": "not_applicable",
                "case_refs": [],
                "coverage_state": "not_applicable",
                "not_applicable_reason": "endpoint is public by accepted contract",
                "review_acceptance_ref": "review.REVIEW-V244-AUTH-NA",
            }
        )
        reviewed_na["risk_coverage"]["summary"].update(
            {
                "applicable": 10,
                "covered": 10,
                "not_applicable": 1,
                "coverage_rate": 1,
            }
        )
        accepted_na = self.validator.validate_document(
            self.validator._load_policy(), reviewed_na
        )
        self.assertTrue(accepted_na["ok"], accepted_na)
        weaker_exit = valid_plan()
        weaker_exit["exit_criteria"]["max_flaky"] = 1
        self.assert_rejected(weaker_exit, "E_V244_PLAN_EXIT")
        duplicate_environment = valid_plan()
        duplicate_environment["environments"].append(
            copy.deepcopy(duplicate_environment["environments"][0])
        )
        self.assert_rejected(duplicate_environment, "E_V244_PLAN_ENVIRONMENT")

    def test_plan_requires_independent_identity_and_case_chain(self) -> None:
        plan = valid_plan()
        plan.update(
            {
                "revision": 1,
                "owner_identity": {
                    "agent_type": "goal_api_integration_test_designer",
                    "member_id": "member-plan-owner",
                    "run_id": "RUN-V244-PLAN-OWNER",
                },
                "validator_identity": {
                    "agent_type": "goal_reviewer",
                    "member_id": "member-plan-reviewer",
                    "run_id": "RUN-V244-PLAN-REVIEW",
                },
            }
        )
        accepted = self.validator.validate_document(
            self.validator._load_policy(), plan
        )
        self.assertTrue(accepted["ok"], accepted)
        self_review = copy.deepcopy(plan)
        self_review["validator_identity"]["member_id"] = self_review[
            "owner_identity"
        ]["member_id"]
        self.assert_rejected(self_review, "E_V244_PLAN_IDENTITY")
        foreign_case = copy.deepcopy(plan)
        foreign_case["risk_coverage"]["risks"][0]["case_refs"] = [
            "TC-V244-API-DOES-NOT-EXIST"
        ]
        self.assert_rejected(foreign_case, "E_V244_PLAN_CASE_BINDING")

    def test_each_risk_requires_dedicated_executable_scenario_and_oracle(self) -> None:
        shared_api_oracle = valid_api_case()
        for control in shared_api_oracle["api"]["risk_coverage"].values():
            control["scenario_ref"] = "SC-API-AUTH"
            control["oracle_assertion_ref"] = "A-API-AUTH"
        self.assert_rejected(
            shared_api_oracle, "E_V244_API_RISK_SCENARIO"
        )
        shared_e2e_oracle = valid_e2e_case()
        for control in shared_e2e_oracle["e2e"]["risk_coverage"].values():
            control["scenario_ref"] = "S1"
            control["oracle_assertion_ref"] = "A-E2E-SESSION"
        self.assert_rejected(
            shared_e2e_oracle, "E_V244_E2E_RISK_SCENARIO"
        )

    def test_run_result_binds_counts_exit_retry_flake_cleanup_and_replay(self) -> None:
        bad_summary = valid_run_result()
        bad_summary["summary"]["passed"] = 0
        self.assert_rejected(bad_summary, "E_V244_RUN_SUMMARY")
        false_success = valid_run_result()
        false_success["exit_code"] = 1
        self.assert_rejected(false_success, "E_V244_RUN_EXIT")
        hidden_retry = valid_run_result()
        hidden_retry["retry"] = {
            "authorized": False,
            "attempted": False,
            "max_attempts": 2,
            "reason_refs": [],
            "case_ids": [],
        }
        self.assert_rejected(hidden_retry, "E_V244_RUN_RETRY")
        hidden_flake = valid_run_result()
        hidden_flake["flake"] = {
            "detected": False,
            "case_ids": ["TC-V244-E2E-001"],
            "classification": "none",
        }
        self.assert_rejected(hidden_flake, "E_V244_RUN_FLAKE")
        cleanup_not_verified = valid_run_result()
        cleanup_not_verified["cleanup"]["status"] = "failed"
        self.assert_rejected(cleanup_not_verified, "E_V244_RUN_CLEANUP")
        replay_not_deterministic = valid_run_result()
        replay_not_deterministic["replay"]["deterministic"] = False
        self.assert_rejected(replay_not_deterministic, "E_V244_RUN_REPLAY")
        time_drift = valid_run_result()
        time_drift["duration_ms"] = 2499
        self.assert_rejected(time_drift, "E_V244_RUN_TIMING")

    def test_run_result_rejects_source_identity_and_attempt_proof_gaps(self) -> None:
        source_drift = valid_run_result()
        source_drift["source_binding"]["snapshot_sha256"] = "0" * 64
        self.assert_rejected(source_drift, "E_V244_RUN_SOURCE_BINDING")
        self_review = valid_run_result()
        self_review["runner_identity"]["designer_member_id"] = self_review[
            "runner_identity"
        ]["member_id"]
        self.assert_rejected(self_review, "E_V244_RUN_IDENTITY")
        missing_observation = valid_run_result()
        missing_observation["attempts"][0]["case_results"][0]["observed"] = {}
        self.assert_rejected(missing_observation, "E_V244_RUN_CASE_RESULT")
        assertion_wash = valid_run_result()
        assertion_wash["attempts"][0]["case_results"][0]["assertion_results"][0][
            "passed"
        ] = False
        self.assert_rejected(assertion_wash, "E_V244_RUN_ASSERTION_EVALUATION")
        forged_comparator = valid_run_result()
        assertion = forged_comparator["attempts"][0]["case_results"][0][
            "assertion_results"
        ][0]
        assertion.update({"actual": "wrong", "expected": "created", "passed": True})
        self.assert_rejected(
            forged_comparator, "E_V244_RUN_ASSERTION_EVALUATION"
        )
        missing_artifact = valid_run_result()
        missing_artifact["artifacts"][0]["path"] = (
            "evidence/v2.44/does-not-exist.xml"
        )
        self.assert_rejected(missing_artifact, "E_V244_ARTIFACT_INTEGRITY")
        fixture_root = ROOT / "tests" / "v23" / "fixtures" / "v244"
        with tempfile.TemporaryDirectory(dir=fixture_root) as directory:
            temporary = Path(directory)
            real_dir = temporary / "real"
            real_dir.mkdir()
            real_file = real_dir / "evidence.json"
            real_file.write_text('{"status":"verified"}\n', encoding="utf-8")
            alias = temporary / "alias"
            os.symlink(real_dir, alias)
            symlinked = valid_run_result()
            relative = (alias / "evidence.json").relative_to(ROOT).as_posix()
            symlinked["artifacts"][0] = artifact_ref(
                relative,
                sha256=hashlib.sha256(real_file.read_bytes()).hexdigest(),
            )
            symlinked["artifacts"][0]["path"] = relative
            symlinked["artifacts"][0]["sha256"] = hashlib.sha256(
                real_file.read_bytes()
            ).hexdigest()
            self.assert_rejected(
                symlinked, "E_V244_ARTIFACT_INTEGRITY"
            )
        foreign_case = valid_run_result()
        foreign_case["case_ids"] = ["TC-V244-API-DOES-NOT-EXIST"]
        foreign_case["attempts"][0]["case_results"][0]["case_id"] = (
            "TC-V244-API-DOES-NOT-EXIST"
        )
        self.assert_rejected(foreign_case, "E_V244_RUN_CASE_BINDING")

    def test_run_result_recomputes_every_supported_comparator(self) -> None:
        valid_pairs = {
            "equals": (1, 1, 2),
            "not_equals": (1, 2, 1),
            "contains": (["a", "b"], "a", "z"),
            "member_of": ("a", ["a", "b"], ["z"]),
            "less_than": (1, 2, 0),
            "less_than_or_equal": (2, 2, 1),
            "greater_than": (2, 1, 3),
            "greater_than_or_equal": (2, 2, 3),
            "json_subset": ({"a": 1, "b": 2}, {"a": 1}, {"a": 2}),
            "sequence_equals": ([1, 2], [1, 2], [2, 1]),
            "sha256_equals": ("a" * 64, "a" * 64, "b" * 64),
            "status_code_equals": (201, 201, 500),
            "visible": (True, True, False),
            "not_visible": (False, False, True),
        }
        for comparator, (actual, expected, invalid_expected) in valid_pairs.items():
            with self.subTest(comparator=comparator):
                self.assertTrue(
                    self.validator._evaluate_comparator(
                        comparator, actual, expected
                    )
                )
                self.assertFalse(
                    self.validator._evaluate_comparator(
                        comparator, actual, invalid_expected
                    )
                )

    def test_run_result_checks_every_artifact_group(self) -> None:
        selectors = {
            "snapshot": lambda d: d["source_binding"]["protected_snapshot_ref"],
            "attestation": lambda d: d["runner_identity"]["host_attestation_ref"],
            "plan": lambda d: d["plan_binding"]["artifact_ref"],
            "case": lambda d: d["test_case_refs"][0],
            "config": lambda d: d["environment"]["config_refs"][0],
            "data": lambda d: d["data_refs"][0],
            "attempt": lambda d: d["attempts"][0]["artifact_refs"][0],
            "top-level": lambda d: d["artifacts"][0],
            "cleanup": lambda d: d["cleanup"]["evidence_refs"][0],
            "replay-environment": lambda d: d["replay"]["environment_refs"][0],
            "replay-seed": lambda d: d["replay"]["seed_refs"][0],
            "replay-evidence": lambda d: d["replay"]["evidence_refs"][0],
        }
        for name, select in selectors.items():
            with self.subTest(group=name):
                document = valid_run_result()
                select(document)["sha256"] = "0" * 64
                self.assert_rejected(
                    document, "E_V244_ARTIFACT_INTEGRITY"
                )

    def test_fail_to_pass_is_retained_as_flaky_not_clean_pass(self) -> None:
        flaky = valid_run_result()
        clean_attempt = copy.deepcopy(flaky["attempts"][0])
        clean_attempt.update(
            {
                "attempt_id": "ATTEMPT-V244-002",
                "ordinal": 2,
                "reason": "diagnostic_retry",
                "started_at": "2026-07-23T10:00:01Z",
                "duration_ms": 1500,
            }
        )
        first_attempt = copy.deepcopy(flaky["attempts"][0])
        first_attempt.update(
            {
                "attempt_id": "ATTEMPT-V244-001",
                "ordinal": 1,
                "reason": "initial",
                "ended_at": "2026-07-23T10:00:00.500Z",
                "duration_ms": 500,
                "exit_code": 1,
                "outcome": "failed",
            }
        )
        failed_case = first_attempt["case_results"][0]
        failed_case["outcome"] = "failed"
        failed_assertion = failed_case["assertion_results"][3]
        failed_assertion["actual"] = "missing"
        failed_assertion["passed"] = False
        first_attempt["case_results"] = [failed_case]
        flaky["attempts"] = [first_attempt, clean_attempt]
        flaky["summary"] = {
            "collected": 1,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "flaky": 1,
        }
        flaky["failures"] = [
            {
                "attempt_id": "ATTEMPT-V244-001",
                "case_id": "TC-V244-API-001",
                "assertion_id": "A-API-RETRY",
                "message": "initial attempt did not observe the order",
                "evidence_refs": [artifact_ref("evidence/v2.44/failure.json")],
            }
        ]
        flaky["retry"] = {
            "authorized": True,
            "attempted": True,
            "max_attempts": 2,
            "reason_refs": ["plan.retry_policy.diagnostic"],
            "case_ids": ["TC-V244-API-001"],
        }
        flaky["flake"] = {
            "detected": True,
            "case_ids": ["TC-V244-API-001"],
            "classification": "confirmed",
        }
        self.assert_rejected(flaky, "E_V244_RUN_OUTCOME")
        flaky["outcome"] = "flaky"
        accepted = self.validator.validate_document(
            self.validator._load_policy(), flaky
        )
        self.assertTrue(accepted["ok"], accepted)
        self.assertEqual(accepted["summary"]["flaky"], 1, accepted)

    def test_cli_emits_one_line_and_self_test_executes_v244_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api-case.json"
            path.write_text(
                json.dumps(valid_api_case(), ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(VALIDATOR_PATH), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, (proc.stdout, proc.stderr))
        self.assertEqual(len(proc.stdout.strip().splitlines()), 1)
        self.assertTrue(json.loads(proc.stdout)["ok"])
        self_test = subprocess.run(
            [sys.executable, str(VALIDATOR_PATH), "--self-test"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            self_test.returncode, 0, (self_test.stdout, self_test.stderr)
        )
        payload = json.loads(self_test.stdout)
        self.assertTrue(payload["passed"], payload)
        self.assertGreaterEqual(payload["v244_valid_contracts_executed"], 1)
        self.assertGreaterEqual(payload["v244_negative_contracts_executed"], 1)


if __name__ == "__main__":
    unittest.main()
