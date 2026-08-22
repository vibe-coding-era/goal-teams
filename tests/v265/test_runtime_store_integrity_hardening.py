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


CONTRACT_SHA256 = "e60d0f90db023249639aafba88404f6584ffd4ffafbe252aab49f9d22c7521ce"
PLAN_REVISION = 1
TASK_EXACT_SET_SHA256 = "bdde25c367a8264b324133f36f47eaa113dfe9dacbcdd21ab704590b9f43e8c3"
ZERO_SHA256 = "0" * 64


class TestV265RuntimeStoreIntegrityHardening(unittest.TestCase):
    """Immutable failure-injection denominator for the local SQLite Store."""

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

    def _open(self, name: str, *, busy_timeout_ms: int = 5000) -> SQLiteRuntimeStore:
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
            created_at="2026-08-22T14:00:00Z",
        )

    def _schema_snapshot(self, name: str) -> dict[str, object]:
        connection = self._connection(name)
        try:
            objects = [
                tuple(row)
                for row in connection.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
                ).fetchall()
            ]
            tables = [row[1] for row in objects if row[0] == "table"]
            details: dict[str, object] = {}
            for table in tables:
                indexes = [
                    tuple(row)
                    for row in connection.execute(
                        f"PRAGMA index_list('{table}')"
                    ).fetchall()
                ]
                details[table] = {
                    "table_info": [
                        tuple(row)
                        for row in connection.execute(
                            f"PRAGMA table_info('{table}')"
                        ).fetchall()
                    ],
                    "foreign_keys": [
                        tuple(row)
                        for row in connection.execute(
                            f"PRAGMA foreign_key_list('{table}')"
                        ).fetchall()
                    ],
                    "indexes": indexes,
                    "index_info": {
                        row[1]: [
                            tuple(item)
                            for item in connection.execute(
                                f"PRAGMA index_info('{row[1]}')"
                            ).fetchall()
                        ]
                        for row in indexes
                    },
                }
            return {
                "user_version": int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                ),
                "objects": objects,
                "details": details,
            }
        finally:
            connection.close()

    def _event(
        self,
        store: SQLiteRuntimeStore,
        run_id: str,
        *,
        event_type: str,
        node_id: str | None,
        attempt: int,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        head = store.read_run_head(run_id)
        sequence = int(head["revision"]) + 1
        return make_graph_event(
            run_id=run_id,
            event_id=f"EVENT-{run_id}-{sequence}",
            event_seq=sequence,
            event_type=event_type,
            node_id=node_id,
            attempt=attempt,
            cas_base_revision=sequence - 1,
            previous_event_sha256=str(head["last_event_sha256"]),
            bindings=self.bindings,
            payload=copy.deepcopy(dict(payload)),
            evidence_refs=[f"evidence:store-integrity:{sequence}"],
            actor_identity="runtime_controller",
            actor_relationship="authorized_writer",
            occurred_at=f"2026-08-22T14:00:{sequence:02d}Z",
        )

    def _ready(self, store: SQLiteRuntimeStore, run_id: str) -> dict[str, Any]:
        return self._event(
            store,
            run_id,
            event_type="node.ready",
            node_id="STORE",
            attempt=1,
            payload={
                "satisfied_edge_ids": [],
                "fan_in_mode": "root",
                "required_edge_count": 0,
                "satisfied_edge_count": 0,
            },
        )

    def _assert_schema_open_error(self, name: str) -> None:
        try:
            unexpected = SQLiteRuntimeStore(
                self._path(name), runtime_root=self.runtime_root
            )
        except RuntimeStoreError as exc:
            self.assertEqual("E_V265_STORE_SCHEMA", exc.code)
        except Exception as exc:
            self.fail(f"E_TEST_V265_SCHEMA_EXCEPTION:{type(exc).__name__}:{exc}")
        else:
            self.opened.append(unexpected)
            self.fail("E_TEST_V265_INVALID_SCHEMA_ACCEPTED")

    def test_existing_old_user_version_is_rejected_without_overwrite(self) -> None:
        self.assertRegex(CONTRACT_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(1, PLAN_REVISION)
        self.assertRegex(TASK_EXACT_SET_SHA256, r"^[0-9a-f]{64}$")
        name = "old-version.sqlite3"
        initial = self._open(name)
        initial.close()
        self._execute(name, "PRAGMA user_version=264")

        accepted = False
        try:
            unexpected = SQLiteRuntimeStore(
                self._path(name), runtime_root=self.runtime_root
            )
        except RuntimeStoreError as exc:
            self.assertEqual("E_V265_STORE_SCHEMA", exc.code)
        except Exception as exc:
            self.fail(f"E_TEST_V265_SCHEMA_EXCEPTION:{type(exc).__name__}:{exc}")
        else:
            accepted = True
            self.opened.append(unexpected)
        connection = self._connection(name)
        try:
            observed = int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
        self.assertEqual(264, observed, "existing user_version was overwritten")
        self.assertFalse(accepted, "existing old user_version database was accepted")

    def test_weak_existing_ddl_is_rejected_before_mutation(self) -> None:
        name = "weak-ddl.sqlite3"
        connection = self._connection(name)
        try:
            connection.execute("CREATE TABLE runs(run_id TEXT)")
            connection.execute("PRAGMA user_version=265")
            connection.commit()
        finally:
            connection.close()
        before = self._schema_snapshot(name)
        self._assert_schema_open_error(name)
        self.assertEqual(
            before,
            self._schema_snapshot(name),
            "invalid existing database was mutated before rejection",
        )

    def test_every_extra_manifest_object_is_rejected(self) -> None:
        for kind in ("table", "index", "trigger", "view"):
            name = f"extra-{kind}.sqlite3"
            initial = self._open(name)
            initial.close()
            if kind == "table":
                statement = "CREATE TABLE unexpected_manifest_table(value TEXT)"
            elif kind == "index":
                statement = (
                    "CREATE INDEX unexpected_manifest_index ON runs(updated_at)"
                )
            elif kind == "trigger":
                statement = """
                CREATE TRIGGER unexpected_manifest_trigger
                AFTER INSERT ON events BEGIN SELECT 1; END
                """
            else:
                statement = (
                    "CREATE VIEW unexpected_manifest_view AS "
                    "SELECT run_id,revision FROM runs"
                )
            self._execute(name, statement)
            with self.subTest(kind=kind):
                self._assert_schema_open_error(name)

    def test_verify_cross_checks_every_redundant_event_column(self) -> None:
        mutations: tuple[tuple[str, str, object], ...] = (
            ("run_id", "run_id", "RUN-ROW-OTHER"),
            ("event_seq", "event_seq", 2),
            ("event_id", "event_id", "EVENT-FORGED"),
            ("event_type", "event_type", "node.ready"),
            ("node_id", "node_id", "STORE"),
            ("attempt", "attempt", 1),
            ("previous_hash", "previous_event_sha256", "f" * 64),
            ("event_hash", "event_sha256", "e" * 64),
            ("occurred_at", "occurred_at", "2026-08-22T14:59:59Z"),
        )
        for label, column, value in mutations:
            name = f"event-column-{label}.sqlite3"
            run_id = f"RUN-COLUMN-{label.upper()}"
            store = self._open(name)
            self._create(store, run_id)
            self._execute(
                name,
                f"UPDATE events SET {column}=? WHERE run_id=? AND event_seq=1",
                (value, run_id),
            )
            with self.subTest(column=column):
                try:
                    store.verify_run(run_id)
                except RuntimeStoreError as exc:
                    self.assertEqual("E_V265_STORE_CORRUPT", exc.code)
                except Exception as exc:
                    self.fail(
                        f"E_TEST_V265_EVENT_COLUMN_EXCEPTION:{column}:{type(exc).__name__}:{exc}"
                    )
                else:
                    self.fail(f"E_TEST_V265_EVENT_COLUMN_TAMPER_ACCEPTED:{column}")

    def test_append_postcommit_event_row_corruption_returns_readback_error(self) -> None:
        name = "append-event-readback.sqlite3"
        run_id = "RUN-APPEND-EVENT-READBACK"
        store = self._open(name)
        self._create(store, run_id)
        self._execute(
            name,
            """
            CREATE TRIGGER corrupt_appended_event
            AFTER INSERT ON events WHEN NEW.event_seq=2
            BEGIN
              UPDATE events SET event_id='EVENT-CORRUPTED'
               WHERE run_id=NEW.run_id AND event_seq=NEW.event_seq;
            END
            """,
        )
        event = self._ready(store, run_id)
        with self.assertRaises(RuntimeStoreError) as caught:
            store.append_event(run_id, event, expected_revision=1)
        self.assertEqual("E_V265_STORE_READBACK", caught.exception.code)

    def test_create_run_genesis_event_corruption_returns_readback_error(self) -> None:
        name = "genesis-event-readback.sqlite3"
        run_id = "RUN-GENESIS-EVENT-READBACK"
        store = self._open(name)
        self._execute(
            name,
            """
            CREATE TRIGGER corrupt_genesis_event
            AFTER INSERT ON events WHEN NEW.event_seq=1
            BEGIN
              UPDATE events SET event_id='EVENT-GENESIS-CORRUPTED'
               WHERE run_id=NEW.run_id AND event_seq=NEW.event_seq;
            END
            """,
        )
        with self.assertRaises(RuntimeStoreError) as caught:
            self._create(store, run_id)
        self.assertEqual("E_V265_STORE_READBACK", caught.exception.code)

    def test_append_postcommit_all_affected_indexes_are_read_back(self) -> None:
        for target in ("attempt", "lease"):
            name = f"append-{target}-readback.sqlite3"
            run_id = f"RUN-APPEND-{target.upper()}-READBACK"
            store = self._open(name)
            self._create(store, run_id)
            ready = self._ready(store, run_id)
            store.append_event(run_id, ready, expected_revision=1)
            if target == "attempt":
                statement = """
                CREATE TRIGGER corrupt_claim_attempt
                AFTER INSERT ON leases
                BEGIN
                  UPDATE attempts SET state='forged'
                   WHERE run_id=NEW.run_id AND node_id=NEW.node_id
                     AND attempt=NEW.attempt;
                END
                """
            else:
                statement = """
                CREATE TRIGGER corrupt_claim_lease
                AFTER INSERT ON leases
                BEGIN
                  UPDATE leases SET state='forged'
                   WHERE run_id=NEW.run_id AND node_id=NEW.node_id
                     AND attempt=NEW.attempt;
                END
                """
            self._execute(name, statement)
            claimed = self._event(
                store,
                run_id,
                event_type="node.claimed",
                node_id="STORE",
                attempt=1,
                payload={
                    "worker_id": "WORKER-STORE-1",
                    "lease_id": "LEASE-STORE-1",
                    "lease_expires_at": "2026-08-22T14:10:00Z",
                },
            )
            with self.subTest(index=target):
                with self.assertRaises(RuntimeStoreError) as caught:
                    store.append_event(run_id, claimed, expected_revision=2)
                self.assertEqual("E_V265_STORE_READBACK", caught.exception.code)

    def test_checkpoint_busy_maps_without_raw_sqlite_exception(self) -> None:
        name = "checkpoint-busy.sqlite3"
        run_id = "RUN-CHECKPOINT-BUSY"
        store = self._open(name, busy_timeout_ms=25)
        self._create(store, run_id)
        projection = reduce_graph_events(
            self.graph,
            store.load_events(run_id),
            expected_bindings=self.bindings,
        )
        blocker = self._connection(name, timeout=0)
        try:
            blocker.execute("BEGIN IMMEDIATE")
            try:
                store.save_checkpoint(
                    run_id,
                    projection,
                    expected_revision=1,
                    created_at="2026-08-22T14:00:01Z",
                )
            except RuntimeStoreError as exc:
                self.assertEqual("E_V265_STORE_BUSY", exc.code)
            except Exception as exc:
                self.fail(
                    f"E_TEST_V265_CHECKPOINT_BUSY_EXCEPTION:{type(exc).__name__}:{exc}"
                )
            else:
                self.fail("E_TEST_V265_CHECKPOINT_BUSY_ACCEPTED")
        finally:
            blocker.rollback()
            blocker.close()

    def test_blob_event_json_is_store_corruption(self) -> None:
        name = "blob-event-json.sqlite3"
        run_id = "RUN-BLOB-EVENT"
        store = self._open(name)
        self._create(store, run_id)
        connection = self._connection(name)
        try:
            raw = connection.execute(
                "SELECT event_json FROM events WHERE run_id=? AND event_seq=1",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE events SET event_json=? WHERE run_id=? AND event_seq=1",
                (sqlite3.Binary(raw.encode("utf-8")), run_id),
            )
            connection.commit()
        finally:
            connection.close()
        try:
            store.load_events(run_id)
        except RuntimeStoreError as exc:
            self.assertEqual("E_V265_STORE_CORRUPT", exc.code)
        except Exception as exc:
            self.fail(f"E_TEST_V265_BLOB_JSON_EXCEPTION:{type(exc).__name__}:{exc}")
        else:
            self.fail("E_TEST_V265_BLOB_EVENT_JSON_ACCEPTED")


if __name__ == "__main__":
    unittest.main()
