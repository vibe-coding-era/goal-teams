---
type: Goal Teams Functional Contract
title: Task State Contract
description: 定义任务、检查、Evidence、审计、运行与 Goal 的正交状态合同。
tags: [goal-teams, v2.52, task-state, lifecycle]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# Task State Contract

- `contract_id`: `CONTRACT-TASK-STATE-V250`
- `purpose`: 统一任务、检查、Evidence、审计、运行与 Goal 状态，防止跨轴冒充。

## trigger_and_exclusion_facts

- 触发：任何非 Discussion 执行、交接、审查、LOOP 或用户可见状态更新。
- 排除：自然语言“完成”不能绕过机器状态；Replay verdict 不能满足 Current completion。

## inputs

- revision-bound canonical events、source/route/contract digest、actor identity 和 Evidence refs。

## obligations_and_outputs

- 从 canonical events 确定性投影正交状态，不直接信任可写投影。
- 第一轮 bootstrap 必须按 `TaskList -> task assignment -> environment_preflight` 投影；三项未闭合时 implementation task 不得进入 active。
- 用户可见输出只使用六字段 envelope，终止字段按 LOOP 决策二选一。

## oracles_and_evidence

- 状态枚举、合法转换、CAS revision、绑定 digest 和投影重建比较。

## contract_refs

- `CONTRACT-HARNESS-EVIDENCE-V250`
- `CONTRACT-REVIEW-COMPLETION-V250`

## dependencies

- `CORE-V250`

## owned_rule_ids

- `GT250-STATE-ORTHOGONAL`: `task_state`、`check_state`、`evidence_state`、`audit_state`、`run_outcome` 与 `goal_state` 分轴记录，禁止用一个字段替代另一轴。
- `GT250-STATE-VOCABULARY`: `accepted` 仅用于 Task，`achieved` 仅用于 Goal；failed、blocked、not_run、stale、invalid 保留其精确含义。
- `GT250-STATE-EVENTS`: 状态投影必须由 append-only canonical events、revision 和 digest 重建；只有投影 writer allowlist 可更新派生视图。
- `GT250-STATE-TRANSITION`: 任何状态转换必须满足前置状态、当前绑定和 actor 权限；CAS 冲突或 binding 漂移不得覆盖新状态。
- `GT250-STATE-BOOTSTRAP`: 第一轮 TaskList、Owner/Validator 分配和独立环境 preflight 必须按序产生 current receipt；缺任一项或后续轮缺首轮 receipt ref 时，implementation task 保持 pending/blocked。
- `GT250-STATE-OUTPUT`: 用户可见执行更新只输出 `任务、成员、进度、结果、Banchmark` 加 `下一轮 LOOP` 或 `下一个任务` 之一；`进度` 必须含当前轮次/总轮次，终局 `结果` 必须含独立于 Benchmark 的 LOOP 改进建议；不输出内部推理或同时输出两个终止字段。
- `GT250-STATE-REPLAY-SEPARATION`: 历史回放状态只描述历史合同结果，不得投影为 Current accepted、release-ready 或 achieved。
