"""Negative tests for immutable Git reads in the V2.40 release helpers."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

from tests.v23.common import ROOT


BUILD_ENTRY = ROOT / "scripts" / "release" / "build-release.py"
VALIDATE_ENTRY = ROOT / "scripts" / "release" / "validate-release.py"
PUBLISH_ENTRY = ROOT / "scripts" / "release" / "publish-github-release.sh"
OFFICIAL_REMOTE = "git@github.com:vibe-coding-era/goal-teams.git"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load(BUILD_ENTRY, "v240_build_release_git_trust")
VALIDATE = _load(VALIDATE_ENTRY, "v240_validate_release_git_trust")


class GitFixture:
    def __init__(self, case: unittest.TestCase) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="v240-git-trust-")
        case.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "V2.40 Test")
        self.git("config", "user.email", "v240@example.invalid")
        self.git("remote", "add", "origin", OFFICIAL_REMOTE)
        (self.root / "payload.txt").write_text("first\n", encoding="utf-8")
        self.git("add", "payload.txt")
        self.git("commit", "-q", "-m", "first")
        self.first_commit = self.git("rev-parse", "HEAD")
        self.first_blob = self.git("rev-parse", "HEAD:payload.txt")
        (self.root / "payload.txt").write_text("second\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "second")
        self.second_commit = self.git("rev-parse", "HEAD")
        self.second_blob = self.git("rev-parse", "HEAD:payload.txt")

    def git(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise AssertionError(result.stderr)
        return result.stdout.strip()

    @property
    def git_dir(self) -> Path:
        value = Path(self.git("rev-parse", "--git-dir"))
        return value if value.is_absolute() else self.root / value

    @property
    def common_dir(self) -> Path:
        value = Path(self.git("rev-parse", "--git-common-dir"))
        return value if value.is_absolute() else self.root / value

    def install_publish_script(self) -> Path:
        target = self.root / "scripts" / "release" / PUBLISH_ENTRY.name
        target.parent.mkdir(parents=True)
        shutil.copy2(PUBLISH_ENTRY, target)
        target.chmod(0o755)
        return target


class V240ReleaseGitTrustTests(unittest.TestCase):
    modules = (BUILD, VALIDATE)

    def assert_git_trust_failure(self, module: ModuleType, action: object) -> None:
        with self.assertRaises(module.V240GitTrustError) as failure:
            action()  # type: ignore[operator]
        self.assertEqual(
            failure.exception.receipt,
            {
                "passed": False,
                "error_code": "E_V240_GIT_OBJECT_GRAPH",
                "mutation_count": 0,
                "external_side_effect_count": 0,
            },
        )

    def check_modules_reject(self, fixture: GitFixture) -> None:
        for module in self.modules:
            with self.subTest(module=module.__name__), mock.patch.object(
                module, "SOURCE_ROOT", fixture.root
            ):
                self.assert_git_trust_failure(
                    module, module._assert_trusted_git_repository
                )

    def test_commit_and_blob_replace_refs_are_rejected(self) -> None:
        commit_fixture = GitFixture(self)
        commit_fixture.git(
            "replace", commit_fixture.second_commit, commit_fixture.first_commit
        )
        self.check_modules_reject(commit_fixture)

        blob_fixture = GitFixture(self)
        blob_fixture.git(
            "replace", blob_fixture.second_blob, blob_fixture.first_blob
        )
        self.check_modules_reject(blob_fixture)

    def test_grafts_alternates_shallow_and_partial_clones_are_rejected(self) -> None:
        grafted = GitFixture(self)
        (grafted.common_dir / "info").mkdir(parents=True, exist_ok=True)
        (grafted.common_dir / "info" / "grafts").write_text(
            grafted.second_commit + "\n", encoding="ascii"
        )
        self.check_modules_reject(grafted)

        alternate = GitFixture(self)
        alternate_info = alternate.common_dir / "objects" / "info"
        alternate_info.mkdir(parents=True, exist_ok=True)
        (alternate_info / "alternates").write_text(
            str(alternate.root / "foreign-objects") + "\n", encoding="utf-8"
        )
        self.check_modules_reject(alternate)

        shallow = GitFixture(self)
        (shallow.git_dir / "shallow").write_text(
            shallow.first_commit + "\n", encoding="ascii"
        )
        self.check_modules_reject(shallow)

        partial = GitFixture(self)
        partial.git("config", "remote.origin.promisor", "true")
        self.check_modules_reject(partial)

    def test_dangerous_git_environment_is_rejected_and_never_forwarded(self) -> None:
        fixture = GitFixture(self)
        for module in self.modules:
            with self.subTest(module=module.__name__), mock.patch.object(
                module, "SOURCE_ROOT", fixture.root
            ), mock.patch.dict(
                os.environ,
                {
                    "GIT_DIR": str(fixture.git_dir),
                    "GIT_REPLACE_REF_BASE": "refs/attacker/",
                },
            ):
                self.assert_git_trust_failure(
                    module,
                    lambda module=module: (
                        module.git("rev-parse", "HEAD", text=True)
                        if module is BUILD
                        else module.git_text("rev-parse", "HEAD")
                    ),
                )

        for module in self.modules:
            with self.subTest(clean_environment=module.__name__):
                environment = module._git_environment()
                self.assertEqual(environment["GIT_NO_REPLACE_OBJECTS"], "1")
                self.assertEqual(environment["GIT_NO_LAZY_FETCH"], "1")
                self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
                self.assertFalse(
                    set(environment).intersection(
                        {
                            "GIT_DIR",
                            "GIT_COMMON_DIR",
                            "GIT_WORK_TREE",
                            "GIT_OBJECT_DIRECTORY",
                            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                            "GIT_REPLACE_REF_BASE",
                            "GIT_SHALLOW_FILE",
                            "GIT_CONFIG_COUNT",
                        }
                    )
                )

    def run_publish_preflight(
        self,
        fixture: GitFixture,
        *,
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = fixture.install_publish_script()
        environment = os.environ.copy()
        environment["GOAL_TEAMS_RELEASE_ORCHESTRATOR"] = "1"
        if extra_environment:
            environment.update(extra_environment)
        return subprocess.run(
            ["bash", str(script)],
            cwd=fixture.root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_publish_adapter_rejects_replace_environment_and_nonofficial_origin(self) -> None:
        replacement = GitFixture(self)
        replacement.git(
            "replace", replacement.second_commit, replacement.first_commit
        )
        replaced = self.run_publish_preflight(replacement)
        self.assertNotEqual(replaced.returncode, 0)
        self.assertIn("E_V240_GIT_OBJECT_GRAPH", replaced.stderr)
        self.assertIn("replacement refs", replaced.stderr)

        environment = GitFixture(self)
        poisoned = self.run_publish_preflight(
            environment, extra_environment={"GIT_DIR": str(environment.git_dir)}
        )
        self.assertNotEqual(poisoned.returncode, 0)
        self.assertIn("caller-controlled Git environment", poisoned.stderr)

        fork = GitFixture(self)
        fork.git("remote", "set-url", "origin", "git@github.com:attacker/fork.git")
        rejected_origin = self.run_publish_preflight(fork)
        self.assertNotEqual(rejected_origin.returncode, 0)
        self.assertIn("fixed github.com/vibe-coding-era/goal-teams", rejected_origin.stderr)

        push_fork = GitFixture(self)
        push_fork.git(
            "config", "remote.origin.pushurl", "git@github.com:attacker/fork.git"
        )
        rejected_push = self.run_publish_preflight(push_fork)
        self.assertNotEqual(rejected_push.returncode, 0)
        self.assertIn("remote.origin.pushurl", rejected_push.stderr)

        rewritten = GitFixture(self)
        rewritten.git(
            "config",
            "url.git@github.com:vibe-coding-era/goal-teams.git.insteadOf",
            "git@github.com:attacker/",
        )
        rejected_rewrite = self.run_publish_preflight(rewritten)
        self.assertNotEqual(rejected_rewrite.returncode, 0)
        self.assertIn("URL rewrite", rejected_rewrite.stderr)

    def test_publish_adapter_rejects_grafts_alternates_shallow_and_partial(self) -> None:
        cases: list[tuple[str, GitFixture]] = []

        grafted = GitFixture(self)
        (grafted.common_dir / "info").mkdir(parents=True, exist_ok=True)
        (grafted.common_dir / "info" / "grafts").write_text(
            grafted.second_commit + "\n", encoding="ascii"
        )
        cases.append(("grafts", grafted))

        alternate = GitFixture(self)
        alternate_info = alternate.common_dir / "objects" / "info"
        alternate_info.mkdir(parents=True, exist_ok=True)
        (alternate_info / "alternates").write_text(
            str(alternate.root / "foreign-objects") + "\n", encoding="utf-8"
        )
        cases.append(("alternates", alternate))

        shallow = GitFixture(self)
        (shallow.git_dir / "shallow").write_text(
            shallow.first_commit + "\n", encoding="ascii"
        )
        cases.append(("shallow", shallow))

        partial = GitFixture(self)
        partial.git("config", "remote.origin.promisor", "true")
        cases.append(("partial", partial))

        for label, fixture in cases:
            with self.subTest(label=label):
                result = self.run_publish_preflight(fixture)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("E_V240_GIT_OBJECT_GRAPH", result.stderr)

    def test_publish_adapter_accepts_only_trusted_preflight_before_arguments(self) -> None:
        fixture = GitFixture(self)
        result = self.run_publish_preflight(fixture)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("E_V240_GIT_OBJECT_GRAPH", result.stderr)
        self.assertIn("usage: publish-github-release.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
