---
type: CodeAgent Runtime Overlay
title: Kimi Code Overlay
description: Kimi Code 的 Skill roots、AGENTS.md、调用语法与权限差异。
tags: [goal-teams, v2.47, kimi-code]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Kimi Code Overlay

- Skill roots：项目 `.kimi-code/skills/`、`.agents/skills/`，用户 `$KIMI_CODE_HOME/skills`、`~/.agents/skills`；显式调用为 `/skill:goal-teams`。
- 同名优先级是 Project > User > Extra > Built-in；`--skills-dir` 会替换自动发现目录，必须记录启动事实。
- Kimi 方言 `type`、`whenToUse`、`disableModelInvocation`、`arguments` 只在本 overlay 解释；公共入口只用 `name`、`description`。
- 项目/子目录 `AGENTS.md` 按相关范围加载；旧 `~/.kimi/` 与当前 `$KIMI_CODE_HOME` 不得静态混用。
- `--plan` 只是偏向只读，`--yolo` 跳过常规审批；安全边界必须以实际工具/权限 probe 为准。
