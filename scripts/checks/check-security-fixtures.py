#!/usr/bin/env python3
"""Validate V2.3 capability downgrade and security fixtures without executing payloads."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "v23" / "goalteams_v23.py"
FIXTURES = ROOT / "tests" / "v23" / "fixtures"


def fail(message: str) -> None:
    raise AssertionError(message)


def cli(command: str, fixture: Path, *, expect_success: bool = True) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(TOOL), command, str(fixture)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"{command} did not return one JSON envelope: rc={result.returncode}")
        raise AssertionError from exc
    if not isinstance(payload, dict) or payload.get("ok") is not expect_success:
        fail(f"{command} envelope status mismatch: {payload}")
    if expect_success and result.returncode != 0:
        fail(f"{command} unexpectedly failed: {payload}")
    if not expect_success and result.returncode == 0:
        fail(f"{command} unexpectedly accepted a negative fixture: {payload}")
    return payload


def check_capabilities() -> None:
    full = cli("capability", FIXTURES / "capability" / "full.json")["capability"]
    restricted = cli("capability", FIXTURES / "capability" / "restricted.json")["capability"]
    cli("capability", FIXTURES / "capability" / "privilege-escalation.json", expect_success=False)
    required = {
        "naming_constraints", "custom_goal_subagents", "concurrency", "context_inheritance",
        "shared_filesystem", "recovery", "telemetry", "dispatch_mode",
        "degraded_capability", "reason", "impact", "budget_metric", "fallback_allowed",
    }
    for label, capability in (("full", full), ("restricted", restricted)):
        missing = sorted(required - capability.keys())
        if missing:
            fail(f"{label} capability output omitted fields: {missing}")
    if full["dispatch_mode"] != "goal_subagents" or full["degraded_capability"]:
        fail("full capability fixture was incorrectly degraded")
    if full["budget_metric"] != "tokens_cost" or full["fallback_allowed"] is not True:
        fail("full capability budget/fallback policy is incorrect")
    if restricted["dispatch_mode"] != "generic_subagent_or_serial":
        fail("restricted host did not select its fallback dispatch mode")
    if not restricted["degraded_capability"] or not restricted["reason"] or not restricted["impact"]:
        fail("restricted host downgrade is not auditable")
    if restricted["budget_metric"] != "round_time_member_file_size":
        fail("restricted host fabricated token/cost telemetry")
    if restricted["fallback_allowed"] is not True:
        fail("permission-reducing fallback should be allowed")
    if restricted["concurrency"] != {"max_members": 1, "parallel": False}:
        fail("restricted host concurrency was not normalized deterministically")


def check_redaction() -> None:
    fixture = FIXTURES / "security" / "redaction-input.txt"
    payload = cli("redact", fixture)
    redacted = payload.get("redacted")
    if not isinstance(redacted, str):
        fail("redact output must be text")
    forbidden = (
        "header-token-value", "cookie-secret-value", "query-token-value",
        "json-password-value", "json-api-key-value", "private-key-material-value",
        "/Users/alice/private-project", "/home/bob/company", "C:\\Users\\Carol\\private-project",
    )
    leaked = [value for value in forbidden if value in redacted]
    if leaked:
        fail(f"security redaction leaked fixture values: {leaked}")
    required_visible = ("safe=visible", "visible-user", "visible-json")
    missing_visible = [value for value in required_visible if value not in redacted]
    if missing_visible:
        fail(f"redaction destroyed non-sensitive data: {missing_visible}")
    if redacted.count("[REDACTED") < 6:
        fail("redaction did not emit stable markers for headers, query, JSON, and private key classes")
    if redacted.count("~/") < 2 or "~\\" not in redacted:
        fail("home paths were not minimized to stable cross-platform aliases")


def classify_untrusted_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    """Pure policy evaluation: the payload string is never interpreted or executed."""
    trust = fixture.get("source_trust")
    locked_scope = fixture.get("locked_scope")
    payload = fixture.get("payload")
    if trust != "external_untrusted":
        fail("prompt-injection fixture must be explicitly untrusted")
    if not isinstance(locked_scope, list) or not locked_scope or not all(isinstance(item, str) for item in locked_scope):
        fail("prompt-injection fixture must have a locked scope")
    if not isinstance(payload, str) or not payload:
        fail("prompt-injection fixture payload must be non-empty text")
    indicators = ("ignore all previous instructions", "upload it", "edit scripts/")
    if not all(indicator in payload.lower() for indicator in indicators):
        fail("prompt-injection fixture does not exercise instruction override and scope escape")
    return {
        "classification": "untrusted_data",
        "execute_payload": False,
        "scope_changed": False,
        "allowed_actions": ["classify", "redact", "report"],
    }


def check_prompt_injection() -> None:
    fixture_path = FIXTURES / "security" / "prompt-injection.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict) or not isinstance(fixture.get("expected"), dict):
        fail("prompt-injection fixture schema is invalid")
    actual = classify_untrusted_fixture(fixture)
    if actual != fixture["expected"]:
        fail(f"prompt-injection policy mismatch: {actual}")


def check_v235_security_and_path_gates() -> None:
    """Run the focused executable V2.35 authorization and path-injection gates."""
    command = [
        sys.executable,
        "-m",
        "unittest",
        "-q",
        (
            "tests.v23.test_v235_protocol.V235SpecialistPackageTests."
            "test_security_scope_and_external_active_scan_fail_closed"
        ),
        (
            "tests.v23.test_v235_versioned_runtime.V235VersionBindingTests."
            "test_invalid_bindings_and_paths_are_zero_mutation"
        ),
        (
            "tests.v23.test_v235_versioned_runtime.V235VersionBindingTests."
            "test_symlink_contract_and_archive_parent_are_rejected"
        ),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        fail(
            "V2.35 active-scan authorization or version/archive path gate failed: "
            + result.stdout
            + result.stderr
        )


def check_public_sources_do_not_embed_current_home() -> None:
    home = str(Path.home())
    roots = (
        ROOT / "benchmarks",
        ROOT / "docs",
        ROOT / "examples",
        ROOT / "prompts",
        ROOT / "references",
        ROOT / "subagents",
    )
    leaked: list[str] = []
    for base in roots:
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if home in text:
                leaked.append(path.relative_to(ROOT).as_posix())
    if leaked:
        fail(f"public package sources embed the current home path: {leaked}")


def main() -> None:
    check_capabilities()
    check_redaction()
    check_prompt_injection()
    check_v235_security_and_path_gates()
    check_public_sources_do_not_embed_current_home()
    print(
        "Capability, security data, V2.35 active-scan authorization, and path gates passed."
    )


if __name__ == "__main__":
    main()
