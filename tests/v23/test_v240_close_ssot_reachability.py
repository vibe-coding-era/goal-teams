from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.v23.common import ROOT


def _load_release_module():
    path = ROOT / "scripts" / "release" / "release.py"
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_close_reachability", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE = _load_release_module()


def _load_v23_module():
    path = ROOT / "scripts" / "v23" / "goalteams_v23.py"
    spec = importlib.util.spec_from_file_location(
        "goal_teams_v240_close_reachability_v23", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V23 = _load_v23_module()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _materialize_nonportable_evidence(
    work_root: Path,
    target_version: Path,
    candidate: str,
) -> None:
    evidence_path = target_version / "evidence" / "evidence.jsonl"
    records = [
        json.loads(line)
        for line in evidence_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source_paths = ["VERSION"]
    workspace_revision = V23.source_manifest_sha256(
        ROOT,
        source_paths,
        commit=candidate,
    )
    for record in records:
        record.pop("portable_fixture", None)
        record.pop("artifact_transport", None)
        record.pop("mtime_policy", None)
        record["environment"].update(
            {
                "commit": candidate,
                "workspace_revision": workspace_revision,
                "source_paths": source_paths,
            }
        )
        artifact = work_root / record["artifact_ref"]
        log = work_root / record["command"]["log_path"]
        record["artifact_mtime_ns"] = artifact.stat().st_mtime_ns
        record["command"]["log_mtime_ns"] = log.stat().st_mtime_ns

        binding_digest = V23.evidence_replay_binding_digest(record)
        integrity_argv = V23.artifact_verifier_argv(
            record["artifact_ref"],
            record["artifact_sha256"],
            binding_digest,
        )
        replay = subprocess.run(
            integrity_argv,
            cwd=work_root,
            capture_output=True,
            check=False,
        )
        if replay.returncode != 0 or replay.stderr:
            raise AssertionError(
                f"integrity replay failed: {replay.returncode} {replay.stderr!r}"
            )
        integrity_log = work_root / record["integrity_replay"]["log_path"]
        integrity_log.write_bytes(replay.stdout)
        record["integrity_replay"].update(
            {
                "argv": integrity_argv,
                "exit_code": replay.returncode,
                "log_sha256": _sha256(integrity_log),
                "log_size": integrity_log.stat().st_size,
                "log_mtime_ns": integrity_log.stat().st_mtime_ns,
            }
        )

    evidence_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    _write_json(target_version / "evidence" / "evidence.json", records[0])
    _write_json(target_version / "evidence" / "evidence-recovery.json", records[1])


class V240CloseSsotReachabilityTests(unittest.TestCase):
    def test_formal_archived_ssot_chain_is_reachable_with_standard_v23_fields(
        self,
    ) -> None:
        """Exercise reducer, TaskList, Evidence, Harness, review, and audit.

        The frozen canonical V2.3 bundle supplies a mechanically valid ledger
        and Evidence chain.  The V2.40 control copy deliberately retains
        standard ``check_state``/``audit_state`` fields (without synthetic
        ``passed`` booleans), while the original V2.3 subtree remains the
        immutable artifact target referenced by those records.
        """

        self.assertEqual(
            RELEASE.V236_GOAL_TEAMS_TRUSTED_RELEASE_BASE,
            V23.V236_GOAL_TEAMS_TRUSTED_RELEASE_BASE,
        )
        host_boundary_required = RELEASE._requires_v236_completion_host_boundary(ROOT)
        if not host_boundary_required:
            self.skipTest(
                "CP18 reachability requires the trusted Goal Teams Git lineage"
            )
        candidate = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        full_gate_calls: list[list[str]] = []

        def run_without_recursive_full_gate(argv, workspace):
            values = [str(value) for value in argv]
            if len(values) > 1 and Path(values[1]).name == "check-v23.py":
                full_gate_calls.append(values)
                # Real unittest output contains volatile duration/temp-path
                # text.  Deliberately vary both observation hashes across the
                # two CP18 replays; the stable SSOT receipt must not change.
                call_number = len(full_gate_calls)
                return {
                    "argv_sha256": RELEASE._canonical_json_sha256(values),
                    "stdout_sha256": hashlib.sha256(
                        f"volatile stdout {call_number}".encode()
                    ).hexdigest(),
                    "stderr_sha256": hashlib.sha256(
                        f"Ran tests in 0.{call_number}s".encode()
                    ).hexdigest(),
                    "exit_code": 0,
                }
            return original_ssot_validator(argv, workspace)

        original_ssot_validator = RELEASE._run_ssot_validator
        canonical = ROOT / "examples" / "canonical-v23"
        docs = ROOT / "docs"
        docs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="v240-close-ssot-", dir=docs) as tmp:
            archive_root = Path(tmp)
            work_root = archive_root / "GoalTeamsWork-V2.40"
            shutil.copytree(canonical, work_root)
            source_version = work_root / "versions" / "V2.3"
            target_version = work_root / "versions" / "V2.40"
            shutil.copytree(source_version, target_version)
            _materialize_nonportable_evidence(work_root, target_version, candidate)
            pre_finalization_tree = RELEASE._directory_tree_receipt(work_root)

            harness_path = target_version / "harness" / "harness.json"
            harness = json.loads(harness_path.read_text(encoding="utf-8"))
            harness["harness_contract"]["checks"] = [
                check
                for check in harness["harness_contract"]["checks"]
                if check.get("check_state") == "passed"
            ]
            harness["runs"] = [
                run for run in harness["runs"] if run.get("status") == "passed"
            ]
            _write_json(harness_path, harness)

            trace_path = target_version / "harness" / "traceability.json"
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["checks"] = [
                check
                for check in trace["checks"]
                if check.get("check_state") == "passed"
            ]
            trace["runs"] = [
                run for run in trace["runs"] if run.get("status") == "passed"
            ]
            _write_json(trace_path, trace)

            audit_path = target_version / "audit" / "completion-audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit.update(
                {
                    "source_commit": candidate,
                    "version": "V2.40",
                    "independent": True,
                }
            )
            _write_json(audit_path, audit)

            reviews = target_version / "reviews"
            _write_json(
                reviews / "final-independent-review.json",
                {
                    "schema_version": "goal-teams-v2.40-review-receipt-v1",
                    "status": "passed",
                    "role": "independent_release_reviewer",
                    "source_commit": candidate,
                    "version": "V2.40",
                    "independent": True,
                },
            )
            _write_json(
                reviews / "final-independent-qa.json",
                {
                    "schema_version": "goal-teams-v2.40-review-receipt-v1",
                    "status": "passed",
                    "role": "independent_release_qa",
                    "source_commit": candidate,
                    "version": "V2.40",
                    "independent": True,
                },
            )

            reducer_probe = subprocess.run(
                [
                    "python3.13",
                    str(ROOT / "scripts" / "v23" / "goalteams_v23.py"),
                    "reduce-ledger",
                    str(target_version / "ledger" / "events.jsonl"),
                    "--ledger-owner-run-id",
                    "RUN-CAN-LEDGER-OWNER",
                    "--evidence-jsonl",
                    str(target_version / "evidence" / "evidence.jsonl"),
                    "--evidence-root",
                    str(work_root),
                    "--source-root",
                    str(ROOT),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                reducer_probe.returncode,
                0,
                reducer_probe.stdout + "\n" + reducer_probe.stderr,
            )
            reduced = json.loads(reducer_probe.stdout)
            self.assertTrue(reduced["ok"])
            _write_json(
                target_version / "ledger" / "checkpoint.json",
                reduced["state"],
            )

            # CP18 normally runs after the canonical root has fast-forwarded
            # to the frozen candidate.  This test executes earlier from the
            # candidate worktree, so bind the validator to that equivalent
            # workspace boundary explicitly.
            with (
                mock.patch.object(RELEASE, "_workspace_root", return_value=ROOT),
                mock.patch.object(
                    RELEASE,
                    "_run_ssot_validator",
                    side_effect=run_without_recursive_full_gate,
                ),
            ):
                completion_bytes = audit_path.read_bytes()
                audit_path.unlink()
                with self.assertRaises(RELEASE.PolicyError) as missing_completion:
                    RELEASE._validate_archived_goal_teams_ssot(
                        archive_root,
                        {"candidate_commit": candidate, "version": "V2.40"},
                    )
                self.assertEqual(
                    missing_completion.exception.receipt["error_code"],
                    "E_V240_CLOSE_SSOT",
                )
                audit_path.write_bytes(completion_bytes)

                finalization_tree = RELEASE._directory_tree_receipt(work_root)
                self.assertNotEqual(
                    pre_finalization_tree,
                    finalization_tree,
                    "accepted evidence/review/Completion must finalize after CP17",
                )
                receipt = RELEASE._validate_archived_goal_teams_ssot(
                    archive_root,
                    {"candidate_commit": candidate, "version": "V2.40"},
                )
                replayed_receipt = RELEASE._validate_archived_goal_teams_ssot(
                    archive_root,
                    {"candidate_commit": candidate, "version": "V2.40"},
                )

            self.assertEqual(
                receipt,
                replayed_receipt,
                "CP18 pre/post-finalize SSOT receipts must ignore volatile validator logs",
            )

        self.assertEqual(receipt["required_task_count"], 2)
        self.assertEqual(receipt["ledger_revision"], 21)
        validators = receipt["formal_validators"]
        self.assertEqual(validators["reduce_ledger"]["exit_code"], 0)
        self.assertEqual(validators["render_tasklist"]["exit_code"], 0)
        self.assertEqual(validators["completion_audit"]["exit_code"], 1)
        self.assertTrue(validators["completion_audit"]["host_boundary_enforced"])
        self.assertEqual(
            validators["completion_audit"]["expected_error_code"],
            "E_V236_HOST_ADAPTER_REQUIRED",
        )
        self.assertEqual(validators["check_v23"]["exit_code"], 0)
        self.assertEqual(len(full_gate_calls), 2)

    def test_private_goal_teams_provenance_is_not_public_payload(self) -> None:
        private = RELEASE.scan_private_evidence_payload(
            {
                "identity/registry.json": json.dumps(
                    {
                        "transport_handle": "reviewer-local-handle",
                        "artifact_path": "/Users/" + "example/private-evidence.json",
                    }
                )
            }
        )
        self.assertTrue(private["passed"])
        with self.assertRaises(RELEASE.PolicyError):
            RELEASE.scan_public_payload(
                {"identity/registry.json": '{"transport_handle":"private"}'}
            )


if __name__ == "__main__":
    unittest.main()
