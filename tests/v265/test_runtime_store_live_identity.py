from __future__ import annotations

import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

from scripts.v265.graph_runtime import make_graph_event, reduce_graph_events
from scripts.v265.runtime_store import RuntimeStoreError, SQLiteRuntimeStore
from tests.v265.test_runtime_store_atomicity import _bindings, _compiled_graph


CONTRACT_SHA256 = "959a14159a51a881f32d697a2364c95492f2bc1db12e2c3ad242f645d364f186"
PLAN_REVISION = 1
TASK_EXACT_SET_SHA256 = "0f49220bf570a557869802aaa3b9b653bd35ab36b08be91f8cea8c9c5e8f5e33"


class TestV265RuntimeStoreLiveIdentity(unittest.TestCase):
    """Immutable Red denominator for live RunHead and SQLite identity checks."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp.name).resolve()
        self.graph = _compiled_graph()
        self.bindings = _bindings(self.graph)
        self.opened: list[SQLiteRuntimeStore] = []

    def tearDown(self) -> None:
        for store in reversed(self.opened):
            try:
                store.close()
            except Exception:
                pass
        self.temp.cleanup()

    def _path(self, name: str) -> Path:
        return self.runtime_root / name

    def _open(self, name: str, *, busy_timeout_ms: int = 250) -> SQLiteRuntimeStore:
        store = SQLiteRuntimeStore(
            self._path(name),
            runtime_root=self.runtime_root,
            busy_timeout_ms=busy_timeout_ms,
        )
        self.opened.append(store)
        return store

    def _connection(self, name: str, *, timeout: float = 5.0) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path(name)), timeout=timeout)

    def _execute(
        self,
        name: str,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> None:
        connection = self._connection(name)
        try:
            connection.execute(statement, parameters)
            connection.commit()
        finally:
            connection.close()

    def _create(self, store: SQLiteRuntimeStore, run_id: str) -> None:
        store.create_run(
            run_id,
            self.graph,
            self.bindings,
            created_at="2026-08-22T15:00:00Z",
        )

    def _ready(self, store: SQLiteRuntimeStore, run_id: str) -> dict[str, Any]:
        head = store.read_run_head(run_id)
        sequence = int(head["revision"]) + 1
        return make_graph_event(
            run_id=run_id,
            event_id=f"EVENT-{run_id}-{sequence}",
            event_seq=sequence,
            event_type="node.ready",
            node_id="STORE",
            attempt=1,
            cas_base_revision=sequence - 1,
            previous_event_sha256=str(head["last_event_sha256"]),
            bindings=self.bindings,
            payload={
                "satisfied_edge_ids": [],
                "fan_in_mode": "root",
                "required_edge_count": 0,
                "satisfied_edge_count": 0,
            },
            evidence_refs=["evidence:store-live:ready"],
            actor_identity="runtime_controller",
            actor_relationship="authorized_writer",
            occurred_at="2026-08-22T15:00:02Z",
        )

    def _projection(self, store: SQLiteRuntimeStore, run_id: str) -> dict[str, Any]:
        return reduce_graph_events(
            self.graph,
            store.load_events(run_id),
            expected_bindings=self.bindings,
        )

    def _assert_error(
        self,
        operation: Any,
        code: str,
        *,
        label: str,
    ) -> None:
        try:
            result = operation()
        except RuntimeStoreError as exc:
            self.assertEqual(code, exc.code)
        except Exception as exc:
            self.fail(f"E_TEST_V265_{label}_EXCEPTION:{type(exc).__name__}:{exc}")
        else:
            self.fail(f"E_TEST_V265_{label}_ACCEPTED:{result!r}")

    def test_verify_binds_created_and_updated_to_first_and_last_event(self) -> None:
        self.assertRegex(CONTRACT_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(1, PLAN_REVISION)
        self.assertRegex(TASK_EXACT_SET_SHA256, r"^[0-9a-f]{64}$")
        for column, forged in (
            ("created_at", "2026-08-22T14:59:59Z"),
            ("updated_at", "2026-08-22T15:00:01Z"),
        ):
            name = f"verify-{column}.sqlite3"
            run_id = f"RUN-VERIFY-{column.upper()}"
            store = self._open(name)
            self._create(store, run_id)
            self._execute(
                name,
                f"UPDATE runs SET {column}=? WHERE run_id=?",
                (forged, run_id),
            )
            with self.subTest(column=column):
                self._assert_error(
                    lambda: store.verify_run(run_id),
                    "E_V265_STORE_CORRUPT",
                    label=f"VERIFY_{column.upper()}",
                )

    def test_create_postcommit_created_at_corruption_is_readback_not_success(self) -> None:
        name = "create-created-at.sqlite3"
        run_id = "RUN-CREATE-CREATED-AT"
        store = self._open(name)
        self._execute(
            name,
            """
            CREATE TRIGGER corrupt_genesis_created_at
            AFTER INSERT ON events WHEN NEW.event_seq=1
            BEGIN
              UPDATE runs SET created_at='2026-08-22T14:59:59Z'
               WHERE run_id=NEW.run_id;
            END
            """,
        )
        self._assert_error(
            lambda: store.create_run(
                run_id,
                self.graph,
                self.bindings,
                created_at="2026-08-22T15:00:00Z",
            ),
            "E_V265_STORE_READBACK",
            label="CREATE_TIMESTAMP_READBACK",
        )
        self._execute(name, "DROP TRIGGER corrupt_genesis_created_at")
        self._assert_error(
            lambda: store.verify_run(run_id),
            "E_V265_STORE_CORRUPT",
            label="CREATE_TIMESTAMP_VERIFY",
        )

    def test_append_postcommit_updated_at_corruption_is_readback_not_success(self) -> None:
        name = "append-updated-at.sqlite3"
        run_id = "RUN-APPEND-UPDATED-AT"
        store = self._open(name)
        self._create(store, run_id)
        self._execute(
            name,
            """
            CREATE TRIGGER corrupt_append_updated_at
            AFTER UPDATE OF revision ON runs WHEN NEW.revision=2
            BEGIN
              UPDATE runs SET updated_at='2026-08-22T15:59:59Z'
               WHERE run_id=NEW.run_id;
            END
            """,
        )
        event = self._ready(store, run_id)
        self._assert_error(
            lambda: store.append_event(run_id, event, expected_revision=1),
            "E_V265_STORE_READBACK",
            label="APPEND_TIMESTAMP_READBACK",
        )
        self._execute(name, "DROP TRIGGER corrupt_append_updated_at")
        self._assert_error(
            lambda: store.verify_run(run_id),
            "E_V265_STORE_CORRUPT",
            label="APPEND_TIMESTAMP_VERIFY",
        )

    def test_active_user_version_drift_blocks_verify_and_append_without_receipt(self) -> None:
        for operation in ("verify", "append"):
            name = f"identity-{operation}.sqlite3"
            run_id = f"RUN-IDENTITY-{operation.upper()}"
            store = self._open(name)
            self._create(store, run_id)
            self._execute(name, "PRAGMA user_version=264")
            if operation == "verify":
                call = lambda: store.verify_run(run_id)
            else:
                event = self._ready(store, run_id)
                call = lambda: store.append_event(run_id, event, expected_revision=1)
            with self.subTest(operation=operation):
                self._assert_error(
                    call,
                    "E_V265_STORE_SCHEMA",
                    label=f"IDENTITY_{operation.upper()}",
                )

    def test_checkpoint_pre_read_schema_operational_error_is_mapped(self) -> None:
        name = "checkpoint-pre-read-schema.sqlite3"
        run_id = "RUN-CHECKPOINT-PRE-READ"
        store = self._open(name)
        self._create(store, run_id)
        projection = self._projection(store, run_id)
        connection = self._connection(name)
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DROP TABLE runs")
            connection.commit()
        finally:
            connection.close()
        self._assert_error(
            lambda: store.save_checkpoint(
                run_id,
                projection,
                expected_revision=1,
                created_at="2026-08-22T15:00:01Z",
            ),
            "E_V265_STORE_SCHEMA",
            label="CHECKPOINT_PRE_READ_SCHEMA",
        )


if __name__ == "__main__":
    unittest.main()
