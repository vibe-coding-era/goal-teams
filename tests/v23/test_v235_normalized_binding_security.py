"""Security regressions for caller-supplied normalized V2.35 bindings.

An external caller must not be able to replace the trusted descriptor with a
self-authored normalized object and digest.  Public state and CLI entrypoints
must revalidate the exact current contract/review provenance before any write.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v23.common import ROOT, gt, task_event
from tests.v23.test_v234_reset_delivery import (
    RESET_AUTHORITY_RUN,
    create_candidate,
    refresh_authorization_scope,
    reset_authorization,
    reset_security_context,
)
from tests.v23.test_v234_state_loop import OWNER_RUN, require_v234, synthetic_contract_text


CLI = ROOT / "scripts" / "v23" / "goalteams_v23.py"
NORMALIZED_SCHEMA = "goal-teams-normalized-version-binding-v1"
CONTRACT_FIXTURE_PATH = (
    ROOT / "tests" / "v23" / "fixtures" / "v235" / "v2.35-contract.md"
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tree_digest(root: Path) -> str:
    entries: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append(
                    {"path": relative, "kind": "symlink", "target": os.readlink(path)}
                )
            elif path.is_file():
                entries.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "sha256": sha256_path(path),
                        "size": path.stat().st_size,
                    }
                )
            elif path.is_dir():
                entries.append({"path": relative, "kind": "dir"})
    return sha256_bytes(canonical_bytes(entries))


def forged_normalized_binding() -> dict[str, Any]:
    binding: dict[str, Any] = {
        "schema_version": NORMALIZED_SCHEMA,
        "explicit": True,
        "project_version": "V2.35",
        "release_version": "V2.35",
        "artifact_version": "V2.35-run2",
        "archive_prefix": "docs/archive/V2.35",
        "contract_ref": "spec/forged-v2.35-contract.md",
        "contract_sha256": "a" * 64,
        "contract_revision": 2,
        "review_ref": "reviews/forged-v2.35-review.json",
        "review_sha256": "b" * 64,
        "review_state": "passed",
        "contract_owner_run_id": "RUN-FORGED-CONTRACT-OWNER",
        "contract_validator_run_id": "RUN-FORGED-CONTRACT-VALIDATOR",
        "review_owner_run_id": "RUN-FORGED-REVIEW-OWNER",
        "review_validator_run_id": "RUN-FORGED-REVIEW-VALIDATOR",
    }
    binding["binding_digest"] = sha256_bytes(canonical_bytes(binding))
    return binding


def canonical_delta_contract() -> str:
    return CONTRACT_FIXTURE_PATH.read_text(encoding="utf-8")


def trusted_descriptor(repo: Path) -> dict[str, Any]:
    contract = repo / "spec" / "v2.35-contract.md"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(canonical_delta_contract(), encoding="utf-8")
    contract_sha = sha256_path(contract)
    review = repo / "reviews" / "v2.35-review.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    review_record = {
        "schema_version": "goal-teams-v2.35-binding-review-v1",
        "review_id": "REVIEW-V235-BINDING-SECURITY-TEST",
        "artifact_type": "v2.35_delta_contract",
        "state": "passed",
        "decision": "approved",
        "current": True,
        "owner_run_id": "RUN-V235-REVIEW-OWNER-SECURITY-TEST",
        "validator_run_id": "RUN-V235-REVIEW-VALIDATOR-SECURITY-TEST",
        "artifact_ref": "spec/v2.35-contract.md",
        "artifact_sha256": contract_sha,
        "contract_sha256": contract_sha,
        "contract_revision": 2,
        "reviewed_at": "2026-07-12T00:00:00Z",
    }
    review.write_bytes(canonical_bytes(review_record) + b"\n")
    return {
        "schema_version": "goal-teams-version-binding-v1",
        "project_version": "V2.35",
        "release_version": "V2.35",
        "artifact_version": "V2.35-run2",
        "contract_ref": "spec/v2.35-contract.md",
        "contract_sha256": contract_sha,
        "contract_revision": 2,
        "review_ref": "reviews/v2.35-review.json",
        "review_sha256": sha256_path(review),
        "review_state": "passed",
    }


def state_inputs(repo: Path) -> dict[str, Any]:
    contract = repo / "control-contract.md"
    contract.write_text(synthetic_contract_text(), encoding="utf-8")
    event = task_event(
        "EVT-V235-NORMALIZED-SECURITY-001",
        "TASK-V235-NORMALIZED-SECURITY",
        0,
        "planned",
        attempt_id="ATT-V235-NORMALIZED-SECURITY-001",
    )
    events = [event]
    checkpoint = gt.reduce_events(events, valid_evidence_ids=set(), evidence_registry={})
    checkpoint_bytes = canonical_bytes(checkpoint)
    ledger_binding = {
        "revision": 1,
        "prefix_sha256": gt.ledger_prefix_sha256(events, 1),
        "checkpoint_sha256": sha256_bytes(checkpoint_bytes),
        "last_event_id": event["event_id"],
    }
    paths = {
        "contract": contract,
        "ledger": repo / "ledger.jsonl",
        "checkpoint": repo / "checkpoint.json",
        "ledger_binding": repo / "ledger-binding.json",
    }
    paths["ledger"].write_bytes(canonical_bytes(event) + b"\n")
    paths["checkpoint"].write_bytes(checkpoint_bytes)
    paths["ledger_binding"].write_bytes(canonical_bytes(ledger_binding) + b"\n")
    return {
        "paths": paths,
        "events": events,
        "checkpoint": checkpoint,
        "checkpoint_bytes": checkpoint_bytes,
        "ledger_binding": ledger_binding,
    }


def initialize_trusted_state(
    test: unittest.TestCase, repo: Path, inputs: dict[str, Any]
) -> tuple[Any, Path, dict[str, Any]]:
    runtime = require_v234(test)
    descriptor = trusted_descriptor(repo)
    state_root = repo / "state"
    state_root.mkdir()
    result = runtime.initialize_state_bundle(
        state_root,
        repo_root=repo,
        loop_id="LOOP-V235-NORMALIZED-SECURITY",
        contract_path=inputs["paths"]["contract"],
        ledger_binding=inputs["ledger_binding"],
        actor_run_id=OWNER_RUN,
        ledger_events=inputs["events"],
        checkpoint_bytes=inputs["checkpoint_bytes"],
        version_binding=descriptor,
    )
    test.assertTrue(result["ok"], result)
    marker = runtime.load_state_bundle(state_root)
    binding = marker.get("version_binding")
    test.assertIsInstance(binding, dict)
    return runtime, state_root, dict(binding)


def invalidate_current_review(repo: Path) -> None:
    review = repo / "reviews" / "v2.35-review.json"
    record = json.loads(review.read_text(encoding="utf-8"))
    record["validator_run_id"] = record["owner_run_id"]
    review.write_bytes(canonical_bytes(record) + b"\n")


def initialize_explicit_reset_state(
    test: unittest.TestCase, repo: Path
) -> tuple[
    Any,
    Path,
    dict[str, Any],
    Path,
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
]:
    runtime = require_v234(test)
    state_root = repo / "GoalTeamsWork-V2.35" / "versions" / "V2.35-run2"
    state_root.mkdir(parents=True)
    control_contract = state_root / "contract.md"
    control_contract.write_text(synthetic_contract_text(), encoding="utf-8")
    candidate = create_candidate(repo, "candidate-v235")
    authorization = reset_authorization(repo, candidate)
    authorization["contract_sha256"] = sha256_path(control_contract)
    refresh_authorization_scope(authorization)
    identities, authorization_events = reset_security_context(authorization)

    planned = task_event(
        "EVT-V235-RESET-LEDGER-001",
        "TASK-V234-RESET",
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
        "EVT-V235-RESET-LEDGER-002",
        "TASK-V234-RESET",
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
        event["timestamp"] = f"2026-07-12T00:00:{index:02d}Z"
    checkpoint = gt.reduce_events(events, valid_evidence_ids=set(), evidence_registry={})
    test.assertEqual(checkpoint["conflicts"], [])
    checkpoint_bytes = canonical_bytes(checkpoint)
    initialized = runtime.initialize_state_bundle(
        state_root,
        repo_root=repo,
        loop_id="LOOP-V235-RESET",
        contract_path=control_contract,
        ledger_binding={
            "revision": len(events),
            "prefix_sha256": gt.ledger_prefix_sha256(events, len(events)),
            "checkpoint_sha256": sha256_bytes(checkpoint_bytes),
            "last_event_id": events[-1]["event_id"],
        },
        actor_run_id=OWNER_RUN,
        initial_loop={"iteration": 9, "attempt": 1, "phase": "reason"},
        ledger_events=events,
        checkpoint_bytes=checkpoint_bytes,
        version_binding=trusted_descriptor(repo),
    )
    test.assertTrue(initialized["ok"], initialized)
    bundle = json.loads((state_root / "feature_list.json").read_text(encoding="utf-8"))
    return (
        runtime,
        state_root,
        bundle,
        candidate,
        authorization,
        identities,
        events,
        checkpoint,
    )


def run_cli(*args: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"CLI did not return JSON: rc={completed.returncode} stdout={completed.stdout!r} "
            f"stderr={completed.stderr!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise AssertionError(f"CLI envelope must be an object: {payload!r}")
    return completed, payload


class V235NormalizedBindingSecurityTests(unittest.TestCase):
    def assert_binding_rejection(self, result: dict[str, Any]) -> None:
        self.assertFalse(result.get("ok"), result)
        self.assertRegex(str(result.get("error_code")), r"^E_V235_VERSION_BINDING_")
        self.assertEqual(result.get("mutation_count"), 0, result)

    def assert_cli_rejection(
        self, completed: subprocess.CompletedProcess[str], payload: dict[str, Any]
    ) -> None:
        self.assertNotEqual(completed.returncode, 0, payload)
        self.assert_binding_rejection(payload)

    def test_public_state_init_rejects_forged_normalized_binding_without_mutation(self) -> None:
        runtime = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            inputs = state_inputs(repo)
            before = tree_digest(repo)
            result = runtime.initialize_state_bundle(
                repo / "state",
                repo_root=repo,
                loop_id="LOOP-V235-FORGED-NORMALIZED-DIRECT",
                contract_path=inputs["paths"]["contract"],
                ledger_binding=inputs["ledger_binding"],
                actor_run_id=OWNER_RUN,
                ledger_events=inputs["events"],
                checkpoint_bytes=inputs["checkpoint_bytes"],
                version_binding=forged_normalized_binding(),
            )
            self.assertEqual(tree_digest(repo), before, result)
            self.assert_binding_rejection(result)

    def test_public_state_validate_revalidates_current_review_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            inputs = state_inputs(repo)
            runtime, state_root, normalized = initialize_trusted_state(self, repo, inputs)
            invalidate_current_review(repo)
            before = tree_digest(repo)
            result = runtime.validate_state_bundle(
                state_root, repo_root=repo, version_binding=normalized
            )
            self.assertEqual(tree_digest(repo), before, result)
            self.assert_binding_rejection(result)

    def test_public_state_validate_without_binding_revalidates_explicit_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            inputs = state_inputs(repo)
            runtime, state_root, _ = initialize_trusted_state(self, repo, inputs)
            invalidate_current_review(repo)
            before = tree_digest(repo)
            result = runtime.validate_state_bundle(state_root, repo_root=repo)
            self.assertEqual(tree_digest(repo), before, result)
            self.assert_binding_rejection(result)

    def test_state_transition_without_binding_rejects_stale_explicit_marker_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            inputs = state_inputs(repo)
            runtime, state_root, _ = initialize_trusted_state(self, repo, inputs)
            ready = runtime.validate_state_bundle(
                state_root,
                ledger_events=inputs["events"],
                checkpoint=inputs["checkpoint"],
                repo_root=repo,
            )
            self.assertTrue(ready["ok"], ready)
            self.assertEqual(ready["state"], "valid", ready)
            marker = ready["marker"]
            invalidate_current_review(repo)
            before = tree_digest(repo)
            result = runtime.transition_state_bundle(
                state_root,
                to_phase="reason",
                expected_bundle_revision=marker["bundle_revision"],
                expected_bundle_digest=marker["bundle_digest"],
                actor_run_id=OWNER_RUN,
                ledger_events=inputs["events"],
                checkpoint=inputs["checkpoint"],
                repo_root=repo,
            )
            self.assertEqual(tree_digest(repo), before, result)
            self.assertFalse(result.get("ok"), result)
            self.assertIn(
                result.get("error_code"),
                {"E_V234_STATE_INVALID", "E_V235_VERSION_BINDING_PROVENANCE", "E_V235_VERSION_BINDING_REVIEW"},
                result,
            )

    def test_explicit_iteration_nine_reset_revalidates_review_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (
                runtime,
                state_root,
                bundle,
                candidate,
                authorization,
                identities,
                events,
                checkpoint,
            ) = initialize_explicit_reset_state(self, repo)
            planned = runtime.plan_controlled_reset(
                bundle,
                candidate.name,
                authorization,
                repo_root=repo,
                state_root=state_root,
                identity_registry=identities,
                ledger_events=events,
            )
            self.assertTrue(planned["ok"], planned)
            applied = runtime.apply_controlled_reset(
                bundle,
                planned["plan"],
                authorization,
                repo_root=repo,
                state_root=state_root,
                actor_run_id=OWNER_RUN,
                identity_registry=identities,
                ledger_events=events,
                checkpoint=checkpoint,
            )
            self.assertTrue(applied["ok"], applied)
            self.assertFalse(candidate.exists())
            self.assertEqual(
                json.loads((state_root / "feature_list.json").read_text(encoding="utf-8"))[
                    "project_version"
                ],
                "V2.35",
            )

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (
                runtime,
                state_root,
                bundle,
                candidate,
                authorization,
                identities,
                events,
                checkpoint,
            ) = initialize_explicit_reset_state(self, repo)
            planned = runtime.plan_controlled_reset(
                bundle,
                candidate.name,
                authorization,
                repo_root=repo,
                state_root=state_root,
                identity_registry=identities,
                ledger_events=events,
            )
            self.assertTrue(planned["ok"], planned)
            invalidate_current_review(repo)
            before = tree_digest(repo)
            rejected = runtime.apply_controlled_reset(
                bundle,
                planned["plan"],
                authorization,
                repo_root=repo,
                state_root=state_root,
                actor_run_id=OWNER_RUN,
                identity_registry=identities,
                ledger_events=events,
                checkpoint=checkpoint,
            )
            self.assertEqual(tree_digest(repo), before, rejected)
            self.assertFalse(rejected.get("ok"), rejected)
            self.assertEqual(rejected.get("mutation_count"), 0, rejected)

    def test_cli_state_init_rejects_forged_normalized_binding_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            inputs = state_inputs(repo)
            binding_path = repo / "forged-normalized-binding.json"
            binding_path.write_bytes(canonical_bytes(forged_normalized_binding()) + b"\n")
            before = tree_digest(repo)
            completed, payload = run_cli(
                "v234-state-init",
                str(repo / "state"),
                "--repo-root",
                str(repo),
                "--loop-id",
                "LOOP-V235-FORGED-NORMALIZED-CLI",
                "--contract",
                str(inputs["paths"]["contract"]),
                "--ledger-binding",
                str(inputs["paths"]["ledger_binding"]),
                "--ledger",
                str(inputs["paths"]["ledger"]),
                "--checkpoint",
                str(inputs["paths"]["checkpoint"]),
                "--actor-run-id",
                OWNER_RUN,
                "--version-binding",
                str(binding_path),
            )
            self.assertEqual(tree_digest(repo), before, payload)
            self.assert_cli_rejection(completed, payload)

    def test_cli_state_validate_revalidates_current_review_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            inputs = state_inputs(repo)
            _, state_root, normalized = initialize_trusted_state(self, repo, inputs)
            invalidate_current_review(repo)
            binding_path = repo / "stale-normalized-binding.json"
            binding_path.write_bytes(canonical_bytes(normalized) + b"\n")
            before = tree_digest(repo)
            completed, payload = run_cli(
                "v234-state-validate",
                str(state_root),
                "--repo-root",
                str(repo),
                "--version-binding",
                str(binding_path),
            )
            self.assertEqual(tree_digest(repo), before, payload)
            self.assert_cli_rejection(completed, payload)


if __name__ == "__main__":
    unittest.main()
