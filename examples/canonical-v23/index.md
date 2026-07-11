---
type: Goal Teams Canonical Index
title: Goal Teams V2.3 可重放 Canonical
description: 连接 ledger、TaskList、Harness、Evidence、Review、Audit 与 Behavior 的 V2.3 官方验证资产。
tags: [goal-teams, canonical, v2.3, replay]
timestamp: 2026-07-10T00:00:00Z
okf_version: "0.1"
goal_teams_version: V2.3
artifact_version: V2.3
---

# Goal Teams V2.3 可重放 Canonical

- SSOT：`versions/V2.3/ledger/events.jsonl`
- 投影：`versions/V2.3/TaskList.md`
- 验证链：`SPEC -> Harness -> Evidence -> Review -> Completion Audit`
- deterministic contract：四个核心场景与五个压力场景，仅证明包内契约，不冒充发布期行为证据。
- Behavior Release Gate：消费隔离工作区中当前 path/hash 锁定 Codex CLI 生成的九场景 blind summary；信任级别为 local-process-attested。
