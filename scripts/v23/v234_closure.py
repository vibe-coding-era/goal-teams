#!/usr/bin/env python3
"""Safe builders for Goal Teams V2.34 recovery and completion artifacts.

The V2.34 runtime deliberately consumes immutable JSON facts instead of
caller-supplied booleans.  This companion module closes the producer side of
that contract.  It only creates private, append-only snapshots below the
version state root; reset application and public delivery remain separate
commands with their own gates.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


CLOSURE_SCHEMA = "goal-teams-v2.34-closure-snapshot-v1"
_STATE_FILES = ("feature_list.json", "progress.md", "contract.md", "log.md")
_PHASES = ("gather", "reason", "act", "verify", "repeat")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_file(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def _load_json(path: Path) -> dict[str, Any]:
    if not _regular_file(path):
        raise ValueError("regular JSON file required")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _load_json_array(path: Path) -> list[Any]:
    if not _regular_file(path):
        raise ValueError("regular JSON file required")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("JSON array required")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not _regular_file(path):
        raise ValueError("regular JSONL file required")
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("JSONL object required")
        rows.append(value)
    if not rows:
        raise ValueError("non-empty JSONL required")
    return rows


def _error(code: str, **values: Any) -> dict[str, Any]:
    return {"ok": False, "error_code": code, **values}


def _safe_private_destination(state_root: Path, output_dir: Path) -> Path:
    if not state_root.is_dir() or state_root.is_symlink():
        raise ValueError("invalid state root")
    root = state_root.absolute().resolve()
    # macOS commonly exposes ``/var`` through ``/private/var``.  Resolve both
    # sides before containment checks so a legitimate temporary state root is
    # not mistaken for an escape, while still rejecting symlink traversal.
    target = output_dir.absolute().resolve(strict=False)
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("snapshot must remain below state root") from exc
    if (
        len(relative.parts) < 2
        or relative.parts[0] != ".goalteams-state"
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("snapshot must be private")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            metadata = os.lstat(current)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("unsafe snapshot ancestor")
        else:
            current.mkdir(mode=0o700)
    if target.exists() or target.is_symlink():
        raise FileExistsError("snapshot already exists")
    return target


def _persist_snapshot(
    state_root: Path, output_dir: Path, *, snapshot_type: str,
    files: dict[str, Any], metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = _safe_private_destination(state_root, output_dir)
    temp = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        records: list[dict[str, Any]] = []
        for name, value in sorted(files.items()):
            if PurePosixPath(name).name != name or name == "manifest.json":
                raise ValueError("unsafe snapshot filename")
            data = (
                value if isinstance(value, bytes)
                else json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            )
            path = temp / name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            records.append({"path": name, "sha256": _digest_bytes(data), "size": len(data)})
        manifest = {
            "schema_version": CLOSURE_SCHEMA,
            "snapshot_type": snapshot_type,
            "files": records,
            **(metadata or {}),
        }
        manifest["snapshot_sha256"] = _digest_bytes(_canonical_bytes(manifest))
        manifest_data = json.dumps(
            manifest, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8") + b"\n"
        descriptor = os.open(
            temp / "manifest.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(manifest_data)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(temp, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.replace(temp, target)
        parent_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return {
            "ok": True,
            "error_code": None,
            "snapshot_dir": str(target),
            "snapshot_sha256": manifest["snapshot_sha256"],
            "files": records,
        }
    except Exception:
        if temp.is_dir() and not temp.is_symlink():
            for child in temp.iterdir():
                child.unlink()
            temp.rmdir()
        raise


def _checkpoint_with_source(checkpoint_path: Path) -> tuple[dict[str, Any], bytes]:
    if not _regular_file(checkpoint_path):
        raise ValueError("regular checkpoint required")
    raw = checkpoint_path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("checkpoint object required")
    value["_source_sha256"] = _digest_bytes(raw)
    revision = value.get("ledger_revision")
    value.setdefault("revision", revision)
    seen = value.get("seen_events")
    if isinstance(seen, list) and seen:
        value.setdefault("last_event_id", seen[-1])
    return value, raw


def snapshot_ledger_binding(
    runtime: Any, state_root: Path | str, *, ledger_path: Path | str,
    checkpoint_path: Path | str, output_dir: Path | str,
) -> dict[str, Any]:
    """Derive the exact state-init binding from replayable ledger files."""
    try:
        events = _load_jsonl(Path(ledger_path))
        checkpoint, _ = _checkpoint_with_source(Path(checkpoint_path))
        binding, errors = runtime._validate_ledger_checkpoint(events, checkpoint)
        if errors or binding is None:
            return _error("E_V234_CLOSURE_LEDGER", errors=errors)
        persisted = _persist_snapshot(
            Path(state_root), Path(output_dir), snapshot_type="ledger_binding",
            files={"ledger-binding.json": binding},
            metadata={"ledger_revision": binding["revision"]},
        )
        return {**persisted, "ledger_binding": binding}
    except FileExistsError:
        return _error("E_V234_CLOSURE_CONFLICT")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error("E_V234_CLOSURE_LEDGER", errors=[type(exc).__name__])


def snapshot_legacy_adoption(
    state_root: Path | str, *, output_dir: Path | str,
) -> dict[str, Any]:
    """Hash the exact four legacy files without adopting or rewriting them."""
    root = Path(state_root)
    try:
        records: list[dict[str, Any]] = []
        for name in sorted(_STATE_FILES):
            path = root / name
            if not _regular_file(path):
                raise ValueError("legacy file is not regular")
            data = path.read_bytes()
            records.append({"path": name, "sha256": _digest_bytes(data), "size": len(data)})
        digest = _digest_bytes(_canonical_bytes(records))
        adoption = {
            "schema_version": "goal-teams-v2.34-legacy-adoption-v1",
            "legacy_digest": digest,
            "files": records,
            "mutation_count": 0,
        }
        persisted = _persist_snapshot(
            root, Path(output_dir), snapshot_type="legacy_adoption",
            files={"legacy-adoption.json": adoption},
            metadata={"legacy_digest": digest},
        )
        return {**persisted, "legacy_digest": digest, "records": records}
    except FileExistsError:
        return _error("E_V234_CLOSURE_CONFLICT")
    except (OSError, ValueError) as exc:
        return _error("E_V234_CLOSURE_LEGACY", errors=[type(exc).__name__])


def snapshot_reset_plan(
    runtime: Any, state_root: Path | str, *, repo_root: Path | str,
    candidate_id: str, authorization_path: Path | str,
    identity_registry_path: Path | str, ledger_path: Path | str,
    output_dir: Path | str, artifact_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and persist reset authorization plus a no-mutation plan."""
    root = Path(state_root)
    try:
        authorization = _load_json(Path(authorization_path))
        identities = _load_json(Path(identity_registry_path))
        events = _load_jsonl(Path(ledger_path))
        bundle = runtime.load_state_bundle(root)
        result = runtime.plan_controlled_reset(
            bundle, candidate_id, authorization,
            repo_root=Path(repo_root), state_root=root,
            artifact_root=Path(artifact_root) if artifact_root is not None else None,
            identity_registry=identities, ledger_events=events,
            version_binding=version_binding,
        )
        if not result.get("ok") or result.get("mutation_count") != 0:
            return result
        plan = result["plan"]
        persisted = _persist_snapshot(
            root, Path(output_dir), snapshot_type="reset_plan",
            files={
                "reset-authorization.json": authorization,
                "reset-plan.json": plan,
            },
            metadata={
                "authorization_id": authorization.get("authorization_id"),
                "plan_sha256": plan.get("plan_sha256"),
                "mutation_count": 0,
            },
        )
        return {**persisted, "plan": plan, "mutation_count": 0}
    except FileExistsError:
        return _error("E_V234_CLOSURE_CONFLICT")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _error("E_V234_CLOSURE_RESET", errors=[type(exc).__name__])


def _relative_repo_file(repo: Path, value: Path | str) -> tuple[str, Path]:
    source = Path(value)
    if not source.is_absolute():
        source = repo / source
    if not _regular_file(source):
        raise ValueError("regular repository file required")
    real = source.resolve()
    relative = real.relative_to(repo.resolve()).as_posix()
    if not relative or relative.startswith("../"):
        raise ValueError("repository file escaped")
    return relative, real


def _completion_proof(
    runtime: Any, *, bundle: dict[str, Any], context: dict[str, Any],
    descriptors: list[dict[str, Any]], required_task_ids: list[str],
    evidence_ids: list[str], rebuilt_candidate_ref: str,
    rebuilt_candidate_path: Path, rebuilt_candidate_evidence_id: str,
    repository_check_evidence_id: str, prompt_lifecycle: list[Any],
    normalized_binding: dict[str, Any],
) -> dict[str, Any]:
    records = context["evidence_registry"]["records"]
    reset = bundle.get("reset", {})
    proof = {
        "schema_version": "goal-teams-v2.34-completion-proof-v1",
        "bundle_revision": bundle.get("bundle_revision"),
        "bundle_digest": bundle.get("bundle_digest"),
        "ledger_revision": context["checkpoint"].get("ledger_revision"),
        "contract_revision": bundle.get("contract", {}).get("contract_revision"),
        "required_task_ids": sorted(set(required_task_ids)),
        "evidence_ids": sorted(set(evidence_ids)),
        "review_id": context["review_record"].get("review_id"),
        "completion_audit_id": context["audit_record"].get("audit_id"),
        "reset": {
            key: reset.get(key)
            for key in ("reset_event_id", "receipt_sha256", "manifest_sha256", "evidence_id")
        },
        "rebuilt_candidate": {
            "artifact_ref": rebuilt_candidate_ref,
            "artifact_sha256": _digest_bytes(rebuilt_candidate_path.read_bytes()),
            "evidence_id": rebuilt_candidate_evidence_id,
        },
        "repository_check": {
            "evidence_id": repository_check_evidence_id,
            "artifact_sha256": records[repository_check_evidence_id].get("artifact_sha256"),
        },
        "quality_scores": copy.deepcopy(bundle.get("quality_scores")),
        "prompt_lifecycle": copy.deepcopy(prompt_lifecycle),
        "bottleneck": copy.deepcopy(bundle.get("bottleneck")),
        "version": normalized_binding["project_version"],
        "roadmap_sha256": _digest_bytes(Path(context["roadmap_path"]).read_bytes()),
        "worktree_guard_sha256": context["worktree_guard"].get("guard_sha256"),
        "archive_descriptor_sha256": _digest_bytes(_canonical_bytes(descriptors)),
    }
    if normalized_binding.get("explicit") is True:
        proof["release_version"] = normalized_binding["release_version"]
        proof["artifact_version"] = normalized_binding["artifact_version"]
        proof["version_binding_digest"] = normalized_binding["binding_digest"]
    proof["proof_digest"] = _digest_bytes(_canonical_bytes(proof))
    return proof


def build_completion_snapshot(
    runtime: Any, state_root: Path | str, *, repo_root: Path | str,
    ledger_path: Path | str, checkpoint_path: Path | str,
    evidence_registry_path: Path | str, identity_registry_path: Path | str,
    review_record_path: Path | str, audit_record_path: Path | str,
    roadmap_path: Path | str, rebuilt_candidate_path: Path | str,
    rebuilt_candidate_evidence_id: str, repository_check_evidence_id: str,
    required_task_ids: list[str], evidence_ids: list[str],
    public_sources: list[str], validator_run_id: str,
    baseline_commit: str | None, candidate_commit: str | None,
    candidate_snapshot_path: Path | str | None, protected_paths: list[str],
    output_dir: Path | str, prompt_lifecycle_path: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and gate all JSON inputs required by delivery.

    The function derives every digest from a regular source file and calls the
    runtime delivery gate before the snapshot directory becomes visible.
    """
    root = Path(state_root)
    repo = Path(repo_root).absolute().resolve()
    try:
        events = _load_jsonl(Path(ledger_path))
        checkpoint, _ = _checkpoint_with_source(Path(checkpoint_path))
        binding, ledger_errors = runtime._validate_ledger_checkpoint(events, checkpoint)
        if ledger_errors or binding is None:
            return _error("E_V234_CLOSURE_LEDGER", errors=ledger_errors)
        registry = _load_json(Path(evidence_registry_path))
        records, registry_error = runtime._validated_registry(registry, events, checkpoint)
        if registry_error or records is None:
            return _error("E_V234_CLOSURE_EVIDENCE", errors=[registry_error])
        identities = _load_json(Path(identity_registry_path))
        review = _load_json(Path(review_record_path))
        audit = _load_json(Path(audit_record_path))
        roadmap = Path(roadmap_path)
        if not _regular_file(roadmap):
            raise ValueError("regular roadmap required")
        candidate_ref, candidate = _relative_repo_file(repo, rebuilt_candidate_path)
        if not required_task_ids or not evidence_ids or not public_sources or not protected_paths:
            raise ValueError("non-empty closure selections required")
        if rebuilt_candidate_evidence_id not in records or repository_check_evidence_id not in records:
            return _error("E_V234_CLOSURE_EVIDENCE", errors=["missing selected evidence"])
        if any(item not in records for item in evidence_ids):
            return _error("E_V234_CLOSURE_EVIDENCE", errors=["unknown evidence id"])
        bundle = runtime.load_state_bundle(root)
        binding_result = runtime._binding_result(
            repo, version_binding, marker=bundle
        )
        if not binding_result.get("ok"):
            return binding_result
        normalized_binding = binding_result["binding"]
        contract_revision = bundle.get("contract", {}).get("contract_revision")
        descriptors: list[dict[str, Any]] = []
        seen_archive: set[str] = set()
        for index, source_value in enumerate(public_sources, 1):
            source_ref, source = _relative_repo_file(repo, source_value)
            archive_ref = source.name
            if archive_ref in seen_archive:
                raise ValueError("duplicate archive basename")
            seen_archive.add(archive_ref)
            descriptors.append(
                {
                    "source_artifact_id": (
                        f"ART-V235-PUBLIC-{index:03d}"
                        if normalized_binding.get("explicit") is True
                        else f"ART-V234-PUBLIC-{index:03d}"
                    ),
                    "source_ref": source_ref,
                    "archive_ref": archive_ref,
                    "publication_state": "completed",
                    "visibility": "public",
                    "artifact_version": normalized_binding["artifact_version"],
                    "validator_run_id": validator_run_id,
                    "contract_revision": contract_revision,
                    "classification": "public_completion_doc",
                    "accepted": True,
                    **(
                        {"version_binding_digest": normalized_binding["binding_digest"]}
                        if normalized_binding.get("explicit") is True else {}
                    ),
                }
            )
        guard = runtime.capture_worktree_guard(repo, protected_paths=protected_paths)
        if set(guard.get("protected", {})) != set(protected_paths):
            return _error("E_V234_CLOSURE_WORKTREE", errors=["unprotected path"])
        lifecycle = (
            _load_json_array(Path(prompt_lifecycle_path))
            if prompt_lifecycle_path is not None else []
        )
        context: dict[str, Any] = {
            "repo_root": str(repo),
            "ledger_events": events,
            "checkpoint": checkpoint,
            "evidence_registry": registry,
            "identity_registry": identities,
            "identity_path": str(Path(identity_registry_path).resolve()),
            "review_record": review,
            "review_path": str(Path(review_record_path).resolve()),
            "audit_record": audit,
            "audit_path": str(Path(audit_record_path).resolve()),
            "worktree_guard": guard,
            "roadmap_path": str(roadmap.resolve()),
        }
        candidate_snapshot: dict[str, Any] | None = None
        if candidate_snapshot_path is not None:
            if candidate_commit is not None:
                raise ValueError("publish sources are mutually exclusive")
            candidate_snapshot = _load_json(Path(candidate_snapshot_path))
            snapshot_check = runtime.validate_protected_candidate_snapshot(
                repo, candidate_snapshot, version_binding=normalized_binding,
            )
            if not snapshot_check.get("ok"):
                return _error(
                    "E_V234_CLOSURE_PUBLISH",
                    errors=snapshot_check.get("errors", [snapshot_check.get("error_code")]),
                )
            context["candidate_snapshot_receipt"] = candidate_snapshot
            context["candidate_snapshot_path"] = str(
                Path(candidate_snapshot_path).resolve()
            )
        elif (
            not isinstance(baseline_commit, str)
            or not baseline_commit
            or not isinstance(candidate_commit, str)
            or not candidate_commit
        ):
            return _error(
                "E_V234_CLOSURE_PUBLISH", errors=["commit pair or snapshot required"]
            )
        else:
            context["baseline_commit"] = baseline_commit
            context["candidate_commit"] = candidate_commit
        proof = _completion_proof(
            runtime,
            bundle=bundle,
            context=context,
            descriptors=descriptors,
            required_task_ids=required_task_ids,
            evidence_ids=evidence_ids,
            rebuilt_candidate_ref=candidate_ref,
            rebuilt_candidate_path=candidate,
            rebuilt_candidate_evidence_id=rebuilt_candidate_evidence_id,
            repository_check_evidence_id=repository_check_evidence_id,
            prompt_lifecycle=lifecycle,
            normalized_binding=normalized_binding,
        )
        if candidate_snapshot is not None:
            proof["candidate_snapshot_receipt_sha256"] = candidate_snapshot.get(
                "receipt_sha256"
            )
            proof["proof_digest"] = _digest_bytes(
                _canonical_bytes(
                    {key: value for key, value in proof.items() if key != "proof_digest"}
                )
            )
        completion = {
            "run_outcome_candidate": "achieved",
            "completion_audit": {
                "state": audit.get("state"),
                "validator_run_id": audit.get("auditor_run_id"),
                "ledger_revision": checkpoint.get("ledger_revision"),
                "sha256": _digest_bytes(Path(audit_record_path).read_bytes()),
            },
            "contract_revision": contract_revision,
        }
        if normalized_binding.get("explicit") is True:
            completion["release_version"] = normalized_binding["release_version"]
            completion["artifact_version"] = normalized_binding["artifact_version"]
            completion["version_binding_digest"] = normalized_binding["binding_digest"]
            context["version_binding"] = copy.deepcopy(normalized_binding)
            context["version_binding_digest"] = normalized_binding["binding_digest"]
        final_output = Path(output_dir).absolute().resolve(strict=False)
        validation_root = root / ".goalteams-state" / "closure-validation"
        validation_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, raw_proof_path = tempfile.mkstemp(
            prefix=".completion-proof.", suffix=".json", dir=validation_root
        )
        proof_validation_path = Path(raw_proof_path)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(
                    json.dumps(
                        proof, ensure_ascii=False, indent=2, sort_keys=True
                    ).encode("utf-8")
                    + b"\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
            context["completion_proof_path"] = str(proof_validation_path)
            gate = runtime.evaluate_delivery_gate(
                bundle, proof, descriptors, source_context=context,
                version_binding=normalized_binding,
            )
            eligibility = runtime.validate_archive_eligibility(
                descriptors, completion, repo_root=repo,
                completion_proof=proof, source_context=context,
                version_binding=normalized_binding,
            ) if gate.get("ok") else None
        finally:
            if proof_validation_path.exists() and not proof_validation_path.is_symlink():
                proof_validation_path.unlink()
        if not gate.get("ok"):
            return _error(
                "E_V234_CLOSURE_GATE",
                errors=gate.get("gaps", gate.get("errors", [gate.get("error_code")])),
                gate=gate,
            )
        if not isinstance(eligibility, dict) or not eligibility.get("ok"):
            return _error(
                "E_V234_CLOSURE_ARCHIVE",
                errors=(eligibility or {}).get(
                    "errors", (eligibility or {}).get("ineligible_artifact_ids", [])
                ),
            )
        context["completion_proof_path"] = str(final_output / "completion-proof.json")
        persisted = _persist_snapshot(
            root, final_output, snapshot_type="completion",
            files={
                "archive-descriptor.json": descriptors,
                "completion-proof.json": proof,
                "source-context.json": context,
                "completion.json": completion,
            },
            metadata={
                "bundle_revision": bundle.get("bundle_revision"),
                "bundle_digest": bundle.get("bundle_digest"),
                "ledger_revision": binding.get("revision"),
                "proof_digest": proof.get("proof_digest"),
                **(
                    {"version_binding_digest": normalized_binding["binding_digest"]}
                    if normalized_binding.get("explicit") is True else {}
                ),
            },
        )
        return {
            **persisted,
            "gate": gate,
            "eligible_artifact_ids": eligibility.get("artifact_ids", []),
            "proof_digest": proof["proof_digest"],
        }
    except FileExistsError:
        return _error("E_V234_CLOSURE_CONFLICT")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return _error("E_V234_CLOSURE_BUILD", errors=[type(exc).__name__])


def advance_loop(
    runtime: Any, state_root: Path | str, *, target_iteration: int,
    target_phase: str, actor_run_id: str, ledger_path: Path | str,
    checkpoint_path: Path | str, evidence_registry_path: Path | str,
    identity_registry_path: Path | str, output_dir: Path | str,
    repo_root: Path | str | None = None,
    version_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance normal LOOP edges transaction-by-transaction with fresh CAS.

    Iteration 9 still calls the runtime reset gate, and iteration 11 verify is
    the terminal target: delivery remains the only path to ``achieved``.
    """
    root = Path(state_root)
    receipts: list[dict[str, Any]] = []
    try:
        if (
            isinstance(target_iteration, bool)
            or not isinstance(target_iteration, int)
            or target_iteration < 1
            or target_iteration > 11
            or target_phase not in _PHASES
            or (target_iteration == 11 and _PHASES.index(target_phase) > _PHASES.index("verify"))
        ):
            return _error("E_V234_LOOP_TARGET")
        events = _load_jsonl(Path(ledger_path))
        checkpoint, _ = _checkpoint_with_source(Path(checkpoint_path))
        registry = _load_json(Path(evidence_registry_path))
        identities = _load_json(Path(identity_registry_path))
        start = runtime.validate_state_bundle(
            root, ledger_events=events, checkpoint=checkpoint,
            repo_root=repo_root, version_binding=version_binding,
        )
        if not start.get("ok") or start.get("state") != "valid":
            if str(start.get("error_code", "")).startswith("E_V235_VERSION_BINDING_"):
                return start
            return _error("E_V234_LOOP_STATE", validation=start)
        initial = start["marker"]["loop"]
        start_ordinal = (initial["iteration"] - 1) * len(_PHASES) + _PHASES.index(initial["phase"])
        target_ordinal = (target_iteration - 1) * len(_PHASES) + _PHASES.index(target_phase)
        if target_ordinal < start_ordinal:
            return _error("E_V234_LOOP_TARGET")
        while True:
            current = runtime.validate_state_bundle(
                root, ledger_events=events, checkpoint=checkpoint,
                repo_root=repo_root, version_binding=version_binding,
            )
            if not current.get("ok") or current.get("state") != "valid":
                if str(current.get("error_code", "")).startswith("E_V235_VERSION_BINDING_"):
                    return current
                result = _error("E_V234_LOOP_STATE", validation=current)
                break
            marker = current["marker"]
            loop = marker["loop"]
            if loop["iteration"] == target_iteration and loop["phase"] == target_phase:
                result = {
                    "ok": True,
                    "error_code": None,
                    "bundle_revision": marker["bundle_revision"],
                    "bundle_digest": marker["bundle_digest"],
                    "iteration": target_iteration,
                    "phase": target_phase,
                }
                break
            phase_index = _PHASES.index(loop["phase"])
            next_phase = _PHASES[(phase_index + 1) % len(_PHASES)]
            request: dict[str, Any] = {"to_phase": next_phase}
            if loop["phase"] == "repeat":
                request["iteration"] = loop["iteration"] + 1
            step = runtime.transition_state_bundle(
                root,
                expected_bundle_revision=marker["bundle_revision"],
                expected_bundle_digest=marker["bundle_digest"],
                actor_run_id=actor_run_id,
                transition=request,
                evidence_registry=registry,
                ledger_events=events,
                identity_registry=identities,
                checkpoint=checkpoint,
                repo_root=repo_root,
                version_binding=version_binding,
            )
            if str(step.get("error_code", "")).startswith("E_V235_VERSION_BINDING_"):
                return step
            receipt = {
                "from_iteration": loop["iteration"],
                "from_phase": loop["phase"],
                "to_phase": next_phase,
                "requested_iteration": request.get("iteration", loop["iteration"]),
                "ok": step.get("ok") is True,
                "error_code": step.get("error_code"),
                "bundle_revision": step.get("bundle_revision"),
                "bundle_digest": step.get("bundle_digest"),
                "transaction_id": step.get("transaction_id"),
            }
            receipts.append(receipt)
            if not step.get("ok"):
                result = step
                break
        workflow = {
            "schema_version": "goal-teams-v2.34-loop-advance-v1",
            "actor_run_id": actor_run_id,
            "start": {"iteration": initial["iteration"], "phase": initial["phase"]},
            "target": {"iteration": target_iteration, "phase": target_phase},
            "completed": result.get("ok") is True,
            "result_error_code": result.get("error_code"),
            "steps": receipts,
        }
        workflow["workflow_sha256"] = _digest_bytes(_canonical_bytes(workflow))
        persisted = _persist_snapshot(
            root, Path(output_dir), snapshot_type="loop_advance",
            files={"loop-advance.json": workflow},
            metadata={
                "workflow_sha256": workflow["workflow_sha256"],
                "step_count": len(receipts),
                "completed": workflow["completed"],
            },
        )
        return {
            **result,
            "snapshot_dir": persisted["snapshot_dir"],
            "snapshot_sha256": persisted["snapshot_sha256"],
            "step_count": len(receipts),
            "receipts": receipts,
        }
    except FileExistsError:
        return _error("E_V234_CLOSURE_CONFLICT")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return _error("E_V234_LOOP_ADVANCE", errors=[type(exc).__name__])
