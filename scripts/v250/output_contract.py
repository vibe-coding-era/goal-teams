"""Validate the concise V2.50 user-visible six-field response envelope."""

from __future__ import annotations

from typing import Any, Mapping


BASE_FIELDS = ("任务", "成员", "进度", "结果", "Banchmark")
TERMINAL_BY_DECISION = {
    "continue": "下一轮 LOOP",
    "replan": "下一轮 LOOP",
    "stop": "下一个任务",
}


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
