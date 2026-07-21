# Goal Teams Lead LOOP Protocol

Lead LOOP 是 Goal Lead 的执行期闭环协议。它不代表新的 runtime、后台自动执行器、CI/CD、生产审批或无限运行能力；它只定义每轮整合后的状态、证据、决策和停止边界。

## Core V2.5 内环

实现类/长任务的每轮内环固定为 `Gather → Reason → Act → Verify → Repeat`，不可跳过 `Reason` 直接写实现。进入 `Act` 前，Lead 必须确认 route 派生的 required gates：

- scoped contract current，并有当前验证方式；
- Lite/Standard 只要求命中的 Architecture/Environment/independent test gates；
- Full/Regulated 的 Architecture 已 accepted、`development_environment_check=ready` 且独立测试已写入；
- iteration/attempt/intent/expected constraints/action scope 已按当前项目恢复合同持久化。

固定 52 条断言、四文件、第 9/11 轮、四维评分、GTLOG、prompt identity/Cache Evidence/OKF gate、V2.42 发行状态机和公开归档只在 `policy_profile=goal-teams-self-release-v2.42` 时读取 `references/profiles/goal-teams-self-release-v2.42.md`。`goal-teams-self-release-v2.41`、`goal-teams-self-release-v2.40`、`goal-teams-self-release-v2.39` 与 `goal-teams-self-release-v2.38` Profile 只用于历史 replay；普通项目不得加载这些专项门禁。

## 适用时机

- 长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖任务必须使用 Lead LOOP。
- 普通 Goal Teams 执行在每次 `Integrate` 后至少做一次轻量 Loop Decision。
- 最终完成前仍必须启动新的只读 `goal_completion_auditor`；中途 Loop Audit 不能替代最终收尾审计。

V2.35 专家改进 loop 的状态只允许 `proposed → reviewed → applied → verified` 或 `reviewed → reverted`。专家只提交 proposal；Lead 另派 applied 的实现 run，verified 必须由不同 run 绑定 current regression + holdout Evidence。专家不能派生 nested team。

Full/Regulated release loop 的顺序为 contract review → Architecture → Environment → tests/red → implementation → green/full → release readiness → release Evidence → post-release verification → graph-external Completion Audit；Audit 自引用返回 `E_AUDIT_SELF_REFERENCE`。

## Lead LOOP 状态流

`Plan -> Dispatch -> Route -> Integrate -> Audit -> Continue`

| 阶段 | 输入 | Lead 输出 |
| --- | --- | --- |
| `Plan` | 用户目标、Done Criteria、已发现文档、风险 | SPEC、TaskList、Harness、Budget Gate、Conflict Policy |
| `Dispatch` | TaskList、Teams 规划表、成员包 | Member Goal Packet、locked_scope、Owner/validator |
| `Route` | 成员阻塞、依赖、冲突、审批需求 | 阻塞路由、用户问题、串并行调整 |
| `Integrate` | 成员交付、Evidence、失败报告、revision-bound events | ledger merge、TaskList projection、progress、Evidence index、open gaps |
| `Audit` | Done Criteria、Harness、Evidence、独立校验 | integration audit；结束前 completion audit |
| `Continue` | open gaps、预算、范围和风险 | Loop Decision、续跑计划或停止请求 |

## Loop Decision

每轮 `Integrate` 后，Lead 必须记录一个 Loop Decision：

```text
Loop Decision:
- loop_id:
- round:
- loop_decision: continue | replan | stop
- run_outcome: achieved | partial | blocked | aborted
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
| `continue` | 缺口仍在已确认范围内，且不触发安全、审批或预算边界 | 展示续跑 Teams 规划表并继续 |
| `replan` | 原计划依赖、Owner、Harness 或顺序不适配，但范围未变 | 写入修订事件，更新依赖、Budget Gate、Conflict Policy，并由 reducer 重建 TaskList |
| `stop` | 已完成、需用户输入、预算耗尽、延期或中止 | 分别记录 `run_outcome` 与 `stop_reason`；只有完成谓词和审计通过时才可 `achieved` |

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

`block_completion_when_evidence_missing` 的含义是缺证时不得输出 `audit_state=passed` 或 `run_outcome=achieved`；如果缺口仍在已确认范围内，且未触发预算、安全、审批或用户决策边界，Lead 应使用 `loop_decision=continue|replan` 补证。

Budget Gate 或 Loop Gate 超限时，优先保留安全、正确性、证据完整度和可复盘性；不得为了完成表面进度而跳过独立校验。

## 状态快照

长任务或自动续跑必须在 `progress.md` 记录状态快照。V2.34 可恢复运行必须使用 `feature_list.json` / `progress.md` / `contract.md` / `log.md` 四文件 bundle；`loop-state.json` 只是旧版可选输入，不能作为 V2.34 第五个事实源。

```json
{
  "schema_version": "goal-teams-v2.3",
  "loop_id": "lead-loop-<timestamp>",
  "round": 1,
  "artifact_version": "<artifact_version>",
  "workspace_commit": "<git commit or unavailable>",
  "ledger_revision": 0,
  "attempt_id": "<attempt_id>",
  "last_event_id": "<non-empty event_id; bootstrap must first append an event>",
  "updated_at": "<ISO 8601>",
  "active_member_runs": [],
  "confirmed_scope": [],
  "run_outcome": "partial",
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
  "loop_decision": "continue",
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
| `owner_member_id` + `owner_run_id` | 下一轮具体 Owner 身份；必须绑定 identity registry |
| `validator_member_id` + `validator_run_id` | 具体独立检查者身份；不得等于 Owner run |
| `harness` | 检查方式和证据路径 |
| `expected_evidence` | 续跑完成后必须新增的证据 |
| `user_confirmation_required` | 是否必须问用户 |

## 禁止事项

- 不用 Lead 主观判断替代独立证据。
- 不把中途 integration audit 当作最终 completion audit。
- 不把新范围、高风险、凭证、外部审批或关键业务决策自动续跑。
- 不声明不存在的 runner、CI/CD、生产审批或后台执行能力。
- 不在 Budget Gate 超限后继续自动扩张范围。
