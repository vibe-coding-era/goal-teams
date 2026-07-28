---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.47
description: Goal Teams V2.47 候选的流程测试、缓存友好文档、响应与跨 CodeAgent 兼容规则；正式发布仍需独立 release profile。
tags: [goal-teams, self-release, v2.47, policy-profile]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.47

机器名：`goal-teams-self-release-v2.47`。仅当可信 adapter 验证目标为 Goal Teams
仓库、产品版本为 `V2.47` 且任务类型为 `goal_teams_self_release` 时加载；V2.46 及更早
Profile 只用于历史 replay。

## 组合规则

1. Core V2.5、legacy V2.3、V2.44 API/E2E、V2.46 验证治理与 desktop 合同继续兼容，不原地改写历史 schema/Evidence。
2. 流程测试唯一入口是 `references/flow-test-strategy-manifest.json`：small=增量+P0；medium 最终等待用户选择；large 最终以新 Run/Evidence 重跑完整分母。
3. 过程文档读取 `references/incremental-document-ssot-protocol.md`：稳定前缀在前、动态实例在尾，fragment/ledger 是唯一事实源，最终文档只做确定性投影。
4. CodeAgent 环境读取 `references/codeagent-runtime-manifest.json`，只加载 Portable Core、正常规则和一个经检测匹配的宿主特殊规则；未知/冲突环境 blocked。
5. 用户可见执行更新只输出 `任务、成员、进度、结果、Banchmark、下一轮 LOOP 或下一个任务`。
6. TaskList 外的新任务只能形成 `scope_change_proposal`；先完成用户指定任务，再交用户选择。

`policy_profile` 与 `execution_profile` 正交：V2.47 候选且 `release=false` 不因仓库身份自动
升级 full；small 按 flow manifest 只做增量与 P0。只有 `release=true`、large、高风险或
其他 L0 升级事实才要求 full/regulated 与最终全量。V2.36 policy runtime 仅历史 replay，
不得覆盖本 Profile 的当前 flow suite。

## 候选与发布边界

V2.47 当前是开发候选。正式 release profile、public-scan baseline、`release/current`、
tag/Release、推送、安装与外部写入均未由本 Profile 授权；仍由当前已发布 V2.46
release engine fail closed，直到独立发布审批建立新的冻结身份。
