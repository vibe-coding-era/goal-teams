#!/usr/bin/env python3
"""Validate Goal Teams V2.3 routing through the real pure router."""

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

FIXTURES = (
    RouteFixture("plan-preview-lite", {"risk":"low", "plan_preview": True}, "lite", ("RULES.md",), ("references/rules-ui.md", "references/rules-testing.md")),
    RouteFixture("backend-cli-full", {"backend": True, "tests": True, "risk":"medium"}, "full", ("references/rules-testing.md",), ("references/rules-ui.md",)),
    RouteFixture("original-ui-full-no-pixel", {"ui": True, "replica": False}, "full", ("references/rules-ui.md",), ("references/ui-e2e-pixel-protocol.md",)),
    RouteFixture("ui-replica-full-pixel", {"ui": True, "replica": True}, "full", ("references/rules-ui.md", "references/ui-e2e-pixel-protocol.md"), ()),
    RouteFixture("long-running-full", {"long_running": True}, "full", ("references/rules-loop.md",), ("references/rules-ui.md",)),
    RouteFixture("external-write-regulated", {"external_write": True, "risk":"high"}, "regulated", ("references/dual-review-protocol.md",), ()),
    RouteFixture("standard-doc", {"risk":"medium", "standard": True}, "standard", ("RULES.md",), ("references/rules-ui.md", "references/rules-testing.md")),
)

def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)

def run_route(features: dict[str, object]) -> dict[str, object]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as fh:
        json.dump(features, fh)
        tmp = fh.name
    try:
        proc = subprocess.run([sys.executable, str(TOOL), "route", tmp], cwd=ROOT, text=True, capture_output=True)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if proc.returncode != 0:
        fail(proc.stdout + proc.stderr)
    payload = json.loads(proc.stdout)
    return payload["route"]

def main() -> None:
    for fixture in FIXTURES:
        route = run_route(fixture.features)
        if route["profile"] != fixture.expected_profile:
            fail(f"{fixture.name}: profile {route['profile']} != {fixture.expected_profile}")
        refs = set(route["rule_set"])
        for ref in fixture.expected_refs:
            if ref not in refs:
                fail(f"{fixture.name}: missing {ref}")
        for ref in fixture.forbidden_refs:
            if ref in refs:
                fail(f"{fixture.name}: unexpected {ref}")
    print(f"Routing fixture validation passed for {len(FIXTURES)} V2.3 scenarios.")

if __name__ == "__main__":
    main()
