from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.release import skill_release
from scripts.v250 import release_flow, runtime_transition
from scripts.v250.generation_runtime import load_candidate_generation
from scripts.v250.route_closure import compile_derived_route_closure
from scripts.v250.route_derivation import derive_route
from scripts.v250.repository_boundary import build_boundary_receipt
from tests.v250.v263_candidate_fixture import inactive_candidate_fixture
from tests.v250.test_runtime_transition import _observe as observe_runtime_transition


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
        "version": "V2.63",
        "candidate_branch": "codex/develop-v2.63",
        "tag": "v2.63",
        "locked_scope": "V2.63 release test fixture",
        "action_allowlist": actions,
        "validity_conditions": conditions,
    }
    return {
        "schema_version": "goal-teams-project-start-authorization-v2.50",
        "receipt_id": "AUTH-V250-TEST",
        "authorization_id": "AUTH-V250-TEST",
        "authorization_state": "granted_once_at_project_start",
        "authorization_lineage_preserved": True,
        "authorization_source": "user_confirmed_v250_one_shot_prompt",
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
        "version": "V2.63",
        "candidate_branch": "codex/develop-v2.63",
        "tag": "v2.63",
        "locked_scope": "V2.63 release test fixture",
        "action_allowlist": actions,
        "validity_conditions": conditions,
        "intent": intent,
        "intent_sha256": release_flow.canonical_sha256(intent),
        "revocation_conditions": ["explicit_user_revocation"],
    }


def full_regression() -> dict:
    files = [
        {"path": "tests/v250/test_release_control.py", "sha256": "a" * 64},
        {"path": "tests/v263/test_delivery_closure.py", "sha256": "b" * 64},
    ]
    denominator = {
        "denominator_id": "V250-CURRENT-GENERATION-FULL",
        "generation_id": "V2.63",
        "scope": "current_generation_full_regression",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "test_roots": ["tests/v250", "tests/v263"],
        "test_pattern": "test_*.py",
        "contract_path": "references/current/generations/V2.63/contracts/release-command-manifest.json",
        "contract_sha256": "e" * 64,
        "test_files": files,
        "test_file_count": 2,
        "test_file_set_sha256": release_flow.canonical_sha256(files),
        "test_case_count": 2,
        "legacy_roots_excluded": ["tests/v23", "tests/v249", "tests/v26"],
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
            "discovered_test_count": 2,
            "legacy_test_invocation_count": 0,
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "invocation_count_for_released_identity": 1,
            "argv": [
                "python3",
                "-m",
                "unittest",
                "-v",
                "tests.v250.test_release_control",
                "tests.v263.test_delivery_closure",
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
        / "references/current/generations/V2.63/contracts/"
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
        "generation_id": "V2.63",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "manifest_path": "references/current/generations/V2.63/contracts/release-security-review-manifest.json",
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
        if item["path"] == "scripts/checks/run-v250-release-security-review.py"
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
                "runner_path": "scripts/checks/run-v250-release-security-review.py",
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
        "authorization_id": "AUTH-V250-TEST",
        "authorization_receipt_sha256": "7" * 64,
        "authorization_intent_sha256": "8" * 64,
        "previous_controller_product_version": "V2.6",
        "previous_run_id": "V251-HOST-RUN-1",
        "nonce": "nonce-v250-controller-handoff-000001",
        "issued_at": "2026-08-01T07:55:00+00:00",
        "expires_at": "2026-08-01T08:05:00+00:00",
        "installed_v26_current_state": {
            "state_sha256": "9" * 64,
            "source_commit": "3" * 40,
            "source_tree": "4" * 40,
            "tag": "v2.6",
            "release_id": 362135071,
        },
        "github_signing_identity": {
            "account": "vibe-coding-era",
            "key_id": 152596014,
            "public_key": "ssh-ed25519 test-fixture",
            "public_key_fingerprint": "SHA256:test-fixture",
            "ssh_signature_namespace": "goal-teams-v2.63-controller-handoff",
        },
    }
    handoff = {
        "schema_version": "goal-teams-v2.63-controller-handoff-receipt-v1",
        "signed_payload": signed_payload,
        "payload_sha256": release_flow.canonical_sha256(signed_payload),
        "ssh_signature": "external-test-fixture",
    }
    launch = seal(
        {
            "schema_version": "goal-teams-v2.63-runtime-launch-receipt-v1",
            "controller_handoff_receipt_sha256": release_flow.canonical_sha256(
                handoff
            ),
            "controller_handoff_payload_sha256": handoff["payload_sha256"],
            "nonce": signed_payload["nonce"],
            "parent_pid": 200,
            "expected_child_pid": 201,
            "host_execution_id": "GITHUB-RUN-1",
            "new_run_id": "V250-RUNTIME-RUN-1",
            "launched_at": "2026-08-01T08:00:00+00:00",
            "adapter_identity": "release-control-test-adapter",
            "adapter_code_sha256": "a" * 64,
        }
    )
    return seal(
        {
            "schema_version": "goal-teams-v2.63-runtime-transition-receipt-v1",
            "transition_id": "TRANSITION-RELEASED",
            "stage": "released",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "generation_id": "V2.63",
            "loaded_runtime_product_version": "V2.63",
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
        and value.get("loaded_runtime_product_version") == "V2.63"
        and payload.get("previous_controller_product_version") == "V2.6"
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
        "errors": [] if valid else ["E_V250_TEST_RUNTIME_FIXTURE"],
        "may_enter_s0": valid,
    }


def s2_receipt() -> dict:
    return release_flow.build_s2_receipt(
        source_commit=SOURCE,
        source_tree=TREE,
        asset_set_id="ASSET-V250",
        assets=[
            {"name": "SHA256SUMS", "size": 1, "sha256": "a" * 64},
            {"name": "_files.sha256", "size": 2, "sha256": "b" * 64},
            {"name": "_release.json", "size": 3, "sha256": "c" * 64},
            {"name": "goal-teams-V2.63.tar.gz", "size": 4, "sha256": "d" * 64},
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
            "schema_version": "goal-teams-v2.63-external-anchor-validation-v1",
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
            version="V2.63",
            project_size="medium",
            candidate_branch="codex/develop-v2.63",
            tag="v2.63",
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
            expected_version="V2.63",
            expected_candidate_branch="codex/develop-v2.63",
            expected_tag="v2.63",
            expected_source_commit=SOURCE,
            expected_source_tree=TREE,
            validation_time=NOW,
        )


def checkpoint_fixture(root: Path) -> tuple[Path, Path, dict[str, str]]:
    receipt_root = root / "receipts"
    release_root = root / "release"
    artifact_root = release_root / "V2.63" / "_artifacts"
    receipt_root.mkdir(parents=True)
    artifact_root.mkdir(parents=True)
    asset_paths = {
        "SHA256SUMS": artifact_root / "SHA256SUMS",
        "_files.sha256": release_root / "V2.63" / "_files.sha256",
        "_release.json": release_root / "V2.63" / "_release.json",
        "goal-teams-V2.63.tar.gz": artifact_root / "goal-teams-V2.63.tar.gz",
    }
    for index, (name, path) in enumerate(sorted(asset_paths.items()), start=1):
        path.write_bytes(f"{index}:{name}\n".encode())
    assets = [
        {
            "name": name,
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in sorted(asset_paths.items())
    ]
    s2 = release_flow.build_s2_receipt(
        source_commit=SOURCE,
        source_tree=TREE,
        asset_set_id="ASSET-V250-CHECKPOINT",
        assets=assets,
    )
    auth = authorization()
    route_facts = {
        "facts_source": {"schema_version": "test-route-facts-source-v1"},
        "project_route_facts": {"project_size": "large"},
        "project_route_facts_sha256": "a" * 64,
    }
    derived_route = {
        "route_id": "V250-ROUTE-LARGE-RELEASE",
        "receipt_sha256": "b" * 64,
    }
    route_closure = {
        "route_id": "V250-ROUTE-LARGE-RELEASE",
        "derived_route_sha256": derived_route["receipt_sha256"],
        "closure_digest": "c" * 64,
    }

    def fixture_raw(value: dict) -> bytes:
        return json.dumps(value, sort_keys=True).encode("utf-8")

    runtime = {
        "receipt_sha256": "1" * 64,
        "controller_handoff_receipt": {},
        "route_id": route_closure["route_id"],
        "route_facts_receipt_sha256": hashlib.sha256(
            fixture_raw(route_facts)
        ).hexdigest(),
        "project_route_facts_sha256": route_facts[
            "project_route_facts_sha256"
        ],
        "derived_route_receipt_sha256": hashlib.sha256(
            fixture_raw(derived_route)
        ).hexdigest(),
        "derived_route_sha256": derived_route["receipt_sha256"],
        "route_receipt_sha256": hashlib.sha256(
            fixture_raw(route_closure)
        ).hexdigest(),
        "route_closure_digest": route_closure["closure_digest"],
    }
    s0 = {"receipt_sha256": "2" * 64}
    full = {"receipt_sha256": "3" * 64}
    security = {"receipt_sha256": "4" * 64}
    s1 = {"receipt_sha256": "5" * 64}
    integrity = {"receipt_sha256": "6" * 64}
    s3 = {"receipt_sha256": "7" * 64, "s3_process_invocation_count": 1}
    boundary = {"receipt_sha256": "8" * 64}
    control = {
        "project_size": "large",
        "asset_set_id": s2["asset_set_id"],
        "asset_set_digest": s2["asset_set_digest"],
        "authorization_receipt": auth,
        "released_runtime_transition": runtime,
        "s0": s0,
        "full_regression": full,
        "release_security_review": security,
        "s1": s1,
        "s2": s2,
        "asset_integrity_validation": integrity,
        "s3": s3,
        "repository_boundary": boundary,
        "release_control_sha256": "9" * 64,
    }
    values = {
        "authorization.json": auth,
        "controller-handoff.json": {},
        "github-owner-key-validation.json": {},
        "release-route-facts.json": route_facts,
        "release-route-derived.json": derived_route,
        "release-route-receipt.json": route_closure,
        "released-runtime-transition.json": runtime,
        "s1-check.json": {
            "s0_receipt": s0,
            "release_gate_receipts": {
                "full_regression": full,
                "release_security_review": security,
            },
            "s1_receipt": s1,
        },
        "s2-build.json": {},
        "asset-validation.json": {
            "s2_receipt": s2,
            "asset_integrity_validation_receipt": integrity,
        },
        "repository-boundary.json": boundary,
        "repository-boundary-pre-s4.json": boundary,
        "s3.json": s3,
        "release-control.json": control,
        "s4-authorized-operation-plan.json": {
            "status": "authorized_operation_plan_not_executed",
            "publish_state": "authorized_not_executed",
            "external_side_effect_count": 0,
            "action_executed": False,
            "operation_plan_authorized": True,
            "source_commit": SOURCE,
            "source_git_tree": TREE,
            "release_control_sha256": control["release_control_sha256"],
            "authorization_id": auth["authorization_id"],
            "asset_set_id": s2["asset_set_id"],
            "asset_set_digest": s2["asset_set_digest"],
            "check_state": "not_started",
            "run_outcome": "not_run",
            "evidence_state": "not_created",
            "ok": False,
            "passed": False,
            "additional_user_confirmation_required": False,
            "https_git_fallback_allowed": False,
        },
    }
    for name, value in values.items():
        (receipt_root / name).write_text(
            json.dumps(value, sort_keys=True), encoding="utf-8"
        )
    outcomes = {
        phase: "success" for phase in skill_release.V250_CONTINUATION_PHASE_ORDER
    }
    return receipt_root, release_root, outcomes


class TestV250ReleaseControl(unittest.TestCase):
    def test_release_flow_replays_stale_runner_paths_from_portable_triplet(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = observe_runtime_transition(root)
            source_paths = {
                "route_facts_receipt_path_override": (
                    root / "docs/release-route-facts.json"
                ),
                "derived_route_receipt_path_override": (
                    root / "docs/release-route-derived.json"
                ),
                "route_receipt_path_override": (
                    root / "docs/release-route-receipt.json"
                ),
                "authorization_receipt_path_override": (
                    root / "docs/authorization-receipt.json"
                ),
            }
            portable_root = root / "downloaded"
            portable_root.mkdir()
            portable_inputs: dict[str, Path] = {}
            for override_name, source_path in source_paths.items():
                target = portable_root / source_path.name
                target.write_bytes(source_path.read_bytes())
                portable_inputs[override_name] = target

            runtime["route_facts_receipt_path"] = (
                "/home/runner/work/_temp/release-route-facts.json"
            )
            runtime["derived_route_receipt_path"] = (
                "/home/runner/work/_temp/release-route-derived.json"
            )
            runtime["route_receipt_path"] = (
                "/home/runner/work/_temp/release-route-receipt.json"
            )
            runtime["authorization_receipt_path"] = (
                "/home/runner/work/_temp/authorization.json"
            )
            runtime["receipt_sha256"] = runtime_transition._canonical_sha256(
                runtime
            )

            def actual_validator(receipt: object, **kwargs: object) -> dict:
                with mock.patch.object(
                    runtime_transition,
                    "_verify_handoff_signature",
                    return_value=True,
                ):
                    return runtime_transition.validate_transition(
                        receipt,
                        root=root,
                        **kwargs,
                    )

            with mock.patch.object(
                release_flow,
                "validate_runtime_transition",
                side_effect=actual_validator,
            ):
                stale = release_flow._runtime_transition_errors(
                    runtime,
                    SOURCE,
                    TREE,
                )
                portable = release_flow._runtime_transition_errors(
                    runtime,
                    SOURCE,
                    TREE,
                    **portable_inputs,
                )
                incomplete = {
                    missing: release_flow._runtime_transition_errors(
                        runtime,
                        SOURCE,
                        TREE,
                        **{
                            name: path
                            for name, path in portable_inputs.items()
                            if name != missing
                        },
                    )
                    for missing in portable_inputs
                }

        self.assertIn("E_V250_RELEASED_RUNTIME_S0_REQUIRED", stale)
        self.assertEqual([], portable)
        for missing, errors in incomplete.items():
            with self.subTest(missing=missing):
                self.assertIn("E_V250_RELEASED_RUNTIME_S0_REQUIRED", errors)

    def test_s4_revalidates_handoff_at_recorded_transition_time(self) -> None:
        captured_at = "2026-08-01T08:00:00+00:00"
        receipt = {"captured_at": captured_at}
        portable_inputs = {
            "route_facts_receipt_path_override": Path(
                "/portable/release-route-facts.json"
            ),
            "derived_route_receipt_path_override": Path(
                "/portable/release-route-derived.json"
            ),
            "route_receipt_path_override": Path(
                "/portable/release-route-receipt.json"
            ),
            "authorization_receipt_path_override": Path(
                "/portable/authorization.json"
            ),
        }
        with mock.patch.object(
            release_flow,
            "validate_runtime_transition",
            return_value={"ok": True, "may_enter_s0": True, "errors": []},
        ) as validator:
            errors = release_flow._runtime_transition_errors(
                receipt,
                SOURCE,
                TREE,
                **portable_inputs,
            )

        self.assertEqual([], errors)
        self.assertEqual(
            dt.datetime.fromisoformat(captured_at),
            validator.call_args.kwargs["validation_time"],
        )
        for name, path in portable_inputs.items():
            self.assertEqual(path, validator.call_args.kwargs[name])

    def test_release_control_forwards_complete_portable_runtime_inputs(self) -> None:
        control = control_receipt()
        portable_inputs = {
            "runtime_route_facts_receipt_path": Path(
                "/portable/release-route-facts.json"
            ),
            "runtime_derived_route_receipt_path": Path(
                "/portable/release-route-derived.json"
            ),
            "runtime_route_receipt_path": Path(
                "/portable/release-route-receipt.json"
            ),
            "runtime_authorization_receipt_path": Path(
                "/portable/authorization.json"
            ),
        }
        runtime_validator = mock.Mock(side_effect=fixture_runtime_validation)
        with (
            mock.patch.object(
                release_flow,
                "validate_runtime_transition",
                runtime_validator,
            ),
            mock.patch.object(
                release_flow,
                "_security_review_git_snapshot",
                return_value=security_git_snapshot(),
            ),
        ):
            verdict = release_flow.validate_release_control_receipt(
                control,
                expected_repository="vibe-coding-era/goal-teams",
                expected_version="V2.63",
                expected_candidate_branch="codex/develop-v2.63",
                expected_tag="v2.63",
                expected_source_commit=SOURCE,
                expected_source_tree=TREE,
                validation_time=NOW,
                **portable_inputs,
            )

        self.assertTrue(verdict["ok"])
        self.assertEqual(
            portable_inputs["runtime_route_facts_receipt_path"],
            runtime_validator.call_args.kwargs[
                "route_facts_receipt_path_override"
            ],
        )
        self.assertEqual(
            portable_inputs["runtime_derived_route_receipt_path"],
            runtime_validator.call_args.kwargs[
                "derived_route_receipt_path_override"
            ],
        )
        self.assertEqual(
            portable_inputs["runtime_route_receipt_path"],
            runtime_validator.call_args.kwargs["route_receipt_path_override"],
        )
        self.assertEqual(
            portable_inputs["runtime_authorization_receipt_path"],
            runtime_validator.call_args.kwargs[
                "authorization_receipt_path_override"
            ],
        )

    def test_runtime_external_anchor_tracks_the_complete_dynamic_input_set(self) -> None:
        activation_path = (
            "references/current/generations/V2.63/activation-manifest.json"
        )
        prompt_manifest_path = (
            "references/current/generations/V2.63/prompt-manifest.json"
        )
        current_paths = [
            "references/current/generations/V2.63/core.md",
            "references/current/generations/V2.63/functions/release-operations.md",
        ]
        self.assertEqual(
            set(runtime_transition.REQUIRED_STATIC_INPUT_PATHS),
            set(skill_release.V250_RUNTIME_STATIC_INPUT_PATHS),
        )
        expected_paths = (
            set(skill_release.V250_RUNTIME_STATIC_INPUT_PATHS)
            | {
                runtime_transition.ACTIVE_PATH,
                activation_path,
                prompt_manifest_path,
                *current_paths,
            }
        )
        contents = {path: f"content:{path}".encode() for path in expected_paths}
        contents[activation_path] = json.dumps(
            {"prompt_manifest_path": prompt_manifest_path},
            sort_keys=True,
        ).encode()
        digests = {
            path: hashlib.sha256(raw).hexdigest()
            for path, raw in contents.items()
        }
        runtime = {
            "input_digests": digests,
            "loaded_paths": sorted(digests),
            "current_loaded_paths": current_paths,
            "current_input_digests": {
                path: digests[path] for path in current_paths
            },
        }

        observed = skill_release._validate_v250_runtime_external_anchor(
            runtime=runtime,
            activation_path=activation_path,
            frozen_bytes=lambda path: contents[path],
        )

        self.assertEqual(digests, observed)

        runtime["loaded_paths"] = sorted(digests)[:-1]
        with self.assertRaisesRegex(
            skill_release.SkillReleaseError, "E_V263_RUNTIME_EXTERNAL_ANCHOR"
        ):
            skill_release._validate_v250_runtime_external_anchor(
                runtime=runtime,
                activation_path=activation_path,
                frozen_bytes=lambda path: contents[path],
            )

    def test_exact_large_release_runtime_closure_is_accepted_by_preflight(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with inactive_candidate_fixture(root) as fixture:
            generation = load_candidate_generation(
                fixture.root,
                generation_id="V2.63",
                activation_manifest_path=fixture.activation_path,
                expected_activation_sha256=fixture.activation_sha256,
            )
            route = compile_derived_route_closure(
                fixture.root,
                generation,
                derive_route(
                    {
                        "project_size": "large",
                        "workflow_phase": "release",
                        "stage": "released",
                        "release_intent": True,
                        "implementation_scope_complete": True,
                        "risk": "high",
                        "failure_consequence": "high",
                        "reversibility": "partially_reversible",
                        "compliance": "none",
                        "external_write": True,
                        "security_sensitive": True,
                        "ui_or_desktop": False,
                        "agent_runtime": True,
                        "environment_check_required": True,
                        "authorization_state": "granted",
                        "facts_source_sha256": "a" * 64,
                    }
                ),
            )
            activation_path = generation["activation_manifest_path"]
            prompt_manifest_path = generation["activation_manifest"][
                "prompt_manifest_path"
            ]
            expected_paths = (
                set(runtime_transition.REQUIRED_STATIC_INPUT_PATHS)
                | {
                    runtime_transition.ACTIVE_PATH,
                    activation_path,
                    prompt_manifest_path,
                    *route["loaded_paths"],
                }
            )
            self.assertEqual(30, len(expected_paths))
            digests = {
                path: hashlib.sha256((fixture.root / path).read_bytes()).hexdigest()
                for path in expected_paths
            }
            runtime = {
                "input_digests": digests,
                "loaded_paths": sorted(digests),
                "current_loaded_paths": route["loaded_paths"],
                "current_input_digests": {
                    path: digests[path] for path in route["loaded_paths"]
                },
            }

            observed = skill_release._validate_v250_runtime_external_anchor(
                runtime=runtime,
                activation_path=activation_path,
                frozen_bytes=lambda path: (fixture.root / path).read_bytes(),
            )

            self.assertEqual(digests, observed)

    def test_s0_uses_shared_strict_runtime_validator_and_rejects_weak_entry(self) -> None:
        runtime = transition()
        strict_failure = {
            "ok": False,
            "passed": False,
            "errors": ["E_V250_CONTROLLER_HANDOFF_REQUIRED"],
            "may_enter_s0": False,
        }
        with (
            mock.patch.object(
                release_flow,
                "validate_runtime_transition",
                return_value=strict_failure,
                create=True,
            ) as validator,
            self.assertRaisesRegex(ValueError, "E_V250_RELEASED_RUNTIME_S0_REQUIRED"),
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
        with self.assertRaisesRegex(ValueError, "E_V250_RELEASED_RUNTIME_S0_REQUIRED"):
            release_flow.build_s0_receipt(
                source_commit=SOURCE,
                source_tree=TREE,
                runtime_transition=runtime,
                expected_host_execution_id="GITHUB-RUN-1",
            )

    def test_s0_rejects_swapped_runtime_version_axes(self) -> None:
        runtime = transition()
        runtime["previous_controller_product_version"] = "V2.63"
        runtime["loaded_runtime_product_version"] = "V2.48"
        runtime["receipt_sha256"] = release_flow._receipt_sha256(runtime)
        with self.assertRaisesRegex(ValueError, "E_V250_RELEASED_RUNTIME_S0_REQUIRED"):
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
        self.assertIn("E_V250_S2_RECEIPT_DIGEST", verdict["errors"])

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
        self.assertIn("E_V250_AUTHORIZATION_ACTION_DRIFT", verdict["errors"])

    def test_authorization_rejects_unexpected_persisted_fields(self) -> None:
        for location in ("top", "repository"):
            with self.subTest(location=location):
                value = authorization()
                if location == "top":
                    value["access_token"] = "must-not-be-persisted"
                else:
                    value["repository"]["private_note"] = "must-not-be-persisted"
                verdict = release_flow.validate_project_start_authorization(
                    value,
                    repository="vibe-coding-era/goal-teams",
                    version="V2.63",
                    candidate_branch="codex/develop-v2.63",
                    tag="v2.63",
                    validation_time=NOW,
                )
                self.assertFalse(verdict["ok"])
                self.assertIn(
                    "E_V250_AUTHORIZATION_UNEXPECTED_FIELD", verdict["errors"]
                )

        value = authorization()
        del value["repository"]["id"]
        value["intent"]["repository_id"] = None
        value["intent_sha256"] = release_flow.canonical_sha256(value["intent"])
        verdict = release_flow.validate_project_start_authorization(
            value,
            repository="vibe-coding-era/goal-teams",
            version="V2.63",
            candidate_branch="codex/develop-v2.63",
            tag="v2.63",
            validation_time=NOW,
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_AUTHORIZATION_UNEXPECTED_FIELD", verdict["errors"])

        malformed = authorization()
        malformed["locked_scope"] = None
        malformed["intent"]["locked_scope"] = None
        malformed["intent_sha256"] = release_flow.canonical_sha256(
            malformed["intent"]
        )
        malformed["action_allowlist"] = [{"unexpected": "object"}]
        verdict = release_flow.validate_project_start_authorization(
            malformed,
            repository="vibe-coding-era/goal-teams",
            version="V2.63",
            candidate_branch="codex/develop-v2.63",
            tag="v2.63",
            validation_time=NOW,
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_AUTHORIZATION_IDENTITY_DRIFT", verdict["errors"])
        self.assertIn("E_V250_AUTHORIZATION_ACTION_DRIFT", verdict["errors"])

        nested_secret = authorization()
        nested_secret["credential_policy"] = {"access_token": "forbidden"}
        verdict = release_flow.validate_project_start_authorization(
            nested_secret,
            repository="vibe-coding-era/goal-teams",
            version="V2.63",
            candidate_branch="codex/develop-v2.63",
            tag="v2.63",
            validation_time=NOW,
        )
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_AUTHORIZATION_FIELD_TYPE", verdict["errors"])

    def test_continuation_checkpoint_requires_complete_ready_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt_root, release_root, outcomes = checkpoint_fixture(Path(temp))
            with (
                mock.patch.object(
                    skill_release,
                    "_read_identity",
                    return_value={"source_git_tree": TREE},
                ),
                mock.patch.object(
                    skill_release,
                    "validate_v250_s4_control",
                    return_value={"ok": True, "errors": []},
                ),
            ):
                checkpoint = skill_release.build_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    project_size="large",
                    job_status="success",
                    workflow_run_id="1001",
                    workflow_run_attempt="1",
                    gate_outcomes=outcomes,
                    receipt_source_root=receipt_root,
                    release_root=release_root,
                )
            self.assertEqual("ready_for_s4", checkpoint["state"])
            self.assertEqual("release_asset_chain_only", checkpoint["claim_scope"])
            self.assertEqual({}, checkpoint["diagnostic_files"])
            self.assertEqual([], checkpoint["missing_files"])
            self.assertEqual(4, len(checkpoint["public_assets"]))
            self.assertEqual(
                set(skill_release.V263_CONTINUATION_FORMAL_RECEIPTS),
                set(checkpoint["formal_files"]),
            )
            self.assertTrue(checkpoint["resumable_without_rebuild"])

            (receipt_root / "release-control.json").write_text(
                "not-json", encoding="utf-8"
            )
            with mock.patch.object(
                skill_release,
                "_read_identity",
                return_value={"source_git_tree": TREE},
            ):
                partial = skill_release.build_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    project_size="large",
                    job_status="success",
                    workflow_run_id="1001",
                    workflow_run_attempt="1",
                    gate_outcomes=outcomes,
                    receipt_source_root=receipt_root,
                    release_root=release_root,
                )
            self.assertEqual("diagnostic_partial", partial["state"])
            self.assertEqual("checkpoint_validation", partial["first_failed_phase"])
            self.assertEqual({}, partial["formal_files"])
            self.assertFalse(partial["resumable_without_rebuild"])

    def test_continuation_checkpoint_uses_explicit_step_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt_root, release_root, outcomes = checkpoint_fixture(Path(temp))
            outcomes["s4_plan"] = "failure"
            (receipt_root / "plan-output.json").write_text(
                json.dumps(
                    {
                        "command": "authorize_s4_plan",
                        "status": "failed",
                        "error_code": "E_TEST",
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                skill_release,
                "_read_identity",
                return_value={"source_git_tree": TREE},
            ):
                checkpoint = skill_release.build_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    project_size="large",
                    job_status="failure",
                    workflow_run_id="1002",
                    workflow_run_attempt="1",
                    gate_outcomes=outcomes,
                    receipt_source_root=receipt_root,
                    release_root=release_root,
                )
            self.assertEqual("diagnostic_partial", checkpoint["state"])
            self.assertEqual("s4_plan", checkpoint["first_failed_phase"])
            self.assertEqual("failure", checkpoint["failure_outcome"])
            self.assertIn("plan-output.json", checkpoint["diagnostic_files"])
            self.assertEqual({}, checkpoint["formal_files"])

    def test_ready_checkpoint_consumer_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt_root, release_root, outcomes = checkpoint_fixture(Path(temp))
            with (
                mock.patch.object(
                    skill_release,
                    "_read_identity",
                    return_value={"source_git_tree": TREE},
                ),
                mock.patch.object(
                    skill_release,
                    "validate_v250_s4_control",
                    return_value={"ok": True, "errors": []},
                ),
            ):
                checkpoint = skill_release.build_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    project_size="large",
                    job_status="success",
                    workflow_run_id="1003",
                    workflow_run_attempt="1",
                    gate_outcomes=outcomes,
                    receipt_source_root=receipt_root,
                    release_root=release_root,
                )
                (receipt_root / "_checkpoint.json").write_text(
                    json.dumps(checkpoint, sort_keys=True), encoding="utf-8"
                )
                verdict = skill_release.validate_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    checkpoint,
                    receipt_root=receipt_root,
                    release_root=release_root,
                    expected_workflow_run_id="1003",
                    expected_workflow_run_attempt="1",
                )
                self.assertTrue(verdict["passed"], verdict["errors"])

                forged_summary = copy.deepcopy(checkpoint)
                forged_summary["asset_set_digest"] = "f" * 64
                forged_summary.pop("checkpoint_sha256")
                forged_summary["checkpoint_sha256"] = release_flow.canonical_sha256(
                    forged_summary
                )
                summary_verdict = (
                    skill_release.validate_v250_continuation_checkpoint(
                        "V2.63",
                        SOURCE,
                        forged_summary,
                        receipt_root=receipt_root,
                        release_root=release_root,
                        expected_workflow_run_id="1003",
                        expected_workflow_run_attempt="1",
                    )
                )
                self.assertIn(
            "E_V263_CONTINUATION_SUMMARY_BINDING",
                    summary_verdict["errors"],
                )

                forged_route = copy.deepcopy(checkpoint)
                forged_route["project_size"] = "small"
                forged_route["gate_outcomes"] = {
                    phase: "failure"
                    for phase in skill_release.V250_CONTINUATION_PHASE_ORDER
                }
                forged_route["workflow_run_id"] = ""
                forged_route["workflow_run_attempt"] = ""
                forged_route.pop("checkpoint_sha256")
                forged_route["checkpoint_sha256"] = release_flow.canonical_sha256(
                    forged_route
                )
                route_verdict = (
                    skill_release.validate_v250_continuation_checkpoint(
                        "V2.63",
                        SOURCE,
                        forged_route,
                        receipt_root=receipt_root,
                        release_root=release_root,
                        expected_workflow_run_id="1003",
                        expected_workflow_run_attempt="1",
                    )
                )
                self.assertIn(
            "E_V263_CONTINUATION_GATE_OUTCOMES",
                    route_verdict["errors"],
                )
                self.assertIn(
                    "E_V263_CONTINUATION_CHECKPOINT_IDENTITY",
                    route_verdict["errors"],
                )

                plan_path = receipt_root / "s4-authorized-operation-plan.json"
                original_plan = plan_path.read_text(encoding="utf-8")
                forged_plan_value = json.loads(original_plan)
                forged_plan_value.update(
                    {
                        "publish_state": "published",
                        "operation_plan_authorized": False,
                        "source_commit": "a" * 40,
                        "source_git_tree": "b" * 40,
                    }
                )
                plan_path.write_text(
                    json.dumps(forged_plan_value, sort_keys=True), encoding="utf-8"
                )
                forged_plan_checkpoint = copy.deepcopy(checkpoint)
                forged_plan_checkpoint["formal_files"][plan_path.name] = {
                    "size": plan_path.stat().st_size,
                    "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                }
                forged_plan_checkpoint.pop("checkpoint_sha256")
                forged_plan_checkpoint["checkpoint_sha256"] = (
                    release_flow.canonical_sha256(forged_plan_checkpoint)
                )
                plan_verdict = skill_release.validate_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    forged_plan_checkpoint,
                    receipt_root=receipt_root,
                    release_root=release_root,
                    expected_workflow_run_id="1003",
                    expected_workflow_run_attempt="1",
                )
                self.assertIn(
                    "E_V263_CONTINUATION_PLAN_CONTRACT", plan_verdict["errors"]
                )
                plan_path.write_text(original_plan, encoding="utf-8")

                auth_path = receipt_root / "authorization.json"
                original_auth = auth_path.read_text(encoding="utf-8")
                auth_path.write_text("{}", encoding="utf-8")
                forged_auth_checkpoint = copy.deepcopy(checkpoint)
                forged_auth_checkpoint["formal_files"][auth_path.name] = {
                    "size": auth_path.stat().st_size,
                    "sha256": hashlib.sha256(auth_path.read_bytes()).hexdigest(),
                }
                forged_auth_checkpoint["authorization_receipt_sha256"] = (
                    release_flow.canonical_sha256({})
                )
                forged_auth_checkpoint.pop("checkpoint_sha256")
                forged_auth_checkpoint["checkpoint_sha256"] = (
                    release_flow.canonical_sha256(forged_auth_checkpoint)
                )
                auth_verdict = skill_release.validate_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    forged_auth_checkpoint,
                    receipt_root=receipt_root,
                    release_root=release_root,
                    expected_workflow_run_id="1003",
                    expected_workflow_run_attempt="1",
                )
                self.assertIn(
                    "E_V263_CHECKPOINT_RECEIPT_BINDING", auth_verdict["errors"]
                )
                auth_path.write_text(original_auth, encoding="utf-8")

                tar_path = (
                    release_root
                    / "V2.63"
                    / "_artifacts"
                    / "goal-teams-V2.63.tar.gz"
                )
                original_tar = tar_path.read_bytes()
                tar_path.write_bytes(b"tampered-asset")
                forged_assets = copy.deepcopy(checkpoint)
                forged_assets["public_assets"]["goal-teams-V2.63.tar.gz"] = {
                    "size": tar_path.stat().st_size,
                    "sha256": hashlib.sha256(tar_path.read_bytes()).hexdigest(),
                }
                forged_assets.pop("checkpoint_sha256")
                forged_assets["checkpoint_sha256"] = release_flow.canonical_sha256(
                    forged_assets
                )
                asset_verdict = skill_release.validate_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    forged_assets,
                    receipt_root=receipt_root,
                    release_root=release_root,
                    expected_workflow_run_id="1003",
                    expected_workflow_run_attempt="1",
                )
                self.assertIn(
                    "E_V263_CONTINUATION_ASSET_BINDING", asset_verdict["errors"]
                )
                tar_path.write_bytes(original_tar)

                (receipt_root / "s1-check.json").write_text("{}", encoding="utf-8")
                tampered = skill_release.validate_v250_continuation_checkpoint(
                    "V2.63",
                    SOURCE,
                    checkpoint,
                    receipt_root=receipt_root,
                    release_root=release_root,
                    expected_workflow_run_id="1003",
                    expected_workflow_run_attempt="1",
                )
            self.assertFalse(tampered["passed"])
            self.assertIn(
                "E_V263_CONTINUATION_RECEIPT_DIGEST", tampered["errors"]
            )

    def test_non_large_checkpoint_requires_large_s3_steps_to_be_skipped(self) -> None:
        outcomes = {
            phase: "success"
            for phase in skill_release.V250_CONTINUATION_PHASE_ORDER
        }
        self.assertIn(
            "E_V263_CHECKPOINT_GATE_OUTCOME",
            skill_release._checkpoint_gate_errors(
                project_size="medium",
                gate_outcomes=outcomes,
                version="V2.63",
            ),
        )
        for phase in skill_release.V250_CONTINUATION_LARGE_ONLY_PHASES:
            outcomes[phase] = "skipped"
        self.assertEqual(
            [],
            skill_release._checkpoint_gate_errors(
                project_size="medium",
                gate_outcomes=outcomes,
                version="V2.63",
            ),
        )

    def test_resealed_runtime_or_security_summary_is_not_accepted(self) -> None:
        control = control_receipt()
        runtime = control["released_runtime_transition"]
        runtime["loaded_paths"] = []
        runtime["receipt_sha256"] = release_flow._receipt_sha256(runtime)
        control["release_control_sha256"] = release_flow._receipt_sha256(control)
        verdict = validate(control)
        self.assertFalse(verdict["ok"])
        self.assertIn("E_V250_RELEASED_RUNTIME_S0_REQUIRED", verdict["errors"])

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
        self.assertIn("E_V250_SECURITY_REVIEW_CONTRACT", verdict["errors"])

    def test_self_consistent_reviewed_file_forgery_fails_exact_git_object(self) -> None:
        security = security_review()
        target = next(
            item
            for item in security["reviewed_files"]
            if item["path"] == "scripts/v250/s4_executor.py"
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
        self.assertIn("E_V250_SECURITY_REVIEW_CONTRACT", verdict["errors"])

    def test_authorized_publish_command_is_only_a_not_run_plan(self) -> None:
        control = control_receipt()
        config = {
            "candidate_branch": "codex/develop-v2.63",
            "tag": "v2.63",
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
                skill_release, "_v250_release_flow_module", return_value=release_flow
            ),
            mock.patch.object(
                skill_release,
                "_validate_v250_external_anchors",
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
                "V2.63", SOURCE, release_control_receipt=control
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
            "candidate_branch": "codex/develop-v2.63",
            "tag": "v2.63",
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
                "_validate_v250_external_anchors",
                return_value=control_receipt()["external_anchor_validation"],
            ),
        ):
            receipt = skill_release.publish(
                "V2.63", SOURCE, release_control_receipt=control
            )

        self.assertFalse(receipt["ok"])
        self.assertFalse(receipt["passed"])
        self.assertEqual("blocked", receipt["publish_state"])
        self.assertEqual("E_V263_EXTERNAL_ANCHOR_REVALIDATION", receipt["error_code"])


if __name__ == "__main__":
    unittest.main()
