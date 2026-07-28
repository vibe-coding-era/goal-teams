---
type: CodeAgent Runtime Overlay
title: Qoder Overlay
description: Qoder Skills、Rules、edition 路径与权限差异。
tags: [goal-teams, v2.47, qoder]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Qoder Overlay

- Skill roots：项目 `.qoder/skills/`、用户 `~/.qoder/skills/`；显式调用 `/goal-teams`，且 User Skill > Project Skill。
- 必须先探测国际版或 CN edition，再选择 `~/.qoder/` 或 `~/.qoder-cn/`；两套根不得混用。
- `AGENTS.md`、`AGENTS.local.md` 与 `.qoder/rules/**/*.md` 承载上下文；Rules 的 `paths` 和子目录文件访问支持按需加载。
- Rules 优先级与 Skill 优先级不可互换；permissions/hooks 才能提供强制边界，`--yolo` 会跳过权限检查。
- 当前只声明官方合同映射，实际发现、权限和 Evidence smoke 未通过前不得声称完整 adapter。
