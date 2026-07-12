---
name: goal-teams
description: 仓库作用域的 Goal Teams 入口。适用于在本仓库中通过 $goal-teams、Goal Mode 或 Plan Mode 进行多 agent 规划、执行、验证与交付；先加载仓库根 V2.36 Skill，普通工作使用 V2.5 通用核心，仓库自发布才加载 self-release Profile。
---

# Goal Teams 仓库入口

1. 在执行任何 Goal Teams 工作前，必须完整读取仓库根 `../../../SKILL.md`。
2. 将根 `SKILL.md` 引用的所有相对路径按仓库根目录解析，不要按本 wrapper 所在目录解析。
3. 涉及 V2.3 的 Goal Teams 工作时，必须完整读取仓库根 `../../../GoalTeams-PRD-V2.3.md`，并将其作为 V2.3 scope。
4. 普通仓库维护使用根 Skill 的 `goal-teams-core-v2.5`；只有产品版本 `V2.36` 且任务类型为 `goal_teams_self_release` 时，才加载 `goal-teams-self-release-v2.36`。
5. 按根 `SKILL.md` 的流程和渐进式加载规则执行；本文件仅提供仓库作用域入口，不复制或替代根 Skill 的规则。
