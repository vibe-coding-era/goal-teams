"""Project state directory and the append-only, hash-chained ledger."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import VERSION, gitinfo
from .util import EXIT, GTError, FileLock, ZERO_HASH, canonical_json, now_iso, sha256_file, sha256_text, web_url

STATE_DIRNAME = gitinfo.STATE_DIRNAME
CONFIG_SCHEMA = "goal-teams/config@1"
EVENT_SCHEMA = "goal-teams/event@2"
EVENT_SCHEMAS = ("goal-teams/event@1", EVENT_SCHEMA)  # the reducer reads both; event@1 ledgers are not migrated
MANIFEST_SCHEMA = "goal-teams/manifest@1"
MANIFEST_MIN_READER = "2.9.0"   # the first gt that writes manifests; raised only when the format changes
# Capabilities this reader implements. A manifest that requires one we do not have is refused (AC14).
READER_CAPABILITIES = frozenset()

DEFAULT_CONFIG: Dict[str, Any] = {
    "schema": CONFIG_SCHEMA,
    "project": "",
    "locale": "zh",
    "enforce_report": False,
    "require_independent_review": False,
    "git": {"remote_protocol": "inherit", "branch": "feature", "branch_prefix": "goal/"},
}

STATE_GITIGNORE = "evidence/\n.lock\n.hook-*\n*.tmp\n"
# Keep the ledger byte-exact on checkout (core.autocrlf would break the hash chain).
STATE_GITATTRIBUTES = "* -text\n"
EVIDENCE_LOG = re.compile(r"^(R\d+)(?:-[0-9a-f]+)?\.log$")


def find_root(start: Path, explicit: Optional[str] = None) -> Path:
    """Project root: ``--root``; inside a linked git worktree the main worktree when it
    has state (members record into the main project's ledger); else the nearest
    ancestor with ``.goal-teams/``; else the main git worktree root; else ``start``."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    here = start.resolve()
    if gitinfo.is_linked_worktree(here):
        main = gitinfo.main_root(here)
        if main is not None and (main / STATE_DIRNAME / "config.json").is_file():
            return main
    for candidate in [here, *here.parents]:
        if (candidate / STATE_DIRNAME / "config.json").is_file():
            return candidate
    git_root = gitinfo.main_root(here)
    return git_root or here


class Project:
    def __init__(self, root: Path, cwd: Optional[Path] = None) -> None:
        self.root = root
        self.state = root / STATE_DIRNAME
        cwd = (cwd or Path.cwd()).resolve()
        work = gitinfo.toplevel(cwd)
        if work is not None and gitinfo.main_root(cwd) == root:
            self.work_tree = work
        else:
            self.work_tree = root

    # ---- paths -----------------------------------------------------------------
    @property
    def ledger_path(self) -> Path:
        return self.state / "ledger.jsonl"

    @property
    def config_path(self) -> Path:
        return self.state / "config.json"

    @property
    def evidence_dir(self) -> Path:
        return self.state / "evidence"

    @property
    def head_path(self) -> Path:
        return self.state / "ledger.head"

    @property
    def journal_path(self) -> Path:
        return self.state / "journal.json"

    @property
    def manifest_path(self) -> Path:
        return self.state / "manifest.json"

    def tree_label(self) -> str:
        """Where evidence is produced: ``.`` for the main tree, else the worktree path."""
        if self.work_tree == self.root:
            return "."
        try:
            return self.work_tree.relative_to(self.root).as_posix()
        except ValueError:
            return str(self.work_tree)

    def exists(self) -> bool:
        return self.config_path.is_file()

    def require(self) -> None:
        if not self.exists():
            raise GTError(
                "这里还没有 Goal Teams 状态目录：%s" % self.state,
                hint="先运行 gt init；direct 工作的第一条 gt tdd red / gt run 会自动建立。",
            )

    # ---- config ----------------------------------------------------------------
    def config(self) -> Dict[str, Any]:
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.config_path.is_file():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise GTError("config.json 不是有效 JSON：%s" % exc)
            for key, value in data.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
        if not merged.get("project"):
            merged["project"] = self.root.name
        return merged

    def write_config(self, config: Dict[str, Any]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.config_path)

    # ---- manifest --------------------------------------------------------------
    def manifest(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except OSError:
            return None
        except ValueError as exc:
            raise GTError("manifest.json 不是有效 JSON：%s" % exc, code=EXIT.blocked)
        return data if isinstance(data, dict) else None

    def new_manifest(self) -> Dict[str, Any]:
        work = self.work_tree
        origin = next((r["url"] for r in gitinfo.remotes(work) if r["name"] == "origin"), None) if gitinfo.is_repo(work) else None
        repo = web_url(origin) if origin else None
        return {
            "schema": MANIFEST_SCHEMA,
            "event_schema": EVENT_SCHEMA,
            "min_reader": MANIFEST_MIN_READER,
            "required_capabilities": [],
            "project": {"id": sha256_text("%s|%s" % (repo or "", self.root.name))[:16], "name": self.root.name,
                        "repo": repo},
            "created_by": VERSION,
            "created_at": now_iso(),
        }

    def ensure_manifest(self) -> None:
        """A state directory written before manifests existed gets one on its next append (no migration:
        the events stay as they are; the reducer reads both event schemas)."""
        if not self.manifest_path.exists():
            self._atomic_json(self.manifest_path, self.new_manifest())

    def check_manifest(self) -> None:
        """Refuse to judge or extend a ledger this version may not understand (AC14)."""
        manifest = self.manifest()
        if manifest is None:
            return
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise GTError("manifest.json 的 schema 是 %s，本版本只认识 %s；不能据此判定或追加。" % (
                manifest.get("schema"), MANIFEST_SCHEMA), code=EXIT.blocked)
        need = str(manifest.get("min_reader") or "0")
        if _version_tuple(need) > _version_tuple(VERSION):
            raise GTError("账本要求 gt ≥ %s（manifest.json 的 min_reader），当前是 %s；请升级 gt，本版本不判定也不追加。" % (
                need, VERSION), code=EXIT.blocked)
        missing = [c for c in (manifest.get("required_capabilities") or []) if c not in READER_CAPABILITIES]
        if missing:
            raise GTError("账本要求本版本没有的能力：%s（manifest.json 的 required_capabilities）；不能据此判定或追加。" % (
                ", ".join(map(str, missing))), code=EXIT.blocked)

    def _atomic_json(self, path: Path, data: Dict[str, Any]) -> None:
        tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    # ---- ledger ----------------------------------------------------------------
    def _lock(self) -> FileLock:
        return FileLock(self.state / ".lock")

    def read_lines(self) -> List[str]:
        if not self.ledger_path.is_file():
            return []
        raw = self.ledger_path.read_bytes().decode("utf-8")
        lines = raw.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        elif lines:
            # A trailing line without newline is a write in progress; ignore it.
            lines.pop()
        # A CRLF checkout must not break the hash chain: hash the line as gt wrote it.
        return [line[:-1] if line.endswith("\r") else line for line in lines]

    def events(self) -> List[Dict[str, Any]]:
        self.check_manifest()
        out = []
        for number, line in enumerate(self.read_lines(), start=1):
            try:
                out.append(json.loads(line))
            except ValueError:
                raise GTError("账本第 %d 行损坏：%s" % (number, self.ledger_path),
                              hint="运行 gt verify 查看详情；不要手工编辑账本。")
        return out

    def append(self, event_type: str, data: Any, actor: str,
               prepare: Optional[Callable[[int, str], Tuple[Dict[str, Any], Callable[[], None]]]] = None,
               after: Optional[Callable[[], None]] = None, reset_head: bool = False,
               expect: Optional[Callable[[List[Dict[str, Any]]], None]] = None) -> Dict[str, Any]:
        """Append one event under the lock.

        ``prepare(seq, prev)`` may build the data from the final sequence number (and the hash of
        the previous line) and return
        ``(data, commit)``; ``commit`` runs after the line is durably written (used to
        move evidence logs to their receipt name). ``after`` also runs under the lock
        (used to regenerate the projections in ledger order). ``expect(events)`` runs under
        the lock on the events as they are now and raises ``GTError`` when the precondition
        checked before the lock no longer holds (a duplicate id, a replaced goal, a task that
        changed state meanwhile).
        """
        self.require()
        self._ensure_support_files()
        with self._lock():
            self._recover()
            self.ensure_manifest()
            self.check_manifest()
            lines = self.read_lines()
            if not reset_head:
                self._check_head(lines)
            if expect is not None:
                expect([json.loads(line) for line in lines])
            prev = sha256_text(lines[-1]) if lines else ZERO_HASH
            seq = 1
            if lines:
                try:
                    seq = int(json.loads(lines[-1]).get("seq", len(lines))) + 1
                except ValueError:
                    raise GTError("账本最后一行损坏，拒绝继续追加。", hint="运行 gt verify。")
            commit: Optional[Callable[[], None]] = None
            if prepare is not None:
                data, commit = prepare(seq, prev)
            event = {"schema": EVENT_SCHEMA, "seq": seq, "ts": now_iso(), "type": event_type,
                     "actor": actor, "data": data, "prev": prev}
            line = canonical_json(event)
            # 1. intent: what is about to be appended (so a crash between the next two writes is recoverable)
            self._atomic_json(self.journal_path, {"prev_head": self.read_head(), "seq": seq, "sha256": sha256_text(line),
                                                  "type": event_type})
            # 2. the event, durably
            with open(self.ledger_path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            # 3. the head, atomically; 4. the intent is fulfilled
            self._write_head(seq, line)
            if commit is not None:
                commit()  # e.g. the evidence log takes its receipt name, before the intent is cleared
            try:
                os.remove(self.journal_path)
            except OSError:
                pass
            if after is not None:
                after()
            return event

    def read_journal(self) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except OSError:
            return None
        except ValueError:
            raise GTError("journal.json 损坏：上一次写入的意图无法读出，拒绝继续追加。",
                          hint="运行 gt verify；确认原因后可用 gt verify --reset-head --reason \"...\"。")
        return data if isinstance(data, dict) else None

    def _recover(self) -> None:
        """Finish or forget the previous append from its journal (under the lock).

        - journal + the line is the ledger's last line: the head write was lost — write it now.
        - journal + the ledger does not have the line: the event was never written — forget it.
        - journal + the ledger's last line has that seq but another hash: refuse; someone else wrote.
        A line without a trailing newline is a crashed write and is dropped first.
        """
        self._drop_partial_tail()
        journal = self.read_journal()
        if journal is None:
            return
        lines = self.read_lines()
        last = lines[-1] if lines else None
        try:
            last_seq = int(json.loads(last).get("seq")) if last else 0
        except (ValueError, TypeError, AttributeError):
            raise GTError("账本最后一行损坏，拒绝继续追加。", hint="运行 gt verify。")
        seq = int(journal.get("seq") or 0)
        if last is not None and last_seq == seq:
            if sha256_text(last) != journal.get("sha256"):
                raise GTError("journal 记录的待写事件（seq %d）与账本末行不一致：账本在 gt 之外被改写，拒绝继续追加。" % seq,
                              hint="运行 gt verify；确认原因后可用 gt verify --reset-head --reason \"...\"。")
            head = self.read_head()
            if head is None or int(head.get("seq") or 0) < seq:
                self._write_head(seq, last)
            print("gt: 上一次写入在更新链头前中断，已按 journal 补齐（seq %d）。" % seq, file=sys.stderr)
        else:
            prev_head = journal.get("prev_head")
            head = self.read_head()
            if prev_head != head and not (prev_head is None and head is None):
                raise GTError("journal 与 ledger.head 不一致（journal 记 seq %s，head 记 seq %s），拒绝继续追加。" % (
                    (prev_head or {}).get("seq"), (head or {}).get("seq")),
                              hint="运行 gt verify；确认原因后可用 gt verify --reset-head --reason \"...\"。")
            print("gt: 上一次写入在落盘前中断（seq %d 未写入），已忘记该意图。" % seq, file=sys.stderr)
        try:
            os.remove(self.journal_path)
        except OSError:
            pass

    def _write_head(self, seq: int, line: str) -> None:
        """Record the chain head outside the ledger so a truncated tail is detectable."""
        tmp = self.head_path.with_name("ledger.head.%d.tmp" % os.getpid())
        tmp.write_text(json.dumps({"seq": seq, "sha256": sha256_text(line)}) + "\n", encoding="utf-8")
        os.replace(tmp, self.head_path)

    def read_head(self) -> Optional[Dict[str, Any]]:
        try:
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return head if isinstance(head, dict) else None

    def _ensure_support_files(self) -> None:
        for name, text in ((".gitignore", STATE_GITIGNORE), (".gitattributes", STATE_GITATTRIBUTES)):
            path = self.state / name
            if not path.exists():
                try:
                    path.write_text(text, encoding="utf-8")
                except OSError:
                    pass

    def _check_head(self, lines: List[str]) -> None:
        """Refuse to extend a ledger whose tail no longer matches ``ledger.head``.

        Appending would chain onto a truncated or rewritten tail and hide it, so gt stops
        instead (a crash mid-append is recovered from the journal before this check).
        """
        head = self.read_head()
        hint = "运行 gt verify 查看；确认原因后可用 gt verify --reset-head --reason \"...\" 在账本里记下重置。"
        if not lines:
            if head is not None and int(head.get("seq") or 0) > 0:
                raise GTError("账本是空的，但 ledger.head 记录到 seq %s：账本被清空。" % head.get("seq"), hint=hint)
            return
        try:
            last_seq = int(json.loads(lines[-1]).get("seq"))
        except (ValueError, TypeError, AttributeError):
            raise GTError("账本最后一行损坏，拒绝继续追加。", hint=hint)
        if head is None:
            raise GTError("缺少 .goal-teams/ledger.head，无法确认账本末尾完整，拒绝继续追加。", hint=hint)
        head_seq = int(head.get("seq") or 0)
        if head_seq == last_seq and sha256_text(lines[-1]) == head.get("sha256"):
            return
        # A crash between the event write and the head write leaves a journal, which _recover()
        # finishes; without one, a head that is behind means the ledger was written outside gt.
        raise GTError("账本末尾与 ledger.head 不一致（head 记录 seq %d，账本到 seq %d）：账本被截断、改写或在 gt 之外追加，"
                      "拒绝继续追加。" % (head_seq, last_seq), hint=hint)

    def _drop_partial_tail(self) -> None:
        """Under the lock a line without a trailing newline is a crashed write, unless it is
        the complete event that ``ledger.head`` names (only its newline went missing)."""
        if not self.ledger_path.is_file():
            return
        raw = self.ledger_path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            keep = raw.rfind(b"\n") + 1
            tail = raw[keep:].decode("utf-8", errors="replace").rstrip("\r")
            head = self.read_head()
            if head is not None and sha256_text(tail) == head.get("sha256"):
                with open(self.ledger_path, "ab") as handle:
                    handle.write(b"\n")
                return
            with open(self.ledger_path, "r+b") as handle:
                handle.truncate(keep)
            print("gt: 丢弃账本末尾未写完的一行（上次写入中断）。", file=sys.stderr)

    def verify(self) -> List[str]:
        """Problems with the hash chain, the chain head and the evidence logs."""
        problems = []
        prev = ZERO_HASH
        expected_seq = 1
        lines = self.read_lines()
        last_seq = 0
        for number, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except ValueError:
                problems.append("第 %d 行不是有效 JSON" % number)
                prev = sha256_text(line)
                continue
            if event.get("prev") != prev:
                problems.append("第 %d 行（seq %s）的 prev 哈希不匹配：账本被改写或截断" % (number, event.get("seq")))
            if event.get("seq") != expected_seq:
                problems.append("第 %d 行的 seq=%s，期望 %d" % (number, event.get("seq"), expected_seq))
            try:
                expected_seq = int(event.get("seq", expected_seq)) + 1
            except (TypeError, ValueError):
                expected_seq += 1
            last_seq = expected_seq - 1
            prev = sha256_text(line)
        head = self.read_head()
        if head is None:
            if lines:
                problems.append("缺少 .goal-teams/ledger.head：无法确认账本末尾完整（不要删除它）")
        else:
            head_seq = int(head.get("seq") or 0)
            if last_seq < head_seq:
                problems.append("账本被截断：ledger.head 记录到 seq %d，账本只到 seq %d" % (head_seq, last_seq))
            elif last_seq == head_seq and lines and sha256_text(lines[-1]) != head.get("sha256"):
                problems.append("最后一条事件（seq %d）与 ledger.head 不一致：账本被改写" % last_seq)
            elif last_seq > head_seq:
                journal = None
                try:
                    journal = self.read_journal()
                except GTError:
                    problems.append("journal.json 损坏")
                if journal and int(journal.get("seq") or 0) == last_seq and sha256_text(lines[-1]) == journal.get("sha256"):
                    problems.append("上一次写入在更新链头前中断（seq %d）：下一次 gt 命令会按 journal 补齐" % last_seq)
                else:
                    problems.append("账本在 gt 之外多了 %d 条事件（ledger.head 记录到 seq %d）" % (last_seq - head_seq, head_seq))
        for number, line in enumerate(lines, start=1):
            try:
                schema = json.loads(line).get("schema")
            except ValueError:
                continue
            if schema not in EVENT_SCHEMAS:
                problems.append("第 %d 行的 schema %r 不是本版本认识的事件格式" % (number, schema))
                break
        return problems

    def log_warnings(self, receipts: List[Dict[str, Any]]) -> List[str]:
        """Evidence logs that changed after their receipt was written, and logs no receipt names.

        ``evidence/`` is local and not versioned, so after switching branches or restoring the
        ledger from git, logs of the other history are expected; they are reported, not failed.
        """
        out = []
        named = {receipt.get("log") for receipt in receipts}
        if self.evidence_dir.is_dir():
            orphans = [p.name for p in sorted(self.evidence_dir.iterdir())
                       if EVIDENCE_LOG.match(p.name) and ".goal-teams/evidence/%s" % p.name not in named]
            kept = self.evidence_dir / "orphans"
            orphans += ["orphans/%s" % p.name for p in sorted(kept.iterdir())] if kept.is_dir() else []
            if orphans:
                out.append("%d 个证据日志不属于当前账本（切换分支、恢复账本或重置链头后常见）：%s" % (
                    len(orphans), ", ".join(orphans[:6])))
        for receipt in receipts:
            log, digest = receipt.get("log"), receipt.get("log_sha256")
            if not log or not digest:
                continue
            path = self.root / log
            if path.is_file() and sha256_file(path) != digest:
                out.append("%s 的日志在记录后被修改（可能有后台进程仍在写）" % receipt.get("id"))
        return out


def init_state(project: Project, name: Optional[str], locale: Optional[str]) -> bool:
    """Create the state directory. Returns False if it already existed."""
    if project.exists():
        return False
    project.state.mkdir(parents=True, exist_ok=True)
    (project.state / "evidence").mkdir(exist_ok=True)
    (project.state / ".gitignore").write_text(STATE_GITIGNORE, encoding="utf-8")
    (project.state / ".gitattributes").write_text(STATE_GITATTRIBUTES, encoding="utf-8")
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["project"] = name or project.root.name
    if locale:
        config["locale"] = locale
    config["created_at"] = now_iso()
    project.write_config(config)
    project.ledger_path.touch()
    project.ensure_manifest()
    return True


def _version_tuple(text: str) -> Tuple[int, ...]:
    parts = []
    for piece in str(text).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)
