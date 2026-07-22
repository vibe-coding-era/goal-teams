from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT


def _load_version_checker():
    path = ROOT / "scripts" / "checks" / "check-version-sync.py"
    spec = importlib.util.spec_from_file_location("goal_teams_v240_version_sync", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load_version_checker()
PROTOCOL = ROOT / "references" / "release-packaging-protocol.md"
SCRIPT_README = ROOT / "scripts" / "release" / "README.md"
RELEASE_ENTRY = ROOT / "scripts" / "release" / "release.py"
COMMANDS = ("start", "doctor", "prepare", "promote", "status", "recover", "close")
EXECUTABLE_CHAIN = (
    "start(CP00) → promote(CP01) → 根恢复并切换到 clean main → "
    "doctor(CP02 前必须通过) → promote(CP02–CP08) → prepare(CP09–CP10) "
    "→ promote(CP11–CP17) → close(CP18)"
)
IMPOSSIBLE_LEGACY_CHAIN = (
    "start → doctor → promote(CP01–CP08) → prepare(CP09–CP10) "
    "→ promote(CP11–CP17) → close(CP18)"
)


class V240ReleaseDocumentationTests(unittest.TestCase):
    def test_root_release_blocks_are_localized_and_semantically_equal(self) -> None:
        zh_text = (ROOT / "README.md").read_text(encoding="utf-8")
        en_text = (ROOT / "README.en.md").read_text(encoding="utf-8")
        self.assertIn("当前发行：**V2.40**", zh_text)
        self.assertIn("[GitHub 发行页]", zh_text)
        self.assertIn("[发行说明](release/current/README.md)", zh_text)
        self.assertIn("Current release: **V2.40**", en_text)
        self.assertNotIn("Current release: **V2.40**", zh_text)
        self.assertEqual(
            CHECKER.read_release_block("README.md", "V2.40", "V2.40"),
            CHECKER.read_release_block("README.en.md", "V2.40", "V2.40"),
        )

    def test_development_projection_separates_published_and_product_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "release" / "current").mkdir(parents=True)
            (root / "README.md").write_text(
                CHECKER.expected_release_block("README.md", "V2.39")
                + "\n\n当前版本：`V2.40`\n",
                encoding="utf-8",
            )
            (root / "README.en.md").write_text(
                CHECKER.expected_release_block("README.en.md", "V2.39")
                + "\n\nCurrent version: `V2.40`\n",
                encoding="utf-8",
            )
            (root / "release" / "current" / "README.md").write_text(
                "# Goal Teams V2.39 Release\n\n"
                "Tokens consumed / Tokens 消耗: Unavailable / 未获取到\n"
                "Cache hit rate / Cache 命中率: Unavailable / 未获取到\n",
                encoding="utf-8",
            )
            telemetry_record = {
                "status": "unavailable",
                "value": None,
                "display_zh": "未获取到",
                "display_en": "Unavailable",
            }
            manifest = {
                "schema_version": "goal-teams-release-manifest-v2.39",
                "product_version": "V2.39",
                "docs_policy": "local-only",
                "claim_scope": "structural_governance",
                "cache_evidence": {
                    "structural_delivery_state": "passed",
                    "host_integration_state": "unavailable",
                    "live_cache_validation_state": "not_authorized",
                    "request_hit_rate_support_state": "unavailable",
                },
                "completion_telemetry": {
                    "tokens_consumed": telemetry_record,
                    "cache_hit_rate": telemetry_record,
                    "claim_policy": "no_estimation_without_trusted_host_usage_evidence",
                },
            }
            (root / "release" / "current" / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with mock.patch.object(CHECKER, "ROOT", root):
                CHECKER.validate_release_projection("V2.39", "V2.40")

    def test_active_runtime_identity_is_current_and_replay_only(self) -> None:
        profile, profile_path = CHECKER.validate_runtime_identity("V2.43")
        self.assertEqual(profile, "goal-teams-self-release-v2.43")
        self.assertEqual(
            profile_path,
            "references/profiles/goal-teams-self-release-v2.43.md",
        )

        original_read = CHECKER.read

        def stale_read(path: str) -> str:
            text = original_read(path)
            if path == "references/runtime/03-goal-loop.md":
                return text.replace(
                    "我是 Goal Teams Lead V2.43。",
                    "我是 Goal Teams Lead V2.39。",
                    1,
                )
            return text

        with mock.patch.object(CHECKER, "read", side_effect=stale_read):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                CHECKER.validate_runtime_identity("V2.43")

    def test_public_command_set_and_checkpoint_order_are_documented(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(RELEASE_ENTRY), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        help_text = proc.stdout + proc.stderr
        protocol = PROTOCOL.read_text(encoding="utf-8")
        script_readme = SCRIPT_README.read_text(encoding="utf-8")
        for command in COMMANDS:
            with self.subTest(command=command):
                self.assertIn(command, help_text)
                self.assertRegex(
                    protocol,
                    rf"release\.py {re.escape(command)} --input",
                )
                self.assertIn(f"`{command}`", script_readme)
        self.assertIn(EXECUTABLE_CHAIN, protocol)
        self.assertIn(EXECUTABLE_CHAIN, script_readme)
        self.assertNotIn(IMPOSSIBLE_LEGACY_CHAIN, protocol)
        self.assertNotIn(IMPOSSIBLE_LEGACY_CHAIN, script_readme)
        self.assertIn("CP01 前的 canonical root 已知为 dirty/non-main", protocol)
        self.assertIn("真正的 topology gate 位于 CP01 后、CP02 前", protocol)
        for number in range(19):
            self.assertIn(f"| CP{number:02d} |", protocol)
        self.assertIn("`status` 是任意非终态阶段的只读观测", protocol)
        self.assertIn("`recover` 只处理当前已持久化 intent", protocol)

    def test_all_documented_json_envelopes_are_valid_and_cover_public_shapes(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        blocks = [
            json.loads(payload)
            for payload in re.findall(r"```json\n(.*?)\n```", protocol, flags=re.DOTALL)
        ]
        self.assertEqual(len(blocks), 8)
        start, doctor, status, promote, next_before, recover, prepare, close = blocks

        state_envelopes = (start, doctor, status, promote, recover, prepare, close)
        for envelope in state_envelopes:
            with self.subTest(state_path=envelope["state_path"]):
                state_path = Path(envelope["state_path"])
                self.assertTrue(state_path.is_absolute())
                self.assertTrue(
                    state_path.as_posix().endswith(
                        "/goal-teams/docs/release-state/V2.40/promotion-state.json"
                    )
                )
                self.assertNotIn("<canonical-root>", envelope["state_path"])

        self.assertEqual(
            set(start),
            {
                "state_path",
                "repository",
                "version",
                "base_main_commit",
                "candidate_commit",
                "candidate_tree",
                "scope",
            },
        )
        self.assertEqual(
            set(start["scope"]),
            {
                "repository",
                "version",
                "candidate_commit",
                "owner_run_id",
                "locked_scope",
                "route_receipt_sha256",
                "spec_sha256",
                "done_criteria",
            },
        )
        self.assertEqual(
            set(doctor),
            {"state_path", "expected_state_sha256", "expected_scope"},
        )
        self.assertEqual(set(status), {"state_path", "expected_state_sha256"})
        self.assertEqual(promote["checkpoint_id"], "CP01")
        self.assertIn("CP01.legacy_recovery", promote["operation_authorizations"])
        self.assertEqual(
            next_before,
            {
                "next_checkpoint_expected_before": {
                    "CP12.candidate_push": {"remote_candidate_commit": None}
                }
            },
        )
        self.assertEqual(recover["checkpoint_id"], "CP12")
        self.assertIs(recover["execute_external_writes"], True)
        self.assertIs(recover["resume_external_writes"], True)
        candidate_auth = recover["operation_authorizations"]["CP12.candidate_push"]
        self.assertEqual(candidate_auth["mode"], "execute_github")
        self.assertEqual(
            candidate_auth["expected_before"],
            {"remote_candidate_commit": None},
        )
        self.assertEqual(set(prepare), {"state_path", "expected_state_sha256"})
        self.assertEqual(close["checkpoint_id"], "CP18")
        self.assertEqual(
            close["archive_index_path"],
            "/absolute/path/to/goal-teams/docs/archive/releases/V2.40/close-index.json",
        )
        self.assertEqual(
            set(close["operation_authorizations"]),
            {"CP18.promotion_lock_finalize", "CP18.archive_close"},
        )
        finalize = close["operation_authorizations"]["CP18.promotion_lock_finalize"]
        self.assertEqual(
            finalize["expected_before"]["ruleset_id"],
            finalize["parameters"]["ruleset_id"],
        )
        self.assertNotEqual(
            finalize["expected_before"]["ruleset_name"],
            finalize["parameters"]["ruleset_name"],
        )

    def test_start_and_close_use_one_canonical_absolute_state(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        script_readme = SCRIPT_README.read_text(encoding="utf-8")
        for text in (protocol, script_readme):
            self.assertIn("start", text)
            self.assertIn("candidate worktree", text)
            self.assertIn("close", text)
            self.assertIn("canonical root", text)
            self.assertIn("state_path", text)
            self.assertIn("绝对路径", text)
            self.assertNotIn('"state_path": "docs/release-state/', text)

    def test_cp18_archive_root_is_canonical_everywhere(self) -> None:
        paths = {
            PROTOCOL: "V2.40",
            ROOT / "references" / "profiles" / "goal-teams-self-release-v2.43.md": "V2.43",
            ROOT / "prompts" / "lead" / "audit.md": "V2.43",
        }
        for path, version in paths.items():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertIn(f"docs/archive/releases/{version}/", text)
                self.assertNotIn(f"docs/archive/{version}/", text)

    def test_public_docs_require_an_explicit_python_311_interpreter(self) -> None:
        for path in (PROTOCOL, SCRIPT_README):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertIn('PYTHON_BIN="${PYTHON:', text)
                self.assertIn('"$PYTHON_BIN" -c', text)
                self.assertIn("sys.version_info >= (3, 11)", text)
                self.assertNotRegex(text, r"(?m)^python3 scripts/release/release\.py")

    def test_ci_approval_binds_release_actor_separately_from_reviewer(self) -> None:
        text = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("release_actor_id", text)
        self.assertIn("github_authority.actor_id", text)
        self.assertIn("triggering_actor_id", text)
        self.assertIn("run_attempt > 1", text)
        self.assertIn("reviewer", text)
        self.assertIn("E_V240_CI_TRUST_BINDING", text)

    def test_release_adoption_contract_freezes_public_metadata_and_assets(self) -> None:
        text = PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("Goal Teams V2.40", text)
        self.assertIn(
            "Goal Teams V2.40. See release/current/README.md in the tagged source.",
            text,
        )
        self.assertIn("persisted release ID", text)
        self.assertIn("asset_set_sha256", text)
        self.assertIn("conflict", text)


if __name__ == "__main__":
    unittest.main()
