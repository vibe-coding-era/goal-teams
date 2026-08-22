from __future__ import annotations

import copy
import hashlib
import json
import unittest

from scripts.v250.state_reducer import (
    StateReducerError,
    completion_projection,
    make_state_event,
    make_validation_receipt,
    reduce_budget_events,
    reduce_state_events,
    validate_state_projection,
)
from scripts.v250.task_plan_compiler import (
    compile_task_plan,
    validate_compiled_task_plan,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _task(task_id: str, consumer: str) -> dict[str, object]:
    return {
        "task_id": task_id,
        "requirement_refs": ["REQ-V263-COMPLETION"],
        "consumer_refs": [consumer],
        "admission": {
            "current_consumer_confirmed": True,
            "observable_acceptance_defined": True,
            "scope_locked": True,
            "budget_bound": True,
            "exit_condition_frozen": True,
            "evidence_refs": [f"receipt:demand:{task_id}"],
        },
        "owner": f"owner:{task_id}",
        "validator": f"validator:{task_id}",
        "scope_allowlist": [f"scope/{task_id}/**"],
        "forbidden_scope": ["README.md"],
        "depends_on": [],
        "budget_wu": 2,
        "attempt_budget": 2,
        "revalidation_budget": 1,
        "inputs": [{"input_id": f"input:{task_id}"}],
        "outputs": [
            {
                "output_id": f"output:{task_id}",
                "consumer_refs": [consumer],
                "required": True,
            }
        ],
        "verification": [
            {
                "verification_id": f"verification:{task_id}",
                "verification_type": "test",
                "method": f"run {task_id} assertions",
                "expected_result": "all assertions pass",
                "evidence_refs": [f"receipt:test-contract:{task_id}"],
            }
        ],
        "business_oracle": {
            "oracle_id": f"oracle:{task_id}",
            "oracle_type": "consumer_acceptance",
            "acceptance_criteria": [f"{task_id} observable outcome"],
            "evidence_refs": [f"receipt:oracle:{task_id}"],
        },
        "exit_condition": {
            "exit_id": f"exit:{task_id}",
            "exit_type": "receipts_closed",
            "required_receipt_types": ["task_verification", "task_exit"],
            "on_budget_exhaustion": "blocked",
        },
        "failure_artifacts": [f"failure:{task_id}"],
    }


class V263CompletionAuthorityTests(unittest.TestCase):
    def _context(self) -> dict[str, object]:
        tasks = [
            _task("P01", "consumer:engineering"),
            _task("P11", "consumer:runtime"),
            _task("P12", "consumer:release"),
        ]
        plan = compile_task_plan(
            {
                "schema_version": "goal-teams-task-plan-v1",
                "plan_id": "GT-V263-COMPLETION",
                "plan_revision": 1,
                "tasks": tasks,
                "phase_exact_sets": {
                    "development": ["P01"],
                    "runtime": ["P11"],
                    "release": ["P12"],
                },
            }
        )
        plan_validation = validate_compiled_task_plan(plan)
        bindings = {
            "source_sha256": "1" * 64,
            "route_sha256": "2" * 64,
            "contract_sha256": "3" * 64,
            "task_exact_set_sha256": plan["task_exact_set_digest"],
            "environment_sha256": "5" * 64,
            "authorization_lineage_sha256": "6" * 64,
        }
        receipts = []
        events = []
        previous = "0" * 64
        revision = 0
        seq = 0
        for task in tasks:
            task_id = str(task["task_id"])
            verification = make_validation_receipt(
                receipt_type="task_verification",
                subject_id=task_id,
                status="passed",
                bindings=bindings,
                evidence_refs=[f"receipt:verification-run:{task_id}"],
                observations={
                    "task_id": task_id,
                    "verification_contract_sha256": _digest(task["verification"]),
                    "outcome": "passed",
                },
                validator_identity=f"validator:{task_id}",
                issued_at="2026-08-12T17:00:00Z",
            )
            exit_receipt = make_validation_receipt(
                receipt_type="task_exit",
                subject_id=task_id,
                status="passed",
                bindings=bindings,
                evidence_refs=[f"receipt:exit-check:{task_id}"],
                observations={
                    "task_id": task_id,
                    "exit_condition_sha256": _digest(task["exit_condition"]),
                    "verification_receipt_sha256": verification["receipt_digest"],
                    "condition_met": True,
                },
                validator_identity=f"validator:{task_id}",
                issued_at="2026-08-12T17:00:01Z",
            )
            receipts.extend([verification, exit_receipt])
            seq += 1
            active = make_state_event(
                event_id=f"event-{seq}",
                event_seq=seq,
                event_type="task.transition",
                axis="task",
                entity_id=task_id,
                previous_event_sha256=previous,
                cas_base_revision=revision,
                before_state="pending",
                requested_state="active",
                bindings=bindings,
                actor_identity="goal_lead",
                actor_relationship="authorized_writer",
                evidence_refs=[f"receipt:task-start:{task_id}"],
                occurred_at=f"2026-08-12T17:01:{seq:02d}Z",
            )
            events.append(active)
            previous = str(active["event_sha256"])
            revision += 1
            seq += 1
            accepted = make_state_event(
                event_id=f"event-{seq}",
                event_seq=seq,
                event_type="task.transition",
                axis="task",
                entity_id=task_id,
                previous_event_sha256=previous,
                cas_base_revision=revision,
                before_state="active",
                requested_state="accepted",
                bindings=bindings,
                actor_identity="goal_lead",
                actor_relationship="authorized_writer",
                evidence_refs=[
                    f"sha256:{verification['receipt_digest']}",
                    f"sha256:{exit_receipt['receipt_digest']}",
                ],
                occurred_at=f"2026-08-12T17:01:{seq:02d}Z",
            )
            events.append(accepted)
            previous = str(accepted["event_sha256"])
            revision += 1
        state_projection = reduce_state_events(
            events,
            expected_bindings=bindings,
            validation_receipts=receipts,
            compiled_task_plan=plan,
            task_plan_validation_receipt=plan_validation,
        )
        state_validation = validate_state_projection(
            events,
            expected_bindings=bindings,
            supplied_projection=state_projection,
            validation_receipts=receipts,
            compiled_task_plan=plan,
            task_plan_validation_receipt=plan_validation,
        )
        budget_projection = reduce_budget_events(plan, plan_validation, [])
        return {
            "tasks": tasks,
            "plan": plan,
            "plan_validation": plan_validation,
            "bindings": bindings,
            "receipts": receipts,
            "events": events,
            "state_projection": state_projection,
            "state_validation": state_validation,
            "budget_projection": budget_projection,
        }

    def _axis_receipt(
        self,
        context: dict[str, object],
        receipt_type: str,
        subject_id: str,
        observations: dict[str, object],
    ) -> dict[str, object]:
        return make_validation_receipt(
            receipt_type=receipt_type,
            subject_id=subject_id,
            status="passed",
            bindings=context["bindings"],
            evidence_refs=[f"receipt:evidence:{receipt_type}"],
            observations=observations,
            validator_identity=f"validator:{receipt_type}",
            issued_at="2026-08-12T17:30:00Z",
        )

    def _base_axis_receipts(self, context: dict[str, object]) -> list[dict[str, object]]:
        return [
            self._axis_receipt(
                context,
                "development_denominator",
                "development",
                {
                    "phase": "development",
                    "exact_task_ids": ["P01"],
                    "denominator_sha256": "7" * 64,
                },
            ),
            self._axis_receipt(
                context,
                "git_scope",
                str(context["plan"]["plan_id"]),
                {
                    "baseline_sha256": "8" * 64,
                    "working_state_sha256": "9" * 64,
                    "in_scope": True,
                },
            ),
            self._axis_receipt(
                context,
                "runtime_observation",
                "runtime",
                {
                    "exact_task_ids": ["P11"],
                    "observation_sha256": "a" * 64,
                    "host_execution_id": "host-run-263",
                    "fresh": True,
                },
            ),
            self._axis_receipt(
                context,
                "business_validation",
                str(context["plan"]["plan_id"]),
                {
                    "oracle_contract_sha256": "b" * 64,
                    "observation_sha256": "c" * 64,
                    "oracle_identity": "business-owner",
                    "accepted": True,
                },
            ),
            self._axis_receipt(
                context,
                "release_gate",
                "release",
                {
                    "exact_task_ids": ["P12"],
                    "frozen_identity_sha256": "d" * 64,
                    "gate_receipt_sha256": "e" * 64,
                },
            ),
            self._axis_receipt(
                context,
                "open_gap_audit",
                str(context["plan"]["plan_id"]),
                {"open_gap_ids": []},
            ),
        ]

    def _completion(
        self, context: dict[str, object], receipts: list[dict[str, object]]
    ) -> dict[str, object]:
        return completion_projection(
            compiled_task_plan=context["plan"],
            task_plan_validation_receipt=context["plan_validation"],
            state_events=context["events"],
            state_projection=context["state_projection"],
            state_projection_validation_receipt=context["state_validation"],
            budget_events=[],
            budget_projection=context["budget_projection"],
            validation_receipts=[*context["receipts"], *receipts],
        )

    def test_release_ready_publication_and_installation_are_independent_axes(self) -> None:
        context = self._context()
        base = self._base_axis_receipts(context)
        ready = self._completion(context, base)
        self.assertTrue(ready["authoritative"])
        self.assertTrue(ready["engineering_complete"])
        self.assertTrue(ready["runtime_complete"])
        self.assertTrue(ready["business_validated"])
        self.assertTrue(ready["release_ready"])
        self.assertFalse(ready["release_published"])
        self.assertFalse(ready["installation_current"])

        publication = self._axis_receipt(
            context,
            "release_publication",
            "V2.65",
            {
                "tag_name": "V2.65",
                "release_id": "release-263",
                "expected_tag_target_sha256": "1" * 64,
                "observed_tag_target_sha256": "1" * 64,
                "expected_asset_ids": ["goal-teams-V2.65.tar.gz"],
                "observed_asset_ids": ["goal-teams-V2.65.tar.gz"],
            },
        )
        published = self._completion(context, [*base, publication])
        self.assertTrue(published["release_published"])
        self.assertFalse(published["installation_current"])

        installation = self._axis_receipt(
            context,
            "installation_readback",
            "canonical-goal-teams",
            {
                "expected_source_sha256": "1" * 64,
                "observed_source_sha256": "1" * 64,
                "expected_artifact_sha256": "f" * 64,
                "observed_artifact_sha256": "f" * 64,
                "expected_version": "V2.65",
                "observed_version": "V2.65",
                "expected_canonical_path": "/Users/Rou/.codex/skills/goal-teams",
                "observed_canonical_path": "/Users/Rou/.codex/skills/goal-teams",
            },
        )
        installed = self._completion(context, [*base, publication, installation])
        self.assertTrue(installed["release_published"])
        self.assertTrue(installed["installation_current"])

    def test_compiled_plan_projection_and_receipt_tampering_fail_closed(self) -> None:
        context = self._context()
        base = self._base_axis_receipts(context)
        cases = []

        tampered_plan = copy.deepcopy(context)
        tampered_plan["plan"]["phase_exact_sets"]["development"] = ["FAKE"]
        cases.append(tampered_plan)

        tampered_projection = copy.deepcopy(context)
        tampered_projection["state_projection"]["axes"]["task"]["FAKE"] = "accepted"
        tampered_projection["state_projection"]["projection_sha256"] = _digest(
            {
                key: value
                for key, value in tampered_projection["state_projection"].items()
                if key != "projection_sha256"
            }
        )
        cases.append(tampered_projection)

        tampered_receipt = copy.deepcopy(context)
        tampered_receipt["state_validation"]["projection_sha256"] = "f" * 64
        tampered_receipt["state_validation"]["receipt_digest"] = _digest(
            {
                key: value
                for key, value in tampered_receipt["state_validation"].items()
                if key != "receipt_digest"
            }
        )
        cases.append(tampered_receipt)

        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises(
                (StateReducerError, ValueError)
            ):
                self._completion(candidate, base)

    def test_missing_or_replaced_exact_task_ids_cannot_complete(self) -> None:
        context = self._context()
        base = self._base_axis_receipts(context)
        for replacement in (None, "FAKE"):
            events = [
                event
                for event in context["events"]
                if event["entity_id"] != "P12"
            ]
            if replacement:
                previous = events[-1]["event_sha256"]
                events.append(
                    make_state_event(
                        event_id="fake-event",
                        event_seq=len(events) + 1,
                        event_type="task.transition",
                        axis="task",
                        entity_id=replacement,
                        previous_event_sha256=previous,
                        cas_base_revision=len(events),
                        before_state="pending",
                        requested_state="active",
                        bindings=context["bindings"],
                        actor_identity="goal_lead",
                        actor_relationship="authorized_writer",
                        evidence_refs=["receipt:fake"],
                        occurred_at="2026-08-12T18:00:00Z",
                    )
                )
            projection = reduce_state_events(
                events,
                expected_bindings=context["bindings"],
                validation_receipts=context["receipts"],
                compiled_task_plan=context["plan"],
                task_plan_validation_receipt=context["plan_validation"],
            )
            validation = validate_state_projection(
                events,
                expected_bindings=context["bindings"],
                supplied_projection=projection,
                validation_receipts=context["receipts"],
                compiled_task_plan=context["plan"],
                task_plan_validation_receipt=context["plan_validation"],
            )
            candidate = {**context, "events": events, "state_projection": projection, "state_validation": validation}
            with self.subTest(replacement=replacement), self.assertRaises(StateReducerError) as raised:
                self._completion(candidate, base)
            self.assertEqual("E_V263_COMPLETION_TASK_EXACT_SET", raised.exception.code)

    def test_free_form_passed_strings_are_compatibility_only_and_never_complete(self) -> None:
        legacy = completion_projection(
            development_task_states={"P01": "accepted"},
            runtime_task_states={"P11": "accepted"},
            release_task_states={"P12": "accepted"},
            development_denominator="passed",
            git_scope_state="passed",
            runtime_observation_state="passed",
            business_validation_state="passed",
            release_gate_state="passed",
            release_execution_state="passed",
        )
        self.assertFalse(legacy["authoritative"])
        for axis in (
            "engineering_complete",
            "runtime_complete",
            "business_validated",
            "release_ready",
            "release_published",
            "installation_current",
        ):
            self.assertFalse(legacy[axis], axis)


if __name__ == "__main__":
    unittest.main()
