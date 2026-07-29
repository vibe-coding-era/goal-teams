#!/usr/bin/env python3
"""Minimal, fail-closed release helper for the Goal Teams Skill package.

This helper intentionally has no GitHub, installation, tag, or publication
adapter.  ``plan`` is read-only.  ``verify`` builds an isolated snapshot from
an immutable Git commit, validates the package manifest through the existing
builder, and runs the packaged structural validator.  ``publish`` only reports
that fresh explicit user approval is required.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RECEIPT_SCHEMA = "goal-teams-skill-release-receipt-v1"
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class SkillReleaseError(RuntimeError):
    """Return a stable local-only failure without external side effects."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        self.receipt = _base_receipt(
            command=details.pop("command", "verify"),
            status="failed",
            error_code=code,
            error=message,
            **details,
        )
        super().__init__(f"{code}: {message}")


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_MODULE",
            f"cannot load local release module: {path.relative_to(ROOT)}",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_config_module() -> ModuleType:
    return _load_module(
        "_goal_teams_skill_release_config",
        ROOT / "scripts" / "release" / "release_config.py",
    )


def _builder_module() -> ModuleType:
    return _load_module(
        "_goal_teams_skill_release_builder",
        ROOT / "scripts" / "release" / "build-release.py",
    )


def _base_receipt(
    *,
    command: str,
    status: str,
    error_code: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "command": command,
        "status": status,
        "ok": error_code is None,
        "passed": error_code is None,
        "error_code": error_code,
        "persistent_local_mutation_count": 0,
        "external_mutation_count": 0,
        "external_side_effect_count": 0,
        **details,
    }


def _simple_config(version: str) -> dict[str, Any]:
    if VERSION_RE.fullmatch(version) is None:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_VERSION",
            "version must match V<major>.<minor>",
            version=version,
        )
    config_module = _release_config_module()
    try:
        config = config_module.release_config(version)
    except Exception as exc:
        receipt = getattr(exc, "receipt", {})
        raise SkillReleaseError(
            str(receipt.get("error_code") or "E_SKILL_RELEASE_PROFILE"),
            str(exc),
            version=version,
        ) from exc
    if (
        config.get("release_mode") != "skill_simple"
        or config.get("approval_model")
        != "single_human_before_external_write"
        or config.get("closure_state") != "ready_for_local_validation"
        or config.get("external_writes_allowed") is not False
        or not isinstance(config.get("release_gates"), list)
        or len(config["release_gates"]) != 5
    ):
        raise SkillReleaseError(
            "E_SKILL_RELEASE_PROFILE",
            "version is not an active fail-closed Skill simple-release profile",
            version=version,
        )
    return config


def _read_identity(
    version: str,
    commit: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    if COMMIT_RE.fullmatch(commit) is None:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_COMMIT",
            "a 40-character lowercase immutable commit SHA is required",
            version=version,
            source_commit=commit,
        )
    builder = _builder_module()
    try:
        frozen = builder.require_frozen_commit(commit)
        tree_result = builder._run_git(  # noqa: SLF001
            "rev-parse",
            f"{frozen}^{{tree}}",
            text=True,
        )
        tag_result = builder._run_git(  # noqa: SLF001
            "rev-parse",
            "--verify",
            f"refs/tags/{config['tag']}^{{commit}}",
            text=True,
            check=False,
        )
    except Exception as exc:
        receipt = getattr(exc, "receipt", {})
        raise SkillReleaseError(
            str(receipt.get("error_code") or "E_SKILL_RELEASE_COMMIT"),
            str(exc),
            version=version,
            source_commit=commit,
        ) from exc
    source_tree = str(tree_result.stdout).strip()
    if re.fullmatch(r"[0-9a-f]{40}", source_tree) is None:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_BINDING",
            "immutable commit did not resolve to an exact Git tree",
            version=version,
            source_commit=commit,
        )
    tag_target = str(tag_result.stdout).strip()
    if tag_result.returncode != 0:
        tag_state = "absent"
        tag_target = None
    elif tag_target == commit:
        tag_state = "matches_candidate"
    else:
        tag_state = "conflict"
    return {
        "source_commit": commit,
        "source_git_tree": source_tree,
        "tag": config["tag"],
        "tag_state": tag_state,
        "tag_target_commit": tag_target,
    }


def plan(version: str, commit: str) -> dict[str, Any]:
    """Return the five-gate local/publish plan without mutating anything."""

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    gate_states = {
        gate: (
            "requires_explicit_user_approval"
            if gate == "publish"
            else "not_run"
        )
        for gate in config["release_gates"]
    }
    return _base_receipt(
        command="plan",
        status="ready_for_local_validation",
        version=version,
        release_mode=config["release_mode"],
        approval_model=config["approval_model"],
        gates=gate_states,
        **identity,
        publish_state="requires_explicit_user_approval",
    )


def _run_structure_gate(snapshot: Path) -> dict[str, Any]:
    validator = snapshot / "scripts" / "checks" / "validate.py"
    if not validator.is_file() or validator.is_symlink():
        raise SkillReleaseError(
            "E_SKILL_RELEASE_STRUCTURE_GATE",
            "packaged structural validator is missing or unsafe",
        )
    result = subprocess.run(
        [sys.executable, str(validator)],
        cwd=snapshot,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = (result.stdout + result.stderr).strip()
    output_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
    if result.returncode != 0:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_STRUCTURE_GATE",
            "packaged structural validator failed",
            structure_gate_returncode=result.returncode,
            structure_gate_output_sha256=output_sha256,
        )
    return {
        "returncode": result.returncode,
        "output_sha256": output_sha256,
    }


def verify(version: str, commit: str) -> dict[str, Any]:
    """Locally verify one immutable Skill package candidate."""

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    builder = _builder_module()
    with tempfile.TemporaryDirectory(prefix="goal-teams-skill-release-") as temp:
        release_root = Path(temp) / "release" / "versions"
        try:
            record = builder.build(
                version,
                commit,
                source_ref=commit,
                release_root=release_root,
                archive_root=None,
            )
        except Exception as exc:
            receipt = getattr(exc, "receipt", {})
            raise SkillReleaseError(
                str(receipt.get("error_code") or "E_SKILL_RELEASE_PACKAGE"),
                str(exc),
                version=version,
                source_commit=commit,
            ) from exc
        snapshot = release_root / version
        structure = _run_structure_gate(snapshot)
        try:
            package_manifest_sha256 = str(
                record["source_package_manifest_sha256"]
            )
            source_tree = str(record["source_git_tree_id"])
            snapshot_tree = str(record["tree_sha256"])
        except KeyError as exc:
            raise SkillReleaseError(
                "E_SKILL_RELEASE_BINDING",
                f"builder receipt is missing identity field: {exc}",
                version=version,
                source_commit=commit,
            ) from exc
        if (
            record.get("version") != version
            or record.get("source_commit") != commit
            or source_tree != identity["source_git_tree"]
            or re.fullmatch(r"[0-9a-f]{40}", source_tree) is None
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_tree) is None
            or re.fullmatch(r"[0-9a-f]{64}", package_manifest_sha256) is None
        ):
            raise SkillReleaseError(
                "E_SKILL_RELEASE_BINDING",
                "builder receipt does not bind the requested version/commit/tree",
                version=version,
                source_commit=commit,
            )
    return _base_receipt(
        command="verify",
        status="partial_local_verification",
        version=version,
        release_mode=config["release_mode"],
        approval_model=config["approval_model"],
        **identity,
        package_tree_sha256=snapshot_tree,
        package_manifest_sha256=package_manifest_sha256,
        gates={
            "source_freeze": "passed",
            "checks": "partial",
            "package": "partial",
            "isolated_install": "not_run",
            "publish": "requires_explicit_user_approval",
        },
        verification_detail={
            "checks": {
                "structure": "passed",
                "full": "not_run",
            },
            "package": {
                "single_temporary_build": "passed",
                "double_build_reproducibility": "not_run",
            },
            "isolated_install": "not_run",
        },
        structure_gate=structure,
        temporary_local_mutation_count=1,
        publish_state="requires_explicit_user_approval",
    )


def publish(version: str, commit: str) -> dict[str, Any]:
    """Never publish; report the explicit approval boundary."""

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    return _base_receipt(
        command="publish",
        status="requires_explicit_user_approval",
        ok=False,
        passed=False,
        version=version,
        release_mode=config["release_mode"],
        approval_model=config["approval_model"],
        **identity,
        publish_state="requires_explicit_user_approval",
        required_operations=[
            "push_candidate_commit",
            "create_version_tag",
            "create_github_release",
        ],
        action_executed=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "publish"):
        child = subparsers.add_parser(command)
        child.add_argument("--version", default="V2.48")
        child.add_argument("--commit", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--version", default="V2.48")
    verify_parser.add_argument("--commit", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "plan":
            receipt = plan(args.version, args.commit)
        elif args.command == "verify":
            receipt = verify(args.version, args.commit)
        else:
            receipt = publish(args.version, args.commit)
    except SkillReleaseError as exc:
        print(json.dumps(exc.receipt, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from exc
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
