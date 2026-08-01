---
type: Goal Teams Functional Contract
title: Review and Completion Contract
description: 定义独立审查、开发完成、发行就绪与 Goal 完成合同。
tags: [goal-teams, v2.49, review, completion]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Review and Completion Contract

- `contract_id`: `CONTRACT-REVIEW-COMPLETION-V249`
- `purpose`: 定义语义审查、行为审查、actor assurance、Development completion、Release readiness 和 Goal completion。

## trigger_and_exclusion_facts

- 触发：任务请求 review、准备接受交接物、结束开发、进入 Release Readiness 或宣称 Goal 完成。
- 排除：实现者、同模型相关成员或 repository candidate 自报不能成为唯一独立完成证明。

## inputs

- 当前 denominator、Task/Check/Run/Evidence 状态、reviewer identity/relationship、open gaps 和阶段事实。

## obligations_and_outputs

- 分别输出 semantic review、behavior review、completion audit 和 assurance；不把过程 Review 当作完成审计。
- 区分 `development_complete`、`release_ready` 与 `goal achieved`。

## oracles_and_evidence

- actor assurance/relationship、独立重算、open-gap 清单、阶段 denominator 和 source/route/contract digest。

## contract_refs

- `CONTRACT-TASK-STATE-V249`
- `CONTRACT-TEST-CASE-GATE-V249`
- `CONTRACT-HARNESS-EVIDENCE-V249`

## dependencies

- `CORE-V249`

## owned_rule_ids

- `GT249-REVIEW-SEMANTIC`: Semantic Review 检查 Requirement、Owner、冲突、分母和规则语义，不以测试通过替代。
- `GT249-REVIEW-BEHAVIOR`: Behavior Review 独立重算适用 assertions、运行 Evidence 和外部 readback，不以文档映射替代真实行为。
- `GT249-REVIEW-ASSURANCE`: 每个审查声明 actor assurance 与 relationship；run ID 不同不自动提高 assurance，同模型相关复核不得标为外部独立。
- `GT249-COMPLETE-DEVELOPMENT`: Development completion 只要求实现范围完成、Development denominator 闭合和无开发 open gap；它不代表 release-ready。
- `GT249-COMPLETE-RELEASE`: Release readiness 只由 frozen identity 的 Release denominator、发行 Gate 和当前回执闭合；开发回执不得抵扣。
- `GT249-COMPLETE-GOAL`: Goal achieved 要求全部 required Task accepted、当前 Evidence、适用审查/审计通过且无 open gap；stop 本身不等于 achieved。
- `GT249-COMPLETE-FAIL-CLOSED`: 任一 required item failed、blocked、not_run、stale、invalid 或 denominator 不一致时，完成谓词为 false 并记录精确原因。
