"""V2.34 public archive, publish isolation and release-closure TDD tests."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v23.common import ROOT
from tests.v23.test_v234_reset_delivery import (
    complete_delivery_inputs,
    strict_completion_fixture,
)
from tests.v23.test_v234_state_loop import (
    FIXED_HASH_A,
    FIXED_HASH_B,
    OWNER_RUN,
    VALIDATOR_RUN,
    assert_error_code,
    canonical_hash,
    initialize_bundle,
    marker,
    require_v234,
)


ROADMAP_BYTES = b"# V2.34 roadmap fixture\n\n- immutable input\n"
ROADMAP_SHA256 = hashlib.sha256(ROADMAP_BYTES).hexdigest()


class InjectedDeliveryCrash(RuntimeError):
    pass


def archive_tree_hash(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                }
            )
    payload = json.dumps(
        entries, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=check
    )


def init_git_repo(repo: Path) -> None:
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "v234-tests@example.invalid")
    git(repo, "config", "user.name", "V2.34 Tests")


def archive_descriptor(source_refs: tuple[str, ...] = ("public/guide.md", "public/release.md")) -> list[dict[str, Any]]:
    descriptors = []
    for index, source_ref in enumerate(source_refs, 1):
        descriptors.append(
            {
                "source_artifact_id": f"ART-V234-PUBLIC-{index:02d}",
                "source_ref": source_ref,
                "archive_ref": Path(source_ref).name,
                "publication_state": "completed",
                "visibility": "public",
                "artifact_version": "V2.34",
                "validator_run_id": VALIDATOR_RUN,
                "contract_revision": 2,
                "classification": "public_completion_doc",
                "accepted": True,
            }
        )
    return descriptors


def archive_completion() -> dict[str, Any]:
    return {
        "run_outcome_candidate": "achieved",
        "completion_audit": {
            "state": "passed",
            "validator_run_id": "RUN-COMPLETION-AUDITOR-V234-01",
            "ledger_revision": 50,
            "sha256": FIXED_HASH_A,
        },
        "contract_revision": 2,
    }


class V234ArchiveTests(unittest.TestCase):
    def test_archive_eligibility_requires_audit_and_acceptance(self) -> None:
        """ASSERT-V234-045"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            descriptors = archive_descriptor()
            _, proof, context, completion = strict_completion_fixture(
                self, repo, descriptors
            )
            eligible = v234.validate_archive_eligibility(
                descriptors,
                completion,
                repo_root=repo,
                completion_proof=proof,
                source_context=context,
            )
            self.assertTrue(eligible["ok"], eligible)
            self.assertEqual(
                eligible["artifact_ids"],
                ["ART-V234-PUBLIC-01", "ART-V234-PUBLIC-02"],
            )
            forged_proof = copy.deepcopy(proof)
            forged_proof["reset"]["receipt_sha256"] = "0" * 64
            forged_proof["proof_digest"] = canonical_hash(
                {
                    key: value
                    for key, value in forged_proof.items()
                    if key != "proof_digest"
                }
            )
            self.assertFalse(
                v234.validate_archive_eligibility(
                    descriptors,
                    completion,
                    repo_root=repo,
                    completion_proof=forged_proof,
                    source_context=context,
                )["ok"]
            )
            audit_path = Path(context["audit_path"])
            audit_bytes = audit_path.read_bytes()
            audit_path.write_text('{"state":"forged"}\n', encoding="utf-8")
            self.assertFalse(
                v234.validate_archive_eligibility(
                    descriptors,
                    completion,
                    repo_root=repo,
                    completion_proof=proof,
                    source_context=context,
                )["ok"]
            )
            audit_path.write_bytes(audit_bytes)
            failed_audit = copy.deepcopy(completion)
            failed_audit["completion_audit"]["state"] = "failed"
            self.assertFalse(
                v234.validate_archive_eligibility(
                    descriptors,
                    failed_audit,
                    repo_root=repo,
                    completion_proof=proof,
                    source_context=context,
                )["ok"]
            )
            unaccepted = archive_descriptor()
            unaccepted[1]["accepted"] = False
            result = v234.validate_archive_eligibility(
                unaccepted,
                completion,
                repo_root=repo,
                completion_proof=proof,
                source_context=context,
            )
            self.assertFalse(result["ok"], result)
            self.assertIn("ART-V234-PUBLIC-02", result["ineligible_artifact_ids"])
            invalid_descriptors = {
                "reserved_manifest": ("archive_ref", "manifest.json"),
                "process_source": (
                    "source_ref",
                    "GoalTeamsWork-V2.34/versions/V2.34/reviews/internal.md",
                ),
                "absolute_home_source": (
                    "source_ref",
                    "/Users/" + "example/private/completion.md",
                ),
                "process_class": ("classification", "completion_audit"),
            }
            for case, (field, value) in invalid_descriptors.items():
                candidate = archive_descriptor()
                candidate[0][field] = value
                invalid = v234.validate_archive_eligibility(
                    candidate,
                    completion,
                    repo_root=repo,
                    completion_proof=proof,
                    source_context=context,
                )
                with self.subTest(case=case):
                    self.assertFalse(invalid["ok"], invalid)

    def test_archive_atomicity_manifest_and_idempotency(self) -> None:
        """ASSERT-V234-046"""
        v234 = require_v234(self)
        # Delivery-gate authenticity is covered by ASSERT-V234-029/052.  This
        # test isolates the archive/state transaction crash matrix so it can
        # inject a fault after the gate would already have passed.
        original_gate = v234.evaluate_delivery_gate
        self.addCleanup(setattr, v234, "evaluate_delivery_gate", original_gate)
        v234.evaluate_delivery_gate = lambda *args, **kwargs: {
            "ok": True,
            "error_code": None,
            "gaps": [],
            "run_outcome_candidate": "achieved",
        }
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "public").mkdir()
            (repo / "public" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            (repo / "public" / "release.md").write_text("# V2.34\n", encoding="utf-8")
            first = v234.create_public_archive(
                repo,
                delivery_id="DELIVERY-V234-001",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
            )
            self.assertTrue(first["ok"], first)
            archive_root = repo / "docs" / "archive" / "V2.34" / "DELIVERY-V234-001"
            self.assertTrue(archive_root.is_dir())
            self.assertFalse((archive_root.parent / ".DELIVERY-V234-001.tmp").exists())
            manifest_bytes = (archive_root / "manifest.json").read_bytes()
            manifest = json.loads(manifest_bytes)
            self.assertEqual(len(manifest["artifacts"]), 2)
            for item in manifest["artifacts"]:
                for field in (
                    "source_artifact_id", "public_relative_path", "source_sha256",
                    "public_sha256", "classification", "validator_run_id",
                    "contract_revision", "size", "media_type",
                ):
                    self.assertIn(field, item)
            replay = v234.create_public_archive(
                repo,
                delivery_id="DELIVERY-V234-001",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
            )
            self.assertTrue(replay["ok"], replay)
            self.assertTrue(replay["idempotent"])
            self.assertEqual((archive_root / "manifest.json").read_bytes(), manifest_bytes)
            (repo / "public" / "guide.md").write_text("changed\n", encoding="utf-8")
            conflict = v234.create_public_archive(
                repo,
                delivery_id="DELIVERY-V234-001",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
            )
            assert_error_code(self, conflict, "E_V234_ARCHIVE_CONFLICT")

        with self.subTest(case="temp_symlink"), tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "public").mkdir()
            (repo / "public" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            (repo / "public" / "release.md").write_text("# V2.34\n", encoding="utf-8")
            parent = repo / "docs" / "archive" / "V2.34"
            parent.mkdir(parents=True)
            outside = repo / "outside-archive"
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            (parent / ".DELIVERY-V234-SYMLINK.tmp").symlink_to(
                outside, target_is_directory=True
            )
            symlinked = v234.create_public_archive(
                repo,
                delivery_id="DELIVERY-V234-SYMLINK",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
            )
            self.assertFalse(symlinked["ok"], symlinked)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")
            self.assertFalse((parent / "DELIVERY-V234-SYMLINK").exists())

        crash_points_before_marker = (
            "archive_renamed",
            "docs_parent_fsynced",
            "log_replaced",
            "progress_replaced",
        )
        for crash_point in crash_points_before_marker:
            with self.subTest(crash_point=crash_point), tempfile.TemporaryDirectory() as directory:
                v234, repo, state_root, _ = initialize_bundle(
                    self, directory, iteration=11, phase="verify"
                )
                (repo / "public").mkdir()
                (repo / "public" / "guide.md").write_text("# Guide\n", encoding="utf-8")
                (repo / "public" / "release.md").write_text("# V2.34\n", encoding="utf-8")
                before = marker(state_root)
                seen: list[str] = []

                def fault_injector(point: str) -> None:
                    seen.append(point)
                    if point == crash_point:
                        raise InjectedDeliveryCrash(point)

                with self.assertRaises(InjectedDeliveryCrash):
                    v234.deliver(
                        state_root,
                        repo_root=repo,
                        delivery_id="DELIVERY-V234-CRASH",
                        transaction_id="TXN-V234-DELIVERY-CRASH",
                        descriptors=archive_descriptor(),
                        completion=archive_completion(),
                        delivery_inputs=complete_delivery_inputs(),
                        expected_bundle_revision=before["bundle_revision"],
                        expected_bundle_digest=before["bundle_digest"],
                        actor_run_id=OWNER_RUN,
                        fault_injector=fault_injector,
                    )
                self.assertIn("archive_renamed", seen)
                archive_root = repo / "docs" / "archive" / "V2.34" / "DELIVERY-V234-CRASH"
                self.assertTrue(archive_root.is_dir(), "archive rename must precede state marker")
                archive_hash_before = archive_tree_hash(archive_root)
                persisted = marker(state_root)
                self.assertNotEqual(persisted["loop"]["run_outcome"], "achieved")
                self.assertEqual(persisted["bundle_revision"], before["bundle_revision"])
                inspected = v234.recover_delivery(
                    state_root,
                    repo_root=repo,
                    delivery_id="DELIVERY-V234-CRASH",
                    mode="inspect",
                )
                self.assertEqual(inspected["state"], "recoverable_pending", inspected)
                self.assertFalse(inspected["achieved"])
                rolled = v234.recover_delivery(
                    state_root,
                    repo_root=repo,
                    delivery_id="DELIVERY-V234-CRASH",
                    mode="auto",
                    descriptors=archive_descriptor(),
                    completion=archive_completion(),
                    delivery_inputs=complete_delivery_inputs(),
                    actor_run_id=OWNER_RUN,
                )
                self.assertTrue(rolled["ok"], rolled)
                self.assertTrue(rolled["journal_verified"])
                self.assertTrue(rolled["achieved"])
                self.assertEqual(archive_tree_hash(archive_root), archive_hash_before)
                self.assertEqual(marker(state_root)["loop"]["run_outcome"], "achieved")

        with self.subTest(crash_point="feature_marker_replaced"), tempfile.TemporaryDirectory() as directory:
            v234, repo, state_root, _ = initialize_bundle(
                self, directory, iteration=11, phase="verify"
            )
            (repo / "public").mkdir()
            (repo / "public" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            (repo / "public" / "release.md").write_text("# V2.34\n", encoding="utf-8")
            before = marker(state_root)

            def crash_after_marker(point: str) -> None:
                if point == "feature_marker_replaced":
                    raise InjectedDeliveryCrash(point)

            with self.assertRaises(InjectedDeliveryCrash):
                v234.deliver(
                    state_root,
                    repo_root=repo,
                    delivery_id="DELIVERY-V234-MARKER",
                    transaction_id="TXN-V234-DELIVERY-MARKER",
                    descriptors=archive_descriptor(),
                    completion=archive_completion(),
                    delivery_inputs=complete_delivery_inputs(),
                    expected_bundle_revision=before["bundle_revision"],
                    expected_bundle_digest=before["bundle_digest"],
                    actor_run_id=OWNER_RUN,
                    fault_injector=crash_after_marker,
                )
            self.assertEqual(marker(state_root)["loop"]["run_outcome"], "achieved")
            finalized = v234.recover_delivery(
                state_root,
                repo_root=repo,
                delivery_id="DELIVERY-V234-MARKER",
                mode="auto",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
                delivery_inputs=complete_delivery_inputs(),
                actor_run_id=OWNER_RUN,
            )
            self.assertTrue(finalized["ok"], finalized)
            self.assertTrue(finalized["idempotent"])
            self.assertTrue(finalized["achieved"])

        with self.subTest(case="orphan_without_journal"), tempfile.TemporaryDirectory() as directory:
            v234, repo, state_root, _ = initialize_bundle(
                self, directory, iteration=11, phase="verify"
            )
            orphan = repo / "docs" / "archive" / "V2.34" / "DELIVERY-V234-ORPHAN"
            orphan.mkdir(parents=True)
            (orphan / "manifest.json").write_text("{}\n", encoding="utf-8")
            result = v234.recover_delivery(
                state_root,
                repo_root=repo,
                delivery_id="DELIVERY-V234-ORPHAN",
                mode="auto",
            )
            self.assertFalse(result["ok"], result)
            self.assertEqual(result["state"], "reconcile_required")
            self.assertFalse(result["achieved"])
            self.assertEqual(marker(state_root)["loop"]["run_outcome"], "partial")
            self.assertTrue(orphan.is_dir(), "unknown orphan bytes must not be deleted or trusted")

        with self.subTest(case="successful_order_and_transaction_replay"), tempfile.TemporaryDirectory() as directory:
            v234, repo, state_root, _ = initialize_bundle(
                self, directory, iteration=11, phase="verify"
            )
            (repo / "public").mkdir()
            (repo / "public" / "guide.md").write_text("# Guide\n", encoding="utf-8")
            (repo / "public" / "release.md").write_text("# V2.34\n", encoding="utf-8")
            before = marker(state_root)
            order: list[str] = []
            delivered = v234.deliver(
                state_root,
                repo_root=repo,
                delivery_id="DELIVERY-V234-ORDER",
                transaction_id="TXN-V234-DELIVERY-ORDER",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
                delivery_inputs=complete_delivery_inputs(),
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                actor_run_id=OWNER_RUN,
                fault_injector=order.append,
            )
            self.assertTrue(delivered["ok"], delivered)
            required_order = [
                "archive_renamed", "docs_parent_fsynced", "log_replaced",
                "progress_replaced", "feature_marker_replaced",
            ]
            self.assertEqual(
                [order.index(point) for point in required_order],
                sorted(order.index(point) for point in required_order),
            )
            file_replace_points = [
                point
                for point in order
                if point in {"log_replaced", "progress_replaced", "feature_marker_replaced"}
            ]
            self.assertEqual(file_replace_points[-1], "feature_marker_replaced")
            replay = v234.deliver(
                state_root,
                repo_root=repo,
                delivery_id="DELIVERY-V234-ORDER",
                transaction_id="TXN-V234-DELIVERY-ORDER",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
                delivery_inputs=complete_delivery_inputs(),
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                actor_run_id=OWNER_RUN,
            )
            self.assertTrue(replay["ok"], replay)
            self.assertTrue(replay["idempotent"])
            self.assertEqual(replay["bundle_digest"], delivered["bundle_digest"])
            archive_root = repo / "docs" / "archive" / "V2.34" / "DELIVERY-V234-ORDER"
            archive_before_conflict = archive_tree_hash(archive_root)
            (repo / "public" / "guide.md").write_text("conflicting tree\n", encoding="utf-8")
            conflicting_replay = v234.deliver(
                state_root,
                repo_root=repo,
                delivery_id="DELIVERY-V234-ORDER",
                transaction_id="TXN-V234-DELIVERY-ORDER",
                descriptors=archive_descriptor(),
                completion=archive_completion(),
                delivery_inputs=complete_delivery_inputs(),
                expected_bundle_revision=before["bundle_revision"],
                expected_bundle_digest=before["bundle_digest"],
                actor_run_id=OWNER_RUN,
            )
            assert_error_code(self, conflicting_replay, "E_V234_ARCHIVE_CONFLICT")
            self.assertEqual(archive_tree_hash(archive_root), archive_before_conflict)

    def test_publish_guard_checks_archive_index_and_commit(self) -> None:
        """ASSERT-V234-047"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_git_repo(repo)
            (repo / "docs" / "archive" / "V2.34" / "DELIVERY").mkdir(parents=True)
            (repo / "docs" / "archive" / "V2.34" / "DELIVERY" / "manifest.json").write_text("{}\n", encoding="utf-8")
            process = repo / "GoalTeamsWork-V2.34" / "versions" / "V2.34" / "evidence" / "evidence.jsonl"
            process.parent.mkdir(parents=True)
            process.write_text("{}\n", encoding="utf-8")
            secret = repo / "docs" / "archive" / "V2.34" / "DELIVERY" / "secret.txt"
            secret.write_text(
                "api_" + "key=" + "sk-" + "abcdefghijklmnop1234\n",
                encoding="utf-8",
            )
            git(repo, "add", "docs/archive/V2.34/DELIVERY/manifest.json")
            clean = v234.publish_guard(repo, mode="index")
            self.assertTrue(clean["ok"], clean)
            git(repo, "add", "-f", process.relative_to(repo).as_posix(), secret.relative_to(repo).as_posix())
            staged = v234.publish_guard(repo, mode="index")
            self.assertFalse(staged["ok"], staged)
            self.assertIn("GoalTeamsWork-V2.34/versions/V2.34/evidence/evidence.jsonl", staged["denied_paths"])
            self.assertIn("docs/archive/V2.34/DELIVERY/secret.txt", staged["denied_paths"])
            git(repo, "commit", "-qm", "unsafe candidate")
            committed = v234.publish_guard(repo, mode="commit", commit="HEAD")
            self.assertFalse(committed["ok"], committed)

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_git_repo(repo)
            historical = (
                repo
                / "GoalTeamsWork-V2.3"
                / "versions"
                / "V2.3"
                / "evidence"
                / "historical.jsonl"
            )
            historical.parent.mkdir(parents=True)
            historical.write_text('{"historical":true}\n', encoding="utf-8")
            (repo / "README.md").write_text("baseline\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "historical baseline")
            baseline = git(repo, "rev-parse", "HEAD").stdout.strip()

            archive = repo / "docs" / "archive" / "V2.34" / "DELIVERY"
            archive.mkdir(parents=True)
            (archive / "manifest.json").write_text('{"version":"V2.34"}\n', encoding="utf-8")
            git(repo, "add", "docs/archive/V2.34/DELIVERY/manifest.json")
            git(repo, "commit", "-qm", "safe public archive")
            safe_candidate = git(repo, "rev-parse", "HEAD").stdout.strip()
            grandfathered = v234.publish_guard(
                repo,
                mode="commit",
                commit=safe_candidate,
                baseline_commit=baseline,
            )
            self.assertTrue(grandfathered["ok"], grandfathered)
            self.assertNotIn(
                historical.relative_to(repo).as_posix(),
                grandfathered["checked_paths"],
                "unchanged historical process artifacts are outside the candidate delta",
            )

            historical.write_text('{"historical":"modified"}\n', encoding="utf-8")
            git(repo, "add", "-f", historical.relative_to(repo).as_posix())
            git(repo, "commit", "-qm", "modify historical process artifact")
            modified_candidate = git(repo, "rev-parse", "HEAD").stdout.strip()
            modified = v234.publish_guard(
                repo,
                mode="commit",
                commit=modified_candidate,
                baseline_commit=safe_candidate,
            )
            self.assertFalse(modified["ok"], modified)
            self.assertIn(historical.relative_to(repo).as_posix(), modified["denied_paths"])

            newly_added = (
                repo
                / "GoalTeamsWork-V2.34"
                / "versions"
                / "V2.34"
                / "reviews"
                / "new-review.md"
            )
            newly_added.parent.mkdir(parents=True)
            newly_added.write_text("private review\n", encoding="utf-8")
            git(repo, "add", "-f", newly_added.relative_to(repo).as_posix())
            git(repo, "commit", "-qm", "add process artifact")
            added_candidate = git(repo, "rev-parse", "HEAD").stdout.strip()
            added = v234.publish_guard(
                repo,
                mode="commit",
                commit=added_candidate,
                baseline_commit=modified_candidate,
            )
            self.assertFalse(added["ok"], added)
            self.assertIn(newly_added.relative_to(repo).as_posix(), added["denied_paths"])

    def test_sanitizer_preserves_private_provenance(self) -> None:
        """ASSERT-V234-048"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "log.md"
            public = root / "public.md"
            original = b"tool_call spawn_agent RUN-INTERNAL-001 transport_handle=h-123\n"
            private.write_bytes(original)
            before_hash = hashlib.sha256(private.read_bytes()).hexdigest()
            result = v234.sanitize_public_copy(private, public)
            self.assertTrue(result["ok"], result)
            self.assertEqual(private.read_bytes(), original)
            self.assertEqual(hashlib.sha256(private.read_bytes()).hexdigest(), before_hash)
            self.assertNotEqual(public.read_bytes(), original)
            for process_name in ("ledger", "evidence", "review", "audit", "provenance"):
                self.assertIn(process_name, v234.PRESERVED_PRIVATE_ARTIFACT_CLASSES)

    def test_public_render_noise_positive_and_negative_fixtures(self) -> None:
        """ASSERT-V234-049"""
        v234 = require_v234(self)
        private_home = "/Users/" + "example/private"
        internal_task = "/ro" + "ot/v234_dev"
        source = (
            "Current release is V2.34. V2.33 compatibility remains documented.\n"
            "Historical version V2.3 introduced the machine core.\n"
            f"spawn_agent {internal_task} RUN-INTERNAL-001 transport_handle=h-123\n"
            "tool_call={\"name\":\"internal\"}\n"
            f"private source {private_home}/completion.md\n"
        )
        public = v234.sanitize_public_text(source)
        self.assertIn("Current release is V2.34", public)
        self.assertIn("V2.33 compatibility", public)
        self.assertIn("Historical version V2.3", public)
        for noise in (
            "spawn_agent", internal_task, "RUN-INTERNAL-001",
            "transport_handle", "tool_call", private_home,
        ):
            self.assertNotIn(noise, public)


class V234ReleaseTests(unittest.TestCase):
    def test_roadmap_and_dirty_worktree_preserved(self) -> None:
        """ASSERT-V234-050"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_git_repo(repo)
            roadmap = repo / "docs" / "后续版本规划 V3.3-3.5.md"
            roadmap.parent.mkdir(parents=True)
            roadmap.write_bytes(ROADMAP_BYTES)
            self.assertEqual(hashlib.sha256(roadmap.read_bytes()).hexdigest(), ROADMAP_SHA256)
            (repo / "user.txt").write_text("baseline\n", encoding="utf-8")
            (repo / "implementation.py").write_text("old\n", encoding="utf-8")
            git(repo, "add", "user.txt", "implementation.py")
            git(repo, "commit", "-qm", "baseline")
            (repo / "user.txt").write_text("user dirty edit\n", encoding="utf-8")
            guard = v234.capture_worktree_guard(repo, protected_paths=["user.txt"])
            (repo / "implementation.py").write_text("new\n", encoding="utf-8")
            preserved = v234.validate_worktree_guard(repo, guard, allowed_paths=["implementation.py"])
            self.assertTrue(preserved["ok"], preserved)
            (repo / "user.txt").write_text("overwritten\n", encoding="utf-8")
            overwritten = v234.validate_worktree_guard(repo, guard, allowed_paths=["implementation.py"])
            self.assertFalse(overwritten["ok"], overwritten)
            self.assertIn("user.txt", overwritten["changed_protected_paths"])

    def test_v234_version_surface_sync(self) -> None:
        """ASSERT-V234-051"""
        v234 = require_v234(self)
        current_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        result = v234.validate_version_sync(ROOT, expected_version=current_version)
        self.assertTrue(result["ok"], result)
        expected_surfaces = {
            "VERSION", "SKILL.md", "README.md", "README.en.md",
            "scripts/v23/goalteams_v23.py", "agents/openai.yaml",
        }
        self.assertTrue(expected_surfaces.issubset(set(result["checked_paths"])))
        self.assertEqual(result["stale_current_version_markers"], [])

    def test_full_v234_release_closure(self) -> None:
        """ASSERT-V234-052"""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            descriptors = archive_descriptor()
            _, proof, context, _ = strict_completion_fixture(
                self, Path(directory), descriptors
            )
            self.assertNotIn("version_binding", context)
            legacy_sync = v234.validate_version_sync(
                Path(directory), expected_version="V2.34"
            )
            self.assertTrue(legacy_sync["ok"], legacy_sync)
            self.assertEqual(legacy_sync["stale_current_version_markers"], [])
            valid = v234.validate_release_closure(
                proof, source_context=context
            )
            self.assertTrue(valid["ok"], valid)

            stale = copy.deepcopy(proof)
            stale["evidence_ids"] = ["EVD-V234-STALE"]
            stale["proof_digest"] = canonical_hash(
                {key: value for key, value in stale.items() if key != "proof_digest"}
            )
            self.assertFalse(
                v234.validate_release_closure(stale, source_context=context)["ok"]
            )

            self_review_context = copy.deepcopy(context)
            self_review_context["audit_record"]["auditor_run_id"] = self_review_context[
                "audit_record"
            ]["author_run_id"]
            self.assertFalse(
                v234.validate_release_closure(
                    proof, source_context=self_review_context
                )["ok"]
            )

            report_record = next(iter(context["evidence_registry"]["records"].values()))
            report_path = (
                Path(context["evidence_registry"]["evidence_root"])
                / report_record["artifact_ref"]
            )
            report_path.write_text('{"tampered":true}\n', encoding="utf-8")
            tampered = v234.validate_release_closure(
                proof, source_context=context
            )
            self.assertFalse(tampered["ok"], tampered)


if __name__ == "__main__":
    unittest.main()
