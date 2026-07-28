"""Incremental tests for the V2.47 document reducer."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.v23.common import ROOT


VALIDATOR = ROOT / "scripts" / "checks" / "validate-v247-incremental-document.py"
MANIFEST = ROOT / "references" / "incremental-document-manifest.json"


class V247IncrementalDocumentTests(unittest.TestCase):
    def run_validator(self, path: Path = MANIFEST) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_projection_and_stable_prefix_smoke(self) -> None:
        proc = self.run_validator()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["fragment_count"], 5)
        self.assertEqual(result["final_revision"], 5)
        self.assertTrue(result["stable_prefix_digest_unchanged"])
        self.assertTrue(result["projection_byte_equivalent"])
        self.assertEqual(
            result["runtime_integration_state"],
            "contract_p0_not_runtime_integrated",
        )

    def test_revision_gap_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["p0_projection_fixture"]["fragments"][1]["base_revision"] = 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("CAS base revision mismatch", proc.stdout)

    def test_content_hash_drift_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["p0_projection_fixture"]["fragments"][0]["content"] = "drift"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("content hash mismatch", proc.stdout)

    def test_unknown_manifest_field_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["unknown"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unknown fields", proc.stdout)

    def test_missing_fragment_provenance_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        del manifest["p0_projection_fixture"]["fragments"][0]["actor_run_id"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing fields", proc.stdout)

    def test_fragment_document_binding_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["p0_projection_fixture"]["fragments"][0]["document_id"] = "OTHER"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("document_id mismatch", proc.stdout)

    def test_fragment_timestamp_without_timezone_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["p0_projection_fixture"]["fragments"][0]["created_at"] = (
            "2026-07-28T00:00:01"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RFC3339", proc.stdout)

    def test_fragment_non_rfc3339_timestamp_fails_closed(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["p0_projection_fixture"]["fragments"][0]["created_at"] = (
            "2026-07-28 00:00:01+08:00"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            proc = self.run_validator(path)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RFC3339", proc.stdout)


if __name__ == "__main__":
    unittest.main()
