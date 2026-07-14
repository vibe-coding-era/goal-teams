from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
RELEASE_ENTRY = ROOT / "scripts" / "release" / "release.py"


def _load_release():
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_release_git_graph_tests", RELEASE_ENTRY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load_release()


class GitFixture:
    def __init__(self, test: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="v240-git-graph-")
        test.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "V240 Git Graph Test")
        self.git("config", "user.email", "git-graph@example.invalid")
        self.git("config", "commit.gpgSign", "false")
        self.write("value.txt", "safe\n")
        self.base = self.commit("base")
        self.write("value.txt", "candidate\n")
        self.candidate = self.commit("candidate")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def write(self, relative: str, value: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "--no-gpg-sign", "-m", message)
        return self.git("rev-parse", "HEAD")


class V240ReleaseGitGraphTests(unittest.TestCase):
    def assert_policy(self, code: str, action) -> None:
        with self.assertRaises(release.PolicyError) as caught:
            action()
        self.assertEqual(caught.exception.receipt["error_code"], code)
        self.assertEqual(caught.exception.receipt["external_side_effect_count"], 0)

    def test_clean_full_repository_is_accepted(self) -> None:
        fixture = GitFixture(self)
        receipt = release._assert_unmodified_git_object_graph(fixture.root)
        self.assertEqual(receipt["replace_ref_count"], 0)
        self.assertFalse(receipt["shallow"])
        self.assertFalse(receipt["partial_clone"])

    def test_replace_ref_is_rejected_and_fixed_git_reader_ignores_it(self) -> None:
        fixture = GitFixture(self)
        fixture.git("replace", fixture.candidate, fixture.base)

        self.assert_policy(
            "E_V240_GIT_OBJECT_GRAPH",
            lambda: release._assert_unmodified_git_object_graph(fixture.root),
        )
        actual_tree = fixture.git("--no-replace-objects", "rev-parse", f"{fixture.candidate}^{{tree}}")
        fixed_tree = release._run_fixed(
            ("git", "rev-parse", f"{fixture.candidate}^{{tree}}"),
            cwd=fixture.root,
        ).stdout.strip()
        replaced_tree = fixture.git("rev-parse", f"{fixture.candidate}^{{tree}}")
        self.assertEqual(fixed_tree, actual_tree)
        self.assertNotEqual(replaced_tree, actual_tree)

    def test_grafts_and_object_alternates_are_rejected(self) -> None:
        for relative in ("info/grafts", "objects/info/alternates"):
            with self.subTest(relative=relative):
                fixture = GitFixture(self)
                common = Path(fixture.git("rev-parse", "--git-common-dir"))
                if not common.is_absolute():
                    common = fixture.root / common
                path = common / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("forbidden\n", encoding="utf-8")
                self.assert_policy(
                    "E_V240_GIT_OBJECT_GRAPH",
                    lambda: release._assert_unmodified_git_object_graph(fixture.root),
                )

    def test_partial_clone_configuration_is_rejected(self) -> None:
        fixture = GitFixture(self)
        fixture.git("config", "remote.origin.promisor", "true")
        self.assert_policy(
            "E_V240_GIT_OBJECT_GRAPH",
            lambda: release._assert_unmodified_git_object_graph(fixture.root),
        )

    def test_dangerous_git_environment_is_rejected(self) -> None:
        fixture = GitFixture(self)
        with mock.patch.dict(os.environ, {"GIT_OBJECT_DIRECTORY": "/tmp/forged"}):
            self.assert_policy(
                "E_V240_GIT_OBJECT_GRAPH",
                lambda: release._assert_unmodified_git_object_graph(fixture.root),
            )


if __name__ == "__main__":
    unittest.main()
