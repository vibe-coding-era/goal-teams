from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATION = ROOT / "references/current/generations/V2.65"


def _section_refs(source: str, heading: str) -> set[str]:
    matched = re.search(
        rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        source,
        re.MULTILINE | re.DOTALL,
    )
    if matched is None:
        return set()
    return set(re.findall(r"^- `([^`]+)`", matched.group(1), re.MULTILINE))


class TestV265OwnerDependencyProjection(unittest.TestCase):
    def _owners(self) -> list[dict[str, object]]:
        manifest = json.loads(
            (GENERATION / "rule-manifest.json").read_text(encoding="utf-8")
        )
        return manifest["owners"]

    def test_markdown_contract_and_dependency_refs_equal_projection(self) -> None:
        mismatches: dict[str, dict[str, list[str]]] = {}
        for owner in self._owners():
            source = (ROOT / owner["path"]).read_text(encoding="utf-8")
            declared = _section_refs(source, "contract_refs") | _section_refs(
                source, "dependencies"
            )
            projected = {
                dependency["owner_id"] for dependency in owner["dependencies"]
            }
            if declared != projected:
                mismatches[owner["owner_id"]] = {
                    "missing": sorted(declared - projected),
                    "extra": sorted(projected - declared),
                }
        self.assertEqual({}, mismatches)

    def test_v265_owner_refs_do_not_create_a_new_dependency_cycle(self) -> None:
        owners = self._owners()
        dependencies: dict[str, set[str]] = {}
        for owner in owners:
            source = (ROOT / owner["path"]).read_text(encoding="utf-8")
            dependencies[owner["owner_id"]] = _section_refs(
                source, "contract_refs"
            ) | _section_refs(source, "dependencies")

        new_owners = {
            "FUNCTION-GRAPH-ENGINEERING-V265",
            "CONTRACT-LOOP-EVOLUTION-V265",
        }

        def reaches_start(start: str, current: str, path: set[str]) -> bool:
            for dependency in dependencies[current]:
                self.assertIn(dependency, dependencies)
                if dependency == start:
                    return True
                if dependency in path:
                    continue
                if reaches_start(start, dependency, path | {dependency}):
                    return True
            return False

        for owner_id in new_owners:
            self.assertFalse(
                reaches_start(owner_id, owner_id, {owner_id}),
                f"V2.65 owner dependency cycle returns to {owner_id}",
            )


if __name__ == "__main__":
    unittest.main()
