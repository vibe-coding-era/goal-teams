"""Canonical V2.3 end-to-end replay and mutation tests."""

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


CANONICAL = ROOT / "examples" / "canonical-v23"
VERSION = Path("versions/V2.3")


def jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AssertionError(f"{path}:{number} must be a JSON object")
        rows.append(value)
    return rows


def canonical_evidence_registry(root: Path = CANONICAL):
    ledger = root / VERSION / "ledger/events.jsonl"
    events = jsonl(ledger)
    records = jsonl(root / VERSION / "evidence/evidence.jsonl")
    registry, errors = gt.build_evidence_registry(
        records,
        root,
        ledger_events=events,
        allow_portable_fixture=True,
    )
    if errors:
        raise AssertionError(f"canonical Evidence registry invalid: {errors}")
    return registry


class CanonicalChainTests(unittest.TestCase):
    def test_canonical_chain_passes_every_real_validator(self) -> None:
        errors = gt.validate_canonical(CANONICAL)
        self.assertEqual(errors, [])
        proc = run_cli("validate-canonical", str(CANONICAL))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(parse_envelope(proc)["ok"])

    def test_portable_evidence_is_scoped_only_to_canonical_validation(self) -> None:
        events = jsonl(CANONICAL / VERSION / "ledger/events.jsonl")
        records = jsonl(CANONICAL / VERSION / "evidence/evidence.jsonl")
        self.assertIn(
            "E_PORTABLE_FIXTURE_SCOPE",
            gt.validate_evidence(records[0], CANONICAL, ledger_events=events),
        )
        _, registry_errors = gt.build_evidence_registry(
            records, CANONICAL, ledger_events=events
        )
        self.assertTrue(
            any("E_PORTABLE_FIXTURE_SCOPE" in error for error in registry_errors),
            registry_errors,
        )
        trace = json.loads(
            (CANONICAL / VERSION / "harness/traceability.json").read_text(encoding="utf-8")
        )
        trace_result = gt.validate_traceability(
            trace, CANONICAL, ledger_events=events
        )
        self.assertFalse(trace_result["ok"])
        self.assertTrue(
            any("E_PORTABLE_FIXTURE_SCOPE" in error for error in trace_result["errors"]),
            trace_result,
        )

    def test_git_tracked_portable_copy_survives_transport_mtime_changes(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "examples") as td:
            copied = Path(td)
            shutil.copytree(CANONICAL, copied, dirs_exist_ok=True)
            subprocess.run(["git", "init", "-q"], cwd=copied, check=True)
            subprocess.run(
                ["git", "config", "user.email", "portable@example.invalid"],
                cwd=copied,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Portable Fixture"],
                cwd=copied,
                check=True,
            )
            subprocess.run(["git", "add", "-A"], cwd=copied, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "portable fixture"], cwd=copied, check=True
            )
            for record in jsonl(copied / VERSION / "evidence/evidence.jsonl"):
                for relative in (
                    record["artifact_ref"],
                    record["command"]["log_path"],
                    record["integrity_replay"]["log_path"],
                ):
                    path = copied / relative
                    stat = path.stat()
                    os.utime(
                        path,
                        ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000),
                    )
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=copied,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(status.stdout, "")
            self.assertEqual(gt.validate_canonical(copied), [])

    def test_installer_validated_stage_survives_gitless_transport_mtime_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "canonical-v23"
            shutil.copytree(CANONICAL, copied)
            for record in jsonl(copied / VERSION / "evidence/evidence.jsonl"):
                for relative in (
                    record["artifact_ref"],
                    record["command"]["log_path"],
                    record["integrity_replay"]["log_path"],
                ):
                    path = copied / relative
                    stat = path.stat()
                    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
            self.assertFalse((copied / ".git").exists())
            with mock.patch.dict(os.environ, {"GOAL_TEAMS_INSTALL_VALIDATION": "1"}):
                records = jsonl(copied / VERSION / "evidence/evidence.jsonl")
                events = jsonl(copied / VERSION / "ledger/events.jsonl")
                _, errors = gt.build_evidence_registry(
                    records,
                    copied,
                    ledger_events=events,
                    allow_portable_fixture=True,
                )
                self.assertEqual(errors, [])

    def test_ledger_replay_is_byte_equivalent_to_checked_in_tasklist(self) -> None:
        events = jsonl(CANONICAL / VERSION / "ledger/events.jsonl")
        registry = canonical_evidence_registry()
        valid_ids = {
            evidence_id
            for evidence_id, entry in registry.items()
            if entry.get("valid_for_acceptance") is True
        }
        state = gt.reduce_events(events, valid_evidence_ids=valid_ids, evidence_registry=registry)
        self.assertEqual(state.get("conflicts"), [])
        rendered = gt.render_tasklist(state).encode("utf-8")
        checked_in = (CANONICAL / VERSION / "TaskList.md").read_bytes()
        self.assertEqual(rendered, checked_in)

    def test_canonical_ledger_exercises_success_blocked_failure_and_recovery(self) -> None:
        events = jsonl(CANONICAL / VERSION / "ledger/events.jsonl")
        states_by_task: dict[str, list[str]] = {}
        for event in events:
            state = event.get("payload", {}).get("task_state")
            if state:
                states_by_task.setdefault(event["task_id"], []).append(state)
        self.assertIn("accepted", states_by_task.get("TASK-CAN-SUCCESS", []))
        self.assertIn("blocked", states_by_task.get("TASK-CAN-BLOCKED", []))
        failure_path = states_by_task.get("TASK-CAN-FAILURE-RECOVERY", [])
        self.assertGreaterEqual(failure_path.count("review"), 2)
        self.assertIn("running", failure_path)
        recovery_path = states_by_task.get("TASK-CAN-BLOCKED-RECOVERY", [])
        self.assertIn("blocked", recovery_path)
        self.assertEqual(recovery_path[-1], "accepted")
        runs = json.loads((CANONICAL / VERSION / "harness/harness.json").read_text(encoding="utf-8"))["runs"]
        self.assertTrue(any(run.get("status") == "failed" for run in runs))
        self.assertTrue(any(run.get("recovery_of_run_id") for run in runs))

    def test_every_markdown_file_has_parseable_okf_type(self) -> None:
        for path in sorted(CANONICAL.rglob("*.md")):
            with self.subTest(path=path.relative_to(CANONICAL)):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                head = text.split("---", 2)[1]
                self.assertRegex(head, r"(?m)^type:\s*\S")

    def test_harness_checks_runs_and_full_traceability_are_strictly_valid(self) -> None:
        harness = json.loads((CANONICAL / VERSION / "harness/harness.json").read_text(encoding="utf-8"))
        contract = harness["harness_contract"]
        self.assertEqual(contract["task_type"], "replica")
        self.assertEqual(contract["required_review_class"], "comparison")
        self.assertNotIn("task_type", harness)
        review = json.loads(
            (CANONICAL / VERSION / "reviews/dual-review.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(review["review_class"], "comparison")
        self.assertEqual(gt.validate_review_class_policy(review, harness), [])
        registry = canonical_evidence_registry()
        valid_ids = {
            evidence_id
            for evidence_id, entry in registry.items()
            if entry.get("valid_for_acceptance") is True
        }
        for check in harness["harness_contract"]["checks"]:
            with self.subTest(check=check.get("check_id")):
                self.assertEqual(gt.validate_check(check, valid_ids, registry), [])
        for run in harness["runs"]:
            with self.subTest(run=run.get("run_id")):
                self.assertEqual(gt.validate_run(run, valid_ids, registry), [])
        trace = json.loads((CANONICAL / VERSION / "harness/traceability.json").read_text(encoding="utf-8"))
        result = gt.validate_traceability(
            trace,
            CANONICAL,
            valid_ids,
            registry,
            ledger_events=jsonl(CANONICAL / VERSION / "ledger/events.jsonl"),
            allow_portable_fixture=True,
        )
        self.assertTrue(result["ok"], result)

    def test_recorded_evidence_commands_reexecute_to_exact_bound_logs(self) -> None:
        for record in jsonl(CANONICAL / VERSION / "evidence/evidence.jsonl"):
            command = record["command"]
            cwd = CANONICAL / command["cwd"]
            with self.subTest(evidence=record["evidence_id"]):
                proc = subprocess.run(
                    command["argv"], cwd=cwd, text=False, capture_output=True, check=False
                )
                self.assertEqual(proc.returncode, command["exit_code"])
                self.assertEqual(proc.stderr, b"")
                self.assertEqual(proc.stdout, (CANONICAL / command["log_path"]).read_bytes())

    def test_replay_policy_rejects_inline_and_external_python_code(self) -> None:
        evidence = jsonl(CANONICAL / VERSION / "evidence/evidence.jsonl")[0]
        self.assertEqual(gt.validate_evidence_command_replay(evidence, CANONICAL), [])
        inline = json.loads(json.dumps(evidence))
        inline["integrity_replay"]["argv"] = ["python3", "-c", "print('forged')"]
        self.assertIn(
            "E_COMMAND_REPLAY_POLICY",
            gt.validate_evidence_command_replay(inline, CANONICAL),
        )
        external = json.loads(json.dumps(evidence))
        external["integrity_replay"]["argv"] = ["python3", "/tmp/forged.py", "success"]
        self.assertIn(
            "E_COMMAND_REPLAY_POLICY",
            gt.validate_evidence_command_replay(external, CANONICAL),
        )

        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "canonical"
            shutil.copytree(CANONICAL, copied)
            review = json.loads((copied / VERSION / "reviews/dual-review.json").read_text(encoding="utf-8"))
            report_path = copied / VERSION / "reviews/script-review.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["integrity_replay"]["argv"] = ["python3", "-c", "print('forged')"]
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.assertIn(
                "E_REVIEW_TOOL_REPLAY_POLICY",
                gt.validate_review_command_replay(review, copied),
            )

            legacy = json.loads(
                (CANONICAL / VERSION / "reviews/script-review.json").read_text(
                    encoding="utf-8"
                )
            )
            legacy["command"] = legacy.pop("domain_execution")
            legacy.pop("integrity_replay", None)
            report_path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertIn(
                "E_REVIEW_TOOL_REPLAY_POLICY",
                gt.validate_review_command_replay(review, copied),
            )

    def test_replay_command_is_bound_to_artifact_and_claim_identity(self) -> None:
        evidence = jsonl(CANONICAL / VERSION / "evidence/evidence.jsonl")[0]
        recovery = CANONICAL / VERSION / "evidence/recovery.txt"
        forged = json.loads(json.dumps(evidence))
        forged.update(
            {
                "artifact_ref": "versions/V2.3/evidence/recovery.txt",
                "artifact_sha256": sha256_path(recovery),
                "artifact_size": recovery.stat().st_size,
                "artifact_mtime_ns": recovery.stat().st_mtime_ns,
            }
        )
        self.assertIn(
            "E_COMMAND_REPLAY_BINDING",
            gt.validate_evidence_command_replay(forged, CANONICAL),
        )
        claim_mutations = {
            "check_id": "CHECK-FORGED",
            "run_id": "RUN-FORGED",
            "attempt_id": "ATT-FORGED",
        }
        for field, value in claim_mutations.items():
            with self.subTest(evidence_binding=field):
                wrong_claim = json.loads(json.dumps(evidence))
                wrong_claim[field] = value
                self.assertIn(
                    "E_COMMAND_REPLAY_BINDING",
                    gt.validate_evidence_command_replay(wrong_claim, CANONICAL),
                )
        wrong_environment = json.loads(json.dumps(evidence))
        wrong_environment["environment"]["workspace_revision"] = "0" * 64
        self.assertIn(
            "E_COMMAND_REPLAY_BINDING",
            gt.validate_evidence_command_replay(wrong_environment, CANONICAL),
        )

        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "canonical"
            shutil.copytree(CANONICAL, copied)
            review_path = copied / VERSION / "reviews/dual-review.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            copied_recovery = copied / VERSION / "evidence/recovery.txt"
            review["artifact"].update(
                {
                    "artifact_ref": "versions/V2.3/evidence/recovery.txt",
                    "artifact_sha256": sha256_path(copied_recovery),
                }
            )
            report_path = copied / VERSION / "reviews/script-review.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report.update(
                {
                    "artifact_ref": "versions/V2.3/evidence/recovery.txt",
                    "artifact_sha256": sha256_path(copied_recovery),
                }
            )
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.assertIn(
                "E_REVIEW_TOOL_REPLAY_BINDING",
                gt.validate_review_command_replay(review, copied),
            )

        review = json.loads(
            (CANONICAL / VERSION / "reviews/dual-review.json").read_text(encoding="utf-8")
        )
        for field, value in (
            ("author_run_id", "RUN-FORGED-AUTHOR"),
            ("reviewer_run_id", "RUN-FORGED-REVIEWER"),
        ):
            with self.subTest(review_binding=field):
                wrong_review = json.loads(json.dumps(review))
                wrong_review[field] = value
                self.assertIn(
                    "E_REVIEW_TOOL_REPLAY_BINDING",
                    gt.validate_review_command_replay(wrong_review, CANONICAL),
                )
        wrong_script_reviewer = json.loads(json.dumps(review))
        wrong_script_reviewer["script_review"]["reviewer_run_id"] = "RUN-FORGED-SCRIPT"
        self.assertIn(
            "E_REVIEW_TOOL_REPLAY_BINDING",
            gt.validate_review_command_replay(wrong_script_reviewer, CANONICAL),
        )


class CanonicalMutationTests(unittest.TestCase):
    def rebind_copied_evidence(self, root: Path) -> None:
        evidence_path = root / VERSION / "evidence/evidence.jsonl"
        records = jsonl(evidence_path)
        for record in records:
            artifact = root / record["artifact_ref"]
            log = root / record["command"]["log_path"]
            artifact_stat = artifact.stat()
            log_stat = log.stat()
            record.update(
                {
                    "artifact_sha256": sha256_path(artifact),
                    "artifact_size": artifact_stat.st_size,
                    "artifact_mtime_ns": artifact_stat.st_mtime_ns,
                }
            )
            record["command"].update(
                {
                    "log_sha256": sha256_path(log),
                    "log_size": log_stat.st_size,
                    "log_mtime_ns": log_stat.st_mtime_ns,
                }
            )
            command = record["command"]
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
            execution_path.write_text(
                json.dumps(execution, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            command.update(
                execution_record_sha256=sha256_path(execution_path),
                execution_record_size=execution_path.stat().st_size,
            )
            integrity = record["integrity_replay"]
            integrity["argv"] = gt.artifact_verifier_argv(
                record["artifact_ref"],
                record["artifact_sha256"],
                gt.evidence_replay_binding_digest(record),
            )
            proc = subprocess.run(
                integrity["argv"],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, b"")
            integrity_log = root / integrity["log_path"]
            integrity_log.write_bytes(proc.stdout)
            integrity_stat = integrity_log.stat()
            integrity.update(
                exit_code=proc.returncode,
                log_sha256=sha256_path(integrity_log),
                log_size=integrity_stat.st_size,
                log_mtime_ns=integrity_stat.st_mtime_ns,
            )
        evidence_path.write_text(
            "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        standalone = {
            "EVD-CAN-001": "evidence.json",
            "EVD-CAN-002": "evidence-recovery.json",
        }
        for record in records:
            filename = standalone.get(record["evidence_id"])
            if filename:
                (root / VERSION / "evidence" / filename).write_text(
                    json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
        trace_path = root / VERSION / "harness/traceability.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        trace["evidence"] = records
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def assert_mutation_rejected(self, mutate, label: str, expected_code: str) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "examples") as td:
            root = Path(td)
            shutil.copytree(CANONICAL, root, dirs_exist_ok=True)
            pristine_errors = gt.validate_canonical(root)
            self.assertEqual(pristine_errors, [], f"pristine copied canonical is invalid before {label}: {pristine_errors}")
            mutate(root)
            errors = gt.validate_canonical(root)
            self.assertTrue(
                any(error == expected_code or error.startswith(expected_code + ":") for error in errors),
                f"canonical mutation {label} expected {expected_code}, got {errors}",
            )
            proc = run_cli("validate-canonical", str(root))
            self.assertNotEqual(proc.returncode, 0, f"{label}: {proc.stdout}")
            envelope = parse_envelope(proc)
            self.assertFalse(envelope["ok"])
            self.assertTrue(
                any(error == expected_code or str(error).startswith(expected_code + ":") for error in envelope.get("errors", [])),
                envelope,
            )

    def test_full_chain_mutation_matrix_fails_closed(self) -> None:
        def delete(rel: str):
            return lambda root: (root / VERSION / rel).unlink()

        def malformed(rel: str):
            return lambda root: (root / VERSION / rel).write_text("{malformed\n", encoding="utf-8")

        def tamper_tasklist(root: Path) -> None:
            path = root / VERSION / "TaskList.md"
            path.write_text(path.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

        def tamper_artifact(root: Path) -> None:
            (root / VERSION / "evidence/artifact.txt").write_text("tampered\n", encoding="utf-8")

        def empty_audit(root: Path) -> None:
            (root / VERSION / "audit/completion-audit.json").write_text("{}\n", encoding="utf-8")

        def remove_ac2_evidence(root: Path) -> None:
            path = root / VERSION / "harness/traceability.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["evidence"] = [row for row in payload["evidence"] if row.get("check_id") != "CHECK-CAN-RECOVERY"]
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def self_review(root: Path) -> None:
            path = root / VERSION / "reviews/dual-review.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["reviewer_run_id"] = payload["author_run_id"]
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def dual_review_evidence_hash(root: Path) -> None:
            path = root / VERSION / "reviews/dual-review.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["script_review"]["evidence_sha256"] = "0" * 64
            payload["llm_review"]["evidence_sha256"] = "0" * 64
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def static_behavior(root: Path) -> None:
            path = root / VERSION / "behavior/plan-preview.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.pop("provenance", None)
            payload["executed"] = True
            payload["result"] = "passed"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def failed_behavior(root: Path) -> None:
            path = root / VERSION / "behavior/plan-preview.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["result"] = "failed"
            payload["score"]["quality"] = -999
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def invalid_check(root: Path) -> None:
            path = root / VERSION / "harness/harness.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["harness_contract"]["checks"][0].pop("validator_run_id", None)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def invalid_run(root: Path) -> None:
            path = root / VERSION / "harness/harness.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["runs"][0].pop("producer_run_id", None)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def id_only_traceability(root: Path) -> None:
            path = root / VERSION / "harness/traceability.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["tasks"] = [{"task_id": "TASK-CAN-SUCCESS", "requirement_refs": ["REQ-CAN-001"], "acceptance_criteria_refs": ["AC-CAN-001"]}]
            payload["checks"] = [{"check_id": "CHECK-CAN-SUCCESS", "acceptance_criteria_refs": ["AC-CAN-001"]}]
            payload["runs"] = [{"run_id": "RUN-CAN-SUCCESS", "check_id": "CHECK-CAN-SUCCESS", "status": "passed"}]
            payload["evidence"] = [{"evidence_id": "EVD-CAN-001", "check_id": "CHECK-CAN-SUCCESS", "run_id": "RUN-CAN-SUCCESS", "current": True}]
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def nonexistent_acceptance_evidence(root: Path) -> None:
            path = root / VERSION / "ledger/events.jsonl"
            events = jsonl(path)
            accepted = next(event for event in events if event.get("payload", {}).get("task_state") == "accepted")
            accepted["payload"]["evidence_refs"] = ["EVD-DOES-NOT-EXIST"]
            path.write_text("".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in events), encoding="utf-8")

        def raw_secret_log(root: Path) -> None:
            (root / VERSION / "evidence/run.log").write_text(
                "Authorization: Bearer canonical-raw-secret\n", encoding="utf-8"
            )
            self.rebind_copied_evidence(root)

        mutations = {
            "missing_evidence_file": (delete("evidence/evidence.jsonl"), "E_CANONICAL_MISSING"),
            "missing_review_file": (delete("reviews/semantic-review.md"), "E_CANONICAL_MISSING"),
            "missing_behavior_scenario": (delete("behavior/plan-preview.json"), "E_CANONICAL_BEHAVIOR_COVERAGE"),
            "malformed_ledger": (malformed("ledger/events.jsonl"), "E_JSONL_PARSE"),
            "malformed_evidence": (malformed("evidence/evidence.jsonl"), "E_JSONL_PARSE"),
            "empty_completion_audit": (empty_audit, "E_AUDIT_SCHEMA"),
            "projection_drift": (tamper_tasklist, "E_CANONICAL_PROJECTION"),
            "artifact_hash_drift": (tamper_artifact, "E_HASH_MISMATCH"),
            "required_ac_missing_evidence": (remove_ac2_evidence, "E_CANONICAL_TRACEABILITY"),
            "self_review": (self_review, "E_REVIEW_SELF"),
            "dual_review_evidence_hash": (dual_review_evidence_hash, "E_REVIEW_EVIDENCE_HASH"),
            "static_behavior_self_report": (static_behavior, "E_BEHAVIOR_PROVENANCE"),
            "failed_behavior_and_invalid_score": (failed_behavior, "E_BEHAVIOR_RESULT"),
            "invalid_check": (invalid_check, "E_CHECK_IDENTITY"),
            "invalid_run": (invalid_run, "E_RUN_REQUIRED"),
            "id_only_traceability": (id_only_traceability, "E_TRACEABILITY_NODE_INVALID"),
            "accepted_nonexistent_evidence": (nonexistent_acceptance_evidence, "E_TASK_ACCEPTED_EVIDENCE"),
            "raw_secret_log": (raw_secret_log, "E_LOG_SECRET"),
        }
        for label, (mutate, expected_code) in mutations.items():
            with self.subTest(mutation=label):
                self.assert_mutation_rejected(mutate, label, expected_code)


if __name__ == "__main__":
    unittest.main()
