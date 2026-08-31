"""V2.67 S1 regression and release-security denominator Red tests."""

from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "1" * 40
TREE = "2" * 40
CURRENT_ROOTS = ["tests/v250", "tests/v267"]
PREDECESSOR_ROOTS = ["tests/v266"]
LEGACY_ROOTS = ["tests/v23", "tests/v249", "tests/v26", "tests/v262", "tests/v263"]


class TestV267ReleaseGateDenominator(unittest.TestCase):
    def _flow(self) -> ModuleType:
        try:
            return importlib.import_module("scripts.v267.release_flow")
        except ModuleNotFoundError as exc:
            self.fail(f"E_TEST_V267_RELEASE_FLOW_MISSING:{exc}")

    def _load(self, path: Path, name: str) -> ModuleType:
        self.assertTrue(path.is_file(), f"E_TEST_V267_MODULE_MISSING:{path}")
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _receipt(self, flow: ModuleType) -> dict[str, object]:
        files = [
            {"path": "tests/v250/test_alpha.py", "sha256": "a" * 64},
            {"path": "tests/v267/test_delta.py", "sha256": "b" * 64},
        ]
        denominator = {
            "denominator_id": "V250-CURRENT-GENERATION-FULL",
            "generation_id": "V2.67",
            "scope": "current_generation_full_regression",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "test_roots": list(CURRENT_ROOTS),
            "published_predecessor_test_roots": list(PREDECESSOR_ROOTS),
            "predecessor_test_invocation_limit": 0,
            "predecessor_release_identity_path": (
                "references/current/generations/V2.67/contracts/"
                "predecessor-release-identity.json"
            ),
            "test_pattern": "test_*.py",
            "contract_path": (
                "references/current/generations/V2.67/contracts/"
                "release-command-manifest.json"
            ),
            "contract_sha256": "d" * 64,
            "test_files": files,
            "test_file_count": len(files),
            "test_file_set_sha256": flow.canonical_sha256(files),
            "test_case_count": len(files),
            "legacy_roots_excluded": list(LEGACY_ROOTS),
        }
        denominator["denominator_sha256"] = flow.canonical_sha256(denominator)
        receipt = {
            "schema_version": "goal-teams-v2.67-release-gate-receipt-v1",
            "gate_id": "full_regression",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "runner_role": "current_generation_full_regression",
            "run_id": "FULL-V267-CURRENT-RUN",
            "execution_source": "exact_clean_worktree",
            "worktree_binding": {
                "binding_kind": "exact_clean_worktree",
                "head_commit": SOURCE,
                "head_tree": TREE,
                "status_porcelain_sha256": hashlib.sha256(b"").hexdigest(),
                "dirty_entry_count": 0,
                "untracked_entry_count": 0,
            },
            "denominator": denominator,
            "discovered_test_count": len(files),
            "legacy_test_invocation_count": 0,
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "invocation_count_for_released_identity": 1,
            "argv": [
                "python3",
                "-m",
                "unittest",
                "-v",
                "tests.v250.test_alpha",
                "tests.v267.test_delta",
            ],
            "cwd": ".",
            "returncode": 0,
            "output_sha256": "e" * 64,
        }
        receipt["receipt_sha256"] = flow.canonical_sha256(receipt)
        return receipt

    def _reseal(self, flow: ModuleType, receipt: dict[str, object]) -> None:
        denominator = receipt["denominator"]
        denominator.pop("denominator_sha256", None)
        denominator["denominator_sha256"] = flow.canonical_sha256(denominator)
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = flow.canonical_sha256(receipt)

    def test_accepts_only_v250_and_v267_current_roots(self) -> None:
        flow = self._flow()
        command_path = ROOT / (
            "references/current/generations/V2.67/contracts/"
            "release-command-manifest.json"
        )
        self.assertTrue(command_path.is_file(), "E_TEST_V267_COMMAND_MANIFEST_MISSING")
        command = json.loads(command_path.read_text(encoding="utf-8"))
        declared = command["release"]["s1"]["current_full_regression_denominator"]
        self.assertEqual(CURRENT_ROOTS, declared["test_roots"])
        self.assertEqual(PREDECESSOR_ROOTS, declared["published_predecessor_test_roots"])
        self.assertEqual(0, declared["predecessor_test_invocation_limit"])
        self.assertEqual(
            [], flow._validate_full_regression_receipt(self._receipt(flow), SOURCE, TREE)
        )

    def test_rejects_missing_root_predecessor_file_duplicate_and_order_drift(self) -> None:
        flow = self._flow()
        cases = {
            "missing_root": "E_V250_CURRENT_DENOMINATOR_INCOMPLETE",
            "predecessor_file": "E_V250_CURRENT_DENOMINATOR_FILE",
            "duplicate": "E_V250_CURRENT_DENOMINATOR_FILE_DUPLICATE",
            "order": "E_V250_CURRENT_FULL_RUN_CONTRACT",
        }
        for case, expected_code in cases.items():
            with self.subTest(case=case):
                receipt = copy.deepcopy(self._receipt(flow))
                denominator = receipt["denominator"]
                if case == "missing_root":
                    denominator["test_roots"].remove("tests/v267")
                elif case == "predecessor_file":
                    denominator["test_files"][1]["path"] = "tests/v266/test_old.py"
                    denominator["test_file_set_sha256"] = flow.canonical_sha256(
                        denominator["test_files"]
                    )
                elif case == "duplicate":
                    denominator["test_files"].append(
                        copy.deepcopy(denominator["test_files"][-1])
                    )
                    denominator["test_file_count"] = 3
                    denominator["test_case_count"] = 3
                    denominator["test_file_set_sha256"] = flow.canonical_sha256(
                        denominator["test_files"]
                    )
                    receipt["discovered_test_count"] = 3
                    receipt["argv"].append(receipt["argv"][-1])
                else:
                    receipt["argv"][-2:] = reversed(receipt["argv"][-2:])
                self._reseal(flow, receipt)
                errors = flow._validate_full_regression_receipt(
                    receipt, SOURCE, TREE
                )
                self.assertIn(expected_code, errors)

    def test_security_manifest_runner_and_flow_share_one_exact_target_set(self) -> None:
        flow = self._flow()
        self.assertEqual(
            "scripts/checks/run-v267-release-security-review.py",
            flow.SECURITY_REVIEW_RUNNER_PATH,
        )
        manifest_path = ROOT / (
            "references/current/generations/V2.67/contracts/"
            "release-security-review-manifest.json"
        )
        self.assertTrue(manifest_path.is_file(), "E_TEST_V267_SECURITY_MANIFEST_MISSING")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runner = self._load(
            ROOT / "scripts/checks/run-v267-release-security-review.py",
            "_test_v267_security_runner",
        )
        targets = {item["path"] for item in manifest["review_targets"]}
        required = {
            ".github/workflows/check.yml",
            ".github/workflows/release-gate.yml",
            "schemas/v2.67/runtime-transition-receipt.schema.json",
            "schemas/v2.67/release-control.schema.json",
            "scripts/v267/release_identity.py",
            "scripts/v267/release_flow.py",
            "scripts/v267/runtime_transition.py",
            "scripts/v267/runtime_host_adapter.py",
            "scripts/v267/s4_executor.py",
        }
        self.assertTrue(required.issubset(targets), sorted(required - targets))
        self.assertEqual(targets, set(runner.MANDATORY_REVIEW_TARGETS))
        self.assertEqual(targets, set(flow.V250_SECURITY_REQUIRED_TARGET_PATHS))


if __name__ == "__main__":
    unittest.main()
