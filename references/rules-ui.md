---
type: Goal Teams UI Rules
title: Goal Teams UI Rules
description: UI 页面、复刻、截图对齐、HTML Prototype MOCK 和视觉证据的条件规则。
tags: [goal-teams, ui, e2e, pixel-diff, okf]
timestamp: 2026-07-09T00:00:00+08:00
okf_version: "0.1"
---

# Goal Teams UI Rules

只在任务涉及 UI 页面、HTML Prototype、静态页面 MOCK、动态前端页面、浏览器工作流、截图对齐、复刻、还原、临摹或视觉验收时读取本文件。

## 必读文件

- `references/ui-visual-contract-protocol.md`
- `references/ui-e2e-pixel-protocol.md`
- `prompts/packets/page-spec-card.md`
- `prompts/packets/html-prototype-mock.md`
- `references/google-okf-bilingual-spec.md`

## 规划规则

- UI 页面、复刻、还原、截图对齐或前端交互页面必须在 PRD 后生成或更新 `spec/page-spec-card.md`；非 UI 任务写 `not_applicable_reason`。
- 页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面任务，若未提供组件库名称、版本、URL 或 Git 仓库，必须先澄清；已提供时写入 `memory.md`、`page-spec-card.md` 和 HTML OKF 元数据。
- 页面规格卡必须在 OKF 头部记录组件库名称、版本和来源；每个用户可见元素都要记录组件库归属，有数据模型的组件还要记录数据模型或 mock 引用。
- HTML 原型 MOCK 必须用注释、`application/okf+yaml` 或 `data-*` 属性记录组件库信息，并能被 Harness 检查。

## 视觉证据规则

- 任何界面级任务都必须有 E2E Harness，覆盖关键用户路径、主要 viewport、控制台错误和可见状态；不能执行 E2E 时不得标记完成。
- 复刻、临摹、还原、对照参考图或参考页面的界面任务必须截图并做像素级对比；缺少可比较参考时记录阻塞或 `not_applicable_reason`。
- 使用视觉锁层、baseline overlay 或截图遮挡层时，不能只用锁层截图作为通过证据；必须同时提供 locked screenshot 和 unlocked real DOM screenshot。
- 关键组件必须有组件级视觉契约和可执行断言；头像、图标、小按钮等小组件必须有局部 crop 或几何断言。
- 弹窗、表单、菜单、头像、表格、分页等用户可见组件必须覆盖至少一个交互态证据；弹窗必须覆盖打开态、错误态、切换态、关闭态和移动端态。
- 独立 Reviewer 和 Completion Auditor 必须检查证据是否覆盖已知视觉风险，而不只是检查证据是否存在。

## 推荐 Harness

| 检查 | 证据 |
| --- | --- |
| E2E 用户路径 | Playwright、Browser 或 Chrome 运行日志 |
| viewport | desktop、tablet、mobile 截图 |
| console/network | 控制台错误、关键请求状态 |
| pixel diff | baseline、actual、diff 图和 changed ratio/MAE |
| 局部组件 | crop、bbox、宽高、可见性、状态切换截图 |
| 组件库元数据 | OKF frontmatter、`application/okf+yaml`、`data-component-library` |

## 可用工具

- 像素对比优先执行 `scripts/harness/pixel-diff.py`；兼容入口见 `references/compat.md`。
