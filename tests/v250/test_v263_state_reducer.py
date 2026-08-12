from __future__ import annotations

import unittest

from scripts.v250.state_reducer import (
    StateReducerError,
    completion_projection,
    make_state_event,
    rebuild_projection,
    reduce_state_events,
)


BINDINGS = {
    "source_sha256": "a" * 64,
    "route_sha256": "b" * 64,
    "contract_sha256": "c" * 64,
    "task_exact_set_sha256": "d" * 64,
    "environment_sha256": "e" * 64,
}


class TestV263StateReducer(unittest.TestCase):
    def _event(
        self,
        *,
        seq: int,
        previous: str,
        revision: int,
        axis: str = "task",
        entity: str = "P01",
        before: str = "pending",
        requested: str = "active",
        writer: str = "goal_lead",
        bindings: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return make_state_event(
            event_id=f"event-{seq}",
            event_seq=seq,
            event_type=f"{axis}.transition",
            axis=axis,
            entity_id=entity,
            previous_event_sha256=previous,
            cas_base_revision=revision,
            before_state=before,
            requested_state=requested,
            bindings=bindings or BINDINGS,
            actor_identity=writer,
            actor_relationship="authorized_writer",
            evidence_refs=[f"sha256:{seq:064x}"],
            occurred_at=f"2026-08-12T14:00:{seq:02d}Z",
        )

    def test_reducer_accepts_hash_chained_cas_transitions_and_replays(self) -> None:
        first = self._event(seq=1, previous="0" * 64, revision=0)
        second = self._event(
            seq=2,
            previous=str(first["event_sha256"]),
            revision=1,
            before="active",
            requested="accepted",
        )
        projection = reduce_state_events([first, second], expected_bindings=BINDINGS)
        self.assertEqual(2, projection["revision"])
        self.assertEqual("accepted", projection["axes"]["task"]["P01"])
        rebuilt = rebuild_projection(
            [first, second],
            expected_bindings=BINDINGS,
            expected_projection_sha256=projection["projection_sha256"],
        )
        self.assertEqual(projection, rebuilt)

    def test_cas_conflict_binding_drift_illegal_axis_and_writer_fail_closed(self) -> None:
        first = self._event(seq=1, previous="0" * 64, revision=0)
        cases = {
            "cas": self._event(
                seq=2,
                previous=str(first["event_sha256"]),
                revision=0,
                before="active",
                requested="accepted",
            ),
            "binding": self._event(
                seq=2,
                previous=str(first["event_sha256"]),
                revision=1,
                before="active",
                requested="accepted",
                bindings={**BINDINGS, "source_sha256": "f" * 64},
            ),
            "cross_axis": self._event(
                seq=2,
                previous=str(first["event_sha256"]),
                revision=1,
                axis="goal",
                entity="goal",
                before="pending",
                requested="accepted",
            ),
            "writer": self._event(
                seq=2,
                previous=str(first["event_sha256"]),
                revision=1,
                before="active",
                requested="accepted",
                writer="implementation_member",
            ),
        }
        expected_codes = {
            "cas": "E_V263_STATE_CAS",
            "binding": "E_V263_STATE_BINDING",
            "cross_axis": "E_V263_STATE_TRANSITION",
            "writer": "E_V263_STATE_WRITER",
        }
        for name, event in cases.items():
            with self.subTest(name=name), self.assertRaises(StateReducerError) as ctx:
                reduce_state_events([first, event], expected_bindings=BINDINGS)
            self.assertEqual(expected_codes[name], ctx.exception.code)

    def test_projection_mismatch_is_invalid_and_completion_axes_are_orthogonal(self) -> None:
        first = self._event(seq=1, previous="0" * 64, revision=0)
        with self.assertRaises(StateReducerError) as ctx:
            rebuild_projection(
                [first],
                expected_bindings=BINDINGS,
                expected_projection_sha256="f" * 64,
            )
        self.assertEqual("E_V263_STATE_REPLAY_MISMATCH", ctx.exception.code)

        completion = completion_projection(
            development_task_states={"P00": "accepted", "P01": "accepted"},
            runtime_task_states={"P11": "pending"},
            release_task_states={"P12": "pending"},
            development_denominator="passed",
            git_scope_state="passed",
            runtime_observation_state="not_run",
            business_validation_state="not_run",
            release_gate_state="not_run",
        )
        self.assertFalse(completion["authoritative"])
        self.assertEqual("unverified_compatibility", completion["authority"])
        self.assertFalse(completion["engineering_complete"])
        self.assertFalse(completion["runtime_complete"])
        self.assertFalse(completion["business_validated"])
        self.assertFalse(completion["release_ready"])
        self.assertFalse(completion["release_published"])
        self.assertFalse(completion["installation_current"])


if __name__ == "__main__":
    unittest.main()
