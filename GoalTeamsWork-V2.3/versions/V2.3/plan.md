---
type: Goal Teams Plan
title: Goal Teams V2.3 审计修复计划
description: 将深度审计缺口修复到 RC Release Gates 可验证通过。
tags: [goal-teams, v2.3, plan, loop]
timestamp: 2026-07-10T15:30:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.3 审计修复计划

## 用户目标

把已查出的问题写入 TaskList，一次执行并保持 LOOP，直到 V2.3 RC 范围内全部门禁通过。

## Done Criteria

1. 12 个 Release Gate 均由机器检查与独立语义复核给出结论；RC 代码门禁全部通过。
2. GA License 未决时必须被正确阻断，不把外部决策伪装成技术失败或通过。
3. 所有负向 mutation 均非零退出；canonical ledger、TaskList、Evidence、Review、Audit 可重放且一致。
4. installer 生命周期在失败点保持 skill、agents 和用户配置事务一致。
5. TaskList、progress、test plan、acceptance、dual review 与 completion audit 证据闭合。

## 执行顺序

1. Schema/State/Ledger/Evidence/Migration 核心实现。
2. 独立测试、canonical 与 behavior gate。
3. Installer/Context/Pixel/Security/CI。
4. 规则和文档同步。
5. Script review + LLM review + Completion Audit。

## 风险与边界

- 不回滚或覆盖用户已有无关改动。
- 用户已追加授权：全部技术门禁与审计通过、GitHub 提交成功后，用同一已验证提交事务化更新全局 `/Users/Rou/.codex/skills/goal-teams/`；在此之前不覆盖本地安装。
- 不选择 License；只实现 GA fail-closed gate。
- 不创建真实后台 runner、生产审批或外部发布能力。

## 发布追加范围

- 只提交本轮 V2.3 代码、规则、测试、canonical 与 `GoalTeamsWork-V2.3` 证据链；保留并排除工作树中既有个人文件。
- 推送当前 `codex/v2.3-cloud-seed`，以 `main` 为 base 创建或更新 draft PR。
- 本地更新必须使用 installer 的 staging/verify/atomic switch/rollback 路径，并对安装结果复验。
