#!/usr/bin/env python3
"""Run and validate the V2.51 repository-boundary integrity gate.

The gate validates the already-built S2 asset set against frozen source and
repository/package boundaries.  It performs zero asset builds and makes no
reproducibility or S2-security claim.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_MODES = {"executed_now", "reused_receipt"}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"E_V250_BOUNDARY_MODULE:{path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _receipt_sha256(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("receipt_sha256", None)
    return _canonical_sha256(payload)


def _default_frozen_source_revalidation(
    source_commit: str,
    source_tree: str,
) -> dict[str, Any]:
    """Return the fixture-safe shape production fills from a live Git readback."""

    return {
        "check_state": "passed",
        "revalidated_now": True,
        "head_commit": source_commit,
        "head_tree": source_tree,
        "status_porcelain_sha256": EMPTY_SHA256,
        "dirty_entry_count": 0,
        "untracked_entry_count": 0,
    }


def observe_frozen_source(
    source_commit: str,
    source_tree: str,
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Re-read the exact clean source identity immediately before a boundary gate."""

    root = (repository_root or ROOT).resolve()
    commands = {
        "head_commit": ["git", "rev-parse", "HEAD^{commit}"],
        "head_tree": ["git", "rev-parse", "HEAD^{tree}"],
        "status": ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    }
    observed: dict[str, str] = {}
    for key, argv in commands.items():
        result = subprocess.run(
            argv,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode != 0:
            raise ValueError("E_V250_REPOSITORY_BOUNDARY_SOURCE_READBACK")
        observed[key] = result.stdout.strip()
    diff = subprocess.run(
        ["git", "diff", "--quiet", source_commit, "--"],
        cwd=root,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    cached = subprocess.run(
        ["git", "diff", "--cached", "--quiet", source_commit, "--"],
        cwd=root,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    status_lines = [line for line in observed["status"].splitlines() if line]
    untracked = [line for line in status_lines if line.startswith("?? ")]
    if (
        observed["head_commit"] != source_commit
        or observed["head_tree"] != source_tree
        or status_lines
        or diff.returncode != 0
        or cached.returncode != 0
    ):
        raise ValueError("E_V250_REPOSITORY_BOUNDARY_SOURCE_NOT_FROZEN")
    return {
        "check_state": "passed",
        "revalidated_now": True,
        "head_commit": observed["head_commit"],
        "head_tree": observed["head_tree"],
        "status_porcelain_sha256": hashlib.sha256(
            observed["status"].encode("utf-8")
        ).hexdigest(),
        "dirty_entry_count": len(status_lines) - len(untracked),
        "untracked_entry_count": len(untracked),
    }


def resolve_release_directory(
    release_root: Path,
    *,
    repository_root: Path | None = None,
) -> Path:
    """Accept only the repository-owned, ignored S2 output root."""

    root = (repository_root or ROOT).resolve()
    observed_root = release_root.resolve()
    expected_root = (root / "release/versions").resolve()
    release_directory = observed_root / "V2.51"
    if observed_root != expected_root or not release_directory.is_dir():
        raise ValueError("E_V250_REPOSITORY_BOUNDARY_RELEASE_ROOT")
    return release_directory


def boundary_contract_digests(
    *, repository_root: Path | None = None
) -> dict[str, Any]:
    """Return the source-derived digests shared by every boundary invocation."""

    root = (repository_root or ROOT).resolve()
    package_manifest = root / "scripts/install/package-manifest.txt"
    validator_paths = (
        root / "scripts/checks/check-workspace-boundaries.py",
        root / "scripts/checks/check-package-manifest.py",
        root / "scripts/release/validate-release.py",
        root / "scripts/v250/repository_boundary.py",
    )
    if (
        not package_manifest.is_file()
        or package_manifest.is_symlink()
        or any(not path.is_file() or path.is_symlink() for path in validator_paths)
    ):
        raise ValueError("E_V250_REPOSITORY_BOUNDARY_VALIDATOR")
    validator_rows = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in validator_paths
    ]
    return {
        "package_manifest_digest": hashlib.sha256(
            package_manifest.read_bytes()
        ).hexdigest(),
        "validator_digest": _canonical_sha256(validator_rows),
        "validator_rows": validator_rows,
    }


def build_boundary_receipt(
    *,
    source_commit: str,
    source_tree: str,
    asset_set_id: str,
    asset_set_digest: str,
    package_manifest_digest: str,
    validator_digest: str,
    argv: Sequence[Any],
    cwd: str,
    check_state: str,
    run_outcome: str,
    evidence_state: str = "current",
    command_receipts: Sequence[dict[str, Any]] = (),
    s2_receipt_sha256: str | None = None,
    receipt_mode: str = "executed_now",
    reused_receipt_sha256: str | None = None,
    frozen_source_revalidation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe an already-observed read-only boundary invocation."""

    receipt: dict[str, Any] = {
        "schema_version": "goal-teams-v2.51-repository-boundary-receipt-v1",
        "gate_id": "repository_boundary_compliance",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "asset_set_id": asset_set_id,
        "asset_set_digest": asset_set_digest,
        "s2_receipt_sha256": s2_receipt_sha256,
        "package_manifest_digest": package_manifest_digest,
        "validator_digest": validator_digest,
        "argv": list(argv),
        "cwd": cwd,
        "command_receipts": [dict(item) for item in command_receipts],
        "check_state": check_state,
        "run_outcome": run_outcome,
        "evidence_state": evidence_state,
        "receipt_mode": receipt_mode,
        "reused_receipt_sha256": reused_receipt_sha256,
        "frozen_source_revalidation": dict(
            frozen_source_revalidation
            or _default_frozen_source_revalidation(source_commit, source_tree)
        ),
        "asset_build_invocation_count": 0,
        "same_built_asset_set": True,
        "validation_kind": "frozen_source_and_boundary_integrity",
        "second_build_comparison_attempted": False,
        "claim_scope": "repository_boundary_only",
        "s2_security_checks": "not_applicable",
        "reproducibility": "not_applicable",
        "reproducibility_claim": False,
    }
    receipt["receipt_sha256"] = _receipt_sha256(receipt)
    return receipt


def validate_boundary_receipt(
    receipt: object,
    *,
    source_commit: str,
    source_tree: str,
    asset_set_id: str,
    asset_set_digest: str,
    package_manifest_digest: str,
    validator_digest: str,
    argv: Sequence[Any],
    cwd: str,
    s2_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Reject missing, failed, stale, or second-build boundary Evidence."""

    if not isinstance(receipt, dict):
        return {
            "ok": False,
            "passed": False,
            "errors": ["E_V250_REPOSITORY_BOUNDARY_MISSING"],
            "may_enter_s4": False,
        }
    errors: list[str] = []
    expected = {
        "gate_id": "repository_boundary_compliance",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "asset_set_id": asset_set_id,
        "asset_set_digest": asset_set_digest,
        "package_manifest_digest": package_manifest_digest,
        "validator_digest": validator_digest,
        "argv": list(argv),
        "cwd": cwd,
        "asset_build_invocation_count": 0,
    }
    if s2_receipt_sha256 is not None:
        expected["s2_receipt_sha256"] = s2_receipt_sha256
    if (
        COMMIT_RE.fullmatch(source_commit) is None
        or COMMIT_RE.fullmatch(source_tree) is None
        or any(
            SHA256_RE.fullmatch(value) is None
            for value in (
                asset_set_digest,
                package_manifest_digest,
                validator_digest,
            )
        )
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_EXPECTATION")
    if any(receipt.get(key) != value for key, value in expected.items()):
        errors.append("E_V250_REPOSITORY_BOUNDARY_STALE")
    if receipt.get("receipt_sha256") != _receipt_sha256(receipt):
        errors.append("E_V250_REPOSITORY_BOUNDARY_DIGEST")
    if (
        receipt.get("check_state") != "passed"
        or receipt.get("run_outcome") != "passed"
        or receipt.get("evidence_state") != "current"
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_NOT_CURRENT")
    if (
        receipt.get("claim_scope") != "repository_boundary_only"
        or receipt.get("s2_security_checks") != "not_applicable"
        or receipt.get("reproducibility") != "not_applicable"
        or receipt.get("same_built_asset_set") is not True
        or receipt.get("validation_kind")
        != "frozen_source_and_boundary_integrity"
        or receipt.get("second_build_comparison_attempted") is not False
        or receipt.get("reproducibility_claim") is not False
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_CLAIM_SCOPE")
    receipt_mode = receipt.get("receipt_mode")
    reused_receipt_sha256 = receipt.get("reused_receipt_sha256")
    if (
        receipt_mode not in RECEIPT_MODES
        or (
            receipt_mode == "executed_now"
            and reused_receipt_sha256 is not None
        )
        or (
            receipt_mode == "reused_receipt"
            and (
                not isinstance(reused_receipt_sha256, str)
                or SHA256_RE.fullmatch(reused_receipt_sha256) is None
            )
        )
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_RECEIPT_MODE")
    frozen = receipt.get("frozen_source_revalidation")
    if (
        not isinstance(frozen, dict)
        or frozen.get("check_state") != "passed"
        or frozen.get("revalidated_now") is not True
        or frozen.get("head_commit") != source_commit
        or frozen.get("head_tree") != source_tree
        or frozen.get("status_porcelain_sha256") != EMPTY_SHA256
        or frozen.get("dirty_entry_count") != 0
        or frozen.get("untracked_entry_count") != 0
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_SOURCE_NOT_FROZEN")
    commands = receipt.get("command_receipts")
    if (
        not isinstance(commands, list)
        or len(commands) != 3
        or any(
            not isinstance(item, dict)
            or item.get("argv") != list(argv[index])
            or item.get("returncode") != 0
            or not isinstance(item.get("output_sha256"), str)
            or SHA256_RE.fullmatch(item["output_sha256"]) is None
            for index, item in enumerate(commands)
        )
    ):
        errors.append("E_V250_REPOSITORY_BOUNDARY_COMMANDS")
    deduplicated = list(dict.fromkeys(errors))
    return {
        "ok": not deduplicated,
        "passed": not deduplicated,
        "errors": deduplicated,
        "may_enter_s4": not deduplicated,
    }


def run_repository_boundary(
    *,
    source_commit: str,
    source_tree: str,
    s2_receipt: dict[str, Any],
    asset_validation_receipt: dict[str, Any],
    release_root: Path,
    reused_receipt: dict[str, Any] | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Run the three fixed read-only gates against one existing asset set."""

    root = (repository_root or ROOT).resolve()
    release_flow = _load_module(
        "_goalteams_v250_boundary_release_flow",
        root / "scripts/v250/release_flow.py",
    )
    s2_verdict = release_flow.validate_s2_receipt(
        s2_receipt,
        source_commit=source_commit,
        source_tree=source_tree,
    )
    if not s2_verdict["ok"]:
        raise ValueError(str(s2_verdict["errors"][0]))
    validation = asset_validation_receipt.get("asset_integrity_validation_receipt")
    if (
        asset_validation_receipt.get("passed") is not True
        or not isinstance(validation, dict)
        or validation.get("source_commit") != source_commit
        or validation.get("source_tree") != source_tree
        or validation.get("asset_set_id") != s2_receipt.get("asset_set_id")
        or validation.get("asset_set_digest") != s2_receipt.get("asset_set_digest")
        or validation.get("s2_receipt_sha256") != s2_receipt.get("receipt_sha256")
        or validation.get("validation_kind")
        != "frozen_source_and_boundary_integrity"
        or validation.get("same_built_asset_set") is not True
        or validation.get("asset_build_invocation_count") != 0
        or validation.get("second_build_comparison_attempted") is not False
        or validation.get("reproducibility_claim") is not False
        or validation.get("returncode") != 0
        or validation.get("check_state") != "passed"
        or validation.get("receipt_sha256")
        != release_flow.canonical_sha256(
            {key: value for key, value in validation.items() if key != "receipt_sha256"}
        )
    ):
        raise ValueError("E_V250_SAME_ASSET_INTEGRITY_RECEIPT")
    release_directory = resolve_release_directory(
        release_root,
        repository_root=root,
    )
    public_asset_sources = asset_validation_receipt.get("public_asset_sources")
    if not isinstance(public_asset_sources, dict) or not public_asset_sources:
        raise ValueError("E_V250_REPOSITORY_BOUNDARY_ASSET_SOURCES")
    for source in public_asset_sources.values():
        if not isinstance(source, str):
            raise ValueError("E_V250_REPOSITORY_BOUNDARY_ASSET_SOURCES")
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = root / source_path
        try:
            source_path.resolve().relative_to(release_directory.resolve())
        except ValueError as exc:
            raise ValueError("E_V250_REPOSITORY_BOUNDARY_ASSET_SOURCES") from exc
    contract = boundary_contract_digests(repository_root=root)
    package_manifest_digest = contract["package_manifest_digest"]
    validator_digest = contract["validator_digest"]
    commands = [
        [sys.executable, "scripts/checks/check-workspace-boundaries.py"],
        [sys.executable, "scripts/checks/check-package-manifest.py"],
        list(validation["argv"]),
    ]
    if reused_receipt is not None:
        reused_verdict = validate_boundary_receipt(
            reused_receipt,
            source_commit=source_commit,
            source_tree=source_tree,
            asset_set_id=s2_receipt["asset_set_id"],
            asset_set_digest=s2_receipt["asset_set_digest"],
            package_manifest_digest=package_manifest_digest,
            validator_digest=validator_digest,
            argv=commands,
            cwd=".",
            s2_receipt_sha256=s2_receipt["receipt_sha256"],
        )
        if not reused_verdict["ok"]:
            raise ValueError(str(reused_verdict["errors"][0]))
    frozen_source_revalidation = observe_frozen_source(
        source_commit,
        source_tree,
        repository_root=root,
    )
    command_receipts: list[dict[str, Any]] = []
    all_passed = True
    for argv in commands[:2]:
        result = subprocess.run(
            argv,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        output = (result.stdout + result.stderr).encode("utf-8", errors="replace")
        command_receipts.append(
            {
                "argv": argv,
                "cwd": ".",
                "returncode": result.returncode,
                "output_sha256": hashlib.sha256(output).hexdigest(),
            }
        )
        all_passed = all_passed and result.returncode == 0
    command_receipts.append(
        {
            "argv": list(validation["argv"]),
            "cwd": validation["cwd"],
            "returncode": validation["returncode"],
            "output_sha256": validation["output_sha256"],
            "receipt_sha256": validation["receipt_sha256"],
            "validation_kind": validation["validation_kind"],
        }
    )
    return build_boundary_receipt(
        source_commit=source_commit,
        source_tree=source_tree,
        asset_set_id=s2_receipt["asset_set_id"],
        asset_set_digest=s2_receipt["asset_set_digest"],
        package_manifest_digest=package_manifest_digest,
        validator_digest=validator_digest,
        argv=commands,
        cwd=".",
        check_state="passed" if all_passed else "failed",
        run_outcome="passed" if all_passed else "failed",
        command_receipts=command_receipts,
        s2_receipt_sha256=s2_receipt["receipt_sha256"],
        receipt_mode="reused_receipt" if reused_receipt is not None else "executed_now",
        reused_receipt_sha256=(
            reused_receipt.get("receipt_sha256") if reused_receipt is not None else None
        ),
        frozen_source_revalidation=frozen_source_revalidation,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--s2-receipt", type=Path, required=True)
    parser.add_argument("--asset-validation-receipt", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument(
        "--reuse-receipt",
        type=Path,
        help="reuse a current boundary receipt only after executing fresh frozen-source and boundary revalidation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        s2 = json.loads(args.s2_receipt.read_text(encoding="utf-8"))
        if not isinstance(s2, dict):
            raise ValueError("E_V250_S2_RECEIPT_MISSING")
        s2 = s2.get("s2_receipt", s2)
        if not isinstance(s2, dict):
            raise ValueError("E_V250_S2_RECEIPT_MISSING")
        validation = json.loads(
            args.asset_validation_receipt.read_text(encoding="utf-8")
        )
        if not isinstance(validation, dict):
            raise ValueError("E_V250_SAME_ASSET_INTEGRITY_RECEIPT")
        reused = None
        if args.reuse_receipt is not None:
            reused = json.loads(args.reuse_receipt.read_text(encoding="utf-8"))
            if not isinstance(reused, dict):
                raise ValueError("E_V250_REPOSITORY_BOUNDARY_MISSING")
        receipt = run_repository_boundary(
            source_commit=args.source_commit,
            source_tree=args.source_tree,
            s2_receipt=s2,
            asset_validation_receipt=validation,
            release_root=args.release_root,
            reused_receipt=reused,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "goal-teams-v2.51-repository-boundary-receipt-v1",
                    "passed": False,
                    "error_code": str(exc),
                    "asset_build_invocation_count": 0,
                    "reproducibility_claim": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["check_state"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
