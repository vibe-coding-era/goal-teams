"""Incremental tests for the V2.47 flow/P0 strategy."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT


VALIDATOR = ROOT / "scripts" / "checks" / "validate-v247-flow-test-strategy.py"
MANIFEST = ROOT / "references" / "flow-test-strategy-manifest.json"


class V247FlowTestStrategyTests(unittest.TestCase):
    def run_validator(self, path: Path = MANIFEST) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_all_flow_and_product_p0_cases_execute(self) -> None:
        proc = self.run_validator()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["flow_count"], 3)
        self.assertEqual(result["product_count"], 14)
        self.assertEqual(result["evaluated_contract_case_count"], 18)
        self.assertEqual(result["assertion_count"], 28)
        self.assertFalse(result["full_regression_executed"])

    def test_medium_without_choice_stays_awaiting_user(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["flow_policies"]["medium"]["unconfirmed_state"],
            "awaiting_user_choice",
        )

    def test_large_cannot_reuse_prior_incremental_or_smoke(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["flow_policies"]["large"][
            "reuse_prior_incremental_or_smoke_in_full_run"
        ] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("may not reuse prior results", proc.stdout)

    def test_unknown_manifest_field_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["unknown"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unknown fields", proc.stdout)


if __name__ == "__main__":
    unittest.main()
