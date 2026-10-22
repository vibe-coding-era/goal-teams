"""Claude Code Stop hook: opt-in reminder to send the gt report.

Fires in every session where the plugin is enabled, so it must be fast and silent
unless the project explicitly opted in with ``"enforce_report": true`` in
``.goal-teams/config.json``. It blocks at most once per ledger state, which makes
loops impossible even if ``stop_hook_active`` is not provided.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, TextIO

from .ledger import STATE_DIRNAME
from .util import read_stdin_text

ACTIVITY = {"task.add", "task.edit", "task.state", "tdd.red", "tdd.green", "run", "diff", "review", "retire",
            "head.reset",
            "loop.decide", "plan.freeze", "plan.applied", "goal", "goal.update", "goal.accept", "goal.finished", "tdd.confirm"}
MARKERS = ("◆ Goal-Teams", "Benchmark：", "Benchmark: ")


def _state_root(cwd: Path) -> Optional[Path]:
    for candidate in [cwd, *cwd.parents]:
        if (candidate / STATE_DIRNAME / "config.json").is_file():
            return candidate
    return None


def stop(stdin: Optional[TextIO] = None) -> int:
    try:
        raw = stdin.read() if stdin is not None else read_stdin_text()
        payload: Dict[str, Any] = json.loads(raw or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("stop_hook_active"):
        return 0
    root = _state_root(Path(payload.get("cwd") or ".").resolve())
    if root is None:
        return 0
    state_dir = root / STATE_DIRNAME
    try:
        config = json.loads((state_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not config.get("enforce_report"):
        return 0
    last_activity = last_report = 0
    active_goal = False
    try:
        lines = (state_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        if kind == "goal":
            active_goal = True
        if kind == "loop.decide" and (event.get("data") or {}).get("decision") == "stop":
            active_goal = False
            last_activity = max(last_activity, int(event.get("seq", 0)))
        elif kind in ACTIVITY:
            last_activity = int(event.get("seq", 0))
        elif kind == "report":
            last_report = int(event.get("seq", 0))
    if not last_activity or last_report >= last_activity:
        return 0
    message = str(payload.get("last_assistant_message") or "")
    if all(marker in message for marker in MARKERS[:2]) or (MARKERS[0] in message and MARKERS[2] in message):
        return 0
    marker = state_dir / (".hook-%d" % last_activity)
    if marker.exists():
        return 0
    try:
        marker.write_text("blocked once\n", encoding="utf-8")
    except OSError:
        return 0
    reason = ("Goal Teams：本轮有新的执行记录（账本 seq %d），但还没有发送 gt report。"
              "请运行 gt report --summary \"<本轮摘要>\" 并把输出原样作为回复；若这次只是讨论，可忽略本提示。"
              % last_activity)
    if not active_goal:
        reason = "Goal Teams：目标已结束但还没有发送收尾报告。请运行 gt report 并原样发送输出。"
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0
