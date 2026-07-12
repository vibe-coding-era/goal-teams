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
- `ui_mode=replica` 时读取 `references/ui-e2e-pixel-protocol.md`
- 新页面、跨页面状态或 prototype 时读取 `prompts/packets/page-spec-card.md`；生成 HTML Prototype 时再读 `prompts/packets/html-prototype-mock.md` 与 `references/google-okf-bilingual-spec.md`

## 规划规则

- UI 不再自动使用 `profile=full`。small/low-risk 的原创 UI 局部改动可为 lite，medium 或含 backend/API 的原创 UI 为 standard；复刻、还原、截图对齐或 reference-driven UI 至少 full，高风险覆盖升级 regulated。
- 新 UI 页面、复刻、跨页面状态或重要交互变化必须在 PRD 后生成或更新 `spec/page-spec-card.md`；已有页面的 lite 局部样式/文案/单组件行为修正可引用既有规格和 locked scope，不强制重建整页规格卡。
- 页面原型、HTML Prototype MOCK、静态页面 MOCK 或动态前端页面任务，若未提供组件库名称、版本、URL 或 Git 仓库，必须先澄清；已提供时写入 `memory.md`、`page-spec-card.md` 和 HTML OKF 元数据。
- 页面规格卡必须在 OKF 头部记录组件库名称、版本和来源；每个用户可见元素都要记录组件库归属，有数据模型的组件还要记录数据模型或 mock 引用。
- HTML 原型 MOCK 必须用注释、`application/okf+yaml` 或 `data-*` 属性记录组件库信息，并能被 Harness 检查。

## 视觉证据规则

- 任何界面级任务都必须有可执行 browser Harness 和真实 DOM/可见状态 Evidence。Lite 可只覆盖受影响关键路径和目标 viewport；Standard 覆盖受影响路径、控制台错误与适用 viewport；Full/Regulated 覆盖完整关键路径和主要 viewport。无法执行当前等级 required 的 browser check 时不得标记完成。
- 原创 UI 不要求外部参考图或 pixel baseline；使用真实 DOM screenshot、可见状态、几何/可访问性断言验证设计目标，缺参考图不构成 blocked。
- 只有 `ui_mode=replica` 的复刻、临摹、还原、对照参考图/页面任务才必须做像素级对比；缺少可比较参考、环境指纹或独立 baseline approval 时保持 blocked。若用户把目标改为原创 UI 或非 UI/`sample_only`，必须记录范围 revision 并重新路由，不能用 waiver 假装 replica 已通过。
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
| pixel diff（仅 replica） | baseline、actual、diff 图、环境指纹、独立 baseline approval 和 changed ratio/MAE |
| 局部组件 | crop、bbox、宽高、可见性、状态切换截图 |
| 组件库元数据 | OKF frontmatter、`application/okf+yaml`、`data-component-library` |

## 可用工具

- 原创 UI 默认不调用 pixel diff；如团队自选内部截图回归，只能作为附加证据，不能把同一张图当成 reference baseline。
- replica/reference-driven UI 的像素对比执行 `scripts/harness/pixel-diff.py --ui-mode replica`，并强制不同 baseline/actual、环境指纹与独立 baseline approval；兼容入口见 `references/compat.md`。
