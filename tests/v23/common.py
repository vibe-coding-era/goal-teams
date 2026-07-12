"""Shared helpers for the V2.3 fail-closed test suite."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "v23" / "goalteams_v23.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("goalteams_v23_under_test", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import {TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gt = load_runtime()


ROOT_HAS_TRUSTED_V236_BASE = gt._verified_v236_goal_teams_target(ROOT)


def requires_trusted_goal_teams_checkout(test):
    """Skip only assertions whose premise is this exact trusted source checkout."""

    return unittest.skipUnless(
        ROOT_HAS_TRUSTED_V236_BASE,
        "requires a source checkout containing the trusted Goal Teams V2.35 base",
    )(test)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def clone(value: Any) -> Any:
    return copy.deepcopy(value)


def run_cli(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_envelope(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"stdout is not one JSON envelope: rc={proc.returncode}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        ) from exc
    if not isinstance(value, dict):
        raise AssertionError(f"envelope must be an object, got {type(value).__name__}")
    for key in ("ok", "schema_version", "error_code"):
        if key not in value:
            raise AssertionError(f"envelope missing {key}: {value}")
    return value


def task_event(
    event_id: str,
    task_id: str,
    base_revision: int,
    task_state: str,
    *,
    payload: dict[str, Any] | None = None,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    owner_run_id = f"RUN-OWNER-{task_id}"
    validator_run_id = f"RUN-VALIDATOR-{task_id}"
    body: dict[str, Any] = {"task_state": task_state}
    if base_revision == 0:
        body.update(
            {
                "title": task_id,
                "required_for_done": False,
                "acceptance_blocking": False,
                "owner_member_id": f"实现-{task_id}",
                "validator_member_id": f"评审-{task_id}",
                "owner_run_id": owner_run_id,
                "validator_run_id": validator_run_id,
                "merge_owner_run_id": "RUN-LEDGER-OWNER",
                "check_state": "not_started",
                "requirement_refs": [],
                "acceptance_criteria_refs": [],
                "artifact_refs": [],
                "evidence_refs": [],
                "harness_refs": [],
            }
        )
    if payload:
        body.update(payload)
    return {
        "schema_version": "goal-teams-v2.3",
        "event_id": event_id,
        "event_type": "task_patch",
        "task_id": task_id,
        "attempt_id": attempt_id or f"ATT-{event_id}",
        "actor_run_id": body.get("owner_run_id", owner_run_id),
        "ledger_owner_run_id": "RUN-LEDGER-OWNER",
        "base_revision": base_revision,
        "timestamp": "2026-07-10T00:00:00Z",
        "payload": body,
    }


def error_tokens(result: Any) -> set[str]:
    """Normalize direct-validator and envelope errors for stable assertions."""
    if isinstance(result, dict):
        raw = result.get("errors", [])
        if not raw and result.get("error_code"):
            raw = [result["error_code"]]
    else:
        raw = result
    tokens: set[str] = set()
    for item in raw or []:
        if isinstance(item, dict):
            tokens.update(str(value) for value in item.values())
        else:
            tokens.add(str(item))
    return tokens


def has_error(result: Any, code: str) -> bool:
    return any(code in token for token in error_tokens(result))
