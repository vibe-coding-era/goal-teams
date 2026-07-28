---
type: CodeAgent Runtime Overlay
title: Codex Overlay
description: Codex 的 Skill、AGENTS.md、rules 与权限差异。
tags: [goal-teams, v2.47, codex]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# Codex Overlay

- Skill roots：项目 `.agents/skills/`、用户 `$CODEX_HOME/skills`、管理员 `/etc/codex/skills`；显式调用为 `$goal-teams`。
- 项目指令按根到 CWD 的 `AGENTS.override.md`/`AGENTS.md` 层级组合，更近目录覆盖；项目 Skill 从 CWD 向仓库根发现。
- `agents/openai.yaml`、`.rules` 是 Codex 方言，不得投影到其他宿主；多条命令规则取最严格决策。
- Skill metadata、规则和 MCP dependency 均不授予权限；执行仍受 sandbox、approval、网络与当前工具约束。
- 官方合同已映射，但当前环境 adapter 验证未由该文件完成，状态保持 `contract_mapped_not_runtime_verified`。
