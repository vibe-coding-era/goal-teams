---
type: Goal Teams Function Rules
title: UI and Desktop Function
description: 定义 UI、交互、浏览器与桌面应用的条件规则和验证面。
tags: [goal-teams, v2.49, ui, desktop, e2e]
timestamp: 2026-08-01T00:00:00+08:00
okf_version: "0.1"
---

# UI and Desktop Function

- `function_id`: `FUNCTION-UI-DESKTOP-V249`
- `purpose`: 拥有 UI、页面状态、交互、浏览器与桌面应用的条件规则和可观察验证面。

## trigger_and_exclusion_facts

- 触发：用户可见页面、交互状态、视觉复刻、浏览器行为或桌面运行时发生变化。
- 排除：无 UI 影响的后端、规则或文档任务不加载本功能；像素比较只在可信视觉基线和复刻目标存在时启用。

## inputs

- 页面/组件清单、状态矩阵、设计基线、目标环境、输入设备和 runtime capability。

## obligations_and_outputs

- 定义页面规格、组件状态、交互路径、错误/空/加载态和适用 E2E。
- 视觉复刻使用组件级视觉合同、截图和像素差；一般 UI 变化不自动升级为视觉复刻。
- Desktop/Computer Use 只能按宿主实测 capability 声明执行能力。

## oracles_and_evidence

- DOM/可访问状态、真实交互回读、截图、像素差、窗口/平台信息和失败 artifact。

## contract_refs

- `CONTRACT-TEST-CASE-GATE-V249`
- `CONTRACT-HARNESS-EVIDENCE-V249`

## dependencies

- `FUNCTION-REQUIREMENTS-V249`
- `FUNCTION-TESTING-V249`
- `FUNCTION-AGENT-RUNTIME-V249`

## owned_rule_ids

- `GT249-UI-TRIGGER`: 只有实际 UI/交互影响才加载页面与 E2E 规则；存在前端文件本身不构成触发事实。
- `GT249-UI-STATE-MATRIX`: 页面规格必须覆盖正常、加载、空、错误、禁用、权限和关键 overlay 状态，并把 AC 映射到可观察断言。
- `GT249-UI-E2E`: E2E 必须通过真实交互与回读验证行为，不能只检查静态文本、模拟器或生成文件。
- `GT249-UI-PIXEL`: 只有视觉复刻 route 才要求基线截图、组件视觉锁、像素差和平台归一化 Evidence。
- `GT249-DESKTOP-CAPABILITY`: Browser、Computer Use、Playwright 和桌面控制能力分别按当前宿主观测报告；资料或 manifest 不等于实机能力。
