from __future__ import annotations

import copy
import datetime as dt
import unittest
from unittest import mock

from scripts.release import skill_release
from scripts.v249 import release_flow
from scripts.v249.repository_boundary import build_boundary_receipt


SOURCE = "1" * 40
TREE = "2" * 40
NOW = dt.datetime(2026, 8, 1, 8, 0, tzinfo=dt.timezone.utc)


def seal(value: dict) -> dict:
    result = copy.deepcopy(value)
    result["receipt_sha256"] = release_flow.canonical_sha256(result)
    return result


def authorization() -> dict:
    actions = sorted(
        release_flow.REQUIRED_S4_ACTION_CLASSES
        | {"git_stage_commit", "targeted_test_and_validation"}
    )
    conditions = sorted(release_flow.REQUIRED_AUTH_VALIDITY_CONDITIONS)
    intent = {
        "repository_id": "R_GOAL_TEAMS",
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.49",
        "candidate_branch": "codex/v2.49-simplification",
        "tag": "v2.49",
        "locked_scope": "V2.49 release test fixture",
        "action_allowlist": actions,
        "validity_conditions": conditions,
    }
    return {
        "schema_version": "goal-teams-project-start-authorization-v2.49",
        "receipt_id": "AUTH-V249-TEST",
        "authorization_id": "AUTH-V249-TEST",
        "authorization_state": "granted_once_at_project_start",
        "authorization_lineage_preserved": True,
        "authorization_source": "user_confirmed_v249_one_shot_prompt",
        "approver_identity": "user",
        "issued_at": "2026-07-31T08:00:00+00:00",
        "expires_at": None,
        "repository": {
            "id": "R_GOAL_TEAMS",
            "name_with_owner": "vibe-coding-era/goal-teams",
            "origin_fetch": "git@github.com:vibe-coding-era/goal-teams.git",
            "origin_push": "git@github.com:vibe-coding-era/goal-teams.git",
            "default_branch": "main",
        },
        "version": "V2.49",
        "candidate_branch": "codex/v2.49-simplification",
        "tag": "v2.49",
        "locked_scope": "V2.49 release test fixture",
        "action_allowlist": actions,
        "validity_conditions": conditions,
        "intent": intent,
        "intent_sha256": release_flow.canonical_sha256(intent),
        "revocation_conditions": ["explicit_user_revocation"],
    }


def full_regression() -> dict:
    files = [{"path": "tests/v249/test_release_control.py", "sha256": "a" * 64}]
    denominator = {
        "denominator_id": "V249-CURRENT-GENERATION-FULL",
        "generation_id": "V2.49",
        "scope": "current_generation_full_regression",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "test_root": "tests/v249",
        "test_pattern": "test_*.py",
        "contract_path": "references/current/generations/V2.49/contracts/release-command-manifest.json",
        "contract_sha256": "e" * 64,
        "test_files": files,
        "test_file_count": 1,
        "test_file_set_sha256": release_flow.canonical_sha256(files),
        "test_case_count": 1,
        "legacy_roots_excluded": ["tests/v23"],
    }
    denominator["denominator_sha256"] = release_flow.canonical_sha256(denominator)
    return seal(
        {
            "gate_id": "full_regression",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "runner_role": "current_generation_full_regression",
            "run_id": "FULL-RUN-1",
            "execution_source": "exact_clean_worktree",
            "worktree_binding": {
                "binding_kind": "exact_clean_worktree",
                "head_commit": SOURCE,
                "head_tree": TREE,
                "status_porcelain_sha256": __import__("hashlib").sha256(b"").hexdigest(),
                "dirty_entry_count": 0,
                "untracked_entry_count": 0,
            },
            "denominator": denominator,
            "discovered_test_count": 1,
            "legacy_test_invocation_count": 0,
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "invocation_count_for_released_identity": 1,
            "argv": [
                "python3",
                "-m",
                "unittest",
                "discover",
                "-v",
                "-s",
                "tests/v249",
                "-p",
                "test_*.py",
            ],
            "cwd": ".",
            "returncode": 0,
            "output_sha256": "f" * 64,
        }
    )


def security_git_snapshot() -> dict:
    import hashlib
    import json
    import stat
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    manifest_path = (
        root
        / "references/current/generations/V2.49/contracts/"
        "release-security-review-manifest.json"
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    objects = {}
    for target in manifest["review_targets"]:
        path = root / target["path"]
        data = path.read_bytes()
        git_blob = hashlib.sha1(
            b"blob " + str(len(data)).encode("ascii") + b"\x00" + data
        ).hexdigest()
        objects[target["path"]] = {
            "path": target["path"],
            "categories": target["categories"],
            "content_kind": target["content_kind"],
            "git_mode": "100755" if stat.S_IMODE(path.stat().st_mode) & 0o111 else "100644",
            "git_blob": git_blob,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "target_paths": sorted(objects),
        "objects": objects,
    }


def security_review() -> dict:
    import hashlib

    snapshot = security_git_snapshot()
    manifest = snapshot["manifest"]
    assertions = [
        {"assertion_id": assertion_id, "passed": True, "observed": {}}
        for assertion_id in manifest["assertion_denominator"]
    ]
    reviewed_files = []
    for target in sorted(manifest["review_targets"], key=lambda item: item["path"]):
        frozen = snapshot["objects"][target["path"]]
        reviewed_files.append(
            {
                **frozen,
                "filesystem_sha256": frozen["sha256"],
                "git_object_matches_filesystem": True,
                "symlink": False,
            }
        )
    reviewed_file_set_sha256 = release_flow.canonical_sha256(reviewed_files)
    denominator = {
        "denominator_id": manifest["denominator_id"],
        "generation_id": "V2.49",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "manifest_path": "references/current/generations/V2.49/contracts/release-security-review-manifest.json",
        "manifest_sha256": snapshot["manifest_sha256"],
        "target_count": len(reviewed_files),
        "target_paths": [item["path"] for item in reviewed_files],
        "required_categories": manifest["required_categories"],
        "reviewed_file_set_sha256": reviewed_file_set_sha256,
        "unknown_or_missing_policy": "fail_closed",
    }
    denominator["denominator_sha256"] = release_flow.canonical_sha256(denominator)
    components = {
        "dependency_review": {
            "passed": True,
            "discovered_dependency_files": [],
            "declared_dependency_files": [],
            "python_imports": [],
            "unknown_import_count": 0,
            "findings": [],
        },
        "secret_negative_scan": {
            "passed": True,
            "rule_count": 8,
            "scanned_file_count": len(reviewed_files),
            "finding_count": 0,
            "findings": [],
        },
        "dangerous_operation_review": {
            "passed": True,
            "observed_count": manifest["dangerous_operation_allowlist"]["allowed_inventory_count"],
            "allowed_count": manifest["dangerous_operation_allowlist"]["allowed_inventory_count"],
            "inventory_sha256": manifest["dangerous_operation_allowlist"]["allowed_inventory_sha256"],
            "allowed_operations": [],
            "findings": [],
        },
        "command_execution_review": {
            "passed": True,
            "subprocess_call_count": 1,
            "subprocess_calls": [],
            "findings": [],
        },
        "workflow_dependency_review": {
            "passed": True,
            "action_pins": [],
            "findings": [],
        },
        "git_ssh_review": {
            "passed": True,
            "workflow_checkout_count": 3,
            "findings": [],
        },
    }
    runner_file = next(
        item
        for item in reviewed_files
        if item["path"] == "scripts/checks/run-v249-release-security-review.py"
    )
    contract_paths = {
        target["path"]
        for target in manifest["review_targets"]
        if "contract" in target["categories"]
    }
    review_material = {
        "assertions": assertions,
        "findings": [],
        "reviewed_file_set_sha256": reviewed_file_set_sha256,
        "dangerous_operation_inventory_sha256": components[
            "dangerous_operation_review"
        ]["inventory_sha256"],
    }
    return seal(
        {
            "gate_id": "release_security_review",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "runner_role": "exact_released_implementation_security_reviewer",
            "reviewer_identity": {
                "reviewer_id": "security-reviewer",
                "runner_path": "scripts/checks/run-v249-release-security-review.py",
                "runner_sha256": runner_file["sha256"],
            },
            "review_run_id": "SEC-RUN-1",
            "identity_binding": {
                "binding_kind": "exact_clean_git_object_and_filesystem",
                "repository_root": ".",
                "head_commit": SOURCE,
                "head_tree": TREE,
                "status_porcelain_sha256": hashlib.sha256(b"").hexdigest(),
                "dirty_entry_count": 0,
                "untracked_entry_count": 0,
                "worktree_diff_returncode": 0,
                "index_diff_returncode": 0,
                "git_replace_objects_disabled": True,
                "lazy_fetch_disabled": True,
            },
            "review_denominator": denominator,
            "reviewed_files": reviewed_files,
            "reviewed_file_set_sha256": reviewed_file_set_sha256,
            "fresh_process_observed": True,
            "fresh_separate_process": True,
            "runner_pid": 101,
            "orchestrator_pid": 100,
            "actor_assurance": "I1",
            "actor_relationship": "correlated",
            "external_independence": False,
            "independence_claim": False,
            "independence_scope": "fresh_separate_process_only",
            "legacy_security_fixture_invocation_count": 0,
            "s2_security_check_invocation_count": 0,
            "s2_projection": "forbidden",
            "assertions": assertions,
            "findings": [],
            "finding_count": 0,
            **components,
            "review_digest": release_flow.canonical_sha256(review_material),
            "contract_digests": {
                item["path"]: item["sha256"]
                for item in reviewed_files
                if item["path"] in contract_paths
            },
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "invocation_count_for_released_identity": 1,
        }
    )


def transition() -> dict:
    signed_payload = {
        "repository": "vibe-coding-era/goal-teams",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "authorization_id": "AUTH-V249-TEST",
        "authorization_receipt_sha256": "7" * 64,
        "authorization_intent_sha256": "8" * 64,
        "previous_controller_product_version": "V2.48",
        "previous_run_id": "V248-HOST-RUN-1",
        "nonce": "nonce-v249-controller-handoff-000001",
        "issued_at": "2026-08-01T07:55:00+00:00",
        "expires_at": "2026-08-01T08:05:00+00:00",
        "installed_v248_current_state": {
            "state_sha256": "9" * 64,
            "source_commit": "3" * 40,
            "source_tree": "4" * 40,
            "tag": "v2.48",
            "release_id": 362135071,
        },
        "github_signing_identity": {
            "account": "vibe-coding-era",
            "key_id": 152596014,
            "public_key": "ssh-ed25519 test-fixture",
            "public_key_fingerprint": "SHA256:test-fixture",
            "ssh_signature_namespace": "goal-teams-v2.49-controller-handoff",
        },
    }
    handoff = {
        "schema_version": "goal-teams-v2.49-controller-handoff-receipt-v1",
        "signed_payload": signed_payload,
        "payload_sha256": release_flow.canonical_sha256(signed_payload),
        "ssh_signature": "external-test-fixture",
    }
    launch = seal(
        {
            "schema_version": "goal-teams-v2.49-runtime-launch-receipt-v1",
            "controller_handoff_receipt_sha256": release_flow.canonical_sha256(
                handoff
            ),
            "controller_handoff_payload_sha256": handoff["payload_sha256"],
            "nonce": signed_payload["nonce"],
            "parent_pid": 200,
            "expected_child_pid": 201,
            "host_execution_id": "GITHUB-RUN-1",
            "new_run_id": "V249-RUNTIME-RUN-1",
            "launched_at": "2026-08-01T08:00:00+00:00",
            "adapter_identity": "release-control-test-adapter",
            "adapter_code_sha256": "a" * 64,
        }
    )
    return seal(
        {
            "schema_version": "goal-teams-v2.49-runtime-transition-receipt-v1",
            "transition_id": "TRANSITION-RELEASED",
            "stage": "released",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "generation_id": "V2.49",
            "loaded_runtime_product_version": "V2.49",
            "controller_handoff_receipt": handoff,
            "controller_handoff_receipt_sha256": release_flow.canonical_sha256(
                handoff
            ),
            "controller_handoff_signature_verified": True,
            "runtime_launch_receipt": launch,
            "runtime_launch_receipt_sha256": release_flow.canonical_sha256(launch),
            "host_execution_id": launch["host_execution_id"],
            "fresh_process_observed": True,
            "fresh_process_kind": "host_adapter_popen_child",
            "runner_pid": 201,
            "orchestrator_pid": 200,
            "actor_assurance": "I1",
            "actor_relationship": "correlated",
            "independence_claim": False,
            "external_independent": False,
            "cryptographic_host_attestation": False,
            "input_digests": {"SKILL.md": "3" * 64},
            "loaded_paths": ["SKILL.md"],
            "receipt_state": "current",
        }
    )


def fixture_runtime_validation(receipt: object, **kwargs: object) -> dict:
    value = receipt if isinstance(receipt, dict) else {}
    handoff = value.get("controller_handoff_receipt")
    handoff = handoff if isinstance(handoff, dict) else {}
    payload = handoff.get("signed_payload")
    payload = payload if isinstance(payload, dict) else {}
    launch = value.get("runtime_launch_receipt")
    launch = launch if isinstance(launch, dict) else {}
    digests = value.get("input_digests")
    valid = bool(
        value.get("stage") == "released"
        and value.get("source_commit") == kwargs.get("expected_source_commit", SOURCE)
        and value.get("source_tree") == kwargs.get("expected_source_tree", TREE)
        and value.get("loaded_runtime_product_version") == "V2.49"
        and payload.get("previous_controller_product_version") == "V2.48"
        and payload.get("previous_run_id")
        and launch.get("new_run_id")
        and payload.get("previous_run_id") != launch.get("new_run_id")
        and not any(
            field in value
            for field in (
                "controller_version",
                "previous_controller_product_version",
                "previous_run_id",
                "new_run_id",
            )
        )
        and isinstance(digests, dict)
        and digests
        and value.get("loaded_paths") == sorted(digests)
        and value.get("receipt_sha256") == release_flow._receipt_sha256(value)
    )
    return {
        "ok": valid,
        "passed": valid,
        "errors": [] if valid else ["E_V249_TEST_RUNTIME_FIXTURE"],
        "may_enter_s0": valid,
    }


def s2_receipt() -> dict:
    return release_flow.build_s2_receipt(
        source_commit=SOURCE,
        source_tree=TREE,
        asset_set_id="ASSET-V249",
        assets=[
            {"name": "SHA256SUMS", "size": 1, "sha256": "a" * 64},
            {"name": "_files.sha256", "size": 2, "sha256": "b" * 64},
            {"name": "_release.json", "size": 3, "sha256": "c" * 64},
            {"name": "goal-teams-V2.49.tar.gz", "size": 4, "sha256": "d" * 64},
        ],
    )


def control_receipt() -> dict:
    runtime = transition()
    full = full_regression()
    security = security_review()
    with mock.patch.object(
        release_flow,
        "validate_runtime_transition",
        side_effect=fixture_runtime_validation,
    ):
        s0 = release_flow.build_s0_receipt(
            source_commit=SOURCE,
            source_tree=TREE,
            runtime_transition=runtime,
            expected_host_execution_id="GITHUB-RUN-1",
        )
    with mock.patch.object(
        release_flow,
        "_security_review_git_snapshot",
        return_value=security_git_snapshot(),
    ):
        s1 = release_flow.build_s1_receipt(
            source_commit=SOURCE,
            source_tree=TREE,
            full_regression=full,
            release_security_review=security,
        )
    s2 = s2_receipt()
    integrity = seal(
        {
            "gate_id": "same_built_asset_integrity_validation",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "asset_set_id": s2["asset_set_id"],
            "asset_set_digest": s2["asset_set_digest"],
            "s2_receipt_sha256": s2["receipt_sha256"],
            "validation_kind": "frozen_source_and_boundary_integrity",
            "same_built_asset_set": True,
            "asset_build_invocation_count": 0,
            "second_build_comparison_attempted": False,
            "reproducibility_claim": False,
            "returncode": 0,
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
        }
    )
    s3 = seal(
        {
            "gate_id": "s3_not_required",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "asset_set_id": s2["asset_set_id"],
            "asset_set_digest": s2["asset_set_digest"],
            "s2_receipt_sha256": s2["receipt_sha256"],
            "gate_requirement": "not_required",
            "check_state": "not_required",
            "run_outcome": "not_run",
            "evidence_state": "current",
            "s3_process_invocation_count": 0,
            "child_argv": [],
        }
    )
    commands = [
        ["python3", "scripts/checks/check-workspace-boundaries.py"],
        ["python3", "scripts/checks/check-package-manifest.py"],
        ["python3", "scripts/release/validate-release.py"],
    ]
    boundary = build_boundary_receipt(
        source_commit=SOURCE,
        source_tree=TREE,
        asset_set_id=s2["asset_set_id"],
        asset_set_digest=s2["asset_set_digest"],
        package_manifest_digest="e" * 64,
        validator_digest="f" * 64,
        argv=commands,
        cwd=".",
        check_state="passed",
        run_outcome="passed",
        s2_receipt_sha256=s2["receipt_sha256"],
        command_receipts=[
            {"argv": argv, "returncode": 0, "output_sha256": str(index) * 64}
            for index, argv in enumerate(commands, start=1)
        ],
    )
    anchor = seal(
        {
            "schema_version": "goal-teams-v2.49-external-anchor-validation-v1",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "current_test_file_set_sha256": "4" * 64,
            "runtime_input_set_sha256": "5" * 64,
            "security_contract_set_sha256": "6" * 64,
            "asset_set_digest": s2["asset_set_digest"],
            "check_state": "passed",
            "evidence_state": "current",
        }
    )
    with (
        mock.patch.object(
            release_flow,
            "validate_runtime_transition",
            side_effect=fixture_runtime_validation,
        ),
        mock.patch.object(
            release_flow,
            "_security_review_git_snapshot",
            return_value=security_git_snapshot(),
        ),
    ):
        return release_flow.build_release_control_receipt(
            repository="vibe-coding-era/goal-teams",
            version="V2.49",
            project_size="medium",
            candidate_branch="codex/v2.49-simplification",
            tag="v2.49",
            source_commit=SOURCE,
            source_tree=TREE,
            authorization_receipt=authorization(),
            released_runtime_transition=runtime,
            s0=s0,
            full_regression=full,
            release_security_review=security,
            s1=s1,
            s2=s2,
            asset_integrity_validation=integrity,
            s3=s3,
            repository_boundary=boundary,
            external_anchor_validation=anchor,
            validation_time=NOW,
        )


def validate(control: dict) -> dict:
    with (
        mock.patch.object(
            release_flow,
            "validate_runtime_transition",
            side_effect=fixture_runtime_validation,
        ),
        mock.patch.object(
            release_flow,
            "_security_review_git_snapshot",
            return_value=security_git_snapshot(),
        ),
    ):
        return release_flow.validate_release_control_receipt(
            control,
            expected_repository="vibe-coding-era/goal-teams",
            expected_version="V2.49",
            expected_candidate_branch="codex/v2.49-simplification",
            expected_tag="v2.49",
            expected_source_commit=SOURCE,
            expected_source_tree=TREE,
            validation_time=NOW,
        )


class TestV249ReleaseControl(unittest.TestCase):
    def test_s0_uses_shared_strict_runtime_validator_and_rejects_weak_entry(self) -> None:
        runtime = transition()
        strict_failure = {
            "ok": False,
            "passed": False,
            "errors": ["E_V249_CONTROLLER_HANDOFF_REQUIRED"],
            "may_enter_s0": False,
        }
        with (
            mock.patch.object(
                release_flow,
                "validate_runtime_transition",
                return_value=strict_failure,
                create=True,
            ) as validator,
            self.assertRaisesRegex(ValueError, "E_V249_RELEASED_RUNTIME_S0_REQUIRED"),
        ):
            release_flow.build_s0_receipt(
                source_commit=SOURCE,
                source_tree=TREE,
                runtime_transition=runtime,
                expected_host_execution_id="GITHUB-RUN-1",
            )
        validator.assert_called_once()

    def test_candidate_runtime_never_enters_s0(self) -> None:
        runtime = transition()
        runtime["stage"] = "candidate"
        runtime["receipt_sha256"] = release_flow._receipt_sha256(runtime)
        with self.assertRaisesRegex(ValueError, "E_V249_RELEASED_RUNTIME_S0_REQUIRED"):
            release_flow.build_s0_receipt(
                source_commit=SOURCE,
                source_tree=TREE,
                runtime_transition=runtime,
                expected_host_execution_id="GITHUB-RUN-1",
            )

    def test_s0_rejects_swapped_runtime_version_axes(self) -> None:
        runtime = transition()
        runtime["previous_controller_product_version"] = "V2.49"
        runtime["loaded_runtime_product_version"] = "V2.48"
        runtime["receipt_sha256"] = release_flow._receipt_sha256(runtime)
        with self.assertRaisesRegex(ValueError, "E_V249_RELEASED_RUNTIME_S0_REQUIRED"):
            release_flow.build_s0_receipt(
                source_commit=SOURCE,
                source_tree=TREE,
                runtime_transition=runtime,
                expected_host_execution_id="GITHUB-RUN-1",
            )

    def test_complete_chain_allows_s4_preflight(self) -> None:
        control = control_receipt()
        verdict = validate(control)
        self.assertTrue(verdict["ok"], verdict["errors"])
        self.assertFalse(verdict["publish_allowed"])
        self.assertTrue(verdict["external_anchor_revalidation_required"])

    def test_missing_receipt_and_nested_identity_drift_fail_closed(self) -> None:
        control = control_receipt()
        del control["repository_boundary"]
        control["release_control_sha256"] = release_flow._receipt_sha256(control)
        self.assertFalse(validate(control)["ok"])

        control = control_receipt()
        control["s2"]["source_tree"] = "f" * 40
        control["release_control_sha256"] = release_flow._receipt_sha256(control)
        verdict = validate(control)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_S2_RECEIPT_DIGEST", verdict["errors"])

    def test_authorization_action_and_intent_drift_fail_closed(self) -> None:
        control = control_receipt()
        authorization_value = control["authorization_receipt"]
        authorization_value["action_allowlist"].remove(
            "formal_install_update_rollback_uninstall"
        )
        authorization_value["intent"]["action_allowlist"] = authorization_value[
            "action_allowlist"
        ]
        authorization_value["intent_sha256"] = release_flow.canonical_sha256(
            authorization_value["intent"]
        )
        control["release_control_sha256"] = release_flow._receipt_sha256(control)
        verdict = validate(control)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_AUTHORIZATION_ACTION_DRIFT", verdict["errors"])

    def test_resealed_runtime_or_security_summary_is_not_accepted(self) -> None:
        control = control_receipt()
        runtime = control["released_runtime_transition"]
        runtime["loaded_paths"] = []
        runtime["receipt_sha256"] = release_flow._receipt_sha256(runtime)
        control["release_control_sha256"] = release_flow._receipt_sha256(control)
        verdict = validate(control)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_RELEASED_RUNTIME_S0_REQUIRED", verdict["errors"])

        control = control_receipt()
        security = control["release_security_review"]
        security["assertions"] = [security["assertions"][0]]
        security["review_digest"] = __import__("hashlib").sha256(
            __import__("json").dumps(
                security["assertions"], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        security["receipt_sha256"] = release_flow._receipt_sha256(security)
        control["release_control_sha256"] = release_flow._receipt_sha256(control)
        verdict = validate(control)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_SECURITY_REVIEW_CONTRACT", verdict["errors"])

    def test_self_consistent_reviewed_file_forgery_fails_exact_git_object(self) -> None:
        security = security_review()
        target = next(
            item
            for item in security["reviewed_files"]
            if item["path"] == "scripts/v249/s4_executor.py"
        )
        target["sha256"] = "f" * 64
        target["filesystem_sha256"] = target["sha256"]
        reviewed_digest = release_flow.canonical_sha256(security["reviewed_files"])
        security["reviewed_file_set_sha256"] = reviewed_digest
        security["review_denominator"]["reviewed_file_set_sha256"] = reviewed_digest
        security["review_denominator"]["denominator_sha256"] = release_flow.canonical_sha256(
            {
                key: value
                for key, value in security["review_denominator"].items()
                if key != "denominator_sha256"
            }
        )
        security["review_digest"] = release_flow.canonical_sha256(
            {
                "assertions": security["assertions"],
                "findings": security["findings"],
                "reviewed_file_set_sha256": reviewed_digest,
                "dangerous_operation_inventory_sha256": security[
                    "dangerous_operation_review"
                ]["inventory_sha256"],
            }
        )
        security["receipt_sha256"] = release_flow._receipt_sha256(security)
        with mock.patch.object(
            release_flow,
            "_security_review_git_snapshot",
            return_value=security_git_snapshot(),
        ):
            verdict = release_flow.validate_release_gate_bindings(
                SOURCE, TREE, full_regression(), security
            )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V249_SECURITY_REVIEW_CONTRACT", verdict["errors"])

    def test_authorized_publish_command_is_only_a_not_run_plan(self) -> None:
        control = control_receipt()
        config = {
            "candidate_branch": "codex/v2.49-simplification",
            "tag": "v2.49",
            "release_mode": "skill_simple",
            "approval_model": "project_start_authorization_reused",
        }
        identity = {
            "source_commit": SOURCE,
            "source_git_tree": TREE,
            "source_ref": "refs/heads/main",
        }
        with (
            mock.patch.object(skill_release, "_simple_config", return_value=config),
            mock.patch.object(skill_release, "_read_identity", return_value=identity),
            mock.patch.object(
                skill_release, "_v249_release_flow_module", return_value=release_flow
            ),
            mock.patch.object(
                skill_release,
                "_validate_v249_external_anchors",
                return_value=control["external_anchor_validation"],
            ),
            mock.patch.object(
                release_flow,
                "validate_runtime_transition",
                side_effect=fixture_runtime_validation,
            ),
            mock.patch.object(
                release_flow,
                "_security_review_git_snapshot",
                return_value=security_git_snapshot(),
            ),
        ):
            receipt = skill_release.publish(
                "V2.49", SOURCE, release_control_receipt=control
            )

        self.assertEqual("authorize_s4_plan", receipt["command"])
        self.assertEqual("authorized_operation_plan_not_executed", receipt["status"])
        self.assertFalse(receipt["ok"])
        self.assertFalse(receipt["passed"])
        self.assertEqual("not_run", receipt["run_outcome"])
        self.assertFalse(receipt["action_executed"])
        self.assertEqual("authorized_not_executed", receipt["publish_state"])

    def test_forged_external_anchor_never_produces_an_authorized_plan(self) -> None:
        control = control_receipt()
        forged = copy.deepcopy(control["external_anchor_validation"])
        forged["current_test_file_set_sha256"] = "9" * 64
        forged["receipt_sha256"] = release_flow.canonical_sha256(forged)
        control["external_anchor_validation"] = forged
        control["release_control_sha256"] = release_flow._receipt_sha256(control)
        config = {
            "candidate_branch": "codex/v2.49-simplification",
            "tag": "v2.49",
            "release_mode": "skill_simple",
            "approval_model": "project_start_authorization_reused",
        }
        identity = {
            "source_commit": SOURCE,
            "source_git_tree": TREE,
            "source_ref": "refs/heads/main",
        }
        with (
            mock.patch.object(skill_release, "_simple_config", return_value=config),
            mock.patch.object(skill_release, "_read_identity", return_value=identity),
            mock.patch.object(
                skill_release,
                "_validate_v249_external_anchors",
                return_value=control_receipt()["external_anchor_validation"],
            ),
        ):
            receipt = skill_release.publish(
                "V2.49", SOURCE, release_control_receipt=control
            )

        self.assertFalse(receipt["ok"])
        self.assertFalse(receipt["passed"])
        self.assertEqual("blocked", receipt["publish_state"])
        self.assertEqual("E_V249_EXTERNAL_ANCHOR_REVALIDATION", receipt["error_code"])


if __name__ == "__main__":
    unittest.main()
