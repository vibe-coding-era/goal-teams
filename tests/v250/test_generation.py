from __future__ import annotations

import pathlib
import unittest

from scripts.v250.generation_runtime import load_generation
from scripts.v250.route_closure import validate_declared_route_closure


REPO = pathlib.Path(__file__).resolve().parents[2]


class TestV250Generation(unittest.TestCase):
    def test_v266_current_closure_has_no_legacy_and_meets_budget(self) -> None:
        generation = load_generation(REPO)
        closure = validate_declared_route_closure(
            REPO,
            generation,
            route_id="V250-ROUTE-LARGE-DEVELOPMENT",
        )
        self.assertEqual([], closure["legacy_intersection"])
        self.assertLessEqual(closure["loaded_rule_bytes"], 72194)
        self.assertEqual("V2.66", closure["generation_id"])
        self.assertEqual("offline_manifest_audit", closure["route_selection_mode"])

    def test_active_pointer_is_digest_bound(self) -> None:
        generation = load_generation(REPO)
        self.assertTrue(generation["activation_digest_verified"])


if __name__ == "__main__":
    unittest.main()
