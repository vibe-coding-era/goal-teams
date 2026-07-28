"""Incremental tests for V2.47 CodeAgent compatibility routing."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT


VALIDATOR = ROOT / "scripts" / "checks" / "validate-v247-codeagent-runtime.py"
MANIFEST = ROOT / "references" / "codeagent-runtime-manifest.json"


class V247CodeAgentRuntimeTests(unittest.TestCase):
    def run_validator(self, path: Path = MANIFEST) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_runtime_denominator_sources_overlays_and_fixtures_close(self) -> None:
        proc = self.run_validator()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["runtime_count"], 8)
        self.assertEqual(result["official_source_count"], 32)
        self.assertEqual(result["overlay_count"], 8)
        self.assertEqual(result["fixture_count"], 7)
        self.assertEqual(result["full_adapter_verified_count"], 0)

    def test_glm_is_not_promoted_to_a_runtime(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        glm = next(item for item in manifest["runtimes"] if item["runtime_id"] == "glm")
        self.assertEqual(glm["runtime_kind"], "model_provider")
        self.assertEqual(glm["skill_roots"], [])

    def test_trae_schema_gap_cannot_be_silently_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        trae = next(item for item in manifest["runtimes"] if item["runtime_id"] == "trae")
        trae["adapter_state"] = "contract_mapped_not_runtime_verified"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("TRAE must fail closed", proc.stdout)

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
