"""Tests for the maintainer tools: generator, repository checks and examples."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check  # noqa: E402
import gen  # noqa: E402


class GenTests(unittest.TestCase):
    def test_frontmatter_subset(self):
        meta, body = gen.parse_frontmatter(
            '---\nname: goal_x\nrole: 测试\nmode: write\ndescription: "a: b"\nnicknames: ["测试-一"]\n---\nbody\n', "x")
        self.assertEqual(meta["description"], "a: b")
        self.assertEqual(meta["nicknames"], ["测试-一"])
        self.assertEqual(body, "body\n")

    def test_members_are_valid_and_generated_files_current(self):
        members = gen.load_members()
        self.assertEqual(len(members), 20)
        modes = {m["name"]: m["mode"] for m in members}
        self.assertEqual(modes["goal_reviewer"], "read-only")
        self.assertEqual(modes["goal_unit_test_runner"], "runner")
        self.assertEqual(modes["goal_backend"], "write")
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "gen.py"), "--check"], capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_agents_enforce_modes(self):
        for member in gen.load_members():
            text = gen.claude_agent(member)
            self.assertIn("Agent", text.split("---", 2)[1], "no member may spawn subagents")
            if member["mode"] != "write":
                self.assertIn("disallowedTools: Write, Edit, NotebookEdit, Agent", text)
            toml = gen.codex_agent(member)
            self.assertIn('name = "%s"' % member["name"], toml)
            if sys.version_info >= (3, 11):
                import tomllib
                data = tomllib.loads(toml)
                self.assertEqual(data["name"], member["name"])
                self.assertTrue(data["developer_instructions"].startswith("## 成员协议"))


class CheckTests(unittest.TestCase):
    def test_versioned_segments_are_detected(self):
        for bad in ("v2.68", "V2.3", "v268", "v2.50-x"):
            self.assertTrue(check.VERSIONED_SEGMENT.match(bad), bad)
        for good in ("vendor", "v", "views", "validators", "kg262", "version"):
            self.assertFalse(check.VERSIONED_SEGMENT.match(good), good)

    def test_stale_version_and_paths(self):
        self.assertTrue(check.stale_version("见 V2.68 规则"))
        self.assertTrue(check.stale_version("V3.0"))
        self.assertFalse(check.stale_version("我是 Goal Teams Lead %s。" % check.display_version()))
        self.assertTrue(check.ABSOLUTE_PATH.search("/home/alice/x"))

    def test_skill_route_table_matches_gt(self):
        ok, details = check.check_route_table()
        self.assertTrue(ok, details)

    def test_budgets(self):
        ok, details = check.check_budgets()
        self.assertTrue(ok, details)

    def test_rule_ids_and_references(self):
        for fn in (check.check_rule_ids, check.check_references, check.check_skill_md, check.check_manifests):
            ok, details = fn()
            self.assertTrue(ok, "%s: %s" % (fn.__name__, details))


class BoundaryTests(unittest.TestCase):  # AC33 (decisions D1/D2)
    def test_local_only_folders_are_refused_and_the_readme_block_is_checked(self):
        from unittest import mock
        real = check.tracked_files()
        with mock.patch.object(check, "tracked_files", return_value=real + ["docs/notes.md", "develops/v2.9/x.md"]):
            ok, details = check.check_layout()
        self.assertFalse(ok)
        self.assertIn("docs/notes.md", "\n".join(details))
        ok, details = check.check_manifests()
        self.assertTrue(ok, details)
        outputs = gen.planned_outputs()
        readme = check.ROOT / "README.md"
        self.assertIn(readme, outputs, "the README release block is generated from VERSION (D1 default)")
        self.assertEqual(outputs[readme], readme.read_text(encoding="utf-8"), "only the block between the markers changes")


class ExampleTests(unittest.TestCase):
    def test_examples_match_real_gt_output(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "make_examples.py"), "--check"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
