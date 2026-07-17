from __future__ import annotations

import importlib.util
import os
import pwd
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT


def _load_release_module():
    path = ROOT / "scripts" / "release" / "release.py"
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_release_canonical_home", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = _load_release_module()


class V240ReleaseCanonicalHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.uid = os.getuid()
        # The test replaces the passwd database result below, so the fixture
        # need not write into the real account home (which may be read-only in
        # a sandbox).  Keep it on a non-symlinked writable repository path.
        self.temp = tempfile.TemporaryDirectory(
            prefix=".goal-teams-release-home-", dir=ROOT
        )
        self.home = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _call(
        self,
        *,
        home_env: Path | None = None,
        codex_env: Path | None = None,
        euid: int | None = None,
        sudo: bool = False,
        passwd_home: Path | None = None,
    ) -> Path:
        account_home = passwd_home or self.home
        environment = {
            "HOME": str(home_env or self.home),
            "CODEX_HOME": str(codex_env or (self.home / ".codex")),
        }
        if sudo:
            environment.update({"SUDO_UID": str(self.uid), "SUDO_USER": "root"})
        account = types.SimpleNamespace(pw_dir=str(account_home))
        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch("os.getuid", return_value=self.uid),
            mock.patch("os.geteuid", return_value=self.uid if euid is None else euid),
            mock.patch("pwd.getpwuid", return_value=account),
        ):
            return RELEASE._canonical_codex_home()

    def test_exact_passwd_home_is_the_only_production_target(self) -> None:
        self.assertEqual(self._call(), self.home / ".codex")

    def test_fake_home_and_codex_home_are_rejected(self) -> None:
        other = self.home / "other"
        other.mkdir()
        for kwargs in (
            {"home_env": other},
            {"codex_env": other / ".codex"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(RELEASE.PolicyError) as caught:
                    self._call(**kwargs)
                self.assertEqual(
                    caught.exception.receipt["error_code"], "E_V240_INSTALL_TARGET"
                )

    def test_sudo_and_effective_uid_mismatch_are_rejected(self) -> None:
        for kwargs in (
            {"sudo": True},
            {"euid": self.uid + 1},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(RELEASE.PolicyError) as caught:
                    self._call(**kwargs)
                self.assertEqual(
                    caught.exception.receipt["error_code"], "E_V240_INSTALL_TARGET"
                )

    def test_symlinked_passwd_home_is_rejected(self) -> None:
        real = self.home / "real"
        real.mkdir()
        linked = self.home / "linked"
        linked.symlink_to(real, target_is_directory=True)
        with self.assertRaises(RELEASE.PolicyError) as caught:
            self._call(
                passwd_home=linked,
                home_env=linked,
                codex_env=linked / ".codex",
            )
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_INSTALL_TARGET")

    def test_foreign_owned_passwd_home_is_rejected(self) -> None:
        original = Path.lstat

        def forged(path: Path) -> os.stat_result:
            observed = original(path)
            if path == self.home:
                values = list(observed)
                values[4] = self.uid + 1
                return os.stat_result(values)
            return observed

        with mock.patch.object(Path, "lstat", new=forged):
            with self.assertRaises(RELEASE.PolicyError) as caught:
                self._call()
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_INSTALL_TARGET")

    def test_release_runtime_no_longer_uses_mutable_path_home(self) -> None:
        source = (ROOT / "scripts" / "release" / "release.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Path.home() / \".codex\"", source)
        self.assertGreaterEqual(source.count("_canonical_codex_home()"), 3)


if __name__ == "__main__":
    unittest.main()
