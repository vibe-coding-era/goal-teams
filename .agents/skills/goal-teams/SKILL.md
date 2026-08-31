---
name: goal-teams-repo
description: Goal Teams V2.67 输出控制与 Graph Engineering 仓库入口；从 ACTIVE generation 加载 Current 规则，Legacy 仅显式 Replay。
---

# Goal Teams 仓库入口

完整读取仓库根 `../../../SKILL.md`，并以仓库根解析其中路径。默认只加载 `references/current/ACTIVE.json` 指向的 Current generation；只有用户明确要求历史复盘且提供 `replay_version` 时，才进入 `references/legacy-replay/manifest.json` 的隔离 Replay。
