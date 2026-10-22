"""Regression cases for extracted-source checks and interrupted-install previews."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import test_install as installer
from tests import test_tools as maintainer


class InterruptedPreviewTests(unittest.TestCase):
    def test_rollback_dry_run_preserves_interrupted_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = installer.make_source(str(root / "source"))
            command = [sys.executable, installer.INSTALL_PY, "--host", "codex", "--source", source,
                       "--home", str(root / "host"), "--skills-dir", str(root / "skills")]
            env = dict(os.environ, GOAL_TEAMS_INSTALL_KILL_AT="after_skill")
            crashed = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(crashed.returncode, 70, crashed.stdout + crashed.stderr)
            before = installer.snapshot(directory)
            preview = subprocess.run(command + ["--rollback", "--dry-run"], capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            self.assertEqual(installer.snapshot(directory), before, "dry-run must not recover or clean staging")
            self.assertIn("dry run", preview.stdout.lower())
            self.assertTrue((root / "host/goal-teams-backups/journal.json").is_file())
            recovered = subprocess.run(command + ["--rollback"], capture_output=True, text=True)
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            self.assertFalse((root / "host/goal-teams-backups/journal.json").exists())


@unittest.skipUnless(shutil.which("git"), "git is required")
class ExtractedSourceChecks(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.parent = Path(directory.name)
        subprocess.run(["git", "init", "-q", str(self.parent)], check=True)
        (self.parent / ".gitignore").write_text("unpacked/\n", encoding="utf-8")
        self.source = self.parent / "unpacked"
        self.source.mkdir()
        (self.source / "VERSION").write_text("2.95.0\n", encoding="utf-8")

    def test_ignored_child_source_is_scanned_instead_of_empty_parent_index(self):
        unexpected = self.source / "unexpected/payload.txt"
        unexpected.parent.mkdir()
        unexpected.write_text("must be checked\n", encoding="utf-8")
        with mock.patch.object(maintainer.check, "ROOT", self.source):
            files = maintainer.check.tracked_files()
            ok, details = maintainer.check.check_layout()
        self.assertIn("unexpected/payload.txt", files)
        self.assertFalse(ok, details)
        self.assertIn("unexpected", "\n".join(details))

    def test_ignored_child_shipped_text_cannot_pass_without_reading_files(self):
        bad = self.source / "plugins/goal-teams/bad.md"
        bad.parent.mkdir(parents=True)
        bad.write_text("stale product V999.0\n", encoding="utf-8")
        with mock.patch.object(maintainer.check, "ROOT", self.source):
            ok, details = maintainer.check.check_shipped_text()
        self.assertFalse(ok, details)
        self.assertIn("V999.0", "\n".join(details))


if __name__ == "__main__":
    unittest.main()
