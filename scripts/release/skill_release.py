#!/usr/bin/env python3
"""Fail-closed local release helper for the Goal Teams Skill package.

This helper intentionally has no GitHub, installation, tag, or publication
side effect. ``plan`` is read-only. V2.62 ``validate`` checks the same asset
set created by the single explicit S2 build; it never starts another build or makes
a reproducibility claim. ``preflight`` and ``plan-s4`` require the complete
project-start-authorization and S0-S4 receipt chain. The compatibility command
``publish`` is also only an authorization plan and can never report execution.

The in-place v250 flow is generation-specific.  Published predecessors that
shared that path must be operated from their exact tagged helper; this Current
helper rejects them before identity resolution so it cannot mix their version
with V2.62 contracts or assets.
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
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
RECEIPT_SCHEMA = "goal-teams-skill-release-receipt-v1"
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
POSITIVE_DECIMAL_RE = re.compile(r"^[1-9][0-9]*$")
ACTIVE_SIMPLE_VERSION = "V2.62"
SINGLE_BUILD_VERSIONS = frozenset({"V2.49", "V2.50", "V2.52", "V2.6", "V2.62"})
SHARED_FLOW_PREDECESSORS = frozenset({"V2.50", "V2.52", "V2.6"})
V249_REPOSITORY = "vibe-coding-era/goal-teams"
V250_REPOSITORY = V249_REPOSITORY
_RUNTIME_COMMON_STATIC_INPUT_PATHS = (
    ".agents/skills/goal-teams/SKILL.md",
    "AGENTS.md",
    "RULES.md",
    "SKILL.md",
)


def _version_digits(version: str) -> str:
    if version not in SINGLE_BUILD_VERSIONS:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_VERSION",
            "release flow is defined only for V2.49, V2.50, V2.52, V2.6, and V2.62",
            version=version,
        )
    return version.removeprefix("V").replace(".", "")


def _version_lower(version: str) -> str:
    return version.lower()


def _protocol_digits(version: str) -> str:
    """Return the compatible execution-protocol directory generation."""

    return "250" if version in {"V2.52", "V2.6", "V2.62"} else _version_digits(version)


def _protocol_lower(version: str) -> str:
    return "v2.50" if version in {"V2.52", "V2.6", "V2.62"} else _version_lower(version)


def _version_error(version: str, suffix: str) -> str:
    return f"E_V{_version_digits(version)}_{suffix}"


def runtime_static_input_paths(version: str) -> tuple[str, ...]:
    digits = _protocol_digits(version)
    lower = _version_lower(version)
    schema_lower = _protocol_lower(version)
    return _RUNTIME_COMMON_STATIC_INPUT_PATHS + (
        f"references/profiles/goal-teams-self-release-{lower}.md",
        f"references/release-profiles/{lower}.json",
        f"references/current/generations/{version}/contracts/release-route-manifest.json",
        f"references/current/generations/{version}/contracts/release-command-manifest.json",
        f"schemas/{schema_lower}/runtime-transition-receipt.schema.json",
        f"scripts/checks/check-v{digits}.py",
        f"scripts/v{digits}/runtime_host_adapter.py",
        f"scripts/v{digits}/runtime_transition.py",
    )


def continuation_asset_names(version: str) -> tuple[str, ...]:
    _version_digits(version)
    return (
        "SHA256SUMS",
        "_files.sha256",
        "_release.json",
        f"goal-teams-{version}.tar.gz",
    )


def _receipt_version(receipt: Mapping[str, Any]) -> str:
    schema = receipt.get("schema_version")
    for version in sorted(SINGLE_BUILD_VERSIONS):
        if isinstance(schema, str) and schema.startswith(
            f"goal-teams-{_version_lower(version)}-"
        ):
            return version
    raise SkillReleaseError(
        "E_SKILL_RELEASE_RECEIPT_VERSION",
        "receipt does not identify a supported release generation",
    )


V249_RUNTIME_STATIC_INPUT_PATHS = runtime_static_input_paths("V2.49")
V252_RUNTIME_STATIC_INPUT_PATHS = runtime_static_input_paths("V2.52")
V250_RUNTIME_STATIC_INPUT_PATHS = runtime_static_input_paths("V2.62")
V251_RUNTIME_STATIC_INPUT_PATHS = V250_RUNTIME_STATIC_INPUT_PATHS
V26_RUNTIME_STATIC_INPUT_PATHS = runtime_static_input_paths("V2.6")
V262_RUNTIME_STATIC_INPUT_PATHS = V250_RUNTIME_STATIC_INPUT_PATHS
V249_CONTINUATION_FORMAL_RECEIPTS = (
    "authorization.json",
    "controller-handoff.json",
    "github-owner-key-validation.json",
    "release-route-receipt.json",
    "released-runtime-transition.json",
    "s1-check.json",
    "s2-build.json",
    "asset-validation.json",
    "repository-boundary.json",
    "repository-boundary-pre-s4.json",
    "s3.json",
    "release-control.json",
    "s4-authorized-operation-plan.json",
)
V249_CONTINUATION_DIAGNOSTIC_OUTPUTS = (
    "preflight-output.json",
    "plan-output.json",
)
V249_CONTINUATION_PHASE_ORDER = (
    "identity",
    "authorization",
    "controller_handoff",
    "release_route",
    "github_owner_key",
    "runtime_transition",
    "s1",
    "s2_build",
    "asset_validation",
    "repository_boundary",
    "boundary_pre_s3",
    "s3_prepare",
    "s3_install",
    "s3_bind",
    "boundary_pre_s4",
    "s4_plan",
    "asset_verify",
)
V249_CONTINUATION_LARGE_ONLY_PHASES = frozenset(
    {"boundary_pre_s3", "s3_prepare", "s3_install"}
)
V249_CONTINUATION_ASSET_NAMES = (
    "SHA256SUMS",
    "_files.sha256",
    "_release.json",
    "goal-teams-V2.49.tar.gz",
)
V250_CONTINUATION_FORMAL_RECEIPTS = V249_CONTINUATION_FORMAL_RECEIPTS
V250_CONTINUATION_DIAGNOSTIC_OUTPUTS = V249_CONTINUATION_DIAGNOSTIC_OUTPUTS
V250_CONTINUATION_PHASE_ORDER = V249_CONTINUATION_PHASE_ORDER
V250_CONTINUATION_LARGE_ONLY_PHASES = V249_CONTINUATION_LARGE_ONLY_PHASES
V250_CONTINUATION_ASSET_NAMES = continuation_asset_names("V2.50")
V251_CONTINUATION_ASSET_NAMES = continuation_asset_names("V2.52")
V26_CONTINUATION_ASSET_NAMES = continuation_asset_names("V2.6")
V262_CONTINUATION_ASSET_NAMES = continuation_asset_names("V2.62")


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


def _release_flow_path(version: str) -> Path:
    return ROOT / "scripts" / f"v{_protocol_digits(version)}" / "release_flow.py"


def _v250_release_flow_module() -> ModuleType:
    return _load_module(
        "_goal_teams_v250_release_flow",
        _release_flow_path("V2.50"),
    )


def _release_flow_module(version: str) -> ModuleType:
    if version in SHARED_FLOW_PREDECESSORS:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_PREDECESSOR_FLOW_UNAVAILABLE",
            "published predecessor requires its exact tagged release helper",
            version=version,
        )
    if version == "V2.49":
        return _v249_release_flow_module()
    if version in {"V2.50", "V2.52", "V2.6", "V2.62"}:
        return _v250_release_flow_module()
    _version_digits(version)
    raise AssertionError("unreachable")


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


def _validate_v249_runtime_external_anchor(
    *,
    runtime: dict[str, Any],
    activation_path: str,
    frozen_bytes: Callable[[str], bytes],
    version: str = "V2.49",
) -> dict[str, str]:
    """Bind the strict runtime's complete static and dynamic input closure."""

    runtime_digests = runtime.get("input_digests")
    loaded_paths = runtime.get("loaded_paths")
    current_paths = runtime.get("current_loaded_paths")
    current_digests = runtime.get("current_input_digests")
    try:
        activation = json.loads(frozen_bytes(activation_path))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise SkillReleaseError(
            _version_error(version, "RUNTIME_EXTERNAL_ANCHOR"),
            "released runtime inputs differ from the exact commit",
            command="preflight",
        ) from exc
    prompt_manifest_path = (
        activation.get("prompt_manifest_path")
        if isinstance(activation, dict)
        else None
    )
    if (
        not isinstance(runtime_digests, dict)
        or not runtime_digests
        or not all(isinstance(path, str) and path for path in runtime_digests)
        or not isinstance(loaded_paths, list)
        or not all(isinstance(path, str) and path for path in loaded_paths)
        or loaded_paths != sorted(runtime_digests)
        or not isinstance(current_paths, list)
        or not current_paths
        or not all(isinstance(path, str) and path for path in current_paths)
        or len(current_paths) != len(set(current_paths))
        or not isinstance(current_digests, dict)
        or not isinstance(prompt_manifest_path, str)
        or not prompt_manifest_path
    ):
        raise SkillReleaseError(
            _version_error(version, "RUNTIME_EXTERNAL_ANCHOR"),
            "released runtime inputs differ from the exact commit",
            command="preflight",
        )
    expected_paths = (
        set(runtime_static_input_paths(version))
        | {
            "references/current/ACTIVE.json",
            activation_path,
            prompt_manifest_path,
        }
        | set(current_paths)
    )
    if (
        set(runtime_digests) != expected_paths
        or current_digests
        != {path: runtime_digests.get(path) for path in current_paths}
        or any(
            not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
            or digest != hashlib.sha256(frozen_bytes(path)).hexdigest()
            for path, digest in runtime_digests.items()
        )
    ):
        raise SkillReleaseError(
            _version_error(version, "RUNTIME_EXTERNAL_ANCHOR"),
            "released runtime inputs differ from the exact commit",
            command="preflight",
        )
    return runtime_digests


def _validate_v250_runtime_external_anchor(
    *,
    runtime: dict[str, Any],
    activation_path: str,
    frozen_bytes: Callable[[str], bytes],
    version: str = "V2.62",
) -> dict[str, str]:
    return _validate_v249_runtime_external_anchor(
        runtime=runtime,
        activation_path=activation_path,
        frozen_bytes=frozen_bytes,
        version=version,
    )


def _security_external_anchor_paths(manifest: object) -> set[str]:
    """Derive the security contract denominator from its frozen manifest."""

    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("review_targets"), list
    ):
        raise ValueError("security review manifest is malformed")
    paths: set[str] = set()
    for target in manifest["review_targets"]:
        if (
            not isinstance(target, dict)
            or not isinstance(target.get("path"), str)
            or not isinstance(target.get("categories"), list)
        ):
            raise ValueError("security review target is malformed")
        if "contract" in target["categories"]:
            paths.add(target["path"])
    if not paths:
        raise ValueError("security review contract denominator is empty")
    return paths


def _validate_v249_external_anchors(
    *,
    commit: str,
    source_tree: str,
    s1_check_receipt: dict[str, Any],
    asset_validation_receipt: dict[str, Any],
    version: str = "V2.49",
) -> dict[str, Any]:
    """Recompute Current/runtime/security anchors from the exact Git commit."""

    builder = _builder_module()
    entries = builder.tree(commit)

    def frozen_bytes(relative: str) -> bytes:
        row = entries.get(relative)
        if row is None:
            raise SkillReleaseError(
                _version_error(version, "EXTERNAL_ANCHOR_PATH"),
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
            _version_error(version, "EXTERNAL_ANCHOR_RECEIPT"),
            "raw S1/runtime/S2/integrity receipts are required",
            command="preflight",
            source_commit=commit,
        ) from exc

    digits = _protocol_digits(version)
    lower = _version_lower(version)
    release_flow = _release_flow_module(version)
    command_manifest_path = (
        f"references/current/generations/{version}/contracts/"
        "release-command-manifest.json"
    )
    command_manifest_bytes = frozen_bytes(command_manifest_path)
    if version == "V2.62":
        try:
            command_manifest = json.loads(command_manifest_bytes)
            expected_test_roots = command_manifest["release"]["s1"][
                "current_full_regression_denominator"
            ]["test_roots"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillReleaseError(
                _version_error(version, "CURRENT_DENOMINATOR_EXTERNAL_ANCHOR"),
                "Current test roots are missing from the exact release contract",
                command="preflight",
                source_commit=commit,
            ) from exc
        if expected_test_roots != ["tests/v250", "tests/v262"]:
            raise SkillReleaseError(
                _version_error(version, "CURRENT_DENOMINATOR_EXTERNAL_ANCHOR"),
                "Current test roots differ from the V2.62 release contract",
                command="preflight",
                source_commit=commit,
            )
    else:
        expected_test_roots = [f"tests/v{digits}"]
    expected_test_files = [
        {
            "path": path,
            "sha256": hashlib.sha256(frozen_bytes(path)).hexdigest(),
        }
        for path in sorted(entries)
        if any(path.startswith(root + "/") for root in expected_test_roots)
        and Path(path).name.startswith("test_")
        and path.endswith(".py")
    ]
    denominator = full.get("denominator") if isinstance(full, dict) else None
    if (
        not expected_test_files
        or not isinstance(denominator, dict)
        or (
            version == "V2.62"
            and denominator.get("test_roots") != expected_test_roots
        )
        or denominator.get("test_files") != expected_test_files
        or denominator.get("test_file_count") != len(expected_test_files)
        or denominator.get("test_file_set_sha256")
        != release_flow.canonical_sha256(expected_test_files)
        or denominator.get("source_commit") != commit
        or denominator.get("source_tree") != source_tree
        or denominator.get("contract_sha256")
        != hashlib.sha256(command_manifest_bytes).hexdigest()
    ):
        raise SkillReleaseError(
            _version_error(version, "CURRENT_DENOMINATOR_EXTERNAL_ANCHOR"),
            "Current full-regression denominator differs from the exact commit",
            command="preflight",
            source_commit=commit,
        )

    active = json.loads(frozen_bytes("references/current/ACTIVE.json"))
    activation_path = active.get("activation_manifest")
    runtime_digests = _validate_v249_runtime_external_anchor(
        runtime=runtime if isinstance(runtime, dict) else {},
        activation_path=str(activation_path),
        frozen_bytes=frozen_bytes,
        version=version,
    )

    security_digests = security.get("contract_digests") if isinstance(security, dict) else None
    security_manifest_path = (
        f"references/current/generations/{version}/contracts/"
        "release-security-review-manifest.json"
    )
    try:
        expected_security_paths = _security_external_anchor_paths(
            json.loads(frozen_bytes(security_manifest_path))
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SkillReleaseError(
            _version_error(version, "SECURITY_EXTERNAL_ANCHOR"),
            "security denominator or runner differs from the exact commit",
            command="preflight",
            source_commit=commit,
        ) from exc
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
            frozen_bytes(f"scripts/checks/run-v{digits}-release-security-review.py")
        ).hexdigest()
    ):
        raise SkillReleaseError(
            _version_error(version, "SECURITY_EXTERNAL_ANCHOR"),
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
            _version_error(version, "ASSET_EXTERNAL_ANCHOR"),
            "S2 or same-built-asset integrity receipt is inconsistent",
            command="preflight",
            source_commit=commit,
        )
    anchor = {
        "schema_version": f"goal-teams-{lower}-external-anchor-validation-v1",
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


def _validate_v250_external_anchors(
    *,
    commit: str,
    source_tree: str,
    s1_check_receipt: dict[str, Any],
    asset_validation_receipt: dict[str, Any],
    version: str = "V2.62",
) -> dict[str, Any]:
    return _validate_v249_external_anchors(
        commit=commit,
        source_tree=source_tree,
        s1_check_receipt=s1_check_receipt,
        asset_validation_receipt=asset_validation_receipt,
        version=version,
    )


def _validate_external_anchors(version: str, **kwargs: Any) -> dict[str, Any]:
    if version == "V2.49":
        return _validate_v249_external_anchors(**kwargs)
    if version in {"V2.50", "V2.52", "V2.6", "V2.62"}:
        return _validate_v250_external_anchors(version=version, **kwargs)
    _version_digits(version)
    raise AssertionError("unreachable")


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
    if version in SHARED_FLOW_PREDECESSORS:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_PREDECESSOR_FLOW_UNAVAILABLE",
            "published predecessor requires its exact tagged release helper",
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
        if version in SINGLE_BUILD_VERSIONS
        else "single_human_before_external_write"
    )
    expected_gate_count = 6 if version in SINGLE_BUILD_VERSIONS else 5
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
    if version in SINGLE_BUILD_VERSIONS:
        route_value = route or {
            "project_size": "medium",
            "workflow_phase": "development",
            "release_intent": False,
            "implementation_scope_complete": False,
            "stage": "candidate",
        }
        release_plan = _release_flow_module(version).derive_release_plan(route_value)
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

    V2.49/V2.50 requires the explicit ``build-release.py`` S2 entrypoint followed by
    ``validate_existing_asset_set``.  Refusing it here prevents this helper
    from accidentally becoming a second build path.
    """

    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    if version in SINGLE_BUILD_VERSIONS:
        raise SkillReleaseError(
            _version_error(version, "EXPLICIT_SINGLE_BUILD_REQUIRED"),
            f"{version} S2 must use build-release.py once, then validate the same asset set",
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
                "status": f"not_run_by_v{_version_digits(version)}_policy",
                "reason": "repository_boundary_compliance_is_independent",
            }
            if version in SINGLE_BUILD_VERSIONS
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
    if version in SINGLE_BUILD_VERSIONS:
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
                    "reproducibility": (
                        f"not_verified_by_v{_version_digits(version)}_policy"
                    ),
                    "s2_security_checks": (
                        f"not_run_by_v{_version_digits(version)}_policy"
                    ),
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
    """Validate the asset set from one explicit V2.49 or V2.50 S2 build.

    This function never calls the builder.  ``validate-release.py`` validates
    frozen-source and boundary integrity for the same bytes and modes already
    present under ``release_root``; this is not a reproducibility comparison.
    """

    if version not in SINGLE_BUILD_VERSIONS:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_VALIDATE_VERSION",
            "same-built-asset validation is defined for V2.49 and V2.50",
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
            _version_error(version, "EXISTING_ASSET_SET_REQUIRED"),
            f"the already-built {version} snapshot is missing or unsafe",
            command="validate",
            version=version,
            source_commit=commit,
            asset_build_invocation_count=0,
        )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillReleaseError(
            _version_error(version, "EXISTING_ASSET_SET_RECORD"),
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
            _version_error(version, "S2_BUILD_RECEIPT_DRIFT"),
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
            _version_error(version, "PUBLIC_ASSET_SET"),
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
    digits = _version_digits(version)
    lower = _version_lower(version)
    release_flow = _release_flow_module(version)
    asset_set_digest = release_flow.canonical_sha256(assets)
    asset_set_id = f"V{digits}-ASSET-{asset_set_digest[:20]}"
    s2_receipt = release_flow.build_s2_receipt(
        source_commit=commit,
        source_tree=identity["source_git_tree"],
        asset_set_id=asset_set_id,
        assets=assets,
        build_run_id=f"V{digits}-S2-{commit[:12]}-{asset_set_digest[:12]}",
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
    validator_errors = validation.get("errors") if isinstance(validation, dict) else []
    if not isinstance(validator_errors, list) or not all(
        isinstance(error, str) for error in validator_errors
    ):
        validator_errors = []
    if result.returncode != 0 or validation.get("passed") is not True:
        raise SkillReleaseError(
            _version_error(version, "SAME_ASSET_INTEGRITY_VALIDATION"),
            "frozen-source and boundary integrity validation failed",
            command="validate",
            version=version,
            source_commit=commit,
            asset_set_id=asset_set_id,
            asset_build_invocation_count=0,
            validator_returncode=result.returncode,
            validator_output_sha256=hashlib.sha256(output).hexdigest(),
            validator_errors=validator_errors,
        )
    validation_receipt = {
        "schema_version": f"goal-teams-{lower}-same-asset-validation-receipt-v1",
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
        "release_id": f"v{digits}-s3-{asset_set_digest[:16]}",
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
        reproducibility=f"not_verified_by_v{digits}_policy",
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

    version = _receipt_version(s2_receipt)
    digits = _version_digits(version)
    lower = _version_lower(version)
    release_flow = _release_flow_module(version)
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
        "schema_version": f"goal-teams-{lower}-s3-receipt-v1",
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
            or source.get("version") != version
            or source.get("commit") != s2_receipt["source_commit"]
            or source.get("git_tree_id") != s2_receipt["source_tree"]
            or observed_assets != expected_assets
        ):
            raise SkillReleaseError(
                _version_error(version, "S3_INSTALL_REPORT_DRIFT"),
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
    if version not in SINGLE_BUILD_VERSIONS:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_CONTROL_VERSION",
            "release-control preflight is defined for V2.49 and V2.50",
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
            _version_error(version, "RELEASE_CONTROL_RECEIPT_MISSING"),
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
            _version_error(version, "S1_NOT_CURRENT"),
            "S1 checker receipt is not passed/current",
            command="preflight",
            version=version,
            source_commit=commit,
        )
    release_flow = _release_flow_module(version)
    try:
        external_anchor = _validate_external_anchors(
            version,
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


def _validate_s4_control(
    version: str,
    commit: str,
    release_control_receipt: dict[str, Any],
    *,
    runtime_route_receipt_path: Path | str | None = None,
    runtime_authorization_receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    """Revalidate a complete control receipt against the exact frozen commit.

    The pure receipt validator deliberately cannot read Git.  This public
    boundary adds the external anchors that prevent a re-sealed synthetic
    denominator, runtime summary, or security summary from authorizing S4.
    """

    if version not in SINGLE_BUILD_VERSIONS:
        return {
            "ok": False,
            "passed": False,
            "errors": ["E_SKILL_RELEASE_CONTROL_VERSION"],
        }
    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    control = release_control_receipt
    verdict = _release_flow_module(version).validate_release_control_receipt(
        control,
        expected_repository=V249_REPOSITORY,
        expected_version=version,
        expected_candidate_branch=config["candidate_branch"],
        expected_tag=config["tag"],
        expected_source_commit=commit,
        expected_source_tree=identity["source_git_tree"],
        runtime_route_receipt_path=runtime_route_receipt_path,
        runtime_authorization_receipt_path=(
            runtime_authorization_receipt_path
        ),
    )
    try:
        recomputed_anchor = _validate_external_anchors(
            version,
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
            _version_error(version, "EXTERNAL_ANCHOR_REVALIDATION"),
            *[
                error
                for error in verdict.get("errors", [])
                if error != _version_error(version, "EXTERNAL_ANCHOR_REVALIDATION")
            ],
        ]
    verdict["errors"] = list(dict.fromkeys(verdict.get("errors", [])))
    verdict["ok"] = bool(verdict.get("ok") and anchor_matches)
    verdict["passed"] = verdict["ok"]
    verdict["source_tree"] = identity["source_git_tree"]
    verdict["source_identity"] = identity
    verdict["release_config"] = config
    return verdict


def validate_v249_s4_control(
    version: str,
    commit: str,
    release_control_receipt: dict[str, Any],
    *,
    runtime_route_receipt_path: Path | str | None = None,
    runtime_authorization_receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    if version != "V2.49":
        return {
            "ok": False,
            "passed": False,
            "errors": ["E_V249_RELEASE_CONTROL_VERSION"],
        }
    return _validate_s4_control(
        version,
        commit,
        release_control_receipt,
        runtime_route_receipt_path=runtime_route_receipt_path,
        runtime_authorization_receipt_path=runtime_authorization_receipt_path,
    )


def validate_v250_s4_control(
    version: str,
    commit: str,
    release_control_receipt: dict[str, Any],
    *,
    runtime_route_receipt_path: Path | str | None = None,
    runtime_authorization_receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    if version not in {"V2.50", "V2.52", "V2.6", "V2.62"}:
        return {
            "ok": False,
            "passed": False,
            "errors": ["E_V250_RELEASE_CONTROL_VERSION"],
        }
    return _validate_s4_control(
        version,
        commit,
        release_control_receipt,
        runtime_route_receipt_path=runtime_route_receipt_path,
        runtime_authorization_receipt_path=runtime_authorization_receipt_path,
    )


def _validate_version_s4_control(
    version: str,
    commit: str,
    release_control_receipt: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    if version == "V2.49":
        return validate_v249_s4_control(
            version, commit, release_control_receipt, **kwargs
        )
    if version in {"V2.50", "V2.52", "V2.6", "V2.62"}:
        return validate_v250_s4_control(
            version, commit, release_control_receipt, **kwargs
        )
    _version_digits(version)
    raise AssertionError("unreachable")


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
    if version in SINGLE_BUILD_VERSIONS:
        if project_start_authorization_receipt is not None:
            # A bare authorization receipt is intentionally insufficient.  It
            # is accepted only as a compatibility input that still fails
            # closed until the complete release-control chain is provided.
            release_control_receipt = None
        control = release_control_receipt or {}
        verdict = _validate_version_s4_control(version, commit, control)
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
                    else _version_error(version, "RELEASE_CONTROL_REQUIRED")
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


def _checkpoint_file_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        return None
    return {"size": path.stat().st_size, "sha256": _sha256_file(path)}


def _checkpoint_json(
    path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    record = _checkpoint_file_record(path)
    if record is None:
        return None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, {**record, "json_state": "invalid"}
    if not isinstance(value, dict):
        return None, {**record, "json_state": "invalid"}
    return value, {**record, "json_state": "valid_object"}


def _v249_public_asset_paths(release_root: Path) -> dict[str, Path]:
    return _public_asset_paths("V2.49", release_root)


def _v250_public_asset_paths(release_root: Path) -> dict[str, Path]:
    return _public_asset_paths("V2.50", release_root)


def _public_asset_paths(version: str, release_root: Path) -> dict[str, Path]:
    _version_digits(version)
    snapshot = release_root / version
    return {
        "SHA256SUMS": snapshot / "_artifacts" / "SHA256SUMS",
        "_files.sha256": snapshot / "_files.sha256",
        "_release.json": snapshot / "_release.json",
        f"goal-teams-{version}.tar.gz": (
            snapshot / "_artifacts" / f"goal-teams-{version}.tar.gz"
        ),
    }


def _checkpoint_gate_errors(
    *,
    project_size: str,
    gate_outcomes: Mapping[str, str],
    version: str = "V2.49",
) -> list[str]:
    if set(gate_outcomes) != set(V249_CONTINUATION_PHASE_ORDER):
        return [_version_error(version, "CHECKPOINT_GATE_OUTCOME_SET")]
    errors: list[str] = []
    for phase in V249_CONTINUATION_PHASE_ORDER:
        outcome = gate_outcomes[phase]
        if outcome not in {"success", "failure", "skipped", "cancelled"}:
            errors.append(_version_error(version, "CHECKPOINT_GATE_OUTCOME_VALUE"))
            continue
        if project_size != "large" and phase in V249_CONTINUATION_LARGE_ONLY_PHASES:
            if outcome != "skipped":
                errors.append(_version_error(version, "CHECKPOINT_GATE_OUTCOME"))
        elif outcome != "success":
            errors.append(_version_error(version, "CHECKPOINT_GATE_OUTCOME"))
    return list(dict.fromkeys(errors))


def _v249_checkpoint_gate_errors(
    *, project_size: str, gate_outcomes: Mapping[str, str]
) -> list[str]:
    return _checkpoint_gate_errors(
        project_size=project_size,
        gate_outcomes=gate_outcomes,
        version="V2.49",
    )


def _v250_checkpoint_gate_errors(
    *, project_size: str, gate_outcomes: Mapping[str, str]
) -> list[str]:
    return _checkpoint_gate_errors(
        project_size=project_size,
        gate_outcomes=gate_outcomes,
        version="V2.50",
    )


def _valid_v249_s4_plan(
    plan: Mapping[str, Any],
    *,
    commit: str,
    source_tree: str,
    control: Mapping[str, Any],
) -> bool:
    authorization = control.get("authorization_receipt")
    authorization_id = (
        authorization.get("authorization_id")
        if isinstance(authorization, Mapping)
        else None
    )
    return (
        plan.get("status") == "authorized_operation_plan_not_executed"
        and plan.get("publish_state") == "authorized_not_executed"
        and plan.get("external_side_effect_count") == 0
        and plan.get("action_executed") is False
        and plan.get("operation_plan_authorized") is True
        and plan.get("source_commit") == commit
        and plan.get("source_git_tree") == source_tree
        and plan.get("release_control_sha256")
        == control.get("release_control_sha256")
        and plan.get("authorization_id") == authorization_id
        and plan.get("asset_set_id") == control.get("asset_set_id")
        and plan.get("asset_set_digest") == control.get("asset_set_digest")
        and plan.get("check_state") == "not_started"
        and plan.get("run_outcome") == "not_run"
        and plan.get("evidence_state") == "not_created"
        and plan.get("ok") is False
        and plan.get("passed") is False
        and plan.get("additional_user_confirmation_required") is False
        and plan.get("https_git_fallback_allowed") is False
    )


def _valid_v250_s4_plan(
    plan: Mapping[str, Any],
    *,
    commit: str,
    source_tree: str,
    control: Mapping[str, Any],
) -> bool:
    return _valid_v249_s4_plan(
        plan,
        commit=commit,
        source_tree=source_tree,
        control=control,
    )


def _v249_checkpoint_receipt_binding_errors(
    receipt_values: Mapping[str, Mapping[str, Any]],
    control: Mapping[str, Any],
    *,
    version: str = "V2.49",
) -> list[str]:
    s1_check = receipt_values.get("s1-check.json", {})
    release_gate_receipts = s1_check.get("release_gate_receipts", {})
    if not isinstance(release_gate_receipts, Mapping):
        release_gate_receipts = {}
    runtime = receipt_values.get("released-runtime-transition.json", {})
    asset_validation = receipt_values.get("asset-validation.json", {})
    bindings = {
        "authorization_receipt": receipt_values.get("authorization.json"),
        "released_runtime_transition": runtime,
        "s0": s1_check.get("s0_receipt"),
        "full_regression": release_gate_receipts.get("full_regression"),
        "release_security_review": release_gate_receipts.get(
            "release_security_review"
        ),
        "s1": s1_check.get("s1_receipt"),
        "s2": asset_validation.get("s2_receipt"),
        "asset_integrity_validation": asset_validation.get(
            "asset_integrity_validation_receipt"
        ),
        "s3": receipt_values.get("s3.json"),
        "repository_boundary": receipt_values.get(
            "repository-boundary-pre-s4.json"
        ),
    }
    errors: list[str] = []
    if any(control.get(key) != value for key, value in bindings.items()):
        errors.append(_version_error(version, "CHECKPOINT_RECEIPT_BINDING"))
    if runtime.get("controller_handoff_receipt") != receipt_values.get(
        "controller-handoff.json"
    ):
        errors.append(_version_error(version, "CHECKPOINT_CONTROLLER_BINDING"))
    return errors


def _v250_checkpoint_receipt_binding_errors(
    receipt_values: Mapping[str, Mapping[str, Any]],
    control: Mapping[str, Any],
) -> list[str]:
    return _v249_checkpoint_receipt_binding_errors(
        receipt_values,
        control,
        version="V2.50",
    )


def build_v249_continuation_checkpoint(
    version: str,
    commit: str,
    *,
    project_size: str,
    job_status: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    gate_outcomes: Mapping[str, str],
    receipt_source_root: Path,
    release_root: Path,
) -> dict[str, Any]:
    """Evaluate whether one exact S2 asset chain is safe to continue into S4."""

    if version not in SINGLE_BUILD_VERSIONS or project_size not in {
        "small",
        "medium",
        "large",
    }:
        raise SkillReleaseError(
            "E_SKILL_RELEASE_CHECKPOINT_IDENTITY",
            "continuation checkpoint identity is invalid",
            command="checkpoint",
        )
    if job_status not in {"success", "failure", "cancelled"}:
        raise SkillReleaseError(
            _version_error(version, "CHECKPOINT_JOB_STATUS"),
            "continuation checkpoint job status is invalid",
            command="checkpoint",
        )
    if (
        POSITIVE_DECIMAL_RE.fullmatch(workflow_run_id) is None
        or POSITIVE_DECIMAL_RE.fullmatch(workflow_run_attempt) is None
    ):
        raise SkillReleaseError(
            _version_error(version, "CHECKPOINT_WORKFLOW_IDENTITY"),
            "workflow run ID and attempt must be positive decimal identities",
            command="checkpoint",
        )
    config = _simple_config(version)
    identity = _read_identity(version, commit, config)
    source_tree = identity["source_git_tree"]
    lower = _version_lower(version)
    release_flow = _release_flow_module(version)
    errors = _checkpoint_gate_errors(
        project_size=project_size,
        gate_outcomes=gate_outcomes,
        version=version,
    )

    receipt_values: dict[str, dict[str, Any]] = {}
    observed_outputs: dict[str, dict[str, Any]] = {}
    missing_files: list[str] = []
    for name in V249_CONTINUATION_FORMAL_RECEIPTS:
        value, record = _checkpoint_json(receipt_source_root / name)
        if record is None:
            missing_files.append(f"receipt:{name}")
            continue
        observed_outputs[name] = record
        if value is not None:
            receipt_values[name] = value
        elif job_status == "success":
            errors.append(_version_error(version, "CHECKPOINT_RECEIPT_JSON"))

    diagnostic_files: dict[str, dict[str, Any]] = {}
    for name in V249_CONTINUATION_DIAGNOSTIC_OUTPUTS:
        _, record = _checkpoint_json(receipt_source_root / name)
        if record is not None:
            diagnostic_files[name] = record

    public_assets: dict[str, dict[str, Any]] = {}
    for name, path in _public_asset_paths(version, release_root).items():
        record = _checkpoint_file_record(path)
        if record is None:
            missing_files.append(f"asset:{name}")
        else:
            public_assets[name] = record

    ready_candidate = job_status == "success" and not errors
    required_receipts_present = (
        set(receipt_values) == set(V249_CONTINUATION_FORMAL_RECEIPTS)
    )
    required_assets_present = set(public_assets) == set(
        continuation_asset_names(version)
    )
    if ready_candidate and not required_receipts_present:
        errors.append(_version_error(version, "CHECKPOINT_RECEIPT_SET"))
    if ready_candidate and not required_assets_present:
        errors.append(_version_error(version, "CHECKPOINT_ASSET_SET"))

    asset_validation = receipt_values.get("asset-validation.json", {})
    s2 = asset_validation.get("s2_receipt", {})
    if not isinstance(s2, dict):
        s2 = {}
    s3 = receipt_values.get("s3.json", {})
    authorization = receipt_values.get("authorization.json", {})
    control = receipt_values.get("release-control.json", {})
    plan = receipt_values.get("s4-authorized-operation-plan.json", {})

    if ready_candidate and not errors:
        auth_verdict = release_flow.validate_project_start_authorization(
            authorization,
            repository=V249_REPOSITORY,
            version=version,
            candidate_branch=config["candidate_branch"],
            tag=config["tag"],
        )
        if not auth_verdict.get("ok"):
            errors.extend(auth_verdict.get("errors", []))
        s2_verdict = release_flow.validate_s2_receipt(
            s2,
            source_commit=commit,
            source_tree=source_tree,
        )
        if not s2_verdict.get("ok"):
            errors.extend(s2_verdict.get("errors", []))
        expected_assets = [
            {"name": name, **public_assets[name]}
            for name in sorted(public_assets)
        ]
        if s2.get("assets") != expected_assets:
            errors.append(_version_error(version, "CHECKPOINT_ASSET_BINDING"))
        try:
            control_verdict = _validate_version_s4_control(
                version,
                commit,
                control,
                runtime_route_receipt_path=(
                    receipt_source_root / "release-route-receipt.json"
                ),
                runtime_authorization_receipt_path=(
                    receipt_source_root / "authorization.json"
                ),
            )
        except SkillReleaseError as exc:
            control_verdict = {
                "ok": False,
                "errors": [exc.receipt.get("error_code")],
            }
        if not control_verdict.get("ok"):
            errors.extend(control_verdict.get("errors", []))
        if not _valid_v249_s4_plan(
            plan,
            commit=commit,
            source_tree=source_tree,
            control=control,
        ):
            errors.append(_version_error(version, "CHECKPOINT_PLAN_CONTRACT"))
        errors.extend(
            _v249_checkpoint_receipt_binding_errors(
                receipt_values, control, version=version
            )
        )

    errors = list(dict.fromkeys(str(error) for error in errors if error))
    state = (
        "ready_for_s4"
        if job_status == "success"
        and not errors
        and not missing_files
        and required_receipts_present
        and required_assets_present
        else "diagnostic_partial"
    )
    first_failed_phase = next(
        (
            phase
            for phase in V249_CONTINUATION_PHASE_ORDER
            if gate_outcomes.get(phase) in {"failure", "cancelled"}
        ),
        None,
    )
    if state == "diagnostic_partial" and first_failed_phase is None:
        first_failed_phase = (
            "checkpoint_validation"
            if job_status == "success" and (errors or missing_files)
            else "unclassified_workflow_failure"
        )
    failure_outcome = (
        None
        if first_failed_phase is None
        else gate_outcomes.get(first_failed_phase, job_status)
    )
    formal_files = (
        {
            name: {
                "size": observed_outputs[name]["size"],
                "sha256": observed_outputs[name]["sha256"],
            }
            for name in V249_CONTINUATION_FORMAL_RECEIPTS
        }
        if state == "ready_for_s4"
        else {}
    )
    checkpoint = {
        "schema_version": f"goal-teams-{lower}-continuation-checkpoint-v1",
        "state": state,
        "claim_scope": "release_asset_chain_only",
        "repository": V249_REPOSITORY,
        "version": version,
        "project_size": project_size,
        "source_commit": commit,
        "source_tree": source_tree,
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "gate_outcomes": {
            phase: gate_outcomes.get(phase)
            for phase in V249_CONTINUATION_PHASE_ORDER
        },
        "first_failed_phase": first_failed_phase,
        "failure_outcome": failure_outcome,
        "asset_set_id": s2.get("asset_set_id"),
        "asset_set_digest": s2.get("asset_set_digest"),
        "s2_receipt_sha256": s2.get("receipt_sha256"),
        "authorization_receipt_sha256": (
            release_flow.canonical_sha256(authorization)
            if authorization
            else None
        ),
        "release_control_sha256": control.get("release_control_sha256"),
        "s2_build_invocation_count": s2.get(
            "build_invocation_count_for_asset_set"
        ),
        "s3_process_invocation_count": s3.get("s3_process_invocation_count"),
        "public_assets": public_assets if state == "ready_for_s4" else {},
        "formal_files": formal_files,
        "diagnostic_files": (
            {} if state == "ready_for_s4" else diagnostic_files
        ),
        "observed_output_files": (
            {} if state == "ready_for_s4" else observed_outputs
        ),
        "missing_files": [] if state == "ready_for_s4" else sorted(missing_files),
        "validation_errors": [] if state == "ready_for_s4" else errors,
        "s4_external_side_effect_count": 0,
        "resumable_without_rebuild": state == "ready_for_s4",
    }
    checkpoint["checkpoint_sha256"] = release_flow.canonical_sha256(checkpoint)
    return checkpoint


def build_v250_continuation_checkpoint(
    version: str,
    commit: str,
    **kwargs: Any,
) -> dict[str, Any]:
    if version not in {"V2.50", "V2.52", "V2.6", "V2.62"}:
        raise SkillReleaseError(
            "E_V250_CHECKPOINT_IDENTITY",
            "V2.50 continuation checkpoint identity is invalid",
            command="checkpoint",
        )
    return build_v249_continuation_checkpoint(version, commit, **kwargs)


def validate_v249_continuation_checkpoint(
    version: str,
    commit: str,
    checkpoint: object,
    *,
    receipt_root: Path,
    release_root: Path,
    expected_workflow_run_id: str,
    expected_workflow_run_attempt: str,
) -> dict[str, Any]:
    """Fail closed unless a staged continuation artifact exactly matches its checkpoint."""

    if version not in SINGLE_BUILD_VERSIONS:
        return _base_receipt(
            command="verify-continuation-checkpoint",
            status="failed",
            error_code="E_SKILL_RELEASE_CHECKPOINT_IDENTITY",
            version=version,
            source_commit=commit,
            errors=["E_SKILL_RELEASE_CHECKPOINT_IDENTITY"],
            check_state="failed",
            run_outcome="failed",
            evidence_state="invalid",
        )
    value = checkpoint if isinstance(checkpoint, dict) else {}
    errors: list[str] = []
    lower = _version_lower(version)
    release_flow = _release_flow_module(version)
    payload = dict(value)
    claimed_digest = payload.pop("checkpoint_sha256", None)
    if (
        value.get("schema_version")
        != f"goal-teams-{lower}-continuation-checkpoint-v1"
        or value.get("state") != "ready_for_s4"
        or value.get("claim_scope") != "release_asset_chain_only"
        or value.get("repository") != V249_REPOSITORY
        or value.get("version") != version
        or value.get("source_commit") != commit
        or value.get("workflow_run_id") != expected_workflow_run_id
        or value.get("workflow_run_attempt") != expected_workflow_run_attempt
        or POSITIVE_DECIMAL_RE.fullmatch(expected_workflow_run_id) is None
        or POSITIVE_DECIMAL_RE.fullmatch(expected_workflow_run_attempt) is None
        or claimed_digest != release_flow.canonical_sha256(payload)
    ):
        errors.append(_version_error(version, "CONTINUATION_CHECKPOINT_IDENTITY"))
    try:
        identity = _read_identity(version, commit, _simple_config(version))
    except SkillReleaseError:
        identity = {}
        errors.append(_version_error(version, "CONTINUATION_CHECKPOINT_IDENTITY"))
    if value.get("source_tree") != identity.get("source_git_tree"):
        errors.append(_version_error(version, "CONTINUATION_CHECKPOINT_IDENTITY"))
    if (
        value.get("first_failed_phase") is not None
        or value.get("failure_outcome") is not None
        or value.get("missing_files") != []
        or value.get("validation_errors") != []
        or value.get("diagnostic_files") != {}
        or value.get("observed_output_files") != {}
        or value.get("s4_external_side_effect_count") != 0
        or value.get("resumable_without_rebuild") is not True
    ):
        errors.append(_version_error(version, "CONTINUATION_CHECKPOINT_STATE"))
    project_size = value.get("project_size")
    gate_outcomes = value.get("gate_outcomes")
    if (
        project_size not in {"small", "medium", "large"}
        or not isinstance(gate_outcomes, dict)
        or _checkpoint_gate_errors(
            project_size=str(project_size),
            gate_outcomes=gate_outcomes,
            version=version,
        )
    ):
        errors.append(_version_error(version, "CONTINUATION_GATE_OUTCOMES"))

    formal = value.get("formal_files")
    if not isinstance(formal, dict) or set(formal) != set(
        V249_CONTINUATION_FORMAL_RECEIPTS
    ):
        errors.append(_version_error(version, "CONTINUATION_RECEIPT_SET"))
        formal = {}
    actual_receipt_names = {
        path.name
        for path in receipt_root.iterdir()
        if path.is_file() and not path.is_symlink()
    } if receipt_root.is_dir() and not receipt_root.is_symlink() else set()
    if actual_receipt_names != set(V249_CONTINUATION_FORMAL_RECEIPTS) | {
        "_checkpoint.json"
    }:
        errors.append(_version_error(version, "CONTINUATION_RECEIPT_SET"))
    for name in V249_CONTINUATION_FORMAL_RECEIPTS:
        record = _checkpoint_file_record(receipt_root / name)
        if record != formal.get(name):
            errors.append(_version_error(version, "CONTINUATION_RECEIPT_DIGEST"))
            break

    assets = value.get("public_assets")
    if not isinstance(assets, dict) or set(assets) != set(
        continuation_asset_names(version)
    ):
        errors.append(_version_error(version, "CONTINUATION_ASSET_SET"))
        assets = {}
    for name, path in _public_asset_paths(version, release_root).items():
        if _checkpoint_file_record(path) != assets.get(name):
            errors.append(_version_error(version, "CONTINUATION_ASSET_DIGEST"))
            break
    receipt_values: dict[str, dict[str, Any]] = {}
    try:
        receipt_values = {
            name: _read_receipt_file(receipt_root / name)
            for name in V249_CONTINUATION_FORMAL_RECEIPTS
        }
    except SkillReleaseError:
        errors.append(_version_error(version, "CONTINUATION_RECEIPT_JSON"))
    authorization = receipt_values.get("authorization.json", {})
    asset_validation = receipt_values.get("asset-validation.json", {})
    s3 = receipt_values.get("s3.json", {})
    control = receipt_values.get("release-control.json", {})
    plan = receipt_values.get("s4-authorized-operation-plan.json", {})
    s2 = asset_validation.get("s2_receipt", {})
    if not isinstance(s2, dict):
        s2 = {}
    actual_assets = (
        [{"name": name, **assets[name]} for name in sorted(assets)]
        if set(assets) == set(continuation_asset_names(version))
        else []
    )
    s2_verdict = release_flow.validate_s2_receipt(
        s2,
        source_commit=commit,
        source_tree=str(value.get("source_tree", "")),
    )
    if not s2_verdict.get("ok"):
        errors.extend(s2_verdict.get("errors", []))
    if s2.get("assets") != actual_assets:
        errors.append(_version_error(version, "CONTINUATION_ASSET_BINDING"))
    if (
        value.get("project_size") != control.get("project_size")
        or value.get("asset_set_id") != s2.get("asset_set_id")
        or value.get("asset_set_digest") != s2.get("asset_set_digest")
        or value.get("s2_receipt_sha256") != s2.get("receipt_sha256")
        or value.get("authorization_receipt_sha256")
        != release_flow.canonical_sha256(authorization)
        or value.get("release_control_sha256")
        != control.get("release_control_sha256")
        or value.get("s2_build_invocation_count")
        != s2.get("build_invocation_count_for_asset_set")
        or value.get("s3_process_invocation_count")
        != s3.get("s3_process_invocation_count")
    ):
        errors.append(_version_error(version, "CONTINUATION_SUMMARY_BINDING"))
    errors.extend(
        _v249_checkpoint_receipt_binding_errors(
            receipt_values, control, version=version
        )
    )
    try:
        control_verdict = _validate_version_s4_control(
            version,
            commit,
            control,
            runtime_route_receipt_path=(
                receipt_root / "release-route-receipt.json"
            ),
            runtime_authorization_receipt_path=(
                receipt_root / "authorization.json"
            ),
        )
    except SkillReleaseError as exc:
        control_verdict = {
            "ok": False,
            "errors": [exc.receipt.get("error_code")],
        }
    if not control_verdict.get("ok"):
        errors.extend(control_verdict.get("errors", []))
    if not _valid_v249_s4_plan(
        plan,
        commit=commit,
        source_tree=str(value.get("source_tree", "")),
        control=control,
    ):
        errors.append(_version_error(version, "CONTINUATION_PLAN_CONTRACT"))
    errors = list(dict.fromkeys(str(error) for error in errors if error))
    return _base_receipt(
        command="verify-continuation-checkpoint",
        status=("continuation_checkpoint_passed" if not errors else "failed"),
        error_code=(None if not errors else errors[0]),
        version=version,
        source_commit=commit,
        source_tree=value.get("source_tree"),
        checkpoint_sha256=value.get("checkpoint_sha256"),
        claim_scope=value.get("claim_scope"),
        errors=errors,
        check_state="passed" if not errors else "failed",
        run_outcome="passed" if not errors else "failed",
        evidence_state="current" if not errors else "invalid",
    )


def validate_v250_continuation_checkpoint(
    version: str,
    commit: str,
    checkpoint: object,
    **kwargs: Any,
) -> dict[str, Any]:
    if version not in {"V2.50", "V2.52", "V2.6", "V2.62"}:
        return _base_receipt(
            command="verify-continuation-checkpoint",
            status="failed",
            error_code="E_V250_CONTINUATION_CHECKPOINT_IDENTITY",
            version=version,
            source_commit=commit,
            errors=["E_V250_CONTINUATION_CHECKPOINT_IDENTITY"],
            check_state="failed",
            run_outcome="failed",
            evidence_state="invalid",
        )
    return validate_v249_continuation_checkpoint(
        version, commit, checkpoint, **kwargs
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--version", default=ACTIVE_SIMPLE_VERSION)
    plan_parser.add_argument("--commit", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--version", default=ACTIVE_SIMPLE_VERSION)
    verify_parser.add_argument("--commit", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--version", default=ACTIVE_SIMPLE_VERSION)
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
    preflight_parser.add_argument("--version", default=ACTIVE_SIMPLE_VERSION)
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
    checkpoint_parser = subparsers.add_parser("checkpoint")
    checkpoint_parser.add_argument("--version", default=ACTIVE_SIMPLE_VERSION)
    checkpoint_parser.add_argument("--commit", required=True)
    checkpoint_parser.add_argument(
        "--project-size", choices=("small", "medium", "large"), required=True
    )
    checkpoint_parser.add_argument(
        "--job-status", choices=("success", "failure", "cancelled"), required=True
    )
    checkpoint_parser.add_argument("--workflow-run-id", required=True)
    checkpoint_parser.add_argument("--workflow-run-attempt", required=True)
    checkpoint_parser.add_argument(
        "--gate-outcome", action="append", default=[], required=True
    )
    checkpoint_parser.add_argument(
        "--receipt-source-root", type=Path, required=True
    )
    checkpoint_parser.add_argument("--release-root", type=Path, required=True)
    verify_checkpoint_parser = subparsers.add_parser("verify-checkpoint")
    verify_checkpoint_parser.add_argument("--version", default=ACTIVE_SIMPLE_VERSION)
    verify_checkpoint_parser.add_argument("--commit", required=True)
    verify_checkpoint_parser.add_argument(
        "--checkpoint-receipt", type=Path, required=True
    )
    verify_checkpoint_parser.add_argument("--receipt-root", type=Path, required=True)
    verify_checkpoint_parser.add_argument("--release-root", type=Path, required=True)
    verify_checkpoint_parser.add_argument(
        "--expected-workflow-run-id", required=True
    )
    verify_checkpoint_parser.add_argument(
        "--expected-workflow-run-attempt", required=True
    )
    for command_name in ("plan-s4", "publish"):
        publish_parser = subparsers.add_parser(command_name)
        publish_parser.add_argument("--version", default=ACTIVE_SIMPLE_VERSION)
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
        elif args.command == "checkpoint":
            gate_outcomes: dict[str, str] = {}
            for item in args.gate_outcome:
                phase, separator, outcome = item.partition("=")
                if not separator or not phase or not outcome or phase in gate_outcomes:
                    raise SkillReleaseError(
                        _version_error(
                            args.version, "CHECKPOINT_GATE_OUTCOME_SET"
                        ),
                        "checkpoint gate outcomes must be unique phase=outcome pairs",
                        command="checkpoint",
                    )
                gate_outcomes[phase] = outcome
            checkpoint_builder = (
                build_v250_continuation_checkpoint
                if args.version in {"V2.50", "V2.52", "V2.6", "V2.62"}
                else build_v249_continuation_checkpoint
            )
            receipt = checkpoint_builder(
                args.version,
                args.commit,
                project_size=args.project_size,
                job_status=args.job_status,
                workflow_run_id=args.workflow_run_id,
                workflow_run_attempt=args.workflow_run_attempt,
                gate_outcomes=gate_outcomes,
                receipt_source_root=args.receipt_source_root,
                release_root=args.release_root,
            )
        elif args.command == "verify-checkpoint":
            checkpoint_validator = (
                validate_v250_continuation_checkpoint
                if args.version in {"V2.50", "V2.52", "V2.6", "V2.62"}
                else validate_v249_continuation_checkpoint
            )
            receipt = checkpoint_validator(
                args.version,
                args.commit,
                _read_receipt_file(args.checkpoint_receipt),
                receipt_root=args.receipt_root,
                release_root=args.release_root,
                expected_workflow_run_id=args.expected_workflow_run_id,
                expected_workflow_run_attempt=args.expected_workflow_run_attempt,
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
        error_receipt = dict(exc.receipt)
        error_receipt["command"] = args.command
        print(json.dumps(error_receipt, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from exc
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if args.command in {"plan-s4", "publish"} and not receipt.get(
        "operation_plan_authorized"
    ):
        raise SystemExit(1)
    if args.command == "verify-checkpoint" and not receipt.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
