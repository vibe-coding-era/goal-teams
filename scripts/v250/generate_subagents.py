#!/usr/bin/env python3
"""Deterministically project the V2.65 common contract into subagent TOML files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
SUBAGENTS = ROOT / "subagents"
COMMON_PATH = SUBAGENTS / "common-developer-instructions.txt"

ROLE_FOCUS = {
    "goal-agent-product-manager.toml": "Agent 产品定义、Prompt/Context/Memory、工具与宿主能力边界；资料说明不能替代 runtime Evidence。",
    "goal-api-integration-test-designer.toml": "设计 API 集成 TestCase、风险分母、输入、步骤、期望与断言；不执行测试或修改实现。",
    "goal-api-integration-test-runner.toml": "执行冻结的 API 集成 TestCase，保留首错、环境与 TestRunReceipt；不修改用例或实现。",
    "goal-backend.toml": "后端领域、存储、API、CLI、MCP、迁移与集成实现；不越界编辑前端或自批测试。",
    "goal-completion-auditor.toml": "只读完成审计，逐项核对 Done Criteria、Evidence freshness 和正交状态；不得修复或自降标准。",
    "goal-docs.toml": "维护用户文档、SPEC、Doc Capsule 与版本投影；文档结论不得冒充工程或 runtime 验证。",
    "goal-e2e-test-designer.toml": "设计真实用户行为 E2E TestCase、状态矩阵与断言；不运行浏览器或修改产品。",
    "goal-e2e-test-runner.toml": "执行冻结 E2E TestCase，记录环境、截图/日志、首错与 TestRunReceipt；不改用例或实现。",
    "goal-frontend.toml": "前端组件、状态、交互、可访问性与 UI 实现；视觉/E2E 验证必须由独立成员执行。",
    "goal-performance.toml": "只读性能评估与可验证优化提案；未经 Lead 派发不得改代码、跑破坏性压测或自证收益。",
    "goal-product.toml": "需求、用户故事、功能验收、范围与优先级；不得把未验证假设写成已决定需求。",
    "goal-qa.toml": "独立 QA/验收，按 Harness 重算行为与覆盖；不得修复被测产物或以检查数量代替风险分母。",
    "goal-refactor.toml": "只读重构评估和最小任务补丁建议；未经 Lead 派发不得直接实现或改变行为合同。",
    "goal-release-engineer.toml": "以 environment_preflight 模式独立检查并复用开发环境；Release 模式只读复核最终 Evidence 并形成受控计划，不得自批。",
    "goal-requirements-analyst.toml": "澄清目标、约束、用户故事与可执行验收；只在缺失信息会改变结果时提出问题。",
    "goal-reviewer.toml": "独立代码/文档 review，聚焦正确性、回归、边界和证据；不得自修后自批。",
    "goal-security.toml": "只读安全评估和 Release security review；不得泄露凭证、修改实现或把结果回填为 S2 安全。",
    "goal-sqa.toml": "只读质量体系评估，检查门禁价值、状态诚实与证据链；不得增加无依据的流程负担。",
    "goal-unit-test-designer.toml": "先设计 immutable unit TestCase 和 TDD Red 断言；不修改实现或执行 Green。",
    "goal-unit-test-runner.toml": "执行冻结 unit TestCase，区分 tdd_red/tdd_green/verification 并记录 receipt；不改用例或实现。",
}


def common_text() -> str:
    return COMMON_PATH.read_text(encoding="utf-8").strip()


def render(path: Path, common: str) -> str:
    with path.open("rb") as handle:
        existing = tomllib.load(handle)
    focus = ROLE_FOCUS[path.name]
    common_digest = hashlib.sha256((common + "\n").encode("utf-8")).hexdigest()
    nicknames = json.dumps(existing.get("nickname_candidates", []), ensure_ascii=False)
    instructions = (
        f"{common}\n"
        f"角色职责：{focus}\n"
        "只加载 ACTIVE generation 中与 packet 命中的功能规则和合同；显式 Legacy Replay 除外。"
    )
    return (
        f'name = {json.dumps(existing["name"], ensure_ascii=False)}\n'
        f'description = {json.dumps(existing["description"], ensure_ascii=False)}\n'
        '# common_prefix_generation = "V2.65"\n'
        f'# common_prefix_sha256 = "{common_digest}"\n'
        'developer_instructions = """\n'
        f"{instructions}\n"
        '"""\n'
        f"nickname_candidates = {nicknames}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    common = common_text()
    drift: list[str] = []
    for filename in sorted(ROLE_FOCUS):
        path = SUBAGENTS / filename
        projected = render(path, common)
        if path.read_text(encoding="utf-8") != projected:
            drift.append(filename)
            if not args.check:
                path.write_text(projected, encoding="utf-8")
    if args.check and drift:
        print(json.dumps({"ok": False, "drift": drift}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "files": len(ROLE_FOCUS), "updated": drift}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
