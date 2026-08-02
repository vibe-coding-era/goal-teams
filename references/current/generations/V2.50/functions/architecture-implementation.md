---
type: Goal Teams Function Rules
title: Architecture and Implementation Function
description: 定义架构触发、实现顺序、TDD 增量开发与 source identity 规则。
tags: [goal-teams, v2.50, architecture, implementation, tdd]
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
- 每个实现切片绑定 source digest、受影响面和增量验证；Medium/Large 开发过程不得加载 Release Readiness Gate。

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
- `GT250-ARCH-ENVIRONMENT`: 开发、测试与生产环境假设分别记录；生产环境规划不等于部署、凭证或生产写入授权。
- `GT250-IMPL-TDD`: 行为实现使用同一不可变 TestCase 的先失败后通过链；测试或 case 漂移必须建立新 revision。
- `GT250-IMPL-INCREMENTAL`: 开发过程的阻断性验证只覆盖适用 TDD 与受影响面增量测试，并绑定当前 source 与 environment digest。
- `GT250-IMPL-IDENTITY`: 实现状态与 Evidence 必须绑定 exact source snapshot；任何代码、依赖、配置或迁移输入变化使旧回执 stale。
