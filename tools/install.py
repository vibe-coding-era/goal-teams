#!/usr/bin/env python3
"""Goal Teams installer: copy the skill and its member agents into Codex and/or Claude Code.

Usage:
  python3 tools/install.py [--host codex|claude|both] [--home DIR] [--skills-dir DIR] [--source DIR]
                           [--dry-run] [--yes]
  python3 tools/install.py --verify         [--host ...] [--home DIR] [--skills-dir DIR]
  python3 tools/install.py --uninstall      [--host ...] [--home DIR] [--skills-dir DIR] [--dry-run]
  python3 tools/install.py --list-backups   [--host ...] [--home DIR]
  python3 tools/install.py --rollback [ID]  [--host ...] [--home DIR] [--skills-dir DIR] [--dry-run]
  Add --json to any command for one machine-readable JSON document on stdout.

What goes where (<source> defaults to the folder above tools/: the git repo or an extracted release;
<pkg> is <source>/plugins/goal-teams; ~ is the user home: $HOME, on Windows %USERPROFILE%):
  codex   skill   <pkg>/skills/goal-teams         -> ~/.agents/skills/goal-teams/  (Codex user skills)
          agents  <pkg>/codex/agents/goal_*.toml  -> <home>/agents/   home: $CODEX_HOME or ~/.codex
  claude  skill   <pkg>/skills/goal-teams         -> <home>/skills/goal-teams/
          agents  <pkg>/agents/goal_*.md          -> <home>/agents/   home: $CLAUDE_CONFIG_DIR or ~/.claude
  Backups go to <home>/goal-teams-backups/. For one host, --home DIR replaces its home (agents, backups
  and, for codex, the old location <home>/skills/goal-teams) and --skills-dir DIR its skills folder (the
  skill then goes to DIR/goal-teams). Default host: codex if $CODEX_HOME is set or ~/.codex exists, else
  claude if $CLAUDE_CONFIG_DIR is set or ~/.claude exists, else codex.

Safety:
  * Refuses (exit 2) when source and target overlap, e.g. a git clone living at ~/.codex/skills/goal-teams
    (where older versions told you to clone it). Keep the clone elsewhere (e.g. ~/src/goal-teams), run it
    from there.
  * Nothing is deleted: whatever is replaced or removed is MOVED into
    <home>/goal-teams-backups/<UTC time>-<host>/ together with a backup.json. A managed install is a
    folder with the manifest this installer writes; anything else at the target (an older package, a git
    clone, a manual copy) is an unmanaged directory, moved there too. Such a backup is never pruned
    automatically, and neither is one holding your own changes: a managed install is compared with its
    manifest before it is moved (as --verify does), and a backup with modified, missing or extra files, or
    agents this installer did not write, is kept until you delete it (backup.json lists the changes).
    Of the clean backups the newest 3 are kept.
  * Codex: <home>/skills/goal-teams is the old skills location, which Codex still reads. Whatever is there
    (an older package or clone, or an install by an older version of this script) goes into the same
    backup, so that Codex does not load two copies; and so do the agents of older versions,
    <home>/agents/goal-*.toml (this version uses goal_*.toml). The rest of <home>/skills (Codex's own
    .system skills, other skills) is left alone.
  * The switch is all-or-nothing: on any error everything is moved back (exit 1).
  * One install at a time: a lock file is held in <home> and next to the install target
    (<skills dir>/.goal-teams-install.lock, by real path, so that two homes installing into the same
    folder share it). A lock holds the pid and start time of its owner; one whose process has ended is
    stale and replaced. Staging copies carry the owning pid in their name and are removed only once that
    process has ended.
  * .goal-teams-install.json in the installed skill folder lists every installed file with its sha256.
    --verify checks it (and reports a second copy at the old Codex location as drift); --uninstall
    removes only those files and keeps (and reports) unknown files.
  * --rollback restores a backup (default: the newest) after backing up the current state; everything
    goes back where it came from, the old Codex location included.

Exit codes: 0 ok; 1 failed (verify found drift, or an error after which the previous state was put
back); 2 refused or usage error (nothing changed).
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MANIFEST, LOCK = ".goal-teams-install.json", ".goal-teams-install.lock"
SCHEMA, BACKUP_SCHEMA = "goal-teams/install@1", "goal-teams/backup@1"
KEEP_BACKUPS, LOCK_STALE_SECONDS = 3, 600
SKIP_NAMES = {"__pycache__", ".DS_Store", ".git", MANIFEST}  # never copied from the source
HOSTS = {  # host: (agents dir inside plugins/goal-teams, agent suffix, home env var, default home)
    "codex": ("codex/agents", ".toml", "CODEX_HOME", "~/.codex"),
    "claude": ("agents", ".md", "CLAUDE_CONFIG_DIR", "~/.claude"),
}
BACKUP_ID = re.compile(r"^(\d{8}T\d{6}Z)-(codex|claude)(?:-(\d+))?$")
AGENT_NAME = re.compile(r"^goal[-_][A-Za-z0-9_.-]+\.(?:toml|md)$")
STAGING = ".goal-teams-staging-"  # staging copies: .<key><STAGING><pid of the installer that made them>
STAGING_PID = re.compile(re.escape(STAGING) + r"(\d+)$")
SKILL_KEYS = ("skill", "legacy-skill")  # skill folders in a backup: the target, the old Codex location
DRIFT_KINDS = ("modified", "missing", "extra")
NOTHING = {"kind": "none", "what": "nothing"}


class Refused(Exception):
    """A safety or usage problem; nothing was changed (exit 2)."""


class Failed(Exception):
    """The operation failed after it started (exit 1)."""


class Out:
    """Human-readable lines, or (with --json) one JSON document printed at the end."""

    def __init__(self, as_json):
        self.as_json, self.hosts = as_json, []
        self.top = self.cur = {"messages": []}

    def begin(self, host, home):
        self.cur = {"host": host, "home": home, "messages": []}
        self.hosts.append(self.cur)

    def say(self, msg, err=False):
        if self.as_json:
            self.cur["messages"].append(msg)
        else:
            print(msg, file=sys.stderr if err else sys.stdout, flush=True)

    def data(self, **values):
        self.cur.update(values)


# ------------------------------------------------------------------ helpers
def now(fmt="%Y-%m-%dT%H:%M:%SZ"):
    return datetime.now(timezone.utc).strftime(fmt)


def fault(point):
    """Test hooks. GOAL_TEAMS_INSTALL_FAIL_AT=after_skill|after_switch simulates a failure mid-switch (the
    in-process rollback runs); GOAL_TEAMS_INSTALL_KILL_AT=<point> ends the process there without any cleanup,
    like a power cut; GOAL_TEAMS_INSTALL_WAIT_AT=locked|staged:<file> pauses there (locks held) until that
    file exists."""
    if os.environ.get("GOAL_TEAMS_INSTALL_FAIL_AT") == point:
        raise RuntimeError(f"simulated failure at {point}")
    if os.environ.get("GOAL_TEAMS_INSTALL_KILL_AT") == point:
        os._exit(70)
    wait = os.environ.get("GOAL_TEAMS_INSTALL_WAIT_AT", "")
    if wait.startswith(point + ":"):
        deadline = time.time() + 60
        while not os.path.exists(wait[len(point) + 1:]) and time.time() < deadline:
            time.sleep(0.05)


def alive(pid):
    """True or False whether the process with this id still runs, None if that cannot be told. Nothing is
    signalled: on POSIX signal 0 only checks that the process exists (os.kill with 0 would kill on Windows)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: it exists; anything else: it does not
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except (OSError, AttributeError, ImportError, ValueError):
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, it belongs to someone else
    except OSError:
        return None
    return True


def norm(path):
    return os.path.normcase(os.path.realpath(path))


def inside(path, root):
    """True if path is root or below it, by real path or by file identity (case-insensitive disks)."""
    a, b = norm(path), norm(root)
    with contextlib.suppress(ValueError):  # ValueError: different drives
        if os.path.commonpath([a, b]) == b:
            return True
    try:
        root_stat = os.stat(b)
    except OSError:
        return False
    while root_stat.st_ino and os.path.dirname(a) != a:
        with contextlib.suppress(OSError):
            if os.path.samestat(os.stat(a), root_stat):
                return True
        a = os.path.dirname(a)
    return False


def same(a, b):
    return inside(a, b) and inside(b, a)


def user_home():
    """Path.home(): $HOME, on Windows %USERPROFILE%. Codex reads user skills from <user home>/.agents/skills."""
    try:
        home = str(Path.home())
    except (RuntimeError, KeyError):  # no HOME and no password database entry
        home = ""
    if not os.path.isabs(home):
        raise Refused("cannot tell the user home: set HOME (on Windows USERPROFILE) or pass --skills-dir DIR")
    return home


def q(path):
    """A path as it can be pasted into a shell."""
    return f'"{path}"' if re.search(r"\s", path) else path


def rel_ok(rel):
    """A safe relative POSIX path (no absolute path, drive, backslash or '..')."""
    return (isinstance(rel, str) and bool(rel) and not rel.startswith("/") and "\\" not in rel
            and ":" not in rel and all(part not in ("", ".", "..") for part in rel.split("/")))


def is_cache(rel):
    parts = rel.split("/")
    return "__pycache__" in parts or rel.endswith(".pyc") or parts[-1] == ".DS_Store"


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, data):
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(path + ".tmp", path)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest(), os.path.getsize(path)


def move(src, dst):
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "destination exists", dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(src, dst)  # another filesystem: copy, then delete


def remove(path):
    def force(func, p, _exc):  # read-only files, e.g. git objects on Windows
        os.chmod(p, stat.S_IRWXU)
        func(p)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, **({"onexc": force} if sys.version_info >= (3, 12) else {"onerror": force}))
    elif os.path.lexists(path):
        try:
            os.remove(path)
        except PermissionError:
            force(os.remove, path, None)


def _raise(exc):
    raise exc


def walk_files(root):
    """Every non-directory entry below root as a POSIX path (symlinked dirs are entries, not entered)."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=_raise):
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        prefix = "" if rel == "." else rel + "/"
        found += [prefix + n for n in filenames]
        found += [prefix + d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
    return sorted(found)


def git(cwd, *args):
    """stdout of a read-only git command, or None (no git, not a repo, error). git is optional."""
    exe = shutil.which("git")
    try:
        res = subprocess.run([exe, "-C", cwd, *args], capture_output=True, encoding="utf-8", errors="replace",
                             timeout=60, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0")) if exe else None
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() if res and res.returncode == 0 else None


# ------------------------------------------------------------------ source, target, plan
class Source:
    def __init__(self, root):
        self.root = os.path.abspath(os.path.expanduser(root))
        self.package = os.path.join(self.root, "plugins", "goal-teams")
        self.skill = os.path.join(self.package, "skills", "goal-teams")
        if not os.path.isfile(os.path.join(self.skill, "SKILL.md")):
            raise Refused(f"{self.root} is not a Goal Teams source "
                          "(no plugins/goal-teams/skills/goal-teams/SKILL.md); pass --source DIR")
        if not inside(self.skill, self.root):
            raise Refused(f"{self.skill} resolves outside {self.root}; refusing to follow that link")

    def version(self):
        with contextlib.suppress(OSError), open(os.path.join(self.root, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or None
        return None

    def git_info(self):
        """(HEAD commit, dirty) when the source root is itself a git work tree, else (None, None)."""
        top = git(self.root, "rev-parse", "--show-toplevel")
        if not top or norm(top) != norm(self.root):  # no repo, or an unrelated enclosing repo
            return None, None
        status = git(self.root, "status", "--porcelain", "--", "plugins/goal-teams", "VERSION")
        return git(self.root, "rev-parse", "HEAD"), None if status is None else bool(status)

    def regular(self, path, out):
        """A regular file whose real path is inside the package (links out of it are never followed)."""
        real = os.path.realpath(path)
        if not inside(real, self.package):
            out.say(f"  warning: skipped {path}: it resolves outside the package")
        elif not os.path.isfile(real):
            out.say(f"  warning: skipped special file: {path}")
        else:
            return True
        return False

    def files(self, out):
        """Sorted (POSIX relative path, absolute path) of the skill files to install."""
        found = []
        for dirpath, dirnames, filenames in os.walk(self.skill, onerror=_raise):
            links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
            for d in links:
                out.say(f"  warning: skipped symlinked directory {os.path.join(dirpath, d)}")
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_NAMES and d not in links
                                 and not (d == "results" and os.path.basename(dirpath) == "evals"))
            for name in filenames:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, self.skill).replace(os.sep, "/")
                if name in SKIP_NAMES or name.endswith(".pyc") or not self.regular(path, out):
                    continue
                if not rel_ok(rel):
                    out.say(f"  warning: skipped file with an unportable name: {path}")
                    continue
                found.append((rel, path))
        return sorted(found)

    def agent_dir(self, host):
        return os.path.join(self.package, *HOSTS[host][0].split("/"))

    def agents(self, host, out):
        folder, suffix = self.agent_dir(host), HOSTS[host][1]
        names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        return [(n, os.path.join(folder, n)) for n in names if n.startswith("goal_") and n.endswith(suffix)
                and self.regular(os.path.join(folder, n), out)]


class Target:
    """One host's places: the skill in <skills>/goal-teams; agents and backups in <home>; the locks in
    <home> (agents, backups, the old Codex location) and in the real <skills> folder (the skill: two homes
    that install into the same folder, e.g. two $CODEX_HOME values, share that one)."""

    def __init__(self, host, home, skills_dir=None):
        self.host, self.home = host, os.path.abspath(os.path.expanduser(home))
        if skills_dir:
            self.skills = os.path.abspath(os.path.expanduser(skills_dir))
        else:  # Codex reads user skills from ~/.agents/skills, Claude Code from <claude home>/skills
            self.skills = os.path.join(user_home(), ".agents", "skills") if host == "codex" else \
                os.path.join(self.home, "skills")
        self.skill = os.path.join(self.skills, "goal-teams")
        self.agents = os.path.join(self.home, "agents")
        self.backups = os.path.join(self.home, "goal-teams-backups")
        self.lock = os.path.join(self.home, LOCK)
        target_lock = os.path.join(os.path.realpath(self.skills), LOCK)
        self.locks = [self.lock] + ([target_lock] if norm(target_lock) != norm(self.lock) else [])
        # The old Codex location (clones and installs of older versions). Codex still reads it, so a copy there is moved
        # away; None when it is the target itself (e.g. --skills-dir <codex home>/skills).
        legacy = os.path.join(self.home, "skills", "goal-teams") if host == "codex" else None
        self.legacy = None if legacy is None or same(legacy, self.skill) else legacy
        for other, what in ((self.legacy, "the old Codex location"), (self.agents, "the agents folder"),
                            (self.backups, "the backups folder")):
            if other and (inside(self.skill, other) or inside(other, self.skill)):
                raise Refused(f"the skill folder {self.skill} and {what} {other} overlap; "
                              "choose another --skills-dir or --home")


def guard(src, t):
    """Refuse when target and source overlap (older installers replaced the user's git clone that way)."""
    s, tgt = src.skill, t.skill
    reasons = [text for bad, text in (
        (inside(tgt, s) and inside(s, tgt), "the target is the source skill directory"),
        (inside(tgt, s) != inside(s, tgt), "the target and the source skill directory are nested"),
        (inside(src.root, tgt), f"the source tree {src.root} is inside the target"),
        (inside(tgt, src.package) or inside(t.agents, src.package), "the target is inside the source package"),
    ) if bad]
    move_hint = ("Move the clone out of the skills folder and install from there, e.g.\n"
                 f"    mv {q(src.root)} ~/src/goal-teams && python3 ~/src/goal-teams/tools/install.py")
    if reasons:
        if os.path.islink(tgt):
            hint = f"{tgt} is a symlink to the source: remove just the link (its target stays), then run again."
        else:
            hint = move_hint if inside(src.root, tgt) else "Use a --home or --skills-dir outside the source tree."
        raise Refused(f"will not install into {tgt}: {'; '.join(reasons)}.\n"
                      f"  That would overwrite the source with a copy of itself.\n  {hint}")
    old = t.legacy  # moved into the backup by the switch: it must not hold, or lie inside, the source
    if old and os.path.lexists(old) and (inside(src.root, old) or inside(old, src.root)
                                         or inside(os.path.dirname(old), src.root)):
        if inside(src.root, old):
            reason = f"the source tree is inside {old}, the old Codex skills location"
        else:
            reason = f"{old}, the old Codex skills location, is inside the source tree"
        if os.path.islink(old):
            hint = f"{old} is a symlink to {os.readlink(old)}: remove just the link (its target stays), then run again."
        else:
            hint = move_hint if inside(src.root, old) else "Use a --home outside the source tree."
        raise Refused(f"will not install from {src.root}: {reason}.\n  The installer moves that folder into a "
                      f"backup so that Codex does not load two copies, and that would move the source too.\n  {hint}")


def manifest_entries(t, m, root=None):
    """(kind, label, live path or None if unsafe, sha256, size) for every file and agent of the manifest
    of the install at root (default: the target)."""
    rows, root = [], root or t.skill
    for e in m.get("files") or []:
        e = e if isinstance(e, dict) else {}
        rel = e.get("path")
        rows.append(("file", str(rel), os.path.join(root, *rel.split("/")) if rel_ok(rel) else None,
                     e.get("sha256"), e.get("size")))
    for e in m.get("agents") or []:
        e = e if isinstance(e, dict) else {}
        rel = str(e.get("path"))
        ok = rel.startswith("agents/") and AGENT_NAME.match(rel[7:])
        rows.append(("agent", rel, os.path.join(t.agents, rel[7:]) if ok else None, e.get("sha256"), None))
    return rows


def inspect(p):
    """What is at a skill folder (the target or the old Codex location) now: kind none | managed (it holds
    the manifest this installer writes) | unmanaged (anything else: an older package, a clone, a copy)."""
    if not p or not os.path.lexists(p):
        return dict(NOTHING)
    if os.path.islink(p) or not os.path.isdir(p):
        return {"kind": "unmanaged", "what": f"a symlink to {os.readlink(p)}" if os.path.islink(p) else "a file"}
    m = read_json(os.path.join(p, MANIFEST))
    if isinstance(m, dict) and m.get("schema") == SCHEMA:
        source = m.get("source") if isinstance(m.get("source"), dict) else {}
        info = {"kind": "managed", "what": f"Goal Teams {m.get('version') or '?'} (managed install)",
                "manifest": m, "version": m.get("version"), "commit": source.get("commit")}
    else:
        info = {"kind": "unmanaged",
                "what": "an unmanaged directory (no install manifest: an older package or a manual copy)"}
    if os.path.lexists(os.path.join(p, ".git")):
        status = git(p, "status", "--porcelain")
        info["git"], info["dirty"] = True, None if status is None else bool(status)
        clone = "a git clone " + {True: "WITH UNCOMMITTED CHANGES", False: "(clean)",
                                  None: "(could not check for uncommitted changes)"}[info["dirty"]]
        info["what"] = clone if info["kind"] == "unmanaged" else f"{info['what']} inside {clone}"
    return info


def precious(cur):
    """An unmanaged directory or a git clone: the installer does not know its content, so its backup is never
    pruned. (A managed install with your own changes is protected too, see backup_drift.)"""
    return cur["kind"] == "unmanaged" or bool(cur.get("git"))


def compare(t, m, root, agents=True):
    """The --verify comparison of the managed install at root with its manifest m: {modified, missing, extra},
    files as paths relative to root, agents (the files in <home>/agents) as agents/<name>."""
    drift, listed = {kind: [] for kind in DRIFT_KINDS}, set()
    for kind, label, path, digest, size in manifest_entries(t, m, root):
        if kind == "agent" and not agents:
            continue
        if path is None:
            drift["modified"].append(f"{label} (unsafe path in manifest)")
            continue
        if kind == "file":
            listed.add(label)
        if not os.path.isfile(path):
            drift["missing"].append(label)
        elif os.path.islink(path) or sha256_file(path)[0] != digest or size not in (None, os.path.getsize(path)):
            drift["modified"].append(label)
    drift["extra"] = [r for r in walk_files(root) if r not in listed and r != MANIFEST and not is_cache(r)]
    return drift


def backup_drift(t, cur, leg, steps):
    """Your own changes among what the steps move into a backup, as paths inside it (skill/..., legacy-skill/...,
    agents/...). A managed skill folder is compared with its manifest like --verify: moved whole, its files may
    be modified, missing or extra; moved file by file (--uninstall keeps the extra ones in place), modified or
    missing. An agent is clean when a manifest being backed up lists it with the same hash; an agent no
    manifest lists (your own file, or one of an older version) is extra."""
    drift, moved = {kind: [] for kind in DRIFT_KINDS}, [s[2] for s in steps if s[0] == "backup"]
    manifests = {}  # key -> manifest of the managed install these steps take apart
    for key, info, root in zip(SKILL_KEYS, (cur, leg), (t.skill, t.legacy)):
        m = info.get("manifest")
        if not m or not any(p == key or p.startswith(key + "/") for p in moved):
            continue
        manifests[key] = m
        found = compare(t, m, root, agents=False)
        kinds = DRIFT_KINDS if key in moved else DRIFT_KINDS[:2]  # moved file by file: the extra ones stay
        for kind in kinds:
            drift[kind] += [f"{key}/{row}" for row in found[kind]]
    expected, primary = {}, next(iter(manifests), None)  # agents/<name> -> the hashes the manifests know for it
    for key, m in manifests.items():
        for kind, label, path, digest, _size in manifest_entries(t, m):
            if kind == "agent" and path:
                expected.setdefault(label, set()).add(digest)
            if kind == "agent" and key == primary:  # an agent the target's own manifest lists is gone
                if path is None:
                    drift["modified"].append(f"{label} (unsafe path in manifest)")
                elif not os.path.isfile(path):
                    drift["missing"].append(label)
    for op, live, where, _note in steps:
        if op != "backup" or not where.startswith("agents/"):
            continue
        if where not in expected:
            drift["extra"].append(where)
        elif os.path.islink(live) or not os.path.isfile(live) or sha256_file(live)[0] not in expected[where]:
            drift["modified"].append(where)
    return drift


def describe_drift(drift, limit=5):
    """'1 modified: skill/rules/core.md; 2 extra: skill/notes.txt, agents/goal_mine.toml'."""
    parts = []
    for kind in DRIFT_KINDS:
        rows = drift.get(kind) or []
        if rows:
            more = f" and {len(rows) - limit} more" if len(rows) > limit else ""
            parts.append(f"{len(rows)} {kind}: {', '.join(rows[:limit])}{more}")
    return "; ".join(parts)


def changed(meta):
    """True when the backup described by meta holds the user's own changes."""
    return bool(meta) and any((meta.get("drift") or {}).values())


def plan_steps(t, cur, leg, puts, names, why):
    """Ordered moves: ('backup', live path, path in backup, note) or ('put', staged key, live path, note).

    cur and leg describe the target and the old Codex location; puts maps staged keys to live folders."""
    old = {}  # agent files to move away: name -> reason
    for info in (cur, leg):
        for kind, _label, path, _sha, _size in manifest_entries(t, info.get("manifest") or {}):
            if kind == "agent" and path and os.path.lexists(path):
                name = os.path.basename(path)
                old[name] = "previous install" if name in names else "obsolete agent of the previous install"
    for name in names:
        if name not in old and os.path.lexists(os.path.join(t.agents, name)):
            old[name] = "existing file with the same name"
    if t.host == "codex" and os.path.isdir(t.agents):
        for name in sorted(os.listdir(t.agents)):
            if name.startswith("goal-") and name.endswith(".toml"):
                old.setdefault(name, "agent of an older version; this version uses goal_*.toml")
    steps = [("backup", t.skill, "skill", cur["what"])] if cur["kind"] != "none" else []
    if leg["kind"] != "none":
        steps.append(("backup", t.legacy, "legacy-skill",
                      f"{leg['what']}; old Codex skills location, Codex would load it as a second copy"))
    steps += [("put", key, live, why) for key, live in puts.items()]
    for name in names:
        live = os.path.join(t.agents, name)
        if name in old:
            steps.append(("backup", live, "agents/" + name, old.pop(name)))
        steps.append(("put", name, live, why))
    return steps + [("backup", os.path.join(t.agents, n), "agents/" + n, note) for n, note in sorted(old.items())]


def moved_whole(steps, live, key):
    return any(s[:3] == ("backup", live, key) for s in steps)


def show_plan(t, cur, leg, steps, meta, prune, put_desc, out):
    bdir = os.path.join(t.backups, meta["id"]) if meta else ""
    out.say("plan:" + ("" if steps else " nothing to do"))
    for key, live in zip(SKILL_KEYS, (t.skill, t.legacy)):
        files = [s for s in steps if s[0] == "backup" and s[2].startswith(key + "/")]
        if files:
            out.say(f"  move    {len(files)} files of {live}\n       -> {os.path.join(bdir, key)}")
    for op, a, b, note in steps:
        if op == "backup" and not b.startswith(tuple(key + "/" for key in SKILL_KEYS)):
            out.say(f"  move    {a}\n       -> {os.path.join(bdir, *b.split('/'))}  ({note})")
        elif op == "put":
            out.say(f"  install {b}  ({put_desc.get(a, note)})")
    for b in prune:
        out.say(f"  prune   old backup {b['path']}")
    for key, live, info in zip(SKILL_KEYS, (t.skill, t.legacy), (cur, leg)):
        if not (precious(info) and moved_whole(steps, live, key)):
            continue  # say clearly that an unmanaged directory (an older package, a git clone) is kept
        lines = [f"{live} is {info['what']}.", f"It is MOVED (not deleted) to {os.path.join(bdir, key)}",
                 "and that backup is never pruned automatically."]
        if os.path.isfile(os.path.join(live, ".git")):
            lines.append("It is a git worktree: run `git worktree repair` in its new place if you keep using it.")
        if info.get("dirty"):
            bar = "!" * 76
            lines.append("Your uncommitted changes and git history stay intact there.")
            out.say("\n".join([bar, "!! WARNING: " + lines[0]] + ["!! " + s for s in lines[1:]] + [bar]))
        else:
            out.say("note: " + "\n      ".join(lines))
    if changed(meta):
        out.say(f"note: the backup will contain your own changes ({describe_drift(meta['drift'])});\n"
                "      it is kept until you delete it (never pruned automatically).")


def note_changes(meta, out):
    """After the switch: the new backup holds the user's own changes, so it is never pruned."""
    if changed(meta):
        out.say(f"backup contains your own changes: {describe_drift(meta['drift'])}; it is kept until you delete it")


# ------------------------------------------------------------------ backups, lock, switch
def list_backups(t):
    """This host's backups, newest first."""
    rows = []
    for name in os.listdir(t.backups) if os.path.isdir(t.backups) else []:
        m = BACKUP_ID.match(name)
        if not m or m.group(2) != t.host:
            continue
        meta = read_json(os.path.join(t.backups, name, "backup.json"))
        meta = meta if isinstance(meta, dict) and meta.get("schema") == BACKUP_SCHEMA else {}
        drift = meta.get("drift") if isinstance(meta.get("drift"), dict) else {}
        rows.append({"key": (m.group(1), int(m.group(3) or 1)), "id": name, "path": os.path.join(t.backups, name),
                     "status": meta.get("status", "unreadable"), "reason": meta.get("reason"),
                     "created_at": meta.get("created_at"), "protected": bool(meta.get("protected", True)),
                     "previous": describe_previous(meta.get("previous")),
                     "drift": {kind: [str(r) for r in drift.get(kind) or []] for kind in DRIFT_KINDS},
                     "items": [i for i in meta.get("items") or [] if isinstance(i, dict)]})
    rows.sort(key=lambda row: row["key"], reverse=True)
    return [{k: v for k, v in row.items() if k != "key"} for row in rows]


def new_backup_id(t):
    stamp = now("%Y%m%dT%H%M%SZ")
    names = os.listdir(t.backups) if os.path.isdir(t.backups) else []
    n = max([int(m.group(3) or 1) for m in map(BACKUP_ID.match, names) if m and m.group(1) == stamp], default=0)
    return f"{stamp}-{t.host}" + (f"-{n + 1}" if n else "")


def describe_previous(prev):
    """One line for what a backup holds, e.g. 'nothing; old location: a git clone (clean)'."""
    prev = prev if isinstance(prev, dict) else {}
    legacy = prev.get("legacy") if isinstance(prev.get("legacy"), dict) else None
    what = str(prev.get("what") or "?")
    return what + (f"; old location: {legacy.get('what') or '?'}" if legacy else "")


def backup_meta(t, reason, cur, leg, steps):
    items = []
    for op, a, b, note in steps:
        key = b.split("/")[0]
        if op == "backup" and key in SKILL_KEYS:
            if not any(i["what"] == key for i in items):
                items.append({"what": key, "name": "goal-teams", "from": t.skill if key == "skill" else t.legacy,
                              "to": key, "note": note})
        elif op == "backup":
            items.append({"what": "agent", "name": os.path.basename(a), "from": a, "to": b, "note": note})
    if not items:
        return None
    fields = ("kind", "what", "version", "commit", "git", "dirty")
    previous = {k: cur[k] for k in fields if k in cur}
    protected = precious(cur)
    if any(i["what"] == "legacy-skill" for i in items):
        previous["legacy"] = {"path": t.legacy, **{k: leg[k] for k in fields if k in leg}}
        protected = protected or precious(leg)
    drift = backup_drift(t, cur, leg, steps)  # your own changes make the backup protected too
    return {"schema": BACKUP_SCHEMA, "id": new_backup_id(t), "host": t.host, "reason": reason,
            "created_at": now(), "status": "in-progress", "protected": protected or any(drift.values()),
            "drift": drift, "previous": previous, "items": items}


def prune_candidates(t, new=None):
    """Complete clean backups beyond the newest KEEP_BACKUPS, counting the new one (meta) when it is clean.
    Protected backups (unmanaged directories, git clones, your own changes), incomplete and unknown ones
    never take part."""
    new_id = new["id"] if new else None
    regular = [b for b in list_backups(t) if b["status"] == "complete" and not b["protected"] and b["id"] != new_id]
    return regular[KEEP_BACKUPS - (1 if new and not new["protected"] else 0):]


def make_dirs(path):
    """os.makedirs; returns the directories it had to create, deepest first (to take them back if unused)."""
    missing, p = [], path
    while p and not os.path.isdir(p) and os.path.dirname(p) != p:
        missing.append(p)
        p = os.path.dirname(p)
    os.makedirs(path, exist_ok=True)
    return missing


@contextlib.contextmanager
def locked(t, path, out):
    """Hold the lock file at path (created with O_EXCL; it records pid and start time). A lock whose process
    has ended is stale, as is one without a readable pid that is older than 10 minutes; a stale lock is
    replaced once. Never waits: a held lock refuses (exit 2). A folder created just for the lock is removed
    again when it is still empty at the end (a refusal changes nothing)."""
    made, fd, replaced = make_dirs(os.path.dirname(path)), None, False
    for _attempt in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            break
        except FileNotFoundError:  # the folder went away meanwhile (another installer gave it up)
            made += make_dirs(os.path.dirname(path))
        except FileExistsError:
            with contextlib.suppress(OSError):  # OSError: the lock vanished meanwhile, just retry
                age = time.time() - os.path.getmtime(path)
                held = read_json(path)
                pid = held.get("pid") if isinstance(held, dict) else None
                state = alive(pid)
                stale = state is False or (state is None and age > LOCK_STALE_SECONDS)
                if replaced or not stale:
                    raise Refused(f"another install is running (lock {path}, {f'pid {pid}, ' if pid else ''}"
                                  f"{int(age)}s old); if none is, delete the lock file and retry") from None
                why = f"process {pid} has ended" if state is False else f"{int(age // 60)} min old"
                out.say(f"removing stale lock {path} ({why})")
                os.remove(path)
                replaced = True
    try:
        if fd is None:
            raise Refused(f"could not take the lock {path}; retry")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "started_at": now(), "host": t.host, "home": t.home,
                                "target": t.skill}))
        yield
    finally:
        with contextlib.suppress(OSError):
            if fd is not None:
                os.remove(path)
        for folder in made:  # deepest first; stops at the first one that is in use
            try:
                os.rmdir(folder)
            except OSError:
                break


@contextlib.contextmanager
def locks(t, out):
    """Hold the home lock, then the lock next to the install target (see Target)."""
    with contextlib.ExitStack() as stack:
        for path in t.locks:
            stack.enter_context(locked(t, path, out))
        fault("locked")
        yield


def clean_staging(t, out):
    """Remove staging copies left by an interrupted run, but only those whose installer (the pid in the
    name) has ended; one without a pid in its name when it is older than 10 minutes. We hold the locks, so
    a copy of a live pid belongs to an installer that does not share them (an older version of this script
    run from another home, or a reused pid): it is left alone and reported."""
    for folder in (t.skills, t.agents, t.legacy and os.path.dirname(t.legacy)):
        for name in sorted(os.listdir(folder)) if folder and os.path.isdir(folder) else []:
            if not (name.startswith(".") and STAGING in name):
                continue
            path, m = os.path.join(folder, name), STAGING_PID.search(name)
            pid = int(m.group(1)) if m else None
            state = alive(pid) if m else None
            if state is True:
                out.say(f"note: {path} belongs to another install still running (pid {pid}); left alone")
                continue
            if state is None:
                with contextlib.suppress(OSError):
                    if time.time() - os.lstat(path).st_mtime <= LOCK_STALE_SECONDS:
                        out.say(f"note: {path} may belong to another install; left alone")
                        continue
            remove(path)
            out.say(f"removed leftover staging copy {path}"
                    + (f" (process {pid} has ended)" if state is False else " (older than 10 minutes)"))


JOURNAL = "journal.json"


def journal_path(t):
    return os.path.join(t.backups, JOURNAL)


def write_journal(t, entry):
    """The switch's intent and progress, replaced atomically after every move (so a crash at any point
    leaves a journal that says exactly which moves happened)."""
    os.makedirs(t.backups, exist_ok=True)
    tmp = journal_path(t) + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)
    os.replace(tmp, journal_path(t))


def recover(t, out):
    """Finish what an interrupted switch left behind, from its journal only: the recorded moves are undone
    newest first, so the live folders are what they were before that install. Anything the journal does not
    explain is left alone and reported; an unknown state stops the installer (exit 2) rather than guessing."""
    path = journal_path(t)
    entry = read_json(path) if os.path.isfile(path) else None
    if entry is None:
        return False
    pid = entry.get("pid")
    if alive(pid) is True:
        raise Refused(f"another install (pid {pid}) is in the middle of its switch ({path}); wait for it")
    problems = []
    moves = list(entry.get("done") or [])
    doing = entry.get("doing")
    if doing and os.path.lexists(doing[1]) and not os.path.lexists(doing[0]):
        moves.append(doing)  # the move happened, the journal update did not
    undone = 0
    for src, dst in reversed(moves):
        if not os.path.lexists(dst) and os.path.lexists(src):
            continue  # never happened (or already undone)
        if os.path.lexists(dst) and not os.path.lexists(src):
            try:
                move(dst, src)
                undone += 1
            except OSError as err:
                problems.append(f"{dst} -> {src}: {err}")
        elif os.path.lexists(dst) and os.path.lexists(src):
            problems.append(f"both {src} and {dst} exist; the journal cannot tell which is current")
    if problems:
        raise Refused(f"an earlier install was interrupted during its switch and could not be undone from {path}: "
                      f"{'; '.join(problems)}. Resolve by hand, then delete the journal.")
    bdir = entry.get("backup")
    if bdir and os.path.isdir(bdir) and set(os.listdir(bdir)) <= {"backup.json"}:
        remove(bdir)  # everything the backup held went back; it never became a backup
    os.remove(path)
    with contextlib.suppress(OSError):
        os.rmdir(t.backups)  # only when nothing else is in it
    out.say(f"recovered from an interrupted install (journal {entry.get('started_at')}, pid {pid}): "
            f"{undone} move(s) undone; the previous files are back in place")
    return True


def switch(t, steps, staged, meta):
    """Apply the moves. On any error move everything back, newest first. Returns the backup dir.
    Every move is written to the journal first; a crash leaves a journal that recover() can undo."""
    bdir = None
    if meta:
        meta["id"] = new_backup_id(t)  # final id, taken under the lock
        bdir = os.path.join(t.backups, meta["id"])
        os.makedirs(bdir)
        write_json(os.path.join(bdir, "backup.json"), meta)
    done = []
    entry = {"pid": os.getpid(), "started_at": now(), "host": t.host, "backup": bdir,
             "steps": [[op, a, b] for op, a, b, _n in steps], "done": []}
    write_journal(t, entry)
    try:
        for op, a, b, _note in steps:
            src, dst = (a, os.path.join(bdir, *b.split("/"))) if op == "backup" else (staged[a], b)
            entry["doing"] = [src, dst]  # journalled before the move: a crash in between is recoverable
            write_journal(t, entry)
            move(src, dst)
            fault("moved")  # test hook: a crash after the rename, before the journal records it
            done.append((src, dst))
            entry["done"].append([src, dst])
            entry["doing"] = None
            write_journal(t, entry)
            if op == "put" and a == "skill":
                fault("after_skill")
        fault("after_switch")
        if meta:
            meta["status"] = "complete"
            write_json(os.path.join(bdir, "backup.json"), meta)
        os.remove(journal_path(t))
        with contextlib.suppress(OSError):
            os.rmdir(t.backups)  # only when nothing else is in it (a fresh install has no backup)
    except BaseException as exc:
        problems = []
        for src, dst in reversed(done):
            try:
                move(dst, src)
            except OSError as err:
                problems.append(f"{dst} -> {src}: {err}")
        if not problems:
            with contextlib.suppress(OSError):
                os.remove(journal_path(t))
            with contextlib.suppress(OSError):
                os.rmdir(t.backups)  # a fresh install made it only for the journal
        what = "interrupted" if isinstance(exc, KeyboardInterrupt) else f"{type(exc).__name__}: {exc}"
        if isinstance(exc, PermissionError):
            what += " (is Codex or Claude Code still using these files? close it and retry)"
        if problems:
            raise Failed(f"{what}; could NOT move everything back ({'; '.join(problems)}). "
                         f"The previous files are in {bdir} (see backup.json).") from None
        if bdir:
            with contextlib.suppress(OSError):
                remove(bdir)
                os.rmdir(t.backups)  # only if it is now empty
        raise Failed(f"{what}; the previous state was restored, nothing changed") from None
    return bdir


def replace(t, args, out, reason, puts, names, why, stage, check=None, put_desc=None):
    """Swap the live skill folders and agents for staged copies; the old ones go into a new backup.

    puts maps the staged skill folders ('skill', 'legacy-skill') to the live folders they become.
    Plans under the locks (with --dry-run it only prints the plan); stage(paths) fills the staging
    paths before anything live is touched. Returns (backup dir or None, pruned backups, backup meta).
    """
    def plan():
        cur, leg = inspect(t.skill), inspect(t.legacy)
        if check:
            check(cur, leg)
        out.say(f"target: {t.skill} (now: {cur['what']})")
        if leg["kind"] != "none":
            out.say(f"old location: {t.legacy} (now: {leg['what']})")
        steps = plan_steps(t, cur, leg, puts, names, why)
        meta = backup_meta(t, reason, cur, leg, steps)
        prune = prune_candidates(t, meta) if reason == "install" else []
        show_plan(t, cur, leg, steps, meta, prune, put_desc or {}, out)
        return cur, leg, steps, meta

    if args.dry_run:
        plan()
        out.say("dry run: nothing changed.")
        return None, [], None
    with locks(t, out):  # the locks create <home> and the skills folder when they are missing
        recover(t, out)  # before clean_staging: an interrupted switch may still need its staging copies
        clean_staging(t, out)
        cur, leg, steps, meta = plan()
        keep = [live for key, live, info in zip(SKILL_KEYS, (t.skill, t.legacy), (cur, leg))
                if precious(info) and moved_whole(steps, live, key)]
        if meta and keep and not (args.yes or args.json) and sys.stdin and sys.stdin.isatty():
            answer = ""
            with contextlib.suppress(EOFError):
                answer = input(f"Move {' and '.join(keep)} into the backup and continue? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                raise Refused("cancelled; nothing changed")
        staged = {n: os.path.join(t.agents, f".{n}{STAGING}{os.getpid()}") for n in names}
        staged.update((key, os.path.join(os.path.dirname(live), f".{key}{STAGING}{os.getpid()}"))
                      for key, live in puts.items())  # next to the live folder: the switch is a rename
        for folder in sorted({os.path.dirname(path) for path in staged.values()}):
            os.makedirs(folder, exist_ok=True)
        try:
            stage(staged)
            fault("staged")
            bdir = switch(t, steps, staged, meta)
        finally:
            for path in staged.values():
                if os.path.lexists(path):
                    remove(path)
        pruned = prune_candidates(t, meta) if reason == "install" else []
        for b in pruned:
            try:
                remove(b["path"])
            except OSError as exc:
                out.say(f"warning: could not prune {b['path']}: {exc}")
    return bdir, pruned, meta


def note_old_state(t, out):
    old_state = os.path.join(t.home, "state", "goal-teams")
    if os.path.isdir(old_state):
        out.say(f"note: {old_state} was written by older versions and is not used any more; "
                "remove it by hand if you no longer need it.")


# ------------------------------------------------------------------ commands
def cmd_install(t, src, args, out):
    guard(src, t)
    files, agents = src.files(out), src.agents(t.host, out)
    if not agents:
        raise Refused(f"no {t.host} agents (goal_*{HOSTS[t.host][1]}) in {src.agent_dir(t.host)}; "
                      "run python3 tools/gen.py first")
    version, (commit, dirty) = src.version(), src.git_info()
    out.say(f"source: {src.root} (version {version or 'unknown'}, " + (
        f"commit {commit[:12]}{' + uncommitted changes' if dirty else ''})" if commit else "not a git checkout)"))

    def check(cur, leg):
        for path, info in ((t.skill, cur), (t.legacy, leg)):
            host = (info.get("manifest") or {}).get("host")
            if host not in (None, t.host):
                raise Refused(f"{path} holds the {host} install; use a separate --home per host")

    def stage(staged):
        def copy(src_path, dst):  # copy with mode (following an allowed in-package link), hash the copy
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src_path, dst)
            return sha256_file(dst)
        agent_rows = [{"path": "agents/" + n, "sha256": copy(p, staged[n])[0]} for n, p in agents]
        rows = []
        for rel, path in files:
            digest, size = copy(path, os.path.join(staged["skill"], *rel.split("/")))
            rows.append({"path": rel, "sha256": digest, "size": size})
        write_json(os.path.join(staged["skill"], MANIFEST), {
            "schema": SCHEMA, "version": version, "host": t.host,
            "source": {"path": src.root, "commit": commit, "dirty": dirty},
            "installed_at": now(), "files": rows, "agents": agent_rows})

    bdir, pruned, meta = replace(t, args, out, "install", {"skill": t.skill}, [n for n, _ in agents], "new", stage,
                                 check, {"skill": f"{len(files)} files from {src.skill}"})
    if args.dry_run:
        return 0
    out.say(f"installed Goal Teams{' ' + version if version else ''} for {t.host}: "
            f"{len(files)} files -> {t.skill}, {len(agents)} agents -> {t.agents}")
    out.say(f"backup of the previous state: {bdir} (undo with --rollback)" if bdir
            else "nothing replaced; no backup needed")
    note_changes(meta, out)
    if bdir and os.path.lexists(os.path.join(bdir, "legacy-skill")):
        out.say(f"the old copy {t.legacy} is now {os.path.join(bdir, 'legacy-skill')}, "
                "so Codex does not load two copies")
    if pruned:
        out.say(f"pruned {len(pruned)} old backup(s); the newest {KEEP_BACKUPS} clean backups are kept "
                "(backups holding your own changes or an unmanaged directory are never pruned)")
    out.data(backup=bdir, version=version, pruned=[b["id"] for b in pruned],
             protected=meta["protected"] if meta else None, drift=meta["drift"] if meta else None)
    note_old_state(t, out)
    if t.host == "claude":
        market = read_json(os.path.join(src.root, ".claude-plugin", "marketplace.json"))
        name = market.get("name") if isinstance(market, dict) else None
        out.say("tip: Claude Code can also install Goal Teams as a plugin (/plugin marketplace add <repo or "
                f"{src.root}>, then /plugin install goal-teams@{name or '<marketplace>'}); use one method, not both.")
    flags = (f" --home {q(t.home)}" if args.home else "") + (f" --skills-dir {q(t.skills)}" if args.skills_dir else "")
    out.say(f"next: start a new {'Codex' if t.host == 'codex' else 'Claude Code'} session"
            + (f" (Codex reads user skills from {t.skills})" if t.host == "codex" and not args.skills_dir else "")
            + f". Check the install with:\n  python3 {q(os.path.abspath(__file__))} --verify --host {t.host}{flags}")
    return 0


def cmd_verify(t, _src, _args, out):
    if os.path.isfile(journal_path(t)):
        raise Refused(f"an install was interrupted during its switch ({journal_path(t)}); run the installer again "
                      "(it undoes the recorded moves first) or --rollback, then verify")
    cur, leg = inspect(t.skill), inspect(t.legacy)
    if cur["kind"] != "managed":
        old = (f"; the old Codex location {t.legacy} holds {leg['what']}: run the installer to move it"
               if leg["kind"] != "none" else "")
        raise Refused(f"no managed install at {t.skill} (found {cur['what']}); nothing to verify{old}")
    m = cur["manifest"]
    drift = compare(t, m, t.skill)
    drift["duplicate"] = [t.legacy] if leg["kind"] != "none" else []
    entries = manifest_entries(t, m)
    source = m.get("source") if isinstance(m.get("source"), dict) else {}
    out.say(f"{cur['what']} at {t.skill}, installed {m.get('installed_at')} from {source.get('path')}")
    out.say(f"  {sum(e[0] == 'file' and e[2] is not None for e in entries)} files and "
            f"{sum(e[0] == 'agent' for e in entries)} agents checked: "
            + ", ".join(f"{len(drift[kind])} {kind}" for kind in DRIFT_KINDS))
    for kind in DRIFT_KINDS:
        for row in drift[kind]:
            out.say(f"  {kind}: {row}")
    for path in drift["duplicate"]:
        out.say(f"  duplicate: {path} holds {leg['what']}; Codex still reads that old location and loads it as "
                "a second copy. Run the installer again to move it into a backup.")
    out.data(**drift)
    bad = any(drift.values())
    out.say("verify: DRIFT" if bad else "verify: OK")
    return 1 if bad else 0


def uninstall_steps(t, key, root, info, steps):
    """Append the moves that uninstall the managed install at root; return the files Goal Teams did not install."""
    entries = manifest_entries(t, info["manifest"], root)
    listed = {label for kind, label, path, _d, _s in entries if kind == "file" and path}
    unknown = []
    for rel in walk_files(root):
        if rel in listed or is_cache(rel):
            steps.append(("backup", os.path.join(root, *rel.split("/")), f"{key}/{rel}", "installed file"))
        elif rel != MANIFEST:
            unknown.append(rel)
    steps.append(("backup", os.path.join(root, MANIFEST), f"{key}/{MANIFEST}", "install manifest"))
    moved = {step[1] for step in steps}  # an agent listed by both installs moves once
    steps += [("backup", path, label, "installed agent") for kind, label, path, _d, _s in entries
              if kind == "agent" and path and os.path.lexists(path) and path not in moved]
    return unknown


def ours(t, info):
    """A managed install of this host (the old Codex location may hold one made for the other host)."""
    return info["kind"] == "managed" and (info.get("manifest") or {}).get("host") in (None, t.host)


def note_legacy(t, leg, out):
    if leg["kind"] != "none" and not ours(t, leg):
        why = ("it is not a managed install" if leg["kind"] != "managed"
               else f"it is the {leg['manifest'].get('host')} install")
        out.say(f"note: {t.legacy} (the old Codex skills location, which Codex still reads) holds {leg['what']}; "
                f"{why}, so it is left alone. Remove it yourself if you no longer need it.")


def cmd_uninstall(t, _src, args, out):
    cur, leg = inspect(t.skill), inspect(t.legacy)
    if cur["kind"] == "none" and not ours(t, leg):
        out.say(f"nothing to uninstall: {t.skill} does not exist")
        note_legacy(t, leg, out)
        return 0
    with contextlib.ExitStack() as stack:
        if not args.dry_run:
            stack.enter_context(locks(t, out))
        cur, leg = inspect(t.skill), inspect(t.legacy)
        if cur["kind"] not in ("none", "managed"):
            raise Refused(f"{t.skill} is not a managed install ({cur['what']}); leaving it alone. "
                          "Remove it yourself if you no longer need it.")
        steps, kept = [], {}  # kept: skill folder -> files Goal Teams did not install
        for key, root, info in zip(SKILL_KEYS, (t.skill, t.legacy), (cur, leg)):
            if info["kind"] == "managed" and (key == "skill" or ours(t, info)):
                kept[root] = uninstall_steps(t, key, root, info, steps)
        if not steps:
            out.say(f"nothing to uninstall: {t.skill} does not exist")
            return 0
        meta = backup_meta(t, "uninstall", cur, leg, steps)
        show_plan(t, cur, leg, steps, meta, [], {}, out)
        for root, rows in kept.items():
            if rows:
                out.say(f"  keep    {len(rows)} file(s) in {root} not installed by Goal Teams: {', '.join(rows)}")
        note_legacy(t, leg, out)
        if args.dry_run:
            out.say("dry run: nothing changed.")
            return 0
        bdir = switch(t, steps, {}, meta)
        for root in kept:
            for dirpath, _dirs, _files in os.walk(root, topdown=False):
                with contextlib.suppress(OSError):
                    os.rmdir(dirpath)  # succeeds only for empty directories
    out.say(f"uninstalled Goal Teams for {t.host}"
            + (f" (also the old install at {t.legacy})" if t.legacy in kept else "")
            + f"; the removed files are in {bdir} (undo with --rollback)")
    note_changes(meta, out)
    for root, rows in kept.items():
        if rows:
            out.say(f"kept {len(rows)} file(s) that Goal Teams did not install, in {root}: {', '.join(rows)}")
    out.data(backup=bdir, kept=kept.get(t.skill, []), protected=meta["protected"], drift=meta["drift"],
             **({"kept_legacy": kept.get(t.legacy, [])} if t.legacy else {}))
    note_old_state(t, out)
    return 0


def cmd_list(t, _src, _args, out):
    rows = list_backups(t)
    out.say(f"backups in {t.backups} (newest first):" if rows else f"no backups in {t.backups}")
    for b in rows:
        flag = ""
        if b["protected"] and b["status"] == "complete":
            flag = "  [never pruned: holds your own changes]" if changed(b) else "  [never pruned]"
        out.say(f"  {b['id']}  {b['reason'] or '?':<9} {b['status']:<11} previous: {b['previous']}{flag}")
    out.data(backups=[{k: v for k, v in b.items() if k != "items"} for b in rows])
    return 0


def cmd_rollback(t, _src, args, out):
    if os.path.isfile(journal_path(t)):
        if args.dry_run:
            out.say(f"would recover the interrupted install from {journal_path(t)} before rollback")
            if args.rollback:
                out.say(f"backup {args.rollback!r} will be checked after recovery; its restore plan is deferred")
            out.say("dry run: nothing changed.")
            return 0
        with locks(t, out):
            recover(t, out)
            clean_staging(t, out)
        out.say("the interrupted install is undone; the files are as they were before it")
        if not args.rollback:
            return 0
    rows = list_backups(t)
    row = next((b for b in rows if (b["id"] == args.rollback if args.rollback else b["status"] == "complete")), None)
    if row is None:
        raise Refused(f"no backup {args.rollback!r} for {t.host} in {t.backups} (see --list-backups)"
                      if args.rollback else f"no complete backup for {t.host} in {t.backups}")
    if row["status"] != "complete":
        raise Refused(f"backup {row['id']} is {row['status']}; restore it by hand from {row['path']} (see backup.json)")
    puts, folders = {}, []  # each skill folder goes back where it came from
    for item in row["items"]:
        key, frm = item.get("what"), item.get("from")
        path = os.path.join(row["path"], str(key))
        if key not in SKILL_KEYS or key in puts or not os.path.lexists(path):
            continue
        # 'skill' in a backup by an older version of this script came from the old Codex location
        old = key == "legacy-skill" or bool(t.legacy and isinstance(frm, str) and os.path.isabs(frm)
                                              and same(frm, t.legacy))
        live = (t.legacy or t.skill) if old else t.skill
        if live in puts.values():
            raise Refused(f"backup {row['id']} holds two skill folders for {live}; "
                          f"restore it by hand from {row['path']}")
        puts[key] = live
        folders.append((key, path))
    agents = [(i["name"], os.path.join(row["path"], "agents", i["name"])) for i in row["items"]
              if i.get("what") == "agent" and AGENT_NAME.match(str(i.get("name")))
              and os.path.lexists(os.path.join(row["path"], "agents", i["name"]))]
    out.say(f"restoring backup {row['id']} (it holds: {row['previous']})")

    def stage(staged):  # copy as-is (symlinks stay symlinks); the backup itself stays intact
        for key, path in agents + folders:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.copytree(path, staged[key], symlinks=True)
            else:
                shutil.copy2(path, staged[key], follow_symlinks=False)

    bdir, _, meta = replace(t, args, out, "rollback", puts, [n for n, _ in agents], f"from backup {row['id']}", stage)
    if not args.dry_run:
        out.say(f"rolled back to {row['id']}" + (f"; the state before the rollback is saved in {bdir}" if bdir else ""))
        note_changes(meta, out)
        out.data(backup=bdir, restored=row["id"], protected=meta["protected"] if meta else None,
                 drift=meta["drift"] if meta else None)
    return 0


COMMANDS = {"install": cmd_install, "verify": cmd_verify, "uninstall": cmd_uninstall,
            "list-backups": cmd_list, "rollback": cmd_rollback}


def pick_hosts(choice):
    if choice:
        return (["codex", "claude"] if choice == "both" else [choice]), ""
    if os.environ.get("CODEX_HOME") or os.path.isdir(os.path.expanduser("~/.codex")):
        return ["codex"], "auto: $CODEX_HOME or ~/.codex found"
    if os.environ.get("CLAUDE_CONFIG_DIR") or os.path.isdir(os.path.expanduser("~/.claude")):
        return ["claude"], "auto: no ~/.codex, but $CLAUDE_CONFIG_DIR or ~/.claude found"
    return ["codex"], "auto: neither ~/.codex nor ~/.claude found"


def parser():
    p = argparse.ArgumentParser(prog="install.py", usage=argparse.SUPPRESS, description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", choices=["codex", "claude", "both"], help="where to install (default: auto-detect)")
    p.add_argument("--home", metavar="DIR", help="home dir of the host: agents, backups and, for codex, the old "
                   "skills location (default: $CODEX_HOME or ~/.codex, $CLAUDE_CONFIG_DIR or ~/.claude)")
    p.add_argument("--skills-dir", metavar="DIR", help="skills folder of the host; the skill goes to DIR/goal-teams "
                   "(default: ~/.agents/skills for codex, <home>/skills for claude)")
    p.add_argument("--source", metavar="DIR",
                   help="folder holding plugins/goal-teams (default: the folder above tools/)")
    p.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    p.add_argument("--yes", "-y", action="store_true",
                   help="do not ask before moving an unmanaged directory into a backup")
    p.add_argument("--json", action="store_true", help="print one JSON document instead of text")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true", help="check the installed files against the manifest")
    group.add_argument("--uninstall", action="store_true", help="remove the installed files (moved into a backup)")
    group.add_argument("--list-backups", action="store_true", help="list the backups, newest first")
    group.add_argument("--rollback", nargs="?", const="", metavar="BACKUP_ID",
                       help="restore a backup (default: the newest) after backing up the current state")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="backslashreplace")  # odd console encodings must not crash us
    args = parser().parse_args(argv)
    command = ("verify" if args.verify else "uninstall" if args.uninstall else "list-backups" if args.list_backups
               else "rollback" if args.rollback is not None else "install")
    out, code, src = Out(args.json), 0, None
    hosts, why = pick_hosts(args.host)
    try:
        if len(hosts) > 1 and (args.home or args.skills_dir or args.rollback):
            raise Refused("--home, --skills-dir and a backup id apply to one host: add --host codex or --host claude")
        if command == "install":
            src = Source(args.source or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except Refused as exc:
        out.say(f"REFUSED: {exc}", err=True)
        code, hosts = 2, []
    for host in hosts:
        home = os.path.abspath(os.path.expanduser(args.home or os.environ.get(HOSTS[host][2]) or HOSTS[host][3]))
        out.begin(host, home)
        out.say(f"== {host}: {home}" + (f"  ({why}; choose with --host codex|claude|both)" if why else ""))
        try:
            t = Target(host, home, args.skills_dir)
            out.data(skill=t.skill, agents=t.agents, legacy=t.legacy)
            rc = COMMANDS[command](t, src, args, out) or 0
        except Refused as exc:
            out.say(f"REFUSED: {exc}", err=True)
            rc = 2
        except (Exception, KeyboardInterrupt) as exc:  # Failed, or an error before anything live changed
            out.say(f"FAILED: {exc if isinstance(exc, Failed) else f'{type(exc).__name__}: {exc}'}", err=True)
            rc = 1
        out.data(exit=rc)
        code = max(code, rc)
    if args.json:
        print(json.dumps({"command": command, "exit": code, "messages": out.top["messages"], "hosts": out.hosts},
                         indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # SIGTERM -> KeyboardInterrupt -> undo
    sys.exit(main())
