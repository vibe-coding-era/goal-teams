"""Small shared helpers: time, hashing, JSON, paths, globs, locking, errors."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, List, Optional

ZERO_HASH = "0" * 64


class _Exit:
    """The one place exit codes are defined (every command and every document quotes these).

    ok: done · unverified: recorded, but a check, expectation or completion gate is not closed ·
    usage: bad arguments or state · blocked: capability or authorization missing ·
    conflict: the ledger or the goal changed under the command (re-read and retry).
    """
    ok = 0
    unverified = 1
    usage = 2
    blocked = 3
    conflict = 4


EXIT = _Exit()


class GTError(Exception):
    """A user-facing error; ``code`` is one of ``EXIT`` (default ``usage``)."""

    def __init__(self, message: str, code: int = EXIT.usage, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


def now_iso() -> str:
    """UTC timestamp; ``GT_NOW`` overrides it so tests and examples are reproducible."""
    override = os.environ.get("GT_NOW")
    if override:
        return override
    stamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    return stamp.isoformat().replace("+00:00", "Z")


def today() -> str:
    return now_iso()[:10]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def posix_rel(path: Path, root: Path) -> str:
    return PurePosixPath(Path(os.path.relpath(path, root)).as_posix()).as_posix()


def split_csv(values: Optional[Iterable[str]]) -> List[str]:
    """Accept ``--deps A,B --deps C`` style values and return a clean ordered list."""
    out: List[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


_GLOB_CACHE: dict = {}


def normalize_scope(pattern: str) -> str:
    """``./src/`` -> ``src/**``; ``.`` or ``./`` -> ``**`` (the whole project)."""
    pat = str(pattern).strip().replace("\\", "/")
    while pat.startswith("./"):
        pat = pat[2:]
    if pat in ("", "."):
        return "**"
    if pat.endswith("/"):
        pat = pat + "**"
    return pat


def glob_to_regex(pattern: str, ignore_case: bool = False) -> "re.Pattern[str]":
    """Translate a POSIX-style glob (``**``, ``*``, ``?``) into an anchored regex.

    A pattern without glob characters also matches everything below it, so
    ``src/auth`` covers ``src/auth/login.py``.
    """
    key = (pattern, ignore_case)
    cached = _GLOB_CACHE.get(key)
    if cached is not None:
        return cached
    pat = normalize_scope(pattern)
    out = []
    i = 0
    while i < len(pat):
        char = pat[i]
        if char == "*":
            if i + 1 < len(pat) and pat[i + 1] == "*":
                i += 2
                if i < len(pat) and pat[i] == "/":
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = pat.find("]", i + 1)
            if end == -1:
                out.append(re.escape(char))
            else:
                inner = pat[i + 1 : end].replace("\\", "\\\\")
                if inner.startswith("!"):
                    inner = "^" + inner[1:]
                out.append("[" + inner + "]")
                i = end
        else:
            out.append(re.escape(char))
        i += 1
    body = "".join(out)
    if not any(ch in pat for ch in "*?["):
        body = body + "(?:/.*)?"
    compiled = re.compile("^" + body + "$", re.IGNORECASE if ignore_case else 0)
    _GLOB_CACHE[key] = compiled
    return compiled


def matches_any(path: str, patterns: Iterable[str], ignore_case: bool = False) -> bool:
    return any(glob_to_regex(p, ignore_case).match(path) for p in patterns if p is not None)


_CRED_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]*@")


def sanitize_url(url: str) -> str:
    """Strip any userinfo (tokens, passwords) from a remote URL."""
    return _CRED_RE.sub(r"\1", url.strip())


def remote_protocol(url: str) -> str:
    url = url.strip()
    if url.startswith(("https://", "http://")):
        return "https"
    if url.startswith("ssh://") or re.match(r"^[^/\s]+@[^/\s]+:", url):
        return "ssh"
    if url.startswith("file://") or url.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", url):
        return "file"
    return "other"


def web_url(remote: str) -> Optional[str]:
    """Best-effort browsable https URL for a git remote (never includes credentials)."""
    remote = sanitize_url(remote)
    match = re.match(r"^(?:ssh://)?[^@/\s]+@([^:/\s]+)[:/](.+?)(?:\.git)?/?$", remote)
    if match:
        return "https://%s/%s" % (match.group(1), match.group(2))
    match = re.match(r"^https?://([^/\s]+)/(.+?)(?:\.git)?/?$", remote)
    if match:
        return "https://%s/%s" % (match.group(1), match.group(2))
    return None


def pid_alive(pid: int) -> Optional[bool]:
    """True/False when known, None when it cannot be told (never signals the process)."""
    if pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False if kernel32.GetLastError() == 87 else None  # 87: invalid parameter = no such pid
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return code.value == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


class FileLock:
    """Cross-platform advisory lock using an O_EXCL lock file.

    The file holds ``pid host time``. A lock whose process is gone on this host is
    broken at once; any other lock is broken only after ``stale_after`` seconds.
    """

    def __init__(self, path: Path, timeout: float = 20.0, stale_after: float = 120.0) -> None:
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after
        self._fd: Optional[int] = None

    def _holder_gone(self) -> bool:
        try:
            parts = self.path.read_text(encoding="ascii", errors="replace").split()
            age = time.time() - os.path.getmtime(self.path)
        except OSError:
            return False
        if age > self.stale_after:
            return True
        if len(parts) >= 2 and parts[1] == _HOST and parts[0].isdigit():
            return pid_alive(int(parts[0])) is False
        return False

    def __enter__(self) -> "FileLock":
        start = time.monotonic()
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, ("%d %s %s\n" % (os.getpid(), _HOST, now_iso())).encode("ascii", "replace"))
                return self
            except FileExistsError:
                if self._holder_gone():
                    try:
                        os.remove(self.path)
                        continue
                    except OSError:
                        pass  # e.g. still open on Windows: wait like any other holder
            if time.monotonic() - start > self.timeout:
                raise GTError(
                    "账本被另一个 gt 进程锁定：%s" % self.path,
                    hint="稍后重试；若确认没有其他 gt 在运行，删除该锁文件。",
                )
            time.sleep(0.05)

    def __exit__(self, *exc: Any) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            owned = os.fstat(fd)
        finally:
            os.close(fd)
        # Windows readers can briefly prevent deletion. This is a bounded
        # release budget, independent of the timeout for acquiring a lock.
        deadline = time.monotonic() + 1.0
        while True:
            try:
                current = self.path.stat()
                if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
                    raise GTError("释放账本锁时锁文件已被替换：%s" % self.path)
                os.remove(self.path)
                return
            except FileNotFoundError:
                return
            except OSError as error:
                remaining = deadline - time.monotonic()
                if getattr(error, "winerror", None) in (32, 33) and remaining > 0:
                    time.sleep(min(0.05, remaining))
                    continue
                raise GTError(
                    "无法释放账本锁：%s（%s）" % (self.path, error),
                    hint="本次写入可能已完成；先核对账本，确认没有其他 gt 在运行后再处理残留锁。",
                ) from error


def _hostname() -> str:
    import socket
    try:
        name = socket.gethostname() or "localhost"
    except OSError:
        name = "localhost"
    return re.sub(r"\s+", "_", name) or "localhost"


_HOST = _hostname()


def read_stdin_text() -> str:
    """Read stdin as UTF-8 regardless of the console code page (Windows)."""
    import sys
    stream = sys.stdin
    if stream is None:
        return ""
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", errors="replace")
    return stream.read()


def valid_date(value: str) -> bool:
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10


def md_cell(value: Any) -> str:
    """Make a value safe for a Markdown table cell."""
    text = "" if value is None else str(value)
    return text.replace("\r", " ").replace("\n", " ").replace("|", "\\|").strip()


def shorten(text: str, limit: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
