#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

PYTHON_BIN=""
for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3; do
  [[ -n "$candidate" ]] || continue
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" - <<'PY' >/dev/null 2>&1; then
import tomllib
PY
    PYTHON_BIN="$candidate"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "Goal Teams installer requires Python 3.11+ with tomllib. Set PYTHON to a compatible interpreter." >&2
  exit 2
fi

exec "$PYTHON_BIN" - "$ROOT" "$@" <<'PY'
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import tomllib
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import fcntl  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - Windows fallback
    fcntl = None


SCHEMA_VERSION = "goal-teams-install-v2.3"
OKF_GENERATED_PATH = "references/okf-conformance-manifest.json"
ROOT = Path(sys.argv[1]).resolve()
ARGS = sys.argv[2:]


class InstallError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atomically install, roll back, or uninstall Goal Teams.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--rollback", action="store_true", help="restore the immediately previous verified snapshot")
    action.add_argument("--uninstall", action="store_true", help="restore the snapshot from before Goal Teams was installed")
    parser.add_argument("--update-team-fallback", action="store_true", help="opt in to timestamped fallback agent edits")
    parser.add_argument("--dry-run", action="store_true", help="validate source and staging without switching targets")
    parser.add_argument("--allow-dirty", action="store_true", help="package tracked files from a dirty tree and record the downgrade")
    return parser.parse_args(ARGS)


args = parse_args()
code_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
skill_target = code_home / "skills" / "goal-teams"
agent_target = code_home / "agents"
state_dir = code_home / "state" / "goal-teams"
backup_root = state_dir / "backups"
preserved_root = state_dir / "preserved"
report_root = state_dir / "reports"
current_state_path = state_dir / "current.json"
stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}-{uuid.uuid4().hex[:8]}"
report_path = Path(os.environ.get("INSTALL_REPORT", str(report_root / f"{stamp}.json"))).expanduser()
manifest_path = ROOT / "scripts" / "install" / "package-manifest.txt"
validation_results: list[dict[str, Any]] = []
preserved_changes: list[dict[str, Any]] = []
package_files: list[dict[str, Any]] = []
generated_paths: set[str] = set()
backed_up_components: list[str] = []
source_info: dict[str, Any] = {
    "version": "unknown",
    "commit": "unknown",
    "dirty": None,
    "dirty_entry_count": None,
    "tree_digest": None,
    "tracked_tree_digest": None,
    "git_tree_id": None,
    "package_manifest_sha256": None,
    "okf_conformance_manifest_sha256": None,
    "okf_payload_tree_sha256": None,
    "okf_policy_sha256": None,
    "okf_checker_hashes": {},
    "okf_package_completeness_state": "unavailable",
    "skill_source_path": ".",
    "prompt_identity_version": None,
    "runtime_prompt_route": "installed_startup",
    "runtime_prompt_refs": [],
    "prefix_manifest_sha256": None,
    "route_static_digest": None,
    "prompt_manifest_status": "unavailable",
    "prompt_digest_scope": "partial",
    "stable_prefix_digest": None,
    "runtime_prompt_digest": None,
}
dependencies = {
    "python": {"required": True, "available": True, "version": ".".join(map(str, sys.version_info[:3]))},
    "tomllib": {"required": True, "available": True},
    "git": {"required": True, "available": shutil.which("git") is not None},
    "pyyaml": {"required": False, "available": importlib.util.find_spec("yaml") is not None},
    "pillow": {"required": False, "available": importlib.util.find_spec("PIL") is not None},
}
install_lock_handle: Any = None
install_lock_directory: Path | None = None


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_prompt_identity(root: Path) -> dict[str, Any]:
    module_path = root / "scripts" / "v23" / "prompt_cache.py"
    if not module_path.is_file() or module_path.is_symlink():
        raise InstallError("E_PROMPT_IDENTITY_RUNTIME")
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            f"_goalteams_install_prompt_cache_{stamp}", module_path
        )
        if spec is None or spec.loader is None:
            raise InstallError("E_PROMPT_IDENTITY_RUNTIME")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    try:
        identity = module.build_prompt_identity(root, "installed_startup")
    except (OSError, TypeError, ValueError) as exc:
        raise InstallError("E_PROMPT_IDENTITY_INVALID") from exc
    if identity.get("passed") is not True:
        raise InstallError("E_PROMPT_IDENTITY_BUDGET")
    return identity


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{stamp}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def safe_report_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(code_home).as_posix()
    except ValueError:
        return "custom-report.json"


def write_report(status: str, action: str, *, backup_id: str | None = None, error_code: str | None = None) -> None:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "action": action,
        "created_at": utc_now(),
        "source": source_info,
        "target": {
            "skill": "skills/goal-teams",
            "agents": "agents/goal-*.toml",
            "state": "state/goal-teams/current.json",
        },
        "dependencies": dependencies,
        "validation": validation_results,
        "package_files": package_files,
        "backup_id": backup_id,
        "backed_up_components": backed_up_components,
        "preserved_user_changes": preserved_changes,
        "report_ref": safe_report_path(report_path),
        "error_code": error_code,
    }
    atomic_json(report_path, payload)


def acquire_install_lock() -> None:
    global install_lock_handle, install_lock_directory
    state_dir.mkdir(parents=True, exist_ok=True)
    if fcntl is not None:
        lock_path = state_dir / "install.lock"
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise InstallError("E_INSTALL_LOCKED") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "started_at": utc_now()}, sort_keys=True) + "\n")
        handle.flush()
        install_lock_handle = handle
        return
    lock_directory = state_dir / "install.lock.d"
    try:
        lock_directory.mkdir()
    except FileExistsError as exc:  # pragma: no cover - Windows fallback
        raise InstallError("E_INSTALL_LOCKED") from exc
    install_lock_directory = lock_directory


def release_install_lock() -> None:
    global install_lock_handle, install_lock_directory
    if install_lock_handle is not None:
        if fcntl is not None:
            fcntl.flock(install_lock_handle.fileno(), fcntl.LOCK_UN)
        install_lock_handle.close()
        install_lock_handle = None
    if install_lock_directory is not None:
        shutil.rmtree(install_lock_directory, ignore_errors=True)
        install_lock_directory = None


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def git(*git_args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", *git_args], cwd=ROOT, capture_output=True, text=text, check=False
    )


def validate_relative_path(raw: str) -> None:
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "\\" in raw:
        raise InstallError(f"E_MANIFEST_PATH:{raw}")


def safe_source_file(relative: str) -> Path:
    """Resolve a tracked package file without following any ancestor symlink."""
    validate_relative_path(relative)
    parts = PurePosixPath(relative).parts
    cursor = ROOT
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            metadata = cursor.lstat()
        except OSError as exc:
            raise InstallError(f"E_PACKAGE_FILE_INVALID:{relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError(f"E_PACKAGE_ANCESTOR_UNSAFE:{relative}")
        is_final = index == len(parts) - 1
        if is_final and not stat.S_ISREG(metadata.st_mode):
            raise InstallError(f"E_PACKAGE_FILE_INVALID:{relative}")
        if not is_final and not stat.S_ISDIR(metadata.st_mode):
            raise InstallError(f"E_PACKAGE_ANCESTOR_UNSAFE:{relative}")
    try:
        cursor.resolve(strict=True).relative_to(ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise InstallError(f"E_PACKAGE_ANCESTOR_UNSAFE:{relative}") from exc
    return cursor


def load_allowlist() -> tuple[set[str], list[str], set[str]]:
    try:
        safe_manifest_path = safe_source_file("scripts/install/package-manifest.txt")
    except InstallError as exc:
        raise InstallError("E_PACKAGE_MANIFEST_MISSING") from exc
    files: set[str] = set()
    prefixes: list[str] = []
    generated: set[str] = set()
    for number, raw_line in enumerate(safe_manifest_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in {"file", "prefix", "generated"}:
            raise InstallError(f"E_PACKAGE_MANIFEST_SYNTAX:{number}")
        kind, value = parts
        validate_relative_path(value.rstrip("/"))
        if kind == "file":
            if value.endswith("/"):
                raise InstallError(f"E_PACKAGE_MANIFEST_FILE:{number}")
            files.add(value)
        elif kind == "prefix":
            if not value.endswith("/"):
                raise InstallError(f"E_PACKAGE_MANIFEST_PREFIX:{number}")
            prefixes.append(value)
        else:
            if value.endswith("/"):
                raise InstallError(f"E_PACKAGE_MANIFEST_GENERATED:{number}")
            generated.add(value)
    required_entries = {"VERSION", "SKILL.md", "scripts/check.sh", "scripts/install/package-manifest.txt"}
    tracked_by_manifest = lambda item: item in files or any(item.startswith(prefix) for prefix in prefixes)
    missing = sorted(item for item in required_entries if not tracked_by_manifest(item))
    if missing:
        raise InstallError("E_PACKAGE_MANIFEST_REQUIRED:" + ",".join(missing))
    if generated != {OKF_GENERATED_PATH}:
        raise InstallError("E_PACKAGE_MANIFEST_GENERATED")
    return files, prefixes, generated


def package_tree_digest() -> str:
    digest_input = "".join(
        f"{entry['path']}\0{entry['sha256']}\0{entry['size']}\0{entry['mode']}\n"
        for entry in sorted(package_files, key=lambda value: value["path"])
    ).encode("utf-8")
    return sha256_bytes(digest_input)


def prepare_source() -> list[str]:
    if not dependencies["git"]["available"]:
        raise InstallError("E_DEPENDENCY_GIT: install Git before running the installer")
    inside = git("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise InstallError("E_SOURCE_NOT_GIT: install from a Git working tree")
    commit = git("rev-parse", "HEAD")
    if commit.returncode != 0:
        raise InstallError("E_SOURCE_COMMIT")
    status_result = git("status", "--porcelain=v1", "--untracked-files=all")
    if status_result.returncode != 0:
        raise InstallError("E_SOURCE_STATUS")
    dirty_lines = [line for line in status_result.stdout.splitlines() if line]
    source_info["version"] = safe_source_file("VERSION").read_text(encoding="utf-8").strip()
    source_info["commit"] = commit.stdout.strip()
    tree = git("rev-parse", "HEAD^{tree}")
    if tree.returncode != 0:
        raise InstallError("E_SOURCE_TREE")
    source_info["git_tree_id"] = tree.stdout.strip()
    source_info["dirty"] = bool(dirty_lines)
    source_info["dirty_entry_count"] = len(dirty_lines)
    if dirty_lines and not args.allow_dirty:
        raise InstallError("E_SOURCE_DIRTY: commit/stash changes or explicitly pass --allow-dirty")
    tracked_result = git("ls-files", "-z", text=False)
    if tracked_result.returncode != 0:
        raise InstallError("E_SOURCE_TRACKED_FILES")
    tracked = [item.decode("utf-8") for item in tracked_result.stdout.split(b"\0") if item]
    allowed_files, allowed_prefixes, required_generated = load_allowlist()
    generated_paths.clear()
    generated_paths.update(required_generated)
    tracked_generated = sorted(set(tracked) & required_generated)
    if tracked_generated:
        raise InstallError("E_PACKAGE_GENERATED_TRACKED:" + ",".join(tracked_generated))
    selected = sorted(
        item for item in tracked
        if item in allowed_files or any(item.startswith(prefix) for prefix in allowed_prefixes)
    )
    if not selected:
        raise InstallError("E_PACKAGE_EMPTY")
    for relative in selected:
        source = safe_source_file(relative)
        file_mode = stat.S_IMODE(source.stat().st_mode)
        if file_mode & 0o7000:
            raise InstallError(f"E_PACKAGE_FILE_MODE:{relative}")
        entry = {
            "path": relative,
            "sha256": sha256_file(source),
            "size": source.stat().st_size,
            "mode": file_mode,
        }
        package_files.append(entry)
    source_info["package_manifest_sha256"] = sha256_file(
        safe_source_file("scripts/install/package-manifest.txt")
    )
    source_info["tracked_tree_digest"] = package_tree_digest()
    source_info["tree_digest"] = source_info["tracked_tree_digest"]
    prompt_identity = compute_prompt_identity(ROOT)
    source_info.update({
        "prompt_identity_version": prompt_identity["prompt_identity_version"],
        "runtime_prompt_route": prompt_identity["route_id"],
        "runtime_prompt_refs": prompt_identity["ordered_refs"],
        "prefix_manifest_sha256": prompt_identity["prefix_manifest_sha256"],
        "route_static_digest": prompt_identity["route_static_digest"],
        "prompt_manifest_status": prompt_identity["manifest_status"],
        "prompt_digest_scope": prompt_identity["digest_scope"],
        "stable_prefix_digest": prompt_identity["stable_prefix_digest"],
        "runtime_prompt_digest": prompt_identity["runtime_prompt_digest"],
    })
    return selected


def validation_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GOAL_TEAMS_INSTALL_VALIDATION"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["CODEX_HOME"] = str(code_home)
    return environment


def validate_skill(root: Path, phase: str) -> None:
    checker = root / "scripts" / "check.sh"
    if not checker.is_file():
        raise InstallError(f"E_VALIDATION_ENTRY:{phase}")
    result = run([str(checker)], cwd=root, env=validation_environment())
    combined = (result.stdout + result.stderr).encode("utf-8", errors="replace")
    validation_results.append({
        "phase": phase,
        "command": "scripts/check.sh",
        "exit_code": result.returncode,
        "output_sha256": sha256_bytes(combined),
        "status": "passed" if result.returncode == 0 else "failed",
    })
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise InstallError(f"E_VALIDATION_FAILED:{phase}")
    prompt_identity = compute_prompt_identity(root)
    if (
        prompt_identity["prefix_manifest_sha256"]
        != source_info.get("prefix_manifest_sha256")
        or prompt_identity["route_static_digest"]
        != source_info.get("route_static_digest")
        or prompt_identity["ordered_refs"] != source_info.get("runtime_prompt_refs")
    ):
        raise InstallError(f"E_PROMPT_IDENTITY_DRIFT:{phase}")
    validation_results.append({
        "phase": f"prompt_identity_{phase}",
        "command": "scripts/v23/prompt_cache.py:installed_startup",
        "exit_code": 0,
        "status": "passed",
        "prefix_manifest_sha256": prompt_identity["prefix_manifest_sha256"],
        "route_static_digest": prompt_identity["route_static_digest"],
        "manifest_status": prompt_identity["manifest_status"],
        "digest_scope": prompt_identity["digest_scope"],
        "runtime_prompt_digest": prompt_identity["runtime_prompt_digest"],
    })


def copy_package(selected: list[str], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    expected_by_path = {entry["path"]: entry for entry in package_files}
    if set(expected_by_path) != set(selected):
        raise InstallError("E_PACKAGE_MANIFEST_DRIFT")
    for relative in selected:
        source = safe_source_file(relative)
        expected = expected_by_path[relative]
        source_record = {
            "path": relative,
            "sha256": sha256_file(source),
            "size": source.stat().st_size,
            "mode": stat.S_IMODE(source.stat().st_mode),
        }
        if source_record != expected:
            raise InstallError(f"E_PACKAGE_SOURCE_CHANGED:{relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        staged_record = {
            "path": relative,
            "sha256": sha256_file(target),
            "size": target.stat().st_size,
            "mode": stat.S_IMODE(target.stat().st_mode),
        }
        if staged_record != expected:
            raise InstallError(f"E_PACKAGE_COPY_DRIFT:{relative}")
    validate_package_tree(destination, "copy")


def generate_okf_manifest(stage: Path) -> None:
    if generated_paths != {OKF_GENERATED_PATH}:
        raise InstallError("E_PACKAGE_MANIFEST_GENERATED")
    runtime_path = stage / "scripts" / "v23" / "okf_conformance.py"
    checker_path = stage / "scripts" / "checks" / "check-okf.py"
    if (
        not runtime_path.is_file()
        or runtime_path.is_symlink()
        or not checker_path.is_file()
        or checker_path.is_symlink()
    ):
        raise InstallError("E_OKF_PACKAGE_RUNTIME")
    spec = importlib.util.spec_from_file_location(
        f"_goalteams_install_okf_{stamp}", runtime_path
    )
    if spec is None or spec.loader is None:
        raise InstallError("E_OKF_PACKAGE_RUNTIME")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except (OSError, TypeError, ValueError) as exc:
        raise InstallError("E_OKF_PACKAGE_RUNTIME") from exc
    finally:
        sys.dont_write_bytecode = previous
    try:
        policy = module.load_policy(stage)
        manifest = module.build_package_manifest(
            stage,
            policy,
            source_binding={
                "commit_sha256": source_info["commit"],
                "git_tree_id": source_info["git_tree_id"],
                "package_manifest_sha256": source_info["package_manifest_sha256"],
            },
        )
    except (OSError, TypeError, ValueError) as exc:
        raise InstallError("E_OKF_PACKAGE_GENERATE") from exc
    if (
        manifest.get("manifest_scope") != "installed_package_complete"
        or manifest.get("source", {}).get("commit_sha256") != source_info["commit"]
        or manifest.get("source", {}).get("git_tree_id") != source_info["git_tree_id"]
        or manifest.get("source", {}).get("package_manifest_sha256")
        != source_info["package_manifest_sha256"]
    ):
        raise InstallError("E_OKF_PACKAGE_SOURCE_BINDING")
    data = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    target = stage / OKF_GENERATED_PATH
    if target.exists() or target.is_symlink():
        raise InstallError("E_OKF_PACKAGE_GENERATED_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.resolve(strict=True).relative_to(stage.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise InstallError("E_OKF_PACKAGE_GENERATED_PATH") from exc
    temporary = target.with_name(f".{target.name}.tmp-{stamp}")
    temporary.write_bytes(data)
    temporary.chmod(0o644)
    os.replace(temporary, target)
    package_files.append(
        {
            "path": OKF_GENERATED_PATH,
            "sha256": sha256_bytes(data),
            "size": len(data),
            "mode": 0o644,
        }
    )
    source_info.update(
        {
            "tree_digest": package_tree_digest(),
            "okf_conformance_manifest_sha256": sha256_bytes(data),
            "okf_payload_tree_sha256": manifest["package"]["payload_tree_sha256"],
            "okf_policy_sha256": manifest["policy"]["sha256"],
            "okf_checker_hashes": {
                item["path"]: item["sha256"] for item in manifest["checkers"]
            },
        }
    )
    validate_package_tree(stage, "generated_manifest")
    replay = run(
        [
            sys.executable,
            str(checker_path),
            "--root",
            str(stage),
            "--package-tree",
            str(stage),
        ],
        cwd=stage,
        env=validation_environment(),
    )
    try:
        replay_payload = json.loads(replay.stdout)
    except json.JSONDecodeError as exc:
        raise InstallError("E_OKF_PACKAGE_REPLAY") from exc
    if (
        replay.returncode != 0
        or replay_payload.get("passed") is not True
        or replay_payload.get("package_completeness_state") != "complete"
    ):
        raise InstallError("E_OKF_PACKAGE_REPLAY")
    source_info["okf_package_completeness_state"] = "complete"
    validation_results.append(
        {
            "phase": "okf_package_tree_staging",
            "command": "scripts/checks/check-okf.py --package-tree",
            "exit_code": 0,
            "status": "passed",
            "manifest_sha256": source_info["okf_conformance_manifest_sha256"],
            "payload_tree_sha256": source_info["okf_payload_tree_sha256"],
            "policy_sha256": source_info["okf_policy_sha256"],
        }
    )


def validate_package_tree(root: Path, phase: str) -> None:
    actual: list[dict[str, Any]] = []
    if not root.is_dir() or root.is_symlink():
        raise InstallError(f"E_PACKAGE_TREE_INVALID:{phase}")
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
        ):
            raise InstallError(f"E_PACKAGE_TREE_NONREGULAR:{phase}:{relative}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        actual.append({
            "path": relative,
            "sha256": sha256_file(path),
            "size": metadata.st_size,
            "mode": stat.S_IMODE(metadata.st_mode),
        })
    expected = sorted(package_files, key=lambda entry: entry["path"])
    if actual != expected:
        raise InstallError(f"E_PACKAGE_TREE_DRIFT:{phase}")
    validation_results.append({
        "phase": f"package_identity_{phase}",
        "command": "path/mode/size/sha256 manifest comparison",
        "exit_code": 0,
        "status": "passed",
    })


def file_record(path: Path, relative: str) -> dict[str, Any]:
    mode = stat.S_IMODE(path.lstat().st_mode)
    if path.is_symlink():
        return {"path": relative, "type": "symlink", "mode": mode, "target": os.readlink(path)}
    return {"path": relative, "type": "file", "mode": mode, "sha256": sha256_file(path), "size": path.stat().st_size}


def tree_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir() or path.is_symlink():
        raise InstallError("E_TREE_NOT_DIRECTORY")
    records: list[dict[str, Any]] = []
    for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        relative = child.relative_to(path).as_posix()
        if child.is_symlink() or child.is_file():
            records.append(file_record(child, relative))
        elif child.is_dir():
            records.append({
                "path": relative,
                "type": "directory",
                "mode": stat.S_IMODE(child.stat().st_mode),
            })
    return records


def records_digest(records: list[dict[str, Any]]) -> str:
    return sha256_bytes(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def path_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {"exists": False}
    if path.is_dir() and not path.is_symlink():
        records = tree_records(path)
        return {"exists": True, "type": "directory", "digest": records_digest(records), "files": records}
    record = file_record(path, ".")
    return {"exists": True, "type": record["type"], "digest": records_digest([record]), "file": record}


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def copy_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, destination, symlinks=True)
    elif source.is_symlink():
        destination.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, destination)


def read_state() -> dict[str, Any] | None:
    if not current_state_path.is_file():
        return None
    try:
        payload = json.loads(current_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError("E_INSTALL_STATE_INVALID") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise InstallError("E_INSTALL_STATE_SCHEMA")
    for field in ("managed_agent_files", "fallback_agent_files"):
        values = payload.get(field, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) and Path(value).name == value for value in values
        ):
            raise InstallError(f"E_INSTALL_STATE_FIELD:{field}")
    for field in ("backup_id", "origin_backup_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not value or Path(value).name != value:
            raise InstallError(f"E_INSTALL_STATE_FIELD:{field}")
    for field in ("version", "source_commit", "source_tree_digest", "skill_tree_digest"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise InstallError(f"E_INSTALL_STATE_FIELD:{field}")
    agent_hashes = payload.get("agent_hashes", {})
    allowed_agents = set(payload.get("managed_agent_files", []) + payload.get("fallback_agent_files", []))
    if (
        not isinstance(agent_hashes, dict)
        or set(agent_hashes) != allowed_agents
        or not all(
            isinstance(key, str)
            and Path(key).name == key
            and key in allowed_agents
            and isinstance(value, str)
            and value
            for key, value in agent_hashes.items()
        )
    ):
        raise InstallError("E_INSTALL_STATE_FIELD:agent_hashes")
    stored_package_files = payload.get("package_files")
    if not isinstance(stored_package_files, list) or not stored_package_files:
        raise InstallError("E_INSTALL_STATE_FIELD:package_files")
    for entry in stored_package_files:
        if not isinstance(entry, dict):
            raise InstallError("E_INSTALL_STATE_FIELD:package_files")
        package_path = entry.get("path")
        try:
            if not isinstance(package_path, str):
                raise ValueError
            validate_relative_path(package_path)
        except (ValueError, InstallError) as exc:
            raise InstallError("E_INSTALL_STATE_FIELD:package_files") from exc
        digest = entry.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(entry.get("size"), int)
            or entry["size"] < 0
            or not isinstance(entry.get("mode"), int)
        ):
            raise InstallError("E_INSTALL_STATE_FIELD:package_files")
    return payload


def target_for_label(label: str) -> Path:
    if label == "skill":
        return skill_target
    if label.startswith("agent:"):
        name = label.split(":", 1)[1]
        if Path(name).name != name:
            raise InstallError("E_BACKUP_AGENT_NAME")
        return agent_target / name
    raise InstallError("E_BACKUP_LABEL")


def snapshot_path(backup_dir: Path, label: str) -> Path:
    if label == "skill":
        return backup_dir / "snapshot" / "skill"
    return backup_dir / "snapshot" / "agents" / label.split(":", 1)[1]


def detect_and_preserve_user_changes(state: dict[str, Any] | None, action: str) -> None:
    if not state:
        return
    changed: list[tuple[str, Path]] = []
    expected_skill = state.get("skill_tree_digest")
    if expected_skill and path_snapshot(skill_target).get("digest") != expected_skill:
        changed.append(("skill", skill_target))
    expected_agents = state.get("agent_hashes", {})
    if isinstance(expected_agents, dict):
        for name, expected in sorted(expected_agents.items()):
            target = agent_target / name
            actual = path_snapshot(target).get("digest")
            if actual != expected:
                changed.append((f"agent:{name}", target))
    if not changed:
        return
    preserve_dir = preserved_root / stamp
    for label, source in changed:
        if not source.exists() and not source.is_symlink():
            preserved_changes.append({"component": label, "status": "user_removed", "archive_ref": "not_applicable"})
            continue
        preserved_digest = path_snapshot(source).get("digest")
        archive = preserve_dir / ("skill" if label == "skill" else f"agents/{label.split(':', 1)[1]}")
        copy_path(source, archive)
        preserved_changes.append({
            "component": label,
            "status": "archived_before_" + action,
            "archive_ref": archive.relative_to(code_home).as_posix(),
            "digest": preserved_digest,
        })


def create_backup(labels: list[str], previous_state: dict[str, Any] | None) -> tuple[str, Path]:
    backup_id = stamp
    backup_dir = backup_root / backup_id
    backup_dir.mkdir(parents=True, exist_ok=False)
    components: list[dict[str, Any]] = []
    for label in labels:
        target = target_for_label(label)
        metadata = path_snapshot(target)
        components.append({"label": label, "snapshot": metadata})
        if metadata["exists"]:
            backed_up_components.append(label)
            copy_path(target, snapshot_path(backup_dir, label))
    if previous_state is not None:
        atomic_json(backup_dir / "previous-state.json", previous_state)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "backup_id": backup_id,
        "created_at": utc_now(),
        "components": components,
        "has_previous_state": previous_state is not None,
    }
    atomic_json(backup_dir / "backup-manifest.json", manifest)
    validate_backup(backup_dir)
    validation_results.append({"phase": "backup", "command": "manifest hash validation", "exit_code": 0, "status": "passed"})
    return backup_id, backup_dir


def load_backup(backup_id: str) -> tuple[Path, dict[str, Any]]:
    if not backup_id or Path(backup_id).name != backup_id:
        raise InstallError("E_BACKUP_ID")
    backup_dir = backup_root / backup_id
    manifest_file = backup_dir / "backup-manifest.json"
    if not manifest_file.is_file():
        raise InstallError("E_BACKUP_MANIFEST_MISSING")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallError("E_BACKUP_MANIFEST_JSON") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("backup_id") != backup_id:
        raise InstallError("E_BACKUP_MANIFEST_SCHEMA")
    return backup_dir, manifest


def validate_backup(backup_dir: Path) -> dict[str, Any]:
    backup_id = backup_dir.name
    loaded_dir, manifest = load_backup(backup_id)
    if loaded_dir != backup_dir:
        raise InstallError("E_BACKUP_LOCATION")
    labels: set[str] = set()
    for component in manifest.get("components", []):
        label = component.get("label")
        if not isinstance(label, str) or label in labels:
            raise InstallError("E_BACKUP_COMPONENT")
        labels.add(label)
        expected = component.get("snapshot")
        if not isinstance(expected, dict):
            raise InstallError("E_BACKUP_SNAPSHOT")
        stored = snapshot_path(backup_dir, label)
        actual = path_snapshot(stored)
        if expected.get("exists"):
            if actual.get("digest") != expected.get("digest") or actual.get("type") != expected.get("type"):
                raise InstallError(f"E_BACKUP_HASH:{label}")
        elif actual.get("exists"):
            raise InstallError(f"E_BACKUP_UNEXPECTED:{label}")
    return manifest


def restore_backup(backup_dir: Path, *, restore_previous_state: bool) -> None:
    manifest = validate_backup(backup_dir)
    transaction = Path(tempfile.mkdtemp(prefix=f".goal-teams-restore-{stamp}-", dir=code_home))
    staged = transaction / "staged"
    previous_live = transaction / "previous-live"
    state_before = current_state_path.read_bytes() if current_state_path.is_file() else None
    try:
        for component in manifest["components"]:
            label = component["label"]
            expected = component["snapshot"]
            if expected["exists"]:
                stage_path = snapshot_path(staged, label)
                copy_path(snapshot_path(backup_dir, label), stage_path)
                actual = path_snapshot(stage_path)
                if actual.get("digest") != expected.get("digest") or actual.get("type") != expected.get("type"):
                    raise InstallError(f"E_RESTORE_STAGING_HASH:{label}")

        switched_labels: list[str] = []
        try:
            for component in manifest["components"]:
                label = component["label"]
                target = target_for_label(label)
                target.parent.mkdir(parents=True, exist_ok=True)
                switched_labels.append(label)
                if target.exists() or target.is_symlink():
                    live_snapshot = snapshot_path(previous_live, label)
                    live_snapshot.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, live_snapshot)
                if component["snapshot"]["exists"]:
                    os.replace(snapshot_path(staged, label), target)
            if restore_previous_state:
                previous = backup_dir / "previous-state.json"
                if previous.is_file():
                    payload = json.loads(previous.read_text(encoding="utf-8"))
                    atomic_json(current_state_path, payload)
                else:
                    current_state_path.unlink(missing_ok=True)
            for component in manifest["components"]:
                label = component["label"]
                expected = component["snapshot"]
                actual = path_snapshot(target_for_label(label))
                if actual.get("digest") != expected.get("digest") or actual.get("exists") != expected.get("exists"):
                    raise InstallError(f"E_RESTORE_HASH:{label}")
        except BaseException:
            for label in reversed(switched_labels):
                target = target_for_label(label)
                remove_path(target)
                live_snapshot = snapshot_path(previous_live, label)
                if live_snapshot.exists() or live_snapshot.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(live_snapshot, target)
            if state_before is None:
                current_state_path.unlink(missing_ok=True)
            else:
                current_state_path.parent.mkdir(parents=True, exist_ok=True)
                state_tmp = current_state_path.with_name(f".{current_state_path.name}.restore-{stamp}")
                state_tmp.write_bytes(state_before)
                os.replace(state_tmp, current_state_path)
            raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


FALLBACK_REPLACEMENTS = {
    "team-implementer.toml": 'nickname_candidates = ["实现-功能开发", "实现-修复任务", "实现-集成改造"]',
    "team-qa.toml": 'nickname_candidates = ["测试-E2E 验证", "测试-回归检查", "测试-验收证据"]',
    "team-researcher.toml": 'nickname_candidates = ["调研-代码路径分析", "调研-资料证据收集", "调研-上下文梳理"]',
    "team-reviewer.toml": 'nickname_candidates = ["评审-代码审查", "评审-一致性复核", "评审-风险边界检查"]',
}


def prepare_agents(stage_skill: Path, stage_agents: Path) -> tuple[list[str], list[str]]:
    stage_agents.mkdir(parents=True, exist_ok=True)
    managed: list[str] = []
    fallback: list[str] = []
    for source in sorted((stage_skill / "subagents").glob("goal-*.toml")):
        with source.open("rb") as handle:
            tomllib.load(handle)
        shutil.copy2(source, stage_agents / source.name)
        managed.append(source.name)
    if not managed:
        raise InstallError("E_AGENT_PACKAGE_EMPTY")
    if args.update_team_fallback:
        for name, replacement in FALLBACK_REPLACEMENTS.items():
            source = agent_target / name
            if not source.is_file():
                continue
            original = source.read_text(encoding="utf-8")
            lines = original.splitlines()
            replaced = False
            previous_nickname_lines: list[str] = []
            updated_lines: list[str] = []
            for line in lines:
                if line.startswith("nickname_candidates = "):
                    previous_nickname_lines.append(line)
                    updated_lines.append(replacement)
                    replaced = True
                else:
                    updated_lines.append(line)
            if not replaced:
                updated_lines.append(replacement)
            updated = "\n".join(updated_lines) + "\n"
            target = stage_agents / name
            target.write_text(updated, encoding="utf-8")
            with target.open("rb") as handle:
                tomllib.load(handle)
            print(f"--- agents/{name}:nickname_candidates (current)")
            print(f"+++ agents/{name}:nickname_candidates (proposed)")
            for old_line in previous_nickname_lines or ["nickname_candidates = <absent>"]:
                print(f"-{old_line}")
            print(f"+{replacement}")
            fallback.append(name)
    return managed, fallback


def maybe_fail(point: str) -> None:
    if os.environ.get("GOAL_TEAMS_INSTALL_FAIL_AT") == point:
        raise InstallError(f"E_FAULT_INJECTION:{point}")


def state_payload(
    *, backup_id: str, origin_backup_id: str, managed_agents: list[str], fallback_agents: list[str]
) -> dict[str, Any]:
    agent_hashes = {
        name: path_snapshot(agent_target / name).get("digest")
        for name in sorted(managed_agents + fallback_agents)
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "installed_at": utc_now(),
        "version": source_info["version"],
        "source_commit": source_info["commit"],
        "source_dirty": source_info["dirty"],
        "source_tree_digest": source_info["tree_digest"],
        "source_tracked_tree_digest": source_info["tracked_tree_digest"],
        "source_git_tree_id": source_info["git_tree_id"],
        "package_manifest_sha256": source_info["package_manifest_sha256"],
        "okf_conformance_manifest_sha256": source_info["okf_conformance_manifest_sha256"],
        "okf_payload_tree_sha256": source_info["okf_payload_tree_sha256"],
        "okf_policy_sha256": source_info["okf_policy_sha256"],
        "okf_checker_hashes": source_info["okf_checker_hashes"],
        "okf_package_completeness_state": source_info["okf_package_completeness_state"],
        "skill_source_path": source_info["skill_source_path"],
        "prompt_identity_version": source_info["prompt_identity_version"],
        "runtime_prompt_route": source_info["runtime_prompt_route"],
        "runtime_prompt_refs": source_info["runtime_prompt_refs"],
        "prefix_manifest_sha256": source_info["prefix_manifest_sha256"],
        "route_static_digest": source_info["route_static_digest"],
        "prompt_manifest_status": source_info["prompt_manifest_status"],
        "prompt_digest_scope": source_info["prompt_digest_scope"],
        "stable_prefix_digest": source_info["stable_prefix_digest"],
        "runtime_prompt_digest": source_info["runtime_prompt_digest"],
        "skill_tree_digest": path_snapshot(skill_target).get("digest"),
        "agent_hashes": agent_hashes,
        "managed_agent_files": sorted(managed_agents),
        "fallback_agent_files": sorted(fallback_agents),
        "backup_id": backup_id,
        "origin_backup_id": origin_backup_id,
        "package_files": package_files,
    }


def lifecycle_action(action: str) -> None:
    state = read_state()
    if state is None:
        raise InstallError(f"E_{action.upper()}_NO_STATE")
    source_info.update({
        "version": state.get("version", "unknown"),
        "commit": state.get("source_commit", "unknown"),
        "dirty": state.get("source_dirty"),
        "dirty_entry_count": None,
        "tree_digest": state.get("source_tree_digest"),
        "tracked_tree_digest": state.get("source_tracked_tree_digest"),
        "git_tree_id": state.get("source_git_tree_id"),
        "package_manifest_sha256": state.get("package_manifest_sha256"),
        "okf_conformance_manifest_sha256": state.get("okf_conformance_manifest_sha256"),
        "okf_payload_tree_sha256": state.get("okf_payload_tree_sha256"),
        "okf_policy_sha256": state.get("okf_policy_sha256"),
        "okf_checker_hashes": state.get("okf_checker_hashes", {}),
        "okf_package_completeness_state": state.get(
            "okf_package_completeness_state", "unavailable"
        ),
        "skill_source_path": state.get("skill_source_path", "legacy_unknown"),
        "prompt_identity_version": state.get("prompt_identity_version"),
        "runtime_prompt_route": state.get("runtime_prompt_route", "installed_startup"),
        "runtime_prompt_refs": state.get("runtime_prompt_refs", []),
        "prefix_manifest_sha256": state.get("prefix_manifest_sha256"),
        "route_static_digest": state.get("route_static_digest"),
        "prompt_manifest_status": state.get("prompt_manifest_status", "unavailable"),
        "prompt_digest_scope": state.get("prompt_digest_scope", "partial"),
        "stable_prefix_digest": state.get("stable_prefix_digest"),
        "runtime_prompt_digest": state.get("runtime_prompt_digest"),
    })
    stored_package_files = state.get("package_files", [])
    if isinstance(stored_package_files, list):
        package_files.extend(stored_package_files)
    backup_id = state["backup_id"] if action == "rollback" else state["origin_backup_id"]
    backup_dir, _ = load_backup(backup_id)
    validate_backup(backup_dir)
    validation_results.append({"phase": "backup", "command": "manifest hash validation", "exit_code": 0, "status": "passed"})
    if args.dry_run:
        write_report("dry_run", action, backup_id=backup_id)
        print(f"Dry-run {action}: verified backup {backup_id}")
        return
    detect_and_preserve_user_changes(state, action)
    restore_backup(backup_dir, restore_previous_state=action == "rollback")
    if action == "uninstall":
        current_state_path.unlink(missing_ok=True)
    validation_results.append({"phase": "restore", "command": "byte-equivalent manifest verification", "exit_code": 0, "status": "passed"})
    write_report("restored" if action == "rollback" else "uninstalled", action, backup_id=backup_id)
    print(f"Goal Teams {action} completed; backup {backup_id} verified.")


def install() -> None:
    previous_state = read_state()
    selected = prepare_source()
    action = "update" if previous_state is not None else "install"
    validate_skill(ROOT, "source")
    code_home.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=f".goal-teams-transaction-{stamp}-", dir=code_home))
    backup_dir: Path | None = None
    backup_id: str | None = None
    switched = False
    try:
        stage_skill = transaction / "stage" / "skill"
        stage_agents = transaction / "stage" / "agents"
        copy_package(selected, stage_skill)
        generate_okf_manifest(stage_skill)
        managed_agents, fallback_agents = prepare_agents(stage_skill, stage_agents)
        if previous_state is not None:
            for name in previous_state.get("fallback_agent_files", []):
                if not isinstance(name, str) or Path(name).name != name:
                    raise InstallError("E_INSTALL_STATE_FALLBACK")
                if name in fallback_agents:
                    continue
                existing_fallback = agent_target / name
                if existing_fallback.is_file() and not existing_fallback.is_symlink():
                    shutil.copy2(existing_fallback, stage_agents / name)
                    fallback_agents.append(name)
        validate_skill(stage_skill, "staging")
        validate_package_tree(stage_skill, "post_staging_validation")
        maybe_fail("staging_validation")
        if args.dry_run:
            write_report("dry_run", action)
            print(f"Dry-run {action}: source and tracked allowlist staging verified.")
            return

        detect_and_preserve_user_changes(previous_state, action)
        previous_managed = previous_state.get("managed_agent_files", []) if previous_state else []
        previous_fallback = previous_state.get("fallback_agent_files", []) if previous_state else []
        affected_agents = sorted(set(managed_agents + fallback_agents + previous_managed + previous_fallback))
        labels = ["skill"] + [f"agent:{name}" for name in affected_agents]
        backup_id, backup_dir = create_backup(labels, previous_state)
        origin_backup_id = previous_state.get("origin_backup_id", backup_id) if previous_state else backup_id

        skill_target.parent.mkdir(parents=True, exist_ok=True)
        agent_target.mkdir(parents=True, exist_ok=True)
        live_previous = transaction / "live-previous"
        live_previous.mkdir(parents=True, exist_ok=True)
        switched = True
        if skill_target.exists() or skill_target.is_symlink():
            os.replace(skill_target, live_previous / "skill")
        os.replace(stage_skill, skill_target)
        maybe_fail("after_skill_switch")
        for name in affected_agents:
            target = agent_target / name
            if target.exists() or target.is_symlink():
                previous_agent = live_previous / "agents" / name
                previous_agent.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, previous_agent)
            staged_agent = stage_agents / name
            if staged_agent.is_file():
                os.replace(staged_agent, target)
        maybe_fail("after_agent_switch")
        validate_skill(skill_target, "post_switch")
        validate_package_tree(skill_target, "post_switch_validation")
        maybe_fail("post_switch_validation")
        state = state_payload(
            backup_id=backup_id,
            origin_backup_id=origin_backup_id,
            managed_agents=managed_agents,
            fallback_agents=fallback_agents,
        )
        atomic_json(current_state_path, state)
        write_report("installed", action, backup_id=backup_id)
        print(f"Goal Teams {action} completed from tracked allowlist; report {safe_report_path(report_path)}")
    except BaseException as exc:
        if switched and backup_dir is not None:
            try:
                restore_backup(backup_dir, restore_previous_state=True)
                validation_results.append({"phase": "automatic_rollback", "command": "byte-equivalent manifest verification", "exit_code": 0, "status": "passed"})
                error_code = str(exc).split(":", 1)[0] if isinstance(exc, InstallError) else type(exc).__name__
                write_report("failed_rolled_back", action, backup_id=backup_id, error_code=error_code)
            except BaseException as rollback_exc:
                rollback_code = str(rollback_exc).split(":", 1)[0] if isinstance(rollback_exc, InstallError) else type(rollback_exc).__name__
                write_report("rollback_failed", action, backup_id=backup_id, error_code=rollback_code)
                raise InstallError(f"E_AUTOMATIC_ROLLBACK:{rollback_exc}") from exc
        raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)


def handle_signal(signum: int, _frame: Any) -> None:
    raise InstallError(f"E_SIGNAL:{signum}")


for handled_signal in (signal.SIGINT, signal.SIGTERM):
    signal.signal(handled_signal, handle_signal)


try:
    acquire_install_lock()
    if args.rollback:
        lifecycle_action("rollback")
    elif args.uninstall:
        lifecycle_action("uninstall")
    else:
        install()
except InstallError as exc:
    if not report_path.exists():
        action = "rollback" if args.rollback else "uninstall" if args.uninstall else "install"
        try:
            write_report("failed", action, error_code=str(exc).split(":", 1)[0])
        except OSError:
            pass
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
except Exception as exc:
    action = "rollback" if args.rollback else "uninstall" if args.uninstall else "install"
    if not report_path.exists():
        try:
            write_report("failed", action, error_code="E_INTERNAL")
        except OSError:
            pass
    print(f"E_INTERNAL:{type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1)
finally:
    release_install_lock()
PY
