"""V2.36 completion binding regressions."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.v23 import v236_acceptance as acceptance
from scripts.v23 import v236_trust as trust
from tests.v23.common import (
    ROOT,
    TOOL,
    gt,
    parse_envelope,
    requires_trusted_goal_teams_checkout,
    run_cli,
)
from tests.v23.test_governance_release import _normal_completion_fixture
from tests.v23.test_v236_profiles import policy, route_request


HEX40 = "a" * 40
HEX64 = "b" * 64
CANONICAL = ROOT / "examples" / "canonical-v23"
CANONICAL_VERSION = CANONICAL / "versions" / "V2.3"


class V236AcceptanceBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._semantic_directory = tempfile.TemporaryDirectory()
        cls._semantic_root = _normal_completion_fixture(
            Path(cls._semantic_directory.name)
        )
        cls._semantic_version = cls._semantic_root / "versions" / "V2.3"

    @classmethod
    def tearDownClass(cls) -> None:
        cls._semantic_directory.cleanup()

    @staticmethod
    def _completion_cli(root: Path, *, ledger: Path | None = None):
        version = root / "versions/V2.3"
        return run_cli(
            "completion-audit",
            str(version / "audit/completion-audit.json"),
            str(version / "ledger/checkpoint.json"),
            "--evidence-jsonl",
            str(version / "evidence/evidence.jsonl"),
            "--evidence-root",
            str(root),
            "--traceability",
            str(version / "harness/traceability.json"),
            "--review",
            str(version / "reviews/dual-review.json"),
            "--identity-registry",
            str(version / "identity/registry.json"),
            "--harness",
            str(version / "harness/harness.json"),
            "--ledger",
            str(ledger or version / "ledger/events.jsonl"),
            "--tasklist",
            str(version / "TaskList.md"),
        )

    @classmethod
    def _semantic_evidence(cls, binding: dict[str, object]):
        records = [
            json.loads(line)
            for line in (
                cls._semantic_version / "evidence" / "evidence.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        core = acceptance.build_acceptance_core_binding(binding)
        for record in records:
            record["environment"] = {
                **record["environment"],
                "v236_acceptance_core_binding": core,
            }
        events = [
            json.loads(line)
            for line in (
                cls._semantic_version / "ledger" / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {
            "evidence_records": records,
            "valid_evidence_ids": {"EVD-CAN-001", "EVD-CAN-002"},
            "evidence_root": cls._semantic_root,
            "ledger_events": events,
            "source_root": cls._semantic_root,
        }

    @staticmethod
    def _gate_proofs(binding: dict[str, object]):
        execution = {
            key: binding[key]
            for key in (
                "execution_profile",
                "required_review_class",
                "gates",
                "gate_scopes",
                "execution_contract_sha256",
            )
        }
        gate_checks = {}
        canonical_harness = json.loads(
            (CANONICAL_VERSION / "harness" / "harness.json").read_text(
                encoding="utf-8"
            )
        )
        harness_checks = [
            copy.deepcopy(canonical_harness["harness_contract"]["checks"][0])
        ]
        results = {}
        for gate, requirement in binding["gates"].items():
            if gate == "completion_audit":
                gate_checks[gate] = []
                results[gate] = {
                    "state": "passed",
                    "check_refs": [],
                    "evidence_refs": [],
                    "task_refs": [],
                    "external_gate": True,
                    "audit_state": "passed",
                    "acceptance_binding_sha256": acceptance.canonical_json_sha256(
                        binding
                    ),
                }
                continue
            passed = requirement == "required"
            check_refs = ["CHECK-CAN-SUCCESS"] if passed else []
            gate_checks[gate] = check_refs
            results[gate] = {
                "state": "passed" if passed else "not_required",
                "check_refs": check_refs,
                "evidence_refs": ["EVD-CAN-001"] if passed else [],
                "task_refs": ["TASK-CAN-SUCCESS"] if passed else [],
                **(
                    {
                        "reason": "route gate is conditional or not required",
                        "impact_decision": "not_applicable",
                        **(
                            {"impact_scope": binding["gate_scopes"][gate]}
                            if requirement == "conditional"
                            else {}
                        ),
                    }
                    if not passed
                    else {}
                ),
            }
        harness = {
            "v236_acceptance_binding": binding,
            "harness_contract": {
                "task_type": (
                    "regulated"
                    if binding["required_review_class"] == "safety"
                    else (
                        "comparison"
                        if binding["required_review_class"] == "comparison"
                        else "backend"
                    )
                ),
                "required_review_class": binding["required_review_class"],
                "v236_execution_contract": execution,
                "v236_gate_checks": gate_checks,
                "checks": harness_checks,
            },
        }
        checkpoint = json.loads(
            (CANONICAL_VERSION / "ledger" / "checkpoint.json").read_text(
                encoding="utf-8"
            )
        )
        tasks = {
            "TASK-CAN-SUCCESS": copy.deepcopy(
                checkpoint["tasks"]["TASK-CAN-SUCCESS"]
            )
        }
        completion_inputs = {
            **execution,
            "v236_gate_results": results,
        }
        return harness, tasks, completion_inputs

    @staticmethod
    def _validate_contract(
        binding: dict[str, object],
        harness: dict[str, object],
        tasks: dict[str, object],
        completion_inputs: dict[str, object],
        *,
        route_validation: dict[str, object] | None = None,
        review: dict[str, object] | None = None,
    ) -> list[str]:
        document = {"v236_acceptance_binding": binding}
        audit_document = {
            "v236_acceptance_binding": binding,
            "audit_state": "passed",
        }
        review_document = {
            "v236_acceptance_binding": binding,
            "review_class": binding["required_review_class"],
        }
        return acceptance.validate_acceptance_bindings(
            expected=binding,
            audit=audit_document,
            review=review or review_document,
            harness=harness,
            **V236AcceptanceBindingTests._semantic_evidence(binding),
            route_validation=route_validation or {"route": binding},
            tasks=tasks,
            completion_inputs=completion_inputs,
        )

    def _fixture(
        self, root: Path, **route_updates: object
    ) -> tuple[dict[str, object], dict[str, object]]:
        paths = {}
        for name in (
            "evidence.jsonl",
            "events.jsonl",
            "checkpoint.json",
            "traceability.json",
            "review.json",
            "harness.json",
            "audit.json",
            "TaskList.md",
        ):
            path = root / name
            path.write_text("{}\n" if path.suffix in {".json", ".jsonl"} else f"{name}\n", encoding="utf-8")
            paths[name] = path
        ignored = root / "GoalTeamsWork-V2.36" / "reports"
        ignored.mkdir(parents=True)
        artifact = ignored / "artifact.txt"
        log = ignored / "execution.log"
        binary = ignored / "model.bin"
        artifact.write_text("artifact\n", encoding="utf-8")
        log.write_text("log\n", encoding="utf-8")
        binary.write_bytes(b"\x00\x01model")
        paths["evidence.jsonl"].write_text(
            json.dumps(
                {
                    "artifact_ref": artifact.relative_to(root).as_posix(),
                    "artifacts": {
                        "actual": binary.relative_to(root).as_posix()
                    },
                    "command": {"log_path": log.relative_to(root).as_posix()},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        route_receipt = {"schema_version": "goal-teams-v2.36-host-route-receipt-v1", "nonce": "route-1"}
        derived = policy.normalize_project_route(route_request(**route_updates))
        self.assertTrue(derived["ok"], derived)
        route_validation = {
            "route": {
                "route_digest": "c" * 64,
                "actual_target_fingerprint": "9" * 64,
                "actual_target_kind": derived["target_kind"],
                "release": derived["release"],
                "trusted_release_base": HEX40,
                "policy_profile": derived["policy_profile"],
                "state_gate_profile": derived["state_gate_profile"],
                "execution_profile": derived["profile"],
                "required_review_class": derived["required_review_class"],
                "gates": derived["gates"],
                "gate_scopes": derived["gate_scopes"],
                "execution_contract_sha256": derived[
                    "execution_contract_sha256"
                ],
            }
        }
        snapshot_receipt = {
            "receipt_sha256": HEX64,
            "snapshot_tree": "d" * 40,
            "baseline_commit": HEX40,
            "repository_fingerprint": "9" * 64,
        }
        identity_registry = {
            "schema_version": "goal-teams-v2.36-attested-identity-registry-v1",
            "identities": [{"agent_run_id": "RUN-1"}],
        }
        input_snapshot = acceptance.build_acceptance_input_snapshot(
            root,
            required_paths={
                "evidence": paths["evidence.jsonl"],
                "review": paths["review.json"],
                "harness": paths["harness.json"],
                "audit": paths["audit.json"],
                "ledger": paths["events.jsonl"],
                "checkpoint": paths["checkpoint.json"],
                "traceability": paths["traceability.json"],
                "tasklist": paths["TaskList.md"],
            },
        )
        binding = acceptance.build_acceptance_binding(
            acceptance_root=root,
            route_receipt=route_receipt,
            route_validation=route_validation,
            snapshot_receipt=snapshot_receipt,
            identity_registry=identity_registry,
            evidence_registry_path=paths["evidence.jsonl"],
            ledger_path=paths["events.jsonl"],
            checkpoint_path=paths["checkpoint.json"],
            traceability_path=paths["traceability.json"],
            tasklist_path=paths["TaskList.md"],
            acceptance_input_snapshot=input_snapshot,
        )
        return binding, {
            "route_receipt": route_receipt,
            "route_validation": route_validation,
            "snapshot_receipt": snapshot_receipt,
            "identity_registry": identity_registry,
            "paths": paths,
            "acceptance_input_snapshot": input_snapshot,
        }

    def test_v236_generation_is_derived_from_target_or_documents(self) -> None:
        self.assertTrue(
            acceptance.requires_v236_acceptance([], verified_goal_teams_target=True)
        )
        self.assertTrue(
            acceptance.requires_v236_acceptance(
                [{"product_version": "V2.36"}], verified_goal_teams_target=False
            )
        )
        self.assertFalse(
            acceptance.requires_v236_acceptance(
                [{"schema_version": "goal-teams-v2.3"}],
                verified_goal_teams_target=False,
            )
        )

    def test_acceptance_binding_schema_matches_runtime_id(self) -> None:
        root = Path(__file__).resolve().parents[2]
        pairs = (
            (
                "acceptance-binding.schema.json",
                acceptance.ACCEPTANCE_BINDING_SCHEMA_VERSION,
            ),
            (
                "acceptance-core-binding.schema.json",
                acceptance.ACCEPTANCE_CORE_BINDING_SCHEMA_VERSION,
            ),
            (
                "acceptance-input-snapshot.schema.json",
                acceptance.ACCEPTANCE_INPUT_SNAPSHOT_SCHEMA_VERSION,
            ),
        )
        for name, expected in pairs:
            schema = json.loads(
                (root / "schemas/v2.36" / name).read_text(encoding="utf-8")
            )
            self.assertEqual(schema["$id"], expected)

    def test_audit_review_harness_and_every_current_evidence_bind_same_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, _ = self._fixture(Path(directory))
        documents = {"v236_acceptance_binding": binding}
        audit_document = {
            "v236_acceptance_binding": binding,
            "audit_state": "passed",
        }
        review_document = {
            "v236_acceptance_binding": binding,
            "review_class": binding["required_review_class"],
        }
        harness, tasks, completion_inputs = self._gate_proofs(binding)
        errors = acceptance.validate_acceptance_bindings(
            expected=binding,
            audit=audit_document,
            review=review_document,
            harness=harness,
            **self._semantic_evidence(binding),
            route_validation={"route": binding},
            tasks=tasks,
            completion_inputs=completion_inputs,
        )
        self.assertEqual(errors, [])

        mutated = json.loads(json.dumps(audit_document))
        mutated["v236_acceptance_binding"]["snapshot_tree"] = "e" * 40
        invalid_evidence = self._semantic_evidence(binding)
        invalid_evidence["evidence_records"][0]["environment"][
            "v236_acceptance_core_binding"
        ] = {}
        errors = acceptance.validate_acceptance_bindings(
            expected=binding,
            audit=mutated,
            review=review_document,
            harness=harness,
            **invalid_evidence,
            route_validation={"route": binding},
            tasks=tasks,
            completion_inputs=completion_inputs,
        )
        self.assertIn("E_V236_ACCEPTANCE_AUDIT_BINDING", errors)
        self.assertIn("E_V236_ACCEPTANCE_EVIDENCE_BINDING:EVD-CAN-001", errors)

    def test_caller_claims_cannot_turn_minimal_objects_into_gate_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, _ = self._fixture(Path(directory))
        harness, _, completion_inputs = self._gate_proofs(binding)
        harness["harness_contract"]["checks"] = [
            {
                "check_id": "CHECK-CAN-SUCCESS",
                "check_state": "passed",
                "evidence_refs": ["EVD-CAN-001"],
            }
        ]
        tasks = {
            "TASK-CAN-SUCCESS": {
                "task_state": "accepted",
                "check_state": "passed",
            }
        }
        semantic = self._semantic_evidence(binding)
        semantic["evidence_records"] = [
            {
                "evidence_id": "EVD-CAN-001",
                "environment": {
                    "v236_acceptance_core_binding": (
                        acceptance.build_acceptance_core_binding(binding)
                    )
                },
            }
        ]
        semantic["valid_evidence_ids"] = {"EVD-CAN-001"}
        errors = acceptance.validate_acceptance_bindings(
            expected=binding,
            audit={
                "v236_acceptance_binding": binding,
                "audit_state": "passed",
            },
            review={
                "v236_acceptance_binding": binding,
                "review_class": binding["required_review_class"],
            },
            harness=harness,
            route_validation={"route": binding},
            tasks=tasks,
            completion_inputs=completion_inputs,
            **semantic,
        )
        self.assertTrue(
            any(
                error.startswith("E_V236_ACCEPTANCE_EVIDENCE_SEMANTICS:")
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any(
                error.startswith("E_V236_ACCEPTANCE_CHECK_SEMANTICS:")
                for error in errors
            ),
            errors,
        )
        self.assertTrue(
            any(
                error.startswith("E_V236_ACCEPTANCE_TASK_SEMANTICS:")
                for error in errors
            ),
            errors,
        )

    def test_release_base_must_equal_snapshot_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding, fixture = self._fixture(root)
            self.assertEqual(binding["trusted_release_base"], HEX40)
            fixture["snapshot_receipt"]["baseline_commit"] = "f" * 40
            with self.assertRaisesRegex(ValueError, "E_V236_ACCEPTANCE_BINDING"):
                acceptance.build_acceptance_binding(
                    acceptance_root=root,
                    route_receipt=fixture["route_receipt"],
                    route_validation=fixture["route_validation"],
                    snapshot_receipt=fixture["snapshot_receipt"],
                    identity_registry=fixture["identity_registry"],
                    evidence_registry_path=root / "evidence.jsonl",
                    ledger_path=root / "events.jsonl",
                    checkpoint_path=root / "checkpoint.json",
                    traceability_path=root / "traceability.json",
                    tasklist_path=root / "TaskList.md",
                    acceptance_input_snapshot=fixture[
                        "acceptance_input_snapshot"
                    ],
                )

    def test_snapshot_covers_ignored_artifacts_and_rejects_omission_or_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, fixture = self._fixture(root)
            snapshot = fixture["acceptance_input_snapshot"]
            records = {record["path"]: record for record in snapshot["files"]}
            artifact_path = "GoalTeamsWork-V2.36/reports/artifact.txt"
            log_path = "GoalTeamsWork-V2.36/reports/execution.log"
            binary_path = "GoalTeamsWork-V2.36/reports/model.bin"
            self.assertIn(artifact_path, records)
            self.assertIn(log_path, records)
            self.assertIn(binary_path, records)
            self.assertEqual(records[log_path]["hash_mode"], "raw_sha256")
            self.assertEqual(
                records["review.json"]["hash_mode"],
                "canonical_json_without_acceptance_bindings",
            )

            forged = copy.deepcopy(snapshot)
            forged["files"] = [
                record
                for record in forged["files"]
                if record["path"] != binary_path
            ]
            forged["file_count"] = len(forged["files"])
            forged["total_size"] = sum(record["size"] for record in forged["files"])
            core = {key: value for key, value in forged.items() if key != "snapshot_sha256"}
            forged["snapshot_sha256"] = acceptance.canonical_json_sha256(core)
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, forged),
                ["E_V236_ACCEPTANCE_INPUT_DRIFT"],
            )
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_SNAPSHOT"
            ):
                acceptance.build_acceptance_binding(
                    acceptance_root=root,
                    route_receipt=fixture["route_receipt"],
                    route_validation=fixture["route_validation"],
                    snapshot_receipt=fixture["snapshot_receipt"],
                    identity_registry=fixture["identity_registry"],
                    evidence_registry_path=fixture["paths"]["evidence.jsonl"],
                    ledger_path=fixture["paths"]["events.jsonl"],
                    checkpoint_path=fixture["paths"]["checkpoint.json"],
                    traceability_path=fixture["paths"]["traceability.json"],
                    tasklist_path=fixture["paths"]["TaskList.md"],
                    acceptance_input_snapshot=forged,
                )

            (root / log_path).write_text("tampered log\n", encoding="utf-8")
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, snapshot),
                ["E_V236_ACCEPTANCE_INPUT_DRIFT"],
            )

    def test_snapshot_rejects_missing_referenced_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, fixture = self._fixture(root)
            snapshot = fixture["acceptance_input_snapshot"]
            (root / "GoalTeamsWork-V2.36/reports/artifact.txt").unlink()
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_REFERENCE"
            ):
                acceptance.build_acceptance_input_snapshot(
                    root, required_paths=snapshot["required_inputs"]
                )

    def test_snapshot_rejects_duplicate_keys_in_projected_json(self) -> None:
        payloads = {
            "review.json": (
                '{"v236_acceptance_binding":{"x":1},'
                '"v236_acceptance_binding":{"x":2}}\n'
            ),
            "harness.json": '{"nested":{"check":1,"check":2}}\n',
            "audit.json": '{"audit":{"state":"passed","state":"failed"}}\n',
        }
        for name, payload in payloads.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, fixture = self._fixture(root)
                fixture["paths"][name].write_text(payload, encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, "E_V236_ACCEPTANCE_INPUT_PARSE"
                ):
                    acceptance.build_acceptance_input_snapshot(
                        root,
                        required_paths=fixture["acceptance_input_snapshot"][
                            "required_inputs"
                        ],
                    )

    def test_snapshot_rejects_duplicate_keys_in_json_and_jsonl_refs(self) -> None:
        payloads = {
            "evidence.jsonl": (
                '{"artifact_ref":"first.bin",'
                '"artifact_ref":"second.bin"}\n'
            ),
            "checkpoint.json": '{"artifact":{"path":"a.bin","path":"b.bin"}}\n',
            "traceability.json": '{"score":NaN}\n',
        }
        for name, payload in payloads.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, fixture = self._fixture(root)
                fixture["paths"][name].write_text(payload, encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, "E_V236_ACCEPTANCE_INPUT_PARSE"
                ):
                    acceptance.build_acceptance_input_snapshot(
                        root,
                        required_paths=fixture["acceptance_input_snapshot"][
                            "required_inputs"
                        ],
                    )

    def test_snapshot_follows_markdown_inline_and_reference_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, fixture = self._fixture(root)
            reports = root / "GoalTeamsWork-V2.36/reports"
            inline = reports / "inline-model.bin"
            referenced = reports / "reference-model.bin"
            inline.write_bytes(b"inline-model")
            referenced.write_bytes(b"reference-model")
            report = reports / "report.md"
            report.write_text(
                "[inline evidence](inline-model.bin)\n"
                "[reference evidence][model]\n\n"
                "[model]: reference-model.bin\n",
                encoding="utf-8",
            )
            fixture["paths"]["evidence.jsonl"].write_text(
                json.dumps({"report_ref": report.relative_to(root).as_posix()})
                + "\n",
                encoding="utf-8",
            )
            snapshot = acceptance.build_acceptance_input_snapshot(
                root,
                required_paths=fixture["acceptance_input_snapshot"][
                    "required_inputs"
                ],
            )
            paths = {record["path"] for record in snapshot["files"]}
            self.assertIn(inline.relative_to(root).as_posix(), paths)
            self.assertIn(referenced.relative_to(root).as_posix(), paths)
            referenced.write_bytes(b"drifted-reference-model")
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, snapshot),
                ["E_V236_ACCEPTANCE_INPUT_DRIFT"],
            )

    def test_snapshot_follows_okf_frontmatter_scalars_and_lists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, fixture = self._fixture(root)
            reports = root / "GoalTeamsWork-V2.36/reports"
            local = reports / "model.bin"
            block = reports / "block-model.bin"
            flow = reports / "flow-model.bin"
            root_shadow = root / "model.bin"
            local.write_bytes(b"local-model")
            block.write_bytes(b"block-model")
            flow.write_bytes(b"flow-model")
            root_shadow.write_bytes(b"wrong-root-shadow")
            report = reports / "report.md"
            report.write_text(
                "---\n"
                'artifact_ref: "model.bin"\n'
                "source_paths:\n"
                "  - 'block-model.bin'\n"
                "attachments: ['flow-model.bin']\n"
                "---\n"
                "# OKF report\n",
                encoding="utf-8",
            )
            fixture["paths"]["evidence.jsonl"].write_text(
                json.dumps({"report_ref": report.relative_to(root).as_posix()})
                + "\n",
                encoding="utf-8",
            )
            snapshot = acceptance.build_acceptance_input_snapshot(
                root,
                required_paths=fixture["acceptance_input_snapshot"][
                    "required_inputs"
                ],
            )
            paths = {record["path"] for record in snapshot["files"]}
            for expected in (local, block, flow):
                self.assertIn(expected.relative_to(root).as_posix(), paths)
            self.assertNotIn(root_shadow.relative_to(root).as_posix(), paths)

            local.write_bytes(b"drifted-local-model")
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, snapshot),
                ["E_V236_ACCEPTANCE_INPUT_DRIFT"],
            )
            local.write_bytes(b"local-model")
            block.unlink()
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_REFERENCE"
            ):
                acceptance.build_acceptance_input_snapshot(
                    root, required_paths=snapshot["required_inputs"]
                )

    def test_snapshot_rejects_okf_frontmatter_symlink_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, fixture = self._fixture(root)
            reports = root / "GoalTeamsWork-V2.36/reports"
            target = reports / "real-model.bin"
            alias = reports / "model.bin"
            target.write_bytes(b"model")
            alias.unlink()
            alias.symlink_to(target)
            report = reports / "report.md"
            report.write_text(
                "---\nartifact_ref: model.bin\n---\n# report\n",
                encoding="utf-8",
            )
            fixture["paths"]["evidence.jsonl"].write_text(
                json.dumps({"report_ref": report.relative_to(root).as_posix()})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_REFERENCE"
            ):
                acceptance.build_acceptance_input_snapshot(
                    root,
                    required_paths=fixture["acceptance_input_snapshot"][
                        "required_inputs"
                    ],
                )

    def test_snapshot_rejects_root_and_reference_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "real-root"
            root.mkdir()
            _, fixture = self._fixture(root)
            snapshot = fixture["acceptance_input_snapshot"]

            root_alias = base / "root-alias"
            root_alias.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_ROOT"
            ):
                acceptance.build_acceptance_input_snapshot(
                    root_alias, required_paths=snapshot["required_inputs"]
                )

            target = root / "GoalTeamsWork-V2.36/reports/artifact.txt"
            alias = root / "artifact-alias.txt"
            alias.symlink_to(target)
            fixture["paths"]["evidence.jsonl"].write_text(
                json.dumps({"artifact_ref": alias.relative_to(root).as_posix()})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_REFERENCE"
            ):
                acceptance.build_acceptance_input_snapshot(
                    root, required_paths=snapshot["required_inputs"]
                )

            directory_alias = root / "reports-alias"
            directory_alias.symlink_to(target.parent, target_is_directory=True)
            fixture["paths"]["evidence.jsonl"].write_text(
                json.dumps({"artifact_ref": "reports-alias/artifact.txt"})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_REFERENCE"
            ):
                acceptance.build_acceptance_input_snapshot(
                    root, required_paths=snapshot["required_inputs"]
                )

    def test_snapshot_rejects_intermediate_root_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real_parent = base / "real-parent"
            root = real_parent / "root"
            root.mkdir(parents=True)
            _, fixture = self._fixture(root)
            alias_parent = base / "alias-parent"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(
                ValueError, "E_V236_ACCEPTANCE_INPUT_ROOT"
            ):
                acceptance.build_acceptance_input_snapshot(
                    alias_parent / "root",
                    required_paths=fixture["acceptance_input_snapshot"][
                        "required_inputs"
                    ],
                )

    @unittest.skipUnless(
        sys.platform == "darwin" and Path("/var").is_symlink(),
        "macOS /var system alias only",
    )
    def test_snapshot_accepts_exact_macos_var_system_alias(self) -> None:
        alias_tmp = Path(tempfile.gettempdir())
        if not alias_tmp.as_posix().startswith("/var/"):
            self.skipTest("active writable temp root does not use the macOS /var alias")
        with tempfile.TemporaryDirectory(dir=alias_tmp) as directory:
            root = Path(directory)
            _, fixture = self._fixture(root)
            snapshot = acceptance.build_acceptance_input_snapshot(
                root,
                required_paths=fixture["acceptance_input_snapshot"][
                    "required_inputs"
                ],
            )
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, snapshot), []
            )

    def test_projected_binding_breaks_cycle_but_exact_validator_catches_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binding, fixture = self._fixture(root)
            snapshot = fixture["acceptance_input_snapshot"]
            review_path = fixture["paths"]["review.json"]
            review_path.write_text(
                json.dumps({"v236_acceptance_binding": binding}, sort_keys=True),
                encoding="utf-8",
            )
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, snapshot), []
            )

            tampered_binding = copy.deepcopy(binding)
            tampered_binding["snapshot_tree"] = "e" * 40
            tampered_review_on_disk = {
                "v236_acceptance_binding": tampered_binding,
            }
            tampered_review = {
                "v236_acceptance_binding": tampered_binding,
                "review_class": binding["required_review_class"],
            }
            review_path.write_text(
                json.dumps(tampered_review_on_disk, sort_keys=True),
                encoding="utf-8",
            )
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, snapshot), []
            )
            harness, tasks, completion_inputs = self._gate_proofs(binding)
            errors = self._validate_contract(
                binding,
                harness,
                tasks,
                completion_inputs,
                review=tampered_review,
            )
            self.assertIn("E_V236_ACCEPTANCE_REVIEW_BINDING", errors)

            review_path.write_text(
                json.dumps(
                    {
                        "v236_acceptance_binding": tampered_binding,
                        "finding": "non-binding content changed",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                acceptance.validate_acceptance_input_snapshot(root, snapshot),
                ["E_V236_ACCEPTANCE_INPUT_DRIFT"],
            )

    def test_full_and_regulated_cannot_omit_any_derived_gate(self) -> None:
        cases = (
            {"project_size": "large", "work_type": "feature", "release": True},
            {"security_sensitive": True},
        )
        for route_updates in cases:
            with self.subTest(route_updates=route_updates), tempfile.TemporaryDirectory() as directory:
                binding, _ = self._fixture(Path(directory), **route_updates)
                self.assertIn(binding["execution_profile"], {"full", "regulated"})
                harness, tasks, completion_inputs = self._gate_proofs(binding)
                missing_gate = next(
                    gate
                    for gate, requirement in binding["gates"].items()
                    if requirement == "required"
                )
                del completion_inputs["v236_gate_results"][missing_gate]
                errors = self._validate_contract(
                    binding, harness, tasks, completion_inputs
                )
                self.assertIn("E_V236_ACCEPTANCE_GATE_RESULTS_REQUIRED", errors)
                self.assertIn("E_V236_ACCEPTANCE_FULL_GATE_COVERAGE", errors)
                self.assertIn(
                    f"E_V236_ACCEPTANCE_GATE_RESULT:{missing_gate}", errors
                )

    def test_gate_proofs_must_resolve_to_real_checks_evidence_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, _ = self._fixture(Path(directory))
        base_harness, base_tasks, base_inputs = self._gate_proofs(binding)
        required_gate = next(
            gate
            for gate, requirement in binding["gates"].items()
            if requirement == "required"
        )

        harness = copy.deepcopy(base_harness)
        inputs = copy.deepcopy(base_inputs)
        harness["harness_contract"]["v236_gate_checks"][required_gate] = [
            "CHECK-NOT-REAL"
        ]
        inputs["v236_gate_results"][required_gate]["check_refs"] = [
            "CHECK-NOT-REAL"
        ]
        self.assertIn(
            f"E_V236_ACCEPTANCE_GATE_CHECK:{required_gate}",
            self._validate_contract(binding, harness, base_tasks, inputs),
        )

        inputs = copy.deepcopy(base_inputs)
        inputs["v236_gate_results"][required_gate]["evidence_refs"] = [
            "EVD-NOT-REAL"
        ]
        self.assertIn(
            f"E_V236_ACCEPTANCE_GATE_EVIDENCE:{required_gate}",
            self._validate_contract(binding, base_harness, base_tasks, inputs),
        )

        inputs = copy.deepcopy(base_inputs)
        inputs["v236_gate_results"][required_gate]["evidence_refs"] = [
            "EVD-CAN-002"
        ]
        errors = acceptance.validate_route_execution_contract(
            expected=binding,
            route_validation={"route": binding},
            harness=base_harness,
            tasks=base_tasks,
            completion_inputs=inputs,
            **self._semantic_evidence(binding),
            audit={
                "v236_acceptance_binding": binding,
                "audit_state": "passed",
            },
        )
        self.assertIn(f"E_V236_ACCEPTANCE_GATE_CHECK:{required_gate}", errors)
        self.assertNotIn(
            f"E_V236_ACCEPTANCE_GATE_EVIDENCE:{required_gate}", errors
        )

        inputs = copy.deepcopy(base_inputs)
        inputs["v236_gate_results"][required_gate]["task_refs"] = [
            "TASK-NOT-REAL"
        ]
        self.assertIn(
            f"E_V236_ACCEPTANCE_GATE_TASK:{required_gate}",
            self._validate_contract(binding, base_harness, base_tasks, inputs),
        )

    def test_conditional_gate_needs_explicit_impact_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, _ = self._fixture(Path(directory))
        harness, tasks, completion_inputs = self._gate_proofs(binding)
        conditional_gate = next(
            gate
            for gate, requirement in binding["gates"].items()
            if requirement == "conditional"
        )
        del completion_inputs["v236_gate_results"][conditional_gate][
            "impact_decision"
        ]
        errors = self._validate_contract(
            binding, harness, tasks, completion_inputs
        )
        self.assertIn(
            f"E_V236_ACCEPTANCE_GATE_CONDITIONAL:{conditional_gate}", errors
        )

    def test_completion_audit_gate_rejects_task_check_or_evidence_self_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, _ = self._fixture(Path(directory))
        harness, tasks, completion_inputs = self._gate_proofs(binding)
        result = completion_inputs["v236_gate_results"]["completion_audit"]
        result["task_refs"] = ["TASK-CAN-SUCCESS"]
        result["evidence_refs"] = ["EVD-CAN-001"]
        result["check_refs"] = ["CHECK-completion_audit"]
        harness["harness_contract"]["v236_gate_checks"][
            "completion_audit"
        ] = ["CHECK-completion_audit"]
        harness["harness_contract"]["checks"].append(
            {
                "check_id": "CHECK-completion_audit",
                "check_state": "passed",
                "evidence_refs": ["EVD-CAN-001"],
            }
        )
        errors = self._validate_contract(
            binding, harness, tasks, completion_inputs
        )
        self.assertIn(
            "E_V236_ACCEPTANCE_COMPLETION_AUDIT_SELF_REFERENCE", errors
        )

    def test_route_harness_and_completion_inputs_cannot_relabel_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binding, _ = self._fixture(Path(directory))
        harness, tasks, completion_inputs = self._gate_proofs(binding)

        forged_route = copy.deepcopy(binding)
        forged_route["execution_profile"] = "standard"
        self.assertIn(
            "E_V236_ACCEPTANCE_ROUTE_EXECUTION_BINDING",
            self._validate_contract(
                binding,
                harness,
                tasks,
                completion_inputs,
                route_validation={"route": forged_route},
            ),
        )

        forged_harness = copy.deepcopy(harness)
        forged_harness["harness_contract"]["v236_execution_contract"][
            "gates"
        ] = {}
        self.assertIn(
            "E_V236_ACCEPTANCE_HARNESS_GATE_BINDING",
            self._validate_contract(
                binding, forged_harness, tasks, completion_inputs
            ),
        )

        forged_inputs = copy.deepcopy(completion_inputs)
        del forged_inputs["execution_profile"]
        self.assertIn(
            "E_V236_ACCEPTANCE_REVIEW_CLASS",
            self._validate_contract(binding, harness, tasks, forged_inputs),
        )

    def test_goal_teams_v236_completion_cannot_omit_trust_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _normal_completion_fixture(Path(directory))
            (root / "VERSION").write_text("V2.36\n", encoding="utf-8")
            (root / "SKILL.md").write_text(
                "---\nname: goal-teams\ndescription: fixture\n---\n",
                encoding="utf-8",
            )
            version = root / "versions/V2.3"
            audit_path = version / "audit/completion-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["product_version"] = "V2.36"
            audit_path.write_text(
                json.dumps(audit, sort_keys=True) + "\n", encoding="utf-8"
            )
            proc = run_cli(
                "completion-audit",
                str(audit_path),
                str(version / "ledger/checkpoint.json"),
                "--evidence-jsonl",
                str(version / "evidence/evidence.jsonl"),
                "--evidence-root",
                str(root),
                "--source-root",
                str(root),
                "--traceability",
                str(version / "harness/traceability.json"),
                "--review",
                str(version / "reviews/dual-review.json"),
                "--identity-registry",
                str(version / "identity/registry.json"),
                "--harness",
                str(version / "harness/harness.json"),
                "--ledger",
                str(version / "ledger/events.jsonl"),
                "--tasklist",
                str(version / "TaskList.md"),
            )
            envelope = parse_envelope(proc)
        self.assertNotEqual(proc.returncode, 0, envelope)
        self.assertIn("E_V236_HOST_ADAPTER_REQUIRED", envelope.get("errors", []))

    @requires_trusted_goal_teams_checkout
    def test_completion_auto_observes_trusted_outer_repo_without_v236_markers(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as trusted_directory:
            trusted = _normal_completion_fixture(Path(trusted_directory))
            trusted_proc = self._completion_cli(trusted)
            trusted_envelope = parse_envelope(trusted_proc)
            trusted_version = trusted / "versions/V2.3"
            (trusted_version / "ledger/checkpoint.json").write_text(
                "{malformed", encoding="utf-8"
            )
            (trusted_version / "ledger/events.jsonl").write_text(
                "{malformed\n", encoding="utf-8"
            )
            malformed_proc = self._completion_cli(trusted)
            malformed_envelope = parse_envelope(malformed_proc)
        self.assertNotEqual(trusted_proc.returncode, 0, trusted_envelope)
        self.assertIn(
            "E_V236_HOST_ADAPTER_REQUIRED", trusted_envelope.get("errors", [])
        )
        self.assertNotEqual(malformed_proc.returncode, 0, malformed_envelope)
        self.assertEqual(
            malformed_envelope.get("errors"), ["E_V236_HOST_ADAPTER_REQUIRED"]
        )

    def test_external_legacy_completion_and_symlink_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as external_directory:
            external = _normal_completion_fixture(Path(external_directory))
            external_proc = self._completion_cli(external)
            external_envelope = parse_envelope(external_proc)
            with tempfile.TemporaryDirectory(dir=ROOT) as alias_directory:
                alias = Path(alias_directory) / "external-alias"
                alias.symlink_to(external, target_is_directory=True)
                alias_proc = self._completion_cli(
                    external,
                    ledger=alias / "versions/V2.3/ledger/events.jsonl",
                )
                alias_envelope = parse_envelope(alias_proc)
        self.assertEqual(external_proc.returncode, 0, external_envelope)
        self.assertTrue(external_envelope["ok"])
        self.assertNotEqual(alias_proc.returncode, 0, alias_envelope)
        self.assertEqual(
            alias_envelope["error_code"], "E_V236_SOURCE_ROOT_UNVERIFIED"
        )

    def test_candidate_host_context_cannot_enable_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "candidate-selected-state.json"
            args = SimpleNamespace(
                source_root=str(root),
                v236_route_request=None,
                v236_route_receipt=None,
                v236_protected_snapshot=None,
            )
            host_context = {
                "schema_version": "caller-selected-untrusted-context",
                "provider_trust_level": "caller_claimed",
                "trust_key": b"caller-controlled-key-material-000000000",
                "state_path": str(state_path),
            }
            context = gt._prepare_v236_completion_acceptance(
                args,
                checkpoint={"product_version": "V2.36"},
                events=[],
                evidence_records=[],
                valid_evidence_ids=set(),
                trace_doc={},
                review_doc={},
                identity_doc={},
                harness_doc={},
                audit_doc={},
                evidence_root=root,
                ledger_path=root / "events.jsonl",
                checkpoint_path=root / "checkpoint.json",
                traceability_path=root / "traceability.json",
                host_context=host_context,
            )
        self.assertEqual(context["errors"], ["E_V236_HOST_ADAPTER_REQUIRED"])
        self.assertEqual(
            gt._consume_v236_completion_acceptance(context),
            ["E_V236_HOST_ADAPTER_REQUIRED"],
        )
        self.assertFalse(state_path.exists())

    def test_agent_cli_identity_validation_is_diagnostic_not_acceptance(self) -> None:
        key = b"host-private-cli-key-material-00000000000000000"
        issuer = "host-cli"
        identity = {
            "agent_type": "goal_qa",
            "agent_run_id": "RUN-CLI-ATTESTED",
            "member_id": "测试-CLI",
            "display_name": "测试-CLI",
            "transport_handle": "host-cli-worker",
        }
        identity["host_attestation"] = trust.issue_agent_host_attestation(
            identity,
            trust_key=key,
            issuer=issuer,
            nonce="cli-once",
        )["attestation"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-v2.36-attested-identity-registry-v1",
                        "identities": [identity],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            environment = os.environ.copy()
            environment["GOAL_TEAMS_HOST_ATTESTATION_KEY"] = key.decode("utf-8")
            first = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    "v236-validate-attested-identities",
                    str(registry),
                    "--expected-issuer",
                    issuer,
                ],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            first_envelope = parse_envelope(first)
            self.assertEqual(first.returncode, 0, first_envelope)
            self.assertFalse(first_envelope["validation"]["acceptance_eligible"])
            self.assertNotIn(key.decode("utf-8"), first.stdout + first.stderr)


if __name__ == "__main__":
    unittest.main()
