from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load("goal_teams_v240_release_cli", ROOT / "scripts/release/release.py")
adapter_module = _load(
    "goal_teams_v240_github_adapter_cli",
    ROOT / "scripts/release/github_adapter.py",
)


COMMIT = "b" * 40
BASE = "a" * 40


def _release_tagger(
    name: str = "Goal Teams Release Maintainer",
    email: str = "release-maintainer@goal-teams.org",
) -> dict[str, str]:
    identity = {"name": name, "email": email}
    return {
        **identity,
        "identity_sha256": adapter_module._canonical_sha256(identity),
    }


def _release_scope(candidate: str) -> tuple[dict[str, object], dict[str, object]]:
    spec_root = ROOT / "GoalTeamsWork-V2.40" / "versions" / "V2.40" / "spec"
    route_path = spec_root / "current-route-receipt.json"
    if not route_path.is_file():
        raise unittest.SkipTest(
            "V2.40 scope tests require the canonical local-only Goal Teams workspace"
        )
    route = json.loads(route_path.read_text(encoding="utf-8"))
    spec_rows = [
        {"path": name, "sha256": release._sha256_file(spec_root / name)}
        for name in (
            "PRD.md",
            "acceptance.md",
            "architecture-design.md",
            "requirement-card.md",
            "test-plan.md",
            "promotion-state-contract.json",
        )
    ]
    return (
        {
            "repository": "vibe-coding-era/goal-teams",
            "version": "V2.40",
            "candidate_commit": candidate,
            "owner_run_id": "RUN-V240-LEAD",
            "locked_scope": route["locked_scope"],
            "route_receipt_sha256": release._sha256_file(route_path),
            "spec_sha256": release._canonical_json_sha256(spec_rows),
            "done_criteria": ["all gates", "five-point identity"],
        },
        route,
    )


def _adapter(workspace: Path):
    return adapter_module.GitHubAdapter(
        source_root=ROOT,
        workspace_root=workspace,
        repository="vibe-coding-era/goal-teams",
        version="V2.40",
        candidate_commit=COMMIT,
        base_main_commit=BASE,
        authority={},
        execute_external_writes=False,
    )


def _workflow_identity(blob: str = "d" * 40) -> dict[str, object]:
    return {
        "workflow_id": 240,
        "source_path": ".github/workflows/release-gate.yml",
        "source_blob_sha": blob,
    }


def _write_assets(workspace: Path) -> dict[str, Path]:
    root = workspace / "release" / "versions" / "V2.40"
    artifacts = root / "_artifacts"
    artifacts.mkdir(parents=True)
    values = {
        "goal-teams-V2.40.tar.gz": b"tar-v240",
        "SHA256SUMS": b"sum-v240",
        "_release.json": b"release-v240",
        "_files.sha256": b"files-v240",
    }
    paths: dict[str, Path] = {}
    for name, data in values.items():
        path = artifacts / name if name in {"goal-teams-V2.40.tar.gz", "SHA256SUMS"} else root / name
        path.write_bytes(data)
        paths[name] = path
    return paths


def _release_asset_fixture(
    adapter, asset_ids: tuple[int, int, int, int] = (2401, 2402, 2403, 2404)
) -> tuple[list[dict[str, object]], str]:
    local_assets = adapter._local_asset_set()
    remote_assets: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    for asset_id, (name, sealed) in zip(asset_ids, sorted(local_assets.items())):
        remote_assets.append(
            {
                "id": asset_id,
                "name": name,
                "size": sealed["size"],
                "digest": f"sha256:{sealed['sha256']}",
            }
        )
        identity_rows.append(
            {
                "name": name,
                "asset_id": asset_id,
                "size": sealed["size"],
                "sha256": sealed["sha256"],
            }
        )
    return remote_assets, adapter_module._canonical_sha256(identity_rows)


def _final_main_ruleset_payload() -> dict[str, object]:
    return {
        "name": "goal-teams-main-protection",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [
            {"actor_id": 240, "actor_type": "User", "bypass_mode": "always"}
        ],
        "conditions": {
            "ref_name": {"include": ["refs/heads/main"], "exclude": []}
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": True,
                    "required_approving_review_count": 1,
                    "required_review_thread_resolution": True,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [
                        {"context": "check-ubuntu"},
                        {"context": "check-macos"},
                        {"context": "release-asset-gate"},
                    ],
                },
            },
        ],
    }


def _remote_mutation_guard(
    operation_id: str, action: str
) -> dict[str, object]:
    promotion = _final_main_ruleset_payload()
    permanent_tag = {
        "name": "goal-teams-tag-protection",
        "target": "tag",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {"include": ["refs/tags/v*"], "exclude": []}
        },
        "rules": [
            {"type": "deletion"},
            {
                "type": "update",
                "parameters": {"update_allows_fetch_and_merge": False},
            },
        ],
    }

    def identity(ruleset_id: int, payload: dict[str, object]) -> dict[str, object]:
        normalized = adapter_module.normalize_ruleset(payload)
        return {
            "ruleset_id": ruleset_id,
            "ruleset_name": normalized["name"],
            "ruleset_sha256": adapter_module._canonical_sha256(normalized),
            "ruleset": normalized,
        }

    checkpoint_id = operation_id.split(".", 1)[0]
    allowed_main = (
        [COMMIT]
        if checkpoint_id == "CP17" and action != "main_promote"
        else [BASE]
    )
    return {
        "schema_version": "goal-teams-v2.40-remote-mutation-guard-v1",
        "operation_id": operation_id,
        "action": action,
        "main_ref": "refs/heads/main",
        "allowed_main_commits": allowed_main,
        "temporary_main_lock": identity(24014, promotion),
        "permanent_tag_ruleset": identity(24015, permanent_tag),
    }


class V240ReleaseCliSecurityTests(unittest.TestCase):
    def test_mutation_edge_guard_blocks_post_observe_ruleset_drift_without_write(
        self,
    ) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        operation_id = "CP16.draft_create"
        action = "draft_create"
        guard = _remote_mutation_guard(operation_id, action)
        parameters = {"_remote_mutation_guard": guard}
        observed = {"draft": False}

        def release_json(_release_id=None):
            observed["draft"] = True
            return None

        def ruleset_by_name(name: str):
            self.assertTrue(
                observed["draft"],
                "mutation-edge ruleset read must occur after the action observe",
            )
            for key in ("temporary_main_lock", "permanent_tag_ruleset"):
                identity = guard[key]
                if name == identity["ruleset_name"]:
                    ruleset_id = identity["ruleset_id"]
                    if key == "permanent_tag_ruleset":
                        ruleset_id += 1
                    return {"id": ruleset_id, **identity["ruleset"]}
            return None

        with mock.patch.object(
            adapter, "_release_json", side_effect=release_json
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_ruleset_by_name", side_effect=ruleset_by_name
        ), mock.patch.object(
            adapter_module, "_run"
        ) as mutation:
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id=operation_id,
                    action=action,
                    expected_before={
                        "targetCommitish": COMMIT,
                        "name": adapter_module.CANONICAL_RELEASE_TITLE,
                        "body": adapter_module.CANONICAL_RELEASE_BODY,
                    },
                    parameters=parameters,
                )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_REMOTE_RESOURCE_CONFLICT",
        )
        self.assertEqual(
            caught.exception.receipt["external_side_effect_count"], 0
        )
        mutation.assert_not_called()

    def test_mutation_edge_guard_accepts_only_full_ruleset_ids_and_main_lease(
        self,
    ) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        operation_id = "CP15.tag_push"
        action = "tag_push"
        guard = _remote_mutation_guard(operation_id, action)

        def ruleset_by_name(name: str):
            for key in ("temporary_main_lock", "permanent_tag_ruleset"):
                identity = guard[key]
                if name == identity["ruleset_name"]:
                    return {"id": identity["ruleset_id"], **identity["ruleset"]}
            return None

        with mock.patch.object(
            adapter, "_ruleset_by_name", side_effect=ruleset_by_name
        ), mock.patch.object(adapter, "_remote_ref", return_value=BASE):
            receipt = adapter._validate_remote_mutation_guard(
                operation_id,
                action,
                {"_remote_mutation_guard": guard},
            )
        self.assertEqual(receipt["main_commit"], BASE)
        self.assertEqual(receipt["temporary_main_lock"]["ruleset_id"], 24014)
        self.assertEqual(receipt["permanent_tag_ruleset"]["ruleset_id"], 24015)

        missing_payload = json.loads(json.dumps(guard))
        del missing_payload["temporary_main_lock"]["ruleset"]
        with self.assertRaises(adapter_module.AdapterError) as caught:
            adapter._validate_remote_mutation_guard(
                operation_id,
                action,
                {"_remote_mutation_guard": missing_payload},
            )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_ADAPTER_EXPECTED_BEFORE",
        )

    def test_cp01_clean_root_uses_read_only_stash_attestation_and_isolated_clone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            git_env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_")
            }

            def git(*arguments: str) -> bytes:
                result = subprocess.run(
                    ["git", "--no-replace-objects", *arguments],
                    cwd=workspace,
                    env=git_env,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    (result.stdout + result.stderr).decode("utf-8", errors="replace"),
                )
                return result.stdout

            git("init", "-b", "main")
            git("config", "user.name", "Goal Teams test")
            git("config", "user.email", "goal-teams-test@example.invalid")
            (workspace / ".gitignore").write_text(
                "/docs/\n/develops/\n", encoding="utf-8"
            )
            (workspace / "tracked.txt").write_text("base\n", encoding="utf-8")
            git("add", ".gitignore", "tracked.txt")
            git("commit", "-m", "base")
            base_commit = git("rev-parse", "HEAD").decode().strip()
            git("update-ref", "refs/remotes/origin/main", base_commit)
            git("switch", "-c", "old-root")
            (workspace / "tracked.txt").write_text(
                "base\nprivate work\n", encoding="utf-8"
            )
            untracked = workspace / "notes" / "private.txt"
            untracked.parent.mkdir()
            untracked.write_text("private untracked\n", encoding="utf-8")

            recovery_root = workspace / "docs" / "recovery" / "pre-v2.40"
            bundle = recovery_root / "root-old-worktree"
            bundle.mkdir(parents=True)
            required = {
                "receipt": bundle / "receipt.json",
                "staged": bundle / "staged.patch",
                "unstaged": bundle / "unstaged.patch",
                "status": bundle / "status.txt",
                "archive": bundle / "untracked.tar",
                "manifest": bundle / "untracked-manifest.json",
            }
            required["staged"].write_bytes(git("diff", "--cached", "--binary"))
            required["unstaged"].write_bytes(git("diff", "--binary"))
            required["status"].write_bytes(
                git(
                    "status",
                    "--porcelain=v2",
                    "--branch",
                    "--untracked-files=normal",
                )
            )
            payload = untracked.read_bytes()
            manifest = [
                {
                    "path": "notes/private.txt",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ]
            required["manifest"].write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            with tarfile.open(required["archive"], "w") as archive:
                archive.add(untracked, arcname="notes/private.txt", recursive=False)
            status_entries = [
                line
                for line in required["status"].read_text().splitlines()
                if line and not line.startswith("#")
            ]
            receipt = {
                "schema_version": "goal-teams-worktree-recovery-v1",
                "worktree": str(workspace),
                "label": "root-old-worktree",
                "head": base_commit,
                "branch": "old-root",
                "upstream": None,
                "status_entry_count": len(status_entries),
                "staged_patch_sha256": release._sha256_file(required["staged"]),
                "unstaged_patch_sha256": release._sha256_file(required["unstaged"]),
                "untracked_archive_sha256": release._sha256_file(required["archive"]),
                "untracked_count": 1,
            }
            required["receipt"].write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            rehearsal_path = recovery_root / "restore-rehearsal-receipt.json"
            rehearsal_path.write_text(
                json.dumps(
                    {
                        "schema_version": "goal-teams-recovery-rehearsal-v1",
                        "passed": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stash_message = "v240-read-only-recovery"
            git("stash", "push", "--include-untracked", "-m", stash_message)
            stash_commit = git("rev-parse", "refs/stash").decode().strip()
            git("switch", "main")

            intent = {
                "intent_id": "INT-V240-CP01-LEGACY-RECOVERY",
                "operation_id": "CP01.legacy_recovery",
                "action": "local_validate",
                "created_at": "2026-07-16T00:00:00Z",
            }
            prior_binding = {
                "repository": "vibe-coding-era/goal-teams",
                "version": "V2.40",
                "candidate_commit": base_commit,
                "operation_id": "CP01.legacy_recovery",
                "action": "local_validate",
            }
            intent["inputs_sha256"] = release._canonical_json_sha256(
                prior_binding
            )
            intent["idempotency_key"] = release._canonical_json_sha256(
                {
                    "transition_map": "goal-teams-v2.40-transition-map-v1",
                    **prior_binding,
                }
            )
            readback = {
                "classification": "exact",
                "source": "local_filesystem",
                "observed_at": "2026-07-16T00:00:01Z",
                "details": {
                    "recovery_bundles": {
                        "root-old-worktree": {
                            "receipt_sha256": release._sha256_file(
                                required["receipt"]
                            ),
                            "manifest_sha256": release._sha256_file(
                                required["manifest"]
                            ),
                            "status_sha256": release._sha256_file(
                                required["status"]
                            ),
                            "status_entry_count": len(status_entries),
                            "untracked_count": 1,
                        }
                    },
                    "restore_rehearsal_sha256": release._sha256_file(
                        rehearsal_path
                    ),
                },
            }
            readback["state_sha256"] = release._canonical_json_sha256(
                readback["details"]
            )
            operation_receipt = release._canonical_json_sha256(
                {"intent": intent, "readback": readback}
            )
            checkpoint_receipt = release._canonical_json_sha256(
                [operation_receipt]
            )
            prior_relative = (
                "docs/release-state/V2.40/history/pre-root-recovery.json"
            )
            prior_path = workspace / prior_relative
            prior_path.parent.mkdir(parents=True)
            prior_path.write_text(
                json.dumps(
                    {
                        "repository": "vibe-coding-era/goal-teams",
                        "version": "V2.40",
                        "base_main_commit": base_commit,
                        "candidate_commit": base_commit,
                        "transition_map_version": "goal-teams-v2.40-transition-map-v1",
                        "checkpoints": {
                            "CP01": {
                                "checkpoint_id": "CP01",
                                "status": "passed",
                                "operations": [
                                    {
                                        "operation_id": "CP01.legacy_recovery",
                                        "status": "passed",
                                        "intent": intent,
                                        "readback": readback,
                                        "receipt_sha256": operation_receipt,
                                    }
                                ],
                                "receipt_sha256": checkpoint_receipt,
                            }
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            state = {
                "repository": "vibe-coding-era/goal-teams",
                "version": "V2.40",
                "base_main_commit": base_commit,
                "candidate_commit": base_commit,
            }

            with mock.patch.object(release, "_workspace_root", return_value=workspace):
                attestation = release.build_root_recovery_stash_attestation(
                    state,
                    stash_commit=stash_commit,
                    stash_message=stash_message,
                    prior_state_archive_path=prior_relative,
                )
            attestation_path = (
                workspace
                / "docs"
                / "release-state"
                / "V2.40"
                / "root-recovery-stash.json"
            )
            attestation_path.write_text(
                json.dumps(attestation, indent=2) + "\n", encoding="utf-8"
            )

            control_before = release._repository_control_snapshot(workspace)
            with mock.patch.object(
                release, "_run_git_unchecked", wraps=release._run_git_unchecked
            ) as unchecked, mock.patch.object(
                release, "_run_fixed", wraps=release._run_fixed
            ) as fixed:
                validated = release._validate_root_recovery_stash_attestation(
                    workspace,
                    state,
                    attestation_path,
                    required=required,
                    receipt=receipt,
                    manifest=manifest,
                    rehearsal_path=rehearsal_path,
                )
                replay = release._replay_recovery_bundle_live(
                    workspace=workspace,
                    label="root-old-worktree",
                    receipt=receipt,
                    files=required,
                    manifest_rows={row["path"]: row for row in manifest},
                )
            self.assertEqual(validated["stash_commit"], stash_commit)
            self.assertEqual(
                replay["method"], "isolated_clone_patch_and_untracked_replay"
            )
            self.assertEqual(
                control_before, release._repository_control_snapshot(workspace)
            )
            commands = [
                tuple(call.args[0])
                for recorder in (unchecked, fixed)
                for call in recorder.call_args_list
            ]
            forbidden = {
                ("stash", "apply"),
                ("stash", "drop"),
                ("worktree", "add"),
                ("worktree", "remove"),
            }
            for command in commands:
                words = tuple(word for word in command if word != "git")
                self.assertNotIn(words[:2], forbidden)
                self.assertNotIn("update-ref", words)

            extra = dict(attestation)
            extra["caller_selected_path"] = "/tmp/forged"
            attestation_path.write_text(
                json.dumps(extra, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaises(release.PolicyError) as caught:
                release._validate_root_recovery_stash_attestation(
                    workspace,
                    state,
                    attestation_path,
                    required=required,
                    receipt=receipt,
                    manifest=manifest,
                    rehearsal_path=rehearsal_path,
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_RECOVERY_STASH_ATTESTATION",
            )

            git("update-ref", "refs/remotes/origin/main", base_commit)
            marker = workspace / "docs" / "external-diff-ran"
            helper = workspace / "docs" / "external-diff-helper.sh"
            helper.write_text(
                f"#!/bin/sh\nprintf ran > {marker}\n",
                encoding="utf-8",
            )
            helper.chmod(0o755)
            git("config", "diff.external", str(helper))
            with mock.patch.object(
                release, "_workspace_root", return_value=workspace
            ):
                with self.assertRaises(release.PolicyError) as caught:
                    release.build_root_recovery_stash_attestation(
                        state,
                        stash_commit=stash_commit,
                        stash_message=stash_message,
                        prior_state_archive_path=prior_relative,
                    )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_GIT_OBJECT_GRAPH",
            )
            self.assertFalse(marker.exists())
            git("config", "--unset", "diff.external")

            git("config", "extensions.worktreeConfig", "true")
            git("config", "--worktree", "core.fsmonitor", str(helper))
            with mock.patch.object(
                release, "_workspace_root", return_value=workspace
            ):
                with self.assertRaises(release.PolicyError) as caught:
                    release.build_root_recovery_stash_attestation(
                        state,
                        stash_commit=stash_commit,
                        stash_message=stash_message,
                        prior_state_archive_path=prior_relative,
                    )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_GIT_OBJECT_GRAPH",
            )
            self.assertFalse(marker.exists())
            git("config", "--worktree", "--unset", "core.fsmonitor")
            git("config", "--unset", "extensions.worktreeConfig")

            included_config = workspace / "docs" / "included-git-config"
            included_config.write_text(
                f"[core]\n\tfsmonitor = {helper}\n", encoding="utf-8"
            )
            git("config", "include.path", str(included_config))
            with mock.patch.object(
                release, "_workspace_root", return_value=workspace
            ):
                with self.assertRaises(release.PolicyError) as caught:
                    release.build_root_recovery_stash_attestation(
                        state,
                        stash_commit=stash_commit,
                        stash_message=stash_message,
                        prior_state_archive_path=prior_relative,
                    )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_GIT_OBJECT_GRAPH",
            )
            self.assertFalse(marker.exists())
            git("config", "--unset", "include.path")

            def mutate_control_then_fail(*_args, **_kwargs):
                git("update-ref", "refs/heads/cp01-injected", stash_commit)
                raise release.PolicyError("E_TEST", "synthetic CP01 failure")

            with mock.patch.object(
                release, "_workspace_root", return_value=workspace
            ), mock.patch.object(
                release,
                "_execute_local_operation_unchecked",
                side_effect=mutate_control_then_fail,
            ):
                with self.assertRaises(release.PolicyError) as caught:
                    release._execute_local_operation(
                        "CP01.legacy_recovery", state, {}, prior_path
                    )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_RECOVERY_BUNDLE",
            )

            forged_stash = dict(attestation)
            forged_stash["stash_commit"] = base_commit
            attestation_path.write_text(
                json.dumps(forged_stash, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaises(release.PolicyError) as caught:
                release._validate_root_recovery_stash_attestation(
                    workspace,
                    state,
                    attestation_path,
                    required=required,
                    receipt=receipt,
                    manifest=manifest,
                    rehearsal_path=rehearsal_path,
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_RECOVERY_STASH_ATTESTATION",
            )

            attestation_path.write_text(
                json.dumps(attestation, indent=2) + "\n", encoding="utf-8"
            )
            git("update-ref", "refs/remotes/origin/main", stash_commit)
            with self.assertRaises(release.PolicyError) as caught:
                release._validate_root_recovery_stash_attestation(
                    workspace,
                    state,
                    attestation_path,
                    required=required,
                    receipt=receipt,
                    manifest=manifest,
                    rehearsal_path=rehearsal_path,
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_RECOVERY_STASH_ATTESTATION",
            )

    def test_github_transport_is_fixed_and_rejects_forks_rewrites_and_enterprise_host(self) -> None:
        canonical = "git@github.com:vibe-coding-era/goal-teams.git"

        def values(_root, argv, *, allow_missing=False):
            key = tuple(argv)
            if key == ("config", "--show-origin", "--get-regexp", r"^url\."):
                return []
            if key == ("config", "--get-all", "remote.origin.url"):
                return [canonical]
            if key == ("config", "--get-all", "remote.origin.pushurl"):
                return []
            if key in {
                ("remote", "get-url", "--all", "origin"),
                ("remote", "get-url", "--push", "--all", "origin"),
            }:
                return [canonical]
            raise AssertionError(key)

        with mock.patch.object(adapter_module, "_git_config_values", side_effect=values):
            receipt = adapter_module.validate_github_transport(
                ROOT, "vibe-coding-era/goal-teams"
            )
        self.assertEqual(receipt["api_host"], "github.com")
        self.assertEqual(receipt["url_rewrite_count"], 0)

        def fork_origin(_root, argv, *, allow_missing=False):
            if tuple(argv) == ("config", "--get-all", "remote.origin.url"):
                return ["git@github.com:someone/goal-teams.git"]
            return values(_root, argv, allow_missing=allow_missing)

        with mock.patch.object(adapter_module, "_git_config_values", side_effect=fork_origin):
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter_module.validate_github_transport(
                    ROOT, "vibe-coding-era/goal-teams"
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_GITHUB_TRANSPORT_BINDING")

        def fork_push(_root, argv, *, allow_missing=False):
            if tuple(argv) == ("config", "--get-all", "remote.origin.pushurl"):
                return ["git@github.com:someone/goal-teams.git"]
            return values(_root, argv, allow_missing=allow_missing)

        with mock.patch.object(adapter_module, "_git_config_values", side_effect=fork_push):
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter_module.validate_github_transport(
                    ROOT, "vibe-coding-era/goal-teams"
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_GITHUB_TRANSPORT_BINDING")

        def rewritten(_root, argv, *, allow_missing=False):
            if tuple(argv) == ("config", "--show-origin", "--get-regexp", r"^url\."):
                return ["file:/tmp/.gitconfig url.ssh://fork/.insteadof https://github.com/"]
            return values(_root, argv, allow_missing=allow_missing)

        with mock.patch.object(adapter_module, "_git_config_values", side_effect=rewritten):
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter_module.validate_github_transport(
                    ROOT, "vibe-coding-era/goal-teams"
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_GITHUB_URL_REWRITE")

        with mock.patch.dict(os.environ, {"GH_HOST": "github.enterprise.test"}):
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter_module.validate_github_transport(
                    ROOT, "vibe-coding-era/goal-teams"
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_GITHUB_HOST_BINDING")

    def test_rest_ref_is_primary_and_origin_divergence_fails_closed(self) -> None:
        adapter = _adapter(ROOT)
        with mock.patch.object(adapter, "_validate_transport_authority"), mock.patch.object(
            adapter,
            "_rest_ref",
            return_value={"ref": "refs/tags/v2.40", "object": {"type": "tag", "sha": "c" * 40}},
        ), mock.patch.object(
            adapter, "_ls_remote_ref", side_effect=["c" * 40, COMMIT]
        ), mock.patch.object(
            adapter,
            "_gh_api",
            return_value={
                "tag": "v2.40",
                "message": adapter_module.CANONICAL_TAG_MESSAGE + "\n",
                "object": {"type": "commit", "sha": COMMIT},
                "tagger": {
                    "name": _release_tagger()["name"],
                    "email": _release_tagger()["email"],
                    "date": "2026-07-17T00:00:00Z",
                },
            },
        ):
            identity = adapter._remote_tag_identity("v2.40")
        self.assertEqual(identity["peeled_commit"], COMMIT)
        self.assertEqual(identity["message"], adapter_module.CANONICAL_TAG_MESSAGE)
        self.assertEqual(
            identity["tagger_identity_sha256"],
            _release_tagger()["identity_sha256"],
        )

        with mock.patch.object(adapter, "_validate_transport_authority"), mock.patch.object(
            adapter,
            "_rest_ref",
            return_value={"ref": "refs/heads/main", "object": {"type": "commit", "sha": COMMIT}},
        ), mock.patch.object(adapter, "_ls_remote_ref", return_value=BASE):
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter._remote_ref("refs/heads/main")
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_GITHUB_REF_DIVERGENCE")

    def test_post_release_dispatch_intent_adopts_unique_run_and_never_redispatches(self) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        adapter._fixed_workflow_identity = mock.Mock(
            return_value=_workflow_identity()
        )
        intent = "9" * 64
        title = f"Goal Teams V2.40 release {intent}"
        workflow = ".github/workflows/release-gate.yml"
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": workflow,
            "workflow_id": 240,
            "workflow_blob_sha": "d" * 40,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }

        def run(run_id=24017, *, title_value=title, conclusion="success"):
            return {
                "id": run_id,
                "run_attempt": 1,
                "head_sha": COMMIT,
                "path": workflow,
                "workflow_id": 240,
                "event": "workflow_dispatch",
                "actor": {"id": 240},
                "triggering_actor": {"id": 240},
                "display_title": title_value,
                "conclusion": conclusion,
                "created_at": "2026-07-14T09:00:00Z",
            }

        jobs = {
            "jobs": [
                {"name": name, "conclusion": "success"}
                for name in approval["required_jobs"]
            ]
        }
        parameters = {"_release_intent": intent, "dispatch": True, "workflow": workflow}
        with mock.patch.object(adapter, "_gh_api", return_value={"workflow_runs": []}):
            absent = adapter.observe(
                operation_id="CP17.post_release_ci",
                action="post_release_ci",
                expected_before={"ci_approval": approval},
                parameters=parameters,
            )
        self.assertEqual(absent["classification"], "absent")

        with mock.patch.object(
            adapter, "_gh_api", return_value={"workflow_runs": []}
        ), mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
            adapter, "_validate_remote_mutation_guard", return_value={}
        ), mock.patch.object(
            adapter_module,
            "_run",
            return_value=subprocess.CompletedProcess(["gh"], 0, "", ""),
        ) as dispatch:
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP17.post_release_ci",
                    action="post_release_ci",
                    expected_before={"ci_approval": approval},
                    parameters=parameters,
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CI_PENDING")
        self.assertEqual(caught.exception.receipt["external_side_effect_count"], 1)
        dispatch.assert_called_once()
        self.assertIn(f"release_intent={intent}", dispatch.call_args.args[0])

        wrong = run(title_value=f"Goal Teams V2.40 release {'8' * 64}")
        with mock.patch.object(adapter, "_gh_api", return_value={"workflow_runs": [wrong]}):
            self.assertEqual(
                adapter.observe(
                    operation_id="CP17.post_release_ci",
                    action="post_release_ci",
                    expected_before={"ci_approval": approval},
                    parameters=parameters,
                )["classification"],
                "absent",
            )

        with mock.patch.object(adapter, "_gh_api", return_value={"workflow_runs": [run(1), run(2)]}):
            conflict = adapter.observe(
                operation_id="CP17.post_release_ci",
                action="post_release_ci",
                expected_before={"ci_approval": approval},
                parameters=parameters,
            )
        self.assertEqual(conflict["classification"], "conflict")

        pending = run(conclusion=None)
        with mock.patch.object(
            adapter, "_gh_api", side_effect=[{"workflow_runs": [pending]}, pending, jobs]
        ), mock.patch.object(
            adapter_module,
            "_run",
            return_value=subprocess.CompletedProcess(["git"], 0, "d" * 40 + "\n", ""),
        ) as mutate, mock.patch.object(adapter, "_require_write_authority"):
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP17.post_release_ci",
                    action="post_release_ci",
                    expected_before={"ci_approval": approval},
                    parameters=parameters,
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CI_PENDING")
        self.assertEqual(caught.exception.receipt["external_side_effect_count"], 0)
        mutate.assert_not_called()  # fixed workflow identity was injected; no dispatch

        green = run()
        with mock.patch.object(
            adapter, "_gh_api", side_effect=[{"workflow_runs": [green]}, green, jobs]
        ), mock.patch.object(
            adapter_module,
            "_run",
            return_value=subprocess.CompletedProcess(["git"], 0, "d" * 40 + "\n", ""),
        ):
            adopted = adapter.observe(
                operation_id="CP17.post_release_ci",
                action="post_release_ci",
                expected_before={"ci_approval": approval},
                parameters=parameters,
            )
        self.assertEqual(adopted["classification"], "exact")
        self.assertEqual(adopted["details"]["ci_receipt"]["release_intent"], intent)

    def test_adapter_public_identity_derives_from_verified_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "VERSION").write_text("V2.41\n", encoding="utf-8")
            adapter = adapter_module.GitHubAdapter(
                source_root=source,
                workspace_root=source,
                repository="vibe-coding-era/goal-teams",
                version="V2.41",
                candidate_commit=COMMIT,
                base_main_commit=BASE,
                authority={},
                execute_external_writes=False,
            )
            self.assertEqual(adapter.tag, "v2.41")
            self.assertEqual(adapter.release_title, "Goal Teams V2.41")
            self.assertEqual(
                adapter.release_body,
                "Goal Teams V2.41. See release/current/README.md in the tagged source.",
            )
            self.assertEqual(adapter.tag_message, "Goal Teams V2.41")
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter_module.GitHubAdapter(
                    source_root=source,
                    workspace_root=source,
                    repository="vibe-coding-era/goal-teams",
                    version="V2.40",
                    candidate_commit=COMMIT,
                    base_main_commit=BASE,
                    authority={},
                    execute_external_writes=False,
                )
        self.assertEqual(
            caught.exception.receipt["error_code"], "E_V240_ADAPTER_IDENTITY"
        )

        tag_policy = release._tag_ruleset_payload({})
        self.assertEqual(tag_policy["name"], "goal-teams-tag-protection")
        adapter._validate_ruleset_payload("tag_ruleset_create", tag_policy)
        stale_name = copy.deepcopy(tag_policy)
        stale_name["name"] = "goal-teams-tag-protection-v2.40"
        with self.assertRaises(adapter_module.AdapterError):
            adapter._validate_ruleset_payload("tag_ruleset_create", stale_name)

    def test_post_release_dispatch_recovery_searches_all_pages_before_dispatch(self) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        intent = "7" * 64
        title = f"{adapter.release_title} release {intent}"
        workflow = ".github/workflows/release-gate.yml"
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": workflow,
            "workflow_id": 240,
            "workflow_blob_sha": "d" * 40,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }
        matching = {
            "id": 24017,
            "run_attempt": 1,
            "head_sha": COMMIT,
            "path": workflow,
            "workflow_id": 240,
            "event": "workflow_dispatch",
            "actor": {"id": 240},
            "triggering_actor": {"id": 240},
            "display_title": title,
            "conclusion": None,
            "created_at": "2026-07-14T09:00:00Z",
        }
        decoys = [
            {**matching, "id": index + 1, "display_title": f"decoy-{index}"}
            for index in range(100)
        ]
        pages = [
            {"workflow_runs": decoys},
            {"workflow_runs": [matching]},
        ]
        jobs = {
            "jobs": [
                {"name": name, "conclusion": None}
                for name in approval["required_jobs"]
            ]
        }
        parameters = {
            "_release_intent": intent,
            "dispatch": True,
            "workflow": workflow,
        }
        workflow_metadata = {
            "id": 240,
            "path": workflow,
            "state": "active",
        }
        with mock.patch.object(
            adapter,
            "_gh_api",
            side_effect=[workflow_metadata, pages, matching, jobs],
        ) as api, mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter_module,
            "_run",
            return_value=subprocess.CompletedProcess(
                ["git"], 0, "d" * 40 + "\n", ""
            ),
        ) as command:
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP17.post_release_ci",
                    action="post_release_ci",
                    expected_before={"ci_approval": approval},
                    parameters=parameters,
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CI_PENDING")
        self.assertEqual(caught.exception.receipt["external_side_effect_count"], 0)
        runs_call = api.call_args_list[1]
        self.assertEqual(
            runs_call.args[0],
            "repos/vibe-coding-era/goal-teams/actions/workflows/240/runs?per_page=100",
        )
        self.assertEqual(runs_call.args[-2:], ("--paginate", "--slurp"))
        for forbidden_filter in ("event=", "branch=", "head_sha=", "status="):
            self.assertNotIn(forbidden_filter, runs_call.args[0])
        self.assertNotIn("%2F", runs_call.args[0])
        command.assert_called_once()  # candidate workflow blob read; no dispatch

        duplicate = {**matching, "id": 24018}
        with mock.patch.object(
            adapter,
            "_gh_api",
            side_effect=[
                workflow_metadata,
                [
                    {"workflow_runs": [matching]},
                    {"workflow_runs": [duplicate]},
                ],
            ],
        ), mock.patch.object(
            adapter_module,
            "_run",
            return_value=subprocess.CompletedProcess(
                ["git"], 0, "d" * 40 + "\n", ""
            ),
        ):
            conflict = adapter.observe(
                operation_id="CP17.post_release_ci",
                action="post_release_ci",
                expected_before={"ci_approval": approval},
                parameters=parameters,
            )
        self.assertEqual(conflict["classification"], "conflict")
        self.assertEqual(
            conflict["details"]["matching_run_ids"], [24017, 24018]
        )

    def test_entry_fails_fast_before_python_311(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            release._require_python_311((3, 10, 99))
        self.assertEqual(
            str(caught.exception),
            "E_V240_PYTHON_VERSION: Python 3.11+ required",
        )
        self.assertIsNone(release._require_python_311((3, 11, 0)))

    @unittest.skipIf(
        os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1",
        "CP00 scope freeze requires the canonical local-only release workspace",
    )
    def test_start_creates_state_and_executes_real_cp00_receipt_chain(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
        ).strip()
        scope, route = _release_scope(candidate)
        docs = ROOT / "docs"
        docs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="v240-start-", dir=docs) as directory:
            path = Path(directory) / "promotion-state.json"
            receipt = release.start_release(
                {
                    "state_path": str(path),
                    "repository": "vibe-coding-era/goal-teams",
                    "version": "V2.40",
                    "base_main_commit": route["target"]["base_main_commit"],
                    "candidate_commit": candidate,
                    "candidate_tree": tree,
                    "scope": scope,
                }
            )
            state = json.loads(path.read_text())
        self.assertEqual(receipt["command"], "start")
        self.assertEqual(state["checkpoints"]["CP00"]["status"], "passed")
        self.assertEqual(state["current_checkpoint"], "CP01")
        self.assertTrue(release.validate_promotion_state(state)["passed"])

    @unittest.skipIf(
        os.environ.get("GOAL_TEAMS_INSTALL_VALIDATION") == "1",
        "CP00 scope freeze requires the canonical local-only release workspace",
    )
    def test_start_rejects_bad_scope_before_creating_any_state(self) -> None:
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
        ).strip()
        scope, route = _release_scope(candidate)
        scope["owner_run_id"] = "RUN-FORGED"
        docs = ROOT / "docs"
        docs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="v240-bad-start-", dir=docs) as directory:
            path = Path(directory) / "promotion-state.json"
            with self.assertRaises(release.PolicyError) as caught:
                release.start_release(
                    {
                        "state_path": str(path),
                        "repository": "vibe-coding-era/goal-teams",
                        "version": "V2.40",
                        "base_main_commit": route["target"]["base_main_commit"],
                        "candidate_commit": candidate,
                        "candidate_tree": tree,
                        "scope": scope,
                    }
                )
            self.assertFalse(path.exists())
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_SCOPE_FREEZE")

    def test_doctor_rejects_caller_workspace_success_facts(self) -> None:
        with self.assertRaises(release.PolicyError) as caught:
            release.doctor_release(
                {
                    "state_path": "/tmp/forged.json",
                    "expected_state_sha256": "a" * 64,
                    "workspace_facts": {
                        "canonical_branch": "main",
                        "dirty": False,
                    },
                }
            )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CLI_INPUT")

    def test_actual_install_rejects_caller_selected_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "docs").mkdir()
            with mock.patch.object(
                release, "_workspace_root", return_value=workspace
            ), mock.patch.dict(
                "os.environ", {"GOAL_TEAMS_RELEASE_INSTALL": "1"}, clear=False
            ):
                with self.assertRaises(release.PolicyError) as caught:
                    release._execute_local_operation(
                        "CP17.actual_install",
                        {"version": "V2.40", "candidate_commit": COMMIT},
                        {
                            "execute_actual_install": True,
                            "codex_home": "/tmp/not-production-codex-home",
                        },
                        workspace / "docs" / "state.json",
                    )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_INSTALL_TARGET")

    def test_cp14_lease_rejects_caller_observed_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "docs").mkdir()
            with mock.patch.object(release, "_workspace_root", return_value=workspace):
                with self.assertRaises(release.PolicyError) as caught:
                    release._execute_local_operation(
                        "CP14.promotion_lease",
                        {"version": "V2.40", "candidate_commit": COMMIT},
                        {"observed_main_commit": BASE},
                        workspace / "docs" / "state.json",
                    )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_REMOTE_MAIN_LEASE")

    def test_finalize_adopts_exact_post_mutation_after_marker_loss(self) -> None:
        adapter = _adapter(ROOT)
        absent = {"classification": "absent", "details": {}}
        exact = {
            "classification": "exact",
            "source": "github_api",
            "details": {"ruleset_name": "main", "ruleset_sha256": "c" * 64},
        }
        with mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
            adapter, "observe", side_effect=[absent, exact]
        ) as observe:
            receipt = adapter.execute(
                operation_id="CP18.promotion_lock_finalize",
                action="promotion_lock_finalize",
                expected_before={"ruleset_name": "main"},
                parameters={"ruleset_name": "main"},
            )
        self.assertTrue(receipt["adopted_after_marker_loss"])
        self.assertEqual(receipt["external_side_effect_count"], 0)
        self.assertTrue(observe.call_args_list[1].kwargs["parameters"]["_post_mutation"])

    def test_finalize_reuses_bound_permanent_ruleset_without_put(self) -> None:
        final = _final_main_ruleset_payload()
        ruleset_id = 24014
        expected_before = {
            "ruleset_id": ruleset_id,
            "ruleset_name": final["name"],
            "ruleset_payload": final,
            "ruleset_sha256": adapter_module._canonical_sha256(
                adapter_module.normalize_ruleset(final)
            ),
        }
        parameters = {
            "ruleset_id": ruleset_id,
            "ruleset_name": final["name"],
            "ruleset_payload": final,
            "ruleset_payload_sha256": adapter_module._canonical_sha256(
                adapter_module.normalize_ruleset(final)
            ),
        }
        lookups: list[str] = []

        def ruleset_by_name(name: str):
            lookups.append(name)
            return {"id": ruleset_id, **final} if name == final["name"] else None

        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        with mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
            adapter, "_ruleset_by_name", side_effect=ruleset_by_name
        ), mock.patch.object(adapter_module, "_run") as put:
            receipt = adapter.execute(
                operation_id="CP18.promotion_lock_finalize",
                action="promotion_lock_finalize",
                expected_before=expected_before,
                parameters=parameters,
            )
        put.assert_not_called()
        self.assertEqual(receipt["classification"], "exact")
        self.assertTrue(receipt["adopted_existing"])
        self.assertEqual(receipt["external_side_effect_count"], 0)
        self.assertEqual(lookups, [final["name"]])

    def test_finalize_old_conflict_and_final_absent_fails_without_put(self) -> None:
        adapter = _adapter(ROOT)
        with mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
            adapter,
            "observe",
            side_effect=[
                {"classification": "conflict", "details": {}},
                {"classification": "absent", "details": {}},
            ],
        ), mock.patch.object(adapter_module, "_run") as put:
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP18.promotion_lock_finalize",
                    action="promotion_lock_finalize",
                    expected_before={"ruleset_name": "old"},
                    parameters={"ruleset_name": "final"},
                )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_REMOTE_RESOURCE_CONFLICT",
        )
        put.assert_not_called()

    def test_marker_loss_adopts_exact_canonical_install_without_reinstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / ".codex"
            current_path = codex_home / "state" / "goal-teams" / "current.json"
            current_path.parent.mkdir(parents=True)
            assets = [
                {
                    "name": "goal-teams-V2.40.tar.gz",
                    "sha256": "c" * 64,
                    "size": 10,
                }
            ]
            current = {
                "source_kind": "github_release_asset",
                "repository": "vibe-coding-era/goal-teams",
                "release_tag": "v2.40",
                "release_id": 240,
                "release_state": "published",
                "release_assets": assets,
                "source_commit": COMMIT,
                "skill_tree_digest": "d" * 64,
            }
            current_path.write_text(json.dumps(current), encoding="utf-8")
            bundle = root / "bundle"
            bundle.mkdir()
            with mock.patch.object(
                release,
                "_validate_installed_package_tree",
                return_value={"installed_tree_sha256": "d" * 64},
            ) as validate:
                receipt = release._adopt_exact_actual_install(
                    {
                        "repository": "vibe-coding-era/goal-teams",
                        "version": "V2.40",
                        "tag": "v2.40",
                        "candidate_commit": COMMIT,
                    },
                    bundle,
                    {"release_id": 240, "assets": assets},
                    codex_home,
                )
        self.assertIsNotNone(receipt)
        self.assertTrue(receipt["details"]["adopted_after_marker_loss"])
        validate.assert_called_once()

    def test_promote_rejects_cp18_without_close_capability(self) -> None:
        fake_state = {"current_checkpoint": "CP18"}
        with mock.patch.object(
            release,
            "_load_state_cas",
            return_value=(Path("/tmp/state.json"), fake_state, "a" * 64),
        ), mock.patch.object(release, "_verify_frozen_git_identity"):
            with self.assertRaises(release.PolicyError) as caught:
                release.execute_current_checkpoint(
                    "/tmp/state.json", {"expected_state_sha256": "a" * 64}
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CLOSE_REQUIRED")

    def test_recover_rejects_cp18_without_close_capability(self) -> None:
        fake_state = {"current_checkpoint": "CP18"}
        with mock.patch.object(
            release,
            "_load_state_cas",
            return_value=(Path("/tmp/state.json"), fake_state, "a" * 64),
        ), mock.patch.object(release, "_verify_frozen_git_identity"):
            with self.assertRaises(release.PolicyError) as caught:
                release.execute_current_checkpoint(
                    "/tmp/state.json",
                    {"expected_state_sha256": "a" * 64},
                    recover_only=True,
                )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CLOSE_REQUIRED")

    def test_ci_approval_requires_prebound_numeric_workflow_id(self) -> None:
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_id": 240,
            "workflow_blob_sha": "d" * 40,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }
        receipt = {
            **approval,
            "actor_id": 240,
            "triggering_actor_id": 240,
            "workflow_raw_path": ".github/workflows/release-gate.yml",
            "workflow_raw_ref": None,
            "run_id": 24013,
            "run_attempt": 1,
            "jobs": [
                {"name": name, "head_sha": COMMIT, "conclusion": "success"}
                for name in approval["required_jobs"]
            ],
        }
        validated = release.validate_ci_receipt(receipt, approval)
        self.assertEqual(validated["workflow_id"], 240)
        self.assertEqual(validated["actor_id"], 240)
        self.assertEqual(validated["triggering_actor_id"], 240)
        missing_id = {key: value for key, value in approval.items() if key != "workflow_id"}
        with self.assertRaises(release.PolicyError):
            release.validate_ci_receipt(receipt, missing_id)

    def test_fixed_workflow_identity_accepts_only_canonical_or_main_run_path(
        self,
    ) -> None:
        adapter = _adapter(ROOT)
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_id": 240,
            "workflow_blob_sha": "d" * 40,
            "required_jobs": [
                "check-ubuntu",
                "check-macos",
                "release-asset-gate",
            ],
        }
        metadata = {
            "id": 240,
            "path": approval["workflow_path"],
            "state": "active",
        }
        with mock.patch.object(
            adapter, "_gh_api", return_value=metadata
        ) as api, mock.patch.object(
            adapter_module,
            "_run",
            return_value=subprocess.CompletedProcess(
                ["git"], 0, approval["workflow_blob_sha"] + "\n", ""
            ),
        ):
            identity = adapter._fixed_workflow_identity(approval)
        api.assert_called_once_with(
            "repos/vibe-coding-era/goal-teams/actions/workflows/release-gate.yml"
        )
        self.assertEqual(identity, _workflow_identity())

        canonical = approval["workflow_path"]
        self.assertEqual(
            adapter._canonical_run_workflow_path(canonical),
            {"source_path": canonical, "raw_path": canonical, "raw_ref": None},
        )
        self.assertEqual(
            adapter._canonical_run_workflow_path(f"{canonical}@main"),
            {
                "source_path": canonical,
                "raw_path": f"{canonical}@main",
                "raw_ref": "main",
            },
        )
        for spoof in (
            f"{canonical}@v2.40",
            f"{canonical}@refs/heads/main",
            f"{canonical}@refs/tags/v2.40",
            ".github/workflows/other.yml@main",
        ):
            with self.subTest(spoof=spoof), self.assertRaises(
                adapter_module.AdapterError
            ) as caught:
                adapter._canonical_run_workflow_path(spoof)
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_CI_TRUST_BINDING",
            )

        for metadata_drift in (
            {**metadata, "id": 241},
            {**metadata, "path": f"{canonical}@main"},
            {**metadata, "state": "disabled_manually"},
        ):
            with self.subTest(metadata_drift=metadata_drift), mock.patch.object(
                adapter, "_gh_api", return_value=metadata_drift
            ), self.assertRaises(adapter_module.AdapterError) as caught:
                adapter._fixed_workflow_identity(approval)
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_CI_TRUST_BINDING",
            )

    def test_ci_actor_chain_rejects_other_positive_actor(self) -> None:
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_id": 240,
            "workflow_blob_sha": "d" * 40,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }
        receipt = {
            **approval,
            "actor_id": 241,
            "triggering_actor_id": 241,
            "workflow_raw_path": ".github/workflows/release-gate.yml",
            "workflow_raw_ref": None,
            "run_id": 24013,
            "run_attempt": 1,
            "jobs": [
                {"name": name, "head_sha": COMMIT, "conclusion": "success"}
                for name in approval["required_jobs"]
            ],
        }
        with self.assertRaises(release.PolicyError) as caught:
            release.validate_ci_receipt(receipt, approval)
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CI_TRUST_BINDING")

        other_actor_approval = {**approval, "release_actor_id": 241}
        with self.assertRaises(release.PolicyError) as state_caught:
            release._validate_ci_state_authority(
                {"github_authority": {"actor_id": 240}},
                other_actor_approval,
                receipt,
            )
        self.assertEqual(
            state_caught.exception.receipt["error_code"],
            "E_V240_CI_TRUST_BINDING",
        )

    def test_cp05_approval_release_actor_is_separate_from_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "docs").mkdir()
            approval = {
                "release_actor_id": 241,
                "reviewer": {
                    "role": "independent_release_reviewer",
                    "member_id": "reviewer-v240",
                    "run_id": "RUN-V240-INDEPENDENT-REVIEW",
                    "independent": True,
                    "decision": "accepted",
                    "source_commit": COMMIT,
                    "reviewed_at": "2026-07-14T07:00:00Z",
                },
            }
            with mock.patch.object(
                release, "_workspace_root", return_value=workspace
            ), mock.patch.object(
                release, "_require_clean_candidate_checkout", return_value={}
            ):
                with self.assertRaises(release.PolicyError) as caught:
                    release._execute_local_operation(
                        "CP05.workflow_approve",
                        {
                            "version": "V2.40",
                            "candidate_commit": COMMIT,
                            "github_authority": {"actor_id": 240},
                        },
                        {"ci_approval": approval},
                        workspace / "docs" / "state.json",
                    )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_CI_TRUST_BINDING")

    def test_ci_observer_other_positive_actor_is_unavailable(self) -> None:
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_id": 240,
            "workflow_blob_sha": "d" * 40,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }
        jobs = [
            {"name": name, "conclusion": "success"}
            for name in approval["required_jobs"]
        ]
        for actor_id, triggering_actor_id, attempt, classification in (
            (240, 240, 2, "exact"),
            (240, 241, 2, "unavailable"),
            (241, 241, 1, "unavailable"),
        ):
            with self.subTest(
                actor_id=actor_id,
                triggering_actor_id=triggering_actor_id,
                attempt=attempt,
            ):
                adapter = _adapter(ROOT)
                adapter.authority = {"actor_id": 240}
                adapter._fixed_workflow_identity = mock.Mock(
                    return_value=_workflow_identity()
                )
                run = {
                    "id": 24013,
                    "run_attempt": attempt,
                    "head_sha": COMMIT,
                    "path": approval["workflow_path"],
                    "workflow_id": 240,
                    "event": "push",
                    "actor": {"id": actor_id},
                    "triggering_actor": {"id": triggering_actor_id},
                    "conclusion": "success",
                    "created_at": "2026-07-14T07:00:00Z",
                }
                with mock.patch.object(
                    adapter, "_gh_api", side_effect=[run, {"jobs": jobs}]
                ), mock.patch.object(
                    adapter_module,
                    "_run",
                    return_value=subprocess.CompletedProcess(
                        ["git"], 0, approval["workflow_blob_sha"] + "\n", ""
                    ),
                ):
                    observed = adapter.observe(
                        operation_id="CP13.candidate_ci",
                        action="ci_wait",
                        expected_before={"ci_approval": approval},
                        parameters={"run_id": 24013},
                    )
                self.assertEqual(observed["classification"], classification)

    def test_candidate_ci_marker_recovery_scans_beyond_1000_without_filters(
        self,
    ) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        workflow = ".github/workflows/release-gate.yml"
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": workflow,
            "workflow_id": 240,
            "workflow_blob_sha": "d" * 40,
            "required_jobs": [
                "check-ubuntu",
                "check-macos",
                "release-asset-gate",
            ],
        }
        matching = {
            "id": 24013,
            "run_attempt": 2,
            "head_sha": COMMIT,
            "path": f"{workflow}@main",
            "workflow_id": 240,
            "event": "push",
            "actor": {"id": 240},
            "triggering_actor": {"id": 240},
            "conclusion": "success",
            "created_at": "2026-07-14T07:00:00Z",
        }
        pages = []
        for page_index in range(10):
            pages.append(
                {
                    "workflow_runs": [
                        {
                            **matching,
                            "id": page_index * 100 + row_index + 1,
                            "head_sha": BASE,
                            "path": workflow,
                        }
                        for row_index in range(100)
                    ]
                }
            )
        pages.append({"workflow_runs": [matching]})
        jobs = {
            "jobs": [
                {"name": name, "conclusion": "success"}
                for name in approval["required_jobs"]
            ]
        }
        metadata = {"id": 240, "path": workflow, "state": "active"}
        with mock.patch.object(
            adapter,
            "_gh_api",
            side_effect=[metadata, pages, matching, jobs],
        ) as api, mock.patch.object(
            adapter_module,
            "_run",
            return_value=subprocess.CompletedProcess(
                ["git"], 0, approval["workflow_blob_sha"] + "\n", ""
            ),
        ):
            observed = adapter.observe(
                operation_id="CP13.candidate_ci",
                action="ci_wait",
                expected_before={"ci_approval": approval},
                parameters={},
            )
        self.assertEqual(observed["classification"], "exact")
        receipt = observed["details"]["ci_receipt"]
        self.assertEqual(receipt["workflow_path"], workflow)
        self.assertEqual(receipt["workflow_raw_path"], f"{workflow}@main")
        self.assertEqual(receipt["workflow_raw_ref"], "main")
        runs_call = api.call_args_list[1]
        self.assertEqual(
            runs_call.args,
            (
                "repos/vibe-coding-era/goal-teams/actions/workflows/240/runs?per_page=100",
                "--paginate",
                "--slurp",
            ),
        )
        for forbidden_filter in ("event=", "branch=", "head_sha=", "status="):
            self.assertNotIn(forbidden_filter, runs_call.args[0])

    def test_ruleset_lookup_flattens_all_pages_and_rejects_global_duplicate(
        self,
    ) -> None:
        adapter = _adapter(ROOT)
        name = "goal-teams-main-protection"
        summary = {"id": 24014, "name": name}
        detail = {**summary, "target": "branch", "enforcement": "active"}
        pages = [
            [{"id": 1, "name": "unrelated-first-page"}],
            [summary],
            [{"id": 2, "name": "unrelated-last-page"}],
        ]
        with mock.patch.object(
            adapter, "_gh_api", side_effect=[pages, detail]
        ) as api:
            observed = adapter._ruleset_by_name(name)
        self.assertEqual(observed, detail)
        self.assertEqual(
            api.call_args_list[0].args,
            (
                "repos/vibe-coding-era/goal-teams/rulesets",
                "--paginate",
                "--slurp",
            ),
        )

        duplicate_pages = [
            [{"id": 24014, "name": name}],
            [{"id": 24015, "name": name}],
        ]
        with mock.patch.object(
            adapter, "_gh_api", return_value=duplicate_pages
        ), self.assertRaises(adapter_module.AdapterError) as caught:
            adapter._ruleset_by_name(name)
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_REMOTE_RESOURCE_CONFLICT",
        )

    def test_ruleset_get_response_normalizes_to_create_payload(self) -> None:
        payload = _final_main_ruleset_payload()
        response = {
            **payload,
            "id": 24014,
            "source": "vibe-coding-era/goal-teams",
            "source_type": "Repository",
            "created_at": "2026-07-14T00:00:00Z",
            "updated_at": "2026-07-14T00:01:00Z",
        }
        self.assertEqual(
            adapter_module.normalize_ruleset(payload),
            adapter_module.normalize_ruleset(response),
        )
        expected_sha = adapter_module._canonical_sha256(
            adapter_module.normalize_ruleset(payload)
        )
        with tempfile.TemporaryDirectory() as directory:
            adapter = _adapter(Path(directory))
            adapter.authority = {"actor_id": 240}
            with mock.patch.object(adapter, "_ruleset_by_name", return_value=response):
                receipt = adapter.observe(
                    operation_id="CP14.main_promotion_lock",
                    action="promotion_lock_create",
                    expected_before={
                        "ruleset_name": payload["name"],
                        "ruleset_payload": payload,
                        "ruleset_sha256": expected_sha,
                    },
                    parameters={},
                )
        self.assertEqual(receipt["classification"], "exact")
        self.assertEqual(receipt["details"]["ruleset_sha256"], expected_sha)
        self.assertEqual(receipt["details"]["ruleset_id"], 24014)
        self.assertNotIn("id", receipt["details"]["ruleset"])

    def test_cp14_reuses_only_the_exact_release_actor_main_ruleset(self) -> None:
        payload = _final_main_ruleset_payload()
        expected_sha = adapter_module._canonical_sha256(
            adapter_module.normalize_ruleset(payload)
        )
        expected_before = {
            "ruleset_name": payload["name"],
            "ruleset_payload": payload,
            "ruleset_sha256": expected_sha,
        }
        parameters = {
            "ruleset_name": payload["name"],
            "ruleset_payload": payload,
            "ruleset_payload_sha256": expected_sha,
        }
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        with mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_ruleset_by_name", return_value={"id": 24014, **payload}
        ), mock.patch.object(adapter_module, "_run") as mutation:
            receipt = adapter.execute(
                operation_id="CP14.main_promotion_lock",
                action="promotion_lock_create",
                expected_before=expected_before,
                parameters=parameters,
            )
        self.assertTrue(receipt["adopted_existing"])
        self.assertEqual(receipt["external_side_effect_count"], 0)
        mutation.assert_not_called()

        wrong_actor = copy.deepcopy(payload)
        wrong_actor["bypass_actors"][0]["actor_id"] = 241
        with mock.patch.object(
            adapter, "_ruleset_by_name", return_value={"id": 24014, **wrong_actor}
        ), self.assertRaises(adapter_module.AdapterError) as caught:
            adapter.observe(
                operation_id="CP14.main_promotion_lock",
                action="promotion_lock_create",
                expected_before=expected_before,
                parameters=parameters,
            )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_PROMOTION_LOCK")

    def test_classic_main_protection_must_allow_release_actor_force_lease(self) -> None:
        adapter = _adapter(ROOT)
        with mock.patch.object(adapter, "_gh_api", return_value=None) as api:
            absent = adapter._classic_main_protection_compatibility(
                actor_login="release-owner",
                actor_is_admin=True,
            )
        self.assertFalse(absent["present"])
        self.assertTrue(absent["release_actor_can_force_with_lease"])
        self.assertIn("branches/main/protection", api.call_args.args[0])

        admin_bypass_policy = {
            "enforce_admins": {"enabled": False},
            "allow_force_pushes": {"enabled": False},
            "required_status_checks": {"contexts": ["legacy-check"]},
            "required_pull_request_reviews": {"required_approving_review_count": 2},
            "required_signatures": {"enabled": True},
            "required_linear_history": {"enabled": True},
            "lock_branch": {"enabled": False},
            "restrictions": None,
        }
        with mock.patch.object(
            adapter, "_gh_api", return_value=admin_bypass_policy
        ):
            bypass = adapter._classic_main_protection_compatibility(
                actor_login="release-owner",
                actor_is_admin=True,
            )
        self.assertEqual(bypass["compatibility_mode"], "admin_bypass")

        conflicting = copy.deepcopy(admin_bypass_policy)
        conflicting["enforce_admins"]["enabled"] = True
        with mock.patch.object(
            adapter, "_gh_api", return_value=conflicting
        ), self.assertRaises(adapter_module.AdapterError) as caught:
            adapter._classic_main_protection_compatibility(
                actor_login="release-owner",
                actor_is_admin=True,
            )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_CLASSIC_BRANCH_PROTECTION",
        )

        explicit = {
            "enforce_admins": {"enabled": True},
            "allow_force_pushes": {"enabled": True},
            "required_status_checks": None,
            "required_pull_request_reviews": None,
            "required_signatures": {"enabled": False},
            "required_linear_history": {"enabled": False},
            "lock_branch": {"enabled": False},
            "restrictions": {"users": [{"login": "release-owner"}]},
        }
        with mock.patch.object(adapter, "_gh_api", return_value=explicit):
            receipt = adapter._classic_main_protection_compatibility(
                actor_login="release-owner",
                actor_is_admin=True,
            )
        self.assertEqual(receipt["compatibility_mode"], "explicit_force_push")
        self.assertTrue(receipt["release_actor_can_force_with_lease"])

    def test_cp03_and_cp14_authority_readbacks_query_classic_main_protection(
        self,
    ) -> None:
        transport = {
            "api_host": "github.com",
            "repository": "vibe-coding-era/goal-teams",
            "raw_fetch_urls": [
                "git@github.com:vibe-coding-era/goal-teams.git"
            ],
            "raw_push_urls": [
                "git@github.com:vibe-coding-era/goal-teams.git"
            ],
            "resolved_fetch_urls": [
                "git@github.com:vibe-coding-era/goal-teams.git"
            ],
            "resolved_push_urls": [
                "git@github.com:vibe-coding-era/goal-teams.git"
            ],
            "pushurl_configured": False,
            "url_rewrite_count": 0,
        }
        transport["origin_binding_sha256"] = adapter_module._canonical_sha256(
            transport
        )
        for operation_id in (
            "CP03.github_authority_readback",
            "CP14.github_authority_revalidate",
        ):
            with self.subTest(operation_id=operation_id):
                adapter = _adapter(ROOT)
                endpoints: list[str] = []

                def gh_api(endpoint: str, *args: str, **kwargs):
                    endpoints.append(endpoint)
                    if endpoint == "user":
                        return {"id": 240, "login": "release-owner"}
                    if endpoint == "repos/vibe-coding-era/goal-teams":
                        return {
                            "id": adapter_module.FIXED_REPOSITORY_ID,
                            "full_name": "vibe-coding-era/goal-teams",
                            "permissions": {"admin": True},
                        }
                    if endpoint.endswith("/immutable-releases"):
                        return {"enabled": True}
                    if endpoint.endswith("/rulesets"):
                        return []
                    if endpoint.endswith("/branches/main/protection"):
                        return None
                    self.fail(f"unexpected endpoint: {endpoint}")

                with mock.patch.object(
                    adapter,
                    "_validate_transport_authority",
                    return_value=transport,
                ), mock.patch.object(adapter, "_gh_api", side_effect=gh_api):
                    readback = adapter.observe(
                        operation_id=operation_id,
                        action="github_authority_verify",
                        expected_before={},
                        parameters={},
                    )
                self.assertEqual(readback["classification"], "exact")
                self.assertEqual(
                    endpoints.count(
                        "repos/vibe-coding-era/goal-teams/branches/main/protection"
                    ),
                    1,
                )

    def test_ruleset_exclude_and_missing_required_parameters_fail_closed(self) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        canonical = _final_main_ruleset_payload()
        ineffective = json.loads(json.dumps(canonical))
        ineffective["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        missing_status_parameters = json.loads(json.dumps(canonical))
        missing_status_parameters["rules"][3]["parameters"].pop(
            "strict_required_status_checks_policy"
        )
        for payload in (ineffective, missing_status_parameters):
            with self.subTest(payload=payload), self.assertRaises(
                adapter_module.AdapterError
            ):
                adapter._validate_ruleset_payload("promotion_lock_create", payload)

        missing_code_owner = _final_main_ruleset_payload()
        missing_code_owner["rules"][2]["parameters"].pop(
            "require_code_owner_review"
        )
        with self.assertRaises(adapter_module.AdapterError):
            adapter._validate_ruleset_payload(
                "promotion_lock_finalize", missing_code_owner
            )

    def test_ruleset_observer_rejects_weak_live_policy_before_adoption(self) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        canonical = _final_main_ruleset_payload()
        weak_live = json.loads(json.dumps(canonical))
        weak_live["id"] = 24014
        weak_live["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        expected_sha = adapter_module._canonical_sha256(
            adapter_module.normalize_ruleset(canonical)
        )
        with mock.patch.object(
            adapter, "_ruleset_by_name", return_value=weak_live
        ), self.assertRaises(adapter_module.AdapterError) as caught:
            adapter.observe(
                operation_id="CP14.main_promotion_lock",
                action="promotion_lock_create",
                expected_before={
                    "ruleset_name": canonical["name"],
                    "ruleset_payload": canonical,
                    "ruleset_sha256": expected_sha,
                },
                parameters={},
            )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_PROMOTION_LOCK")

    def test_ruleset_execute_cannot_adopt_a_weak_exact_payload(self) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        weak = _final_main_ruleset_payload()
        weak["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        expected = {
            "ruleset_name": weak["name"],
            "ruleset_payload": weak,
            "ruleset_sha256": adapter_module._canonical_sha256(
                adapter_module.normalize_ruleset(weak)
            ),
        }
        with mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_ruleset_by_name", return_value={"id": 24014, **weak}
        ), mock.patch.object(adapter_module, "_run") as mutation:
            with self.assertRaises(adapter_module.AdapterError):
                adapter.execute(
                    operation_id="CP14.main_promotion_lock",
                    action="promotion_lock_create",
                    expected_before=expected,
                    parameters={},
                )
        mutation.assert_not_called()

    def test_finalize_marker_loss_cannot_adopt_a_weak_final_policy(self) -> None:
        adapter = _adapter(ROOT)
        adapter.authority = {"actor_id": 240}
        canonical = _final_main_ruleset_payload()
        weak_final = copy.deepcopy(canonical)
        weak_final["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        ruleset_id = 24014

        def ruleset_by_name(name: str):
            if name == weak_final["name"]:
                return {"id": ruleset_id, **weak_final}
            return None

        with mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_ruleset_by_name", side_effect=ruleset_by_name
        ), mock.patch.object(adapter_module, "_run") as mutation:
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP18.promotion_lock_finalize",
                    action="promotion_lock_finalize",
                    expected_before={
                        "ruleset_id": ruleset_id,
                        "ruleset_name": canonical["name"],
                        "ruleset_payload": canonical,
                        "ruleset_sha256": adapter_module._canonical_sha256(
                            adapter_module.normalize_ruleset(canonical)
                        ),
                    },
                    parameters={
                        "ruleset_id": ruleset_id,
                        "ruleset_name": canonical["name"],
                        "ruleset_payload": canonical,
                        "ruleset_payload_sha256": adapter_module._canonical_sha256(
                            adapter_module.normalize_ruleset(canonical)
                        ),
                    },
                )
        self.assertEqual(
            caught.exception.receipt["error_code"], "E_V240_PROMOTION_LOCK"
        )
        mutation.assert_not_called()

    def test_final_main_ruleset_rejects_a_weak_subset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = _adapter(Path(directory))
            adapter.authority = {"actor_id": 240}
            base = {
                "name": "goal-teams-main-protection",
                "target": "branch",
                "enforcement": "active",
                "bypass_actors": [
                    {"actor_id": 240, "actor_type": "User", "bypass_mode": "always"}
                ],
                "conditions": {
                    "ref_name": {"include": ["refs/heads/main"], "exclude": []}
                },
            }
            weak = {**base, "rules": [{"type": "deletion"}]}
            with self.assertRaises(adapter_module.AdapterError):
                adapter._validate_ruleset_payload("promotion_lock_finalize", weak)
            strong = {
                **base,
                "rules": [
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                    {
                        "type": "pull_request",
                        "parameters": {
                            "dismiss_stale_reviews_on_push": True,
                            "require_code_owner_review": False,
                            "require_last_push_approval": True,
                            "required_approving_review_count": 1,
                            "required_review_thread_resolution": True,
                        },
                    },
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "strict_required_status_checks_policy": True,
                            "do_not_enforce_on_create": False,
                            "required_status_checks": [
                                {"context": "check-ubuntu"},
                                {"context": "check-macos"},
                                {"context": "release-asset-gate"},
                            ],
                        },
                    },
                ],
            }
            adapter._validate_ruleset_payload("promotion_lock_finalize", strong)

    def test_asset_upload_observe_distinguishes_absent_exact_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            paths = _write_assets(workspace)
            adapter = _adapter(workspace)
            path = paths["_files.sha256"]
            expected = {
                "asset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "asset_size": path.stat().st_size,
                "release_id": 240,
            }
            draft_without_asset = {
                "databaseId": 240,
                "isDraft": True,
                "isPrerelease": False,
                "tagName": "v2.40",
                "assets": [],
            }
            with mock.patch.object(adapter, "_release_json", return_value=draft_without_asset):
                absent = adapter.observe(
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    expected_before=expected,
                    parameters={},
                )
            self.assertEqual(absent["classification"], "absent")

            release_with_asset = {
                **draft_without_asset,
                "assets": [{"id": 2404, "name": "_files.sha256", "size": path.stat().st_size}],
            }

            def fake_download(asset_id: int, destination: Path):
                self.assertEqual(asset_id, 2404)
                shutil.copyfile(path, destination)

            with mock.patch.object(adapter, "_release_json", return_value=release_with_asset), mock.patch.object(
                adapter, "_download_release_asset", side_effect=fake_download
            ):
                exact = adapter.observe(
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    expected_before=expected,
                    parameters={},
                )
            self.assertEqual(exact["classification"], "exact")

            def fake_conflict(asset_id: int, destination: Path):
                self.assertEqual(asset_id, 2404)
                destination.write_bytes(b"x" * path.stat().st_size)

            with mock.patch.object(adapter, "_release_json", return_value=release_with_asset), mock.patch.object(
                adapter, "_download_release_asset", side_effect=fake_conflict
            ):
                conflict = adapter.observe(
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    expected_before=expected,
                    parameters={},
                )
            self.assertEqual(conflict["classification"], "conflict")

    def test_asset_upload_execute_does_not_adopt_an_absent_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            paths = _write_assets(workspace)
            adapter = _adapter(workspace)
            path = paths["_files.sha256"]
            expected = {
                "asset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "asset_size": path.stat().st_size,
                "release_id": 240,
            }
            uploaded = {"value": False}

            def release_json(release_id=None):
                self.assertEqual(release_id, 240)
                assets = []
                if uploaded["value"]:
                    assets = [{"id": 2404, "name": "_files.sha256", "size": path.stat().st_size}]
                return {"databaseId": 240, "isDraft": True, "isPrerelease": False, "tagName": "v2.40", "assets": assets}

            def fake_upload(
                release_id: int,
                name: str,
                upload_path: Path,
                **_guard: object,
            ):
                self.assertEqual((release_id, name), (240, "_files.sha256"))
                self.assertEqual(upload_path.resolve(), path.resolve())
                uploaded["value"] = True

            def fake_download(asset_id: int, destination: Path):
                self.assertEqual(asset_id, 2404)
                shutil.copyfile(path, destination)

            with mock.patch.object(adapter, "_release_json", side_effect=release_json), mock.patch.object(
                adapter, "_require_write_authority"
            ), mock.patch.object(
                adapter, "_validate_remote_mutation_guard", return_value={}
            ), mock.patch.object(
                adapter, "_upload_release_asset", side_effect=fake_upload
            ), mock.patch.object(
                adapter, "_download_release_asset", side_effect=fake_download
            ):
                receipt = adapter.execute(
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    expected_before=expected,
                    parameters={},
                )
            self.assertTrue(uploaded["value"])
            self.assertEqual(receipt["classification"], "exact")
            self.assertEqual(receipt["external_side_effect_count"], 1)

    def test_asset_upload_requires_and_targets_the_frozen_release_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            paths = _write_assets(workspace)
            adapter = _adapter(workspace)
            path = paths["_files.sha256"]
            expected = {
                "asset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "asset_size": path.stat().st_size,
            }
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.observe(
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    expected_before=expected,
                    parameters={},
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_ADAPTER_EXPECTED_BEFORE",
            )

            commands: list[tuple[str, ...]] = []

            def run_command(argv, *, cwd, env=None):
                commands.append(tuple(argv))
                return subprocess.CompletedProcess(argv, 0, "{}", "")

            with mock.patch.object(
                adapter, "_validate_remote_mutation_guard", return_value={}
            ), mock.patch.object(adapter_module, "_run", side_effect=run_command):
                adapter._upload_release_asset(
                    240,
                    "_files.sha256",
                    path,
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    parameters={},
                )
            self.assertEqual(len(commands), 1)
            self.assertIn(
                "https://uploads.github.com/repos/vibe-coding-era/goal-teams/"
                "releases/240/assets?name=_files.sha256",
                commands[0],
            )
            self.assertNotIn("v2.40", commands[0])

    def test_release_publish_final_projection_precedes_external_host_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            assets = adapter._local_asset_set()
            asset_set_sha256 = adapter_module._canonical_sha256(assets)
            remote_assets, draft_asset_identity_sha256 = _release_asset_fixture(
                adapter
            )
            draft = {
                "databaseId": 240,
                "isDraft": True,
                "isImmutable": False,
                "isPrerelease": False,
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "assets": remote_assets,
            }
            releases = iter((draft, draft, draft))

            with mock.patch.object(
                adapter,
                "_release_json",
                side_effect=lambda release_id=None: next(releases),
            ), mock.patch.object(
                adapter,
                "_persist_verified_bundle",
                return_value={
                    "asset_set_sha256": asset_set_sha256,
                    "asset_identity_sha256": draft_asset_identity_sha256,
                    "assets": [],
                    "bundle_path": "/ignored/published-bundle",
                },
            ) as persist, mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
                adapter, "_validate_remote_mutation_guard", return_value={}
            ), mock.patch.object(adapter, "_gh_api") as gh_api:
                with self.assertRaises(adapter_module.AdapterError) as caught:
                    adapter.execute(
                        operation_id="CP17.release_publish",
                        action="release_publish",
                        expected_before={
                            "asset_set_sha256": asset_set_sha256,
                            "draft_asset_set_sha256": asset_set_sha256,
                            "draft_asset_identity_sha256": (
                                draft_asset_identity_sha256
                            ),
                            "candidate_commit": COMMIT,
                            "tag": "v2.40",
                            "release_id": 240,
                            "targetCommitish": COMMIT,
                            "name": adapter.release_title,
                            "body": adapter.release_body,
                        },
                        parameters={},
                    )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_EXCLUSIVE_HOST_AUTHORITY_REQUIRED",
            )
            self.assertEqual(persist.call_count, 2)
            gh_api.assert_not_called()

    def test_release_publish_requires_external_exclusive_host_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            asset_set_sha256 = adapter_module._canonical_sha256(
                adapter._local_asset_set()
            )
            _, draft_asset_identity_sha256 = _release_asset_fixture(adapter)
            expected = {
                "release_id": 240,
                "draft_asset_set_sha256": asset_set_sha256,
                "draft_asset_identity_sha256": draft_asset_identity_sha256,
            }
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter._require_external_exclusive_publish_host(expected)
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_EXCLUSIVE_HOST_AUTHORITY_REQUIRED",
            )
            self.assertEqual(
                caught.exception.receipt["external_side_effect_count"], 0
            )
            self.assertEqual(
                caught.exception.receipt["required_binding"]["version"],
                "V2.40",
            )
            self.assertEqual(
                caught.exception.receipt["required_binding"]["tag"],
                "v2.40",
            )

    def test_release_publish_rejects_same_bytes_with_new_asset_ids_before_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            local_assets = adapter._local_asset_set()
            asset_set_sha256 = adapter_module._canonical_sha256(local_assets)
            _, draft_asset_identity_sha256 = _release_asset_fixture(adapter)
            replacement_assets, _ = _release_asset_fixture(
                adapter, (3401, 3402, 3403, 3404)
            )
            live_draft = {
                "databaseId": 240,
                "isDraft": True,
                "isImmutable": False,
                "isPrerelease": False,
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "assets": replacement_assets,
            }
            expected = {
                "asset_set_sha256": asset_set_sha256,
                "draft_asset_set_sha256": asset_set_sha256,
                "draft_asset_identity_sha256": draft_asset_identity_sha256,
                "candidate_commit": COMMIT,
                "tag": "v2.40",
                "release_id": 240,
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
            }
            with mock.patch.object(
                adapter, "_release_json", return_value=live_draft
            ), mock.patch.object(
                adapter, "_require_write_authority"
            ), mock.patch.object(
                adapter, "_persist_verified_bundle"
            ) as persist, mock.patch.object(adapter, "_gh_api") as gh_api:
                with self.assertRaises(adapter_module.AdapterError) as caught:
                    adapter.execute(
                        operation_id="CP17.release_publish",
                        action="release_publish",
                        expected_before=expected,
                        parameters={},
                    )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_DRAFT_ASSET_IDENTITY",
            )
            persist.assert_not_called()
            gh_api.assert_not_called()
            self.assertFalse((workspace / "docs" / "release-state").exists())

    def test_release_publish_rechecks_asset_ids_after_observe_before_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            local_assets = adapter._local_asset_set()
            asset_set_sha256 = adapter_module._canonical_sha256(local_assets)
            original_assets, draft_asset_identity_sha256 = _release_asset_fixture(
                adapter
            )
            replacement_assets, _ = _release_asset_fixture(
                adapter, (3401, 3402, 3403, 3404)
            )
            base_release = {
                "databaseId": 240,
                "isDraft": True,
                "isImmutable": False,
                "isPrerelease": False,
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
            }
            expected = {
                "asset_set_sha256": asset_set_sha256,
                "draft_asset_set_sha256": asset_set_sha256,
                "draft_asset_identity_sha256": draft_asset_identity_sha256,
                "candidate_commit": COMMIT,
                "tag": "v2.40",
                "release_id": 240,
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
            }
            with mock.patch.object(
                adapter,
                "_release_json",
                side_effect=[
                    {**base_release, "assets": original_assets},
                    {**base_release, "assets": replacement_assets},
                ],
            ), mock.patch.object(
                adapter, "_require_write_authority"
            ), mock.patch.object(adapter, "_gh_api") as gh_api:
                with self.assertRaises(adapter_module.AdapterError) as caught:
                    adapter.execute(
                        operation_id="CP17.release_publish",
                        action="release_publish",
                        expected_before=expected,
                        parameters={},
                    )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_DRAFT_ASSET_IDENTITY",
            )
            gh_api.assert_not_called()
            self.assertFalse((workspace / "docs" / "release-state").exists())

    def test_release_publish_final_post_guard_read_blocks_all_drift_before_patch(
        self,
    ) -> None:
        drift_kinds = (
            "name",
            "body",
            "target",
            "target_main_alias",
            "prerelease",
            "asset_id",
            "asset_size",
            "asset_digest",
            "asset_digest_missing",
        )
        for drift_kind in drift_kinds:
            with self.subTest(drift_kind=drift_kind), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                _write_assets(workspace)
                adapter = _adapter(workspace)
                local_assets = adapter._local_asset_set()
                asset_set_sha256 = adapter_module._canonical_sha256(local_assets)
                original_assets, draft_asset_identity_sha256 = _release_asset_fixture(
                    adapter
                )
                base_release = {
                    "databaseId": 240,
                    "isDraft": True,
                    "isImmutable": False,
                    "isPrerelease": False,
                    "tagName": "v2.40",
                    "targetCommitish": COMMIT,
                    "name": adapter.release_title,
                    "body": adapter.release_body,
                    "assets": original_assets,
                }
                drifted = copy.deepcopy(base_release)
                if drift_kind == "name":
                    drifted["name"] = "tampered title"
                elif drift_kind == "body":
                    drifted["body"] = "tampered body"
                elif drift_kind == "target":
                    drifted["targetCommitish"] = "c" * 40
                elif drift_kind == "target_main_alias":
                    drifted["targetCommitish"] = "main"
                elif drift_kind == "prerelease":
                    drifted["isPrerelease"] = True
                elif drift_kind == "asset_id":
                    drifted["assets"][0]["id"] = 9999
                elif drift_kind == "asset_size":
                    drifted["assets"][0]["size"] += 1
                elif drift_kind == "asset_digest":
                    drifted["assets"][0]["digest"] = "sha256:" + "f" * 64
                else:
                    drifted["assets"][0].pop("digest")
                expected = {
                    "asset_set_sha256": asset_set_sha256,
                    "draft_asset_set_sha256": asset_set_sha256,
                    "draft_asset_identity_sha256": draft_asset_identity_sha256,
                    "candidate_commit": COMMIT,
                    "tag": "v2.40",
                    "release_id": 240,
                    "targetCommitish": COMMIT,
                    "name": adapter.release_title,
                    "body": adapter.release_body,
                }

                def verify_assets(release_value, *, expected_draft, expected_asset_identity_sha256):
                    self.assertTrue(expected_draft)
                    identity = adapter._release_asset_identity(release_value)
                    if identity["sha256"] != expected_asset_identity_sha256:
                        adapter_module._fail(
                            "E_V240_DRAFT_ASSET_IDENTITY",
                            "test final asset identity drift",
                        )
                    return {
                        "asset_set_sha256": asset_set_sha256,
                        "asset_identity_sha256": identity["sha256"],
                    }

                with mock.patch.object(
                    adapter,
                    "_release_json",
                    side_effect=[base_release, base_release, drifted],
                ), mock.patch.object(
                    adapter,
                    "_resolve_target_commitish",
                    side_effect=lambda target: (
                        COMMIT if target in {COMMIT, "main"} else target
                    ),
                ), mock.patch.object(
                    adapter, "_require_write_authority"
                ), mock.patch.object(
                    adapter,
                    "_persist_verified_bundle",
                    side_effect=verify_assets,
                ), mock.patch.object(
                    adapter, "_validate_remote_mutation_guard", return_value={}
                ) as guard, mock.patch.object(adapter, "_gh_api") as gh_api:
                    with self.assertRaises(adapter_module.AdapterError) as caught:
                        adapter.execute(
                            operation_id="CP17.release_publish",
                            action="release_publish",
                            expected_before=expected,
                            parameters={},
                        )
                self.assertIn(
                    caught.exception.receipt["error_code"],
                    {
                        "E_V240_REMOTE_RESOURCE_CONFLICT",
                        "E_V240_DRAFT_ASSET_IDENTITY",
                    },
                )
                self.assertEqual(
                    caught.exception.receipt["external_side_effect_count"], 0
                )
                guard.assert_called_once()
                gh_api.assert_not_called()

    def test_published_asset_download_rejects_new_ids_without_bundle_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            _, draft_asset_identity_sha256 = _release_asset_fixture(adapter)
            replacement_assets, _ = _release_asset_fixture(
                adapter, (3401, 3402, 3403, 3404)
            )
            published = {
                "databaseId": 240,
                "isDraft": False,
                "isImmutable": True,
                "isPrerelease": False,
                "tagName": "v2.40",
                "assets": replacement_assets,
            }
            with mock.patch.object(
                adapter, "_release_json", return_value=published
            ), mock.patch.object(
                adapter, "_download_release_asset"
            ) as download:
                observed = adapter.observe(
                    operation_id="CP17.published_asset_download",
                    action="published_asset_download",
                    expected_before={
                        "release_id": 240,
                        "draft_asset_identity_sha256": (
                            draft_asset_identity_sha256
                        ),
                    },
                    parameters={},
                )
            self.assertEqual(observed["classification"], "conflict")
            self.assertEqual(
                observed["details"]["asset_identity_error"],
                "E_V240_DRAFT_ASSET_IDENTITY",
            )
            download.assert_not_called()
            self.assertFalse((workspace / "docs" / "release-state").exists())

    def test_release_publish_marker_loss_adopts_only_full_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            asset_set_sha256 = adapter_module._canonical_sha256(
                adapter._local_asset_set()
            )
            remote_assets, draft_asset_identity_sha256 = _release_asset_fixture(
                adapter
            )
            expected = {
                "asset_set_sha256": asset_set_sha256,
                "draft_asset_set_sha256": asset_set_sha256,
                "draft_asset_identity_sha256": draft_asset_identity_sha256,
                "candidate_commit": COMMIT,
                "tag": "v2.40",
                "release_id": 240,
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
            }
            published = {
                "databaseId": 240,
                "isDraft": False,
                "isImmutable": True,
                "isPrerelease": False,
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "publishedAt": "2026-07-14T08:00:00Z",
                "assets": remote_assets,
            }

            def remote_ref(ref: str, *, peel: bool = False):
                if ref == "refs/heads/main":
                    return COMMIT
                return COMMIT if peel else "c" * 40

            with mock.patch.object(
                adapter, "_release_json", return_value=published
            ), mock.patch.object(
                adapter, "_latest_release", return_value={"id": 240, "tag_name": "v2.40"}
            ), mock.patch.object(
                adapter, "_remote_ref", side_effect=remote_ref
            ), mock.patch.object(
                adapter,
                "_remote_tag_identity",
                return_value={
                    "tag": "v2.40",
                    "annotated": True,
                    "tag_object": "c" * 40,
                    "peeled_commit": COMMIT,
                    "message": adapter_module.CANONICAL_TAG_MESSAGE,
                    "tagger_name": _release_tagger()["name"],
                    "tagger_email": _release_tagger()["email"],
                    "tagger_identity_sha256": _release_tagger()[
                        "identity_sha256"
                    ],
                },
            ), mock.patch.object(
                adapter,
                "_persist_verified_bundle",
                return_value={
                    "asset_set_sha256": asset_set_sha256,
                    "asset_identity_sha256": draft_asset_identity_sha256,
                    "assets": [],
                    "bundle_path": "/ignored/published-bundle",
                },
            ), mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
                adapter, "_run_release_adapter"
            ) as release_adapter:
                receipt = adapter.execute(
                    operation_id="CP17.release_publish",
                    action="release_publish",
                    expected_before=expected,
                    parameters={},
                )
            self.assertEqual(receipt["classification"], "exact")
            self.assertTrue(receipt["adopted_existing"])
            self.assertTrue(receipt["adopted_after_marker_loss"])
            self.assertEqual(receipt["external_side_effect_count"], 0)
            release_adapter.assert_not_called()

    def test_release_publish_marker_loss_rejects_reuploaded_asset_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            local_assets = adapter._local_asset_set()
            asset_set_sha256 = adapter_module._canonical_sha256(local_assets)
            _, draft_asset_identity_sha256 = _release_asset_fixture(adapter)
            replacement_assets, _ = _release_asset_fixture(
                adapter, (3401, 3402, 3403, 3404)
            )
            published = {
                "databaseId": 240,
                "isDraft": False,
                "isImmutable": True,
                "isPrerelease": False,
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "publishedAt": "2026-07-14T08:00:00Z",
                "assets": replacement_assets,
            }
            with mock.patch.object(
                adapter, "_release_json", return_value=published
            ), mock.patch.object(
                adapter, "_latest_release"
            ) as latest, mock.patch.object(
                adapter, "_persist_verified_bundle"
            ) as persist:
                observed = adapter.observe(
                    operation_id="CP17.release_publish",
                    action="release_publish",
                    expected_before={
                        "asset_set_sha256": asset_set_sha256,
                        "draft_asset_set_sha256": asset_set_sha256,
                        "draft_asset_identity_sha256": (
                            draft_asset_identity_sha256
                        ),
                        "candidate_commit": COMMIT,
                        "tag": "v2.40",
                        "release_id": 240,
                        "targetCommitish": COMMIT,
                        "name": adapter_module.CANONICAL_RELEASE_TITLE,
                        "body": adapter_module.CANONICAL_RELEASE_BODY,
                    },
                    parameters={},
                )
            self.assertEqual(observed["classification"], "conflict")
            self.assertEqual(
                observed["details"]["asset_identity_error"],
                "E_V240_DRAFT_ASSET_IDENTITY",
            )
            latest.assert_not_called()
            persist.assert_not_called()
            self.assertFalse((workspace / "docs" / "release-state").exists())

    def test_release_publish_identity_drift_is_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            asset_set_sha256 = adapter_module._canonical_sha256(
                adapter._local_asset_set()
            )
            remote_assets, draft_asset_identity_sha256 = _release_asset_fixture(
                adapter
            )
            expected = {
                "asset_set_sha256": asset_set_sha256,
                "draft_asset_set_sha256": asset_set_sha256,
                "draft_asset_identity_sha256": draft_asset_identity_sha256,
                "candidate_commit": COMMIT,
                "tag": "v2.40",
                "release_id": 240,
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
            }
            canonical = {
                "databaseId": 240,
                "isDraft": False,
                "isImmutable": True,
                "isPrerelease": False,
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "publishedAt": "2026-07-14T08:00:00Z",
                "assets": remote_assets,
            }
            cases = {
                "release_id": ({**canonical, "databaseId": 241}, COMMIT, asset_set_sha256),
                # The raw alias is forbidden even if it resolves to the frozen
                # candidate after main promotion.
                "target": ({**canonical, "targetCommitish": "main"}, COMMIT, asset_set_sha256),
                "body": ({**canonical, "body": "drift"}, COMMIT, asset_set_sha256),
                "assets": (canonical, COMMIT, "d" * 64),
            }
            for name, (release_value, resolved_target, observed_asset_set) in cases.items():
                with self.subTest(name=name), mock.patch.object(
                    adapter, "_release_json", return_value=release_value
                ), mock.patch.object(
                    adapter, "_latest_release", return_value={"id": 240, "tag_name": "v2.40"}
                ), mock.patch.object(
                    adapter,
                    "_resolve_target_commitish",
                    return_value=resolved_target,
                ), mock.patch.object(
                    adapter,
                    "_remote_ref",
                    side_effect=lambda ref, peel=False: COMMIT if peel else "c" * 40,
                ), mock.patch.object(
                    adapter,
                    "_remote_tag_identity",
                    return_value={
                        "tag_object": "c" * 40,
                        "peeled_commit": COMMIT,
                        "message": adapter_module.CANONICAL_TAG_MESSAGE,
                        "tagger_name": _release_tagger()["name"],
                        "tagger_email": _release_tagger()["email"],
                        "tagger_identity_sha256": _release_tagger()[
                            "identity_sha256"
                        ],
                    },
                ), mock.patch.object(
                    adapter,
                    "_persist_verified_bundle",
                    return_value={
                        "asset_set_sha256": observed_asset_set,
                        "asset_identity_sha256": draft_asset_identity_sha256,
                        "assets": [],
                        "bundle_path": "/ignored/published-bundle",
                    },
                ):
                    observed = adapter.observe(
                        operation_id="CP17.release_publish",
                        action="release_publish",
                        expected_before=expected,
                        parameters={},
                    )
                self.assertEqual(observed["classification"], "conflict")

    def test_draft_create_binds_canonical_target_title_and_body(self) -> None:
        adapter = _adapter(ROOT)
        expected = {
            "targetCommitish": COMMIT,
            "name": adapter_module.CANONICAL_RELEASE_TITLE,
            "body": adapter_module.CANONICAL_RELEASE_BODY,
        }
        canonical = {
            "databaseId": 240,
            "isDraft": True,
            "isImmutable": False,
            "isPrerelease": False,
            "tagName": "v2.40",
            "targetCommitish": COMMIT,
            "name": adapter_module.CANONICAL_RELEASE_TITLE,
            "body": adapter_module.CANONICAL_RELEASE_BODY,
            "assets": [],
        }
        with mock.patch.object(
            adapter, "_release_json", return_value=canonical
        ), mock.patch.object(
            adapter,
            "_remote_ref",
            side_effect=lambda ref, peel=False: COMMIT if peel else "c" * 40,
        ):
            exact = adapter.observe(
                operation_id="CP16.draft_create",
                action="draft_create",
                expected_before=expected,
                parameters={},
            )
        self.assertEqual(exact["classification"], "exact")
        with mock.patch.object(
            adapter,
            "_release_json",
            return_value={**canonical, "targetCommitish": "main"},
        ), mock.patch.object(
            adapter,
            "_resolve_target_commitish",
            return_value=COMMIT,
        ):
            alias_conflict = adapter.observe(
                operation_id="CP16.draft_create",
                action="draft_create",
                expected_before=expected,
                parameters={},
            )
        self.assertEqual(alias_conflict["classification"], "conflict")
        with mock.patch.object(
            adapter, "_release_json", return_value={**canonical, "body": "drift"}
        ), mock.patch.object(
            adapter,
            "_remote_ref",
            side_effect=lambda ref, peel=False: COMMIT if peel else "c" * 40,
        ):
            conflict = adapter.observe(
                operation_id="CP16.draft_create",
                action="draft_create",
                expected_before=expected,
                parameters={},
            )
        self.assertEqual(conflict["classification"], "conflict")

    def test_draft_create_command_uses_canonical_metadata(self) -> None:
        adapter = _adapter(ROOT)
        expected = {
            "targetCommitish": COMMIT,
            "name": adapter_module.CANONICAL_RELEASE_TITLE,
            "body": adapter_module.CANONICAL_RELEASE_BODY,
        }
        draft = {
            "databaseId": 240,
            "isDraft": True,
            "isImmutable": False,
            "isPrerelease": False,
            "tagName": "v2.40",
            "targetCommitish": COMMIT,
            "name": adapter_module.CANONICAL_RELEASE_TITLE,
            "body": adapter_module.CANONICAL_RELEASE_BODY,
            "assets": [],
        }
        commands: list[tuple[str, ...]] = []

        def run_command(argv, *, cwd, env=None):
            commands.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(
            adapter, "_release_json", side_effect=[None, draft]
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_validate_remote_mutation_guard", return_value={}
        ), mock.patch.object(adapter_module, "_run", side_effect=run_command):
            receipt = adapter.execute(
                operation_id="CP16.draft_create",
                action="draft_create",
                expected_before=expected,
                parameters={},
            )
        self.assertEqual(receipt["classification"], "exact")
        create = commands[0]
        self.assertEqual(create[create.index("--target") + 1], COMMIT)
        self.assertEqual(
            create[create.index("--title") + 1],
            adapter_module.CANONICAL_RELEASE_TITLE,
        )
        self.assertEqual(
            create[create.index("--notes") + 1],
            adapter_module.CANONICAL_RELEASE_BODY,
        )

    def test_release_rest_readback_keeps_name_and_body(self) -> None:
        adapter = _adapter(ROOT)
        payload = {
            "id": 240,
            "draft": True,
            "immutable": False,
            "prerelease": False,
            "tag_name": "v2.40",
            "target_commitish": COMMIT,
            "name": adapter_module.CANONICAL_RELEASE_TITLE,
            "body": adapter_module.CANONICAL_RELEASE_BODY,
            "published_at": None,
            "assets": [],
            "html_url": "https://example.invalid/release/v2.40",
        }
        with mock.patch.object(adapter, "_gh_api", return_value=payload) as gh_api:
            observed = adapter._release_json(240)
        gh_api.assert_called_once_with(
            "repos/vibe-coding-era/goal-teams/releases/240",
            not_found_ok=True,
        )
        self.assertEqual(observed["name"], adapter_module.CANONICAL_RELEASE_TITLE)
        self.assertEqual(observed["body"], adapter_module.CANONICAL_RELEASE_BODY)
        self.assertIs(observed["isPrerelease"], False)

    def test_release_rest_readback_rejects_numeric_id_substitution(self) -> None:
        adapter = _adapter(ROOT)
        payload = {
            "id": 241,
            "draft": True,
            "immutable": False,
            "tag_name": "v2.40",
            "target_commitish": COMMIT,
            "name": adapter_module.CANONICAL_RELEASE_TITLE,
            "body": adapter_module.CANONICAL_RELEASE_BODY,
            "published_at": None,
            "assets": [],
            "html_url": "https://example.invalid/release/v2.40",
        }
        with mock.patch.object(adapter, "_gh_api", return_value=payload), self.assertRaises(
            adapter_module.AdapterError
        ) as caught:
            adapter._release_json(240)
        self.assertEqual(
            caught.exception.receipt["error_code"], "E_V240_ADAPTER_READBACK"
        )

    def test_candidate_creation_uses_an_explicit_absent_force_with_lease(self) -> None:
        adapter = _adapter(ROOT)
        commands: list[tuple[str, ...]] = []

        def run_command(argv, *, cwd, env=None):
            commands.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(
            adapter, "_remote_ref", side_effect=[None, COMMIT]
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(adapter_module, "_run", side_effect=run_command):
            receipt = adapter.execute(
                operation_id="CP12.candidate_push",
                action="candidate_push",
                expected_before={"remote_candidate_commit": None},
                parameters={},
            )
        self.assertEqual(receipt["classification"], "exact")
        self.assertEqual(len(commands), 1)
        self.assertIn(
            "--force-with-lease=refs/heads/codex/v2.40:", commands[0]
        )
        self.assertIn(
            f"{COMMIT}:refs/heads/codex/v2.40", commands[0]
        )

    def test_tag_creation_uses_canonical_annotated_message(self) -> None:
        adapter = _adapter(ROOT)
        commands: list[tuple[str, ...]] = []
        command_environments: list[dict[str, str] | None] = []
        tagger = _release_tagger()

        def run_command(argv, *, cwd, env=None):
            commands.append(tuple(argv))
            command_environments.append(dict(env) if env is not None else None)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(
            adapter,
            "_remote_tag_identity",
            side_effect=[
                None,
                {
                    "tag": "v2.40",
                    "annotated": True,
                    "tag_object": "c" * 40,
                    "peeled_commit": COMMIT,
                    "message": adapter_module.CANONICAL_TAG_MESSAGE,
                    "tagger_name": tagger["name"],
                    "tagger_email": tagger["email"],
                    "tagger_identity_sha256": tagger["identity_sha256"],
                },
            ],
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_effective_release_tagger_identity", return_value=tagger
        ), mock.patch.object(
            adapter, "_validate_remote_mutation_guard", return_value={}
        ), mock.patch.object(
            adapter,
            "_local_tag_identity",
            side_effect=[
                None,
                {
                    "tag": "v2.40",
                    "annotated": True,
                    "tag_object": "c" * 40,
                    "peeled_commit": COMMIT,
                    "message": adapter_module.CANONICAL_TAG_MESSAGE,
                    "tagger_name": tagger["name"],
                    "tagger_email": tagger["email"],
                    "tagger_identity_sha256": tagger["identity_sha256"],
                },
            ],
        ), mock.patch.object(adapter_module, "_run", side_effect=run_command):
            receipt = adapter.execute(
                operation_id="CP15.tag_push",
                action="tag_push",
                expected_before={"remote_tag_commit": None},
                parameters={},
            )
        self.assertEqual(receipt["classification"], "exact")
        tag_command = next(command for command in commands if command[:2] == ("git", "tag"))
        self.assertEqual(
            tag_command[tag_command.index("-m") + 1],
            adapter_module.CANONICAL_TAG_MESSAGE,
        )
        tag_command_index = commands.index(tag_command)
        self.assertEqual(
            command_environments[tag_command_index],
            {
                "GIT_COMMITTER_NAME": tagger["name"],
                "GIT_COMMITTER_EMAIL": tagger["email"],
            },
        )
        push_command = next(command for command in commands if command[:2] == ("git", "push"))
        self.assertIn(
            "--force-with-lease=refs/tags/v2.40:",
            push_command,
        )
        self.assertIn("refs/tags/v2.40:refs/tags/v2.40", push_command)

    def test_tag_creation_rejects_a_local_lightweight_tag_without_push(self) -> None:
        adapter = _adapter(ROOT)
        tagger = _release_tagger()
        with mock.patch.object(
            adapter, "_remote_tag_identity", return_value=None
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_effective_release_tagger_identity", return_value=tagger
        ), mock.patch.object(
            adapter,
            "_local_tag_identity",
            return_value={
                "tag": "v2.40",
                "annotated": False,
                "tag_object": COMMIT,
                "peeled_commit": COMMIT,
                "message": None,
            },
        ), mock.patch.object(adapter_module, "_run") as run_command:
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP15.tag_push",
                    action="tag_push",
                    expected_before={"remote_tag_commit": None},
                    parameters={},
                )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_REMOTE_RESOURCE_CONFLICT",
        )
        run_command.assert_not_called()

    def test_fixture_release_tagger_fails_before_any_tag_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)

            def git(*arguments: str) -> subprocess.CompletedProcess[str]:
                result = subprocess.run(
                    ["git", *arguments],
                    cwd=source,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return result

            git("init", "-q", "-b", "main")
            git("config", "user.name", "Release Fixture")
            git("config", "user.email", "release-fixture@example.invalid")
            (source / "VERSION").write_text("V2.40\n", encoding="utf-8")
            common_dir = Path(git("rev-parse", "--git-common-dir").stdout.strip())
            if not common_dir.is_absolute():
                common_dir = source / common_dir
            config_path = common_dir / "config"
            config_before = config_path.read_bytes()

            adapter = adapter_module.GitHubAdapter(
                source_root=source,
                workspace_root=source,
                repository="vibe-coding-era/goal-teams",
                version="V2.40",
                candidate_commit=COMMIT,
                base_main_commit=BASE,
                authority={},
                execute_external_writes=False,
            )
            with mock.patch.object(
                adapter, "_remote_tag_identity", return_value=None
            ), mock.patch.object(adapter, "_require_write_authority"):
                with self.assertRaises(adapter_module.AdapterError) as caught:
                    adapter.execute(
                        operation_id="CP15.tag_push",
                        action="tag_push",
                        expected_before={"remote_tag_commit": None},
                        parameters={},
                    )
            self.assertEqual(
                caught.exception.receipt,
                {
                    "passed": False,
                    "error_code": "E_V240_RELEASE_TAGGER_IDENTITY",
                    "mutation_count": 0,
                    "external_side_effect_count": 0,
                },
            )
            self.assertEqual(git("tag", "--list").stdout, "")
            self.assertEqual(config_path.read_bytes(), config_before)

    def test_controlled_release_tagger_creates_exact_object_without_config_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)

            def git(*arguments: str) -> str:
                result = subprocess.run(
                    ["git", *arguments],
                    cwd=source,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()

            git("init", "-q", "-b", "main")
            tagger = _release_tagger()
            git("config", "user.name", tagger["name"])
            git("config", "user.email", tagger["email"])
            (source / "VERSION").write_text("V2.40\n", encoding="utf-8")
            (source / "payload.txt").write_text("release\n", encoding="utf-8")
            git("add", "VERSION", "payload.txt")
            git("commit", "-q", "-m", "release candidate")
            candidate = git("rev-parse", "HEAD")
            common_dir = Path(git("rev-parse", "--git-common-dir"))
            if not common_dir.is_absolute():
                common_dir = source / common_dir
            config_path = common_dir / "config"
            config_before = config_path.read_bytes()

            adapter = adapter_module.GitHubAdapter(
                source_root=source,
                workspace_root=source,
                repository="vibe-coding-era/goal-teams",
                version="V2.40",
                candidate_commit=candidate,
                base_main_commit=BASE,
                authority={},
                execute_external_writes=False,
            )
            remote_reads = 0

            def remote_tag(_tag: str):
                nonlocal remote_reads
                remote_reads += 1
                if remote_reads == 1:
                    return None
                return adapter._local_tag_identity()

            real_run = adapter_module._run
            commands: list[tuple[str, ...]] = []

            def run_without_remote(argv, *, cwd, env=None):
                commands.append(tuple(argv))
                if tuple(argv[:2]) == ("git", "push"):
                    return subprocess.CompletedProcess(argv, 0, "", "")
                return real_run(argv, cwd=cwd, env=env)

            with mock.patch.object(
                adapter, "_remote_tag_identity", side_effect=remote_tag
            ), mock.patch.object(
                adapter, "_require_write_authority"
            ), mock.patch.object(
                adapter, "_validate_remote_mutation_guard", return_value={}
            ), mock.patch.object(
                adapter_module, "_run", side_effect=run_without_remote
            ):
                receipt = adapter.execute(
                    operation_id="CP15.tag_push",
                    action="tag_push",
                    expected_before={"remote_tag_commit": None},
                    parameters={},
                )

            local_tag = adapter._local_tag_identity()
            self.assertIsNotNone(local_tag)
            self.assertEqual(local_tag["tagger_name"], tagger["name"])
            self.assertEqual(local_tag["tagger_email"], tagger["email"])
            self.assertEqual(
                receipt["details"]["tag_object"], local_tag["tag_object"]
            )
            self.assertEqual(config_path.read_bytes(), config_before)
            self.assertEqual(git("config", "user.name"), tagger["name"])
            self.assertEqual(git("config", "user.email"), tagger["email"])
            self.assertEqual(
                sum(command[:2] == ("git", "push") for command in commands), 1
            )

    def test_tagger_or_tag_object_drift_is_rejected(self) -> None:
        adapter = _adapter(ROOT)
        frozen = _release_tagger()
        drifted = _release_tagger(
            name="Different Release Maintainer",
            email="different-maintainer@goal-teams.org",
        )
        local_tag = {
            "tag": "v2.40",
            "annotated": True,
            "tag_object": "c" * 40,
            "peeled_commit": COMMIT,
            "message": adapter_module.CANONICAL_TAG_MESSAGE,
            "tagger_name": drifted["name"],
            "tagger_email": drifted["email"],
            "tagger_identity_sha256": drifted["identity_sha256"],
        }
        with mock.patch.object(
            adapter, "_remote_tag_identity", return_value=None
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_effective_release_tagger_identity", return_value=frozen
        ), mock.patch.object(
            adapter, "_local_tag_identity", return_value=local_tag
        ), mock.patch.object(adapter_module, "_run") as run_command:
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP15.tag_push",
                    action="tag_push",
                    expected_before={"remote_tag_commit": None},
                    parameters={},
                )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_RELEASE_TAGGER_IDENTITY",
        )
        run_command.assert_not_called()

        exact_local_tag = {
            **local_tag,
            "tagger_name": frozen["name"],
            "tagger_email": frozen["email"],
            "tagger_identity_sha256": frozen["identity_sha256"],
        }
        remote_tag = {**exact_local_tag, "tag_object": "d" * 40}
        commands: list[tuple[str, ...]] = []

        def run_command(argv, *, cwd, env=None):
            commands.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(
            adapter, "_remote_tag_identity", side_effect=[None, remote_tag]
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            adapter, "_effective_release_tagger_identity", return_value=frozen
        ), mock.patch.object(
            adapter, "_local_tag_identity", return_value=exact_local_tag
        ), mock.patch.object(
            adapter, "_validate_remote_mutation_guard", return_value={}
        ), mock.patch.object(adapter_module, "_run", side_effect=run_command):
            with self.assertRaises(adapter_module.AdapterError) as caught:
                adapter.execute(
                    operation_id="CP15.tag_push",
                    action="tag_push",
                    expected_before={"remote_tag_commit": None},
                    parameters={},
                )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_TAG_OBJECT_IDENTITY",
        )
        self.assertEqual(caught.exception.receipt["external_side_effect_count"], 1)
        self.assertEqual(
            sum(command[:2] == ("git", "push") for command in commands), 1
        )

    def test_publish_shell_is_a_numeric_id_read_only_download_verifier(self) -> None:
        script = (
            ROOT / "scripts" / "release" / "publish-github-release.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("gh release edit", script)
        self.assertNotIn("gh release download", script)
        self.assertNotIn("gh release create", script)
        self.assertNotIn("--method POST", script)
        self.assertNotIn("--method PATCH", script)
        self.assertNotIn("uploads.github.com", script)
        self.assertNotIn("GOAL_TEAMS_RELEASE_ORCHESTRATOR", script)
        self.assertIn('[[ "$ACTION" == "verify-download" ]]', script)
        self.assertIn('releases/$EXPECTED_RELEASE_ID', script)
        self.assertIn('releases/assets/$asset_id', script)

    def test_state_compare_and_swap_allows_only_one_concurrent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            docs = workspace / "docs"
            docs.mkdir()
            path = docs / "state.json"
            with mock.patch.object(release, "_workspace_root", return_value=workspace):
                original_sha = release._atomic_state_write(
                    path, {"generation": 0}, expected_sha256=None
                )
                barrier = threading.Barrier(2)

                def writer(generation: int):
                    barrier.wait()
                    try:
                        return release._atomic_state_write(
                            path, {"generation": generation}, expected_sha256=original_sha
                        )
                    except Exception as exc:  # machine receipt is asserted below
                        return getattr(exc, "receipt", None)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(writer, (1, 2)))
                successes = [value for value in results if isinstance(value, str)]
                failures = [value for value in results if isinstance(value, dict)]
                self.assertEqual(len(successes), 1)
                self.assertEqual(len(failures), 1)
                self.assertEqual(failures[0]["error_code"], "E_V240_STATE_CAS")
                self.assertIn(json.loads(path.read_text())["generation"], {1, 2})

    def test_installed_full_tree_detects_non_readme_runtime_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / "installed"
            bundle = root / "bundle"
            runtime = installed / "scripts" / "runtime.py"
            runtime.parent.mkdir(parents=True)
            bundle.mkdir()
            runtime.write_bytes(b"print('ok')\n")
            runtime.chmod(0o644)
            digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
            row = {
                "path": "scripts/runtime.py",
                "mode": "100644",
                "size": runtime.stat().st_size,
                "sha256": digest,
            }
            (bundle / "_files.sha256").write_text(
                f"{digest}\t100644\t{row['size']}\tscripts/runtime.py\n"
            )
            tree_input = (
                f"{row['path']}\0{row['mode']}\0{row['size']}\0{row['sha256']}\n"
            ).encode()
            tree_sha = hashlib.sha256(tree_input).hexdigest()
            (bundle / "_release.json").write_text(
                json.dumps({"tree_sha256": tree_sha}) + "\n"
            )
            snapshot_records = [
                {"path": "scripts", "type": "directory", "mode": 0o755},
                {
                    "path": "scripts/runtime.py",
                    "type": "file",
                    "mode": 0o644,
                    "sha256": digest,
                    "size": row["size"],
                },
            ]
            state = {
                "source_tree_digest": tree_sha,
                "bundle_tree_sha256": tree_sha,
                "skill_tree_digest": release._canonical_json_sha256(snapshot_records),
            }
            self.assertEqual(
                release._validate_installed_package_tree(installed, bundle, state)[
                    "file_count"
                ],
                1,
            )
            runtime.write_bytes(b"print('tampered')\n")
            with self.assertRaises(release.PolicyError) as caught:
                release._validate_installed_package_tree(installed, bundle, state)
            self.assertEqual(caught.exception.receipt["error_code"], "E_V240_INSTALL_IDENTITY")


if __name__ == "__main__":
    unittest.main()
