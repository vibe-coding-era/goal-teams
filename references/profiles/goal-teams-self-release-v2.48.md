---
type: Goal Teams Policy Profile
title: Goal Teams Self Release V2.48
description: Goal Teams V2.48 候选的 Agent 产品开发成员、资料合同与既有流程测试兼容规则；正式发布仍需独立 release profile。
tags: [goal-teams, self-release, v2.48, policy-profile, agent-development]
timestamp: 2026-07-29T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams Self Release V2.48

机器名：`goal-teams-self-release-v2.48`。仅当可信 adapter 验证目标为 Goal Teams
仓库、产品版本为 `V2.48` 且任务类型为 `goal_teams_self_release` 时加载；V2.47 及更早
Profile 只用于历史 replay。

## 组合规则

1. Core V2.5、legacy V2.3、V2.44 API/E2E、V2.46 验证治理与 desktop 合同继续兼容，不原地改写历史 schema/Evidence。
2. V2.47 的 `references/flow-test-strategy-manifest.json`、`references/incremental-document-ssot-protocol.md` 与 `references/codeagent-runtime-manifest.json` 保持兼容/回放合同；它们不因 V2.48 的 Agent 产品开发资料扩大运行时 adapter 分母。
3. Agent 产品、Prompt/Context/Cache、Tool/MCP、Browser/Computer Use/Playwright、方案组合与测试边界唯一入口是 `references/agent-development/INDEX.md` 与 `references/agent-development-capability-manifest.json`。
4. `goal_agent_product_manager` 是专门的产品角色；通用 `goal_product` 仍保留现有 PRD/原型职责。前后端、QA 与独立测试成员仅在 Goal Packet 命中 Agent 开发任务时加载角色专属资料。
5. 第三方平台能力只能按来源矩阵写 `documented`、`documented_limited`、`unknown` 或 `not_found`；资料不等于当前 runtime adapter、实机执行或完整产品兼容。
6. 用户可见执行更新只输出 `任务、成员、进度、结果、Banchmark、下一轮 LOOP 或下一个任务`。

`policy_profile` 与 `execution_profile` 正交：V2.48 候选且 `release=false` 不因仓库身份自动
升级 full；small 按 flow manifest 只做增量与 P0。只有 `release=true`、large、高风险或
其他 L0 升级事实才要求 full/regulated 与最终全量。Agent 的 Browser/Computer Use、凭证、
权限、支付、删除或外部写入必须按实际风险升级，不能借小型流程绕过批准。

## 候选与发布边界

V2.48 当前是开发候选。正式 release profile、public-scan baseline、`release/current`、
tag/Release、推送、安装与外部写入均未由本 Profile 授权；仍由当前已发布 V2.46
release engine fail closed，直到独立发布审批建立新的冻结身份。
