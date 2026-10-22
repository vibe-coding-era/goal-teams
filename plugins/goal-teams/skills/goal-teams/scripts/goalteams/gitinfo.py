"""Read-only git helpers. gt never commits, pushes or rewrites anything."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .util import GTError, remote_protocol, sanitize_url, sha256_file

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
STATE_DIRNAME = ".goal-teams"
WALK_SKIP_DIRS = {
    ".git", STATE_DIRNAME, "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".tox", "dist", "build", ".idea", ".vscode", ".gradle", "target",
}
WALK_FILE_LIMIT = 20000
# Build/cache noise that is never part of a change set, even when a repo forgot to ignore it.
DEFAULT_IGNORE = ("**/__pycache__/**", "**/*.pyc", "**/*.pyo", "**/.DS_Store", "**/.pytest_cache/**",
                  "**/.mypy_cache/**", "**/Thumbs.db")


def ignored(path: str) -> bool:
    from .util import matches_any
    return path.startswith(STATE_DIRNAME + "/") or matches_any(path, DEFAULT_IGNORE)


def git_available() -> bool:
    return shutil.which("git") is not None


def normalize_rel(path: str) -> str:
    """``./a\\b`` -> ``a/b`` (keeps leading dots of names such as ``.github``)."""
    value = str(path).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/")


def _env() -> Dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_OPTIONAL_LOCKS", "0")
    return env


def run_git(args: Sequence[str], cwd: Path, binary: bool = False) -> subprocess.CompletedProcess:
    if binary:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, env=_env())
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=_env(),
    )


def _out(args: Sequence[str], cwd: Path) -> Optional[str]:
    if not git_available():
        return None
    try:
        result = run_git(args, cwd)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def toplevel(cwd: Path) -> Optional[Path]:
    value = _out(["rev-parse", "--show-toplevel"], cwd)
    return Path(value).resolve() if value else None


def main_root(cwd: Path) -> Optional[Path]:
    """Root of the main worktree (linked worktrees share the main project's state)."""
    common = _out(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    if common is None:
        common = _out(["rev-parse", "--git-common-dir"], cwd)
        if common is not None and not os.path.isabs(common):
            common = str((cwd / common).resolve())
    if common:
        path = Path(common).resolve()
        if path.name == ".git":
            return path.parent
    return toplevel(cwd)


def is_linked_worktree(cwd: Path) -> bool:
    git_dir = _out(["rev-parse", "--path-format=absolute", "--git-dir"], cwd)
    common = _out(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    return bool(git_dir and common and Path(git_dir).resolve() != Path(common).resolve())


def head(cwd: Path) -> Optional[str]:
    return _out(["rev-parse", "--verify", "-q", "HEAD"], cwd) or None


def branch(cwd: Path) -> Optional[str]:
    name = _out(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
    return name or None


def default_branch(cwd: Path) -> Optional[str]:
    ref = _out(["symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"], cwd)
    if ref and "/" in ref:
        return ref.split("/", 1)[1]
    for candidate in ("main", "master", "trunk"):
        if _out(["rev-parse", "--verify", "-q", "refs/heads/" + candidate], cwd):
            return candidate
    return None


def remotes(cwd: Path) -> List[Dict[str, str]]:
    raw = _out(["remote", "-v"], cwd)
    seen = []
    out: List[Dict[str, str]] = []
    for line in (raw or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "(fetch)" and parts[0] not in seen:
            seen.append(parts[0])
            url = sanitize_url(parts[1])
            out.append({"name": parts[0], "url": url, "protocol": remote_protocol(url)})
    return out


def _z(args: Sequence[str], cwd: Path) -> List[str]:
    if not git_available():
        return []
    result = run_git(args, cwd)
    if result.returncode != 0:
        return []
    return [item for item in result.stdout.split("\0") if item]


def status_counts(cwd: Path) -> Dict[str, int]:
    entries = _z(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd)
    counts = {"changed": 0, "untracked": 0}
    for entry in entries:
        if len(entry) < 4 or entry[2] != " " or ignored(entry[3:]):
            continue
        counts["untracked" if entry.startswith("??") else "changed"] += 1
    return counts


def untracked(cwd: Path) -> List[str]:
    """Untracked, not ignored files (nested repositories and worktrees are not part of this tree)."""
    return sorted(p for p in _z(["ls-files", "--others", "--exclude-standard", "-z"], cwd)
                  if not ignored(p) and not p.endswith("/"))


def nested_repos(cwd: Path) -> List[str]:
    """Untracked directories that are git repositories or worktrees of their own."""
    return sorted(p.rstrip("/") for p in _z(["ls-files", "--others", "--exclude-standard", "--directory", "-z"], cwd)
                  if p.endswith("/") and (cwd / p / ".git").exists())


def paths_in_commit(cwd: Path, commit: Optional[str], paths: Iterable[str]) -> List[str]:
    """Which of ``paths`` existed in ``commit`` (e.g. the goal baseline)."""
    wanted = sorted({normalize_rel(p) for p in paths})
    if not commit or not wanted:
        return []
    return sorted(set(_z(["ls-tree", "-r", "-z", "--name-only", commit, "--", *wanted], cwd)) & set(wanted))


def tracked(cwd: Path) -> List[str]:
    """Paths in the index (tracked by git)."""
    return sorted(set(_z(["ls-files", "-z"], cwd)))


def tracked_and_untracked(cwd: Path) -> List[str]:
    files = _z(["ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd)
    return sorted({p for p in files if not ignored(p) and not p.endswith("/")})


def changed_since(cwd: Path, base: Optional[str]) -> List[Tuple[str, str]]:
    """``[(status, path)]`` for working tree vs ``base`` (A/M/D/T), renames split."""
    entries = _z(["diff", "--name-status", "-z", "--no-renames", base or EMPTY_TREE], cwd)
    out: List[Tuple[str, str]] = []
    for i in range(0, len(entries) - 1, 2):
        out.append((entries[i][:1], entries[i + 1]))
    return out


def _walk_files(root: Path) -> List[str]:
    files: List[str] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in WALK_SKIP_DIRS)
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if ignored(rel):
                continue
            files.append(rel)
            if len(files) > WALK_FILE_LIMIT:
                raise GTError("这个目录不是 git 仓库，且文件超过 %d 个，gt 无法计算源码摘要。" % WALK_FILE_LIMIT,
                              hint="在 git 仓库里使用 gt（git init 即可），或用 --root 指向更小的项目目录。")
    return files


def is_repo(cwd: Path) -> bool:
    return toplevel(cwd) is not None


def object_format(cwd: Path) -> str:
    value = _out(["rev-parse", "--show-object-format"], cwd)
    return value if value in ("sha1", "sha256") else "sha1"


def _blob_id(data: bytes, algo: str) -> str:
    return hashlib.new(algo, b"blob %d\0" % len(data) + data).hexdigest()


def _hash_paths(work_tree: Path, paths: List[str]) -> Dict[str, str]:
    """Blob ids of working-tree files, computed the way ``git add`` would (filters, eol)."""
    out: Dict[str, str] = {}
    batch = [p for p in paths if "\n" not in p and "\r" not in p]
    if batch:
        result = subprocess.run(["git", "hash-object", "--stdin-paths"], cwd=str(work_tree),
                                input="\n".join(batch) + "\n", capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=_env())
        ids = result.stdout.split()
        if result.returncode == 0 and len(ids) == len(batch):
            out.update(zip(batch, ids))
    for path in paths:
        if path not in out:
            result = run_git(["hash-object", "--", path], work_tree)
            out[path] = result.stdout.strip() if result.returncode == 0 else \
                "unreadable:" + hashlib.sha256(path.encode("utf-8", "surrogateescape")).hexdigest()
    return out


def content_ids(work_tree: Path) -> Dict[str, str]:
    """``{path: object id}`` of every existing tracked or untracked (not ignored) file.

    Ids describe the working-tree content only, so commits, staging and other
    history operations never change the result; only editing files does.
    """
    index: Dict[str, Tuple[str, str]] = {}
    dirty = set()
    for entry in _z(["ls-files", "-s", "-z"], work_tree):
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) != 3 or not path:
            continue
        mode, oid, stage = parts
        index[path] = (mode, oid)
        if stage != "0":
            dirty.add(path)
    dirty.update(_z(["diff-files", "-z", "--name-only"], work_tree))
    others = [p for p in _z(["ls-files", "--others", "--exclude-standard", "-z"], work_tree)
              if not p.endswith("/")]
    ids: Dict[str, str] = {}
    files: List[str] = []
    algo = None
    for path in [p for p in index if p in dirty] + others:
        full = work_tree / path
        if not os.path.lexists(str(full)):
            continue  # deleted in the working tree
        mode = index.get(path, ("", ""))[0]
        if full.is_symlink():
            algo = algo or object_format(work_tree)
            ids[path] = _blob_id(os.fsencode(os.readlink(str(full))), algo)
        elif full.is_dir():
            if mode == "160000":  # submodule: its checked-out commit
                ids[path] = _out(["rev-parse", "HEAD"], full) or index[path][1]
        else:
            files.append(path)
    ids.update(_hash_paths(work_tree, files))
    for path, (mode, oid) in index.items():
        if path not in dirty:
            ids[path] = oid
    return ids


def tree_ids(work_tree: Path) -> Tuple[Dict[str, str], str]:
    """``({path: content id}, method)`` for every file of the tree (see :func:`content_ids`)."""
    if is_repo(work_tree):
        return content_ids(work_tree), "git"
    return {path: sha256_file(work_tree / path) for path in _walk_files(work_tree)}, "walk"


def digest_ids(ids: Dict[str, str], keep: Optional[Callable[[str], bool]] = None) -> str:
    digest = hashlib.sha256()
    for path, oid in sorted(ids.items()):
        if ignored(path) or (keep is not None and not keep(path)):
            continue
        digest.update(("%s\0%s\n" % (path, oid)).encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def source_digest(work_tree: Path, exclude: Iterable[str] = (),
                  skip: Optional[Callable[[str], bool]] = None) -> Tuple[str, str]:
    """Digest of the source content, excluding the given paths, ``skip`` matches and gt state.

    Returns ``(digest, method)``. With git it hashes the object id of every
    existing tracked and untracked file (commits alone never change it); without
    git it hashes every file under the tree (bounded).
    """
    excluded = {normalize_rel(e) for e in exclude}
    ids, method = tree_ids(work_tree)
    return digest_ids(ids, lambda p: p not in excluded and not (skip is not None and skip(p))), method


def hidden_changes(work_tree: Path) -> List[str]:
    """Existing files that git is told not to look at (assume-unchanged / skip-worktree)."""
    out: List[str] = []
    for entry in _z(["ls-files", "-v", "-z"], work_tree):
        tag, _, path = entry.partition(" ")
        if not path:
            continue
        if (tag.islower() or tag == "S") and os.path.lexists(str(work_tree / path)):
            out.append(path)
    return sorted(out)


def ignore_case(work_tree: Path) -> bool:
    return (_out(["config", "--bool", "core.ignorecase"], work_tree) or "").strip() == "true"


def files_digest(work_tree: Path, paths: Iterable[str]) -> Tuple[str, List[Dict[str, str]]]:
    entries: List[Dict[str, str]] = []
    digest = hashlib.sha256()
    for path in sorted({normalize_rel(p) for p in paths}):
        full = work_tree / path
        value = sha256_file(full) if full.is_file() else "MISSING"
        entries.append({"path": path, "sha256": value})
        digest.update(("%s:%s\n" % (path, value)).encode("utf-8"))
    return digest.hexdigest(), entries


def project_files(work_tree: Path) -> List[str]:
    """Tracked + untracked (not ignored) files; falls back to a bounded walk."""
    if is_repo(work_tree):
        return [p for p in tracked_and_untracked(work_tree) if not p.startswith(STATE_DIRNAME + "/")]
    return _walk_files(work_tree)
