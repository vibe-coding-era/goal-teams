"""V2.34 four-file crash consistency and recovery TDD tests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import gt, task_event
from tests.v23.test_v234_state_loop import (
    OWNER_RUN,
    assert_error_code,
    canonical_hash,
    initialize_bundle,
    marker,
    require_v234,
    state_proof,
    synthetic_contract_text,
)


class InjectedCrash(RuntimeError):
    pass


def write_legacy_bundle(state_root: Path) -> tuple[dict[str, bytes], str]:
    """Write the exact four pre-marker legacy files and return their digest."""
    state_root.mkdir(parents=True, exist_ok=True)
    files = {
        "contract.md": synthetic_contract_text().encode("utf-8"),
        "feature_list.json": json.dumps(
            {
                "schema_version": "goal-teams-v2.34-legacy-input-v1",
                "features": [{"feature_id": "FEAT-V234-LEGACY", "status": "planned"}],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n",
        "progress.md": b"# Legacy progress\n\nHuman-authored progress is not verified state.\n",
        "log.md": b"# Legacy log\n\nHuman-authored notes are preserved by digest only.\n",
    }
    for name, data in files.items():
        (state_root / name).write_bytes(data)
    records = [
        {
            "path": name,
            "sha256": hashlib.sha256(files[name]).hexdigest(),
            "size": len(files[name]),
        }
        for name in sorted(files)
    ]
    return files, canonical_hash(records)


def minimal_ledger_replay() -> tuple[list[dict], bytes, dict]:
    event = task_event(
        "EVT-V234-LEGACY-001",
        "TASK-V234-LEGACY",
        0,
        "planned",
        attempt_id="ATT-V234-LEGACY-01",
    )
    events = [event]
    checkpoint_value = gt.reduce_events(
        events, valid_evidence_ids=set(), evidence_registry={}
    )
    if checkpoint_value.get("conflicts"):
        raise AssertionError(f"legacy ledger fixture is invalid: {checkpoint_value}")
    checkpoint = json.dumps(
        checkpoint_value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    binding = {
        "revision": 1,
        "prefix_sha256": gt.ledger_prefix_sha256(events, 1),
        "checkpoint_sha256": hashlib.sha256(checkpoint).hexdigest(),
        "last_event_id": event["event_id"],
    }
    return events, checkpoint, binding


class V234RecoveryCrashTests(unittest.TestCase):
    def test_missing_each_recovery_file_fails_closed(self) -> None:
        """ASSERT-V234-011"""
        for missing in ("feature_list.json", "progress.md", "contract.md", "log.md"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                v234, _, state_root, _ = initialize_bundle(self, directory)
                target = state_root / missing
                target.unlink()
                result = v234.validate_state_bundle(state_root)
                self.assertIn(result["state"], {"reconcile_required", "blocked"}, result)
                self.assertFalse(target.exists(), "validation must not silently recreate facts")
                transition = v234.transition_state_bundle(
                    state_root,
                    to_phase="reason",
                    expected_bundle_revision=1,
                    expected_bundle_digest="0" * 64,
                    actor_run_id=OWNER_RUN,
                    **state_proof(state_root),
                )
                self.assertFalse(transition["ok"], transition)
                self.assertFalse(target.exists(), "failed transition must have zero repair writes")

    def test_bundle_cross_file_and_checkpoint_binding(self) -> None:
        """ASSERT-V234-012"""
        mutations = {
            "progress.md": lambda path: path.write_text(
                path.read_text(encoding="utf-8") + "\nmanual drift\n", encoding="utf-8"
            ),
            "contract.md": lambda path: path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "deterministic assertion 001", "mutated assertion 001", 1
                ),
                encoding="utf-8",
            ),
            "log.md": lambda path: path.write_text(
                path.read_text(encoding="utf-8") + "GTLOG {}\n", encoding="utf-8"
            ),
            "feature_list.json": self._drift_checkpoint,
        }
        for filename, mutate in mutations.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                v234, _, state_root, _ = initialize_bundle(self, directory)
                mutate(state_root / filename)
                result = v234.validate_state_bundle(state_root)
                self.assertNotEqual(result["state"], "valid", result)
                self.assertTrue(result["errors"], result)

    @staticmethod
    def _drift_checkpoint(path: Path) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        value["ledger"]["checkpoint_sha256"] = "d" * 64
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def test_crash_matrix_commit_marker_last(self) -> None:
        """ASSERT-V234-013"""
        for crash_target in ("log.md", "progress.md", "feature_list.json"):
            with self.subTest(crash_target=crash_target), tempfile.TemporaryDirectory() as directory:
                v234, _, state_root, _ = initialize_bundle(self, directory)
                before = marker(state_root)
                real_replace = os.replace
                destinations: list[str] = []

                def crash_at_target(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
                    name = Path(destination).name
                    if name in {"contract.md", "log.md", "progress.md", "feature_list.json"}:
                        destinations.append(name)
                    if name == crash_target:
                        raise InjectedCrash(crash_target)
                    real_replace(source, destination)

                with mock.patch.object(v234.os, "replace", side_effect=crash_at_target):
                    with self.assertRaises(InjectedCrash):
                        v234.transition_state_bundle(
                            state_root,
                            to_phase="reason",
                            expected_bundle_revision=before["bundle_revision"],
                            expected_bundle_digest=before["bundle_digest"],
                            actor_run_id=OWNER_RUN,
                            **state_proof(state_root),
                        )

                self.assertEqual(destinations[-1], crash_target)
                if "feature_list.json" in destinations:
                    self.assertEqual(destinations[-1], "feature_list.json")
                after_marker = marker(state_root)
                self.assertEqual(after_marker["bundle_revision"], before["bundle_revision"])
                recovery = v234.validate_state_bundle(state_root)
                self.assertIn(
                    recovery["state"],
                    {"recoverable_pending", "reconcile_required", "blocked"},
                    recovery,
                )
                self.assertNotEqual(recovery["state"], "valid")

    def test_reconcile_never_selects_max_revision(self) -> None:
        """ASSERT-V234-015"""
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, _ = initialize_bundle(self, directory)
            forged = marker(state_root)
            forged["bundle_revision"] = 999
            forged["bundle_digest"] = "f" * 64
            (state_root / "feature_list.json").write_text(
                json.dumps(forged, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )
            validation = v234.validate_state_bundle(state_root)
            self.assertEqual(validation["state"], "reconcile_required", validation)
            result = v234.reconcile_state_bundle(
                state_root,
                mode="auto",
                expected_bundle_revision=999,
                expected_bundle_digest="f" * 64,
            )
            assert_error_code(self, result, "E_V234_RECONCILE_EVIDENCE")
            self.assertEqual(marker(state_root)["bundle_revision"], 999)

        # Legacy adoption is a recovery operation, not a trust upgrade.  It is
        # accepted only for the exact four-file byte digest plus a replayable
        # V2.3 ledger/checkpoint pair, and the receipt must preserve the exact
        # pre-adoption hashes without projecting human prose as verified state.
        with self.subTest(case="legacy_exact_adoption"), tempfile.TemporaryDirectory() as directory:
            v234 = require_v234(self)
            repo_root = Path(directory)
            state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
            legacy_files, legacy_digest = write_legacy_bundle(state_root)
            events, checkpoint, binding = minimal_ledger_replay()

            missing_opt_in = v234.initialize_state_bundle(
                state_root,
                repo_root=repo_root,
                loop_id="LOOP-V234-LEGACY",
                contract_path=state_root / "contract.md",
                ledger_binding=binding,
                actor_run_id=OWNER_RUN,
                ledger_events=events,
                checkpoint_bytes=checkpoint,
            )
            assert_error_code(self, missing_opt_in, "E_V234_LEGACY_ADOPTION_REQUIRED")

            wrong_digest = v234.initialize_state_bundle(
                state_root,
                repo_root=repo_root,
                loop_id="LOOP-V234-LEGACY",
                contract_path=state_root / "contract.md",
                ledger_binding=binding,
                actor_run_id=OWNER_RUN,
                adopt_legacy_digest="0" * 64,
                ledger_events=events,
                checkpoint_bytes=checkpoint,
            )
            assert_error_code(self, wrong_digest, "E_V234_LEGACY_DIGEST")

            bad_replay = v234.initialize_state_bundle(
                state_root,
                repo_root=repo_root,
                loop_id="LOOP-V234-LEGACY",
                contract_path=state_root / "contract.md",
                ledger_binding={**binding, "prefix_sha256": "f" * 64},
                actor_run_id=OWNER_RUN,
                adopt_legacy_digest=legacy_digest,
                ledger_events=events,
                checkpoint_bytes=checkpoint,
            )
            assert_error_code(self, bad_replay, "E_V234_LEGACY_LEDGER_REPLAY")

            checkpoint_value = json.loads(checkpoint.decode("utf-8"))
            checkpoint_mutations = {
                "event_digests": lambda value: value["event_digests"].update(
                    {events[0]["event_id"]: "0" * 64}
                ),
                "tasks": lambda value: value["tasks"].clear(),
                "ledger_owner": lambda value: value.__setitem__(
                    "ledger_owner_run_id", "RUN-FORGED-LEDGER-OWNER"
                ),
                "schema_hash": lambda value: value.__setitem__(
                    "schema_source_hash", "0" * 64
                ),
            }
            for name, mutate in checkpoint_mutations.items():
                with tempfile.TemporaryDirectory() as forged_directory:
                    forged_repo = Path(forged_directory)
                    forged_state = (
                        forged_repo
                        / "GoalTeamsWork-V2.34"
                        / "versions"
                        / "V2.34"
                    )
                    _, forged_legacy_digest = write_legacy_bundle(forged_state)
                    forged_checkpoint = json.loads(json.dumps(checkpoint_value))
                    mutate(forged_checkpoint)
                    forged_bytes = json.dumps(
                        forged_checkpoint,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    forged_binding = {
                        **binding,
                        "checkpoint_sha256": hashlib.sha256(forged_bytes).hexdigest(),
                    }
                    forged_result = v234.initialize_state_bundle(
                        forged_state,
                        repo_root=forged_repo,
                        loop_id=f"LOOP-V234-LEGACY-FORGED-{name}",
                        contract_path=forged_state / "contract.md",
                        ledger_binding=forged_binding,
                        actor_run_id=OWNER_RUN,
                        adopt_legacy_digest=forged_legacy_digest,
                        ledger_events=events,
                        checkpoint_bytes=forged_bytes,
                    )
                    with self.subTest(checkpoint_mutation=name):
                        assert_error_code(
                            self, forged_result, "E_V234_LEGACY_LEDGER_REPLAY"
                        )

            adopted = v234.initialize_state_bundle(
                state_root,
                repo_root=repo_root,
                loop_id="LOOP-V234-LEGACY",
                contract_path=state_root / "contract.md",
                ledger_binding=binding,
                actor_run_id=OWNER_RUN,
                adopt_legacy_digest=legacy_digest,
                ledger_events=events,
                checkpoint_bytes=checkpoint,
            )
            self.assertTrue(adopted["ok"], adopted)
            self.assertTrue(adopted["legacy_imported"])
            receipt_path = Path(adopted["legacy_import_receipt"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["legacy_import"]["legacy_digest"], legacy_digest)
            expected_hashes = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in legacy_files.items()
            }
            self.assertEqual(
                {item["path"]: item["sha256"] for item in receipt["legacy_import"]["files"]},
                expected_hashes,
            )
            self.assertNotIn("accepted", receipt["legacy_import"])
            self.assertNotIn("passed", receipt["legacy_import"])
            self.assertTrue(v234.validate_state_bundle(state_root)["ok"])

        with self.subTest(case="legacy_derived_state_rejected"), tempfile.TemporaryDirectory() as directory:
            v234 = require_v234(self)
            repo_root = Path(directory)
            state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
            _, _ = write_legacy_bundle(state_root)
            forged = json.loads((state_root / "feature_list.json").read_text(encoding="utf-8"))
            forged["implementation_gate"] = True
            (state_root / "feature_list.json").write_text(
                json.dumps(forged, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            records = [
                {
                    "path": name,
                    "sha256": hashlib.sha256((state_root / name).read_bytes()).hexdigest(),
                    "size": (state_root / name).stat().st_size,
                }
                for name in sorted(("feature_list.json", "progress.md", "contract.md", "log.md"))
            ]
            events, checkpoint, binding = minimal_ledger_replay()
            result = v234.initialize_state_bundle(
                state_root,
                repo_root=repo_root,
                loop_id="LOOP-V234-LEGACY-FORGED",
                contract_path=state_root / "contract.md",
                ledger_binding=binding,
                actor_run_id=OWNER_RUN,
                adopt_legacy_digest=canonical_hash(records),
                ledger_events=events,
                checkpoint_bytes=checkpoint,
            )
            assert_error_code(self, result, "E_V234_LEGACY_DERIVED_STATE")

        with self.subTest(case="legacy_crash_divergent_bytes"), tempfile.TemporaryDirectory() as directory:
            v234 = require_v234(self)
            repo_root = Path(directory)
            state_root = repo_root / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
            _, legacy_digest = write_legacy_bundle(state_root)
            events, checkpoint, binding = minimal_ledger_replay()
            real_replace = os.replace

            def crash_before_marker(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
                if Path(destination).name == "feature_list.json":
                    raise InjectedCrash("legacy marker")
                real_replace(source, destination)

            with mock.patch.object(v234.os, "replace", side_effect=crash_before_marker):
                with self.assertRaises(InjectedCrash):
                    v234.initialize_state_bundle(
                        state_root,
                        repo_root=repo_root,
                        loop_id="LOOP-V234-LEGACY-CRASH",
                        contract_path=state_root / "contract.md",
                        ledger_binding=binding,
                        actor_run_id=OWNER_RUN,
                        adopt_legacy_digest=legacy_digest,
                        ledger_events=events,
                        checkpoint_bytes=checkpoint,
                    )
            validation = v234.validate_state_bundle(state_root)
            self.assertIn(validation["state"], {"reconcile_required", "blocked"}, validation)
            receipts = list((state_root / ".goalteams-state" / "receipts").glob("legacy-import-*.json"))
            self.assertEqual(receipts, [], "crashed adoption must not mint provenance")

    def test_gtlog_append_only_chain_mutations(self) -> None:
        """ASSERT-V234-016"""
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, _ = initialize_bundle(self, directory)
            first_marker = marker(state_root)
            event = {
                "event_id": "LOG-V234-TEST-002",
                "event_type": "INTENT",
                "bundle_revision": first_marker["bundle_revision"] + 1,
                "iteration": 1,
                "attempt": 1,
                "phase": "gather",
                "actor_run_id": OWNER_RUN,
                "timestamp": "2026-07-11T08:00:00Z",
                "intent_id": "INTENT-V234-001",
                "expected_constraints": ["ASSERT-V234-016"],
                "allowed_outcomes": ["partial"],
                "action_scope": ["tests/v23"],
                "prompt_ref": "prompts/lead/loop.md",
                "prompt_sha256": "a" * 64,
                "assertion_refs": ["ASSERT-V234-016"],
            }
            appended = v234.append_log_event(
                state_root,
                event,
                expected_bundle_revision=first_marker["bundle_revision"],
                expected_bundle_digest=first_marker["bundle_digest"],
                **state_proof(state_root),
            )
            self.assertTrue(appended["ok"], appended)
            duplicate = v234.append_log_event(
                state_root,
                event,
                expected_bundle_revision=appended["bundle_revision"],
                expected_bundle_digest=appended["bundle_digest"],
                **state_proof(state_root),
            )
            assert_error_code(self, duplicate, "E_V234_LOG_DUPLICATE_ID")

            log_path = state_root / "log.md"
            original = log_path.read_bytes()
            log_path.write_bytes(original[:-1])
            truncated = v234.validate_state_bundle(state_root)
            self.assertNotEqual(truncated["state"], "valid")
            self.assertTrue(
                any("LOG" in str(error) or "DIGEST" in str(error) for error in truncated["errors"]),
                truncated,
            )


if __name__ == "__main__":
    unittest.main()
