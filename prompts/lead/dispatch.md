# Goal Teams Dispatch

启动 worker subagents 或编辑实现文件前，总是展示 `Teams 规划表`。直接执行时标题用 `执行计划（已按用户要求直接执行）`。

四列合并展示格式：

| 成员 / Skill(Subagent) | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Skill/Subagent：`goal_backend` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行，前置任务 Backend Architecture Design + TDD 单测用例<br>锁定范围：`src/api/wiki/` | 交付物：后端实现（`backend_implementation`）<br>完成标准：单测和 API 集成测试通过<br>Harness：TDD 单测 + Python/pytest API 集成测试<br>文档/TaskList：Backend Architecture Design + TaskList.md | 测试 Owner：单测执行-WIKI 列表TDD运行；API集成测试-WIKI 列表执行<br>校验者：评审-WIKI 列表代码审查 |

按需展示：

- 环境和指南表：AGENTS/agent、CLAUDE、输出目录、`index.md`、`memory.md`、版本子目录、`TaskList.md`。
- SPEC 准备度表。
- Harness 准备度表。
- Benchmark 适用性表。
- Lead LOOP 适用性和 Loop Gate 表。
- 风险和审批表。
- 执行进度表。
- 独立校验表。

并发规则：

- 大多数项目使用 3-6 个并发成员。
- 按交付物、版本 lane、模块或评审视角并行。
- 共享核心模块和高风险改动串行。
- 每个交付物或 lane 只有一个 Owner。
- 每个交接物必须使用 `prompts/packets/handoff-artifacts.md` 中的类型和状态字段。
- 派发前，Lead 必须确认版本子目录 TaskList 已写入交接物 Owner subagent、validator subagent、状态、Harness 和证据路径占位。
- 每个实现成员必须有 `locked_scope`。
- 验证必须由独立测试成员或 testing skill/subagent 负责。
- `max_depth = 1`，成员不能创建嵌套团队。

成员派发：

- 每个成员都接收 Member Goal Packet，并执行 `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`。
- 每个成员都必须在执行过程中更新自己负责的 TaskList 交接物行，至少更新 `handoff_status`、`independent_check_status`、证据路径、阻塞或延期原因。
- 分析/评审成员可只读；实现成员必须有明确 `locked_scope`。
- 成员不能自我批准生成的文档、代码或测试。
- Lead 负责路由阻塞、跨成员问题、共享核心改动、高风险审批和整合。
- Lead 每轮整合后必须记录 `Loop Decision`；如果决策为 `continue_same_scope` 或 `replan`，续跑计划也必须展示为四列 `Teams 规划表`。

使用完整派发协议时读取 `references/subagent-dispatch-protocol.md`。
