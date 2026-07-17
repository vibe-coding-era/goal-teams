from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
import tempfile
import types
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from tests.v23.common import ROOT


INSTALLER = ROOT / "scripts" / "install" / "install-local.sh"


def _embedded_installer_source() -> str:
    shell = INSTALLER.read_text(encoding="utf-8")
    embedded = shell.split("<<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]
    return embedded.split("\nfor handled_signal in ", 1)[0]


def _identity(source_kind: str) -> dict[str, Any]:
    published = source_kind == "github_release_asset"
    return {
        "source_kind": source_kind,
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.40",
        "release_tag": "v2.40",
        "release_id": 240 if published else 0,
        "release_state": "published" if published else "local",
        "source_commit": "a" * 40,
        "source_git_tree_id": "b" * 40,
        "assets": [],
    }


@contextmanager
def _installer_runtime(
    *,
    passwd_home: Path,
    home: Path,
    code_home: Path,
    uid: int,
    euid: int,
    extra_env: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    environment = {
        "HOME": str(home),
        "CODEX_HOME": str(code_home),
        "PATH": os.environ.get("PATH", ""),
    }
    if extra_env:
        environment.update(extra_env)
    argv = [
        "install-local-embedded.py",
        str(ROOT),
        "--release-bundle",
        str(home / "bundle"),
        "--release-identity",
        str(home / "identity.json"),
    ]
    namespace: dict[str, Any] = {"__name__": "goal_teams_installer_test"}
    account = types.SimpleNamespace(pw_dir=str(passwd_home))
    with (
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch.object(sys, "argv", argv),
        mock.patch("os.getuid", return_value=uid),
        mock.patch("os.geteuid", return_value=euid),
        mock.patch("pwd.getpwuid", return_value=account),
    ):
        exec(compile(_embedded_installer_source(), str(INSTALLER), "exec"), namespace)
        try:
            yield namespace
        finally:
            namespace["release_install_lock"]()
            anchor = namespace.get("production_target_anchor")
            if anchor is not None:
                anchor.close()


class V240InstallerCanonicalHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.real_uid = os.getuid()
        self.real_home = Path(pwd.getpwuid(self.real_uid).pw_dir)
        self.temp = tempfile.TemporaryDirectory(
            prefix=".goal-teams-installer-v240-", dir=ROOT
        )
        self.fake_home = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _validated_identity(self, runtime: dict[str, Any], source_kind: str) -> dict[str, Any]:
        payload = json.dumps(_identity(source_kind), sort_keys=True).encode("utf-8")
        return runtime["parse_release_identity"](payload)

    def _run_shell(
        self,
        *,
        source_kind: str,
        home: Path,
        code_home: Path,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        bundle = self.fake_home / f"bundle-{source_kind}-{uuid_suffix()}"
        bundle.mkdir()
        identity = self.fake_home / f"identity-{source_kind}-{uuid_suffix()}.json"
        identity.write_text(
            json.dumps(_identity(source_kind), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        for inherited in (
            "INSTALL_REPORT",
            "GOAL_TEAMS_INSTALL_TEST_VALIDATION",
            "GOAL_TEAMS_RELEASE_REHEARSAL",
            "SUDO_UID",
            "SUDO_USER",
        ):
            environment.pop(inherited, None)
        environment.update(
            {
                "PYTHON": sys.executable,
                "HOME": str(home),
                "CODEX_HOME": str(code_home),
            }
        )
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            [
                str(INSTALLER),
                "--release-bundle",
                str(bundle),
                "--release-identity",
                str(identity),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_published_target_accepts_exact_passwd_home_and_owned_ancestors(self) -> None:
        code_home = self.fake_home / ".codex"
        (code_home / "skills").mkdir(parents=True)
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)

    def test_published_first_state_and_lock_creation_are_dirfd_anchored(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            runtime["acquire_install_lock"]()
            self.assertTrue((code_home / "state" / "goal-teams").is_dir())
            self.assertTrue((code_home / "state" / "goal-teams" / "install.lock").is_file())
            self.assertEqual(runtime["state_dir"], code_home / "state" / "goal-teams")
            self.assertNotIn("/dev/fd/", str(runtime["state_dir"]))

    def test_copy_path_closes_source_parent_when_destination_open_fails(self) -> None:
        code_home = self.fake_home / ".codex"
        source_parent = code_home / "source-parent"
        source_parent.mkdir(parents=True)
        source = source_parent / "source.txt"
        source.write_text("source\n", encoding="utf-8")
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            original_open_parent = anchor._open_parent
            captured: list[int] = []

            def fail_destination(path: Path, *, create_parents: bool = False):
                if not captured:
                    descriptor, name, owned = original_open_parent(
                        path, create_parents=create_parents
                    )
                    self.assertTrue(owned)
                    captured.append(descriptor)
                    return descriptor, name, owned
                raise runtime["InstallError"]("E_RELEASE_TARGET_TEST_DESTINATION")

            with mock.patch.object(anchor, "_open_parent", side_effect=fail_destination):
                with self.assertRaisesRegex(
                    runtime["InstallError"], "E_RELEASE_TARGET_TEST_DESTINATION"
                ):
                    anchor.copy_path(source, code_home / "destination" / "copy.txt")
            self.assertEqual(len(captured), 1)
            with self.assertRaises(OSError):
                os.fstat(captured[0])

    def test_production_install_uses_canonical_validation_and_fd_safe_rollback(self) -> None:
        code_home = self.fake_home / ".codex"
        old_skill = code_home / "skills" / "goal-teams"
        old_skill.mkdir(parents=True, mode=0o700)
        (old_skill / "old.txt").write_text("old\n", encoding="utf-8")
        agents = code_home / "agents"
        agents.mkdir(mode=0o700)
        old_agent = agents / "goal-test.toml"
        old_agent.write_text('name = "old"\n', encoding="utf-8")
        observed_validation_roots: list[Path] = []

        def assert_quarantine_receipts(report: dict[str, Any]) -> None:
            quarantine = code_home / "state" / "goal-teams" / "quarantine"
            actual = {
                path.relative_to(self.fake_home).as_posix()
                for path in quarantine.iterdir()
                if path.is_dir()
            }
            reported = {
                row["tombstone_ref"]
                for row in report.get("retained_mutation_quarantines", [])
            }
            self.assertEqual(reported, actual)

        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            runtime["release_bundle_preflight"] = {"identity": identity}
            runtime["release_bundle_verified"] = True
            runtime["acquire_install_lock"]()
            anchor = runtime["production_target_anchor"]
            digest = "c" * 64
            asset_names = (
                "goal-teams-V2.40.tar.gz",
                "SHA256SUMS",
                "_release.json",
                "_files.sha256",
            )
            runtime["source_info"].update(
                {
                    "source_kind": "github_release_asset",
                    "repository": "vibe-coding-era/goal-teams",
                    "release_tag": "v2.40",
                    "release_id": 240,
                    "release_state": "published",
                    "release_assets": [
                        {
                            "name": name,
                            "asset_id": index + 1,
                            "size": 1,
                            "sha256": digest,
                            "download_sha256": digest,
                        }
                        for index, name in enumerate(asset_names)
                    ],
                    "release_asset_sha256": digest,
                    "release_identity_sha256": "d" * 64,
                    "bundle_tree_sha256": "e" * 64,
                    "version": "V2.40",
                    "commit": "a" * 40,
                    "dirty": False,
                    "tree_digest": "e" * 64,
                    "tracked_tree_digest": "e" * 64,
                    "git_tree_id": "b" * 40,
                    "package_manifest_sha256": "f" * 64,
                }
            )
            runtime["package_files"].append(
                {"path": "new.txt", "sha256": digest, "size": 4, "mode": 0o644}
            )

            def materialize(destination: Path) -> None:
                anchor.create_dir(destination, pin=True)
                anchor.atomic_bytes(destination / "source.txt", b"source\n", mode=0o644)

            def validate(root: Path, _phase: str) -> None:
                self.assertTrue(root.is_absolute())
                self.assertNotIn("/dev/fd/", str(root))
                self.assertTrue(root.exists())
                anchor.revalidate()
                observed_validation_roots.append(root)

            def copy_selected(_selected: list[str], destination: Path) -> None:
                anchor.create_dir(destination)
                anchor.atomic_bytes(destination / "new.txt", b"new\n", mode=0o644)

            def prepare_minimal_agents(
                _stage_skill: Path, stage_agents: Path
            ) -> tuple[list[str], list[str]]:
                anchor.create_dir(stage_agents, pin=True)
                anchor.atomic_bytes(
                    stage_agents / "goal-test.toml", b'name = "new"\n', mode=0o644
                )
                return ["goal-test.toml"], []

            def fail_after_live_skill_switch(point: str) -> None:
                if point == "after_skill_switch":
                    raise runtime["InstallError"]("E_TEST_AFTER_SKILL_SWITCH")

            runtime.update(
                {
                    "materialize_release_bundle": materialize,
                    "prepare_release_source": lambda: ["source.txt"],
                    "replay_okf_manifest": lambda *_args: None,
                    "validate_skill": validate,
                    "validate_package_tree": lambda *_args: anchor.revalidate(),
                    "copy_package": copy_selected,
                    "prepare_agents": prepare_minimal_agents,
                    "maybe_fail": fail_after_live_skill_switch,
                }
            )

            with self.assertRaisesRegex(
                runtime["InstallError"], "^E_TEST_AFTER_SKILL_SWITCH$"
            ):
                runtime["install"]()

            self.assertEqual((old_skill / "old.txt").read_text(encoding="utf-8"), "old\n")
            self.assertFalse((old_skill / "new.txt").exists())
            self.assertEqual(old_agent.read_text(encoding="utf-8"), 'name = "old"\n')
            self.assertTrue(observed_validation_roots)
            self.assertTrue(all(str(path).startswith(str(code_home)) for path in observed_validation_roots))
            self.assertFalse(any(code_home.glob(".goal-teams-transaction-*")))
            self.assertFalse(any(code_home.glob(".goal-teams-restore-*")))
            report = json.loads(runtime["report_path"].read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed_rolled_back")
            self.assertEqual(report["error_code"], "E_TEST_AFTER_SKILL_SWITCH")
            assert_quarantine_receipts(report)

            anchor.remove_path(runtime["backup_root"] / runtime["stamp"])
            runtime["backed_up_components"].clear()
            runtime["maybe_fail"] = lambda _point: None
            runtime["report_path"] = runtime["report_root"] / "second-install.json"
            runtime["install"]()

            self.assertEqual((old_skill / "new.txt").read_text(encoding="utf-8"), "new\n")
            self.assertFalse((old_skill / "old.txt").exists())
            self.assertEqual(old_agent.read_text(encoding="utf-8"), 'name = "new"\n')
            self.assertIsNotNone(runtime["read_state"]())
            success_report = json.loads(runtime["report_path"].read_text(encoding="utf-8"))
            self.assertEqual(success_report["status"], "installed")
            assert_quarantine_receipts(success_report)
            self.assertFalse(any(code_home.glob(".goal-teams-transaction-*")))
            self.assertFalse(any(code_home.glob(".goal-teams-restore-*")))

    def test_published_target_rejects_effective_uid_mismatch(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid + 1,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            with self.assertRaisesRegex(
                runtime["InstallError"], "^E_RELEASE_PRODUCTION_EUID$"
            ):
                runtime["validate_production_release_target"](identity)
        self.assertFalse(code_home.exists())

    def test_published_target_rejects_symlinked_codex_home(self) -> None:
        code_home = self.fake_home / ".codex"
        link_target = self.fake_home / "link-target"
        link_target.mkdir()
        code_home.symlink_to(link_target, target_is_directory=True)
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            with self.assertRaisesRegex(
                runtime["InstallError"], "^E_RELEASE_TARGET_SYMLINK:"
            ):
                runtime["validate_production_release_target"](identity)
        self.assertEqual(list(link_target.iterdir()), [])

    def test_published_target_rejects_foreign_owned_existing_ancestor(self) -> None:
        code_home = self.fake_home / ".codex"
        code_home.mkdir()
        original_fstat = os.fstat
        observed_codex_inode = code_home.stat().st_ino

        def forged_fstat(descriptor: int) -> os.stat_result:
            observed = original_fstat(descriptor)
            if observed.st_ino == observed_codex_inode:
                fields = list(observed)
                fields[4] = self.real_uid + 1
                return os.stat_result(fields)
            return observed

        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            with mock.patch("os.fstat", side_effect=forged_fstat):
                with self.assertRaisesRegex(
                    runtime["InstallError"], "^E_RELEASE_TARGET_OWNER:"
                ):
                    runtime["validate_production_release_target"](identity)
        self.assertFalse((code_home / "state").exists())

    def test_published_target_rejects_group_or_world_writable_ancestor(self) -> None:
        code_home = self.fake_home / ".codex"
        code_home.mkdir(mode=0o700)
        code_home.chmod(0o777)
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            with self.assertRaisesRegex(
                runtime["InstallError"], "^E_RELEASE_TARGET_WRITABLE:.codex$"
            ):
                runtime["validate_production_release_target"](identity)
        self.assertFalse((code_home / "state").exists())

    def test_symlink_swap_after_check_cannot_mutate_wrong_target(self) -> None:
        code_home = self.fake_home / ".codex"
        code_home.mkdir(mode=0o700)
        original = self.fake_home / ".codex-original"
        wrong_target = self.fake_home / "wrong-target"
        wrong_target.mkdir(mode=0o700)
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            code_home.rename(original)
            code_home.symlink_to(wrong_target, target_is_directory=True)
            with self.assertRaisesRegex(
                runtime["InstallError"], "^E_RELEASE_TARGET_SYMLINK:.codex$"
            ):
                runtime["bind_production_target_io"]()
        self.assertEqual(list(wrong_target.iterdir()), [])
        self.assertFalse((original / "state").exists())

    def test_owner_drift_after_check_fails_before_first_state_mutation(self) -> None:
        code_home = self.fake_home / ".codex"
        code_home.mkdir(mode=0o700)
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            codex_fd = anchor.fd((".codex",))
            original_fstat = os.fstat

            def forged_fstat(descriptor: int) -> os.stat_result:
                observed = original_fstat(descriptor)
                if descriptor == codex_fd:
                    fields = list(observed)
                    fields[4] = self.real_uid + 1
                    return os.stat_result(fields)
                return observed

            with mock.patch("os.fstat", side_effect=forged_fstat):
                with self.assertRaisesRegex(
                    runtime["InstallError"], "^E_RELEASE_TARGET_OWNER:.codex$"
                ):
                    runtime["bind_production_target_io"]()
        self.assertFalse((code_home / "state").exists())

    def test_skill_switch_uses_held_parent_fd_after_last_check(self) -> None:
        code_home = self.fake_home / ".codex"
        code_home.mkdir(mode=0o700)
        wrong_target = self.fake_home / "wrong-skills-target"
        wrong_target.mkdir(mode=0o700)
        pinned_skills = self.fake_home / "pinned-skills"
        staged = self.fake_home / "staged-skill"
        staged.mkdir(mode=0o700)
        (staged / "marker.txt").write_text("anchored\n", encoding="utf-8")
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            runtime["bind_production_target_io"]()
            canonical_skills = code_home / "skills"
            anchor = runtime["production_target_anchor"]
            original_revalidate = anchor.revalidate
            swapped = False

            def swap_after_check() -> None:
                nonlocal swapped
                original_revalidate()
                if not swapped:
                    canonical_skills.rename(pinned_skills)
                    canonical_skills.symlink_to(wrong_target, target_is_directory=True)
                    swapped = True

            with mock.patch.object(anchor, "revalidate", side_effect=swap_after_check):
                with self.assertRaisesRegex(
                    runtime["InstallError"], "^E_RELEASE_TARGET_SYMLINK:skills$"
                ):
                    runtime["replace_path_to_target"](staged, runtime["skill_target"])
        self.assertEqual(list(wrong_target.iterdir()), [])
        self.assertEqual(
            (pinned_skills / "goal-teams" / "marker.txt").read_text(encoding="utf-8"),
            "anchored\n",
        )

    def test_pinned_remove_rejects_name_swap_without_deleting_substitute(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]

            transaction = anchor.create_unique_dir(self.fake_home, "txn-")
            (transaction / "original.txt").write_text("original\n", encoding="utf-8")
            saved_original = self.fake_home / "saved-original"
            transaction.rename(saved_original)
            transaction.mkdir(mode=0o700)
            (transaction / "victim.txt").write_text("victim\n", encoding="utf-8")

            with self.assertRaisesRegex(
                runtime["InstallError"], r"^E_RELEASE_TARGET_CHANGED:"
            ):
                anchor.remove_path(transaction)

            self.assertTrue((transaction / "victim.txt").is_file())
            self.assertTrue((saved_original / "original.txt").is_file())

    def test_pinned_replace_rejects_source_swap_after_revalidate(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]

            stage = anchor.create_unique_dir(self.fake_home, "stage-")
            (stage / "original.txt").write_text("original\n", encoding="utf-8")
            destination = self.fake_home / "live"
            saved_stage = self.fake_home / "saved-stage"
            original_revalidate = anchor.revalidate
            calls = 0

            def swap_source_after_initial_revalidate() -> None:
                nonlocal calls
                calls += 1
                original_revalidate()
                if calls == 1:
                    stage.rename(saved_stage)
                    stage.mkdir(mode=0o700)
                    (stage / "substitute.txt").write_text(
                        "substitute\n", encoding="utf-8"
                    )

            with mock.patch.object(
                anchor,
                "revalidate",
                side_effect=swap_source_after_initial_revalidate,
            ):
                with self.assertRaisesRegex(
                    runtime["InstallError"], r"^E_RELEASE_TARGET_CHANGED:"
                ):
                    anchor.replace_path(stage, destination)

            self.assertFalse(destination.exists())
            self.assertTrue((stage / "substitute.txt").is_file())
            self.assertTrue((saved_stage / "original.txt").is_file())

    def test_pinned_remove_rejects_swap_at_mutation_edge(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            transaction = anchor.create_unique_dir(self.fake_home, "txn-edge-")
            (transaction / "original.txt").write_text("original\n", encoding="utf-8")
            saved_original = self.fake_home / "saved-edge-original"
            original_assert = anchor._assert_pinned_entry
            swapped = False

            def swap_after_identity_assert(*args: Any, **kwargs: Any):
                nonlocal swapped
                metadata = original_assert(*args, **kwargs)
                if not swapped:
                    swapped = True
                    transaction.rename(saved_original)
                    transaction.mkdir(mode=0o700)
                    (transaction / "victim.txt").write_text(
                        "victim\n", encoding="utf-8"
                    )
                return metadata

            with mock.patch.object(
                anchor, "_assert_pinned_entry", side_effect=swap_after_identity_assert
            ):
                with self.assertRaisesRegex(
                    runtime["InstallError"], r"^E_RELEASE_TARGET_CHANGED:"
                ):
                    anchor.remove_path(transaction)

            self.assertTrue((transaction / "victim.txt").is_file())
            self.assertTrue((saved_original / "original.txt").is_file())

    def test_pinned_replace_rolls_back_swap_at_mutation_edge(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            stage = anchor.create_unique_dir(self.fake_home, "stage-edge-")
            (stage / "original.txt").write_text("original\n", encoding="utf-8")
            destination = self.fake_home / "live-edge"
            saved_stage = self.fake_home / "saved-edge-stage"
            original_assert = anchor._assert_pinned_entry
            calls = 0

            def swap_after_identity_assert(*args: Any, **kwargs: Any):
                nonlocal calls
                metadata = original_assert(*args, **kwargs)
                calls += 1
                if calls == 1:
                    stage.rename(saved_stage)
                    stage.mkdir(mode=0o700)
                    (stage / "substitute.txt").write_text(
                        "substitute\n", encoding="utf-8"
                    )
                return metadata

            with mock.patch.object(
                anchor, "_assert_pinned_entry", side_effect=swap_after_identity_assert
            ):
                with self.assertRaisesRegex(
                    runtime["InstallError"], r"^E_RELEASE_TARGET_CHANGED:"
                ):
                    anchor.replace_path(stage, destination)

            self.assertFalse(destination.exists())
            self.assertTrue((stage / "substitute.txt").is_file())
            self.assertTrue((saved_stage / "original.txt").is_file())

    def test_replace_does_not_overwrite_destination_inserted_after_absence_check(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            source = self.fake_home / "staged-agent.toml"
            destination = self.fake_home / "live-agent.toml"
            source.write_text("staged\n", encoding="utf-8")
            original_create = anchor._create_mutation_quarantine

            def insert_destination(*args: Any, **kwargs: Any):
                result = original_create(*args, **kwargs)
                destination.write_text("victim\n", encoding="utf-8")
                return result

            with mock.patch.object(
                anchor,
                "_create_mutation_quarantine",
                side_effect=insert_destination,
            ):
                with self.assertRaisesRegex(
                    runtime["InstallError"], r"^E_RELEASE_TARGET_(EXISTS|CHANGED):"
                ):
                    anchor.replace_path(source, destination)

            self.assertEqual(destination.read_text(encoding="utf-8"), "victim\n")
            self.assertEqual(source.read_text(encoding="utf-8"), "staged\n")

    def test_remove_file_recovers_known_sibling_swap_without_unlink(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            target = self.fake_home / "remove-agent.toml"
            victim = self.fake_home / "victim-agent.toml"
            target.write_text("target\n", encoding="utf-8")
            victim.write_text("victim\n", encoding="utf-8")
            original_assert = anchor._assert_pinned_entry
            calls = 0

            def swap_after_quarantine_check(*args: Any, **kwargs: Any):
                nonlocal calls
                metadata = original_assert(*args, **kwargs)
                calls += 1
                if calls == 2:
                    quarantine_fd = kwargs["parent_fd"]
                    os.rename(
                        "entry",
                        "saved-original",
                        src_dir_fd=quarantine_fd,
                        dst_dir_fd=quarantine_fd,
                    )
                    os.rename(
                        victim.name,
                        "entry",
                        src_dir_fd=anchor.fd(()),
                        dst_dir_fd=quarantine_fd,
                    )
                return metadata

            with mock.patch.object(
                anchor,
                "_assert_pinned_entry",
                side_effect=swap_after_quarantine_check,
            ):
                with self.assertRaisesRegex(
                    runtime["InstallError"], r"^E_RELEASE_TARGET_CHANGED:"
                ):
                    anchor.remove_path(target)

            self.assertEqual(target.read_text(encoding="utf-8"), "target\n")
            self.assertEqual(victim.read_text(encoding="utf-8"), "victim\n")

    def test_unlink_path_uses_reversible_quarantine(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            target = self.fake_home / "current.json"
            target.write_text("state\n", encoding="utf-8")
            anchor.unlink_path(target)
            self.assertFalse(target.exists())
            tombstones = list(
                (code_home / "state" / "goal-teams" / "quarantine").iterdir()
            )
            self.assertEqual(len(tombstones), 1)
            self.assertEqual(
                (tombstones[0] / "entry").read_text(encoding="utf-8"),
                "state\n",
            )
            self.assertEqual(
                runtime["retained_quarantines"][-1]["status"],
                "retained_no_automatic_delete",
            )

    def test_atomic_bytes_retains_previous_file_and_commits_new_inode(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            target = self.fake_home / "state.json"
            target.write_bytes(b"old\n")
            anchor.atomic_bytes(target, b"new\n", mode=0o600)
            self.assertEqual(target.read_bytes(), b"new\n")
            tombstones = list(
                (code_home / "state" / "goal-teams" / "quarantine").iterdir()
            )
            retained_files = [
                item / "entry" for item in tombstones if (item / "entry").is_file()
            ]
            self.assertEqual([item.read_bytes() for item in retained_files], [b"old\n"])

    def test_terminal_report_is_create_only_without_unreported_tombstone(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            runtime["bind_production_target_io"]()
            report = runtime["report_path"]
            report.write_text("concurrent-writer\n", encoding="utf-8")

            with self.assertRaisesRegex(
                runtime["InstallError"], r"^E_RELEASE_REPORT_EXISTS:"
            ):
                runtime["write_report"]("installed", "install")

            self.assertEqual(report.read_text(encoding="utf-8"), "concurrent-writer\n")
            self.assertEqual(list(report.parent.glob(f".{report.name}.pending-*")), [])
            quarantine = code_home / "state" / "goal-teams" / "quarantine"
            tombstones = list(quarantine.iterdir())
            self.assertEqual(len(tombstones), 1)
            self.assertEqual(
                json.loads((tombstones[0] / "entry").read_text(encoding="utf-8"))[
                    "status"
                ],
                "installed",
            )
            receipt = json.loads(
                (tombstones[0] / "receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(runtime["retained_quarantines"], [receipt])
            self.assertEqual(
                receipt["tombstone_ref"],
                tombstones[0].relative_to(self.fake_home).as_posix(),
            )

    def test_terminal_report_write_failure_never_exposes_partial_final(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            runtime["bind_production_target_io"]()
            anchor = runtime["production_target_anchor"]
            report = runtime["report_root"] / "fault.json"
            original_write = os.write
            calls = 0

            report_write_started = False

            def partial_then_fail(descriptor: int, data: Any) -> int:
                nonlocal calls
                nonlocal report_write_started
                calls += 1
                current = bytes(data)
                if current.startswith(b"{\n") and not report_write_started:
                    report_write_started = True
                    return original_write(descriptor, bytes(data[:7]))
                if report_write_started:
                    raise OSError("injected report write failure")
                return original_write(descriptor, data)

            with mock.patch("os.write", side_effect=partial_then_fail):
                with self.assertRaisesRegex(
                    runtime["InstallError"], r"^E_RELEASE_REPORT_PENDING:"
                ):
                    anchor.create_json_once(report, {"status": "installed"})

            self.assertFalse(report.exists())
            self.assertEqual(list(report.parent.glob(f".{report.name}.pending-*")), [])
            quarantine = code_home / "state" / "goal-teams" / "quarantine"
            tombstones = list(quarantine.iterdir())
            self.assertEqual(len(tombstones), 1)
            self.assertEqual((tombstones[0] / "entry").read_bytes(), b'{\n  "st')
            receipt = json.loads(
                (tombstones[0] / "receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(runtime["retained_quarantines"], [receipt])

    def test_terminal_report_entry_swap_is_evacuated_from_final_path(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            runtime["bind_production_target_io"]()
            anchor = runtime["production_target_anchor"]
            report = runtime["report_root"] / "swapped.json"
            original_rename = anchor._rename_noreplace
            swapped = False

            def swap_before_publish(
                source_name: str,
                destination_name: str,
                *,
                source_fd: int,
                destination_fd: int,
            ) -> None:
                nonlocal swapped
                if (
                    not swapped
                    and source_name == "entry"
                    and destination_name == report.name
                ):
                    swapped = True
                    os.rename(
                        "entry",
                        "saved-original",
                        src_dir_fd=source_fd,
                        dst_dir_fd=source_fd,
                    )
                    forged_fd = os.open(
                        "entry",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=source_fd,
                    )
                    try:
                        os.write(forged_fd, b'{"status":"forged"}\n')
                        os.fsync(forged_fd)
                    finally:
                        os.close(forged_fd)
                original_rename(
                    source_name,
                    destination_name,
                    source_fd=source_fd,
                    destination_fd=destination_fd,
                )

            with mock.patch.object(
                anchor,
                "_rename_noreplace",
                side_effect=swap_before_publish,
            ):
                with self.assertRaisesRegex(
                    runtime["InstallError"], r"^E_RELEASE_REPORT_CHANGED:"
                ):
                    anchor.create_json_once(report, {"status": "installed"})

            self.assertTrue(swapped)
            self.assertFalse(report.exists())
            quarantine = code_home / "state" / "goal-teams" / "quarantine"
            tombstones = list(quarantine.iterdir())
            self.assertEqual(len(tombstones), 1)
            self.assertEqual(
                json.loads(
                    (tombstones[0] / "saved-original").read_text(encoding="utf-8")
                )["status"],
                "installed",
            )
            conflicts = list(tombstones[0].glob("conflict-*"))
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(
                json.loads(conflicts[0].read_text(encoding="utf-8"))["status"],
                "forged",
            )
            receipt = json.loads(
                (tombstones[0] / "receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(runtime["retained_quarantines"], [receipt])

    def test_noreplace_primitive_preserves_existing_destination(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            source = self.fake_home / "source.txt"
            destination = self.fake_home / "destination.txt"
            source.write_text("source\n", encoding="utf-8")
            destination.write_text("destination\n", encoding="utf-8")
            with self.assertRaisesRegex(
                runtime["InstallError"], r"^E_RELEASE_TARGET_EXISTS:"
            ):
                anchor._rename_noreplace(
                    source.name,
                    destination.name,
                    source_fd=anchor.fd(()),
                    destination_fd=anchor.fd(()),
                )
            self.assertEqual(source.read_text(encoding="utf-8"), "source\n")
            self.assertEqual(
                destination.read_text(encoding="utf-8"), "destination\n"
            )

    def test_noreplace_primitive_fails_closed_on_unsupported_platform(self) -> None:
        code_home = self.fake_home / ".codex"
        with _installer_runtime(
            passwd_home=self.fake_home,
            home=self.fake_home,
            code_home=code_home,
            uid=self.real_uid,
            euid=self.real_uid,
        ) as runtime:
            identity = self._validated_identity(runtime, "github_release_asset")
            runtime["validate_production_release_target"](identity)
            anchor = runtime["production_target_anchor"]
            with mock.patch.object(sys, "platform", "unsupported-test"):
                with self.assertRaisesRegex(
                    runtime["InstallError"],
                    r"^E_RELEASE_PRODUCTION_NOREPLACE_PLATFORM$",
                ):
                    anchor._rename_noreplace(
                        "source",
                        "destination",
                        source_fd=anchor.fd(()),
                        destination_fd=anchor.fd(()),
                    )

    def test_fake_home_fails_before_target_creation(self) -> None:
        code_home = self.fake_home / ".codex"
        result = self._run_shell(
            source_kind="github_release_asset",
            home=self.fake_home,
            code_home=code_home,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("E_RELEASE_PRODUCTION_HOME", result.stderr)
        self.assertFalse(code_home.exists())

    def test_fake_codex_home_fails_before_target_creation(self) -> None:
        code_home = self.fake_home / ".codex"
        result = self._run_shell(
            source_kind="github_release_asset",
            home=self.real_home,
            code_home=code_home,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("E_RELEASE_PRODUCTION_CODEX_HOME", result.stderr)
        self.assertFalse(code_home.exists())

    def test_sudo_markers_fail_before_target_creation(self) -> None:
        code_home = self.fake_home / ".codex"
        result = self._run_shell(
            source_kind="github_release_asset",
            home=self.real_home,
            code_home=code_home,
            extra_env={"SUDO_UID": str(self.real_uid), "SUDO_USER": "attacker"},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("E_RELEASE_PRODUCTION_SUDO", result.stderr)
        self.assertFalse(code_home.exists())

    def test_local_rehearsal_keeps_explicit_temporary_codex_home(self) -> None:
        code_home = self.fake_home / ".codex"
        result = self._run_shell(
            source_kind="local_release_bundle",
            home=self.fake_home,
            code_home=code_home,
            extra_env={"GOAL_TEAMS_RELEASE_REHEARSAL": "1"},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("E_RELEASE_BUNDLE_ASSET_SET", result.stderr)
        self.assertNotIn("E_RELEASE_PRODUCTION_", result.stderr)
        self.assertFalse(code_home.exists())

    def test_canonical_gate_precedes_first_live_target_mutation(self) -> None:
        source = INSTALLER.read_text(encoding="utf-8")
        prepare = source.split("def prepare_release_bundle()", 1)[1].split(
            "def recheck_release_assets()", 1
        )[0]
        self.assertLess(
            prepare.index("validate_production_release_target(identity)"),
            prepare.index("expected_names ="),
        )
        acquire = source.split("def acquire_install_lock()", 1)[1].split(
            "def release_install_lock()", 1
        )[0]
        self.assertLess(
            acquire.index("validate_verified_release_target()"),
            acquire.index("bind_production_target_io()"),
        )
        self.assertLess(
            acquire.index("bind_production_target_io()"),
            acquire.index("production_target_anchor.open_lock()"),
        )
        anchor = source.split("class ProductionTargetAnchor:", 1)[1].split(
            "def validate_no_symlink_ancestors", 1
        )[0]
        self.assertIn("os.open(name, self._DIR_FLAGS, dir_fd=parent_fd)", anchor)
        self.assertIn("os.mkdir(name, mode=0o700, dir_fd=parent_fd)", anchor)
        self.assertIn("libc.renameatx_np", anchor)
        self.assertIn("libc.renameat2", anchor)
        self.assertIn("self._rename_noreplace(", anchor)
        self.assertNotIn("os.replace(", anchor)
        self.assertNotIn("os.unlink(", anchor)
        self.assertNotIn("shutil.rmtree(", anchor)
        self.assertNotIn("def fd_path", anchor)


def uuid_suffix() -> str:
    return uuid.uuid4().hex


if __name__ == "__main__":
    unittest.main()
