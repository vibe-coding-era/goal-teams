---
type: Goal Teams Function Rules
title: Architecture and Implementation Function
description: 定义架构触发、实现顺序、TDD 增量开发与 source identity 规则。
tags: [goal-teams, v2.66, architecture, implementation, tdd]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Architecture and Implementation Function

- `function_id`: `FUNCTION-ARCHITECTURE-IMPLEMENTATION-V250`
- `purpose`: 拥有架构触发条件、环境边界、实现顺序、TDD 增量开发和 source identity。

## trigger_and_exclusion_facts

- 触发：任务包含代码、配置、Schema、数据迁移、工具链或运行时行为变化。
- 排除：纯文档讨论或无实现影响的说明不建立实现流水线；测试对象 Schema 由测试合同拥有。

## inputs

- 已确认 requirement/AC、现有架构证据、依赖、环境、迁移与恢复约束。

## obligations_and_outputs

- 先定义受影响组件、接口、数据流、失败模式、环境差异和恢复路径，再按小切片 TDD 实现。
- 首轮环境检查由与实现 Owner 不同的 `goal_release_engineer` 以 `environment_preflight` 模式执行。Medium、Large 或用户指定检查时，先按项目版本、source、工具链和依赖 digest 查找既有环境；匹配且 current 时复用，否则在仓库边界内创建新环境。
- 除 Small 外，新开发环境必须包含逻辑分支 `develop-v<major.minor>` 与仓库内 `develops/v<major.minor>` worktree；宿主要求 namespace 时添加前缀，本仓为 `codex/develop-v<major.minor>`。Small 可不创建版本开发分支，但仍执行独立轻量 preflight。分支或环境复用、创建和拒绝复用的理由都写入 Evidence。
- 每个实现切片绑定 source digest、受影响面和增量验证；Medium/Large 开发过程不得加载 Release Readiness Gate。
- 冻结计划必须编译为有消费者、预算、验证、退出条件和 owner/validator 的 `TaskExactSet` 与 DAG；新增/删除 Task 或改变依赖、消费者、预算必须提升 plan revision 并重算关键路径。
- 外部 blocker 独立记录，只阻断受影响 Task 的 DAG 后继闭包；预算耗尽或范围漂移触发 `replan|blocked`，不得静默扩张。

## oracles_and_evidence

- 架构决策与源证据、实现 patch/source digest、TDD red/green 顺序和受影响面测试回执。
- 架构或实现输入漂移时相关 Evidence 变为 stale。

## contract_refs

- `CONTRACT-TEST-CASE-GATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-TASK-STATE-V250`

## dependencies

- `FUNCTION-REQUIREMENTS-V250`
- `FUNCTION-TESTING-V250`

## owned_rule_ids

- `GT250-ARCH-TRIGGER`: 跨组件、接口、数据、依赖、迁移、运行时或恢复行为变化必须先形成足够架构边界；局部低风险修改可使用轻量决策记录。
- `GT250-ARCH-ENVIRONMENT`: 开发、测试与生产环境假设分别记录；首轮由独立 `goal_release_engineer` 的 `environment_preflight` 模式检查。Medium、Large 或用户指定时，先复用 identity 匹配且 current 的既有环境，否则创建新环境；除 Small 外绑定逻辑分支 `develop-v<major.minor>`，并按宿主要求添加 namespace。生产环境规划不等于部署、凭证或生产写入授权。
- `GT250-IMPL-TDD`: 行为实现使用同一不可变 TestCase 的先失败后通过链；测试或 case 漂移必须建立新 revision。
- `GT250-IMPL-INCREMENTAL`: 开发过程的阻断性验证只覆盖适用 TDD 与受影响面增量测试，并绑定当前 source 与 environment digest。
- `GT250-IMPL-IDENTITY`: 实现状态与 Evidence 必须绑定 exact source snapshot；任何代码、依赖、配置或迁移输入变化使旧回执 stale。
- `GT263-IMPL-EXACT-SET`: active 实现任务必须与当前 `TaskExactSet` 完全一致；DAG 必须无环、无缺失依赖、无孤立且无消费者节点，每个 required output 至少存在一个消费者。
- `GT263-IMPL-BUDGET-EXIT`: 每个 Task 的预算、验证命令/Oracle 和退出条件在执行前冻结；预算耗尽不等于完成，只能形成新 revision 或精确 blocker。
