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
        yield namespace


class V240InstallerCanonicalHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.real_uid = os.getuid()
        self.real_home = Path(pwd.getpwuid(self.real_uid).pw_dir)
        self.temp = tempfile.TemporaryDirectory(
            prefix=".goal-teams-installer-v240-", dir=self.real_home
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
        original_lstat = Path.lstat

        def forged_lstat(path: Path) -> os.stat_result:
            observed = original_lstat(path)
            if path == code_home:
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
            with mock.patch.object(Path, "lstat", new=forged_lstat):
                with self.assertRaisesRegex(
                    runtime["InstallError"], "^E_RELEASE_TARGET_OWNER:"
                ):
                    runtime["validate_production_release_target"](identity)
        self.assertFalse((code_home / "state").exists())

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
            acquire.index("state_dir.mkdir"),
        )


def uuid_suffix() -> str:
    return uuid.uuid4().hex


if __name__ == "__main__":
    unittest.main()
