"""Validate and render the V2.66 dashboard embedded in the outer Result field."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA_VERSION = "goal-teams-output-dashboard-v2.66"
DECISIONS = frozenset({"continue", "replan", "stop"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PRIORITY_RE = re.compile(r"^P[0-9]+$")


def _result(*errors: str) -> dict[str, Any]:
    unique = list(dict.fromkeys(errors))
    return {
        "ok": not unique,
        "error_code": unique[0] if unique else None,
        "errors": unique,
        "mutation_count": 0,
        "schema_version": SCHEMA_VERSION,
    }


def _exact(value: Any, fields: set[str]) -> bool:
    return isinstance(value, Mapping) and set(value) == fields


def _text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and "\n" not in value
        and "\r" not in value
        and "|" not in value
    )


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _link(value: Any) -> bool:
    return (
        _exact(value, {"label", "href"})
        and _text(value.get("label"))
        and _text(value.get("href"))
        and not any(marker in str(value["href"]) for marker in ("{", "}", "<", ">"))
    )


def _links(value: Any) -> bool:
    return isinstance(value, list) and all(_link(item) for item in value)


def _https_link(value: Mapping[str, Any]) -> bool:
    if not _link(value):
        return False
    parsed = urlsplit(str(value["href"]))
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


def _local_link_path(value: Mapping[str, Any], repo_root: Path) -> Path | None:
    """Resolve an exact repo-relative regular file without following symlinks."""

    href = str(value.get("href", ""))
    if "\\" in href or "\0" in href:
        return None
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    relative = PurePosixPath(parsed.path)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        return None
    candidate = repo_root.joinpath(*relative.parts)
    cursor = repo_root
    try:
        for part in relative.parts:
            cursor = cursor / part
            mode = os.lstat(cursor).st_mode
            if stat.S_ISLNK(mode):
                return None
        if not stat.S_ISREG(os.lstat(candidate).st_mode):
            return None
    except (FileNotFoundError, NotADirectoryError, OSError):
        return None
    return candidate


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _same_json(left: Any, right: Any) -> bool:
    options = {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")}
    return json.dumps(left, **options) == json.dumps(right, **options)


def _validate_dashboard(value: Any) -> list[str]:
    fields = {
        "completed_tasks",
        "total_tasks",
        "completed_subtasks",
        "total_subtasks",
        "tasklist_ref",
        "state_machine_ref",
        "active_rows",
    }
    if not _exact(value, fields):
        return ["E_V266_OUTPUT_DASHBOARD"]
    errors: list[str] = []
    for complete, total in (
        ("completed_tasks", "total_tasks"),
        ("completed_subtasks", "total_subtasks"),
    ):
        if not _count(value[complete]) or not _count(value[total]) or value[complete] > value[total]:
            errors.append("E_V266_OUTPUT_COUNTS")
    if not _link(value["tasklist_ref"]) or not _link(value["state_machine_ref"]):
        errors.append("E_V266_OUTPUT_LINK")
    rows = value["active_rows"]
    if not isinstance(rows, list):
        return errors + ["E_V266_OUTPUT_ACTIVE_ROWS"]
    task_ids: set[str] = set()
    parent_ids: set[str] = set()
    row_fields = {
        "row_kind",
        "task_id",
        "parent_task_id",
        "priority",
        "name",
        "members",
        "parallel",
        "in_progress",
        "remaining",
    }
    for row in rows:
        if not _exact(row, row_fields):
            errors.append("E_V266_OUTPUT_ACTIVE_ROWS")
            continue
        task_id = row["task_id"]
        kind = row["row_kind"]
        members = row["members"]
        if (
            kind not in {"task", "subtask"}
            or not _text(task_id)
            or task_id in task_ids
            or not PRIORITY_RE.fullmatch(str(row["priority"]))
            or not _text(row["name"])
            or not isinstance(members, list)
            or not members
            or not all(_text(member) for member in members)
            or len(members) != len(set(members))
            or type(row["parallel"]) is not bool
            or not _count(row["in_progress"])
            or not _count(row["remaining"])
            or row["in_progress"] + row["remaining"] <= 0
        ):
            errors.append("E_V266_OUTPUT_ACTIVE_ROWS")
            continue
        parent = row["parent_task_id"]
        if kind == "task":
            if parent is not None:
                errors.append("E_V266_OUTPUT_ACTIVE_ROWS")
            parent_ids.add(str(task_id))
        elif not _text(parent) or parent not in parent_ids:
            errors.append("E_V266_OUTPUT_ACTIVE_ROWS")
        task_ids.add(str(task_id))
    return errors


def _validate_context(value: Any) -> list[str]:
    if not _exact(value, {"core_rules", "project_knowledge", "codebase", "tools"}):
        return ["E_V266_OUTPUT_CONTEXT"]
    errors: list[str] = []
    if not _links(value["core_rules"]) or not _links(value["project_knowledge"]):
        errors.append("E_V266_OUTPUT_LINK")
    elif not any(
        item.get("label") == "memory.md"
        and PurePosixPath(str(item.get("href", ""))).name == "memory.md"
        for item in value["project_knowledge"]
    ):
        errors.append("E_V266_OUTPUT_PROJECT_MEMORY")
    if not _link(value["codebase"]):
        errors.append("E_V266_OUTPUT_LINK")
    tools = value["tools"]
    if not isinstance(tools, list):
        return errors + ["E_V266_OUTPUT_CONTEXT"]
    for tool in tools:
        if (
            not _exact(tool, {"tool_kind", "label", "href"})
            or tool.get("tool_kind") not in {"MCP", "CLI", "API"}
            or not _link({"label": tool.get("label"), "href": tool.get("href")})
        ):
            errors.append("E_V266_OUTPUT_LINK")
    return errors


def _validate_loop(value: Any, loop_decision: str) -> list[str]:
    fields = {
        "current_round",
        "estimated_total_rounds",
        "plan",
        "do",
        "new_evidence_count",
        "gap_count",
        "blocked_count",
        "decision",
        "evidence_ref",
        "banchmark_ref",
        "loop_review_ref",
    }
    if not _exact(value, fields):
        return ["E_V266_OUTPUT_LOOP"]
    errors: list[str] = []
    current = value["current_round"]
    total = value["estimated_total_rounds"]
    if (
        not isinstance(current, int)
        or isinstance(current, bool)
        or current < 1
        or not isinstance(total, int)
        or isinstance(total, bool)
        or total < 1
        or current > total
    ):
        errors.append("E_V266_OUTPUT_LOOP_ROUND")
    if not _text(value["plan"]) or not _text(value["do"]):
        errors.append("E_V266_OUTPUT_LOOP")
    for field in ("new_evidence_count", "gap_count", "blocked_count"):
        if not _count(value[field]):
            errors.append("E_V266_OUTPUT_LOOP")
    if value["decision"] not in DECISIONS or value["decision"] != loop_decision:
        errors.append("E_V266_OUTPUT_DECISION")
    if not _link(value["evidence_ref"]) or value["evidence_ref"].get("label") != "evidence.json":
        errors.append("E_V266_OUTPUT_LINK")
    if not _link(value["banchmark_ref"]) or value["banchmark_ref"].get("label") != "Banchmark.md":
        errors.append("E_V266_OUTPUT_LINK")
    if not _link(value["loop_review_ref"]) or value["loop_review_ref"].get("label") != "loop-review.md":
        errors.append("E_V266_OUTPUT_LINK")
    return errors


def _validate_readback(value: Mapping[str, Any], repo_root: Path) -> list[str]:
    dashboard = value["dashboard"]
    context = value["context"]
    loop = value["loop"]
    local_links = [
        dashboard["tasklist_ref"],
        dashboard["state_machine_ref"],
        *context["core_rules"],
        *context["project_knowledge"],
        *context["tools"],
        loop["evidence_ref"],
        loop["banchmark_ref"],
        loop["loop_review_ref"],
    ]
    resolved: dict[str, Path] = {}
    for link in local_links:
        path = _local_link_path(link, repo_root)
        if path is None:
            return ["E_V266_OUTPUT_READBACK"]
        resolved[str(link["href"])] = path

    bindings = value["bindings"]
    digest_links = {
        "tasklist_sha256": dashboard["tasklist_ref"],
        "state_machine_sha256": dashboard["state_machine_ref"],
        "evidence_sha256": loop["evidence_ref"],
        "banchmark_sha256": loop["banchmark_ref"],
        "loop_review_sha256": loop["loop_review_ref"],
    }
    for binding, link in digest_links.items():
        if _file_sha256(resolved[str(link["href"])]) != bindings[binding]:
            return ["E_V266_OUTPUT_BINDING"]

    state = _json_object(resolved[str(dashboard["state_machine_ref"]["href"])])
    evidence = _json_object(resolved[str(loop["evidence_ref"]["href"])])
    if state is None or evidence is None:
        return ["E_V266_OUTPUT_READBACK"]
    return _validate_execution_facts(value, state, evidence)


def _validate_execution_facts(
    value: Mapping[str, Any],
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> list[str]:
    if not _exact(state, {"schema_version", "dashboard", "loop"}) or state.get(
        "schema_version"
    ) != "goal-teams-dashboard-state-v1":
        return ["E_V266_OUTPUT_STATE_MISMATCH"]
    state_dashboard = state.get("dashboard")
    state_loop = state.get("loop")
    if not _exact(
        state_dashboard,
        {
            "completed_tasks",
            "total_tasks",
            "completed_subtasks",
            "total_subtasks",
            "active_rows",
            "ready_layers",
        },
    ) or not _exact(
        state_loop,
        {
            "current_round",
            "estimated_total_rounds",
            "plan",
            "do",
            "gap_count",
            "blocked_count",
            "decision",
        },
    ):
        return ["E_V266_OUTPUT_STATE_MISMATCH"]

    dashboard = value["dashboard"]
    loop = value["loop"]
    count_fields = (
        "completed_tasks",
        "total_tasks",
        "completed_subtasks",
        "total_subtasks",
    )
    if any(not _count(state_dashboard[field]) for field in count_fields) or any(
        not _same_json(dashboard[field], state_dashboard[field]) for field in count_fields
    ):
        return ["E_V266_OUTPUT_STATE_MISMATCH"]

    state_rows = state_dashboard["active_rows"]
    if not isinstance(state_rows, list) or len(state_rows) != len(dashboard["active_rows"]):
        return ["E_V266_OUTPUT_STATE_MISMATCH"]
    state_row_fields = {
        "row_kind",
        "task_id",
        "parent_task_id",
        "priority",
        "name",
        "members",
        "in_progress",
        "remaining",
    }
    active_ids: list[str] = []
    for observed, expected in zip(dashboard["active_rows"], state_rows):
        if not _exact(expected, state_row_fields):
            return ["E_V266_OUTPUT_STATE_MISMATCH"]
        projected = {field: observed[field] for field in state_row_fields}
        if not _same_json(projected, expected):
            return ["E_V266_OUTPUT_STATE_MISMATCH"]
        active_ids.append(str(observed["task_id"]))

    task_rows = [row for row in dashboard["active_rows"] if row["row_kind"] == "task"]
    subtask_rows = [row for row in dashboard["active_rows"] if row["row_kind"] == "subtask"]
    if (
        task_rows
        and dashboard["completed_tasks"] >= dashboard["total_tasks"]
        or subtask_rows
        and dashboard["completed_subtasks"] >= dashboard["total_subtasks"]
    ):
        return ["E_V266_OUTPUT_STATE_MISMATCH"]

    ready_layers = state_dashboard["ready_layers"]
    if not isinstance(ready_layers, list):
        return ["E_V266_OUTPUT_READY_LAYERS"]
    layer_by_id: dict[str, int] = {}
    flattened: list[str] = []
    for layer in ready_layers:
        if (
            not isinstance(layer, list)
            or not layer
            or not all(_text(task_id) for task_id in layer)
            or len(layer) != len(set(layer))
        ):
            return ["E_V266_OUTPUT_READY_LAYERS"]
        for task_id in layer:
            if task_id in layer_by_id:
                return ["E_V266_OUTPUT_READY_LAYERS"]
            layer_by_id[task_id] = len(layer)
            flattened.append(task_id)
    if flattened != active_ids:
        return ["E_V266_OUTPUT_READY_LAYERS"]
    for row in dashboard["active_rows"]:
        expected_parallel = layer_by_id[str(row["task_id"])] > 1
        if row["parallel"] is not expected_parallel:
            return ["E_V266_OUTPUT_READY_LAYERS"]

    state_loop_fields = {
        "current_round",
        "estimated_total_rounds",
        "plan",
        "do",
        "gap_count",
        "blocked_count",
        "decision",
    }
    if (
        not isinstance(state_loop["current_round"], int)
        or isinstance(state_loop["current_round"], bool)
        or state_loop["current_round"] < 1
        or not isinstance(state_loop["estimated_total_rounds"], int)
        or isinstance(state_loop["estimated_total_rounds"], bool)
        or state_loop["estimated_total_rounds"] < 1
        or not _text(state_loop["plan"])
        or not _text(state_loop["do"])
        or not _count(state_loop["gap_count"])
        or not _count(state_loop["blocked_count"])
        or state_loop["decision"] not in DECISIONS
        or not _same_json({field: loop[field] for field in state_loop_fields}, state_loop)
    ):
        return ["E_V266_OUTPUT_STATE_MISMATCH"]
    if not _exact(evidence, {"schema_version", "new_evidence_count"}) or evidence.get(
        "schema_version"
    ) != "goal-teams-dashboard-evidence-v1":
        return ["E_V266_OUTPUT_EVIDENCE_MISMATCH"]
    if not _count(evidence.get("new_evidence_count")) or not _same_json(
        evidence.get("new_evidence_count"), loop["new_evidence_count"]
    ):
        return ["E_V266_OUTPUT_EVIDENCE_MISMATCH"]
    return []


def validate_dashboard(
    value: Mapping[str, Any],
    *,
    loop_decision: str,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    if loop_decision not in DECISIONS or not _exact(
        value,
        {"schema_version", "mode", "project", "dashboard", "context", "loop", "bindings"},
    ):
        return _result("E_V266_OUTPUT_SHAPE")
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION or not _text(value.get("project")):
        errors.append("E_V266_OUTPUT_SHAPE")
    mode = value.get("mode")
    if mode not in {"execution", "preview"}:
        errors.append("E_V266_OUTPUT_MODE")
    errors.extend(_validate_dashboard(value.get("dashboard")))
    errors.extend(_validate_context(value.get("context")))
    errors.extend(_validate_loop(value.get("loop"), loop_decision))
    context = value.get("context") if isinstance(value.get("context"), Mapping) else {}
    if isinstance(context.get("codebase"), Mapping):
        if not _https_link(context["codebase"]) or context["codebase"].get("label") != value.get("project"):
            errors.append("E_V266_OUTPUT_LINK")
    bindings = value.get("bindings")
    binding_fields = {
        "tasklist_sha256",
        "state_machine_sha256",
        "evidence_sha256",
        "banchmark_sha256",
        "loop_review_sha256",
        "freshness",
    }
    if not _exact(bindings, binding_fields) or bindings.get("freshness") != "current" or any(
        not SHA256_RE.fullmatch(str(bindings.get(field, "")))
        for field in binding_fields - {"freshness"}
    ):
        errors.append("E_V266_OUTPUT_BINDING")
    if mode == "preview":
        dashboard = value.get("dashboard") if isinstance(value.get("dashboard"), Mapping) else {}
        loop = value.get("loop") if isinstance(value.get("loop"), Mapping) else {}
        if (
            any(dashboard.get(field) != 0 for field in ("completed_tasks", "total_tasks", "completed_subtasks", "total_subtasks"))
            or bool(dashboard.get("active_rows"))
            or any(loop.get(field) != 0 for field in ("new_evidence_count", "gap_count", "blocked_count"))
            or loop.get("plan") != "not_created"
            or loop.get("do") != "not_run"
            or loop.get("decision") != "continue"
        ):
            errors.append("E_V266_OUTPUT_PREVIEW_STATE")
        # Preview is a planning/schema shape only.  It never enters the
        # execution renderer because its links and digests have no readback.
        errors.append("E_V266_OUTPUT_PREVIEW_STATE")
    elif mode == "execution" and not errors:
        if repo_root is None:
            errors.append("E_V266_OUTPUT_READBACK")
        else:
            root_input = Path(repo_root)
            try:
                if root_input.is_symlink():
                    raise OSError("repo root must not be a symlink")
                root = root_input.resolve(strict=True)
                if not root.is_dir():
                    raise OSError("repo root must be a directory")
            except (OSError, RuntimeError):
                errors.append("E_V266_OUTPUT_READBACK")
            else:
                errors.extend(_validate_readback(value, root))
    return _result(*errors)


def _markdown_link(value: Mapping[str, str], repo_root: Path | None = None) -> str:
    href = value["href"]
    if repo_root is not None and not urlsplit(href).scheme:
        href = str(repo_root.joinpath(*PurePosixPath(href).parts))
    target = f"<{href}>" if any(character.isspace() for character in href) else href
    return f"[{value['label']}]({target})"


def _members(values: Sequence[str], parallel: bool) -> str:
    rendered = "、".join(f"`{member}`" for member in values)
    return rendered + ("（并行）" if parallel else "")


def serialize_dashboard(
    value: Mapping[str, Any],
    *,
    loop_decision: str,
    repo_root: Path | str | None = None,
) -> str:
    verdict = validate_dashboard(value, loop_decision=loop_decision, repo_root=repo_root)
    if not verdict["ok"]:
        raise ValueError(str(verdict["error_code"]))
    dashboard = value["dashboard"]
    context = value["context"]
    loop = value["loop"]
    display_root = Path(repo_root).resolve(strict=True) if repo_root is not None else None
    lines = [
        "**◆ Goal-Teams 任务执行看板：** "
        f"已完成任务 {dashboard['completed_tasks']}/{dashboard['total_tasks']}｜"
        f"已完成子任务 {dashboard['completed_subtasks']}/{dashboard['total_subtasks']}｜"
        f"{_markdown_link(dashboard['tasklist_ref'], display_root)}｜"
        f"{_markdown_link(dashboard['state_machine_ref'], display_root)}",
        "",
        "| 优先级 | 任务 / 子任务 | Subagent 成员 | 进度 |",
        "|---|---|---|---|",
    ]
    for row in dashboard["active_rows"]:
        priority = row["priority"] if row["row_kind"] == "task" else ""
        name = f"**{row['name']}**" if row["row_kind"] == "task" else f"↳ {row['name']}"
        lines.append(
            f"| {priority} | {name} | {_members(row['members'], row['parallel'])} | "
            f"进行中 {row['in_progress']}｜剩余 {row['remaining']} |"
        )
    lines.extend(
        [
            "",
            "**◆ Context / Knowledge / Tools：**",
            "",
            "| 核心规则 | 项目知识 | 代码库 | MCP/CLI/API |",
            "|---|---|---|---|",
        ]
    )
    rows = max(
        len(context["core_rules"]),
        len(context["project_knowledge"]),
        len(context["tools"]),
        1,
    )
    for index in range(rows):
        core = (
            _markdown_link(context["core_rules"][index], display_root)
            if index < len(context["core_rules"])
            else ""
        )
        knowledge = (
            _markdown_link(context["project_knowledge"][index], display_root)
            if index < len(context["project_knowledge"])
            else ""
        )
        codebase = _markdown_link(context["codebase"], display_root) if index == 0 else ""
        tool = ""
        if index < len(context["tools"]):
            item = context["tools"][index]
            tool = f"{item['tool_kind']}：{_markdown_link(item, display_root)}"
        lines.append(f"| {core} | {knowledge} | {codebase} | {tool} |")
    lines.extend(
        [
            "",
            f"**◆ LOOP：第 {loop['current_round']} 轮 / 预计 {loop['estimated_total_rounds']} 轮**",
            "",
            f"`P ｜ 计划 / 下一轮目标：`{loop['plan']}  ",
            f"`D ｜ 执行 / 本轮执行：`{loop['do']}  ",
            "`C ｜ 检查 / 执行结果：`"
            f"新增 Evidence {loop['new_evidence_count']}｜缺口 {loop['gap_count']}｜"
            f"阻塞 {loop['blocked_count']}｜{_markdown_link(loop['banchmark_ref'], display_root)}  ",
            "`A ｜ 改进 / 调整行动：`"
            f"决策 `{loop['decision']}`｜改进反思：{_markdown_link(loop['loop_review_ref'], display_root)}",
        ]
    )
    return "\n".join(lines)


__all__ = ["SCHEMA_VERSION", "serialize_dashboard", "validate_dashboard"]
