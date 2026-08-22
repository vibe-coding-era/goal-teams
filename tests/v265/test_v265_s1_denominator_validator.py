"""V2.65 S1 frozen denominator validator contract."""

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


def _current_three_root_receipt() -> dict:
    files = [
        {"path": "tests/v250/test_alpha.py", "sha256": "a" * 64},
        {"path": "tests/v265/test_gamma.py", "sha256": "c" * 64},
    ]
    denominator = {
        "denominator_id": "V250-CURRENT-GENERATION-FULL",
        "generation_id": "V2.65",
        "scope": "current_generation_full_regression",
        "source_commit": SOURCE,
        "source_tree": TREE,
        "test_roots": ["tests/v250", "tests/v265"],
        "published_predecessor_test_roots": ["tests/v263"],
        "predecessor_test_invocation_limit": 0,
        "predecessor_release_identity_path": "references/current/generations/V2.65/contracts/predecessor-release-identity.json",
        "test_pattern": "test_*.py",
        "contract_path": (
            "references/current/generations/V2.65/contracts/"
            "release-command-manifest.json"
        ),
        "contract_sha256": "d" * 64,
        "test_files": files,
        "test_file_count": len(files),
        "test_file_set_sha256": release_flow.canonical_sha256(files),
        "test_case_count": len(files),
        "legacy_roots_excluded": ["tests/v23", "tests/v249", "tests/v26"],
    }
    denominator["denominator_sha256"] = release_flow.canonical_sha256(
        denominator
    )
    return _seal(
        {
            "gate_id": "full_regression",
            "source_commit": SOURCE,
            "source_tree": TREE,
            "runner_role": "current_generation_full_regression",
            "run_id": "FULL-V265-THREE-ROOT-RUN",
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
                "tests.v265.test_gamma",
            ],
            "cwd": ".",
            "returncode": 0,
            "output_sha256": "e" * 64,
        }
    )


def _reseal(receipt: dict) -> None:
    denominator = receipt["denominator"]
    denominator.pop("denominator_sha256", None)
    denominator["denominator_sha256"] = release_flow.canonical_sha256(
        denominator
    )
    receipt.pop("receipt_sha256", None)
    _seal(receipt)


class TestV265S1DenominatorValidator(unittest.TestCase):
    def test_accepts_frozen_current_root_files_and_module_argv(self) -> None:
        self.assertEqual(
            [],
            release_flow._validate_full_regression_receipt(
                _current_three_root_receipt(), SOURCE, TREE
            ),
        )

    def test_rejects_missing_v265_root_or_bound_file(self) -> None:
        expected_codes = {
            "root": "E_V250_CURRENT_DENOMINATOR_INCOMPLETE",
            "file": "E_V250_CURRENT_DENOMINATOR_ROOT_COVERAGE",
        }
        for case in expected_codes:
            with self.subTest(case=case):
                receipt = copy.deepcopy(_current_three_root_receipt())
                denominator = receipt["denominator"]
                if case == "root":
                    denominator["test_roots"].remove("tests/v265")
                else:
                    denominator["test_files"] = denominator["test_files"][:-1]
                    denominator["test_file_count"] = 1
                    denominator["test_case_count"] = 1
                    denominator["test_file_set_sha256"] = (
                        release_flow.canonical_sha256(
                            denominator["test_files"]
                        )
                    )
                    receipt["discovered_test_count"] = 1
                    receipt["argv"] = receipt["argv"][:-1]
                _reseal(receipt)
                errors = release_flow._validate_full_regression_receipt(
                    receipt, SOURCE, TREE
                )
                self.assertIn(expected_codes[case], errors)

    def test_rejects_legacy_file_duplicate_or_module_order_drift(self) -> None:
        expected_codes = {
            "legacy": "E_V250_CURRENT_DENOMINATOR_FILE",
            "duplicate": "E_V250_CURRENT_DENOMINATOR_FILE_DUPLICATE",
            "order": "E_V250_CURRENT_FULL_RUN_CONTRACT",
        }
        for case in expected_codes:
            with self.subTest(case=case):
                receipt = copy.deepcopy(_current_three_root_receipt())
                denominator = receipt["denominator"]
                if case == "legacy":
                    denominator["test_files"][1]["path"] = (
                        "tests/v263/test_beta.py"
                    )
                    denominator["test_file_set_sha256"] = (
                        release_flow.canonical_sha256(
                            denominator["test_files"]
                        )
                    )
                elif case == "duplicate":
                    denominator["test_files"].append(
                        copy.deepcopy(denominator["test_files"][-1])
                    )
                    denominator["test_file_count"] = 3
                    denominator["test_case_count"] = 3
                    denominator["test_file_set_sha256"] = (
                        release_flow.canonical_sha256(
                            denominator["test_files"]
                        )
                    )
                    receipt["discovered_test_count"] = 3
                    receipt["argv"].append(receipt["argv"][-1])
                else:
                    receipt["argv"][-2:] = reversed(receipt["argv"][-2:])
                _reseal(receipt)
                errors = release_flow._validate_full_regression_receipt(
                    receipt, SOURCE, TREE
                )
                self.assertIn(expected_codes[case], errors)


if __name__ == "__main__":
    unittest.main()
