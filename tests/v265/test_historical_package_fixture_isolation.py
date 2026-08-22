from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.v250 import refresh_generation_manifests as refresh


ROOT = Path(__file__).resolve().parents[2]
V263_ACTIVATION = (
    ROOT / "references/current/generations/V2.63/activation-manifest.json"
)


def _root_paths(activation: dict[str, object]) -> set[str]:
    return {
        item["path"]
        for entries in activation["root_sets"].values()
        for item in entries
    }


def _is_v265_path(path: str) -> bool:
    return path.startswith(
        (
            "references/current/generations/V2.65/",
            "references/compatibility/v2.65/",
            "references/profiles/goal-teams-self-release-v2.65",
            "references/release-profiles/v2.65",
            "schemas/v2.65/",
            "scripts/v265/",
            "tests/v265/",
            "tests/v250/test_v265_",
            "tests/v250/v265_",
        )
    )


class TestV263HistoricalPackageFixtureIsolation(unittest.TestCase):
    def test_historical_projection_reuses_exact_frozen_path_sets(self) -> None:
        frozen = json.loads(V263_ACTIVATION.read_text(encoding="utf-8"))
        paths = refresh._generation_paths("V2.63")
        _rule, _prompt, derived = refresh._derive_projection(
            paths,
            generation_id="V2.63",
            predecessor="V2.62",
            state="active",
        )

        self.assertEqual(_root_paths(frozen), _root_paths(derived))
        frozen_selected = set(frozen["current_default_allowlist"]) | set(
            frozen["package_supplement_allowlist"]
        )
        self.assertEqual(
            frozen_selected,
            refresh._package_selected_paths("V2.63", derived),
        )

    def test_historical_projection_contains_zero_v265_paths(self) -> None:
        paths = refresh._generation_paths("V2.63")
        _rule, _prompt, derived = refresh._derive_projection(
            paths,
            generation_id="V2.63",
            predecessor="V2.62",
            state="active",
        )
        selected = refresh._package_selected_paths("V2.63", derived)
        polluted = sorted(
            path for path in _root_paths(derived) | selected if _is_v265_path(path)
        )
        self.assertEqual([], polluted)


if __name__ == "__main__":
    unittest.main()
