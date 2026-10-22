"""Frozen release inputs must come from the recorded Git commit, not index hints."""

from __future__ import annotations

import json
import unittest

from tests import test_release as fixtures


@unittest.skipUnless(fixtures.HAS_GIT, "git is required")
class FrozenSourceTests(fixtures.ReleaseTestCase):
    def test_assume_unchanged_cannot_ship_uncommitted_bytes(self):
        self._hidden_change("--assume-unchanged")

    def test_skip_worktree_cannot_ship_uncommitted_bytes(self):
        self._hidden_change("--skip-worktree")

    def _hidden_change(self, index_flag):
        repo = self.make_repo()
        self.git(repo, "update-index", index_flag, fixtures.GT)
        (repo / fixtures.GT).write_bytes(b"print('uncommitted payload')\n")
        self.assertEqual(self.git(repo, "status", "--porcelain"), "")
        dist = self.build(repo)
        manifest = json.loads((dist / "release.json").read_bytes())
        files = {m.name: data for m, data in fixtures.read_members(dist / fixtures.TARBALL) if m.isfile()}
        self.assertEqual(files[fixtures.TOP + "/" + fixtures.GT], fixtures.FILES[fixtures.GT])
        self.assertEqual(manifest["commit"], self.git(repo, "rev-parse", "HEAD"))
        self.assertEqual(self.verify(dist)[0], 0)

    def test_frozen_version_comes_from_the_same_commit_as_payload(self):
        repo = self.make_repo()
        self.git(repo, "update-index", "--assume-unchanged", "VERSION")
        (repo / "VERSION").write_text("9.99.0\n", encoding="utf-8")
        dist = self.build(repo)
        manifest = json.loads((dist / "release.json").read_bytes())
        self.assertEqual(manifest["version"], fixtures.VERSION)
        self.assertTrue((dist / fixtures.TARBALL).is_file())


if __name__ == "__main__":
    unittest.main()
