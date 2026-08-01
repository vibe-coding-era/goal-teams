---
type: Goal Teams Functional Contract
title: Task State Contract
description: 定义任务、检查、Evidence、审计、运行与 Goal 的正交状态合同。
tags: [goal-teams, v2.49, task-state, lifecycle]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Task State Contract

- `contract_id`: `CONTRACT-TASK-STATE-V249`
- `purpose`: 统一任务、检查、Evidence、审计、运行与 Goal 状态，防止跨轴冒充。

## trigger_and_exclusion_facts

- 触发：任何非 Discussion 执行、交接、审查、LOOP 或用户可见状态更新。
- 排除：自然语言“完成”不能绕过机器状态；Replay verdict 不能满足 Current completion。

## inputs

- revision-bound canonical events、source/route/contract digest、actor identity 和 Evidence refs。

## obligations_and_outputs

- 从 canonical events 确定性投影正交状态，不直接信任可写投影。
- 用户可见输出只使用六字段 envelope，终止字段按 LOOP 决策二选一。

## oracles_and_evidence

- 状态枚举、合法转换、CAS revision、绑定 digest 和投影重建比较。

## contract_refs

- `CONTRACT-HARNESS-EVIDENCE-V249`
- `CONTRACT-REVIEW-COMPLETION-V249`

## dependencies

- `CORE-V249`

## owned_rule_ids

- `GT249-STATE-ORTHOGONAL`: `task_state`、`check_state`、`evidence_state`、`audit_state`、`run_outcome` 与 `goal_state` 分轴记录，禁止用一个字段替代另一轴。
- `GT249-STATE-VOCABULARY`: `accepted` 仅用于 Task，`achieved` 仅用于 Goal；failed、blocked、not_run、stale、invalid 保留其精确含义。
- `GT249-STATE-EVENTS`: 状态投影必须由 append-only canonical events、revision 和 digest 重建；只有投影 writer allowlist 可更新派生视图。
- `GT249-STATE-TRANSITION`: 任何状态转换必须满足前置状态、当前绑定和 actor 权限；CAS 冲突或 binding 漂移不得覆盖新状态。
- `GT249-STATE-OUTPUT`: 用户可见执行更新只输出 `任务、成员、进度、结果、Banchmark` 加 `下一轮 LOOP` 或 `下一个任务` 之一，不输出内部推理或同时输出两个终止字段。
- `GT249-STATE-REPLAY-SEPARATION`: 历史回放状态只描述历史合同结果，不得投影为 Current accepted、release-ready 或 achieved。
