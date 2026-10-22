"""Source scans must exclude ledger state before opening files to hash them."""
import unittest
from unittest import mock

from tests.test_gt import HAS_GIT, Repo
from goalteams import gitinfo


@unittest.skipUnless(HAS_GIT, "git required")
class SourceScanTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.state_files = {".goal-teams/" + name for name in (
            "ledger.head", "ledger.jsonl", "journal.json", "TaskList.md", "benchmark.md")}
        for name in self.state_files:
            self.repo.write(name, "synthetic state fixture\n")

    def scan(self):
        hashed = []
        original = gitinfo._hash_paths

        def observe(work_tree, paths):
            hashed.extend(paths)
            return original(work_tree, paths)

        with mock.patch.object(gitinfo, "_hash_paths", side_effect=observe):
            ids = gitinfo.content_ids(self.repo.path)
        return ids, set(hashed)

    def test_untracked_state_is_excluded_before_hashing(self):
        self.repo.write("new-source.py", "value = 1\n")
        ids, hashed = self.scan()
        self.assertFalse(hashed & self.state_files, "source hashing must not open mutable ledger state")
        self.assertFalse(set(ids) & self.state_files)
        self.assertIn("new-source.py", hashed)
        self.assertIn("new-source.py", ids)

    def test_tracked_clean_and_dirty_state_are_excluded_before_hashing(self):
        self.repo.run_git("add", ".goal-teams")
        self.repo.run_git("commit", "-qm", "tracked state fixture")
        self.repo.write(".goal-teams/ledger.head", "new head with a different length\n")
        self.repo.write("src/calc.py", "value = 2\n")
        ids, hashed = self.scan()
        self.assertFalse(hashed & self.state_files, "dirty tracked state must not be opened either")
        self.assertFalse(set(ids) & self.state_files, "clean index entries are also outside the source snapshot")
        self.assertIn("src/calc.py", hashed)
        self.assertIn("src/calc.py", ids)

    def test_source_changes_stay_visible_while_state_and_git_history_do_not_change_digest(self):
        def digest():
            return gitinfo.source_digest(self.repo.path)[0]

        before = digest()
        self.repo.write(".goal-teams/ledger.head", "changed head\n")
        self.repo.write(".goal-teams/journal.json", "changed journal\n")
        self.assertEqual(digest(), before)
        self.repo.write("src/calc.py", "value = 3\n")
        tracked_changed = digest()
        self.assertNotEqual(tracked_changed, before)
        self.repo.run_git("add", "src/calc.py")
        self.assertEqual(digest(), tracked_changed)
        self.repo.run_git("commit", "-qm", "source change")
        self.assertEqual(digest(), tracked_changed)
        self.repo.write("new-source.py", "value = 1\n")
        untracked_added = digest()
        self.assertNotEqual(untracked_added, tracked_changed)
        self.repo.write("new-source.py", "value = 2\n")
        self.assertNotEqual(digest(), untracked_added)
        (self.repo.path / "new-source.py").unlink()
        self.assertEqual(digest(), tracked_changed)


if __name__ == "__main__":
    unittest.main()
