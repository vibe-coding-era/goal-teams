from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
RELEASE_ENTRY = ROOT / "scripts" / "release" / "release.py"
COMMIT = "b" * 40
BASE = "a" * 40
TREE = "c" * 40


def _load_release():
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_public_scan_release_gate_tests", RELEASE_ENTRY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load_release()


def _state() -> dict[str, object]:
    return {
        "repository": "vibe-coding-era/goal-teams",
        "version": "V2.40",
        "base_main_commit": BASE,
        "candidate_commit": COMMIT,
        "candidate_tree": TREE,
        "github_authority": {"actor_id": 240},
    }


class FakeBaselineModule:
    @staticmethod
    def load_baseline(_value: bytes) -> dict[str, object]:
        return {}

    @staticmethod
    def validate_baseline(
        _value: object, *, version: str
    ) -> dict[str, object]:
        assert version == "V2.40"
        return {
            "review": {
                "reviewer_type": "independent_release_reviewer",
                "independent": True,
                "decision": "accepted",
                "review_id": "review-v240",
            },
            "assertions": [],
        }


class V240PublicScanReleaseGateTests(unittest.TestCase):
    def test_trust_bindings_are_derived_from_exact_frozen_blobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blobs = {
                release.PUBLIC_SCAN_RELATIVE: b"scanner\n",
                release.PUBLIC_SCAN_DETECTOR_RELATIVE: b"detector\n",
                release.PUBLIC_SCAN_BASELINE_RELATIVE: b"baseline\n",
            }
            for relative, data in blobs.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            with mock.patch.object(release, "RELEASE_ROOT", root), mock.patch.object(
                release,
                "_git_blob_bytes",
                side_effect=lambda _commit, path: blobs[path],
            ), mock.patch.object(
                release, "_load_public_scan_module", return_value=FakeBaselineModule
            ):
                bindings = release._public_scan_trust_bindings(_state())
            self.assertEqual(
                bindings["scanner_blob_sha256"],
                hashlib.sha256(blobs[release.PUBLIC_SCAN_RELATIVE]).hexdigest(),
            )
            self.assertEqual(
                bindings["detector_blob_sha256"],
                hashlib.sha256(
                    blobs[release.PUBLIC_SCAN_DETECTOR_RELATIVE]
                ).hexdigest(),
            )
            self.assertEqual(bindings["baseline_assertion_count"], 0)

    def test_complete_scan_inputs_are_fixed_by_state_and_constants(self) -> None:
        captured: dict[str, object] = {}
        bindings = {
            "scanner_blob_sha256": "1" * 64,
            "detector_blob_sha256": "2" * 64,
            "baseline_blob_sha256": hashlib.sha256(b"baseline\n").hexdigest(),
        }

        def scan_surfaces(**kwargs):
            captured.update(kwargs)
            return {
                "passed": True,
                "errors": [],
                "unwaived_findings": [],
                "trust_bindings": {
                    "scanner_blob_sha256": bindings["scanner_blob_sha256"],
                    "detector_blob_sha256": bindings["detector_blob_sha256"],
                    "baseline_blob_sha256": bindings["baseline_blob_sha256"],
                },
                "receipt_sha256": "3" * 64,
            }

        module = types.SimpleNamespace(scan_surfaces=scan_surfaces)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            release, "_public_scan_trust_bindings", return_value=bindings
        ), mock.patch.object(
            release, "_load_public_scan_module", return_value=module
        ), mock.patch.object(
            release, "_git_blob_bytes", return_value=b"baseline\n"
        ):
            receipt = release._run_public_release_scan(_state(), Path(directory))
        self.assertEqual(receipt["receipt_sha256"], "3" * 64)
        self.assertEqual(captured["base_commit"], BASE)
        self.assertEqual(captured["candidate_commit"], COMMIT)
        self.assertEqual(captured["candidate_tree"], TREE)
        self.assertEqual(captured["expected_detector_digest"], "2" * 64)
        self.assertEqual(captured["tag_message"], release.CANONICAL_TAG_MESSAGE)
        self.assertEqual(set(captured["asset_paths"]), {
            "goal-teams-V2.40.tar.gz",
            "SHA256SUMS",
            "_release.json",
            "_files.sha256",
        })

    def test_unwaived_or_unbound_scan_can_never_pass_the_release_gate(self) -> None:
        bindings = {
            "scanner_blob_sha256": "1" * 64,
            "detector_blob_sha256": "2" * 64,
            "baseline_blob_sha256": hashlib.sha256(b"baseline\n").hexdigest(),
        }
        module = types.SimpleNamespace(
            scan_surfaces=lambda **_kwargs: {
                "passed": False,
                "errors": ["unwaived"],
                "unwaived_findings": [{"path": "git/final/private.txt"}],
                "trust_bindings": {},
                "receipt_sha256": "3" * 64,
            }
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            release, "_public_scan_trust_bindings", return_value=bindings
        ), mock.patch.object(
            release, "_load_public_scan_module", return_value=module
        ), mock.patch.object(
            release, "_git_blob_bytes", return_value=b"baseline\n"
        ):
            with self.assertRaises(release.PolicyError) as caught:
                release._run_public_release_scan(_state(), Path(directory))
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_PUBLIC_SCAN")

    def test_revalidation_requires_the_exact_cp10_scan_receipt(self) -> None:
        scan = {
            "passed": True,
            "errors": [],
            "unwaived_findings": [],
            "receipt_sha256": "3" * 64,
        }
        assets = {"fixed": {"sha256": "4" * 64, "size": 1}}
        validation = {"passed": True}
        validation_sha = release._canonical_json_sha256(validation)
        sealed = {
            "assets": assets,
            "asset_set_sha256": release._canonical_json_sha256(assets),
            "validator_receipt_sha256": validation_sha,
            "public_scan_receipt": scan,
        }
        completed = subprocess.CompletedProcess(
            ["validate"], 0, json.dumps(validation), ""
        )
        patches = (
            mock.patch.object(release, "_operation_details", return_value=sealed),
            mock.patch.object(release, "_canonical_release_assets", return_value=assets),
            mock.patch.object(release, "_run_fixed", return_value=completed),
        )
        with patches[0], patches[1], patches[2], mock.patch.object(
            release, "_run_public_release_scan", return_value=scan
        ):
            receipt = release._revalidate_canonical_release(_state())
        self.assertEqual(receipt["public_scan_receipt_sha256"], "3" * 64)

        drifted = {**scan, "receipt_sha256": "5" * 64}
        with patches[0], patches[1], patches[2], mock.patch.object(
            release, "_run_public_release_scan", return_value=drifted
        ):
            with self.assertRaises(release.PolicyError) as caught:
                release._revalidate_canonical_release(_state())
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_PUBLIC_SCAN")

    def test_cp05_independent_approval_must_bind_the_scanner_baseline(self) -> None:
        bindings = {
            "candidate_commit": COMMIT,
            "candidate_tree": TREE,
            "base_main_commit": BASE,
            "scanner_blob_sha256": "1" * 64,
            "detector_blob_sha256": "2" * 64,
            "baseline_blob_sha256": "3" * 64,
            "baseline_assertion_count": 4,
            "baseline_assertions_sha256": "5" * 64,
            "baseline_review_sha256": "6" * 64,
        }
        approval = {
            "release_actor_id": 240,
            "reviewer": {
                "role": "independent_release_reviewer",
                "member_id": "scanner-reviewer-v240",
                "run_id": "RUN-V240-SCANNER-REVIEW",
                "independent": True,
                "decision": "accepted",
                "source_commit": COMMIT,
                "reviewed_at": "2026-07-14T07:00:00Z",
            },
            "head_sha": COMMIT,
            "workflow_path": ".github/workflows/release-gate.yml",
            "workflow_blob_sha": "d" * 40,
            "required_jobs": [
                "check-ubuntu",
                "check-macos",
                "release-asset-gate",
            ],
            "checker_tree_sha256": "7" * 64,
            "checker_file_count": 8,
        }
        command = subprocess.CompletedProcess(["git"], 0, "d" * 40 + "\n", "")
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            release, "_workspace_root", return_value=Path(directory)
        ), mock.patch.object(
            release, "_require_clean_candidate_checkout", return_value={}
        ), mock.patch.object(
            release, "_run_fixed", return_value=command
        ), mock.patch.object(
            release,
            "_checker_surface_digest",
            return_value={"checker_tree_sha256": "7" * 64, "checker_file_count": 8},
        ), mock.patch.object(
            release, "_public_scan_trust_bindings", return_value=bindings
        ):
            with self.assertRaises(release.PolicyError) as caught:
                release._execute_local_operation(
                    "CP05.workflow_approve",
                    _state(),
                    {"ci_approval": approval},
                    Path(directory) / "state.json",
                )
            self.assertEqual(
                caught.exception.receipt["error_code"], "E_V240_CI_TRUST_BINDING"
            )

            accepted = release._execute_local_operation(
                "CP05.workflow_approve",
                _state(),
                {"ci_approval": {**approval, "public_scan_bindings": bindings}},
                Path(directory) / "state.json",
            )
        self.assertEqual(
            accepted["details"]["ci_approval"]["public_scan_bindings"], bindings
        )


if __name__ == "__main__":
    unittest.main()
