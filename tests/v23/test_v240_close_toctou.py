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


def _sealed_audit(**updates: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "passed": True,
        "mutation_count": 0,
        "external_side_effect_count": 0,
        "source_commit": CANDIDATE,
        "version": "V2.40",
        "independent": True,
        "release_actor_id": 240,
    }
    receipt.update(updates)
    receipt["receipt_sha256"] = RELEASE._canonical_json_sha256(receipt)
    return receipt


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
            "ruleset_name": "goal-teams-main-protection",
        }
    return value


def _cp18_state(stored_audit: dict[str, object]) -> dict[str, object]:
    finalize = _intent("CP18.promotion_lock_finalize", "promotion_lock_finalize")
    archive = _intent("CP18.archive_close", "archive_close")
    state = {
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.40",
        "tag": "v2.40",
        "base_main_commit": "c" * 40,
        "candidate_commit": CANDIDATE,
        "github_authority": {"actor_id": 240},
        "phase": "INSTALLED_VERIFIED",
        "current_checkpoint": "CP18",
        "checkpoints": {
            "CP17": {
                "operations": [
                    {
                        "operation_id": "CP17.independent_audit",
                        "readback": _exact_readback(
                            "github_api", {"audit_receipt": stored_audit}
                        ),
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
    for operation in state["checkpoints"]["CP18"]["operations"]:  # type: ignore[index]
        intent = operation["intent"]
        expected_before = intent.get("expected_before")
        parameters = RELEASE._bound_operation_parameters(
            state,
            operation["operation_id"],
            intent["action"],
            expected_before,
        )
        intent["parameters_sha256"] = RELEASE._canonical_json_sha256(parameters)
        intent["expected_after_sha256"] = RELEASE._canonical_json_sha256(
            RELEASE._expected_after_descriptor(
                state,
                operation["operation_id"],
                intent["action"],
                expected_before,
                parameters,
            )
        )
    return state


def _authorizations(state: dict[str, object]) -> dict[str, dict[str, object]]:
    checkpoint = state["checkpoints"]["CP18"]  # type: ignore[index]
    operations = checkpoint["operations"]  # type: ignore[index]
    result: dict[str, dict[str, object]] = {}
    for operation in operations:  # type: ignore[assignment]
        intent = operation["intent"]
        operation_id = str(operation["operation_id"])
        expected_before = intent.get("expected_before")
        parameters = RELEASE._bound_operation_parameters(
            state,
            operation_id,
            intent["action"],
            expected_before,
        )
        result[operation_id] = {
            "intent_sha256": RELEASE._canonical_json_sha256(intent),
            "expected_before": expected_before,
            "parameters_sha256": intent.get("parameters_sha256"),
            "expected_after_sha256": intent.get("expected_after_sha256"),
            "mode": (
                "execute_github"
                if operation_id == "CP18.promotion_lock_finalize"
                else "execute_local"
            ),
            "parameters": parameters,
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
        "rules": [
            {"type": "deletion"},
            {
                "type": "update",
                "parameters": {"update_allows_fetch_and_merge": False},
            },
        ],
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
        payload = RELEASE._final_main_ruleset_payload(240)
        return _exact_readback(
            "github_api",
            {
                "ruleset_id": 24018,
                "ruleset_name": payload["name"],
                "ruleset_sha256": RELEASE._ruleset_payload_sha256(payload),
                "ruleset": payload,
            },
        )

    def _ruleset_by_name(self, _name: str):
        return copy.deepcopy(self.ruleset)

    def _validate_ruleset_payload(self, _action: str, _payload):
        return None

    def _release_json(self):
        return {
            "isDraft": False,
            "isImmutable": True,
            "isPrerelease": False,
            "tagName": "v2.40",
            "targetCommitish": CANDIDATE,
            "resolvedTargetCommit": CANDIDATE,
            "name": "Goal Teams V2.40",
            "body": "Goal Teams V2.40. See release/current/README.md in the tagged source.",
        }


class V240CloseToctouTests(unittest.TestCase):
    def test_cp17_audit_rejects_ssot_or_candidate_host_authority_fields(self) -> None:
        state = {"candidate_commit": CANDIDATE, "version": "V2.40"}
        for field in sorted(RELEASE.FORBIDDEN_CP17_AUDIT_SSOT_FIELDS):
            receipt = _sealed_audit()
            receipt[field] = {"forged": True}
            receipt.pop("receipt_sha256")
            receipt["receipt_sha256"] = RELEASE._canonical_json_sha256(receipt)
            with self.subTest(field=field), self.assertRaises(
                RELEASE.PolicyError
            ) as caught:
                RELEASE._validate_cp17_audit_receipt(
                    state,
                    receipt,
                    error_code="E_V240_AUDIT",
                )
            self.assertEqual(caught.exception.receipt["error_code"], "E_V240_AUDIT")

        nested_candidate_input = {
            "operation_authorizations": {
                "CP18.archive_close": {
                    "parameters": {"host_receipt": {"passed": True}}
                }
            }
        }
        with self.assertRaises(RELEASE.PolicyError) as caught:
            RELEASE._reject_candidate_host_authority(nested_candidate_input)
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_HOST_AUTHORITY_FORBIDDEN",
        )

    def test_close_binds_archive_to_the_stored_cp17_audit_not_a_drifted_fresh_one(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="v240-close-audit-drift-") as directory:
            workspace = Path(directory)
            state_path = (
                workspace
                / "docs"
                / "release-state"
                / "V2.40"
                / "promotion-state.json"
            )
            stored_audit = _sealed_audit()
            fresh_audit = _sealed_audit(release_actor_id=241)
            state = _cp18_state(stored_audit)
            config = {
                "state_path": str(state_path),
                "expected_state_sha256": STATE_SHA256,
            }
            with (
                mock.patch.object(RELEASE, "_workspace_root", return_value=workspace),
                mock.patch.object(
                    RELEASE,
                    "_load_state_cas",
                    return_value=(state_path, state, STATE_SHA256),
                ),
                mock.patch.object(
                    RELEASE,
                    "collect_live_audit_observation",
                    return_value={"source_commit": CANDIDATE},
                ),
                mock.patch.object(
                    RELEASE,
                    "_run_independent_audit",
                    return_value=fresh_audit,
                ),
                mock.patch.object(
                    RELEASE,
                    "_operation_details",
                    return_value={"audit_receipt": stored_audit},
                ),
            ):
                with self.assertRaises(RELEASE.PolicyError) as caught:
                    RELEASE.close_release(config)
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_CLOSE_AUDIT",
            )

    def _assert_boundary_drift_blocks_closed(
        self, scenario: str, *, mutation_timing: str = "post_finalize"
    ) -> None:
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

            fresh_audit = _sealed_audit()
            stored_audit = copy.deepcopy(fresh_audit)
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

            adapter = _FinalizerAdapter(
                mutate_after_finalize
                if mutation_timing == "post_finalize"
                else lambda: None
            )

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

            atomic_write_calls = 0

            def atomic_state_write(*_args, **_kwargs):
                nonlocal atomic_write_calls
                atomic_write_calls += 1
                if mutation_timing == "pre_finalize" and atomic_write_calls == 1:
                    mutate_after_finalize()
                return "3" * 64

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
                    side_effect=atomic_state_write,
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
            self.assertEqual(
                adapter.finalize_calls,
                0 if mutation_timing == "pre_finalize" else 1,
            )
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
        self._assert_boundary_drift_blocks_closed("archive_byte_drift")

    def test_candidate_recreation_or_registration_before_archive_close_is_rejected(
        self,
    ) -> None:
        self._assert_boundary_drift_blocks_closed(
            "candidate_recreated_or_registered"
        )

    def test_canonical_root_dirty_before_archive_close_is_rejected(self) -> None:
        self._assert_boundary_drift_blocks_closed("canonical_root_dirty")

    def test_archive_drift_after_seal_blocks_finalize_before_remote_write(self) -> None:
        self._assert_boundary_drift_blocks_closed(
            "archive_byte_drift", mutation_timing="pre_finalize"
        )

    def _marker_loss_recovery(
        self,
        *,
        drift_boundary: bool,
        stored_audit: dict[str, object] | None = None,
    ) -> tuple[dict, int]:
        stored_audit = copy.deepcopy(stored_audit or _sealed_audit())
        state = _cp18_state(stored_audit)
        checkpoint = state["checkpoints"]["CP18"]  # type: ignore[index]
        checkpoint["status"] = "in_progress"  # type: ignore[index]

        payload = RELEASE._final_main_ruleset_payload(240)
        finalize_details = {
            "ruleset_id": 24018,
            "ruleset_name": payload["name"],
            "ruleset_sha256": RELEASE._ruleset_payload_sha256(payload),
            "ruleset": payload,
        }
        stable_boundary_body = {
            "passed": True,
            "candidate_commit": CANDIDATE,
            "audit_receipt_sha256": RELEASE._canonical_json_sha256(stored_audit),
            "cleanup_verified": True,
            "candidate_worktree_absent": True,
            "candidate_worktree_entry_absent": True,
            "scanner_receipt_sha256": "1" * 64,
            "ssot_receipt_sha256": "2" * 64,
        }
        stable_boundary = {
            **stable_boundary_body,
            "receipt_sha256": RELEASE._canonical_json_sha256(stable_boundary_body),
        }
        # CP18 persists this deterministic boundary before the permanent
        # ruleset mutation.  A marker-loss recovery must use the same seal,
        # rather than recreating a caller-controlled close boundary.
        state["cp18_close_boundary_seal"] = copy.deepcopy(stable_boundary)
        state["cp18_close_boundary_seal_sha256"] = RELEASE._canonical_json_sha256(
            stable_boundary
        )
        archive_details = {
            "closed_identity_sha256": RELEASE._canonical_json_sha256(stored_audit),
            "candidate_commit": CANDIDATE,
            "close_boundary_receipt_sha256": stable_boundary["receipt_sha256"],
            "post_finalize_boundary_revalidated": True,
            "cleanup_verified": True,
            "scanner_receipt_sha256": stable_boundary["scanner_receipt_sha256"],
            "ssot_receipt_sha256": stable_boundary["ssot_receipt_sha256"],
            **RELEASE.CLOSED_COMPLETION_SEMANTICS,
        }
        operations = checkpoint["operations"]  # type: ignore[index]
        for operation, details in zip(
            operations,
            (finalize_details, archive_details),
        ):
            readback = _exact_readback("github_api", details)
            readback.pop("external_side_effect_count", None)
            operation["status"] = "in_progress"
            operation["readback"] = readback
            operation["receipt_sha256"] = RELEASE._canonical_json_sha256(
                {"intent": operation["intent"], "readback": readback}
            )

        authorizations = _authorizations(state)
        archive_authorization = authorizations["CP18.archive_close"]
        archive_authorization["parameters"] = {
            "audit_receipt": stored_audit,
            "close_boundary_receipt": stable_boundary,
            "archive_index_path": "/ignored/final-close-index.json",
        }

        class MarkerLossAdapter:
            def __init__(self) -> None:
                self.execute_calls = 0

            def observe(self, **_kwargs):
                return _exact_readback("github_api", finalize_details)

            def execute(self, **_kwargs):
                self.execute_calls += 1
                raise AssertionError("marker-loss recovery must not replay finalize")

        adapter = MarkerLossAdapter()
        fresh_boundary = copy.deepcopy(stable_boundary)
        if drift_boundary:
            fresh_boundary["ssot_receipt_sha256"] = "9" * 64
            source = dict(fresh_boundary)
            source.pop("receipt_sha256", None)
            fresh_boundary["receipt_sha256"] = RELEASE._canonical_json_sha256(source)

        with tempfile.TemporaryDirectory(prefix="v240-close-marker-loss-") as directory:
            state_path = Path(directory) / "promotion-state.json"
            with (
                mock.patch.object(
                    RELEASE,
                    "_load_state_cas",
                    return_value=(state_path, state, STATE_SHA256),
                ),
                mock.patch.object(RELEASE, "_verify_frozen_git_identity"),
                mock.patch.object(
                    RELEASE,
                    "_github_adapter_for_state",
                    return_value=adapter,
                ),
                mock.patch.object(
                    RELEASE,
                    "_validate_close_local_boundary",
                    return_value=fresh_boundary,
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
                config = {
                    "expected_state_sha256": STATE_SHA256,
                    "checkpoint_id": "CP18",
                    "operation_authorizations": authorizations,
                }
                if drift_boundary:
                    with self.assertRaises(RELEASE.PolicyError) as caught:
                        RELEASE.execute_current_checkpoint(
                            state_path,
                            config,
                            allowed_checkpoints={"CP18"},
                            recover_only=True,
                            _close_capability=RELEASE._CLOSE_CAPABILITY,
                        )
                    self.assertIn(
                        caught.exception.receipt["error_code"],
                        {
                            "E_V240_CLOSE_ARCHIVE",
                            "E_V240_RECOVERY_STALE_READBACK",
                            "E_V240_STATE_DERIVATION",
                        },
                    )
                else:
                    receipt = RELEASE.execute_current_checkpoint(
                        state_path,
                        config,
                        allowed_checkpoints={"CP18"},
                        recover_only=True,
                        _close_capability=RELEASE._CLOSE_CAPABILITY,
                    )
                    self.assertTrue(receipt["passed"])
                    self.assertEqual(receipt["phase"], "CLOSED")
                    self.assertEqual(
                        {
                            field: receipt[field]
                            for field in RELEASE.CLOSED_COMPLETION_FIELDS
                        },
                        RELEASE.CLOSED_COMPLETION_SEMANTICS,
                    )
                    self.assertEqual(
                        {
                            field: state[field]
                            for field in RELEASE.CLOSED_COMPLETION_FIELDS
                        },
                        RELEASE.CLOSED_COMPLETION_SEMANTICS,
                    )
                    archive_details = state["checkpoints"]["CP18"]["operations"][1][
                        "readback"
                    ]["details"]
                    self.assertEqual(
                        archive_details["closure_scope"],
                        "distribution_and_archive_only",
                    )
                    self.assertIs(archive_details["goal_achieved"], False)
                    self.assertIs(
                        archive_details["external_host_acceptance_required"], True
                    )
                    self.assertEqual(
                        archive_details["completion_authority"],
                        "repository_external_single_use_host",
                    )
        return state, adapter.execute_calls

    def test_cp18_archive_marker_loss_rejects_final_ledger_or_completion_drift(
        self,
    ) -> None:
        state, execute_calls = self._marker_loss_recovery(drift_boundary=True)
        self.assertEqual(execute_calls, 0)
        self.assertNotEqual(state.get("phase"), "CLOSED")

    def test_cp18_archive_marker_loss_unchanged_boundary_recovers_without_replay(
        self,
    ) -> None:
        state, execute_calls = self._marker_loss_recovery(drift_boundary=False)
        self.assertEqual(execute_calls, 0)
        self.assertEqual(state.get("phase"), "CLOSED")

    def test_cp17_to_cp18_window_allows_final_ssot_change_before_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v240-ssot-finalization-") as directory:
            root = Path(directory) / "GoalTeamsWork-V2.40"
            root.mkdir()
            release_task = root / "release-task.json"
            release_task.write_text(
                '{"task_state":"running","completion":null}\n',
                encoding="utf-8",
            )
            pre_cp17_tree = RELEASE._directory_tree_receipt(root)
            audit = _sealed_audit()
            with (
                mock.patch.object(
                    RELEASE,
                    "collect_live_audit_observation",
                    return_value={"source_commit": CANDIDATE},
                ),
                mock.patch.object(
                    RELEASE,
                    "_run_independent_audit",
                    return_value=audit,
                ),
            ):
                cp17_readback = RELEASE._execute_local_operation_unchecked(
                    "CP17.independent_audit",
                    {"candidate_commit": CANDIDATE, "version": "V2.40"},
                    {},
                    Path(directory) / "promotion-state.json",
                )
            stored_audit = cp17_readback["details"]["audit_receipt"]
            self.assertNotIn("goal_teams_work_tree", stored_audit)

            release_task.write_text(
                '{"task_state":"accepted","completion":"passed"}\n',
                encoding="utf-8",
            )
            (root / "completion-audit.json").write_text(
                '{"audit_state":"passed","independent":true}\n',
                encoding="utf-8",
            )
            final_tree = RELEASE._directory_tree_receipt(root)
            self.assertNotEqual(pre_cp17_tree, final_tree)

            state, execute_calls = self._marker_loss_recovery(
                drift_boundary=False,
                stored_audit=stored_audit,
            )
            self.assertEqual(execute_calls, 0)
            self.assertEqual(state.get("phase"), "CLOSED")


if __name__ == "__main__":
    unittest.main()
