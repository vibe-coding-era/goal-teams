"""Capture real installed V2.67 files for a correlated V2.68 launch handoff.

The compact receipt transports a local observer's result. A remote validator can
verify its bindings, but cannot independently inspect the originating host.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v268.release_identity import PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR


SCHEMA_VERSION = "goal-teams-v2.68-installed-predecessor-observation-v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FIELDS = frozenset({
    "schema_version", "repository", "repository_id", "target_product_version",
    "predecessor_product_version", "release_identity", "authorization_id",
    "authorization_intent_sha256", "captured_at", "state_raw_sha256",
    "package_manifest_sha256", "expected_file_set_sha256", "observed_file_set_sha256",
    "package_file_count", "extra_file_count", "strict_payload_check",
    "observation_source", "actor_assurance", "actor_relationship", "receipt_sha256",
})


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _fail(code: str) -> None:
    raise ValueError(code)


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("E_V268_PREDECESSOR_JSON_DUPLICATE")
        result[key] = value
    return result


def strict_json(raw: bytes) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_strict_pairs,
                           parse_constant=lambda _: _fail("E_V268_PREDECESSOR_JSON_NUMBER"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("E_V268_PREDECESSOR_JSON") from exc
    if not isinstance(value, dict):
        _fail("E_V268_PREDECESSOR_JSON")
    return value


def _safe_path(path: Path | str, *, directory: bool = False) -> Path:
    if not isinstance(path, (str, Path)) or ".." in Path(path).parts:
        _fail("E_V268_PREDECESSOR_PATH")
    path = Path(os.path.abspath(path))
    cursor = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            cursor /= part
            info = cursor.lstat()
            if stat.S_ISLNK(info.st_mode):
                _fail("E_V268_PREDECESSOR_SYMLINK")
        mode = path.lstat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            _fail("E_V268_PREDECESSOR_FILE_TYPE")
    except OSError as exc:
        raise ValueError("E_V268_PREDECESSOR_PATH") from exc
    return path


def _read_file(path: Path, *, max_bytes: int = 128 * 1024 * 1024) -> tuple[bytes, dict]:
    path = _safe_path(path)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > max_bytes:
            _fail("E_V268_PREDECESSOR_FILE_TYPE")
        chunks = []
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                _fail("E_V268_PREDECESSOR_FILE_SIZE")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        fresh = _safe_path(path).stat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_mode)
        if identity(before) != identity(after) or identity(after) != identity(fresh) or size != after.st_size:
            _fail("E_V268_PREDECESSOR_READ_DRIFT")
        raw = b"".join(chunks)
        return raw, {"sha256": hashlib.sha256(raw).hexdigest(), "size": size, "mode": stat.S_IMODE(after.st_mode)}
    except OSError as exc:
        raise ValueError("E_V268_PREDECESSOR_READ") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _timestamp(value: Any) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (TypeError, ValueError) as exc:
        raise ValueError("E_V268_PREDECESSOR_CAPTURE_TIME") from exc


def _authorization_errors(authorization: Mapping[str, Any]) -> list[str]:
    # Import lazily: release_flow imports runtime_transition, which consumes this
    # receipt. No capture or authorization check runs at module import time.
    from scripts.v268.release_flow import validate_project_start_authorization

    verdict = validate_project_start_authorization(
        authorization, repository="vibe-coding-era/goal-teams", version="V2.68",
        candidate_branch="codex/develop-v2.68", tag="v2.68",
    )
    return list(verdict.get("errors", []))


def validate_installed_predecessor(
    observation: object, *, authorization: Mapping[str, Any] | None = None,
    expected_identity: Mapping[str, Any], expected_authorization_id: str | None = None,
    expected_authorization_intent_sha256: str | None = None,
) -> dict[str, Any]:
    errors = []
    value = observation if isinstance(observation, dict) else {}
    if set(value) != FIELDS:
        return {"ok": False, "errors": ["E_V268_PREDECESSOR_SHAPE"]}
    if authorization is not None:
        errors.extend(_authorization_errors(authorization))
        if errors:
            return {"ok": False, "errors": errors}
        expected_authorization_id = authorization.get("authorization_id")
        expected_authorization_intent_sha256 = authorization.get("intent_sha256")
        expected_repository_id = authorization.get("repository", {}).get("id")
    else:
        expected_repository_id = "1249985345"
    if (value["schema_version"] != SCHEMA_VERSION
            or value["repository"] != "vibe-coding-era/goal-teams"
            or value["repository_id"] != expected_repository_id
            or value["target_product_version"] != "V2.68"
            or value["predecessor_product_version"] != "V2.67"
            or value["release_identity"] != dict(expected_identity)
            or not expected_authorization_id
            or value["authorization_id"] != expected_authorization_id
            or value["authorization_intent_sha256"] != expected_authorization_intent_sha256):
        errors.append("E_V268_PREDECESSOR_IDENTITY")
    for field in ("state_raw_sha256", "package_manifest_sha256", "expected_file_set_sha256", "observed_file_set_sha256", "authorization_intent_sha256", "receipt_sha256"):
        if not isinstance(value[field], str) or SHA256.fullmatch(value[field]) is None:
            errors.append("E_V268_PREDECESSOR_DIGEST")
    if (type(value["package_file_count"]) is not int or value["package_file_count"] < 1
            or type(value["extra_file_count"]) is not int or value["extra_file_count"] != 0
            or value["strict_payload_check"] != "passed"
            or value["expected_file_set_sha256"] != value["observed_file_set_sha256"]
            or value["observation_source"] != "observed_on_authorized_local_host"
            or value["actor_assurance"] != "I1" or value["actor_relationship"] != "correlated"):
        errors.append("E_V268_PREDECESSOR_PAYLOAD")
    if (value["package_file_count"] != PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_file_count"]
            or value["expected_file_set_sha256"] != PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_files_sha256"]
            or value["observed_file_set_sha256"] != PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_files_sha256"]
            or value["package_manifest_sha256"] != PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_manifest_sha256"]):
        errors.append("E_V268_PREDECESSOR_PUBLISHED_PAYLOAD")
    try:
        captured = _timestamp(value["captured_at"])
        if authorization is not None and captured < _timestamp(authorization.get("issued_at")):
            errors.append("E_V268_PREDECESSOR_CAPTURE_TIME")
        if value["receipt_sha256"] != canonical_sha256({key: item for key, item in value.items() if key != "receipt_sha256"}):
            errors.append("E_V268_PREDECESSOR_DIGEST")
    except (ValueError, TypeError, RecursionError):
        errors.append("E_V268_PREDECESSOR_DIGEST")
    return {"ok": not errors, "errors": list(dict.fromkeys(errors)), "actor_assurance": "I1", "actor_relationship": "correlated"}


def capture_installed_predecessor(
    *, installation_root: Path | str, state_path: Path | str,
    authorization: Mapping[str, Any], expected_identity: Mapping[str, Any],
    captured_at: str | None = None,
) -> dict[str, Any]:
    errors = _authorization_errors(authorization)
    if errors:
        _fail(errors[0])
    root = _safe_path(installation_root, directory=True)
    state_raw, _ = _read_file(Path(state_path), max_bytes=16 * 1024 * 1024)
    state = strict_json(state_raw)
    if (state.get("schema_version") != "goal-teams-install-v2.3"
            or state.get("version") != "V2.67" or state.get("source_kind") != "github_release_asset"
            or state.get("source_dirty") is not False
            or state.get("repository") != "vibe-coding-era/goal-teams"
            or state.get("release_tag") != expected_identity.get("tag")
            or state.get("release_id") != expected_identity.get("release_id")
            or state.get("release_state") != "published"
            or state.get("source_commit") != expected_identity.get("source_commit")
            or state.get("source_git_tree_id") != expected_identity.get("source_tree")):
        _fail("E_V268_PREDECESSOR_INSTALLED_IDENTITY")
    files = state.get("package_files")
    if not isinstance(files, list) or not 1 <= len(files) <= 20000:
        _fail("E_V268_PREDECESSOR_MANIFEST")
    try:
        declared_digest = canonical_sha256(sorted(files, key=lambda row: row["path"]))
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise ValueError("E_V268_PREDECESSOR_MANIFEST") from exc
    if (len(files) != PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_file_count"]
            or declared_digest != PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_files_sha256"]
            or state.get("package_manifest_sha256") != PUBLISHED_PREDECESSOR_PAYLOAD_ANCHOR["package_manifest_sha256"]):
        _fail("E_V268_PREDECESSOR_PUBLISHED_PAYLOAD")
    expected, observed = [], []
    seen = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size", "mode"}:
            _fail("E_V268_PREDECESSOR_MANIFEST")
        path = entry["path"]
        if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(ord(char) < 32 for char in path) or path.casefold() in seen
                or not isinstance(entry["sha256"], str) or SHA256.fullmatch(entry["sha256"]) is None
                or type(entry["size"]) is not int or entry["size"] < 0
                or type(entry["mode"]) is not int or entry["mode"] not in {0o644, 0o755}):
            _fail("E_V268_PREDECESSOR_MANIFEST")
        seen.add(path.casefold())
        raw, row = _read_file(root / path)
        if {key: entry[key] for key in ("sha256", "size", "mode")} != row:
            _fail("E_V268_PREDECESSOR_FILE_DRIFT")
        if path == "VERSION" and raw.decode("utf-8").strip() != "V2.67":
            _fail("E_V268_PREDECESSOR_INSTALLED_VERSION")
        expected.append(dict(entry))
        observed.append({"path": path, **row})
    if "version" not in seen or "skill.md" not in seen:
        _fail("E_V268_PREDECESSOR_MANIFEST")
    actual = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            _safe_path(Path(directory) / name, directory=True)
        for name in names:
            path = _safe_path(Path(directory) / name)
            actual.append(path.relative_to(root).as_posix())
    if sorted(actual) != sorted(row["path"] for row in expected):
        _fail("E_V268_PREDECESSOR_EXTRA_FILES")
    if _read_file(Path(state_path), max_bytes=16 * 1024 * 1024)[0] != state_raw:
        _fail("E_V268_PREDECESSOR_READ_DRIFT")
    timestamp = captured_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _timestamp(timestamp)
    value = {
        "schema_version": SCHEMA_VERSION, "repository": "vibe-coding-era/goal-teams",
        "repository_id": authorization["repository"]["id"], "target_product_version": "V2.68",
        "predecessor_product_version": "V2.67", "release_identity": dict(expected_identity),
        "authorization_id": authorization["authorization_id"],
        "authorization_intent_sha256": authorization["intent_sha256"], "captured_at": timestamp,
        "state_raw_sha256": hashlib.sha256(state_raw).hexdigest(),
        "package_manifest_sha256": state.get("package_manifest_sha256"),
        "expected_file_set_sha256": canonical_sha256(sorted(expected, key=lambda row: row["path"])),
        "observed_file_set_sha256": canonical_sha256(sorted(observed, key=lambda row: row["path"])),
        "package_file_count": len(observed), "extra_file_count": 0, "strict_payload_check": "passed",
        "observation_source": "observed_on_authorized_local_host", "actor_assurance": "I1", "actor_relationship": "correlated",
    }
    value["receipt_sha256"] = canonical_sha256(value)
    verdict = validate_installed_predecessor(value, authorization=authorization, expected_identity=expected_identity)
    if not verdict["ok"]:
        _fail(verdict["errors"][0])
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation-root", type=Path, required=True)
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--authorization-receipt", type=Path, required=True)
    parser.add_argument("--expected-identity", type=Path, required=True)
    args = parser.parse_args()
    try:
        authority = strict_json(_read_file(args.authorization_receipt, max_bytes=1024 * 1024)[0])
        identity = strict_json(_read_file(args.expected_identity, max_bytes=1024 * 1024)[0])
        result = capture_installed_predecessor(installation_root=args.installation_root, state_path=args.state_path, authorization=authority, expected_identity=identity.get("release_identity", identity))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError) as exc:
        code = str(exc) if str(exc).startswith("E_V") and "\n" not in str(exc) else "E_V268_PREDECESSOR_CAPTURE"
        print(json.dumps({"ok": False, "error_code": code, "external_write_count": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
