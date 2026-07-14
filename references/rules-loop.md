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

## Core V2.5 LOOP 契约

通用执行内环为 `Gather → Reason → Act → Verify → Repeat`。`Gather` 只收集当前契约、图和 Evidence；`Reason` 写出可测试断言、预期结果与 action scope；`Act` 只执行已过门动作；`Verify` 产生 current Evidence；`Repeat` 按 current gaps 决定继续、重规划或停止。不可幂等的外部动作必须先持久化 intent、预期副作用和授权边界。

固定 52 条断言、第 9/11 轮、四文件恢复 bundle、四维评分、prompt identity/Cache Evidence/OKF gate、V2.40 发行状态机与公开归档只属于当前 `goal-teams-self-release-v2.40`。只有路由结果明确包含该 `policy_profile` 时才加载 `references/profiles/goal-teams-self-release-v2.40.md`；V2.39/V2.38 Profile 只用于历史 replay，普通任务不得从本文件推导这些专项门禁。

### Contract-first 与门禁顺序

1. 所有等级都先冻结 scoped contract、Required 标记、验证方式和安全解释；合同变化创建新 revision，并重跑受影响的 Evidence/Review。
2. `lite` 允许 Architecture、完整环境报告和独立测试为条件门，但必须有目标检查和 current Evidence；涉及用户可见行为时至少执行针对性验证。
3. `standard` 要求影响分析、当前环境预检、适用独立测试和独立 Review；合同/API/数据/跨模块边界变化时 Architecture 升为 required。
4. `full|regulated` 固定使用 `contract review → Architecture → Environment → independent tests/current TDD red → implementation → independent green/适用回归 → Completion Audit`。少任一 current binding 即 fail closed。
5. release task 额外要求发布 Evidence 与 post-release verification；Completion Audit 始终位于任务图外，不得成为 required/blocking task或被 required artifact/Evidence 自引用。

### 通用恢复与 bottleneck

- 长任务在 `progress.md` 或当前项目声明的 `loop-state.json` 记录 iteration、attempt、current contract、ledger checkpoint、open gaps、last decision 和 next owner；具体文件集、最大轮次和交付轮由 Plan/Loop Gate 定义。
- 状态 revision/digest/checkpoint 冲突时只能 `reconcile_required|blocked`，不得按 mtime、多数票或默认值继续不可幂等动作。
- 当前 bottleneck 只从阻断 required AC/feature 的 unresolved gaps 选择；每次 Verify 从 current graph 重算并记录选择依据。评分或旧快照不得覆盖失败 Evidence。
- 本协议只支持当前会话与磁盘恢复，不声明 daemon、后台 runner 或无限自动执行。

## 必读文件

- `prompts/lead/loop.md`
- `prompts/lead/audit.md`
- `prompts/lead/completion.md`
- `references/goal-teams-scripted-tooling.md`
- 当前路由为 `goal-teams-self-release-v2.40` 时读取 `references/profiles/goal-teams-self-release-v2.40.md`；V2.39/V2.38 Profile 只读 replay
- 生产流读取 `references/goal-teams-production-pipeline.md`
- Benchmark 读取 `benchmarks/README.md` 和对应任务包

## 触发条件

出现以下任一情况，Plan 必须写 `Loop Gate`：

- 预计超过 4 个 subagents。
- 需要自动续跑。
- 涉及生产流、Benchmark、浏览器 E2E、像素对比或跨成员依赖。
- 用户给出时间、tokens 或费用限制。
- 存在共享核心模块、高风险改动、认证、支付、迁移、安全敏感代码或大范围 API 合同变更。

Budget Gate 只使用当轮 agent 可见的 `subject_visible_telemetry`。runner 在 `turn.completed` 后取得的 `observer_telemetry` 只能用于事后 cache 分析，不得倒灌为当轮已知事实。telemetry 不可用时不得伪造 tokens/cost；Budget Gate 的机器回退值固定为 `telemetry_status=unavailable`、`budget_metric=round_time_member_file_size`，并记录 round time、成员数和文件规模。

## Loop Decision

每轮 `Integrate` 后记录一个决策：

```text
loop_decision: continue | replan | stop
run_outcome: achieved | partial | blocked | aborted
```

| decision | 动作 |
| --- | --- |
| `continue` | 缺口仍在已确认范围内，且不触发安全、审批或预算边界；展示续跑 Teams 规划表并继续 |
| `replan` | 原计划依赖、Owner、Harness 或顺序不适配；写入修订事件，更新依赖、Budget Gate、Conflict Policy，并由 reducer 重建 TaskList |
| `stop` | 循环停止；必须另写 `run_outcome` 和 `stop_reason=achieved | user_input_required | authorization_required | budget_exceeded | deferred | aborted`，不得把停止自动等同完成 |

## 自动续跑边界

- 自动续跑只能处理已确认范围内的缺口。
- 新范围、高风险、凭证、外部审批、安全敏感改动、关键业务决策或 Budget Gate 超限必须停下问用户或记录阻塞。
- 所有续跑任务必须有 Owner、validator、Harness、预期新增证据和停止条件。
- 中途 Loop Audit 不能替代最终 `goal_completion_auditor`。
- Lead LOOP 不代表新的 runtime、后台自动执行器、CI/CD、生产审批或无限运行能力。
- 四专家只提交 proposal/dispatch request，不能在自己的 loop 内派生实现团队。Lead 接受 proposal 后必须创建新的实现/测试 task/run；`proposed|reviewed|applied|verified|reverted` 任一转换都记录 actor run，verified 另需 current regression + holdout。

## 状态快照

长任务或自动续跑必须在 `progress.md` 记录状态快照；需要机器可读恢复时可额外写 `loop-state.json`。快照至少记录 loop id、轮次、已确认范围、open gaps、最后决策、下一轮 Owner、validator、证据路径和停止边界。
