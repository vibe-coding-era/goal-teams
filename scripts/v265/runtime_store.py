"""Durable standard-library SQLite RuntimeEventLog for V2.65."""

from __future__ import annotations

import copy
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping, Protocol

from scripts.v265.canonical import (
    canonical_json_bytes,
    canonical_sha256,
    is_int,
    is_non_empty_string,
    is_sha256,
    parse_json_bytes,
    require_utc_timestamp,
)
from scripts.v265.graph_runtime import (
    GraphRuntimeError,
    ZERO_SHA256,
    make_graph_event,
    reduce_graph_events,
    validate_runtime_graph_contract,
)


class RuntimeStoreError(ValueError):
    """Stable fail-closed store error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _error(code: str, message: str) -> RuntimeStoreError:
    return RuntimeStoreError(code, message)


class RuntimeEventLog(Protocol):
    def append_event(
        self, run_id: str, event: Mapping[str, Any], *, expected_revision: int
    ) -> dict[str, Any]: ...

    def load_events(self, run_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]: ...

    def read_run_head(self, run_id: str) -> dict[str, Any]: ...


DDL = """
CREATE TABLE IF NOT EXISTS runs(
  run_id TEXT PRIMARY KEY,
  graph_receipt_sha256 TEXT NOT NULL,
  compiled_graph_json TEXT NOT NULL,
  bindings_json TEXT NOT NULL,
  revision INTEGER NOT NULL,
  last_event_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
  run_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  event_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  node_id TEXT,
  attempt INTEGER NOT NULL,
  event_json TEXT NOT NULL,
  previous_event_sha256 TEXT NOT NULL,
  event_sha256 TEXT NOT NULL UNIQUE,
  occurred_at TEXT NOT NULL,
  PRIMARY KEY(run_id,event_seq),
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS attempts(
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  state TEXT NOT NULL,
  outcome TEXT,
  owner_run_id TEXT,
  validator_run_id TEXT,
  started_at TEXT,
  finished_at TEXT,
  PRIMARY KEY(run_id,node_id,attempt),
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS leases(
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  lease_id TEXT NOT NULL UNIQUE,
  worker_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  state TEXT NOT NULL,
  PRIMARY KEY(run_id,node_id),
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS checkpoints(
  run_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  projection_json TEXT NOT NULL,
  projection_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(run_id,revision),
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS idempotency_keys(
  run_id TEXT NOT NULL,
  key TEXT NOT NULL,
  node_id TEXT NOT NULL,
  state TEXT NOT NULL,
  result_digest TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(run_id,key),
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS hitl_interrupts(
  run_id TEXT NOT NULL,
  interrupt_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  gate_id TEXT NOT NULL,
  state TEXT NOT NULL,
  approval_receipt_sha256 TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(run_id,interrupt_id),
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
"""


def _canonical_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _load_json(raw: str, label: str) -> Any:
    if type(raw) is not str:
        raise _error("E_V265_STORE_CORRUPT", f"{label} is not stored as TEXT")
    try:
        encoded = raw.encode("utf-8")
        parsed = parse_json_bytes(encoded)
        if canonical_json_bytes(parsed) != encoded:
            raise ValueError("stored JSON is not canonical")
        return parsed
    except (TypeError, UnicodeError, ValueError) as exc:
        raise _error("E_V265_STORE_CORRUPT", f"{label} is invalid JSON") from exc


def _assert_no_symlink_components(path: Path, *, label: str) -> None:
    """Reject every existing symlink component in one absolute lexical path."""

    if not path.is_absolute():
        raise _error("E_V265_STORE_PATH", f"{label} must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise _error("E_V265_STORE_PATH", f"{label} crosses a symlink")
        if not current.exists():
            break


def _validate_projection_digest(projection: Mapping[str, Any], *, label: str) -> str:
    claimed = projection.get("projection_sha256")
    if not is_sha256(claimed) or canonical_sha256(
        {key: value for key, value in projection.items() if key != "projection_sha256"}
    ) != claimed:
        raise _error("E_V265_STORE_CORRUPT", f"{label} self-digest differs")
    return str(claimed)


def _pragma_rows(
    connection: sqlite3.Connection, pragma: str, object_name: str
) -> list[list[Any]]:
    quoted = object_name.replace("'", "''")
    rows = connection.execute(f"PRAGMA {pragma}('{quoted}')").fetchall()
    return [list(row) for row in rows]


def _schema_manifest(connection: sqlite3.Connection) -> dict[str, Any]:
    """Export the exact non-internal SQLite schema and derived PRAGMA shape."""

    object_rows = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE type IN ('table','index','trigger','view') "
        "AND substr(name,1,7) != 'sqlite_' ORDER BY type,name"
    ).fetchall()
    objects = [
        {
            "type": row[0],
            "name": row[1],
            "table_name": row[2],
            "sql": row[3],
        }
        for row in object_rows
    ]
    table_names = sorted(
        item["name"] for item in objects if item["type"] == "table"
    )
    tables: dict[str, Any] = {}
    for table_name in table_names:
        index_list = _pragma_rows(connection, "index_list", table_name)
        index_list.sort(key=lambda row: tuple(str(item) for item in row))
        index_info = {
            str(row[1]): _pragma_rows(connection, "index_info", str(row[1]))
            for row in index_list
        }
        tables[table_name] = {
            "table_info": _pragma_rows(connection, "table_info", table_name),
            "foreign_key_list": _pragma_rows(
                connection, "foreign_key_list", table_name
            ),
            "index_list": index_list,
            "index_info": {key: index_info[key] for key in sorted(index_info)},
        }
    return {"objects": objects, "tables": tables}


def _expected_schema_manifest() -> dict[str, Any]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(DDL)
        return _schema_manifest(connection)
    finally:
        connection.close()


class SQLiteRuntimeStore(RuntimeEventLog):
    """One-controller-thread SQLite event log with transactional indexes."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        runtime_root: Path | str,
        busy_timeout_ms: int = 5000,
    ) -> None:
        root = Path(runtime_root)
        if not root.is_absolute() or not root.exists() or not root.is_dir() or root.is_symlink():
            raise _error("E_V265_STORE_PATH", "runtime_root must be an existing absolute real directory")
        _assert_no_symlink_components(root, label="runtime_root")
        root_real = root.resolve(strict=True)
        if root_real != root:
            raise _error("E_V265_STORE_PATH", "runtime_root must use its canonical realpath")
        if not isinstance(busy_timeout_ms, int) or isinstance(busy_timeout_ms, bool) or busy_timeout_ms <= 0:
            raise _error("E_V265_STORE_SCHEMA", "busy_timeout_ms must be positive")
        if str(db_path) == ":memory:" or str(db_path).startswith("file:"):
            raise _error("E_V265_STORE_PATH", "SQLite memory and URI modes are not durable")
        path = Path(db_path)
        if not path.is_absolute():
            path = root_real / path
        if ".." in path.parts:
            raise _error("E_V265_STORE_PATH", "database path contains a parent traversal")
        try:
            relative = path.relative_to(root_real)
        except ValueError as exc:
            raise _error("E_V265_STORE_PATH", "database path escapes runtime_root") from exc
        parent = path.parent
        if not parent.exists() or not parent.is_dir():
            raise _error("E_V265_STORE_PATH", "database parent must already exist")
        current = root_real
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise _error("E_V265_STORE_PATH", "database path crosses a symlink")
            if current.exists() and current != path and not current.is_dir():
                raise _error("E_V265_STORE_PATH", "database path crosses a non-directory")
        path_real = path.resolve(strict=False)
        try:
            path_real.relative_to(root_real)
        except ValueError as exc:
            raise _error("E_V265_STORE_PATH", "database path escapes runtime_root") from exc
        if path.exists() and path.is_symlink():
            raise _error("E_V265_STORE_PATH", "database file is a symlink")

        self.db_path = path_real
        self._runtime_root = root_real
        self.busy_timeout_ms = busy_timeout_ms
        self._thread_id = threading.get_ident()
        self._lock = threading.RLock()
        try:
            self._connection = sqlite3.connect(
                str(self.db_path),
                timeout=busy_timeout_ms / 1000,
                isolation_level=None,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            initial_user_version = int(
                self._connection.execute("PRAGMA user_version").fetchone()[0]
            )
            initial_objects = self._connection.execute(
                "SELECT type,name FROM sqlite_master "
                "WHERE type IN ('table','index','trigger','view') "
                "AND substr(name,1,7) != 'sqlite_' LIMIT 1"
            ).fetchone()
            expected_manifest = _expected_schema_manifest()
            fresh = initial_user_version == 0 and initial_objects is None
            if not fresh:
                if initial_user_version != 265:
                    raise _error(
                        "E_V265_STORE_SCHEMA",
                        "existing SQLite user_version differs",
                    )
                if _schema_manifest(self._connection) != expected_manifest:
                    raise _error(
                        "E_V265_STORE_SCHEMA",
                        "existing SQLite schema manifest differs",
                    )

            journal = self._connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            if fresh:
                self._connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + DDL
                    + "\nPRAGMA user_version=265;\nCOMMIT;"
                )
            observed_manifest = _schema_manifest(self._connection)
            if observed_manifest != expected_manifest:
                raise _error(
                    "E_V265_STORE_SCHEMA", "SQLite schema manifest readback differs"
                )
        except RuntimeStoreError:
            try:
                self._connection.execute("ROLLBACK")
            except (AttributeError, sqlite3.Error):
                pass
            try:
                self._connection.close()
            except (AttributeError, sqlite3.Error):
                pass
            raise
        except sqlite3.Error as exc:
            try:
                self._connection.execute("ROLLBACK")
            except (AttributeError, sqlite3.Error):
                pass
            try:
                self._connection.close()
            except (AttributeError, sqlite3.Error):
                pass
            raise _error("E_V265_STORE_SCHEMA", "SQLite initialization failed") from exc
        if str(journal).lower() != "wal":
            raise _error("E_V265_STORE_SCHEMA", "SQLite WAL mode was not established")
        observed_pragmas = {
            "user_version": self._connection.execute("PRAGMA user_version").fetchone()[0],
            "journal_mode": str(
                self._connection.execute("PRAGMA journal_mode").fetchone()[0]
            ).lower(),
            "synchronous": self._connection.execute("PRAGMA synchronous").fetchone()[0],
            "foreign_keys": self._connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout_ms": self._connection.execute("PRAGMA busy_timeout").fetchone()[0],
        }
        if observed_pragmas != {
            "user_version": 265,
            "journal_mode": "wal",
            "synchronous": 2,
            "foreign_keys": 1,
            "busy_timeout_ms": busy_timeout_ms,
        }:
            self._connection.close()
            raise _error("E_V265_STORE_SCHEMA", "SQLite PRAGMA readback differs")
        self._ddl_sha256 = canonical_sha256(DDL)
        self._expected_schema_manifest = copy.deepcopy(expected_manifest)
        self._schema_manifest_sha256 = canonical_sha256(observed_manifest)
        self._database_identity_sha256 = canonical_sha256(
            {
                "realpath": str(self.db_path),
                "ddl_sha256": self._ddl_sha256,
                "schema_manifest_sha256": self._schema_manifest_sha256,
                "user_version": observed_pragmas["user_version"],
                "journal_mode": observed_pragmas["journal_mode"],
                "synchronous": observed_pragmas["synchronous"],
                "foreign_keys": observed_pragmas["foreign_keys"],
                "busy_timeout_ms": busy_timeout_ms,
            }
        )

    @property
    def runtime_root(self) -> Path:
        """Constructor-validated trusted root; callers cannot replace it."""

        return self._runtime_root

    def _observe_live_identity(self, *, include_manifest: bool) -> None:
        """Re-observe persistent and owned-connection identity before success."""

        try:
            observed = {
                "user_version": int(
                    self._connection.execute("PRAGMA user_version").fetchone()[0]
                ),
                "journal_mode": str(
                    self._connection.execute("PRAGMA journal_mode").fetchone()[0]
                ).lower(),
                "synchronous": self._connection.execute(
                    "PRAGMA synchronous"
                ).fetchone()[0],
                "foreign_keys": self._connection.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0],
                "busy_timeout_ms": self._connection.execute(
                    "PRAGMA busy_timeout"
                ).fetchone()[0],
            }
            if observed != {
                "user_version": 265,
                "journal_mode": "wal",
                "synchronous": 2,
                "foreign_keys": 1,
                "busy_timeout_ms": self.busy_timeout_ms,
            }:
                raise _error("E_V265_STORE_SCHEMA", "live SQLite identity drifted")
            if include_manifest:
                manifest = _schema_manifest(self._connection)
                if (
                    manifest != self._expected_schema_manifest
                    or canonical_sha256(manifest) != self._schema_manifest_sha256
                ):
                    raise _error(
                        "E_V265_STORE_SCHEMA", "live SQLite schema manifest drifted"
                    )
        except RuntimeStoreError:
            raise
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            code = (
                "E_V265_STORE_BUSY"
                if "locked" in message or "busy" in message
                else "E_V265_STORE_SCHEMA"
            )
            raise _error(code, "live SQLite identity observation failed") from exc
        except sqlite3.Error as exc:
            raise _error(
                "E_V265_STORE_SCHEMA", "live SQLite identity observation failed"
            ) from exc

    def _assert_thread(self) -> None:
        if threading.get_ident() != self._thread_id:
            raise _error("E_V265_STORE_THREAD", "store mutation attempted from callback thread")

    def _run_row(self, run_id: str) -> sqlite3.Row:
        row = self._connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise _error("E_V265_STORE_RUN", "run does not exist")
        return row

    def _store_receipt(
        self,
        *,
        run_id: str,
        operation: str,
        before: int,
        after: int,
        event_sha256: str | None,
    ) -> dict[str, Any]:
        receipt: dict[str, Any] = {
            "schema_version": "goal-teams-sqlite-store-receipt-v2.65",
            "run_id": run_id,
            "operation": operation,
            "revision_before": before,
            "revision_after": after,
            "event_sha256": event_sha256,
            "database_identity_sha256": self._database_identity_sha256,
            "committed": True,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        return receipt

    def create_run(
        self,
        run_id: str,
        compiled_graph: Mapping[str, Any],
        bindings: Mapping[str, str],
        *,
        created_at: str,
    ) -> dict[str, Any]:
        self._assert_thread()
        self._observe_live_identity(include_manifest=False)
        if not is_non_empty_string(run_id) or not is_sha256(compiled_graph.get("receipt_sha256")):
            raise _error("E_V265_STORE_RUN", "run or Graph identity is invalid")
        validate_runtime_graph_contract(compiled_graph)
        graph = copy.deepcopy(dict(compiled_graph))
        run_bindings = copy.deepcopy(dict(bindings))
        genesis = make_graph_event(
            run_id=run_id,
            event_id=f"EVENT-{run_id}-1",
            event_seq=1,
            event_type="run.created",
            node_id=None,
            attempt=0,
            cas_base_revision=0,
            previous_event_sha256=ZERO_SHA256,
            bindings=run_bindings,
            payload={"graph_receipt_sha256": graph["receipt_sha256"]},
            evidence_refs=["evidence:run-created"],
            actor_identity="runtime_controller",
            actor_relationship="authorized_writer",
            occurred_at=created_at,
        )
        # Validate the complete genesis transition before acquiring the write lock.
        reduce_graph_events(graph, [genesis], expected_bindings=run_bindings)
        graph_text = _canonical_text(graph)
        bindings_text = _canonical_text(run_bindings)
        try:
            with self._lock:
                self._connection.execute("BEGIN IMMEDIATE")
                if self._connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                    raise _error("E_V265_STORE_CONFLICT", "run ID already exists")
                self._connection.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        graph["receipt_sha256"],
                        graph_text,
                        bindings_text,
                        0,
                        ZERO_SHA256,
                        created_at,
                        created_at,
                    ),
                )
                self._connection.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        1,
                        genesis["event_id"],
                        genesis["event_type"],
                        None,
                        0,
                        _canonical_text(genesis),
                        ZERO_SHA256,
                        genesis["event_sha256"],
                        created_at,
                    ),
                )
                self._update_indexes(genesis)
                self._connection.execute(
                    "UPDATE runs SET revision=1,last_event_sha256=?,updated_at=? WHERE run_id=?",
                    (genesis["event_sha256"], created_at, run_id),
                )
                self._connection.execute("COMMIT")
        except (RuntimeStoreError, GraphRuntimeError):
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        except sqlite3.IntegrityError as exc:
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise _error("E_V265_STORE_CONFLICT", "create_run transaction was rejected") from exc
        except sqlite3.OperationalError as exc:
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            code = "E_V265_STORE_BUSY" if "locked" in str(exc).lower() else "E_V265_STORE_SCHEMA"
            raise _error(code, "create_run transaction failed") from exc
        except sqlite3.Error as exc:
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise _error("E_V265_STORE_SCHEMA", "create_run transaction failed") from exc

        # The transaction is not reported successful until every canonical row
        # can be read back exactly from a new SQLite read transaction.
        try:
            head = self.read_run_head(run_id)
            events = self.load_events(run_id)
            verification = self.verify_run(run_id)
        except RuntimeStoreError as exc:
            if exc.code in {"E_V265_STORE_SCHEMA", "E_V265_STORE_BUSY"}:
                raise
            raise _error("E_V265_STORE_READBACK", "create_run readback failed") from exc
        except (GraphRuntimeError, sqlite3.Error) as exc:
            raise _error("E_V265_STORE_READBACK", "create_run readback failed") from exc
        if (
            head["revision"] != 1
            or head["last_event_sha256"] != genesis["event_sha256"]
            or canonical_json_bytes(head["compiled_graph"]) != canonical_json_bytes(graph)
            or canonical_json_bytes(head["bindings"]) != canonical_json_bytes(run_bindings)
            or events != [genesis]
            or verification["verified"] is not True
        ):
            raise _error("E_V265_STORE_READBACK", "create_run exact readback differs")
        return self._store_receipt(
            run_id=run_id,
            operation="run.created",
            before=0,
            after=1,
            event_sha256=genesis["event_sha256"],
        )

    def _events_unlocked(self, run_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        head = self._run_row(run_id)
        revision = int(head["revision"])
        rows = self._connection.execute(
            "SELECT run_id,event_seq,event_id,event_type,node_id,attempt,event_json,"
            "previous_event_sha256,event_sha256,occurred_at "
            "FROM events WHERE run_id=? AND event_seq>? ORDER BY event_seq",
            (run_id, after_seq),
        ).fetchall()
        expected_count = max(0, revision - after_seq)
        if len(rows) != expected_count:
            raise _error("E_V265_STORE_CORRUPT", "stored Event row count differs")
        events: list[dict[str, Any]] = []
        for expected_seq, row in enumerate(rows, start=after_seq + 1):
            raw = row["event_json"]
            if type(raw) is not str:
                raise _error("E_V265_STORE_CORRUPT", "stored Event JSON is not TEXT")
            event = _load_json(raw, "stored Event")
            if not isinstance(event, Mapping):
                raise _error("E_V265_STORE_CORRUPT", "stored Event is not an object")
            try:
                if (
                    type(row["run_id"]) is not str
                    or type(row["event_seq"]) is not int
                    or type(row["event_id"]) is not str
                    or type(row["event_type"]) is not str
                    or not (
                        row["node_id"] is None or type(row["node_id"]) is str
                    )
                    or type(row["attempt"]) is not int
                    or type(row["previous_event_sha256"]) is not str
                    or type(row["event_sha256"]) is not str
                    or type(row["occurred_at"]) is not str
                ):
                    raise _error(
                        "E_V265_STORE_CORRUPT", "stored Event column type differs"
                    )
                redundant = {
                    "run_id": row["run_id"],
                    "event_seq": row["event_seq"],
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "node_id": row["node_id"],
                    "attempt": row["attempt"],
                    "previous_event_sha256": row["previous_event_sha256"],
                    "event_sha256": row["event_sha256"],
                    "occurred_at": row["occurred_at"],
                }
                if (
                    row["run_id"] != run_id
                    or row["event_seq"] != expected_seq
                    or any(event[field] != value for field, value in redundant.items())
                ):
                    raise _error(
                        "E_V265_STORE_CORRUPT", "stored Event redundant columns differ"
                    )
            except (KeyError, TypeError) as exc:
                raise _error("E_V265_STORE_CORRUPT", "stored Event fields are invalid") from exc
            events.append(copy.deepcopy(dict(event)))
        return events

    def _update_indexes(self, event: Mapping[str, Any]) -> None:
        run_id = event["run_id"]
        node_id = event["node_id"]
        attempt = event["attempt"]
        event_type = event["event_type"]
        payload = event["payload"]
        occurred_at = event["occurred_at"]
        if event_type == "node.claimed":
            self._connection.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, node_id, attempt, "claimed", None, None, None, None, None),
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO leases VALUES(?,?,?,?,?,?,?)",
                (
                    run_id,
                    node_id,
                    payload["lease_id"],
                    payload["worker_id"],
                    attempt,
                    payload["lease_expires_at"],
                    "active",
                ),
            )
        elif event_type == "node.started":
            self._connection.execute(
                "UPDATE attempts SET state='active',owner_run_id=?,validator_run_id=?,started_at=? WHERE run_id=? AND node_id=? AND attempt=?",
                (payload["owner_run_id"], payload["validator_run_id"], occurred_at, run_id, node_id, attempt),
            )
        elif event_type == "node.heartbeat":
            self._connection.execute(
                "UPDATE leases SET expires_at=? WHERE run_id=? AND node_id=? AND lease_id=?",
                (payload["new_expires_at"], run_id, node_id, payload["lease_id"]),
            )
        elif event_type in {"node.outcome_recorded", "node.blocked", "node.cancelled"}:
            outcome = payload.get("outcome") or ("blocked" if event_type == "node.blocked" else "cancelled")
            self._connection.execute(
                "UPDATE attempts SET state='terminal',outcome=?,finished_at=? WHERE run_id=? AND node_id=? AND attempt=?",
                (outcome, occurred_at, run_id, node_id, attempt),
            )
            self._connection.execute(
                "UPDATE leases SET state='released' WHERE run_id=? AND node_id=?",
                (run_id, node_id),
            )
        elif event_type == "node.validation_recorded":
            self._connection.execute(
                "UPDATE attempts SET validator_run_id=? WHERE run_id=? AND node_id=? AND attempt=?",
                (payload["validator_run_id"], run_id, node_id, attempt),
            )
        elif event_type == "node.lease_expired":
            self._connection.execute(
                "UPDATE leases SET state='expired' WHERE run_id=? AND node_id=? AND lease_id=?",
                (run_id, node_id, payload["lease_id"]),
            )
            self._connection.execute(
                "UPDATE attempts SET state=?,outcome=?,finished_at=? WHERE run_id=? AND node_id=? AND attempt=?",
                (
                    "ready" if payload["recovery_decision"] == "ready" else "terminal",
                    None if payload["recovery_decision"] == "ready" else "failed",
                    occurred_at,
                    run_id,
                    node_id,
                    attempt,
                ),
            )
        elif event_type == "node.interrupted":
            self._connection.execute(
                "UPDATE leases SET state='released' WHERE run_id=? AND node_id=?",
                (run_id, node_id),
            )
            self._connection.execute(
                "INSERT INTO hitl_interrupts VALUES(?,?,?,?,?,?,?)",
                (
                    run_id,
                    payload["interrupt_id"],
                    node_id,
                    payload["gate_id"],
                    "waiting_user",
                    None,
                    occurred_at,
                ),
            )
        elif event_type == "node.resumed":
            self._connection.execute(
                "UPDATE hitl_interrupts SET state='resolved',approval_receipt_sha256=?,updated_at=? WHERE run_id=? AND interrupt_id=?",
                (
                    payload["approval_receipt"]["receipt_sha256"],
                    occurred_at,
                    run_id,
                    payload["interrupt_id"],
                ),
            )
        elif event_type == "side_effect.intent":
            self._connection.execute(
                "INSERT INTO idempotency_keys VALUES(?,?,?,?,?,?)",
                (run_id, payload["idempotency_key"], node_id, "pending", None, occurred_at),
            )
        elif event_type == "side_effect.confirmed":
            self._connection.execute(
                "UPDATE idempotency_keys SET state='confirmed',result_digest=?,updated_at=? WHERE run_id=? AND key=?",
                (payload["result_digest"], occurred_at, run_id, payload["idempotency_key"]),
            )
        elif event_type == "side_effect.reconciliation_required":
            self._connection.execute(
                "UPDATE idempotency_keys SET state='reconciliation_required',updated_at=? WHERE run_id=? AND key=?",
                (occurred_at, run_id, payload["idempotency_key"]),
            )

    def append_event(
        self,
        run_id: str,
        event: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        self._assert_thread()
        self._observe_live_identity(include_manifest=False)
        try:
            with self._lock:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._run_row(run_id)
                before = int(row["revision"])
                if expected_revision != before or event.get("cas_base_revision") != before:
                    raise _error("E_V265_STORE_CAS", "store revision differs")
                if event.get("event_seq") != before + 1 or event.get("previous_event_sha256") != row[
                    "last_event_sha256"
                ]:
                    raise _error("E_V265_STORE_CAS", "event head differs")
                graph = _load_json(row["compiled_graph_json"], "compiled Graph")
                bindings = _load_json(row["bindings_json"], "run bindings")
                prior = self._events_unlocked(run_id)
                try:
                    reduce_graph_events(
                        graph,
                        [*prior, copy.deepcopy(dict(event))],
                        expected_bindings=bindings,
                    )
                except GraphRuntimeError:
                    raise
                self._connection.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        event["event_seq"],
                        event["event_id"],
                        event["event_type"],
                        event["node_id"],
                        event["attempt"],
                        _canonical_text(event),
                        event["previous_event_sha256"],
                        event["event_sha256"],
                        event["occurred_at"],
                    ),
                )
                self._update_indexes(event)
                self._connection.execute(
                    "UPDATE runs SET revision=?,last_event_sha256=?,updated_at=? WHERE run_id=?",
                    (before + 1, event["event_sha256"], event["occurred_at"], run_id),
                )
                self._connection.execute("COMMIT")
        except (RuntimeStoreError, GraphRuntimeError):
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        except sqlite3.IntegrityError as exc:
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise _error("E_V265_STORE_CONFLICT", "SQLite unique constraint rejected Event") from exc
        except sqlite3.OperationalError as exc:
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            code = "E_V265_STORE_BUSY" if "locked" in str(exc).lower() else "E_V265_STORE_SCHEMA"
            raise _error(code, "SQLite Event transaction failed") from exc
        except sqlite3.Error as exc:
            try:
                self._connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise _error("E_V265_STORE_SCHEMA", "SQLite Event transaction failed") from exc

        try:
            head = self.read_run_head(run_id)
            appended = self.load_events(run_id, after_seq=before)
            verification = self.verify_run(run_id)
        except RuntimeStoreError as exc:
            if exc.code in {"E_V265_STORE_SCHEMA", "E_V265_STORE_BUSY"}:
                raise
            raise _error("E_V265_STORE_READBACK", "post-commit Event readback failed") from exc
        except (GraphRuntimeError, sqlite3.Error) as exc:
            raise _error("E_V265_STORE_READBACK", "post-commit Event readback failed") from exc
        if (
            head["revision"] != before + 1
            or head["last_event_sha256"] != event["event_sha256"]
            or appended != [dict(event)]
            or verification["verified"] is not True
        ):
            raise _error("E_V265_STORE_READBACK", "post-commit Event or index differs")
        return self._store_receipt(
            run_id=run_id,
            operation=event["event_type"],
            before=before,
            after=before + 1,
            event_sha256=event["event_sha256"],
        )

    def load_events(self, run_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        if not is_int(after_seq, minimum=0):
            raise _error("E_V265_STORE_RUN", "after_seq is invalid")
        with self._lock:
            self._run_row(run_id)
            return copy.deepcopy(self._events_unlocked(run_id, after_seq=after_seq))

    def read_run_head(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._run_row(run_id)
            graph = _load_json(row["compiled_graph_json"], "compiled Graph")
            bindings = _load_json(row["bindings_json"], "run bindings")
            try:
                validate_runtime_graph_contract(graph)
            except GraphRuntimeError as exc:
                raise _error("E_V265_STORE_CORRUPT", "stored compiled Graph is invalid") from exc
            if (
                canonical_json_bytes(graph).decode("utf-8") != row["compiled_graph_json"]
                or canonical_json_bytes(bindings).decode("utf-8") != row["bindings_json"]
                or row["graph_receipt_sha256"] != graph.get("receipt_sha256")
                or not is_int(row["revision"], minimum=1)
                or not is_sha256(row["last_event_sha256"])
            ):
                raise _error("E_V265_STORE_CORRUPT", "stored run head identity differs")
            require_utc_timestamp(
                row["created_at"],
                error=lambda message: _error("E_V265_STORE_CORRUPT", message),
                label="run.created_at",
            )
            require_utc_timestamp(
                row["updated_at"],
                error=lambda message: _error("E_V265_STORE_CORRUPT", message),
                label="run.updated_at",
            )
            return {
                "run_id": row["run_id"],
                "graph_receipt_sha256": row["graph_receipt_sha256"],
                "compiled_graph": graph,
                "bindings": bindings,
                "revision": row["revision"],
                "last_event_sha256": row["last_event_sha256"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def save_checkpoint(
        self,
        run_id: str,
        projection: Mapping[str, Any],
        *,
        expected_revision: int,
        created_at: str,
    ) -> dict[str, Any]:
        """Map SQLite failures across the complete checkpoint public path."""

        self._assert_thread()
        try:
            self._observe_live_identity(include_manifest=False)
            receipt = self._save_checkpoint_impl(
                run_id,
                projection,
                expected_revision=expected_revision,
                created_at=created_at,
            )
            self._observe_live_identity(include_manifest=True)
            return receipt
        except RuntimeStoreError:
            raise
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            code = (
                "E_V265_STORE_BUSY"
                if "locked" in message or "busy" in message
                else "E_V265_STORE_SCHEMA"
            )
            raise _error(code, "checkpoint SQLite operation failed") from exc
        except sqlite3.Error as exc:
            raise _error("E_V265_STORE_SCHEMA", "checkpoint SQLite operation failed") from exc

    def _save_checkpoint_impl(
        self,
        run_id: str,
        projection: Mapping[str, Any],
        *,
        expected_revision: int,
        created_at: str,
    ) -> dict[str, Any]:
        self._assert_thread()
        require_utc_timestamp(
            created_at,
            error=lambda message: _error("E_V265_RUNTIME_CHECKPOINT_STALE", message),
            label="checkpoint.created_at",
        )
        head = self.read_run_head(run_id)
        if head["revision"] != expected_revision:
            raise _error("E_V265_STORE_CAS", "checkpoint revision differs")
        try:
            rebuilt = reduce_graph_events(
                head["compiled_graph"],
                self.load_events(run_id),
                expected_bindings=head["bindings"],
            )
        except GraphRuntimeError as exc:
            raise _error("E_V265_STORE_CORRUPT", "checkpoint replay failed") from exc
        if dict(projection) != rebuilt:
            raise _error("E_V265_RUNTIME_CHECKPOINT_STALE", "checkpoint projection differs")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                locked_head = self._run_row(run_id)
                if int(locked_head["revision"]) != expected_revision:
                    raise _error("E_V265_STORE_CAS", "checkpoint revision changed")
                existing = self._connection.execute(
                    "SELECT * FROM checkpoints WHERE run_id=? AND revision=?",
                    (run_id, expected_revision),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["projection_json"] != _canonical_text(rebuilt)
                        or existing["projection_sha256"] != rebuilt["projection_sha256"]
                        or existing["created_at"] != created_at
                    ):
                        raise _error(
                            "E_V265_RUNTIME_CHECKPOINT_STALE",
                            "checkpoint identity conflicts",
                        )
                else:
                    self._connection.execute(
                        "INSERT INTO checkpoints VALUES(?,?,?,?,?)",
                        (
                            run_id,
                            expected_revision,
                            _canonical_text(rebuilt),
                            rebuilt["projection_sha256"],
                            created_at,
                        ),
                    )
                self._connection.execute("COMMIT")
            except RuntimeStoreError:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            except sqlite3.OperationalError as exc:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                message = str(exc).lower()
                code = (
                    "E_V265_STORE_BUSY"
                    if "locked" in message or "busy" in message
                    else "E_V265_STORE_SCHEMA"
                )
                raise _error(code, "checkpoint SQLite transaction failed") from exc
            except sqlite3.Error as exc:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise _error(
                    "E_V265_STORE_SCHEMA", "checkpoint SQLite transaction failed"
                ) from exc
        try:
            readback = self.load_checkpoint(run_id)
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            code = (
                "E_V265_STORE_BUSY"
                if "locked" in message or "busy" in message
                else "E_V265_STORE_SCHEMA"
            )
            raise _error(code, "checkpoint SQLite readback failed") from exc
        except sqlite3.Error as exc:
            raise _error("E_V265_STORE_SCHEMA", "checkpoint SQLite readback failed") from exc
        except RuntimeStoreError as exc:
            raise _error(
                "E_V265_STORE_READBACK", "checkpoint post-commit readback failed"
            ) from exc
        if (
            readback is None
            or readback["revision"] != expected_revision
            or readback["projection"] != rebuilt
            or readback["projection_sha256"] != rebuilt["projection_sha256"]
            or readback["created_at"] != created_at
        ):
            raise _error("E_V265_STORE_READBACK", "checkpoint exact readback differs")
        return self._store_receipt(
            run_id=run_id,
            operation="checkpoint.save",
            before=expected_revision,
            after=expected_revision,
            event_sha256=None,
        )

    def load_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            head = self.read_run_head(run_id)
            row = self._connection.execute(
                "SELECT * FROM checkpoints WHERE run_id=? ORDER BY revision DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            projection = _load_json(row["projection_json"], "checkpoint")
            if not isinstance(projection, Mapping):
                raise _error("E_V265_STORE_CORRUPT", "checkpoint projection is not an object")
            projection_sha256 = _validate_projection_digest(
                projection, label="checkpoint projection"
            )
            revision = row["revision"]
            if (
                not is_int(revision, minimum=1)
                or revision > head["revision"]
                or projection_sha256 != row["projection_sha256"]
                or canonical_json_bytes(projection).decode("utf-8")
                != row["projection_json"]
            ):
                raise _error("E_V265_STORE_CORRUPT", "checkpoint identity differs")
            require_utc_timestamp(
                row["created_at"],
                error=lambda message: _error("E_V265_STORE_CORRUPT", message),
                label="checkpoint.created_at",
            )
            events = self._events_unlocked(run_id)
            try:
                rebuilt = reduce_graph_events(
                    head["compiled_graph"],
                    events[:revision],
                    expected_bindings=head["bindings"],
                )
            except GraphRuntimeError as exc:
                raise _error("E_V265_STORE_CORRUPT", "checkpoint replay failed") from exc
            if dict(projection) != rebuilt:
                raise _error("E_V265_STORE_CORRUPT", "checkpoint differs from Event replay")
            return {
                "run_id": run_id,
                "revision": revision,
                "projection": copy.deepcopy(dict(projection)),
                "projection_sha256": projection_sha256,
                "created_at": row["created_at"],
            }

    def _read_rows(self, table: str, run_id: str, order: str) -> list[dict[str, Any]]:
        with self._lock:
            self._run_row(run_id)
            rows = self._connection.execute(
                f"SELECT * FROM {table} WHERE run_id=? ORDER BY {order}", (run_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def read_attempts(self, run_id: str) -> list[dict[str, Any]]:
        return self._read_rows("attempts", run_id, "node_id,attempt")

    def read_leases(self, run_id: str) -> list[dict[str, Any]]:
        return self._read_rows("leases", run_id, "node_id")

    def read_interrupts(self, run_id: str) -> list[dict[str, Any]]:
        return self._read_rows("hitl_interrupts", run_id, "interrupt_id")

    def record_attempt(self, run_id: str, event: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        if event.get("event_type") not in {"node.started", "node.outcome_recorded", "node.validation_recorded"}:
            raise _error("E_V265_STORE_CONFLICT", "record_attempt received wrong Event type")
        return self.append_event(run_id, event, expected_revision=expected_revision)

    def claim_lease(self, run_id: str, event: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        if event.get("event_type") != "node.claimed":
            raise _error("E_V265_STORE_CONFLICT", "claim_lease received wrong Event type")
        return self.append_event(run_id, event, expected_revision=expected_revision)

    def renew_lease(self, run_id: str, event: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        if event.get("event_type") != "node.heartbeat":
            raise _error("E_V265_STORE_CONFLICT", "renew_lease received wrong Event type")
        return self.append_event(run_id, event, expected_revision=expected_revision)

    def release_lease(self, run_id: str, event: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        return self.append_event(run_id, event, expected_revision=expected_revision)

    def record_interrupt(self, run_id: str, event: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        if event.get("event_type") != "node.interrupted":
            raise _error("E_V265_STORE_CONFLICT", "record_interrupt received wrong Event type")
        return self.append_event(run_id, event, expected_revision=expected_revision)

    def resolve_interrupt(self, run_id: str, event: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]:
        if event.get("event_type") != "node.resumed":
            raise _error("E_V265_STORE_CONFLICT", "resolve_interrupt received wrong Event type")
        return self.append_event(run_id, event, expected_revision=expected_revision)

    def reserve_idempotency_key(
        self,
        run_id: str,
        node_id: str,
        key: str,
        intent_event: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        existing = self.get_idempotency_record(run_id, key)
        if existing is not None:
            if existing["state"] == "confirmed":
                return {**existing, "execute": False}
            return {**existing, "execute": False}
        receipt = self.append_event(run_id, intent_event, expected_revision=expected_revision)
        return {**self.get_idempotency_record(run_id, key), "execute": True, "store_receipt": receipt}

    def confirm_idempotency_key(
        self,
        run_id: str,
        key: str,
        result_digest: str,
        confirmation_event: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        if confirmation_event.get("payload", {}).get("result_digest") != result_digest:
            raise _error("E_V265_STORE_CONFLICT", "idempotency result digest differs")
        receipt = self.append_event(run_id, confirmation_event, expected_revision=expected_revision)
        return {**self.get_idempotency_record(run_id, key), "store_receipt": receipt}

    def get_idempotency_record(self, run_id: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            self._run_row(run_id)
            row = self._connection.execute(
                "SELECT * FROM idempotency_keys WHERE run_id=? AND key=?", (run_id, key)
            ).fetchone()
            return None if row is None else dict(row)

    def verify_run(self, run_id: str) -> dict[str, Any]:
        try:
            head = self.read_run_head(run_id)
            events = self.load_events(run_id)
            projection = reduce_graph_events(
                head["compiled_graph"], events, expected_bindings=head["bindings"]
            )
            _validate_projection_digest(projection, label="current Runtime projection")
        except (
            RuntimeStoreError,
            GraphRuntimeError,
            KeyError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ) as exc:
            if isinstance(exc, RuntimeStoreError) and exc.code == "E_V265_STORE_RUN":
                raise
            raise _error("E_V265_STORE_CORRUPT", "run replay failed") from exc
        if (
            head["graph_receipt_sha256"] != head["compiled_graph"].get("receipt_sha256")
            or head["revision"] != len(events)
            or head["last_event_sha256"] != projection["last_event_sha256"]
            or head["created_at"] != events[0]["occurred_at"]
            or head["updated_at"] != events[-1]["occurred_at"]
        ):
            raise _error("E_V265_STORE_CORRUPT", "run head differs from Event replay")
        expected_attempts: dict[tuple[str, int], dict[str, Any]] = {}
        expected_leases: dict[str, dict[str, Any]] = {}
        expected_idempotency: dict[str, dict[str, Any]] = {}
        expected_interrupts: dict[str, dict[str, Any]] = {}
        for event in events:
            event_type = event["event_type"]
            node_id = event["node_id"]
            attempt = event["attempt"]
            payload = event["payload"]
            occurred = event["occurred_at"]
            key = (node_id, attempt)
            if event_type == "node.claimed":
                expected_attempts[key] = {
                    "run_id": run_id, "node_id": node_id, "attempt": attempt,
                    "state": "claimed", "outcome": None, "owner_run_id": None,
                    "validator_run_id": None, "started_at": None, "finished_at": None,
                }
                expected_leases[node_id] = {
                    "run_id": run_id, "node_id": node_id, "lease_id": payload["lease_id"],
                    "worker_id": payload["worker_id"], "attempt": attempt,
                    "expires_at": payload["lease_expires_at"], "state": "active",
                }
            elif event_type == "node.started":
                expected_attempts[key].update(
                    {"state": "active", "owner_run_id": payload["owner_run_id"],
                     "validator_run_id": payload["validator_run_id"], "started_at": occurred}
                )
            elif event_type == "node.heartbeat":
                expected_leases[node_id]["expires_at"] = payload["new_expires_at"]
            elif event_type in {"node.outcome_recorded", "node.blocked", "node.cancelled"}:
                outcome = payload.get("outcome") or ("blocked" if event_type == "node.blocked" else "cancelled")
                if key in expected_attempts:
                    expected_attempts[key].update({"state": "terminal", "outcome": outcome, "finished_at": occurred})
                if node_id in expected_leases:
                    expected_leases[node_id]["state"] = "released"
            elif event_type == "node.validation_recorded" and key in expected_attempts:
                expected_attempts[key]["validator_run_id"] = payload["validator_run_id"]
            elif event_type == "node.lease_expired":
                expected_leases[node_id]["state"] = "expired"
                expected_attempts[key].update(
                    {"state": "ready" if payload["recovery_decision"] == "ready" else "terminal",
                     "outcome": None if payload["recovery_decision"] == "ready" else "failed",
                     "finished_at": occurred}
                )
            elif event_type == "node.interrupted":
                if node_id in expected_leases:
                    expected_leases[node_id]["state"] = "released"
                expected_interrupts[payload["interrupt_id"]] = {
                    "run_id": run_id, "interrupt_id": payload["interrupt_id"], "node_id": node_id,
                    "gate_id": payload["gate_id"], "state": "waiting_user",
                    "approval_receipt_sha256": None, "updated_at": occurred,
                }
            elif event_type == "node.resumed":
                expected_interrupts[payload["interrupt_id"]].update(
                    {"state": "resolved", "approval_receipt_sha256": payload["approval_receipt"]["receipt_sha256"],
                     "updated_at": occurred}
                )
            elif event_type == "side_effect.intent":
                expected_idempotency[payload["idempotency_key"]] = {
                    "run_id": run_id, "key": payload["idempotency_key"], "node_id": node_id,
                    "state": "pending", "result_digest": None, "updated_at": occurred,
                }
            elif event_type == "side_effect.confirmed":
                expected_idempotency[payload["idempotency_key"]].update(
                    {"state": "confirmed", "result_digest": payload["result_digest"], "updated_at": occurred}
                )
            elif event_type == "side_effect.reconciliation_required":
                expected_idempotency[payload["idempotency_key"]].update(
                    {"state": "reconciliation_required", "updated_at": occurred}
                )

        actual_attempts = self.read_attempts(run_id)
        actual_leases = self.read_leases(run_id)
        actual_interrupts = self.read_interrupts(run_id)
        actual_idempotency = self._read_rows("idempotency_keys", run_id, "key")
        attempt_matches = actual_attempts == [expected_attempts[key] for key in sorted(expected_attempts)]
        lease_matches = actual_leases == [expected_leases[key] for key in sorted(expected_leases)]
        interrupt_matches = actual_interrupts == [expected_interrupts[key] for key in sorted(expected_interrupts)]
        idempotency_matches = actual_idempotency == [expected_idempotency[key] for key in sorted(expected_idempotency)]

        checkpoints = self._read_rows("checkpoints", run_id, "revision")
        checkpoint_matches = True
        for item in checkpoints:
            stored_projection = _load_json(item["projection_json"], "checkpoint")
            try:
                if not isinstance(stored_projection, Mapping):
                    raise _error(
                        "E_V265_STORE_CORRUPT", "checkpoint projection is not an object"
                    )
                stored_digest = _validate_projection_digest(
                    stored_projection, label="checkpoint projection"
                )
                if (
                    not is_int(item["revision"], minimum=1)
                    or item["revision"] > len(events)
                    or stored_digest != item["projection_sha256"]
                    or canonical_json_bytes(stored_projection).decode("utf-8")
                    != item["projection_json"]
                ):
                    checkpoint_matches = False
                    break
                require_utc_timestamp(
                    item["created_at"],
                    error=lambda message: _error("E_V265_STORE_CORRUPT", message),
                    label="checkpoint.created_at",
                )
                rebuilt_checkpoint = reduce_graph_events(
                    head["compiled_graph"],
                    events[: item["revision"]],
                    expected_bindings=head["bindings"],
                )
                _validate_projection_digest(
                    rebuilt_checkpoint, label="rebuilt checkpoint projection"
                )
            except (GraphRuntimeError, RuntimeStoreError, ValueError):
                checkpoint_matches = False
                break
            if (
                stored_projection != rebuilt_checkpoint
            ):
                checkpoint_matches = False
                break
        if not all((attempt_matches, lease_matches, interrupt_matches, idempotency_matches, checkpoint_matches)):
            raise _error("E_V265_STORE_CORRUPT", "one or more Runtime indexes differ from Event replay")
        self._observe_live_identity(include_manifest=True)
        result: dict[str, Any] = {
            "schema_version": "goal-teams-runtime-store-verification-v2.65",
            "run_id": run_id,
            "graph_receipt_sha256": head["graph_receipt_sha256"],
            "revision": head["revision"],
            "event_count": len(events),
            "last_event_sha256": head["last_event_sha256"],
            "projection_sha256": projection["projection_sha256"],
            "attempt_index_matches": attempt_matches,
            "lease_index_matches": lease_matches,
            "checkpoint_index_matches": checkpoint_matches,
            "idempotency_index_matches": idempotency_matches,
            "interrupt_index_matches": interrupt_matches,
            "verified": True,
        }
        result["receipt_sha256"] = canonical_sha256(result)
        return result

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = ["RuntimeEventLog", "RuntimeStoreError", "SQLiteRuntimeStore"]
