# Goal Teams Dispatch

启动 worker subagents 前，总是展示 `Teams 规划表`。其前置条件是需求卡已记录 `flow_selection=small|medium|large` 且 `flow_confirmation=confirmed`；`awaiting_confirmation` 或 `awaiting_customization` 时不得启动 worker、编辑实现文件或生成该表。`skipped`（用户选 `5` / 直接改）时不创建该表、不派发成员，Goal Lead 仅可在当前明确范围内直接修改并运行适用轻量验证；安全、授权和上层门禁仍然有效。直接执行时标题用 `执行计划（已按用户要求直接执行）`，但不能绕过流程澄清确认。

四列合并展示格式：

| 成员 / Skill(Subagent) | 任务范围 | 交付与标准 | 验证安排 |
| --- | --- | --- | --- |
| 成员：后端-WIKI 列表后端开发<br>Agent type：`goal_backend`<br>Member/Run：`MEMBER-BACKEND-WIKI` / `RUN-BACKEND-WIKI-001` | 目标切片：WIKI 列表 API<br>认领任务：GT-003<br>Workflow：串行，前置任务 Backend Architecture Design + TDD 单测用例<br>锁定范围：`src/api/wiki/` | 交付物：后端实现（`backend_implementation`）<br>完成标准：单测和 API 集成测试通过<br>Harness：TDD 单测 + Python/pytest API 集成测试<br>Ledger event：Architecture Design + implementation refs | 测试 Owner：单测执行-WIKI 列表TDD运行；API集成测试-WIKI 列表执行<br>Validator run：`RUN-REVIEW-WIKI-CODE-001` |

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
- 派发前，Lead 必须确认 ledger 已登记交接物、具体 Owner/Validator、状态、Harness 和 Evidence 占位，并由 reducer 生成版本子目录 TaskList。
- 每个实现成员必须有 `locked_scope`。
- 验证必须由独立测试成员或 testing skill/subagent 负责。
- `max_depth = 1`，成员不能创建嵌套团队。
- V2.35 专家另固定 `sandbox_mode=read-only`、`coordination_depth=1`、`can_spawn_subagents=false`、`can_dispatch=false`、`dispatch_owner_agent_type=goal_lead`、`handoff_mode=proposal_only`。

成员派发：

- 每个成员都接收 Member Goal Packet，并执行 `Load -> Plan -> Implement -> Test -> Document -> Review -> Continue`。
- 每个成员必须提交结构化 event/patch；只有 ledger owner 合并后才能由 reducer 更新 TaskList 投影视图。
- 分析/评审成员可只读；实现成员必须有明确 `locked_scope`。
- 成员不能自我批准生成的文档、代码或测试。
- Lead 负责路由阻塞、跨成员问题、共享核心改动、高风险审批和整合。
- 专家只提交 proposal/dispatch request；Lead 校验 proposal hash、scope、capability、预算、冲突、授权和 review class 后，才在 ledger 创建实现/测试任务。专家请求不得当作已派发或执行 Evidence。
- Lead 每轮整合后必须记录 `loop_decision=continue|replan|stop` 与正交 `run_outcome`；如果决策为 continue 或 replan，续跑计划也必须展示为四列 Teams 规划表。

使用完整派发协议时读取 `references/subagent-dispatch-protocol.md`。
