---
type: CodeAgent Runtime Overlay
title: Claude Code Overlay
description: Claude Code 的 Skill、CLAUDE.md、Rules 与方言字段。
tags: [goal-teams, v2.47, claude-code]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Claude Code Overlay

- Skill roots：项目 `.claude/skills/`、用户 `~/.claude/skills/`；显式调用为 `/goal-teams`。
- Claude Code 不原生把 `AGENTS.md` 当项目指令；只允许用薄 `CLAUDE.md` 的 `@AGENTS.md` 导入或受控链接，公共规则仍以 `AGENTS.md` 为 SSOT。
- `.claude/rules/**/*.md` 可用 `paths` 按需加载；祖先到 CWD 的 `CLAUDE.md` 依次组合。
- `allowed-tools`、`context: fork`、`agent`、Skill shell expansion 是 Claude 方言；CLI 与 SDK 的授权语义不同，必须按 surface 探测。
- 当前只声明 `contract_mapped_not_runtime_verified`，不得把官方原生能力写成 Goal Teams 完整 adapter 已通过。
