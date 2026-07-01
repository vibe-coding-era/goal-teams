# Requirement Card Lead Rule

Plan 模式收到需求后，Goal Lead 必须先产出“需求卡片”，再进入完整 SPEC、tasklist 和 Teams 规划表。

## 定位

需求卡片是简洁方案，用来把最早期需求压缩成可讨论、可写入、可追溯的最小文档。它不替代 `Requirement Specification Card`、PRD、Architecture Design 或 test plan；后续需求分析师应以它作为输入继续展开。

默认写入路径：

```text
GoalTeamsWork-<project_version>/versions/<artifact_version>/spec/requirement-card.md
```

## 必填内容

- 核心目标：一句话说明这次真正要达成什么。
- 关键功能：列出本轮必须覆盖的功能点或交付面。
- 用户故事：用“作为...我想要...以便...”表达主要用户、能力和价值，至少覆盖核心用户路径。
- 功能验收标准：用可验证条目描述每个关键功能的通过条件，优先写成 Given/When/Then 或清晰的状态/行为/结果。
- 边界：写清非目标、暂不处理、禁止修改或只读范围。
- 约束：记录时间、版本、技术栈、权限、安全、成本、兼容性、上下文和运行环境限制。
- 风险：记录需求不清、验收不明、依赖缺失、并发冲突、验证成本、生产或安全风险。

## 生成规则

- 保持简洁，默认控制在一页以内；宁可写假设和待确认问题，也不要把不确定内容包装成事实。
- 能从仓库、历史文档或用户上下文推断的内容先写入卡片；高风险或业务关键决策保留待确认问题。
- 直接执行只跳过等待确认，不跳过需求卡片；卡片作为执行记录的一部分。
- 如果用户只要建议、不进入执行，也可以只写需求卡片和简短 Plan，不派发成员。
- 卡片写入后，在 Plan 中引用路径，并说明用户故事和功能验收标准如何流向 `Requirement Specification Card`、PRD、tasklist 和 Harness。
- 如果任务是 UI 页面、复刻、还原、截图对齐或前端交互页面，需求卡片后续必须流向 `page-spec-card.md`。
- 需求卡片不得代替页面规格卡；页面规格卡必须承接视觉契约、交互状态矩阵、Harness 和 Evidence。
- PRD 完成后，先生成或更新页面规格卡，再进入 HTML Prototype MOCK 或前端实现。
- 如果用户要求页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面，需求卡片必须记录组件库澄清状态；已提供组件库时写入 `memory.md`，缺失时列为待确认问题。
- 需求卡片必须采用 OKF Markdown 格式，遵守 `references/google-okf-bilingual-spec.md`。

## 质量检查

需求卡片完成前，检查：

- 是否同时覆盖“核心目标 / 关键功能 / 用户故事 / 功能验收标准 / 边界 / 约束 / 风险”。
- 是否能直接转成 Done Criteria 和 tasklist。
- UI/复刻/前端交互任务是否明确写入 `page-spec-card.md` 的后续流向。
- 页面原型任务是否已明确组件库名称、版本、URL 或 Git 仓库，或已列入待确认问题。
- 是否标明了需要用户确认的开放问题。
- 是否避免了承诺不存在的 runtime、测试、外部审批或生产能力。
