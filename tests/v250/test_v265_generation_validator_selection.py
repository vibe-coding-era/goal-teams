from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from tests.v250.v265_activation_fixture import V265ActivationFixture


REPO = pathlib.Path(__file__).resolve().parents[2]
VALIDATOR = pathlib.Path("scripts/checks/validate-v250-generation.py")


class TestV265GenerationValidatorSelection(unittest.TestCase):
    def test_active_selection_uses_only_active_pointer_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "repo"
            fixture = V265ActivationFixture.copy_from(REPO, root)
            prepare = fixture.prepare_v265()
            self.assertEqual(0, prepare.returncode, prepare.stdout)
            prepared_sha256 = fixture.prepared_activation_sha256
            self.assertIsNotNone(prepared_sha256)
            activate = fixture.run_refresh(
                "--activate",
                "--generation-id",
                "V2.65",
                "--predecessor",
                "V2.63",
                "--base-active-sha256",
                fixture.base_active_sha256,
                "--base-activation-sha256",
                fixture.base_activation_sha256,
                "--expected-prepared-activation-sha256",
                str(prepared_sha256),
                "--activated-at",
                "2026-08-22T17:45:00+08:00",
            )
            self.assertEqual(0, activate.returncode, activate.stdout)

            active_validation = subprocess.run(
                [
                    sys.executable,
                    str(root / VALIDATOR),
                    "--generation-id",
                    "V2.65",
                    "--selection",
                    "active",
                    "--json",
                ],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(0, active_validation.returncode, active_validation.stdout)
            self.assertEqual("active", json.loads(active_validation.stdout)["selection"])

            ambiguous = subprocess.run(
                [
                    sys.executable,
                    str(root / VALIDATOR),
                    "--generation-id",
                    "V2.65",
                    "--selection",
                    "active",
                    "--expected-activation-sha256",
                    prepared_sha256,
                    "--json",
                ],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(0, ambiguous.returncode, ambiguous.stdout)
            self.assertIn(
                "E_V250_ACTIVE_EXTERNAL_DIGEST_FORBIDDEN",
                ambiguous.stdout,
            )


if __name__ == "__main__":
    unittest.main()
