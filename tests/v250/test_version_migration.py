from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV250VersionMigration(unittest.TestCase):
    def test_v268_current_identity_is_complete_and_predecessors_are_not_default(self) -> None:
        self.assertEqual(
            "V2.68",
            (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        )

        active = json.loads(
            (ROOT / "references/current/ACTIVE.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("V2.68", active["generation_id"])
        self.assertEqual(
            "references/current/generations/V2.68/activation-manifest.json",
            active["activation_manifest"],
        )

        profile = json.loads(
            (ROOT / "references/release-profiles/v2.68.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("V2.68", profile["version"])
        self.assertEqual("v2.68", profile["tag"])
        self.assertEqual("V2.67", profile["published_before"])
        self.assertEqual("codex/develop-v2.68", profile["candidate_branch"])

        for relative in (
            "references/current/generations/V2.68/activation-manifest.json",
            "schemas/v2.68/release-control.schema.json",
            "scripts/v268/s4_executor.py",
            "scripts/checks/check-v268.py",
            "schemas/v2.67/output-dashboard.schema.json",
            "scripts/v267/output_dashboard.py",
            "scripts/v268/output_gateway.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

        package_manifest = (
            ROOT / "scripts/install/package-manifest.txt"
        ).read_text(encoding="utf-8")
        package_lines = {
            line
            for line in package_manifest.splitlines()
            if line and not line.startswith("#")
        }
        self.assertIn("prefix references/current/generations/V2.68/", package_lines)
        self.assertIn("prefix schemas/v2.50/", package_manifest)
        self.assertIn("prefix scripts/v250/", package_manifest)
        self.assertIn("prefix tests/v250/", package_manifest)
        self.assertIn("prefix schemas/v2.68/", package_lines)
        self.assertIn("prefix scripts/v268/", package_lines)
        self.assertIn("prefix tests/v268/", package_lines)
        expected_shared_v267_output = {
            "file scripts/v267/__init__.py",
            "file scripts/v267/output_dashboard.py",
            "file schemas/v2.67/output-dashboard.schema.json",
        }
        self.assertEqual(expected_shared_v267_output, {
            line for line in package_lines
            if line.startswith("file scripts/v267/") or line.startswith("file schemas/v2.67/")
        })
        for forbidden in (
            "prefix references/current/generations/V2.67/",
            "prefix schemas/v2.67/", "prefix scripts/v267/", "prefix tests/v267/",
        ):
            self.assertNotIn(forbidden, package_lines)

        expected_shared_v265_runtime = {
            "file schemas/v2.65/context-bundle.schema.json",
            "file schemas/v2.65/graph-contract.schema.json",
            "file schemas/v2.65/graph-runtime.schema.json",
            "file schemas/v2.65/host-capability.schema.json",
            "file schemas/v2.65/loop-coordinator.schema.json",
            "file schemas/v2.65/loop-review.schema.json",
            "file schemas/v2.65/member-packet.schema.json",
            "file scripts/v265/__init__.py",
            "file scripts/v265/canonical.py",
            "file scripts/v265/context_compiler.py",
            "file scripts/v265/graph_contract.py",
            "file scripts/v265/graph_runtime.py",
            "file scripts/v265/host_adapter.py",
            "file scripts/v265/loop_coordinator.py",
            "file scripts/v265/loop_review.py",
            "file scripts/v265/member_packet.py",
            "file scripts/v265/runtime_controller.py",
            "file scripts/v265/runtime_store.py",
        }
        actual_shared_v265_runtime = {
            line
            for line in package_lines
            if line.startswith("file schemas/v2.65/")
            or line.startswith("file scripts/v265/")
        }
        self.assertEqual(expected_shared_v265_runtime, actual_shared_v265_runtime)
        self.assertNotIn("prefix schemas/v2.65/", package_lines)
        self.assertNotIn("prefix scripts/v265/", package_lines)
        self.assertNotIn("prefix tests/v265/", package_lines)
        self.assertNotIn(
            "prefix references/current/generations/V2.65/",
            package_lines,
        )
        self.assertNotIn(
            "prefix references/current/generations/V2.63/",
            package_manifest,
        )
        self.assertNotIn("prefix scripts/v262/", package_manifest)
        self.assertNotIn("prefix tests/v262/", package_manifest)
        self.assertNotIn(
            "prefix references/current/generations/V2.49/",
            package_manifest,
        )
        self.assertNotIn("prefix scripts/v249/", package_manifest)
        self.assertNotIn("prefix tests/v249/", package_manifest)
        self.assertNotIn("prefix references/current/generations/V2.6/", package_manifest)
        self.assertNotIn("prefix scripts/v26/", package_manifest)
        self.assertNotIn("prefix tests/v26/", package_manifest)


if __name__ == "__main__":
    unittest.main()
