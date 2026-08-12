"""Validate the concise V2.62 user-visible six-field response envelope."""

from __future__ import annotations

import re
from typing import Any, Mapping


BASE_FIELDS = ("任务", "成员", "进度", "结果", "Banchmark")
TERMINAL_BY_DECISION = {
    "continue": "下一轮 LOOP",
    "replan": "下一轮 LOOP",
    "stop": "下一个任务",
}
LOOP_PROGRESS_RE = re.compile(
    r"第\s*(?P<current>[1-9][0-9]*)\s*轮\s*/\s*(?:共|总)\s*(?P<total>[1-9][0-9]*)\s*轮"
)
LOOP_IMPROVEMENT_LABEL = "LOOP 改进建议"


def validate_output(value: Mapping[str, Any], *, loop_decision: str) -> dict[str, Any]:
    terminal = TERMINAL_BY_DECISION.get(loop_decision)
    if terminal is None or not isinstance(value, Mapping):
        return {
            "ok": False,
            "error_code": "E_V250_OUTPUT_ENVELOPE",
            "errors": ["E_V250_OUTPUT_ENVELOPE"],
            "mutation_count": 0,
        }
    expected = {*BASE_FIELDS, terminal}
    values_are_text = all(
        isinstance(value.get(field), str) and bool(value[field].strip())
        for field in expected
    )
    if set(value) != expected or not values_are_text:
        return {
            "ok": False,
            "error_code": "E_V250_OUTPUT_ENVELOPE",
            "errors": ["E_V250_OUTPUT_ENVELOPE"],
            "mutation_count": 0,
        }
    progress_match = LOOP_PROGRESS_RE.search(value["进度"])
    if progress_match is None or int(progress_match["current"]) > int(
        progress_match["total"]
    ):
        return {
            "ok": False,
            "error_code": "E_V251_OUTPUT_LOOP_PROGRESS",
            "errors": ["E_V251_OUTPUT_LOOP_PROGRESS"],
            "mutation_count": 0,
        }
    if loop_decision == "stop" and LOOP_IMPROVEMENT_LABEL not in value["结果"]:
        return {
            "ok": False,
            "error_code": "E_V251_OUTPUT_LOOP_IMPROVEMENTS",
            "errors": ["E_V251_OUTPUT_LOOP_IMPROVEMENTS"],
            "mutation_count": 0,
        }
    return {
        "ok": True,
        "error_code": None,
        "errors": [],
        "mutation_count": 0,
        "terminal_field": terminal,
        "field_count": 6,
        "visible_reasoning_field_present": False,
        "assurance_state": "contract_mapped_static_tests_passed",
        "host_runtime_verified": False,
        "provider_prompt_assembly": "unavailable",
        "runtime_receipt_sha256": None,
    }


def serialize_output(value: Mapping[str, Any], *, loop_decision: str) -> str:
    """Render the only user-visible envelope in deterministic field order.

    The serializer does not add a runtime identity fingerprint.  Runtime and
    Provider assurance stay in machine receipts and the validation result.
    """

    validation = validate_output(value, loop_decision=loop_decision)
    if not validation.get("ok"):
        raise ValueError(str(validation.get("error_code") or "E_V250_OUTPUT_ENVELOPE"))
    terminal = TERMINAL_BY_DECISION[loop_decision]
    ordered = (*BASE_FIELDS, terminal)
    lines: list[str] = []
    for field in ordered:
        rendered = value[field].strip().replace("\r\n", "\n").replace("\r", "\n")
        rendered = rendered.replace("\n", "\n  ")
        lines.append(f"{field}：{rendered}")
    return "\n\n".join(lines)


__all__ = ["BASE_FIELDS", "serialize_output", "validate_output"]
