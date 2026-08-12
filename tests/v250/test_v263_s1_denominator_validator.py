"""V2.63 S1 frozen denominator validator contract."""

from __future__ import annotations

import copy
import hashlib
import unittest

from scripts.v250 import release_flow


SOURCE = "1" * 40
TREE = "2" * 40


def _seal(value: dict) -> dict:
    value["receipt_sha256"] = release_flow.canonical_sha256(value)
    return value


def _current_dual_root_receipt() -> dict:
    files = [
        {"path": "tests/v250/test_alpha.py", "sha256": "a" * 64},
        {"path": "tests/v263/integration/test_beta.py", "sha256": "b" * 64},
    ]
    denominator = {
        "denominator_id": "V250-CURRENT-GENERATION-FULL",
        "generation_id": "V2.63",
        "scope": "current_generation_full_regression",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "test_roots": ["tests/v250", "tests/v263"],
        "test_pattern": "test_*.py",
        "contract_path": (
            "references/current/generations/V2.63/contracts/"
            "release-command-manifest.json"
        ),
        "contract_sha256": "c" * 64,
        "test_files": files,
        "test_file_count": len(files),
        "test_file_set_sha256": release_flow.canonical_sha256(files),
        "test_case_count": 2,
        "legacy_roots_excluded": ["tests/v23", "tests/v249", "tests/v26"],
    }
    denominator["denominator_sha256"] = release_flow.canonical_sha256(denominator)
    return _seal(
        {
            "gate_id": "full_regression",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "runner_role": "current_generation_full_regression",
            "run_id": "FULL-DUAL-ROOT-RUN",
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
            "discovered_test_count": 2,
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
                "tests.v263.integration.test_beta",
            ],
            "cwd": ".",
            "returncode": 0,
            "output_sha256": "d" * 64,
        }
    )


class TestV263S1DenominatorValidator(unittest.TestCase):
    def test_accepts_frozen_dual_root_files_and_module_argv(self) -> None:
        errors = release_flow._validate_full_regression_receipt(
            _current_dual_root_receipt(), SOURCE, TREE
        )

        self.assertEqual([], errors)

    def test_rejects_test_file_outside_current_roots(self) -> None:
        receipt = copy.deepcopy(_current_dual_root_receipt())
        files = receipt["denominator"]["test_files"]
        files[1]["path"] = "tests/v23/test_beta.py"
        receipt["denominator"]["test_file_set_sha256"] = (
            release_flow.canonical_sha256(files)
        )
        receipt["denominator"].pop("denominator_sha256")
        receipt["denominator"]["denominator_sha256"] = (
            release_flow.canonical_sha256(receipt["denominator"])
        )
        receipt.pop("receipt_sha256")
        _seal(receipt)

        errors = release_flow._validate_full_regression_receipt(receipt, SOURCE, TREE)

        self.assertIn("E_V250_CURRENT_DENOMINATOR_FILE", errors)

    def test_rejects_module_argv_order_or_content_drift(self) -> None:
        receipt = copy.deepcopy(_current_dual_root_receipt())
        receipt["argv"][-2:] = list(reversed(receipt["argv"][-2:]))
        receipt.pop("receipt_sha256")
        _seal(receipt)

        errors = release_flow._validate_full_regression_receipt(receipt, SOURCE, TREE)

        self.assertIn("E_V250_CURRENT_FULL_RUN_CONTRACT", errors)

    def test_rejects_declared_root_without_any_bound_test_file(self) -> None:
        receipt = copy.deepcopy(_current_dual_root_receipt())
        denominator = receipt["denominator"]
        denominator["test_files"] = denominator["test_files"][:1]
        denominator["test_file_count"] = 1
        denominator["test_file_set_sha256"] = release_flow.canonical_sha256(
            denominator["test_files"]
        )
        denominator["test_case_count"] = 1
        denominator.pop("denominator_sha256")
        denominator["denominator_sha256"] = release_flow.canonical_sha256(
            denominator
        )
        receipt["discovered_test_count"] = 1
        receipt["argv"] = receipt["argv"][:-1]
        receipt.pop("receipt_sha256")
        _seal(receipt)

        errors = release_flow._validate_full_regression_receipt(
            receipt, SOURCE, TREE
        )

        self.assertIn("E_V250_CURRENT_DENOMINATOR_ROOT_COVERAGE", errors)

    def test_rejects_duplicate_bound_test_path_and_module(self) -> None:
        receipt = copy.deepcopy(_current_dual_root_receipt())
        denominator = receipt["denominator"]
        denominator["test_files"].append(
            copy.deepcopy(denominator["test_files"][1])
        )
        denominator["test_file_count"] = 3
        denominator["test_file_set_sha256"] = release_flow.canonical_sha256(
            denominator["test_files"]
        )
        denominator["test_case_count"] = 3
        denominator.pop("denominator_sha256")
        denominator["denominator_sha256"] = release_flow.canonical_sha256(
            denominator
        )
        receipt["discovered_test_count"] = 3
        receipt["argv"].append(receipt["argv"][-1])
        receipt.pop("receipt_sha256")
        _seal(receipt)

        errors = release_flow._validate_full_regression_receipt(
            receipt, SOURCE, TREE
        )

        self.assertIn("E_V250_CURRENT_DENOMINATOR_FILE_DUPLICATE", errors)

    def test_rejects_nul_or_backslash_in_bound_test_path(self) -> None:
        for unsafe_path in (
            "tests/v263/test_bad\x00.py",
            "tests/v263/test_bad\\evil.py",
        ):
            with self.subTest(path=unsafe_path):
                receipt = copy.deepcopy(_current_dual_root_receipt())
                denominator = receipt["denominator"]
                denominator["test_files"][1]["path"] = unsafe_path
                denominator["test_file_set_sha256"] = (
                    release_flow.canonical_sha256(denominator["test_files"])
                )
                denominator.pop("denominator_sha256")
                denominator["denominator_sha256"] = (
                    release_flow.canonical_sha256(denominator)
                )
                receipt["argv"][-1] = unsafe_path[:-3].replace("/", ".")
                receipt.pop("receipt_sha256")
                _seal(receipt)

                errors = release_flow._validate_full_regression_receipt(
                    receipt, SOURCE, TREE
                )

                self.assertIn("E_V250_CURRENT_DENOMINATOR_FILE", errors)


if __name__ == "__main__":
    unittest.main()
