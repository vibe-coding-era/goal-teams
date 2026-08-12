from __future__ import annotations

import inspect
import subprocess
import unittest
from pathlib import Path

from scripts.v250 import runtime_host_adapter, runtime_transition


ROOT = Path(__file__).resolve().parents[2]


class TestV263RuntimeRouteCliBinding(unittest.TestCase):
    def test_host_and_child_require_all_three_route_evidence_paths(self) -> None:
        for script in (
            "scripts/v250/runtime_host_adapter.py",
            "scripts/v250/runtime_transition.py",
        ):
            command = ["python3", script]
            if script.endswith("runtime_host_adapter.py"):
                command.append("launch")
            command.append("--help")
            result = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("--route-facts-receipt", result.stdout)
            self.assertIn("--derived-route-receipt", result.stdout)
            self.assertIn("--route-receipt", result.stdout)

        host_parameters = inspect.signature(
            runtime_host_adapter.launch_runtime_transition
        ).parameters
        transition_parameters = inspect.signature(
            runtime_transition.observe_transition
        ).parameters
        for parameters in (host_parameters, transition_parameters):
            self.assertIn("route_facts_receipt_path", parameters)
            self.assertIn("derived_route_receipt_path", parameters)
            self.assertIs(inspect.Parameter.empty, parameters["route_facts_receipt_path"].default)
            self.assertIs(
                inspect.Parameter.empty,
                parameters["derived_route_receipt_path"].default,
            )


if __name__ == "__main__":
    unittest.main()
