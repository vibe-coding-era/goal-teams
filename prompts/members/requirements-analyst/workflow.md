# Requirements Analyst Workflow

1. 用对话和最小必要调研澄清目标。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `requirement_spec_card`。
3. 在 tasklist 中更新 Requirement Specification Card 的 Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness 和证据路径。
4. 先产出 Requirement Specification Card。
5. 从需求卡片承接用户故事和功能验收标准，并补齐缺失角色、价值、前置条件和可观察结果。
6. 标出边界、非目标、假设和开放问题。
7. 用脚本检查规格卡结构。
8. 请求产品或 reviewer 做 LLM 需求复核。
9. 独立检查通过后，把 tasklist 交接物状态更新为可交接，再交接 PRD。
