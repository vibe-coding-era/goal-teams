"""V2.65 frozen external-anchor denominator contract."""

from __future__ import annotations

import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from scripts.release import skill_release
from scripts.v250 import release_flow


class TestV263ExternalAnchorTestRoots(unittest.TestCase):
    COMMIT = "1" * 40
    TREE = "2" * 40

    def _fixture(self) -> tuple[dict[str, bytes], dict[str, object], dict[str, object]]:
        command_path = (
            "references/current/generations/V2.65/contracts/"
            "release-command-manifest.json"
        )
        security_path = (
            "references/current/generations/V2.65/contracts/"
            "release-security-review-manifest.json"
        )
        contract_path = "contracts/reviewed.json"
        runner_path = "scripts/checks/run-v250-release-security-review.py"
        files = {
            command_path: json.dumps(
                {
                    "release": {
                        "s1": {
                            "current_full_regression_denominator": {
                                "test_roots": ["tests/v250", "tests/v265"],
                                "published_predecessor_test_roots": ["tests/v263"],
                                "predecessor_test_invocation_limit": 0,
                                "predecessor_release_identity_path": "references/current/generations/V2.65/contracts/predecessor-release-identity.json"
                            }
                        }
                    }
                },
                sort_keys=True,
            ).encode(),
            security_path: b"{}",
            "references/current/ACTIVE.json": json.dumps(
                {"activation_manifest": "activation.json"}, sort_keys=True
            ).encode(),
            contract_path: b"reviewed contract",
            runner_path: b"reviewed runner",
            "tests/v250/test_alpha.py": b"alpha",
            "tests/v263/test_beta.py": b"beta",
            "tests/v265/test_gamma.py": b"gamma",
            "tests/v26/test_legacy.py": b"legacy",
        }
        expected_tests = [
            {
                "path": path,
                "sha256": hashlib.sha256(files[path]).hexdigest(),
            }
            for path in (
                "tests/v250/test_alpha.py",
                "tests/v265/test_gamma.py",
            )
        ]
        full = {
            "denominator": {
                "test_roots": ["tests/v250", "tests/v265"],
                "published_predecessor_test_roots": ["tests/v263"],
                "predecessor_test_invocation_limit": 0,
                "predecessor_release_identity_path": "references/current/generations/V2.65/contracts/predecessor-release-identity.json",
                "test_files": expected_tests,
                "test_file_count": len(expected_tests),
                "test_file_set_sha256": release_flow.canonical_sha256(expected_tests),
                "source_commit": self.COMMIT,
                "source_tree": self.TREE,
                "contract_sha256": hashlib.sha256(files[command_path]).hexdigest(),
            }
        }
        security = {
            "contract_digests": {
                contract_path: hashlib.sha256(files[contract_path]).hexdigest()
            },
            "reviewer_identity": {
                "runner_sha256": hashlib.sha256(files[runner_path]).hexdigest()
            },
        }
        s1 = {
            "release_gate_receipts": {
                "full_regression": full,
                "release_security_review": security,
            },
            "released_runtime_transition": {},
        }
        s2 = {
            "assets": [{"name": "goal-teams-V2.65.tar.gz"}],
            "asset_set_id": "asset-set",
            "asset_set_digest": "3" * 64,
            "receipt_sha256": "4" * 64,
        }
        integrity = {
            "source_commit": self.COMMIT,
            "source_tree": self.TREE,
            "asset_set_id": s2["asset_set_id"],
            "asset_set_digest": s2["asset_set_digest"],
            "s2_receipt_sha256": s2["receipt_sha256"],
            "asset_build_invocation_count": 0,
            "second_build_comparison_attempted": False,
            "reproducibility_claim": False,
        }
        integrity["receipt_sha256"] = release_flow.canonical_sha256(integrity)
        asset_validation = {
            "s2_receipt": s2,
            "public_assets": s2["assets"],
            "asset_integrity_validation_receipt": integrity,
        }
        return files, s1, asset_validation

    def _validate(
        self,
        files: dict[str, bytes],
        s1: dict[str, object],
        asset_validation: dict[str, object],
    ) -> dict[str, object]:
        blob_by_id = {f"blob-{index}": content for index, content in enumerate(files.values())}
        tree = {
            path: ("100644", blob_id)
            for path, blob_id in zip(files, blob_by_id, strict=True)
        }
        builder = SimpleNamespace(
            tree=lambda _commit: tree,
            blob=lambda blob_id: blob_by_id[blob_id],
        )
        flow = SimpleNamespace(
            canonical_sha256=release_flow.canonical_sha256,
            validate_s2_receipt=lambda *_args, **_kwargs: {"ok": True},
        )
        with (
            mock.patch.object(skill_release, "_builder_module", return_value=builder),
            mock.patch.object(skill_release, "_release_flow_module", return_value=flow),
            mock.patch.object(
                skill_release,
                "_validate_v249_runtime_external_anchor",
                return_value={"runtime": "5" * 64},
            ),
            mock.patch.object(
                skill_release,
                "_security_external_anchor_paths",
                return_value={"contracts/reviewed.json"},
            ),
        ):
            return skill_release._validate_v250_external_anchors(
                commit=self.COMMIT,
                source_tree=self.TREE,
                s1_check_receipt=s1,
                asset_validation_receipt=asset_validation,
                version="V2.65",
            )

    def test_external_anchor_uses_all_current_test_roots_from_frozen_contract(self) -> None:
        files, s1, asset_validation = self._fixture()

        receipt = self._validate(files, s1, asset_validation)

        denominator = s1["release_gate_receipts"]["full_regression"]["denominator"]
        self.assertEqual(
            release_flow.canonical_sha256(denominator["test_files"]),
            receipt["current_test_file_set_sha256"],
        )

    def test_external_anchor_rejects_receipt_that_omits_current_roots(self) -> None:
        files, s1, asset_validation = self._fixture()
        denominator = s1["release_gate_receipts"]["full_regression"]["denominator"]
        denominator["test_files"] = denominator["test_files"][:1]
        denominator["test_file_count"] = 1
        denominator["test_file_set_sha256"] = release_flow.canonical_sha256(
            denominator["test_files"]
        )

        with self.assertRaisesRegex(
            skill_release.SkillReleaseError,
            "E_V265_CURRENT_DENOMINATOR_EXTERNAL_ANCHOR",
        ):
            self._validate(files, s1, asset_validation)


if __name__ == "__main__":
    unittest.main()
