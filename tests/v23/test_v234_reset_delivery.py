"""V2.34 iteration-nine quarantine and iteration-eleven delivery TDD tests."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.v23.common import gt, task_event
from tests.v23.test_v234_contract_environment import strict_environment_proof
from tests.v23.test_v234_scoring_diagnostics import score_record
from tests.v23.test_v234_state_loop import (
    FIXED_HASH_A,
    FIXED_HASH_B,
    OWNER_RUN,
    ROOT,
    VALIDATOR_RUN,
    assert_error_code,
    canonical_hash,
    initialize_bundle,
    marker,
    require_v234,
    state_proof,
    synthetic_contract_text,
)


RESET_AUTHORITY_RUN = "RUN-USER-AUTHORITY-V234"


def tree_digest(root: Path) -> str:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
        elif path.is_dir():
            entries.append({"path": relative, "kind": "directory"})
        else:
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                }
            )
    return canonical_hash(entries)


def reset_bundle() -> dict[str, Any]:
    return {
        "schema_version": "goal-teams-v2.34-state-v1",
        "bundle_revision": 40,
        "bundle_digest": FIXED_HASH_A,
        "loop": {
            "iteration": 9,
            "attempt": 1,
            "attempt_id": "ATT-V234-RESET-01",
            "phase": "reason",
            "loop_decision": "continue",
            "run_outcome": "partial",
        },
        "contract": {
            "contract_revision": 2,
            "contract_sha256": FIXED_HASH_B,
            "preimplementation_gate_state": "passed",
        },
        "ledger": {
            "revision": 40,
            "prefix_sha256": "9" * 64,
        },
        "reset": {
            "state": "due",
            "completed_iteration": None,
            "task_id": "TASK-V234-RESET",
        },
    }


def completed_reset_bundle() -> dict[str, Any]:
    bundle = reset_bundle()
    bundle["reset"] = {
        "state": "quarantined",
        "completed_iteration": 9,
        "task_id": "TASK-V234-RESET",
        "evidence_id": "EVD-V234-RESET-001",
        "receipt_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "reset_event_id": "EVT-V234-RESET-APPLIED",
        "attempt_id": "ATT-V234-RESET-01",
        "contract_revision": 2,
        "contract_sha256": FIXED_HASH_B,
        "ledger_revision": 40,
        "ledger_prefix_sha256": "9" * 64,
    }
    return bundle


def reset_evidence(**overrides: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "evidence_id": "EVD-V234-RESET-001",
        "task_id": "TASK-V234-RESET",
        "trust_level": "local_verified",
        "current": True,
        "bundle_revision": 40,
        "bundle_digest": FIXED_HASH_A,
        "attempt_id": "ATT-V234-RESET-01",
        "contract_revision": 2,
        "contract_sha256": FIXED_HASH_B,
        "reset_event_id": "EVT-V234-RESET-APPLIED",
        "receipt_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "ledger_revision": 40,
        "ledger_prefix_sha256": "9" * 64,
        "producer_run_id": "RUN-RESET-RUNNER-V234-01",
        "validator_run_id": "RUN-QA-V234-01",
    }
    evidence.update(overrides)
    return evidence


def strict_reset_proof(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest = {
        "reset_event_id": "EVT-V234-RESET-APPLIED",
        "candidate_id": "candidate-v234",
        "before_tree_sha256": "7" * 64,
        "actor_run_id": "RUN-RESET-RUNNER-V234-01",
        "contract_revision": 2,
        "contract_sha256": FIXED_HASH_B,
    }
    manifest_bytes = (
        json.dumps(
            manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    receipt = {
        "record_type": "v234_reset_receipt",
        "reset_event_id": "EVT-V234-RESET-APPLIED",
        "manifest_ref": "reset-manifest.json",
        "manifest_sha256": manifest_sha,
        "bundle_revision": 40,
        "bundle_digest": FIXED_HASH_A,
    }
    receipt_bytes = (
        json.dumps(
            receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    record_bindings = {
        "task_id": "TASK-V234-RESET",
        "bundle_revision": 40,
        "bundle_digest": FIXED_HASH_A,
        "attempt_id": "ATT-V234-RESET-01",
        "contract_revision": 2,
        "contract_sha256": FIXED_HASH_B,
        "reset_event_id": "EVT-V234-RESET-APPLIED",
        "receipt_sha256": receipt_sha,
        "manifest_ref": "reset-manifest.json",
        "manifest_sha256": manifest_sha,
        # The reset action can precede the independent Evidence execution.
        # These lineage fields intentionally differ from the canonical
        # Evidence ledger_revision/prefix populated by strict_environment_proof.
        "reset_ledger_revision": 2,
        "reset_ledger_prefix_sha256": "8" * 64,
        "producer_run_id": "RUN-RESET-RUNNER-V234-01",
        "validator_run_id": "RUN-QA-V234-01",
    }
    events, checkpoint, wrapper, raw = strict_environment_proof(
        root,
        evidence_id="EVD-V234-RESET-001",
        task_id="TASK-V234-RESET",
        attempt_id="ATT-V234-RESET-01",
        artifact_name="reset-receipt.json",
        artifact_payload=receipt,
        record_bindings=record_bindings,
        required_for_done=True,
        acceptance_blocking=True,
    )
    (root / "reset-manifest.json").write_bytes(manifest_bytes)
    record = wrapper["records"][raw["evidence_id"]]
    bundle = completed_reset_bundle()
    bundle["reset"].update(
        {
            "receipt_sha256": receipt_sha,
            "manifest_sha256": manifest_sha,
            "ledger_revision": record["reset_ledger_revision"],
            "ledger_prefix_sha256": record["reset_ledger_prefix_sha256"],
        }
    )
    return bundle, wrapper, events, checkpoint


def create_candidate(repo_root: Path, candidate_id: str = "candidate-v234") -> Path:
    candidate = repo_root / ".goalteams-candidates" / candidate_id
    candidate.mkdir(parents=True)
    (candidate / "app.py").write_text("print('candidate')\n", encoding="utf-8")
    (candidate / "README.md").write_text("candidate\n", encoding="utf-8")
    return candidate


def reset_authorization(
    repo_root: Path, candidate: Path, *, task_id: str | None = None,
) -> dict[str, Any]:
    core = {
        "reset_iteration": 9,
        "disposable_candidate_root": ".goalteams-candidates",
        "candidate_id": candidate.name,
        "candidate_path": f".goalteams-candidates/{candidate.name}",
        "expected_realpath": str(candidate.resolve()),
        "before_tree_sha256": tree_digest(candidate),
        "operation": "quarantine",
        "authorization_id": "AUTH-V234-RESET-001",
        "reset_id": "RESET-V234-001",
        "authorized_by_run_id": RESET_AUTHORITY_RUN,
        "authorization_event_id": "EVT-V234-RESET-AUTHORIZATION",
        "authorized_at": "2026-07-11T08:00:00Z",
        "contract_revision": 2,
        "contract_sha256": FIXED_HASH_B,
        "manifest_paths": ["README.md", "app.py"],
        "ownership_verified": True,
        "permission_verified": True,
    }
    if task_id is not None:
        core["task_id"] = task_id
    refresh_authorization_scope(core)
    return core


def refresh_authorization_scope(authorization: dict[str, Any]) -> None:
    scope = {
        "candidate_root": authorization["disposable_candidate_root"],
        "candidate_id": authorization["candidate_id"],
        "candidate_path": authorization["candidate_path"],
        "operation": authorization["operation"],
        "contract_revision": authorization["contract_revision"],
    }
    if authorization.get("task_id") is not None:
        scope["task_id"] = authorization["task_id"]
    authorization["authorized_scope_digest"] = canonical_hash(scope)
    refresh_authorization_record(authorization)


def refresh_authorization_record(authorization: dict[str, Any]) -> None:
    authorization["record_sha256"] = canonical_hash(
        {key: value for key, value in authorization.items() if key != "record_sha256"}
    )


def reset_security_context(
    authorization: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    identities = {
        "runs": {
            RESET_AUTHORITY_RUN: {
                "member_id": "MEMBER-REPOSITORY-OWNER-V234",
                "role": "repository_owner",
            },
            OWNER_RUN: {"member_id": "MEMBER-RUNTIME-V234", "role": "implementation"},
            "RUN-RESET-RUNNER-V234-01": {
                "member_id": "MEMBER-RESET-RUNNER-V234",
                "role": "producer",
            },
            "RUN-QA-V234-01": {"member_id": "MEMBER-QA-V234", "role": "validator"},
        }
    }
    if authorization is None:
        return identities, []
    event = {
        "schema_version": "goal-teams-v2.3",
        "event_id": authorization["authorization_event_id"],
        "event_type": "artifact_created",
        "task_id": authorization.get("task_id", "TASK-V234-RESET"),
        "attempt_id": "ATT-V234-RESET-01",
        "actor_run_id": authorization["authorized_by_run_id"],
        "ledger_owner_run_id": "RUN-V234-LEDGER-OWNER",
        "base_revision": 39,
        "timestamp": "2026-07-11T08:00:00Z",
        "payload": {
            "artifact_refs": ["reset-authorization.json"],
            "v234_reset_authorization": {
                "authorization_id": authorization["authorization_id"],
                "authorization_record_sha256": authorization["record_sha256"],
                "authorized_by_run_id": authorization["authorized_by_run_id"],
                "contract_revision": authorization["contract_revision"],
                "contract_sha256": authorization["contract_sha256"],
                "operation": "quarantine",
            },
        },
    }
    return identities, [event]


def initialize_reset_state(
    test: unittest.TestCase, directory: str, *, task_id: str = "TASK-V234-RESET",
) -> tuple[
    Any,
    Path,
    Path,
    dict[str, Any],
    Path,
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
]:
    v234 = require_v234(test)
    repo_root = Path(directory)
    state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
    state_root.mkdir(parents=True)
    contract_path = state_root / "contract.md"
    contract_path.write_text(synthetic_contract_text(), encoding="utf-8")
    candidate = create_candidate(repo_root)
    authorization = reset_authorization(
        repo_root, candidate,
        task_id=task_id if task_id != "TASK-V234-RESET" else None,
    )
    authorization["contract_sha256"] = hashlib.sha256(
        contract_path.read_bytes()
    ).hexdigest()
    refresh_authorization_scope(authorization)
    identities, authorization_events = reset_security_context(authorization)

    planned = task_event(
        "EVT-V234-RESET-LEDGER-001",
        task_id,
        0,
        "planned",
        attempt_id="ATT-V234-RESET-01",
    )
    planned["payload"].update(
        {
            "owner_member_id": "MEMBER-REPOSITORY-OWNER-V234",
            "owner_run_id": RESET_AUTHORITY_RUN,
            "validator_member_id": "MEMBER-QA-V234",
            "validator_run_id": "RUN-QA-V234-01",
        }
    )
    planned["actor_run_id"] = RESET_AUTHORITY_RUN
    running = task_event(
        "EVT-V234-RESET-LEDGER-002",
        task_id,
        1,
        "running",
        attempt_id="ATT-V234-RESET-01",
    )
    running["actor_run_id"] = RESET_AUTHORITY_RUN
    authorization_event = authorization_events[0]
    authorization_event["base_revision"] = 2
    authorization_event["ledger_owner_run_id"] = planned["ledger_owner_run_id"]
    events = [planned, running, authorization_event]
    for index, event in enumerate(events):
        event["timestamp"] = f"2026-07-11T08:00:{index:02d}Z"
    checkpoint = gt.reduce_events(
        events, valid_evidence_ids=set(), evidence_registry={}
    )
    test.assertEqual(checkpoint["conflicts"], [])
    checkpoint_bytes = json.dumps(
        checkpoint,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    initialized = v234.initialize_state_bundle(
        state_root,
        repo_root=repo_root,
        loop_id="LOOP-V234-RESET",
        contract_path=contract_path,
        ledger_binding={
            "revision": len(events),
            "prefix_sha256": gt.ledger_prefix_sha256(events, len(events)),
            "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
            "last_event_id": events[-1]["event_id"],
        },
        actor_run_id=OWNER_RUN,
        initial_loop={"iteration": 9, "attempt": 1, "phase": "reason"},
        ledger_events=events,
        checkpoint_bytes=checkpoint_bytes,
    )
    test.assertTrue(initialized["ok"], initialized)
    bundle = marker(state_root)
    return (
        v234,
        repo_root,
        state_root,
        bundle,
        candidate,
        authorization,
        identities,
        events,
        checkpoint,
    )


def filesystem_snapshot(root: Path) -> dict[str, tuple[Any, ...]]:
    snapshot: dict[str, tuple[Any, ...]] = {}
    if not root.exists() and not root.is_symlink():
        return snapshot
    paths = [root]
    if root.is_dir() and not root.is_symlink():
        paths.extend(sorted(root.rglob("*")))
    for path in paths:
        stat_result = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            payload: tuple[Any, ...] = ("symlink", stat_result.st_ino, os.readlink(path))
        elif path.is_dir():
            payload = ("directory", stat_result.st_ino, stat_result.st_mode)
        else:
            payload = (
                "file",
                stat_result.st_ino,
                stat_result.st_mode,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        snapshot[relative] = payload
    return snapshot


def quarantine_snapshot(repo_root: Path) -> dict[str, tuple[Any, ...]]:
    return filesystem_snapshot(repo_root / ".goalteams-quarantine")


DELIVERY_REQUIREMENTS = (
    "contract_gate_current",
    "architecture_gate_current",
    "environment_gate_current",
    "required_tasks_accepted",
    "required_checks_passed",
    "current_evidence_and_reviews",
    "bundle_consistent",
    "reset_lineage_current",
    "rebuilt_candidate_digest_current",
    "full_tests_passed",
    "archive_preflight_passed",
    "completion_audit_passed",
    "scores_valid",
    "prompt_lifecycle_closed",
    "bottleneck_current",
    "version_sync_passed",
    "publish_guard_passed",
    "roadmap_unchanged",
    "worktree_scope_preserved",
)


def delivery_bundle(iteration: int = 11, phase: str = "verify") -> dict[str, Any]:
    return {
        "bundle_revision": 60,
        "bundle_digest": FIXED_HASH_A,
        "loop": {
            "iteration": iteration,
            "attempt": 1,
            "phase": phase,
            "loop_decision": "continue",
            "run_outcome": "partial",
        },
        "delivery": {"state": "not_ready"},
    }


def complete_delivery_inputs() -> dict[str, Any]:
    result: dict[str, Any] = {name: True for name in DELIVERY_REQUIREMENTS}
    result.update(
        {
            "ledger_revision": 50,
            "ledger_prefix_sha256": FIXED_HASH_A,
            "completion_audit_ref": "audit/completion-audit.json",
            "completion_audit_sha256": FIXED_HASH_B,
            "independent_validator_run_id": "RUN-COMPLETION-AUDITOR-V234-01",
        }
    )
    return result


def completion_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "source_artifact_id": f"ART-V234-PUBLIC-{index:02d}",
            "source_ref": source_ref,
            "archive_ref": Path(source_ref).name,
            "publication_state": "completed",
            "visibility": "public",
            "artifact_version": "V2.34",
            "validator_run_id": VALIDATOR_RUN,
            "contract_revision": 2,
            "classification": "public_completion_doc",
            "accepted": True,
        }
        for index, source_ref in enumerate(
            ("public/guide.md", "public/release.md"), 1
        )
    ]


def strict_completion_fixture(
    test: unittest.TestCase,
    root: Path,
    descriptors: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    reset, evidence_registry, events, checkpoint = strict_reset_proof(root)
    v234 = require_v234(test)

    surfaces = {
        "VERSION": "V2.34\n",
        "SKILL.md": "当前版本 `V2.34`。\n启动身份：Goal Teams Lead V2.34。\n",
        "README.md": "当前版本：`V2.34`\n",
        "README.en.md": "Current version: `V2.34`\n",
        "scripts/v23/goalteams_v23.py": 'PRODUCT_VERSION = "V2.34"\n',
        "agents/openai.yaml": "description: Goal Teams V2.34\n",
        "public/guide.md": "# V2.34 Guide\n",
        "public/release.md": "# V2.34 Release\n",
        "user-owned.txt": "user baseline\n",
    }
    for relative, content in surfaces.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # The roadmap belongs to the caller's workspace and is deliberately not an
    # install-package dependency.  Keep the release proof fixture self-contained
    # so installation lifecycle validation does not require an untracked plan.
    roadmap = root / "docs" / "后续版本规划 V3.3-3.5.md"
    roadmap.parent.mkdir(parents=True, exist_ok=True)
    roadmap.write_bytes(b"# V2.34 roadmap fixture\n\n- immutable input\n")
    subprocess.run(
        ["git", "add", *surfaces.keys(), roadmap.relative_to(root).as_posix()],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-qm", "completion baseline"], cwd=root, check=True)
    baseline_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    candidate = root / "public" / "candidate.txt"
    candidate.write_text("verified V2.34 candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", candidate.relative_to(root).as_posix()], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "verified candidate"], cwd=root, check=True)
    candidate_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()

    identities, _ = reset_security_context(None)
    identities["runs"].update(
        {
            "RUN-COMPLETION-AUDITOR-V234-01": {
                "member_id": "MEMBER-COMPLETION-AUDITOR-V234",
                "role": "completion_auditor",
            },
            VALIDATOR_RUN: {"member_id": "MEMBER-QA-V234", "role": "reviewer"},
        }
    )
    identity_path = root / "identity" / "registry.json"
    identity_path.parent.mkdir()
    identity_path.write_text(
        json.dumps(identities, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence_id = reset["reset"]["evidence_id"]
    review_core = {
        "schema_version": "goal-teams-v2.34-review-v1",
        "review_id": "REVIEW-V234-COMPLETION-001",
        "state": "passed",
        "author_run_id": "RUN-RESET-RUNNER-V234-01",
        "validator_run_id": VALIDATOR_RUN,
        "ledger_revision": checkpoint["ledger_revision"],
        "evidence_refs": [evidence_id],
        "artifact_ref": candidate.relative_to(root).as_posix(),
        "artifact_sha256": candidate_sha,
    }
    review = {**review_core, "record_sha256": canonical_hash(review_core)}
    review_path = root / "reviews" / "completion-review.json"
    review_path.parent.mkdir()
    review_path.write_text(
        json.dumps(review, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    task_digest = canonical_hash(checkpoint["tasks"])
    audit_core = {
        "schema_version": "goal-teams-v2.34-completion-audit-v1",
        "audit_id": "AUD-V234-COMPLETION-001",
        "state": "passed",
        "run_outcome_candidate": "achieved",
        "author_run_id": "RUN-RESET-RUNNER-V234-01",
        "auditor_run_id": "RUN-COMPLETION-AUDITOR-V234-01",
        "ledger_revision": checkpoint["ledger_revision"],
        "task_state_digest": task_digest,
        "required_task_ids": ["TASK-V234-RESET"],
        "evidence_refs": [evidence_id],
        "review_id": review["review_id"],
        "review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
        "bundle_revision": reset["bundle_revision"],
        "bundle_digest": reset["bundle_digest"],
    }
    audit = {**audit_core, "record_sha256": canonical_hash(audit_core)}
    audit_path = root / "audit" / "completion-audit.json"
    audit_path.parent.mkdir()
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    scores = score_record(reviewer_run_id=VALIDATOR_RUN)
    scores["artifact_sha256"] = candidate_sha
    scores["artifact_owner_run_id"] = "RUN-RESET-RUNNER-V234-01"
    scores["evidence_refs"] = [evidence_id]
    for dimension in scores["dimensions"].values():
        for item in dimension["items"]:
            item["artifact_sha256"] = candidate_sha
            item["evidence_refs"] = [evidence_id]
    test.assertTrue(v234.validate_quality_scores(scores)["ok"])

    worktree_guard = v234.capture_worktree_guard(
        root, protected_paths=["user-owned.txt"]
    )
    bundle = copy.deepcopy(reset)
    bundle["loop"].update(
        iteration=11,
        phase="verify",
        run_outcome="partial",
        loop_decision="continue",
    )
    bundle["quality_scores"] = scores
    bundle["bottleneck"] = {
        "assessment_id": "BOTTLENECK-V234-ITERATION-11",
        "iteration": 11,
        "phase": "verify",
        "current": None,
        "evidence_refs": [evidence_id],
    }
    proof = {
        "schema_version": "goal-teams-v2.34-completion-proof-v1",
        "bundle_revision": bundle["bundle_revision"],
        "bundle_digest": bundle["bundle_digest"],
        "contract_revision": 2,
        "ledger_revision": checkpoint["ledger_revision"],
        "required_task_ids": ["TASK-V234-RESET"],
        "evidence_ids": [evidence_id],
        "review_id": review["review_id"],
        "completion_audit_id": audit["audit_id"],
        "reset": {
            "reset_event_id": reset["reset"]["reset_event_id"],
            "receipt_sha256": reset["reset"]["receipt_sha256"],
            "manifest_sha256": reset["reset"]["manifest_sha256"],
            "evidence_id": evidence_id,
        },
        "rebuilt_candidate": {
            "artifact_ref": candidate.relative_to(root).as_posix(),
            "artifact_sha256": candidate_sha,
            "evidence_id": evidence_id,
        },
        "repository_check": {
            "evidence_id": evidence_id,
            "artifact_sha256": evidence_registry["records"][evidence_id]["artifact_sha256"],
        },
        "quality_scores": scores,
        "prompt_lifecycle": [],
        "bottleneck": copy.deepcopy(bundle["bottleneck"]),
        "version": "V2.34",
        "roadmap_sha256": hashlib.sha256(roadmap.read_bytes()).hexdigest(),
        "worktree_guard_sha256": worktree_guard["guard_sha256"],
        "archive_descriptor_sha256": canonical_hash(descriptors),
    }
    proof["proof_digest"] = canonical_hash(proof)
    proof_path = root / "completion-proof.json"
    proof_path.write_text(
        json.dumps(proof, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    context = {
        "repo_root": str(root),
        "ledger_events": events,
        "checkpoint": checkpoint,
        "evidence_registry": evidence_registry,
        "identity_registry": identities,
        "identity_path": str(identity_path),
        "review_record": review,
        "review_path": str(review_path),
        "audit_record": audit,
        "audit_path": str(audit_path),
        "completion_proof_path": str(proof_path),
        "worktree_guard": worktree_guard,
        "baseline_commit": baseline_commit,
        "candidate_commit": candidate_commit,
        "roadmap_path": str(roadmap),
    }
    completion = {
        "run_outcome_candidate": "achieved",
        "completion_audit": {
            "state": "passed",
            "validator_run_id": audit["auditor_run_id"],
            "ledger_revision": checkpoint["ledger_revision"],
            "sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        },
        "contract_revision": 2,
    }
    return bundle, proof, context, completion


class V234ResetTests(unittest.TestCase):
    def test_iteration_nine_reset_is_mandatory(self) -> None:
        """ASSERT-V234-023"""
        v234 = require_v234(self)
        for target in ("act", "iteration_10", "delivery"):
            result = v234.evaluate_reset_gate(
                reset_bundle(),
                target=target,
                evidence_registry={},
                ledger_events=[],
                identity_registry={"runs": {}},
                checkpoint={},
            )
            with self.subTest(target=target):
                assert_error_code(self, result, "E_V234_RESET_REQUIRED")

        with tempfile.TemporaryDirectory() as directory:
            completed, registry, reset_events, reset_checkpoint = strict_reset_proof(
                Path(directory)
            )
            identities, _ = reset_security_context(None)
            for target in ("act", "iteration_10", "delivery"):
                current = v234.evaluate_reset_gate(
                    completed,
                    target=target,
                    evidence_registry=registry,
                    ledger_events=reset_events,
                    identity_registry=identities,
                    checkpoint=reset_checkpoint,
                )
                with self.subTest(target=target, case="current"):
                    self.assertTrue(current["ok"], current)
                    self.assertEqual(current["mutation_count"], 0)

            evidence_id = completed["reset"]["evidence_id"]
            negative_mutations = {
                "stale": ("current", False),
                "unverified_trust": ("trust_level", "unverified"),
                "wrong_bundle_revision": ("bundle_revision", 39),
                "wrong_bundle_digest": ("bundle_digest", "8" * 64),
                "wrong_attempt": ("attempt_id", "ATT-V234-OTHER"),
                "wrong_contract_revision": ("contract_revision", 3),
                "wrong_contract_digest": ("contract_sha256", "3" * 64),
                "wrong_reset_event": ("reset_event_id", "EVT-V234-OTHER"),
                "wrong_manifest": ("manifest_sha256", "4" * 64),
                "wrong_receipt": ("receipt_sha256", "5" * 64),
                "wrong_reset_ledger_revision": ("reset_ledger_revision", 1),
                "wrong_reset_ledger_prefix": ("reset_ledger_prefix_sha256", "6" * 64),
                "future_ledger_prefix": ("ledger_revision", len(reset_events) + 1),
                "invalid_ledger_prefix": ("ledger_prefix_sha256", "6" * 64),
                "cross_task": ("task_id", "TASK-V234-OTHER"),
                "self_validated": (
                    "validator_run_id",
                    "RUN-RESET-RUNNER-V234-01",
                ),
            }
            for case, (field, value) in negative_mutations.items():
                candidate_registry = copy.deepcopy(registry)
                candidate_registry["records"][evidence_id][field] = value
                candidate_registry["records_sha256"] = canonical_hash(
                    candidate_registry["records"]
                )
                for target in ("act", "iteration_10", "delivery"):
                    result = v234.evaluate_reset_gate(
                        completed,
                        target=target,
                        evidence_registry=candidate_registry,
                        ledger_events=reset_events,
                        identity_registry=identities,
                        checkpoint=reset_checkpoint,
                    )
                    with self.subTest(case=case, target=target):
                        self.assertFalse(result["ok"], result)
                        self.assertEqual(result["mutation_count"], 0)
                        self.assertNotEqual(result.get("run_outcome"), "achieved")

            missing = v234.evaluate_reset_gate(
                completed,
                target="act",
                evidence_registry={},
                ledger_events=reset_events,
                identity_registry=identities,
                checkpoint=reset_checkpoint,
            )
            self.assertFalse(missing["ok"], missing)

        # The LOOP transition itself must enforce the reset gate.  Calling the
        # generic state transition API without current reset Evidence cannot
        # bypass the dedicated reset command at iteration 9 reason -> act.
        with tempfile.TemporaryDirectory() as directory:
            _, _, state_root, _ = initialize_bundle(
                self, directory, iteration=9, phase="reason"
            )
            before = marker(state_root)
            result = v234.transition_state_bundle(
                state_root,
                to_phase="act",
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                actor_run_id=OWNER_RUN,
                evidence_registry={},
                identity_registry={"runs": {}},
                **state_proof(state_root),
            )
            assert_error_code(self, result, "E_V234_RESET_REQUIRED")
            self.assertEqual(marker(state_root)["bundle_revision"], before["bundle_revision"])
            self.assertEqual(marker(state_root)["loop"]["phase"], "reason")

    def test_reset_candidate_identity_and_containment(self) -> None:
        """ASSERT-V234-024"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            repo_root = Path(directory)
            state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
            state_root.mkdir(parents=True)
            candidate = create_candidate(repo_root)
            authorization = reset_authorization(repo_root, candidate)
            identities, authorization_events = reset_security_context(authorization)
            result = v234.plan_controlled_reset(
                reset_bundle(),
                candidate.name,
                authorization,
                repo_root=repo_root,
                state_root=state_root,
                identity_registry=identities,
                ledger_events=authorization_events,
            )
            self.assertTrue(result["ok"], result)
            plan = result["plan"]
            self.assertEqual(plan["candidate_realpath"], str(candidate.resolve()))
            self.assertEqual(plan["before_tree_sha256"], tree_digest(candidate))
            self.assertNotEqual(plan["candidate_realpath"], str(repo_root.resolve()))
            self.assertTrue(Path(plan["candidate_realpath"]).is_relative_to(repo_root.resolve()))

    def test_reset_destructive_negative_matrix(self) -> None:
        """ASSERT-V234-025"""
        v234 = require_v234(self)
        cases = (
            "missing", "traversal", "absolute", "dot", "empty", "backslash",
            "control", "path_ambiguity", "symlink", "root_alias", "ancestor_symlink",
            "tree_escape_symlink", "no_authorization", "auth_operation",
            "auth_candidate", "auth_scope", "dirty", "digest_drift",
            "protected_repo_root", "protected_state_root", "protected_artifact_root", "protected_candidate_root",
            "protected_git", "protected_docs", "protected_ledger", "protected_evidence",
            "protected_audit", "protected_provenance", "ownership_unknown",
            "permission_unknown", "forged_authority", "quarantine_conflict",
            "quarantine_ancestor_symlink",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                repo_root = Path(directory)
                state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
                state_root.mkdir(parents=True)
                artifact_root = repo_root / "artifact-root"
                artifact_root.mkdir()
                candidate = create_candidate(repo_root)
                authorization: dict[str, Any] | None = reset_authorization(repo_root, candidate)
                candidate_id = candidate.name
                expected_code = "E_V234_RESET_PREFLIGHT"
                authorization_block = False

                def bind_target(target: Path) -> None:
                    nonlocal candidate_id, authorization
                    assert authorization is not None
                    authorization["disposable_candidate_root"] = target.parent.relative_to(repo_root).as_posix() or "."
                    authorization["candidate_id"] = target.name
                    authorization["candidate_path"] = target.relative_to(repo_root).as_posix()
                    authorization["expected_realpath"] = str(target.resolve())
                    authorization["before_tree_sha256"] = tree_digest(target)
                    authorization["manifest_paths"] = [
                        path.relative_to(target).as_posix()
                        for path in sorted(target.rglob("*"))
                        if path.is_file() and not path.is_symlink()
                    ]
                    candidate_id = target.name
                    refresh_authorization_scope(authorization)

                if case == "missing":
                    candidate_id = "does-not-exist"
                    assert authorization is not None
                    authorization.update(
                        candidate_id=candidate_id,
                        candidate_path=f".goalteams-candidates/{candidate_id}",
                        expected_realpath=str(
                            (repo_root / ".goalteams-candidates" / candidate_id).resolve()
                        ),
                    )
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_TARGET_MISSING"
                elif case == "traversal":
                    candidate_id = "../candidate-v234"
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "absolute":
                    candidate_id = str(candidate.resolve())
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "dot":
                    candidate_id = "."
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "empty":
                    candidate_id = ""
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "backslash":
                    candidate_id = "candidate\\v234"
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "control":
                    candidate_id = "candidate\x00v234"
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "path_ambiguity":
                    candidate_id = "candidate//v234"
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "symlink":
                    outside = repo_root / "outside"
                    outside.mkdir()
                    link = repo_root / ".goalteams-candidates" / "candidate-link"
                    link.symlink_to(outside, target_is_directory=True)
                    candidate_id = link.name
                    authorization = reset_authorization(repo_root, candidate)
                    authorization["candidate_id"] = candidate_id
                    authorization["candidate_path"] = f".goalteams-candidates/{candidate_id}"
                    authorization["expected_realpath"] = str(outside.resolve())
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_SYMLINK"
                elif case == "root_alias":
                    alias = repo_root / ".goalteams-candidates" / "repo-root-alias"
                    alias.symlink_to(repo_root, target_is_directory=True)
                    candidate_id = alias.name
                    assert authorization is not None
                    authorization.update(
                        candidate_id=candidate_id,
                        candidate_path=f".goalteams-candidates/{candidate_id}",
                        expected_realpath=str(repo_root.resolve()),
                    )
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_SYMLINK"
                elif case == "ancestor_symlink":
                    shutil.rmtree(repo_root / ".goalteams-candidates")
                    real_candidates = repo_root / "real-candidates"
                    candidate = create_candidate(real_candidates.parent, candidate.name)
                    # Move the helper-created root to the intended non-standard location.
                    helper_root = real_candidates.parent / ".goalteams-candidates"
                    helper_root.rename(real_candidates)
                    (repo_root / ".goalteams-candidates").symlink_to(real_candidates, target_is_directory=True)
                    candidate = real_candidates / "candidate-v234"
                    authorization = reset_authorization(repo_root, candidate)
                    authorization["candidate_path"] = ".goalteams-candidates/candidate-v234"
                    authorization["expected_realpath"] = str(candidate.resolve())
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_SYMLINK"
                elif case == "tree_escape_symlink":
                    outside = repo_root / "outside.txt"
                    outside.write_text("outside\n", encoding="utf-8")
                    (candidate / "escape").symlink_to(outside)
                    assert authorization is not None
                    authorization["before_tree_sha256"] = tree_digest(candidate)
                    authorization["manifest_paths"].append("escape")
                    expected_code = "E_V234_RESET_SYMLINK"
                elif case == "no_authorization":
                    authorization = None
                    expected_code = "E_V234_RESET_AUTHORIZATION"
                    authorization_block = True
                elif case == "auth_operation":
                    assert authorization is not None
                    authorization["operation"] = "purge"
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_AUTHORIZATION"
                    authorization_block = True
                elif case == "auth_candidate":
                    assert authorization is not None
                    authorization["candidate_id"] = "other-candidate"
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_AUTHORIZATION"
                    authorization_block = True
                elif case == "auth_scope":
                    assert authorization is not None
                    authorization["authorized_scope_digest"] = "0" * 64
                    expected_code = "E_V234_RESET_AUTHORIZATION"
                    authorization_block = True
                elif case == "dirty":
                    (candidate / "user-note.txt").write_text("unregistered", encoding="utf-8")
                    # Deliberately update the tree hash while leaving the allow manifest stale.
                    assert authorization is not None
                    authorization["before_tree_sha256"] = tree_digest(candidate)
                    expected_code = "E_V234_RESET_UNREGISTERED_CHANGE"
                elif case == "digest_drift":
                    (candidate / "app.py").write_text("changed after authorization\n", encoding="utf-8")
                    expected_code = "E_V234_RESET_DIGEST"
                elif case == "protected_repo_root":
                    assert authorization is not None
                    authorization.update(
                        disposable_candidate_root="..",
                        candidate_id=repo_root.name,
                        candidate_path=".",
                        expected_realpath=str(repo_root.resolve()),
                        before_tree_sha256=tree_digest(repo_root),
                    )
                    candidate_id = repo_root.name
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_PROTECTED_ROOT"
                elif case == "protected_state_root":
                    bind_target(state_root)
                    expected_code = "E_V234_RESET_PROTECTED_ROOT"
                elif case == "protected_artifact_root":
                    bind_target(artifact_root)
                    expected_code = "E_V234_RESET_PROTECTED_ROOT"
                elif case == "protected_candidate_root":
                    candidate_id = "."
                    expected_code = "E_V234_RESET_CANDIDATE_ID"
                elif case == "protected_git":
                    git_root = repo_root / ".git"
                    git_root.mkdir()
                    alias = repo_root / ".goalteams-candidates" / "git-root-alias"
                    alias.symlink_to(git_root, target_is_directory=True)
                    candidate_id = alias.name
                    assert authorization is not None
                    authorization.update(candidate_id=candidate_id, candidate_path=f".goalteams-candidates/{candidate_id}", expected_realpath=str(git_root.resolve()))
                    refresh_authorization_scope(authorization)
                    expected_code = "E_V234_RESET_SYMLINK"
                elif case == "protected_docs":
                    docs_root = repo_root / "docs"
                    docs_root.mkdir()
                    bind_target(docs_root)
                    expected_code = "E_V234_RESET_PROTECTED_ROOT"
                elif case.startswith("protected_"):
                    name = case.removeprefix("protected_")
                    protected = state_root / name
                    protected.mkdir()
                    bind_target(protected)
                    expected_code = "E_V234_RESET_PROTECTED_ROOT"
                elif case == "ownership_unknown":
                    assert authorization is not None
                    authorization["ownership_verified"] = False
                    expected_code = "E_V234_RESET_OWNERSHIP"
                    authorization_block = True
                elif case == "permission_unknown":
                    assert authorization is not None
                    authorization["permission_verified"] = False
                    expected_code = "E_V234_RESET_PERMISSION"
                    authorization_block = True
                elif case == "forged_authority":
                    assert authorization is not None
                    authorization["authorized_by_run_id"] = "RUN-FORGED-RESET-AUTHORITY"
                    expected_code = "E_V234_RESET_AUTHORIZATION"
                    authorization_block = True
                elif case == "quarantine_conflict":
                    conflict = repo_root / ".goalteams-quarantine" / "RESET-V234-001" / candidate.name
                    conflict.mkdir(parents=True)
                    expected_code = "E_V234_RESET_QUARANTINE_CONFLICT"
                elif case == "quarantine_ancestor_symlink":
                    outside_quarantine = repo_root / "outside-quarantine"
                    outside_quarantine.mkdir()
                    (repo_root / ".goalteams-quarantine").symlink_to(
                        outside_quarantine, target_is_directory=True
                    )
                    expected_code = "E_V234_RESET_SYMLINK"

                if authorization is not None:
                    refresh_authorization_record(authorization)
                identities, authorization_events = reset_security_context(authorization)
                before = filesystem_snapshot(repo_root)
                quarantine_before = quarantine_snapshot(repo_root)
                result = v234.plan_controlled_reset(
                    reset_bundle(),
                    candidate_id,
                    authorization,
                    repo_root=repo_root,
                    state_root=state_root,
                    artifact_root=artifact_root,
                    identity_registry=identities,
                    ledger_events=authorization_events,
                )
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error_code"], expected_code, result)
                self.assertEqual(result["mutation_count"], 0, result)
                self.assertEqual(before, filesystem_snapshot(repo_root), "preflight failure must mutate zero paths")
                self.assertEqual(quarantine_before, quarantine_snapshot(repo_root))
                if authorization_block:
                    self.assertEqual(result.get("task_state"), "blocked")
                    self.assertEqual(result.get("check_state"), "blocked")
                    self.assertEqual(result.get("stop_reason"), "authorization_required")
                else:
                    self.assertEqual(result.get("task_state"), "running")
                    self.assertEqual(result.get("check_state"), "failed")

        for drift in ("inode", "tree_hash", "quarantine_ancestor"):
            with self.subTest(case=f"toctou_{drift}"), tempfile.TemporaryDirectory() as directory:
                (
                    v234,
                    repo_root,
                    state_root,
                    bundle,
                    candidate,
                    authorization,
                    identities,
                    authorization_events,
                    checkpoint,
                ) = initialize_reset_state(self, directory)
                artifact_root = repo_root / "artifact-root"
                artifact_root.mkdir()
                planned = v234.plan_controlled_reset(
                    bundle, candidate.name, authorization,
                    repo_root=repo_root, state_root=state_root, artifact_root=artifact_root,
                    identity_registry=identities, ledger_events=authorization_events,
                )
                self.assertTrue(planned["ok"], planned)
                if drift == "inode":
                    replaced = candidate.with_name("candidate-old")
                    candidate.rename(replaced)
                    candidate.mkdir()
                    for source in replaced.iterdir():
                        if source.is_file():
                            shutil.copy2(source, candidate / source.name)
                else:
                    if drift == "tree_hash":
                        (candidate / "app.py").write_text(
                            "changed after plan\n", encoding="utf-8"
                        )
                    else:
                        outside_quarantine = repo_root / "outside-quarantine"
                        outside_quarantine.mkdir()
                        (repo_root / ".goalteams-quarantine").symlink_to(
                            outside_quarantine, target_is_directory=True
                        )
                candidate_before = filesystem_snapshot(candidate)
                quarantine_before = quarantine_snapshot(repo_root)
                result = v234.apply_controlled_reset(
                    bundle, planned["plan"], authorization,
                    repo_root=repo_root, state_root=state_root,
                    actor_run_id=OWNER_RUN,
                    identity_registry=identities,
                    ledger_events=authorization_events,
                    checkpoint=checkpoint,
                )
                self.assertFalse(result["ok"], result)
                self.assertIn(
                    result["error_code"],
                    {"E_V234_RESET_TOCTOU", "E_V234_RESET_SYMLINK"},
                    result,
                )
                self.assertEqual(result["mutation_count"], 0)
                self.assertEqual(candidate_before, filesystem_snapshot(candidate))
                self.assertEqual(quarantine_before, quarantine_snapshot(repo_root))

        with self.subTest(case="cross_device"), tempfile.TemporaryDirectory() as directory:
            (
                v234,
                repo_root,
                state_root,
                bundle,
                candidate,
                authorization,
                identities,
                authorization_events,
                checkpoint,
            ) = initialize_reset_state(self, directory)
            artifact_root = repo_root / "artifact-root"
            artifact_root.mkdir()
            quarantine_parent = repo_root / ".goalteams-quarantine" / "RESET-V234-001"
            quarantine_parent.mkdir(parents=True)
            planned = v234.plan_controlled_reset(
                bundle, candidate.name, authorization,
                repo_root=repo_root, state_root=state_root, artifact_root=artifact_root,
                identity_registry=identities, ledger_events=authorization_events,
            )
            self.assertTrue(planned["ok"], planned)
            real_fstat = os.fstat

            def other_device(result: os.stat_result) -> os.stat_result:
                fields = list(result)
                fields[2] = result.st_dev + 1
                return os.stat_result(fields)

            def fake_fstat(descriptor: int) -> os.stat_result:
                return other_device(real_fstat(descriptor))

            candidate_before = filesystem_snapshot(candidate)
            quarantine_before = quarantine_snapshot(repo_root)
            with mock.patch.object(v234.os, "fstat", side_effect=fake_fstat):
                result = v234.apply_controlled_reset(
                    bundle, planned["plan"], authorization,
                    repo_root=repo_root, state_root=state_root,
                    actor_run_id=OWNER_RUN,
                    identity_registry=identities,
                    ledger_events=authorization_events,
                    checkpoint=checkpoint,
                )
            assert_error_code(self, result, "E_V234_RESET_CROSS_DEVICE")
            self.assertEqual(result["mutation_count"], 0)
            self.assertEqual(candidate_before, filesystem_snapshot(candidate))
            self.assertEqual(quarantine_before, quarantine_snapshot(repo_root))

    def test_reset_quarantine_manifest_and_recovery(self) -> None:
        """ASSERT-V234-026"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            (
                v234,
                repo_root,
                state_root,
                bundle,
                candidate,
                authorization,
                identities,
                authorization_events,
                checkpoint,
            ) = initialize_reset_state(self, directory)
            planned = v234.plan_controlled_reset(
                bundle, candidate.name, authorization,
                repo_root=repo_root, state_root=state_root,
                identity_registry=identities, ledger_events=authorization_events,
            )
            self.assertTrue(planned["ok"], planned)
            applied = v234.apply_controlled_reset(
                bundle, planned["plan"], authorization,
                repo_root=repo_root, state_root=state_root,
                actor_run_id=OWNER_RUN,
                identity_registry=identities,
                ledger_events=authorization_events,
                checkpoint=checkpoint,
            )
            self.assertTrue(applied["ok"], applied)
            self.assertFalse(candidate.exists())
            quarantine = Path(applied["manifest"]["quarantine_realpath"])
            self.assertTrue(quarantine.is_dir())
            for field in (
                "source_realpath", "quarantine_realpath", "before_tree_sha256",
                "timestamp", "actor_run_id", "contract_revision", "reset_event_id",
                "recovery_command",
            ):
                self.assertTrue(applied["manifest"].get(field), field)
            self.assertEqual(applied["manifest"]["before_tree_sha256"], authorization["before_tree_sha256"])

    def test_reset_noncanonical_task_binding_and_safe_repair(self) -> None:
        """ASSERT-V234-023 ASSERT-V234-024 ASSERT-V234-026"""
        v234 = require_v234(self)
        reset_task_id = "TASK-V234R3-RESET"
        with tempfile.TemporaryDirectory() as directory:
            (
                v234,
                repo_root,
                state_root,
                bundle,
                candidate,
                authorization,
                identities,
                authorization_events,
                checkpoint,
            ) = initialize_reset_state(self, directory, task_id=reset_task_id)
            planned = v234.plan_controlled_reset(
                bundle, candidate.name, authorization,
                repo_root=repo_root, state_root=state_root,
                identity_registry=identities, ledger_events=authorization_events,
            )
            self.assertTrue(planned["ok"], planned)
            self.assertEqual(planned["plan"]["task_id"], reset_task_id)
            applied = v234.apply_controlled_reset(
                bundle, planned["plan"], authorization,
                repo_root=repo_root, state_root=state_root,
                actor_run_id=OWNER_RUN,
                identity_registry=identities, ledger_events=authorization_events,
                checkpoint=checkpoint,
            )
            self.assertTrue(applied["ok"], applied)
            self.assertEqual(applied["manifest"]["task_id"], reset_task_id)
            self.assertEqual(applied["receipt"]["task_id"], reset_task_id)
            self.assertEqual(marker(state_root)["reset"]["task_id"], reset_task_id)

            # Reproduce the early V2.34 projection bug without touching the
            # quarantine receipt, then prove that recovery derives its target
            # from the immutable authorization event (not caller input).
            current = marker(state_root)
            regressed = v234._commit_projection_update(
                state_root,
                expected_bundle_revision=current["bundle_revision"],
                expected_bundle_digest=current["bundle_digest"],
                actor_run_id=OWNER_RUN,
                event_type="TEST_RESET_TASK_REGRESSION",
                assertion_refs=["ASSERT-V234-023"],
                mutation=lambda value: value["reset"].__setitem__(
                    "task_id", "TASK-V234-RESET"
                ),
                ledger_events=authorization_events,
                checkpoint=checkpoint,
            )
            self.assertTrue(regressed["ok"], regressed)
            regressed_marker = marker(state_root)
            unauthorized = v234.repair_reset_task_binding(
                state_root, authorization,
                actor_run_id="RUN-UNREGISTERED-V234",
                expected_bundle_revision=regressed_marker["bundle_revision"],
                expected_bundle_digest=regressed_marker["bundle_digest"],
                identity_registry=identities,
                ledger_events=authorization_events,
                checkpoint=checkpoint,
            )
            assert_error_code(self, unauthorized, "E_V234_RESET_TASK_BINDING")
            self.assertEqual(unauthorized["mutation_count"], 0)
            self.assertEqual(marker(state_root), regressed_marker)
            repaired = v234.repair_reset_task_binding(
                state_root, authorization,
                actor_run_id=OWNER_RUN,
                expected_bundle_revision=regressed_marker["bundle_revision"],
                expected_bundle_digest=regressed_marker["bundle_digest"],
                identity_registry=identities,
                ledger_events=authorization_events,
                checkpoint=checkpoint,
            )
            self.assertTrue(repaired["ok"], repaired)
            self.assertEqual(repaired["previous_task_id"], "TASK-V234-RESET")
            self.assertEqual(repaired["task_id"], reset_task_id)
            self.assertEqual(marker(state_root)["reset"]["task_id"], reset_task_id)

            idempotent_marker = marker(state_root)
            idempotent = v234.repair_reset_task_binding(
                state_root, authorization,
                actor_run_id=OWNER_RUN,
                expected_bundle_revision=idempotent_marker["bundle_revision"],
                expected_bundle_digest=idempotent_marker["bundle_digest"],
                identity_registry=identities,
                ledger_events=authorization_events,
                checkpoint=checkpoint,
            )
            self.assertTrue(idempotent["ok"], idempotent)
            self.assertTrue(idempotent["idempotent"])
            self.assertEqual(idempotent["mutation_count"], 0)

    def test_quarantine_purge_requires_new_authorization(self) -> None:
        """ASSERT-V234-027"""
        v234 = require_v234(self)
        reset_auth = {"authorization_id": "AUTH-RESET", "operation": "quarantine"}
        for purge_auth in (None, reset_auth, {"authorization_id": "AUTH-RESET", "operation": "purge"}):
            result = v234.validate_purge_authorization(reset_auth, purge_auth)
            self.assertFalse(result["ok"], result)
        explicit = v234.validate_purge_authorization(
            reset_auth,
            {"authorization_id": "AUTH-PURGE-NEW", "operation": "purge", "explicit": True},
        )
        self.assertTrue(explicit["ok"], explicit)


class V234DeliveryTests(unittest.TestCase):
    def test_early_delivery_is_rejected(self) -> None:
        """ASSERT-V234-028"""
        v234 = require_v234(self)
        for iteration in range(1, 11):
            result = v234.evaluate_delivery_gate(
                delivery_bundle(iteration=iteration), complete_delivery_inputs(), []
            )
            with self.subTest(iteration=iteration):
                assert_error_code(self, result, "E_V234_DELIVERY_ITERATION")
                self.assertNotEqual(result.get("run_outcome"), "achieved")

    def test_intact_delivery_full_conjunction(self) -> None:
        """ASSERT-V234-029"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            descriptors = completion_descriptors()
            bundle, proof, context, _ = strict_completion_fixture(
                self, Path(directory), descriptors
            )
            valid = v234.evaluate_delivery_gate(
                bundle, proof, descriptors, source_context=context
            )
            self.assertTrue(valid["ok"], valid)

            proof_mutations = {
                "ledger": lambda candidate: candidate.__setitem__(
                    "required_task_ids", ["TASK-V234-MISSING"]
                ),
                "evidence": lambda candidate: candidate.__setitem__(
                    "evidence_ids", ["EVD-V234-MISSING"]
                ),
                "review": lambda candidate: candidate.__setitem__(
                    "review_id", "REVIEW-V234-MISSING"
                ),
                "audit": lambda candidate: candidate.__setitem__(
                    "completion_audit_id", "AUD-V234-MISSING"
                ),
                "reset": lambda candidate: candidate["reset"].__setitem__(
                    "receipt_sha256", "0" * 64
                ),
                "rebuild": lambda candidate: candidate["rebuilt_candidate"].__setitem__(
                    "artifact_sha256", "0" * 64
                ),
                "tests": lambda candidate: candidate["repository_check"].__setitem__(
                    "evidence_id", "EVD-V234-MISSING"
                ),
                "scores": lambda candidate: candidate["quality_scores"]["dimensions"][
                    "functionality"
                ].__setitem__("score", 0.75),
                "prompt": lambda candidate: candidate["prompt_lifecycle"].append(
                    {"status": "applied", "required": True}
                ),
                "bottleneck": lambda candidate: candidate["bottleneck"].__setitem__(
                    "iteration", 10
                ),
                "version": lambda candidate: candidate.__setitem__("version", "V2.33"),
                "archive": lambda candidate: candidate.__setitem__(
                    "archive_descriptor_sha256", "0" * 64
                ),
                "roadmap": lambda candidate: candidate.__setitem__(
                    "roadmap_sha256", "0" * 64
                ),
                "worktree": lambda candidate: candidate.__setitem__(
                    "worktree_guard_sha256", "0" * 64
                ),
            }
            for requirement, mutate in proof_mutations.items():
                broken = copy.deepcopy(proof)
                mutate(broken)
                broken["proof_digest"] = canonical_hash(
                    {key: value for key, value in broken.items() if key != "proof_digest"}
                )
                result = v234.evaluate_delivery_gate(
                    bundle, broken, descriptors, source_context=context
                )
                with self.subTest(requirement=requirement):
                    self.assertFalse(result["ok"], result)
                    self.assertNotEqual(result.get("run_outcome"), "achieved")

    def test_iteration_eleven_failure_stops_without_iteration_twelve(self) -> None:
        """ASSERT-V234-030"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            descriptors = completion_descriptors()
            bundle, proof, context, _ = strict_completion_fixture(
                self, Path(directory), descriptors
            )
            Path(context["audit_path"]).write_text('{"state":"failed"}\n', encoding="utf-8")
            result = v234.evaluate_delivery_gate(
                bundle, proof, descriptors, source_context=context
            )
            self.assertFalse(result["ok"], result)
            self.assertIn(result["run_outcome"], {"partial", "blocked"})
            self.assertIsNone(result.get("next_iteration"))
            self.assertFalse(result.get("archive_created", False))
            self.assertNotEqual(result["run_outcome"], "achieved")

        pure_transition = v234.validate_loop_transition(
            {
                "phase": "repeat",
                "iteration": 11,
                "attempt": 1,
                "verify_committed": True,
                "loop_decision": "continue",
                "run_outcome": "partial",
            },
            {"to_phase": "gather"},
        )
        self.assertFalse(pure_transition["ok"], pure_transition)
        self.assertNotEqual(
            pure_transition.get("next_state", {}).get("iteration"), 12
        )

        with tempfile.TemporaryDirectory() as directory:
            _, _, state_root, _ = initialize_bundle(
                self, directory, iteration=11, phase="verify"
            )
            before = marker(state_root)
            persisted = v234.transition_state_bundle(
                state_root,
                to_phase="repeat",
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                actor_run_id=OWNER_RUN,
                **state_proof(state_root),
            )
            self.assertFalse(persisted["ok"], persisted)
            self.assertNotEqual(persisted.get("run_outcome"), "achieved")
            self.assertEqual(marker(state_root)["bundle_revision"], before["bundle_revision"])
            self.assertEqual(marker(state_root)["loop"]["iteration"], 11)


if __name__ == "__main__":
    unittest.main()
