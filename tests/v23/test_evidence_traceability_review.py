"""V2.3 Evidence, traceability, review and error-envelope tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import (
    ROOT,
    clone,
    gt,
    has_error,
    parse_envelope,
    run_cli,
    sha256_path,
    task_event,
)


class EvidenceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name).resolve()
        self.artifact = self.root / "artifact.txt"
        self.log = self.root / "run.log"
        self.source = self.root / "source.py"
        self.artifact.write_text("verified artifact\n", encoding="utf-8")
        self.log.write_text("command completed\n", encoding="utf-8")
        self.source.write_text("VALUE = 'source-current'\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "V2.3 Tests"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "add", "artifact.txt", "run.log", "source.py"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True, capture_output=True, check=True
        ).stdout.strip()
        initial = task_event(
            "EVT-EVIDENCE-1", "TASK-EVIDENCE", 0, "planned", attempt_id="ATT-1"
        )
        running = task_event(
            "EVT-EVIDENCE-2", "TASK-EVIDENCE", 1, "running", attempt_id="ATT-1"
        )
        review = task_event(
            "EVT-EVIDENCE-3", "TASK-EVIDENCE", 2, "review", attempt_id="ATT-1"
        )

        def reference_event(
            event_id: str,
            base_revision: int,
            evidence_id: str,
            check_id: str,
            run_id: str,
        ) -> dict:
            value = task_event(
                event_id,
                "TASK-EVIDENCE",
                base_revision,
                "review",
                attempt_id="ATT-1",
                payload={
                    "check_state": "passed",
                    "evidence_refs": [evidence_id],
                    "validation_check_id": check_id,
                    "validation_run_id": run_id,
                },
            )
            value.update(
                {
                    "event_type": "check_executed",
                    "actor_run_id": "RUN-VALIDATOR-TASK-EVIDENCE",
                    "validation_check_id": check_id,
                    "validation_run_id": run_id,
                }
            )
            return value

        first_reference = reference_event(
            "EVT-EVIDENCE-4", 3, "EVD-1", "CHECK-1", "RUN-1"
        )
        second_reference = reference_event(
            "EVT-EVIDENCE-5", 4, "EVD-2", "CHECK-2", "RUN-2"
        )
        self.ledger_events = [
            initial,
            running,
            review,
            first_reference,
            second_reference,
        ]
        for value, timestamp in zip(
            self.ledger_events,
            (
                "2026-07-09T23:59:57Z",
                "2026-07-09T23:59:58Z",
                "2026-07-09T23:59:59Z",
                "2026-07-10T00:00:02Z",
                "2026-07-10T00:00:03Z",
            ),
            strict=True,
        ):
            value["timestamp"] = timestamp
        artifact_stat = self.artifact.stat()
        log_stat = self.log.stat()
        self.good = {
            "schema_version": "goal-teams-v2.3",
            "evidence_id": "EVD-1",
            "check_id": "CHECK-1",
            "run_id": "RUN-1",
            "attempt_id": "ATT-1",
            "artifact_ref": "artifact.txt",
            "artifact_sha256": sha256_path(self.artifact),
            "artifact_size": artifact_stat.st_size,
            "artifact_mtime_ns": artifact_stat.st_mtime_ns,
            "producer_run_id": "RUN-PRODUCER-1",
            "created_at": "2026-07-10T00:00:01Z",
            "trust_level": "local_verified",
            "evidence_kind": "command_execution",
            "command": {
                "argv": ["python", "-m", "unittest"],
                "cwd": ".",
                "started_at": "2026-07-10T00:00:00Z",
                "ended_at": "2026-07-10T00:00:01Z",
                "exit_code": 0,
                "log_path": "run.log",
                "log_sha256": sha256_path(self.log),
                "log_size": log_stat.st_size,
                "log_mtime_ns": log_stat.st_mtime_ns,
            },
            "environment": {
                "commit": commit,
                "workspace_revision": gt.source_manifest_sha256(
                    self.root, ["source.py"]
                ),
                "source_paths": ["source.py"],
                "platform": "test-platform",
                "python_version": "3.x-test",
                "ledger_revision": 3,
                "ledger_prefix_sha256": gt.ledger_prefix_sha256(self.ledger_events, 3),
            },
        }
        self.bind_execution_record(self.good, "execution-EVD-1.json")

    def bind_execution_record(self, doc: dict, filename: str) -> None:
        command = doc["command"]
        record = {
            "schema_version": "goal-teams-v2.3",
            "record_type": "command_execution",
            "evidence_id": doc["evidence_id"],
            "check_id": doc["check_id"],
            "run_id": doc["run_id"],
            "attempt_id": doc["attempt_id"],
            "producer_run_id": doc["producer_run_id"],
            "argv": command["argv"],
            "cwd": command["cwd"],
            "started_at": command["started_at"],
            "ended_at": command["ended_at"],
            "exit_code": command["exit_code"],
            "log_path": command["log_path"],
            "log_sha256": command["log_sha256"],
            "log_size": command["log_size"],
        }
        path = self.root / filename
        path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        command.update(
            {
                "execution_record_path": filename,
                "execution_record_sha256": sha256_path(path),
                "execution_record_size": path.stat().st_size,
            }
        )
        self.bind_integrity_replay(doc, f"integrity-{doc['evidence_id']}.log")

    def bind_integrity_replay(self, doc: dict, filename: str) -> None:
        binding_digest = gt.evidence_replay_binding_digest(doc)
        argv = gt.artifact_verifier_argv(
            doc["artifact_ref"], doc["artifact_sha256"], binding_digest
        )
        proc = subprocess.run(
            argv,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0 or proc.stderr:
            raise AssertionError(
                f"fixture integrity replay failed: {proc.returncode} {proc.stderr!r}"
            )
        path = self.root / filename
        path.write_bytes(proc.stdout)
        stat = path.stat()
        doc["integrity_replay"] = {
            "argv": argv,
            "cwd": ".",
            "started_at": doc["command"]["ended_at"],
            "ended_at": doc["created_at"],
            "exit_code": proc.returncode,
            "log_path": filename,
            "log_sha256": sha256_path(path),
            "log_size": stat.st_size,
            "log_mtime_ns": stat.st_mtime_ns,
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()


class EvidenceValidatorTests(EvidenceFixture):
    def test_complete_locally_verified_evidence_passes(self) -> None:
        self.assertEqual(
            gt.validate_evidence(self.good, self.root, ledger_events=self.ledger_events),
            [],
        )

    def test_domain_execution_and_locked_integrity_replay_are_both_required(self) -> None:
        missing_domain = clone(self.good)
        missing_domain.pop("command")
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    missing_domain, self.root, ledger_events=self.ledger_events
                ),
                "E_COMMAND_OBJECT",
            )
        )

        missing_integrity = clone(self.good)
        missing_integrity.pop("integrity_replay")
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    missing_integrity, self.root, ledger_events=self.ledger_events
                ),
                "E_INTEGRITY_REPLAY_OBJECT",
            )
        )

        failed_domain = clone(self.good)
        failed_domain["command"]["exit_code"] = 1
        self.bind_execution_record(failed_domain, "execution-domain-failed.json")
        errors = gt.validate_evidence(
            failed_domain, self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(has_error(errors, "E_COMMAND_EXIT"), errors)
        registry, registry_errors = gt.build_evidence_registry(
            [failed_domain], self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(registry_errors)
        self.assertFalse(registry[failed_domain["evidence_id"]]["valid_for_acceptance"])

        swapped = clone(self.good)
        swapped["command"], swapped["integrity_replay"] = (
            swapped["integrity_replay"],
            swapped["command"],
        )
        errors = gt.validate_evidence(
            swapped, self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(
            has_error(errors, "E_COMMAND_PROVENANCE")
            or has_error(errors, "E_INTEGRITY_REPLAY_POLICY"),
            errors,
        )

        same_log = clone(self.good)
        same_log["integrity_replay"].update(
            log_path=same_log["command"]["log_path"],
            log_sha256=same_log["command"]["log_sha256"],
            log_size=same_log["command"]["log_size"],
            log_mtime_ns=same_log["command"]["log_mtime_ns"],
        )
        errors = gt.validate_evidence(
            same_log, self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(has_error(errors, "E_INTEGRITY_REPLAY_SEPARATION"), errors)

        unbound_domain = clone(self.good)
        unbound_domain["command"]["argv"] = ["different-domain-command"]
        errors = gt.validate_evidence(
            unbound_domain, self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(
            has_error(errors, "E_COMMAND_PROVENANCE_BINDING")
            or has_error(errors, "E_INTEGRITY_REPLAY_BINDING"),
            errors,
        )

    def test_completion_replay_never_executes_the_recorded_domain_argv(self) -> None:
        sentinel = self.root / "domain-sentinel"
        script = self.root / "malicious-domain.py"
        script.write_text(
            "from pathlib import Path\nPath('domain-sentinel').write_text('executed')\n",
            encoding="utf-8",
        )
        doc = clone(self.good)
        doc["command"]["argv"] = [sys.executable, str(script)]
        self.bind_execution_record(doc, "execution-domain-sentinel.json")
        self.assertEqual(
            gt.validate_evidence(doc, self.root, ledger_events=self.ledger_events),
            [],
        )
        self.assertEqual(gt.validate_evidence_command_replay(doc, self.root), [])
        self.assertFalse(sentinel.exists(), "integrity replay executed the domain argv")

    def test_integrity_success_cannot_mask_execution_record_log_or_identity_tampering(self) -> None:
        execution_path = self.root / self.good["command"]["execution_record_path"]
        execution_original = execution_path.read_bytes()
        log_original = self.log.read_bytes()
        try:
            execution_path.write_text("{}\n", encoding="utf-8")
            errors = gt.validate_evidence(
                self.good, self.root, ledger_events=self.ledger_events
            )
            self.assertTrue(has_error(errors, "E_COMMAND_PROVENANCE_HASH"), errors)
            execution_path.write_bytes(execution_original)

            self.log.write_text("tampered domain log\n", encoding="utf-8")
            errors = gt.validate_evidence(
                self.good, self.root, ledger_events=self.ledger_events
            )
            self.assertTrue(has_error(errors, "E_LOG_HASH"), errors)
            self.log.write_bytes(log_original)

            forged_identity = clone(self.good)
            forged_identity["producer_run_id"] = "RUN-FORGED-PRODUCER"
            errors = gt.validate_evidence(
                forged_identity, self.root, ledger_events=self.ledger_events
            )
            self.assertTrue(
                has_error(errors, "E_COMMAND_PROVENANCE_BINDING")
                or has_error(errors, "E_INTEGRITY_REPLAY_BINDING"),
                errors,
            )
        finally:
            execution_path.write_bytes(execution_original)
            self.log.write_bytes(log_original)

    def test_execution_record_rejects_extra_secret_fields_even_when_rebound(self) -> None:
        doc = clone(self.good)
        original_execution = self.root / doc["command"]["execution_record_path"]
        execution = json.loads(original_execution.read_text(encoding="utf-8"))
        execution["extra_claim"] = "sk-" + "proj-1234567890abcdefghijklmnopqrstuv"
        execution_path = self.root / "execution-extra-secret.json"
        execution_path.write_text(
            json.dumps(execution, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        doc["command"].update(
            execution_record_path=execution_path.name,
            execution_record_sha256=sha256_path(execution_path),
            execution_record_size=execution_path.stat().st_size,
        )
        binding_digest = gt.evidence_replay_binding_digest(doc)
        argv = gt.artifact_verifier_argv(
            doc["artifact_ref"], doc["artifact_sha256"], binding_digest
        )
        proc = subprocess.run(
            argv,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        integrity_log = self.root / "integrity-extra-secret.log"
        integrity_log.write_bytes(proc.stdout)
        doc["integrity_replay"].update(
            argv=argv,
            exit_code=proc.returncode,
            log_path=integrity_log.name,
            log_sha256=sha256_path(integrity_log),
            log_size=integrity_log.stat().st_size,
            log_mtime_ns=integrity_log.stat().st_mtime_ns,
        )
        errors = gt.validate_evidence(
            doc, self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(has_error(errors, "E_COMMAND_PROVENANCE_BINDING"), errors)
        self.assertTrue(has_error(errors, "E_COMMAND_PROVENANCE_SECRET"), errors)
        self.assertTrue(has_error(errors, "E_SECRET_PRESENT"), errors)

    def test_fail_closed_mutation_matrix(self) -> None:
        outside = self.root.parent / f"outside-{self.root.name}.txt"
        outside.write_text("outside", encoding="utf-8")
        try:
            cases = {
                "nonzero_exit": (lambda doc: doc["command"].update(exit_code=1), "E_COMMAND_EXIT"),
                "missing_log": (lambda doc: doc["command"].update(log_path="missing.log"), "E_LOG_MISSING"),
                "cwd_escape": (lambda doc: doc["command"].update(cwd=".."), "E_CWD_CONTAINMENT"),
                "artifact_escape": (lambda doc: doc.update(artifact_ref=f"../{outside.name}"), "E_PATH_CONTAINMENT"),
                "artifact_mtime": (lambda doc: doc.update(artifact_mtime_ns=0), "E_MTIME_MISMATCH"),
                "artifact_hash": (lambda doc: doc.update(artifact_sha256="0" * 64), "E_HASH_MISMATCH"),
                "stale_commit": (lambda doc: doc["environment"].update(commit="0" * 40), "E_COMMIT_MISMATCH"),
                "invalid_trust": (lambda doc: doc.update(trust_level="local"), "E_TRUST_LEVEL"),
                "artifact_ref_type": (lambda doc: doc.update(artifact_ref=["artifact.txt"]), "E_EVIDENCE_TYPE"),
                "argv_type": (lambda doc: doc["command"].update(argv="true"), "E_COMMAND_ARGV"),
                "exit_type": (lambda doc: doc["command"].update(exit_code="0"), "E_COMMAND_EXIT_CODE"),
                "environment_type": (lambda doc: doc.update(environment="test"), "E_ENVIRONMENT"),
                "zero_ledger_revision": (
                    lambda doc: doc["environment"].update(ledger_revision=0),
                    "E_EVIDENCE_LEDGER_REVISION",
                ),
                "forged_ledger_revision": (
                    lambda doc: doc["environment"].update(ledger_revision=999),
                    "E_EVIDENCE_LEDGER_REVISION",
                ),
                "forged_ledger_prefix": (
                    lambda doc: doc["environment"].update(ledger_prefix_sha256="0" * 64),
                    "E_EVIDENCE_LEDGER_PREFIX",
                ),
                "missing_source_paths": (
                    lambda doc: doc["environment"].update(source_paths=[]),
                    "E_SOURCE_PATHS",
                ),
                "source_path_escape": (
                    lambda doc: doc["environment"].update(source_paths=["../source.py"]),
                    "E_SOURCE_PATH_INVALID",
                ),
            }
            for name, (mutate, expected) in cases.items():
                with self.subTest(case=name):
                    doc = clone(self.good)
                    mutate(doc)
                    errors = gt.validate_evidence(doc, self.root, ledger_events=self.ledger_events)
                    self.assertTrue(errors, f"mutation {name} was accepted")
                    self.assertTrue(has_error(errors, expected), f"{name}: expected {expected}, got {errors}")
        finally:
            outside.unlink(missing_ok=True)

    def test_normal_evidence_requires_immutable_current_source_manifest(self) -> None:
        symbolic = clone(self.good)
        symbolic["environment"].update(commit="HEAD", workspace_revision="HEAD")
        symbolic_errors = gt.validate_evidence(
            symbolic, self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(has_error(symbolic_errors, "E_COMMIT_MISMATCH"))
        self.assertTrue(
            has_error(symbolic_errors, "E_WORKSPACE_REVISION_MISMATCH")
        )

        self.source.write_text("VALUE = 'mutated-after-evidence'\n", encoding="utf-8")
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    self.good, self.root, ledger_events=self.ledger_events
                ),
                "E_SOURCE_COMMIT_DRIFT",
            )
        )
        forged_current = clone(self.good)
        forged_current["environment"]["workspace_revision"] = gt.source_manifest_sha256(
            self.root, ["source.py"]
        )
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    forged_current, self.root, ledger_events=self.ledger_events
                ),
                "E_SOURCE_COMMIT_DRIFT",
            ),
            "updating the claimed digest must not legitimize dirty source",
        )

        untracked = self.root / "untracked-source.py"
        untracked.write_text("VALUE = 'untracked'\n", encoding="utf-8")
        forged_untracked = clone(self.good)
        forged_untracked["environment"].update(
            source_paths=[untracked.name],
            workspace_revision=gt.source_manifest_sha256(
                self.root, [untracked.name]
            ),
        )
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    forged_untracked, self.root, ledger_events=self.ledger_events
                ),
                "E_SOURCE_PATH_UNTRACKED",
            )
        )

    def test_source_added_or_changed_after_bound_commit_cannot_be_rebound(self) -> None:
        original_commit = self.good["environment"]["commit"]
        self.source.write_text("VALUE = 'changed-in-descendant'\n", encoding="utf-8")
        added = self.root / "descendant-source.py"
        added.write_text("VALUE = 'added-in-descendant'\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", self.source.name, added.name], cwd=self.root, check=True
        )
        subprocess.run(
            ["git", "commit", "-qm", "change source in descendant"],
            cwd=self.root,
            check=True,
        )

        changed = clone(self.good)
        changed["environment"].update(
            commit=original_commit,
            workspace_revision=gt.source_manifest_sha256(
                self.root, [self.source.name]
            ),
        )
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    changed, self.root, ledger_events=self.ledger_events
                ),
                "E_SOURCE_COMMIT_DRIFT",
            )
        )

        missing_at_bound_commit = clone(self.good)
        missing_at_bound_commit["environment"].update(
            commit=original_commit,
            source_paths=[added.name],
            workspace_revision=gt.source_manifest_sha256(
                self.root, [added.name]
            ),
        )
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    missing_at_bound_commit,
                    self.root,
                    ledger_events=self.ledger_events,
                ),
                "E_SOURCE_PATH_UNTRACKED",
            )
        )

    def test_descendant_commit_touching_only_non_source_keeps_evidence_current(self) -> None:
        note = self.root / "evidence-note.json"
        note.write_text('{"kind":"non-source"}\n', encoding="utf-8")
        subprocess.run(["git", "add", note.name], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "record non-source evidence metadata"],
            cwd=self.root,
            check=True,
        )
        self.assertEqual(
            gt.validate_evidence(
                self.good, self.root, ledger_events=self.ledger_events
            ),
            [],
        )

    def test_missing_ledger_and_nonprefix_history_fail_closed(self) -> None:
        self.assertTrue(
            has_error(
                gt.validate_evidence(self.good, self.root),
                "E_EVIDENCE_LEDGER_UNAVAILABLE",
            )
        )
        forged_history = clone(self.ledger_events)
        forged_history[0]["payload"]["title"] = "forged non-prefix history"
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    self.good,
                    self.root,
                    ledger_events=forged_history,
                ),
                "E_EVIDENCE_LEDGER_PREFIX",
            )
        )

    def test_prefix_context_and_evidence_time_order_cannot_be_degenerated(self) -> None:
        too_early = clone(self.good)
        too_early["environment"].update(
            ledger_revision=1,
            ledger_prefix_sha256=gt.ledger_prefix_sha256(self.ledger_events, 1),
        )
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    too_early, self.root, ledger_events=self.ledger_events
                ),
                "E_EVIDENCE_LEDGER_CONTEXT",
            )
        )

        before_prefix = clone(self.good)
        before_prefix["created_at"] = "2026-07-09T23:59:58Z"
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    before_prefix, self.root, ledger_events=self.ledger_events
                ),
                "E_EVIDENCE_LEDGER_TIME",
            )
        )

    def test_prefix_context_is_task_exact_for_single_and_shared_references(self) -> None:
        def check_event(
            event_id: str,
            task_id: str,
            base_revision: int,
            evidence_id: str,
        ) -> dict:
            value = task_event(
                event_id,
                task_id,
                base_revision,
                "review",
                attempt_id="ATT-SHARED",
                payload={
                    "check_state": "passed",
                    "evidence_refs": [evidence_id],
                    "validation_check_id": "CHECK-1",
                    "validation_run_id": "RUN-1",
                },
            )
            value.update(
                {
                    "event_type": "check_executed",
                    "actor_run_id": f"RUN-VALIDATOR-{task_id}",
                    "validation_check_id": "CHECK-1",
                    "validation_run_id": "RUN-1",
                }
            )
            return value

        def timestamp(events: list[dict]) -> None:
            for second, event in enumerate(events):
                event["timestamp"] = f"2026-07-10T00:00:{second:02d}Z"

        def evidence_for(events: list[dict], prefix_revision: int, *, created_at: str) -> dict:
            value = clone(self.good)
            value["attempt_id"] = "ATT-SHARED"
            for key in (
                "execution_record_path",
                "execution_record_sha256",
                "execution_record_size",
            ):
                value["command"].pop(key, None)
            value["command"].update(
                started_at=events[prefix_revision - 1]["timestamp"],
                ended_at=created_at,
            )
            value["created_at"] = created_at
            value["environment"].update(
                ledger_revision=prefix_revision,
                ledger_prefix_sha256=gt.ledger_prefix_sha256(events, prefix_revision),
            )
            return value

        # TASK-A provides the same attempt id in the prefix, but only TASK-B
        # consumes the Evidence later. TASK-A must not satisfy TASK-B's context.
        single_reference = [
            task_event("EXACT-1", "TASK-A", 0, "planned", attempt_id="ATT-SHARED"),
            task_event("EXACT-2", "TASK-A", 1, "running", attempt_id="ATT-SHARED"),
            task_event("EXACT-3", "TASK-B", 0, "planned", attempt_id="ATT-SHARED"),
            task_event("EXACT-4", "TASK-B", 1, "running", attempt_id="ATT-SHARED"),
            task_event("EXACT-5", "TASK-B", 2, "review", attempt_id="ATT-SHARED"),
            check_event("EXACT-6", "TASK-B", 3, "EVD-1"),
        ]
        timestamp(single_reference)
        wrong_task = evidence_for(single_reference, 2, created_at="2026-07-10T00:00:05Z")
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    wrong_task, self.root, ledger_events=single_reference
                ),
                "E_EVIDENCE_LEDGER_CONTEXT",
            )
        )

        # A shared Evidence may be referenced by multiple tasks only when every
        # consuming task was already running/review at the bound prefix.
        shared_reference = [
            task_event("SHARED-1", "TASK-A", 0, "planned", attempt_id="ATT-SHARED"),
            task_event("SHARED-2", "TASK-A", 1, "running", attempt_id="ATT-SHARED"),
            task_event("SHARED-3", "TASK-B", 0, "planned", attempt_id="ATT-SHARED"),
            task_event("SHARED-4", "TASK-A", 2, "review", attempt_id="ATT-SHARED"),
            check_event("SHARED-5", "TASK-A", 3, "EVD-1"),
            task_event("SHARED-6", "TASK-B", 1, "running", attempt_id="ATT-SHARED"),
            task_event("SHARED-7", "TASK-B", 2, "review", attempt_id="ATT-SHARED"),
            check_event("SHARED-8", "TASK-B", 3, "EVD-1"),
        ]
        timestamp(shared_reference)
        partially_bound = evidence_for(
            shared_reference, 3, created_at="2026-07-10T00:00:04Z"
        )
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    partially_bound, self.root, ledger_events=shared_reference
                ),
                "E_EVIDENCE_LEDGER_CONTEXT",
            )
        )

        after_reference = clone(self.good)
        after_reference["created_at"] = "2026-07-10T00:00:03Z"
        self.assertTrue(
            has_error(
                gt.validate_evidence(
                    after_reference, self.root, ledger_events=self.ledger_events
                ),
                "E_EVIDENCE_LEDGER_TIME",
            )
        )

    def test_artifact_modified_after_run_invalidates_old_evidence(self) -> None:
        self.artifact.write_text("modified after verification\n", encoding="utf-8")
        errors = gt.validate_evidence(self.good, self.root, ledger_events=self.ledger_events)
        self.assertTrue(has_error(errors, "E_HASH_MISMATCH"))

    def test_raw_authorization_in_bound_log_is_rejected_even_when_hash_matches(self) -> None:
        self.log.write_text(
            "Authorization: Bearer dummy-fixture-raw-token\n", encoding="utf-8"
        )
        stat = self.log.stat()
        doc = clone(self.good)
        doc["command"].update(
            {
                "log_sha256": sha256_path(self.log),
                "log_size": stat.st_size,
                "log_mtime_ns": stat.st_mtime_ns,
            }
        )
        errors = gt.validate_evidence(doc, self.root, ledger_events=self.ledger_events)
        self.assertTrue(has_error(errors, "E_SECRET_PRESENT"), errors)
        self.assertTrue(has_error(errors, "E_LOG_SECRET"), errors)

    def test_evidence_union_records_are_structural_but_only_local_success_is_acceptance_valid(self) -> None:
        success = clone(self.good)
        failure = clone(self.good)
        failure.update(
            {
                "evidence_id": "EVD-FAILURE",
                "evidence_kind": "failure_record",
                "trust_level": "local_verified",
            }
        )
        failure["command"]["exit_code"] = 1
        for key in ("execution_record_path", "execution_record_sha256", "execution_record_size"):
            failure["command"].pop(key, None)
        self.bind_execution_record(failure, "execution-EVD-FAILURE.json")

        manual = clone(self.good)
        manual.update(
            {
                "evidence_id": "EVD-MANUAL",
                "evidence_kind": "manual_observation",
                "trust_level": "manual_observation",
                "observation": {
                    "observer_run_id": self.good["producer_run_id"],
                    "method": "independent visual inspection",
                    "observed_at": "2026-07-10T00:00:00Z",
                },
            }
        )
        manual.pop("command")
        manual.pop("integrity_replay")

        external = clone(self.good)
        external.update(
            {
                "evidence_id": "EVD-EXTERNAL",
                "evidence_kind": "external_reference",
                "trust_level": "externally_referenced",
                "external_reference": {
                    "source": "authoritative fixture",
                    "uri": "https://example.invalid/evidence",
                    "retrieved_at": "2026-07-10T00:00:00Z",
                },
            }
        )
        external.pop("command")
        external.pop("integrity_replay")

        unverified_failure = clone(failure)
        unverified_failure["evidence_id"] = "EVD-UNVERIFIED"
        unverified_failure["trust_level"] = "unverified"
        self.bind_execution_record(
            unverified_failure, "execution-EVD-UNVERIFIED.json"
        )
        records = [success, failure, manual, external, unverified_failure]
        for record in records:
            with self.subTest(kind=record["evidence_kind"], trust=record["trust_level"]):
                self.assertEqual(
                    gt.validate_evidence(record, self.root, ledger_events=self.ledger_events),
                    [],
                )
        registry, errors = gt.build_evidence_registry(
            records, self.root, ledger_events=self.ledger_events
        )
        self.assertEqual(errors, [])
        self.assertTrue(registry["EVD-1"]["valid_for_acceptance"])
        for evidence_id in ("EVD-FAILURE", "EVD-MANUAL", "EVD-EXTERNAL", "EVD-UNVERIFIED"):
            with self.subTest(evidence_id=evidence_id):
                self.assertTrue(registry[evidence_id]["structurally_valid"])
                self.assertFalse(registry[evidence_id]["valid_for_acceptance"])

        for record in records:
            with self.subTest(secret_scan=record["evidence_id"]):
                mutated = clone(record)
                self.artifact.write_text(
                    "Authorization: Bearer dummy-fixture-raw-union\n",
                    encoding="utf-8",
                )
                stat = self.artifact.stat()
                mutated.update(
                    {
                        "artifact_sha256": sha256_path(self.artifact),
                        "artifact_size": stat.st_size,
                        "artifact_mtime_ns": stat.st_mtime_ns,
                    }
                )
                self.assertTrue(
                    has_error(
                        gt.validate_evidence(mutated, self.root, ledger_events=self.ledger_events),
                        "E_ARTIFACT_SECRET",
                    )
                )
                self.artifact.write_text("verified artifact\n", encoding="utf-8")

        for record in records:
            with self.subTest(hash_binding=record["evidence_id"]):
                mutated = clone(record)
                mutated["artifact_sha256"] = "0" * 64
                self.assertTrue(
                    has_error(
                        gt.validate_evidence(mutated, self.root, ledger_events=self.ledger_events),
                        "E_HASH_MISMATCH",
                    )
                )


class TraceabilityValidatorTests(EvidenceFixture):
    def graph(self) -> dict:
        first = clone(self.good)
        first["current"] = True
        second = clone(self.good)
        second.update(
            {
                "evidence_id": "EVD-2",
                "check_id": "CHECK-2",
                "run_id": "RUN-2",
                "attempt_id": "ATT-1",
                "current": True,
            }
        )
        self.bind_execution_record(second, "execution-EVD-2.json")
        return {
            "requirements": [{"id": "REQ-1"}],
            "acceptance_criteria": [
                {"id": "AC-1", "required": True},
                {"id": "AC-2", "required": True},
            ],
            "tasks": [
                {
                    "schema_version": "goal-teams-v2.3",
                    "task_id": "TASK-1",
                    "title": "Fully bound task",
                    "task_state": "accepted",
                    "required_for_done": True,
                    "acceptance_blocking": True,
                    "owner_member_id": "实现-1",
                    "validator_member_id": "评审-1",
                    "owner_run_id": "RUN-OWNER",
                    "validator_run_id": "RUN-VALIDATOR",
                    "merge_owner_run_id": "RUN-LEDGER-OWNER",
                    "check_state": "passed",
                    "requirement_refs": ["REQ-1"],
                    "acceptance_criteria_refs": ["AC-1"],
                    "attempt_id": "ATT-1",
                    "revision": 4,
                    "artifact_refs": ["artifact.txt"],
                    "evidence_refs": ["EVD-1"],
                    "harness_refs": ["harness.json"],
                    "last_actor_run_id": "RUN-VALIDATOR",
                    "validation_check_id": "CHECK-1",
                    "validation_run_id": "RUN-1",
                },
                {
                    "schema_version": "goal-teams-v2.3",
                    "task_id": "TASK-2",
                    "title": "Second fully bound task",
                    "task_state": "accepted",
                    "required_for_done": True,
                    "acceptance_blocking": True,
                    "owner_member_id": "实现-2",
                    "validator_member_id": "评审-2",
                    "owner_run_id": "RUN-OWNER-2",
                    "validator_run_id": "RUN-VALIDATOR",
                    "merge_owner_run_id": "RUN-LEDGER-OWNER",
                    "check_state": "passed",
                    "requirement_refs": ["REQ-1"],
                    "acceptance_criteria_refs": ["AC-2"],
                    "attempt_id": "ATT-1",
                    "revision": 4,
                    "artifact_refs": ["artifact.txt"],
                    "evidence_refs": ["EVD-2"],
                    "harness_refs": ["harness.json"],
                    "last_actor_run_id": "RUN-VALIDATOR",
                    "validation_check_id": "CHECK-2",
                    "validation_run_id": "RUN-2",
                },
            ],
            "checks": [
                {
                    "schema_version": "goal-teams-v2.3",
                    "check_id": "CHECK-1",
                    "check_state": "passed",
                    "required": True,
                    "acceptance_blocking": True,
                    "acceptance_criteria_refs": ["AC-1"],
                    "validator_run_id": "RUN-VALIDATOR",
                    "evidence_refs": ["EVD-1"],
                    "expected_domain_execution": {
                        "argv": first["command"]["argv"],
                        "cwd": first["command"]["cwd"],
                    },
                },
                {
                    "schema_version": "goal-teams-v2.3",
                    "check_id": "CHECK-2",
                    "check_state": "passed",
                    "required": True,
                    "acceptance_blocking": True,
                    "acceptance_criteria_refs": ["AC-2"],
                    "validator_run_id": "RUN-VALIDATOR",
                    "evidence_refs": ["EVD-2"],
                    "expected_domain_execution": {
                        "argv": second["command"]["argv"],
                        "cwd": second["command"]["cwd"],
                    },
                },
            ],
            "runs": [
                {
                    "schema_version": "goal-teams-v2.3",
                    "run_id": "RUN-1",
                    "attempt_id": "ATT-1",
                    "check_id": "CHECK-1",
                    "producer_run_id": "RUN-PRODUCER-1",
                    "status": "passed",
                    "started_at": "2026-07-10T00:00:00Z",
                    "ended_at": "2026-07-10T00:00:01Z",
                    "evidence_refs": ["EVD-1"],
                },
                {
                    "schema_version": "goal-teams-v2.3",
                    "run_id": "RUN-2",
                    "attempt_id": "ATT-1",
                    "check_id": "CHECK-2",
                    "producer_run_id": "RUN-PRODUCER-1",
                    "status": "passed",
                    "started_at": "2026-07-10T00:00:00Z",
                    "ended_at": "2026-07-10T00:00:01Z",
                    "evidence_refs": ["EVD-2"],
                },
            ],
            "evidence": [first, second],
        }

    def test_each_required_ac_needs_its_own_current_evidence(self) -> None:
        graph = self.graph()
        graph["evidence"] = graph["evidence"][:1]
        result = gt.validate_traceability(graph, self.root, ledger_events=self.ledger_events)
        self.assertFalse(result["ok"])
        self.assertIn("AC-2", result["uncovered_acceptance_criteria"])

    def test_each_required_ac_independently_passes_when_fully_bound(self) -> None:
        result = gt.validate_traceability(
            self.graph(), self.root, ledger_events=self.ledger_events
        )
        self.assertTrue(result["ok"], result)

    def test_orphan_task_and_evidence_are_reported(self) -> None:
        graph = self.graph()
        graph["tasks"].append(
            {"task_id": "TASK-ORPHAN", "requirement_refs": ["REQ-MISSING"], "acceptance_criteria_refs": []}
        )
        graph["evidence"].append(
            {"evidence_id": "EVD-ORPHAN", "check_id": "CHECK-MISSING", "run_id": "RUN-X", "current": True}
        )
        result = gt.validate_traceability(graph, self.root, ledger_events=self.ledger_events)
        self.assertFalse(result["ok"])
        self.assertIn("TASK-ORPHAN", result["orphan_tasks"])
        self.assertIn("EVD-ORPHAN", result["orphan_evidence"])

    def test_id_only_nodes_are_rejected_instead_of_counting_as_proof(self) -> None:
        id_only = {
            "requirements": [{"id": "REQ-1"}],
            "acceptance_criteria": [{"id": "AC-1", "required": True}],
            "tasks": [{"task_id": "TASK-1", "requirement_refs": ["REQ-1"], "acceptance_criteria_refs": ["AC-1"]}],
            "checks": [{"check_id": "CHECK-1", "acceptance_criteria_refs": ["AC-1"]}],
            "runs": [{"run_id": "RUN-1", "check_id": "CHECK-1", "status": "passed"}],
            "evidence": [{"evidence_id": "EVD-1", "check_id": "CHECK-1", "run_id": "RUN-1", "current": True}],
        }
        result = gt.validate_traceability(id_only, self.root, ledger_events=self.ledger_events)
        self.assertFalse(result["ok"])
        self.assertIn("E_TRACEABILITY_NODE_INVALID", result["errors"])

    def test_nonlocal_trust_levels_never_count_as_acceptance_evidence(self) -> None:
        for trust in ("externally_referenced", "manual_observation", "unverified"):
            with self.subTest(trust=trust):
                graph = self.graph()
                graph["evidence"][1]["trust_level"] = trust
                result = gt.validate_traceability(
                    graph, self.root, ledger_events=self.ledger_events
                )
                self.assertFalse(result["ok"])
                self.assertIn("AC-2", result["uncovered_acceptance_criteria"])
                self.assertNotIn("EVD-2", result["valid_evidence_ids"])
                self.assertIn("E_TRACEABILITY_ORPHAN", result["errors"])

    def test_required_ac_rejects_split_task_validation_path(self) -> None:
        graph = self.graph()
        task = graph["tasks"][0]
        task["acceptance_criteria_refs"] = ["AC-1"]
        task["validation_check_id"] = "CHECK-2"
        task["validation_run_id"] = "RUN-2"
        task["evidence_refs"] = ["EVD-2"]
        result = gt.validate_traceability(
            graph, self.root, ledger_events=self.ledger_events
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("E_TRACEABILITY_SPLIT_PATH", result["errors"], result)
        self.assertIn("AC-1", result["uncovered_acceptance_criteria"], result)

    def test_optional_planned_task_cannot_cover_a_required_ac(self) -> None:
        graph = self.graph()
        graph["acceptance_criteria"] = [
            item for item in graph["acceptance_criteria"] if item["id"] == "AC-1"
        ]
        graph["checks"] = [graph["checks"][0]]
        graph["runs"] = [graph["runs"][0]]
        graph["evidence"] = [graph["evidence"][0]]
        graph["tasks"] = [graph["tasks"][0]]
        task = graph["tasks"][0]
        task.update(
            task_state="planned",
            check_state="not_started",
            required_for_done=False,
            acceptance_blocking=False,
            acceptance_criteria_refs=["AC-1"],
            evidence_refs=[],
            nonblocking_reason="optional work is still planned",
        )
        task.pop("validation_check_id", None)
        task.pop("validation_run_id", None)
        result = gt.validate_traceability(
            graph, self.root, ledger_events=self.ledger_events
        )
        self.assertFalse(result["ok"], result)
        self.assertIn("E_TRACEABILITY_UNCOVERED", result["errors"], result)
        self.assertIn("AC-1", result["uncovered_acceptance_criteria"], result)

    def test_run_evidence_producer_and_task_validator_attribution_are_bound(self) -> None:
        producer_mismatch = self.graph()
        producer_mismatch["runs"][0]["producer_run_id"] = "RUN-DIFFERENT-PRODUCER"
        result = gt.validate_traceability(
            producer_mismatch, self.root, ledger_events=self.ledger_events
        )
        self.assertFalse(result["ok"], result)
        self.assertTrue(has_error(result["errors"], "E_RUN_EVIDENCE_BINDING"), result)

        validator_mismatch = self.graph()
        validator_mismatch["tasks"][0]["validator_run_id"] = "RUN-DIFFERENT-VALIDATOR"
        result = gt.validate_traceability(
            validator_mismatch, self.root, ledger_events=self.ledger_events
        )
        self.assertFalse(result["ok"], result)
        self.assertTrue(has_error(result["errors"], "E_TASK_VALIDATION_BINDING"), result)
        self.assertIn("AC-1", result["uncovered_acceptance_criteria"], result)


class DualReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(dir=ROOT / "examples")
        self.root = Path(self.tempdir.name)
        self.artifact = self.root / "artifact.txt"
        self.script_evidence = self.root / "script-review.json"
        self.script_log = self.root / "script-review.log"
        self.llm_evidence = self.root / "semantic-review.md"
        self.artifact.write_text("reviewed artifact\n", encoding="utf-8")
        self.baseline = self.root / "baseline" / "artifact.txt"
        self.baseline.parent.mkdir()
        self.baseline.write_bytes(self.artifact.read_bytes())
        artifact_hash = sha256_path(self.artifact)
        self.script_log.write_text("artifact comparison passed\n", encoding="utf-8")
        self.script_evidence.write_text(
            json.dumps(
                {
                    "schema_version": "goal-teams-v2.3",
                    "ok": True,
                    "error_code": None,
                    "exit_code": 0,
                    "tool": "validate-artifact",
                    "reviewer_run_id": "RUN-SCRIPT",
                    "artifact_ref": "artifact.txt",
                    "artifact_sha256": artifact_hash,
                    "artifact_version": "V2.3",
                    "command": {
                        "argv": ["validate-artifact", "artifact.txt"],
                        "exit_code": 0,
                        "log_path": "script-review.log",
                        "log_sha256": sha256_path(self.script_log),
                    },
                }
            ),
            encoding="utf-8",
        )
        self.llm_evidence.write_text(
            "---\ntype: Semantic Review\ntitle: Independent review\n"
            "reviewer_run_id: RUN-REVIEWER\nartifact_version: V2.3\n"
            f"artifact_sha256: {artifact_hash}\n---\npass\n",
            encoding="utf-8",
        )
        script_size = self.script_evidence.stat().st_size
        llm_size = self.llm_evidence.stat().st_size
        self.good = {
            "schema_version": "goal-teams-v2.3",
            "review_class": "comparison",
            "author_run_id": "RUN-AUTHOR",
            "reviewer_run_id": "RUN-REVIEWER",
            "artifact": {
                "artifact_ref": "artifact.txt",
                "artifact_sha256": artifact_hash,
                "artifact_version": "V2.3",
            },
            "script_review": {
                "reviewer_run_id": "RUN-SCRIPT",
                "tool": "compare-artifacts",
                "status": "passed",
                "exit_code": 0,
                "evidence_path": "script-review.json",
                "evidence_sha256": sha256_path(self.script_evidence),
                "evidence_size": script_size,
                "artifact_sha256": artifact_hash,
                "artifact_version": "V2.3",
            },
            "llm_review": {
                "reviewer_run_id": "RUN-REVIEWER",
                "reviewer": "评审-V2.3",
                "status": "passed",
                "evidence_path": "semantic-review.md",
                "evidence_sha256": sha256_path(self.llm_evidence),
                "evidence_size": llm_size,
                "artifact_sha256": artifact_hash,
                "artifact_version": "V2.3",
                "summary": "语义与风险检查通过",
            },
            "final_decision": {"status": "pass", "reason": "independent checks passed"},
        }
        self.bind_script_review(self.good)

    def bind_script_review(self, doc: dict) -> None:
        artifact = doc["artifact"]
        tool = ROOT / "scripts" / "review" / "compare-artifacts.py"
        domain_argv = [
            "python3",
            "../../scripts/review/compare-artifacts.py",
            artifact["artifact_ref"],
            "baseline/artifact.txt",
        ]
        domain_proc = subprocess.run(
            domain_argv,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if domain_proc.returncode != 0 or domain_proc.stderr:
            raise AssertionError(
                f"comparison fixture failed: {domain_proc.returncode} {domain_proc.stderr!r}"
            )
        self.script_log.write_bytes(domain_proc.stdout)
        domain = {
            "argv": domain_argv,
            "cwd": ".",
            "started_at": "2026-07-10T00:00:00Z",
            "ended_at": "2026-07-10T00:00:01Z",
            "exit_code": 0,
            "log_path": self.script_log.name,
            "log_sha256": sha256_path(self.script_log),
            "log_size": self.script_log.stat().st_size,
        }
        report = {
            "schema_version": "goal-teams-v2.3",
            "ok": True,
            "error_code": None,
            "exit_code": 0,
            "tool": doc["script_review"]["tool"],
            "reviewer_run_id": doc["script_review"]["reviewer_run_id"],
            "artifact_ref": artifact["artifact_ref"],
            "artifact_sha256": artifact["artifact_sha256"],
            "artifact_version": artifact["artifact_version"],
            "domain_execution": domain,
            "comparison_inputs": {
                "actual_ref": artifact["artifact_ref"],
                "actual_sha256": artifact["artifact_sha256"],
                "baseline_ref": "baseline/artifact.txt",
                "baseline_sha256": sha256_path(self.baseline),
                "baseline_approver_run_id": "RUN-BASELINE-APPROVER",
                "baseline_approved_at": "2026-07-09T00:00:00Z",
            },
            "comparison_mode": "exact_hash_match",
            "tool_ref": "scripts/review/compare-artifacts.py",
            "tool_sha256": sha256_path(tool),
        }
        binding_digest = gt.review_replay_binding_digest(doc, report)
        report["binding_digest"] = binding_digest
        argv = gt.artifact_verifier_argv(
            artifact["artifact_ref"], artifact["artifact_sha256"], binding_digest
        )
        proc = subprocess.run(
            argv,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0 or proc.stderr:
            raise AssertionError(
                f"review integrity replay failed: {proc.returncode} {proc.stderr!r}"
            )
        integrity_log = self.root / "script-review-integrity.log"
        integrity_log.write_bytes(proc.stdout)
        report["integrity_replay"] = {
            "argv": argv,
            "cwd": ".",
            "started_at": "2026-07-10T00:00:01Z",
            "ended_at": "2026-07-10T00:00:02Z",
            "exit_code": proc.returncode,
            "log_path": integrity_log.name,
            "log_sha256": sha256_path(integrity_log),
            "log_size": integrity_log.stat().st_size,
        }
        self.script_evidence.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        doc["script_review"].update(
            evidence_sha256=sha256_path(self.script_evidence),
            evidence_size=self.script_evidence.stat().st_size,
        )

    def persist_script_report(self, doc: dict, report: dict) -> None:
        self.script_evidence.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        doc["script_review"].update(
            evidence_sha256=sha256_path(self.script_evidence),
            evidence_size=self.script_evidence.stat().st_size,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_complete_independent_review_passes(self) -> None:
        self.assertEqual(gt.validate_dual_review(self.good, self.root), [])

    def test_review_domain_and_integrity_split_is_mandatory_and_domain_is_not_replayed(self) -> None:
        original_report = json.loads(self.script_evidence.read_text(encoding="utf-8"))

        def swap_channels(report: dict) -> None:
            report["domain_execution"], report["integrity_replay"] = (
                report["integrity_replay"],
                report["domain_execution"],
            )

        def reuse_domain_log(report: dict) -> None:
            domain = report["domain_execution"]
            report["integrity_replay"].update(
                log_path=domain["log_path"],
                log_sha256=domain["log_sha256"],
                log_size=domain["log_size"],
            )

        cases = {
            "missing_domain": (
                lambda report: report.pop("domain_execution"),
                "E_REVIEW_TOOL_PROVENANCE",
            ),
            "missing_integrity": (
                lambda report: report.pop("integrity_replay"),
                "E_REVIEW_TOOL_PROVENANCE",
            ),
            "failed_domain": (
                lambda report: report["domain_execution"].update(exit_code=1),
                "E_REVIEW_TOOL_PROVENANCE",
            ),
            "domain_log_hash": (
                lambda report: report["domain_execution"].update(log_sha256="0" * 64),
                "E_REVIEW_TOOL_PROVENANCE",
            ),
            "swapped_channels": (swap_channels, "E_REVIEW_TOOL_PROVENANCE"),
            "shared_log": (reuse_domain_log, "E_REVIEW_TOOL_PROVENANCE"),
            "unbound_domain_argv": (
                lambda report: report["domain_execution"].update(
                    argv=["different-domain-command"]
                ),
                "E_REVIEW_TOOL_REPLAY_BINDING",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(case=name):
                doc = clone(self.good)
                report = clone(original_report)
                mutate(report)
                self.persist_script_report(doc, report)
                errors = gt.validate_dual_review(doc, self.root)
                self.assertTrue(has_error(errors, expected), errors)

        doc = clone(self.good)
        report = clone(original_report)
        self.persist_script_report(doc, report)
        observed_argv: list[list[str]] = []
        original_run = gt.subprocess.run

        def recording_run(argv, *args, **kwargs):
            observed_argv.append(list(argv))
            return original_run(argv, *args, **kwargs)

        gt.subprocess.run = recording_run
        try:
            self.assertEqual(gt.validate_dual_review(doc, self.root), [])
        finally:
            gt.subprocess.run = original_run
        self.assertNotIn(report["domain_execution"]["argv"], observed_argv)
        self.assertTrue(
            any(argv[1:] == report["integrity_replay"]["argv"][1:] for argv in observed_argv),
            observed_argv,
        )

    def test_review_mutation_matrix_fails_closed(self) -> None:
        cases = {
            "missing_artifact": (lambda doc: doc["artifact"].update(artifact_ref="missing.txt"), "E_REVIEW_ARTIFACT_MISSING"),
            "missing_llm_evidence": (lambda doc: doc["llm_review"].update(evidence_path="missing.md"), "E_REVIEW_LLM_EVIDENCE"),
            "empty_author": (lambda doc: doc.update(author_run_id=""), "E_REVIEW_IDENTITY"),
            "empty_reviewer": (lambda doc: doc.update(reviewer_run_id=""), "E_REVIEW_IDENTITY"),
            "self_review": (lambda doc: doc.update(reviewer_run_id=doc["author_run_id"]), "E_REVIEW_SELF"),
            "script_hash_drift": (lambda doc: doc["script_review"].update(artifact_sha256="0" * 64), "E_REVIEW_ARTIFACT_BINDING"),
            "llm_hash_drift": (lambda doc: doc["llm_review"].update(artifact_sha256="0" * 64), "E_REVIEW_ARTIFACT_BINDING"),
            "artifact_hash_drift": (lambda doc: doc["artifact"].update(artifact_sha256="0" * 64), "E_REVIEW_ARTIFACT_HASH"),
            "script_evidence_hash_drift": (lambda doc: doc["script_review"].update(evidence_sha256="0" * 64), "E_REVIEW_EVIDENCE_HASH"),
            "llm_evidence_hash_drift": (lambda doc: doc["llm_review"].update(evidence_sha256="0" * 64), "E_REVIEW_EVIDENCE_HASH"),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(case=name):
                doc = clone(self.good)
                mutate(doc)
                errors = gt.validate_dual_review(doc, self.root)
                self.assertTrue(errors, f"review mutation {name} was accepted")
                self.assertTrue(has_error(errors, expected), f"{name}: expected {expected}, got {errors}")

    def test_review_class_matrix_and_structured_not_applicable_contract(self) -> None:
        for review_class in ("comparison", "safety"):
            with self.subTest(review_class=review_class):
                doc = clone(self.good)
                doc["review_class"] = review_class
                self.bind_script_review(doc)
                self.assertEqual(gt.validate_dual_review(doc, self.root), [])
                missing_script = clone(doc)
                missing_script["script_review"]["status"] = "not_applicable"
                self.assertTrue(has_error(gt.validate_dual_review(missing_script, self.root), "E_REVIEW_TOOL_EXIT"))
                missing_llm = clone(doc)
                missing_llm["llm_review"]["status"] = "not_applicable"
                self.assertTrue(has_error(gt.validate_dual_review(missing_llm, self.root), "E_REVIEW_LLM_RESULT"))

        self.bind_script_review(self.good)

        na_path = self.root / "not-applicable.json"
        na_path.write_text(
            json.dumps(
                {
                    "schema_version": "goal-teams-v2.3",
                    "decision": "not_applicable",
                    "artifact_sha256": self.good["artifact"]["artifact_sha256"],
                    "artifact_version": "V2.3",
                    "reviewer_run_id": "RUN-REVIEWER",
                    "reason": "review class does not require this review channel",
                }
            ),
            encoding="utf-8",
        )

        def na_review(reviewer_run_id: str) -> dict:
            return {
                "reviewer_run_id": reviewer_run_id,
                "status": "not_applicable",
                "reason": "review class does not require this review channel",
                "reviewer_acceptance": "accepted",
                "evidence_path": "not-applicable.json",
                "evidence_sha256": sha256_path(na_path),
                "evidence_size": na_path.stat().st_size,
                "artifact_sha256": self.good["artifact"]["artifact_sha256"],
                "artifact_version": "V2.3",
            }

        semantic = clone(self.good)
        semantic["review_class"] = "semantic"
        semantic["script_review"] = na_review("RUN-NA-SCRIPT")
        self.assertEqual(gt.validate_dual_review(semantic, self.root), [])

        structural = clone(self.good)
        structural["review_class"] = "structural"
        structural["llm_review"] = na_review("RUN-REVIEWER")
        self.bind_script_review(structural)
        self.assertEqual(gt.validate_dual_review(structural, self.root), [])

        missing_reason = clone(structural)
        missing_reason["llm_review"].pop("reason")
        self.assertTrue(has_error(gt.validate_dual_review(missing_reason, self.root), "E_REVIEW_NA"))
        self_approved = clone(semantic)
        self_approved["script_review"]["reviewer_run_id"] = self_approved["author_run_id"]
        self.assertTrue(has_error(gt.validate_dual_review(self_approved, self.root), "E_REVIEW_IDENTITY"))
        missing_binding = clone(structural)
        missing_binding["llm_review"]["evidence_sha256"] = "0" * 64
        self.assertTrue(has_error(gt.validate_dual_review(missing_binding, self.root), "E_REVIEW_EVIDENCE_HASH"))

    def test_derived_review_policy_uses_channel_sets_not_a_linear_rank(self) -> None:
        allowed = {
            "semantic": {"semantic", "comparison", "safety"},
            "structural": {"structural", "comparison", "safety"},
            "comparison": {"comparison", "safety"},
            "safety": {"safety"},
        }
        classes = {"semantic", "structural", "comparison", "safety"}
        for minimum, accepted in allowed.items():
            harness = {
                "harness_contract": {
                    "task_type": "backend",
                    "required_review_class": minimum,
                }
            }
            for actual in classes:
                with self.subTest(minimum=minimum, actual=actual):
                    errors = gt.validate_review_class_policy(
                        {"review_class": actual}, harness
                    )
                    if actual in accepted:
                        self.assertEqual(errors, [])
                    else:
                        self.assertIn("E_REVIEW_CLASS_DOWNGRADE", errors)

        outer_spoof = {
            "required_review_class": "semantic",
            "task_type": "backend",
            "harness_contract": {
                "required_review_class": "comparison",
                "task_type": "replica",
            },
        }
        self.assertIn(
            "E_REVIEW_CLASS_DOWNGRADE",
            gt.validate_review_class_policy(
                {"review_class": "semantic"}, outer_spoof
            ),
        )
        for missing in ("task_type", "required_review_class"):
            with self.subTest(missing=missing):
                contract = {
                    "task_type": "backend",
                    "required_review_class": "semantic",
                }
                contract.pop(missing)
                self.assertIn(
                    "E_REVIEW_CLASS_POLICY",
                    gt.validate_review_class_policy(
                        {"review_class": "semantic"},
                        {"harness_contract": contract},
                    ),
                )


class JsonEnvelopeTests(unittest.TestCase):
    def test_malformed_json_always_returns_one_error_envelope(self) -> None:
        commands = [
            ("validate-evidence", ["--root", "."]),
            ("validate-traceability", []),
            ("validate-dual-review", ["--root", "."]),
            ("validate-behavior", []),
            ("route", []),
            ("capability", []),
        ]
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text('{"unterminated":', encoding="utf-8")
            for command, trailing in commands:
                with self.subTest(command=command):
                    proc = run_cli(command, str(bad), *trailing)
                    self.assertNotEqual(proc.returncode, 0)
                    envelope = parse_envelope(proc)
                    self.assertFalse(envelope["ok"])
                    self.assertEqual(envelope["error_code"], "E_JSON_PARSE")
                    self.assertEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
