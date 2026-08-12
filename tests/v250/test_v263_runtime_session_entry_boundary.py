from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.v250.runtime_session import (
    RuntimeSessionError,
    compile_runtime_session_receipt,
)
from tests.v250.test_v263_trust_boundary_hardening import RuntimeFixture


class TestV263RuntimeSessionEntryBoundary(unittest.TestCase):
    def test_compatibility_compiler_cannot_claim_trusted_runtime_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = RuntimeFixture(Path(directory))
            artifact = fixture.artifact()
            with self.assertRaises(RuntimeSessionError) as caught:
                compile_runtime_session_receipt(
                    runtime_session_id="BYPASS-SESSION",
                    discovery_decision_sha256="f" * 64,
                    generation_snapshot_sha256=fixture.session.snapshot.snapshot_sha256,
                    derived_route_sha256=fixture.route["receipt_sha256"],
                    prompt_artifact=artifact,
                    host_load_observation=fixture.observation(artifact),
                    host_execution_id="HOST-EXEC-263-TRUST",
                )
            self.assertEqual(
                "E_V263_RUNTIME_PROVENANCE_REQUIRED", caught.exception.code
            )


if __name__ == "__main__":
    unittest.main()
