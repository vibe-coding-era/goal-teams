---
type: Requirement Specification Card
title: Goal Teams V2.3 审计修复规格卡
description: V2.3 RC 修复的结构化需求、流程与验收摘要。
tags: [goal-teams, v2.3, specification]
timestamp: 2026-07-10T15:30:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.3 审计修复规格卡

## 功能结构

1. Schema、状态机与单写者 ledger。
2. Evidence、Traceability、Dual Review 与 Completion Audit。
3. Canonical、Behavior、Migration、Installer、Context、Security 和 CI。
4. 文档/规则同步、TaskList 和独立审计。

## 主流程

`PRD → ledger/TaskList → running/review prefix → Test/Evidence → check/accepted append → Canonical/Release Gates → Dual Review → external Completion Audit`

## 验收

- 正向 fixtures 全部通过。
- 每类已知假绿都有对应 mutation 且非零退出。
- 同一 ledger 生成 byte-equivalent TaskList。
- live prefix Evidence 可在后续 append 后保持有效；空/伪 prefix、错 binding、错时序与 Audit 自引用全部 fail-closed。
- RC gate 可通过；License 未决的 GA gate 必须拒绝。
