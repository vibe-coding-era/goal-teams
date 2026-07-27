from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "scripts" / "checks" / "validate-desktop-engineering.py"
MANIFEST_PATH = ROOT / "references" / "desktop-capability-manifest.json"
SCHEMA_PATH = ROOT / "schemas" / "v2.46" / "desktop-engineering.schema.json"
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "v23"
    / "fixtures"
    / "v246"
    / "desktop-engineering-cases.json"
)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V246DesktopEngineeringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = _load_module(
            "_goalteams_v246_desktop_engineering_validator",
            VALIDATOR_PATH,
        )
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.artifact_directory = tempfile.TemporaryDirectory(dir=ROOT / "docs")
        cls.artifact_root = Path(cls.artifact_directory.name)
        cls._hydrate_typed_artifacts(cls.fixtures["base_document"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.artifact_directory.cleanup()

    @classmethod
    def _write_artifact(
        cls,
        name: str,
        payload: dict[str, Any] | bytes,
    ) -> dict[str, str]:
        path = cls.artifact_root / name
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        return {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    @classmethod
    def _bind_evidence(
        cls,
        evidence: dict[str, Any],
        *,
        evidence_type: str,
        subject_id: str,
        command: str | None,
        tuple_id: str | None,
        producer_run_id: str,
        reviewer_run_id: str,
        assertion_ids: list[str],
    ) -> None:
        evidence.update(
            {
                "evidence_type": evidence_type,
                "result": "passed",
                "producer_run_id": producer_run_id,
                "reviewer_run_id": reviewer_run_id,
                "subject_id": subject_id,
                "command": command,
                "tuple_id": tuple_id,
                "assertion_ids": assertion_ids,
            }
        )
        payload = {
            "schema_version": "goal-teams-desktop-evidence-v1",
            **{
                key: value
                for key, value in evidence.items()
                if key != "artifact"
            },
        }
        evidence["artifact"] = cls._write_artifact(
            evidence["evidence_id"] + ".json",
            payload,
        )

    @classmethod
    def _bind_baseline_approval(
        cls,
        document: dict[str, Any],
    ) -> None:
        approval = document["source_contract"]["baseline_approval"]
        payload = {
            "schema_version": "goal-teams-desktop-approval-v1",
            "approval_type": "baseline",
            "bundle_id": document["bundle_id"],
            "bundle_revision": document["revision"],
            "approval_id": approval["approval_id"],
            "author_run_id": approval["author_run_id"],
            "reviewer_run_id": approval["reviewer_run_id"],
            "decision": approval["decision"],
        }
        approval["artifact"] = cls._write_artifact(
            "baseline-approval.json",
            payload,
        )

    @classmethod
    def _hydrate_typed_artifacts(cls, document: dict[str, Any]) -> None:
        roles = document["roles"]
        producer = roles["test_runner_run_id"]
        reviewer = roles["reviewer_run_id"]
        cls._bind_baseline_approval(document)
        for gate in document["rust_backend_contract"]["gates"]:
            cls._bind_evidence(
                gate["evidence"],
                evidence_type="rust_gate",
                subject_id=gate["gate_id"],
                command=gate["command"],
                tuple_id=None,
                producer_run_id=producer,
                reviewer_run_id=reviewer,
                assertion_ids=["ASSERT-RUST-GATE-PASSED"],
            )
        contract = document["desktop_test_contract"]
        cases = {case["case_id"]: case for case in contract["cases"]}
        for run in contract["runs"]:
            cls._bind_evidence(
                run["evidence"],
                evidence_type="desktop_run",
                subject_id=run["run_id"],
                command=None,
                tuple_id=run["tuple_id"],
                producer_run_id=run["runner_run_id"],
                reviewer_run_id=run["reviewer_run_id"],
                assertion_ids=list(cases[run["case_id"]]["assertions"]),
            )
        replica = document["ui_replica_contract"]
        cls._bind_evidence(
            replica["coverage_complete"]["evidence"],
            evidence_type="coverage_metric",
            subject_id="coverage_complete",
            command=None,
            tuple_id=None,
            producer_run_id=producer,
            reviewer_run_id=reviewer,
            assertion_ids=["ASSERT-COVERAGE-COMPLETE"],
        )
        for metric in replica["pixel_exact"]:
            cls._bind_evidence(
                metric["evidence"],
                evidence_type="pixel_metric",
                subject_id="pixel_exact",
                command=None,
                tuple_id=metric["tuple_id"],
                producer_run_id=producer,
                reviewer_run_id=reviewer,
                assertion_ids=["ASSERT-ZERO-PIXEL-DIFF"],
            )
        for index, metric in enumerate(replica["high_fidelity"]):
            metric["evidence"] = {
                "evidence_id": f"EV-HIGH-FIDELITY-{index + 1}",
                "level": "L3",
                "artifact": copy.deepcopy(metric["diff_artifact"]),
                "code_revision": "a" * 64,
                "contract_revision": document["revision"],
                "environment_id": "ENV-MACOS-14-ARM64",
            }
            cls._bind_evidence(
                metric["evidence"],
                evidence_type="high_fidelity_metric",
                subject_id="high_fidelity",
                command=None,
                tuple_id=metric["tuple_id"],
                producer_run_id=producer,
                reviewer_run_id=reviewer,
                assertion_ids=["ASSERT-FIDELITY-THRESHOLD"],
            )
        cls._bind_evidence(
            replica["native_semantic_match"]["evidence"],
            evidence_type="native_metric",
            subject_id="native_semantic_match",
            command=None,
            tuple_id=None,
            producer_run_id=producer,
            reviewer_run_id=reviewer,
            assertion_ids=["ASSERT-NATIVE-SEMANTICS"],
        )
        cls._bind_evidence(
            contract["production_isolation"]["evidence"],
            evidence_type="production_isolation",
            subject_id="production_isolation",
            command=None,
            tuple_id=None,
            producer_run_id=producer,
            reviewer_run_id=reviewer,
            assertion_ids=["ASSERT-PRODUCTION-ISOLATION"],
        )
        cls._bind_completion_receipts(document)

    @classmethod
    def _bind_completion_receipts(
        cls,
        document: dict[str, Any],
    ) -> None:
        if document["profile"] not in {"full", "regulated"}:
            document["decision"]["qa_review_ref"] = None
            document["decision"]["completion_audit_ref"] = None
            return
        contract = cls.manifest["typed_completion_receipt_contract"]
        evidence_ids: set[str] = set()

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                if {
                    "evidence_id",
                    "artifact",
                    "contract_revision",
                } <= set(value):
                    evidence_ids.add(value["evidence_id"])
                for nested in value.values():
                    collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)

        collect(document)
        for field, receipt_type, actor in (
            ("qa_review_ref", "qa_review", document["roles"]["qa_run_id"]),
            (
                "completion_audit_ref",
                "completion_audit",
                document["roles"]["completion_auditor_run_id"],
            ),
        ):
            payload = {
                "schema_version": contract["schema_version"],
                "receipt_type": receipt_type,
                "bundle_id": document["bundle_id"],
                "bundle_revision": document["revision"],
                "actor_run_id": actor,
                "evidence_ids": sorted(evidence_ids),
                "completion_predicates": contract["completion_predicates"],
                "conclusion": contract["passing_conclusion"],
            }
            document["decision"][field] = cls._write_artifact(
                receipt_type
                + "-"
                + hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode("utf-8")
                ).hexdigest()
                + ".json",
                payload,
            )

    @classmethod
    def _bind_rust_na_approvals(
        cls,
        document: dict[str, Any],
    ) -> None:
        rust = document["rust_backend_contract"]
        for contract_type in ("async_contract", "persistence_contract"):
            contract = rust[contract_type]
            if contract.get("applicable") is not False:
                continue
            approval = contract["na_approval"]
            payload = {
                "schema_version": "goal-teams-desktop-approval-v1",
                "approval_type": "rust_contract_na",
                "bundle_id": document["bundle_id"],
                "bundle_revision": document["revision"],
                "contract_type": contract_type,
                "reason": approval["reason"],
                "approver_run_id": approval["approver_run_id"],
                "decision": "approved",
            }
            approval["artifact"] = cls._write_artifact(
                "rust-contract-na-"
                + contract_type
                + "-"
                + hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode("utf-8")
                ).hexdigest()
                + ".json",
                payload,
            )

    @classmethod
    def _refresh_evidence_artifact(
        cls,
        evidence: dict[str, Any],
        name: str,
    ) -> None:
        evidence["artifact"] = cls._write_artifact(
            name,
            {
                "schema_version": "goal-teams-desktop-evidence-v1",
                **{
                    key: value
                    for key, value in evidence.items()
                    if key != "artifact"
                },
            },
        )

    @classmethod
    def _make_na_document(
        cls,
        *,
        approver_run_id: str = "RUN-NA-APPROVER",
        receipt_mutation: tuple[str, Any] | None = None,
    ) -> dict[str, Any]:
        document = copy.deepcopy(cls.fixtures["base_document"])
        case = document["desktop_test_contract"]["cases"][0]
        run = document["desktop_test_contract"]["runs"][0]
        payload = {
            "schema_version": "goal-teams-desktop-approval-v1",
            "approval_type": "na",
            "bundle_id": document["bundle_id"],
            "bundle_revision": document["revision"],
            "case_id": case["case_id"],
            "approver_run_id": approver_run_id,
            "decision": "approved",
        }
        if receipt_mutation is not None:
            payload[receipt_mutation[0]] = receipt_mutation[1]
        case["required"] = False
        case["na_approval"] = {
            "reason": "Capability is absent under the approved product contract.",
            "artifact": cls._write_artifact(
                "na-approval-"
                + hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode("utf-8")
                ).hexdigest()
                + ".json",
                payload,
            ),
            "approver_run_id": approver_run_id,
        }
        run["status"] = "not_applicable"
        run["evidence"] = None
        cls._bind_completion_receipts(document)
        return document

    def _case(self, case_id: str, *, valid: bool) -> dict[str, Any]:
        key = "valid_cases" if valid else "invalid_cases"
        for case in self.fixtures[key]:
            if case["case_id"] == case_id:
                return case
        self.fail(f"missing fixture {case_id}")

    def _materialize(self, case: dict[str, Any]) -> dict[str, Any]:
        document = copy.deepcopy(self.fixtures["base_document"])
        for mutation in case.get("mutations", []):
            parts = mutation["path"].strip("/").split("/")
            target: Any = document
            for raw_part in parts[:-1]:
                part: Any = int(raw_part) if isinstance(target, list) else raw_part
                target = target[part]
            raw_leaf = parts[-1]
            leaf: Any = int(raw_leaf) if isinstance(target, list) else raw_leaf
            if mutation["op"] == "remove":
                if isinstance(target, list):
                    target.pop(leaf)
                else:
                    target.pop(leaf)
            elif mutation["op"] == "add" and isinstance(target, list):
                target.insert(leaf, copy.deepcopy(mutation["value"]))
            else:
                target[leaf] = copy.deepcopy(mutation["value"])
        self._bind_rust_na_approvals(document)
        return document

    def _validate(
        self,
        document: dict[str, Any],
        *,
        fixture_root: Path | None = ROOT,
    ) -> dict[str, Any]:
        result = self.validator.validate_document(
            document,
            fixture_root=fixture_root,
        )
        self.assertIsInstance(result, dict)
        self.assertLessEqual(
            {"ok", "error_code", "errors", "summary"},
            set(result),
        )
        return result

    def test_fixture_matrix_is_complete_and_non_duplicated(self) -> None:
        self.assertEqual(
            self.fixtures["schema_version"],
            "goal-teams-desktop-engineering-fixtures-v2.46",
        )
        all_cases = self.fixtures["valid_cases"] + self.fixtures["invalid_cases"]
        case_ids = [case["case_id"] for case in all_cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        required = {
            "V246-DESKTOP-FULL-MACOS-TAURI-REPLICA",
            "V246-DESKTOP-RUST-ONLY-LITE",
            "V246-DESKTOP-RUST-ONLY-REQUIRES-L3",
            "V246-DESKTOP-PRD-ONLY-SKIPS-HTML-BASELINE",
            "V246-DESKTOP-PRD-ONLY-SELF-APPROVED-BASELINE",
            "V246-DESKTOP-PRD-ONLY-NON-REPLICA-CHAIN",
            "V246-DESKTOP-ROUTE-MISSING-SOURCE-CONTRACT",
            "V246-DESKTOP-ROUTE-MISSING-TEST-CONTRACT",
            "V246-DESKTOP-REPLICA-BELOW-FULL",
            "V246-DESKTOP-PACKAGE-BELOW-FULL",
            "V246-DESKTOP-CROSS-PLATFORM-BELOW-FULL",
            "V246-DESKTOP-COVERAGE-NOT-100",
            "V246-DESKTOP-PIXEL-CHANGED-NONZERO",
            "V246-DESKTOP-PIXEL-TOLERANCE-NONZERO",
            "V246-DESKTOP-PIXEL-MASK-NONZERO",
            "V246-DESKTOP-HIGH-FIDELITY-NOT-PIXEL-EXACT",
            "V246-DESKTOP-NATIVE-SEMANTIC-INCOMPLETE",
            "V246-DESKTOP-CRATE-DAG-CYCLE",
            "V246-DESKTOP-ADAPTER-CROSSES-INFRASTRUCTURE",
            "V246-DESKTOP-IPC-MISSING-AUTHORIZATION",
            "V246-DESKTOP-IPC-MISSING-TIMEOUT",
            "V246-DESKTOP-IPC-MISSING-CANCELLATION",
            "V246-DESKTOP-RUST-GATE-MISSING",
            "V246-DESKTOP-RUST-COMMAND-WITHOUT-EVIDENCE",
            "V246-DESKTOP-MACOS-DIRECT-TAURI-DRIVER",
            "V246-DESKTOP-L2-MASQUERADES-AS-L3",
            "V246-DESKTOP-L4-EMBEDDED-CLAIMS-PRODUCTION-ISOLATION",
            "V246-DESKTOP-REQUIRED-CASE-BLOCKED",
            "V246-DESKTOP-REQUIRED-CASE-NOT-RUN",
            "V246-DESKTOP-REQUIRED-CASE-FLAKY",
            "V246-DESKTOP-REQUIRED-TUPLE-UNAVAILABLE",
            "V246-DESKTOP-OPTIONAL-NA-FORGED-APPROVAL",
            "V246-DESKTOP-OPTIONAL-NA-SELF-APPROVED",
            "V246-DESKTOP-L4-TEST-PLUGIN-LEAK",
            "V246-DESKTOP-L4-DEBUG-PORT-LEAK",
            "V246-DESKTOP-L4-MOCK-HOOK-LEAK",
            "V246-DESKTOP-L4-BROAD-CAPABILITY-LEAK",
            "V246-DESKTOP-RUNNER-SELF-REVIEW",
            "V246-DESKTOP-ARTIFACT-MISSING",
            "V246-DESKTOP-ARTIFACT-HASH-DRIFT",
            "V246-DESKTOP-GATE-COMMAND-TRUE",
            "V246-DESKTOP-FMT-COMMAND-MISSING-TOKENS",
            "V246-DESKTOP-CLIPPY-COMMAND-MISSING-TOKENS",
            "V246-DESKTOP-TEST-COMMAND-MISSING-TOKENS",
            "V246-DESKTOP-GATE-EVIDENCE-ZERO-BYTE",
            "V246-DESKTOP-GATE-EVIDENCE-ARBITRARY-JSON",
            "V246-DESKTOP-PIXEL-EVIDENCE-ZERO-BYTE",
            "V246-DESKTOP-PIXEL-EVIDENCE-ARBITRARY-JSON",
            "V246-DESKTOP-EVIDENCE-WRONG-TYPE",
            "V246-DESKTOP-EVIDENCE-FAILED-RESULT",
            "V246-DESKTOP-EVIDENCE-PRODUCER-IMPLEMENTER",
            "V246-DESKTOP-EVIDENCE-REVIEWER-UNBOUND",
            "V246-DESKTOP-EVIDENCE-WRONG-SUBJECT",
            "V246-DESKTOP-EVIDENCE-WRONG-COMMAND",
            "V246-DESKTOP-EVIDENCE-WRONG-TUPLE",
            "V246-DESKTOP-BASELINE-REVIEWER-UNBOUND",
            "V246-DESKTOP-BASELINE-REVIEWER-IMPLEMENTER",
            "V246-DESKTOP-BASELINE-APPROVAL-WRONG-BUNDLE",
            "V246-DESKTOP-NA-APPROVER-TEST-DESIGNER",
            "V246-DESKTOP-NA-APPROVAL-WRONG-BUNDLE",
            "V246-DESKTOP-NA-APPROVAL-WRONG-REVISION",
            "V246-DESKTOP-NA-APPROVAL-WRONG-CASE",
        }
        self.assertEqual(required, set(case_ids))

    def test_full_macos_tauri_replica_is_accepted(self) -> None:
        case = self._case(
            "V246-DESKTOP-FULL-MACOS-TAURI-REPLICA",
            valid=True,
        )
        result = self._validate(self._materialize(case))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["error_code"], "OK")
        for key, expected in case["expected_summary"].items():
            self.assertEqual(result["summary"].get(key), expected, result)

    def test_rust_only_lite_does_not_invent_desktop_l3(self) -> None:
        case = self._case("V246-DESKTOP-RUST-ONLY-LITE", valid=True)
        document = self._materialize(case)
        self.assertIsNone(document["desktop_test_contract"])
        self.assertIsNone(document["source_contract"])
        self.assertIsNone(document["ui_replica_contract"])
        self.assertEqual(
            document["rust_backend_contract"]["ipc_commands"],
            [],
        )
        self.assertFalse(
            document["rust_backend_contract"]["async_contract"][
                "applicable"
            ]
        )
        self.assertFalse(
            document["rust_backend_contract"]["persistence_contract"][
                "applicable"
            ]
        )
        result = self._validate(document)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["summary"]["required_platform_count"], 0)
        self.assertEqual(result["summary"]["required_case_count"], 0)

    def test_rust_contract_na_without_approval_fails_closed(self) -> None:
        document = self._materialize(
            self._case("V246-DESKTOP-RUST-ONLY-LITE", valid=True)
        )
        document["rust_backend_contract"]["async_contract"].pop(
            "na_approval"
        )
        result = self._validate(document)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["error_code"],
            "E_V246_DESKTOP_SCHEMA",
            result,
        )

    def test_rust_contract_na_forged_scope_fails_closed(self) -> None:
        document = self._materialize(
            self._case("V246-DESKTOP-RUST-ONLY-LITE", valid=True)
        )
        approval = document["rust_backend_contract"][
            "async_contract"
        ]["na_approval"]
        payload = {
            "schema_version": "goal-teams-desktop-approval-v1",
            "approval_type": "rust_contract_na",
            "bundle_id": document["bundle_id"],
            "bundle_revision": document["revision"],
            "contract_type": "persistence_contract",
            "reason": approval["reason"],
            "approver_run_id": approval["approver_run_id"],
            "decision": "approved",
        }
        approval["artifact"] = self._write_artifact(
            "rust-contract-na-forged-scope.json",
            payload,
        )
        result = self._validate(document)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["error_code"],
            "E_V246_DESKTOP_NA",
            result,
        )

    def test_rust_contract_na_self_approval_fails_closed(self) -> None:
        document = self._materialize(
            self._case("V246-DESKTOP-RUST-ONLY-LITE", valid=True)
        )
        approval = document["rust_backend_contract"][
            "persistence_contract"
        ]["na_approval"]
        approval["approver_run_id"] = document["roles"][
            "implementer_run_id"
        ]
        payload = {
            "schema_version": "goal-teams-desktop-approval-v1",
            "approval_type": "rust_contract_na",
            "bundle_id": document["bundle_id"],
            "bundle_revision": document["revision"],
            "contract_type": "persistence_contract",
            "reason": approval["reason"],
            "approver_run_id": approval["approver_run_id"],
            "decision": "approved",
        }
        approval["artifact"] = self._write_artifact(
            "rust-contract-na-self-approved.json",
            payload,
        )
        result = self._validate(document)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["error_code"],
            "E_V246_DESKTOP_NA",
            result,
        )

    def test_full_completion_audit_run_id_tamper_is_rejected(
        self,
    ) -> None:
        document = self._materialize(
            self._case(
                "V246-DESKTOP-FULL-MACOS-TAURI-REPLICA",
                valid=True,
            )
        )
        contract = self.manifest["typed_completion_receipt_contract"]
        payload = {
            "schema_version": contract["schema_version"],
            "receipt_type": "completion_audit",
            "bundle_id": document["bundle_id"],
            "bundle_revision": document["revision"],
            "actor_run_id": "RUN-FORGED-AUDITOR",
            "evidence_ids": sorted(
                evidence["evidence_id"]
                for evidence in self.validator._evidence_refs(document)
            ),
            "completion_predicates": contract["completion_predicates"],
            "conclusion": contract["passing_conclusion"],
        }
        document["decision"]["completion_audit_ref"] = (
            self._write_artifact(
                "completion-audit-forged-run-id.json",
                payload,
            )
        )
        result = self._validate(document)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["error_code"],
            "E_V246_DESKTOP_COMPLETION",
            result,
        )

    def test_failed_gate_cannot_project_not_run_outcome(self) -> None:
        document = self._materialize(
            self._case(
                "V246-DESKTOP-FULL-MACOS-TAURI-REPLICA",
                valid=True,
            )
        )
        gate = document["rust_backend_contract"]["gates"][0]
        gate["state"] = "failed"
        gate["evidence"]["result"] = "failed"
        self._refresh_evidence_artifact(
            gate["evidence"],
            "failed-gate-evidence.json",
        )
        document["decision"].update(
            {
                "run_outcome": "not_run",
                "contract_achieved": False,
                "reason_codes": ["RUST-GATE-FAILED"],
            }
        )
        result = self._validate(document)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["error_code"],
            "E_V246_DESKTOP_COMPLETION",
            result,
        )

    def test_all_negative_fixtures_fail_closed_with_stable_code(self) -> None:
        for case in self.fixtures["invalid_cases"]:
            with self.subTest(case_id=case["case_id"]):
                if case.get("execution_mode") in {
                    "typed_evidence",
                    "typed_approval",
                }:
                    continue
                result = self._validate(self._materialize(case))
                self.assertFalse(result["ok"], result)
                self.assertEqual(
                    result["error_code"],
                    case["expected_error_code"],
                    result,
                )
                self.assertIn(case["expected_error_code"], result["errors"])

    def test_typed_evidence_content_and_binding_fail_closed(self) -> None:
        cases = [
            case
            for case in self.fixtures["invalid_cases"]
            if case.get("execution_mode") == "typed_evidence"
        ]
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                document = self._materialize(case)
                if case["target"] == "pixel":
                    evidence = document["ui_replica_contract"][
                        "pixel_exact"
                    ][0]["evidence"]
                    gate = None
                elif case["target"] == "run":
                    run = document["desktop_test_contract"]["runs"][2]
                    evidence = run["evidence"]
                    gate = None
                else:
                    gate_index = {
                        "clippy_tokens": 1,
                        "test_tokens": 2,
                    }.get(case["mutation"], 0)
                    gate = document["rust_backend_contract"]["gates"][
                        gate_index
                    ]
                    evidence = gate["evidence"]
                mutation = case["mutation"]
                if mutation == "zero_byte":
                    evidence["artifact"] = self._write_artifact(
                        case["case_id"] + ".json",
                        b"",
                    )
                elif mutation == "arbitrary_json":
                    evidence["artifact"] = self._write_artifact(
                        case["case_id"] + ".json",
                        {"observed": "nothing typed or asserted"},
                    )
                else:
                    if mutation == "command_true":
                        gate["command"] = "true"
                        evidence["command"] = "true"
                    elif mutation == "fmt_tokens":
                        gate["command"] = "cargo fmt --all"
                        evidence["command"] = gate["command"]
                    elif mutation == "clippy_tokens":
                        gate["command"] = "cargo clippy --workspace"
                        evidence["command"] = gate["command"]
                    elif mutation == "test_tokens":
                        gate["command"] = "cargo test"
                        evidence["command"] = gate["command"]
                    elif mutation == "wrong_type":
                        evidence["evidence_type"] = "desktop_run"
                    elif mutation == "failed_result":
                        evidence["result"] = "failed"
                    elif mutation == "producer_implementer":
                        evidence["producer_run_id"] = document["roles"][
                            "implementer_run_id"
                        ]
                    elif mutation == "reviewer_unbound":
                        evidence["reviewer_run_id"] = "RUN-UNBOUND-REVIEWER"
                    elif mutation == "wrong_subject":
                        evidence["subject_id"] = "GATE-OTHER"
                    elif mutation == "wrong_command":
                        evidence["command"] = "cargo test"
                    elif mutation == "wrong_tuple":
                        evidence["tuple_id"] = "TUPLE-MACOS-14-ARM64"
                    elif mutation == "flaky_result":
                        run["status"] = "flaky"
                        evidence["result"] = "failed"
                    self._refresh_evidence_artifact(
                        evidence,
                        case["case_id"] + ".json",
                    )
                result = self._validate(document)
                self.assertFalse(result["ok"], result)
                self.assertEqual(
                    result["error_code"],
                    case["expected_error_code"],
                    result,
                )

    def test_typed_baseline_and_na_approvals_fail_closed(self) -> None:
        cases = [
            case
            for case in self.fixtures["invalid_cases"]
            if case.get("execution_mode") == "typed_approval"
        ]
        self.assertGreaterEqual(len(cases), 7)
        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                mutation = case["mutation"]
                if case["target"] == "na":
                    approver = (
                        "RUN-TEST-DESIGNER"
                        if mutation == "approver_designer"
                        else "RUN-NA-APPROVER"
                    )
                    receipt_mutation = {
                        "wrong_bundle": ("bundle_id", "BUNDLE-FORGED"),
                        "wrong_revision": ("bundle_revision", 999),
                        "wrong_case": ("case_id", "CASE-FORGED"),
                    }.get(mutation)
                    document = self._make_na_document(
                        approver_run_id=approver,
                        receipt_mutation=receipt_mutation,
                    )
                else:
                    document = self._materialize(case)
                    approval = document["source_contract"][
                        "baseline_approval"
                    ]
                    if mutation == "reviewer_unbound":
                        approval["reviewer_run_id"] = "RUN-UNBOUND-REVIEWER"
                    elif mutation == "reviewer_implementer":
                        approval["reviewer_run_id"] = document["roles"][
                            "implementer_run_id"
                        ]
                    payload = {
                        "schema_version": "goal-teams-desktop-approval-v1",
                        "approval_type": "baseline",
                        "bundle_id": (
                            "BUNDLE-FORGED"
                            if mutation == "wrong_bundle"
                            else document["bundle_id"]
                        ),
                        "bundle_revision": document["revision"],
                        "approval_id": approval["approval_id"],
                        "author_run_id": approval["author_run_id"],
                        "reviewer_run_id": approval["reviewer_run_id"],
                        "decision": approval["decision"],
                    }
                    approval["artifact"] = self._write_artifact(
                        case["case_id"] + ".json",
                        payload,
                    )
                result = self._validate(document)
                self.assertFalse(result["ok"], result)
                self.assertEqual(
                    result["error_code"],
                    case["expected_error_code"],
                    result,
                )

    def test_optional_na_with_typed_independent_approval_is_accepted(
        self,
    ) -> None:
        result = self._validate(self._make_na_document())
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["summary"]["contract_achieved"])

    def test_manifest_schema_and_route_derivation_are_machine_bound(self) -> None:
        self.assertEqual(
            self.manifest["schema"],
            "schemas/v2.46/desktop-engineering.schema.json",
        )
        self.assertEqual(
            self.manifest["validator"],
            "scripts/checks/validate-desktop-engineering.py",
        )
        self.assertEqual(
            self.schema["$id"].rsplit("/", 1)[-1],
            "desktop-engineering.schema.json",
        )
        derivation = {
            row["when"]: set(row["requires"])
            for row in self.manifest["requirement_derivation"]
        }
        self.assertEqual(
            derivation["rust=true"],
            {"rust_backend_contract", "L1", "rust_quality_gates"},
        )
        self.assertLessEqual(
            {"typed_ipc", "capability_denials", "L2", "L3"},
            derivation["tauri=true"],
        )
        self.assertLessEqual(
            {"L4", "production_package_isolation"},
            derivation["desktop_package=true"],
        )
        applicability = self.manifest["rust_contract_applicability"]
        self.assertEqual(
            set(applicability["contracts"]),
            {"async_contract", "persistence_contract"},
        )
        self.assertTrue(
            applicability[
                "not_applicable_requires_typed_independent_approval"
            ]
        )

    def test_full_fixture_has_complete_native_risk_and_level_denominators(
        self,
    ) -> None:
        document = self.fixtures["base_document"]
        contract = document["desktop_test_contract"]
        self.assertEqual(
            {case["risk_id"] for case in contract["cases"]},
            set(self.manifest["required_native_risks"]),
        )
        self.assertEqual(
            set(contract["required_evidence_levels"]),
            {"L1", "L2", "L3", "L4"},
        )
        required_tuples = {
            row["tuple_id"]
            for row in contract["platform_denominator"]
            if row["required"]
        }
        required_cases = {
            row["case_id"] for row in contract["cases"] if row["required"]
        }
        passed_pairs = {
            (row["case_id"], row["tuple_id"])
            for row in contract["runs"]
            if row["status"] == "passed"
        }
        self.assertLessEqual(
            {
                (case_id, tuple_id)
                for case_id in required_cases
                for tuple_id in required_tuples
            },
            passed_pairs,
        )

    def test_cli_accepts_valid_bundle_with_explicit_artifact_root(self) -> None:
        document = self._materialize(
            self._case(
                "V246-DESKTOP-FULL-MACOS-TAURI-REPLICA",
                valid=True,
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "desktop-bundle.json"
            path.write_text(
                json.dumps(document, ensure_ascii=False),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR_PATH),
                    "--input",
                    str(path),
                    "--fixture-root",
                    str(ROOT),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, (proc.stdout, proc.stderr))
        self.assertEqual(len(proc.stdout.strip().splitlines()), 1)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_cli_rejects_artifacts_without_a_trusted_root(self) -> None:
        document = self._materialize(
            self._case(
                "V246-DESKTOP-FULL-MACOS-TAURI-REPLICA",
                valid=True,
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "desktop-bundle.json"
            path.write_text(
                json.dumps(document, ensure_ascii=False),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR_PATH),
                    "--input",
                    str(path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(proc.returncode, 0, (proc.stdout, proc.stderr))
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["error_code"], "E_V246_DESKTOP_ARTIFACT")

    def test_validator_self_test_executes_both_polarities(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(VALIDATOR_PATH), "--self-test"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, (proc.stdout, proc.stderr))
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["passed"], payload)
        self.assertGreaterEqual(payload["valid_cases_executed"], 1)
        self.assertGreaterEqual(payload["invalid_cases_executed"], 1)


if __name__ == "__main__":
    unittest.main()
