---
type: Goal Teams Loop Rules
title: Goal Teams Loop Rules
description: Lead LOOP、Loop Decision、Loop Gate、Budget Gate、Conflict Policy 和自动续跑边界。
tags: [goal-teams, loop, budget, audit, okf]
timestamp: 2026-07-09T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Loop Rules

只在任务涉及长任务、自动续跑、生产流、Benchmark、浏览器 E2E、像素对比、跨成员依赖、预算约束或中途审计时读取本文件。普通 Goal Teams 执行在每次整合后仍至少记录轻量 `Loop Decision`。

## 必读文件

- `prompts/lead/loop.md`
- `prompts/lead/audit.md`
- `prompts/lead/completion.md`
- `references/goal-teams-scripted-tooling.md`
- 生产流读取 `references/goal-teams-production-pipeline.md`
- Benchmark 读取 `benchmarks/README.md` 和对应任务包

## 触发条件

出现以下任一情况，Plan 必须写 `Loop Gate`：

- 预计超过 4 个 subagents。
- 需要自动续跑。
- 涉及生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖。
- 用户给出时间、tokens 或费用限制。
- 存在共享核心模块、高风险改动、认证、支付、迁移、安全敏感代码或大范围 API 合同变更。

## Loop Decision

每轮 `Integrate` 后记录一个决策：

```text
complete | continue_same_scope | replan | blocked_needs_user | stop_budget | deferred
```

| decision | 动作 |
| --- | --- |
| `complete` | Done Criteria 满足，证据完整，最终 auditor 未发现已确认范围内遗漏 |
| `continue_same_scope` | 缺口仍在已确认范围内，且不触发安全、审批或预算边界；展示续跑 Teams 规划表并继续 |
| `replan` | 原计划依赖、Owner、Harness 或顺序不适配；更新 TaskList、依赖、Budget Gate 和 Conflict Policy |
| `blocked_needs_user` | 需要新范围、凭证、外部审批、破坏性操作、安全敏感改动或关键业务决策；记录阻塞并询问用户 |
| `stop_budget` | 达到最大轮次、成员数、时间、tokens 或费用上限；停止自动续跑并汇报缺口 |
| `deferred` | 用户允许延期，或剩余项不影响本轮验收且已记录风险、Owner 和触发条件 |

## 自动续跑边界

- 自动续跑只能处理已确认范围内的缺口。
- 新范围、高风险、凭证、外部审批、安全敏感改动、关键业务决策或 Budget Gate 超限必须停下问用户或记录阻塞。
- 所有续跑任务必须有 Owner、validator、Harness、预期新增证据和停止条件。
- 中途 Loop Audit 不能替代最终 `goal_completion_auditor`。
- Lead LOOP 不代表新的 runtime、后台自动执行器、CI/CD、生产审批或无限运行能力。

## 状态快照

长任务或自动续跑必须在 `progress.md` 记录状态快照；需要机器可读恢复时可额外写 `loop-state.json`。快照至少记录 loop id、轮次、已确认范围、open gaps、最后决策、下一轮 Owner、validator、证据路径和停止边界。
