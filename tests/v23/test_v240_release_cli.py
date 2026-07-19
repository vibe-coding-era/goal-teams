from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
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


def _final_main_ruleset_payload() -> dict[str, object]:
    return {
        "name": "goal-teams-main-protection",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
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


class V240ReleaseCliSecurityTests(unittest.TestCase):
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
            },
        ):
            identity = adapter._remote_tag_identity("v2.40")
        self.assertEqual(identity["peeled_commit"], COMMIT)
        self.assertEqual(identity["message"], adapter_module.CANONICAL_TAG_MESSAGE)

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
        intent = "9" * 64
        title = f"Goal Teams V2.40 release {intent}"
        workflow = ".github/workflows/release-gate.yml"
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": workflow,
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
        mutate.assert_called_once()  # workflow blob read only; no gh workflow dispatch

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

    def test_finalize_executes_one_put_between_bound_old_and_final_rulesets(self) -> None:
        temporary = {
            "name": "goal-teams-promotion-lock-V2.40-bbbbbbbb",
            "target": "branch",
            "enforcement": "active",
            "bypass_actors": [
                {"actor_id": 240, "actor_type": "User", "bypass_mode": "always"}
            ],
            "conditions": {
                "ref_name": {"include": ["refs/heads/main"], "exclude": []}
            },
            "rules": [{"type": "update"}],
        }
        final = _final_main_ruleset_payload()
        ruleset_id = 24014
        expected_before = {
            "ruleset_id": ruleset_id,
            "ruleset_name": temporary["name"],
            "ruleset_payload": temporary,
            "ruleset_sha256": adapter_module._canonical_sha256(
                adapter_module.normalize_ruleset(temporary)
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
        mutated = False
        lookups: list[str] = []

        def ruleset_by_name(name: str):
            lookups.append(name)
            if mutated:
                return None if name == temporary["name"] else {"id": ruleset_id, **final}
            return {"id": ruleset_id, **temporary} if name == temporary["name"] else None

        def run_put(argv, *, cwd, env=None):
            nonlocal mutated
            self.assertFalse(mutated)
            self.assertIn(f"rulesets/{ruleset_id}", argv[2])
            self.assertIn("PUT", argv)
            mutated = True
            return subprocess.CompletedProcess(argv, 0, "", "")

        adapter = _adapter(ROOT)
        with mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
            adapter, "_ruleset_by_name", side_effect=ruleset_by_name
        ), mock.patch.object(adapter_module, "_run", side_effect=run_put) as put:
            receipt = adapter.execute(
                operation_id="CP18.promotion_lock_finalize",
                action="promotion_lock_finalize",
                expected_before=expected_before,
                parameters=parameters,
            )
        self.assertTrue(mutated)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(receipt["classification"], "exact")
        self.assertEqual(receipt["external_side_effect_count"], 1)
        self.assertEqual(
            lookups,
            [temporary["name"], final["name"], final["name"], temporary["name"]],
        )

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

    def test_ci_approval_does_not_require_preknown_remote_workflow_id(self) -> None:
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_blob_sha": "d" * 40,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }
        receipt = {
            **approval,
            "actor_id": 240,
            "triggering_actor_id": 240,
            "workflow_id": 240,
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

    def test_ci_actor_chain_rejects_other_positive_actor(self) -> None:
        approval = {
            "release_actor_id": 240,
            "head_sha": COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_blob_sha": "d" * 40,
            "required_jobs": ["check-ubuntu", "check-macos", "release-asset-gate"],
        }
        receipt = {
            **approval,
            "actor_id": 241,
            "triggering_actor_id": 241,
            "workflow_id": 240,
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

    def test_ruleset_get_response_normalizes_to_create_payload(self) -> None:
        payload = {
            "name": "goal-teams-promotion-lock-V2.40-bbbbbbbbbbbb",
            "target": "branch",
            "enforcement": "active",
            "bypass_actors": [
                {"actor_id": 240, "actor_type": "User", "bypass_mode": "always"}
            ],
            "conditions": {
                "ref_name": {"include": ["refs/heads/main"], "exclude": []}
            },
            "rules": [{"type": "update"}],
        }
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

    def test_final_main_ruleset_rejects_a_weak_subset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = _adapter(Path(directory))
            base = {
                "name": "goal-teams-main-protection",
                "target": "branch",
                "enforcement": "active",
                "bypass_actors": [],
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
            }
            draft_without_asset = {
                "databaseId": 240,
                "isDraft": True,
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

            def fake_download(argv, *, cwd, env=None):
                target = Path(argv[argv.index("--dir") + 1]) / "_files.sha256"
                shutil.copyfile(path, target)
                return subprocess.CompletedProcess(argv, 0, "", "")

            with mock.patch.object(adapter, "_release_json", return_value=release_with_asset), mock.patch.object(
                adapter_module, "_run", side_effect=fake_download
            ):
                exact = adapter.observe(
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    expected_before=expected,
                    parameters={},
                )
            self.assertEqual(exact["classification"], "exact")

            def fake_conflict(argv, *, cwd, env=None):
                target = Path(argv[argv.index("--dir") + 1]) / "_files.sha256"
                target.write_bytes(b"x" * path.stat().st_size)
                return subprocess.CompletedProcess(argv, 0, "", "")

            with mock.patch.object(adapter, "_release_json", return_value=release_with_asset), mock.patch.object(
                adapter_module, "_run", side_effect=fake_conflict
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
            }
            uploaded = {"value": False}

            def release_json():
                assets = []
                if uploaded["value"]:
                    assets = [{"id": 2404, "name": "_files.sha256", "size": path.stat().st_size}]
                return {"databaseId": 240, "isDraft": True, "tagName": "v2.40", "assets": assets}

            def fake_run(argv, *, cwd, env=None):
                if "upload" in argv:
                    uploaded["value"] = True
                elif "download" in argv:
                    target = Path(argv[argv.index("--dir") + 1]) / "_files.sha256"
                    shutil.copyfile(path, target)
                return subprocess.CompletedProcess(argv, 0, "", "")

            with mock.patch.object(adapter, "_release_json", side_effect=release_json), mock.patch.object(
                adapter, "_require_write_authority"
            ), mock.patch.object(adapter_module, "_run", side_effect=fake_run):
                receipt = adapter.execute(
                    operation_id="CP16.asset_upload_files",
                    action="asset_upload",
                    expected_before=expected,
                    parameters={},
                )
            self.assertTrue(uploaded["value"])
            self.assertEqual(receipt["classification"], "exact")
            self.assertEqual(receipt["external_side_effect_count"], 1)

    def test_release_publish_download_verification_precedes_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            assets = adapter._local_asset_set()
            asset_set_sha256 = adapter_module._canonical_sha256(assets)
            draft = {
                "databaseId": 240,
                "isDraft": True,
                "isImmutable": False,
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "assets": [],
            }
            published = {
                **draft,
                "isDraft": False,
                "isImmutable": True,
            }
            releases = iter((draft, draft, published))
            actions: list[str] = []
            with mock.patch.object(adapter, "_release_json", side_effect=lambda: next(releases)), mock.patch.object(
                adapter, "_latest_release", return_value={"id": 240, "tag_name": "v2.40"}
            ), mock.patch.object(
                adapter,
                "_remote_tag_identity",
                return_value={
                    "tag": "v2.40",
                    "annotated": True,
                    "tag_object": "c" * 40,
                    "peeled_commit": COMMIT,
                    "message": adapter_module.CANONICAL_TAG_MESSAGE,
                },
            ), mock.patch.object(
                adapter,
                "_persist_verified_bundle",
                return_value={
                    "asset_set_sha256": asset_set_sha256,
                    "assets": [],
                    "bundle_path": "/ignored/published-bundle",
                },
            ), mock.patch.object(adapter, "_require_write_authority"), mock.patch.object(
                adapter, "_run_release_adapter", side_effect=lambda action: actions.append(action)
            ):
                receipt = adapter.execute(
                    operation_id="CP17.release_publish",
                    action="release_publish",
                    expected_before={
                        "asset_set_sha256": asset_set_sha256,
                        "draft_asset_set_sha256": asset_set_sha256,
                        "candidate_commit": COMMIT,
                        "tag": "v2.40",
                        "release_id": 240,
                        "targetCommitish": COMMIT,
                        "name": adapter_module.CANONICAL_RELEASE_TITLE,
                        "body": adapter_module.CANONICAL_RELEASE_BODY,
                    },
                    parameters={},
                )
            self.assertEqual(actions, ["download", "publish"])
            self.assertEqual(receipt["classification"], "exact")

    def test_release_publish_marker_loss_adopts_only_full_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            asset_set_sha256 = adapter_module._canonical_sha256(
                adapter._local_asset_set()
            )
            expected = {
                "asset_set_sha256": asset_set_sha256,
                "draft_asset_set_sha256": asset_set_sha256,
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
                "tagName": "v2.40",
                "targetCommitish": "main",
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "publishedAt": "2026-07-14T08:00:00Z",
                "assets": [],
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
                },
            ), mock.patch.object(
                adapter,
                "_persist_verified_bundle",
                return_value={
                    "asset_set_sha256": asset_set_sha256,
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

    def test_release_publish_identity_drift_is_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_assets(workspace)
            adapter = _adapter(workspace)
            asset_set_sha256 = adapter_module._canonical_sha256(
                adapter._local_asset_set()
            )
            expected = {
                "asset_set_sha256": asset_set_sha256,
                "draft_asset_set_sha256": asset_set_sha256,
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
                "tagName": "v2.40",
                "targetCommitish": COMMIT,
                "name": adapter_module.CANONICAL_RELEASE_TITLE,
                "body": adapter_module.CANONICAL_RELEASE_BODY,
                "publishedAt": "2026-07-14T08:00:00Z",
                "assets": [],
            }
            cases = {
                "release_id": ({**canonical, "databaseId": 241}, COMMIT, asset_set_sha256),
                "target": ({**canonical, "targetCommitish": "main"}, BASE, asset_set_sha256),
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
                    "_persist_verified_bundle",
                    return_value={
                        "asset_set_sha256": observed_asset_set,
                        "assets": [],
                        "bundle_path": "/ignored/published-bundle",
                    },
                ), mock.patch.object(
                    adapter, "_validate_transport_authority", return_value={}
                ), mock.patch.object(
                    adapter,
                    "_remote_tag_identity",
                    return_value={
                        "tag_object": "c" * 40,
                        "peeled_commit": COMMIT,
                        "message": adapter_module.CANONICAL_TAG_MESSAGE,
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
            "tagName": "v2.40",
            "targetCommitish": "v2.40",
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
            "tag_name": "v2.40",
            "target_commitish": COMMIT,
            "name": adapter_module.CANONICAL_RELEASE_TITLE,
            "body": adapter_module.CANONICAL_RELEASE_BODY,
            "published_at": None,
            "assets": [],
            "html_url": "https://example.invalid/release/v2.40",
        }
        completed = subprocess.CompletedProcess(
            ["gh"], 0, json.dumps(payload), ""
        )
        with mock.patch.object(subprocess, "run", return_value=completed):
            observed = adapter._release_json()
        self.assertEqual(observed["name"], adapter_module.CANONICAL_RELEASE_TITLE)
        self.assertEqual(observed["body"], adapter_module.CANONICAL_RELEASE_BODY)

    def test_tag_creation_uses_canonical_annotated_message(self) -> None:
        adapter = _adapter(ROOT)
        commands: list[tuple[str, ...]] = []

        def run_command(argv, *, cwd, env=None):
            commands.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")

        local_tag_absent = subprocess.CompletedProcess(["git"], 1, "", "missing")
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
                },
            ],
        ), mock.patch.object(
            adapter, "_require_write_authority"
        ), mock.patch.object(
            subprocess, "run", return_value=local_tag_absent
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
