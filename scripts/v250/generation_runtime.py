"""Digest-bound loader for Goal Teams policy generations.

The loader has no write, network, subprocess, or environment side effects.
Current policy content is returned only after the activation manifest and
every declared member have been verified.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping


ACTIVE_PATH = "references/current/ACTIVE.json"
GENERATION_ID_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CURRENT_SCHEMA = "goal-teams-activation-manifest-v2.50"
BASELINE_SCHEMA = "goal-teams-baseline-activation-manifest-v2.50"
V250_CONTROL_SCHEMA_PATHS = (
    "schemas/v2.50/activation-manifest.schema.json",
    "schemas/v2.50/baseline-activation-manifest.schema.json",
    "schemas/v2.50/legacy-replay-manifest.schema.json",
    "schemas/v2.50/okf-document-graph.schema.json",
    "schemas/v2.50/project-route.schema.json",
    "schemas/v2.50/release-control.schema.json",
    "schemas/v2.50/rule-manifest.schema.json",
    "schemas/v2.50/runtime-transition-receipt.schema.json",
    "schemas/v2.50/test-gate.schema.json",
    "schemas/v2.50/user-output.schema.json",
)
V250_REQUIRED_CONTROL_PATHS = (
    "VERSION",
    "references/current/generations/V2.62/contracts/public-asset-map.json",
    "references/current/generations/V2.62/contracts/release-command-manifest.json",
    "references/current/generations/V2.62/contracts/release-route-manifest.json",
    "references/current/generations/V2.62/contracts/release-security-review-manifest.json",
    "references/okf-conformance-policy.json",
    "references/profiles/goal-teams-self-release-v2.62.md",
    "references/release-profiles/v2.62.json",
    "release/current/manifest.json",
    "schemas/release-engine-profile.schema.json",
    "scripts/check.sh",
    "scripts/checks/check-okf.py",
    "scripts/checks/check-package-manifest.py",
    "scripts/checks/check-v250.py",
    "scripts/checks/check.sh",
    "scripts/checks/run-v250-release-security-review.py",
    "scripts/checks/validate-v250-generation.py",
    "scripts/checks/validate-v250-test-gate.py",
    "scripts/checks/validate.py",
    "scripts/install-local.sh",
    "scripts/install/install-local.sh",
    "scripts/install/package-manifest.txt",
    "scripts/install/replay-package-manifest.txt",
    "scripts/release/build-release.py",
    "scripts/release/release_config.py",
    "scripts/release/skill_release.py",
    "scripts/release/validate-release.py",
    "scripts/v250/freeze_v248_snapshot.py",
    "scripts/v250/generate_subagents.py",
    "scripts/v250/generation_runtime.py",
    "scripts/v250/github_ssh.py",
    "scripts/v250/okf_conformance.py",
    "scripts/v250/okf_document_graph.py",
    "scripts/v250/output_contract.py",
    "scripts/v250/release_flow.py",
    "scripts/v250/replay_runner.py",
    "scripts/v250/repository_boundary.py",
    "scripts/v250/route_closure.py",
    "scripts/v250/runtime_host_adapter.py",
    "scripts/v250/runtime_transition.py",
    "scripts/v250/test_gate.py",
    "subagents/common-developer-instructions.txt",
    "subagents/goal-agent-product-manager.toml",
    "subagents/goal-api-integration-test-designer.toml",
    "subagents/goal-api-integration-test-runner.toml",
    "subagents/goal-backend.toml",
    "subagents/goal-completion-auditor.toml",
    "subagents/goal-docs.toml",
    "subagents/goal-e2e-test-designer.toml",
    "subagents/goal-e2e-test-runner.toml",
    "subagents/goal-frontend.toml",
    "subagents/goal-performance.toml",
    "subagents/goal-product.toml",
    "subagents/goal-qa.toml",
    "subagents/goal-refactor.toml",
    "subagents/goal-requirements-analyst.toml",
    "subagents/goal-reviewer.toml",
    "subagents/goal-security.toml",
    "subagents/goal-sqa.toml",
    "subagents/goal-unit-test-designer.toml",
    "subagents/goal-unit-test-runner.toml",
    "tests/v250/__init__.py",
    "tests/v250/test_generation.py",
    "tests/v250/test_github_ssh.py",
    "tests/v250/test_installer_route.py",
    "tests/v250/test_output_contract.py",
    "tests/v250/test_release_flow.py",
    "tests/v250/test_replay.py",
    "tests/v250/test_runtime_transition.py",
    "tests/v250/test_subagents.py",
    "tests/v250/test_test_gate.py",
    *V250_CONTROL_SCHEMA_PATHS,
)
V250_DYNAMIC_CONTROL_GLOBS = (
    "references/current/generations/V2.62/contracts/*.json",
    "schemas/v2.50/*.json",
    "scripts/checks/*v250*.py",
    "scripts/v250/*.py",
    "subagents/goal-*.toml",
    "tests/v250/test_*.py",
)


def _generation_required_control_paths(generation_id: str) -> set[str]:
    required = set(V250_REQUIRED_CONTROL_PATHS)
    if generation_id != "V2.63":
        return required
    required = {
        path.replace("V2.62", "V2.63")
        .replace("v2.62", "v2.63")
        .replace("v262", "v263")
        for path in required
    }
    # ``release/current/manifest.json`` is a mutable publication projection.
    # V2.63 binds immutable release command/profile controls instead; otherwise
    # an S4 projection update would invalidate an already-active generation.
    required.discard("release/current/manifest.json")
    return required


def _generation_dynamic_control_globs(generation_id: str) -> tuple[str, ...]:
    if generation_id != "V2.63":
        return V250_DYNAMIC_CONTROL_GLOBS
    return tuple(
        pattern.replace("V2.62", "V2.63")
        .replace("v2.62", "v2.63")
        .replace("v262", "v263")
        for pattern in V250_DYNAMIC_CONTROL_GLOBS
    )


class GenerationLoadError(RuntimeError):
    """Stable fail-closed generation loading error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_json_digest(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def resolve_repo_file(repo_root: Path | str, relative_path: str) -> Path:
    """Resolve a regular, non-symlink repository file without path escape."""

    root = Path(repo_root).resolve()
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise GenerationLoadError("E_V250_PATH_INVALID", "path must be a non-empty string")
    if "\\" in relative_path:
        raise GenerationLoadError("E_V250_PATH_INVALID", f"backslash is forbidden: {relative_path!r}")
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise GenerationLoadError("E_V250_PATH_ESCAPE", f"unsafe repository path: {relative_path!r}")

    candidate = root.joinpath(*pure.parts)
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise GenerationLoadError("E_V250_PATH_SYMLINK", f"symlink is forbidden: {relative_path}")
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise GenerationLoadError("E_V250_PATH_ESCAPE", f"path escapes repository: {relative_path}") from exc
    if not candidate.is_file():
        raise GenerationLoadError("E_V250_PATH_MISSING", f"missing regular file: {relative_path}")
    return candidate


def _read_json_file(repo_root: Path, relative_path: str) -> tuple[dict[str, Any], bytes]:
    path = resolve_repo_file(repo_root, relative_path)
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationLoadError("E_V250_JSON_INVALID", f"invalid JSON: {relative_path}") from exc
    if not isinstance(value, dict):
        raise GenerationLoadError("E_V250_JSON_SHAPE", f"JSON root must be an object: {relative_path}")
    return value, raw


def _validate_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise GenerationLoadError("E_V250_DIGEST_FORMAT", f"{field} must be a lowercase SHA-256")
    return value


def _activation_payload_digest(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_payload_sha256", None)
    return canonical_json_digest(payload)


def _iter_manifest_members(manifest: dict[str, Any]) -> Iterable[tuple[str, str, int | None]]:
    """Yield path/digest/size for both V2.62 and frozen baseline formats."""

    root_sets = manifest.get("root_sets")
    if isinstance(root_sets, dict):
        for root_name in ("bootstrap", "current", "execution", "schemas_and_validators"):
            entries = root_sets.get(root_name)
            if not isinstance(entries, list):
                raise GenerationLoadError("E_V250_ROOT_SET_INVALID", f"root_sets.{root_name} must be an array")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise GenerationLoadError("E_V250_MEMBER_INVALID", f"invalid member in {root_name}")
                yield entry.get("path"), entry.get("sha256"), entry.get("bytes")
        return

    for field in ("semantic_owner_paths", "execution_identity_paths"):
        entries = manifest.get(field, [])
        if not isinstance(entries, list):
            raise GenerationLoadError("E_V250_BASELINE_INVALID", f"{field} must be an array")
        for entry in entries:
            if not isinstance(entry, dict):
                raise GenerationLoadError("E_V250_BASELINE_INVALID", f"invalid member in {field}")
            yield entry.get("path"), entry.get("sha256"), entry.get("bytes")
    subagents = manifest.get("subagent_config_digests", {})
    if not isinstance(subagents, dict):
        raise GenerationLoadError("E_V250_BASELINE_INVALID", "subagent_config_digests must be an object")
    for path, digest in subagents.items():
        yield path, digest, None


def _verify_members(repo_root: Path, manifest: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    paths: list[str] = []
    digests: dict[str, str] = {}
    for relative_path, expected_digest, expected_bytes in _iter_manifest_members(manifest):
        if not isinstance(relative_path, str):
            raise GenerationLoadError("E_V250_MEMBER_INVALID", "member path must be a string")
        digest = _validate_digest(expected_digest, f"member digest for {relative_path}")
        if relative_path in digests:
            if digests[relative_path] != digest:
                raise GenerationLoadError("E_V250_MEMBER_COLLISION", f"conflicting digests for {relative_path}")
            continue
        path = resolve_repo_file(repo_root, relative_path)
        raw = path.read_bytes()
        actual = sha256_bytes(raw)
        if actual != digest:
            raise GenerationLoadError(
                "E_V250_MEMBER_DIGEST_MISMATCH",
                f"{relative_path}: expected {digest}, observed {actual}",
            )
        if expected_bytes is not None:
            if not isinstance(expected_bytes, int) or expected_bytes < 0 or len(raw) != expected_bytes:
                raise GenerationLoadError("E_V250_MEMBER_SIZE_MISMATCH", f"byte count mismatch for {relative_path}")
        paths.append(relative_path)
        digests[relative_path] = digest
    if not paths:
        raise GenerationLoadError("E_V250_GENERATION_EMPTY", "activation manifest declares no members")
    return paths, digests


def _validate_baseline_snapshot(manifest: dict[str, Any], member_paths: list[str]) -> None:
    snapshot_root = manifest.get("snapshot_root")
    if snapshot_root != "references/legacy-replay/generations/V2.48/snapshot":
        raise GenerationLoadError("E_V250_BASELINE_SNAPSHOT_ROOT", "V2.48 snapshot root differs")
    prefix = snapshot_root + "/"
    if any(not path.startswith(prefix) for path in member_paths):
        raise GenerationLoadError(
            "E_V250_BASELINE_SHARED_PATH",
            "baseline members must be isolated snapshot paths",
        )
    source_paths = manifest.get("source_paths")
    if (
        not isinstance(source_paths, dict)
        or set(source_paths) != set(member_paths)
        or not all(isinstance(value, str) and value for value in source_paths.values())
        or len(set(source_paths.values())) != len(source_paths)
    ):
        raise GenerationLoadError("E_V250_BASELINE_SOURCE_MAP", "baseline source map is incomplete")


def _load_v250_control_schemas(
    repo_root: Path,
    member_digests: dict[str, str],
    generation_id: str,
) -> dict[str, dict[str, Any]]:
    from scripts.v250.control_registry import is_control_asset_applicable

    required = _generation_required_control_paths(generation_id)
    for pattern in _generation_dynamic_control_globs(generation_id):
        for path in repo_root.glob(pattern):
            if path.is_file() and not path.is_symlink():
                relative_path = path.relative_to(repo_root).as_posix()
                if is_control_asset_applicable(
                    relative_path, generation_id=generation_id
                ):
                    required.add(relative_path)
    missing = sorted(required - set(member_digests))
    if missing:
        raise GenerationLoadError(
            "E_V250_CONTROL_ASSET_UNBOUND",
            "activation does not bind required Current control assets: " + ", ".join(missing),
        )
    schemas: dict[str, dict[str, Any]] = {}
    schema_paths = set(V250_CONTROL_SCHEMA_PATHS)
    schema_paths.update(
        path.relative_to(repo_root).as_posix()
        for path in repo_root.glob("schemas/v2.50/*.json")
        if path.is_file() and not path.is_symlink()
        and is_control_asset_applicable(
            path.relative_to(repo_root).as_posix(), generation_id=generation_id
        )
    )
    for relative_path in sorted(schema_paths):
        payload, _raw = _read_json_file(repo_root, relative_path)
        if payload.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise GenerationLoadError("E_V250_CONTROL_SCHEMA_INVALID", relative_path)
        schemas[relative_path] = payload
    route_properties = schemas["schemas/v2.50/project-route.schema.json"].get("properties")
    if not isinstance(route_properties, dict) or route_properties.get("s1_current") != {"type": "boolean"}:
        raise GenerationLoadError(
            "E_V250_PROJECT_ROUTE_SCHEMA_DRIFT",
            "project route schema must declare the checker-consumed s1_current fact",
        )
    return schemas


def _validate_v250_projection_digests(
    manifest: dict[str, Any],
    rule_manifest: dict[str, Any],
) -> None:
    owners = rule_manifest.get("owners")
    if not isinstance(owners, list):
        raise GenerationLoadError("E_V250_OWNER_SET_INVALID", "rule owners must be an array")
    owner_binding = sorted(
        (
            {"path": owner.get("path"), "sha256": owner.get("source_sha256")}
            for owner in owners
            if isinstance(owner, dict)
        ),
        key=lambda item: str(item["path"]),
    )
    if len(owner_binding) != len(owners) or canonical_json_digest(owner_binding) != manifest.get(
        "semantic_owner_set_digest"
    ):
        raise GenerationLoadError("E_V250_OWNER_SET_DRIFT", "semantic owner set digest differs")

    root_sets = manifest.get("root_sets", {})
    schema_entries = root_sets.get("schemas_and_validators", [])
    if canonical_json_digest(sorted(schema_entries, key=lambda item: item["path"])) != manifest.get(
        "schema_and_validator_digest"
    ):
        raise GenerationLoadError("E_V250_SCHEMA_SET_DRIFT", "schema and validator digest differs")

    current_entries = root_sets.get("current", [])
    generation_id = manifest.get("generation_id")
    contract_prefix = f"references/current/generations/{generation_id}/contracts/"
    contract_entries = sorted(
        (
            entry
            for entry in current_entries
            if isinstance(entry, dict)
            and str(entry.get("path", "")).startswith(contract_prefix)
            and str(entry.get("path", "")).endswith(".json")
        ),
        key=lambda item: item["path"],
    )
    if canonical_json_digest(contract_entries) != manifest.get(
        "fixture_and_completion_contract_digest"
    ):
        raise GenerationLoadError(
            "E_V250_COMPLETION_CONTRACT_SET_DRIFT", "Current control-contract digest differs"
        )

    writers = manifest.get("projection_writer_allowlist")
    if not isinstance(writers, list) or canonical_json_digest(sorted(writers)) != manifest.get(
        "projection_writer_allowlist_digest"
    ):
        raise GenerationLoadError("E_V250_PROJECTION_WRITER_DRIFT", "projection writer digest differs")
    if manifest.get("repository_control_exclusions") != [
        {
            "path_prefix": ".github/workflows/",
            "reason": "repository_only_not_installable_runtime_asset",
            "binding": "exact_source_tree_plus_release_profile_and_command_contract",
        }
    ]:
        raise GenerationLoadError(
            "E_V250_REPOSITORY_CONTROL_SCOPE",
            "repository-only workflow exclusion must remain explicit",
        )


def _load_v250_projection(
    repo_root: Path,
    manifest: dict[str, Any],
    member_digests: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    rule_path = manifest.get("rule_manifest_path")
    prompt_path = manifest.get("prompt_manifest_path")
    if not isinstance(rule_path, str) or not isinstance(prompt_path, str):
        raise GenerationLoadError("E_V250_PROJECTION_PATH", "rule and prompt manifest paths are required")
    if rule_path not in member_digests or prompt_path not in member_digests:
        raise GenerationLoadError("E_V250_PROJECTION_UNBOUND", "rule or prompt manifest is not activation-bound")
    rule_manifest, rule_raw = _read_json_file(repo_root, rule_path)
    prompt_manifest, prompt_raw = _read_json_file(repo_root, prompt_path)
    if rule_manifest.get("generation_id") != manifest.get("generation_id"):
        raise GenerationLoadError("E_V250_RULE_GENERATION_MISMATCH", "rule manifest generation differs")
    if prompt_manifest.get("generation_id") != manifest.get("generation_id"):
        raise GenerationLoadError("E_V250_PROMPT_GENERATION_MISMATCH", "prompt manifest generation differs")
    rule_digest = sha256_bytes(rule_raw)
    prompt_digest = sha256_bytes(prompt_raw)
    if rule_digest != manifest.get("rule_index_digest"):
        raise GenerationLoadError("E_V250_RULE_INDEX_DRIFT", "rule index digest differs from activation manifest")
    if prompt_digest != manifest.get("prompt_plan_digest"):
        raise GenerationLoadError("E_V250_PROMPT_PLAN_DRIFT", "prompt plan digest differs from activation manifest")
    return rule_manifest, prompt_manifest, rule_digest, prompt_digest


def _load_generation_impl(
    repo_root: Path | str,
    generation_id: str | None = None,
    *,
    candidate_manifest_path: str | None = None,
    candidate_expected_digest: str | None = None,
    explicit_selection_state: str | None = None,
) -> dict[str, Any]:
    """Load a generation after verifying pointer/payload and all members."""

    root = Path(repo_root).resolve()
    candidate_bound = (
        candidate_manifest_path is not None or candidate_expected_digest is not None
    )
    if candidate_bound:
        if candidate_manifest_path is None or candidate_expected_digest is None:
            raise GenerationLoadError(
                "E_V250_CANDIDATE_BINDING",
                "candidate manifest path and expected digest are both required",
            )
        if not isinstance(generation_id, str) or not GENERATION_ID_RE.fullmatch(
            generation_id
        ):
            raise GenerationLoadError(
                "E_V250_GENERATION_ID", f"invalid generation id: {generation_id!r}"
            )
        active_generation = None
        active_manifest_path = None
        active_manifest_digest = None
        active_raw: bytes | None = None
        requested = generation_id
        manifest_path = candidate_manifest_path
        pointer_bound = False
        if explicit_selection_state not in {"inactive_candidate", "active"}:
            raise GenerationLoadError(
                "E_V250_EXPLICIT_SELECTION_STATE",
                "explicit selection must bind inactive_candidate or active",
            )
        selection_mode = (
            "candidate_expected_digest"
            if explicit_selection_state == "inactive_candidate"
            else "prepared_active_expected_digest"
        )
    else:
        active, active_raw = _read_json_file(root, ACTIVE_PATH)
        active_generation = active.get("generation_id")
        active_manifest_path = active.get("activation_manifest")
        active_manifest_digest = active.get("activation_manifest_sha256")

        if generation_id is None:
            requested = active_generation
            manifest_path = active_manifest_path
            pointer_bound = True
            selection_mode = "active_pointer"
        else:
            requested = generation_id
            if not isinstance(requested, str) or not GENERATION_ID_RE.fullmatch(
                requested
            ):
                raise GenerationLoadError(
                    "E_V250_GENERATION_ID",
                    f"invalid generation id: {requested!r}",
                )
            if requested == active_generation:
                manifest_path = active_manifest_path
                pointer_bound = True
                selection_mode = "active_pointer"
            else:
                manifest_path = (
                    f"references/current/generations/{requested}/activation-manifest.json"
                )
                pointer_bound = False
                selection_mode = "active_bound_rollback"

    if not isinstance(requested, str) or not GENERATION_ID_RE.fullmatch(requested):
        raise GenerationLoadError("E_V250_ACTIVE_INVALID", "ACTIVE.json has an invalid generation_id")
    if not isinstance(manifest_path, str):
        raise GenerationLoadError("E_V250_ACTIVE_INVALID", "activation manifest path is missing")

    rollback_bound_digest: str | None = None
    if not pointer_bound and not candidate_bound:
        if not isinstance(active_manifest_path, str):
            raise GenerationLoadError("E_V250_ACTIVE_INVALID", "active manifest path is missing")
        active_manifest, active_manifest_raw = _read_json_file(root, active_manifest_path)
        active_expected = _validate_digest(
            active_manifest_digest, "ACTIVE activation_manifest_sha256"
        )
        if sha256_bytes(active_manifest_raw) != active_expected:
            raise GenerationLoadError("E_V250_ACTIVE_DIGEST_MISMATCH", "active generation digest differs")
        rollback = active_manifest.get("rollback")
        if not isinstance(rollback, dict) or rollback.get("window_status") != "open":
            raise GenerationLoadError("E_V250_GENERATION_NOT_REACHABLE", "rollback window is not open")
        if rollback.get("activation_manifest_path") != manifest_path:
            raise GenerationLoadError(
                "E_V250_GENERATION_NOT_REACHABLE", "generation is not the ACTIVE-bound rollback target"
            )
        rollback_bound_digest = _validate_digest(
            rollback.get("activation_manifest_sha256"), "rollback activation_manifest_sha256"
        )

    manifest, manifest_raw = _read_json_file(root, manifest_path)
    manifest_digest = sha256_bytes(manifest_raw)
    if manifest.get("generation_id") != requested:
        raise GenerationLoadError("E_V250_ACTIVATION_GENERATION_MISMATCH", "activation generation differs from selection")

    observed_generation_state = manifest.get("generation_state")
    if pointer_bound and observed_generation_state != "active":
        raise GenerationLoadError(
            "E_V250_ACTIVE_STATE",
            "ACTIVE may point only to an activation manifest with generation_state=active",
        )
    if candidate_bound and observed_generation_state != explicit_selection_state:
        code = (
            "E_V250_CANDIDATE_STATE"
            if explicit_selection_state == "inactive_candidate"
            else "E_V250_PREPARED_STATE"
        )
        raise GenerationLoadError(
            code,
            f"explicit selection requires generation_state={explicit_selection_state}",
        )
    if not pointer_bound and not candidate_bound and observed_generation_state != "active":
        raise GenerationLoadError(
            "E_V250_ROLLBACK_STATE",
            "ACTIVE-bound rollback target must have generation_state=active",
        )

    if pointer_bound:
        expected = _validate_digest(active_manifest_digest, "ACTIVE activation_manifest_sha256")
        if manifest_digest != expected:
            raise GenerationLoadError(
                "E_V250_ACTIVE_DIGEST_MISMATCH",
                f"expected {expected}, observed {manifest_digest}",
            )
        activation_digest_verified = True
    elif candidate_bound:
        expected = _validate_digest(
            candidate_expected_digest, "expected_activation_sha256"
        )
        if manifest_digest != expected:
            raise GenerationLoadError(
                "E_V250_CANDIDATE_DIGEST_MISMATCH",
                f"expected {expected}, observed {manifest_digest}",
            )
        activation_digest_verified = True
    else:
        if manifest_digest != rollback_bound_digest:
            raise GenerationLoadError(
                "E_V250_ROLLBACK_DIGEST_MISMATCH",
                f"expected {rollback_bound_digest}, observed {manifest_digest}",
            )
        activation_digest_verified = True

    expected_payload = _validate_digest(
        manifest.get("manifest_payload_sha256"), "manifest_payload_sha256"
    )
    observed_payload = _activation_payload_digest(manifest)
    if observed_payload != expected_payload:
        raise GenerationLoadError(
            "E_V250_ACTIVATION_PAYLOAD_MISMATCH",
            f"expected {expected_payload}, observed {observed_payload}",
        )

    member_paths, member_digests = _verify_members(root, manifest)

    schema_version = manifest.get("schema_version")
    if schema_version == CURRENT_SCHEMA:
        rule_manifest, prompt_manifest, rule_digest, prompt_digest = _load_v250_projection(
            root, manifest, member_digests
        )
        expected_prompt_state = (
            "active_current"
            if manifest.get("generation_state") == "active"
            else "inactive_candidate"
        )
        if prompt_manifest.get("manifest_state") != expected_prompt_state:
            raise GenerationLoadError(
                "E_V250_PROMPT_STATE",
                "prompt manifest state differs from activation generation state",
            )
        control_schemas = _load_v250_control_schemas(
            root, member_digests, requested
        )
        _validate_v250_projection_digests(manifest, rule_manifest)
        current_allowlist = manifest.get("current_default_allowlist")
        if not isinstance(current_allowlist, list) or not all(isinstance(path, str) for path in current_allowlist):
            raise GenerationLoadError("E_V250_CURRENT_ALLOWLIST", "current_default_allowlist must be an array")
        if len(current_allowlist) != len(set(current_allowlist)):
            raise GenerationLoadError("E_V250_CURRENT_ALLOWLIST", "current_default_allowlist contains duplicates")
        required_allowlist = set(member_paths) | {ACTIVE_PATH, manifest_path}
        missing_allowlist = sorted(required_allowlist - set(current_allowlist))
        if missing_allowlist:
            raise GenerationLoadError(
                "E_V250_CURRENT_ALLOWLIST_INCOMPLETE",
                "Current allowlist omits activation-bound assets: " + ", ".join(missing_allowlist),
            )
        observed_allowlist_digest = canonical_json_digest(sorted(current_allowlist))
        if observed_allowlist_digest != manifest.get("current_default_allowlist_digest"):
            raise GenerationLoadError("E_V250_CURRENT_ALLOWLIST_DRIFT", "current allowlist digest differs")

        legacy = manifest.get("legacy_classification", {})
        if not isinstance(legacy, dict):
            raise GenerationLoadError("E_V250_LEGACY_CLASSIFICATION", "legacy_classification must be an object")
        prefixes = legacy.get("path_prefixes", [])
        exact = legacy.get("exact_paths", [])
        if not isinstance(prefixes, list) or not isinstance(exact, list):
            raise GenerationLoadError("E_V250_LEGACY_CLASSIFICATION", "legacy path sets must be arrays")
        legacy_intersection = sorted(
            path for path in current_allowlist
            if path in set(exact) or any(path.startswith(prefix) for prefix in prefixes)
        )
        if legacy_intersection:
            raise GenerationLoadError(
                "E_V250_CURRENT_REPLAY_INTERSECTION",
                "current allowlist intersects legacy classification: " + ", ".join(legacy_intersection),
            )
    elif schema_version == BASELINE_SCHEMA:
        _validate_baseline_snapshot(manifest, member_paths)
        rule_manifest = {}
        prompt_manifest = {}
        rule_digest = ""
        prompt_digest = ""
        for path in member_paths:
            if path.endswith("prompt-cache-manifest.json"):
                prompt_manifest, prompt_raw = _read_json_file(root, path)
                prompt_digest = sha256_bytes(prompt_raw)
                break
        current_allowlist = list(member_paths)
        prefixes = []
        exact = []
        control_schemas = {}
    else:
        raise GenerationLoadError("E_V250_ACTIVATION_SCHEMA", "unsupported activation schema")

    return {
        "generation_id": requested,
        "active_generation_id": active_generation,
        "selected_via_active_pointer": pointer_bound,
        "selection_mode": selection_mode,
        "active_sha256": sha256_bytes(active_raw) if active_raw is not None else None,
        "activation_manifest_path": manifest_path,
        "activation_manifest_sha256": manifest_digest,
        "activation_digest_verified": activation_digest_verified,
        "member_digests_verified": True,
        "activation_manifest": manifest,
        "rule_manifest": rule_manifest,
        "rule_manifest_sha256": rule_digest,
        "prompt_manifest": prompt_manifest,
        "prompt_manifest_sha256": prompt_digest,
        "current_default_allowlist": list(current_allowlist),
        "optional_replay_allowlist_digest": manifest.get("optional_replay_allowlist_digest"),
        "legacy_path_prefixes": list(prefixes),
        "legacy_exact_paths": list(exact),
        "member_paths": member_paths,
        "member_digests": member_digests,
        "control_schemas": control_schemas,
    }


def load_generation(
    repo_root: Path | str, generation_id: str | None = None
) -> dict[str, Any]:
    """Load only ACTIVE or its explicitly ACTIVE-bound rollback target."""

    return _load_generation_impl(repo_root, generation_id)


def load_candidate_generation(
    repo_root: Path | str,
    *,
    generation_id: str,
    activation_manifest_path: str,
    expected_activation_sha256: str,
) -> dict[str, Any]:
    """Load a non-Current candidate bound by a caller-supplied trusted digest.

    Candidate loading never reads ACTIVE and therefore cannot be reached by
    passing a candidate generation id to :func:`load_generation`.
    """

    return _load_generation_impl(
        repo_root,
        generation_id,
        candidate_manifest_path=activation_manifest_path,
        candidate_expected_digest=expected_activation_sha256,
        explicit_selection_state="inactive_candidate",
    )


def load_prepared_generation(
    repo_root: Path | str,
    *,
    generation_id: str,
    activation_manifest_path: str,
    expected_activation_sha256: str,
) -> dict[str, Any]:
    """Load a prepared active manifest without consulting ``ACTIVE.json``.

    This is the only pre-cutover validation path for a manifest whose
    ``generation_state`` is already ``active``.  The caller must supply the
    trusted raw-file digest that the subsequent ACTIVE pointer CAS will bind.
    """

    return _load_generation_impl(
        repo_root,
        generation_id,
        candidate_manifest_path=activation_manifest_path,
        candidate_expected_digest=expected_activation_sha256,
        explicit_selection_state="active",
    )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class GenerationSnapshot:
    """Immutable session identity derived from one ACTIVE initialization."""

    session_id: str
    selected_root_realpath: str
    source_commit: str | None
    source_tree: str | None
    active_sha256: str
    activation_manifest_sha256: str
    rule_manifest_sha256: str
    prompt_manifest_sha256: str
    generation_id: str
    member_digests: tuple[tuple[str, str], ...]
    captured_at: str
    snapshot_sha256: str


_GENERATION_RUNTIME_SESSION_ISSUER = object()


class GenerationRuntimeSession:
    """Read-once ACTIVE session with explicit invalidation events."""

    def __init__(
        self,
        *,
        snapshot: GenerationSnapshot,
        generation: Mapping[str, Any],
        _issuer: object,
    ) -> None:
        if _issuer is not _GENERATION_RUNTIME_SESSION_ISSUER:
            raise GenerationLoadError(
                "E_V250_SESSION_PROVENANCE",
                "runtime sessions can only be created by the generation loader",
            )
        self._snapshot = snapshot
        self._generation = generation
        self._issuer = _issuer
        self._invalid_reason: str | None = None

    @classmethod
    def initialize(
        cls,
        repo_root: Path | str,
        *,
        session_id: str,
        source_commit: str | None = None,
        source_tree: str | None = None,
        captured_at: str | None = None,
    ) -> "GenerationRuntimeSession":
        if not isinstance(session_id, str) or not session_id:
            raise GenerationLoadError(
                "E_V250_SESSION_ID", "session_id must be a non-empty string"
            )
        generation = load_generation(repo_root)
        active_sha256 = generation.get("active_sha256")
        if not isinstance(active_sha256, str):
            raise GenerationLoadError(
                "E_V250_ACTIVE_INVALID", "ACTIVE content digest is unavailable"
            )
        timestamp = captured_at or datetime.now(timezone.utc).isoformat()
        member_digests = tuple(sorted(generation["member_digests"].items()))
        payload = {
            "session_id": session_id,
            "selected_root_realpath": Path(repo_root).resolve().as_posix(),
            "source_commit": source_commit,
            "source_tree": source_tree,
            "active_sha256": active_sha256,
            "activation_manifest_sha256": generation[
                "activation_manifest_sha256"
            ],
            "rule_manifest_sha256": generation["rule_manifest_sha256"],
            "prompt_manifest_sha256": generation["prompt_manifest_sha256"],
            "generation_id": generation["generation_id"],
            "member_digests": member_digests,
            "captured_at": timestamp,
        }
        snapshot = GenerationSnapshot(
            **payload,
            snapshot_sha256=canonical_json_digest(payload),
        )
        return cls(
            snapshot=snapshot,
            generation=_deep_freeze(generation),
            _issuer=_GENERATION_RUNTIME_SESSION_ISSUER,
        )

    def _require_current(self) -> None:
        if self._invalid_reason is not None:
            raise GenerationLoadError(
                "E_ACTIVE_CHANGED_RESTART_REQUIRED",
                "generation snapshot was invalidated; start a new session",
            )

    @property
    def snapshot(self) -> GenerationSnapshot:
        self._require_current()
        return self._snapshot

    @property
    def generation(self) -> Mapping[str, Any]:
        self._require_current()
        return self._generation

    def notify_active_change(self, observed_active_sha256: str) -> None:
        observed = _validate_digest(observed_active_sha256, "observed_active_sha256")
        if observed != self._snapshot.active_sha256:
            self._invalid_reason = "active_content_changed"

    def invalidate(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason:
            raise GenerationLoadError(
                "E_V250_SESSION_INVALIDATION", "invalidation reason is required"
            )
        self._invalid_reason = reason


def validate_generation_runtime_session(
    session: GenerationRuntimeSession,
) -> GenerationSnapshot:
    """Return a snapshot only for a live loader-issued runtime session."""

    if (
        not isinstance(session, GenerationRuntimeSession)
        or getattr(session, "_issuer", None) is not _GENERATION_RUNTIME_SESSION_ISSUER
    ):
        raise GenerationLoadError(
            "E_V250_SESSION_PROVENANCE",
            "trusted runtime requires a loader-issued generation session",
        )
    session._require_current()
    snapshot = session._snapshot
    generation = session._generation
    payload = {
        "session_id": snapshot.session_id,
        "selected_root_realpath": snapshot.selected_root_realpath,
        "source_commit": snapshot.source_commit,
        "source_tree": snapshot.source_tree,
        "active_sha256": snapshot.active_sha256,
        "activation_manifest_sha256": snapshot.activation_manifest_sha256,
        "rule_manifest_sha256": snapshot.rule_manifest_sha256,
        "prompt_manifest_sha256": snapshot.prompt_manifest_sha256,
        "generation_id": snapshot.generation_id,
        "member_digests": snapshot.member_digests,
        "captured_at": snapshot.captured_at,
    }
    if snapshot.snapshot_sha256 != canonical_json_digest(payload):
        raise GenerationLoadError(
            "E_V250_SESSION_PROVENANCE", "generation snapshot digest differs"
        )
    expected_bindings = {
        "active_sha256": generation.get("active_sha256"),
        "activation_manifest_sha256": generation.get(
            "activation_manifest_sha256"
        ),
        "rule_manifest_sha256": generation.get("rule_manifest_sha256"),
        "prompt_manifest_sha256": generation.get("prompt_manifest_sha256"),
        "generation_id": generation.get("generation_id"),
        "member_digests": tuple(sorted(generation.get("member_digests", {}).items())),
    }
    observed_bindings = {
        "active_sha256": snapshot.active_sha256,
        "activation_manifest_sha256": snapshot.activation_manifest_sha256,
        "rule_manifest_sha256": snapshot.rule_manifest_sha256,
        "prompt_manifest_sha256": snapshot.prompt_manifest_sha256,
        "generation_id": snapshot.generation_id,
        "member_digests": snapshot.member_digests,
    }
    if observed_bindings != expected_bindings:
        raise GenerationLoadError(
            "E_V250_SESSION_PROVENANCE",
            "generation snapshot differs from loader state",
        )
    return snapshot


__all__ = [
    "ACTIVE_PATH",
    "BASELINE_SCHEMA",
    "CURRENT_SCHEMA",
    "GenerationRuntimeSession",
    "GenerationSnapshot",
    "GenerationLoadError",
    "V250_CONTROL_SCHEMA_PATHS",
    "V250_DYNAMIC_CONTROL_GLOBS",
    "V250_REQUIRED_CONTROL_PATHS",
    "canonical_json_bytes",
    "canonical_json_digest",
    "load_candidate_generation",
    "load_generation",
    "load_prepared_generation",
    "resolve_repo_file",
    "sha256_bytes",
    "validate_generation_runtime_session",
]
