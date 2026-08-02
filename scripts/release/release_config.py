#!/usr/bin/env python3
"""Load closed, Git-tracked release identities.

V2.50 is the active Skill release profile used by ``skill_release.py``.
V2.48 remains the published rollback baseline; V2.49 is retained as history.
V2.46 keeps the governed CP00-CP18 engine; earlier versions are replay-only.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "goal-teams-release-engine-profile-v1"
PROTOCOL_VERSION = "V2.40"
ACTIVE_VERSION = "V2.50"
NEXT_VERSION = None
ROOT = Path(__file__).resolve().parents[2]
PROFILE_BY_VERSION = {
    "V2.40": ROOT / "references" / "release-profiles" / "v2.40.json",
    "V2.44": ROOT / "references" / "release-profiles" / "v2.44.json",
    "V2.45": ROOT / "references" / "release-profiles" / "v2.45.json",
    "V2.46": ROOT / "references" / "release-profiles" / "v2.46.json",
    "V2.48": ROOT / "references" / "release-profiles" / "v2.48.json",
    "V2.49": ROOT / "references" / "release-profiles" / "v2.49.json",
    "V2.50": ROOT / "references" / "release-profiles" / "v2.50.json",
}
PREDECESSOR_BY_VERSION = {
    "V2.40": None,
    "V2.44": "V2.40",
    "V2.45": "V2.44",
    "V2.46": "V2.45",
    "V2.48": "V2.46",
    "V2.49": "V2.48",
    "V2.50": "V2.48",
}
HOST_ACCEPTANCE_VERSIONS = {"V2.44", "V2.45", "V2.46"}
REQUIRED_FIELDS = {
    "schema_version",
    "protocol_version",
    "version",
    "status",
    "external_writes_allowed",
    "published_before",
    "tag",
    "candidate_location",
    "candidate_branch",
    "goal_teams_work",
    "goal_teams_work_location",
    "owner_run_id",
    "profile_path",
    "release_title",
    "release_body",
    "tag_message",
    "workflow_display_prefix",
    "legacy_recovery_required",
    "snapshot_schema_version",
    "files_manifest_format",
    "public_scan_baseline",
    "close_schema_version",
    "host_acceptance",
}
SIMPLE_FIELDS = {
    "schema_version",
    "version",
    "status",
    "external_writes_allowed",
    "release_mode",
    "approval_model",
    "release_gates",
    "required_status_checks",
    "published_before",
    "tag",
    "candidate_branch",
    "profile_path",
    "release_title",
    "release_body",
    "tag_message",
    "snapshot_schema_version",
    "files_manifest_format",
}
V249_FIELDS = SIMPLE_FIELDS | {
    "development_gate_policy",
    "release_readiness_policy",
    "s2_policy",
    "s3_policy",
    "s4_authorization_source",
    "repository_boundary_gate",
    "runtime_transition_assurance",
    "git_transport",
    "public_asset_map_path",
}
V250_FIELDS = V249_FIELDS
SIMPLE_GATES = [
    "source_freeze",
    "checks",
    "package",
    "isolated_install",
    "publish",
]
V249_GATES = [
    "source_freeze",
    "release_readiness",
    "single_build",
    "repository_boundary_compliance",
    "large_release_install",
    "publish",
]
V250_GATES = V249_GATES
CURRENT_SIMPLE_VERSIONS = {"V2.49", "V2.50"}
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
CANDIDATE_RE = re.compile(r"^develops/[a-z0-9][a-z0-9._-]*$")
BRANCH_RE = re.compile(r"^codex/[A-Za-z0-9._/-]+$")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _load_profile(version: str) -> dict[str, Any]:
    path = PROFILE_BY_VERSION.get(version)
    if path is None:
        raise ValueError(f"unsupported release version: {version}")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"release profile is missing or unsafe: {version}")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"release profile is unreadable: {version}") from exc
    simple_mode = (
        version in {"V2.48", *CURRENT_SIMPLE_VERSIONS}
        and isinstance(value, dict)
        and value.get("release_mode") == "skill_simple"
    )
    expected_fields = (
        V249_FIELDS
        if simple_mode and version in CURRENT_SIMPLE_VERSIONS
        else SIMPLE_FIELDS
        if simple_mode
        else REQUIRED_FIELDS
    )
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise ValueError(f"release profile fields drift: {version}")
    if simple_mode and version == "V2.48":
        if (
            value["schema_version"] != SCHEMA_VERSION
            or value["version"] != version
            or value["status"] != "active"
            or value["external_writes_allowed"] is not False
            or value["approval_model"]
            != "single_human_before_external_write"
            or value["release_gates"] != SIMPLE_GATES
            or value["required_status_checks"]
            != ["check-macos", "release-asset-gate"]
            or value["published_before"] != "V2.46"
            or value["tag"] != "v2.48"
            or value["candidate_branch"] != "codex/v2.48-release"
            or value["profile_path"]
            != "references/profiles/goal-teams-self-release-v2.48.md"
            or value["release_title"] != "Goal Teams V2.48"
            or value["release_body"]
            != (
                "Goal Teams V2.48. "
                "See release/current/README.md in the tagged source."
            )
            or value["tag_message"] != "Goal Teams V2.48"
            or value["snapshot_schema_version"]
            != "goal-teams-release-snapshot-v2.40"
            or value["files_manifest_format"]
            != "sha256-mode-size-path-v1"
        ):
            raise ValueError(f"release simple policy drift: {version}")
        profile_path = (ROOT / value["profile_path"]).resolve()
        try:
            profile_path.relative_to(ROOT)
        except ValueError as exc:
            raise ValueError(
                f"release profile path escapes root: {version}"
            ) from exc
        if not profile_path.is_file() or profile_path.is_symlink():
            raise ValueError(
                f"release profile dependency is unsafe: {value['profile_path']}"
            )
        projected = deepcopy(value)
        projected["closure_state"] = "ready_for_local_validation"
        return {
            **projected,
            "config_path": path.relative_to(ROOT).as_posix(),
            "config_sha256": hashlib.sha256(raw).hexdigest(),
            "config_canonical_sha256": hashlib.sha256(
                _canonical_bytes(value)
            ).hexdigest(),
        }
    if simple_mode and version in CURRENT_SIMPLE_VERSIONS:
        expected_branch = {
            "V2.49": "codex/v2.49-simplification",
            "V2.50": "codex/v2.50-release",
        }[version]
        lowercase_version = version.lower()
        if (
            value["schema_version"] != SCHEMA_VERSION
            or value["version"] != version
            or value["status"] != "active"
            or value["external_writes_allowed"] is not False
            or value["approval_model"] != "project_start_authorization_reused"
            or value["release_gates"] != V249_GATES
            or value["required_status_checks"]
            != ["check-macos", "release-asset-gate"]
            or value["published_before"] != "V2.48"
            or value["tag"] != lowercase_version
            or value["candidate_branch"] != expected_branch
            or value["profile_path"]
            != f"references/profiles/goal-teams-self-release-{lowercase_version}.md"
            or value["release_title"] != f"Goal Teams {version}"
            or value["release_body"]
            != (
                f"Goal Teams {version}. "
                "See release/current/README.md in the tagged source."
            )
            or value["tag_message"] != f"Goal Teams {version}"
            or value["snapshot_schema_version"]
            != "goal-teams-release-snapshot-v2.40"
            or value["files_manifest_format"] != "sha256-mode-size-path-v1"
            or value["development_gate_policy"]
            != "tdd_and_incremental_only"
            or value["release_readiness_policy"]
            != "released_identity_final_full_and_security_once"
            or value["s2_policy"]
            != "single_build_release_versions_no_reproducibility_or_security"
            or value["s3_policy"]
            != "large_release_only_after_current_s1_and_repository_boundary"
            or value["s4_authorization_source"]
            != "project_start_authorization_receipt"
            or value["repository_boundary_gate"]
            != "repository_boundary_compliance"
            or value["runtime_transition_assurance"] != "I1_correlated"
            or value["git_transport"] != "ssh_only"
            or value["public_asset_map_path"]
            != (
                f"references/current/generations/{version}/contracts/"
                "public-asset-map.json"
            )
        ):
            raise ValueError(f"release simple policy drift: {version}")
        for relative in (value["profile_path"], value["public_asset_map_path"]):
            dependency = (ROOT / relative).resolve()
            try:
                dependency.relative_to(ROOT)
            except ValueError as exc:
                raise ValueError(
                    f"release profile path escapes root: {version}"
                ) from exc
            if not dependency.is_file() or dependency.is_symlink():
                raise ValueError(
                    f"release profile dependency is unsafe: {relative}"
                )
        projected = deepcopy(value)
        projected["closure_state"] = "ready_for_local_validation"
        return {
            **projected,
            "config_path": path.relative_to(ROOT).as_posix(),
            "config_sha256": hashlib.sha256(raw).hexdigest(),
            "config_canonical_sha256": hashlib.sha256(
                _canonical_bytes(value)
            ).hexdigest(),
        }
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["protocol_version"] != PROTOCOL_VERSION
        or value["version"] != version
        or VERSION_RE.fullmatch(version) is None
        or value["tag"] != f"v{version[1:]}"
        or value["goal_teams_work"] != f"GoalTeamsWork-{version}"
        or value["release_title"] != f"Goal Teams {version}"
        or value["tag_message"] != f"Goal Teams {version}"
        or value["workflow_display_prefix"]
        != f"Goal Teams {version} release "
        or value["release_body"]
        != (
            f"Goal Teams {version}. "
            "See release/current/README.md in the tagged source."
        )
        or value["snapshot_schema_version"]
        != "goal-teams-release-snapshot-v2.40"
        or value["files_manifest_format"] != "sha256-mode-size-path-v1"
        or value["status"] not in {"active", "historical_replay"}
        or value["goal_teams_work_location"]
        not in {"candidate", "workspace_docs"}
        or CANDIDATE_RE.fullmatch(str(value["candidate_location"])) is None
        or BRANCH_RE.fullmatch(str(value["candidate_branch"])) is None
        or ".." in str(value["candidate_branch"]).split("/")
        or value["owner_run_id"]
        != f"RUN-{version.replace('.', '')}-LEAD"
        or value["profile_path"]
        != f"references/profiles/goal-teams-self-release-{version.lower()}.md"
        or value["public_scan_baseline"]
        != f"references/public-release-scan-baseline-{version.lower()}.json"
        or value["close_schema_version"]
        != f"goal-teams-release-close-{version.lower()}"
        or not isinstance(value["external_writes_allowed"], bool)
        or not isinstance(value["legacy_recovery_required"], bool)
    ):
        raise ValueError(f"release profile identity drift: {version}")
    expected_status = (
        "active"
        if version in {"V2.46", ACTIVE_VERSION}
        else "historical_replay"
    )
    expected_external_writes = version == "V2.46"
    expected_predecessor = PREDECESSOR_BY_VERSION.get(version)
    host_required = version in HOST_ACCEPTANCE_VERSIONS
    if (
        value["status"] != expected_status
        or value["external_writes_allowed"] is not expected_external_writes
        or value["published_before"] != expected_predecessor
        or value["legacy_recovery_required"] is not (version == "V2.40")
    ):
        raise ValueError(f"release profile lifecycle is inconsistent: {version}")
    if (
        host_required
        and (
            not isinstance(value["host_acceptance"], dict)
            or set(value["host_acceptance"])
            != {
                "schema_version",
                "algorithm",
                "signature_domain",
                "issuer",
                "public_key_hex",
                "key_id",
            }
            or value["host_acceptance"]["schema_version"]
            != "goal-teams-external-host-acceptance-v2"
            or value["host_acceptance"]["algorithm"] != "Ed25519"
            or value["host_acceptance"]["signature_domain"]
            != (
                f"goal-teams/{version.lower()}/cp05/"
                "host-acceptance/ed25519/v1"
            )
            or value["host_acceptance"]["issuer"]
            != "goal-teams-trusted-host"
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str(value["host_acceptance"]["public_key_hex"]),
            )
            is None
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str(value["host_acceptance"]["key_id"]),
            )
            is None
            or hashlib.sha256(
                bytes.fromhex(value["host_acceptance"]["public_key_hex"])
            ).hexdigest()
            != value["host_acceptance"]["key_id"]
        )
    ):
        raise ValueError(f"release host profile is inconsistent: {version}")
    if not host_required and value.get("host_acceptance") is not None:
        raise ValueError(f"release host profile is inconsistent: {version}")
    for relative in (value["profile_path"], value["public_scan_baseline"]):
        target = (ROOT / relative).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError as exc:
            raise ValueError(f"release profile path escapes root: {version}") from exc
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"release profile dependency is unsafe: {relative}")
    projected = deepcopy(value)
    return {
        **projected,
        "config_path": path.relative_to(ROOT).as_posix(),
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "config_canonical_sha256": hashlib.sha256(
            _canonical_bytes(value)
        ).hexdigest(),
    }


def supported_versions() -> tuple[str, ...]:
    return tuple(PROFILE_BY_VERSION)


def release_config(version: str) -> dict[str, Any]:
    return deepcopy(_load_profile(version))


def active_release_config() -> dict[str, Any]:
    return release_config(ACTIVE_VERSION)
