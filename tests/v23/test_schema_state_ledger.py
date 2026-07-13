"""V2.3 schema, state-machine, reducer and projection contract tests."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT, gt, has_error, parse_envelope, run_cli, sha256_path, task_event


EXPECTED_ENUMS = {
    "task_state": {"planned", "running", "review", "accepted", "blocked", "deferred", "cancelled"},
    "run_outcome": {"achieved", "partial", "blocked", "aborted"},
    "loop_decision": {"continue", "replan", "stop"},
    "check_state": {"not_required", "not_started", "running", "passed", "failed", "blocked", "waived"},
    "profile": {"lite", "standard", "full", "regulated"},
    "trust_level": {"local_verified", "externally_referenced", "manual_observation", "unverified"},
}

# Direct task_patch transitions. Reopening an accepted task requires a separate,
# explicitly audited operation and therefore is not a direct state transition.
EXPECTED_TRANSITIONS = {
    "planned": {"running", "blocked", "deferred", "cancelled"},
    "running": {"review", "blocked", "deferred", "cancelled"},
    "review": {"running", "accepted", "blocked", "deferred", "cancelled"},
    "accepted": set(),
    "blocked": {"running", "deferred", "cancelled"},
    "deferred": {"planned", "running", "cancelled"},
    "cancelled": set(),
}

PATH_TO_RUNTIME_CONSTANT = {
    "task_state": "TASK_STATES",
    "run_outcome": "RUN_OUTCOMES",
    "loop_decision": "LOOP_DECISIONS",
    "check_state": "CHECK_STATES",
    "profile": "PROFILES",
    "trust_level": "TRUST_LEVELS",
}


def find_v23_schema() -> tuple[Path, dict]:
    matches: list[tuple[Path, dict]] = []
    for path in sorted((ROOT / "schemas").rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema_version") == "goal-teams-v2.3":
            matches.append((path, payload))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one V2.3 schema source, found {[str(p) for p, _ in matches]}")
    return matches[0]


def schema_enum(schema: dict, name: str) -> set[str]:
    enums = schema.get("enums")
    if isinstance(enums, dict) and isinstance(enums.get(name), list):
        return set(enums[name])
    definitions = schema.get("definitions", {})
    entry = definitions.get(name, {}) if isinstance(definitions, dict) else {}
    if isinstance(entry, dict) and isinstance(entry.get("enum"), list):
        return set(entry["enum"])
    raise AssertionError(f"schema does not expose enum {name!r} from its canonical source")


def make_source_revision(root: Path) -> tuple[str, str]:
    source = root / "source.txt"
    source.write_text("source-current fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "state-fixture@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "State Fixture"], cwd=root, check=True
    )
    subprocess.run(["git", "add", source.name], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "source baseline"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return commit, gt.source_manifest_sha256(root, [source.name])


def bind_evidence_execution(root: Path, evidence: dict) -> None:
    command = evidence["command"]
    execution = {
        "schema_version": "goal-teams-v2.3",
        "record_type": "command_execution",
        "evidence_id": evidence["evidence_id"],
        "check_id": evidence["check_id"],
        "run_id": evidence["run_id"],
        "attempt_id": evidence["attempt_id"],
        "producer_run_id": evidence["producer_run_id"],
        "argv": command["argv"],
        "cwd": command["cwd"],
        "started_at": command["started_at"],
        "ended_at": command["ended_at"],
        "exit_code": command["exit_code"],
        "log_path": command["log_path"],
        "log_sha256": command["log_sha256"],
        "log_size": command["log_size"],
    }
    execution_path = root / f"execution-{evidence['evidence_id']}.json"
    execution_path.write_text(
        json.dumps(execution, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    command.update(
        execution_record_path=execution_path.name,
        execution_record_sha256=sha256_path(execution_path),
        execution_record_size=execution_path.stat().st_size,
    )
    binding_digest = gt.evidence_replay_binding_digest(evidence)
    argv = gt.artifact_verifier_argv(
        evidence["artifact_ref"], evidence["artifact_sha256"], binding_digest
    )
    proc = subprocess.run(
        argv,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 or proc.stderr:
        raise AssertionError(
            f"state Evidence integrity replay failed: {proc.returncode} {proc.stderr!r}"
        )
    integrity_path = root / f"integrity-{evidence['evidence_id']}.log"
    integrity_path.write_bytes(proc.stdout)
    evidence["integrity_replay"] = {
        "argv": argv,
        "cwd": ".",
        "started_at": command["ended_at"],
        "ended_at": evidence["created_at"],
        "exit_code": proc.returncode,
        "log_path": integrity_path.name,
        "log_sha256": sha256_path(integrity_path),
        "log_size": integrity_path.stat().st_size,
        "log_mtime_ns": integrity_path.stat().st_mtime_ns,
    }


class SchemaSingleSourceTests(unittest.TestCase):
    def test_versioned_schema_is_single_source_for_all_core_enums(self) -> None:
        _, schema = find_v23_schema()
        for schema_name, expected in EXPECTED_ENUMS.items():
            with self.subTest(enum=schema_name):
                self.assertEqual(schema_enum(schema, schema_name), expected)
                runtime_name = PATH_TO_RUNTIME_CONSTANT[schema_name]
                self.assertTrue(hasattr(gt, runtime_name), f"runtime missing generated constant {runtime_name}")
                self.assertEqual(set(getattr(gt, runtime_name)), expected)

    def test_schema_contains_transition_matrix_and_source_digest(self) -> None:
        schema_path, schema = find_v23_schema()
        transitions = schema.get("task_state_transitions")
        self.assertIsInstance(transitions, dict)
        self.assertEqual({key: set(value) for key, value in transitions.items()}, EXPECTED_TRANSITIONS)
        lock_path = schema_path.with_name("schema.lock.json")
        self.assertTrue(lock_path.is_file(), "versioned schema requires a generated-source lock")
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock_hash = lock.get("source_sha256", lock.get("schema_sha256", ""))
        self.assertRegex(str(lock_hash), r"^[0-9a-f]{64}$")
        self.assertEqual(lock_hash, sha256_path(schema_path))


class StateMachineTests(unittest.TestCase):
    def test_every_direct_transition_pair_matches_contract(self) -> None:
        self.assertTrue(hasattr(gt, "task_transition_allowed"), "runtime must expose task_transition_allowed")
        for source in EXPECTED_ENUMS["task_state"]:
            for target in EXPECTED_ENUMS["task_state"]:
                with self.subTest(source=source, target=target):
                    expected = target == source or target in EXPECTED_TRANSITIONS[source]
                    self.assertIs(gt.task_transition_allowed(source, target), expected)

    def test_accepted_cannot_return_to_running_without_audited_reopen(self) -> None:
        initial = task_event(
            "E1",
            "TASK-1",
            0,
            "planned",
            attempt_id="ATT-1",
            payload={
                "title": "Accepted task",
                "required_for_done": True,
                "acceptance_blocking": True,
                "owner_member_id": "实现-1",
                "validator_member_id": "评审-1",
                "owner_run_id": "RUN-OWNER-TASK-1",
                "validator_run_id": "RUN-VALIDATOR-TASK-1",
                "merge_owner_run_id": "RUN-LEDGER-OWNER",
                "check_state": "not_started",
                "requirement_refs": ["REQ-1"],
                "acceptance_criteria_refs": ["AC-1"],
                "artifact_refs": ["artifact.txt"],
                "evidence_refs": [],
                "harness_refs": ["harness.json"],
            },
        )
        review = task_event(
            "E3",
            "TASK-1",
            2,
            "review",
            attempt_id="ATT-1",
        )
        check = task_event(
            "E4",
            "TASK-1",
            3,
            "review",
            attempt_id="ATT-1",
            payload={
                "check_state": "passed",
                "evidence_refs": ["EVD-1"],
                "validation_check_id": "CHECK-1",
                "validation_run_id": "RUN-CHECK-1",
            },
        )
        check.update(
            {
                "event_type": "check_executed",
                "actor_run_id": "RUN-VALIDATOR-TASK-1",
                "validation_check_id": "CHECK-1",
                "validation_run_id": "RUN-CHECK-1",
            }
        )
        accepted = task_event("E5", "TASK-1", 4, "accepted", attempt_id="ATT-1")
        accepted.update(
            {
                "event_type": "review_completed",
                "actor_run_id": "RUN-VALIDATOR-TASK-1",
                "validation_check_id": "CHECK-1",
                "validation_run_id": "RUN-CHECK-1",
            }
        )
        accepted["payload"].update(
            {"validation_check_id": "CHECK-1", "validation_run_id": "RUN-CHECK-1"}
        )
        running = task_event("E2", "TASK-1", 1, "running", attempt_id="ATT-1")
        reopened = task_event("E6", "TASK-1", 5, "running", attempt_id="ATT-1")
        events = [initial, running, review, check, accepted, reopened]
        for second, ledger_event in enumerate(events):
            ledger_event["timestamp"] = f"2026-07-10T00:00:{second:02d}Z"
        prefix_revision = 3
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "artifact.txt"
            log = root / "run.log"
            artifact.write_text("verified\n", encoding="utf-8")
            log.write_text("passed\n", encoding="utf-8")
            source_commit, source_revision = make_source_revision(root)
            artifact_stat = artifact.stat()
            log_stat = log.stat()
            evidence = {
                "schema_version": "goal-teams-v2.3",
                "evidence_id": "EVD-1",
                "check_id": "CHECK-1",
                "run_id": "RUN-CHECK-1",
                "attempt_id": "ATT-1",
                "artifact_ref": "artifact.txt",
                "artifact_sha256": sha256_path(artifact),
                "artifact_size": artifact_stat.st_size,
                "artifact_mtime_ns": artifact_stat.st_mtime_ns,
                "producer_run_id": "RUN-OWNER-TASK-1",
                "created_at": "2026-07-10T00:00:03Z",
                "trust_level": "local_verified",
                "evidence_kind": "command_execution",
                "command": {
                    "argv": ["true"],
                    "cwd": ".",
                    "started_at": "2026-07-10T00:00:02Z",
                    "ended_at": "2026-07-10T00:00:03Z",
                    "exit_code": 0,
                    "log_path": "run.log",
                    "log_sha256": sha256_path(log),
                    "log_size": log_stat.st_size,
                    "log_mtime_ns": log_stat.st_mtime_ns,
                },
                "environment": {
                    "commit": source_commit,
                    "workspace_revision": source_revision,
                    "source_paths": ["source.txt"],
                    "platform": "test",
                    "python_version": "test",
                    "ledger_revision": prefix_revision,
                    "ledger_prefix_sha256": gt.ledger_prefix_sha256(
                        events, prefix_revision
                    ),
                },
            }
            bind_evidence_execution(root, evidence)
            registry, errors = gt.build_evidence_registry(
                [evidence],
                root,
                ledger_events=events[:-1],
                source_root=root,
            )
            self.assertEqual(errors, [])
            state = gt.reduce_events(
                events,
                valid_evidence_ids={"EVD-1"},
                evidence_registry=registry,
            )
            unverified = gt.reduce_events(
                events[:-1],
                valid_evidence_ids={"EVD-1"},
                evidence_registry=dict(registry),
            )
        self.assertEqual(state["tasks"]["TASK-1"]["task_state"], "accepted")
        self.assertTrue(has_error(state.get("conflicts", []), "E_STATE_TRANSITION"))
        self.assertTrue(
            has_error(unverified.get("conflicts", []), "E_TASK_EVIDENCE_REGISTRY_UNVERIFIED")
        )

    def test_live_evidence_prefix_survives_acceptance_and_later_task_append(self) -> None:
        primary = task_event(
            "LIVE-1",
            "TASK-LIVE",
            0,
            "planned",
            attempt_id="ATT-LIVE",
            payload={
                "title": "Live prefix task",
                "required_for_done": True,
                "acceptance_blocking": True,
                "requirement_refs": ["REQ-LIVE"],
                "acceptance_criteria_refs": ["AC-LIVE"],
                "artifact_refs": ["artifact.txt"],
                "harness_refs": ["harness.json"],
            },
        )
        running = task_event(
            "LIVE-2", "TASK-LIVE", 1, "running", attempt_id="ATT-LIVE"
        )
        review = task_event(
            "LIVE-3", "TASK-LIVE", 2, "review", attempt_id="ATT-LIVE"
        )
        check = task_event(
            "LIVE-4",
            "TASK-LIVE",
            3,
            "review",
            attempt_id="ATT-LIVE",
            payload={
                "check_state": "passed",
                "evidence_refs": ["EVD-LIVE"],
                "validation_check_id": "CHECK-LIVE",
                "validation_run_id": "RUN-CHECK-LIVE",
            },
        )
        check.update(
            {
                "event_type": "check_executed",
                "actor_run_id": "RUN-VALIDATOR-TASK-LIVE",
                "validation_check_id": "CHECK-LIVE",
                "validation_run_id": "RUN-CHECK-LIVE",
            }
        )
        accepted = task_event(
            "LIVE-5", "TASK-LIVE", 4, "accepted", attempt_id="ATT-LIVE"
        )
        accepted.update(
            {
                "event_type": "review_completed",
                "actor_run_id": "RUN-VALIDATOR-TASK-LIVE",
                "validation_check_id": "CHECK-LIVE",
                "validation_run_id": "RUN-CHECK-LIVE",
            }
        )
        accepted["payload"].update(
            {
                "validation_check_id": "CHECK-LIVE",
                "validation_run_id": "RUN-CHECK-LIVE",
            }
        )
        later_append = task_event(
            "LIVE-6", "TASK-LATER", 0, "planned", attempt_id="ATT-LATER"
        )
        events = [primary, running, review, check, accepted, later_append]
        for second, ledger_event in enumerate(events):
            ledger_event["timestamp"] = f"2026-07-10T00:00:{second:02d}Z"

        prefix_revision = 3
        prefix_digest = gt.ledger_prefix_sha256(events, prefix_revision)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "artifact.txt"
            log = root / "run.log"
            artifact.write_text("live verified\n", encoding="utf-8")
            log.write_text("live command passed\n", encoding="utf-8")
            source_commit, source_revision = make_source_revision(root)
            artifact_stat = artifact.stat()
            log_stat = log.stat()
            evidence = {
                "schema_version": "goal-teams-v2.3",
                "evidence_id": "EVD-LIVE",
                "check_id": "CHECK-LIVE",
                "run_id": "RUN-CHECK-LIVE",
                "attempt_id": "ATT-LIVE",
                "artifact_ref": "artifact.txt",
                "artifact_sha256": sha256_path(artifact),
                "artifact_size": artifact_stat.st_size,
                "artifact_mtime_ns": artifact_stat.st_mtime_ns,
                "producer_run_id": "RUN-OWNER-TASK-LIVE",
                "created_at": "2026-07-10T00:00:03Z",
                "trust_level": "local_verified",
                "evidence_kind": "command_execution",
                "command": {
                    "argv": ["true"],
                    "cwd": ".",
                    "started_at": "2026-07-10T00:00:02Z",
                    "ended_at": "2026-07-10T00:00:03Z",
                    "exit_code": 0,
                    "log_path": "run.log",
                    "log_sha256": sha256_path(log),
                    "log_size": log_stat.st_size,
                    "log_mtime_ns": log_stat.st_mtime_ns,
                },
                "environment": {
                    "commit": source_commit,
                    "workspace_revision": source_revision,
                    "source_paths": ["source.txt"],
                    "platform": "test",
                    "python_version": "test",
                    "ledger_revision": prefix_revision,
                    "ledger_prefix_sha256": prefix_digest,
                },
            }
            bind_evidence_execution(root, evidence)
            registry, errors = gt.build_evidence_registry(
                [evidence],
                root,
                ledger_events=events,
                source_root=root,
            )
            self.assertEqual(errors, [])
            self.assertTrue(registry["EVD-LIVE"]["valid_for_acceptance"])
            state = gt.reduce_events(
                events,
                valid_evidence_ids={"EVD-LIVE"},
                evidence_registry=registry,
            )

        self.assertEqual(state.get("conflicts"), [])
        self.assertEqual(state["tasks"]["TASK-LIVE"]["task_state"], "accepted")
        self.assertEqual(state["tasks"]["TASK-LATER"]["task_state"], "planned")
        self.assertEqual(
            gt.ledger_prefix_sha256(events, prefix_revision),
            prefix_digest,
            "legal later appends must not invalidate an earlier Evidence prefix",
        )

    def test_empty_task_set_never_vacuously_achieves_goal(self) -> None:
        self.assertNotEqual(gt.goal_outcome([], "passed", valid_evidence_ids=set()), "achieved")

    def test_required_and_acceptance_blocking_tasks_gate_achieved(self) -> None:
        accepted = {
            "schema_version": "goal-teams-v2.3",
            "task_id": "TASK-1",
            "title": "Accepted task",
            "task_state": "accepted",
            "required_for_done": True,
            "acceptance_blocking": True,
            "owner_member_id": "实现-1",
            "validator_member_id": "评审-1",
            "owner_run_id": "RUN-OWNER",
            "validator_run_id": "RUN-VALIDATOR",
            "merge_owner_run_id": "RUN-LEDGER-OWNER",
            "last_actor_run_id": "RUN-VALIDATOR",
            "check_state": "passed",
            "validation_check_id": "CHECK-1",
            "validation_run_id": "RUN-CHECK-1",
            "requirement_refs": ["REQ-1"],
            "acceptance_criteria_refs": ["AC-1"],
            "attempt_id": "ATT-1",
            "revision": 4,
            "artifact_refs": ["artifact.txt"],
            "evidence_refs": ["EVD-1"],
            "harness_refs": ["harness.json"],
        }
        cases = [
            ([accepted], "passed", {"EVD-1"}, "achieved"),
            ([{"task_state": "review", "required_for_done": True, "acceptance_blocking": True}], "passed", "partial"),
            ([{"task_state": "blocked", "required_for_done": True, "acceptance_blocking": True}], "passed", "blocked"),
            ([{"task_state": "deferred", "required_for_done": False, "acceptance_blocking": False}, accepted], "passed", {"EVD-1"}, "achieved"),
            ([{"task_state": "accepted", "required_for_done": True, "acceptance_blocking": True}], "failed", "partial"),
        ]
        normalized = [
            case if len(case) == 4 else (case[0], case[1], set(), case[2])
            for case in cases
        ]
        for tasks, audit, valid_ids, expected in normalized:
            with self.subTest(tasks=tasks, audit=audit):
                registry = gt.ValidatedEvidenceRegistry({
                    "EVD-1": {
                        "valid_for_acceptance": True,
                        "check_id": "CHECK-1",
                        "run_id": "RUN-CHECK-1",
                        "attempt_id": "ATT-1",
                    }
                }, "TEST-REGISTRY")
                self.assertEqual(
                    gt.goal_outcome(tasks, audit, valid_evidence_ids=valid_ids, evidence_registry=registry),
                    expected,
                )

    def test_accepted_task_requires_independent_runs_passed_check_and_valid_registry(self) -> None:
        task = {
            "schema_version": "goal-teams-v2.3",
            "task_id": "TASK-ACCEPTED",
            "title": "Accepted task",
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
            "validation_run_id": "RUN-CHECK-1",
        }
        self.assertTrue(has_error(gt.validate_task(task), "E_TASK_EVIDENCE_REGISTRY"))
        self.assertTrue(has_error(gt.validate_task(task, valid_evidence_ids=set()), "E_TASK_ACCEPTED_EVIDENCE"))
        registry = gt.ValidatedEvidenceRegistry({
            "EVD-1": {
                "valid_for_acceptance": True,
                "check_id": "CHECK-1",
                "run_id": "RUN-CHECK-1",
                "attempt_id": "ATT-1",
            }
        }, "TEST-REGISTRY")
        self.assertEqual(gt.validate_task(task, evidence_registry=registry), [])
        same_run = dict(task, validator_run_id="RUN-OWNER")
        self.assertTrue(has_error(gt.validate_task(same_run, evidence_registry=registry), "E_TASK_REVIEW_IDENTITY"))
        failed_check = dict(task, check_state="failed")
        self.assertTrue(has_error(gt.validate_task(failed_check, evidence_registry=registry), "E_TASK_CHECK_NOT_PASSED"))

    def test_waived_or_not_required_checks_are_only_valid_for_nonblocking_optional_scope(self) -> None:
        waived = {
            "schema_version": "goal-teams-v2.3",
            "check_id": "CHECK-WAIVED",
            "validator_run_id": "RUN-VALIDATOR",
            "check_state": "waived",
            "required": False,
            "acceptance_blocking": False,
            "acceptance_criteria_refs": [],
            "evidence_refs": [],
            "waiver_evidence_ref": "waiver.json",
            "waiver_reason": "optional environment is unavailable",
            "waiver_reviewer_run_id": "RUN-INDEPENDENT-REVIEWER",
        }
        self.assertEqual(gt.validate_check(waived), [])
        required = dict(waived, required=True, acceptance_blocking=True)
        self.assertTrue(has_error(gt.validate_check(required), "E_CHECK_WAIVER_SCOPE"))
        not_required = {
            **waived,
            "check_state": "not_required",
            "not_applicable_reason": "optional branch",
            "reviewer_run_id": "RUN-INDEPENDENT-REVIEWER",
        }
        self.assertEqual(gt.validate_check(not_required), [])
        required_na = dict(not_required, required=True)
        self.assertTrue(has_error(gt.validate_check(required_na), "E_CHECK_NOT_REQUIRED_SCOPE"))


class LedgerReducerTests(unittest.TestCase):
    def test_task_local_cas_allows_independent_tasks_at_revision_zero(self) -> None:
        state = gt.reduce_events(
            [
                task_event("E1", "TASK-A", 0, "planned"),
                task_event("E2", "TASK-B", 0, "planned"),
            ]
        )
        self.assertEqual(set(state["tasks"]), {"TASK-A", "TASK-B"})
        self.assertEqual(state["tasks"]["TASK-A"]["revision"], 1)
        self.assertEqual(state["tasks"]["TASK-B"]["revision"], 1)
        self.assertEqual(state.get("conflicts"), [])

    def test_stale_revision_on_same_task_is_rejected_with_rebase_data(self) -> None:
        state = gt.reduce_events(
            [
                task_event("E1", "TASK-A", 0, "planned"),
                task_event("E2", "TASK-A", 0, "running"),
            ]
        )
        self.assertEqual(state["tasks"]["TASK-A"]["task_state"], "planned")
        conflict = state["conflicts"][0]
        self.assertEqual(conflict.get("error"), "E_REVISION_CONFLICT")
        self.assertEqual(conflict.get("expected_revision"), 1)
        self.assertEqual(conflict.get("base_revision"), 0)

    def test_reduce_ledger_cli_conflict_is_nonzero_stable_envelope(self) -> None:
        events = [
            task_event("E1", "TASK-A", 0, "planned"),
            task_event("E2", "TASK-A", 0, "running"),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "events.jsonl"
            path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
            proc = run_cli("reduce-ledger", str(path))
        self.assertNotEqual(proc.returncode, 0)
        envelope = parse_envelope(proc)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error_code"], "E_REVISION_CONFLICT")
        self.assertTrue(envelope["state"]["conflicts"])

    def test_identical_duplicate_event_is_idempotent(self) -> None:
        event = task_event("E1", "TASK-A", 0, "planned")
        once = gt.reduce_events([event])
        twice = gt.reduce_events([event, dict(event)])
        self.assertEqual(once["tasks"], twice["tasks"])
        self.assertEqual(once.get("ledger_revision", once.get("revision")), twice.get("ledger_revision", twice.get("revision")))
        self.assertEqual(twice.get("conflicts"), [])

    def test_same_event_id_with_different_content_is_a_conflict(self) -> None:
        original = task_event("E1", "TASK-A", 0, "planned")
        forged = task_event("E1", "TASK-A", 0, "blocked")
        state = gt.reduce_events([original, forged])
        self.assertEqual(state["tasks"]["TASK-A"]["task_state"], "planned")
        self.assertTrue(has_error(state.get("conflicts", []), "E_EVENT_ID_COLLISION"))

    def test_duplicate_event_liveness_is_idempotent_and_fail_closed(self) -> None:
        event = task_event(
            "EVT-IDEMPOTENT",
            "TASK-IDEMPOTENT",
            0,
            "planned",
            attempt_id="ATT-IDEMPOTENT",
        )
        forged_digest = json.loads(json.dumps(event))
        forged_digest["event_digest"] = "0" * 64
        reduced = gt.reduce_events([event, forged_digest])
        self.assertTrue(
            has_error(reduced.get("conflicts", []), "E_EVENT_DIGEST"),
            reduced,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "events.jsonl"
            event_path = root / "event.json"
            event_path.write_text(json.dumps(event), encoding="utf-8")

            first = run_cli(
                "append-event",
                str(ledger),
                str(event_path),
                "--ledger-owner-run-id",
                "RUN-LEDGER-OWNER",
            )
            second = run_cli(
                "append-event",
                str(ledger),
                str(event_path),
                "--ledger-owner-run-id",
                "RUN-LEDGER-OWNER",
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 1)

            collision = json.loads(json.dumps(event))
            collision["payload"]["title"] = "different content under same event id"
            event_path.write_text(json.dumps(collision), encoding="utf-8")
            collision_proc = run_cli(
                "append-event",
                str(ledger),
                str(event_path),
                "--ledger-owner-run-id",
                "RUN-LEDGER-OWNER",
            )
            self.assertNotEqual(collision_proc.returncode, 0)
            self.assertIn(
                "E_EVENT_ID_COLLISION",
                parse_envelope(collision_proc).get("errors", []),
            )
            self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 1)

            event_path.write_text(json.dumps(forged_digest), encoding="utf-8")
            forged_proc = run_cli(
                "append-event",
                str(ledger),
                str(event_path),
                "--ledger-owner-run-id",
                "RUN-LEDGER-OWNER",
            )
            self.assertNotEqual(forged_proc.returncode, 0)
            self.assertIn("E_EVENT_DIGEST", parse_envelope(forged_proc).get("errors", []))
            self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 1)

    def test_payload_cannot_overwrite_reserved_ledger_fields(self) -> None:
        reserved = ["task_id", "revision", "last_event_id", "event_digest", "base_revision", "attempt_id"]
        for field in reserved:
            with self.subTest(field=field):
                state = gt.reduce_events(
                    [task_event("E1", "TASK-A", 0, "planned", payload={field: "FORGED"})]
                )
                self.assertNotIn("TASK-A", state["tasks"])
                self.assertTrue(has_error(state.get("conflicts", []), "E_RESERVED_PAYLOAD_FIELD"))

    def test_projection_is_byte_equivalent_for_same_event_log(self) -> None:
        events = [
            task_event("E1", "TASK-B", 0, "planned"),
            task_event("E2", "TASK-A", 0, "planned"),
            task_event("E3", "TASK-A", 1, "running"),
        ]
        first = gt.render_tasklist(gt.reduce_events(events))
        second = gt.render_tasklist(gt.reduce_events(json.loads(json.dumps(events))))
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))
        self.assertIn("timestamp:", first)

    def test_projection_preserves_handoff_ssot_identity_check_trace_and_harness_fields(self) -> None:
        task = {
            "task_id": "TASK-FULL",
            "title": "Full handoff",
            "task_state": "review",
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
            "revision": 3,
            "artifact_refs": ["artifact.txt"],
            "evidence_refs": ["EVD-1"],
            "harness_refs": ["harness.json"],
            "last_event_id": "EVT-3",
        }
        rendered = gt.render_tasklist(
            {"schema_version": "goal-teams-v2.3", "ledger_revision": 3, "tasks": {"TASK-FULL": task}}
        )
        for value in (
            "RUN-OWNER",
            "RUN-VALIDATOR",
            "RUN-LEDGER-OWNER",
            "passed",
            "REQ-1",
            "AC-1",
            "artifact.txt",
            "EVD-1",
            "harness.json",
            "EVT-3",
        ):
            with self.subTest(value=value):
                self.assertIn(value, rendered)


class LoopContractTests(unittest.TestCase):
    def loop(self) -> dict:
        return {
            "schema_version": "goal-teams-v2.3",
            "loop_id": "LOOP-1",
            "artifact_version": "V2.3",
            "workspace_commit": "HEAD",
            "attempt_id": "ATT-1",
            "last_event_id": "EVT-1",
            "ledger_revision": 1,
            "updated_at": "2026-07-10T00:00:00Z",
            "active_member_runs": [],
            "loop_decision": "continue",
            "run_outcome": "partial",
            "stop_reason": None,
        }

    def test_loop_requires_outcome_and_rejects_decision_reason_contradictions(self) -> None:
        self.assertEqual(gt.validate_loop(self.loop()), [])
        achieved = self.loop()
        achieved.update(loop_decision="stop", run_outcome="achieved", stop_reason="achieved")
        self.assertEqual(gt.validate_loop(achieved), [])
        cases = {
            "missing_schema": (
                lambda doc: doc.pop("schema_version"),
                "E_LOOP_SCHEMA",
            ),
            "missing_outcome": (
                lambda doc: doc.pop("run_outcome"),
                "E_LOOP_OUTCOME",
            ),
            "blocked_claims_achieved": (
                lambda doc: doc.update(loop_decision="stop", run_outcome="blocked", stop_reason="achieved"),
                "E_LOOP_OUTCOME_CONTRADICTION",
            ),
            "continue_claims_achieved": (
                lambda doc: doc.update(loop_decision="continue", run_outcome="achieved", stop_reason=None),
                "E_LOOP_OUTCOME_CONTRADICTION",
            ),
            "continue_has_stop_reason": (
                lambda doc: doc.update(stop_reason="achieved"),
                "E_LOOP_STOP_REASON",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(case=name):
                value = self.loop()
                mutate(value)
                self.assertTrue(has_error(gt.validate_loop(value), expected))


if __name__ == "__main__":
    unittest.main()
