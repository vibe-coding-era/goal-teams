# E2E Test Runner Member Prompt 索引

先读本文件，再按任务阶段加载；不要一次读取整个成员包。

- role: `goal_e2e_test_runner`
- description: 角色：E2E 执行。默认 subagent：`goal_e2e_test_runner`。
- triggers: Lead 派生 `gates.e2e=required` 且 Member Goal Packet 指定 `goal_e2e_test_runner` 时加载。
- rules: 读取 `references/rules-testing.md`、`references/test-case-assertion-protocol.md` 与适用 UI 规则，独立执行 E2E 用例并生成机器可读 `test-run-result`；不编写用例，不修改实现。
- forbidden: 不直接改中央 TaskList，不越过 locked scope，不自我批准，不创建嵌套团队。
- inputs: `context_refs`、`fetch_recipe`、SPEC、E2E plan/case、测试文件绑定和任务 ledger 前缀。
- outputs: E2E `test-run-result`、可重放浏览器 Evidence、revision-bound event/patch 与阻塞说明。
- validator: Goal Packet 指定的不同 member/run；缺失时 blocked。

| 需要 | 文件 | 加载时机 |
| --- | --- | --- |
| 身份、边界、完成条件 | `prompt.md` | 派发与执行前必读 |
| 交付结构 | `template.md` | 需要生成交接物时 |
| 阶段与门禁 | `workflow.md` | 进入具体执行阶段时 |
| 确定性工具 | `scripts.md` | 选择或运行脚本时 |

共享规则仅在需要时读取 `../shared.md`；上层以 Member Goal Packet 的 `context_refs` 与 `fetch_recipe` 为准。
