"""Every release identity field must use the one captured immutable commit."""
from __future__ import annotations
import os
import unittest
from unittest import mock
from tests import test_release as fixtures


@unittest.skipUnless(fixtures.HAS_GIT, 'git is required')
class FrozenIdentityRaceTests(fixtures.ReleaseTestCase):
    def test_head_moving_after_capture_cannot_change_recorded_tree(self):
        repo = self.make_repo()
        commit_a = self.git(repo, 'rev-parse', 'HEAD')
        tree_a = self.git(repo, 'rev-parse', 'HEAD^{tree}')
        (repo / fixtures.GT).write_bytes(b"print('second committed version')\n")
        self.git(repo, 'add', fixtures.GT)
        self.git(repo, 'commit', '-qm', 'second version')
        commit_b = self.git(repo, 'rev-parse', 'HEAD')
        self.assertNotEqual(tree_a, self.git(repo, 'rev-parse', 'HEAD^{tree}'))
        self.git(repo, 'reset', '--hard', commit_a)
        real_git = fixtures.release.git
        changed = []

        def race_git(root, *args):
            result = real_git(root, *args)
            if not changed and args == ('rev-parse', '--verify', '--quiet', 'HEAD^{commit}'):
                self.git(repo, 'reset', '--hard', commit_b)
                changed.append(True)
            return result

        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(fixtures.release, 'git', race_git):
            entries, commit, tree, _ = fixtures.release.collect_from_git(repo, False, set())
        self.assertEqual(changed, [True])
        self.assertEqual(commit, commit_a)
        self.assertEqual(tree, tree_a)
        self.assertEqual({name: data for name, mode, data in entries}[fixtures.GT], fixtures.FILES[fixtures.GT])
