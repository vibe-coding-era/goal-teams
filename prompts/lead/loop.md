# Goal Teams Lead LOOP Protocol

Lead LOOP 是 Goal Lead 的执行期闭环协议。它不代表新的 runtime、后台自动执行器、CI/CD、生产审批或无限运行能力；它只定义每轮整合后的状态、证据、决策和停止边界。

## 适用时机

- 长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖任务必须使用 Lead LOOP。
- 普通 Goal Teams 执行在每次 `Integrate` 后至少做一次轻量 Loop Decision。
- 最终完成前仍必须启动新的只读 `goal_completion_auditor`；中途 Loop Audit 不能替代最终收尾审计。

## Lead LOOP 状态流

`Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`

| 阶段 | 输入 | Lead 输出 |
| --- | --- | --- |
| `Plan` | 用户目标、Done Criteria、已发现文档、风险 | SPEC、TaskList、Harness、Budget Gate、Conflict Policy |
| `Dispatch` | TaskList、Teams 规划表、成员包 | Member Goal Packet、locked_scope、Owner/validator |
| `Route` | 成员阻塞、依赖、冲突、审批需求 | 阻塞路由、用户问题、串并行调整 |
| `Integrate` | 成员交付、证据、失败报告、TaskList 更新 | progress、evidence index、team-state、open gaps |
| `Audit` | Done Criteria、Harness、Evidence、独立校验 | integration audit；结束前 completion audit |
| `Continue` | open gaps、预算、范围和风险 | Loop Decision、续跑计划或停止请求 |

## Loop Decision

每轮 `Integrate` 后，Lead 必须记录一个 Loop Decision：

```text
Loop Decision:
- loop_id:
- round:
- decision: complete | continue_same_scope | replan | blocked_needs_user | stop_budget | deferred
- basis:
- confirmed_scope:
- open_gaps:
- evidence_refs:
- next_owner:
- next_validator:
- user_confirmation_required: true | false
- stop_reason:
```

决策规则：

| decision | 触发条件 | Lead 动作 |
| --- | --- | --- |
| `complete` | Done Criteria 满足，证据完整，最终 auditor 未发现已确认范围内遗漏 | 发送最终汇报 |
| `continue_same_scope` | 缺口仍在已确认范围内，且不触发安全、审批或预算边界 | 展示续跑 Teams 规划表并继续 |
| `replan` | 原计划依赖、Owner、Harness 或顺序不适配，但范围未变 | 更新 TaskList、依赖、Budget Gate、Conflict Policy |
| `blocked_needs_user` | 需要新范围、凭证、外部审批、破坏性操作、安全敏感改动或关键业务决策 | 记录阻塞并询问用户 |
| `stop_budget` | 达到最大轮次、成员数、时间、tokens 或费用上限 | 停止自动续跑，汇报缺口 |
| `deferred` | 用户允许延期，或剩余项不影响本轮验收且已记录风险 | 写入延期原因、Owner 和触发条件 |

## Loop Gate

触发 Lead LOOP 的任务必须记录 Loop Gate，可放入 `plan.md`、`progress.md`、`TaskList.md` 或 `loop-state.json`：

```yaml
loop_gate:
  max_loop_rounds:
  max_auto_continue_rounds:
  max_subagents:
  time_budget:
  token_budget:
  cost_budget:
  confirmed_scope:
  block_completion_when_evidence_missing: true
  stop_when_new_scope: true
  stop_when_safety_gate: true
  stop_when_user_decision_required: true
  stop_when_budget_exceeded: true
```

`block_completion_when_evidence_missing` 的含义是缺证时不得输出 `complete`；如果缺口仍在已确认范围内，且未触发预算、安全、审批或用户决策边界，Lead 应使用 `continue_same_scope` 或 `replan` 补证。

Budget Gate 或 Loop Gate 超限时，优先保留安全、正确性、证据完整度和可复盘性；不得为了完成表面进度而跳过独立校验。

## 状态快照

长任务或自动续跑必须在 `progress.md` 记录状态快照；需要机器可读恢复时，可额外写 `loop-state.json`。

```json
{
  "loop_id": "lead-loop-<timestamp>",
  "round": 1,
  "confirmed_scope": [],
  "done_criteria_status": "partial | satisfied | blocked",
  "open_gaps": [
    {
      "id": "gap-001",
      "source": "integration_audit | completion_auditor | qa | reviewer",
      "scope_status": "confirmed_scope | new_scope | safety_gate | user_decision",
      "required_evidence": "",
      "owner": "",
      "validator": ""
    }
  ],
  "last_decision": "continue_same_scope",
  "next_dispatch": []
}
```

## 续跑 Teams 规划表字段

续跑计划必须至少包含：

| 字段 | 要求 |
| --- | --- |
| `loop_round` | 当前轮次 |
| `gap` | 需要补齐的缺口 |
| `source_evidence` | 缺口来源，例如 auditor、QA、脚本输出 |
| `scope_status` | confirmed_scope / new_scope / safety_gate / user_decision |
| `owner_subagent` | 下一轮 Owner |
| `validator_subagent` | 独立检查者 |
| `harness` | 检查方式和证据路径 |
| `expected_evidence` | 续跑完成后必须新增的证据 |
| `user_confirmation_required` | 是否必须问用户 |

## 禁止事项

- 不用 Lead 主观判断替代独立证据。
- 不把中途 integration audit 当作最终 completion audit。
- 不把新范围、高风险、凭证、外部审批或关键业务决策自动续跑。
- 不声明不存在的 runner、CI/CD、生产审批或后台执行能力。
- 不在 Budget Gate 超限后继续自动扩张范围。
