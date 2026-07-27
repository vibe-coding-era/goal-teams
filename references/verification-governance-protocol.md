---
type: Verification Governance Protocol
title: Goal Teams V2.46 验证治理协议
description: 历史 Evidence 适用性、正交状态机、测试合同、Grill me 与对抗式测试的统一规范。
tags: [goal-teams, verification, evidence, state-machine, okf]
timestamp: 2026-07-27T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.46 验证治理协议

## 1. 目标与权威来源

本协议在保留 `SPEC -> Harness -> Evidence -> Audit`、独立验证和 V2.44 API/E2E
测试合同的前提下，统一解决以下问题：

1. 规则、SPEC、Harness、环境或验收合同变化后，历史测试事实不得被错误清零。
2. 任务、检查、运行、Evidence 适用性、恢复和发布状态必须正交建模。
3. 测试合同、Grill me 和对抗式测试共享同一风险分母与追踪链。

机器事实源为 `references/verification-governance-manifest.json` 和
`schemas/v2.46/verification-governance.schema.json`；语义由
`scripts/checks/validate-verification-governance.py` fail closed 校验。本文只解释
人类可读语义，不另建状态或枚举。

V2.3 与 V2.44 记录保持 replay-only。V2.46 通过追加事件投影新语义，不覆写旧
Evidence、旧测试结果或旧 Schema。

## 2. Evidence 的三个正交维度

每条 Evidence 本体不可变。后续变化只追加 `evidence_applicability_event`：

| 维度 | 字段 | 语义 |
| --- | --- | --- |
| 历史可信性 | `evidence_integrity_state` | `valid` 表示证据作为历史事实可信；`invalid` 只表示 hash、来源、身份、时序或内容完整性失败 |
| 当前适用性 | `evidence_applicability_state` | `current` 可参与当前合同；`stale` 仍是历史事实但不能单独支撑当前验收 |
| 复验义务 | `revalidation_state` | `not_required`、`retest_required`、`scheduled`、`running`、`closed` |

禁止使用 `invalid` 表达普通规则升级、合同漂移、环境变化、全量回归策略或新增
要求。`invalid` 必须带 `integrity_failure_code` 和证据完整性 Evidence。

标准投影：

| 情况 | impact | integrity | applicability | 当前检查 |
| --- | --- | --- | --- | --- |
| 无依赖路径 | `unaffected` | 保持 `valid` | `current` | 保留原结果 |
| 依赖路径受影响 | `affected` | 保持 `valid` | `stale` | `retest_required` |
| 新增要求 | `new_requirement` | 无旧证据 | 不适用 | `check_state=not_started`、`run_conclusion=not_run` |
| 实际执行失败 | 不由影响分析替代 | 新失败记录仍可为 `valid` | `current` | `failed` |
| 缺环境、权限或依赖 | 按影响分析投影 | 保持历史事实 | 不推测 | `blocked` |
| 证据被伪造或篡改 | 不适用 | `invalid` | 不得进入验收 | `failed` |
| 影响无法证明 | `undetermined` | 保持历史事实 | 不擅自标 stale | 当前验收 `blocked` |

全量回归是当前版本的验证策略，只扩大 `retest_required` 的集合，不得改写历史。
重跑必须产生新的 `evidence_id`、`run_id` 和 `attempt_id`，并通过
`supersedes_evidence_id` 连接旧记录；旧 Evidence 的 latest applicability 永久保持
`stale/retest_required`，禁止用同一 `evidence_id` 复活为 current/closed。当前验收
只读取 `acceptance_evidence_ids` 明示的 current valid Evidence 集合。

Bundle 顶层 `revision` 是治理账本 revision。revision 1 的
`previous_bundle_ref=null`；后续 revision 必须以 artifact hash 指向 revision-1。
validator 对历史 Evidence ID、applicability event、transition receipt、合同、Grill
和风险记录逐项验证不可变前缀，不能通过同时删除 baseline 与 history 或保留 ID
但篡改旧事件来重投影历史。

`historical_evidence_ids` 不是可手填的名称清单：每个 ID 都必须有 CAS 连续的
applicability event，并绑定可哈希回读的 Evidence artifact。Risk、Grill、guard 或
transition 即使引用已登记 ID，只要缺少该 event/artifact 链仍按孤儿引用 fail closed。

## 3. 变化影响分析

规则、SPEC、AC、Harness、Schema、环境、风险分母或测试机制变化必须先创建
`change_event`，再创建 `impact_assessment`。逐项分类：

- `unaffected`：必须证明目标与变更之间没有依赖路径，保持当前适用。
- `affected`：必须给出从 changed artifact 到 test/Evidence 的非空 `dependency_path`。
- `new_requirement`：必须指向新增 requirement/AC/risk，当前状态为
  `check_state=not_started`、`run_conclusion=not_run`。
- `scope_change_pending`：实现方主动扩大产品语义、风险分母或 required gate，必须先
  写 intent、更新 SPEC/Harness 并绑定批准；无批准则阻塞。
- `undetermined`：不能证明影响范围时保留历史事实，但当前验收 fail closed。

每个 assessment 必须完整列出其 `denominator_item_ids`。不得通过遗漏旧失败项、删除
风险、把未验证项改为 N/A 或缩小分母获得通过。

## 4. 正交状态机与转换收据

任务生命周期、检查结果、运行结论、Evidence 状态、恢复状态和发布阶段使用各自的
state machine。一个通用 `status` 不得同时表达多个域。

每次状态转换都写 `transition_receipt`，至少绑定：

- `machine_id`、`entity_id`、`transition_event`
- `from_state`、`to_state`
- `expected_revision`、`new_revision`
- `guard_results`
- `actor_run_id`、`reason_code`
- `evidence_refs`
- `occurred_at`、`idempotency_key`
- 外部写入时的 `intent_ref`、`side_effect_receipt_ref`、`exact_readback_ref`

manifest 中声明的每个状态必须有可达路径；未声明的转换、revision 非连续、CAS 冲突、
缺守卫或缺 Evidence 均 fail closed。

`accepted`、`achieved`、`released`、`closed` 只能由完成谓词、current valid Evidence
和独立审计推导。执行者不得直接声明完成。新规则影响已 accepted 任务时创建 successor
revalidation task；旧任务仍保持 accepted 历史。

`task_lifecycle:review -> accepted` 还必须绑定 typed task completion audit receipt；
receipt 固定 task、executor、auditor、Evidence 集和完成谓词。auditor 必须与 executor
不同；仅填写 `actor_run_id`、守卫为 true 或状态名为 `accepted` 均不足以完成转换。

Release runtime 的 `release_checkpoint` 与 `recovery` 是两个正交、可转换状态机。
`recovery_state` 只能由独立的 append-only `recovery_transition_receipts` 账本头推导，
并使用独立 `recovery_revision` 做 CAS；不得复用 checkpoint 的 `state_revision`，
也不得由 runtime 或调用方直接赋值。正常恢复路径固定为
`none -> reconciliation_required -> recovering -> recovered -> none`；每一步都必须有
canonical event、守卫、Evidence、actor、reason 与未复用的 idempotency key。
`external_surface_phase` 仍由按序的 exact operation readback 推导，是只读投影。
CP16 的 draft asset 回读明确投影 `release_draft -> asset_verified`。

## 5. 外部副作用与恢复

发布、推送、安装或其他不可逆/外部写入固定执行：

```text
persist intent
-> verify pre-state and revision/CAS
-> execute once
-> exact readback
-> persist receipt
-> commit state
```

结果不确定时只允许进入 `reconciliation_required`，随后执行 exact readback：

- `absent`：只有持久化 intent 存在时才允许执行。
- `exact`：禁止重放副作用，只补写 receipt/marker。
- `conflict`：进入 conflict 并停止，等待授权对账。
- `unavailable`：保持 blocked，只重试 readback，不推测成功。

uncertain/conflict 的落盘必须同时产生 recovery transition receipt；恢复命令先以
独立 CAS 转为 `recovering`，exact readback 后依次转为 `recovered`、`none`。receipt
重放、revision 冲突、跳步或 recovery/checkpoint revision 混用均 fail closed。

用户可见发布状态必须来自已回读的 `external_surface_phase`。内部 checkpoint 不能替代
GitHub、tag、Release、asset 或安装身份的真实状态。

## 6. 统一 Verification Contract

`verification_contract` 统一承载三项机制，避免创建三套平行交付物。

### 6.1 测试合同

合同必须包含 requirement/AC、风险分母、不可接受风险、通过阈值、责任人、Evidence
要求、N/A/waiver、变更审批和以下追踪：

```text
Requirement -> AC -> Test Contract -> Test Plan -> Test Case
-> Harness Check -> Run -> Evidence -> Review/Audit
```

任一 required 链断裂、Evidence stale/invalid、检查 `failed|blocked|not_run|flaky`
或复验未关闭时，当前验收不得 achieved。

### 6.2 Grill me

每条 critical requirement 必须回答：定义、依据、版本/环境绑定、失败路径、残余风险、
N/A 合理性和 Evidence。回答“已测试”或只给退出码不构成证据。

Grill 结论只允许 `answered_with_evidence`、`finding`、`blocked`、
`not_applicable_accepted`。critical 项有 finding/blocked 时 Review 不能通过；N/A
必须有来源、影响分析和独立 reviewer。

### 6.3 对抗式测试

风险目录覆盖滥用、越权、异常输入、并发、重试/幂等、故障恢复、资源清理、伪造或
过期 Evidence、CAS 冲突、N/A/waiver/分母绕过。每个适用 risk 必须形成：

```text
risk_id -> case_id -> assertion_id -> run_id -> evidence_id -> reviewer_run_id
```

Profile 只决定哪些风险适用，不允许把 `blocked`、`not_run`、`flaky`、`waived` 或
无依据 N/A 计为通过。

## 7. 条件路由

- Lite：受影响路径分析、scoped test contract、最小关键 Grill 集和关键风险检查；不创建空仪式任务。
- Standard：完整影响清单、所有已路由关键 Grill、适用对抗风险与独立 Review。
- Full：完整风险分母、全部合同关键 Grill、独立 Designer/Runner/QA/Reviewer 和 Completion Audit。
- Regulated：Full 加 safety review、防伪/防重放、恢复、审批与外部副作用对账。

项目规模不直接降低风险门禁。安全、认证、支付、发布、迁移、破坏性写入仍按 route
提升到 Full/Regulated。

## 8. 验收谓词

当前版本只有同时满足以下条件才可 achieved：

1. 所有 required impact item 已分类，且无 `undetermined|scope_change_pending`。
2. `affected` 的复验全部 `closed`，新增项均已真实执行。
3. `acceptance_evidence_ids` 中所有 Evidence 为 `integrity=valid` 且
   `applicability=current`，且不包含被 supersede 的旧 Evidence。
4. required check/run 无 `failed|blocked|not_run|flaky`。
5. 所有 critical Grill 有 Evidence 且无 finding/blocked。
6. 对抗风险分母没有删除、未批准 N/A 或无 Evidence 覆盖。
7. 完成状态由 typed、hash-bound 的独立 Review/Completion Audit receipt 推导；
   receipt 必须绑定 bundle/revision/acceptance Evidence 集、完成谓词和独立 actor。
8. V2.3/V2.44 历史 replay 仍可验证，且未被 V2.46 原地改写。
