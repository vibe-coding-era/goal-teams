#!/usr/bin/env python3
"""Fail-closed local release helper for the Goal Teams Skill package.

This helper intentionally has no GitHub, installation, tag, or publication
side effect. ``plan`` is read-only. V2.49 ``validate`` checks the same asset set
created by the single explicit S2 build; it never starts another build or makes
a reproducibility claim. ``preflight`` and ``plan-s4`` require the complete
project-start-authorization and S0-S4 receipt chain. The compatibility command
``publish`` is also only an authorization plan and can never report execution.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
V249_REPOSITORY = "vibe-coding-era/goal-teams"


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


def _v249_release_flow_module() -> ModuleType:
    return _load_module(
        "_goal_teams_v249_release_flow",
        ROOT / "scripts" / "v249" / "release_flow.py",
    )


def _read_receipt_file(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise SkillReleaseError(
            "E_V249_RECEIPT_INPUT",
            "receipt input is missing, unsafe, or too large",
            receipt_path=str(path),
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillReleaseError(
            "E_V249_RECEIPT_INPUT",
            "receipt input is not canonical JSON",
            receipt_path=str(path),
        ) from exc
    if not isinstance(value, dict):
        raise SkillReleaseError(
            "E_V249_RECEIPT_INPUT",
            "receipt input root must be an object",
            receipt_path=str(path),
        )
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_v249_external_anchors(
    *,
    commit: str,
    source_tree: str,
    s1_check_receipt: dict[str, Any],
    asset_validation_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Recompute Current/runtime/security anchors from the exact Git commit."""

    builder = _builder_module()
    entries = builder.tree(commit)

    def frozen_bytes(relative: str) -> bytes:
        row = entries.get(relative)
        if row is None:
            raise SkillReleaseError(
                "E_V249_EXTERNAL_ANCHOR_PATH",
                f"required frozen path is missing: {relative}",
                command="preflight",
                source_commit=commit,
            )
        return builder.blob(row[1])

    try:
        full = s1_check_receipt["release_gate_receipts"]["full_regression"]
        security = s1_check_receipt["release_gate_receipts"][
            "release_security_review"
        ]
        runtime = s1_check_receipt["released_runtime_transition"]
        s2 = asset_validation_receipt["s2_receipt"]
        integrity = asset_validation_receipt["asset_integrity_validation_receipt"]
    except (KeyError, TypeError) as exc:
        raise SkillReleaseError(
            "E_V249_EXTERNAL_ANCHOR_RECEIPT",
            "raw S1/runtime/S2/integrity receipts are required",
            command="preflight",
            source_commit=commit,
        ) from exc

    release_flow = _v249_release_flow_module()
    expected_test_files = [
        {
            "path": path,
            "sha256": hashlib.sha256(frozen_bytes(path)).hexdigest(),
        }
        for path in sorted(entries)
        if path.startswith("tests/v249/test_") and path.endswith(".py")
    ]
    denominator = full.get("denominator") if isinstance(full, dict) else None
    if (
        not expected_test_files
        or not isinstance(denominator, dict)
        or denominator.get("test_files") != expected_test_files
        or denominator.get("test_file_count") != len(expected_test_files)
        or denominator.get("test_file_set_sha256")
        != release_flow.canonical_sha256(expected_test_files)
        or denominator.get("source_commit") != commit
        or denominator.get("source_tree") != source_tree
        or denominator.get("contract_sha256")
        != hashlib.sha256(
            frozen_bytes(
                "references/current/generations/V2.49/contracts/release-command-manifest.json"
            )
        ).hexdigest()
    ):
        raise SkillReleaseError(
            "E_V249_CURRENT_DENOMINATOR_EXTERNAL_ANCHOR",
            "Current full-regression denominator differs from the exact commit",
            command="preflight",
            source_commit=commit,
        )

    active = json.loads(frozen_bytes("references/current/ACTIVE.json"))
    activation_path = active.get("activation_manifest")
    runtime_required = {
        ".agents/skills/goal-teams/SKILL.md",
        "SKILL.md",
        "RULES.md",
        "references/current/ACTIVE.json",
        "references/profiles/goal-teams-self-release-v2.49.md",
        "references/current/generations/V2.49/contracts/release-route-manifest.json",
        "references/current/generations/V2.49/contracts/release-command-manifest.json",
        "scripts/checks/check-v249.py",
        "scripts/v249/runtime_transition.py",
        str(activation_path),
    }
    runtime_digests = runtime.get("input_digests") if isinstance(runtime, dict) else None
    if (
        not isinstance(runtime_digests, dict)
        or set(runtime_digests) != runtime_required
        or runtime.get("loaded_paths") != sorted(runtime_required)
        or any(
            runtime_digests[path] != hashlib.sha256(frozen_bytes(path)).hexdigest()
            for path in runtime_required
        )
    ):
        raise SkillReleaseError(
            "E_V249_RUNTIME_EXTERNAL_ANCHOR",
            "released runtime inputs differ from the exact commit",
            command="preflight",
            source_commit=commit,
        )

    security_digests = security.get("contract_digests") if isinstance(security, dict) else None
    expected_security_paths = {
        "references/current/generations/V2.49/contracts/public-asset-map.json",
        "references/current/generations/V2.49/contracts/release-command-manifest.json",
        "references/current/generations/V2.49/contracts/release-route-manifest.json",
        "references/current/generations/V2.49/contracts/release-security-review-manifest.json",
        "schemas/v2.49/project-route.schema.json",
        "schemas/v2.49/release-control.schema.json",
    }
    reviewer = security.get("reviewer_identity") if isinstance(security, dict) else None
    if (
        not isinstance(security_digests, dict)
        or set(security_digests) != expected_security_paths
        or any(
            security_digests[path] != hashlib.sha256(frozen_bytes(path)).hexdigest()
            for path in expected_security_paths
        )
        or not isinstance(reviewer, dict)
        or reviewer.get("runner_sha256")
        != hashlib.sha256(
            frozen_bytes("scripts/checks/run-v249-release-security-review.py")
        ).hexdigest()
    ):
        raise SkillReleaseError(
            "E_V249_SECURITY_EXTERNAL_ANCHOR",
            "security denominator or runner differs from the exact commit",
            command="preflight",
            source_commit=commit,
        )

    s2_verdict = release_flow.validate_s2_receipt(
        s2,
        source_commit=commit,
        source_tree=source_tree,
    )
    public_assets = asset_validation_receipt.get("public_assets")
    if (
        not s2_verdict["ok"]
        or public_assets != s2.get("assets")
        or not isinstance(integrity, dict)
        or integrity.get("source_commit") != commit
        or integrity.get("source_tree") != source_tree
        or integrity.get("asset_set_id") != s2.get("asset_set_id")
        or integrity.get("asset_set_digest") != s2.get("asset_set_digest")
        or integrity.get("s2_receipt_sha256") != s2.get("receipt_sha256")
        or integrity.get("asset_build_invocation_count") != 0
        or integrity.get("second_build_comparison_attempted") is not False
        or integrity.get("reproducibility_claim") is not False
        or integrity.get("receipt_sha256")
        != release_flow.canonical_sha256(
            {key: value for key, value in integrity.items() if key != "receipt_sha256"}
        )
    ):
        raise SkillReleaseError(
            "E_V249_ASSET_EXTERNAL_ANCHOR",
            "S2 or same-built-asset integrity receipt is inconsistent",
            command="preflight",
            source_commit=commit,
        )
    anchor = {
        "schema_version": "goal-teams-v2.49-external-anchor-validation-v1",
        "source_commit": commit,
        "source_tree": source_tree,
        "current_test_file_set_sha256": release_flow.canonical_sha256(
            expected_test_files
        ),
        "runtime_input_set_sha256": release_flow.canonical_sha256(runtime_digests),
        "security_contract_set_sha256": release_flow.canonical_sha256(
            security_digests
        ),
        "asset_set_digest": s2["asset_set_digest"],
        "check_state": "passed",
        "evidence_state": "current",
    }
    anchor["receipt_sha256"] = release_flow.canonical_sha256(anchor)
    return anchor


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
    expected_approval = (
        "project_start_authorization_reused"
        if version == "V2.49"
        else "single_human_before_external_write"
    )
    expected_gate_count = 6 if version == "V2.49" else 5
    if (
        config.get("release_mode") != "skill_simple"
        or config.get("approval_model") != expected_approval
        or config.get("closure_state") != "ready_for_local_validation"
        or config.get("external_writes_allowed") is not False
        or not isinstance(config.get("release_gates"), list)
        or len(config["release_gates"]) != expected_gate_count
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


def plan(
    version: str,
    commit: str,
    *,
    route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a phase-aware local/publish plan without mutating anything."""

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    if version == "V2.49":
        route_value = route or {
            "project_size": "medium",
            "workflow_phase": "development",
            "release_intent": False,
            "implementation_scope_complete": False,
            "stage": "candidate",
        }
        release_plan = _v249_release_flow_module().derive_release_plan(route_value)
        gate_states = {
            gate: "not_run" for gate in config["release_gates"]
        }
        gate_states["publish"] = "uses_project_start_authorization_receipt"
        publish_state = "project_start_authorization_receipt_required"
        status = (
            "release_readiness_not_met"
            if not release_plan["release_ready"]
            else "ready_for_release_gate_receipts"
        )
    else:
        release_plan = None
        gate_states = {
            gate: (
                "requires_explicit_user_approval"
                if gate == "publish"
                else "not_run"
            )
            for gate in config["release_gates"]
        }
        publish_state = "requires_explicit_user_approval"
        status = "ready_for_local_validation"
    return _base_receipt(
        command="plan",
        status=status,
        version=version,
        release_mode=config["release_mode"],
        approval_model=config["approval_model"],
        gates=gate_states,
        release_plan=release_plan,
        **identity,
        publish_state=publish_state,
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
    """Legacy simple-release verifier.

    V2.49 requires the explicit ``build-release.py`` S2 entrypoint followed by
    ``validate_existing_asset_set``.  Refusing V2.49 here prevents this helper
    from accidentally becoming a second build path.
    """

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    if version == "V2.49":
        raise SkillReleaseError(
            "E_V249_EXPLICIT_SINGLE_BUILD_REQUIRED",
            "V2.49 S2 must use build-release.py once, then validate the same asset set",
            command="verify",
            version=version,
            source_commit=commit,
            source_git_tree=identity["source_git_tree"],
            s2_build_invocation_count=0,
        )
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
        structure = (
            {
                "status": "not_run_by_v249_policy",
                "reason": "repository_boundary_compliance_is_independent",
            }
            if version == "V2.49"
            else _run_structure_gate(snapshot)
        )
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
    if version == "V2.49":
        return _base_receipt(
            command="verify",
            status="s2_single_build_complete",
            version=version,
            release_mode=config["release_mode"],
            approval_model=config["approval_model"],
            **identity,
            package_tree_sha256=snapshot_tree,
            package_manifest_sha256=package_manifest_sha256,
            gates={
                "source_freeze": "passed",
                "release_readiness": "receipt_required",
                "single_build": "passed",
                "large_release_install": "not_run",
                "repository_boundary_compliance": "not_run",
                "publish": "project_start_authorization_receipt_required",
            },
            verification_detail={
                "s2": {
                    "build_invocation_count_for_asset_set": 1,
                    "second_build_comparison_attempted": False,
                    "reproducibility": "not_verified_by_v249_policy",
                    "s2_security_checks": "not_run_by_v249_policy",
                },
                "repository_boundary_compliance": "not_run",
                "large_release_install": "not_run",
            },
            structure_gate=structure,
            temporary_local_mutation_count=1,
            publish_state="project_start_authorization_receipt_required",
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


def validate_existing_asset_set(
    version: str,
    commit: str,
    *,
    release_root: Path,
    build_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Validate the asset set from the one explicit V2.49 S2 build.

    This function never calls the builder.  ``validate-release.py`` validates
    frozen-source and boundary integrity for the same bytes and modes already
    present under ``release_root``; this is not a reproducibility comparison.
    """

    if version != "V2.49":
        raise SkillReleaseError(
            "E_V249_VALIDATE_VERSION",
            "same-built-asset validation is defined for V2.49",
            command="validate",
            version=version,
        )
    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    release_root = release_root.resolve()
    snapshot = release_root / version
    record_path = snapshot / "_release.json"
    if not snapshot.is_dir() or not record_path.is_file() or record_path.is_symlink():
        raise SkillReleaseError(
            "E_V249_EXISTING_ASSET_SET_REQUIRED",
            "the already-built V2.49 snapshot is missing or unsafe",
            command="validate",
            version=version,
            source_commit=commit,
            asset_build_invocation_count=0,
        )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillReleaseError(
            "E_V249_EXISTING_ASSET_SET_RECORD",
            "the already-built release record is invalid",
            command="validate",
            version=version,
            source_commit=commit,
            asset_build_invocation_count=0,
        ) from exc
    built = build_receipt.get("built")
    if (
        not isinstance(record, dict)
        or not isinstance(built, list)
        or len(built) != 1
        or built[0] != record
        or record.get("version") != version
        or record.get("source_commit") != commit
        or record.get("source_git_tree_id") != identity["source_git_tree"]
    ):
        raise SkillReleaseError(
            "E_V249_S2_BUILD_RECEIPT_DRIFT",
            "build receipt, frozen identity, and existing release record differ",
            command="validate",
            version=version,
            source_commit=commit,
            asset_build_invocation_count=0,
        )

    asset_paths = {
        f"goal-teams-{version}.tar.gz": snapshot
        / "_artifacts"
        / f"goal-teams-{version}.tar.gz",
        "SHA256SUMS": snapshot / "_artifacts" / "SHA256SUMS",
        "_release.json": record_path,
        "_files.sha256": snapshot / "_files.sha256",
    }
    if any(not path.is_file() or path.is_symlink() for path in asset_paths.values()):
        raise SkillReleaseError(
            "E_V249_PUBLIC_ASSET_SET",
            "the exact existing four-asset set is incomplete",
            command="validate",
            version=version,
            source_commit=commit,
            asset_build_invocation_count=0,
        )
    assets = [
        {"name": name, "size": path.stat().st_size, "sha256": _sha256_file(path)}
        for name, path in sorted(asset_paths.items())
    ]
    release_flow = _v249_release_flow_module()
    asset_set_digest = release_flow.canonical_sha256(assets)
    asset_set_id = f"V249-ASSET-{asset_set_digest[:20]}"
    s2_receipt = release_flow.build_s2_receipt(
        source_commit=commit,
        source_tree=identity["source_git_tree"],
        asset_set_id=asset_set_id,
        assets=assets,
        build_run_id=f"V249-S2-{commit[:12]}-{asset_set_digest[:12]}",
    )

    validator = ROOT / "scripts/release/validate-release.py"
    argv = [
        sys.executable,
        str(validator),
        "--version",
        version,
        "--release-root",
        str(release_root),
        "--isolated-no-docs-archive",
    ]
    result = subprocess.run(
        argv,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    output = (result.stdout + result.stderr).encode("utf-8", errors="replace")
    try:
        validation = json.loads(result.stdout)
    except json.JSONDecodeError:
        validation = {}
    if result.returncode != 0 or validation.get("passed") is not True:
        raise SkillReleaseError(
            "E_V249_SAME_ASSET_INTEGRITY_VALIDATION",
            "frozen-source and boundary integrity validation failed",
            command="validate",
            version=version,
            source_commit=commit,
            asset_set_id=asset_set_id,
            asset_build_invocation_count=0,
            validator_returncode=result.returncode,
            validator_output_sha256=hashlib.sha256(output).hexdigest(),
        )
    validation_receipt = {
        "schema_version": "goal-teams-v2.49-same-asset-validation-receipt-v1",
        "gate_id": "same_built_asset_integrity_validation",
        "source_commit": commit,
        "source_tree": identity["source_git_tree"],
        "asset_set_id": asset_set_id,
        "asset_set_digest": asset_set_digest,
        "s2_receipt_sha256": s2_receipt["receipt_sha256"],
        "validation_kind": "frozen_source_and_boundary_integrity",
        "same_built_asset_set": True,
        "asset_build_invocation_count": 0,
        "second_build_comparison_attempted": False,
        "reproducibility_claim": False,
        "argv": argv,
        "cwd": ".",
        "returncode": result.returncode,
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "validator_sha256": _sha256_file(validator),
        "check_state": "passed",
        "run_outcome": "passed",
        "evidence_state": "current",
    }
    validation_receipt["receipt_sha256"] = release_flow.canonical_sha256(
        validation_receipt
    )
    installer_identity = {
        "source_kind": "local_release_bundle",
        "repository": V249_REPOSITORY,
        "version": version,
        "release_tag": config["tag"],
        "release_id": f"v249-s3-{asset_set_digest[:16]}",
        "release_state": "rehearsal",
        "source_commit": commit,
        "source_git_tree_id": identity["source_git_tree"],
        "assets": [
            {**asset, "download_sha256": asset["sha256"], "asset_id": None}
            for asset in assets
        ],
    }
    return _base_receipt(
        command="validate",
        status="same_built_asset_integrity_passed",
        version=version,
        release_mode=config["release_mode"],
        approval_model=config["approval_model"],
        **identity,
        asset_set_id=asset_set_id,
        asset_set_digest=asset_set_digest,
        public_assets=assets,
        public_asset_sources={
            name: str(path) for name, path in sorted(asset_paths.items())
        },
        s2_receipt=s2_receipt,
        asset_integrity_validation_receipt=validation_receipt,
        installer_release_identity=installer_identity,
        asset_build_invocation_count=0,
        second_build_comparison_attempted=False,
        reproducibility="not_verified_by_v249_policy",
        temporary_local_mutation_count=0,
        publish_state="release_control_receipt_required",
    )


def build_s3_receipt(
    *,
    project_size: str,
    s2_receipt: dict[str, Any],
    install_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a Large-only isolated install report to the exact S2 asset set."""

    release_flow = _v249_release_flow_module()
    verdict = release_flow.validate_s2_receipt(
        s2_receipt,
        source_commit=str(s2_receipt.get("source_commit", "")),
        source_tree=str(s2_receipt.get("source_tree", "")),
    )
    if not verdict["ok"]:
        raise SkillReleaseError(
            str(verdict["errors"][0]),
            "S3 input is not a current exact S2 receipt",
            command="s3-receipt",
        )
    base = {
        "schema_version": "goal-teams-v2.49-s3-receipt-v1",
        "source_commit": s2_receipt["source_commit"],
        "source_tree": s2_receipt["source_tree"],
        "asset_set_id": s2_receipt["asset_set_id"],
        "asset_set_digest": s2_receipt["asset_set_digest"],
        "s2_receipt_sha256": s2_receipt["receipt_sha256"],
    }
    if project_size != "large":
        receipt = {
            **base,
            "gate_id": "s3_not_required",
            "gate_requirement": "not_required",
            "not_required_reason": "large_release_only",
            "check_state": "not_required",
            "run_outcome": "not_run",
            "evidence_state": "current",
            "s3_process_invocation_count": 0,
            "child_argv": [],
        }
    else:
        source = install_report.get("source") if isinstance(install_report, dict) else None
        report_assets = source.get("release_assets") if isinstance(source, dict) else None
        expected_assets = {
            item["name"]: (item["sha256"], item["size"])
            for item in s2_receipt["assets"]
        }
        observed_assets = {
            item.get("name"): (item.get("sha256"), item.get("size"))
            for item in report_assets
            if isinstance(item, dict)
        } if isinstance(report_assets, list) else {}
        if (
            not isinstance(install_report, dict)
            or install_report.get("status") != "installed"
            or not isinstance(source, dict)
            or source.get("version") != "V2.49"
            or source.get("commit") != s2_receipt["source_commit"]
            or source.get("git_tree_id") != s2_receipt["source_tree"]
            or observed_assets != expected_assets
        ):
            raise SkillReleaseError(
                "E_V249_S3_INSTALL_REPORT_DRIFT",
                "Large S3 install report does not bind the exact S2 asset set",
                command="s3-receipt",
                asset_set_id=s2_receipt["asset_set_id"],
            )
        report_digest = release_flow.canonical_sha256(install_report)
        receipt = {
            **base,
            "gate_id": "s3_large_release_install",
            "gate_requirement": "required",
            "check_state": "passed",
            "run_outcome": "passed",
            "evidence_state": "current",
            "s3_process_invocation_count": 1,
            "child_argv": ["scripts/install/install-local.sh"],
            "install_report_sha256": report_digest,
        }
    receipt["receipt_sha256"] = release_flow.canonical_sha256(receipt)
    return receipt


def preflight_release_control(
    version: str,
    commit: str,
    *,
    project_size: str,
    authorization_receipt: dict[str, Any],
    s1_check_receipt: dict[str, Any],
    asset_validation_receipt: dict[str, Any],
    s3_receipt: dict[str, Any],
    boundary_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Build the complete local release-control and S4-preflight receipt."""

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    if version != "V2.49":
        raise SkillReleaseError(
            "E_V249_RELEASE_CONTROL_VERSION",
            "release-control preflight is defined for V2.49",
            command="preflight",
            version=version,
        )
    try:
        transition = s1_check_receipt["released_runtime_transition"]
        s0 = s1_check_receipt["s0_receipt"]
        full = s1_check_receipt["release_gate_receipts"]["full_regression"]
        security = s1_check_receipt["release_gate_receipts"][
            "release_security_review"
        ]
        s1 = s1_check_receipt["s1_receipt"]
        s2 = asset_validation_receipt["s2_receipt"]
        asset_integrity = asset_validation_receipt[
            "asset_integrity_validation_receipt"
        ]
    except (KeyError, TypeError) as exc:
        raise SkillReleaseError(
            "E_V249_RELEASE_CONTROL_RECEIPT_MISSING",
            "S0, S1, or S2 input receipt is missing",
            command="preflight",
            version=version,
            source_commit=commit,
        ) from exc
    if (
        s1_check_receipt.get("passed") is not False
        or s1_check_receipt.get("s1_passed") is not True
        or s1_check_receipt.get("release_control_state") != "incomplete"
        or s1_check_receipt.get("status")
        != "s1_passed_release_control_incomplete"
    ):
        raise SkillReleaseError(
            "E_V249_S1_NOT_CURRENT",
            "S1 checker receipt is not passed/current",
            command="preflight",
            version=version,
            source_commit=commit,
        )
    release_flow = _v249_release_flow_module()
    try:
        external_anchor = _validate_v249_external_anchors(
            commit=commit,
            source_tree=identity["source_git_tree"],
            s1_check_receipt=s1_check_receipt,
            asset_validation_receipt=asset_validation_receipt,
        )
        control = release_flow.build_release_control_receipt(
            repository=V249_REPOSITORY,
            version=version,
            project_size=project_size,
            candidate_branch=config["candidate_branch"],
            tag=config["tag"],
            source_commit=commit,
            source_tree=identity["source_git_tree"],
            authorization_receipt=authorization_receipt,
            released_runtime_transition=transition,
            s0=s0,
            full_regression=full,
            release_security_review=security,
            s1=s1,
            s2=s2,
            asset_integrity_validation=asset_integrity,
            s3=s3_receipt,
            repository_boundary=boundary_receipt,
            external_anchor_validation=external_anchor,
        )
    except (SkillReleaseError, ValueError) as exc:
        if isinstance(exc, SkillReleaseError):
            raise
        raise SkillReleaseError(
            str(exc),
            "release-control receipt chain is missing, stale, or inconsistent",
            command="preflight",
            version=version,
            source_commit=commit,
        ) from exc
    return control


def validate_v249_s4_control(
    version: str,
    commit: str,
    release_control_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Revalidate a complete control receipt against the exact frozen commit.

    The pure receipt validator deliberately cannot read Git.  This public
    boundary adds the external anchors that prevent a re-sealed synthetic
    denominator, runtime summary, or security summary from authorizing S4.
    """

    if version != "V2.49":
        return {
            "ok": False,
            "passed": False,
            "errors": ["E_V249_RELEASE_CONTROL_VERSION"],
        }
    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    control = release_control_receipt
    verdict = _v249_release_flow_module().validate_release_control_receipt(
        control,
        expected_repository=V249_REPOSITORY,
        expected_version=version,
        expected_candidate_branch=config["candidate_branch"],
        expected_tag=config["tag"],
        expected_source_commit=commit,
        expected_source_tree=identity["source_git_tree"],
    )
    try:
        recomputed_anchor = _validate_v249_external_anchors(
            commit=commit,
            source_tree=identity["source_git_tree"],
            s1_check_receipt={
                "release_gate_receipts": {
                    "full_regression": control.get("full_regression"),
                    "release_security_review": control.get(
                        "release_security_review"
                    ),
                },
                "released_runtime_transition": control.get(
                    "released_runtime_transition"
                ),
            },
            asset_validation_receipt={
                "s2_receipt": control.get("s2"),
                "public_assets": control.get("s2", {}).get("assets"),
                "asset_integrity_validation_receipt": control.get(
                    "asset_integrity_validation"
                ),
            },
        )
        anchor_matches = recomputed_anchor == control.get(
            "external_anchor_validation"
        )
    except SkillReleaseError as exc:
        anchor_matches = False
        external_error = exc.receipt.get("error_code")
        if external_error:
            verdict.setdefault("errors", []).append(external_error)
    if not anchor_matches:
        # Put the public-boundary failure first. A low-level receipt error is
        # useful detail, but must not hide that exact Git anchors did not match.
        verdict["errors"] = [
            "E_V249_EXTERNAL_ANCHOR_REVALIDATION",
            *[
                error
                for error in verdict.get("errors", [])
                if error != "E_V249_EXTERNAL_ANCHOR_REVALIDATION"
            ],
        ]
    verdict["errors"] = list(dict.fromkeys(verdict.get("errors", [])))
    verdict["ok"] = bool(verdict.get("ok") and anchor_matches)
    verdict["passed"] = verdict["ok"]
    verdict["source_tree"] = identity["source_git_tree"]
    verdict["source_identity"] = identity
    verdict["release_config"] = config
    return verdict


def publish(
    version: str,
    commit: str,
    *,
    release_control_receipt: dict[str, Any] | None = None,
    project_start_authorization_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an S4 operation plan without executing an external write."""

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    if version == "V2.49":
        if project_start_authorization_receipt is not None:
            # A bare authorization receipt is intentionally insufficient.  It
            # is accepted only as a compatibility input that still fails
            # closed until the complete release-control chain is provided.
            release_control_receipt = None
        control = release_control_receipt or {}
        verdict = validate_v249_s4_control(version, commit, control)
        authorized = bool(verdict["ok"])
        return _base_receipt(
            command="authorize_s4_plan",
            status=(
                "authorized_operation_plan_not_executed"
                if authorized
                else "s4_authorization_plan_blocked"
            ),
            error_code=(
                None
                if authorized
                else (
                    verdict["errors"][0]
                    if verdict.get("errors")
                    else "E_V249_RELEASE_CONTROL_REQUIRED"
                )
            ),
            version=version,
            release_mode=config["release_mode"],
            approval_model=config["approval_model"],
            **identity,
            publish_state="authorized_not_executed" if authorized else "blocked",
            operation_plan_authorized=authorized,
            release_control_sha256=verdict.get("release_control_sha256"),
            authorization_id=verdict.get("authorization_id"),
            asset_set_id=verdict.get("asset_set_id"),
            asset_set_digest=verdict.get("asset_set_digest"),
            required_operations=[
                "git_push_tag_via_ssh",
                "github_release_via_api",
                "github_release_asset_upload_via_api",
                "github_release_exact_readback_via_api",
                "formal_install_from_published_asset",
                "formal_install_exact_readback",
            ],
            action_executed=False,
            check_state="not_started" if authorized else "blocked",
            run_outcome="not_run" if authorized else "blocked",
            evidence_state="not_created" if authorized else "invalid",
            ok=False,
            passed=False,
            additional_user_confirmation_required=False,
            https_git_fallback_allowed=False,
        )
    return _base_receipt(
        command="authorize_s4_plan",
        status="requires_explicit_user_approval",
        ok=False,
        passed=False,
        version=version,
        release_mode=config["release_mode"],
        approval_model=config["approval_model"],
        **identity,
        publish_state="requires_explicit_user_approval",
        operation_plan_authorized=False,
        required_operations=[
            "push_candidate_commit",
            "create_version_tag",
            "create_github_release",
        ],
        action_executed=False,
        check_state="blocked",
        run_outcome="blocked",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--version", default="V2.49")
    plan_parser.add_argument("--commit", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--version", default="V2.49")
    verify_parser.add_argument("--commit", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--version", default="V2.49")
    validate_parser.add_argument("--commit", required=True)
    validate_parser.add_argument("--release-root", type=Path, required=True)
    validate_parser.add_argument("--build-receipt", type=Path, required=True)
    s3_parser = subparsers.add_parser("s3-receipt")
    s3_parser.add_argument(
        "--project-size", choices=("small", "medium", "large"), required=True
    )
    s3_parser.add_argument("--s2-receipt", type=Path, required=True)
    s3_parser.add_argument("--install-report", type=Path)
    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--version", default="V2.49")
    preflight_parser.add_argument("--commit", required=True)
    preflight_parser.add_argument(
        "--project-size", choices=("small", "medium", "large"), required=True
    )
    preflight_parser.add_argument("--authorization-receipt", type=Path, required=True)
    preflight_parser.add_argument("--s1-check-receipt", type=Path, required=True)
    preflight_parser.add_argument(
        "--asset-validation-receipt", type=Path, required=True
    )
    preflight_parser.add_argument("--s3-receipt", type=Path, required=True)
    preflight_parser.add_argument("--boundary-receipt", type=Path, required=True)
    for command_name in ("plan-s4", "publish"):
        publish_parser = subparsers.add_parser(command_name)
        publish_parser.add_argument("--version", default="V2.49")
        publish_parser.add_argument("--commit", required=True)
        publish_parser.add_argument(
            "--release-control-receipt", type=Path, required=True
        )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.command == "plan":
            receipt = plan(args.version, args.commit)
        elif args.command == "verify":
            receipt = verify(args.version, args.commit)
        elif args.command == "validate":
            receipt = validate_existing_asset_set(
                args.version,
                args.commit,
                release_root=args.release_root,
                build_receipt=_read_receipt_file(args.build_receipt),
            )
        elif args.command == "s3-receipt":
            s2_input = _read_receipt_file(args.s2_receipt)
            s2 = s2_input.get("s2_receipt", s2_input)
            install_report = (
                _read_receipt_file(args.install_report)
                if args.install_report is not None
                else None
            )
            receipt = build_s3_receipt(
                project_size=args.project_size,
                s2_receipt=s2,
                install_report=install_report,
            )
        elif args.command == "preflight":
            receipt = preflight_release_control(
                args.version,
                args.commit,
                project_size=args.project_size,
                authorization_receipt=_read_receipt_file(
                    args.authorization_receipt
                ),
                s1_check_receipt=_read_receipt_file(args.s1_check_receipt),
                asset_validation_receipt=_read_receipt_file(
                    args.asset_validation_receipt
                ),
                s3_receipt=_read_receipt_file(args.s3_receipt),
                boundary_receipt=_read_receipt_file(args.boundary_receipt),
            )
        else:
            receipt = publish(
                args.version,
                args.commit,
                release_control_receipt=_read_receipt_file(
                    args.release_control_receipt
                ),
            )
    except SkillReleaseError as exc:
        print(json.dumps(exc.receipt, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from exc
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if args.command in {"plan-s4", "publish"} and not receipt.get(
        "operation_plan_authorized"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
