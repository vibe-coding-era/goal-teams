#!/usr/bin/env python3
"""Fail closed validation for the V2.48 Agent-development reference contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "references/agent-development-capability-manifest.json"
SCHEMA = ROOT / "schemas/v2.48/agent-development-capability.schema.json"
EXPECTED_ROLES = {
    "goal_agent_product_manager", "goal_product", "goal_backend", "goal_frontend", "goal_qa",
    "goal_unit_test_designer", "goal_unit_test_runner", "goal_api_integration_test_designer",
    "goal_api_integration_test_runner", "goal_e2e_test_designer", "goal_e2e_test_runner",
}
EXPECTED_PATTERNS = {"controlled_task_execution", "context_workflow_collaboration", "browser_desktop_execution"}
EXPECTED_ORDER = ["api_or_mcp", "playwright_or_dom", "browser", "computer_use"]
REFERENCE_FILES = {
    "INDEX.md", "platform-reference-matrix.md", "prompt-context-cache.md", "tool-browser-computer-use.md",
    "product-design-patterns.md", "architecture-patterns.md", "testing-evaluation-safety.md",
}


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def validate(path: Path = MANIFEST) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"manifest unreadable: {exc}")
    if data.get("schema_version") != "goal-teams-agent-development-v2.48":
        fail("schema_version mismatch")
    if data.get("product_version") != "V2.48":
        fail("product_version mismatch")
    allowed = {"schema_version", "product_version", "schema", "validator", "reference_index", "roles", "design_patterns", "tool_execution_order", "claim_states"}
    if set(data) != allowed:
        fail("manifest key set drift")
    if data.get("schema") != "schemas/v2.48/agent-development-capability.schema.json":
        fail("manifest schema path drift")
    if data.get("validator") != "scripts/checks/validate-v248-agent-development.py":
        fail("manifest validator path drift")
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"schema unreadable: {exc}")
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or set(required) != allowed:
        fail("schema required key denominator drift")
    if not isinstance(properties, dict) or set(properties) != allowed:
        fail("schema property denominator drift")
    if schema.get("schema_version") != data["schema_version"]:
        fail("schema version drift")
    if properties.get("schema", {}).get("const") != data["schema"]:
        fail("schema path contract drift")
    if properties.get("validator", {}).get("const") != data["validator"]:
        fail("schema validator contract drift")
    refs = ROOT / "references/agent-development"
    missing = sorted(name for name in REFERENCE_FILES if not (refs / name).is_file())
    if missing:
        fail(f"reference files missing: {missing}")
    if data.get("reference_index") != "references/agent-development/INDEX.md":
        fail("reference index drift")
    roles = data.get("roles")
    if not isinstance(roles, list) or {item.get("role_id") for item in roles if isinstance(item, dict)} != EXPECTED_ROLES:
        fail("role denominator drift")
    for item in roles:
        if not isinstance(item, dict) or set(item) != {"role_id", "member_package", "required_topics"}:
            fail("role shape drift")
        package = item["member_package"]
        if not isinstance(package, str) or not (ROOT / package / "prompt.md").is_file():
            fail(f"role package missing: {package!r}")
        if not isinstance(item["required_topics"], list) or not item["required_topics"]:
            fail("role topics missing")
    patterns = data.get("design_patterns")
    if not isinstance(patterns, list) or {item.get("pattern_id") for item in patterns if isinstance(item, dict)} != EXPECTED_PATTERNS:
        fail("design pattern denominator drift")
    for item in patterns:
        if not isinstance(item, dict) or set(item) != {"pattern_id", "modules", "non_goals"}:
            fail("design pattern shape drift")
        if not all(isinstance(item[key], list) and item[key] for key in ("modules", "non_goals")):
            fail("design pattern modules/non_goals missing")
    if data.get("tool_execution_order") != EXPECTED_ORDER:
        fail("tool execution order drift")
    required_states = {"documented", "contract_mapped_not_runtime_verified", "blocked", "not_run", "unknown", "not_found"}
    states = data.get("claim_states")
    if not isinstance(states, list) or not required_states <= set(states):
        fail("claim state coverage drift")
    matrix = (refs / "platform-reference-matrix.md").read_text(encoding="utf-8")
    for marker in ("`documented`", "`not_found`", "WorkBuddy", "Trae", "不得从产品名称推断"):
        if marker not in matrix:
            fail(f"platform matrix missing boundary marker: {marker}")
    tooling = (refs / "tool-browser-computer-use.md").read_text(encoding="utf-8")
    for marker in ("Playwright", "Computer Use", "安全拒绝是终态", "Input → Processing → Expected Output → Assertions"):
        if marker not in tooling:
            fail(f"tooling contract missing marker: {marker}")
    return {"ok": True, "role_count": len(roles), "pattern_count": len(patterns), "reference_count": len(REFERENCE_FILES)}


if __name__ == "__main__":
    selected = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else MANIFEST
    if len(sys.argv) > 2:
        fail("usage: validate-v248-agent-development.py [manifest.json]")
    print(json.dumps(validate(selected), ensure_ascii=False, sort_keys=True))
