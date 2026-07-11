#!/usr/bin/env python3
"""Execute and score Goal Teams V2.3 benchmark scenarios with provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
V23_MODULE_DIR = ROOT / "scripts" / "v23"
if str(V23_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(V23_MODULE_DIR))

from package_selection import (  # noqa: E402
    BLIND_PACKAGE_ALLOWLIST,
    PackageSelectionError,
    blind_path_allowed,
    build_blind_package_selection,
)

V23_TOOL = ROOT / "scripts" / "v23" / "goalteams_v23.py"
TASKS_DIR = ROOT / "benchmarks" / "tasks"
REQUIRED_FILES = ["task.md", "harness.md", "scoring.md", "expected-artifacts.md"]
REQUIRED_TERMS = ["baseline", "goal-teams", "scoring"]
BLIND_SCHEMA_VERSION = "goal-teams-blind-eval-v2.3"
BLIND_BOOTSTRAP_REFS = ("AGENTS.md", "SKILL.md", "RULES.md")
BLIND_SUBJECT_PREAMBLE = """你正在盲评当前隔离目录中实际暂存的 Goal Teams V2.3 Skill 包。
必须先读取 AGENTS.md、SKILL.md、RULES.md，再按 SKILL.md 的渐进式路由读取完成本场景所需 references；禁止读取当前隔离目录之外的文件。
不得创建或修改任何文件，不得尝试寻找评分器、manifest、tests、benchmarks 或 canonical answers。
最终只能输出一个严格 JSON 对象，禁止 Markdown 围栏或附加文字；除场景指定字段外，必须额外包含 loaded_refs 数组，列出实际读取的仓库相对路径。

场景：
"""
class BlindEvalError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_path(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repository_commit() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unavailable"


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def check_tasks() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task_dir in sorted(TASKS_DIR.glob("GT-BENCH-*")):
        missing = [name for name in REQUIRED_FILES if not (task_dir / name).is_file()]
        combined = "\n".join(
            (task_dir / name).read_text(encoding="utf-8")
            for name in REQUIRED_FILES
            if (task_dir / name).is_file()
        )
        combined_lower = combined.lower()
        missing_terms = [term for term in REQUIRED_TERMS if term.lower() not in combined_lower]
        rows.append(
            {
                "task": task_dir.name,
                "missing_files": missing,
                "missing_terms": missing_terms,
                "status": "package_structural_valid",
                "behavior_run": "not_counted_until_executed",
            }
        )
    if not rows:
        fail("No benchmark tasks found")
    failures = [row for row in rows if row["missing_files"] or row["missing_terms"]]
    if failures:
        fail(json.dumps(failures, ensure_ascii=False, indent=2))
    return rows


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    scenario_class: str
    command_name: str
    input_value: Any
    expected_returncode: int
    scorer: Callable[[dict[str, Any]], bool]
    prepare: Callable[[Path, Any], list[str]]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prepare_json_command(command: str, *, trailing: list[str] | None = None):
    def prepare(root: Path, value: Any) -> list[str]:
        write_json(root / "input.json", value)
        return [command, "input.json", *(trailing or [])]

    return prepare


def prepare_ledger(root: Path, value: Any) -> list[str]:
    events = value["events"]
    (root / "events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8"
    )
    return ["reduce-ledger", "events.jsonl"]


def prepare_forged_evidence(root: Path, value: Any) -> list[str]:
    (root / "artifact.txt").write_text("artifact\n", encoding="utf-8")
    (root / "run.log").write_text("run\n", encoding="utf-8")
    artifact_stat = (root / "artifact.txt").stat()
    log_stat = (root / "run.log").stat()
    payload = {
        "schema_version": "goal-teams-v2.3",
        "evidence_id": "EVD-FORGED",
        "check_id": "CHECK-FORGED",
        "run_id": "RUN-FORGED",
        "attempt_id": "ATT-FORGED",
        "artifact_ref": "artifact.txt",
        "artifact_sha256": "0" * 64,
        "artifact_size": artifact_stat.st_size,
        "artifact_mtime_ns": artifact_stat.st_mtime_ns,
        "producer_run_id": "RUN-FORGED",
        "created_at": "2026-07-10T00:00:01Z",
        "trust_level": "local_verified",
        "command": {
            "argv": ["false"],
            "cwd": ".",
            "started_at": "2026-07-10T00:00:00Z",
            "ended_at": "2026-07-10T00:00:01Z",
            "exit_code": 0,
            "log_path": "run.log",
            "log_sha256": digest_path(root / "run.log"),
            "log_size": log_stat.st_size,
            "log_mtime_ns": log_stat.st_mtime_ns,
        },
        "environment": {
            "commit": repository_commit(),
            "workspace_revision": repository_commit(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
    }
    write_json(root / "evidence.json", payload)
    return ["validate-evidence", "evidence.json", "--root", "."]


def prepare_self_review(root: Path, value: Any) -> list[str]:
    artifact = root / "artifact.txt"
    artifact.write_text("review target\n", encoding="utf-8")
    artifact_hash = digest_path(artifact)
    write_json(
        root / "script-review.json",
        {"ok": True, "exit_code": 0, "artifact_sha256": artifact_hash, "artifact_version": "V2.3"},
    )
    (root / "semantic-review.md").write_text("---\ntype: Semantic Review\n---\npass\n", encoding="utf-8")
    review = {
        "schema_version": "goal-teams-v2.3",
        "review_class": "comparison",
        "author_run_id": "RUN-SAME",
        "reviewer_run_id": "RUN-SAME",
        "artifact": {
            "artifact_ref": "artifact.txt",
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
        },
        "script_review": {
            "reviewer_run_id": "RUN-SCRIPT",
            "tool": "validate-artifact",
            "status": "passed",
            "exit_code": 0,
            "evidence_path": "script-review.json",
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
        },
        "llm_review": {
            "reviewer_run_id": "RUN-SAME",
            "reviewer": "self",
            "status": "passed",
            "evidence_path": "semantic-review.md",
            "artifact_sha256": artifact_hash,
            "artifact_version": "V2.3",
            "summary": "invalid self review fixture",
        },
        "final_decision": {"status": "pass", "reason": "fixture"},
    }
    write_json(root / "review.json", review)
    return ["validate-dual-review", "review.json", "--root", "."]


def event(event_id: str, task_id: str, revision: int, state: str) -> dict[str, Any]:
    owner_run_id = f"RUN-BENCH-OWNER-{task_id}"
    payload: dict[str, Any] = {"task_state": state}
    if revision == 0:
        payload.update(
            {
                "title": task_id,
                "required_for_done": False,
                "acceptance_blocking": False,
                "owner_member_id": f"owner-{task_id}",
                "owner_run_id": owner_run_id,
                "validator_member_id": f"validator-{task_id}",
                "validator_run_id": f"RUN-BENCH-VALIDATOR-{task_id}",
                "merge_owner_run_id": "RUN-BENCH-LEDGER-OWNER",
                "check_state": "not_started",
                "requirement_refs": [],
                "acceptance_criteria_refs": [],
                "artifact_refs": [],
                "evidence_refs": [],
                "harness_refs": [],
            }
        )
    return {
        "schema_version": "goal-teams-v2.3",
        "event_id": event_id,
        "event_type": "task_patch",
        "task_id": task_id,
        "attempt_id": f"ATT-{event_id}",
        "actor_run_id": owner_run_id,
        "ledger_owner_run_id": "RUN-BENCH-LEDGER-OWNER",
        "base_revision": revision,
        "timestamp": "2026-07-10T00:00:00Z",
        "payload": payload,
    }


def parse_cli_output(output: dict[str, Any]) -> dict[str, Any]:
    value = output.get("envelope")
    return value if isinstance(value, dict) else {}


def route_profile(profile: str):
    return lambda output: parse_cli_output(output).get("route", {}).get("profile") == profile


def capability_field(key: str, expected: Any):
    return lambda output: parse_cli_output(output).get("capability", {}).get(key) == expected


def scenarios() -> list[Scenario]:
    full_capability = json.loads((ROOT / "tests/v23/fixtures/capability/full.json").read_text(encoding="utf-8"))
    restricted_capability = json.loads((ROOT / "tests/v23/fixtures/capability/restricted.json").read_text(encoding="utf-8"))
    telemetry_unavailable = dict(full_capability, telemetry="unavailable")
    recovery_events = [
        event("E1", "TASK-RECOVERY", 0, "planned"),
        event("E2", "TASK-RECOVERY", 1, "running"),
        event("E3", "TASK-RECOVERY", 2, "blocked"),
        event("E4", "TASK-RECOVERY", 3, "running"),
    ]
    conflict_events = [
        event("E1", "TASK-CONFLICT", 0, "planned"),
        event("E2", "TASK-CONFLICT", 0, "running"),
    ]
    return [
        Scenario("plan-preview", "core", "route", {"risk": "low"}, 0, route_profile("lite"), prepare_json_command("route")),
        Scenario("backend-cli", "core", "route", {"backend": True, "tests": True}, 0, route_profile("full"), prepare_json_command("route")),
        Scenario("ui-replica", "core", "route", {"ui": True, "replica": True}, 0, route_profile("full"), prepare_json_command("route")),
        Scenario(
            "long-task-recovery",
            "core",
            "reduce-ledger",
            {"events": recovery_events},
            0,
            lambda output: parse_cli_output(output).get("state", {}).get("tasks", {}).get("TASK-RECOVERY", {}).get("task_state") == "running",
            prepare_ledger,
        ),
        Scenario(
            "revision-conflict",
            "stress",
            "reduce-ledger",
            {"events": conflict_events},
            1,
            lambda output: (
                parse_cli_output(output).get("error_code") == "E_REVISION_CONFLICT"
                and bool(parse_cli_output(output).get("state", {}).get("conflicts"))
            ),
            prepare_ledger,
        ),
        Scenario(
            "forged-evidence",
            "stress",
            "validate-evidence",
            {"mutation": "artifact hash mismatch"},
            1,
            lambda output: parse_cli_output(output).get("ok") is False,
            prepare_forged_evidence,
        ),
        Scenario(
            "self-review",
            "stress",
            "validate-dual-review",
            {"mutation": "author and reviewer share run id"},
            1,
            lambda output: parse_cli_output(output).get("ok") is False,
            prepare_self_review,
        ),
        Scenario(
            "telemetry-unavailable",
            "stress",
            "capability",
            telemetry_unavailable,
            0,
            capability_field("budget_metric", "round_time_member_file_size"),
            prepare_json_command("capability"),
        ),
        Scenario(
            "no-custom-agent",
            "stress",
            "capability",
            restricted_capability,
            0,
            capability_field("dispatch_mode", "generic_subagent_or_serial"),
            prepare_json_command("capability"),
        ),
    ]


def execute_scenario(scenario: Scenario, root: Path) -> dict[str, Any]:
    scenario_root = root / scenario.scenario_id
    scenario_root.mkdir(parents=True)
    argv = scenario.prepare(scenario_root, scenario.input_value)
    started_at = utc_now()
    proc = subprocess.run(
        [sys.executable, str(V23_TOOL), *argv],
        cwd=scenario_root,
        text=True,
        capture_output=True,
        check=False,
    )
    ended_at = utc_now()
    log_path = scenario_root / "subject-run.log"
    log_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        envelope = {"parse_error": True, "stdout": proc.stdout}
    output = {"returncode": proc.returncode, "envelope": envelope}
    trace_path = scenario_root / "trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "command": scenario.command_name,
                "argv": argv,
                "expected_returncode": scenario.expected_returncode,
                "actual_returncode": proc.returncode,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    passed = proc.returncode == scenario.expected_returncode and scenario.scorer(output)
    score_path = scenario_root / "score.json"
    write_json(
        score_path,
        {
            "quality": 1.0 if passed else 0.0,
            "decision": "pass" if passed else "fail",
            "scorer_run_id": f"SCORER-{scenario.scenario_id}",
        },
    )
    record = {
        "schema_version": "goal-teams-v2.3",
        "scenario_id": scenario.scenario_id,
        "scenario_class": scenario.scenario_class,
        "input": scenario.input_value,
        "output": output,
        "executed": True,
        "result": "passed" if passed else "failed",
        "subject_run_id": f"SUBJECT-{scenario.scenario_id}",
        "scorer_run_id": f"SCORER-{scenario.scenario_id}",
        "started_at": started_at,
        "ended_at": ended_at,
        "environment": {
            "commit": repository_commit(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        },
        "provenance": {
            "runner_id": "goal-teams-benchmark-runner",
            "runner_version": "V2.3",
            "run_nonce": f"CONTRACT-{uuid.uuid4().hex}",
            "generated_at": utc_now(),
            "expected_exit_code": scenario.expected_returncode,
            "input_sha256": digest_bytes(canonical_bytes(scenario.input_value)),
            "output_sha256": digest_bytes(canonical_bytes(output)),
            "command": {
                "argv": [sys.executable, str(V23_TOOL), *argv],
                "cwd": ".",
                "exit_code": proc.returncode,
                "log_path": "subject-run.log",
                "log_sha256": digest_path(log_path),
            },
        },
        "trace": [{"path": "trace.jsonl", "sha256": digest_path(trace_path)}],
        "evidence": [{"path": "subject-run.log", "sha256": digest_path(log_path)}],
        "score": {
            "quality": 1.0 if passed else 0.0,
            "rubric_version": "behavior-v2.3",
            "scorer_run_id": f"SCORER-{scenario.scenario_id}",
            "evidence_path": "score.json",
            "evidence_sha256": digest_path(score_path),
        },
    }
    record_path = scenario_root / "record.json"
    write_json(record_path, record)
    validation = subprocess.run(
        [sys.executable, str(V23_TOOL), "validate-behavior", "record.json", "--root", "."],
        cwd=scenario_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if validation.returncode != 0:
        fail(f"{scenario.scenario_id} behavior record invalid: {validation.stdout}{validation.stderr}")
    if not passed:
        fail(f"{scenario.scenario_id} scorer failed: {json.dumps(output, ensure_ascii=False)}")
    return {
        "run": scenario.scenario_id,
        "scenario_class": scenario.scenario_class,
        "status": "executed_validated",
        "quality": 1.0,
    }


def execute_behavior_runs() -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="goal-teams-behavior-") as td:
        root = Path(td)
        return [execute_scenario(scenario, root) for scenario in scenarios()]


def _resolve_argv(argv: Any, output_last_message: Path | None = None) -> list[str]:
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "adapter command must be a non-empty string list")
    executable = shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
    if not executable or not Path(executable).is_file():
        raise BlindEvalError("E_BLIND_AGENT_RUNNER_MISSING", f"runner executable not found: {argv[0]}")
    replacements = {"{output_last_message}": str(output_last_message)} if output_last_message else {}
    return [str(executable), *(replacements.get(item, item) for item in argv[1:])]


def _workspace_status_digest() -> str:
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=False,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        return digest_bytes(proc.stdout)
    return digest_bytes(
        canonical_bytes(
            {
                "mode": "non_git_filesystem",
                "source_tree_sha256": _filesystem_source_digest(ROOT),
            }
        )
    )


_SOURCE_DIGEST_EXCLUDED_PARTS = frozenset(
    {
        ".codex",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "output",
        "outputs",
        "temp",
        "tmp",
    }
)


def _source_path_is_dynamic(relative: Path) -> bool:
    return bool(
        any(
            part in _SOURCE_DIGEST_EXCLUDED_PARTS
            or part.startswith("GoalTeamsWork-")
            for part in relative.parts
        )
        or relative.suffix in {".pyc", ".pyo"}
        or relative.name == ".DS_Store"
    )


def _filesystem_source_digest(root: Path) -> str:
    """Hash a non-Git installed package without treating runtime output as source."""
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if _source_path_is_dynamic(relative):
            continue
        data = path.read_bytes()
        entries.append(
            {
                "path": relative.as_posix(),
                "size": len(data),
                "sha256": digest_bytes(data),
            }
        )
    return digest_bytes(canonical_bytes(entries))


def _source_tree_digest() -> str:
    """Hash every tracked/unignored source file so dirty-state changes cannot hide."""
    proc = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        text=False,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return _filesystem_source_digest(ROOT)
    digest = hashlib.sha256()
    for raw in sorted(item for item in proc.stdout.split(b"\0") if item):
        relative = os.fsdecode(raw)
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def _blind_path_is_forbidden(relative: str) -> bool:
    return not blind_path_allowed(relative)


def _blind_path_is_allowlisted(relative: str) -> bool:
    return any(
        relative == allowed or relative.startswith(allowed.rstrip("/") + "/")
        for allowed in BLIND_PACKAGE_ALLOWLIST
    )


def _blind_package_selection(root: Path = ROOT) -> dict[str, Any]:
    try:
        return build_blind_package_selection(root)
    except PackageSelectionError as exc:
        raise BlindEvalError("E_PACKAGE_IDENTITY", str(exc)) from exc


def _tree_manifest(root: Path) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if ".git" in relative_path.parts:
            continue
        if path.is_symlink():
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_NONREGULAR",
                f"symlink is forbidden in blind package tree: {relative_path.as_posix()}",
            )
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_NONREGULAR",
                f"non-regular entry is forbidden in blind package tree: {relative_path.as_posix()}",
            )
        permissions = stat.S_IMODE(mode)
        if permissions not in {0o644, 0o755}:
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_MODE",
                f"non-canonical file mode in blind package tree: {relative_path.as_posix()}",
            )
        entries.append(
            {
                "path": relative_path.as_posix(),
                "mode": "100755" if permissions == 0o755 else "100644",
                "size": path.stat().st_size,
                "sha256": digest_path(path),
            }
        )
    return entries, digest_bytes(canonical_bytes(entries))


def _stage_blind_package(destination: Path) -> dict[str, Any]:
    selection = _blind_package_selection(ROOT)
    destination.mkdir(parents=True, exist_ok=False)
    for selected_entry in selection["blind_safe_entries"]:
        relative = selected_entry["path"]
        expected_mode = selected_entry["mode"]
        if expected_mode not in {"100644", "100755"}:
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_MODE",
                f"tracked package path has unsupported Git mode {expected_mode}: {relative}",
            )
        source = ROOT / relative
        if source.is_symlink() or not source.exists():
            raise BlindEvalError("E_BLIND_AGENT_STAGE", f"tracked package path is missing or unsafe: {relative}")
        source_mode = source.lstat().st_mode
        if not stat.S_ISREG(source_mode):
            raise BlindEvalError("E_BLIND_AGENT_STAGE", f"tracked package path is not a regular file: {relative}")
        file_mode = stat.S_IMODE(source_mode)
        expected_permissions = 0o755 if expected_mode == "100755" else 0o644
        if file_mode != expected_permissions:
            raise BlindEvalError(
                "E_BLIND_AGENT_STAGE_MODE",
                f"Git index/worktree mode drift for package path: {relative}",
            )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    entries, package_digest = _tree_manifest(destination)
    staged_paths = [entry["path"] for entry in entries]
    if entries != selection["files"] or package_digest != selection["package_sha256"]:
        raise BlindEvalError(
            "E_PACKAGE_IDENTITY",
            "staged bytes or modes differ from the pre-copy package selection",
        )
    leaked = [entry["path"] for entry in entries if _blind_path_is_forbidden(entry["path"])]
    if leaked:
        raise BlindEvalError("E_BLIND_AGENT_STAGE_LEAK", f"forbidden package paths staged: {leaked}")
    if staged_paths != selection["blind_safe_paths"]:
        raise BlindEvalError(
            "E_BLIND_AGENT_STAGE_SELECTION",
            "staged paths differ from the installer manifest Git-index projection",
        )
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    subprocess.run(["git", "config", "user.email", "blind-eval@example.invalid"], cwd=destination, check=True)
    subprocess.run(["git", "config", "user.name", "Goal Teams Blind Eval"], cwd=destination, check=True)
    subprocess.run(["git", "add", "--all"], cwd=destination, check=True)
    subprocess.run(["git", "commit", "-qm", "stage Goal Teams V2.3 package"], cwd=destination, check=True)
    staged_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=destination, text=True, capture_output=True, check=True
    ).stdout.strip()
    return {
        "source_commit": repository_commit(),
        "package_manifest_path": selection["package_manifest_path"],
        "package_manifest_sha256": selection["package_manifest_sha256"],
        "installer_tracked_paths_sha256": selection["installer_tracked_paths_sha256"],
        "installer_tracked_entries_sha256": selection["installer_tracked_entries_sha256"],
        "blind_safe_paths_sha256": selection["blind_safe_paths_sha256"],
        "blind_safe_entries_sha256": selection["blind_safe_entries_sha256"],
        "forbidden_exclusions": selection["forbidden_exclusions"],
        "forbidden_exclusions_sha256": selection["forbidden_exclusions_sha256"],
        "blind_safe_allowlist": selection["blind_safe_allowlist"],
        "blind_safe_allowlist_sha256": selection["blind_safe_allowlist_sha256"],
        "excluded_untracked": selection["excluded_untracked"],
        "file_count": len(entries),
        "files": entries,
        "package_sha256": package_digest,
        "staged_git_commit": staged_commit,
    }


def _commit_subject_input(workspace: Path, subject_input: dict[str, Any]) -> str:
    write_json(workspace / "scenario-input.json", subject_input)
    subprocess.run(["git", "add", "scenario-input.json"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "add blind scenario input"], cwd=workspace, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workspace, text=True, capture_output=True, check=True
    ).stdout.strip()


def _load_blind_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", f"invalid manifest: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != BLIND_SCHEMA_VERSION:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "blind eval manifest schema mismatch")
    if not isinstance(payload.get("adapter"), dict) or not isinstance(payload.get("scenarios"), list) or not payload["scenarios"]:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "blind eval manifest requires adapter and scenarios")
    return payload


_MISSING = object()


def _effective_blind_scorer(scorer: Any) -> Any:
    if not isinstance(scorer, dict):
        return scorer
    effective = json.loads(json.dumps(scorer, ensure_ascii=False))
    allowed = effective.get("allowed_fields")
    required = effective.get("required_fields")
    if isinstance(allowed, list) and "loaded_refs" not in allowed:
        allowed.append("loaded_refs")
    if isinstance(required, list) and not any(
        isinstance(item, dict) and item.get("path") == "loaded_refs" for item in required
    ):
        required.append(
            {
                "path": "loaded_refs",
                "value_type": "array",
                "contains_all": list(BLIND_BOOTSTRAP_REFS),
            }
        )
    return effective


def _json_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _typed(value: Any, expected: str) -> bool:
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return False


def _score_blind_output(
    output: str,
    scorer: Any,
    subject_input: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not isinstance(scorer, dict):
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "scenario scorer must be an object")
    if scorer.get("type") != "json_contract":
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "blind scorer type must be json_contract")
    required = scorer.get("required_fields")
    allowed = scorer.get("allowed_fields")
    forbidden = scorer.get("forbidden_fields", [])
    bindings = scorer.get("input_bindings", [])
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in required)
        or not isinstance(allowed, list)
        or not all(isinstance(item, str) and item for item in allowed)
        or not isinstance(forbidden, list)
        or not all(isinstance(item, str) and item for item in forbidden)
        or not isinstance(bindings, list)
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("input_path"), str)
            and isinstance(item.get("output_path"), str)
            for item in bindings
        )
    ):
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "typed blind scorer fields are invalid")
    rubric_sha256 = digest_bytes(canonical_bytes(scorer))
    try:
        parsed = json.loads(output.strip())
    except json.JSONDecodeError as exc:
        return False, {
            "error_code": "E_BLIND_AGENT_OUTPUT_JSON",
            "parse_error": str(exc),
            "rubric_sha256": rubric_sha256,
        }
    if not isinstance(parsed, dict):
        return False, {
            "error_code": "E_BLIND_AGENT_OUTPUT_TYPE",
            "observed_type": type(parsed).__name__,
            "rubric_sha256": rubric_sha256,
        }
    violations: list[dict[str, Any]] = []
    for contract in required:
        path = contract["path"]
        value = _json_path(parsed, path)
        expected_type = contract.get("value_type")
        if value is _MISSING:
            violations.append({"path": path, "violation": "missing"})
            continue
        if not isinstance(expected_type, str) or not _typed(value, expected_type):
            violations.append(
                {"path": path, "violation": "type", "expected": expected_type, "observed": type(value).__name__}
            )
            continue
        if "equals" in contract and value != contract["equals"]:
            violations.append({"path": path, "violation": "equals"})
        if "enum" in contract and (not isinstance(contract["enum"], list) or value not in contract["enum"]):
            violations.append({"path": path, "violation": "enum"})
        if contract.get("nonempty") is True and not value:
            violations.append({"path": path, "violation": "nonempty"})
        minimum = contract.get("min_length")
        if minimum is not None and (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or not hasattr(value, "__len__")
            or len(value) < minimum
        ):
            violations.append({"path": path, "violation": "min_length"})
        contains_all = contract.get("contains_all")
        if contains_all is not None and (
            not isinstance(value, list)
            or not isinstance(contains_all, list)
            or not all(item in value for item in contains_all)
        ):
            violations.append({"path": path, "violation": "contains_all"})
    unexpected = sorted(set(parsed) - set(allowed))
    forbidden_present = sorted(path for path in forbidden if _json_path(parsed, path) is not _MISSING)
    for binding in bindings:
        expected = _json_path(subject_input or {}, binding["input_path"])
        observed = _json_path(parsed, binding["output_path"])
        if expected is _MISSING or observed is _MISSING or observed != expected:
            violations.append({"path": binding["output_path"], "violation": "input_binding"})
    if unexpected:
        violations.append({"paths": unexpected, "violation": "unexpected_fields"})
    if forbidden_present:
        violations.append({"paths": forbidden_present, "violation": "forbidden_fields"})
    return not violations, {
        "error_code": None if not violations else "E_BLIND_AGENT_OUTPUT_CONTRACT",
        "parsed_json": parsed,
        "violations": violations,
        "rubric_sha256": rubric_sha256,
        "required_field_count": len(required),
        "allowed_fields": sorted(allowed),
    }


def execute_blind_agent_eval(
    manifest_path: Path,
    output_dir: Path,
    *,
    release_gate: bool,
    selected_scenarios: set[str] | None = None,
) -> dict[str, Any]:
    manifest = _load_blind_manifest(manifest_path)
    adapter = manifest["adapter"]
    adapter_type = adapter.get("type")
    provider = adapter.get("provider")
    if adapter_type not in {"codex_cli", "fixture"} or not isinstance(provider, str) or not provider:
        raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "adapter type/provider is invalid")
    scenarios_to_run = [
        scenario
        for scenario in manifest["scenarios"]
        if isinstance(scenario, dict)
        and (not selected_scenarios or scenario.get("scenario_id") in selected_scenarios)
    ]
    required_ids = {
        scenario.get("scenario_id")
        for scenario in manifest["scenarios"]
        if isinstance(scenario, dict) and scenario.get("required") is True
    }
    selected_ids = {scenario.get("scenario_id") for scenario in scenarios_to_run}
    if not scenarios_to_run or (release_gate and not required_ids <= selected_ids):
        raise BlindEvalError("E_BLIND_AGENT_INCOMPLETE", "release eval must execute every required scenario")
    try:
        output_dir.resolve().relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise BlindEvalError(
            "E_BLIND_AGENT_OUTPUT_SCOPE",
            "blind output must be persistent and outside the source repository",
        )
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise BlindEvalError("E_BLIND_AGENT_OUTPUT_EXISTS", "output directory must be new for this invocation") from exc
    invocation_id = f"BLIND-{uuid.uuid4().hex}"
    source_commit = repository_commit()
    source_status_before = _workspace_status_digest()
    source_tree_before = _source_tree_digest()
    runner_path = Path(__file__).resolve()
    runner_provenance = {
        "path": str(runner_path),
        "sha256": digest_path(runner_path),
        "size": runner_path.stat().st_size,
    }
    effective_rubrics = {
        str(scenario.get("scenario_id")): _effective_blind_scorer(scenario.get("scorer"))
        for scenario in scenarios_to_run
    }
    rubric_sha256 = digest_bytes(
        canonical_bytes(
            [
                {
                    "scenario_id": scenario_id,
                    "rubric_sha256": digest_bytes(canonical_bytes(rubric)),
                }
                for scenario_id, rubric in sorted(effective_rubrics.items())
            ]
        )
    )
    records: list[dict[str, Any]] = []
    record_refs: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="goal-teams-v23-isolated-") as td:
        isolation_root = Path(td).resolve()
        staged_root = isolation_root / "staged-package"
        stage = _stage_blind_package(staged_root)
        shutil.copytree(
            staged_root,
            output_dir / "staged-package",
            ignore=shutil.ignore_patterns(".git"),
        )
        write_json(output_dir / "stage-manifest.json", stage)
        stage_manifest_hash = digest_path(output_dir / "stage-manifest.json")
        version_argv = _resolve_argv(adapter.get("version_command"))
        version_proc = subprocess.run(
            version_argv, cwd=staged_root, text=True, capture_output=True, check=False
        )
        provider_version = (version_proc.stdout + version_proc.stderr).strip()
        executable = Path(_resolve_argv(adapter.get("command"))[0]).resolve()
        provider_provenance = {
            "adapter_type": adapter_type,
            "provider": provider,
            "provider_trust_level": "local_process_attested",
            "provider_version": provider_version,
            "version_argv": version_argv,
            "version_exit_code": version_proc.returncode,
            "executable": str(executable),
            "executable_sha256": digest_path(executable),
            "invocation_id": invocation_id,
            "source_commit": source_commit,
            "staged_package_sha256": stage["package_sha256"],
            "staged_package_commit": stage["staged_git_commit"],
            "stage_manifest_sha256": stage_manifest_hash,
            "package_manifest_sha256": stage["package_manifest_sha256"],
            "installer_tracked_entries_sha256": stage["installer_tracked_entries_sha256"],
            "blind_safe_entries_sha256": stage["blind_safe_entries_sha256"],
            "forbidden_exclusions_sha256": stage["forbidden_exclusions_sha256"],
            "blind_safe_allowlist_sha256": stage["blind_safe_allowlist_sha256"],
        }
        for scenario in scenarios_to_run:
            scenario_id = scenario.get("scenario_id")
            prompt = scenario.get("prompt")
            context = scenario.get("subject_input", {})
            if (
                not isinstance(scenario_id, str)
                or not scenario_id
                or not isinstance(prompt, str)
                or not prompt
                or not isinstance(context, dict)
            ):
                raise BlindEvalError("E_BLIND_AGENT_MANIFEST", "scenario id/prompt/subject_input is invalid")
            scenario_dir = output_dir / scenario_id
            scenario_dir.mkdir()
            subject_prompt = BLIND_SUBJECT_PREAMBLE + prompt
            subject_input = {
                "scenario_id": scenario_id,
                "prompt": subject_prompt,
                "context": context,
                "bootstrap_refs_required": list(BLIND_BOOTSTRAP_REFS),
                "response_contract": "one strict JSON object; no Markdown fences or prose",
            }
            write_json(scenario_dir / "input.json", subject_input)
            workspace = isolation_root / "workspaces" / scenario_id
            workspace.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(staged_root, workspace)
            scenario_commit = _commit_subject_input(workspace, subject_input)
            workspace_entries_before, workspace_digest_before = _tree_manifest(workspace)
            output_last_message = scenario_dir / "output.txt"
            command = _resolve_argv(adapter.get("command"), output_last_message)
            source_tree_pre_scenario = _source_tree_digest()
            source_status_pre_scenario = _workspace_status_digest()
            started_at = utc_now()
            proc = subprocess.run(
                command,
                cwd=workspace,
                input=subject_prompt,
                text=True,
                capture_output=True,
                check=False,
            )
            ended_at = utc_now()
            (scenario_dir / "stdout.log").write_text(proc.stdout, encoding="utf-8")
            (scenario_dir / "stderr.log").write_text(proc.stderr, encoding="utf-8")
            if not output_last_message.is_file():
                output_last_message.write_text(proc.stdout, encoding="utf-8")
            output_text = output_last_message.read_text(encoding="utf-8")
            _, workspace_digest_after = _tree_manifest(workspace)
            workspace_commit_after = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace,
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
            source_tree_post_scenario = _source_tree_digest()
            source_status_post_scenario = _workspace_status_digest()
            effective_rubric = effective_rubrics[scenario_id]
            score_passed, score_details = _score_blind_output(output_text, effective_rubric, subject_input)
            workspace_unchanged = workspace_digest_before == workspace_digest_after
            source_unchanged = (
                source_tree_pre_scenario == source_tree_post_scenario
                and source_status_pre_scenario == source_status_post_scenario
            )
            passed = proc.returncode == 0 and score_passed and workspace_unchanged and source_unchanged
            scorer_run_id = f"SCORER-{invocation_id}-{scenario_id}"
            subject_run_id = f"SUBJECT-{invocation_id}-{scenario_id}"
            rubric = effective_rubric
            (scenario_dir / "rubric.json").write_bytes(canonical_bytes(rubric))
            score = {
                "schema_version": "goal-teams-blind-score-v2.3",
                "quality": 1.0 if passed else 0.0,
                "decision": "pass" if passed else "fail",
                "scorer_run_id": scorer_run_id,
                "workspace_unchanged": workspace_unchanged,
                "source_repository_unchanged": source_unchanged,
                "rubric_path": "rubric.json",
                "rubric_sha256": digest_path(scenario_dir / "rubric.json"),
                **score_details,
            }
            write_json(scenario_dir / "score.json", score)
            evaluation_class = "blind_agent" if adapter_type == "codex_cli" else "pipeline_fixture"
            release_eligible = bool(
                evaluation_class == "blind_agent"
                and provider == "openai-codex-cli"
                and version_proc.returncode == 0
                and "codex-cli" in provider_version.lower()
                and passed
                and stage["file_count"] > 0
                and not any(
                    _blind_path_is_forbidden(entry["path"])
                    for entry in workspace_entries_before
                    if entry["path"] != "scenario-input.json"
                )
            )
            output_value = {
                "parsed_json": score_details.get("parsed_json"),
                "subject_exit_code": proc.returncode,
            }
            record = {
                "schema_version": "goal-teams-v2.3",
                "scenario_id": scenario_id,
                "scenario_class": scenario.get("scenario_class", "core"),
                "evaluation_class": evaluation_class,
                "provider_trust_level": "local_process_attested",
                "release_eligible": release_eligible,
                "input": subject_input,
                "output": output_value,
                "executed": True,
                "result": "passed" if passed else "failed",
                "subject_run_id": subject_run_id,
                "scorer_run_id": scorer_run_id,
                "started_at": started_at,
                "ended_at": ended_at,
                "environment": {
                    "commit": source_commit,
                    "platform": platform.platform(),
                    "python_version": platform.python_version(),
                },
                "provider_provenance": provider_provenance,
                "isolation": {
                    "isolated_workspace": True,
                    "workspace_id": f"{invocation_id}-{scenario_id}",
                    "execution_cwd": str(workspace),
                    "workspace_git_commit": scenario_commit,
                    "workspace_git_commit_before": scenario_commit,
                    "workspace_git_commit_after": workspace_commit_after,
                    "workspace_sha256_before": workspace_digest_before,
                    "workspace_sha256_after": workspace_digest_after,
                    "workspace_unchanged": workspace_unchanged,
                    "source_tree_sha256_before": source_tree_pre_scenario,
                    "source_tree_sha256_after": source_tree_post_scenario,
                    "source_status_sha256_before": source_status_pre_scenario,
                    "source_status_sha256_after": source_status_post_scenario,
                    "source_repository_unchanged": source_unchanged,
                    "scorer_staged_with_subject": False,
                    "manifest_staged_with_subject": False,
                    "answer_bearing_roots_staged": False,
                    "bootstrap_refs_required": list(BLIND_BOOTSTRAP_REFS),
                    "subject_declared_loaded_refs": score_details.get("parsed_json", {}).get("loaded_refs", [])
                    if isinstance(score_details.get("parsed_json"), dict)
                    else [],
                },
                "provenance": {
                    "runner_id": "goal-teams-blind-agent-runner",
                    "runner_version": "V2.3",
                    "run_nonce": f"{invocation_id}-{scenario_id}",
                    "generated_at": utc_now(),
                    "expected_exit_code": 0,
                    "input_sha256": digest_bytes(canonical_bytes(subject_input)),
                    "output_sha256": digest_bytes(canonical_bytes(output_value)),
                    "command": {
                        "argv": command,
                        "cwd": str(workspace),
                        "exit_code": proc.returncode,
                        "log_path": "stdout.log",
                        "log_sha256": digest_path(scenario_dir / "stdout.log"),
                        "stdout_path": "stdout.log",
                        "stdout_sha256": digest_path(scenario_dir / "stdout.log"),
                        "stderr_path": "stderr.log",
                        "stderr_sha256": digest_path(scenario_dir / "stderr.log"),
                    },
                },
                "trace": [{"path": "stdout.log", "sha256": digest_path(scenario_dir / "stdout.log")}],
                "evidence": [
                    {"path": "output.txt", "sha256": digest_path(output_last_message)},
                    {"path": "stderr.log", "sha256": digest_path(scenario_dir / "stderr.log")},
                    {"path": "rubric.json", "sha256": digest_path(scenario_dir / "rubric.json")},
                ],
                "score": {
                    "quality": score["quality"],
                    "rubric_version": "blind-agent-json-contract-v2.3",
                    "rubric_sha256": score["rubric_sha256"],
                    "evaluation_rubric_sha256": rubric_sha256,
                    "scorer_run_id": scorer_run_id,
                    "evidence_path": "score.json",
                    "evidence_sha256": digest_path(scenario_dir / "score.json"),
                },
            }
            record_path = scenario_dir / "record.json"
            write_json(record_path, record)
            record_refs.append(
                {
                    "scenario_id": scenario_id,
                    "path": f"{scenario_id}/record.json",
                    "sha256": digest_path(record_path),
                    "size": record_path.stat().st_size,
                }
            )
            records.append(record)
    source_tree_after = _source_tree_digest()
    source_status_after = _workspace_status_digest()
    source_repository_unchanged = (
        source_tree_before == source_tree_after and source_status_before == source_status_after
    )
    write_json(output_dir / "manifest.json", manifest)
    source_provenance = {
        "source_commit": source_commit,
        "source_tree_digest_before": source_tree_before,
        "source_tree_digest_after": source_tree_after,
        "source_status_digest_before": source_status_before,
        "source_status_digest_after": source_status_after,
        "source_repository_unchanged": source_repository_unchanged,
    }
    staged_manifest = {
        "path": "stage-manifest.json",
        "sha256": digest_path(output_dir / "stage-manifest.json"),
        "size": (output_dir / "stage-manifest.json").stat().st_size,
        "package_root": "staged-package",
        "staged_tree_digest": stage["package_sha256"],
        "staged_git_commit": stage["staged_git_commit"],
        "package_manifest_path": stage["package_manifest_path"],
        "package_manifest_sha256": stage["package_manifest_sha256"],
        "installer_tracked_paths_sha256": stage["installer_tracked_paths_sha256"],
        "installer_tracked_entries_sha256": stage["installer_tracked_entries_sha256"],
        "blind_safe_paths_sha256": stage["blind_safe_paths_sha256"],
        "blind_safe_entries_sha256": stage["blind_safe_entries_sha256"],
        "forbidden_exclusions_sha256": stage["forbidden_exclusions_sha256"],
        "blind_safe_allowlist_sha256": stage["blind_safe_allowlist_sha256"],
    }
    # Bind the global source/stage/rubric facts into every record after all
    # subject invocations have completed, then refresh record hashes/sizes.
    for index, ref in enumerate(record_refs):
        record_path = output_dir / ref["path"]
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["source_provenance"] = source_provenance
        record["staged_manifest"] = staged_manifest
        record["evaluation_rubric_sha256"] = rubric_sha256
        record["runner_provenance"] = runner_provenance
        write_json(record_path, record)
        ref["sha256"] = digest_path(record_path)
        ref["size"] = record_path.stat().st_size
        records[index] = record
    passed_ids = {record["scenario_id"] for record in records if record["result"] == "passed"}
    release_eligible_ids = {record["scenario_id"] for record in records if record["release_eligible"]}
    summary = {
        "schema_version": BLIND_SCHEMA_VERSION,
        "evaluation_id": manifest.get("evaluation_id"),
        "invocation_id": invocation_id,
        "evaluation_class": "blind_agent" if adapter_type == "codex_cli" else "pipeline_fixture",
        "provider_trust_level": "local_process_attested",
        "provider_provenance": provider_provenance,
        "manifest_source_path": str(manifest_path),
        "manifest_source_sha256": digest_path(manifest_path),
        "source_provenance": source_provenance,
        "staged_manifest": staged_manifest,
        "rubric_sha256": rubric_sha256,
        "runner_provenance": runner_provenance,
        "source_repository_unchanged": source_repository_unchanged,
        "required_scenarios": sorted(required_ids),
        "passed_scenarios": sorted(passed_ids),
        "release_eligible_scenarios": sorted(release_eligible_ids),
        "records": record_refs,
        "output_dir": str(output_dir.resolve()),
        "release_gate_passed": source_repository_unchanged and required_ids <= release_eligible_ids,
    }
    write_json(output_dir / "summary.json", summary)
    if release_gate and adapter_type != "codex_cli":
        raise BlindEvalError("E_BLIND_AGENT_FIXTURE", "fixture/mock runner cannot satisfy Behavior Release Gate")
    if release_gate and not summary["release_gate_passed"]:
        raise BlindEvalError("E_BLIND_AGENT_FAILED", "required blind-agent scenarios did not all pass")
    return summary


def write_report(rows: list[dict[str, object]], output: Path) -> None:
    payload = {
        "generated_at": utc_now(),
        "row_count": len(rows),
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".json":
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return
    lines = [
        "# Goal Teams Benchmark Report",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- row_count: {len(rows)}",
        "",
        "| Item | Status | Behavior |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        item = row.get("task", row.get("run", "unknown"))
        lines.append(f"| {item} | {row['status']} | {row.get('behavior_run', 'fresh execution')} |")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["contract", "blind-agent"], default="contract")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--output", default="benchmarks/runs/latest-report.md")
    args = parser.parse_args()
    try:
        if args.mode == "contract":
            if args.release_gate:
                raise BlindEvalError(
                    "E_BLIND_AGENT_REQUIRED",
                    "deterministic contract fixtures do not satisfy Behavior Release Gate",
                )
            package_rows = check_tasks()
            contract_rows = execute_behavior_runs()
            if not args.check_only:
                write_report(package_rows + contract_rows, ROOT / args.output)
            print(
                f"Deterministic contract validation passed for {len(package_rows)} packages and "
                f"{len(contract_rows)} fixture scenarios; this does not satisfy Behavior Gate."
            )
            return
        if args.manifest is None or args.output_dir is None:
            raise BlindEvalError(
                "E_BLIND_AGENT_ARGUMENTS",
                "blind-agent mode requires --manifest and a new persistent --output-dir",
            )
        summary = execute_blind_agent_eval(
            args.manifest.resolve(),
            args.output_dir.resolve(),
            release_gate=args.release_gate,
            selected_scenarios=set(args.scenario) or None,
        )
        print(json.dumps({"ok": True, "error_code": None, **summary}, ensure_ascii=False, sort_keys=True))
    except BlindEvalError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "schema_version": BLIND_SCHEMA_VERSION,
                    "error_code": exc.code,
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
