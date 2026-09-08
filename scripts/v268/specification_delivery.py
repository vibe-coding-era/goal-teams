"""Read-only, correlated records for locally authorized document delivery.

Digests bind the supplied record and the bytes read here.  They do not authenticate
the caller, a reviewer identity, or an external host's final message delivery.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from urllib.parse import quote


SCHEMA_VERSION = "goal-teams-specification-delivery-v2.68"
_FIELDS = {
    "schema_version", "record_id", "user_request", "authorized_paths", "owner",
    "reviewer", "product_development_admitted", "stage", "inputs", "artifacts",
    "reviews", "reflection", "previous_record_sha256", "record_sha256", "repository_root",
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class SpecificationError(ValueError):
    """A bounded validation failure, suitable for a fail-closed output gateway."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise SpecificationError(code, message)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _digest(record: dict) -> str:
    try:
        payload = {key: value for key, value in record.items() if key != "record_sha256"}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise SpecificationError("E_SPEC_JSON", "Record is not canonical JSON.") from exc


def _root(repo_root: str | Path) -> Path:
    try:
        root = Path(repo_root).absolute()
        _require(not root.is_symlink() and root.is_dir(), "E_SPEC_ROOT", "Repository root must be a directory, not a symlink.")
        return root.resolve(strict=True)
    except (TypeError, ValueError, OSError) as exc:
        if isinstance(exc, SpecificationError):
            raise
        raise SpecificationError("E_SPEC_ROOT", "Repository root is unavailable.") from exc


def _paths(paths: object) -> list[str]:
    _require(type(paths) is list and bool(paths), "E_SPEC_PATH", "Authorization paths must be a nonempty list.")
    seen: set[str] = set()
    for value in paths:
        _require(_text(value), "E_SPEC_PATH", "An authorization path is empty or untyped.")
        parts = value.split("/")
        _require(
            not PurePosixPath(value).is_absolute()
            and all(part not in {"", ".", ".."} for part in parts)
            and not any(char in value for char in "\\<>:")
            and not any(ord(char) < 32 or ord(char) == 127 for char in value),
            "E_SPEC_PATH", "Authorization paths must be canonical repository-relative paths.",
        )
        _require(value not in seen, "E_SPEC_PATH", "Authorization paths must be unique.")
        seen.add(value)
    return list(paths)


def _read(root: Path, path: str, *, allow_missing: bool) -> dict:
    """Open every component without following symlinks; never emit file content."""
    descriptor = None
    parent = None
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parts = path.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "E_SPEC_PATH", "Authorized artifact must be a regular file.")
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        _require(
            (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            and size == after.st_size,
            "E_SPEC_DRIFT", "Artifact changed during readback.",
        )
        return {"path": path, "sha256": digest.hexdigest(), "bytes": size}
    except FileNotFoundError as exc:
        if allow_missing:
            return {"path": path, "exists": False, "sha256": None}
        raise SpecificationError("E_SPEC_MISSING", "Authorized artifact is missing.") from exc
    except OSError as exc:
        raise SpecificationError("E_SPEC_PATH", "Artifact path is unsafe or unreadable.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


def _reviews(reviews: object, paths: list[str], reviewer: str, artifacts: list[dict]) -> None:
    _require(type(reviews) is list, "E_SPEC_REVIEW", "Reviews must be a list.")
    observed = {artifact["path"]: artifact["sha256"] for artifact in artifacts}
    seen: set[str] = set()
    for review in reviews:
        _require(type(review) is dict and set(review) == {"path", "sha256", "reviewer", "verdict", "note"},
                 "E_SPEC_REVIEW", "Review fields do not match the contract.")
        path = review["path"]
        _require(isinstance(path, str) and path in paths and path not in seen,
                 "E_SPEC_REVIEW", "Review must bind one unique authorized artifact.")
        _require(review["reviewer"] == reviewer and review["verdict"] in ("passed", "failed")
                 and _text(review["note"]) and _sha(review["sha256"])
                 and observed.get(path) == review["sha256"],
                 "E_SPEC_REVIEW", "Review identity, verdict, or artifact binding is invalid.")
        seen.add(path)


def _shape(record: object) -> list[str]:
    _require(type(record) is dict and set(record) == _FIELDS, "E_SPEC_SHAPE", "Record fields do not match the contract.")
    _require(record["schema_version"] == SCHEMA_VERSION and record["product_development_admitted"] is False,
             "E_SPEC_SHAPE", "Record schema or development admission is invalid.")
    _require(_text(record["repository_root"]) and Path(record["repository_root"]).is_absolute(),
             "E_SPEC_ROOT_BINDING", "Record must bind its canonical repository root.")
    _require(all(_text(record[key]) for key in ("record_id", "user_request", "owner", "reviewer"))
             and record["owner"] != record["reviewer"], "E_SPEC_IDENTITY", "Document owner and reviewer must be distinct named members.")
    _require(_sha(record["record_sha256"]) and _digest(record) == record["record_sha256"],
             "E_SPEC_DIGEST", "Record self-digest does not match.")
    paths = _paths(record["authorized_paths"])
    inputs = record["inputs"]
    _require(type(inputs) is list and len(inputs) == len(paths), "E_SPEC_INPUT", "Input baseline does not cover the authorized paths.")
    for path, baseline in zip(paths, inputs):
        _require(type(baseline) is dict and set(baseline) == {"path", "exists", "sha256"},
                 "E_SPEC_INPUT", "Input baseline fields are invalid.")
        _require(baseline["path"] == path and type(baseline["exists"]) is bool
                 and (_sha(baseline["sha256"]) if baseline["exists"] else baseline["sha256"] is None),
                 "E_SPEC_INPUT", "Input baseline binding is invalid.")
    _require(type(record["artifacts"]) is list and type(record["reviews"]) is list,
             "E_SPEC_SHAPE", "Artifacts and reviews must be lists.")
    if record["stage"] == "planned":
        _require(record["previous_record_sha256"] is None and record["artifacts"] == []
                 and record["reviews"] == [] and record["reflection"] == "",
                 "E_SPEC_STAGE", "Planned record cannot claim observations or reviews.")
    else:
        _require(record["stage"] == "observed" and _text(record["reflection"])
                 and _sha(record["previous_record_sha256"]), "E_SPEC_STAGE", "Observed record requires its parent digest and reflection.")
        planned = {**record, "stage": "planned", "artifacts": [], "reviews": [], "reflection": "", "previous_record_sha256": None}
        _require(_digest(planned) == record["previous_record_sha256"], "E_SPEC_PARENT", "Observed record does not preserve the planned record binding.")
        _require(len(record["artifacts"]) == len(paths), "E_SPEC_ARTIFACT", "Observation must cover every authorized artifact.")
        for path, artifact in zip(paths, record["artifacts"]):
            _require(type(artifact) is dict and set(artifact) == {"path", "sha256", "bytes"},
                     "E_SPEC_ARTIFACT", "Artifact fields do not match the contract.")
            _require(artifact["path"] == path and _sha(artifact["sha256"])
                     and type(artifact["bytes"]) is int and artifact["bytes"] >= 0,
                     "E_SPEC_ARTIFACT", "Artifact binding is invalid.")
        _reviews(record["reviews"], paths, record["reviewer"], record["artifacts"])
    return paths


def prepare_record(repo_root, *, record_id, user_request, paths, owner, reviewer) -> dict:
    """Bind the authorized scope and existing baseline before a document write."""
    root = _root(repo_root)
    authorized = _paths(paths)
    _require(all(_text(value) for value in (record_id, user_request, owner, reviewer)) and owner != reviewer,
             "E_SPEC_IDENTITY", "Record identity, request, owner, and reviewer must be nonempty and distinct where applicable.")
    inputs = []
    for path in authorized:
        observation = _read(root, path, allow_missing=True)
        inputs.append({"path": path, "exists": observation.get("exists", True), "sha256": observation["sha256"]})
    record = {
        "schema_version": SCHEMA_VERSION, "record_id": record_id, "user_request": user_request,
        "repository_root": str(root),
        "authorized_paths": authorized, "owner": owner, "reviewer": reviewer,
        "product_development_admitted": False, "stage": "planned", "inputs": inputs,
        "artifacts": [], "reviews": [], "reflection": "", "previous_record_sha256": None,
    }
    record["record_sha256"] = _digest(record)
    return record


def observe_record(record, repo_root, *, reviews, reflection) -> dict:
    """Observe authorized document bytes after writing; never mutate the record."""
    paths = _shape(record)
    _require(record["stage"] == "planned", "E_SPEC_STAGE", "Only a planned record can be observed.")
    _require(_text(reflection), "E_SPEC_REFLECTION", "Observation requires a nonempty reflection.")
    root = _root(repo_root)
    _require(record["repository_root"] == str(root), "E_SPEC_ROOT_BINDING", "Record belongs to another repository.")
    artifacts = [_read(root, path, allow_missing=False) for path in paths]
    _reviews(reviews, paths, record["reviewer"], artifacts)
    observed = copy.deepcopy(record)
    observed.update(stage="observed", artifacts=artifacts, reviews=copy.deepcopy(reviews),
                    reflection=reflection, previous_record_sha256=record["record_sha256"])
    observed["record_sha256"] = _digest(observed)
    return observed


def validate_record(record, repo_root) -> dict:
    """Re-read observed artifacts, retaining partial delivery for absent/failed reviews."""
    paths = _shape(record)
    root = _root(repo_root)
    _require(record["repository_root"] == str(root), "E_SPEC_ROOT_BINDING", "Record belongs to another repository.")
    if record["stage"] == "planned":
        # A planned baseline may legitimately differ after its authorized write.
        for path in paths:
            _read(root, path, allow_missing=True)
        return {"ok": True, "artifact_delivery": "pending", "artifacts": []}
    current = [_read(root, path, allow_missing=False) for path in paths]
    _require(current == record["artifacts"], "E_SPEC_DRIFT", "Current artifacts differ from the recorded observation.")
    completed = len(record["reviews"]) == len(paths) and all(review["verdict"] == "passed" for review in record["reviews"])
    return {"ok": True, "artifact_delivery": "completed" if completed else "partial", "artifacts": current}


def _inline(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#!|<>])", r"\\\1", " ".join(value.splitlines()))


def _link(label: str, path: Path) -> str:
    href = quote(str(path), safe="/:@-._~ ")
    return f"[{_inline(label)}](<{href}>)"


def render_document_result(record, repo_root, *, project, current_round, estimated_total_rounds, loop_decision) -> str:
    """Render a V2.68 document view, without inventing V2.67 execution bindings."""
    _require(_text(project), "E_SPEC_RENDER", "Project name is required.")
    _require(type(current_round) is int and type(estimated_total_rounds) is int
             and 1 <= current_round <= estimated_total_rounds, "E_SPEC_ROUND", "Loop rounds must be positive ordered integers.")
    _require(loop_decision in ("continue", "replan", "stop"), "E_SPEC_DECISION", "Loop decision is invalid.")
    validation = validate_record(record, repo_root)
    _require(loop_decision != "stop" or validation["artifact_delivery"] == "completed",
             "E_SPEC_INCOMPLETE", "Incomplete document review cannot produce a completed stop response.")
    root = _root(repo_root)
    total = len(record["authorized_paths"])
    readbacks = len(validation["artifacts"])
    passed = {review["path"] for review in record["reviews"] if review["verdict"] == "passed"}
    lines = [
        f"**◆ Goal-Teams 任务执行看板：** 已完成任务 {len(passed)}/{total}｜已完成子任务 {readbacks + len(passed)}/{2 * total}",
        "", "V2.68 轻量文档视图；依据本地文件 readback 与相关成员复核生成，未证明外部独立或 Host 强制发送。",
        "", "| 优先级 | 任务 / 子任务 | Subagent 成员 | 进度 |", "|---|---|---|---|",
    ]
    observed = {artifact["path"] for artifact in validation["artifacts"]}
    failed = {review["path"] for review in record["reviews"] if review["verdict"] == "failed"}
    for path in record["authorized_paths"]:
        if path not in passed:
            label = _link(path, root / path) if path in observed else _inline(path)
            state = "review failed" if path in failed else "review pending" if path in observed else "readback pending"
            lines.append(f"| P1 | {label} | {_inline(record['owner'])} / {_inline(record['reviewer'])} | {state} |")
    links = "、".join(_link(artifact["path"], root / artifact["path"]) for artifact in validation["artifacts"])
    lines.extend([
        "", "**◆ Context / Knowledge / Tools：**", "",
        "| 核心规则 | 项目知识 | 代码库 | MCP/CLI/API |", "|---|---|---|---|",
        f"|  | {links} | {_link(project, root)} |  |", "",
        f"**◆ LOOP：第 {current_round} 轮 / 预计 {estimated_total_rounds} 轮**", "",
        f"`P ｜ 计划 / 下一轮目标` {_inline(record['user_request'])}  ",
        f"`D ｜ 执行 / 本轮执行` 本地文档 readback {readbacks}/{total}；通过复核 {len(passed)}/{total}。  ",
        f"`C ｜ 检查 / 执行结果` artifact_delivery={validation['artifact_delivery']}；复核身份为调用方记录的相关成员，保障层级 correlated。  ",
        f"`A ｜ 改进 / 调整行动` 决策 `{loop_decision}`；LOOP 改进建议：{record['reflection'] or '本轮尚未观察产物；交付后记录复核与反思。'}",
    ])
    return "\n".join(lines)
