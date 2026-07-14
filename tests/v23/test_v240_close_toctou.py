from __future__ import annotations

import copy
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT


def _load_release_module():
    path = ROOT / "scripts" / "release" / "release.py"
    spec = importlib.util.spec_from_file_location("goal_teams_v240_close_toctou", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = _load_release_module()
CANDIDATE = "b" * 40
STATE_SHA256 = "a" * 64


def _exact_readback(source: str, details: dict[str, object]) -> dict[str, object]:
    return {
        "classification": "exact",
        "source": source,
        "observed_at": "2026-07-15T00:00:00Z",
        "state_sha256": RELEASE._canonical_json_sha256(details),
        "details": details,
        "external_side_effect_count": 1 if source == "github_api" else 0,
    }


def _intent(operation_id: str, action: str) -> dict[str, object]:
    value: dict[str, object] = {
        "intent_id": "INT-" + operation_id.replace(".", "-").upper(),
        "operation_id": operation_id,
        "action": action,
        "idempotency_key": hashlib.sha256(operation_id.encode()).hexdigest(),
        "inputs_sha256": hashlib.sha256(action.encode()).hexdigest(),
        "created_at": "2026-07-15T00:00:00Z",
    }
    if action == "promotion_lock_finalize":
        value["expected_before"] = {
            "ruleset_id": 24018,
            "ruleset_name": "goal-teams-promotion-lock-V2.40-bbbbbbbb",
        }
    return value


def _cp18_state(stored_audit: dict[str, object]) -> dict[str, object]:
    finalize = _intent("CP18.promotion_lock_finalize", "promotion_lock_finalize")
    archive = _intent("CP18.archive_close", "archive_close")
    return {
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.40",
        "tag": "v2.40",
        "base_main_commit": "c" * 40,
        "candidate_commit": CANDIDATE,
        "phase": "INSTALLED_VERIFIED",
        "current_checkpoint": "CP18",
        "checkpoints": {
            "CP17": {
                "operations": [
                    {
                        "operation_id": "CP17.independent_audit",
                        "readback": {
                            "details": {"audit_receipt": stored_audit},
                        },
                    }
                ]
            },
            "CP18": {
                "checkpoint_id": "CP18",
                "candidate_commit": CANDIDATE,
                "status": "pending",
                "operations": [
                    {
                        "operation_id": finalize["operation_id"],
                        "sequence": 1,
                        "status": "pending",
                        "intent": finalize,
                    },
                    {
                        "operation_id": archive["operation_id"],
                        "sequence": 2,
                        "status": "pending",
                        "intent": archive,
                    },
                ],
            },
        },
    }


def _authorizations(state: dict[str, object]) -> dict[str, dict[str, object]]:
    checkpoint = state["checkpoints"]["CP18"]  # type: ignore[index]
    operations = checkpoint["operations"]  # type: ignore[index]
    result: dict[str, dict[str, object]] = {}
    for operation in operations:  # type: ignore[assignment]
        intent = operation["intent"]
        operation_id = str(operation["operation_id"])
        result[operation_id] = {
            "intent_sha256": RELEASE._canonical_json_sha256(intent),
            "expected_before": intent.get("expected_before"),
            "mode": (
                "execute_github"
                if operation_id == "CP18.promotion_lock_finalize"
                else "execute_local"
            ),
            "parameters": {},
        }
    return result


def _tag_ruleset() -> dict[str, object]:
    return {
        "name": "goal-teams-tag-protection-v2.40",
        "target": "tag",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {"include": ["refs/tags/v2.40"], "exclude": []}
        },
        "rules": [{"type": "deletion"}, {"type": "update"}],
    }


class _FinalizerAdapter:
    def __init__(self, mutate_after_finalize):
        self._mutate_after_finalize = mutate_after_finalize
        self.finalize_calls = 0
        self.ruleset = _tag_ruleset()

    def observe(self, **_kwargs):
        return _exact_readback("github_api", {"enabled": True})

    def execute(self, *, action: str, **_kwargs):
        if action != "promotion_lock_finalize":
            raise AssertionError(f"unexpected external action: {action}")
        self.finalize_calls += 1
        self._mutate_after_finalize()
        return _exact_readback(
            "github_api",
            {
                "ruleset_name": "goal-teams-main-protection",
                "ruleset_sha256": "d" * 64,
            },
        )

    def _ruleset_by_name(self, _name: str):
        return copy.deepcopy(self.ruleset)

    def _validate_ruleset_payload(self, _action: str, _payload):
        return None

    def _release_json(self):
        return {"isImmutable": True}


class V240CloseToctouTests(unittest.TestCase):
    def _assert_post_finalize_drift_blocks_closed(self, scenario: str) -> None:
        with tempfile.TemporaryDirectory(prefix=f"v240-close-toctou-{scenario}-") as directory:
            workspace = Path(directory)
            docs = workspace / "docs"
            archive_root = docs / "archive" / "releases" / "V2.40"
            archive_root.mkdir(parents=True)
            archive_file = archive_root / "release-evidence.json"
            archive_file.write_bytes(b"trusted-archive-byte\n")
            archive_digest = RELEASE._sha256_file(archive_file)

            tracked_file = workspace / "tracked-release-state.txt"
            tracked_file.write_bytes(b"clean-main\n")
            tracked_digest = RELEASE._sha256_file(tracked_file)
            candidate = workspace / "develops" / "v2.40"
            registered_worktrees: set[Path] = set()

            fresh_audit = {
                "passed": True,
                "source_commit": CANDIDATE,
                "version": "V2.40",
                "independent": True,
            }
            stored_audit = {
                **fresh_audit,
                "goal_teams_work_tree": {
                    "tree_sha256": "e" * 64,
                    "file_count": 1,
                    "rows_sha256": "f" * 64,
                },
            }
            state = _cp18_state(stored_audit)
            state_path = docs / "release-state" / "V2.40" / "promotion-state.json"
            state_path.parent.mkdir(parents=True)

            def mutate_after_finalize() -> None:
                if scenario == "archive_byte_drift":
                    data = bytearray(archive_file.read_bytes())
                    data[0] ^= 1
                    archive_file.write_bytes(bytes(data))
                elif scenario == "candidate_recreated_or_registered":
                    candidate.mkdir(parents=True)
                    registered_worktrees.add(candidate.resolve())
                elif scenario == "canonical_root_dirty":
                    tracked_file.write_bytes(b"dirty-main\n")
                else:  # pragma: no cover - the table below is closed
                    raise AssertionError(f"unknown scenario: {scenario}")

            boundary_calls = 0

            def validate_fresh_boundary(_state, audit_receipt, _config):
                nonlocal boundary_calls
                boundary_calls += 1
                if RELEASE._sha256_file(archive_file) != archive_digest:
                    RELEASE._fail(
                        "E_V240_CLOSE_ARCHIVE",
                        "archive bytes changed after promotion lock finalization",
                    )
                if candidate.exists() or candidate.resolve() in registered_worktrees:
                    RELEASE._fail(
                        "E_V240_CLOSE_WORKTREE",
                        "candidate worktree reappeared after boundary validation",
                    )
                if RELEASE._sha256_file(tracked_file) != tracked_digest:
                    RELEASE._fail(
                        "E_V240_CLOSE_WORKTREE",
                        "canonical root became dirty after boundary validation",
                    )
                body = {
                    "passed": True,
                    "candidate_commit": CANDIDATE,
                    "audit_receipt_sha256": RELEASE._canonical_json_sha256(
                        audit_receipt
                    ),
                    "cleanup_verified": True,
                    "candidate_worktree_absent": True,
                    "candidate_worktree_entry_absent": True,
                    "scanner_receipt_sha256": "1" * 64,
                    "ssot_receipt_sha256": "2" * 64,
                }
                return {**body, "receipt_sha256": RELEASE._canonical_json_sha256(body)}

            adapter = _FinalizerAdapter(mutate_after_finalize)

            def operation_details(_state, checkpoint_id: str, operation_id: str):
                if (checkpoint_id, operation_id) == (
                    "CP17",
                    "CP17.independent_audit",
                ):
                    return {"audit_receipt": stored_audit}
                if (checkpoint_id, operation_id) == (
                    "CP14",
                    "CP14.tag_ruleset",
                ):
                    return {"ruleset": adapter.ruleset}
                raise AssertionError(
                    f"unexpected operation detail lookup: {checkpoint_id}/{operation_id}"
                )

            config = {
                "state_path": str(state_path),
                "expected_state_sha256": STATE_SHA256,
                "archive_index_path": str(archive_root / "close.json"),
                "execute_external_writes": True,
                "operation_authorizations": _authorizations(state),
            }
            immutable_operation = {"intent": {"expected_before": {}}}

            with (
                mock.patch.object(RELEASE, "_workspace_root", return_value=workspace),
                mock.patch.object(
                    RELEASE,
                    "_load_state_cas",
                    return_value=(state_path, state, STATE_SHA256),
                ),
                mock.patch.object(RELEASE, "_verify_frozen_git_identity"),
                mock.patch.object(
                    RELEASE,
                    "collect_live_audit_observation",
                    return_value={"source_commit": CANDIDATE},
                ),
                mock.patch.object(
                    RELEASE, "_run_independent_audit", return_value=fresh_audit
                ),
                mock.patch.object(
                    RELEASE,
                    "_operation_details",
                    side_effect=operation_details,
                ),
                mock.patch.object(
                    RELEASE,
                    "_checkpoint_operation",
                    return_value=immutable_operation,
                ),
                mock.patch.object(
                    RELEASE, "_validate_close_local_boundary", side_effect=validate_fresh_boundary
                ),
                mock.patch.object(
                    RELEASE, "_github_adapter_for_state", return_value=adapter
                ),
                mock.patch.object(
                    RELEASE,
                    "_atomic_state_write",
                    return_value="3" * 64,
                ),
                mock.patch.object(
                    RELEASE,
                    "validate_promotion_state",
                    return_value={"passed": True},
                ),
            ):
                with self.assertRaises(RELEASE.PolicyError) as caught:
                    RELEASE.close_release(config)

            expected_code = (
                "E_V240_CLOSE_ARCHIVE"
                if scenario == "archive_byte_drift"
                else "E_V240_CLOSE_WORKTREE"
            )
            self.assertEqual(caught.exception.receipt["error_code"], expected_code)
            self.assertEqual(adapter.finalize_calls, 1)
            self.assertGreaterEqual(
                boundary_calls,
                2,
                "archive_close must recompute the local boundary after finalization",
            )
            self.assertNotEqual(state.get("phase"), "CLOSED")
            self.assertNotEqual(
                state["checkpoints"]["CP18"].get("status"),  # type: ignore[index]
                "passed",
            )

    def test_archive_byte_drift_between_finalize_and_archive_close_is_rejected(self) -> None:
        self._assert_post_finalize_drift_blocks_closed("archive_byte_drift")

    def test_candidate_recreation_or_registration_before_archive_close_is_rejected(
        self,
    ) -> None:
        self._assert_post_finalize_drift_blocks_closed(
            "candidate_recreated_or_registered"
        )

    def test_canonical_root_dirty_before_archive_close_is_rejected(self) -> None:
        self._assert_post_finalize_drift_blocks_closed("canonical_root_dirty")


if __name__ == "__main__":
    unittest.main()
