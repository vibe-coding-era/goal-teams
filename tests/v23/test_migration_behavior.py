"""V2.3 typed migration and behavior-run contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import stat
from pathlib import Path

from tests.v23.common import ROOT, TOOL, clone, gt, has_error, parse_envelope, run_cli, sha256_path


def legacy_tasklist(state: str = "planned", *, independent_check: str = "not_started") -> str:
    return f"""---
type: Goal Teams TaskList
title: V2.2 migration fixture
goal_teams_version: V2.2
---
# V2.2 TaskList

| task_id | title | handoff_status | independent_check_status | required_for_done | acceptance_blocking |
| --- | --- | --- | --- | --- | --- |
| LEGACY-1 | Legacy task | {state} | {independent_check} | true | true |
"""


def tree_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def tree_modes(root: Path) -> dict[str, int]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): stat.S_IMODE(path.lstat().st_mode)
        for path in sorted(root.rglob("*"))
    }


class MigrationTests(unittest.TestCase):
    def migrate(self, src: Path, dst: Path, phase: str, *, env: dict[str, str] | None = None):
        proc = subprocess.run(
            [sys.executable, str(TOOL), "migrate", str(src), str(dst), "--phase", phase],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        return proc, parse_envelope(proc)

    def test_scan_and_plan_are_read_only_and_report_legacy_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, dst = root / "legacy", root / "target"
            src.mkdir()
            legacy = src / "tasklist.md"
            legacy.write_text(legacy_tasklist(), encoding="utf-8")
            source_before = tree_snapshot(src)
            for phase in ("scan", "plan"):
                with self.subTest(phase=phase):
                    proc, envelope = self.migrate(src, dst, phase)
                    self.assertEqual(proc.returncode, 0, envelope)
                    self.assertTrue(envelope["ok"])
                    migration = envelope["migration"]
                    self.assertEqual(migration["legacy_hashes"]["tasklist.md"], sha256_path(legacy))
                    self.assertFalse(dst.exists())
                    self.assertEqual(tree_snapshot(src), source_before)

    def test_dual_ssot_and_manual_review_block_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, dst = root / "legacy", root / "target"
            src.mkdir()
            (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
            (src / "TaskList.md").write_text(legacy_tasklist(), encoding="utf-8")
            if not {"tasklist.md", "TaskList.md"} <= set(os.listdir(src)):
                self.skipTest("dual case fixture requires a case-sensitive filesystem; Linux CI covers this gate")
            proc, envelope = self.migrate(src, dst, "apply")
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(envelope["ok"])
            self.assertTrue(has_error(envelope, "E_MIGRATION_MANUAL_REVIEW"))
            self.assertFalse(dst.exists())

    def test_unverified_v22_completion_migrates_as_explicit_gap_never_accepted_or_achieved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, dst = root / "legacy", root / "target"
            src.mkdir()
            (src / "tasklist.md").write_text(
                legacy_tasklist("done", independent_check="passed"), encoding="utf-8"
            )
            proc, envelope = self.migrate(src, dst, "plan")
            self.assertEqual(proc.returncode, 0)
            migration = envelope["migration"]
            report_text = json.dumps(migration, ensure_ascii=False)
            self.assertTrue(migration.get("gaps"), migration)
            self.assertFalse(migration.get("manual_review"), migration)
            self.assertNotIn('"task_state": "accepted"', report_text)
            self.assertNotIn('"run_outcome": "achieved"', report_text)
            apply_proc, apply_envelope = self.migrate(src, dst, "apply")
            self.assertEqual(apply_proc.returncode, 0, apply_envelope)
            self.assertTrue(apply_envelope["ok"])
            checkpoint = json.loads((dst / "ledger/checkpoint.json").read_text(encoding="utf-8"))
            task = checkpoint["tasks"]["LEGACY-1"]
            self.assertEqual(task["task_state"], "review")
            self.assertEqual(task["check_state"], "not_started")
            audit = json.loads((dst / "audit/completion-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["run_outcome"], "partial")

    def test_staging_verification_failure_is_byte_equivalent_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, dst = root / "legacy", root / "target"
            src.mkdir()
            dst.mkdir()
            (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
            (dst / "TaskList.md").write_bytes(b"existing canonical bytes\n")
            (dst / "keep.bin").write_bytes(b"\x00\x01keep")
            before = tree_snapshot(dst)
            env = dict(os.environ)
            env["GOAL_TEAMS_TEST_FAIL_MIGRATION_STAGE"] = "verify"
            proc, envelope = self.migrate(src, dst, "apply", env=env)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(envelope["ok"])
            self.assertTrue(has_error(envelope, "E_MIGRATION_STAGING_VERIFY"))
            self.assertEqual(tree_snapshot(dst), before)

    def test_apply_rejects_preexisting_staging_and_rollback_path_collisions(self) -> None:
        for path_kind in ("staging", "rollback"):
            for collision_kind in ("directory", "symlink"):
                with (
                    self.subTest(path=path_kind, collision=collision_kind),
                    tempfile.TemporaryDirectory() as td,
                ):
                    root = Path(td)
                    src, dst = root / "legacy", root / "target"
                    src.mkdir()
                    dst.mkdir()
                    (src / "tasklist.md").write_text(
                        legacy_tasklist(), encoding="utf-8"
                    )
                    (dst / "TaskList.md").write_bytes(b"existing target\n")
                    plan_proc, plan_envelope = self.migrate(src, dst, "plan")
                    self.assertEqual(plan_proc.returncode, 0, plan_envelope)
                    plan_id = plan_envelope["migration"]["plan_id"]
                    collision = dst.with_name(
                        f".{dst.name}.goalteams-{path_kind}-{plan_id[:12]}"
                    )
                    external = root / f"external-{path_kind}-{collision_kind}"
                    external.mkdir()
                    (external / "sentinel.bin").write_bytes(
                        f"{path_kind}-{collision_kind}-must-survive\x00".encode()
                    )
                    if collision_kind == "directory":
                        collision.mkdir()
                        (collision / "collision.bin").write_bytes(
                            b"preexisting collision must survive\x00"
                        )
                    else:
                        try:
                            collision.symlink_to(external, target_is_directory=True)
                        except OSError as exc:
                            self.skipTest(f"directory symlink unavailable: {exc}")

                    source_before = tree_snapshot(src)
                    destination_before = tree_snapshot(dst)
                    external_before = tree_snapshot(external)
                    collision_before = (
                        os.readlink(collision)
                        if collision.is_symlink()
                        else tree_snapshot(collision)
                    )
                    apply_proc, apply_envelope = self.migrate(src, dst, "apply")
                    self.assertNotEqual(apply_proc.returncode, 0, apply_envelope)
                    self.assertTrue(
                        has_error(apply_envelope, "E_MIGRATION_RECOVERY_COLLISION"),
                        apply_envelope,
                    )
                    self.assertEqual(tree_snapshot(src), source_before)
                    self.assertEqual(tree_snapshot(dst), destination_before)
                    self.assertEqual(tree_snapshot(external), external_before)
                    if collision_kind == "symlink":
                        self.assertTrue(collision.is_symlink())
                        self.assertEqual(os.readlink(collision), collision_before)
                    else:
                        self.assertTrue(collision.is_dir())
                        self.assertEqual(tree_snapshot(collision), collision_before)

    def test_successful_apply_writes_only_canonical_case_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, dst = root / "legacy", root / "target"
            src.mkdir()
            (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
            source_before = tree_snapshot(src)
            proc, envelope = self.migrate(src, dst, "apply")
            self.assertEqual(proc.returncode, 0, envelope)
            exact_names = {entry.name for entry in dst.iterdir()}
            self.assertIn("TaskList.md", exact_names)
            self.assertNotIn("tasklist.md", exact_names)
            self.assertTrue((dst / "migration-manifest.json").is_file())
            for relative in (
                "ledger/events.jsonl",
                "ledger/checkpoint.json",
                "audit/completion-audit.json",
            ):
                self.assertTrue((dst / relative).is_file(), relative)
            self.assertEqual(tree_snapshot(src), source_before)
            events = [
                json.loads(line)
                for line in (dst / "ledger/events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            checkpoint = json.loads((dst / "ledger/checkpoint.json").read_text(encoding="utf-8"))
            replay = gt.reduce_events(events, valid_evidence_ids=set(), evidence_registry={})
            self.assertEqual(replay, checkpoint)
            self.assertEqual(gt.validate_checkpoint(checkpoint), [])
            self.assertEqual(gt.render_tasklist(checkpoint).encode("utf-8"), (dst / "TaskList.md").read_bytes())
            audit = json.loads((dst / "audit/completion-audit.json").read_text(encoding="utf-8"))
            self.assertNotEqual(audit.get("run_outcome"), "achieved")
            self.assertEqual(
                gt.validate_completion_audit(
                    audit,
                    checkpoint["tasks"],
                    set(),
                    traceability_valid=False,
                    dual_review_valid=False,
                ),
                [],
            )
            verify_proc, verify_envelope = self.migrate(src, dst, "verify")
            self.assertEqual(verify_proc.returncode, 0, verify_envelope)

    def test_verify_rejects_missing_or_corrupt_migration_ledger_checkpoint_and_audit(self) -> None:
        mutations = {
            "missing_ledger": lambda dst: (dst / "ledger/events.jsonl").unlink(),
            "corrupt_checkpoint": lambda dst: (dst / "ledger/checkpoint.json").write_text("{}\n", encoding="utf-8"),
            "projection_drift": lambda dst: (dst / "TaskList.md").write_text("manual drift\n", encoding="utf-8"),
            "missing_audit": lambda dst: (dst / "audit/completion-audit.json").unlink(),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                src, dst = root / "legacy", root / "target"
                src.mkdir()
                (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
                apply_proc, apply_envelope = self.migrate(src, dst, "apply")
                self.assertEqual(apply_proc.returncode, 0, apply_envelope)
                mutate(dst)
                verify_proc, verify_envelope = self.migrate(src, dst, "verify")
                self.assertNotEqual(verify_proc.returncode, 0)
                self.assertFalse(verify_envelope["ok"])
                self.assertEqual(verify_envelope["error_code"], "E_MIGRATION_VERIFY")

    def test_verify_rejects_manifest_provenance_and_mapping_tampering(self) -> None:
        mutations = {
            "source_sha256_null": (
                lambda doc: doc.update(source_sha256=None),
                "E_MIGRATION_SOURCE_BINDING",
            ),
            "source_sha256_random": (
                lambda doc: doc.update(source_sha256="0" * 64),
                "E_MIGRATION_SOURCE_BINDING",
            ),
            "source_file": (
                lambda doc: doc.update(source_file="forged-tasklist.md"),
                "E_MIGRATION_SOURCE_BINDING",
            ),
            "legacy_hash": (
                lambda doc: doc["legacy_hashes"].update(
                    {doc["source_file"]: "0" * 64}
                ),
                "E_MIGRATION_SOURCE_BINDING",
            ),
            "plan_id": (
                lambda doc: doc.update(plan_id="0" * 64),
                "E_MIGRATION_PLAN_BINDING",
            ),
            "mappings": (
                lambda doc: doc.update(mappings=[]),
                "E_MIGRATION_PLAN_BINDING",
            ),
        }
        for name, (mutate, expected_detail) in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                src, dst = root / "legacy", root / "target"
                src.mkdir()
                (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
                apply_proc, apply_envelope = self.migrate(src, dst, "apply")
                self.assertEqual(apply_proc.returncode, 0, apply_envelope)
                manifest_path = dst / "migration-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest)
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                verify_proc, verify_envelope = self.migrate(src, dst, "verify")
                self.assertNotEqual(verify_proc.returncode, 0, verify_envelope)
                self.assertFalse(verify_envelope["ok"])
                self.assertEqual(
                    verify_envelope["error_code"], "E_MIGRATION_VERIFY", verify_envelope
                )
                self.assertTrue(
                    has_error(verify_envelope, expected_detail),
                    verify_envelope,
                )

    def test_explicit_rollback_restores_previous_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src, dst = root / "legacy", root / "target"
            src.mkdir()
            dst.mkdir()
            (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
            (dst / "TaskList.md").write_bytes(b"before migration\n")
            executable = dst / "verify.sh"
            executable.write_bytes(b"#!/bin/sh\nexit 0\n")
            os.chmod(dst / "TaskList.md", 0o644)
            os.chmod(executable, 0o755)
            before = tree_snapshot(dst)
            modes_before = tree_modes(dst)
            apply_proc, apply_envelope = self.migrate(src, dst, "apply")
            self.assertEqual(apply_proc.returncode, 0, apply_envelope)
            rollback_proc, rollback_envelope = self.migrate(src, dst, "rollback")
            self.assertEqual(rollback_proc.returncode, 0, rollback_envelope)
            self.assertEqual(tree_snapshot(dst), before)
            self.assertEqual(tree_modes(dst), modes_before)

    def test_rollback_rejects_backup_mode_drift_before_touching_either_tree(self) -> None:
        # macOS clears setuid/setgid bits on ordinary files for an unprivileged
        # owner, so use the sticky bit as the portable non-canonical mode.
        for drift_mode in (0o755, 0o1644):
            with self.subTest(mode=oct(drift_mode)), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                src, dst = root / "legacy", root / "target"
                src.mkdir()
                dst.mkdir()
                (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
                protected = dst / "protected.txt"
                protected.write_bytes(b"rollback mode binding\n")
                os.chmod(protected, 0o644)
                apply_proc, apply_envelope = self.migrate(src, dst, "apply")
                self.assertEqual(apply_proc.returncode, 0, apply_envelope)
                manifest = json.loads(
                    (dst / "migration-manifest.json").read_text(encoding="utf-8")
                )
                backup = Path(manifest["rollback_path"])
                backup_file = backup / "protected.txt"
                os.chmod(backup_file, drift_mode)
                destination_before = tree_snapshot(dst)
                destination_modes_before = tree_modes(dst)
                backup_before = tree_snapshot(backup)
                backup_modes_before = tree_modes(backup)

                rollback_proc, rollback_envelope = self.migrate(src, dst, "rollback")
                self.assertNotEqual(rollback_proc.returncode, 0, rollback_envelope)
                self.assertTrue(
                    has_error(rollback_envelope, "E_MIGRATION_ROLLBACK_BINDING"),
                    rollback_envelope,
                )
                self.assertEqual(tree_snapshot(dst), destination_before)
                self.assertEqual(tree_modes(dst), destination_modes_before)
                self.assertEqual(tree_snapshot(backup), backup_before)
                self.assertEqual(tree_modes(backup), backup_modes_before)

    def test_rollback_rejects_live_target_drift_without_touching_any_tree(self) -> None:
        mutations = {
            "added": lambda dst: (dst / "injected.txt").write_bytes(b"post-apply addition\n"),
            "modified": lambda dst: (dst / "TaskList.md").write_bytes(b"post-apply mutation\n"),
            "deleted": lambda dst: (dst / "TaskList.md").unlink(),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                src, dst = root / "legacy", root / "target"
                sentinel = root / "external-sentinel.bin"
                src.mkdir()
                dst.mkdir()
                (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
                (dst / "protected.txt").write_bytes(b"pre-migration target\n")
                os.chmod(dst / "protected.txt", 0o644)
                sentinel.write_bytes(b"outside rollback scope\x00")
                apply_proc, apply_envelope = self.migrate(src, dst, "apply")
                self.assertEqual(apply_proc.returncode, 0, apply_envelope)
                manifest = json.loads(
                    (dst / "migration-manifest.json").read_text(encoding="utf-8")
                )
                backup = Path(manifest["rollback_path"])
                mutate(dst)
                destination_before = tree_snapshot(dst)
                destination_modes_before = tree_modes(dst)
                backup_before = tree_snapshot(backup)
                backup_modes_before = tree_modes(backup)
                sentinel_before = sentinel.read_bytes()

                rollback_proc, rollback_envelope = self.migrate(src, dst, "rollback")
                self.assertNotEqual(rollback_proc.returncode, 0, rollback_envelope)
                self.assertTrue(
                    has_error(rollback_envelope, "E_MIGRATION_ROLLBACK_DRIFT"),
                    rollback_envelope,
                )
                self.assertEqual(tree_snapshot(dst), destination_before)
                self.assertEqual(tree_modes(dst), destination_modes_before)
                self.assertEqual(tree_snapshot(backup), backup_before)
                self.assertEqual(tree_modes(backup), backup_modes_before)
                self.assertEqual(sentinel.read_bytes(), sentinel_before)

    def test_rollback_rejects_manifest_path_and_identity_injection_without_writes(self) -> None:
        def set_external_rollback(manifest: dict, external: Path) -> None:
            manifest["rollback_path"] = str(external)

        def set_external_destination(manifest: dict, external: Path) -> None:
            manifest["destination"] = str(external)

        def set_forged_plan(manifest: dict, _external: Path) -> None:
            manifest["plan_id"] = "0" * 64

        def set_forged_previous_flag(manifest: dict, _external: Path) -> None:
            manifest["had_previous_target"] = False

        mutations = {
            "rollback_path": set_external_rollback,
            "destination": set_external_destination,
            "plan_id": set_forged_plan,
            "had_previous_target": set_forged_previous_flag,
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                src, dst = root / "legacy", root / "target"
                external = root / "external-sentinel"
                src.mkdir()
                dst.mkdir()
                external.mkdir()
                (src / "tasklist.md").write_text(legacy_tasklist(), encoding="utf-8")
                (dst / "TaskList.md").write_bytes(b"pre-migration target\n")
                (external / "sentinel.bin").write_bytes(b"outside must not move\x00")
                apply_proc, apply_envelope = self.migrate(src, dst, "apply")
                self.assertEqual(apply_proc.returncode, 0, apply_envelope)
                manifest_path = dst / "migration-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest, external)
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                destination_before = tree_snapshot(dst)
                external_before = tree_snapshot(external)
                rollback_proc, rollback_envelope = self.migrate(src, dst, "rollback")
                self.assertNotEqual(rollback_proc.returncode, 0, rollback_envelope)
                self.assertTrue(
                    has_error(rollback_envelope, "E_MIGRATION_ROLLBACK_BINDING"),
                    rollback_envelope,
                )
                self.assertEqual(tree_snapshot(dst), destination_before)
                self.assertEqual(tree_snapshot(external), external_before)


class BehaviorRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.trace_path = self.root / "trace.jsonl"
        self.evidence_path = self.root / "run.log"
        self.score_path = self.root / "score.json"
        self.trace_path.write_text('{"step":"executed"}\n', encoding="utf-8")
        self.evidence_path.write_text("actual command output\n", encoding="utf-8")
        self.score_path.write_text('{"quality":1.0,"decision":"pass"}\n', encoding="utf-8")
        input_value = {"prompt": "只规划", "features": {"risk": "low"}}
        output_value = {"profile": "lite", "writes": []}
        self.good = {
            "schema_version": "goal-teams-v2.3",
            "scenario_id": "plan-preview",
            "scenario_class": "core",
            "evaluation_class": "deterministic_contract",
            "release_eligible": False,
            "input": input_value,
            "output": output_value,
            "executed": True,
            "result": "passed",
            "subject_run_id": "RUN-SUBJECT-1",
            "scorer_run_id": "RUN-SCORER-1",
            "started_at": "2026-07-10T00:00:00Z",
            "ended_at": "2026-07-10T00:00:01Z",
            "environment": {
                "commit": "0" * 40,
                "platform": "test-platform",
                "python_version": "3.x-test",
            },
            "provenance": {
                "runner_id": "tests.v23.behavior-runner",
                "runner_version": "V2.3",
                "run_nonce": "TEST-RUN-NONCE-1",
                "generated_at": "2026-07-10T00:00:02Z",
                "input_sha256": hashlib.sha256(
                    json.dumps(input_value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "output_sha256": hashlib.sha256(
                    json.dumps(output_value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "command": {
                    "argv": ["goalteams_v23.py", "route", "input.json"],
                    "cwd": ".",
                    "exit_code": 0,
                    "log_path": "run.log",
                    "log_sha256": sha256_path(self.evidence_path),
                },
            },
            "trace": [{"path": "trace.jsonl", "sha256": sha256_path(self.trace_path)}],
            "evidence": [{"path": "run.log", "sha256": sha256_path(self.evidence_path)}],
            "score": {
                "quality": 1.0,
                "rubric_version": "behavior-v2.3",
                "scorer_run_id": "RUN-SCORER-1",
                "evidence_path": "score.json",
                "evidence_sha256": sha256_path(self.score_path),
            },
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def validate(self, doc: dict):
        return gt.validate_behavior_run(doc, self.root)

    def test_plan_preview_route_is_observably_filesystem_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = root / "request.json"
            request.write_text(json.dumps({"risk": "low"}), encoding="utf-8")
            before = tree_snapshot(root)
            proc = subprocess.run(
                [sys.executable, str(TOOL), "route", "request.json"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            after = tree_snapshot(root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        envelope = parse_envelope(proc)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["route"]["profile"], "lite")
        self.assertEqual(before, after, "plan preview route mutated the filesystem")

    def test_provenance_bound_run_passes(self) -> None:
        self.assertEqual(self.validate(self.good), [])

    def test_static_self_report_and_mutations_fail_closed(self) -> None:
        cases = {
            "static_self_report": (
                lambda doc: [doc.pop(key, None) for key in ("provenance", "trace", "evidence")],
                "E_BEHAVIOR_PROVENANCE",
            ),
            "self_scored": (lambda doc: doc.update(scorer_run_id=doc["subject_run_id"]), "E_BEHAVIOR_SELF_SCORE"),
            "missing_runner_log": (
                lambda doc: doc["provenance"]["command"].update(log_path="missing.log"),
                "E_BEHAVIOR_EVIDENCE",
            ),
            "trace_hash": (lambda doc: doc["trace"][0].update(sha256="0" * 64), "E_BEHAVIOR_TRACE_HASH"),
            "evidence_hash": (lambda doc: doc["evidence"][0].update(sha256="0" * 64), "E_BEHAVIOR_EVIDENCE_HASH"),
            "score_hash": (lambda doc: doc["score"].update(evidence_sha256="0" * 64), "E_BEHAVIOR_SCORE_HASH"),
            "empty_input": (lambda doc: doc.update(input={}), "E_BEHAVIOR_INPUT"),
            "empty_output": (lambda doc: doc.update(output={}), "E_BEHAVIOR_OUTPUT"),
            "ready_claim": (lambda doc: doc.update(result="ready"), "E_BEHAVIOR_RESULT"),
            "completed_claim": (lambda doc: doc.update(result="completed"), "E_BEHAVIOR_RESULT"),
            "failed_required_scenario": (lambda doc: doc.update(result="failed"), "E_BEHAVIOR_RESULT"),
            "negative_quality": (lambda doc: doc["score"].update(quality=-999), "E_BEHAVIOR_SCORE"),
            "quality_above_one": (lambda doc: doc["score"].update(quality=1.01), "E_BEHAVIOR_SCORE"),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(case=name):
                doc = clone(self.good)
                mutate(doc)
                errors = self.validate(doc)
                self.assertTrue(errors, f"behavior mutation {name} was accepted")
                self.assertTrue(has_error(errors, expected), f"{name}: expected {expected}, got {errors}")

    def test_canonical_suite_covers_core_and_stress_scenarios(self) -> None:
        behavior_root = ROOT / "examples" / "canonical-v23" / "versions" / "V2.3" / "behavior"
        records = []
        for path in sorted(behavior_root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("scenario_id"):
                records.append(payload)
        ids = {item["scenario_id"] for item in records}
        required_core = {"plan-preview", "backend-cli", "ui-replica", "long-task-recovery"}
        required_stress = {
            "revision-conflict",
            "forged-evidence",
            "self-review",
            "telemetry-unavailable",
            "no-custom-agent",
        }
        self.assertTrue(required_core <= ids, f"missing core scenarios: {sorted(required_core - ids)}")
        self.assertTrue(required_stress <= ids, f"missing stress scenarios: {sorted(required_stress - ids)}")
        for record in records:
            with self.subTest(scenario=record["scenario_id"]):
                self.assertEqual(record.get("evaluation_class"), "deterministic_contract")
                self.assertIs(record.get("release_eligible"), False)
                errors = gt.validate_behavior_run(record, behavior_root)
                self.assertEqual(errors, [])


class BenchmarkRunnerTests(unittest.TestCase):
    runner = ROOT / "scripts" / "benchmark" / "benchmark-runner.py"

    def load_runner_module(self, name: str = "goalteams_benchmark_under_test"):
        spec = importlib.util.spec_from_file_location(name, self.runner)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def run_benchmark(self, *args: str) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, str(self.runner), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return proc

    def make_blind_package_repo(self, root: Path) -> None:
        files = {
            "AGENTS.md": "fixture agents\n",
            "VERSION": "V2.3\n",
            "SKILL.md": "---\nname: goal-teams\ndescription: fixture\n---\n",
            "RULES.md": "fixture rules\n",
            "goal-teams.md": "fixture goal teams\n",
            "README.md": "installer-only readme\n",
            "GoalTeams-PRD-V2.3.md": "installer-only PRD\n",
            "agents/openai.yaml": "interface:\n  display_name: fixture\n",
            "prompts/visible.md": "blind-safe prompt\n",
            "references/invariants.md": "blind-safe reference\n",
            "schemas/v2.3/goal-teams.schema.json": "{}\n",
            "scripts/check.sh": "#!/bin/sh\nexit 0\n",
            "scripts/checks/check-v23.py": "raise SystemExit('must not stage')\n",
            "scripts/review/review.py": "raise SystemExit('must not stage')\n",
            "scripts/v23/tool.py": "print('blind-safe runtime')\n",
            "subagents/goal-test.toml": "name = 'fixture'\n",
            "tests/v23/answer.py": "ANSWER = True\n",
            "benchmarks/tasks/answer.md": "hidden benchmark answer\n",
            "examples/canonical/answer.json": "{}\n",
            "outputs/run/answer.json": "{}\n",
        }
        manifest = """# fixture installer package
file AGENTS.md
file GoalTeams-PRD-V2.3.md
file README.md
file RULES.md
file SKILL.md
file VERSION
file goal-teams.md
prefix agents/
prefix benchmarks/
prefix examples/
prefix outputs/
prefix prompts/
prefix references/
prefix schemas/
prefix scripts/
prefix subagents/
prefix tests/v23/
"""
        files["scripts/install/package-manifest.txt"] = manifest
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        os.chmod(root / "scripts/check.sh", 0o755)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "blind-stage@example.invalid"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Blind Stage Fixture"],
            cwd=root,
            check=True,
        )
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "package fixture"], cwd=root, check=True)
        untracked = root / "prompts/untracked.md"
        untracked.write_text("must be recorded but never staged\n", encoding="utf-8")
        (root / "tests/v23/untracked-answer.py").write_text(
            "ANSWER = 'must not even enter excluded_untracked'\n", encoding="utf-8"
        )
        (root / "references/skill-authoring-guide.md").write_text(
            "untracked blind-safe-looking guide\n", encoding="utf-8"
        )
        integrity_log = root / "examples/canonical-v23/versions/V2.3/evidence/integrity.log"
        integrity_log.parent.mkdir(parents=True, exist_ok=True)
        integrity_log.write_text("untracked canonical evidence\n", encoding="utf-8")

    def test_blind_stage_is_the_installer_index_projection_and_excludes_untracked(self) -> None:
        module = self.load_runner_module("goalteams_benchmark_stage_projection")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "source"
            root.mkdir()
            self.make_blind_package_repo(root)
            module.ROOT = root
            selection = module._blind_package_selection(root)
            expected_safe = sorted(
                path
                for path in selection["installer_tracked_paths"]
                if module._blind_path_is_allowlisted(path)
                and not module._blind_path_is_forbidden(path)
            )
            self.assertEqual(selection["blind_safe_paths"], expected_safe)
            self.assertEqual(
                selection["excluded_untracked"],
                [
                    "prompts/untracked.md",
                    "references/skill-authoring-guide.md",
                ],
            )

            stage = module._stage_blind_package(base / "staged")
            staged_paths = [entry["path"] for entry in stage["files"]]
            self.assertEqual(staged_paths, expected_safe)
            self.assertNotIn("prompts/untracked.md", staged_paths)
            self.assertNotIn("references/skill-authoring-guide.md", staged_paths)
            self.assertNotIn(
                "examples/canonical-v23/versions/V2.3/evidence/integrity.log",
                staged_paths,
            )
            self.assertIn("scripts/review/review.py", staged_paths)
            forbidden_leaks = {
                "README.md",
                "GoalTeams-PRD-V2.3.md",
                "scripts/checks/check-v23.py",
                "scripts/install/package-manifest.txt",
                "tests/v23/answer.py",
                "benchmarks/tasks/answer.md",
                "examples/canonical/answer.json",
                "outputs/run/answer.json",
            }
            self.assertTrue(forbidden_leaks.isdisjoint(staged_paths), staged_paths)
            self.assertEqual(
                stage["package_manifest_sha256"],
                sha256_path(root / "scripts/install/package-manifest.txt"),
            )
            self.assertEqual(
                stage["blind_safe_entries_sha256"],
                module.digest_bytes(module.canonical_bytes(selection["blind_safe_entries"])),
            )
            for entry in stage["files"]:
                self.assertIn(entry["mode"], {"100644", "100755"})

    def test_blind_selection_rejects_tracked_path_through_ancestor_symlink(self) -> None:
        cases = {
            "blind_safe": ("prompts", "visible.md"),
            "installer_only": ("benchmarks", "tasks/answer.md"),
        }
        for name, (ancestor, relative_file) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                module = self.load_runner_module(f"goalteams_benchmark_ancestor_symlink_{name}")
                base = Path(td)
                root = base / "source"
                root.mkdir()
                self.make_blind_package_repo(root)
                external = base / f"external-{ancestor}"
                external_file = external / relative_file
                external_file.parent.mkdir(parents=True)
                external_file.write_text(
                    "external bytes must never enter package identity\n", encoding="utf-8"
                )
                shutil.rmtree(root / ancestor)
                (root / ancestor).symlink_to(external, target_is_directory=True)
                module.ROOT = root
                with self.assertRaises(module.BlindEvalError) as raised:
                    module._blind_package_selection(root)
                self.assertEqual(raised.exception.code, "E_PACKAGE_IDENTITY")

    def test_blind_stage_rejects_index_worktree_and_special_mode_drift(self) -> None:
        for mutation in ("index_only", "worktree_only", "special_bits"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                base = Path(td)
                root = base / "source"
                root.mkdir()
                self.make_blind_package_repo(root)
                module = self.load_runner_module(
                    f"goalteams_benchmark_mode_{mutation}"
                )
                module.ROOT = root
                source = root / "prompts/visible.md"
                if mutation == "index_only":
                    subprocess.run(
                        ["git", "update-index", "--chmod=+x", "prompts/visible.md"],
                        cwd=root,
                        check=True,
                    )
                elif mutation == "worktree_only":
                    os.chmod(source, 0o755)
                else:
                    # The sticky bit persists on regular files on macOS and
                    # Linux, unlike setuid/setgid bits which macOS may clear.
                    os.chmod(source, 0o1644)
                with self.assertRaises(module.BlindEvalError) as raised:
                    module._stage_blind_package(base / "staged")
                self.assertEqual(raised.exception.code, "E_PACKAGE_IDENTITY")

    def test_blind_stage_rejects_selection_to_copy_byte_drift(self) -> None:
        module = self.load_runner_module("goalteams_benchmark_stage_toctou")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "source"
            root.mkdir()
            self.make_blind_package_repo(root)
            module.ROOT = root
            original_selection = module.build_blind_package_selection

            def select_then_mutate(source_root: Path) -> dict:
                selection = original_selection(source_root)
                (source_root / "prompts/visible.md").write_text(
                    "changed after selection but before copy\n", encoding="utf-8"
                )
                return selection

            module.build_blind_package_selection = select_then_mutate
            with self.assertRaises(module.BlindEvalError) as raised:
                module._stage_blind_package(base / "staged")
            self.assertEqual(raised.exception.code, "E_PACKAGE_IDENTITY")

    def test_blind_tree_manifest_rejects_symlink_and_nonregular_entries(self) -> None:
        module = self.load_runner_module("goalteams_benchmark_nonregular")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            tree = base / "tree"
            tree.mkdir()
            regular = tree / "regular.txt"
            regular.write_text("regular\n", encoding="utf-8")
            os.chmod(regular, 0o644)
            external = base / "external-secret.txt"
            external.write_text("must not be followed\n", encoding="utf-8")
            link = tree / "link.txt"
            link.symlink_to(external)
            with self.assertRaises(module.BlindEvalError) as raised:
                module._tree_manifest(tree)
            self.assertEqual(raised.exception.code, "E_BLIND_AGENT_STAGE_NONREGULAR")
            self.assertEqual(external.read_text(encoding="utf-8"), "must not be followed\n")
            link.unlink()

            fifo = tree / "named-pipe"
            if not hasattr(os, "mkfifo"):
                self.skipTest("FIFO creation is unavailable on this platform")
            os.mkfifo(fifo)
            with self.assertRaises(module.BlindEvalError) as raised:
                module._tree_manifest(tree)
            self.assertEqual(raised.exception.code, "E_BLIND_AGENT_STAGE_NONREGULAR")

    def test_deterministic_contract_mode_is_explicitly_not_behavior_release_evidence(self) -> None:
        proc = self.run_benchmark("--mode", "contract", "--check-only")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("deterministic contract", proc.stdout.lower())
        self.assertIn("does not satisfy behavior gate", proc.stdout.lower())

    def test_contract_or_fixture_runner_cannot_pass_release_gate(self) -> None:
        contract = self.run_benchmark("--mode", "contract", "--release-gate")
        self.assertNotEqual(contract.returncode, 0)
        self.assertIn("E_BLIND_AGENT_REQUIRED", contract.stdout + contract.stderr)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subject = root / "subject.py"
            subject.write_text(
                "import json,sys\nsys.stdin.read()\n"
                "print(json.dumps({'status':'fixture_ok','privilege_escalated':False,"
                "'loaded_refs':['AGENTS.md','SKILL.md','RULES.md']}))\n",
                encoding="utf-8",
            )
            manifest = {
                "schema_version": "goal-teams-blind-eval-v2.3",
                "evaluation_id": "EVAL-FIXTURE",
                "adapter": {
                    "type": "fixture",
                    "provider": "local-pipeline-fixture",
                    "command": [sys.executable, str(subject)],
                    "version_command": [sys.executable, "--version"],
                },
                "scenarios": [
                    {
                        "scenario_id": "pipeline-fixture",
                        "required": True,
                        "prompt": "subject sees only this prompt",
                        "scorer": {
                            "type": "json_contract",
                            "allowed_fields": ["status", "privilege_escalated"],
                            "forbidden_fields": ["hidden_answer"],
                            "required_fields": [
                                {"path": "status", "value_type": "string", "equals": "fixture_ok"},
                                {"path": "privilege_escalated", "value_type": "boolean", "equals": False},
                            ],
                            "input_bindings": [],
                        },
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "runs"
            pipeline = self.run_benchmark(
                "--mode", "blind-agent", "--manifest", str(manifest_path), "--output-dir", str(output)
            )
            self.assertEqual(pipeline.returncode, 0, pipeline.stdout + pipeline.stderr)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(
                gt._validate_blind_stage(
                    output,
                    summary["staged_manifest"],
                    summary["source_provenance"],
                ),
                [],
            )
            record_path = output / "pipeline-fixture" / "record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["evaluation_class"], "pipeline_fixture")
            self.assertFalse(record["release_eligible"])
            self.assertEqual(
                record["provider_provenance"]["provider_trust_level"],
                "local_process_attested",
            )
            self.assertNotIn(
                "crypto", record["provider_provenance"]["provider_trust_level"]
            )
            self.assertEqual(gt.validate_behavior_run(record, record_path.parent), [])
            drifted = clone(record)
            drifted["isolation"]["source_tree_sha256_after"] = "0" * 64
            self.assertTrue(
                has_error(
                    gt.validate_behavior_run(drifted, record_path.parent),
                    "E_BEHAVIOR_SOURCE_DRIFT",
                )
            )
            self.assertTrue(record["isolation"]["isolated_workspace"])
            self.assertTrue(record["isolation"]["workspace_unchanged"])
            self.assertTrue(record["isolation"]["source_repository_unchanged"])
            self.assertFalse(record["isolation"]["scorer_staged_with_subject"])
            for name in ("input.json", "stdout.log", "stderr.log", "output.txt", "rubric.json", "score.json", "record.json"):
                self.assertTrue((record_path.parent / name).is_file(), name)
            stage = json.loads((output / "stage-manifest.json").read_text(encoding="utf-8"))
            staged_paths = {item["path"] for item in stage["files"]}
            persisted_paths = {
                str(path.relative_to(output / "staged-package"))
                for path in (output / "staged-package").rglob("*")
                if path.is_file()
            }
            self.assertEqual(persisted_paths, staged_paths)
            for entry in stage["files"]:
                path = output / "staged-package" / entry["path"]
                self.assertEqual(path.stat().st_size, entry["size"])
                self.assertEqual(sha256_path(path), entry["sha256"])
            self.assertIn("AGENTS.md", staged_paths)
            self.assertIn("SKILL.md", staged_paths)
            self.assertIn("RULES.md", staged_paths)
            self.assertFalse(
                any(
                    set(Path(path).parts) & {"tests", "benchmarks", "examples", "GoalTeamsWork-V2.3"}
                    for path in staged_paths
                )
            )
            blocked = self.run_benchmark(
                "--mode",
                "blind-agent",
                "--release-gate",
                "--manifest",
                str(manifest_path),
                "--output-dir",
                str(root / "release-runs"),
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("E_BLIND_AGENT_FIXTURE", blocked.stdout + blocked.stderr)

    def test_non_git_source_digest_fallback_is_stable_and_detects_midrun_change(self) -> None:
        module = self.load_runner_module("goalteams_benchmark_non_git_digest")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "SKILL.md"
            source.write_text("stable installed source\n", encoding="utf-8")
            (root / "scripts").mkdir()
            (root / "scripts/runner.py").write_text("VALUE = 1\n", encoding="utf-8")
            module.ROOT = root

            source_before = module._source_tree_digest()
            status_before = module._workspace_status_digest()
            self.assertRegex(source_before, r"^[0-9a-f]{64}$")
            self.assertRegex(status_before, r"^[0-9a-f]{64}$")
            self.assertEqual(source_before, module._source_tree_digest())
            self.assertEqual(status_before, module._workspace_status_digest())

            dynamic = root / "outputs/run-1"
            dynamic.mkdir(parents=True)
            (dynamic / "result.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(source_before, module._source_tree_digest())
            self.assertEqual(status_before, module._workspace_status_digest())

            source.write_text("mutated during evaluation\n", encoding="utf-8")
            self.assertNotEqual(source_before, module._source_tree_digest())
            self.assertNotEqual(status_before, module._workspace_status_digest())

    def test_codex_manifest_separates_subject_prompt_from_hidden_scorer(self) -> None:
        manifest_path = ROOT / "tests/v23/fixtures/behavior/blind-agent-codex.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["adapter"]["type"], "codex_cli")
        self.assertEqual(manifest["adapter"]["provider"], "openai-codex-cli")
        expected = {
            "blind-plan-preview",
            "blind-backend-cli",
            "blind-ui-replica",
            "blind-long-task-recovery",
            "blind-forged-evidence",
            "blind-self-review",
            "blind-telemetry-unavailable",
            "blind-no-custom-agent",
            "blind-prompt-injection",
        }
        self.assertEqual({item["scenario_id"] for item in manifest["scenarios"]}, expected)
        self.assertTrue(all(item.get("required") is True for item in manifest["scenarios"]))
        for scenario in manifest["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                subject_payload = json.dumps(
                    {
                        "scenario_id": scenario["scenario_id"],
                        "prompt": scenario["prompt"],
                        "context": scenario.get("subject_input", {}),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                self.assertEqual(scenario["scorer"]["type"], "json_contract")
                self.assertTrue(scenario["scorer"]["required_fields"])
                self.assertNotIn("required_patterns", scenario["scorer"])
                self.assertNotIn(json.dumps(scenario["scorer"], sort_keys=True), subject_payload)

    def test_typed_hidden_scorer_pristine_then_mutations_fail_closed(self) -> None:
        module = self.load_runner_module()
        scorer = {
            "type": "json_contract",
            "allowed_fields": ["accepted", "error_code", "reason"],
            "forbidden_fields": ["completion_claim"],
            "required_fields": [
                {"path": "accepted", "value_type": "boolean", "equals": False},
                {"path": "error_code", "value_type": "string", "equals": "E_HASH_MISMATCH"},
                {"path": "reason", "value_type": "string", "nonempty": True},
            ],
            "input_bindings": [],
        }
        pristine = json.dumps(
            {"accepted": False, "error_code": "E_HASH_MISMATCH", "reason": "hash differs"}
        )
        passed, details = module._score_blind_output(pristine, scorer, {})
        self.assertTrue(passed, details)
        mutations = {
            "invalid_json": ("```json\n{}\n```", "E_BLIND_AGENT_OUTPUT_JSON"),
            "wrong_type": (
                json.dumps({"accepted": "false", "error_code": "E_HASH_MISMATCH", "reason": "hash differs"}),
                "E_BLIND_AGENT_OUTPUT_CONTRACT",
            ),
            "wrong_value": (
                json.dumps({"accepted": True, "error_code": "E_HASH_MISMATCH", "reason": "hash differs"}),
                "E_BLIND_AGENT_OUTPUT_CONTRACT",
            ),
            "forbidden_semantic": (
                json.dumps(
                    {
                        "accepted": False,
                        "error_code": "E_HASH_MISMATCH",
                        "reason": "hash differs",
                        "completion_claim": True,
                    }
                ),
                "E_BLIND_AGENT_OUTPUT_CONTRACT",
            ),
        }
        for name, (payload, expected) in mutations.items():
            with self.subTest(case=name):
                passed, details = module._score_blind_output(payload, scorer, {})
                self.assertFalse(passed)
                self.assertEqual(details["error_code"], expected)


if __name__ == "__main__":
    unittest.main()
