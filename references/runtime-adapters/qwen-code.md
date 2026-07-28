---
type: CodeAgent Runtime Overlay
title: Qwen Code Overlay
description: Qwen Code 的 Skill、QWEN.md、paths 与 approval 差异。
tags: [goal-teams, v2.47, qwen-code]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Qwen Code Overlay

- Skill roots：项目 `.qwen/skills/`、用户 `~/.qwen/skills/`；显式调用为 `/goal-teams`。
- 长期指令按 `~/.qwen/QWEN.md`、项目 `QWEN.md`、`.qwen/QWEN.local.md` 加载，并兼容 `AGENTS.md`；引用文件须按当前文档相对解析。
- `priority` 仅排序；`paths`、`user-invocable`、`disable-model-invocation` 是 Qwen 方言。path-gated Skill 在访问匹配文件后才进入模型可见集。
- `/approval-mode plan`、safe mode、auto/yolo 与 sandbox 是独立执行事实；Skill 不提供授权。
- 同名跨作用域优先级官方未完整定义，发生冲突时 capability probe 或 fail closed。
