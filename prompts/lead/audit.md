# Goal Teams Audit

每次 Goal Teams 运行都有最终审计门：

V2.1 起，Lead 每轮 `Integrate` 后先按 `prompts/lead/loop.md` 做轻量 integration audit 并记录 `Loop Decision`。integration audit 只能用于中途纠偏，不能替代本文件定义的最终收尾审计。

1. Lead 在候选收尾（所有可推进工作已处理，可能仍有 documented failed/blocked/deferred）时启动新的只读 `goal_completion_auditor`。Completion Audit 是被审任务图之外的最终门禁，不得注册成 required/acceptance-blocking task；只有 passed/achieved 分支要求 required task 全 accepted。
2. Auditor 检查 ledger/checkpoint、reducer TaskList、strict Evidence registry、full-object Traceability、Dual Review、测试结果、SPEC/docs、未解决阻塞和剩余风险。
3. Auditor 必须按 `prompts/packets/handoff-artifacts.md` 核对每个交接物是否有具体 Owner/Validator、`task_state`、`check_state`、Harness、当前 Evidence 和阻塞/延期原因，并验证 TaskList 与 ledger projection 一致。
4. 只读 Auditor 返回完整 Completion Audit JSON；Lead/ledger owner 原样持久化为 `audit/completion-audit.json` 并实际运行 V2.3 `completion-audit` validator。required/blocking task 或 Evidence 指向本次实际 audit 文件（含自定义文件名）时必须以 `E_AUDIT_SELF_REFERENCE` 失败。只有 validator 通过且重算得到 `audit_state=passed` / `run_outcome=achieved`，Lead 才可发送最终完成回复。
5. 如果未完成工作仍在已确认目标范围内，且未触发 Loop Gate 或 Budget Gate 停止条件，Lead 必须创建续跑任务并自动启动下一轮 Goal Teams；只展示续跑 `Teams 规划表`，不再要求用户确认。
6. 如果用户最初授权直接执行，同一确认范围内的续跑继续直接执行；触及安全边界、新范围、预算/轮次超限或用户决策时才问用户。
7. 如果审计发现新范围、破坏性或安全敏感工作、缺少凭证、外部审批、未解决用户决策、最大轮次/成员数/时间/tokens/费用超限，记录 `audit_state=blocked`、`loop_decision=stop`、合法 `run_outcome` 与结构化 stop_reason，不自动续跑。
8. 每次续跑前后更新 `progress.md` 或 `loop-state.json`，记录 loop round、缺口、Owner、validator、证据和停止条件。
9. 重复审计和续跑，直到 auditor 报告完成，或只剩有记录的阻塞/延期工作。

证据不足不能完成：缺少 E2E、缺少像素级对比、只有实现者自测、缺少独立校验、交接物缺少 tasklist 状态或证据、生产流缺少审批/回滚/监控证据时，QA、Reviewer 或 Completion Auditor 必须打回。

最终审计结论必须映射到 Lead LOOP：

| Auditor 输出 | Lead Loop Decision |
| --- | --- |
| `audit_state=passed` | `loop_decision=stop`, `run_outcome=achieved`, `stop_reason=achieved` |
| `audit_state=failed` 且缺口在确认范围 | `loop_decision=continue` 或 `replan`, `run_outcome=partial` |
| `audit_state=blocked` 且需要用户/授权 | `loop_decision=stop`, `run_outcome=blocked`, `stop_reason=user_input_required|authorization_required` |
| 预算或轮次超限 | `loop_decision=stop`, `run_outcome=partial`, `stop_reason=budget_exceeded` |
| 用户允许延期或非阻断延期项 | `loop_decision=stop`，完成谓词决定 `achieved` 或 `partial`，`stop_reason=deferred` |
