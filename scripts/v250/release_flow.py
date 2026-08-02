#!/usr/bin/env python3
"""Pure V2.50 release routing and receipt-chain helpers.

The helpers in this module do not launch tests, build assets, install files, or
perform a network write.  They validate and bind receipts produced by the
dedicated V2.50 runners.  A consistent receipt chain is evidence correlation;
it is not a cryptographic host attestation or external-independence proof.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.v250.runtime_transition import (
    validate_transition as validate_runtime_transition,
)

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROJECT_SIZES = {"discussion", "small", "medium", "large"}
PUBLIC_ASSET_NAMES = {
    "goal-teams-V2.50.tar.gz",
    "SHA256SUMS",
    "_release.json",
    "_files.sha256",
}
REQUIRED_S4_ACTION_CLASSES = {
    "ssh_fetch_pull_ls_remote_branch_push_tag_push",
    "github_pr_actions_merge_release_api",
    "release_asset_build_and_readback",
    "formal_install_update_rollback_uninstall",
}
REQUIRED_AUTH_VALIDITY_CONDITIONS = {
    "repository_version_locked_scope_target_branch_tag_and_action_classes_unchanged",
    "run_state_running_replan_or_same_checkpoint_resumable_blocked",
    "not_revoked_by_user",
}
PROJECT_START_AUTHORIZATION_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "authorization_id",
        "authorization_state",
        "authorization_lineage_preserved",
        "issued_at",
        "expires_at",
        "repository",
        "version",
        "candidate_branch",
        "tag",
        "locked_scope",
        "action_allowlist",
        "validity_conditions",
        "intent",
        "intent_sha256",
    }
)
PROJECT_START_AUTHORIZATION_ALLOWED_KEYS = (
    PROJECT_START_AUTHORIZATION_REQUIRED_KEYS
    | {
        "authorization_source",
        "approver_identity",
        "conversational_reconfirmation_required",
        "credential_policy",
        "idempotency_key",
        "later_exact_identity_is_evidence_not_authorization",
        "permitted_other_external_writes",
        "revocation_conditions",
        "revoked",
        "revoked_at",
    }
)
PROJECT_START_AUTHORIZATION_REPOSITORY_REQUIRED_KEYS = frozenset(
    {
        "id",
        "name_with_owner",
        "origin_fetch",
        "origin_push",
        "default_branch",
    }
)
PROJECT_START_AUTHORIZATION_REPOSITORY_KEYS = (
    PROJECT_START_AUTHORIZATION_REPOSITORY_REQUIRED_KEYS
    | {
        "base_sha",
        "base_tree",
    }
)
PROJECT_START_AUTHORIZATION_INTENT_KEYS = frozenset(
    {
        "repository_id",
        "repository",
        "version",
        "candidate_branch",
        "tag",
        "locked_scope",
        "action_allowlist",
        "validity_conditions",
    }
)

V250_SECURITY_CONTRACT_PATH = (
    "references/current/generations/V2.50/contracts/"
    "release-security-review-manifest.json"
)
V250_SECURITY_REQUIRED_TARGET_PATHS = frozenset(
    {
        ".github/workflows/check.yml",
        ".github/workflows/release-gate.yml",
        "references/current/generations/V2.50/contracts/public-asset-map.json",
        "references/current/generations/V2.50/contracts/release-command-manifest.json",
        "references/current/generations/V2.50/contracts/release-route-manifest.json",
        V250_SECURITY_CONTRACT_PATH,
        "schemas/v2.50/project-route.schema.json",
        "schemas/v2.50/release-control.schema.json",
        "scripts/checks/check-package-manifest.py",
        "scripts/checks/check-v250.py",
        "scripts/checks/check-workspace-boundaries.py",
        "scripts/checks/run-v250-release-security-review.py",
        "scripts/install/install-local.sh",
        "scripts/release/build-release.py",
        "scripts/release/release_config.py",
        "scripts/release/skill_release.py",
        "scripts/release/validate-release.py",
        "scripts/v250/github_ssh.py",
        "scripts/v250/refresh_generation_manifests.py",
        "scripts/v250/release_flow.py",
        "scripts/v250/repository_boundary.py",
        "scripts/v250/runtime_host_adapter.py",
        "scripts/v250/runtime_transition.py",
        "scripts/v250/s4_executor.py",
    }
)


def canonical_sha256(value: Any) -> str:
    """Return the canonical JSON SHA-256 used by V2.50 receipt bindings."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _receipt_sha256(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    payload.pop("receipt_sha256", None)
    payload.pop("release_control_sha256", None)
    return canonical_sha256(payload)


def _seal_receipt(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result["receipt_sha256"] = _receipt_sha256(result)
    return result


def _valid_receipt_digest(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("receipt_sha256"), str)
        and SHA256_RE.fullmatch(value["receipt_sha256"]) is not None
        and value["receipt_sha256"] == _receipt_sha256(value)
    )


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _not_required(reason: str) -> dict[str, Any]:
    return {
        "gate_requirement": "not_required",
        "not_required_reason": reason,
        "check_state": "not_required",
        "run_outcome": "not_run",
    }


def _release_ready(route: dict[str, Any]) -> bool:
    return (
        route.get("workflow_phase") == "release"
        and route.get("release_intent") is True
        and route.get("implementation_scope_complete") is True
        and route.get("stage") == "released"
    )


def derive_release_plan(route: dict[str, Any]) -> dict[str, Any]:
    """Derive V2.50 S0-S4 without executing child processes."""

    if not isinstance(route, dict):
        raise TypeError("route must be an object")
    size = route.get("project_size")
    if size not in PROJECT_SIZES:
        raise ValueError("project_size is invalid")

    ready = _release_ready(route)
    gates: dict[str, dict[str, Any]] = {}
    if not ready:
        reason = "release_readiness_conditions_not_met"
        for gate_id in ("s0", "s1", "s2", "s3", "s4"):
            gates[gate_id] = _not_required(reason)
        gates["s3"].update({"s3_process_invocation_count": 0, "child_argv": []})
        return {
            "generation_id": "V2.50",
            "workflow_phase": route.get("workflow_phase"),
            "release_ready": False,
            "s1_gates": [],
            "invocation_limits": {
                "full_regression": 0,
                "release_security_review": 0,
                "s2_build": 0,
                "s3": 0,
            },
            "gates": gates,
        }

    s1_current = route.get("s1_current") is True
    gates["s0"] = {"gate_requirement": "required", "check_state": "not_started"}
    gates["s1"] = {
        "gate_requirement": "required",
        "required_checks": ["full_regression", "release_security_review"],
        "check_state": "passed" if s1_current else "not_started",
    }
    gates["s2"] = {
        "gate_requirement": "required",
        "check_state": "not_started",
        "build_invocation_count_for_asset_set": 1,
        "second_build_comparison_attempted": False,
        "reproducibility": "not_verified_by_v250_policy",
        "s2_security_checks": "not_run_by_v250_policy",
    }

    if size != "large" or route.get("release_intent") is not True:
        gates["s3"] = _not_required("large_release_only")
        gates["s3"].update({"s3_process_invocation_count": 0, "child_argv": []})
        s3_limit = 0
    elif not s1_current:
        gates["s3"] = {
            "gate_requirement": "blocked",
            "blocked_code": "E_V250_S3_S1_REQUIRED",
            "check_state": "blocked",
            "run_outcome": "blocked",
            "s3_process_invocation_count": 0,
            "child_argv": [],
        }
        s3_limit = 0
    else:
        gates["s3"] = {
            "gate_requirement": "required",
            "check_state": "not_started",
            "s3_process_invocation_count": 1,
            "child_argv": ["scripts/install/install-local.sh"],
        }
        s3_limit = 1

    gates["s4"] = {
        "gate_requirement": "required",
        "check_state": "not_started",
        "authorization_source": "project_start_authorization_receipt",
        "additional_user_confirmation_required": False,
    }
    return {
        "generation_id": "V2.50",
        "workflow_phase": "release",
        "release_ready": True,
        "s1_gates": ["full_regression", "release_security_review"],
        "invocation_limits": {
            "full_regression": 1,
            "release_security_review": 1,
            "s2_build": 1,
            "s3": s3_limit,
        },
        "gates": gates,
    }


def build_s2_receipt(
    *,
    source_commit: str,
    source_tree: str,
    asset_set_id: str,
    assets: Iterable[dict[str, Any]],
    build_run_id: str = "V250-S2-SINGLE-BUILD",
) -> dict[str, Any]:
    """Build a data-only receipt for the one already-completed S2 build."""

    asset_rows = [dict(asset) for asset in assets]
    if COMMIT_RE.fullmatch(source_commit) is None:
        raise ValueError("source_commit must be a 40-character lowercase SHA")
    if COMMIT_RE.fullmatch(source_tree) is None:
        raise ValueError("source_tree must be a 40-character lowercase SHA")
    if not _nonempty(asset_set_id) or not _nonempty(build_run_id):
        raise ValueError("asset_set_id and build_run_id are required")
    if {asset.get("name") for asset in asset_rows} != PUBLIC_ASSET_NAMES:
        raise ValueError("the exact V2.50 four-asset set is required")
    if len(asset_rows) != len(PUBLIC_ASSET_NAMES):
        raise ValueError("duplicate public asset identity")
    for asset in asset_rows:
        if (
            set(asset) != {"name", "size", "sha256"}
            or not _nonempty(asset["name"])
            or not isinstance(asset["size"], int)
            or isinstance(asset["size"], bool)
            or asset["size"] < 0
            or not isinstance(asset["sha256"], str)
            or SHA256_RE.fullmatch(asset["sha256"]) is None
        ):
            raise ValueError("asset identity is invalid")
    asset_rows.sort(key=lambda item: item["name"])
    asset_set_digest = canonical_sha256(asset_rows)
    return _seal_receipt(
        {
            "schema_version": "goal-teams-v2.50-s2-receipt-v1",
            "gate_id": "s2_single_build",
            "stage": "released",
            "source_commit": source_commit,
            "source_tree": source_tree,
            "asset_set_id": asset_set_id,
            "asset_set_digest": asset_set_digest,
            "assets": asset_rows,
            "build_run_id": build_run_id,
            "build_entrypoint": "scripts/release/build-release.py",
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "build_invocation_count_for_asset_set": 1,
            "second_build_comparison_attempted": False,
            "same_built_asset_integrity_validation_required": True,
            "reproducibility": "not_verified_by_v250_policy",
            "s2_security_checks": "not_run_by_v250_policy",
            "legacy_double_build_gate_loaded": False,
            "legacy_s2_security_gate_loaded": False,
        }
    )


def validate_s2_receipt(
    receipt: object,
    *,
    source_commit: str,
    source_tree: str,
    asset_set_id: str | None = None,
    asset_set_digest: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    value = receipt if isinstance(receipt, dict) else {}
    if not isinstance(receipt, dict):
        errors.append("E_V250_S2_RECEIPT_MISSING")
    if not _valid_receipt_digest(value):
        errors.append("E_V250_S2_RECEIPT_DIGEST")
    if (
        value.get("gate_id") != "s2_single_build"
        or value.get("source_commit") != source_commit
        or value.get("source_tree") != source_tree
        or (asset_set_id is not None and value.get("asset_set_id") != asset_set_id)
        or (
            asset_set_digest is not None
            and value.get("asset_set_digest") != asset_set_digest
        )
    ):
        errors.append("E_V250_S2_IDENTITY_DRIFT")
    assets = value.get("assets")
    if (
        not isinstance(assets, list)
        or len(assets) != 4
        or {item.get("name") for item in assets if isinstance(item, dict)}
        != PUBLIC_ASSET_NAMES
        or value.get("asset_set_digest") != canonical_sha256(assets)
    ):
        errors.append("E_V250_S2_ASSET_SET_DRIFT")
    if (
        value.get("check_state") != "passed"
        or value.get("run_outcome") != "passed"
        or value.get("evidence_state") != "current"
        or value.get("build_invocation_count_for_asset_set") != 1
    ):
        errors.append("E_V250_S2_NOT_CURRENT")
    if (
        value.get("second_build_comparison_attempted") is not False
        or value.get("reproducibility") != "not_verified_by_v250_policy"
        or value.get("s2_security_checks") != "not_run_by_v250_policy"
        or value.get("legacy_double_build_gate_loaded") is not False
        or value.get("legacy_s2_security_gate_loaded") is not False
    ):
        errors.append("E_V250_S2_POLICY_VIOLATION")
    errors = list(dict.fromkeys(errors))
    return {"ok": not errors, "passed": not errors, "errors": errors}


def _validate_full_regression_receipt(
    receipt: object, source_commit: str, source_tree: str
) -> list[str]:
    errors: list[str] = []
    value = receipt if isinstance(receipt, dict) else {}
    if not isinstance(receipt, dict) or value.get("gate_id") != "full_regression":
        return ["E_V250_RELEASE_GATE_MISSING"]
    if not _valid_receipt_digest(value):
        errors.append("E_V250_RELEASE_GATE_DIGEST")
    if value.get("source_commit") != source_commit or value.get("source_tree") != source_tree:
        errors.append("E_V250_RELEASE_GATE_STALE")
    if (
        value.get("check_state") != "passed"
        or value.get("run_outcome") != "passed"
        or value.get("evidence_state") != "current"
        or value.get("invocation_count_for_released_identity") != 1
    ):
        errors.append("E_V250_RELEASE_GATE_NOT_CURRENT")
    denominator = value.get("denominator")
    if not isinstance(denominator, dict):
        errors.append("E_V250_CURRENT_DENOMINATOR_MISSING")
        return errors
    files = denominator.get("test_files")
    case_count = denominator.get("test_case_count")
    if (
        denominator.get("denominator_id") != "V250-CURRENT-GENERATION-FULL"
        or denominator.get("generation_id") != "V2.50"
        or denominator.get("scope") != "current_generation_full_regression"
        or denominator.get("source_commit") != source_commit
        or denominator.get("source_tree") != source_tree
        or denominator.get("test_root") != "tests/v250"
        or denominator.get("test_pattern") != "test_*.py"
        or denominator.get("contract_path")
        != "references/current/generations/V2.50/contracts/release-command-manifest.json"
        or not isinstance(denominator.get("contract_sha256"), str)
        or SHA256_RE.fullmatch(denominator["contract_sha256"]) is None
        or denominator.get("legacy_roots_excluded") != ["tests/v23", "tests/v249"]
        or not isinstance(files, list)
        or not files
        or files != sorted(files, key=lambda item: item.get("path", ""))
        or denominator.get("test_file_count") != len(files)
        or not isinstance(case_count, int)
        or isinstance(case_count, bool)
        or case_count < 1
        or value.get("discovered_test_count") != case_count
        or value.get("legacy_test_invocation_count") != 0
    ):
        errors.append("E_V250_CURRENT_DENOMINATOR_INCOMPLETE")
    for item in files if isinstance(files, list) else []:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item.get("path"), str)
            or not item["path"].startswith("tests/v250/test_")
            or not item["path"].endswith(".py")
            or not isinstance(item.get("sha256"), str)
            or SHA256_RE.fullmatch(item["sha256"]) is None
        ):
            errors.append("E_V250_CURRENT_DENOMINATOR_FILE")
            break
    if isinstance(files, list) and denominator.get("test_file_set_sha256") != canonical_sha256(files):
        errors.append("E_V250_CURRENT_DENOMINATOR_DIGEST")
    denominator_payload = dict(denominator)
    claimed_denominator_digest = denominator_payload.pop("denominator_sha256", None)
    if claimed_denominator_digest != canonical_sha256(denominator_payload):
        errors.append("E_V250_CURRENT_DENOMINATOR_DIGEST")
    argv = value.get("argv")
    worktree = value.get("worktree_binding")
    if (
        value.get("runner_role") != "current_generation_full_regression"
        or value.get("execution_source") != "exact_clean_worktree"
        or not _nonempty(value.get("run_id"))
        or not isinstance(argv, list)
        or argv[1:]
        != [
            "-m",
            "unittest",
            "discover",
            "-v",
            "-s",
            "tests/v250",
            "-p",
            "test_*.py",
        ]
        or value.get("cwd") != "."
        or value.get("returncode") != 0
        or not isinstance(value.get("output_sha256"), str)
        or SHA256_RE.fullmatch(value["output_sha256"]) is None
        or not isinstance(worktree, dict)
        or worktree.get("binding_kind") != "exact_clean_worktree"
        or worktree.get("head_commit") != source_commit
        or worktree.get("head_tree") != source_tree
        or worktree.get("dirty_entry_count") != 0
        or worktree.get("untracked_entry_count") != 0
        or worktree.get("status_porcelain_sha256")
        != hashlib.sha256(b"").hexdigest()
    ):
        errors.append("E_V250_CURRENT_FULL_RUN_CONTRACT")
    return errors


def _security_git(*args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    """Read one frozen security denominator without network or replace objects."""

    return subprocess.run(
        ["git", "--no-replace-objects", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=text,
        env={
            **os.environ,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )


def _security_git_bytes(*args: str) -> bytes:
    result = _security_git(*args, text=False)
    if result.returncode != 0:
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_OBJECT")
    return bytes(result.stdout)


def _security_git_text(*args: str) -> str:
    result = _security_git(*args, text=True)
    if result.returncode != 0:
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_OBJECT")
    return str(result.stdout).strip()


def _security_target_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_PATH")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or str(pure) != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_PATH")
    return value


def _security_review_git_snapshot(
    source_commit: str, source_tree: str
) -> dict[str, Any]:
    """Read the manifest and every reviewed target from the exact Git object."""

    if (
        COMMIT_RE.fullmatch(source_commit) is None
        or COMMIT_RE.fullmatch(source_tree) is None
        or _security_git_text("rev-parse", f"{source_commit}^{{tree}}")
        != source_tree
    ):
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_IDENTITY")
    manifest_bytes = _security_git_bytes(
        "show", f"{source_commit}:{V250_SECURITY_CONTRACT_PATH}"
    )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_MANIFEST") from exc
    targets = manifest.get("review_targets") if isinstance(manifest, dict) else None
    if (
        not isinstance(targets, list)
        or not targets
        or manifest.get("schema_version")
        != "goal-teams-v2.50-release-security-review-v2"
        or manifest.get("denominator_id")
        != "V250-RELEASE-SECURITY-IMPLEMENTATION"
        or manifest.get("unknown_or_missing_policy") != "fail_closed"
    ):
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_MANIFEST")
    target_by_path: dict[str, dict[str, Any]] = {}
    for target in targets:
        if (
            not isinstance(target, dict)
            or set(target) != {"path", "content_kind", "categories"}
            or not isinstance(target.get("categories"), list)
            or not target["categories"]
            or target["categories"] != sorted(set(target["categories"]))
        ):
            raise ValueError("E_V250_SECURITY_REVIEW_GIT_MANIFEST")
        path = _security_target_path(target.get("path"))
        if path in target_by_path:
            raise ValueError("E_V250_SECURITY_REVIEW_GIT_MANIFEST")
        target_by_path[path] = target
    if set(target_by_path) != V250_SECURITY_REQUIRED_TARGET_PATHS:
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_DENOMINATOR")

    raw_tree = _security_git_bytes(
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        source_commit,
        "--",
        *sorted(target_by_path),
    )
    tree_entries: dict[str, dict[str, str]] = {}
    for record in raw_tree.split(b"\x00"):
        if not record:
            continue
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ", 2)
            path = path_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("E_V250_SECURITY_REVIEW_GIT_TREE") from exc
        if path in tree_entries:
            raise ValueError("E_V250_SECURITY_REVIEW_GIT_TREE")
        tree_entries[path] = {
            "mode": mode,
            "type": kind,
            "object_id": object_id,
        }
    if set(tree_entries) != set(target_by_path):
        raise ValueError("E_V250_SECURITY_REVIEW_GIT_DENOMINATOR")
    objects: dict[str, dict[str, Any]] = {}
    for path in sorted(target_by_path):
        entry = tree_entries[path]
        if (
            entry["type"] != "blob"
            or entry["mode"] not in {"100644", "100755"}
            or COMMIT_RE.fullmatch(entry["object_id"]) is None
        ):
            raise ValueError("E_V250_SECURITY_REVIEW_GIT_TARGET")
        blob = _security_git_bytes("cat-file", "blob", entry["object_id"])
        if blob != _security_git_bytes("show", f"{source_commit}:{path}"):
            raise ValueError("E_V250_SECURITY_REVIEW_GIT_BLOB")
        objects[path] = {
            "path": path,
            "categories": target_by_path[path]["categories"],
            "content_kind": target_by_path[path]["content_kind"],
            "git_mode": entry["mode"],
            "git_blob": entry["object_id"],
            "size": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
    return {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "target_paths": sorted(target_by_path),
        "objects": objects,
    }


def _validate_security_review_receipt(
    receipt: object, source_commit: str, source_tree: str
) -> list[str]:
    errors: list[str] = []
    value = receipt if isinstance(receipt, dict) else {}
    if not isinstance(receipt, dict) or value.get("gate_id") != "release_security_review":
        return ["E_V250_RELEASE_GATE_MISSING"]
    if not _valid_receipt_digest(value):
        errors.append("E_V250_RELEASE_GATE_DIGEST")
    if value.get("source_commit") != source_commit or value.get("source_tree") != source_tree:
        errors.append("E_V250_RELEASE_GATE_STALE")
    if (
        value.get("check_state") != "passed"
        or value.get("run_outcome") != "passed"
        or value.get("evidence_state") != "current"
        or value.get("invocation_count_for_released_identity") != 1
    ):
        errors.append("E_V250_RELEASE_GATE_NOT_CURRENT")
    reviewer = value.get("reviewer_identity")
    if (
        not isinstance(reviewer, dict)
        or not _nonempty(reviewer.get("reviewer_id"))
        or reviewer.get("runner_path")
        != "scripts/checks/run-v250-release-security-review.py"
        or not isinstance(reviewer.get("runner_sha256"), str)
        or SHA256_RE.fullmatch(reviewer["runner_sha256"]) is None
        or not _nonempty(value.get("review_run_id"))
    ):
        errors.append("E_V250_SECURITY_REVIEWER_IDENTITY")
    if (
        value.get("fresh_process_observed") is not True
        or value.get("fresh_separate_process") is not True
        or value.get("runner_pid") == value.get("orchestrator_pid")
        or not isinstance(value.get("runner_pid"), int)
        or not isinstance(value.get("orchestrator_pid"), int)
        or value.get("actor_assurance") != "I1"
        or value.get("actor_relationship") != "correlated"
        or value.get("external_independence") is not False
        or value.get("independence_claim") is not False
        or value.get("independence_scope") != "fresh_separate_process_only"
    ):
        errors.append("E_V250_SECURITY_ASSURANCE")
    manifest: dict[str, Any] = {}
    expected_objects: dict[str, dict[str, Any]] = {}
    try:
        snapshot = _security_review_git_snapshot(source_commit, source_tree)
        manifest = snapshot["manifest"]
        targets = manifest.get("review_targets")
        expected_assertions = manifest["assertion_denominator"]
        expected_target_paths = snapshot["target_paths"]
        expected_objects = snapshot["objects"]
        expected_contract_paths = {
            item["path"]
            for item in targets
            if isinstance(item, dict)
            and isinstance(item.get("categories"), list)
            and "contract" in item["categories"]
        }
        manifest_sha256 = snapshot["manifest_sha256"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        errors.append("E_V250_SECURITY_REVIEW_DENOMINATOR")
        expected_assertions = []
        expected_target_paths = []
        expected_contract_paths = set()
        manifest_sha256 = None
    assertions = value.get("assertions")
    assertion_ids = (
        [item.get("assertion_id") for item in assertions if isinstance(item, dict)]
        if isinstance(assertions, list)
        else []
    )
    contract_digests = value.get("contract_digests")
    identity = value.get("identity_binding")
    denominator = value.get("review_denominator")
    reviewed_files = value.get("reviewed_files")
    reviewed_paths = (
        [item.get("path") for item in reviewed_files if isinstance(item, dict)]
        if isinstance(reviewed_files, list)
        else []
    )
    reviewed_by_path = (
        {
            item.get("path"): item
            for item in reviewed_files
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        if isinstance(reviewed_files, list)
        else {}
    )
    runner_file = reviewed_by_path.get(
        "scripts/checks/run-v250-release-security-review.py", {}
    )
    denominator_digest_valid = bool(
        isinstance(denominator, dict)
        and denominator.get("denominator_sha256")
        == canonical_sha256(
            {
                key: item
                for key, item in denominator.items()
                if key != "denominator_sha256"
            }
        )
    )
    reviewed_file_set_valid = bool(
        isinstance(reviewed_files, list)
        and value.get("reviewed_file_set_sha256")
        == canonical_sha256(reviewed_files)
    )
    reviewed_file_entries_valid = bool(
        isinstance(reviewed_files, list)
        and reviewed_paths == expected_target_paths
        and len(reviewed_by_path) == len(expected_target_paths)
        and all(
            isinstance(item, dict)
            and set(item)
            == {
                "path",
                "categories",
                "content_kind",
                "git_mode",
                "git_blob",
                "size",
                "sha256",
                "filesystem_sha256",
                "git_object_matches_filesystem",
                "symlink",
            }
            and item.get("categories")
            == expected_objects.get(item.get("path"), {}).get("categories")
            and item.get("content_kind")
            == expected_objects.get(item.get("path"), {}).get("content_kind")
            and item.get("git_mode")
            == expected_objects.get(item.get("path"), {}).get("git_mode")
            and item.get("git_blob")
            == expected_objects.get(item.get("path"), {}).get("git_blob")
            and item.get("size")
            == expected_objects.get(item.get("path"), {}).get("size")
            and item.get("sha256")
            == expected_objects.get(item.get("path"), {}).get("sha256")
            and item.get("filesystem_sha256") == item.get("sha256")
            and item.get("git_object_matches_filesystem") is True
            and item.get("symlink") is False
            for item in reviewed_files
        )
    )
    identity_valid = bool(
        isinstance(identity, dict)
        and identity.get("binding_kind")
        == "exact_clean_git_object_and_filesystem"
        and identity.get("repository_root") == "."
        and identity.get("head_commit") == source_commit
        and identity.get("head_tree") == source_tree
        and identity.get("status_porcelain_sha256")
        == hashlib.sha256(b"").hexdigest()
        and identity.get("dirty_entry_count") == 0
        and identity.get("untracked_entry_count") == 0
        and identity.get("worktree_diff_returncode") == 0
        and identity.get("index_diff_returncode") == 0
        and identity.get("git_replace_objects_disabled") is True
        and identity.get("lazy_fetch_disabled") is True
    )
    denominator_valid = bool(
        isinstance(denominator, dict)
        and denominator.get("denominator_id")
        == "V250-RELEASE-SECURITY-IMPLEMENTATION"
        and denominator.get("generation_id") == "V2.50"
        and denominator.get("source_commit") == source_commit
        and denominator.get("source_tree") == source_tree
        and denominator.get("manifest_path")
        == "references/current/generations/V2.50/contracts/release-security-review-manifest.json"
        and denominator.get("manifest_sha256") == manifest_sha256
        and denominator.get("target_count") == len(expected_target_paths)
        and denominator.get("target_paths") == expected_target_paths
        and denominator.get("required_categories")
        == manifest.get("required_categories")
        and denominator.get("reviewed_file_set_sha256")
        == value.get("reviewed_file_set_sha256")
        and denominator.get("unknown_or_missing_policy") == "fail_closed"
        and denominator_digest_valid
    )
    components = {
        "dependency_review": value.get("dependency_review"),
        "secret_negative_scan": value.get("secret_negative_scan"),
        "dangerous_operation_review": value.get("dangerous_operation_review"),
        "command_execution_review": value.get("command_execution_review"),
        "workflow_dependency_review": value.get("workflow_dependency_review"),
        "git_ssh_review": value.get("git_ssh_review"),
    }
    component_valid = all(
        isinstance(item, dict)
        and item.get("passed") is True
        and item.get("findings") == []
        for item in components.values()
    )
    dangerous = components["dangerous_operation_review"]
    secret_scan = components["secret_negative_scan"]
    review_material = {
        "assertions": assertions,
        "findings": value.get("findings"),
        "reviewed_file_set_sha256": value.get("reviewed_file_set_sha256"),
        "dangerous_operation_inventory_sha256": (
            dangerous.get("inventory_sha256")
            if isinstance(dangerous, dict)
            else None
        ),
    }
    if (
        value.get("legacy_security_fixture_invocation_count") != 0
        or value.get("s2_security_check_invocation_count") != 0
        or value.get("s2_projection") != "forbidden"
        or value.get("runner_role")
        != "exact_released_implementation_security_reviewer"
        or not identity_valid
        or not denominator_valid
        or not reviewed_file_set_valid
        or not reviewed_file_entries_valid
        or not isinstance(runner_file, dict)
        or (reviewer if isinstance(reviewer, dict) else {}).get("runner_sha256")
        != runner_file.get("sha256")
        or assertion_ids != expected_assertions
        or any(
            not isinstance(item, dict) or item.get("passed") is not True
            for item in (assertions if isinstance(assertions, list) else [])
        )
        or value.get("findings") != []
        or value.get("finding_count") != 0
        or not component_valid
        or not isinstance(secret_scan, dict)
        or secret_scan.get("finding_count") != 0
        or not isinstance(dangerous, dict)
        or dangerous.get("observed_count")
        != dangerous.get("allowed_count")
        or dangerous.get("observed_count")
        != manifest.get("dangerous_operation_allowlist", {}).get(
            "allowed_inventory_count"
        )
        or dangerous.get("inventory_sha256")
        != manifest.get("dangerous_operation_allowlist", {}).get(
            "allowed_inventory_sha256"
        )
        or value.get("review_digest") != canonical_sha256(review_material)
        or not isinstance(contract_digests, dict)
        or set(contract_digests) != expected_contract_paths
        or any(
            contract_digests.get(path)
            != reviewed_by_path.get(path, {}).get("sha256")
            for path in expected_contract_paths
        )
        or any(
            not isinstance(item, str) or SHA256_RE.fullmatch(item) is None
            for item in contract_digests.values()
        )
    ):
        errors.append("E_V250_SECURITY_REVIEW_CONTRACT")
    return errors


def validate_release_gate_bindings(
    source_commit: str,
    source_tree: str,
    full_regression: object,
    release_security_review: object,
) -> dict[str, Any]:
    """Require current, passed S1 receipts bound to one released identity."""

    errors = _validate_full_regression_receipt(full_regression, source_commit, source_tree)
    errors.extend(
        _validate_security_review_receipt(
            release_security_review, source_commit, source_tree
        )
    )
    deduplicated = list(dict.fromkeys(errors))
    return {
        "ok": not deduplicated,
        "passed": not deduplicated,
        "errors": deduplicated,
        "source_commit": source_commit,
        "source_tree": source_tree,
    }


def _runtime_transition_errors(
    receipt: object,
    source_commit: str,
    source_tree: str,
    expected_host_execution_id: str | None = None,
    route_receipt_path_override: Path | str | None = None,
    authorization_receipt_path_override: Path | str | None = None,
) -> list[str]:
    try:
        verdict = validate_runtime_transition(
            receipt,
            expected_stage="released",
            allow_release=True,
            expected_source_commit=source_commit,
            expected_source_tree=source_tree,
            expected_host_execution_id=expected_host_execution_id,
            route_receipt_path_override=route_receipt_path_override,
            authorization_receipt_path_override=(
                authorization_receipt_path_override
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        verdict = {"ok": False, "may_enter_s0": False, "errors": []}
    if verdict.get("ok") and verdict.get("may_enter_s0"):
        return []
    strict_errors = verdict.get("errors")
    return list(
        dict.fromkeys(
            ["E_V250_RELEASED_RUNTIME_S0_REQUIRED"]
            + (
                [str(item) for item in strict_errors]
                if isinstance(strict_errors, list)
                else []
            )
        )
    )


def build_s0_receipt(
    *,
    source_commit: str,
    source_tree: str,
    runtime_transition: Mapping[str, Any],
    expected_host_execution_id: str,
) -> dict[str, Any]:
    transition_errors = _runtime_transition_errors(
        runtime_transition,
        source_commit,
        source_tree,
        expected_host_execution_id,
    )
    if transition_errors:
        raise ValueError(transition_errors[0])
    return _seal_receipt(
        {
            "schema_version": "goal-teams-v2.50-s0-receipt-v1",
            "gate_id": "s0_identity",
            "source_commit": source_commit,
            "source_tree": source_tree,
            "runtime_transition_id": runtime_transition.get("transition_id"),
            "runtime_transition_receipt_sha256": runtime_transition["receipt_sha256"],
            "host_execution_id": expected_host_execution_id,
            "actor_assurance": "I1",
            "actor_relationship": "correlated",
            "external_independence": False,
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
        }
    )


def build_s1_receipt(
    *,
    source_commit: str,
    source_tree: str,
    full_regression: Mapping[str, Any],
    release_security_review: Mapping[str, Any],
) -> dict[str, Any]:
    verdict = validate_release_gate_bindings(
        source_commit, source_tree, full_regression, release_security_review
    )
    if not verdict["ok"]:
        raise ValueError(str(verdict["errors"][0]))
    return _seal_receipt(
        {
            "schema_version": "goal-teams-v2.50-s1-receipt-v1",
            "gate_id": "s1_release_readiness",
            "source_commit": source_commit,
            "source_tree": source_tree,
            "full_regression_receipt_sha256": full_regression["receipt_sha256"],
            "release_security_review_receipt_sha256": release_security_review[
                "receipt_sha256"
            ],
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
        }
    )


def validate_project_start_authorization(
    receipt: object,
    *,
    repository: str,
    version: str,
    candidate_branch: str,
    tag: str,
    required_action_classes: Sequence[str] = tuple(sorted(REQUIRED_S4_ACTION_CLASSES)),
    validation_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Validate the real project-start receipt without inventing a new state."""

    errors: list[str] = []
    value = receipt if isinstance(receipt, dict) else {}
    if not isinstance(receipt, dict):
        errors.append("E_V250_PROJECT_START_AUTHORIZATION_REQUIRED")
    repository_value = value.get("repository")
    if (
        not PROJECT_START_AUTHORIZATION_REQUIRED_KEYS.issubset(value)
        or not set(value).issubset(PROJECT_START_AUTHORIZATION_ALLOWED_KEYS)
        or not isinstance(repository_value, dict)
        or not PROJECT_START_AUTHORIZATION_REPOSITORY_REQUIRED_KEYS.issubset(
            repository_value
        )
        or not set(repository_value).issubset(
            PROJECT_START_AUTHORIZATION_REPOSITORY_KEYS
        )
    ):
        errors.append("E_V250_AUTHORIZATION_UNEXPECTED_FIELD")
    optional_string_fields = (
        "authorization_source",
        "approver_identity",
        "credential_policy",
        "idempotency_key",
    )
    optional_boolean_fields = (
        "conversational_reconfirmation_required",
        "later_exact_identity_is_evidence_not_authorization",
        "revoked",
    )
    optional_string_list_fields = (
        "permitted_other_external_writes",
        "revocation_conditions",
    )
    if (
        any(
            field in value and not _nonempty(value.get(field))
            for field in optional_string_fields
        )
        or any(
            field in value and not isinstance(value.get(field), bool)
            for field in optional_boolean_fields
        )
        or any(
            field in value
            and (
                not isinstance(value.get(field), list)
                or not all(_nonempty(item) for item in value.get(field, []))
            )
            for field in optional_string_list_fields
        )
        or (
            "revoked_at" in value
            and value.get("revoked_at") is not None
            and not _nonempty(value.get("revoked_at"))
        )
        or (
            isinstance(repository_value, dict)
            and any(
                field in repository_value
                and (
                    not isinstance(repository_value.get(field), str)
                    or COMMIT_RE.fullmatch(repository_value[field]) is None
                )
                for field in ("base_sha", "base_tree")
            )
        )
    ):
        errors.append("E_V250_AUTHORIZATION_FIELD_TYPE")
    if (
        value.get("schema_version") != "goal-teams-project-start-authorization-v2.50"
        or value.get("authorization_state") != "granted_once_at_project_start"
        or not _nonempty(value.get("authorization_id"))
        or value.get("authorization_id") != value.get("receipt_id")
        or value.get("authorization_lineage_preserved") is not True
        or value.get("version") != version
        or value.get("candidate_branch") != candidate_branch
        or value.get("tag") != tag
        or not _nonempty(value.get("locked_scope"))
        or not isinstance(repository_value, dict)
        or not _nonempty(repository_value.get("id"))
        or repository_value.get("name_with_owner") != repository
        or repository_value.get("origin_fetch") != f"git@github.com:{repository}.git"
        or repository_value.get("origin_push") != f"git@github.com:{repository}.git"
        or repository_value.get("default_branch") != "main"
    ):
        errors.append("E_V250_AUTHORIZATION_IDENTITY_DRIFT")
    actions = value.get("action_allowlist")
    if (
        not isinstance(actions, list)
        or not all(_nonempty(action) for action in actions)
        or len(actions) != len(set(actions))
        or not set(required_action_classes).issubset(set(actions))
    ):
        errors.append("E_V250_AUTHORIZATION_ACTION_DRIFT")
    conditions = value.get("validity_conditions")
    if (
        not isinstance(conditions, list)
        or not all(_nonempty(condition) for condition in conditions)
        or len(conditions) != len(set(conditions))
        or not REQUIRED_AUTH_VALIDITY_CONDITIONS.issubset(set(conditions))
    ):
        errors.append("E_V250_AUTHORIZATION_VALIDITY")
    intent = value.get("intent")
    expected_intent = {
        "repository_id": repository_value.get("id") if isinstance(repository_value, dict) else None,
        "repository": repository,
        "version": version,
        "candidate_branch": candidate_branch,
        "tag": tag,
        "locked_scope": value.get("locked_scope"),
        "action_allowlist": actions,
        "validity_conditions": conditions,
    }
    if (
        not isinstance(intent, dict)
        or set(intent) != PROJECT_START_AUTHORIZATION_INTENT_KEYS
        or intent != expected_intent
        or value.get("intent_sha256") != canonical_sha256(intent)
    ):
        errors.append("E_V250_AUTHORIZATION_INTENT_DRIFT")
    now = validation_time or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    try:
        issued = dt.datetime.fromisoformat(str(value.get("issued_at")))
        if issued.tzinfo is None:
            raise ValueError("issued_at must include timezone")
        expires_raw = value.get("expires_at")
        expires = (
            None
            if expires_raw is None
            else dt.datetime.fromisoformat(str(expires_raw))
        )
        if expires is not None and expires.tzinfo is None:
            raise ValueError("expires_at must include timezone")
        if issued > now or (expires is not None and expires <= now):
            raise ValueError("authorization is outside validity window")
    except (TypeError, ValueError):
        errors.append("E_V250_AUTHORIZATION_EXPIRED")
    if value.get("revoked_at") not in (None, "") or value.get("revoked") is True:
        errors.append("E_V250_AUTHORIZATION_REVOKED")
    errors = list(dict.fromkeys(errors))
    return {
        "ok": not errors,
        "passed": not errors,
        "errors": errors,
        "authorization_id": value.get("authorization_id"),
        "intent_sha256": value.get("intent_sha256"),
        "authorization_receipt_sha256": canonical_sha256(value) if isinstance(receipt, dict) else None,
    }


def _validate_s3(
    receipt: object,
    *,
    project_size: str,
    source_commit: str,
    source_tree: str,
    asset_set_id: str,
    asset_set_digest: str,
    s2_receipt_sha256: str,
) -> list[str]:
    value = receipt if isinstance(receipt, dict) else {}
    errors: list[str] = []
    if not isinstance(receipt, dict) or not _valid_receipt_digest(value):
        return ["E_V250_S3_RECEIPT_MISSING"]
    identity_ok = (
        value.get("source_commit") == source_commit
        and value.get("source_tree") == source_tree
        and value.get("asset_set_id") == asset_set_id
        and value.get("asset_set_digest") == asset_set_digest
        and value.get("s2_receipt_sha256") == s2_receipt_sha256
    )
    if not identity_ok:
        errors.append("E_V250_S3_IDENTITY_DRIFT")
    if project_size == "large":
        if (
            value.get("gate_id") != "s3_large_release_install"
            or value.get("gate_requirement") != "required"
            or value.get("check_state") != "passed"
            or value.get("run_outcome") != "passed"
            or value.get("evidence_state") != "current"
            or value.get("s3_process_invocation_count") != 1
            or not isinstance(value.get("install_report_sha256"), str)
            or SHA256_RE.fullmatch(value["install_report_sha256"]) is None
        ):
            errors.append("E_V250_S3_NOT_CURRENT")
    else:
        if (
            value.get("gate_requirement") != "not_required"
            or value.get("check_state") != "not_required"
            or value.get("run_outcome") != "not_run"
            or value.get("s3_process_invocation_count") != 0
            or value.get("child_argv") != []
        ):
            errors.append("E_V250_S3_UNEXPECTED_INVOCATION")
    return errors


def _validate_boundary(
    receipt: object,
    *,
    source_commit: str,
    source_tree: str,
    asset_set_id: str,
    asset_set_digest: str,
    s2_receipt_sha256: str,
) -> list[str]:
    value = receipt if isinstance(receipt, dict) else {}
    if not isinstance(receipt, dict):
        return ["E_V250_REPOSITORY_BOUNDARY_MISSING"]
    errors: list[str] = []
    if not _valid_receipt_digest(value):
        errors.append("E_V250_REPOSITORY_BOUNDARY_DIGEST")
    if (
        value.get("gate_id") != "repository_boundary_compliance"
        or value.get("source_commit") != source_commit
        or value.get("source_tree") != source_tree
        or value.get("asset_set_id") != asset_set_id
        or value.get("asset_set_digest") != asset_set_digest
        or value.get("s2_receipt_sha256") != s2_receipt_sha256
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_STALE")
    if (
        value.get("check_state") != "passed"
        or value.get("run_outcome") != "passed"
        or value.get("evidence_state") != "current"
        or value.get("asset_build_invocation_count") != 0
        or value.get("claim_scope") != "repository_boundary_only"
        or value.get("same_built_asset_set") is not True
        or value.get("validation_kind") != "frozen_source_and_boundary_integrity"
        or value.get("second_build_comparison_attempted") is not False
        or value.get("reproducibility_claim") is not False
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_NOT_CURRENT")
    return errors


def build_release_control_receipt(
    *,
    repository: str,
    version: str,
    project_size: str,
    candidate_branch: str,
    tag: str,
    source_commit: str,
    source_tree: str,
    authorization_receipt: Mapping[str, Any],
    released_runtime_transition: Mapping[str, Any],
    s0: Mapping[str, Any],
    full_regression: Mapping[str, Any],
    release_security_review: Mapping[str, Any],
    s1: Mapping[str, Any],
    s2: Mapping[str, Any],
    asset_integrity_validation: Mapping[str, Any],
    s3: Mapping[str, Any],
    repository_boundary: Mapping[str, Any],
    external_anchor_validation: Mapping[str, Any],
    validation_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Create and validate the complete local S4 preflight receipt chain."""

    auth = validate_project_start_authorization(
        authorization_receipt,
        repository=repository,
        version=version,
        candidate_branch=candidate_branch,
        tag=tag,
        validation_time=validation_time,
    )
    if not auth["ok"]:
        raise ValueError(str(auth["errors"][0]))
    asset_set_id = str(s2.get("asset_set_id", ""))
    asset_set_digest = str(s2.get("asset_set_digest", ""))
    chain_digests = {
        "authorization_receipt_sha256": auth["authorization_receipt_sha256"],
        "released_runtime_transition_receipt_sha256": released_runtime_transition.get("receipt_sha256"),
        "s0_receipt_sha256": s0.get("receipt_sha256"),
        "full_regression_receipt_sha256": full_regression.get("receipt_sha256"),
        "release_security_review_receipt_sha256": release_security_review.get("receipt_sha256"),
        "s1_receipt_sha256": s1.get("receipt_sha256"),
        "s2_receipt_sha256": s2.get("receipt_sha256"),
        "asset_integrity_validation_receipt_sha256": asset_integrity_validation.get("receipt_sha256"),
        "s3_receipt_sha256": s3.get("receipt_sha256"),
        "repository_boundary_receipt_sha256": repository_boundary.get("receipt_sha256"),
        "external_anchor_validation_receipt_sha256": external_anchor_validation.get("receipt_sha256"),
    }
    s4_preflight = _seal_receipt(
        {
            "schema_version": "goal-teams-v2.50-s4-preflight-receipt-v1",
            "gate_id": "s4_preflight",
            "repository": repository,
            "version": version,
            "candidate_branch": candidate_branch,
            "tag": tag,
            "source_commit": source_commit,
            "source_tree": source_tree,
            "asset_set_id": asset_set_id,
            "asset_set_digest": asset_set_digest,
            "authorization_id": auth["authorization_id"],
            "intent_sha256": auth["intent_sha256"],
            "required_action_classes": sorted(REQUIRED_S4_ACTION_CLASSES),
            "authorized_operation_plan": [
                "git_push_tag_via_ssh",
                "github_release_via_api",
                "github_release_asset_upload_via_api",
                "github_release_exact_readback_via_api",
                "formal_install_from_published_asset",
                "formal_install_exact_readback",
            ],
            "chain_digests": chain_digests,
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "release_control_correlated": True,
            "publish_allowed": False,
            "external_anchor_revalidation_required": True,
            "action_executed": False,
            "additional_user_confirmation_required": False,
            "git_transport": "ssh_only",
            "https_git_fallback_allowed": False,
        }
    )
    control: dict[str, Any] = {
        "schema_version": "goal-teams-v2.50-release-control-receipt-v1",
        "repository": repository,
        "version": version,
        "project_size": project_size,
        "candidate_branch": candidate_branch,
        "tag": tag,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "asset_set_id": asset_set_id,
        "asset_set_digest": asset_set_digest,
        "intent_sha256": auth["intent_sha256"],
        "authorization_receipt": copy.deepcopy(dict(authorization_receipt)),
        "released_runtime_transition": copy.deepcopy(dict(released_runtime_transition)),
        "s0": copy.deepcopy(dict(s0)),
        "full_regression": copy.deepcopy(dict(full_regression)),
        "release_security_review": copy.deepcopy(dict(release_security_review)),
        "s1": copy.deepcopy(dict(s1)),
        "s2": copy.deepcopy(dict(s2)),
        "asset_integrity_validation": copy.deepcopy(dict(asset_integrity_validation)),
        "s3": copy.deepcopy(dict(s3)),
        "repository_boundary": copy.deepcopy(dict(repository_boundary)),
        "external_anchor_validation": copy.deepcopy(dict(external_anchor_validation)),
        "s4_preflight": s4_preflight,
    }
    control["release_control_sha256"] = _receipt_sha256(control)
    verdict = validate_release_control_receipt(
        control,
        expected_repository=repository,
        expected_version=version,
        expected_candidate_branch=candidate_branch,
        expected_tag=tag,
        expected_source_commit=source_commit,
        expected_source_tree=source_tree,
        validation_time=validation_time,
    )
    if not verdict["ok"]:
        raise ValueError(str(verdict["errors"][0]))
    return control


def validate_release_control_receipt(
    receipt: object,
    *,
    expected_repository: str,
    expected_version: str,
    expected_candidate_branch: str,
    expected_tag: str,
    expected_source_commit: str,
    expected_source_tree: str,
    runtime_route_receipt_path: Path | str | None = None,
    runtime_authorization_receipt_path: Path | str | None = None,
    validation_time: dt.datetime | None = None,
) -> dict[str, Any]:
    """Fail closed on any missing, stale, or cross-asset release receipt."""

    value = receipt if isinstance(receipt, dict) else {}
    errors: list[str] = []
    if not isinstance(receipt, dict):
        return {
            "ok": False,
            "passed": False,
            "publish_allowed": False,
            "errors": ["E_V250_RELEASE_CONTROL_REQUIRED"],
        }
    if value.get("schema_version") != "goal-teams-v2.50-release-control-receipt-v1":
        errors.append("E_V250_RELEASE_CONTROL_SCHEMA")
    if (
        value.get("release_control_sha256") != _receipt_sha256(value)
        or SHA256_RE.fullmatch(str(value.get("release_control_sha256", ""))) is None
    ):
        errors.append("E_V250_RELEASE_CONTROL_DIGEST")
    if (
        value.get("repository") != expected_repository
        or value.get("version") != expected_version
        or value.get("candidate_branch") != expected_candidate_branch
        or value.get("tag") != expected_tag
        or value.get("source_commit") != expected_source_commit
        or value.get("source_tree") != expected_source_tree
        or value.get("project_size") not in {"small", "medium", "large"}
    ):
        errors.append("E_V250_RELEASE_CONTROL_IDENTITY_DRIFT")

    auth = validate_project_start_authorization(
        value.get("authorization_receipt"),
        repository=expected_repository,
        version=expected_version,
        candidate_branch=expected_candidate_branch,
        tag=expected_tag,
        validation_time=validation_time,
    )
    errors.extend(auth["errors"])
    if value.get("intent_sha256") != auth.get("intent_sha256"):
        errors.append("E_V250_RELEASE_CONTROL_INTENT_DRIFT")

    transition = value.get("released_runtime_transition")
    transition_value = transition if isinstance(transition, dict) else {}
    errors.extend(
        _runtime_transition_errors(
            transition,
            expected_source_commit,
            expected_source_tree,
            route_receipt_path_override=runtime_route_receipt_path,
            authorization_receipt_path_override=(
                runtime_authorization_receipt_path
            ),
        )
    )
    s0 = value.get("s0")
    s0_value = s0 if isinstance(s0, dict) else {}
    if (
        not _valid_receipt_digest(s0)
        or s0_value.get("gate_id") != "s0_identity"
        or s0_value.get("source_commit") != expected_source_commit
        or s0_value.get("source_tree") != expected_source_tree
        or s0_value.get("runtime_transition_receipt_sha256")
        != transition_value.get("receipt_sha256")
        or s0_value.get("host_execution_id")
        != transition_value.get("host_execution_id")
        or s0_value.get("check_state") != "passed"
        or s0_value.get("evidence_state") != "current"
    ):
        errors.append("E_V250_S0_NOT_CURRENT")

    full = value.get("full_regression")
    security = value.get("release_security_review")
    full_value = full if isinstance(full, dict) else {}
    security_value = security if isinstance(security, dict) else {}
    s1_verdict = validate_release_gate_bindings(
        expected_source_commit, expected_source_tree, full, security
    )
    errors.extend(s1_verdict["errors"])
    s1 = value.get("s1")
    s1_value = s1 if isinstance(s1, dict) else {}
    if (
        not _valid_receipt_digest(s1)
        or s1_value.get("gate_id") != "s1_release_readiness"
        or s1_value.get("source_commit") != expected_source_commit
        or s1_value.get("source_tree") != expected_source_tree
        or s1_value.get("full_regression_receipt_sha256") != full_value.get("receipt_sha256")
        or s1_value.get("release_security_review_receipt_sha256")
        != security_value.get("receipt_sha256")
        or s1_value.get("check_state") != "passed"
        or s1_value.get("evidence_state") != "current"
    ):
        errors.append("E_V250_S1_NOT_CURRENT")

    s2 = value.get("s2")
    s2_value = s2 if isinstance(s2, dict) else {}
    s2_verdict = validate_s2_receipt(
        s2,
        source_commit=expected_source_commit,
        source_tree=expected_source_tree,
        asset_set_id=value.get("asset_set_id"),
        asset_set_digest=value.get("asset_set_digest"),
    )
    errors.extend(s2_verdict["errors"])
    integrity = value.get("asset_integrity_validation")
    integrity_value = integrity if isinstance(integrity, dict) else {}
    if (
        not _valid_receipt_digest(integrity)
        or integrity_value.get("gate_id")
        != "same_built_asset_integrity_validation"
        or integrity_value.get("source_commit") != expected_source_commit
        or integrity_value.get("source_tree") != expected_source_tree
        or integrity_value.get("asset_set_id") != value.get("asset_set_id")
        or integrity_value.get("asset_set_digest") != value.get("asset_set_digest")
        or integrity_value.get("s2_receipt_sha256")
        != s2_value.get("receipt_sha256")
        or integrity_value.get("validation_kind")
        != "frozen_source_and_boundary_integrity"
        or integrity_value.get("same_built_asset_set") is not True
        or integrity_value.get("asset_build_invocation_count") != 0
        or integrity_value.get("second_build_comparison_attempted") is not False
        or integrity_value.get("reproducibility_claim") is not False
        or integrity_value.get("returncode") != 0
        or integrity_value.get("check_state") != "passed"
        or integrity_value.get("evidence_state") != "current"
    ):
        errors.append("E_V250_SAME_ASSET_INTEGRITY_RECEIPT")
    errors.extend(
        _validate_s3(
            value.get("s3"),
            project_size=str(value.get("project_size")),
            source_commit=expected_source_commit,
            source_tree=expected_source_tree,
            asset_set_id=str(value.get("asset_set_id", "")),
            asset_set_digest=str(value.get("asset_set_digest", "")),
            s2_receipt_sha256=str(s2_value.get("receipt_sha256", "")),
        )
    )
    errors.extend(
        _validate_boundary(
            value.get("repository_boundary"),
            source_commit=expected_source_commit,
            source_tree=expected_source_tree,
            asset_set_id=str(value.get("asset_set_id", "")),
            asset_set_digest=str(value.get("asset_set_digest", "")),
            s2_receipt_sha256=str(s2_value.get("receipt_sha256", "")),
        )
    )

    anchor = value.get("external_anchor_validation")
    anchor_value = anchor if isinstance(anchor, dict) else {}
    if (
        not _valid_receipt_digest(anchor)
        or anchor_value.get("schema_version")
        != "goal-teams-v2.50-external-anchor-validation-v1"
        or anchor_value.get("source_commit") != expected_source_commit
        or anchor_value.get("source_tree") != expected_source_tree
        or anchor_value.get("asset_set_digest") != value.get("asset_set_digest")
        or anchor_value.get("check_state") != "passed"
        or anchor_value.get("evidence_state") != "current"
        or any(
            not isinstance(anchor_value.get(field), str)
            or SHA256_RE.fullmatch(anchor_value[field]) is None
            for field in (
                "current_test_file_set_sha256",
                "runtime_input_set_sha256",
                "security_contract_set_sha256",
            )
        )
    ):
        errors.append("E_V250_EXTERNAL_ANCHOR_REQUIRED")

    s4 = value.get("s4_preflight")
    expected_chain = {
        "authorization_receipt_sha256": auth.get("authorization_receipt_sha256"),
        "released_runtime_transition_receipt_sha256": transition_value.get("receipt_sha256"),
        "s0_receipt_sha256": s0_value.get("receipt_sha256"),
        "full_regression_receipt_sha256": full_value.get("receipt_sha256"),
        "release_security_review_receipt_sha256": security_value.get("receipt_sha256"),
        "s1_receipt_sha256": s1_value.get("receipt_sha256"),
        "s2_receipt_sha256": s2_value.get("receipt_sha256"),
        "asset_integrity_validation_receipt_sha256": integrity_value.get("receipt_sha256"),
        "s3_receipt_sha256": value.get("s3", {}).get("receipt_sha256"),
        "repository_boundary_receipt_sha256": value.get("repository_boundary", {}).get("receipt_sha256"),
        "external_anchor_validation_receipt_sha256": anchor_value.get("receipt_sha256"),
    }
    if (
        not _valid_receipt_digest(s4)
        or s4.get("gate_id") != "s4_preflight"
        or s4.get("source_commit") != expected_source_commit
        or s4.get("source_tree") != expected_source_tree
        or s4.get("asset_set_id") != value.get("asset_set_id")
        or s4.get("asset_set_digest") != value.get("asset_set_digest")
        or s4.get("intent_sha256") != auth.get("intent_sha256")
        or s4.get("chain_digests") != expected_chain
        or s4.get("required_action_classes") != sorted(REQUIRED_S4_ACTION_CLASSES)
        or s4.get("check_state") != "passed"
        or s4.get("evidence_state") != "current"
        or s4.get("release_control_correlated") is not True
        or s4.get("publish_allowed") is not False
        or s4.get("external_anchor_revalidation_required") is not True
        or s4.get("action_executed") is not False
        or s4.get("additional_user_confirmation_required") is not False
        or s4.get("git_transport") != "ssh_only"
        or s4.get("https_git_fallback_allowed") is not False
    ):
        errors.append("E_V250_S4_PREFLIGHT_NOT_CURRENT")
    errors = list(dict.fromkeys(errors))
    return {
        "ok": not errors,
        "passed": not errors,
        "publish_allowed": False,
        "external_anchor_revalidation_required": not errors,
        "errors": errors,
        "release_control_sha256": value.get("release_control_sha256"),
        "authorization_id": auth.get("authorization_id"),
        "asset_set_id": value.get("asset_set_id"),
        "asset_set_digest": value.get("asset_set_digest"),
    }
