# Goal Teams Audit

每次 Goal Teams 运行都有最终审计门：

1. Lead 认为所有认领工作完成、延期或阻塞后，启动新的只读 `goal_completion_auditor`。
2. Auditor 检查 tasklist、progress、验收证据、测试结果、SPEC/docs、独立校验记录、未解决阻塞和剩余风险。
3. Auditor 必须按 `prompts/packets/handoff-artifacts.md` 核对每个交接物是否有 Owner subagent、validator subagent、`handoff_status`、`independent_check_status`、Harness、证据路径和阻塞/延期原因。
4. 如果没有未完成工作，Lead 可以发送最终完成回复。
5. 如果未完成工作仍在已确认目标范围内，Lead 必须创建续跑任务并自动启动下一轮 Goal Teams；只展示续跑 `Teams 规划表`，不再要求用户确认。
6. 如果用户最初授权直接执行，同一确认范围内的续跑继续直接执行；触及安全边界或新范围时才问用户。
7. 如果审计发现新范围、破坏性或安全敏感工作、缺少凭证、外部审批或未解决用户决策，记录阻塞并询问用户，不自动续跑。
8. 重复审计和续跑，直到 auditor 报告完成，或只剩有记录的阻塞/延期工作。

证据不足不能完成：缺少 E2E、缺少像素级对比、只有实现者自测、缺少独立校验、交接物缺少 tasklist 状态或证据、生产流缺少审批/回滚/监控证据时，QA、Reviewer 或 Completion Auditor 必须打回。
