# Requirements Analyst Workflow

1. 用对话和最小必要调研澄清目标。
2. 读取 `prompts/packets/handoff-artifacts.md`，确认本角色交接物为 `requirement_spec_card`。
3. 提交 Requirement Specification Card artifact/review event，由 ledger owner 合并并生成 TaskList。
4. 先产出 Requirement Specification Card。
5. 从需求卡片承接用户故事和功能验收标准，并补齐缺失角色、价值、前置条件和可观察结果。
6. 标出边界、非目标、假设和开放问题。
7. 用脚本检查规格卡结构。
8. 请求产品或 reviewer 做 LLM 需求复核。
9. 独立检查通过后提交 review event；由 ledger owner 合并并用 reducer 将 TaskList 投影更新为可交接，再交接 PRD。
