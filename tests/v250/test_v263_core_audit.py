from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.v250.git_change_receipt import (
    GitChangeError,
    capture_git_baseline,
    compile_git_change_receipt,
)
from scripts.v250.state_reducer import (
    StateReducerError,
    completion_projection,
    make_state_event,
    reduce_state_events,
)
from scripts.v250.task_plan_compiler import (
    TaskPlanError,
    classify_audit_finding,
    compile_blocker_receipt,
    compile_task_plan,
)


ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 64


def _canonical_digest(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _task(task_id: str, *, depends_on: list[str] | None = None) -> dict[str, object]:
    return {
        "task_id": task_id,
        "requirement_refs": ["REQ-V263"],
        "consumer_refs": ["consumer:goal-lead"],
        "owner": f"owner:{task_id}",
        "validator": f"validator:{task_id}",
        "scope_allowlist": [f"scope/{task_id}/**"],
        "forbidden_scope": ["README.md"],
        "depends_on": list(depends_on or []),
        "budget_wu": 1,
        "attempt_budget": 1,
        "revalidation_budget": 1,
        "inputs": [{"input_id": f"input:{task_id}"}],
        "outputs": [
            {
                "output_id": f"output:{task_id}",
                "consumer_refs": ["consumer:goal-lead"],
                "required": True,
            }
        ],
        "verification": [f"verify:{task_id}"],
        "business_oracle": f"oracle:{task_id}",
        "exit_condition": f"exit:{task_id}",
        "failure_artifacts": [],
    }


def _plan(
    tasks: list[dict[str, object]], phase_exact_sets: dict[str, list[str]]
) -> dict[str, object]:
    return {
        "schema_version": "goal-teams-task-plan-v1",
        "plan_id": "GT-V263-CORE-AUDIT",
        "plan_revision": 1,
        "tasks": tasks,
        "phase_exact_sets": phase_exact_sets,
    }


class V263CoreAuditTests(unittest.TestCase):
    def test_audit_finding_requires_exact_booleans(self) -> None:
        canonical: dict[str, object] = {
            "finding_id": "FINDING-CORE-AUDIT",
            "evidence_verified": True,
            "in_locked_scope": True,
            "consumer_confirmed": True,
            "estimated_attempts": 1,
            "attempt_budget_remaining": 1,
            "estimated_revalidations": 1,
            "revalidation_budget_remaining": 1,
            "authorization_boundary_unchanged": True,
        }
        for field in (
            "evidence_verified",
            "in_locked_scope",
            "consumer_confirmed",
            "authorization_boundary_unchanged",
        ):
            with self.subTest(field=field):
                malformed = {**canonical, field: "false"}
                with self.assertRaises(TaskPlanError) as raised:
                    classify_audit_finding(malformed)
                self.assertEqual("E_V263_FINDING_BOOLEAN", raised.exception.code)

    def test_task_plan_schema_compiles_under_strict_ajv(self) -> None:
        script = """
const fs = require('fs');
const Ajv2020 = require('ajv/dist/2020');
const schema = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
new Ajv2020({strict: true, allErrors: true, validateFormats: false}).compile(schema);
"""
        subprocess.run(
            ["node", "-e", script, str(ROOT / "schemas/v2.50/task-plan.schema.json")],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_forbidden_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self._repo(Path(temporary))
            baseline = capture_git_baseline(repo)
            (repo / "owned/forbidden.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(GitChangeError) as raised:
                compile_git_change_receipt(
                    repo,
                    baseline,
                    {
                        "P08": {
                            "scope_allowlist": ["owned/**"],
                            "forbidden_scope": ["owned/forbidden.txt"],
                        }
                    },
                )
            self.assertEqual("E_V263_GIT_FORBIDDEN_SCOPE", raised.exception.code)

    def test_state_event_binds_authorization_lineage(self) -> None:
        bindings = {
            "source_sha256": "1" * 64,
            "route_sha256": "2" * 64,
            "contract_sha256": "3" * 64,
            "task_exact_set_sha256": "4" * 64,
            "environment_sha256": "5" * 64,
            "authorization_lineage_sha256": "6" * 64,
        }
        event = make_state_event(
            event_id="event-1",
            event_seq=1,
            event_type="task.transition",
            axis="task",
            entity_id="P09",
            previous_event_sha256="0" * 64,
            cas_base_revision=0,
            before_state="pending",
            requested_state="active",
            bindings=bindings,
            actor_identity="goal_lead",
            actor_relationship="authorized_writer",
            evidence_refs=["sha256:" + SHA],
            occurred_at="2026-08-12T00:00:00Z",
        )
        projection = reduce_state_events([event], expected_bindings=bindings)
        self.assertEqual(
            bindings["authorization_lineage_sha256"],
            projection["bindings"]["authorization_lineage_sha256"],
        )
        drifted = {**bindings, "authorization_lineage_sha256": "7" * 64}
        with self.assertRaises(StateReducerError) as raised:
            reduce_state_events([event], expected_bindings=drifted)
        self.assertEqual("E_V263_STATE_BINDING", raised.exception.code)
        schema = json.loads((ROOT / "schemas/v2.50/state-ledger.schema.json").read_text())
        self.assertIn(
            "authorization_lineage_sha256",
            schema["$defs"]["bindings"]["required"],
        )

    def test_completion_rejects_open_gaps_and_unknown_status_and_exposes_released(self) -> None:
        open_gap = completion_projection(
            development_task_states={"P00": "accepted"},
            runtime_task_states={"P11": "pending"},
            release_task_states={"P12": "pending"},
            development_denominator="passed",
            git_scope_state="passed",
            runtime_observation_state="not_run",
            business_validation_state="not_run",
            release_gate_state="not_run",
            internal_open_gap_count=1,
        )
        self.assertFalse(open_gap["engineering_complete"])
        with self.assertRaises(StateReducerError) as raised:
            completion_projection(
                development_task_states={"P00": "accepted"},
                runtime_task_states={"P11": "pending"},
                release_task_states={"P12": "pending"},
                development_denominator="passed",
                git_scope_state="passed",
                runtime_observation_state="unknown",
                business_validation_state="not_run",
                release_gate_state="not_run",
            )
        self.assertEqual("E_V263_COMPLETION_STATUS", raised.exception.code)
        released = completion_projection(
            development_task_states={"P00": "accepted"},
            runtime_task_states={"P11": "accepted"},
            release_task_states={"P12": "accepted"},
            development_denominator="passed",
            git_scope_state="passed",
            runtime_observation_state="passed",
            business_validation_state="passed",
            release_gate_state="passed",
            release_execution_state="passed",
        )
        self.assertFalse(released["authoritative"])
        self.assertEqual("unverified_compatibility", released["authority"])
        self.assertFalse(released["release_ready"])
        self.assertFalse(released["release_published"])
        self.assertFalse(released["installation_current"])

    def test_blocker_rebuilds_dependency_map_from_canonical_tasks(self) -> None:
        compiled = compile_task_plan(
            _plan(
                [_task("A"), _task("B", depends_on=["A"])],
                {"development": ["A", "B"], "runtime": [], "release": []},
            )
        )
        tampered = copy.deepcopy(compiled)
        tampered["dependency_map"] = {"A": [], "B": []}
        tampered["receipt_digest"] = _canonical_digest(
            {key: value for key, value in tampered.items() if key != "receipt_digest"}
        )
        with self.assertRaises(TaskPlanError) as raised:
            compile_blocker_receipt(
                tampered,
                blocked_task_ids=["A"],
                task_states={"A": "pending", "B": "pending"},
                blocker={
                    "blocker_id": "BLOCK-CORE-AUDIT",
                    "blocker_type": "external_service",
                    "external_owner": "provider-team",
                    "first_observed_at": "2026-08-12T00:00:00Z",
                    "status": "open",
                    "evidence": [{"receipt_id": "EV-1"}],
                    "recovery_condition": "service is healthy",
                    "revalidation_method": "rerun probe",
                },
            )
        self.assertEqual("E_V263_BLOCKER_PLAN", raised.exception.code)

    def test_working_state_digest_binds_dirty_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = self._repo(Path(temporary))
            baseline = capture_git_baseline(repo)
            target = repo / "owned/allowed.txt"
            target.write_text("first change\n", encoding="utf-8")
            first = compile_git_change_receipt(repo, baseline, {"P08": ["owned/**"]})
            target.write_text("second change\n", encoding="utf-8")
            second = compile_git_change_receipt(repo, baseline, {"P08": ["owned/**"]})
            self.assertRegex(first["working_state_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotEqual(
                first["working_state_sha256"], second["working_state_sha256"]
            )
            self.assertEqual(first["observed_tree"], second["observed_tree"])
            schema = json.loads(
                (ROOT / "schemas/v2.50/git-change-receipt.schema.json").read_text()
            )
            self.assertIn("working_state_sha256", schema["required"])

    def test_phase_dependencies_only_reference_same_or_earlier_phase(self) -> None:
        invalid = _plan(
            [_task("D", depends_on=["R"]), _task("R")],
            {"development": ["D"], "runtime": [], "release": ["R"]},
        )
        with self.assertRaises(TaskPlanError) as raised:
            compile_task_plan(invalid)
        self.assertEqual("E_V263_PHASE_DEPENDENCY_ORDER", raised.exception.code)

    @staticmethod
    def _repo(path: Path) -> Path:
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Goal Teams Test"], cwd=path, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "goal-teams@example.invalid"],
            cwd=path,
            check=True,
        )
        (path / "owned").mkdir()
        (path / "owned/allowed.txt").write_text("original\n", encoding="utf-8")
        (path / "owned/forbidden.txt").write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=path, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=path, check=True)
        return path


if __name__ == "__main__":
    unittest.main()
