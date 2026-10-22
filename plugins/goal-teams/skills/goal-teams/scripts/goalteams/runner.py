"""Run a user command, capture its log, and describe the result for a receipt."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .util import GTError, now_iso, sha256_file

TAIL_LINES = 40


def _resolve(argv: List[str]) -> List[str]:
    if not argv:
        raise GTError("缺少要运行的命令。", hint="在 -- 之后写命令，例如：gt run T1 --kind affected -- python -m pytest -q")
    found = shutil.which(argv[0])
    return [found or argv[0], *argv[1:]]


def _kill_tree(proc: "subprocess.Popen[bytes]") -> None:
    """Stop the command and everything it started (it runs in its own process group)."""
    if proc.poll() is not None and os.name == "nt":
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ValueError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def execute(argv: List[str], cwd: Path, log_path: Path, timeout: Optional[float] = None,
            env: Optional[Dict[str, str]] = None, stdin_text: Optional[str] = None) -> Dict[str, Any]:
    """Run ``argv`` without a shell; stdout+stderr go to ``log_path``.

    The command runs in its own process group so a timeout (or Ctrl-C) stops its
    children too, and nothing keeps writing to the log after it was hashed. ``env`` adds to
    the inherited environment; ``stdin_text`` is fed to the command (default: no stdin).
    """
    resolved = _resolve(argv)
    full_env = dict(os.environ, **env) if env else None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    group: Dict[str, Any] = {}
    if os.name == "nt":
        group["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        group["start_new_session"] = True
    with open(log_path, "wb") as log:
        header = "$ %s\n# cwd: %s\n# started: %s\n\n" % (shlex.join(argv), cwd, now_iso())
        log.write(header.encode("utf-8"))
        log.flush()
        try:
            proc = subprocess.Popen(resolved, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                    env=full_env, **group)
        except FileNotFoundError:
            proc = None
            exit_code = 127
            log.write(("\n[gt] command not found: %s\n" % argv[0]).encode("utf-8"))
        except PermissionError:
            proc = None
            exit_code = 126
            log.write(("\n[gt] permission denied: %s\n" % argv[0]).encode("utf-8"))
        if proc is not None:
            try:
                if stdin_text is not None:
                    proc.communicate(stdin_text.encode("utf-8"), timeout=timeout)
                    exit_code = proc.returncode
                else:
                    exit_code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                proc.wait()
                exit_code = 124
                timed_out = True
                log.write(("\n[gt] timed out after %ss\n" % timeout).encode("utf-8"))
            except KeyboardInterrupt:
                _kill_tree(proc)
                proc.wait()
                raise
        log.write(("\n# exit: %d\n" % exit_code).encode("utf-8"))
    duration = int((time.monotonic() - started) * 1000)
    if os.environ.get("GT_FIXED_DURATION_MS"):  # reproducible examples and tests, like GT_NOW
        duration = int(os.environ["GT_FIXED_DURATION_MS"])
    text = log_path.read_bytes().decode("utf-8", errors="replace")
    body = text.split("\n\n", 1)[1] if "\n\n" in text else text
    lines = [line for line in body.splitlines() if not line.startswith("# exit:")]
    own = [line for line in lines if not line.startswith("[gt] ")]  # only the command's output
    summary = next((line.strip() for line in reversed(lines) if line.strip()), "")
    return {
        "cmd": list(argv),
        "exit_code": exit_code,
        "duration_ms": duration,
        "timed_out": timed_out,
        "log_sha256": sha256_file(log_path),
        "summary": summary[:200],
        "_output": "\n".join(own),
        "_tail": lines[-TAIL_LINES:],
    }


def check_pattern(pattern: Optional[str]) -> None:
    if not pattern:
        return
    try:
        re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        raise GTError("--expect 不是有效的正则表达式：%s" % exc)


def expect_matches(output: str, pattern: Optional[str]) -> Optional[bool]:
    if not pattern:
        return None
    try:
        return re.search(pattern, output, re.MULTILINE) is not None
    except re.error as exc:
        raise GTError("--expect 不是有效的正则表达式：%s" % exc)


def print_tail(result: Dict[str, Any], label: str) -> None:
    tail = result.get("_tail") or []
    if tail:
        print("\n".join(tail))
    print(label, file=sys.stdout)


def tmp_log(evidence_dir: Path) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return evidence_dir / (".pending-%d-%d.log" % (os.getpid(), int(time.time() * 1000)))
