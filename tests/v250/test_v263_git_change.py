from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.v250.git_change_receipt import (
    GitChangeError,
    capture_git_baseline,
    compile_git_change_receipt,
)


class GitChangeReceiptTests(unittest.TestCase):
    def test_collects_modified_added_deleted_renamed_mode_and_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self._repo(Path(temporary))
            baseline = capture_git_baseline(repo)

            (repo / "owned/modify.txt").write_text("modified\n", encoding="utf-8")
            (repo / "owned/delete.txt").unlink()
            self._git(repo, "mv", "owned/rename.txt", "owned/renamed.txt")
            os.chmod(repo / "owned/mode.sh", 0o755)
            (repo / "owned/added.txt").write_text("added\n", encoding="utf-8")
            self._git(repo, "add", "owned/added.txt")
            (repo / "owned/untracked.txt").write_text("untracked\n", encoding="utf-8")

            receipt = compile_git_change_receipt(
                repo, baseline, {"P08": ["owned/**"]}
            )
            by_path = {entry["path"]: entry for entry in receipt["changes"]}

            self.assertEqual("M", by_path["owned/modify.txt"]["status"])
            self.assertEqual("D", by_path["owned/delete.txt"]["status"])
            self.assertEqual("A", by_path["owned/added.txt"]["status"])
            self.assertEqual("R", by_path["owned/renamed.txt"]["status"])
            self.assertEqual("owned/rename.txt", by_path["owned/renamed.txt"]["old_path"])
            self.assertEqual("M", by_path["owned/mode.sh"]["status"])
            self.assertTrue(by_path["owned/mode.sh"]["mode_changed"])
            self.assertEqual("UNTRACKED", by_path["owned/untracked.txt"]["status"])
            self.assertEqual({"P08"}, {entry["task_id"] for entry in receipt["changes"]})
            self.assertEqual("passed", receipt["scope_gate"])
            self.assertRegex(receipt["receipt_digest"], r"^[0-9a-f]{64}$")

    def test_scope_allowlist_rejects_unowned_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self._repo(Path(temporary))
            baseline = capture_git_baseline(repo)
            (repo / "outside.txt").write_text("scope drift\n", encoding="utf-8")

            with self.assertRaises(GitChangeError) as raised:
                compile_git_change_receipt(repo, baseline, {"P08": ["owned/**"]})
            self.assertEqual("E_V263_GIT_SCOPE_DRIFT", raised.exception.code)

    def test_path_matching_multiple_tasks_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self._repo(Path(temporary))
            baseline = capture_git_baseline(repo)
            (repo / "owned/modify.txt").write_text("changed\n", encoding="utf-8")

            with self.assertRaises(GitChangeError) as raised:
                compile_git_change_receipt(
                    repo,
                    baseline,
                    {"P07": ["owned/**"], "P08": ["owned/modify.txt"]},
                )
            self.assertEqual("E_V263_GIT_MULTI_TASK", raised.exception.code)

    def test_dirty_baseline_is_excluded_until_its_digest_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self._repo(Path(temporary))
            path = repo / "owned/modify.txt"
            path.write_text("pre-existing user change\n", encoding="utf-8")
            baseline = capture_git_baseline(
                repo, dirty_owners={"owned/modify.txt": "user"}
            )

            unchanged = compile_git_change_receipt(
                repo, baseline, {"P08": ["owned/**"]}
            )
            self.assertEqual([], unchanged["changes"])
            self.assertEqual("user", baseline["dirty_entries"][0]["owner"])

            path.write_text("implementation changed it again\n", encoding="utf-8")
            changed = compile_git_change_receipt(
                repo, baseline, {"P08": ["owned/**"]}
            )
            self.assertEqual(["owned/modify.txt"], [item["path"] for item in changed["changes"]])
            self.assertEqual("M", changed["changes"][0]["status"])

    def _repo(self, path: Path) -> Path:
        self._git(path, "init", "-q")
        self._git(path, "config", "user.name", "Goal Teams Test")
        self._git(path, "config", "user.email", "goal-teams@example.invalid")
        self._git(path, "config", "core.filemode", "true")
        (path / "owned").mkdir()
        (path / "owned/modify.txt").write_text("original\n", encoding="utf-8")
        (path / "owned/delete.txt").write_text("delete me\n", encoding="utf-8")
        (path / "owned/rename.txt").write_text("rename me\n", encoding="utf-8")
        (path / "owned/mode.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        os.chmod(path / "owned/mode.sh", 0o644)
        self._git(path, "add", ".")
        self._git(path, "commit", "-qm", "baseline")
        return path

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout


if __name__ == "__main__":
    unittest.main()
