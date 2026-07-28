---
type: CodeAgent Provider Overlay
title: GLM Provider Overlay
description: GLM Coding Plan 与实际 Agent runtime 的身份分离规则。
tags: [goal-teams, v2.47, glm]
timestamp: 2026-07-28T00:00:00+08:00
okf_version: "0.1"
---

# GLM Provider Overlay

- GLM Coding Plan 是模型/服务提供方，不是独立 Skill runtime；CodeGeeX 官方资料也未给出原生 `SKILL.md`/Rules 契约。
- 身份必须拆成 `model_provider=glm` 与 `host_runtime_id=<actual host>`；没有实际宿主时状态为 `blocked: host_runtime_required`。
- Skill roots、指令文件、调用语法、权限与渐进加载全部跟随已探测宿主；禁止建立或宣称“GLM 原生 Skill adapter”。
- 本文件只记录 provider 边界，不计入已选择 runtime overlay 数；若实际宿主为 Claude Code/Codex/Cursor 等，只加载该宿主 overlay。
