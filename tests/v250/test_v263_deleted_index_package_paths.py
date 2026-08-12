from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REFRESH_PATH = ROOT / "scripts/v250/refresh_generation_manifests.py"
CHECKER_PATH = ROOT / "scripts/checks/check-package-manifest.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestV263DeletedIndexPackagePaths(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        (self.repo / "pkg").mkdir(parents=True)
        (self.repo / "scripts/install").mkdir(parents=True)

        (self.repo / ".gitignore").write_text("pkg/ignored.txt\n", encoding="utf-8")
        (self.repo / "pkg/tracked.txt").write_text("tracked\n", encoding="utf-8")
        (self.repo / "pkg/deleted.txt").write_text("deleted\n", encoding="utf-8")
        (self.repo / "pkg/non-regular.txt").write_text(
            "regular at index time\n", encoding="utf-8"
        )
        os.symlink("tracked.txt", self.repo / "pkg/tracked-link")
        (self.repo / "scripts/install/package-manifest.txt").write_text(
            "prefix pkg/\n", encoding="utf-8"
        )

        self._git("init", "-q")
        self._git("config", "user.name", "Goal Teams Test")
        self._git("config", "user.email", "goal-teams-test@invalid.local")
        self._git("add", ".gitignore", "pkg", "scripts/install/package-manifest.txt")
        self._git("commit", "-q", "-m", "tracked package fixture")

        (self.repo / "pkg/deleted.txt").unlink()
        (self.repo / "pkg/non-regular.txt").unlink()
        (self.repo / "pkg/non-regular.txt").mkdir()
        (self.repo / "pkg/untracked.txt").write_text("untracked\n", encoding="utf-8")
        (self.repo / "pkg/ignored.txt").write_text("ignored\n", encoding="utf-8")
        os.symlink("tracked.txt", self.repo / "pkg/untracked-link")

        self.refresh = _load_module("v263_deleted_index_refresh", REFRESH_PATH)
        self.checker = _load_module("v263_deleted_index_checker", CHECKER_PATH)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_source_enumerator_keeps_only_existing_regular_non_symlink_files(self) -> None:
        source_paths = self.checker._source_paths(self.repo)

        self.assertIn("pkg/tracked.txt", source_paths)
        self.assertIn("pkg/untracked.txt", source_paths)
        self.assertNotIn("pkg/deleted.txt", source_paths)
        self.assertNotIn("pkg/tracked-link", source_paths)
        self.assertNotIn("pkg/untracked-link", source_paths)
        self.assertNotIn("pkg/non-regular.txt", source_paths)
        self.assertNotIn("pkg/ignored.txt", source_paths)

    def test_refresh_prefix_selection_uses_the_same_physical_file_boundary(self) -> None:
        original_root = self.refresh.ROOT
        original_manifest = self.refresh.PACKAGE_MANIFEST
        try:
            self.refresh.ROOT = self.repo
            self.refresh.PACKAGE_MANIFEST = Path(
                "scripts/install/package-manifest.txt"
            )
            selected = self.refresh._package_selected_paths()
        finally:
            self.refresh.ROOT = original_root
            self.refresh.PACKAGE_MANIFEST = original_manifest

        self.assertEqual({"pkg/tracked.txt", "pkg/untracked.txt"}, selected)

    def test_deleted_direct_file_is_missing_for_both_consumers(self) -> None:
        rules = [("file", "pkg/deleted.txt")]
        selected, errors = self.checker._selected_paths(self.repo, rules)
        self.assertEqual(set(), selected)
        self.assertEqual(
            ["E_PACKAGE_MANIFEST_FILE_MISSING:pkg/deleted.txt"], errors
        )

        manifest = self.repo / "scripts/install/package-manifest.txt"
        manifest.write_text("file pkg/deleted.txt\n", encoding="utf-8")
        original_root = self.refresh.ROOT
        original_manifest = self.refresh.PACKAGE_MANIFEST
        try:
            self.refresh.ROOT = self.repo
            self.refresh.PACKAGE_MANIFEST = Path(
                "scripts/install/package-manifest.txt"
            )
            with self.assertRaisesRegex(
                ValueError, "package file is missing: pkg/deleted.txt"
            ):
                self.refresh._package_selected_paths()
        finally:
            self.refresh.ROOT = original_root
            self.refresh.PACKAGE_MANIFEST = original_manifest


if __name__ == "__main__":
    unittest.main()
