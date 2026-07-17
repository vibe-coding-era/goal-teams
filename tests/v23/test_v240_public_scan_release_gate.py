from __future__ import annotations

import copy
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
ASSERTION_SET = "8" * 64
OCCURRENCE_SET = "9" * 64
REVIEWED_AT = "2026-07-14T07:00:00Z"


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


def _baseline_review(**changes: object) -> dict[str, object]:
    review: dict[str, object] = {
        "reviewer_type": "independent_release_reviewer",
        "independent": True,
        "decision": "accepted",
        "review_id": "review-v240",
        "reviewer_member_id": "scanner-reviewer-v240",
        "reviewer_run_id": "RUN-V240-SCANNER-REVIEW",
        "assertion_set_sha256": ASSERTION_SET,
        "occurrence_set_sha256": OCCURRENCE_SET,
        "reviewed_at": REVIEWED_AT,
    }
    review.update(changes)
    return review


def _bindings(**changes: object) -> dict[str, object]:
    review = _baseline_review()
    bindings: dict[str, object] = {
        "candidate_commit": COMMIT,
        "candidate_tree": TREE,
        "base_main_commit": BASE,
        "scanner_path": release.PUBLIC_SCAN_RELATIVE,
        "scanner_blob_sha256": "1" * 64,
        "detector_path": release.PUBLIC_SCAN_DETECTOR_RELATIVE,
        "detector_blob_sha256": "2" * 64,
        "baseline_path": release.PUBLIC_SCAN_BASELINE_RELATIVE,
        "baseline_blob_sha256": "3" * 64,
        "baseline_assertion_count": 0,
        "baseline_assertions_sha256": release._canonical_json_sha256([]),
        "baseline_assertion_set_sha256": ASSERTION_SET,
        "baseline_occurrence_set_sha256": OCCURRENCE_SET,
        "baseline_review": review,
        "baseline_review_sha256": release._canonical_json_sha256(review),
    }
    bindings.update(changes)
    return bindings


def _receipt_trust(bindings: dict[str, object]) -> dict[str, object]:
    return {
        key: bindings[key]
        for key in (
            "scanner_blob_sha256",
            "detector_blob_sha256",
            "baseline_blob_sha256",
            "baseline_assertion_count",
            "baseline_assertions_sha256",
            "baseline_assertion_set_sha256",
            "baseline_occurrence_set_sha256",
            "baseline_review_sha256",
        )
    }


def _receipt_identity(
    state: dict[str, object] | None = None,
) -> dict[str, object]:
    current = _state() if state is None else state
    return {
        "version": current["version"],
        "base_commit": current["base_main_commit"],
        "candidate_commit": current["candidate_commit"],
        "candidate_tree": current["candidate_tree"],
        "asset_names": [
            "SHA256SUMS",
            "_files.sha256",
            "_release.json",
            "goal-teams-V2.40.tar.gz",
        ],
    }


def _receipt_coverage(surface_count: int = 1) -> dict[str, object]:
    return {
        "new_commit_count": 1,
        "introduced_blob_count": 1,
        "history_tree_path_count": 1,
        "final_blob_path_count": 1,
        "snapshot_file_count": 1,
        "snapshot_package_file_count": 1,
        "tar_regular_file_count": 1,
        "outer_asset_count": 4,
        "release_text_count": 3,
        "surface_count": surface_count,
        "snapshot_tar_identity_sha256": "a" * 64,
        "occurrence_set_sha256": "b" * 64,
    }


def _seal_receipt(receipt: dict[str, object]) -> dict[str, object]:
    sealed = copy.deepcopy(receipt)
    sealed.pop("receipt_sha256", None)
    sealed["receipt_sha256"] = release._canonical_json_sha256(sealed)
    return sealed


def _valid_receipt(
    bindings: dict[str, object] | None = None,
    state: dict[str, object] | None = None,
) -> dict[str, object]:
    current_bindings = _bindings() if bindings is None else bindings
    return _seal_receipt(
        {
            "schema_version": "goal-teams-public-scan-receipt-v2",
            "passed": True,
            "identity": _receipt_identity(state),
            "trust_bindings": _receipt_trust(current_bindings),
            "coverage": _receipt_coverage(),
            "occurrence_set_sha256": "b" * 64,
            "surfaces": [{"path": "git/final/README.md"}],
            "waived_findings": [],
            "unwaived_findings": [],
            "baseline_candidate_rows": [],
            "errors": [],
        }
    )


def _context(
    module: object,
    bindings: dict[str, object],
    baseline_bytes: bytes = b"baseline\n",
) -> dict[str, object]:
    return {
        "module": module,
        "bindings": bindings,
        "baseline_bytes": baseline_bytes,
    }


def _approval(bindings: dict[str, object], **reviewer_changes: object) -> dict[str, object]:
    reviewer: dict[str, object] = {
        "role": "independent_release_reviewer",
        "member_id": "scanner-reviewer-v240",
        "run_id": "RUN-V240-SCANNER-REVIEW",
        "independent": True,
        "decision": "accepted",
        "review_id": "review-v240",
        "source_commit": COMMIT,
        "candidate_tree": TREE,
        "assertion_set_sha256": ASSERTION_SET,
        "occurrence_set_sha256": OCCURRENCE_SET,
        "reviewed_at": REVIEWED_AT,
    }
    reviewer.update(reviewer_changes)
    return {
        "release_actor_id": 240,
        "reviewer": reviewer,
        "head_sha": COMMIT,
        "workflow_path": ".github/workflows/release-gate.yml",
        "workflow_id": 240,
        "workflow_blob_sha": "d" * 40,
        "required_jobs": [
            "check-ubuntu",
            "check-macos",
            "release-asset-gate",
        ],
        "checker_tree_sha256": "7" * 64,
        "checker_file_count": 8,
        "public_scan_bindings": bindings,
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
            "review": _baseline_review(),
            "assertions": [],
        }

    @staticmethod
    def assertion_set_sha256(_assertions: object) -> str:
        return ASSERTION_SET

    @staticmethod
    def occurrence_set_sha256(_assertions: object) -> str:
        return OCCURRENCE_SET


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
            self.assertEqual(bindings["baseline_assertion_set_sha256"], ASSERTION_SET)
            self.assertEqual(bindings["baseline_occurrence_set_sha256"], OCCURRENCE_SET)
            self.assertNotIn("source_commit", bindings["baseline_review"])
            self.assertNotIn("candidate_tree", bindings["baseline_review"])

    def test_real_scanner_v2_digest_helpers_match_release_bindings(self) -> None:
        scanner_bytes = (ROOT / release.PUBLIC_SCAN_RELATIVE).read_bytes()
        real_module = release._load_public_scan_module(
            source_bytes=scanner_bytes,
            candidate_commit=COMMIT,
        )
        self.assertEqual(
            real_module._IMPORTED_SCANNER_BLOB_SHA256,
            hashlib.sha256(scanner_bytes).hexdigest(),
        )
        assertion_set = real_module.assertion_set_sha256([])
        occurrence_set = real_module.occurrence_set_sha256([])
        review = _baseline_review(
            assertion_set_sha256=assertion_set,
            occurrence_set_sha256=occurrence_set,
        )
        baseline_bytes = (
            json.dumps(
                {
                    "schema_version": "goal-teams-public-scan-baseline-v2",
                    "version": "V2.40",
                    "review": review,
                    "assertions": [],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blobs = {
                release.PUBLIC_SCAN_RELATIVE: (
                    ROOT / release.PUBLIC_SCAN_RELATIVE
                ).read_bytes(),
                release.PUBLIC_SCAN_DETECTOR_RELATIVE: (
                    ROOT / release.PUBLIC_SCAN_DETECTOR_RELATIVE
                ).read_bytes(),
                release.PUBLIC_SCAN_BASELINE_RELATIVE: baseline_bytes,
            }
            for relative, data in blobs.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            with mock.patch.object(release, "RELEASE_ROOT", root), mock.patch.object(
                release,
                "_git_blob_bytes",
                side_effect=lambda _commit, path: blobs[path],
            ):
                bindings = release._public_scan_trust_bindings(_state())
        self.assertEqual(bindings["baseline_assertion_set_sha256"], assertion_set)
        self.assertEqual(bindings["baseline_occurrence_set_sha256"], occurrence_set)
        self.assertEqual(bindings["baseline_review"], review)

    def test_replace_between_check_and_import_cannot_execute_worktree_bytes(self) -> None:
        scanner_bytes = (ROOT / release.PUBLIC_SCAN_RELATIVE).read_bytes()
        frozen_module = release._load_public_scan_module(
            source_bytes=scanner_bytes,
            candidate_commit=COMMIT,
        )
        assertion_set = frozen_module.assertion_set_sha256([])
        occurrence_set = frozen_module.occurrence_set_sha256([])
        review = _baseline_review(
            assertion_set_sha256=assertion_set,
            occurrence_set_sha256=occurrence_set,
        )
        baseline_bytes = (
            json.dumps(
                {
                    "schema_version": "goal-teams-public-scan-baseline-v2",
                    "version": "V2.40",
                    "review": review,
                    "assertions": [],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        ).encode()
        detector_bytes = (ROOT / release.PUBLIC_SCAN_DETECTOR_RELATIVE).read_bytes()
        blobs = {
            release.PUBLIC_SCAN_RELATIVE: scanner_bytes,
            release.PUBLIC_SCAN_DETECTOR_RELATIVE: detector_bytes,
            release.PUBLIC_SCAN_BASELINE_RELATIVE: baseline_bytes,
        }
        original_loader = release._load_public_scan_module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, data in blobs.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

            def replace_then_load(**kwargs: object) -> object:
                (root / release.PUBLIC_SCAN_RELATIVE).write_bytes(
                    b"raise RuntimeError('worktree replacement executed')\n"
                )
                return original_loader(**kwargs)

            with mock.patch.object(
                release, "RELEASE_ROOT", root
            ), mock.patch.object(
                release,
                "_git_blob_bytes",
                side_effect=lambda _commit, path: blobs[path],
            ), mock.patch.object(
                release,
                "_load_public_scan_module",
                side_effect=replace_then_load,
            ) as loader:
                context = release._public_scan_trust_context(_state())

        self.assertEqual(loader.call_count, 1)
        self.assertEqual(
            context["module"]._IMPORTED_SCANNER_BLOB_SHA256,
            hashlib.sha256(scanner_bytes).hexdigest(),
        )
        self.assertEqual(context["bindings"]["baseline_review"], review)

    def test_real_scanner_receipt_matches_release_gate_exact_contract(self) -> None:
        from tests.v23.test_v240_public_scan import (
            PublicScanFixture,
            _baseline,
            scanner,
        )

        fixture = PublicScanFixture(self)
        receipt = fixture.scan()
        baseline_bytes = _baseline()
        baseline = scanner.validate_baseline(
            scanner.load_baseline(baseline_bytes), version="V2.40"
        )
        identity = receipt["identity"]
        trust = receipt["trust_bindings"]
        expected_trust_fields = {
            "scanner_blob_sha256",
            "detector_blob_sha256",
            "baseline_blob_sha256",
            "baseline_assertion_count",
            "baseline_assertions_sha256",
            "baseline_assertion_set_sha256",
            "baseline_occurrence_set_sha256",
            "baseline_review_sha256",
        }
        self.assertEqual(set(trust), expected_trust_fields)
        state = {
            "repository": "vibe-coding-era/goal-teams",
            "version": "V2.40",
            "base_main_commit": identity["base_commit"],
            "candidate_commit": identity["candidate_commit"],
            "candidate_tree": identity["candidate_tree"],
            "github_authority": {"actor_id": 240},
        }
        bindings = {
            "candidate_commit": identity["candidate_commit"],
            "candidate_tree": identity["candidate_tree"],
            "base_main_commit": identity["base_commit"],
            "scanner_path": release.PUBLIC_SCAN_RELATIVE,
            "scanner_blob_sha256": trust["scanner_blob_sha256"],
            "detector_path": release.PUBLIC_SCAN_DETECTOR_RELATIVE,
            "detector_blob_sha256": trust["detector_blob_sha256"],
            "baseline_path": release.PUBLIC_SCAN_BASELINE_RELATIVE,
            "baseline_blob_sha256": trust["baseline_blob_sha256"],
            "baseline_assertion_count": trust["baseline_assertion_count"],
            "baseline_assertions_sha256": trust["baseline_assertions_sha256"],
            "baseline_assertion_set_sha256": trust[
                "baseline_assertion_set_sha256"
            ],
            "baseline_occurrence_set_sha256": trust[
                "baseline_occurrence_set_sha256"
            ],
            "baseline_review": baseline["review"],
            "baseline_review_sha256": trust["baseline_review_sha256"],
        }
        module = types.SimpleNamespace(
            scan_surfaces=lambda **_kwargs: receipt,
        )
        with mock.patch.object(
            release,
            "_public_scan_trust_context",
            return_value=_context(module, bindings, baseline_bytes),
        ):
            accepted = release._run_public_release_scan(state, fixture.snapshot)
        self.assertEqual(accepted, receipt)

    def test_complete_scan_inputs_are_fixed_by_state_and_constants(self) -> None:
        captured: dict[str, object] = {}
        bindings = _bindings(
            baseline_blob_sha256=hashlib.sha256(b"baseline\n").hexdigest()
        )
        expected = _valid_receipt(bindings)
        calls = 0

        def scan_surfaces(**kwargs):
            nonlocal calls
            calls += 1
            captured.update(kwargs)
            return expected

        module = types.SimpleNamespace(scan_surfaces=scan_surfaces)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            release,
            "_public_scan_trust_context",
            return_value=_context(module, bindings),
        ), mock.patch.object(
            release,
            "_load_public_scan_module",
            side_effect=AssertionError("operation attempted a second import"),
        ):
            receipt = release._run_public_release_scan(_state(), Path(directory))
        self.assertEqual(receipt, expected)
        self.assertEqual(calls, 1)
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
        bindings = _bindings(
            baseline_blob_sha256=hashlib.sha256(b"baseline\n").hexdigest()
        )
        rejected = _valid_receipt(bindings)
        rejected["passed"] = False
        rejected["errors"] = ["unwaived"]
        rejected["unwaived_findings"] = [
            {"path": "git/final/private.txt"}
        ]
        rejected = _seal_receipt(rejected)
        module = types.SimpleNamespace(
            scan_surfaces=lambda **_kwargs: rejected,
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            release,
            "_public_scan_trust_context",
            return_value=_context(module, bindings),
        ):
            with self.assertRaises(release.PolicyError) as caught:
                release._run_public_release_scan(_state(), Path(directory))
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_PUBLIC_SCAN")

    def _assert_receipt_rejected(
        self,
        receipt: object,
        bindings: dict[str, object],
        *,
        receipt_hash: object | None = None,
    ) -> None:
        module = types.SimpleNamespace(
            scan_surfaces=lambda **_kwargs: receipt,
        )
        if receipt_hash is not None:
            module.receipt_hash = receipt_hash
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            release,
            "_public_scan_trust_context",
            return_value=_context(module, bindings),
        ), self.assertRaises(release.PolicyError) as caught:
            release._run_public_release_scan(_state(), Path(directory))
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_PUBLIC_SCAN",
        )

    def test_receipt_closed_sets_reject_every_field_deletion_and_extension(
        self,
    ) -> None:
        bindings = _bindings()
        valid = _valid_receipt(bindings)

        for field in sorted(valid):
            candidate = copy.deepcopy(valid)
            candidate.pop(field)
            if field != "receipt_sha256":
                candidate = _seal_receipt(candidate)
            with self.subTest(layer="top", deletion=field):
                self._assert_receipt_rejected(candidate, bindings)

        extended = copy.deepcopy(valid)
        extended["unexpected"] = True
        with self.subTest(layer="top", extension="unexpected"):
            self._assert_receipt_rejected(_seal_receipt(extended), bindings)

        for layer in ("identity", "trust_bindings", "coverage"):
            nested = valid[layer]
            assert isinstance(nested, dict)
            for field in sorted(nested):
                candidate = copy.deepcopy(valid)
                candidate_nested = candidate[layer]
                assert isinstance(candidate_nested, dict)
                candidate_nested.pop(field)
                with self.subTest(layer=layer, deletion=field):
                    self._assert_receipt_rejected(
                        _seal_receipt(candidate), bindings
                    )
            candidate = copy.deepcopy(valid)
            candidate_nested = candidate[layer]
            assert isinstance(candidate_nested, dict)
            candidate_nested["unexpected"] = True
            with self.subTest(layer=layer, extension="unexpected"):
                self._assert_receipt_rejected(
                    _seal_receipt(candidate), bindings
                )

    def test_receipt_required_lists_reject_non_list_types_and_minimal_receipt(
        self,
    ) -> None:
        bindings = _bindings()
        valid = _valid_receipt(bindings)
        for field in sorted(release._PUBLIC_SCAN_LIST_FIELDS):
            for wrong_type in ({}, (), None):
                candidate = copy.deepcopy(valid)
                candidate[field] = wrong_type
                with self.subTest(field=field, type=type(wrong_type).__name__):
                    self._assert_receipt_rejected(
                        _seal_receipt(candidate), bindings
                    )

        minimal = _seal_receipt(
            {
                "schema_version": "goal-teams-public-scan-receipt-v2",
                "passed": True,
                "errors": [],
                "unwaived_findings": [],
            }
        )
        self._assert_receipt_rejected(minimal, bindings)

    def test_receipt_identity_trust_coverage_and_occurrence_are_exact(
        self,
    ) -> None:
        bindings = _bindings()
        variants: dict[str, dict[str, object]] = {}
        identity_drift = _valid_receipt(bindings)
        identity = identity_drift["identity"]
        assert isinstance(identity, dict)
        identity["candidate_tree"] = "d" * 40
        variants["identity"] = identity_drift

        trust_drift = _valid_receipt(bindings)
        trust = trust_drift["trust_bindings"]
        assert isinstance(trust, dict)
        trust["baseline_occurrence_set_sha256"] = "4" * 64
        variants["trust"] = trust_drift

        coverage_drift = _valid_receipt(bindings)
        coverage = coverage_drift["coverage"]
        assert isinstance(coverage, dict)
        coverage["outer_asset_count"] = 3
        variants["coverage"] = coverage_drift

        occurrence_drift = _valid_receipt(bindings)
        occurrence_drift["occurrence_set_sha256"] = "5" * 64
        variants["occurrence"] = occurrence_drift

        for label, candidate in variants.items():
            with self.subTest(label=label):
                self._assert_receipt_rejected(
                    _seal_receipt(candidate), bindings
                )

    def test_release_computes_receipt_hash_and_ignores_malicious_helper(
        self,
    ) -> None:
        bindings = _bindings()
        forged = _valid_receipt(bindings)
        forged["receipt_sha256"] = "4" * 64
        malicious_helper = mock.Mock(return_value="4" * 64)
        self._assert_receipt_rejected(
            forged,
            bindings,
            receipt_hash=malicious_helper,
        )
        malicious_helper.assert_not_called()

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
            mock.patch.object(
                release, "_canonical_snapshot", return_value=Path("/canonical/V2.40")
            ),
        )
        with patches[0], patches[1], patches[2], patches[3], mock.patch.object(
            release, "_run_public_release_scan", return_value=scan
        ):
            receipt = release._revalidate_canonical_release(_state())
        self.assertEqual(receipt["public_scan_receipt_sha256"], "3" * 64)

        drifted = {**scan, "receipt_sha256": "5" * 64}
        with patches[0], patches[1], patches[2], patches[3], mock.patch.object(
            release, "_run_public_release_scan", return_value=drifted
        ):
            with self.assertRaises(release.PolicyError) as caught:
                release._revalidate_canonical_release(_state())
        self.assertEqual(caught.exception.receipt["error_code"], "E_V240_PUBLIC_SCAN")

    def test_cp05_independent_approval_must_bind_the_scanner_baseline(self) -> None:
        bindings = _bindings()
        approval = _approval(bindings)
        self.assertEqual(set(approval), set(release.CP05_CI_APPROVAL_FIELDS))
        self.assertEqual(approval["workflow_id"], 240)
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
                    {"ci_approval": {**approval, "public_scan_bindings": None}},
                    Path(directory) / "state.json",
                )
            self.assertEqual(
                caught.exception.receipt["error_code"], "E_V240_CI_TRUST_BINDING"
            )

            accepted = release._execute_local_operation(
                "CP05.workflow_approve",
                _state(),
                {"ci_approval": approval},
                Path(directory) / "state.json",
            )
        self.assertEqual(
            accepted["details"]["ci_approval"]["public_scan_bindings"], bindings
        )

    def test_cp05_detached_review_exactly_matches_baseline_and_candidate(self) -> None:
        bindings = _bindings()
        approval = _approval(bindings)
        self.assertEqual(
            release._validate_public_scan_approval_review(
                _state(), approval, bindings
            )["source_commit"],
            COMMIT,
        )
        self.assertNotIn("source_commit", bindings["baseline_review"])
        self.assertNotIn("candidate_tree", bindings["baseline_review"])

        drift_cases = {
            "member identity": {"member_id": "another-reviewer"},
            "run identity": {"run_id": "RUN-V240-ANOTHER-REVIEW"},
            "review id": {"review_id": "another-review"},
            "candidate commit": {"source_commit": "e" * 40},
            "candidate tree": {"candidate_tree": "f" * 40},
            "assertion set": {"assertion_set_sha256": "a" * 64},
            "occurrence set": {"occurrence_set_sha256": "b" * 64},
            "review time": {"reviewed_at": "2026-07-14T07:00:01Z"},
        }
        for label, changes in drift_cases.items():
            with self.subTest(label=label), self.assertRaises(
                release.PolicyError
            ) as caught:
                release._validate_public_scan_approval_review(
                    _state(), _approval(bindings, **changes), bindings
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_CI_TRUST_BINDING",
            )

    def test_in_tree_baseline_rejects_impossible_candidate_self_reference(self) -> None:
        for forbidden_field, value in (
            ("source_commit", COMMIT),
            ("candidate_tree", TREE),
        ):
            normalized = {
                "review": _baseline_review(**{forbidden_field: value}),
                "assertions": [],
            }
            with self.subTest(field=forbidden_field), self.assertRaises(
                release.PolicyError
            ) as caught:
                release._public_scan_review_binding(
                    module=FakeBaselineModule,
                    normalized=normalized,
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_PUBLIC_SCAN_BASELINE",
            )

    def test_cp05_rejects_nonclosed_or_drifted_public_scan_bindings(self) -> None:
        review = _baseline_review()
        self_referential_review = _baseline_review(source_commit=COMMIT)
        variants = {
            "candidate binding": _bindings(candidate_commit="e" * 40),
            "tree binding": _bindings(candidate_tree="f" * 40),
            "base binding": _bindings(base_main_commit="0" * 40),
            "assertion set binding": _bindings(
                baseline_assertion_set_sha256="4" * 64
            ),
            "occurrence set binding": _bindings(
                baseline_occurrence_set_sha256="5" * 64
            ),
            "review digest binding": _bindings(
                baseline_review_sha256="6" * 64
            ),
            "self-referential baseline review": _bindings(
                baseline_review=self_referential_review,
                baseline_review_sha256=release._canonical_json_sha256(
                    self_referential_review
                ),
            ),
            "extra binding field": _bindings(unapproved=True),
        }
        for label, bindings in variants.items():
            with self.subTest(label=label), self.assertRaises(
                release.PolicyError
            ) as caught:
                release._validate_public_scan_approval_review(
                    _state(), _approval(bindings), bindings
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_CI_TRUST_BINDING",
            )

        valid_bindings = _bindings(
            baseline_review=review,
            baseline_review_sha256=release._canonical_json_sha256(review),
        )
        extended_approval = _approval(valid_bindings)
        extended_approval["unapproved"] = True
        with self.assertRaises(release.PolicyError) as caught:
            release._validate_public_scan_approval_review(
                _state(), extended_approval, valid_bindings
            )
        self.assertEqual(
            caught.exception.receipt["error_code"],
            "E_V240_CI_TRUST_BINDING",
        )

    def test_cp05_rejects_release_author_or_lead_self_review(self) -> None:
        for member_id, run_id in (
            ("Goal-Lead", "RUN-V240-SCANNER-REVIEW"),
            ("架构-Lead", "RUN-V240-SCANNER-REVIEW"),
            ("scanner-reviewer-v240", "RUN-V240-LEAD"),
        ):
            review = _baseline_review(
                reviewer_member_id=member_id,
                reviewer_run_id=run_id,
            )
            bindings = _bindings(
                baseline_review=review,
                baseline_review_sha256=release._canonical_json_sha256(review),
            )
            with self.subTest(member_id=member_id, run_id=run_id), self.assertRaises(
                release.PolicyError
            ) as caught:
                release._validate_public_scan_approval_review(
                    _state(),
                    _approval(bindings, member_id=member_id, run_id=run_id),
                    bindings,
                )
            self.assertEqual(
                caught.exception.receipt["error_code"],
                "E_V240_CI_TRUST_BINDING",
            )


if __name__ == "__main__":
    unittest.main()
