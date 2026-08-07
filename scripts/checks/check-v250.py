#!/usr/bin/env python3
"""V2.6 route-aware development and final-release checker."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "references/current/generations/V2.6/contracts"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TEST_COUNT_RE = re.compile(r"Ran ([0-9]+) tests? in ")
_COMMAND_EXECUTION_COUNT = 0


def _run_subprocess(
    *args: Any,
    command_counter: dict[str, int] | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run one child process and record it before launch, including failures."""

    global _COMMAND_EXECUTION_COUNT
    _COMMAND_EXECUTION_COUNT += 1
    if command_counter is not None:
        command_counter["count"] = command_counter.get("count", 0) + 1
    return subprocess.run(*args, **kwargs)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"unsafe or missing JSON: {path.relative_to(ROOT)}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path.relative_to(ROOT)}")
    return value


def validate_contracts() -> dict[str, Any]:
    required = {
        "release-route-manifest.json": "goal-teams-v2.6-release-route-v1",
        "release-command-manifest.json": "goal-teams-v2.6-release-command-manifest-v1",
        "release-security-review-manifest.json": "goal-teams-v2.6-release-security-review-v2",
        "public-asset-map.json": "goal-teams-v2.6-public-asset-map-v1",
    }
    errors: list[str] = []
    values: dict[str, dict[str, Any]] = {}
    for name, schema_version in required.items():
        try:
            value = _read_json(CONTRACT_ROOT / name)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"E_V250_CONTRACT:{name}:{type(exc).__name__}")
            continue
        values[name] = value
        if value.get("schema_version") != schema_version:
            errors.append(f"E_V250_CONTRACT_SCHEMA:{name}")
    assets = values.get("public-asset-map.json", {})
    expected_assets = {
        "goal-teams-V2.6.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    }
    observed_assets = {
        item.get("name") for item in assets.get("assets", []) if isinstance(item, dict)
    }
    if assets.get("asset_count") != 4 or observed_assets != expected_assets:
        errors.append("E_V250_PUBLIC_ASSET_MAP")
    command = values.get("release-command-manifest.json", {})
    denominator = command.get("release", {}).get("s1", {}).get(
        "current_full_regression_denominator", {}
    )
    if (
        denominator.get("denominator_id") != "V250-CURRENT-GENERATION-FULL"
        or denominator.get("test_root") != "tests/v250"
        or denominator.get("test_pattern") != "test_*.py"
        or denominator.get("legacy_roots_excluded") != ["tests/v23", "tests/v249"]
    ):
        errors.append("E_V250_CURRENT_DENOMINATOR_CONTRACT")
    return {
        "ok": not errors,
        "passed": not errors,
        "errors": errors,
        "contract_count": len(values),
    }


def _git_run(*args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return _run_subprocess(
        ["git", "--no-replace-objects", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=text,
        env={
            **os.environ,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )


def _git_text(*args: str) -> str:
    result = _git_run(*args)
    if result.returncode != 0:
        raise ValueError("E_V250_RELEASE_GIT_IDENTITY")
    return str(result.stdout).strip()


def _git_bytes(*args: str) -> bytes:
    result = _git_run(*args, text=False)
    if result.returncode != 0:
        raise ValueError("E_V250_RELEASE_GIT_IDENTITY")
    return bytes(result.stdout)


def _released_identity(
    source_commit: str | None, source_tree: str | None
) -> tuple[str, str, dict[str, Any]]:
    """Require HEAD, index, worktree, and caller identity to be exact/clean."""

    if source_commit is None or source_tree is None:
        raise ValueError("E_V250_RELEASE_IDENTITY_REQUIRED")
    commit = source_commit
    tree = source_tree
    if COMMIT_RE.fullmatch(commit) is None or COMMIT_RE.fullmatch(tree) is None:
        raise ValueError("E_V250_RELEASE_IDENTITY")
    root = Path(_git_text("rev-parse", "--show-toplevel")).resolve()
    if root != ROOT.resolve():
        raise ValueError("E_V250_RELEASE_WORKTREE_ROOT")
    head = _git_text("rev-parse", "HEAD^{commit}")
    if head != commit:
        raise ValueError("E_V250_RELEASE_COMMIT_DRIFT")
    resolved_tree = _git_text("rev-parse", f"{commit}^{{tree}}")
    if resolved_tree != tree:
        raise ValueError("E_V250_RELEASE_TREE_DRIFT")
    status_result = _git_run("status", "--porcelain=v1", "--untracked-files=all")
    if status_result.returncode != 0:
        raise ValueError("E_V250_RELEASE_WORKTREE_STATUS")
    status = str(status_result.stdout)
    if status:
        raise ValueError("E_V250_RELEASE_WORKTREE_DIRTY")
    for argv in (("diff", "--quiet", commit, "--"), ("diff", "--cached", "--quiet", commit, "--")):
        if _git_run(*argv).returncode != 0:
            raise ValueError("E_V250_RELEASE_WORKTREE_DIRTY")
    return commit, tree, {
        "binding_kind": "exact_clean_worktree",
        "head_commit": head,
        "head_tree": resolved_tree,
        "status_porcelain_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "dirty_entry_count": 0,
        "untracked_entry_count": 0,
    }


def _current_test_denominator(
    source_commit: str,
    *,
    observed_test_count: int,
    release_flow: ModuleType,
) -> dict[str, Any]:
    tracked = _git_text(
        "ls-tree", "-r", "--name-only", source_commit, "--", "tests/v250"
    ).splitlines()
    paths = sorted(
        path
        for path in tracked
        if path.startswith("tests/v250/")
        and Path(path).name.startswith("test_")
        and path.endswith(".py")
    )
    filesystem_paths = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests/v250").rglob("test_*.py")
        if path.is_file() and not path.is_symlink()
    )
    if not paths or paths != filesystem_paths:
        raise ValueError("E_V250_CURRENT_DENOMINATOR_FILE_DRIFT")
    files: list[dict[str, str]] = []
    for relative in paths:
        frozen = _git_bytes("show", f"{source_commit}:{relative}")
        current = (ROOT / relative).read_bytes()
        if current != frozen:
            raise ValueError("E_V250_CURRENT_DENOMINATOR_CONTENT_DRIFT")
        files.append(
            {"path": relative, "sha256": hashlib.sha256(frozen).hexdigest()}
        )
    denominator: dict[str, Any] = {
        "denominator_id": "V250-CURRENT-GENERATION-FULL",
        "generation_id": "V2.6",
        "scope": "current_generation_full_regression",
        "source_commit": source_commit,
        "source_tree": _git_text("rev-parse", f"{source_commit}^{{tree}}"),
        "test_root": "tests/v250",
        "test_pattern": "test_*.py",
        "contract_path": "references/current/generations/V2.6/contracts/release-command-manifest.json",
        "contract_sha256": hashlib.sha256(
            (CONTRACT_ROOT / "release-command-manifest.json").read_bytes()
        ).hexdigest(),
        "test_files": files,
        "test_file_count": len(files),
        "test_file_set_sha256": release_flow.canonical_sha256(files),
        "test_case_count": observed_test_count,
        "legacy_roots_excluded": ["tests/v23", "tests/v249"],
    }
    denominator["denominator_sha256"] = release_flow.canonical_sha256(denominator)
    return denominator


def run_full_regression(
    source_commit: str,
    source_tree: str,
    worktree_binding: dict[str, Any],
    release_flow: ModuleType,
    *,
    command_counter: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Run the complete frozen V2.6 Current-generation denominator once."""

    argv = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-v",
        "-s",
        "tests/v250",
        "-p",
        "test_*.py",
    ]
    result = _run_subprocess(
        argv,
        command_counter=command_counter,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    combined = result.stdout + result.stderr
    output = combined.encode("utf-8", errors="replace")
    matches = TEST_COUNT_RE.findall(combined)
    observed_count = int(matches[-1]) if matches else 0
    denominator = _current_test_denominator(
        source_commit,
        observed_test_count=observed_count,
        release_flow=release_flow,
    )
    passed = result.returncode == 0 and observed_count > 0
    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-v2.6-release-gate-receipt-v1",
        "gate_id": "full_regression",
        "run_id": f"V250-CURRENT-FULL-{source_commit[:12]}-{uuid.uuid4().hex}",
        "runner_role": "current_generation_full_regression",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "execution_source": "exact_clean_worktree",
        "worktree_binding": worktree_binding,
        "denominator": denominator,
        "discovered_test_count": observed_count,
        "legacy_test_invocation_count": 0,
        "check_state": "passed" if passed else "failed",
        "evidence_state": "current",
        "run_outcome": "passed" if passed else "failed",
        "invocation_count_for_released_identity": 1,
        "argv": argv,
        "cwd": ".",
        "returncode": result.returncode,
        "output_sha256": hashlib.sha256(output).hexdigest(),
    }
    receipt["receipt_sha256"] = release_flow.canonical_sha256(receipt)
    return receipt


def run_release_security_review(
    source_commit: str,
    source_tree: str,
    *,
    command_counter: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Launch the exact released-implementation reviewer in a fresh process."""

    review_run_id = f"V250-SECURITY-{source_commit[:12]}-{uuid.uuid4().hex}"
    argv = [
        sys.executable,
        "scripts/checks/run-v250-release-security-review.py",
        "--source-commit",
        source_commit,
        "--source-tree",
        source_tree,
        "--reviewer-id",
        "goal-teams-v250-release-implementation-security-reviewer",
        "--review-run-id",
        review_run_id,
        "--orchestrator-pid",
        str(os.getpid()),
    ]
    result = _run_subprocess(
        argv,
        command_counter=command_counter,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    try:
        receipt = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("E_V250_SECURITY_REVIEW_OUTPUT") from exc
    if not isinstance(receipt, dict):
        raise ValueError("E_V250_SECURITY_REVIEW_OUTPUT")
    if result.returncode != 0:
        return receipt
    if (
        receipt.get("review_run_id") != review_run_id
        or receipt.get("orchestrator_pid") != os.getpid()
        or receipt.get("runner_pid") == os.getpid()
    ):
        raise ValueError("E_V250_SECURITY_REVIEW_PROCESS_BINDING")
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("development", "release"), default="development"
    )
    parser.add_argument(
        "--project-size",
        choices=("discussion", "small", "medium", "large"),
        default="medium",
    )
    parser.add_argument("--stage", choices=("candidate", "released"), default="candidate")
    parser.add_argument("--release-intent", action="store_true")
    parser.add_argument("--implementation-scope-complete", action="store_true")
    parser.add_argument("--s1-current", action="store_true")
    parser.add_argument("--source-commit")
    parser.add_argument("--source-tree")
    parser.add_argument("--released-runtime-receipt", type=Path)
    parser.add_argument("--expected-host-execution-id")
    return parser.parse_args()


def main() -> int:
    global _COMMAND_EXECUTION_COUNT
    _COMMAND_EXECUTION_COUNT = 0
    args = parse_args()
    command_counter = {"count": 0}
    contract_result = validate_contracts()
    release_flow = _load_module(
        "_goalteams_v250_release_flow", ROOT / "scripts/v250/release_flow.py"
    )
    runtime_transition = _load_module(
        "_goalteams_v250_runtime_transition",
        ROOT / "scripts/v250/runtime_transition.py",
    )
    route = {
        "project_size": args.project_size,
        "workflow_phase": args.phase,
        "release_intent": args.release_intent,
        "implementation_scope_complete": args.implementation_scope_complete,
        "stage": args.stage,
        "s1_current": False,
    }
    release_gate_receipts: dict[str, Any] = {}
    release_gate_binding: dict[str, Any] | None = None
    worktree_binding: dict[str, Any] | None = None
    released_runtime_receipt: dict[str, Any] | None = None
    released_runtime_validation: dict[str, Any] | None = None
    s0_receipt: dict[str, Any] | None = None
    s1_receipt: dict[str, Any] | None = None
    if args.phase == "release":
        try:
            source_commit, source_tree, worktree_binding = _released_identity(
                args.source_commit, args.source_tree
            )
            if args.released_runtime_receipt is None:
                raise ValueError("E_V250_RELEASED_RUNTIME_RECEIPT_REQUIRED")
            expected_host_execution_id = getattr(
                args, "expected_host_execution_id", None
            )
            if not expected_host_execution_id:
                raise ValueError("E_V250_HOST_EXECUTION_ID_REQUIRED")
            released_runtime_receipt = _read_json(args.released_runtime_receipt.resolve())
            released_runtime_validation = runtime_transition.validate_transition(
                released_runtime_receipt,
                expected_stage="released",
                allow_release=True,
                expected_source_commit=source_commit,
                expected_source_tree=source_tree,
                expected_project_size=args.project_size,
                expected_host_execution_id=expected_host_execution_id,
                root=ROOT,
            )
            if not released_runtime_validation.get("may_enter_s0"):
                raise ValueError("E_V250_RELEASED_RUNTIME_S0_REQUIRED")
            s0_receipt = release_flow.build_s0_receipt(
                source_commit=source_commit,
                source_tree=source_tree,
                runtime_transition=released_runtime_receipt,
                expected_host_execution_id=expected_host_execution_id,
            )
            regression = run_full_regression(
                source_commit,
                source_tree,
                worktree_binding,
                release_flow,
                command_counter=command_counter,
            )
            security = run_release_security_review(
                source_commit,
                source_tree,
                command_counter=command_counter,
            )
            release_gate_receipts = {
                "full_regression": regression,
                "release_security_review": security,
            }
            release_gate_binding = release_flow.validate_release_gate_bindings(
                source_commit,
                source_tree,
                regression,
                security,
            )
            if release_gate_binding["ok"]:
                s1_receipt = release_flow.build_s1_receipt(
                    source_commit=source_commit,
                    source_tree=source_tree,
                    full_regression=regression,
                    release_security_review=security,
                )
            route["s1_current"] = bool(release_gate_binding["ok"])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            release_gate_binding = {
                "ok": False,
                "passed": False,
                "errors": [str(exc) or f"E_V250_RELEASE_GATE_RUNNER:{type(exc).__name__}"],
            }
    plan = release_flow.derive_release_plan(route)
    passed = bool(contract_result["passed"])
    s1_passed = False
    if args.phase == "release":
        s1_passed = passed and bool(
            release_gate_binding
            and release_gate_binding.get("ok")
            and s0_receipt
            and s1_receipt
        )
        # This command closes S0/S1 only.  It must never present S1 as overall
        # Release completion before S2/S3/boundary/S4 preflight are bound.
        passed = False
    payload: dict[str, Any] = {
        "schema_version": "goal-teams-v2.6-check-result-v1",
        "passed": passed,
        "s1_passed": s1_passed,
        "release_control_state": (
            "incomplete" if args.phase == "release" else "not_applicable"
        ),
        "status": (
            "s1_passed_release_control_incomplete"
            if args.phase == "release" and s1_passed
            else "s1_failed"
            if args.phase == "release"
            else "development_passed"
            if passed
            else "development_failed"
        ),
        "workflow_phase": args.phase,
        "route": route,
        "contracts": contract_result,
        "release_plan": plan,
        "worktree_binding": worktree_binding,
        "released_runtime_transition": released_runtime_receipt,
        "released_runtime_validation": released_runtime_validation,
        "s0_receipt": s0_receipt,
        "release_gate_receipts": release_gate_receipts,
        "release_gate_binding": release_gate_binding,
        "s1_receipt": s1_receipt,
        "command_execution_count": _COMMAND_EXECUTION_COUNT,
        "external_side_effect_count": 0,
    }
    payload["receipt_sha256"] = release_flow.canonical_sha256(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if (payload["s1_passed"] if args.phase == "release" else payload["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
