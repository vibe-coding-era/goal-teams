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
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

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
TEST_CASE_CONTRACTS = (
    ROOT
    / "tests"
    / "v23"
    / "fixtures"
    / "v240"
    / "release-lifecycle-contracts.json"
)
LOCAL_IGNORED_TEST_CASE_CONTRACTS = V240_SPEC_ROOT / "test-case-contracts.json"

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
            "name": "goal-teams-promotion-lock-V2.40-bbbbbbbbbbbb",
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

    return {
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
        promotion_contract = json.loads(PROMOTION_STATE_CONTRACT.read_text())
        test_contracts = json.loads(TEST_CASE_CONTRACTS.read_text())
        if LOCAL_IGNORED_TEST_CASE_CONTRACTS.is_file():
            self.assertEqual(
                TEST_CASE_CONTRACTS.read_bytes(),
                LOCAL_IGNORED_TEST_CASE_CONTRACTS.read_bytes(),
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
        authorization = "Author" + "ization: Be" + "arer "
        synthetic = "-".join(("sk", "proj", "private", "fixture"))
        private_record = {
            "surface_kind": "private_log",
            "ignored": True,
            "path": "docs/private/release-run.json",
            "fields": {
                "authorization": authorization + synthetic,
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
            "fields": {"authorization": "private-fixture"},
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
        authorization = "Author" + "ization: Be" + "arer "
        synthetic = "-".join(("sk", "proj", "fixture", "not-a-secret"))
        self.policy_failure(
            "E_V240_PUBLIC_SECRET",
            lambda: scan({"README.md": authorization + synthetic}),
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
