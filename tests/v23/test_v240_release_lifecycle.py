"""Pre-implementation contracts for the Goal Teams V2.40 release lifecycle.

These tests intentionally describe the public release-policy boundary before the
V2.40 implementation exists.  GitHub is never contacted.  Mutable host facts are
provided as data and every successful result must expose a business receipt; a
process exit code alone is never accepted as release Evidence.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from tests.v23.common import ROOT


RELEASE_ENTRY = ROOT / "scripts" / "release" / "release.py"
AUDIT_ENTRY = ROOT / "scripts" / "release" / "audit-release.py"
BUILD_ENTRY = ROOT / "scripts" / "release" / "build-release.py"
VALIDATE_ENTRY = ROOT / "scripts" / "release" / "validate-release.py"
README_START = "<!-- goal-teams-release:start -->"
README_END = "<!-- goal-teams-release:end -->"
VERSION = "V2.40"
TAG = "v2.40"
BASE_COMMIT = "a" * 40
CANDIDATE_COMMIT = "b" * 40
ARTIFACT_SHA256 = "c" * 64
V240_SPEC_ROOT = ROOT / "GoalTeamsWork-V2.40" / "versions" / VERSION / "spec"
PROMOTION_STATE_CONTRACT = ROOT / "schemas" / "release-promotion-state.schema.json"
LOCAL_PROMOTION_STATE_CONTRACT = V240_SPEC_ROOT / "promotion-state-contract.json"
TEST_CASE_CONTRACTS = (
    ROOT
    / "tests"
    / "v23"
    / "fixtures"
    / "v240"
    / "release-lifecycle-contracts.json"
)
LOCAL_IGNORED_TEST_CASE_CONTRACTS = V240_SPEC_ROOT / "test-case-contracts.json"
CP07_QUALITY_GATE_COMMAND_SET = (
    ("scripts/check.sh",),
    ("$PYTHON", "scripts/checks/check-v23.py"),
    ("$PYTHON", "scripts/benchmark/benchmark-runner.py", "--check-only"),
    ("$PYTHON", "scripts/checks/check-install-lifecycle.py"),
)

PROMOTION_OPERATION_PLAN: dict[str, tuple[tuple[str, str], ...]] = {
    "CP00": (("CP00.scope_freeze", "local_validate"),),
    "CP01": (("CP01.legacy_recovery", "local_validate"),),
    "CP02": (("CP02.topology_validate", "local_validate"),),
    "CP03": (
        ("CP03.github_authority_readback", "github_authority_verify"),
        ("CP03.immutable_release_enable", "immutable_release_enable"),
        ("CP03.ruleset_capability_verify", "ruleset_capability_verify"),
    ),
    "CP04": (("CP04.development_identity", "local_validate"),),
    "CP05": (
        ("CP05.contract_validate", "local_validate"),
        ("CP05.workflow_approve", "local_validate"),
    ),
    "CP06": (("CP06.static_gates", "local_validate"),),
    "CP07": (("CP07.quality_gates", "local_validate"),),
    "CP08": (
        ("CP08.candidate_identity", "local_validate"),
        ("CP08.rc_commit", "rc_commit"),
    ),
    "CP09": (
        ("CP09.build_primary", "local_build"),
        ("CP09.build_reproducibility", "local_build"),
    ),
    "CP10": (
        ("CP10.asset_validate", "local_validate"),
        ("CP10.snapshot_seal", "local_snapshot_seal"),
    ),
    "CP11": (
        ("CP11.local_bundle_rehearsal", "local_install_rehearsal"),
    ),
    "CP12": (("CP12.candidate_push", "candidate_push"),),
    "CP13": (("CP13.candidate_ci", "ci_wait"),),
    "CP14": (
        ("CP14.github_authority_revalidate", "github_authority_verify"),
        ("CP14.main_promotion_lock", "promotion_lock_create"),
        ("CP14.immutable_release_verify", "immutable_release_verify"),
        ("CP14.tag_ruleset", "tag_ruleset_create"),
        ("CP14.promotion_lease", "local_validate"),
    ),
    "CP15": (("CP15.tag_push", "tag_push"),),
    "CP16": (
        ("CP16.draft_create", "draft_create"),
        ("CP16.asset_upload_tar", "asset_upload"),
        ("CP16.asset_upload_sums", "asset_upload"),
        ("CP16.asset_upload_release", "asset_upload"),
        ("CP16.asset_upload_files", "asset_upload"),
        ("CP16.asset_download_verify", "asset_download_verify"),
        ("CP16.remote_bundle_rehearsal", "local_install_rehearsal"),
    ),
    "CP17": (
        ("CP17.main_promote", "main_promote"),
        ("CP17.release_publish", "release_publish"),
        ("CP17.published_asset_download", "published_asset_download"),
        ("CP17.actual_install", "actual_install"),
        ("CP17.post_release_ci", "post_release_ci"),
        ("CP17.independent_audit", "independent_audit"),
    ),
    "CP18": (
        ("CP18.promotion_lock_finalize", "promotion_lock_finalize"),
        ("CP18.archive_close", "archive_close"),
    ),
}

CHECKPOINT_PHASE = {
    "CP00": "DRIFTED",
    "CP01": "RECOVERED",
    "CP02": "DEV_OPEN",
    "CP03": "DEV_OPEN",
    "CP04": "DEV_OPEN",
    "CP05": "DEV_OPEN",
    "CP06": "DEV_OPEN",
    "CP07": "DEV_OPEN",
    "CP08": "RC_FROZEN",
    "CP09": "RC_VALIDATED",
    "CP10": "RC_VALIDATED",
    "CP11": "RC_VALIDATED",
    "CP12": "RC_VALIDATED",
    "CP13": "CANDIDATE_CI_GREEN",
    "CP14": "PROMOTION_LOCKED",
    "CP15": "TAG_PUSHED",
    "CP16": "DRAFT_VERIFIED",
    "CP17": "INSTALLED_VERIFIED",
    "CP18": "CLOSED",
}

GITHUB_AUTHORIZED_ACTIONS = (
    "read_repository",
    "read_refs",
    "read_workflows",
    "read_releases",
    "read_rulesets",
    "enable_immutable_releases",
    "manage_promotion_ruleset",
    "manage_tag_ruleset",
    "push_candidate",
    "push_tag",
    "promote_main",
    "create_release_draft",
    "upload_release_assets",
    "publish_release",
    "dispatch_workflow",
)

EXTERNAL_ACTIONS_REQUIRE_EXPECTED_BEFORE = {
    "github_authority_verify",
    "immutable_release_enable",
    "immutable_release_verify",
    "ruleset_capability_verify",
    "tag_ruleset_create",
    "candidate_push",
    "ci_wait",
    "promotion_lock_create",
    "tag_push",
    "draft_create",
    "asset_upload",
    "asset_download_verify",
    "main_promote",
    "release_publish",
    "published_asset_download",
    "actual_install",
    "post_release_ci",
    "independent_audit",
    "promotion_lock_finalize",
}


def _load_optional(name: str, path: Path):
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release = _load_optional("goalteams_v240_release_test", RELEASE_ENTRY)
audit = _load_optional("goalteams_v240_release_audit_test", AUDIT_ENTRY)
build_release = _load_optional("goalteams_v240_build_release_test", BUILD_ENTRY)
validate_release = _load_optional("goalteams_v240_validate_release_test", VALIDATE_ENTRY)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _release_block(version: str = VERSION, *, current_link: bool = True) -> str:
    link = (
        "[release/current/README.md](release/current/README.md)"
        if current_link
        else "release notes unavailable"
    )
    return (
        f"{README_START}\n"
        f"Current release: **{version}** · "
        f"[GitHub Release](https://github.com/vibe-coding-era/goal-teams/releases/tag/{version.lower()}) "
        f"· {link}\n"
        f"{README_END}\n"
    )


def _write_readmes(root: Path, *, zh: str | None = None, en: str | None = None) -> None:
    (root / "README.md").write_text(
        "# Goal Teams\n\n" + (zh if zh is not None else _release_block()),
        encoding="utf-8",
    )
    (root / "README.en.md").write_text(
        "# Goal Teams\n\n" + (en if en is not None else _release_block()),
        encoding="utf-8",
    )


def _workspace_facts() -> dict[str, Any]:
    return {
        "canonical_root_role": "stable",
        "canonical_branch": "main",
        "candidate_location": "develops/v2.40",
        "candidate_branch": "codex/v2.40",
        "expected_candidate_branch": "codex/v2.40",
        "dirty": False,
        "candidate_commit": CANDIDATE_COMMIT,
        "remote_main_commit": BASE_COMMIT,
        "candidate_descends_from_remote_main": True,
        "tracked_local_only_paths": [],
        "parent_version_copies": [],
        "tag_exists": False,
        "release_exists": False,
        "tools": {"git": True, "gh": True, "python_3_11": True},
    }


def _ci_run(stage: str, run_id: int, created_at: str) -> dict[str, Any]:
    result = {
        "stage": stage,
        "workflow_path": ".github/workflows/release-gate.yml",
        "workflow_raw_path": ".github/workflows/release-gate.yml",
        "workflow_raw_ref": None,
        "workflow_blob_sha": "f" * 40,
        "workflow_approval_sha256": "6" * 64,
        "workflow_id": 240,
        "run_id": run_id,
        "run_attempt": 1,
        "event": "push" if stage == "candidate" else "workflow_dispatch",
        "actor_id": 240,
        "triggering_actor_id": 240,
        "head_sha": CANDIDATE_COMMIT,
        "jobs": [
            {
                "name": name,
                "head_sha": CANDIDATE_COMMIT,
                "conclusion": "success",
            }
            for name in ("check-ubuntu", "check-macos", "release-asset-gate")
        ],
        "created_at": created_at,
    }
    if stage == "post_release":
        result["release_intent"] = "a" * 64
        result["display_title"] = f"Goal Teams V2.40 release {'a' * 64}"
    return result


def _promotion_public_scan_bindings(now: str) -> dict[str, Any]:
    assertion_set = "a" * 64
    occurrence_set = "b" * 64
    review = {
        "reviewer_type": "independent_release_reviewer",
        "independent": True,
        "decision": "accepted",
        "review_id": "review-v240",
        "reviewer_member_id": "scanner-reviewer-v240",
        "reviewer_run_id": "RUN-V240-SCANNER-REVIEW",
        "assertion_set_sha256": assertion_set,
        "occurrence_set_sha256": occurrence_set,
        "reviewed_at": now,
    }
    return {
        "candidate_commit": CANDIDATE_COMMIT,
        "candidate_tree": "d" * 40,
        "base_main_commit": BASE_COMMIT,
        "scanner_path": "scripts/release/public_scan.py",
        "scanner_blob_sha256": "1" * 64,
        "detector_path": "scripts/v23/v236_security.py",
        "detector_blob_sha256": "2" * 64,
        "baseline_path": "references/public-release-scan-baseline-v2.40.json",
        "baseline_blob_sha256": "3" * 64,
        "baseline_assertion_count": 4,
        "baseline_assertions_sha256": "4" * 64,
        "baseline_assertion_set_sha256": assertion_set,
        "baseline_occurrence_set_sha256": occurrence_set,
        "baseline_review": review,
        "baseline_review_sha256": _canonical_json_sha256(review),
    }


def _promotion_ci_approval(now: str) -> dict[str, Any]:
    bindings = _promotion_public_scan_bindings(now)
    review = bindings["baseline_review"]
    return {
        "release_actor_id": 240,
        "reviewer": {
            "role": review["reviewer_type"],
            "member_id": review["reviewer_member_id"],
            "run_id": review["reviewer_run_id"],
            "independent": review["independent"],
            "decision": review["decision"],
            "review_id": review["review_id"],
            "source_commit": CANDIDATE_COMMIT,
            "candidate_tree": "d" * 40,
            "assertion_set_sha256": review["assertion_set_sha256"],
            "occurrence_set_sha256": review["occurrence_set_sha256"],
            "reviewed_at": review["reviewed_at"],
        },
        "head_sha": CANDIDATE_COMMIT,
        "workflow_path": ".github/workflows/release-gate.yml",
        "workflow_id": 240,
        "workflow_blob_sha": "f" * 40,
        "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        "checker_tree_sha256": "5" * 64,
        "checker_file_count": 8,
        "public_scan_bindings": bindings,
    }


def _promotion_state(checkpoint: str = "CP09") -> dict[str, Any]:
    number = int(checkpoint[2:])
    current_index = 18 if number == 18 else number + 1
    now = "2026-07-14T07:00:00Z"
    checkpoints: dict[str, Any] = {}
    operation_seed = 0
    for index in range(current_index + 1):
        checkpoint_id = f"CP{index:02d}"
        checkpoint_passed = index <= number
        operations: list[dict[str, Any]] = []
        for sequence, (operation_id, action) in enumerate(
            PROMOTION_OPERATION_PLAN[checkpoint_id], start=1
        ):
            operation_seed += 1
            if action in {"candidate_push", "tag_push", "main_promote"}:
                source = "git_ls_remote"
            elif action in {"ci_wait", "post_release_ci"}:
                source = "github_actions_api"
            elif action == "actual_install":
                source = "installed_tree"
            elif action in {
                "github_authority_verify",
                "immutable_release_enable",
                "immutable_release_verify",
                "ruleset_capability_verify",
                "tag_ruleset_create",
                "promotion_lock_create",
                "draft_create",
                "asset_upload",
                "asset_download_verify",
                "release_publish",
                "published_asset_download",
                "independent_audit",
                "promotion_lock_finalize",
            }:
                source = "github_api"
            else:
                source = "local_filesystem"
            intent = {
                "intent_id": "INT-V240-"
                + operation_id.replace(".", "-").replace("_", "-").upper(),
                "operation_id": operation_id,
                "action": action,
                "idempotency_key": f"{operation_seed + 2000:064x}",
                "inputs_sha256": f"{operation_seed + 3000:064x}",
                "created_at": now,
            }
            if action in EXTERNAL_ACTIONS_REQUIRE_EXPECTED_BEFORE:
                intent["expected_before"] = {
                    "base_main_commit": BASE_COMMIT,
                    "candidate_commit": CANDIDATE_COMMIT,
                    "operation_id": operation_id,
                }
            operation = {
                "operation_id": operation_id,
                "sequence": sequence,
                "status": "passed" if checkpoint_passed else "pending",
                "intent": intent,
            }
            if checkpoint_passed:
                details = {
                    "operation_id": operation_id,
                    "action": action,
                }
                if operation_id == "CP05.workflow_approve":
                    approval = _promotion_ci_approval(now)
                    details = {
                        "ci_approval": approval,
                        "ci_approval_sha256": _canonical_json_sha256(approval),
                    }
                if operation_id == "CP07.quality_gates":
                    command_set = [
                        list(command) for command in CP07_QUALITY_GATE_COMMAND_SET
                    ]
                    details = {
                        "quality_gate_profile": "full_release_gate",
                        "installer_package_profile": False,
                        "cross_python_required": True,
                        "quality_gate_commands": command_set,
                        "quality_gate_command_set_sha256": _canonical_json_sha256(
                            command_set
                        ),
                        "quality_gate_receipts": [f"{index:064x}" for index in range(1, 5)],
                        "receipt_trust_level": "local_unattested",
                        "authoritative_execution_proof": {
                            "checkpoint_id": "CP13",
                            "operation_id": "CP13.candidate_ci",
                            "required_jobs": [
                                "check-ubuntu",
                                "check-macos",
                                "release-asset-gate",
                            ],
                        },
                        "candidate_checkout": {
                            "location": "develops/v2.40",
                            "branch": "codex/v2.40",
                            "head": CANDIDATE_COMMIT,
                            "clean": True,
                            "status_sha256": _sha256_bytes(b""),
                        },
                    }
                readback = {
                    "classification": "exact",
                    "source": source,
                    "observed_at": now,
                    "state_sha256": _canonical_json_sha256(details),
                    "details": details,
                }
                operation.update(
                    {
                        "readback": readback,
                        "receipt_sha256": _canonical_json_sha256(
                            {"intent": intent, "readback": readback}
                        ),
                        "completed_at": now,
                    }
                )
            operations.append(operation)
        checkpoint_record = {
            "checkpoint_id": checkpoint_id,
            "status": "passed" if checkpoint_passed else "pending",
            "candidate_commit": CANDIDATE_COMMIT,
            "operations": operations,
        }
        if checkpoint_passed:
            checkpoint_record.update(
                {
                    "receipt_sha256": _canonical_json_sha256(
                        [operation["receipt_sha256"] for operation in operations]
                    ),
                    "completed_at": now,
                }
            )
        checkpoints[checkpoint_id] = checkpoint_record

    remote_lock = None
    if number >= 14:
        remote_lock = {
            "ruleset_id": 24014,
            "name": "goal-teams-main-protection",
            "target_ref": "refs/heads/main",
            "candidate_commit": CANDIDATE_COMMIT,
            "bypass_actor_id": 240,
            "ruleset_sha256": "7" * 64,
            "observed_at": now,
        }

    remote_identity = None
    if number >= 16:
        assets = []
        for asset_id, (name, record) in enumerate(_required_assets().items(), start=1):
            assets.append(
                {
                    "name": name,
                    "asset_id": asset_id,
                    "size": record["size"],
                    "sha256": record["sha256"],
                    "download_sha256": record["sha256"],
                }
            )
        published = number >= 17
        remote_identity = {
            "main_commit": CANDIDATE_COMMIT if published else BASE_COMMIT,
            "tag_object": "e" * 40,
            "tag_commit": CANDIDATE_COMMIT,
            "release_id": 240,
            "release_state": "published" if published else "draft",
            "isDraft": not published,
            "isPrerelease": False,
            "targetCommitish": CANDIDATE_COMMIT,
            "resolvedTargetCommit": CANDIDATE_COMMIT,
            "latest": published,
            "immutable": published,
            "immutable_release_enabled": True,
            "tag_ruleset_id": 24015,
            "assets": assets,
        }

    ci_runs = []
    if number >= 13:
        ci_runs.append(_ci_run("candidate", 24013, now))
    if number >= 17:
        ci_runs.append(_ci_run("post_release", 24017, now))

    install_identity = None
    if number >= 17:
        install_identity = {
            "source_kind": "github_release_asset",
            "repository": "vibe-coding-era/goal-teams",
            "version": VERSION,
            "tag": TAG,
            "release_id": 240,
            "source_commit": CANDIDATE_COMMIT,
            "source_git_tree_id": "d" * 40,
            "asset_sha256": "1" * 64,
            "installed_tree_sha256": "8" * 64,
            "state_sha256": "9" * 64,
        }

    github_authority = None
    if number >= 3:
        github_authority, _ = _github_live_authority()

    state = {
        "schema_version": "goal-teams-release-promotion-v2.40",
        "repository": "vibe-coding-era/goal-teams",
        "version": VERSION,
        "tag": TAG,
        "base_main_commit": BASE_COMMIT,
        "candidate_commit": CANDIDATE_COMMIT,
        "candidate_tree": "d" * 40,
        "phase": CHECKPOINT_PHASE[checkpoint],
        "current_checkpoint": f"CP{current_index:02d}",
        "transition_map_version": "goal-teams-v2.40-transition-map-v1",
        "checkpoints": checkpoints,
        "github_authority": github_authority,
        "sanitization_receipts": [],
        "remote_lock": remote_lock,
        "remote_identity": remote_identity,
        "ci_runs": ci_runs,
        "install_identity": install_identity,
        "created_at": now,
        "updated_at": now,
    }

    def set_details(
        checkpoint_id: str, operation_id: str, details: dict[str, Any]
    ) -> None:
        operation = next(
            item
            for item in state["checkpoints"][checkpoint_id]["operations"]
            if item["operation_id"] == operation_id
        )
        readback = operation["readback"]
        readback["details"] = copy.deepcopy(details)
        readback["state_sha256"] = _canonical_json_sha256(details)
        operation["receipt_sha256"] = _canonical_json_sha256(
            {"intent": operation["intent"], "readback": readback}
        )

    if number >= 18:
        state.update(copy.deepcopy(release.CLOSED_COMPLETION_SEMANTICS))
        set_details(
            "CP18",
            "CP18.archive_close",
            {
                "operation_id": "CP18.archive_close",
                "action": "archive_close",
                **release.CLOSED_COMPLETION_SEMANTICS,
            },
        )

    def bind_intent(operation: dict[str, Any], expected_before: dict[str, Any]) -> None:
        intent = operation["intent"]
        intent["expected_before"] = copy.deepcopy(expected_before)
        binding = {
            "repository": state["repository"],
            "version": state["version"],
            "candidate_commit": state["candidate_commit"],
            "operation_id": operation["operation_id"],
            "action": intent["action"],
            "expected_before": copy.deepcopy(expected_before),
        }
        intent["inputs_sha256"] = _canonical_json_sha256(binding)
        intent["idempotency_key"] = _canonical_json_sha256(
            {
                "transition_map": "goal-teams-v2.40-transition-map-v1",
                **binding,
            }
        )
        if "readback" in operation:
            operation["receipt_sha256"] = _canonical_json_sha256(
                {"intent": intent, "readback": operation["readback"]}
            )

    if "CP16" in state["checkpoints"]:
        sealed_assets = _required_assets()
        sealed_asset_set = _canonical_json_sha256(sealed_assets)
        set_details(
            "CP10",
            "CP10.snapshot_seal",
            {
                "assets": sealed_assets,
                "asset_set_sha256": sealed_asset_set,
                "validator_receipt_sha256": "5" * 64,
            },
        )
        cp10 = state["checkpoints"]["CP10"]
        cp10["receipt_sha256"] = _canonical_json_sha256(
            [operation["receipt_sha256"] for operation in cp10["operations"]]
        )
        cp16 = state["checkpoints"]["CP16"]
        draft_operation = cp16["operations"][0]
        draft_expected = release._derive_cp16_draft_expected_before(state)[
            "CP16.draft_create"
        ]
        bind_intent(draft_operation, draft_expected)
        if number < 16:
            cp16["operations"] = [draft_operation]
        else:
            set_details(
                "CP16",
                "CP16.draft_create",
                {
                    "databaseId": 240,
                    "isDraft": True,
                    "isImmutable": False,
                    "isPrerelease": False,
                    "tagName": TAG,
                    "targetCommitish": CANDIDATE_COMMIT,
                    "resolvedTargetCommit": CANDIDATE_COMMIT,
                    "name": "Goal Teams V2.40",
                    "body": "Goal Teams V2.40. See release/current/README.md in the tagged source.",
                },
            )
            downloaded_assets = [
                {
                    "name": name,
                    "asset_id": asset_id,
                    "size": record["size"],
                    "sha256": record["sha256"],
                    "download_sha256": record["sha256"],
                }
                for asset_id, (name, record) in enumerate(
                    sealed_assets.items(), start=1
                )
            ]
            download_details = {
                "release_id": 240,
                "release_state": "draft",
                "asset_set_sha256": sealed_asset_set,
                "release_identity_sha256": "6" * 64,
                "assets": downloaded_assets,
            }
            set_details(
                "CP16", "CP16.asset_download_verify", download_details
            )
            identity_rows = sorted(
                [
                    {
                        "name": row["name"],
                        "asset_id": row["asset_id"],
                        "size": row["size"],
                        "sha256": row["sha256"],
                    }
                    for row in downloaded_assets
                ],
                key=lambda row: row["name"],
            )
            set_details(
                "CP16",
                "CP16.remote_bundle_rehearsal",
                {
                    "source_commit": CANDIDATE_COMMIT,
                    "install_report_sha256": "7" * 64,
                    "release_id": 240,
                    "asset_set_sha256": sealed_asset_set,
                    "draft_asset_identity_sha256": _canonical_json_sha256(
                        identity_rows
                    ),
                    "release_identity_sha256": "6" * 64,
                    "draft_download_details_sha256": _canonical_json_sha256(
                        download_details
                    ),
                },
            )
            derived_cp16 = release._derive_cp16_post_draft_expected_before(state)
            for operation in cp16["operations"][1:]:
                bind_intent(operation, derived_cp16[operation["operation_id"]])
            cp16["receipt_sha256"] = _canonical_json_sha256(
                [operation["receipt_sha256"] for operation in cp16["operations"]]
            )
            if "CP17" in state["checkpoints"]:
                derived_cp17 = release._derive_cp17_expected_before(state)
                cp17 = state["checkpoints"]["CP17"]
                for operation in cp17["operations"]:
                    bind_intent(operation, derived_cp17[operation["operation_id"]])
                if cp17["status"] == "passed":
                    cp17["receipt_sha256"] = _canonical_json_sha256(
                        [
                            operation["receipt_sha256"]
                            for operation in cp17["operations"]
                        ]
                    )
    if "CP14" in state["checkpoints"]:
        cp14 = state["checkpoints"]["CP14"]
        if cp14["status"] == "passed":
            promotion_payload = release._promotion_lock_ruleset_payload(state)
            tag_payload = release._tag_ruleset_payload(state)
            promotion_sha256 = release._ruleset_payload_sha256(
                promotion_payload
            )
            tag_sha256 = release._ruleset_payload_sha256(tag_payload)
            set_details(
                "CP14",
                "CP14.main_promotion_lock",
                {
                    "ruleset_id": 24014,
                    "ruleset_name": promotion_payload["name"],
                    "ruleset_sha256": promotion_sha256,
                    "ruleset": promotion_payload,
                },
            )
            set_details(
                "CP14",
                "CP14.tag_ruleset",
                {
                    "ruleset_id": 24015,
                    "ruleset_name": tag_payload["name"],
                    "ruleset_sha256": tag_sha256,
                    "ruleset": tag_payload,
                },
            )
            state["remote_lock"] = {
                "ruleset_id": 24014,
                "name": promotion_payload["name"],
                "target_ref": "refs/heads/main",
                "candidate_commit": CANDIDATE_COMMIT,
                "bypass_actor_id": 240,
                "ruleset_sha256": promotion_sha256,
                "observed_at": now,
            }

    if "CP15" in state["checkpoints"] and state["checkpoints"]["CP15"]["status"] == "passed":
        set_details(
            "CP15",
            "CP15.tag_push",
            {
                "tag": TAG,
                "tag_object": "e" * 40,
                "peeled_commit": CANDIDATE_COMMIT,
                "message": "Goal Teams V2.40",
            },
        )

    if number >= 17:
        published_asset_identity = release._downloaded_asset_identity_sha256(
            downloaded_assets
        )
        set_details(
            "CP17",
            "CP17.release_publish",
            {
                "databaseId": 240,
                "isDraft": False,
                "isImmutable": True,
                "isPrerelease": False,
                "tagName": TAG,
                "targetCommitish": CANDIDATE_COMMIT,
                "resolvedTargetCommit": CANDIDATE_COMMIT,
                "name": "Goal Teams V2.40",
                "body": "Goal Teams V2.40. See release/current/README.md in the tagged source.",
                "tagObject": "e" * 40,
                "peeledCommit": CANDIDATE_COMMIT,
                "latest": True,
                "asset_set_sha256": sealed_asset_set,
                "asset_identity_sha256": published_asset_identity,
                "assets": downloaded_assets,
                "publishedAt": "2026-07-14T07:00:01Z",
            },
        )
        set_details(
            "CP17",
            "CP17.published_asset_download",
            {
                "release_id": 240,
                "release_state": "published",
                "asset_set_sha256": sealed_asset_set,
                "asset_identity_sha256": published_asset_identity,
                "assets": downloaded_assets,
            },
        )

    if number >= 18:
        audit_receipt = {
            "passed": True,
            "source_commit": CANDIDATE_COMMIT,
            "version": VERSION,
            "independent": True,
        }
        audit_receipt["receipt_sha256"] = _canonical_json_sha256(audit_receipt)
        set_details(
            "CP17",
            "CP17.independent_audit",
            {"audit_receipt": audit_receipt},
        )
        boundary = {
            "passed": True,
            "candidate_commit": CANDIDATE_COMMIT,
            "audit_receipt_sha256": _canonical_json_sha256(audit_receipt),
            "cleanup_verified": True,
            "candidate_worktree_absent": True,
            "candidate_worktree_entry_absent": True,
            "scanner_receipt_sha256": "1" * 64,
            "ssot_receipt_sha256": "2" * 64,
        }
        boundary["receipt_sha256"] = _canonical_json_sha256(boundary)
        state["cp18_close_boundary_seal"] = copy.deepcopy(boundary)
        state["cp18_close_boundary_seal_sha256"] = _canonical_json_sha256(
            boundary
        )

    if number >= 16:
        state["remote_identity"] = release._derive_remote_identity(
            state,
            published=number >= 17,
        )

    for checkpoint_record in state["checkpoints"].values():
        for operation in checkpoint_record["operations"]:
            operation_id = operation["operation_id"]
            intent = operation["intent"]
            canonical_expected = release._expected_before_for_operation(
                state, operation_id
            )
            if canonical_expected is not None:
                intent["expected_before"] = copy.deepcopy(canonical_expected)
            expected_before = intent.get("expected_before")
            parameters = release._bound_operation_parameters(
                state,
                operation_id,
                intent["action"],
                expected_before,
            )
            intent["parameters_sha256"] = _canonical_json_sha256(parameters)
            intent["expected_after_sha256"] = _canonical_json_sha256(
                release._expected_after_descriptor(
                    state,
                    operation_id,
                    intent["action"],
                    expected_before,
                    parameters,
                )
            )
            binding = release._intent_binding(
                state,
                operation_id,
                intent["action"],
                expected_before,
                intent["parameters_sha256"],
                intent["expected_after_sha256"],
            )
            intent["inputs_sha256"] = _canonical_json_sha256(binding)
            intent["idempotency_key"] = _canonical_json_sha256(
                {
                    "transition_map": "goal-teams-v2.40-transition-map-v1",
                    **binding,
                }
            )
            if "readback" in operation:
                operation["receipt_sha256"] = _canonical_json_sha256(
                    {"intent": intent, "readback": operation["readback"]}
                )
        if checkpoint_record["status"] == "passed":
            checkpoint_record["receipt_sha256"] = _canonical_json_sha256(
                [
                    operation["receipt_sha256"]
                    for operation in checkpoint_record["operations"]
                ]
            )
    return state


def _promotion_expectation() -> dict[str, Any]:
    return {
        "repository": "vibe-coding-era/goal-teams",
        "version": VERSION,
        "candidate_commit": CANDIDATE_COMMIT,
        "transition_map_version": "goal-teams-v2.40-transition-map-v1",
        "operation_plan": {
            checkpoint: [
                {
                    "sequence": sequence,
                    "operation_id": operation_id,
                    "action": action,
                }
                for sequence, (operation_id, action) in enumerate(
                    operations, start=1
                )
            ]
            for checkpoint, operations in PROMOTION_OPERATION_PLAN.items()
        },
        "checkpoint_phase_after_pass": dict(CHECKPOINT_PHASE),
        "current_checkpoint_rule": "first_non_passed_or_CP18_when_all_passed",
    }


def _github_live_authority() -> tuple[dict[str, Any], dict[str, Any]]:
    actor = {"actor_id": 240, "actor_login": "release-owner"}
    origin_binding = {
        "api_host": "github.com",
        "repository": "vibe-coding-era/goal-teams",
        "raw_fetch_urls": ["git@github.com:vibe-coding-era/goal-teams.git"],
        "raw_push_urls": ["git@github.com:vibe-coding-era/goal-teams.git"],
        "resolved_fetch_urls": ["git@github.com:vibe-coding-era/goal-teams.git"],
        "resolved_push_urls": ["git@github.com:vibe-coding-era/goal-teams.git"],
        "pushurl_configured": False,
        "url_rewrite_count": 0,
    }
    origin_binding["origin_binding_sha256"] = _canonical_json_sha256(origin_binding)
    repository = {
        "api_host": "github.com",
        "repository_id": 1249985345,
        "repository_full_name": "vibe-coding-era/goal-teams",
        "origin_binding": copy.deepcopy(origin_binding),
    }
    capabilities = {
        "immutable_endpoint_capability": {
            "read": True,
            "enable": True,
            "enabled": True,
            "endpoint_sha256": "1" * 64,
        },
        "ruleset_capability": {
            "read": True,
            "write": True,
            "bypass_actor_supported": True,
            "endpoint_sha256": "2" * 64,
        },
        "classic_main_protection": {
            "present": False,
            "release_actor_can_force_with_lease": True,
            "compatibility_mode": "absent",
            "endpoint_sha256": _canonical_json_sha256(None),
        },
    }
    authority = {
        **actor,
        **repository,
        "origin_binding_sha256": origin_binding["origin_binding_sha256"],
        "permission": "admin",
        **capabilities,
        "authorized_external_actions": list(GITHUB_AUTHORIZED_ACTIONS),
        "observed_at": "2026-07-14T07:00:00Z",
        "actor_binding_sha256": _canonical_json_sha256(actor),
        "repository_binding_sha256": _canonical_json_sha256(repository),
        "capability_binding_sha256": _canonical_json_sha256(capabilities),
        "authorized_actions_sha256": _canonical_json_sha256(
            list(GITHUB_AUTHORIZED_ACTIONS)
        ),
    }
    authority["receipt_sha256"] = _canonical_json_sha256(authority)
    return copy.deepcopy(authority), copy.deepcopy(authority)


def _required_assets() -> dict[str, dict[str, Any]]:
    return {
        f"goal-teams-{VERSION}.tar.gz": {"sha256": "1" * 64, "size": 101},
        "SHA256SUMS": {"sha256": "2" * 64, "size": 102},
        "_release.json": {"sha256": "3" * 64, "size": 103},
        "_files.sha256": {"sha256": "4" * 64, "size": 104},
    }


def _install_identity() -> tuple[dict[str, Any], dict[str, Any]]:
    release_receipt = {
        "version": VERSION,
        "tag": TAG,
        "release_id": "REL-V240-001",
        "source_commit": CANDIDATE_COMMIT,
        "artifact_sha256": ARTIFACT_SHA256,
    }
    install_state = {
        "version": VERSION,
        "source_kind": "github_release_asset",
        "source_commit": CANDIDATE_COMMIT,
        "release_tag": TAG,
        "release_id": "REL-V240-001",
        "release_asset_sha256": ARTIFACT_SHA256,
        "source_dirty": False,
    }
    return release_receipt, install_state


def _audit_observation() -> dict[str, Any]:
    zh = _sha256_bytes(b"README.md V2.40\n")
    en = _sha256_bytes(b"README.en.md V2.40\n")
    surfaces = ("main", "tag", "release", "asset", "installed")
    def ci_stage(stage: str, run_id: int, created_at: str) -> dict[str, Any]:
        return {
            "head_sha": CANDIDATE_COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_raw_path": ".github/workflows/release-gate.yml",
            "workflow_raw_ref": None,
            "workflow_blob_sha": "f" * 40,
            "workflow_id": 240,
            "run_id": run_id,
            "run_attempt": 1,
            "event": "push" if stage == "candidate" else "workflow_dispatch",
            "actor_id": 240,
            "triggering_actor_id": 240,
            "created_at": created_at,
            "jobs": [
                {
                    "name": name,
                    "head_sha": CANDIDATE_COMMIT,
                    "conclusion": "success",
                }
                for name in (
                    "check-ubuntu",
                    "check-macos",
                    "release-asset-gate",
                )
            ],
        }

    return {
        "version": VERSION,
        "tag": TAG,
        "latest_release_tag": TAG,
        "commits": {
            "main": CANDIDATE_COMMIT,
            "tag": CANDIDATE_COMMIT,
            "release": CANDIDATE_COMMIT,
            "asset": CANDIDATE_COMMIT,
            "installed": CANDIDATE_COMMIT,
        },
        "readme_sha256": {
            "README.md": {surface: zh for surface in surfaces},
            "README.en.md": {surface: en for surface in surfaces},
        },
        "release_published_at": "2026-07-14T15:00:00Z",
        "release_actor_id": 240,
        "ci": {
            "candidate": ci_stage("candidate", 24013, "2026-07-14T14:00:00Z"),
            "post_release": ci_stage(
                "post_release", 24017, "2026-07-14T16:00:00Z"
            ),
        },
        # A forged promote boolean is deliberately present.  Independent audit
        # must decide from the raw observations above instead of trusting it.
        "promote_reported_passed": True,
    }


def _write_tar(path: Path, members: list[dict[str, Any]]) -> None:
    """Create small adversarial archives without extracting them in the test."""

    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as archive:
        for member in members:
            data = member.get("data", b"fixture\n")
            info = tarfile.TarInfo(str(member["name"]))
            info.type = member.get("type", tarfile.REGTYPE)
            info.linkname = str(member.get("linkname", ""))
            info.pax_headers = dict(member.get("pax_headers", {}))
            if info.type == tarfile.REGTYPE:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                info.size = 0
                archive.addfile(info)


class V240ReleaseLifecycleContractTests(unittest.TestCase):
    def release_api(self, name: str) -> Callable[..., Any]:
        self.assertIsNotNone(release, "scripts/release/release.py is required")
        value = getattr(release, name, None)
        self.assertTrue(callable(value), f"missing public API release.{name}")
        return value

    def audit_api(self, name: str) -> Callable[..., Any]:
        self.assertIsNotNone(audit, "scripts/release/audit-release.py is required")
        value = getattr(audit, name, None)
        self.assertTrue(callable(value), f"missing public API audit_release.{name}")
        return value

    def build_api(self, name: str) -> Callable[..., Any]:
        self.assertIsNotNone(
            build_release, "scripts/release/build-release.py is required"
        )
        value = getattr(build_release, name, None)
        self.assertTrue(callable(value), f"missing public API build_release.{name}")
        return value

    def validator_api(self, name: str) -> Callable[..., Any]:
        self.assertIsNotNone(
            validate_release, "scripts/release/validate-release.py is required"
        )
        value = getattr(validate_release, name, None)
        self.assertTrue(callable(value), f"missing public API validate_release.{name}")
        return value

    def policy_failure(
        self, expected_code: str, action: Callable[[], Any]
    ) -> dict[str, Any]:
        """Require a machine failure receipt, not merely an exception or rc."""

        try:
            result = action()
        except Exception as exc:  # the production error must carry its receipt
            receipt = getattr(exc, "receipt", None)
        else:
            receipt = result
        self.assertIsInstance(receipt, dict, "policy failure must expose a receipt")
        self.assertFalse(receipt.get("passed", True))
        self.assertEqual(receipt.get("error_code"), expected_code)
        self.assertEqual(receipt.get("mutation_count"), 0)
        self.assertEqual(receipt.get("external_side_effect_count"), 0)
        return receipt

    def test_v240_security_contracts_match_promotion_schema_exactly(self) -> None:
        if LOCAL_PROMOTION_STATE_CONTRACT.is_file():
            self.assertEqual(
                PROMOTION_STATE_CONTRACT.read_bytes(),
                LOCAL_PROMOTION_STATE_CONTRACT.read_bytes(),
                "local SPEC mirror must be byte-identical to the executable schema",
            )
        promotion_contract = json.loads(PROMOTION_STATE_CONTRACT.read_text())
        test_contracts = json.loads(TEST_CASE_CONTRACTS.read_text())
        if LOCAL_IGNORED_TEST_CASE_CONTRACTS.is_file():
            self.assertEqual(
                TEST_CASE_CONTRACTS.read_bytes(),
                LOCAL_IGNORED_TEST_CASE_CONTRACTS.read_bytes(),
            )
        cp07_contract = promotion_contract["$defs"]["cp07_quality_gate_details"]
        self.assertIs(cp07_contract["additionalProperties"], False)
        self.assertEqual(
            cp07_contract["properties"]["quality_gate_commands"]["const"],
            [list(command) for command in CP07_QUALITY_GATE_COMMAND_SET],
        )
        self.assertEqual(
            cp07_contract["properties"]["quality_gate_receipts"]["minItems"],
            4,
        )
        self.assertEqual(
            cp07_contract["properties"]["quality_gate_receipts"]["maxItems"],
            4,
        )
        self.assertEqual(
            cp07_contract["properties"]["receipt_trust_level"]["const"],
            "local_unattested",
        )
        self.assertEqual(
            cp07_contract["properties"]["authoritative_execution_proof"]["const"]
            ["operation_id"],
            "CP13.candidate_ci",
        )
        schema_plan = {
            checkpoint: tuple(
                (operation["operation_id"], operation["action"])
                for operation in operations
            )
            for checkpoint, operations in promotion_contract[
                "x-operation-plan"
            ].items()
        }
        semantic = promotion_contract["x-semantic-validator"]
        authority_actions = tuple(
            promotion_contract["$defs"]["github_authority"]["properties"]
            ["authorized_external_actions"]["items"]["enum"]
        )
        self.assertEqual(PROMOTION_OPERATION_PLAN, schema_plan)
        self.assertEqual(
            CHECKPOINT_PHASE, semantic["checkpoint_phase_after_pass"]
        )
        self.assertEqual(GITHUB_AUTHORIZED_ACTIONS, authority_actions)
        ci_run_contract = promotion_contract["$defs"]["ci_run"]
        self.assertIn("triggering_actor_id", ci_run_contract["required"])
        self.assertEqual(
            ci_run_contract["properties"]["triggering_actor_id"]["minimum"],
            1,
        )
        ci_approval_contract = promotion_contract["$defs"]["cp05_ci_approval"]
        self.assertIn("workflow_id", ci_approval_contract["required"])
        self.assertEqual(
            ci_approval_contract["properties"]["workflow_id"]["minimum"],
            1,
        )
        remote_identity_contract = promotion_contract["$defs"][
            "remote_identity"
        ]
        self.assertTrue(
            {
                "isDraft",
                "isPrerelease",
                "targetCommitish",
                "resolvedTargetCommit",
            }
            <= set(remote_identity_contract["required"])
        )
        self.assertIs(
            remote_identity_contract["properties"]["isPrerelease"]["const"],
            False,
        )
        baseline_review = promotion_contract["$defs"][
            "public_scan_baseline_review"
        ]
        approval_reviewer = promotion_contract["$defs"][
            "public_scan_approval_reviewer"
        ]
        self.assertTrue(baseline_review["additionalProperties"] is False)
        self.assertNotIn("source_commit", baseline_review["required"])
        self.assertNotIn("candidate_tree", baseline_review["required"])
        self.assertNotIn("source_commit", baseline_review["properties"])
        self.assertNotIn("candidate_tree", baseline_review["properties"])
        self.assertIn("source_commit", approval_reviewer["required"])
        self.assertIn("candidate_tree", approval_reviewer["required"])
        self.assertEqual(
            baseline_review["properties"]["reviewer_run_id"]["not"]["const"],
            "RUN-V240-LEAD",
        )
        review_binding = semantic["cp05_public_scan_review_binding"]
        self.assertEqual(
            review_binding["git_self_reference_policy"],
            "baseline_review_must_not_contain_final_candidate_commit_or_tree",
        )
        self.assertEqual(
            review_binding["detached_candidate_identity_fields"],
            ["source_commit", "candidate_tree"],
        )
        stash_contract = promotion_contract["$defs"][
            "root_recovery_stash_attestation"
        ]
        self.assertTrue(stash_contract["additionalProperties"] is False)
        self.assertEqual(
            semantic["cp01_recovered_root_stash_attestation"]["fixed_path"],
            "docs/release-state/V2.40/root-recovery-stash.json",
        )
        self.assertEqual(
            semantic["cp01_recovered_root_stash_attestation"][
                "remote_main_tracking_ref"
            ],
            "refs/remotes/origin/main^{commit}",
        )
        self.assertEqual(
            semantic["cp01_recovered_root_stash_attestation"][
                "forbidden_git_mutations"
            ],
            [
                "stash_apply",
                "stash_drop",
                "update_ref",
                "worktree_add",
                "worktree_remove",
            ],
        )
        self.assertEqual(
            semantic["internally_derived_next_checkpoint_expected_before"][
                "CP16"
            ]["caller_override"],
            "forbidden",
        )
        cp16_dynamic = semantic["dynamic_operation_materialization"]["CP16"]
        self.assertEqual(cp16_dynamic["persisted_prefix_lengths"], [1, 7])
        self.assertEqual(
            cp16_dynamic["materialization_trigger"],
            "CP16.draft_create.exact_readback",
        )
        self.assertTrue(cp16_dynamic["marker_last"])
        self.assertTrue(cp16_dynamic["second_authorization_required"])
        finalization = semantic["cp17_cp18_ssot_finalization"]
        self.assertEqual(
            finalization["finalization_window"],
            "after_CP17_pass_before_CP18_close",
        )
        self.assertEqual(
            finalization["closed_semantics"],
            {
                "closure_scope": "distribution_and_archive_only",
                "goal_achieved": False,
                "external_host_acceptance_required": True,
                "completion_authority": "repository_external_single_use_host",
                "negative_host_boundary_cannot_authorize_completion": True,
            },
        )

        cases = {
            case["case_id"]: case
            for case in test_contracts["valid_cases"]
        }
        self.assertEqual(
            cases["SEC-240-024"]["input"]["values"]["expected_phase"],
            semantic["checkpoint_phase_after_pass"]["CP09"],
        )
        self.assertEqual(
            cases["SEC-240-025"]["input"]["values"]["required_order"],
            [action for _, action in schema_plan["CP17"]],
        )
        authority_case = cases["SEC-240-029"]["input"]["values"]
        self.assertEqual(authority_case["required_actions"], list(authority_actions))
        self.assertEqual(
            set(authority_case["observed_actions"]),
            set(authority_actions) - {"manage_promotion_ruleset"},
        )
        projection_case = cases["SEC-240-037"]["input"]["values"]
        self.assertEqual(projection_case["field"], "isPrerelease")
        self.assertIs(projection_case["forged_value"], True)
        self.assertIs(projection_case["public_digests_resealed"], True)

        state = _promotion_state("CP09")
        self.assertEqual(state["phase"], "RC_VALIDATED")
        self.assertEqual(state["current_checkpoint"], "CP10")
        self.assertEqual(state["checkpoints"]["CP09"]["status"], "passed")
        self.assertEqual(state["checkpoints"]["CP10"]["status"], "pending")
        for checkpoint in state["checkpoints"].values():
            for operation in checkpoint["operations"]:
                if operation["intent"]["action"] in (
                    EXTERNAL_ACTIONS_REQUIRE_EXPECTED_BEFORE
                ):
                    self.assertIn("expected_before", operation["intent"])

    def test_remote_mutation_intents_bind_closed_expected_and_parameters(self) -> None:
        state = _promotion_state("CP13")
        for checkpoint in state["checkpoints"].values():
            for operation in checkpoint["operations"]:
                operation_id = operation["operation_id"]
                action = operation["intent"]["action"]
                if (
                    operation_id.startswith("CP03.")
                    or action in release.REMOTE_MUTATING_ACTIONS
                ):
                    expected_before = operation["intent"].get("expected_before")
                    self.assertIsInstance(expected_before, dict)
                    self.assertTrue(expected_before)

        main_lock = next(
            operation
            for operation in state["checkpoints"]["CP14"]["operations"]
            if operation["operation_id"] == "CP14.main_promotion_lock"
        )
        intent = main_lock["intent"]
        parameters = release._bound_operation_parameters(
            state,
            main_lock["operation_id"],
            intent["action"],
            intent["expected_before"],
        )
        authorization = {
            "intent_sha256": _canonical_json_sha256(intent),
            "expected_before": copy.deepcopy(intent["expected_before"]),
            "parameters_sha256": intent["parameters_sha256"],
            "expected_after_sha256": intent["expected_after_sha256"],
            "mode": "execute_github",
            "parameters": parameters,
        }
        release._operation_authorization(
            main_lock,
            {"operation_authorizations": {main_lock["operation_id"]: authorization}},
        )

        tampered = copy.deepcopy(authorization)
        tampered["parameters"]["ruleset_payload"]["name"] = "attacker-lock"
        self.policy_failure(
            "E_V240_OPERATION_AUTHORIZATION",
            lambda: release._operation_authorization(
                main_lock,
                {"operation_authorizations": {main_lock["operation_id"]: tampered}},
            ),
        )

        promotion_state = _promotion_state("CP16")
        guarded_operations = []
        for checkpoint_id in ("CP15", "CP16", "CP17"):
            for operation in promotion_state["checkpoints"][checkpoint_id][
                "operations"
            ]:
                if operation["intent"]["action"] in release.CP15_CP17_MUTATING_ACTIONS:
                    guarded_operations.append(operation)
        self.assertEqual(len(guarded_operations), 9)
        for operation in guarded_operations:
            intent = operation["intent"]
            parameters = release._bound_operation_parameters(
                promotion_state,
                operation["operation_id"],
                intent["action"],
                intent["expected_before"],
            )
            guard = parameters.get("_remote_mutation_guard")
            self.assertIsInstance(guard, dict)
            self.assertEqual(
                guard["schema_version"],
                "goal-teams-v2.40-remote-mutation-guard-v1",
            )
            self.assertEqual(
                set(guard["temporary_main_lock"]),
                {"ruleset_id", "ruleset_name", "ruleset_sha256", "ruleset"},
            )
            self.assertEqual(
                set(guard["permanent_tag_ruleset"]),
                {"ruleset_id", "ruleset_name", "ruleset_sha256", "ruleset"},
            )
            self.assertEqual(
                _canonical_json_sha256(parameters), intent["parameters_sha256"]
            )

        for operation_id, action in (
            ("CP03.github_authority_readback", "github_authority_verify"),
            ("CP15.tag_push", "tag_push"),
        ):
            with self.subTest(empty_expected_before=operation_id):
                self.policy_failure(
                    "E_V240_STATE_EXPECTED_BEFORE",
                    lambda operation_id=operation_id, action=action: release._new_operation_record(
                        state,
                        {
                            "sequence": 1,
                            "operation_id": operation_id,
                            "action": action,
                        },
                        {},
                        status="pending",
                    ),
                )

    def test_ruleset_payloads_close_update_and_code_owner_parameters(self) -> None:
        state = _promotion_state("CP13")
        promotion = release._promotion_lock_ruleset_payload(state)
        permanent_tag = release._tag_ruleset_payload(state)
        final_main = release._final_main_ruleset_payload(240)

        self.assertEqual(
            promotion["conditions"]["ref_name"],
            {"include": ["refs/heads/main"], "exclude": []},
        )
        self.assertEqual(promotion, final_main)
        self.assertEqual(
            promotion["bypass_actors"],
            [{"actor_id": 240, "actor_type": "User", "bypass_mode": "always"}],
        )
        self.assertEqual(
            permanent_tag["conditions"]["ref_name"],
            {"include": ["refs/tags/v*"], "exclude": []},
        )
        self.assertIn(
            {
                "type": "update",
                "parameters": {"update_allows_fetch_and_merge": False},
            },
            permanent_tag["rules"],
        )
        pull_request = next(
            rule for rule in final_main["rules"] if rule["type"] == "pull_request"
        )
        self.assertIs(pull_request["parameters"]["require_code_owner_review"], False)

    def test_cp15_cp17_fresh_ruleset_and_main_cas_blocks_toctou_and_marker_loss(
        self,
    ) -> None:
        state = _promotion_state("CP14")
        promotion = release._promotion_lock_ruleset_payload(state)
        permanent_tag = release._tag_ruleset_payload(state)

        class GuardAdapter:
            def __init__(self) -> None:
                self.main = BASE_COMMIT
                self.promotion_id = 24014
                self.tag_id = 24015
                self.ruleset_reads: list[str] = []
                self.main_reads = 0

            def _ruleset_by_name(self, name: str) -> dict[str, Any] | None:
                self.ruleset_reads.append(name)
                if name == promotion["name"]:
                    return {"id": self.promotion_id, **copy.deepcopy(promotion)}
                if name == permanent_tag["name"]:
                    return {"id": self.tag_id, **copy.deepcopy(permanent_tag)}
                return None

            def _validate_ruleset_payload(
                self, _action: str, _payload: dict[str, Any]
            ) -> None:
                return None

            def _remote_ref(self, ref: str) -> str:
                self.assert_ref = ref
                self.main_reads += 1
                return self.main

        adapter = GuardAdapter()
        release._validate_remote_mutation_preconditions(
            state, "CP15", "tag_push", adapter
        )
        release._validate_remote_mutation_preconditions(
            state, "CP16", "asset_upload", adapter
        )
        release._validate_remote_mutation_preconditions(
            state, "CP17", "main_promote", adapter
        )
        self.assertEqual(adapter.ruleset_reads.count(promotion["name"]), 3)
        self.assertEqual(adapter.ruleset_reads.count(permanent_tag["name"]), 3)
        self.assertEqual(adapter.main_reads, 3)

        adapter.main = CANDIDATE_COMMIT
        release._validate_remote_mutation_preconditions(
            state, "CP17", "main_promote", adapter, stored_exact=True
        )
        release._validate_remote_mutation_preconditions(
            state, "CP17", "release_publish", adapter
        )

        adapter.main = BASE_COMMIT
        release._validate_remote_mutation_preconditions(
            state, "CP17", "main_promote", adapter, mode="observe"
        )
        adapter.main = CANDIDATE_COMMIT
        release._validate_remote_mutation_preconditions(
            state, "CP17", "main_promote", adapter, mode="observe"
        )

        adapter.tag_id += 1
        self.policy_failure(
            "E_V240_REMOTE_RESOURCE_CONFLICT",
            lambda: release._validate_remote_mutation_preconditions(
                state, "CP16", "draft_create", adapter
            ),
        )

        adapter.tag_id = 24015
        adapter.main = CANDIDATE_COMMIT
        self.policy_failure(
            "E_V240_REMOTE_MAIN_LEASE",
            lambda: release._validate_remote_mutation_preconditions(
                state, "CP16", "asset_upload", adapter
            ),
        )

        stored = release._operation_details(
            state, "CP14", "CP14.main_promotion_lock"
        )
        identity = release._critical_readback_identity(
            "promotion_lock_create", stored
        )
        self.assertEqual(identity["ruleset_id"], 24014)
        self.assertEqual(
            identity["ruleset"],
            release._load_github_adapter().normalize_ruleset(promotion),
        )
        marker_loss = copy.deepcopy(stored)
        del marker_loss["ruleset"]
        self.policy_failure(
            "E_V240_RULESET_IDENTITY",
            lambda: release._ruleset_readback_identity(
                marker_loss, action="promotion_lock_create"
            ),
        )

    def test_cp17_main_marker_loss_observe_adopts_candidate_without_write(
        self,
    ) -> None:
        state = _promotion_state("CP16")
        promotion = release._promotion_lock_ruleset_payload(state)
        permanent_tag = release._tag_ruleset_payload(state)
        sealed_assets = _required_assets()
        sealed = {
            "assets": sealed_assets,
            "asset_set_sha256": _canonical_json_sha256(sealed_assets),
            "validator_receipt_sha256": "5" * 64,
        }

        class ObserveAdapter:
            def __init__(self) -> None:
                self.execute_calls = 0
                self.observe_calls: list[str] = []

            def _ruleset_by_name(self, name: str) -> dict[str, Any] | None:
                if name == promotion["name"]:
                    return {"id": 24014, **copy.deepcopy(promotion)}
                if name == permanent_tag["name"]:
                    return {"id": 24015, **copy.deepcopy(permanent_tag)}
                return None

            def _validate_ruleset_payload(
                self, _action: str, _payload: dict[str, Any]
            ) -> None:
                return None

            def _remote_ref(self, ref: str) -> str:
                self.assert_ref = ref
                return CANDIDATE_COMMIT

            def observe(
                self, *, operation_id, action, expected_before, parameters
            ) -> dict[str, Any]:
                self.observe_calls.append(operation_id)
                if action == "main_promote":
                    details = {
                        "ref": "refs/heads/main",
                        "remote_commit": CANDIDATE_COMMIT,
                    }
                    return {
                        "classification": "exact",
                        "source": "git_ls_remote",
                        "observed_at": "2026-07-14T07:00:03Z",
                        "state_sha256": _canonical_json_sha256(details),
                        "details": details,
                    }
                raise release.PolicyError(
                    "E_V240_SYNTHETIC_STOP",
                    "stop after the marker-loss main adoption",
                )

            def execute(self, **_kwargs):
                self.execute_calls += 1
                raise AssertionError("observe-adopt must not execute a remote write")

        authorizations: dict[str, dict[str, Any]] = {}
        for operation in state["checkpoints"]["CP17"]["operations"]:
            intent = operation["intent"]
            parameters = release._bound_operation_parameters(
                state,
                operation["operation_id"],
                intent["action"],
                intent.get("expected_before"),
            )
            mode = "observe"
            if operation["operation_id"] in {
                "CP17.actual_install",
                "CP17.independent_audit",
            }:
                mode = "execute_local"
            authorizations[operation["operation_id"]] = {
                "intent_sha256": _canonical_json_sha256(intent),
                "expected_before": copy.deepcopy(intent.get("expected_before")),
                "parameters_sha256": intent["parameters_sha256"],
                "expected_after_sha256": intent["expected_after_sha256"],
                "mode": mode,
                "parameters": parameters,
            }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "promotion-state.json"
            path.write_text(
                json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            adapter = ObserveAdapter()
            with mock.patch.object(
                release, "_allowed_state_path", side_effect=lambda value: Path(value)
            ), mock.patch.object(
                release, "_verify_frozen_git_identity", return_value={}
            ), mock.patch.object(
                release, "_require_clean_candidate_checkout", return_value={}
            ), mock.patch.object(
                release, "_revalidate_canonical_release", return_value=sealed
            ), mock.patch.object(
                release, "_github_adapter_for_state", return_value=adapter
            ):
                self.policy_failure(
                    "E_V240_SYNTHETIC_STOP",
                    lambda: release.execute_current_checkpoint(
                        path,
                        {
                            "expected_state_sha256": digest,
                            "checkpoint_id": "CP17",
                            "operation_authorizations": authorizations,
                        },
                    ),
                )
            persisted = json.loads(path.read_text(encoding="utf-8"))
            main_operation = persisted["checkpoints"]["CP17"]["operations"][0]
            self.assertEqual(
                main_operation["readback"]["details"]["remote_commit"],
                CANDIDATE_COMMIT,
            )
            self.assertEqual(main_operation["readback"]["classification"], "exact")
            self.assertEqual(adapter.execute_calls, 0)
            self.assertEqual(
                adapter.observe_calls,
                ["CP17.main_promote", "CP17.release_publish"],
            )

    def test_cp17_resume_after_post_ci_runs_only_missing_independent_audit(
        self,
    ) -> None:
        state = _promotion_state("CP17")
        state["checkpoints"].pop("CP18")
        state["current_checkpoint"] = "CP17"
        state["phase"] = "DRAFT_VERIFIED"
        checkpoint = state["checkpoints"]["CP17"]
        checkpoint["status"] = "in_progress"
        checkpoint.pop("completed_at", None)
        checkpoint.pop("receipt_sha256", None)
        audit_operation = None
        for operation in checkpoint["operations"]:
            operation["status"] = "in_progress"
            operation.pop("completed_at", None)
            if operation["operation_id"] == "CP17.independent_audit":
                audit_operation = operation
                operation.pop("readback", None)
                operation.pop("receipt_sha256", None)
        self.assertIsNotNone(audit_operation)

        stored_external = {
            operation["operation_id"]: copy.deepcopy(operation["readback"])
            for operation in checkpoint["operations"][:5]
            if operation["operation_id"]
            not in {"CP17.actual_install"}
        }

        class ResumeAdapter:
            def __init__(self) -> None:
                self.observe_calls: list[str] = []
                self.execute_calls = 0

            def observe(self, *, operation_id, **_kwargs):
                self.observe_calls.append(operation_id)
                return copy.deepcopy(stored_external[operation_id])

            def execute(self, **_kwargs):
                self.execute_calls += 1
                raise AssertionError("exact CP17 readbacks must not be replayed")

        authorizations: dict[str, dict[str, Any]] = {}
        for operation in checkpoint["operations"]:
            intent = operation["intent"]
            operation_id = operation["operation_id"]
            parameters = release._bound_operation_parameters(
                state,
                operation_id,
                intent["action"],
                intent.get("expected_before"),
            )
            authorizations[operation_id] = {
                "intent_sha256": _canonical_json_sha256(intent),
                "expected_before": copy.deepcopy(intent.get("expected_before")),
                "parameters_sha256": intent["parameters_sha256"],
                "expected_after_sha256": intent["expected_after_sha256"],
                "mode": (
                    "execute_local"
                    if operation_id
                    in {"CP17.actual_install", "CP17.independent_audit"}
                    else "observe"
                ),
                "parameters": parameters,
            }

        audit_details = {
            "audit_receipt": {
                "passed": True,
                "source_commit": CANDIDATE_COMMIT,
                "version": VERSION,
            }
        }
        audit_readback = release._exact_readback("github_api", audit_details)
        adapter = ResumeAdapter()
        local_calls: list[str] = []

        def execute_local(operation_id, *_args, **_kwargs):
            local_calls.append(operation_id)
            if operation_id != "CP17.independent_audit":
                raise AssertionError(f"unexpected local replay: {operation_id}")
            return copy.deepcopy(audit_readback)

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "promotion-state.json"
            with (
                mock.patch.object(
                    release,
                    "_load_state_cas",
                    return_value=(state_path, state, "a" * 64),
                ),
                mock.patch.object(release, "_verify_frozen_git_identity"),
                mock.patch.object(release, "_require_clean_candidate_checkout"),
                mock.patch.object(
                    release,
                    "_revalidate_canonical_release",
                    return_value={"passed": True},
                ),
                mock.patch.object(
                    release,
                    "_validate_remote_mutation_preconditions",
                    return_value={},
                ),
                mock.patch.object(
                    release,
                    "_github_adapter_for_state",
                    return_value=adapter,
                ),
                mock.patch.object(
                    release,
                    "_execute_local_operation",
                    side_effect=execute_local,
                ),
                mock.patch.object(
                    release,
                    "_derive_checkpoint_state_updates",
                    return_value={},
                ),
                mock.patch.object(release, "_append_next_checkpoint"),
                mock.patch.object(
                    release,
                    "validate_promotion_state",
                    return_value={"passed": True},
                ),
                mock.patch.object(
                    release,
                    "_atomic_state_write",
                    return_value="b" * 64,
                ),
            ):
                receipt = release.execute_current_checkpoint(
                    state_path,
                    {
                        "expected_state_sha256": "a" * 64,
                        "checkpoint_id": "CP17",
                        "operation_authorizations": authorizations,
                    },
                )
        self.assertTrue(receipt["passed"])
        self.assertEqual(adapter.execute_calls, 0)
        self.assertEqual(
            adapter.observe_calls,
            [
                "CP17.main_promote",
                "CP17.release_publish",
                "CP17.published_asset_download",
                "CP17.post_release_ci",
            ],
        )
        self.assertEqual(local_calls, ["CP17.independent_audit"])

    def test_cp16_derives_cp17_expected_before_after_live_draft_id(self) -> None:
        state = _promotion_state("CP16")
        assets = _required_assets()
        asset_set_sha256 = _canonical_json_sha256(assets)
        downloaded_assets = [
            {
                "name": name,
                "asset_id": index,
                "size": row["size"],
                "sha256": row["sha256"],
                "download_sha256": row["sha256"],
            }
            for index, (name, row) in enumerate(assets.items(), start=501)
        ]

        def set_details(checkpoint_id: str, operation_id: str, details: dict[str, Any]) -> None:
            operation = next(
                item
                for item in state["checkpoints"][checkpoint_id]["operations"]
                if item["operation_id"] == operation_id
            )
            operation["readback"]["details"] = copy.deepcopy(details)
            operation["readback"]["state_sha256"] = _canonical_json_sha256(details)
            operation["receipt_sha256"] = _canonical_json_sha256(
                {"intent": operation["intent"], "readback": operation["readback"]}
            )
            checkpoint = state["checkpoints"][checkpoint_id]
            if checkpoint["status"] == "passed":
                checkpoint["receipt_sha256"] = _canonical_json_sha256(
                    [item["receipt_sha256"] for item in checkpoint["operations"]]
                )

        set_details(
            "CP10",
            "CP10.snapshot_seal",
            {
                "assets": assets,
                "asset_set_sha256": asset_set_sha256,
                "validator_receipt_sha256": "5" * 64,
            },
        )
        set_details(
            "CP16",
            "CP16.draft_create",
            {
                "databaseId": 987654321,
                "isDraft": True,
                "isImmutable": False,
                "isPrerelease": False,
                "tagName": TAG,
                "targetCommitish": CANDIDATE_COMMIT,
                "resolvedTargetCommit": CANDIDATE_COMMIT,
                "name": "Goal Teams V2.40",
                "body": "Goal Teams V2.40. See release/current/README.md in the tagged source.",
            },
        )
        download_details = {
            "release_id": 987654321,
            "release_state": "draft",
            "asset_set_sha256": asset_set_sha256,
            "release_identity_sha256": "8" * 64,
            "assets": downloaded_assets,
        }
        set_details(
            "CP16",
            "CP16.asset_download_verify",
            download_details,
        )
        identity_rows = sorted(
            [
                {
                    "name": row["name"],
                    "asset_id": row["asset_id"],
                    "size": row["size"],
                    "sha256": row["sha256"],
                }
                for row in downloaded_assets
            ],
            key=lambda row: row["name"],
        )
        set_details(
            "CP16",
            "CP16.remote_bundle_rehearsal",
            {
                "source_commit": CANDIDATE_COMMIT,
                "install_report_sha256": "6" * 64,
                "release_id": 987654321,
                "asset_set_sha256": asset_set_sha256,
                "draft_asset_identity_sha256": _canonical_json_sha256(
                    identity_rows
                ),
                "release_identity_sha256": "8" * 64,
                "draft_download_details_sha256": _canonical_json_sha256(
                    download_details
                ),
            },
        )
        derived_cp16 = release._derive_cp16_post_draft_expected_before(state)
        cp16 = state["checkpoints"]["CP16"]
        for operation in cp16["operations"][1:]:
            expected_before = derived_cp16[operation["operation_id"]]
            intent = operation["intent"]
            intent["expected_before"] = copy.deepcopy(expected_before)
            parameters = release._bound_operation_parameters(
                state,
                operation["operation_id"],
                intent["action"],
                expected_before,
            )
            intent["parameters_sha256"] = _canonical_json_sha256(parameters)
            intent["expected_after_sha256"] = _canonical_json_sha256(
                release._expected_after_descriptor(
                    state,
                    operation["operation_id"],
                    intent["action"],
                    expected_before,
                    parameters,
                )
            )
            binding = release._intent_binding(
                state,
                operation["operation_id"],
                intent["action"],
                expected_before,
                intent["parameters_sha256"],
                intent["expected_after_sha256"],
            )
            intent["inputs_sha256"] = _canonical_json_sha256(binding)
            intent["idempotency_key"] = _canonical_json_sha256(
                {
                    "transition_map": "goal-teams-v2.40-transition-map-v1",
                    **binding,
                }
            )
            operation["receipt_sha256"] = _canonical_json_sha256(
                {
                    "intent": operation["intent"],
                    "readback": operation["readback"],
                }
            )
        cp16["receipt_sha256"] = _canonical_json_sha256(
            [operation["receipt_sha256"] for operation in cp16["operations"]]
        )
        del state["checkpoints"]["CP17"]

        forged = copy.deepcopy(state)
        self.policy_failure(
            "E_V240_STATE_EXPECTED_BEFORE",
            lambda: release._append_next_checkpoint(
                forged,
                "CP16",
                {
                    "next_checkpoint_expected_before": {
                        "CP17.release_publish": {"release_id": 1}
                    }
                },
            ),
        )
        explicit_null = copy.deepcopy(state)
        self.policy_failure(
            "E_V240_STATE_EXPECTED_BEFORE",
            lambda: release._append_next_checkpoint(
                explicit_null,
                "CP16",
                {"next_checkpoint_expected_before": None},
            ),
        )

        expected_map = release._derive_cp17_expected_before(state)
        self.assertEqual(expected_map, release._derive_cp17_expected_before(state))
        release._append_next_checkpoint(state, "CP16", {})
        persisted = {
            operation["operation_id"]: operation["intent"]["expected_before"]
            for operation in state["checkpoints"]["CP17"]["operations"]
        }
        self.assertEqual(persisted, expected_map)
        self.assertEqual(
            persisted["CP17.release_publish"]["release_id"], 987654321
        )
        self.assertEqual(
            persisted["CP17.post_release_ci"]["ci_approval"],
            _promotion_ci_approval("2026-07-14T07:00:00Z"),
        )

        persisted_tamper = copy.deepcopy(state)
        actual_install = next(
            operation
            for operation in persisted_tamper["checkpoints"]["CP17"][
                "operations"
            ]
            if operation["operation_id"] == "CP17.actual_install"
        )
        actual_install["intent"]["expected_before"]["release_id"] = 1
        self.policy_failure(
            "E_V240_STATE_EXPECTED_BEFORE",
            lambda: release.validate_promotion_state(persisted_tamper),
        )

        persisted_hash_tamper = copy.deepcopy(state)
        release_publish = next(
            operation
            for operation in persisted_hash_tamper["checkpoints"]["CP17"][
                "operations"
            ]
            if operation["operation_id"] == "CP17.release_publish"
        )
        release_publish["intent"]["inputs_sha256"] = "0" * 64
        self.policy_failure(
            "E_V240_STATE_RECEIPT_CHAIN",
            lambda: release.validate_promotion_state(persisted_hash_tamper),
        )

        tampered = copy.deepcopy(state)
        del tampered["checkpoints"]["CP17"]
        download = next(
            operation
            for operation in tampered["checkpoints"]["CP16"]["operations"]
            if operation["operation_id"] == "CP16.asset_download_verify"
        )
        download["readback"]["details"]["release_id"] = 1
        self.policy_failure(
            "E_V240_STATE_DERIVATION",
            lambda: release._derive_cp17_expected_before(tampered),
        )

        duplicate_asset_id = copy.deepcopy(state)
        del duplicate_asset_id["checkpoints"]["CP17"]
        download = next(
            operation
            for operation in duplicate_asset_id["checkpoints"]["CP16"][
                "operations"
            ]
            if operation["operation_id"] == "CP16.asset_download_verify"
        )
        asset_rows = download["readback"]["details"]["assets"]
        asset_rows[1]["asset_id"] = asset_rows[0]["asset_id"]
        self.policy_failure(
            "E_V240_STATE_DERIVATION",
            lambda: release._derive_cp17_expected_before(duplicate_asset_id),
        )

    def test_release_projection_tamper_fails_after_public_digest_reseal(
        self,
    ) -> None:
        def operation(state: dict[str, Any], checkpoint: str, operation_id: str):
            return next(
                row
                for row in state["checkpoints"][checkpoint]["operations"]
                if row["operation_id"] == operation_id
            )

        def reseal(state: dict[str, Any], checkpoint: str, operation_id: str):
            row = operation(state, checkpoint, operation_id)
            readback = row["readback"]
            readback["state_sha256"] = _canonical_json_sha256(
                readback["details"]
            )
            row["receipt_sha256"] = _canonical_json_sha256(
                {"intent": row["intent"], "readback": readback}
            )
            state["checkpoints"][checkpoint]["receipt_sha256"] = (
                _canonical_json_sha256(
                    [
                        item["receipt_sha256"]
                        for item in state["checkpoints"][checkpoint][
                            "operations"
                        ]
                    ]
                )
            )

        draft_state = _promotion_state("CP16")
        draft_intent = operation(
            draft_state, "CP16", "CP16.draft_create"
        )["intent"]["expected_before"]
        self.assertIs(draft_intent["isDraft"], True)
        self.assertIs(draft_intent["isPrerelease"], False)
        draft_details = operation(
            draft_state, "CP16", "CP16.draft_create"
        )["readback"]["details"]
        draft_details["isPrerelease"] = True
        reseal(draft_state, "CP16", "CP16.draft_create")
        self.policy_failure(
            "E_V240_STATE_DERIVATION",
            lambda: release.validate_promotion_state(draft_state),
        )
        self.policy_failure(
            "E_V240_STATE_DERIVATION",
            lambda: release._derive_cp17_expected_before(draft_state),
        )

        remote_tamper = _promotion_state("CP16")
        remote_tamper["remote_identity"]["isPrerelease"] = True
        self.policy_failure(
            "E_V240_STATE_DERIVATION",
            lambda: release.validate_promotion_state(remote_tamper),
        )

        published = _promotion_state("CP17")
        publish_intent = operation(
            published, "CP17", "CP17.release_publish"
        )["intent"]["expected_before"]
        self.assertIs(publish_intent["isDraft"], True)
        self.assertIs(publish_intent["isPrerelease"], False)
        release.validate_promotion_state(published)
        for field, forged in (
            ("isPrerelease", True),
            ("isDraft", True),
            ("targetCommitish", "main"),
            ("resolvedTargetCommit", BASE_COMMIT),
        ):
            tampered = copy.deepcopy(published)
            details = operation(
                tampered, "CP17", "CP17.release_publish"
            )["readback"]["details"]
            details[field] = forged
            tampered["remote_identity"][field] = forged
            reseal(tampered, "CP17", "CP17.release_publish")
            with self.subTest(published_projection=field):
                self.policy_failure(
                    "E_V240_STATE_DERIVATION",
                    lambda tampered=tampered: release.validate_promotion_state(
                        tampered
                    ),
                )

    def test_fresh_release_identity_includes_prerelease_and_raw_target(self) -> None:
        draft = {
            "databaseId": 240,
            "isDraft": True,
            "isImmutable": False,
            "isPrerelease": False,
            "tagName": TAG,
            "targetCommitish": CANDIDATE_COMMIT,
            "resolvedTargetCommit": CANDIDATE_COMMIT,
            "name": "Goal Teams V2.40",
            "body": "Goal Teams V2.40. See release/current/README.md in the tagged source.",
        }
        published = {
            **draft,
            "isDraft": False,
            "isImmutable": True,
        }
        for action, exact in (
            ("draft_create", draft),
            ("release_publish", published),
        ):
            prerelease = {**exact, "isPrerelease": True}
            alias = {**exact, "targetCommitish": "main"}
            with self.subTest(action=action, drift="prerelease"):
                self.assertNotEqual(
                    release._critical_readback_identity(action, exact),
                    release._critical_readback_identity(action, prerelease),
                )
            with self.subTest(action=action, drift="raw_target"):
                self.assertNotEqual(
                    release._critical_readback_identity(action, exact),
                    release._critical_readback_identity(action, alias),
                )

    def test_cp16_materializes_numeric_followups_marker_last_and_rejects_partial_or_forged_state(
        self,
    ) -> None:
        state = _promotion_state("CP15")
        cp16 = state["checkpoints"]["CP16"]
        self.assertEqual(
            [operation["operation_id"] for operation in cp16["operations"]],
            ["CP16.draft_create"],
        )
        self.assertNotIn(
            "release_id",
            cp16["operations"][0]["intent"]["expected_before"],
        )
        release.validate_promotion_state(state)

        for field in (
            "schema_version",
            "tag",
            "base_main_commit",
            "candidate_tree",
            "sanitization_receipts",
            "created_at",
            "updated_at",
        ):
            missing = copy.deepcopy(state)
            del missing[field]
            with self.subTest(missing_required_state_field=field):
                self.policy_failure(
                    "E_V240_STATE_SCHEMA",
                    lambda missing=missing: release.validate_promotion_state(
                        missing
                    ),
                )
        for field, value in (
            ("schema_version", "evil"),
            ("transition_map_version", "evil"),
            ("repository", "attacker/fork"),
            ("version", "V2.39"),
            ("tag", "v2.39"),
            ("candidate_tree", "0" * 39),
        ):
            forged_identity = copy.deepcopy(state)
            forged_identity[field] = value
            with self.subTest(forged_state_identity=field):
                self.policy_failure(
                    "E_V240_STATE_FORGED",
                    lambda forged_identity=forged_identity: release.validate_promotion_state(
                        forged_identity
                    ),
                )

        precreated_cp17 = copy.deepcopy(state)
        precreated_cp17["checkpoints"]["CP17"] = copy.deepcopy(
            _promotion_state("CP16")["checkpoints"]["CP17"]
        )
        self.policy_failure(
            "E_V240_STATE_CHECKPOINT_GAP",
            lambda: release.validate_promotion_state(precreated_cp17),
        )

        precreated_cp16 = _promotion_state("CP14")
        precreated_cp16["checkpoints"]["CP16"] = copy.deepcopy(
            state["checkpoints"]["CP16"]
        )
        self.policy_failure(
            "E_V240_STATE_CHECKPOINT_GAP",
            lambda: release.validate_promotion_state(precreated_cp16),
        )

        truncated_all_passed = _promotion_state("CP15")
        del truncated_all_passed["checkpoints"]["CP16"]
        truncated_all_passed["current_checkpoint"] = "CP18"
        self.policy_failure(
            "E_V240_STATE_CHECKPOINT_GAP",
            lambda: release.validate_promotion_state(truncated_all_passed),
        )

        invalid_checkpoint_status = copy.deepcopy(state)
        invalid_checkpoint_status["checkpoints"]["CP16"]["status"] = "garbage"
        self.policy_failure(
            "E_V240_STATE_FORGED",
            lambda: release.validate_promotion_state(invalid_checkpoint_status),
        )
        invalid_operation_status = copy.deepcopy(state)
        invalid_operation_status["checkpoints"]["CP16"]["operations"][0][
            "status"
        ] = "garbage"
        self.policy_failure(
            "E_V240_STATE_FORGED",
            lambda: release.validate_promotion_state(invalid_operation_status),
        )

        existing_next = copy.deepcopy(state)
        self.policy_failure(
            "E_V240_STATE_CHECKPOINT_GAP",
            lambda: release._append_next_checkpoint(existing_next, "CP15", {}),
        )

        with_override = copy.deepcopy(state)
        del with_override["checkpoints"]["CP16"]
        self.policy_failure(
            "E_V240_STATE_EXPECTED_BEFORE",
            lambda: release._append_next_checkpoint(
                with_override,
                "CP15",
                {"next_checkpoint_expected_before": None},
            ),
        )

        draft = cp16["operations"][0]
        draft_details = {
            "databaseId": 987654321,
            "isDraft": True,
            "isImmutable": False,
            "isPrerelease": False,
            "tagName": TAG,
            "targetCommitish": CANDIDATE_COMMIT,
            "resolvedTargetCommit": CANDIDATE_COMMIT,
            "name": "Goal Teams V2.40",
            "body": "Goal Teams V2.40. See release/current/README.md in the tagged source.",
        }
        draft_readback = {
            "classification": "exact",
            "source": "github_api",
            "observed_at": "2026-07-14T07:00:01Z",
            "state_sha256": _canonical_json_sha256(draft_details),
            "details": draft_details,
        }
        cp16["status"] = "in_progress"
        draft["status"] = "in_progress"
        draft["readback"] = draft_readback
        draft["receipt_sha256"] = _canonical_json_sha256(
            {"intent": draft["intent"], "readback": draft_readback}
        )
        release.validate_promotion_state(state)

        release._materialize_cp16_post_draft_intents(state)
        self.assertEqual(len(cp16["operations"]), 7)
        self.assertEqual(
            {
                operation["intent"]["expected_before"]["release_id"]
                for operation in cp16["operations"][1:]
            },
            {987654321},
        )
        self.assertEqual(
            len(
                {
                    operation["intent"]["created_at"]
                    for operation in cp16["operations"][1:]
                }
            ),
            1,
        )
        release.validate_promotion_state(state)

        malformed_readback = copy.deepcopy(state)
        malformed_readback["checkpoints"]["CP16"]["operations"][0][
            "readback"
        ] = "evil"
        self.policy_failure(
            "E_V240_STATE_RECEIPT_CHAIN",
            lambda: release.validate_promotion_state(malformed_readback),
        )

        for length in range(2, 7):
            partial = copy.deepcopy(state)
            partial["checkpoints"]["CP16"]["operations"] = partial[
                "checkpoints"
            ]["CP16"]["operations"][:length]
            self.policy_failure(
                "E_V240_STATE_OPERATION_PLAN",
                lambda partial=partial: release.validate_promotion_state(partial),
            )

        forged = copy.deepcopy(state)
        forged["checkpoints"]["CP16"]["operations"][1]["intent"][
            "expected_before"
        ]["release_id"] = 1
        self.policy_failure(
            "E_V240_STATE_EXPECTED_BEFORE",
            lambda: release.validate_promotion_state(forged),
        )

    def test_cp16_two_invocation_engine_handles_new_existing_and_marker_loss_drafts(
        self,
    ) -> None:
        now = "2026-07-14T07:00:02Z"

        def exact(details: dict[str, Any], *, effects: int = 0) -> dict[str, Any]:
            return {
                "classification": "exact",
                "source": "github_api",
                "observed_at": now,
                "state_sha256": _canonical_json_sha256(details),
                "details": copy.deepcopy(details),
                "external_side_effect_count": effects,
            }

        class DraftAdapter:
            def __init__(self, *, fail_after_create: bool = False) -> None:
                self.fail_after_create = fail_after_create
                self.created = 0
                self.executed: list[str] = []
                self.observed: list[str] = []

            def observe(self, *, operation_id, action, expected_before, parameters):
                self.observed.append(operation_id)
                if operation_id == "CP16.draft_create":
                    return exact(draft_details)
                raise AssertionError(f"unexpected observe: {operation_id}")

            def _ruleset_by_name(self, name: str) -> dict[str, Any] | None:
                promotion = release._promotion_lock_ruleset_payload(state)
                tag = release._tag_ruleset_payload(state)
                if name == promotion["name"]:
                    return {"id": 24014, **promotion}
                if name == tag["name"]:
                    return {"id": 24015, **tag}
                return None

            def _validate_ruleset_payload(
                self, _action: str, _payload: dict[str, Any]
            ) -> None:
                return None

            def _remote_ref(self, ref: str) -> str:
                if ref != "refs/heads/main":
                    raise AssertionError(f"unexpected ref read: {ref}")
                return BASE_COMMIT

            def execute(self, *, operation_id, action, expected_before, parameters):
                self.executed.append(operation_id)
                if operation_id == "CP16.draft_create":
                    self.created += 1
                    if self.fail_after_create:
                        self.fail_after_create = False
                        raise release.PolicyError(
                            "E_V240_SYNTHETIC_CRASH",
                            "remote Draft exists but readback marker is absent",
                        )
                    return exact(draft_details, effects=1)
                if action == "asset_upload":
                    return exact(
                        {
                            "operation_id": operation_id,
                            "release_id": 987654321,
                        },
                        effects=1,
                    )
                if action == "asset_download_verify":
                    return exact(download_details)
                raise AssertionError(f"unexpected execute: {operation_id}")

        draft_details = {
            "databaseId": 987654321,
            "isDraft": True,
            "isImmutable": False,
            "isPrerelease": False,
            "tagName": TAG,
            "targetCommitish": CANDIDATE_COMMIT,
            "resolvedTargetCommit": CANDIDATE_COMMIT,
            "name": "Goal Teams V2.40",
            "body": "Goal Teams V2.40. See release/current/README.md in the tagged source.",
        }
        sealed_assets = _required_assets()
        sealed = {
            "assets": sealed_assets,
            "asset_set_sha256": _canonical_json_sha256(sealed_assets),
            "validator_receipt_sha256": "5" * 64,
        }
        downloaded_assets = [
            {
                "name": name,
                "asset_id": asset_id,
                "size": row["size"],
                "sha256": row["sha256"],
                "download_sha256": row["sha256"],
            }
            for asset_id, (name, row) in enumerate(
                sealed_assets.items(), start=501
            )
        ]
        download_details = {
            "release_id": 987654321,
            "release_state": "draft",
            "asset_set_sha256": sealed["asset_set_sha256"],
            "release_identity_sha256": "6" * 64,
            "assets": downloaded_assets,
        }
        rehearsal_details = {
            "source_commit": CANDIDATE_COMMIT,
            "install_report_sha256": "7" * 64,
            "release_id": 987654321,
            "asset_set_sha256": sealed["asset_set_sha256"],
            "draft_asset_identity_sha256": release._downloaded_asset_identity_sha256(
                downloaded_assets
            ),
            "release_identity_sha256": "6" * 64,
            "draft_download_details_sha256": _canonical_json_sha256(
                download_details
            ),
        }

        def write_state(path: Path) -> str:
            state = _promotion_state("CP15")
            path.write_text(
                json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            return hashlib.sha256(path.read_bytes()).hexdigest()

        def authorization(operation: dict[str, Any], mode: str) -> dict[str, Any]:
            intent = operation["intent"]
            expected_before = intent.get("expected_before")
            parameters = release._bound_operation_parameters(
                state,
                operation["operation_id"],
                intent["action"],
                expected_before,
            )
            return {
                "intent_sha256": _canonical_json_sha256(intent),
                "expected_before": copy.deepcopy(expected_before),
                "parameters_sha256": intent["parameters_sha256"],
                "expected_after_sha256": intent["expected_after_sha256"],
                "mode": mode,
                "parameters": parameters,
            }

        def patches(adapter: DraftAdapter):
            return (
                mock.patch.object(release, "_allowed_state_path", side_effect=lambda path: Path(path)),
                mock.patch.object(release, "_verify_frozen_git_identity", return_value={}),
                mock.patch.object(release, "_require_clean_candidate_checkout", return_value={}),
                mock.patch.object(release, "_revalidate_canonical_release", return_value=sealed),
                mock.patch.object(release, "_github_adapter_for_state", return_value=adapter),
                mock.patch.object(
                    release,
                    "_execute_local_operation",
                    return_value={
                        "classification": "exact",
                        "source": "installed_tree",
                        "observed_at": now,
                        "state_sha256": _canonical_json_sha256(rehearsal_details),
                        "details": copy.deepcopy(rehearsal_details),
                    },
                ),
                mock.patch.object(
                    release,
                    "_derive_checkpoint_state_updates",
                    side_effect=release._derive_checkpoint_state_updates,
                ),
            )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "promotion-state.json"
            digest = write_state(path)
            state = json.loads(path.read_text(encoding="utf-8"))
            draft = state["checkpoints"]["CP16"]["operations"][0]
            adapter = DraftAdapter()
            contexts = patches(adapter)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5], contexts[6]:
                self.policy_failure(
                    "E_V240_STATE_EXPECTED_BEFORE",
                    lambda: release.execute_current_checkpoint(
                        path,
                        {
                            "expected_state_sha256": digest,
                            "checkpoint_id": "CP16",
                            "next_checkpoint_expected_before": None,
                            "operation_authorizations": {
                                "CP16.draft_create": authorization(
                                    draft, "execute_github"
                                )
                            },
                        },
                    ),
                )
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                self.assertEqual(adapter.created, 0)
                self.policy_failure(
                    "E_V240_OPERATION_AUTHORIZATION",
                    lambda: release.execute_current_checkpoint(
                        path,
                        {
                            "expected_state_sha256": digest,
                            "checkpoint_id": "CP16",
                            "operation_authorizations": {
                                "CP16.draft_create": authorization(
                                    draft, "execute_github"
                                ),
                                "CP16.asset_upload_tar": {},
                            },
                        },
                    ),
                )
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
                self.assertEqual(adapter.created, 0)
                first = release.execute_current_checkpoint(
                    path,
                    {
                        "expected_state_sha256": digest,
                        "checkpoint_id": "CP16",
                        "operation_authorizations": {
                            "CP16.draft_create": authorization(
                                draft, "execute_github"
                            )
                        },
                    },
                )
                self.assertEqual(first["next_checkpoint"], "CP16")
                self.assertEqual(
                    first["checkpoint_stage"],
                    "draft_bound_followup_intents_persisted",
                )
                self.assertEqual(adapter.created, 1)
                state = json.loads(path.read_text(encoding="utf-8"))
                operations = state["checkpoints"]["CP16"]["operations"]
                self.assertEqual(len(operations), 7)
                second_authorizations = {
                    operation["operation_id"]: authorization(
                        operation,
                        "execute_local"
                        if operation["operation_id"]
                        == "CP16.remote_bundle_rehearsal"
                        else "execute_github",
                    )
                    for operation in operations
                }
                second = release.execute_current_checkpoint(
                    path,
                    {
                        "expected_state_sha256": first["state_sha256"],
                        "checkpoint_id": "CP16",
                        "operation_authorizations": second_authorizations,
                    },
                )
            self.assertEqual(second["next_checkpoint"], "CP17")
            self.assertEqual(adapter.created, 1)
            self.assertEqual(
                [item for item in adapter.executed if "asset_upload" in item],
                [
                    "CP16.asset_upload_tar",
                    "CP16.asset_upload_sums",
                    "CP16.asset_upload_release",
                    "CP16.asset_upload_files",
                ],
            )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing-state.json"
            digest = write_state(path)
            state = json.loads(path.read_text(encoding="utf-8"))
            draft = state["checkpoints"]["CP16"]["operations"][0]
            adapter = DraftAdapter()
            contexts = patches(adapter)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5], contexts[6]:
                adopted = release.execute_current_checkpoint(
                    path,
                    {
                        "expected_state_sha256": digest,
                        "checkpoint_id": "CP16",
                        "operation_authorizations": {
                            "CP16.draft_create": authorization(draft, "observe")
                        },
                    },
                )
            self.assertEqual(adopted["next_checkpoint"], "CP16")
            self.assertEqual(adapter.created, 0)
            self.assertEqual(adapter.observed, ["CP16.draft_create"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "crash-state.json"
            digest = write_state(path)
            state = json.loads(path.read_text(encoding="utf-8"))
            draft = state["checkpoints"]["CP16"]["operations"][0]
            adapter = DraftAdapter(fail_after_create=True)
            contexts = patches(adapter)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5], contexts[6]:
                self.policy_failure(
                    "E_V240_SYNTHETIC_CRASH",
                    lambda: release.execute_current_checkpoint(
                        path,
                        {
                            "expected_state_sha256": digest,
                            "checkpoint_id": "CP16",
                            "operation_authorizations": {
                                "CP16.draft_create": authorization(
                                    draft, "execute_github"
                                )
                            },
                        },
                    ),
                )
                crashed_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                crashed = json.loads(path.read_text(encoding="utf-8"))
                crashed_draft = crashed["checkpoints"]["CP16"]["operations"][0]
                recovered = release.execute_current_checkpoint(
                    path,
                    {
                        "expected_state_sha256": crashed_digest,
                        "checkpoint_id": "CP16",
                        "operation_authorizations": {
                            "CP16.draft_create": authorization(
                                crashed_draft, "observe"
                            )
                        },
                    },
                    recover_only=True,
                )
            self.assertEqual(recovered["next_checkpoint"], "CP16")
            self.assertEqual(adapter.created, 1)
            self.assertEqual(adapter.observed, ["CP16.draft_create"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readback-marker-loss-state.json"
            state = _promotion_state("CP15")
            cp16 = state["checkpoints"]["CP16"]
            draft = cp16["operations"][0]
            readback = exact(draft_details)
            readback.pop("external_side_effect_count")
            cp16["status"] = "in_progress"
            draft["status"] = "in_progress"
            draft["readback"] = readback
            draft["receipt_sha256"] = _canonical_json_sha256(
                {"intent": draft["intent"], "readback": readback}
            )
            path.write_text(
                json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            adapter = DraftAdapter()
            contexts = patches(adapter)
            with contexts[0], contexts[1], contexts[2], contexts[3], contexts[4], contexts[5], contexts[6]:
                recovered = release.execute_current_checkpoint(
                    path,
                    {
                        "expected_state_sha256": digest,
                        "checkpoint_id": "CP16",
                        "operation_authorizations": {
                            "CP16.draft_create": authorization(draft, "observe")
                        },
                    },
                    recover_only=True,
                )
            recovered_state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                recovered["checkpoint_stage"],
                "draft_bound_followup_intents_persisted",
            )
            self.assertEqual(recovered["next_checkpoint"], "CP16")
            self.assertEqual(len(recovered_state["checkpoints"]["CP16"]["operations"]), 7)
            self.assertEqual(adapter.created, 0)
            self.assertEqual(adapter.executed, [])
            self.assertEqual(adapter.observed, ["CP16.draft_create"])

    def test_v240_files_manifest_builder_validator_four_column_contract(self) -> None:
        format_manifest = self.build_api("format_v240_files_manifest")
        parse_manifest = self.validator_api("parse_v240_files_manifest")
        rows = [
            {
                "sha256": "1" * 64,
                "mode": "100644",
                "size": 3,
                "path": "README.md",
            },
            {
                "sha256": "2" * 64,
                "mode": "100755",
                "size": 17,
                "path": "scripts/check.sh",
            },
        ]
        expected = (
            f"{'1' * 64}\t100644\t3\tREADME.md\n"
            f"{'2' * 64}\t100755\t17\tscripts/check.sh\n"
        )
        manifest = format_manifest(rows)
        self.assertEqual(manifest, expected)
        self.assertEqual(parse_manifest(manifest), rows)
        self.policy_failure(
            "E_V240_FILES_MANIFEST_COLUMNS",
            lambda: parse_manifest(f"{'1' * 64}  README.md\n"),
        )

    def test_single_release_entry_advertises_the_frozen_command_set(self) -> None:
        self.assertTrue(RELEASE_ENTRY.is_file(), "scripts/release/release.py is required")
        proc = subprocess.run(
            [sys.executable, str(RELEASE_ENTRY), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        help_text = proc.stdout + proc.stderr
        for command in ("doctor", "prepare", "promote", "status", "recover", "close"):
            with self.subTest(command=command):
                self.assertIn(command, help_text)
        self.assertIn("single release entry", help_text.lower())

    def test_required_release_policy_apis_exist(self) -> None:
        for name in (
            "validate_readme_projection",
            "require_frozen_commit",
            "validate_frozen_release_record",
            "validate_workspace_facts",
            "commit_checkpoint",
            "plan_resume",
            "validate_remote_lease",
            "evaluate_ci_conclusions",
            "validate_draft_assets",
            "validate_install_identity",
            "safe_extract_release_tar",
            "validate_tar_limits",
            "validate_remote_promotion_lock",
            "classify_remote_resource",
            "recover_operation",
            "validate_ci_receipt",
            "validate_promotion_state",
            "validate_safe_ancestors",
            "scan_public_payload",
            "validate_release_bundle",
            "validate_remote_immutability",
            "validate_github_live_authority",
            "redact_private_ignored_log",
        ):
            with self.subTest(name=name):
                self.release_api(name)
        self.audit_api("audit_release_identity")

    def test_cp09_fault_injection_rejects_any_second_build_identity_drift(self) -> None:
        compare = self.release_api("_require_reproducible_build_receipts")
        primary = {
            "tree_sha256": "1" * 64,
            "file_count": 449,
            "rows_sha256": "2" * 64,
            "source_commit": CANDIDATE_COMMIT,
            "source_git_tree_id": "3" * 40,
            "artifact_sha256": "4" * 64,
        }
        self.assertRegex(
            compare(primary, copy.deepcopy(primary))["build_identity_sha256"],
            r"^[0-9a-f]{64}$",
        )
        for field, replacement in (
            ("tree_sha256", "5" * 64),
            ("rows_sha256", "6" * 64),
            ("file_count", 450),
            ("artifact_sha256", "7" * 64),
            ("source_git_tree_id", "8" * 40),
        ):
            secondary = copy.deepcopy(primary)
            secondary[field] = replacement
            with self.subTest(field=field):
                receipt = self.policy_failure(
                    "E_V240_BUILD_REPRODUCIBILITY",
                    lambda secondary=secondary: compare(primary, secondary),
                )
                self.assertIn(field, receipt["mismatched_fields"])

    def test_cp06_static_gate_explicitly_executes_security_fixtures(self) -> None:
        source = RELEASE_ENTRY.read_text(encoding="utf-8")
        cp06 = source.split('if operation_id == "CP06.static_gates":', 1)[1]
        cp06 = cp06.split('if operation_id == "CP07.quality_gates":', 1)[0]
        self.assertIn("check-security-fixtures.py", cp06)

    def test_fixed_release_commands_reject_the_installer_only_profile(self) -> None:
        run_fixed = self.release_api("_run_fixed")
        probe = (
            sys.executable,
            "-c",
            "import os; print(os.environ.get('GOAL_TEAMS_INSTALL_VALIDATION', 'absent'))",
        )
        with mock.patch.dict(
            os.environ, {"GOAL_TEAMS_INSTALL_VALIDATION": "1"}
        ):
            result = run_fixed(probe)
        self.assertEqual(result.stdout.strip(), "absent")
        self.policy_failure(
            "E_V240_GATE_PROFILE",
            lambda: run_fixed(
                probe,
                env={"GOAL_TEAMS_INSTALL_VALIDATION": "1"},
            ),
        )

    def test_cp07_receipt_is_bound_to_the_full_cross_python_gate(self) -> None:
        execute = self.release_api("_execute_local_operation_unchecked")
        completed = subprocess.CompletedProcess(("gate",), 0, "passed\n", "")
        state = {
            "version": VERSION,
            "candidate_commit": CANDIDATE_COMMIT,
        }
        with mock.patch.object(
            release, "_workspace_root", return_value=ROOT
        ), mock.patch.object(
            release, "validate_safe_ancestors"
        ), mock.patch.object(
            release,
            "_require_clean_candidate_checkout",
            return_value={
                "path": str(ROOT.resolve()),
                "branch": "codex/v2.40",
                "head": CANDIDATE_COMMIT,
                "clean": True,
                "status_sha256": _sha256_bytes(b""),
            },
        ), mock.patch.object(
            release, "_run_fixed", return_value=completed
        ) as run_fixed:
            receipt = execute(
                "CP07.quality_gates",
                state,
                {},
                ROOT / "docs" / "release-state" / VERSION / "promotion-state.json",
            )
        self.assertEqual(receipt["classification"], "exact")
        self.assertEqual(receipt["details"]["quality_gate_profile"], "full_release_gate")
        self.assertIs(receipt["details"]["installer_package_profile"], False)
        self.assertIs(receipt["details"]["cross_python_required"], True)
        self.assertEqual(
            receipt["details"]["quality_gate_commands"],
            [list(command) for command in CP07_QUALITY_GATE_COMMAND_SET],
        )
        self.assertEqual(len(receipt["details"]["quality_gate_receipts"]), 4)
        self.assertEqual(
            receipt["details"]["candidate_checkout"]["location"],
            "develops/v2.40",
        )
        self.assertNotIn("path", receipt["details"]["candidate_checkout"])
        self.assertEqual(
            receipt["details"]["receipt_trust_level"], "local_unattested"
        )
        self.assertEqual(
            receipt["details"]["authoritative_execution_proof"],
            {
                "checkpoint_id": "CP13",
                "operation_id": "CP13.candidate_ci",
                "required_jobs": [
                    "check-ubuntu",
                    "check-macos",
                    "release-asset-gate",
                ],
            },
        )
        self.assertEqual(run_fixed.call_count, 4)
        for call in run_fixed.call_args_list:
            self.assertEqual(
                call.kwargs.get("env"),
                {
                    "GOAL_TEAMS_REQUIRE_CROSS_PYTHON": "1",
                    "PYTHON": sys.executable,
                },
            )

    def test_cp07_persisted_receipt_rejects_every_full_gate_downgrade(self) -> None:
        valid = _promotion_state("CP09")
        release.validate_promotion_state(valid)

        def mutate_and_reseal(mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
            state = copy.deepcopy(valid)
            checkpoint = state["checkpoints"]["CP07"]
            operation = checkpoint["operations"][0]
            details = operation["readback"]["details"]
            mutator(details)
            operation["readback"]["state_sha256"] = _canonical_json_sha256(details)
            operation["receipt_sha256"] = _canonical_json_sha256(
                {"intent": operation["intent"], "readback": operation["readback"]}
            )
            checkpoint["receipt_sha256"] = _canonical_json_sha256(
                [operation["receipt_sha256"]]
            )
            return state

        mutations: tuple[Callable[[dict[str, Any]], None], ...] = (
            lambda details: details.pop("quality_gate_profile"),
            lambda details: details.__setitem__("quality_gate_profile", "package_validation"),
            lambda details: details.__setitem__("installer_package_profile", True),
            lambda details: details.__setitem__("cross_python_required", False),
            lambda details: details.__setitem__("quality_gate_receipts", []),
            lambda details: details.__setitem__("quality_gate_receipts", ["not-a-sha"] * 4),
            lambda details: details["quality_gate_commands"][0].append("--downgrade"),
            lambda details: details.__setitem__("quality_gate_command_set_sha256", "0" * 64),
            lambda details: details.__setitem__("receipt_trust_level", "host_attested"),
            lambda details: details["authoritative_execution_proof"].__setitem__(
                "checkpoint_id", "CP07"
            ),
            lambda details: details["candidate_checkout"].__setitem__("clean", False),
            lambda details: details["candidate_checkout"].__setitem__(
                "location", "attacker/develops/v2.40"
            ),
        )
        for index, mutator in enumerate(mutations):
            with self.subTest(mutation=index):
                tampered = mutate_and_reseal(mutator)
                self.policy_failure(
                    "E_V240_GATE_PROFILE",
                    lambda tampered=tampered: release.validate_promotion_state(tampered),
                )

    def test_cp07_state_identity_is_portable_but_live_checkout_is_rechecked(self) -> None:
        state = _promotion_state("CP09")
        with mock.patch.object(
            release,
            "RELEASE_ROOT",
            Path("/ci/checkout/goal-teams"),
        ):
            release.validate_promotion_state(state)

        execute = self.release_api("_execute_local_operation_unchecked")
        clean = {
            "path": str(ROOT.resolve()),
            "branch": "codex/v2.40",
            "head": CANDIDATE_COMMIT,
            "clean": True,
            "status_sha256": _sha256_bytes(b""),
        }
        drifted = {**clean, "head": "c" * 40}
        completed = subprocess.CompletedProcess(("gate",), 0, "passed\n", "")
        with mock.patch.object(
            release, "_workspace_root", return_value=ROOT
        ), mock.patch.object(
            release, "validate_safe_ancestors"
        ), mock.patch.object(
            release,
            "_require_clean_candidate_checkout",
            side_effect=(clean, drifted),
        ), mock.patch.object(release, "_run_fixed", return_value=completed):
            self.policy_failure(
                "E_V240_GATE_PROFILE",
                lambda: execute(
                    "CP07.quality_gates",
                    {"version": VERSION, "candidate_commit": CANDIDATE_COMMIT},
                    {},
                    ROOT
                    / "docs"
                    / "release-state"
                    / VERSION
                    / "promotion-state.json",
                ),
            )

    @unittest.skipIf(
        os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1",
        "real CP11 release rehearsal is not recursively executed inside installer validation",
    )
    def test_cp11_real_release_tar_runs_fresh_update_and_explicit_rollback(self) -> None:
        rehearse = self.release_api("_run_release_bundle_lifecycle_rehearsal")
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output_root = root / "release"
            built = subprocess.run(
                [
                    sys.executable,
                    str(BUILD_ENTRY),
                    "--version",
                    VERSION,
                    "--commit",
                    commit,
                    "--source-ref",
                    commit,
                    "--output-root",
                    str(output_root),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            snapshot = output_root / VERSION
            sources = {
                f"goal-teams-{VERSION}.tar.gz": snapshot
                / "_artifacts"
                / f"goal-teams-{VERSION}.tar.gz",
                "SHA256SUMS": snapshot / "_artifacts" / "SHA256SUMS",
                "_release.json": snapshot / "_release.json",
                "_files.sha256": snapshot / "_files.sha256",
            }
            bundle = root / "bundle"
            bundle.mkdir()
            assets: list[dict[str, Any]] = []
            for name, source in sorted(sources.items()):
                target = bundle / name
                target.write_bytes(source.read_bytes())
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                assets.append(
                    {
                        "name": name,
                        "asset_id": 0,
                        "size": target.stat().st_size,
                        "sha256": digest,
                        "download_sha256": digest,
                    }
                )
            release_record = json.loads(
                (snapshot / "_release.json").read_text(encoding="utf-8")
            )
            identity = root / "release-identity.json"
            identity.write_text(
                json.dumps(
                    {
                        "source_kind": "local_release_bundle",
                        "repository": "vibe-coding-era/goal-teams",
                        "version": VERSION,
                        "release_tag": TAG,
                        "release_id": 0,
                        "release_state": "local",
                        "source_commit": commit,
                        "source_git_tree_id": release_record["source_git_tree_id"],
                        "assets": assets,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            # CP06/CP07 own the full check.sh matrix. This targeted integration
            # keeps the real release tar, installer extraction, OKF replay,
            # backup, live switch, state, report, update, and rollback paths,
            # while replacing only the six repeated check.sh invocations.
            harness_bin = root / "harness-bin"
            harness_bin.mkdir()
            harness_log = root / "check-harness.log"
            bash_wrapper = harness_bin / "bash"
            bash_wrapper.write_text(
                "#!/bin/sh\n"
                "case \"${1:-}\" in\n"
                "  */scripts/check.sh) "
                "printf '%s\\n' \"$1\" >> \"$GOAL_TEAMS_TEST_CHECK_LOG\"; exit 0 ;;\n"
                "esac\n"
                "exec /bin/bash \"$@\"\n",
                encoding="utf-8",
            )
            bash_wrapper.chmod(0o755)
            real_run_fixed = release._run_fixed

            def test_run_fixed(
                argv: Any,
                *,
                cwd: Path = release.RELEASE_ROOT,
                env: dict[str, str] | None = None,
            ) -> Any:
                injected = dict(env or {})
                injected["PATH"] = (
                    str(harness_bin)
                    + ":"
                    + release.os.environ.get("PATH", "")
                )
                injected["GOAL_TEAMS_TEST_CHECK_LOG"] = str(harness_log)
                return real_run_fixed(argv, cwd=cwd, env=injected)

            with mock.patch.object(
                release, "_run_fixed", side_effect=test_run_fixed
            ):
                try:
                    receipt = rehearse(
                        bundle,
                        identity,
                        root / "rehearsal",
                        allowed_root=root,
                    )
                except Exception as exc:
                    self.fail(
                        json.dumps(
                            getattr(exc, "receipt", {"exception": repr(exc)}),
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                        )
                    )
            check_calls = harness_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(check_calls), 6)
            self.assertTrue(
                all(path.endswith("/scripts/check.sh") for path in check_calls)
            )
            self.assertEqual(receipt["fresh_install_action"], "install")
            self.assertEqual(receipt["update_install_action"], "update")
            self.assertEqual(receipt["rollback_action"], "rollback")
            self.assertTrue(receipt["rollback_restored_fresh_state"])
            self.assertEqual(receipt["fresh_install_source_commit"], commit)
            for field in (
                "fresh_install_report_sha256",
                "update_install_report_sha256",
                "rollback_report_sha256",
                "fresh_install_state_sha256",
            ):
                self.assertRegex(receipt[field], r"^[0-9a-f]{64}$")
            report_root = root / "rehearsal" / "codex-home" / "reports"
            fresh_report = json.loads(
                (report_root / "fresh-install-report.json").read_text(
                    encoding="utf-8"
                )
            )
            update_report = json.loads(
                (report_root / "update-install-report.json").read_text(
                    encoding="utf-8"
                )
            )
            rollback_report = json.loads(
                (report_root / "rollback-report.json").read_text(
                    encoding="utf-8"
                )
            )
            for report in (fresh_report, update_report):
                check_rows = [
                    row
                    for row in report["validation"]
                    if row.get("command") == "scripts/check.sh"
                ]
                self.assertEqual(len(check_rows), 3)
                self.assertTrue(all(row["status"] == "passed" for row in check_rows))
                phases = {row["phase"] for row in report["validation"]}
                self.assertTrue(
                    {
                        "okf_package_tree_source",
                        "okf_package_tree_staging",
                        "backup",
                    }
                    <= phases
                )
                self.assertGreater(len(report["package_files"]), 100)
                self.assertEqual(
                    report["source"]["source_kind"], "local_release_bundle"
                )
            self.assertIn("skill", update_report["backed_up_components"])
            rollback_phases = {
                row["phase"] for row in rollback_report["validation"]
            }
            self.assertTrue({"backup", "restore"} <= rollback_phases)
            self.assertFalse(
                any(
                    row.get("command") == "scripts/check.sh"
                    for row in rollback_report["validation"]
                )
            )

    def test_readme_projection_accepts_one_matching_controlled_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_readmes(root)
            receipt = self.release_api("validate_readme_projection")(root, VERSION)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["version"], VERSION)
        self.assertEqual(set(receipt["files"]), {"README.md", "README.en.md"})
        for record in receipt["files"].values():
            self.assertRegex(record["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(record["marker_count"], 1)

    def test_readme_projection_rejects_marker_version_and_link_drift(self) -> None:
        cases = (
            ("missing", "plain README\n", "plain README\n", "E_V240_README_MARKER"),
            (
                "duplicate",
                _release_block() + _release_block(),
                _release_block(),
                "E_V240_README_MARKER",
            ),
            (
                "language_version_drift",
                _release_block(),
                _release_block("V2.39"),
                "E_V240_README_VERSION",
            ),
            (
                "stale_current_identity",
                _release_block().replace("Current release", "Current release V2.39; now"),
                _release_block(),
                "E_V240_README_STALE_IDENTITY",
            ),
            (
                "current_link_missing",
                _release_block(current_link=False),
                _release_block(),
                "E_V240_README_CURRENT_LINK",
            ),
        )
        validate = self.release_api("validate_readme_projection")
        for name, zh, en, code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _write_readmes(root, zh=zh, en=en)
                with self.assertRaisesRegex(Exception, code):
                    validate(root, VERSION)

    def test_frozen_commit_requires_exact_lowercase_git_sha(self) -> None:
        require = self.release_api("require_frozen_commit")
        receipt = require(CANDIDATE_COMMIT)
        self.assertEqual(receipt["commit"], CANDIDATE_COMMIT)
        self.assertTrue(receipt["frozen"])
        for value in ("HEAD", "codex/v2.40", "b" * 39, "B" * 40, "b" * 41):
            with self.subTest(value=value), self.assertRaisesRegex(
                Exception, "E_V240_FROZEN_COMMIT"
            ):
                require(value)

    def test_release_record_uses_commit_as_authority_not_mutable_ref(self) -> None:
        validate = self.release_api("validate_frozen_release_record")
        record = {
            "version": VERSION,
            "source_commit": CANDIDATE_COMMIT,
            "source_ref": "codex/v2.40",
            "source_git_tree_id": "d" * 40,
        }
        receipt = validate(record, VERSION, CANDIDATE_COMMIT)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["identity_authority"], "source_commit")
        moved_ref = copy.deepcopy(record)
        moved_ref["source_ref"] = "refs/heads/renamed-after-release"
        self.assertTrue(validate(moved_ref, VERSION, CANDIDATE_COMMIT)["passed"])
        for field, value in (
            ("source_commit", "HEAD"),
            ("source_commit", BASE_COMMIT),
            ("version", "V2.39"),
        ):
            invalid = copy.deepcopy(record)
            invalid[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                Exception, "E_V240_RELEASE_SOURCE_IDENTITY"
            ):
                validate(invalid, VERSION, CANDIDATE_COMMIT)

    def test_workspace_doctor_accepts_only_the_canonical_topology(self) -> None:
        receipt = self.release_api("validate_workspace_facts")(_workspace_facts())
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["candidate_commit"], CANDIDATE_COMMIT)
        self.assertEqual(receipt["remote_main_commit"], BASE_COMMIT)
        self.assertGreaterEqual(len(receipt["checks"]), 8)
        self.assertTrue(all(check["status"] == "passed" for check in receipt["checks"]))

    def test_workspace_doctor_fails_closed_for_each_boundary(self) -> None:
        cases = (
            ("dirty", True, "E_V240_WORKTREE_DIRTY"),
            ("candidate_location", "../goal-teams-v240", "E_V240_WORKTREE_LOCATION"),
            ("candidate_branch", "main", "E_V240_WORKTREE_BRANCH"),
            (
                "candidate_descends_from_remote_main",
                False,
                "E_V240_CANDIDATE_ANCESTRY",
            ),
            ("tracked_local_only_paths", ["docs/private.md"], "E_V240_LOCAL_PATH_TRACKED"),
            ("parent_version_copies", ["goal-teams-v240"], "E_V240_PARENT_COPY"),
            ("tag_exists", True, "E_V240_TAG_EXISTS"),
            ("release_exists", True, "E_V240_RELEASE_EXISTS"),
        )
        validate = self.release_api("validate_workspace_facts")
        for field, value, code in cases:
            facts = _workspace_facts()
            facts[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(Exception, code):
                validate(facts)
        facts = _workspace_facts()
        facts["tools"]["gh"] = False
        with self.assertRaisesRegex(Exception, "E_V240_TOOL_UNAVAILABLE"):
            validate(facts)

    def test_checkpoint_marker_is_written_only_after_verified_receipt(self) -> None:
        commit = self.release_api("commit_checkpoint")
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "promote-state.json"
            before = _promotion_state("CP09")
            state_path.write_text(json.dumps(before, sort_keys=True) + "\n", encoding="utf-8")
            original = state_path.read_bytes()
            with self.assertRaisesRegex(Exception, "E_V240_CHECKPOINT_UNVERIFIED"):
                commit(
                    state_path,
                    "CP10",
                    {"verified": False, "candidate_commit": CANDIDATE_COMMIT},
                )
            self.assertEqual(state_path.read_bytes(), original)
            result = commit(
                state_path,
                "CP10",
                {
                    "verified": True,
                    "candidate_commit": CANDIDATE_COMMIT,
                    "receipt_sha256": "e" * 64,
                },
            )
            stored = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(result["current_checkpoint"], "CP10")
        self.assertEqual(stored["current_checkpoint"], "CP10")
        self.assertEqual(stored["checkpoints"]["CP10"]["receipt_sha256"], "e" * 64)

    def test_checkpoint_resume_is_idempotent_and_does_not_repeat_side_effect(self) -> None:
        commit = self.release_api("commit_checkpoint")
        plan_resume = self.release_api("plan_resume")
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "promote-state.json"
            state = _promotion_state("CP12")
            state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
            before = state_path.read_bytes()
            result = commit(
                state_path,
                "CP12",
                {
                    "verified": True,
                    "candidate_commit": CANDIDATE_COMMIT,
                    "receipt_sha256": state["checkpoints"]["CP12"]["receipt_sha256"],
                },
            )
            self.assertEqual(state_path.read_bytes(), before)
            plan = plan_resume(state_path)
        self.assertTrue(result["already_completed"])
        self.assertEqual(plan["next_checkpoint"], "CP13")
        self.assertIn("CP12", plan["skip_side_effects"])
        self.assertNotIn("atomic_main_tag_push", plan["actions"])

    def test_checkpoint_order_cannot_skip_a_required_stage(self) -> None:
        commit = self.release_api("commit_checkpoint")
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "promote-state.json"
            state_path.write_text(
                json.dumps(_promotion_state("CP09"), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "E_V240_CHECKPOINT_ORDER"):
                commit(
                    state_path,
                    "CP11",
                    {
                        "verified": True,
                        "candidate_commit": CANDIDATE_COMMIT,
                        "receipt_sha256": "f" * 64,
                    },
                )

    def test_remote_main_lease_requires_exact_unchanged_sha(self) -> None:
        validate = self.release_api("validate_remote_lease")
        receipt = validate(BASE_COMMIT, BASE_COMMIT, CANDIDATE_COMMIT)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["expected_main_commit"], BASE_COMMIT)
        self.assertEqual(receipt["candidate_commit"], CANDIDATE_COMMIT)
        with self.assertRaisesRegex(Exception, "E_V240_REMOTE_MAIN_LEASE"):
            validate(BASE_COMMIT, "9" * 40, CANDIDATE_COMMIT)

    def test_ci_gate_accepts_only_complete_exact_sha_success(self) -> None:
        evaluate = self.release_api("evaluate_ci_conclusions")
        jobs = [
            {"name": "check-ubuntu", "head_sha": CANDIDATE_COMMIT, "conclusion": "success"},
            {"name": "check-macos", "head_sha": CANDIDATE_COMMIT, "conclusion": "success"},
            {"name": "release-asset-gate", "head_sha": CANDIDATE_COMMIT, "conclusion": "success"},
        ]
        receipt = evaluate(
            jobs,
            CANDIDATE_COMMIT,
            ["check-ubuntu", "check-macos", "release-asset-gate"],
        )
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["head_sha"], CANDIDATE_COMMIT)
        self.assertEqual(receipt["successful_jobs"], [
            "check-macos",
            "check-ubuntu",
            "release-asset-gate",
        ])

    def test_ci_gate_rejects_failed_cancelled_skipped_missing_and_wrong_sha(self) -> None:
        evaluate = self.release_api("evaluate_ci_conclusions")
        required = ["check-ubuntu", "check-macos"]
        for conclusion in ("failure", "cancelled", "skipped", "timed_out", "action_required"):
            jobs = [
                {"name": "check-ubuntu", "head_sha": CANDIDATE_COMMIT, "conclusion": "success"},
                {"name": "check-macos", "head_sha": CANDIDATE_COMMIT, "conclusion": conclusion},
            ]
            with self.subTest(conclusion=conclusion), self.assertRaisesRegex(
                Exception, "E_V240_CI_NOT_SUCCESS"
            ):
                evaluate(jobs, CANDIDATE_COMMIT, required)
        with self.assertRaisesRegex(Exception, "E_V240_CI_REQUIRED_MISSING"):
            evaluate(
                [{"name": "check-ubuntu", "head_sha": CANDIDATE_COMMIT, "conclusion": "success"}],
                CANDIDATE_COMMIT,
                required,
            )
        with self.assertRaisesRegex(Exception, "E_V240_CI_SHA_MISMATCH"):
            evaluate(
                [
                    {"name": "check-ubuntu", "head_sha": BASE_COMMIT, "conclusion": "success"},
                    {"name": "check-macos", "head_sha": BASE_COMMIT, "conclusion": "success"},
                ],
                CANDIDATE_COMMIT,
                required,
            )

    def test_draft_requires_exact_four_downloaded_asset_identities(self) -> None:
        validate = self.release_api("validate_draft_assets")
        expected = _required_assets()
        observed = copy.deepcopy(expected)
        receipt = validate(VERSION, expected, observed)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["asset_names"], sorted(expected))
        self.assertEqual(receipt["verification"], "downloaded_byte_identity")

    def test_draft_rejects_missing_extra_or_tampered_asset(self) -> None:
        validate = self.release_api("validate_draft_assets")
        expected = _required_assets()
        cases: list[tuple[str, dict[str, Any], str]] = []
        missing = copy.deepcopy(expected)
        missing.pop("_release.json")
        cases.append(("missing", missing, "E_V240_DRAFT_ASSET_SET"))
        extra = copy.deepcopy(expected)
        extra["unreviewed.bin"] = {"sha256": "5" * 64, "size": 105}
        cases.append(("extra", extra, "E_V240_DRAFT_ASSET_SET"))
        tampered = copy.deepcopy(expected)
        tampered[f"goal-teams-{VERSION}.tar.gz"]["sha256"] = "6" * 64
        cases.append(("tampered", tampered, "E_V240_DRAFT_ASSET_IDENTITY"))
        resized = copy.deepcopy(expected)
        resized["SHA256SUMS"]["size"] += 1
        cases.append(("resized", resized, "E_V240_DRAFT_ASSET_IDENTITY"))
        for name, observed, code in cases:
            with self.subTest(name=name), self.assertRaisesRegex(Exception, code):
                validate(VERSION, expected, observed)

    def test_install_identity_binds_downloaded_asset_tag_release_and_commit(self) -> None:
        release_receipt, install_state = _install_identity()
        receipt = self.release_api("validate_install_identity")(
            release_receipt, install_state
        )
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["source_kind"], "github_release_asset")
        self.assertEqual(receipt["source_commit"], CANDIDATE_COMMIT)
        self.assertEqual(receipt["asset_sha256"], ARTIFACT_SHA256)

    def test_install_identity_rejects_each_missing_or_drifted_binding(self) -> None:
        release_receipt, base_state = _install_identity()
        cases = (
            ("source_kind", "worktree", "E_V240_INSTALL_SOURCE_KIND"),
            ("source_commit", BASE_COMMIT, "E_V240_INSTALL_COMMIT"),
            ("release_tag", "v2.39", "E_V240_INSTALL_TAG"),
            ("release_id", "REL-OTHER", "E_V240_INSTALL_RELEASE"),
            ("release_asset_sha256", "0" * 64, "E_V240_INSTALL_ASSET"),
            ("source_dirty", True, "E_V240_INSTALL_DIRTY"),
        )
        validate = self.release_api("validate_install_identity")
        for field, value, code in cases:
            install_state = copy.deepcopy(base_state)
            install_state[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(Exception, code):
                validate(release_receipt, install_state)

    def test_independent_audit_proves_five_point_and_readme_byte_identity(self) -> None:
        receipt = self.audit_api("audit_release_identity")(_audit_observation())
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["source_commit"], CANDIDATE_COMMIT)
        self.assertEqual(receipt["identity_points"], [
            "main",
            "tag",
            "release",
            "asset",
            "installed",
        ])
        self.assertEqual(receipt["latest_release_tag"], TAG)
        self.assertEqual(receipt["readme_files"], ["README.en.md", "README.md"])

    def test_independent_audit_ignores_forged_promote_success(self) -> None:
        observation = _audit_observation()
        observation["commits"]["installed"] = BASE_COMMIT
        observation["promote_reported_passed"] = True
        with self.assertRaisesRegex(Exception, "E_V240_FIVE_POINT_IDENTITY"):
            self.audit_api("audit_release_identity")(observation)

    def test_independent_audit_rejects_readme_latest_release_and_post_ci_drift(self) -> None:
        cases: list[tuple[str, dict[str, Any], str]] = []
        readme = _audit_observation()
        readme["readme_sha256"]["README.md"]["installed"] = "0" * 64
        cases.append(("readme", readme, "E_V240_README_BYTE_IDENTITY"))
        latest = _audit_observation()
        latest["latest_release_tag"] = "v2.39"
        cases.append(("latest", latest, "E_V240_LATEST_RELEASE"))
        post_ci = _audit_observation()
        post_ci["ci"]["post_release"]["jobs"][1]["conclusion"] = "cancelled"
        cases.append(("post_ci", post_ci, "E_V240_POST_RELEASE_CI"))
        for name, observation, code in cases:
            with self.subTest(name=name), self.assertRaisesRegex(Exception, code):
                self.audit_api("audit_release_identity")(observation)

    def test_security_frozen_input_rejects_mutable_and_noncommit_objects(self) -> None:
        require = self.release_api("require_frozen_commit")
        self.policy_failure("E_V240_FROZEN_COMMIT", lambda: require("HEAD"))
        self.policy_failure(
            "E_V240_FROZEN_OBJECT_TYPE",
            lambda: require(CANDIDATE_COMMIT, object_type="tree"),
        )

    def test_security_tar_rejects_traversal_links_pax_and_duplicates_before_write(self) -> None:
        extract = self.release_api("safe_extract_release_tar")
        cases = (
            (
                "traversal",
                [{"name": f"goal-teams-{VERSION}/../escape.txt"}],
                "E_V240_TAR_UNSAFE_PATH",
            ),
            (
                "symlink",
                [
                    {
                        "name": f"goal-teams-{VERSION}/link",
                        "type": tarfile.SYMTYPE,
                        "linkname": "../escape",
                    }
                ],
                "E_V240_TAR_LINK",
            ),
            (
                "hardlink",
                [
                    {
                        "name": f"goal-teams-{VERSION}/hard",
                        "type": tarfile.LNKTYPE,
                        "linkname": f"goal-teams-{VERSION}/VERSION",
                    }
                ],
                "E_V240_TAR_LINK",
            ),
            (
                "pax_path_override",
                [
                    {
                        "name": f"goal-teams-{VERSION}/safe.txt",
                        "pax_headers": {"path": "../escape.txt"},
                    }
                ],
                "E_V240_TAR_PAX_OVERRIDE",
            ),
            (
                "duplicate",
                [
                    {"name": f"goal-teams-{VERSION}/VERSION", "data": b"one\n"},
                    {"name": f"goal-teams-{VERSION}/VERSION", "data": b"two\n"},
                ],
                "E_V240_TAR_DUPLICATE",
            ),
        )
        for name, members, code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / "candidate.tar"
                target = root / "allowed" / "target"
                allowed = root / "allowed"
                allowed.mkdir()
                target.mkdir()
                _write_tar(archive, members)
                self.policy_failure(
                    code,
                    lambda archive=archive, target=target, allowed=allowed: extract(
                        archive, target, allowed
                    ),
                )
                self.assertEqual(list(target.rglob("*")), [])
                self.assertFalse((root / "escape.txt").exists())

    def test_security_tar_limits_are_fixed_and_zero_mutation(self) -> None:
        validate = self.release_api("validate_tar_limits")
        base = {
            "member_count": 1,
            "max_path_bytes": 32,
            "max_single_file_bytes": 1024,
            "total_uncompressed_bytes": 1024,
            "compressed_bytes": 512,
        }
        cases = (
            ("members", "member_count", 2049, "E_V240_TAR_LIMIT_MEMBERS"),
            ("path", "max_path_bytes", 241, "E_V240_TAR_LIMIT_PATH"),
            (
                "single_file",
                "max_single_file_bytes",
                16 * 1024 * 1024 + 1,
                "E_V240_TAR_LIMIT_SINGLE_FILE",
            ),
            (
                "total",
                "total_uncompressed_bytes",
                128 * 1024 * 1024 + 1,
                "E_V240_TAR_LIMIT_TOTAL",
            ),
        )
        for name, field, value, code in cases:
            summary = dict(base)
            summary[field] = value
            with self.subTest(name=name):
                self.policy_failure(code, lambda summary=summary: validate(summary))
        ratio = dict(base)
        ratio["total_uncompressed_bytes"] = 10100
        ratio["compressed_bytes"] = 100
        self.policy_failure("E_V240_TAR_LIMIT_RATIO", lambda: validate(ratio))

    def test_security_remote_promotion_lock_mismatch_is_fail_closed(self) -> None:
        validate = self.release_api("validate_remote_promotion_lock")
        expected = {
            "active": True,
            "target_ref": "refs/heads/main",
            "candidate_commit": CANDIDATE_COMMIT,
            "bypass_actor_id": 240,
            "ruleset_sha256": "7" * 64,
        }
        for field, value in (
            ("active", False),
            ("target_ref", "refs/heads/other"),
            ("candidate_commit", BASE_COMMIT),
            ("bypass_actor_id", 241),
            ("ruleset_sha256", "8" * 64),
        ):
            observed = dict(expected)
            observed[field] = value
            with self.subTest(field=field):
                self.policy_failure(
                    "E_V240_PROMOTION_LOCK",
                    lambda observed=observed: validate(expected, observed),
                )

    def test_security_remote_lease_drift_has_zero_side_effects(self) -> None:
        validate = self.release_api("validate_remote_lease")
        self.policy_failure(
            "E_V240_REMOTE_MAIN_LEASE",
            lambda: validate(BASE_COMMIT, "9" * 40, CANDIDATE_COMMIT),
        )

    def test_security_remote_tag_and_release_classify_absent_exact_conflict(self) -> None:
        classify = self.release_api("classify_remote_resource")
        expected = {
            "source_commit": CANDIDATE_COMMIT,
            "resource_id": 240,
            "digest": "a" * 64,
        }
        for resource_kind in ("tag", "release"):
            with self.subTest(resource_kind=resource_kind, classification="absent"):
                receipt = classify(resource_kind, expected, None, prior_intent=True)
                self.assertEqual(receipt["classification"], "absent")
                self.assertEqual(receipt["permitted_action"], "create")
                self.assertEqual(receipt["mutation_count"], 0)
                self.assertEqual(receipt["external_side_effect_count"], 0)
            with self.subTest(resource_kind=resource_kind, classification="exact"):
                receipt = classify(
                    resource_kind, expected, dict(expected), prior_intent=True
                )
                self.assertEqual(receipt["classification"], "exact")
                self.assertEqual(receipt["permitted_action"], "adopt")
                self.assertEqual(receipt["external_side_effect_count"], 0)
            conflict = dict(expected)
            conflict["digest"] = "b" * 64
            with self.subTest(resource_kind=resource_kind, classification="conflict"):
                self.policy_failure(
                    "E_V240_REMOTE_RESOURCE_CONFLICT",
                    lambda resource_kind=resource_kind, conflict=conflict: classify(
                        resource_kind, expected, conflict, prior_intent=True
                    ),
                )

    def test_security_published_exact_marker_crash_adopts_without_replay(self) -> None:
        recover = self.release_api("recover_operation")
        intent = {
            "operation_id": "CP17.release_publish",
            "idempotency_key": "c" * 64,
            "release_id": 240,
            "source_commit": CANDIDATE_COMMIT,
            "asset_digests": sorted(value["sha256"] for value in _required_assets().values()),
        }
        observed = {
            "classification": "exact",
            "release_state": "published",
            "release_id": 240,
            "source_commit": CANDIDATE_COMMIT,
            "asset_digests": intent["asset_digests"],
        }
        receipt = recover(intent, observed, marker_present=False)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["recovery_action"], "adopt_marker")
        self.assertFalse(receipt["replayed_side_effect"])
        self.assertEqual(receipt["external_side_effect_count"], 0)
        self.policy_failure(
            "E_V240_PUBLISHED_RECOVERY_INTENT",
            lambda: recover(None, observed, marker_present=False),
        )

    def test_critical_checkpoint_crash_matrix_never_replays_exact_side_effects(self) -> None:
        recover = self.release_api("recover_operation")
        critical_operations = (
            "CP03.immutable_release_enable",
            "CP12.candidate_push",
            "CP14.main_promotion_lock",
            "CP14.tag_ruleset",
            "CP15.tag_push",
            "CP16.draft_create",
            "CP16.asset_upload_tar",
            "CP16.asset_upload_sums",
            "CP16.asset_upload_release",
            "CP16.asset_upload_files",
            "CP17.main_promote",
            "CP17.release_publish",
            "CP17.post_release_ci",
            "CP18.promotion_lock_finalize",
        )
        for operation_id in critical_operations:
            intent: dict[str, Any] = {
                "operation_id": operation_id,
                "idempotency_key": hashlib.sha256(operation_id.encode()).hexdigest(),
            }
            exact: dict[str, Any] = {"classification": "exact"}
            if operation_id == "CP17.release_publish":
                intent.update(
                    {
                        "release_id": 240,
                        "source_commit": CANDIDATE_COMMIT,
                        "asset_digests": ["a" * 64, "b" * 64],
                    }
                )
                exact.update(
                    {
                        "release_state": "published",
                        "release_id": 240,
                        "source_commit": CANDIDATE_COMMIT,
                        "asset_digests": intent["asset_digests"],
                    }
                )
            with self.subTest(operation_id=operation_id, crash_point="after_effect"):
                adopted = recover(intent, exact, marker_present=False)
                self.assertEqual(adopted["recovery_action"], "adopt_marker")
                self.assertFalse(adopted["replayed_side_effect"])
                self.assertEqual(adopted["external_side_effect_count"], 0)
            with self.subTest(operation_id=operation_id, crash_point="before_effect"):
                pending = recover(
                    intent,
                    {"classification": "absent"},
                    marker_present=False,
                )
                self.assertEqual(
                    pending["recovery_action"], "execute_persisted_intent"
                )
                self.assertFalse(pending["replayed_side_effect"])
            with self.subTest(operation_id=operation_id, crash_point="after_marker"):
                marked = recover(None, {}, marker_present=True)
                self.assertEqual(marked["recovery_action"], "already_marked")
                self.assertFalse(marked["replayed_side_effect"])

    def test_security_ci_receipt_binds_sha_workflow_and_required_jobs(self) -> None:
        validate = self.release_api("validate_ci_receipt")
        approval = {
            "release_actor_id": 240,
            "head_sha": CANDIDATE_COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_blob_sha": "d" * 40,
            "workflow_id": 240,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }
        receipt = {
            **approval,
            "actor_id": 240,
            "triggering_actor_id": 240,
            "workflow_raw_path": ".github/workflows/release-gate.yml",
            "workflow_raw_ref": None,
            "run_id": 24001,
            "run_attempt": 1,
            "jobs": [
                {"name": name, "head_sha": CANDIDATE_COMMIT, "conclusion": "success"}
                for name in approval["required_jobs"]
            ],
        }
        self.assertTrue(validate(receipt, approval)["passed"])
        wrong_sha = copy.deepcopy(receipt)
        wrong_sha["head_sha"] = BASE_COMMIT
        wrong_workflow = copy.deepcopy(receipt)
        wrong_workflow["workflow_blob_sha"] = "e" * 40
        wrong_job = copy.deepcopy(receipt)
        wrong_job["jobs"][2]["name"] = "unapproved-job"
        wrong_actor = copy.deepcopy(receipt)
        wrong_actor["actor_id"] = 241
        wrong_triggering_actor = copy.deepcopy(receipt)
        wrong_triggering_actor["run_attempt"] = 2
        wrong_triggering_actor["triggering_actor_id"] = 241
        for name, invalid in (
            ("sha", wrong_sha),
            ("workflow", wrong_workflow),
            ("job", wrong_job),
            ("actor", wrong_actor),
            ("rerun_triggering_actor", wrong_triggering_actor),
        ):
            with self.subTest(name=name):
                self.policy_failure(
                    "E_V240_CI_TRUST_BINDING",
                    lambda invalid=invalid: validate(invalid, approval),
                )

    def test_security_forged_local_state_cannot_become_authority(self) -> None:
        validate = self.release_api("validate_promotion_state")
        expected = _promotion_expectation()
        good = _promotion_state("CP09")
        self.assertTrue(validate(good, expected)["passed"])
        forged = copy.deepcopy(good)
        forged["checkpoints"]["CP09"]["candidate_commit"] = BASE_COMMIT
        forged["promote_reported_passed"] = True
        self.policy_failure(
            "E_V240_STATE_FORGED", lambda: validate(forged, expected)
        )

    def test_promotion_state_fixture_matches_exact_plan_continuity_and_phase(self) -> None:
        state = _promotion_state("CP18")
        expected_checkpoints = [f"CP{index:02d}" for index in range(19)]
        self.assertEqual(list(state["checkpoints"]), expected_checkpoints)
        self.assertEqual(state["phase"], "CLOSED")
        for checkpoint_id in expected_checkpoints:
            operations = state["checkpoints"][checkpoint_id]["operations"]
            observed_plan = [
                (operation["operation_id"], operation["intent"]["action"])
                for operation in operations
            ]
            self.assertEqual(
                observed_plan,
                list(PROMOTION_OPERATION_PLAN[checkpoint_id]),
                checkpoint_id,
            )
            self.assertEqual(
                [operation["sequence"] for operation in operations],
                list(range(1, len(operations) + 1)),
            )
            self.assertTrue(
                all(
                    operation["operation_id"]
                    == operation["intent"]["operation_id"]
                    for operation in operations
                )
            )
        receipt = self.release_api("validate_promotion_state")(
            state, _promotion_expectation()
        )
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["mutation_count"], 0)
        self.assertEqual(receipt["external_side_effect_count"], 0)

    def test_closed_state_semantics_are_exact_and_non_closed_injection_fails(
        self,
    ) -> None:
        validate = self.release_api("validate_promotion_state")
        closed = _promotion_state("CP18")
        self.assertTrue(validate(closed, _promotion_expectation())["passed"])
        for field, forged_value in (
            ("closure_scope", "goal_achieved"),
            ("goal_achieved", True),
            ("external_host_acceptance_required", False),
            ("completion_authority", "candidate_runtime"),
        ):
            with self.subTest(field=field):
                forged = copy.deepcopy(closed)
                forged[field] = forged_value
                self.policy_failure(
                    "E_V240_STATE_DERIVATION",
                    lambda forged=forged: validate(
                        forged, _promotion_expectation()
                    ),
                )
        missing = copy.deepcopy(closed)
        missing.pop("goal_achieved")
        self.policy_failure(
            "E_V240_STATE_DERIVATION",
            lambda: validate(missing, _promotion_expectation()),
        )
        non_closed = _promotion_state("CP17")
        non_closed.update(copy.deepcopy(release.CLOSED_COMPLETION_SEMANTICS))
        self.policy_failure(
            "E_V240_STATE_DERIVATION",
            lambda: validate(non_closed, _promotion_expectation()),
        )

    def test_closed_status_echoes_external_host_completion_semantics(self) -> None:
        state = _promotion_state("CP18")
        state_path = Path("/tmp/goal-teams-v240-closed-state.json")
        with (
            mock.patch.object(
                release,
                "_load_state_cas",
                return_value=(state_path, state, "a" * 64),
            ),
            mock.patch.object(
                release,
                "plan_resume",
                return_value={
                    "next_checkpoint": None,
                    "actions": [],
                    "skip_side_effects": True,
                },
            ),
        ):
            receipt = release._status_from_config(
                {"state_path": str(state_path)}
            )
        self.assertEqual(
            {field: receipt[field] for field in release.CLOSED_COMPLETION_FIELDS},
            release.CLOSED_COMPLETION_SEMANTICS,
        )

    def test_closed_recover_is_read_only_and_echoes_completion_semantics(self) -> None:
        state = _promotion_state("CP18")
        state_path = Path("/tmp/goal-teams-v240-closed-recover.json")
        with (
            mock.patch.object(
                release,
                "_load_state_cas",
                return_value=(state_path, state, "a" * 64),
            ),
            mock.patch.object(
                release,
                "plan_resume",
                return_value={
                    "next_checkpoint": None,
                    "actions": [],
                    "skip_side_effects": True,
                },
            ),
            mock.patch.object(
                release, "execute_current_checkpoint"
            ) as execute_checkpoint,
        ):
            receipt = release._recover_from_config({"state_path": str(state_path)})
        execute_checkpoint.assert_not_called()
        self.assertEqual(receipt["command"], "recover")
        self.assertEqual(receipt["mutation_count"], 0)
        self.assertEqual(receipt["external_side_effect_count"], 0)
        self.assertEqual(
            {field: receipt[field] for field in release.CLOSED_COMPLETION_FIELDS},
            release.CLOSED_COMPLETION_SEMANTICS,
        )

    def test_caller_cannot_inject_closed_semantics_through_state_updates(
        self,
    ) -> None:
        state = _promotion_state("CP17")
        state_path = Path("/tmp/goal-teams-v240-cp18-pending.json")
        with (
            mock.patch.object(
                release,
                "_load_state_cas",
                return_value=(state_path, state, "a" * 64),
            ),
            mock.patch.object(release, "_verify_frozen_git_identity"),
        ):
            self.policy_failure(
                "E_V240_STATE_UPDATE",
                lambda: release.execute_current_checkpoint(
                    state_path,
                    {
                        "expected_state_sha256": "a" * 64,
                        "state_updates": copy.deepcopy(
                            release.CLOSED_COMPLETION_SEMANTICS
                        ),
                    },
                ),
            )

    def test_security_promotion_state_rejects_plan_gap_and_phase_drift(self) -> None:
        validate = self.release_api("validate_promotion_state")
        expected = _promotion_expectation()

        wrong_id = _promotion_state("CP09")
        wrong_id["checkpoints"]["CP09"]["operations"][0][
            "operation_id"
        ] = "CP09.build_unapproved"
        wrong_id["checkpoints"]["CP09"]["operations"][0]["intent"][
            "operation_id"
        ] = "CP09.build_unapproved"
        self.policy_failure(
            "E_V240_STATE_OPERATION_PLAN", lambda: validate(wrong_id, expected)
        )

        wrong_order = _promotion_state("CP09")
        operations = wrong_order["checkpoints"]["CP09"]["operations"]
        operations.reverse()
        for sequence, operation in enumerate(operations, start=1):
            operation["sequence"] = sequence
        self.policy_failure(
            "E_V240_STATE_OPERATION_PLAN", lambda: validate(wrong_order, expected)
        )

        checkpoint_gap = _promotion_state("CP09")
        del checkpoint_gap["checkpoints"]["CP08"]
        self.policy_failure(
            "E_V240_STATE_CHECKPOINT_GAP",
            lambda: validate(checkpoint_gap, expected),
        )

        wrong_phase = _promotion_state("CP09")
        wrong_phase["phase"] = "DRAFT_VERIFIED"
        self.policy_failure(
            "E_V240_STATE_PHASE", lambda: validate(wrong_phase, expected)
        )

    def test_security_cp17_order_is_locked_before_publish_not_main_last(self) -> None:
        validate = self.release_api("validate_promotion_state")
        expected = _promotion_expectation()
        state = _promotion_state("CP17")
        actions = [
            operation["intent"]["action"]
            for operation in state["checkpoints"]["CP17"]["operations"]
        ]
        self.assertEqual(
            actions,
            [
                "main_promote",
                "release_publish",
                "published_asset_download",
                "actual_install",
                "post_release_ci",
                "independent_audit",
            ],
        )
        self.assertIsNotNone(state["remote_lock"])
        self.assertEqual(state["remote_lock"]["candidate_commit"], CANDIDATE_COMMIT)
        self.assertTrue(validate(state, expected)["passed"])

        # CP14's remote lock and CP17's exact main CAS make main-before-publish
        # safe.  The V2.40 contract deliberately does not use main-last.
        reversed_publish_order = copy.deepcopy(state)
        operations = reversed_publish_order["checkpoints"]["CP17"]["operations"]
        operations[0], operations[1] = operations[1], operations[0]
        for sequence, operation in enumerate(operations, start=1):
            operation["sequence"] = sequence
        self.policy_failure(
            "E_V240_STATE_OPERATION_PLAN",
            lambda: validate(reversed_publish_order, expected),
        )

    def test_security_github_live_authority_is_exactly_bound(self) -> None:
        validate = self.release_api("validate_github_live_authority")
        binding, observed = _github_live_authority()
        receipt = validate(observed, binding)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["actor_login"], binding["actor_login"])
        self.assertEqual(receipt["actor_id"], binding["actor_id"])
        self.assertEqual(
            receipt["repository_full_name"], binding["repository_full_name"]
        )
        self.assertEqual(receipt["repository_id"], binding["repository_id"])
        self.assertEqual(receipt["permission"], "admin")
        self.assertEqual(
            receipt["authorized_external_actions"],
            list(GITHUB_AUTHORIZED_ACTIONS),
        )
        self.assertEqual(receipt["receipt_sha256"], binding["receipt_sha256"])

        cases: list[tuple[str, dict[str, Any], str]] = []
        for field, value in (("actor_login", "other-owner"), ("actor_id", 241)):
            invalid = copy.deepcopy(observed)
            invalid[field] = value
            cases.append((f"actor_{field}", invalid, "E_V240_GITHUB_ACTOR_BINDING"))
        for field, value in (
            ("repository_full_name", "vibe-coding-era/other"),
            ("repository_id", 1249985346),
        ):
            invalid = copy.deepcopy(observed)
            invalid[field] = value
            cases.append(
                (f"repository_{field}", invalid, "E_V240_GITHUB_REPOSITORY_BINDING")
            )
        invalid = copy.deepcopy(observed)
        invalid["permission"] = "maintain"
        cases.append(("permission", invalid, "E_V240_GITHUB_ADMIN_REQUIRED"))
        invalid = copy.deepcopy(observed)
        invalid["authorized_external_actions"].remove("manage_promotion_ruleset")
        cases.append(("action", invalid, "E_V240_GITHUB_ACTION_UNAUTHORIZED"))
        invalid = copy.deepcopy(observed)
        invalid["immutable_endpoint_capability"]["enable"] = False
        cases.append(
            ("immutable", invalid, "E_V240_GITHUB_IMMUTABLE_CAPABILITY")
        )
        invalid = copy.deepcopy(observed)
        invalid["ruleset_capability"]["write"] = False
        cases.append(("ruleset", invalid, "E_V240_GITHUB_RULESET_CAPABILITY"))
        invalid = copy.deepcopy(observed)
        invalid["actor_binding_sha256"] = "0" * 64
        cases.append(("binding", invalid, "E_V240_GITHUB_AUTHORITY_BINDING"))
        for name, invalid, code in cases:
            with self.subTest(name=name):
                self.policy_failure(code, lambda invalid=invalid: validate(invalid, binding))

    def test_private_ignored_log_redaction_binds_input_policy_and_output(self) -> None:
        redact = self.release_api("redact_private_ignored_log")
        authorization_prefix = "Author" + "ization: Be" + "arer "
        synthetic = "dummy-fixture-private-log"
        private_record = {
            "surface_kind": "private_log",
            "ignored": True,
            "path": "docs/private/release-run.json",
            "fields": {
                "authorization": authorization_prefix + synthetic,
                "run_id": "RUN-V240-PRIVATE",
                "status": "failed",
            },
        }
        private_input_sha256 = _canonical_json_sha256(private_record)
        sanitizer_sha256 = "5" * 64
        receipt = redact(
            private_record,
            expected_input_sha256=private_input_sha256,
            sanitizer_sha256=sanitizer_sha256,
            redacted_fields=["authorization"],
        )
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["private_input_sha256"], private_input_sha256)
        self.assertEqual(receipt["sanitizer_sha256"], sanitizer_sha256)
        self.assertEqual(receipt["redacted_fields"], ["authorization"])
        self.assertEqual(receipt["public_fields"]["authorization"], "[REDACTED]")
        self.assertEqual(receipt["public_fields"]["run_id"], "RUN-V240-PRIVATE")
        self.assertEqual(
            receipt["public_output_sha256"],
            _canonical_json_sha256(receipt["public_fields"]),
        )
        self.assertNotIn(synthetic, json.dumps(receipt["public_fields"]))
        self.assertEqual(receipt["mutation_count"], 0)
        self.assertEqual(receipt["external_side_effect_count"], 0)

    def test_redaction_rejects_nonignored_public_and_digest_drift(self) -> None:
        redact = self.release_api("redact_private_ignored_log")
        private_record = {
            "surface_kind": "private_log",
            "ignored": True,
            "path": "docs/private/release-run.json",
            "fields": {"authorization": "dummy-fixture-private"},
        }
        expected_input_sha256 = _canonical_json_sha256(private_record)
        kwargs = {
            "expected_input_sha256": expected_input_sha256,
            "sanitizer_sha256": "5" * 64,
            "redacted_fields": ["authorization"],
        }
        nonignored = copy.deepcopy(private_record)
        nonignored["ignored"] = False
        nonignored_kwargs = {
            **kwargs,
            "expected_input_sha256": _canonical_json_sha256(nonignored),
        }
        self.policy_failure(
            "E_V240_REDACTION_SCOPE",
            lambda: redact(nonignored, **nonignored_kwargs),
        )
        for surface_kind in (
            "release_asset",
            "tag_message",
            "tracked_release_note",
            "tracked_readme",
        ):
            public_record = copy.deepcopy(private_record)
            public_record["surface_kind"] = surface_kind
            public_record["ignored"] = False
            public_record["path"] = f"public/{surface_kind}"
            public_kwargs = {
                **kwargs,
                "expected_input_sha256": _canonical_json_sha256(public_record),
            }
            with self.subTest(surface_kind=surface_kind):
                self.policy_failure(
                    "E_V240_PUBLIC_REDACTION_FORBIDDEN",
                    lambda public_record=public_record, public_kwargs=public_kwargs: redact(
                        public_record, **public_kwargs
                    ),
                )
        self.policy_failure(
            "E_V240_REDACTION_DIGEST",
            lambda: redact(
                private_record,
                **{**kwargs, "expected_input_sha256": "0" * 64},
            ),
        )

    def test_security_symlink_ancestor_is_rejected_before_write(self) -> None:
        validate = self.release_api("validate_safe_ancestors")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            real = allowed / "real"
            allowed.mkdir()
            real.mkdir()
            linked = allowed / "linked"
            linked.symlink_to(real, target_is_directory=True)
            target = linked / "child"
            self.policy_failure(
                "E_V240_SYMLINK_ANCESTOR",
                lambda: validate(target, allowed),
            )
            self.assertFalse(target.exists())
            self.assertEqual(list(real.iterdir()), [])

    def test_security_public_secret_and_absolute_home_path_are_rejected(self) -> None:
        scan = self.release_api("scan_public_payload")
        authorization_prefix = "Author" + "ization: Be" + "arer "
        synthetic = "-".join(("sk", "proj", "fixture", "not-a-secret"))
        self.policy_failure(
            "E_V240_PUBLIC_SECRET",
            lambda: scan({"README.md": authorization_prefix + synthetic}),
        )
        absolute_home = "/" + "Users" + "/private/release-evidence.json"
        self.policy_failure(
            "E_V240_PUBLIC_ABSOLUTE_PATH",
            lambda: scan({"_release.json": absolute_home}),
        )

    def test_security_bundle_tamper_and_outside_target_leave_zero_files(self) -> None:
        validate = self.release_api("validate_release_bundle")
        expected = _required_assets()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            allowed.mkdir()
            target = allowed / "target"
            tampered = copy.deepcopy(expected)
            tampered["_files.sha256"]["sha256"] = "f" * 64
            self.policy_failure(
                "E_V240_BUNDLE_TAMPER",
                lambda: validate(expected, tampered, target, allowed),
            )
            self.assertFalse(target.exists())
            outside = root / "outside" / "target"
            self.policy_failure(
                "E_V240_TARGET_OUTSIDE",
                lambda: validate(expected, copy.deepcopy(expected), outside, allowed),
            )
            self.assertFalse(outside.exists())

    def test_security_release_and_tag_immutability_are_independent_gates(self) -> None:
        validate = self.release_api("validate_remote_immutability")
        good = {
            "immutable_release_enabled": True,
            "release_state": "published",
            "release_immutable": True,
            "tag_ruleset_active": True,
            "tag_update_allowed": False,
            "tag_deletion_allowed": False,
        }
        self.assertTrue(validate(good)["passed"])
        mutable_release = dict(good)
        mutable_release["release_immutable"] = False
        self.policy_failure(
            "E_V240_RELEASE_IMMUTABILITY",
            lambda: validate(mutable_release),
        )
        mutable_tag = dict(good)
        mutable_tag["tag_update_allowed"] = True
        self.policy_failure(
            "E_V240_TAG_RULESET",
            lambda: validate(mutable_tag),
        )

    def test_security_promotion_receipt_chain_rejects_nested_detail_tamper(self) -> None:
        validate = self.release_api("validate_promotion_state")
        state = _promotion_state("CP13")
        self.assertTrue(validate(state, _promotion_expectation())["passed"])
        forged = copy.deepcopy(state)
        forged["checkpoints"]["CP13"]["operations"][0]["readback"][
            "details"
        ]["conclusion"] = "forged-success"
        self.policy_failure(
            "E_V240_STATE_RECEIPT_CHAIN",
            lambda: validate(forged, _promotion_expectation()),
        )


if __name__ == "__main__":
    unittest.main()
