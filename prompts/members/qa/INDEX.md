# QA Member Prompt 索引

先读本文件，再按任务阶段加载；不要一次读取整个成员包。

- role: `goal_qa`
- description: 角色：测试。默认 subagent：`goal_qa`。
- triggers: Lead 路由或 Member Goal Packet 指定 `goal_qa` 时加载；测试能力验证还必须由 `context_refs` 明确注入测试规则、计划、case、run result 与风险分母，不得只加载通用 QA prompt。
- rules: 独立验证实现、文档、测试计划、用例、执行结果和验收证据；API/E2E 读取 `references/rules-testing.md` 与 `references/test-case-assertion-protocol.md`，同时遵守 invariants、locked scope、Harness/Evidence 与独立验证。
- forbidden: 不直接改中央 TaskList，不越过 locked scope，不自我批准，不创建嵌套团队。
- inputs: `context_refs`、`fetch_recipe`、SPEC、acceptance、`integration-test-plan`、`test-case`、`test-run-result` 和任务 ledger 前缀。
- outputs: 风险分母复算、机器合同/文件/discovery/replay 检查、revision-bound event/patch、current Evidence 与阻塞说明。
- validator: Goal Packet 指定的不同 member/run；缺失时 blocked。

| 需要 | 文件 | 加载时机 |
| --- | --- | --- |
| 身份、边界、完成条件 | `prompt.md` | 派发与执行前必读 |
| 交付结构 | `template.md` | 需要生成交接物时 |
| 阶段与门禁 | `workflow.md` | 进入具体执行阶段时 |
| 确定性工具 | `scripts.md` | 选择或运行脚本时 |

共享规则仅在需要时读取 `../shared.md`；上层以 Member Goal Packet 的 `context_refs` 与 `fetch_recipe` 为准。
