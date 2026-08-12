from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def frontmatter_name(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError(f"missing frontmatter: {path}")
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("name:"):
            return line.partition(":")[2].strip()
    raise AssertionError(f"missing name: {path}")


class TestV263DiscoveryNames(unittest.TestCase):
    def test_workspace_wrapper_and_canonical_skill_have_distinct_discovery_names(self) -> None:
        self.assertEqual("goal-teams", frontmatter_name(ROOT / "SKILL.md"))
        self.assertEqual(
            "goal-teams-repo",
            frontmatter_name(ROOT / ".agents/skills/goal-teams/SKILL.md"),
        )


if __name__ == "__main__":
    unittest.main()
