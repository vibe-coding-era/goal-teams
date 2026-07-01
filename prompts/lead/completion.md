# Goal Teams Completion

只有满足以下条件，Goal Team 才算完成：

- Done Criteria 已满足。
- 每个认领任务都是 `done`、`deferred` 或 `blocked`，且有原因。
- 每个认领任务都有 Harness 契约、验证证据或不适用说明。
- 每个交接物都已写入版本子目录 TaskList，且包含 Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness、证据路径或阻塞/延期原因。
- 每个交接物都有独立检查结果；Owner 不能自我批准。
- 如使用 Benchmark，相关任务的运行记录和失败分类已写入报告或 progress。
- 最终汇报包含每个任务或 subagent 的资源消耗列，格式为 `资源消耗（用户 / tokens / 费用）`；运行时没有返回 tokens 或费用时写 `未提供`。
- 新的 `goal_completion_auditor` 未发现已确认范围内的未完成工作，或剩余工作都有阻塞/延期说明。
- 必要测试已运行，或说明跳过原因和风险。
- 测试由独立成员、skill 或 subagent 执行，例外必须记录。
- 每个生成文档、代码变更和测试用例都有独立校验证据。
- TaskList 和必要文档已更新成员 Owner 与最终状态。
- Requirement Specification Card、PRD、Backend/Frontend Architecture Design、HTML Prototype、test plan、acceptance、TaskList 已完成或明确不适用。
- 输出目录、版本子目录、`index.md` 和 `memory.md` 已更新。
- 后端任务已有 Backend Architecture Design、独立 TDD 单测用例、独立单测执行证据、API 集成测试脚本和执行证据；API 集成测试默认 Python + pytest 或有替代说明。
- 前端任务已有独立 E2E 用例生成和独立 E2E 执行证据。
- 生成 Markdown 产物符合 Google OKF，至少包含可解析 frontmatter 和非空 `type`。
- 阻塞和剩余风险已记录。
- 如使用 runtime 文件，`team-state.json` 反映最终状态。
