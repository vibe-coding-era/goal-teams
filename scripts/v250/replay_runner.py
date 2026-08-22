"""Read-only, digest-only runner for explicitly selected historical replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.v250.generation_runtime import (
    GenerationLoadError,
    canonical_json_digest,
    load_generation,
    resolve_repo_file,
    sha256_bytes,
)


REPLAY_MANIFEST_PATH = "references/legacy-replay/manifest.json"
ALLOWED_STATUSES = ("historical_passed", "historical_failed", "replay_unavailable")


def load_replay_manifest(
    repo_root: Path | str,
    *,
    generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    path = resolve_repo_file(root, REPLAY_MANIFEST_PATH)
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationLoadError("E_V250_REPLAY_MANIFEST_JSON", "legacy replay manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise GenerationLoadError("E_V250_REPLAY_MANIFEST_SHAPE", "legacy replay manifest must be an object")
    generation = load_generation(root) if generation is None else generation
    activation = generation.get("activation_manifest", {})
    legacy = activation.get("legacy_classification", {})
    expected_raw_digest = legacy.get("replay_manifest_sha256")
    if not isinstance(expected_raw_digest, str) or sha256_bytes(raw) != expected_raw_digest:
        raise GenerationLoadError(
            "E_V250_REPLAY_ACTIVE_BINDING",
            "legacy replay manifest raw digest differs from the ACTIVE activation binding",
        )
    if manifest.get("schema_version") != "goal-teams-legacy-replay-manifest-v2.50":
        raise GenerationLoadError("E_V250_REPLAY_SCHEMA", "unsupported replay manifest schema")
    if manifest.get("network_policy") != "deny" or manifest.get("write_policy") != "deny_all":
        raise GenerationLoadError("E_V250_REPLAY_ISOLATION", "replay must deny network and writes")
    if manifest.get("output_status_enum") != list(ALLOWED_STATUSES):
        raise GenerationLoadError("E_V250_REPLAY_OUTPUT", "replay status enum differs")
    isolation = manifest.get("isolation_profile")
    if isolation != {
        "network": "deny",
        "filesystem_write": "deny",
        "subprocess": "deny",
        "environment_inheritance": "deny",
    }:
        raise GenerationLoadError("E_V250_REPLAY_ISOLATION", "replay isolation profile differs")
    allowlist = manifest.get("optional_replay_allowlist")
    if not isinstance(allowlist, list) or not all(isinstance(item, str) for item in allowlist):
        raise GenerationLoadError("E_V250_REPLAY_ALLOWLIST", "optional replay allowlist is invalid")
    if len(allowlist) != len(set(allowlist)):
        raise GenerationLoadError("E_V250_REPLAY_ALLOWLIST", "optional replay allowlist has duplicates")
    observed = canonical_json_digest(sorted(allowlist))
    if observed != manifest.get("optional_replay_allowlist_digest"):
        raise GenerationLoadError("E_V250_REPLAY_ALLOWLIST_DRIFT", "optional replay allowlist digest differs")
    if observed != generation.get("optional_replay_allowlist_digest"):
        raise GenerationLoadError(
            "E_V250_REPLAY_ALLOWLIST_ACTIVE_DRIFT",
            "optional replay allowlist digest differs from the ACTIVE activation binding",
        )
    replays = manifest.get("replays")
    if not isinstance(replays, list) or not replays:
        raise GenerationLoadError("E_V250_REPLAY_EMPTY", "replay manifest has no entries")
    versions = [entry.get("legacy_version") for entry in replays if isinstance(entry, dict)]
    if len(versions) != len(replays) or len(versions) != len(set(versions)):
        raise GenerationLoadError("E_V250_REPLAY_VERSION", "replay versions must be unique objects")
    return manifest


def run_replay(
    repo_root: Path | str,
    legacy_version: str,
    *,
    explicit_intent: bool = False,
    identified_artifact: bool = False,
    operation: str = "content_digest_verify",
    generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one manifest-selected read-only operation without subprocesses."""

    result: dict[str, Any] = {
        "legacy_version": legacy_version,
        "operation": operation,
        "status": "replay_unavailable",
        "checked_paths": [],
        "errors": [],
        "current_completion_eligible": False,
    }
    if explicit_intent is not True and identified_artifact is not True:
        result["errors"].append("E_V250_REPLAY_EXPLICIT_INTENT_REQUIRED")
        return result
    try:
        manifest = load_replay_manifest(repo_root, generation=generation)
    except GenerationLoadError as exc:
        result["errors"].append(exc.code)
        return result

    entry = next((item for item in manifest["replays"] if item.get("legacy_version") == legacy_version), None)
    if entry is None:
        result["errors"].append("E_V250_REPLAY_VERSION_UNAVAILABLE")
        return result
    if operation not in entry.get("supported_read_only_operations", []):
        result["errors"].append("E_V250_REPLAY_OPERATION_FORBIDDEN")
        return result
    if entry.get("network_policy") != "deny" or entry.get("write_policy") != "deny_all":
        result["errors"].append("E_V250_REPLAY_ISOLATION")
        return result
    if entry.get("isolation_profile") != "digest_only_no_subprocess":
        result["errors"].append("E_V250_REPLAY_SUBPROCESS_FORBIDDEN")
        return result

    root = Path(repo_root).resolve()
    allowset = set(manifest["optional_replay_allowlist"])
    content_digests = entry.get("content_digests")
    if not isinstance(content_digests, list) or not content_digests:
        result["errors"].append("E_V250_REPLAY_CONTENT_EMPTY")
        return result
    seen: set[str] = set()
    for item in content_digests:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            result["errors"].append("E_V250_REPLAY_CONTENT_INVALID")
            continue
        relative_path = item["path"]
        if relative_path in seen:
            result["errors"].append("E_V250_REPLAY_CONTENT_DUPLICATE")
            continue
        seen.add(relative_path)
        if relative_path not in allowset:
            result["errors"].append("E_V250_REPLAY_PATH_UNMANAGED")
            continue
        try:
            path = resolve_repo_file(root, relative_path)
        except GenerationLoadError as exc:
            result["errors"].append(exc.code)
            continue
        observed = sha256_bytes(path.read_bytes())
        result["checked_paths"].append({
            "path": relative_path,
            "expected_sha256": item.get("sha256"),
            "observed_sha256": observed,
        })
        if observed != item.get("sha256"):
            result["errors"].append("E_V250_REPLAY_CONTENT_DRIFT")

    if result["errors"]:
        result["status"] = "historical_failed"
    else:
        status = entry.get("expected_replay_status")
        result["status"] = status if status in ALLOWED_STATUSES else "replay_unavailable"
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--legacy-version", required=True)
    parser.add_argument("--operation", default="content_digest_verify")
    parser.add_argument("--explicit-intent", action="store_true")
    parser.add_argument("--identified-artifact", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_replay(
        args.repo_root,
        args.legacy_version,
        explicit_intent=args.explicit_intent,
        identified_artifact=args.identified_artifact,
        operation=args.operation,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return {"historical_passed": 0, "historical_failed": 1, "replay_unavailable": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ALLOWED_STATUSES", "REPLAY_MANIFEST_PATH", "load_replay_manifest", "run_replay"]
