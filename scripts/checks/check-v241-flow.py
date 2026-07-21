#!/usr/bin/env python3
"""Fail-closed checks for the V2.41 flow contract on the V2.42 runtime."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"[FAIL] missing required V2.42 file: {relative}")
    return path.read_text(encoding="utf-8")


def require_markers(relative: str, *markers: str) -> None:
    text = read(relative)
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"[FAIL] {relative} missing V2.42 marker: {marker}")


def main() -> None:
    if read("VERSION").strip() != "V2.42":
        raise SystemExit("[FAIL] VERSION must be V2.42")
    require_markers(
        "references/flow-clarification-protocol.md",
        "LLM 的判断是：你应该使用",
        "小迭代流程",
        "中迭代流程",
        "大迭代流程",
        "```mermaid",
        "确认前不得创建正式 Plan、Teams 表或派发 subagent",
        "直接改：不创建正式 Plan 或 Teams，只修改指定内容并完成适用的轻量验证",
    )
    require_markers(
        "references/project-flow-selection.md",
        "小型需求/BugFix",
        "中型项目",
        "大型系统",
        "直接改",
        "可能的 Subagent：0–1 个。",
        "可能的 Subagent：2–4 个。",
        "可能的 Subagent：5–8 个。",
        "选项 `1`、`2`、`3` 分别规范化为 `small`、`medium`、`large`",
    )
    require_markers(
        "references/agent-runtime-capability-contract.md",
        "Portable Core",
        "Runtime Capability Contract",
        "Codex Adapter",
        "identity_attestation",
        "不能声称全功能兼容",
    )
    require_markers(
        "prompts/lead/planning.md",
        "flow-clarification-protocol.md",
        "流程澄清已确认",
        "Development Configuration Plan",
        "Production Configuration Plan",
    )
    require_markers(
        "prompts/packets/handoff-artifacts.md",
        "environment_configuration_plan",
        "Development Configuration Plan",
        "Production Configuration Plan",
        "不代表部署授权",
    )
    require_markers(
        "prompts/packets/requirement-card.md",
        "流程澄清记录（Plan 前必填）",
        "确认状态",
        "不得生成正式 Plan、Teams 规划表或派发成员",
    )
    require_markers(
        "prompts/packets/team-plan-table.md",
        "flow_selection=small|medium|large",
        "flow_confirmation=confirmed",
        "不创建 Teams 规划表、不派发成员",
    )
    require_markers(
        "SKILL.md",
        "不得向用户粘贴、复述或逐条解释 `RULES.md`",
        "文件作用",
        "输入/输出格式",
        "规模与大小",
        "为避免误用流程，请确认：",
        "references/project-flow-selection.md",
        "1=小型需求/BugFix",
        "5=直接改",
    )
    require_markers(
        "RULES.md",
        "V2.42 流程澄清与运行时兼容",
        "Proposal",
        "确认前",
        "生产环境规划不等于部署授权",
    )
    print("V2.42 flow clarification checks passed.")


if __name__ == "__main__":
    main()
