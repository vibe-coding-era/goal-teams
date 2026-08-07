from __future__ import annotations

import copy
import pathlib
import unittest

from scripts.v26.compatibility import (
    load_compatibility_metadata,
    resolve_route,
    validate_runtime_binding_receipt,
)


ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "references/compatibility/v2.6/manifest.json"


class TestV26RuntimeBindingContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = load_compatibility_metadata(MANIFEST)

    def _receipt(self) -> dict[str, object]:
        return {
            "schema_version": "goal-teams-runtime-binding-v2.6-v1",
            "binding_run_id": "RUN-V26-BINDING-0001",
            "captured_at": "2026-08-07T16:00:00+08:00",
            **resolve_route(
                self.metadata, "host.codex", "provider.deepseek/flash"
            ),
        }

    def test_resolution_binds_each_ordered_route_reference_digest(self) -> None:
        resolution = resolve_route(
            self.metadata, "host.codex", "provider.deepseek/flash"
        )
        self.assertEqual(
            resolution["route_refs"],
            [item["id"] for item in resolution["route_ref_digests"]],
        )
        for item in resolution["route_ref_digests"]:
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")

    def test_binding_requires_run_identity_capture_time_and_exact_digests(self) -> None:
        receipt = self._receipt()
        self.assertTrue(
            validate_runtime_binding_receipt(receipt, self.metadata)["ok"]
        )
        mutations = {
            "missing-run": lambda value: value.pop("binding_run_id"),
            "missing-time": lambda value: value.pop("captured_at"),
            "digest-drift": lambda value: value["route_ref_digests"][0].__setitem__(
                "sha256", "0" * 64
            ),
        }
        expected = {
            "missing-run": "E_V26_RECEIPT_RUN_ID",
            "missing-time": "E_V26_RECEIPT_CAPTURED_AT",
            "digest-drift": "E_V26_RECEIPT_ROUTE_DRIFT",
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = copy.deepcopy(receipt)
                mutate(value)
                verdict = validate_runtime_binding_receipt(value, self.metadata)
                self.assertFalse(verdict["ok"])
                self.assertIn(expected[label], verdict["errors"])


if __name__ == "__main__":
    unittest.main()
