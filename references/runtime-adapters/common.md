---
type: CodeAgent Runtime Common Rules
title: Goal Teams V2.47 CodeAgent Portable Core
description: 所有宿主共享的最小 Skill、能力和渐进加载边界。
tags: [goal-teams, v2.47, codeagent, portable-core]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# CodeAgent Portable Core

1. 根 `SKILL.md` 只把 `name`、`description` 视为跨宿主可移植 frontmatter；任何扩展字段必须留在对应 runtime overlay。
2. 先探测 `runtime_id`、`surface`、`version`、Skill roots、指令文件、权限、sandbox、subagent 与 Evidence 能力；品牌名、模型名和文件存在本身都不是能力证明。
3. 固定加载顺序：Portable Core → 正常规则 → 本文件 → 一个 runtime overlay → 当前任务动态尾部。未知 runtime、多个冲突 runtime 或 overlay 数量不等于一时 fail closed。
4. `SKILL.md`、`AGENTS.md`、`CLAUDE.md`、Rules 只承载指令，不能授予 shell、文件、网络、MCP、subagent 或外部写权限。
5. Stable Contract Prefix 不含用户、task、run、路径或 Evidence 值；项目目标、增量 fragment 和本轮状态只放 Dynamic Instance Tail。
6. 完整 adapter 必须分别验证发现、规则优先级、显式/隐式调用、权限拒绝、脚本执行、subagent 独立性和 Evidence 回传；未闭合时只能报告 manifest-bounded compatibility。
