from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV250RuntimeCLI(unittest.TestCase):
    def test_release_wrapper_forwards_runtime_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            log = temp / "python-argv.log"
            fake_python = temp / "python3"
            fake_python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$FAKE_PYTHON_LOG\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            runtime_receipt = temp / "runtime-transition.json"
            runtime_receipt.write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                [
                    "bash",
                    "scripts/checks/check.sh",
                    "--phase",
                    "release",
                    "--project-size",
                    "large",
                    "--source-commit",
                    "1" * 40,
                    "--source-tree",
                    "2" * 40,
                    "--expected-host-execution-id",
                    "HOST-RUN-1",
                    "--released-runtime-receipt",
                    str(runtime_receipt),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHON": str(fake_python), "FAKE_PYTHON_LOG": str(log)},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            invocations = log.read_text(encoding="utf-8").splitlines()

        release_invocation = next(
            value
            for value in invocations
            if value.startswith("scripts/checks/check-v250.py --phase release")
        )
        self.assertIn(
            f"--released-runtime-receipt {runtime_receipt}", release_invocation
        )
        self.assertIn("--expected-host-execution-id HOST-RUN-1", release_invocation)

    def test_runtime_child_cli_forbids_raw_lineage_and_uses_stdin_receipts(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/v250/runtime_transition.py", "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        for option in (
            "--child",
            "--project-size",
            "--route-receipt",
            "--authorization-receipt",
            "--adapter-identity",
            "--adapter-code",
        ):
            self.assertIn(option, result.stdout)
        for forbidden in (
            "--controller-version",
            "--previous-controller-version",
            "--loaded-runtime-version",
            "--previous-run-id",
            "--new-run-id",
        ):
            self.assertNotIn(forbidden, result.stdout)

    def test_host_adapter_cli_has_launch_and_read_only_key_verification(self) -> None:
        result = subprocess.run(
            ["python3", "scripts/v250/runtime_host_adapter.py", "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("launch", result.stdout)
        self.assertIn("verify-github-key", result.stdout)

    def test_host_adapter_declares_v26_to_v262_runtime_handoff(self) -> None:
        adapter_source = (ROOT / "scripts/v250/runtime_host_adapter.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("V2.6 -> V2.62 runtime handoff", adapter_source)
        self.assertNotIn("V2.62 -> V2.62 runtime handoff", adapter_source)


if __name__ == "__main__":
    unittest.main()
