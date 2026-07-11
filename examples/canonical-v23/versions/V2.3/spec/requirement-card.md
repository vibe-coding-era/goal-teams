---
type: Requirement Card
title: Canonical V2.3 全链需求卡
description: 将 success、blocked、failed、recovery 与行为 provenance 固定为 canonical Done Criteria。
tags: [goal-teams, requirement-card, canonical, v2.3]
timestamp: 2026-07-10T00:00:00Z
okf_version: "0.1"
goal_teams_version: V2.3
artifact_version: V2.3
owner_subagent: 实现-Canonical
validator_subagent: 评审-Canonical
---

# Canonical V2.3 全链需求卡

## 用户故事

作为 Skill Maintainer，我需要一份可重放的 canonical，任何 ledger、Evidence、Review、Audit 或 Behavior 被删改时，release gate 都必须非零退出。

## Done Criteria

- 相同 ledger 两次生成 byte-equivalent `TaskList.md`。
- required AC 各自绑定 Task、Check、Run 和当前 Evidence。
- author、script reviewer、semantic reviewer 和 completion auditor 具有不同 run identity。
- success、blocked、failed、recovery 四类状态路径可从 ledger 和 Harness 重建。
- 四个核心及五个压力 Behavior 场景具有 runner、scorer、trace 与 Evidence provenance。
