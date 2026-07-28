---
type: CodeAgent Runtime Overlay
title: TRAE Overlay
description: TRAE 已确认能力与必须 fail closed 的公开契约缺口。
tags: [goal-teams, v2.47, trae]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# TRAE Overlay

- 官方已确认 Agent Skills、global/project Skills、`.agents/skills`、嵌套 Rules 与 `AGENTS.md` 能力。
- 官方公开资料未闭合 `SKILL.md` frontmatter、完整扫描根、同名优先级、手动调用语法与 Rules 限额；不得自行补齐。
- 启动必须 probe `skill_schema_fields`、实际 roots、调用方式、Rules 文件和 sandbox；任一必需事实缺失时保持 `capability_probe_required`。
- `AGENTS.md`/`AGENT.md`、`CLAUDE.md` 与 `.trae/rules` 的公开口径有差异，只报告当前版本实测识别结果。
- 未通过 probe 时只能加载 Portable Core 与正常规则，禁止生成 TRAE 特有 frontmatter 或宣称完整 adapter。
