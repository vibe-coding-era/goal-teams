from __future__ import annotations

import unittest
from pathlib import Path

from scripts.v250 import refresh_generation_manifests as refresh


class TestV263RefreshDuplicateRejection(unittest.TestCase):
    def test_prompt_refresh_rejects_duplicate_refs_instead_of_deduplicating(self) -> None:
        original = refresh._load

        def load_with_duplicate(path: Path):
            value = original(path)
            if path.name == "prompt-manifest.json":
                route = next(iter(value["routes"].values()))
                route["ordered_refs"].append(route["ordered_refs"][0])
            return value

        refresh._load = load_with_duplicate
        try:
            paths = refresh._generation_paths("V2.63")
            with self.assertRaisesRegex(ValueError, "duplicate prompt route ref"):
                refresh._refreshed_prompt_manifest(paths, "V2.63")
        finally:
            refresh._load = original


if __name__ == "__main__":
    unittest.main()
