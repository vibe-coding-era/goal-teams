from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = (
    ROOT / "scripts" / "checks" / "validate-verification-governance.py"
)
MANIFEST_PATH = ROOT / "references" / "verification-governance-manifest.json"
SCHEMA_PATH = ROOT / "schemas" / "v2.46" / "verification-governance.schema.json"
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "v23"
    / "fixtures"
    / "v246"
    / "verification-governance-cases.json"
)
V244_VALIDATOR_PATH = (
    ROOT / "scripts" / "checks" / "validate-test-case-contract.py"
)
RELEASE_SCHEMA_PATH = ROOT / "schemas" / "release-promotion-state.schema.json"
RELEASE_RUNTIME_PATH = ROOT / "scripts" / "release" / "release.py"
TEMP_ROOT = ROOT / "tests"
RELEASE_STATE_TEMP_ROOT = ROOT / "develops"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V246VerificationGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = _load_module(
            "_goalteams_v246_verification_governance_validator",
            VALIDATOR_PATH,
        )
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.release = _load_module(
            "_goalteams_v246_release_state_runtime",
            RELEASE_RUNTIME_PATH,
        )
        cls.release_state_temp_root_preexisting = (
            RELEASE_STATE_TEMP_ROOT.exists()
        )
        RELEASE_STATE_TEMP_ROOT.mkdir(exist_ok=True)
        cls.receipt_directory = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        cls.receipt_root = Path(cls.receipt_directory.name)
        acceptance_evidence_ids = ["EV-HISTORICAL-PASS-1"]
        predicates = {
            "required_checks_passed": True,
            "required_runs_achieved": True,
            "evidence_current_valid": True,
            "risk_denominator_closed": True,
        }
        cls.valid_review_receipt = {
            "schema_version": "goal-teams-v246-review-receipt-v1",
            "receipt_type": "independent_review",
            "bundle_id": "BUNDLE-V246-BASE",
            "bundle_revision": 1,
            "acceptance_evidence_ids": acceptance_evidence_ids,
            "actor_run_id": "RUN-CONTRACT-REVIEWER",
            "completion_predicates": predicates,
            "conclusion": "passed",
        }
        cls.valid_audit_receipt = {
            **cls.valid_review_receipt,
            "receipt_type": "completion_audit",
            "actor_run_id": "RUN-COMPLETION-AUDITOR",
        }
        review_ref = cls._write_receipt_artifact(
            "independent-review.json",
            cls.valid_review_receipt,
        )
        audit_ref = cls._write_receipt_artifact(
            "completion-audit.json",
            cls.valid_audit_receipt,
        )
        cls.default_review_ref = review_ref
        cls.default_audit_ref = audit_ref
        projection = cls.fixtures["base_document"]["acceptance_projection"]
        projection["independent_review_refs"] = [review_ref]
        projection["completion_audit_refs"] = [audit_ref]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.receipt_directory.cleanup()
        if not cls.release_state_temp_root_preexisting:
            RELEASE_STATE_TEMP_ROOT.rmdir()

    def test_v246_tests_do_not_require_ignored_docs_directory(self) -> None:
        ignored_docs_temp_root = "dir=ROOT" + ' / "docs"'
        for name in (
            "test_v246_verification_governance.py",
            "test_v246_desktop_engineering.py",
        ):
            source = (ROOT / "tests" / "v23" / name).read_text(
                encoding="utf-8"
            )
            self.assertNotIn(ignored_docs_temp_root, source)

    @classmethod
    def _write_receipt_artifact(
        cls,
        name: str,
        document: dict[str, Any] | None,
    ) -> dict[str, str]:
        path = cls.receipt_root / name
        if document is None:
            path.write_bytes(b"")
        else:
            path.write_text(
                json.dumps(
                    document,
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
        self.assertIn("ok", result)
        self.assertIn("error_code", result)
        self.assertIn("errors", result)
        self.assertIn("summary", result)
        return result

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
            else:
                target[leaf] = copy.deepcopy(mutation["value"])
        task_completion_contract = self.manifest[
            "task_completion_receipt_contract"
        ]
        for transition in document["transition_receipts"]:
            if (
                transition["machine_id"] == "task_lifecycle"
                and transition["to_state"] == "accepted"
            ):
                transition.setdefault(
                    "executor_run_id",
                    "RUN-HISTORICAL-EXECUTOR",
                )
                receipt = {
                    "schema_version": task_completion_contract[
                        "schema_version"
                    ],
                    "receipt_type": task_completion_contract["receipt_type"],
                    "bundle_id": document["bundle_id"],
                    "bundle_revision": document["revision"],
                    "task_id": transition["entity_id"],
                    "executor_run_id": transition["executor_run_id"],
                    "auditor_run_id": transition["actor_run_id"],
                    "evidence_ids": list(transition["evidence_refs"]),
                    "completion_predicates": task_completion_contract[
                        "completion_predicates"
                    ],
                    "conclusion": task_completion_contract[
                        "passing_conclusion"
                    ],
                }
                transition["completion_audit_ref"] = (
                    self._write_receipt_artifact(
                        "task-completion-"
                        + hashlib.sha256(
                            json.dumps(receipt, sort_keys=True).encode(
                                "utf-8"
                            )
                        ).hexdigest()
                        + ".json",
                        receipt,
                    )
                )
        projection = document["acceptance_projection"]
        if projection["independent_review_refs"] == [self.default_review_ref]:
            review = copy.deepcopy(self.valid_review_receipt)
            review["bundle_id"] = document["bundle_id"]
            review["bundle_revision"] = document["revision"]
            review["acceptance_evidence_ids"] = list(
                projection["acceptance_evidence_ids"]
            )
            projection["independent_review_refs"] = [
                self._write_receipt_artifact(
                    "independent-review-"
                    + hashlib.sha256(
                        json.dumps(review, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    + ".json",
                    review,
                )
            ]
        if projection["completion_audit_refs"] == [self.default_audit_ref]:
            audit = copy.deepcopy(self.valid_audit_receipt)
            audit["bundle_id"] = document["bundle_id"]
            audit["bundle_revision"] = document["revision"]
            audit["acceptance_evidence_ids"] = list(
                projection["acceptance_evidence_ids"]
            )
            projection["completion_audit_refs"] = [
                self._write_receipt_artifact(
                    "completion-audit-"
                    + hashlib.sha256(
                        json.dumps(audit, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    + ".json",
                    audit,
                )
            ]
        return document

    def _rewrite_task_completion_receipt(
        self,
        document: dict[str, Any],
        transition: dict[str, Any],
    ) -> None:
        contract = self.manifest["task_completion_receipt_contract"]
        payload = {
            "schema_version": contract["schema_version"],
            "receipt_type": contract["receipt_type"],
            "bundle_id": document["bundle_id"],
            "bundle_revision": document["revision"],
            "task_id": transition["entity_id"],
            "executor_run_id": transition["executor_run_id"],
            "auditor_run_id": transition["actor_run_id"],
            "evidence_ids": list(transition["evidence_refs"]),
            "completion_predicates": contract["completion_predicates"],
            "conclusion": contract["passing_conclusion"],
        }
        transition["completion_audit_ref"] = self._write_receipt_artifact(
            "task-completion-rewrite-"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            + ".json",
            payload,
        )

    def _valid_case(self, case_id: str) -> dict[str, Any]:
        for case in self.fixtures["valid_cases"]:
            if case["case_id"] == case_id:
                return case
        self.fail(f"missing valid fixture {case_id}")

    def _invalid_case(self, case_id: str) -> dict[str, Any]:
        for case in self.fixtures["invalid_cases"]:
            if case["case_id"] == case_id:
                return case
        self.fail(f"missing invalid fixture {case_id}")

    def test_fixture_is_a_complete_non_duplicated_regression_matrix(self) -> None:
        self.assertEqual(
            self.fixtures["schema_version"],
            "goal-teams-verification-governance-fixtures-v2.46",
        )
        all_cases = self.fixtures["valid_cases"] + self.fixtures["invalid_cases"]
        case_ids = [case["case_id"] for case in all_cases]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        required = {
            "V246-UNAFFECTED-HISTORY-PRESERVED",
            "V246-AFFECTED-STALE-RETEST",
            "V246-AFFECTED-RETEST-NEW-EVIDENCE-CURRENT",
            "V246-NEW-REQUIREMENT-NOT-RUN",
            "V246-ACTUAL-EXECUTION-FAILED",
            "V246-FORGED-EVIDENCE-INVALID",
            "V246-UNDETERMINED-BLOCKS-NOT-CLEARS",
            "V246-FULL-REGRESSION-PRESERVES-HISTORY",
            "V246-UNAPPROVED-SCOPE-EXPANSION",
            "V246-CHECK-RETRY-FLAKY",
            "V246-TRANSITION-CHAIN-CAS-CONFLICT",
            "V246-ACCEPTED-SUCCESSOR",
            "V246-SUCCESSOR-WITHOUT-ACCEPTED-PREDECESSOR",
            "V246-SIDE-EFFECT-RECONCILIATION",
            "V246-GRILL-WITHOUT-EVIDENCE",
            "V246-NA-WITHOUT-INDEPENDENT-ACCEPTANCE",
            "V246-ADVERSARIAL-RISK-SELF-REVIEW",
            "V246-DIRECT-ACTOR-ACHIEVED",
            "V246-SCHEMA-UNKNOWN-NESTED-FIELD",
            "V246-SCHEMA-MISSING-NESTED-REQUIRED",
            "V246-CONTRACT-MISSING-PASS-THRESHOLDS",
            "V246-BAD-GENERATED-AT",
            "V246-GRILL-FAKE-EVIDENCE",
            "V246-RISK-FAKE-EVIDENCE",
            "V246-FULL-MISSING-QA",
            "V246-FULL-INCOMPLETE-RISK-CATALOG",
            "V246-ARBITRARY-TRANSITION-EVENT",
            "V246-FIRST-RECEIPT-NONINITIAL-REVISION",
            "V246-FORGED-REVIEW-AUDIT-REFS",
            "V246-ARTIFACT-REF-MISSING-SHA",
            "V246-PROFILE-CONTRACT-DRIFT",
            "V246-EMPTY-CHAINS-CLAIM-ACHIEVED",
            "V246-REQUIRED-RISK-FAKE-NA-APPROVAL",
            "V246-ACHIEVED-WITHOUT-TRUSTED-ARTIFACT-ROOT",
            "V246-ACHIEVED-WITH-MISSING-ARTIFACT",
            "V246-SAME-EVIDENCE-STALE-THEN-CURRENT",
            "V246-PREVIOUS-BUNDLE-HISTORY-DELETION",
            "V246-PREVIOUS-BUNDLE-APPLICABILITY-REWRITE",
            "V246-PREVIOUS-BUNDLE-TRANSITION-REWRITE",
            "V246-PREVIOUS-BUNDLE-CONTRACT-REWRITE",
            "V246-OPTIONAL-RISK-FAKE-NA-APPROVAL",
            "V246-IMPACT-ITEM-BORROWS-OTHER-EVIDENCE-EVENT",
            "V246-CONTRACT-FOREIGN-AC",
            "V246-UNACCEPTABLE-RISK-OUTSIDE-DENOMINATOR",
            "V246-ARBITRARY-PASS-THRESHOLDS",
            "V246-ALLOW-ANYTHING-WAIVER",
            "V246-SKIP-SPEC-CHANGE-POLICY",
            "V246-FULL-MISSING-COMPLETION-AUDITOR",
            "V246-FULL-COMPLETE-CONTRACT",
            "V246-OPTIONAL-RISK-NA-WITH-INDEPENDENT-APPROVAL",
            "V246-GRILL-NA-WITH-INDEPENDENT-APPROVAL",
            "V246-REQUIRED-CHECK-WAIVED-CLAIMS-ACHIEVED",
            "V246-REQUIRED-CHECK-NOT-REQUIRED-CLAIMS-ACHIEVED",
            "V246-RUN-RUNNING-CLAIMS-ACHIEVED",
            "V246-GRILL-FOREIGN-BASIS",
            "V246-GRILL-FORGED-VERSION-ENVIRONMENT",
            "V246-GRILL-RESIDUAL-RISK-OUTSIDE-CONTRACT",
            "V246-REVIEW-RECEIPT-ZERO-BYTE",
            "V246-REVIEW-RECEIPT-WRONG-TYPE",
            "V246-REVIEW-RECEIPT-WRONG-BUNDLE",
            "V246-AUDIT-RECEIPT-WRONG-REVISION",
            "V246-AUDIT-RECEIPT-WRONG-EVIDENCE-SET",
            "V246-REVIEW-RECEIPT-SELF-REVIEW",
            "V246-AUDIT-RECEIPT-SELF-AUDIT",
            "V246-AUDIT-RECEIPT-NON-PASSED",
            "V246-V244-REPLAY",
        }
        self.assertEqual(required - set(case_ids), set())

    def test_all_declared_state_machine_states_are_reachable(self) -> None:
        for machine_id, machine in self.manifest["state_machines"].items():
            with self.subTest(machine_id=machine_id):
                initial = machine["initial"]
                transitions = machine["transitions"]
                reached = {initial}
                pending = deque([initial])
                while pending:
                    source = pending.popleft()
                    for target in transitions[source]:
                        if target not in reached:
                            reached.add(target)
                            pending.append(target)
                self.assertEqual(set(machine["states"]) - reached, set())
                self.assertEqual(set(transitions), set(machine["states"]))
                for targets in transitions.values():
                    self.assertLessEqual(set(targets), set(machine["states"]))

    def test_valid_impact_and_state_scenarios(self) -> None:
        case_ids = (
            "V246-UNAFFECTED-HISTORY-PRESERVED",
            "V246-AFFECTED-STALE-RETEST",
            "V246-AFFECTED-RETEST-NEW-EVIDENCE-CURRENT",
            "V246-NEW-REQUIREMENT-NOT-RUN",
            "V246-ACTUAL-EXECUTION-FAILED",
            "V246-FORGED-EVIDENCE-INVALID",
            "V246-UNDETERMINED-BLOCKS-NOT-CLEARS",
            "V246-FULL-REGRESSION-PRESERVES-HISTORY",
            "V246-CHECK-RETRY-FLAKY",
            "V246-ACCEPTED-SUCCESSOR",
            "V246-SIDE-EFFECT-RECONCILIATION",
            "V246-FULL-COMPLETE-CONTRACT",
            "V246-OPTIONAL-RISK-NA-WITH-INDEPENDENT-APPROVAL",
            "V246-GRILL-NA-WITH-INDEPENDENT-APPROVAL",
            "V246-V244-REPLAY",
        )
        for case_id in case_ids:
            with self.subTest(case_id=case_id):
                case = self._valid_case(case_id)
                result = self._validate(self._materialize(case))
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["error_code"], "OK")
                for key, expected in case.get("expected_summary", {}).items():
                    self.assertEqual(result["summary"].get(key), expected, result)

    def test_unapproved_scope_expansion_is_rejected(self) -> None:
        case = self._invalid_case("V246-UNAPPROVED-SCOPE-EXPANSION")
        result = self._validate(self._materialize(case))
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V246_SCOPE_APPROVAL")

    def test_grill_claim_without_evidence_is_rejected(self) -> None:
        case = self._invalid_case("V246-GRILL-WITHOUT-EVIDENCE")
        result = self._validate(self._materialize(case))
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V246_GRILL_EVIDENCE")

    def test_achieved_grill_and_risk_reject_stale_evidence(self) -> None:
        case = self._valid_case(
            "V246-AFFECTED-RETEST-NEW-EVIDENCE-CURRENT"
        )
        for target, expected_error in (
            ("grill", "E_V246_GRILL_EVIDENCE"),
            ("risk", "E_V246_RISK_EVIDENCE"),
        ):
            with self.subTest(target=target):
                document = self._materialize(case)
                document["verification_contracts"][0]["traceability"][0][
                    "evidence_ids"
                ].append("EV-HISTORICAL-PASS-1")
                if target == "grill":
                    document["grill_reviews"][0]["evidence_refs"] = [
                        "EV-HISTORICAL-PASS-1"
                    ]
                else:
                    document["adversarial_risks"][0]["evidence_refs"] = [
                        "EV-HISTORICAL-PASS-1"
                    ]
                result = self._validate(document)
                self.assertFalse(result["ok"], result)
                self.assertEqual(
                    result["error_code"],
                    expected_error,
                    result,
                )

    def test_risk_grill_and_transition_orphan_evidence_is_rejected(
        self,
    ) -> None:
        mutations = (
            ("risk", "/adversarial_risks/0/evidence_refs"),
            ("grill", "/grill_reviews/0/evidence_refs"),
            ("transition", "/transition_receipts/0/evidence_refs"),
        )
        for label, path in mutations:
            with self.subTest(target=label):
                document = self._materialize(
                    self._valid_case(
                        "V246-UNAFFECTED-HISTORY-PRESERVED"
                    )
                )
                document["historical_evidence_ids"].append(
                    f"EV-ORPHAN-{label.upper()}"
                )
                target: Any = document
                for part in path.strip("/").split("/")[:-1]:
                    target = target[
                        int(part) if isinstance(target, list) else part
                    ]
                target[path.rsplit("/", 1)[-1]] = [
                    f"EV-ORPHAN-{label.upper()}"
                ]
                result = self._validate(document)
                self.assertFalse(result["ok"], result)
                self.assertEqual(
                    result["error_code"],
                    "E_V246_TRACEABILITY",
                    result,
                )

    def test_task_executor_cannot_self_accept_with_a_typed_receipt(
        self,
    ) -> None:
        document = self._materialize(
            self._valid_case("V246-ACCEPTED-SUCCESSOR")
        )
        accepted = document["transition_receipts"][0]
        accepted["executor_run_id"] = accepted["actor_run_id"]
        self._rewrite_task_completion_receipt(document, accepted)
        result = self._validate(document)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["error_code"],
            "E_V246_AUDIT_RECEIPT",
            result,
        )

    def test_na_without_independent_acceptance_is_rejected(self) -> None:
        case = self._invalid_case(
            "V246-NA-WITHOUT-INDEPENDENT-ACCEPTANCE"
        )
        result = self._validate(self._materialize(case))
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error_code"], "E_V246_GRILL_NA")

    def test_all_negative_fixtures_fail_closed_with_stable_code(self) -> None:
        for case in self.fixtures["invalid_cases"]:
            with self.subTest(case_id=case["case_id"]):
                if case.get("execution_mode") in {
                    "previous_bundle",
                    "typed_receipt",
                }:
                    continue
                fixture_root = (
                    None
                    if case.get("fixture_root_mode") == "none"
                    else ROOT
                )
                result = self._validate(
                    self._materialize(case),
                    fixture_root=fixture_root,
                )
                self.assertFalse(result["ok"], result)
                self.assertEqual(
                    result["error_code"],
                    case["expected_error_code"],
                    result,
                )
                self.assertIn(case["expected_error_code"], result["errors"])

    def test_typed_review_and_audit_receipts_fail_closed(self) -> None:
        mutation_map = {
            "wrong_type": ("receipt_type", "completion_audit"),
            "wrong_bundle": ("bundle_id", "BUNDLE-FORGED"),
            "wrong_revision": ("bundle_revision", 999),
            "wrong_evidence": (
                "acceptance_evidence_ids",
                ["EV-FORGED"],
            ),
            "self_actor": ("actor_run_id", "RUN-TEST-RUNNER"),
            "non_passed": ("conclusion", "failed"),
        }
        cases = [
            case
            for case in self.fixtures["invalid_cases"]
            if case.get("execution_mode") == "typed_receipt"
        ]
        self.assertGreaterEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                document = self._materialize(case)
                target = case["receipt_target"]
                if target == "review":
                    receipt = copy.deepcopy(self.valid_review_receipt)
                    field = "independent_review_refs"
                else:
                    receipt = copy.deepcopy(self.valid_audit_receipt)
                    field = "completion_audit_refs"
                if case["receipt_mutation"] == "zero_byte":
                    receipt_ref = self._write_receipt_artifact(
                        case["case_id"] + ".json",
                        None,
                    )
                else:
                    key, value = mutation_map[case["receipt_mutation"]]
                    receipt[key] = value
                    receipt_ref = self._write_receipt_artifact(
                        case["case_id"] + ".json",
                        receipt,
                    )
                document["acceptance_projection"][field] = [receipt_ref]
                result = self._validate(document)
                self.assertFalse(result["ok"], result)
                self.assertEqual(
                    result["error_code"],
                    case["expected_error_code"],
                    result,
                )

    def test_previous_bundle_binding_rejects_baseline_and_history_deletion(
        self,
    ) -> None:
        case = self._invalid_case(
            "V246-PREVIOUS-BUNDLE-HISTORY-DELETION"
        )
        previous = copy.deepcopy(self.fixtures["base_document"])
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            previous_path = Path(directory) / "previous-bundle.json"
            previous_path.write_text(
                json.dumps(
                    previous,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            current = copy.deepcopy(previous)
            current["bundle_id"] = "BUNDLE-V246-REVISION-2"
            current["revision"] = 2
            current["previous_bundle_ref"] = {
                "path": previous_path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(
                    previous_path.read_bytes()
                ).hexdigest(),
            }
            current["history_baseline_evidence_ids"] = []
            current["historical_evidence_ids"] = []
            result = self._validate(current, fixture_root=ROOT)
        self.assertFalse(result["ok"], result)
        self.assertEqual(
            result["error_code"],
            case["expected_error_code"],
            result,
        )

    def test_previous_bundle_binding_rejects_historical_prefix_rewrites(
        self,
    ) -> None:
        cases = {
            "V246-PREVIOUS-BUNDLE-APPLICABILITY-REWRITE": (
                "evidence_applicability_events",
                [],
            ),
            "V246-PREVIOUS-BUNDLE-TRANSITION-REWRITE": (
                "transition_receipts",
                [],
            ),
            "V246-PREVIOUS-BUNDLE-CONTRACT-REWRITE": (
                "verification_contracts",
                [],
            ),
        }
        previous = copy.deepcopy(self.fixtures["base_document"])
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            previous_path = Path(directory) / "previous-bundle.json"
            previous_path.write_text(
                json.dumps(
                    previous,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            previous_ref = {
                "path": previous_path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(
                    previous_path.read_bytes()
                ).hexdigest(),
            }
            for case_id, (field, replacement) in cases.items():
                with self.subTest(case_id=case_id):
                    case = self._invalid_case(case_id)
                    current = copy.deepcopy(previous)
                    current["bundle_id"] = f"{case_id}-REVISION-2"
                    current["revision"] = 2
                    current["previous_bundle_ref"] = previous_ref
                    current[field] = copy.deepcopy(replacement)
                    result = self._validate(current, fixture_root=ROOT)
                    self.assertFalse(result["ok"], result)
                    self.assertEqual(
                        result["error_code"],
                        case["expected_error_code"],
                        result,
                    )

    def test_bundle_never_uses_one_generic_status_for_orthogonal_domains(
        self,
    ) -> None:
        for case in self.fixtures["valid_cases"]:
            document = self._materialize(case)
            self.assertNotIn("status", document, case["case_id"])
            for receipt in document["transition_receipts"]:
                self.assertIn(
                    receipt["machine_id"],
                    self.manifest["state_machines"],
                    case["case_id"],
                )
                self.assertIn("from_state", receipt)
                self.assertIn("to_state", receipt)

    def test_cli_validates_one_bundle_and_emits_one_json_line(self) -> None:
        case = self._valid_case("V246-AFFECTED-STALE-RETEST")
        document = self._materialize(case)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
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

    def test_cli_rejects_artifact_bearing_achieved_without_trusted_root(
        self,
    ) -> None:
        case = self._valid_case("V246-UNAFFECTED-HISTORY-PRESERVED")
        document = self._materialize(case)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
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
        self.assertEqual(payload["error_code"], "E_V246_ARTIFACT")

    def test_cli_rejects_forged_artifact_digest_with_trusted_root(
        self,
    ) -> None:
        case = self._invalid_case("V246-FORGED-REVIEW-AUDIT-REFS")
        document = self._materialize(case)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
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
        self.assertNotEqual(proc.returncode, 0, (proc.stdout, proc.stderr))
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["error_code"], "E_V246_ARTIFACT")

    def test_validator_self_test_executes_positive_and_negative_cases(
        self,
    ) -> None:
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

    def test_schema_and_manifest_are_part_of_the_validator_contract(self) -> None:
        self.assertTrue(SCHEMA_PATH.is_file())
        self.assertEqual(
            self.manifest["schema"],
            "schemas/v2.46/verification-governance.schema.json",
        )
        self.assertEqual(
            self.manifest["validator"],
            "scripts/checks/validate-verification-governance.py",
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["$id"].rsplit("/", 1)[-1],
            "verification-governance.schema.json",
        )

    def test_release_checkpoint_state_machine_is_the_machine_ssot(self) -> None:
        schema = json.loads(RELEASE_SCHEMA_PATH.read_text(encoding="utf-8"))
        machine = self.manifest["state_machines"]["release_checkpoint"]
        self.assertEqual(schema["x-transition-map"], machine["transitions"])
        self.assertEqual(
            set(schema["properties"]["checkpoint_phase"]["enum"]),
            set(machine["states"]),
        )
        self.assertLessEqual(
            {
                "state_revision",
                "release_transition_receipts",
                "recovery_revision",
                "recovery_transition_receipts",
            },
            set(schema["required"]),
        )
        orthogonal = schema["x-v246-orthogonal-state"]
        self.assertEqual(
            orthogonal["authoritative_release_state"],
            "checkpoint_phase",
        )
        self.assertEqual(orthogonal["compatibility_phase"], "projection_only")
        recovery_binding = self.manifest["state_machines"]["recovery"][
            "binding"
        ]
        self.assertTrue(recovery_binding["release_runtime_field"])
        self.assertEqual(
            recovery_binding["revision_field"], "recovery_revision"
        )
        self.assertEqual(
            recovery_binding["receipt_field"],
            "recovery_transition_receipts",
        )
        self.assertTrue(recovery_binding["direct_state_write_forbidden"])

    def test_release_transition_receipt_enforces_cas_and_legacy_projection(
        self,
    ) -> None:
        state = {
            "repository": "vibe-coding-era/goal-teams",
            "version": "V2.46",
            "phase": "DRIFTED",
            "checkpoint_phase": "DRIFTED",
            "external_surface_phase": "absent",
            "recovery_state": "none",
            "reconciliation": None,
            "resume_checkpoint_phase": None,
            "state_revision": 0,
            "release_transition_receipts": [],
            "recovery_revision": 0,
            "recovery_transition_receipts": [],
        }
        receipt = self.release._append_release_transition(
            state,
            to_state="RECOVERED",
            event="release_checkpoint.DRIFTED.RECOVERED",
            actor_run_id="RUN-RELEASE-ENGINEER",
            reason_code="EXACT_RECOVERY_READBACK",
            evidence_refs=["EV-RELEASE-READBACK-1"],
            idempotency_key="1" * 64,
            expected_revision=0,
        )
        self.assertEqual(state["checkpoint_phase"], "RECOVERED")
        self.assertEqual(state["phase"], "DRIFTED")
        self.assertEqual(state["state_revision"], 1)
        self.assertEqual(receipt["from_state"], "DRIFTED")
        self.assertEqual(receipt["to_state"], "RECOVERED")
        self.assertEqual(receipt["expected_revision"], 0)
        self.assertEqual(receipt["new_revision"], 1)
        self.assertEqual(state["release_transition_receipts"], [receipt])

        frozen = copy.deepcopy(state)
        with self.assertRaises(self.release.PolicyError):
            self.release._append_release_transition(
                state,
                to_state="DEV_OPEN",
                event="release_checkpoint.RECOVERED.DEV_OPEN",
                actor_run_id="RUN-RELEASE-ENGINEER",
                reason_code="STALE_CAS",
                evidence_refs=["EV-RELEASE-READBACK-2"],
                idempotency_key="2" * 64,
                expected_revision=0,
            )
        self.assertEqual(state, frozen)

    def test_recovery_machine_requires_receipt_chain_revision_cas_and_idempotency(
        self,
    ) -> None:
        state = {
            "repository": "vibe-coding-era/goal-teams",
            "version": "V2.46",
            "recovery_state": "none",
            "recovery_revision": 0,
            "recovery_transition_receipts": [],
        }
        transitions = (
            ("reconciliation_required", "UNCERTAIN", "1" * 64),
            ("recovering", "RECOVERY_STARTED", "2" * 64),
            ("recovered", "EXACT_READBACK", "3" * 64),
            ("none", "RECOVERY_SETTLED", "4" * 64),
        )
        for target, reason, key in transitions:
            source = state["recovery_state"]
            receipt = self.release._append_recovery_transition(
                state,
                to_state=target,
                event=f"recovery.{source}.{target}",
                actor_run_id="RUN-RECONCILER",
                reason_code=reason,
                evidence_refs=[f"EV-{reason}"],
                idempotency_key=key,
                expected_revision=state["recovery_revision"],
            )
            self.assertEqual(receipt["from_state"], source)
            self.assertEqual(receipt["to_state"], target)
        self.assertEqual(state["recovery_state"], "none")
        self.assertEqual(state["recovery_revision"], 4)
        self.release._validate_recovery_transition_ledger(state)

        for mutation, expected_code in (
            (
                lambda candidate: candidate.update(
                    {"recovery_state": "recovering"}
                ),
                "E_V246_RECOVERY_TRANSITION",
            ),
            (
                lambda candidate: candidate.update(
                    {"recovery_revision": 3}
                ),
                "E_V246_RECOVERY_TRANSITION_CAS",
            ),
            (
                lambda candidate: candidate[
                    "recovery_transition_receipts"
                ][-1].update({"idempotency_key": "1" * 64}),
                "E_V246_RECOVERY_TRANSITION",
            ),
        ):
            candidate = copy.deepcopy(state)
            mutation(candidate)
            with self.assertRaises(self.release.PolicyError) as caught:
                self.release._validate_recovery_transition_ledger(candidate)
            self.assertEqual(
                caught.exception.receipt["error_code"], expected_code
            )

        frozen = copy.deepcopy(state)
        with self.assertRaises(self.release.PolicyError) as caught:
            self.release._append_recovery_transition(
                state,
                to_state="reconciliation_required",
                event="recovery.none.reconciliation_required",
                actor_run_id="RUN-RECONCILER",
                reason_code="STALE_CAS",
                evidence_refs=["EV-STALE"],
                idempotency_key="5" * 64,
                expected_revision=3,
            )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V246_RECOVERY_TRANSITION_CAS",
        )
        self.assertEqual(state, frozen)

        with self.assertRaises(self.release.PolicyError) as caught:
            self.release._append_recovery_transition(
                state,
                to_state="reconciliation_required",
                event="recovery.none.reconciliation_required",
                actor_run_id="RUN-RECONCILER",
                reason_code="REPLAY",
                evidence_refs=["EV-REPLAY"],
                idempotency_key="1" * 64,
                expected_revision=4,
            )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V246_RECOVERY_TRANSITION_CAS",
        )
        self.assertEqual(state, frozen)

        with self.assertRaises(self.release.PolicyError) as caught:
            self.release._append_recovery_transition(
                state,
                to_state="recovered",
                event="recovery.none.recovered",
                actor_run_id="RUN-RECONCILER",
                reason_code="SHORTCUT",
                evidence_refs=["EV-SHORTCUT"],
                idempotency_key="6" * 64,
                expected_revision=4,
            )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V246_RECOVERY_TRANSITION",
        )
        self.assertEqual(state, frozen)

    def test_release_runtime_cannot_write_recovery_state_outside_transition(
        self,
    ) -> None:
        tree = ast.parse(RELEASE_RUNTIME_PATH.read_text(encoding="utf-8"))
        owners: list[str] = []

        class RecoveryAssignmentVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.function_stack: list[str] = []

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self.function_stack.append(node.name)
                self.generic_visit(node)
                self.function_stack.pop()

            def visit_Assign(self, node: ast.Assign) -> None:
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "state"
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "recovery_state"
                    ):
                        owners.append(
                            self.function_stack[-1]
                            if self.function_stack
                            else "<module>"
                        )
                self.generic_visit(node)

        RecoveryAssignmentVisitor().visit(tree)
        self.assertEqual(owners, ["_append_recovery_transition"])

    def test_cp00_through_cp18_release_phase_sequence_is_executable(
        self,
    ) -> None:
        schema = json.loads(RELEASE_SCHEMA_PATH.read_text(encoding="utf-8"))
        phase_map = schema["x-semantic-validator"][
            "checkpoint_phase_after_pass"
        ]
        state = {
            "repository": "vibe-coding-era/goal-teams",
            "version": "V2.46",
            "phase": "DRIFTED",
            "checkpoint_phase": "DRIFTED",
            "external_surface_phase": "absent",
            "recovery_state": "none",
            "reconciliation": None,
            "resume_checkpoint_phase": None,
            "state_revision": 0,
            "release_transition_receipts": [],
            "recovery_revision": 0,
            "recovery_transition_receipts": [],
        }
        for checkpoint_id, target in phase_map.items():
            source = state["checkpoint_phase"]
            if source == target:
                continue
            receipt = self.release._append_release_transition(
                state,
                to_state=target,
                event=f"release_checkpoint.{source}.{target}",
                actor_run_id="RUN-RELEASE-ENGINEER",
                reason_code=f"{checkpoint_id}_PASSED",
                evidence_refs=[f"EV-{checkpoint_id}"],
                idempotency_key=hashlib.sha256(
                    checkpoint_id.encode("utf-8")
                ).hexdigest(),
                expected_revision=state["state_revision"],
            )
            self.assertEqual(receipt["from_state"], source)
            self.assertEqual(receipt["to_state"], target)
        self.assertEqual(state["checkpoint_phase"], "CLOSED")
        transition_count = sum(
            left != right
            for left, right in zip(
                ["DRIFTED", *list(phase_map.values())[:-1]],
                phase_map.values(),
            )
        )
        self.assertEqual(state["state_revision"], transition_count)
        self.assertEqual(
            len(state["release_transition_receipts"]),
            transition_count,
        )

    def test_release_transition_rejects_undeclared_event_self_loop_and_recovery_shortcut(
        self,
    ) -> None:
        def state_at(value: str) -> dict[str, Any]:
            return {
                "repository": "vibe-coding-era/goal-teams",
                "version": "V2.46",
                "phase": "DEV_OPEN",
                "checkpoint_phase": value,
                "external_surface_phase": "absent",
                "recovery_state": "none",
                "reconciliation": None,
                "resume_checkpoint_phase": (
                    "DEV_OPEN" if value == "FAILED" else None
                ),
                "state_revision": 0,
                "release_transition_receipts": [],
                "recovery_revision": 0,
                "recovery_transition_receipts": [],
            }

        with self.assertRaises(self.release.PolicyError):
            self.release._append_release_transition(
                state_at("DRIFTED"),
                to_state="RECOVERED",
                event="arbitrary_release_event",
                actor_run_id="RUN-RELEASE-ENGINEER",
                reason_code="UNDECLARED_EVENT",
                evidence_refs=["EV-RELEASE-1"],
                idempotency_key="6" * 64,
                expected_revision=0,
            )
        with self.assertRaises(self.release.PolicyError):
            self.release._append_release_transition(
                state_at("TAG_PUSHED"),
                to_state="TAG_PUSHED",
                event="release_checkpoint.TAG_PUSHED.TAG_PUSHED",
                actor_run_id="RUN-RELEASE-ENGINEER",
                reason_code="UNDECLARED_SELF_LOOP",
                evidence_refs=["EV-RELEASE-2"],
                idempotency_key="7" * 64,
                expected_revision=0,
            )
        with self.assertRaises(self.release.PolicyError):
            self.release._append_release_transition(
                state_at("FAILED"),
                to_state="DEV_OPEN",
                event="release_reconciled",
                actor_run_id="RUN-RECONCILER",
                reason_code="BYPASS_RECOVERED",
                evidence_refs=["EV-RELEASE-3"],
                idempotency_key="8" * 64,
                expected_revision=0,
            )

    def test_release_failed_and_conflict_are_durable_and_recoverable_only_by_contract(
        self,
    ) -> None:
        base = {
            "repository": "vibe-coding-era/goal-teams",
            "version": "V2.46",
            "phase": "DRIFTED",
            "checkpoint_phase": "DRIFTED",
            "external_surface_phase": "absent",
            "recovery_state": "none",
            "reconciliation": None,
            "resume_checkpoint_phase": None,
            "state_revision": 0,
            "release_transition_receipts": [],
            "recovery_revision": 0,
            "recovery_transition_receipts": [],
        }
        for classification, expected_state, recovery_state in (
            ("unavailable", "FAILED", "reconciliation_required"),
            ("conflict", "CONFLICT", "conflict"),
        ):
            with self.subTest(classification=classification), tempfile.TemporaryDirectory(
                dir=RELEASE_STATE_TEMP_ROOT
            ) as directory:
                path = Path(directory) / "promotion-state.json"
                state = copy.deepcopy(base)
                path.write_text(
                    json.dumps(state, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                result_digest, receipt, recovery_receipt = (
                    self.release._persist_terminal_release_state(
                        path,
                        state,
                        digest,
                        operation_id="CP17.release_publish",
                        intent={"idempotency_key": "INTENT-RELEASE-1"},
                        readback={
                            "classification": classification,
                            "observed_at": "2026-07-27T00:00:00Z",
                            "details": {"release_id": "unknown"},
                        },
                        actor_run_id="RUN-RELEASE-ENGINEER",
                        external_side_effect_count=1,
                    )
                )
                persisted = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    result_digest,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                self.assertEqual(persisted["checkpoint_phase"], expected_state)
                self.assertEqual(persisted["recovery_state"], recovery_state)
                self.assertEqual(receipt["to_state"], expected_state)
                self.assertEqual(
                    persisted["release_transition_receipts"][-1],
                    receipt,
                )
                self.assertEqual(
                    persisted["recovery_transition_receipts"][-1],
                    recovery_receipt,
                )
                self.assertEqual(recovery_receipt["from_state"], "none")
                self.assertEqual(
                    recovery_receipt["to_state"], recovery_state
                )
                self.assertEqual(persisted["recovery_revision"], 1)
                if expected_state == "FAILED":
                    self.assertEqual(
                        persisted["resume_checkpoint_phase"],
                        "DRIFTED",
                    )
                    recovering = self.release._append_recovery_transition(
                        persisted,
                        to_state="recovering",
                        event=(
                            "recovery.reconciliation_required.recovering"
                        ),
                        actor_run_id="RUN-RECONCILER",
                        reason_code="RECONCILIATION_STARTED",
                        evidence_refs=["EV-EXACT-READBACK"],
                        idempotency_key="a" * 64,
                        expected_revision=persisted["recovery_revision"],
                    )
                    self.assertEqual(recovering["to_state"], "recovering")
                    recovered = self.release._append_release_transition(
                        persisted,
                        to_state="RECOVERED",
                        event="release_checkpoint.FAILED.RECOVERED",
                        actor_run_id="RUN-RECONCILER",
                        reason_code="EXACT_READBACK_RECOVERED",
                        evidence_refs=["EV-EXACT-READBACK"],
                        idempotency_key="3" * 64,
                        expected_revision=persisted["state_revision"],
                    )
                    self.assertEqual(recovered["to_state"], "RECOVERED")
                    resumed = self.release._append_release_transition(
                        persisted,
                        to_state=persisted["resume_checkpoint_phase"],
                        event="release_checkpoint.RECOVERED.DRIFTED",
                        actor_run_id="RUN-RECONCILER",
                        reason_code="RESUME_FROZEN_CHECKPOINT_PHASE",
                        evidence_refs=["EV-EXACT-READBACK"],
                        idempotency_key="5" * 64,
                        expected_revision=persisted["state_revision"],
                    )
                    self.assertEqual(resumed["to_state"], "DRIFTED")
                    recovery_complete = (
                        self.release._append_recovery_transition(
                            persisted,
                            to_state="recovered",
                            event="recovery.recovering.recovered",
                            actor_run_id="RUN-RECONCILER",
                            reason_code="EXACT_READBACK_RECOVERED",
                            evidence_refs=["EV-EXACT-READBACK"],
                            idempotency_key="b" * 64,
                            expected_revision=persisted[
                                "recovery_revision"
                            ],
                        )
                    )
                    self.assertEqual(
                        recovery_complete["to_state"], "recovered"
                    )
                    settled = self.release._append_recovery_transition(
                        persisted,
                        to_state="none",
                        event="recovery.recovered.none",
                        actor_run_id="RUN-RECONCILER",
                        reason_code="RECOVERY_SETTLED",
                        evidence_refs=["EV-EXACT-READBACK"],
                        idempotency_key="c" * 64,
                        expected_revision=persisted["recovery_revision"],
                    )
                    self.assertEqual(settled["to_state"], "none")
                    self.assertEqual(persisted["recovery_revision"], 4)
                    self.assertEqual(persisted["phase"], "DRIFTED")
                else:
                    frozen = copy.deepcopy(persisted)
                    with self.assertRaises(self.release.PolicyError):
                        self.release._append_release_transition(
                            persisted,
                            to_state="RECOVERED",
                            event="release_checkpoint.CONFLICT.RECOVERED",
                            actor_run_id="RUN-RECONCILER",
                            reason_code="ILLEGAL_CONFLICT_RECOVERY",
                            evidence_refs=["EV-EXACT-READBACK"],
                            idempotency_key="4" * 64,
                            expected_revision=persisted["state_revision"],
                        )
                    with self.assertRaises(self.release.PolicyError):
                        self.release._append_recovery_transition(
                            persisted,
                            to_state="recovered",
                            event="recovery.conflict.recovered",
                            actor_run_id="RUN-RECONCILER",
                            reason_code="ILLEGAL_CONFLICT_RECOVERY",
                            evidence_refs=["EV-EXACT-READBACK"],
                            idempotency_key="d" * 64,
                            expected_revision=persisted[
                                "recovery_revision"
                            ],
                        )
                    self.assertEqual(persisted, frozen)

    def test_cp16_external_surface_is_derived_from_exact_operation_receipts(
        self,
    ) -> None:
        state = {
            "recovery_state": "none",
            "checkpoints": {
                "CP12": {
                    "operations": [
                        {
                            "operation_id": "CP12.candidate_push",
                            "readback": {"classification": "exact"},
                        }
                    ]
                },
                "CP15": {
                    "operations": [
                        {
                            "operation_id": "CP15.tag_push",
                            "readback": {"classification": "exact"},
                        }
                    ]
                },
                "CP16": {
                    "operations": [
                        {
                            "operation_id": "CP16.draft_create",
                            "readback": {"classification": "exact"},
                        },
                        {
                            "operation_id": "CP16.asset_download_verify",
                            "readback": {"classification": "unavailable"},
                        },
                    ]
                }
            },
        }
        self.assertEqual(
            self.release._derived_external_surface_phase(state),
            "release_draft",
        )
        state["checkpoints"]["CP16"]["operations"][1]["readback"][
            "classification"
        ] = "exact"
        self.assertEqual(
            self.release._derived_external_surface_phase(state),
            "asset_verified",
        )
        state["recovery_state"] = "conflict"
        self.assertEqual(
            self.release._derived_external_surface_phase(state),
            "conflict",
        )

    def test_external_surface_projection_sequence_is_executable(self) -> None:
        state = {
            "recovery_state": "none",
            "checkpoints": {
                "CP12": {
                    "operations": [
                        {
                            "operation_id": "CP12.candidate_push",
                            "readback": {"classification": "exact"},
                        }
                    ]
                },
                "CP15": {
                    "operations": [
                        {
                            "operation_id": "CP15.tag_push",
                            "readback": {"classification": "exact"},
                        }
                    ]
                },
                "CP16": {
                    "operations": [
                        {
                            "operation_id": "CP16.draft_create",
                            "readback": {"classification": "exact"},
                        },
                        {
                            "operation_id": "CP16.asset_download_verify",
                            "readback": {"classification": "exact"},
                        },
                    ]
                },
                "CP17": {
                    "operations": [
                        {
                            "operation_id": "CP17.main_promote",
                            "readback": {"classification": "exact"},
                        },
                        {
                            "operation_id": "CP17.release_publish",
                            "readback": {"classification": "exact"},
                        },
                        {
                            "operation_id": "CP17.published_asset_download",
                            "readback": {"classification": "exact"},
                        },
                        {
                            "operation_id": "CP17.actual_install",
                            "readback": {"classification": "exact"},
                        },
                    ]
                },
            },
        }
        self.assertEqual(
            self.release._derived_external_surface_phase(state),
            "installed_verified",
        )

        manifest = copy.deepcopy(self.manifest)
        manifest["state_machines"]["external_surface"]["transitions"][
            "main_promoted"
        ].remove("release_published")
        bad_manifest_path = self.receipt_root / "bad-surface-manifest.json"
        bad_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False),
            encoding="utf-8",
        )
        with mock.patch.object(
            self.release,
            "VERIFICATION_GOVERNANCE_MANIFEST_PATH",
            bad_manifest_path,
        ):
            with self.assertRaises(self.release.PolicyError) as caught:
                self.release._derived_external_surface_phase(state)
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V246_RELEASE_STATE_ORTHOGONAL",
        )

    def test_v244_contract_replay_remains_executable(self) -> None:
        replay_case = self._valid_case("V246-V244-REPLAY")
        replay_result = self._validate(self._materialize(replay_case))
        self.assertTrue(replay_result["ok"], replay_result)
        proc = subprocess.run(
            [sys.executable, str(V244_VALIDATOR_PATH), "--self-test"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, (proc.stdout, proc.stderr))
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["passed"], payload)
        self.assertGreaterEqual(payload["v244_valid_contracts_executed"], 1)
        self.assertGreaterEqual(payload["v244_negative_contracts_executed"], 1)


if __name__ == "__main__":
    unittest.main()
