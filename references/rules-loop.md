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

## V2.34 可恢复 LOOP 契约

V2.34 的执行内环固定为 `Gather → Reason → Act → Verify → Repeat`。`Gather` 只收集当前契约、图和 Evidence；`Reason` 在磁盘上写出可测试断言、预期结果与 action scope；`Act` 只执行已持久化且过门的动作；`Verify` 由独立运行产生 current Evidence；`Repeat` 按 current gaps 重算 bottleneck 后决定下一轮。任一阶段的 intent、phase、iteration、attempt 和预期副作用都必须先持久化，再开始不可幂等的外部动作。

### Contract-first 与门禁顺序

1. 实现前先在 `contract.md` 冻结可测试断言、Required 标记、验证器和安全解释；评审状态、gate 与 acceptance 不可回写 immutable contract。
2. 顺序固定为 `contract frozen + independent review → Architecture Design accepted → development_environment_check ready + independent Evidence → independent tests written → implementation`。少任一 current exact-hash 绑定即 fail closed。
3. 合同变更必须创建新 revision 并重跑受影响的 review/Evidence；不得以代码或高分反向改写完成定义。

### 四文件磁盘状态

可恢复版本目录使用四个固定路径：

- `feature_list.json`：机器主投影与 commit marker，绑定 project/artifact/loop run、`bundle_revision`、iteration/attempt/phase、contract/progress/log digest、ledger checkpoint/prefix 和 gate 投影。Task acceptance 仍只由 ledger reducer 导出。
- `progress.md`：由 state writer 确定性渲染的人类投影，不接受手工双写。
- `contract.md`：当前 immutable contract revision，只能在显式 contract-revision transaction 更新。
- `log.md`：OKF header 后追加 hash-chained 单行 `GTLOG <canonical-json>` frame；旧 bytes 不可截断或重写。

写入必须校验 expected `bundle_revision`/digest 的 CAS，使用同文件系统 temp、flush/fsync、`os.replace` 和 transaction journal。替换顺序为 contract（仅修订时）、`log.md`、`progress.md`，最后且只能最后替换 `feature_list.json` marker；每次 replace 后 fsync parent directory。journal 是恢复元数据，不是第五个事实源。

任一文件缺失、混合 revision、digest/commit frame/checkpoint 不一致或 pending journal 时，恢复入口只能返回 `recoverable_pending | reconcile_required | blocked`，不得按 mtime、多数票或默认值继续 `Act`。`reconcile` 必须幂等 roll-forward 至新 revision，追加 `STATE_RECONCILED` 并保留 hash-only receipt；无法证明唯一安全结果则 blocked。本协议仅支持会话内/磁盘恢复，不声明 daemon、后台 runner 或无限自动执行。

### 第 9 轮重置与第 11 轮交付

- iteration 9 进入 `Act` 前必须完成一次 `controlled_reset`。对象必须是 contract 预授权且在 `.goalteams-candidates/<candidate_id>` 内的 disposable candidate；操作是原子移入 `.goalteams-quarantine/<reset_id>/<candidate_id>` 并写 pre/post hash manifest 与 independent Evidence。禁止删除仓库、工作树、用户数据、过程账本、Evidence 或 provenance；quarantine 的 purge 需要新的明确授权。
- iteration 10 只能从 reset receipt 绑定的 clean candidate 重建。iteration 11 是唯一 delivery iteration，必须同时满足 required tasks accepted、current Evidence/Review、四文件一致、reset lineage、重建 digest、全量测试、归档预检和独立 Completion Audit passed。任一缺口都必须留在 iteration 11 并输出 gaps；不得写 `achieved`、不得发布、不得进入 iteration 12。
- 需要跨多轮推进时可使用 `v234-loop-advance`，但它只能逐事务调用正常 transition、每步重新读取 CAS 并保存 receipt；不得合并阶段或直接改 iteration。iteration 9 `Reason → Act` 仍必须有 current reset Evidence，目标上限固定为 iteration 11 `Verify`，后续只能进入 delivery gate/`v234-deliver`。
- ledger binding、legacy digest、reset authorization/plan 和第 11 轮 delivery inputs 使用 `v234-closure-*` 从真实文件生成私有原子快照；快照生成器不得执行 reset、公开归档、`achieved` 或用户工作树改写。
- 第 11 轮的当前产品候选默认使用 isolated index/tree receipt：临时 Git index/object directory 只能读取主 object database，不得修改主 index、HEAD、branch、refs 或 history；receipt 必须绑定非空 V2.34 产品 delta 并从当前 bytes 重建验证。兼容 commit delta 不得接受 `baseline == candidate` 或其他空差异。Completion proof 文件、checkpoint required-task 全集以及 Audit 的 required/evidence/ledger/task digest/bundle/Review hash 绑定任一不一致均停留在 `partial`。

### 评分、分歧与 moving bottleneck

`design` / `originality` / `craft` / `functionality` 四维必须同时存在，每维恰好四个冻结 rubric item，每项通过计 `0.25`，`score = passed_count / 4`，且必须是 `[0,1]` 内有限 JSON number。每项绑定 criterion ID、candidate digest、Evidence 和与 Owner 不同的 reviewer run；`unverified` 计 0 且 score check 失败。评分只是附加质量信号，绝不能覆盖单元/API/E2E、Harness、Review 或 Audit 失败。

每个可执行判断必须用 `INTENT` 与 `JUDGMENT` GTLOG frame 记录 `event_id/parent_event_id/intent_id/expected_constraints/judgment/action_scope/prompt_ref/assertion_refs/outcome`。诊断器只允许五类确定性 divergence：`required_assertion_missing | gate_conflict | action_scope_out_of_bounds | outcome_not_allowed | constraint_judgment_incompatible`；每条因果链只报首个分歧的行号、IDs、expected/actual、prompt/assertion refs，不使用模糊文本相似度。Prompt 修订只能精确命中该 `prompt_ref` 与 locked scope，记录 before/after hash、patch、actor、reason 和 divergence；状态只允许 `proposed | applied | verified | reverted`，必须 regression 与 holdout 都通过才能 `verified`，原 divergence/provenance 永不删除。

当前瓶颈候选只来自阻断 required AC/feature 的 unresolved gap，类别只允许 `contract | planning | architecture | environment | implementation | verification | review | authorization | delivery`。每次 `Verify` 必须从 current graph 重算，以 `(-blocking_ac_count, -downstream_required_feature_count, opened_bundle_revision, gap_id)` 的字典序最小元组选唯一结果，并把 previous/current、全部 metrics、选择原因与 current Evidence 同时写入 `progress.md` 和 `GTLOG BOTTLENECK`。无候选为 `none`；复制旧值、固定 implementation 或固定轮换都失败。

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

telemetry 不可用时不得伪造 tokens/cost；Budget Gate 的机器回退值固定为 `telemetry_status=unavailable`、`budget_metric=round_time_member_file_size`，并记录 round time、成员数和文件规模。

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

## 状态快照

长任务或自动续跑必须在 `progress.md` 记录状态快照；需要机器可读恢复时可额外写 `loop-state.json`。快照至少记录 loop id、轮次、已确认范围、open gaps、最后决策、下一轮 Owner、validator、证据路径和停止边界。
