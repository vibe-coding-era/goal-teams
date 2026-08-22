from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV263ReleaseRouteIdentity(unittest.TestCase):
    def test_release_route_requires_installed_v262_controller(self) -> None:
        value = json.loads(
            (
                ROOT
                / "references/current/generations/V2.65/contracts/release-route-manifest.json"
            ).read_text(encoding="utf-8")
        )
        runtime = value["runtime_transition"]
        self.assertEqual(
            "externally_issued_by_installed_v2.63_codex_host",
            runtime["controller_handoff_source"],
        )
        self.assertNotIn("installed_v2.6_codex_host", json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
