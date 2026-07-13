---
type: Goal Teams Memory
title: Canonical V2.3 Memory
description: Canonical V2.3 的 append-only 决策与验证摘要。
tags: [goal-teams, memory, v2.3]
timestamp: 2026-07-10T00:00:00Z
okf_version: "0.1"
goal_teams_version: V2.3
artifact_version: V2.3
author: GoalTeams
timeline_order: old_to_new
---

# Canonical V2.3 Memory

- 2026-07-10T00:00:00Z: ledger 为唯一状态事实源，`TaskList.md` 只由 reducer 生成。
- 2026-07-10T00:01:00Z: required AC 使用当前本地 Evidence；历史失败不计入当前通过。
- 2026-07-10T00:02:00Z: Behavior deterministic records 绑定 runner、独立 scorer、trace 和文件 hash，但 `release_eligible=false`；发布门禁另需 local-process-attested isolated blind summary，不宣称远程签名。
- 2026-07-10T00:03:00Z: replica Pixel Gate 绑定双环境指纹、独立 baseline approval、报告与 diff hash。
