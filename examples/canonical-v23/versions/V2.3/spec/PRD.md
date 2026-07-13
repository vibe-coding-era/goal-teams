---
type: Product Requirements Document
title: Canonical V2.3 Replay PRD
description: 定义 canonical 全链、状态分支和行为回归的可机械验收范围。
tags: [goal-teams, prd, canonical, v2.3]
timestamp: 2026-07-10T00:00:00Z
okf_version: "0.1"
goal_teams_version: V2.3
artifact_version: V2.3
status: historical_replay_fixture
historical_acceptance_state: unbound_fixture_only
owner_subagent: 实现-Canonical
validator_subagent: 评审-Canonical
---

# Canonical V2.3 Replay PRD

## Requirements

- REQ-CAN-001：required success 分支必须有当前 Evidence 和独立 Review。
- REQ-CAN-002：required blocked 分支恢复后必须重新执行检查并验收。
- REQ-CAN-003：optional 非阻断 blocked 分支不得让 achieved 假失败。
- REQ-CAN-004：历史 check failure 必须保留，并与 recovery run 机械关联。

## Acceptance Criteria

- AC-CAN-001（required）：success artifact 的 hash、命令日志和 review 均有效。
- AC-CAN-002（required）：blocked recovery artifact 使用独立当前 run Evidence。
- AC-CAN-003（optional）：非阻断 optional task 可保持 blocked，audit 记录其原因。
- AC-CAN-004（optional）：failed run 与 recovery run 同时存在，只有 recovery Evidence 计入当前覆盖。
