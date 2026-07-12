"""V2.35 tests-first contract for trusted version binding and archive paths.

The new binding module is loaded lazily so its pre-implementation absence is a
deterministic RED test rather than an import/discovery error.  Existing V2.34
helpers remain the compatibility oracle for calls without a descriptor.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v23.common import ROOT, gt, task_event
from tests.v23.test_v234_state_loop import (
    OWNER_RUN,
    VALIDATOR_RUN,
    initialize_bundle,
    require_v234,
    synthetic_contract_text,
)


BINDING_PATH = ROOT / "scripts" / "v23" / "version_binding.py"
CLOSURE_PATH = ROOT / "scripts" / "v23" / "v234_closure.py"
FIXTURE_PATH = ROOT / "tests" / "v23" / "fixtures" / "v235" / "version-bindings.json"
CONTRACT_FIXTURE_PATH = ROOT / "tests" / "v23" / "fixtures" / "v235" / "v2.35-contract.md"
FIXED_HASH = "a" * 64


_BINDING: Any | None = None
_BINDING_LOAD_ERROR: BaseException | None = None


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def assert_binding_rejection(
    test: unittest.TestCase, result: Any, error_code: str
) -> None:
    test.assertIsInstance(result, dict, result)
    test.assertFalse(result.get("ok"), result)
    test.assertEqual(result.get("error_code"), error_code, result)
    test.assertIn("mutation_count", result, result)
    test.assertEqual(result["mutation_count"], 0, result)


def tree_digest(root: Path) -> str:
    entries: list[dict[str, Any]] = []
    if not root.exists():
        return hashlib.sha256(b"").hexdigest()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "sha256": sha256_path(path),
                    "size": path.stat().st_size,
                }
            )
        elif path.is_dir():
            entries.append({"path": relative, "kind": "dir"})
    return hashlib.sha256(canonical_bytes(entries)).hexdigest()


def require_binding(test: unittest.TestCase) -> Any:
    global _BINDING, _BINDING_LOAD_ERROR
    if _BINDING is None and _BINDING_LOAD_ERROR is None:
        try:
            if not BINDING_PATH.is_file():
                raise FileNotFoundError(BINDING_PATH)
            spec = importlib.util.spec_from_file_location(
                "goalteams_v235_version_binding_under_test", BINDING_PATH
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {BINDING_PATH}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            _BINDING = module
        except BaseException as exc:
            _BINDING_LOAD_ERROR = exc
    if _BINDING_LOAD_ERROR is not None:
        test.fail(
            "V2.35 version binding implementation is not available yet: "
            f"{type(_BINDING_LOAD_ERROR).__name__}: {_BINDING_LOAD_ERROR}"
        )
    return _BINDING


def canonical_delta_contract() -> str:
    return CONTRACT_FIXTURE_PATH.read_text(encoding="utf-8")


def build_trusted_descriptor(repo: Path) -> dict[str, Any]:
    contract = repo / "spec" / "v2.35-contract.md"
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(canonical_delta_contract(), encoding="utf-8")
    contract_hash = sha256_path(contract)
    review = repo / "reviews" / "architecture-review.json"
    review.parent.mkdir(parents=True, exist_ok=True)
    review_record = {
        "schema_version": "goal-teams-v2.35-binding-review-v1",
        "review_id": "REVIEW-V235-BINDING-TEST",
        "artifact_type": "v2.35_delta_contract",
        "state": "passed",
        "decision": "approved",
        "current": True,
        "owner_run_id": "RUN-V235-ARCH-OWNER-TEST",
        "validator_run_id": "RUN-V235-ARCH-REVIEW-TEST",
        "artifact_ref": "spec/v2.35-contract.md",
        "artifact_sha256": contract_hash,
        "contract_sha256": contract_hash,
        "contract_revision": 2,
        "reviewed_at": "2026-07-12T00:00:00Z",
    }
    review.write_bytes(canonical_bytes(review_record) + b"\n")
    return {
        "schema_version": "goal-teams-version-binding-v1",
        "project_version": "V2.35",
        "release_version": "V2.35",
        "artifact_version": "V2.35-run2",
        "contract_ref": "spec/v2.35-contract.md",
        "contract_sha256": contract_hash,
        "contract_revision": 2,
        "review_ref": "reviews/architecture-review.json",
        "review_sha256": sha256_path(review),
        "review_state": "passed",
    }


def rewrite_review(
    repo: Path, descriptor: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    review = repo / descriptor["review_ref"]
    record = json.loads(review.read_text(encoding="utf-8"))
    deep_merge(record, patch)
    review.write_bytes(canonical_bytes(record) + b"\n")
    descriptor["review_sha256"] = sha256_path(review)
    return record


def rebind_contract_and_review(
    repo: Path, descriptor: dict[str, Any], contract_text: str, *, revision: int = 2
) -> None:
    contract = repo / descriptor["contract_ref"]
    contract.write_text(contract_text, encoding="utf-8")
    contract_hash = sha256_path(contract)
    descriptor["contract_sha256"] = contract_hash
    descriptor["contract_revision"] = revision
    rewrite_review(
        repo,
        descriptor,
        {
            "artifact_sha256": contract_hash,
            "contract_sha256": contract_hash,
            "contract_revision": revision,
        },
    )


def load_closure() -> Any:
    spec = importlib.util.spec_from_file_location(
        "goalteams_v234_closure_for_v235_test", CLOSURE_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(CLOSURE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def state_binding_inputs(repo: Path) -> tuple[Path, dict[str, Any], list[dict[str, Any]], bytes]:
    control_contract = repo / "control-contract.md"
    control_contract.write_text(synthetic_contract_text(), encoding="utf-8")
    event = task_event(
        "EVT-V235-BINDING-TEST-001",
        "TASK-V235-BINDING-TEST",
        0,
        "planned",
        attempt_id="ATT-V235-BINDING-TEST-001",
    )
    events = [event]
    checkpoint = gt.reduce_events(events, valid_evidence_ids=set(), evidence_registry={})
    checkpoint_bytes = canonical_bytes(checkpoint)
    binding = {
        "revision": 1,
        "prefix_sha256": gt.ledger_prefix_sha256(events, 1),
        "checkpoint_sha256": hashlib.sha256(checkpoint_bytes).hexdigest(),
        "last_event_id": event["event_id"],
    }
    return control_contract, binding, events, checkpoint_bytes


def v235_archive_descriptors() -> list[dict[str, Any]]:
    return [
        {
            "source_artifact_id": "ART-V235-PUBLIC-001",
            "source_ref": "public/release.md",
            "archive_ref": "release.md",
            "publication_state": "completed",
            "visibility": "public",
            "artifact_version": "V2.35-run2",
            "validator_run_id": VALIDATOR_RUN,
            "contract_revision": 2,
            "classification": "public_completion_doc",
            "accepted": True,
        }
    ]


def archive_completion() -> dict[str, Any]:
    return {
        "run_outcome_candidate": "achieved",
        "completion_audit": {
            "state": "passed",
            "validator_run_id": "RUN-COMPLETION-AUDITOR-V235-TEST",
            "ledger_revision": 50,
            "sha256": FIXED_HASH,
        },
        "contract_revision": 2,
    }


class V235VersionBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_default_and_explicit_binding(self) -> None:
        """ASSERT-V235-003: default V2.34, trusted explicit V2.35."""
        binding = require_binding(self)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            default = binding.normalize_version_binding(None, repo_root=repo)
            self.assertTrue(default["ok"], default)
            for key, value in self.fixtures["default_expected"].items():
                self.assertEqual(default["binding"][key], value)
            descriptor = build_trusted_descriptor(repo)
            explicit = binding.normalize_version_binding(descriptor, repo_root=repo)
            self.assertTrue(explicit["ok"], explicit)
            for key, value in self.fixtures["explicit_expected"].items():
                self.assertEqual(explicit["binding"][key], value)
            self.assertEqual(explicit["binding"]["contract_sha256"], descriptor["contract_sha256"])
            self.assertEqual(explicit["binding"]["contract_revision"], 2)

    def test_public_archive_path_uses_release_not_artifact(self) -> None:
        """ASSERT-V235-004: archive segment is contract-bound release_version."""
        binding = require_binding(self)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            descriptor = build_trusted_descriptor(repo)
            normalized = binding.normalize_version_binding(descriptor, repo_root=repo)
            self.assertTrue(normalized["ok"], normalized)
            result = binding.public_archive_path(
                repo,
                normalized["binding"],
                delivery_id="DELIVERY-V235-001",
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                result["archive_ref"], "docs/archive/V2.35/DELIVERY-V235-001"
            )
            self.assertNotIn("run2", result["archive_ref"])
            self.assertFalse((repo / "docs").exists(), "path calculation must not mutate")

    def test_invalid_bindings_and_paths_are_zero_mutation(self) -> None:
        """ASSERT-V235-004: mixed versions and path injection fail closed."""
        binding = require_binding(self)
        for fixture in self.fixtures["invalid_overlays"]:
            with self.subTest(case=fixture["case_id"]), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)
                descriptor = build_trusted_descriptor(repo)
                before = tree_digest(repo)
                if "delivery_id" in fixture:
                    normalized = binding.normalize_version_binding(descriptor, repo_root=repo)
                    self.assertTrue(normalized["ok"], normalized)
                    result = binding.public_archive_path(
                        repo,
                        normalized["binding"],
                        delivery_id=fixture["delivery_id"],
                    )
                else:
                    descriptor.update(copy.deepcopy(fixture.get("patch", {})))
                    result = binding.normalize_version_binding(descriptor, repo_root=repo)
                assert_binding_rejection(self, result, fixture["error_code"])
                self.assertEqual(tree_digest(repo), before, fixture["case_id"])

    def test_review_body_is_current_independent_and_contract_bound(self) -> None:
        """ASSERT-V235-003/004: review digest alone cannot authorize a descriptor."""
        binding = require_binding(self)
        review_cases = (
            (
                "artifact-ref",
                {"artifact_ref": "spec/other-contract.md"},
                "E_V235_VERSION_BINDING_REVIEW",
            ),
            (
                "artifact-hash",
                {"artifact_sha256": "0" * 64},
                "E_V235_VERSION_BINDING_REVIEW",
            ),
            (
                "contract-hash",
                {"contract_sha256": "0" * 64},
                "E_V235_VERSION_BINDING_REVIEW",
            ),
            (
                "revision",
                {"contract_revision": 1},
                "E_V235_VERSION_BINDING_REVIEW",
            ),
            (
                "self-review",
                {"validator_run_id": "RUN-V235-ARCH-OWNER-TEST"},
                "E_V235_VERSION_BINDING_INDEPENDENCE",
            ),
            (
                "stale",
                {"current": False},
                "E_V235_VERSION_BINDING_REVIEW",
            ),
            (
                "decision",
                {"decision": "changes_requested"},
                "E_V235_VERSION_BINDING_REVIEW",
            ),
            (
                "state",
                {"state": "failed"},
                "E_V235_VERSION_BINDING_REVIEW",
            ),
        )
        for name, patch, code in review_cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)
                descriptor = build_trusted_descriptor(repo)
                rewrite_review(repo, descriptor, patch)
                before = tree_digest(repo)
                result = binding.normalize_version_binding(descriptor, repo_root=repo)
                assert_binding_rejection(self, result, code)
                self.assertEqual(tree_digest(repo), before)

    def test_contract_semantic_mutation_is_rejected_even_when_all_hashes_rebind(self) -> None:
        """ASSERT-V235-003/004: current bytes must still be the frozen 36-row contract."""
        binding = require_binding(self)
        original = canonical_delta_contract()
        mutations = (
            (
                "required-false",
                original.replace(
                    "且不进入 index commit package | true",
                    "且不进入 index commit package | false",
                    1,
                ),
                2,
            ),
            (
                "count-35",
                original.replace("required_assertion_count: 36", "required_assertion_count: 35", 1),
                2,
            ),
            (
                "missing-row",
                "\n".join(
                    line for line in original.splitlines() if "ASSERT-V235-036" not in line
                )
                + "\n",
                2,
            ),
            (
                "revision-3",
                original.replace("contract_revision: 2", "contract_revision: 3", 1),
                3,
            ),
        )
        for name, text, revision in mutations:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)
                descriptor = build_trusted_descriptor(repo)
                rebind_contract_and_review(repo, descriptor, text, revision=revision)
                before = tree_digest(repo)
                result = binding.normalize_version_binding(descriptor, repo_root=repo)
                assert_binding_rejection(
                    self, result, "E_V235_VERSION_BINDING_CONTRACT_SEMANTICS"
                )
                self.assertEqual(tree_digest(repo), before)

    def test_review_symlink_is_rejected_without_repo_or_target_mutation(self) -> None:
        """ASSERT-V235-004."""
        binding = require_binding(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            outside = root / "outside"
            repo.mkdir()
            outside.mkdir()
            descriptor = build_trusted_descriptor(repo)
            original_review = repo / descriptor["review_ref"]
            outside_review = outside / "review.json"
            outside_review.write_bytes(original_review.read_bytes())
            linked_review = repo / "reviews" / "linked-review.json"
            linked_review.symlink_to(outside_review)
            descriptor["review_ref"] = "reviews/linked-review.json"
            descriptor["review_sha256"] = sha256_path(outside_review)
            repo_before = tree_digest(repo)
            outside_before = tree_digest(outside)
            result = binding.normalize_version_binding(descriptor, repo_root=repo)
            assert_binding_rejection(
                self, result, "E_V235_VERSION_BINDING_PATH"
            )
            self.assertEqual(tree_digest(repo), repo_before)
            self.assertEqual(tree_digest(outside), outside_before)

    def test_symlink_contract_and_archive_parent_are_rejected(self) -> None:
        """ASSERT-V235-004: no symlink-based containment bypass."""
        binding = require_binding(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            outside = root / "outside"
            repo.mkdir()
            outside.mkdir()
            descriptor = build_trusted_descriptor(repo)
            real_contract = repo / descriptor["contract_ref"]
            linked_contract = repo / "spec" / "linked-contract.md"
            linked_contract.symlink_to(real_contract)
            linked = copy.deepcopy(descriptor)
            linked["contract_ref"] = "spec/linked-contract.md"
            linked["contract_sha256"] = sha256_path(real_contract)
            before = tree_digest(repo)
            rejected = binding.normalize_version_binding(linked, repo_root=repo)
            assert_binding_rejection(
                self, rejected, "E_V235_VERSION_BINDING_PATH"
            )
            self.assertEqual(tree_digest(repo), before)
            normalized = binding.normalize_version_binding(descriptor, repo_root=repo)
            self.assertTrue(normalized["ok"], normalized)
            (repo / "docs" / "archive").mkdir(parents=True)
            (repo / "docs" / "archive" / "V2.35").symlink_to(outside, target_is_directory=True)
            repo_before = tree_digest(repo)
            outside_before = tree_digest(outside)
            result = binding.public_archive_path(
                repo, normalized["binding"], delivery_id="DELIVERY-V235-SYMLINK"
            )
            assert_binding_rejection(self, result, "E_V235_VERSION_BINDING_PATH")
            self.assertEqual(tree_digest(repo), repo_before)
            self.assertEqual(tree_digest(outside), outside_before)


class V235StateAndArchiveCompatibilityTests(unittest.TestCase):
    def test_v234_default_state_is_unchanged_without_descriptor(self) -> None:
        """ASSERT-V235-002/003."""
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, result = initialize_bundle(self, directory)
            self.assertTrue(result["ok"], result)
            marker = v234.load_state_bundle(state_root)
            self.assertEqual(marker["project_version"], "V2.34")
            self.assertEqual(marker["artifact_version"], "V2.34")
            for byte_field in ("_contract_bytes", "_progress_bytes", "_log_bytes"):
                self.assertNotIn(b"V2.35", marker[byte_field])

    def test_explicit_binding_initializes_and_validates_v235_state(self) -> None:
        """ASSERT-V235-003: state consumes the normalized trusted descriptor."""
        v234 = require_v234(self)
        self.assertIn("version_binding", inspect.signature(v234.initialize_state_bundle).parameters)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            descriptor = build_trusted_descriptor(repo)
            control_contract, ledger_binding, events, checkpoint_bytes = state_binding_inputs(repo)
            state_root = repo / "GoalTeamsWork-V2.35" / "versions" / "V2.35-run2"
            state_root.mkdir(parents=True)
            result = v234.initialize_state_bundle(
                state_root,
                repo_root=repo,
                loop_id="LOOP-V235-TEST",
                contract_path=control_contract,
                ledger_binding=ledger_binding,
                actor_run_id=OWNER_RUN,
                ledger_events=events,
                checkpoint_bytes=checkpoint_bytes,
                version_binding=descriptor,
            )
            self.assertTrue(result["ok"], result)
            marker = v234.load_state_bundle(state_root)
            self.assertEqual(marker["project_version"], "V2.35")
            self.assertEqual(marker["artifact_version"], "V2.35-run2")
            release_version = marker.get(
                "release_version", marker.get("version_binding", {}).get("release_version")
            )
            self.assertEqual(release_version, "V2.35")
            validated = v234.validate_state_bundle(
                state_root,
                repo_root=repo,
                version_binding=marker["version_binding"],
            )
            self.assertTrue(validated["ok"], validated)

    def test_invalid_binding_precedes_state_lock_and_writes_nothing(self) -> None:
        """ASSERT-V235-004: binding failure has zero filesystem mutation."""
        v234 = require_v234(self)
        self.assertIn("version_binding", inspect.signature(v234.initialize_state_bundle).parameters)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            descriptor = build_trusted_descriptor(repo)
            descriptor["release_version"] = "V2.34"
            control_contract, ledger_binding, events, checkpoint_bytes = state_binding_inputs(repo)
            state_root = repo / "state"
            state_root.mkdir()
            before = tree_digest(repo)
            result = v234.initialize_state_bundle(
                state_root,
                repo_root=repo,
                loop_id="LOOP-V235-INVALID",
                contract_path=control_contract,
                ledger_binding=ledger_binding,
                actor_run_id=OWNER_RUN,
                ledger_events=events,
                checkpoint_bytes=checkpoint_bytes,
                version_binding=descriptor,
            )
            assert_binding_rejection(
                self, result, "E_V235_VERSION_BINDING_MISMATCH"
            )
            self.assertEqual(tree_digest(repo), before)

    def test_public_archive_and_manifest_use_explicit_v235_binding(self) -> None:
        """ASSERT-V235-004: runtime archive path and manifest share one binding."""
        v234 = require_v234(self)
        self.assertIn("version_binding", inspect.signature(v234.create_public_archive).parameters)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            descriptor = build_trusted_descriptor(repo)
            (repo / "public").mkdir()
            (repo / "public" / "release.md").write_text("# V2.35\n", encoding="utf-8")
            result = v234.create_public_archive(
                repo,
                delivery_id="DELIVERY-V235-ARCHIVE",
                descriptors=v235_archive_descriptors(),
                completion=archive_completion(),
                version_binding=descriptor,
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                result["archive_ref"], "docs/archive/V2.35/DELIVERY-V235-ARCHIVE"
            )
            manifest = json.loads(
                (
                    repo
                    / "docs"
                    / "archive"
                    / "V2.35"
                    / "DELIVERY-V235-ARCHIVE"
                    / "manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["release_version"], "V2.35")
            self.assertEqual(manifest["artifact_version"], "V2.35-run2")

    def test_archive_api_has_no_caller_supplied_path_and_closure_accepts_binding(self) -> None:
        """ASSERT-V235-004/036: closure and archive share descriptor input."""
        v234 = require_v234(self)
        create_parameters = inspect.signature(v234.create_public_archive).parameters
        self.assertIn("version_binding", create_parameters)
        self.assertNotIn("archive_path", create_parameters)
        self.assertNotIn("archive_root", create_parameters)
        closure = load_closure()
        closure_parameters = inspect.signature(closure.build_completion_snapshot).parameters
        self.assertIn("version_binding", closure_parameters)


if __name__ == "__main__":
    unittest.main()
