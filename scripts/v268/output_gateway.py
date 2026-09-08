"""Validate and serialize Goal Teams responses through one local entrypoint.

This tool never sends a message, grants permission, or claims Host interception.
Delivery facts and review identities are supplied by the caller; readback and
serialization establish local consistency, not external actor attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11+ is required for the output gateway.")

SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts.v250.output_contract import serialize_output, validate_output
from scripts.v267.output_dashboard import validate_dashboard
from scripts.v268.output_dashboard import render_document_result, serialize_dashboard
from scripts.v268.specification_delivery import (
    SpecificationError,
    observe_record,
    prepare_record,
    validate_record,
)

REQUEST_SCHEMA = "goal-teams-output-request-v2.68"
RESULT_SCHEMA = "goal-teams-output-result-v2.68"
REQUEST_FIELDS = frozenset({
    "schema_version", "facts", "project", "current_round", "estimated_total_rounds",
    "loop_decision", "task", "members", "result", "banchmark", "next_action",
    "dashboard", "specification_record",
})
FACT_FIELDS = frozenset({"activity", "persistent_write", "development_admitted"})
DECISIONS = {"continue", "replan", "stop"}
MAX_JSON_BYTES = 4 * 1024 * 1024


class OutputError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _rounds(current: Any, total: Any) -> bool:
    return type(current) is int and type(total) is int and 1 <= current <= total


def classify_delivery(facts: Mapping[str, Any]) -> str:
    """Classify typed caller facts without making them an authorization oracle."""
    if not isinstance(facts, Mapping) or set(facts) != FACT_FIELDS:
        raise OutputError("E_V268_OUTPUT_FACTS")
    if type(facts["persistent_write"]) is not bool or type(facts["development_admitted"]) is not bool:
        raise OutputError("E_V268_OUTPUT_FACTS")
    activity = facts["activity"]
    if not isinstance(activity, str):
        raise OutputError("E_V268_OUTPUT_FACTS")
    if activity in {"discussion", "plan_preview"}:
        if facts["persistent_write"] or facts["development_admitted"]:
            raise OutputError("E_V268_OUTPUT_FACTS")
        return activity
    if activity == "document":
        if not facts["persistent_write"] or facts["development_admitted"]:
            raise OutputError("E_V268_OUTPUT_FACTS")
        return "specification_delivery"
    if activity in {"development", "release"} and facts["development_admitted"]:
        return "execution"
    raise OutputError("E_V268_OUTPUT_FACTS")


def _execution_heading(text: str) -> bool:
    """Reject an actual execution heading, not a quoted discussion of its name."""
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        match = re.match(r"(`{3,}|~{3,})", stripped)
        if match:
            marker = match[1]
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
            continue
        if fence is None and re.match(
            r"^(?:#{1,6}\s+)?[*_]*◆\s*(?:Goal-Teams 任务执行看板|Context / Knowledge / Tools|LOOP：)",
            stripped,
        ):
            return True
    return False


def _spec_status(request: Mapping[str, Any], repo_root: Path | str) -> tuple[str, list[dict]]:
    """Read artifact status independently, including when output validation fails."""
    record = request.get("specification_record")
    if record is None:
        return "not_applicable", []
    try:
        verdict = validate_record(record, repo_root)
        return verdict["artifact_delivery"], verdict["artifacts"]
    except (SpecificationError, OSError, TypeError, ValueError, KeyError):
        return "unverified", []


def _result(*, ok: bool, mode: str, decision: str, body: str,
            artifact_delivery: str, errors: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "ok": ok,
        "mode": mode,
        "loop_decision": decision,
        "output_contract": "passed" if ok else "blocked",
        "artifact_delivery": artifact_delivery,
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "errors": list(errors),
        "host_enforcement": "unavailable",
        "frame_verification": "unavailable",
        "claim_scope": "local_validation_and_serialization_only",
    }


def _fallback(request: Mapping[str, Any], *, mode: str, code: str,
              artifact_delivery: str = "not_applicable", artifact_links: str = "") -> dict[str, Any]:
    # Deliberately do not echo arbitrary input values or exception text.
    current, total = request.get("current_round"), request.get("estimated_total_rounds")
    if not _rounds(current, total):
        current, total = 1, 1
    payload = {
        "任务": "检查并恢复输出合同。",
        "成员": "Goal Teams 输出校验器。",
        "进度": f"第 {current} 轮/共 {total} 轮；输出诊断。",
        "结果": f"blocked：{code}。请修正必要输入后重新渲染。"
                  f"文档交付状态：{artifact_delivery}；此输出错误不回滚已验证的交付事实。" + artifact_links,
        "Banchmark": "请求的输出未通过；诊断正文已经外层校验。Host 强制发送未验证。",
        "下一轮 LOOP": "replan：补齐输入或当前绑定，保留原始交付物，重新调用输出入口。",
    }
    body = serialize_output(payload, loop_decision="replan")
    return _result(ok=False, mode=mode, decision="replan", body=body,
                   artifact_delivery=artifact_delivery, errors=[code])


def render_response(request: Mapping[str, Any], repo_root: Path | str) -> dict[str, Any]:
    """Generate either validated response bytes or validated blocked diagnostics."""
    request = request if isinstance(request, Mapping) else {}
    artifact_delivery, artifacts = _spec_status(request, repo_root)
    artifact_links = ""
    if artifacts:
        from urllib.parse import quote

        links = []
        for artifact in artifacts:
            path = Path(repo_root).resolve() / artifact["path"]
            label = re.sub(r"([\\`*_{}\[\]()#!|<>])", r"\\\1", path.name)
            href = quote(str(path), safe="/:@-._~ ")
            links.append(f"[{label}](<{href}>)")
        artifact_links = "\n\n已读回产物：" + "、".join(links)
    mode = "unresolved"
    try:
        if set(request) != REQUEST_FIELDS or request.get("schema_version") != REQUEST_SCHEMA:
            raise OutputError("E_V268_OUTPUT_REQUEST")
        mode = classify_delivery(request["facts"])
        for field in ("project", "task", "members", "banchmark", "next_action"):
            if not _text(request[field]):
                raise OutputError("E_V268_OUTPUT_TEXT")
        current, total = request["current_round"], request["estimated_total_rounds"]
        if not _rounds(current, total):
            raise OutputError("E_V268_OUTPUT_ROUND")
        decision = request["loop_decision"]
        if not isinstance(decision, str) or decision not in DECISIONS:
            raise OutputError("E_V268_OUTPUT_DECISION")
        dashboard, record = request["dashboard"], request["specification_record"]
        if mode in {"discussion", "plan_preview"}:
            if dashboard is not None or record is not None or not _text(request["result"]):
                raise OutputError("E_V268_OUTPUT_MODE_PAYLOAD")
            if _execution_heading(request["result"]):
                raise OutputError("E_V268_OUTPUT_DISCUSSION_DASHBOARD")
            rendered = request["result"]
        elif mode == "execution":
            if record is not None or request["result"] != "" or not isinstance(dashboard, Mapping):
                raise OutputError("E_V268_OUTPUT_DASHBOARD_REQUIRED")
            if dashboard.get("project") != request["project"]:
                raise OutputError("E_V268_OUTPUT_PROJECT_BINDING")
            inner_loop = dashboard.get("loop")
            if not isinstance(inner_loop, Mapping) or (
                inner_loop.get("current_round") != current
                or inner_loop.get("estimated_total_rounds") != total
            ):
                raise OutputError("E_V268_OUTPUT_ROUND_BINDING")
            verdict = validate_dashboard(dashboard, loop_decision=decision, repo_root=repo_root)
            if not verdict["ok"]:
                raise OutputError(str(verdict["error_code"]))
            rendered = serialize_dashboard(dashboard, loop_decision=decision, repo_root=repo_root)
        else:
            if dashboard is not None or request["result"] != "" or not isinstance(record, Mapping):
                raise OutputError("E_V268_OUTPUT_SPECIFICATION_REQUIRED")
            spec = validate_record(record, repo_root)
            artifact_delivery = spec["artifact_delivery"]
            rendered = render_document_result(
                record, repo_root, project=request["project"], current_round=current,
                estimated_total_rounds=total, loop_decision=decision,
            )
        terminal = "下一个任务" if decision == "stop" else "下一轮 LOOP"
        payload = {
            "任务": request["task"], "成员": request["members"],
            "进度": f"第 {current} 轮/共 {total} 轮",
            "结果": rendered, "Banchmark": request["banchmark"],
            terminal: request["next_action"],
        }
        verdict = validate_output(payload, loop_decision=decision)
        if not verdict["ok"]:
            raise OutputError(str(verdict["error_code"]))
        body = serialize_output(payload, loop_decision=decision)
        return _result(ok=True, mode=mode, decision=decision, body=body,
                       artifact_delivery=artifact_delivery, errors=[])
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        code = getattr(exc, "code", "E_V268_OUTPUT_RENDER")
        if not isinstance(code, str) or not re.fullmatch(r"E_[A-Z0-9_]{1,100}", code):
            code = "E_V268_OUTPUT_RENDER"
        return _fallback(request, mode=mode, code=code, artifact_delivery=artifact_delivery,
                         artifact_links=artifact_links)


def _load_json(path: Path) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise OutputError("E_V268_JSON_DUPLICATE")
            result[key] = value
        return result

    def reject_constant(value):
        raise OutputError("E_V268_JSON_CONSTANT")

    if path.is_symlink() or not path.is_file():
        raise OutputError("E_V268_JSON_FILE")
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise OutputError("E_V268_JSON_SIZE")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OutputError("E_V268_JSON_INVALID") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render")
    render.add_argument("--request", type=Path, required=True)
    render.add_argument("--format", choices=("json", "markdown"), default="json")
    prepare = sub.add_parser("prepare-specification")
    prepare.add_argument("--request", type=Path, required=True)
    observe = sub.add_parser("observe-specification")
    observe.add_argument("--record", type=Path, required=True)
    observe.add_argument("--reviews", type=Path, required=True)
    observe.add_argument("--reflection", required=True)
    for command in (render, prepare, observe):
        command.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "render":
            result = render_response(_load_json(args.request), args.repo_root)
        elif args.command == "prepare-specification":
            source = _load_json(args.request)
            expected = {"record_id", "user_request", "paths", "owner", "reviewer"}
            if not isinstance(source, dict) or set(source) != expected:
                raise OutputError("E_V268_SPEC_PREPARE_INPUT")
            result = prepare_record(args.repo_root, **source)
        else:
            result = observe_record(_load_json(args.record), args.repo_root,
                                    reviews=_load_json(args.reviews), reflection=args.reflection)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        code = getattr(exc, "code", "E_V268_JSON_INPUT")
        if not isinstance(code, str) or not re.fullmatch(r"E_[A-Z0-9_]{1,100}", code):
            code = "E_V268_JSON_INPUT"
        result = _fallback({}, mode="unresolved", code=code)
    if getattr(args, "format", "json") == "markdown":
        sys.stdout.write(result["body"] + "\n")
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
    return 1 if result.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
