from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.v250.task_plan_compiler import (
    compile_task_plan,
    validate_compiled_task_plan,
)
from scripts.v265.graph_contract import compile_graph_contract
from scripts.v265.graph_runtime import reduce_graph_events
from scripts.v265.runtime_store import RuntimeStoreError, SQLiteRuntimeStore


ARCHITECTURE_SHA256 = "5f350bae868f842bc02d00b67ba44c577765c3f9a7f9ed080ada31e81f3c486f"
HARDENING_PLAN_REVISION = 3
TASK_EXACT_SET_SHA256 = "d0f5bbf75cadf24338028d477b0e1ccc40c29b8aeb0c642cdc988d2600ebf496"
ZERO_SHA256 = "0" * 64


def _task() -> dict[str, object]:
    return {
        "task_id": "STORE",
        "requirement_refs": ["REQ-H265-STORE"],
        "consumer_refs": ["consumer:H265-03G"],
        "admission": {
            "current_consumer_confirmed": True,
            "observable_acceptance_defined": True,
            "scope_locked": True,
            "budget_bound": True,
            "exit_condition_frozen": True,
            "evidence_refs": ["evidence:H265-03R:consumer"],
        },
        "owner": "goal_backend",
        "validator": "goal_unit_test_runner",
        "scope_allowlist": ["scripts/v265/runtime_store.py"],
        "forbidden_scope": ["README.md", "README.en.md", "release/**"],
        "depends_on": [],
        "budget_wu": 7,
        "attempt_budget": 2,
        "revalidation_budget": 1,
        "inputs": [{"input_id": "input:H265-03R"}],
        "outputs": [
            {
                "output_id": "output:H265-03G",
                "consumer_refs": ["consumer:H265-03G"],
                "required": True,
            }
        ],
        "verification": [
            {
                "verification_id": "verification:H265-03R",
                "verification_type": "runtime_behavior",
                "method": "observe SQLite atomicity and process reopen",
                "expected_result": "Store fails closed without orphan state",
                "evidence_refs": ["evidence:H265-03R:red"],
            }
        ],
        "business_oracle": {
            "oracle_id": "oracle:H265-03R",
            "oracle_type": "runtime_behavior",
            "acceptance_criteria": ["Event and indexes survive process termination"],
            "evidence_refs": ["evidence:H265-03R:oracle"],
        },
        "exit_condition": {
            "exit_id": "exit:H265-03G",
            "exit_type": "validated_outcome",
            "required_receipt_types": ["runtime_store_verification"],
            "on_budget_exhaustion": "replan",
        },
        "failure_artifacts": ["failure:H265-03G"],
    }


def _compiled_graph() -> dict[str, object]:
    source = {
        "schema_version": "goal-teams-task-plan-v1",
        "plan_id": "GT-V265-H265-03R",
        "plan_revision": HARDENING_PLAN_REVISION,
        "tasks": [_task()],
        "phase_exact_sets": {
            "development": ["STORE"],
            "runtime": [],
            "release": [],
        },
    }
    compiled_plan = compile_task_plan(source)
    plan_validation = validate_compiled_task_plan(compiled_plan)
    task = source["tasks"][0]
    document = {
        "schema_version": "goal-teams-graph-contract-v2.65",
        "graph_id": "GRAPH-H265-STORE-ATOMICITY",
        "graph_revision": 1,
        "plan_binding": {
            "plan_id": source["plan_id"],
            "plan_revision": source["plan_revision"],
            "task_exact_set_sha256": compiled_plan["task_exact_set_digest"],
            "compiled_task_plan_sha256": compiled_plan["receipt_digest"],
            "task_plan_validation_sha256": plan_validation["receipt_digest"],
        },
        "supersedes_graph_sha256": None,
        "nodes": [
            {
                "node_id": "STORE",
                "task_refs": ["STORE"],
                "node_type": "action",
                "owner_identity": task["owner"],
                "validator_identity": task["validator"],
                "action_ref": "action:store",
                "resource_refs": {
                    "required": [],
                    "recommended": [],
                    "generated": [],
                    "upstream_artifacts": [],
                    "forbidden": [],
                },
                "input_ports": [],
                "output_ports": [],
                "scope_allowlist": list(task["scope_allowlist"]),
                "forbidden_scope": list(task["forbidden_scope"]),
                "budget": {
                    "work_units": task["budget_wu"],
                    "attempts": task["attempt_budget"],
                    "revalidations": task["revalidation_budget"],
                    "context_tokens": 128,
                },
                "timeout_seconds": 30,
                "retry_policy": {
                    "max_attempts": task["attempt_budget"],
                    "retryable_outcomes": ["failed"],
                    "backoff_seconds": [0],
                },
                "gate_refs": [],
                "exit_condition_ref": task["exit_condition"]["exit_id"],
                "recovery_policy": {"mode": "none", "edge_id": None},
                "fan_in": None,
            }
        ],
        "edges": [],
        "resources": [],
        "gates": [],
        "actions": [
            {
                "action_id": "action:store",
                "runner": "host_adapter",
                "effect": "local_write",
                "tool_allowlist": ["sqlite"],
                "network_policy": "deny",
                "workspace_policy": "node_scope",
                "input_schema_ref": "schema:store:input",
                "output_schema_ref": "schema:store:output",
                "idempotency_required": False,
            }
        ],
    }
    return compile_graph_contract(
        document,
        compiled_task_plan=compiled_plan,
        task_plan_validation_receipt=plan_validation,
    )


def _bindings(compiled_graph: dict[str, object]) -> dict[str, str]:
    return {
        "source_sha256": "1" * 64,
        "route_sha256": "2" * 64,
        "contract_sha256": str(compiled_graph["receipt_sha256"]),
        "task_exact_set_sha256": str(
            compiled_graph["plan_binding"]["task_exact_set_sha256"]
        ),
        "environment_sha256": "3" * 64,
        "authorization_lineage_sha256": "4" * 64,
    }


def _canonical_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class TestV265RuntimeStoreAtomicity(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.temp.name).resolve()
        self.compiled_graph = _compiled_graph()
        self.bindings = _bindings(self.compiled_graph)
        self._opened: list[SQLiteRuntimeStore] = []

    def tearDown(self) -> None:
        for store in reversed(self._opened):
            try:
                store.close()
            except Exception:
                pass
        self.temp.cleanup()

    def _store(self, name: str) -> SQLiteRuntimeStore:
        store = SQLiteRuntimeStore(
            self.runtime_root / name,
            runtime_root=self.runtime_root,
        )
        self._opened.append(store)
        return store

    def _execute_sql(
        self,
        database_name: str,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> None:
        connection = sqlite3.connect(str(self.runtime_root / database_name))
        try:
            connection.execute(statement, parameters)
            connection.commit()
        finally:
            connection.close()

    def _create(self, store: SQLiteRuntimeStore, run_id: str) -> None:
        store.create_run(
            run_id,
            self.compiled_graph,
            self.bindings,
            created_at="2026-08-22T14:00:00Z",
        )

    def _projection(self, store: SQLiteRuntimeStore, run_id: str) -> dict[str, object]:
        return reduce_graph_events(
            self.compiled_graph,
            store.load_events(run_id),
            expected_bindings=self.bindings,
        )

    def test_atomic_genesis_failure_rolls_back_every_row_and_same_id_retries(self) -> None:
        store = self._store("atomic-genesis.sqlite3")
        self._execute_sql(
            "atomic-genesis.sqlite3",
            """
            CREATE TRIGGER h265_fail_genesis
            BEFORE INSERT ON events
            BEGIN
              SELECT RAISE(ABORT, 'H265 synthetic genesis failure');
            END
            """
        )

        with self.assertRaises(RuntimeStoreError):
            self._create(store, "RUN-ATOMIC-GENESIS")

        with self.assertRaises(RuntimeStoreError) as absent:
            store.read_run_head("RUN-ATOMIC-GENESIS")
        self.assertEqual("E_V265_STORE_RUN", absent.exception.code)

        self._execute_sql(
            "atomic-genesis.sqlite3",
            "DROP TRIGGER h265_fail_genesis",
        )
        self._create(store, "RUN-ATOMIC-GENESIS")
        head = store.read_run_head("RUN-ATOMIC-GENESIS")
        self.assertEqual(1, head["revision"])
        self.assertEqual(1, len(store.load_events("RUN-ATOMIC-GENESIS")))

    def test_runtime_root_is_constructor_validated_read_only_identity(self) -> None:
        store = self._store("runtime-root.sqlite3")
        self.assertEqual(self.runtime_root, store.runtime_root)
        with self.assertRaises(AttributeError):
            store.runtime_root = self.runtime_root / "caller-replacement"

    def test_database_path_rejects_existing_nested_symlink_component(self) -> None:
        actual = self.runtime_root / "actual"
        actual.mkdir()
        alias = self.runtime_root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        try:
            unexpected = SQLiteRuntimeStore(
                alias / "runtime.sqlite3",
                runtime_root=self.runtime_root,
            )
        except RuntimeStoreError as caught:
            self.assertEqual("E_V265_STORE_PATH", caught.code)
        else:
            self._opened.append(unexpected)
            self.fail("nested symlink database parent was accepted")

    def test_checkpoint_commit_exact_readback_detects_trigger_corruption(self) -> None:
        store = self._store("checkpoint-readback.sqlite3")
        self._create(store, "RUN-CHECKPOINT-READBACK")
        projection = self._projection(store, "RUN-CHECKPOINT-READBACK")
        self._execute_sql(
            "checkpoint-readback.sqlite3",
            f"""
            CREATE TRIGGER h265_corrupt_checkpoint
            AFTER INSERT ON checkpoints
            BEGIN
              UPDATE checkpoints
                 SET projection_json='{{}}', projection_sha256='{ZERO_SHA256}'
               WHERE run_id=NEW.run_id AND revision=NEW.revision;
            END
            """
        )
        with self.assertRaises(RuntimeStoreError) as caught:
            store.save_checkpoint(
                "RUN-CHECKPOINT-READBACK",
                projection,
                expected_revision=1,
                created_at="2026-08-22T14:00:01Z",
            )
        self.assertEqual("E_V265_STORE_READBACK", caught.exception.code)

    def test_event_corruption_fails_verify_run_closed(self) -> None:
        store = self._store("event-corrupt.sqlite3")
        self._create(store, "RUN-EVENT-CORRUPT")
        self._execute_sql(
            "event-corrupt.sqlite3",
            "UPDATE events SET event_json='{}' WHERE run_id=? AND event_seq=1",
            ("RUN-EVENT-CORRUPT",),
        )
        with self.assertRaises(RuntimeStoreError) as caught:
            store.verify_run("RUN-EVENT-CORRUPT")
        self.assertEqual("E_V265_STORE_CORRUPT", caught.exception.code)

    def test_index_corruption_fails_verify_run_closed(self) -> None:
        store = self._store("index-corrupt.sqlite3")
        self._create(store, "RUN-INDEX-CORRUPT")
        self._execute_sql(
            "index-corrupt.sqlite3",
            "INSERT INTO idempotency_keys VALUES(?,?,?,?,?,?)",
            (
                "RUN-INDEX-CORRUPT",
                "ORPHAN-KEY",
                "STORE",
                "confirmed",
                "5" * 64,
                "2026-08-22T14:00:01Z",
            ),
        )
        with self.assertRaises(RuntimeStoreError) as caught:
            store.verify_run("RUN-INDEX-CORRUPT")
        self.assertEqual("E_V265_STORE_CORRUPT", caught.exception.code)

    def test_checkpoint_corruption_is_rejected_on_load_and_verification(self) -> None:
        store = self._store("checkpoint-corrupt.sqlite3")
        self._create(store, "RUN-CHECKPOINT-CORRUPT")
        projection = self._projection(store, "RUN-CHECKPOINT-CORRUPT")
        store.save_checkpoint(
            "RUN-CHECKPOINT-CORRUPT",
            projection,
            expected_revision=1,
            created_at="2026-08-22T14:00:01Z",
        )
        forged_projection = dict(projection)
        forged_projection["projection_sha256"] = ZERO_SHA256
        self._execute_sql(
            "checkpoint-corrupt.sqlite3",
            "UPDATE checkpoints SET projection_json=?,projection_sha256=? WHERE run_id=? AND revision=1",
            (
                _canonical_text(forged_projection),
                ZERO_SHA256,
                "RUN-CHECKPOINT-CORRUPT",
            ),
        )

        with self.assertRaises(RuntimeStoreError) as load_error:
            store.load_checkpoint("RUN-CHECKPOINT-CORRUPT")
        self.assertEqual("E_V265_STORE_CORRUPT", load_error.exception.code)
        with self.assertRaises(RuntimeStoreError) as verify_error:
            store.verify_run("RUN-CHECKPOINT-CORRUPT")
        self.assertEqual("E_V265_STORE_CORRUPT", verify_error.exception.code)

    def test_real_process_exit_reopens_checkpoint_and_verifies_without_controller(self) -> None:
        graph_path = self.runtime_root / "compiled-graph.json"
        bindings_path = self.runtime_root / "bindings.json"
        graph_path.write_text(_canonical_text(self.compiled_graph), encoding="utf-8")
        bindings_path.write_text(_canonical_text(self.bindings), encoding="utf-8")
        db_path = self.runtime_root / "process-exit.sqlite3"
        project_root = Path(__file__).resolve().parents[2]
        child = """
import json
import os
import sys
from pathlib import Path
from scripts.v265.graph_runtime import reduce_graph_events
from scripts.v265.runtime_store import SQLiteRuntimeStore

runtime_root = Path(sys.argv[1])
db_path = Path(sys.argv[2])
graph = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
bindings = json.loads(Path(sys.argv[4]).read_text(encoding='utf-8'))
store = SQLiteRuntimeStore(db_path, runtime_root=runtime_root)
store.create_run(
    'RUN-PROCESS-EXIT', graph, bindings, created_at='2026-08-22T14:00:00Z'
)
projection = reduce_graph_events(
    graph, store.load_events('RUN-PROCESS-EXIT'), expected_bindings=bindings
)
store.save_checkpoint(
    'RUN-PROCESS-EXIT', projection,
    expected_revision=1, created_at='2026-08-22T14:00:01Z'
)
os._exit(23)
"""
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (str(project_root), environment.get("PYTHONPATH", "")))
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(self.runtime_root),
                str(db_path),
                str(graph_path),
                str(bindings_path),
            ],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(
            23,
            completed.returncode,
            msg=f"stdout={completed.stdout!r} stderr={completed.stderr!r}",
        )

        reopened = self._store("process-exit.sqlite3")
        verification = reopened.verify_run("RUN-PROCESS-EXIT")
        self.assertTrue(verification["verified"])
        self.assertEqual(1, verification["event_count"])
        checkpoint = reopened.load_checkpoint("RUN-PROCESS-EXIT")
        self.assertIsNotNone(checkpoint)
        self.assertEqual(
            self._projection(reopened, "RUN-PROCESS-EXIT"),
            checkpoint["projection"],
        )


if __name__ == "__main__":
    unittest.main()
