---
type: Requirement Card
title: Goal Teams V2.3 审计修复需求卡片
description: 修复 V2.3 深度审计发现并建立 fail-closed Release Gates。
tags: [goal-teams, v2.3, requirement, remediation]
timestamp: 2026-07-10T15:30:00+08:00
okf_version: "0.1"
---

# Goal Teams V2.3 审计修复需求卡片

- 核心目标：把“脚本全绿但契约未成立”改为可重放、可变异验证、失败闭合的 V2.3 RC。
- 用户故事：作为仓库 owner，我希望 Release Gate 只在真实证据完整时通过，以免发布假绿版本。
- 功能验收：承接 `GoalTeams-PRD-V2.3.md` 的 AC-23-001..031。
- 边界：不实现 V2.4 adapter；不选择 License；不执行真实生产发布。
- 风险：核心 schema 和旧文档同步面大；采用 schema SSOT、mutation tests 和独立审计降低风险。
