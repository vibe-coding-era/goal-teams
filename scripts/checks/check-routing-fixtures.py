#!/usr/bin/env python3
"""Validate Goal Teams progressive-loading routes against scenario fixtures."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RouteFixture:
    name: str
    prompt: str
    row_pattern: str
    expected_refs: tuple[str, ...]
    forbidden_refs: tuple[str, ...] = ()


FIXTURES = (
    RouteFixture(
        name="backend-cli",
        prompt="Use $goal-teams。请直接执行：为本地 CLI 增加后端 API 参数解析、TDD 单测和 API 集成测试。",
        row_pattern="后端、API、TDD 或测试编排",
        expected_refs=(
            "references/rules-testing.md",
            "prompts/members/backend/prompt.md",
            "prompts/members/unit-test-designer/prompt.md",
            "prompts/members/api-integration-test-runner/prompt.md",
        ),
        forbidden_refs=(
            "references/rules-ui.md",
            "references/ui-visual-contract-protocol.md",
            "references/ui-e2e-pixel-protocol.md",
        ),
    ),
    RouteFixture(
        name="ui-replica",
        prompt="Use $goal-teams。请复刻这个管理后台列表页，要求截图对齐、组件库记录、E2E 和像素级对比。",
        row_pattern="UI 页面、复刻、截图或前端交互",
        expected_refs=(
            "references/rules-ui.md",
            "references/ui-visual-contract-protocol.md",
            "references/ui-e2e-pixel-protocol.md",
            "prompts/packets/page-spec-card.md",
            "scripts/harness/pixel-diff.py",
        ),
        forbidden_refs=("references/rules-loop.md",),
    ),
    RouteFixture(
        name="long-running-loop",
        prompt="Use $goal-teams。请直接执行长任务续跑：多成员并行补齐缺失证据，记录 Loop Gate 和预算停止边界。",
        row_pattern="Lead LOOP、自动续跑和中途审计",
        expected_refs=(
            "references/rules-loop.md",
            "prompts/lead/loop.md",
            "prompts/lead/audit.md",
            "prompts/packets/team-plan-table.md",
        ),
        forbidden_refs=("references/rules-ui.md",),
    ),
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    sys.exit(1)


def load_route_rows() -> dict[str, str]:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^## 渐进式加载\n(?P<section>.*?)(?:\n## |\Z)", skill, flags=re.S | re.M)
    if not match:
        fail("SKILL.md missing progressive-loading section")
    rows: dict[str, str] = {}
    for line in match.group("section").splitlines():
        if not line.startswith("| ") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2 or cells[0] == "场景":
            continue
        rows[cells[0]] = cells[1]
    return rows


def main() -> None:
    rows = load_route_rows()
    for fixture in FIXTURES:
        matches = [content for label, content in rows.items() if fixture.row_pattern in label]
        if len(matches) != 1:
            fail(f"{fixture.name}: expected one route row matching {fixture.row_pattern!r}, got {len(matches)}")
        content = matches[0]
        for ref in fixture.expected_refs:
            if ref not in content:
                fail(f"{fixture.name}: route row missing expected reference {ref}")
        for ref in fixture.forbidden_refs:
            if ref in content:
                fail(f"{fixture.name}: route row unexpectedly includes {ref}")
    print(f"Routing fixture validation passed for {len(FIXTURES)} scenarios.")


if __name__ == "__main__":
    main()
