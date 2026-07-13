---
name: goal-teams
description: Goal Teams 仓库入口；先加载根 Skill，再按其 route、Harness 与独立审计规则执行。
---

# Goal Teams 仓库入口

完整读取仓库根 `../../../SKILL.md`，相对路径按仓库根解析。普通维护用 Core V2.5；可信路由仅在产品 V2.39、本仓库且 `release=true` 时加载 `goal-teams-self-release-v2.39`，V2.38 仅历史 replay。legacy V2.3 scope 再读根 `GoalTeams-PRD-V2.3.md`。
