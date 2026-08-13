from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TRANSITION = ROOT / "scripts/v250/runtime_transition.py"


class TestV263RuntimeChildScriptBootstrap(unittest.TestCase):
    def test_direct_child_script_bootstraps_repo_imports_without_pythonpath(self) -> None:
        probe = textwrap.dedent(
            """
            import importlib.util
            import json
            import sys
            from pathlib import Path

            source = Path(sys.argv[1])
            evidence_root = Path(sys.argv[2])
            spec = importlib.util.spec_from_file_location(
                "isolated_runtime_transition", source
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)

            activation = {
                "schema_version": "goal-teams-activation-manifest-v2.50",
                "generation_id": "V2.63",
                "generation_state": "active",
                "identity": {
                    "loaded_runtime_product_version": "V2.63",
                    "route_contract_schema_version": "goal-teams-project-route-v2.50",
                    "target_policy_generation": "V2.63",
                },
                "prompt_manifest_path": "prompt.json",
                "rule_manifest_path": "rules.json",
                "current_default_allowlist": [],
                "legacy_classification": {"exact_paths": [], "path_prefixes": []},
                "manifest_payload_sha256": "",
            }
            activation["manifest_payload_sha256"] = module._canonical_sha256(
                activation, digest_field="manifest_payload_sha256"
            )
            activation_raw = json.dumps(activation).encode("utf-8")
            active = {
                "schema_version": "goal-teams-active-generation-v1",
                "generation_id": "V2.63",
                "state": "active_current",
                "activation_manifest": "activation.json",
                "activation_manifest_sha256": module._sha256(activation_raw),
            }
            prompt = {
                "schema_version": "goal-teams-prompt-manifest-v2.50",
                "generation_id": "V2.63",
                "manifest_state": "active_current",
                "routes": {
                    "V250-ROUTE-MEDIUM-RELEASE": {
                        "workflow_phase": "release",
                        "ordered_refs": ["owner.md"],
                    }
                },
            }
            rules = {"owners": []}
            encoded = {
                module.ACTIVE_PATH: (active, json.dumps(active).encode("utf-8")),
                "activation.json": (activation, activation_raw),
                "prompt.json": (prompt, json.dumps(prompt).encode("utf-8")),
                "rules.json": (rules, json.dumps(rules).encode("utf-8")),
            }
            module._read_repo_json = lambda _root, relative: encoded[relative]
            module._activation_member_digests = lambda _activation: {
                "rules.json": module._sha256(encoded["rules.json"][1])
            }

            try:
                module._load_route_context(
                    root=evidence_root,
                    stage="released",
                    project_size="medium",
                    route_facts_receipt_path=evidence_root / "route-facts.json",
                    derived_route_receipt_path=evidence_root / "derived-route.json",
                    route_receipt_path=evidence_root / "route.json",
                    loaded_runtime_product_version="V2.63",
                )
            except ValueError as exc:
                if not str(exc).startswith("E_V"):
                    raise
                print(str(exc))
            else:
                raise AssertionError("invalid fixtures must fail closed")
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            isolated = Path(directory)
            for name in ("route-facts.json", "derived-route.json", "route.json"):
                (isolated / name).write_text("{}\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            environment["PYTHONNOUSERSITE"] = "1"
            result = subprocess.run(
                [sys.executable, "-I", "-c", probe, str(RUNTIME_TRANSITION), str(isolated)],
                cwd=isolated,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(result.stdout.startswith("E_V"), result.stdout)


if __name__ == "__main__":
    unittest.main()
