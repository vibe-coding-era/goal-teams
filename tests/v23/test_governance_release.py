"""V2.3 identity, Completion Audit and release-authorization gates."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT, gt, parse_envelope, run_cli, sha256_path


CANONICAL = ROOT / "examples/canonical-v23"
VERSION = CANONICAL / "versions/V2.3"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _normal_completion_fixture(destination: Path) -> Path:
    """Convert the portable canonical into a normal source-bound completion fixture."""
    root = destination / "normal-completion"
    shutil.copytree(CANONICAL, root)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "completion-fixture@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Completion Fixture"], cwd=root, check=True
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "normal completion source baseline"], cwd=root, check=True)
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    version = root / "versions/V2.3"
    ledger_events = _read_jsonl(version / "ledger/events.jsonl")
    source_paths = ["versions/V2.3/spec/PRD.md"]
    source_revision = gt.source_manifest_sha256(root, source_paths)
    records = _read_jsonl(version / "evidence/evidence.jsonl")
    standalone = {
        "EVD-CAN-001": version / "evidence/evidence.json",
        "EVD-CAN-002": version / "evidence/evidence-recovery.json",
    }
    for record in records:
        for key in ("portable_fixture", "artifact_transport", "mtime_policy"):
            record.pop(key, None)
        record["environment"].update(
            commit=source_commit,
            workspace_revision=source_revision,
            source_paths=source_paths,
        )
        artifact = root / record["artifact_ref"]
        artifact_stat = artifact.stat()
        record.update(
            artifact_sha256=sha256_path(artifact),
            artifact_size=artifact_stat.st_size,
            artifact_mtime_ns=artifact_stat.st_mtime_ns,
        )
        command = record["command"]
        log = root / command["log_path"]
        log_stat = log.stat()
        command.update(
            log_sha256=sha256_path(log),
            log_size=log_stat.st_size,
            log_mtime_ns=log_stat.st_mtime_ns,
        )
        execution = {
            "schema_version": "goal-teams-v2.3",
            "record_type": "command_execution",
            "evidence_id": record["evidence_id"],
            "check_id": record["check_id"],
            "run_id": record["run_id"],
            "attempt_id": record["attempt_id"],
            "producer_run_id": record["producer_run_id"],
            "argv": command["argv"],
            "cwd": command["cwd"],
            "started_at": command["started_at"],
            "ended_at": command["ended_at"],
            "exit_code": command["exit_code"],
            "log_path": command["log_path"],
            "log_sha256": command["log_sha256"],
            "log_size": command["log_size"],
        }
        execution_path = root / command["execution_record_path"]
        _write_json(execution_path, execution)
        command.update(
            execution_record_sha256=sha256_path(execution_path),
            execution_record_size=execution_path.stat().st_size,
        )
        binding_digest = gt.evidence_replay_binding_digest(record)
        integrity = record["integrity_replay"]
        integrity["argv"] = gt.artifact_verifier_argv(
            record["artifact_ref"], record["artifact_sha256"], binding_digest
        )
        proc = subprocess.run(
            integrity["argv"], cwd=root, capture_output=True, check=False
        )
        if proc.returncode != 0 or proc.stderr:
            raise AssertionError(
                f"normal fixture integrity replay failed: {proc.returncode} {proc.stderr!r}"
            )
        integrity_log = root / integrity["log_path"]
        integrity_log.write_bytes(proc.stdout)
        integrity_stat = integrity_log.stat()
        integrity.update(
            exit_code=proc.returncode,
            log_sha256=sha256_path(integrity_log),
            log_size=integrity_stat.st_size,
            log_mtime_ns=integrity_stat.st_mtime_ns,
        )
        _write_json(standalone[record["evidence_id"]], record)
    _write_jsonl(version / "evidence/evidence.jsonl", records)

    registry, registry_errors = gt.build_evidence_registry(
        records,
        root,
        ledger_events=ledger_events,
        source_root=root,
    )
    if registry_errors:
        raise AssertionError(f"normal completion Evidence invalid: {registry_errors}")
    valid_ids = {
        evidence_id
        for evidence_id, entry in registry.items()
        if entry.get("valid_for_acceptance") is True
    }
    state = gt.reduce_events(
        ledger_events,
        valid_evidence_ids=valid_ids,
        evidence_registry=registry,
    )
    if state.get("conflicts"):
        raise AssertionError(f"normal completion ledger invalid: {state['conflicts']}")
    gt.write_checkpoint(version / "ledger/checkpoint.json", state)
    (version / "TaskList.md").write_text(gt.render_tasklist(state), encoding="utf-8")
    trace_path = version / "harness/traceability.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["evidence"] = records
    trace["tasks"] = [state["tasks"][key] for key in sorted(state["tasks"])]
    _write_json(trace_path, trace)

    # The checked-in canonical lives two directories below the repository, so
    # its comparison argv can use ../../scripts.  A transported completion
    # fixture has a different parent layout and must bind the invocation to the
    # runtime's actual trusted comparison tool instead of retaining that
    # location-dependent argv.
    review_path = version / "reviews/dual-review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    script_report_path = version / "reviews/script-review.json"
    script_report = json.loads(script_report_path.read_text(encoding="utf-8"))
    script_report["domain_execution"]["argv"][1] = os.path.relpath(
        ROOT / "scripts/review/compare-artifacts.py", root.resolve()
    )
    binding_digest = gt.review_replay_binding_digest(review, script_report)
    script_report["binding_digest"] = binding_digest
    integrity = script_report["integrity_replay"]
    integrity["argv"] = gt.artifact_verifier_argv(
        script_report["artifact_ref"],
        script_report["artifact_sha256"],
        binding_digest,
    )
    proc = subprocess.run(integrity["argv"], cwd=root, capture_output=True, check=False)
    if proc.returncode != 0 or proc.stderr:
        raise AssertionError(
            f"normal fixture review replay failed: {proc.returncode} {proc.stderr!r}"
        )
    integrity_log = root / integrity["log_path"]
    integrity_log.write_bytes(proc.stdout)
    integrity.update(
        exit_code=proc.returncode,
        log_sha256=sha256_path(integrity_log),
        log_size=integrity_log.stat().st_size,
    )
    _write_json(script_report_path, script_report)
    review["script_review"].update(
        evidence_sha256=sha256_path(script_report_path),
        evidence_size=script_report_path.stat().st_size,
    )
    _write_json(review_path, review)
    return root


class IdentityRegistryTests(unittest.TestCase):
    def registry(self) -> dict:
        return {
            "schema_version": "goal-teams-v2.3",
            "identities": [
                {
                    "agent_type": "goal_backend",
                    "agent_run_id": "RUN-OWNER-1",
                    "member_id": "实现-Canonical",
                    "display_name": "实现-Canonical",
                    "transport_handle": "backend_1",
                },
                {
                    "agent_type": "goal_reviewer",
                    "agent_run_id": "RUN-VALIDATOR-1",
                    "member_id": "评审-Canonical",
                    "display_name": "评审-Canonical",
                    "transport_handle": "reviewer_1",
                },
            ],
        }

    def validate(self, payload: dict) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "identities.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            proc = run_cli("validate-identity-registry", str(path))
        return proc.returncode, parse_envelope(proc)

    def test_identity_registry_accepts_localized_display_and_distinct_transport(self) -> None:
        rc, envelope = self.validate(self.registry())
        self.assertEqual(rc, 0, envelope)
        self.assertTrue(envelope["ok"])

    def test_identity_registry_rejects_duplicate_run_transport_and_collapsed_semantics(self) -> None:
        cases = {
            "duplicate_run": (
                lambda doc: doc["identities"][1].update(agent_run_id=doc["identities"][0]["agent_run_id"]),
                "E_IDENTITY_RUN_DUPLICATE",
            ),
            "duplicate_transport": (
                lambda doc: doc["identities"][1].update(transport_handle=doc["identities"][0]["transport_handle"]),
                "E_IDENTITY_TRANSPORT_COLLISION",
            ),
            "localized_transport": (
                lambda doc: doc["identities"][0].update(transport_handle=doc["identities"][0]["display_name"]),
                "E_IDENTITY_BINDING",
            ),
            "run_equals_member": (
                lambda doc: doc["identities"][0].update(agent_run_id=doc["identities"][0]["member_id"]),
                "E_IDENTITY_BINDING",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(case=name):
                payload = json.loads(json.dumps(self.registry(), ensure_ascii=False))
                mutate(payload)
                rc, envelope = self.validate(payload)
                self.assertNotEqual(rc, 0)
                self.assertFalse(envelope["ok"])
                self.assertIn(expected, envelope.get("errors", []))


class CompletionAuditCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._fixture_tempdir = tempfile.TemporaryDirectory()
        cls.normal_root = _normal_completion_fixture(Path(cls._fixture_tempdir.name))
        cls.normal_version = cls.normal_root / "versions/V2.3"

    @classmethod
    def tearDownClass(cls) -> None:
        cls._fixture_tempdir.cleanup()

    def command(
        self,
        audit_path: Path,
        *,
        identity_registry: Path | None = None,
        harness: Path | None = None,
        review: Path | None = None,
        ledger: Path | None = None,
        tasklist: Path | None = None,
    ) -> tuple[int, dict]:
        version = self.normal_version
        if audit_path.resolve() == (VERSION / "audit/completion-audit.json").resolve():
            audit_path = version / "audit/completion-audit.json"
        proc = run_cli(
            "completion-audit",
            str(audit_path),
            str(version / "ledger/checkpoint.json"),
            "--evidence-jsonl",
            str(version / "evidence/evidence.jsonl"),
            "--evidence-root",
            str(self.normal_root),
            "--traceability",
            str(version / "harness/traceability.json"),
            "--review",
            str(review or version / "reviews/dual-review.json"),
            "--identity-registry",
            str(identity_registry or version / "identity/registry.json"),
            "--harness",
            str(harness or version / "harness/harness.json"),
            "--ledger",
            str(ledger or version / "ledger/events.jsonl"),
            "--tasklist",
            str(tasklist or version / "TaskList.md"),
        )
        return proc.returncode, parse_envelope(proc)

    def test_completion_audit_recomputes_all_inputs_from_files(self) -> None:
        rc, envelope = self.command(VERSION / "audit/completion-audit.json")
        self.assertEqual(rc, 0, envelope)
        self.assertTrue(envelope["ok"])

    def test_portable_canonical_evidence_is_rejected_by_general_completion_cli(self) -> None:
        proc = run_cli(
            "completion-audit",
            str(VERSION / "audit/completion-audit.json"),
            str(VERSION / "ledger/checkpoint.json"),
            "--evidence-jsonl",
            str(VERSION / "evidence/evidence.jsonl"),
            "--evidence-root",
            str(CANONICAL),
            "--traceability",
            str(VERSION / "harness/traceability.json"),
            "--review",
            str(VERSION / "reviews/dual-review.json"),
            "--identity-registry",
            str(VERSION / "identity/registry.json"),
            "--harness",
            str(VERSION / "harness/harness.json"),
            "--ledger",
            str(VERSION / "ledger/events.jsonl"),
            "--tasklist",
            str(VERSION / "TaskList.md"),
        )
        envelope = parse_envelope(proc)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(
            any(
                str(error).startswith("E_PORTABLE_FIXTURE_SCOPE")
                for error in envelope.get("errors", [])
            ),
            envelope,
        )

    def test_self_auditor_is_rejected_even_when_audit_claims_passed(self) -> None:
        audit = json.loads((VERSION / "audit/completion-audit.json").read_text(encoding="utf-8"))
        checkpoint = json.loads((VERSION / "ledger/checkpoint.json").read_text(encoding="utf-8"))
        owner_run_id = next(iter(checkpoint["tasks"].values()))["owner_run_id"]
        audit["auditor_run_id"] = owner_run_id
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "self-audit.json"
            path.write_text(json.dumps(audit), encoding="utf-8")
            rc, envelope = self.command(path)
        self.assertNotEqual(rc, 0)
        self.assertIn("E_AUDIT_IDENTITY", envelope.get("errors", []))

    def test_required_task_cannot_self_reference_a_custom_named_completion_audit(self) -> None:
        audit = json.loads(
            (VERSION / "audit/completion-audit.json").read_text(encoding="utf-8")
        )
        checkpoint = json.loads(
            (VERSION / "ledger/checkpoint.json").read_text(encoding="utf-8")
        )
        tasks = json.loads(json.dumps(checkpoint["tasks"], ensure_ascii=False))
        required = next(
            task
            for task in tasks.values()
            if task.get("required_for_done") is True
        )
        custom_audit_ref = "versions/V2.3/audit/custom-final-review.json"
        required["artifact_refs"].append(custom_audit_ref)

        errors = gt.validate_completion_audit(
            audit,
            tasks,
            traceability_valid=True,
            dual_review_valid=True,
            ledger_revision=checkpoint["ledger_revision"],
            expected_audit_ref=custom_audit_ref,
        )
        self.assertIn("E_AUDIT_SELF_REFERENCE", errors)

    def test_removed_self_report_flags_cannot_force_a_pass(self) -> None:
        proc = run_cli(
            "completion-audit",
            str(VERSION / "audit/completion-audit.json"),
            str(VERSION / "ledger/checkpoint.json"),
            "--valid-evidence-ids",
            "FAKE",
            "--traceability-valid",
            "--dual-review-valid",
        )
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertNotIn('"ok": true', combined.lower())

    def test_identity_registry_and_harness_are_recomputed_not_self_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            identity = json.loads((VERSION / "identity/registry.json").read_text(encoding="utf-8"))
            identity["identities"] = [
                item for item in identity["identities"] if item["agent_run_id"] != "RUN-CAN-OWNER"
            ]
            identity_path = root / "identity.json"
            identity_path.write_text(json.dumps(identity), encoding="utf-8")
            rc, envelope = self.command(
                VERSION / "audit/completion-audit.json", identity_registry=identity_path
            )
            self.assertNotEqual(rc, 0)
            self.assertTrue(
                any(str(error).startswith("E_IDENTITY_BINDING") for error in envelope.get("errors", [])),
                envelope,
            )

            harness = json.loads((VERSION / "harness/harness.json").read_text(encoding="utf-8"))
            harness["runs"] = []
            harness_path = root / "harness.json"
            harness_path.write_text(json.dumps(harness), encoding="utf-8")
            rc, envelope = self.command(
                VERSION / "audit/completion-audit.json", harness=harness_path
            )
            self.assertNotEqual(rc, 0)
            self.assertIn("E_AUDIT_HARNESS_BINDING", envelope.get("errors", []))

    def test_completion_closure_fields_are_recomputed_from_bound_files(self) -> None:
        base = json.loads((VERSION / "audit/completion-audit.json").read_text(encoding="utf-8"))
        cases = {
            "required_task_ids": (
                lambda doc: doc.update(required_task_ids=[]),
                "E_AUDIT_CLOSURE:required_task_ids",
            ),
            "accepted_required_task_ids": (
                lambda doc: doc.update(accepted_required_task_ids=[]),
                "E_AUDIT_CLOSURE:accepted_required_task_ids",
            ),
            "open_acceptance_blocking_task_ids": (
                lambda doc: doc.update(open_acceptance_blocking_task_ids=["FAKE"]),
                "E_AUDIT_CLOSURE:open_acceptance_blocking_task_ids",
            ),
            "documented_nonblocking_tasks": (
                lambda doc: doc.update(documented_nonblocking_tasks=[]),
                "E_AUDIT_CLOSURE:documented_nonblocking_tasks",
            ),
            "required_acceptance_criteria": (
                lambda doc: doc.update(required_acceptance_criteria=[]),
                "E_AUDIT_CLOSURE:required_acceptance_criteria",
            ),
            "covered_acceptance_criteria": (
                lambda doc: doc.update(covered_acceptance_criteria=[]),
                "E_AUDIT_CLOSURE:covered_acceptance_criteria",
            ),
            "review_ref": (
                lambda doc: doc.update(review_ref="reviews/fake.json"),
                "E_AUDIT_REVIEW_REF",
            ),
            "stop_reason": (
                lambda doc: doc.update(stop_reason="not-a-stop-reason"),
                "E_AUDIT_STOP_REASON",
            ),
            "conclusion": (
                lambda doc: doc.update(conclusion="claimed success"),
                "E_AUDIT_CONCLUSION",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(field=name), tempfile.TemporaryDirectory() as td:
                payload = json.loads(json.dumps(base, ensure_ascii=False))
                mutate(payload)
                path = Path(td) / "audit.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                rc, envelope = self.command(path)
                self.assertNotEqual(rc, 0)
                self.assertIn(expected, envelope.get("errors", []), envelope)

    def test_completion_audit_rejects_tasklist_projection_drift(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="projection-drift-",
            suffix=".md",
            dir=self.normal_version / "audit",
            delete=False,
        ) as stream:
            stream.write((self.normal_version / "TaskList.md").read_text(encoding="utf-8"))
            stream.write("manual drift\n")
            path = Path(stream.name)
        try:
            rc, envelope = self.command(
                VERSION / "audit/completion-audit.json", tasklist=path
            )
        finally:
            path.unlink(missing_ok=True)
        self.assertNotEqual(rc, 0)
        self.assertIn("E_AUDIT_PROJECTION", envelope.get("errors", []), envelope)

    def test_completion_derives_minimum_review_class_from_harness_risk(self) -> None:
        version = self.normal_version
        review_path = version / "reviews/dual-review.json"
        original_review = review_path.read_bytes()
        na_path = version / "reviews/script-not-applicable.json"
        try:
            review = json.loads(original_review)
            artifact = review["artifact"]
            na_payload = {
                "schema_version": "goal-teams-v2.3",
                "decision": "not_applicable",
                "artifact_sha256": artifact["artifact_sha256"],
                "artifact_version": artifact["artifact_version"],
                "reviewer_run_id": review["script_review"]["reviewer_run_id"],
                "reason": "semantic-only review channel",
            }
            _write_json(na_path, na_payload)
            review["review_class"] = "semantic"
            review["script_review"] = {
                "reviewer_run_id": review["script_review"]["reviewer_run_id"],
                "status": "not_applicable",
                "reason": "semantic-only review channel",
                "reviewer_acceptance": "accepted",
                "evidence_path": "versions/V2.3/reviews/script-not-applicable.json",
                "evidence_sha256": sha256_path(na_path),
                "evidence_size": na_path.stat().st_size,
                "artifact_sha256": artifact["artifact_sha256"],
                "artifact_version": artifact["artifact_version"],
            }
            _write_json(review_path, review)
            self.assertEqual(gt.validate_dual_review(review, self.normal_root), [])

            base_harness = json.loads(
                (version / "harness/harness.json").read_text(encoding="utf-8")
            )
            cases = {
                "replica": {"task_type": "replica"},
                "security": {"task_type": "backend", "security_sensitive": True},
                "external_write": {"task_type": "backend", "external_write": True},
            }
            for name, features in cases.items():
                with self.subTest(case=name), tempfile.TemporaryDirectory() as td:
                    harness = json.loads(json.dumps(base_harness, ensure_ascii=False))
                    contract = harness["harness_contract"]
                    for key in ("task_type", "security_sensitive", "external_write"):
                        contract.pop(key, None)
                    contract["required_review_class"] = "semantic"
                    contract.update(features)
                    harness["task_type"] = "semantic"
                    harness["required_review_class"] = "semantic"
                    harness_path = Path(td) / "harness.json"
                    _write_json(harness_path, harness)
                    rc, envelope = self.command(
                        version / "audit/completion-audit.json",
                        harness=harness_path,
                    )
                    self.assertNotEqual(rc, 0, envelope)
                    self.assertIn(
                        "E_REVIEW_CLASS_DOWNGRADE",
                        envelope.get("errors", []),
                        envelope,
                    )
        finally:
            review_path.write_bytes(original_review)
            na_path.unlink(missing_ok=True)

    def test_standalone_and_completion_preserve_the_same_review_failure_codes(self) -> None:
        version = self.normal_version
        review_path = version / "reviews/dual-review.json"
        report_path = version / "reviews/script-review.json"
        review_original = review_path.read_bytes()
        report_original = report_path.read_bytes()
        try:
            report = json.loads(report_original)
            report["domain_execution"]["exit_code"] = 1
            _write_json(report_path, report)
            review = json.loads(review_original)
            review["script_review"].update(
                evidence_sha256=sha256_path(report_path),
                evidence_size=report_path.stat().st_size,
            )
            _write_json(review_path, review)
            standalone = gt.validate_dual_review(review, self.normal_root)
            self.assertIn("E_REVIEW_TOOL_PROVENANCE", standalone, standalone)
            rc, envelope = self.command(version / "audit/completion-audit.json")
            self.assertNotEqual(rc, 0, envelope)
            for code in standalone:
                self.assertIn(code, envelope.get("errors", []), envelope)
        finally:
            report_path.write_bytes(report_original)
            review_path.write_bytes(review_original)


class ReleaseAuthorizationTests(unittest.TestCase):
    def real_blind_summary(self) -> Path:
        value = os.environ.get("GOAL_TEAMS_REAL_BLIND_SUMMARY")
        if not value:
            self.skipTest("set GOAL_TEAMS_REAL_BLIND_SUMMARY to a fresh nine-scenario Codex run")
        path = Path(value).resolve()
        if not path.is_file():
            self.fail(f"GOAL_TEAMS_REAL_BLIND_SUMMARY does not exist: {path}")
        return path

    def test_rc_without_blind_summary_fails_closed(self) -> None:
        proc = run_cli("release-gate", str(CANONICAL), "--mode", "rc")
        envelope = parse_envelope(proc)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(envelope["error_code"], "E_BLIND_AGENT_EVIDENCE_REQUIRED")

    def test_ga_without_blind_summary_and_license_reports_both_closed_gates(self) -> None:
        proc = run_cli("release-gate", str(CANONICAL), "--mode", "ga")
        envelope = parse_envelope(proc)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("E_BLIND_AGENT_EVIDENCE_REQUIRED", envelope.get("errors", []))
        self.assertIn("E_LICENSE_DECISION_REQUIRED", envelope.get("errors", []))

    def test_pipeline_fixture_summary_can_never_satisfy_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = root / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-blind-eval-v2.3",
                        "evaluation_id": "FIXTURE",
                        "evaluation_class": "pipeline_fixture",
                        "provider_provenance": {
                            "adapter_type": "fixture",
                            "provider": "local-pipeline-fixture",
                        },
                    }
                ),
                encoding="utf-8",
            )
            proc = run_cli(
                "release-gate",
                str(CANONICAL),
                "--mode",
                "rc",
                "--blind-summary",
                str(summary),
            )
        envelope = parse_envelope(proc)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(envelope["error_code"], "E_BLIND_AGENT_FIXTURE")

    def test_fresh_real_nine_scenario_summary_is_required_for_rc_pass(self) -> None:
        summary = self.real_blind_summary()
        proc = run_cli(
            "release-gate",
            str(CANONICAL),
            "--mode",
            "rc",
            "--blind-summary",
            str(summary),
        )
        envelope = parse_envelope(proc)
        self.assertEqual(proc.returncode, 0, envelope)
        self.assertTrue(envelope["ok"])

    def test_rc_composes_the_real_deterministic_suite_and_fails_closed(self) -> None:
        fake_summary = Path("/tmp/goal-teams-valid-blind-summary.json")
        failed = mock.Mock(returncode=7, stdout="", stderr="distribution gate failed")
        with (
            mock.patch.object(gt, "validate_canonical", return_value=[]),
            mock.patch.object(gt, "validate_blind_release_summary", return_value=[]),
            mock.patch.object(gt.subprocess, "run", return_value=failed) as run,
            mock.patch.dict(os.environ, {"GOAL_TEAMS_RELEASE_COMPOSITION": "0"}),
        ):
            errors = gt.release_gate(CANONICAL, "rc", fake_summary)
        self.assertIn("E_RELEASE_DETERMINISTIC_SUITE", errors)
        run.assert_called_once()
        args, kwargs = run.call_args
        command = args[0]
        self.assertTrue(
            any(str(item).endswith("scripts/checks/check.sh") for item in command),
            command,
        )
        self.assertNotIn("GOAL_TEAMS_RELEASE_COMPOSITION", kwargs["env"])
        self.assertNotIn("GOAL_TEAMS_REAL_BLIND_SUMMARY", kwargs["env"])

    def test_external_release_composition_env_cannot_bypass_the_suite(self) -> None:
        fake_summary = Path("/tmp/goal-teams-valid-blind-summary.json")
        failed = mock.Mock(returncode=9, stdout="", stderr="still failed")
        with (
            mock.patch.object(gt, "validate_canonical", return_value=[]),
            mock.patch.object(gt, "validate_blind_release_summary", return_value=[]),
            mock.patch.object(gt.subprocess, "run", return_value=failed) as run,
            mock.patch.dict(os.environ, {"GOAL_TEAMS_RELEASE_COMPOSITION": "1"}),
        ):
            errors = gt.release_gate(CANONICAL, "rc", fake_summary)
        self.assertIn("E_RELEASE_DETERMINISTIC_SUITE", errors)
        run.assert_called_once()

    def test_local_owner_fixture_is_only_a_proposal_not_a_ga_attestation(self) -> None:
        decision = {
            "schema_version": "goal-teams-v2.3",
            "decision_id": "DEC-LICENSE-TEST-INTERNAL",
            "owner_run_id": "RUN-REPOSITORY-OWNER-FIXTURE",
            "distribution_scope": "internal_only",
            "authorized_at": "2026-07-10T00:00:00Z",
            "owner_authorized": True,
            "internal_sharing_approved": True,
            "fixture_only": True,
        }
        identity_doc = json.loads((VERSION / "identity/registry.json").read_text(encoding="utf-8"))
        registry, errors = gt.validate_identity_registry(identity_doc)
        self.assertEqual(errors, [])
        self.assertIn(
            "E_LICENSE_ATTESTATION_UNVERIFIED",
            gt.validate_license_decision(decision, registry),
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "local-license-proposal.json"
            _write_json(path, decision)
            proc = run_cli(
                "release-gate",
                str(CANONICAL),
                "--mode",
                "ga",
                "--license-decision",
                str(path),
            )
        envelope = parse_envelope(proc)
        self.assertNotEqual(proc.returncode, 0, envelope)
        self.assertIn(
            "E_LICENSE_ATTESTATION_UNVERIFIED",
            envelope.get("errors", []),
            envelope,
        )

    def test_invalid_or_unauthorized_decision_is_rejected(self) -> None:
        decision = {
            "schema_version": "goal-teams-v2.3",
            "decision_id": "DEC-INVALID",
            "owner_run_id": "",
            "distribution_scope": "open_source",
            "authorized_at": "2026-07-10T00:00:00Z",
            "owner_authorized": False,
        }
        identity_doc = json.loads((VERSION / "identity/registry.json").read_text(encoding="utf-8"))
        registry, errors = gt.validate_identity_registry(identity_doc)
        self.assertEqual(errors, [])
        decision_errors = gt.validate_license_decision(decision, registry)
        self.assertIn("E_LICENSE_DECISION_INVALID", decision_errors)


class BlindReleaseFreshnessTests(unittest.TestCase):
    def summary(self) -> Path:
        value = os.environ.get("GOAL_TEAMS_REAL_BLIND_SUMMARY")
        if not value:
            self.skipTest("freshness mutations require a real nine-scenario blind summary")
        path = Path(value).resolve()
        if not path.is_file():
            self.fail(f"GOAL_TEAMS_REAL_BLIND_SUMMARY does not exist: {path}")
        return path

    def test_repo_contained_alternate_manifest_cannot_define_the_release_rubric(self) -> None:
        official_path = ROOT / "tests/v23/fixtures/behavior/blind-agent-codex.json"
        manifest = json.loads(official_path.read_text(encoding="utf-8"))
        alternate = ROOT / "tests/v23/fixtures/behavior/.alternate-blind-manifest.json"
        scenario_hashes = {
            item["scenario_id"]: gt.canonical_json_sha256(
                gt._effective_blind_rubric(item["scorer"])
            )
            for item in manifest["scenarios"]
        }
        combined_hash = gt.canonical_json_sha256(
            [
                {"scenario_id": scenario_id, "rubric_sha256": rubric_hash}
                for scenario_id, rubric_hash in sorted(scenario_hashes.items())
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            output_root = Path(td).resolve()
            summary_path = output_root / "summary.json"
            try:
                _write_json(alternate, manifest)
                summary = {
                    "schema_version": "goal-teams-blind-eval-v2.3",
                    "evaluation_id": manifest["evaluation_id"],
                    "invocation_id": "BLIND-ALTERNATE-MANIFEST",
                    "evaluation_class": "blind_agent",
                    "release_gate_passed": True,
                    "output_dir": str(output_root),
                    "required_scenarios": sorted(gt.BLIND_REQUIRED_SCENARIOS),
                    "passed_scenarios": sorted(gt.BLIND_REQUIRED_SCENARIOS),
                    "release_eligible_scenarios": sorted(gt.BLIND_REQUIRED_SCENARIOS),
                    "provider_provenance": {},
                    "source_provenance": {},
                    "source_repository_unchanged": True,
                    "runner_provenance": {},
                    "staged_manifest": {},
                    "manifest_source_path": str(alternate),
                    "manifest_source_sha256": sha256_path(alternate),
                    "rubric_sha256": combined_hash,
                    "records": [],
                }
                _write_json(summary_path, summary)
                errors = gt.validate_blind_release_summary(summary_path)
            finally:
                alternate.unlink(missing_ok=True)
        self.assertIn("E_BLIND_AGENT_RUBRIC", errors, errors)

    def test_source_snapshot_detects_index_only_and_cached_deletion_drift(self) -> None:
        def repository(root: Path) -> tuple[Path, bytes, str]:
            source = root / "source.txt"
            original = b"committed source bytes\n"
            source.write_bytes(original)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "index-drift@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Index Drift Fixture"],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "add", source.name], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "source baseline"], cwd=root, check=True
            )
            digest = gt._repository_source_digest(root)
            self.assertIsInstance(digest, str)
            return source, original, digest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, original, baseline = repository(root)
            subprocess.run(
                ["git", "rm", "--cached", "-q", source.name], cwd=root, check=True
            )
            self.assertEqual(source.read_bytes(), original)
            self.assertNotEqual(gt._repository_source_digest(root), baseline)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, original, baseline = repository(root)
            source.write_bytes(b"staged-only replacement\n")
            subprocess.run(["git", "add", source.name], cwd=root, check=True)
            source.write_bytes(original)
            self.assertEqual(source.read_bytes(), original)
            self.assertNotEqual(gt._repository_source_digest(root), baseline)

    def test_post_run_staged_package_rejects_symlink_and_nonregular_mutations(self) -> None:
        summary = self.summary()
        self.assertEqual(gt.validate_blind_release_summary(summary), [])
        staged = summary.parent / "staged-package"
        with tempfile.TemporaryDirectory() as td:
            external = Path(td) / "external-secret.txt"
            external.write_text("validator must not follow this target\n", encoding="utf-8")
            link = staged / "post-run-symlink"
            link.symlink_to(external)
            try:
                errors = gt.validate_blind_release_summary(summary)
                self.assertTrue(
                    any(str(error).startswith("E_BLIND_AGENT_STAGE") for error in errors),
                    errors,
                )
                self.assertEqual(
                    external.read_text(encoding="utf-8"),
                    "validator must not follow this target\n",
                )
            finally:
                link.unlink(missing_ok=True)
        self.assertEqual(gt.validate_blind_release_summary(summary), [])

        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO creation is unavailable on this platform")
        fifo = staged / "post-run-fifo"
        os.mkfifo(fifo)
        try:
            errors = gt.validate_blind_release_summary(summary)
            self.assertTrue(
                any(str(error).startswith("E_BLIND_AGENT_STAGE") for error in errors),
                errors,
            )
        finally:
            fifo.unlink(missing_ok=True)
        self.assertEqual(gt.validate_blind_release_summary(summary), [])

    def test_persisted_output_is_rescored_and_record_evidence_paths_are_exact(self) -> None:
        summary_path = self.summary()
        self.assertEqual(gt.validate_blind_release_summary(summary_path), [])
        summary_original = summary_path.read_bytes()
        summary = json.loads(summary_original)
        ref = summary["records"][0]
        record_path = summary_path.parent / ref["path"]
        record_original = record_path.read_bytes()
        record = json.loads(record_original)
        output_path = record_path.parent / "output.txt"
        output_original = output_path.read_bytes()

        def persist_record(value: dict) -> None:
            _write_json(record_path, value)
            ref["sha256"] = sha256_path(record_path)
            ref["size"] = record_path.stat().st_size
            _write_json(summary_path, summary)

        try:
            output_path.write_text("{}\n", encoding="utf-8")
            rescored = json.loads(record_original)
            output_evidence = next(
                item for item in rescored["evidence"] if item.get("path") == "output.txt"
            )
            output_evidence["sha256"] = sha256_path(output_path)
            persist_record(rescored)
            errors = gt.validate_blind_release_summary(summary_path)
            self.assertIn("E_BLIND_AGENT_SCORE_REPLAY", errors, errors)

            output_path.write_bytes(output_original)
            wrong_paths = json.loads(record_original)
            wrong_paths["evidence"] = [
                {
                    "path": "stdout.log",
                    "sha256": sha256_path(record_path.parent / "stdout.log"),
                },
                *[
                    item
                    for item in wrong_paths["evidence"]
                    if item.get("path") != "output.txt"
                ],
            ]
            persist_record(wrong_paths)
            errors = gt.validate_blind_release_summary(summary_path)
            self.assertIn("E_BLIND_AGENT_RECORD_EVIDENCE", errors, errors)
        finally:
            output_path.write_bytes(output_original)
            record_path.write_bytes(record_original)
            summary_path.write_bytes(summary_original)
        self.assertEqual(gt.validate_blind_release_summary(summary_path), [])

    def test_nonpackage_project_audit_write_does_not_invalidate_blind_summary(self) -> None:
        summary = self.summary()
        self.assertEqual(gt.validate_blind_release_summary(summary), [])
        project_root = ROOT / "GoalTeamsWork-V2.3"
        project_root.mkdir(exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="blind-freshness-", dir=project_root))
        try:
            (scratch / "audit-note.json").write_text('{"audit":"post-blind"}\n', encoding="utf-8")
            self.assertEqual(gt.validate_blind_release_summary(summary), [])
        finally:
            shutil.rmtree(scratch)
        self.assertEqual(gt.validate_blind_release_summary(summary), [])

    def test_package_runner_and_manifest_mutations_fail_with_stable_codes(self) -> None:
        summary = self.summary()
        mutations = {
            ROOT / "SKILL.md": "E_BLIND_AGENT_STAGE_SOURCE",
            ROOT / "scripts/v23/goalteams_v23.py": "E_BLIND_AGENT_STAGE_SOURCE",
            ROOT / "scripts/benchmark/benchmark-runner.py": "E_BLIND_AGENT_RUNNER",
            ROOT / "tests/v23/fixtures/behavior/blind-agent-codex.json": "E_BLIND_AGENT_RUBRIC",
        }
        for path, expected in mutations.items():
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(gt.validate_blind_release_summary(summary), [])
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"\n")
                    errors = gt.validate_blind_release_summary(summary)
                    self.assertIn(expected, errors, errors)
                finally:
                    path.write_bytes(original)
                self.assertEqual(gt.validate_blind_release_summary(summary), [])

    def test_fake_executable_cannot_impersonate_codex_provider(self) -> None:
        summary = self.summary()
        self.assertEqual(gt.validate_blind_release_summary(summary), [])
        original = summary.read_bytes()
        try:
            payload = json.loads(original)
            fake = Path("/bin/sh").resolve()
            payload["provider_provenance"].update(
                {
                    "executable": str(fake),
                    "executable_sha256": gt.sha256(fake),
                    "provider_version": "codex-cli fake",
                    "version_argv": [str(fake), "--version"],
                }
            )
            summary.write_text(json.dumps(payload), encoding="utf-8")
            errors = gt.validate_blind_release_summary(summary)
            self.assertIn("E_BLIND_AGENT_PROVIDER", errors, errors)
        finally:
            summary.write_bytes(original)
        self.assertEqual(gt.validate_blind_release_summary(summary), [])


if __name__ == "__main__":
    unittest.main()
