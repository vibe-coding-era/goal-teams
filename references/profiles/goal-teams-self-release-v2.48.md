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

V2.48 当前是 Skill 开发候选，默认使用
`references/skill-release-simple-protocol.md` 的 `skill_simple` 路径：

1. 本地 S0–S3 不需要先批准发行计划。
2. 只冻结 version、commit/tree、package manifest、检查结果、两次构建和隔离安装生命周期。
3. tag、GitHub Release 或正式安装前只取得一次人工确认；确认必须列出 exact candidate、
   固定资产与外部操作。
4. 没有确认时状态是 `ready_for_publish_approval` 或 `not_authorized`，不是通过伪造
   trusted-host identity 来解除阻断。
5. 普通 Skill 发行不要求 Ed25519 plan/execution approval、nonce authority、
   independent review authority 或 CP00–CP18 ledger。

V2.48 `skill_simple` profile 不声明历史 trust 字段，也不要求补 key。旧高保障字段只保留在
历史 profile 或显式 `governed_release` profile 中。

## Skill 发行分类边界

V2.48 默认分类为 `skill_bundle`。说明、Prompt、schema、脚本和 installer 按实际变更增加
定向检查，但仍使用同一五步简单发行。只有命中凭证、支付/认证、数据库/服务、破坏性基础设施、
自动外部写入或用户指定高保障发行时，才升级 `governed_release`。

`docs_only` 通常随下一次 Skill 版本一起发布；`skill_bundle` 必须完成确定性包和隔离安装生命周期。
分类只决定本地检查深度，不授权 GitHub、tag 或正式安装。
