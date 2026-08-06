---
type: Goal Teams Function Rules
title: Requirements Function
description: 定义需求、用户故事、验收标准、范围与变更语义规则。
tags: [goal-teams, v2.51, requirements, acceptance]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Requirements Function

- `function_id`: `FUNCTION-REQUIREMENTS-V250`
- `purpose`: 拥有需求、用户故事、功能验收标准、范围和变更语义。

## trigger_and_exclusion_facts

- 触发：目标、用户价值、边界或验收标准尚未形成可信输入。
- 排除：纯讨论可只返回结论；测试运行、UI 像素算法和发行流程由其他 Owner 定义。

## inputs

- 用户目标、约束、persona、现状证据、外部依赖和授权边界。

## obligations_and_outputs

- 形成 source/revision-bound requirement、user story、AC、out-of-scope 和 unresolved decisions。
- 将适用 Requirement、AC、persona、journey、failure mode 和 authorization surface 提供给风险分母，不直接定义测试执行。

## oracles_and_evidence

- 每个需求与 AC 有稳定 ID、来源和可判定结果。
- 范围变化具有影响分析和新 revision；未确认内容保持 open/blocked。

## contract_refs

- `CONTRACT-TASK-STATE-V250`
- `CONTRACT-TEST-CASE-GATE-V250`

## dependencies

- `CORE-V250`
- `ROUTING-V250`

## owned_rule_ids

- `GT250-REQ-TRACEABILITY`: Requirement、用户故事和 AC 必须使用稳定 ID 并记录来源、revision、状态与验证方式。
- `GT250-REQ-AC`: 功能 AC 必须描述输入、业务行为、可观察结果和失败边界，不能以“已实现”或测试退出码替代。
- `GT250-REQ-SCOPE`: in-scope、out-of-scope、假设、依赖和授权边界必须显式；未解决的关键选择不得静默默认。
- `GT250-REQ-CHANGE`: 实质范围变化产生新 revision 和 impact analysis；超出开始授权时停止为 `blocked/new_scope_required`。
- `GT250-REQ-DENOMINATOR-SEED`: 需求功能只提供风险分母种子与来源，不拥有 TestCase、Run 或 Review 的执行语义。
