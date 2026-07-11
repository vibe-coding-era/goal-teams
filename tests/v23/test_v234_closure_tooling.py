"""V2.34 safe closure builders and bounded LOOP workflow tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.v23.common import ROOT
from tests.v23.test_v234_release_archive import archive_descriptor
from tests.v23.test_v234_reset_delivery import (
    initialize_reset_state,
    strict_completion_fixture,
)
from tests.v23.test_v234_state_loop import (
    OWNER_RUN,
    initialize_bundle,
    marker,
    require_v234,
    state_proof,
)


CLOSURE_PATH = ROOT / "scripts" / "v23" / "v234_closure.py"


def require_closure(test: unittest.TestCase) -> Any:
    spec = importlib.util.spec_from_file_location(
        "goalteams_v234_closure_under_test", CLOSURE_PATH
    )
    if spec is None or spec.loader is None:
        test.fail("V2.34 closure module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_ledger_inputs(
    root: Path, events: list[dict[str, Any]], checkpoint: dict[str, Any]
) -> tuple[Path, Path]:
    ledger = root / "ledger-input.jsonl"
    ledger.write_text(
        "".join(
            json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n"
            for item in events
        ),
        encoding="utf-8",
    )
    checkpoint_path = root / "checkpoint-input.json"
    checkpoint_path.write_bytes(
        json.dumps(
            checkpoint, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    return ledger, checkpoint_path


def write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


class V234ClosureSnapshotTests(unittest.TestCase):
    def test_ledger_binding_and_legacy_digest_are_derived_from_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, initialized = initialize_bundle(self, directory)
            closure = require_closure(self)
            proof = state_proof(state_root)
            ledger, checkpoint = write_ledger_inputs(
                state_root, proof["ledger_events"], proof["checkpoint"]
            )

            binding_dir = state_root / ".goalteams-state" / "closure" / "binding-001"
            binding = closure.snapshot_ledger_binding(
                v234,
                state_root,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                output_dir=binding_dir,
            )
            self.assertTrue(binding["ok"], binding)
            self.assertEqual(binding["ledger_binding"]["revision"], 1)
            self.assertEqual(
                binding["ledger_binding"]["checkpoint_sha256"],
                hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            )
            self.assertTrue((binding_dir / "manifest.json").is_file())

            legacy_dir = state_root / ".goalteams-state" / "closure" / "legacy-001"
            legacy = closure.snapshot_legacy_adoption(
                state_root, output_dir=legacy_dir
            )
            self.assertTrue(legacy["ok"], legacy)
            expected_records = []
            for name in sorted(
                ("feature_list.json", "progress.md", "contract.md", "log.md")
            ):
                data = (state_root / name).read_bytes()
                expected_records.append(
                    {
                        "path": name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size": len(data),
                    }
                )
            expected = hashlib.sha256(
                json.dumps(
                    expected_records,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(legacy["legacy_digest"], expected)
            self.assertEqual(
                marker(state_root)["bundle_digest"], initialized["bundle_digest"]
            )

            duplicate = closure.snapshot_legacy_adoption(
                state_root, output_dir=legacy_dir
            )
            self.assertEqual(duplicate["error_code"], "E_V234_CLOSURE_CONFLICT")

    def test_snapshot_destination_and_symlink_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            v234, repo, state_root, _ = initialize_bundle(self, directory)
            closure = require_closure(self)
            proof = state_proof(state_root)
            ledger, checkpoint = write_ledger_inputs(
                state_root, proof["ledger_events"], proof["checkpoint"]
            )
            escaped = closure.snapshot_ledger_binding(
                v234,
                state_root,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                output_dir=repo / "escaped",
            )
            self.assertFalse(escaped["ok"], escaped)
            self.assertFalse((repo / "escaped").exists())

            target = state_root / "real-log.md"
            (state_root / "log.md").replace(target)
            os.symlink(target.name, state_root / "log.md")
            rejected = closure.snapshot_legacy_adoption(
                state_root,
                output_dir=state_root / ".goalteams-state" / "closure" / "bad-legacy",
            )
            self.assertEqual(rejected["error_code"], "E_V234_CLOSURE_LEGACY")

    def test_reset_authorization_and_plan_are_persisted_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                v234,
                _,
                state_root,
                before,
                candidate,
                authorization,
                identities,
                events,
                _,
            ) = initialize_reset_state(self, directory)
            closure = require_closure(self)
            auth_path = write_json(state_root / "authorization-input.json", authorization)
            identities_path = write_json(state_root / "identity-input.json", identities)
            ledger_path = state_root / "reset-ledger-input.jsonl"
            ledger_path.write_text(
                "".join(
                    json.dumps(
                        item,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                    for item in events
                ),
                encoding="utf-8",
            )
            # initialize_reset_state does not publish its checkpoint through the
            # shared helper; reset planning only consumes the ledger JSONL.
            output = state_root / ".goalteams-state" / "resets" / "RESET-V234-001"
            result = closure.snapshot_reset_plan(
                v234,
                state_root,
                repo_root=Path(directory),
                candidate_id=candidate.name,
                authorization_path=auth_path,
                identity_registry_path=identities_path,
                ledger_path=ledger_path,
                output_dir=output,
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["mutation_count"], 0)
            self.assertTrue(candidate.is_dir())
            self.assertEqual(marker(state_root)["bundle_digest"], before["bundle_digest"])
            self.assertEqual(
                json.loads((output / "reset-authorization.json").read_text()),
                authorization,
            )
            self.assertEqual(
                json.loads((output / "reset-plan.json").read_text())["plan_sha256"],
                result["plan"]["plan_sha256"],
            )

    def test_completion_builder_reconstructs_gate_inputs_and_validates_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "v234@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "V2.34 Closure"],
                cwd=repo,
                check=True,
            )
            descriptors = archive_descriptor()
            bundle, expected_proof, context, _ = strict_completion_fixture(
                self, repo, descriptors
            )
            v234 = require_v234(self)
            closure = require_closure(self)
            state_root = repo / "GoalTeamsWork-V2.34" / "versions" / "V2.34"
            state_root.mkdir(parents=True)
            write_json(state_root / "feature_list.json", bundle)
            for name in ("progress.md", "contract.md", "log.md"):
                (state_root / name).write_text(f"fixture {name}\n", encoding="utf-8")
            ledger, checkpoint = write_ledger_inputs(
                state_root, context["ledger_events"], context["checkpoint"]
            )
            # strict_completion_fixture adds the final required-task flags
            # after its lower-level Evidence helper returns.  Rebind the
            # wrapper to that final checkpoint, as a real persisted wrapper is.
            context["evidence_registry"]["checkpoint_sha256"] = hashlib.sha256(
                checkpoint.read_bytes()
            ).hexdigest()
            registry_path = write_json(
                state_root / "validated-evidence-registry.json",
                context["evidence_registry"],
            )
            output = state_root / ".goalteams-state" / "closure" / "completion-001"
            evidence_id = expected_proof["evidence_ids"][0]
            built = closure.build_completion_snapshot(
                v234,
                state_root,
                repo_root=repo,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                evidence_registry_path=registry_path,
                identity_registry_path=context["identity_path"],
                review_record_path=context["review_path"],
                audit_record_path=context["audit_path"],
                roadmap_path=context["roadmap_path"],
                rebuilt_candidate_path=repo / expected_proof["rebuilt_candidate"]["artifact_ref"],
                rebuilt_candidate_evidence_id=evidence_id,
                repository_check_evidence_id=evidence_id,
                required_task_ids=expected_proof["required_task_ids"],
                evidence_ids=expected_proof["evidence_ids"],
                public_sources=["public/guide.md", "public/release.md"],
                validator_run_id="RUN-QA-V234-01",
                baseline_commit=context["baseline_commit"],
                candidate_commit=context["candidate_commit"],
                candidate_snapshot_path=None,
                protected_paths=["user-owned.txt"],
                output_dir=output,
            )
            self.assertTrue(built["ok"], built)
            self.assertEqual(built["gate"]["run_outcome_candidate"], "achieved")
            self.assertEqual(len(built["eligible_artifact_ids"]), 2)
            generated_proof = json.loads(
                (output / "completion-proof.json").read_text(encoding="utf-8")
            )
            generated_context = json.loads(
                (output / "source-context.json").read_text(encoding="utf-8")
            )
            generated_descriptors = json.loads(
                (output / "archive-descriptor.json").read_text(encoding="utf-8")
            )
            checked = v234.evaluate_delivery_gate(
                bundle,
                generated_proof,
                generated_descriptors,
                source_context=generated_context,
            )
            self.assertTrue(checked["ok"], checked)

            (repo / ".gitignore").write_text(
                "\n".join(
                    (
                        "GoalTeamsWork-*",
                        "identity/",
                        "reviews/",
                        "audit/",
                        "evidence*",
                        "execution-*",
                        "integrity-*",
                        "reset-*",
                        "source.py",
                        "report.md",
                        "completion-proof.json",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            state_source = repo / "scripts" / "v23" / "v234_state.py"
            state_source.write_text(
                "# V2.34 closure snapshot baseline\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", ".gitignore", "scripts/v23/v234_state.py"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-qm", "ignore private fixture inputs"],
                cwd=repo,
                check=True,
            )
            snapshot_baseline = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            (repo / "README.md").write_text(
                (repo / "README.md").read_text(encoding="utf-8")
                + "\nProtected snapshot candidate.\n",
                encoding="utf-8",
            )
            (repo / "VERSION").write_text("V2.34\n\n", encoding="utf-8")
            state_source.write_text(
                state_source.read_text(encoding="utf-8") + "# snapshot delta\n",
                encoding="utf-8",
            )
            cli_source = repo / "scripts" / "v23" / "goalteams_v23.py"
            cli_source.write_text(
                cli_source.read_text(encoding="utf-8") + "# snapshot delta\n",
                encoding="utf-8",
            )
            snapshot_test = repo / "tests" / "v23" / "test_v234_closure_snapshot.py"
            snapshot_test.parent.mkdir(parents=True, exist_ok=True)
            snapshot_test.write_text(
                "def test_closure_snapshot():\n    assert True\n", encoding="utf-8"
            )
            snapshot_path = state_root / "candidate-snapshot.json"
            snapshot = v234.create_protected_candidate_snapshot(
                repo,
                baseline_commit=snapshot_baseline,
                receipt_path=snapshot_path,
            )
            self.assertTrue(snapshot["ok"], snapshot)
            snapshot_output = (
                state_root / ".goalteams-state" / "closure" / "completion-snapshot-001"
            )
            snapshot_built = closure.build_completion_snapshot(
                v234,
                state_root,
                repo_root=repo,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                evidence_registry_path=registry_path,
                identity_registry_path=context["identity_path"],
                review_record_path=context["review_path"],
                audit_record_path=context["audit_path"],
                roadmap_path=context["roadmap_path"],
                rebuilt_candidate_path=repo
                / expected_proof["rebuilt_candidate"]["artifact_ref"],
                rebuilt_candidate_evidence_id=evidence_id,
                repository_check_evidence_id=evidence_id,
                required_task_ids=expected_proof["required_task_ids"],
                evidence_ids=expected_proof["evidence_ids"],
                public_sources=["public/guide.md", "public/release.md"],
                validator_run_id="RUN-QA-V234-01",
                baseline_commit=None,
                candidate_commit=None,
                candidate_snapshot_path=snapshot_path,
                protected_paths=["user-owned.txt"],
                output_dir=snapshot_output,
            )
            self.assertTrue(snapshot_built["ok"], snapshot_built)
            snapshot_proof = json.loads(
                (snapshot_output / "completion-proof.json").read_text(encoding="utf-8")
            )
            snapshot_context = json.loads(
                (snapshot_output / "source-context.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                snapshot_proof["candidate_snapshot_receipt_sha256"],
                snapshot["receipt"]["receipt_sha256"],
            )
            self.assertNotIn("candidate_commit", snapshot_context)

            forged_registry = json.loads(registry_path.read_text(encoding="utf-8"))
            forged_registry["records_sha256"] = "0" * 64
            forged_path = write_json(state_root / "forged-registry.json", forged_registry)
            rejected = closure.build_completion_snapshot(
                v234,
                state_root,
                repo_root=repo,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                evidence_registry_path=forged_path,
                identity_registry_path=context["identity_path"],
                review_record_path=context["review_path"],
                audit_record_path=context["audit_path"],
                roadmap_path=context["roadmap_path"],
                rebuilt_candidate_path=repo / expected_proof["rebuilt_candidate"]["artifact_ref"],
                rebuilt_candidate_evidence_id=evidence_id,
                repository_check_evidence_id=evidence_id,
                required_task_ids=expected_proof["required_task_ids"],
                evidence_ids=expected_proof["evidence_ids"],
                public_sources=["public/guide.md"],
                validator_run_id="RUN-QA-V234-01",
                baseline_commit=context["baseline_commit"],
                candidate_commit=context["candidate_commit"],
                candidate_snapshot_path=None,
                protected_paths=["user-owned.txt"],
                output_dir=state_root / ".goalteams-state" / "closure" / "forged",
            )
            self.assertEqual(rejected["error_code"], "E_V234_CLOSURE_EVIDENCE")


class V234LoopAdvanceTests(unittest.TestCase):
    def _workflow_inputs(
        self, state_root: Path
    ) -> tuple[Path, Path, Path, Path]:
        proof = state_proof(state_root)
        ledger, checkpoint = write_ledger_inputs(
            state_root, proof["ledger_events"], proof["checkpoint"]
        )
        registry = write_json(state_root / "empty-registry.json", {})
        identities = write_json(state_root / "empty-identities.json", {"runs": {}})
        return ledger, checkpoint, registry, identities

    def test_loop_advance_stops_at_iteration_nine_reset_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, _ = initialize_bundle(
                self, directory, iteration=9, phase="reason"
            )
            closure = require_closure(self)
            ledger, checkpoint, registry, identities = self._workflow_inputs(state_root)
            before = marker(state_root)
            result = closure.advance_loop(
                v234,
                state_root,
                target_iteration=9,
                target_phase="act",
                actor_run_id=OWNER_RUN,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                evidence_registry_path=registry,
                identity_registry_path=identities,
                output_dir=state_root / ".goalteams-state" / "loop" / "blocked-reset",
            )
            self.assertEqual(result["error_code"], "E_V234_RESET_REQUIRED")
            self.assertEqual(result["step_count"], 1)
            self.assertEqual(marker(state_root)["bundle_digest"], before["bundle_digest"])
            receipt = json.loads(
                (
                    state_root
                    / ".goalteams-state"
                    / "loop"
                    / "blocked-reset"
                    / "loop-advance.json"
                ).read_text(encoding="utf-8")
            )
            self.assertFalse(receipt["completed"])

    def test_loop_advance_reaches_iteration_eleven_verify_but_not_beyond(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            v234, _, state_root, _ = initialize_bundle(
                self, directory, iteration=10, phase="gather"
            )
            closure = require_closure(self)
            ledger, checkpoint, registry, identities = self._workflow_inputs(state_root)
            reached = closure.advance_loop(
                v234,
                state_root,
                target_iteration=11,
                target_phase="verify",
                actor_run_id=OWNER_RUN,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                evidence_registry_path=registry,
                identity_registry_path=identities,
                output_dir=state_root / ".goalteams-state" / "loop" / "to-delivery",
            )
            self.assertTrue(reached["ok"], reached)
            self.assertEqual(marker(state_root)["loop"]["iteration"], 11)
            self.assertEqual(marker(state_root)["loop"]["phase"], "verify")
            before = marker(state_root)
            refused = closure.advance_loop(
                v234,
                state_root,
                target_iteration=11,
                target_phase="repeat",
                actor_run_id=OWNER_RUN,
                ledger_path=ledger,
                checkpoint_path=checkpoint,
                evidence_registry_path=registry,
                identity_registry_path=identities,
                output_dir=state_root / ".goalteams-state" / "loop" / "past-delivery",
            )
            self.assertEqual(refused["error_code"], "E_V234_LOOP_TARGET")
            self.assertEqual(marker(state_root)["bundle_digest"], before["bundle_digest"])


class V234ClosureCliTests(unittest.TestCase):
    def test_cli_exposes_closure_and_loop_commands(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "v23" / "goalteams_v23.py"), "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in (
            "v234-closure-ledger-binding",
            "v234-closure-legacy-digest",
            "v234-closure-reset-snapshot",
            "v234-closure-build",
            "v234-loop-advance",
        ):
            self.assertIn(command, result.stdout)


if __name__ == "__main__":
    unittest.main()
