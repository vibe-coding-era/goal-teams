#!/usr/bin/env python3
"""Generate host files from the single sources, and sync the version everywhere.

Sources -> generated files:
  members/_protocol.md + members/_readonly.md + members/goal_*.md
      -> plugins/goal-teams/agents/goal_*.md          (Claude Code subagents)
      -> plugins/goal-teams/codex/agents/goal_*.toml  (Codex custom agents)
      -> the member table inside plugins/goal-teams/skills/goal-teams/rules/tracked.md
  VERSION
      -> plugin.json version, gt package version, identity line in SKILL.md,
         README.md / README.en.md release block

Usage:
  python3 tools/gen.py           # write files
  python3 tools/gen.py --check   # exit 1 if any generated file is out of date (CI)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "goal-teams"
SKILL = PLUGIN / "skills" / "goal-teams"
MEMBERS = ROOT / "members"
REPO_URL = "https://github.com/vibe-coding-era/goal-teams"

MODES = {"write", "runner", "read-only"}
FRONTMATTER_KEYS = ["name", "role", "mode", "description", "nicknames"]
OPTIONAL_KEYS = ["effort", "model"]  # reasoning effort for the host; a model override only when a member needs one
EFFORTS = ("low", "medium", "high")
DEFAULT_EFFORT = {"write": "high", "runner": "low", "read-only": "high"}
BODY_SECTIONS = ["## 职责", "## 输入（packet 提供）", "## 产出", "## 停止条件", "## 常用 gt 命令"]
CLAUDE_DISALLOWED = {"write": "Agent", "runner": "Write, Edit, NotebookEdit, Agent",
                     "read-only": "Write, Edit, NotebookEdit, Agent"}
MAX_BODY = 1800
MAX_DESCRIPTION = 120


class GenError(Exception):
    pass


# ----------------------------------------------------------------------------- parsing
def parse_scalar(raw: str):
    raw = raw.strip()
    if raw.startswith("["):
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise GenError("bad inline list %r: %s" % (raw, exc))
        if not all(isinstance(x, str) for x in value):
            raise GenError("list items must be strings: %r" % raw)
        return value
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return json.loads(raw) if raw[0] == '"' else raw[1:-1]
    return raw


def parse_frontmatter(text: str, source: str) -> Tuple[Dict[str, object], str]:
    if not text.startswith("---\n"):
        raise GenError("%s: missing frontmatter" % source)
    end = text.find("\n---\n", 4)
    if end == -1:
        raise GenError("%s: unterminated frontmatter" % source)
    data: Dict[str, object] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise GenError("%s: bad frontmatter line %r" % (source, line))
        key, value = line.split(":", 1)
        data[key.strip()] = parse_scalar(value)
    return data, text[end + 5:]


def load_members() -> List[Dict[str, object]]:
    protocol = (MEMBERS / "_protocol.md").read_text(encoding="utf-8").strip()
    readonly = (MEMBERS / "_readonly.md").read_text(encoding="utf-8").strip()
    members = []
    for path in sorted(MEMBERS.glob("goal_*.md")):
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"), path.name)
        problems = []
        if [k for k in meta if k not in OPTIONAL_KEYS] != FRONTMATTER_KEYS:
            problems.append("frontmatter keys must be %s (plus optional %s), got %s" % (FRONTMATTER_KEYS, OPTIONAL_KEYS, list(meta)))
        if meta.get("effort", DEFAULT_EFFORT.get(str(meta.get("mode")), "high")) not in EFFORTS:
            problems.append("effort must be one of %s" % ", ".join(EFFORTS))
        if meta.get("name") != path.stem:
            problems.append("name must equal the file name")
        if meta.get("mode") not in MODES:
            problems.append("mode must be one of %s" % sorted(MODES))
        description = str(meta.get("description", ""))
        if not description or len(description) > MAX_DESCRIPTION:
            problems.append("description must be 1..%d chars (got %d)" % (MAX_DESCRIPTION, len(description)))
        nicknames = meta.get("nicknames")
        if not isinstance(nicknames, list) or not nicknames:
            problems.append("nicknames must be a non-empty list")
        body = body.strip()
        if len(body.encode("utf-8")) > MAX_BODY:
            problems.append("body is %d bytes (max %d)" % (len(body.encode("utf-8")), MAX_BODY))
        positions = [body.find(section) for section in BODY_SECTIONS]
        if -1 in positions or positions != sorted(positions):
            problems.append("body sections must be, in order: %s" % ", ".join(BODY_SECTIONS))
        if "'''" in body or "'''" in protocol:
            problems.append("text must not contain ''' (Codex TOML literal string)")
        if problems:
            raise GenError("%s:\n  - %s" % (path.name, "\n  - ".join(problems)))
        parts = [protocol]
        if meta["mode"] != "write":
            parts.append(readonly)
        parts.append(body)
        meta.setdefault("effort", DEFAULT_EFFORT[str(meta["mode"])])
        members.append({**meta, "body": "\n\n".join(parts) + "\n"})
    if not members:
        raise GenError("no members found in %s" % MEMBERS)
    return members


# ----------------------------------------------------------------------------- renderers
def claude_agent(member: Dict[str, object]) -> str:
    model = "\nmodel: %s" % member["model"] if member.get("model") else ""
    return "---\nname: %s\ndescription: %s\ndisallowedTools: %s%s\n---\n\n%s" % (
        member["name"], json.dumps(member["description"], ensure_ascii=False),
        CLAUDE_DISALLOWED[str(member["mode"])], model, member["body"])


def codex_agent(member: Dict[str, object]) -> str:
    model = "model = %s\n" % json.dumps(member["model"]) if member.get("model") else ""
    return (
        "# Generated from members/%s.md by tools/gen.py -- edit the source, then run python3 tools/gen.py\n"
        "name = %s\n"
        "description = %s\n"
        "%s"
        "model_reasoning_effort = %s\n"
        "developer_instructions = '''\n%s'''\n"
        "nickname_candidates = %s\n"
    ) % (member["name"], json.dumps(member["name"]), json.dumps(member["description"], ensure_ascii=False),
         model, json.dumps(member["effort"]), member["body"], json.dumps(member["nicknames"], ensure_ascii=False))


def member_table(members: List[Dict[str, object]], current: str) -> str:
    """Compact: name, role, mode, effort. The dispatch description lives in each agent file, where the
    host shows it; the Lead's rule budget cannot carry 20 long descriptions."""
    rows = ["| 成员 | 角色 | 模式 | effort |", "|---|---|---|---|"]
    for member in members:
        rows.append("| `%s` | %s | %s | %s |" % (member["name"], member["role"], member["mode"], member["effort"]))
    return replace_block(current, "<!-- members:start -->", "<!-- members:end -->", "\n".join(rows))


def replace_block(text: str, start: str, end: str, inner: str) -> str:
    if start not in text or end not in text:
        raise GenError("markers %s ... %s not found" % (start, end))
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return head + start + "\n" + inner + "\n" + end + tail


def version() -> Tuple[str, str]:
    raw = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", raw):
        raise GenError("VERSION must look like 2.7.0, got %r" % raw)
    major, minor, _ = raw.split(".")
    return raw, "V%s.%s" % (major, minor)


def version_transforms(raw: str, display: str) -> Dict[Path, object]:
    """``{path: transform(text) -> text}`` for every file that carries the version."""
    identity = re.compile(r"我是 Goal Teams Lead V\d+\.\d+。")
    say = "我是 Goal Teams Lead %s。" % display

    def plugin_json(text: str) -> str:
        data = json.loads(text)
        data["version"] = raw
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    def package(text: str) -> str:
        text = re.sub(r'^VERSION = "[^"]*"', 'VERSION = "%s"' % raw, text, flags=re.M)
        return re.sub(r'^DISPLAY_VERSION = "[^"]*"', 'DISPLAY_VERSION = "%s"' % display, text, flags=re.M)

    def readme(line: str):
        def apply(text: str) -> str:
            start, end = "<!-- goal-teams-release:start -->", "<!-- goal-teams-release:end -->"
            return replace_block(text, start, end, line) if start in text else text
        return apply

    return {
        SKILL / "SKILL.md": lambda s: identity.sub(say, s),
        SKILL / "scripts" / "goalteams" / "__init__.py": package,
        PLUGIN / ".claude-plugin" / "plugin.json": plugin_json,
        ROOT / "README.md": readme("当前版本：**%s** · [GitHub 发行页](%s/releases/tag/v%s) · [更新记录](CHANGELOG.md)"
                                   % (display, REPO_URL, raw)),
        ROOT / "README.en.md": readme("Current version: **%s** · [GitHub Release](%s/releases/tag/v%s) · "
                                      "[Changelog](CHANGELOG.md)" % (display, REPO_URL, raw)),
    }


def planned_outputs() -> Dict[Path, str]:
    members = load_members()
    outputs: Dict[Path, str] = {}
    for member in members:
        outputs[PLUGIN / "agents" / ("%s.md" % member["name"])] = claude_agent(member)
        outputs[PLUGIN / "codex" / "agents" / ("%s.toml" % member["name"])] = codex_agent(member)
    rules_members = SKILL / "rules" / "tracked.md"
    outputs[rules_members] = member_table(members, rules_members.read_text(encoding="utf-8"))
    raw, display = version()
    for path, transform in version_transforms(raw, display).items():
        if path in outputs:
            outputs[path] = transform(outputs[path])
        elif path.is_file():
            outputs[path] = transform(path.read_text(encoding="utf-8"))
    return outputs


def stale_generated(outputs: Dict[Path, str]) -> List[Path]:
    """Generated agent files that no longer have a member source."""
    expected = {p for p in outputs}
    stale = []
    for folder, pattern in ((PLUGIN / "agents", "goal_*.md"), (PLUGIN / "codex" / "agents", "goal_*.toml")):
        if folder.is_dir():
            stale.extend(p for p in folder.glob(pattern) if p not in expected)
    return stale


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report out-of-date files")
    args = parser.parse_args(argv)
    try:
        outputs = planned_outputs()
    except GenError as exc:
        print("gen: %s" % exc, file=sys.stderr)
        return 2
    changed = [p for p, text in outputs.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
    stale = stale_generated(outputs)
    if args.check:
        for path in changed:
            print("out of date: %s" % path.relative_to(ROOT))
        for path in stale:
            print("stale generated file: %s" % path.relative_to(ROOT))
        if changed or stale:
            print("run: python3 tools/gen.py", file=sys.stderr)
            return 1
        print("generated files are up to date (%d files)" % len(outputs))
        return 0
    for path in changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(outputs[path], encoding="utf-8", newline="\n")
        print("wrote %s" % path.relative_to(ROOT))
    for path in stale:
        path.unlink()
        print("removed %s" % path.relative_to(ROOT))
    if not changed and not stale:
        print("nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
