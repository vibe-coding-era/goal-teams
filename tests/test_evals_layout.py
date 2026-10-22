"""Offline checks for the `claude plugin eval` suite in plugins/goal-teams/evals/.

No model calls. The checks cover five things:
- every case follows the documented format (prompt.md / case.yaml / graders/*.md), carries
  a Goal Teams trigger when it is meant to load the skill, and splits its graders into
  "scored in both arms" and "with-only" exactly as the README documents;
- every scaffold script passes `bash -n` and runs the way the CLI runs it
  (`bash <script>` in an empty workspace, minimal environment, < 60 s);
- every fixture really contains what its graders look for (bug present, suite green,
  seeded API defects and contract-conforming controls reproducible, release repo in the
  expected state), and every file a grader reads exists or is created by the run;
- the grader regexes match the inputs they are meant to match: tool inputs, replies,
  ledgers written by the real gt CLI, and stream-json traces carrying real unittest output;
- when node is on PATH, the same regexes give the same answers in JavaScript, which is
  how `claude plugin eval` evaluates them.

Grader semantics mirrored here (claude plugin eval 2.1.302): `input_match` is tested with
`new RegExp(p)` against JSON.stringify(tool input); `tool_order` passes when the first
call matching `before` comes before the first call matching `after`; `target: trace` is
the stream-json transcript, one JSON message per line, tool results included.

Run: python3 -m unittest tests.test_evals_layout -v
"""

from __future__ import annotations

import shlex
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALS_DIR = REPO_ROOT / "plugins" / "goal-teams" / "evals"
SKILL_DIR = REPO_ROOT / "plugins" / "goal-teams" / "skills" / "goal-teams"
GT_SCRIPT = SKILL_DIR / "scripts" / "gt.py"

EXPECTED_CASES = {
    "discussion-plain-question",
    "small-bugfix-tdd",
    "medium-feature-ledger",
    "api-defect-hunt",
    "release-needs-authorization",
    "plan-only-requirement-card",
    "direct-slugify-fix",
    "tracked-two-tasks",
}
README_MAX_BYTES = 7000
SCAFFOLD_TIMEOUT_SECONDS = 60

# Cases meant to exercise the Goal Teams path name it in the prompt, so the WITH arm loads
# the skill (both arms get the same prompt). The plain question must not trigger it.
GOAL_TEAMS_CASES = EXPECTED_CASES - {"discussion-plain-question"}
PLAIN_CASES = {"discussion-plain-question"}
TRIGGER_RE = re.compile(r"goal[\s-]*teams", re.IGNORECASE)
# Trigger words from the SKILL.md description (lower-cased); a plain question uses none.
DESCRIPTION_TRIGGERS = ("goal teams", "goal-teams", "团队协作", "多 agent", "规划", "plan mode",
                        "需求卡片", "loop", "带证据", "发布")

# (scored in both arms, with-only indicators) per case; the README table documents the same.
EXPECTED_ARMS: Dict[str, Tuple[Set[str], Set[str]]] = {
    "discussion-plain-question": (
        {"answer-quality", "no-execution-envelope", "no-shell-bookkeeping", "no-team-dispatch"}, set()),
    "small-bugfix-tdd": (
        {"fix-inclusive-threshold", "regression-test-added", "test-before-fix", "red-run-before-fix",
         "evidence-summary"}, {"skill-fired"}),
    "medium-feature-ledger": (
        {"feature-store", "feature-cli", "feature-tests", "cli-tests", "readme-usage", "red-shown",
         "delivery-honesty"},
        {"skill-fired", "ledger-goal", "ledger-tdd", "ledger-report", "progress-line", "task-board"}),
    "api-defect-hunt": (
        {"defect-auth", "defect-duplicate-orders", "defect-read-after-write", "no-false-defects",
         "ui-status-honest", "repro-evidence", "service-untouched"}, {"skill-fired"}),
    "release-needs-authorization": ({"asks-authorization", "no-external-write"}, {"skill-fired"}),
    "plan-only-requirement-card": (
        {"card-content", "acceptance-ids", "no-code-write", "no-code-edit"}, {"skill-fired"}),
    "direct-slugify-fix": (
        {"fix-trailing-dash", "regression-test-added", "red-run-before-fix", "evidence-summary"},
        {"skill-fired", "ledger-direct", "ledger-finished", "no-plan-ceremony"}),
    "tracked-two-tasks": (
        {"feature-char-count", "feature-cli-chars", "tests-added", "cli-tests", "delivery-honesty"},
        {"skill-fired", "ledger-plan", "ledger-finished", "gt-budget"}),
}
# A grader that looks for gt artifacts measures the tool, not the outcome: it must be with-only.
GT_ARTIFACT_RE = re.compile(r"\.goal-teams/|scripts/gt|Goal-Teams|任务执行看板|进度")
# `claude plugin eval --help` options in 2.1.302; the README must not invent others.
KNOWN_EVAL_FLAGS = {
    "--ablation", "--allow-real-servers", "--allow-tools", "--case", "--concurrency", "--disallow-tools",
    "--eval-dir", "--help", "--json", "--judge-model", "--keep-temp", "--max-cost-usd", "--mocks", "--model",
    "--no-publish", "--no-scaffold", "--output-dir", "--publish-report", "--report", "--runs", "--scaffold",
    "--tag", "--threshold", "--trust-plugin", "--verbose",
}

# prompt.md frontmatter keys documented for `claude plugin eval` (an unknown key fails the case).
PROMPT_KEYS = {
    "schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome",
    "model", "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env",
}
CASE_YAML_KEYS = {
    "schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome",
    "context", "execution", "graders",
}
CONTEXT_KEYS = {"scaffold_script", "history_file", "add_dirs"}
EXECUTION_KEYS = {
    "prompt", "model", "max_turns", "timeout_seconds", "allowed_tools",
    "append_system_prompt", "env",
}
COMMON_GRADER_KEYS = {"type", "weight", "arm"}
GRADER_KEYS = {
    "regex": {"pattern", "flags", "match", "target"},
    "tool_used": {"tool", "input_match", "min", "max"},
    "tool_order": {"before", "after"},
    "file_exists": {"path", "exists"},
    "llm": {"criteria", "focus"},
    "baseline": {"baseline_file", "criteria"},
}
# In the .md layout the body fills this field when the frontmatter leaves it out.
BODY_FIELD = {"llm": "criteria", "baseline": "criteria", "regex": "pattern"}
TARGETS = {"last_message", "trace", "files", "mock_calls"}
READ_ONLY_TOOLS = {
    "Read", "Glob", "Grep", "NotebookRead", "Skill", "AskUserQuestion", "Agent", "TodoWrite",
    "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TaskStop",
}
GRANTABLE_TOOLS = {"Bash", "Write", "Edit", "WebFetch", "WebSearch", "PowerShell"}


# YAML subset ---------------------------------------------------------------------------

class YamlSubsetError(ValueError):
    pass


_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*))?$")
_INT_RE = re.compile(r"^[-+]?[0-9]+$")
_FLOAT_RE = re.compile(r"^[-+]?[0-9]+\.[0-9]+$")
_PLAIN_BAD_START = set("[]{},&*!|>'\"%@`#")
_DQ_ESCAPES = {"\\": "\\", '"': '"', "/": "/", "n": "\n", "t": "\t", "r": "\r"}


def parse_yaml_subset(text: str) -> Dict[str, Any]:
    """Parse the YAML subset this suite uses.

    Supported: `key: scalar` (plain, 'single', "double", int, float, bool, null),
    flow lists `[a, 'b']`, flow maps `{a: 1}`, one level of block nesting
    (`key:` followed by indented `sub: value` lines), full-line and trailing comments.
    Anything else raises YamlSubsetError, which keeps the suite inside the subset.
    """
    result: Dict[str, Any] = {}
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if raw[0] in " \t":
            raise YamlSubsetError(f"unexpected indentation: {raw!r}")
        match = _KEY_RE.match(raw.rstrip())
        if not match:
            raise YamlSubsetError(f"not a 'key: value' line: {raw!r}")
        key, rest = match.group(1), match.group(2) or ""
        if key in result:
            raise YamlSubsetError(f"duplicate key: {key}")
        if rest.strip() and not rest.strip().startswith("#"):
            result[key] = parse_yaml_value(rest)
            continue
        block: Dict[str, Any] = {}
        indent: Optional[int] = None
        while index < len(lines):
            sub = lines[index]
            if not sub.strip() or sub.strip().startswith("#"):
                index += 1
                continue
            if "\t" in sub[: len(sub) - len(sub.lstrip())]:
                raise YamlSubsetError(f"tab indentation: {sub!r}")
            lead = len(sub) - len(sub.lstrip(" "))
            if lead == 0:
                break
            if indent is None:
                indent = lead
            elif lead != indent:
                raise YamlSubsetError(f"only one level of nesting is supported: {sub!r}")
            sub_match = _KEY_RE.match(sub[lead:].rstrip())
            if not sub_match:
                raise YamlSubsetError(f"not a 'key: value' line: {sub!r}")
            sub_key, sub_rest = sub_match.group(1), sub_match.group(2) or ""
            if sub_key in block:
                raise YamlSubsetError(f"duplicate key: {key}.{sub_key}")
            if not sub_rest.strip() or sub_rest.strip().startswith("#"):
                raise YamlSubsetError(f"only one level of nesting is supported: {key}.{sub_key}")
            block[sub_key] = parse_yaml_value(sub_rest)
            index += 1
        if not block:
            raise YamlSubsetError(f"{key}: empty value")
        result[key] = block
    return result


def parse_yaml_value(text: str) -> Any:
    value, rest = _parse_node(text.strip(), flow=False)
    rest = rest.strip()
    if rest and not rest.startswith("#"):
        raise YamlSubsetError(f"unexpected text after value: {text!r}")
    return value


def _parse_node(text: str, flow: bool) -> Tuple[Any, str]:
    if text.startswith("'"):
        return _parse_single_quoted(text)
    if text.startswith('"'):
        return _parse_double_quoted(text)
    if text.startswith("["):
        return _parse_flow_list(text)
    if text.startswith("{"):
        return _parse_flow_map(text)
    return _parse_plain(text, flow)


def _parse_single_quoted(text: str) -> Tuple[str, str]:
    out: List[str] = []
    index = 1
    while index < len(text):
        char = text[index]
        if char == "'":
            if text[index + 1:index + 2] == "'":
                out.append("'")
                index += 2
                continue
            return "".join(out), text[index + 1:]
        out.append(char)
        index += 1
    raise YamlSubsetError(f"unterminated single-quoted string: {text!r}")


def _parse_double_quoted(text: str) -> Tuple[str, str]:
    out: List[str] = []
    index = 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            escape = text[index + 1:index + 2]
            if escape not in _DQ_ESCAPES:
                raise YamlSubsetError(f"unsupported escape \\{escape} in {text!r} (single-quote regexes)")
            out.append(_DQ_ESCAPES[escape])
            index += 2
            continue
        if char == '"':
            return "".join(out), text[index + 1:]
        out.append(char)
        index += 1
    raise YamlSubsetError(f"unterminated double-quoted string: {text!r}")


def _parse_flow_list(text: str) -> Tuple[List[Any], str]:
    items: List[Any] = []
    rest = text[1:].lstrip()
    if rest.startswith("]"):
        return items, rest[1:]
    while True:
        value, rest = _parse_node(rest, flow=True)
        items.append(value)
        rest = rest.lstrip()
        if rest.startswith(","):
            rest = rest[1:].lstrip()
            continue
        if rest.startswith("]"):
            return items, rest[1:]
        raise YamlSubsetError(f"malformed flow list: {text!r}")


def _parse_flow_map(text: str) -> Tuple[Dict[str, Any], str]:
    mapping: Dict[str, Any] = {}
    rest = text[1:].lstrip()
    if rest.startswith("}"):
        return mapping, rest[1:]
    while True:
        match = re.match(r"([A-Za-z_][A-Za-z0-9_-]*)\s*:\s+", rest)
        if not match:
            raise YamlSubsetError(f"malformed flow map: {text!r}")
        key = match.group(1)
        if key in mapping:
            raise YamlSubsetError(f"duplicate key in flow map: {key}")
        value, rest = _parse_node(rest[match.end():], flow=True)
        mapping[key] = value
        rest = rest.lstrip()
        if rest.startswith(","):
            rest = rest[1:].lstrip()
            continue
        if rest.startswith("}"):
            return mapping, rest[1:]
        raise YamlSubsetError(f"malformed flow map: {text!r}")


def _parse_plain(text: str, flow: bool) -> Tuple[Any, str]:
    if not text:
        raise YamlSubsetError("empty value")
    if text[0] in _PLAIN_BAD_START or text[:2] in ("- ", "? ", ": "):
        raise YamlSubsetError(f"plain scalar starts with a YAML indicator, quote it: {text!r}")
    end = len(text)
    comment = re.search(r"\s#", text)
    if comment:
        end = comment.start()
    if flow:
        stop = re.search(r"[,\]}]", text[:end])
        if stop:
            end = stop.start()
    token = text[:end].rstrip()
    if ": " in token or token.endswith(":"):
        raise YamlSubsetError(f"plain scalar contains ': ', quote it: {token!r}")
    return _plain_value(token), text[end:]


def _plain_value(token: str) -> Any:
    if token in ("true", "True", "TRUE"):
        return True
    if token in ("false", "False", "FALSE"):
        return False
    if token in ("null", "Null", "NULL", "~"):
        return None
    if _INT_RE.match(token):
        return int(token)
    if _FLOAT_RE.match(token):
        return float(token)
    return token


# Case loading --------------------------------------------------------------------------

# Same expression the CLI uses: frontmatter ends at the first '---' after the opener.
_FRONTMATTER_RE = re.compile(r"^---\s*\n([\s\S]*?)---\s*\n?")


def split_frontmatter(text: str) -> Tuple[Optional[str], str, List[str]]:
    problems: List[str] = []
    if text.startswith("\ufeff"):
        problems.append("file starts with a BOM")
    if "\r" in text:
        problems.append("file has CR line endings")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, text, problems
    frontmatter = match.group(1)
    if frontmatter and not frontmatter.endswith("\n"):
        problems.append("frontmatter contains '---' before its closing line")
    return frontmatter, text[match.end():], problems


def discover_cases() -> List[Path]:
    cases: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(EVALS_DIR):
        relative = Path(dirpath).relative_to(EVALS_DIR)
        if relative.parts and relative.parts[0] in ("results", "mocks"):
            dirnames[:] = []
            continue
        if "prompt.md" in filenames or "case.yaml" in filenames:
            cases.append(Path(dirpath))
            dirnames[:] = []  # everything inside a case directory belongs to that case
        dirnames.sort()
    return sorted(cases)


def load_prompt(case_dir: Path) -> Tuple[Dict[str, Any], str, List[str]]:
    path = case_dir / "prompt.md"
    if not path.is_file():
        return {}, "", []
    frontmatter, body, problems = split_frontmatter(path.read_text(encoding="utf-8"))
    if frontmatter is None:
        return {}, body.strip(), problems
    try:
        return parse_yaml_subset(frontmatter), body.strip(), problems
    except YamlSubsetError as exc:
        return {}, body.strip(), problems + [f"prompt.md frontmatter: {exc}"]


def load_case_yaml(case_dir: Path) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    path = case_dir / "case.yaml"
    if not path.is_file():
        return None, []
    try:
        return parse_yaml_subset(path.read_text(encoding="utf-8")), []
    except YamlSubsetError as exc:
        return None, [f"case.yaml: {exc}"]


def load_graders(case_dir: Path) -> List[Tuple[str, Optional[Dict[str, Any]], List[str]]]:
    loaded = []
    for path in sorted((case_dir / "graders").glob("*.md")):
        frontmatter, body, problems = split_frontmatter(path.read_text(encoding="utf-8"))
        if frontmatter is None:
            problems.append("no frontmatter: the CLI silently skips grader files without one")
            loaded.append((path.stem, None, problems))
            continue
        try:
            grader = parse_yaml_subset(frontmatter)
        except YamlSubsetError as exc:
            loaded.append((path.stem, None, problems + [f"frontmatter: {exc}"]))
            continue
        field = BODY_FIELD.get(grader.get("type")) if isinstance(grader.get("type"), str) else None
        if field and field not in grader and body.strip():
            grader[field] = body.strip()
        loaded.append((path.stem, grader, problems))
    return loaded


def case_allowed_tools(case_dir: Path) -> List[str]:
    prompt, _, _ = load_prompt(case_dir)
    case_yaml, _ = load_case_yaml(case_dir)
    tools = prompt.get("allowed_tools")
    if tools is None and case_yaml:
        tools = (case_yaml.get("execution") or {}).get("allowed_tools")
    return list(tools or [])


def grader_by_name(case: str, name: str) -> Dict[str, Any]:
    for grader_name, grader, problems in load_graders(EVALS_DIR / case):
        if grader_name == name:
            if grader is None:
                raise AssertionError(f"{case}/{name}: {problems}")
            return grader
    raise AssertionError(f"grader not found: {case}/graders/{name}.md")


def grader_file(grader: Dict[str, Any]) -> Optional[str]:
    """The workspace file a regex `target` or llm `focus` reads, if it reads one."""
    where = grader.get("target") if grader.get("type") == "regex" else grader.get("focus")
    return where.get("path") if isinstance(where, dict) else None


def is_with_only(grader: Dict[str, Any]) -> bool:
    """The CLI's rule: `arm: with-only`, or a `tool_used: Skill` grader that sets no arm."""
    if grader.get("arm") == "with-only":
        return True
    return "arm" not in grader and grader.get("type") == "tool_used" and grader.get("tool") == "Skill"


# Regex helpers ---------------------------------------------------------------------------

_JS_INCOMPATIBLE = ("(?P<", "(?P=", "(?#", "(?>", "\\A", "\\Z", "(?i", "(?m", "(?s", "(?x", "(?a", "(?u")


def js_regex(pattern: str, flags: str = "") -> "re.Pattern[str]":
    """Compile a grader regex with Python `re` the way JavaScript would read it."""
    for token in _JS_INCOMPATIBLE:
        if token in pattern:
            raise re.error(f"{token!r} is not valid JavaScript regex syntax")
    py_flags = re.ASCII  # JavaScript \b, \w and \d are ASCII-only without the u flag
    if "i" in flags:
        py_flags |= re.IGNORECASE
    if "m" in flags:
        py_flags |= re.MULTILINE
    if "s" in flags:
        py_flags |= re.DOTALL
    return re.compile(pattern, py_flags)


def tool_input_text(tool_input: Dict[str, Any]) -> str:
    """What `input_match` is tested against: the JSON-encoded tool input (like JSON.stringify)."""
    return json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))


ToolCall = Tuple[str, Dict[str, Any]]


def first_matching_call(calls: List[ToolCall], ref: Any) -> int:
    """Index of the first call matching a tool_order side (a tool name or {tool, input_match}), or -1."""
    tool, pattern = (ref, None) if isinstance(ref, str) else (ref["tool"], ref.get("input_match"))
    regex = js_regex(pattern) if pattern else None
    for index, (name, tool_input) in enumerate(calls):
        if name == tool and (regex is None or regex.search(tool_input_text(tool_input))):
            return index
    return -1


def tool_order_passes(calls: List[ToolCall], grader: Dict[str, Any]) -> bool:
    """`tool_order` as the CLI scores it: both sides called, first `before` precedes first `after`."""
    before, after = first_matching_call(calls, grader["before"]), first_matching_call(calls, grader["after"])
    return before != -1 and after != -1 and before < after


# Validation ----------------------------------------------------------------------------

def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _check_target(value: Any, label: str) -> List[str]:
    if isinstance(value, str):
        return [] if value in TARGETS else [f"{label}: unknown value {value!r}"]
    if isinstance(value, dict):
        path = value.get("path")
        if set(value) != {"source", "path"} or value.get("source") != "file":
            return [f"{label}: must be one of {sorted(TARGETS)} or {{source: file, path: ...}}"]
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
            return [f"{label}: path must be a relative path inside the workspace"]
        return []
    return [f"{label}: must be a string or a mapping"]


def _check_regex(pattern: Any, label: str, flags: str = "") -> List[str]:
    if not isinstance(pattern, str) or not pattern:
        return [f"{label}: must be a non-empty string"]
    try:
        js_regex(pattern, flags)
    except re.error as exc:
        return [f"{label}: does not compile: {exc}"]
    return []


def _check_tool_ref(value: Any, label: str) -> List[str]:
    if isinstance(value, str):
        return [] if value else [f"{label}: empty tool name"]
    if not isinstance(value, dict) or not isinstance(value.get("tool"), str) or not value["tool"]:
        return [f"{label}: must be a tool name or {{tool, input_match}}"]
    errors = [f"{label}: unknown key {key!r}" for key in set(value) - {"tool", "input_match"}]
    if "input_match" in value:
        errors += _check_regex(value["input_match"], f"{label}.input_match")
    return errors


def validate_grader(grader: Dict[str, Any], case_dir: Path) -> List[str]:
    kind = grader.get("type")
    if kind not in GRADER_KEYS:
        return [f"type must be one of {sorted(GRADER_KEYS)}, got {kind!r}"]
    errors = [f"unknown key {key!r} for type {kind}"
              for key in sorted(set(grader) - GRADER_KEYS[kind] - COMMON_GRADER_KEYS)]
    if "weight" in grader:
        weight = grader["weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            errors.append("weight must be a positive number")
    if "arm" in grader and grader["arm"] not in ("with-only", "both"):
        errors.append("arm must be with-only or both")
    if kind == "regex":
        flags = grader.get("flags", "")
        if not isinstance(flags, str) or not re.fullmatch(r"[dgimsuvy]*", flags):
            errors.append("flags must be JavaScript RegExp flags (d g i m s u v y)")
            flags = ""
        errors += _check_regex(grader.get("pattern"), "pattern", flags)
        match = grader.get("match", "contains")
        if not (match in ("contains", "not_contains") or re.fullmatch(r"count:\d+", str(match))):
            errors.append("match must be contains | not_contains | count:N")
        errors += _check_target(grader.get("target", "last_message"), "target")
    elif kind == "tool_used":
        if not isinstance(grader.get("tool"), str) or not grader["tool"]:
            errors.append("tool is required")
        if "input_match" in grader:
            errors += _check_regex(grader["input_match"], "input_match")
        for bound in ("min", "max"):
            if bound in grader and (not _is_int(grader[bound]) or grader[bound] < 0):
                errors.append(f"{bound} must be a non-negative integer")
        low, high = grader.get("min", 1), grader.get("max")
        if _is_int(low) and _is_int(high) and low > high:
            errors.append("min must not exceed max")
    elif kind == "tool_order":
        for side in ("before", "after"):
            if side not in grader:
                errors.append(f"{side} is required")
            else:
                errors += _check_tool_ref(grader[side], side)
    elif kind == "file_exists":
        if not isinstance(grader.get("path"), str) or not grader["path"]:
            errors.append("path is required")
        if "exists" in grader and not isinstance(grader["exists"], bool):
            errors.append("exists must be true or false")
    elif kind == "llm":
        if not isinstance(grader.get("criteria"), str) or not grader["criteria"].strip():
            errors.append("criteria (or a file body) is required")
        errors += _check_target(grader.get("focus", "last_message"), "focus")
    elif kind == "baseline":
        baseline = grader.get("baseline_file")
        if not isinstance(baseline, str) or not (case_dir / baseline).is_file():
            errors.append("baseline_file must name a .jsonl file in the case directory")
        if not isinstance(grader.get("criteria"), str) or not grader["criteria"].strip():
            errors.append("criteria (or a file body) is required")
    return errors


def validate_prompt_frontmatter(frontmatter: Dict[str, Any]) -> List[str]:
    errors = [f"unknown prompt.md key {key!r}" for key in sorted(set(frontmatter) - PROMPT_KEYS)]
    for key in ("name", "description", "expected_outcome", "model", "append_system_prompt"):
        if key in frontmatter and not isinstance(frontmatter[key], str):
            errors.append(f"{key} must be a string")
    if "schema_version" in frontmatter and frontmatter["schema_version"] != "1.1":
        errors.append('schema_version must be the string "1.1"')
    for key in ("tags", "plugins", "allowed_tools"):
        if key in frontmatter and not _is_str_list(frontmatter[key]):
            errors.append(f"{key} must be a list of strings")
    for key, high in (("runs", 50), ("max_turns", 200), ("timeout_seconds", 3600)):
        if key in frontmatter:
            value = frontmatter[key]
            if not _is_int(value) or not 1 <= value <= high:
                errors.append(f"{key} must be an integer in 1..{high}")
    env = frontmatter.get("env", {})
    if not isinstance(env, dict) or any(not re.fullmatch(r"EVAL_[A-Z0-9_]*", key) for key in env):
        errors.append("env keys must match EVAL_[A-Z0-9_]*")
    for tool in frontmatter.get("allowed_tools", []) or []:
        if not (tool in READ_ONLY_TOOLS or tool in GRANTABLE_TOOLS or tool.startswith("mcp__")
                or re.fullmatch(r"[A-Za-z]+\(.+\)", tool)):
            errors.append(f"allowed_tools: unknown tool {tool!r}")
    return errors


def validate_case_yaml(case_yaml: Dict[str, Any], case_dir: Path) -> List[str]:
    errors = [f"unknown case.yaml key {key!r}" for key in sorted(set(case_yaml) - CASE_YAML_KEYS)]
    if case_yaml.get("schema_version") != "1.1":
        errors.append('schema_version must be the string "1.1"')
    if case_yaml.get("name") != case_dir.name:
        errors.append(f"name must be the directory name {case_dir.name!r}")
    context = case_yaml.get("context", {})
    if not isinstance(context, dict):
        return errors + ["context must be a mapping"]
    errors += [f"unknown context key {key!r}" for key in sorted(set(context) - CONTEXT_KEYS)]
    execution = case_yaml.get("execution", {})
    if not isinstance(execution, dict):
        errors.append("execution must be a mapping")
    else:
        errors += [f"unknown execution key {key!r}" for key in sorted(set(execution) - EXECUTION_KEYS)]
    for key in ("scaffold_script", "history_file"):
        if key not in context:
            continue
        value = context[key]
        if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts:
            errors.append(f"context.{key} must be a relative path inside the case directory")
        elif not (case_dir / value).is_file():
            errors.append(f"context.{key}: {value} does not exist")
        elif key == "scaffold_script" and os.name != "nt" and not os.access(case_dir / value, os.X_OK):
            errors.append(f"context.scaffold_script: {value} is not executable (chmod +x)")
    for directory in context.get("add_dirs", []) or []:
        if not (case_dir / directory).is_dir():
            errors.append(f"context.add_dirs: {directory} is not a directory in the case")
    return errors


def scaffold_script(case_dir: Path) -> Optional[Path]:
    case_yaml, _ = load_case_yaml(case_dir)
    if not case_yaml:
        return None
    script = (case_yaml.get("context") or {}).get("scaffold_script")
    return (case_dir / script).resolve() if isinstance(script, str) else None


# Layout tests ----------------------------------------------------------------------------

class EvalSuiteLayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        if not EVALS_DIR.is_dir():
            self.fail(f"eval directory missing: {EVALS_DIR}")
        self.cases = discover_cases()

    def test_expected_cases_present(self) -> None:
        names = {case.name for case in self.cases}
        self.assertTrue(EXPECTED_CASES <= names, f"missing cases: {sorted(EXPECTED_CASES - names)}")
        for case in self.cases:
            self.assertRegex(case.name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertEqual(len(names), len(self.cases), "case names must be unique")

    def test_readme_and_gitignore(self) -> None:
        readme = EVALS_DIR / "README.md"
        self.assertTrue(readme.is_file(), "evals/README.md is missing")
        size = len(readme.read_bytes())
        self.assertLessEqual(size, README_MAX_BYTES, f"README.md is {size} bytes")
        gitignore = (EVALS_DIR / ".gitignore").read_text(encoding="utf-8").split()
        self.assertIn("results/", gitignore)

    def test_no_stray_build_artifacts(self) -> None:
        stray = [str(path.relative_to(EVALS_DIR)) for path in EVALS_DIR.rglob("*")
                 if path.name in ("__pycache__", ".DS_Store") or path.suffix == ".pyc"]
        self.assertEqual(stray, [], "remove build artifacts from the eval directory")

    def test_prompt_and_case_yaml(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.name):
                prompt, body, problems = load_prompt(case)
                case_yaml, yaml_problems = load_case_yaml(case)
                errors = problems + yaml_problems
                if (case / "prompt.md").is_file():
                    errors += validate_prompt_frontmatter(prompt)
                if case_yaml is not None:
                    errors += validate_case_yaml(case_yaml, case)
                execution = (case_yaml or {}).get("execution") or {}
                if not body and not execution.get("prompt"):
                    errors.append("no prompt: prompt.md body and execution.prompt are both empty")
                self.assertEqual(errors, [])

    def test_graders(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.name):
                graders = load_graders(case)
                self.assertGreaterEqual(len(graders), 1, "a case needs at least one grader")
                errors: List[str] = []
                for name, grader, problems in graders:
                    errors += [f"{name}: {problem}" for problem in problems]
                    if grader is not None:
                        errors += [f"{name}: {error}" for error in validate_grader(grader, case)]
                self.assertEqual(errors, [])

    def test_graders_only_need_tools_the_case_lists(self) -> None:
        # A grader that needs a call to a tool the run withholds can never pass.
        for case in self.cases:
            allowed = set(case_allowed_tools(case))
            for name, grader, _ in load_graders(case):
                if grader is None:
                    continue
                needed: List[str] = []
                if grader.get("type") == "tool_used" and grader.get("min", 1) >= 1:
                    needed.append(grader.get("tool"))
                if grader.get("type") == "tool_order":
                    for side in ("before", "after"):
                        ref = grader.get(side)
                        needed.append(ref if isinstance(ref, str) else (ref or {}).get("tool"))
                for tool in needed:
                    with self.subTest(case=case.name, grader=name, tool=tool):
                        self.assertIn(tool, allowed, "list the tool in allowed_tools")

    def test_skill_indicator_uses_plugin_skill_name(self) -> None:
        for case in self.cases:
            for name, grader, _ in load_graders(case):
                if grader and grader.get("type") == "tool_used" and grader.get("tool") == "Skill":
                    with self.subTest(case=case.name, grader=name):
                        pattern = js_regex(grader["input_match"])
                        self.assertTrue(pattern.search(tool_input_text({"skill": "goal-teams:goal-teams"})))
                        self.assertTrue(pattern.search(tool_input_text({"skill": "goal-teams"})))
                        self.assertFalse(pattern.search(tool_input_text({"skill": "goal-teams-lite"})))

    def test_goal_teams_cases_carry_a_natural_trigger(self) -> None:
        description = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").split("\n---", 1)[0]
        self.assertTrue(TRIGGER_RE.search(description), "SKILL.md description no longer names Goal Teams")
        names = {case.name for case in self.cases}
        self.assertEqual(GOAL_TEAMS_CASES | PLAIN_CASES, names & (GOAL_TEAMS_CASES | PLAIN_CASES))
        for case in self.cases:
            _, body, _ = load_prompt(case)
            with self.subTest(case=case.name):
                if case.name in GOAL_TEAMS_CASES:
                    self.assertRegex(body, TRIGGER_RE, "say Goal Teams in the prompt so the WITH arm loads the skill")
                if case.name in PLAIN_CASES:
                    found = [word for word in DESCRIPTION_TRIGGERS if word in body.lower()]
                    self.assertEqual(found, [], "a plain question must not contain skill trigger words")

    def test_arms_match_the_documented_split(self) -> None:
        self.assertEqual(set(EXPECTED_ARMS), {case.name for case in self.cases})
        for case in self.cases:
            graders = [(name, grader) for name, grader, _ in load_graders(case) if grader is not None]
            scored = {name for name, grader in graders if not is_with_only(grader)}
            with_only = {name for name, grader in graders if is_with_only(grader)}
            with self.subTest(case=case.name):
                self.assertEqual((scored, with_only), EXPECTED_ARMS[case.name])
                self.assertTrue(scored, "Δ comes only from graders scored in both arms")

    def test_gt_artifact_graders_are_with_only(self) -> None:
        # A baseline without the plugin cannot produce gt artifacts, so grading them in both
        # arms would measure the tool rather than the outcome.
        for case in self.cases:
            for name, grader, _ in load_graders(case):
                if grader is None:
                    continue
                kind = grader.get("type")
                path = grader_file(grader) or (grader.get("path") if kind == "file_exists" else None)
                positive = ((kind == "regex" and grader.get("match", "contains") == "contains"
                             and GT_ARTIFACT_RE.search(grader.get("pattern", "")))
                            or (kind == "tool_used" and grader.get("min", 1) >= 1
                                and GT_ARTIFACT_RE.search(grader.get("input_match", ""))))
                if positive or (path and GT_ARTIFACT_RE.search(path)):
                    with self.subTest(case=case.name, grader=name):
                        self.assertEqual(grader.get("arm"), "with-only")

    def test_readme_documents_every_grader_and_only_real_flags(self) -> None:
        readme = (EVALS_DIR / "README.md").read_text(encoding="utf-8")
        for case in self.cases:
            for name, _, _ in load_graders(case):
                with self.subTest(case=case.name, grader=name):
                    self.assertIn(name, readme)
        flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", readme))
        self.assertEqual(sorted(flags - KNOWN_EVAL_FLAGS), [], "README names options the CLI does not have")


class YamlSubsetParserTest(unittest.TestCase):
    def test_supported_subset(self) -> None:
        parsed = parse_yaml_subset(
            "# comment\n"
            'schema_version: "1.1"\n'
            "tags: [a, 'b c', \"d\"]\n"
            "max_turns: 40  # trailing comment\n"
            "pattern: '\\bfoo\\s+it''s'\n"
            "context:\n"
            "  scaffold_script: scaffold.sh\n"
            "  add_dirs: []\n"
            "before: {tool: Bash, input_match: 'x|y'}\n"
            "exists: false\n"
        )
        self.assertEqual(parsed["schema_version"], "1.1")
        self.assertEqual(parsed["tags"], ["a", "b c", "d"])
        self.assertEqual(parsed["max_turns"], 40)
        self.assertEqual(parsed["pattern"], "\\bfoo\\s+it's")
        self.assertEqual(parsed["context"], {"scaffold_script": "scaffold.sh", "add_dirs": []})
        self.assertEqual(parsed["before"], {"tool": "Bash", "input_match": "x|y"})
        self.assertIs(parsed["exists"], False)

    def test_rejects_yaml_this_suite_does_not_use(self) -> None:
        for text in (
            "schema_version: 1.1\nname: x\nbad line\n",
            'pattern: "\\s+"\n',  # invalid escape in a double-quoted YAML string
            "path: **/x\n",  # alias indicator, must be quoted
            "a:\n  b:\n    c: 1\n",  # two levels of nesting
            "a: 1\na: 2\n",
            "list:\n  - a\n",
        ):
            with self.subTest(text=text):
                with self.assertRaises(YamlSubsetError):
                    parse_yaml_subset(text)
        self.assertEqual(parse_yaml_subset("schema_version: 1.1\n")["schema_version"], 1.1)


# Scaffold tests --------------------------------------------------------------------------

def _git_version() -> Tuple[int, int]:
    try:
        output = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return (0, 0)
    match = re.search(r"(\d+)\.(\d+)", output)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


SCAFFOLD_SKIP_REASON = None
if os.name == "nt":
    SCAFFOLD_SKIP_REASON = "scaffold scripts run under bash on POSIX (use WSL2 on Windows)"
elif not shutil.which("bash") or not shutil.which("git"):
    SCAFFOLD_SKIP_REASON = "bash and git are required to run scaffold scripts"
elif _git_version() < (2, 31):
    SCAFFOLD_SKIP_REASON = "claude plugin eval requires git >= 2.31"


class ScaffoldRun:
    def __init__(self, workspace: Path, env: Dict[str, str], returncode: Optional[int],
                 stderr: str, seconds: float) -> None:
        self.workspace = workspace
        self.env = env
        self.returncode = returncode
        self.stderr = stderr
        self.seconds = seconds


_TMP_ROOT: Optional[tempfile.TemporaryDirectory] = None
_SCAFFOLD_RUNS: Dict[str, ScaffoldRun] = {}


def tmp_root() -> Path:
    """One temporary directory for every workspace this module builds; removed at module teardown."""
    global _TMP_ROOT
    if _TMP_ROOT is None:
        _TMP_ROOT = tempfile.TemporaryDirectory(prefix="gt-evals-")
    return Path(_TMP_ROOT.name)


def eval_like_env(home: Path, tmp: Path) -> Dict[str, str]:
    """The fixed environment `claude plugin eval` gives a scaffold script."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "TERM": "dumb",
        "GIT_CONFIG_NOSYSTEM": "1",
        "USER_TYPE": "external",
        "NODE_ENV": "production",
    }


def run_scaffold(case_dir: Path) -> ScaffoldRun:
    """Run a case's scaffold once (cached): `bash <realpath>` with cwd = a fresh workspace."""
    if case_dir.name in _SCAFFOLD_RUNS:
        return _SCAFFOLD_RUNS[case_dir.name]
    script = scaffold_script(case_dir)
    if script is None:
        raise AssertionError(f"{case_dir.name} has no scaffold_script")
    root = tmp_root() / case_dir.name
    workspace, home, tmp = root / "work", root / "home", root / "tmp"
    for directory in (workspace, home, tmp):
        directory.mkdir(parents=True)
    env = eval_like_env(home, tmp)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["bash", str(script)], cwd=str(workspace), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            timeout=SCAFFOLD_TIMEOUT_SECONDS,
        )
        returncode, stderr = proc.returncode, proc.stderr
    except subprocess.TimeoutExpired:
        returncode, stderr = None, f"timed out after {SCAFFOLD_TIMEOUT_SECONDS}s"
    run = ScaffoldRun(workspace, env, returncode, stderr, time.monotonic() - started)
    _SCAFFOLD_RUNS[case_dir.name] = run
    return run


def tearDownModule() -> None:  # noqa: N802
    global _TMP_ROOT
    if _TMP_ROOT is not None:
        _TMP_ROOT.cleanup()
        _TMP_ROOT = None


def scaffolded_cases() -> List[Path]:
    return [case for case in discover_cases() if scaffold_script(case) is not None]


@unittest.skipIf(SCAFFOLD_SKIP_REASON is not None, SCAFFOLD_SKIP_REASON or "")
class ScaffoldTest(unittest.TestCase):
    def test_scaffold_scripts_pass_bash_syntax_check(self) -> None:
        for case in scaffolded_cases():
            with self.subTest(case=case.name):
                proc = subprocess.run(["bash", "-n", str(scaffold_script(case))],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_scaffold_scripts_run_in_a_fresh_workspace(self) -> None:
        self.assertGreaterEqual(len(scaffolded_cases()), 4)
        for case in scaffolded_cases():
            with self.subTest(case=case.name):
                run = run_scaffold(case)
                self.assertEqual(run.returncode, 0, f"scaffold failed: {run.stderr[-1500:]}")
                self.assertLess(run.seconds, SCAFFOLD_TIMEOUT_SECONDS)
                self.assertTrue((run.workspace / ".git").is_dir(), "scaffold should create a git repo")
                status = subprocess.run(["git", "status", "--porcelain"], cwd=str(run.workspace),
                                        env=run.env, capture_output=True, text=True, check=True)
                self.assertEqual(status.stdout, "", "scaffolded repo should be clean")
                # The CLI may drop an empty `.eval-artifacts` placeholder in the workspace;
                # it must not show up as an untracked (out-of-scope) change.
                placeholder = run.workspace / ".eval-artifacts"
                placeholder.touch()
                try:
                    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(run.workspace),
                                            env=run.env, capture_output=True, text=True, check=True)
                    self.assertEqual(status.stdout, "", ".eval-artifacts should be git-excluded")
                finally:
                    placeholder.unlink()

    def test_file_graders_point_at_scaffolded_files_and_fail_before_any_work(self) -> None:
        for case in scaffolded_cases():
            run = run_scaffold(case)
            if run.returncode != 0:
                continue  # reported by test_scaffold_scripts_run_in_a_fresh_workspace
            _, prompt_body, _ = load_prompt(case)
            with self.subTest(case=case.name, check="gt state comes from the run"):
                self.assertFalse((run.workspace / ".goal-teams").exists())
            for name, grader, _ in load_graders(case):
                if not grader:
                    continue
                with self.subTest(case=case.name, grader=name):
                    rel = grader_file(grader)
                    if rel is not None:
                        path = run.workspace / rel
                        if not path.exists():
                            # A file the run creates: gt state (with-only), or one the prompt asks for.
                            self.assertTrue(rel.startswith(".goal-teams/") or f"`{rel}`" in prompt_body,
                                            f"{rel} is neither scaffolded nor asked for in prompt.md")
                        elif grader["type"] == "regex" and grader.get("match", "contains") == "contains":
                            pattern = js_regex(grader["pattern"], grader.get("flags", ""))
                            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")),
                                              "grader already passes on the untouched fixture")
                    if grader.get("type") == "file_exists" and grader.get("exists", True):
                        glob = grader["path"].replace("**/", "")
                        self.assertEqual(list(run.workspace.glob("**/" + glob)), [],
                                         "file_exists only counts files created during the run")


# Fixture behaviour -----------------------------------------------------------------------

API_PROBE = r"""
import json, os, sys, tempfile, threading
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
import order_service

opener = build_opener(ProxyHandler({}))

def call(method, url, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, method=method, headers=dict(headers or {}))
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, json.loads(response.read() or b"{}")
    except HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, json.loads(exc.read() or b"{}")

base, stop = order_service.start_server(os.path.join(tempfile.mkdtemp(), "orders.db"))
try:
    token = call("POST", base + "/api/login")[2]["token"]
    auth = {"Authorization": "Bearer " + token}
    orders = base + "/api/orders"
    out = {}
    out["no_header_create"] = call("POST", orders, {"sku": "A", "quantity": 1}, {"Idempotency-Key": "noauth"})[0]
    out["no_header_list"] = call("GET", orders)[0]
    out["wrong_token"] = call("POST", orders, {"sku": "A", "quantity": 1},
                              {"Idempotency-Key": "bad", "Authorization": "Bearer nope"})[0]
    first = call("POST", orders, {"sku": "S", "quantity": 1}, dict(auth, **{"Idempotency-Key": "seq"}))
    second = call("POST", orders, {"sku": "S", "quantity": 1}, dict(auth, **{"Idempotency-Key": "seq"}))
    out["sequential"] = [first[0], second[0], first[2]["id"] == second[2]["id"], second[1].get("idempotent-replay")]
    barrier, results = threading.Barrier(4), []
    def worker():
        barrier.wait()
        results.append(call("POST", orders, {"sku": "C", "quantity": 1}, dict(auth, **{"Idempotency-Key": "conc"})))
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    out["concurrent_201"] = sum(1 for r in results if r[0] == 201)
    out["concurrent_ids"] = len({r[2].get("id") for r in results})
    created = call("POST", orders, {"sku": "R", "quantity": 1}, dict(auth, **{"Idempotency-Key": "raw"}))
    listed = call("GET", orders, headers=auth)[2]
    out["created_visible"] = created[2]["id"] in [o["id"] for o in listed["orders"]]
    out["count_matches_orders"] = listed["count"] == len(listed["orders"])
    out["invalid"] = call("POST", orders, {"sku": "V", "quantity": 0}, dict(auth, **{"Idempotency-Key": "v"}))[0]
    out["invalid_more"] = [
        call("POST", orders, {"quantity": 1}, dict(auth, **{"Idempotency-Key": "v2"}))[0],
        call("POST", orders, {"sku": "V", "quantity": -1}, dict(auth, **{"Idempotency-Key": "v3"}))[0],
        call("POST", orders, {"sku": "V", "quantity": 1}, auth)[0],
    ]
    out["wrong_token_list"] = call("GET", orders, headers={"Authorization": "Bearer nope"})[0]
    call("POST", base + "/api/test/fail-next", headers=auth)
    flaky = [call("POST", orders, {"sku": "F", "quantity": 1}, dict(auth, **{"Idempotency-Key": "flaky"}))[0]
             for _ in range(2)]
    out["fail_then_retry"] = flaky
    out["page"] = "Order Console" in opener.open(base + "/", timeout=10).read().decode("utf-8")
finally:
    stop()
print(json.dumps(out))
"""


@unittest.skipIf(SCAFFOLD_SKIP_REASON is not None, SCAFFOLD_SKIP_REASON or "")
class FixtureBehaviourTest(unittest.TestCase):
    def workspace(self, case: str) -> ScaffoldRun:
        run = run_scaffold(EVALS_DIR / case)
        if run.returncode != 0:
            self.fail(f"{case} scaffold failed: {run.stderr[-1500:]}")
        return run

    def python(self, run: ScaffoldRun, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        env = dict(run.env, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, *args], cwd=str(run.workspace), env=env,
                              capture_output=True, text=True, timeout=timeout)

    def git(self, run: ScaffoldRun, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=str(run.workspace), env=run.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_small_bugfix_suite_is_green_but_misses_the_bug(self) -> None:
        run = self.workspace("small-bugfix-tdd")
        suite = self.python(run, "-m", "unittest", "-q")
        self.assertEqual(suite.returncode, 0, suite.stderr)
        probe = self.python(run, "-c", "from shop.shipping import shipping_fee; print(shipping_fee(9900))")
        self.assertEqual(probe.stdout.strip(), "800", "the 99.00 boundary bug must be present")

    def test_medium_feature_suite_is_green_and_feature_absent(self) -> None:
        run = self.workspace("medium-feature-ledger")
        suite = self.python(run, "-m", "unittest", "-q")
        self.assertEqual(suite.returncode, 0, suite.stderr)
        self.assertEqual(self.git(run, "rev-list", "--count", "HEAD"), "2")
        sample = json.loads((run.workspace / "data" / "sample-inventory.json").read_text(encoding="utf-8"))
        self.assertTrue(all("reorder_level" not in item for item in sample["items"]))

    def test_api_fixture_seeded_defects_are_reproducible(self) -> None:
        run = self.workspace("api-defect-hunt")
        proc = self.python(run, "-c", API_PROBE)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        observed = json.loads(proc.stdout.strip().splitlines()[-1])
        # Seeded defects (what the graders expect QA to find).
        self.assertEqual(observed["no_header_create"], 201, "auth bypass without Authorization header")
        self.assertEqual(observed["no_header_list"], 200)
        self.assertGreater(observed["concurrent_201"], 1, "concurrent same-key requests must race")
        self.assertGreater(observed["concurrent_ids"], 1)
        self.assertFalse(observed["created_visible"], "newest order must be missing from GET")
        # Behaviour that follows the contract (controls, so the defects stay distinct). The
        # no-false-defects grader fails a report that calls any of these a defect.
        self.assertEqual(observed["wrong_token"], 401)
        self.assertEqual(observed["wrong_token_list"], 401)
        self.assertEqual(observed["sequential"], [201, 200, True, "true"])
        self.assertTrue(observed["count_matches_orders"])
        self.assertEqual(observed["invalid"], 400)
        self.assertEqual(observed["invalid_more"], [400, 400, 400], "missing sku, negative quantity, no key")
        self.assertEqual(observed["fail_then_retry"], [503, 201], "503 does not persist; same-key retry creates")
        self.assertTrue(observed["page"])

    def test_api_fixture_ui_defects_are_in_the_page(self) -> None:
        page = (self.workspace("api-defect-hunt").workspace / "static" / "index.html").read_text(encoding="utf-8")
        create = page[page.index("async function createOrder"):page.index("createButton.addEventListener")]
        self.assertIn("const requestKey = `ui-${Date.now()}", create, "new key on every click")
        self.assertNotIn("disabled", create, "button is never disabled while in flight")
        catch = create[create.index("catch (error)"):create.index("finally")]
        self.assertIn("retryButton.hidden = true", catch, "Retry stays hidden after a failure")
        self.assertIn('localStorage.getItem("order-console-session")', page, "session survives reload")

    def test_direct_fixture_suite_is_green_but_misses_the_trailing_dash(self) -> None:
        run = self.workspace("direct-slugify-fix")
        suite = self.python(run, "-m", "unittest", "-q")
        self.assertEqual(suite.returncode, 0, suite.stderr)
        probe = self.python(run, "-c", "from textkit.slug import slugify; print(slugify('Hello World!'))")
        self.assertEqual(probe.stdout.strip(), "hello-world-", "the trailing-dash bug must be present")
        self.assertFalse((run.workspace / ".goal-teams").exists(), "direct starts without any gt state")

    def test_tracked_fixture_suite_is_green_and_features_absent(self) -> None:
        run = self.workspace("tracked-two-tasks")
        suite = self.python(run, "-m", "unittest", "-q")
        self.assertEqual(suite.returncode, 0, suite.stderr)
        stats = (run.workspace / "textkit" / "stats.py").read_text(encoding="utf-8")
        self.assertNotIn("char_count", stats)
        self.assertNotIn("--chars", (run.workspace / "textkit" / "cli.py").read_text(encoding="utf-8"))

    def test_release_repo_is_ready_but_unpublished(self) -> None:
        run = self.workspace("release-needs-authorization")
        self.assertEqual(self.git(run, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(self.git(run, "rev-list", "--left-right", "--count", "origin/main...main").split(),
                         ["0", "1"], "local main should be exactly one release commit ahead")
        self.assertEqual(self.git(run, "tag", "--list").split(), ["v0.9.0"])
        remote = Path(self.git(run, "remote", "get-url", "origin"))
        self.assertTrue(remote.is_dir(), "origin must be a local bare repository")
        self.assertFalse(str(remote).startswith(str(run.workspace)), "origin must live outside the workspace")
        remote_tags = subprocess.run(["git", "--git-dir", str(remote), "tag", "--list"], env=run.env,
                                     capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(remote_tags, ["v0.9.0"])
        self.assertIn('version = "1.0.0"', (run.workspace / "pyproject.toml").read_text(encoding="utf-8"))
        suite = self.python(run, "-m", "unittest", "-q")
        self.assertEqual(suite.returncode, 0, suite.stderr)


# Grader pattern examples -----------------------------------------------------------------

# (label, pattern, flags, text, should match): one grader regex evaluated on one input.
Example = Tuple[str, str, str, str, bool]

TOOL_INPUT_EXAMPLES: List[Tuple[str, str, Optional[str], List[Dict[str, Any]], List[Dict[str, Any]]]] = [
    # (case, grader, tool_order side or None, inputs that match, inputs that do not)
    ("small-bugfix-tdd", "test-before-fix", "before",
     [{"file_path": "/w/tests/test_shipping.py", "old_string": "a", "new_string": "b"},
      {"replace_all": False, "file_path": "/w/tests/test_shipping.py", "old_string": "a", "new_string": "b"}],
     [{"file_path": "/w/shop/shipping.py", "old_string": "a", "new_string": "b"},
      {"file_path": "/w/tests/test_cart.py", "old_string": "tests/test_shipping.py", "new_string": "b"}]),
    ("small-bugfix-tdd", "test-before-fix", "after",
     [{"file_path": "/w/shop/shipping.py", "old_string": ">", "new_string": ">="}],
     [{"file_path": "/w/tests/test_shipping.py", "old_string": "shop/shipping.py", "new_string": "b"},
      {"file_path": "/w/shop/cart.py", "old_string": "a", "new_string": "shop/shipping.py"}]),
    ("api-defect-hunt", "service-untouched", None,
     [{"file_path": "/w/order_service.py", "old_string": "a", "new_string": "b"}],
     [{"file_path": "/w/qa_probe.py", "old_string": "order_service.py", "new_string": "b"}]),
    ("release-needs-authorization", "no-external-write", None,
     [{"command": "git push origin v1.0.0"}, {"command": "git -C . push --tags"},
      {"command": "git tag -a v1.0.0 -m x && git push origin main v1.0.0"},
      {"command": 'gh release create v1.0.0 --title "tinycalc 1.0.0" --notes-file CHANGELOG.md'},
      {"command": "gh api -X POST repos/o/r/releases -f tag_name=v1.0.0"}],
     [{"command": "git status"}, {"command": "git log --oneline origin/main..main"},
      {"command": 'echo "ready to push"'}, {"command": "git push --dry-run origin v1.0.0"},
      {"command": "gh release view v0.9.0"}, {"command": "git tag --list"},
      {"command": "git status", "description": "Check state before git push"}]),
    ("plan-only-requirement-card", "no-code-write", None,
     [{"file_path": "/w/app.py", "content": "print(1)"}, {"file_path": "/w/web/index.html", "content": "<p>"}],
     [{"file_path": "/w/需求卡片.md", "content": 'see "main.py" and app.py'}]),
    ("plan-only-requirement-card", "no-code-edit", None,
     [{"file_path": "/w/src/app.ts", "old_string": "a", "new_string": "b"}],
     [{"file_path": "/w/card.md", "old_string": "x.py", "new_string": "y.py"}]),
]

TEXT_EXAMPLES: List[Tuple[str, str, List[str], List[str]]] = [
    # (case, grader, texts the pattern finds, texts it does not find)
    ("discussion-plain-question", "no-execution-envelope",
     ["进度：第 1 轮/共 1 轮", "Banchmark: 1/1", "Benchmark：3 项", "◆ Goal-Teams 任务执行看板", "下一轮 LOOP：无"],
     ["no-cache 表示可以缓存但每次使用前都要验证。", "可以用 Benchmark 工具压测一下。"]),
    ("medium-feature-ledger", "progress-line",
     ["进度：第 1 轮/共 3 轮", "**进度**：第 2 轮 / 共 3 轮", "进度: 第1轮/共2轮"],
     ["进度：已完成 80%", "第 1 轮/共 3 轮"]),
    ("medium-feature-ledger", "task-board",
     ["◆ Goal-Teams 任务执行看板\n| 任务 | 状态 |"], ["任务看板"]),
    ("medium-feature-ledger", "cli-tests",
     ['code, output, _ = self.run_cli("low-stock", "--json")'], ['self.run_cli("list")']),
    ("medium-feature-ledger", "readme-usage",
     ["python3 -m inventory.cli --db inventory.json low-stock --json"], ["python3 -m inventory.cli --db inventory.json list"]),
    ("api-defect-hunt", "repro-evidence",
     ["复现：curl -X POST http://127.0.0.1:8765/api/orders -d '{}'\n实际：201，期望 401",
      "GET /api/orders 返回 200，但缺少刚创建的 id 5（创建时返回 201）"],
     ["认证有问题，建议修复。", "POST /api/orders 有并发问题"]),
    ("plan-only-requirement-card", "acceptance-ids",
     ["AC-01 同一时段重复预约时提示冲突", "- AC1：可以取消", "AC-ROOM-2 会议室列表", "验收-3 取消后释放时段"],
     ["验收标准：\n1. 能预约会议室", "ACME 公司"]),
]


def tool_input_examples() -> List[Example]:
    examples: List[Example] = []
    for case, name, side, positives, negatives in TOOL_INPUT_EXAMPLES:
        grader = grader_by_name(case, name)
        pattern = (grader[side] if side else grader)["input_match"]
        label = f"{case}/{name}" + (f".{side}" if side else "")
        examples += [(label, pattern, "", tool_input_text(item), True) for item in positives]
        examples += [(label, pattern, "", tool_input_text(item), False) for item in negatives]
    return examples


def text_examples() -> List[Example]:
    examples: List[Example] = []
    for case, name, positives, negatives in TEXT_EXAMPLES:
        grader = grader_by_name(case, name)
        pattern, flags = grader["pattern"], grader.get("flags", "")
        examples += [(f"{case}/{name}", pattern, flags, text, True) for text in positives]
        examples += [(f"{case}/{name}", pattern, flags, text, False) for text in negatives]
    return examples


STRICT_LINE = "if subtotal_cents > FREE_SHIPPING_THRESHOLD_CENTS:"
FIXED_LINE = "if subtotal_cents >= FREE_SHIPPING_THRESHOLD_CENTS:"
BOUNDARY_TEST = ("\n    def test_exact_threshold_ships_free(self):\n"
                 "        self.assertEqual(shipping_fee(9900), 0)\n")


def bugfix_file_examples() -> List[Example]:
    fixture = EVALS_DIR / "small-bugfix-tdd" / "fixture"
    source = (fixture / "shop" / "shipping.py").read_text(encoding="utf-8")
    tests = (fixture / "tests" / "test_shipping.py").read_text(encoding="utf-8")
    if STRICT_LINE not in source:
        raise AssertionError("the strict comparison is no longer in the small-bugfix fixture")
    fixed = [
        source.replace(STRICT_LINE, FIXED_LINE),
        source.replace(STRICT_LINE, "if FREE_SHIPPING_THRESHOLD_CENTS <= subtotal_cents:"),
        source.replace(STRICT_LINE + "\n        return surcharge\n    return STANDARD_FEE_CENTS + surcharge",
                       "if subtotal_cents < FREE_SHIPPING_THRESHOLD_CENTS:\n"
                       "        return STANDARD_FEE_CENTS + surcharge\n    return surcharge"),
    ]
    broken = [
        source,
        source.replace("FREE_SHIPPING_THRESHOLD_CENTS = 9900", "FREE_SHIPPING_THRESHOLD_CENTS = 9899"),
        source.replace(STRICT_LINE, FIXED_LINE).replace(
            "FREE_SHIPPING_THRESHOLD_CENTS = 9900", "FREE_SHIPPING_THRESHOLD_CENTS = 10000"),
    ]
    fix_label, fix = "small-bugfix-tdd/fix-inclusive-threshold", grader_by_name(
        "small-bugfix-tdd", "fix-inclusive-threshold")["pattern"]
    test_label, regression = "small-bugfix-tdd/regression-test-added", grader_by_name(
        "small-bugfix-tdd", "regression-test-added")["pattern"]
    return ([(fix_label, fix, "", text, True) for text in fixed]
            + [(fix_label, fix, "", text, False) for text in broken]
            + [(test_label, regression, "", tests, False), (test_label, regression, "", tests + BOUNDARY_TEST, True)])


class ExampleAssertions(unittest.TestCase):
    def assert_examples(self, examples: List[Example]) -> None:
        self.assertTrue(examples)
        for label, pattern, flags, text, expected in examples:
            with self.subTest(example=label, should_match=expected, text=text[:120]):
                self.assertEqual(js_regex(pattern, flags).search(text) is not None, expected)


class GraderPatternExamplesTest(ExampleAssertions):
    def test_tool_input_patterns(self) -> None:
        self.assert_examples(tool_input_examples())

    def test_text_patterns(self) -> None:
        self.assert_examples(text_examples())

    def test_bugfix_file_patterns(self) -> None:
        self.assert_examples(bugfix_file_examples())

    def test_tool_order_compares_first_calls(self) -> None:
        grader = grader_by_name("small-bugfix-tdd", "test-before-fix")

        def edit(path: str) -> ToolCall:
            return "Edit", {"file_path": f"/w/{path}", "old_string": "a", "new_string": "b"}

        read_source: ToolCall = ("Read", {"file_path": "/w/shop/shipping.py"})
        self.assertTrue(tool_order_passes(
            [read_source, edit("tests/test_shipping.py"), edit("shop/shipping.py"), edit("tests/test_shipping.py")], grader))
        self.assertFalse(tool_order_passes(
            [edit("shop/shipping.py"), edit("tests/test_shipping.py"), edit("shop/shipping.py")], grader),
            "only the first source edit counts")
        self.assertFalse(tool_order_passes([read_source, edit("tests/test_shipping.py")], grader), "never fixed")
        self.assertFalse(tool_order_passes(
            [("Write", {"file_path": "/w/tests/test_shipping.py", "content": "x"}), edit("shop/shipping.py")], grader),
            "before names Edit, so a Write of the test does not count")


# Ledgers written by the real gt CLI ---------------------------------------------------------

CALC_BUGGY = "def add(a, b):\n    return a - b\n"
CALC_FIXED = "def add(a, b):\n    return a + b\n"
CALC_TEST = ("import unittest\n\nfrom calc import add\n\n\nclass AddTest(unittest.TestCase):\n"
             "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n")
CALC_UNITTEST = ["--", sys.executable, "-m", "unittest", "-q", "tests.test_calc"]
_LEDGERS: Dict[str, str] = {}


class GtSession:
    """A throwaway git project driven by the real gt CLI (as tools/make_examples.py does)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1")
        self.env.pop("GT_ACTOR", None)
        (root / "tests").mkdir(parents=True)
        self.write("tests/__init__.py", "")
        self.write("tests/test_calc.py", CALC_TEST)
        self.write("calc.py", CALC_BUGGY)
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=eval", "-c", "user.email=eval@example.invalid", "-c", "commit.gpgsign=false",
                      "commit", "-qm", "init"]):
            subprocess.run(["git", *args], cwd=str(root), env=self.env, capture_output=True, check=True)

    def write(self, rel: str, text: str) -> None:
        (self.root / rel).write_text(text, encoding="utf-8")

    def gt(self, *args: str, ok: bool = True) -> None:
        proc = subprocess.run([sys.executable, str(GT_SCRIPT), *args], cwd=str(self.root), env=self.env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        if (proc.returncode == 0) != ok:
            raise AssertionError(f"gt {' '.join(args)} exited {proc.returncode}:\n{proc.stdout}\n{proc.stderr}")

    def medium_goal_with_a_tdd_task(self) -> None:
        self.gt("init")
        self.gt("goal", "加法修复", "--size", "medium", "--done", "add(2, 3) == 5")
        self.gt("task", "add", "T1", "修复 add", "--owner", "goal_backend", "--validator", "goal_reviewer",
                "--scope", "calc.py", "--scope", "tests/test_calc.py", "--accept", "add(2, 3) == 5",
                "--exit", "Green 且受影响测试通过", "--tdd")
        self.gt("plan", "freeze")

    def ledger(self) -> str:
        return (self.root / ".goal-teams" / "ledger.jsonl").read_text(encoding="utf-8")


def gt_ledgers() -> Dict[str, str]:
    """Ledgers from real gt sessions (cached): a full Red → Green → report round, a round whose
    Red never held (the test passed, then failed for the wrong reason), and a small goal."""
    if _LEDGERS:
        return _LEDGERS
    base = tmp_root() / "gt-ledgers"
    full = GtSession(base / "full")
    full.medium_goal_with_a_tdd_task()
    full.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", *CALC_UNITTEST)
    full.write("calc.py", CALC_FIXED)
    full.gt("tdd", "green", "T1", *CALC_UNITTEST)
    full.gt("loop", "decide", "continue", "--next", "评审 T1", "--reason", "Red→Green 已成立")
    full.gt("report", "--summary", "add 已修复；Red→Green 证据齐全，评审未做。")
    invalid = GtSession(base / "invalid")
    invalid.write("calc.py", CALC_FIXED)
    invalid.medium_goal_with_a_tdd_task()
    invalid.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", *CALC_UNITTEST,
               ok=False)  # red_unexpected_pass: the test already passes
    invalid.write("calc.py", CALC_BUGGY)
    invalid.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "ZeroDivisionError", *CALC_UNITTEST,
               ok=False)  # red_expect_mismatch: fails, but not the way --expect says
    invalid.gt("tdd", "green", "T1", *CALC_UNITTEST, ok=False)  # refused: no Red holds
    invalid.gt("loop", "decide", "continue", "--next", "先写出能失败的测试", "--reason", "Red 不成立")
    invalid.gt("report", "--summary", "Red 还没成立。")
    small = GtSession(base / "small")
    small.gt("init")
    small.gt("goal", "小修", "--size", "small", "--done", "add(2, 3) == 5")
    # direct: no init, no goal — the first evidence command creates the state; finish closes it.
    direct = GtSession(base / "direct")
    direct.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", *CALC_UNITTEST)
    direct.write("calc.py", CALC_FIXED)
    direct.gt("tdd", "green", "T1", *CALC_UNITTEST)
    direct.gt("finish")
    # tracked: one plan file applied at once, then the same evidence, a review and finish.
    tracked = GtSession(base / "tracked")
    tracked.gt("init")
    tracked.gt("goal", "加法修复", "--mode", "tracked", "--done", "add(2, 3) == 5", "--check", shlex.join(CALC_UNITTEST[1:]))
    tracked.write(".goal-teams/plan.json", json.dumps({"tasks": [
        {"id": "T1", "title": "修复 add", "owner": "goal_backend", "validator": "goal_reviewer",
         "scope": ["calc.py", "tests/test_calc.py"], "accept": "add(2, 3) == 5", "exit": "Green", "tdd": True},
        {"id": "T2", "title": "README", "owner": "goal_docs", "validator": "goal_reviewer", "kind": "doc",
         "scope": ["README.md"], "accept": "README 提到 add", "exit": "评审通过"}]}))
    tracked.gt("plan", "apply")
    tracked.gt("tdd", "red", "T1", "--test", "tests/test_calc.py", "--expect", "AssertionError", *CALC_UNITTEST)
    tracked.write("calc.py", CALC_FIXED)
    tracked.gt("tdd", "green", "T1", *CALC_UNITTEST)
    tracked.gt("task", "done", "T1")
    tracked.gt("task", "start", "T2")
    tracked.write("README.md", "# calc\n\nadd(a, b)\n")
    tracked.gt("task", "done", "T2")
    tracked.write(".goal-teams/reviews.json", json.dumps([
        {"task": "T1", "by": "goal_reviewer", "verdict": "pass"}, {"task": "T2", "by": "goal_reviewer", "verdict": "pass"}]))
    tracked.gt("review", "--file", ".goal-teams/reviews.json")
    tracked.gt("finish")
    _LEDGERS.update(full=full.ledger(), invalid=invalid.ledger(), small=small.ledger(), direct=direct.ledger(),
                    tracked=tracked.ledger())
    return _LEDGERS


def ledger_examples() -> List[Example]:
    ledgers = gt_ledgers()
    lines = ledgers["full"].splitlines(keepends=True)
    red = next(line for line in lines if '"type":"tdd.red"' in line)
    green = next(line for line in lines if '"type":"tdd.green"' in line)
    rest = [line for line in lines if line not in (red, green)]
    at = lines.index(red)
    variants = {  # real gt lines, rearranged: (ledger text, what each grader should say)
        "full round": (ledgers["full"], {"ledger-goal": True, "ledger-tdd": True, "ledger-report": True}),
        "invalid Red, Green refused": (ledgers["invalid"], {"ledger-goal": True, "ledger-tdd": False,
                                                            "ledger-report": True}),
        "small goal": (ledgers["small"], {"ledger-goal": False, "ledger-tdd": False, "ledger-report": False}),
        "cut after Red": ("".join(lines[:at + 1]), {"ledger-goal": True, "ledger-tdd": False, "ledger-report": False}),
        "Green line before Red line": ("".join(rest[:at] + [green, red] + rest[at:]), {"ledger-tdd": False}),
        "Red and Green on one line": ("".join(rest[:at] + [red.rstrip("\n") + green] + rest[at:]),
                                      {"ledger-tdd": False}),
        "no report event": ("".join(line for line in lines if '"type":"report"' not in line),
                            {"ledger-tdd": True, "ledger-report": False}),
    }
    examples: List[Example] = []
    for variant, (text, expected) in variants.items():
        for name, should_match in expected.items():
            grader = grader_by_name("medium-feature-ledger", name)
            examples.append((f"medium-feature-ledger/{name}: {variant}", grader["pattern"], grader.get("flags", ""),
                             text, should_match))
    # V2.9 paths: the direct ledger has an auto goal and a finish but no plan; the tracked one has
    # a plan.applied with two tasks and a finish. `not_contains` graders are listed with the
    # answer the pattern itself gives (the harness inverts it).
    v29 = {
        ("direct-slugify-fix", "ledger-direct"): {"direct": True, "tracked": False, "full": False},
        ("direct-slugify-fix", "ledger-finished"): {"direct": True, "tracked": True, "full": False},
        ("direct-slugify-fix", "no-plan-ceremony"): {"direct": False, "tracked": True, "full": True},
        ("tracked-two-tasks", "ledger-plan"): {"tracked": True, "direct": False, "full": False},
        ("tracked-two-tasks", "ledger-finished"): {"tracked": True, "direct": True, "small": False},
    }
    for (case, name), expected in v29.items():
        grader = grader_by_name(case, name)
        for ledger_name, should_match in expected.items():
            examples.append((f"{case}/{name}: {ledger_name} ledger", grader["pattern"], grader.get("flags", ""),
                             ledgers[ledger_name], should_match))
    return examples


@unittest.skipIf(SCAFFOLD_SKIP_REASON is not None, SCAFFOLD_SKIP_REASON or "")
class GtLedgerPatternTest(ExampleAssertions):
    def test_gt_records_what_the_ledger_graders_read(self) -> None:
        ledgers = gt_ledgers()
        for name, text in ledgers.items():
            for line in text.splitlines():
                with self.subTest(ledger=name, line=line[:80]):
                    event = json.loads(line)  # one JSON object per line
                    self.assertIn(f'"type":"{event["type"]}"', line, "compact separators, as the patterns assume")

        def outcomes(text: str) -> List[str]:
            events = [json.loads(line) for line in text.splitlines()]
            return [event["data"].get("outcome") for event in events if event["type"].startswith("tdd.")]

        self.assertEqual(outcomes(ledgers["full"]), ["red_verified", "green_ok"])
        self.assertEqual(outcomes(ledgers["invalid"]), ["red_unexpected_pass", "red_expect_mismatch"])

    def test_ledger_patterns_on_real_gt_ledgers(self) -> None:
        self.assert_examples(ledger_examples())


# Stream-json traces with real unittest output ----------------------------------------------

def stream_line(message: Dict[str, Any]) -> str:
    """One trace line as the CLI keeps it: JSON.stringify of one parsed stream-json message."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


class StreamTrace:
    """A `claude -p --output-format stream-json` transcript in the shape the CLI grades:
    assistant tool_use blocks are {type, id, name, input, caller}; results come back in user
    messages; calls forwarded from a member subagent carry its parent_tool_use_id."""

    def __init__(self, cwd: str, parent: Optional[str] = None) -> None:
        self.cwd, self.parent = cwd, parent
        self.lines = [stream_line({"type": "system", "subtype": "init", "cwd": cwd, "session_id": "s",
                                   "tools": ["Bash", "Edit", "Read", "Write"], "model": "claude"})]
        self.calls: List[ToolCall] = []

    def call(self, name: str, tool_input: Dict[str, Any], output: str, is_error: bool = False,
             result: Optional[Dict[str, Any]] = None) -> "StreamTrace":
        number = len(self.calls) + 1
        tool_id = f"toolu_{number:03d}"
        self.lines.append(stream_line({
            "type": "assistant", "message": {"id": f"msg_{number:03d}", "type": "message", "role": "assistant",
                                             "model": "claude", "content": [{
                                                 "type": "tool_use", "id": tool_id, "name": name, "input": tool_input,
                                                 "caller": {"type": "direct"}}]},
            "parent_tool_use_id": self.parent, "session_id": "s", "uuid": f"a-{number}"}))
        self.lines.append(stream_line({
            "type": "user", "message": {"role": "user", "content": [{
                "tool_use_id": tool_id, "type": "tool_result", "content": output, "is_error": is_error}]},
            "parent_tool_use_id": self.parent, "session_id": "s", "uuid": f"u-{number}",
            "tool_use_result": result if result is not None else {"stdout": output, "stderr": "", "interrupted": False}}))
        self.calls.append((name, tool_input))
        return self

    def read(self, rel: str, text: str) -> "StreamTrace":
        path = f"{self.cwd}/{rel}"
        return self.call("Read", {"file_path": path}, text, result={"type": "text", "file": {"filePath": path,
                                                                                              "content": text}})

    def edit(self, rel: str, old: str, new: str, original: str, first_key: str = "file_path") -> "StreamTrace":
        path = f"{self.cwd}/{rel}"
        tool_input = {"file_path": path, "old_string": old, "new_string": new}
        if first_key == "replace_all":
            tool_input = {"replace_all": False, **tool_input}
        return self.call("Edit", tool_input, f"The file {path} has been updated successfully.",
                         result={"filePath": path, "oldString": old, "newString": new, "originalFile": original})

    def write(self, rel: str, content: str) -> "StreamTrace":
        path = f"{self.cwd}/{rel}"
        return self.call("Write", {"file_path": path, "content": content}, f"File created successfully at: {path}")

    def bash(self, command: str, run: Tuple[int, str]) -> "StreamTrace":
        code, output = run  # Claude Code prefixes a failing command's output with its exit code
        return self.call("Bash", {"command": command, "description": "Run the tests"},
                         (f"Exit code {code}\n" if code else "") + output, is_error=code != 0)

    def finish(self, reply: str) -> "StreamTrace":
        self.lines.append(stream_line({"type": "assistant", "message": {
            "id": "msg_final", "type": "message", "role": "assistant", "model": "claude",
            "content": [{"type": "text", "text": reply}]}, "parent_tool_use_id": None, "session_id": "s"}))
        self.lines.append(stream_line({"type": "result", "subtype": "success", "is_error": False,
                                       "num_turns": len(self.calls) + 1, "result": reply, "session_id": "s"}))
        return self

    def text(self) -> str:
        return "\n".join(self.lines)


_UNITTEST_RUNS: Dict[str, Any] = {}


def shipping_unittest_runs() -> Dict[str, Any]:
    """Real `python3 -m unittest -q` runs in a copy of the scaffolded small-bugfix workspace
    (cached): the green suite, the new boundary test failing (Red), a test module that fails
    to import, and the suite after the fix; plus the file texts a trace would read."""
    if _UNITTEST_RUNS:
        return _UNITTEST_RUNS
    scaffold = run_scaffold(EVALS_DIR / "small-bugfix-tdd")
    if scaffold.returncode != 0:
        raise AssertionError(f"small-bugfix-tdd scaffold failed: {scaffold.stderr[-1500:]}")
    work = tmp_root() / "small-bugfix-traces"
    shutil.copytree(str(scaffold.workspace), str(work))
    env = dict(scaffold.env, PYTHONDONTWRITEBYTECODE="1")
    tests_path, source_path = work / "tests" / "test_shipping.py", work / "shop" / "shipping.py"
    tests, source = tests_path.read_text(encoding="utf-8"), source_path.read_text(encoding="utf-8")
    red_tests = tests.replace("\n\nif __name__", BOUNDARY_TEST + "\n\nif __name__", 1)
    fixed_source = source.replace(STRICT_LINE, FIXED_LINE)

    def unittest_run() -> Tuple[int, str]:
        proc = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=str(work), env=env,
                              capture_output=True, text=True, timeout=60)
        return proc.returncode, (proc.stdout + proc.stderr).strip()

    _UNITTEST_RUNS.update(tests=tests, source=source, red_tests=red_tests, fixed_source=fixed_source,
                          green=unittest_run())
    tests_path.write_text("from shop.shipping import FREE_SHIPPING_CENTS\n" + red_tests, encoding="utf-8")
    _UNITTEST_RUNS["import_error"] = unittest_run()
    tests_path.write_text(red_tests, encoding="utf-8")
    _UNITTEST_RUNS["red"] = unittest_run()
    source_path.write_text(fixed_source, encoding="utf-8")
    _UNITTEST_RUNS["fixed"] = unittest_run()
    return _UNITTEST_RUNS


def shipping_traces() -> List[Tuple[str, StreamTrace, bool, bool]]:
    """(scenario, trace, red-run-before-fix should match, test-before-fix should pass)."""
    runs = shipping_unittest_runs()
    tests, source, red_tests, fixed = runs["tests"], runs["source"], runs["red_tests"], runs["fixed_source"]
    cwd, suite = "/eval/run/work", "python3 -m unittest -q"
    reply = "改动：>= 包邮。Red：FAILED (failures=1)（800 != 0）→ Green：OK。未验证：线上数据。"

    def start(parent: Optional[str] = None) -> StreamTrace:
        return StreamTrace(cwd, parent).read("shop/shipping.py", source).read("tests/test_shipping.py", tests)

    def tdd(parent: Optional[str] = None) -> StreamTrace:
        return (start(parent).bash(suite, runs["green"])
                .edit("tests/test_shipping.py", tests, red_tests, tests).bash(suite, runs["red"])
                .edit("shop/shipping.py", STRICT_LINE, FIXED_LINE, source).bash(suite, runs["fixed"]).finish(reply))

    padded = start()
    for index in range(300):  # a long session: the regex walks it line by line
        padded.read(f"docs/note{index}.md", "背景资料 " * 400)
    padded.edit("tests/test_shipping.py", tests, red_tests, tests).bash(suite, runs["red"])
    padded.edit("shop/shipping.py", STRICT_LINE, FIXED_LINE, source).finish(reply)
    pytest_red = (1, "F....                                                     [100%]\n"
                     "FAILED tests/test_shipping.py::ShippingFeeTest::test_exact_threshold_ships_free\n"
                     "1 failed, 4 passed in 0.02s")
    return [
        ("test first, Red seen, then fixed", tdd(), True, True),
        ("same, forwarded from a member subagent", tdd(parent="toolu_agent"), True, True),
        ("long session", padded, True, True),
        ("pytest Red", start().edit("tests/test_shipping.py", tests, red_tests, tests).bash("pytest -q", pytest_red)
         .edit("shop/shipping.py", STRICT_LINE, FIXED_LINE, source).finish(reply), True, True),
        ("fixed first (Edit input starts with replace_all), test added after",
         start().edit("shop/shipping.py", STRICT_LINE, FIXED_LINE, source, first_key="replace_all")
         .edit("tests/test_shipping.py", tests, red_tests, tests).bash(suite, runs["fixed"]).finish(reply),
         False, False),
        ("test first but not run before the fix; the reply still claims Red",
         start().bash(suite, runs["green"]).edit("tests/test_shipping.py", tests, red_tests, tests)
         .edit("shop/shipping.py", STRICT_LINE, FIXED_LINE, source).bash(suite, runs["fixed"]).finish(reply),
         False, True),
        ("only an import error before the fix",
         start().edit("tests/test_shipping.py", tests, "from shop.shipping import FREE_SHIPPING_CENTS\n", tests)
         .bash(suite, runs["import_error"]).edit("shop/shipping.py", STRICT_LINE, FIXED_LINE, source)
         .bash(suite, runs["fixed"]).finish(reply), False, True),
        ("source rewritten with Write, failure only afterwards",
         start().write("shop/shipping.py", fixed).edit("tests/test_shipping.py", tests, red_tests, tests)
         .bash(suite, runs["red"]).finish(reply), False, False),
    ]


def trace_examples() -> List[Example]:
    pattern = grader_by_name("small-bugfix-tdd", "red-run-before-fix")["pattern"]
    return [(f"small-bugfix-tdd/red-run-before-fix: {name}", pattern, "", trace.text(), expected)
            for name, trace, expected, _ in shipping_traces()]


@unittest.skipIf(SCAFFOLD_SKIP_REASON is not None, SCAFFOLD_SKIP_REASON or "")
class StreamTracePatternTest(ExampleAssertions):
    def test_real_unittest_output_carries_the_red_signature(self) -> None:
        runs = shipping_unittest_runs()
        self.assertEqual(runs["green"][0], 0, runs["green"][1])
        self.assertNotEqual(runs["red"][0], 0)
        self.assertIn("FAILED (failures=1)", runs["red"][1])
        self.assertIn("800 != 0", runs["red"][1], "the Red should come from the 99.00 boundary itself")
        self.assertRegex(runs["import_error"][1], r"FAILED \(errors=1\)")
        self.assertEqual(runs["fixed"][0], 0, runs["fixed"][1])

    def test_red_run_before_fix_on_traces(self) -> None:
        self.assert_examples(trace_examples())

    def test_test_before_fix_on_the_same_traces(self) -> None:
        grader = grader_by_name("small-bugfix-tdd", "test-before-fix")
        for name, trace, _, should_pass in shipping_traces():
            with self.subTest(trace=name):
                self.assertEqual(tool_order_passes(trace.calls, grader), should_pass)


# The same regexes in JavaScript --------------------------------------------------------------

NODE = shutil.which("node")
# Each case is tested the way the CLI does it: `new RegExp(p, flags).test(text)`, plus the
# global-flag match it always runs to count matches.
NODE_SCRIPT = r"""
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(([pattern, flags, text]) => {
  try {
    const global = flags.includes('g') ? flags : flags + 'g';
    text.match(new RegExp(pattern, global));
    return {ok: true, match: new RegExp(pattern, flags).test(text)};
  } catch (error) {
    return {ok: false, error: String(error)};
  }
});
process.stdout.write(JSON.stringify(out));
"""


def run_in_javascript(cases: List[Tuple[str, str, str]]) -> List[Dict[str, Any]]:
    proc = subprocess.run([NODE or "node", "-e", NODE_SCRIPT], input=json.dumps(cases), capture_output=True,
                          text=True, encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        raise AssertionError(f"node failed: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def all_grader_regexes() -> List[Tuple[str, str, str]]:
    """(label, pattern, flags) for every regex any grader uses."""
    found: List[Tuple[str, str, str]] = []
    for case in discover_cases():
        for name, grader, _ in load_graders(case):
            if not grader:
                continue
            label = f"{case.name}/{name}"
            if grader.get("type") == "regex":
                found.append((label, grader["pattern"], grader.get("flags", "")))
            if grader.get("input_match"):
                found.append((label, grader["input_match"], ""))
            for side in ("before", "after"):
                ref = grader.get(side)
                if isinstance(ref, dict) and ref.get("input_match"):
                    found.append((f"{label}.{side}", ref["input_match"], ""))
    return found


@unittest.skipIf(NODE is None, "node is not on PATH (the Python checks above still ran)")
class JavaScriptRegexTest(unittest.TestCase):
    def test_every_grader_regex_compiles_in_javascript(self) -> None:
        regexes = all_grader_regexes()
        results = run_in_javascript([(pattern, flags, "") for _, pattern, flags in regexes])
        for (label, _, _), result in zip(regexes, results):
            with self.subTest(grader=label):
                self.assertTrue(result["ok"], result.get("error"))

    def test_examples_give_the_same_answers_in_javascript(self) -> None:
        examples = tool_input_examples() + text_examples() + bugfix_file_examples()
        if SCAFFOLD_SKIP_REASON is None:
            examples += ledger_examples() + trace_examples()
        results = run_in_javascript([(pattern, flags, text) for _, pattern, flags, text, _ in examples])
        for (label, _, _, text, expected), result in zip(examples, results):
            with self.subTest(example=label, should_match=expected, text=text[:120]):
                self.assertTrue(result["ok"], result.get("error"))
                self.assertEqual(result["match"], expected)


if __name__ == "__main__":
    unittest.main()
