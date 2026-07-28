---
type: CodeAgent Runtime Overlay
title: Cursor Overlay
description: Cursor Skills、Project Rules、AGENTS.md 与 CLI permissions 差异。
tags: [goal-teams, v2.47, cursor]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Cursor Overlay

- Skill roots：`.agents/skills/`、`.cursor/skills/` 及对应用户目录；显式调用为 `/goal-teams`。
- 项目规则使用 `.cursor/rules/**/*.mdc`；普通 `.md` 不能冒充 `.mdc` 规则。根与嵌套 `AGENTS.md` 按目录作用域合并。
- Skill 的 `paths`、`disable-model-invocation`、`metadata` 是 Cursor 方言；共同 `SKILL.md` 不复制这些字段。
- CLI 权限由全局或项目 CLI 配置控制，deny 优先；Skill 与文字规则不能代替权限拒绝。
- 编辑器、CLI 与其他 surface 不互相外推；当前状态为 `contract_mapped_not_runtime_verified`。
