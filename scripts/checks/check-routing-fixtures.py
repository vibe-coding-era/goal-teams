#!/usr/bin/env python3
"""Validate V2.3 routing plus current preview/reference policy gates."""

from __future__ import annotations
import json, subprocess, sys, tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "v23" / "goalteams_v23.py"

@dataclass(frozen=True)
class RouteFixture:
    name: str
    features: dict[str, object]
    expected_profile: str
    expected_refs: tuple[str, ...]
    forbidden_refs: tuple[str, ...] = ()
    expected_mode: str = "execute"


@dataclass(frozen=True)
class PolicyFixture:
    name: str
    command: str
    request: dict[str, object]
    expected: dict[str, object]

FIXTURES = (
    RouteFixture("plan-preview-lite", {"risk":"low", "plan_preview": True}, "lite", ("RULES.md",), ("references/rules-ui.md", "references/rules-testing.md"), "plan_preview"),
    RouteFixture("backend-cli-full", {"backend": True, "tests": True, "risk":"medium"}, "full", ("references/rules-testing.md",), ("references/rules-ui.md",)),
    RouteFixture("original-ui-full-no-pixel", {"ui": True, "replica": False}, "full", ("references/rules-ui.md",), ("references/ui-e2e-pixel-protocol.md",)),
    RouteFixture("ui-replica-full-pixel", {"ui": True, "replica": True}, "full", ("references/rules-ui.md", "references/ui-e2e-pixel-protocol.md"), ()),
    RouteFixture("long-running-full", {"long_running": True}, "full", ("references/rules-loop.md",), ("references/rules-ui.md",)),
    RouteFixture("external-write-regulated", {"external_write": True, "risk":"high"}, "regulated", ("references/dual-review-protocol.md",), ()),
    RouteFixture("standard-doc", {"risk":"medium", "standard": True}, "standard", ("RULES.md",), ("references/rules-ui.md", "references/rules-testing.md")),
)

POLICY_FIXTURES = (
    PolicyFixture(
        "preview-explicit-no-write",
        "plan-preview-policy",
        {"request_text": "只规划，不落盘"},
        {"plan_preview": True, "persistence": "forbidden", "reason": "explicit_planning_only_and_no_write"},
    ),
    PolicyFixture(
        "preview-plan-only-is-not-enough",
        "plan-preview-policy",
        {"request_text": "只规划"},
        {"plan_preview": False, "persistence": "required_or_unspecified", "reason": "explicit_pair_incomplete"},
    ),
    PolicyFixture(
        "preview-execution-overrides-no-write",
        "plan-preview-policy",
        {"request_text": "只规划，不落盘，然后一次完成"},
        {"plan_preview": False, "persistence": "required_or_unspecified", "reason": "execution_or_write_intent_present"},
    ),
    PolicyFixture(
        "missing-required-reference-is-blocked",
        "reference-policy",
        {
            "required_refs": ["RULES.md", "references/does-not-exist.md"],
            "triggered_conditional_refs": [],
            "optional_refs": [],
            "available_refs": ["RULES.md"],
            "low_risk": True,
            "acceptance_blocking": False,
            "independent_validation_required": False,
        },
        {"state": "blocked", "execution_mode": "blocked", "acceptance_allowed": False, "missing_required_refs": ["references/does-not-exist.md"]},
    ),
    PolicyFixture(
        "missing-triggered-reference-is-blocked",
        "reference-policy",
        {
            "required_refs": ["RULES.md"],
            "triggered_conditional_refs": ["references/does-not-exist.md"],
            "optional_refs": [],
            "available_refs": ["RULES.md"],
            "low_risk": True,
            "acceptance_blocking": False,
            "independent_validation_required": False,
        },
        {"state": "blocked", "execution_mode": "blocked", "acceptance_allowed": False, "missing_triggered_conditional_refs": ["references/does-not-exist.md"]},
    ),
    PolicyFixture(
        "missing-optional-reference-safe-single-agent",
        "reference-policy",
        {
            "required_refs": ["RULES.md"],
            "triggered_conditional_refs": [],
            "optional_refs": ["references/does-not-exist.md"],
            "available_refs": ["RULES.md"],
            "low_risk": True,
            "acceptance_blocking": False,
            "independent_validation_required": False,
        },
        {"state": "degraded", "execution_mode": "single_agent_degraded", "acceptance_allowed": False},
    ),
    PolicyFixture(
        "missing-optional-reference-required-validation-stays-blocked",
        "reference-policy",
        {
            "required_refs": ["RULES.md"],
            "triggered_conditional_refs": [],
            "optional_refs": ["references/does-not-exist.md"],
            "available_refs": ["RULES.md"],
            "low_risk": True,
            "acceptance_blocking": False,
            "independent_validation_required": True,
        },
        {"state": "degraded", "execution_mode": "blocked", "acceptance_allowed": False},
    ),
)

def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)

def run_route(features: dict[str, object]) -> dict[str, object]:
    return run_policy("route", features)["route"]


def run_policy(command: str, request: dict[str, object]) -> dict[str, object]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as fh:
        json.dump(request, fh)
        tmp = fh.name
    try:
        proc = subprocess.run([sys.executable, str(TOOL), command, tmp], cwd=ROOT, text=True, capture_output=True)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if proc.returncode != 0:
        fail(proc.stdout + proc.stderr)
    payload = json.loads(proc.stdout)
    return payload

def main() -> None:
    for fixture in FIXTURES:
        route = run_route(fixture.features)
        if route["profile"] != fixture.expected_profile:
            fail(f"{fixture.name}: profile {route['profile']} != {fixture.expected_profile}")
        if route.get("mode") != fixture.expected_mode:
            fail(f"{fixture.name}: mode {route.get('mode')!r} != {fixture.expected_mode!r}")
        if fixture.expected_mode == "plan_preview" and route.get("writes_created") is not False:
            fail(f"{fixture.name}: preview route must declare no writes")
        refs = set(route["rule_set"])
        for ref in fixture.expected_refs:
            if ref not in refs:
                fail(f"{fixture.name}: missing {ref}")
        for ref in fixture.forbidden_refs:
            if ref in refs:
                fail(f"{fixture.name}: unexpected {ref}")
    for fixture in POLICY_FIXTURES:
        payload = run_policy(fixture.command, fixture.request)
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            fail(f"{fixture.name}: {fixture.command} did not return a policy object")
        for key, expected in fixture.expected.items():
            if policy.get(key) != expected:
                fail(f"{fixture.name}: {key} {policy.get(key)!r} != {expected!r}")
    print(
        "Routing and current policy fixture validation passed for "
        f"{len(FIXTURES)} routes and {len(POLICY_FIXTURES)} policy scenarios."
    )

if __name__ == "__main__":
    main()
