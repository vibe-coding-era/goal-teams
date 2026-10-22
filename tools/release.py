#!/usr/bin/env python3
"""Goal Teams release tool (Python 3.9+, standard library only).

Subcommands (each also takes --root DIR; default: the repository holding this tool):

  build [--out DIR] [--version X] [--allow-dirty]
      Build the release asset set once into DIR (default ./dist):
      goal-teams-<version>.tar.gz, release.json (every file's path/size/SHA-256
      plus the source commit/tree) and SHA256SUMS. Inside git clean builds read
      the exact HEAD blobs; visible changes are refused (--allow-dirty makes
      a local test build that records commit/tree as null).
  verify DIR [--pubkey PATH]
      Check downloaded assets: SHA256SUMS against the files, the optional
      Ed25519 signature SHA256SUMS.sig, release.json against the tarball and
      every tarball member. Refuses unsafe archives (absolute or '..' paths,
      links, devices, duplicates, members outside the top directory).
  notes VERSION
      Print the CHANGELOG.md section of VERSION (the release notes).
  check-tag TAG
      Exit 1 unless TAG == "v" + the contents of VERSION.

Exit status: 0 ok, 1 failed or refused, 2 usage error.

Determinism of `build`: members sorted by path; mtime = SOURCE_DATE_EPOCH, else
the HEAD commit time, else 0; uid/gid 0 and empty owner names; files 0644, or
0755 when executable in git (on disk outside git); directories 0755; PAX tar
with UTF-8 names; gzip level 9 with mtime 0 and no file name. Checkout paths,
file times and owners never reach the output. The gzip bytes also depend on the
zlib build, so byte-identical rebuilds are only expected in the same environment.

Signatures: SHA256SUMS.sig is the raw 64-byte Ed25519 signature of the exact
SHA256SUMS bytes (`openssl pkeyutl -sign -rawin -inkey key.pem -in SHA256SUMS
-out SHA256SUMS.sig`). The public key lives in keys/release-ed25519.pub as PEM
SubjectPublicKeyInfo (`openssl pkey -in key.pem -pubout`); DER or 64 hex
characters are accepted too. The private key never enters the repository.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import platform
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

NAME = "goal-teams"
TOOL_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = "plugins/goal-teams"
REQUIRED_FILES = ("tools/install.py",)
OPTIONAL_FILES = (
    ".claude-plugin/marketplace.json",
    "LICENSE",
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "MIGRATION.md",
    "VERSION",
)
PATHSPECS = (PLUGIN_DIR,) + REQUIRED_FILES + OPTIONAL_FILES
MANIFEST = "release.json"
SUMS = "SHA256SUMS"
SIG = "SHA256SUMS.sig"
DEFAULT_PUBKEY = "keys/release-ed25519.pub"
OS_METADATA = {".DS_Store", "Thumbs.db", "desktop.ini"}  # ignored in a download directory

VERSION_RE = re.compile(r"[0-9]+(?:\.[0-9]+)+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
OBJECT_ID_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
SUMS_LINE_RE = re.compile(r"([0-9a-f]{64}) [ *](\S+)")
UNSAFE_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\\:]")
MAX_MEMBERS = 50_000
MAX_TOTAL_BYTES = 1 << 30
MAX_MTIME = 8**11 - 1  # largest value a ustar header holds without a PAX record
CHUNK = 1 << 16

Entry = Tuple[str, int, bytes]  # (repository-relative POSIX path, mode, content)


class ReleaseError(Exception):
    """A refusal or failure with a message that says what to do."""


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_version(version: str, origin: str) -> str:
    if not VERSION_RE.fullmatch(version):
        raise ReleaseError(
            f"{origin}: version {version!r} must look like 2.7.0"
            " (digits and dots, optional -suffix, no leading 'v')"
        )
    return version


def read_version(root: Path) -> str:
    path = root / "VERSION"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ReleaseError(f"{path} not found") from None
    except UnicodeDecodeError:
        raise ReleaseError(f"{path} is not UTF-8 text") from None
    return check_version(text.strip(), str(path))


def path_problem(path: str) -> Optional[str]:
    """Return why a POSIX relative path is unsafe or unportable, else None."""

    if not path:
        return "empty path"
    if path.startswith("/"):
        return "absolute path"
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return "not valid UTF-8"
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return "empty, '.' or '..' path component"
        if UNSAFE_CHARS_RE.search(part):
            return "control character, backslash or colon in the path"
    return None


def is_excluded(path: str) -> bool:
    """Files that never ship: bytecode caches, .DS_Store, evals/results/."""

    parts = path.split("/")
    if "__pycache__" in parts or parts[-1] == ".DS_Store" or parts[-1].endswith(".pyc"):
        return True
    return any(
        parts[i] == "evals" and parts[i + 1] == "results" for i in range(len(parts) - 2)
    )


def in_release_set(path: str) -> bool:
    return path.startswith(PLUGIN_DIR + "/") or path in REQUIRED_FILES or path in OPTIONAL_FILES


# --------------------------------------------------------------------------- git


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), "--no-optional-locks", "--literal-pathspecs", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def git_out(root: Path, *args: str) -> bytes:
    proc = git(root, *args)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise ReleaseError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def is_git_root(root: Path) -> bool:
    if shutil.which("git") is None:
        if os.path.lexists(root / ".git"):
            warn(f"{root} has .git but git is not installed; building from the file system")
        return False
    proc = git(root, "rev-parse", "--show-toplevel")
    top = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not top:
        if os.path.lexists(root / ".git"):
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise ReleaseError(f"{root} has .git but git cannot read it: {detail}")
        return False
    try:
        if os.path.samefile(top, root):
            return True
    except OSError:
        pass
    warn(f"{root} is inside the git work tree {top} but is not its top level;"
         " building from the file system (commit/tree = null)")
    return False


def _records(raw: bytes) -> List[str]:
    paths = []
    for record in raw.split(b"\0"):
        if record:
            try:
                paths.append(record.decode("utf-8"))
            except UnicodeDecodeError:
                raise ReleaseError(f"path is not valid UTF-8: {record!r}") from None
    return paths


def collect_from_git(
    root: Path, allow_dirty: bool, warned: set
) -> Tuple[List[Entry], Optional[str], Optional[str], Optional[int]]:
    """Frozen HEAD blobs, or working-tree files for an explicitly dirty local build."""

    tracked: List[Tuple[str, int]] = []
    for record in _records(git_out(root, "ls-files", "-z", "--stage", "--", *PATHSPECS)):
        meta, _, path = record.partition("\t")
        if not in_release_set(path):
            continue
        mode, _object, stage = meta.split(" ")
        if stage != "0":
            raise ReleaseError(f"{path}: unmerged in the index; resolve the conflict first")
        if mode == "120000":
            raise ReleaseError(f"{path}: symlinks are not allowed in the release")
        if mode == "160000":
            raise ReleaseError(f"{path}: submodules are not allowed in the release")
        if mode not in ("100644", "100755"):
            raise ReleaseError(f"{path}: unsupported git file mode {mode}")
        if is_excluded(path):
            warn(f"{path}: tracked, but cache/OS/eval-result files never ship; skipped")
            continue
        tracked.append((path, 0o755 if mode == "100755" else 0o644))

    head = git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    commit = head.stdout.decode("ascii").strip() if head.returncode == 0 else None
    tree = commit_time = None
    if commit:
        tree = git_out(root, "rev-parse", commit + "^{tree}").decode("ascii").strip()
        raw_commit = git_out(root, "cat-file", "commit", commit)
        match = re.search(rb"^committer .* ([0-9]+) [+-][0-9]{4}$", raw_commit, re.M)
        commit_time = int(match.group(1)) if match else None

    status = git_out(
        root, "status", "--porcelain", "-z", "--untracked-files=no", "--", *PATHSPECS
    )
    changed = [rec[3:] for rec in _records(status) if len(rec) > 3 and rec[2] == " "]
    dirty = bool(status) or commit is None
    if dirty:
        what = ", ".join(changed[:8]) + (" ..." if len(changed) > 8 else "")
        reason = f"files differ from HEAD: {what}" if changed else "the repository has no commit"
        if not allow_dirty:
            raise ReleaseError(
                f"release input does not match a commit ({reason}). Commit the changes,"
                " or pass --allow-dirty for a local test build (commit/tree are then null)."
            )
        warn(f"--allow-dirty: {reason}; recording commit/tree as null")
        commit = tree = None

    untracked = [
        path
        for path in _records(
            git_out(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *PATHSPECS)
        )
        if in_release_set(path) and not is_excluded(path)
    ]
    for path in untracked[:10]:
        warn(f"{path}: not tracked by git; not shipped")
    if len(untracked) > 10:
        warn(f"... and {len(untracked) - 10} more untracked files; not shipped")
    warned.update(untracked)

    if commit is not None:
        # Index flags such as assume-unchanged/skip-worktree can hide edits from status.
        # Only immutable object bytes may carry the recorded commit/tree identity.
        entries: List[Entry] = []
        for record in _records(git_out(root, "ls-tree", "-r", "-z", commit, "--", *PATHSPECS)):
            meta, _, path = record.partition("\t")
            mode, kind, object_id = meta.split(" ")
            if not in_release_set(path) or is_excluded(path):
                continue
            if kind != "blob" or mode not in ("100644", "100755"):
                raise ReleaseError(f"{path}: unsupported frozen Git entry {mode} {kind}")
            entries.append((path, 0o755 if mode == "100755" else 0o644,
                            git_out(root, "cat-file", "blob", object_id)))
        return entries, commit, tree, commit_time

    entries: List[Entry] = []
    checked: set = set()
    for path, mode in tracked:
        if not os.path.lexists(root / path) and allow_dirty:
            warn(f"{path}: deleted in the working tree; skipped")
            continue
        data, _ = read_regular(root, path, checked)
        entries.append((path, mode, data))
    return entries, commit, tree, commit_time


# ------------------------------------------------------------------ file system


def read_regular(root: Path, path: str, checked: set) -> Tuple[bytes, int]:
    """Read a regular file; refuse symlinks anywhere on its path below root."""

    parts = path.split("/")
    for depth in range(1, len(parts)):
        parent = "/".join(parts[:depth])
        if parent not in checked:
            if os.path.islink(root / parent):
                raise ReleaseError(f"{parent}: symlinks are not allowed in the release")
            checked.add(parent)
    full = root / path
    try:
        info = os.lstat(full)
    except FileNotFoundError:
        raise ReleaseError(f"{path}: listed but missing from the working tree") from None
    if stat.S_ISLNK(info.st_mode):
        raise ReleaseError(f"{path}: symlinks are not allowed in the release")
    if not stat.S_ISREG(info.st_mode):
        raise ReleaseError(f"{path}: not a regular file")
    return full.read_bytes(), info.st_mode


def collect_from_walk(root: Path) -> List[Entry]:
    entries: List[Entry] = []
    checked: set = set()

    def add(path: str) -> None:
        data, mode = read_regular(root, path, checked)
        entries.append((path, 0o755 if mode & stat.S_IXUSR else 0o644, data))

    base = root / PLUGIN_DIR
    for parent in ("plugins", PLUGIN_DIR):
        if os.path.islink(root / parent):
            raise ReleaseError(f"{parent}: symlinks are not allowed in the release")
    if base.is_dir():
        for dirpath, dirnames, filenames in os.walk(base):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            checked.add(rel_dir)
            for name in sorted(dirnames):
                rel = f"{rel_dir}/{name}"
                if is_excluded(rel + "/x"):
                    dirnames.remove(name)
                elif os.path.islink(os.path.join(dirpath, name)):
                    raise ReleaseError(f"{rel}: symlinks are not allowed in the release")
            for name in sorted(filenames):
                rel = f"{rel_dir}/{name}"
                if not is_excluded(rel):
                    add(rel)
    for path in REQUIRED_FILES + OPTIONAL_FILES:
        if os.path.lexists(root / path):
            add(path)
    return entries


def finalize(entries: List[Entry], warned: set, hint: str = "") -> List[Entry]:
    entries = sorted(entries, key=lambda entry: entry[0])
    folded: Dict[str, str] = {}
    for path, _, _ in entries:
        problem = path_problem(path)
        if problem:
            raise ReleaseError(f"{path!r}: {problem}")
        parts = path.split("/")
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            other = folded.setdefault(prefix.casefold(), prefix)
            if other != prefix:
                raise ReleaseError(f"{prefix!r} and {other!r} differ only by letter case")
    present = {path for path, _, _ in entries}
    if not any(path.startswith(PLUGIN_DIR + "/") for path in present):
        raise ReleaseError(f"{PLUGIN_DIR}/ is required but has no files{hint}")
    for path in REQUIRED_FILES:
        if path not in present:
            raise ReleaseError(f"{path} is required but missing{hint}")
    for path in OPTIONAL_FILES:
        if path not in present and path not in warned:
            warn(f"{path}: not found; skipped")
    return entries


# ------------------------------------------------------------------------ build


def source_date(commit_time: Optional[int]) -> Tuple[int, str]:
    raw = os.environ.get("SOURCE_DATE_EPOCH", "")
    if raw:
        if not raw.isdigit() or not raw.isascii() or int(raw) > MAX_MTIME:
            raise ReleaseError(f"SOURCE_DATE_EPOCH={raw!r} is not a valid Unix time")
        return int(raw), "SOURCE_DATE_EPOCH"
    if commit_time is not None:
        if commit_time > MAX_MTIME:
            raise ReleaseError("HEAD commit time is out of range; set SOURCE_DATE_EPOCH")
        return commit_time, "HEAD commit time"
    return 0, "no commit time"


def tar_bytes(top: str, entries: List[Entry], mtime: int) -> bytes:
    directories = {top}
    for path, _, _ in entries:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            directories.add(top + "/" + "/".join(parts[:depth]))
    members: List[Tuple[str, Optional[int], Optional[bytes]]] = [
        (name, None, None) for name in directories
    ]
    members += [(f"{top}/{path}", mode, data) for path, mode, data in entries]
    members.sort(key=lambda member: member[0])
    buffer = io.BytesIO()
    with tarfile.open(
        fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT, encoding="utf-8"
    ) as archive:
        for name, mode, data in members:
            info = tarfile.TarInfo(name)
            info.mtime = mtime
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)
            else:
                info.mode = mode
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def gzip_bytes(data: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as gz:
        gz.write(data)
    return buffer.getvalue()


def manifest_bytes(
    version: str,
    commit: Optional[str],
    tree: Optional[str],
    entries: List[Entry],
    tarball_name: str,
    tarball: bytes,
) -> bytes:
    files = [{"path": path, "size": len(data), "sha256": sha256(data)} for path, _, data in entries]
    tar = {"name": tarball_name, "size": len(tarball), "sha256": sha256(tarball)}
    document = {
        "name": NAME,
        "version": version,
        "commit": commit,
        "tree": tree,
        "files": files,
        "tarball": tar,
        # identity of the exact asset set a readback must find (AC26/AC27): every file plus the tarball
        "asset_set_id": asset_set_id(files, tar),
        "build": {"python": platform.python_version(), "platform": platform.platform(), "tool": f"{NAME} release.py"},
    }
    return (json.dumps(document, indent=2) + "\n").encode("ascii")


def asset_set_id(files: List[dict], tar: dict) -> str:
    items = sorted(f"{item['path']}:{item['size']}:{item['sha256']}" for item in files)
    items.append(f"{tar['name']}:{tar['size']}:{tar['sha256']}")
    return sha256("\n".join(items).encode("utf-8"))


def sums_bytes(files: Dict[str, bytes]) -> bytes:
    lines = [f"{sha256(data)}  {name}\n" for name, data in sorted(files.items())]
    return "".join(lines).encode("ascii")


def prepare_out(out: Path, root: Path, tarball_name: str) -> None:
    try:
        out.resolve().relative_to((root / PLUGIN_DIR).resolve())
    except ValueError:
        pass
    else:
        raise ReleaseError(f"--out {out} must not be inside {PLUGIN_DIR}/")
    ours = {tarball_name, MANIFEST, SUMS, SIG}
    out.mkdir(parents=True, exist_ok=True)
    others = sorted(
        child.name
        for child in out.iterdir()
        if child.name not in ours and not (child.name.endswith(".tmp") and child.name[:-4] in ours)
    )
    if others:
        raise ReleaseError(
            f"{out} already holds other files ({', '.join(others[:5])});"
            " use an empty or dedicated output directory"
        )
    for name in sorted(ours):
        for path in (out / name, out / (name + ".tmp")):
            if path.is_symlink() or path.is_dir():
                raise ReleaseError(f"{path} must be a regular file")
            if path.name.endswith(".tmp") and path.exists():
                path.unlink()
    if (out / SIG).exists():
        (out / SIG).unlink()
        warn(f"removed the stale {SIG}; sign the new {SUMS} again")


def write_atomic(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def cmd_build(args: argparse.Namespace) -> int:
    root = resolve_root(args)
    warned: set = set()
    if is_git_root(root):
        entries, commit, tree, commit_time = collect_from_git(root, args.allow_dirty, warned)
        origin, hint = "git", " (inside git only tracked files count)"
    else:
        entries, commit, tree, commit_time = collect_from_walk(root), None, None, None
        origin, hint = "the file system (no git: commit/tree = null)", ""

    def input_version() -> str:
        if commit is None:
            return read_version(root)
        raw = next((data for path, _mode, data in entries if path == "VERSION"), None)
        if raw is None:
            raise ReleaseError(f"{commit}: VERSION not found in frozen source")
        try:
            return check_version(raw.decode("utf-8").strip(), f"{commit}:VERSION")
        except UnicodeDecodeError:
            raise ReleaseError(f"{commit}:VERSION is not UTF-8 text") from None

    if args.version:
        version = check_version(args.version, "--version")
        try:
            file_version: Optional[str] = input_version()
        except ReleaseError:
            file_version = None
        if file_version != version:
            warn(f"--version {version} differs from VERSION ({file_version})")
    else:
        version = input_version()
    entries = finalize(entries, warned, hint)
    mtime, mtime_origin = source_date(commit_time)

    top = f"{NAME}-{version}"
    tarball_name = f"{top}.tar.gz"
    tarball = gzip_bytes(tar_bytes(top, entries, mtime))
    manifest = manifest_bytes(version, commit, tree, entries, tarball_name, tarball)
    sums = sums_bytes({tarball_name: tarball, MANIFEST: manifest})

    out = Path(args.out)
    prepare_out(out, root, tarball_name)
    write_atomic(out / tarball_name, tarball)
    write_atomic(out / MANIFEST, manifest)
    write_atomic(out / SUMS, sums)

    size = sum(len(data) for _, _, data in entries)
    print(f"built {NAME} {version} from {origin}")
    if commit:
        print(f"  source   commit {commit}, tree {tree}")
    print(f"  content  {len(entries)} files, {size} bytes; mtime {mtime} ({mtime_origin})")
    for name, data in ((tarball_name, tarball), (MANIFEST, manifest), (SUMS, sums)):
        print(f"  {sha256(data)}  {out / name} ({len(data)} bytes)")
    return 0


# ----------------------------------------------------------------------- verify


def load_ed25519():
    path = Path(__file__).resolve().with_name("ed25519_verify.py")
    if not path.is_file():
        raise ReleaseError(f"{path} is missing; it is needed to check signatures")
    spec = importlib.util.spec_from_file_location("goal_teams_ed25519_verify", path)
    if spec is None or spec.loader is None:
        raise ReleaseError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_sums(directory: Path) -> Tuple[Optional[bytes], Dict[str, str], List[str]]:
    path = directory / SUMS
    if path.is_symlink() or not path.is_file():
        return None, {}, [f"{SUMS} is missing"]
    data = path.read_bytes()
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return data, {}, [f"{SUMS} is not ASCII text"]
    problems: List[str] = []
    entries: Dict[str, str] = {}
    if text and not text.endswith("\n"):
        problems.append(f"{SUMS} does not end with a newline")
    for number, line in enumerate(text.split("\n")[:-1] if text.endswith("\n") else text.split("\n"), 1):
        match = SUMS_LINE_RE.fullmatch(line)
        if match is None:
            problems.append(f"{SUMS} line {number} is not '<sha256>  <file>': {line!r}")
            continue
        digest, name = match.groups()
        if path_problem(name) or "/" in name or name in (SUMS, SIG):
            problems.append(f"{SUMS} line {number}: bad file name {name!r}")
        elif name in entries:
            problems.append(f"{SUMS} lists {name!r} twice")
        else:
            entries[name] = digest
    if not entries:
        problems.append(f"{SUMS} lists no files")
    for name, digest in sorted(entries.items()):
        target = directory / name
        if target.is_symlink() or not target.is_file():
            problems.append(f"{name}: listed in {SUMS} but missing")
        elif sha256_file(target) != digest:
            problems.append(f"{name}: SHA-256 does not match {SUMS}")
    allowed = set(entries) | {SUMS, SIG} | OS_METADATA
    for child in sorted(directory.iterdir()):
        if child.name not in allowed:
            problems.append(f"{child.name}: unexpected file, not covered by {SUMS}")
    return data, entries, problems


def check_signature(
    directory: Path, sums: Optional[bytes], pubkey: Optional[str], root: Path
) -> Tuple[str, List[str]]:
    sig_path = directory / SIG
    if not sig_path.exists():
        if pubkey:
            return "missing", [f"--pubkey was given but {SIG} is missing (expected a signed release)"]
        return "none: no SHA256SUMS.sig, so integrity only; authenticity NOT verified", []
    key_path = Path(pubkey) if pubkey else root / DEFAULT_PUBKEY
    if not key_path.is_file():
        if pubkey:
            return "failed", [f"public key {key_path} not found"]
        return "failed", [
            f"{SIG} is present but no public key is available:"
            f" pass --pubkey PATH or add {DEFAULT_PUBKEY}"
        ]
    ed25519 = load_ed25519()
    try:
        key = ed25519.load_public_key(key_path.read_bytes())
    except ValueError as exc:
        return "failed", [f"{key_path}: {exc}"]
    signature = sig_path.read_bytes() if sig_path.is_file() and not sig_path.is_symlink() else b""
    if len(signature) != 64:
        return "failed", [f"{SIG} must be a raw 64-byte Ed25519 signature (got {len(signature)} bytes)"]
    if sums is None:
        return "failed", [f"cannot check {SIG} without {SUMS}"]
    if not ed25519.verify(key, sums, signature):
        return "failed", [f"{SIG} is not a valid Ed25519 signature of {SUMS} for {key_path}"]
    return f"ok (Ed25519, key {key_path}, key sha256 {sha256(key)[:16]})", []


def is_size(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_manifest(document: object) -> List[str]:
    if not isinstance(document, dict):
        return [f"{MANIFEST} must be a JSON object"]
    missing = [key for key in ("name", "version", "commit", "tree", "files", "tarball") if key not in document]
    if missing:
        return [f"{MANIFEST} lacks {', '.join(missing)}"]
    problems: List[str] = []
    if document["name"] != NAME:
        problems.append(f"{MANIFEST}: name is {document['name']!r}, expected {NAME!r}")
    version = document["version"]
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        return problems + [f"{MANIFEST}: invalid version {version!r}"]
    for key in ("commit", "tree"):
        value = document[key]
        if value is not None and not (isinstance(value, str) and OBJECT_ID_RE.fullmatch(value)):
            problems.append(f"{MANIFEST}: {key} must be null or a git object id")
    files = document["files"]
    if not isinstance(files, list) or not files:
        return problems + [f"{MANIFEST}: files must be a non-empty list"]
    seen = set()
    for index, item in enumerate(files):
        path = item.get("path") if isinstance(item, dict) else None
        if not isinstance(path, str) or path_problem(path):
            problems.append(f"{MANIFEST}: files[{index}] has an unsafe or missing path {path!r}")
        elif not is_size(item.get("size")) or not (
            isinstance(item.get("sha256"), str) and HEX64_RE.fullmatch(item["sha256"])
        ):
            problems.append(f"{MANIFEST}: {path} needs an integer size and a sha256")
        elif path in seen:
            problems.append(f"{MANIFEST}: {path} is listed twice")
        seen.add(path)
    tarball = document["tarball"]
    expected_name = f"{NAME}-{version}.tar.gz"
    if not isinstance(tarball, dict) or tarball.get("name") != expected_name:
        problems.append(f"{MANIFEST}: tarball.name must be {expected_name}")
    elif not is_size(tarball.get("size")) or not (
        isinstance(tarball.get("sha256"), str) and HEX64_RE.fullmatch(tarball["sha256"])
    ):
        problems.append(f"{MANIFEST}: tarball needs an integer size and a sha256")
    elif not problems and "asset_set_id" in document:
        recorded = document["asset_set_id"]
        if not (isinstance(recorded, str) and HEX64_RE.fullmatch(recorded)):
            problems.append(f"{MANIFEST}: asset_set_id must be a sha256")
        elif recorded != asset_set_id(files, tarball):
            problems.append(f"{MANIFEST}: asset_set_id does not match the listed files and tarball")
    return problems


def check_manifest(directory: Path, listed: Dict[str, str]) -> Tuple[Optional[dict], List[str]]:
    path = directory / MANIFEST
    if path.is_symlink() or not path.is_file():
        return None, [f"{MANIFEST} is missing"]
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, [f"{MANIFEST} is not valid JSON: {exc}"]
    problems = validate_manifest(document)
    if problems:
        return None, problems
    tarball = document["tarball"]
    name = tarball["name"]
    for required in (MANIFEST, name):
        if required not in listed:
            problems.append(f"{SUMS} does not list {required}")
    extra = sorted(set(listed) - {MANIFEST, name})
    if extra:
        problems.append(f"{SUMS} lists files that are not part of the release: {', '.join(extra)}")
    tar_path = directory / name
    if tar_path.is_symlink() or not tar_path.is_file():
        problems.append(f"{name} is missing")
    else:
        if tar_path.stat().st_size != tarball["size"]:
            problems.append(f"{name}: size differs from {MANIFEST}")
        if sha256_file(tar_path) != tarball["sha256"]:
            problems.append(f"{name}: SHA-256 differs from {MANIFEST}")
    return document, problems


def member_kind(member: tarfile.TarInfo) -> str:
    if member.issym():
        return "symlink"
    if member.islnk():
        return "hard link"
    if member.ischr() or member.isblk():
        return "device"
    if member.isfifo():
        return "fifo"
    if member.issparse():
        return "sparse file"
    return f"type {member.type!r}"


def check_tarball(tar_path: Path, document: dict) -> Tuple[str, List[str]]:
    """Scan every member without extracting anything."""

    top = f"{NAME}-{document['version']}"
    expected = {item["path"]: (item["size"], item["sha256"]) for item in document["files"]}
    implied = {top}
    for path in expected:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            implied.add(top + "/" + "/".join(parts[:depth]))
    problems: List[str] = []
    seen: set = set()
    folded: Dict[str, str] = {}
    directories: set = set()
    found: Dict[str, Tuple[int, str]] = {}
    total = 0
    try:
        with tarfile.open(tar_path, mode="r:gz", encoding="utf-8") as archive:
            complete = True
            for count, member in enumerate(archive, 1):
                name = member.name
                total += member.size
                if count > MAX_MEMBERS or total > MAX_TOTAL_BYTES:
                    problems.append(f"more than {MAX_MEMBERS} members or {MAX_TOTAL_BYTES} bytes")
                    complete = False
                    break
                problem = path_problem(name)
                if problem:
                    problems.append(f"member {name!r}: {problem}")
                    continue
                parts = name.split("/")
                if parts[0] != top:
                    problems.append(f"member {name!r}: outside the top directory {top}/")
                    continue
                if name in seen:
                    problems.append(f"member {name!r}: duplicate")
                    continue
                seen.add(name)
                other = folded.setdefault(name.casefold(), name)
                if other != name:
                    problems.append(f"member {name!r}: differs only by case from {other!r}")
                    continue
                unexpected_pax = sorted(set(member.pax_headers) - {"path"})
                if unexpected_pax:
                    problems.append(f"member {name!r}: unexpected PAX records {unexpected_pax}")
                parent = "/".join(parts[:-1])
                if parent and parent not in directories:
                    problems.append(f"member {name!r}: its directory entry is missing or comes later")
                if member.isdir():
                    if member.mode != 0o755:
                        problems.append(f"directory {name!r}: mode {member.mode:o}, expected 755")
                    directories.add(name)
                elif member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and len(parts) > 1:
                    if member.mode not in (0o644, 0o755):
                        problems.append(f"member {name!r}: mode {member.mode:o}, expected 644 or 755")
                    digest = hashlib.sha256()
                    handle = archive.extractfile(member)
                    size = 0
                    for chunk in iter(lambda: handle.read(CHUNK), b""):
                        digest.update(chunk)
                        size += len(chunk)
                    found["/".join(parts[1:])] = (size, digest.hexdigest())
                elif len(parts) == 1:
                    problems.append(f"member {name!r}: the top-level entry must be a directory")
                else:
                    problems.append(f"member {name!r}: {member_kind(member)} entries are not allowed")
            if complete:
                stream = archive.fileobj
                stream.seek(archive.offset)
                for chunk in iter(lambda: stream.read(CHUNK), b""):
                    if chunk.strip(b"\0"):
                        problems.append("data after the end-of-archive marker (hidden or corrupt members)")
                        break
            if archive.pax_headers:
                problems.append("global PAX headers are not allowed")
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:
        problems.append(f"cannot read {tar_path.name}: {exc}")
        return "failed", problems

    missing = sorted(set(expected) - set(found))
    extra = sorted(set(found) - set(expected))
    problems += [f"{path}: listed in {MANIFEST} but not in the tarball" for path in missing[:10]]
    problems += [f"{path}: in the tarball but not listed in {MANIFEST}" for path in extra[:10]]
    for path in sorted(set(expected) & set(found)):
        if found[path] != expected[path]:
            problems.append(f"{path}: size or SHA-256 differs from {MANIFEST}")
    for name in sorted(directories - implied)[:10]:
        problems.append(f"directory {name!r}: not implied by any file in {MANIFEST}")
    size = sum(size for size, _ in found.values())
    return f"ok ({len(found)} files, {size} bytes, top directory {top}/)", problems


def cmd_verify(args: argparse.Namespace) -> int:
    root = resolve_root(args)
    directory = Path(args.dir)
    if not directory.is_dir():
        raise ReleaseError(f"{directory} is not a directory")
    print(f"verify {directory}")
    failures = 0

    def report(label: str, summary: str, problems: List[str]) -> None:
        nonlocal failures
        failures += len(problems)
        print(f"  {label:<13}{'FAILED' if problems else summary}")
        for problem in problems:
            print(f"    - {problem}")

    sums, listed, problems = check_sums(directory)
    report(SUMS, f"ok ({len(listed)} files match)", problems)
    summary, problems = check_signature(directory, sums, args.pubkey, root)
    report("signature", summary, problems)
    document, problems = check_manifest(directory, listed)
    source = "none recorded"
    if document is not None and document["commit"]:
        source = f"commit {document['commit']}, tree {document['tree']} (recorded; not checked against git)"
    version = document["version"] if document is not None else "?"
    report(MANIFEST, f"ok ({NAME} {version}; source {source})", problems)
    tar_path = directory / f"{NAME}-{version}.tar.gz"
    if document is not None and tar_path.is_file() and not tar_path.is_symlink():
        summary, problems = check_tarball(tar_path, document)
        report("tarball", summary, problems)
    else:
        report("tarball", "", ["not checked: release.json or the tarball is missing or invalid"])
    if failures:
        print(f"RESULT: FAILED ({failures} problem{'s' if failures != 1 else ''})")
        return 1
    print("RESULT: OK")
    return 0


# ------------------------------------------------------------- notes, check-tag


def changelog_section(text: str, version: str) -> Optional[str]:
    """Body of the first '## ' heading naming `version` (3.0.0 also matches 3.0)."""

    lines = text.split("\n")
    headings: List[Tuple[int, int]] = []
    fence: Optional[str] = None
    for index, line in enumerate(lines):
        stripped = line.lstrip(" ")
        if len(line) - len(stripped) <= 3 and stripped[:3] in ("```", "~~~"):
            if fence is None:
                fence = stripped[:3]
            elif stripped[:3] == fence:
                fence = None
            continue
        match = re.match(r"(#{1,2})(?:[ \t]|$)", line) if fence is None else None
        if match:
            headings.append((index, len(match.group(1))))
    candidates = [version]
    short = re.fullmatch(r"([0-9]+\.[0-9]+)\.0", version)
    if short:
        candidates.append(short.group(1))
    for candidate in candidates:
        pattern = re.compile(
            r"(?<![0-9A-Za-z.])[vV]?" + re.escape(candidate) + r"(?![0-9A-Za-z]|[.+-][0-9A-Za-z])"
        )
        for position, (index, level) in enumerate(headings):
            if level == 2 and pattern.search(lines[index]):
                end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
                return "\n".join(lines[index + 1:end]).strip("\n") + "\n"
    return None


def write_stdout(text: str) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def cmd_notes(args: argparse.Namespace) -> int:
    root = resolve_root(args)
    version = check_version(args.version[1:] if args.version[:1] in ("v", "V") else args.version, "notes")
    path = root / "CHANGELOG.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ReleaseError(f"{path} not found") from None
    body = changelog_section(text, version)
    if body is None:
        raise ReleaseError(f"{path} has no '## ' heading for version {version}")
    if not body.strip():
        raise ReleaseError(f"the {path.name} section for {version} is empty")
    write_stdout(body)
    return 0


def cmd_check_tag(args: argparse.Namespace) -> int:
    version = read_version(resolve_root(args))
    expected = "v" + version
    if args.tag == expected:
        print(f"ok: tag {expected} matches VERSION {version}")
        return 0
    print(f"error: tag {args.tag!r} does not match VERSION {version!r}; expected {expected!r}",
          file=sys.stderr)
    return 1


# -------------------------------------------------------------------------- cli


def resolve_root(args: argparse.Namespace) -> Path:
    return Path(args.root).resolve() if args.root else TOOL_ROOT


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="repository root (default: the repository holding this tool)")
    parser = argparse.ArgumentParser(
        prog="release.py",
        description="Build, verify and describe Goal Teams releases.",
        epilog="Exit status: 0 ok, 1 failed or refused, 2 usage error.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    build = commands.add_parser("build", parents=[common], help="build the release assets once")
    build.add_argument("--out", default="dist", help="output directory (default: dist)")
    build.add_argument("--version", help="version to build (default: contents of VERSION)")
    build.add_argument("--allow-dirty", action="store_true",
                       help="allow input that differs from HEAD; commit/tree are recorded as null")
    build.set_defaults(func=cmd_build)

    verify = commands.add_parser("verify", parents=[common], help="verify downloaded release assets")
    verify.add_argument("dir", help="directory holding the downloaded assets")
    verify.add_argument("--pubkey", help=f"Ed25519 public key (default when signed: {DEFAULT_PUBKEY})")
    verify.set_defaults(func=cmd_verify)

    notes = commands.add_parser("notes", parents=[common], help="print the CHANGELOG.md section")
    notes.add_argument("version", help="version, e.g. 2.7.0")
    notes.set_defaults(func=cmd_notes)

    check_tag = commands.add_parser("check-tag", parents=[common], help="require TAG == v + VERSION")
    check_tag.add_argument("tag")
    check_tag.set_defaults(func=cmd_check_tag)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
