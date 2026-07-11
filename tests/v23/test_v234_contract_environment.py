"""V2.34 immutable-contract and Architecture→Environment gate TDD tests."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Any

from tests.v23.common import gt, sha256_path, task_event
from tests.v23.test_v234_state_loop import (
    FIXED_HASH_A,
    FIXED_HASH_B,
    FIXED_HASH_C,
    OWNER_RUN,
    VALIDATOR_RUN,
    assert_error_code,
    canonical_hash,
    require_v234,
)


CONTRACT_OWNER = "RUN-REQ-CONTRACT-V234-01"
CONTRACT_VALIDATOR = "RUN-REVIEW-DESIGN-V234-01"
ARCH_OWNER = "RUN-ARCH-V234-01"
ARCH_VALIDATOR = "RUN-REVIEW-DESIGN-V234-01"
ENV_OWNER = "RUN-RUNTIME-DEV-V234-01"
ENV_VALIDATOR = "RUN-QA-V234-01"
ENV_PRODUCER = "RUN-ENV-CHECK-V234-01"
ACTUAL_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "GoalTeamsWork-V2.34"
    / "versions"
    / "V2.34"
    / "contract.md"
)
ACTUAL_CONTRACT_SHA256 = "26da4c22c2272924b5a40cca5822f4a4fc6ee8d2f8ace32e7c6327ad0cdf0a20"
ACTUAL_ASSERTION_SET_SHA256 = "c3738164d70edfdb2569bd8858f258e62b32c74e4df7be5e322079f8f1ec1c9d"
# Frozen from the accepted Chinese revision-2 contract.  The compressed JSON
# keeps package-isolated tests independent of the intentionally excluded
# GoalTeamsWork process bundle while retaining every non-ASCII assertion byte.
EMBEDDED_ASSERTIONS_ZLIB_B64 = (
    "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"
    "/Z//B07UiAA="
)


def embedded_assertions() -> list[dict[str, Any]]:
    raw = zlib.decompress(base64.b64decode(EMBEDDED_ASSERTIONS_ZLIB_B64))
    records = json.loads(raw.decode("utf-8"))
    if not isinstance(records, list) or len(records) != 52:
        raise AssertionError("embedded V2.34 assertion fixture is corrupt")
    return records


def embedded_contract_text() -> str:
    rows = [
        "| {id} | {assertion} | {required} | {planned_verifier} | {content_state} |".format(
            id=record["id"],
            assertion=record["assertion"],
            required="true" if record["required"] else "false",
            planned_verifier=record["planned_verifier"],
            content_state=record["content_state"],
        )
        for record in embedded_assertions()
    ]
    return "\n".join(
        [
            "---",
            "type: V2.34 Execution Contract",
            "contract_revision: 2",
            "assertion_content_state: frozen",
            "required_assertion_count: 52",
            f"owner_run_id: {CONTRACT_OWNER}",
            f"validator_run_id: {CONTRACT_VALIDATOR}",
            "---",
            "",
            "# V2.34 中文不可变断言合同（package-isolated fixture）",
            "",
            "| ID | 可测试断言 | Required | 计划验证器 | 内容状态 |",
            "| --- | --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )


def process_contract_available() -> bool:
    return (
        os.environ.get("GOAL_TEAMS_V234_FORCE_EMBEDDED_CONTRACT") != "1"
        and ACTUAL_CONTRACT_PATH.is_file()
    )


def actual_contract_text() -> str:
    if not process_contract_available():
        return embedded_contract_text()
    raw = ACTUAL_CONTRACT_PATH.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != ACTUAL_CONTRACT_SHA256:
        raise AssertionError(
            f"frozen contract bytes drifted: {actual_sha} != {ACTUAL_CONTRACT_SHA256}"
        )
    text = raw.decode("utf-8")
    if embedded_assertions()[0]["assertion"] not in text:
        raise AssertionError("process contract does not match embedded Chinese records")
    return text


def identity_registry() -> dict[str, Any]:
    return {
        "runs": {
            CONTRACT_OWNER: {"member_id": "MEMBER-CONTRACT", "role": "owner"},
            CONTRACT_VALIDATOR: {"member_id": "MEMBER-CONTRACT-REVIEW", "role": "validator"},
            ARCH_OWNER: {"member_id": "MEMBER-ARCH", "role": "owner"},
            ENV_OWNER: {"member_id": "MEMBER-ENV", "role": "owner"},
            ENV_PRODUCER: {"member_id": "MEMBER-ENV-CHECK", "role": "producer"},
            ENV_VALIDATOR: {"member_id": "MEMBER-QA", "role": "validator"},
        }
    }


def strict_environment_proof(
    root: Path,
    *,
    evidence_id: str = "EVD-V234-ENV-STRICT",
    task_id: str = "TASK-V234-ENV-PROOF",
    attempt_id: str = "ATT-V234-ENV-PROOF-01",
    artifact_name: str = "environment-report.json",
    artifact_payload: dict[str, Any] | None = None,
    record_bindings: dict[str, Any] | None = None,
    environment_bindings: dict[str, Any] | None = None,
    required_for_done: bool = False,
    acceptance_blocking: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create real files and a V2.3-validated Evidence registry wrapper."""
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.py"
    report = root / artifact_name
    log = root / "environment-check.log"
    source.write_text("ENVIRONMENT = 'current'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "v234-proof@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "V2.34 Proof"], cwd=root, check=True
    )
    subprocess.run(["git", "add", "source.py"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "proof source"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()

    report.write_text(
        json.dumps(
            artifact_payload
            or {
                "record_type": "v234_environment_readiness",
                "architecture_sha256": FIXED_HASH_B,
                "workspace_fingerprint": FIXED_HASH_C,
                "conclusion": "ready",
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    log.write_text("environment check passed\n", encoding="utf-8")

    planned = task_event(
        "EVT-V234-ENV-PROOF-001",
        task_id,
        0,
        "planned",
        attempt_id=attempt_id,
    )
    planned["payload"].update(
        {
            "owner_run_id": ENV_PRODUCER,
            "validator_run_id": ENV_VALIDATOR,
            "owner_member_id": "MEMBER-ENV-CHECK",
            "validator_member_id": "MEMBER-QA",
            "required_for_done": required_for_done,
            "acceptance_blocking": acceptance_blocking,
        }
    )
    planned["actor_run_id"] = ENV_PRODUCER
    running = task_event(
        "EVT-V234-ENV-PROOF-002",
        task_id,
        1,
        "running",
        attempt_id=attempt_id,
    )
    running["actor_run_id"] = ENV_PRODUCER
    review = task_event(
        "EVT-V234-ENV-PROOF-003",
        task_id,
        2,
        "review",
        attempt_id=attempt_id,
    )
    review["actor_run_id"] = ENV_PRODUCER
    check = task_event(
        "EVT-V234-ENV-PROOF-004",
        task_id,
        3,
        "review",
        attempt_id=attempt_id,
        payload={
            "check_state": "passed",
            "evidence_refs": [evidence_id],
            "validation_check_id": "CHECK-V234-ENV-STRICT",
            "validation_run_id": "RUN-CHECK-V234-ENV-STRICT",
        },
    )
    check.update(
        {
            "event_type": "check_executed",
            "actor_run_id": ENV_VALIDATOR,
            "validation_check_id": "CHECK-V234-ENV-STRICT",
            "validation_run_id": "RUN-CHECK-V234-ENV-STRICT",
        }
    )
    accepted = task_event(
        "EVT-V234-ENV-PROOF-005",
        task_id,
        4,
        "accepted",
        attempt_id=attempt_id,
        payload={
            "check_state": "passed",
            "evidence_refs": [evidence_id],
            "validation_check_id": "CHECK-V234-ENV-STRICT",
            "validation_run_id": "RUN-CHECK-V234-ENV-STRICT",
        },
    )
    accepted.update(
        {
            "event_type": "review_completed",
            "actor_run_id": ENV_VALIDATOR,
            "validation_check_id": "CHECK-V234-ENV-STRICT",
            "validation_run_id": "RUN-CHECK-V234-ENV-STRICT",
        }
    )
    events = [planned, running, review, check, accepted]
    event_seconds = (0, 1, 2, 5, 6)
    for event, second in zip(events, event_seconds, strict=True):
        event["timestamp"] = f"2026-07-11T08:00:{second:02d}Z"

    evidence = {
        "schema_version": "goal-teams-v2.3",
        "evidence_id": evidence_id,
        "check_id": "CHECK-V234-ENV-STRICT",
        "run_id": "RUN-CHECK-V234-ENV-STRICT",
        "attempt_id": attempt_id,
        "artifact_ref": report.name,
        "artifact_sha256": sha256_path(report),
        "artifact_size": report.stat().st_size,
        "artifact_mtime_ns": report.stat().st_mtime_ns,
        "producer_run_id": ENV_PRODUCER,
        "validator_run_id": ENV_VALIDATOR,
        "created_at": "2026-07-11T08:00:04Z",
        "trust_level": "local_verified",
        "evidence_kind": "command_execution",
        "current": True,
        "status": "passed",
        "command": {
            "argv": ["python", "-m", "unittest", "tests.v23.test_v234_contract_environment"],
            "cwd": ".",
            "started_at": "2026-07-11T08:00:02Z",
            "ended_at": "2026-07-11T08:00:03Z",
            "exit_code": 0,
            "log_path": log.name,
            "log_sha256": sha256_path(log),
            "log_size": log.stat().st_size,
            "log_mtime_ns": log.stat().st_mtime_ns,
        },
        "environment": {
            "commit": commit,
            "workspace_revision": gt.source_manifest_sha256(root, [source.name]),
            "source_paths": [source.name],
            "platform": "test-platform",
            "python_version": "3.x-test",
            "ledger_revision": 3,
            "ledger_prefix_sha256": gt.ledger_prefix_sha256(events, 3),
            "workspace_fingerprint": FIXED_HASH_C,
            "architecture_sha256": FIXED_HASH_B,
            "environment_report_sha256": sha256_path(report),
        },
    }
    evidence.update(record_bindings or {})
    evidence["environment"].update(environment_bindings or {})
    evidence.setdefault("ledger_revision", evidence["environment"]["ledger_revision"])
    evidence.setdefault(
        "ledger_prefix_sha256", evidence["environment"]["ledger_prefix_sha256"]
    )
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
    execution_path = root / f"execution-{evidence_id}.json"
    execution_path.write_text(
        json.dumps(execution, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    command.update(
        {
            "execution_record_path": execution_path.name,
            "execution_record_sha256": sha256_path(execution_path),
            "execution_record_size": execution_path.stat().st_size,
        }
    )
    binding_digest = gt.evidence_replay_binding_digest(evidence)
    argv = gt.artifact_verifier_argv(
        evidence["artifact_ref"], evidence["artifact_sha256"], binding_digest
    )
    replay = subprocess.run(
        argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if replay.returncode != 0 or replay.stderr:
        raise AssertionError(
            f"strict Environment Evidence replay failed: {replay.returncode} {replay.stderr!r}"
        )
    integrity_path = root / f"integrity-{evidence_id}.log"
    integrity_path.write_bytes(replay.stdout)
    evidence["integrity_replay"] = {
        "argv": argv,
        "cwd": ".",
        "started_at": command["ended_at"],
        "ended_at": evidence["created_at"],
        "exit_code": replay.returncode,
        "log_path": integrity_path.name,
        "log_sha256": sha256_path(integrity_path),
        "log_size": integrity_path.stat().st_size,
        "log_mtime_ns": integrity_path.stat().st_mtime_ns,
    }

    registry, errors = gt.build_evidence_registry(
        [evidence], root, ledger_events=events, source_root=root
    )
    if errors or not registry[evidence["evidence_id"]]["valid_for_acceptance"]:
        raise AssertionError(f"strict V2.3 Evidence fixture invalid: {errors} {registry}")
    strict_record = copy.deepcopy(evidence)
    strict_record.update(registry[evidence["evidence_id"]])
    strict_record["environment"] = copy.deepcopy(evidence["environment"])
    strict_record["current"] = True
    strict_record["status"] = "passed"
    records = {evidence["evidence_id"]: strict_record}
    registry_path = root / "evidence.jsonl"
    registry_path.write_text(
        json.dumps(
            evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        + "\n",
        encoding="utf-8",
    )
    projected_tasks, projection_valid = gt._ledger_task_projection(events)
    if not projection_valid:
        raise AssertionError("strict proof ledger projection is invalid")
    checkpoint = {
        "schema_version": "goal-teams-v2.3",
        "schema_source_hash": gt.schema_source_hash(),
        "ledger_revision": len(events),
        "revision": len(events),
        "conflicts": [],
        "ledger_owner_run_id": events[0]["ledger_owner_run_id"],
        "last_event_id": events[-1]["event_id"],
        "seen_events": [event["event_id"] for event in events],
        "tasks": projected_tasks,
        "event_digests": {
            event["event_id"]: canonical_hash(
                {key: value for key, value in event.items() if key != "event_digest"}
            )
            for event in events
        },
    }
    wrapper = {
        "schema_version": "goal-teams-v2.34-validated-evidence-registry-v1",
        "evidence_root": str(root),
        "source_root": str(root),
        "registry_source_path": str(registry_path),
        "registry_source_sha256": sha256_path(registry_path),
        "records": records,
        "valid_evidence_ids": sorted(records),
        "records_sha256": canonical_hash(records),
        "ledger_revision": len(events),
        "ledger_prefix_sha256": gt.ledger_prefix_sha256(events, len(events)),
        "checkpoint_sha256": canonical_hash(checkpoint),
        "validation": {
            evidence["evidence_id"]: {
                "structurally_valid": True,
                "valid_for_acceptance": True,
                "current": True,
            }
        },
    }
    return events, checkpoint, wrapper, evidence


def contract_gate_fixture() -> tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    contract = actual_contract_text()
    contract_sha = hashlib.sha256(contract.encode("utf-8")).hexdigest()
    set_sha = ACTUAL_ASSERTION_SET_SHA256
    review_core = {
        "record_type": "v234_contract_spec_review",
        "decision": "passed",
        "contract_revision": 2,
        "contract_sha256": contract_sha,
        "assertion_set_sha256": set_sha,
        "owner_run_id": CONTRACT_OWNER,
        "validator_run_id": CONTRACT_VALIDATOR,
        "review_ref": "reviews/contract-review.md",
        "reviewed_ledger_revision": 3,
        "reviewed_ledger_prefix_sha256": FIXED_HASH_A,
        "assertions": [
            {"assertion_id": f"ASSERT-V234-{number:03d}", "decision": "accepted"}
            for number in range(1, 53)
        ],
    }
    review = {**review_core, "record_sha256": canonical_hash(review_core)}
    extension = {
        "preimplementation_gate_state": "passed",
        "contract_revision": 2,
        "contract_sha256": contract_sha,
        "assertion_set_sha256": set_sha,
        "external_review_ref": review["review_ref"],
        "external_review_sha256": review["record_sha256"],
        "reviewed_ledger_revision": 3,
        "reviewed_ledger_prefix_sha256": FIXED_HASH_A,
        "decision": "passed",
        "decided_at": "2026-07-11T08:00:00Z",
    }
    event = {
        "schema_version": "goal-teams-v2.3",
        "event_id": "EVT-V234-CONTRACT-GATE",
        "event_type": "check_executed",
        "task_id": "TASK-V234-CONTRACT",
        "attempt_id": "ATT-V234-CONTRACT-01",
        "actor_run_id": CONTRACT_VALIDATOR,
        "ledger_owner_run_id": "RUN-LEDGER-OWNER-V234",
        "base_revision": 3,
        "timestamp": "2026-07-11T08:01:00Z",
        "payload": {
            "task_state": "review",
            "check_state": "running",
            "v234_contract_gate": extension,
        },
    }
    return contract, identity_registry(), [event], review


def accepted_architecture() -> dict[str, Any]:
    return {
        "task_id": "TASK-V234-ARCH",
        "state": "accepted",
        "artifact_ref": "spec/architecture-design.md",
        "artifact_sha256": FIXED_HASH_B,
        "accepted_event_id": "EVT-V234-ARCH-ACCEPTED",
        "accepted_ledger_revision": 8,
        "owner_run_id": ARCH_OWNER,
        "validator_run_id": ARCH_VALIDATOR,
        "review_state": "passed",
    }


def readiness_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_type": "v234_environment_readiness",
        "architecture_ref": "spec/architecture-design.md",
        "architecture_sha256": FIXED_HASH_B,
        "architecture_accepted_event_id": "EVT-V234-ARCH-ACCEPTED",
        "workspace_fingerprint": FIXED_HASH_C,
        "tool_versions": {"python": "3.12.0", "git": "2.50.0"},
        "dependency_checks": [{"id": "DEP-1", "state": "passed", "log_ref": "env.log"}],
        "permission_checks": [{"id": "PERM-1", "state": "passed", "log_ref": "env.log"}],
        "service_checks": [{"id": "SVC-1", "state": "not_required", "log_ref": "env.log"}],
        "gaps": [],
        "remediation": [],
        "execution_logs": [{"ref": "env.log", "sha256": FIXED_HASH_A, "exit_code": 0}],
        "conclusion": "ready",
        "owner_run_id": ENV_OWNER,
        "validator_run_id": ENV_VALIDATOR,
        "checked_ledger_revision": 9,
        "evidence_refs": ["EVD-V234-ENV-001"],
    }
    record.update(overrides)
    return record


def implementation_bundle() -> dict[str, Any]:
    return {
        "bundle_revision": 7,
        "bundle_digest": FIXED_HASH_A,
        "implementation_owner_run_id": OWNER_RUN,
        "contract": {
            "contract_revision": 2,
            "contract_sha256": FIXED_HASH_A,
            "assertion_set_sha256": FIXED_HASH_B,
            "external_review_sha256": FIXED_HASH_C,
            "preimplementation_gate_state": "passed",
        },
        "development_environment": {
            "architecture": accepted_architecture(),
            "check": {
                "state": "ready",
                "report_sha256": "d" * 64,
                "based_on_architecture_sha256": FIXED_HASH_B,
                "workspace_fingerprint": FIXED_HASH_C,
                "check_id": "CHECK-V234-ENV-001",
                "run_id": "RUN-CHECK-V234-ENV-001",
                "evidence_refs": ["EVD-V234-ENV-001"],
                "validator_run_id": ENV_VALIDATOR,
                "checked_ledger_revision": 9,
            },
        },
    }


class V234ContractTests(unittest.TestCase):
    def test_contract_assertion_schema_count_and_frozen_state(self) -> None:
        """ASSERT-V234-001"""
        contract = actual_contract_text()
        self.assertIn("可测试断言", contract)
        fixture_assertions = embedded_assertions()
        self.assertEqual(len(fixture_assertions), 52)
        self.assertEqual(
            gt.canonical_json_sha256(fixture_assertions),
            ACTUAL_ASSERTION_SET_SHA256,
        )
        if process_contract_available():
            self.assertEqual(
                hashlib.sha256(contract.encode("utf-8")).hexdigest(),
                ACTUAL_CONTRACT_SHA256,
            )
        v234 = require_v234(self)
        parsed = v234.parse_contract_document(contract)
        self.assertTrue(parsed["ok"], parsed)
        assertions = parsed["assertions"]
        self.assertEqual(len(assertions), 52)
        self.assertEqual(
            [item["id"] for item in assertions],
            [f"ASSERT-V234-{number:03d}" for number in range(1, 53)],
        )
        for assertion in assertions:
            self.assertTrue(assertion["assertion"])
            self.assertIs(assertion["required"], True)
            self.assertTrue(assertion["planned_verifier"])
            self.assertEqual(assertion["content_state"], "frozen")
        self.assertTrue(
            any(
                any("\u4e00" <= character <= "\u9fff" for character in item["assertion"])
                for item in assertions
            ),
            "the canonicalization fixture must contain real non-ASCII assertion text",
        )
        self.assertEqual(
            gt.canonical_json_sha256(assertions), ACTUAL_ASSERTION_SET_SHA256
        )
        self.assertEqual(canonical_hash(assertions), ACTUAL_ASSERTION_SET_SHA256)
        wrong_non_ascii_digest = hashlib.sha256(
            json.dumps(
                assertions,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(wrong_non_ascii_digest, ACTUAL_ASSERTION_SET_SHA256)
        self.assertEqual(parsed["assertion_set_sha256"], ACTUAL_ASSERTION_SET_SHA256)
        self.assertEqual(
            gt.canonical_json_sha256(embedded_assertions()),
            ACTUAL_ASSERTION_SET_SHA256,
        )

    def test_contract_immutable_content_has_no_derived_state(self) -> None:
        """ASSERT-V234-002"""
        v234 = require_v234(self)
        contract = actual_contract_text()
        self.assertTrue(v234.validate_contract_document(contract)["ok"])
        forbidden = (
            "reviewer_decision: passed\n"
            "gate_state: open\n"
            "task_state: accepted\n"
            f"contract_sha256: {FIXED_HASH_A}\n"
        )
        mutated = contract.replace("---\n\n#", f"{forbidden}---\n\n#", 1)
        result = v234.validate_contract_document(mutated)
        assert_error_code(self, result, "E_V234_CONTRACT_DERIVED_STATE")

    def test_preimplementation_check_event_schema_and_identity(self) -> None:
        """ASSERT-V234-003"""
        v234 = require_v234(self)
        contract, identities, events, review = contract_gate_fixture()
        valid = v234.evaluate_contract_gate(contract, identities, events, review)
        self.assertTrue(valid["ok"], valid)
        self.assertEqual(valid["task_state"], "review")
        self.assertNotEqual(valid["check_state"], "passed")
        self.assertEqual(valid["preimplementation_gate_state"], "passed")
        self.assertFalse(valid["accepted"])
        self_review = copy.deepcopy(events)
        self_review[0]["actor_run_id"] = CONTRACT_OWNER
        result = v234.evaluate_contract_gate(contract, identities, self_review, review)
        assert_error_code(self, result, "E_V234_CONTRACT_REVIEW_IDENTITY")

    def test_contract_byte_mutation_requires_new_revision(self) -> None:
        """ASSERT-V234-004"""
        contract, identities, events, review = contract_gate_fixture()
        assertion_052 = next(
            record
            for record in embedded_assertions()
            if record["id"] == "ASSERT-V234-052"
        )
        frozen_row = (
            f"| {assertion_052['id']} | {assertion_052['assertion']} | true | "
            f"{assertion_052['planned_verifier']} | {assertion_052['content_state']} |"
        )
        changed_row = frozen_row.replace(
            assertion_052["assertion"],
            assertion_052["assertion"] + "（mutation fixture）",
            1,
        )
        self.assertIn(frozen_row, contract)
        self.assertNotEqual(frozen_row, changed_row)
        self.assertEqual(contract.count(frozen_row), 1)
        changed = contract.replace(frozen_row, changed_row, 1)
        self.assertNotEqual(changed, contract)
        self.assertNotEqual(
            hashlib.sha256(changed.encode("utf-8")).hexdigest(),
            hashlib.sha256(contract.encode("utf-8")).hexdigest(),
        )
        v234 = require_v234(self)
        result = v234.validate_contract_document(
            changed,
            previous_contract_text=contract,
            external_gate=v234.evaluate_contract_gate(contract, identities, events, review),
        )
        assert_error_code(self, result, "E_V234_CONTRACT_REVISION_REQUIRED")

    def test_invalid_preimplementation_gate_has_zero_mutations(self) -> None:
        """ASSERT-V234-005"""
        v234 = require_v234(self)
        contract, identities, events, review = contract_gate_fixture()
        invalid_events = [[], events, copy.deepcopy(events), copy.deepcopy(events)]
        invalid_events[1][0]["payload"]["v234_contract_gate"]["preimplementation_gate_state"] = "not_started"
        invalid_events[2][0]["payload"]["v234_contract_gate"]["contract_sha256"] = "f" * 64
        invalid_events[3][0]["payload"]["v234_contract_gate"]["reviewed_ledger_prefix_sha256"] = "e" * 64
        for index, candidate_events in enumerate(invalid_events):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as directory:
                sentinel = Path(directory) / "implementation.txt"
                gate = v234.evaluate_contract_gate(contract, identities, candidate_events, review)
                called = []

                def mutation() -> None:
                    called.append(True)
                    sentinel.write_text("mutated", encoding="utf-8")

                result = v234.run_guarded_implementation_action(gate, mutation)
                self.assertFalse(result["ok"], result)
                self.assertEqual(called, [])
                self.assertFalse(sentinel.exists())

    def test_two_stage_contract_acceptance(self) -> None:
        """ASSERT-V234-006"""
        v234 = require_v234(self)
        contract, identities, events, review = contract_gate_fixture()
        bootstrap = v234.evaluate_contract_gate(contract, identities, events, review)
        self.assertTrue(bootstrap["ok"])
        self.assertFalse(bootstrap["accepted"])
        incomplete = v234.evaluate_final_contract_acceptance(
            bootstrap,
            strict_evidence=None,
            check_event=None,
            review_event=None,
        )
        self.assertFalse(incomplete["accepted"])
        complete = v234.evaluate_final_contract_acceptance(
            bootstrap,
            strict_evidence={"trust_level": "local_verified", "current": True, "evidence_id": "EVD-CONTRACT"},
            check_event={"event_type": "check_executed", "check_state": "passed", "evidence_refs": ["EVD-CONTRACT"], "actor_run_id": CONTRACT_VALIDATOR},
            review_event={"event_type": "review_completed", "task_state": "accepted", "actor_run_id": CONTRACT_VALIDATOR},
        )
        self.assertTrue(complete["accepted"], complete)


class V234EnvironmentTests(unittest.TestCase):
    def test_environment_projection_replaces_superseded_architecture_task(self) -> None:
        marker = {
            "development_environment": {
                "architecture": {"task_id": "TASK-OLD", "artifact_sha256": FIXED_HASH_B},
                "check": {"state": "ready", "report_sha256": FIXED_HASH_A},
            }
        }
        architecture = {
            "task_id": "TASK-V234R3-ARCH-ULTIMATE",
            "artifact_sha256": FIXED_HASH_B,
        }
        check = {
            "state": "ready",
            "report_sha256": FIXED_HASH_C,
            "based_on_architecture_sha256": FIXED_HASH_B,
        }
        gt._apply_v234_environment_projection(marker, architecture, check)
        self.assertEqual(
            marker["development_environment"]["architecture"]["task_id"],
            "TASK-V234R3-ARCH-ULTIMATE",
        )
        self.assertEqual(marker["development_environment"]["check"], check)

    def test_cli_registry_wrapper_preserves_raw_evidence_transport_fields(self) -> None:
        """Regression: normalized V2.3 entries must not erase V2.34 proof fields."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_path = root / "evidence.jsonl"
            raw = {
                "schema_version": "goal-teams-v2.3",
                "evidence_id": "EVD-WRAPPER-001",
                "artifact_ref": "artifact.txt",
                "artifact_sha256": FIXED_HASH_A,
                "artifact_size": 7,
                "artifact_mtime_ns": 123,
                "trust_level": "local_verified",
                "environment": {"workspace_fingerprint": FIXED_HASH_B},
            }
            evidence_path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            event = {
                "schema_version": "goal-teams-v2.3",
                "event_id": "EVT-WRAPPER-001",
                "event_type": "task_patch",
                "task_id": "TASK-WRAPPER",
                "attempt_id": "ATT-WRAPPER-01",
                "actor_run_id": "RUN-WRAPPER",
                "ledger_owner_run_id": "RUN-LEDGER",
                "base_revision": 0,
                "timestamp": "2026-07-11T12:00:00Z",
                "payload": {"task_state": "planned"},
            }
            checkpoint = {"ledger_revision": 1, "_source_sha256": FIXED_HASH_C}
            normalized = {
                raw["evidence_id"]: {
                    "evidence_id": raw["evidence_id"],
                    "trust_level": "local_verified",
                    "structurally_valid": True,
                    "valid_for_acceptance": True,
                }
            }
            wrapper = gt._v234_validated_registry_wrapper(
                evidence_path, root, normalized, [event], checkpoint
            )
            record = wrapper["records"][raw["evidence_id"]]
            self.assertEqual(record["artifact_size"], 7)
            self.assertEqual(record["artifact_mtime_ns"], 123)
            self.assertEqual(record["environment"], raw["environment"])
            self.assertTrue(record["structurally_valid"])
            self.assertTrue(record["valid_for_acceptance"])

    def test_okf_environment_projection_uses_explicit_run_architecture_task(self) -> None:
        """Regression: task-local Run IDs must not be replaced by TASK-V234-ARCH."""
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "environment.md"
            report.write_text(
                "---\n"
                "type: Development Environment Readiness\n"
                "readiness_state: ready\n"
                "goal_teams_version: V2.34\n"
                "architecture_task_id: TASK-V234R2-ARCH-CURRENT\n"
                f"architecture_sha256: {FIXED_HASH_B}\n"
                f"workspace_fingerprint: {FIXED_HASH_C}\n"
                "owner_agent_run_id: RUN-ENV-OWNER\n"
                "validator_agent_run_id: RUN-ENV-VALIDATOR\n"
                "checked_ledger_revision: 12\n"
                "---\n",
                encoding="utf-8",
            )
            checkpoint = {
                "tasks": {
                    "TASK-V234R2-ARCH-CURRENT": {
                        "task_state": "accepted",
                        "check_state": "passed",
                        "artifact_refs": ["spec/architecture-design.md"],
                        "artifact_sha256": {"spec/architecture-design.md": FIXED_HASH_B},
                        "last_event_id": "EVT-ARCH-CURRENT-ACCEPTED",
                        "revision": 5,
                        "owner_run_id": ARCH_OWNER,
                        "validator_run_id": ARCH_VALIDATOR,
                    }
                }
            }
            record, architecture = gt._environment_record_from_okf(
                report, checkpoint, ["EVD-ENV-PROJECTION"]
            )
            self.assertEqual(architecture["task_id"], "TASK-V234R2-ARCH-CURRENT")
            self.assertEqual(architecture["state"], "accepted")
            self.assertEqual(record["architecture_sha256"], FIXED_HASH_B)

            report.write_text(
                report.read_text(encoding="utf-8").replace(
                    "TASK-V234R2-ARCH-CURRENT", "TASK-V234R2-MISSING"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(gt.ContractError):
                gt._environment_record_from_okf(
                    report, checkpoint, ["EVD-ENV-PROJECTION"]
                )

    def test_environment_check_requires_current_architecture_review(self) -> None:
        """ASSERT-V234-018"""
        v234 = require_v234(self)
        for mutation in ("draft", "self", "stale"):
            architecture = accepted_architecture()
            if mutation == "draft":
                architecture["state"] = "review"
            elif mutation == "self":
                architecture["validator_run_id"] = architecture["owner_run_id"]
            else:
                architecture["artifact_sha256"] = "e" * 64
            result = v234.validate_environment_readiness(
                readiness_record(), architecture, identity_registry()
            )
            with self.subTest(mutation=mutation):
                assert_error_code(self, result, "E_V234_ARCHITECTURE_GATE")

    def test_environment_readiness_schema(self) -> None:
        """ASSERT-V234-019"""
        v234 = require_v234(self)
        result = v234.validate_environment_readiness(
            readiness_record(), accepted_architecture(), identity_registry()
        )
        self.assertTrue(result["ok"], result)
        for field in (
            "architecture_sha256", "workspace_fingerprint", "tool_versions",
            "dependency_checks", "permission_checks", "service_checks", "gaps",
            "remediation", "execution_logs", "conclusion", "validator_run_id",
        ):
            bad = readiness_record()
            bad.pop(field)
            with self.subTest(missing=field):
                self.assertFalse(
                    v234.validate_environment_readiness(
                        bad, accepted_architecture(), identity_registry()
                    )["ok"]
                )

    def test_environment_remediation_respects_authority(self) -> None:
        """ASSERT-V234-020"""
        v234 = require_v234(self)
        unsafe_kinds = ("system_install", "credential_write", "external_write", "destructive_config")
        for kind in unsafe_kinds:
            record = readiness_record(
                remediation=[{"kind": kind, "authority": "missing", "state": "proposed"}],
                conclusion="ready",
            )
            result = v234.validate_environment_readiness(
                record, accepted_architecture(), identity_registry()
            )
            with self.subTest(kind=kind):
                assert_error_code(self, result, "E_V234_REMEDIATION_AUTHORIZATION")
                self.assertNotEqual(result.get("conclusion"), "ready")

    def test_implementation_gate_rejects_environment_drift(self) -> None:
        """ASSERT-V234-021"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            proof_root = Path(directory) / "strict-proof"
            events, checkpoint, evidence, raw = strict_environment_proof(proof_root)
            bundle = implementation_bundle()
            bundle["development_environment"]["check"].update(
                {
                    "report_sha256": raw["artifact_sha256"],
                    "evidence_refs": [raw["evidence_id"]],
                    "checked_ledger_revision": checkpoint["ledger_revision"],
                }
            )
            valid = v234.evaluate_implementation_gate(
                bundle,
                "TASK-V234-IMPLEMENT",
                events,
                evidence,
                checkpoint=checkpoint,
            )
            self.assertTrue(valid["ok"], valid)

            drifted = copy.deepcopy(bundle)
            drifted["development_environment"]["check"]["workspace_fingerprint"] = "0" * 64
            result = v234.evaluate_implementation_gate(
                drifted,
                "TASK-V234-IMPLEMENT",
                events,
                evidence,
                checkpoint=checkpoint,
            )
            assert_error_code(self, result, "E_V234_ENVIRONMENT_STALE")

            fake_record = {
                "evidence_id": raw["evidence_id"],
                "trust_level": "local_verified",
                "current": True,
                "status": "passed",
                "artifact_sha256": raw["artifact_sha256"],
                "producer_run_id": ENV_PRODUCER,
                "validator_run_id": ENV_VALIDATOR,
                "environment": copy.deepcopy(raw["environment"]),
            }
            fake_registry = copy.deepcopy(evidence)
            fake_registry["records"] = {raw["evidence_id"]: fake_record}
            fake_registry["records_sha256"] = canonical_hash(fake_registry["records"])
            forged = v234.evaluate_implementation_gate(
                bundle,
                "TASK-V234-IMPLEMENT",
                events,
                fake_registry,
                checkpoint=checkpoint,
            )
            self.assertFalse(forged["ok"], forged)
            self.assertIn(
                forged["error_code"],
                {"E_V234_EVIDENCE_REGISTRY", "E_V234_ENVIRONMENT_STALE"},
                forged,
            )

            stale_registry = copy.deepcopy(evidence)
            stale_registry["records"][raw["evidence_id"]]["current"] = False
            stale_registry["records_sha256"] = canonical_hash(stale_registry["records"])
            stale = v234.evaluate_implementation_gate(
                bundle,
                "TASK-V234-IMPLEMENT",
                events,
                stale_registry,
                checkpoint=checkpoint,
            )
            self.assertFalse(stale["ok"], stale)

            report_path = proof_root / raw["artifact_ref"]
            report_path.write_text('{"tampered":true}\n', encoding="utf-8")
            tampered = v234.evaluate_implementation_gate(
                bundle,
                "TASK-V234-IMPLEMENT",
                events,
                evidence,
                checkpoint=checkpoint,
            )
            self.assertFalse(tampered["ok"], tampered)

            bad_checkpoint = copy.deepcopy(checkpoint)
            bad_checkpoint["last_event_id"] = "EVT-V234-FORGED"
            mismatched = v234.evaluate_implementation_gate(
                bundle,
                "TASK-V234-IMPLEMENT",
                events,
                evidence,
                checkpoint=bad_checkpoint,
            )
            self.assertFalse(mismatched["ok"], mismatched)


if __name__ == "__main__":
    unittest.main()
