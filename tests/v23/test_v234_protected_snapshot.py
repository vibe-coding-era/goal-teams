#!/usr/bin/env python3
"""Security regressions for the V2.34 protected candidate snapshot."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.v23.test_v234_reset_delivery import (
    canonical_hash,
    completion_descriptors,
    require_v234,
    strict_completion_fixture,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repo, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def init_candidate_repo(root: Path) -> str:
    git(root, "init", "-q")
    git(root, "config", "user.email", "tests@example.invalid")
    git(root, "config", "user.name", "Tests")
    files = {
        "VERSION": "V2.33\n",
        "scripts/v23/v234_state.py": "# V2.33 runtime\n",
        "scripts/v23/goalteams_v23.py": 'PRODUCT_VERSION = "V2.33"\n',
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return git(root, "rev-parse", "HEAD")


def apply_v234_candidate(root: Path) -> None:
    (root / "VERSION").write_text("V2.34\n", encoding="utf-8")
    (root / "scripts/v23/v234_state.py").write_text(
        "# V2.34 protected snapshot runtime\n", encoding="utf-8"
    )
    (root / "scripts/v23/goalteams_v23.py").write_text(
        'PRODUCT_VERSION = "V2.34"\n', encoding="utf-8"
    )
    test_path = root / "tests/v23/test_v234_snapshot.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_snapshot():\n    assert True\n", encoding="utf-8")


def resign(record: dict[str, object]) -> dict[str, object]:
    core = {key: value for key, value in record.items() if key != "record_sha256"}
    return {**core, "record_sha256": canonical_hash(core)}


class V234ProtectedSnapshotTests(unittest.TestCase):
    def test_isolated_snapshot_proves_current_product_delta_without_repo_pollution(self) -> None:
        """Security extension of ASSERT-V234-029."""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = init_candidate_repo(root)
            apply_v234_candidate(root)
            receipt_path = root / "candidate-snapshot.json"
            before = {
                "head": git(root, "rev-parse", "HEAD"),
                "branch": git(root, "symbolic-ref", "HEAD"),
                "index": hashlib.sha256((root / ".git/index").read_bytes()).hexdigest(),
                "refs": git(root, "show-ref", "--head"),
                "cached": git(root, "diff", "--cached", "--binary"),
            }

            result = v234.create_protected_candidate_snapshot(
                root, baseline_commit=baseline, receipt_path=receipt_path
            )
            self.assertTrue(result["ok"], result)
            receipt = result["receipt"]
            self.assertEqual(receipt["mode"], "isolated_index_tree")
            self.assertNotEqual(receipt["baseline_tree_oid"], receipt["candidate_tree_oid"])
            self.assertEqual(
                set(receipt["changed_paths"]),
                {
                    "VERSION",
                    "scripts/v23/goalteams_v23.py",
                    "scripts/v23/v234_state.py",
                    "tests/v23/test_v234_snapshot.py",
                },
            )
            self.assertTrue(receipt_path.is_file())
            self.assertTrue(
                v234.validate_protected_candidate_snapshot(root, receipt)["ok"]
            )
            after = {
                "head": git(root, "rev-parse", "HEAD"),
                "branch": git(root, "symbolic-ref", "HEAD"),
                "index": hashlib.sha256((root / ".git/index").read_bytes()).hexdigest(),
                "refs": git(root, "show-ref", "--head"),
                "cached": git(root, "diff", "--cached", "--binary"),
            }
            self.assertEqual(after, before)

            # Codex desktop creates these volatile checkpoint refs while the
            # turn is still running.  They must not invalidate an otherwise
            # byte-identical release candidate.
            git(
                root,
                "update-ref",
                "refs/codex/turn-diffs/checkpoints/test/snapshot",
                git(root, "rev-parse", "HEAD"),
            )
            self.assertTrue(
                v234.validate_protected_candidate_snapshot(root, receipt)["ok"]
            )

            # Conventional publish-bearing refs remain protected.
            git(root, "update-ref", "refs/tags/v234-test", git(root, "rev-parse", "HEAD"))
            ref_stale = v234.validate_protected_candidate_snapshot(root, receipt)
            self.assertFalse(ref_stale["ok"], ref_stale)
            git(root, "update-ref", "-d", "refs/tags/v234-test")
            self.assertTrue(
                v234.validate_protected_candidate_snapshot(root, receipt)["ok"]
            )

            (root / "scripts/v23/v234_state.py").write_text(
                "# tampered after snapshot\n", encoding="utf-8"
            )
            stale = v234.validate_protected_candidate_snapshot(root, receipt)
            self.assertFalse(stale["ok"], stale)

    def test_publish_guard_rejects_empty_commit_delta_and_tampered_snapshot(self) -> None:
        """Security extension of ASSERT-V234-047."""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = init_candidate_repo(root)
            empty = v234.publish_guard(
                root, mode="commit", commit=baseline, baseline_commit=baseline
            )
            self.assertFalse(empty["ok"], empty)
            self.assertEqual(empty["error_code"], "E_V234_PUBLISH_EMPTY_DELTA")

            apply_v234_candidate(root)
            snapshot = v234.create_protected_candidate_snapshot(
                root, baseline_commit=baseline
            )
            self.assertTrue(snapshot["ok"], snapshot)
            guarded = v234.publish_guard(
                root, mode="snapshot", snapshot_receipt=snapshot["receipt"]
            )
            self.assertTrue(guarded["ok"], guarded)
            forged = copy.deepcopy(snapshot["receipt"])
            forged["candidate_tree_oid"] = "0" * len(forged["candidate_tree_oid"])
            forged["receipt_sha256"] = canonical_hash(
                {key: value for key, value in forged.items() if key != "receipt_sha256"}
            )
            rejected = v234.publish_guard(
                root, mode="snapshot", snapshot_receipt=forged
            )
            self.assertFalse(rejected["ok"], rejected)

    def test_candidate_snapshot_cli_persists_and_revalidates_receipt(self) -> None:
        """CLI coverage for the protected candidate receipt."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = init_candidate_repo(root)
            apply_v234_candidate(root)
            receipt_path = root / "candidate-snapshot.json"
            command = [
                sys.executable,
                str(REPO_ROOT / "scripts/v23/goalteams_v23.py"),
                "v234-candidate-snapshot",
                str(root),
                "--baseline-commit",
                baseline,
                "--receipt",
                str(receipt_path),
            ]
            created = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
            self.assertTrue(json.loads(created.stdout)["ok"])
            guarded = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts/v23/goalteams_v23.py"),
                    "v234-publish-guard",
                    str(root),
                    "--snapshot-receipt",
                    str(receipt_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(guarded.returncode, 0, guarded.stderr or guarded.stdout)
            self.assertTrue(json.loads(guarded.stdout)["ok"])

    def test_completion_proof_binds_exact_proof_and_complete_required_task_set(self) -> None:
        """Security extension of ASSERT-V234-052."""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            _, proof, context, _ = strict_completion_fixture(
                self, Path(directory), completion_descriptors()
            )
            Path(context["completion_proof_path"]).write_text(
                '{"forged":true}\n', encoding="utf-8"
            )
            forged_file = v234.validate_release_closure(proof, source_context=context)
            self.assertFalse(forged_file["ok"], forged_file)
            self.assertIn("completion_proof_file", forged_file["gaps"])

        with tempfile.TemporaryDirectory() as directory:
            _, proof, context, _ = strict_completion_fixture(
                self, Path(directory), completion_descriptors()
            )
            context["checkpoint"]["tasks"]["TASK-V234-OMITTED"] = {
                "task_state": "accepted",
                "check_state": "passed",
                "required_for_done": True,
                "acceptance_blocking": True,
            }
            audit = copy.deepcopy(context["audit_record"])
            audit["required_task_ids"] = sorted(context["checkpoint"]["tasks"])
            audit["task_state_digest"] = canonical_hash(context["checkpoint"]["tasks"])
            audit = resign(audit)
            context["audit_record"] = audit
            Path(context["audit_path"]).write_text(
                json.dumps(audit, ensure_ascii=True, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            omitted = v234.validate_release_closure(proof, source_context=context)
            self.assertFalse(omitted["ok"], omitted)
            self.assertIn("required_tasks", omitted["gaps"])

    def test_completion_gate_accepts_exact_current_snapshot_instead_of_commit(self) -> None:
        """Positive isolated-tree path for ASSERT-V234-029/052."""
        v234 = require_v234(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, proof, context, _ = strict_completion_fixture(
                self, root, completion_descriptors()
            )
            baseline = git(root, "rev-parse", "HEAD")
            (root / "VERSION").write_text("V2.34\n\n", encoding="utf-8")
            state_source = root / "scripts/v23/v234_state.py"
            state_source.write_text("# V2.34 isolated snapshot\n", encoding="utf-8")
            cli_source = root / "scripts/v23/goalteams_v23.py"
            cli_source.write_text(
                cli_source.read_text(encoding="utf-8") + "# protected snapshot CLI\n",
                encoding="utf-8",
            )
            test_source = root / "tests/v23/test_v234_snapshot_mode.py"
            test_source.parent.mkdir(parents=True)
            test_source.write_text("def test_snapshot_mode():\n    assert True\n", encoding="utf-8")
            receipt_path = root / "candidate-snapshot.json"
            snapshot = v234.create_protected_candidate_snapshot(
                root, baseline_commit=baseline, receipt_path=receipt_path
            )
            self.assertTrue(snapshot["ok"], snapshot)
            context.pop("baseline_commit")
            context.pop("candidate_commit")
            context["candidate_snapshot_receipt"] = snapshot["receipt"]
            context["candidate_snapshot_path"] = str(receipt_path)
            proof["candidate_snapshot_receipt_sha256"] = snapshot["receipt"][
                "receipt_sha256"
            ]
            proof["proof_digest"] = canonical_hash(
                {key: value for key, value in proof.items() if key != "proof_digest"}
            )
            Path(context["completion_proof_path"]).write_text(
                json.dumps(proof, ensure_ascii=True, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            valid = v234.validate_release_closure(proof, source_context=context)
            self.assertTrue(valid["ok"], valid)

            receipt_path.write_text('{"forged":true}\n', encoding="utf-8")
            forged = v234.validate_release_closure(proof, source_context=context)
            self.assertFalse(forged["ok"], forged)
            self.assertIn("publish", forged["gaps"])

    def test_completion_audit_cannot_be_resigned_with_mismatched_bindings(self) -> None:
        """Security extension of ASSERT-V234-052."""
        mutations = {
            "required_task_ids": lambda value: value.__setitem__("required_task_ids", []),
            "evidence_refs": lambda value: value.__setitem__("evidence_refs", []),
            "bundle_revision": lambda value: value.__setitem__("bundle_revision", 999),
            "bundle_digest": lambda value: value.__setitem__("bundle_digest", "0" * 64),
            "task_state_digest": lambda value: value.__setitem__("task_state_digest", "0" * 64),
            "review_sha256": lambda value: value.__setitem__("review_sha256", "0" * 64),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                v234 = require_v234(self)
                _, proof, context, _ = strict_completion_fixture(
                    self, Path(directory), completion_descriptors()
                )
                audit = copy.deepcopy(context["audit_record"])
                mutate(audit)
                audit = resign(audit)
                context["audit_record"] = audit
                Path(context["audit_path"]).write_text(
                    json.dumps(audit, ensure_ascii=True, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                result = v234.validate_release_closure(proof, source_context=context)
                self.assertFalse(result["ok"], (field, result))
                self.assertIn("review_audit", result["gaps"])


if __name__ == "__main__":
    unittest.main()
