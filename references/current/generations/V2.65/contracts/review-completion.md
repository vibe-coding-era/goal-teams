---
type: Goal Teams Functional Contract
title: Review and Completion Contract
description: 定义独立审查、开发完成、发行就绪与 Goal 完成合同。
tags: [goal-teams, v2.65, review, completion]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Review and Completion Contract

- `contract_id`: `CONTRACT-REVIEW-COMPLETION-V250`
- `purpose`: 定义语义审查、行为审查、actor assurance、Development completion、Release readiness 和 Goal completion。

## trigger_and_exclusion_facts

- 触发：任务请求 review、准备接受交接物、结束开发、进入 Release Readiness 或宣称 Goal 完成。
- 排除：实现者、同模型相关成员或 repository candidate 自报不能成为唯一独立完成证明。

## inputs

- 当前 denominator、Task/Check/Run/Evidence 状态、reviewer identity/relationship、open gaps 和阶段事实。

## obligations_and_outputs

- 分别输出 semantic review、behavior review、completion audit 和 assurance；不把过程 Review 当作完成审计。
- 区分 `engineering_complete`、`runtime_complete`、`business_validated`、`release_ready`、`release_published`、`installation_current` 与 `goal achieved`。

## oracles_and_evidence

- actor assurance/relationship、独立重算、open-gap 清单、阶段 denominator 和 source/route/contract digest。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-TEST-CASE-GATE-V250`
- `CONTRACT-HARNESS-EVIDENCE-V250`

## dependencies

- `CORE-V250`

## owned_rule_ids

- `GT250-REVIEW-SEMANTIC`: Semantic Review 检查 Requirement、Owner、冲突、分母和规则语义，不以测试通过替代。
- `GT250-REVIEW-BEHAVIOR`: Behavior Review 独立重算适用 assertions、运行 Evidence 和外部 readback，不以文档映射替代真实行为。
- `GT250-REVIEW-ASSURANCE`: 每个审查声明 actor assurance 与 relationship；run ID 不同不自动提高 assurance，同模型相关复核不得标为外部独立。
- `GT250-COMPLETE-DEVELOPMENT`: Engineering completion 只要求 Development TaskExactSet 全部 accepted、Development denominator 闭合、Git scope 无漂移且内部 open gap 为零；它不代表 runtime、业务验证或 release-ready。
- `GT250-COMPLETE-RELEASE`: Release readiness 只由 frozen identity 的 Release denominator、发行 Gate 和当前回执闭合；开发回执不得抵扣。
- `GT250-COMPLETE-GOAL`: Goal achieved 要求全部 required Task accepted、当前 Evidence、适用审查/审计通过且无 open gap；stop 本身不等于 achieved。终局投影必须在 Benchmark 之外给出基于本轮 Evidence 的 LOOP 改进建议，至少评估 Skill、上下文、资料、Harness 与流程中的适用方面。
- `GT250-COMPLETE-FAIL-CLOSED`: 任一 required item failed、blocked、not_run、stale、invalid 或 denominator 不一致时，完成谓词为 false 并记录精确原因。
- `GT263-COMPLETE-RUNTIME-BUSINESS`: Runtime completion 需要真实宿主的当前 observation/session Evidence；business validation 需要业务验收者/Oracle Evidence。二者均不能由结构检查、工程 accepted 或仓库自报替代。
