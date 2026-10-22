"""Projection regeneration shares one fresh filesystem snapshot inside the ledger lock."""
import argparse
import os
import sys
import unittest
from unittest import mock

from tests.test_gt import HAS_GIT, Repo
from goalteams import checks, completion, context, render


@unittest.skipUnless(HAS_GIT, "git required")
class ProjectionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.ok("init")
        self.ok("goal", "Fresh projection", "--impact", "config_change")
        self.ok("task", "add", "D", "reviewed document", "--kind", "doc", "--scope", "README.md",
                "--owner", "goal_docs", "--validator", "goal_reviewer")
        self.ok("task", "done", "D")
        self.ok("review", "D", "--by", "goal_reviewer", "--verdict", "pass")
        self.ok("run", "-", "--kind", "runtime", "--", sys.executable, "-c", "pass")
        self.ctx = context.Ctx(argparse.Namespace(root=str(self.repo.path)))

    def ok(self, *args):
        return self.repo.ok("--root", str(self.repo.path), *args)

    def capture_snapshots(self, snapshots):
        collect = checks.collect

        def capture(*args, **kwargs):
            snapshot = collect(*args, **kwargs)
            snapshots.append(snapshot)
            return snapshot

        return mock.patch.object(checks, "collect", side_effect=capture)

    def test_one_tree_snapshot_drives_both_projection_files(self):
        snapshots = []
        with self.capture_snapshots(snapshots), \
                mock.patch.object(checks.gitinfo, "tree_ids", wraps=checks.gitinfo.tree_ids) as tree_ids, \
                mock.patch.object(render, "tasklist_md", wraps=render.tasklist_md) as tasklist, \
                mock.patch.object(render, "benchmark_md", wraps=render.benchmark_md) as benchmark:
            self.ctx.regenerate()
        self.assertEqual(tree_ids.call_count, 1, "one projection rebuild must not rescan the same work tree")
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertIs(tasklist.call_args.args[0], snapshot.state)
        self.assertIs(benchmark.call_args.args[0], snapshot.state)
        self.assertIs(self.ctx.state(), snapshot.state)
        self.assertEqual(benchmark.call_args.kwargs["axes"], completion._axes(snapshot))
        self.assertEqual(benchmark.call_args.kwargs["oos"], len(snapshot.diff["out_of_scope"]))
        self.assertEqual((self.ctx.project.state / "TaskList.md").read_text(encoding="utf-8"),
                         render.tasklist_md(snapshot.state, snapshot.config))
        self.assertEqual((self.ctx.project.state / "benchmark.md").read_text(encoding="utf-8"),
                         render.benchmark_md(snapshot.state, snapshot.config,
                                             axes=completion._axes(snapshot), oos=0))

    def test_next_rebuild_is_fresh_and_preserves_stale_review_axes_and_scope(self):
        snapshots = []
        with self.capture_snapshots(snapshots):
            self.ctx.regenerate()
            first = snapshots[-1]
            self.assertFalse(first.tasks["D"].stale)
            self.assertEqual(completion._axes(first)["runtime"], "passed")
            self.repo.write("README.md", "# changed after review and runtime verification\n")
            self.repo.write("outside.txt", "out of the document task's scope\n")
            self.ctx.regenerate()
        self.assertEqual(len(snapshots), 2)
        second = snapshots[-1]
        self.assertIsNot(first.state, second.state, "rebuild must reduce the current ledger again")
        self.assertNotEqual(first.source_digest, second.source_digest)
        self.assertFalse(first.tasks["D"].stale, "a later rebuild must not mutate the earlier snapshot")
        self.assertTrue(second.tasks["D"].stale)
        self.assertEqual(completion._axes(second)["runtime"], "stale")
        self.assertEqual(second.diff["out_of_scope"], ["outside.txt"])
        tasklist = (self.ctx.project.state / "TaskList.md").read_text(encoding="utf-8")
        benchmark = (self.ctx.project.state / "benchmark.md").read_text(encoding="utf-8")
        self.assertIn("评审已过期", tasklist)
        self.assertIn("| runtime | 已过期（源码已变化） |", benchmark)
        self.assertIn("越界文件 1", benchmark)

    def test_append_keeps_projection_publication_inside_the_ledger_lock(self):
        observed = []
        original = render.benchmark_md

        def inspect(*args, **kwargs):
            lock = self.ctx.project.state / ".lock"
            observed.append((lock.exists(), lock.read_text().split()[0], args[0].last_seq))
            return original(*args, **kwargs)

        with mock.patch.object(render, "benchmark_md", side_effect=inspect):
            event = self.ctx.append("context.add", {"title": "projection lock regression", "ref": "README.md"})
        self.assertEqual(observed, [(True, str(os.getpid()), event["seq"])])
        self.assertFalse((self.ctx.project.state / ".lock").exists())
        self.assertEqual(self.ctx.project.verify(), [])
        self.assertEqual(self.ctx.project.read_head()["seq"], event["seq"])


if __name__ == "__main__":
    unittest.main()
