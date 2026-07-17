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
import contextlib
import ctypes
import datetime as dt
import errno
import hashlib
import importlib.util
import json
import os
try:
    import pwd
except ModuleNotFoundError:  # pragma: no cover - production installs are Unix-only
    pwd = None  # type: ignore[assignment]
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unicodedata
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
SOURCE_ROOT = ROOT
ARGS = sys.argv[2:]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VERSION_RE = re.compile(r"^V[0-9]+\.[0-9]+$")
TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+$")
RELEASE_SOURCE_KINDS = {"local_release_bundle", "github_release_asset"}
TAR_LIMITS = {
    "max_members": 2048,
    "max_path_bytes": 240,
    "max_single_file_bytes": 16 * 1024 * 1024,
    "max_total_uncompressed_bytes": 128 * 1024 * 1024,
    "max_compression_ratio": 100,
}


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
    parser.add_argument("--release-bundle", type=Path, help="install an exact four-asset, Gitless release bundle")
    parser.add_argument("--release-identity", type=Path, help="identity receipt binding the downloaded release assets")
    parsed = parser.parse_args(ARGS)
    if bool(parsed.release_bundle) != bool(parsed.release_identity):
        parser.error("--release-bundle and --release-identity must be provided together")
    if parsed.release_bundle and (parsed.rollback or parsed.uninstall or parsed.allow_dirty):
        parser.error("--release-bundle conflicts with --rollback, --uninstall, and --allow-dirty")
    return parsed


args = parse_args()
code_home_input = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
code_home = (
    Path(os.path.abspath(code_home_input))
    if args.release_bundle
    else code_home_input.resolve()
)
configured_code_home = code_home
skill_target = code_home / "skills" / "goal-teams"
agent_target = code_home / "agents"
state_dir = code_home / "state" / "goal-teams"
backup_root = state_dir / "backups"
preserved_root = state_dir / "preserved"
quarantine_root = state_dir / "quarantine"
report_root = state_dir / "reports"
current_state_path = state_dir / "current.json"
stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}-{uuid.uuid4().hex[:8]}"
report_path = Path(os.environ.get("INSTALL_REPORT", str(report_root / f"{stamp}.json"))).expanduser()
configured_report_path = report_path
manifest_path = ROOT / "scripts" / "install" / "package-manifest.txt"
validation_results: list[dict[str, Any]] = []
preserved_changes: list[dict[str, Any]] = []
retained_quarantines: list[dict[str, Any]] = []
package_files: list[dict[str, Any]] = []
generated_paths: set[str] = set()
backed_up_components: list[str] = []
source_info: dict[str, Any] = {
    "source_kind": "worktree",
    "repository": None,
    "release_tag": None,
    "release_id": None,
    "release_state": None,
    "release_assets": [],
    "release_asset_sha256": None,
    "release_identity_sha256": None,
    "bundle_tree_sha256": None,
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
    "git": {"required": not bool(args.release_bundle), "available": shutil.which("git") is not None},
    "pyyaml": {"required": False, "available": importlib.util.find_spec("yaml") is not None},
    "pillow": {"required": False, "available": importlib.util.find_spec("PIL") is not None},
}
install_lock_handle: Any = None
install_lock_directory: Path | None = None
release_bundle_preflight: dict[str, Any] | None = None
release_bundle_verified = False
production_target_anchor: Any = None
production_target_io_bound = False


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


def canonical_json_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


class ProductionTargetAnchor:
    """A passwd-home anchored directory capability for published installs.

    Every mutable directory is opened relative to an already-open parent with
    ``O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC``.  The descriptors stay open for the
    entire installation, so a rename/symlink swap of the pathname cannot
    redirect a later state, lock, report, or live-target mutation.
    """

    _DIR_FLAGS = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    _FILE_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    _UNSAFE_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH
    _DARWIN_RENAME_EXCL = 0x00000004
    _LINUX_RENAME_NOREPLACE = 0x00000001

    def __init__(self, home: Path, uid: int) -> None:
        self._noreplace_operation()
        if any(not hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")):
            raise InstallError("E_RELEASE_PRODUCTION_DIRFD_PLATFORM")
        if any(
            operation not in os.supports_dir_fd
            for operation in (
                os.open,
                os.mkdir,
                os.stat,
                os.unlink,
                os.rmdir,
                os.rename,
                os.readlink,
                os.symlink,
            )
        ) or not shutil.rmtree.avoids_symlink_attacks:
            raise InstallError("E_RELEASE_PRODUCTION_DIRFD_PLATFORM")
        self.home = home
        self.uid = uid
        self._fds: dict[tuple[str, ...], int] = {}
        self._identities: dict[tuple[str, ...], tuple[int, int]] = {}
        self._dynamic: dict[Path, tuple[int, tuple[int, int]]] = {}
        try:
            descriptor = os.open(home, self._DIR_FLAGS)
        except OSError as exc:
            raise InstallError("E_RELEASE_PRODUCTION_PASSWD_HOME") from exc
        try:
            identity = self._validate_directory_fd(descriptor, "home")
        except BaseException:
            os.close(descriptor)
            raise
        self._fds[()] = descriptor
        self._identities[()] = identity

    @staticmethod
    def _label(relative: tuple[str, ...]) -> str:
        return relative[-1] if relative else "home"

    def _validate_directory_fd(self, descriptor: int, label: str) -> tuple[int, int]:
        try:
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise InstallError(f"E_RELEASE_TARGET_METADATA:{label}") from exc
        if not stat.S_ISDIR(metadata.st_mode):
            raise InstallError(f"E_RELEASE_TARGET_TYPE:{label}")
        if metadata.st_uid != self.uid:
            raise InstallError(f"E_RELEASE_TARGET_OWNER:{label}")
        if metadata.st_nlink < 1:
            raise InstallError(f"E_RELEASE_TARGET_NLINK:{label}")
        if stat.S_IMODE(metadata.st_mode) & self._UNSAFE_WRITE_BITS:
            raise InstallError(f"E_RELEASE_TARGET_WRITABLE:{label}")
        return (metadata.st_dev, metadata.st_ino)

    def _open_child(self, parent_fd: int, name: str, label: str) -> int:
        try:
            return os.open(name, self._DIR_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise InstallError(f"E_RELEASE_TARGET_SYMLINK:{label}") from exc
            if exc.errno == errno.ENOTDIR:
                try:
                    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except OSError:
                    metadata = None
                if metadata is not None and stat.S_ISLNK(metadata.st_mode):
                    raise InstallError(f"E_RELEASE_TARGET_SYMLINK:{label}") from exc
                raise InstallError(f"E_RELEASE_TARGET_TYPE:{label}") from exc
            raise InstallError(f"E_RELEASE_TARGET_OPEN:{label}") from exc

    @classmethod
    def _noreplace_operation(cls) -> tuple[Any, int]:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            try:
                operation = libc.renameatx_np
            except AttributeError as exc:
                raise InstallError("E_RELEASE_PRODUCTION_NOREPLACE_PLATFORM") from exc
            flags = cls._DARWIN_RENAME_EXCL
        elif sys.platform.startswith("linux"):
            try:
                operation = libc.renameat2
            except AttributeError as exc:
                raise InstallError("E_RELEASE_PRODUCTION_NOREPLACE_PLATFORM") from exc
            flags = cls._LINUX_RENAME_NOREPLACE
        else:
            raise InstallError("E_RELEASE_PRODUCTION_NOREPLACE_PLATFORM")
        operation.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        operation.restype = ctypes.c_int
        return operation, flags

    @classmethod
    def _rename_noreplace(
        cls,
        source_name: str,
        destination_name: str,
        *,
        source_fd: int,
        destination_fd: int,
    ) -> None:
        """Atomically move one directory entry without ever replacing another.

        Published installs fail closed when the host kernel cannot provide the
        primitive.  A name-based existence check followed by ``rename`` is not
        an acceptable substitute because it reopens the overwrite race.
        """

        operation, flags = cls._noreplace_operation()
        ctypes.set_errno(0)
        result = operation(
            source_fd,
            os.fsencode(source_name),
            destination_fd,
            os.fsencode(destination_name),
            flags,
        )
        if result == 0:
            return
        observed_errno = ctypes.get_errno()
        if observed_errno in {errno.EEXIST, errno.ENOTEMPTY}:
            raise InstallError(f"E_RELEASE_TARGET_EXISTS:{destination_name}")
        if observed_errno == errno.ENOENT:
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{source_name}")
        if observed_errno == errno.EXDEV:
            raise InstallError("E_RELEASE_TARGET_RENAME_CROSS_DEVICE")
        unsupported = {
            errno.EINVAL,
            errno.ENOSYS,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if observed_errno in unsupported:
            raise InstallError("E_RELEASE_PRODUCTION_NOREPLACE_PLATFORM")
        raise InstallError(f"E_RELEASE_TARGET_RENAME:{source_name}")

    def _remember_or_compare(self, relative: tuple[str, ...], descriptor: int) -> None:
        try:
            identity = self._validate_directory_fd(descriptor, self._label(relative))
        except BaseException:
            os.close(descriptor)
            raise
        expected = self._identities.get(relative)
        if expected is not None:
            try:
                if identity != expected:
                    raise InstallError(f"E_RELEASE_TARGET_CHANGED:{self._label(relative)}")
            finally:
                os.close(descriptor)
            return
        self._fds[relative] = descriptor
        self._identities[relative] = identity

    def validate_existing(self, relative: tuple[str, ...]) -> None:
        cursor: tuple[str, ...] = ()
        for name in relative:
            child = cursor + (name,)
            parent_fd = self._fds[cursor]
            try:
                descriptor = self._open_child(parent_fd, name, self._label(child))
            except FileNotFoundError:
                return
            self._remember_or_compare(child, descriptor)
            cursor = child

    def ensure_dir(self, relative: tuple[str, ...]) -> int:
        cursor: tuple[str, ...] = ()
        for name in relative:
            child = cursor + (name,)
            if child not in self._fds:
                parent_fd = self._fds[cursor]
                try:
                    descriptor = self._open_child(parent_fd, name, self._label(child))
                except FileNotFoundError:
                    try:
                        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                    except OSError as exc:
                        raise InstallError(f"E_RELEASE_TARGET_MKDIR:{self._label(child)}") from exc
                    descriptor = self._open_child(parent_fd, name, self._label(child))
                self._remember_or_compare(child, descriptor)
            else:
                self._revalidate_one(child)
            cursor = child
        return self._fds[relative]

    def _revalidate_one(self, relative: tuple[str, ...]) -> None:
        if not relative:
            try:
                descriptor = os.open(self.home, self._DIR_FLAGS)
            except OSError as exc:
                raise InstallError("E_RELEASE_PRODUCTION_PASSWD_HOME") from exc
        else:
            parent = relative[:-1]
            descriptor = self._open_child(
                self._fds[parent], relative[-1], self._label(relative)
            )
        self._remember_or_compare(relative, descriptor)
        held_identity = self._validate_directory_fd(
            self._fds[relative], self._label(relative)
        )
        if held_identity != self._identities[relative]:
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{self._label(relative)}")

    def revalidate(self) -> None:
        for relative in sorted(self._fds, key=lambda value: (len(value), value)):
            self._revalidate_one(relative)
        for path, (held_fd, expected) in sorted(
            self._dynamic.items(), key=lambda item: (len(item[0].parts), str(item[0]))
        ):
            descriptor, owned = self._open_directory(path, exclude=path)
            try:
                observed = self._validate_directory_fd(descriptor, path.name)
                held = self._validate_directory_fd(held_fd, path.name)
                if observed != expected or held != expected:
                    raise InstallError(f"E_RELEASE_TARGET_CHANGED:{path.name}")
            finally:
                if owned:
                    os.close(descriptor)

    def fd(self, relative: tuple[str, ...]) -> int:
        try:
            return self._fds[relative]
        except KeyError as exc:
            raise InstallError(f"E_RELEASE_TARGET_FD:{self._label(relative)}") from exc

    def canonical_path(self, relative: tuple[str, ...]) -> Path:
        return self.home.joinpath(*relative)

    def _capabilities(self) -> list[tuple[Path, int]]:
        fixed = [
            (self.canonical_path(relative), descriptor)
            for relative, descriptor in self._fds.items()
        ]
        dynamic = [(path, value[0]) for path, value in self._dynamic.items()]
        return fixed + dynamic

    def _find_root(self, path: Path, *, exclude: Path | None = None) -> tuple[Path, int]:
        absolute = absolute_lexical(path)
        matches = [
            (root, descriptor)
            for root, descriptor in self._capabilities()
            if root != exclude and (absolute == root or path_within(absolute, root))
        ]
        if not matches:
            raise InstallError("E_RELEASE_TARGET_OUTSIDE")
        return max(matches, key=lambda item: len(item[0].parts))

    def _open_directory(
        self,
        path: Path,
        *,
        create: bool = False,
        pin: bool = False,
        exclude: Path | None = None,
    ) -> tuple[int, bool]:
        absolute = absolute_lexical(path)
        root, descriptor = self._find_root(absolute, exclude=exclude)
        relative = absolute.relative_to(root)
        owned = False
        for name in relative.parts:
            parent_fd = descriptor
            try:
                child_fd = self._open_child(parent_fd, name, name)
            except FileNotFoundError:
                if not create:
                    if owned:
                        os.close(descriptor)
                    raise
                try:
                    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    if owned:
                        os.close(descriptor)
                    raise InstallError(f"E_RELEASE_TARGET_MKDIR:{name}") from exc
                try:
                    child_fd = self._open_child(parent_fd, name, name)
                except BaseException:
                    if owned:
                        os.close(descriptor)
                    raise
            except BaseException:
                if owned:
                    os.close(descriptor)
                raise
            try:
                self._validate_directory_fd(child_fd, name)
            except BaseException:
                os.close(child_fd)
                if owned:
                    os.close(descriptor)
                raise
            if owned:
                os.close(descriptor)
            descriptor = child_fd
            owned = True
        if pin and absolute not in self._dynamic:
            if not owned:
                duplicate = os.dup(descriptor)
                try:
                    self._validate_directory_fd(duplicate, absolute.name)
                except BaseException:
                    os.close(duplicate)
                    raise
                descriptor = duplicate
            try:
                identity = self._validate_directory_fd(descriptor, absolute.name)
            except BaseException:
                os.close(descriptor)
                raise
            self._dynamic[absolute] = (descriptor, identity)
            return descriptor, False
        return descriptor, owned

    def _open_parent(
        self, path: Path, *, create_parents: bool = False
    ) -> tuple[int, str, bool]:
        absolute = absolute_lexical(path)
        if absolute.name in {"", ".", ".."}:
            raise InstallError("E_RELEASE_TARGET_NAME")
        descriptor, owned = self._open_directory(
            absolute.parent, create=create_parents
        )
        return descriptor, absolute.name, owned

    def mkdir_path(self, path: Path, *, pin: bool = False) -> Path:
        absolute = absolute_lexical(path)
        descriptor, owned = self._open_directory(absolute, create=True, pin=pin)
        if owned:
            os.close(descriptor)
        return absolute

    def create_dir(self, path: Path, *, pin: bool = False) -> Path:
        absolute = absolute_lexical(path)
        parent_fd, name, owned = self._open_parent(absolute)
        child_fd: int | None = None
        created = False
        try:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                created = True
            except FileExistsError as exc:
                raise InstallError(f"E_RELEASE_TARGET_EXISTS:{name}") from exc
            child_fd = self._open_child(parent_fd, name, name)
            try:
                identity = self._validate_directory_fd(child_fd, name)
            except BaseException:
                os.close(child_fd)
                child_fd = None
                raise
            if pin:
                self._dynamic[absolute] = (child_fd, identity)
                child_fd = None
            return absolute
        finally:
            if child_fd is not None:
                os.close(child_fd)
            if owned:
                os.close(parent_fd)

    def create_unique_dir(self, parent: Path, prefix: str) -> Path:
        parent_fd, owned = self._open_directory(parent)
        try:
            for _ in range(64):
                name = f"{prefix}{uuid.uuid4().hex}"
                try:
                    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    continue
                child_fd = self._open_child(parent_fd, name, name)
                try:
                    identity = self._validate_directory_fd(child_fd, name)
                except BaseException:
                    os.close(child_fd)
                    raise
                path = absolute_lexical(parent / name)
                self._dynamic[path] = (child_fd, identity)
                return path
            raise InstallError("E_RELEASE_TARGET_MKDIR_UNIQUE")
        finally:
            if owned:
                os.close(parent_fd)

    def unpin(self, path: Path) -> None:
        absolute = absolute_lexical(path)
        for candidate in sorted(
            [item for item in self._dynamic if item == absolute or path_within(item, absolute)],
            key=lambda value: len(value.parts),
            reverse=True,
        ):
            descriptor, _ = self._dynamic.pop(candidate)
            with contextlib.suppress(OSError):
                os.close(descriptor)

    def atomic_json(self, path: Path, payload: dict[str, Any]) -> None:
        absolute = absolute_lexical(path)
        parent_fd, name, owned = self._open_parent(absolute, create_parents=True)
        temporary = f".{name}.tmp-{stamp}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._FILE_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
            encoded = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            view = memoryview(encoded)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise InstallError("E_RELEASE_TARGET_WRITE")
                view = view[count:]
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self.uid
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) & self._UNSAFE_WRITE_BITS
            ):
                raise InstallError("E_RELEASE_TARGET_FILE_METADATA")
            temporary_identity = (metadata.st_dev, metadata.st_ino)
            self._commit_temporary_file(
                path=absolute,
                parent_fd=parent_fd,
                temporary=temporary,
                destination=name,
                temporary_identity=temporary_identity,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                self.remove_path(absolute.parent / temporary)
            finally:
                if owned:
                    os.close(parent_fd)

    def create_json_once(self, path: Path, payload: dict[str, Any]) -> None:
        """Atomically publish a terminal report exactly once."""

        absolute = absolute_lexical(path)
        parent_fd, name, owned = self._open_parent(absolute, create_parents=True)
        quarantine_fd: int | None = None
        quarantine_name = ""
        quarantine_identity: tuple[int, int] | None = None
        tombstone_ref = ""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._FILE_NOFOLLOW
        descriptor: int | None = None
        try:
            quarantine_name, quarantine_fd, quarantine_identity = (
                self._create_mutation_quarantine(parent_fd, name)
            )
            retained_name = self._retain_mutation_quarantine(
                parent_fd=parent_fd,
                name=quarantine_name,
                descriptor=quarantine_fd,
                identity=quarantine_identity,
                original_path=absolute,
                operation="terminal-report",
            )
            tombstone_ref = (
                Path(".codex/state/goal-teams/quarantine") / retained_name
            ).as_posix()
            receipt = retained_quarantines[-1]
            receipt_bytes = (
                json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            receipt_fd = os.open(
                "receipt.json",
                flags,
                0o600,
                dir_fd=quarantine_fd,
            )
            try:
                remaining_receipt = memoryview(receipt_bytes)
                while remaining_receipt:
                    count = os.write(receipt_fd, remaining_receipt)
                    if count <= 0:
                        raise InstallError("E_RELEASE_TARGET_WRITE")
                    remaining_receipt = remaining_receipt[count:]
                os.fsync(receipt_fd)
            finally:
                os.close(receipt_fd)
            descriptor = os.open("entry", flags, 0o600, dir_fd=quarantine_fd)
            encoded = (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            view = memoryview(encoded)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise InstallError("E_RELEASE_TARGET_WRITE")
                view = view[count:]
            os.fsync(descriptor)
            held = os.fstat(descriptor)
            observed = os.stat("entry", dir_fd=quarantine_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(held.st_mode)
                or held.st_uid != self.uid
                or held.st_nlink != 1
                or stat.S_IMODE(held.st_mode) & self._UNSAFE_WRITE_BITS
                or (held.st_dev, held.st_ino) != (observed.st_dev, observed.st_ino)
            ):
                raise InstallError(f"E_RELEASE_REPORT_CHANGED:{tombstone_ref}/entry")
            self._rename_noreplace(
                "entry",
                name,
                source_fd=quarantine_fd,
                destination_fd=parent_fd,
            )
            published = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (held.st_dev, held.st_ino) != (published.st_dev, published.st_ino):
                evacuated = False
                for _ in range(64):
                    conflict_name = f"conflict-{uuid.uuid4().hex}"
                    try:
                        self._rename_noreplace(
                            name,
                            conflict_name,
                            source_fd=parent_fd,
                            destination_fd=quarantine_fd,
                        )
                    except InstallError as exc:
                        message = str(exc)
                        if message.startswith(
                            f"E_RELEASE_TARGET_EXISTS:{conflict_name}"
                        ):
                            continue
                        if message.startswith(f"E_RELEASE_TARGET_CHANGED:{name}"):
                            evacuated = True
                            break
                        raise InstallError(
                            f"E_RELEASE_REPORT_FINAL_CONFLICT:{name}"
                        ) from exc
                    try:
                        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        evacuated = True
                        break
                if not evacuated:
                    raise InstallError(
                        f"E_RELEASE_REPORT_FINAL_CONFLICT:{name}"
                    )
                raise InstallError(f"E_RELEASE_REPORT_CHANGED:{name}")
        except InstallError as exc:
            if str(exc).startswith(f"E_RELEASE_TARGET_EXISTS:{name}"):
                raise InstallError(
                    f"E_RELEASE_REPORT_EXISTS:{name}:pending={tombstone_ref}/entry"
                ) from exc
            raise
        except OSError as exc:
            raise InstallError(
                f"E_RELEASE_REPORT_PENDING:{tombstone_ref}/entry:{type(exc).__name__}"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if quarantine_fd is not None:
                os.close(quarantine_fd)
            if owned:
                os.close(parent_fd)

    def atomic_bytes(self, path: Path, data: bytes, *, mode: int) -> None:
        absolute = absolute_lexical(path)
        parent_fd, name, owned = self._open_parent(absolute, create_parents=True)
        temporary = f".{name}.tmp-{stamp}-{uuid.uuid4().hex[:8]}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._FILE_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, mode, dir_fd=parent_fd)
            remaining = memoryview(data)
            while remaining:
                count = os.write(descriptor, remaining)
                if count <= 0:
                    raise InstallError("E_RELEASE_TARGET_WRITE")
                remaining = remaining[count:]
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != self.uid
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) & self._UNSAFE_WRITE_BITS
            ):
                raise InstallError("E_RELEASE_TARGET_FILE_METADATA")
            temporary_identity = (metadata.st_dev, metadata.st_ino)
            self._commit_temporary_file(
                path=absolute,
                parent_fd=parent_fd,
                temporary=temporary,
                destination=name,
                temporary_identity=temporary_identity,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                self.remove_path(absolute.parent / temporary)
            finally:
                if owned:
                    os.close(parent_fd)

    def open_lock(self) -> Any:
        state_relative = (".codex", "state", "goal-teams")
        state_fd = self.fd(state_relative)
        flags = os.O_RDWR | os.O_CREAT | self._FILE_NOFOLLOW
        try:
            descriptor = os.open("install.lock", flags, 0o600, dir_fd=state_fd)
        except OSError as exc:
            raise InstallError("E_RELEASE_INSTALL_LOCK_OPEN") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise InstallError("E_RELEASE_INSTALL_LOCK_TYPE")
            if metadata.st_uid != self.uid:
                raise InstallError("E_RELEASE_INSTALL_LOCK_OWNER")
            if metadata.st_nlink != 1:
                raise InstallError("E_RELEASE_INSTALL_LOCK_NLINK")
            if stat.S_IMODE(metadata.st_mode) & self._UNSAFE_WRITE_BITS:
                raise InstallError("E_RELEASE_INSTALL_LOCK_WRITABLE")
            return os.fdopen(descriptor, "r+", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise

    def read_optional_file(self, path: Path, *, max_bytes: int) -> bytes | None:
        parent_fd, name, owned = self._open_parent(path)
        flags = os.O_RDONLY | self._FILE_NOFOLLOW
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            if owned:
                os.close(parent_fd)
            return None
        except OSError as exc:
            if owned:
                os.close(parent_fd)
            raise InstallError(f"E_RELEASE_TARGET_FILE_OPEN:{name}") from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise InstallError(f"E_RELEASE_TARGET_FILE_TYPE:{name}")
            if before.st_uid != self.uid:
                raise InstallError(f"E_RELEASE_TARGET_FILE_OWNER:{name}")
            if before.st_nlink != 1:
                raise InstallError(f"E_RELEASE_TARGET_FILE_NLINK:{name}")
            if stat.S_IMODE(before.st_mode) & self._UNSAFE_WRITE_BITS:
                raise InstallError(f"E_RELEASE_TARGET_FILE_WRITABLE:{name}")
            if before.st_size > max_bytes:
                raise InstallError(f"E_RELEASE_TARGET_FILE_SIZE:{name}")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise InstallError(f"E_RELEASE_TARGET_FILE_SIZE:{name}")
            after = os.fstat(descriptor)
            if (
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            ):
                raise InstallError(f"E_RELEASE_TARGET_FILE_CHANGED:{name}")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
            if owned:
                os.close(parent_fd)

    def entry_exists_path(self, path: Path) -> bool:
        parent_fd, name, owned = self._open_parent(path)
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise InstallError(f"E_RELEASE_TARGET_METADATA:{name}") from exc
        finally:
            if owned:
                os.close(parent_fd)
        return True

    def _assert_pinned_entry(
        self,
        *,
        path: Path,
        parent_fd: int,
        name: str,
        binding: tuple[int, tuple[int, int]] | None = None,
        expected_identity: tuple[int, int] | None = None,
    ) -> os.stat_result:
        """Bind the pathname immediately adjacent to a destructive mutation."""

        absolute = absolute_lexical(path)
        current = self._dynamic.get(absolute) if binding is None else binding
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            if current is None:
                raise
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}") from exc
        except OSError as exc:
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}") from exc
        if current is None:
            if expected_identity is not None and (
                metadata.st_dev,
                metadata.st_ino,
            ) != expected_identity:
                raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}")
            return metadata
        held_fd, expected = current
        observed = (metadata.st_dev, metadata.st_ino)
        held = self._validate_directory_fd(held_fd, name)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != self.uid
            or stat.S_IMODE(metadata.st_mode) & self._UNSAFE_WRITE_BITS
            or observed != expected
            or (expected_identity is not None and observed != expected_identity)
            or held != expected
        ):
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}")
        return metadata

    def _create_mutation_quarantine(
        self, parent_fd: int, label: str
    ) -> tuple[str, int, tuple[int, int]]:
        for _ in range(64):
            name = f".{label}.mutation-{uuid.uuid4().hex}"
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            except OSError as exc:
                raise InstallError(f"E_RELEASE_TARGET_MKDIR:{label}") from exc
            try:
                descriptor = self._open_child(parent_fd, name, label)
                identity = self._validate_directory_fd(descriptor, label)
            except BaseException:
                raise
            return name, descriptor, identity
        raise InstallError(f"E_RELEASE_TARGET_MKDIR:{label}")

    def _retain_mutation_quarantine(
        self,
        *,
        parent_fd: int,
        name: str,
        descriptor: int,
        identity: tuple[int, int],
        original_path: Path,
        operation: str,
    ) -> str:
        """Move a mutation capsule to durable private quarantine.

        No automatic path deletes a capsule.  This intentionally trades a
        bounded local retention cost for a no-data-loss guarantee when a
        same-user process races the installer between validation and cleanup.
        """

        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}") from exc
        held = self._validate_directory_fd(descriptor, name)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != identity
            or held != identity
        ):
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}")
        quarantine_relative = (
            ".codex",
            "state",
            "goal-teams",
            "quarantine",
        )
        retention_fd = self.ensure_dir(quarantine_relative)
        destination_name = f"{stamp}-{operation}-{uuid.uuid4().hex}"
        self._rename_noreplace(
            name,
            destination_name,
            source_fd=parent_fd,
            destination_fd=retention_fd,
        )
        try:
            retained = os.stat(
                destination_name,
                dir_fd=retention_fd,
                follow_symlinks=False,
            )
            retained_identity = (retained.st_dev, retained.st_ino)
            held_after = self._validate_directory_fd(descriptor, destination_name)
            if (
                not stat.S_ISDIR(retained.st_mode)
                or retained_identity != identity
                or held_after != identity
            ):
                raise InstallError(
                    f"E_RELEASE_TARGET_CHANGED:{destination_name}"
                )
        except BaseException:
            with contextlib.suppress(InstallError):
                self._rename_noreplace(
                    destination_name,
                    name,
                    source_fd=retention_fd,
                    destination_fd=parent_fd,
                )
            raise
        try:
            original_ref = absolute_lexical(original_path).relative_to(self.home).as_posix()
        except ValueError:
            original_ref = "outside-home-rejected"
        retained_quarantines.append(
            {
                "operation": operation,
                "original_ref": original_ref,
                "tombstone_ref": (
                    Path(".codex/state/goal-teams/quarantine") / destination_name
                ).as_posix(),
                "device": identity[0],
                "inode": identity[1],
                "status": "retained_no_automatic_delete",
            }
        )
        return destination_name

    def _verify_moved_entry(
        self,
        *,
        parent_fd: int,
        name: str,
        expected_identity: tuple[int, int],
        binding: tuple[int, tuple[int, int]] | None,
        require_regular: bool = False,
    ) -> os.stat_result:
        try:
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}") from exc
        if (
            (metadata.st_dev, metadata.st_ino) != expected_identity
            or metadata.st_uid != self.uid
            or stat.S_IMODE(metadata.st_mode) & self._UNSAFE_WRITE_BITS
            or (require_regular and not stat.S_ISREG(metadata.st_mode))
            or (require_regular and metadata.st_nlink != 1)
        ):
            raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}")
        if binding is not None:
            held = self._validate_directory_fd(binding[0], name)
            if not stat.S_ISDIR(metadata.st_mode) or held != expected_identity:
                raise InstallError(f"E_RELEASE_TARGET_CHANGED:{name}")
        return metadata

    @staticmethod
    def _snapshot_parent_entry_names(
        parent_fd: int,
    ) -> dict[tuple[int, int], str]:
        snapshot: dict[tuple[int, int], str] = {}
        for child in os.listdir(parent_fd):
            try:
                metadata = os.stat(
                    child,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(metadata.st_mode) or metadata.st_nlink == 1:
                snapshot[(metadata.st_dev, metadata.st_ino)] = child
        return snapshot

    def _restore_known_quarantine_entries(
        self,
        *,
        quarantine_fd: int,
        parent_fd: int,
        expected_identity: tuple[int, int],
        original_name: str,
        known_names: dict[tuple[int, int], str],
    ) -> None:
        """Best-effort reversible recovery without replacing any live name."""

        restore_names = dict(known_names)
        restore_names[expected_identity] = original_name
        for child in sorted(os.listdir(quarantine_fd)):
            try:
                metadata = os.stat(
                    child,
                    dir_fd=quarantine_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            destination = restore_names.get((metadata.st_dev, metadata.st_ino))
            if destination is None:
                continue
            try:
                self._rename_noreplace(
                    child,
                    destination,
                    source_fd=quarantine_fd,
                    destination_fd=parent_fd,
                )
            except InstallError:
                # A conflicting live name is never overwritten; the entry
                # remains in the durable tombstone retained by the caller.
                continue

    def _commit_temporary_file(
        self,
        *,
        path: Path,
        parent_fd: int,
        temporary: str,
        destination: str,
        temporary_identity: tuple[int, int],
    ) -> None:
        """Commit one held temporary file with no overwrite race."""

        quarantine_fd: int | None = None
        quarantine_name = ""
        quarantine_identity: tuple[int, int] | None = None
        previous_location = "absent"
        temporary_location = "temporary"
        try:
            try:
                previous = os.stat(
                    destination,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                previous = None
            if previous is not None:
                previous_identity = (previous.st_dev, previous.st_ino)
                if (
                    not stat.S_ISREG(previous.st_mode)
                    or previous.st_uid != self.uid
                    or previous.st_nlink != 1
                    or stat.S_IMODE(previous.st_mode) & self._UNSAFE_WRITE_BITS
                ):
                    raise InstallError(
                        f"E_RELEASE_TARGET_FILE_CHANGED:{destination}"
                    )
                quarantine_name, quarantine_fd, quarantine_identity = (
                    self._create_mutation_quarantine(parent_fd, destination)
                )
                self._rename_noreplace(
                    destination,
                    "entry",
                    source_fd=parent_fd,
                    destination_fd=quarantine_fd,
                )
                previous_location = "quarantine"
                try:
                    self._verify_moved_entry(
                        parent_fd=quarantine_fd,
                        name="entry",
                        expected_identity=previous_identity,
                        binding=None,
                        require_regular=True,
                    )
                except BaseException:
                    self._rename_noreplace(
                        "entry",
                        destination,
                        source_fd=quarantine_fd,
                        destination_fd=parent_fd,
                    )
                    previous_location = "destination"
                    raise
            try:
                self._rename_noreplace(
                    temporary,
                    destination,
                    source_fd=parent_fd,
                    destination_fd=parent_fd,
                )
                temporary_location = "destination"
            except BaseException as commit_exc:
                if previous_location == "quarantine":
                    try:
                        self._rename_noreplace(
                            "entry",
                            destination,
                            source_fd=quarantine_fd,
                            destination_fd=parent_fd,
                        )
                        previous_location = "destination"
                    except InstallError as restore_exc:
                        raise InstallError(
                            f"E_RELEASE_TARGET_RESTORE_CONFLICT:{destination}"
                        ) from restore_exc
                raise commit_exc
            try:
                self._verify_moved_entry(
                    parent_fd=parent_fd,
                    name=destination,
                    expected_identity=temporary_identity,
                    binding=None,
                    require_regular=True,
                )
            except BaseException as verify_exc:
                try:
                    self._rename_noreplace(
                        destination,
                        temporary,
                        source_fd=parent_fd,
                        destination_fd=parent_fd,
                    )
                    temporary_location = "temporary"
                except InstallError as restore_temp_exc:
                    raise InstallError(
                        f"E_RELEASE_TARGET_RESTORE_CONFLICT:{destination}"
                    ) from restore_temp_exc
                if previous_location == "quarantine":
                    try:
                        self._rename_noreplace(
                            "entry",
                            destination,
                            source_fd=quarantine_fd,
                            destination_fd=parent_fd,
                        )
                        previous_location = "destination"
                    except InstallError as restore_previous_exc:
                        raise InstallError(
                            f"E_RELEASE_TARGET_RESTORE_CONFLICT:{destination}"
                        ) from restore_previous_exc
                raise verify_exc
        finally:
            if quarantine_fd is not None and quarantine_identity is not None:
                try:
                    self._retain_mutation_quarantine(
                        parent_fd=parent_fd,
                        name=quarantine_name,
                        descriptor=quarantine_fd,
                        identity=quarantine_identity,
                        original_path=path,
                        operation=f"write-{previous_location}-{temporary_location}",
                    )
                finally:
                    os.close(quarantine_fd)

    def replace_path(self, source: Path, destination: Path) -> None:
        self.revalidate()
        source_absolute = absolute_lexical(source)
        source_binding = self._dynamic.get(source_absolute)
        source_fd, source_name, source_owned = self._open_parent(source)
        destination_fd: int | None = None
        destination_owned = False
        quarantine_fd: int | None = None
        quarantine_name = ""
        quarantine_identity: tuple[int, int] | None = None
        entry_location = "source"
        try:
            destination_fd, destination_name, destination_owned = self._open_parent(
                destination, create_parents=True
            )
            source_metadata = self._assert_pinned_entry(
                path=source_absolute,
                parent_fd=source_fd,
                name=source_name,
                binding=source_binding,
            )
            source_identity = (source_metadata.st_dev, source_metadata.st_ino)
            try:
                os.stat(destination_name, dir_fd=destination_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise InstallError(f"E_RELEASE_TARGET_EXISTS:{destination_name}")
            quarantine_name, quarantine_fd, quarantine_identity = (
                self._create_mutation_quarantine(source_fd, source_name)
            )
            self._rename_noreplace(
                source_name,
                "entry",
                source_fd=source_fd,
                destination_fd=quarantine_fd,
            )
            entry_location = "quarantine"
            try:
                self._verify_moved_entry(
                    parent_fd=quarantine_fd,
                    name="entry",
                    binding=source_binding,
                    expected_identity=source_identity,
                )
            except BaseException:
                self._rename_noreplace(
                    "entry",
                    source_name,
                    source_fd=quarantine_fd,
                    destination_fd=source_fd,
                )
                entry_location = "source"
                raise
            try:
                self._rename_noreplace(
                    "entry",
                    destination_name,
                    source_fd=quarantine_fd,
                    destination_fd=destination_fd,
                )
                entry_location = "destination"
            except BaseException:
                self._rename_noreplace(
                    "entry",
                    source_name,
                    source_fd=quarantine_fd,
                    destination_fd=source_fd,
                )
                entry_location = "source"
                raise
            try:
                self._verify_moved_entry(
                    parent_fd=destination_fd,
                    name=destination_name,
                    binding=source_binding,
                    expected_identity=source_identity,
                )
            except BaseException:
                self._rename_noreplace(
                    destination_name,
                    "entry",
                    source_fd=destination_fd,
                    destination_fd=quarantine_fd,
                )
                entry_location = "quarantine"
                self._rename_noreplace(
                    "entry",
                    source_name,
                    source_fd=quarantine_fd,
                    destination_fd=source_fd,
                )
                entry_location = "source"
                raise
            if source_binding is not None:
                self.unpin(source_absolute)
        finally:
            try:
                if quarantine_fd is not None and quarantine_identity is not None:
                    self._retain_mutation_quarantine(
                        parent_fd=source_fd,
                        name=quarantine_name,
                        descriptor=quarantine_fd,
                        identity=quarantine_identity,
                        original_path=source_absolute,
                        operation=f"replace-{entry_location}",
                    )
            finally:
                if quarantine_fd is not None:
                    os.close(quarantine_fd)
                if source_owned:
                    os.close(source_fd)
                if destination_fd is not None and destination_owned:
                    os.close(destination_fd)
        self.revalidate()

    def unlink_path(self, path: Path, *, missing_ok: bool = False) -> None:
        if not missing_ok and not self.entry_exists_path(path):
            raise FileNotFoundError(str(path))
        self.remove_path(path)

    def remove_path(self, path: Path) -> None:
        absolute = absolute_lexical(path)
        binding = self._dynamic.get(absolute)
        parent_fd, name, owned = self._open_parent(absolute)
        quarantine_fd: int | None = None
        quarantine_name = ""
        quarantine_identity: tuple[int, int] | None = None
        entry_location = "source"
        try:
            try:
                metadata = self._assert_pinned_entry(
                    path=absolute,
                    parent_fd=parent_fd,
                    name=name,
                    binding=binding,
                )
            except FileNotFoundError:
                return
            expected_identity = (metadata.st_dev, metadata.st_ino)
            known_names = self._snapshot_parent_entry_names(parent_fd)
            quarantine_name, quarantine_fd, quarantine_identity = (
                self._create_mutation_quarantine(parent_fd, name)
            )
            self._rename_noreplace(
                name,
                "entry",
                source_fd=parent_fd,
                destination_fd=quarantine_fd,
            )
            entry_location = "quarantine"
            try:
                self._assert_pinned_entry(
                    path=absolute,
                    parent_fd=quarantine_fd,
                    name="entry",
                    binding=binding,
                    expected_identity=expected_identity,
                )
                self._verify_moved_entry(
                    parent_fd=quarantine_fd,
                    name="entry",
                    binding=binding,
                    expected_identity=expected_identity,
                )
            except BaseException:
                self._restore_known_quarantine_entries(
                    quarantine_fd=quarantine_fd,
                    parent_fd=parent_fd,
                    expected_identity=expected_identity,
                    original_name=name,
                    known_names=known_names,
                )
                if not os.listdir(quarantine_fd):
                    entry_location = "source"
                raise
            self.unpin(absolute)
        finally:
            try:
                if quarantine_fd is not None and quarantine_identity is not None:
                    self._retain_mutation_quarantine(
                        parent_fd=parent_fd,
                        name=quarantine_name,
                        descriptor=quarantine_fd,
                        identity=quarantine_identity,
                        original_path=absolute,
                        operation=f"remove-{entry_location}",
                    )
            finally:
                if quarantine_fd is not None:
                    os.close(quarantine_fd)
                if owned:
                    os.close(parent_fd)

    def copy_path(self, source: Path, destination: Path) -> None:
        source_fd, source_name, source_owned = self._open_parent(source)
        destination_fd: int | None = None
        destination_name = ""
        destination_owned = False
        try:
            destination_fd, destination_name, destination_owned = self._open_parent(
                destination, create_parents=True
            )
            self._copy_entry(source_fd, source_name, destination_fd, destination_name)
        finally:
            if source_owned:
                os.close(source_fd)
            if destination_fd is not None and destination_owned:
                os.close(destination_fd)

    def _copy_entry(
        self, source_parent: int, source_name: str, destination_parent: int, destination_name: str
    ) -> None:
        metadata = os.stat(source_name, dir_fd=source_parent, follow_symlinks=False)
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            link = os.readlink(source_name, dir_fd=source_parent)
            os.symlink(link, destination_name, dir_fd=destination_parent)
            return
        if stat.S_ISREG(metadata.st_mode):
            source_fd = os.open(
                source_name, os.O_RDONLY | self._FILE_NOFOLLOW, dir_fd=source_parent
            )
            destination_fd: int | None = None
            try:
                opened = os.fstat(source_fd)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
                ):
                    raise InstallError(f"E_RELEASE_TARGET_FILE_CHANGED:{source_name}")
                destination_fd = os.open(
                    destination_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._FILE_NOFOLLOW,
                    mode,
                    dir_fd=destination_parent,
                )
                while True:
                    chunk = os.read(source_fd, 1024 * 1024)
                    if not chunk:
                        break
                    remaining = memoryview(chunk)
                    while remaining:
                        count = os.write(destination_fd, remaining)
                        if count <= 0:
                            raise InstallError("E_RELEASE_TARGET_WRITE")
                        remaining = remaining[count:]
                os.fchmod(destination_fd, mode)
            finally:
                os.close(source_fd)
                if destination_fd is not None:
                    os.close(destination_fd)
            return
        if not stat.S_ISDIR(metadata.st_mode):
            raise InstallError(f"E_RELEASE_TARGET_TYPE:{source_name}")
        os.mkdir(destination_name, mode=mode, dir_fd=destination_parent)
        source_fd = self._open_child(source_parent, source_name, source_name)
        destination_fd: int | None = None
        try:
            destination_fd = self._open_child(
                destination_parent, destination_name, destination_name
            )
            self._validate_directory_fd(source_fd, source_name)
            self._validate_directory_fd(destination_fd, destination_name)
            for child in sorted(os.listdir(source_fd)):
                self._copy_entry(source_fd, child, destination_fd, child)
        finally:
            os.close(source_fd)
            if destination_fd is not None:
                os.close(destination_fd)

    def close(self) -> None:
        self.unpin(self.home)
        for descriptor in reversed(list(self._fds.values())):
            with contextlib.suppress(OSError):
                os.close(descriptor)
        self._fds.clear()
        self._identities.clear()


def validate_no_symlink_ancestors(path: Path, error_code: str) -> Path:
    """Reject symlinks without resolving away the evidence first."""

    absolute = absolute_lexical(path)
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise InstallError(error_code) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError(f"{error_code}:{cursor.name}")
    return absolute


def validate_owned_existing_ancestors(path: Path, home: Path, owner_uid: int) -> Path:
    """Validate existing target ancestors from the passwd home downward."""

    safe_home = validate_no_symlink_ancestors(home, "E_RELEASE_PRODUCTION_HOME_SYMLINK")
    absolute = validate_no_symlink_ancestors(path, "E_RELEASE_TARGET_SYMLINK")
    if absolute != safe_home and not path_within(absolute, safe_home):
        raise InstallError("E_RELEASE_TARGET_OUTSIDE")
    try:
        relative = absolute.relative_to(safe_home)
    except ValueError as exc:  # Defensive duplicate of the lexical boundary above.
        raise InstallError("E_RELEASE_TARGET_OUTSIDE") from exc
    cursor = safe_home
    checkpoints = [safe_home]
    for part in relative.parts:
        cursor = cursor / part
        checkpoints.append(cursor)
    for index, candidate in enumerate(checkpoints):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise InstallError("E_RELEASE_TARGET_METADATA") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError(f"E_RELEASE_TARGET_SYMLINK:{candidate.name}")
        if metadata.st_uid != owner_uid:
            raise InstallError(f"E_RELEASE_TARGET_OWNER:{candidate.name}")
        if index < len(checkpoints) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise InstallError(f"E_RELEASE_TARGET_TYPE:{candidate.name}")
    return absolute


def validate_production_release_target(identity: dict[str, Any]) -> None:
    """Bind a published GitHub asset install to the real login home.

    Local release-bundle rehearsals intentionally keep their explicit temporary
    ``CODEX_HOME`` path.  A published release is different: neither HOME nor
    CODEX_HOME is authority.  The passwd database and real uid are the trust
    root, and every existing target ancestor below that home must remain owned
    by the same uid and free of symlinks before the installer may mutate it.
    """

    global production_target_anchor
    if identity.get("source_kind") != "github_release_asset":
        return
    if pwd is None or not hasattr(os, "getuid") or not hasattr(os, "geteuid"):
        raise InstallError("E_RELEASE_PRODUCTION_PLATFORM")
    uid = os.getuid()
    if uid != os.geteuid():
        raise InstallError("E_RELEASE_PRODUCTION_EUID")
    if "SUDO_UID" in os.environ or "SUDO_USER" in os.environ:
        raise InstallError("E_RELEASE_PRODUCTION_SUDO")
    try:
        account = pwd.getpwuid(uid)
    except (KeyError, OSError) as exc:
        raise InstallError("E_RELEASE_PRODUCTION_PASSWD_HOME") from exc
    raw_home = getattr(account, "pw_dir", None)
    if not isinstance(raw_home, str) or not raw_home:
        raise InstallError("E_RELEASE_PRODUCTION_PASSWD_HOME")
    passwd_home = Path(raw_home)
    if not passwd_home.is_absolute() or raw_home != str(absolute_lexical(passwd_home)):
        raise InstallError("E_RELEASE_PRODUCTION_PASSWD_HOME")
    if os.environ.get("HOME") != raw_home:
        raise InstallError("E_RELEASE_PRODUCTION_HOME")
    canonical_code_home = passwd_home / ".codex"
    if (
        os.environ.get("CODEX_HOME") != str(canonical_code_home)
        or configured_code_home != canonical_code_home
    ):
        raise InstallError("E_RELEASE_PRODUCTION_CODEX_HOME")
    if production_target_anchor is None:
        production_target_anchor = ProductionTargetAnchor(passwd_home, uid)
    elif production_target_anchor.home != passwd_home or production_target_anchor.uid != uid:
        raise InstallError("E_RELEASE_PRODUCTION_ANCHOR_IDENTITY")
    production_target_anchor.revalidate()
    for relative in (
        (".codex",),
        (".codex", "skills"),
        (".codex", "agents"),
        (".codex", "state"),
        (".codex", "state", "goal-teams"),
        (".codex", "state", "goal-teams", "backups"),
        (".codex", "state", "goal-teams", "preserved"),
        (".codex", "state", "goal-teams", "quarantine"),
        (".codex", "state", "goal-teams", "reports"),
    ):
        production_target_anchor.validate_existing(relative)
    production_target_anchor.revalidate()


def bind_production_target_io() -> None:
    """Create and pin every published-install mutable parent with mkdirat."""

    global production_target_io_bound
    if production_target_anchor is None:
        return
    required = (
        (".codex",),
        (".codex", "skills"),
        (".codex", "agents"),
        (".codex", "state"),
        (".codex", "state", "goal-teams"),
        (".codex", "state", "goal-teams", "backups"),
        (".codex", "state", "goal-teams", "preserved"),
        (".codex", "state", "goal-teams", "quarantine"),
        (".codex", "state", "goal-teams", "reports"),
    )
    for relative in required:
        production_target_anchor.ensure_dir(relative)
    production_target_anchor.revalidate()
    try:
        configured_report_relative = absolute_lexical(configured_report_path).relative_to(
            configured_code_home
        )
    except ValueError as exc:
        raise InstallError("E_RELEASE_CUSTOM_REPORT_OUTSIDE") from exc
    expected_prefix = ("state", "goal-teams", "reports")
    if configured_report_relative.parts[:3] != expected_prefix:
        raise InstallError("E_RELEASE_CUSTOM_REPORT_OUTSIDE")
    production_target_io_bound = True


def validate_release_runtime_boundary() -> None:
    global report_path
    if not args.release_bundle:
        return
    if production_target_anchor is not None:
        production_target_anchor.revalidate()
        if "INSTALL_REPORT" in os.environ:
            if os.environ.get("GOAL_TEAMS_INSTALL_TEST_VALIDATION") != "1":
                raise InstallError("E_RELEASE_CUSTOM_REPORT_FORBIDDEN")
            custom = absolute_lexical(configured_report_path)
            canonical_report_root = configured_code_home / "state" / "goal-teams" / "reports"
            if not path_within(custom, canonical_report_root):
                raise InstallError("E_RELEASE_CUSTOM_REPORT_OUTSIDE")
        return
    safe_home = validate_no_symlink_ancestors(code_home, "E_RELEASE_TARGET_SYMLINK")
    if safe_home == Path(safe_home.anchor):
        raise InstallError("E_RELEASE_TARGET_ROOT")
    for target in (
        skill_target,
        agent_target,
        state_dir,
        backup_root,
        preserved_root,
        quarantine_root,
        report_root,
        current_state_path,
        state_dir / "install.lock",
        state_dir / "install.lock.d",
    ):
        absolute = validate_no_symlink_ancestors(target, "E_RELEASE_TARGET_SYMLINK")
        if not path_within(absolute, safe_home):
            raise InstallError("E_RELEASE_TARGET_OUTSIDE")
    if "INSTALL_REPORT" in os.environ:
        if os.environ.get("GOAL_TEAMS_INSTALL_TEST_VALIDATION") != "1":
            raise InstallError("E_RELEASE_CUSTOM_REPORT_FORBIDDEN")
        report_path = absolute_lexical(report_path)
        validate_no_symlink_ancestors(report_path, "E_RELEASE_TARGET_SYMLINK")
        if not path_within(report_path, safe_home):
            raise InstallError("E_RELEASE_CUSTOM_REPORT_OUTSIDE")
    else:
        report_path = report_root / f"{stamp}.json"


def stable_file_record(path: Path, *, max_bytes: int | None = None) -> dict[str, Any]:
    absolute = validate_no_symlink_ancestors(path, "E_RELEASE_ASSET_SYMLINK")
    try:
        before = absolute.lstat()
    except OSError as exc:
        raise InstallError(f"E_RELEASE_ASSET_MISSING:{absolute.name}") from exc
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise InstallError(f"E_RELEASE_ASSET_TYPE:{absolute.name}")
    if max_bytes is not None and before.st_size > max_bytes:
        raise InstallError(f"E_RELEASE_ASSET_SIZE:{absolute.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as exc:
        raise InstallError(f"E_RELEASE_ASSET_OPEN:{absolute.name}") from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_size != before.st_size
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
        ):
            raise InstallError(f"E_RELEASE_ASSET_CHANGED:{absolute.name}")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
        ):
            raise InstallError(f"E_RELEASE_ASSET_CHANGED:{absolute.name}")
    finally:
        os.close(descriptor)
    return {
        "path": absolute,
        "name": absolute.name,
        "sha256": digest.hexdigest(),
        "size": before.st_size,
        "device": before.st_dev,
        "inode": before.st_ino,
        "mtime_ns": before.st_mtime_ns,
    }


def read_stable_bytes(path: Path, *, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    record = stable_file_record(path, max_bytes=max_bytes)
    with verified_asset_handle(record) as handle:
        data = handle.read()
    return data, record


def require_json_object(data: bytes, error_code: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(error_code) from exc
    if not isinstance(payload, dict):
        raise InstallError(error_code)
    return payload


def normalize_release_relative(raw: str, error_code: str) -> str:
    if not isinstance(raw, str):
        raise InstallError(error_code)
    normalized = unicodedata.normalize("NFC", raw)
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized != raw
        or "\x00" in normalized
        or "\\" in normalized
        or normalized.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != normalized
    ):
        raise InstallError(f"{error_code}:{raw}")
    return path.as_posix()


def parse_release_identity(data: bytes) -> dict[str, Any]:
    payload = require_json_object(data, "E_RELEASE_IDENTITY_JSON")
    source_kind = payload.get("source_kind")
    repository = payload.get("repository")
    version = payload.get("version")
    tag = payload.get("release_tag", payload.get("tag"))
    if payload.get("release_tag") and payload.get("tag") and payload["release_tag"] != payload["tag"]:
        raise InstallError("E_RELEASE_IDENTITY_TAG")
    release_id = payload.get("release_id")
    release_state = payload.get("release_state")
    source_commit = payload.get("source_commit")
    source_git_tree_id = payload.get("source_git_tree_id")
    if source_kind not in RELEASE_SOURCE_KINDS:
        raise InstallError("E_RELEASE_IDENTITY_SOURCE_KIND")
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise InstallError("E_RELEASE_IDENTITY_REPOSITORY")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise InstallError("E_RELEASE_IDENTITY_VERSION")
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag) or tag != f"v{version[1:]}":
        raise InstallError("E_RELEASE_IDENTITY_TAG")
    if not isinstance(source_commit, str) or not GIT_SHA_RE.fullmatch(source_commit):
        raise InstallError("E_RELEASE_IDENTITY_COMMIT")
    if not isinstance(source_git_tree_id, str) or not GIT_SHA_RE.fullmatch(source_git_tree_id):
        raise InstallError("E_RELEASE_IDENTITY_TREE")
    if source_kind == "github_release_asset":
        if release_state != "published":
            raise InstallError("E_RELEASE_IDENTITY_NOT_PUBLISHED")
        if not isinstance(release_id, int) or isinstance(release_id, bool) or release_id < 1:
            raise InstallError("E_RELEASE_IDENTITY_RELEASE_ID")
    else:
        if release_state not in {"local", "draft", "rehearsal"}:
            raise InstallError("E_RELEASE_IDENTITY_REHEARSAL_STATE")
        if not ((isinstance(release_id, int) and not isinstance(release_id, bool) and release_id >= 0) or (isinstance(release_id, str) and release_id)):
            raise InstallError("E_RELEASE_IDENTITY_RELEASE_ID")
        if os.environ.get("GOAL_TEAMS_RELEASE_REHEARSAL") != "1" or "CODEX_HOME" not in os.environ:
            raise InstallError("E_RELEASE_REHEARSAL_ONLY")
    raw_assets = payload.get("assets")
    normalized_assets: dict[str, dict[str, Any]] = {}
    if isinstance(raw_assets, dict):
        iterable = []
        for name, value in raw_assets.items():
            if not isinstance(value, dict):
                raise InstallError("E_RELEASE_IDENTITY_ASSETS")
            iterable.append({"name": name, **value})
    elif isinstance(raw_assets, list):
        iterable = raw_assets
    else:
        raise InstallError("E_RELEASE_IDENTITY_ASSETS")
    for value in iterable:
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            raise InstallError("E_RELEASE_IDENTITY_ASSETS")
        name = value["name"]
        if Path(name).name != name or name in normalized_assets:
            raise InstallError("E_RELEASE_IDENTITY_ASSETS")
        digest = value.get("sha256")
        downloaded = value.get("download_sha256")
        size = value.get("size")
        asset_id = value.get("asset_id")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise InstallError(f"E_RELEASE_IDENTITY_ASSET_HASH:{name}")
        if not isinstance(downloaded, str) or downloaded != digest:
            raise InstallError(f"E_RELEASE_IDENTITY_DOWNLOAD_HASH:{name}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise InstallError(f"E_RELEASE_IDENTITY_ASSET_SIZE:{name}")
        if source_kind == "github_release_asset":
            if not isinstance(asset_id, int) or isinstance(asset_id, bool) or asset_id < 1:
                raise InstallError(f"E_RELEASE_IDENTITY_ASSET_ID:{name}")
        elif asset_id is not None and not (
            (isinstance(asset_id, int) and not isinstance(asset_id, bool) and asset_id >= 0)
            or (isinstance(asset_id, str) and asset_id)
        ):
            raise InstallError(f"E_RELEASE_IDENTITY_ASSET_ID:{name}")
        normalized_assets[name] = {
            "name": name,
            "asset_id": asset_id,
            "size": size,
            "sha256": digest,
            "download_sha256": downloaded,
        }
    return {
        "source_kind": source_kind,
        "repository": repository,
        "version": version,
        "release_tag": tag,
        "release_id": release_id,
        "release_state": release_state,
        "source_commit": source_commit,
        "source_git_tree_id": source_git_tree_id,
        "assets": normalized_assets,
    }


def parse_release_file_manifest(data: bytes, version: str) -> dict[str, dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise InstallError("E_RELEASE_FILES_CANONICAL")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise InstallError("E_RELEASE_FILES_ENCODING") from exc
    entries: dict[str, dict[str, Any]] = {}
    collision_keys: set[str] = set()
    previous_path: str | None = None
    for number, line in enumerate(lines, start=1):
        if not line:
            raise InstallError(f"E_RELEASE_FILES_ROW:{number}")
        if "\t" in line:
            fields = line.split("\t", 3)
            if len(fields) != 4:
                raise InstallError(f"E_RELEASE_FILES_ROW:{number}")
            digest, git_mode, size_raw, raw_path = fields
            if git_mode not in {"100644", "100755"}:
                raise InstallError(f"E_RELEASE_FILES_MODE:{number}")
            try:
                size = int(size_raw)
            except ValueError as exc:
                raise InstallError(f"E_RELEASE_FILES_SIZE:{number}") from exc
            if size < 0:
                raise InstallError(f"E_RELEASE_FILES_SIZE:{number}")
        else:
            if version == "V2.40" or "  " not in line:
                raise InstallError(f"E_RELEASE_FILES_EXTENDED_REQUIRED:{number}")
            digest, raw_path = line.split("  ", 1)
            git_mode = "100644"
            size = -1
        if not SHA256_RE.fullmatch(digest):
            raise InstallError(f"E_RELEASE_FILES_HASH:{number}")
        relative = normalize_release_relative(raw_path, "E_RELEASE_FILES_PATH")
        collision = relative.casefold()
        if relative in entries or collision in collision_keys:
            raise InstallError(f"E_RELEASE_FILES_DUPLICATE:{relative}")
        if previous_path is not None and relative <= previous_path:
            raise InstallError("E_RELEASE_FILES_ORDER")
        previous_path = relative
        collision_keys.add(collision)
        entries[relative] = {
            "path": relative,
            "sha256": digest,
            "size": size,
            "git_mode": git_mode,
            "mode": 0o755 if git_mode == "100755" else 0o644,
        }
    if not entries:
        raise InstallError("E_RELEASE_FILES_EMPTY")
    return entries


def validate_release_record(
    payload: dict[str, Any], identity: dict[str, Any], files: dict[str, dict[str, Any]]
) -> None:
    version = identity["version"]
    if (
        payload.get("schema_version") != "goal-teams-release-snapshot-v2.40"
        or
        payload.get("version") != version
        or payload.get("source_commit") != identity["source_commit"]
        or payload.get("source_git_tree_id") != identity["source_git_tree_id"]
        or payload.get("identity_authority") != "source_commit"
        or payload.get("sealed") is not True
    ):
        raise InstallError("E_RELEASE_RECORD_IDENTITY")
    manifest_sha = payload.get("source_package_manifest_sha256")
    tree_sha = payload.get("tree_sha256")
    if not isinstance(manifest_sha, str) or not SHA256_RE.fullmatch(manifest_sha):
        raise InstallError("E_RELEASE_RECORD_MANIFEST")
    if not isinstance(tree_sha, str) or not SHA256_RE.fullmatch(tree_sha):
        raise InstallError("E_RELEASE_RECORD_TREE")
    if payload.get("file_count") != len(files) or payload.get("total_bytes") != sum(
        entry["size"] for entry in files.values()
    ):
        raise InstallError("E_RELEASE_RECORD_COUNTS")
    digest_input = b"".join(
        f"{entry['path']}\0{entry['git_mode']}\0{entry['size']}\0{entry['sha256']}\n".encode("utf-8")
        for entry in files.values()
    )
    if sha256_bytes(digest_input) != tree_sha:
        raise InstallError("E_RELEASE_RECORD_TREE")
    artifact = payload.get("artifact")
    expected_name = f"goal-teams-{version}.tar.gz"
    if not isinstance(artifact, dict) or artifact.get("path") != f"_artifacts/{expected_name}":
        raise InstallError("E_RELEASE_RECORD_ARTIFACT")
    if not isinstance(artifact.get("sha256"), str) or not SHA256_RE.fullmatch(artifact["sha256"]):
        raise InstallError("E_RELEASE_RECORD_ARTIFACT")
    if not isinstance(artifact.get("size"), int) or artifact["size"] < 1:
        raise InstallError("E_RELEASE_RECORD_ARTIFACT")
    generated = payload.get("builder_generated_files")
    okf = files.get(OKF_GENERATED_PATH)
    if not isinstance(generated, list) or len(generated) != 1 or okf is None:
        raise InstallError("E_RELEASE_RECORD_OKF")
    generated_row = generated[0]
    if not isinstance(generated_row, dict) or any(
        generated_row.get(field) != okf.get(field)
        for field in ("path", "size", "sha256")
    ) or generated_row.get("mode") != okf["git_mode"]:
        raise InstallError("E_RELEASE_RECORD_OKF")


@contextlib.contextmanager
def verified_asset_handle(record: dict[str, Any]):
    path = Path(record["path"])
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InstallError(f"E_RELEASE_ASSET_OPEN:{path.name}") from exc
    handle = os.fdopen(descriptor, "rb", closefd=True)
    try:
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_dev != record["device"]
            or metadata.st_ino != record["inode"]
            or metadata.st_size != record["size"]
            or metadata.st_mtime_ns != record["mtime_ns"]
        ):
            raise InstallError(f"E_RELEASE_ASSET_CHANGED:{path.name}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != record["sha256"]:
            raise InstallError(f"E_RELEASE_ASSET_CHANGED:{path.name}")
        handle.seek(0)
        yield handle
        after = os.fstat(handle.fileno())
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_size != metadata.st_size
            or after.st_mtime_ns != metadata.st_mtime_ns
        ):
            raise InstallError(f"E_RELEASE_ASSET_CHANGED:{path.name}")
    finally:
        handle.close()


def inspect_release_tar(
    tar_record: dict[str, Any],
    version: str,
    expected_files: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], bytes]:
    prefix = f"goal-teams-{version}/"
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    max_single = 0
    max_path = 0
    okf_bytes: bytes | None = None
    with verified_asset_handle(tar_record) as raw:
        try:
            archive = tarfile.open(fileobj=raw, mode="r:*")
        except tarfile.TarError as exc:
            raise InstallError("E_RELEASE_TAR_INVALID") from exc
        try:
            members = archive.getmembers()
            if len(members) > TAR_LIMITS["max_members"]:
                raise InstallError("E_RELEASE_TAR_MEMBER_LIMIT")
            for member in members:
                if any(key in member.pax_headers for key in ("path", "linkpath", "GNU.sparse.name")):
                    raise InstallError("E_RELEASE_TAR_PAX_OVERRIDE")
                if member.issym() or member.islnk():
                    raise InstallError("E_RELEASE_TAR_LINK")
                if member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE}:
                    raise InstallError("E_RELEASE_TAR_TYPE")
                normalized_name = unicodedata.normalize("NFC", member.name)
                if normalized_name != member.name or not normalized_name.startswith(prefix):
                    raise InstallError("E_RELEASE_TAR_ROOT")
                relative = normalize_release_relative(
                    normalized_name[len(prefix):], "E_RELEASE_TAR_PATH"
                )
                collision = relative.casefold()
                if collision in seen:
                    raise InstallError("E_RELEASE_TAR_DUPLICATE")
                seen.add(collision)
                path_bytes = len(normalized_name.encode("utf-8"))
                max_path = max(max_path, path_bytes)
                if path_bytes > TAR_LIMITS["max_path_bytes"]:
                    raise InstallError("E_RELEASE_TAR_PATH_LIMIT")
                if member.size < 0 or member.size > TAR_LIMITS["max_single_file_bytes"]:
                    raise InstallError("E_RELEASE_TAR_SINGLE_LIMIT")
                mode = stat.S_IMODE(member.mode)
                if mode not in {0o644, 0o755}:
                    raise InstallError("E_RELEASE_TAR_MODE")
                source = archive.extractfile(member)
                if source is None:
                    raise InstallError("E_RELEASE_TAR_INVALID")
                digest = hashlib.sha256()
                captured = bytearray() if relative == OKF_GENERATED_PATH else None
                read_size = 0
                with source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        read_size += len(chunk)
                        digest.update(chunk)
                        if captured is not None:
                            captured.extend(chunk)
                if read_size != member.size:
                    raise InstallError("E_RELEASE_TAR_TRUNCATED")
                expected = expected_files.get(relative)
                if expected is None or (
                    expected["sha256"] != digest.hexdigest()
                    or expected["size"] != member.size
                    or expected["mode"] != mode
                ):
                    raise InstallError(f"E_RELEASE_TAR_FILE_IDENTITY:{relative}")
                total += member.size
                max_single = max(max_single, member.size)
                if total > TAR_LIMITS["max_total_uncompressed_bytes"]:
                    raise InstallError("E_RELEASE_TAR_TOTAL_LIMIT")
                if captured is not None:
                    okf_bytes = bytes(captured)
                prepared.append(
                    {
                        "archive_name": member.name,
                        "path": relative,
                        "sha256": digest.hexdigest(),
                        "size": member.size,
                        "mode": mode,
                    }
                )
        finally:
            archive.close()
    if set(seen) != {path.casefold() for path in expected_files} or len(prepared) != len(expected_files):
        raise InstallError("E_RELEASE_TAR_FILE_SET")
    if total and total / max(1, tar_record["size"]) > TAR_LIMITS["max_compression_ratio"]:
        raise InstallError("E_RELEASE_TAR_RATIO_LIMIT")
    if okf_bytes is None:
        raise InstallError("E_RELEASE_TAR_OKF_MISSING")
    prepared.sort(key=lambda entry: entry["path"])
    return prepared, okf_bytes


def validate_okf_release_bytes(
    data: bytes, identity: dict[str, Any], record: dict[str, Any]
) -> dict[str, Any]:
    manifest = require_json_object(data, "E_RELEASE_OKF_JSON")
    source = manifest.get("source")
    package = manifest.get("package")
    policy = manifest.get("policy")
    checkers = manifest.get("checkers")
    if (
        manifest.get("manifest_scope") != "installed_package_complete"
        or not isinstance(source, dict)
        or source.get("commit_sha256") != identity["source_commit"]
        or source.get("git_tree_id") != identity["source_git_tree_id"]
        or source.get("package_manifest_sha256") != record["source_package_manifest_sha256"]
        or not isinstance(package, dict)
        or not isinstance(package.get("payload_tree_sha256"), str)
        or not SHA256_RE.fullmatch(package["payload_tree_sha256"])
        or not isinstance(policy, dict)
        or not isinstance(policy.get("sha256"), str)
        or not SHA256_RE.fullmatch(policy["sha256"])
        or not isinstance(checkers, list)
    ):
        raise InstallError("E_RELEASE_OKF_IDENTITY")
    checker_hashes: dict[str, str] = {}
    for checker in checkers:
        if (
            not isinstance(checker, dict)
            or not isinstance(checker.get("path"), str)
            or not isinstance(checker.get("sha256"), str)
            or not SHA256_RE.fullmatch(checker["sha256"])
        ):
            raise InstallError("E_RELEASE_OKF_CHECKERS")
        if checker["path"] in checker_hashes:
            raise InstallError("E_RELEASE_OKF_CHECKERS")
        checker_hashes[checker["path"]] = checker["sha256"]
    summary = record.get("okf_conformance")
    if not isinstance(summary, dict) or (
        summary.get("manifest_path") != OKF_GENERATED_PATH
        or summary.get("manifest_sha256") != sha256_bytes(data)
        or summary.get("payload_tree_sha256") != package["payload_tree_sha256"]
        or summary.get("policy_sha256") != policy["sha256"]
        or summary.get("package_completeness_state") != "complete"
        or summary.get("checker_bindings") != checkers
    ):
        raise InstallError("E_RELEASE_OKF_RECORD")
    return {
        "manifest_sha256": sha256_bytes(data),
        "payload_tree_sha256": package["payload_tree_sha256"],
        "policy_sha256": policy["sha256"],
        "checker_hashes": checker_hashes,
    }


def prepare_release_bundle() -> None:
    global release_bundle_preflight, release_bundle_verified
    assert args.release_bundle is not None and args.release_identity is not None
    bundle = validate_no_symlink_ancestors(args.release_bundle, "E_RELEASE_BUNDLE_SYMLINK")
    identity_path = validate_no_symlink_ancestors(args.release_identity, "E_RELEASE_IDENTITY_SYMLINK")
    if not bundle.is_dir() or bundle.is_symlink():
        raise InstallError("E_RELEASE_BUNDLE_DIRECTORY")
    if path_within(bundle, code_home) or path_within(code_home, bundle):
        raise InstallError("E_RELEASE_BUNDLE_TARGET_OVERLAP")
    if path_within(identity_path, code_home):
        raise InstallError("E_RELEASE_IDENTITY_TARGET_OVERLAP")
    identity_data, identity_file_record = read_stable_bytes(identity_path, max_bytes=2 * 1024 * 1024)
    identity = parse_release_identity(identity_data)
    # This is intentionally immediately after identity validation and before
    # any live target mkdir/lock/report write.
    validate_production_release_target(identity)
    expected_names = {
        f"goal-teams-{identity['version']}.tar.gz",
        "SHA256SUMS",
        "_release.json",
        "_files.sha256",
    }
    children = list(bundle.iterdir())
    actual_names = {child.name for child in children}
    if len(children) != 4 or actual_names != expected_names:
        raise InstallError("E_RELEASE_BUNDLE_ASSET_SET")
    asset_records: dict[str, dict[str, Any]] = {}
    for child in children:
        asset_records[child.name] = stable_file_record(
            child, max_bytes=128 * 1024 * 1024
        )
    if set(identity["assets"]) != expected_names:
        raise InstallError("E_RELEASE_IDENTITY_ASSET_SET")
    normalized_asset_receipts: list[dict[str, Any]] = []
    for name in sorted(expected_names):
        expected = identity["assets"][name]
        actual = asset_records[name]
        if expected["sha256"] != actual["sha256"] or expected["size"] != actual["size"]:
            raise InstallError(f"E_RELEASE_IDENTITY_ASSET_DRIFT:{name}")
        normalized_asset_receipts.append(dict(expected))
    sums_data, _ = read_stable_bytes(asset_records["SHA256SUMS"]["path"], max_bytes=64 * 1024)
    try:
        sums_lines = sums_data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise InstallError("E_RELEASE_SHA256SUMS") from exc
    tar_name = f"goal-teams-{identity['version']}.tar.gz"
    if len(sums_lines) != 1 or "  " not in sums_lines[0]:
        raise InstallError("E_RELEASE_SHA256SUMS")
    sum_digest, sum_name = sums_lines[0].split("  ", 1)
    if sum_name != tar_name or sum_digest != asset_records[tar_name]["sha256"]:
        raise InstallError("E_RELEASE_SHA256SUMS")
    record_data, _ = read_stable_bytes(asset_records["_release.json"]["path"], max_bytes=2 * 1024 * 1024)
    record = require_json_object(record_data, "E_RELEASE_RECORD_JSON")
    files_data, _ = read_stable_bytes(asset_records["_files.sha256"]["path"], max_bytes=8 * 1024 * 1024)
    files = parse_release_file_manifest(files_data, identity["version"])
    validate_release_record(record, identity, files)
    if (
        record["artifact"]["sha256"] != asset_records[tar_name]["sha256"]
        or record["artifact"]["size"] != asset_records[tar_name]["size"]
    ):
        raise InstallError("E_RELEASE_RECORD_ARTIFACT")
    prepared, okf_bytes = inspect_release_tar(asset_records[tar_name], identity["version"], files)
    okf = validate_okf_release_bytes(okf_bytes, identity, record)
    package_files.clear()
    package_files.extend(
        {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "size": entry["size"],
            "mode": entry["mode"],
        }
        for entry in prepared
    )
    source_info.update(
        {
            "source_kind": identity["source_kind"],
            "repository": identity["repository"],
            "release_tag": identity["release_tag"],
            "release_id": identity["release_id"],
            "release_state": identity["release_state"],
            "release_assets": normalized_asset_receipts,
            "release_asset_sha256": asset_records[tar_name]["sha256"],
            "release_identity_sha256": sha256_bytes(identity_data),
            "bundle_tree_sha256": record["tree_sha256"],
            "version": identity["version"],
            "commit": identity["source_commit"],
            "dirty": False,
            "dirty_entry_count": 0,
            "tree_digest": record["tree_sha256"],
            "tracked_tree_digest": record["tree_sha256"],
            "git_tree_id": identity["source_git_tree_id"],
            "package_manifest_sha256": record["source_package_manifest_sha256"],
            "okf_conformance_manifest_sha256": okf["manifest_sha256"],
            "okf_payload_tree_sha256": okf["payload_tree_sha256"],
            "okf_policy_sha256": okf["policy_sha256"],
            "okf_checker_hashes": okf["checker_hashes"],
            "okf_package_completeness_state": "complete",
            "skill_source_path": "release-bundle",
        }
    )
    release_bundle_preflight = {
        "bundle": bundle,
        "identity": identity,
        "identity_file_record": identity_file_record,
        "asset_records": asset_records,
        "files": files,
        "prepared": prepared,
        "record": record,
        "preflight_sha256": canonical_json_sha256(
            {
                "identity": identity,
                "assets": {
                    name: {"sha256": value["sha256"], "size": value["size"]}
                    for name, value in sorted(asset_records.items())
                },
                "files": prepared,
            }
        ),
    }
    validate_production_release_target(identity)
    release_bundle_verified = True


def validate_verified_release_target() -> None:
    if release_bundle_preflight is None:
        return
    identity = release_bundle_preflight.get("identity")
    if not isinstance(identity, dict):
        raise InstallError("E_RELEASE_IDENTITY_JSON")
    validate_production_release_target(identity)


def recheck_release_assets() -> None:
    if release_bundle_preflight is None:
        raise InstallError("E_RELEASE_BUNDLE_NOT_PREPARED")
    for name, expected in release_bundle_preflight["asset_records"].items():
        actual = stable_file_record(Path(expected["path"]), max_bytes=128 * 1024 * 1024)
        if any(actual[field] != expected[field] for field in ("sha256", "size", "device", "inode", "mtime_ns")):
            raise InstallError(f"E_RELEASE_ASSET_CHANGED:{name}")
    expected_identity = release_bundle_preflight["identity_file_record"]
    actual_identity = stable_file_record(
        Path(expected_identity["path"]), max_bytes=2 * 1024 * 1024
    )
    if any(
        actual_identity[field] != expected_identity[field]
        for field in ("sha256", "size", "device", "inode", "mtime_ns")
    ):
        raise InstallError("E_RELEASE_IDENTITY_CHANGED")


def materialize_release_bundle(destination: Path) -> None:
    if release_bundle_preflight is None:
        raise InstallError("E_RELEASE_BUNDLE_NOT_PREPARED")
    validate_no_symlink_ancestors(destination, "E_RELEASE_TARGET_SYMLINK")
    if not path_within(absolute_lexical(destination), code_home):
        raise InstallError("E_RELEASE_TARGET_OUTSIDE")
    recheck_release_assets()
    identity = release_bundle_preflight["identity"]
    tar_name = f"goal-teams-{identity['version']}.tar.gz"
    prepared, _ = inspect_release_tar(
        release_bundle_preflight["asset_records"][tar_name],
        identity["version"],
        release_bundle_preflight["files"],
    )
    if canonical_json_sha256(prepared) != canonical_json_sha256(release_bundle_preflight["prepared"]):
        raise InstallError("E_RELEASE_TAR_CHANGED")
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.create_dir(destination, pin=True)
    else:
        destination.mkdir(parents=True, exist_ok=False)
    try:
        tar_record = release_bundle_preflight["asset_records"][tar_name]
        with verified_asset_handle(tar_record) as raw:
            with tarfile.open(fileobj=raw, mode="r:*") as archive:
                members = {member.name: member for member in archive.getmembers()}
                for entry in prepared:
                    member = members.get(entry["archive_name"])
                    if member is None or not member.isfile():
                        raise InstallError("E_RELEASE_TAR_CHANGED")
                    target = destination.joinpath(*PurePosixPath(entry["path"]).parts)
                    validate_no_symlink_ancestors(target.parent, "E_RELEASE_TARGET_SYMLINK")
                    if not path_within(absolute_lexical(target), absolute_lexical(destination)):
                        raise InstallError("E_RELEASE_TARGET_OUTSIDE")
                    if production_target_io_bound and production_target_anchor is not None:
                        production_target_anchor.mkdir_path(target.parent)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise InstallError("E_RELEASE_TAR_INVALID")
                    with source:
                        data = source.read(entry["size"] + 1)
                    if len(data) != entry["size"] or sha256_bytes(data) != entry["sha256"]:
                        raise InstallError(f"E_RELEASE_TAR_WRITE_DRIFT:{entry['path']}")
                    if production_target_io_bound and production_target_anchor is not None:
                        production_target_anchor.atomic_bytes(
                            target, data, mode=entry["mode"]
                        )
                    else:
                        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                        descriptor = os.open(target, flags, entry["mode"])
                        try:
                            remaining = memoryview(data)
                            while remaining:
                                count = os.write(descriptor, remaining)
                                if count <= 0:
                                    raise InstallError("E_RELEASE_TAR_WRITE")
                                remaining = remaining[count:]
                            os.fchmod(descriptor, entry["mode"])
                        finally:
                            os.close(descriptor)
        validate_package_tree(destination, "release_materialized")
    except BaseException:
        if production_target_io_bound and production_target_anchor is not None:
            with contextlib.suppress(OSError, InstallError):
                production_target_anchor.remove_path(destination)
        else:
            shutil.rmtree(destination, ignore_errors=True)
        raise


def prepare_release_source() -> list[str]:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
    allowed_files, allowed_prefixes, required_generated = load_allowlist()
    generated_paths.clear()
    generated_paths.update(required_generated)
    selected = sorted(entry["path"] for entry in package_files)
    allowed = lambda item: item in allowed_files or item in required_generated or any(
        item.startswith(prefix) for prefix in allowed_prefixes
    )
    unexpected = [item for item in selected if not allowed(item)]
    if unexpected:
        raise InstallError("E_RELEASE_PACKAGE_ALLOWLIST:" + ",".join(unexpected))
    actual = sorted(
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    if actual != selected:
        raise InstallError("E_RELEASE_PACKAGE_FILE_SET")
    for relative in selected:
        source = safe_source_file(relative)
        expected = next(entry for entry in package_files if entry["path"] == relative)
        if (
            sha256_file(source) != expected["sha256"]
            or source.stat().st_size != expected["size"]
            or stat.S_IMODE(source.stat().st_mode) != expected["mode"]
        ):
            raise InstallError(f"E_RELEASE_PACKAGE_DRIFT:{relative}")
    prompt_identity = compute_prompt_identity(SOURCE_ROOT)
    source_info.update(
        {
            "prompt_identity_version": prompt_identity["prompt_identity_version"],
            "runtime_prompt_route": prompt_identity["route_id"],
            "runtime_prompt_refs": prompt_identity["ordered_refs"],
            "prefix_manifest_sha256": prompt_identity["prefix_manifest_sha256"],
            "route_static_digest": prompt_identity["route_static_digest"],
            "prompt_manifest_status": prompt_identity["manifest_status"],
            "prompt_digest_scope": prompt_identity["digest_scope"],
            "stable_prefix_digest": prompt_identity["stable_prefix_digest"],
            "runtime_prompt_digest": prompt_identity["runtime_prompt_digest"],
        }
    )
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
    return selected


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
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
        production_target_anchor.atomic_json(path, payload)
        production_target_anchor.revalidate()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{stamp}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def safe_report_path(path: Path) -> str:
    if production_target_io_bound and production_target_anchor is not None:
        try:
            relative = absolute_lexical(path).relative_to(report_root)
        except ValueError:
            return "custom-report.json"
        return (Path("state") / "goal-teams" / "reports" / relative).as_posix()
    try:
        return path.resolve().relative_to(code_home).as_posix()
    except ValueError:
        return "custom-report.json"


def write_report(status: str, action: str, *, backup_id: str | None = None, error_code: str | None = None) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
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
        "retained_mutation_quarantines": retained_quarantines,
        "report_ref": safe_report_path(report_path),
        "error_code": error_code,
    }
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.create_json_once(report_path, payload)
    else:
        atomic_json(report_path, payload)


def acquire_install_lock() -> None:
    global install_lock_handle, install_lock_directory
    if args.release_bundle:
        validate_release_runtime_boundary()
        validate_verified_release_target()
    if production_target_anchor is not None:
        bind_production_target_io()
    else:
        state_dir.mkdir(parents=True, exist_ok=True)
    if args.release_bundle:
        validate_release_runtime_boundary()
        validate_verified_release_target()
    if fcntl is not None:
        if production_target_anchor is not None:
            handle = production_target_anchor.open_lock()
        else:
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
    if production_target_anchor is not None:  # pragma: no cover - Unix production has fcntl
        state_fd = production_target_anchor.fd((".codex", "state", "goal-teams"))
        try:
            os.mkdir("install.lock.d", mode=0o700, dir_fd=state_fd)
        except FileExistsError as exc:
            raise InstallError("E_INSTALL_LOCKED") from exc
        install_lock_directory = state_dir / "install.lock.d"
    else:
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
        if production_target_io_bound and production_target_anchor is not None:
            with contextlib.suppress(OSError, InstallError):
                production_target_anchor.remove_path(install_lock_directory)
        else:
            shutil.rmtree(install_lock_directory, ignore_errors=True)
        install_lock_directory = None


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
    try:
        return subprocess.run(
            command, cwd=cwd, env=env, text=True, capture_output=True, check=False
        )
    finally:
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.revalidate()


def git(*git_args: str, text: bool = True) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        ["git", *git_args], cwd=SOURCE_ROOT, capture_output=True, text=text, check=False
    )


def validate_relative_path(raw: str) -> None:
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "\\" in raw:
        raise InstallError(f"E_MANIFEST_PATH:{raw}")


def safe_source_file(relative: str) -> Path:
    """Resolve a tracked package file without following any ancestor symlink."""
    validate_relative_path(relative)
    parts = PurePosixPath(relative).parts
    cursor = SOURCE_ROOT
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
        cursor.resolve(strict=True).relative_to(SOURCE_ROOT.resolve(strict=True))
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
    source_info["source_kind"] = "worktree"
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
    prompt_identity = compute_prompt_identity(SOURCE_ROOT)
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
    # Directory descriptors are deliberately CLOEXEC.  Validation subprocesses
    # receive the canonical, non-authoritative display path; all parent-process
    # mutations continue through the held descriptor roots.
    environment["CODEX_HOME"] = str(configured_code_home)
    return environment


def validate_skill(root: Path, phase: str) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
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
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()


def copy_package(selected: list[str], destination: Path) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.create_dir(destination)
    else:
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
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.copy_path(source, target)
        else:
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
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.mkdir_path(target.parent)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.resolve(strict=True).relative_to(stage.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise InstallError("E_OKF_PACKAGE_GENERATED_PATH") from exc
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.atomic_bytes(target, data, mode=0o644)
    else:
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


def replay_okf_manifest(stage: Path, phase: str) -> None:
    """Validate the builder-generated manifest without regenerating it."""

    manifest = stage / OKF_GENERATED_PATH
    checker = stage / "scripts" / "checks" / "check-okf.py"
    if (
        not manifest.is_file()
        or manifest.is_symlink()
        or not checker.is_file()
        or checker.is_symlink()
    ):
        raise InstallError(f"E_RELEASE_OKF_PACKAGE:{phase}")
    before = sha256_file(manifest)
    if before != source_info.get("okf_conformance_manifest_sha256"):
        raise InstallError(f"E_RELEASE_OKF_DRIFT:{phase}")
    result = run(
        [
            sys.executable,
            str(checker),
            "--root",
            str(stage),
            "--package-tree",
            str(stage),
        ],
        cwd=stage,
        env=validation_environment(),
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise InstallError(f"E_RELEASE_OKF_REPLAY:{phase}") from exc
    if (
        result.returncode != 0
        or payload.get("passed") is not True
        or payload.get("package_completeness_state") != "complete"
        or sha256_file(manifest) != before
    ):
        raise InstallError(f"E_RELEASE_OKF_REPLAY:{phase}")
    validate_package_tree(stage, f"okf_replay_{phase}")
    validation_results.append(
        {
            "phase": f"okf_package_tree_{phase}",
            "command": "scripts/checks/check-okf.py --package-tree (replay only)",
            "exit_code": 0,
            "status": "passed",
            "manifest_sha256": before,
            "payload_tree_sha256": source_info["okf_payload_tree_sha256"],
            "policy_sha256": source_info["okf_policy_sha256"],
        }
    )


def validate_package_tree(root: Path, phase: str) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
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
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()


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
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
    if not path.exists() and not path.is_symlink():
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.revalidate()
        return {"exists": False}
    if path.is_dir() and not path.is_symlink():
        records = tree_records(path)
        result = {"exists": True, "type": "directory", "digest": records_digest(records), "files": records}
    else:
        record = file_record(path, ".")
        result = {"exists": True, "type": record["type"], "digest": records_digest([record]), "file": record}
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
    return result


def remove_path(path: Path) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.remove_path(path)
        return
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def copy_path(source: Path, destination: Path) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.copy_path(source, destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, destination, symlinks=True)
    elif source.is_symlink():
        destination.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, destination)


def read_state() -> dict[str, Any] | None:
    try:
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.revalidate()
            state_bytes = production_target_anchor.read_optional_file(
                current_state_path,
                max_bytes=8 * 1024 * 1024,
            )
            production_target_anchor.revalidate()
            if state_bytes is None:
                return None
            payload = json.loads(state_bytes.decode("utf-8"))
        else:
            if not current_state_path.is_file():
                return None
            payload = json.loads(current_state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    source_kind = payload.get("source_kind", "worktree")
    if source_kind not in {"worktree", *RELEASE_SOURCE_KINDS}:
        raise InstallError("E_INSTALL_STATE_FIELD:source_kind")
    if source_kind in RELEASE_SOURCE_KINDS:
        repository = payload.get("repository")
        version = payload.get("version")
        release_tag = payload.get("release_tag")
        release_state = payload.get("release_state")
        release_id = payload.get("release_id")
        if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
            raise InstallError("E_INSTALL_STATE_FIELD:repository")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise InstallError("E_INSTALL_STATE_FIELD:version")
        if not isinstance(release_tag, str) or not TAG_RE.fullmatch(release_tag):
            raise InstallError("E_INSTALL_STATE_FIELD:release_tag")
        if release_tag != f"v{str(payload.get('version'))[1:]}":
            raise InstallError("E_INSTALL_STATE_FIELD:release_tag")
        if source_kind == "github_release_asset":
            if release_state != "published" or not isinstance(release_id, int) or isinstance(release_id, bool) or release_id < 1:
                raise InstallError("E_INSTALL_STATE_FIELD:release_identity")
        elif (
            release_state not in {"local", "draft", "rehearsal"}
            or not (
                (isinstance(release_id, int) and not isinstance(release_id, bool) and release_id >= 0)
                or (isinstance(release_id, str) and release_id)
            )
        ):
            raise InstallError("E_INSTALL_STATE_FIELD:release_identity")
        if payload.get("source_dirty") is not False:
            raise InstallError("E_INSTALL_STATE_FIELD:source_dirty")
        for field in (
            "source_commit",
            "source_git_tree_id",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not GIT_SHA_RE.fullmatch(value):
                raise InstallError(f"E_INSTALL_STATE_FIELD:{field}")
        for field in (
            "release_asset_sha256",
            "release_identity_sha256",
            "bundle_tree_sha256",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
                raise InstallError(f"E_INSTALL_STATE_FIELD:{field}")
        assets = payload.get("release_assets")
        expected_names = {
            f"goal-teams-{payload.get('version')}.tar.gz",
            "SHA256SUMS",
            "_release.json",
            "_files.sha256",
        }
        if not isinstance(assets, list) or len(assets) != 4:
            raise InstallError("E_INSTALL_STATE_FIELD:release_assets")
        names: set[str] = set()
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("name") in names:
                raise InstallError("E_INSTALL_STATE_FIELD:release_assets")
            name = asset.get("name")
            digest = asset.get("sha256")
            if (
                not isinstance(name, str)
                or not isinstance(digest, str)
                or not SHA256_RE.fullmatch(digest)
                or asset.get("download_sha256") != digest
                or not isinstance(asset.get("size"), int)
                or asset["size"] < 0
            ):
                raise InstallError("E_INSTALL_STATE_FIELD:release_assets")
            asset_id = asset.get("asset_id")
            if source_kind == "github_release_asset" and (
                not isinstance(asset_id, int)
                or isinstance(asset_id, bool)
                or asset_id < 1
            ):
                raise InstallError("E_INSTALL_STATE_FIELD:release_assets")
            names.add(name)
        if names != expected_names:
            raise InstallError("E_INSTALL_STATE_FIELD:release_assets")
        tar_name = f"goal-teams-{payload.get('version')}.tar.gz"
        tar_asset = next(asset for asset in assets if asset.get("name") == tar_name)
        if payload.get("release_asset_sha256") != tar_asset.get("sha256"):
            raise InstallError("E_INSTALL_STATE_FIELD:release_asset_sha256")
        if payload.get("bundle_tree_sha256") != payload.get("source_tree_digest"):
            raise InstallError("E_INSTALL_STATE_FIELD:bundle_tree_sha256")
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


def target_entry_exists(path: Path) -> bool:
    if production_target_io_bound and production_target_anchor is not None:
        return production_target_anchor.entry_exists_path(path)
    return path.exists() or path.is_symlink()


def replace_target_to_path(target: Path, destination: Path) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.replace_path(target, destination)
        return
    os.replace(target, destination)


def replace_path_to_target(source: Path, target: Path) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.replace_path(source, target)
        return
    os.replace(source, target)


def ensure_live_target_parent(target: Path) -> None:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.mkdir_path(target.parent)
        return
    target.parent.mkdir(parents=True, exist_ok=True)


def target_archive_ref(path: Path) -> str:
    if production_target_io_bound:
        try:
            relative = absolute_lexical(path).relative_to(preserved_root)
        except ValueError:
            raise InstallError("E_RELEASE_TARGET_OUTSIDE")
        return (Path("state") / "goal-teams" / "preserved" / relative).as_posix()
    return path.relative_to(code_home).as_posix()


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
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.create_dir(preserve_dir, pin=True)
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
            "archive_ref": target_archive_ref(archive),
            "digest": preserved_digest,
        })


def create_backup(labels: list[str], previous_state: dict[str, Any] | None) -> tuple[str, Path]:
    backup_id = stamp
    backup_dir = backup_root / backup_id
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.create_dir(backup_dir, pin=True)
    else:
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
    try:
        if production_target_io_bound and production_target_anchor is not None:
            data = production_target_anchor.read_optional_file(
                manifest_file, max_bytes=8 * 1024 * 1024
            )
            if data is None:
                raise InstallError("E_BACKUP_MANIFEST_MISSING")
            manifest = json.loads(data.decode("utf-8"))
        else:
            if not manifest_file.is_file():
                raise InstallError("E_BACKUP_MANIFEST_MISSING")
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    if production_target_io_bound and production_target_anchor is not None:
        transaction = production_target_anchor.create_unique_dir(
            code_home, f".goal-teams-restore-{stamp}-"
        )
    else:
        transaction = Path(tempfile.mkdtemp(prefix=f".goal-teams-restore-{stamp}-", dir=code_home))
    staged = transaction / "staged"
    previous_live = transaction / "previous-live"
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.create_dir(staged, pin=True)
        production_target_anchor.create_dir(previous_live, pin=True)
        state_before = production_target_anchor.read_optional_file(
            current_state_path, max_bytes=8 * 1024 * 1024
        )
    else:
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
                ensure_live_target_parent(target)
                switched_labels.append(label)
                if target_entry_exists(target):
                    live_snapshot = snapshot_path(previous_live, label)
                    if production_target_io_bound and production_target_anchor is not None:
                        production_target_anchor.mkdir_path(live_snapshot.parent)
                    else:
                        live_snapshot.parent.mkdir(parents=True, exist_ok=True)
                    replace_target_to_path(target, live_snapshot)
                if component["snapshot"]["exists"]:
                    replace_path_to_target(snapshot_path(staged, label), target)
            if restore_previous_state:
                previous = backup_dir / "previous-state.json"
                previous_bytes = (
                    production_target_anchor.read_optional_file(
                        previous, max_bytes=8 * 1024 * 1024
                    )
                    if production_target_io_bound and production_target_anchor is not None
                    else previous.read_bytes() if previous.is_file() else None
                )
                if previous_bytes is not None:
                    payload = json.loads(previous_bytes.decode("utf-8"))
                    atomic_json(current_state_path, payload)
                else:
                    if production_target_io_bound and production_target_anchor is not None:
                        production_target_anchor.unlink_path(
                            current_state_path, missing_ok=True
                        )
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
                    ensure_live_target_parent(target)
                    replace_path_to_target(live_snapshot, target)
            if state_before is None:
                if production_target_io_bound and production_target_anchor is not None:
                    production_target_anchor.unlink_path(current_state_path, missing_ok=True)
                else:
                    current_state_path.unlink(missing_ok=True)
            else:
                if production_target_io_bound and production_target_anchor is not None:
                    production_target_anchor.atomic_bytes(
                        current_state_path, state_before, mode=0o600
                    )
                else:
                    current_state_path.parent.mkdir(parents=True, exist_ok=True)
                    state_tmp = current_state_path.with_name(f".{current_state_path.name}.restore-{stamp}")
                    state_tmp.write_bytes(state_before)
                    os.replace(state_tmp, current_state_path)
            raise
    finally:
        if production_target_io_bound and production_target_anchor is not None:
            with contextlib.suppress(OSError, InstallError):
                production_target_anchor.remove_path(transaction)
        else:
            shutil.rmtree(transaction, ignore_errors=True)


FALLBACK_REPLACEMENTS = {
    "team-implementer.toml": 'nickname_candidates = ["实现-功能开发", "实现-修复任务", "实现-集成改造"]',
    "team-qa.toml": 'nickname_candidates = ["测试-E2E 验证", "测试-回归检查", "测试-验收证据"]',
    "team-researcher.toml": 'nickname_candidates = ["调研-代码路径分析", "调研-资料证据收集", "调研-上下文梳理"]',
    "team-reviewer.toml": 'nickname_candidates = ["评审-代码审查", "评审-一致性复核", "评审-风险边界检查"]',
}


def prepare_agents(stage_skill: Path, stage_agents: Path) -> tuple[list[str], list[str]]:
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.create_dir(stage_agents, pin=True)
    else:
        stage_agents.mkdir(parents=True, exist_ok=True)
    managed: list[str] = []
    fallback: list[str] = []
    for source in sorted((stage_skill / "subagents").glob("goal-*.toml")):
        with source.open("rb") as handle:
            tomllib.load(handle)
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.copy_path(source, stage_agents / source.name)
        else:
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
            if production_target_io_bound and production_target_anchor is not None:
                production_target_anchor.atomic_bytes(
                    target, updated.encode("utf-8"), mode=0o644
                )
            else:
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
        "source_kind": source_info["source_kind"],
        "repository": source_info["repository"],
        "release_tag": source_info["release_tag"],
        "release_id": source_info["release_id"],
        "release_state": source_info["release_state"],
        "release_assets": source_info["release_assets"],
        "release_asset_sha256": source_info["release_asset_sha256"],
        "release_identity_sha256": source_info["release_identity_sha256"],
        "bundle_tree_sha256": source_info["bundle_tree_sha256"],
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
        "source_kind": state.get("source_kind", "worktree"),
        "repository": state.get("repository"),
        "release_tag": state.get("release_tag"),
        "release_id": state.get("release_id"),
        "release_state": state.get("release_state"),
        "release_assets": state.get("release_assets", []),
        "release_asset_sha256": state.get("release_asset_sha256"),
        "release_identity_sha256": state.get("release_identity_sha256"),
        "bundle_tree_sha256": state.get("bundle_tree_sha256"),
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
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.unlink_path(current_state_path, missing_ok=True)
        else:
            current_state_path.unlink(missing_ok=True)
    validation_results.append({"phase": "restore", "command": "byte-equivalent manifest verification", "exit_code": 0, "status": "passed"})
    write_report("restored" if action == "rollback" else "uninstalled", action, backup_id=backup_id)
    print(f"Goal Teams {action} completed; backup {backup_id} verified.")


def install() -> None:
    global SOURCE_ROOT
    previous_state = read_state()
    action = "update" if previous_state is not None else "install"
    if production_target_io_bound and production_target_anchor is not None:
        production_target_anchor.revalidate()
    else:
        code_home.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
    if production_target_io_bound and production_target_anchor is not None:
        transaction = production_target_anchor.create_unique_dir(
            code_home, f".goal-teams-transaction-{stamp}-"
        )
    else:
        transaction = Path(tempfile.mkdtemp(prefix=f".goal-teams-transaction-{stamp}-", dir=code_home))
    backup_dir: Path | None = None
    backup_id: str | None = None
    switched = False
    transaction_retired = False

    def retire_transaction() -> None:
        nonlocal transaction_retired
        global SOURCE_ROOT
        if transaction_retired:
            return
        SOURCE_ROOT = ROOT
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.remove_path(transaction)
        else:
            shutil.rmtree(transaction, ignore_errors=True)
        transaction_retired = True

    try:
        if args.release_bundle:
            # A rehearsal CODEX_HOME may itself live below a repository.  An
            # transaction-local .git indirection prevents Git discovery
            # from walking upward and binding gitless package checks to that
            # unrelated ancestor index.  It never enters the staged package.
            git_discovery_barrier = transaction / ".git"
            if production_target_io_bound and production_target_anchor is not None:
                production_target_anchor.atomic_bytes(
                    git_discovery_barrier,
                    b"gitdir: .goal-teams-gitless\n",
                    mode=0o600,
                )
            else:
                git_discovery_barrier.write_text(
                    "gitdir: .goal-teams-gitless\n", encoding="utf-8"
                )
                git_discovery_barrier.chmod(0o600)
            release_source = transaction / "release-source"
            materialize_release_bundle(release_source)
            SOURCE_ROOT = release_source
            selected = prepare_release_source()
            replay_okf_manifest(SOURCE_ROOT, "source")
        else:
            SOURCE_ROOT = ROOT
            selected = prepare_source()
        validate_skill(SOURCE_ROOT, "source")
        stage_root = transaction / "stage"
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.create_dir(stage_root, pin=True)
        stage_skill = transaction / "stage" / "skill"
        stage_agents = transaction / "stage" / "agents"
        copy_package(selected, stage_skill)
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.mkdir_path(stage_skill, pin=True)
        if args.release_bundle:
            replay_okf_manifest(stage_skill, "staging")
        else:
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
                    if production_target_io_bound and production_target_anchor is not None:
                        production_target_anchor.copy_path(
                            existing_fallback, stage_agents / name
                        )
                    else:
                        shutil.copy2(existing_fallback, stage_agents / name)
                    fallback_agents.append(name)
        validate_skill(stage_skill, "staging")
        validate_package_tree(stage_skill, "post_staging_validation")
        maybe_fail("staging_validation")
        if args.dry_run:
            retire_transaction()
            write_report("dry_run", action)
            source_label = "release bundle" if args.release_bundle else "tracked allowlist"
            print(f"Dry-run {action}: source and {source_label} staging verified.")
            return

        detect_and_preserve_user_changes(previous_state, action)
        previous_managed = previous_state.get("managed_agent_files", []) if previous_state else []
        previous_fallback = previous_state.get("fallback_agent_files", []) if previous_state else []
        affected_agents = sorted(set(managed_agents + fallback_agents + previous_managed + previous_fallback))
        labels = ["skill"] + [f"agent:{name}" for name in affected_agents]
        backup_id, backup_dir = create_backup(labels, previous_state)
        origin_backup_id = previous_state.get("origin_backup_id", backup_id) if previous_state else backup_id

        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.revalidate()
        else:
            skill_target.parent.mkdir(parents=True, exist_ok=True)
            agent_target.mkdir(parents=True, exist_ok=True)
        live_previous = transaction / "live-previous"
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.create_dir(live_previous, pin=True)
        else:
            live_previous.mkdir(parents=True, exist_ok=True)
        switched = True
        if target_entry_exists(skill_target):
            replace_target_to_path(skill_target, live_previous / "skill")
        replace_path_to_target(stage_skill, skill_target)
        maybe_fail("after_skill_switch")
        for name in affected_agents:
            target = agent_target / name
            if target_entry_exists(target):
                previous_agent = live_previous / "agents" / name
                if production_target_io_bound and production_target_anchor is not None:
                    production_target_anchor.mkdir_path(previous_agent.parent)
                else:
                    previous_agent.parent.mkdir(parents=True, exist_ok=True)
                replace_target_to_path(target, previous_agent)
            staged_agent = stage_agents / name
            if staged_agent.is_file():
                replace_path_to_target(staged_agent, target)
        maybe_fail("after_agent_switch")
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.revalidate()
            production_target_anchor.mkdir_path(skill_target, pin=True)
        try:
            validate_skill(skill_target, "post_switch")
            validate_package_tree(skill_target, "post_switch_validation")
        finally:
            if production_target_io_bound and production_target_anchor is not None:
                production_target_anchor.unpin(skill_target)
        maybe_fail("post_switch_validation")
        state = state_payload(
            backup_id=backup_id,
            origin_backup_id=origin_backup_id,
            managed_agents=managed_agents,
            fallback_agents=fallback_agents,
        )
        atomic_json(current_state_path, state)
        retire_transaction()
        write_report("installed", action, backup_id=backup_id)
        if production_target_io_bound and production_target_anchor is not None:
            production_target_anchor.revalidate()
        source_label = "verified release bundle" if args.release_bundle else "tracked allowlist"
        print(f"Goal Teams {action} completed from {source_label}; report {safe_report_path(report_path)}")
    except BaseException as exc:
        if switched and backup_dir is not None:
            try:
                restore_backup(backup_dir, restore_previous_state=True)
                validation_results.append({"phase": "automatic_rollback", "command": "byte-equivalent manifest verification", "exit_code": 0, "status": "passed"})
                error_code = str(exc).split(":", 1)[0] if isinstance(exc, InstallError) else type(exc).__name__
                retire_transaction()
                write_report("failed_rolled_back", action, backup_id=backup_id, error_code=error_code)
            except BaseException as rollback_exc:
                rollback_code = str(rollback_exc).split(":", 1)[0] if isinstance(rollback_exc, InstallError) else type(rollback_exc).__name__
                retire_transaction()
                write_report("rollback_failed", action, backup_id=backup_id, error_code=rollback_code)
                raise InstallError(f"E_AUTOMATIC_ROLLBACK:{rollback_exc}") from exc
        raise
    finally:
        SOURCE_ROOT = ROOT
        retire_transaction()


def handle_signal(signum: int, _frame: Any) -> None:
    raise InstallError(f"E_SIGNAL:{signum}")


for handled_signal in (signal.SIGINT, signal.SIGTERM):
    signal.signal(handled_signal, handle_signal)


try:
    if args.release_bundle:
        validate_release_runtime_boundary()
        prepare_release_bundle()
        validate_release_runtime_boundary()
    acquire_install_lock()
    if args.rollback:
        lifecycle_action("rollback")
    elif args.uninstall:
        lifecycle_action("uninstall")
    else:
        install()
except InstallError as exc:
    report_capability_ready = production_target_anchor is None or production_target_io_bound
    if (
        report_capability_ready
        and not report_path.exists()
        and (not args.release_bundle or release_bundle_verified)
    ):
        action = "rollback" if args.rollback else "uninstall" if args.uninstall else "install"
        try:
            write_report("failed", action, error_code=str(exc).split(":", 1)[0])
        except (OSError, InstallError):
            pass
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
except Exception as exc:
    action = "rollback" if args.rollback else "uninstall" if args.uninstall else "install"
    report_capability_ready = production_target_anchor is None or production_target_io_bound
    if (
        report_capability_ready
        and not report_path.exists()
        and (not args.release_bundle or release_bundle_verified)
    ):
        try:
            write_report("failed", action, error_code="E_INTERNAL")
        except (OSError, InstallError):
            pass
    print(f"E_INTERNAL:{type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1)
finally:
    try:
        release_install_lock()
    finally:
        if production_target_anchor is not None:
            production_target_anchor.close()
PY
